"""Content Writer's rewrite pipeline, against a stub Anthropic client -- same
approach as test_alt_text.py: no network, no credentials."""

from types import SimpleNamespace

import pytest

from src.content_writer.models import ExtractedContent, RewriteOptions, Section, SectionLink
from src.content_writer.rewrite import (
    RewritePageOutput, RewrittenSectionOutput, load_brand_voice, rewrite_page,
    rewrite_section,
)
from src.llm_cost import Budget


def _usage(input_tokens=800, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class StubClient:
    def __init__(self, parsed, input_tokens=800):
        self.parsed = parsed
        self.input_tokens = input_tokens
        self.calls = 0
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=self.input_tokens)

    def _parse(self, **kw):
        self.calls += 1
        return SimpleNamespace(parsed_output=self.parsed, usage=_usage(), stop_reason="end_turn")


BRAND_VOICE = load_brand_voice()


def _extracted(n=2):
    return ExtractedContent(
        page_title="Campus Life",
        sections=[Section(heading=f"Section {i}", body=f"Body {i}", kind="body") for i in range(n)],
        source_note="test",
    )


def test_load_brand_voice_reads_the_committed_config():
    bv = load_brand_voice()
    assert bv["brand"] == "UTA"
    assert "institutional" in bv["registers"]
    assert "prospective_student" in bv["registers"]


def test_rewrite_page_maps_the_parsed_output_into_structured_content():
    parsed = RewritePageOutput(
        page_title="Campus Life at UTA", content_register="institutional",
        sections=[
            RewrittenSectionOutput(heading="Housing", body="Rewritten housing copy.", kind="body"),
            RewrittenSectionOutput(heading="Dining", body="Rewritten dining copy.", kind="body"),
        ])
    client = StubClient(parsed)
    result = rewrite_page(_extracted(2), RewriteOptions(), budget=Budget(), client=client,
                          brand_voice=BRAND_VOICE, model="claude-opus-5")

    assert result.page_title == "Campus Life at UTA"
    assert result.register == "institutional"
    assert [s.heading for s in result.sections] == ["Housing", "Dining"]
    assert [s.heading for s in result.original_sections] == ["Section 0", "Section 1"]
    assert client.calls == 1


def test_rewrite_page_falls_back_when_the_model_changes_the_section_count():
    """A count mismatch means the model merged/split sections against
    instructions -- the caller must never receive a structure that no
    longer lines up with what was actually extracted."""
    parsed = RewritePageOutput(
        page_title="T", content_register="institutional",
        sections=[RewrittenSectionOutput(heading="Only one", body="...", kind="body")])
    client = StubClient(parsed)
    extracted = _extracted(3)
    result = rewrite_page(extracted, RewriteOptions(), budget=Budget(), client=client,
                          brand_voice=BRAND_VOICE, model="claude-opus-5")
    assert len(result.sections) == len(extracted.sections)


def test_rewrite_page_passes_guardrail_issues_into_the_prompt():
    parsed = RewritePageOutput(page_title="T", content_register="institutional", sections=[\
        RewrittenSectionOutput(heading="H", body="B", kind="body")])
    client = StubClient(parsed)
    rewrite_page(_extracted(1), RewriteOptions(), budget=Budget(), client=client,
                brand_voice=BRAND_VOICE, guardrail_issues=["uses slang"], model="claude-opus-5")
    # No direct hook into the prompt text from here without over-mocking --
    # this just confirms the call succeeds with issues present and costs one call.
    assert client.calls == 1


def test_rewrite_section_regenerates_just_one_section():
    parsed = RewrittenSectionOutput(heading="New Heading", body="New body.", kind="cta")
    client = StubClient(parsed)
    section, cost = rewrite_section(\
        Section(heading="Old", body="Old body", kind="body"),
        page_title="T", register="institutional", options=RewriteOptions(),
        budget=Budget(), client=client, brand_voice=BRAND_VOICE, model="claude-opus-5")
    assert section.heading == "New Heading"
    assert section.kind == "cta"
    assert cost >= 0


def test_rewrite_page_preserves_the_original_sections_links_and_media_refs():
    """Rewriting only ever changes heading/body text -- it must never drop
    the section's real links/media_refs (this used to silently happen on
    every page, independent of anything about a specific site)."""
    link = SectionLink(text="Apply Now", url="https://e.edu/apply", is_button=True)
    extracted = ExtractedContent(
        page_title="T",
        sections=[Section(heading="Housing", body="Old body", kind="body",
                         links=[link], media_refs=["a photo of a dorm room"])],
        source_note="test", page_chrome_context="Nav: Admissions")
    parsed = RewritePageOutput(
        page_title="T", content_register="institutional",
        sections=[RewrittenSectionOutput(heading="Housing", body="New body.", kind="body")])
    client = StubClient(parsed)

    result = rewrite_page(extracted, RewriteOptions(), budget=Budget(), client=client,
                          brand_voice=BRAND_VOICE, model="claude-opus-5")

    assert result.sections[0].body == "New body."
    assert result.sections[0].links == [link]
    assert result.sections[0].media_refs == ["a photo of a dorm room"]
    assert result.page_chrome_context == "Nav: Admissions"


def test_rewrite_page_fallback_path_also_preserves_links_and_media_refs():
    """Same guarantee on the section-count-mismatch fallback path, which
    rebuilds Section objects from extracted.sections directly."""
    link = SectionLink(text="Handbook", url="https://e.edu/handbook.pdf", is_document=True)
    extracted = ExtractedContent(
        page_title="T",
        sections=[
            Section(heading="A", body="Body A", kind="body", links=[link]),
            Section(heading="B", body="Body B", kind="body", media_refs=["a campus photo"]),
        ],
        source_note="test")
    parsed = RewritePageOutput(
        page_title="T", content_register="institutional",
        sections=[RewrittenSectionOutput(heading="Only one", body="...", kind="body")])
    client = StubClient(parsed)

    result = rewrite_page(extracted, RewriteOptions(), budget=Budget(), client=client,
                          brand_voice=BRAND_VOICE, model="claude-opus-5")

    assert result.sections[0].links == [link]
    assert result.sections[1].media_refs == ["a campus photo"]


def test_rewrite_section_preserves_the_original_sections_links_and_media_refs():
    link = SectionLink(text="Apply Now", url="https://e.edu/apply", is_button=True)
    parsed = RewrittenSectionOutput(heading="New Heading", body="New body.", kind="cta")
    client = StubClient(parsed)

    section, _ = rewrite_section(
        Section(heading="Old", body="Old body", kind="body",
               links=[link], media_refs=["a photo"]),
        page_title="T", register="institutional", options=RewriteOptions(),
        budget=Budget(), client=client, brand_voice=BRAND_VOICE, model="claude-opus-5")

    assert section.links == [link]
    assert section.media_refs == ["a photo"]


def test_a_section_with_no_body_stays_bodiless():
    """A heading over a row of buttons has no copy; the model once wrote a
    whole invented sentence for one on the live admissions page."""
    extracted = ExtractedContent(page_title="T", sections=[
        Section(heading="Apply", body="", kind="body",
                links=[SectionLink(text="Undergraduate", url="https://e.edu/ug", is_button=True)])])
    parsed = RewritePageOutput(page_title="T", content_register="institutional", sections=[
        RewrittenSectionOutput(heading="Apply now", body="Your first step toward an enriching experience.", kind="body")])
    result = rewrite_page(extracted, RewriteOptions(), budget=Budget(), client=StubClient(parsed),
                          brand_voice=BRAND_VOICE, model="claude-opus-5")
    assert result.sections[0].heading == "Apply now"
    assert result.sections[0].body == ""
    assert result.sections[0].links[0].url == "https://e.edu/ug"


def test_rewrite_page_respects_the_budget():
    from src.llm_cost import BudgetExceeded

    parsed = RewritePageOutput(page_title="T", content_register="institutional", sections=[\
        RewrittenSectionOutput(heading="H", body="B", kind="body")])
    client = StubClient(parsed, input_tokens=10_000_000)
    with pytest.raises(BudgetExceeded):
        rewrite_page(_extracted(1), RewriteOptions(), budget=Budget(max_usd=0.0000001),
                    client=client, brand_voice=BRAND_VOICE)


def test_rewrite_page_uses_openai_model_when_openai_active(monkeypatch):
    from src import llm_provider
    monkeypatch.setattr(llm_provider, "active_provider", lambda: "openai")

    parsed = RewritePageOutput(
        page_title="OpenAI rewritten", content_register="institutional",
        sections=[RewrittenSectionOutput(heading="H", body="B", kind="body")])

    called_model = []

    def fake_call_structured(model, *args, **kwargs):
        called_model.append(model)
        return parsed, 0.01

    monkeypatch.setattr(llm_provider, "call_structured", fake_call_structured)

    result = rewrite_page(_extracted(1), RewriteOptions(), budget=Budget(),
                          brand_voice=BRAND_VOICE)
    # Content Writer's default is that provider's *recommended* catalog
    # model (llm_provider.MODEL_CATALOG), not MODELS["high"] and not the
    # strongest/most expensive tier -- see content_writer.rewrite._default_model.
    assert called_model == [llm_provider.recommended_model("openai")]


def test_content_writer_calls_default_to_medium_reasoning_effort(monkeypatch):
    """Content Writer's own default (content_writer.rewrite._call), not
    call_structured's own "high" -- cuts latency/truncation risk on a
    reasoning-tier model at an acceptable planning-depth cost."""
    from src import llm_provider

    parsed = RewritePageOutput(
        page_title="T", content_register="institutional",
        sections=[RewrittenSectionOutput(heading="H", body="B", kind="body")])
    captured = {}

    def fake_call_structured(model, system, prompt, output_format, budget, **kwargs):
        captured["effort"] = kwargs.get("effort")
        return parsed, 0.01

    monkeypatch.setattr(llm_provider, "call_structured", fake_call_structured)
    rewrite_page(_extracted(1), RewriteOptions(), budget=Budget(), brand_voice=BRAND_VOICE)
    assert captured["effort"] == "medium"
