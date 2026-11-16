import pytest

from src.diff_structural import (
    HEADING_REWORD_RATIO, Severity, SiteContext, align_headings, diff_structural,
    heading_match_score, match_images, match_links,
)
from src.extract import extract
from src.models import Heading, Image, Link, PageContent
from tests.fixtures import UNIVERSITY_PAGE, UNIVERSITY_PAGE_DEGRADED

OLD_ROOT, NEW_ROOT = "https://old.uta.edu", "https://new.uta.edu"


def _page(**kw) -> PageContent:
    base = dict(url="https://old.uta.edu/a", fetched_url="https://old.uta.edu/a",
                source="live", status=200, text="word " * 200)
    return PageContent(**{**base, **kw})


# --- site-relative link identity ------------------------------------------

def test_host_move_keeps_internal_links_identical():
    """The bug this exists to prevent: comparing absolute URLs would report
    every internal link on every page as dropped."""
    ctx = SiteContext(OLD_ROOT, NEW_ROOT)
    assert ctx.key(f"{OLD_ROOT}/apply", side="old") == \
        ctx.key(f"{NEW_ROOT}/apply", side="new")


def test_cms_page_extensions_are_not_a_moved_page():
    ctx = SiteContext(OLD_ROOT, NEW_ROOT)
    assert ctx.key(f"{OLD_ROOT}/dept/Apply.aspx", side="old") == \
        ctx.key(f"{NEW_ROOT}/dept/apply/", side="new")


def test_subsite_move_under_one_host():
    ctx = SiteContext("https://uta.edu/oldsite", "https://uta.edu/newsite")
    assert ctx.key("https://uta.edu/oldsite/forms", side="old") == \
        ctx.key("https://uta.edu/newsite/forms", side="new")


def test_external_links_compare_in_full():
    ctx = SiteContext(OLD_ROOT, NEW_ROOT)
    key = ctx.key("https://irs.gov/forms", side="old")
    assert key == ctx.key("https://irs.gov/forms", side="new")
    assert key != ctx.key("https://irs.gov/other", side="new")


def test_different_internal_paths_stay_different():
    ctx = SiteContext(OLD_ROOT, NEW_ROOT)
    assert ctx.key(f"{OLD_ROOT}/apply", side="old") != \
        ctx.key(f"{NEW_ROOT}/admissions", side="new")


# --- heading matching -----------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("requirements", "admission requirements"),   # expansion
    ("deadlines", "deadline"),                    # single word, spelling
    ("apply now", "how to apply now"),            # expansion
])
def test_headings_that_are_one_heading_reworded(a, b):
    assert heading_match_score(a, b) >= HEADING_REWORD_RATIO


@pytest.mark.parametrize("a,b", [
    ("graduate studies", "undergraduate studies"),  # 0.86 on characters alone
    ("youth programs", "explore programs"),         # share only 'programs'
    ("contact us", "contact information"),
])
def test_distinct_sections_are_not_treated_as_rewording(a, b):
    """Character similarity merges these. Both pairs above are separate
    sections of the real uta.edu/academics page; merging them would hide a
    dropped section as a harmless rename."""
    assert heading_match_score(a, b) < HEADING_REWORD_RATIO


def test_alignment_reports_drop_reword_and_add_separately():
    old = [Heading(1, "Admissions"), Heading(2, "Requirements"),
           Heading(3, "Deadlines")]
    new = [Heading(1, "Admissions"), Heading(2, "Admission Requirements"),
           Heading(2, "Cost")]
    by_old = {a.old.text: a for a in align_headings(old, new) if a.old}
    assert not by_old["Admissions"].is_reworded
    assert by_old["Requirements"].is_reworded
    assert by_old["Deadlines"].is_dropped
    assert [a.new.text for a in align_headings(old, new) if a.is_added] == ["Cost"]


def test_level_change_is_detected_on_an_otherwise_identical_heading():
    a = align_headings([Heading(2, "Academics")], [Heading(1, "Academics")])[0]
    assert a.level_changed and not a.is_reworded


# --- image matching -------------------------------------------------------

def test_images_match_across_a_rehost_by_filename():
    """Sitecore's /-/media/x.jpg becomes WordPress's /wp-content/uploads/x.jpg;
    the URL is not an identity but the filename usually survives."""
    old = [Image("https://old.uta.edu/-/media/campus.jpg", "Campus")]
    new = [Image("https://new.uta.edu/wp-content/uploads/2026/campus.jpg", "Campus")]
    pairs, dropped, added = match_images(old, new)
    assert len(pairs) == 1 and not dropped and not added


def test_images_match_on_alt_text_when_the_filename_changed_too():
    old = [Image("https://old.uta.edu/a/9f3b2c.jpg", "The research team in the lab")]
    new = [Image("https://new.uta.edu/b/team-photo.jpg", "The research team in the lab")]
    pairs, dropped, _ = match_images(old, new)
    assert len(pairs) == 1 and not dropped


def test_unmatched_images_are_reported_as_dropped():
    old = [Image("https://old.uta.edu/a/gone.jpg", "Gone")]
    pairs, dropped, added = match_images(old, [])
    assert not pairs and len(dropped) == 1 and not added


# --- link matching --------------------------------------------------------

def test_links_match_site_relatively_across_a_host_move():
    ctx = SiteContext(OLD_ROOT, NEW_ROOT)
    pairs, dropped, added = match_links(
        [Link(f"{OLD_ROOT}/apply", "Apply")],
        [Link(f"{NEW_ROOT}/apply", "Apply Now")], ctx)
    assert len(pairs) == 1 and not dropped and not added


# --- the whole diff -------------------------------------------------------

@pytest.fixture(scope="module")
def sabotaged():
    """The build plan's synthetic worst-case pair, across a host move."""
    return diff_structural(
        extract(UNIVERSITY_PAGE, "https://old.uta.edu/admissions"),
        extract(UNIVERSITY_PAGE_DEGRADED, "https://new.uta.edu/admissions"),
    )


def test_identical_pages_produce_no_findings():
    """A page that did not change must not generate findings, even across a
    host move -- false positives are what make a QA tool get ignored."""
    old = extract(UNIVERSITY_PAGE, "https://old.uta.edu/admissions")
    new = extract(UNIVERSITY_PAGE, "https://new.uta.edu/admissions")
    diff = diff_structural(old, new)
    assert diff.findings == []
    assert diff.is_clean
    assert diff.worst is Severity.INFO


def test_dropped_section_is_high_severity(sabotaged):
    dropped = sabotaged.of_kind("heading.dropped")
    assert len(dropped) == 1
    assert dropped[0].severity is Severity.HIGH
    assert dropped[0].items == ["### Deadlines"]


def test_dropped_pdf_is_high_severity(sabotaged):
    """Documents are split out because nothing else in the pipeline would
    notice a PDF vanishing -- it is not part of the page's text."""
    docs = sabotaged.of_kind("link.document_dropped")
    assert len(docs) == 1 and docs[0].severity is Severity.HIGH
    assert "checklist.pdf" in docs[0].items[0]


def test_lost_alt_text_is_reported(sabotaged):
    alt = sabotaged.of_kind("image.alt_lost")
    assert len(alt) == 1 and alt[0].severity is Severity.MEDIUM


def test_surviving_external_link_is_not_reported_as_dropped(sabotaged):
    """The external testing link exists on both sides; a host-move diff that
    compared absolute URLs would still have called it dropped."""
    dropped = " ".join(f.items[0] for f in sabotaged.of_kind("link.dropped"))
    assert "external.example.org" not in dropped


def test_counts_are_recorded_for_the_dashboard(sabotaged):
    assert sabotaged.counts["headings"] == (3, 2)
    assert sabotaged.counts["document_links"] == (1, 0)
    assert sabotaged.counts["words"][0] > sabotaged.counts["words"][1]


def test_findings_rank_worst_first(sabotaged):
    severities = [f.severity for f in sabotaged.ranked()]
    assert severities == sorted(severities, reverse=True)
    assert severities[0] is Severity.HIGH


def test_additions_never_outrank_losses():
    """New content is not a migration defect; ranking it beside losses would
    bury them."""
    old = _page(headings=[Heading(1, "Intro")])
    new = _page(headings=[Heading(1, "Intro"), Heading(2, "Brand New Section")])
    diff = diff_structural(old, new)
    assert diff.is_clean
    assert all(f.severity is Severity.INFO for f in diff.findings)


def test_img_becoming_a_css_background_is_its_own_finding():
    """Straight from the real UTA pair: missing-alt counts can *improve* while
    accessibility worsens, because an element that became a CSS background can
    no longer carry alt text at all."""
    old = _page(images=[Image("https://old.uta.edu/i/hero.jpg", "Campus at dusk")])
    new = _page(images=[Image("https://new.uta.edu/i/hero.jpg", None, kind="background")])
    diff = diff_structural(old, new)
    finding = diff.of_kind("image.became_background")
    assert len(finding) == 1
    assert finding[0].severity is Severity.MEDIUM
    assert "Campus at dusk" in finding[0].items[0]
    assert diff.of_kind("image.alt_lost") == []      # not double-reported


def test_missing_h1_is_reported():
    diff = diff_structural(_page(headings=[Heading(1, "Title")]),
                           _page(headings=[Heading(2, "Title")]))
    assert diff.of_kind("heading.h1_missing")


def test_link_that_kept_its_text_but_changed_target():
    ctx_old = _page(links=[Link("https://old.uta.edu/apply", "Apply")])
    ctx_new = _page(links=[Link("https://new.uta.edu/enroll", "Apply")])
    diff = diff_structural(ctx_old, ctx_new, old_root=OLD_ROOT, new_root=NEW_ROOT)
    moved = diff.of_kind("link.target_changed")
    assert len(moved) == 1 and moved[0].severity is Severity.MEDIUM
