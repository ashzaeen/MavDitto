"""Point it at two site roots; get back the page-by-page migration map.

    python -m src.discover_cli --old https://old.example.edu --new https://example.edu

This is the step that makes the rest of the tool usable on a whole site rather
than a hand-written list. It enumerates both sites, pairs their pages, and
writes `url_pairs.csv` for `src.compare` to consume.

Its own headline answer comes before any content is compared: **which old pages
have no counterpart at all**. A page that no longer exists anywhere is the worst
migration failure there is, and a pairwise content diff structurally cannot see
it -- you cannot compare a page against a replacement it does not have.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .discover import (
    DEFAULT_MAX_DEPTH, DEFAULT_MAX_PAGES, MatchReport, SiteInventory,
    check_reachable, discover, match_by_title, match_sites,
)
from .fetch import Fetcher
from .models import utcnow_iso
from .pair import PairSpec, write_pairs_csv
from .store import Discovery, save_discovery


def _console():
    for kwargs in ({"encoding": "utf-8", "errors": "replace"},
                   {"errors": "replace"}):
        try:
            sys.stdout.reconfigure(**kwargs)
            break
        except Exception:
            continue
    try:
        from rich.console import Console
        return Console()
    except ImportError:
        return None


def _emit(console, text: str, style: str | None = None) -> None:
    console.print(text, style=style) if console else print(text)


def report_inventory(console, label: str, inventory: SiteInventory) -> None:
    _emit(console, f"\n{label}: {len(inventory)} page(s) via {inventory.method}")
    for note in inventory.notes:
        _emit(console, f"    {note}", "dim")
    if inventory.unreachable:
        _emit(console, f"    {len(inventory.unreachable)} listed page(s) did not "
                       "respond:", "yellow")
        for page in inventory.unreachable[:10]:
            _emit(console, f"        {page.path}", "yellow")
        if len(inventory.unreachable) > 10:
            _emit(console,
                  f"        ... and {len(inventory.unreachable) - 10} more", "dim")


def report_match(console, report: MatchReport, old_root: str, new_root: str,
                 show: int) -> None:
    total_old = len(report.pairs) + len(report.unmatched_old)

    if console is None:
        _emit(console, f"\n{len(report.pairs)}/{total_old} old pages matched "
                       f"({report.migrated_share:.0%})")
    else:
        from rich.table import Table

        table = Table(title="Migration map", title_style="bold",
                      show_header=True, header_style="bold")
        table.add_column("old page", overflow="fold")
        table.add_column("new page", overflow="fold")
        table.add_column("matched by", width=11)
        table.add_column("conf", justify="right", width=5)
        for pairing in report.pairs[:show]:
            table.add_row(pairing.old.path, pairing.new.path,
                          pairing.method, f"{pairing.confidence:.2f}")
        console.print(table)
        if len(report.pairs) > show:
            _emit(console, f"    ... and {len(report.pairs) - show} more matched "
                           "pairs", "dim")

    # The headline. Printed after the map because it is the conclusion, and
    # loudly because it is the thing a pairwise content diff cannot find.
    if report.unmatched_old:
        _emit(console, f"\nNOT MIGRATED - {len(report.unmatched_old)} old page(s) "
                       "have no counterpart on the new site:", "bold red")
        for page in report.unmatched_old:
            _emit(console, f"    {page.path}    {page.url}")
    else:
        _emit(console, "\nEvery old page has a counterpart on the new site.",
              "bold green")

    if report.unmatched_new:
        _emit(console, f"\nNew pages with no old counterpart "
                       f"({len(report.unmatched_new)}) - net-new content:", "cyan")
        for page in report.unmatched_new[:show]:
            _emit(console, f"    {page.path}")
        if len(report.unmatched_new) > show:
            _emit(console, f"    ... and {len(report.unmatched_new) - show} more",
                  "dim")

    _emit(console, "")
    style = ("bold green" if report.migrated_share == 1
             else "bold red" if report.migrated_share < 0.9 else "bold yellow")
    _emit(console, f"{len(report.pairs)} of {total_old} old pages accounted for "
                   f"({report.migrated_share:.0%})", style)


def write_inventory_csv(inventory: SiteInventory, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["path", "url", "title", "source"])
        for page in inventory.pages:
            writer.writerow([page.path, page.url, page.title, page.source])


def write_unmatched_csv(report: MatchReport, path: Path) -> None:
    """The pages that need a human decision: redirect, rebuild, or accept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["side", "path", "url", "title", "decision needed"])
        for page in report.unmatched_old:
            writer.writerow([
                "old", page.path, page.url, page.title,
                "no counterpart found - redirect it, rebuild it, or accept the loss"])
        for page in report.unmatched_new:
            writer.writerow([
                "new", page.path, page.url, page.title,
                "net-new page, nothing on the old site corresponds"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.discover_cli",
        description="Crawl two sites, pair their pages, and report what did not "
                    "make it across.")
    ap.add_argument("--old", required=True, help="old site root URL")
    ap.add_argument("--new", required=True, help="new site root URL")
    ap.add_argument("--out", default="data", metavar="DIR",
                    help="where to write url_pairs.csv and the inventories")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                    help=f"per-site page cap (default {DEFAULT_MAX_PAGES})")
    ap.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    ap.add_argument("--no-sitemap", action="store_true",
                    help="always crawl, even when a sitemap is published")
    ap.add_argument("--check-live", action="store_true",
                    help="confirm every listed page actually responds; a sitemap "
                         "is a claim, not a guarantee")
    ap.add_argument("--workers", type=int, default=6,
                    help="how many pages to fetch at once (default 6)")
    ap.add_argument("--match-titles", action="store_true",
                    help="fetch leftover pages and try matching them on title; "
                         "costs one request per unmatched page")
    ap.add_argument("--respect-robots", action="store_true",
                    help="consult robots.txt before fetching. Off by default: "
                         "staging and preview hosts serve Disallow: / to stay "
                         "out of search results, not to refuse their owner")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="minimum seconds between requests to one host")
    ap.add_argument("--show", type=int, default=25,
                    help="how many matched pairs to print")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    console = _console()
    out_dir = Path(args.out)

    with Fetcher(delay_s=args.delay, use_cache=not args.no_cache) as fetcher:
        _emit(console, f"Enumerating {args.old} ...", "dim")
        old = discover(args.old, fetcher, max_pages=args.max_pages,
                       max_depth=args.max_depth, use_sitemap=not args.no_sitemap,
                       respect_robots=args.respect_robots)
        _emit(console, f"Enumerating {args.new} ...", "dim")
        new = discover(args.new, fetcher, max_pages=args.max_pages,
                       max_depth=args.max_depth, use_sitemap=not args.no_sitemap,
                       respect_robots=args.respect_robots)

        if args.check_live:
            _emit(console, "Checking every page responds ...", "dim")
            check_reachable(old, fetcher,
                            respect_robots=args.respect_robots)
            check_reachable(new, fetcher,
                            respect_robots=args.respect_robots)

        report_inventory(console, "old site", old)
        report_inventory(console, "new site", new)

        if not old.pages:
            _emit(console, "\nNo pages found under the old root; nothing to pair.",
                  "bold red")
            return 1

        match = match_sites(old, new)
        if args.match_titles:
            found = match_by_title(
                match, fetcher,
                respect_robots=args.respect_robots)
            old_signal, new_signal = match.label_signals
            _emit(console, f"\nname matching used {old_signal} on the old site, "
                           f"{new_signal} on the new site", "dim")
            if "not distinctive" in old_signal + new_signal:
                _emit(console, "    one side gives every page the same name, so "
                               "there is nothing to match on there", "yellow")
            _emit(console, f"    {found} further pair(s) matched by name", "dim")

    report_match(console, match, old.root, new.root, args.show)

    specs = [
        PairSpec(old_url=p.old.url, new_url=p.new.url,
                 old_root=old.root, new_root=new.root,
                 label=p.old.path)
        for p in match.pairs
    ]
    pairs_path = out_dir / "url_pairs.csv"
    write_pairs_csv(specs, pairs_path)

    def as_rows(pages):
        return [{"path": p.path, "url": p.url, "title": p.title} for p in pages]

    # The dashboard reads this. Without it the headline finding -- pages with
    # no counterpart at all -- would exist only in a CSV, and a reviewer would
    # see a report that silently omits the worst outcome.
    save_discovery(out_dir, Discovery(
        old_root=old.root, new_root=new.root, discovered_at=utcnow_iso(),
        matched=len(match.pairs),
        old_total=len(old) + len(old.unreachable),
        new_total=len(new) + len(new.unreachable),
        label_signals=list(match.label_signals),
        matched_pairs=[
            {"path": p.old.path, "oldUrl": p.old.url, "newUrl": p.new.url,
             "method": p.method, "confidence": p.confidence}
            for p in match.pairs
        ],
        not_migrated=as_rows(match.unmatched_old),
        net_new=as_rows(match.unmatched_new),
        unreachable_old=as_rows(old.unreachable + match.unreachable_old),
        unreachable_new=as_rows(new.unreachable + match.unreachable_new),
    ))
    write_inventory_csv(old, out_dir / "inventory_old.csv")
    write_inventory_csv(new, out_dir / "inventory_new.csv")
    write_unmatched_csv(match, out_dir / "unmatched_pages.csv")

    _emit(console, f"\nwrote {pairs_path} ({len(specs)} pairs)")
    _emit(console, f"      {out_dir / 'unmatched_pages.csv'} "
                   f"({len(match.unmatched_old)} not migrated, "
                   f"{len(match.unmatched_new)} net-new)")
    _emit(console, f"      {out_dir / 'inventory_old.csv'}, "
                   f"{out_dir / 'inventory_new.csv'}")
    _emit(console, "\nNext: compare the content of those pairs with\n"
                   f"      python -m src.compare --pairs {pairs_path} --out data/out",
          "dim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
