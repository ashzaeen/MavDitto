"""Refine a selection or a whole section in place: shorten, expand,
simplify, and so on. Same system prompt as every other path, so a refined
passage stays in the brand voice; every result is reviewed, and redrafted
once against any blocking issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from . import templates as tpl
from .brand_voice import load_brand_voice, load_knowledge_base
from .models import VoiceSettings
from .prompting import facts_block, plain_text, relevant_facts, settings_block, system_prompt
from .review import ReviewResult, review
from ..llm_cost import Budget

ACTIONS: dict[str, str] = {
    "shorten": "Make it shorter -- cut padding and repetition, keep every fact.",
    "expand": "Expand it with more useful detail, using only facts already present in the "
              "context or the verified facts. If there is nothing true to add, make it clearer instead.",
    "simplify": "Simplify it: plainer words, shorter sentences, no jargon.",
    "rephrase": "Say the same thing a different way.",
    "warmer": "Make it warmer and more encouraging, within the brand voice.",
    "more-formal": "Make it more formal, within the brand voice.",
    "fix-grammar": "Fix grammar, punctuation and house style only -- change nothing else.",
    "add-cta": "End it with a clear, specific call to action.",
    "bullets": "Turn it into a short intro line followed by '- ' bullet lines.",
    "custom": "",
}

ACTION_LABELS = {
    "shorten": "Shorten", "expand": "Expand", "simplify": "Simplify", "rephrase": "Rephrase",
    "warmer": "Warmer", "more-formal": "More formal", "fix-grammar": "Fix grammar and style",
    "add-cta": "Add a call to action", "bullets": "Turn into bullets", "custom": "Custom instruction",
}


class RefinedOutput(BaseModel):
    text: str = Field(description="The refined passage only -- nothing before or after it.")
    brand_notes: list[str] = Field(default_factory=list, description="1-2 short notes on what changed.")


@dataclass
class RefineResult:
    text: str
    brand_notes: list[str] = field(default_factory=list)
    review: ReviewResult | None = None
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "brandNotes": list(self.brand_notes),
                "review": self.review.to_dict() if self.review else None,
                "costUsd": round(self.cost_usd, 6)}


def refine(text: str, action: str, *, instruction: str = "", context_text: str = "",
           template_key: str = "new-page", settings: VoiceSettings | None = None,
           budget: Budget | None = None, model: str | None = None,
           brand_voice: dict | None = None, knowledge_base: list[dict] | None = None,
           max_review_retries: int = 0, use_critic: bool = True, client=None) -> RefineResult:
    from .rewrite import _call, _default_model

    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    if action == "custom" and not instruction.strip():
        raise ValueError("a custom refinement needs an instruction")
    if not text.strip():
        raise ValueError("there is no text to refine")

    budget = budget or Budget()
    model = model or _default_model()
    bv = brand_voice or load_brand_voice()
    s = settings or VoiceSettings()
    t = tpl.BY_KEY.get(template_key) or tpl.get("new-page")
    facts = (knowledge_base if knowledge_base is not None else load_knowledge_base()) \
        if s.use_knowledge_base else []
    corpus = "\n".join([text, context_text] + [f["fact"] for f in facts]
                       + [r.get("example", "") for r in bv.get("registers", {}).values()])
    offered = relevant_facts(facts, f"{text}\n{context_text}", t.key, bv)

    base = [
        f"Refine the PASSAGE below. {ACTIONS[action] or instruction.strip()}",
        (f"Additional instruction: {instruction.strip()}"
         if instruction.strip() and action != "custom" else ""),
        settings_block(bv, t, s),
        facts_block(offered),
        (f"SURROUNDING CONTEXT (for reference only -- do not repeat it):\n{context_text[:6000]}"
         if context_text.strip() else ""),
        f"PASSAGE:\n{text}",
    ]
    total, issues = 0.0, None
    parsed = rv = None
    for attempt in range(max_review_retries + 1):
        prompt = "\n\n".join(p for p in base if p)
        if issues:
            prompt += "\n\nA prior attempt failed review -- fix these:\n" + "\n".join(f"- {i}" for i in issues)
        parsed, cost = _call(model, system_prompt(bv, t.key), prompt, RefinedOutput, budget,
                             client=client)
        total += cost
        rv = review([{"body": parsed.text}], bv, output_kind="snippet", keywords=None,
                    allowed_corpus=corpus, request_summary=f"Refine ({ACTION_LABELS[action]})",
                    use_critic=use_critic, budget=budget, model=model, client=client)
        total += rv.cost_usd
        if rv.passes or attempt == max_review_retries:
            break
        issues = rv.blocking()
    return RefineResult(text=plain_text(parsed.text).strip(), brand_notes=list(parsed.brand_notes),
                        review=rv, cost_usd=total)
