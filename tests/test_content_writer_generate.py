"""generate(): template dispatch, prompt contents, the review/redraft loop,
variants, and knowledge-base relevance -- all against the routing stub."""

import pytest

from src.content_writer.brand_voice import load_brand_voice, load_knowledge_base
from src.content_writer.generate import (
    GeneratedItem, GeneratedItemsOutput, GeneratedPageOutput, GeneratedSection,
    GenerationRequest, generate,
)
from src.content_writer.models import VoiceSettings
from src.content_writer.pipeline import ContentInput
from src.content_writer.prompting import relevant_facts
from src.content_writer.review import CriticOutput
from src.content_writer.rewrite import RewritePageOutput, RewrittenSectionOutput
from src.llm_cost import Budget
from tests.cw_stubs import RoutingStub, clean_critic

BV = load_brand_voice()
MODEL = "claude-opus-5"


def _page(body="The Central Library opens a study space on Oct. 6."):
    return GeneratedPageOutput(page_title="Library opens study space", content_register="institutional",
                               sections=[GeneratedSection(heading=None, body=body, kind="body")],
                               brand_notes=["Applied Specific"])


def _run(template, brief, settings=None, routes=None, **kw):
    stub = RoutingStub(routes or {"GeneratedPageOutput": _page(), "CriticOutput": clean_critic()})
    result = generate(GenerationRequest(template, brief, settings or VoiceSettings()),
                      budget=Budget(max_usd=10), model=MODEL, brand_voice=BV,
                      knowledge_base=load_knowledge_base(), client=stub, **kw)
    return result, stub


NEWS = {"topic": "Library study space", "who_what_when_where": "The Central Library opens a study space on Oct. 6."}


def test_a_page_template_returns_a_reviewed_variant():
    result, stub = _run("news-story", NEWS)
    v = result.variants[0]
    assert v.kind == "page" and v.page.page_title == "Library opens study space"
    assert v.review.passes and v.attempts == 1
    assert v.brand_notes == ["Applied Specific"]
    assert v.page.review["passes"] is True
    assert stub.count("GeneratedPageOutput") == 1 and stub.count("CriticOutput") == 1


def test_the_prompt_carries_the_template_brief_dials_and_audience():
    _, stub = _run("news-story", NEWS, VoiceSettings(audience="media", dials={"energy": 5},
                                                      keywords=["study space"]))
    user = stub.user_text("GeneratedPageOutput")
    assert "Content type: News story" in user
    assert "The Central Library opens a study space" in user
    assert "Energy 5/5" in user and "Formality 4/5" in user     # override + brand default
    assert "Audience: Media" in user
    assert "study space" in user and "Today's date is" in user
    assert "AP style" in stub.system_text("GeneratedPageOutput")


def test_uta_context_is_added_for_uta_only():
    _, stub = _run("news-story", NEWS)
    assert "uta.edu" in stub.user_text("GeneratedPageOutput")


def test_a_failed_review_triggers_a_redraft_with_the_issues():
    bad = _page("A world-class library opens on Oct. 6.")
    routes = {"GeneratedPageOutput": [bad, _page()], "CriticOutput": clean_critic()}
    result, stub = _run("news-story", NEWS, routes=routes, max_review_retries=1)
    v = result.variants[0]
    assert v.attempts == 2 and v.review.passes
    assert "world-class" in stub.user_text("GeneratedPageOutput", 1)   # issue fed back
    assert stub.count("CriticOutput") == 2                            # every draft reviewed


def test_the_last_draft_is_always_reviewed_even_when_it_still_fails():
    bad = _page("A world-class library.")
    routes = {"GeneratedPageOutput": bad, "CriticOutput": clean_critic()}
    result, stub = _run("news-story", NEWS, routes=routes, max_review_retries=2)
    v = result.variants[0]
    assert v.attempts == 3 and not v.review.passes
    assert stub.count("CriticOutput") == 3


def test_cost_sums_every_draft_and_every_review():
    bad = _page("A world-class library.")
    result, stub = _run("news-story", NEWS, routes={"GeneratedPageOutput": [bad, _page()],
                                                    "CriticOutput": clean_critic()},
                        max_review_retries=1)
    assert result.cost_usd == pytest.approx(result.variants[0].cost_usd)
    assert result.variants[0].cost_usd > 0 and len(stub.calls) == 4


def test_variants_share_a_budget_and_are_told_to_differ():
    result, stub = _run("news-story", NEWS, VoiceSettings(variants=3))
    assert len(result.variants) == 3
    assert "Earlier variants opened like this" in stub.user_text("GeneratedPageOutput", 1)
    assert "Earlier variants opened like this" not in stub.user_text("GeneratedPageOutput", 0)


def test_running_out_of_budget_mid_variants_keeps_what_was_written():
    stub = RoutingStub({"GeneratedPageOutput": _page(), "CriticOutput": clean_critic()})
    result = generate(GenerationRequest("news-story", NEWS, VoiceSettings(variants=3)),
                      budget=Budget(max_usd=10, max_calls=3), model=MODEL, brand_voice=BV,
                      knowledge_base=[], client=stub)
    assert 1 <= len(result.variants) < 3
    assert "Stopped after" in result.notice


def test_an_items_template_counts_characters():
    items = GeneratedItemsOutput(items=[GeneratedItem(text="Apply to UT Arlington today."),
                                        GeneratedItem(text="  ")])
    result, _ = _run("meta-descriptions", {"page_topic": "Apply"},
                     routes={"GeneratedItemsOutput": items, "CriticOutput": clean_critic()})
    v = result.variants[0]
    assert v.kind == "items" and v.items == [{"text": "Apply to UT Arlington today.", "chars": 28, "note": ""}]


def test_missing_required_brief_fields_are_reported_before_any_call():
    stub = RoutingStub({})
    with pytest.raises(ValueError, match="Date and time"):
        generate(GenerationRequest("event-announcement", {"event_name": "Preview Day"}),
                 budget=Budget(), model=MODEL, brand_voice=BV, knowledge_base=[], client=stub)
    assert stub.calls == []


def test_rewrite_page_requires_a_source():
    with pytest.raises(ValueError, match="source material"):
        generate(GenerationRequest("rewrite-page", {}), budget=Budget(), model=MODEL,
                 brand_voice=BV, knowledge_base=[], client=RoutingStub({}))


def test_rewrite_page_goes_through_the_section_aligned_rewrite():
    parsed = RewritePageOutput(page_title="T", content_register="institutional",
                               sections=[RewrittenSectionOutput(heading="Title", body="Body text.", kind="body")])
    stub = RoutingStub({"RewritePageOutput": parsed, "CriticOutput": clean_critic()})
    result = generate(GenerationRequest("rewrite-page", {}, VoiceSettings(),
                                        ContentInput(kind="markdown", data=b"# Title\n\nBody text.\n")),
                      budget=Budget(), model=MODEL, brand_voice=BV, knowledge_base=[], client=stub)
    page = result.variants[0].page
    assert page.sections[0].body == "Body text."
    assert page.original_sections[0].body == "Body text."


def test_a_source_satisfies_the_brief():
    with pytest.raises(ValueError, match="Missing"):
        _run("news-story", {})
    stub2 = RoutingStub({"GeneratedPageOutput": _page(), "CriticOutput": clean_critic()})
    generate(GenerationRequest("news-story", {}, VoiceSettings(),
                               ContentInput(kind="markdown", data=b"# Library\n\nOpens Oct. 6.\n")),
             budget=Budget(), model=MODEL, brand_voice=BV, knowledge_base=[], client=stub2)
    assert "SOURCE MATERIAL" in stub2.user_text("GeneratedPageOutput")


# --- building a page from a long source ------------------------------------

SYLLABUS_MD = (b"# CSE 3380 Syllabus\n\n## Meetings\n\nFr 4:00PM - 6:50PM in NH 112.\n\n"
               b"## Assignments\n\nAssignment 1 due February 13. Assignment 2 due March 6.\n")


def test_a_page_from_a_source_defaults_to_full_coverage():
    """The syllabus case: no length chosen + a source attached used to mean
    the 200-word "Short" preset, and 18 of 20 key details were dropped."""
    _, stub = _run_src(_page("Class meets Fridays 4-6:50 p.m. in NH 112. Assignments are due Feb. 13 and March 6."))
    user = stub.user_text("GeneratedPageOutput")
    assert "Carry every fact in the source material" in user
    assert "carry every fact from here into the page" in user
    assert "About 200 words" not in user


def test_full_coverage_redrafts_until_nothing_is_dropped():
    thin = _page("Class meets on Fridays in NH 112.")
    full = _page("CSE 3380 meets Fridays 4-6:50 p.m. in NH 112. Assignments are due Feb. 13 and March 6.")
    result, stub = _run_src([thin, full])
    v = result.variants[0]
    assert v.attempts == 2 and v.review.passes
    assert "details from the source are missing" in stub.user_text("GeneratedPageOutput", 1)
    assert v.review.metrics["source_details_kept"] == v.review.metrics["source_details"]


def test_a_chosen_shorter_length_reports_but_does_not_fail_on_dropped_details():
    thin = _page("Class meets on Fridays in NH 112.")
    result, stub = _run_src(thin, VoiceSettings(length="Short"))
    v = result.variants[0]
    assert v.attempts == 1 and v.review.passes
    assert any("details from the source are missing" in i.message and i.severity == "suggested"
               for i in v.review.issues)
    assert "About 200 words" in stub.user_text("GeneratedPageOutput")


def test_markdown_emphasis_is_stripped_from_generated_copy():
    result, _ = _run("news-story", NEWS, routes={
        "GeneratedPageOutput": _page("**Instructor:** Dr. Rivas. The library opens Oct. 6."),
        "CriticOutput": clean_critic()})
    assert result.variants[0].page.sections[0].body.startswith("Instructor: Dr. Rivas.")


def _run_src(page_or_pages, settings=None):
    stub = RoutingStub({"GeneratedPageOutput": page_or_pages, "CriticOutput": clean_critic()})
    result = generate(GenerationRequest("new-page", {}, settings or VoiceSettings(),
                                        ContentInput(kind="markdown", data=SYLLABUS_MD)),
                      budget=Budget(max_usd=10), model=MODEL, brand_voice=BV, knowledge_base=[],
                      client=stub, max_review_retries=1)
    return result, stub


# --- knowledge base relevance ------------------------------------------------

def test_only_relevant_facts_are_offered():
    kb = load_knowledge_base()
    assert relevant_facts(kb, "The library opens a 24-hour study space with group rooms.", "news-story", BV) == []
    ids = {f["id"] for f in relevant_facts(kb, "Why UTA: research, financial aid, veterans", "new-page", BV)}
    assert {"carnegie-r1", "veterans"} <= ids


def test_a_press_release_always_gets_the_boilerplate():
    ids = [f["id"] for f in relevant_facts(load_knowledge_base(), "New dean named", "press-release", BV)]
    assert ids == ["boilerplate"]


def test_the_brands_own_documented_commitment_is_not_flagged_as_invented():
    page = _page("The University is committed to providing access. The library opens Oct. 6.")
    result, _ = _run("news-story", NEWS, routes={"GeneratedPageOutput": page, "CriticOutput": clean_critic()})
    assert result.variants[0].review.passes


def test_every_fact_is_offered_and_allowed_by_the_figure_check():
    """All facts reach the writer, and a verified figure is never a violation."""
    page = _page("Fall 2024 enrollment was 41,613 students, and the library opens Oct. 6.")
    result, stub = _run("news-story", NEWS, routes={"GeneratedPageOutput": page, "CriticOutput": clean_critic()})
    assert "41,613" in stub.user_text("GeneratedPageOutput")          # offered
    assert result.variants[0].review.passes                          # and allowed
