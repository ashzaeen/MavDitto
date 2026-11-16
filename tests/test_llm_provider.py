import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src import llm_provider
from src.llm_cost import Budget, BudgetExceeded, CredentialsMissing


class Output(BaseModel):
    text: str


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def test_provider_for_model_recognizes_gemini_by_prefix():
    assert llm_provider.provider_for_model("gemini-3.8-flash") == "gemini"
    assert llm_provider.provider_for_model("claude-opus-5") == "claude"
    assert llm_provider.provider_for_model("gpt-5.5-pro") == "openai"


def test_default_model_follows_the_active_provider(monkeypatch):
    monkeypatch.setattr(llm_provider, "active_provider", lambda: "gemini")
    assert llm_provider.provider_for_model(llm_provider.default_model("fast")) == "gemini"

    monkeypatch.setattr(llm_provider, "active_provider", lambda: "claude")
    assert llm_provider.provider_for_model(llm_provider.default_model("fast")) == "claude"

    monkeypatch.setattr(llm_provider, "active_provider", lambda: "openai")
    assert llm_provider.provider_for_model(llm_provider.default_model("fast")) == "openai"


def test_active_provider_reads_the_saved_llm_config(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {"active_provider": "gemini", "gemini_api_key": "dummy"})
    assert llm_provider.active_provider() == "gemini"


def test_active_provider_falls_back_to_openai_when_claude_has_no_credentials(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {
        "active_provider": "claude",
        "claude_api_key": "",
        "openai_api_key": "sk-proj-test-1234",
    })
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm_provider.active_provider() == "openai"
    assert llm_provider.default_model("high") == "gpt-4o-mini"


def test_active_provider_honors_openai_explicitly_selected(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {
        "active_provider": "openai",
        "openai_api_key": "sk-proj-test-1234",
    })
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_provider.active_provider() == "openai"
    assert llm_provider.default_model("high") == "gpt-4o-mini"


# --------------------------------------------------------------------------
# Claude path
# --------------------------------------------------------------------------

class _ClaudeUsage:
    def __init__(self, prompt_tokens=300, output_tokens=50):
        self.input_tokens = prompt_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class StubClaudeClient:
    def __init__(self, parsed, raises=None):
        self.parsed = parsed
        self.raises = raises
        self.last_kwargs = None
        self.calls = 0

    def _parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(
            parsed_output=self.parsed,
            usage=_ClaudeUsage(),
            stop_reason="end_turn",
        )

    def _count(self, **kwargs):
        return SimpleNamespace(input_tokens=100)

    @property
    def messages(self):
        return SimpleNamespace(parse=self._parse, count_tokens=self._count)


def test_call_structured_dispatches_claude_models_to_the_claude_path():
    client = StubClaudeClient(Output(text="hi"))
    parsed, cost = llm_provider.call_structured(
        "claude-opus-5", "system", "prompt", Output, Budget(), client=client)
    assert parsed.text == "hi"
    assert cost > 0
    assert client.calls == 1


def test_claude_image_input_is_sent_as_an_image_block():
    client = StubClaudeClient(Output(text="described"))
    parsed, cost = llm_provider.call_structured(
        "claude-opus-5", "system", "describe this", Output, Budget(),
        image=(b"\x89PNG\r\n\x1a\nfakepngdata", "image/png"), client=client)
    assert parsed.text == "described"
    messages = client.last_kwargs["messages"]
    assert len(messages[0]["content"]) == 2
    assert messages[0]["content"][0]["type"] == "image"
    assert messages[0]["content"][1]["type"] == "text"


def test_claude_budget_checked_before_and_recorded_after():
    client = StubClaudeClient(Output(text="hi"))
    budget = Budget(max_usd=1.0)
    _, cost = llm_provider.call_structured(
        "claude-opus-5", "system", "prompt", Output, budget, client=client)
    assert budget.calls == 1
    assert budget.spent_usd == pytest.approx(cost)


def test_claude_budget_exceeded_before_call_raises():
    client = StubClaudeClient(Output(text="hi"))
    with pytest.raises(BudgetExceeded):
        llm_provider.call_structured(
            "claude-opus-5", "system", "prompt", Output,
            Budget(max_usd=0.0000001), client=client)
    assert client.calls == 0


def test_claude_refusal_raises():
    client = StubClaudeClient(None)
    client._parse = lambda **kw: SimpleNamespace(
        parsed_output=None, usage=None, stop_reason="refusal")
    with pytest.raises(RuntimeError, match="declined"):
        llm_provider.call_structured(
            "claude-opus-5", "system", "prompt", Output, Budget(), client=client)


def test_call_structured_labels_a_claude_failure():
    client = StubClaudeClient(None, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="judge failed"):
        llm_provider.call_structured(
            "claude-opus-5", "system", "prompt", Output, Budget(), client=client, label="judge")


# --------------------------------------------------------------------------
# Gemini path
# --------------------------------------------------------------------------

class _GeminiResponse:
    def __init__(self, parsed, *, prompt_tokens=300, candidates_tokens=40, thoughts_tokens=10):
        self.parsed = parsed
        self.usage_metadata = SimpleNamespace(
            prompt_token_count=prompt_tokens, candidates_token_count=candidates_tokens,
            thoughts_token_count=thoughts_tokens, cached_content_token_count=0)


class StubGeminiClient:
    def __init__(self, parsed, raises=None):
        self.parsed = parsed
        self.raises = raises
        self.last_kwargs = None
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return _GeminiResponse(self.parsed)


def test_call_structured_dispatches_gemini_models_to_the_gemini_path():
    client = StubGeminiClient(Output(text="hi"))
    parsed, cost = llm_provider.call_structured(
        "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)
    assert parsed.text == "hi"
    assert cost > 0
    assert client.calls == 1


def test_gemini_image_input_is_sent_as_a_part():
    client = StubGeminiClient(Output(text="described"))
    parsed, cost = llm_provider.call_structured(
        "gemini-3.8-flash", "system", "describe this", Output, Budget(),
        image=(b"\x89PNG\r\n\x1a\nfakepngdata", "image/png"), client=client)
    assert parsed.text == "described"
    contents = client.last_kwargs["contents"]
    assert len(contents) == 2


def test_gemini_budget_checked_before_and_recorded_after():
    client = StubGeminiClient(Output(text="hi"))
    budget = Budget(max_usd=1.0)
    _, cost = llm_provider.call_structured(
        "gemini-3.8-flash", "system", "prompt", Output, budget, client=client)
    assert budget.calls == 1
    assert budget.spent_usd == pytest.approx(cost)


def test_gemini_budget_exceeded_before_call_raises():
    client = StubGeminiClient(Output(text="hi"))
    with pytest.raises(BudgetExceeded):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output,
            Budget(max_usd=0.0000001), client=client)
    assert client.calls == 0


def test_gemini_missing_credentials_are_reported_before_a_client_is_built(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {"gemini_api_key": ""})
    with pytest.raises(CredentialsMissing):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=None)


def test_gemini_auth_failure_is_translated_to_credentials_missing():
    client = StubGeminiClient(None, raises=RuntimeError("400 PERMISSION_DENIED: bad API key"))
    with pytest.raises(CredentialsMissing):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)


def test_gemini_other_failures_are_wrapped_not_swallowed():
    client = StubGeminiClient(None, raises=RuntimeError("400 INVALID_ARGUMENT: bad request"))
    with pytest.raises(RuntimeError, match="Gemini request failed"):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)
    assert client.calls == 1


def test_gemini_a_transient_503_is_retried_and_can_still_succeed(monkeypatch):
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _seconds: None)
    failures = [RuntimeError("503 UNAVAILABLE: overloaded"), RuntimeError("503 UNAVAILABLE: overloaded")]

    def _flaky(**kwargs):
        client.calls += 1
        if failures:
            raise failures.pop(0)
        return _GeminiResponse(Output(text="recovered"))

    client = StubGeminiClient(None)
    client.models.generate_content = _flaky
    parsed, _ = llm_provider.call_structured(
        "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)
    assert parsed.text == "recovered"
    assert client.calls == 3


def test_gemini_a_persistent_503_still_fails_after_retries(monkeypatch):
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _seconds: None)
    client = StubGeminiClient(None, raises=RuntimeError("503 UNAVAILABLE: persistent"))
    with pytest.raises(RuntimeError, match="Gemini request failed"):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)
    assert client.calls == 3


def test_gemini_a_429_quota_error_is_not_retried():
    client = StubGeminiClient(None, raises=RuntimeError("429 RESOURCE_EXHAUSTED: quota"))
    with pytest.raises(RuntimeError, match="Gemini request failed"):
        llm_provider.call_structured(
            "gemini-3.8-flash", "system", "prompt", Output, Budget(), client=client)
    assert client.calls == 1


def test_gemini_cost_is_billed_from_usage_metadata():
    client = StubGeminiClient(Output(text="hi"))
    budget = Budget()
    _, cost = llm_provider.call_structured(
        "gemini-3.8-flash", "system", "prompt", Output, budget, client=client)
    assert cost > 0
    assert budget.spent_usd == pytest.approx(cost)
    assert budget.output_tokens == 50


# --------------------------------------------------------------------------
# OpenAI path
# --------------------------------------------------------------------------

class _OpenAIResponseUsage:
    def __init__(self, prompt_tokens=300, output_tokens=40):
        self.input_tokens = prompt_tokens
        self.output_tokens = output_tokens
        self.input_tokens_details = SimpleNamespace(cached_tokens=0)


class StubOpenAIClient:
    def __init__(self, parsed, raises=None):
        self.parsed = parsed
        self.raises = raises
        self.last_kwargs = None
        self.calls = 0

        self.responses = SimpleNamespace(
            parse=self._parse,
            input_tokens=SimpleNamespace(count=self._count_input_tokens),
        )

    def _parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(
            output_parsed=self.parsed,
            usage=_OpenAIResponseUsage(),
        )

    def _count_input_tokens(self, **kwargs):
        return SimpleNamespace(input_tokens=100)


def test_call_structured_dispatches_openai_models_to_the_openai_path():
    client = StubOpenAIClient(Output(text="hi"))
    parsed, cost = llm_provider.call_structured(
        "gpt-5.4-mini", "system", "prompt", Output, Budget(), client=client)
    assert parsed.text == "hi"
    assert cost > 0
    assert client.calls == 1


def test_openai_image_input_is_sent_as_an_image_block():
    client = StubOpenAIClient(Output(text="described"))
    parsed, cost = llm_provider.call_structured(
        "gpt-5.4-mini", "system", "describe this", Output, Budget(),
        image=(b"\x89PNG\r\n\x1a\nfakepngdata", "image/png"), client=client)
    assert parsed.text == "described"
    input_list = client.last_kwargs["input"]
    user_turn = input_list[0]
    content = user_turn["content"]
    assert len(content) == 2
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"


def test_openai_budget_checked_before_and_recorded_after():
    client = StubOpenAIClient(Output(text="hi"))
    budget = Budget(max_usd=1.0)
    _, cost = llm_provider.call_structured(
        "gpt-5.4-mini", "system", "prompt", Output, budget, client=client)
    assert budget.calls == 1
    assert budget.spent_usd == pytest.approx(cost)


def test_openai_budget_exceeded_before_call_raises():
    client = StubOpenAIClient(Output(text="hi"))
    with pytest.raises(BudgetExceeded):
        llm_provider.call_structured(
            "gpt-5.4-mini", "system", "prompt", Output,
            Budget(max_usd=0.0000001), client=client)
    assert client.calls == 0


def test_openai_missing_credentials_are_reported_before_a_client_is_built(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {"openai_api_key": ""})
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CredentialsMissing, match="No OpenAI credentials"):
        llm_provider.call_structured(
            "gpt-5.4-mini", "system", "prompt", Output, Budget(), client=None)


def test_openai_auth_failure_is_translated_to_credentials_missing():
    import httpx as httpx2
    import openai
    resp = httpx2.Response(401, request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
    client = StubOpenAIClient(None, raises=openai.AuthenticationError(
        "bad key", response=resp, body=None))
    with pytest.raises(CredentialsMissing):
        llm_provider.call_structured(
            "gpt-5.4-mini", "system", "prompt", Output, Budget(), client=client)


def test_openai_a_token_count_failure_falls_back_instead_of_skipping_the_budget():
    client = StubOpenAIClient(Output(text="hi"))
    client.responses.input_tokens.count = lambda **kw: (_ for _ in ()).throw(RuntimeError("unavailable"))
    parsed, cost = llm_provider.call_structured(
        "gpt-5.4-mini", "system", "prompt", Output, Budget(), client=client)
    assert parsed.text == "hi"


def test_openai_other_failures_are_labeled_not_swallowed():
    client = StubOpenAIClient(None, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="judge failed"):
        llm_provider.call_structured(
            "gpt-5.4-mini", "system", "prompt", Output, Budget(), client=client, label="judge")


def test_openai_cost_is_billed_from_usage():
    client = StubOpenAIClient(Output(text="hi"))
    budget = Budget()
    _, cost = llm_provider.call_structured(
        "gpt-5.4-mini", "system", "prompt", Output, budget, client=client)
    assert cost > 0
    assert budget.spent_usd == pytest.approx(cost)
    assert budget.output_tokens == 40


# --------------------------------------------------------------------------
# MODEL_CATALOG / provider-scoped model picker (Content Writer)
# --------------------------------------------------------------------------

def test_model_catalog_covers_every_provider_ordered_weakest_to_strongest():
    for provider in ("claude", "openai", "gemini"):
        catalog = llm_provider.MODEL_CATALOG[provider]
        assert len(catalog) >= 2
        ids = [m["id"] for m in catalog]
        assert len(ids) == len(set(ids)), f"duplicate model id in {provider} catalog"
        for m in catalog:
            assert m["id"] and m["label"]


def test_strongest_model_is_the_catalogs_last_entry():
    for provider in ("claude", "openai", "gemini"):
        assert llm_provider.strongest_model(provider) == llm_provider.MODEL_CATALOG[provider][-1]["id"]


def test_configured_providers_only_lists_providers_with_credentials(monkeypatch):
    from src import llm_config
    # load_config() syncs keys into os.environ as a side effect -- an
    # earlier real call in this process may have already set these, so
    # clear them for a hermetic check (see llm_config.py's env-sync).
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm_config, "load_config", lambda: {
        "active_provider": "openai", "openai_api_key": "sk-real", "gemini_api_key": "", "claude_api_key": "",
    })
    assert llm_provider.configured_providers() == ["openai"]


def test_configured_providers_can_list_more_than_one(monkeypatch):
    from src import llm_config
    monkeypatch.setattr(llm_config, "load_config", lambda: {
        "active_provider": "openai", "openai_api_key": "sk-real", "gemini_api_key": "dummy", "claude_api_key": "",
    })
    assert llm_provider.configured_providers() == ["openai", "gemini"]


def test_resolve_model_keeps_an_explicit_choice_valid_for_the_provider():
    picked = llm_provider.MODEL_CATALOG["gemini"][0]["id"]
    assert llm_provider.resolve_model(picked, provider="gemini") == picked


def test_resolve_model_falls_back_when_explicit_choice_is_empty_or_unknown():
    # Empty (writer never picked one) -> that provider's recommended default.
    assert llm_provider.resolve_model("", provider="openai") == llm_provider.recommended_model("openai")
    # A model id from a provider that's no longer active -> recommended
    # default of the provider actually in use, not a hard error.
    stale = llm_provider.MODEL_CATALOG["claude"][0]["id"]
    assert llm_provider.resolve_model(stale, provider="openai") == llm_provider.recommended_model("openai")


def test_resolve_model_defaults_to_the_active_provider_when_none_given(monkeypatch):
    monkeypatch.setattr(llm_provider, "active_provider", lambda: "gemini")
    assert llm_provider.resolve_model("") == llm_provider.recommended_model("gemini")


def test_recommended_model_is_marked_in_the_catalog_and_is_not_the_strongest():
    for provider in ("claude", "openai", "gemini"):
        recommended = llm_provider.recommended_model(provider)
        marked = [m for m in llm_provider.MODEL_CATALOG[provider] if m.get("default")]
        assert len(marked) == 1, f"{provider} catalog should mark exactly one default"
        assert recommended == marked[0]["id"]
        assert recommended != llm_provider.strongest_model(provider), (
            f"{provider}'s recommended default should not be its most expensive tier")


# --------------------------------------------------------------------------
# Reasoning models: output-budget headroom and diagnostic "no output" errors
# --------------------------------------------------------------------------

def test_reasoning_model_gets_extra_output_token_headroom():
    """A reasoning model's thinking tokens bill from the same
    max_output_tokens ceiling as its visible completion -- confirmed live
    against gpt-5.5-pro returning no parsed output at the old flat ceiling.
    The call sent to the API (and the budget check) must both reflect the
    bumped total, not the caller's original number."""
    client = StubOpenAIClient(Output(text="hi"))
    llm_provider.call_structured(
        "gpt-5.5-pro", "system", "prompt", Output, Budget(max_usd=10.0),
        max_output_tokens=4096, effort="high", client=client)
    assert client.last_kwargs["max_output_tokens"] == 4096 + 12288
    assert client.last_kwargs["reasoning"] == {"effort": "high"}


def test_non_reasoning_model_gets_no_headroom():
    client = StubOpenAIClient(Output(text="hi"))
    llm_provider.call_structured(
        "gpt-4o-mini", "system", "prompt", Output, Budget(),
        max_output_tokens=4096, client=client)
    assert client.last_kwargs["max_output_tokens"] == 4096
    assert "reasoning" not in client.last_kwargs


def test_no_parsed_output_reports_truncation_when_incomplete():
    client = StubOpenAIClient(None)
    client.responses.parse = lambda **kw: SimpleNamespace(
        output_parsed=None, status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"), usage=None)
    with pytest.raises(RuntimeError, match="ran out of its output budget"):
        llm_provider.call_structured(
            "gpt-5.5-pro", "system", "prompt", Output, Budget(max_usd=10.0), client=client)


def test_no_parsed_output_with_no_diagnostic_info_still_raises_clearly():
    client = StubOpenAIClient(None)
    with pytest.raises(RuntimeError, match="returned no parseable output"):
        llm_provider.call_structured(
            "gpt-4o-mini", "system", "prompt", Output, Budget(), client=client)
