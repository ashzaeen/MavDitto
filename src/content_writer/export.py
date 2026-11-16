"""Export a draft as Markdown, plain text, HTML, Word, or PDF. One
implementation per format so every export carries the same content in the
same order, for both the section/item shape every template but Compose
produces and Compose's own block shape."""

from __future__ import annotations

import html
import io
import re
from typing import Any

FORMATS = {
    "md": ("text/markdown", "md"),
    "txt": ("text/plain", "txt"),
    "html": ("text/html", "html"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
}

UTA_BLUE = "#0064b1"
UTA_HEADING = "#003865"
UTA_ORANGE = "#f58025"
BORDER = "rgba(0, 56, 101, 0.14)"
WARN_BG = "#fdf1e3"
WARN_TEXT = "#b45309"


def _blocks(body: str):
    """Split a body into ('p', text) and ('ul', [items]) blocks -- the writer
    uses '- ' lines for lists."""
    out, bullets = [], []
    for para in re.split(r"\n\s*\n", body.strip()):
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and all(re.match(r"^\s*[-*•]\s+", ln) for ln in lines):
            out.append(("ul", [re.sub(r"^\s*[-*•]\s+", "", ln) for ln in lines]))
        elif lines:
            out.append(("p", " ".join(ln.strip() for ln in lines)))
    return out


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "content"


def render(fmt: str, *, title: str, subtitle: str = "", sections: list[dict[str, Any]] | None = None,
           items: list[str] | None = None, blocks: list[dict[str, Any]] | None = None,
           ) -> tuple[str, str, bytes]:
    """-> (filename, mime type, file bytes)."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
    mime, ext = FORMATS[fmt]
    name = f"{_slug(title)}.{ext}"

    if blocks:
        return name, mime, _render_blocks(fmt, title, subtitle, blocks)

    sections = sections or []
    items = items or []

    if fmt == "pdf":
        return name, mime, _print_pdf(_page_html(title, sections=sections, items=items))

    if fmt == "docx":
        from docx import Document
        doc = Document()
        doc.add_heading(title, level=1)
        for s in sections:
            if s.get("heading"):
                doc.add_heading(s["heading"], level=2)
            for kind, val in _blocks(s.get("body", "")):
                if kind == "ul":
                    for it in val:
                        doc.add_paragraph(it, style="List Bullet")
                else:
                    doc.add_paragraph(val)
        for it in items:
            doc.add_paragraph(it, style="List Number")
        buf = io.BytesIO()
        doc.save(buf)
        return name, mime, buf.getvalue()

    if fmt == "html":
        return name, mime, _page_html(title, sections=sections, items=items).encode("utf-8")

    lines: list[str] = []
    if fmt == "md":
        lines.append(f"# {title}\n")
        for s in sections:
            if s.get("heading"):
                lines.append(f"## {s['heading']}\n")
            lines.append(s.get("body", "").strip() + "\n")
        lines.extend(f"{i + 1}. {it}" for i, it in enumerate(items))
    else:
        lines.append(title + "\n")
        for s in sections:
            if s.get("heading"):
                lines.append(s["heading"])
            lines.append(s.get("body", "").strip() + "\n")
        lines.extend(items)
    return name, mime, ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _page_html(title: str, *, sections: list[dict[str, Any]], items: list[str]) -> str:
    e = html.escape
    parts = [f"<h1>{e(title)}</h1>"]
    for s in sections:
        if s.get("heading"):
            parts.append(f"<h2>{e(s['heading'])}</h2>")
        for kind, val in _blocks(s.get("body", "")):
            parts.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in val) + "</ul>"
                         if kind == "ul" else f"<p>{e(val)}</p>")
    if items:
        parts.append("<ol>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ol>")
    return _html_document(e(title), "\n".join(parts))


def _html_document(title_html: str, body_html: str) -> str:
    """A standalone, inline-styled document -- no external stylesheet, so it
    renders identically in a browser tab, an exported .html file, and the
    headless print that becomes the PDF."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title_html}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
         color: #1a1a1a; max-width: 760px; margin: 40px auto; padding: 0 24px;
         line-height: 1.6; }}
  h1 {{ color: {UTA_HEADING}; font-size: 28px; margin-bottom: 4px; }}
  h2 {{ color: {UTA_HEADING}; font-size: 19px; margin-top: 28px; }}
  p {{ margin: 10px 0; }}
  ul {{ margin: 10px 0; padding-left: 22px; }}
</style></head>
<body>{body_html}</body></html>"""


def _print_pdf(html_str: str) -> bytes:
    """Rendered via a one-off headless Chromium launch -- playwright is
    already a dependency of this project (see src/fetch.py's JS-rendering
    fallback); this is a separate, self-contained launch because that one is
    for fetching remote pages, not printing a locally-built document."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_str, wait_until="load")
            return page.pdf(format="Letter", print_background=True,
                            margin={"top": "0.6in", "bottom": "0.6in",
                                   "left": "0.6in", "right": "0.6in"})
        finally:
            browser.close()


# --------------------------------------------------------------------------
# Compose mode: blocks
# --------------------------------------------------------------------------

def _placeholder_note(b: dict[str, Any]) -> str:
    return str(b.get("placeholderNote") or "").strip() if b.get("isPlaceholder") else ""


def _render_blocks(fmt: str, title: str, subtitle: str, blocks: list[dict[str, Any]]) -> bytes:
    if fmt == "pdf":
        return _print_pdf(_blocks_html(title, subtitle, blocks))
    if fmt == "html":
        return _blocks_html(title, subtitle, blocks).encode("utf-8")
    if fmt == "docx":
        return _blocks_docx(title, subtitle, blocks)
    return _blocks_text(fmt, title, subtitle, blocks)


def _blocks_text(fmt: str, title: str, subtitle: str, blocks: list[dict[str, Any]]) -> bytes:
    md = fmt == "md"
    lines = [f"# {title}" if md else title]
    if subtitle:
        lines.append(subtitle)
    lines.append("")
    for b in blocks:
        t = b.get("type")
        note = _placeholder_note(b)
        if t in ("hero", "heading", "text"):
            if b.get("heading"):
                lines.append(f"## {b['heading']}" if md else b["heading"])
            if b.get("subheading"):
                lines.append(b["subheading"])
            if b.get("body"):
                lines.append(b["body"])
        elif t == "image":
            lines.append(f"[IMAGE PLACEHOLDER: {b.get('imageAlt', '')}]"
                         + (f" -- {b['imageCaption']}" if b.get("imageCaption") else ""))
        elif t == "quote":
            lines.append((f"> {b.get('quoteText', '')}" if md else f'"{b.get("quoteText", "")}"')
                         + (f" — {b['quoteAttribution']}" if b.get("quoteAttribution") else ""))
        elif t == "stat":
            lines.append(f"STAT: {b.get('statValue', '')} — {b.get('statLabel', '')}")
        elif t == "links":
            for link in b.get("links", []):
                lines.append(f"- {link.get('text', '')}: {link.get('url', '')}")
        elif t == "cta":
            link = (b.get("links") or [{}])[0]
            lines.append(f"CTA: {b.get('heading', '')} -> {link.get('url', '')}")
        elif t == "divider":
            lines.append("---" if md else "----------")
        if note:
            lines.append(f"[Placeholder: {note}]")
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _blocks_docx(title: str, subtitle: str, blocks: list[dict[str, Any]]) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    doc.add_heading(title, level=1)
    if subtitle:
        doc.add_paragraph(subtitle)

    def placeholder_line(b):
        note = _placeholder_note(b)
        if note:
            p = doc.add_paragraph()
            run = p.add_run(f"[Placeholder: {note}]")
            run.italic = True

    for b in blocks:
        t = b.get("type")
        if t in ("hero", "heading"):
            doc.add_heading(b.get("heading", ""), level=1 if t == "hero" else 2)
            if b.get("subheading"):
                doc.add_paragraph(b["subheading"])
            if b.get("body"):
                doc.add_paragraph(b["body"])
        elif t == "text":
            if b.get("heading"):
                doc.add_heading(b["heading"], level=2)
            for kind, val in _blocks(b.get("body", "")):
                if kind == "ul":
                    for it in val:
                        doc.add_paragraph(it, style="List Bullet")
                else:
                    doc.add_paragraph(val)
        elif t == "image":
            p = doc.add_paragraph()
            p.add_run(f"[Image: {b.get('imageAlt', '')}]").bold = True
            if b.get("imageCaption"):
                doc.add_paragraph(b["imageCaption"])
        elif t == "quote":
            p = doc.add_paragraph()
            run = p.add_run(f"“{b.get('quoteText', '')}”")
            run.italic = True
            if b.get("quoteAttribution"):
                doc.add_paragraph(f"— {b['quoteAttribution']}")
        elif t == "stat":
            p = doc.add_paragraph()
            p.add_run(f"{b.get('statValue', '')} — {b.get('statLabel', '')}").bold = True
        elif t == "links":
            for link in b.get("links", []):
                doc.add_paragraph(f"{link.get('text', '')} ({link.get('url', '')})", style="List Bullet")
        elif t == "cta":
            link = (b.get("links") or [{}])[0]
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run(f"[ {b.get('heading', '')} ]").bold = True
            if link.get("url"):
                doc.add_paragraph(link["url"]).alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif t == "divider":
            doc.add_paragraph("—" * 20)
        placeholder_line(b)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _blocks_html(title: str, subtitle: str, blocks: list[dict[str, Any]]) -> str:
    e = html.escape
    parts: list[str] = []
    badge = ('<span style="display:inline-block;font-size:11px;font-weight:700;'
            f'color:{WARN_TEXT};background:{WARN_BG};border-radius:999px;'
            'padding:2px 9px;margin-left:8px;vertical-align:middle;">Placeholder</span>')

    def note_html(b):
        note = _placeholder_note(b)
        return (f'<p style="font-size:12.5px;color:{WARN_TEXT};font-style:italic;'
                f'margin-top:6px;">Placeholder: {e(note)}</p>') if note else ""

    i, n = 0, len(blocks)
    while i < n:
        b = blocks[i]
        t = b.get("type")
        ph = badge if b.get("isPlaceholder") else ""

        if t == "hero":
            cta = ""
            parts.append(
                f'<div style="background:{UTA_HEADING};color:#fff;padding:44px 32px;'
                f'border-radius:10px;text-align:center;margin:0 0 28px;">'
                f'<h1 style="margin:0 0 8px;font-size:30px;">{e(b.get("heading", ""))}{ph}</h1>'
                + (f'<p style="margin:0 0 18px;font-size:16px;opacity:0.9;">{e(b.get("subheading", ""))}</p>'
                  if b.get("subheading") else "")
                + (f'<p style="margin:0 0 18px;">{e(b.get("body", ""))}</p>' if b.get("body") else "")
                + '</div>' + note_html(b))
            i += 1
            continue

        if t == "stat":
            group = []
            while i < n and blocks[i].get("type") == "stat":
                group.append(blocks[i])
                i += 1
            tiles = "".join(
                f'<div style="flex:1 1 160px;border:1px solid {BORDER};border-radius:8px;'
                f'padding:18px;text-align:center;">'
                f'<div style="font-size:26px;font-weight:800;color:{UTA_BLUE};">{e(g.get("statValue", ""))}</div>'
                f'<div style="font-size:12.5px;color:#555;text-transform:uppercase;'
                f'letter-spacing:0.03em;">{e(g.get("statLabel", ""))}</div>'
                f'{badge if g.get("isPlaceholder") else ""}{note_html(g)}</div>'
                for g in group)
            parts.append(f'<div style="display:flex;flex-wrap:wrap;gap:14px;margin:24px 0;">{tiles}</div>')
            continue

        if t == "heading":
            parts.append(f'<h2 style="color:{UTA_HEADING};margin-top:32px;">{e(b.get("heading", ""))}{ph}</h2>'
                         + note_html(b))
        elif t == "text":
            if b.get("heading"):
                parts.append(f'<h2 style="color:{UTA_HEADING};margin-top:28px;">{e(b["heading"])}{ph}</h2>')
            for kind, val in _blocks(b.get("body", "")):
                parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in val) + "</ul>"
                             if kind == "ul" else f"<p>{e(val)}</p>")
            parts.append(note_html(b))
        elif t == "image":
            parts.append(
                f'<div style="border:1.5px dashed {BORDER};border-radius:8px;padding:28px;'
                f'text-align:center;color:#666;margin:20px 0;">'
                f'<div style="font-weight:600;">Image{ph}</div>'
                f'<div style="font-size:13px;margin-top:4px;">{e(b.get("imageAlt", ""))}</div>'
                + (f'<div style="font-size:12px;color:#888;margin-top:4px;">{e(b.get("imageCaption", ""))}</div>'
                  if b.get("imageCaption") else "")
                + f'</div>{note_html(b)}')
        elif t == "quote":
            parts.append(
                f'<blockquote style="border-left:3px solid {UTA_ORANGE};margin:22px 0;'
                f'padding:4px 20px;font-style:italic;color:#333;">'
                f'“{e(b.get("quoteText", ""))}”{ph}'
                + (f'<footer style="margin-top:8px;font-style:normal;font-size:13px;color:#666;">'
                  f'— {e(b.get("quoteAttribution", ""))}</footer>' if b.get("quoteAttribution") else "")
                + f'</blockquote>{note_html(b)}')
        elif t == "links":
            items = "".join(f'<li><a href="{e(link.get("url", ""))}" style="color:{UTA_BLUE};">'
                            f'{e(link.get("text", ""))}</a></li>' for link in b.get("links", []))
            parts.append(f'<ul>{items}</ul>{ph}{note_html(b)}')
        elif t == "cta":
            link = (b.get("links") or [{}])[0]
            parts.append(
                f'<div style="text-align:center;margin:26px 0;">'
                f'<a href="{e(link.get("url", "#"))}" style="display:inline-block;'
                f'background:{UTA_ORANGE};color:#fff;font-weight:700;text-decoration:none;'
                f'padding:12px 28px;border-radius:6px;">{e(b.get("heading", ""))}</a>{ph}</div>'
                + note_html(b))
        elif t == "divider":
            parts.append(f'<hr style="border:none;border-top:1px solid {BORDER};margin:28px 0;">')
        i += 1

    header = f'<h1 style="color:{UTA_HEADING};">{e(title)}</h1>'
    if subtitle:
        header += f'<p style="font-size:16px;color:#555;">{e(subtitle)}</p>'
    return _html_document(e(title), header + "\n".join(parts))
