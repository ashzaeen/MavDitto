"""The LLM judge: what a rewrite actually did to the content.

This exists because of a measured limit, not as polish. Phase 3's calibration
(`python -m src.tune_semantic`) showed the classes overlap: a faithful heavy
paraphrase scores 0.734 while a rewrite that silently dropped a GPA requirement
scores 0.764. Cosine similarity measures topical overlap, not factual
completeness, so no embedding threshold separates "reworded" from "reworded and
lost a fact". The judge is the only component that can make that call.

So it does not re-judge whole pages. It reads exactly the passages the semantic
stage could not vouch for -- the ones between MATCH_WEAK and MATCH_STRONG --
plus the passages that vanished outright, and answers the one question the rest
of the pipeline cannot: did this rewrite keep the facts?

Cost is controlled three ways, because the build plan asks for an explicit cap:

* only flagged pages are judged, and within them only flagged passages;
* one request per page rather than per passage;
* a hard `Budget` that is checked *before* each call, using the API's own token
  counter, and refuses to start a call it cannot afford.

Results are cached on disk by content, so re-running the pipeline over pages
that have not changed costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .llm_cost import (
    Budget, BudgetExceeded, CredentialsMissing, NO_CREDENTIALS_MESSAGE,
    PRICING, explain_api_failure, is_credentials_error,
)

MAX_PASSAGES_PER_PAGE = 12     # beyond this the page is plainly broken anyway
MAX_CHARS_PER_PASSAGE = 4000
MAX_OUTPUT_TOKENS = 8000       # adaptive thinking shares this ceiling

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "judge_cache"


# Budget, BudgetExceeded, CredentialsMissing, is_credentials_error and
# NO_CREDENTIALS_MESSAGE now live in llm_cost.py, shared with alt_text.py.
# Re-exported here (via the import above) so existing callers of
# `from .llm_judge import Budget` keep working unchanged.

# --------------------------------------------------------------------------
# what we ask for back
# --------------------------------------------------------------------------

class PassageVerdict(BaseModel):
    index: int = Field(description="The passage number given in the prompt.")
    verdict: Literal["facts_kept", "facts_lost", "unclear"] = Field(
        description=("facts_kept if every specific claim in the old passage still "
                     "appears; facts_lost if any specific claim is gone; unclear "
                     "if the passages are too different to compare."))
    detail: str = Field(
        description=("One sentence naming what was lost, quoting the specific "
                     "figure, date, requirement or instruction. If nothing was "
                     "lost, say what was merely reworded."))


class PageJudgement(BaseModel):
    summary: str = Field(
        description=("Two or three sentences a content reviewer can act on, "
                     "naming what changed on this page."))
    severity: Literal["none", "minor", "major"] = Field(
        description=("major if a reader of the new page would be missing "
                     "information they need; minor if only wording or emphasis "
                     "changed; none if nothing meaningful changed."))
    passages: list[PassageVerdict] = Field(
        description="One entry per numbered passage in the prompt.")


# --------------------------------------------------------------------------
# the prompt
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are reviewing a website migration. Each page existed on \
an old site and was rebuilt on a new one, and your job is to say whether the \
rebuild lost information.

You will be given numbered passages. Each has the OLD text and either the NEW \
text that replaced it, or a note that nothing on the new page corresponds to it.

For each passage, decide whether every specific claim in the old text still \
appears in the new text. Specific claims are the things a reader would act on:

- figures: fees, tuition, GPA minimums, credit hours, counts, percentages
- dates and deadlines
- requirements, eligibility rules, and conditions
- named contacts, offices, phone numbers and addresses
- instructions telling the reader what to do

Rewording is not loss. If the new text says the same thing in different words, \
or is shorter but keeps every claim, that is facts_kept. Only call it \
facts_lost when a specific claim that was in the old text is absent from the \
new text.

Added information is not loss either. The new page may say more; judge only \
whether the old claims survived.

Examples:
- OLD: "The application fee is $75 and is non-refundable." NEW: "A fee \
applies when you submit your application." -> facts_lost. The $75 figure and \
the non-refundable condition are both gone -- "a fee applies" is not the same \
specific claim as "$75, non-refundable."
- OLD: "The application fee is $75 and is non-refundable." NEW: "Applying \
costs $75; this fee cannot be refunded once submitted." -> facts_kept. Same \
two claims, different wording.
- OLD: "Priority consideration closes on February 15." NEW: (nothing on the \
new page corresponds to it) -> facts_lost. The deadline is simply gone.

For each passage, first list which specific claims (per the categories \
above) the OLD text actually contains, then check each one individually \
against the NEW text before deciding the verdict -- do not jump straight to \
an overall impression.

Be concrete. "Some details were removed" is useless to a reviewer. Name the \
figure, the date, or the requirement that is gone, and quote it.

Do not speculate about why something changed, and do not recommend fixes."""


def _truncate(text: str, limit: int = MAX_CHARS_PER_PASSAGE) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    # Cut at a sentence boundary where possible so the judge is not asked to
    # reason about a passage that stops mid-word.
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("\n"))
    return (head[: cut + 1] if cut > limit // 2 else head) + "\n[... truncated]"


def select_passages(passages: list[dict], *, limit: int = MAX_PASSAGES_PER_PAGE
                    ) -> list[dict]:
    """The passages worth paying for.

    Reworded ones first: those are the band embeddings provably cannot resolve,
    and the whole reason this stage exists. Dropped ones follow, because naming
    what vanished is what makes the summary usable -- but they are already known
    losses, so they never crowd out the ambiguous cases.
    """
    reworded = [p for p in passages if p.get("verdict") == "reworded"]
    dropped = [p for p in passages if p.get("verdict") == "dropped"]
    reworded.sort(key=lambda p: p.get("similarity", 0.0))
    dropped.sort(key=lambda p: -len((p.get("old_text") or "").split()))
    return (reworded + dropped)[:limit]


def build_prompt(passages: list[dict], *, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.append(f"Page: {title}")
        lines.append("")
    for number, passage in enumerate(passages, start=1):
        section = passage.get("section") or "(no heading)"
        lines.append(f"--- Passage {number} (section: {section}) ---")
        lines.append("OLD:")
        lines.append(_truncate(passage.get("old_text") or ""))
        lines.append("")
        new_text = passage.get("new_text")
        if new_text:
            lines.append("NEW:")
            lines.append(_truncate(new_text))
        else:
            lines.append("NEW: (nothing on the new page corresponds to this "
                         "passage)")
        lines.append("")
    lines.append(f"Give a verdict for each of the {len(passages)} passages, "
                 "then a summary of what this page lost.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

class JudgeCache:
    """Disk cache keyed by what was actually judged.

    The key covers the model, the prompt and the passage text, so re-running
    the pipeline over unchanged pages costs nothing, while a changed page or a
    changed rubric is judged again rather than served stale.
    """

    def __init__(self, directory: Path | str = CACHE_DIR, enabled: bool = True):
        self.directory = Path(directory)
        self.enabled = enabled
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, prompt: str) -> str:
        payload = f"{model}\x00{SYSTEM_PROMPT}\x00{prompt}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            (self.directory / f"{key}.json").write_text(
                json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass      # a cache write failure is never worth failing a run over


# --------------------------------------------------------------------------
# the judge
# --------------------------------------------------------------------------

@dataclass
class JudgeOutcome:
    """What the judge concluded about one page, plus what it cost."""

    judged: bool = False
    summary: str = ""
    severity: str = "none"
    passages: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    cost_usd: float = 0.0
    cached: bool = False
    skipped_reason: str = ""

    @property
    def facts_lost(self) -> list[dict[str, Any]]:
        return [p for p in self.passages if p.get("verdict") == "facts_lost"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "judged": self.judged,
            "summary": self.summary,
            "severity": self.severity,
            "passages": self.passages,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 6),
            "cached": self.cached,
            "skipped_reason": self.skipped_reason,
        }


class Judge:
    """Judges one page per call, within a budget.

    The client is built lazily so importing this module, and running the
    pipeline without `--judge`, never needs credentials.
    """

    def __init__(self, *, model: str | None = None, budget: Budget | None = None,
                 cache: JudgeCache | None = None, effort: str = "high"):
        from . import llm_provider
        self.model = model or llm_provider.default_model("high")
        self.budget = budget or Budget()
        self.cache = cache if cache is not None else JudgeCache()
        self.effort = effort
        self._client = None
        self.budget.price(self.model)      # fail now, not after a page has been fetched

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "the anthropic package is not installed; uncomment the phase 6 "
                    "line in requirements.txt and reinstall"
                ) from exc
            # Zero-arg construction resolves ANTHROPIC_API_KEY,
            # ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile, in that
            # order. Construction succeeds even with none of them -- the
            # failure surfaces on the first request; see is_credentials_error.
            self._client = anthropic.Anthropic()
        return self._client

    def count_input_tokens(self, prompt: str) -> int:
        """Ask the API what this call will cost in input tokens.

        Counting is free and unmetered on Claude, which is what makes a
        pre-call budget check possible at all -- Gemini has no equivalent in
        this abstraction, so a Gemini model goes straight to the same
        character estimate `llm_provider`'s own Gemini path uses. If Claude's
        real count fails for any other reason, fall back to that same
        pessimistic estimate rather than skipping the check.
        """
        from . import llm_provider
        if llm_provider.provider_for_model(self.model) != "claude":
            return (len(SYSTEM_PROMPT) + len(prompt)) // 3
        try:
            counted = self.client.messages.count_tokens(
                model=self.model,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return int(counted.input_tokens)
        except Exception as exc:
            if is_credentials_error(exc):
                raise CredentialsMissing(NO_CREDENTIALS_MESSAGE) from exc
            return (len(SYSTEM_PROMPT) + len(prompt)) // 3

    def judge_page(self, passages: list[dict], *, title: str = "") -> JudgeOutcome:
        """Judge one page's flagged passages."""
        selected = select_passages(passages)
        if not selected:
            return JudgeOutcome(
                skipped_reason="nothing ambiguous to judge on this page")

        prompt = build_prompt(selected, title=title)
        key = JudgeCache.key(self.model, prompt)

        cached = self.cache.get(key)
        if cached is not None:
            outcome = JudgeOutcome(**cached)
            outcome.cached = True
            outcome.cost_usd = 0.0
            return outcome

        try:
            self.budget.check(self.model, self.count_input_tokens(prompt))
        except BudgetExceeded as exc:
            self.budget.skipped += 1
            return JudgeOutcome(skipped_reason=str(exc))
        except CredentialsMissing as exc:
            return JudgeOutcome(skipped_reason=str(exc))

        from . import llm_provider

        try:
            # The rubric is identical on every call, so on Claude it's sent
            # with cache_control -- the bulk of each request becomes a cache
            # read after the first page (llm_provider always marks the
            # system prompt cacheable on the Claude path).
            parsed, cost = llm_provider.call_structured(
                self.model, SYSTEM_PROMPT, prompt, PageJudgement, self.budget,
                max_output_tokens=MAX_OUTPUT_TOKENS, effort=self.effort,
                client=self._client, label="judge")
        except BudgetExceeded as exc:
            self.budget.skipped += 1
            return JudgeOutcome(skipped_reason=str(exc))
        except CredentialsMissing as exc:
            return JudgeOutcome(skipped_reason=str(exc))
        except Exception as exc:
            # llm_provider already turned this into a labeled, human-readable
            # message -- explain_api_failure again here would double-wrap it.
            return JudgeOutcome(skipped_reason=str(exc))

        by_index = {p.index: p for p in parsed.passages}
        outcome = JudgeOutcome(
            judged=True,
            summary=parsed.summary,
            severity=parsed.severity,
            model=self.model,
            cost_usd=cost,
            passages=[
                {
                    "section": passage.get("section", ""),
                    "similarity": passage.get("similarity"),
                    "semantic_verdict": passage.get("verdict"),
                    "verdict": (by_index[number].verdict
                                if number in by_index else "unclear"),
                    "detail": (by_index[number].detail
                               if number in by_index else
                               "the judge returned no verdict for this passage"),
                }
                for number, passage in enumerate(selected, start=1)
            ],
        )
        self.cache.put(key, {**outcome.to_dict(), "cached": False})
        return outcome


def should_judge(risk_tier: str, semantic: dict) -> bool:
    """Whether a page is worth spending a call on.

    The build plan's cost rule, made concrete: judge only pages the pipeline has
    already flagged, and only when there is something for the judge to resolve.
    A clean page has nothing ambiguous on it, and paying to be told so is waste.
    """
    if risk_tier in ("Clean", "Unknown"):
        return False
    return any(p.get("verdict") in ("reworded", "dropped")
               for p in semantic.get("passages", []))
