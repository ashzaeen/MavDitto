"""HTTP/format checking for deduplicated links.

Page/document/image/media/external links get a HEAD request (falling back to
GET if HEAD isn't supported), since HEAD wastes no bandwidth pulling a whole
PDF or video just to learn its status code. Anchor links always need a GET --
confirming the target id exists means reading the body. Email/phone links
never touch the network at all; "checking" them is a format check.

Concurrency is deliberately uneven: external hosts get a longer per-host
delay and a hard concurrency ceiling of their own (`_EXTERNAL_GATE`),
independent of how many workers the internal checks are using -- a subsite
audit's own domain can take a much higher request rate than someone else's
server should be asked to.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import httpx

from ..fetch import USER_AGENT, RateLimiter
from .models import (
    CATEGORY_ANCHOR, CATEGORY_EMAIL, CATEGORY_EXTERNAL, CATEGORY_PHONE,
    CheckedLink, STATUS_BROKEN, STATUS_BROKEN_ANCHOR, STATUS_FORMAT_INVALID,
    STATUS_OK, STATUS_REDIRECTED, STATUS_RESTRICTED, STATUS_UNREACHABLE,
)

DEFAULT_TIMEOUT = 12.0
DEFAULT_WORKERS = 8
EXTERNAL_CONCURRENCY = 2
INTERNAL_DELAY_S = 0.3
EXTERNAL_DELAY_S = 1.5

# Loose on purpose: this validates *shape*, per the design doc ("format-
# validated, not fetched"), not whether the mailbox/number actually exists.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d()\-.\s]{7,20}$")

_ID_RE = re.compile(r"""\bid\s*=\s*(['"])(.*?)\1""", re.IGNORECASE)
_NAME_RE = re.compile(r"""\bname\s*=\s*(['"])(.*?)\1""", re.IGNORECASE)


def _check_email(address: str) -> tuple[str, str]:
    if _EMAIL_RE.match(address):
        return STATUS_OK, ""
    return STATUS_FORMAT_INVALID, f'"{address}" is not a valid email address'


def _check_phone(number: str) -> tuple[str, str]:
    digits = re.sub(r"\D", "", number)
    if _PHONE_RE.match(number) and 7 <= len(digits) <= 15:
        return STATUS_OK, ""
    return STATUS_FORMAT_INVALID, f'"{number}" is not a valid phone number'


def _tier_for_status(code: int) -> str:
    if code in (401, 403):
        return STATUS_RESTRICTED
    if 200 <= code < 300:
        return STATUS_OK
    return STATUS_BROKEN


def _request(client: httpx.Client, url: str, *, method: str) -> tuple[httpx.Response | None, str]:
    try:
        resp = client.request(method, url, follow_redirects=True, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as exc:
        return None, str(exc)
    return resp, ""


def _anchor_exists(resp: httpx.Response, fragment: str) -> bool | None:
    """True/False once the target's body has been searched; None when the
    target isn't HTML at all, so no search is possible -- treated as "can't
    tell, don't fail it" by the caller."""
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return None
    text = resp.text
    return any(m.group(2) == fragment for m in _ID_RE.finditer(text)) or \
        any(m.group(2) == fragment for m in _NAME_RE.finditer(text))


def _check_one(link: CheckedLink, client: httpx.Client, *,
               internal_limiter: RateLimiter, external_limiter: RateLimiter,
               external_gate) -> None:
    if link.category == CATEGORY_EMAIL:
        address = link.url[len("mailto:"):].split("?", 1)[0]
        link.status, link.error = _check_email(address)
        return
    if link.category == CATEGORY_PHONE:
        link.status, link.error = _check_phone(link.url[len("tel:"):])
        return

    base_url, _, fragment = link.url.partition("#")
    # Only a link categorize.py actually decided is an anchor gets its target
    # id verified -- a non-anchor link that merely happens to carry a "#" in
    # its URL (categorize.py falls through to this for a malformed fragment
    # that could never be a real HTML id) must never enter this branch: it
    # would search a bodyless HEAD response and always "find" nothing.
    is_anchor = link.category == CATEGORY_ANCHOR and bool(fragment)
    is_external = link.category == CATEGORY_EXTERNAL
    limiter = external_limiter if is_external else internal_limiter
    gate = external_gate if is_external else nullcontext()

    limiter.wait(base_url)
    with gate:
        resp, err = _request(client, base_url, method="GET" if is_anchor else "HEAD")
        if resp is not None and not is_anchor and resp.status_code in (405, 501):
            resp, err = _request(client, base_url, method="GET")

    if resp is None:
        link.status, link.error = STATUS_UNREACHABLE, err
        return

    link.http_code = resp.status_code
    link.final_url = str(resp.url)
    link.redirect_chain = [str(r.url) for r in resp.history]

    status = _tier_for_status(resp.status_code)
    if status == STATUS_OK and link.redirect_chain:
        status = STATUS_REDIRECTED

    if is_anchor and status in (STATUS_OK, STATUS_REDIRECTED):
        exists = _anchor_exists(resp, fragment)
        if exists is False:
            status = STATUS_BROKEN_ANCHOR
            link.error = f'no element with id/name "{fragment}" on the target page'
        elif exists is None:
            link.error = "target is not an HTML page; the anchor itself was not verified"

    link.status = status


def check_all(links: list[CheckedLink], *, workers: int = DEFAULT_WORKERS,
              cancel: threading.Event | None = None, on_progress=None) -> None:
    """Check every link in place (mutates each `CheckedLink`)."""
    if not links:
        return

    client = httpx.Client(headers={"User-Agent": USER_AGENT})
    internal_limiter = RateLimiter(INTERNAL_DELAY_S)
    external_limiter = RateLimiter(EXTERNAL_DELAY_S)
    external_gate = threading.Semaphore(EXTERNAL_CONCURRENCY)
    lock = threading.Lock()
    done = 0

    def one(link: CheckedLink) -> None:
        nonlocal done
        if cancel is not None and cancel.is_set():
            return
        _check_one(link, client, internal_limiter=internal_limiter,
                  external_limiter=external_limiter, external_gate=external_gate)
        with lock:
            done += 1
            if on_progress:
                on_progress(done, len(links))

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, links))
    finally:
        client.close()
