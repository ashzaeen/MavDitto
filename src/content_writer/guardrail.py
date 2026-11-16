"""The guardrail pass: a second LLM call that checks a rewrite against the
brand-appropriateness floor, independent of whatever tone was requested.

Exists for the same reason `llm_judge.py` exists for the migration pipeline:
one call cannot both optimize for a requested style *and* reliably police
its own floor -- a dedicated second look, reading the actual output rather
than trusting the first call's own judgment of itself, catches drift a
single combined prompt would not.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .models import StructuredContent
from ..llm_cost import Budget

MAX_OUTPUT_TOKENS = 2048


class GuardrailResult(BaseModel):
    passes: bool = Field(description="True if the copy stays within the appropriateness floor.")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific, actionable problems found, empty if passes is true. "
                    "e.g. 'Section 2 uses slang (\"awesome\")' or "
                    "'Section 4 claims \"top-ranked\" with no cited source.'")


def _prompt(content: StructuredContent, floor_description: str, checks: list[str]) -> str:
    lines = [
        f"Appropriateness floor: {floor_description}",
        "",
        "Specific checks:",
        *[f"- {c}" for c in checks],
        "",
        f"Page title: {content.page_title}",
        f"Register: {content.register}",
        "",
        "Review every section below against the floor and checks above.",
        "",
    ]
    for i, section in enumerate(content.sections):
        lines.append(f"--- Section {i} ---")
        if section.heading:
            lines.append(f"Heading: {section.heading}")
        lines.append(f"Body:\n{section.body}")
        lines.append("")
    return "\n".join(lines)


def check(content: StructuredContent, brand_voice: dict, *,
         budget: Budget | None = None, model: str | None = None,
         client=None) -> GuardrailResult:
    from .rewrite import _call, _default_model  # shared call plumbing

    budget = budget or Budget()
    model = model or _default_model()
    guardrail = brand_voice["guardrail"]
    system = (
        "You are a strict brand-appropriateness reviewer for a university's "
        "public website copy. You do not rewrite anything -- you only judge "
        "whether the copy given to you crosses the floor described.\n\n"
        "Check every section against every item in the checklist below, one "
        "section and one checklist item at a time -- do not form an overall "
        "impression first and only skim for confirmation. A single violation "
        "in a single section is enough to fail the whole page.\n\n"
        "Also independently check every section for generic filler that "
        "could describe any organization's program, regardless of whether "
        "the checklist below names this explicitly -- phrases like "
        "\"innovative teaching methods,\" \"a rapidly evolving industry,\" "
        "\"a wealth of opportunities,\" or \"we look forward to welcoming "
        "you to our community.\" Test each sentence: would it read exactly "
        "the same on a different organization's website with only the name "
        "swapped? If yes, that sentence fails, even if no single word on "
        "the checklist is present -- a rewrite is not done just because it "
        "avoided the specific banned words if it still says nothing that "
        "couldn't be said about anyone.\n\n"
        "Be concrete when you fail something: name the section number and "
        "quote the exact word or phrase that crosses the floor (e.g. Section "
        "2 uses \"amazing\" -- an unsourced superlative), never a vague "
        "summary like \"tone issues in places.\" If every section clears "
        "every checklist item, pass it -- do not invent a minor issue just "
        "to have something to say."
    )
    prompt = _prompt(content, guardrail["floor_description"], guardrail.get("checks", []))

    parsed, cost = _call(model, system, prompt, GuardrailResult, budget, client=client)
    content.cost_usd += cost
    return parsed
