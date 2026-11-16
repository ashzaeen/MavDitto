"""Tests for the JSON the React dashboard reads.

This file is the contract between the pipeline and the dashboard, so the shape
is asserted here rather than discovered in a browser.
"""

import json

import pytest

from src.diff_semantic import diff_semantic
from src.diff_structural import diff_structural
from src.export_web import TIER_KEYS, build_payload, main, page_row
from src.models import Heading, Image, Link, PageContent
from src.pair import PagePair, PairSpec
from src.score import score_pair
from src.store import Discovery, build_result, save_discovery, save_result
from tests.test_diff_semantic import StubEmbedder

SECTIONS = StubEmbedder({"alpha": 1, "beta": 2, "gamma": 3})


def _page(text="", headings=None, links=None, images=None, **kw) -> PageContent:
    base = dict(url="https://old.uta.edu/a", fetched_url="https://old.uta.edu/a",
                source="live", status=200,
                text=text or " ".join(["body words"] * 80),
                headings=headings or [], links=links or [], images=images or [])
    return PageContent(**{**base, **kw})


def _sectioned(*names) -> PageContent:
    return _page(
        text="\n".join(f"{n.title()}\n" + " ".join([f"{n} detail wording"] * 20)
                       for n in names),
        headings=[Heading(2, n.title()) for n in names])


def _result(old, new, label="pair"):
    spec = PairSpec(f"https://old.uta.edu/{label}", f"https://new.uta.edu/{label}",
                    label=label)
    pair = PagePair(spec=spec, old=old, new=new)
    if pair.problems:
        return build_result(spec, pair, None, None, score_pair(pair, None, None))
    structural = diff_structural(old, new)
    semantic = diff_semantic(old, new, SECTIONS)
    return build_result(spec, pair, structural, semantic,
                        score_pair(pair, structural, semantic))


def _discovery(**kw) -> Discovery:
    defaults = dict(
        old_root="https://old.uta.edu", new_root="https://www.uta.edu",
        matched=1, old_total=3, new_total=4,
        not_migrated=[{"path": "/parking", "url": "https://old.uta.edu/parking",
                       "title": "Parking"}],
        net_new=[{"path": "/tour", "url": "https://www.uta.edu/tour", "title": "Tour"}],
        unreachable_old=[{"path": "/dead", "url": "https://old.uta.edu/dead",
                          "title": ""}])
    return Discovery(**{**defaults, **kw})


# --- the row contract -----------------------------------------------------

def test_every_tier_maps_to_a_dashboard_key():
    from src.score import RiskTier
    for tier in RiskTier:
        assert tier.label in TIER_KEYS


def test_an_uncompared_pair_becomes_a_visible_error_row():
    """The design renders this as "Couldn't check". Dropping the row instead
    would let a page nobody could fetch read as absent rather than unknown."""
    row = page_row(1, _result(_sectioned("alpha"), _page(status=404, text="")))
    assert row["tier"] == "error"
    assert row["detail"] is None
    assert row["problems"]


def test_coverage_travels_beside_similarity():
    """Similarity alone is the number that hides loss, so the row carries both."""
    row = page_row(1, _result(_sectioned("alpha", "beta"), _sectioned("alpha")))
    assert 0 <= row["similarity"] <= 100
    assert 0 <= row["coverage"] <= 100
    assert row["coverage"] < 100


def test_document_segments_rebuild_a_reworded_paragraphs_text():
    """A reworded block's word-level segments have to read as the passage; if
    rebuilding them drops or reflows text, the highlighting rewrote the
    evidence rather than marking it."""
    from src.export_web import _matched_content_blocks

    old_row, new_row = _matched_content_blocks({
        "kind": "paragraph", "section": "Fees", "verdict": "reworded",
        "similarity": 0.9,
        "old_text": "The application fee is $75 and is non-refundable once paid",
        "new_text": "The application fee is $75 and is non-refundable",
    })
    assert "".join(s["text"] for s in old_row["segments"]) == old_row["text"]
    assert "".join(s["text"] for s in new_row["segments"]) == new_row["text"]
    assert {s["kind"] for s in old_row["segments"]} <= {"plain", "removed"}
    assert {s["kind"] for s in new_row["segments"]} <= {"plain", "added"}


def test_dropped_headings_travel_with_the_counts():
    """Counts alone call a page clean when every heading changed."""
    detail = page_row(1, _result(_sectioned("alpha", "beta"),
                                 _sectioned("alpha")))["detail"]
    assert detail["headingsDropped"]


def test_caveats_reach_the_dashboard():
    """The original design showed a confidence note on Clean rows only; the
    reasons not to trust a verdict matter most on the rows that are not clean."""
    old = _page(source="wayback", snapshot_timestamp="20150601120000",
                text=_sectioned("alpha", "beta").text,
                headings=[Heading(2, "Alpha"), Heading(2, "Beta")])
    detail = page_row(1, _result(old, _sectioned("alpha")))["detail"]
    assert any("drift" in c for c in detail["caveats"])


def test_documents_are_their_own_row_when_the_old_page_had_any():
    old = _page(links=[Link("https://old.uta.edu/f.pdf", "Form", is_document=True)])
    detail = page_row(1, _result(old, _page()))["detail"]
    assert detail is not None
    assert detail["documentsOld"] == 1
    assert detail["documentsDropped"]


# --- the payload ----------------------------------------------------------

def test_payload_carries_discovery_so_missing_pages_are_not_lost():
    """A page that does not exist appears in no per-pair record, so without
    this block the dashboard would omit the worst outcome entirely."""
    payload = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))],
                            _discovery())
    assert payload["discovery"]["notMigrated"][0]["path"] == "/parking"
    assert payload["discovery"]["migratedShare"] == pytest.approx(0.5)


def test_payload_without_discovery_is_still_valid():
    payload = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))], None)
    assert payload["discovery"] is None
    assert payload["pages"]


def test_totals_count_every_row_including_the_unreadable_ones():
    results = [_result(_sectioned("alpha"), _sectioned("alpha"), "a"),
               _result(_sectioned("alpha"), _page(status=404, text=""), "b")]
    totals = build_payload(results, None)["totals"]
    assert sum(totals.values()) == 2
    assert totals["error"] == 1


def test_redirect_map_lists_pages_with_no_target():
    """Leaving them out would make the map look complete when it is not."""
    rows = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))],
                         _discovery())["redirects"]
    needs_review = [r for r in rows if r["status"] == "needs review"]
    assert len(needs_review) == 1
    assert needs_review[0]["newUrl"] == ""


# --- the CLI --------------------------------------------------------------

def test_cli_writes_a_file_the_dashboard_can_fetch(tmp_path):
    results_dir = tmp_path / "run"
    save_result(results_dir, _result(_sectioned("alpha", "beta"), _sectioned("alpha")))
    save_discovery(results_dir, _discovery())

    out = tmp_path / "web" / "data.json"
    assert main(["--results", str(results_dir), "--out", str(out)]) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["pages"] and payload["discovery"] and payload["redirects"]
    assert payload["generatedAt"]


def test_cli_reports_an_empty_results_folder_rather_than_writing_nothing(tmp_path):
    assert main(["--results", str(tmp_path), "--out", str(tmp_path / "x.json")]) == 1


# --- the redirect map is independent of the content comparison ------------

def test_redirect_map_lists_every_matched_pair_not_only_compared_ones():
    """A pair cap stops content being diffed; it does not stop the pages being
    matched. A redirect map that quietly omits them is wrong -- a matched pair
    is a redirect worth writing whether or not its text was read."""
    discovery = _discovery(
        matched=3,
        matched_pairs=[
            {"path": "/", "oldUrl": "https://old.uta.edu/",
             "newUrl": "https://www.uta.edu/", "method": "exact"},
            {"path": "/venues", "oldUrl": "https://old.uta.edu/venues",
             "newUrl": "https://www.uta.edu/venues", "method": "exact"},
            {"path": "/contact", "oldUrl": "https://old.uta.edu/contact",
             "newUrl": "https://www.uta.edu/contact", "method": "exact"},
        ])
    # Only one of the three was actually compared.
    payload = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))],
                            discovery)
    matched = [r for r in payload["redirects"] if r["status"] == "matched"]
    assert len(matched) == 3
    assert any("/venues" in r["oldUrl"] for r in matched)


def test_pages_matched_but_not_compared_are_counted():
    """Otherwise they vanish between the two halves of the report."""
    discovery = _discovery(matched=5, matched_pairs=[{"path": f"/p{i}"} for i in range(5)])
    payload = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))],
                            discovery)
    assert payload["matched"] == 5
    assert payload["notCompared"] == 4


def test_nothing_is_reported_uncompared_when_everything_was():
    payload = build_payload(
        [_result(_sectioned("alpha"), _sectioned("alpha"))],
        _discovery(matched=1, matched_pairs=[{"path": "/"}]))
    assert payload["notCompared"] == 0


def test_a_record_without_matched_pairs_still_produces_a_map():
    """Records written before matched_pairs existed must not lose their map."""
    payload = build_payload([_result(_sectioned("alpha"), _sectioned("alpha"))],
                            _discovery(matched_pairs=[]))
    assert [r for r in payload["redirects"] if r["status"] == "matched"]


# --- passages, structured for reading -------------------------------------

def test_the_page_is_rendered_as_a_document_on_both_sides():
    """The review screen is built as a document, not a single page-wide diff:
    a page-wide word diff marks every word when the pages differ a lot and
    says nothing."""
    detail = page_row(1, _result(_sectioned("alpha", "beta"),
                                 _sectioned("alpha")))["detail"]
    assert detail["oldDocument"]
    assert detail["newDocument"]
    content = [b for b in detail["oldDocument"] if b["type"] != "heading"]
    assert all("text" in b for b in content)


def test_a_wholesale_rewrite_is_not_offered_for_word_level_highlighting():
    """Above the noise ratio the aligner is matching coincidences rather than
    tracking an edit, and both columns come out striped."""
    from src.export_web import DIFF_NOISE_RATIO, _matched_content_blocks

    old_row, new_row = _matched_content_blocks({
        "kind": "paragraph", "section": "x", "verdict": "reworded",
        "similarity": 0.6,
        "old_text": "the application fee is seventy five dollars each term",
        "new_text": "campus tours run every Friday throughout the spring",
    })
    assert old_row["changeRatio"] > DIFF_NOISE_RATIO
    assert old_row["worthHighlighting"] is False
    assert "segments" not in old_row
    assert "segments" not in new_row


def test_a_light_edit_is_offered_for_highlighting():
    from src.export_web import _matched_content_blocks

    old_row, new_row = _matched_content_blocks({
        "kind": "paragraph", "section": "x", "verdict": "reworded",
        "similarity": 0.95,
        "old_text": "The application fee is $75 and is non-refundable once paid",
        "new_text": "The application fee is $75 and is non-refundable",
    })
    assert old_row["worthHighlighting"] is True
    assert old_row["segments"] and new_row["segments"]


def test_outline_markers_do_not_leak_into_the_interface():
    """Headings are stored as '## Requirements' so a diff can compare level and
    text together. That is a storage detail."""
    from src.export_web import _clean_heading

    assert _clean_heading("#### Have a Promo Code?") == "Have a Promo Code?"
    assert _clean_heading("## Requirements") == "Requirements"
    assert _clean_heading("Already clean") == "Already clean"


def test_dropped_headings_reach_the_dashboard_without_markers():
    detail = page_row(1, _result(_sectioned("alpha", "beta"),
                                 _sectioned("alpha")))["detail"]
    assert detail["headingsDropped"]
    assert not any(h.startswith("#") for h in detail["headingsDropped"])


# --- the document view, end to end from real HTML --------------------------
#
# A real page's Block list only exists once it has gone through extract(),
# not through the synthetic _page()/_sectioned() helpers above -- those build
# a PageContent with only `.text`, which is exactly the case the document
# builder falls back for. These tests go through extract() so the review
# screen's actual reason for existing -- a list stays a list, a table stays a
# table -- is checked against real DOM structure, not a stand-in for it.

def _result_with_embedder(old, new, embedder, label="doc"):
    spec = PairSpec(f"https://old.uta.edu/{label}", f"https://new.uta.edu/{label}",
                    label=label)
    pair = PagePair(spec=spec, old=old, new=new)
    if pair.problems:
        return build_result(spec, pair, None, None, score_pair(pair, None, None))
    structural = diff_structural(old, new)
    semantic = diff_semantic(old, new, embedder)
    return build_result(spec, pair, structural, semantic,
                        score_pair(pair, structural, semantic))


def test_a_real_page_keeps_its_list_and_table_structure_through_export():
    """The case the document view exists for: a section with several
    paragraphs, a list and a table should read as exactly that, not as a
    stream of text blobs that all carry the same heading label."""
    from src.extract import extract

    filler = " ".join(["Applicants must submit official transcripts."] * 20)
    html = ("<html><body><main><h1>Admissions</h1>"
            f"<p>{filler}</p>"
            "<h2>Requirements</h2>"
            "<ul><li>Transcript</li><li>Essay</li><li>Two letters</li></ul>"
            "<h2>Deadlines</h2>"
            "<table><tr><th>Term</th><th>Date</th></tr>"
            "<tr><td>Fall</td><td>March 1</td></tr>"
            "<tr><td>Spring</td><td>October 1</td></tr></table>"
            "</main></body></html>")

    old = extract(html, "https://old.uta.edu/admissions")
    new = extract(html, "https://new.uta.edu/admissions")   # identical: everything kept
    # Distinct groups per block, so the greedy matcher pairs paragraph with
    # paragraph, list with list, table with table, rather than every
    # unrecognized chunk colliding in one catch-all bucket.
    embedder = StubEmbedder({"applicants": 1, "transcript": 2, "term": 3})
    detail = page_row(1, _result_with_embedder(old, new, embedder))["detail"]

    old_kinds = [b["type"] for b in detail["oldDocument"]]
    assert old_kinds.count("heading") == 3
    assert "list" in old_kinds and "table" in old_kinds

    old_list = next(b for b in detail["oldDocument"] if b["type"] == "list")
    assert [i["text"] for i in old_list["items"]] == ["Transcript", "Essay", "Two letters"]

    old_table = next(b for b in detail["oldDocument"] if b["type"] == "table")
    assert old_table["columns"] == ["Term", "Date"]
    assert len(old_table["items"]) == 2

    new_kinds = [b["type"] for b in detail["newDocument"]]
    assert new_kinds.count("heading") == 3
    assert "list" in new_kinds and "table" in new_kinds


def test_a_list_with_no_new_page_counterpart_is_dropped_item_and_all():
    """A whole section removed on the new page has to show up as a dropped
    list, not silently vanish because nothing in a flat word-budget chunk
    happened to notice."""
    from src.extract import extract

    filler = " ".join(["Applicants must submit official transcripts."] * 20)
    old_html = ("<html><body><main><h1>Admissions</h1>"
               f"<p>{filler}</p>"
               "<h2>Requirements</h2>"
               "<ul><li>Transcript</li><li>Essay</li></ul>"
               "</main></body></html>")
    new_html = ("<html><body><main><h1>Admissions</h1>"
               f"<p>{filler}</p></main></body></html>")

    old = extract(old_html, "https://old.uta.edu/admissions")
    new = extract(new_html, "https://new.uta.edu/admissions")
    embedder = StubEmbedder({"applicants": 1})
    detail = page_row(1, _result_with_embedder(old, new, embedder))["detail"]

    old_list = next(b for b in detail["oldDocument"] if b["type"] == "list")
    assert old_list["verdict"] == "dropped"
    assert [i["verdict"] for i in old_list["items"]] == ["dropped", "dropped"]

    requirements = next(b for b in detail["oldDocument"]
                        if b["type"] == "heading" and b["text"] == "Requirements")
    assert requirements["verdict"] == "dropped"
