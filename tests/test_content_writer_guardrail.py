from types import SimpleNamespace

from src.content_writer.guardrail import GuardrailResult, check
from src.content_writer.models import Section, StructuredContent
from src.content_writer.rewrite import load_brand_voice
from src.llm_cost import Budget

BRAND_VOICE = load_brand_voice()


def _usage():
    return SimpleNamespace(input_tokens=500, output_tokens=100,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class StubClient:
    def __init__(self, result: GuardrailResult):
        self.result = result
        self.calls = 0
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=500)

    def _parse(self, **kw):
        self.calls += 1
        return SimpleNamespace(parsed_output=self.result, usage=_usage(), stop_reason="end_turn")


def _content():
    return StructuredContent(
        page_title="T", register="institutional",
        sections=[Section(heading="H", body="B", kind="body")])


def test_a_passing_review_reports_no_issues():
    client = StubClient(GuardrailResult(passes=True, issues=[]))
    result = check(_content(), BRAND_VOICE, budget=Budget(), client=client, model="claude-opus-5")
    assert result.passes
    assert result.issues == []


def test_a_failing_review_reports_specific_issues():
    client = StubClient(GuardrailResult(passes=False, issues=["Section 0 uses slang."]))
    result = check(_content(), BRAND_VOICE, budget=Budget(), client=client, model="claude-opus-5")
    assert not result.passes
    assert "slang" in result.issues[0]


def test_the_guardrail_calls_cost_is_added_to_the_content():
    content = _content()
    assert content.cost_usd == 0.0
    client = StubClient(GuardrailResult(passes=True, issues=[]))
    check(content, BRAND_VOICE, budget=Budget(), client=client, model="claude-opus-5")
    assert content.cost_usd > 0.0
