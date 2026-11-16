"""run_page_scan / run_site_scan, wired end to end against a stub fetcher and
a monkeypatched crawl -- no network, no real HTTP checking (check_all itself
is covered in test_link_checker_check.py, so these stub it out too, to keep
focus on the orchestration: extraction, region filtering, and dedup)."""

from src.link_checker import pipeline
from src.link_checker.models import STATUS_OK
from src.models import FetchResult

PAGE_HTML = """
<html><body>
<header><a href="/apply">Apply</a></header>
<nav><a href="/programs">Programs</a></nav>
<main>
<a href="/about">About</a>
<a href="mailto:info@e.edu">Email</a>
</main>
<footer><a href="/privacy">Privacy</a></footer>
</body></html>
"""


class StubFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch(self, url, **kw):
        html = self.pages.get(url)
        if html is None:
            return FetchResult(url=url, fetched_url=url, status=404, html="")
        return FetchResult(url=url, fetched_url=url, status=200, html=html)


def _stub_check_all(monkeypatch):
    """Mark every link OK without making a real HTTP request -- the point of
    these tests is the pipeline wiring, not check_links.py's own logic."""
    def fake_check_all(links, **kw):
        for link in links:
            link.status = STATUS_OK
    monkeypatch.setattr(pipeline, "check_all", fake_check_all)


def test_page_scan_excludes_header_nav_footer_by_default(monkeypatch):
    _stub_check_all(monkeypatch)
    fetcher = StubFetcher({"https://e.edu/campus": PAGE_HTML})
    result = pipeline.run_page_scan("https://e.edu/campus", fetcher)

    urls = {l.url for l in result.links}
    assert "https://e.edu/about" in urls
    assert "mailto:info@e.edu" in urls
    assert "https://e.edu/apply" not in urls
    assert "https://e.edu/programs" not in urls
    assert "https://e.edu/privacy" not in urls


def test_page_scan_includes_opted_in_regions(monkeypatch):
    _stub_check_all(monkeypatch)
    fetcher = StubFetcher({"https://e.edu/campus": PAGE_HTML})
    result = pipeline.run_page_scan(
        "https://e.edu/campus", fetcher,
        include_header=True, include_footer=True, include_nav=True)

    urls = {l.url for l in result.links}
    assert "https://e.edu/apply" in urls
    assert "https://e.edu/programs" in urls
    assert "https://e.edu/privacy" in urls


def test_page_scan_raises_when_the_page_cannot_be_fetched():
    fetcher = StubFetcher({})
    try:
        pipeline.run_page_scan("https://e.edu/missing", fetcher)
        assert False, "expected a RuntimeError"
    except RuntimeError as exc:
        assert "could not fetch" in str(exc)


def test_page_scan_every_link_is_checked(monkeypatch):
    _stub_check_all(monkeypatch)
    fetcher = StubFetcher({"https://e.edu/campus": PAGE_HTML})
    result = pipeline.run_page_scan("https://e.edu/campus", fetcher)
    assert all(l.status == STATUS_OK for l in result.links)


def test_site_scan_crawls_every_discovered_page_and_dedups_links(monkeypatch):
    _stub_check_all(monkeypatch)
    monkeypatch.setattr(
        pipeline, "crawl_pages",
        lambda root, fetcher, **kw: (
            ["https://e.edu/campus/a", "https://e.edu/campus/b"], False))

    shared_link_html = '<html><body><main><a href="/shared">Shared</a></main></body></html>'
    fetcher = StubFetcher({
        "https://e.edu/campus/a": shared_link_html,
        "https://e.edu/campus/b": shared_link_html,
    })
    result = pipeline.run_site_scan("https://e.edu/campus/", fetcher)

    assert len(result.links) == 1
    assert sorted(result.links[0].found_on) == [
        "https://e.edu/campus/a", "https://e.edu/campus/b"]
    assert result.pages_crawled == ["https://e.edu/campus/a", "https://e.edu/campus/b"]


def test_site_scan_reports_truncation_from_the_crawl(monkeypatch):
    _stub_check_all(monkeypatch)
    monkeypatch.setattr(pipeline, "crawl_pages",
                        lambda root, fetcher, **kw: (["https://e.edu/a"], True))
    fetcher = StubFetcher({"https://e.edu/a": "<html><body></body></html>"})
    result = pipeline.run_site_scan("https://e.edu/", fetcher)
    assert result.truncated is True


def test_site_scan_skips_pages_that_fail_to_fetch(monkeypatch):
    _stub_check_all(monkeypatch)
    monkeypatch.setattr(
        pipeline, "crawl_pages",
        lambda root, fetcher, **kw: (["https://e.edu/ok", "https://e.edu/broken"], False))
    fetcher = StubFetcher({"https://e.edu/ok": PAGE_HTML})  # /broken -> 404 via StubFetcher
    result = pipeline.run_site_scan("https://e.edu/", fetcher)
    assert any(l.url == "https://e.edu/about" for l in result.links)
