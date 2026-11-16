"""The deterministic half of the review -- every rule here was added because
a live draft broke it -- plus how the critic's verdict folds in."""

from src.content_writer.brand_voice import load_brand_voice
from src.content_writer.review import (
    CRITICAL, SUGGESTED, CriticIssue, CriticOutput, invented_significance, review, rule_checks,
    text_metrics, unsourced_figures, unsourced_names,
)
from src.llm_cost import Budget
from tests.cw_stubs import RoutingStub, clean_critic

BV = load_brand_voice()


def _msgs(issues, severity=None):
    return [i.message for i in issues if severity is None or i.severity == severity]


def test_banned_terms_and_ai_tells_are_critical():
    issues, _ = rule_checks([{"body": "A world-class campus where you can unlock your potential."}], BV)
    msgs = _msgs(issues, CRITICAL)
    assert "Uses a banned term" in msgs and "Generic AI phrasing" in msgs


def test_generic_phrasing_from_the_source_is_a_suggestion_not_a_failure():
    """Rewriting uta.edu/admissions/apply: the live page itself says
    "vibrant community". A faithful rewrite echoing it must not fail review
    three times over the source's own words."""
    body = [{"body": "You will find a vibrant community here."}]
    introduced, _ = rule_checks(body, BV, allowed_corpus="")
    inherited, _ = rule_checks(body, BV, allowed_corpus="you'll find a vibrant community")
    assert "Generic AI phrasing" in _msgs(introduced, CRITICAL)
    assert "Generic phrasing (from the source)" in _msgs(inherited, SUGGESTED)
    assert not _msgs(inherited, CRITICAL)


def test_a_non_preferred_term_suggests_the_preferred_one():
    issues, _ = rule_checks([{"body": "Students at UT-Arlington study here."}], BV)
    hit = next(i for i in issues if i.message == "Non-preferred term")
    assert hit.severity == SUGGESTED and "UT Arlington" in hit.fix


def test_items_over_the_character_limit_are_critical():
    issues, _ = rule_checks([{"text": "x" * 170}], BV, output_kind="items", char_limit=155)
    assert any("over the 155-character limit" in m for m in _msgs(issues, CRITICAL))


def test_sourced_figures_pass_and_invented_ones_do_not():
    corpus = "Fall 2024 enrollment was 41,613 students. It has 120 seats."
    assert unsourced_figures("UTA enrolled 41,613 students; the room has 120 seats.", corpus) == []
    assert unsourced_figures("Graduates earn 35% more and there are 99,999 fans.", corpus) == ["35%", "99,999"]


def test_years_are_not_treated_as_statistics():
    assert unsourced_figures("In 2026 the library opens.", "") == []


def test_rankings_need_a_source():
    assert unsourced_figures("UTA is No. 3 for research.", "") == ["No. 3"]
    assert unsourced_figures("UTA is No. 1 in North Texas.", "ranked the No. 1 university") == []


def test_invented_significance_is_caught_in_its_many_phrasings():
    for sentence in ("This reflects UTA's commitment to students.",
                     "It is part of the University's broader efforts to grow.",
                     "This is indicative of UTA's commitment to enhancing resources.",
                     "We are dedicated to supporting your success."):
        assert invented_significance(sentence, ""), sentence


def test_a_commitment_the_source_itself_states_is_allowed():
    corpus = "The University is committed to providing access and ensuring student success."
    assert invented_significance("UTA is committed to providing access.", corpus) == []


def test_an_unrelated_dedicated_in_the_corpus_does_not_license_a_new_claim():
    """The knowledge-base boilerplate says 'dedicated to the advancement of
    knowledge' -- that must not wave through 'dedicated to supporting you'."""
    corpus = "an institution dedicated to the advancement of knowledge"
    assert invented_significance("We are dedicated to supporting your success.", corpus)


def test_unsourced_proper_names_are_flagged_and_sourced_ones_are_not():
    corpus = "The Central Library opens. Free printing with a Mav ID. The University of Texas at Arlington."
    body = ("The Central Library at The University of Texas at Arlington opens soon. Students "
            "with a Maverick ID print free. Staff at The Office of Wellness Hub helped. "
            "Visit Central Library today.")
    assert unsourced_names(body, corpus) == ["Maverick ID", "The Office of Wellness Hub"]


def test_first_reference_should_be_the_full_name():
    issues, _ = rule_checks([{"body": "UTA opens a library. The University of Texas at Arlington said so."}], BV)
    assert any(i.message.startswith("First reference") for i in issues)
    issues, _ = rule_checks([{"body": "The University of Texas at Arlington opens a library. UTA said so."}], BV)
    assert not any(i.message.startswith("First reference") for i in issues)


def test_ap_style_dates_are_checked_only_when_asked():
    body = [{"body": "It opens October 6 in Fall 2024 plans."}]
    assert not any("AP style" in m for m in _msgs(rule_checks(body, BV)[0]))
    msgs = _msgs(rule_checks(body, BV, ap_style=True)[0])
    assert "AP style abbreviates this month with a date" in msgs
    assert "AP style lowercases seasons" in msgs


def test_markdown_links_in_plain_copy_are_critical():
    issues, _ = rule_checks([{"body": "Visit [our site](https://libraries.uta.edu) today."}], BV)
    assert "Markdown link syntax in plain-text copy" in _msgs(issues, CRITICAL)


def test_superlatives_need_a_source():
    issues, _ = rule_checks([{"body": "Our award-winning faculty teach here."}], BV)
    assert "Superlative or claim with no source" in _msgs(issues, CRITICAL)
    issues, _ = rule_checks([{"body": "Our award-winning faculty teach here."}], BV,
                            allowed_corpus="Professor X leads the award-winning lab.")
    assert "Superlative or claim with no source" not in _msgs(issues)


def test_source_details_match_across_reformatting():
    from src.content_writer.review import dropped_details
    source = ("Fr 4:00PM - 6:50PM NH 112. Office hours 4.30 PM -5.30 PM. Due February 13. "
              "Call 817-272-3785 or email Francklin.rivas@uta.edu. 2 assignments (10 points each).")
    draft = ("Class meets Fridays, 4-6:50 p.m. in NH 112; office hours 4:30-5:30 p.m. Due Feb. 13. "
             "Call 817.272.3785 or email francklin.rivas@uta.edu. The 2 assignments are worth 10 points each.")
    assert dropped_details(draft, source) == ([], 10)


def test_dropped_details_are_named():
    from src.content_writer.review import dropped_details
    missing, total = dropped_details("Due Feb. 13.", "Due February 13. Exam on April 24 in NH 112.")
    assert missing == ["April 24", "NH 112"] and total == 3


def test_coverage_required_fails_and_coverage_reported_only_suggests():
    source = "Assignment 1 due February 13. Assignment 2 due March 6. Room NH 112."
    unit = [{"body": "Assignment 1 is due Feb. 13."}]
    required, m = rule_checks(unit, BV, source_text=source, coverage="required")
    reported, _ = rule_checks(unit, BV, source_text=source, coverage="report")
    assert "2 of 3 details from the source are missing" in _msgs(required, CRITICAL)
    assert "2 of 3 details from the source are missing" in _msgs(reported, SUGGESTED)
    assert m["source_details"] == 3 and m["source_details_kept"] == 1


def test_a_name_reworded_from_source_words_is_not_invented():
    corpus = "Teaching Assistant: Satyal, Sachit. Federal Student\nAid recipients."
    body = "Your teaching assistant is Sachit Satyal. It matters for Federal Student Aid recipients."
    assert unsourced_names(body, corpus) == []


def test_an_email_domain_is_not_a_first_reference():
    body = [{"body": "Email francklin.rivas@uta.edu. The University of Texas at Arlington offers it."}]
    issues, _ = rule_checks(body, BV)
    assert not any(i.message.startswith("First reference") for i in issues)


def test_reading_level_is_a_suggestion_not_a_block():
    long = ("The institutional prioritization of multidisciplinary collaborative scholarship "
            "necessitates comprehensive infrastructural reconfiguration. ") * 8
    issues, m = rule_checks([{"body": long}], BV, reading_level="grade 8")
    grade = next(i for i in issues if i.message.startswith("Reads at grade"))
    assert grade.severity == SUGGESTED and m["fk_grade"] > 10


def test_text_metrics_are_sane():
    m = text_metrics("The cat sat. The dog ran fast.")
    assert m["words"] == 7 and m["sentences"] == 2 and m["avg_sentence_words"] == 3.5


def test_review_folds_in_the_critic_and_passes_only_without_critical_issues():
    critic = CriticOutput(voice_match=4, tone_fit=5, clarity=5, fact_fidelity=2, issues=[
        CriticIssue(severity="Critical", section=0, quote="best", problem="Unsourced claim", fix="Cut it")])
    stub = RoutingStub({"CriticOutput": critic})
    rv = review([{"body": "A clean sentence."}], BV, budget=Budget(), client=stub, model="claude-opus-5")
    assert rv.passes is False
    assert rv.scores["fact_fidelity"] == 2
    assert rv.issues[0].source == "critic" and rv.issues[0].severity == CRITICAL
    assert rv.cost_usd > 0


def test_a_critic_fix_that_breaks_the_rules_is_dropped():
    """Seen live: the critic suggested "cutting-edge research" (banned) and
    "over 300 student organizations" (invented) as fixes."""
    critic = CriticOutput(voice_match=3, tone_fit=4, clarity=4, fact_fidelity=4, issues=[
        CriticIssue(severity="suggested", section=0, quote="innovative", problem="Vague",
                    fix="Say 'cutting-edge research' instead."),
        CriticIssue(severity="suggested", section=0, quote="many clubs", problem="Vague",
                    fix="Say 'over 300 student organizations'."),
        CriticIssue(severity="suggested", section=0, quote="dynamic", problem="Vague",
                    fix="Name the student organizations instead.")])
    rv = review([{"body": "Text."}], BV, budget=Budget(), client=RoutingStub({"CriticOutput": critic}),
                model="claude-opus-5")
    assert [i.fix for i in rv.issues] == ["", "", "Name the student organizations instead."]


def test_a_clean_draft_passes():
    stub = RoutingStub({"CriticOutput": clean_critic()})
    rv = review([{"body": "The library opens Oct. 6."}], BV, allowed_corpus="Oct. 6",
                budget=Budget(), client=stub, model="claude-opus-5")
    assert rv.passes and not [i for i in rv.issues if i.severity == CRITICAL]


def test_the_critic_is_given_the_allowed_facts_and_the_vendored_checklist():
    stub = RoutingStub({"CriticOutput": clean_critic()})
    review([{"body": "Text."}], BV, allowed_corpus="THE-ALLOWED-FACT", request_summary="News story",
           budget=Budget(), client=stub, model="claude-opus-5")
    assert "THE-ALLOWED-FACT" in stub.user_text("CriticOutput")
    assert "Voice compliance" in stub.system_text("CriticOutput")
