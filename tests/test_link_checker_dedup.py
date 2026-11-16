from src.link_checker.dedup import dedup
from src.link_checker.models import CATEGORY_ANCHOR, CATEGORY_INTERNAL_OTHER, RawLink

ROOT = "https://e.edu/"


def test_the_same_link_on_two_pages_collapses_into_one_entry():
    raw = [
        RawLink(url="https://e.edu/apply", text="Apply", region="nav", found_on="https://e.edu/a"),
        RawLink(url="https://e.edu/apply", text="Apply now", region="nav", found_on="https://e.edu/b"),
    ]
    checked = dedup(raw, root_prefix=ROOT)
    assert len(checked) == 1
    assert sorted(checked[0].found_on) == ["https://e.edu/a", "https://e.edu/b"]


def test_tracking_params_collapse_together():
    raw = [
        RawLink(url="https://e.edu/apply?utm_source=x", text="Apply", region="",
               found_on="https://e.edu/a"),
        RawLink(url="https://e.edu/apply", text="Apply", region="", found_on="https://e.edu/b"),
    ]
    checked = dedup(raw, root_prefix=ROOT)
    assert len(checked) == 1


def test_different_anchor_fragments_do_not_collapse_together():
    raw = [
        RawLink(url="https://e.edu/page#a", text="A", region="", found_on="https://e.edu/x"),
        RawLink(url="https://e.edu/page#b", text="B", region="", found_on="https://e.edu/x"),
    ]
    checked = dedup(raw, root_prefix=ROOT)
    assert len(checked) == 2
    assert {c.category for c in checked} == {CATEGORY_ANCHOR}


def test_the_same_page_found_twice_on_the_same_source_page_is_not_double_listed():
    raw = [
        RawLink(url="https://e.edu/apply", text="Apply", region="", found_on="https://e.edu/a"),
        RawLink(url="https://e.edu/apply", text="Apply", region="", found_on="https://e.edu/a"),
    ]
    checked = dedup(raw, root_prefix=ROOT)
    assert checked[0].found_on == ["https://e.edu/a"]


def test_dedup_assigns_a_category_to_each_unique_link():
    raw = [RawLink(url="https://external.example/", text="Vendor", region="",
                  found_on="https://e.edu/a")]
    checked = dedup(raw, root_prefix=ROOT)
    assert checked[0].category != CATEGORY_INTERNAL_OTHER  # external domain
