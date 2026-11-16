"""crawl_site: a thin wrapper around discover() -- discover() itself is
already covered by tests/test_discover.py, so these only check the wrapping:
URL extraction, root-inclusion, and the truncated flag."""

from src.discover import PageRef, SiteInventory
from src.link_checker import crawl_site


def _inventory(urls, root="https://e.edu/admissions/"):
    return SiteInventory(root=root, pages=[PageRef(url=u) for u in urls])


def test_returns_every_page_url_from_the_inventory(monkeypatch):
    monkeypatch.setattr(crawl_site, "discover",
                        lambda root, fetcher, **kw: _inventory(
                            ["https://e.edu/admissions/", "https://e.edu/admissions/apply"]))
    urls, truncated = crawl_site.crawl_pages("https://e.edu/admissions/", fetcher=object())
    assert "https://e.edu/admissions/apply" in urls
    assert truncated is False


def test_the_root_is_included_even_if_discovery_did_not_list_it(monkeypatch):
    monkeypatch.setattr(crawl_site, "discover",
                        lambda root, fetcher, **kw: _inventory(
                            ["https://e.edu/admissions/apply"]))
    urls, _ = crawl_site.crawl_pages("https://e.edu/admissions/", fetcher=object())
    assert "https://e.edu/admissions/" in urls


def test_hitting_the_page_cap_is_reported_as_truncated(monkeypatch):
    monkeypatch.setattr(crawl_site, "discover",
                        lambda root, fetcher, **kw: _inventory(
                            [f"https://e.edu/admissions/p{i}" for i in range(5)]))
    urls, truncated = crawl_site.crawl_pages(
        "https://e.edu/admissions/", fetcher=object(), max_pages=5)
    assert truncated is True


def test_well_under_the_page_cap_is_not_truncated(monkeypatch):
    monkeypatch.setattr(crawl_site, "discover",
                        lambda root, fetcher, **kw: _inventory(
                            ["https://e.edu/admissions/"]))
    urls, truncated = crawl_site.crawl_pages(
        "https://e.edu/admissions/", fetcher=object(), max_pages=500)
    assert truncated is False
