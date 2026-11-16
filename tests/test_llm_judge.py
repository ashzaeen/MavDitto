"""Judge tests, run against a stub client.

No network and no credentials: every test drives a fake that mimics the SDK's
shapes (`messages.parse` returning `.parsed_output` / `.usage` / `.stop_reason`,
`messages.count_tokens` returning `.input_tokens`). That covers selection,
budgeting, caching and error translation. What it cannot cover is whether the
real model returns good verdicts -- that needs credentials and a live run.
"""

from types import SimpleNamespace

import pytest

from src.llm_judge import (
    NO_CREDENTIALS_MESSAGE, Budget, BudgetExceeded, Judge, JudgeCache,
    PageJudgement, PassageVerdict, build_prompt, is_credentials_error,
    select_passages, should_judge,
)


def _usage(input_tokens=1000, output_tokens=200, cached=0):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0,
                           cache_read_input_tokens=cached)


class StubClient:
    """Mimics the SDK surface the judge touches."""

    def __init__(self, judgement=None, raises=None, input_tokens=1000):
        self.judgement = judgement or PageJudgement(
            summary="The fee figure was dropped.", severity="major",
            passages=[PassageVerdict(index=1, verdict="facts_lost",
                                     detail="The $75 application fee is gone.")])
        self.raises = raises
        self.input_tokens = input_tokens
        self.calls = 0
        self.last_kwargs = None
        self.messages = SimpleNamespace(parse=self._parse,
                                        count_tokens=self._count)

    def _count(self, **kwargs):
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(input_tokens=self.input_tokens)

    def _parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(parsed_output=self.judgement, usage=_usage(),
                               stop_reason="end_turn")


def _judge(tmp_path, client=None, **kw) -> Judge:
    kw.setdefault("model", "claude-opus-5")
    judge = Judge(cache=JudgeCache(tmp_path / "cache"), **kw)
    judge._client = client if client is not None else StubClient()
    return judge


PASSAGES = [
    {"verdict": "reworded", "similarity": 0.60, "section": "Fees",
     "old_text": "The application fee is 75 dollars and is non-refundable.",
     "new_text": "A fee applies when you submit your application."},
    {"verdict": "kept", "similarity": 0.99, "section": "Intro",
     "old_text": "Welcome to admissions.", "new_text": "Welcome to admissions."},
    {"verdict": "dropped", "similarity": 0.20, "section": "Deadlines",
     "old_text": "Priority consideration closes on February 15.", "new_text": None},
]


# --- selection ------------------------------------------------------------

def test_only_ambiguous_passages_are_paid_for():
    """Kept passages are settled; paying to be told so is waste."""
    chosen = select_passages(PASSAGES)
    assert [p["section"] for p in chosen] == ["Fees", "Deadlines"]


def test_reworded_passages_come_first():
    """They are the band embeddings provably cannot resolve -- the whole reason
    this stage exists -- so they must never be crowded out by known losses."""
    many = [{"verdict": "dropped", "similarity": 0.1, "old_text": "x " * 50}
            for _ in range(20)]
    many.append({"verdict": "reworded", "similarity": 0.7, "old_text": "fee",
                 "new_text": "cost", "section": "Fees"})
    chosen = select_passages(many, limit=5)
    assert chosen[0]["section"] == "Fees"


def test_passage_cap_is_enforced():
    many = [{"verdict": "reworded", "similarity": 0.7, "old_text": "a",
             "new_text": "b"} for _ in range(40)]
    assert len(select_passages(many, limit=12)) == 12


def test_long_passages_are_truncated_not_dropped():
    long_passage = [{"verdict": "reworded", "similarity": 0.7,
                     "old_text": "word " * 5000, "new_text": "short"}]
    prompt = build_prompt(select_passages(long_passage))
    assert "truncated" in prompt
    assert len(prompt) < 20000


def test_prompt_marks_a_passage_with_no_counterpart():
    prompt = build_prompt(select_passages(PASSAGES))
    assert "nothing on the new page corresponds" in prompt
    assert "February 15" in prompt


# --- which pages are worth judging ---------------------------------------

def test_clean_and_unknown_pages_are_never_judged():
    semantic = {"passages": PASSAGES}
    assert not should_judge("Clean", semantic)
    assert not should_judge("Unknown", semantic)
    assert should_judge("Missing content", semantic)


def test_a_flagged_page_with_nothing_ambiguous_is_not_judged():
    settled = {"passages": [{"verdict": "kept", "old_text": "x"}]}
    assert not should_judge("Major rewording", settled)


# --- budget ---------------------------------------------------------------

def test_budget_refuses_a_call_it_cannot_afford():
    """Checked before the call, so the cap is never discovered by passing it."""
    budget = Budget(max_usd=0.01)
    with pytest.raises(BudgetExceeded, match="cap"):
        budget.check("claude-opus-5", 100_000)


def test_budget_estimate_assumes_the_full_output_ceiling():
    """A budget that only holds on average is not a budget."""
    budget = Budget()
    assert budget.estimate("claude-opus-5", 1000) > \
        budget.estimate("claude-opus-5", 1000, output_tokens=10)


def test_unknown_model_is_refused_rather_than_uncapped():
    with pytest.raises(BudgetExceeded, match="no price on file"):
        Budget().price("claude-imaginary-9")


def test_judge_construction_rejects_an_unpriceable_model(tmp_path):
    with pytest.raises(BudgetExceeded):
        Judge(model="claude-imaginary-9", cache=JudgeCache(tmp_path))


def test_call_cap_stops_the_run(tmp_path):
    judge = _judge(tmp_path, budget=Budget(max_calls=1, max_usd=100))
    first = judge.judge_page(PASSAGES)
    second = judge.judge_page([dict(p, section="Other") for p in PASSAGES])
    assert first.judged
    assert not second.judged
    assert "call cap" in second.skipped_reason
    assert judge.budget.skipped == 1


def test_spend_is_recorded_from_actual_usage(tmp_path):
    judge = _judge(tmp_path)
    outcome = judge.judge_page(PASSAGES)
    assert outcome.cost_usd > 0
    assert judge.budget.spent_usd == pytest.approx(outcome.cost_usd)
    assert judge.budget.calls == 1


def test_cached_reads_are_billed_at_a_tenth(tmp_path):
    budget = Budget()
    full = budget.estimate("claude-opus-5", 10_000, output_tokens=0)
    budget.record("claude-opus-5", _usage(input_tokens=0, output_tokens=0,
                                          cached=10_000))
    assert budget.spent_usd == pytest.approx(full * 0.1, rel=1e-6)


# --- the call itself ------------------------------------------------------

def test_verdicts_are_matched_back_to_their_passages(tmp_path):
    judge = _judge(tmp_path)
    outcome = judge.judge_page(PASSAGES, title="Admissions")
    assert outcome.judged and outcome.severity == "major"
    assert outcome.passages[0]["section"] == "Fees"
    assert outcome.passages[0]["semantic_verdict"] == "reworded"
    assert outcome.facts_lost and "$75" in outcome.facts_lost[0]["detail"]


def test_a_passage_the_model_skipped_is_marked_unclear(tmp_path):
    """The model may return fewer verdicts than passages; silently dropping one
    would let an unjudged passage read as judged."""
    partial = PageJudgement(summary="s", severity="minor", passages=[])
    judge = _judge(tmp_path, StubClient(judgement=partial))
    outcome = judge.judge_page(PASSAGES)
    assert all(p["verdict"] == "unclear" for p in outcome.passages)


def test_the_stable_rubric_is_cached_on_the_request(tmp_path):
    """It is identical on every call, so caching turns the bulk of each request
    into a cache read after the first page."""
    client = StubClient()
    judge = _judge(tmp_path, client)
    judge.judge_page(PASSAGES)
    system = client.last_kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_adaptive_thinking_is_requested(tmp_path):
    client = StubClient()
    _judge(tmp_path, client).judge_page(PASSAGES)
    assert client.last_kwargs["thinking"] == {"type": "adaptive"}


def test_a_page_with_nothing_to_judge_costs_nothing(tmp_path):
    client = StubClient()
    judge = _judge(tmp_path, client)
    outcome = judge.judge_page([{"verdict": "kept", "old_text": "x"}])
    assert not outcome.judged and client.calls == 0
    assert judge.budget.spent_usd == 0


def test_a_refusal_is_reported_not_treated_as_a_verdict(tmp_path):
    client = StubClient()
    client._parse = lambda **kw: SimpleNamespace(
        parsed_output=None, usage=_usage(), stop_reason="refusal")
    client.messages = SimpleNamespace(parse=client._parse, count_tokens=client._count)
    outcome = _judge(tmp_path, client).judge_page(PASSAGES)
    assert not outcome.judged and "declined" in outcome.skipped_reason


# --- caching --------------------------------------------------------------

def test_identical_pages_are_not_judged_twice(tmp_path):
    client = StubClient()
    judge = _judge(tmp_path, client)
    first = judge.judge_page(PASSAGES)
    second = judge.judge_page(PASSAGES)
    assert client.calls == 1
    assert second.cached and second.cost_usd == 0
    assert second.summary == first.summary


def test_changed_text_is_judged_again(tmp_path):
    client = StubClient()
    judge = _judge(tmp_path, client)
    judge.judge_page(PASSAGES)
    judge.judge_page([dict(p, old_text=(p["old_text"] or "") + " changed")
                      for p in PASSAGES])
    assert client.calls == 2


def test_cache_can_be_turned_off(tmp_path):
    client = StubClient()
    judge = Judge(model="claude-opus-5", cache=JudgeCache(tmp_path, enabled=False))
    judge._client = client
    judge.judge_page(PASSAGES)
    judge.judge_page(PASSAGES)
    assert client.calls == 2


# --- failure handling -----------------------------------------------------

def test_missing_credentials_produce_an_instruction_not_a_traceback(tmp_path):
    """The SDK raises a plain TypeError on the first request -- not at client
    construction, and not as AuthenticationError."""
    error = TypeError("Could not resolve authentication method. Expected one of "
                      "api_key, auth_token, or credentials to be set.")
    assert is_credentials_error(error)
    outcome = _judge(tmp_path, StubClient(raises=error)).judge_page(PASSAGES)
    assert not outcome.judged
    assert outcome.skipped_reason == NO_CREDENTIALS_MESSAGE


def test_an_api_failure_leaves_the_rest_of_the_run_intact(tmp_path):
    judge = _judge(tmp_path, StubClient(raises=RuntimeError("boom")))
    outcome = judge.judge_page(PASSAGES)
    assert not outcome.judged
    assert "boom" in outcome.skipped_reason
    assert judge.budget.spent_usd == 0      # nothing billed for a failed call


def test_a_token_count_failure_falls_back_instead_of_skipping_the_budget(tmp_path):
    """Losing the count must not mean losing the cap."""
    client = StubClient()
    client._count = lambda **kw: (_ for _ in ()).throw(RuntimeError("unavailable"))
    client.messages = SimpleNamespace(parse=client._parse, count_tokens=client._count)
    judge = _judge(tmp_path, client)
    assert judge.count_input_tokens("x" * 300) > 0
    assert judge.judge_page(PASSAGES).judged
