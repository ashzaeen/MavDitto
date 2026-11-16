"""Single entry point for all structured LLM calls across the codebase.

Reads `data/llm_config.json` via `llm_config.py` to honor the user's active
setting (Claude, Gemini or OpenAI), so every feature that calls an LLM --
Content Writer, Web Builder, Alt Text Generator, LLM Judge -- automatically
uses whichever provider is active without per-feature plumbing.

SDK clients (`anthropic`/`google-genai`/`openai`) are imported lazily inside
their respective call branches, keeping test suites light and isolating
dependencies so a deployment that only uses one provider doesn't fail at
import time on the others.

Every non-Claude model name below was confirmed live (a real `models.list()`
or equivalent call against the vendor's API in March 2026); no hallucinated
model names allowed.
"""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from .llm_cost import (
    Budget, CredentialsMissing, NO_CREDENTIALS_MESSAGE, explain_api_failure,
    is_credentials_error,
)

T = TypeVar("T", bound=BaseModel)

# Default models per provider, split into "high" (reasoning, rewrite quality,
# complex decisions), "medium" (judgment-heavy but still cost-sensitive --
# Web Builder's plan + populate calls, where the user directly judges output
# quality), and "fast" (extraction, alt text, classification). "high" and
# "fast" intentionally resolve to the same cheapest model per provider today
# -- "medium" is the one real step up, chosen to stay in the same rough
# price band across providers (~$0.5-1 / $4-5 per M tokens) rather than
# jumping to a premium tier.
MODELS: dict[str, dict[str, str]] = {
    "claude": {
        "high": "claude-haiku-4-5",
        "medium": "claude-haiku-4-5",
        "fast": "claude-haiku-4-5",
    },
    "openai": {
        "high": "gpt-4o-mini",
        "medium": "gpt-5.4-mini",
        "fast": "gpt-4o-mini",
    },
    "gemini": {
        "high": "gemini-3.1-flash-lite",
        "medium": "gemini-3.8-flash",
        "fast": "gemini-3.1-flash-lite",
    },
}

# Every model a writer can pick explicitly, per provider, ordered weakest ->
# strongest. Separate from `MODELS` above on purpose: `MODELS`'s "high" tier
# is deliberately the cheapest model in each lineup (used by Alt Text, LLM
# Judge, Web Builder, extraction, where that tradeoff is fine) and changing
# its meaning there would silently raise cost across features nobody asked
# to upgrade. This catalog is what backs Content Writer's own model picker.
#
# Every id here must have a `llm_cost.PRICING` entry, or the very first real
# call raises BudgetExceeded ("no price on file for ...") -- confirmed the
# hard way while wiring this up. Stick to ids `PRICING` already carries
# (each already independently confirmed live there, per its own comments)
# rather than adding new ones here on the strength of a web search alone.
#
# `"default": True` marks the entry Content Writer actually falls back to
# when the writer hasn't picked one (see `recommended_model`/`resolve_model`)
# -- deliberately NOT the strongest entry. The top tier (gpt-5.5-pro etc.) is
# a real reasoning model: confirmed live to run into stricter per-minute
# rate limits, $0.50-1.70+ per call, and multi-minute latency even at
# "medium" reasoning effort, which makes it a bad *default* for every
# generate/refine/regenerate/review call even though it's a good *choice*
# for a writer who explicitly wants to spend more on one important page.
MODEL_CATALOG: dict[str, list[dict[str, str]]] = {
    "claude": [
        {"id": "claude-3-haiku-20240307", "label": "Claude 3 Haiku"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "default": True},
        {"id": "claude-opus-5", "label": "Claude Opus 5"},
    ],
    "openai": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
        {"id": "gpt-5.4-mini", "label": "GPT-5.4 mini", "default": True},
        {"id": "gpt-5.5-pro", "label": "GPT-5.5 Pro"},
    ],
    "gemini": [
        {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
        {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash", "default": True},
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro"},
    ],
}

PROVIDER_LABELS = {"claude": "Claude", "openai": "OpenAI", "gemini": "Gemini"}

# The Gemini SDK surfaces transient resource exhaustion (503 / UNAVAILABLE /
# "The model is overloaded. Please try again later.") on bursty calls. The
# retry is safe to apply universally because all calls through here are
# idempotent (pure read / generate; no side effects until the caller acts on
# the structured result). Other errors (400 bad request, 403 auth, 404 model
# not found) raise immediately -- retrying those is pure waste. A 503 is
# genuinely transient and usually resolves within a couple of seconds (the
# own error text says so), so worth one short retry before surfacing it as a
# failure. A 429 (quota/rate limit) is deliberately NOT covered here: it is
# not transient in the same sense, and the API's own suggested retry delay
# (tens of seconds) is too long for a synchronous request to just sleep through.
_GEMINI_MAX_ATTEMPTS = 3
_GEMINI_RETRY_DELAY_SECONDS = 2.0

# The google-genai SDK's own default is no timeout at all -- a stalled
# connection to Gemini (as opposed to a clean error) would otherwise hang
# the whole synchronous request forever, with nothing for a caller (a page
# scan covering dozens of images, in one HTTP response) to show or retry.
# 60s comfortably covers a real vision + structured-output call.
_GEMINI_TIMEOUT_MS = 60_000


def _has_creds(cfg: dict[str, Any], p: str) -> bool:
    if p == "claude":
        return bool(cfg.get("claude_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if p == "openai":
        return bool(cfg.get("openai_api_key", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip())
    if p == "gemini":
        return bool(cfg.get("gemini_api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip())
    return False


def active_provider() -> str:
    from . import llm_config
    cfg = llm_config.load_config()
    provider = cfg.get("active_provider", "claude").strip().lower()

    if provider in ("claude", "openai", "gemini") and _has_creds(cfg, provider):
        return provider

    # Fallback to whichever provider is actually configured
    for candidate in ("openai", "gemini", "claude"):
        if _has_creds(cfg, candidate):
            return candidate

    return provider if provider in ("claude", "openai", "gemini") else "claude"


def configured_providers() -> list[str]:
    """Every provider with credentials saved, in a stable display order --
    used to scope Content Writer's model picker to providers the writer can
    actually call, rather than listing all three regardless of setup."""
    from . import llm_config
    cfg = llm_config.load_config()
    return [p for p in ("claude", "openai", "gemini") if _has_creds(cfg, p)]


def strongest_model(provider: str) -> str:
    """The top of that provider's catalog -- not the default (see
    `recommended_model`); this is for a writer explicitly opting into the
    most capable tier for one request."""
    catalog = MODEL_CATALOG.get(provider) or []
    if catalog:
        return catalog[-1]["id"]
    return MODELS.get(provider, MODELS["claude"])["high"]


def recommended_model(provider: str) -> str:
    """The catalog entry marked `"default": True` -- Content Writer's actual
    fallback when the writer hasn't picked a model. A solid middle tier, not
    the strongest one: see MODEL_CATALOG's module comment for why."""
    catalog = MODEL_CATALOG.get(provider) or []
    for m in catalog:
        if m.get("default"):
            return m["id"]
    return strongest_model(provider)


def resolve_model(explicit: str, provider: str | None = None) -> str:
    """`explicit` if it's a real model of the (given or active) provider's
    catalog, else that provider's recommended default. Falling back rather
    than raising covers the case where a saved setting names a model from a
    provider that was active when it was picked but isn't anymore."""
    provider = provider or active_provider()
    valid_ids = {m["id"] for m in MODEL_CATALOG.get(provider, [])}
    if explicit and explicit in valid_ids:
        return explicit
    return recommended_model(provider)


def default_model(tier: str = "high") -> str:
    provider = active_provider()
    return MODELS.get(provider, MODELS["claude"])[tier]


def provider_for_model(model: str) -> str:
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    return "claude"


def call_structured(
    model: str, system: str, prompt: str, output_format: type[T], budget: Budget, *,
    image: tuple[bytes, str] | None = None, max_output_tokens: int = 4096,
    effort: str = "high", client=None, label: str = "call",
) -> tuple[T, float]:
    """One user turn (optionally with an image) -> a validated instance of
    `output_format`, plus this call's cost.

    `client` is injectable for tests (an Anthropic-shaped stub for a
    "claude*" model, a Gemini-shaped stub for a "gemini*" one); production
    callers leave it None.

    Budget is checked BEFORE making the call (using a token count probe on
    Claude, an estimate on Gemini) and recorded AFTER with actual usage.

    Raises `CredentialsMissing` on missing credentials, `BudgetExceeded` if
    the call would blow the cap, and `RuntimeError` on any other failure;
    a Claude failure reads as double-nested.
    """
    provider = provider_for_model(model)
    if provider == "gemini":
        return _call_gemini(
            model, system, prompt, output_format, budget,
            image=image, max_output_tokens=max_output_tokens, client=client,
            label=label, effort=effort,
        )
    if provider == "openai":
        return _call_openai(
            model, system, prompt, output_format, budget,
            image=image, max_output_tokens=max_output_tokens, effort=effort,
            client=client, label=label,
        )
    return _call_claude(
        model, system, prompt, output_format, budget,
        image=image, max_output_tokens=max_output_tokens, effort=effort,
        client=client, label=label,
    )


# --------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------

def _claude_content(prompt: str, image: tuple[bytes, str] | None):
    if image is None:
        return prompt
    import base64
    img_bytes, media_type = image
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": prompt},
    ]


def _call_claude(model, system, prompt, output_format, budget, *,
                 image, max_output_tokens, effort, client, label="call"):
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "the anthropic package is not installed; check requirements.txt") from exc
        from . import llm_config
        key = llm_config.load_config().get("claude_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    content = _claude_content(prompt, image)
    messages = [{"role": "user", "content": content}]
    try:
        input_tokens = int(client.messages.count_tokens(
            model=model, system=system, messages=messages).input_tokens)
    except Exception as exc:
        if is_credentials_error(exc):
            raise CredentialsMissing(NO_CREDENTIALS_MESSAGE) from exc
        input_tokens = len(system) // 3 + len(prompt) // 3

    budget.check(model, input_tokens, output_tokens=max_output_tokens)

    parse_kwargs = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "output_format": output_format,
    }
    if "haiku" not in model.lower() and "claude-3-sonnet" not in model.lower() and "claude-3-opus" not in model.lower():
        parse_kwargs["thinking"] = {"type": "adaptive"}
        parse_kwargs["output_config"] = {"effort": effort}

    try:
        response = client.messages.parse(**parse_kwargs)
    except Exception as exc:
        raise RuntimeError(explain_api_failure(exc, label=label)) from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("the model declined to respond")

    cost = budget.record(model, response.usage)
    return response.parsed_output, cost


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

def _gemini_content(prompt: str, image: tuple[bytes, str] | None):
    if image is None:
        return prompt
    from google.genai import types
    img_bytes, media_type = image
    return [types.Part.from_bytes(data=img_bytes, mime_type=media_type), prompt]


def _gemini_client(key: str):
    from google import genai
    from google.genai import types
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=_GEMINI_TIMEOUT_MS))


class _GeminiUsage:
    """Adapts a google-genai `GenerateContentResponseUsageMetadata` to the
    shape `Budget.record()` already knows how to bill against -- Gemini's
    "thoughts" tokens are billed as output, the same way Claude's thinking
    tokens are."""

    def __init__(self, usage):
        self.input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        candidate = getattr(usage, "candidates_token_count", 0) or 0
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0
        self.output_tokens = candidate + thoughts
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = (
            getattr(usage, "cached_content_token_count", 0) or 0)


def _call_gemini(model, system, prompt, output_format, budget, *,
                 image, max_output_tokens, client, label="call", effort="high"):
    if client is None:
        from . import llm_config
        key = llm_config.load_config().get("gemini_api_key", "").strip()
        if not key:
            raise CredentialsMissing(
                "No Gemini credentials found. Save a Gemini API key in Settings, "
                "or set GEMINI_API_KEY in the environment the server runs in.")
        client = _gemini_client(key)

    from google.genai import types

    # Pessimistic character-based input token estimate -- Gemini's SDK has
    # a count_tokens method, but calling it adds a full network roundtrip
    # before every single generation turn. 1 token ~ 3 characters of English
    # text is conservative enough to prevent accidental overspends.
    estimated_input_tokens = (len(system) + len(prompt)) // 3
    if image is not None:
        estimated_input_tokens += 1000
    budget.check(model, estimated_input_tokens, output_tokens=max_output_tokens)

    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=output_format,
        max_output_tokens=max_output_tokens,
    )
    last_exc = None
    for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=_gemini_content(prompt, image),
                config=config,
            )
            last_exc = None
            break
        except Exception as exc:
            msg = str(exc)
            if "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
                raise CredentialsMissing(
                    "Gemini rejected the configured API key. Check it in Settings.") from exc
            is_overloaded = "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower()
            if is_overloaded and attempt < _GEMINI_MAX_ATTEMPTS:
                time.sleep(_GEMINI_RETRY_DELAY_SECONDS * attempt)
                continue
            last_exc = exc
            break

    if last_exc is not None:
        raise RuntimeError(f"Gemini request failed: {last_exc}") from last_exc

    if response.parsed is None:
        raise RuntimeError("the model declined to respond")

    cost = budget.record(model, _GeminiUsage(response.usage_metadata))
    return response.parsed, cost


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------

def _openai_input(prompt: str, image: tuple[bytes, str] | None):
    if image is None:
        return prompt
    import base64
    img_bytes, media_type = image
    b64 = base64.b64encode(img_bytes).decode("ascii")
    data_uri = f"data:{media_type};base64,{b64}"
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_uri},
            ],
        }
    ]


class _OpenAIUsage:
    """Adapts a Responses API `ResponseUsage` to the shape `Budget.record()`
    already knows how to bill against -- reasoning tokens bill as output,
    the same way Claude's thinking and Gemini's thoughts tokens already do."""

    def __init__(self, usage):
        self.input_tokens = getattr(usage, "input_tokens", 0) or 0
        self.output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.cache_creation_input_tokens = 0
        details = getattr(usage, "input_tokens_details", None)
        self.cache_read_input_tokens = getattr(details, "cached_tokens", 0) or 0 if details else 0


def _openai_client(key: str):
    from openai import OpenAI
    return OpenAI(api_key=key)


def _call_openai(model, system, prompt, output_format, budget, *,
                 image, max_output_tokens, effort, client, label="call"):
    if client is None:
        from . import llm_config
        key = llm_config.load_config().get("openai_api_key", "").strip()
        if not key:
            raise CredentialsMissing(
                "No OpenAI credentials found. Save an OpenAI API key in Settings, "
                "or set OPENAI_API_KEY in the environment the server runs in.")
        client = _openai_client(key)

    import openai

    input_value = _openai_input(prompt, image)
    try:
        input_tokens = int(client.responses.input_tokens.count(
            model=model, instructions=system, input=input_value).input_tokens)
    except openai.AuthenticationError as exc:
        raise CredentialsMissing(
            "OpenAI rejected the configured API key. Check it in Settings.") from exc
    except Exception:
        input_tokens = len(system) // 3 + len(prompt) // 3

    # A reasoning model's thinking tokens are billed from the same
    # max_output_tokens ceiling as its visible completion -- on "high"/
    # "xhigh" effort they can consume the whole budget before the model
    # ever emits the structured output, which comes back as
    # `output_parsed is None` ("the model declined to respond") with no
    # actual refusal involved. Confirmed live: a compose-page call against
    # gpt-5.5-pro at the old flat ceiling. Give reasoning models extra
    # headroom, scaled to effort, on top of whatever the caller asked for
    # the visible output -- and do it before budget.check so the estimate
    # matches what's actually sent.
    is_reasoning_model = not model.startswith("gpt-4") and any(
        model.startswith(p) for p in ("o1", "o3", "o4", "gpt-5"))
    resolved_effort = effort
    if is_reasoning_model and model.startswith("gpt-5.5") and effort not in ("medium", "high", "xhigh"):
        resolved_effort = "medium"
    if is_reasoning_model:
        headroom = {"xhigh": 16384, "high": 12288, "medium": 6144}.get(resolved_effort, 4096)
        max_output_tokens = max_output_tokens + headroom

    budget.check(model, input_tokens, output_tokens=max_output_tokens)

    parse_kwargs = {
        "model": model,
        "instructions": system,
        "input": input_value,
        "text_format": output_format,
        "max_output_tokens": max_output_tokens,
    }
    if is_reasoning_model:
        parse_kwargs["reasoning"] = {"effort": resolved_effort}

    try:
        response = client.responses.parse(**parse_kwargs)
    except openai.AuthenticationError as exc:
        raise CredentialsMissing(
            "OpenAI rejected the configured API key. Check it in Settings.") from exc
    except openai.PermissionDeniedError as exc:
        raise RuntimeError(f"{label} failed: these credentials are not allowed to call this model") from exc
    except openai.NotFoundError as exc:
        raise RuntimeError(f"{label} failed: the model name was rejected: {exc}") from exc
    except openai.RateLimitError as exc:
        raise RuntimeError(f"{label} failed: rate limited by the API; try again with a smaller batch") from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(f"{label} failed: could not reach the API; check the network") from exc
    except openai.APIStatusError as exc:
        raise RuntimeError(f"{label} failed: API error {exc.status_code}: {exc.message}") from exc
    except Exception as exc:
        raise RuntimeError(f"{label} failed: {type(exc).__name__}: {exc}") from exc

    if response.output_parsed is None:
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        status = getattr(response, "status", None)
        if reason == "max_output_tokens" or status == "incomplete":
            raise RuntimeError(
                f"{label} failed: {model} ran out of its output budget before finishing "
                "(reasoning effort can consume this on a complex request) -- try again, "
                "or pick a lower-effort/non-reasoning model for this request")
        if reason == "content_filter":
            raise RuntimeError(f"{label} failed: {model} refused the request (content filter)")
        raise RuntimeError(f"{label} failed: {model} returned no parseable output"
                           + (f" (status={status!r}, reason={reason!r})" if status or reason else ""))

    cost = budget.record(model, _OpenAIUsage(response.usage))
    return response.output_parsed, cost
