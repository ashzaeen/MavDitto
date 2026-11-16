"""Loads config/components.json -- the single source of truth both the
matcher and the populator read from."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import ComponentSpec

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "components.json"

_CHAR_LIMIT_RE = re.compile(r"(\d+)\s*char", re.IGNORECASE)


def build_field_skeleton(*, chrome: bool, shared_copy_unconfirmed: bool, rich_text: bool,
                        max_images: int | None, max_buttons: int | None,
                        links_mode: str | None, links_max: int | None,
                        listing_mode: str | None, listing_max: int | None,
                        notes: str = "") -> list[dict]:
    """A component's `fields[]`, built deterministically from the six raw
    signals every catalog source ultimately produces -- the live verified
    crawl (see `scripts/migrate_catalog_schema.py`) and the setup engine's
    freeform inference (`ingest_components.py`) both funnel through this
    same function, so fieldType/constraints are never invented by a model
    in either path, only derived from flags a model (or a human) already
    committed to."""
    if chrome:
        return []

    inherits_note = ("inherits from the parent page's field, not its own -- "
                     "unconfirmed by the public catalog") if shared_copy_unconfirmed else ""
    char_match = _CHAR_LIMIT_RE.search(notes or "")
    char_limit = char_match.group(1) if char_match else None

    fields: list[dict] = [
        {
            "name": "Page Title" if shared_copy_unconfirmed else "Title",
            "fieldType": "plaintext", "constraints": "not confirmed", "notes": inherits_note,
        },
        {
            "name": "Page Description" if shared_copy_unconfirmed else ("Body" if rich_text else "Description"),
            "fieldType": "richtext" if rich_text else "plaintext",
            "constraints": f"{char_limit} char (from crawl notes)" if char_limit else "not confirmed",
            "notes": inherits_note,
        },
    ]

    if max_buttons:
        fields.append({
            "name": "Button", "fieldType": "button",
            "constraints": f"max {max_buttons} button(s); allowed color(s) not confirmed by the public catalog",
            "notes": "",
        })

    if links_mode not in (None, "none", "not_supported"):
        constraint = f"max {links_max}" if links_max is not None else (
            "required, max not confirmed" if links_mode == "required" else "optional, max not confirmed")
        fields.append({
            "name": "Link", "fieldType": "link", "constraints": constraint,
            "notes": f"link mode: {links_mode}",
        })

    if max_images:
        fields.append({
            "name": "Image" if max_images == 1 else f"Image (up to {max_images})",
            "fieldType": "image",
            "constraints": f"max {max_images} image(s), never confirmed as an exact requirement by the public catalog",
            "notes": "alt text is populated via the Alt Text tool, not this pipeline",
        })

    if listing_mode in ("limited", "unlimited"):
        constraint = f"up to {listing_max} item(s)" if listing_max is not None else "unlimited items"
        fields.append({
            "name": "Listing item", "fieldType": "listing", "constraints": constraint,
            "notes": "repeatable child item -- populated as one entry per item the section's "
                     "content actually contains, never padded to hit a cap",
        })

    return fields


def load_catalog(path: Path = CONFIG_PATH) -> list[ComponentSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ComponentSpec.from_dict(c) for c in data["components"]]


def content_components(catalog: list[ComponentSpec]) -> list[ComponentSpec]:
    """Components that can actually receive manually authored copy --
    excludes `dynamic` (auto-populated from a folder/topic) and `chrome`
    (Header/Footer, no authorable fields at all)."""
    return [c for c in catalog if not c.dynamic and not c.chrome]


def dynamic_components(catalog: list[ComponentSpec]) -> list[ComponentSpec]:
    return [c for c in catalog if c.dynamic]


def by_name(catalog: list[ComponentSpec]) -> dict[str, ComponentSpec]:
    return {c.name: c for c in catalog}
