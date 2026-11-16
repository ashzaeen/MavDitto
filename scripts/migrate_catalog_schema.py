"""One-off migration: config/components.json's flat schema (richText,
maxImages, maxButtons, links{mode,max}, listing{mode,max}) -> the richer
per-field schema Web Builder v2 needs (purpose, fields[] with fieldType +
constraints + notes, examples).

Not part of the running app -- run once, review the diff, commit the
result. Re-run only if the source catalog is re-verified against the live
design system again.

Design: the field *skeleton* (which fields exist, their fieldType, their
constraints) is built deterministically from the six flags already
verified live -- never invented by a model. The one thing genuinely worth
an LLM call per component is prose: a `purpose` paragraph and 1-2
`examples`, both grounded in that component's own `notes`/`category`/name
(the same "don't claim what the input doesn't state" discipline already
used in `setup_engine/ingest_components.py`), not freely generated.

Usage:
    python scripts/migrate_catalog_schema.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, Field

from src import llm_provider
from src.llm_cost import Budget
from src.web_builder.catalog import build_field_skeleton

CATALOG_PATH = ROOT / "config" / "components.json"

_SYSTEM_PROMPT = """You write two things about a Sitecore web component for a \
university's design system catalog, using ONLY the facts given to you --\
category, existing usage notes, and its known field constraints.

1. `purpose`: one to three sentences describing when and why an editor \
would reach for this specific component -- what it's good for, and, when \
the notes suggest a similarly-named or similarly-purposed alternative, what \
it's NOT for (so the two aren't confused). Paraphrase and clarify the given \
notes; never add a claim, a use case, or a constraint the notes don't \
already support.

2. `examples`: one or two short, illustrative pieces of content that would \
plausibly fit this component, grounded in its actual purpose and category. \
These are invented illustrations for a catalog reader's benefit, not claims \
about real UTA content -- keep them generic and clearly hypothetical \
(no invented specific statistics, names, or dates presented as if real)."""


class ComponentEnrichment(BaseModel):
    purpose: str = Field(description="1-3 sentences, grounded only in the given notes/category.")
    examples: list[str] = Field(
        description="1-2 short hypothetical examples of content that fits this component.")


def _skeleton_for(c: dict) -> list[dict]:
    links = c.get("links") or {}
    listing = c.get("listing") or {}
    return build_field_skeleton(
        chrome=c.get("chrome", False), shared_copy_unconfirmed=c.get("sharedCopyUnconfirmed", False),
        rich_text=c["richText"], max_images=c.get("maxImages"), max_buttons=c.get("maxButtons"),
        links_mode=links.get("mode"), links_max=links.get("max"),
        listing_mode=listing.get("mode"), listing_max=listing.get("max"),
        notes=c.get("notes", ""),
    )


def _prompt_for(c: dict) -> str:
    return (
        f"Name: {c['name']}\n"
        f"Category: {c['category']}\n"
        f"Existing usage notes: {c.get('notes') or '(none given)'}\n"
        f"Supports rich text: {c['richText']}\n"
        f"Max images: {c.get('maxImages')}\n"
        f"Max buttons: {c.get('maxButtons')}\n"
        f"Links: {c.get('links')}\n"
        f"Listing: {c.get('listing')}\n"
        f"Auto-populated (dynamic): {c.get('dynamic')}\n"
    )


def migrate(dry_run: bool = False) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    components = data["components"]
    budget = Budget(max_usd=3.0, max_calls=len(components) + 5)
    model = llm_provider.default_model("fast")

    migrated = []
    for i, c in enumerate(components, start=1):
        fields = _skeleton_for(c)
        parsed = cost = None
        last_exc = None
        for attempt in range(2):
            try:
                parsed, cost = llm_provider.call_structured(
                    model, _SYSTEM_PROMPT, _prompt_for(c), ComponentEnrichment, budget,
                    max_output_tokens=768, label="catalog migration")
                break
            except Exception as exc:  # a garbled/truncated response from a cheap model
                last_exc = exc
        if parsed is None:
            print(f"[{i}/{len(components)}] {c['name']}: FAILED twice ({last_exc}) -- using notes as purpose")
            first_sentence = (c.get("notes") or "").split(". ")[0].strip() or "Purpose not available from the crawl notes."
            parsed = ComponentEnrichment(purpose=first_sentence, examples=[])
            cost = 0.0
        print(f"[{i}/{len(components)}] {c['name']}: ${cost:.5f} -- {parsed.purpose[:70]}...")

        migrated.append({
            "name": c["name"],
            "category": c["category"],
            "purpose": parsed.purpose,
            "fields": fields,
            "examples": parsed.examples,
            "dynamic": c.get("dynamic", False),
            "chrome": c.get("chrome", False),
            "sharedCopyUnconfirmed": c.get("sharedCopyUnconfirmed", False),
        })

    print(f"\ntotal cost: ${budget.spent_usd:.4f} ({budget.calls} calls)")

    new_data = {
        "brand": data["brand"],
        "version": "verified-live-2-typed-fields",
        "source_note": (
            data["source_note"] + " Migrated to a per-field schema (purpose/fields[]/examples) on "
            "2026-09-28 -- field skeletons (fieldType, constraints) are derived deterministically "
            "from the same six verified flags this file always had, never invented by a model; "
            "`purpose` and `examples` are the only model-written text, grounded in each "
            "component's own crawled notes."
        ),
        "components": migrated,
    }

    if dry_run:
        print("\n--dry-run: not writing to disk. Sample entry:")
        print(json.dumps(migrated[0], indent=2))
        return

    CATALOG_PATH.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {CATALOG_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the first result instead of writing to disk")
    args = ap.parse_args()
    migrate(dry_run=args.dry_run)
