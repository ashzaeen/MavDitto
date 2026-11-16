"""Check that the risk tiers actually discriminate, on graded damage.

Real page pairs are a poor calibration set for the middle tiers. Comparing a
page to its own latest capture gives an identical pair, and comparing it to a
capture from years ago gives a wholesale rewrite; almost nothing lands in
between, so "Minor rewording" and "Major rewording" never get exercised.

So this takes one page and damages it by degrees, in two separate series:

* **rewording** -- the text is rephrased more and more heavily, but every fact
  is kept. However far this goes it must never reach Missing content.
* **removal** -- progressively more content is deleted. This must climb into
  Missing content and must never go *down* as more is removed.

    python -m src.tune_score
    python -m src.tune_score --page https://www.uta.edu/about

A failure here means the weights in `score.py` need revisiting, not that the
page is interesting.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace

from .diff_semantic import diff_semantic
from .diff_structural import diff_structural
from .embed import LocalEmbedder
from .models import Image, Link, PageContent
from .pair import PagePair, PairSpec
from .score import RiskTier, score_pair

# Deterministic rewording, so a run is reproducible and needs no model to
# generate. Applied in prefix order, so each level includes the ones before it.
SYNONYMS = [
    (r"\bmust\b", "are required to"),
    (r"\bsubmit\b", "provide"),
    (r"\bapplicants\b", "candidates"),
    (r"\brequired\b", "necessary"),
    (r"\boffers\b", "provides"),
    (r"\bstudents\b", "learners"),
    (r"\bprograms\b", "courses of study"),
    (r"\buniversity\b", "institution"),
    (r"\bacademic\b", "scholarly"),
    (r"\bresearch\b", "scholarly investigation"),
    (r"\bcampus\b", "grounds"),
    (r"\bdegree\b", "qualification"),
]

FILLER = (" This information is provided to help you plan ahead, and we "
          "encourage you to reach out with any questions you may have.")


def _apply(text: str, level: int) -> str:
    for pattern, replacement in SYNONYMS[: level * 4]:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def reword(page: PageContent, level: int) -> PageContent:
    """Rephrase without dropping anything. level 0 is untouched."""
    text = _apply(page.text, level)
    headings = [replace(h, text=_apply(h.text, level)) for h in page.headings]
    if level >= 3:
        # Heaviest level also pads each block, the way a tone rewrite does.
        text = "\n".join(
            line + FILLER if len(line.split()) > 12 else line
            for line in text.splitlines())
    # The URL stays put: these variants stand for the same page after a
    # rewrite, and moving the site root would make every internal link
    # compare as dropped even on an untouched copy.
    return replace(page, text=text, headings=headings)


def remove_text(page: PageContent, keep_fraction: float) -> PageContent:
    """Delete whole blocks from the end, keeping the given share of them."""
    lines = [l for l in page.text.splitlines() if l.strip()]
    keep = max(1, int(len(lines) * keep_fraction))
    kept = lines[:keep]
    kept_keys = {" ".join(l.lower().split()) for l in kept}
    return replace(
        page,
        text="\n".join(kept),
        headings=[h for h in page.headings
                  if " ".join(h.text.lower().split()) in kept_keys],
    )


def drop_documents(page: PageContent) -> PageContent:
    return replace(page, links=[l for l in page.links if not l.is_document])


def drop_images(page: PageContent) -> PageContent:
    return replace(page, images=[])


def evaluate(old: PageContent, new: PageContent, embedder):
    pair = PagePair(spec=PairSpec(old.url, new.url), old=old, new=new)
    structural = diff_structural(old, new)
    semantic = diff_semantic(old, new, embedder)
    return score_pair(pair, structural, semantic), semantic


def _sample_page() -> PageContent:
    """A realistic multi-section page, built offline."""
    from .extract import extract

    html = """
    <html><head><title>Undergraduate Admissions</title></head><body><main>
      <h1>Undergraduate Admissions</h1>
      <p>Applications for the fall semester are due by March 1. The application
         fee is $75 and is non-refundable once submitted to the university.</p>
      <h2>Requirements</h2>
      <p>Freshman applicants must submit official high school transcripts and
         demonstrate a minimum 3.0 grade point average on a four point scale.</p>
      <h2>Transfer students</h2>
      <p>Transfer applicants need at least 24 completed credit hours from a
         regionally accredited institution before they may be considered.</p>
      <h2>Deadlines</h2>
      <p>Priority consideration closes on February 15 for scholarship review,
         and late applications are considered only if space remains available.</p>
      <h2>Financial aid</h2>
      <p>Students should file the federal aid application by January 15 to be
         considered for need based grants administered by the university.</p>
      <h2>Contact</h2>
      <p>The admissions office is open weekdays from eight in the morning until
         five in the afternoon, and can be reached by telephone or email.</p>
      <img src="/img/campus.jpg" alt="Students on the campus lawn">
      <a href="/docs/checklist.pdf">Application checklist (PDF)</a>
      <a href="/tuition">Tuition and fees</a>
    </main></body></html>
    """
    return extract(html, "https://old.uta.edu/admissions")


def _fetch_page(url: str) -> PageContent:
    from .fetch import Fetcher
    from .extract import extract_fetch_result

    with Fetcher() as fetcher:
        page = extract_fetch_result(fetcher.fetch(url))
    if page.status != 200 or page.word_count < 80:
        raise SystemExit(f"{url}: not enough text to perturb "
                         f"(HTTP {page.status}, {page.word_count} words)")
    return replace(page, url="https://old.uta.edu/sample")


def run(page: PageContent, embedder) -> int:
    print(f"base page: {page.word_count} words, {len(page.headings)} headings, "
          f"{len(page.images)} images, {len(page.links)} links\n")

    header = f"{'variant':<34}{'cover':>6}{'sim':>6}  {'tier':<17}{'score':>6}{'loss':>7}{'chg':>7}"
    failures: list[str] = []

    print("REWORDING -- facts kept; must never reach Missing content")
    print(header)
    print("-" * 79)
    for level, name in enumerate(
            ["identical", "light rewording", "moderate rewording",
             "heavy rewording + padding"]):
        risk, semantic = evaluate(page, reword(page, level), embedder)
        print(f"{name:<34}{semantic.coverage:>6.2f}{semantic.overall_similarity:>6.2f}  "
              f"{risk.tier.label:<17}{risk.score:>6}{risk.loss:>7}{risk.change:>7}")
        if risk.tier is RiskTier.MISSING:
            failures.append(f"{name!r} was scored Missing content, but nothing was removed")
        if level == 0 and risk.tier is not RiskTier.CLEAN:
            failures.append(f"an identical page scored {risk.tier.label}")

    print("\nREMOVAL -- content deleted; must climb and never fall")
    print(header)
    print("-" * 79)
    removal = [
        ("one image removed", drop_images(page)),
        ("PDF link removed", drop_documents(page)),
        ("one sixth of the text removed", remove_text(page, 0.83)),
        ("a third of the text removed", remove_text(page, 0.67)),
        ("half the text removed", remove_text(page, 0.5)),
        ("all but the first section", remove_text(page, 0.17)),
    ]
    previous_tier, previous_name = None, ""
    for name, damaged in removal:
        risk, semantic = evaluate(page, damaged, embedder)
        print(f"{name:<34}{semantic.coverage:>6.2f}{semantic.overall_similarity:>6.2f}  "
              f"{risk.tier.label:<17}{risk.score:>6}{risk.loss:>7}{risk.change:>7}")
        if name.endswith("text removed") or name.startswith("all but"):
            if previous_tier is not None and risk.tier < previous_tier:
                failures.append(
                    f"{name!r} scored {risk.tier.label}, below {previous_name!r} "
                    f"at {previous_tier.label} -- more damage must not score better")
            previous_tier, previous_name = risk.tier, name

    worst, _ = evaluate(page, remove_text(page, 0.17), embedder)
    if worst.tier is not RiskTier.MISSING:
        failures.append(f"removing all but one section scored {worst.tier.label}, "
                        "not Missing content")

    print()
    if failures:
        print("FAILED:")
        for problem in failures:
            print(f"  - {problem}")
        return 1
    print("tiers discriminate correctly on both series")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.tune_score")
    ap.add_argument("--page", default="",
                    help="fetch a real page to perturb instead of the built-in sample")
    args = ap.parse_args(argv)
    page = _fetch_page(args.page) if args.page else _sample_page()
    return run(page, LocalEmbedder())


if __name__ == "__main__":
    sys.exit(main())
