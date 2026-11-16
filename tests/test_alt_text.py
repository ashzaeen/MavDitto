"""Alt text tests, run against a stub client -- the same approach as
test_llm_judge.py: no network, no credentials, a fake that mimics the SDK's
shapes (`messages.parse` -> `.parsed_output`/`.usage`/`.stop_reason`,
`messages.count_tokens` -> `.input_tokens`). What this cannot cover is
whether the real model writes good alt text -- that needs credentials and a
live call.
"""

import json
from types import SimpleNamespace

import pytest

from src.alt_text import (
    AltTextCache, AltTextGenerator, AltTextSuggestion, BatchImageResult,
    PageImageResult, SUPPORTED_MEDIA_TYPES, generate_batch, scan_page,
)
from src.llm_cost import NO_CREDENTIALS_MESSAGE, Budget
from src.models import FetchResult, Image

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake but nonempty png data"


def _usage(input_tokens=800, output_tokens=60, cached=0):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0,
                           cache_read_input_tokens=cached)


class StubClient:
    """Mimics the SDK surface the generator touches."""

    def __init__(self, suggestion=None, raises=None, input_tokens=800):
        self.suggestion = suggestion or AltTextSuggestion(
            is_decorative=False, alt_text="A student walks past the library at dusk.",
            rationale="Describes the visible subject and setting.")
        self.raises = raises
        self.input_tokens = input_tokens
        self.calls = 0
        self.last_kwargs = None
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kwargs):
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(input_tokens=self.input_tokens)

    def _parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(parsed_output=self.suggestion, usage=_usage(),
                               stop_reason="end_turn")


def _generator(tmp_path, client=None, **kw) -> AltTextGenerator:
    kw.setdefault("model", "claude-opus-5")
    # A real config/brand-voice.json exists in this repo (it's UTA's own,
    # pre-committed) -- default every test to a path that isn't there, so
    # ordinary tests aren't silently coupled to that file's content. Tests
    # about the UTA framing itself pass their own brand_voice_path.
    kw.setdefault("brand_voice_path", tmp_path / "no-brand-voice-here.json")
    gen = AltTextGenerator(cache=AltTextCache(tmp_path / "cache"), **kw)
    gen._client = client if client is not None else StubClient()
    return gen


# --- input validation, before anything costs a call ------------------------

def test_an_unsupported_image_type_is_rejected_without_a_call(tmp_path):
    client = StubClient()
    outcome = _generator(tmp_path, client).generate(b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "image/svg+xml")
    assert not outcome.generated
    assert "unsupported" in outcome.skipped_reason
    assert client.calls == 0


def test_an_oversized_image_is_rejected_without_a_call(tmp_path):
    from src.alt_text import MAX_IMAGE_BYTES

    client = StubClient()
    huge = b"x" * (MAX_IMAGE_BYTES + 1)
    outcome = _generator(tmp_path, client).generate(huge, "image/png")
    assert not outcome.generated
    assert "MB cap" in outcome.skipped_reason
    assert client.calls == 0


def test_empty_image_data_is_rejected(tmp_path):
    client = StubClient()
    outcome = _generator(tmp_path, client).generate(b"", "image/png")
    assert not outcome.generated
    assert client.calls == 0


def test_every_supported_type_is_accepted():
    assert SUPPORTED_MEDIA_TYPES == {"image/jpeg", "image/png", "image/gif", "image/webp"}


# --- the call itself ---------------------------------------------------------

def test_a_generated_result_carries_the_alt_text(tmp_path):
    outcome = _generator(tmp_path).generate(PNG_BYTES, "image/png")
    assert outcome.generated
    assert outcome.alt_text == "A student walks past the library at dusk."
    assert outcome.is_decorative is False
    assert outcome.cost_usd > 0


def test_a_decorative_image_carries_no_alt_text_even_if_the_model_wrote_one(tmp_path):
    """is_decorative wins -- an empty alt attribute is the correct output for a
    decorative image regardless of what text the model drafted alongside it."""
    suggestion = AltTextSuggestion(
        is_decorative=True, alt_text="A faint geometric pattern.",
        rationale="Repeating background texture, no informational content.")
    outcome = _generator(tmp_path, StubClient(suggestion=suggestion)).generate(
        PNG_BYTES, "image/png")
    assert outcome.is_decorative is True
    assert outcome.alt_text == ""


def test_adaptive_thinking_is_requested(tmp_path):
    client = StubClient()
    _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    assert client.last_kwargs["thinking"] == {"type": "adaptive"}


def test_the_system_prompt_is_cached_on_the_request(tmp_path):
    client = StubClient()
    _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    system = client.last_kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_the_image_is_sent_as_a_base64_content_block(tmp_path):
    client = StubClient()
    _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    content = client.last_kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"


def test_a_refusal_is_reported_not_treated_as_a_description(tmp_path):
    client = StubClient()
    client._parse = lambda **kw: SimpleNamespace(
        parsed_output=None, usage=_usage(), stop_reason="refusal")
    client.messages = SimpleNamespace(parse=client._parse, count_tokens=client._count)
    outcome = _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    assert not outcome.generated and "declined" in outcome.skipped_reason


def test_a_schema_valid_but_empty_result_is_retried_once(tmp_path):
    """A cheap model can return a well-formed but useless response (a
    non-decorative image with blank alt text) -- confirmed live against
    Gemini's flash-lite. One retry is cheap insurance against that."""
    empty = AltTextSuggestion(is_decorative=False, alt_text="", rationale="")
    good = AltTextSuggestion(is_decorative=False, alt_text="A clear description.",
                            rationale="Describes the image.")
    client = StubClient()
    responses = [empty, good]

    def _parse(**kw):
        client.calls += 1
        return SimpleNamespace(parsed_output=responses.pop(0), usage=_usage(), stop_reason="end_turn")

    client._parse = _parse
    client.messages = SimpleNamespace(parse=client._parse, count_tokens=client._count)
    outcome = _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    assert client.calls == 2
    assert outcome.generated and outcome.alt_text == "A clear description."
    assert outcome.cost_usd > 0


def test_two_empty_results_in_a_row_are_reported_not_cached(tmp_path):
    empty = AltTextSuggestion(is_decorative=False, alt_text="", rationale="")
    client = StubClient(suggestion=empty)
    gen = _generator(tmp_path, client)
    outcome = gen.generate(PNG_BYTES, "image/png")
    assert client.calls == 2
    assert not outcome.generated
    assert "empty" in outcome.skipped_reason
    # Not cached: a second call still tries the model rather than replaying
    # the useless result forever.
    outcome2 = gen.generate(PNG_BYTES, "image/png")
    assert client.calls == 4


# --- budget -------------------------------------------------------------

def test_budget_refuses_a_call_it_cannot_afford(tmp_path):
    gen = _generator(tmp_path, budget=Budget(max_usd=0.0000001))
    outcome = gen.generate(PNG_BYTES, "image/png")
    assert not outcome.generated
    assert "cap" in outcome.skipped_reason
    assert gen.budget.skipped == 1


def test_call_cap_stops_the_scan(tmp_path):
    gen = _generator(tmp_path, budget=Budget(max_calls=1, max_usd=100))
    first = gen.generate(PNG_BYTES, "image/png")
    second = gen.generate(PNG_BYTES + b"more", "image/png")
    assert first.generated
    assert not second.generated
    assert "call cap" in second.skipped_reason


def test_spend_is_recorded_from_actual_usage(tmp_path):
    gen = _generator(tmp_path)
    outcome = gen.generate(PNG_BYTES, "image/png")
    assert outcome.cost_usd > 0
    assert gen.budget.spent_usd == pytest.approx(outcome.cost_usd)


# --- caching -----------------------------------------------------------

def test_the_same_image_is_not_described_twice(tmp_path):
    client = StubClient()
    gen = _generator(tmp_path, client)
    first = gen.generate(PNG_BYTES, "image/png")
    second = gen.generate(PNG_BYTES, "image/png")
    assert client.calls == 1
    assert second.cached and second.cost_usd == 0
    assert second.alt_text == first.alt_text


def test_a_different_image_is_described_again(tmp_path):
    client = StubClient()
    gen = _generator(tmp_path, client)
    gen.generate(PNG_BYTES, "image/png")
    gen.generate(PNG_BYTES + b"different", "image/png")
    assert client.calls == 2


def test_the_same_bytes_with_different_context_are_described_again(tmp_path):
    """The page title rides along as context; two pages sharing one hero image
    should not silently reuse a caption written for the other page's title."""
    client = StubClient()
    gen = _generator(tmp_path, client)
    gen.generate(PNG_BYTES, "image/png", context="Page: Admissions")
    gen.generate(PNG_BYTES, "image/png", context="Page: Athletics")
    assert client.calls == 2


# --- UTA-aware framing ---------------------------------------------------

def _write_brand_voice(tmp_path, brand: str):
    path = tmp_path / "brand-voice.json"
    path.write_text(json.dumps({"brand": brand}), encoding="utf-8")
    return path


def test_uta_framing_is_added_when_the_configured_brand_is_uta(tmp_path):
    path = _write_brand_voice(tmp_path, "UTA")
    client = StubClient()
    _generator(tmp_path, client, brand_voice_path=path).generate(PNG_BYTES, "image/png")
    system = client.last_kwargs["system"][0]["text"]
    assert "University of Texas at Arlington" in system


def test_uta_framing_is_case_insensitive_and_trims_whitespace(tmp_path):
    path = _write_brand_voice(tmp_path, "  uta  ")
    client = StubClient()
    _generator(tmp_path, client, brand_voice_path=path).generate(PNG_BYTES, "image/png")
    system = client.last_kwargs["system"][0]["text"]
    assert "University of Texas at Arlington" in system


def test_uta_framing_is_absent_for_a_different_configured_brand(tmp_path):
    path = _write_brand_voice(tmp_path, "Acme State University")
    client = StubClient()
    _generator(tmp_path, client, brand_voice_path=path).generate(PNG_BYTES, "image/png")
    system = client.last_kwargs["system"][0]["text"]
    assert "University of Texas at Arlington" not in system


def test_uta_framing_is_absent_when_no_brand_voice_file_exists(tmp_path):
    client = StubClient()
    _generator(tmp_path, client).generate(PNG_BYTES, "image/png")
    system = client.last_kwargs["system"][0]["text"]
    assert "University of Texas at Arlington" not in system


def test_a_uta_framed_result_is_cached_separately_from_a_plain_one(tmp_path):
    """Same image, same page context, but the brand-voice profile changed
    from UTA to something else in between -- the earlier cached result was
    written under a different system prompt and must not be replayed as-is."""
    client = StubClient()
    plain_gen = _generator(tmp_path, client)
    plain_gen.generate(PNG_BYTES, "image/png")

    uta_path = _write_brand_voice(tmp_path, "UTA")
    uta_gen = _generator(tmp_path, client, brand_voice_path=uta_path)
    outcome = uta_gen.generate(PNG_BYTES, "image/png")

    assert client.calls == 2
    assert not outcome.cached


# --- batch generation ------------------------------------------------------

def test_a_batch_describes_every_image_in_order(tmp_path):
    client = StubClient()
    gen = _generator(tmp_path, client)
    results = generate_batch(
        [("a.png", PNG_BYTES, "image/png"), ("b.png", PNG_BYTES + b"2", "image/png")],
        gen)
    assert [r.name for r in results] == ["a.png", "b.png"]
    assert all(r.outcome.generated for r in results)
    assert client.calls == 2


def test_a_batch_result_serializes_with_its_outcome(tmp_path):
    gen = _generator(tmp_path)
    results = generate_batch([("a.png", PNG_BYTES, "image/png")], gen)
    d = results[0].to_dict()
    assert d["name"] == "a.png"
    assert d["outcome"]["alt_text"] == "A student walks past the library at dusk."


def test_the_batch_cap_is_enforced_but_the_rest_still_appear(tmp_path):
    client = StubClient()
    gen = _generator(tmp_path, client)
    images = [(f"{i}.png", PNG_BYTES + str(i).encode(), "image/png") for i in range(3)]
    results = generate_batch(images, gen, max_images=2)

    assert len(results) == 3
    assert client.calls == 2
    capped = results[2]
    assert not capped.outcome.generated
    assert "cap reached" in capped.outcome.skipped_reason


def test_a_batch_shares_one_budget_across_every_image(tmp_path):
    gen = _generator(tmp_path, budget=Budget(max_calls=1, max_usd=100))
    images = [(f"{i}.png", PNG_BYTES + str(i).encode(), "image/png") for i in range(3)]
    results = generate_batch(images, gen)

    assert results[0].outcome.generated
    assert not results[1].outcome.generated
    assert "call cap" in results[1].outcome.skipped_reason


def test_an_unsupported_image_in_a_batch_is_reported_without_a_call(tmp_path):
    client = StubClient()
    gen = _generator(tmp_path, client)
    results = generate_batch([("a.svg", b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "image/svg+xml")], gen)
    assert not results[0].outcome.generated
    assert "unsupported" in results[0].outcome.skipped_reason
    assert client.calls == 0


# --- failure handling ----------------------------------------------------

def test_missing_credentials_produce_an_instruction_not_a_traceback(tmp_path):
    error = TypeError("Could not resolve authentication method. Expected one of "
                      "api_key, auth_token, or credentials to be set.")
    outcome = _generator(tmp_path, StubClient(raises=error)).generate(
        PNG_BYTES, "image/png")
    assert not outcome.generated
    assert outcome.skipped_reason == NO_CREDENTIALS_MESSAGE


def test_an_api_failure_leaves_the_budget_unspent(tmp_path):
    gen = _generator(tmp_path, StubClient(raises=RuntimeError("boom")))
    outcome = gen.generate(PNG_BYTES, "image/png")
    assert not outcome.generated
    assert "boom" in outcome.skipped_reason
    assert gen.budget.spent_usd == 0


# --- scanning a page -------------------------------------------------------

class StubFetcher:
    """Answers one page fetch, any number of image downloads, and any linked
    stylesheet fetches (`stylesheets`, url -> CSS text; unlisted URLs act as
    a 404 -- see fetch_text)."""

    def __init__(self, page_result: FetchResult, images: dict[str, tuple[bytes, str] | None],
                stylesheets: dict[str, str] | None = None):
        self.page_result = page_result
        self.images = images
        self.stylesheets = stylesheets or {}
        self.binary_calls: list[str] = []
        self.text_calls: list[str] = []

    def fetch(self, url, **kw):
        return self.page_result

    def fetch_binary(self, url, **kw):
        self.binary_calls.append(url)
        return self.images.get(url)

    def fetch_text(self, url, **kw):
        self.text_calls.append(url)
        return self.stylesheets.get(url)


class StubGenerator:
    """Records every image it was asked to describe, without calling out.

    Bytes named in `decorative_bytes` come back as the model judging that
    image decorative -- standing in for AltTextSuggestion.is_decorative,
    which is the only thing that should decide it now (see scan_page).
    """

    def __init__(self, decorative_bytes: set[bytes] = frozenset()):
        self.calls: list[tuple[bytes, str, str]] = []
        self.decorative_bytes = decorative_bytes

    def generate(self, image_bytes, media_type, *, context=""):
        from src.alt_text import AltTextOutcome
        self.calls.append((image_bytes, media_type, context))
        if image_bytes in self.decorative_bytes:
            return AltTextOutcome(generated=True, is_decorative=True,
                                  rationale="Repeating background texture.")
        return AltTextOutcome(generated=True, alt_text=f"described ({len(self.calls)})")


PAGE_HTML = """
<html><head><title>Campus Life</title></head><body>
<header><img src="https://e.edu/logo.png" alt="University logo"></header>
<main>
<img src="https://e.edu/photo.jpg" alt="old alt">
<div style="background-image: url('https://e.edu/bg.png')"></div>
</main>
<footer><img src="https://e.edu/social-icon.png" alt=""></footer>
</body></html>
"""


def _page_result(html=PAGE_HTML, status=200) -> FetchResult:
    return FetchResult(url="https://e.edu/campus", fetched_url="https://e.edu/campus",
                       status=status, html=html)


ALL_PAGE_IMAGES = {
    "https://e.edu/logo.png": (b"logo-bytes", "image/png"),
    "https://e.edu/photo.jpg": (b"jpg-bytes", "image/jpeg"),
    "https://e.edu/bg.png": (b"bg-bytes", "image/png"),
    "https://e.edu/social-icon.png": (b"icon-bytes", "image/png"),
}


def test_background_images_are_downloaded_and_sent_to_the_model():
    """This used to be pre-skipped by markup kind alone -- on a real page that
    silently threw away an actual hero banner. A CSS background is now judged
    by the model exactly like any other image."""
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    background = next(r for r in results if r.kind == "background")
    assert "https://e.edu/bg.png" in fetcher.binary_calls
    assert background.outcome.generated
    assert b"bg-bytes" in [c[0] for c in generator.calls]


def test_the_models_own_verdict_decides_what_is_decorative_not_the_markup_kind():
    """A real <img> can be decorative (a spacer gif) and a CSS background can
    be real content (a hero banner) -- kind was never a reliable proxy."""
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator(decorative_bytes={b"bg-bytes"})
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    background = next(r for r in results if r.kind == "background")
    photo = next(r for r in results if r.src == "https://e.edu/photo.jpg")
    assert background.outcome.is_decorative
    assert not photo.outcome.is_decorative


def test_images_outside_the_main_region_are_still_found():
    """A header logo and a footer icon are not "content" for the structural
    diff, but they are real images a screen reader still has to get through --
    scoping the scan to <main> was hiding 22 of 31 images on a real page.
    (include_header/include_footer default off -- see the dedicated tests
    for that -- so both are explicitly opted in here to isolate the region
    this test is actually about: main-region scoping, not chrome filtering.)
    """
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator,
                              include_header=True, include_footer=True)

    srcs = {r.src for r in results}
    assert "https://e.edu/logo.png" in srcs          # <header>
    assert "https://e.edu/social-icon.png" in srcs   # <footer>


def test_results_are_in_the_same_order_the_images_appear_on_the_page():
    """PAGE_HTML reads header logo -> main photo -> main background -> footer
    icon. The dashboard renders results in the order scan_page returns them,
    so that has to be page order, not "every <img> first, every background
    after" -- which used to put a background image sitting in the middle of
    the page at the end of the list instead."""
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator,
                              include_header=True, include_footer=True)

    order = [r.src.rsplit("/", 1)[-1] for r in results]
    assert order == ["logo.png", "photo.jpg", "bg.png", "social-icon.png"]


def test_header_and_footer_images_are_excluded_by_default():
    """A site's masthead logo and footer social icons repeat on every page --
    a reviewer scanning one page's content almost never wants those two
    dozen images every time."""
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    srcs = {r.src for r in results}
    assert "https://e.edu/logo.png" not in srcs
    assert "https://e.edu/social-icon.png" not in srcs
    assert "https://e.edu/photo.jpg" in srcs
    assert "https://e.edu/bg.png" in srcs


def test_header_images_are_included_when_asked_for():
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator,
                              include_header=True)

    srcs = {r.src for r in results}
    assert "https://e.edu/logo.png" in srcs
    assert "https://e.edu/social-icon.png" not in srcs


def test_footer_images_are_included_when_asked_for():
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator,
                              include_footer=True)

    srcs = {r.src for r in results}
    assert "https://e.edu/social-icon.png" in srcs
    assert "https://e.edu/logo.png" not in srcs


def test_excluded_header_and_footer_images_are_not_even_downloaded():
    """Filtering happens before the download/describe loop, so leaving both
    options off also means neither image costs a vision call."""
    fetcher = StubFetcher(_page_result(), images=ALL_PAGE_IMAGES)
    generator = StubGenerator()
    scan_page("https://e.edu/campus", fetcher, generator)

    assert "https://e.edu/logo.png" not in fetcher.binary_calls
    assert "https://e.edu/social-icon.png" not in fetcher.binary_calls


EXTERNAL_CSS_HTML = """
<html><head><title>Campus Life</title>
<link rel="stylesheet" href="https://e.edu/main.css">
</head><body><main>
<a id="highlight_block_1" class="feature-box"></a>
</main></body></html>
"""


def test_an_id_driven_background_defined_only_in_an_external_stylesheet_is_found():
    """The real UTA homepage carried a rule exactly like this -- a background
    image named only in main.min.css, invisible to a scanner that never
    fetches the page's linked stylesheets."""
    fetcher = StubFetcher(
        _page_result(EXTERNAL_CSS_HTML),
        images={"https://e.edu/tower.png": (b"tower-bytes", "image/png")},
        stylesheets={
            "https://e.edu/main.css":
                "#highlight_block_1 { background: url('/tower.png'); }",
        },
    )
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    assert "https://e.edu/main.css" in fetcher.text_calls
    assert any(r.src == "https://e.edu/tower.png" for r in results)


NOSCRIPT_ONLY_HTML = """
<html><body><main>
<div class="uta-lazy-bg hero-bg-image"></div>
<noscript><div class="uta-lazy-bg hero-bg-image"
    style="background-image: url('https://e.edu/hero.jpg')"></div></noscript>
</main></body></html>
"""


def test_an_image_whose_only_trace_is_a_noscript_fallback_is_still_found():
    """A real UTA page's hero image had no inline background-image at all on
    the live element -- only its <noscript> fallback carried the URL, which
    is exactly the accessible, no-JS path extract()'s own noise-stripping
    throws away before it is ever seen."""
    fetcher = StubFetcher(_page_result(NOSCRIPT_ONLY_HTML),
                          images={"https://e.edu/hero.jpg": (b"hero-bytes", "image/jpeg")})
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    assert any(r.src == "https://e.edu/hero.jpg" for r in results)
    assert generator.calls and generator.calls[0][0] == b"hero-bytes"


def test_a_download_failure_is_reported_not_fatal():
    html = ('<html><body><main><img src="https://e.edu/photo.jpg" alt="old alt">'
            '</main></body></html>')
    fetcher = StubFetcher(_page_result(html), images={"https://e.edu/photo.jpg": None})
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator)

    real = next(r for r in results if r.kind == "img")
    assert not real.outcome.generated
    assert "could not download" in real.outcome.skipped_reason
    assert generator.calls == []


def test_the_image_cap_is_enforced_but_the_rest_still_appear():
    html = "<html><body><main>" + "".join(
        f'<img src="https://e.edu/p{i}.jpg" alt="">' for i in range(3)
    ) + "</main></body></html>"
    fetcher = StubFetcher(_page_result(html), images={
        f"https://e.edu/p{i}.jpg": (b"bytes", "image/jpeg") for i in range(3)})
    generator = StubGenerator()
    page, results = scan_page("https://e.edu/campus", fetcher, generator, max_images=2)

    assert len(results) == 3
    assert len(generator.calls) == 2
    capped = results[2]
    assert not capped.outcome.generated
    assert "cap reached" in capped.outcome.skipped_reason


def test_an_unreachable_page_raises_rather_than_returning_an_empty_scan():
    fetcher = StubFetcher(_page_result(status=404), images={})
    with pytest.raises(RuntimeError, match="could not fetch"):
        scan_page("https://e.edu/gone", fetcher, StubGenerator())


def test_page_image_result_serializes_with_its_outcome():
    from src.alt_text import AltTextOutcome

    row = PageImageResult(src="https://e.edu/a.jpg", current_alt="", kind="img",
                          outcome=AltTextOutcome(generated=True, alt_text="x"))
    d = row.to_dict()
    assert d["src"] == "https://e.edu/a.jpg"
    assert d["outcome"]["alt_text"] == "x"


def test_the_real_type_comes_from_the_bytes_not_the_declared_label(tmp_path):
    client = StubClient()
    outcome = _generator(tmp_path, client).generate(PNG_BYTES, "image/jpeg")
    assert outcome.generated      # mislabelled JPEG/PNG is not rejected; Claude 400s on a mismatch
