"""URL normalization and Wayback unwrapping.

Two jobs that both `fetch.py` and `extract.py` need, and that `discover.py`
will need again for pairing:

1. Normalize a URL so two spellings of the same page compare equal.
2. Unwrap Wayback's rewritten URLs back to the original. Wayback rewrites every
   href and img src on an archived page to `/web/<timestamp>/<original>`, so
   without this step an old page's links would never match the new page's.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode

WAYBACK_HOSTS = {"web.archive.org", "archive.org"}

# `/web/20180412030405id_/http://example.com/page` -> timestamp, original
_WAYBACK_PATH = re.compile(
    r"^/web/(\d{4,14})(?:[a-z_]{2,3}_)?/(?P<orig>.+)$", re.IGNORECASE
)

# Tracking params that never change which page you land on.
_JUNK_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "_ga", "ref", "referrer",
}


def unwrap_wayback(url: str) -> str:
    """Turn a Wayback snapshot URL back into the original URL. Idempotent."""
    if not url:
        return url
    parts = urlsplit(url)
    if parts.netloc.lower().lstrip("www.") not in {h.lstrip("www.") for h in WAYBACK_HOSTS}:
        return url
    m = _WAYBACK_PATH.match(parts.path)
    if not m:
        return url
    orig = m.group("orig")
    if parts.query:
        orig = f"{orig}?{parts.query}"
    # Wayback occasionally collapses `http://` to `http:/`.
    orig = re.sub(r"^(https?):/(?!/)", r"\1://", orig)
    if not orig.startswith(("http://", "https://")):
        orig = "http://" + orig
    return unwrap_wayback(orig)   # nested wrapping happens; unwrap until stable


def wayback_timestamp(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.netloc.lower() not in WAYBACK_HOSTS:
        return None
    m = _WAYBACK_PATH.match(parts.path)
    return m.group(1) if m else None


def normalize(url: str, *, keep_query: bool = True) -> str:
    """Canonical spelling of a URL, for comparison and de-duplication."""
    if not url:
        return ""
    url = unwrap_wayback(url.strip())
    parts = urlsplit(url)

    scheme = (parts.scheme or "http").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    # Drop default ports.
    if host.endswith(":80") and scheme == "http":
        host = host[:-3]
    elif host.endswith(":443") and scheme == "https":
        host = host[:-4]

    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    # Strip index files and trailing slash so /about/, /about, /about/index.html agree.
    path = re.sub(r"/(index|default)\.(html?|aspx?|php)$", "/", path, flags=re.I)
    if len(path) > 1:
        path = path.rstrip("/")

    query = ""
    if keep_query and parts.query:
        kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in _JUNK_PARAMS]
        query = urlencode(sorted(kept))

    return urlunsplit((scheme, host, path, query, ""))   # fragment always dropped


def same_site(a: str, b: str) -> bool:
    """True if two URLs share a registrable-ish host (ignoring www)."""
    ha = urlsplit(normalize(a)).netloc
    hb = urlsplit(normalize(b)).netloc
    return bool(ha) and ha == hb


def is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https", "")


def absolutize(href: str, base_url: str) -> str:
    """Resolve `href` against `base_url`, unwrapping Wayback on both sides.

    Wayback-served pages carry a Wayback base, so relative links must resolve
    against the snapshot first and only then be unwrapped -- doing it in the
    other order loses the path.
    """
    if not href:
        return ""
    joined = urljoin(base_url, href.strip())
    return unwrap_wayback(joined)


def path_slug(url: str) -> str:
    """The trailing path segment, lowercased -- the unit `discover.py` pairs on."""
    path = urlsplit(normalize(url)).path
    seg = [s for s in path.split("/") if s]
    return seg[-1].lower() if seg else ""


def compare_key(url: str) -> str:
    """Case-folded normalization, for matching only -- never for fetching.

    URL paths are case-sensitive per RFC 3986, and some servers act on that, so
    `normalize` preserves case. But Sitecore tends to emit `/About/Apply.aspx`
    where WordPress emits `/about/apply/`, and those are the same page. Pairing
    and de-duplication use this key; anything that hits the network does not.
    """
    n = normalize(url)
    parts = urlsplit(n)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.lower(),
                       parts.query, ""))


def make_resolver(fetched_url: str):
    """Build the right href/src resolver for wherever a page came from.

    Archived pages come in two flavours and they need opposite treatment:

    * Fetched with the `id_` modifier, Wayback returns the original bytes
      *unrewritten*. A root-relative `/academics/programs` is then the old
      site's own link and must resolve against the original URL. Resolving it
      against the snapshot URL instead yields `web.archive.org/academics/
      programs` -- the path is silently replaced, and every root-relative link
      on the page compares as changed.
    * Fetched through the framed viewer, hrefs are rewritten to
      `/web/<timestamp>/<original>` and must resolve against the snapshot,
      then be unwrapped.

    Returns a callable taking a raw href and giving back an absolute original
    URL, picking the base per-link so both flavours work.
    """
    snapshot_base = fetched_url
    original_base = unwrap_wayback(fetched_url)
    is_snapshot = original_base != fetched_url

    def resolve(raw: str) -> str:
        if not raw:
            return ""
        raw = raw.strip()
        if not is_snapshot:
            return absolutize(raw, original_base)
        if raw.startswith("/web/") or "web.archive.org/web/" in raw:
            return absolutize(raw, snapshot_base)   # Wayback-rewritten
        return absolutize(raw, original_base)       # original markup

    return resolve
