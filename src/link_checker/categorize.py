"""Assigns each link a category from the design doc's link taxonomy.

Order matters: a fragment marks an in-page/cross-page jump regardless of
what the pre-fragment URL looks like, so anchor detection runs first; file
extension beats domain scoping, since a PDF hosted on the scanned domain
itself is still a Document, not an "internal page".
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from ..models import DOCUMENT_EXTENSIONS
from ..urls import normalize
from .models import (
    CATEGORY_ANCHOR, CATEGORY_DOCUMENT, CATEGORY_EMAIL, CATEGORY_EXTERNAL,
    CATEGORY_IMAGE, CATEGORY_INTERNAL_IN_SCOPE, CATEGORY_INTERNAL_OTHER,
    CATEGORY_MEDIA, CATEGORY_PHONE,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}
MEDIA_EXTENSIONS = {".mp4", ".mp3", ".mov", ".avi", ".wav", ".ogg", ".webm", ".m4a", ".m4v"}


def categorize(url: str, *, root_prefix: str) -> str:
    """`root_prefix` is the scan's own starting URL. Its path is the "in
    scope" boundary for Internal (in scope) vs Internal (other section) --
    for a Page Scan there is no wider crawl, so every internal link except
    the page itself naturally falls in "other section".
    """
    if url.startswith("mailto:"):
        return CATEGORY_EMAIL
    if url.startswith("tel:"):
        return CATEGORY_PHONE

    parts = urlsplit(url)
    if url.endswith("#") or (parts.fragment and not re.search(r"\s", unquote(parts.fragment))):
        # An HTML `id`/`name` can never contain whitespace, so a fragment
        # that does isn't a real anchor target -- on a real UTA page, an
        # author had typed `href=".../article#Learn More"` (the visible link
        # label pasted straight onto the href by mistake). Checking that as
        # an anchor would always report it "broken": no element's id is
        # ever literally "Learn More" with a space in it. Falling through
        # lets it categorize -- and get checked -- as whatever the
        # pre-fragment URL actually is.
        return CATEGORY_ANCHOR

    path = parts.path.lower()
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return CATEGORY_IMAGE
    if any(path.endswith(ext) for ext in MEDIA_EXTENSIONS):
        return CATEGORY_MEDIA
    if any(path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
        return CATEGORY_DOCUMENT

    root_norm = urlsplit(normalize(root_prefix))
    url_norm = urlsplit(normalize(url))
    if url_norm.netloc != root_norm.netloc:
        return CATEGORY_EXTERNAL
    root_path = root_norm.path if root_norm.path.endswith("/") else root_norm.path + "/"
    if url_norm.path == root_norm.path or url_norm.path.startswith(root_path):
        return CATEGORY_INTERNAL_IN_SCOPE
    return CATEGORY_INTERNAL_OTHER
