"""check_links: HTTP/format checking. httpx.Client.request is monkeypatched
class-wide, the same way test_fetch.py stubs fetcher.client.get -- no real
network traffic."""

import httpx
import pytest

from src.link_checker.check_links import check_all
from src.link_checker.models import (
    CATEGORY_ANCHOR, CATEGORY_EMAIL, CATEGORY_EXTERNAL, CATEGORY_INTERNAL_IN_SCOPE,
    CATEGORY_PHONE, CheckedLink, STATUS_BROKEN, STATUS_BROKEN_ANCHOR,
    STATUS_FORMAT_INVALID, STATUS_OK, STATUS_REDIRECTED, STATUS_RESTRICTED,
    STATUS_UNREACHABLE,
)


class _FakeURL:
    def __init__(self, s):
        self._s = s

    def __str__(self):
        return self._s


class _FakeResponse:
    def __init__(self, status_code=200, url="https://e.edu/x", history=(),
                content_type="text/html", text=""):
        self.status_code = status_code
        self.url = _FakeURL(url)
        self.history = [_FakeResponse(url=u) for u in history]
        self.headers = {"content-type": content_type}
        self.text = text


def _link(url, category=CATEGORY_INTERNAL_IN_SCOPE, text="link") -> CheckedLink:
    return CheckedLink(url=url, text=text, category=category, region="")


def test_a_200_is_ok(monkeypatch):
    monkeypatch.setattr(httpx.Client, "request",
                        lambda self, method, url, **kw: _FakeResponse(200))
    link = _link("https://e.edu/page")
    check_all([link])
    assert link.status == STATUS_OK
    assert link.http_code == 200


def test_a_redirect_history_is_redirected_not_ok(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "request",
        lambda self, method, url, **kw: _FakeResponse(
            200, url="https://e.edu/final", history=["https://e.edu/old"]))
    link = _link("https://e.edu/old")
    check_all([link])
    assert link.status == STATUS_REDIRECTED
    assert link.final_url == "https://e.edu/final"
    assert link.redirect_chain == ["https://e.edu/old"]


def test_a_404_is_broken(monkeypatch):
    monkeypatch.setattr(httpx.Client, "request",
                        lambda self, method, url, **kw: _FakeResponse(404))
    link = _link("https://e.edu/gone")
    check_all([link])
    assert link.status == STATUS_BROKEN
    assert link.http_code == 404


def test_a_403_is_restricted_not_broken(monkeypatch):
    monkeypatch.setattr(httpx.Client, "request",
                        lambda self, method, url, **kw: _FakeResponse(403))
    link = _link("https://e.edu/private")
    check_all([link])
    assert link.status == STATUS_RESTRICTED


def test_a_connection_error_is_unreachable(monkeypatch):
    def raise_error(self, method, url, **kw):
        raise httpx.ConnectError("no route to host")
    monkeypatch.setattr(httpx.Client, "request", raise_error)
    link = _link("https://e.edu/down")
    check_all([link])
    assert link.status == STATUS_UNREACHABLE
    assert link.error


def test_head_not_supported_falls_back_to_get(monkeypatch):
    calls = []

    def fake(self, method, url, **kw):
        calls.append(method)
        if method == "HEAD":
            return _FakeResponse(405)
        return _FakeResponse(200)

    monkeypatch.setattr(httpx.Client, "request", fake)
    link = _link("https://e.edu/head-unsupported")
    check_all([link])
    assert calls == ["HEAD", "GET"]
    assert link.status == STATUS_OK


def test_an_anchor_link_whose_target_id_exists_is_ok(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "request",
        lambda self, method, url, **kw: _FakeResponse(
            200, text='<div id="section-2">Here</div>'))
    link = _link("https://e.edu/page#section-2", category=CATEGORY_ANCHOR)
    check_all([link])
    assert link.status == STATUS_OK


def test_an_anchor_link_whose_target_id_is_missing_is_broken_anchor(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "request",
        lambda self, method, url, **kw: _FakeResponse(200, text='<p>no ids here</p>'))
    link = _link("https://e.edu/page#missing", category=CATEGORY_ANCHOR)
    check_all([link])
    assert link.status == STATUS_BROKEN_ANCHOR


def test_an_anchor_check_always_uses_get_not_head(monkeypatch):
    methods = []

    def fake(self, method, url, **kw):
        methods.append(method)
        return _FakeResponse(200, text='<div id="x"></div>')

    monkeypatch.setattr(httpx.Client, "request", fake)
    link = _link("https://e.edu/page#x", category=CATEGORY_ANCHOR)
    check_all([link])
    assert methods == ["GET"]


def test_a_link_with_a_hash_that_is_not_really_an_anchor_is_not_id_checked(monkeypatch):
    """Confirmed on a real UTA page: categorize.py falls a whitespace-bearing
    fragment through to a non-anchor category, but the raw URL still carries
    the "#". This must not trip check_links' own anchor-verification branch --
    that would search a bodyless HEAD response and always report "broken"."""
    methods = []

    def fake(self, method, url, **kw):
        methods.append(method)
        return _FakeResponse(200, text="")  # HEAD: no body, as real HEAD responses have

    monkeypatch.setattr(httpx.Client, "request", fake)
    link = _link("https://e.edu/news/article#Learn More", category=CATEGORY_INTERNAL_IN_SCOPE)
    check_all([link])
    assert methods == ["HEAD"]
    assert link.status == STATUS_OK


def test_a_valid_email_is_ok():
    link = _link("mailto:info@uta.edu", category=CATEGORY_EMAIL)
    check_all([link])
    assert link.status == STATUS_OK


def test_an_invalid_email_is_format_invalid():
    link = _link("mailto:not-an-email", category=CATEGORY_EMAIL)
    check_all([link])
    assert link.status == STATUS_FORMAT_INVALID


def test_a_valid_phone_is_ok():
    link = _link("tel:+18175551234", category=CATEGORY_PHONE)
    check_all([link])
    assert link.status == STATUS_OK


def test_an_invalid_phone_is_format_invalid():
    link = _link("tel:call-us", category=CATEGORY_PHONE)
    check_all([link])
    assert link.status == STATUS_FORMAT_INVALID


def test_email_and_phone_links_never_touch_the_network(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("should not make an HTTP request")
    monkeypatch.setattr(httpx.Client, "request", fail)
    links = [_link("mailto:info@uta.edu", category=CATEGORY_EMAIL),
            _link("tel:+18175551234", category=CATEGORY_PHONE)]
    check_all(links)
    assert all(l.status == STATUS_OK for l in links)


def test_check_all_on_an_empty_list_does_nothing():
    check_all([])  # must not raise
