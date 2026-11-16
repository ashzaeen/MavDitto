"""Reads and writes `/config/*.json` -- plain files, not a database, per the
design doc's white-label architecture: versionable, diffable, editable by
hand, and matching the fork-and-run use case with no migrations or schema
setup beyond what the app already needs.

Both Content Writer and Web Builder check `config_status()` to decide
whether to show their normal setup panel or a Configure screen; the setup
wizard and Settings' "Redo brand voice"/"Redo component catalog" actions
both write through `save_config()`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
BRAND_VOICE_PATH = CONFIG_DIR / "brand-voice.json"
COMPONENTS_PATH = CONFIG_DIR / "components.json"
KNOWLEDGE_BASE_PATH = CONFIG_DIR / "knowledge-base.json"


def config_status() -> dict[str, bool]:
    return {
        "brandVoice": BRAND_VOICE_PATH.is_file(),
        "components": COMPONENTS_PATH.is_file(),
        # Optional: Content Writer runs without one, it just has no verified
        # facts to cite.
        "knowledgeBase": KNOWLEDGE_BASE_PATH.is_file(),
    }


def save_config(*, brand_voice: dict[str, Any] | None = None,
                components: dict[str, Any] | None = None) -> dict[str, bool]:
    """Writes whichever of the two configs is given, leaving the other
    untouched -- Settings' two "Redo" actions are independent, and the setup
    wizard's Configure screens can complete one before the other."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if brand_voice is not None:
        brand_voice = {k: v for k, v in brand_voice.items() if k != "cost_usd"}
        BRAND_VOICE_PATH.write_text(
            json.dumps(brand_voice, indent=2, ensure_ascii=False), encoding="utf-8")
    if components is not None:
        components = {k: v for k, v in components.items() if k != "cost_usd"}
        COMPONENTS_PATH.write_text(
            json.dumps(components, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_status()
