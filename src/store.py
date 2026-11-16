"""The results store: one JSON file per compared pair.

The pipeline writes here and the dashboard reads here, so the dashboard never
recomputes anything -- no fetching, no model loading, no waiting. That
separation is the point of having a store at all, and it is why the record
carries both normalized pages in full rather than just their scores: the detail
view needs the actual text to show a reviewer.

JSON files rather than SQLite for the MVP, as the build plan allows. The schema
below is what a SQLite table would hold if this grows, and `PairResult` is the
row; moving over later means changing this module and nothing else.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import PageContent

SCHEMA_VERSION = 1


def result_filename(old_url: str, new_url: str, discriminator: str = "") -> str:
    """Stable name for a pair's record.

    Keyed on everything that distinguishes one comparison from another:

    * both URLs, because several old pages consolidating onto one new page is an
      ordinary migration pattern and keying on the new URL alone made those
      pairs silently overwrite each other;
    * a discriminator carrying the snapshot and label, because comparing one
      page against captures from different dates is a legitimate run -- it is
      how you watch a page drift -- and those share both URLs exactly.
    """
    digest = hashlib.sha256(
        f"{old_url}|{new_url}|{discriminator}".encode()).hexdigest()[:8]
    stem = "".join(c if c.isalnum() else "_" for c in new_url)[-64:]
    return f"{stem}_{digest}.json"


@dataclass
class PairResult:
    """One compared pair, as the dashboard sees it."""

    old_url: str
    new_url: str
    label: str = ""
    compared_at: str = ""
    problems: list[str] = field(default_factory=list)
    old: PageContent | None = None
    new: PageContent | None = None
    risk: dict[str, Any] = field(default_factory=dict)
    structural: dict[str, Any] = field(default_factory=dict)
    semantic: dict[str, Any] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    path: str = ""

    # --- what the table needs --------------------------------------------

    @property
    def title(self) -> str:
        for candidate in (self.label,
                          self.new.title if self.new else "",
                          self.old.title if self.old else "",
                          self.new_url):
            if candidate:
                return candidate
        return "(untitled)"

    @property
    def tier(self) -> str:
        return self.risk.get("tier", "Unknown")

    @property
    def tier_rank(self) -> int:
        return int(self.risk.get("tier_rank", -1))

    @property
    def score(self) -> float:
        return float(self.risk.get("score", 0.0))

    @property
    def confidence(self) -> str:
        return self.risk.get("confidence", "none")

    @property
    def similarity(self) -> float | None:
        value = self.semantic.get("overall_similarity")
        return float(value) if value is not None else None

    @property
    def coverage(self) -> float | None:
        value = self.semantic.get("coverage")
        return float(value) if value is not None else None

    @property
    def snapshot(self) -> str:
        return (self.old.snapshot_timestamp or "") if self.old else ""

    @property
    def findings(self) -> list[dict[str, Any]]:
        """Structural and semantic findings together, worst first."""
        order = {"high": 3, "medium": 2, "low": 1, "info": 0}
        both = (self.structural.get("findings", [])
                + self.semantic.get("findings", []))
        return sorted(both, key=lambda f: -order.get(f.get("severity", "info"), 0))

    @property
    def passages(self) -> list[dict[str, Any]]:
        return self.semantic.get("passages", [])

    @property
    def judged(self) -> bool:
        return bool(self.judge.get("judged"))

    @property
    def judge_summary(self) -> str:
        return self.judge.get("summary", "")

    @property
    def facts_lost(self) -> list[dict[str, Any]]:
        """Passages the judge found a specific claim missing from."""
        return [p for p in self.judge.get("passages", [])
                if p.get("verdict") == "facts_lost"]

    @property
    def counts(self) -> dict[str, list[int]]:
        return self.structural.get("counts", {})

    # --- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "old_url": self.old_url,
            "new_url": self.new_url,
            "label": self.label,
            "compared_at": self.compared_at,
            "problems": self.problems,
            "risk": self.risk,
            "structural": self.structural,
            "semantic": self.semantic,
            "judge": self.judge,
            "old": self.old.to_dict() if self.old else None,
            "new": self.new.to_dict() if self.new else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str = "") -> "PairResult":
        return cls(
            old_url=data.get("old_url", ""),
            new_url=data.get("new_url", ""),
            label=data.get("label", ""),
            compared_at=data.get("compared_at", ""),
            problems=data.get("problems") or [],
            old=PageContent.from_dict(data["old"]) if data.get("old") else None,
            new=PageContent.from_dict(data["new"]) if data.get("new") else None,
            risk=data.get("risk") or {},
            structural=data.get("structural") or {},
            semantic=data.get("semantic") or {},
            judge=data.get("judge") or {},
            schema_version=int(data.get("schema_version", 0)),
            path=path,
        )


# --------------------------------------------------------------------------
# reading and writing
# --------------------------------------------------------------------------

def build_result(spec, pair, structural=None, semantic=None, risk=None,
                 judge=None) -> PairResult:
    """Assemble the record the store persists, from the pipeline's objects."""
    result = PairResult(
        old_url=spec.old_url,
        new_url=spec.new_url,
        label=spec.label,
        compared_at=pair.compared_at,
        problems=list(pair.problems),
        old=pair.old,
        new=pair.new,
    )

    if risk is not None:
        result.risk = {
            "tier": risk.tier.label,
            "tier_rank": int(risk.tier),
            "score": risk.score,
            "loss": risk.loss,
            "change": risk.change,
            "confidence": risk.confidence,
            "reasons": risk.reasons,
            "caveats": risk.caveats,
        }

    if structural is not None:
        result.structural = {
            "worst": structural.worst.label,
            "is_clean": structural.is_clean,
            "counts": {k: list(v) for k, v in structural.counts.items()},
            "findings": _findings(structural.ranked()),
        }

    if semantic is not None:
        result.semantic = {
            "overall_similarity": round(semantic.overall_similarity, 4),
            "coverage": round(semantic.coverage, 4),
            "interpretation": semantic.interpretation(),
            "embedder": semantic.embedder,
            "notes": semantic.notes,
            "findings": _findings(semantic.findings),
            # Passage-level detail, for the dashboard's document view and for
            # phase 6: the judge reads the reworded ones, where a threshold
            # cannot tell a faithful rewrite from one that dropped a fact.
            # kind/items/columns carry the block's shape through so a list
            # stays a list and a table stays a table on the review screen,
            # instead of flattening to text indistinguishable from a paragraph.
            "passages": [
                {"section": m.old.section,
                 "kind": m.old.kind,
                 "ordered": m.old.ordered,
                 "columns": m.old.columns,
                 "items_old": m.old.items,
                 "items_new": (m.new.items if m.new else []),
                 "old_text": m.old.text,
                 "new_text": m.new.text if m.new else None,
                 "new_section": m.new.section if m.new else None,
                 # Position of the matched chunk among the new page's own
                 # content blocks -- the new-side document is rendered in the
                 # new page's own order, not the old page's, so this is what
                 # places a matched passage where it actually sits over there.
                 "new_index": m.new.index if m.new else None,
                 "similarity": round(m.similarity, 4),
                 "verdict": ("dropped" if m.is_dropped
                             else "reworded" if m.is_reworded else "kept")}
                for m in semantic.matches
            ],
            # New-page blocks no old block claimed. Every content block on the
            # new side ends up in exactly one of `passages` (by new_index) or
            # here -- match_chunks partitions new_chunks that way -- so the two
            # together are enough to render the new page as a whole document.
            "added": [
                {"index": c.index, "section": c.section, "kind": c.kind,
                 "ordered": c.ordered, "columns": c.columns, "items": c.items,
                 "text": c.text}
                for c in semantic.added
            ],
        }

    if judge is not None:
        result.judge = judge.to_dict()
    return result


def _findings(findings) -> list[dict[str, Any]]:
    return [{"kind": f.kind, "severity": f.severity.label,
             "summary": f.summary, "items": f.items} for f in findings]


def save_result(out_dir: str | Path, result: PairResult) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / result_filename(
        result.old_url, result.new_url,
        discriminator=f"{result.snapshot}|{result.label}")
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")
    result.path = str(path)
    return path


def load_results(directory: str | Path) -> list[PairResult]:
    """Read every record in a directory, worst first.

    Unreadable files are skipped rather than raising: a half-written record
    from an interrupted run should not stop a reviewer seeing the rest.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    results: list[PairResult] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "new_url" not in data:
            continue     # not one of ours; the folder may hold other JSON
        results.append(PairResult.from_dict(data, path=str(path)))

    return sorted(results, key=lambda r: (-r.tier_rank, -r.score))


def tally(results: list[PairResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.tier] = counts.get(result.tier, 0) + 1
    return counts


# --------------------------------------------------------------------------
# the discovery record
# --------------------------------------------------------------------------

DISCOVERY_FILE = "discovery.json"


@dataclass
class Discovery:
    """What crawling both sites found, independent of any content comparison.

    Kept beside the per-pair records because its headline -- pages with no
    counterpart at all -- is the one finding the content comparison cannot
    produce. A page that does not exist has nothing to compare, so it would
    otherwise never reach the dashboard at all.
    """

    old_root: str = ""
    new_root: str = ""
    discovered_at: str = ""
    matched: int = 0
    old_total: int = 0
    new_total: int = 0
    label_signals: list[str] = field(default_factory=list)
    # Every pair discovery found, not only the ones whose content was later
    # compared. The redirect map is independent of risk scoring, and capping
    # the comparison must not silently shorten it.
    matched_pairs: list[dict[str, Any]] = field(default_factory=list)
    not_migrated: list[dict[str, Any]] = field(default_factory=list)
    net_new: list[dict[str, Any]] = field(default_factory=list)
    unreachable_old: list[dict[str, Any]] = field(default_factory=list)
    unreachable_new: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @property
    def migrated_share(self) -> float:
        total = self.matched + len(self.not_migrated)
        return self.matched / total if total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "discovery",
            "old_root": self.old_root,
            "new_root": self.new_root,
            "discovered_at": self.discovered_at,
            "matched": self.matched,
            "old_total": self.old_total,
            "new_total": self.new_total,
            "label_signals": self.label_signals,
            "matched_pairs": self.matched_pairs,
            "not_migrated": self.not_migrated,
            "net_new": self.net_new,
            "unreachable_old": self.unreachable_old,
            "unreachable_new": self.unreachable_new,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Discovery":
        return cls(
            old_root=data.get("old_root", ""),
            new_root=data.get("new_root", ""),
            discovered_at=data.get("discovered_at", ""),
            matched=int(data.get("matched", 0)),
            old_total=int(data.get("old_total", 0)),
            new_total=int(data.get("new_total", 0)),
            label_signals=data.get("label_signals") or [],
            matched_pairs=data.get("matched_pairs") or [],
            not_migrated=data.get("not_migrated") or [],
            net_new=data.get("net_new") or [],
            unreachable_old=data.get("unreachable_old") or [],
            unreachable_new=data.get("unreachable_new") or [],
            schema_version=int(data.get("schema_version", 0)),
        )


def save_discovery(out_dir: str | Path, discovery: Discovery) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / DISCOVERY_FILE
    path.write_text(json.dumps(discovery.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_discovery(directory: str | Path) -> Discovery | None:
    """Read the discovery record, looking one level up as well.

    Discovery and comparison are separate runs and people point them at
    neighbouring folders; finding it either way beats making a reviewer notice
    that a whole section of the report is silently absent.
    """
    directory = Path(directory)
    for candidate in (directory / DISCOVERY_FILE,
                      directory.parent / DISCOVERY_FILE):
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("kind") == "discovery":
            return Discovery.from_dict(data)
    return None


def clear_results(directory: str | Path) -> int:
    """Remove the records of a previous run, leaving anything else alone.

    A run writes one file per pair, named by the pair's URLs. Without this, a
    second run over different sites *adds* to the folder instead of replacing
    it, and the dashboard shows the two comparisons mixed together -- rows from
    a migration nobody is looking at any more, beside a discovery record that
    describes different sites entirely.

    Only files this module wrote are removed: a folder may hold notes, CSVs, or
    someone else's data, and a results writer has no business deleting those.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return 0

    removed = 0
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        ours = ("new_url" in data or data.get("kind") == "discovery"
                or "totals" in data and "pages" in data)
        if not ours:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
