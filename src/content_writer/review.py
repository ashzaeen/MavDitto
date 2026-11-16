"""Quality review of a draft: deterministic checks that cost nothing, then an
LLM critic following the vendored quality-assurance method.

The deterministic half catches what a model is unreliable at noticing in its
own output -- a banned word, a 170-character meta description, a statistic
that appears nowhere in what it was given. The critic judges what rules
cannot: voice, tone fit, and the name-swap test for generic filler.

`passes` means no *critical* issue from either half; suggestions never
block, they are shown to the writer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from . import voice_method
from .brand_voice import brand_full_name, brand_name
from .prompting import GENERIC_AI_TELLS
from ..llm_cost import Budget

MAX_OUTPUT_TOKENS = 3072

CRITICAL, SUGGESTED = "critical", "suggested"

_GRADE = {"grade 8": 8, "grade 9": 9, "grade 10": 10, "grade 12": 12, "college": 14}


@dataclass
class ReviewIssue:
    severity: str                  # critical | suggested
    message: str
    section: int | None = None     # index into sections/items, None = whole draft
    quote: str = ""
    fix: str = ""
    source: str = "rule"           # rule | critic

    def __str__(self) -> str:
        where = f"Section {self.section}: " if self.section is not None else ""
        quote = f' ("{self.quote}")' if self.quote else ""
        fix = f" Fix: {self.fix}" if self.fix else ""
        return f"{where}{self.message}{quote}.{fix}"


@dataclass
class ReviewResult:
    passes: bool
    issues: list[ReviewIssue] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    open_questions: list[dict[str, str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passes": self.passes,
            "issues": [asdict(i) for i in self.issues],
            "scores": dict(self.scores),
            "openQuestions": list(self.open_questions),
            "metrics": dict(self.metrics),
            "costUsd": round(self.cost_usd, 6),
        }

    def blocking(self) -> list[str]:
        return [str(i) for i in self.issues if i.severity == CRITICAL]


# --------------------------------------------------------------------------
# text metrics
# --------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _syllables(word: str) -> int:
    w = word.lower().strip("'")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p for p in (s.strip() for s in parts) if _WORD.search(p)]


def text_metrics(text: str) -> dict[str, Any]:
    words = _WORD.findall(text)
    sentences = _sentences(text)
    if not words or not sentences:
        return {"words": len(words), "sentences": len(sentences), "fk_grade": 0.0,
                "avg_sentence_words": 0.0}
    syl = sum(_syllables(w) for w in words)
    wps = len(words) / len(sentences)
    fk = 0.39 * wps + 11.8 * (syl / len(words)) - 15.59
    return {"words": len(words), "sentences": len(sentences),
            "fk_grade": round(max(0.0, fk), 1), "avg_sentence_words": round(wps, 1)}


# --------------------------------------------------------------------------
# figures: anything that reads like a statistic must come from somewhere
# --------------------------------------------------------------------------

_FIGURE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|thousand|[MBK]))?"
    r"|\d[\d,]*(?:\.\d+)?\s?(?:%|percent)"
    r"|No\.\s?\d+"
    r"|\b\d{1,3}(?:,\d{3})+\b"
    r"|\b\d{3,}\b", re.IGNORECASE)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def _norm_figure(s: str) -> str:
    s = s.lower().replace("percent", "%").replace(",", "").replace(" ", "")
    return s


def unsourced_figures(text: str, allowed_corpus: str) -> list[str]:
    corpus = _norm_figure(allowed_corpus)
    found = []
    for m in _FIGURE.finditer(text):
        fig = m.group(0).strip()
        if _YEAR.match(fig):
            continue
        n = _norm_figure(fig)
        # "41,613 students" is fine if "41613" is anywhere in what we were given
        digits = re.sub(r"[^\d.]", "", n)
        if n in corpus or (digits and digits in re.sub(r"[^\d.]", " ", corpus).split()):
            continue
        if fig not in found:
            found.append(fig)
    return found


# --------------------------------------------------------------------------
# invented significance, unsourced names, AP dates
# --------------------------------------------------------------------------

_POSS = r"(?:(?:the|our|its|their)\s)?(?:[A-Z][\w.]*(?:'s|’s)\s)?"
_FILLER = re.compile(
    r"\b(?:reflects|underscores|demonstrates|highlights|showcases|reinforces)\s+" + _POSS
    + r"(?:ongoing\s|continued\s|deep\s|strong\s)?(?:commitment|dedication)\b"
    r"|\bpart\s+of\s+" + _POSS + r"(?:broader|larger|ongoing|wider)\s+(?:effort|efforts|initiative|mission|strategy)\b",
    re.IGNORECASE)

# Two or more capitalized words in a row (allowing "of"/"and"/"for"/"at"
# inside), or a capitalized word followed by an all-caps token like "ID".
_NAME = re.compile(
    r"\b[A-Z][a-z]+(?:(?:\s+(?:of|and|for|at|the))?\s+(?:[A-Z][a-z]+|[A-Z]{2,}))+\b")
_MONTH = re.compile(r"\b(January|February|August|September|October|November|December)\s+\d{1,2}\b")
_SEASON = re.compile(r"(?<![.!?]\s)(?<!^)\b(Fall|Spring|Summer|Winter)\s+(?:19|20)\d{2}\b")
_AP_MONTH = {"January": "Jan.", "February": "Feb.", "August": "Aug.", "September": "Sept.",
             "October": "Oct.", "November": "Nov.", "December": "Dec."}


_COMMITMENT = re.compile(r"\b(?:commitment|dedication|committed|dedicated)\s+to\s+\w+(?:ing)?\b",
                         re.IGNORECASE)


def invented_significance(text: str, corpus: str) -> list[str]:
    """A claimed motive or commitment is always a claim -- and only the
    source can back it. Phrasings vary endlessly ("reinforces", "is
    indicative of", "speaks to"), so every "committed/dedicated to X" counts
    unless the source makes that same claim. Matched per claim, not per word:
    a boilerplate "dedicated to the advancement of knowledge" must not
    license "dedicated to supporting your success"."""
    low = corpus.lower()
    found = [m.group(0) for m in _FILLER.finditer(text) if m.group(0).lower() not in low]
    for m in _COMMITMENT.finditer(text):
        claim = m.group(0)
        verb_object = claim.lower().split(" to ", 1)[-1]
        backed = re.search(r"\b(?:commit\w*|dedicat\w*)\s+to\s+" + re.escape(verb_object), low)
        if not backed and not any(claim.lower() in f.lower() or f.lower() in claim.lower() for f in found):
            found.append(claim)
    return found


def unsourced_names(text: str, corpus: str) -> list[str]:
    """Multi-word proper names in the draft that appear nowhere in what the
    writer was given -- an invented office, program, or a renamed ID."""
    # Whitespace-normalized: a PDF line break inside "Federal Student\nAid"
    # must not make a sourced name look invented.
    low = re.sub(r"\s+", " ", corpus.lower())
    corpus_words = set(re.findall(r"[a-z][a-z'-]+", low))
    out: list[str] = []
    for sentence in _sentences(text):
        for m in _NAME.finditer(sentence):
            # "The Central Library at The University of Texas at Arlington" is
            # two names joined by "at" -- each is checked on its own. "of"
            # stays inside a name (University of Texas).
            parts = re.split(r"\s+(?:at|and|for)\s+(?=[A-Z])", m.group(0))
            for n, name in enumerate(parts):
                words = name.split()
                # A sentence's first word is capitalized anyway -- "Visit
                # Central Library" names only "Central Library".
                if m.start() == 0 and n == 0:
                    words = words[1:]
                elif words[0] in ("The", "A", "An"):
                    words = words[1:]
                if len(words) < 2:
                    continue
                core = " ".join(words)
                if core.lower() in low or name.lower() in low or name in out:
                    continue
                # Every word of it is in the source ("Sachit Satyal" when the
                # source says "Satyal, Sachit"; a heading built from source
                # words): reworded, not invented.
                significant = [w.lower().strip("'") for w in words
                               if len(w) > 2 and w.lower() not in ("the", "and", "for")]
                if significant and all(w in corpus_words for w in significant):
                    continue
                out.append(name)
    return out


# --------------------------------------------------------------------------
# coverage: which concrete details from the source made it into the draft
# --------------------------------------------------------------------------

_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
     ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
     ("oct", "october"), ("nov", "november"), ("dec", "december")], start=1) for m in names}
_A_URL = re.compile(r"https?://[^\s)>\]\"']+", re.I)
_A_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_A_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_A_TIME_RANGE = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])?\.?\s*(?:m\.?)?\s*(?:-|–|to)\s*(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
_A_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
_A_DATE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True))
                     + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_A_ROOM = re.compile(r"\b[A-Z]{2,4}[\s-]?\d{3,4}[A-Z]?\b")
_A_QTY = re.compile(r"\b(\d+(?:\.\d+)?)[ \t]+(points?|credits?|credit hours?|hours?|minutes?|days?|"
                    r"weeks?|percent|seats?|rooms?|students?|courses?|exams?|assignments?)\b", re.I)


def _t24(h: str, m: str | None, ap: str) -> str:
    hour = int(h) % 12 + (12 if ap.lower() == "p" else 0)
    return f"{hour:02d}:{int(m or 0):02d}"


def anchors(text: str) -> dict[str, str]:
    """Concrete, checkable details -> {canonical form: first surface form}.
    Canonical forms survive reformatting: "4:00PM" and "4 p.m." are both
    time:16:00, "February 13" and "Feb. 13" both date:02-13. Each pattern
    masks what it matched so a phone number is not also three figures."""
    found: dict[str, str] = {}
    buf = text

    def take(pattern, canon):
        nonlocal buf
        for m in pattern.finditer(buf):
            for key in canon(m):
                found.setdefault(key, m.group(0).strip())
        buf = pattern.sub(lambda m: " " * len(m.group(0)), buf)

    take(_A_URL, lambda m: ["url:" + m.group(0).lower().split("://", 1)[1].rstrip("/.,;")])
    take(_A_EMAIL, lambda m: ["email:" + m.group(0).lower().rstrip(".")])
    take(_A_PHONE, lambda m: ["phone:" + re.sub(r"\D", "", m.group(0))])
    take(_A_TIME_RANGE, lambda m: ["time:" + _t24(m.group(1), m.group(2), m.group(3) or m.group(6)),
                                   "time:" + _t24(m.group(4), m.group(5), m.group(6))])
    take(_A_TIME, lambda m: ["time:" + _t24(m.group(1), m.group(2), m.group(3))])
    take(_A_DATE, lambda m: [f"date:{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"])
    take(_A_ROOM, lambda m: ["code:" + re.sub(r"[\s-]", "", m.group(0))])
    take(_A_QTY, lambda m: [f"qty:{m.group(1)} {m.group(2).lower().rstrip('s')}"])
    for m in _FIGURE.finditer(buf):
        fig = m.group(0).strip()
        if not _YEAR.match(fig):
            found.setdefault("fig:" + _norm_figure(fig), fig)
    return found


def dropped_details(draft: str, source: str) -> tuple[list[str], int]:
    """Source details missing from the draft (surface forms), and how many
    details the source had."""
    want = anchors(source)
    have = anchors(draft)
    missing = [surface for key, surface in want.items() if key not in have]
    return list(dict.fromkeys(missing)), len(want)


# --------------------------------------------------------------------------
# deterministic checks
# --------------------------------------------------------------------------

def _find_phrase(text: str, phrase: str) -> str | None:
    m = re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", text, re.IGNORECASE)
    return m.group(0) if m else None


def rule_checks(units: list[dict[str, Any]], bv: dict[str, Any], *,
                output_kind: str = "page", char_limit: int | None = None,
                keywords: list[str] | None = None, reading_level: str = "",
                allowed_corpus: str = "", ap_style: bool = False,
                source_text: str = "", coverage: str = "", strictness: str = "",
                ) -> tuple[list[ReviewIssue], dict[str, Any]]:
    """`coverage`: "required" (every source detail must appear -- critical
    if any is dropped), "report" (show what was dropped as a suggestion),
    or "" (don't check). `units` are the draft's sections ({heading, body}),
    items ({text}), or blocks ({heading, body, placeholder, placeholder_note,
    type, image_alt} -- see compose.units_from_blocks).

    A unit with `placeholder` true is exempt from the fact-sourcing checks
    (figures, names, invented significance, needs-source claims) -- that is
    the whole point of marking it a placeholder. It still has to clear the
    banned-terms/generic-phrasing/markdown-link checks (a placeholder quote
    should not use banned language either), and it must carry a non-empty
    `placeholder_note`, or -- in `strictness == "publish-ready"` -- must not
    exist at all.
    """
    issues: list[ReviewIssue] = []
    terms = bv.get("terminology", {})

    def text_of(u):
        return "\n".join(x for x in (u.get("heading"), u.get("body"), u.get("text")) if x)

    for i, u in enumerate(units):
        t = text_of(u)
        placeholder = bool(u.get("placeholder"))
        for banned in terms.get("banned", []):
            if hit := _find_phrase(t, banned):
                issues.append(ReviewIssue(CRITICAL, "Uses a banned term", i, hit,
                                          "Replace it with a specific, sourced fact or cut it."))
        if not placeholder:
            for claim in terms.get("needs_source", []):
                if (hit := _find_phrase(t, claim)) and not _find_phrase(allowed_corpus, claim):
                    issues.append(ReviewIssue(CRITICAL, "Superlative or claim with no source", i, hit,
                                              "Cut it, or cite the source that says so."))
        for tell in GENERIC_AI_TELLS:
            if hit := _find_phrase(t, tell):
                # Critical when the writer introduced it; a suggestion when
                # it is the source's own wording (a faithful rewrite echoing
                # it should not fail review for it).
                inherited = bool(_find_phrase(allowed_corpus, tell))
                issues.append(ReviewIssue(
                    SUGGESTED if inherited else CRITICAL,
                    "Generic phrasing (from the source)" if inherited else "Generic AI phrasing",
                    i, hit, "Say the specific thing instead."))
        for p in terms.get("preferred", []):
            wrong = p.get("instead_of", "")
            if wrong and (hit := _find_phrase(t, wrong)):
                issues.append(ReviewIssue(SUGGESTED, "Non-preferred term", i, hit,
                                          f"Write \"{p.get('use', '')}\"."))
        if char_limit and output_kind == "items":
            n = len(u.get("text", ""))
            if n > char_limit:
                issues.append(ReviewIssue(CRITICAL, f"{n} characters, over the {char_limit}-character limit",
                                          i, fix="Shorten it."))
        if not placeholder:
            for fig in unsourced_figures(t, allowed_corpus):
                issues.append(ReviewIssue(
                    CRITICAL, "Figure not found in the brief, the source or the verified facts",
                    i, fig, "Remove it, or add the fact (with its source) to the knowledge base."))
            for phrase in invented_significance(t, allowed_corpus):
                issues.append(ReviewIssue(
                    CRITICAL, "States a motive or significance nobody gave", i, phrase,
                    "Cut it, or say the specific thing the brief actually states."))
        body = u.get("body") or u.get("text") or ""
        for m in re.finditer(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", t):
            issues.append(ReviewIssue(
                CRITICAL, "Markdown link syntax in plain-text copy", i, m.group(0),
                f"Write the URL as-is ({m.group(2)}); link text is set where the page is built."))
        if output_kind != "items" and not (output_kind == "blocks" and placeholder):
            for name in unsourced_names(body, allowed_corpus):
                issues.append(ReviewIssue(
                    SUGGESTED, "Name not in the brief, the source or the verified facts", i, name,
                    "Check it is spelled exactly as the source spells it, or remove it."))
        if ap_style:
            for m in _MONTH.finditer(body):
                issues.append(ReviewIssue(SUGGESTED, "AP style abbreviates this month with a date", i,
                                          m.group(0), f"Write {_AP_MONTH[m.group(1)]} {m.group(0).split()[1]}."))
            for m in _SEASON.finditer(body):
                issues.append(ReviewIssue(SUGGESTED, "AP style lowercases seasons", i, m.group(0),
                                          f"Write {m.group(0).lower()}."))
        if output_kind == "blocks":
            if placeholder and not str(u.get("placeholder_note") or "").strip():
                issues.append(ReviewIssue(
                    CRITICAL, "Placeholder without an explanation of what it stands in for", i,
                    fix="Add a placeholder_note saying what a real one should replace it with."))
            if placeholder and strictness == "publish-ready":
                issues.append(ReviewIssue(
                    CRITICAL, "Placeholder content in publish-ready mode", i,
                    fix="Ground it in the brief, the source or the knowledge base, or omit this block."))
            if u.get("type") == "image" and not str(u.get("image_alt") or "").strip():
                issues.append(ReviewIssue(CRITICAL, "Image block has no alt text", i,
                                          fix="Add image_alt describing what the image shows."))

    all_text = "\n".join(text_of(u) for u in units)
    bodies = "\n".join(u.get("body") or u.get("text") or "" for u in units)
    metrics = text_metrics(bodies)
    if output_kind == "blocks":
        metrics["total_blocks"] = len(units)
        metrics["placeholder_blocks"] = sum(1 for u in units if u.get("placeholder"))

    # First reference: the full name before any short form, where the
    # profile defines both (UTA's house style; any fork with brand_full_name).
    short, full = brand_name(bv), brand_full_name(bv)
    if output_kind == "page" and full != short and short != "the organization":
        # Case-sensitive, with emails and URLs blanked out: "@uta.edu" is not
        # a first reference to UTA.
        prose = _A_EMAIL.sub(" ", _A_URL.sub(" ", bodies))
        m_short = re.search(r"(?<![\w-])" + re.escape(short) + r"(?![\w-])", prose)
        first_short = m_short.group(0) if m_short else None
        if first_short:
            i_short = m_short.start()
            i_full = prose.lower().find(full.lower())
            if i_full == -1 or i_full > i_short:
                issues.append(ReviewIssue(SUGGESTED, f"First reference uses \"{short}\"",
                                          quote=first_short,
                                          fix=f"Use \"{full}\" on first reference."))

    if coverage and source_text.strip():
        dropped, total = dropped_details(all_text, source_text)
        if total:
            metrics["source_details"] = total
            metrics["source_details_kept"] = total - len(dropped)
        if dropped:
            shown = ", ".join(dropped[:40]) + (f", and {len(dropped) - 40} more" if len(dropped) > 40 else "")
            issues.append(ReviewIssue(
                CRITICAL if coverage == "required" else SUGGESTED,
                f"{len(dropped)} of {total} details from the source are missing", quote=shown,
                fix="Add each one where it belongs." if coverage == "required"
                else "Expected at this length; choose \"Cover everything in the source\" to keep them."))

    for kw in keywords or []:
        if not _find_phrase(all_text, kw):
            issues.append(ReviewIssue(SUGGESTED, f"Keyword not used: {kw}"))
    metrics["keywords_used"] = sum(1 for kw in keywords or [] if _find_phrase(all_text, kw))

    target = _GRADE.get(reading_level)
    if target and output_kind == "page" and metrics["words"] >= 60:
        metrics["target_grade"] = target
        if metrics["fk_grade"] > target + 2:
            issues.append(ReviewIssue(
                SUGGESTED, f"Reads at grade {metrics['fk_grade']}, above the grade {target} target",
                fix="Shorter sentences and plainer words."))
    if output_kind == "page" and metrics["avg_sentence_words"] > 25:
        issues.append(ReviewIssue(SUGGESTED,
                                  f"Average sentence is {metrics['avg_sentence_words']} words long",
                                  fix="Split the longest sentences."))
    return issues, metrics


# --------------------------------------------------------------------------
# the critic
# --------------------------------------------------------------------------

class CriticIssue(BaseModel):
    severity: str = Field(description="critical (must fix) or suggested (should fix).")
    section: int | None = Field(default=None, description="Section/item number, or null for the whole draft.")
    quote: str = Field(default="", description="The exact words at fault.")
    problem: str = Field(description="What is wrong, citing the guideline it breaks.")
    fix: str = Field(default="", description="An actionable fix.")


class CriticOpenQuestion(BaseModel):
    question: str
    recommendation: str


class CriticOutput(BaseModel):
    voice_match: int = Field(description="1-5: reflects We Are, avoids We Are Not.")
    tone_fit: int = Field(description="1-5: formality, energy and technical depth fit the request.")
    clarity: int = Field(description="1-5: plain, scannable, easy to act on.")
    fact_fidelity: int = Field(description="1-5: every claim traceable to what the writer was given.")
    issues: list[CriticIssue] = Field(default_factory=list)
    open_questions: list[CriticOpenQuestion] = Field(
        default_factory=list,
        description="Brand decisions this draft surfaced that the guidelines do not settle, each "
                    "with your recommendation. Empty if none.")


def _critic_system(bv: dict[str, Any], *, strictness: str = "") -> str:
    rows = "\n".join(f"- WE ARE {r.get('we_are', '')} | WE ARE NOT {r.get('we_are_not', '')}"
                     for r in bv.get("we_are", []))
    terms = bv.get("terminology", {})
    guard = bv.get("guardrail", {})
    placeholder_rule = (
        "\n\nSome units are marked [PLACEHOLDER: note] in the draft below -- their writer has "
        "already declared that specific content (a quote, a figure, a link, an image scene) is "
        "illustrative rather than sourced. Do not fail a placeholder unit on fact fidelity for "
        "the content the note describes; only check that the note actually explains what's "
        "illustrative. " + ("This page must not ship with any placeholders at all -- flag every "
        "[PLACEHOLDER] unit as critical." if strictness == "publish-ready" else
        "Placeholders are expected here and are not themselves a problem."))
    return (
        f"You are the quality reviewer for {brand_full_name(bv)}'s web copy. You do not "
        "rewrite; you judge the draft against the brand standards below.\n\n"
        "Method (vendored from Anthropic's brand-voice quality-assurance agent):\n"
        + voice_method.qa_checklist() + "\n\n"
        + (f"We Are / We Are Not:\n{rows}\n\n" if rows else "")
        + (f"Floor: {guard.get('floor_description', '')}\n" if guard.get("floor_description") else "")
        + ("Checklist:\n" + "\n".join(f"- {c}" for c in guard.get("checks", [])) + "\n\n"
           if guard.get("checks") else "")
        + ("House style:\n" + "\n".join(f"- {r}" for r in terms.get("style_rules", [])) + "\n\n"
           if terms.get("style_rules") else "")
        + "Also apply the name-swap test to every sentence: if it would read the same on "
        "another organization's site with the name swapped, it is generic filler (critical).\n\n"
        "Fact fidelity -- go sentence by sentence against the ALLOWED FACTS block. Each of "
        "these is critical:\n"
        "- any figure, quote, ranking or claim not supported there;\n"
        "- a motive, plan, significance or trend nobody stated (\"part of broader efforts "
        "to...\", \"reflects a commitment to...\", \"aims to...\" when the brief never said so);\n"
        "- a proper name, program name or ID written differently from ALLOWED FACTS (e.g. an "
        "abbreviation expanded);\n"
        "- an allowed fact dropped in as padding that has nothing to do with this piece's "
        "topic, or an old figure restated as current without its date.\n"
        "Score fact_fidelity 5 only if none of these occur. Quote the exact words at fault. "
        "Do not invent a minor issue to have something to say; a clean draft gets high scores "
        "and no issues." + placeholder_rule
    )


def critic(units: list[dict[str, Any]], bv: dict[str, Any], *, request_summary: str,
           allowed_corpus: str, strictness: str = "", budget: Budget | None = None,
           model: str | None = None, client=None) -> tuple[CriticOutput, float]:
    from .rewrite import _call, _default_model

    lines = ["REQUEST:", request_summary, "", "ALLOWED FACTS:",
             allowed_corpus.strip()[:12000] or "(none -- the draft should contain no specific facts "
                                                "beyond general, verifiable statements)",
             "", "DRAFT:"]
    for i, u in enumerate(units):
        lines.append(f"--- {i} ---"
                     + (f" [PLACEHOLDER: {u.get('placeholder_note', '')}]" if u.get("placeholder") else ""))
        if u.get("heading"):
            lines.append(f"Heading: {u['heading']}")
        lines.append(u.get("body") or u.get("text") or "")
    return _call(model or _default_model(), _critic_system(bv, strictness=strictness), "\n".join(lines),
                 CriticOutput, budget or Budget(), client=client,
                 max_output_tokens=MAX_OUTPUT_TOKENS)


def _safe_fix(fix: str, bv: dict[str, Any], corpus: str) -> str:
    """A critic's suggested wording must pass the same rules as the draft --
    a weak critic has recommended a banned term and an invented figure as
    "fixes". Such a fix is dropped (the issue itself is kept)."""
    if not fix.strip():
        return ""
    found, _ = rule_checks([{"body": fix}], bv, output_kind="snippet", allowed_corpus=corpus)
    return "" if any(i.severity == CRITICAL for i in found) else fix


def review(units: list[dict[str, Any]], bv: dict[str, Any], *, output_kind: str = "page",
           char_limit: int | None = None, keywords: list[str] | None = None,
           reading_level: str = "", allowed_corpus: str = "", request_summary: str = "",
           ap_style: bool = False, source_text: str = "", coverage: str = "", strictness: str = "",
           use_critic: bool = True, budget: Budget | None = None,
           model: str | None = None, client=None) -> ReviewResult:
    issues, metrics = rule_checks(units, bv, output_kind=output_kind, char_limit=char_limit,
                                  keywords=keywords, reading_level=reading_level,
                                  allowed_corpus=allowed_corpus, ap_style=ap_style,
                                  source_text=source_text, coverage=coverage, strictness=strictness)
    scores: dict[str, int] = {}
    questions: list[dict[str, str]] = []
    cost = 0.0
    if use_critic:
        parsed, cost = critic(units, bv, request_summary=request_summary,
                              allowed_corpus=allowed_corpus, strictness=strictness,
                              budget=budget, model=model, client=client)
        scores = {k: max(1, min(5, int(getattr(parsed, k))))
                  for k in ("voice_match", "tone_fit", "clarity", "fact_fidelity")}
        for ci in parsed.issues:
            sev = CRITICAL if ci.severity.strip().lower().startswith("crit") else SUGGESTED
            issues.append(ReviewIssue(sev, ci.problem, ci.section, ci.quote,
                                      _safe_fix(ci.fix, bv, allowed_corpus), "critic"))
        questions = [q.model_dump() for q in parsed.open_questions]
    passes = not any(i.severity == CRITICAL for i in issues)
    return ReviewResult(passes=passes, issues=issues, scores=scores, open_questions=questions,
                        metrics=metrics, cost_usd=cost)


def units_from_sections(sections) -> list[dict[str, Any]]:
    return [{"heading": s.heading, "body": s.body} for s in sections]
