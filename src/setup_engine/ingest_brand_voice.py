"""Freeform brand-voice material -> a draft config/brand-voice.json shape.

One LLM call over whatever text was extracted from the uploaded material
(sample pages, a style guide, any representative writing), inferring
registers, shared principles, a seed system prompt, and -- per the resolved
open question in the design doc -- the appropriateness guardrail floor
itself, so each fork's floor matches its own brand rather than being fixed
to UTA's.

The result is a *draft*: the caller shows it on a review screen before
anything is written to `/config`, since an inferred voice profile is the
kind of thing worth a human glance before it starts shaping every rewrite.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..content_writer.pipeline import ContentInput, extract_content
from ..content_writer.rewrite import _call, _default_model
from ..llm_cost import Budget

MAX_OUTPUT_TOKENS = 4096

_SYSTEM_PROMPT = """You study writing samples from an organization's public \
website and infer a brand voice profile another writer could follow.

Work in this order: (1) read every sample first; (2) look for genuinely \
distinct registers actually present (e.g. a formal institutional voice for \
policy/about content vs. a warmer, second-person voice for service/how-to \
content) -- if the samples only support one register, return just one \
rather than inventing a second to seem thorough; (3) for every field you \
write (description, example, guardrail floor, checks), point back to \
something a sample actually does, not generic advice about "good web \
writing" that would apply to any organization.

Concretely: a bad, ungrounded description reads like "Uses clear, engaging \
language that connects with readers." A good, grounded one reads like "Uses \
short second-person sentences ('You'll need to...') and cites specific \
numbers rather than saying 'many' or 'several' -- e.g. sample 2 says '3,200 \
students' rather than 'thousands of students.'" If you cannot point to a \
specific sample sentence for a claim, do not make that claim."""


class RegisterOutput(BaseModel):
    key: str = Field(description="A short snake_case identifier, e.g. 'institutional'.")
    label: str = Field(description="A human-readable label, e.g. 'Institutional'.")
    used_for: list[str] = Field(description="Page types this register fits, e.g. ['mission', 'policy'].")
    description: str = Field(description="What makes this register distinct: person, tone, sentence structure.")
    example: str = Field(description="One real or representative sentence in this register.")


class WeAreOutput(BaseModel):
    we_are: str = Field(description="An attribute the brand is, with a short gloss.")
    we_are_not: str = Field(description="The boundary on the other side of that attribute.")
    evidence: str = Field(description="The sample sentence(s) supporting this row, and a confidence "
                                      "level (high / medium / low) per the scoring rules.")


class ToneContextOutput(BaseModel):
    template_key: str = Field(description="One of the content-type keys listed in the prompt.")
    formality: int = Field(description="1 (casual) to 5 (highly formal).")
    energy: int = Field(description="1 (measured) to 5 (high energy).")
    technical_depth: int = Field(description="1 (plain language) to 5 (specialist).")
    note: str = Field(description="One sentence of guidance for this content type.")


class PreferredTermOutput(BaseModel):
    use: str
    instead_of: str
    note: str = ""


class AudienceOutput(BaseModel):
    key: str = Field(description="A short kebab-case identifier.")
    label: str
    description: str
    reading_level: str = Field(description="One of: grade 8, grade 9, grade 10, grade 12, college.")


class OpenQuestionOutput(BaseModel):
    question: str
    recommendation: str


class BrandVoiceOutput(BaseModel):
    brand: str = Field(description="The organization's name.")
    registers: list[RegisterOutput] = Field(
        description="One or more distinct registers actually evidenced in the samples.")
    shared_principles: list[str] = Field(
        description="Vocabulary/style rules that hold across every register.")
    seed_system_prompt: str = Field(
        description="A paragraph of instructions a rewrite LLM should follow to write in this brand's voice.")
    guardrail_floor_description: str = Field(
        description="One sentence describing the appropriateness floor a tone request must never override.")
    guardrail_checks: list[str] = Field(
        description="Specific, checkable items a second reviewing pass can verify against.")
    # v2 fields -- defaulted so a model (or a test stub) that omits them still
    # yields a valid, if thinner, profile.
    brand_full_name: str = Field(default="", description="The organization's full formal name.")
    we_are: list[WeAreOutput] = Field(default_factory=list,
                                      description="4 or more We Are / We Are Not rows, each with evidence.")
    tone_by_context: list[ToneContextOutput] = Field(default_factory=list)
    preferred_terms: list[PreferredTermOutput] = Field(default_factory=list)
    banned_terms: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    audiences: list[AudienceOutput] = Field(default_factory=list)
    open_questions: list[OpenQuestionOutput] = Field(
        default_factory=list, description="Every ambiguity or conflict, each with a recommendation.")


def _extract_material_text(inputs: list[ContentInput], *, fetcher=None) -> str:
    parts = []
    for input_ in inputs:
        extracted = extract_content(input_, fetcher=fetcher)
        if not extracted.sections:
            continue
        parts.append(f"=== {extracted.page_title} ===")
        for section in extracted.sections:
            if section.heading:
                parts.append(section.heading)
            parts.append(section.body)
    return "\n\n".join(parts)


def ingest_brand_voice(inputs: list[ContentInput], *, fetcher=None,
                       budget: Budget | None = None, model: str | None = None,
                       client=None) -> dict:
    """Returns a draft brand-voice.json-shaped dict -- not yet saved."""
    budget = budget or Budget()
    model = model or _default_model()
    material = _extract_material_text(inputs, fetcher=fetcher)
    if not material.strip():
        raise RuntimeError("no readable text was found in the uploaded material")

    from ..content_writer import templates, voice_method

    template_keys = ", ".join(f"{t.key} ({t.label})" for t in templates.TEMPLATES)
    prompt = (
        "Writing samples from this organization's public website:\n\n"
        f"{material}\n\n"
        "Infer a brand voice profile from these samples. For tone_by_context, give one row per "
        f"content type that the samples give you any basis for, using these keys: {template_keys}."
    )
    system = (_SYSTEM_PROMPT + "\n\nGuideline method (vendored from Anthropic's brand-voice "
              "plugin -- follow it for the We Are table, tone matrix, confidence levels, and open "
              "questions):\n\n" + voice_method.guideline_method())
    parsed, cost = _call(model, system, prompt, BrandVoiceOutput, budget, client=client)

    return {
        "brand": parsed.brand,
        "brand_full_name": parsed.brand_full_name or parsed.brand,
        "version": "inferred-2",
        "source_note": "Inferred by the setup engine from uploaded material -- review before saving.",
        "registers": {
            r.key: {
                "label": r.label, "used_for": r.used_for,
                "description": r.description, "example": r.example,
            }
            for r in parsed.registers
        },
        "shared_principles": parsed.shared_principles,
        "seed_system_prompt": parsed.seed_system_prompt,
        "tone_options": ["Warmer", "More formal", "More concise", "More detailed"],
        "length_options": ["Match original", "Condense", "Expand"],
        "guardrail": {
            "floor_description": parsed.guardrail_floor_description,
            "checks": parsed.guardrail_checks,
        },
        "we_are": [r.model_dump() for r in parsed.we_are],
        "tone_by_context": {
            r.template_key: {"formality": max(1, min(5, r.formality)),
                             "energy": max(1, min(5, r.energy)),
                             "technical_depth": max(1, min(5, r.technical_depth)),
                             "note": r.note}
            for r in parsed.tone_by_context if r.template_key in templates.BY_KEY
        },
        "terminology": {
            "preferred": [t.model_dump() for t in parsed.preferred_terms],
            "banned": list(parsed.banned_terms),
            "style_rules": list(parsed.style_rules),
        },
        "audiences": [{**a.model_dump(), "default_register": None} for a in parsed.audiences],
        "examples": [],
        "open_questions": [q.model_dump() for q in parsed.open_questions],
        "cost_usd": cost,
    }
