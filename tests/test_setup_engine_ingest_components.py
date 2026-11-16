from types import SimpleNamespace

import pytest

from src.content_writer.pipeline import ContentInput
from src.llm_cost import Budget
from src.setup_engine.ingest_components import (
    ComponentCatalogOutput, ComponentOutput, ingest_components,
)


def _usage():
    return SimpleNamespace(input_tokens=500, output_tokens=200,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class StubClient:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = 0
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=500)

    def _parse(self, **kw):
        self.calls += 1
        return SimpleNamespace(parsed_output=self.parsed, usage=_usage(), stop_reason="end_turn")


def _output():
    return ComponentCatalogOutput(components=[
        ComponentOutput(
            name="Hero Banner", category="Headers",
            purpose="A page-opening header with a single background image.",
            examples=["A campus photo with a welcome title."],
            rich_text=False, max_images=1,
            max_buttons=None, links_mode="none", links_max=None,
            listing_mode="not_supported", listing_max=None, notes="",
            dynamic=False, chrome=False),
        ComponentOutput(
            name="News Feed", category="News", purpose="Auto-pulls recent articles from a folder.",
            examples=[], rich_text=False, max_images=None,
            max_buttons=None, links_mode="none", links_max=None,
            listing_mode="limited", listing_max=6, notes="auto-pulls from a folder",
            dynamic=True, chrome=False),
    ])


def test_ingest_components_returns_the_expected_config_shape():
    client = StubClient(_output())
    draft = ingest_components(
        [ContentInput(kind="markdown", data=b"# Components\n\nHero Banner: 1 image.\n")],
        budget=Budget(), client=client, model="claude-opus-5")

    names = {c["name"] for c in draft["components"]}
    assert names == {"Hero Banner", "News Feed"}
    hero = next(c for c in draft["components"] if c["name"] == "Hero Banner")
    assert hero["purpose"] == "A page-opening header with a single background image."
    assert hero["examples"] == ["A campus photo with a welcome title."]
    image_field = next(f for f in hero["fields"] if f["fieldType"] == "image")
    assert "max 1 image" in image_field["constraints"]
    news = next(c for c in draft["components"] if c["name"] == "News Feed")
    assert news["dynamic"] is True
    listing_field = next(f for f in news["fields"] if f["fieldType"] == "listing" and f["name"] == "Listing item")
    assert "6" in listing_field["constraints"]
    assert client.calls == 1


def test_ingest_components_defaults_shared_copy_unconfirmed_to_false():
    client = StubClient(_output())
    draft = ingest_components(
        [ContentInput(kind="markdown", data=b"# Components\n\nSome content.\n")],
        budget=Budget(), client=client, model="claude-opus-5")
    assert all(c["sharedCopyUnconfirmed"] is False for c in draft["components"])


def test_ingest_components_chrome_component_gets_an_empty_field_skeleton():
    output = ComponentCatalogOutput(components=[
        ComponentOutput(
            name="Footer", category="Global", purpose="Site-wide footer.", examples=[],
            rich_text=False, max_images=None, max_buttons=None, links_mode="unspecified",
            links_max=None, listing_mode="not_supported", listing_max=None, notes="",
            dynamic=False, chrome=True),
    ])
    client = StubClient(output)
    draft = ingest_components(
        [ContentInput(kind="markdown", data=b"# Components\n\nFooter.\n")],
        budget=Budget(), client=client, model="claude-opus-5")
    footer = next(c for c in draft["components"] if c["name"] == "Footer")
    assert footer["fields"] == []


def test_ingest_components_raises_when_material_has_no_readable_text():
    client = StubClient(_output())
    with pytest.raises(RuntimeError, match="no readable text"):
        ingest_components([ContentInput(kind="markdown", data=b"")], budget=Budget(), client=client)
    assert client.calls == 0
