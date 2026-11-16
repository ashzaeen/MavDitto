"""Orchestrates Web Builder: match -> plan (Phase 1); separately,
populate -> validate (Phase 2). The approval step in between the two phases
is UI-driven, not code -- see the design doc's Phase 1/Phase 2 split.
"""

from __future__ import annotations

from .. import llm_provider
from ..content_writer.models import StructuredContent
from ..llm_cost import Budget
from ..content_writer.rewrite import load_brand_voice
from .catalog import by_name, load_catalog
from .match import build_plan
from .models import LayoutPlan, PopulatedComponent
from .populate import _populate_row, _system_prompt, populate_plan
from .validate import validate_populated


def make_plan(content: StructuredContent, *, budget: Budget | None = None,
              model: str | None = None, client=None) -> LayoutPlan:
    catalog = load_catalog()
    return build_plan(content, catalog, budget=budget, model=model, client=client)


def populate_approved_plan(content: StructuredContent, plan: LayoutPlan, *,
                           budget: Budget | None = None, model: str | None = None,
                           client=None) -> tuple[list[PopulatedComponent], list[str]]:
    catalog = load_catalog()
    catalog_by_name = by_name(catalog)
    populated = populate_plan(content, plan, catalog_by_name, budget=budget, model=model, client=client)
    problems = validate_populated(populated)
    return populated, problems


def populate_one_component(content: StructuredContent, row, *,
                           budget: Budget | None = None, model: str | None = None,
                           client=None) -> PopulatedComponent:
    """Regenerate a single approved row -- the per-card "Regenerate this
    component" action, cheap because population is already one call per
    component, not per page."""
    catalog = load_catalog()
    catalog_by_name = by_name(catalog)
    budget = budget or Budget()
    model = model or llm_provider.default_model("medium")
    system_prompt = _system_prompt(load_brand_voice())
    populated, cost = _populate_row(
        content, row, catalog_by_name.get(row.component), budget=budget, model=model,
        client=client, system_prompt=system_prompt)
    content.cost_usd += cost
    return populated
