"""Risk scoring: one tier per page, from the structural and semantic findings.

The build plan's tiers are Clean / Minor rewording / Major rewording / Missing
content, and those are not four points on one scale. "Missing" is a different
*kind* of evidence from "rewritten", not merely more of it: a page can be
rewritten end to end and still say everything it used to, while a page that
dropped one paragraph may be otherwise untouched. Collapsing both into a single
number is what makes a QA tool rank a heavy but faithful rewrite above a quiet
deletion.

So two axes are scored separately:

* **loss** -- evidence that specific content is gone: passages with no
  counterpart, dropped headings, dropped documents, dropped images and links.
* **change** -- evidence of rewording: passages substantially rewritten,
  headings reworded, overall similarity down.

The tier comes from rules over those two axes, so it can always be explained in
words. The 0-100 score exists only to order pages *within* a tier, and nothing
should be decided from it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .diff_semantic import SemanticDiff
from .diff_structural import StructuralDiff

# --- loss weights ---------------------------------------------------------
# Coverage dominates when the semantic stage ran: it measures the share of the
# old page's words with no counterpart, which is the most direct evidence of
# loss available. The structural weights below are per-item, each capped, so a
# link-heavy page cannot out-shout a page that lost a whole section.
COVERAGE_WEIGHT = 100.0
LOSS_PER_DOCUMENT = 15.0     # a dropped PDF is invisible to every other signal
LOSS_PER_HEADING = 8.0       # a heading gone usually means a section gone
LOSS_PER_IMAGE = 3.0
LOSS_PER_LINK = 2.0
LOSS_CAP_DOCUMENTS = 45.0
LOSS_CAP_HEADINGS = 40.0
LOSS_CAP_IMAGES = 15.0
LOSS_CAP_LINKS = 12.0

# When the semantic stage reports the old text fully accounted for, a dropped
# heading or image means the page was *restructured*, not that content is gone
# -- the words are still there under a different shape. Those signals are
# proxies for text loss, and adding them to a coverage figure that already says
# "nothing missing" double-counts a redesign as a deletion. The real
# uta.edu/about pair proved it: coverage 1.00, text grown from 113 to 285
# words, and still scored Missing content purely on dropped headings.
#
# Document links are exempt. A PDF is not part of the page's text, so no
# coverage figure can vouch for it; its loss is independent evidence.
# The discount ramps rather than switching, because a cliff at one coverage
# value means a page slipping from 0.90 to 0.89 has its structural loss
# quadruple and can jump two tiers on a rounding error. Full weight is restored
# once a quarter of the text is genuinely unaccounted for.
STRUCTURAL_PROXY_DISCOUNT = 0.25
PROXY_FULL_WEIGHT_AT_MISSING_SHARE = 0.25


def _proxy_weight(semantic) -> float:
    """How much to trust dropped headings/images/links as evidence of loss."""
    if semantic is None or not semantic.matches:
        return 1.0        # no text signal, so the proxies are all there is
    missing_share = max(0.0, 1.0 - semantic.coverage)
    ramp = min(1.0, missing_share / PROXY_FULL_WEIGHT_AT_MISSING_SHARE)
    return STRUCTURAL_PROXY_DISCOUNT + (1.0 - STRUCTURAL_PROXY_DISCOUNT) * ramp

# --- change weights -------------------------------------------------------
CHANGE_REWORDED_SHARE = 50.0   # share of passages substantially rewritten
CHANGE_SIMILARITY = 50.0       # how far overall similarity fell
CHANGE_PER_HEADING = 5.0
CHANGE_PER_LEVEL = 2.0
CHANGE_CAP_HEADINGS = 25.0

# --- tier boundaries ------------------------------------------------------
# Calibrated against the pairs in data/url_pairs.csv and the synthetic
# worst-case page; `python -m src.score --explain` prints where any given pair
# falls and why.
LOSS_MISSING = 25.0    # at or above: content is gone, not merely changed
LOSS_ANY = 6.0         # above: something is gone, but not much
CHANGE_MAJOR = 35.0
CHANGE_MINOR = 12.0

# Ranking blend. Loss counts for more than change because the tool exists to
# find loss; change only breaks ties between pages that lost similar amounts.
CHANGE_RANK_WEIGHT = 0.3


class RiskTier(IntEnum):
    """Ordered worst-first for ranking. UNKNOWN sits below CLEAN on purpose --
    a pair that could not be fetched is not a safe page, but it is also not a
    finding, and letting it outrank real losses would bury them."""

    UNKNOWN = -1
    CLEAN = 0
    MINOR = 1
    MAJOR = 2
    MISSING = 3

    @property
    def label(self) -> str:
        return {
            RiskTier.UNKNOWN: "Unknown",
            RiskTier.CLEAN: "Clean",
            RiskTier.MINOR: "Minor rewording",
            RiskTier.MAJOR: "Major rewording",
            RiskTier.MISSING: "Missing content",
        }[self]


@dataclass
class RiskScore:
    tier: RiskTier
    score: float = 0.0             # 0-100, for ordering only
    loss: float = 0.0
    change: float = 0.0
    reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        """How much to trust this verdict.

        Caveats are the things that could make the tier wrong in either
        direction -- a stale snapshot, a page extracted without a content
        landmark, or rewritten passages an embedding cannot vouch for.
        """
        if self.tier is RiskTier.UNKNOWN:
            return "none"
        if len(self.caveats) >= 2:
            return "low"
        return "medium" if self.caveats else "high"


# --------------------------------------------------------------------------
# the two axes
# --------------------------------------------------------------------------

def _count_items(diff: StructuralDiff, kind: str) -> int:
    return sum(len(f.items) for f in diff.of_kind(kind))


def loss_points(structural: StructuralDiff | None,
                semantic: SemanticDiff | None) -> tuple[float, list[str]]:
    """Evidence that content is gone, with the reasons that produced it."""
    points = 0.0
    reasons: list[str] = []

    if semantic is not None and semantic.matches:
        missing_share = max(0.0, 1.0 - semantic.coverage)
        if missing_share > 0:
            points += missing_share * COVERAGE_WEIGHT
            lost_words = sum(m.old.word_count for m in semantic.dropped)
            reasons.append(
                f"{round(missing_share * 100)}% of the old page's text has no "
                f"counterpart ({lost_words} words across "
                f"{len(semantic.dropped)} passage(s))")

    if structural is None:
        return points, reasons

    proxy = _proxy_weight(semantic)

    for kind, weight, cap, noun, is_proxy in (
        ("link.document_dropped", LOSS_PER_DOCUMENT, LOSS_CAP_DOCUMENTS,
         "document link", False),
        ("heading.dropped", LOSS_PER_HEADING, LOSS_CAP_HEADINGS, "heading", True),
        ("image.dropped", LOSS_PER_IMAGE, LOSS_CAP_IMAGES, "image", True),
        ("link.dropped", LOSS_PER_LINK, LOSS_CAP_LINKS, "link", True),
    ):
        count = _count_items(structural, kind)
        if not count:
            continue
        scale = proxy if is_proxy else 1.0
        points += min(count * weight, cap) * scale
        plural = "s" if count != 1 else ""
        reasons.append(
            f"{count} {noun}{plural} dropped"
            + (" (weighted down: the old page's text is largely accounted for, "
               "so this reads as restructuring)" if scale < 0.6 else ""))

    return points, reasons


def change_points(structural: StructuralDiff | None,
                  semantic: SemanticDiff | None) -> tuple[float, list[str]]:
    """Evidence of rewording, with the reasons that produced it."""
    points = 0.0
    reasons: list[str] = []

    if semantic is not None and semantic.matches:
        reworded_share = len(semantic.reworded) / len(semantic.matches)
        if reworded_share:
            points += reworded_share * CHANGE_REWORDED_SHARE
            reasons.append(f"{len(semantic.reworded)} of {len(semantic.matches)} "
                           "passage(s) substantially rewritten")
        drop = max(0.0, 1.0 - semantic.overall_similarity)
        if drop > 0.02:
            points += drop * CHANGE_SIMILARITY
            reasons.append(f"overall similarity {semantic.overall_similarity:.2f}")

    if structural is not None:
        reworded = _count_items(structural, "heading.reworded")
        if reworded:
            points += min(reworded * CHANGE_PER_HEADING, CHANGE_CAP_HEADINGS)
            reasons.append(f"{reworded} heading(s) reworded")
        relevelled = _count_items(structural, "heading.level_changed")
        if relevelled:
            points += relevelled * CHANGE_PER_LEVEL
            reasons.append(f"{relevelled} heading(s) changed level")

    return points, reasons


# --------------------------------------------------------------------------
# caveats
# --------------------------------------------------------------------------

# A Wayback capture this much older than the new page's fetch makes drift
# indistinguishable from migration loss: the old site kept changing after the
# snapshot was taken, and none of that is the migration's doing.
STALE_SNAPSHOT_DAYS = 400


def _snapshot_age_days(pair) -> int | None:
    from datetime import datetime, timezone

    stamp = pair.old.snapshot_timestamp
    if not stamp or len(stamp) < 8:
        return None
    try:
        taken = datetime.strptime(stamp[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - taken).days


def caveats_for(pair, structural: StructuralDiff | None,
                semantic: SemanticDiff | None) -> list[str]:
    """Reasons this verdict might be wrong, in either direction."""
    out: list[str] = list(pair.warnings)

    age = _snapshot_age_days(pair)
    if age is not None and age > STALE_SNAPSHOT_DAYS:
        out.append(
            f"old page is a Wayback capture from {pair.old.snapshot_timestamp[:8]}, "
            f"about {age // 365} year(s) old -- some differences are the old site's "
            "own drift, not the migration's doing")

    if semantic is None:
        out.append("semantic comparison was skipped; only structure was checked")
    elif semantic.reworded:
        # The phase 3 calibration result, surfaced where it matters: a rewritten
        # passage that quietly dropped a fact scores like a faithful rewrite.
        out.append(
            f"{len(semantic.reworded)} passage(s) were rewritten; embeddings "
            "cannot tell a faithful rewrite from one that dropped a fact, so "
            "these need the LLM judge or a human")

    for side, page in (("old", pair.old), ("new", pair.new)):
        if "body-fallback" in (page.extractor or ""):
            out.append(f"{side} page had no content landmark, so boilerplate may "
                       "have leaked into the comparison")
        if 50 <= page.word_count < 120:
            out.append(f"{side} page yielded only {page.word_count} words, "
                       "which makes every ratio noisy")
    return out


# --------------------------------------------------------------------------
# the tier
# --------------------------------------------------------------------------

def score_pair(pair, structural: StructuralDiff | None,
               semantic: SemanticDiff | None) -> RiskScore:
    """Combine both diffs into one tier, with the reasoning kept attached."""
    if structural is None or pair.problems:
        return RiskScore(
            tier=RiskTier.UNKNOWN,
            reasons=list(pair.problems) or ["the pair could not be compared"],
        )

    loss, loss_reasons = loss_points(structural, semantic)
    change, change_reasons = change_points(structural, semantic)

    if loss >= LOSS_MISSING:
        tier = RiskTier.MISSING
    elif loss > LOSS_ANY:
        # Something is gone but not much. That is still a loss, so it outranks
        # any amount of pure rewording.
        tier = RiskTier.MAJOR
    elif change >= CHANGE_MAJOR:
        tier = RiskTier.MAJOR
    elif loss > 0 or change >= CHANGE_MINOR:
        tier = RiskTier.MINOR
    else:
        tier = RiskTier.CLEAN

    reasons = loss_reasons + change_reasons
    if tier is RiskTier.CLEAN:
        # The plan asks for this explicitly: a reviewer will not trust a green
        # row unless the tool says what it checked to earn it.
        reasons = _clean_reasons(structural, semantic)

    return RiskScore(
        tier=tier,
        score=round(min(100.0, loss + change * CHANGE_RANK_WEIGHT), 1),
        # Reported on the same 0-100 scale as the score. Past the MISSING
        # boundary the excess carries no information, and a loss of 127 shown
        # beside a score of 100 just reads as a bug.
        loss=round(min(100.0, loss), 1),
        change=round(min(100.0, change), 1),
        reasons=reasons,
        caveats=caveats_for(pair, structural, semantic),
    )


def _clean_reasons(structural: StructuralDiff,
                   semantic: SemanticDiff | None) -> list[str]:
    old_headings, _ = structural.counts.get("headings", (0, 0))
    old_links, _ = structural.counts.get("links", (0, 0))
    out = [f"all {old_headings} heading(s) and {old_links} link(s) accounted for"]
    if semantic is not None and semantic.matches:
        out.append(f"all {len(semantic.matches)} passage(s) matched, "
                   f"similarity {semantic.overall_similarity:.2f}")
    else:
        out.append("structure only; no semantic check was run")
    return out


def rank(scored: list[tuple]) -> list[tuple]:
    """Order results worst first. `scored` is (anything..., RiskScore) tuples."""
    return sorted(scored, key=lambda row: (-int(row[-1].tier), -row[-1].score))
