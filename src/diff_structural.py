"""Structural diff: what the heading, image and link structure lost or gained.

Cheap, deterministic, and blind to meaning -- it catches the breakage a reader
would see without reading. The semantic stage (phase 3) handles the rest.

Three things learned from real pages shape this module:

* **Counts are not enough.** The 2019 uta.edu/academics page and its rebuild
  both carry ten headings, of which nine are different. Any diff that compares
  totals calls that page clean, so headings are aligned as a sequence and
  compared by content.
* **Links must be compared site-relative.** A migration moves the whole site,
  so the old page links to `old.edu/apply` where the new one links to
  `new.edu/apply`. Those are the same link. Comparing absolute URLs would
  report every internal link on every page as dropped -- a false-positive flood
  that would bury the real findings.
* **Image URLs change completely.** Sitecore serves `/-/media/<guid>.jpg` and
  WordPress serves `/wp-content/uploads/<year>/<name>.jpg`, so images are
  matched on filename stem and alt text as well as URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from .models import Finding, Heading, Image, Link, PageContent, Severity
from .urls import compare_key, normalize

# Extensions a CMS puts on page URLs. Sitecore emits .aspx where WordPress
# emits a clean path, and that difference is not a moved page.
PAGE_EXTENSIONS = (".aspx", ".asp", ".html", ".htm", ".php", ".jsp", ".cfm")

# Above this score, two headings are one heading reworded; below, the old one
# was dropped and the new one is unrelated. See heading_match_score.
HEADING_REWORD_RATIO = 0.6


@dataclass
class StructuralDiff:
    findings: list[Finding] = field(default_factory=list)
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def worst(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.INFO)

    @property
    def is_clean(self) -> bool:
        return not any(f.severity >= Severity.MEDIUM for f in self.findings)

    def of_kind(self, prefix: str) -> list[Finding]:
        return [f for f in self.findings if f.kind.startswith(prefix)]

    def ranked(self) -> list[Finding]:
        """Worst first; ties keep the order they were found in."""
        return sorted(self.findings, key=lambda f: -int(f.severity))

    def add(self, kind: str, severity: Severity, summary: str,
            items: list[str] | None = None) -> None:
        self.findings.append(Finding(kind, severity, summary, items or []))


# --------------------------------------------------------------------------
# site-relative link identity
# --------------------------------------------------------------------------

def _strip_page_extension(path: str) -> str:
    low = path.lower()
    for ext in PAGE_EXTENSIONS:
        if low.endswith(ext):
            return path[: -len(ext)]
    return path


@dataclass
class SiteContext:
    """The two site roots, so a link can be identified relative to its own site.

    Without this, `old.edu/apply` and `new.edu/apply` look like different links
    and every internal link on every page reports as dropped. With it they
    share the key `/apply` and compare equal.

    Roots default to each page's own scheme+host, which is right for a
    host-to-host move. Pass explicit roots for a subsite move, where both sides
    live on one host under different path prefixes
    (`uta.edu/oldsite` -> `uta.edu/newsite`).
    """

    old_root: str = ""
    new_root: str = ""

    @classmethod
    def from_pages(cls, old: PageContent, new: PageContent,
                   old_root: str = "", new_root: str = "") -> "SiteContext":
        return cls(
            old_root=old_root or _origin(old.url),
            new_root=new_root or _origin(new.url),
        )

    def key(self, url: str, *, side: str) -> str:
        """Identity of a link as seen from `side` ("old" or "new").

        Internal links reduce to their site-relative path; external links keep
        their full normalized URL, since an off-site target is the same target
        whichever page points at it.
        """
        root = self.old_root if side == "old" else self.new_root
        norm = normalize(url)
        if not root:
            return compare_key(norm)

        root_norm = normalize(root)
        root_host = urlsplit(root_norm).netloc
        root_path = urlsplit(root_norm).path.rstrip("/")

        parts = urlsplit(norm)
        if parts.netloc != root_host:
            return compare_key(norm)          # external: compare in full

        path = parts.path
        if root_path and path.lower().startswith(root_path.lower()):
            path = path[len(root_path):] or "/"
        path = _strip_page_extension(path).lower().rstrip("/") or "/"
        return path + (f"?{parts.query}" if parts.query else "")


def _origin(url: str) -> str:
    parts = urlsplit(normalize(url))
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""


# --------------------------------------------------------------------------
# headings
# --------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s]+")


def _norm_heading(text: str) -> str:
    """Compare headings on words alone: case and punctuation churn constantly
    in a migration and never means content was lost."""
    return " ".join(_PUNCT.sub(" ", text.lower()).split())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def heading_match_score(a: str, b: str) -> float:
    """How strongly two normalized headings look like one heading reworded.

    Character similarity alone is actively misleading on section titles.
    'Graduate Studies' and 'Undergraduate Studies' score 0.86 on characters and
    are separate sections of the real uta.edu/academics page -- treating them
    as a rewording would merge them and hide the dropped one. 'Youth Programs'
    and 'Explore Programs' score 0.67 purely on the shared word 'Programs'.

    So multi-word headings need token evidence: they must share at least half
    their words, or one must be an expansion of the other. Single-word headings
    have no tokens to share, and there spelling is all there is to go on.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    tokens_a, tokens_b = set(a.split()), set(b.split())
    char = _ratio(a, b)

    if tokens_a <= tokens_b or tokens_b <= tokens_a:
        return max(char, 0.9)                       # 'Requirements' -> 'Admission Requirements'
    if len(tokens_a) == 1 and len(tokens_b) == 1:
        return char                                 # 'Deadline' -> 'Deadlines'

    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    if jaccard < 0.5:
        return 0.0                                  # too few shared words to be one heading
    return (char + jaccard) / 2


@dataclass
class HeadingAlignment:
    """One old heading paired with its counterpart, if it has one."""

    old: Heading | None
    new: Heading | None
    ratio: float = 1.0

    @property
    def is_dropped(self) -> bool:
        return self.new is None

    @property
    def is_added(self) -> bool:
        return self.old is None

    @property
    def is_reworded(self) -> bool:
        return (self.old is not None and self.new is not None
                and _norm_heading(self.old.text) != _norm_heading(self.new.text))

    @property
    def level_changed(self) -> bool:
        return (self.old is not None and self.new is not None
                and self.old.level != self.new.level)


def align_headings(old: list[Heading], new: list[Heading]) -> list[HeadingAlignment]:
    """Align two heading outlines by content, in document order.

    Exact matches anchor the alignment; inside each differing block, headings
    are paired up greedily by similarity so a reworded section reads as one
    rewording rather than a drop plus an unrelated addition.
    """
    old_keys = [_norm_heading(h.text) for h in old]
    new_keys = [_norm_heading(h.text) for h in new]
    out: list[HeadingAlignment] = []

    for op, i1, i2, j1, j2 in SequenceMatcher(None, old_keys, new_keys).get_opcodes():
        if op == "equal":
            out.extend(HeadingAlignment(old[i], new[j], 1.0)
                       for i, j in zip(range(i1, i2), range(j1, j2)))
            continue
        if op == "delete":
            out.extend(HeadingAlignment(h, None, 0.0) for h in old[i1:i2])
            continue
        if op == "insert":
            out.extend(HeadingAlignment(None, h, 0.0) for h in new[j1:j2])
            continue

        # replace: pair what we can by similarity, report the rest as drops/adds
        remaining_new = list(range(j1, j2))
        for i in range(i1, i2):
            best_j, best_r = None, 0.0
            for j in remaining_new:
                r = heading_match_score(old_keys[i], new_keys[j])
                if r > best_r:
                    best_j, best_r = j, r
            if best_j is not None and best_r >= HEADING_REWORD_RATIO:
                remaining_new.remove(best_j)
                out.append(HeadingAlignment(old[i], new[best_j], best_r))
            else:
                out.append(HeadingAlignment(old[i], None, 0.0))
        out.extend(HeadingAlignment(None, new[j], 0.0) for j in remaining_new)

    return out


def _hierarchy_gaps(headings: list[Heading]) -> list[str]:
    """Places where the outline skips a level, e.g. an h2 followed by an h4.

    Screen readers and outline tools use heading levels as document structure,
    so a skipped level is real breakage even when every heading survived.
    """
    gaps: list[str] = []
    previous = None
    for h in headings:
        if previous is not None and h.level > previous.level + 1:
            gaps.append(f"h{previous.level} '{previous.text}' -> h{h.level} '{h.text}'")
        previous = h
    return gaps


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def _image_stem(src: str) -> str:
    """Filename without directory, query or extension.

    A migration rehosts images entirely -- Sitecore's `/-/media/<guid>.jpg`
    becomes WordPress's `/wp-content/uploads/2026/<name>.jpg` -- so the URL is
    not an identity. The filename usually survives; where it does not, alt text
    usually does.
    """
    path = urlsplit(src).path
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0].lower() if "." in name else name.lower()


def match_images(old: list[Image], new: list[Image]) -> tuple[
        list[tuple[Image, Image]], list[Image], list[Image]]:
    """Pair old images to new ones. Returns (pairs, dropped, added).

    Three passes, most confident first: identical URL, then filename stem, then
    identical alt text. Each new image is claimed once.
    """
    unmatched_new = list(new)
    pairs: list[tuple[Image, Image]] = []
    dropped: list[Image] = []

    def take(predicate):
        for candidate in unmatched_new:
            if predicate(candidate):
                unmatched_new.remove(candidate)
                return candidate
        return None

    for o in old:
        o_key, o_stem = normalize(o.src), _image_stem(o.src)
        found = take(lambda n: normalize(n.src) == o_key)
        if found is None and o_stem:
            found = take(lambda n: _image_stem(n.src) == o_stem)
        if found is None and o.alt and o.alt.strip():
            alt = o.alt.strip().lower()
            found = take(lambda n: (n.alt or "").strip().lower() == alt)
        if found is None:
            dropped.append(o)
        else:
            pairs.append((o, found))

    return pairs, dropped, unmatched_new


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------

def match_links(old: list[Link], new: list[Link], ctx: SiteContext) -> tuple[
        list[tuple[Link, Link]], list[Link], list[Link]]:
    """Pair old links to new ones by site-relative identity."""
    new_by_key: dict[str, list[Link]] = {}
    for l in new:
        new_by_key.setdefault(ctx.key(l.href, side="new"), []).append(l)

    pairs: list[tuple[Link, Link]] = []
    dropped: list[Link] = []
    for o in old:
        bucket = new_by_key.get(ctx.key(o.href, side="old"))
        if bucket:
            pairs.append((o, bucket.pop(0)))
        else:
            dropped.append(o)

    added = [l for bucket in new_by_key.values() for l in bucket]
    return pairs, dropped, added


def _anchor_moves(old: list[Link], new: list[Link], ctx: SiteContext) -> list[str]:
    """Links whose anchor text survived but whose target changed.

    Worth separating from a plain drop: the reader still sees the link, so a
    wrong target is a silent failure rather than a visible gap.
    """
    def by_text(links, side):
        out: dict[str, str] = {}
        for l in links:
            text = l.text.strip().lower()
            if text and text not in out:
                out[text] = ctx.key(l.href, side=side)
        return out

    old_map, new_map = by_text(old, "old"), by_text(new, "new")
    return [
        f"{text!r}: {old_map[text]} -> {new_map[text]}"
        for text in old_map.keys() & new_map.keys()
        if old_map[text] != new_map[text]
    ]


# --------------------------------------------------------------------------
# the diff
# --------------------------------------------------------------------------

def diff_structural(
    old: PageContent,
    new: PageContent,
    *,
    old_root: str = "",
    new_root: str = "",
) -> StructuralDiff:
    """Compare two pages structurally and report what changed.

    Severities say how much each finding suggests real content loss, for phase
    4 to weigh. Additions are reported at INFO throughout: new content is not a
    migration defect, and ranking it alongside losses would bury them.
    """
    ctx = SiteContext.from_pages(old, new, old_root, new_root)
    diff = StructuralDiff(counts={
        "words": (old.word_count, new.word_count),
        "headings": (len(old.headings), len(new.headings)),
        "images": (len(old.images), len(new.images)),
        "background_images": (len(old.background_images), len(new.background_images)),
        "images_missing_alt": (len(old.images_missing_alt), len(new.images_missing_alt)),
        "links": (len(old.links), len(new.links)),
        "document_links": (len(old.document_links), len(new.document_links)),
    })

    _diff_headings(old, new, diff)
    _diff_images(old, new, diff)
    _diff_links(old, new, diff, ctx)
    return diff


def _diff_headings(old: PageContent, new: PageContent, diff: StructuralDiff) -> None:
    alignments = align_headings(old.headings, new.headings)

    dropped = [a.old for a in alignments if a.is_dropped and a.old]
    added = [a.new for a in alignments if a.is_added and a.new]
    reworded = [a for a in alignments if a.is_reworded]
    relevelled = [a for a in alignments if a.level_changed]

    if dropped:
        diff.add("heading.dropped", Severity.HIGH,
                 f"{len(dropped)} heading(s) on the old page have no counterpart",
                 [str(h) for h in dropped])
    if reworded:
        diff.add("heading.reworded", Severity.LOW,
                 f"{len(reworded)} heading(s) reworded",
                 [f"{a.old.text!r} -> {a.new.text!r}" for a in reworded if a.old and a.new])
    if relevelled:
        diff.add("heading.level_changed", Severity.LOW,
                 f"{len(relevelled)} heading(s) changed level",
                 [f"{a.old.text!r}: h{a.old.level} -> h{a.new.level}"
                  for a in relevelled if a.old and a.new])
    if added:
        diff.add("heading.added", Severity.INFO,
                 f"{len(added)} heading(s) are new", [str(h) for h in added])

    old_h1 = [h for h in old.headings if h.level == 1]
    new_h1 = [h for h in new.headings if h.level == 1]
    if old_h1 and not new_h1:
        diff.add("heading.h1_missing", Severity.MEDIUM,
                 "the new page has no h1", [str(h) for h in old_h1])

    gaps_old, gaps_new = _hierarchy_gaps(old.headings), _hierarchy_gaps(new.headings)
    if len(gaps_new) > len(gaps_old):
        diff.add("heading.hierarchy_broken", Severity.LOW,
                 f"the new page skips {len(gaps_new)} heading level(s)", gaps_new)


def _diff_images(old: PageContent, new: PageContent, diff: StructuralDiff) -> None:
    pairs, dropped, added = match_images(old.images, new.images)

    if dropped:
        diff.add("image.dropped", Severity.MEDIUM,
                 f"{len(dropped)} image(s) have no counterpart on the new page",
                 [i.src for i in dropped])
    if added:
        diff.add("image.added", Severity.INFO,
                 f"{len(added)} image(s) are new", [i.src for i in added])

    alt_lost = [(o, n) for o, n in pairs if o.has_alt and not n.has_alt
                and not n.is_decorative]
    if alt_lost:
        diff.add("image.alt_lost", Severity.MEDIUM,
                 f"{len(alt_lost)} image(s) lost their alt text",
                 [f"{n.src} (was {o.alt!r})" for o, n in alt_lost])

    # The finding the real UTA pair surfaced: alt-text counts can *improve*
    # while accessibility gets worse, because an <img> that became a CSS
    # background is no longer an element that can carry alt text at all.
    became_bg = [(o, n) for o, n in pairs if not o.is_decorative and n.is_decorative]
    if became_bg:
        diff.add("image.became_background", Severity.MEDIUM,
                 f"{len(became_bg)} image(s) became CSS backgrounds and can no "
                 "longer carry alt text",
                 [f"{n.src}" + (f" (was {o.alt!r})" if o.has_alt else "")
                  for o, n in became_bg])

    alt_gained = [(o, n) for o, n in pairs if not o.has_alt and n.has_alt]
    if alt_gained:
        diff.add("image.alt_gained", Severity.INFO,
                 f"{len(alt_gained)} image(s) gained alt text",
                 [f"{n.src} ({n.alt!r})" for o, n in alt_gained])


def _diff_links(old: PageContent, new: PageContent, diff: StructuralDiff,
                ctx: SiteContext) -> None:
    pairs, dropped, added = match_links(old.links, new.links, ctx)

    # Documents are split out because they are the plan's called-out risk: a
    # PDF is not part of a page's text, so nothing else in the pipeline would
    # notice it vanishing.
    dropped_docs = [l for l in dropped if l.is_document]
    dropped_pages = [l for l in dropped if not l.is_document]

    if dropped_docs:
        diff.add("link.document_dropped", Severity.HIGH,
                 f"{len(dropped_docs)} document link(s) are gone",
                 [f"{l.text or '(no text)'} -> {l.href}" for l in dropped_docs])
    if dropped_pages:
        diff.add("link.dropped", Severity.MEDIUM,
                 f"{len(dropped_pages)} link(s) have no counterpart",
                 [f"{l.text or '(no text)'} -> {l.href}" for l in dropped_pages])
    if added:
        diff.add("link.added", Severity.INFO,
                 f"{len(added)} link(s) are new",
                 [f"{l.text or '(no text)'} -> {l.href}" for l in added])

    moved = _anchor_moves(old.links, new.links, ctx)
    if moved:
        diff.add("link.target_changed", Severity.MEDIUM,
                 f"{len(moved)} link(s) kept their text but changed target", moved)
