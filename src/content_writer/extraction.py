"""Content extraction: pulls (page_title, [Section]) out of a URL or an
uploaded file, whatever format it is.

Deliberately its own module, not folded into the rewrite pipeline: the
setup engine's own ingestion (`src/setup_engine/ingest_brand_voice.py`) reads
brand-voice material through these exact same handlers.

Each file-format handler is a pure function over bytes already in memory --
no network, no LLM calls -- except `extract_from_image`, which necessarily
needs a vision model call, and so is the one handler that costs money and
needs a `Budget`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .models import ExtractedContent, Section, SectionLink

# --------------------------------------------------------------------------
# shared section-building helpers
# --------------------------------------------------------------------------

_FAQ_PATTERN = re.compile(r"\bfaq\b|frequently asked", re.IGNORECASE)
_CTA_PATTERN = re.compile(
    r"\b(apply|register|get started|contact us|learn more|sign up|enroll)\b",
    re.IGNORECASE,
)


def guess_kind(heading: str | None, body: str) -> str:
    """A lightweight hint, not a hard classification -- Web Builder's
    matcher treats this as a starting signal, per the design doc."""
    h = heading or ""
    if _FAQ_PATTERN.search(h) or (h.strip().endswith("?") and len(body) < 300):
        return "faq-item"
    if _CTA_PATTERN.search(h) and len(body) < 200:
        return "cta"
    if body.count("\n- ") >= 3 or body.count(" | ") >= 6:
        return "fact-list"
    return "body"


class _SectionBuilder:
    """Accumulates (heading, body-so-far) pairs into Sections as a document
    is walked top to bottom -- shared by every format whose source exposes
    real headings (URL blocks, DOCX paragraph styles, Markdown `#` lines)."""

    def __init__(self) -> None:
        self.sections: list[Section] = []
        self._current: Section | None = None
        self._intro_parts: list[str] = []

    def _flush_intro(self) -> None:
        if self._intro_parts:
            body = "\n\n".join(self._intro_parts).strip()
            if body:
                self.sections.append(Section(heading=None, body=body, kind="intro"))
            self._intro_parts = []

    def heading(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._flush_intro()
        self._current = Section(heading=text, body="", kind="body")
        self.sections.append(self._current)

    def body(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self._current is None:
            self._intro_parts.append(text)
        else:
            self._current.body = (self._current.body + "\n\n" + text).strip()
            self._current.kind = guess_kind(self._current.heading, self._current.body)

    def finish(self) -> list[Section]:
        self._flush_intro()
        return self.sections


# --------------------------------------------------------------------------
# URL
# --------------------------------------------------------------------------

def _attach_content_media(sections: list[Section], content_media: list) -> None:
    """Routes each image/link/button/video/form into the section it belongs
    to, matched by `heading_path[-1]` against the sections just built --
    `Block`s and `MediaItem`s share the same heading_path convention (see
    `extract_content_media`'s docstring), so this works without needing a
    shared position index between the two separate lists. An item with no
    heading path (or an unmatched one) lands on the intro section if there
    is one, else the first section -- there is always somewhere for it to
    go as long as at least one section exists."""
    by_heading: dict[str, Section] = {}
    for s in sections:
        if s.heading:
            by_heading[s.heading] = s   # last-wins on a repeated heading, matching document order
    fallback = next((s for s in sections if s.heading is None), None) or (sections[0] if sections else None)

    for item in content_media:
        target = by_heading.get(item.heading_path[-1]) if item.heading_path else None
        section = target or fallback
        if section is None:
            continue
        if item.kind == "image":
            section.media_refs.append(item.text or "image (no alt text)")
        elif item.kind == "video":
            caption_note = " [captions available]" if item.has_captions else ""
            label = item.text or item.href or "video"
            section.media_refs.append(f"video ({item.platform or 'embed'}): {label}{caption_note}")
        elif item.kind == "form":
            section.media_refs.append(f"form: {item.text or 'embedded form'}")
        elif item.kind in ("link", "button"):
            section.links.append(SectionLink(
                text=item.text, url=item.href, is_document=item.is_document,
                is_button=(item.kind == "button")))


def extract_from_url(url: str, fetcher) -> ExtractedContent:
    """Reuses the migration pipeline's own fetch/extract -- `extract_blocks`
    already walks a page into headings/paragraphs/lists/tables in document
    order, which is nearly exactly the Section shape this needs. Images,
    links/buttons, video embeds, and forms come from the separate
    `page.content_media` pass (see `extract_content_media`), attached to
    the right section by `_attach_content_media`; nav/header/footer text
    (`page.chrome_text`) is carried through as page-level background
    context, never a section a component gets placed against."""
    from ..extract import extract_fetch_result

    result = fetcher.fetch(url, source="auto")
    if not result.ok:
        raise RuntimeError(
            f"could not fetch {url} (status {result.status}); check the URL is reachable")

    page = extract_fetch_result(result)
    builder = _SectionBuilder()
    for block in page.blocks:
        if block.kind == "heading":
            builder.heading(block.text)
        elif block.kind == "list":
            lines = ([f"{i + 1}. {item}" for i, item in enumerate(block.items)] if block.ordered
                    else [f"- {item}" for item in block.items])
            builder.body("\n".join(lines))
        elif block.kind == "table":
            rows = ([" | ".join(block.columns)] if block.columns else []) + list(block.items)
            builder.body("\n".join(rows))
        else:
            builder.body(block.text)

    sections = builder.finish()
    _attach_content_media(sections, page.content_media)

    return ExtractedContent(
        page_title=page.title or url, sections=sections,
        source_note=f"extracted from {url}", page_chrome_context=page.chrome_text)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

# A standalone line, no trailing sentence punctuation, short enough to read
# as a title rather than a wrapped sentence -- plain-text PDF extraction
# carries no real heading markup, so this is the best available signal.
_HEADING_LIKE = re.compile(r"^[^.!?]{1,80}$")


_BULLET = re.compile(r"^[•●▪◦·\-*–]\s")
# Headings are at least this much larger than body text.
_HEADING_SIZE_RATIO = 1.15


def _pdf_lines(reader) -> list[tuple[int, str, float]]:
    """(page number, line text, dominant font size) for every line.

    pypdf's visitor sees exactly the text runs extract_text() concatenates
    (checked: the joined runs equal the extracted text), so each character
    can carry the size of the run it came from."""
    out: list[tuple[int, str, float]] = []
    for page_no, page in enumerate(reader.pages):
        runs: list[tuple[str, float]] = []

        def visit(text, cm, tm, font, size, _runs=runs):
            scale = (tm[2] ** 2 + tm[3] ** 2) ** 0.5 if tm else 1.0
            _runs.append((text, round(abs(size * (scale or 1.0)), 1)))

        try:
            page.extract_text(visitor_text=visit)
        except Exception:
            runs = [(page.extract_text() or "", 0.0)]
        parts: list[str] = []
        weight: dict[float, int] = {}

        def emit():
            line = "".join(parts).strip()
            if line:
                size = max(weight, key=weight.get) if weight else 0.0
                out.append((page_no, line, size))
            parts.clear()
            weight.clear()

        for text, size in runs:
            pieces = text.split("\n")
            for i, piece in enumerate(pieces):
                if i:
                    emit()
                parts.append(piece)
                n = len(piece.strip())
                if n:
                    weight[size] = weight.get(size, 0) + n
        emit()
    return out


def _running_lines(lines: list[tuple[int, str, float]], pages: int) -> set[str]:
    """Page headers/footers: the same line (digits ignored, so "Page 3 of 7"
    matches "Page 4 of 7") on most pages -- counted only among each page's
    first and last two lines, so a numbered heading repeated down the
    document ("Week 1", "Week 2") is never mistaken for one."""
    if pages < 2:
        return set()
    by_page: dict[int, list[str]] = {}
    for page_no, line, _ in lines:
        by_page.setdefault(page_no, []).append(line)
    seen: dict[str, set[int]] = {}
    for page_no, page_lines in by_page.items():
        for line in page_lines[:2] + page_lines[-2:]:
            seen.setdefault(re.sub(r"\d+", "#", line), set()).add(page_no)
    return {k for k, p in seen.items() if len(p) >= max(2, pages // 2)}


def _fallback_heading(line: str) -> bool:
    """No font signal: short, unpunctuated lines -- but never a bullet, a
    continuation starting lowercase, or a lead-in ending in a colon."""
    return (bool(_HEADING_LIKE.match(line)) and not _BULLET.match(line)
            and line[:1].isupper() and not line.endswith(":"))


def extract_from_pdf(data: bytes) -> ExtractedContent:
    from pypdf import PdfReader
    import io

    reader = PdfReader(io.BytesIO(data))
    lines = _pdf_lines(reader)
    running = _running_lines(lines, len(reader.pages))
    lines = [(p, t, s) for p, t, s in lines if re.sub(r"\d+", "#", t) not in running]

    sizes: dict[float, int] = {}
    for _, text, size in lines:
        sizes[size] = sizes.get(size, 0) + len(text)
    body_size = max(sizes, key=sizes.get) if sizes else 0.0
    larger = [s for s in sizes if body_size and s >= body_size * _HEADING_SIZE_RATIO]

    if larger:
        # Real typography: a heading is set larger than body text. The title
        # is the first line at the largest size.
        top = max(larger)
        title = next((t for _, t, s in lines if s == top), "")
        tagged = [(t, s in larger and len(t) <= 150) for _, t, s in lines]
        return _tagged_to_extracted(tagged, title=title,
                                    source_note="extracted from an uploaded PDF")
    text = "\n".join(t for _, t, _ in lines)
    return _plaintext_to_extracted(text, source_note="extracted from an uploaded PDF")


def _tagged_to_extracted(tagged: list[tuple[str, bool]], *, title: str,
                         source_note: str) -> ExtractedContent:
    builder = _SectionBuilder()
    body_buffer: list[str] = []

    def flush_body() -> None:
        if body_buffer:
            builder.body("\n".join(body_buffer))
            body_buffer.clear()

    for line, is_heading in tagged:
        if is_heading:
            flush_body()
            title = title or line
            builder.heading(line)
        else:
            body_buffer.append(line)
    flush_body()
    return ExtractedContent(page_title=title or "Untitled document",
                            sections=builder.finish(), source_note=source_note)


def _plaintext_to_extracted(text: str, *, source_note: str) -> ExtractedContent:
    """Line-by-line, not paragraph-by-paragraph: plain PDF text extraction
    does not reliably insert a blank line between paragraphs the way HTML or
    Markdown does (pypdf joins consecutive text runs with a single `\\n`
    regardless of visual spacing), so a blank-line split would merge a title
    line and its very next line of body text into one un-splittable block."""
    tagged = [(line, _fallback_heading(line))
              for line in (raw.strip() for raw in text.splitlines()) if line]
    return _tagged_to_extracted(tagged, title="", source_note=source_note)


# --------------------------------------------------------------------------
# Word (.docx)
# --------------------------------------------------------------------------

def extract_from_docx(data: bytes) -> ExtractedContent:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    builder = _SectionBuilder()
    title = ""
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style else "") or ""
        if style.startswith("Heading") or style == "Title":
            if not title:
                title = text
            builder.heading(text)
        elif style.startswith("List"):
            builder.body(f"- {text}")
        else:
            builder.body(text)

    for table in doc.tables:
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        builder.body("\n".join(rows))

    return ExtractedContent(
        page_title=title or "Untitled document", sections=builder.finish(),
        source_note="extracted from an uploaded Word document")


# --------------------------------------------------------------------------
# PowerPoint (.pptx)
# --------------------------------------------------------------------------

def extract_from_pptx(data: bytes) -> ExtractedContent:
    """One Section per slide: the slide's own title placeholder becomes the
    heading, every other text frame's bullet paragraphs become the body --
    kept separate rather than flattened into one blob, since that separation
    is exactly what makes PPT-to-web-copy work (see the design doc)."""
    import io

    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER_TYPE

    prs = Presentation(io.BytesIO(data))
    sections: list[Section] = []
    doc_title = ""

    for slide in prs.slides:
        heading = None
        body_parts: list[str] = []
        media_refs: list[str] = []
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                media_refs.append("image on this slide")
                continue
            if not getattr(shape, "has_text_frame", False):
                continue
            text = shape.text_frame.text.strip()
            if not text:
                continue
            is_title_placeholder = (
                getattr(shape, "is_placeholder", False)
                and shape.placeholder_format is not None
                and shape.placeholder_format.type in
                (PP_PLACEHOLDER_TYPE.TITLE, PP_PLACEHOLDER_TYPE.CENTER_TITLE)
            )
            if heading is None and (is_title_placeholder or (shape == slide.shapes[0])):
                heading = text
            else:
                body_parts.append("\n".join(f"- {line}" for line in text.splitlines() if line.strip()))

        if not doc_title and heading:
            doc_title = heading
        sections.append(Section(
            heading=heading, body="\n\n".join(body_parts),
            kind=guess_kind(heading, "\n".join(body_parts)),
            media_refs=media_refs,
        ))

    return ExtractedContent(
        page_title=doc_title or "Untitled presentation", sections=sections,
        source_note="extracted from an uploaded PowerPoint presentation")


# --------------------------------------------------------------------------
# Excel (.xlsx)
# --------------------------------------------------------------------------

def extract_from_xlsx(data: bytes) -> ExtractedContent:
    """One Section per sheet -- a sheet name as the heading, its rows
    flattened the same way a table block is elsewhere in this codebase."""
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sections: list[Section] = []
    for sheet in wb.worksheets:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append(" | ".join(cells))
        if not rows:
            continue
        sections.append(Section(
            heading=sheet.title, body="\n".join(rows),
            kind="fact-list" if len(rows) > 1 else "body"))

    return ExtractedContent(
        page_title=wb.worksheets[0].title if wb.worksheets else "Untitled spreadsheet",
        sections=sections, source_note="extracted from an uploaded Excel workbook")


# --------------------------------------------------------------------------
# Markdown (.md)
# --------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def extract_from_markdown(text: str) -> ExtractedContent:
    builder = _SectionBuilder()
    title = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        m = _MD_HEADING.match(para.splitlines()[0])
        if m:
            heading_text = m.group(2).strip()
            if not title:
                title = heading_text
            builder.heading(heading_text)
            rest = "\n".join(para.splitlines()[1:]).strip()
            if rest:
                builder.body(rest)
        else:
            builder.body(para)
    return ExtractedContent(
        page_title=title or "Untitled document", sections=builder.finish(),
        source_note="extracted from an uploaded Markdown file")


# --------------------------------------------------------------------------
# Image (flyer, screenshot of text) -- the one handler that costs money
# --------------------------------------------------------------------------

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE_MAX_OUTPUT_TOKENS = 2048

_IMAGE_SYSTEM_PROMPT = """You read an uploaded image (a flyer, a slide, a \
screenshot of text) for a content-rewriting tool. Transcribe every legible \
word verbatim, in reading order -- do not paraphrase or summarize the text \
itself. If a word or phrase is genuinely too small, blurry, or low-contrast \
to read with confidence, write "[illegible]" in its place rather than \
guessing a plausible-looking word -- a wrong transcription is worse than a \
gap, since this text gets rewritten and republished as if it were accurate.

Separately, in one or two sentences, describe any non-text visual content \
(a photo, a chart, a logo) a reader who cannot see the image would need to \
know about -- describe only what is actually visible, not what this kind of \
flyer/slide would typically show. If the image has one clear main \
heading/title, name it separately from the rest of the body text."""


class ImageExtraction(BaseModel):
    title: str | None = Field(
        description="The image's single clear main heading/title, if one is "
                    "visible, else null.")
    body_text: str = Field(
        description="Every other legible word, transcribed verbatim, in "
                    "reading order.")
    visual_description: str = Field(
        description="One or two sentences describing non-text visual "
                    "content (photos, charts, layout) a reader who cannot "
                    "see the image would need.")


@dataclass
class ImageExtractionOutcome:
    extracted: ExtractedContent | None = None
    cost_usd: float = 0.0
    skipped_reason: str = ""


def extract_from_image(image_bytes: bytes, media_type: str, *, budget=None,
                       model: str | None = None, client=None) -> ImageExtractionOutcome:
    from .. import llm_cost, llm_provider

    budget = budget or llm_cost.Budget()
    model = model or llm_provider.default_model("fast")
    media_type = (media_type or "").lower()
    if media_type not in SUPPORTED_IMAGE_TYPES:
        return ImageExtractionOutcome(
            skipped_reason=f"unsupported image type {media_type or '(unknown)'}; "
                          "expected JPEG, PNG, GIF or WebP")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return ImageExtractionOutcome(
            skipped_reason=f"image is {len(image_bytes) // 1024} KB, over the "
                          f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB cap")
    if not image_bytes:
        return ImageExtractionOutcome(skipped_reason="no image data was received")

    try:
        parsed, cost = llm_provider.call_structured(
            model, _IMAGE_SYSTEM_PROMPT, "Read this image.", ImageExtraction, budget,
            image=(image_bytes, media_type), max_output_tokens=_IMAGE_MAX_OUTPUT_TOKENS,
            effort="medium", client=client, label="content extractor")
    except llm_cost.CredentialsMissing as exc:
        return ImageExtractionOutcome(skipped_reason=str(exc))
    except llm_cost.BudgetExceeded as exc:
        budget.skipped += 1
        return ImageExtractionOutcome(skipped_reason=str(exc))
    except Exception as exc:
        # llm_provider already turned this into a labeled, human-readable
        # message -- explain_api_failure again here would double-wrap it.
        return ImageExtractionOutcome(skipped_reason=str(exc))

    section = Section(
        heading=parsed.title, body=parsed.body_text.strip(), kind="body",
        media_refs=[parsed.visual_description] if parsed.visual_description else [])
    return ImageExtractionOutcome(
        extracted=ExtractedContent(
            page_title=parsed.title or "Untitled image", sections=[section],
            source_note="extracted from an uploaded image"),
        cost_usd=cost)
