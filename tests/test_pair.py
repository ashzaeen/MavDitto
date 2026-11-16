import csv
import pytest

from src.models import PageContent
from src.pair import PagePair, PairSpec, load_pairs_csv, write_pairs_csv


def _page(**kw) -> PageContent:
    defaults = dict(url="https://e.edu/a", fetched_url="https://e.edu/a",
                    source="live", status=200, text="word " * 200)
    return PageContent(**{**defaults, **kw})


# --- PairSpec -------------------------------------------------------------

def test_both_sides_default_to_live():
    """The pre-launch case -- old site still serving, new site being built --
    is the common one, so it needs no flags."""
    spec = PairSpec(old_url="https://old.edu/a", new_url="https://new.edu/a")
    assert spec.old_source == "live"
    assert spec.new_source == "live"


def test_each_side_carries_its_own_source():
    spec = PairSpec(old_url="https://old.edu/a", new_url="https://new.edu/a",
                    old_source="wayback")
    assert (spec.old_source, spec.new_source) == ("wayback", "live")


def test_bad_source_is_rejected_early():
    with pytest.raises(ValueError, match="old_source"):
        PairSpec(old_url="a", new_url="b", old_source="archive")


# --- PagePair -------------------------------------------------------------

def test_pair_is_ok_when_both_sides_fetched():
    pair = PagePair(spec=PairSpec("a", "b"), old=_page(), new=_page())
    assert pair.both_ok
    assert pair.problems == []


def test_fetch_failures_are_reported_separately_from_content_loss():
    """A 404 on the new side is a broken fetch, not a page that lost content;
    conflating them would push fetch errors to the top of a risk ranking."""
    pair = PagePair(spec=PairSpec("a", "b"), old=_page(), new=_page(status=404))
    assert not pair.both_ok
    assert pair.problems == ["new page returned HTTP 404"]


def test_thin_page_is_flagged_as_unreliable():
    pair = PagePair(spec=PairSpec("a", "b"), old=_page(text="tiny"), new=_page())
    assert any("only 1 words" in p for p in pair.problems)


# --- url_pairs.csv --------------------------------------------------------

def _write(tmp_path, rows, header):
    p = tmp_path / "pairs.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return p


def test_csv_with_explicit_per_side_sources(tmp_path):
    p = _write(tmp_path,
               [["https://old.edu/a", "https://new.edu/a", "live", "live", "", "home"]],
               ["old_url", "new_url", "old_source", "new_source", "timestamp", "label"])
    spec = load_pairs_csv(p)[0]
    assert (spec.old_source, spec.new_source, spec.label) == ("live", "live", "home")


def test_csv_accepts_the_plans_original_single_source_column(tmp_path):
    """The build plan's url_pairs.csv has one `source` column; it describes the
    old side, since the new side is live by definition in that framing."""
    p = _write(tmp_path, [["https://old.edu/a", "https://new.edu/a", "wayback"]],
               ["old_url", "new_url", "source"])
    spec = load_pairs_csv(p)[0]
    assert (spec.old_source, spec.new_source) == ("wayback", "live")


def test_csv_skips_blank_padding_rows(tmp_path):
    p = _write(tmp_path,
               [["https://old.edu/a", "https://new.edu/a"], ["", ""], ["  ", ""]],
               ["old_url", "new_url"])
    assert len(load_pairs_csv(p)) == 1


def test_csv_missing_required_column_is_an_error(tmp_path):
    p = _write(tmp_path, [["https://new.edu/a"]], ["new_url"])
    with pytest.raises(ValueError, match="old_url"):
        load_pairs_csv(p)


def test_csv_bad_source_names_the_line(tmp_path):
    p = _write(tmp_path, [["https://old.edu/a", "https://new.edu/a", "ftp"]],
               ["old_url", "new_url", "old_source"])
    with pytest.raises(ValueError, match="line 2"):
        load_pairs_csv(p)


def test_csv_round_trip(tmp_path):
    specs = [PairSpec("https://old.edu/a", "https://new.edu/a", "wayback", "live",
                      "20150601", "dept home")]
    p = tmp_path / "out.csv"
    write_pairs_csv(specs, p)
    assert load_pairs_csv(p) == specs


def test_csv_comment_lines_are_skipped_before_the_header(tmp_path):
    """url_pairs.csv is hand-edited, so it carries # notes; without stripping
    them DictReader takes the first comment as the column names."""
    p = tmp_path / "pairs.csv"
    p.write_text(
        "# pairs for the spring cutover\n"
        "# old_source: live | wayback\n"
        "old_url,new_url,old_source\n"
        "https://old.edu/a,https://new.edu/a,wayback\n",
        encoding="utf-8")
    specs = load_pairs_csv(p)
    assert len(specs) == 1
    assert specs[0].old_source == "wayback"


def test_csv_error_line_numbers_survive_comment_stripping(tmp_path):
    p = tmp_path / "pairs.csv"
    p.write_text(
        "# a note\n"
        "old_url,new_url,old_source\n"
        "https://old.edu/a,https://new.edu/a,live\n"
        "https://old.edu/b,https://new.edu/b,ftp\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="line 4"):
        load_pairs_csv(p)
