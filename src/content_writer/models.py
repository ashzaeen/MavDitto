"""Data shapes for Content Writer.

`Section` is the common intermediate format every input format (URL, PDF,
Word, PowerPoint, Excel, image) gets normalized into, and the shape Web
Builder's matcher consumes -- see the design doc's "Normalize into sections"
step for why this exists: a slide-by-slide PPT dump and a crawled web page
have nothing in common structurally except that both are, ultimately, a
title plus an ordered list of headed sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REGISTER_INSTITUTIONAL = "institutional"
REGISTER_PROSPECTIVE_STUDENT = "prospective-student"
REGISTERS = (REGISTER_INSTITUTIONAL, REGISTER_PROSPECTIVE_STUDENT)

# A lightweight hint, not a hard classification -- Web Builder's matcher
# treats this as a starting signal, not a guarantee. See the design doc.
SECTION_KINDS = ("intro", "body", "cta", "fact-list", "quote", "faq-item")

TONE_OPTIONS = ("Warmer", "More formal", "More concise", "More detailed")
LENGTH_OPTIONS = ("Match original", "Condense", "Expand")


@dataclass
class SectionLink:
    text: str
    url: str
    is_document: bool = False   # points at a PDF/DOCX/etc. rather than a page
    is_button: bool = False     # was styled as a button/CTA in the source, not an inline text link


@dataclass
class Section:
    """One structural unit of normalized content: an optional heading, its
    body text, a `kind` hint, and whatever links/media it carried."""

    heading: str | None
    body: str
    kind: str = "body"
    links: list[SectionLink] = field(default_factory=list)
    media_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading": self.heading,
            "body": self.body,
            "kind": self.kind,
            "links": [{"text": link.text, "url": link.url, "isDocument": link.is_document,
                      "isButton": link.is_button} for link in self.links],
            "mediaRefs": list(self.media_refs),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Section":
        return cls(
            heading=d.get("heading"), body=d.get("body", ""), kind=d.get("kind", "body"),
            links=[SectionLink(text=link.get("text", ""), url=link.get("url", ""),
                               is_document=link.get("isDocument", False),
                               is_button=link.get("isButton", False))
                  for link in d.get("links", [])],
            media_refs=list(d.get("mediaRefs", [])),
        )


@dataclass
class ExtractedContent:
    """What extraction.py produces, before any rewriting happens -- the raw
    (but normalized-into-sections) source material."""

    page_title: str
    sections: list[Section] = field(default_factory=list)
    source_note: str = ""
    page_chrome_context: str = ""   # nav/header/footer text -- background context only, never placeable


@dataclass
class RewriteOptions:
    tone: list[str] = field(default_factory=list)   # subset of TONE_OPTIONS, multi-select
    length: str = "Match original"                  # one of LENGTH_OPTIONS
    register_override: str | None = None             # None means auto-detect


GOALS = {
    "inform": "Inform: help the reader understand something",
    "enroll": "Enroll: move a prospective student toward applying",
    "register": "Register: get the reader to sign up or RSVP",
    "donate": "Give: invite support from alumni and donors",
    "announce": "Announce: report news accurately",
    "visit": "Visit: bring the reader to campus or an event",
}
READING_LEVELS = ("grade 8", "grade 9", "grade 10", "grade 12", "college")
POINTS_OF_VIEW = {"": "Auto", "you": "Second person (you)", "we": "First person plural (we)",
                  "third": "Third person"}
LANGUAGES = ("English", "Spanish")
MAX_VARIANTS = 3
MAX_ITEMS = 10

STRICTNESS_OPTIONS = {
    "mockup": "Mockup — placeholders OK, clearly labeled",
    "publish-ready": "Publish-ready — no placeholders",
}


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = v.splitlines()
    return [str(x).strip() for x in (v or []) if str(x).strip()]


@dataclass
class VoiceSettings:
    """Everything the writer can set beyond the template's own brief --
    audience, goal, the three tone dials, length, and the advanced options.
    Empty/None means "use the brand profile's default for this template"."""

    audience: str = ""
    goal: str = ""
    dials: dict[str, int] = field(default_factory=dict)
    tone: list[str] = field(default_factory=list)
    length: str = ""
    target_words: int | None = None
    register: str | None = None
    reading_level: str = ""
    point_of_view: str = ""
    keywords: list[str] = field(default_factory=list)
    cta: str = ""
    must_include: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    use_knowledge_base: bool = True
    language: str = "English"
    variants: int = 1
    item_count: int = 5
    # Compose mode only: whether an ungrounded block (a quote, stat, link or
    # image with no real source) may appear at all, labeled, or must be
    # grounded or omitted. Every other template ignores this.
    strictness: str = "mockup"
    # Explicit model id from the writer's picker (llm_provider.MODEL_CATALOG).
    # Empty means "use the active provider's strongest configured model" --
    # resolved at call time via llm_provider.resolve_model, not here, since
    # validity depends on which provider is active.
    model: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "VoiceSettings":
        d = d or {}
        dials = {}
        for k, v in (d.get("dials") or {}).items():
            try:
                dials[str(k)] = max(1, min(5, int(v)))
            except (TypeError, ValueError):
                pass
        try:
            target_words = int(d["targetWords"]) if d.get("targetWords") else None
        except (TypeError, ValueError):
            target_words = None
        if target_words is not None:
            target_words = max(20, min(3000, target_words))

        def _int(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(d.get(key) or default)))
            except (TypeError, ValueError):
                return default

        language = str(d.get("language") or "English")
        return cls(
            audience=str(d.get("audience") or ""),
            goal=str(d.get("goal") or "") if str(d.get("goal") or "") in GOALS else "",
            dials=dials,
            tone=[t for t in _str_list(d.get("tone")) if t in TONE_OPTIONS],
            length=str(d.get("length") or ""),
            target_words=target_words,
            register=(str(d["register"]) if d.get("register") else None),
            reading_level=(str(d.get("readingLevel") or "")
                           if str(d.get("readingLevel") or "") in READING_LEVELS else ""),
            point_of_view=(str(d.get("pointOfView") or "")
                           if str(d.get("pointOfView") or "") in POINTS_OF_VIEW else ""),
            keywords=_str_list(d.get("keywords")),
            cta=str(d.get("cta") or "").strip(),
            must_include=_str_list(d.get("mustInclude")),
            avoid=_str_list(d.get("avoid")),
            use_knowledge_base=bool(d.get("useKnowledgeBase", True)),
            language=language if language in LANGUAGES else "English",
            variants=_int("variants", 1, 1, MAX_VARIANTS),
            item_count=_int("itemCount", 5, 1, MAX_ITEMS),
            strictness=(str(d.get("strictness") or "mockup")
                       if str(d.get("strictness") or "mockup") in STRICTNESS_OPTIONS else "mockup"),
            model=str(d.get("model") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audience": self.audience, "goal": self.goal, "dials": dict(self.dials),
            "tone": list(self.tone), "length": self.length, "targetWords": self.target_words,
            "register": self.register, "readingLevel": self.reading_level,
            "pointOfView": self.point_of_view, "keywords": list(self.keywords),
            "cta": self.cta, "mustInclude": list(self.must_include), "avoid": list(self.avoid),
            "useKnowledgeBase": self.use_knowledge_base, "language": self.language,
            "variants": self.variants, "itemCount": self.item_count,
            "strictness": self.strictness, "model": self.model,
        }


@dataclass
class StructuredContent:
    """Content Writer's final output -- what gets displayed for review/
    editing, and what Web Builder consumes for its own matching.

    `original_sections` carries the pre-rewrite extraction alongside the
    rewrite, index-aligned with `sections` -- the results view shows each
    section's original content collapsed next to its rewrite, and neither
    the frontend nor a later Web Builder call should need a second request
    just to see what changed.
    """

    page_title: str
    register: str
    sections: list[Section] = field(default_factory=list)
    original_sections: list[Section] = field(default_factory=list)
    source_note: str = ""
    cost_usd: float = 0.0
    page_chrome_context: str = ""   # nav/header/footer text -- background context only, never placeable
    # The model's own "which guidelines I applied and why" notes (the vendored
    # method's validate-and-explain step), and the review of the final draft.
    brand_notes: list[str] = field(default_factory=list)
    review: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pageTitle": self.page_title,
            "register": self.register,
            "sections": [s.to_dict() for s in self.sections],
            "originalSections": [s.to_dict() for s in self.original_sections],
            "sourceNote": self.source_note,
            "costUsd": round(self.cost_usd, 6),
            "pageChromeContext": self.page_chrome_context,
            "brandNotes": list(self.brand_notes),
            "review": self.review,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StructuredContent":
        return cls(
            page_title=d.get("pageTitle", ""), register=d.get("register", ""),
            sections=[Section.from_dict(s) for s in d.get("sections", [])],
            original_sections=[Section.from_dict(s) for s in d.get("originalSections", [])],
            source_note=d.get("sourceNote", ""), cost_usd=float(d.get("costUsd") or 0.0),
            page_chrome_context=d.get("pageChromeContext", ""),
            brand_notes=list(d.get("brandNotes") or []),
            review=d.get("review"),
        )


# --------------------------------------------------------------------------
# Compose mode: a page as an ordered sequence of typed blocks, not just
# headed paragraphs -- a hero, images, a pull quote, a stat band, a link
# list, a call-to-action button. Flat optional fields per type (only the
# ones relevant to a given `type` are populated), the same shape
# GeneratedSection/GeneratedItem already use for provider-agnostic
# structured output, rather than a tagged union no provider agrees on.
# --------------------------------------------------------------------------

BLOCK_TYPES = ("hero", "heading", "text", "image", "quote", "stat", "links", "cta", "divider")


@dataclass
class Block:
    type: str
    heading: str = ""
    subheading: str = ""
    body: str = ""                          # text/hero body; '- ' lines = a list
    image_alt: str = ""
    image_caption: str = ""
    quote_text: str = ""
    quote_attribution: str = ""
    stat_value: str = ""                    # e.g. "40,000+"
    stat_label: str = ""                    # e.g. "Total enrollment"
    links: list[SectionLink] = field(default_factory=list)   # links block, or one CTA link
    # True when this block's *specific* content (a quote, a figure, a link
    # target, an image scene) is illustrative rather than sourced from the
    # brief, the source material or the knowledge base -- never silently
    # invented; always labeled and explained.
    is_placeholder: bool = False
    placeholder_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type, "heading": self.heading, "subheading": self.subheading,
            "body": self.body, "imageAlt": self.image_alt, "imageCaption": self.image_caption,
            "quoteText": self.quote_text, "quoteAttribution": self.quote_attribution,
            "statValue": self.stat_value, "statLabel": self.stat_label,
            "links": [{"text": link.text, "url": link.url, "isDocument": link.is_document,
                      "isButton": link.is_button} for link in self.links],
            "isPlaceholder": self.is_placeholder, "placeholderNote": self.placeholder_note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Block":
        return cls(
            type=str(d.get("type") or "text"), heading=str(d.get("heading") or ""),
            subheading=str(d.get("subheading") or ""), body=str(d.get("body") or ""),
            image_alt=str(d.get("imageAlt") or ""), image_caption=str(d.get("imageCaption") or ""),
            quote_text=str(d.get("quoteText") or ""),
            quote_attribution=str(d.get("quoteAttribution") or ""),
            stat_value=str(d.get("statValue") or ""), stat_label=str(d.get("statLabel") or ""),
            links=[SectionLink(text=link.get("text", ""), url=link.get("url", ""),
                               is_document=link.get("isDocument", False),
                               is_button=link.get("isButton", False))
                  for link in d.get("links", [])],
            is_placeholder=bool(d.get("isPlaceholder", False)),
            placeholder_note=str(d.get("placeholderNote") or ""),
        )


@dataclass
class ComposedPage:
    """Compose mode's output -- a title plus an ordered list of blocks,
    reviewed like any other draft. `to_structured_content` is the one-way
    bridge to the rest of the pipeline (Web Builder's "Send to" handoff),
    which only understands headed text sections."""

    title: str
    subtitle: str = ""
    register: str = ""
    page_plan: str = ""
    blocks: list[Block] = field(default_factory=list)
    brand_notes: list[str] = field(default_factory=list)
    review: dict[str, Any] | None = None
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "subtitle": self.subtitle, "register": self.register,
            "pagePlan": self.page_plan,
            "blocks": [b.to_dict() for b in self.blocks], "brandNotes": list(self.brand_notes),
            "review": self.review, "costUsd": round(self.cost_usd, 6),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComposedPage":
        return cls(
            title=d.get("title", ""), subtitle=d.get("subtitle", ""), register=d.get("register", ""),
            page_plan=d.get("pagePlan", ""),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            brand_notes=list(d.get("brandNotes") or []), review=d.get("review"),
            cost_usd=float(d.get("costUsd") or 0.0),
        )

    def to_structured_content(self) -> StructuredContent:
        sections: list[Section] = []
        for b in self.blocks:
            if b.type == "divider":
                continue
            if b.type == "quote":
                body = f"“{b.quote_text}”" + (f" — {b.quote_attribution}"
                                                        if b.quote_attribution else "")
                sections.append(Section(heading=b.heading or None, body=body, kind="quote"))
            elif b.type == "stat":
                sections.append(Section(heading=b.heading or None,
                                        body=f"{b.stat_value} — {b.stat_label}", kind="fact-list"))
            elif b.type == "image":
                caption = f" {b.image_caption}" if b.image_caption else ""
                sections.append(Section(heading=b.heading or None,
                                        body=f"[Image: {b.image_alt}]{caption}", kind="body",
                                        media_refs=[b.image_alt] if b.image_alt else []))
            elif b.type == "links":
                body = "\n".join(f"- {link.text}" for link in b.links)
                sections.append(Section(heading=b.heading or None, body=body, kind="fact-list",
                                        links=list(b.links)))
            elif b.type == "cta":
                link = b.links[0] if b.links else SectionLink(text=b.heading, url="", is_button=True)
                sections.append(Section(heading=None, body=b.body, kind="cta", links=[link]))
            else:   # hero, heading, text
                body = "\n".join(x for x in (b.subheading, b.body) if x)
                sections.append(Section(heading=b.heading or None, body=body,
                                        kind="intro" if b.type == "hero" else "body"))
        return StructuredContent(page_title=self.title, register=self.register, sections=sections,
                                 brand_notes=list(self.brand_notes))
