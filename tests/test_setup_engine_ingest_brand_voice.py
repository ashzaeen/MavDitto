from types import SimpleNamespace

import pytest

from src.content_writer.pipeline import ContentInput
from src.llm_cost import Budget
from src.setup_engine.ingest_brand_voice import (
    BrandVoiceOutput, RegisterOutput, ingest_brand_voice,
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
    return BrandVoiceOutput(
        brand="Acme University",
        registers=[
            RegisterOutput(key="institutional", label="Institutional", used_for=["policy"],
                          description="Formal, third-person.", example="Acme is committed to..."),
        ],
        shared_principles=["plain vocabulary"],
        seed_system_prompt="Write formally for policy content.",
        guardrail_floor_description="Never generic AI copy.",
        guardrail_checks=["no slang"],
    )


def test_ingest_brand_voice_returns_the_expected_config_shape():
    client = StubClient(_output())
    draft = ingest_brand_voice(
        [ContentInput(kind="markdown", data=b"# About\n\nAcme is committed to excellence.\n")],
        budget=Budget(), client=client, model="claude-opus-5")

    assert draft["brand"] == "Acme University"
    assert "institutional" in draft["registers"]
    assert draft["registers"]["institutional"]["label"] == "Institutional"
    assert draft["tone_options"] == ["Warmer", "More formal", "More concise", "More detailed"]
    assert draft["guardrail"]["floor_description"] == "Never generic AI copy."
    assert client.calls == 1


def test_ingest_brand_voice_raises_when_material_has_no_readable_text():
    client = StubClient(_output())
    with pytest.raises(RuntimeError, match="no readable text"):
        ingest_brand_voice([ContentInput(kind="markdown", data=b"")], budget=Budget(), client=client)
    assert client.calls == 0


def test_ingest_brand_voice_accepts_multiple_material_inputs():
    client = StubClient(_output())
    draft = ingest_brand_voice(
        [
            ContentInput(kind="markdown", data=b"# Page 1\n\nFirst sample.\n"),
            ContentInput(kind="markdown", data=b"# Page 2\n\nSecond sample.\n"),
        ],
        budget=Budget(), client=client, model="claude-opus-5")
    assert draft["brand"] == "Acme University"
    assert client.calls == 1
