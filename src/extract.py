"""Turn raw HTML into a normalized PageContent.

Two extractors, each doing the job it is actually good at:

* **Body text** comes from trafilatura, which is purpose-built for stripping
  boilerplate. It runs in favor-recall mode: for migration QA, wrongly dropping
  a paragraph is the expensive mistake -- it would show up downstream as
  phantom "content missing" and burn a reviewer's trust.
* **Structure** (headings, images, links) comes from a DOM pass over the main
  content region, because trafilatura's text output does not preserve enough
  of the tree to compare heading hierarchy or read alt attributes.

Locating the main region is a cascade: explicit landmarks first (<main>,
<article>, role=main, the usual #content ids), then readability-lxml, then a
cleaned <body>. Every path first strips nav/header/footer/aside and elements
whose class or id names them as chrome, so a missing landmark never means
counting the nav's links as content.
"""

from __future__ import annotations

import re
from copy import copy
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import (
    DOCUMENT_EXTENSIONS, Block, Heading, Image, Link, MediaItem, PageContent, FetchResult,
)
from .urls import absolutize, make_resolver, normalize, unwrap_wayback

# Tags that never carry page content. "iframe"/"form" are deliberately NOT
# here -- `extract_content_media` needs to see them (video embeds, form
# presence) before they're removed. `extract()` kills them itself, right
# after that pass runs, so every other consumer (`extract_blocks`,
# `extract_images`, `extract_links`, `extract_text`) sees exactly the same
# tree it always did -- see `_walk_blocks`'s explicit form/iframe skip below,
# which keeps that true even for the brief window they're still present.
NOISE_TAGS = ("script", "style", "noscript", "template", "svg")
_NOISE_TAGS_STRIPPED_LATE = ("iframe", "form")

# Landmark tags/selectors that mean "the content starts here", best first.
MAIN_SELECTORS = (
    "main",
    "[role=main]",
    "article",
    "#main-content",
    "#mainContent",
    "#content",
    "#main",
    ".entry-content",      # WordPress
    ".post-content",
    ".page-content",
    ".field--name-body",   # Drupal, occasionally seen alongside Sitecore
)

# class/id substrings that mark a block as site chrome rather than content.
CHROME_PATTERN = re.compile(
    r"(^|[-_ ])(nav|navbar|navigation|menu|breadcrumb|header|footer|sidebar|"
    r"aside|banner|cookie|consent|skip-link|social|share|advert|ads?|promo|"
    r"subscribe|newsletter|related-posts|site-tools|utility-nav|wm-ipp)([-_ ]|$)",
    re.IGNORECASE,
)

# Wayback injects its own toolbar markup even on some id_ responses.
WAYBACK_CHROME_IDS = ("wm-ipp-base", "wm-ipp", "donato", "playback")

# class/id/role substrings that mark an <a> as a styled button/CTA rather
# than an inline text link -- same pattern-matching posture as CHROME_PATTERN.
BUTTON_PATTERN = re.compile(r"(^|[-_ ])(btn|button|cta)([-_ ]|$)", re.IGNORECASE)

# Known video-embed iframe hosts -> platform label. Anything else stays an
# ordinary skipped iframe (an ad, a widget), same as before this file
# started looking at iframes at all.
VIDEO_IFRAME_HOSTS = (
    (re.compile(r"(^|\.)youtube(-nocookie)?\.com$", re.IGNORECASE), "youtube"),
    (re.compile(r"(^|\.)(player\.)?vimeo\.com$", re.IGNORECASE), "vimeo"),
    (re.compile(r"(^|\.)panopto(\.eu)?\.com$|(^|\.)panopto\.eu$", re.IGNORECASE), "panopto"),
)

# Known external form-provider iframe hosts -- a form embedded via a hosted
# widget rather than a native <form> tag.
FORM_PROVIDER_HOSTS = re.compile(
    r"(^|\.)(jotform\.com|docs\.google\.com|qualtrics\.com|formstack\.com|typeform\.com)$",
    re.IGNORECASE,
)

# Sitecore and most university templates set hero/section artwork through CSS
# rather than <img>. Ignoring these would report phantom image loss whenever a
# migration moves that artwork into a real <img> tag (or the reverse).
#
# Two passes, not one: a single "background(-image)?:...url(" regex only ever
# captures the *last* url() in the declaration, because the greedy middle
# `[^;]*` consumes past every earlier one before backtracking to find one to
# match against. A layered background -- "background-image: url(a), url(b)"
# -- is valid, ordinary CSS, and the first pattern silently dropped url(a).
_BACKGROUND_DECLARATION = re.compile(
    r"background(?:-image)?\s*:([^;}]*)", re.IGNORECASE
)
_URL_FN = re.compile(r"""url\(\s*['"]?([^'")]+)""")


def _background_urls(css_text: str) -> list[str]:
    """Every url() named in a background/background-image declaration --
    plural, since a layered background can carry more than one."""
    out: list[str] = []
    for declaration in _BACKGROUND_DECLARATION.findall(css_text or ""):
        for match in _URL_FN.finditer(declaration):
            raw = match.group(1).strip()
            if raw and not raw.startswith("data:"):
                out.append(raw)
    return out

_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def _clean_text(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", s).strip()


# --------------------------------------------------------------------------
# locating the main content region
# --------------------------------------------------------------------------

# Modifier prefixes that describe a page's configuration rather than an
# element's role. "has-footer" means the page has a footer, not that this *is*
# one -- and a real Notion page put its entire <article> inside
# `notion-root max-width has-footer`, so matching it deleted the whole page.
STATE_PREFIXES = ("has", "no", "is", "with", "without", "show", "hide")

# A chrome element holding more of the page than this is mislabeled. Site
# furniture is a small fraction of a page by definition.
CHROME_TEXT_SHARE = 0.25


def looks_like_chrome(value: str) -> bool:
    """Whether a class or id string names site furniture.

    A chrome word preceded by a state prefix is not a role, so `has-footer`,
    `no-sidebar` and `with-header` are left alone.
    """
    for match in CHROME_PATTERN.finditer(value or ""):
        before = (value[: match.start(2)] or "").lower()
        if any(before.endswith((f"{p}-", f"{p}_")) for p in STATE_PREFIXES):
            continue
        return True
    return False


def _kill(tag: Tag) -> None:
    """Decompose a tag unless an earlier pass already took its subtree.

    find_all() hands back descendants of nodes we may have just removed, and
    touching a decomposed tag raises, so every removal checks first.
    """
    if isinstance(tag, Tag) and not tag.decomposed:
        tag.decompose()


def _strip_noise(soup: BeautifulSoup | Tag) -> None:
    """Remove scripts, chrome landmarks, and anything named like site chrome."""
    for tag in list(soup.find_all(NOISE_TAGS)):
        _kill(tag)
    for tag in list(soup.find_all(("nav", "header", "footer", "aside"))):
        _kill(tag)
    for tag in list(soup.find_all(attrs={"role": re.compile(
            r"^(navigation|banner|contentinfo|complementary|search)$", re.I)})):
        _kill(tag)
    for tag in list(soup.find_all(attrs={"aria-hidden": "true"})):
        _kill(tag)
    # How much text the page holds in total, so a "footer" that turns out to
    # contain most of it can be recognized as mislabeled rather than deleted.
    total_text = len(_clean_text(soup.get_text(" ")))

    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or tag.decomposed:
            continue
        ident = str(tag.get("id") or "")
        if any(w in ident.lower() for w in WAYBACK_CHROME_IDS):
            _kill(tag)
            continue
        names = " ".join(tag.get("class") or [])
        if not (looks_like_chrome(names) or looks_like_chrome(ident)):
            continue
        # A page's own h1 is never inside site furniture; Notion's page header
        # block carries the title, and stripping it lost the heading outright.
        # The element may *be* the h1 as well as contain one -- the title block
        # puts the chrome-looking class on the heading itself.
        if tag.name == "h1" or tag.find("h1") is not None:
            continue
        if total_text and _text_len(tag) / total_text > CHROME_TEXT_SHARE:
            continue
        _kill(tag)


def _text_len(node: Tag | None) -> int:
    return len(_clean_text(node.get_text(" ")) if node is not None else "")


def _readability_region(html: str) -> Tag | None:
    """Main region per readability-lxml, if it is installed and returns enough."""
    try:
        from readability import Document
    except ImportError:
        return None
    try:
        summary = Document(html).summary(html_partial=True)
    except Exception:
        return None
    node = BeautifulSoup(summary, "lxml")
    _strip_noise(node)
    return node if _text_len(node) >= 200 else None


def find_main_region(soup: BeautifulSoup, raw_html: str) -> tuple[Tag, str]:
    """Return (region, how) -- the content subtree and which strategy found it.

    `soup` is mutated: noise is stripped before any selector runs, so a page
    without landmarks still does not contribute its nav to the link count.
    """
    _strip_noise(soup)

    best: tuple[int, Tag | None, str] = (0, None, "")
    for selector in MAIN_SELECTORS:
        try:
            node = soup.select_one(selector)
        except Exception:
            continue
        if node is not None:
            size = _text_len(node)
            if size > best[0]:
                best = (size, node, f"landmark:{selector}")

    # A landmark holding almost nothing is a landmark on the wrong element.
    if best[1] is not None and best[0] >= 200:
        return best[1], best[2]

    region = _readability_region(raw_html)
    if region is not None:
        return region, "readability"

    if best[1] is not None and best[0] > 0:
        return best[1], best[2] + " (thin)"

    body = soup.body or soup
    return body, "body-fallback"


# A page's nav/header/footer text is real content -- just not content a
# component ever gets placed against. `_strip_noise` deletes these elements
# outright (that's the whole point, for the main-content extraction this
# module was built for), so this has to run on the *original* soup, before
# `find_main_region`/`_strip_noise` ever touches it.
_CHROME_TEXT_TAGS = ("nav", "header", "footer")
_CHROME_TEXT_ROLES = re.compile(r"^(navigation|banner|contentinfo)$", re.IGNORECASE)
MAX_CHROME_TEXT_CHARS = 1500


def _chrome_text(soup: BeautifulSoup) -> str:
    """Nav/header/footer text, labeled and capped -- page-level background
    context only (see web_builder/match.py's use of it), never a section a
    component gets matched against."""
    seen: set[int] = set()
    parts: list[str] = []
    candidates = list(soup.find_all(_CHROME_TEXT_TAGS)) + \
        list(soup.find_all(attrs={"role": _CHROME_TEXT_ROLES}))
    for tag in candidates:
        if not isinstance(tag, Tag) or id(tag) in seen:
            continue
        seen.add(id(tag))
        text = _clean_text(tag.get_text(" "))
        if not text:
            continue
        label = {"nav": "Nav", "header": "Header", "footer": "Footer"}.get(tag.name, "Nav")
        parts.append(f"{label}: {text}")
    joined = "\n".join(parts)
    if len(joined) > MAX_CHROME_TEXT_CHARS:
        joined = joined[:MAX_CHROME_TEXT_CHARS].rstrip() + " [...]"
    return joined


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

def extract_headings(region: Tag) -> list[Heading]:
    """Every heading, real or faked, in document order.

    Derived from `extract_blocks` rather than a plain `find_all(h1..h6)` so
    the two agree by construction: the review screen pairs a heading block
    with its verdict by position against this exact list, and a heading
    real-tag scanning would miss -- see `_bold_only_text` -- but blocks
    caught would silently misalign every heading after it.
    """
    return [Heading(level=b.level, text=b.text)
            for b in extract_blocks(region) if b.kind == "heading"]


_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# A line whose entire content is bolded and short is the mark-up a rich-text
# editor produces when an author "makes a heading" without ever choosing a
# real heading style -- extremely common in CMS body text (FAQ questions,
# a bolded section label) and invisible to anything that only looks for
# <h1>-<h6>. Bold text embedded *within* a longer paragraph ("**Note:** ...")
# is not this -- that is emphasis, not an author-intended heading -- which is
# why the whole paragraph has to be nothing but the bold run, not just start
# with one.
HEADING_LIKE_MAX_WORDS = 20


def _bold_only_text(tag: Tag) -> str | None:
    """`tag`'s text, if its entire content is exactly one <strong>/<b> run."""
    kids = [c for c in tag.children
            if not (isinstance(c, NavigableString) and not c.strip())]
    if len(kids) != 1 or not isinstance(kids[0], Tag) or kids[0].name not in ("strong", "b"):
        return None
    text = _clean_text(kids[0].get_text(" "))
    return text if text and len(text.split()) <= HEADING_LIKE_MAX_WORDS else None


def extract_blocks(region: Tag) -> list[Block]:
    """The region's headings, paragraphs, lists and tables, in document order.

    Unlike `extract_text`, nothing here is flattened: a list stays a list of
    items, a table stays rows of cells, and every content block carries the
    chain of headings above it. This is what lets the review screen render a
    page as a document instead of a stream of same-labeled text blobs, and
    what lets matching treat one paragraph as one passage instead of an
    80-word slice that may span several unrelated ones.
    """
    stack: list[tuple[int, str, bool]] = []
    out: list[Block] = []
    _walk_blocks(region, stack, out)
    return out


def _nearest_real_level(stack: list[tuple[int, str, bool]]) -> int:
    """The level of the closest ancestor that is an actual <hN> tag.

    A faked heading has no level of its own to declare, so it needs a base to
    nest under -- and that base has to be the nearest *real* heading, not
    whatever is on top of the stack. Basing it on the stack top would make
    each faked heading nest one level under the previous one instead of
    sitting beside it as the sibling it visually is: a page of ten FAQ
    questions would otherwise climb from h2 to h11.
    """
    return next((lvl for lvl, _, is_real in reversed(stack) if is_real), 1)


def _push_heading(text: str, level: int, is_real: bool,
                  stack: list[tuple[int, str, bool]], out: list[Block]) -> None:
    while stack and stack[-1][0] >= level:
        stack.pop()
    out.append(Block(kind="heading", level=level, text=text,
                      heading_path=[t for _, t, _ in stack]))
    stack.append((level, text, is_real))


def _walk_blocks(node: Tag, stack: list[tuple[int, str, bool]],
                 out: list[Block]) -> None:
    for child in node.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        name = (child.name or "").lower()

        if name in _NOISE_TAGS_STRIPPED_LATE:
            # Not yet removed from the tree (extract_content_media needs to
            # see them first) -- skipped here, not recursed into, so this
            # walk's output is identical to when they were deleted upfront.
            continue

        if name in _HEADING_TAGS:
            text = _clean_text(child.get_text(" "))
            if text:
                _push_heading(text, int(name[1]), True, stack, out)
            continue

        if name == "p":
            bold_text = _bold_only_text(child)
            if bold_text:
                level = min(6, _nearest_real_level(stack) + 1)
                _push_heading(bold_text, level, False, stack, out)
                continue

        if name == "p":
            text = _clean_text(child.get_text(" "))
            if text:
                out.append(Block(kind="paragraph", text=text,
                                  heading_path=[t for _, t, _ in stack]))
            continue

        if name == "blockquote":
            text = _clean_text(child.get_text(" "))
            if text:
                out.append(Block(kind="quote", text=text,
                                  heading_path=[t for _, t, _ in stack]))
            continue

        if name in ("ul", "ol"):
            items = [_clean_text(li.get_text(" "))
                    for li in child.find_all("li", recursive=False)]
            items = [i for i in items if i]
            if items:
                out.append(Block(kind="list", ordered=(name == "ol"), items=items,
                                  text=" ".join(items),
                                  heading_path=[t for _, t, _ in stack]))
            continue

        if name == "table":
            rows: list[str] = []
            header: list[str] = []
            for i, tr in enumerate(child.find_all("tr")):
                cells = [_clean_text(c.get_text(" "))
                        for c in tr.find_all(("td", "th"))]
                if i == 0 and tr.find("th") is not None:
                    header = cells
                    continue
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows or header:
                flat = " ".join([" | ".join(header)] + rows) if header \
                    else " ".join(rows)
                out.append(Block(kind="table", items=rows, columns=header,
                                  text=flat, heading_path=[t for _, t, _ in stack]))
            continue

        # A generic wrapper (div, section, ...): recurse rather than treat it
        # as content, since templates nest the actual blocks arbitrarily deep.
        _walk_blocks(child, stack, out)


# A "prefooter" call-to-action block is, functionally, part of a page's
# footer area even when it sits positionally inside <main> -- confirmed on
# the real UTA homepage, where three `prefooter-image-*` elements live
# directly inside <main>, ahead of the actual <footer>. Name-matched
# independent of DOM nesting for exactly that reason.
_PREFOOTER_PATTERN = re.compile(r"pre[-_]?footer", re.IGNORECASE)


def _names_footer_section(tag: Tag) -> bool:
    ident = " ".join(tag.get("class") or []) + " " + str(tag.get("id") or "")
    return bool(_PREFOOTER_PATTERN.search(ident))


# Fallback class/id/role patterns for sites that build header/nav chrome out
# of plain <div>s instead of the semantic tag -- the link checker (which,
# unlike the alt-text scanner, needs a real "nav" region so its own Navbar
# checkbox has something to filter) is what motivated adding these, but they
# sharpen header/footer detection for every caller of `_region_of`.
# "banner" is deliberately excluded from the header pattern: it is also a
# common name for an in-content hero image, and only the ARIA role (checked
# separately, unambiguous by spec) is a safe signal for that word.
_HEADER_NAME_PATTERN = re.compile(r"(^|[-_ ])(header|masthead)([-_ ]|$)", re.IGNORECASE)
_NAV_NAME_PATTERN = re.compile(r"(^|[-_ ])(nav|navbar|navigation|menu)([-_ ]|$)", re.IGNORECASE)


def _names_section(tag: Tag, pattern: re.Pattern) -> bool:
    # Trailing/leading whitespace (from a missing class or id joining onto an
    # empty string) would break the patterns' own `$`/`^` anchors otherwise.
    ident = (" ".join(tag.get("class") or []) + " " + str(tag.get("id") or "")).strip()
    return bool(pattern.search(ident))


def _find_main_landmark(soup: Tag) -> Tag | None:
    """The first landmark `extract()` itself would pick, without the
    text-length comparison or noise-stripping that full `find_main_region`
    does -- this only needs a rough "is this inside the real content area"
    answer, to keep a content section's own <header> from being mistaken for
    site chrome (see `_region_of`)."""
    for selector in MAIN_SELECTORS:
        try:
            node = soup.select_one(selector)
        except Exception:
            continue
        if node is not None:
            return node
    return None


def _region_of(tag: Tag, main_landmark: Tag | None) -> str:
    """"header", "nav", "footer", or "" -- which page-chrome region `tag`
    sits in.

    A <footer> tag or a "prefooter"-named element always counts, regardless
    of literal nesting -- see `_names_footer_section`. <header> and <nav> are
    the opposite risk: a content section can legitimately use <header> to
    wrap its own heading (UTA's "Maverick Highlights" grid does exactly this,
    right inside <main>), so either only counts as site chrome when it sits
    *outside* the main content landmark. The closest matching ancestor wins,
    walking from `tag` itself up to the document root.
    """
    node: Tag | None = tag
    while isinstance(node, Tag):
        if node.name == "footer" or _names_footer_section(node):
            return "footer"
        outside_main = main_landmark is None or main_landmark not in node.parents
        if outside_main:
            role = (node.get("role") or "").strip().lower()
            if node.name == "header" or role == "banner" or _names_section(node, _HEADER_NAME_PATTERN):
                return "header"
            if node.name == "nav" or role == "navigation" or _names_section(node, _NAV_NAME_PATTERN):
                return "nav"
        node = node.parent
    return ""


def extract_images(region: Tag, resolve, *,
                   class_bg: dict[str, list[str]] | None = None,
                   id_bg: dict[str, list[str]] | None = None,
                   main_landmark: Tag | None = None) -> list[Image]:
    """Every image in `region`, in document order.

    One walk, not "every <img> tag, then every background image": a real page
    interleaves photos and background-styled sections freely, and a caller
    that displays or matches images by position needs them in the order the
    page actually reads, not grouped by which markup pattern happened to
    carry each one.

    `class_bg`/`id_bg` (selector name -> unresolved URLs, plural because a
    layered background can carry more than one) are threaded through from
    `extract_all_images` so a class- or ID-driven background image slots into
    its true position too, instead of being appended after everything else
    was already collected.

    `main_landmark`, likewise threaded through from `extract_all_images`, is
    what lets each image be tagged with which page-chrome region (if any) it
    sits in -- see `_region_of`. Left `None` here (as `extract()`'s own call
    does, since its `region` is already chrome-stripped) every image just
    gets region "".
    """
    out: list[Image] = []
    seen: set[str] = set()

    def add(raw: str, *, alt, title=None, kind: str = "img", tag_region: str = "") -> None:
        if not raw or raw.strip().startswith("data:"):
            return
        src = resolve(raw.strip().strip("'\""))
        if not src or src in seen:
            return
        seen.add(src)
        out.append(Image(src=src, alt=alt, title=title, kind=kind, region=tag_region))

    for tag in region.find_all(True):
        tag_region = _region_of(tag, main_landmark)

        if tag.name == "img":
            # Lazy-loading themes leave src as a placeholder; the real URL
            # hides in a data- attribute, and a placeholder would look like a
            # changed image.
            raw = (
                tag.get("src")
                or tag.get("data-src")
                or tag.get("data-lazy-src")
                or tag.get("data-original")
                or ""
            )
            alt = tag.get("alt")   # absent attribute and alt="" are different faults
            add(
                raw,
                alt=alt if alt is None else _clean_text(alt),
                title=_clean_text(tag.get("title")) or None,
                tag_region=tag_region,
            )
        elif tag.name == "input" and (tag.get("type") or "").lower() == "image":
            # A real, if uncommon, image-button element with its own alt
            # attribute -- easy to miss entirely because it is not <img>.
            alt = tag.get("alt")
            add(tag.get("src") or "", alt=alt if alt is None else _clean_text(alt),
                tag_region=tag_region)

        # CSS backgrounds -- inline style, a data- attribute, or a class/ID
        # rule this page's own CSS carries. Checked on every tag regardless
        # of what matched above, since a tag can carry both an <img> and its
        # own background style.
        style = tag.get("style")
        if style:
            for raw in _background_urls(style):
                add(raw, alt=None, kind="background", tag_region=tag_region)
        for attr in ("data-bg", "data-background", "data-background-image"):
            if tag.get(attr):
                add(tag[attr], alt=None, kind="background", tag_region=tag_region)
        if class_bg:
            for cls in tag.get("class") or []:
                for raw in class_bg.get(cls, ()):
                    add(raw, alt=None, kind="background", tag_region=tag_region)
        if id_bg:
            tag_id = tag.get("id")
            if tag_id:
                for raw in id_bg.get(tag_id, ()):
                    add(raw, alt=None, kind="background", tag_region=tag_region)

    return out


def _is_document(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in DOCUMENT_EXTENSIONS)


def extract_links(region: Tag, resolve, page_url: str) -> list[Link]:
    page_host = urlsplit(normalize(page_url)).netloc
    out: list[Link] = []
    seen: set[tuple[str, str]] = set()
    for tag in region.find_all("a", href=True):
        raw = tag["href"].strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "sms:")):
            continue
        href = resolve(raw)
        if not href.startswith(("http://", "https://")):
            continue
        text = _clean_text(tag.get_text(" "))
        key = (normalize(href), text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Link(
                href=href,
                text=text,
                is_document=_is_document(href),
                is_external=bool(page_host) and urlsplit(normalize(href)).netloc != page_host,
            )
        )
    return out


_TRACK_KIND_RE = re.compile(r"^(captions|subtitles)$", re.IGNORECASE)


def extract_content_media(region: Tag, resolve, page_url: str) -> list[MediaItem]:
    """Images, links/buttons, video embeds, and forms found while walking
    the same main-content region `extract_blocks` walks, in document order,
    each tagged with the same `heading_path` convention `Block` uses (built
    with the identical heading-detection rules -- real `<hN>` tags and
    all-bold "faked" headings -- so a caller bucketing these against
    `Block`-derived sections by heading text gets a consistent answer).

    A separate walk from `_walk_blocks` rather than a second output channel
    threaded through it -- see `MediaItem`'s docstring for why this stays
    fully independent of `extract_blocks`/`Block`.
    """
    stack: list[tuple[int, str, bool]] = []
    out: list[MediaItem] = []
    seen_links: set[tuple[str, str]] = set()
    seen_images: set[str] = set()

    def heading_path() -> list[str]:
        return [t for _, t, _ in stack]

    def push_heading(text: str, level: int, is_real: bool) -> None:
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text, is_real))

    def img_src(tag: Tag) -> str:
        return (tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
                or tag.get("data-original") or "")

    def add_image(raw: str, alt) -> None:
        if not raw or raw.strip().startswith("data:"):
            return
        src = resolve(raw.strip().strip("'\""))
        if not src or src in seen_images:
            return
        seen_images.add(src)
        out.append(MediaItem(kind="image", text=_clean_text(alt) if alt else "",
                             href=src, heading_path=heading_path()))

    def walk(node: Tag) -> None:
        for child in node.find_all(recursive=False):
            if not isinstance(child, Tag):
                continue
            name = (child.name or "").lower()

            if name in _HEADING_TAGS:
                text = _clean_text(child.get_text(" "))
                if text:
                    push_heading(text, int(name[1]), True)
                continue

            if name == "p":
                bold_text = _bold_only_text(child)
                if bold_text:
                    push_heading(bold_text, min(6, _nearest_real_level(stack) + 1), False)
                    continue
                walk(child)
                continue

            if name == "img":
                add_image(img_src(child), child.get("alt"))
                continue

            if name == "input" and (child.get("type") or "").lower() == "image":
                add_image(child.get("src") or "", child.get("alt"))
                continue

            if name == "video":
                src = child.get("src") or ""
                if not src:
                    source = child.find("source", src=True)
                    src = source["src"] if source else ""
                has_captions = child.find("track", attrs={"kind": _TRACK_KIND_RE}) is not None
                out.append(MediaItem(
                    kind="video", platform="html5", href=resolve(src) if src else "",
                    has_captions=has_captions, heading_path=heading_path()))
                continue

            if name == "iframe":
                src = (child.get("src") or "").strip()
                if src:
                    host = urlsplit(src).netloc.lower()
                    platform = next((p for pattern, p in VIDEO_IFRAME_HOSTS if pattern.search(host)), None)
                    title = _clean_text(child.get("title")) or ""
                    if platform:
                        out.append(MediaItem(kind="video", platform=platform, href=resolve(src),
                                             text=title, heading_path=heading_path()))
                    elif FORM_PROVIDER_HOSTS.search(host):
                        out.append(MediaItem(kind="form", text=title, href=resolve(src),
                                             heading_path=heading_path()))
                continue

            if name == "form":
                legend = child.find("legend")
                label = _clean_text(legend.get_text(" ")) if legend else _clean_text(child.get("aria-label"))
                if not label and stack:
                    label = stack[-1][1]
                out.append(MediaItem(kind="form", text=label, heading_path=heading_path()))
                continue

            if name == "a" and child.get("href"):
                raw = child["href"].strip()
                if raw and not raw.startswith(("#", "javascript:", "mailto:", "tel:", "sms:")):
                    href = resolve(raw)
                    if href.startswith(("http://", "https://")):
                        text = _clean_text(child.get_text(" "))
                        # A card is often one big link: <a><img><h6>Title</h6></a>.
                        # Its title is the heading its link and image belong
                        # to, so register it before recording either -- else
                        # every card's link lands under the previous heading.
                        inner = child.find(_HEADING_TAGS)
                        if inner is not None:
                            inner_text = _clean_text(inner.get_text(" "))
                            if inner_text:
                                push_heading(inner_text, int(inner.name[1]), True)
                        key = (normalize(href), text.lower())
                        if key not in seen_links:
                            seen_links.add(key)
                            classes = " ".join(child.get("class") or [])
                            role = (child.get("role") or "").strip().lower()
                            is_button = bool(BUTTON_PATTERN.search(classes)) or role == "button"
                            out.append(MediaItem(
                                kind="button" if is_button else "link", text=text, href=href,
                                is_document=_is_document(href), heading_path=heading_path()))
                # Linked images (cards, banners, logos) live inside the anchor.
                walk(child)
                continue

            walk(child)

    walk(region)
    return out


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------

def extract_text(raw_html: str, url: str, region: Tag) -> tuple[str, str]:
    """Return (text, extractor_name).

    favor_recall keeps borderline blocks. For this pipeline a false "content
    missing" costs a reviewer's trust, while a stray extra sentence costs a
    rounding error on a similarity score.
    """
    try:
        import trafilatura

        text = trafilatura.extract(
            raw_html,
            url=unwrap_wayback(url) or None,
            favor_recall=True,
            include_comments=False,
            include_tables=True,
            include_formatting=False,
            no_fallback=False,
        )
        if text and len(text.strip()) >= 120:
            return _normalize_block(text), "trafilatura"
    except ImportError:
        pass
    except Exception:
        pass

    return _normalize_block(region.get_text("\n")), "dom-fallback"


def _normalize_block(text: str) -> str:
    lines = [_clean_text(line) for line in (text or "").splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


# --------------------------------------------------------------------------
# entrypoints
# --------------------------------------------------------------------------

def _page_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return _clean_text(og["content"])
    if soup.title and soup.title.string:
        return _clean_text(soup.title.string)
    h1 = soup.find("h1")
    return _clean_text(h1.get_text(" ")) if h1 else ""


def _page_lang(soup: BeautifulSoup) -> str | None:
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if isinstance(html_tag, Tag) else None
    return _clean_text(lang) or None if lang else None


def extract(
    html: str,
    url: str,
    *,
    source: str = "live",
    status: int = 200,
    fetched_url: str | None = None,
    snapshot_timestamp: str | None = None,
    render_mode: str = "static",
) -> PageContent:
    """Normalize one page's HTML into a PageContent."""
    notes: list[str] = []
    page = PageContent(
        url=unwrap_wayback(url),
        fetched_url=fetched_url or url,
        source=source,
        status=status,
        snapshot_timestamp=snapshot_timestamp,
        render_mode=render_mode,
    )
    if not html or not html.strip():
        page.notes.append("empty HTML -- nothing to extract")
        return page

    soup = BeautifulSoup(html, "lxml")
    page.title = _page_title(soup)
    page.lang = _page_lang(soup)
    # Must run before find_main_region/_strip_noise deletes nav/header/footer
    # outright -- there is no recovering this text afterward.
    page.chrome_text = _chrome_text(soup)

    # Which base a relative href resolves against depends on where the page
    # came from -- see make_resolver. An explicit <base> overrides both.
    base_url = fetched_url or url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(base_tag["href"], base_url)
    resolve = make_resolver(base_url)

    region, how = find_main_region(soup, html)
    # Headings are derived from blocks, not walked separately, so the two can
    # never disagree on what counts as a heading -- see extract_headings.
    page.blocks = extract_blocks(region)
    page.headings = [Heading(level=b.level, text=b.text)
                     for b in page.blocks if b.kind == "heading"]
    # Needs iframe/form still present in `region` (video embeds, form
    # presence) -- run before the late strip below removes them, restoring
    # this file's prior behavior for every extractor that follows.
    page.content_media = extract_content_media(region, resolve, page.url)
    for tag in list(region.find_all(_NOISE_TAGS_STRIPPED_LATE)):
        _kill(tag)
    page.images = extract_images(region, resolve)
    page.links = extract_links(region, resolve, page.url)
    page.text, extractor = extract_text(html, url, region)
    page.extractor = f"{extractor} + {how}"

    if how == "body-fallback":
        notes.append("no content landmark found; extracted from cleaned <body>")
    if page.word_count < 50:
        notes.append(f"only {page.word_count} words extracted -- verify by hand")
    if not page.headings:
        notes.append("no headings found in main content")
    page.notes.extend(notes)
    return page


def extract_fetch_result(result: FetchResult) -> PageContent:
    """Extract straight from a FetchResult, carrying its provenance through."""
    page = extract(
        result.html,
        result.url,
        source=result.source,
        status=result.status,
        fetched_url=result.fetched_url,
        snapshot_timestamp=result.snapshot_timestamp,
        render_mode=result.render_mode,
    )
    page.notes = list(result.notes) + page.notes
    return page


_JSONLD_URL = re.compile(r'"(?:@id|url)"\s*:\s*"([^"]+)"')
_META_REFRESH = re.compile(r"url\s*=\s*(.+)$", re.IGNORECASE)


def harvest_links(html: str, url: str, fetched_url: str | None = None) -> list[Link]:
    """Every link in the document, navigation included.

    Deliberately different from `extract().links`, which returns only what is
    inside the main content region. That is right for comparing two pages --
    counting a site's nav as content would report the whole menu as changed on
    every page -- and wrong for crawling, because navigation is precisely how a
    site exposes its pages.

    Using the content extractor to crawl found three links on a real subsite
    whose menu listed eight, so five pages were never visited and every one of
    them was later reported as "not migrated".

    Beyond `<a href>`, a real site hides navigable pages in a few other places,
    and a crawl that only reads anchors misses them the same way: `<link
    rel="next">` pagination, `<link rel="alternate">` translations, `<area
    href>` image-map targets, `<iframe src>` embeds, a meta-refresh redirect
    target, and JSON-LD `@id`/`url` fields (read before the `<script>` tag that
    carries them is stripped, or there is nothing left to read).
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")

    base_url = fetched_url or url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(base_tag["href"], base_url)
    resolve = make_resolver(base_url)
    page_url = unwrap_wayback(url)

    extra_hrefs: list[str] = []

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = tag.string or tag.get_text() or ""
        extra_hrefs += _JSONLD_URL.findall(text)

    for tag in soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)}):
        match = _META_REFRESH.search(tag.get("content") or "")
        if match:
            extra_hrefs.append(match.group(1).strip(" '\""))

    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).lower()
        if any(word in rel for word in ("next", "prev", "alternate")):
            extra_hrefs.append(tag["href"])

    for tag in list(soup.find_all(("script", "style", "noscript", "template"))):
        _kill(tag)

    for tag in soup.find_all("area", href=True):
        extra_hrefs.append(tag["href"])
    for tag in soup.find_all("iframe", src=True):
        extra_hrefs.append(tag["src"])

    links = extract_links(soup, resolve, page_url)

    page_host = urlsplit(normalize(page_url)).netloc
    seen = {(normalize(l.href), l.text.lower()) for l in links}
    for raw in extra_hrefs:
        raw = (raw or "").strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "sms:")):
            continue
        href = resolve(raw)
        if not href.startswith(("http://", "https://")):
            continue
        key = (normalize(href), "")
        if key in seen:
            continue
        seen.add(key)
        links.append(Link(
            href=href, text="", is_document=_is_document(href),
            is_external=bool(page_host) and urlsplit(normalize(href)).netloc != page_host,
        ))

    return links


def stylesheet_urls(html: str, url: str, fetched_url: str | None = None) -> list[str]:
    """Every `<link rel="stylesheet" href>` on the page, resolved.

    For a caller (`alt_text.scan_page`) that wants to fetch those files too:
    a class- or ID-driven background rule is just as often written in an
    external stylesheet as in a page's own `<style>` block, and nothing about
    the markup tells you which without looking.
    """
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "lxml")
    base_url = fetched_url or url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(base_tag["href"], base_url)
    resolve = make_resolver(base_url)

    out: list[str] = []
    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).lower()
        if "stylesheet" in rel:
            href = resolve(tag["href"])
            if href.startswith(("http://", "https://")):
                out.append(href)
    return out


def extract_all_images(html: str, url: str, fetched_url: str | None = None,
                       extra_css: str = "") -> list[Image]:
    """Every image on the page -- not scoped to the main content region, and
    not blind to <noscript> fallbacks or CSS-only backgrounds.

    Deliberately different from `extract().images`, the same way
    `harvest_links` is deliberately different from `extract().links`.
    `extract_images` scopes to the main content region and (via
    `find_main_region` -> `_strip_noise`) strips <noscript> and <style>
    entirely -- all correct for the structural diff, where a nav logo or a
    lazy-load fallback duplicate is noise nobody is trying to compare. None
    of those exclusions belong in an alt-text audit: a header logo, a footer
    social icon and a nav background all need alt text too, and a site that
    lazy-loads its hero image through JavaScript typically ships the real URL
    in exactly the <noscript> fallback extract()'s own noise-stripping throws
    away -- for a real UTA page, that fallback was the *only* static-HTML
    trace of the hero image at all, and scoping to <main> alone missed 22 of
    the page's 31 <img> tags outright.

    A second real page (also UTA's) showed a third pattern: five cards with
    no <img>, no inline style, and no data-* attribute at all -- each one's
    image came entirely from a `.feature-grid-block .athletics { background:
    ... url(...) }` rule in the page's own embedded <style> block. `extra_css`
    covers the sibling case, a rule living in an *external* stylesheet
    instead -- this function has no network access, so a caller with a
    Fetcher (see `stylesheet_urls` above) passes that text in already fetched.

    <noscript> content needs no special handling to reach here: lxml parses
    it as ordinary child elements (the browser-only "treat as raw text"
    behavior is a scripting-enabled-context rule a static parser doesn't
    apply), so simply not stripping the tag is enough.

    Every image also comes back tagged with `.region` ("header", "footer",
    or "") -- see `_region_of` -- so a caller can offer "include header
    images" / "include footer images" as an opt-in without re-deriving the
    page's chrome structure itself.
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")

    base_url = fetched_url or url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(base_tag["href"], base_url)
    resolve = make_resolver(base_url)

    # Found before <script>/<style> are stripped below -- both the region
    # landmark and the <style> text need the document as-authored.
    main_landmark = _find_main_landmark(soup)

    # Read before <style> is stripped, and combined with whatever external
    # CSS the caller already fetched -- see parse_css_background_rules.
    embedded_css = "\n".join(
        tag.string or tag.get_text() or "" for tag in soup.find_all("style"))
    class_bg, id_bg = parse_css_background_rules(embedded_css + "\n" + extra_css)

    # Only tags that can never contribute a real image are removed. Chrome
    # landmarks (nav/header/footer/aside) and <noscript> are left standing,
    # unlike find_main_region's content pass.
    for tag in list(soup.find_all(("script", "style", "template"))):
        _kill(tag)

    return extract_images(soup, resolve, class_bg=class_bg, id_bg=id_bg,
                          main_landmark=main_landmark)


# The right-most class or ID in a selector, ignoring a trailing pseudo-class
# like :hover -- see parse_css_background_rules.
_LAST_SELECTOR_TOKEN = re.compile(
    r"([.#])([A-Za-z0-9_-]+)(?::{1,2}[a-zA-Z-]+)?\s*$")

# A deliberately rough {selector}{body} scanner, not a CSS parser: it does not
# understand nesting, so an @media block's own braces confuse where a rule
# "ends", and it carries no notion of specificity or the cascade. It only
# needs to recover "this class or ID carries this background image", and a
# CMS-generated per-card background rule is reliably a flat rule naming a
# selector distinctive enough that nothing else on the page reuses it for
# something unrelated -- see selectors like ".athletics" or "#highlight_block_1"
# on the real pages that motivated this.
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)


def parse_css_background_rules(css_text: str
                               ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(class name -> URLs, ID -> URLs), read from any CSS text -- an
    embedded <style> block, an external stylesheet, or both concatenated.

    A repeated selector (e.g. a later `:hover` rule that also happens to set
    a background) extends the URL list for that name rather than replacing
    it, matching how the cascade itself would layer two rules of equal
    specificity in document order -- and because a genuinely layered
    background is exactly what a real declaration can already contain (see
    `_background_urls`).
    """
    class_bg: dict[str, list[str]] = {}
    id_bg: dict[str, list[str]] = {}
    for selector_text, body in _CSS_RULE.findall(css_text or ""):
        urls = _background_urls(body)
        if not urls:
            continue
        for one_selector in selector_text.split(","):
            token_match = _LAST_SELECTOR_TOKEN.search(one_selector.strip())
            if not token_match:
                continue
            marker, name = token_match.groups()
            target = class_bg if marker == "." else id_bg
            target.setdefault(name, []).extend(urls)
    return class_bg, id_bg
