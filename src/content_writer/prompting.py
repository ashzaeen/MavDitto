"""Builds the prompts every Content Writer path shares -- rewrite, generate,
refine, and regenerate-section all speak with one system prompt, so the
brand voice cannot drift between them.

System prompt (stable per brand + content type, so provider-side prompt
caching applies across a whole session):
  the vendored voice method -> We Are / We Are Not -> registers -> shared
  principles -> terminology -> this content type's before/after examples ->
  open questions -> the floor -> the procedure and anti-generic rules.

User prompt: the request itself -- template instructions, brief, settings,
verified facts, source material.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import templates as tpl
from . import voice_method
from .brand_voice import (
    DIALS, brand_full_name, brand_name, dials_for, is_uta, register_keys,
)
from .models import GOALS, POINTS_OF_VIEW, VoiceSettings

GENERIC_AI_TELLS = (
    "discover a world of", "unlock your potential", "in today's fast-paced world",
    "look no further", "endless possibilities", "take your", "to the next level",
    "whether you're a", "embark on a journey", "dive into",
    # Invented-significance filler: says nothing the brief said.
    "broader efforts", "commitment to supporting", "a testament to", "plays a vital role",
    "vibrant community", "rich tapestry",
)


def plain_text(text: str | None) -> str | None:
    """Drop Markdown emphasis and heading marks a model adds despite being
    told the output is plain text ("**Instructor:** Dr. Rivas"). Bullets
    ("- item") are kept -- they are the plain-text list convention here."""
    if text is None:
        return None
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)
    return re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)


def register_block(bv: dict[str, Any]) -> str:
    lines = []
    for key, r in bv.get("registers", {}).items():
        lines.append(
            f"- {r.get('label', key)} [key: {key.replace('_', '-')}] (used for "
            f"{', '.join(r.get('used_for', []))}): {r.get('description', '')} "
            f"Example: \"{r.get('example', '')}\"")
    return "\n".join(lines)


def _we_are_block(bv: dict[str, Any]) -> str:
    rows = bv.get("we_are") or []
    if not rows:
        return ""
    return "\n".join(f"- WE ARE {r.get('we_are', '')} | WE ARE NOT {r.get('we_are_not', '')}"
                     for r in rows)


def _terminology_block(bv: dict[str, Any]) -> str:
    t = bv.get("terminology") or {}
    out = []
    for p in t.get("preferred", []):
        note = f" ({p['note']})" if p.get("note") else ""
        out.append(f"- Write \"{p.get('use', '')}\", not \"{p.get('instead_of', '')}\"{note}")
    if t.get("banned"):
        out.append("- Never use: " + ", ".join(f'"{b}"' for b in t["banned"]))
    if t.get("needs_source"):
        out.append("- Only when the brief, source or verified facts say it too: "
                   + ", ".join(f'"{b}"' for b in t["needs_source"]))
    out.extend(f"- {r}" for r in t.get("style_rules", []))
    return "\n".join(out)


def _examples_block(bv: dict[str, Any], template_key: str | None) -> str:
    examples = bv.get("examples") or []
    matched = [e for e in examples if e.get("template_key") == template_key]
    if not matched:
        # A free-form page (compose-page) can be about anything the request
        # and source describe -- often not the brand's own admissions/news
        # voice the generic examples below are drawn from. Falling back to
        # them here calibrated every compose page toward "Apply now" /
        # "Discover a world of opportunities" diction regardless of topic,
        # which is worse than no examples at all.
        template = tpl.BY_KEY.get(template_key) if template_key else None
        if template is not None and template.output_kind == "blocks":
            return ""
        matched = examples[:2]
    return "\n\n".join(
        f"Before: {e.get('before', '')}\nAfter: {e.get('after', '')}\nWhy: {e.get('why', '')}"
        for e in matched)


def _titled(title: str, body: str) -> str:
    return f"== {title} ==" + chr(10) + body


def system_prompt(bv: dict[str, Any], template_key: str | None = None) -> str:
    """A lean system prompt: who is writing, the brand's own voice, and
    permission to write well. Deliberately NOT a rulebook -- the long
    procedure, before/after examples, floor and "only write facts you were
    given" rules this used to carry produced timid, repetitive copy. Facts and
    claims are checked after the fact by the advisory review, not by
    constraining the draft."""
    name, full = brand_name(bv), brand_full_name(bv)
    who = f"{full} ({name})" if full != name else name
    parts = [f"You are an expert web copywriter and content designer writing for {who}. "
             "Write the strongest, most useful copy you can for the request."]
    if block := _we_are_block(bv):
        parts.append(_titled(f"The {name} voice", block))
    if block := register_block(bv):
        parts.append(_titled("Registers (pick the one that fits)", block))
    if bv.get("shared_principles"):
        parts.append(_titled("Principles", chr(10).join(f"- {p}" for p in bv["shared_principles"])))
    if block := _terminology_block(bv):
        parts.append(_titled("House style", block))
    parts.append(_titled("How to work", (
        f"Use your own knowledge of {name} freely -- its history, campus, programs, research, "
        "student life, region and reputation -- alongside any brief, verified facts and source "
        "material you are given. Prefer the supplied facts for exact figures, rankings and dates, "
        "and quote them as written. Be specific and concrete; vary your structure and wording, "
        "and never repeat the same fact or sentence in two places. If you include a specific "
        "figure, quote or name you are not confident is accurate, say so in brand_notes so a "
        "reviewer can check it -- but do write the copy; do not leave a gap or a generic stand-in. "
        "Where a request conflicts with these guidelines, use your judgment and note the tradeoff "
        "in brand_notes.")))
    return (chr(10) * 2).join(parts)


def _audience(bv: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((a for a in bv.get("audiences", []) if a.get("key") == key), None)


def _dial_line(bv: dict[str, Any], dials: dict[str, int]) -> str:
    dims = bv.get("tone_dimensions", {})
    out = []
    for d in DIALS:
        level = str(dials[d])
        info = dims.get(d, {})
        out.append(f"{info.get('label', d)} {level}/5 ({info.get('levels', {}).get(level, '')})")
    return "; ".join(out)


def settings_block(bv: dict[str, Any], template: tpl.ContentTemplate, s: VoiceSettings) -> str:
    """The request's voice settings, in plain instructions."""
    # Without today's date a model writes "has opened" about next week's event.
    lines = [f"Today's date is {date.today():%B %d, %Y}. Use tense accordingly: events after "
             "today are upcoming. Output plain text: write any URL as-is, never Markdown link "
             "syntax."]
    dials = {**dials_for(bv, template.key), **{k: v for k, v in s.dials.items() if k in DIALS}}
    lines.append(f"Tone dials: {_dial_line(bv, dials)}.")
    note = (bv.get("tone_by_context", {}).get(template.key) or {}).get("note")
    if note:
        lines.append(f"Guidance for this content type: {note}")
    if s.tone:
        lines.append(f"Tone adjustments requested: {', '.join(s.tone)}.")

    audience = _audience(bv, s.audience or template.default_audience)
    if audience:
        lines.append(f"Audience: {audience.get('label')} -- {audience.get('description', '')}")
    reading = s.reading_level or (audience or {}).get("reading_level", "")
    if reading:
        lines.append(f"Target reading level: {reading}.")
    if s.goal:
        lines.append(f"Goal: {GOALS[s.goal]}.")

    keys = register_keys(bv)
    register = s.register or (audience or {}).get("default_register")
    if s.register:
        lines.append(f"Write in the {s.register} register -- the writer chose it explicitly.")
    elif register and register in keys:
        lines.append(f"Default to the {register} register for this audience unless the content "
                     "is clearly institutional/policy material.")
    elif keys:
        lines.append(f"Detect which register ({', '.join(keys)}) this content calls for, and "
                     "write in that register.")
    if s.point_of_view:
        lines.append(f"Point of view: {POINTS_OF_VIEW[s.point_of_view]}.")
    if s.language != "English":
        lines.append(f"Write the copy in {s.language}. Keep proper names, program names and "
                     f"{brand_name(bv)}'s name untranslated.")
    if s.keywords:
        lines.append("Work these search keywords in naturally, never stuffed: "
                     + ", ".join(s.keywords) + ".")
    if s.cta:
        lines.append(f"Call to action to use: {s.cta}")
    if s.must_include:
        lines.append("Must include: " + "; ".join(s.must_include) + ".")
    if s.avoid:
        lines.append("Avoid: " + "; ".join(s.avoid) + ".")
    return "\n".join(lines)


_STOP = frozenset("""about above after again also among and another any are around because been
before being below between both but can could does doing during each even every from further
have having here into more most much must near need only other ours over same should since some
such than that their them then there these they this those through under until upon very were
what when where which while whom whose will with within without would your yours page pages
student students university""".split())


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if w not in _STOP}


def relevant_facts(facts: list[dict[str, Any]], request_text: str, template_key: str,
                   bv: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The knowledge-base facts worth offering the writer for this request.

    Offering every fact invites padding -- a library news story came back
    with enrollment and country counts bolted on. So a fact is offered only
    when it shares a meaningful word with the brief/source, plus the
    boilerplate for a press release. Every fact stays *allowed* regardless:
    the figure check still accepts any of them.
    """
    brand_words = _stems(" ".join([brand_name(bv or {}), brand_full_name(bv or {})])) if bv else set()
    want = _stems(request_text) - brand_words
    out = []
    for f in facts:
        tags = [str(t).lower() for t in f.get("tags", [])]
        if template_key == "press-release" and "boilerplate" in tags:
            out.append(f)
            continue
        have = _stems(" ".join([f.get("title", ""), f.get("fact", ""), " ".join(tags)])) - brand_words
        if want & have:
            out.append(f)
    return out


def facts_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""
    return ("Verified facts on file -- accurate, sourced figures, rankings and designations you "
            "can draw on freely. Use the ones that strengthen this piece; keep a fact's wording "
            "and its timeframe (e.g. \"in fall 2024\"), never restate an "
            "old figure as current:\n"
            + "\n".join(f"- {f['fact']}" for f in facts))


def uta_context(bv: dict[str, Any]) -> str:
    """Framing only for UTA's own deployment -- a fork never sees it."""
    if not is_uta(bv):
        return ""
    return ("This copy is published on uta.edu, the website of The University of Texas at "
            "Arlington in the Dallas-Fort Worth Metroplex. Mention UTA-specific places, programs "
            "and people by name freely where you know them to be real and accurate.")
