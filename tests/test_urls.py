from src.urls import (
    absolutize, compare_key, make_resolver, normalize, path_slug, same_site,
    unwrap_wayback, wayback_timestamp,
)

WB = "https://web.archive.org/web/20180412030405id_/http://www.uta.edu/dept/page.aspx"


def test_unwrap_wayback_strips_snapshot_wrapper():
    assert unwrap_wayback(WB) == "http://www.uta.edu/dept/page.aspx"


def test_unwrap_wayback_is_idempotent_and_ignores_plain_urls():
    plain = "https://www.uta.edu/dept/page"
    assert unwrap_wayback(plain) == plain
    assert unwrap_wayback(unwrap_wayback(WB)) == unwrap_wayback(WB)


def test_unwrap_wayback_repairs_collapsed_scheme():
    url = "https://web.archive.org/web/20180412030405/http:/example.edu/a"
    assert unwrap_wayback(url) == "http://example.edu/a"


def test_wayback_timestamp():
    assert wayback_timestamp(WB) == "20180412030405"
    assert wayback_timestamp("https://example.edu/") is None


def test_normalize_collapses_equivalent_spellings():
    forms = [
        "http://WWW.Example.edu/About/",
        "https://example.edu/about",
        "https://example.edu/about/index.html",
        "https://example.edu/about#section",
        "https://example.edu/about?utm_source=email",
    ]
    # Scheme and path case are preserved on purpose (see compare_key); the
    # trailing slash, index file, fragment and tracking param must all collapse.
    assert {normalize(f) for f in forms} == {
        "http://example.edu/About",
        "https://example.edu/about",
    }


def test_compare_key_folds_path_case_for_matching():
    assert compare_key("https://example.edu/About/Apply.aspx") ==         compare_key("https://example.edu/about/apply.aspx")
    assert compare_key("http://WWW.Example.edu/About/") == "http://example.edu/about"


def test_normalize_keeps_meaningful_query_params():
    assert normalize("https://example.edu/s?q=tuition&utm_medium=x") == \
        "https://example.edu/s?q=tuition"


def test_normalize_unwraps_wayback_first():
    assert normalize(WB) == "http://uta.edu/dept/page.aspx"


def test_absolutize_resolves_against_snapshot_then_unwraps():
    # A relative link on an archived page must resolve against the snapshot,
    # then unwrap -- doing it the other way round loses the path.
    base = "https://web.archive.org/web/20180412030405id_/http://uta.edu/dept/page.aspx"
    assert absolutize("../forms/apply.pdf", base) == "http://uta.edu/forms/apply.pdf"


def test_same_site_ignores_www():
    assert same_site("https://www.uta.edu/a", "http://uta.edu/b")
    assert not same_site("https://uta.edu/a", "https://libraries.uta.edu/b")


def test_path_slug():
    assert path_slug("https://example.edu/a/b/Admissions/") == "admissions"
    assert path_slug("https://example.edu/") == ""


# --- make_resolver: the base-URL bug that poisons archived link comparison ---

SNAP = "https://web.archive.org/web/20190820234659id_/https://www.uta.edu/academics"


def test_resolver_on_live_page_is_plain_absolutization():
    r = make_resolver("https://www.uta.edu/academics")
    assert r("/academics/programs") == "https://www.uta.edu/academics/programs"
    assert r("../admissions/apply") == "https://www.uta.edu/admissions/apply"


def test_resolver_keeps_root_relative_links_on_the_original_host():
    """Regression: resolving against the snapshot turned /academics/programs
    into web.archive.org/academics/programs, dropping the real path."""
    r = make_resolver(SNAP)
    assert r("/academics/programs") == "https://www.uta.edu/academics/programs"
    assert "web.archive.org" not in r("/academics/programs")


def test_resolver_handles_unrewritten_absolute_links_in_id_snapshots():
    r = make_resolver(SNAP)
    assert r("https://www.uta.edu/cappa/") == "https://www.uta.edu/cappa/"


def test_resolver_unwraps_links_rewritten_by_the_framed_viewer():
    r = make_resolver(SNAP)
    assert r("/web/20190820234659/https://www.uta.edu/gradstudies/") == \
        "https://www.uta.edu/gradstudies/"


def test_resolver_returns_empty_for_empty_href():
    assert make_resolver(SNAP)("") == ""
