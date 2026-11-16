"""Old/new page pairs -- the unit everything from phase 2 onward compares.

Three ways a pair's two sides can be sourced, and all of them are ordinary:

* **Both live.** The usual pre-launch check: the old site is still serving
  users while the new one is built, and someone verifies the rebuild before the
  cutover. Nothing is archived yet because nothing has been retired yet.
* **Old from Wayback.** The post-hoc audit, after the old site is already gone.
* **Mixed.** Old site partly retired, or a particular page pulled early.

So the source is a property of each *side*, not of the run. A pair carries its
own provenance and every later stage reads it from there.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .extract import extract_fetch_result
from .fetch import Fetcher
from .models import PageContent, utcnow_iso

VALID_SOURCES = ("live", "wayback", "auto")

# Below this, a page carries too little text for ratios to mean anything.
THIN_PAGE_WORDS = 50


@dataclass
class PairSpec:
    """What to fetch for one pair, before anything has been fetched."""

    old_url: str
    new_url: str
    old_source: str = "live"
    new_source: str = "live"
    timestamp: str = ""          # preferred Wayback capture for the old side
    label: str = ""              # optional human name for the pair
    # Site roots, so internal links can be compared relative to their own site.
    # Default to each page's scheme+host, which is right for a host-to-host
    # move; set them for a subsite move under a single host.
    old_root: str = ""
    new_root: str = ""

    def __post_init__(self) -> None:
        for name, value in (("old_source", self.old_source),
                            ("new_source", self.new_source)):
            if value not in VALID_SOURCES:
                raise ValueError(
                    f"{name}={value!r} is not one of {VALID_SOURCES}"
                )


@dataclass
class PagePair:
    """Both sides of one comparison, normalized and ready to diff."""

    spec: PairSpec
    old: PageContent
    new: PageContent
    compared_at: str = field(default_factory=utcnow_iso)

    @property
    def both_ok(self) -> bool:
        return self.old.status == 200 and self.new.status == 200

    @property
    def problems(self) -> list[str]:
        """Reasons this pair cannot be compared at all.

        Kept separate from the diff itself: a pair that failed to fetch is not
        a page that lost content, and conflating the two would put fetch errors
        at the top of a risk ranking where real content loss belongs.

        Deliberately asymmetric on thin pages. A thin *old* page leaves nothing
        to compare against, so it blocks. A thin *new* page beside a substantial
        old one is the finding this tool exists to make -- the page was gutted --
        so it scores normally and raises a warning instead. Treating it as
        uncompareable suppressed the worst result in the set.
        """
        out: list[str] = []
        for side, page in (("old", self.old), ("new", self.new)):
            if page.status != 200:
                out.append(f"{side} page returned HTTP {page.status}")
        if self.old.status == 200 and self.old.word_count < THIN_PAGE_WORDS:
            out.append(f"old page yielded only {self.old.word_count} words, "
                       "so there is nothing to compare against")
        return out

    @property
    def warnings(self) -> list[str]:
        """Things that weaken a comparison without preventing it."""
        out: list[str] = []
        if (self.new.status == 200 and self.new.word_count < THIN_PAGE_WORDS
                and self.old.word_count >= THIN_PAGE_WORDS):
            out.append(
                f"new page yielded only {self.new.word_count} words against the "
                f"old page's {self.old.word_count} -- scored as loss, but check "
                "it is not a rendering failure")
        return out


def fetch_pair(fetcher: Fetcher, spec: PairSpec, *, render: str = "auto",
               respect_robots: bool | None = None) -> PagePair:
    """Fetch and normalize both sides of one pair.

    `respect_robots` overrides the fetcher's own setting for this pair; None
    leaves it alone. The fetcher does not consult robots.txt by default -- see
    RobotsCache for why -- so this is here for callers that want it back on.
    """
    old_raw = fetcher.fetch(
        spec.old_url, source=spec.old_source, render=render,
        timestamp=spec.timestamp, respect_robots=respect_robots,
    )
    new_raw = fetcher.fetch(
        spec.new_url, source=spec.new_source, render=render,
        respect_robots=respect_robots,
    )
    return PagePair(
        spec=spec,
        old=extract_fetch_result(old_raw),
        new=extract_fetch_result(new_raw),
    )


def fetch_pairs(fetcher: Fetcher, specs: list[PairSpec], **kwargs) -> Iterator[PagePair]:
    for spec in specs:
        yield fetch_pair(fetcher, spec, **kwargs)


# --------------------------------------------------------------------------
# url_pairs.csv -- the standalone artifact the build plan calls for
# --------------------------------------------------------------------------

CSV_FIELDS = ("old_url", "new_url", "old_source", "new_source", "timestamp",
              "label", "old_root", "new_root")


def load_pairs_csv(path: str | Path) -> list[PairSpec]:
    """Read url_pairs.csv.

    Accepts both shapes: the plan's original `source` column (applied to the
    old side, since the new side is live by definition in that framing) and
    explicit `old_source`/`new_source` columns for the both-live case. Only
    old_url and new_url are required.
    """
    specs: list[PairSpec] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        # Drop # comment lines before the header is read; this file is meant to
        # be hand-edited, and DictReader would otherwise take a comment as the
        # column names. Line numbers in errors stay true to the real file.
        numbered = [(i, line) for i, line in enumerate(fh, start=1)
                    if line.strip() and not line.lstrip().startswith("#")]
        if not numbered:
            return specs
        line_numbers = [i for i, _ in numbered[1:]]
        reader = csv.DictReader([line for _, line in numbered])
        if not reader.fieldnames:
            return specs
        headers = {h.strip().lower() for h in reader.fieldnames}
        for missing in ("old_url", "new_url"):
            if missing not in headers:
                raise ValueError(f"{path}: missing required column {missing!r}")

        for row, row_no in zip(reader, line_numbers):
            row = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            if not row.get("old_url") or not row.get("new_url"):
                continue   # blank padding rows are common in hand-edited CSVs
            legacy = row.get("source", "")
            try:
                specs.append(PairSpec(
                    old_url=row["old_url"],
                    new_url=row["new_url"],
                    old_source=row.get("old_source") or legacy or "live",
                    new_source=row.get("new_source") or "live",
                    timestamp=row.get("timestamp", ""),
                    label=row.get("label", ""),
                    old_root=row.get("old_root", ""),
                    new_root=row.get("new_root", ""),
                ))
            except ValueError as exc:
                raise ValueError(f"{path} line {row_no}: {exc}") from exc
    return specs


def write_pairs_csv(specs: list[PairSpec], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for s in specs:
            writer.writerow({
                "old_url": s.old_url, "new_url": s.new_url,
                "old_source": s.old_source, "new_source": s.new_source,
                "timestamp": s.timestamp, "label": s.label,
                "old_root": s.old_root, "new_root": s.new_root,
            })
