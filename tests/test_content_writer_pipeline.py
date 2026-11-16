"""write_page's orchestration -- extract -> rewrite -> guardrail retry loop.
rewrite_page/guardrail_check are stubbed at the pipeline module's own import
boundary (same pattern test_link_checker_pipeline.py uses for check_all), so
these tests cover orchestration, not the LLM-calling internals already
covered in test_content_writer_rewrite.py/test_content_writer_guardrail.py.
"""

from src.content_writer import pipeline
from src.content_writer.guardrail import GuardrailResult
from src.content_writer.models import ExtractedContent, RewriteOptions, Section, StructuredContent
from src.content_writer.pipeline import ContentInput, extract_content, write_page
from src.models import FetchResult


class _StubFetcher:
    def __init__(self, html):
        self.html = html

    def fetch(self, url, **kw):
        return FetchResult(url=url, fetched_url=url, status=200, html=self.html)


# --------------------------------------------------------------------------
# extract_content dispatch
# --------------------------------------------------------------------------

def test_extract_content_dispatches_url_to_the_url_handler():
    html = "<html><body><main><h1>T</h1><p>Body.</p></main></body></html>"
    result = extract_content(ContentInput(kind="url", url="https://e.edu/x"),
                             fetcher=_StubFetcher(html))
    assert result.page_title == "T"


def test_extract_content_requires_a_url_for_kind_url():
    try:
        extract_content(ContentInput(kind="url"), fetcher=_StubFetcher(""))
        assert False, "expected a ValueError"
    except ValueError as exc:
        assert "url is required" in str(exc)


def test_extract_content_rejects_an_unknown_kind():
    try:
        extract_content(ContentInput(kind="bogus"))
        assert False, "expected a ValueError"
    except ValueError as exc:
        assert "unknown input kind" in str(exc)


def test_extract_content_dispatches_markdown():
    md = "# Title\n\nBody text.\n".encode("utf-8")
    result = extract_content(ContentInput(kind="markdown", data=md))
    assert result.page_title == "Title"


# --------------------------------------------------------------------------
# write_page orchestration
# --------------------------------------------------------------------------

def _structured(register="institutional"):
    return StructuredContent(
        page_title="T", register=register,
        sections=[Section(heading="H", body="B", kind="body")])


def test_write_page_returns_the_rewrite_when_the_guardrail_passes_first_try(monkeypatch):
    calls = {"rewrite": 0, "guardrail": 0}

    def fake_rewrite(extracted, options, **kw):
        calls["rewrite"] += 1
        return _structured()

    def fake_guardrail(content, brand_voice, **kw):
        calls["guardrail"] += 1
        return GuardrailResult(passes=True, issues=[])

    monkeypatch.setattr(pipeline, "rewrite_page", fake_rewrite)
    monkeypatch.setattr(pipeline, "guardrail_check", fake_guardrail)

    result = write_page(ContentInput(kind="markdown", data=b"# T\n\nBody.\n"), RewriteOptions())
    assert result.page_title == "T"
    assert calls == {"rewrite": 1, "guardrail": 1}


def test_write_page_retries_the_rewrite_when_the_guardrail_fails(monkeypatch):
    attempts = []

    def fake_rewrite(extracted, options, **kw):
        attempts.append(kw.get("guardrail_issues"))
        return _structured()

    passes_sequence = iter([False, True])

    def fake_guardrail(content, brand_voice, **kw):
        return GuardrailResult(passes=next(passes_sequence), issues=["uses slang"])

    monkeypatch.setattr(pipeline, "rewrite_page", fake_rewrite)
    monkeypatch.setattr(pipeline, "guardrail_check", fake_guardrail)

    write_page(ContentInput(kind="markdown", data=b"# T\n\nBody.\n"), RewriteOptions())
    assert len(attempts) == 2
    assert attempts[0] is None
    assert attempts[1] == ["uses slang"]


def test_write_page_stops_retrying_after_the_cap(monkeypatch):
    call_count = {"rewrite": 0, "guardrail": 0}

    def fake_rewrite(extracted, options, **kw):
        call_count["rewrite"] += 1
        return _structured()

    def fake_guardrail(content, brand_voice, **kw):
        call_count["guardrail"] += 1
        return GuardrailResult(passes=False, issues=["still bad"])

    monkeypatch.setattr(pipeline, "rewrite_page", fake_rewrite)
    monkeypatch.setattr(pipeline, "guardrail_check", fake_guardrail)

    write_page(ContentInput(kind="markdown", data=b"# T\n\nBody.\n"), RewriteOptions(),
              max_guardrail_retries=2)
    assert call_count["rewrite"] == 3  # initial + 2 retries
    # Every draft is checked, including the last one -- this used to be 2,
    # meaning the final retry was returned without ever being reviewed.
    assert call_count["guardrail"] == 3


def test_write_page_cost_includes_every_draft_and_every_review(monkeypatch):
    from src.content_writer.review import ReviewResult

    def fake_rewrite(extracted, options, **kw):
        s = _structured()
        s.cost_usd = 0.10
        return s

    results = iter([ReviewResult(passes=False, cost_usd=0.01),
                    ReviewResult(passes=True, cost_usd=0.02)])
    monkeypatch.setattr(pipeline, "rewrite_page", fake_rewrite)
    monkeypatch.setattr(pipeline, "guardrail_check", lambda c, bv, **kw: next(results))

    result = write_page(ContentInput(kind="markdown", data=b"# T\n\nBody.\n"), RewriteOptions())
    assert abs(result.cost_usd - (0.10 + 0.01 + 0.10 + 0.02)) < 1e-9
    assert result.review["passes"] is True


# --------------------------------------------------------------------------
# JSON round-trip (server routes deserialize what the frontend echoes back)
# --------------------------------------------------------------------------

def test_structured_content_round_trips_through_its_own_dict_shape():
    from src.content_writer.models import SectionLink, StructuredContent

    original = _structured()
    original.sections[0].links.append(SectionLink(text="l", url="https://e.edu/x"))
    restored = StructuredContent.from_dict(original.to_dict())
    assert restored.page_title == original.page_title
    assert restored.register == original.register
    assert restored.sections[0].links[0].url == "https://e.edu/x"
