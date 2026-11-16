"""Semantic diff: meaning that did not survive the rewrite.

The structural stage sees a paragraph is gone only if a heading or a link went
with it. A paragraph reworded to drop a tuition figure leaves the structure
untouched, and that is precisely the failure this project exists to catch.

The central measure here is **coverage**, not similarity. A whole-page cosine
is symmetric and dominated by bulk: a page that kept ninety percent of its text
and dropped one load-bearing paragraph still scores about 0.95, which reads as
"minor rewording" and hides the loss. So each old chunk is matched against its
best counterpart on the new page, and the chunks with no good match *are* the
finding. Overall similarity is still reported, because the dashboard needs a
single number to show a reviewer, but nothing is ranked on it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .embed import Chunk, Embedder, chunk_page
from .models import Finding, PageContent, Severity

# Cosine thresholds for all-MiniLM-L6-v2, calibrated by `python -m
# src.tune_semantic`, which prints the scores behind them.
#
# The calibration's headline result is negative and worth stating plainly: the
# classes overlap. A faithful heavy paraphrase scores 0.734 while a rewrite
# that silently dropped a GPA requirement scores 0.764. Cosine similarity
# measures topical overlap, not factual completeness, so no threshold
# separates "reworded" from "reworded and lost a fact".
#
# So MATCH_STRONG is deliberately set high rather than at the apparent
# boundary. Everything between the two thresholds is "substantially
# rewritten -- a human or the LLM judge must read it", which is exactly the
# queue phase 6 consumes. The two errors are not symmetric: a dropped fact
# scored as "kept" is silent and never reaches a reviewer, while a faithful
# paraphrase sent for review costs one judge call. The threshold is set to
# make the first kind impossible on the calibration set, accepting the second.
MATCH_STRONG = 0.85    # at or above: nothing meaningful changed
MATCH_WEAK = 0.55      # below: nothing of this passage carried over

# A page whose surviving chunks are all strong matches but which lost a chunk
# outright is a different animal from one that was reworded throughout, so
# coverage and similarity are reported separately rather than averaged.
COVERAGE_CONCERN = 0.9
COVERAGE_ALARM = 0.75


@dataclass
class ChunkMatch:
    old: Chunk
    new: Chunk | None
    similarity: float

    @property
    def is_dropped(self) -> bool:
        return self.new is None or self.similarity < MATCH_WEAK

    @property
    def is_reworded(self) -> bool:
        return (self.new is not None
                and MATCH_WEAK <= self.similarity < MATCH_STRONG)


@dataclass
class SemanticDiff:
    overall_similarity: float = 1.0
    coverage: float = 1.0          # share of old content with a counterpart
    matches: list[ChunkMatch] = field(default_factory=list)
    added: list[Chunk] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    embedder: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> list[ChunkMatch]:
        return [m for m in self.matches if m.is_dropped]

    @property
    def reworded(self) -> list[ChunkMatch]:
        return [m for m in self.matches if m.is_reworded]

    @property
    def worst(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.INFO)

    def interpretation(self) -> str:
        """The plain-language line the dashboard shows beside the score.

        Coverage leads, because it is the number that answers the question a
        reviewer is actually asking.
        """
        pct = round(self.overall_similarity * 100)
        if not self.matches:
            return "no comparable text on the old page"
        if self.coverage >= COVERAGE_CONCERN and self.overall_similarity >= MATCH_STRONG:
            return f"{pct}% similar - reworded at most lightly, nothing obviously dropped"
        if self.coverage >= COVERAGE_CONCERN:
            return f"{pct}% similar - substantially rewritten, but all sections still covered"
        if self.coverage >= COVERAGE_ALARM:
            return (f"{pct}% similar - {len(self.dropped)} passage(s) have no "
                    "counterpart on the new page")
        return (f"{pct}% similar - only {round(self.coverage * 100)}% of the old "
                "page is accounted for; likely content loss")


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def _weighted_mean(vectors: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Mean of chunk vectors weighted by length, renormalized.

    Length weighting stops a one-line caption counting as much as a three
    paragraph section when forming the page-level vector.
    """
    if len(vectors) == 0:
        return np.zeros((0,), dtype=np.float32)
    pooled = (vectors * weights[:, None]).sum(axis=0) / max(weights.sum(), 1e-12)
    norm = float(np.linalg.norm(pooled))
    return pooled / norm if norm > 1e-12 else pooled


def match_chunks(
    old_chunks: list[Chunk],
    new_chunks: list[Chunk],
    old_vectors: np.ndarray,
    new_vectors: np.ndarray,
) -> tuple[list[ChunkMatch], list[Chunk]]:
    """Greedily pair old chunks to their best new counterpart.

    Best-first across the whole similarity matrix rather than in document
    order: a migration reorders sections freely, and matching positionally
    would report a moved section as one drop plus one addition.

    A new chunk can be claimed by several old ones, but only up to its own
    length. Merging two sections under one heading is an ordinary migration
    edit, and a rule of one-claim-per-chunk reported half such a page as lost
    even when every word survived -- headings decide chunk boundaries, so
    dropping a heading alone was enough to trigger it. Budgeting by words keeps
    the honest case honest: a new passage shorter than the old ones it absorbs
    runs out of budget, and the remainder is correctly reported as gone.
    """
    if not old_chunks:
        return [], list(new_chunks)
    if not new_chunks:
        return [ChunkMatch(c, None, 0.0) for c in old_chunks], []

    similarity = old_vectors @ new_vectors.T          # both sides L2-normalized
    pairs: list[tuple[float, int, int]] = [
        (float(similarity[i, j]), i, j)
        for i in range(len(old_chunks))
        for j in range(len(new_chunks))
    ]
    pairs.sort(key=lambda t: -t[0])

    taken_old: dict[int, ChunkMatch] = {}
    taken_new: set[int] = set()
    budget = {j: max(c.word_count, 1) for j, c in enumerate(new_chunks)}
    for score, i, j in pairs:
        if i in taken_old or budget[j] <= 0:
            continue
        if score < MATCH_WEAK:
            break                                     # nothing usable remains
        taken_old[i] = ChunkMatch(old_chunks[i], new_chunks[j], score)
        taken_new.add(j)
        budget[j] -= max(old_chunks[i].word_count, 1)

    matches = [
        taken_old.get(i) or ChunkMatch(chunk, None, float(similarity[i].max()))
        for i, chunk in enumerate(old_chunks)
    ]
    added = [c for j, c in enumerate(new_chunks) if j not in taken_new]
    return matches, added


# --------------------------------------------------------------------------
# the diff
# --------------------------------------------------------------------------

def diff_semantic(
    old: PageContent,
    new: PageContent,
    embedder: Embedder,
    *,
    target_words: int = 0,
) -> SemanticDiff:
    """Compare two pages by meaning and report what did not carry over."""
    kwargs = {"target_words": target_words} if target_words else {}
    old_chunks = chunk_page(old, **kwargs)
    new_chunks = chunk_page(new, **kwargs)

    diff = SemanticDiff(embedder=type(embedder).__name__)

    if not old_chunks:
        diff.notes.append("old page has no comparable text")
        diff.overall_similarity = 0.0 if new_chunks else 1.0
        diff.coverage = 1.0
        diff.added = new_chunks
        return diff

    old_vectors = embedder.encode([c.text for c in old_chunks])
    new_vectors = (embedder.encode([c.text for c in new_chunks])
                   if new_chunks else np.zeros((0, old_vectors.shape[1]),
                                               dtype=old_vectors.dtype))

    diff.matches, diff.added = match_chunks(
        old_chunks, new_chunks, old_vectors, new_vectors)

    old_weights = np.array([max(c.word_count, 1) for c in old_chunks], dtype=np.float32)
    if new_chunks:
        new_weights = np.array([max(c.word_count, 1) for c in new_chunks],
                               dtype=np.float32)
        diff.overall_similarity = float(np.clip(
            _weighted_mean(old_vectors, old_weights)
            @ _weighted_mean(new_vectors, new_weights), -1.0, 1.0))
    else:
        diff.overall_similarity = 0.0

    # Coverage is weighted by length, so losing one long section counts for
    # more than losing one caption.
    covered = sum(m.old.word_count for m in diff.matches if not m.is_dropped)
    total = sum(m.old.word_count for m in diff.matches)
    diff.coverage = covered / total if total else 1.0

    _add_findings(diff)
    return diff


def _add_findings(diff: SemanticDiff) -> None:
    dropped, reworded = diff.dropped, diff.reworded

    if dropped:
        lost_words = sum(m.old.word_count for m in dropped)
        severity = Severity.HIGH if diff.coverage < COVERAGE_CONCERN else Severity.MEDIUM
        diff.findings.append(Finding(
            kind="content.dropped",
            severity=severity,
            summary=(f"{len(dropped)} passage(s) totalling {lost_words} words have "
                     "no counterpart on the new page"),
            # Score first: it is the part a reviewer scans for, and a long
            # passage preview would otherwise push it off the end of the line.
            items=[f"[best match {m.similarity:.2f}] {_where(m.old)}{m.old.preview(60)}"
                   for m in dropped],
        ))

    if reworded:
        diff.findings.append(Finding(
            kind="content.reworded",
            severity=Severity.LOW,
            summary=f"{len(reworded)} passage(s) were substantially rewritten",
            items=[f"[similarity {m.similarity:.2f}] {_where(m.old)}{m.old.preview(60)}"
                   for m in reworded],
        ))

    if diff.coverage < COVERAGE_ALARM:
        diff.findings.append(Finding(
            kind="content.coverage_low",
            severity=Severity.HIGH,
            summary=(f"only {round(diff.coverage * 100)}% of the old page's text is "
                     "accounted for on the new page"),
            items=[diff.interpretation()],
        ))

    if diff.added:
        diff.findings.append(Finding(
            kind="content.added",
            severity=Severity.INFO,
            summary=f"{len(diff.added)} passage(s) on the new page are new",
            items=[f"{_where(c)}{c.preview(70)}" for c in diff.added],
        ))


def _where(chunk: Chunk) -> str:
    return f"under {chunk.section!r}: " if chunk.section else ""
