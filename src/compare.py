"""Compare an old page against its replacement, side by side.

Covers the pre-launch check, where the old site is still serving users and the
new one is being built:

    python -m src.compare --old https://www.uta.edu/dept \
                          --new https://new.uta.edu/dept

The old side can equally come from the archive, for an audit after the old site
is gone:

    python -m src.compare --old http://www.uta.edu/dept/ --old-source wayback \
                          --new https://www.uta.edu/dept

Or a whole batch from the plan's url_pairs.csv:

    python -m src.compare --pairs data/url_pairs.csv

Each pair gets a count table, the structural and semantic findings, and a risk
tier with the reasoning that produced it. The run ends with every page ranked
worst first.

`--out DIR` writes one record per pair to the results store, which is what the
dashboard reads:

    python -m src.compare --pairs data/url_pairs.csv --out data/out
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .fetch import Fetcher
from .models import PageContent
from .diff_semantic import SemanticDiff, diff_semantic
from .diff_structural import Severity, StructuralDiff, diff_structural
from .embed import get_embedder
from .pair import PagePair, PairSpec, fetch_pair, load_pairs_csv
from .score import RiskScore, RiskTier, rank, score_pair
from .llm_judge import Budget, Judge, JudgeCache, JudgeOutcome, should_judge
from .store import build_result, save_result


def _safe_stdout() -> None:
    """Stop a page's own characters from killing the run.

    Fetched pages carry whatever their authors wrote -- arrows, dashes, emoji --
    and a Windows console defaults to cp1252, which raises UnicodeEncodeError on
    the first one it cannot represent. That crashed a real comparison partway
    through printing its findings. UTF-8 is tried first; failing that, the
    platform encoding is kept but told to substitute rather than raise.
    """
    for kwargs in ({"encoding": "utf-8", "errors": "replace"},
                   {"errors": "replace"}):
        try:
            sys.stdout.reconfigure(**kwargs)
            sys.stderr.reconfigure(**kwargs)
            return
        except Exception:
            continue


def _console():
    _safe_stdout()
    try:
        from rich.console import Console
        return Console()
    except ImportError:
        return None


def _delta(old_n: int, new_n: int) -> str:
    d = new_n - old_n
    return f"{old_n} -> {new_n}" + (f"  ({d:+d})" if d else "")


def _safe(item: str) -> str:
    """Escape rich markup in a finding's item.

    Findings carry arbitrary text -- a score like "[best match 0.31]", or a URL
    like ".../programs#f:DegreeLevels=[Bachelors]". rich reads square brackets
    as style tags and silently deletes them, so the score or the URL fragment
    just disappears from the report.
    """
    from rich.markup import escape
    return escape(item)


def _shorten(item: str, width: int = 80) -> str:
    """Trim a finding's item for display only.

    Sitecore CDN URLs run past 200 characters of revision hashes, which wraps
    over several terminal lines and buries the findings around it. The width
    leaves room for the indent inside a default terminal, and the marker is
    ASCII because a Windows console will not reliably render an ellipsis. The
    JSON output keeps the full value either way.
    """
    item = " ".join(item.split())
    if len(item) <= width:
        return item
    return item[: width - 3] + "..."


COUNT_LABELS = {
    "words": "words",
    "headings": "headings",
    "images": "images",
    "background_images": "  of those, css background",
    "images_missing_alt": "images missing alt",
    "links": "links",
    "document_links": "document links",
}

TIER_STYLE = {
    RiskTier.MISSING: "bold red",
    RiskTier.MAJOR: "yellow",
    RiskTier.MINOR: "cyan",
    RiskTier.CLEAN: "green",
    RiskTier.UNKNOWN: "dim",
}

SEVERITY_STYLE = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}


def report_pair(pair: PagePair, diff: StructuralDiff, console=None, *,
                show_lists: int = 8, semantic: SemanticDiff | None = None,
                risk: RiskScore | None = None,
                judge: JudgeOutcome | None = None) -> None:
    o, n = pair.old, pair.new
    title = pair.spec.label or (o.title or n.title or "(untitled)")
    old_src = o.source + (f" @ {o.snapshot_timestamp}" if o.snapshot_timestamp else "")

    if console is None:
        print()
        print(f"=== {title} ===")
        print(f"  old  {o.url}  [{old_src}]  HTTP {o.status}")
        print(f"  new  {n.url}  [{n.source}]  HTTP {n.status}")
        if risk is not None:
            print(f"  risk  {risk.tier.label} (score {risk.score}, "
                  f"confidence {risk.confidence})")
            for reason in risk.reasons:
                print(f"      because {reason}")
            for caveat in risk.caveats:
                print(f"      caveat: {caveat}")
        for problem in pair.problems:
            print(f"  !! {problem}")
        if pair.problems:
            return
        print(f"  worst finding: {diff.worst.label}")
        for metric, (a, b) in diff.counts.items():
            print(f"    {COUNT_LABELS.get(metric, metric):<28} {_delta(a, b)}")
        for finding in diff.ranked():
            print(f"    [{finding.severity.label}] {finding.summary}")
            for item in finding.items[:show_lists]:
                print(f"       - {_shorten(item)}")
            if len(finding.items) > show_lists:
                print(f"       ... and {len(finding.items) - show_lists} more")
        if semantic is not None:
            print(f"  semantic: similarity {semantic.overall_similarity:.2f}, "
                  f"coverage {semantic.coverage:.2f}")
            print(f"    {semantic.interpretation()}")
            for finding in semantic.findings:
                print(f"    [{finding.severity.label}] {finding.summary}")
                for item in finding.items[:show_lists]:
                    print(f"       - {_shorten(item)}")
        if judge is not None:
            print(f"  judge: {judge.summary or judge.skipped_reason}")
            for passage in judge.facts_lost:
                print(f"    lost: {passage.get('detail', '')}")
        return

    from rich.panel import Panel
    from rich.table import Table

    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold cyan", justify="right")
    head.add_column()
    head.add_row("old", f"{o.url}  [dim]{old_src}, HTTP {o.status}[/dim]")
    head.add_row("new", f"{n.url}  [dim]{n.source}, HTTP {n.status}[/dim]")
    if risk is not None:
        style = TIER_STYLE[risk.tier]
        head.add_row("risk", f"[{style}]{risk.tier.label}[/{style}]  "
                             f"[dim]score {risk.score} - loss {risk.loss}, "
                             f"change {risk.change} - confidence "
                             f"{risk.confidence}[/dim]")
    console.print(Panel(head, title=title, border_style="cyan"))

    if risk is not None:
        for reason in risk.reasons:
            console.print(f"  [dim]because[/dim] {_safe(reason)}")
        for caveat in risk.caveats:
            console.print(f"  [yellow]caveat[/yellow]  {_safe(caveat)}")

    for problem in pair.problems:
        console.print(f"  [bold red]cannot compare[/bold red]  {problem}")
    if pair.problems:
        console.print()
        return

    counts = Table(show_header=True, header_style="bold")
    counts.add_column("metric", width=28)
    counts.add_column("old -> new")
    for metric, (a, b) in diff.counts.items():
        counts.add_row(COUNT_LABELS.get(metric, metric), _delta(a, b),
                       style="yellow" if b < a else None)
    console.print(counts)

    if not diff.findings:
        console.print()
        console.print("[bold green]no structural differences[/bold green]")
    for finding in diff.ranked():
        style = SEVERITY_STYLE[finding.severity]
        console.print()
        console.print(
            f"[{style}]{finding.severity.label:>6}[/{style}]  {finding.summary}"
            f"  [dim]({finding.kind})[/dim]")
        for item in finding.items[:show_lists]:
            console.print(f"         - {_safe(_shorten(item))}")
        if len(finding.items) > show_lists:
            console.print(
                f"         [dim]... and {len(finding.items) - show_lists} more[/dim]")

    # Always reached, even when the structure is clean: a page can keep every
    # heading, image and link and still have had its text gutted, and that is
    # the case the semantic stage exists for.
    if semantic is not None:
        _report_semantic(semantic, console, show_lists)
    if judge is not None:
        _report_judge(judge, console)
    console.print()


def _report_semantic(semantic: SemanticDiff, console, show_lists: int) -> None:
    from rich.table import Table

    console.print()
    scores = Table(show_header=True, header_style="bold")
    scores.add_column("semantic", width=28)
    scores.add_column("value")
    scores.add_row("overall similarity", f"{semantic.overall_similarity:.3f}")
    # Coverage is the number that answers "did anything go missing", and the
    # one a single similarity score hides: the real UTA pair scores 0.83
    # similar while only a third of its old text is accounted for.
    scores.add_row("coverage of old text", f"{semantic.coverage:.3f}",
                   style="yellow" if semantic.coverage < 0.9 else None)
    scores.add_row("passages", f"{len(semantic.matches)} old, "
                               f"{len(semantic.dropped)} with no counterpart")
    console.print(scores)
    console.print(f"[italic]{_safe(semantic.interpretation())}[/italic]")

    for finding in semantic.findings:
        style = SEVERITY_STYLE[finding.severity]
        console.print()
        console.print(
            f"[{style}]{finding.severity.label:>6}[/{style}]  {finding.summary}"
            f"  [dim]({finding.kind})[/dim]")
        for item in finding.items[:show_lists]:
            console.print(f"         - {_safe(_shorten(item, 92))}")
        if len(finding.items) > show_lists:
            console.print(
                f"         [dim]... and {len(finding.items) - show_lists} more[/dim]")
    for note in semantic.notes:
        console.print(f"  [yellow]note[/yellow]  {note}")


JUDGE_STYLE = {"major": "bold red", "minor": "yellow", "none": "green"}


def _report_judge(judge: JudgeOutcome, console) -> None:
    from rich.panel import Panel

    console.print()
    if not judge.judged:
        console.print(f"  [dim]judge skipped: {_safe(judge.skipped_reason)}[/dim]")
        return

    style = JUDGE_STYLE.get(judge.severity, "dim")
    cost = "cached" if judge.cached else f"${judge.cost_usd:.4f}"
    body = [f"[{style}]{judge.severity.upper()}[/{style}]  {_safe(judge.summary)}"]
    for passage in judge.facts_lost:
        section = passage.get("section") or "(no heading)"
        body.append("")
        body.append(f"[bold red]lost[/bold red]  [dim]{_safe(section)}[/dim]  "
                    f"{_safe(passage.get('detail', ''))}")
    console.print(Panel("\n".join(body),
                        title=f"What changed ({judge.model}, {cost})",
                        border_style=style))


def _parse_auth(value: str | None, url: str) -> dict[str, tuple[str, str]]:
    """Turn --new-auth into a host->credentials map.

    `user:pass` is accepted for convenience, but `user` alone reads the
    password from MAVDITTO_PASSWORD so it need not sit in shell history.
    """
    if not value:
        return {}
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc.lower()
    if ":" in value:
        user, password = value.split(":", 1)
    else:
        user = value
        password = os.environ.get("MAVDITTO_PASSWORD", "")
        if not password:
            raise SystemExit(
                "--new-auth was given a username with no password; set "
                "MAVDITTO_PASSWORD or pass user:pass"
            )
    return {host: (user, password)}


def build_specs(args: argparse.Namespace) -> list[PairSpec]:
    if args.pairs:
        return load_pairs_csv(args.pairs)
    if not (args.old and args.new):
        raise SystemExit("give --old and --new, or --pairs FILE")
    return [PairSpec(
        old_url=args.old,
        new_url=args.new,
        old_source=args.old_source,
        new_source=args.new_source,
        timestamp=args.timestamp,
        old_root=args.old_root,
        new_root=args.new_root,
    )]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.compare",
        description="Compare old and new versions of a page, side by side.",
    )
    ap.add_argument("--old", help="old page URL")
    ap.add_argument("--new", help="new page URL")
    ap.add_argument("--pairs", metavar="FILE", help="url_pairs.csv to read instead")
    ap.add_argument("--old-source", choices=("live", "wayback", "auto"), default="live",
                    help="where the old page comes from (default: live)")
    ap.add_argument("--new-source", choices=("live", "wayback", "auto"), default="live")
    ap.add_argument("--timestamp", default="",
                    help="preferred Wayback capture for the old side, e.g. 20150601")
    ap.add_argument("--old-root", default="",
                    help="old site root, so internal links compare site-relatively; "
                         "defaults to the old page's scheme+host. Set both roots for "
                         "a subsite move under one host")
    ap.add_argument("--new-root", default="", help="new site root (see --old-root)")
    ap.add_argument("--new-auth", metavar="USER[:PASS]",
                    help="HTTP basic auth for the new site (staging is often gated)")
    ap.add_argument("--respect-robots", action="store_true",
                    help="consult robots.txt before fetching. Off by default: "
                         "staging hosts serve Disallow: / to stay out of search "
                         "results, not to refuse their owner")
    ap.add_argument("--judge", action="store_true",
                    help="explain what changed on flagged pages using the Claude "
                         "API (costs money; see --judge-budget)")
    ap.add_argument("--judge-model", default="claude-opus-5",
                    help="model for the judge (default: claude-opus-5)")
    ap.add_argument("--judge-budget", type=float, default=1.00, metavar="USD",
                    help="hard spend cap for this run (default: 1.00). Checked "
                         "before each call, so it is never exceeded")
    ap.add_argument("--judge-max-calls", type=int, default=50,
                    help="hard cap on judge calls for this run (default: 50)")
    ap.add_argument("--judge-effort", choices=("low", "medium", "high", "xhigh"),
                    default="high", help="how hard the judge thinks (default: high)")
    ap.add_argument("--no-judge-cache", action="store_true",
                    help="re-judge pages even if an identical judgement is cached")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip the embedding comparison (structure only)")
    ap.add_argument("--embedder", choices=("local", "lexical"), default="local",
                    help="'local' is the sentence-transformers model; 'lexical' is a "
                         "word-overlap stand-in needing no model, useful only for "
                         "smoke tests since it cannot see meaning")
    ap.add_argument("--render", choices=("auto", "static", "js"), default="auto")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-js", action="store_true")
    ap.add_argument("--list-size", type=int, default=8,
                    help="how many missing headings/links to list per pair")
    ap.add_argument("--out", metavar="DIR", help="write each pair's JSON here")
    args = ap.parse_args(argv)

    specs = build_specs(args)
    if not specs:
        print("no pairs to compare")
        return 0

    credentials: dict[str, tuple[str, str]] = {}
    if args.new_auth:
        credentials = _parse_auth(args.new_auth, specs[0].new_url)

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    console = _console()
    # Built once and reused: loading the model costs about twenty seconds, and
    # it is lazy, so --no-semantic never pays for it at all.
    embedder = None if args.no_semantic else get_embedder(args.embedder)

    # Built only when asked for: constructing it validates the model name and
    # the budget, but the API client itself stays lazy, so a run without
    # --judge never needs credentials.
    judge = None
    if args.judge:
        judge = Judge(
            model=args.judge_model,
            budget=Budget(max_usd=args.judge_budget,
                          max_calls=args.judge_max_calls),
            cache=JudgeCache(enabled=not args.no_judge_cache),
            effort=args.judge_effort,
        )

    results: list[tuple] = []
    with Fetcher(
        delay_s=args.delay,
        use_cache=not args.no_cache,
        allow_js=not args.no_js,
        credentials=credentials,
        respect_robots=args.respect_robots,
    ) as fetcher:
        for spec in specs:
            pair = fetch_pair(fetcher, spec, render=args.render,
                              respect_robots=args.respect_robots)
            # A pair that failed to fetch is not a page that lost content, so
            # it is never handed to either diff -- it would read as total loss.
            diff = semantic = None
            if not pair.problems:
                diff = diff_structural(
                    pair.old, pair.new,
                    old_root=spec.old_root, new_root=spec.new_root,
                )
                if embedder is not None:
                    semantic = diff_semantic(pair.old, pair.new, embedder)
            risk = score_pair(pair, diff, semantic)

            # Built once and reused for the judge, the report and the store:
            # assembling it serializes both pages, which is not free.
            stored = build_result(spec, pair, diff, semantic, risk)

            verdict = None
            if judge is not None and should_judge(risk.tier.label, stored.semantic):
                verdict = judge.judge_page(stored.semantic["passages"],
                                           title=stored.title)
            results.append((pair, diff, semantic, risk))
            report_pair(pair, diff, console, show_lists=args.list_size,
                        semantic=semantic, risk=risk, judge=verdict)
            if out_dir:
                if verdict is not None:
                    stored.judge = verdict.to_dict()
                save_result(out_dir, stored)

    exit_code = _summarize(results, console)
    if judge is not None:
        line = f"  judge: {judge.budget.summary(noun='judge call')}"
        console.print(line, style="dim") if console else print(line)
    return exit_code


def _summarize(results, console) -> int:
    """The ranked list: worst pages first, so a reviewer starts where it matters.

    Pairs that could not be fetched are listed apart rather than given a tier.
    A page nobody could read is not a page that lost content, and mixing the
    two would put fetch errors where real losses belong.
    """
    ranked = rank([r for r in results if r[-1].tier is not RiskTier.UNKNOWN])
    unknown = [r for r in results if r[-1].tier is RiskTier.UNKNOWN]

    def emit(text: str, style: str | None = None) -> None:
        console.print(text, style=style) if console else print(text)

    tally: dict[RiskTier, int] = {}
    for _, _, _, risk in ranked:
        tally[risk.tier] = tally.get(risk.tier, 0) + 1

    emit("")
    if console is None:
        emit(f"=== {len(ranked)} pages by risk ===")
        for pair, _, _, risk in ranked:
            emit(f"  {risk.tier.label:<16} {risk.score:>5}  "
                 f"{risk.confidence:<6}  {pair.spec.new_url}")
    else:
        from rich.table import Table

        table = Table(title="Pages by risk", title_style="bold",
                      show_header=True, header_style="bold")
        table.add_column("tier", width=16)
        table.add_column("score", justify="right", width=6)
        table.add_column("loss", justify="right", width=6)
        table.add_column("change", justify="right", width=7)
        table.add_column("confidence", width=10)
        table.add_column("page", overflow="fold")
        for pair, _, _, risk in ranked:
            style = TIER_STYLE[risk.tier]
            table.add_row(f"[{style}]{risk.tier.label}[/{style}]",
                          f"{risk.score}", f"{risk.loss}", f"{risk.change}",
                          risk.confidence,
                          pair.spec.label or pair.spec.new_url)
        console.print(table)

    parts = [f"{tally.get(t, 0)} {t.label.lower()}"
             for t in (RiskTier.MISSING, RiskTier.MAJOR, RiskTier.MINOR,
                       RiskTier.CLEAN)]
    emit("  " + ",  ".join(parts))

    for pair, _, _, risk in unknown:
        emit(f"  could not compare: {pair.spec.new_url} -- "
             f"{'; '.join(risk.reasons)}", "yellow")
    return 1 if unknown and len(unknown) == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
