"""Phase 2: turn an approved layout plan into populated, ready-to-paste
fields. One LLM call per component (not per page) -- population output
scales with a component's own field count, not the catalog size, which
keeps a single "regenerate this component" action cheap.

Field content is type-aware per the catalog's own fields[]
(richtext/plaintext/link/button/image/enum/date): rich text comes back
formatted; a button field comes back as a label + color + rationale trio,
never inventing a URL -- always one of the section's own real links; an
image field comes back as a role note plus an explicit Alt Text tool
handoff flag, never alt text itself; an enum field is constrained to its
allowedValues; plain text as before, with a character count only when a
real limit is known.

Validated by `validate.py` after every call; a violation retries this same
component's call once (`MAX_POPULATE_RETRIES`) with the specific problem
named -- the same guardrail-style loop `match.py`'s plan step already uses.
Unresolved after that, the component is flagged `needs_review` rather than
silently kept or dropped.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from pydantic import BaseModel, Field

from .. import llm_provider
from ..content_writer.models import StructuredContent
from ..content_writer.rewrite import _GENERIC_AI_TELLS, _register_block, load_brand_voice
from ..llm_cost import Budget
from .models import ComponentField, ComponentSpec, LayoutPlan, PopulatedComponent, PopulatedField
from .validate import validate_component

MAX_OUTPUT_TOKENS = 4096
MAX_POPULATE_RETRIES = 1

_MAX_COUNT_RE = re.compile(r"(\d+)\s*char", re.IGNORECASE)

# Population used to have zero brand-voice grounding -- a URL fed straight
# into Web Builder (bypassing Content Writer's rewrite_page) got its copy
# written by a prompt that never saw the brand voice doc at all. This is
# very likely the single biggest quality gap versus a human feeding the same
# catalog + brand voice + page directly to a model themselves: reuses
# rewrite.py's own pieces (never duplicated) so the two paths -- rewrite-then-
# populate and populate-straight-from-a-URL -- actually sound the same.
_FIELD_TYPE_INSTRUCTIONS = """For each field, follow its fieldType:
- richtext: format the section's body using basic structure (bold/italic, \
headings, bulleted/numbered lists, hyperlinks) where the content actually \
calls for it -- don't invent structure that isn't there.
- plaintext: plain prose, matching the field's role (a title is short and \
specific, a description is the supporting sentence).
- link: choose the URL from the section's own listed links only -- never \
invent one.
- button: a field's constraints name its max button count (e.g. "max 2 \
button(s)") -- return one entry per distinct real call-to-action the \
section actually supports, up to that max. Never invent a second button \
just to fill the count, and never merge two distinct real CTAs into one \
button when the field's max allows both to be returned separately. Each \
button needs a URL from the section's own listed links, a short verb-led \
label (e.g. "Apply Now"), and, only if the field's constraints name \
specific allowed colors, a color chosen from exactly those with one \
sentence explaining why.
- image: check the section's own media references first. If one already \
describes a real image or video (anything other than a "form:" entry), \
write a short note describing THAT real one -- its actual subject, not a \
generic guess. If the section has no real image/video reference, suggest a \
concrete, searchable stock-photo phrase instead (e.g. "engineering lab, \
students working with robotics equipment"), framed as something to search \
a stock-photo library for -- never a literal file name, and never invented \
alt text. The actual alt text is handled elsewhere -- never write it here.
- enum: choose one value, and it must be exactly one of the field's listed \
allowed values, verbatim.
- date: use a date the section actually states; never invent one.
- listing: split the section's body into the discrete items it ALREADY \
contains (e.g. existing bullet points, a numbered list, several already- \
separate short entries) -- one output item per real item, each with a \
short title and description drawn only from that item's own text, and a \
url only if the section's own links naturally match that specific item. \
Never invent an item to reach some target count; if the body is one \
continuous paragraph with no discrete items, return zero items and mark \
the field skipped.

If the section has nothing for a field (e.g. no links to put in a Link \
field), mark that field skipped rather than inventing content."""


def _system_prompt(brand_voice: dict) -> str:
    return (
        f"{brand_voice['seed_system_prompt']}\n\n"
        f"Registers:\n{_register_block(brand_voice)}\n\n"
        f"Shared principles: {'; '.join(brand_voice['shared_principles'])}\n\n"
        f"Never violate this floor, regardless of which register a field's content calls for: "
        f"{brand_voice['guardrail']['floor_description']}\n\n"
        "Generic AI marketing copy is a common failure here, and the floor above forbids it -- "
        "avoid phrases like " + ", ".join(f'"{t}"' for t in _GENERIC_AI_TELLS) +
        ". If a sentence would read the same on any other organization's website with the name "
        "swapped out, it is too generic -- ground it in this section's own specific facts.\n\n"
        "You populate one Sitecore component's fields from a page section's actual content. "
        "Before writing any field: (1) decide which register (institutional or "
        "prospective-student) this section's own content and purpose call for, matching that "
        "register's own example as closely as the content allows -- a recruitment/call-to-action "
        "section usually wants the prospective-student register even on an otherwise "
        "institutional page, so judge this per section, not once for the whole page; (2) if the "
        "section's source text is already well-written and on-brand, keep its substance as-is "
        "rather than rewriting for its own sake -- if it is informal, sparse, or off-register, "
        "rewrite it into the chosen register. In both cases, fill in only what the section "
        "actually supports -- never invent a fact, a link destination, or a statistic the "
        "section doesn't contain.\n\n" + _FIELD_TYPE_INSTRUCTIONS +
        "\n\nWorked example (illustration only -- always use the real section/component given to "
        "you, never these names): a section titled \"About\" with informal source text (\"works on "
        "robots and stuff, check out his cv and google scholar\") and two links -- CV and Google "
        "Scholar -- populating a component whose Button field allows max 2: return BOTH buttons "
        "(\"View CV\" -> the CV link, \"View Google Scholar\" -> the scholar link), not just one, "
        "and rewrite the informal body into the institutional register (e.g. \"His research focuses "
        "on robot perception and autonomy.\") while keeping every fact the source actually stated."
    )


class ListItemOutput(BaseModel):
    title: str | None = Field(default=None, description="short title for this one listing item.")
    description: str | None = Field(default=None, description="supporting text for this one listing item.")
    url: str | None = Field(
        default=None, description="this item's link, only if it's one of the section's own listed "
                                  "link URLs, verbatim -- otherwise leave unset.")


class ButtonItemOutput(BaseModel):
    text: str = Field(description="short, verb-led button label, e.g. 'Apply Now'.")
    url: str = Field(description="this button's destination -- must be one of the section's own "
                                 "listed link URLs, verbatim.")
    color: str | None = Field(default=None, description="button color, only if the field names allowed colors.")
    color_rationale: str | None = Field(default=None, description="one sentence: why this color.")


class PopulatedFieldOutput(BaseModel):
    field_name: str = Field(description="Exact field name from the catalog, verbatim.")
    skipped: bool = Field(default=False, description="True if the section has nothing for this field.")
    text: str | None = Field(default=None, description="plaintext/richtext value.")
    url: str | None = Field(
        default=None, description="link field only -- must be one of the section's own listed "
                                  "link URLs, verbatim.")
    role_note: str | None = Field(default=None, description="image field: what kind of image belongs here and why.")
    enum_value: str | None = Field(default=None, description="enum field: one of the field's allowedValues, verbatim.")
    list_items: list[ListItemOutput] = Field(
        default_factory=list, description="listing field only: one entry per real, already-discrete "
                                          "item the section's content contains. Never padded to a target count.")
    buttons: list[ButtonItemOutput] = Field(
        default_factory=list, description="button field only: one entry per real, distinct "
                                          "call-to-action, up to the field's own max -- never padded.")


class PopulateComponentOutput(BaseModel):
    fields: list[PopulatedFieldOutput] = Field(
        description="Exactly one entry per field in this component's catalog fields[], in the same order.")


def _section_block(section) -> str:
    lines = [f"Heading: {section.heading or '(none)'}", f"Body:\n{section.body}"]
    if section.links:
        lines.append("Links available (choose from these only, never invent another URL):")
        for link in section.links:
            flags = [f for f, v in (("button", link.is_button), ("document", link.is_document)) if v]
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {link.text} -> {link.url}{suffix}")
    if section.media_refs:
        lines.append(
            "Media referenced (for a role note only, never a literal filename): "
            + "; ".join(section.media_refs))
    return "\n".join(lines)


def _field_block(f: ComponentField) -> str:
    allowed = f" allowedValues: {f.allowed_values}" if f.allowed_values else ""
    notes = f" -- {f.notes}" if f.notes else ""
    return f"- {f.name} ({f.field_type}): {f.constraints}{allowed}{notes}"


def _special_features_block(component: ComponentSpec) -> list[str]:
    if not component.special_features:
        return []
    lines = ["Configuration parameters this component exposes (not fields to populate, but useful "
             "context -- e.g. a 'listing' field's item count should be genuine, not padded to match "
             "one of these):"]
    for sf in component.special_features:
        flag = " [CRITICAL]" if sf.importance == "critical" else ""
        lines.append(f"  - {sf.name}{flag}: {sf.description}")
    return lines


def _combined_section_block(sections: list) -> str:
    """One section renders exactly as before. Several (a grouped placement --
    see match.py's grouping rule) render as clearly delimited sub-blocks, so
    a `listing` field can produce one item per real source section instead
    of blending them into one blob."""
    if len(sections) == 1:
        return _section_block(sections[0])
    parts = []
    for s in sections:
        parts.append(f"--- Source section: {s.heading or '(untitled)'} ---")
        parts.append(_section_block(s))
        parts.append("")
    return "\n".join(parts).rstrip()


def _prompt(sections: list, component: ComponentSpec, problems: list[str] | None = None) -> str:
    lines = [
        f"Component: {component.name}",
        f"Purpose: {component.purpose}",
        "Fields to populate:",
        *[_field_block(f) for f in component.fields],
        *_special_features_block(component),
        "",
    ]
    if len(sections) > 1:
        lines.append("Source content (multiple sections grouped into this one component -- "
                     "e.g. a listing field should get one item per source section below, "
                     "not one blended item):")
    else:
        lines.append("Section content:")
    lines.append(_combined_section_block(sections))
    if problems:
        lines.append("")
        lines.append("Your previous attempt had these specific problems -- fix them:")
        lines.extend(f"- {p}" for p in problems)
    return "\n".join(lines)


def _char_limit(field_spec: ComponentField) -> int | None:
    m = _MAX_COUNT_RE.search(field_spec.constraints)
    return int(m.group(1)) if m else None


def _to_populated_field(field_spec: ComponentField, out: PopulatedFieldOutput | None, *,
                        is_page_level: bool) -> PopulatedField:
    if out is None or out.skipped:
        return PopulatedField(name=field_spec.name, field_type=field_spec.field_type,
                              is_page_level=is_page_level, skipped=True)

    pf = PopulatedField(name=field_spec.name, field_type=field_spec.field_type, is_page_level=is_page_level)
    if field_spec.field_type in ("plaintext", "richtext"):
        pf.text = out.text or ""
        pf.char_limit = _char_limit(field_spec)
    elif field_spec.field_type == "link":
        pf.url = out.url or ""
        pf.text = out.text or ""
    elif field_spec.field_type == "button":
        pf.buttons = [
            {"text": b.text, "url": b.url, "color": b.color or "", "colorRationale": b.color_rationale or ""}
            for b in out.buttons
        ]
        if not pf.buttons:
            pf.skipped = True
    elif field_spec.field_type == "image":
        pf.role_note = out.role_note or ""
        pf.alt_text_handoff = True
    elif field_spec.field_type == "enum":
        pf.enum_value = out.enum_value or ""
    elif field_spec.field_type == "date":
        pf.text = out.text or ""
    elif field_spec.field_type == "listing":
        pf.list_items = [item.model_dump(exclude_none=True) for item in out.list_items]
        if not pf.list_items:
            pf.skipped = True
    return pf


def _populate_component(sections: list, component: ComponentSpec, *, budget: Budget,
                        model: str, client, system_prompt: str) -> tuple[PopulatedComponent, float]:
    problems: list[str] | None = None
    status = "valid"
    total_cost = 0.0
    out_by_name: dict[str, PopulatedFieldOutput] = {}
    # validate_component only ever reads `.links` off what's passed as
    # `section` -- a real section for the (overwhelmingly common) one-section
    # case, or this stand-in carrying every grouped section's links combined,
    # so a button/link field can still cite any of the group's real URLs.
    combined_links = SimpleNamespace(links=[l for s in sections for l in s.links])

    for attempt in range(MAX_POPULATE_RETRIES + 1):
        prompt = _prompt(sections, component, problems)
        # effort="medium", not the default "high" -- see match.py's identical
        # note; a reasoning-tier model at "high" effort reliably burns the
        # whole output-token budget on reasoning before emitting a result.
        parsed, cost = llm_provider.call_structured(
            model, system_prompt, prompt, PopulateComponentOutput, budget,
            max_output_tokens=MAX_OUTPUT_TOKENS, effort="medium", client=client, label="web builder populate")
        total_cost += cost
        out_by_name = {o.field_name: o for o in parsed.fields}

        problems = validate_component(component, out_by_name, combined_links)
        if not problems:
            break
        status = "adjusted"
    if problems:
        status = "needs_review"

    fields = [
        _to_populated_field(f, out_by_name.get(f.name), is_page_level=component.shared_copy_unconfirmed)
        for f in component.fields
    ]
    warnings = list(problems) if problems else []
    critical_features = [sf for sf in component.special_features if sf.importance == "critical"]
    if critical_features:
        listing_counts = [len(f.list_items) for f in fields if f.field_type == "listing" and not f.skipped]
        count_note = f" (populated {listing_counts[0]} listing item(s) here)" if listing_counts else ""
        for sf in critical_features:
            warnings.append(f"Critical setting in Sitecore -- {sf.name}: {sf.description}{count_note}")
    if component.shared_copy_unconfirmed:
        warnings.append(
            "This variant may not have its own Title/Body fields -- the original design "
            "doc claims it inherits from the page's own Title/Description instead. That "
            "claim isn't confirmed by the public design system; verify in Sitecore before pasting.")

    return PopulatedComponent(
        component=component.name, section_indices=[], fields=fields,
        warnings=warnings, status=status), total_cost


def _populate_row(content: StructuredContent, row, component: ComponentSpec | None, *,
                  budget: Budget, model: str, client, system_prompt: str) -> tuple[PopulatedComponent, float]:
    if component is None or not row.section_indices:
        return PopulatedComponent(
            component=row.component, section_indices=[], fields=[],
            warnings=[] if component is None else
            ["structural placement only -- pulls content automatically, no fields to populate"],
        ), 0.0

    sections = [content.sections[i] for i in row.section_indices if 0 <= i < len(content.sections)]
    populated, cost = _populate_component(
        sections, component, budget=budget, model=model, client=client, system_prompt=system_prompt)
    populated.section_indices = list(row.section_indices)
    return populated, cost


def populate_plan(content: StructuredContent, plan: LayoutPlan,
                  catalog_by_name: dict[str, ComponentSpec], *,
                  budget: Budget | None = None, model: str | None = None,
                  client=None, brand_voice: dict | None = None) -> list[PopulatedComponent]:
    budget = budget or Budget()
    model = model or llm_provider.default_model("medium")
    system_prompt = _system_prompt(brand_voice or load_brand_voice())
    populated: list[PopulatedComponent] = []
    for row in plan.rows:
        component, cost = _populate_row(
            content, row, catalog_by_name.get(row.component), budget=budget, model=model,
            client=client, system_prompt=system_prompt)
        content.cost_usd += cost
        populated.append(component)
    return populated
