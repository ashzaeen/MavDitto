"""Generate copy for any template: brief + voice settings (+ optional source
material) -> 1-3 reviewed variants.

Each variant is drafted, reviewed (rules + critic), and redrafted against the
review's critical issues up to `max_review_retries` times. The final draft is
always reviewed, and that review ships with it -- the writer sees exactly
what is still flagged, never an unchecked last attempt.

Variants are drafted one after another, not in parallel: `Budget` checks
before each call and records after it, and concurrent calls could each pass
the check and jointly overspend. Each later variant is told how the earlier
ones opened, so the options genuinely differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from . import templates as tpl
from .brand_voice import load_brand_voice, load_knowledge_base
from .models import (
    ComposedPage, ExtractedContent, RewriteOptions, Section, StructuredContent, VoiceSettings,
)
from .prompting import (
    facts_block, plain_text, relevant_facts, settings_block, system_prompt, uta_context,
)
from .review import ReviewResult, review, units_from_sections
from ..llm_cost import Budget, BudgetExceeded

MAX_REVIEW_RETRIES = 0     # one draft; the review is advisory, not a gate
MAX_OUTPUT_TOKENS = 8192
# News copy follows AP style by convention; the review checks its dates.
AP_STYLE_TEMPLATES = ("news-story", "press-release")


class GeneratedSection(BaseModel):
    heading: str | None = Field(description="Section heading, or null for none.")
    body: str = Field(description="Section body copy. Plain text; use '- ' lines for lists.")
    kind: str = Field(description="One of: intro, body, cta, fact-list, quote, faq-item.")


class GeneratedPageOutput(BaseModel):
    page_title: str = Field(description="The page title or headline.")
    content_register: str = Field(description="The register key you wrote in.")
    sections: list[GeneratedSection]
    brand_notes: list[str] = Field(
        default_factory=list,
        description="2-4 short notes: which voice attributes and tone settings you applied, and "
                    "any tradeoff where the request conflicted with the guidelines.")


class GeneratedItem(BaseModel):
    text: str = Field(description="The option itself.")
    note: str = Field(default="", description="A few words on this option's angle.")


class GeneratedItemsOutput(BaseModel):
    items: list[GeneratedItem]
    brand_notes: list[str] = Field(default_factory=list)


@dataclass
class GenerationRequest:
    template_key: str
    brief: dict[str, str] = field(default_factory=dict)
    settings: VoiceSettings = field(default_factory=VoiceSettings)
    source: Any = None                      # pipeline.ContentInput | None


@dataclass
class Variant:
    kind: str                               # page | items | blocks
    page: StructuredContent | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    composed: ComposedPage | None = None
    review: ReviewResult | None = None
    brand_notes: list[str] = field(default_factory=list)
    attempts: int = 1
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "page": self.page.to_dict() if self.page else None,
            "items": list(self.items),
            "composed": self.composed.to_dict() if self.composed else None,
            "review": self.review.to_dict() if self.review else None,
            "brandNotes": list(self.brand_notes),
            "attempts": self.attempts,
            "costUsd": round(self.cost_usd, 6),
        }


@dataclass
class GenerationResult:
    template_key: str
    variants: list[Variant] = field(default_factory=list)
    cost_usd: float = 0.0
    notice: str = ""
    source_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateKey": self.template_key,
            "variants": [v.to_dict() for v in self.variants],
            "costUsd": round(self.cost_usd, 6),
            "notice": self.notice,
            "sourceTitle": self.source_title,
        }


# --------------------------------------------------------------------------
# prompt pieces
# --------------------------------------------------------------------------

def allowed_corpus(brief: dict[str, str], extracted: ExtractedContent | None,
                   facts: list[dict[str, Any]], settings: VoiceSettings,
                   bv: dict[str, Any] | None = None) -> str:
    """Everything a draft may draw facts from -- the critic and the figure
    check both measure the draft against exactly this. The profile's
    register examples count: they are the brand's own published sentences
    (UTA's mission line, "committed to providing access", among them)."""
    parts = [f"{k}: {v}" for k, v in brief.items() if str(v).strip()]
    if bv:
        parts += [r.get("example", "") for r in bv.get("registers", {}).values()]
    parts += [f["fact"] for f in facts]
    parts += settings.must_include
    if settings.cta:
        parts.append(settings.cta)
    if extracted:
        parts.append(extracted.page_title)
        for s in extracted.sections:
            parts += [s.heading or "", s.body]
    return "\n".join(p for p in parts if p)


def source_text(extracted: ExtractedContent | None) -> str:
    if not extracted:
        return ""
    return "\n".join([extracted.page_title]
                     + [f"{s.heading or ''}\n{s.body}" for s in extracted.sections])


def _covers(t: tpl.ContentTemplate, s: VoiceSettings, extracted: ExtractedContent | None) -> bool:
    return tpl.covers(t, s.length, s.target_words, extracted is not None)


def _source_block(extracted: ExtractedContent | None, cover: bool = False) -> str:
    if not extracted:
        return ""
    lead = ("carry every fact from here into the page" if cover
            else "facts may come from here")
    lines = [f"SOURCE MATERIAL (title: {extracted.page_title}) -- {lead}:"]
    for i, s in enumerate(extracted.sections):
        lines.append(f"--- {i} ---")
        if s.heading:
            lines.append(f"Heading: {s.heading}")
        lines.append(s.body)
    return "\n".join(lines)


def _brief_block(t: tpl.ContentTemplate, brief: dict[str, str]) -> str:
    rows = []
    labels = {f.name: f.label for f in t.fields}
    for name, value in brief.items():
        if str(value).strip():
            rows.append(f"{labels.get(name, name)}:\n{str(value).strip()}")
    return "BRIEF:\n" + "\n\n".join(rows) if rows else ""


def request_summary(t: tpl.ContentTemplate, s: VoiceSettings) -> str:
    bits = [f"Content type: {t.label}"]
    if s.audience:
        bits.append(f"audience {s.audience}")
    if s.goal:
        bits.append(f"goal {s.goal}")
    if s.dials:
        bits.append("dials " + ", ".join(f"{k}={v}" for k, v in s.dials.items()))
    if s.tone:
        bits.append("tone " + ", ".join(s.tone))
    if s.reading_level:
        bits.append(f"reading level {s.reading_level}")
    return "; ".join(bits)


def _generate_prompt(t, brief, s, bv, facts, extracted, *, differ_from, issues) -> str:
    parts = [f"Content type: {t.label} -- {t.description}"]
    if t.instructions:
        parts.append(f"Instructions: {t.instructions}")
    if t.output_kind == "items":
        limit = f", each {t.char_limit} characters or fewer (count carefully)" if t.char_limit else ""
        parts.append(f"Write {s.item_count} distinct options{limit}.")
    else:
        if t.sections_hint:
            parts.append(f"Structure: {t.sections_hint}")
        words = len(source_text(extracted).split()) or None
        parts.append("Length: " + tpl.length_instruction(t, s.length, s.target_words, words))
    parts.append(settings_block(bv, t, s))
    if ctx := uta_context(bv):
        parts.append(ctx)
    for block in (_brief_block(t, brief), facts_block(facts),
                  _source_block(extracted, _covers(t, s, extracted))):
        if block:
            parts.append(block)
    if differ_from:
        parts.append("Earlier variants opened like this -- take a clearly different angle and "
                     "opening:\n" + "\n".join(f"- {o}" for o in differ_from))
    if issues:
        parts.append("A prior draft failed review for these reasons -- fix them specifically:\n"
                     + "\n".join(f"- {i}" for i in issues))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# drafting
# --------------------------------------------------------------------------

def _draft(t, brief, s, bv, facts, extracted, *, differ_from, issues, budget, model, client):
    """One draft -> (Variant without review, cost)."""
    from .rewrite import _call, _default_model, rewrite_page

    if t.output_kind == "blocks":
        from . import compose
        page, cost = compose.draft_compose(brief.get("prompt", ""), s, bv=bv, facts=facts,
                                           extracted=extracted, differ_from=differ_from,
                                           issues=issues, budget=budget, model=model, client=client)
        return Variant("blocks", composed=page, brand_notes=page.brand_notes), cost

    if t.key == "rewrite-page":
        extra = "\n\n".join(p for p in (settings_block(bv, t, s), uta_context(bv),
                                        facts_block(facts)) if p)
        if differ_from:
            extra += ("\n\nEarlier variants opened like this -- vary the phrasing:\n"
                      + "\n".join(f"- {o}" for o in differ_from))
        opts = RewriteOptions(tone=s.tone, length=s.length or "Match original",
                              register_override=s.register)
        page = rewrite_page(extracted, opts, budget=budget, model=model, brand_voice=bv,
                            guardrail_issues=issues, extra_instructions=extra, client=client)
        return Variant("page", page=page, brand_notes=page.brand_notes), page.cost_usd

    model = model or _default_model()
    system = system_prompt(bv, t.key)
    prompt = _generate_prompt(t, brief, s, bv, facts, extracted,
                              differ_from=differ_from, issues=issues)
    if t.output_kind == "items":
        parsed, cost = _call(model, system, prompt, GeneratedItemsOutput, budget, client=client,
                             max_output_tokens=MAX_OUTPUT_TOKENS)
        texts = [(plain_text(it.text).strip(), it.note) for it in parsed.items]
        items = [{"text": t_, "chars": len(t_), "note": n} for t_, n in texts if t_]
        return Variant("items", items=items, brand_notes=list(parsed.brand_notes)), cost

    parsed, cost = _call(model, system, prompt, GeneratedPageOutput, budget, client=client,
                         max_output_tokens=MAX_OUTPUT_TOKENS)
    sections = [Section(heading=plain_text(s_.heading), body=plain_text(s_.body).strip(),
                        kind=s_.kind)
                for s_ in parsed.sections]
    page = StructuredContent(
        page_title=parsed.page_title, register=parsed.content_register, sections=sections,
        original_sections=list(extracted.sections) if extracted else [],
        source_note=extracted.source_note if extracted else "", cost_usd=cost,
        page_chrome_context=extracted.page_chrome_context if extracted else "",
        brand_notes=list(parsed.brand_notes))
    return Variant("page", page=page, brand_notes=list(parsed.brand_notes)), cost


def _units(v: Variant) -> list[dict[str, Any]]:
    from .compose import units_from_blocks

    if v.kind == "blocks":
        return units_from_blocks(v.composed.blocks)
    return units_from_sections(v.page.sections) if v.kind == "page" else \
        [{"text": it["text"]} for it in v.items]


def _opening(v: Variant) -> str:
    if v.kind == "items":
        return v.items[0]["text"] if v.items else ""
    if v.kind == "blocks":
        from .compose import opening_text
        return opening_text(v.composed)
    body = next((s.body for s in v.page.sections if s.body.strip()), "")
    return body.split(". ")[0][:160]


def review_variant(v: Variant, t: tpl.ContentTemplate, s: VoiceSettings, bv: dict[str, Any],
                   corpus: str, *, budget, model, client, use_critic: bool = True,
                   extracted: ExtractedContent | None = None) -> ReviewResult:
    # Every source detail must survive a rewrite or a full-coverage page; at a
    # shorter chosen length, what was dropped is reported, not failed.
    if extracted is None or v.kind != "page":
        coverage = ""
    elif t.key == "rewrite-page" or _covers(t, s, extracted):
        coverage = "required"
    else:
        coverage = "report"
    kwargs = dict(output_kind=v.kind, char_limit=t.char_limit, keywords=s.keywords,
                  reading_level=s.reading_level or _audience_level(bv, s, t),
                  allowed_corpus=corpus, request_summary=request_summary(t, s),
                  ap_style=t.key in AP_STYLE_TEMPLATES,
                  source_text=source_text(extracted), coverage=coverage, strictness=s.strictness)
    try:
        return review(_units(v), bv, use_critic=use_critic, budget=budget, model=model,
                      client=client, **kwargs)
    except BudgetExceeded as exc:
        rv = review(_units(v), bv, use_critic=False, **kwargs)
        from .review import SUGGESTED, ReviewIssue
        rv.issues.append(ReviewIssue(SUGGESTED, f"Brand critic skipped: {exc}"))
        return rv


def _audience_level(bv, s, t) -> str:
    key = s.audience or t.default_audience
    a = next((a for a in bv.get("audiences", []) if a.get("key") == key), None)
    return (a or {}).get("reading_level", "")


def generate(req: GenerationRequest, *, fetcher=None, budget: Budget | None = None,
             model: str | None = None, brand_voice: dict | None = None,
             knowledge_base: list[dict[str, Any]] | None = None,
             max_review_retries: int = MAX_REVIEW_RETRIES, use_critic: bool = True,
             client=None) -> GenerationResult:
    from .pipeline import extract_content

    budget = budget or Budget()
    bv = brand_voice or load_brand_voice()
    t = tpl.get(req.template_key)
    s = req.settings
    facts = (knowledge_base if knowledge_base is not None else load_knowledge_base()) \
        if s.use_knowledge_base else []

    extracted = None
    if req.source is not None:
        if not t.accepts_source and not t.requires_source:
            raise ValueError(f"{t.label} does not take source material")
        extracted = extract_content(req.source, fetcher=fetcher, budget=budget)
    missing = tpl.missing_required(t, req.brief, extracted is not None)
    if missing:
        raise ValueError("Missing: " + ", ".join(missing))

    corpus = allowed_corpus(req.brief, extracted, facts, s, bv)
    # Offer every fact on file: the writer picks what helps. (Filtering by word overlap
    # starved broad "why choose us" requests of all 17 facts.)
    offered = facts
    result = GenerationResult(template_key=t.key,
                              source_title=extracted.page_title if extracted else "")
    openings: list[str] = []
    for n in range(s.variants):
        try:
            v = _variant(t, req.brief, s, bv, offered, extracted, corpus, differ_from=openings,
                         max_review_retries=max_review_retries, use_critic=use_critic,
                         budget=budget, model=model, client=client)
        except BudgetExceeded as exc:
            if not result.variants:
                raise
            result.notice = f"Stopped after {n} of {s.variants} variants: {exc}"
            break
        result.variants.append(v)
        result.cost_usd += v.cost_usd
        openings.append(_opening(v))
    return result


def regenerate_section(section: Section, *, page_title: str, register: str,
                       settings: VoiceSettings, template_key: str = "rewrite-page",
                       context_text: str = "", budget: Budget | None = None,
                       model: str | None = None, brand_voice: dict | None = None,
                       knowledge_base: list[dict[str, Any]] | None = None,
                       max_review_retries: int = 0, use_critic: bool = True,
                       client=None) -> tuple[Section, ReviewResult, float]:
    """Redraft one section, reviewed like every other draft. Links and media
    ride along untouched on the returned Section."""
    from .rewrite import rewrite_section

    budget = budget or Budget()
    bv = brand_voice or load_brand_voice()
    t = tpl.BY_KEY.get(template_key) or tpl.get("rewrite-page")
    facts = (knowledge_base if knowledge_base is not None else load_knowledge_base()) \
        if settings.use_knowledge_base else []
    corpus = "\n".join([section.heading or "", section.body, context_text]
                       + [f["fact"] for f in facts]
                       + [r.get("example", "") for r in bv.get("registers", {}).values()])
    offered = relevant_facts(facts, "\n".join([section.heading or "", section.body, context_text]),
                             t.key, bv)
    extra = "\n\n".join(p for p in (settings_block(bv, t, settings), facts_block(offered)) if p)
    opts = RewriteOptions(tone=settings.tone, length=settings.length or "Match original",
                          register_override=settings.register)

    total, issues = 0.0, None
    new = rv = None
    for attempt in range(max_review_retries + 1):
        new, cost = rewrite_section(section, page_title=page_title, register=register,
                                    options=opts, budget=budget, model=model, brand_voice=bv,
                                    extra_instructions=extra, review_issues=issues,
                                    template_key=t.key, client=client)
        total += cost
        kwargs = dict(output_kind="snippet", allowed_corpus=corpus,
                      request_summary=f"Regenerate one section of: {page_title}")
        try:
            rv = review([{"heading": new.heading, "body": new.body}], bv, use_critic=use_critic,
                        budget=budget, model=model, client=client, **kwargs)
        except BudgetExceeded:
            rv = review([{"heading": new.heading, "body": new.body}], bv, use_critic=False, **kwargs)
        total += rv.cost_usd
        if rv.passes or attempt == max_review_retries:
            break
        issues = rv.blocking()
    return new, rv, total


def _variant(t, brief, s, bv, facts, extracted, corpus, *, differ_from, max_review_retries,
             use_critic, budget, model, client) -> Variant:
    issues: list[str] | None = None
    total = 0.0
    v = rv = None
    for attempt in range(max_review_retries + 1):
        v, cost = _draft(t, brief, s, bv, facts, extracted, differ_from=differ_from,
                         issues=issues, budget=budget, model=model, client=client)
        total += cost
        rv = review_variant(v, t, s, bv, corpus, budget=budget, model=model, client=client,
                            use_critic=use_critic, extracted=extracted)
        total += rv.cost_usd
        v.attempts = attempt + 1
        if rv.passes or attempt == max_review_retries:
            break
        issues = rv.blocking()
    v.review = rv
    v.cost_usd = total
    if v.page is not None:
        v.page.review = rv.to_dict()
        v.page.cost_usd = total
    if v.composed is not None:
        v.composed.review = rv.to_dict()
        v.composed.cost_usd = total
    return v
