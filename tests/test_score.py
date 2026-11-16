import pytest

from src.diff_semantic import diff_semantic
from src.diff_structural import diff_structural
from src.models import Heading, Image, Link, PageContent
from src.pair import PagePair, PairSpec
from src.score import (
    RiskScore, RiskTier, caveats_for, change_points, loss_points, rank, score_pair,
)
from tests.test_diff_semantic import StubEmbedder


def _page(text: str = "", headings=None, links=None, images=None, **kw) -> PageContent:
    base = dict(
        url="https://old.uta.edu/a", fetched_url="https://old.uta.edu/a",
        source="live", status=200, text=text or " ".join(["body words"] * 100),
        headings=headings or [], links=links or [], images=images or [],
    )
    return PageContent(**{**base, **kw})


def _pair(old: PageContent, new: PageContent) -> PagePair:
    return PagePair(spec=PairSpec(old.url, new.url), old=old, new=new)


def _score(old: PageContent, new: PageContent, embedder=None) -> RiskScore:
    pair = _pair(old, new)
    structural = diff_structural(old, new)
    semantic = diff_semantic(old, new, embedder) if embedder else None
    return score_pair(pair, structural, semantic)


SECTIONS = StubEmbedder({"alpha": 1, "beta": 2, "gamma": 3})


def _sectioned(*names: str) -> PageContent:
    text = "\n".join(
        f"{n.title()}\n" + " ".join([f"{n} detail wording"] * 20) for n in names)
    return _page(text=text, headings=[Heading(2, n.title()) for n in names])


# --- the tiers ------------------------------------------------------------

def test_unchanged_page_is_clean_and_says_why():
    """The plan asks for this explicitly: a reviewer will not trust a green row
    unless the tool says what it checked to earn it."""
    page = _sectioned("alpha", "beta")
    risk = _score(page, page, SECTIONS)
    assert risk.tier is RiskTier.CLEAN
    assert risk.score == 0.0
    assert risk.reasons
    assert any("accounted for" in r for r in risk.reasons)
    assert risk.confidence == "high"


def test_dropped_section_is_missing_content():
    risk = _score(_sectioned("alpha", "beta"), _sectioned("alpha"), SECTIONS)
    assert risk.tier is RiskTier.MISSING
    assert risk.loss > risk.change


def test_rewritten_but_complete_page_is_rewording_not_missing():
    """The distinction the whole tier scheme exists for: a page rewritten end
    to end that still says everything it used to has lost nothing."""
    old = _sectioned("alpha", "beta")
    new = PageContent(
        url="https://new.uta.edu/a", fetched_url="https://new.uta.edu/a",
        source="live", status=200,
        headings=[Heading(2, "Alpha"), Heading(2, "Beta")],
        text="\n".join([
            "Alpha\n" + " ".join(["alpha rephrased entirely differently"] * 20),
            "Beta\n" + " ".join(["beta rephrased entirely differently"] * 20),
        ]),
    )
    risk = _score(old, new, SECTIONS)
    assert risk.tier is not RiskTier.MISSING
    assert risk.loss == 0.0


def test_any_loss_outranks_pure_rewording():
    """Loss and rewording are different kinds of evidence, not degrees of one.
    A page that lost a PDF must rank above one merely rewritten."""
    lost_pdf = _score(
        _page(links=[Link("https://old.uta.edu/forms/apply.pdf", "Apply",
                          is_document=True)]),
        _page(),
    )
    assert lost_pdf.tier >= RiskTier.MAJOR
    assert lost_pdf.loss > 0


def test_broken_pair_is_unknown_and_does_not_outrank_real_loss():
    pair = PagePair(spec=PairSpec("a", "b"), old=_page(), new=_page(status=404))
    risk = score_pair(pair, None, None)
    assert risk.tier is RiskTier.UNKNOWN
    assert risk.confidence == "none"
    assert risk.tier < RiskTier.CLEAN          # sorts below every real verdict
    assert "404" in " ".join(risk.reasons)


# --- weighting ------------------------------------------------------------

def test_a_link_heavy_page_cannot_outweigh_a_lost_section():
    """Without caps, a page that shed twenty nav links would outrank one that
    lost a whole section of prose."""
    many_links = _page(links=[Link(f"https://old.uta.edu/p{i}", f"Link {i}")
                              for i in range(30)])
    link_loss, _ = loss_points(diff_structural(many_links, _page()), None)
    section_loss, _ = loss_points(None, diff_semantic(
        _sectioned("alpha", "beta"), _sectioned("alpha"), SECTIONS))
    assert section_loss > link_loss


def test_dropped_document_weighs_more_than_a_dropped_image():
    doc = _page(links=[Link("https://old.uta.edu/f.pdf", "F", is_document=True)])
    img = _page(images=[Image("https://old.uta.edu/i.jpg", "I")])
    doc_points, _ = loss_points(diff_structural(doc, _page()), None)
    img_points, _ = loss_points(diff_structural(img, _page()), None)
    assert doc_points > img_points


def test_loss_and_change_are_reported_on_the_same_scale_as_the_score():
    risk = _score(_sectioned("alpha", "beta", "gamma"), _sectioned("alpha"), SECTIONS)
    assert 0 <= risk.loss <= 100
    assert 0 <= risk.change <= 100
    assert 0 <= risk.score <= 100


def test_every_contribution_has_a_stated_reason():
    risk = _score(_sectioned("alpha", "beta"), _sectioned("alpha"), SECTIONS)
    assert risk.reasons
    assert all(isinstance(r, str) and r for r in risk.reasons)


# --- ranking --------------------------------------------------------------

def test_rank_puts_the_worst_pages_first():
    page = _sectioned("alpha", "beta")
    clean = _score(page, page, SECTIONS)
    missing = _score(page, _sectioned("alpha"), SECTIONS)
    unknown = score_pair(
        PagePair(spec=PairSpec("a", "b"), old=_page(), new=_page(status=500)),
        None, None)
    ordered = rank([("clean", clean), ("unknown", unknown), ("missing", missing)])
    assert [name for name, _ in ordered] == ["missing", "clean", "unknown"]


def test_rank_breaks_ties_within_a_tier_by_score():
    page = _sectioned("alpha", "beta", "gamma")
    worse = _score(page, _sectioned("alpha"), SECTIONS)
    milder = _score(page, _sectioned("alpha", "beta"), SECTIONS)
    ordered = rank([("milder", milder), ("worse", worse)])
    assert [name for name, _ in ordered][0] == "worse"


# --- caveats and confidence ----------------------------------------------

def test_stale_wayback_snapshot_is_a_caveat():
    """Differences against a seven-year-old capture include the old site's own
    drift, which is not the migration's doing."""
    old = _page(source="wayback", snapshot_timestamp="20150601120000")
    caveats = caveats_for(_pair(old, _page()), diff_structural(old, _page()), None)
    assert any("drift" in c for c in caveats)


def test_recent_snapshot_is_not_caveated_for_age():
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    old = _page(source="wayback", snapshot_timestamp=recent)
    caveats = caveats_for(_pair(old, _page()), diff_structural(old, _page()), None)
    assert not any("drift" in c for c in caveats)


def test_skipping_the_semantic_stage_is_a_caveat():
    caveats = caveats_for(_pair(_page(), _page()), diff_structural(_page(), _page()),
                          None)
    assert any("semantic comparison was skipped" in c for c in caveats)


def test_rewritten_passages_are_caveated_as_beyond_what_embeddings_can_tell():
    """The phase 3 calibration result, surfaced where a reviewer sees it: a
    rewrite that quietly dropped a fact scores like a faithful one."""
    old = _page(text="Alpha\n" + " ".join(["alpha detail"] * 30),
                headings=[Heading(2, "Alpha")])
    new = _page(text="Alpha\n" + " ".join(["alpha reworded"] * 30),
                headings=[Heading(2, "Alpha")])

    class Partial:
        def encode(self, texts):
            import numpy as np
            out = np.zeros((len(texts), 4), dtype=np.float32)
            for i, t in enumerate(texts):
                out[i] = [0.8, 0.6, 0, 0] if "reworded" in t else [1, 0, 0, 0]
            return out / np.linalg.norm(out, axis=1, keepdims=True)

    semantic = diff_semantic(old, new, Partial())
    assert semantic.reworded
    caveats = caveats_for(_pair(old, new), diff_structural(old, new), semantic)
    assert any("LLM judge" in c for c in caveats)


def test_body_fallback_extraction_is_a_caveat():
    old = _page(extractor="trafilatura + body-fallback")
    caveats = caveats_for(_pair(old, _page()), diff_structural(old, _page()), None)
    assert any("no content landmark" in c for c in caveats)


def test_confidence_falls_as_caveats_accumulate():
    assert RiskScore(RiskTier.CLEAN).confidence == "high"
    assert RiskScore(RiskTier.CLEAN, caveats=["one"]).confidence == "medium"
    assert RiskScore(RiskTier.CLEAN, caveats=["one", "two"]).confidence == "low"
    assert RiskScore(RiskTier.UNKNOWN).confidence == "none"


def test_tier_labels_match_the_build_plan():
    assert [t.label for t in
            (RiskTier.CLEAN, RiskTier.MINOR, RiskTier.MAJOR, RiskTier.MISSING)] == \
        ["Clean", "Minor rewording", "Major rewording", "Missing content"]


# --- structural proxies vs. the text signal -------------------------------

def test_restructured_page_with_all_text_intact_is_not_missing_content():
    """The real uta.edu/about pair: coverage 1.00, text grown from 113 to 285
    words, and it still scored Missing content purely on dropped headings.
    Structural drops are proxies for text loss, so adding them to a coverage
    figure that already says nothing is missing double-counts a redesign."""
    old = _sectioned("alpha", "beta")
    body = {n: " ".join([f"{n} detail wording"] * 20) for n in ("alpha", "beta")}
    restructured = PageContent(
        url="https://new.uta.edu/a", fetched_url="https://new.uta.edu/a",
        source="live", status=200,
        # Every old heading is gone; every old word is still there.
        headings=[Heading(2, "Overview"), Heading(2, "Details")],
        text="\n".join(["Overview", body["alpha"], "Details", body["beta"]]),
    )
    risk = _score(old, restructured, SECTIONS)
    assert risk.tier is not RiskTier.MISSING
    assert any("restructuring" in r for r in risk.reasons)


def test_proxy_weight_ramps_rather_than_switching():
    """A cliff at one coverage value lets a page slipping from 0.90 to 0.89
    jump two tiers on a rounding error."""
    from src.score import _proxy_weight

    class Fake:
        def __init__(self, coverage): self.coverage, self.matches = coverage, [1]

    weights = [_proxy_weight(Fake(c)) for c in (1.0, 0.95, 0.9, 0.85, 0.8, 0.75)]
    assert weights == sorted(weights)                  # monotonic
    assert weights[0] < weights[-1]
    assert weights[-1] == pytest.approx(1.0)
    assert all(abs(b - a) < 0.25 for a, b in zip(weights, weights[1:]))


def test_without_the_semantic_stage_structural_signals_keep_full_weight():
    """They are all the evidence there is, so nothing discounts them."""
    from src.score import _proxy_weight
    assert _proxy_weight(None) == 1.0


def test_a_dropped_document_is_never_discounted():
    """No coverage figure can vouch for a PDF: it is not part of the page's
    text, so its loss is independent evidence."""
    old = _page(text=" ".join(["body words"] * 100),
                links=[Link("https://old.uta.edu/f.pdf", "Form", is_document=True)])
    new = _page(text=" ".join(["body words"] * 100))
    risk = _score(old, new, StubEmbedder({"body words": 1}))
    assert risk.loss > 0
    assert risk.tier >= RiskTier.MAJOR


# --- thin pages -----------------------------------------------------------

def test_a_gutted_new_page_is_scored_not_suppressed():
    """A thin new page beside a substantial old one is the finding this tool
    exists to make. Treating it as uncompareable hid the worst result."""
    old = _sectioned("alpha", "beta", "gamma")
    new = _page(text="Alpha brief.", headings=[Heading(2, "Alpha")])
    pair = _pair(old, new)
    assert pair.problems == []
    assert pair.warnings
    risk = _score(old, new, SECTIONS)
    assert risk.tier is RiskTier.MISSING


def test_a_thin_old_page_still_blocks_the_comparison():
    """Nothing to compare against is a different thing from nothing left."""
    pair = _pair(_page(text="Tiny."), _sectioned("alpha"))
    assert any("nothing to compare against" in p for p in pair.problems)
    assert score_pair(pair, None, None).tier is RiskTier.UNKNOWN


def test_gutted_page_warning_becomes_a_caveat():
    old = _sectioned("alpha", "beta", "gamma")
    new = _page(text="Alpha brief.", headings=[Heading(2, "Alpha")])
    risk = _score(old, new, SECTIONS)
    assert any("rendering failure" in c for c in risk.caveats)
