import json

import pytest

from src.diff_semantic import diff_semantic
from src.diff_structural import diff_structural
from src.models import Heading, Link, PageContent
from src.pair import PagePair, PairSpec
from src.score import score_pair
from src.store import (
    PairResult, build_result, load_results, result_filename, save_result, tally,
)
from tests.test_diff_semantic import StubEmbedder

SECTIONS = StubEmbedder({"alpha": 1, "beta": 2})


def _page(text="", headings=None, links=None, **kw) -> PageContent:
    base = dict(url="https://old.uta.edu/a", fetched_url="https://old.uta.edu/a",
                source="live", status=200,
                text=text or " ".join(["body words"] * 80),
                headings=headings or [], links=links or [])
    return PageContent(**{**base, **kw})


def _sectioned(*names) -> PageContent:
    return _page(
        text="\n".join(f"{n.title()}\n" + " ".join([f"{n} detail wording"] * 20)
                       for n in names),
        headings=[Heading(2, n.title()) for n in names])


def _record(old: PageContent, new: PageContent, label="pair") -> PairResult:
    # Distinct URLs per label: records are filed by the pair's two URLs, so
    # reusing one would make each record overwrite the last.
    spec = PairSpec(f"https://old.uta.edu/{label}", f"https://new.uta.edu/{label}",
                    label=label)
    pair = PagePair(spec=spec, old=old, new=new)
    structural = diff_structural(old, new)
    semantic = diff_semantic(old, new, SECTIONS)
    risk = score_pair(pair, structural, semantic)
    return build_result(spec, pair, structural, semantic, risk)


# --- filenames ------------------------------------------------------------

def test_pairs_sharing_a_new_url_get_different_filenames():
    """Several old pages consolidating onto one new page is an ordinary
    migration pattern; keying on the new URL alone made them overwrite."""
    a = result_filename("https://old.uta.edu/a", "https://new.uta.edu/x")
    b = result_filename("https://old.uta.edu/b", "https://new.uta.edu/x")
    assert a != b


def test_filename_is_stable_across_calls():
    args = ("https://old.uta.edu/a", "https://new.uta.edu/x")
    assert result_filename(*args) == result_filename(*args)


# --- round trip -----------------------------------------------------------

def test_record_round_trips_through_disk(tmp_path):
    record = _record(_sectioned("alpha", "beta"), _sectioned("alpha"))
    save_result(tmp_path, record)
    loaded = load_results(tmp_path)
    assert len(loaded) == 1
    restored = loaded[0]
    assert restored.tier == record.tier
    assert restored.score == record.score
    assert restored.old.text == record.old.text
    assert len(restored.passages) == len(record.passages)


def test_record_keeps_both_pages_so_the_dashboard_need_not_refetch(tmp_path):
    record = _record(_sectioned("alpha", "beta"), _sectioned("alpha"))
    save_result(tmp_path, record)
    restored = load_results(tmp_path)[0]
    assert restored.old is not None and restored.new is not None
    assert restored.old.headings and restored.old.word_count > 0


def test_results_load_worst_first(tmp_path):
    page = _sectioned("alpha", "beta")
    save_result(tmp_path, _record(page, page, label="clean"))
    save_result(tmp_path, _record(page, _sectioned("alpha"), label="missing"))
    assert [r.label for r in load_results(tmp_path)] == ["missing", "clean"]


# --- resilience -----------------------------------------------------------

def test_unreadable_file_is_skipped_not_fatal(tmp_path):
    """A half-written record from an interrupted run must not stop a reviewer
    seeing the rest."""
    save_result(tmp_path, _record(_sectioned("alpha"), _sectioned("alpha")))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(load_results(tmp_path)) == 1


def test_unrelated_json_in_the_folder_is_ignored(tmp_path):
    save_result(tmp_path, _record(_sectioned("alpha"), _sectioned("alpha")))
    (tmp_path / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    assert len(load_results(tmp_path)) == 1


def test_missing_directory_returns_nothing(tmp_path):
    assert load_results(tmp_path / "nope") == []


# --- what the dashboard reads --------------------------------------------

def test_findings_merge_both_stages_worst_first(tmp_path):
    record = _record(_sectioned("alpha", "beta"), _sectioned("alpha"))
    severities = [f["severity"] for f in record.findings]
    order = {"high": 3, "medium": 2, "low": 1, "info": 0}
    assert severities == sorted(severities, key=lambda s: -order[s])


def test_title_falls_back_through_label_then_page_title_then_url():
    assert PairResult("o", "n", label="Label").title == "Label"
    assert PairResult("o", "n", new=_page(title="Page")).title == "Page"
    assert PairResult("o", "https://new.uta.edu/x").title == "https://new.uta.edu/x"


def test_tally_counts_by_tier(tmp_path):
    page = _sectioned("alpha", "beta")
    save_result(tmp_path, _record(page, page, label="a"))
    save_result(tmp_path, _record(page, _sectioned("alpha"), label="b"))
    counts = tally(load_results(tmp_path))
    assert counts["Clean"] == 1 and counts["Missing content"] == 1


def test_uncompared_pair_is_recorded_with_its_problems(tmp_path):
    old, new = _sectioned("alpha"), _page(status=404, text="")
    spec = PairSpec(old.url, new.url, label="broken")
    pair = PagePair(spec=spec, old=old, new=new)
    record = build_result(spec, pair, None, None, score_pair(pair, None, None))
    save_result(tmp_path, record)
    restored = load_results(tmp_path)[0]
    assert restored.tier == "Unknown"
    assert any("404" in p for p in restored.problems)
    assert restored.similarity is None


def test_schema_version_is_written(tmp_path):
    path = save_result(tmp_path, _record(_sectioned("alpha"), _sectioned("alpha")))
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] >= 1


def test_same_urls_at_different_snapshots_do_not_collide(tmp_path):
    """Comparing one page against captures from several dates is a legitimate
    run -- it is how you watch a page drift -- and those pairs share both URLs
    exactly, so the snapshot has to be part of the key."""
    page = _sectioned("alpha", "beta")
    for stamp, label in (("20190101000000", "2019"), ("20240101000000", "2024")):
        old = _page(text=page.text, headings=page.headings,
                    source="wayback", snapshot_timestamp=stamp)
        spec = PairSpec("https://old.uta.edu/x", "https://new.uta.edu/x",
                        label=label, timestamp=stamp[:8])
        pair = PagePair(spec=spec, old=old, new=_sectioned("alpha"))
        structural = diff_structural(old, pair.new)
        semantic = diff_semantic(old, pair.new, SECTIONS)
        save_result(tmp_path, build_result(spec, pair, structural, semantic,
                                           score_pair(pair, structural, semantic)))
    assert len(load_results(tmp_path)) == 2


def test_filename_discriminator_changes_the_name(tmp_path):
    base = result_filename("https://o/a", "https://n/a")
    assert base != result_filename("https://o/a", "https://n/a", "20190101|2019")


# --- a run replaces, rather than adds to, its folder ----------------------

def test_clear_results_removes_our_records(tmp_path):
    """Without this, comparing a second pair of sites leaves the first run's
    pages in the table beside a discovery record describing different sites."""
    from src.store import (
        Discovery, clear_results, load_discovery, save_discovery,
    )

    save_result(tmp_path, _record(_sectioned("alpha"), _sectioned("alpha"), "a"))
    save_result(tmp_path, _record(_sectioned("beta"), _sectioned("beta"), "b"))
    save_discovery(tmp_path, Discovery(old_root="o", new_root="n"))

    assert clear_results(tmp_path) == 3
    assert load_results(tmp_path) == []
    assert load_discovery(tmp_path) is None


def test_clear_results_leaves_other_files_alone(tmp_path):
    """A results folder may hold notes, CSVs, or someone else's data, and a
    results writer has no business deleting those."""
    from src.store import clear_results

    save_result(tmp_path, _record(_sectioned("alpha"), _sectioned("alpha")))
    (tmp_path / "notes.json").write_text('{"mine": true}', encoding="utf-8")
    (tmp_path / "url_pairs.csv").write_text("old_url,new_url\n", encoding="utf-8")

    clear_results(tmp_path)
    assert (tmp_path / "notes.json").is_file()
    assert (tmp_path / "url_pairs.csv").is_file()


def test_clear_results_on_a_missing_folder_is_not_an_error(tmp_path):
    from src.store import clear_results
    assert clear_results(tmp_path / "nope") == 0
