"""Compose mode: free-form -> typed blocks, still brand-voice-aware and
reviewed, with invented content allowed but only when labeled a placeholder."""

import pytest

from src.content_writer.brand_voice import load_brand_voice
from src.content_writer.compose import (
    ComposedBlockOutput, ComposedLinkOutput, ComposedPageOutput, draft_compose, opening_text,
    regenerate_block, units_from_blocks,
)
from src.content_writer.generate import GenerationRequest, generate
from src.content_writer.models import Block, SectionLink, VoiceSettings
from src.llm_cost import Budget
from tests.cw_stubs import RoutingStub, clean_critic

BV = load_brand_voice()
MODEL = "claude-opus-5"


def _page_output(blocks=None, register="prospective-student"):
    return ComposedPageOutput(
        title="What Makes UTA Great", subtitle="Discover the Maverick Difference",
        content_register=register,
        blocks=blocks or [
            ComposedBlockOutput(type="hero", heading="What Makes UTA Great",
                                subheading="Discover the Maverick Difference", is_placeholder=False),
            ComposedBlockOutput(type="stat", stat_value="41,613", stat_label="Total enrollment",
                                is_placeholder=False),
            ComposedBlockOutput(type="quote", quote_text="UTA gave me the tools to build a future.",
                                quote_attribution="Maria G., Class of 2023", is_placeholder=True,
                                placeholder_note="Illustrative testimonial -- replace with a real quote."),
        ],
        brand_notes=["Applied Ambitious with a sourced figure."])


# The fixture's stat block cites 41,613 -- this is what backs it as a real,
# sourced figure rather than an unlabeled invention (the review checks the
# stat against exactly this the same way it would a real knowledge-base fact).
ENROLLMENT_FACT = [{"id": "enrollment", "fact": "Fall 2024 enrollment was 41,613 students.",
                    "title": "Enrollment", "source_url": "https://e.edu", "tags": []}]


def _run(routes=None, settings=None, facts=None, **kw):
    stub = RoutingStub(routes or {"ComposedPageOutput": _page_output(), "CriticOutput": clean_critic()})
    result = generate(GenerationRequest("compose-page", {"prompt": "A page about what makes UTA great"},
                                        settings or VoiceSettings()),
                      budget=Budget(max_usd=10), model=MODEL, brand_voice=BV,
                      knowledge_base=ENROLLMENT_FACT if facts is None else facts, client=stub, **kw)
    return result, stub


# --- generation through the normal template pipeline ------------------------

def test_compose_page_produces_a_reviewed_blocks_variant():
    result, stub = _run()
    v = result.variants[0]
    assert v.kind == "blocks" and v.composed.title == "What Makes UTA Great"
    assert [b.type for b in v.composed.blocks] == ["hero", "stat", "quote"]
    assert v.composed.blocks[2].is_placeholder and v.composed.blocks[2].placeholder_note
    assert v.review.passes
    assert v.composed.review["passes"] is True and v.composed.cost_usd > 0
    assert stub.count("ComposedPageOutput") == 1


def test_the_prompt_field_reaches_the_model_with_the_block_glossary():
    _, stub = _run()
    user = stub.user_text("ComposedPageOutput")
    assert "A page about what makes UTA great" in user
    assert "hero: the page opener" in user
    assert "is_placeholder" in user


def test_publish_ready_forces_a_redraft_away_from_the_placeholder():
    with_placeholder = _page_output()
    grounded = _page_output(blocks=[
        ComposedBlockOutput(type="hero", heading="What Makes UTA Great", is_placeholder=False),
        ComposedBlockOutput(type="stat", stat_value="41,613", stat_label="Total enrollment",
                            is_placeholder=False),
    ])
    routes = {"ComposedPageOutput": [with_placeholder, grounded], "CriticOutput": clean_critic()}
    result, stub = _run(routes, VoiceSettings(strictness="publish-ready"), max_review_retries=1)
    v = result.variants[0]
    assert v.attempts == 2 and v.review.passes
    assert not any(b.is_placeholder for b in v.composed.blocks)
    assert "prepared to publish" in stub.user_text("ComposedPageOutput", 0).lower()


def test_mockup_mode_accepts_a_well_noted_placeholder_on_the_first_try():
    result, _ = _run(settings=VoiceSettings(strictness="mockup"))
    assert result.variants[0].attempts == 1


def test_missing_prompt_is_reported_before_any_call():
    stub = RoutingStub({})
    with pytest.raises(ValueError, match="a description of the page"):
        generate(GenerationRequest("compose-page", {}), budget=Budget(), model=MODEL,
                 brand_voice=BV, knowledge_base=[], client=stub)
    assert stub.calls == []


def test_a_source_does_not_excuse_an_empty_prompt():
    """Unlike other templates, an attached source is grounding material for
    Compose, never a substitute for saying what blocks to write."""
    from src.content_writer.pipeline import ContentInput

    stub = RoutingStub({})
    with pytest.raises(ValueError, match="a description of the page"):
        generate(GenerationRequest("compose-page", {},
                                   source=ContentInput(kind="markdown", data=b"# T\n\nBody.\n")),
                 budget=Budget(), model=MODEL, brand_voice=BV, knowledge_base=[], client=stub)


def test_markdown_emphasis_is_stripped_from_block_text():
    page = _page_output(blocks=[
        ComposedBlockOutput(type="text", heading="**Bold** heading", body="Some *text*.",
                            is_placeholder=False)])
    result, _ = _run({"ComposedPageOutput": page, "CriticOutput": clean_critic()})
    b = result.variants[0].composed.blocks[0]
    assert b.heading == "Bold heading" and b.body == "Some text."


def test_a_quote_that_already_carries_its_own_quote_marks_is_not_doubled():
    """Seen live: the model wrote quote_text as '"UTA truly embodies..."'
    (already quoted), and rendering it inside its own curly quotes produced
    the visible '""like this""' bug."""
    page = _page_output(blocks=[
        ComposedBlockOutput(type="quote", quote_text='"UTA truly embodies the spirit of innovation."',
                            quote_attribution="— A. Innovator, Research Institute Director",
                            is_placeholder=True, placeholder_note="illustrative quote")])
    result, _ = _run({"ComposedPageOutput": page, "CriticOutput": clean_critic()})
    block = result.variants[0].composed.blocks[0]
    assert block.quote_text == "UTA truly embodies the spirit of innovation."
    assert block.quote_attribution == "A. Innovator, Research Institute Director"


def test_a_plain_quote_with_no_wrapping_marks_is_left_alone():
    page = _page_output(blocks=[
        ComposedBlockOutput(type="quote", quote_text="UTA changed my life.", quote_attribution="J. Doe",
                            is_placeholder=True, placeholder_note="illustrative")])
    result, _ = _run({"ComposedPageOutput": page, "CriticOutput": clean_critic()})
    block = result.variants[0].composed.blocks[0]
    assert block.quote_text == "UTA changed my life." and block.quote_attribution == "J. Doe"


def test_an_unrecognized_block_type_falls_back_to_text():
    page = _page_output(blocks=[ComposedBlockOutput(type="carousel", body="Odd type.", is_placeholder=False)])
    result, _ = _run({"ComposedPageOutput": page, "CriticOutput": clean_critic()})
    assert result.variants[0].composed.blocks[0].type == "text"


# --- units_from_blocks / opening_text ---------------------------------------

def test_units_from_blocks_carries_placeholder_metadata():
    blocks = [Block(type="quote", quote_text="Hi", quote_attribution="X", is_placeholder=True,
                    placeholder_note="illustrative")]
    units = units_from_blocks(blocks)
    assert units[0]["placeholder"] is True and units[0]["placeholder_note"] == "illustrative"
    assert units[0]["type"] == "quote" and "Hi" in units[0]["body"]


def test_opening_text_finds_the_first_non_empty_block():
    from src.content_writer.models import ComposedPage

    blocks = [Block(type="divider"), Block(type="hero", heading="Hello there")]
    assert opening_text(ComposedPage(title="T", blocks=blocks)) == "Hello there"


# --- variants differ, cost accumulates --------------------------------------

def test_variants_are_told_to_differ_and_cost_accumulates():
    result, stub = _run(settings=VoiceSettings(variants=2))
    assert len(result.variants) == 2
    assert "Earlier variants opened like this" in stub.user_text("ComposedPageOutput", 1)
    assert result.cost_usd == pytest.approx(sum(v.cost_usd for v in result.variants))


# --- Web Builder handoff -----------------------------------------------------

def test_to_structured_content_flattens_every_block_kind():
    result, _ = _run()
    sc = result.variants[0].composed.to_structured_content()
    assert len(sc.sections) == 3
    assert sc.sections[1].kind == "fact-list" and "41,613" in sc.sections[1].body
    assert "UTA gave me the tools" in sc.sections[2].body and "Maria G." in sc.sections[2].body


def test_to_structured_content_flattens_links_cta_and_image_blocks():
    from src.content_writer.models import ComposedPage

    page = ComposedPage(title="T", blocks=[
        Block(type="links", links=[SectionLink(text="Admissions", url="https://e.edu/apply")]),
        Block(type="cta", heading="Apply Now",
             links=[SectionLink(text="Apply Now", url="https://e.edu/apply", is_button=True)]),
        Block(type="image", image_alt="Campus at sunset", image_caption="The quad"),
    ])
    sc = page.to_structured_content()
    assert sc.sections[0].links[0].url == "https://e.edu/apply"
    assert sc.sections[1].kind == "cta" and sc.sections[1].links[0].is_button
    assert "[Image: Campus at sunset]" in sc.sections[2].body and "The quad" in sc.sections[2].body
    assert sc.sections[2].media_refs == ["Campus at sunset"]


def test_draft_compose_returns_a_composed_page_and_cost():
    stub = RoutingStub({"ComposedPageOutput": _page_output()})
    page, cost = draft_compose("A page about what makes UTA great", VoiceSettings(), bv=BV,
                               facts=[], budget=Budget(), model=MODEL, client=stub)
    assert page.title == "What Makes UTA Great" and cost > 0
    assert page.blocks[0].links == []  # hero carries no links in this fixture


def test_composed_block_output_can_carry_a_real_link():
    parsed = ComposedBlockOutput(type="cta", heading="Apply Now",
                                 links=[ComposedLinkOutput(text="Apply Now", url="https://e.edu/apply",
                                                          is_button=True)],
                                 is_placeholder=False)
    from src.content_writer.compose import _to_block
    block = _to_block(parsed)
    assert block.links[0].url == "https://e.edu/apply" and block.links[0].is_button


def test_to_structured_content_skips_dividers():
    from src.content_writer.models import ComposedPage
    page = ComposedPage(title="T", blocks=[Block(type="divider"), Block(type="text", body="Hi")])
    assert len(page.to_structured_content().sections) == 1


# --- regenerate_block --------------------------------------------------------

def test_regenerate_block_redrafts_one_block_reviewed():
    original = Block(type="stat", stat_value="1", stat_label="Wrong")
    fixed = ComposedBlockOutput(type="stat", stat_value="41,613", stat_label="Total enrollment",
                                is_placeholder=False)
    stub = RoutingStub({"ComposedBlockOutput": fixed, "CriticOutput": clean_critic()})
    new_block, rv, cost = regenerate_block(
        original, index=0, page_title="What Makes UTA Great", all_blocks=[original],
        prompt="A page about UTA", settings=VoiceSettings(), budget=Budget(), model=MODEL,
        brand_voice=BV, knowledge_base=ENROLLMENT_FACT, client=stub)
    assert new_block.stat_value == "41,613" and rv.passes and cost > 0


def test_regenerate_block_retries_against_a_bad_first_draft():
    bad = ComposedBlockOutput(type="text", body="A world-class page.", is_placeholder=False)
    good = ComposedBlockOutput(type="text", body="A specific, factual page.", is_placeholder=False)
    stub = RoutingStub({"ComposedBlockOutput": [bad, good], "CriticOutput": clean_critic()})
    new_block, rv, cost = regenerate_block(
        Block(type="text", body="Old."), index=0, page_title="T", all_blocks=[Block(type="text", body="Old.")],
        prompt="A page", settings=VoiceSettings(), budget=Budget(), model=MODEL, brand_voice=BV,
        knowledge_base=[], client=stub, max_review_retries=1)
    assert stub.count("ComposedBlockOutput") == 2 and rv.passes
    assert new_block.body == "A specific, factual page."
