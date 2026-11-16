"""LLM rewrite: brand voice + tone/length options, applied to a whole page
in one call (the "Rewrite" button) or to a single section (the results
view's per-section regenerate button, for when only one section needs
another pass).

The actual provider call (Claude, OpenAI or Gemini, whichever is active in
`llm_config.py`) goes through `llm_provider.call_structured` -- `_call`
below is a thin wrapper kept for its existing import sites (`guardrail.py`,
`review.py`, `setup_engine/ingest_*.py`). The prompt itself is built in
`prompting.py`, shared with generate/refine.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .brand_voice import CONFIG_PATH, load_brand_voice  # noqa: F401 -- re-exported
from .models import ExtractedContent, RewriteOptions, Section, StructuredContent
from .prompting import GENERIC_AI_TELLS, plain_text, register_block, system_prompt
from .. import llm_provider
from ..llm_cost import Budget

MAX_OUTPUT_TOKENS = 8192

# Kept under their old names: web_builder/populate.py imports both.
_GENERIC_AI_TELLS = GENERIC_AI_TELLS
_register_block = register_block


def _default_model() -> str:
    """Which model to use when a caller doesn't pin one -- resolved at call
    time (not a module constant) since it depends on which provider is
    active in `llm_config.py`, which can change between calls.

    Content Writer's own default, not `llm_provider.MODELS["high"]` (that
    tier is deliberately the cheapest model per provider, used by Alt Text/
    LLM Judge/Web Builder/extraction where that tradeoff is fine). Every
    writer-facing generation path in this package defaults to the active
    provider's *recommended* model -- a solid middle tier, not its
    strongest/most expensive one (see MODEL_CATALOG's module comment in
    llm_provider.py for why) -- a writer can still opt into the top tier
    explicitly per request via `VoiceSettings.model`."""
    return llm_provider.recommended_model(llm_provider.active_provider())


_LENGTH_INSTRUCTION = {
    "Match original": "Keep each section's length close to its original length.",
    "Condense": "Condense each section into tighter, web-ready copy -- cut padding, keep every fact.",
    "Expand": "Expand thin source material (e.g. a sparse slide bullet) into fuller web copy that reads "
             "naturally on a page, without inventing facts that are not present in the source.",
}


def _system_prompt(brand_voice: dict, template_key: str | None = "rewrite-page") -> str:
    return system_prompt(brand_voice, template_key)


def _options_instruction(options: RewriteOptions, brand_voice: dict | None = None) -> str:
    from .brand_voice import register_keys

    parts = []
    if options.tone:
        parts.append(f"Tone adjustments requested: {', '.join(options.tone)}.")
    parts.append(_LENGTH_INSTRUCTION.get(options.length, _LENGTH_INSTRUCTION["Match original"]))
    if options.register_override:
        parts.append(f"Write in the {options.register_override} register regardless of what "
                     "the content itself suggests -- the person reviewing this overrode auto-detection.")
    else:
        keys = register_keys(brand_voice or {}) or ["institutional", "prospective-student"]
        parts.append(f"Detect which register ({' or '.join(keys)}) this content "
                     "calls for, and write in that register.")
    return " ".join(parts)


class RewrittenSectionOutput(BaseModel):
    heading: str | None = Field(description="Rewritten heading, or null if this section has none.")
    body: str = Field(description="Rewritten body copy for this section, in the brand voice.")
    kind: str = Field(description="One of: intro, body, cta, fact-list, quote, faq-item.")


class RewritePageOutput(BaseModel):
    page_title: str = Field(description="A clean, brand-voice-appropriate page title.")
    # Named content_register, not register: BaseModel inherits from ABCMeta,
    # whose own `register()` classmethod a field named plain "register" warns
    # about shadowing.
    content_register: str = Field(description="The register key you wrote in, e.g. 'institutional'.")
    sections: list[RewrittenSectionOutput] = Field(
        description="Exactly one rewritten section per input section, in the same order.")
    brand_notes: list[str] = Field(
        default_factory=list,
        description="2-4 short notes: which voice attributes and tone settings you applied, "
                    "and any tradeoff where the request conflicted with the guidelines.")


def _page_prompt(extracted: ExtractedContent, options: RewriteOptions,
                guardrail_issues: list[str] | None = None, *,
                brand_voice: dict | None = None, extra_instructions: str = "") -> str:
    lines = [
        f"Original page title: {extracted.page_title}",
        "",
        _options_instruction(options, brand_voice),
    ]
    if extra_instructions:
        lines += ["", extra_instructions]
    lines += [
        "",
        "Rewrite every section below. Return exactly one rewritten section per "
        "input section, in the same order -- do not merge, split, add, or drop sections. "
        "A section whose body is empty gets an empty body back: rewrite its heading only.",
        "",
    ]
    for i, section in enumerate(extracted.sections):
        lines.append(f"--- Section {i} (kind hint: {section.kind}) ---")
        if section.heading:
            lines.append(f"Heading: {section.heading}")
        lines.append(f"Body:\n{section.body}")
        if section.media_refs:
            lines.append(f"Media present: {'; '.join(section.media_refs)}")
        lines.append("")
    if guardrail_issues:
        lines.append("A prior draft failed brand review for these reasons -- "
                     "fix them specifically this time:")
        lines.extend(f"- {issue}" for issue in guardrail_issues)
    return "\n".join(lines)


def _call(model: str, system: str, prompt: str, output_format, budget: Budget,
         client=None, max_output_tokens: int = MAX_OUTPUT_TOKENS):
    """Shared call plumbing, delegating to `llm_provider` so this same entry
    point works against whichever provider is active -- `llm_provider`
    already turns SDK errors from any provider into an actionable message.
    `client` stays injectable for tests.

    Content Writer's own reasoning-effort default, not `call_structured`'s
    own ("high") -- "medium" cuts latency and the risk of a reasoning model
    burning its whole output budget on thinking (see `_call_openai`'s
    headroom bump) at some cost to how thoroughly it plans a complex page,
    which is an acceptable trade here. Scoped to this module rather than
    changed globally so a future non-writer caller of `call_structured`
    still gets "high" unless it asks otherwise."""
    return llm_provider.call_structured(
        model, system, prompt, output_format, budget,
        max_output_tokens=max_output_tokens, effort="medium", client=client)


def rewrite_page(extracted: ExtractedContent, options: RewriteOptions, *,
                 budget: Budget | None = None, model: str | None = None,
                 brand_voice: dict | None = None,
                 guardrail_issues: list[str] | None = None,
                 extra_instructions: str = "",
                 client=None) -> StructuredContent:
    budget = budget or Budget()
    model = model or _default_model()
    brand_voice = brand_voice or load_brand_voice()

    system = _system_prompt(brand_voice, "rewrite-page")
    prompt = _page_prompt(extracted, options, guardrail_issues,
                          brand_voice=brand_voice, extra_instructions=extra_instructions)

    parsed, cost = _call(model, system, prompt, RewritePageOutput, budget, client=client)

    # Rewriting only ever changes a section's heading/body text -- its real
    # links/media never came from the model, so every rewritten Section
    # carries over its original counterpart's links/media_refs by position.
    # A section with no body in the source (a heading over a row of buttons)
    # stays bodiless -- a rewrite never writes copy the source didn't have.
    sections = [
        Section(heading=plain_text(s.heading),
               body=plain_text(s.body).strip() if orig.body.strip() else "",
               kind=s.kind, links=orig.links, media_refs=orig.media_refs)
        for s, orig in zip(parsed.sections, extracted.sections)
    ]
    # A count mismatch means the model merged or split sections against
    # instructions -- fall back to the original (unrewritten) sections
    # entirely rather than hand Web Builder a structure that no longer lines
    # up with what was extracted.
    if len(parsed.sections) != len(extracted.sections):
        sections = [Section(heading=s.heading, body=s.body, kind=s.kind,
                           links=s.links, media_refs=s.media_refs)
                   for s in extracted.sections]

    return StructuredContent(
        page_title=parsed.page_title, register=parsed.content_register, sections=sections,
        original_sections=list(extracted.sections),
        source_note=extracted.source_note, cost_usd=cost,
        page_chrome_context=extracted.page_chrome_context,
        brand_notes=list(getattr(parsed, "brand_notes", []) or []))


def rewrite_section(section: Section, *, page_title: str, register: str,
                    options: RewriteOptions, budget: Budget | None = None,
                    model: str | None = None, brand_voice: dict | None = None,
                    extra_instructions: str = "", review_issues: list[str] | None = None,
                    template_key: str | None = "rewrite-page",
                    client=None) -> tuple[Section, float]:
    """Regenerate one section without redoing the whole page."""
    budget = budget or Budget()
    model = model or _default_model()
    brand_voice = brand_voice or load_brand_voice()

    system = _system_prompt(brand_voice, template_key)
    prompt = (
        f"Page title: {page_title}\nRegister: {register}\n\n"
        f"{_options_instruction(options, brand_voice)}\n\n"
        + (f"{extra_instructions}\n\n" if extra_instructions else "")
        + f"Rewrite this one section (kind hint: {section.kind}):\n"
        f"Heading: {section.heading or '(none)'}\nBody:\n{section.body}"
    )
    if review_issues:
        prompt += ("\n\nA prior draft of this section failed brand review -- fix these "
                   "specifically:\n" + "\n".join(f"- {i}" for i in review_issues))

    parsed, cost = _call(model, system, prompt, RewrittenSectionOutput, budget, client=client)
    return Section(heading=plain_text(parsed.heading), body=plain_text(parsed.body).strip(),
                   kind=parsed.kind, links=section.links, media_refs=section.media_refs), cost
