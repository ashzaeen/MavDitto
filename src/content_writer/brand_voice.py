"""The brand profile (config/brand-voice.json) and knowledge base
(config/knowledge-base.json): loading, v1 -> v2 normalization, and the one
shared answer to "is this deployment UTA's own".

v1 profiles (and any fork's ingested profile from before v2) carry only
brand / registers / shared_principles / seed_system_prompt / guardrail.
`normalize` fills every v2 field with a neutral default so every caller can
read the v2 shape unconditionally -- no fork breaks on upgrade, and none
inherits UTA-specific content it never configured.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
CONFIG_PATH = CONFIG_DIR / "brand-voice.json"
KNOWLEDGE_BASE_PATH = CONFIG_DIR / "knowledge-base.json"

DIALS = ("formality", "energy", "technical_depth")

DEFAULT_TONE_DIMENSIONS: dict[str, dict[str, Any]] = {
    "formality": {
        "label": "Formality",
        "levels": {"1": "Casual: contractions, conversational",
                   "2": "Relaxed but professional",
                   "3": "Professional and conversational",
                   "4": "Formal: complete sentences, structured",
                   "5": "Highly formal: institutional, no contractions"},
    },
    "energy": {
        "label": "Energy",
        "levels": {"1": "Measured and deliberate",
                   "2": "Calm and steady",
                   "3": "Balanced: informative and engaging",
                   "4": "Lively: active verbs, shorter sentences",
                   "5": "High: urgent, punchy"},
    },
    "technical_depth": {
        "label": "Technical depth",
        "levels": {"1": "Plain language, outcomes only, no jargon",
                   "2": "Mostly plain, a few field terms explained",
                   "3": "Field terms used and briefly explained",
                   "4": "Assumes some background",
                   "5": "Specialist: full technical terminology"},
    },
}

DEFAULT_DIALS = {"formality": 3, "energy": 3, "technical_depth": 2}

DEFAULT_AUDIENCES = [
    {"key": "general", "label": "General public",
     "description": "Anyone arriving from search with no prior context.",
     "reading_level": "grade 10", "default_register": None},
]


def normalize(bv: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(bv)
    out.setdefault("brand", "")
    out.setdefault("brand_full_name", out["brand"])
    out.setdefault("registers", {})
    out.setdefault("shared_principles", [])
    out.setdefault("seed_system_prompt", "")
    guardrail = out.setdefault("guardrail", {})
    guardrail.setdefault("floor_description", "")
    guardrail.setdefault("checks", [])
    out.setdefault("we_are", [])
    dims = out.setdefault("tone_dimensions", {})
    for key, default in DEFAULT_TONE_DIMENSIONS.items():
        dims.setdefault(key, copy.deepcopy(default))
    out.setdefault("tone_by_context", {})
    terms = out.setdefault("terminology", {})
    terms.setdefault("preferred", [])
    terms.setdefault("banned", [])
    # Claims allowed only when the brief/source/facts make them too.
    terms.setdefault("needs_source", [])
    terms.setdefault("style_rules", [])
    if not out.get("audiences"):
        out["audiences"] = copy.deepcopy(DEFAULT_AUDIENCES)
    out.setdefault("examples", [])
    out.setdefault("open_questions", [])
    return out


def load_brand_voice(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return normalize(json.loads(Path(path).read_text(encoding="utf-8")))


def is_uta(bv: dict[str, Any]) -> bool:
    """True when the active profile is UTA's pre-committed one -- the setup
    wizard's "Yes, this is for UTA" leaves it in place; "No, a different
    organization" replaces it with an ingested profile under another name."""
    return str(bv.get("brand", "")).strip().lower() == "uta"


def brand_name(bv: dict[str, Any]) -> str:
    return str(bv.get("brand") or "").strip() or "the organization"


def brand_full_name(bv: dict[str, Any]) -> str:
    return str(bv.get("brand_full_name") or "").strip() or brand_name(bv)


def dials_for(bv: dict[str, Any], template_key: str) -> dict[str, int]:
    row = bv.get("tone_by_context", {}).get(template_key) or {}
    return {d: int(row.get(d, DEFAULT_DIALS[d])) for d in DIALS}


def register_keys(bv: dict[str, Any]) -> list[str]:
    """The profile's own register names -- an ingested profile may not have
    UTA's institutional / prospective-student pair at all. Keys are
    normalized to hyphens (the committed file uses prospective_student, the
    rest of the code has always said prospective-student)."""
    return [k.replace("_", "-") for k in bv.get("registers", {})]


# --- knowledge base ---------------------------------------------------------

def load_knowledge_base(path: Path = KNOWLEDGE_BASE_PATH) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    facts = data.get("facts", []) if isinstance(data, dict) else data
    return [f for f in facts if isinstance(f, dict) and str(f.get("fact", "")).strip()]


def save_knowledge_base(facts: list[dict[str, Any]], path: Path = KNOWLEDGE_BASE_PATH) -> None:
    clean = []
    for i, f in enumerate(facts):
        fact = str(f.get("fact", "")).strip()
        if not fact:
            continue
        clean.append({
            "id": str(f.get("id") or f"fact-{i + 1}"),
            "title": str(f.get("title", "")).strip(),
            "fact": fact,
            "source_url": str(f.get("source_url", "")).strip(),
            "as_of": str(f.get("as_of", "")).strip(),
            "tags": [str(t).strip() for t in f.get("tags", []) if str(t).strip()],
        })
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"facts": clean}, indent=2, ensure_ascii=False),
                          encoding="utf-8")
