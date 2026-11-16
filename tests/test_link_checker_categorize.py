from src.link_checker.categorize import categorize
from src.link_checker.models import (
    CATEGORY_ANCHOR, CATEGORY_DOCUMENT, CATEGORY_EMAIL, CATEGORY_EXTERNAL,
    CATEGORY_IMAGE, CATEGORY_INTERNAL_IN_SCOPE, CATEGORY_INTERNAL_OTHER,
    CATEGORY_MEDIA, CATEGORY_PHONE,
)

ROOT = "https://www.uta.edu/admissions/"


def test_mailto_is_email():
    assert categorize("mailto:info@uta.edu", root_prefix=ROOT) == CATEGORY_EMAIL


def test_tel_is_phone():
    assert categorize("tel:+18175551234", root_prefix=ROOT) == CATEGORY_PHONE


def test_a_fragment_is_anchor_even_on_an_internal_page():
    assert categorize("https://www.uta.edu/admissions/apply#form",
                      root_prefix=ROOT) == CATEGORY_ANCHOR


def test_a_pdf_is_document_even_when_hosted_on_the_scanned_domain():
    assert categorize("https://www.uta.edu/admissions/catalog.pdf",
                      root_prefix=ROOT) == CATEGORY_DOCUMENT


def test_an_image_extension_is_image():
    assert categorize("https://www.uta.edu/img/hero.jpg", root_prefix=ROOT) == CATEGORY_IMAGE


def test_a_video_extension_is_media():
    assert categorize("https://www.uta.edu/video/tour.mp4", root_prefix=ROOT) == CATEGORY_MEDIA


def test_a_page_under_the_scanned_path_prefix_is_internal_in_scope():
    assert categorize("https://www.uta.edu/admissions/apply/graduate/",
                      root_prefix=ROOT) == CATEGORY_INTERNAL_IN_SCOPE


def test_the_root_url_itself_is_internal_in_scope():
    assert categorize(ROOT, root_prefix=ROOT) == CATEGORY_INTERNAL_IN_SCOPE


def test_a_page_on_the_same_domain_outside_the_prefix_is_internal_other():
    assert categorize("https://www.uta.edu/athletics/",
                      root_prefix=ROOT) == CATEGORY_INTERNAL_OTHER


def test_a_different_domain_is_external():
    assert categorize("https://utamavs.com/news/story",
                      root_prefix=ROOT) == CATEGORY_EXTERNAL


def test_a_fragment_containing_whitespace_is_not_treated_as_a_real_anchor():
    """Confirmed on a real UTA page: a carousel link's href was authored as
    ".../article#Learn More" -- the visible label pasted onto the href by
    mistake. No HTML id can contain a space, so this can never be a genuine
    anchor target; checking it as one would always report "broken"."""
    assert categorize(
        "https://www.uta.edu/news/article#Learn More", root_prefix=ROOT
    ) == CATEGORY_INTERNAL_OTHER


def test_a_percent_encoded_space_in_a_fragment_is_also_not_a_real_anchor():
    assert categorize(
        "https://www.uta.edu/news/article#Learn%20More", root_prefix=ROOT
    ) == CATEGORY_INTERNAL_OTHER


def test_a_normal_single_token_fragment_is_still_an_anchor():
    assert categorize(
        "https://www.uta.edu/news/article#learn-more", root_prefix=ROOT
    ) == CATEGORY_ANCHOR


def test_a_page_scan_has_no_wider_in_scope_section():
    """For a Page Scan, root_prefix is just the scanned page's own URL -- an
    internal link to a sibling page has nothing to be "in scope" against."""
    page_root = "https://www.uta.edu/admissions/apply"
    assert categorize("https://www.uta.edu/admissions/deadlines",
                      root_prefix=page_root) == CATEGORY_INTERNAL_OTHER
