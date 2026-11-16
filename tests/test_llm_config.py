import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.llm_config import (
    load_config,
    save_config,
    get_status,
    mask_key,
    is_masked_key,
    verify_provider_key,
)


@pytest.fixture(autouse=True)
def isolate_llm_env():
    orig = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
    }
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    try:
        yield
    finally:
        for k, v in orig.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("short") == "••••••••"
    assert mask_key("sk-ant-api03-abcdef123456") == "sk-ant-...3456"
    assert mask_key("sk-proj-1234567890abcdef") == "sk-pr...cdef"
    assert mask_key("AIzaSyD9876543210zyxw") == "AIzaSy...zyxw"
    assert mask_key("custom-key-12345678") == "cust...5678"


def test_is_masked_key():
    assert is_masked_key("") is False
    assert is_masked_key("sk-proj-real-key-1234") is False
    assert is_masked_key("sk-pr...Fh8A") is True
    assert is_masked_key("sk-ant-...3456") is True
    assert is_masked_key("••••••••") is True


def test_load_and_save_config(tmp_path, monkeypatch):
    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    # Empty initially
    cfg = load_config()
    assert cfg["active_provider"] == "claude"

    # Save keys
    saved = save_config({
        "claude": "sk-ant-test-key-1234",
        "openai": "sk-proj-test-key-5678",
        "gemini": "AIzaSy-test-key-9999",
        "activeProvider": "openai",
    })

    assert saved["activeProvider"] == "openai"
    assert saved["claude"]["configured"] is True
    assert saved["openai"]["configured"] is True
    assert saved["gemini"]["configured"] is True
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-test-key-1234"
    assert os.environ.get("OPENAI_API_KEY") == "sk-proj-test-key-5678"
    assert os.environ.get("GEMINI_API_KEY") == "AIzaSy-test-key-9999"

    # Reload from disk
    status = get_status()
    assert status["activeProvider"] == "openai"
    assert status["claude"]["configured"] is True
    assert "sk-ant-" in status["claude"]["masked"]

    # Clear one key
    save_config({"gemini": ""})
    status_cleared = get_status()
    assert status_cleared["gemini"]["configured"] is False
    assert os.environ.get("GEMINI_API_KEY") is None


def test_save_masked_key_does_not_corrupt_existing_key(tmp_path, monkeypatch):
    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    # First save real keys
    save_config({
        "openai": "sk-proj-super-secret-key-1234",
        "activeProvider": "openai",
    })
    assert load_config()["openai_api_key"] == "sk-proj-super-secret-key-1234"

    # Simulate frontend submitting the masked status back
    masked_status = get_status()
    masked_key = masked_status["openai"]["masked"]
    assert "..." in masked_key

    # Re-save with masked key
    save_config({
        "openai": masked_key,
        "activeProvider": "openai",
    })

    # The real key MUST NOT have been overwritten by the masked string!
    assert load_config()["openai_api_key"] == "sk-proj-super-secret-key-1234"
    assert os.environ.get("OPENAI_API_KEY") == "sk-proj-super-secret-key-1234"


def test_auto_resolve_active_provider_when_only_openai_configured(tmp_path, monkeypatch):
    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    # User saves only openai key without explicitly changing activeProvider
    saved = save_config({
        "openai": "sk-proj-test-key-5678",
    })

    # activeProvider must automatically switch to openai because claude has no keys!
    assert saved["activeProvider"] == "openai"
    assert load_config()["active_provider"] == "openai"


def test_corrupted_mask_in_config_file_is_cleaned_on_load(tmp_path, monkeypatch):
    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    with open(test_file, "w", encoding="utf-8") as f:
        json.dump({
            "active_provider": "openai",
            "openai_api_key": "sk-pr...Fh8A",
            "claude_api_key": "",
        }, f)

    cfg = load_config()
    assert cfg["openai_api_key"] == ""
    assert cfg["active_provider"] == "openai"


def test_verify_provider_key_no_key(tmp_path, monkeypatch):
    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    res = verify_provider_key("claude", "")
    assert res["ok"] is False
    assert "No API key" in res["error"]


@patch("httpx.get")
def test_verify_provider_key_success(mock_get, tmp_path, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)

    res = verify_provider_key("openai", "sk-proj-real-looking-key")
    assert res["ok"] is True
    assert "Successfully connected" in res["message"]


@patch("httpx.get")
def test_verify_provider_key_resolves_saved_key_when_masked(mock_get, tmp_path, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    test_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("src.llm_config.CONFIG_PATH", test_file)
    save_config({"openai": "sk-proj-saved-real-key-1234"})

    res = verify_provider_key("openai", "sk-pr...1234")
    assert res["ok"] is True
    # Verify mock_get was called with the unmasked real key in Authorization header
    mock_get.assert_called_once()
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-proj-saved-real-key-1234"
