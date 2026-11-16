"""Alt text generation: a short, accurate description for an image, written
the way a screen reader needs it.

Two entry points, both funneling through the same generator:

* `AltTextGenerator.generate` -- one image in, one description out. Used
  directly for an uploaded image.
* `scan_page` -- a page URL in, every non-decorative <img> on it described in
  one pass. Reuses `extract.py`'s existing image extraction (which already
  tells a real photo from a CSS background) rather than re-deriving it.

Cost control mirrors the judge (`llm_judge.py`, sharing `llm_cost.py`): a
`Budget` checked before every call, and a disk cache keyed by the image's own
bytes so re-scanning a page that has not changed costs nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .fetch import Fetcher
from .extract import extract_all_images, extract_fetch_result, stylesheet_urls
from .llm_cost import Budget, BudgetExceeded, CredentialsMissing
from .models import PageContent
from .content_writer.brand_voice import is_uta, load_brand_voice
from .setup_engine.config_io import BRAND_VOICE_PATH

# Alt text is a sentence or two; nowhere near the judge's ceiling. A tighter
# cap here also tightens the budget's worst-case estimate for each call.
MAX_OUTPUT_TOKENS = 1024

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "alt_text_cache"

# What Claude's vision input actually accepts. Anything else (SVG, ICO, ...)
# is rejected before it costs a call, not after.
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

MAX_IMAGE_BYTES = 8 * 1024 * 1024

# API calls per page scan -- every discovered image counts against this, since
# whether an image turns out decorative is now the model's call, not a
# pre-filter (see scan_page). Raised well past the old default now that
# scanning covers a whole page rather than one content region: a real header
# and footer alone can carry a dozen icons before the body content even
# starts. The dollar Budget is still the real backstop against a runaway page.
DEFAULT_MAX_PAGE_IMAGES = 40


# --------------------------------------------------------------------------
# the prompt
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You write alt text for images on a university website.

Alt text serves someone using a screen reader who cannot see the image. \
Describe what the image actually shows and, if it functions as a link or \
button, what that control does -- not what you imagine the photographer or \
designer intended.

Work through every image in this order:
1. Is it purely decorative -- a texture, a pattern, a generic stock \
background, a spacer -- with no content or function a reader would need? If \
so, mark it decorative and leave alt_text empty. Do not invent a caption for \
content that isn't there.
2. Does it contain readable text -- a sign, a slide, a flyer, a chart label? \
If so, that text IS the content -- transcribe the important words verbatim. \
If a word is genuinely too blurry or small to read with confidence, say so \
("a flyer with additional text too small to read") rather than guessing a \
plausible-looking word.
3. Otherwise, describe what is actually depicted: the subject, the setting, \
and anything doing work on the page (a control, a link target).

Write in a clear, professional tone: factual and specific, with no marketing \
language ("stunning", "beautiful", "amazing", "vibrant"). Never start with \
"image of" or "photo of" -- a screen reader already announces that this is \
an image. Medium length: normally one full sentence, occasionally two when \
the image genuinely has that much a reader needs. Do not pad a simple image \
to sound thorough, and do not compress a genuinely busy image into a fragment.

Examples:
- A plain color-block spacer graphic -> decorative, empty alt text. NOT \
"A vibrant graphic element."
- A photo of three students studying at a table with laptops -> "Three \
students study together at a table, using laptops." NOT "Students enjoying \
a stunning collaborative learning experience."
- A slide reading "Fall Deadline: October 15" over a campus photo -> "A \
slide reading 'Fall Deadline: October 15' over a photo of a campus building." \
NOT "An informative slide about important dates," which drops the actual text."""


# "Is this deployment UTA's own" has one definition, shared with the Content
# Writer: content_writer.brand_voice.is_uta, read off config/brand-voice.json.
def _uta_context_line(path: Path = BRAND_VOICE_PATH) -> str:
    try:
        bv = load_brand_voice(path)
    except (OSError, json.JSONDecodeError):
        return ""
    if not is_uta(bv):
        return ""
    return (
        "\n\nEvery image handled here comes from the University of Texas at "
        "Arlington (UTA)'s own website -- that is given context, not "
        "something to visually verify. So when an image shows an "
        "institutional mark -- a school logo, seal, mascot, or a star/emblem "
        "on a building, sign, or banner -- describe it as UTA's own rather "
        "than as an unidentified generic mark: \"UTA's logo\" or \"a "
        "UTA-branded sign,\" not \"a star logo\" or \"a logo.\" You do not "
        "need to recognize the specific design from memory to say this -- "
        "the context already establishes whose it is. The same goes for "
        "campus scenery in general: a building, quad, or landmark can be "
        "described as UTA's campus. What still needs restraint is naming "
        "something more specific than the image itself supports: do not "
        "invent which particular building, department, or event this is "
        "unless that is actually legible in the image (signage, a banner, a "
        "name on the building itself).")


def _sniff_media_type(data: bytes) -> str:
    """The real type from the file's magic bytes. A declared type (a server
    Content-Type, a browser's guess from the extension) is routinely wrong,
    and Claude rejects an image whose bytes disagree with the declared type."""
    if data[:8] == bytes.fromhex("89504e470d0a1a0a"):
        return "image/png"
    if data[:3] == bytes.fromhex("ffd8ff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


class AltTextSuggestion(BaseModel):
    is_decorative: bool = Field(
        description=("True if this image is purely decorative and conveys no "
                     "content or function a reader would need: a texture, a "
                     "pattern, a spacer, a generic stock backdrop."))
    alt_text: str = Field(
        description=("The alt text itself, in the voice and length the system "
                     "prompt describes. Empty string if is_decorative is true."))
    rationale: str = Field(
        description="One sentence: why this alt text, or why the image is decorative.")


# --------------------------------------------------------------------------
# what a caller gets back
# --------------------------------------------------------------------------

@dataclass
class AltTextOutcome:
    generated: bool = False
    alt_text: str = ""
    is_decorative: bool = False
    rationale: str = ""
    model: str = ""
    cost_usd: float = 0.0
    cached: bool = False
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "alt_text": self.alt_text,
            "is_decorative": self.is_decorative,
            "rationale": self.rationale,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 6),
            "cached": self.cached,
            "skipped_reason": self.skipped_reason,
        }


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

class AltTextCache:
    """Disk cache keyed by the image's own bytes.

    Scanning the same page twice -- or two pages that happen to share a hero
    image -- costs nothing the second time, the same reasoning as the judge's
    cache in `llm_judge.py`.
    """

    def __init__(self, directory: Path | str = CACHE_DIR, enabled: bool = True):
        self.directory = Path(directory)
        self.enabled = enabled
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, media_type: str, image_bytes: bytes, context: str,
            *, uta_line: str = "") -> str:
        # The UTA line's own content, not just whether one is present -- a
        # future wording tweak (see _uta_context_line) must invalidate every
        # cached UTA result rather than have them silently outlive the
        # prompt that produced them.
        digest = hashlib.sha256(image_bytes).hexdigest()
        uta_digest = hashlib.sha256(uta_line.encode("utf-8")).hexdigest()[:16] if uta_line else ""
        payload = f"{model}\x00{media_type}\x00{context}\x00{uta_digest}\x00{digest}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            (self.directory / f"{key}.json").write_text(
                json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass      # a cache write failure is never worth failing a call over


# --------------------------------------------------------------------------
# the generator
# --------------------------------------------------------------------------

class AltTextGenerator:
    """Generates one image's alt text per call, within a budget.

    The actual provider call goes through `llm_provider.call_structured`
    (Claude or Gemini, whichever is active), which builds its own client
    lazily -- so importing this module, and using the dashboard without ever
    generating alt text, never needs credentials. `self._client` stays
    settable directly for tests, the same seam it always was.
    """

    def __init__(self, *, model: str | None = None, budget: Budget | None = None,
                cache: AltTextCache | None = None, effort: str = "high",
                brand_voice_path: Path = BRAND_VOICE_PATH):
        from . import llm_provider
        self.model = model or llm_provider.default_model("high")
        self.budget = budget or Budget()
        self.cache = cache if cache is not None else AltTextCache()
        self.effort = effort
        self._client = None
        self.budget.price(self.model)      # fail now, not after an image has been read
        # Resolved once per generator, not per image: a run is one page scan or
        # one upload batch, and the brand-voice profile does not change mid-run.
        self._uta_line = _uta_context_line(brand_voice_path)

    def generate(self, image_bytes: bytes, media_type: str, *,
                context: str = "") -> AltTextOutcome:
        """Describe one image."""
        from . import llm_provider

        media_type = _sniff_media_type(image_bytes) or (media_type or "").lower()
        if media_type not in SUPPORTED_MEDIA_TYPES:
            return AltTextOutcome(
                skipped_reason=f"unsupported image type {media_type or '(unknown)'}; "
                              "expected JPEG, PNG, GIF or WebP")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            return AltTextOutcome(
                skipped_reason=f"image is {len(image_bytes) // 1024} KB, over the "
                              f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB cap")
        if not image_bytes:
            return AltTextOutcome(skipped_reason="no image data was received")

        prompt_text = context.strip() or "Write alt text for this image."
        system_prompt = SYSTEM_PROMPT + self._uta_line
        key = AltTextCache.key(self.model, media_type, image_bytes, prompt_text,
                               uta_line=self._uta_line)

        cached = self.cache.get(key)
        if cached is not None:
            outcome = AltTextOutcome(**cached)
            outcome.cached = True
            outcome.cost_usd = 0.0
            return outcome

        # A weak/cheap model occasionally returns a schema-valid response
        # with a blank alt_text for a non-decorative image -- passes
        # validation, but is useless and would otherwise get cached forever
        # for this exact image. One retry is cheap insurance against that
        # specific degenerate case; a second miss is treated as a real failure.
        total_cost = 0.0
        for attempt in range(2):
            try:
                parsed, cost = llm_provider.call_structured(
                    self.model, system_prompt, prompt_text, AltTextSuggestion, self.budget,
                    image=(image_bytes, media_type), max_output_tokens=MAX_OUTPUT_TOKENS,
                    effort=self.effort, client=self._client, label="alt text generator")
            except BudgetExceeded as exc:
                self.budget.skipped += 1
                return AltTextOutcome(skipped_reason=str(exc), cost_usd=total_cost)
            except CredentialsMissing as exc:
                return AltTextOutcome(skipped_reason=str(exc), cost_usd=total_cost)
            except Exception as exc:
                # llm_provider already turned this into a labeled, human-readable
                # message -- explain_api_failure again here would double-wrap it.
                return AltTextOutcome(skipped_reason=str(exc), cost_usd=total_cost)

            total_cost += cost
            degenerate = not parsed.is_decorative and not parsed.alt_text.strip()
            if not degenerate or attempt == 1:
                break

        if degenerate:
            return AltTextOutcome(
                skipped_reason="the model returned an empty description twice in a row for "
                              "this image; try again",
                cost_usd=total_cost)

        outcome = AltTextOutcome(
            generated=True,
            alt_text=("" if parsed.is_decorative else parsed.alt_text.strip()),
            is_decorative=parsed.is_decorative,
            rationale=parsed.rationale,
            model=self.model,
            cost_usd=total_cost,
        )
        self.cache.put(key, {**outcome.to_dict(), "cached": False})
        return outcome


# --------------------------------------------------------------------------
# scanning a whole page
# --------------------------------------------------------------------------

# A class- or ID-driven background rule is just as often written in an
# external stylesheet as in the page's own <style> block -- one real UTA page
# used the former, a second used the latter. Bounded on both count and size:
# a page can link many stylesheets, and a minified one has been seen north of
# half a megabyte here, but this is one deliberate, user-initiated scan of one
# page, not a bulk crawl, so paying for a handful of extra fetches is worth
# not missing a real image.
MAX_STYLESHEETS = 6
MAX_STYLESHEET_BYTES = 2 * 1024 * 1024


def _external_css(html: str, url: str, fetched_url: str, fetcher: Fetcher) -> str:
    texts: list[str] = []
    for href in stylesheet_urls(html, url, fetched_url=fetched_url)[:MAX_STYLESHEETS]:
        text = fetcher.fetch_text(href, max_bytes=MAX_STYLESHEET_BYTES)
        if text:
            texts.append(text)
    return "\n".join(texts)


@dataclass
class PageImageResult:
    """One image found on a scanned page, and what became of it."""

    src: str
    current_alt: str
    kind: str                 # "img" | "background"
    region: str = ""          # "" | "header" | "footer" -- see extract._region_of
    outcome: AltTextOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "currentAlt": self.current_alt,
            "kind": self.kind,
            "region": self.region,
            **({"outcome": self.outcome.to_dict()} if self.outcome else {}),
        }


def scan_page(url: str, fetcher: Fetcher, generator: AltTextGenerator, *,
              max_images: int = DEFAULT_MAX_PAGE_IMAGES,
              include_header: bool = False,
              include_footer: bool = False,
              ) -> tuple[PageContent, list[PageImageResult]]:
    """Fetch a page, and describe every image found on it -- comprehensively.

    Two things this deliberately does *not* do, because both were measured
    to hide real images on a real page:

    * It does not scope to the main content region. `extract_all_images`
      walks the whole document, so a header logo, a footer icon and a nav
      background are all covered -- a scan is an audit of the page, not a
      diff, and none of those need to be excluded the way they would for
      comparing two versions of the same page.
    * It does not treat "this is a CSS background" as "this is decorative".
      That used to skip every background image on sight -- including, on a
      real page, an actual hero banner whose only static-HTML trace was a
      <noscript> fallback `extract_all_images` now reads. Whether an image is
      decorative is exactly the judgment call `AltTextSuggestion.is_decorative`
      asks the model to make by actually looking at it; a markup-kind
      shortcut answers a different, cheaper question and answered it wrong
      here.

    `max_images` caps only the images actually sent for description -- the
    ones beyond the cap still appear in the result, marked with why they were
    skipped, so a large page reads as "here's what we covered and what's
    left" rather than silently truncating.

    A third pattern -- no <img>, no inline style, no data-* attribute, just a
    class or ID naming a background rule -- can live in either the page's own
    <style> block or a stylesheet it links to. `extract_all_images` reads the
    embedded case on its own; this fetches every linked stylesheet first
    (bounded by MAX_STYLESHEETS/MAX_STYLESHEET_BYTES) so the external case is
    covered too, before anything is scanned for images at all.

    `include_header`/`include_footer` default to False: a site's masthead
    logo and its footer's social-icon row are real images with their own alt
    text, but they are also the same dozen icons on every page of the site,
    so a reviewer auditing page content almost always wants them left out
    unless asked for. Filtered before any image is downloaded or described,
    so leaving both off also means neither costs a vision call.
    """
    result = fetcher.fetch(url, source="auto")
    if not result.ok:
        raise RuntimeError(
            f"could not fetch {url} (status {result.status}); "
            "check the URL is reachable")
    page = extract_fetch_result(result)
    extra_css = _external_css(result.html, url, result.fetched_url, fetcher)
    images = extract_all_images(result.html, url, fetched_url=result.fetched_url,
                                extra_css=extra_css)
    images = [
        image for image in images
        if (image.region != "header" or include_header)
        and (image.region != "footer" or include_footer)
    ]

    out: list[PageImageResult] = []
    calls_made = 0
    for image in images:
        if calls_made >= max_images:
            out.append(PageImageResult(
                src=image.src, current_alt=image.alt or "", kind=image.kind,
                region=image.region,
                outcome=AltTextOutcome(
                    skipped_reason=f"page image cap reached ({max_images}); "
                                  "raise it to cover the rest")))
            continue

        downloaded = fetcher.fetch_binary(image.src)
        if downloaded is None:
            out.append(PageImageResult(
                src=image.src, current_alt=image.alt or "", kind=image.kind,
                region=image.region,
                outcome=AltTextOutcome(skipped_reason="could not download this image")))
            continue

        image_bytes, media_type = downloaded
        context = f"This image is on the page titled {page.title!r}." if page.title else ""
        outcome = generator.generate(image_bytes, media_type, context=context)
        calls_made += 1
        out.append(PageImageResult(
            src=image.src, current_alt=image.alt or "", kind=image.kind,
            region=image.region, outcome=outcome))

    return page, out


# --------------------------------------------------------------------------
# describing a batch of directly-supplied images
# --------------------------------------------------------------------------

# The dashboard's Image Scan panel lets someone paste up to 20 images from
# the clipboard or pick up to 50 files at once; either way they land here as
# one batch under one shared Budget, the same "cap it but still list what
# didn't make it" shape scan_page uses for a page with more images than its
# own cap. 50 is the ceiling regardless of which of the two entry points
# supplied them.
MAX_BATCH_IMAGES = 50


@dataclass
class BatchImageResult:
    """One image handed to the batch endpoint directly (no page, no src URL
    to point back to) -- just a caller-supplied name and what became of it."""

    name: str
    outcome: AltTextOutcome

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "outcome": self.outcome.to_dict()}


def generate_batch(images: list[tuple[str, bytes, str]], generator: AltTextGenerator, *,
                   max_images: int = MAX_BATCH_IMAGES) -> list[BatchImageResult]:
    """Describe a batch of independently supplied images, in order.

    `images` is `(name, image_bytes, media_type)` per item -- `generate`
    already validates type/size/emptiness per image, so this is just the
    loop and the cap, mirroring `scan_page`'s without a page to fetch.
    """
    out: list[BatchImageResult] = []
    for i, (name, image_bytes, media_type) in enumerate(images):
        if i >= max_images:
            out.append(BatchImageResult(
                name=name,
                outcome=AltTextOutcome(
                    skipped_reason=f"batch cap reached ({max_images}); "
                                  "raise it to cover the rest")))
            continue
        out.append(BatchImageResult(
            name=name, outcome=generator.generate(image_bytes, media_type)))
    return out
