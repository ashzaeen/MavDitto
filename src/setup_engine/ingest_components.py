"""Freeform component-library material -> a draft config/components.json
shape.

Accepts whatever the person uploads (docs, screenshots, or a link to a live
design-system/component-library page) with no structured template required --
this is exactly the same freeform-ingestion job as brand voice, just aimed at
a different structured shape. A screenshot goes through the same vision
extraction Content Writer uses for an uploaded image; a link goes through the
same URL extraction.

Like `ingest_brand_voice`, this returns a *draft* for a review screen --
inferred component constraints (an exact-count field, a hard cap) are exactly
the kind of thing that's cheap to get wrong silently and expensive to get
wrong in a live CMS, per the design doc.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..content_writer.pipeline import ContentInput, extract_content
from ..content_writer.rewrite import _call, _default_model
from ..llm_cost import Budget
from ..web_builder.catalog import build_field_skeleton

MAX_OUTPUT_TOKENS = 8192

_SYSTEM_PROMPT = """You study documentation, screenshots, or a live page \
describing a CMS's component library, and infer a structured catalog \
another tool will use to decide which component fits which content and how \
to populate it.

For every constraint field (max_images, max_buttons, links_mode, links_max, \
listing_mode, listing_max), apply this rule: only fill in a number or a \
specific mode if the material actually states or clearly shows it. If it is \
not stated, use the "unstated"/"unspecified"/null option that field allows -- \
a guessed-but-wrong number is worse than an honest gap, since a downstream \
tool will trust it as fact. Example: the material says a component "supports \
images" with no count given -> max_images is null, NOT a guessed number like \
1 or 4. The material says "up to 3 images" -> max_images is 3.

Flag any component that pulls content automatically (a news feed, an \
auto-populated listing) as dynamic, since those must never receive manually \
authored copy. Flag any component that has no fields of its own and instead \
inherits from a parent page's title/description as shared-copy.

Also write, per component: `purpose` (1-3 sentences on when and why an \
editor would reach for this specific component, grounded only in what the \
material actually says -- if it distinguishes this component from a \
similarly-named one, say how) and `examples` (1-2 short, clearly \
hypothetical pieces of content that would fit it -- illustrations for a \
catalog reader, never claims about real content from the material)."""


class ComponentOutput(BaseModel):
    name: str
    category: str = Field(description="A grouping label, e.g. 'Headers', 'Page Content', 'Sidebars'.")
    purpose: str = Field(description="1-3 sentences, grounded only in what the material states.")
    examples: list[str] = Field(default_factory=list, description="1-2 short hypothetical examples.")
    rich_text: bool = Field(description="True if the component's body field supports rich text/HTML.")
    max_images: int | None = Field(description="Max images this component supports, or null if unstated/unsupported.")
    max_buttons: int | None = Field(description="Max buttons, or null if unstated/unsupported.")
    links_mode: str = Field(description="One of: none, required, optional, unspecified.")
    links_max: int | None = Field(description="A stated max link count, or null.")
    listing_mode: str = Field(description="One of: unlimited, limited, not_supported, unspecified.")
    listing_max: int | None = Field(description="A stated max listed-item count, or null.")
    notes: str = Field(description="Any other real constraint or usage note from the material.")
    dynamic: bool = Field(description="True if this component auto-populates rather than taking manual copy.")
    chrome: bool = Field(description="True if this is site-wide structural chrome (a header/footer) with no authorable fields.")


class ComponentCatalogOutput(BaseModel):
    components: list[ComponentOutput]


def _extract_material_text(inputs: list[ContentInput], *, fetcher=None) -> str:
    parts = []
    for input_ in inputs:
        extracted = extract_content(input_, fetcher=fetcher)
        if not extracted.sections:
            continue
        parts.append(f"=== {extracted.page_title} ===")
        for section in extracted.sections:
            if section.heading:
                parts.append(section.heading)
            parts.append(section.body)
            if section.media_refs:
                parts.append("Media noted: " + "; ".join(section.media_refs))
    return "\n\n".join(parts)


def ingest_components(inputs: list[ContentInput], *, fetcher=None,
                      budget: Budget | None = None, model: str | None = None,
                      client=None) -> dict:
    """Returns a draft components.json-shaped dict -- not yet saved."""
    budget = budget or Budget()
    model = model or _default_model()
    material = _extract_material_text(inputs, fetcher=fetcher)
    if not material.strip():
        raise RuntimeError("no readable text was found in the uploaded material")

    prompt = (
        "Component-library material:\n\n"
        f"{material}\n\n"
        "Infer a structured component catalog from this material."
    )
    parsed, cost = _call(model, _SYSTEM_PROMPT, prompt, ComponentCatalogOutput, budget, client=client)

    components = [
        {
            "name": c.name, "category": c.category, "purpose": c.purpose,
            "fields": build_field_skeleton(
                chrome=c.chrome, shared_copy_unconfirmed=False, rich_text=c.rich_text,
                max_images=c.max_images, max_buttons=c.max_buttons,
                links_mode=c.links_mode, links_max=c.links_max,
                listing_mode=c.listing_mode, listing_max=c.listing_max, notes=c.notes,
            ),
            "examples": c.examples, "dynamic": c.dynamic, "chrome": c.chrome,
            "sharedCopyUnconfirmed": False,
        }
        for c in parsed.components
    ]
    return {
        "brand": None,
        "version": "inferred-1",
        "source_note": "Inferred by the setup engine from uploaded material -- review before saving.",
        "components": components,
        "cost_usd": cost,
    }
