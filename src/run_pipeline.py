"""One call that takes two URLs and produces a finished results folder.

    python -m src.run_pipeline --old OLD --new NEW --out data/run

Everything the CLIs do in three steps -- discover, compare, export -- behind a
single function with progress callbacks, so a GUI can offer "paste two URLs and
go" without reimplementing the pipeline or shelling out to itself.

Progress is reported rather than printed, because the caller decides where it
goes: a terminal, a Streamlit status panel, or a polled HTTP endpoint.

A run is minutes of network work, so it is cancellable and every stage is
capped. Nothing here assumes a terminal is attached.
"""

from __future__ import annotations

import argparse
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .diff_semantic import diff_semantic
from .diff_structural import diff_structural
from .discover import check_reachable, discover, match_by_title, match_sites
from .embed import get_embedder
from .fetch import Fetcher
from .models import utcnow_iso
from .pair import PairSpec, fetch_pair, write_pairs_csv
from .score import score_pair
from .store import (
    Discovery, build_result, clear_results, save_discovery, save_result,
)

# Stages, in order, so a GUI can render a step indicator without knowing the
# pipeline's internals.
STAGES = ("crawling old site", "crawling new site", "pairing pages",
          "comparing content", "exporting")

# Floors applied when deep_crawl is on, so ticking one checkbox in a GUI that
# has no depth field still gets a crawl deep enough to matter. A caller who
# asked for something even larger keeps what they asked for -- these only ever
# raise the effective cap, never lower it.
DEEP_MIN_PAGES = 1000
DEEP_MIN_DEPTH = 10


@dataclass
class Progress:
    stage: str = ""
    message: str = ""
    done: int = 0
    total: int = 0
    finished: bool = False
    failed: bool = False
    error: str = ""

    # Filled in as they become known, so a GUI can show real numbers while the
    # run is still going.
    old_pages: int = 0
    new_pages: int = 0
    matched: int = 0
    not_migrated: int = 0
    compared: int = 0

    @property
    def fraction(self) -> float:
        if self.finished:
            return 1.0
        if not self.total:
            return 0.0
        return min(1.0, self.done / self.total)


@dataclass
class RunOptions:
    """Everything a caller might reasonably want to limit or allow."""

    max_pages: int = 200
    max_depth: int = 4
    use_sitemap: bool = True
    check_live: bool = True
    match_titles: bool = True
    # robots.txt is not consulted unless asked for; see RobotsCache.
    respect_robots: bool = False
    delay_s: float = 0.4
    # Merge sitemap and crawl instead of trusting whichever answers first,
    # follow nested sitemaps further, retry pages that failed once, and render
    # JS for pages whose static HTML looks empty. See discover()/crawl(). Also
    # raises the effective page/depth caps below the ones asked for, because
    # the GUI does not expose a depth control at all and "thorough" implied by
    # this flag should not be capped by whatever the quick-run defaults are.
    deep_crawl: bool = False
    # Comparing content is the slow half; a GUI run is usually exploratory, so
    # it stops at a sane number of pairs unless told otherwise.
    max_pairs: int = 50
    semantic: bool = True
    embedder: str = "local"
    # Reading pages with the LLM judge. Off by default because it costs money;
    # the budget is enforced before each call, so it cannot overrun.
    judge: bool = False
    judge_model: str = "claude-opus-5"
    judge_budget_usd: float = 1.0


@dataclass
class RunResult:
    out_dir: Path
    old_root: str = ""
    new_root: str = ""
    old_pages: int = 0
    new_pages: int = 0
    matched: int = 0
    not_migrated: int = 0
    compared: int = 0
    tiers: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    finished_at: str = ""


class Cancelled(RuntimeError):
    """Raised inside a run when the caller asked it to stop."""


ProgressFn = Callable[[Progress], None]


def effective_crawl_caps(options: RunOptions) -> tuple[int, int]:
    """(max_pages, max_depth) actually handed to discover(), floors applied.

    Pulled out so deep_crawl's effect on the caps can be asserted directly,
    without spinning up a real crawl to observe it.
    """
    pages, depth = options.max_pages, options.max_depth
    if options.deep_crawl:
        pages = max(pages, DEEP_MIN_PAGES)
        depth = max(depth, DEEP_MIN_DEPTH)
    return pages, depth


def run(old_url: str, new_url: str, out_dir: str | Path, *,
        options: RunOptions | None = None,
        on_progress: ProgressFn | None = None,
        cancel: threading.Event | None = None) -> RunResult:
    """Crawl both sites, pair their pages, compare the pairs, export the lot.

    `cancel` is checked between pages rather than only between stages: a run is
    minutes of network work, and a stop button that does nothing until the
    current stage ends is not a stop button.
    """
    options = options or RunOptions()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # A run replaces the folder's contents rather than adding to them. Without
    # this, comparing a second pair of sites leaves the first run's pages in
    # the table beside a discovery record describing different sites.
    cleared = clear_results(out)

    progress = Progress()

    def report(**changes) -> None:
        for key, value in changes.items():
            setattr(progress, key, value)
        if on_progress is not None:
            on_progress(progress)

    def check_cancelled() -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled("stopped")

    result = RunResult(out_dir=out)
    if cleared:
        result.notes.append(f"replaced {cleared} record(s) from a previous run")

    crawl_pages, crawl_depth = effective_crawl_caps(options)

    with Fetcher(delay_s=options.delay_s) as fetcher:
        # --- enumerate both sides ---------------------------------------
        report(stage=STAGES[0], message=f"reading {old_url}", done=0, total=5)
        check_cancelled()
        old_site = discover(old_url, fetcher, max_pages=crawl_pages,
                            max_depth=crawl_depth,
                            use_sitemap=options.use_sitemap,
                            respect_robots=options.respect_robots,
                            deep=options.deep_crawl)
        _require_pages(old_site, old_url, "old")

        report(stage=STAGES[1], message=f"reading {new_url}", done=1,
               old_pages=len(old_site))
        check_cancelled()
        new_site = discover(new_url, fetcher, max_pages=crawl_pages,
                            max_depth=crawl_depth,
                            use_sitemap=options.use_sitemap,
                            respect_robots=options.respect_robots,
                            deep=options.deep_crawl)

        # Checked for both sides. A new site that yielded nothing turns every
        # old page into "not migrated" -- a confident, wrong report that reads
        # as a catastrophic migration when the truth is that nobody could read
        # the new site.
        _require_pages(new_site, new_url, "new")

        if options.check_live:
            report(message="checking every listed page responds")
            check_cancelled()
            check_reachable(old_site, fetcher,
                            respect_robots=options.respect_robots)
            check_reachable(new_site, fetcher,
                            respect_robots=options.respect_robots)

        # --- pair them ---------------------------------------------------
        report(stage=STAGES[2], message="matching old pages to new ones", done=2,
               old_pages=len(old_site), new_pages=len(new_site))
        check_cancelled()
        match = match_sites(old_site, new_site)
        if options.match_titles:
            report(message="matching the leftovers by name")
            match_by_title(
                match, fetcher,
                respect_robots=options.respect_robots)

        specs = [
            PairSpec(old_url=p.old.url, new_url=p.new.url,
                     old_root=old_site.root, new_root=new_site.root,
                     label=p.old.path)
            for p in match.pairs
        ]
        write_pairs_csv(specs, out / "url_pairs.csv")

        def rows(pages):
            return [{"path": p.path, "url": p.url, "title": p.title} for p in pages]

        # Saved before any content is compared, so the answer a content diff
        # cannot produce -- pages with no counterpart -- is on disk even if the
        # comparison is cancelled or fails.
        save_discovery(out, Discovery(
            old_root=old_site.root, new_root=new_site.root,
            discovered_at=utcnow_iso(),
            matched=len(match.pairs),
            old_total=len(old_site) + len(old_site.unreachable),
            new_total=len(new_site) + len(new_site.unreachable),
            label_signals=list(match.label_signals),
            matched_pairs=[
                {"path": p.old.path, "oldUrl": p.old.url, "newUrl": p.new.url,
                 "method": p.method, "confidence": p.confidence}
                for p in match.pairs
            ],
            not_migrated=rows(match.unmatched_old),
            net_new=rows(match.unmatched_new),
            unreachable_old=rows(old_site.unreachable + match.unreachable_old),
            unreachable_new=rows(new_site.unreachable + match.unreachable_new),
        ))

        result.old_root, result.new_root = old_site.root, new_site.root
        result.old_pages, result.new_pages = len(old_site), len(new_site)
        result.matched = len(match.pairs)
        result.not_migrated = len(match.unmatched_old)
        report(matched=result.matched, not_migrated=result.not_migrated)

        # --- compare the pairs -------------------------------------------
        capped = specs[: options.max_pairs]
        if len(specs) > len(capped):
            result.notes.append(
                f"compared the first {len(capped)} of {len(specs)} matched pairs; "
                "raise the pair cap to do the rest")

        embedder = get_embedder(options.embedder) if options.semantic else None
        judge = None
        if options.judge:
            from .llm_judge import Budget, Judge
            judge = Judge(model=options.judge_model,
                          budget=Budget(max_usd=options.judge_budget_usd))
        tiers: dict[str, int] = {}

        for index, spec in enumerate(capped, start=1):
            check_cancelled()
            report(stage=STAGES[3],
                   message=f"comparing {spec.label or spec.new_url}",
                   done=2 + index / max(len(capped), 1) * 2,
                   total=5, compared=index - 1)

            pair = fetch_pair(fetcher, spec,
                              respect_robots=options.respect_robots)
            structural = semantic = None
            if not pair.problems:
                structural = diff_structural(pair.old, pair.new,
                                             old_root=spec.old_root,
                                             new_root=spec.new_root)
                if embedder is not None:
                    semantic = diff_semantic(pair.old, pair.new, embedder)
            risk = score_pair(pair, structural, semantic)
            tiers[risk.tier.label] = tiers.get(risk.tier.label, 0) + 1

            record = build_result(spec, pair, structural, semantic, risk)
            if judge is not None and record.semantic.get("passages"):
                from .llm_judge import should_judge
                if should_judge(risk.tier.label, record.semantic):
                    verdict = judge.judge_page(record.semantic["passages"],
                                               title=record.title)
                    record.judge = verdict.to_dict()
            save_result(out, record)

        result.compared = len(capped)
        result.tiers = tiers
        if judge is not None:
            result.notes.append(f"judge: {judge.budget.summary(noun='judge call')}")

    # --- export -----------------------------------------------------------
    report(stage=STAGES[4], message="writing the dashboard data", done=4, total=5,
           compared=result.compared)
    _export(out)

    result.finished_at = utcnow_iso()
    report(stage="done", message="finished", done=5, total=5, finished=True)
    return result


def _require_pages(site, url: str, side: str) -> None:
    """Refuse to continue on a side we could not read.

    Reporting "0 matched" for a site that refused every request is worse than
    failing: it looks like an answer. The message names the cause and the fix,
    because "no pages found" alone sends someone hunting through a crawler.
    """
    if site.pages:
        return

    if site.blocked:
        raise RuntimeError(
            f"{url} refused every request because its robots.txt disallows "
            f"crawling ({site.blocked} page(s) blocked), and this run was told "
            f"to respect it. Turn off 'respect robots.txt' for the {side} site "
            "if it is yours to check.")

    if site.unreachable:
        raise RuntimeError(
            f"{url} listed {len(site.unreachable)} page(s) but served none of "
            "them. The site may be slow to respond, behind a login, or down.")

    raise RuntimeError(
        f"no pages found under {url}. If it publishes no sitemap, the crawler "
        "follows links from that exact URL -- check the root is right, and "
        "raise the page cap if the site is large.")


def _export(out: Path) -> None:
    """Refresh the React app's JSON, if that dashboard is present."""
    from .export_web import build_payload
    from .store import load_discovery, load_results
    import json

    payload = build_payload(load_results(out), load_discovery(out))
    (out / "web.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    web = Path(__file__).resolve().parent.parent / "dashboard-react" / "public"
    if web.is_dir():
        (web / "data.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# running one in the background
# --------------------------------------------------------------------------

class BackgroundRun:
    """A run on its own thread, with progress a GUI can poll.

    Both dashboards need the same thing: start a run, keep drawing, ask how it
    is going, and be able to stop it. Neither should block its event loop for
    the minutes a crawl takes.
    """

    def __init__(self, old_url: str, new_url: str, out_dir: str | Path,
                 options: RunOptions | None = None):
        self.old_url = old_url
        self.new_url = new_url
        self.out_dir = Path(out_dir)
        self.options = options or RunOptions()
        self.progress = Progress(stage="starting", message="queued")
        self.result: RunResult | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> "BackgroundRun":
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()
        return self

    def _work(self) -> None:
        def on_progress(progress: Progress) -> None:
            # Copied under the lock: the reader is another thread, and handing
            # it the live object would let it observe a half-updated state.
            with self._lock:
                self.progress = Progress(**vars(progress))

        try:
            self.result = run(self.old_url, self.new_url, self.out_dir,
                              options=self.options, on_progress=on_progress,
                              cancel=self._cancel)
        except Cancelled:
            with self._lock:
                self.progress = Progress(stage="stopped", message="stopped",
                                         finished=True, failed=True,
                                         error="stopped before finishing")
        except Exception as exc:
            with self._lock:
                self.progress = Progress(
                    stage="failed", message=str(exc), finished=True, failed=True,
                    error=f"{type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)

    def snapshot(self) -> Progress:
        with self._lock:
            return Progress(**vars(self.progress))

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.run_pipeline",
        description="Crawl two sites, pair their pages, compare them, and write "
                    "everything both dashboards read.")
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", default="data/run", metavar="DIR")
    ap.add_argument("--max-pages", type=int, default=RunOptions.max_pages)
    ap.add_argument("--max-pairs", type=int, default=RunOptions.max_pairs)
    ap.add_argument("--no-semantic", action="store_true")
    ap.add_argument("--no-check-live", action="store_true")
    ap.add_argument("--no-match-titles", action="store_true")
    ap.add_argument("--judge", action="store_true",
                    help="read flagged pages with the LLM judge (costs money)")
    ap.add_argument("--judge-budget", type=float, default=1.0, metavar="USD")
    ap.add_argument("--deep", action="store_true",
                    help="crawl exhaustively: merge sitemap and crawl results "
                         "instead of trusting one, follow pagination/alternate/"
                         "embedded links, retry pages that failed once, render "
                         "JS for pages that look like empty shells, and raise "
                         f"the page/depth caps to at least {DEEP_MIN_PAGES}/"
                         f"{DEEP_MIN_DEPTH}. Slower.")
    ap.add_argument("--respect-robots", action="store_true",
                    help="consult robots.txt before fetching. Off by default: "
                         "staging and preview hosts serve Disallow: / to stay "
                         "out of search results, not to refuse their owner")
    ap.add_argument("--delay", type=float, default=RunOptions.delay_s)
    args = ap.parse_args(argv)

    options = RunOptions(
        max_pages=args.max_pages, max_pairs=args.max_pairs,
        semantic=not args.no_semantic, check_live=not args.no_check_live,
        match_titles=not args.no_match_titles,
        respect_robots=args.respect_robots, delay_s=args.delay,
        judge=args.judge, judge_budget_usd=args.judge_budget,
        deep_crawl=args.deep)

    last = [""]

    def show(progress: Progress) -> None:
        line = f"[{progress.stage}] {progress.message}"
        if line != last[0]:
            print(line, flush=True)
            last[0] = line

    try:
        result = run(args.old, args.new, args.out, options=options,
                     on_progress=show)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    print(f"\n{result.old_pages} old page(s), {result.new_pages} new, "
          f"{result.matched} matched, {result.not_migrated} with no counterpart")
    print(f"{result.compared} pair(s) compared: "
          + ", ".join(f"{n} {t.lower()}" for t, n in sorted(result.tiers.items())))
    for note in result.notes:
        print(f"  note: {note}")
    print(f"\nresults in {result.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
