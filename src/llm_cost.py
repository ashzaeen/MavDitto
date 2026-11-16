"""What every LLM-calling feature in this pipeline shares: pricing, a hard
spend cap checked before each call, and turning an SDK's exceptions into
something a reviewer can act on.

Split out of `llm_judge.py` (the first feature to need it) once a second one
-- `alt_text.py` -- needed the same thing. Neither module is a specialization
of the other; both depend on this. `llm_provider.py` added Gemini support
later, reusing this same Budget rather than a second cost-tracking system.
"""

from __future__ import annotations

from dataclasses import dataclass

# USD per million tokens, for the budget estimate. Update alongside the model
# list; a stale price makes the cap wrong in the dangerous direction.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-haiku": (0.25, 1.25),
    # Gemini models newer than this codebase's knowledge cutoff -- confirmed
    # to exist and work via a live models.list() call and a real generation
    # call, but their per-token price is NOT independently confirmed here.
    # Deliberately set higher than Gemini's historically published rates for
    # the nearest prior generation, so the budget cap errs toward stopping a
    # run early rather than under-charging it -- verify against
    # https://ai.google.dev/pricing before relying on this for real spend.
    "gemini-3.1-pro-preview": (2.50, 15.00),
    "gemini-3.8-flash": (0.50, 4.00),
    # Used as MODELS["gemini"]["high"/"fast"] -- confirmed live 2026-09-30
    # after "gemini-3.1-flash" (this tier's previous id) came back 404
    # NOT_FOUND, retired from the API sometime after this file's March 2026
    # verification. flash-lite is confirmed live and priced below.
    "gemini-3.1-flash-lite": (0.10, 0.40),
    # OpenAI models newer than this codebase's knowledge cutoff -- same
    # situation as the Gemini entries above: confirmed live to exist and
    # work (a real models.list() call plus real structured-output and
    # vision calls), but pricing is NOT independently confirmed. Set high
    # for the same reason -- verify against https://openai.com/api/pricing
    # before relying on this for real spend.
    "gpt-5.5-pro": (20.00, 80.00),
    "gpt-5.4-mini": (0.50, 4.00),
    "gpt-4o-mini": (0.15, 0.60),
}


class BudgetExceeded(RuntimeError):
    """Raised when a call would cost more than the run is allowed to spend."""


class CredentialsMissing(RuntimeError):
    """Raised when no Anthropic credentials can be resolved."""


def is_credentials_error(exc: BaseException) -> bool:
    """Recognize the SDK's missing-credentials failure.

    It surfaces as a plain TypeError on the first request -- not at client
    construction, and not as AuthenticationError -- so without this check a
    reviewer sees a raw traceback string where an instruction should be.
    """
    return (isinstance(exc, TypeError)
            and "could not resolve authentication" in str(exc).lower())


NO_CREDENTIALS_MESSAGE = (
    "No Anthropic credentials found. Set ANTHROPIC_API_KEY in the environment "
    "the server runs in, or run `ant auth login` once to store a profile the "
    "SDK picks up automatically. Nothing else in the pipeline needs them."
)


@dataclass
class Budget:
    """A hard cap on what one run may spend.

    Checked before each call rather than after, so the limit is never
    discovered by exceeding it. The input estimate comes from the API's own
    token counter; output is assumed to be the full ceiling, which
    deliberately over-estimates -- a budget that only holds on average is not
    a budget.
    """

    max_usd: float = 1.00
    max_calls: int = 50
    spent_usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    skipped: int = 0

    def price(self, model: str) -> tuple[float, float]:
        if model not in PRICING:
            raise BudgetExceeded(
                f"no price on file for {model!r}, so its spend cannot be capped; "
                f"add it to PRICING or pick one of {', '.join(sorted(PRICING))}"
            )
        return PRICING[model]

    def estimate(self, model: str, input_tokens: int,
                 output_tokens: int = 8000) -> float:
        in_rate, out_rate = self.price(model)
        return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

    def check(self, model: str, input_tokens: int, *,
             output_tokens: int = 8000) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"call cap reached ({self.max_calls}); {self.skipped + 1} item(s) "
                "left unprocessed")
        worst_case = self.estimate(model, input_tokens, output_tokens)
        if self.spent_usd + worst_case > self.max_usd:
            raise BudgetExceeded(
                f"next call could cost ${worst_case:.4f}, which would pass the "
                f"${self.max_usd:.2f} cap (spent ${self.spent_usd:.4f} so far)")

    def record(self, model: str, usage) -> float:
        """Charge actual usage against the budget; returns this call's cost."""
        in_rate, out_rate = self.price(model)
        billed_in = (getattr(usage, "input_tokens", 0)
                     + getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        # Cache reads bill at roughly a tenth of the input rate.
        cost = (billed_in * in_rate + cached * in_rate * 0.1
                + out * out_rate) / 1_000_000
        self.spent_usd += cost
        self.calls += 1
        self.input_tokens += billed_in + cached
        self.output_tokens += out
        return cost

    def summary(self, *, noun: str = "call") -> str:
        return (f"{self.calls} {noun}(s), {self.input_tokens:,} in / "
                f"{self.output_tokens:,} out, ${self.spent_usd:.4f} of "
                f"${self.max_usd:.2f}"
                + (f", {self.skipped} item(s) skipped" if self.skipped else ""))


def explain_api_failure(exc: Exception, *, label: str = "call") -> str:
    """Turn an SDK exception into something a reviewer can act on."""
    if isinstance(exc, CredentialsMissing):
        return str(exc)
    if is_credentials_error(exc):
        return NO_CREDENTIALS_MESSAGE

    try:
        import anthropic
    except ImportError:
        return f"{label} unavailable: {exc}"

    if isinstance(exc, anthropic.AuthenticationError):
        return ("no valid Anthropic credentials; set ANTHROPIC_API_KEY or run "
                "`ant auth login`")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "these credentials are not allowed to call this model"
    if isinstance(exc, anthropic.NotFoundError):
        return "the model name was rejected; check which model this is configured to use"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate limited by the API; try again with a smaller batch"
    if isinstance(exc, anthropic.APIConnectionError):
        return "could not reach the API; check the network"
    if isinstance(exc, anthropic.APIStatusError):
        return f"API error {exc.status_code}: {exc.message}"
    return f"{label} failed: {type(exc).__name__}: {exc}"
