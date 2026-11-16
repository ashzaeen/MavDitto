"""Brand profile v2: normalization, the shared is_uta answer, the knowledge
base, the vendored method loader, and white-label safety (a fork's prompts
never mention UTA)."""

import json

from src.content_writer import voice_method
from src.content_writer.brand_voice import (
    brand_full_name, dials_for, is_uta, load_brand_voice, load_knowledge_base, normalize,
    register_keys, save_knowledge_base,
)
from src.content_writer.prompting import system_prompt

V1_FORK = {
    "brand": "Acme State",
    "registers": {"campus": {"label": "Campus", "used_for": ["news"],
                             "description": "Friendly.", "example": "Welcome to Acme."}},
    "shared_principles": ["Be clear"],
    "seed_system_prompt": "Write like Acme's own staff.",
    "guardrail": {"floor_description": "Nothing generic.", "checks": ["no slang"]},
}


def test_committed_profile_is_v2_and_uta():
    bv = load_brand_voice()
    assert is_uta(bv)
    assert brand_full_name(bv) == "The University of Texas at Arlington"
    assert len(bv["we_are"]) >= 4               # the vendored method's own completeness bar
    assert bv["terminology"]["style_rules"]
    assert bv["audiences"]


def test_a_v1_profile_normalizes_without_inventing_content():
    bv = normalize(V1_FORK)
    assert bv["we_are"] == [] and bv["examples"] == [] and bv["open_questions"] == []
    assert set(bv["tone_dimensions"]) == {"formality", "energy", "technical_depth"}
    assert bv["terminology"] == {"preferred": [], "banned": [], "needs_source": [], "style_rules": []}
    assert bv["audiences"][0]["key"] == "general"
    assert bv["brand_full_name"] == "Acme State"


def test_normalize_does_not_mutate_its_input():
    original = json.loads(json.dumps(V1_FORK))
    normalize(original)
    assert original == V1_FORK


def test_is_uta_is_case_and_space_insensitive():
    assert is_uta({"brand": "  uta "})
    assert not is_uta({"brand": "UT Austin"})
    assert not is_uta({})


def test_dials_fall_back_to_defaults_for_an_unknown_template():
    bv = load_brand_voice()
    assert dials_for(bv, "news-story") == {"formality": 4, "energy": 3, "technical_depth": 2}
    assert dials_for(bv, "no-such-template") == {"formality": 3, "energy": 3, "technical_depth": 2}


def test_register_keys_normalize_underscores():
    assert "prospective-student" in register_keys(load_brand_voice())


def test_a_fork_prompt_never_mentions_uta():
    prompt = system_prompt(normalize(V1_FORK), "news-story")
    assert "UTA" not in prompt and "Arlington" not in prompt
    assert "Acme State" in prompt


def test_the_uta_prompt_carries_the_v2_profile():
    prompt = system_prompt(load_brand_voice(), "news-story")
    assert "The University of Texas at Arlington" in prompt
    assert "WE ARE" in prompt
    assert "Before: UTA is super excited" not in prompt    # lean prompt: no example calibration


def test_the_knowledge_base_round_trips_and_drops_blank_facts(tmp_path):
    path = tmp_path / "kb.json"
    save_knowledge_base([{"title": "A", "fact": "Fact one.", "tags": ["x", " "]},
                         {"title": "blank", "fact": "   "}], path)
    facts = load_knowledge_base(path)
    assert len(facts) == 1 and facts[0]["id"] == "fact-1" and facts[0]["tags"] == ["x"]


def test_a_missing_knowledge_base_is_empty_not_an_error(tmp_path):
    assert load_knowledge_base(tmp_path / "nope.json") == []


def test_every_committed_fact_names_its_source():
    for f in load_knowledge_base():
        assert f["source_url"].startswith("https://"), f["id"]


# --- the vendored method -------------------------------------------------

def test_vendored_method_drops_host_only_lines():
    for text in (voice_method.voice_model(), voice_method.enforcement_procedure(),
                 voice_method.qa_checklist(), voice_method.guideline_method()):
        assert "/brand-voice:" not in text
        assert ".claude/" not in text
        assert "references/" not in text


def test_vendored_method_keeps_fenced_examples_whole():
    """A '## heading' inside a ``` fence is example content -- it must not
    end the section it sits in."""
    text = voice_method.guideline_method()
    assert "Every open question MUST include an agent recommendation" in text


def test_vendored_sales_examples_never_reach_a_prompt():
    """They illustrate the method with invented statistics; this tool forbids those."""
    prompt = system_prompt(load_brand_voice(), "new-page")
    assert "23%" not in prompt and "pipeline" not in prompt.lower()
