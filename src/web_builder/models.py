"""Data shapes for Web Builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# What `populate.py` needs to know to render/validate a field correctly --
# see `scripts/migrate_catalog_schema.py` for how config/components.json's
# fields[] entries are built (deterministically, from the same six flags
# the catalog always verified live; never invented by a model).
FIELD_TYPES = ("richtext", "plaintext", "link", "button", "image", "enum", "date", "listing")


@dataclass
class ComponentField:
    name: str
    field_type: str          # one of FIELD_TYPES
    constraints: str         # e.g. "max 4 image(s), ...", "not confirmed"
    notes: str = ""
    allowed_values: list[str] = field(default_factory=list)  # only meaningful for fieldType == "enum"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "fieldType": self.field_type,
            "constraints": self.constraints, "notes": self.notes,
            "allowedValues": self.allowed_values,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComponentField":
        return cls(
            name=d["name"], field_type=d["fieldType"], constraints=d.get("constraints", ""),
            notes=d.get("notes", ""), allowed_values=list(d.get("allowedValues", [])),
        )


VISUAL_VARIANTS = ("new_look", "classic_look", "unspecified")


@dataclass
class SpecialFeature:
    """A component-level configuration parameter that isn't a content field
    to type into (e.g. Left Image Vertical Listing's "List Size") -- see
    `scripts/build_catalog_v3.py` for how these were extracted, grounded
    only in each component's own scraped 'Page Details And Notes'/'Special
    Notes' text, never invented."""

    name: str
    description: str
    importance: str = "normal"   # "critical" | "normal"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "importance": self.importance}

    @classmethod
    def from_dict(cls, d: dict) -> "SpecialFeature":
        return cls(name=d["name"], description=d.get("description", ""), importance=d.get("importance", "normal"))


@dataclass
class ComponentSpec:
    """One catalog entry -- see config/components.json (generated
    locally by the Setup Wizard; see config/README.md) for where the
    underlying data comes from, and `scripts/migrate_catalog_schema.py` /
    `scripts/build_catalog_v3.py` for how it was reshaped and reconciled
    across UTA's old and new design-system sites. `dynamic`/`chrome`/
    `shared_copy_unconfirmed` stay component-level flags (not per-field)."""

    name: str
    category: str
    purpose: str
    fields: list[ComponentField]
    examples: list[str]
    dynamic: bool
    chrome: bool
    shared_copy_unconfirmed: bool
    visual_variant: str = "unspecified"   # one of VISUAL_VARIANTS
    special_features: list[SpecialFeature] = field(default_factory=list)
    screenshot_asset: str | None = None   # relative path under dashboard-react/public/
    source_sites: list[str] = field(default_factory=list)  # "old" and/or "new"

    def field_of_type(self, field_type: str) -> ComponentField | None:
        return next((f for f in self.fields if f.field_type == field_type), None)

    def has_field_type(self, field_type: str) -> bool:
        return any(f.field_type == field_type for f in self.fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "category": self.category, "purpose": self.purpose,
            "fields": [f.to_dict() for f in self.fields], "examples": self.examples,
            "dynamic": self.dynamic, "chrome": self.chrome,
            "sharedCopyUnconfirmed": self.shared_copy_unconfirmed,
            "visualVariant": self.visual_variant,
            "specialFeatures": [sf.to_dict() for sf in self.special_features],
            "screenshotAsset": self.screenshot_asset, "sourceSites": self.source_sites,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComponentSpec":
        return cls(
            name=d["name"], category=d["category"], purpose=d.get("purpose", ""),
            fields=[ComponentField.from_dict(f) for f in d.get("fields", [])],
            examples=list(d.get("examples", [])),
            dynamic=d.get("dynamic", False), chrome=d.get("chrome", False),
            shared_copy_unconfirmed=d.get("sharedCopyUnconfirmed", False),
            visual_variant=d.get("visualVariant", "unspecified"),
            special_features=[SpecialFeature.from_dict(sf) for sf in d.get("specialFeatures", [])],
            screenshot_asset=d.get("screenshotAsset"),
            source_sites=list(d.get("sourceSites", [])),
        )


@dataclass
class LayoutPlanRow:
    order: int
    component: str
    # Empty list for a dynamic-placement suggestion, tied to no section.
    # Normally one index; more than one when several sections were grouped
    # into a single component (e.g. three short lists folded into one
    # Accordion, each its own item) -- see match.py's grouping instructions.
    section_indices: list[int]
    maps_to: str                 # human-readable description of what maps here (joined when grouped)
    rationale: str
    alternatives: list[str] = field(default_factory=list)  # other valid component names, for swap

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order, "component": self.component,
            "sectionIndices": self.section_indices, "mapsTo": self.maps_to,
            "rationale": self.rationale, "alternatives": self.alternatives,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayoutPlanRow":
        return cls(
            order=int(d.get("order") or 0), component=d.get("component", ""),
            section_indices=list(d.get("sectionIndices", [])), maps_to=d.get("mapsTo", ""),
            rationale=d.get("rationale", ""), alternatives=list(d.get("alternatives", [])),
        )


@dataclass
class LayoutPlan:
    rows: list[LayoutPlanRow] = field(default_factory=list)
    unmatched_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"rows": [r.to_dict() for r in self.rows], "unmatchedNotes": self.unmatched_notes}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayoutPlan":
        return cls(
            rows=[LayoutPlanRow.from_dict(r) for r in d.get("rows", [])],
            unmatched_notes=list(d.get("unmatchedNotes", [])),
        )


@dataclass
class PopulatedField:
    """One populated field, shaped by `field_type` (see FIELD_TYPES) --
    only the payload attributes relevant to that type are meaningful;
    the rest stay at their default. `skipped` means the source section had
    nothing for this field (never filled with an invented value)."""

    name: str
    field_type: str
    is_page_level: bool = False   # per a sharedCopyUnconfirmed component
    skipped: bool = False
    text: str = ""                 # plaintext / richtext value
    url: str = ""                  # link destination
    role_note: str = ""            # image
    alt_text_handoff: bool = False  # image -- true means "hand off to the Alt Text tool"
    enum_value: str = ""           # enum
    char_limit: int | None = None  # plaintext/richtext, only when a real limit is known
    list_items: list[dict] = field(default_factory=list)  # repeatable listing field, one dict per item
    buttons: list[dict] = field(default_factory=list)      # repeatable button field, one dict per button

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "fieldType": self.field_type, "isPageLevel": self.is_page_level,
            "skipped": self.skipped, "text": self.text, "url": self.url,
            "roleNote": self.role_note,
            "altTextHandoff": self.alt_text_handoff, "enumValue": self.enum_value,
            "charLimit": self.char_limit, "listItems": self.list_items, "buttons": self.buttons,
        }


@dataclass
class PopulatedComponent:
    component: str
    section_indices: list[int]   # empty for a structural/dynamic row -- see LayoutPlanRow
    fields: list[PopulatedField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "valid"   # "valid" | "adjusted" | "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component, "sectionIndices": self.section_indices,
            "fields": [f.to_dict() for f in self.fields], "warnings": self.warnings,
            "status": self.status,
        }
