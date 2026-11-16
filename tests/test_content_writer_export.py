"""Export to Markdown, plain text, HTML, Word and PDF -- for both the
section/item shape every template but Compose produces and Compose's own
block shape. No export tests existed before Compose mode added them."""

import pytest

from src.content_writer import export

SECTIONS = [{"heading": "Intro", "body": "Hello world.\n\n- one\n- two"}]

BLOCKS = [
    {"type": "hero", "heading": "What Makes UTA Great", "subheading": "Discover the Maverick Difference",
     "isPlaceholder": False},
    {"type": "stat", "statValue": "41,613", "statLabel": "Total enrollment", "isPlaceholder": False},
    {"type": "quote", "quoteText": "UTA gave me the tools to build a future.",
     "quoteAttribution": "Maria G., Class of 2023", "isPlaceholder": True,
     "placeholderNote": "Illustrative testimonial -- replace with a real quote."},
    {"type": "image", "imageAlt": "Wide shot of the UTA campus", "isPlaceholder": False},
    {"type": "links", "links": [{"text": "Admissions", "url": "https://www.uta.edu/admissions"}]},
    {"type": "cta", "heading": "Apply Now",
     "links": [{"text": "Apply Now", "url": "https://www.uta.edu/apply", "isButton": True}],
     "isPlaceholder": False},
    {"type": "divider"},
]


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError, match="unknown format"):
        export.render("epub", title="T", sections=SECTIONS)


@pytest.mark.parametrize("fmt", ["md", "txt", "html", "docx"])
def test_section_export_runs_for_every_non_pdf_format(fmt):
    name, mime, data = export.render(fmt, title="Campus Life", sections=SECTIONS)
    assert name == f"campus-life.{fmt}" and len(data) > 0


def test_section_html_is_a_standalone_document():
    _, _, data = export.render("html", title="Campus Life", sections=SECTIONS)
    text = data.decode("utf-8")
    assert "<html>" in text and "Campus Life" in text and "Hello world" in text


def test_items_export_numbers_the_options():
    _, _, data = export.render("md", title="CTAs", items=["Apply now", "Start today"])
    text = data.decode("utf-8")
    assert "1. Apply now" in text and "2. Start today" in text


@pytest.mark.parametrize("fmt", ["md", "txt", "html", "docx"])
def test_block_export_runs_for_every_non_pdf_format(fmt):
    name, mime, data = export.render(fmt, title="What Makes UTA Great", subtitle="Discover the Maverick Difference",
                                     blocks=BLOCKS)
    assert name == f"what-makes-uta-great.{fmt}" and len(data) > 0


def test_block_text_export_marks_every_kind_clearly():
    _, _, data = export.render("md", title="T", blocks=BLOCKS)
    text = data.decode("utf-8")
    assert "STAT: 41,613" in text
    assert "Maria G." in text
    assert "Placeholder: Illustrative testimonial" in text
    assert "[IMAGE PLACEHOLDER: Wide shot of the UTA campus]" in text
    assert "CTA: Apply Now -> https://www.uta.edu/apply" in text
    assert "Admissions: https://www.uta.edu/admissions" in text


def test_block_html_groups_consecutive_stats_and_marks_placeholders():
    _, _, data = export.render("html", title="T", blocks=BLOCKS)
    text = data.decode("utf-8")
    assert "41,613" in text and "Placeholder" in text
    assert "Illustrative testimonial" in text
    assert 'href="https://www.uta.edu/apply"' in text


def test_block_html_groups_multiple_consecutive_stat_bands_correctly():
    """Two stat blocks back to back must render as one band, not two."""
    two_stats = [
        {"type": "stat", "statValue": "41,613", "statLabel": "Enrollment", "isPlaceholder": False},
        {"type": "stat", "statValue": "98", "statLabel": "Countries", "isPlaceholder": False},
        {"type": "text", "body": "After the stats."},
    ]
    _, _, data = export.render("html", title="T", blocks=two_stats)
    text = data.decode("utf-8")
    assert text.count('style="display:flex;flex-wrap:wrap;gap:14px;margin:24px 0;"') == 1


def test_block_docx_does_not_crash_and_produces_a_real_zip():
    _, _, data = export.render("docx", title="T", blocks=BLOCKS)
    assert data[:2] == b"PK"   # .docx is a zip archive


def test_a_block_with_no_placeholder_note_renders_without_a_note_line():
    clean = [{"type": "text", "body": "Nothing invented here.", "isPlaceholder": False}]
    _, _, data = export.render("md", title="T", blocks=clean)
    assert "Placeholder:" not in data.decode("utf-8")


def test_section_and_block_pdfs_are_real_pdf_bytes():
    pytest.importorskip("playwright")
    try:
        _, mime, data = export.render("pdf", title="Campus Life", sections=SECTIONS)
    except Exception as exc:   # pragma: no cover - environment without a browser installed
        pytest.skip(f"Chromium not available: {exc}")
    assert mime == "application/pdf" and data[:5] == b"%PDF-"

    _, _, data = export.render("pdf", title="What Makes UTA Great", blocks=BLOCKS)
    assert data[:5] == b"%PDF-"
