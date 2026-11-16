"""Data shapes for the Broken Link Inspector.

Kept separate from the migration pipeline's ``src/models.py``: a
``CheckedLink`` and an ``Image``/``Link`` from the diff pipeline look similar
on the surface, but nothing here needs to round-trip through the comparison
store, and bolting a link-health status tier onto the diff's own ``Link``
would make that dataclass answer two unrelated questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# status tiers -- see the design doc's "Status tiers" table
# --------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_REDIRECTED = "redirected"
STATUS_BROKEN = "broken"
STATUS_BROKEN_ANCHOR = "broken_anchor"
STATUS_RESTRICTED = "restricted"
STATUS_UNREACHABLE = "unreachable"
STATUS_FORMAT_INVALID = "format_invalid"

# Only these four inflate the headline "X broken links found" count.
# Redirected and Restricted are shown but are not necessarily problems.
BROKEN_STATUSES = frozenset({
    STATUS_BROKEN, STATUS_BROKEN_ANCHOR, STATUS_UNREACHABLE, STATUS_FORMAT_INVALID,
})

ALL_STATUSES = (
    STATUS_OK, STATUS_REDIRECTED, STATUS_BROKEN, STATUS_BROKEN_ANCHOR,
    STATUS_RESTRICTED, STATUS_UNREACHABLE, STATUS_FORMAT_INVALID,
)

# --------------------------------------------------------------------------
# link categories -- see the design doc's "Link categories" table
# --------------------------------------------------------------------------

CATEGORY_INTERNAL_IN_SCOPE = "internal_in_scope"
CATEGORY_INTERNAL_OTHER = "internal_other"
CATEGORY_EXTERNAL = "external"
CATEGORY_DOCUMENT = "document"
CATEGORY_IMAGE = "image"
CATEGORY_MEDIA = "media"
CATEGORY_ANCHOR = "anchor"
CATEGORY_EMAIL = "email"
CATEGORY_PHONE = "phone"

ALL_CATEGORIES = (
    CATEGORY_INTERNAL_IN_SCOPE, CATEGORY_INTERNAL_OTHER, CATEGORY_EXTERNAL,
    CATEGORY_DOCUMENT, CATEGORY_IMAGE, CATEGORY_MEDIA, CATEGORY_ANCHOR,
    CATEGORY_EMAIL, CATEGORY_PHONE,
)


@dataclass
class RawLink:
    """One linkable element as found on one page -- before `dedup` collapses
    repeats across pages into a single `CheckedLink`."""

    url: str             # absolute (fragment kept for an in-page anchor)
    text: str
    region: str           # "" | "header" | "nav" | "footer"
    found_on: str        # the page URL this was found on
    element: str = "a"   # "a" | "area"


@dataclass
class CheckedLink:
    """One unique link, deduplicated across every page it appeared on, and
    -- once `check_links.check_all` has run -- its result."""

    url: str
    text: str
    category: str
    region: str
    found_on: list[str] = field(default_factory=list)

    status: str = ""
    http_code: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def is_broken(self) -> bool:
        return self.status in BROKEN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "text": self.text,
            "category": self.category,
            "region": self.region,
            "foundOn": self.found_on,
            "status": self.status,
            "httpCode": self.http_code,
            "finalUrl": self.final_url,
            "redirectChain": self.redirect_chain,
            "error": self.error,
        }


@dataclass
class LinkScanResult:
    """A finished Page Scan or Site Scan."""

    mode: str            # "page" | "site"
    root_url: str
    pages_crawled: list[str] = field(default_factory=list)
    links: list[CheckedLink] = field(default_factory=list)
    truncated: bool = False   # Site Scan only: the page cap was hit

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for link in self.links:
            by_status[link.status] = by_status.get(link.status, 0) + 1
        broken = sum(n for status, n in by_status.items() if status in BROKEN_STATUSES)
        return {
            "totalChecked": len(self.links),
            "totalPagesCrawled": len(self.pages_crawled),
            "brokenCount": broken,
            "byStatus": by_status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "rootUrl": self.root_url,
            "pagesCrawled": self.pages_crawled,
            "truncated": self.truncated,
            "links": [link.to_dict() for link in self.links],
            "summary": self.summary(),
        }
