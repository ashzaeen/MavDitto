"""Site Scan's page discovery.

Reuses `discover.py` rather than reimplementing "find every page under a
path prefix": that is exactly what `discover()` already does for migration
pairing (sitemap first, a bounded same-host crawl as the fallback), and its
crawl scope -- pages under the root's own path -- is precisely what the
design doc calls for.
"""

from __future__ import annotations

from ..discover import discover
from ..urls import normalize

DEFAULT_MAX_PAGES = 500


def crawl_pages(root_url: str, fetcher, *, max_pages: int = DEFAULT_MAX_PAGES,
                deep: bool = False) -> tuple[list[str], bool]:
    """(page URLs under `root_url`, whether the page cap was hit)."""
    inventory = discover(root_url, fetcher, max_pages=max_pages, deep=deep)
    urls = [p.url for p in inventory.pages]

    # The root itself is always in scope, even if discovery's sitemap/crawl
    # somehow didn't surface it as its own entry (a redirecting root, e.g.).
    if normalize(root_url) not in {normalize(u) for u in urls}:
        urls.insert(0, root_url)

    truncated = len(inventory.pages) >= max_pages
    return urls, truncated
