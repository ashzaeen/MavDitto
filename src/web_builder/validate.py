"""Deterministic validation for Web Builder's populate step -- not an LLM
judgment call. Two levels: `validate_component` checks one populate call's
raw output against its own component's fields[] (used inside
`populate.py`'s retry loop, and to explain an unresolved `needs_review`
status); `validate_populated` summarizes across a whole plan for the
reviewer-facing problems list.
"""

from __future__ import annotations

import re

from .models import ComponentSpec, PopulatedComponent

_MAX_COUNT_RE = re.compile(r"(?:up to|max)\s+(\d+)", re.IGNORECASE)


def validate_component(component: ComponentSpec, out_by_name: dict, section) -> list[str]:
    """`out_by_name` maps field name -> a `populate.PopulatedFieldOutput`.
    Only checks what the catalog's own fields[] and the section's real
    links actually support checking -- no claim either way past that."""
    problems: list[str] = []
    link_urls = {link.url for link in section.links}

    for f in component.fields:
        out = out_by_name.get(f.name)
        if out is None:
            problems.append(f"{f.name}: no value returned for this field")
            continue
        if out.skipped:
            continue

        if f.field_type == "link":
            if not (out.url or "").strip():
                problems.append(
                    f"{f.name}: not skipped, but has no URL -- either use one of the "
                    "section's real links or mark this field skipped")
            elif link_urls and out.url not in link_urls:
                problems.append(f"{f.name}: url {out.url!r} is not one of the section's actual links")

        if f.field_type == "button":
            buttons = getattr(out, "buttons", None) or []
            if not buttons:
                problems.append(
                    f"{f.name}: not skipped, but no buttons were returned -- either use one of "
                    "the section's real links or mark this field skipped")
            else:
                m = _MAX_COUNT_RE.search(f.constraints)
                if m and len(buttons) > int(m.group(1)):
                    problems.append(
                        f"{f.name}: {len(buttons)} button(s) returned, but this component "
                        f"supports at most {m.group(1)}")
                for b in buttons:
                    url = getattr(b, "url", "") or ""
                    if not url.strip():
                        problems.append(f"{f.name}: a button has no URL -- either use one of "
                                        "the section's real links or omit it")
                    elif link_urls and url not in link_urls:
                        problems.append(f"{f.name}: button url {url!r} is not one of the section's actual links")
                    if not (getattr(b, "text", "") or "").strip():
                        problems.append(f"{f.name}: a button needs a label")

        if f.field_type == "enum" and f.allowed_values and out.enum_value not in f.allowed_values:
            problems.append(f"{f.name}: {out.enum_value!r} is not one of the allowed values {f.allowed_values}")

        if f.field_type == "listing":
            items = getattr(out, "list_items", None) or []
            m = _MAX_COUNT_RE.search(f.constraints)
            if m and len(items) > int(m.group(1)):
                problems.append(f"{f.name}: {len(items)} item(s) returned, but this component supports at most {m.group(1)}")
            bad_urls = [item.url for item in items if item.url and link_urls and item.url not in link_urls]
            if bad_urls:
                problems.append(f"{f.name}: item url(s) {bad_urls} are not one of the section's actual links")

    return problems


def validate_populated(populated: list[PopulatedComponent]) -> list[str]:
    """A short, reviewer-facing summary -- the field-level detail already
    lives on each component's own `warnings`/`status`; this just flags
    which components still need a human look."""
    return [
        f"{pc.component}: needs review -- {'; '.join(pc.warnings) or 'a constraint could not be resolved'}"
        for pc in populated if pc.status == "needs_review"
    ]
