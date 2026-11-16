"""One-off: build the v3 component catalog (77 components, reconciled from
UTA's old ds.web.uta.edu and new uta.edu design-system sites) from the
scraped+reconciled scratch data produced earlier in that effort
(`merged_raw.json`: one record per final component, with `old_text`/
`new_text`/`screenshot`/`source_sites`).

Not part of the running app -- run once, review the diff, commit the
result. Re-run only if the two live sites are re-scraped and reconciled
again.

Design, matching `migrate_catalog_schema.py`'s discipline:
- For the 68 components that trace back to the old site (kept "old only"
  or merged "both"), the field skeleton (fieldType/constraints/category/
  dynamic/chrome/sharedCopyUnconfirmed) is NOT re-derived -- it's already
  verified, deterministic data sitting in the current config/components.json.
  Only `purpose`/`examples`/`special_features`/`visual_variant` are
  refreshed by one LLM call per component, now grounded in the deeper
  old-site "ABOUT THE COMPONENT" prose and (where present) the new site's
  richer text, new-site text taking precedence per the user's decision.
- For the 9 new-only components, there is no prior verified skeleton, so
  the same LLM call also extracts the six raw skeleton flags -- but only
  ever restating a fact the new site's own structured "ABOUT THE COMPONENT"
  block states (e.g. "Buttons: Yes, up to 2"), marking a count "not
  confirmed" (via None) when the source doesn't give one, same as every
  earlier enrichment pass in this project.

Usage:
    python scripts/build_catalog_v3.py [--merged PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, Field

from src import llm_provider
from src.llm_cost import Budget
from src.web_builder.catalog import build_field_skeleton

# This is a one-off, human-reviewed migration script (77 calls total, not
# the per-user runtime path match.py/populate.py run) -- so unlike those,
# it's worth spending a step up from the app's default cheap "fast"/"high"
# tier (both map to the same nano-ish model, e.g. gpt-4o-mini) for better
# instruction-following on the nuanced "does this specific component have
# its OWN repeatable children" judgment call. A smoke test on 3 components
# showed gpt-4o-mini repeatedly hallucinating a listing cap even given an
# explicit worked counterexample; a stronger model plus the deterministic
# `_derive_listing` regex fallback below is the fix.
STRONG_MODEL_BY_PROVIDER = {
    "claude": "claude-opus-5",
    "openai": "gpt-5.4-mini",
    "gemini": "gemini-3.1-pro",
}

CATALOG_PATH = ROOT / "config" / "components.json"
SCREENSHOT_DEST_DIR = ROOT / "dashboard-react" / "public" / "component-examples"
DEFAULT_MERGED_PATH = Path(
    r"C:\Users\ashza\AppData\Local\Temp\claude\C--Users-ashza-Downloads-MavDitto"
    r"\ee75377f-0483-4c72-b732-89025df4fcca\scratchpad\merged_raw.json"
)
SCREENSHOT_SRC_DIRS = {
    "old": DEFAULT_MERGED_PATH.parent / "old_site_shots",
    "new": DEFAULT_MERGED_PATH.parent / "new_site_shots",
}

# Same six renamed-pair mappings reconcile.py used, needed here to look up
# each merged "both"/"old only" component's EXISTING verified skeleton in
# today's config/components.json, which is keyed by the OLD site's spelling.
PAIRS = {
    "Datapoint Listings": "Datapoint Listing",
    "Hero With Link": "Hero with Link",
    "Announcement": "Announcement Items",
    "CTA Right Rail Listing Items": "CTA Right Rail Listing",
    "CTA Right Rail Quicklinks": "CTA Right Rail Quick Links",
    "Featured Interests": "Feature Interest",
}
NEW_TO_OLD_NAME = {v: k for k, v in PAIRS.items()}


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


_SYSTEM_PROMPT_EXISTING = """You update the catalog entry for a Sitecore web \
component in a university's design-system catalog. You are given that \
component's OLD documentation (from the previous design system) and, when \
available, its NEW documentation (from the current, richer design system) \
-- read both, but where they disagree or the new text is more specific, the \
NEW text wins.

Write:
1. `purpose`: one to three sentences on when and why an editor would reach \
for this component, and, when the text suggests a similarly-named or \
similarly-purposed alternative, what it's NOT for. Paraphrase only what the \
given text actually says -- never add a claim, use case, or constraint the \
text doesn't support.
2. `examples`: one or two short hypothetical pieces of content that would \
plausibly fit this component. These are invented illustrations, not claims \
about real UTA content -- keep them generic, no invented specific stats, \
names, or dates presented as real.
3. `special_features`: configuration-level parameters this component \
exposes beyond its basic content fields -- named options like "List Size", \
"Alternate Sides", "Highlighted Variant", a required exact count, a caution \
about not mixing with another component, etc. These usually appear (on the \
new site) under a "Page Details And Notes" heading, or (on either site) as \
a "Caution"/"Variation"/"Special Notes" callout. Only include a feature the \
text actually names and describes; leave this list empty if the text names \
none. Mark `importance` "critical" only when the text itself flags the \
feature as critical/most important/required to get right (e.g. text saying \
"MOST IMPORTANT"); everything else is "normal".
4. `visual_variant`: "new_look" if the text states this component follows \
(or defaults to) the new site's "new look" layout; "classic_look" if it \
states the classic/old layout; "unspecified" if the text doesn't say, or \
says this component offers BOTH as separate variants/options."""

_SYSTEM_PROMPT_NEW_ONLY = _SYSTEM_PROMPT_EXISTING + """

This component has no prior verified catalog entry, so you must ALSO \
extract its raw field facts -- but only ever restate a fact the "ABOUT THE \
COMPONENT" block (or equivalent structured text) already states; use None/ \
"not confirmed"-safe defaults (see field descriptions) when a fact isn't \
given:
- `category`: pick the single best-fit label from exactly this list: \
Global, Headers, News, Page Content, Sidebars, Special Use, Template \
Elements.
- `rich_text`: true only if the text says "Rich Text: Yes".
- `max_images`: the exact image count if the text gives one (e.g. \
"Images: Yes, 1" -> 1); if it just says "Images: Yes" with no count, use 1; \
if "Images: No" or unmentioned, use None.
- `max_buttons`: the exact button count if given (e.g. "up to 2" -> 2); if \
just "Buttons: Yes" with no count, use 1; if "No"/unmentioned, use None.
- `links_mode`: "not_supported" if the text says "Links: No"; "optional" if \
it says "Links: Yes" without saying required; "required" only if the text \
explicitly says a link is required; "none" if the text never mentions \
links at all.
- `links_max`: an exact link count if the text gives one, else None.
- `dynamic`: true only if the text says content is auto-populated from a \
folder/topic/tag rather than manually authored.
- `chrome`: true only if this is site-wide chrome (e.g. Header/Footer) with \
no authorable content fields at all.
- `shared_copy_unconfirmed`: true only if the text says this component's \
Title/Description fields inherit from the parent page rather than having \
their own."""


class SpecialFeatureOut(BaseModel):
    name: str
    description: str
    importance: Literal["critical", "normal"] = "normal"


class EnrichmentExisting(BaseModel):
    purpose: str
    examples: list[str] = Field(default_factory=list)
    special_features: list[SpecialFeatureOut] = Field(default_factory=list)
    visual_variant: Literal["new_look", "classic_look", "unspecified"] = "unspecified"


class EnrichmentNewOnly(EnrichmentExisting):
    category: str
    rich_text: bool = False
    max_images: int | None = None
    max_buttons: int | None = None
    links_mode: Literal["none", "optional", "required", "not_supported"] = "none"
    links_max: int | None = None
    dynamic: bool = False
    chrome: bool = False
    shared_copy_unconfirmed: bool = False


def _derive_listing(m: dict) -> tuple[str, int | None]:
    """Whether THIS component has its own repeatable children, derived
    deterministically rather than trusted to a cheap model's judgment --
    every new-only component's text was checked by hand and only a
    component with a "List Size"-style parameter for its OWN children (not
    a component that merely lives inside someone else's parent listing,
    e.g. "Component Location: Cards -> Foo Listing") qualifies. The cap
    itself is a page-editor's per-use choice, never a fixed schema
    constant, so `listing_max` always stays None here (matches the "never
    pad to a guessed number" rule already applied to List Size elsewhere)."""
    text = (m.get("new_text") or "") + "\n" + (m.get("old_text") or "")
    if re.search(r"list size", text, re.IGNORECASE):
        return "limited", None
    return "none", None


def _clip(text: str | None, limit: int = 6000) -> str:
    if not text:
        return "(not available)"
    return text if len(text) <= limit else text[:limit] + "\n...(truncated)"


def _prompt_for(m: dict) -> str:
    return (
        f"Component: {m['final_name']}\n"
        f"Present on: {', '.join(m['source_sites'])} site(s)\n\n"
        f"=== OLD SITE TEXT ===\n{_clip(m.get('old_text'))}\n\n"
        f"=== NEW SITE TEXT ===\n{_clip(m.get('new_text'))}\n"
    )


def _resolve_screenshot(m: dict) -> str | None:
    shot = m.get("screenshot")
    if not shot:
        return None
    src_dir = SCREENSHOT_SRC_DIRS.get(m.get("screenshot_source", "new"))
    src = src_dir / shot if src_dir else None
    if not src or not src.exists():
        print(f"  ! screenshot listed but file missing: {src}")
        return None
    return f"component-examples/{shot}"


def _copy_screenshots(merged: list[dict], dry_run: bool) -> None:
    if dry_run:
        return
    SCREENSHOT_DEST_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for m in merged:
        shot = m.get("screenshot")
        if not shot:
            continue
        src_dir = SCREENSHOT_SRC_DIRS.get(m.get("screenshot_source", "new"))
        src = src_dir / shot if src_dir else None
        if src and src.exists():
            shutil.copy2(src, SCREENSHOT_DEST_DIR / shot)
            copied += 1
    print(f"copied {copied} screenshot(s) to {SCREENSHOT_DEST_DIR}")


def build(merged_path: Path, dry_run: bool) -> None:
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    existing = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    existing_by_name = {c["name"]: c for c in existing["components"]}

    budget = Budget(max_usd=5.0, max_calls=len(merged) + 5)
    model = STRONG_MODEL_BY_PROVIDER.get(llm_provider.active_provider(), llm_provider.default_model("high"))

    out_components = []
    for i, m in enumerate(merged, start=1):
        final_name = m["final_name"]
        old_catalog_name = NEW_TO_OLD_NAME.get(final_name, final_name)
        prior = existing_by_name.get(old_catalog_name)
        is_new_only = prior is None
        schema = EnrichmentNewOnly if is_new_only else EnrichmentExisting
        prompt = _prompt_for(m)
        system = _SYSTEM_PROMPT_NEW_ONLY if is_new_only else _SYSTEM_PROMPT_EXISTING

        parsed = cost = None
        last_exc = None
        for attempt in range(2):
            try:
                parsed, cost = llm_provider.call_structured(
                    model, system, prompt, schema, budget,
                    max_output_tokens=4096, effort="medium", label="catalog v3 enrichment")
                break
            except Exception as exc:
                last_exc = exc
        if parsed is None:
            print(f"[{i}/{len(merged)}] {final_name}: FAILED twice ({last_exc}) -- minimal fallback")
            fallback_purpose = (m.get("new_text") or m.get("old_text") or "")[:200] or "Purpose not available from the crawl."
            if is_new_only:
                parsed = EnrichmentNewOnly(purpose=fallback_purpose, category="Special Use")
            else:
                parsed = EnrichmentExisting(purpose=fallback_purpose)
            cost = 0.0
        print(f"[{i}/{len(merged)}] {final_name}: ${cost:.5f} -- {parsed.purpose[:60]}...")

        if is_new_only:
            listing_mode, listing_max = _derive_listing(m)
            fields = build_field_skeleton(
                chrome=parsed.chrome, shared_copy_unconfirmed=parsed.shared_copy_unconfirmed,
                rich_text=parsed.rich_text, max_images=parsed.max_images, max_buttons=parsed.max_buttons,
                links_mode=parsed.links_mode, links_max=parsed.links_max,
                listing_mode=listing_mode, listing_max=listing_max,
                notes="",
            )
            category = parsed.category
            dynamic = parsed.dynamic
            chrome = parsed.chrome
            shared_copy_unconfirmed = parsed.shared_copy_unconfirmed
        else:
            fields = prior["fields"]
            category = prior["category"]
            dynamic = prior.get("dynamic", False)
            chrome = prior.get("chrome", False)
            shared_copy_unconfirmed = prior.get("sharedCopyUnconfirmed", False)

        out_components.append({
            "name": final_name,
            "category": category,
            "purpose": parsed.purpose,
            "fields": fields,
            "examples": parsed.examples,
            "dynamic": dynamic,
            "chrome": chrome,
            "sharedCopyUnconfirmed": shared_copy_unconfirmed,
            "visualVariant": parsed.visual_variant,
            "specialFeatures": [sf.model_dump() for sf in parsed.special_features],
            "screenshotAsset": _resolve_screenshot(m),
            "sourceSites": m["source_sites"],
        })

    print(f"\ntotal cost: ${budget.spent_usd:.4f} ({budget.calls} calls)")
    with_shots = sum(1 for c in out_components if c["screenshotAsset"])
    print(f"components: {len(out_components)}, with screenshot: {with_shots}")

    new_data = {
        "brand": existing["brand"],
        "version": "verified-live-3-reconciled-old-new",
        "source_note": (
            existing["source_note"] + " Reconciled with UTA's newer digital-design-system site on "
            "2026-09-28: components present on both sites merged into one record (new-site name/text "
            "wins per explicit precedence, old site fills gaps); old-only components carried over "
            "as-is; new-only components added fresh. Added visualVariant/specialFeatures/"
            "screenshotAsset/sourceSites -- special features and visual variant are the only "
            "additional model-written data, grounded in each component's own scraped 'Page Details "
            "And Notes'/'ABOUT THE COMPONENT' text, never invented."
        ),
        "components": out_components,
    }

    if dry_run:
        print("\n--dry-run: not writing to disk. Sample new-only entry:")
        sample = next((c for c in out_components if c["sourceSites"] == ["new"]), out_components[0])
        print(json.dumps(sample, indent=2, ensure_ascii=False))
        return

    CATALOG_PATH.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {CATALOG_PATH}")
    _copy_screenshots(merged, dry_run=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", type=Path, default=DEFAULT_MERGED_PATH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build(args.merged, dry_run=args.dry_run)
