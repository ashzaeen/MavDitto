import pytest

from src.textdiff import change_ratio, word_diff


def _text(segments, kind=None):
    return "".join(s.text for s in segments if kind is None or s.kind == kind)


# --- word diff ------------------------------------------------------------

def test_identical_text_is_all_equal():
    old, new = word_diff("the fee is $75", "the fee is $75")
    assert [s.kind for s in old] == ["equal"]
    assert [s.kind for s in new] == ["equal"]


def test_segments_rebuild_the_original_text_exactly():
    """A highlighted passage has to read as the passage; if rebuilding it
    reflows or drops whitespace, the highlighting has rewritten the evidence."""
    a = "Applications  close March 1.\nThe fee is $75."
    b = "Applications close March 1. No fee is charged."
    old, new = word_diff(a, b)
    assert _text(old) == a
    assert _text(new) == b


def test_removed_words_are_marked_on_the_old_side_only():
    old, new = word_diff("the fee is $75 and non-refundable", "the fee is $75")
    assert "non-refundable" in _text(old, "delete")
    assert not [s for s in new if s.kind == "delete"]


def test_added_words_are_marked_on_the_new_side_only():
    old, new = word_diff("the fee is $75", "the application fee is $75")
    assert "application" in _text(new, "insert")
    assert not [s for s in old if s.kind == "insert"]


def test_recapitalization_is_not_a_change():
    """A migration that restyles a heading has not changed what the page says."""
    old, new = word_diff("Admission Requirements", "ADMISSION REQUIREMENTS")
    assert [s.kind for s in old] == ["equal"]


def test_empty_sides_do_not_crash():
    assert word_diff("", "") == ([], [])
    old, new = word_diff("something", "")
    assert [s.kind for s in old] == ["delete"] and new == []


def test_change_ratio_measures_what_did_not_survive():
    assert change_ratio("a b c d", "a b c d") == 0.0
    assert change_ratio("a b c d", "") == 1.0
    assert change_ratio("a b c d", "a b") == pytest.approx(0.5)


# --- item-level diff, for lists and tables ---------------------------------

def test_identical_items_are_all_kept():
    from src.textdiff import diff_items

    old, new = diff_items(["Transcript", "Essay"], ["Transcript", "Essay"])
    assert [d.kind for d in old] == ["kept", "kept"]
    assert [d.kind for d in new] == ["kept", "kept"]


def test_a_removed_item_is_dropped_and_the_rest_stay_kept():
    from src.textdiff import diff_items

    old, new = diff_items(["Transcript", "Essay", "Two letters"],
                          ["Transcript", "Essay"])
    assert [d.kind for d in old] == ["kept", "kept", "dropped"]
    assert [d.kind for d in new] == ["kept", "kept"]


def test_a_new_item_is_added():
    from src.textdiff import diff_items

    old, new = diff_items(["Transcript"], ["Transcript", "Essay"])
    assert [d.kind for d in old] == ["kept"]
    assert [d.kind for d in new] == ["kept", "added"]


def test_a_reworded_item_is_paired_not_dropped_and_added():
    """A bullet whose wording changed should read as one changed item, not as
    an unrelated drop plus an unrelated addition."""
    from src.textdiff import diff_items

    old, new = diff_items(["Fall 2026 | March 1"], ["Fall 2026 | March 15"])
    assert [d.kind for d in old] == ["changed"]
    assert [d.kind for d in new] == ["changed"]


def test_an_unrelated_replacement_is_a_drop_plus_an_addition():
    """Below the reword floor there is nothing to pair -- forcing a match would
    hide one drop and one addition as a single vague 'change'."""
    from src.textdiff import diff_items

    old, new = diff_items(["Submit two letters of recommendation"],
                          ["Campus tours run every Friday"])
    assert [d.kind for d in old] == ["dropped"]
    assert [d.kind for d in new] == ["added"]


def test_item_order_is_not_disturbed_by_a_middle_drop():
    from src.textdiff import diff_items

    old, new = diff_items(["A", "B", "C"], ["A", "C"])
    assert [d.text for d in old] == ["A", "B", "C"]
    assert [d.kind for d in old] == ["kept", "dropped", "kept"]
    assert [d.text for d in new] == ["A", "C"]
