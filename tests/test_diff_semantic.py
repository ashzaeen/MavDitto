import numpy as np
import pytest

from src.diff_semantic import (
    COVERAGE_ALARM, MATCH_STRONG, MATCH_WEAK, diff_semantic, match_chunks,
)
from src.embed import Chunk, LexicalEmbedder, chunk_page
from src.extract import extract
from src.models import Heading, PageContent, Severity
from tests.fixtures import UNIVERSITY_PAGE, UNIVERSITY_PAGE_DEGRADED


class StubEmbedder:
    """Maps texts to vectors by a caller-supplied group id.

    Texts sharing a group get identical vectors (similarity 1.0); different
    groups are orthogonal (similarity 0.0). That makes threshold behaviour
    exact instead of approximate, so a test failure means the logic changed
    rather than a model score drifting.
    """

    def __init__(self, groups: dict[str, int], dims: int = 32):
        self.groups = groups
        self.dims = dims

    def encode(self, texts):
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, text in enumerate(texts):
            lowered = text.lower()
            key = next((k for k in self.groups if k.lower() in lowered), None)
            out[row, self.groups.get(key, 0) if key else self.dims - 1] = 1.0
        return out


def _page(text: str, headings: list[str] | None = None) -> PageContent:
    return PageContent(
        url="https://e.edu/a", fetched_url="https://e.edu/a", source="live",
        status=200, text=text,
        headings=[Heading(2, h) for h in (headings or [])],
    )


# --- chunking -------------------------------------------------------------

def test_chunks_split_on_headings():
    page = _page("Alpha\nBody of alpha section here.\nBeta\nBody of beta section.",
                 ["Alpha", "Beta"])
    chunks = chunk_page(page)
    assert [c.section for c in chunks] == ["Alpha", "Beta"]
    assert "alpha section" in chunks[0].text


def test_heading_travels_with_its_section():
    """A bare heading on its own would be a two-word chunk that matches almost
    anything."""
    page = _page("Deadlines\nPriority closes February 15.", ["Deadlines"])
    chunks = chunk_page(page)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("Deadlines")


def test_trafilatura_single_newlines_are_treated_as_block_breaks():
    """Regression: splitting on blank lines put an entire page in one chunk,
    which defeats per-passage matching completely. trafilatura separates blocks
    with a single newline."""
    page = _page(
        "Applications for the fall semester are due by the first of March each year.\n"
        "Freshman applicants must submit official high school transcripts for review.\n"
        "Priority scholarship consideration closes on the fifteenth of February."
    )
    assert len(chunk_page(page, target_words=10)) == 3


def test_long_text_is_split_into_several_chunks():
    page = _page("\n".join(f"Paragraph number {i} with a few words." for i in range(20)))
    chunks = chunk_page(page)
    assert len(chunks) > 1
    assert all(c.word_count <= 200 for c in chunks)


def test_tiny_trailing_fragment_is_folded_back():
    page = _page("A long opening paragraph with plenty of words to fill it out here.\nOk.")
    chunks = chunk_page(page, target_words=12)
    assert all(c.word_count >= 8 for c in chunks)


def test_empty_page_yields_no_chunks():
    assert chunk_page(_page("")) == []


# --- chunking from real blocks ---------------------------------------------
#
# Once a page carries real Blocks (see models.Block / extract.extract_blocks),
# chunk_page stops guessing chunk boundaries from a word budget: one block is
# one chunk. This is what a section of twenty paragraphs needed -- each one
# becomes its own passage instead of a handful of slices that all carry the
# same heading label.

def _blocked_page(blocks) -> PageContent:
    return PageContent(url="https://e.edu/a", fetched_url="https://e.edu/a",
                       source="live", status=200, blocks=blocks)


def test_a_page_with_blocks_yields_one_chunk_per_content_block():
    from src.models import Block

    page = _blocked_page([
        Block(kind="heading", level=1, text="Admissions"),
        Block(kind="paragraph", text="First paragraph.", heading_path=["Admissions"]),
        Block(kind="paragraph", text="Second paragraph.", heading_path=["Admissions"]),
        Block(kind="paragraph", text="Third paragraph.", heading_path=["Admissions"]),
    ])
    chunks = chunk_page(page)
    assert [c.text for c in chunks] == [
        "First paragraph.", "Second paragraph.", "Third paragraph."]
    assert all(c.section == "Admissions" for c in chunks)


def test_heading_blocks_do_not_become_chunks():
    """Headings are structure, not a passage to match -- StructuralDiff already
    covers whether a heading itself survived."""
    from src.models import Block

    page = _blocked_page([
        Block(kind="heading", level=1, text="Admissions"),
        Block(kind="paragraph", text="Body text.", heading_path=["Admissions"]),
    ])
    assert len(chunk_page(page)) == 1


def test_a_list_block_becomes_one_chunk_carrying_its_items():
    from src.models import Block

    page = _blocked_page([
        Block(kind="list", items=["Transcript", "Essay"], text="Transcript Essay"),
    ])
    chunks = chunk_page(page)
    assert len(chunks) == 1
    assert chunks[0].kind == "list"
    assert chunks[0].items == ["Transcript", "Essay"]


def test_a_table_block_carries_its_columns():
    from src.models import Block

    page = _blocked_page([
        Block(kind="table", columns=["Term", "Date"], items=["Fall | March 1"],
             text="Term | Date Fall | March 1"),
    ])
    chunks = chunk_page(page)
    assert chunks[0].kind == "table"
    assert chunks[0].columns == ["Term", "Date"]


def test_a_page_with_no_blocks_still_falls_back_to_word_budget_chunking():
    """Most tests, and every result written before blocks existed, build a
    PageContent with only `.text` -- that must keep working exactly as
    before."""
    page = _page("Alpha\nBody of alpha section here.\nBeta\nBody of beta section.",
                 ["Alpha", "Beta"])
    assert page.blocks == []
    chunks = chunk_page(page)
    assert [c.section for c in chunks] == ["Alpha", "Beta"]
    assert all(c.kind == "paragraph" for c in chunks)


# --- matching -------------------------------------------------------------

def _chunks(*texts) -> list[Chunk]:
    return [Chunk(t, "", i) for i, t in enumerate(texts)]


def test_reordered_sections_still_match():
    """Migrations reorder sections freely; positional matching would report a
    moved section as one drop plus one addition."""
    old, new = _chunks("alpha", "beta"), _chunks("beta", "alpha")
    emb = StubEmbedder({"alpha": 1, "beta": 2})
    matches, added = match_chunks(old, new, emb.encode([c.text for c in old]),
                                  emb.encode([c.text for c in new]))
    assert not added
    assert all(m.similarity == pytest.approx(1.0) for m in matches)


def test_a_shorter_merged_chunk_cannot_absorb_everything():
    """Two old passages collapsed into a new one no longer than either: the
    second is genuinely unaccounted for, and saying so is the honest reading."""
    old, new = _chunks("alpha one", "alpha two"), _chunks("alpha merged")
    emb = StubEmbedder({"alpha": 1})
    matches, added = match_chunks(old, new, emb.encode([c.text for c in old]),
                                  emb.encode([c.text for c in new]))
    assert sum(m.is_dropped for m in matches) == 1
    assert not added


def test_a_long_merged_chunk_absorbs_both_old_passages():
    """Merging two sections under one heading is an ordinary migration edit.
    A strict one-claim-per-chunk rule called half such a page lost even though
    every word survived."""
    old = _chunks("alpha " * 40, "alpha " * 40)
    new = _chunks("alpha " * 90)
    emb = StubEmbedder({"alpha": 1})
    matches, added = match_chunks(old, new, emb.encode([c.text for c in old]),
                                  emb.encode([c.text for c in new]))
    assert not any(m.is_dropped for m in matches)
    assert not added


def test_unmatched_old_chunk_keeps_its_best_score_for_context():
    old, new = _chunks("alpha"), _chunks("zeta")
    emb = StubEmbedder({"alpha": 1, "zeta": 2})
    matches, _ = match_chunks(old, new, emb.encode(["alpha"]), emb.encode(["zeta"]))
    assert matches[0].is_dropped
    assert matches[0].similarity == pytest.approx(0.0)


def test_no_new_chunks_means_everything_dropped():
    old = _chunks("alpha", "beta")
    emb = LexicalEmbedder()
    matches, added = match_chunks(old, [], emb.encode([c.text for c in old]),
                                  np.zeros((0, 256), dtype=np.float32))
    assert all(m.is_dropped for m in matches) and not added


# --- the whole diff -------------------------------------------------------

def test_identical_pages_are_fully_covered():
    page = extract(UNIVERSITY_PAGE, "https://old.edu/admissions")
    diff = diff_semantic(page, page, LexicalEmbedder())
    assert diff.coverage == pytest.approx(1.0)
    assert diff.overall_similarity == pytest.approx(1.0, abs=1e-5)
    assert diff.dropped == []
    assert not any(f.severity >= Severity.MEDIUM for f in diff.findings)


def test_dropped_section_is_reported_as_content_loss():
    old = _page("Alpha\nThe alpha section explains the fee structure in detail here.\n"
                "Beta\nThe beta section explains the deadline policy in detail here.",
                ["Alpha", "Beta"])
    new = _page("Alpha\nThe alpha section explains the fee structure in detail here.",
                ["Alpha"])
    diff = diff_semantic(old, new, StubEmbedder({"alpha": 1, "beta": 2}))
    assert len(diff.dropped) == 1
    assert diff.dropped[0].old.section == "Beta"
    dropped = [f for f in diff.findings if f.kind == "content.dropped"]
    assert dropped and dropped[0].severity is Severity.HIGH


def test_coverage_is_weighted_by_length():
    """Losing a long section must count for more than losing a caption."""
    long_text = " ".join(["detailed policy wording"] * 30)
    old = _page(f"Alpha\n{long_text}\nBeta\nA short beta caption line goes here.",
                ["Alpha", "Beta"])
    keeps_long = _page(f"Alpha\n{long_text}", ["Alpha"])
    keeps_short = _page("Beta\nA short beta caption line goes here.", ["Beta"])
    emb = StubEmbedder({"detailed policy": 1, "beta": 2})
    assert (diff_semantic(old, keeps_long, emb).coverage
            > diff_semantic(old, keeps_short, emb).coverage)


def test_a_page_reworded_throughout_is_not_called_content_loss():
    """The false positive the plan warns about: legitimate tone and style
    rewrites must not read as dropped content."""
    old = _page("Alpha\nThe alpha section explains the fee structure in detail.",
                ["Alpha"])
    new = _page("Alpha\nAlpha covers how our fees are structured, explained fully.",
                ["Alpha"])
    diff = diff_semantic(old, new, StubEmbedder({"alpha": 1}))
    assert diff.coverage == pytest.approx(1.0)
    assert diff.dropped == []


def test_new_content_is_reported_at_info_only():
    old = _page("Alpha\nThe alpha section explains the fee structure in detail.",
                ["Alpha"])
    new = _page("Alpha\nThe alpha section explains the fee structure in detail.\n"
                "Beta\nA brand new beta section that did not exist before now.",
                ["Alpha", "Beta"])
    diff = diff_semantic(old, new, StubEmbedder({"alpha": 1, "beta": 2}))
    assert diff.coverage == pytest.approx(1.0)
    assert [f.severity for f in diff.findings] == [Severity.INFO]


def test_empty_old_page_is_noted_not_crashed():
    diff = diff_semantic(_page(""), _page("Some new text entirely."), LexicalEmbedder())
    assert diff.matches == []
    assert any("no comparable text" in n for n in diff.notes)
    assert "no comparable text" in diff.interpretation()


def test_interpretation_leads_with_coverage_when_content_is_missing():
    old = _page("Alpha\nThe alpha section explains fees in considerable detail here.\n"
                "Beta\nThe beta section explains deadlines in considerable detail.",
                ["Alpha", "Beta"])
    new = _page("Alpha\nThe alpha section explains fees in considerable detail here.",
                ["Alpha"])
    diff = diff_semantic(old, new, StubEmbedder({"alpha": 1, "beta": 2}))
    assert diff.coverage < COVERAGE_ALARM
    assert "likely content loss" in diff.interpretation()


def test_the_synthetic_worst_case_pair_is_flagged():
    """The build plan's acceptance case for this phase."""
    diff = diff_semantic(
        extract(UNIVERSITY_PAGE, "https://old.edu/admissions"),
        extract(UNIVERSITY_PAGE_DEGRADED, "https://new.edu/admissions"),
        LexicalEmbedder())
    assert diff.coverage < 1.0
    assert diff.dropped
    assert diff.worst is Severity.HIGH


# --- reporting ------------------------------------------------------------

def test_rich_markup_in_findings_is_escaped():
    """Regression: rich reads square brackets as style tags, so "[best match
    0.31]" and URLs like ".../programs#f:DegreeLevels=[Bachelors]" had their
    brackets and everything in them silently deleted from the report."""
    from src.compare import _safe
    assert _safe("[best match 0.31] text") == r"\[best match 0.31] text"
    assert "DegreeLevels=" in _safe("https://e.edu/p#f:DegreeLevels=[Bachelors]")


def test_shorten_keeps_the_score_that_leads_the_item():
    from src.compare import _shorten
    item = "[best match 0.31] " + "a long passage preview " * 20
    assert _shorten(item).startswith("[best match 0.31]")


def test_interpretation_reports_coverage_not_just_similarity():
    """The real UTA pair scores 0.83 similar with 33% coverage -- a report
    leading with similarity alone would call that minor rewording."""
    old = _page("Alpha\n" + " ".join(["alpha detail"] * 40) + "\n"
                "Beta\n" + " ".join(["beta detail"] * 40), ["Alpha", "Beta"])
    new = _page("Alpha\n" + " ".join(["alpha detail"] * 40), ["Alpha"])
    diff = diff_semantic(old, new, StubEmbedder({"alpha": 1, "beta": 2}))
    assert "%" in diff.interpretation()
    assert str(round(diff.coverage * 100)) in diff.interpretation()
