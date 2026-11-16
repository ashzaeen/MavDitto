"""The brand-voice *method*, vendored from Anthropic's knowledge-work-plugins
(`vendor/anthropic_brand_voice/`, Apache-2.0 -- see its NOTICE).

Those files are Claude Code skill/agent definitions, so they carry lines that
only make sense inside that host (slash commands, `.claude/` paths, "delegate
to the X agent", pointers to reference files). This module pulls out just the
sections that describe *how to write and check on-brand copy*, drops the
host-specific lines, and exposes them as prompt blocks. The vendored files
stay byte-for-byte as fetched.

Deliberately not exposed: the sales-oriented tone-by-context matrix and the
before/after examples -- they illustrate the method with invented statistics
for a fictional SaaS company, and this tool forbids unsourced figures. The
brand profile (config/brand-voice.json) supplies its own matrix and examples.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "vendor" / "anthropic_brand_voice"

_HOST_ONLY = re.compile(
    r"`references/|references/[\w-]+\.md|agents/[\w-]+\.md|/brand-voice:|\.claude/"
    r"|delegate to the|Cowork|always-explain")


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (VENDOR_DIR / name).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under a markdown heading (any level), up to the next heading
    of the same or higher level."""
    # Headings inside ``` fences are example content, not structure -- the
    # guideline template's open-questions block is one.
    lines = text.splitlines()
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = None if in_fence else re.match(r"^(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == heading:
            level = len(m.group(1))
            out, fence = [], False
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("```"):
                    fence = not fence
                n = None if fence else re.match(r"^(#+)\s", nxt)
                if n and len(n.group(1)) <= level:
                    break
                out.append(nxt)
            return _clean("\n".join(out))
    raise KeyError(f"heading {heading!r} not found in vendored method")


def _clean(text: str) -> str:
    kept = [line for line in text.splitlines() if not _HOST_ONLY.search(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def voice_model() -> str:
    """Voice is constant, tone flexes -- the model and how to apply it."""
    src = _read("voice-constant-tone-flexes.md")
    return "\n\n".join([
        _section(src, "The Distinction"),
        "How to use the We Are / We Are Not table:\n" + _section(src, "How to Use During Enforcement"),
        "Common mistakes to avoid:\n" + _section(src, "Common Enforcement Mistakes"),
    ])


def enforcement_procedure() -> str:
    """The write-time procedure: analyze, apply voice, flex tone, generate,
    handle conflicts, respect open questions."""
    src = _read("brand-voice-enforcement.SKILL.md")
    return "\n\n".join([
        "Before writing:\n" + _section(src, "1. Analyze the Content Request"),
        "Voice:\n" + _section(src, "2. Apply Voice Constants"),
        "Tone:\n" + _section(src, "3. Flex Tone for Context"),
        "Writing:\n" + _section(src, "4. Generate Content"),
        "When the request conflicts with the guidelines:\n" + _section(src, "Handling Conflicts"),
        "Open questions:\n" + _section(src, "Open Questions Awareness"),
    ])


def qa_checklist() -> str:
    """The critic's checklist and standards."""
    src = _read("quality-assurance.agent.md")
    return "\n\n".join([
        _section(src, "Content Validation"),
        _section(src, "Quality Standards"),
    ])


def guideline_method() -> str:
    """How to derive guidelines from source material, with confidence scores
    and open questions -- used by the setup engine's brand-voice ingest."""
    src = _read("guideline-generation.SKILL.md")
    return "\n\n".join([
        _section(src, "3. Synthesize Into Guidelines"),
        _section(src, "4. Assign Confidence Scores"),
        _section(src, "5. Surface Open Questions"),
        _section(src, "Privacy and Security"),
    ])
