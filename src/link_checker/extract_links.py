"""Every linkable element on a page, region-tagged.

Deliberately whole-document, not main-region-scoped: header/nav/footer links
are exactly what the "include header/navbar/footer" checkboxes need to be
able to find and exclude, and `find_main_region`'s own noise-stripping would
delete them before they were ever seen -- the same reasoning `extract_all_
images` (the alt-text scanner) already applies to images.

Region detection is shared with that scanner too, not reimplemented: `extract
.py`'s `_region_of`/`_find_main_landmark` already solve "is this element site
chrome, and if so which kind" -- including the real-world edge cases that
motivated it (a content section's own <header>, a "prefooter" block sitting
inside <main>). Adding "nav" alongside "header"/"footer" there was the one
piece this feature needed that the alt-text scanner didn't.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from ..extract import _clean_text, _find_main_landmark, _region_of
from ..urls import absolutize, make_resolver, unwrap_wayback
from .models import RawLink

# javascript: is never a real destination. mailto:/tel: are real destinations
# with no HTTP resolution, so they are handled specially, not skipped.
_SKIP_SCHEMES = ("javascript:", "void(")


def extract_all_links(html: str, url: str, fetched_url: str | None = None) -> list[RawLink]:
    """Every `<a href>`/`<area href>` on the whole page, resolved to an
    absolute URL (fragment kept, since `#section` is a real, distinct
    destination -- see categorize.py) and tagged with its page-chrome region.
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    base_url = fetched_url or url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(base_tag["href"], base_url)
    resolve = make_resolver(base_url)
    main_landmark = _find_main_landmark(soup)
    page_url = unwrap_wayback(url)

    out: list[RawLink] = []
    seen: set[tuple[str, str]] = set()

    def add(raw: str, tag: Tag, *, element: str) -> None:
        raw = (raw or "").strip()
        if not raw or raw.lower().startswith(_SKIP_SCHEMES):
            return
        if raw.startswith(("mailto:", "tel:")):
            href = raw
        else:
            href = resolve(raw)
            if not href:
                return
        key = (href, element)
        if key in seen:
            return
        seen.add(key)
        # <area> (image-map regions) carries no text content of its own --
        # `alt` is its real label, the same way it is for <img>.
        text = _clean_text(tag.get_text(" ")) or _clean_text(
            tag.get("aria-label") or tag.get("alt") or tag.get("title") or "")
        out.append(RawLink(
            url=href, text=text, region=_region_of(tag, main_landmark),
            found_on=page_url, element=element,
        ))

    for tag in soup.find_all("a", href=True):
        add(tag["href"], tag, element="a")
    for tag in soup.find_all("area", href=True):
        add(tag["href"], tag, element="area")

    return out
