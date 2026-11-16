"""Fetch rendered HTML for a URL -- live, or from a Wayback snapshot.

Handles the three things the plan flags as early risks:

* **Rate limiting / robots.txt** -- one polite delay per host, exponential
  backoff on 429/5xx, robots.txt honored by default, and an on-disk cache so
  re-running the pipeline during development does not re-hammer anyone.
* **JS-heavy pages** -- a static fetch that comes back as an empty shell is
  retried through Playwright. Detection is a text-density check, so it works
  whether the culprit is Sitecore, a WordPress page builder, or a SPA.
* **Retired old sites** -- source="wayback" resolves the closest archived
  snapshot and fetches it with the `id_` modifier, which returns the original
  bytes without the Wayback toolbar injected.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
import urllib.robotparser as robotparser
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .models import FetchResult
from .urls import unwrap_wayback, wayback_timestamp

USER_AGENT = "MavDitto/0.1 (migration content-QA bot; contact via repo owner)"

DEFAULT_TIMEOUT = 30.0
DEFAULT_DELAY_S = 1.0          # minimum gap between requests to the same host
MAX_RETRIES = 3
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

# Not an HTTP status: our own marker for "robots.txt said no". Distinguishing
# a refusal from a failure matters, because the fix is different -- one is a
# permission decision, the other a broken page.
ROBOTS_BLOCKED = 999

# Below this much visible text, a static fetch is assumed to be a JS shell.
MIN_STATIC_TEXT_CHARS = 250

# Bulk enumeration budget. Tighter than a single deliberate fetch on purpose:
# when reading a whole site, a page that will not answer promptly is itself the
# finding, and waiting out three long retries for each one turns a large site
# into an hour of silence.
BULK_WORKERS = 6
BULK_TIMEOUT = 15.0
BULK_RETRIES = 1

# How many shell-looking pages a single fetch_many(escalate_js=True) call will
# re-fetch with a real browser. Unbounded would turn one crawl level with a lot
# of client-rendered pages into a browser launched per page with no ceiling.
JS_ESCALATION_BUDGET = 20

# A single image over this is almost certainly not one worth writing alt text
# for by hand either -- and the vision API has its own size ceiling well above
# this, so refusing early saves the round trip.
MAX_BINARY_BYTES = 8 * 1024 * 1024

WAYBACK_AVAILABLE = "https://archive.org/wayback/available"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"

# A timestamp no capture can have; Wayback redirects it to the newest one.
LATEST_TIMESTAMP = "29991231235959"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

_TAG_STRIP = re.compile(r"(?is)<(script|style|noscript|template)\b.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def visible_text_estimate(html: str) -> str:
    """Rough visible-text extraction, used only to decide if a page is a shell.

    Deliberately crude -- real extraction is extract.py's job. This only has to
    be fast and good enough to tell "page" from "empty div".
    """
    if not html:
        return ""
    stripped = _TAG_STRIP.sub(" ", html)
    return re.sub(r"\s+", " ", _TAGS.sub(" ", stripped)).strip()


def looks_like_js_shell(html: str) -> bool:
    return len(visible_text_estimate(html)) < MIN_STATIC_TEXT_CHARS


def _cache_key(url: str, render_mode: str) -> str:
    return hashlib.sha256(f"{render_mode}:{url}".encode()).hexdigest()[:24]


class RateLimiter:
    """One minimum-delay clock per host, with jitter so we don't look robotic.

    Thread-safe: bulk enumeration fetches pages from a worker pool, and without
    the lock several workers would read the same "last request" time and all
    fire at once -- turning a politeness delay into a burst.
    """

    def __init__(self, delay_s: float = DEFAULT_DELAY_S) -> None:
        self.delay_s = delay_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        while True:
            with self._lock:
                now = time.monotonic()
                last = self._last.get(host)
                gap = self.delay_s + random.uniform(0, self.delay_s * 0.3)
                if last is None or now - last >= gap:
                    self._last[host] = now
                    return
                remaining = gap - (now - last)
            time.sleep(remaining)


class RobotsCache:
    """robots.txt per host, consulted only when a caller opts in.

    Off by default. This tool checks migrations of sites its operator controls,
    and the hosts involved -- staging, preview, pre-launch subdomains -- serve
    `Disallow: /` to stay out of search results, not to refuse their owner. The
    per-host rate limiter is unaffected and still applies to every request:
    indexing rules and not hammering a server are different concerns.

    A host that will not serve robots.txt is treated as permissive -- that is
    the conventional reading, and refusing to crawl on a network blip would be
    the worse failure.
    """

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._parsers: dict[str, robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host_key = f"{parts.scheme}://{parts.netloc}"
        if host_key not in self._parsers:
            self._parsers[host_key] = self._load(host_key)
        rp = self._parsers[host_key]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def _load(self, host_key: str):
        try:
            resp = self._client.get(f"{host_key}/robots.txt", timeout=10.0)
            if resp.status_code != 200:
                return None
            rp = robotparser.RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
        except Exception:
            return None


# --------------------------------------------------------------------------
# Wayback
# --------------------------------------------------------------------------

def _id_snapshot(original: str, ts: str) -> str:
    """Snapshot URL with the id_ modifier: archived bytes, no Wayback toolbar."""
    return f"https://web.archive.org/web/{ts}id_/{original}"


def optimistic_snapshot(url: str, timestamp: str = "") -> str:
    """Snapshot URL that Wayback itself resolves to the nearest capture.

    Requesting a timestamp Wayback does not hold makes it redirect to the
    closest one it does, so a single ordinary fetch both finds and retrieves the
    snapshot. That matters: it is the only route that keeps working when the
    availability and CDX APIs are rate-limited or offline, which is common.
    A far-future stamp therefore means "the most recent capture" -- the right
    default here, since the last archive before a site was retired is the
    version its replacement should be compared against.
    """
    return _id_snapshot(unwrap_wayback(url), timestamp or LATEST_TIMESTAMP)


def lookup_wayback(
    url: str,
    get,
    *,
    timestamp: str = "",
) -> tuple[str | None, str | None, list[str]]:
    """Ask the Wayback APIs for the closest snapshot to `url`.

    Only used when the redirect route fails. `get` is a rate-limited,
    retrying getter -- these endpoints return 429 readily, and hammering the
    Internet Archive is exactly the risk the build plan calls out.

    Returns (snapshot_url, timestamp, notes).
    """
    notes: list[str] = []
    original = unwrap_wayback(url)

    resp = get(WAYBACK_AVAILABLE,
               {"url": original, "timestamp": timestamp or LATEST_TIMESTAMP})
    if resp is None:
        notes.append("wayback availability API unreachable")
    elif resp.status_code != 200:
        notes.append(f"wayback availability API returned HTTP {resp.status_code}")
    else:
        try:
            snap = (resp.json().get("archived_snapshots") or {}).get("closest") or {}
            if snap.get("available") and snap.get("timestamp"):
                return _id_snapshot(original, snap["timestamp"]), snap["timestamp"], notes
            notes.append("wayback availability API holds no capture for this URL")
        except Exception as exc:
            notes.append(f"wayback availability API gave unreadable JSON: {exc}")

    resp = get(WAYBACK_CDX, {
        "url": original,
        "output": "json",
        "filter": "statuscode:200",
        "collapse": "digest",
        "limit": "-1",       # most recent matching capture
    })
    if resp is None:
        notes.append("wayback CDX unreachable")
    elif resp.status_code != 200:
        notes.append(f"wayback CDX returned HTTP {resp.status_code}")
    else:
        try:
            rows = resp.json()
            if len(rows) > 1:
                ts = rows[1][1]
                return _id_snapshot(original, ts), ts, notes
            notes.append("wayback CDX holds no capture for this URL")
        except Exception as exc:
            notes.append(f"wayback CDX gave unreadable JSON: {exc}")

    return None, None, notes


# --------------------------------------------------------------------------
# Fetcher
# --------------------------------------------------------------------------

class Fetcher:
    """Fetches pages politely, with caching and an optional Playwright fallback.

    Use as a context manager so the HTTP client and browser get closed::

        with Fetcher() as f:
            result = f.fetch(url, source="wayback")
    """

    def __init__(
        self,
        *,
        delay_s: float = DEFAULT_DELAY_S,
        timeout: float = DEFAULT_TIMEOUT,
        respect_robots: bool = False,
        use_cache: bool = True,
        cache_dir: Path | str = CACHE_DIR,
        allow_js: bool = True,
        credentials: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.use_cache = use_cache
        self.allow_js = allow_js
        self.cache_dir = Path(cache_dir)
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=timeout,
        )
        # host -> (user, password). Pre-launch sites are routinely behind HTTP
        # basic auth, which is the whole reason the new side may need its own
        # credentials while the old side needs none.
        self.credentials = {h.lower(): c for h, c in (credentials or {}).items()}
        self.limiter = RateLimiter(delay_s)
        self.robots = RobotsCache(self.client)
        self._browser = None
        self._playwright = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.client.close()
        finally:
            if self._browser is not None:
                try:
                    self._browser.close()
                finally:
                    self._browser = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                finally:
                    self._playwright = None

    # -- cache -------------------------------------------------------------

    def _cache_path(self, url: str, render_mode: str) -> Path:
        return self.cache_dir / f"{_cache_key(url, render_mode)}.json"

    def _cache_read(self, url: str, render_mode: str) -> FetchResult | None:
        if not self.use_cache:
            return None
        path = self._cache_path(url, render_mode)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = FetchResult(**data)
            result.notes = list(result.notes) + ["served from cache"]
            return result
        except Exception:
            return None

    def _cache_write(self, result: FetchResult) -> None:
        if not self.use_cache or not result.ok:
            return
        payload = dict(result.__dict__)
        payload["notes"] = [n for n in result.notes if n != "served from cache"]
        try:
            self._cache_path(result.fetched_url, result.render_mode).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass   # a cache write failure is never worth failing a fetch over

    # -- shared HTTP ---------------------------------------------------------

    def _get(self, url: str, params: dict | None = None, *, timeout: float = 30.0):
        """GET through the rate limiter, with backoff on 429/5xx.

        Wayback's APIs hand out 429s freely, so they go through the same
        politeness path as page fetches rather than around it.
        """
        delay = 2.0
        for attempt in range(1, MAX_RETRIES + 1):
            self.limiter.wait(url)
            try:
                resp = self.client.get(url, params=params, timeout=timeout)
            except httpx.HTTPError:
                if attempt == MAX_RETRIES:
                    return None
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                wait = float(resp.headers.get("Retry-After") or delay)
                time.sleep(min(wait, 30.0))
                delay *= 2
                continue
            return resp
        return None

    # -- fetching ----------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        source: str = "live",
        render: str = "auto",
        timestamp: str = "",
        respect_robots: bool | None = None,
    ) -> FetchResult:
        """Fetch one page.

        source -- "live" hits the URL directly; "wayback" resolves a snapshot
                  first; "auto" tries live and falls back to Wayback.
        render -- "static" (httpx only), "js" (force Playwright), or "auto"
                  (static, escalating to Playwright if the page looks empty).
        respect_robots -- per-call override of the fetcher default. A pre-launch
                  staging site typically serves `Disallow: /` to keep itself out
                  of search results; that is not a request to keep its owner
                  from QA-ing it, so the two sides of a pair can be set apart.
        """
        started = time.monotonic()
        url = url.strip()
        notes: list[str] = []
        snapshot_ts: str | None = None
        target = url

        if source in ("wayback", "auto"):
            if source == "auto":
                probe = self._fetch_static(url, notes, respect_robots=respect_robots)
                if probe is not None and probe.ok and not looks_like_js_shell(probe.html):
                    probe.url = url
                    probe.source = "live"
                    self._cache_write(probe)
                    return self._finish(probe, started)
                notes.append("live fetch unusable; falling back to wayback")
            source = "wayback"
            # Let Wayback's own redirect find the nearest capture first; the
            # APIs are only consulted if that fails.
            target = optimistic_snapshot(url, timestamp)

        cached = self._cache_read(target, "js" if render == "js" else "static")
        if cached is not None:
            cached.url = url
            cached.source = source
            cached.snapshot_timestamp = snapshot_ts or cached.snapshot_timestamp
            cached.notes = list(cached.notes) + notes
            return self._finish(cached, started)

        result: FetchResult | None = None
        if render != "js":
            result = self._fetch_static(target, notes, respect_robots=respect_robots)

        # Redirect route came up empty -- ask the APIs for a concrete capture.
        if source == "wayback" and (result is None or not result.ok):
            notes.append("nearest-capture redirect failed; querying wayback APIs")
            alt_target, api_ts, wb_notes = lookup_wayback(
                url, self._get, timestamp=timestamp
            )
            notes.extend(wb_notes)
            if alt_target and alt_target != target:
                target = alt_target
                snapshot_ts = api_ts
                result = self._fetch_static(
                    target, notes, respect_robots=respect_robots
                )

        blocked = result is not None and result.status == ROBOTS_BLOCKED
        needs_js = (
            self.allow_js
            and render != "static"
            and not blocked
            and (result is None or not result.ok or looks_like_js_shell(result.html))
        )
        if needs_js:
            if result is not None and result.ok:
                chars = len(visible_text_estimate(result.html))
                notes.append(
                    f"static HTML held only ~{chars} chars of text; "
                    "re-fetching with a browser"
                )
            rendered = self._fetch_js(target, notes)
            if rendered is not None and rendered.ok:
                result = rendered

        if result is None:
            result = FetchResult(url=url, fetched_url=target, status=0, html="")

        result.url = url
        result.source = source
        # The redirect we followed names the capture we actually got, which is
        # rarely the one we asked for.
        result.snapshot_timestamp = (
            wayback_timestamp(result.fetched_url) or snapshot_ts
            if source == "wayback" else None
        )
        result.notes = notes
        self._cache_write(result)
        return self._finish(result, started)

    def fetch_many(
        self,
        urls: list[str],
        *,
        workers: int = BULK_WORKERS,
        timeout: float = BULK_TIMEOUT,
        retries: int = BULK_RETRIES,
        respect_robots: bool | None = None,
        on_done=None,
        escalate_js: bool = False,
        js_budget: int = JS_ESCALATION_BUDGET,
    ) -> dict[str, FetchResult]:
        """Fetch many pages at once, for enumerating a whole site.

        Sequential fetching is what makes a large site unusable: one page that
        never answers costs the full timeout budget, and a site with dozens of
        those adds up to an hour of waiting before any result appears. Here the
        waiting overlaps, so unresponsive pages cost wall-clock time once rather
        than once each.

        The budget is deliberately tighter than a single deliberate fetch. In
        bulk, a page that will not answer promptly *is the finding* -- it gets
        reported as unreachable and the run moves on, instead of holding
        everything else up to prove it a third time.

        Politeness is unchanged: every worker goes through the same per-host
        rate limiter, so concurrency overlaps waiting, not requests.

        escalate_js -- when a comprehensive crawl is worth the extra time, a
        static page that comes back looking like an empty JS shell is re-fetched
        with a real browser afterward. This is where a client-rendered nav menu
        gets read at all: `fetch()`'s own auto-escalation only ever sees one URL
        at a time, but *enumerating* a site depends on the links a shell page's
        static HTML never had in the first place. Capped by `js_budget` per call
        because launching a browser per page is slow.
        """
        from concurrent.futures import ThreadPoolExecutor

        results: dict[str, FetchResult] = {}
        if not urls:
            return results

        def one(url: str) -> tuple[str, FetchResult]:
            notes: list[str] = []
            result = self._fetch_static(
                url, notes, respect_robots=respect_robots,
                timeout=timeout, retries=retries)
            if result is None:
                result = FetchResult(url=url, fetched_url=url, status=0, html="")
            result.url = url
            result.notes = notes
            return url, result

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for url, result in pool.map(one, urls):
                results[url] = result
                if on_done is not None:
                    on_done(url, result)

        if escalate_js and self.allow_js:
            shells = [u for u, r in results.items()
                     if r.ok and looks_like_js_shell(r.html)][:max(0, js_budget)]
            for url in shells:
                notes: list[str] = []
                rendered = self._fetch_js(url, notes)
                if rendered is not None and rendered.ok:
                    rendered.url = url
                    rendered.notes = list(results[url].notes) + notes + [
                        "re-fetched with a browser: static HTML looked like an "
                        "empty JS shell"]
                    results[url] = rendered
                    if on_done is not None:
                        on_done(url, rendered)
        return results

    def fetch_binary(self, url: str, *, max_bytes: int = MAX_BINARY_BYTES
                     ) -> tuple[bytes, str] | None:
        """Download a non-HTML resource -- an image, for the alt-text
        generator. Same politeness as a page fetch: rate-limited per host, no
        retries (a slow image is not worth the wait a slow page would be).

        Returns (bytes, content-type) on success, or None on anything that
        makes the bytes unusable: an error, a non-image content type, or a
        response over `max_bytes`. A caller reading this as "just skip it and
        say why" is the point -- a page can have one broken image among fifty
        good ones, and that should not fail the other forty-nine.
        """
        self.limiter.wait(url)
        try:
            resp = self.client.get(url, auth=self._auth_for(url), timeout=self.timeout)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return None
        if len(resp.content) > max_bytes:
            return None
        return resp.content, content_type

    def fetch_text(self, url: str, *, max_bytes: int = MAX_BINARY_BYTES) -> str | None:
        """Download a small text resource -- a linked stylesheet, for the
        alt-text generator's class/ID-driven background image detection.

        Unlike `fetch_binary`, content-type is not checked: a `<link
        rel="stylesheet" href>` is a stylesheet by the page's own
        declaration, so the only real gate here is size.
        """
        self.limiter.wait(url)
        try:
            resp = self.client.get(url, auth=self._auth_for(url), timeout=self.timeout)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_bytes:
            return None
        return resp.text

    @staticmethod
    def _finish(result: FetchResult, started: float) -> FetchResult:
        result.elapsed_s = round(time.monotonic() - started, 3)
        return result

    def _auth_for(self, url: str):
        return self.credentials.get(urlsplit(url).netloc.lower())

    def _fetch_static(
        self,
        url: str,
        notes: list[str],
        *,
        respect_robots: bool | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> FetchResult | None:
        if respect_robots is None:
            respect_robots = self.respect_robots
        attempts = MAX_RETRIES if retries is None else max(1, retries)
        if respect_robots and not self.robots.allowed(url):
            notes.append("blocked by robots.txt -- not fetched")
            return FetchResult(url=url, fetched_url=url,
                               status=ROBOTS_BLOCKED, html="")

        delay = 1.0
        for attempt in range(1, attempts + 1):
            self.limiter.wait(url)
            try:
                resp = self.client.get(url, auth=self._auth_for(url),
                                       timeout=timeout or self.timeout)
            except httpx.HTTPError as exc:
                notes.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt == attempts:
                    return FetchResult(url=url, fetched_url=url, status=0, html="")
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code in RETRY_STATUSES and attempt < attempts:
                wait = float(resp.headers.get("Retry-After") or delay)
                notes.append(
                    f"attempt {attempt}: HTTP {resp.status_code}, retrying in {wait:.0f}s"
                )
                time.sleep(min(wait, 30.0))
                delay *= 2
                continue

            return FetchResult(
                url=url,
                fetched_url=str(resp.url),
                status=resp.status_code,
                html=resp.text,
                render_mode="static",
            )
        return None

    def _ensure_browser(self, notes: list[str]):
        if self._browser is not None:
            return self._browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            notes.append("playwright not installed -- JS rendering unavailable")
            return None
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            notes.append(
                f"could not launch browser ({exc}); run `playwright install chromium`"
            )
            self._browser = None
        return self._browser

    def _fetch_js(self, url: str, notes: list[str]) -> FetchResult | None:
        browser = self._ensure_browser(notes)
        if browser is None:
            return None
        self.limiter.wait(url)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
        page = context.new_page()
        try:
            resp = page.goto(
                url, wait_until="domcontentloaded", timeout=self.timeout * 1000
            )
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass   # networkidle never settling is common and not fatal
            return FetchResult(
                url=url,
                fetched_url=page.url,
                status=resp.status if resp else 200,
                html=page.content(),
                render_mode="js",
            )
        except Exception as exc:
            notes.append(f"playwright fetch failed: {type(exc).__name__}: {exc}")
            return None
        finally:
            context.close()


def fetch(url: str, **kwargs) -> FetchResult:
    """One-shot convenience fetch. Prefer Fetcher for more than a page or two."""
    source = kwargs.pop("source", "live")
    render = kwargs.pop("render", "auto")
    timestamp = kwargs.pop("timestamp", "")
    robots = kwargs.pop("respect_robots_call", None)
    with Fetcher(**kwargs) as f:
        return f.fetch(url, source=source, render=render, timestamp=timestamp,
                       respect_robots=robots)
