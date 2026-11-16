"""Web Builder's matcher, now one LLM call over the whole page plus the
full catalog -- stubbed the same way test_content_writer_rewrite.py stubs
Claude, since there's no network or credentials in tests."""

from types import SimpleNamespace

from src.content_writer.models import Section, SectionLink, StructuredContent
from src.llm_cost import Budget
from src.web_builder.catalog import load_catalog
from src.web_builder.match import LayoutPlanOutput, SectionPlacementOutput, build_plan

CATALOG = load_catalog()


def _content(sections, page_chrome_context=""):
    return StructuredContent(page_title="T", register="institutional", sections=sections,
                             page_chrome_context=page_chrome_context)


def _usage(input_tokens=2000, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class StubClient:
    """A canned LayoutPlanOutput per call -- tests drive what the "model"
    decided, since judgment quality is now the model's job, not this
    module's; this file tests that the prompt/response plumbing is correct."""

    def __init__(self, output: LayoutPlanOutput):
        self.output = output
        self.calls = 0
        self.last_kwargs = None
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=2000)

    def _parse(self, **kw):
        self.calls += 1
        self.last_kwargs = kw
        return SimpleNamespace(parsed_output=self.output, usage=_usage(), stop_reason="end_turn")


def _plan(sections, output: LayoutPlanOutput, budget=None):
    content = _content(sections)
    client = StubClient(output)
    plan = build_plan(content, CATALOG, budget=budget or Budget(), client=client, model="claude-opus-5")
    return plan, client


def test_the_models_placement_is_used_verbatim():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Accordion",
                              rationale="It's an FAQ answer.", alternatives=["Rich Text"]),
    ])
    plan, client = _plan(
        [Section(heading="How do I apply?", body="Short answer.", kind="faq-item")], output)
    assert client.calls == 1
    assert plan.rows[0].component == "Accordion"
    assert plan.rows[0].rationale == "It's an FAQ answer."
    assert plan.rows[0].alternatives == ["Rich Text"]


def test_every_content_section_gets_exactly_one_row_in_order():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Hero", rationale="opener"),
        SectionPlacementOutput(section_indices=[1], component="Rich Text", rationale="cta prose"),
        SectionPlacementOutput(section_indices=[2], component="Accordion", rationale="faq"),
    ])
    sections = [
        Section(heading="A", body="B1", kind="intro"),
        Section(heading="B", body="B2", kind="cta"),
        Section(heading="C", body="B3", kind="faq-item"),
    ]
    plan, _ = _plan(sections, output)
    section_rows = [r for r in plan.rows if r.section_indices]
    assert len(section_rows) == 3
    assert [r.section_indices for r in section_rows] == [[0], [1], [2]]
    assert [r.component for r in section_rows] == ["Hero", "Rich Text", "Accordion"]


def test_a_missing_placement_falls_back_to_a_generic_component_and_is_flagged():
    """The model must place every section -- if it drops one, the pipeline
    still needs a row for it rather than silently losing a section."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Hero", rationale="opener"),
        # section 1 missing entirely
    ])
    sections = [
        Section(heading="A", body="B1", kind="intro"),
        Section(heading="B", body="B2", kind="body"),
    ]
    plan, _ = _plan(sections, output)
    section_rows = [r for r in plan.rows if r.section_indices]
    assert len(section_rows) == 2
    fallback_row = section_rows[1]
    assert fallback_row.component  # some real component name, not empty
    assert any("Section 2" in note or "B" in note for note in plan.unmatched_notes)


def test_an_invalid_component_name_falls_back_rather_than_being_passed_through():
    """The model can hallucinate a name not in the catalog -- never trust it
    blindly, the same discipline `rewrite_page` applies to a section-count
    mismatch."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Nonexistent Widget",
                              rationale="not real"),
    ])
    plan, _ = _plan([Section(heading="A", body="B", kind="body")], output)
    names = {c.name for c in CATALOG}
    assert plan.rows[0].component in names
    assert plan.rows[0].component != "Nonexistent Widget"
    assert plan.unmatched_notes


def test_alternatives_are_filtered_to_real_catalog_names():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="plain prose",
                              alternatives=["Made Up Component", "Rich Text", "Accordion"]),
    ])
    plan, _ = _plan([Section(heading="A", body="B", kind="body")], output)
    assert "Made Up Component" not in plan.rows[0].alternatives
    assert "Rich Text" not in plan.rows[0].alternatives  # never its own alternative
    assert "Accordion" in plan.rows[0].alternatives


def test_alternatives_are_filtered_by_the_same_hard_constraints_the_pick_itself_passed():
    """The swap picker shouldn't offer a component the section's own media
    already rules out -- Rich Text has no image field at all, so it's not a
    real alternative for a section with a photo, even if the model listed it."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Gradient Hero", rationale="page opener",
                              alternatives=["Rich Text", "Hero Compact"]),
    ])
    section = Section(heading="Welcome", body="B", kind="intro", media_refs=["a campus photo"])
    plan, _ = _plan([section], output)
    assert "Rich Text" not in plan.rows[0].alternatives   # no image field -- would violate
    assert "Hero Compact" in plan.rows[0].alternatives    # has an image field -- fine


def test_dynamic_components_the_model_judges_relevant_are_offered_as_structural_suggestions():
    """Only the dynamic components the model actually names come back as
    rows -- not the full catalog of them regardless of page topic (that was
    the bug: a topic-scoped archive showing up on every unrelated page)."""
    output = LayoutPlanOutput(
        placements=[SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose")],
        relevant_dynamic_components=["Featured News", "News Listing"],
    )
    plan, _ = _plan([Section(heading="H", body="B", kind="body")], output)
    dynamic_rows = [r for r in plan.rows if not r.section_indices]
    names = {r.component for r in dynamic_rows}
    assert names == {"Featured News", "News Listing"}
    for row in dynamic_rows:
        assert "auto-populates" in row.rationale


def test_no_relevant_dynamic_components_means_no_structural_rows():
    """An empty list is the model saying none of them fit this page -- a
    normal, common answer, not something to override back to "all of them"."""
    output = LayoutPlanOutput(
        placements=[SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose")],
        relevant_dynamic_components=[],
    )
    plan, _ = _plan([Section(heading="H", body="B", kind="body")], output)
    assert [r for r in plan.rows if not r.section_indices] == []


def test_a_hallucinated_dynamic_component_name_is_dropped_not_trusted():
    output = LayoutPlanOutput(
        placements=[SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose")],
        relevant_dynamic_components=["Featured News", "Not A Real Component"],
    )
    plan, _ = _plan([Section(heading="H", body="B", kind="body")], output)
    names = {r.component for r in plan.rows if not r.section_indices}
    assert names == {"Featured News"}


def test_dynamic_components_are_sent_separately_not_as_placement_candidates():
    """Dynamic components are shown to the model now (so it can judge which
    ones fit the page), but only in the separate auto-populating block --
    never as a section-placement candidate. `_component_block` (placement
    candidates) always follows the name with a newline + "  purpose:";
    `_dynamic_component_block` (relevance-only) puts "--  purpose" on the
    same line -- the two formats are how this test tells them apart.
    Chrome components (Header/Footer) aren't dynamic, so they should not
    appear in either block at all."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    _, client = _plan([Section(heading="H", body="B", kind="body")], output)
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "- Featured News (category: News)\n  purpose:" not in prompt
    assert "- News Listing (category: News)\n  purpose:" not in prompt
    assert "- Header (category:" not in prompt
    assert "- Footer (category:" not in prompt
    # ... but they ARE offered in the separate relevance-judgment block.
    assert "- Featured News (category: News) --" in prompt
    assert "- News Listing (category: News) --" in prompt


def test_chrome_components_are_never_offered_at_all():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    plan, _ = _plan([Section(heading="H", body="B", kind="body")], output)
    names = {r.component for r in plan.rows}
    assert "Header" not in names
    assert "Footer" not in names


def test_the_catalog_sent_includes_more_than_a_handful_of_components():
    """The whole point of the LLM path: every content-eligible component's
    description reaches the model, not a 5-6 entry keyword map."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    _, client = _plan([Section(heading="H", body="B", kind="body")], output)
    system_text = client.last_kwargs["system"][0]["text"]
    from src.web_builder.catalog import content_components
    for component in content_components(CATALOG):
        assert component.name in system_text or component.name in client.last_kwargs["messages"][0]["content"]


def test_the_cost_of_the_call_is_added_to_the_content():
    content = _content([Section(heading="A", body="B", kind="body")])
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    client = StubClient(output)
    assert content.cost_usd == 0.0
    build_plan(content, CATALOG, budget=Budget(), client=client, model="claude-opus-5")
    assert content.cost_usd > 0.0


def test_no_sections_means_no_call_at_all():
    content = _content([])
    client = StubClient(LayoutPlanOutput(placements=[]))
    plan = build_plan(content, CATALOG, budget=Budget(), client=client, model="claude-opus-5")
    assert client.calls == 0
    dynamic_names = {r.component for r in plan.rows}
    assert dynamic_names == {"Featured News", "News Listing", "Featured Topic Listing", "News Topic Archive"}


def test_a_button_and_document_link_are_annotated_in_the_prompt():
    section = Section(
        heading="Apply", body="B", kind="cta",
        links=[
            SectionLink(text="Apply Now", url="https://e.edu/apply", is_button=True),
            SectionLink(text="Handbook", url="https://e.edu/handbook.pdf", is_document=True),
        ])
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    _, client = _plan([section], output)
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "Apply Now (button)" in prompt
    assert "Handbook (document)" in prompt


def test_page_chrome_context_is_included_once_and_labeled_as_background_only():
    content = _content(
        [Section(heading="H", body="B", kind="body")],
        page_chrome_context="Nav: Admissions\nFooter: Copyright 2026",
    )
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    client = StubClient(output)
    build_plan(content, CATALOG, budget=Budget(), client=client, model="claude-opus-5")
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "background context only, never a section to place" in prompt
    assert "Nav: Admissions" in prompt
    assert prompt.count("Copyright 2026") == 1


def test_no_page_chrome_context_means_no_extra_block_in_the_prompt():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="prose"),
    ])
    _, client = _plan([Section(heading="H", body="B", kind="body")], output)
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "background context only" not in prompt


def test_a_video_media_ref_does_not_count_as_an_image_for_constraint_checking():
    """media_refs mixes image/video/form descriptions as plain strings --
    a video reference must not trigger "no image field" against a component
    that legitimately has no image field (this broke live: a video-only
    section was falling back to Rich Text because the video description was
    being counted as an unsupported image)."""
    from src.web_builder.match import _plan_violation
    from src.web_builder.catalog import by_name

    section = Section(heading="Watch", body="B", kind="body",
                      media_refs=["video (youtube): Our Story"])
    rich_text = by_name(CATALOG)["Rich Text"]
    assert _plan_violation(section, rich_text) is None


def test_grouped_sections_produce_one_row_covering_all_their_indices():
    """The faculty-site example move: several short, parallel sections folded into
    one Accordion, each a distinct item -- must become exactly one row
    covering every grouped index, not three separate rows."""
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Rich Text", rationale="intro"),
        SectionPlacementOutput(section_indices=[1, 2, 3], component="Accordion",
                              rationale="three short parallel lists, grouped as accordion items"),
    ])
    sections = [
        Section(heading="Intro", body="B0", kind="intro"),
        Section(heading="Publications", body="B1", kind="body"),
        Section(heading="Teaching", body="B2", kind="body"),
        Section(heading="Sponsors", body="B3", kind="body"),
    ]
    plan, _ = _plan(sections, output)
    assert len(plan.rows) == 2
    grouped_row = next(r for r in plan.rows if r.component == "Accordion")
    assert grouped_row.section_indices == [1, 2, 3]
    assert grouped_row.maps_to == "Publications, Teaching, Sponsors"


def test_group_violation_sums_link_counts_across_every_section_in_the_group():
    from src.web_builder.match import _group_violation
    from src.web_builder.models import ComponentField, ComponentSpec

    one_link_max = ComponentSpec(
        name="Synthetic One Link Component", category="Test", purpose="test fixture",
        fields=[ComponentField(name="Link", field_type="link", constraints="max 1")],
        examples=[], dynamic=False, chrome=False, shared_copy_unconfirmed=False)
    single = [Section(heading="A", body="B", kind="body",
                      links=[SectionLink(text="x", url="https://e.edu/x")])]
    assert _group_violation(single, one_link_max) is None

    grouped = single + [Section(heading="B", body="B", kind="body",
                                links=[SectionLink(text="y", url="https://e.edu/y")])]
    v = _group_violation(grouped, one_link_max)
    assert v is not None and "at most 1" in v
