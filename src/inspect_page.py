"""Phase 1 deliverable: fetch + extract one or more URLs and show the result.

    python -m src.inspect_page https://example.com/page
    python -m src.inspect_page --source wayback https://old.example.edu/dept/
    python -m src.inspect_page --urls data/test_urls.txt --out data/out

Prints the clean text, heading outline, images (flagging missing alt), and
links (flagging documents and externals) -- i.e. exactly the normalized shape
every later stage of the pipeline consumes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fetch import Fetcher
from .extract import extract_fetch_result
from .models import PageContent


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


def report(page: PageContent, *, text_chars: int, console=None) -> None:
    if console is None:
        _report_plain(page, text_chars)
        return

    from rich.panel import Panel
    from rich.table import Table

    status_style = "green" if 200 <= page.status < 300 else "red"
    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold cyan", justify="right")
    header.add_column()
    header.add_row("url", page.url)
    header.add_row("fetched", page.fetched_url)
    header.add_row("status", f"[{status_style}]{page.status}[/{status_style}]")
    header.add_row("source", f"{page.source} ({page.render_mode})")
    if page.snapshot_timestamp:
        header.add_row("snapshot", page.snapshot_timestamp)
    header.add_row("extractor", page.extractor or "-")
    header.add_row("words", str(page.word_count))
    console.print(Panel(header, title=page.title or "(no title)", border_style="cyan"))

    if page.notes:
        for note in page.notes:
            console.print(f"  [yellow]note[/yellow]  {note}")
        console.print()

    outline = Table(title=f"Headings ({len(page.headings)})", show_lines=False)
    outline.add_column("lvl", style="magenta", width=4)
    outline.add_column("text")
    for h in page.headings:
        outline.add_row(f"h{h.level}", f"{'  ' * (h.level - 1)}{h.text}")
    console.print(outline if page.headings else "[dim]no headings[/dim]")

    missing = len(page.images_missing_alt)
    bg = len(page.background_images)
    imgs = Table(
        title=f"Images ({len(page.images)}; {bg} css background, {missing} missing alt)",
        title_style="bold red" if missing else "",
    )
    imgs.add_column("kind", width=5)
    imgs.add_column("alt", width=36)
    imgs.add_column("src", overflow="fold")
    for img in page.images:
        if img.is_decorative:
            alt = "[dim]n/a (css)[/dim]"
        elif img.alt is None:
            alt = "[red]<no alt attr>[/red]"
        elif not img.alt.strip():
            alt = "[red]<empty alt>[/red]"
        else:
            alt = img.alt
        imgs.add_row("bg" if img.is_decorative else "img", alt, img.src)
    console.print(imgs if page.images else "[dim]no images[/dim]")

    docs = len(page.document_links)
    links = Table(title=f"Links ({len(page.links)}, {docs} documents)")
    links.add_column("kind", width=8)
    links.add_column("text", width=34)
    links.add_column("href", overflow="fold")
    for link in page.links:
        kind = "[bold]doc[/bold]" if link.is_document else ("ext" if link.is_external else "int")
        links.add_row(kind, link.text or "[dim](no text)[/dim]", link.href)
    console.print(links if page.links else "[dim]no links[/dim]")

    preview = page.text[:text_chars]
    if len(page.text) > text_chars:
        preview += f"\n[dim]... (+{len(page.text) - text_chars} more chars)[/dim]"
    console.print(Panel(preview or "[dim](no text)[/dim]", title="Body text",
                        border_style="green"))


def _report_plain(page: PageContent, text_chars: int) -> None:
    print(f"\n=== {page.title or '(no title)'} ===")
    print(f"url        {page.url}")
    print(f"fetched    {page.fetched_url}")
    print(f"status     {page.status}   source {page.source} ({page.render_mode})")
    print(f"extractor  {page.extractor}   words {page.word_count}")
    for note in page.notes:
        print(f"  note: {note}")
    print(f"\n-- headings ({len(page.headings)}) --")
    for h in page.headings:
        print(f"  {'  ' * (h.level - 1)}h{h.level}  {h.text}")
    print(f"\n-- images ({len(page.images)}, {len(page.images_missing_alt)} missing alt) --")
    for img in page.images:
        alt = "<no alt attr>" if img.alt is None else (img.alt or "<empty alt>")
        print(f"  [{alt}] {img.src}")
    print(f"\n-- links ({len(page.links)}, {len(page.document_links)} documents) --")
    for link in page.links:
        kind = "doc" if link.is_document else ("ext" if link.is_external else "int")
        print(f"  {kind}  {link.text[:40]!r} -> {link.href}")
    print(f"\n-- text ({len(page.text)} chars) --")
    print(page.text[:text_chars])


def load_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls_positional)
    if args.urls:
        for line in Path(args.urls).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.inspect_page",
        description="Fetch and extract pages; print clean text, headings, images, links.",
    )
    ap.add_argument("urls_positional", nargs="*", metavar="URL")
    ap.add_argument("--urls", metavar="FILE", help="file with one URL per line (# comments ok)")
    ap.add_argument("--source", choices=("live", "wayback", "auto"), default="live",
                    help="where to fetch from; 'auto' tries live then falls back to Wayback")
    ap.add_argument("--render", choices=("auto", "static", "js"), default="auto",
                    help="'auto' escalates to a browser only when a page looks empty")
    ap.add_argument("--timestamp", default="",
                    help="preferred Wayback snapshot, e.g. 20180101")
    ap.add_argument("--delay", type=float, default=1.0, help="min seconds between same-host hits")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="skip the robots.txt check (only for sites you control)")
    ap.add_argument("--no-js", action="store_true", help="never launch a browser")
    ap.add_argument("--text-chars", type=int, default=1200, help="body text preview length")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a report")
    ap.add_argument("--out", metavar="DIR", help="also write one JSON file per page here")
    args = ap.parse_args(argv)

    urls = load_urls(args)
    if not urls:
        ap.error("give at least one URL, or --urls FILE")

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    console = None if args.json else _console()
    pages: list[PageContent] = []

    with Fetcher(
        delay_s=args.delay,
        use_cache=not args.no_cache,
        respect_robots=not args.ignore_robots,
        allow_js=not args.no_js,
    ) as fetcher:
        for url in urls:
            result = fetcher.fetch(
                url, source=args.source, render=args.render, timestamp=args.timestamp
            )
            page = extract_fetch_result(result)
            pages.append(page)

            if args.json:
                print(page.to_json())
            else:
                report(page, text_chars=args.text_chars, console=console)

            if out_dir:
                stem = "".join(c if c.isalnum() else "_" for c in page.url)[-90:]
                (out_dir / f"{stem}.json").write_text(page.to_json(), encoding="utf-8")

    failed = [p for p in pages if not (200 <= p.status < 300) or p.word_count < 50]
    if not args.json:
        msg = f"\n{len(pages) - len(failed)}/{len(pages)} pages extracted cleanly"
        print(msg if console is None else "")
        if console:
            console.print(msg, style="bold green" if not failed else "bold yellow")
        for p in failed:
            line = f"  needs a look: {p.url} (status {p.status}, {p.word_count} words)"
            console.print(line, style="yellow") if console else print(line)
    return 1 if len(failed) == len(pages) and pages else 0


if __name__ == "__main__":
    sys.exit(main())
