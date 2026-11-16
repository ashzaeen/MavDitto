"""Web Builder's populate step, now one LLM call per component -- stubbed
the same way test_web_builder_match.py stubs the plan step, since output
quality is the model's job; this file tests that field-type routing,
validation, and the retry-then-needs_review loop are wired correctly."""

from types import SimpleNamespace

from src.content_writer.models import Section, SectionLink, StructuredContent
from src.web_builder.catalog import by_name, load_catalog
from src.web_builder.models import ComponentField, ComponentSpec, LayoutPlan, LayoutPlanRow
from src.web_builder.populate import (
    ButtonItemOutput, ListItemOutput, PopulateComponentOutput, PopulatedFieldOutput, populate_plan,
)
from src.web_builder.validate import validate_component, validate_populated

CATALOG_BY_NAME = by_name(load_catalog())


def _content(sections):
    return StructuredContent(page_title="T", register="institutional", sections=sections)


def _usage(input_tokens=300, output_tokens=60):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class StubClient:
    """Returns a queued output per call (or the same one every time if only
    one was given) -- lets a test simulate "first attempt bad, retry good"."""

    def __init__(self, outputs):
        self.outputs = list(outputs) if isinstance(outputs, list) else [outputs]
        self.calls = 0
        self.last_kwargs = None
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=300)

    def _parse(self, **kw):
        self.last_kwargs = kw
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return SimpleNamespace(parsed_output=output, usage=_usage(), stop_reason="end_turn")


def _populate(sections, output, catalog=CATALOG_BY_NAME, row_component="Accordion", section_indices=None):
    content = _content(sections)
    plan = LayoutPlan(rows=[LayoutPlanRow(
        order=1, component=row_component,
        section_indices=section_indices if section_indices is not None else [0],
        maps_to="H", rationale="")])
    client = StubClient(output)
    populated = populate_plan(content, plan, catalog, client=client, model="claude-opus-5")
    return populated, client


def test_populate_fills_fields_by_type():
    output = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="H"),
        PopulatedFieldOutput(field_name="Body", text="**Body copy.**"),
        PopulatedFieldOutput(field_name="Link", skipped=True),
        PopulatedFieldOutput(field_name="Listing item", skipped=True),
    ])
    populated, client = _populate(
        [Section(heading="H", body="Body copy.", kind="body")], output)
    assert client.calls == 1
    fields = {f.name: f for f in populated[0].fields}
    assert fields["Title"].text == "H"
    assert fields["Body"].text == "**Body copy.**"
    assert fields["Link"].skipped
    assert populated[0].status == "valid"


def test_the_prompt_flags_button_and_document_links():
    section = Section(
        heading="H", body="Body copy.", kind="body",
        links=[
            SectionLink(text="Apply Now", url="https://e.edu/apply", is_button=True),
            SectionLink(text="Handbook", url="https://e.edu/handbook.pdf", is_document=True),
        ])
    output = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="H"),
        PopulatedFieldOutput(field_name="Body", text="Body copy."),
        PopulatedFieldOutput(field_name="Link", skipped=True),
        PopulatedFieldOutput(field_name="Listing item", skipped=True),
    ])
    _, client = _populate([section], output)
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "Apply Now -> https://e.edu/apply [button]" in prompt
    assert "Handbook -> https://e.edu/handbook.pdf [document]" in prompt


def test_a_component_with_max_two_buttons_can_get_both_filled():
    """The bug this fixes: a "max 2 button(s)" field used to only ever be
    able to carry one button's worth of payload -- now it can carry both."""
    section = Section(
        heading="About", body="Bio text.", kind="body",
        links=[
            SectionLink(text="View CV", url="https://e.edu/cv.pdf", is_document=True),
            SectionLink(text="Google Scholar", url="https://scholar.google.com/x"),
        ])
    output = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="About"),
        PopulatedFieldOutput(field_name="Body", text="Bio text."),
        PopulatedFieldOutput(field_name="Button", buttons=[
            ButtonItemOutput(text="View CV", url="https://e.edu/cv.pdf"),
            ButtonItemOutput(text="Google Scholar", url="https://scholar.google.com/x"),
        ]),
        PopulatedFieldOutput(field_name="Image", role_note="professional headshot"),
    ])
    populated, _ = _populate([section], output, row_component="Left Image Content Block")
    button_field = next(f for f in populated[0].fields if f.field_type == "button")
    assert len(button_field.buttons) == 2
    assert {b["text"] for b in button_field.buttons} == {"View CV", "Google Scholar"}
    assert populated[0].status == "valid"


def test_button_field_is_rejected_when_the_url_is_invented():
    """A button/link url must be one of the section's own real links --
    an invented one fails validation and triggers a retry."""
    bad = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="Apply"),
        PopulatedFieldOutput(field_name="Description", text="Apply today."),
        PopulatedFieldOutput(field_name="Button",
                             buttons=[ButtonItemOutput(text="Apply Now", url="https://example.edu/made-up")]),
    ])
    good = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="Apply"),
        PopulatedFieldOutput(field_name="Description", text="Apply today."),
        PopulatedFieldOutput(field_name="Button",
                             buttons=[ButtonItemOutput(text="Apply Now", url="https://uta.edu/apply")]),
    ])
    section = Section(heading="Apply", body="Apply today.", kind="cta",
                      links=[SectionLink(text="Apply", url="https://uta.edu/apply")])
    populated, client = _populate([section], [bad, good], row_component="CTA Accent")
    assert client.calls == 2
    button = next(f for f in populated[0].fields if f.field_type == "button")
    assert button.buttons == [{"text": "Apply Now", "url": "https://uta.edu/apply", "color": "", "colorRationale": ""}]
    assert populated[0].status == "adjusted"


def test_a_button_url_that_stays_invalid_after_retry_is_flagged_needs_review():
    bad = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="Apply"),
        PopulatedFieldOutput(field_name="Description", text="Apply today."),
        PopulatedFieldOutput(field_name="Button", text="Apply Now", url="https://example.edu/still-made-up"),
    ])
    section = Section(heading="Apply", body="Apply today.", kind="cta",
                      links=[SectionLink(text="Apply", url="https://uta.edu/apply")])
    populated, client = _populate([section], bad, row_component="CTA Accent")
    assert client.calls == 2   # one retry, still bad
    assert populated[0].status == "needs_review"
    assert populated[0].warnings


def test_image_field_gets_a_role_note_and_the_alt_text_handoff_flag():
    output = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Page Title", skipped=True),
        PopulatedFieldOutput(field_name="Page Description", text="A short description."),
        PopulatedFieldOutput(field_name="Image", role_note="A wide campus photo, landscape orientation."),
    ])
    populated, _ = _populate(
        [Section(heading="H", body="B", kind="body", media_refs=["a campus photo"])],
        output, row_component="Gradient Hero")
    image_field = next(f for f in populated[0].fields if f.field_type == "image")
    assert image_field.role_note == "A wide campus photo, landscape orientation."
    assert image_field.alt_text_handoff is True
    # Gradient Hero is sharedCopyUnconfirmed -- Page Title/Page Description are page-level
    title_field = next(f for f in populated[0].fields if f.name == "Page Title")
    assert title_field.is_page_level
    assert any("isn't confirmed" in w for w in populated[0].warnings)


def test_populate_handles_a_dynamic_structural_row_with_no_fields():
    content = _content([Section(heading="H", body="B", kind="body")])
    plan = LayoutPlan(rows=[LayoutPlanRow(order=1, component="Featured News", section_indices=[],
                                         maps_to="(structural)", rationale="")])
    populated = populate_plan(content, plan, CATALOG_BY_NAME, client=StubClient(
        PopulateComponentOutput(fields=[])))
    assert populated[0].fields == []
    assert "no fields to populate" in populated[0].warnings[0]


def test_no_llm_call_for_a_structural_row():
    content = _content([Section(heading="H", body="B", kind="body")])
    plan = LayoutPlan(rows=[LayoutPlanRow(order=1, component="Featured News", section_indices=[],
                                         maps_to="(structural)", rationale="")])
    client = StubClient(PopulateComponentOutput(fields=[]))
    populate_plan(content, plan, CATALOG_BY_NAME, client=client)
    assert client.calls == 0


# --------------------------------------------------------------------------
# validate_component (deterministic, used by the retry loop directly)
# --------------------------------------------------------------------------

_ENUM_COMPONENT = ComponentSpec(
    name="Synthetic Enum Component", category="Test", purpose="test fixture",
    fields=[ComponentField(name="Style", field_type="enum", constraints="must be one of allowedValues",
                          allowed_values=["Blue", "Orange"])],
    examples=[], dynamic=False, chrome=False, shared_copy_unconfirmed=False)


def test_validate_component_rejects_more_buttons_than_the_field_allows():
    button_component = ComponentSpec(
        name="Synthetic Max One Button", category="Test", purpose="test fixture",
        fields=[ComponentField(name="Button", field_type="button", constraints="max 1 button(s)")],
        examples=[], dynamic=False, chrome=False, shared_copy_unconfirmed=False)
    section = Section(heading="H", body="B", kind="cta",
                      links=[SectionLink(text="Go", url="https://uta.edu/go"),
                             SectionLink(text="Learn More", url="https://uta.edu/more")])
    out_by_name = {"Button": PopulatedFieldOutput(field_name="Button", buttons=[
        ButtonItemOutput(text="Go", url="https://uta.edu/go"),
        ButtonItemOutput(text="Learn More", url="https://uta.edu/more"),
    ])}
    problems = validate_component(button_component, out_by_name, section)
    assert any("at most 1" in p for p in problems)


def test_validate_component_catches_an_enum_value_outside_allowed_values():
    section = Section(heading="H", body="B", kind="body")
    out_by_name = {"Style": PopulatedFieldOutput(field_name="Style", enum_value="Purple")}
    problems = validate_component(_ENUM_COMPONENT, out_by_name, section)
    assert problems


def test_validate_component_passes_an_allowed_enum_value():
    section = Section(heading="H", body="B", kind="body")
    out_by_name = {"Style": PopulatedFieldOutput(field_name="Style", enum_value="Blue")}
    assert validate_component(_ENUM_COMPONENT, out_by_name, section) == []


def test_validate_component_requires_a_label_on_a_button():
    button_component = ComponentSpec(
        name="Synthetic Button Component", category="Test", purpose="test fixture",
        fields=[ComponentField(name="Button", field_type="button", constraints="none")],
        examples=[], dynamic=False, chrome=False, shared_copy_unconfirmed=False)
    section = Section(heading="H", body="B", kind="cta",
                      links=[SectionLink(text="Go", url="https://uta.edu/go")])
    out_by_name = {"Button": PopulatedFieldOutput(
        field_name="Button", buttons=[ButtonItemOutput(text="", url="https://uta.edu/go")])}
    problems = validate_component(button_component, out_by_name, section)
    assert any("label" in p for p in problems)


def test_validate_populated_summarizes_needs_review_components():
    from src.web_builder.models import PopulatedComponent

    populated = [
        PopulatedComponent(component="A", section_indices=[0], status="valid"),
        PopulatedComponent(component="B", section_indices=[1], status="needs_review",
                          warnings=["Button: url not one of the section's actual links"]),
    ]
    problems = validate_populated(populated)
    assert len(problems) == 1
    assert "B" in problems[0]


def test_grouped_sections_are_combined_into_one_prompt_with_delimiters():
    """A grouped row (several section_indices, per match.py's grouping
    logic) must pass ALL of its sections' content into the one populate
    call, clearly delimited -- not just the first one."""
    sections = [
        Section(heading="Publications", body="Paper A. Paper B.", kind="body"),
        Section(heading="Teaching", body="Course X. Course Y.", kind="body"),
        Section(heading="Sponsors", body="NSF. USDA.", kind="body"),
    ]
    output = PopulateComponentOutput(fields=[
        PopulatedFieldOutput(field_name="Title", text="Academic Portfolio"),
        PopulatedFieldOutput(field_name="Link", skipped=True),
        PopulatedFieldOutput(field_name="Listing item", list_items=[
            ListItemOutput(title="Publications", description="Paper A. Paper B."),
            ListItemOutput(title="Teaching", description="Course X. Course Y."),
            ListItemOutput(title="Sponsors", description="NSF. USDA."),
        ]),
    ])
    populated, client = _populate(sections, output, row_component="Accordion", section_indices=[0, 1, 2])
    prompt = client.last_kwargs["messages"][0]["content"]
    assert "--- Source section: Publications ---" in prompt
    assert "--- Source section: Teaching ---" in prompt
    assert "--- Source section: Sponsors ---" in prompt
    assert populated[0].section_indices == [0, 1, 2]
    listing_field = next(f for f in populated[0].fields if f.field_type == "listing")
    assert len(listing_field.list_items) == 3
