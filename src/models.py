"""Normalized data structures shared across the pipeline.

Everything downstream of `extract.py` speaks in terms of `PageContent`, so the
diff stages never touch raw HTML. Keeping these JSON-round-trippable means the
results store can be plain files during the MVP and move to SQLite later
without changing the shape of anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from datetime import datetime, timezone
from typing import Any, Iterable

# Link targets we treat as "documents" rather than pages. The PDF/doc link
# checker in the post-MVP plan keys off this, and structural diff reports on it.
DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".rtf", ".odt", ".ods", ".odp", ".zip",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Severity(IntEnum):
    """How much a finding should weigh when phase 4 ranks pages by risk."""

    INFO = 0     # worth showing, not worth worrying about
    LOW = 1      # cosmetic or likely intentional
    MEDIUM = 2   # a reviewer should look
    HIGH = 3     # content is probably gone

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Finding:
    kind: str                    # dotted id, e.g. "heading.dropped"
    severity: Severity
    summary: str                 # one line, reads on its own
    items: list[str] = field(default_factory=list)   # the specific things

    def __str__(self) -> str:
        return f"[{self.severity.label}] {self.summary}"


@dataclass
class Heading:
    level: int      # 1-6, from h1..h6
    text: str

    def __str__(self) -> str:
        return f"{'#' * self.level} {self.text}"


@dataclass
class Image:
    src: str            # absolute, Wayback-unwrapped
    alt: str | None     # None means the attribute was absent entirely
    title: str | None = None
    kind: str = "img"   # "img" | "background"
    region: str = ""    # "" | "header" | "footer" -- see extract._region_of

    @property
    def has_alt(self) -> bool:
        return bool(self.alt and self.alt.strip())

    @property
    def is_decorative(self) -> bool:
        """CSS background images carry no alt text by definition.

        Sitecore templates lean on background-image for hero and section
        artwork, so counting those as "missing alt" would bury the real
        accessibility regressions under hundreds of false positives.
        """
        return self.kind == "background"


@dataclass
class Link:
    href: str           # absolute, Wayback-unwrapped
    text: str
    is_document: bool = False
    is_external: bool = False


@dataclass
class Block:
    """One structural unit of a page's content, in document order.

    Read straight from the DOM rather than from flattened text, so a list
    stays a list and a table stays a table instead of collapsing into lines
    indistinguishable from a paragraph. This is the unit the review screen
    renders and the unit semantic matching is chunked by: one block is one
    passage to match old-to-new, so a section of twenty paragraphs is twenty
    independently addressable blocks rather than a handful of arbitrary
    word-budget slices that all carried the same heading label.
    """

    kind: str                              # "heading" | "paragraph" | "list" | "table" | "quote"
    text: str = ""                          # flattened text, for embedding/matching
    level: int = 0                          # heading level 1-6; 0 for non-headings
    ordered: bool = False                   # list only: <ol> vs <ul>
    items: list[str] = field(default_factory=list)   # list items, or table rows ("cell | cell")
    columns: list[str] = field(default_factory=list)  # table header cells, if any
    heading_path: list[str] = field(default_factory=list)  # ancestor headings, nearest last

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class MediaItem:
    """One inline piece of non-text content -- image, link, button, video
    embed, or form -- found while walking the same main-content region
    `extract_blocks` walks, in document order. Deliberately a separate list
    from `Block` rather than a new `Block.kind`: `Block`/`extract_blocks` is
    also what Migration Validator's diffing (`embed.py`/`export_web.py`)
    consumes, and adding new kinds there would change its diff/embedding
    behavior on every page. This list is purely additive for callers (like
    Web Builder) that want it, at zero risk to that existing consumer."""

    kind: str                    # "image" | "link" | "button" | "video" | "form"
    text: str = ""                 # image alt text; link/button visible text; form's best-effort label
    href: str = ""                 # resolved URL -- image src, link/button href, video embed src
    is_document: bool = False      # link/button only, mirrors Link.is_document (PDF/DOCX/etc.)
    platform: str = ""              # video only: "youtube" | "vimeo" | "panopto" | "html5" | "other"
    has_captions: bool = False      # video only -- a <track kind=captions|subtitles> child was present
    heading_path: list[str] = field(default_factory=list)   # same convention as Block.heading_path


@dataclass
class PageContent:
    """One page, de-boilerplated and normalized."""

    url: str                    # the URL we were asked for (canonical, not Wayback)
    fetched_url: str            # what we actually hit (may be a Wayback snapshot)
    source: str                 # "live" | "wayback"
    status: int
    title: str = ""
    text: str = ""              # main body text, boilerplate stripped
    headings: list[Heading] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)  # headings/paragraphs/lists/tables, in order
    content_media: list[MediaItem] = field(default_factory=list)  # images/links/buttons/video/forms, in order
    chrome_text: str = ""       # nav/header/footer text, captured before it's stripped -- context only
    lang: str | None = None
    snapshot_timestamp: str | None = None   # Wayback 14-digit stamp, if applicable
    render_mode: str = "static"             # "static" | "js"
    fetched_at: str = field(default_factory=utcnow_iso)
    extractor: str = ""                     # which path produced the text
    notes: list[str] = field(default_factory=list)   # non-fatal problems worth surfacing

    # --- convenience accessors the diff stages will lean on -----------------

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def images_missing_alt(self) -> list[Image]:
        """Content images lacking alt text. Background images are excluded --
        see Image.is_decorative."""
        return [i for i in self.images if not i.is_decorative and not i.has_alt]

    @property
    def background_images(self) -> list[Image]:
        return [i for i in self.images if i.kind == "background"]

    @property
    def document_links(self) -> list[Link]:
        return [l for l in self.links if l.is_document]

    def heading_outline(self) -> list[str]:
        return [str(h) for h in self.headings]

    # --- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageContent":
        d = dict(d)
        d["headings"] = [Heading(**h) for h in d.get("headings", [])]
        d["images"] = [Image(**i) for i in d.get("images", [])]
        d["links"] = [Link(**l) for l in d.get("links", [])]
        d["blocks"] = [Block(**b) for b in d.get("blocks", [])]
        d["content_media"] = [MediaItem(**m) for m in d.get("content_media", [])]
        return cls(**d)

    @classmethod
    def from_json(cls, s: str) -> "PageContent":
        return cls.from_dict(json.loads(s))


@dataclass
class FetchResult:
    """Raw output of the fetch stage, before extraction."""

    url: str
    fetched_url: str
    status: int
    html: str
    source: str = "live"
    render_mode: str = "static"
    snapshot_timestamp: str | None = None
    elapsed_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and bool(self.html)


def dump_pages(pages: Iterable[PageContent], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([p.to_dict() for p in pages], fh, indent=2, ensure_ascii=False)
