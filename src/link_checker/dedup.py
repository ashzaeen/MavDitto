"""Collapses repeated links found across many pages into one `CheckedLink`,
tracking every page each one appeared on.

Without this, a Site Scan reports a broken nav link once per page it repeats
on -- forty identical rows for one actual problem, and forty times the
network traffic to a server that may already be struggling.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from ..urls import normalize
from .categorize import categorize
from .models import CheckedLink, RawLink


def _identity(url: str) -> str:
    """The dedup key: normalize everything except the fragment, since an
    anchor link's fragment is exactly what makes it a distinct destination --
    `page#a` and `page#b` must never collapse into one entry, but
    `page?utm_source=x` and `page` should."""
    parts = urlsplit(url)
    base = normalize(urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, "")))
    return f"{base}#{parts.fragment}" if parts.fragment else base


def dedup(raw_links: list[RawLink], *, root_prefix: str) -> list[CheckedLink]:
    by_key: dict[str, CheckedLink] = {}
    for raw in raw_links:
        key = _identity(raw.url)
        link = by_key.get(key)
        if link is None:
            link = CheckedLink(
                url=raw.url, text=raw.text,
                category=categorize(raw.url, root_prefix=root_prefix),
                region=raw.region,
            )
            by_key[key] = link
        if raw.found_on not in link.found_on:
            link.found_on.append(raw.found_on)
    return list(by_key.values())
