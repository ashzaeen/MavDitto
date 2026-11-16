"""Orchestrates Content Writer end to end: extract -> rewrite -> guardrail
-> StructuredContent. The one entry point the server route calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import extraction
from .models import ExtractedContent, RewriteOptions, Section, StructuredContent
from .review import ReviewResult, review, units_from_sections
from .rewrite import load_brand_voice, rewrite_page
from ..llm_cost import Budget

MAX_GUARDRAIL_RETRIES = 2

INPUT_KINDS = ("url", "pdf", "docx", "pptx", "xlsx", "markdown", "image")


@dataclass
class ContentInput:
    """A tagged union of everything Content Writer (and the setup engine)
    can extract from -- one shape, whichever kind of input arrived."""

    kind: str                          # one of INPUT_KINDS
    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None      # image only


def extract_content(input_: ContentInput, *, fetcher=None,
                    budget: Budget | None = None) -> ExtractedContent:
    if input_.kind == "url":
        if not input_.url:
            raise ValueError("a url is required for kind='url'")
        return extraction.extract_from_url(input_.url, fetcher)
    if input_.kind == "pdf":
        return extraction.extract_from_pdf(input_.data)
    if input_.kind == "docx":
        return extraction.extract_from_docx(input_.data)
    if input_.kind == "pptx":
        return extraction.extract_from_pptx(input_.data)
    if input_.kind == "xlsx":
        return extraction.extract_from_xlsx(input_.data)
    if input_.kind == "markdown":
        return extraction.extract_from_markdown(input_.data.decode("utf-8"))
    if input_.kind == "image":
        outcome = extraction.extract_from_image(input_.data, input_.media_type, budget=budget)
        if outcome.extracted is None:
            raise RuntimeError(outcome.skipped_reason)
        return outcome.extracted
    raise ValueError(f"unknown input kind: {input_.kind!r}; expected one of {INPUT_KINDS}")


def review_check(content: StructuredContent, brand_voice: dict, *, budget=None,
                 model=None, corpus: str = "", reading_level: str = "") -> ReviewResult:
    """The review write_page runs after every draft: the deterministic rules
    plus the vendored-method critic (see review.py)."""
    return review(units_from_sections(content.sections), brand_voice, output_kind="page",
                  allowed_corpus=corpus, reading_level=reading_level,
                  request_summary="Rewrite an existing page into the brand voice",
                  budget=budget, model=model)


# The name write_page calls through -- tests swap it at this module boundary.
guardrail_check = review_check


def write_page(input_: ContentInput, options: RewriteOptions, *, fetcher=None,
              budget: Budget | None = None, model: str | None = None,
              brand_voice: dict | None = None,
              max_guardrail_retries: int = MAX_GUARDRAIL_RETRIES) -> StructuredContent:
    """Extract, rewrite, review; redraft against the review's blocking issues
    up to `max_guardrail_retries` times. The final draft is always reviewed
    and its review returned with it -- the last retry never ships unchecked --
    and cost_usd is the total across every draft and every review."""
    budget = budget or Budget()
    brand_voice = brand_voice or load_brand_voice()

    extracted = extract_content(input_, fetcher=fetcher, budget=budget)
    corpus = "\n".join([extracted.page_title] +
                       [f"{s.heading or ''}\n{s.body}" for s in extracted.sections])
    structured = rewrite_page(extracted, options, budget=budget, model=model,
                              brand_voice=brand_voice)
    total = structured.cost_usd

    for attempt in range(max_guardrail_retries + 1):
        result = guardrail_check(structured, brand_voice, budget=budget, model=model,
                                 corpus=corpus)
        total += float(getattr(result, "cost_usd", 0.0) or 0.0)
        if result.passes or attempt == max_guardrail_retries:
            break
        issues = [str(i) for i in result.issues if getattr(i, "severity", "critical") == "critical"]
        structured = rewrite_page(extracted, options, budget=budget, model=model,
                                  brand_voice=brand_voice, guardrail_issues=issues)
        total += structured.cost_usd

    structured.cost_usd = total
    if isinstance(result, ReviewResult):
        structured.review = result.to_dict()
    return structured
