"""extract_all_links: whole-document link pulling + region tagging."""

from src.link_checker.extract_links import extract_all_links


def test_a_plain_internal_link_is_found_with_its_text():
    html = '<html><body><main><a href="/about">About us</a></main></body></html>'
    links = extract_all_links(html, "https://e.edu/")
    assert len(links) == 1
    assert links[0].url == "https://e.edu/about"
    assert links[0].text == "About us"
    assert links[0].region == ""


def test_a_link_in_the_header_is_tagged_header():
    html = ('<html><body><header><a href="/apply">Apply</a></header>'
            '<main><p>content</p></main></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    assert links[0].region == "header"


def test_a_link_in_the_nav_is_tagged_nav():
    html = ('<html><body><nav><a href="/programs">Programs</a></nav>'
            '<main><p>content</p></main></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    assert links[0].region == "nav"


def test_a_link_in_the_footer_is_tagged_footer():
    html = ('<html><body><main><p>content</p></main>'
            '<footer><a href="/privacy">Privacy</a></footer></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    assert links[0].region == "footer"


def test_mailto_and_tel_links_are_kept_as_is_not_url_resolved():
    html = ('<html><body><main>'
            '<a href="mailto:info@e.edu">Email us</a>'
            '<a href="tel:+18175551234">Call us</a>'
            '</main></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    urls = {l.url for l in links}
    assert "mailto:info@e.edu" in urls
    assert "tel:+18175551234" in urls


def test_a_fragment_only_href_keeps_its_fragment():
    html = '<html><body><main><a href="#section-2">Jump</a></main></body></html>'
    links = extract_all_links(html, "https://e.edu/page")
    assert links[0].url == "https://e.edu/page#section-2"


def test_javascript_links_are_skipped():
    html = '<html><body><main><a href="javascript:void(0)">Click</a></main></body></html>'
    assert extract_all_links(html, "https://e.edu/") == []


def test_an_area_elements_alt_text_is_used_since_it_has_no_text_content():
    html = ('<html><body><main><map name="m">'
            '<area href="/labs" alt="Research labs" shape="rect" coords="0,0,10,10">'
            '</map></main></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    assert links[0].text == "Research labs"
    assert links[0].element == "area"


def test_duplicate_links_on_the_same_page_are_collapsed_once():
    html = ('<html><body><main>'
            '<a href="/about">About</a><a href="/about">About us</a>'
            '</main></body></html>')
    links = extract_all_links(html, "https://e.edu/")
    assert len(links) == 1


def test_links_carry_the_page_they_were_found_on():
    html = '<html><body><main><a href="/about">About</a></main></body></html>'
    links = extract_all_links(html, "https://e.edu/campus")
    assert links[0].found_on == "https://e.edu/campus"
