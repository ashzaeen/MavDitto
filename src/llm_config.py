"""Local LLM API Key Configuration and Provider Management.

Manages API keys for Claude (Anthropic), OpenAI, and Gemini (Google AI),
persisting configuration locally to `data/llm_config.json` and keeping
environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`)
in sync so all pipeline tools can access them seamlessly.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "llm_config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "active_provider": "claude",
    "claude_api_key": "",
    "openai_api_key": "",
    "gemini_api_key": "",
}


def mask_key(key: str) -> str:
    """Return a masked representation of an API key for safe UI display."""
    if not key:
        return ""
    key = key.strip()
    if len(key) <= 8:
        return "••••••••"
    if key.startswith("sk-ant-"):
        prefix = key[:7]
        suffix = key[-4:]
        return f"{prefix}...{suffix}"
    if key.startswith("sk-"):
        prefix = key[:5]
        suffix = key[-4:]
        return f"{prefix}...{suffix}"
    if key.startswith("AIza"):
        prefix = key[:6]
        suffix = key[-4:]
        return f"{prefix}...{suffix}"
    return f"{key[:4]}...{key[-4:]}"


def is_masked_key(val: str) -> bool:
    """Return True if the key string is masked and should not overwrite a real key."""
    if not val:
        return False
    val = val.strip()
    return "..." in val or "••" in val or "\u2022\u2022" in val


def load_config() -> dict[str, Any]:
    """Load config from disk and environment, keeping environment in sync."""
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    config.update(loaded)
        except Exception:
            pass

    # Strip any corrupted masked placeholders that may have been saved to disk
    for k in ("claude_api_key", "openai_api_key", "gemini_api_key"):
        if is_masked_key(config.get(k, "")):
            config[k] = ""

    # Environment variables override or backfill empty config values
    env_claude = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    env_openai = os.environ.get("OPENAI_API_KEY", "").strip()
    env_gemini = os.environ.get("GEMINI_API_KEY", "").strip()

    if env_claude and not config.get("claude_api_key"):
        config["claude_api_key"] = env_claude
    if env_openai and not config.get("openai_api_key"):
        config["openai_api_key"] = env_openai
    if env_gemini and not config.get("gemini_api_key"):
        config["gemini_api_key"] = env_gemini

    # Keep os.environ in sync with whatever valid keys exist
    if config.get("claude_api_key"):
        os.environ["ANTHROPIC_API_KEY"] = config["claude_api_key"]
    if config.get("openai_api_key"):
        os.environ["OPENAI_API_KEY"] = config["openai_api_key"]
    if config.get("gemini_api_key"):
        os.environ["GEMINI_API_KEY"] = config["gemini_api_key"]

    claude_has_key = bool(config.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY"))
    openai_has_key = bool(config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"))
    gemini_has_key = bool(config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY"))

    # Auto-resolve active_provider if the currently selected provider has no credentials
    active = config.get("active_provider")
    if active == "claude" and not claude_has_key:
        if openai_has_key:
            config["active_provider"] = "openai"
        elif gemini_has_key:
            config["active_provider"] = "gemini"
    elif active == "openai" and not openai_has_key:
        if gemini_has_key:
            config["active_provider"] = "gemini"
        elif claude_has_key:
            config["active_provider"] = "claude"
    elif active == "gemini" and not gemini_has_key:
        if openai_has_key:
            config["active_provider"] = "openai"
        elif claude_has_key:
            config["active_provider"] = "claude"
    elif not active:
        if openai_has_key:
            config["active_provider"] = "openai"
        elif gemini_has_key:
            config["active_provider"] = "gemini"
        else:
            config["active_provider"] = "claude"

    return config


def save_config(new_data: dict[str, Any]) -> dict[str, Any]:
    """Save new keys and active provider, updating os.environ and disk."""
    current = load_config()

    # Only update keys if a non-masked, non-empty value was provided
    if "claude" in new_data:
        val = str(new_data["claude"]).strip()
        if val and not is_masked_key(val):
            current["claude_api_key"] = val
            os.environ["ANTHROPIC_API_KEY"] = val
        elif val == "":
            current["claude_api_key"] = ""
            os.environ.pop("ANTHROPIC_API_KEY", None)

    if "openai" in new_data:
        val = str(new_data["openai"]).strip()
        if val and not is_masked_key(val):
            current["openai_api_key"] = val
            os.environ["OPENAI_API_KEY"] = val
        elif val == "":
            current["openai_api_key"] = ""
            os.environ.pop("OPENAI_API_KEY", None)

    if "gemini" in new_data:
        val = str(new_data["gemini"]).strip()
        if val and not is_masked_key(val):
            current["gemini_api_key"] = val
            os.environ["GEMINI_API_KEY"] = val
        elif val == "":
            current["gemini_api_key"] = ""
            os.environ.pop("GEMINI_API_KEY", None)

    passed_provider = str(new_data.get("activeProvider", "")).strip().lower()
    if passed_provider in ("claude", "openai", "gemini"):
        current["active_provider"] = passed_provider
    else:
        # If active provider was not explicitly passed, auto-select a provider that has a key
        claude_has_key = bool(current.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY"))
        openai_has_key = bool(current.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"))
        gemini_has_key = bool(current.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY"))
        if current.get("active_provider") == "claude" and not claude_has_key:
            if openai_has_key:
                current["active_provider"] = "openai"
            elif gemini_has_key:
                current["active_provider"] = "gemini"

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

    return get_status()


def get_status() -> dict[str, Any]:
    """Return masked status for frontend consumption."""
    cfg = load_config()
    claude_key = cfg.get("claude_api_key", "").strip()
    openai_key = cfg.get("openai_api_key", "").strip()
    gemini_key = cfg.get("gemini_api_key", "").strip()

    return {
        "activeProvider": cfg.get("active_provider", "claude"),
        "claude": {
            "name": "Claude (Anthropic)",
            "configured": bool(claude_key),
            "masked": mask_key(claude_key),
        },
        "openai": {
            "name": "OpenAI",
            "configured": bool(openai_key),
            "masked": mask_key(openai_key),
        },
        "gemini": {
            "name": "Google Gemini",
            "configured": bool(gemini_key),
            "masked": mask_key(gemini_key),
        },
    }


def verify_provider_key(provider: str, key: str = "") -> dict[str, Any]:
    """Test connecting to the specified provider with the provided key or saved key."""
    cfg = load_config()
    provider = provider.lower().strip()

    resolved_key = key.strip() if key and not is_masked_key(key) else ""
    if not resolved_key:
        if provider == "claude":
            resolved_key = cfg.get("claude_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        elif provider == "openai":
            resolved_key = cfg.get("openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        elif provider == "gemini":
            resolved_key = cfg.get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")

    if not resolved_key:
        return {"ok": False, "error": f"No API key provided for {provider.capitalize()}."}

    import httpx

    try:
        if provider == "claude":
            resp = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": resolved_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=8.0,
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "Successfully connected to Anthropic Claude API."}
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = data.get("error", {}).get("message") or resp.text or f"HTTP {resp.status_code}"
            return {"ok": False, "error": f"Claude API error: {err_msg}"}

        elif provider == "openai":
            resp = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {resolved_key}"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "Successfully connected to OpenAI API."}
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = data.get("error", {}).get("message") or resp.text or f"HTTP {resp.status_code}"
            return {"ok": False, "error": f"OpenAI API error: {err_msg}"}

        elif provider == "gemini":
            resp = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={resolved_key}",
                timeout=8.0,
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "Successfully connected to Google Gemini API."}
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = data.get("error", {}).get("message") or resp.text or f"HTTP {resp.status_code}"
            return {"ok": False, "error": f"Gemini API error: {err_msg}"}

        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

    except Exception as exc:
        return {"ok": False, "error": f"Connection error: {str(exc)}"}
