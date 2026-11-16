"""Tests for bulk fetching -- the enumeration path, not a single deliberate
fetch. No network: the Fetcher's own private methods are monkeypatched, so
these exercise the escalation logic in `fetch_many` without touching httpx or
Playwright.
"""

from src.fetch import Fetcher
from src.models import FetchResult


def _shell(url: str) -> FetchResult:
    return FetchResult(url=url, fetched_url=url, status=200,
                       html="<div id='root'></div>", render_mode="static")


def _rendered(url: str) -> FetchResult:
    return FetchResult(
        url=url, fetched_url=url, status=200,
        html="<html><body><main><h1>Real</h1><p>" + "words " * 60 +
             "</p></main></body></html>",
        render_mode="js")


def test_escalate_js_rerenders_pages_that_look_like_empty_shells(monkeypatch):
    """A static fetch that comes back looking like a JS shell is exactly the
    case a client-rendered nav menu produces -- and enumerating a site depends
    on reading that menu, not just on this one page's own content."""
    with Fetcher(use_cache=False) as fetcher:
        rendered_calls = []
        monkeypatch.setattr(fetcher, "_fetch_static",
                            lambda url, notes, **kw: _shell(url))
        monkeypatch.setattr(fetcher, "_fetch_js",
                            lambda url, notes: rendered_calls.append(url) or _rendered(url))

        results = fetcher.fetch_many(["https://e.edu/a"], escalate_js=True)

    assert rendered_calls == ["https://e.edu/a"]
    assert "Real" in results["https://e.edu/a"].html
    assert any("empty JS shell" in n for n in results["https://e.edu/a"].notes)


def test_without_escalate_js_shells_are_left_as_is(monkeypatch):
    """Off by default: launching a browser per page is slow, and a quick run
    should not pay for it without being asked."""
    with Fetcher(use_cache=False) as fetcher:
        called = []
        monkeypatch.setattr(fetcher, "_fetch_static",
                            lambda url, notes, **kw: _shell(url))
        monkeypatch.setattr(fetcher, "_fetch_js",
                            lambda url, notes: called.append(url))

        results = fetcher.fetch_many(["https://e.edu/a"])

    assert called == []
    assert results["https://e.edu/a"].html == "<div id='root'></div>"


def test_a_page_that_already_has_real_content_is_not_rerendered(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        called = []
        real = FetchResult(url="https://e.edu/a", fetched_url="https://e.edu/a",
                           status=200,
                           html="<html><body><main><h1>Real</h1><p>" +
                                "words " * 60 + "</p></main></body></html>")
        monkeypatch.setattr(fetcher, "_fetch_static", lambda url, notes, **kw: real)
        monkeypatch.setattr(fetcher, "_fetch_js",
                            lambda url, notes: called.append(url))

        fetcher.fetch_many(["https://e.edu/a"], escalate_js=True)

    assert called == []


def test_js_escalation_is_capped_by_a_budget(monkeypatch):
    """Unbounded would turn a crawl level full of client-rendered pages into a
    browser launched per page with no ceiling."""
    with Fetcher(use_cache=False) as fetcher:
        urls = [f"https://e.edu/p{i}" for i in range(5)]
        calls = []
        monkeypatch.setattr(fetcher, "_fetch_static",
                            lambda url, notes, **kw: _shell(url))
        monkeypatch.setattr(fetcher, "_fetch_js",
                            lambda url, notes: calls.append(url) or _rendered(url))

        fetcher.fetch_many(urls, escalate_js=True, js_budget=2)

    assert len(calls) == 2


class _Resp:
    def __init__(self, status_code=200, content=b"", content_type="image/jpeg",
                text=None):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type} if content_type else {}
        self.text = text if text is not None else content.decode("utf-8", "replace")


def test_fetch_binary_returns_bytes_and_content_type(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(content=b"\xff\xd8jpeg-bytes"))
        result = fetcher.fetch_binary("https://e.edu/a.jpg")
    assert result == (b"\xff\xd8jpeg-bytes", "image/jpeg")


def test_fetch_binary_rejects_a_non_image_content_type(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(content=b"<html></html>",
                                                    content_type="text/html"))
        assert fetcher.fetch_binary("https://e.edu/a.jpg") is None


def test_fetch_binary_rejects_an_oversized_response(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(content=b"x" * 100))
        assert fetcher.fetch_binary("https://e.edu/a.jpg", max_bytes=10) is None


def test_fetch_binary_returns_none_on_a_bad_status(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(status_code=404))
        assert fetcher.fetch_binary("https://e.edu/gone.jpg") is None


def test_fetch_binary_returns_none_on_a_network_error(monkeypatch):
    import httpx

    def raise_error(url, **kw):
        raise httpx.ConnectError("no route to host")

    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get", raise_error)
        assert fetcher.fetch_binary("https://e.edu/a.jpg") is None


def test_fetch_text_returns_the_response_body(monkeypatch):
    css = ".hero { background: url('/a.jpg'); }"
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(
                                content=css.encode(), content_type="text/css", text=css))
        assert fetcher.fetch_text("https://e.edu/main.css") == css


def test_fetch_text_does_not_gate_on_content_type(monkeypatch):
    """A <link rel="stylesheet"> names a stylesheet by the page's own
    declaration -- a server that mislabels the content-type header should
    not hide the file the page itself says is CSS."""
    css = ".hero { background: url('/a.jpg'); }"
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(
                                content=css.encode(), content_type="application/octet-stream",
                                text=css))
        assert fetcher.fetch_text("https://e.edu/main.css") == css


def test_fetch_text_rejects_an_oversized_response(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get",
                            lambda url, **kw: _Resp(content=b"x" * 100, text="x" * 100))
        assert fetcher.fetch_text("https://e.edu/main.css", max_bytes=10) is None


def test_fetch_text_returns_none_on_a_bad_status(monkeypatch):
    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get", lambda url, **kw: _Resp(status_code=404))
        assert fetcher.fetch_text("https://e.edu/gone.css") is None


def test_fetch_text_returns_none_on_a_network_error(monkeypatch):
    import httpx

    def raise_error(url, **kw):
        raise httpx.ConnectError("no route to host")

    with Fetcher(use_cache=False) as fetcher:
        monkeypatch.setattr(fetcher.client, "get", raise_error)
        assert fetcher.fetch_text("https://e.edu/main.css") is None


def test_escalation_is_skipped_when_the_fetcher_disallows_js(monkeypatch):
    with Fetcher(use_cache=False, allow_js=False) as fetcher:
        called = []
        monkeypatch.setattr(fetcher, "_fetch_static",
                            lambda url, notes, **kw: _shell(url))
        monkeypatch.setattr(fetcher, "_fetch_js",
                            lambda url, notes: called.append(url))

        fetcher.fetch_many(["https://e.edu/a"], escalate_js=True)

    assert called == []
