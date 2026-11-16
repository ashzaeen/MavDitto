"""Orchestrates the Broken Link Inspector end to end.

`run_page_scan` and `run_site_scan` are the two entry points the design doc
calls for; both funnel through the same extract -> region-filter -> dedup ->
check pipeline, differing only in whether a crawl runs first.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..fetch import Fetcher
from .check_links import check_all
from .crawl_site import DEFAULT_MAX_PAGES, crawl_pages
from .dedup import dedup
from .extract_links import extract_all_links
from .models import LinkScanResult, RawLink

ProgressFn = Callable[[str, str, int, int], None]  # stage, message, done, total


def _region_allowed(region: str, *, include_header: bool, include_footer: bool,
                    include_nav: bool) -> bool:
    if region == "header":
        return include_header
    if region == "footer":
        return include_footer
    if region == "nav":
        return include_nav
    return True


def _filter_region(links: list[RawLink], *, include_header: bool, include_footer: bool,
                   include_nav: bool) -> list[RawLink]:
    return [
        link for link in links
        if _region_allowed(link.region, include_header=include_header,
                           include_footer=include_footer, include_nav=include_nav)
    ]


def run_page_scan(url: str, fetcher: Fetcher, *,
                  include_header: bool = False, include_footer: bool = False,
                  include_nav: bool = False,
                  cancel: threading.Event | None = None,
                  on_progress: ProgressFn | None = None) -> LinkScanResult:
    """Check every link on one page. No crawling."""
    result = fetcher.fetch(url, source="auto")
    if not result.ok:
        raise RuntimeError(
            f"could not fetch {url} (status {result.status}); check the URL is reachable")

    page_url = result.fetched_url or url
    raw_links = extract_all_links(result.html, url, fetched_url=result.fetched_url)
    raw_links = _filter_region(raw_links, include_header=include_header,
                               include_footer=include_footer, include_nav=include_nav)
    checked = dedup(raw_links, root_prefix=page_url)

    def progress(done: int, total: int) -> None:
        if on_progress:
            on_progress("checking", f"checked {done} of {total} links", done, total)

    check_all(checked, cancel=cancel, on_progress=progress)
    return LinkScanResult(mode="page", root_url=url, pages_crawled=[page_url], links=checked)


def run_site_scan(url: str, fetcher: Fetcher, *,
                  max_pages: int = DEFAULT_MAX_PAGES,
                  include_header: bool = False, include_footer: bool = False,
                  include_nav: bool = False,
                  deep: bool = False,
                  cancel: threading.Event | None = None,
                  on_progress: ProgressFn | None = None) -> LinkScanResult:
    """Crawl every page under `url`'s path prefix, then check every link
    found anywhere along the way -- including ones pointing outside the
    crawled section entirely. See crawl_site.py for the crawl-scope /
    check-scope distinction."""
    if on_progress:
        on_progress("crawling", f"discovering pages under {url}", 0, 0)
    page_urls, truncated = crawl_pages(url, fetcher, max_pages=max_pages, deep=deep)

    raw_links: list[RawLink] = []
    for i, page_url in enumerate(page_urls, start=1):
        if cancel is not None and cancel.is_set():
            break
        if on_progress:
            on_progress("extracting", f"reading links from page {i} of {len(page_urls)}",
                       i - 1, len(page_urls))
        result = fetcher.fetch(page_url, source="auto")
        if not result.ok:
            continue
        links = extract_all_links(result.html, page_url, fetched_url=result.fetched_url)
        raw_links.extend(_filter_region(
            links, include_header=include_header, include_footer=include_footer,
            include_nav=include_nav))

    checked = dedup(raw_links, root_prefix=url)

    def progress(done: int, total: int) -> None:
        if on_progress:
            on_progress("checking", f"checked {done} of {total} unique links", done, total)

    check_all(checked, cancel=cancel, on_progress=progress)
    return LinkScanResult(mode="site", root_url=url, pages_crawled=page_urls,
                          links=checked, truncated=truncated)
