"""Enumerate every page under a site root, and pair two sites' pages together.

This is step one of the build plan, and the reason the tool can be handed two
root URLs instead of a hand-written pair list: it crawls both sites, works out
which old page became which new page, and -- the part that matters most --
names the old pages that became *nothing*.

A page that no longer exists anywhere on the new site is the worst migration
failure there is, and it is invisible to a pairwise content diff: you cannot
compare a page against its replacement when it has no replacement. Only an
enumeration of both sides can find those.

Enumeration prefers `sitemap.xml`, because a site that publishes one is telling
you what it thinks its pages are, and reading it costs a single request instead
of hundreds. Sites without a usable sitemap get a bounded same-site crawl.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from .fetch import ROBOTS_BLOCKED
from .urls import compare_key, normalize

# Endings that are never a content page, so a crawl does not chase them.
SKIP_EXTENSIONS = (
    ".css", ".js", ".json", ".xml", ".rss", ".atom", ".ico", ".png", ".jpg",
    ".jpeg", ".gif", ".svg", ".webp", ".avif", ".woff", ".woff2", ".ttf",
    ".eot", ".mp4", ".webm", ".mp3", ".wav", ".zip", ".gz",
)

# Path fragments that are plumbing rather than content.
SKIP_PATH_PARTS = (
    "/wp-json/", "/wp-admin/", "/wp-includes/", "/cgi-bin/", "/api/",
    "/feed/", "/_next/", "/static/", "/assets/", "/cdn-cgi/",
)

# CMS extensions stripped before comparing paths, so Sitecore's /About.aspx
# lines up with WordPress's /about/.
PAGE_EXTENSIONS = (".aspx", ".asp", ".html", ".htm", ".php", ".jsp", ".cfm")

DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_DEPTH = 6

# Below this path similarity two pages are not the same page renamed.
PATH_MATCH_RATIO = 0.72
TITLE_MATCH_RATIO = 0.80

# A title carried by more than this share of a site's pages names the *site*,
# not the page. Single-page apps and site builders routinely serve one static
# <title> for every route, and matching on it would pair every old page with
# whichever new page happened to be compared first.
DISTINCTIVE_SHARE = 0.4

# When an old page's two best candidates score within this of each other, there
# is no evidence to choose between them. Picking one anyway is a coin flip
# presented as a finding, and a wrong pair is worse than an honest "unmatched":
# it sends a reviewer to compare two unrelated pages.
AMBIGUITY_MARGIN = 0.02

_WORDS = re.compile(r"[^a-z0-9]+")


@dataclass
class PageRef:
    """One page found under a site root."""

    url: str
    path: str = ""          # relative to the root, normalized for comparison
    title: str = ""
    heading: str = ""       # first h1; the identity signal when titles repeat
    source: str = ""        # "sitemap" | "crawl"
    depth: int = 0

    @property
    def label(self) -> str:
        """Whatever names this page. Set by `choose_label_signal`."""
        return self._label or self.title or self.heading

    _label: str = ""

    @property
    def slug(self) -> str:
        return self.path.rstrip("/").rsplit("/", 1)[-1] if self.path else ""


@dataclass
class SiteInventory:
    """Every page found under one root."""

    root: str
    pages: list[PageRef] = field(default_factory=list)
    method: str = ""
    notes: list[str] = field(default_factory=list)
    # How many fetches robots.txt refused. A site that blocks everything yields
    # an empty inventory, which is indistinguishable from an empty site unless
    # the reason is carried along.
    blocked: int = 0
    # Pages the site lists but will not serve. A finding in its own right on
    # either side: on the new site they are broken links a visitor will hit,
    # and on the old site they are pages whose content cannot be checked.
    unreachable: list[PageRef] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.pages)

    def by_path(self) -> dict[str, PageRef]:
        return {p.path: p for p in self.pages}


@dataclass
class PagePairing:
    """One old page and the new page it became, with how that was decided."""

    old: PageRef
    new: PageRef
    method: str             # exact | slug | fuzzy-path | title
    confidence: float


@dataclass
class MatchReport:
    pairs: list[PagePairing] = field(default_factory=list)
    unmatched_old: list[PageRef] = field(default_factory=list)
    unmatched_new: list[PageRef] = field(default_factory=list)
    unreachable_old: list[PageRef] = field(default_factory=list)
    unreachable_new: list[PageRef] = field(default_factory=list)
    label_signals: tuple[str, str] = ("", "")

    @property
    def migrated_share(self) -> float:
        total = len(self.pairs) + len(self.unmatched_old)
        return len(self.pairs) / total if total else 1.0


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def root_path(root: str) -> str:
    path = urlsplit(normalize(root)).path.rstrip("/")
    return path


def relative_path(url: str, root: str) -> str | None:
    """The page's path relative to its site root, normalized for comparison.

    Returns None when the URL is not under the root at all -- a sitemap often
    lists pages outside the subsite you asked about, and pairing those would be
    comparing two sites nobody asked to compare.
    """
    parts = urlsplit(normalize(url))
    root_parts = urlsplit(normalize(root))
    if parts.netloc != root_parts.netloc:
        return None

    path = parts.path
    base = root_path(root)
    if base:
        if not path.lower().startswith(base.lower()):
            return None
        path = path[len(base):]

    low = path.lower()
    for ext in PAGE_EXTENSIONS:
        if low.endswith(ext):
            path = path[: -len(ext)]
            break
    path = "/" + path.strip("/").lower()
    return path


def is_content_url(url: str) -> bool:
    low = urlsplit(url).path.lower()
    if any(low.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    return not any(part in low + "/" for part in SKIP_PATH_PARTS)


# --------------------------------------------------------------------------
# enumeration
# --------------------------------------------------------------------------

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_IS_INDEX = re.compile(r"<sitemapindex", re.IGNORECASE)


DEEP_SITEMAP_RECURSION = 4
DEEP_SITEMAP_CHILDREN = 200


def sitemap_candidates(root: str, fetcher, *, deep: bool = False) -> list[str]:
    """Where a site might publish its sitemap, best guess first.

    robots.txt is consulted because that is where a site declares one that is
    not at the conventional path. In deep mode, also try the path variants a
    handful of common CMSes use instead of the plain default -- WordPress 5.5+
    ships `/wp-sitemap.xml` unprompted, and several static-site generators
    split content into `/page-sitemap.xml` / `/post-sitemap.xml`.
    """
    parts = urlsplit(normalize(root))
    origin = f"{parts.scheme}://{parts.netloc}"
    found: list[str] = []
    try:
        response = fetcher._get(f"{origin}/robots.txt", timeout=15.0)
        if response is not None and response.status_code == 200:
            found += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", response.text)
    except Exception:
        pass
    guesses = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
    if deep:
        guesses += ["/wp-sitemap.xml", "/sitemapindex.xml", "/sitemap1.xml",
                    "/page-sitemap.xml", "/post-sitemap.xml",
                    "/sitemap/sitemap.xml", "/sitemaps.xml"]
    for path in guesses:
        if origin + path not in found:
            found.append(origin + path)
    return found


def read_sitemap(url: str, fetcher, *, depth: int = 0, seen: set[str] | None = None,
                 max_recursion: int = 2, max_children: int = 50) -> list[str]:
    """Every <loc> in a sitemap, following sitemap indexes down to `max_recursion`."""
    seen = seen if seen is not None else set()
    if url in seen or depth > max_recursion:
        return []
    seen.add(url)

    response = fetcher._get(url, timeout=30.0)
    if response is None or response.status_code != 200:
        return []
    body = response.text
    locations = _LOC.findall(body)
    if not locations:
        return []

    if _IS_INDEX.search(body):
        nested: list[str] = []
        for child in locations[:max_children]:
            nested += read_sitemap(child, fetcher, depth=depth + 1, seen=seen,
                                   max_recursion=max_recursion,
                                   max_children=max_children)
        return nested
    return locations


def from_sitemap(root: str, fetcher, *, deep: bool = False) -> tuple[list[str], str]:
    max_recursion = DEEP_SITEMAP_RECURSION if deep else 2
    max_children = DEEP_SITEMAP_CHILDREN if deep else 50
    for candidate in sitemap_candidates(root, fetcher, deep=deep):
        locations = read_sitemap(candidate, fetcher, max_recursion=max_recursion,
                                 max_children=max_children)
        if locations:
            return locations, candidate
    return [], ""


def crawl(root: str, fetcher, *, max_pages: int = DEFAULT_MAX_PAGES,
          max_depth: int = DEFAULT_MAX_DEPTH,
          respect_robots: bool | None = None,
          deep: bool = False, retry_failed: bool = True,
          ) -> tuple[list[tuple[str, int, str]], list[str], list[str]]:
    """Breadth-first walk of everything reachable under `root`.

    A whole depth level is fetched at once rather than page by page, so a site
    with unresponsive pages costs one timeout for the level instead of one per
    page. Sequential crawling is what turns a large site into an hour of
    waiting before anything is reported.

    Bounded on purpose: an unbounded crawl of someone's site is a denial of
    service with good intentions. It stays on one host, stays under the root
    path, and stops at the page and depth caps.

    deep -- also re-fetches, with a real browser, any page whose static HTML
    looks like an empty JS shell, so a client-rendered nav menu is read rather
    than silently contributing zero links.

    retry_failed -- a page that timed out once is given a single second
    attempt after the whole crawl finishes, rather than being written off
    immediately. A slow server that recovers mid-crawl should not cost a page
    its "reachable" status just because of when it happened to be fetched.

    Returns (pages, unreachable_urls, notes, robots_blocked_urls); each page is
    (url, depth, title).
    """
    from .extract import extract, harvest_links

    notes: list[str] = []
    unreachable: list[str] = []
    blocked: list[str] = []
    start = normalize(root)
    level: list[str] = [start]
    seen: set[str] = {compare_key(start)}
    found: list[tuple[str, int, str]] = []

    for depth in range(max_depth + 1):
        if not level or len(found) >= max_pages:
            break
        batch = level[: max(0, max_pages - len(found))]
        results = fetcher.fetch_many(batch, respect_robots=respect_robots,
                                     escalate_js=deep)

        next_level: list[str] = []
        for url in batch:
            result = results.get(url)
            if result is None or not result.ok:
                if result is not None and result.status == ROBOTS_BLOCKED:
                    blocked.append(url)
                unreachable.append(url)
                continue
            page = extract(result.html, url, fetched_url=result.fetched_url)
            found.append((url, depth, page.title))
            if depth >= max_depth:
                continue
            # Every link in the document, not just the ones inside the main
            # content: a site's navigation is how it exposes its pages.
            for link in harvest_links(result.html, url,
                                      fetched_url=result.fetched_url):
                if link.is_external or not is_content_url(link.href):
                    continue
                if relative_path(link.href, root) is None:
                    continue
                key = compare_key(link.href)
                if key in seen:
                    continue
                seen.add(key)
                next_level.append(link.href)
        level = next_level

    if retry_failed and unreachable and len(found) < max_pages:
        candidates = [u for u in dict.fromkeys(unreachable) if u not in blocked]
        candidates = candidates[: max(0, max_pages - len(found))]
        if candidates:
            retried = fetcher.fetch_many(candidates, respect_robots=respect_robots,
                                         escalate_js=deep)
            recovered = 0
            still_dead = list(unreachable)
            for url in candidates:
                result = retried.get(url)
                if result is not None and result.ok:
                    page = extract(result.html, url, fetched_url=result.fetched_url)
                    found.append((url, max_depth, page.title))
                    still_dead.remove(url)
                    recovered += 1
            unreachable = still_dead
            if recovered:
                notes.append(f"{recovered} page(s) answered on a retry after "
                             "failing once")

    if unreachable:
        notes.append(f"{len(unreachable)} page(s) did not respond and were "
                     "recorded as unreachable")
    if len(found) >= max_pages:
        notes.append(f"stopped at the {max_pages}-page cap; raise --max-pages "
                     "if the site is larger")
    return found, unreachable, notes, blocked


def _ancestor_roots(root: str) -> list[str]:
    """Each enclosing path of `root`, nearest first, ending at the host root."""
    parts = urlsplit(normalize(root))
    segments = [seg for seg in parts.path.split("/") if seg]
    out = []
    while segments:
        segments.pop()
        out.append(f"{parts.scheme}://{parts.netloc}/" + "/".join(segments))
    return out


def discover(root: str, fetcher, *, max_pages: int = DEFAULT_MAX_PAGES,
             max_depth: int = DEFAULT_MAX_DEPTH, use_sitemap: bool = True,
             respect_robots: bool | None = None, deep: bool = False,
             widen_leaf_roots: bool = True) -> SiteInventory:
    """Every content page under `root` -- or, if `root` is a leaf page with
    nothing beneath it, under the nearest enclosing section that has pages.

    People paste whatever URL they have (`/venues/index.php`), not a clean
    section root. Scoping strictly to that path found one page and silently
    discarded every sibling in the same site. So when the first pass finds
    at most one page, climb to each parent path (crawl only, still capped)
    until one yields more, and say so in the notes.
    """
    inventory = _discover_at(root, fetcher, max_pages=max_pages, max_depth=max_depth,
                             use_sitemap=use_sitemap, respect_robots=respect_robots,
                             deep=deep)
    if not widen_leaf_roots or len(inventory.pages) > 1:
        return inventory
    for parent in _ancestor_roots(root):
        wider = _discover_at(parent, fetcher, max_pages=max_pages, max_depth=max_depth,
                             use_sitemap=False, respect_robots=respect_robots, deep=deep)
        if len(wider.pages) > 1:
            wider.notes.insert(0, f"{root} has no pages beneath it, so the scan widened to "
                                  f"{parent} and found {len(wider.pages)} pages there")
            return wider
    return inventory


def _discover_at(root: str, fetcher, *, max_pages: int, max_depth: int, use_sitemap: bool,
                 respect_robots: bool | None, deep: bool) -> SiteInventory:
    """Every content page under `root`.

    The sitemap is tried first: a site that publishes one is telling you what
    it thinks its pages are, and it costs one request instead of hundreds. A
    crawl is the fallback, and also the answer when a sitemap turns out to list
    only a handful of pages while the site clearly has more.

    In `deep` mode neither source is trusted alone: a sitemap can omit pages
    nobody remembered to list, and a crawl can miss pages nothing links to
    anymore. Both run, and their results are merged -- a page found either way
    is kept. That is also when the crawl widens: nested sitemaps are followed
    further, more sitemap paths are guessed, failed pages get a second try, and
    a page that looks like an empty JS shell is re-rendered with a browser.
    """
    inventory = SiteInventory(root=normalize(root))

    sitemap_pages: list[PageRef] = []
    sitemap_source = ""
    if use_sitemap:
        locations, sitemap_source = from_sitemap(root, fetcher, deep=deep)
        outside = 0
        for url in locations:
            if not is_content_url(url):
                continue
            path = relative_path(url, root)
            if path is None:
                outside += 1
                continue
            sitemap_pages.append(
                PageRef(url=normalize(url), path=path, source="sitemap"))
        sitemap_pages = _dedupe(sitemap_pages)
        if sitemap_pages:
            inventory.notes.append(
                f"{len(sitemap_pages)} page(s) from {sitemap_source}")
            if outside:
                inventory.notes.append(
                    f"{outside} sitemap URL(s) sit outside {root} and were skipped")
        else:
            inventory.notes.append("no usable sitemap" + ("" if deep else
                                                            "; crawling instead"))

    # Outside deep mode, a usable sitemap is trusted on its own -- crawling too
    # would cost every page a second fetch for no benefit most sites ever need.
    should_crawl = deep or not sitemap_pages
    crawl_pages: list[PageRef] = []
    crawl_dead: list[PageRef] = []
    blocked = 0
    if should_crawl:
        pages, dead, notes, blocked_urls = crawl(root, fetcher, max_pages=max_pages,
                                                 max_depth=max_depth,
                                                 respect_robots=respect_robots,
                                                 deep=deep)
        crawl_pages = _dedupe([
            PageRef(url=normalize(url), path=relative_path(url, root) or "/",
                    title=title, source="crawl", depth=depth)
            for url, depth, title in pages
        ])
        crawl_dead = [
            PageRef(url=normalize(u), path=relative_path(u, root) or "/",
                    source="crawl")
            for u in dead
        ]
        blocked = len(blocked_urls)
        inventory.notes.extend(notes)
        inventory.notes.append(f"{len(crawl_pages)} page(s) reached by crawling")

    if sitemap_pages and crawl_pages:
        merged = {p.path: p for p in crawl_pages}
        added = 0
        for page in sitemap_pages:
            if page.path not in merged:
                merged[page.path] = page
                added += 1
        inventory.pages = sorted(merged.values(), key=lambda p: p.path)
        inventory.method = f"sitemap ({sitemap_source}) + crawl"
        if added:
            inventory.notes.append(
                f"{added} page(s) were in the sitemap but not reached by "
                "crawling, and are included anyway")
    elif sitemap_pages:
        inventory.pages = sitemap_pages
        inventory.method = f"sitemap ({sitemap_source})"
    else:
        inventory.pages = crawl_pages
        inventory.method = "crawl"

    inventory.unreachable = crawl_dead
    inventory.blocked = blocked
    return inventory


def check_reachable(inventory: SiteInventory, fetcher, *,
                    respect_robots: bool | None = None) -> None:
    """Confirm every listed page actually answers, and record the ones that do not.

    A sitemap is a claim, not a guarantee: sites routinely list pages that time
    out, 404, or were never built. Those are worth naming on either side -- on
    the new site they are links a visitor will hit and a search engine will
    crawl, and on the old site they are pages whose content cannot be checked
    even though the page is supposed to exist.

    Pages are moved out of `pages` and into `unreachable`, so nothing downstream
    tries to compare content that could not be fetched.
    """
    if not inventory.pages:
        return
    by_url = {p.url: p for p in inventory.pages}
    results = fetcher.fetch_many(list(by_url), respect_robots=respect_robots)

    alive, dead = [], []
    for page in inventory.pages:
        result = results.get(page.url)
        if result is not None and result.ok:
            alive.append(page)
            continue
        if result is not None and result.status == ROBOTS_BLOCKED:
            inventory.blocked += 1
        dead.append(page)

    inventory.pages = alive
    inventory.unreachable.extend(dead)
    if dead:
        inventory.notes.append(
            f"{len(dead)} listed page(s) did not respond and were set aside")


def _dedupe(pages: list[PageRef]) -> list[PageRef]:
    seen: dict[str, PageRef] = {}
    for page in pages:
        if page.path not in seen:
            seen[page.path] = page
    return sorted(seen.values(), key=lambda p: p.path)


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def _words(text: str) -> set[str]:
    return {w for w in _WORDS.split((text or "").lower()) if w}


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def path_similarity(a: str, b: str) -> float:
    """How alike two site-relative paths are.

    Blends character similarity with shared path words, because a rename that
    keeps the words ("/portfolio-coding" to "/projects/coding") should score
    higher than a coincidental string overlap.
    """
    if a == b:
        return 1.0
    words_a, words_b = _words(a), _words(b)
    overlap = (len(words_a & words_b) / len(words_a | words_b)
               if words_a | words_b else 0.0)
    return max(_ratio(a, b), (_ratio(a, b) + overlap) / 2, overlap)


def match_sites(old: SiteInventory, new: SiteInventory, *,
                path_ratio: float = PATH_MATCH_RATIO) -> MatchReport:
    """Pair old pages to new ones, worst-case first.

    Four passes, most confident first, each claiming what it is sure about
    before the looser ones run:

    1. identical site-relative path -- the page did not move;
    2. identical final slug -- the page moved but kept its name;
    3. best-scoring path similarity above the floor -- renamed but recognisable;
    4. titles, if they were collected (see `match_by_title`).

    Every new page is claimed once. What is left over on the old side is the
    answer to "did everything get migrated".
    """
    report = MatchReport()
    remaining_new = {p.path: p for p in new.pages}
    remaining_old: list[PageRef] = []

    # 1. same path
    for page in old.pages:
        twin = remaining_new.pop(page.path, None)
        if twin is not None:
            report.pairs.append(PagePairing(page, twin, "exact", 1.0))
        else:
            remaining_old.append(page)

    # 2. same slug
    by_slug: dict[str, list[PageRef]] = {}
    for page in remaining_new.values():
        if page.slug:
            by_slug.setdefault(page.slug, []).append(page)
    still_unmatched: list[PageRef] = []
    for page in remaining_old:
        bucket = by_slug.get(page.slug) or []
        bucket = [p for p in bucket if p.path in remaining_new]
        if page.slug and len(bucket) == 1:
            twin = bucket[0]
            remaining_new.pop(twin.path, None)
            report.pairs.append(PagePairing(page, twin, "slug", 0.9))
        else:
            still_unmatched.append(page)

    # 3. best path similarity, globally best-first so one strong match is not
    #    stolen by an earlier weaker one. Pages whose top two candidates tie are
    #    left out: there is nothing to choose between them.
    ambiguous: set[str] = set()
    candidates: list[tuple[float, PageRef, PageRef]] = []
    for page in still_unmatched:
        # Keyed sort: a bare tuple sort falls through to comparing PageRefs
        # whenever two candidates score the same, which is exactly the case
        # this block exists to handle.
        scored = sorted(
            ((path_similarity(page.path, twin.path), twin)
             for twin in remaining_new.values()),
            key=lambda pair: -pair[0])
        if (len(scored) > 1 and scored[0][0] >= path_ratio
                and scored[0][0] - scored[1][0] < AMBIGUITY_MARGIN):
            ambiguous.add(page.path)
            continue
        candidates += [(score, page, twin) for score, twin in scored]

    candidates.sort(key=lambda t: -t[0])
    claimed_old: set[str] = set()
    for score, page, twin in candidates:
        if score < path_ratio:
            break
        if page.path in claimed_old or twin.path not in remaining_new:
            continue
        remaining_new.pop(twin.path, None)
        claimed_old.add(page.path)
        report.pairs.append(PagePairing(page, twin, "fuzzy-path", round(score, 3)))

    report.unmatched_old = [p for p in still_unmatched if p.path not in claimed_old]
    report.unmatched_new = list(remaining_new.values())
    report.pairs.sort(key=lambda p: p.old.path)
    report.unmatched_old.sort(key=lambda p: p.path)
    report.unmatched_new.sort(key=lambda p: p.path)
    return report


def match_by_title(report: MatchReport, fetcher, *,
                   ratio: float = TITLE_MATCH_RATIO,
                   respect_robots: bool | None = None,
                   limit: int = 120) -> int:
    """Second chance for leftovers, using page titles.

    The build plan's fallback for when paths differ entirely. It needs a fetch
    per page, so it runs only on what is still unmatched after the path passes
    -- the cost stays proportional to the problem rather than the site.

    Returns how many further pairs it found; `report` is updated in place.
    """
    from .extract import extract

    if not report.unmatched_old or not report.unmatched_new:
        return 0

    def fill(pages: list[PageRef]) -> list[PageRef]:
        wanted = [p for p in pages[:limit] if not (p.title and p.heading)]
        if not wanted:
            return []
        by_url = {p.url: p for p in wanted}
        results = fetcher.fetch_many(list(by_url), respect_robots=respect_robots)
        dead: list[PageRef] = []
        for url, result in results.items():
            page = by_url[url]
            if not result.ok:
                dead.append(page)
                continue
            content = extract(result.html, url, fetched_url=result.fetched_url)
            page.title = content.title
            # The heading is captured alongside the title because a site that
            # serves one title for every route still names each page in its h1.
            tops = [h.text for h in content.headings if h.level == 1]
            page.heading = (tops or [h.text for h in content.headings] or [""])[0]
        return dead

    report.unreachable_old += fill(report.unmatched_old)
    report.unreachable_new += fill(report.unmatched_new)

    old_signal = choose_label_signal(report.unmatched_old)
    new_signal = choose_label_signal(report.unmatched_new)
    report.label_signals = (old_signal, new_signal)

    candidates = [
        (_ratio(_normalize_title(a.label), _normalize_title(b.label)), a, b)
        for a in report.unmatched_old if a.label
        for b in report.unmatched_new if b.label
    ]
    candidates.sort(key=lambda t: -t[0])

    taken_old: set[str] = set()
    taken_new: set[str] = set()
    added = 0
    for score, page, twin in candidates:
        if score < ratio:
            break
        if page.path in taken_old or twin.path in taken_new:
            continue
        taken_old.add(page.path)
        taken_new.add(twin.path)
        report.pairs.append(PagePairing(page, twin, "title", round(score, 3)))
        added += 1

    report.unmatched_old = [p for p in report.unmatched_old if p.path not in taken_old]
    report.unmatched_new = [p for p in report.unmatched_new if p.path not in taken_new]
    report.pairs.sort(key=lambda p: p.old.path)
    return added


def choose_label_signal(pages: list[PageRef]) -> str:
    """Decide what actually identifies a page on this site, and set it.

    Prefers the <title>, falls back to the first <h1>, and reports which it
    used. A site whose pages all share one title is not unusual -- it is the
    default for client-routed sites -- and on those the heading is the only
    per-page text the server sends.
    """
    titled = [p for p in pages if p.title]
    if titled:
        counts: dict[str, int] = {}
        for page in titled:
            key = _normalize_title(page.title)
            counts[key] = counts.get(key, 0) + 1
        most_common = max(counts.values())
        if most_common / len(titled) <= DISTINCTIVE_SHARE:
            for page in pages:
                page._label = page.title
            return "title"

    if any(p.heading for p in pages):
        for page in pages:
            page._label = page.heading or page.title
        return "heading"

    for page in pages:
        page._label = page.title
    return "title (not distinctive)"


def _normalize_title(title: str) -> str:
    """Titles usually carry a site-name suffix that says nothing about the page."""
    cleaned = re.split(r"\s+[|\u2013\u2014-]\s+", title or "")[0]
    return " ".join(_WORDS.split(cleaned.lower())).strip()
