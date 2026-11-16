"""Compose mode: one free-form prompt -> a full page of typed blocks (hero,
text, image, quote, stat, links, CTA), instead of the fixed brief fields the
other templates use.

Same brand voice, same review, same redraft loop as every other template --
what's different is only the shape of the request and the shape of the
output. Anything invented to fill out the request (a placeholder quote, an
illustrative figure, a link target, an image) is never presented as real:
every such block is marked `is_placeholder` with a `placeholder_note`
explaining what it stands in for, and stays visibly labeled all the way
through rendering and export. Whether placeholders are allowed at all is
`VoiceSettings.strictness` ("mockup" vs "publish-ready") -- see review.py.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import templates as tpl
from .brand_voice import brand_name
from .models import BLOCK_TYPES, Block, ComposedPage, ExtractedContent, SectionLink, VoiceSettings
from .prompting import facts_block, plain_text, settings_block, system_prompt, uta_context
from .review import ReviewResult, review
from ..llm_cost import Budget, BudgetExceeded

MAX_OUTPUT_TOKENS = 8192

_BLOCK_GLOSSARY = (
    "Block types, and what belongs in each:\n"
    "- hero: the page opener. heading + subheading; body optional (a short lead-in).\n"
    "- heading: a section break with no body of its own -- a divider with a title.\n"
    "- text: a normal paragraph or two in body ('- ' lines for a bulleted list). heading optional.\n"
    "- image: a placed image slot, same as the images a designer would mark on a layout before "
    "sourcing them -- write image_alt (required: a concrete, specific description of the scene, "
    "as if briefing a photographer) and image_caption (optional). No file is generated, but the "
    "block itself is not optional: if the request asks for N images, write N separate type=image "
    "blocks with distinct image_alt text, positioned where each one belongs in the page (near the "
    "section it illustrates, not bunched at the end) -- this is exactly as required as hitting a "
    "requested link or CTA count, never something to skip because there's no real photo behind it.\n"
    "- quote: quote_text and quote_attribution (name and role/title).\n"
    "- stat: stat_value (e.g. \"40,000+\") and stat_label (e.g. \"Total enrollment\"). Write 2 or "
    "more stat blocks back to back when the request wants figures -- they render as one band.\n"
    "- links: a list of related links, each an entry in `links` (text + url). This is the block "
    "for \"N links\" -- put all of them in one links block's `links` array (or split across a "
    "few, e.g. grouped by topic), not folded into CTA buttons or mentioned only in body text.\n"
    "- cta: a single call-to-action button -- heading is the button label, `links` holds its one "
    "target (mark it isButton true). Use this only for the 1-2 primary actions the request calls "
    "out as buttons, not for a general list of links.\n"
    "- divider: a plain visual break; no other fields.\n\n"
    "is_placeholder: set it true only for content that is illustrative and must be swapped for "
    "something real before publishing -- an invented testimonial and its attribution, a stand-in "
    "URL, a figure you could not source. Facts from the verified list, the brief, the source, or "
    "things you know to be true about the subject are NOT placeholders: write them confidently "
    "with is_placeholder false. Always write the block out in full -- a placeholder is still "
    "finished, natural-sounding copy, never an empty slot or a bracketed marker like"
    "[enrollment figure].")


def _topic_grounding_note(bv: dict[str, Any]) -> str:
    name = brand_name(bv)
    return (
        f"This page's subject is whatever the REQUEST and any source material describe -- that "
        f"may be {name} itself or something it publishes or hosts. Keep every block on that "
        f"subject, and make each block add something the others do not.")


_PUBLISH_READY_NOTE = (
    "\n\nThis page is being prepared to publish, not a mockup: do not write any block that would "
    "need is_placeholder true. Where the request calls for a quote, stat, link or image you have "
    "no real source for, either omit that block or write a text block noting what still needs to "
    "be supplied -- never invent a stand-in.")


def _all_required(schema: dict) -> None:
    """Advertise every field as required in the JSON schema sent to the model.
    Claude rejects a structured-output schema with too many optional fields
    ("Schema is too complex"); the block schema alone has a dozen. Python-side
    defaults stay, so code and tests can still build these models partially."""
    schema["required"] = list(schema.get("properties", {}))


class ComposedLinkOutput(BaseModel):
    model_config = ConfigDict(json_schema_extra=_all_required)
    text: str
    url: str
    is_button: bool = False


class ComposedBlockOutput(BaseModel):
    model_config = ConfigDict(json_schema_extra=_all_required)
    type: str = Field(description="One of: hero, heading, text, image, quote, stat, links, cta, divider.")
    heading: str = ""
    subheading: str = ""
    body: str = Field(default="", description="Plain text; '- ' lines for a bulleted list.")
    image_alt: str = ""
    image_caption: str = ""
    quote_text: str = ""
    quote_attribution: str = ""
    stat_value: str = ""
    stat_label: str = ""
    links: list[ComposedLinkOutput] = Field(default_factory=list)
    is_placeholder: bool = Field(
        description="True if this block's specific content is illustrative rather than sourced "
                    "from the brief, the source material or the verified facts.")
    placeholder_note: str = Field(
        default="", description="Required when is_placeholder is true: what's illustrative and "
                                "what a real one should replace it with.")


class ComposedPageOutput(BaseModel):
    model_config = ConfigDict(json_schema_extra=_all_required)
    title: str
    subtitle: str = ""
    # Named content_register, not register: BaseModel inherits from ABCMeta,
    # whose own register() classmethod a field named plain "register" warns
    # about shadowing (same fix as RewritePageOutput in rewrite.py).
    content_register: str = Field(description="The register key you wrote in, e.g. 'institutional'.")
    # Declared -- and therefore generated -- BEFORE `blocks`. Structured
    # output is produced in field order, so a planning field placed after
    # the blocks it's meant to plan is too late to do anything: the model
    # has already committed to the block sequence by the time it writes it.
    # Putting the plan first makes it a real scratchpad the block generation
    # can build on, the same role a few sentences of chain-of-thought play
    # for a free-form draft -- which matters most on a small model, since a
    # larger one can plan implicitly without ever writing it down.
    page_plan: str = Field(
        default="",
        description="Write this FIRST, before any block: 2-4 sentences planning the page's "
                    "narrative arc and the ordered sequence of block types you are about to "
                    "write, and why (e.g. 'hero opens on the compliance risk, a text block "
                    "explains the program, two image blocks illustrate X and Y, a quote gives "
                    "social proof, a stat band backs it with figures, closing CTA restates the "
                    "ask'). If the request states specific counts (\"4 images\", \"8 links\", "
                    "\"2 CTAs\"), name every one of them in this plan by position -- a count "
                    "missing from the plan will be missing from the blocks below, since this is "
                    "the outline you are about to write to, not a summary of it afterward.")
    blocks: list[ComposedBlockOutput]
    brand_notes: list[str] = Field(
        default_factory=list,
        description="2-4 short notes: which voice attributes you applied, and how what you "
                    "actually wrote differed from the page_plan above, if it did.")


def compose_prompt(prompt: str, t: tpl.ContentTemplate, s: VoiceSettings, bv: dict[str, Any],
                   facts: list[dict[str, Any]], extracted: ExtractedContent | None, *,
                   differ_from: list[str], issues: list[str] | None) -> str:
    from .generate import _source_block, source_text  # local import: generate.py imports this module

    parts = [f"Content type: {t.label} -- {t.description}", _BLOCK_GLOSSARY]
    if t.instructions:
        parts.append(f"Instructions: {t.instructions}")
    length = next((p for p in t.length_presets if p.label == (s.length or t.length_presets[0].label)),
                  t.length_presets[0])
    parts.append(
        f"Length: {length.instruction} This is a default scale, not a ceiling: if the request "
        "below names specific counts (e.g. \"4 images\", \"8 links\", \"2 CTA buttons\"), write "
        "that many of each even if the total block count runs well past this range -- an explicit "
        "count in the request always overrides the general guidance here.")
    parts.append(settings_block(bv, t, s))
    if ctx := uta_context(bv):
        parts.append(ctx)
    parts.append(_topic_grounding_note(bv))
    if s.strictness == "publish-ready":
        parts.append(_PUBLISH_READY_NOTE.strip())
    parts.append(f"REQUEST:\n{prompt.strip()}")
    for block in (facts_block(facts), _source_block(extracted)):
        if block:
            parts.append(block)
    if differ_from:
        parts.append("Earlier variants opened like this -- take a clearly different angle and "
                     "block sequence:\n" + "\n".join(f"- {o}" for o in differ_from))
    if issues:
        parts.append("A prior draft failed review for these reasons -- fix them specifically:\n"
                     + "\n".join(f"- {i}" for i in issues))
    return "\n\n".join(parts)


_WRAPPING_QUOTES = "\"'‘’“”"


def _strip_quote_marks(text: str) -> str:
    """Every quote block is rendered inside its own curly quote marks (see
    BlockCard, and the html/docx/text exporters) -- if the model's own
    quote_text already came wrapped in quotes, the result would double up
    to `""like this""`. Strip one matching wrapping pair, if present."""
    text = text.strip()
    if len(text) >= 2 and text[0] in _WRAPPING_QUOTES and text[-1] in _WRAPPING_QUOTES:
        return text[1:-1].strip()
    return text


def _strip_leading_dash(text: str) -> str:
    """Attribution is rendered as — {text} -- strip a dash the model
    already included so it does not double up."""
    return text.strip().lstrip("—-–").strip()


def _to_block(b: ComposedBlockOutput) -> Block:
    return Block(
        type=b.type.strip().lower() if b.type.strip().lower() in BLOCK_TYPES else "text",
        heading=plain_text(b.heading) or "", subheading=plain_text(b.subheading) or "",
        body=(plain_text(b.body) or "").strip(), image_alt=plain_text(b.image_alt) or "",
        image_caption=plain_text(b.image_caption) or "",
        quote_text=_strip_quote_marks(plain_text(b.quote_text) or ""),
        quote_attribution=_strip_leading_dash(plain_text(b.quote_attribution) or ""), stat_value=b.stat_value,
        stat_label=plain_text(b.stat_label) or "",
        links=[SectionLink(text=plain_text(link.text) or "", url=link.url.strip(),
                           is_button=link.is_button) for link in b.links],
        is_placeholder=b.is_placeholder, placeholder_note=(plain_text(b.placeholder_note) or "").strip(),
    )


def draft_compose(prompt: str, s: VoiceSettings, *, bv: dict[str, Any],
                  facts: list[dict[str, Any]], extracted: ExtractedContent | None = None,
                  differ_from: list[str] | None = None, issues: list[str] | None = None,
                  budget: Budget | None = None, model: str | None = None,
                  client=None) -> tuple[ComposedPage, float]:
    from .rewrite import _call, _default_model

    t = tpl.get("compose-page")
    model = model or _default_model()
    text = compose_prompt(prompt, t, s, bv, facts, extracted, differ_from=differ_from or [],
                          issues=issues)
    parsed, cost = _call(model, system_prompt(bv, t.key), text, ComposedPageOutput,
                         budget or Budget(), client=client, max_output_tokens=MAX_OUTPUT_TOKENS)
    page = ComposedPage(title=plain_text(parsed.title) or "", subtitle=plain_text(parsed.subtitle) or "",
                        register=parsed.content_register, page_plan=plain_text(parsed.page_plan) or "",
                        blocks=[_to_block(b) for b in parsed.blocks],
                        brand_notes=list(parsed.brand_notes), cost_usd=cost)
    return page, cost


def units_from_blocks(blocks: list[Block]) -> list[dict[str, Any]]:
    """One review unit per block -- `body` concatenates every text field a
    block might carry, so the existing text-based checks (banned terms,
    generic phrasing, figures, names) see everything regardless of type.
    `placeholder` marks which units review.py should exempt from the
    fact-sourcing checks."""
    out = []
    for b in blocks:
        text = "\n".join(x for x in (
            b.subheading, b.body, b.image_alt, b.image_caption,
            f'"{b.quote_text}" — {b.quote_attribution}' if b.quote_text else "",
            f"{b.stat_value} {b.stat_label}" if b.stat_value or b.stat_label else "",
            "\n".join(f"{link.text} {link.url}" for link in b.links),
        ) if x)
        out.append({"heading": b.heading or None, "body": text, "placeholder": b.is_placeholder,
                    "placeholder_note": b.placeholder_note, "type": b.type,
                    "image_alt": b.image_alt})
    return out


def opening_text(page: ComposedPage) -> str:
    for b in page.blocks:
        text = b.heading or b.body or b.quote_text
        if text:
            return text[:160]
    return ""


def regenerate_block(block: Block, *, index: int, page_title: str, all_blocks: list[Block],
                     prompt: str, settings: VoiceSettings, budget: Budget | None = None,
                     model: str | None = None, brand_voice: dict[str, Any] | None = None,
                     knowledge_base: list[dict[str, Any]] | None = None,
                     max_review_retries: int = 0, use_critic: bool = True,
                     client=None) -> tuple[Block, ReviewResult, float]:
    """Redraft one block with the rest of the page as context, so a
    regenerated stat doesn't duplicate a neighbor. Reviewed like any other
    draft, with the block's own placeholder status exempting it from the
    fact-sourcing checks only when it stays marked."""
    from .brand_voice import load_brand_voice, load_knowledge_base
    from .rewrite import _call, _default_model

    budget = budget or Budget()
    bv = brand_voice or load_brand_voice()
    facts = (knowledge_base if knowledge_base is not None else load_knowledge_base()) \
        if settings.use_knowledge_base else []
    t = tpl.get("compose-page")
    context = "\n".join(f"[{i}] {b.type}: {b.heading or b.body or b.quote_text or b.stat_value}"
                        for i, b in enumerate(all_blocks) if i != index)
    corpus = "\n".join([prompt, block.body, block.heading] + [f["fact"] for f in facts])

    model = model or _default_model()
    total, issues = 0.0, None
    new = rv = None
    for attempt in range(max_review_retries + 1):
        text = "\n\n".join(p for p in (
            f"Content type: {t.label}", _BLOCK_GLOSSARY, settings_block(bv, t, settings),
            _topic_grounding_note(bv),
            f"PAGE TITLE: {page_title}",
            f"ORIGINAL PAGE REQUEST (for topic/subject context):\n{prompt.strip()}" if prompt.strip() else "",
            f"OTHER BLOCKS ON THIS PAGE (for context -- do not repeat them):\n{context}",
            facts_block(facts),
            f"Regenerate this one block (currently type={block.type}):\n"
            f"heading={block.heading!r} body={block.body!r}",
            (f"A prior attempt failed review -- fix these:\n" + "\n".join(f"- {i}" for i in issues))
            if issues else "",
        ) if p)
        parsed, cost = _call(model, system_prompt(bv, t.key), text, ComposedBlockOutput, budget,
                             client=client, max_output_tokens=MAX_OUTPUT_TOKENS)
        total += cost
        new = _to_block(parsed)
        units = units_from_blocks([new])
        kwargs = dict(output_kind="blocks", allowed_corpus=corpus, strictness=settings.strictness,
                      request_summary=f"Regenerate one block of: {page_title}")
        try:
            rv = review(units, bv, use_critic=use_critic, budget=budget, model=model,
                        client=client, **kwargs)
        except BudgetExceeded:
            rv = review(units, bv, use_critic=False, **kwargs)
        total += rv.cost_usd
        if rv.passes or attempt == max_review_retries:
            break
        issues = rv.blocking()
    return new, rv, total
