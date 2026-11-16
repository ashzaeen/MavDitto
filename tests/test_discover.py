"""Discovery and pairing tests. No network: inventories are built directly."""

import pytest

from src.discover import (
    PageRef, SiteInventory, is_content_url, match_sites, path_similarity,
    relative_path, _normalize_title,
)

OLD_ROOT = "https://old.uta.edu"
NEW_ROOT = "https://www.uta.edu"


def _inventory(root: str, *paths: str, titles: dict[str, str] | None = None
               ) -> SiteInventory:
    titles = titles or {}
    return SiteInventory(
        root=root, method="test",
        pages=[PageRef(url=root.rstrip("/") + p, path=p,
                       title=titles.get(p, ""), source="sitemap")
               for p in paths])


# --- relative paths -------------------------------------------------------

def test_path_is_taken_relative_to_the_root():
    assert relative_path("https://uta.edu/dept/apply", "https://uta.edu/dept") == "/apply"


def test_a_url_outside_the_root_is_rejected():
    """A sitemap often lists pages outside the subsite you asked about, and
    pairing those would compare two sites nobody asked to compare."""
    assert relative_path("https://uta.edu/other/x", "https://uta.edu/dept") is None
    assert relative_path("https://elsewhere.edu/dept/x", "https://uta.edu/dept") is None


def test_cms_extensions_are_stripped_so_sitecore_lines_up_with_wordpress():
    assert relative_path("https://old.edu/About.aspx", "https://old.edu") == \
        relative_path("https://new.edu/about/", "https://new.edu")


def test_root_itself_normalizes_to_a_single_slash():
    assert relative_path("https://uta.edu/", "https://uta.edu") == "/"


@pytest.mark.parametrize("url,ok", [
    ("https://uta.edu/about", True),
    ("https://uta.edu/style.css", False),
    ("https://uta.edu/logo.png", False),
    ("https://uta.edu/wp-json/v2/pages", False),
    ("https://uta.edu/feed/", False),
    ("https://uta.edu/forms/apply.pdf", True),      # documents are content
])
def test_non_content_urls_are_skipped(url, ok):
    assert is_content_url(url) is ok


# --- matching -------------------------------------------------------------

def test_pages_that_did_not_move_match_exactly():
    old = _inventory(OLD_ROOT, "/", "/apply", "/tuition")
    new = _inventory(NEW_ROOT, "/", "/apply", "/tuition")
    report = match_sites(old, new)
    assert len(report.pairs) == 3
    assert {p.method for p in report.pairs} == {"exact"}
    assert report.migrated_share == 1.0


def test_a_page_that_moved_but_kept_its_name_matches_on_slug():
    old = _inventory(OLD_ROOT, "/admissions/apply")
    new = _inventory(NEW_ROOT, "/future-students/apply")
    report = match_sites(old, new)
    assert len(report.pairs) == 1
    assert report.pairs[0].method == "slug"


def test_an_ambiguous_slug_is_not_guessed():
    """Two candidates with the same name is not a match, it is a coin flip."""
    old = _inventory(OLD_ROOT, "/a/index-page")
    new = _inventory(NEW_ROOT, "/b/index-page", "/c/index-page")
    report = match_sites(old, new)
    assert not report.pairs
    assert len(report.unmatched_old) == 1


def test_a_renamed_path_matches_on_similarity():
    old = _inventory(OLD_ROOT, "/portfolio-coding/dev-ops")
    new = _inventory(NEW_ROOT, "/projects/coding/dev-ops")
    report = match_sites(old, new)
    assert len(report.pairs) == 1
    assert report.pairs[0].method in ("slug", "fuzzy-path")


def test_unrelated_paths_are_left_unmatched():
    old = _inventory(OLD_ROOT, "/parking-permits")
    new = _inventory(NEW_ROOT, "/graduate-research-funding")
    report = match_sites(old, new)
    assert not report.pairs
    assert report.unmatched_old[0].path == "/parking-permits"


def test_each_new_page_is_claimed_once():
    old = _inventory(OLD_ROOT, "/apply", "/apply-now")
    new = _inventory(NEW_ROOT, "/apply")
    report = match_sites(old, new)
    assert len(report.pairs) == 1
    assert len(report.unmatched_old) == 1


def test_the_best_match_wins_globally_not_by_iteration_order():
    """A weaker earlier candidate must not steal a page a later one fits better."""
    old = _inventory(OLD_ROOT, "/research-areas", "/research")
    new = _inventory(NEW_ROOT, "/research")
    report = match_sites(old, new)
    assert len(report.pairs) == 1
    assert report.pairs[0].old.path == "/research"      # the exact match wins


# --- the headline ---------------------------------------------------------

def test_old_pages_with_no_counterpart_are_the_headline():
    """A page that no longer exists anywhere is the worst migration failure,
    and a pairwise content diff structurally cannot find it."""
    old = _inventory(OLD_ROOT, "/", "/apply", "/scholarships", "/parking")
    new = _inventory(NEW_ROOT, "/", "/apply")
    report = match_sites(old, new)
    assert [p.path for p in report.unmatched_old] == ["/parking", "/scholarships"]
    assert report.migrated_share == 0.5


def test_net_new_pages_are_reported_separately_from_losses():
    old = _inventory(OLD_ROOT, "/apply")
    new = _inventory(NEW_ROOT, "/apply", "/virtual-tour")
    report = match_sites(old, new)
    assert [p.path for p in report.unmatched_new] == ["/virtual-tour"]
    assert report.migrated_share == 1.0      # nothing was lost


def test_migrated_share_of_an_empty_old_site_is_not_a_division_error():
    assert match_sites(_inventory(OLD_ROOT), _inventory(NEW_ROOT)).migrated_share == 1.0


# --- similarity helpers ---------------------------------------------------

def test_path_similarity_rewards_shared_words():
    """A rename that keeps the words should beat a coincidental string overlap."""
    assert path_similarity("/portfolio-coding", "/projects/coding") > \
        path_similarity("/portfolio-coding", "/contact-copying")


def test_identical_paths_score_one():
    assert path_similarity("/apply", "/apply") == 1.0


def test_title_normalization_drops_the_site_name_suffix():
    assert _normalize_title("Apply Now | University of Texas") == "apply now"
    assert _normalize_title("Apply Now - UTA") == "apply now"
    assert _normalize_title("Apply Now — UTA") == "apply now"


# --- surviving sites that do not answer -----------------------------------

class StubFetcher:
    """Answers some URLs and hangs on others, the way real sites do."""

    def __init__(self, ok: dict[str, str], dead: set[str] = frozenset()):
        # Keys are normalized because that is the form the crawler asks for --
        # a bare root gains its trailing slash on the way through.
        from src.urls import normalize
        self.ok = {normalize(u): html for u, html in ok.items()}
        self.dead = {normalize(u) for u in dead}
        self.batches: list[int] = []

    def fetch_many(self, urls, **kwargs):
        from src.models import FetchResult
        from src.urls import normalize
        self.batches.append(len(urls))
        out = {}
        for url in urls:
            key = normalize(url)
            if key in self.dead or key not in self.ok:
                out[url] = FetchResult(url=url, fetched_url=url, status=0, html="")
            else:
                out[url] = FetchResult(url=url, fetched_url=url, status=200,
                                       html=self.ok[key])
        return out


def _html(title: str) -> str:
    return (f"<html><head><title>{title}</title></head><body><main>"
            f"<h1>{title}</h1><p>" + "body words " * 40 + "</p></main></body></html>")


def test_unresponsive_pages_are_set_aside_not_left_in_the_inventory():
    """A sitemap is a claim, not a guarantee. Pages that never answer must not
    reach the content comparison, which would report them as total loss."""
    from src.discover import check_reachable

    inv = _inventory(NEW_ROOT, "/", "/apply", "/broken")
    fetcher = StubFetcher(
        ok={NEW_ROOT + "/": _html("Home"), NEW_ROOT + "/apply": _html("Apply")},
        dead={NEW_ROOT + "/broken"})
    check_reachable(inv, fetcher)

    assert [p.path for p in inv.pages] == ["/", "/apply"]
    assert [p.path for p in inv.unreachable] == ["/broken"]
    assert any("did not respond" in n for n in inv.notes)


def test_reachability_check_fetches_in_one_batch_not_one_at_a_time():
    """Sequential fetching is what makes a large site unusable: one page that
    never answers costs its whole timeout, and dozens of them add up."""
    from src.discover import check_reachable

    inv = _inventory(NEW_ROOT, *[f"/p{i}" for i in range(20)])
    fetcher = StubFetcher(ok={p.url: _html("x") for p in inv.pages})
    check_reachable(inv, fetcher)
    assert fetcher.batches == [20]


def test_a_crawl_level_is_fetched_as_one_batch():
    from src.discover import crawl

    root = "https://old.uta.edu"
    home = (f"<html><head><title>Home</title></head><body><main><h1>Home</h1>"
            f"<p>{'words ' * 40}</p>"
            f'<a href="{root}/a">A</a><a href="{root}/b">B</a>'
            f'<a href="{root}/c">C</a></main></body></html>')
    fetcher = StubFetcher(ok={
        root: home, root + "/a": _html("A"), root + "/b": _html("B"),
        root + "/c": _html("C")})
    pages, dead, _, blocked = crawl(root, fetcher, max_depth=1)
    assert len(pages) == 4 and not dead and not blocked, (pages, dead)
    assert fetcher.batches == [1, 3]      # the root, then its three children


def test_a_crawl_records_pages_that_never_answer_and_keeps_going():
    from src.discover import crawl

    root = "https://old.uta.edu"
    home = (f"<html><head><title>Home</title></head><body><main><h1>Home</h1>"
            f"<p>{'words ' * 40}</p>"
            f'<a href="{root}/good">Good</a><a href="{root}/dead">Dead</a>'
            f"</main></body></html>")
    fetcher = StubFetcher(ok={root: home, root + "/good": _html("Good")},
                          dead={root + "/dead"})
    pages, dead, notes, blocked = crawl(root, fetcher, max_depth=1)
    from src.urls import normalize
    assert [normalize(p[0]) for p in pages] == [normalize(root),
                                                normalize(root + "/good")]
    assert [normalize(u) for u in dead] == [normalize(root + "/dead")]
    assert any("unreachable" in n for n in notes)
    # A page that simply did not answer is not a page that refused us.
    assert blocked == []


# --- what actually names a page -------------------------------------------

def test_distinctive_titles_are_used_as_the_label():
    from src.discover import choose_label_signal

    pages = [PageRef(url="u1", title="Apply Now"),
             PageRef(url="u2", title="Tuition and Fees"),
             PageRef(url="u3", title="Campus Housing")]
    assert choose_label_signal(pages) == "title"
    assert [p.label for p in pages] == ["Apply Now", "Tuition and Fees",
                                        "Campus Housing"]


def test_a_site_that_serves_one_title_for_every_page_falls_back_to_headings():
    """The default for client-routed sites and many site builders. Matching on
    a shared title would pair every old page with whichever new page happened
    to be compared first."""
    from src.discover import choose_label_signal

    shared = "Ashzaeen Fatmi Khan - Personal Portfolio"
    pages = [PageRef(url="u1", title=shared, heading="VisionScout"),
             PageRef(url="u2", title=shared, heading="Teaching Assistant"),
             PageRef(url="u3", title=shared, heading="Niagara")]
    assert choose_label_signal(pages) == "heading"
    assert [p.label for p in pages] == ["VisionScout", "Teaching Assistant",
                                        "Niagara"]


def test_repeated_titles_with_no_headings_are_reported_as_not_distinctive():
    """Refusing to match is the honest outcome; there is no signal here."""
    from src.discover import choose_label_signal

    pages = [PageRef(url=f"u{i}", title="Same Everywhere") for i in range(5)]
    assert choose_label_signal(pages) == "title (not distinctive)"


def test_a_site_title_suffix_does_not_make_titles_look_distinctive():
    from src.discover import choose_label_signal

    pages = [PageRef(url="u1", title="Apply | UTA"),
             PageRef(url="u2", title="Tuition | UTA"),
             PageRef(url="u3", title="Housing | UTA")]
    assert choose_label_signal(pages) == "title"


def test_pages_are_matched_on_headings_when_titles_all_repeat():
    """End to end: the fallback has to produce the pairs the title signal could
    not, rather than merely declining to produce wrong ones."""
    from src.discover import match_by_title

    shared_old, shared_new = "Old Site", "New Site"
    report = match_sites(
        _inventory(OLD_ROOT, "/p1", "/p2"),
        _inventory(NEW_ROOT, "/a", "/b"))
    for page, heading in zip(report.unmatched_old, ["Robotics Club", "Writing"]):
        page.title, page.heading = shared_old, heading
    for page, heading in zip(report.unmatched_new, ["Writing", "Robotics Club"]):
        page.title, page.heading = shared_new, heading

    class NoFetch:
        def fetch_many(self, urls, **kw):
            raise AssertionError("titles were already present")

    assert match_by_title(report, NoFetch()) == 2
    assert report.label_signals == ("heading", "heading")
    matched = {(p.old.path, p.new.path) for p in report.pairs}
    assert matched == {("/p1", "/b"), ("/p2", "/a")}


# --- exhaustive crawling ----------------------------------------------------

class FlakyFetcher:
    """Fails one URL's first attempt, then answers it -- the way a slow server
    that recovers mid-crawl actually behaves."""

    def __init__(self, ok: dict[str, str], flaky_once: str):
        from src.urls import normalize
        self.ok = {normalize(u): html for u, html in ok.items()}
        self.flaky_once = normalize(flaky_once)
        self.attempts: dict[str, int] = {}
        self.batches: list[int] = []

    def fetch_many(self, urls, **kwargs):
        from src.models import FetchResult
        from src.urls import normalize
        self.batches.append(len(urls))
        out = {}
        for url in urls:
            key = normalize(url)
            self.attempts[key] = self.attempts.get(key, 0) + 1
            if key == self.flaky_once and self.attempts[key] == 1:
                out[url] = FetchResult(url=url, fetched_url=url, status=0, html="")
            elif key in self.ok:
                out[url] = FetchResult(url=url, fetched_url=url, status=200,
                                       html=self.ok[key])
            else:
                out[url] = FetchResult(url=url, fetched_url=url, status=0, html="")
        return out


def test_a_page_that_fails_once_gets_a_second_try():
    """A page that timed out once should not be written off immediately -- a
    slow server that recovers mid-crawl should not cost it its reachability."""
    from src.discover import crawl
    from src.urls import normalize

    root = "https://old.uta.edu"
    home = (f"<html><head><title>Home</title></head><body><main><h1>Home</h1>"
            f"<p>{'words ' * 40}</p>"
            f'<a href="{root}/flaky">Flaky</a></main></body></html>')
    fetcher = FlakyFetcher(ok={root: home, root + "/flaky": _html("Flaky")},
                           flaky_once=root + "/flaky")
    pages, dead, notes, blocked = crawl(root, fetcher, max_depth=1)

    assert normalize(root + "/flaky") in {normalize(p[0]) for p in pages}
    assert not dead
    assert any("retry" in n for n in notes)


def test_retries_can_be_turned_off():
    from src.discover import crawl

    root = "https://old.uta.edu"
    home = (f"<html><head><title>Home</title></head><body><main><h1>Home</h1>"
            f"<p>{'words ' * 40}</p>"
            f'<a href="{root}/flaky">Flaky</a></main></body></html>')
    fetcher = FlakyFetcher(ok={root: home, root + "/flaky": _html("Flaky")},
                           flaky_once=root + "/flaky")
    pages, dead, notes, blocked = crawl(root, fetcher, max_depth=1,
                                        retry_failed=False)
    assert dead


class SitemapAndCrawlFetcher:
    """Answers robots.txt/sitemap requests via _get, and page fetches via
    fetch_many -- enough to exercise discover()'s merge of the two sources."""

    class _Resp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    def __init__(self, sitemap_body: str, pages: dict[str, str]):
        from src.urls import normalize
        self.sitemap_body = sitemap_body
        self.pages = {normalize(u): html for u, html in pages.items()}

    def _get(self, url, params=None, timeout=30.0):
        if url.rstrip("/").endswith("robots.txt"):
            return self._Resp(404, "")
        if url.rstrip("/").endswith("sitemap.xml"):
            return self._Resp(200, self.sitemap_body)
        return self._Resp(404, "")

    def fetch_many(self, urls, **kwargs):
        from src.models import FetchResult
        from src.urls import normalize
        out = {}
        for url in urls:
            key = normalize(url)
            if key in self.pages:
                out[url] = FetchResult(url=url, fetched_url=url, status=200,
                                       html=self.pages[key])
            else:
                out[url] = FetchResult(url=url, fetched_url=url, status=0, html="")
        return out


def test_deep_mode_merges_a_page_the_sitemap_lists_but_nothing_links_to():
    """Neither source is trusted alone in deep mode: a sitemap can list a page
    nobody links to anymore, and a crawl can only find what is actually
    linked. This is the case that justifies running both."""
    from src.discover import discover

    root = "https://old.uta.edu"
    home = (f"<html><head><title>Home</title></head><body><main><h1>Home</h1>"
            f"<p>{'words ' * 40}</p>"
            f'<a href="{root}/b">B</a></main></body></html>')
    sitemap = (f"<urlset><url><loc>{root}/</loc></url>"
              f"<url><loc>{root}/a</loc></url>"
              f"<url><loc>{root}/b</loc></url></urlset>")
    fetcher = SitemapAndCrawlFetcher(
        sitemap, pages={root + "/": home, root + "/b": _html("B")})

    inv = discover(root, fetcher, deep=True, max_depth=1)

    assert {p.path for p in inv.pages} == {"/", "/a", "/b"}
    assert "sitemap" in inv.method and "crawl" in inv.method


def test_without_deep_mode_a_usable_sitemap_is_trusted_alone():
    """Unchanged default behaviour: crawling on top of a working sitemap would
    cost every page a second fetch for no benefit most sites ever need."""
    from src.discover import discover

    root = "https://old.uta.edu"
    sitemap = f"<urlset><url><loc>{root}/</loc></url></urlset>"
    fetcher = SitemapAndCrawlFetcher(sitemap, pages={})

    inv = discover(root, fetcher, max_depth=1)

    assert inv.method.startswith("sitemap")
    assert "crawl" not in inv.method


def test_deep_mode_tries_more_sitemap_paths():
    from src.discover import sitemap_candidates

    class NoRobots:
        def _get(self, url, timeout=15.0):
            class R:
                status_code = 404
                text = ""
            return R()

    shallow = sitemap_candidates("https://old.uta.edu", NoRobots())
    deep = sitemap_candidates("https://old.uta.edu", NoRobots(), deep=True)
    assert len(deep) > len(shallow)
    assert any("wp-sitemap" in c for c in deep)


def test_read_sitemap_respects_a_smaller_children_cap():
    from src.discover import read_sitemap

    class IndexFetcher:
        def __init__(self):
            self.calls: list[str] = []

        def _get(self, url, timeout=30.0):
            self.calls.append(url)

            class R:
                pass
            r = R()
            if url == "https://e.edu/sitemap_index.xml":
                r.status_code = 200
                r.text = ("<sitemapindex>" + "".join(
                    f"<sitemap><loc>https://e.edu/s{i}.xml</loc></sitemap>"
                    for i in range(5)) + "</sitemapindex>")
            else:
                r.status_code = 200
                r.text = "<urlset><url><loc>https://e.edu/p</loc></url></urlset>"
            return r

    fetcher = IndexFetcher()
    read_sitemap("https://e.edu/sitemap_index.xml", fetcher, max_children=2)
    child_calls = [c for c in fetcher.calls if c.rstrip("/").endswith(".xml")
                  and c != "https://e.edu/sitemap_index.xml"]
    assert len(child_calls) == 2


def test_a_leaf_root_climbs_to_its_enclosing_sections():
    from src.discover import _ancestor_roots

    assert _ancestor_roots("https://x.test/venues/index.php") == ["https://x.test/"]   # index file is normalized away
    assert _ancestor_roots("https://x.test/a/b") == ["https://x.test/a", "https://x.test/"]
    assert _ancestor_roots("https://x.test/") == []
