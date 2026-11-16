import re
from types import SimpleNamespace

from src.content_writer.models import Section, StructuredContent
from src.llm_cost import Budget
from src.web_builder.match import LayoutPlanOutput, SectionPlacementOutput
from src.web_builder.pipeline import make_plan, populate_approved_plan, populate_one_component
from src.web_builder.populate import PopulateComponentOutput, PopulatedFieldOutput

_FIELD_LINE_RE = re.compile(r"^- (.+?) \((\w+)\):", re.MULTILINE)


def _content():
    return StructuredContent(
        page_title="Campus Life", register="institutional",
        sections=[
            Section(heading="Welcome", body="Intro copy.", kind="intro"),
            Section(heading="How do I apply?", body="Short answer.", kind="faq-item"),
        ])


def _plan_stub_client():
    output = LayoutPlanOutput(placements=[
        SectionPlacementOutput(section_indices=[0], component="Hero", rationale="page opener"),
        SectionPlacementOutput(section_indices=[1], component="Accordion", rationale="an FAQ answer"),
    ])

    def _count(**kw):
        return SimpleNamespace(input_tokens=2000)

    def _parse(**kw):
        return SimpleNamespace(
            parsed_output=output, stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=2000, output_tokens=200,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))

    return SimpleNamespace(messages=SimpleNamespace(parse=_parse, count_tokens=_count))


class _PopulateStubClient:
    """Reads whichever fields a component actually asks for straight out of
    the prompt's own "Fields to populate:" list (field names vary by
    component -- Hero uses Title/Description, Accordion uses Title/Body --
    so this doesn't hardcode either) and echoes the section's body text into
    every non-title plaintext/richtext field. Good enough to exercise the
    pipeline's plumbing; populate.py's own test file covers field-type
    routing and validation in depth."""

    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=300)

    def _parse(self, **kw):
        self.calls += 1
        prompt = kw["messages"][0]["content"]
        body = "Intro copy." if "Intro copy." in prompt else (
            "Short answer." if "Short answer." in prompt else "")
        fields = []
        for name, field_type in _FIELD_LINE_RE.findall(prompt):
            if field_type in ("plaintext", "richtext") and "title" not in name.lower():
                fields.append(PopulatedFieldOutput(field_name=name, text=body))
            else:
                fields.append(PopulatedFieldOutput(field_name=name, skipped=True))
        output = PopulateComponentOutput(fields=fields)
        return SimpleNamespace(parsed_output=output, usage=SimpleNamespace(
            input_tokens=300, output_tokens=60, cache_creation_input_tokens=0,
            cache_read_input_tokens=0), stop_reason="end_turn")


def _make_plan(content):
    return make_plan(content, budget=Budget(), client=_plan_stub_client(), model="claude-opus-5")


def test_make_plan_produces_one_row_per_section_plus_dynamic_suggestions():
    plan = _make_plan(_content())
    section_rows = [r for r in plan.rows if r.section_indices]
    assert len(section_rows) == 2


def test_populate_approved_plan_returns_populated_components_and_problems():
    content = _content()
    plan = _make_plan(content)
    populated, problems = populate_approved_plan(
        content, plan, client=_PopulateStubClient(), model="claude-opus-5")
    assert len(populated) == len(plan.rows)
    assert problems == []


def test_populate_approved_plan_carries_section_content_into_fields():
    content = _content()
    plan = _make_plan(content)
    populated, _ = populate_approved_plan(
        content, plan, client=_PopulateStubClient(), model="claude-opus-5")
    section_populated = [p for p in populated if p.section_indices]
    bodies = [f.text for p in section_populated for f in p.fields if f.text]
    assert "Intro copy." in bodies
    assert "Short answer." in bodies


def test_populate_one_component_regenerates_just_that_row():
    content = _content()
    plan = _make_plan(content)
    row = next(r for r in plan.rows if r.section_indices == [0])
    populated = populate_one_component(content, row, client=_PopulateStubClient(), model="claude-opus-5")
    assert populated.section_indices == [0]
    bodies = [f.text for f in populated.fields if f.text]
    assert "Intro copy." in bodies


def test_layout_plan_round_trips_through_its_own_dict_shape():
    from src.web_builder.models import LayoutPlan

    plan = _make_plan(_content())
    restored = LayoutPlan.from_dict(plan.to_dict())
    assert len(restored.rows) == len(plan.rows)
    assert restored.rows[0].component == plan.rows[0].component
    assert restored.rows[0].section_indices == plan.rows[0].section_indices
