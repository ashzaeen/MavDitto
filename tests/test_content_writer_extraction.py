"""Content Writer's per-format extraction handlers -- each a pure function
over bytes already in memory (no network), except extract_from_image, which
is stubbed the same way test_alt_text.py stubs the Anthropic client: no
network, no credentials needed.
"""

import io
from types import SimpleNamespace

from src.content_writer.extraction import (
    extract_from_docx, extract_from_image, extract_from_markdown,
    extract_from_pdf, extract_from_pptx, extract_from_url, extract_from_xlsx,
    guess_kind,
)
from src.content_writer.models import ExtractedContent, Section
from src.models import FetchResult


# --------------------------------------------------------------------------
# guess_kind
# --------------------------------------------------------------------------

def test_a_question_heading_is_guessed_as_faq_item():
    assert guess_kind("How do I apply?", "Short answer.") == "faq-item"


def test_an_faq_labeled_heading_is_guessed_as_faq_item():
    assert guess_kind("Admissions FAQ", "Some content here.") == "faq-item"


def test_an_action_heading_with_short_body_is_guessed_as_cta():
    assert guess_kind("Apply now", "Start your application today.") == "cta"


def test_a_bulleted_body_is_guessed_as_fact_list():
    body = "\n".join(f"- fact {i}" for i in range(4))
    assert guess_kind("Quick facts", body) == "fact-list"


def test_an_ordinary_paragraph_is_guessed_as_body():
    assert guess_kind("About us", "A long paragraph of plain prose. " * 5) == "body"


# --------------------------------------------------------------------------
# URL
# --------------------------------------------------------------------------

class _StubFetcher:
    def __init__(self, html, status=200):
        self.html = html
        self.status = status

    def fetch(self, url, **kw):
        return FetchResult(url=url, fetched_url=url, status=self.status, html=self.html)


def test_extract_from_url_groups_content_under_headings():
    html = (
        "<html><head><title>Campus Life</title></head><body><main>"
        "<h1>Campus Life</h1><p>Intro paragraph.</p>"
        "<h2>Housing</h2><p>Housing details here.</p>"
        "<h2>Dining</h2><p>Dining details here.</p>"
        "</main></body></html>"
    )
    result = extract_from_url("https://e.edu/campus", _StubFetcher(html))
    assert result.page_title == "Campus Life"
    headings = [s.heading for s in result.sections]
    assert "Housing" in headings
    assert "Dining" in headings


def test_extract_from_url_content_before_any_heading_becomes_intro():
    html = "<html><body><main><p>Leading text.</p><h2>Later</h2><p>Body.</p></main></body></html>"
    result = extract_from_url("https://e.edu/x", _StubFetcher(html))
    assert result.sections[0].heading is None
    assert result.sections[0].kind == "intro"
    assert "Leading text" in result.sections[0].body


def test_extract_from_url_raises_on_a_failed_fetch():
    fetcher = _StubFetcher("", status=404)
    try:
        extract_from_url("https://e.edu/missing", fetcher)
        assert False, "expected a RuntimeError"
    except RuntimeError as exc:
        assert "could not fetch" in str(exc)


def test_extract_from_url_flattens_lists_and_tables():
    html = (
        "<html><body><main><h1>T</h1>"
        "<h2>Steps</h2><ul><li>First</li><li>Second</li></ul>"
        "<h2>Data</h2><table><tr><th>Col</th></tr><tr><td>1</td></tr></table>"
        "</main></body></html>"
    )
    result = extract_from_url("https://e.edu/x", _StubFetcher(html))
    steps = next(s for s in result.sections if s.heading == "Steps")
    assert "First" in steps.body and "Second" in steps.body
    data = next(s for s in result.sections if s.heading == "Data")
    assert "Col" in data.body


def test_extract_from_url_attaches_images_links_and_buttons_to_the_right_section():
    html = (
        "<html><head><title>T</title></head><body>"
        "<nav><a href=\"/admissions\">Admissions</a></nav>"
        "<main>"
        "<h1>Engineering</h1>"
        "<h2>Gallery</h2><img src=\"/campus.jpg\" alt=\"Campus quad\">"
        "<h2>Apply</h2><p>Ready? <a href=\"https://e.edu/apply\" class=\"btn\">Apply Now</a></p>"
        "<h2>Aid</h2><p>See the <a href=\"https://e.edu/aid.pdf\">aid form</a>.</p>"
        "</main>"
        "<footer>Copyright 2026</footer>"
        "</body></html>"
    )
    result = extract_from_url("https://e.edu/engineering", _StubFetcher(html))

    gallery = next(s for s in result.sections if s.heading == "Gallery")
    assert gallery.media_refs == ["Campus quad"]

    apply_section = next(s for s in result.sections if s.heading == "Apply")
    button = next(l for l in apply_section.links if l.text == "Apply Now")
    assert button.is_button is True
    assert button.url == "https://e.edu/apply"

    aid_section = next(s for s in result.sections if s.heading == "Aid")
    doc_link = next(l for l in aid_section.links if l.text == "aid form")
    assert doc_link.is_document is True
    assert doc_link.is_button is False


def test_extract_from_url_does_not_attach_nav_or_footer_links_to_any_section():
    html = (
        "<html><body><nav><a href=\"/admissions\">Admissions</a></nav>"
        "<main><h1>T</h1><p>Body.</p></main>"
        "<footer><a href=\"/privacy\">Privacy</a></footer></body></html>"
    )
    result = extract_from_url("https://e.edu/x", _StubFetcher(html))
    all_urls = {l.url for s in result.sections for l in s.links}
    assert not any(u.endswith(("/admissions", "/privacy")) for u in all_urls)


def test_extract_from_url_carries_nav_and_footer_text_as_page_chrome_context():
    html = (
        "<html><body><nav><a href=\"/admissions\">Admissions</a></nav>"
        "<main><h1>T</h1><p>Body.</p></main>"
        "<footer>Copyright 2026</footer></body></html>"
    )
    result = extract_from_url("https://e.edu/x", _StubFetcher(html))
    assert "Admissions" in result.page_chrome_context
    assert "Copyright 2026" in result.page_chrome_context


def test_extract_from_url_captures_a_video_embed_as_a_media_ref():
    html = (
        "<html><body><main><h1>T</h1>"
        "<h2>Our Story</h2>"
        "<iframe src=\"https://www.youtube.com/embed/abc\" title=\"Our Story\"></iframe>"
        "</main></body></html>"
    )
    result = extract_from_url("https://e.edu/x", _StubFetcher(html))
    story = next(s for s in result.sections if s.heading == "Our Story")
    assert any("video (youtube)" in ref for ref in story.media_refs)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _make_pdf(lines: list[tuple[int, int, int, str]]) -> bytes:
    """A minimal single-page PDF with each (font_size, x, y, text) drawn as
    its own Tj operator -- just enough for pypdf to extract real text back."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    ops = []
    for size, x, y, text in lines:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"BT /F1 {size} Tf {x} {y} Td ({escaped}) Tj ET")
    content = " ".join(ops).encode("latin-1")

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    page = writer.pages[0]
    page[NameObject("/Contents")] = writer._add_object(
        DecodedStreamObject.initialize_from_dictionary(
            {"__streamdata__": content, NameObject("/Length"): len(content)}))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_headings_come_from_font_size_not_line_length():
    """A syllabus split into 110 sections: its short fact lines (class times,
    TA names, due dates) were all taken for headings, stranding every fact
    outside a body. Typography is the real signal."""
    data = _make_pdf([
        (20, 72, 740, "CSE 3380 Syllabus for Spring 2026"),
        (16, 72, 700, "Time and Place of Class Meetings"),
        (11, 72, 680, "Fr 4:00PM - 6:50PM NH 112"),
        (11, 72, 665, "Teaching Assistant"),
        (11, 72, 650, "Satyal, Sachit"),
        (16, 72, 620, "Assignments"),
        (11, 72, 600, "Assignment 1: Submission date: February 13"),
    ])
    result = extract_from_pdf(data)
    assert result.page_title == "CSE 3380 Syllabus for Spring 2026"
    headings = [s.heading for s in result.sections]
    assert "Time and Place of Class Meetings" in headings and "Assignments" in headings
    assert "Satyal, Sachit" not in headings
    meetings = next(s for s in result.sections if s.heading == "Time and Place of Class Meetings")
    assert "4:00PM" in meetings.body and "Satyal, Sachit" in meetings.body


def _make_multipage_pdf(pages: list[list[tuple[int, int, int, str]]]) -> bytes:
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for lines in pages:
        writer.add_page(PdfReader(io.BytesIO(_make_pdf(lines))).pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _page_lines(n):
    return [(11, 72, 760, f"CSE 3380 Syllabus Updated: 08/11/2025 Page {n} of 3"),
            (11, 72, 740, "Intro line for this page."),
            (16, 72, 700, f"Week {n}"),
            (11, 72, 680, f"Body text for week {n}."),
            (11, 72, 660, "More body text."),
            (11, 72, 640, "Closing line of the page.")]


def test_pdf_running_headers_are_dropped():
    result = extract_from_pdf(_make_multipage_pdf([_page_lines(n) for n in (1, 2, 3)]))
    all_text = " ".join((s.heading or "") + " " + s.body for s in result.sections)
    assert "Syllabus Updated" not in all_text


def test_numbered_headings_down_the_document_are_not_running_headers():
    result = extract_from_pdf(_make_multipage_pdf([_page_lines(n) for n in (1, 2, 3)]))
    assert [s.heading for s in result.sections if s.heading] == ["Week 1", "Week 2", "Week 3"]
    assert result.page_title == "Week 1"


def test_single_size_pdf_falls_back_but_never_makes_a_bullet_a_heading():
    data = _make_pdf([
        (12, 72, 700, "Technology Requirements"),
        (12, 72, 680, "- A computer capable of connecting to the internet"),
        (12, 72, 660, "transformations, determinants and"),
        (12, 72, 640, "includes the following policies:"),
    ])
    headings = [s.heading for s in extract_from_pdf(data).sections]
    assert headings == ["Technology Requirements"]


def test_extract_from_pdf_reads_text_and_treats_short_lines_as_headings():
    data = _make_pdf([
        (24, 72, 700, "Campus Life"),
        (12, 72, 650, "Welcome to campus. This is the intro paragraph."),
    ])
    result = extract_from_pdf(data)
    assert "Campus Life" in [s.heading for s in result.sections] or result.page_title == "Campus Life"


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def _make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Campus Life", level=1)
    doc.add_paragraph("Intro paragraph.")
    doc.add_heading("Housing", level=2)
    doc.add_paragraph("Housing details here.")
    doc.add_paragraph("On-campus", style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_from_docx_reads_headings_and_body():
    result = extract_from_docx(_make_docx())
    assert result.page_title == "Campus Life"
    housing = next(s for s in result.sections if s.heading == "Housing")
    assert "Housing details here." in housing.body
    assert "On-campus" in housing.body


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------

def _make_pptx() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    layout = prs.slide_layouts[1]  # title + content
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = "Why Choose UTA"
    body = slide.placeholders[1]
    body.text_frame.text = "Top-ranked programs"
    body.text_frame.add_paragraph().text = "Affordable tuition"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_extract_from_pptx_reads_slide_title_and_bullets():
    result = extract_from_pptx(_make_pptx())
    assert result.page_title == "Why Choose UTA"
    assert len(result.sections) == 1
    section = result.sections[0]
    assert section.heading == "Why Choose UTA"
    assert "Top-ranked programs" in section.body
    assert "Affordable tuition" in section.body


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------

def _make_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Enrollment"
    ws.append(["Year", "Students"])
    ws.append([2024, 100])
    ws.append([2025, 120])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_from_xlsx_reads_sheet_as_a_section():
    result = extract_from_xlsx(_make_xlsx())
    assert result.sections[0].heading == "Enrollment"
    assert "Year" in result.sections[0].body
    assert "2024" in result.sections[0].body


def test_extract_from_xlsx_skips_a_blank_sheet():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Empty"
    buf = io.BytesIO()
    wb.save(buf)
    result = extract_from_xlsx(buf.getvalue())
    assert result.sections == []


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def test_extract_from_markdown_reads_real_heading_markers():
    md = (
        "# Campus Life\n\nIntro text.\n\n"
        "## Housing\n\nHousing details.\n\n"
        "## Dining\n\nDining details.\n"
    )
    result = extract_from_markdown(md)
    assert result.page_title == "Campus Life"
    headings = [s.heading for s in result.sections]
    assert "Housing" in headings and "Dining" in headings


def test_extract_from_markdown_content_before_first_heading_is_intro():
    md = "Some leading text.\n\n# Title\n\nBody.\n"
    result = extract_from_markdown(md)
    assert result.sections[0].heading is None
    assert result.sections[0].kind == "intro"


# --------------------------------------------------------------------------
# Image (stubbed Anthropic client -- no network, no credentials)
# --------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake but nonempty png data"


class _StubImageResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.usage = SimpleNamespace(
            input_tokens=800, output_tokens=60,
            cache_creation_input_tokens=0, cache_read_input_tokens=0)
        self.stop_reason = "end_turn"


class _StubAnthropicClient:
    def __init__(self, parsed=None):
        self.parsed = parsed
        self.messages = SimpleNamespace(
            count_tokens=lambda **kw: SimpleNamespace(input_tokens=800),
            parse=lambda **kw: _StubImageResponse(self.parsed))


def test_extract_from_image_returns_a_section_from_the_parsed_fields(monkeypatch):
    import anthropic

    from src.content_writer.extraction import ImageExtraction

    parsed = ImageExtraction(
        title="Fall Open House", body_text="Join us October 5th.",
        visual_description="A photo of students on the main quad.")
    monkeypatch.setattr(anthropic, "Anthropic", lambda: _StubAnthropicClient(parsed))

    outcome = extract_from_image(PNG_BYTES, "image/png", model="claude-opus-5")
    assert outcome.extracted is not None
    assert outcome.extracted.page_title == "Fall Open House"
    section = outcome.extracted.sections[0]
    assert section.heading == "Fall Open House"
    assert "October 5th" in section.body
    assert section.media_refs == ["A photo of students on the main quad."]


def test_extract_from_image_rejects_an_unsupported_type():
    outcome = extract_from_image(PNG_BYTES, "image/svg+xml")
    assert outcome.extracted is None
    assert "unsupported" in outcome.skipped_reason


def test_extract_from_image_rejects_an_oversized_image():
    from src.content_writer.extraction import MAX_IMAGE_BYTES

    outcome = extract_from_image(b"x" * (MAX_IMAGE_BYTES + 1), "image/png")
    assert outcome.extracted is None
    assert "MB cap" in outcome.skipped_reason


def test_extract_from_image_rejects_empty_data():
    outcome = extract_from_image(b"", "image/png")
    assert outcome.extracted is None


def test_extract_from_image_respects_the_budget(monkeypatch):
    import anthropic

    from src.llm_cost import Budget

    monkeypatch.setattr(anthropic, "Anthropic", lambda: _StubAnthropicClient())
    tiny_budget = Budget(max_usd=0.0000001)
    outcome = extract_from_image(PNG_BYTES, "image/png", budget=tiny_budget, model="claude-opus-5")
    assert outcome.extracted is None
    assert outcome.skipped_reason
