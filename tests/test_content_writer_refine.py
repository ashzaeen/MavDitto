"""refine(): actions, validation, and the one review-driven retry."""

import pytest

from src.content_writer.brand_voice import load_brand_voice
from src.content_writer.refine import ACTIONS, RefinedOutput, refine
from src.llm_cost import Budget
from tests.cw_stubs import RoutingStub, clean_critic

BV = load_brand_voice()


def _refine(text, action, routes, **kw):
    stub = RoutingStub(routes)
    result = refine(text, action, budget=Budget(), model="claude-opus-5", brand_voice=BV,
                    knowledge_base=[], client=stub, **kw)
    return result, stub


def test_a_refinement_returns_reviewed_text():
    result, stub = _refine("Our library is open late.", "shorten",
                           {"RefinedOutput": RefinedOutput(text="The library opens late."),
                            "CriticOutput": clean_critic()})
    assert result.text == "The library opens late."
    assert result.review.passes and result.cost_usd > 0
    assert ACTIONS["shorten"] in stub.user_text("RefinedOutput")


def test_the_surrounding_context_is_reference_only():
    _, stub = _refine("Open late.", "rephrase",
                      {"RefinedOutput": RefinedOutput(text="Open until 2 a.m."), "CriticOutput": clean_critic()},
                      context_text="The Central Library is open until 2 a.m.")
    user = stub.user_text("RefinedOutput")
    assert "SURROUNDING CONTEXT" in user and "PASSAGE:\nOpen late." in user


def test_a_bad_refinement_is_retried_once_against_its_issues():
    routes = {"RefinedOutput": [RefinedOutput(text="A world-class library."),
                                RefinedOutput(text="The library opens late.")],
              "CriticOutput": clean_critic()}
    result, stub = _refine("Our library is open late.", "warmer", routes, max_review_retries=1)
    assert result.text == "The library opens late."
    assert stub.count("RefinedOutput") == 2
    assert "world-class" in stub.user_text("RefinedOutput", 1)


def test_custom_needs_an_instruction():
    with pytest.raises(ValueError, match="instruction"):
        refine("Text.", "custom", brand_voice=BV, client=RoutingStub({}), model="claude-opus-5")


def test_unknown_action_and_empty_text_are_rejected():
    with pytest.raises(ValueError, match="unknown action"):
        refine("Text.", "sparkle", brand_voice=BV, client=RoutingStub({}), model="claude-opus-5")
    with pytest.raises(ValueError, match="no text"):
        refine("   ", "shorten", brand_voice=BV, client=RoutingStub({}), model="claude-opus-5")
