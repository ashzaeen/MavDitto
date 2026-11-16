"""Export the results store as one JSON file for the React dashboard.

    python -m src.export_web --results data/run --out dashboard-react/public/data.json

The React app fetches this and nothing else: no API, no server, no Python at
runtime. `npm run build` then produces a static bundle that can be dropped
anywhere, which keeps the dashboard as portable as the Streamlit one.

The shape extends the contract the design shipped with (`mockData.js`) rather
than replacing it, so the components that already work keep working. What is
added is everything the design predates -- coverage beside similarity, the
pages that never arrived, which headings went, and the scorer's caveats.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .diff_structural import align_headings
from .models import PageContent, utcnow_iso
from .store import Discovery, PairResult, load_discovery, load_results
from .textdiff import change_ratio, diff_items, word_diff

# The dashboard's tier keys. Everything that could not be compared collapses
# into "error", which the design already renders as "Couldn't check" -- a
# visible row state rather than a silent omission.
TIER_KEYS = {
    "Clean": "clean",
    "Minor rewording": "minor",
    "Major rewording": "major",
    "Missing content": "missing",
    "Unknown": "error",
}


def _segments(old: str, new: str) -> tuple[list[dict], list[dict]]:
    """Word-level diff as the design's segment list.

    Computed here rather than in the browser so the dashboard stays a pure
    renderer, and so the diff a reviewer reads is the same one the risk score
    was derived from.
    """
    old_side, new_side = word_diff(old or "", new or "")
    kinds = {"equal": "plain", "delete": "removed", "insert": "added"}
    return ([{"text": s.text, "kind": kinds[s.kind]} for s in old_side],
            [{"text": s.text, "kind": kinds[s.kind]} for s in new_side])


def _count(result: PairResult, key: str) -> tuple[int, int]:
    pair = result.counts.get(key) or [0, 0]
    return int(pair[0]), int(pair[1])


def _items(result: PairResult, kind: str) -> list[str]:
    for finding in result.findings:
        if finding.get("kind") == kind:
            return list(finding.get("items") or [])
    return []


def page_detail(result: PairResult) -> dict[str, Any] | None:
    """Everything the detail screen needs for one pair."""
    if result.old is None or result.new is None or result.problems:
        return None

    headings_old, headings_new = _count(result, "headings")
    images_old, images_new = _count(result, "images")
    links_old, links_new = _count(result, "links")
    docs_old, docs_new = _count(result, "document_links")
    _, missing_alt = _count(result, "images_missing_alt")

    judge = result.judge or {}
    risk = result.risk or {}
    passages = result.semantic.get("passages") or []
    added = result.semantic.get("added") or []

    return {
        "headingsOld": headings_old,
        "headingsNew": headings_new,
        # Counts alone call a page clean when all ten headings changed, so the
        # dropped ones travel with the numbers.
        "headingsDropped": [_clean_heading(h)
                            for h in _items(result, "heading.dropped")],

        "imagesOld": images_old,
        "imagesNew": images_new,
        "missingAlt": missing_alt,
        "imagesDropped": len(_items(result, "image.dropped")),

        "linksOld": links_old,
        "linksNew": links_new,
        "brokenLinks": len(_items(result, "link.dropped")),
        "documentsOld": docs_old,
        "documentsNew": docs_new,
        "documentsDropped": _items(result, "link.document_dropped"),

        "explanation": judge.get("summary") or "",
        "judgeSeverity": judge.get("severity") or "",
        "judgeModel": judge.get("model") or "",
        "factsLost": [
            {"section": p.get("section") or "", "detail": p.get("detail") or ""}
            for p in (judge.get("passages") or [])
            if p.get("verdict") == "facts_lost"
        ],
        "interpretation": result.semantic.get("interpretation", ""),
        "reasons": list(risk.get("reasons") or []),
        # Why not to take the tier at face value. The design showed a
        # confidence note on Clean rows only; these matter most on the others.
        "caveats": list(risk.get("caveats") or []),
        "confidenceNote": (" · ".join(risk.get("reasons") or [])
                           if result.tier == "Clean" else None),
        # The page rendered as a document, not a stream of same-labeled text
        # blobs: each side keeps its own headings, paragraphs, lists and
        # tables in its own order, coloured by what happened to it. A
        # single page-wide word diff is unreadable when the pages differ a
        # lot -- every word gets marked, and the aligner finds coincidental
        # matches between unrelated sentences, so the colour says nothing.
        "oldDocument": _old_document(result.old, result.new, passages),
        "newDocument": _new_document(result.old, result.new, passages, added),
    }


# Above this share of words changed, a word-level diff is noise: the aligner
# is matching coincidences rather than tracking an edit, and every line comes
# out striped. Those passages are better shown as two plain texts.
DIFF_NOISE_RATIO = 0.7

# item-level verdicts (textdiff.ItemDiff.kind) use their own small vocabulary;
# the rest of the payload calls the same four things kept/reworded/dropped/added.
_ITEM_VERDICT = {"kept": "kept", "changed": "reworded",
                 "dropped": "dropped", "added": "added"}


def _item_rows(items: list[dict]) -> list[dict[str, Any]]:
    return [{"text": d.text, "verdict": _ITEM_VERDICT[d.kind]} for d in items]


def _matched_content_blocks(passage: dict[str, Any]) -> tuple[dict, dict]:
    """Build the (old, new) block dicts for one matched passage.

    Built together because the diff between them is symmetric -- word-level
    for a paragraph, item-level for a list or table -- so computing it once
    and splitting the result guarantees both sides agree on what changed,
    rather than re-deriving it twice.
    """
    kind = passage.get("kind") or "paragraph"
    verdict = passage.get("verdict") or "kept"
    similarity = passage.get("similarity")
    old_row: dict[str, Any] = {"type": kind, "verdict": verdict, "similarity": similarity}
    new_row: dict[str, Any] = {"type": kind, "verdict": verdict, "similarity": similarity}

    if kind in ("list", "table"):
        old_items, new_items = diff_items(passage.get("items_old") or [],
                                          passage.get("items_new") or [])
        old_row["items"] = _item_rows(old_items)
        new_row["items"] = _item_rows(new_items)
        if kind == "list":
            old_row["ordered"] = new_row["ordered"] = bool(passage.get("ordered"))
        else:
            old_row["columns"] = new_row["columns"] = passage.get("columns") or []
        return old_row, new_row

    # paragraph / quote
    old_text = passage.get("old_text") or ""
    new_text = passage.get("new_text") or ""
    old_row["text"] = old_text
    new_row["text"] = new_text or None
    if verdict == "reworded" and new_text:
        changed = change_ratio(old_text, new_text)
        worth = changed <= DIFF_NOISE_RATIO
        old_row["changeRatio"] = new_row["changeRatio"] = round(changed, 3)
        old_row["worthHighlighting"] = new_row["worthHighlighting"] = worth
        if worth:
            old_seg, new_seg = _segments(old_text, new_text)
            old_row["segments"], new_row["segments"] = old_seg, new_seg
    return old_row, new_row


def _added_block(added: dict[str, Any]) -> dict[str, Any]:
    """A new-page block no old block claimed -- there is no other side to
    build here, so unlike a matched passage this needs no diffing at all."""
    kind = added.get("kind") or "paragraph"
    row: dict[str, Any] = {"type": kind, "verdict": "added", "similarity": None}
    if kind in ("list", "table"):
        row["items"] = [{"text": t, "verdict": "added"}
                        for t in (added.get("items") or [])]
        if kind == "list":
            row["ordered"] = bool(added.get("ordered"))
        else:
            row["columns"] = added.get("columns") or []
    else:
        row["text"] = added.get("text") or ""
    return row


def _plain_block(block, verdict: str = "kept") -> dict[str, Any]:
    """A block neither a real diff nor a fallback could place -- shown as-is
    rather than dropped, since an unexplained gap reads as a bug."""
    row: dict[str, Any] = {"type": block.kind, "verdict": verdict, "similarity": None}
    if block.kind in ("list", "table"):
        row["items"] = [{"text": t, "verdict": verdict} for t in block.items]
        if block.kind == "list":
            row["ordered"] = block.ordered
        else:
            row["columns"] = block.columns
    else:
        row["text"] = block.text
    return row


def _heading_verdicts(old_headings, new_headings) -> tuple[dict[int, str], dict[int, str]]:
    """Verdicts for heading blocks, keyed by id() of the Heading objects that
    `align_headings` was actually given -- it hands back the same instances,
    not copies, so identity is a safe key here."""
    old_verdict: dict[int, str] = {}
    new_verdict: dict[int, str] = {}
    for a in align_headings(old_headings, new_headings):
        if a.old is not None:
            old_verdict[id(a.old)] = ("dropped" if a.is_dropped
                                      else "reworded" if a.is_reworded else "kept")
        if a.new is not None:
            new_verdict[id(a.new)] = ("added" if a.is_added
                                      else "reworded" if a.is_reworded else "kept")
    return old_verdict, new_verdict


def _old_document(old: PageContent, new: PageContent,
                  passages: list[dict]) -> list[dict[str, Any]]:
    """The old page, as a document: headings, paragraphs, lists and tables in
    the order the page itself puts them in, each coloured by what became of
    it. Falls back to reconstructing sections from the flat passage list for
    results written before pages carried real blocks."""
    if not old.blocks:
        return _fallback_old_document(passages)

    old_verdict, _ = _heading_verdicts(old.headings, new.headings if new else [])
    headings = iter(old.headings)
    entries = iter(passages)
    out: list[dict[str, Any]] = []

    for block in old.blocks:
        if block.kind == "heading":
            h = next(headings, None)
            verdict = old_verdict.get(id(h), "kept") if h is not None else "kept"
            out.append({"type": "heading", "level": block.level, "text": block.text,
                        "verdict": verdict})
            continue
        passage = next(entries, None)
        out.append(_plain_block(block) if passage is None
                   else _matched_content_blocks(passage)[0])
    return out


def _new_document(old: PageContent, new: PageContent, passages: list[dict],
                  added: list[dict]) -> list[dict[str, Any]]:
    """The new page, as a document, in its own order. Every one of its content
    blocks is either a matched passage (placed by `new_index`, the position
    match_chunks gave it among the new page's own chunks) or one of `added` --
    the two partition every content block on the new side between them."""
    if not new.blocks:
        return _fallback_new_document(passages, added)

    _, new_verdict = _heading_verdicts(old.headings if old else [], new.headings)

    by_index: dict[int, dict[str, Any]] = {}
    for passage in passages:
        if passage.get("new_index") is not None:
            by_index[passage["new_index"]] = _matched_content_blocks(passage)[1]
    for a in added:
        by_index[a["index"]] = _added_block(a)

    headings = iter(new.headings)
    content_i = 0
    out: list[dict[str, Any]] = []
    for block in new.blocks:
        if block.kind == "heading":
            h = next(headings, None)
            verdict = new_verdict.get(id(h), "kept") if h is not None else "kept"
            out.append({"type": "heading", "level": block.level, "text": block.text,
                        "verdict": verdict})
            continue
        out.append(by_index.get(content_i) or _plain_block(block))
        content_i += 1
    return out


# --------------------------------------------------------------------------
# the fallback: results written before pages carried real blocks, and the
# synthetic PageContents most tests build directly with only `.text`
# --------------------------------------------------------------------------

def _fallback_old_document(passages: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current = object()          # sentinel: never equal to a real section
    for passage in passages:
        section = passage.get("section") or ""
        if section and section != current:
            out.append({"type": "heading", "level": 2,
                       "text": _clean_heading(section), "verdict": "kept"})
        current = section
        out.append(_matched_content_blocks(passage)[0])
    return out


def _fallback_new_document(passages: list[dict],
                           added: list[dict]) -> list[dict[str, Any]]:
    rows: list[tuple[int, str, dict[str, Any]]] = []
    for passage in passages:
        if passage.get("new_index") is None:
            continue
        rows.append((passage["new_index"], passage.get("new_section") or "",
                    _matched_content_blocks(passage)[1]))
    for a in added:
        rows.append((a["index"], a.get("section") or "", _added_block(a)))
    rows.sort(key=lambda r: r[0])

    out: list[dict[str, Any]] = []
    current = object()
    for _, section, row in rows:
        if section and section != current:
            out.append({"type": "heading", "level": 2,
                       "text": _clean_heading(section), "verdict": "kept"})
        current = section
        out.append(row)
    return out


def _clean_heading(text: str) -> str:
    """Strip the outline markers the pipeline uses internally.

    Headings are carried as "## Requirements" so a diff can compare level and
    text together. That is a storage detail; a reviewer should see the heading.
    """
    return re.sub(r"^#+\s*", "", (text or "").strip())


def page_row(index: int, result: PairResult) -> dict[str, Any]:
    return {
        "id": index,
        "tier": TIER_KEYS.get(result.tier, "error"),
        "label": result.title,
        "oldUrl": result.old_url,
        "newUrl": result.new_url,
        "similarity": (None if result.similarity is None
                       else round(result.similarity * 100)),
        # The number similarity hides. A page can read as 86% similar with 41%
        # of its text unaccounted for, which is the case this tool exists for.
        "coverage": (None if result.coverage is None
                     else round(result.coverage * 100)),
        "score": result.score,
        "confidence": result.confidence,
        "snapshot": result.snapshot[:8] if result.snapshot else "",
        "checked": (result.compared_at or "")[:16].replace("T", " "),
        "problems": list(result.problems),
        "detail": page_detail(result),
    }


def discovery_block(discovery: Discovery | None) -> dict[str, Any] | None:
    """The half of the answer no content diff can produce.

    A page that no longer exists has nothing to compare against, so it appears
    in no per-pair record. Without this block the dashboard would render a
    confident report that silently omits the worst outcome in a migration.
    """
    if discovery is None:
        return None
    return {
        "oldRoot": discovery.old_root,
        "newRoot": discovery.new_root,
        "discoveredAt": discovery.discovered_at,
        "oldTotal": discovery.old_total,
        "newTotal": discovery.new_total,
        "matched": discovery.matched,
        "matchedPairs": discovery.matched_pairs,
        "migratedShare": round(discovery.migrated_share, 4),
        "notMigrated": discovery.not_migrated,
        "netNew": discovery.net_new,
        "unreachable": (
            [{**p, "side": "old"} for p in discovery.unreachable_old]
            + [{**p, "side": "new"} for p in discovery.unreachable_new]
        ),
        "labelSignals": discovery.label_signals,
    }


def redirect_rows(results: list[PairResult],
                  discovery: Discovery | None) -> list[dict[str, Any]]:
    """The old -> new map, which the build plan wants as its own artifact.

    Built from what discovery matched, not from what was later compared. The
    two differ whenever the pair cap bites, and a redirect map that quietly
    omits pages because nobody diffed their content is wrong: a matched pair is
    a redirect worth writing whether or not its text was read.

    Pages with no counterpart are listed too, with no target. Those are the
    rows that need a human to decide, and leaving them out would make the map
    look complete when it is not.
    """
    pairs = (discovery.matched_pairs if discovery and discovery.matched_pairs
             else None)
    if pairs is not None:
        rows = [
            {"oldUrl": p.get("oldUrl", ""), "newUrl": p.get("newUrl", ""),
             "type": "301", "status": "matched",
             "label": p.get("path") or p.get("oldUrl", "")}
            for p in pairs
        ]
    else:
        # Older records predate matched_pairs; fall back to what was compared.
        rows = [
            {"oldUrl": r.old_url, "newUrl": r.new_url, "type": "301",
             "status": "matched", "label": r.title}
            for r in results if r.tier != "Unknown"
        ]
    for page in (discovery.not_migrated if discovery else []):
        rows.append({"oldUrl": page.get("url", ""), "newUrl": "",
                     "type": "", "status": "needs review",
                     "label": page.get("title") or page.get("path", "")})
    return rows


def build_payload(results: list[PairResult],
                  discovery: Discovery | None) -> dict[str, Any]:
    pages = [page_row(i + 1, r) for i, r in enumerate(results)]

    totals = {key: 0 for key in ("clean", "minor", "major", "missing", "error")}
    for page in pages:
        totals[page["tier"]] = totals.get(page["tier"], 0) + 1

    checked = [p["checked"] for p in pages if p["checked"]]
    # A pair cap leaves pages matched but uncompared. They belong to the run
    # and simply have no content verdict yet, so the dashboard says so rather
    # than letting them disappear between the two halves of the report.
    matched = discovery.matched if discovery else len(pages)
    return {
        "generatedAt": utcnow_iso(),
        "lastRun": max(checked) if checked else "",
        "totals": totals,
        "matched": matched,
        "notCompared": max(0, matched - len(pages)),
        "discovery": discovery_block(discovery),
        "pages": pages,
        "redirects": redirect_rows(results, discovery),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.export_web",
        description="Export the results store as one JSON for the React dashboard.")
    ap.add_argument("--results", default="data/run", metavar="DIR",
                    help="folder written by src.compare / src.discover_cli")
    ap.add_argument("--out", default="dashboard-react/public/data.json",
                    metavar="FILE", help="where to write the JSON")
    args = ap.parse_args(argv)

    results = load_results(args.results)
    discovery = load_discovery(args.results)
    if not results and discovery is None:
        print(f"nothing found in {args.results}; run src.discover_cli and "
              f"src.compare first", file=sys.stderr)
        return 1

    payload = build_payload(results, discovery)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    missing = len(payload["discovery"]["notMigrated"]) if payload["discovery"] else 0
    print(f"wrote {out}")
    print(f"  {len(payload['pages'])} compared page(s), "
          f"{missing} with no counterpart, "
          f"{len(payload['redirects'])} redirect row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
