"""Section-to-component matching, as one LLM call over the whole page.

This used to be a deterministic scorer keyed off a section's `kind` hint (a
handful of keywords -- cta/faq-item/fact-list/quote/intro) plus media count
and body length. That only ever discriminated among ~6 buckets, so every
section without a strong hint -- which in practice was most of them, since
`rewrite.py` mostly tags things "body" -- fell through to the same generic
"rich text" tie-break regardless of what the section actually said. Widening
the keyword map further just moves the ceiling, it doesn't remove it: no
fixed set of keyword rules can weigh 64 real components' actual affordances
(a datapoint grid vs. a quote callout vs. a two-column content block) against
a paragraph's actual content and role on the page.

So instead this sends the model the whole picture in one call: the page's
full semantic structure (title, register, every section in order with its
kind hint, heading, body, links and media) alongside a description of every
content-eligible component in the catalog, and asks it to place each section
-- the same "read the content, read the catalog, use judgment" job a human
building the page by hand would do. One call for the whole page, not one per
section, both to bound cost the way `rewrite_page` already does and because
placement is a page-level judgment (a hero only makes sense once, at the
top) that a per-section call can't see.

Dynamic components (Featured News, News Listing, ...) never take authored
copy -- no section maps to one, so there's nothing to *place* there. But
which of them belong on a given page at all is still a real judgment call,
not a given: a broad, generic one (a "recent campus news" widget) plausibly
fits almost any page, while a narrower one tied to one specific recurring
topic (a news archive scoped to a topic tag) only fits a page that's
actually about that topic. Earlier this asked for literally none of that
judgment -- every dynamic component in the catalog was unconditionally
appended to every plan -- which was invisible while the catalog only had
two broadly-applicable ones, and stopped being invisible the moment a
topic-scoped one joined the catalog (it now showed up on pages that have
nothing to do with its topic). So this folds into the same one call as
section placement: the model is shown each dynamic component's own purpose
and asked which ones actually fit this page, rather than every dynamic
component being offered unconditionally on every page.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .. import llm_provider
from ..content_writer.models import Section, SectionLink, StructuredContent
from ..llm_cost import Budget
from .catalog import content_components, dynamic_components
from .models import ComponentSpec, LayoutPlan, LayoutPlanRow

MAX_OUTPUT_TOKENS = 8192

# Only one retry -- same shape as content_writer's guardrail loop. A second
# miss means the model isn't going to resolve it on its own; falling back
# beats spending another call chasing it.
MAX_PLAN_VALIDATION_RETRIES = 1

_MAX_COUNT_RE = re.compile(r"max\s+(\d+)", re.IGNORECASE)

# A section's body can run long (a whole extracted page section); capped here
# the same way llm_judge.py caps a passage -- the model needs enough to judge
# fit, not the entire text verbatim.
MAX_BODY_CHARS_IN_PROMPT = 1500

_FALLBACK_COMPONENT_HINT = "rich text"


def _truncate(text: str, limit: int = MAX_BODY_CHARS_IN_PROMPT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " [...]"


_SYSTEM_PROMPT = """You are laying out a university web page inside a specific \
Sitecore component library. You will be given a page's content, broken into \
ordered sections, and a catalog of every component available to build with.

Work through EVERY section using this exact procedure, in order. Do not skip \
steps or jump straight to a generic answer:

1. Read the section's heading and body. Decide what it actually IS: a list of \
facts/numbers, a single call to action, one FAQ answer, a quote/testimonial, \
a page-opening intro, or ordinary prose with no special structure.
2. Scan the ENTIRE catalog for a component whose category and notes are \
purpose-built for that same thing. Do this before considering a generic \
rich-text block -- a specific match you haven't looked for yet is not "no \
match."
3. If you found a specific match, sanity-check it against the section's media \
and links: does the component support the images/buttons/links the section \
actually has (richText, maxImages, maxButtons, links, listing)? If the fit is \
good, use it.
4. Only place a generic rich-text/body component when the section is \
genuinely plain prose with none of the structures in step 1 -- never as a \
default because you are unsure or in a hurry. Being unsure is a signal to \
re-check step 2, not to fall back.
5. A hero-type component is a single, page-opening element. Only ever place \
one for the page's first section, never for any later section even if it \
also introduces a topic.

Worked examples (a different catalog than the one below, for illustration \
only -- always choose from the actual catalog given to you, never from these \
example names):
- Section: "By the Numbers" / "12,000 students. 40 majors. 92% placement \
rate." -> This is a list of facts. Component: a facts/datapoint-grid \
component, not rich text.
- Section: "Frequently Asked Questions" / "Do I need a portfolio? No, ..." \
-> This is one FAQ answer. Component: an accordion/FAQ component, not rich text.
- Section: "Apply Today" / "Applications close March 1. Apply now." -> This \
is a single call to action. Component: a CTA/billboard component, not rich text.
- Section: "Our History" / "Founded in 1895, the college has grown into one \
of the region's largest engineering programs, with research spanning..." -> \
This is ordinary prose with no list, FAQ, quote or CTA structure. Component: \
a generic rich-text/body component IS correct here -- this is the one case \
where it's the right answer, not a fallback.
- Three separate sections: "Publications" (a short list of paper titles), \
"Teaching" (a short list of course names), "Sponsors" (a short list of \
funding sources) -> each is short and parallel to the other two, and an \
accordion-shaped component in the catalog can hold each as its own named \
item. Group all three section indices into ONE placement on that accordion \
component, with a rationale naming all three as its sub-items -- three \
separate generic rich-text placements would be the wrong call here.

Every section index must be covered by exactly one placement. Normally that \
means one placement per section -- but group several section indices into \
ONE placement when they are separate, short, clearly parallel entries (e.g. \
three short lists of related items) AND a listing- or accordion-shaped \
component in the catalog can hold each one as its own named sub-item \
without losing anything. Never group sections whose content doesn't \
actually belong together as sub-items of one whole, and never group just \
to reduce the row count -- most pages will have zero groups. If a section \
genuinely doesn't map to anything in the catalog after you've actually \
checked step 2, still name your closest approximation and explain why in a \
note.

Separately -- not as a placement -- you'll also be given a list of \
AUTO-POPULATING components: these pull their own content from a folder or \
topic tag and never take authored copy, so no section maps to one. Judge \
which of them, if any, plausibly belong on THIS page given its actual \
topic: a broad, generic one (e.g. a general "recent campus news" widget) \
fits almost any page; a narrower one scoped to one specific recurring \
topic or archive only fits a page that is actually about that same topic. \
Return the exact names of the ones that fit -- an empty list is a normal, \
common answer, not a fallback to avoid."""


class SectionPlacementOutput(BaseModel):
    section_indices: list[int] = Field(
        description="The section index/indices this placement covers, 0-based. A single-element "
                    "list for almost every placement -- more than one only when those specific "
                    "sections are being grouped into one component, per the grouping rule above.")
    component: str = Field(description="The exact name of one component from the catalog list, verbatim.")
    rationale: str = Field(
        description="One or two sentences: what the section actually is/says, and why this "
                    "specific component fits it better than the alternatives.")
    alternatives: list[str] = Field(
        default_factory=list,
        description="Up to 4 other catalog component names that would also reasonably work, "
                    "best fit first. Empty list if nothing else comes close.")


class LayoutPlanOutput(BaseModel):
    placements: list[SectionPlacementOutput] = Field(
        description="Enough entries to cover every section index exactly once across all of "
                    "them, in page order -- most placements cover one section each.")
    unmatched_notes: list[str] = Field(
        default_factory=list,
        description="One note per section that doesn't map cleanly to anything in the "
                    "catalog, naming the section and why.")
    relevant_dynamic_components: list[str] = Field(
        default_factory=list,
        description="Exact names of the auto-populating components (from the separate list "
                    "given, by exact name) that plausibly belong on this specific page. "
                    "Empty list whenever none of them genuinely fit -- do not include one "
                    "just because it's broadly available.")


def _component_block(component: ComponentSpec) -> str:
    parts = [f"- {component.name} (category: {component.category})"]
    parts.append(f"  purpose: {component.purpose}")
    for f in component.fields:
        notes = f" -- {f.notes}" if f.notes else ""
        parts.append(f"  field: {f.name} ({f.field_type}), {f.constraints}{notes}")
    if component.examples:
        parts.append(f"  examples: {'; '.join(component.examples)}")
    if component.shared_copy_unconfirmed:
        parts.append("  note: may inherit page-level title/description instead of its own fields (unconfirmed)")
    if component.visual_variant != "unspecified":
        parts.append(f"  visual style: {component.visual_variant.replace('_', ' ')} -- don't mix "
                     "'new look' and 'classic look' components on the same page")
    for sf in component.special_features:
        flag = " [CRITICAL]" if sf.importance == "critical" else ""
        parts.append(f"  special feature{flag}: {sf.name} -- {sf.description}")
    return "\n".join(parts)


def _catalog_block(candidates: list[ComponentSpec]) -> str:
    return "\n".join(_component_block(c) for c in candidates)


def _dynamic_component_block(component: ComponentSpec) -> str:
    return f"- {component.name} (category: {component.category}) -- {component.purpose}"


def _dynamic_catalog_block(dynamic: list[ComponentSpec]) -> str:
    return "\n".join(_dynamic_component_block(c) for c in dynamic)


def _link_label(link: SectionLink) -> str:
    flags = []
    if link.is_button:
        flags.append("button")
    if link.is_document:
        flags.append("document")
    suffix = f" ({', '.join(flags)})" if flags else ""
    return f"{link.text}{suffix}"


def _section_block(index: int, section: Section) -> str:
    lines = [f"--- Section {index} (kind hint: {section.kind}) ---"]
    if section.heading:
        lines.append(f"Heading: {section.heading}")
    lines.append(f"Body:\n{_truncate(section.body)}")
    if section.media_refs:
        lines.append(f"Media: {len(section.media_refs)} item(s) -- {'; '.join(section.media_refs)}")
    if section.links:
        lines.append(f"Links: {len(section.links)} -- " + "; ".join(_link_label(l) for l in section.links))
    return "\n".join(lines)


def _prompt(content: StructuredContent, candidates: list[ComponentSpec],
           dynamic: list[ComponentSpec]) -> str:
    lines = [
        "Component catalog (choose only from these, by exact name):",
        _catalog_block(candidates),
        "",
        f"Page title: {content.page_title}",
        f"Register: {content.register}",
        "",
    ]
    if content.page_chrome_context:
        lines.append("Site navigation/footer text -- background context only, never a "
                     "section to place a component against:")
        lines.append(content.page_chrome_context)
        lines.append("")
    lines.append("Sections, in page order:")
    lines.append("")
    for i, section in enumerate(content.sections):
        lines.append(_section_block(i, section))
        lines.append("")
    lines.append(f"Place all {len(content.sections)} sections.")
    if dynamic:
        lines.append("")
        lines.append("Auto-populating components (judge fit separately, per the instructions above):")
        lines.append(_dynamic_catalog_block(dynamic))
    return "\n".join(lines)


def _fallback_component(candidates: list[ComponentSpec]) -> ComponentSpec:
    for c in candidates:
        if c.name.lower() == _FALLBACK_COMPONENT_HINT:
            return c
    for c in candidates:
        if c.has_field_type("richtext"):
            return c
    return candidates[0]


def _field_max(component: ComponentSpec, field_type: str) -> int | None:
    f = component.field_of_type(field_type)
    if f is None:
        return None
    m = _MAX_COUNT_RE.search(f.constraints)
    return int(m.group(1)) if m else None


# media_refs mixes image/video/form descriptions as plain strings (see
# content_writer/extraction.py's _attach_content_media) -- only an actual
# image counts against a component's image-field constraint below; a video
# or form reference has no image-field requirement of its own.
_NON_IMAGE_MEDIA_PREFIXES = ("video (", "form:")


def _image_ref_count(media_refs: list[str]) -> int:
    return sum(1 for m in media_refs if not m.startswith(_NON_IMAGE_MEDIA_PREFIXES))


def _counts_violation(media_count: int, link_count: int, component: ComponentSpec) -> str | None:
    """One human-readable sentence naming a real, checkable constraint
    violation against this catalog's own verified fields[], or None if the
    pick is fine. Only checks what the data actually supports checking --
    no field of that type means no claim either way, not a violation."""
    if media_count:
        if not component.has_field_type("image"):
            return f"{component.name} has no image field, but this section references {media_count} image(s)"
        max_images = _field_max(component, "image")
        if max_images is not None and media_count > max_images:
            return f"{component.name} supports at most {max_images} image(s), but this section references {media_count}"

    if link_count:
        if not (component.has_field_type("link") or component.has_field_type("button")):
            return f"{component.name} has no link/button field, but this section has {link_count} link(s)"
        max_links = _field_max(component, "link")
        if max_links is not None and link_count > max_links:
            return f"{component.name} supports at most {max_links} link(s), but this section has {link_count}"

    return None


def _plan_violation(section: Section, component: ComponentSpec) -> str | None:
    """Single-section convenience wrapper around `_counts_violation` -- used
    by the swap-picker's alternatives filter, which only ever judges one
    section at a time."""
    return _counts_violation(_image_ref_count(section.media_refs), len(section.links), component)


def _group_violation(sections: list[Section], component: ComponentSpec) -> str | None:
    """Same check, summed across every section in a grouped placement --
    a group's combined image/link count is what the single chosen component
    actually has to hold."""
    media_count = sum(_image_ref_count(s.media_refs) for s in sections)
    link_count = sum(len(s.links) for s in sections)
    return _counts_violation(media_count, link_count, component)


def _index_to_placement(placements: list[SectionPlacementOutput],
                        num_sections: int) -> dict[int, SectionPlacementOutput]:
    """Every section index a placement covers maps back to that same
    placement object -- a grouped placement appears under multiple keys."""
    by_index: dict[int, SectionPlacementOutput] = {}
    for p in placements:
        for idx in p.section_indices:
            if 0 <= idx < num_sections:
                by_index[idx] = p
    return by_index


def _validate_placements(content: StructuredContent, placements: list[SectionPlacementOutput],
                         by_name: dict[str, ComponentSpec]) -> dict[int, str]:
    """section_index -> violation message, for every original section index
    whose placement (possibly a group) violates its component's fields[]."""
    violations: dict[int, str] = {}
    for p in placements:
        component = by_name.get(p.component.lower())
        if component is None:
            continue
        group_sections = [content.sections[i] for i in p.section_indices if 0 <= i < len(content.sections)]
        if not group_sections:
            continue
        v = _group_violation(group_sections, component)
        if v:
            for i in p.section_indices:
                if 0 <= i < len(content.sections):
                    violations[i] = v
    return violations


def _run_selection(content: StructuredContent, candidates: list[ComponentSpec], prompt: str,
                   budget: Budget, model: str, client
                   ) -> tuple[list[SectionPlacementOutput], list[str], list[str], float]:
    # effort="medium", not the default "high" -- on a reasoning-tier model
    # (gpt-5.4-mini and similar), "high" reasoning effort against this
    # prompt's size reliably burns the whole output-token budget on
    # reasoning tokens before ever emitting the structured plan itself,
    # surfacing as "the model declined to respond" (confirmed live).
    parsed, cost = llm_provider.call_structured(
        model, _SYSTEM_PROMPT, prompt, LayoutPlanOutput, budget,
        max_output_tokens=MAX_OUTPUT_TOKENS, effort="medium", client=client, label="web builder planner")
    return list(parsed.placements), list(parsed.unmatched_notes), list(parsed.relevant_dynamic_components), cost


def build_plan(content: StructuredContent, catalog: list[ComponentSpec], *,
               budget: Budget | None = None, model: str | None = None,
               client=None) -> LayoutPlan:
    budget = budget or Budget()
    model = model or llm_provider.default_model("medium")
    candidates = content_components(catalog)
    by_name = {c.name.lower(): c for c in candidates}
    dynamic = dynamic_components(catalog)
    dynamic_by_name = {c.name.lower(): c for c in dynamic}

    unmatched_notes: list[str] = []
    placements: list[SectionPlacementOutput] = []
    violations: dict[int, str] = {}
    # No content to judge dynamic-component fit against (an entirely empty
    # page) -- fall back to offering all of them, the old unconditional
    # behavior, rather than silently dropping every one for lack of a call.
    relevant_dynamic_names: list[str] = [c.name for c in dynamic]

    if content.sections:
        prompt = _prompt(content, candidates, dynamic)
        placements, llm_notes, relevant_dynamic_names, cost = _run_selection(
            content, candidates, prompt, budget, model, client)
        content.cost_usd += cost
        unmatched_notes.extend(llm_notes)
        violations = _validate_placements(content, placements, by_name)

        for attempt in range(MAX_PLAN_VALIDATION_RETRIES):
            if not violations:
                break
            problem_lines = []
            for i, msg in violations.items():
                section = content.sections[i]
                label = section.heading or f"Section {i + 1}"
                problem_lines.append(f"- Section {i} (\"{label}\"): {msg}")
            retry_prompt = (
                prompt + "\n\nYour previous proposal had these specific problems -- fix "
                "them, keeping every other placement the same unless it also needs to "
                "change:\n" + "\n".join(problem_lines)
            )
            placements, llm_notes, relevant_dynamic_names, cost = _run_selection(
                content, candidates, retry_prompt, budget, model, client)
            content.cost_usd += cost
            unmatched_notes.extend(llm_notes)
            violations = _validate_placements(content, placements, by_name)

    by_index = _index_to_placement(placements, len(content.sections))
    rows: list[LayoutPlanRow] = []
    processed_placement_ids: set[int] = set()
    for i, section in enumerate(content.sections):
        label = section.heading or f"Section {i + 1}"
        placement = by_index.get(i)

        if i in violations:
            # A violating group is retried once as a whole; if it's still bad,
            # fall back for that whole group (not re-split into singles), so
            # the model's grouping intent survives even when its component
            # pick didn't.
            group_indices = (
                [idx for idx in placement.section_indices if 0 <= idx < len(content.sections)]
                if placement is not None else [i]
            )
            if placement is not None and id(placement) in processed_placement_ids:
                continue
            if placement is not None:
                processed_placement_ids.add(id(placement))
            labels = [content.sections[idx].heading or f"Section {idx + 1}" for idx in group_indices]
            group_label = ", ".join(labels)
            component = _fallback_component(candidates)
            rationale = (f"the model's placement still violated a catalog constraint after "
                        f"a retry ({violations[i]}) -- falling back to a generic rich-text placement")
            alternatives = []
            unmatched_notes.append(f"\"{group_label}\": {violations[i]} -- using {component.name} as a fallback")
            rows.append(LayoutPlanRow(
                order=len(rows) + 1, component=component.name, section_indices=group_indices,
                maps_to=group_label, rationale=rationale, alternatives=alternatives))
            continue

        if placement is not None and id(placement) in processed_placement_ids:
            continue  # already emitted as part of an earlier index in this same group

        if placement is not None and placement.component.lower() in by_name:
            processed_placement_ids.add(id(placement))
            component = by_name[placement.component.lower()]
            rationale = placement.rationale
            group_indices = [idx for idx in placement.section_indices if 0 <= idx < len(content.sections)]
            labels = [content.sections[idx].heading or f"Section {idx + 1}" for idx in group_indices]
            group_label = ", ".join(labels) if labels else label
            # Only offer a swap alternative that would itself pass the same
            # hard-constraint check the chosen component just did -- the
            # swap picker shouldn't offer a component that image/link counts
            # already rule out for this group.
            group_sections = [content.sections[idx] for idx in group_indices]
            alternatives = [
                by_name[a.lower()].name for a in placement.alternatives
                if a.lower() in by_name and a.lower() != component.name.lower()
                and _group_violation(group_sections, by_name[a.lower()]) is None
            ]
            rows.append(LayoutPlanRow(
                order=len(rows) + 1, component=component.name, section_indices=group_indices,
                maps_to=group_label, rationale=rationale, alternatives=alternatives))
        else:
            component = _fallback_component(candidates)
            rationale = ("the assistant did not return a valid catalog component for this "
                        "section -- falling back to a generic rich-text placement")
            unmatched_notes.append(
                f"\"{label}\" had no valid placement returned; using {component.name} as a fallback")
            rows.append(LayoutPlanRow(
                order=len(rows) + 1, component=component.name, section_indices=[i],
                maps_to=label, rationale=rationale, alternatives=[]))

    # Never trust the model's names blindly -- same discipline as a section
    # placement, just matched against the dynamic-only catalog instead.
    seen_dynamic: set[str] = set()
    for name in relevant_dynamic_names:
        component = dynamic_by_name.get(name.lower())
        if component is None or component.name.lower() in seen_dynamic:
            continue
        seen_dynamic.add(component.name.lower())
        rows.append(LayoutPlanRow(
            order=len(rows) + 1, component=component.name, section_indices=[],
            maps_to="(structural placement only -- pulls content automatically)",
            rationale=f"{component.name} auto-populates from a folder/topic; "
                     "not a destination for rewritten copy.",
        ))

    return LayoutPlan(rows=rows, unmatched_notes=unmatched_notes)
