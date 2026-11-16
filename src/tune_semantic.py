"""Print the similarity distribution the semantic thresholds are set from.

The thresholds in `diff_semantic` are judgement calls, and a judgement call
that nobody can re-check is a magic number. This prints the scores the real
model actually gives for each case the thresholds have to separate, so the
values can be re-derived after a model change instead of being trusted:

    python -m src.tune_semantic              # synthetic cases only, offline
    python -m src.tune_semantic --live       # adds the real UTA pairs

A good separation looks like a clear gap between the "same passage reworded"
scores and the "different passage" scores, with MATCH_STRONG and MATCH_WEAK
sitting inside that gap.
"""

from __future__ import annotations

import argparse
import sys

from .diff_semantic import MATCH_STRONG, MATCH_WEAK, diff_semantic
from .embed import LocalEmbedder, chunk_page
from .extract import extract

# Passage pairs whose correct verdict is known, covering the distinctions the
# thresholds must make. The fee and GPA cases are the ones that matter most:
# fluent rewrites that quietly drop a load-bearing fact.
CASES: list[tuple[str, str, str, str]] = [
    ("identical", "same",
     "Applications for the fall semester are due by March 1.",
     "Applications for the fall semester are due by March 1."),
    ("tone rewrite", "same",
     "Applications for the fall semester are due by March 1. The application "
     "fee is $75 and is non-refundable once submitted.",
     "Fall semester applications close on March 1. A non-refundable $75 "
     "application fee applies at submission."),
    ("heavy paraphrase", "same",
     "Freshman applicants must submit official high school transcripts and "
     "demonstrate a minimum 3.0 grade point average on a four point scale.",
     "To be considered as a first-year student you will need to send us your "
     "official transcripts from high school, and you must have earned at "
     "least a 3.0 GPA on a 4.0 scale."),
    ("reordered sentences", "same",
     "Applications close March 1. The fee is $75. Transcripts are required.",
     "Transcripts are required. The fee is $75. Applications close March 1."),
    ("expanded, same facts", "same",
     "Priority consideration closes on February 15 for scholarship review.",
     "The priority deadline for scholarship review is February 15, and we "
     "encourage applicants to submit well before that date."),
    ("fact dropped: fee", "loss",
     "Applications are due by March 1. The application fee is $75 and is "
     "non-refundable once submitted to the university.",
     "Applications are due by March 1. We look forward to reviewing your "
     "materials and welcoming you to our community soon."),
    ("fact dropped: gpa", "loss",
     "Freshman applicants must submit official high school transcripts and "
     "demonstrate a minimum 3.0 grade point average on a four point scale.",
     "Freshman applicants must submit official high school transcripts as "
     "part of a complete application package for review by our staff."),
    # A dropped requirement with no figure in it at all -- the case a bare
    # numeric check could never have caught, which is exactly why the judge
    # exists rather than a regex.
    ("requirement dropped: no figure", "loss",
     "Applicants must submit a letter of recommendation from a teacher and a "
     "personal essay describing their academic goals.",
     "Applicants must submit a personal essay describing their academic goals."),
    ("section replaced", "loss",
     "Priority consideration closes on February 15 for scholarship review.",
     "Our campus tour program runs every Friday throughout the spring."),
    ("unrelated", "loss",
     "Priority consideration closes on February 15 for scholarship review.",
     "The library extends its hours during final examination week."),
]


def _bar(score: float, width: int = 28) -> str:
    filled = max(0, min(width, round(score * width)))
    return "#" * filled + "." * (width - filled)


def run_cases(embedder) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    for name, verdict, old, new in CASES:
        vectors = embedder.encode([old, new])
        rows.append((name, verdict, float(vectors[0] @ vectors[1])))
    return rows


def report_cases(rows: list[tuple[str, str, float]]) -> None:
    width = max(22, max(len(name) for name, _, _ in rows) + 2)
    print(f"\n{'case':<{width}}{'truth':<7}{'score':>7}  distribution")
    print("-" * (width + 48))
    for name, verdict, score in rows:
        print(f"{name:<{width}}{verdict:<7}{score:>7.3f}  {_bar(score)}")

    same = [s for _, v, s in rows if v == "same"]
    loss = [s for _, v, s in rows if v == "loss"]
    print("-" * (width + 48))
    print(f"lowest 'same' score : {min(same):.3f}")
    print(f"highest 'loss' score: {max(loss):.3f}")
    gap = min(same) - max(loss)
    if gap > 0:
        print(f"separable           : yes, between {max(loss):.2f} and {min(same):.2f}")
    else:
        print(f"separable           : NO, classes overlap by {-gap:.3f}")
        print("  Cosine measures topical overlap, not factual completeness, so a")
        print("  faithful paraphrase and a rewrite that dropped a fact can score")
        print("  the same. No threshold fixes that -- the ambiguous band is made")
        print("  wide instead, and the LLM judge resolves what falls inside it.")

    print(f"\ncurrent: MATCH_STRONG={MATCH_STRONG}  MATCH_WEAK={MATCH_WEAK}")

    # The two errors cost very different things, so they are counted apart.
    # A loss scored as kept is silent and never reaches a reviewer. A same
    # scored as reworded only costs one LLM judge call.
    silent = [n for n, v, s in rows if v == "loss" and s >= MATCH_STRONG]
    costly = [n for n, v, s in rows if v == "same" and MATCH_WEAK <= s < MATCH_STRONG]
    wrong = [n for n, v, s in rows if v == "same" and s < MATCH_WEAK]

    print(f"  silently passed (loss read as kept):  "
          f"{', '.join(silent) if silent else 'none'}")
    print(f"  sent for review (same, needs judge):  "
          f"{', '.join(costly) if costly else 'none'}")
    print(f"  wrongly dropped (same read as gone):  "
          f"{', '.join(wrong) if wrong else 'none'}")


def report_live(embedder, limit: int = 6) -> None:
    from .fetch import Fetcher
    from .extract import extract_fetch_result

    pairs = [
        ("unchanged control", "https://uta.edu/academics", "live", "",
         "https://www.uta.edu/academics"),
        ("academics 2019 vs now", "http://www.uta.edu/academics/", "wayback",
         "20190820", "https://www.uta.edu/academics"),
    ]
    with Fetcher() as fetcher:
        for label, old_url, old_source, ts, new_url in pairs:
            old = extract_fetch_result(
                fetcher.fetch(old_url, source=old_source, timestamp=ts))
            new = extract_fetch_result(fetcher.fetch(new_url))
            if old.status != 200 or new.status != 200:
                print(f"\n{label}: could not fetch both sides")
                continue
            diff = diff_semantic(old, new, embedder)
            print(f"\n{label}")
            print(f"  chunks: {len(chunk_page(old))} old, {len(chunk_page(new))} new")
            print(f"  similarity {diff.overall_similarity:.3f}   "
                  f"coverage {diff.coverage:.3f}")
            print(f"  {diff.interpretation()}")
            for match in sorted(diff.matches, key=lambda m: m.similarity)[:limit]:
                verdict = "DROPPED " if match.is_dropped else (
                    "reworded" if match.is_reworded else "kept    ")
                print(f"    {match.similarity:.3f} {verdict} {match.old.preview(60)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.tune_semantic")
    ap.add_argument("--live", action="store_true",
                    help="also score the real UTA pairs (needs network)")
    ap.add_argument("--model", default="", help="override the model name")
    args = ap.parse_args(argv)

    embedder = LocalEmbedder(args.model) if args.model else LocalEmbedder()
    print(f"model: {embedder.model_name}")
    report_cases(run_cases(embedder))
    if args.live:
        report_live(embedder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
