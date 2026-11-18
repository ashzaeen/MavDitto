"""Test configuration.

Most tests run offline against fixtures in `tests/fixtures.py`. A handful assert
against a real brand-voice profile, knowledge base or component catalog, and
those files are deliberately not in this repository (they are generated locally
by the Setup Wizard and git-ignored; see `config/README.md`).

On a fresh clone those tests cannot run, so they are skipped with a note rather
than failing at import time. Generate your own config and they run as normal.
"""
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
REQUIRED_CONFIG = ("brand-voice.json", "knowledge-base.json", "components.json")


def _missing_config() -> list[str]:
    return [name for name in REQUIRED_CONFIG if not (CONFIG_DIR / name).is_file()]


# Test modules that load the real config at import time or assert on its contents.
NEEDS_LOCAL_CONFIG = [
    "test_content_writer_brand_voice.py",
    "test_content_writer_compose.py",
    "test_content_writer_generate.py",
    "test_content_writer_guardrail.py",
    "test_content_writer_refine.py",
    "test_content_writer_review.py",
    "test_content_writer_rewrite.py",
    "test_content_writer_templates.py",
    "test_web_builder_catalog.py",
    "test_web_builder_match.py",
    "test_web_builder_populate.py",
]

collect_ignore = NEEDS_LOCAL_CONFIG if _missing_config() else []

# Individual tests, in modules that otherwise run fine, that read the real config.
NEEDS_LOCAL_CONFIG_TESTS = {
    "test_content_writer_pipeline.py": None,  # None = every test in the module
    "test_web_builder_pipeline.py": None,
    "test_content_writer_server.py": {
        "test_regenerate_section_endpoint_reaches_the_pipeline",
        "test_regenerate_section_keeps_links_and_media",
        "test_templates_endpoint_serves_the_registry_and_brand_profile",
        "test_templates_endpoint_only_lists_providers_with_credentials",
        "test_generate_rejects_an_unknown_template",
        "test_generate_reports_missing_brief_fields",
        "test_review_endpoint_runs_the_rules_without_the_critic",
        "test_generate_reports_a_missing_prompt_for_compose_page",
        "test_review_endpoint_accepts_blocks",
        "test_review_endpoint_exempts_a_labeled_placeholder_block",
    },
    "test_setup_engine_server.py": {"test_config_status_reports_the_real_committed_files"},
}


def pytest_collection_modifyitems(config, items):
    missing = _missing_config()
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"needs your own config/ ({', '.join(missing)}); see config/README.md")
    for item in items:
        names = NEEDS_LOCAL_CONFIG_TESTS.get(Path(str(item.fspath)).name, ())
        if names is None or item.originalname in (names or ()):
            item.add_marker(skip)


def pytest_report_header(config):
    missing = _missing_config()
    if missing:
        return (
            f"config/ is missing {', '.join(missing)}: skipping "
            f"{len(NEEDS_LOCAL_CONFIG)} test modules that need your own brand-voice, "
            "knowledge-base and component config (generate it with the Setup Wizard)."
        )
    return None
