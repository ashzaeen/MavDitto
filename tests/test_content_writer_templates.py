"""The template registry is what the frontend renders from -- a bad entry
breaks a form, so its shape is checked here."""

import pytest

from src.content_writer import templates as tpl
from src.content_writer.brand_voice import load_brand_voice


def test_every_template_is_in_a_known_group_with_a_unique_key():
    keys = [t.key for t in tpl.TEMPLATES]
    assert len(keys) == len(set(keys))
    assert {t.group for t in tpl.TEMPLATES} == set(tpl.GROUPS)


def test_the_requested_content_types_are_all_present():
    assert {"rewrite-page", "new-page", "program-page", "landing-page", "department-page",
            "compose-page", "news-story", "event-announcement", "press-release", "spotlight",
            "headlines", "meta-descriptions", "ctas", "faq-set", "summary"} == set(tpl.BY_KEY)


def test_items_templates_have_a_character_limit():
    for t in tpl.TEMPLATES:
        if t.output_kind == "items":
            assert t.char_limit, t.key


def test_every_template_has_a_brand_default_in_the_uta_profile():
    matrix = load_brand_voice()["tone_by_context"]
    missing = [t.key for t in tpl.TEMPLATES if t.key not in matrix]
    assert missing == []


def test_to_dict_is_json_ready():
    import json
    json.dumps([t.to_dict() for t in tpl.TEMPLATES])


def test_unknown_template_is_a_clear_error():
    with pytest.raises(ValueError, match="unknown template"):
        tpl.get("haiku")


def test_length_instruction_prefers_an_explicit_word_count():
    t = tpl.get("new-page")
    assert tpl.length_instruction(t, "Short", 333) == "About 333 words in total."
    assert tpl.length_instruction(t, "Long", None) == "About 900 words in total."
    assert tpl.length_instruction(t, "nonsense", None) == "About 200 words in total."


def test_missing_required_fields():
    t = tpl.get("event-announcement")
    assert tpl.missing_required(t, {"event_name": "X"}, has_source=False) == ["Date and time", "Location"]
    assert tpl.missing_required(t, {}, has_source=True) == []
    assert tpl.missing_required(tpl.get("rewrite-page"), {}, has_source=False) == ["source material (a URL or file)"]
    assert tpl.missing_required(tpl.get("summary"), {"text": "Some text"}, has_source=False) == []
