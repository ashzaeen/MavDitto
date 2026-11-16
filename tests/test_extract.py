import pytest

from src.extract import extract
from src.fetch import looks_like_js_shell, visible_text_estimate
from src.models import PageContent
from tests.fixtures import (
    JS_SHELL_PAGE, NO_LANDMARK_PAGE, UNIVERSITY_PAGE, UNIVERSITY_PAGE_DEGRADED,
)

BASE = "https://example.edu/admissions/undergraduate"


@pytest.fixture(scope="module")
def page() -> PageContent:
    return extract(UNIVERSITY_PAGE, BASE)


@pytest.fixture(scope="module")
def degraded() -> PageContent:
    return extract(UNIVERSITY_PAGE_DEGRADED, BASE)


# --- the main region ------------------------------------------------------

def test_title_prefers_og_title(page):
    assert page.title == "Undergraduate Admissions"


def test_chrome_is_excluded_from_links(page):
    hrefs = {l.href for l in page.links}
    for chrome in ("/academics", "/privacy", "/related", "/admissions"):
        assert not any(h.endswith(chrome) for h in hrefs), f"{chrome} leaked from chrome"


def test_chrome_is_excluded_from_images(page):
    assert not any(i.src.endswith(("logo.png", "seal.png")) for i in page.images)


def test_body_text_keeps_the_facts_a_diff_must_notice(page):
    for fact in ("$75", "3.0 grade point average", "February 15"):
        assert fact in page.text


# --- structure ------------------------------------------------------------

def test_heading_outline_is_in_document_order(page):
    assert page.heading_outline() == [
        "# Undergraduate Admissions",
        "## Requirements",
        "### Deadlines",
    ]


def test_lazy_loaded_image_is_found_via_data_src(page):
    assert any(i.src.endswith("library.jpg") for i in page.images)


def test_missing_alt_attribute_is_distinct_from_present_alt(page):
    by_name = {i.src.rsplit("/", 1)[-1]: i for i in page.images}
    assert by_name["campus.jpg"].has_alt
    assert by_name["library.jpg"].alt is None
    assert [i.src.rsplit("/", 1)[-1] for i in page.images_missing_alt] == ["library.jpg"]


def test_non_navigational_hrefs_are_dropped(page):
    assert not any(
        l.href.startswith(("mailto:", "#")) or l.href.endswith("#top")
        for l in page.links
    )


def test_links_are_absolute_and_classified(page):
    by_name = {l.href.rsplit("/", 1)[-1]: l for l in page.links}
    assert by_name["checklist.pdf"].href == "https://example.edu/docs/checklist.pdf"
    assert by_name["checklist.pdf"].is_document
    assert not by_name["checklist.pdf"].is_external
    assert by_name["testing"].is_external
    assert not by_name["testing"].is_document


def test_document_links_accessor(page):
    assert [l.href for l in page.document_links] == \
        ["https://example.edu/docs/checklist.pdf"]


# --- the synthetic worst-case pair ---------------------------------------

def test_degraded_page_loses_exactly_what_was_removed(page, degraded):
    """The deliberate sabotage must be visible in the normalized output --
    this is what phases 2-4 will score, so phase 1 has to surface it."""
    assert "$75" not in degraded.text
    assert "3.0 grade point average" not in degraded.text

    assert "### Deadlines" in page.heading_outline()
    assert "### Deadlines" not in degraded.heading_outline()

    assert len(degraded.images) < len(page.images)
    assert len(degraded.images_missing_alt) == 1      # campus.jpg lost its alt
    assert degraded.document_links == []              # the PDF was dropped
    assert degraded.word_count < page.word_count


def test_degraded_page_still_reads_as_fluent_prose(page, degraded):
    """The point of the semantic stage: a length heuristic would not catch this.
    The rewrite is grammatical and keeps most of the page's bulk -- only the
    load-bearing facts are gone."""
    assert "official high school transcripts" in degraded.text
    assert degraded.word_count > page.word_count * 0.5


# --- fallbacks ------------------------------------------------------------

def test_page_without_landmark_still_extracts_and_says_so():
    p = extract(NO_LANDMARK_PAGE, "https://example.edu/parking")
    assert "rear\nwindshield" in p.text or "rear windshield" in p.text
    assert p.headings and p.headings[0].text == "Parking Policy Update"
    assert not any(l.href.endswith("example.edu/") for l in p.links)  # nav dropped


def test_empty_html_is_flagged_not_crashed():
    p = extract("", "https://example.edu/gone", status=404)
    assert p.word_count == 0
    assert any("empty HTML" in n for n in p.notes)


def test_thin_extraction_is_flagged_for_review():
    p = extract("<html><body><main><p>Hi.</p></main></body></html>",
                "https://example.edu/thin")
    assert any("verify by hand" in n for n in p.notes)


# --- JS shell detection ---------------------------------------------------

def test_js_shell_is_detected_and_real_page_is_not():
    assert looks_like_js_shell(JS_SHELL_PAGE)
    assert not looks_like_js_shell(UNIVERSITY_PAGE)


def test_visible_text_estimate_ignores_script_bodies():
    assert "window.boot" not in visible_text_estimate(JS_SHELL_PAGE)


# --- round-trip -----------------------------------------------------------

def test_page_content_survives_json_round_trip(page):
    restored = PageContent.from_json(page.to_json())
    assert restored.heading_outline() == page.heading_outline()
    assert [i.src for i in restored.images] == [i.src for i in page.images]
    assert [l.href for l in restored.links] == [l.href for l in page.links]
    assert restored.text == page.text


# --- CSS background images (real Sitecore pattern) ------------------------

def test_css_background_images_are_captured():
    from tests.fixtures import SITECORE_BACKGROUND_PAGE
    p = extract(SITECORE_BACKGROUND_PAGE, "https://example.edu/research")
    srcs = {i.src.rsplit("/", 1)[-1].split("?")[0] for i in p.images}
    assert {"hero.jpg", "lab.png", "team.jpg"} <= srcs
    assert len(p.background_images) == 2


def test_background_images_do_not_count_as_missing_alt():
    """Otherwise every Sitecore hero would be a false accessibility finding."""
    from tests.fixtures import SITECORE_BACKGROUND_PAGE
    p = extract(SITECORE_BACKGROUND_PAGE, "https://example.edu/research")
    assert p.images_missing_alt == []
    assert all(i.is_decorative for i in p.background_images)


def test_images_are_returned_in_document_order_not_grouped_by_kind():
    """The page reads hero (background) -> lab (background) -> team (<img>).
    A caller displaying these has to see that same order, not every <img>
    first and every background afterward -- which is what a two-pass
    extractor (all <img> tags, then a separate pass over backgrounds)
    produces regardless of where each one actually sits on the page."""
    from tests.fixtures import SITECORE_BACKGROUND_PAGE
    p = extract(SITECORE_BACKGROUND_PAGE, "https://example.edu/research")
    names = [i.src.rsplit("/", 1)[-1].split("?")[0] for i in p.images]
    assert names == ["hero.jpg", "lab.png", "team.jpg"]


# --- state-modifier classes (real Notion / Tailwind / BEM pattern) --------

def test_a_state_modifier_class_does_not_delete_the_page():
    """Regression: `has-footer` means the page *has* a footer, not that this
    element *is* one. Matching it deleted the <article> holding everything --
    on a real Notion site that cost every heading, image and link."""
    from tests.fixtures import STATE_CLASS_PAGE
    p = extract(STATE_CLASS_PAGE, "https://example.edu/")
    assert "budding programmer" in p.text
    assert any(h.text == "Hello, Welcome!" for h in p.headings)
    assert any(h.text == "Experiences" for h in p.headings)


def test_looks_like_chrome_ignores_state_prefixes():
    from src.extract import looks_like_chrome
    assert looks_like_chrome("site-footer")
    assert looks_like_chrome("main-nav")
    assert not looks_like_chrome("has-footer")
    assert not looks_like_chrome("no-sidebar")
    assert not looks_like_chrome("with-header")


def test_a_heading_carrying_a_chrome_class_is_not_stripped():
    """A page's own h1 is never site furniture, even when the title block is
    named like a header -- and the class may sit on the heading itself, not
    only on a wrapper around it."""
    from src.extract import find_main_region
    from bs4 import BeautifulSoup
    from tests.fixtures import STATE_CLASS_PAGE

    soup = BeautifulSoup(STATE_CLASS_PAGE, "lxml")
    find_main_region(soup, STATE_CLASS_PAGE)      # strips chrome in place
    assert "High School Site" in [h.get_text(strip=True) for h in soup.find_all("h1")]


def test_the_page_title_survives_even_when_its_block_is_outside_main():
    """It is recorded as the title rather than as a heading, which is the right
    place for it -- both sides of a pair exclude it consistently."""
    from tests.fixtures import STATE_CLASS_PAGE
    assert extract(STATE_CLASS_PAGE, "https://example.edu/").title == "High School Site"


def test_real_chrome_is_still_removed_alongside_those_guards():
    from tests.fixtures import STATE_CLASS_PAGE
    p = extract(STATE_CLASS_PAGE, "https://example.edu/")
    hrefs = " ".join(l.href for l in p.links)
    assert "/elsewhere" not in hrefs      # nav
    assert "/privacy" not in hrefs        # footer
    assert "/projects" in hrefs           # content


def test_a_chrome_named_element_holding_most_of_the_page_is_kept():
    """Site furniture is a small fraction of a page by definition, so an
    element named like chrome that holds the bulk of the text is mislabeled."""
    body = " ".join(["substantive policy wording for the reader"] * 40)
    html = f'<html><body><div class="footer-wrap"><p>{body}</p></div></body></html>'
    assert "substantive policy wording" in extract(html, "https://example.edu/").text


# --- links for crawling, as opposed to links as content -------------------

NAV_PAGE = """
<!doctype html>
<html><head><title>Tickets</title></head><body>
  <nav class="site-nav">
    <a href="/tickets/venues">Venues</a>
    <a href="/tickets/contact">Contact</a>
    <a href="/tickets/terms">Terms</a>
  </nav>
  <main>
    <h1>Tickets</h1>
    <p>Buy tickets for upcoming events at the arena and the concert hall,
       with student pricing available on most performances this season.</p>
    <a href="/tickets/events/stomp-wars">Stomp Wars</a>
  </main>
  <footer class="site-footer"><a href="/tickets/privacy">Privacy</a></footer>
</body></html>
"""


def test_content_links_exclude_navigation():
    """Counting a site's nav as content would report the whole menu as changed
    on every page."""
    from src.extract import extract
    hrefs = {l.href for l in extract(NAV_PAGE, "https://e.edu/tickets").links}
    assert any(h.endswith("/events/stomp-wars") for h in hrefs)
    assert not any(h.endswith("/venues") for h in hrefs)


def test_harvest_links_includes_navigation():
    """Crawling with the content extractor found three links on a real subsite
    whose menu listed eight; the five it skipped were later reported as pages
    that never migrated."""
    from src.extract import harvest_links
    hrefs = {l.href for l in harvest_links(NAV_PAGE, "https://e.edu/tickets")}
    for expected in ("/venues", "/contact", "/terms", "/privacy",
                     "/events/stomp-wars"):
        assert any(h.endswith(expected) for h in hrefs), expected


def test_harvest_links_still_skips_scripts_and_junk_targets():
    html = ('<html><body><script>var a = "<a href=/fake>x</a>";</script>'
            '<a href="mailto:x@e.edu">Mail</a><a href="#top">Top</a>'
            '<a href="/real">Real</a></body></html>')
    from src.extract import harvest_links
    hrefs = [l.href for l in harvest_links(html, "https://e.edu/")]
    assert hrefs == ["https://e.edu/real"]


def test_harvest_links_on_an_empty_document():
    from src.extract import harvest_links
    assert harvest_links("", "https://e.edu/") == []


# --- structural blocks: headings, paragraphs, lists, tables ----------------

BLOCK_PAGE = """
<html><head><title>T</title></head><body><main>
  <h1>Admissions</h1>
  <p>Freshman applicants must submit official transcripts.</p>
  <h2>Requirements</h2>
  <p>A minimum GPA is required for review.</p>
  <ul><li>Transcript</li><li>Essay</li><li>Two letters</li></ul>
  <h2>Deadlines</h2>
  <table>
    <tr><th>Term</th><th>Date</th></tr>
    <tr><td>Fall</td><td>March 1</td></tr>
    <tr><td>Spring</td><td>October 1</td></tr>
  </table>
  <blockquote>Apply early for best results.</blockquote>
</main></body></html>
"""


def test_blocks_capture_every_kind_in_document_order():
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    assert [b.kind for b in page.blocks] == [
        "heading", "paragraph", "heading", "paragraph", "list", "heading",
        "table", "quote",
    ]


def test_a_heading_blocks_path_is_its_ancestors_not_itself():
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    requirements = next(b for b in page.blocks if b.text == "Requirements")
    assert requirements.heading_path == ["Admissions"]


def test_a_content_blocks_path_includes_the_nearest_heading():
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    list_block = next(b for b in page.blocks if b.kind == "list")
    assert list_block.heading_path == ["Admissions", "Requirements"]


def test_a_sibling_heading_closes_the_previous_ones_path():
    """'Deadlines' is a sibling of 'Requirements', not a child of it -- so
    content under it must carry 'Deadlines' in its path, not 'Requirements'."""
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    table = next(b for b in page.blocks if b.kind == "table")
    assert table.heading_path == ["Admissions", "Deadlines"]


def test_list_items_are_captured_in_order():
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    list_block = next(b for b in page.blocks if b.kind == "list")
    assert list_block.items == ["Transcript", "Essay", "Two letters"]
    assert list_block.ordered is False


def test_table_header_and_rows_are_captured_separately():
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    table = next(b for b in page.blocks if b.kind == "table")
    assert table.columns == ["Term", "Date"]
    assert table.items == ["Fall | March 1", "Spring | October 1"]


def test_heading_blocks_match_the_page_headings_one_to_one():
    """The dashboard pairs a heading block with its verdict by position
    against `page.headings` -- the two have to agree in count and order."""
    page = extract(BLOCK_PAGE, "https://e.edu/admissions")
    heading_blocks = [b.text for b in page.blocks if b.kind == "heading"]
    assert heading_blocks == [h.text for h in page.headings]


def test_blocks_nested_inside_a_generic_wrapper_are_still_found():
    """Templates nest the actual content arbitrarily deep inside layout divs;
    a block-level tag should be found regardless of how it is wrapped."""
    html = ("<html><body><main><div class='row'><div class='col'>"
            "<h2>Fees</h2><p>The application fee is $75.</p>"
            "</div></div></main></body></html>")
    page = extract(html, "https://e.edu/fees")
    assert [b.kind for b in page.blocks] == ["heading", "paragraph"]


def test_an_ordered_list_is_marked_ordered():
    html = "<html><body><main><ol><li>First</li><li>Second</li></ol></main></body></html>"
    page = extract(html, "https://e.edu/steps")
    assert page.blocks[0].ordered is True


def test_a_page_with_no_structural_tags_yields_no_blocks():
    """Some old sites are just <br>-separated text in one div -- no <p>, no
    headings. chunk_page's word-budget fallback exists for exactly this."""
    html = "<html><body><main>Just some text.<br>More text.</main></body></html>"
    page = extract(html, "https://e.edu/plain")
    assert page.blocks == []


# --- headings faked with bold text, not a real <hN> tag --------------------
#
# A real site (a Sitecore/AEM rich-text block of FAQ questions) rendered every
# question as `<p><strong>...</strong></p>` -- no heading tag anywhere. Every
# one of those questions was silently read as ordinary paragraph text, which
# is indistinguishable from the page's actual body copy on the review screen.
# This is not a one-site quirk: bolding a whole line to "make it a heading"
# without ever picking a heading style is one of the most common things a
# rich-text editor produces.

def test_a_paragraph_that_is_entirely_bold_is_read_as_a_heading():
    html = ("<html><body><main><h1>AXS Mobile ID</h1>"
            "<p><strong>HOW DO I GET INTO THE ARENA?</strong></p>"
            "<p>Show your AXS Mobile ID barcode to the ticket taker.</p>"
            "</main></body></html>")
    page = extract(html, "https://e.edu/axs")
    assert [b.kind for b in page.blocks] == ["heading", "heading", "paragraph"]
    faked = page.blocks[1]
    assert faked.text == "HOW DO I GET INTO THE ARENA?"


def test_bold_text_that_is_only_part_of_a_paragraph_is_not_a_heading():
    """A bold label followed by real content ('**Address:** 600 Main St') is
    an address line, not an author trying to write a heading."""
    html = ("<html><body><main>"
            "<p><strong>Address:</strong> 600 S. Center Street</p>"
            "</main></body></html>")
    page = extract(html, "https://e.edu/contact")
    assert [b.kind for b in page.blocks] == ["paragraph"]
    assert page.blocks[0].text == "Address: 600 S. Center Street"


def test_a_long_fully_bolded_paragraph_is_not_treated_as_a_heading():
    """A whole paragraph bolded for emphasis, not as a faked heading -- a
    heading is short by nature, and a 20+ word 'heading' is actually a
    warning notice someone bolded for attention."""
    long_bold = " ".join(["word"] * 30)
    html = f"<html><body><main><p><strong>{long_bold}</strong></p></main></body></html>"
    page = extract(html, "https://e.edu/notice")
    assert [b.kind for b in page.blocks] == ["paragraph"]


def test_consecutive_faked_headings_are_read_as_siblings_not_nested():
    """Ten FAQ questions in a row must not climb from h2 to h11 -- each one
    nests under the nearest *real* heading, not under the previous fake one."""
    questions = "".join(f"<p><strong>Question {i}?</strong></p><p>Answer {i}.</p>"
                        for i in range(5))
    html = f"<html><body><main><h2>FAQ</h2>{questions}</main></body></html>"
    page = extract(html, "https://e.edu/faq")
    faked = [b for b in page.blocks if b.kind == "heading" and b.text != "FAQ"]
    assert len(faked) == 5
    assert len({b.level for b in faked}) == 1
    assert all(b.heading_path == ["FAQ"] for b in faked)


def test_faked_headings_still_agree_with_page_headings():
    """page.headings and the heading-kind blocks are relied on to stay in
    lockstep (the dashboard pairs one with the other by position) -- a faked
    heading has to update both or it silently breaks that pairing."""
    html = ("<html><body><main><h1>Title</h1>"
            "<p><strong>A fake heading</strong></p>"
            "<h2>A real one</h2></main></body></html>")
    page = extract(html, "https://e.edu/mixed")
    heading_blocks = [b.text for b in page.blocks if b.kind == "heading"]
    assert heading_blocks == [h.text for h in page.headings]
    assert heading_blocks == ["Title", "A fake heading", "A real one"]


def test_harvest_links_follows_pagination_and_alternates():
    """A <link> in the head names a page that never shows up as an <a> at all
    -- a paginated listing's later pages, or a translated version of this one."""
    html = ('<html><head>'
            '<link rel="next" href="/page/2">'
            '<link rel="alternate" hreflang="es" href="/es/">'
            '</head><body><a href="/">Home</a></body></html>')
    from src.extract import harvest_links
    hrefs = {l.href for l in harvest_links(html, "https://e.edu/page/1")}
    assert "https://e.edu/page/2" in hrefs
    assert "https://e.edu/es/" in hrefs


def test_harvest_links_reads_jsonld_before_the_script_tag_is_stripped():
    """JSON-LD lives inside <script>, which is stripped to keep script text out
    of the anchor scan -- so this has to run before that removal, not after."""
    html = ('<html><body>'
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"ItemList","itemListElement":['
            '{"url":"https://e.edu/one"},{"url":"https://e.edu/two"}]}</script>'
            '<a href="/three">Three</a></body></html>')
    from src.extract import harvest_links
    hrefs = {l.href for l in harvest_links(html, "https://e.edu/")}
    assert {"https://e.edu/one", "https://e.edu/two", "https://e.edu/three"} <= hrefs


def test_harvest_links_follows_area_iframe_and_meta_refresh():
    html = ('<html><head><meta http-equiv="refresh" content="0;url=/landing">'
            '</head><body><map name="m"><area href="/zoneA" shape="rect">'
            '</map><iframe src="/embed/schedule"></iframe></body></html>')
    from src.extract import harvest_links
    hrefs = {l.href for l in harvest_links(html, "https://e.edu/")}
    assert {"https://e.edu/landing", "https://e.edu/zoneA",
            "https://e.edu/embed/schedule"} <= hrefs


# --- every image on the page, for an alt-text audit -------------------------
#
# extract_all_images() is deliberately different from extract().images: no
# region scoping, and no stripping <noscript>. Both exclusions are correct
# for the structural diff and wrong for an accessibility audit -- see the
# function's docstring for the real page that proved it (22 of 31 <img> tags
# missed by scoping alone, and a hero image whose only static-HTML trace was
# a <noscript> fallback).

CHROME_PAGE = """
<html><body>
<header><img src="/logo.png" alt="Site logo"></header>
<nav><img src="/nav-icon.png" alt=""></nav>
<main><img src="/hero.jpg" alt="A students walks across campus"></main>
<footer><img src="/social.png" alt="Follow us"></footer>
</body></html>
"""


def test_images_outside_main_are_found():
    from src.extract import extract, extract_all_images

    all_images = {i.src for i in extract_all_images(CHROME_PAGE, "https://e.edu/")}
    content_only = {i.src for i in extract(CHROME_PAGE, "https://e.edu/").images}

    assert "https://e.edu/logo.png" in all_images
    assert "https://e.edu/nav-icon.png" in all_images
    assert "https://e.edu/social.png" in all_images
    # The content-scoped extractor is the one that is supposed to exclude
    # these -- confirms the two functions are actually answering different
    # questions, not just duplicating each other.
    assert "https://e.edu/logo.png" not in content_only


NOSCRIPT_HERO_PAGE = """
<html><body><main>
<div class="lazy-bg hero"></div>
<noscript><div class="lazy-bg hero"
    style="background-image: url('/hero-fallback.jpg')"></div></noscript>
</main></body></html>
"""


def test_a_noscript_only_background_image_is_found():
    from src.extract import extract_all_images

    images = extract_all_images(NOSCRIPT_HERO_PAGE, "https://e.edu/")
    assert any(i.src == "https://e.edu/hero-fallback.jpg" for i in images)


def test_extract_still_strips_noscript_for_the_content_pass():
    """The content-scoped extractor's exclusion is intentional and must not
    regress just because the audit-scoped one now reads noscript."""
    from src.extract import extract

    page = extract(NOSCRIPT_HERO_PAGE, "https://e.edu/")
    assert not any("hero-fallback" in i.src for i in page.images)


def test_a_noscript_img_tag_is_found_with_its_existing_alt_text():
    html = ('<html><body><main>'
            '<noscript><img src="/poster.jpg" alt="Concert poster for Friday"></noscript>'
            '</main></body></html>')
    from src.extract import extract_all_images

    images = extract_all_images(html, "https://e.edu/")
    poster = next(i for i in images if i.src == "https://e.edu/poster.jpg")
    assert poster.alt == "Concert poster for Friday"


def test_extract_all_images_still_dedupes_by_resolved_url():
    """The same logo repeated in a responsive nav's desktop and mobile markup
    should not be paid for twice."""
    html = ('<html><body>'
            '<img src="/logo.png" alt="logo"><img src="/logo.png" alt="logo">'
            '</body></html>')
    from src.extract import extract_all_images

    images = extract_all_images(html, "https://e.edu/")
    assert len(images) == 1


def test_extract_all_images_on_an_empty_document():
    from src.extract import extract_all_images
    assert extract_all_images("", "https://e.edu/") == []


# --- images set purely through a class in a <style> block -----------------
#
# A real UTA homepage carries five "Maverick Highlights" cards -- no <img>,
# no inline style, no data-* attribute, each just an <a class="feature-box
# athletics"> whose image comes entirely from ".feature-grid-block .athletics
# { background: #333 url(...) }" in a <style> block extract.py's own
# noise-stripping deletes before anything looks inside it.

CARD_GRID_PAGE = """
<html><head><style>
.feature-grid-block .athletics {
  grid-area: athletics;
  background: #333 url('https://e.edu/media/wbb.jpg');
  background-repeat: no-repeat;
}
.feature-grid-block .campus {
  grid-area: campus;
  background: #f4f4f4 url('/media/business-gift.jpg');
}
</style></head>
<body><main>
<div class="feature-grid-block">
<a href="/a" class="feature-box athletics"><h3>UTA Joins United Athletic Conference</h3></a>
<a href="/b" class="feature-box campus"><h3>Gift Advances Career Readiness</h3></a>
</div>
</main></body></html>
"""


def test_a_class_driven_background_image_is_found():
    from src.extract import extract_all_images

    images = extract_all_images(CARD_GRID_PAGE, "https://e.edu/")
    srcs = {i.src for i in images}
    assert "https://e.edu/media/wbb.jpg" in srcs
    assert "https://e.edu/media/business-gift.jpg" in srcs


def test_a_class_driven_background_image_is_kind_background():
    from src.extract import extract_all_images

    images = extract_all_images(CARD_GRID_PAGE, "https://e.edu/")
    card = next(i for i in images if "wbb" in i.src)
    assert card.kind == "background"


def test_extract_still_strips_style_for_the_content_pass():
    """This is new territory for extract_all_images only -- the content-scoped
    extractor's own exclusion of <style> must not regress."""
    from src.extract import extract

    page = extract(CARD_GRID_PAGE, "https://e.edu/")
    assert not any("wbb" in i.src for i in page.images)


def test_a_class_driven_background_slots_into_its_true_page_position():
    """A real <img> sitting between two class-driven cards has to land
    between them in the results too -- not after both, which is what
    appending class-driven matches in a pass of their own would produce."""
    html = """
    <html><head><style>
    .card.athletics { background: url('/a.jpg'); }
    .card.campus { background: url('/c.jpg'); }
    </style></head>
    <body><main>
    <a class="card athletics"></a>
    <img src="/middle.jpg" alt="a real photo, in between the two cards">
    <a class="card campus"></a>
    </main></body></html>
    """
    from src.extract import extract_all_images

    names = [i.src.rsplit("/", 1)[-1] for i in extract_all_images(html, "https://e.edu/")]
    assert names == ["a.jpg", "middle.jpg", "c.jpg"]


def test_a_class_only_used_for_layout_is_not_mistaken_for_an_image():
    html = ('<html><head><style>.box-1 { grid-area: box-1; }</style></head>'
            '<body><div class="box-1">text</div></body></html>')
    from src.extract import extract_all_images

    assert extract_all_images(html, "https://e.edu/") == []


def test_a_shorthand_background_property_is_read_not_just_background_image():
    """The real rule uses "background: #333 url(...)", not "background-image:
    url(...)" -- both have to resolve to the same image."""
    html = ('<html><head><style>.hero { background: #000 url(\'/h.jpg\') '
            'no-repeat center; }</style></head>'
            '<body><div class="hero"></div></body></html>')
    from src.extract import extract_all_images

    images = extract_all_images(html, "https://e.edu/")
    assert images and images[0].src == "https://e.edu/h.jpg"


def test_a_data_uri_background_is_not_treated_as_a_fetchable_image():
    html = ('<html><head><style>.icon { background-image: '
            'url(data:image/png;base64,AAAA); }</style></head>'
            '<body><div class="icon"></div></body></html>')
    from src.extract import extract_all_images

    assert extract_all_images(html, "https://e.edu/") == []


def test_a_class_defined_in_style_but_never_used_yields_nothing():
    html = ('<html><head><style>.unused { background: url(\'/x.jpg\'); }'
            '</style></head><body><p>no elements use that class</p></body></html>')
    from src.extract import extract_all_images

    assert extract_all_images(html, "https://e.edu/") == []


# --- ID selectors, layered backgrounds, <input type="image">, external CSS -

def test_an_id_driven_background_image_is_found():
    """The real "Maverick Highlights" cards used classes; a rule this
    specific -- one exact image for one exact element -- is at least as
    likely to be written against an ID instead."""
    html = ('<html><head><style>'
            '#highlight_block_1 { background: url(\'/wbb.jpg\'); }'
            '</style></head><body><main>'
            '<a id="highlight_block_1"></a>'
            '</main></body></html>')
    from src.extract import extract_all_images

    images = extract_all_images(html, "https://e.edu/")
    assert any(i.src == "https://e.edu/wbb.jpg" for i in images)


def test_a_layered_background_yields_every_url_not_just_the_last():
    """"background-image: url(a), url(b)" is valid CSS naming two images. A
    single-match regex only ever captured the last url() in a declaration --
    the greedy middle of "background(-image)?:[^;]*url(" consumes past every
    earlier one before backtracking to find one to match against."""
    html = ('<html><head><style>'
            '.hero { background-image: url(\'/a.jpg\'), url(\'/b.jpg\'); }'
            '</style></head><body><div class="hero"></div></body></html>')
    from src.extract import extract_all_images

    srcs = {i.src for i in extract_all_images(html, "https://e.edu/")}
    assert "https://e.edu/a.jpg" in srcs
    assert "https://e.edu/b.jpg" in srcs


def test_a_layered_inline_style_also_yields_every_url():
    """The same bug, for an inline style="" attribute rather than a <style>
    block rule -- extract_images' own inline-style loop used the same
    single-match pattern."""
    html = ('<html><body><main>'
            '<div style="background-image: url(\'/a.jpg\'), url(\'/b.jpg\')">'
            '</div></main></body></html>')
    from src.extract import extract_all_images

    srcs = {i.src for i in extract_all_images(html, "https://e.edu/")}
    assert "https://e.edu/a.jpg" in srcs
    assert "https://e.edu/b.jpg" in srcs


def test_input_type_image_is_found_with_its_alt_text():
    html = ('<html><body><main>'
            '<input type="image" src="/search.png" alt="Search">'
            '</main></body></html>')
    from src.extract import extract_all_images

    images = extract_all_images(html, "https://e.edu/")
    button = next(i for i in images if i.src == "https://e.edu/search.png")
    assert button.alt == "Search"
    assert button.kind == "img"


def test_an_ordinary_text_input_is_not_mistaken_for_an_image():
    html = '<html><body><input type="text" value="not an image"></body></html>'
    from src.extract import extract_all_images

    assert extract_all_images(html, "https://e.edu/") == []


def test_stylesheet_urls_finds_every_linked_stylesheet():
    html = ('<html><head>'
            '<link rel="stylesheet" href="/a.css">'
            '<link rel="preconnect" href="https://fonts.example.com">'
            '<link rel="stylesheet" href="https://cdn.e.edu/b.css">'
            '</head><body></body></html>')
    from src.extract import stylesheet_urls

    urls = stylesheet_urls(html, "https://e.edu/")
    assert urls == ["https://e.edu/a.css", "https://cdn.e.edu/b.css"]


def test_stylesheet_urls_on_an_empty_document():
    from src.extract import stylesheet_urls
    assert stylesheet_urls("", "https://e.edu/") == []


def test_extract_all_images_reads_class_rules_from_extra_css_too():
    """extra_css stands in for a caller having already fetched an external
    stylesheet -- the page itself carries no <style> block at all here."""
    html = ('<html><body><main><a class="feature-box athletics"></a>'
            '</main></body></html>')
    external_css = '.feature-grid-block .athletics { background: url(\'/wbb.jpg\'); }'
    from src.extract import extract_all_images

    without = extract_all_images(html, "https://e.edu/")
    with_css = extract_all_images(html, "https://e.edu/", extra_css=external_css)
    assert without == []
    assert any(i.src == "https://e.edu/wbb.jpg" for i in with_css)


def test_parse_css_background_rules_separates_class_and_id():
    from src.extract import parse_css_background_rules

    css = ('.card { background: url(\'/card.jpg\'); }'
          '#hero { background: url(\'/hero.jpg\'); }')
    class_bg, id_bg = parse_css_background_rules(css)
    assert class_bg == {"card": ["/card.jpg"]}
    assert id_bg == {"hero": ["/hero.jpg"]}


# --- header/footer/prefooter region tagging --------------------------------

def test_an_image_inside_the_site_header_is_tagged_header():
    html = ('<html><body>'
            '<header class="global-header"><img src="/logo.png" alt="Logo"></header>'
            '<main><p>content</p></main>'
            '</body></html>')
    from src.extract import extract_all_images

    logo = next(i for i in extract_all_images(html, "https://e.edu/") if "logo" in i.src)
    assert logo.region == "header"


def test_a_header_tag_used_for_a_content_sections_own_heading_is_not_chrome():
    """The real UTA homepage wraps its "Maverick Highlights" <h2> in a bare
    <header> tag, inside <main> -- a content-sectioning idiom, not site
    chrome. Tagging it "header" would silently hide those cards whenever the
    "include header images" option is left off."""
    html = ('<html><body><main>'
            '<header><h2>Highlights</h2></header>'
            '<a class="feature-box athletics" id="highlight_block_1">'
            '<img src="/wbb.jpg" alt="Team"></a>'
            '</main></body></html>')
    from src.extract import extract_all_images

    photo = next(i for i in extract_all_images(html, "https://e.edu/") if "wbb" in i.src)
    assert photo.region == ""


def test_an_image_inside_the_footer_tag_is_tagged_footer():
    html = ('<html><body><main><p>content</p></main>'
            '<footer><img src="/social.png" alt="Facebook"></footer>'
            '</body></html>')
    from src.extract import extract_all_images

    icon = next(i for i in extract_all_images(html, "https://e.edu/") if "social" in i.src)
    assert icon.region == "footer"


def test_a_prefooter_block_inside_main_is_still_tagged_footer():
    """Confirmed on the real UTA homepage: prefooter-image-* elements sit
    positionally inside <main>, ahead of the real <footer>, but are
    functionally part of the footer area."""
    html = ('<html><body><main>'
            '<p>content</p>'
            '<section class="prefooter-image-block">'
            '<img src="/cta.jpg" alt="Apply now"></section>'
            '</main></body></html>')
    from src.extract import extract_all_images

    cta = next(i for i in extract_all_images(html, "https://e.edu/") if "cta" in i.src)
    assert cta.region == "footer"


def test_an_ordinary_content_image_has_no_region():
    html = '<html><body><main><img src="/photo.jpg" alt="Campus"></main></body></html>'
    from src.extract import extract_all_images

    photo = extract_all_images(html, "https://e.edu/")[0]
    assert photo.region == ""


def test_region_of_tags_a_nav_element_outside_main():
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><nav><img src="/menu-icon.png"></nav>'
        '<main><p>content</p></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == "nav"


def test_region_of_falls_back_to_a_navbar_class_when_theres_no_nav_tag():
    """Not every site marks its nav with the semantic <nav> tag."""
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><div class="site-navbar"><img src="/menu-icon.png"></div>'
        '<main><p>content</p></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == "nav"


def test_region_of_falls_back_to_a_role_navigation_attribute():
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><div role="navigation"><img src="/menu-icon.png"></div>'
        '<main><p>content</p></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == "nav"


def test_region_of_falls_back_to_a_header_class_when_theres_no_header_tag():
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><div class="site-header"><img src="/logo.png"></div>'
        '<main><p>content</p></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == "header"


def test_region_of_does_not_mistake_a_hero_banner_class_for_site_chrome():
    """"banner" alone is excluded from the header fallback pattern -- it is
    just as often a content hero image's own class name as it is the ARIA
    landmark word, and only role="banner" is an unambiguous signal."""
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><main><div class="hero-banner">'
        '<img src="/hero.jpg"></div></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == ""


def test_a_nav_tag_used_for_in_page_jump_links_inside_main_is_not_chrome():
    """The same content-sectioning risk as <header> -- a <nav> wrapping a
    table of contents inside the article body is not the site's navbar."""
    from bs4 import BeautifulSoup
    from src.extract import _find_main_landmark, _region_of

    soup = BeautifulSoup(
        '<html><body><main><nav><a href="#s1">Section 1</a></nav>'
        '<img src="/diagram.png"></main></body></html>', "lxml")
    main_landmark = _find_main_landmark(soup)
    img = soup.find("img")
    assert _region_of(img, main_landmark) == ""


# --- content media: images/links/buttons/video/forms, and chrome-as-context ---

CONTENT_MEDIA_PAGE = """
<html><head><title>T</title></head>
<body>
<nav class="main-nav"><a href="/admissions">Admissions</a></nav>
<header class="site-header">Site Header Text</header>
<main>
  <h1>College of Engineering</h1>
  <p>Welcome. <a href="https://e.edu/apply" class="btn btn-primary">Apply Now</a></p>
  <h2>Photo Gallery</h2>
  <img src="/img/campus.jpg" alt="Students on the quad">
  <h2>Watch Our Story</h2>
  <iframe src="https://www.youtube.com/embed/abc123" title="Our Story Video"></iframe>
  <h2>Apply for Aid</h2>
  <p>Download the <a href="https://e.edu/forms/aid.pdf">financial aid form</a>.</p>
  <h2>Contact Us</h2>
  <form aria-label="Contact form"><input type="text"></form>
  <h2>Campus Tour</h2>
  <video src="/videos/tour.mp4"><track kind="captions" src="/videos/tour.vtt"></video>
</main>
<footer class="site-footer">Copyright 2026. <a href="/privacy">Privacy</a></footer>
</body></html>
"""


@pytest.fixture(scope="module")
def media_page():
    return extract(CONTENT_MEDIA_PAGE, "https://e.edu/engineering")


def test_an_image_is_captured_with_its_alt_text_and_heading_path(media_page):
    image = next(m for m in media_page.content_media if m.kind == "image")
    assert image.text == "Students on the quad"
    assert image.href.endswith("/img/campus.jpg")
    assert image.heading_path == ["College of Engineering", "Photo Gallery"]


def test_a_btn_classed_link_is_captured_as_a_button(media_page):
    button = next(m for m in media_page.content_media if m.kind == "button")
    assert button.text == "Apply Now"
    assert button.href == "https://e.edu/apply"


def test_an_ordinary_link_is_not_a_button(media_page):
    link = next(m for m in media_page.content_media if m.kind == "link")
    assert link.text == "financial aid form"
    assert link.is_document is True   # .pdf


def test_a_youtube_iframe_is_captured_as_a_video_with_its_title(media_page):
    video = next(m for m in media_page.content_media
                if m.kind == "video" and m.platform == "youtube")
    assert video.href == "https://www.youtube.com/embed/abc123"
    assert video.text == "Our Story Video"
    assert video.heading_path == ["College of Engineering", "Watch Our Story"]


def test_a_native_video_tag_is_captured_with_its_caption_track(media_page):
    video = next(m for m in media_page.content_media if m.platform == "html5")
    assert video.kind == "video"
    assert video.has_captions is True
    assert video.heading_path == ["College of Engineering", "Campus Tour"]


def test_a_native_form_is_captured_with_its_aria_label(media_page):
    form = next(m for m in media_page.content_media if m.kind == "form")
    assert form.text == "Contact form"
    assert form.heading_path == ["College of Engineering", "Contact Us"]


def test_nav_and_footer_content_never_appears_as_content_media(media_page):
    """The nav/footer links (/admissions, /privacy) are chrome, not content --
    excluded from content_media the same way they're excluded from blocks."""
    hrefs = {m.href for m in media_page.content_media}
    assert not any(h.endswith(("/admissions", "/privacy")) for h in hrefs)


def test_forms_and_iframes_still_produce_no_blocks_or_stray_text(media_page):
    """Adding content_media support must not change extract_blocks's output --
    Migration Validator depends on that sequence staying exactly as it was."""
    assert all(b.kind in ("heading", "paragraph", "list", "table", "quote")
              for b in media_page.blocks)
    assert not any("Contact form" in b.text for b in media_page.blocks)


def test_chrome_text_captures_nav_header_and_footer(media_page):
    assert "Admissions" in media_page.chrome_text
    assert "Site Header Text" in media_page.chrome_text
    assert "Copyright 2026" in media_page.chrome_text


def test_chrome_text_is_labeled_by_region(media_page):
    assert "Nav:" in media_page.chrome_text
    assert "Header:" in media_page.chrome_text
    assert "Footer:" in media_page.chrome_text


def test_a_jotform_iframe_is_captured_as_a_form():
    html = """
    <html><body><main><h1>Register</h1>
    <iframe src="https://form.jotform.com/12345" title="Registration Form"></iframe>
    </main></body></html>
    """
    page = extract(html, "https://e.edu/register")
    form = next(m for m in page.content_media if m.kind == "form")
    assert form.text == "Registration Form"


def test_an_unrecognized_iframe_is_silently_skipped_not_captured():
    html = """
    <html><body><main><h1>Ads</h1>
    <iframe src="https://ads.example.com/banner"></iframe>
    </main></body></html>
    """
    page = extract(html, "https://e.edu/x")
    assert page.content_media == []


def test_a_role_button_link_without_a_btn_class_is_still_a_button():
    html = """
    <html><body><main><h1>Start</h1>
    <a href="https://e.edu/go" role="button">Get Started</a>
    </main></body></html>
    """
    page = extract(html, "https://e.edu/x")
    item = page.content_media[0]
    assert item.kind == "button"


def test_a_card_link_keeps_its_image_and_its_own_title_heading():
    from bs4 import BeautifulSoup
    from src.extract import extract_content_media

    html = ('<div><h2>Venues</h2>'
            '<div><a href="https://x.test/a"><img alt="Hall A" src="/a.jpg"><h6>Hall A</h6></a></div>'
            '<div><a href="https://x.test/b"><img alt="Hall B" src="/b.jpg"><h6>Hall B</h6></a></div></div>')
    region = BeautifulSoup(html, "html.parser").div
    items = extract_content_media(region, lambda u: "https://x.test" + u if u.startswith("/") else u,
                                  "https://x.test/")
    by_kind = {(i.kind, i.heading_path[-1]) for i in items}
    assert ("image", "Hall A") in by_kind and ("link", "Hall A") in by_kind
    assert ("image", "Hall B") in by_kind and ("link", "Hall B") in by_kind
