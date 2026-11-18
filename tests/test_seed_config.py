"""The UTA seed profile and the script that installs it."""
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_writer.brand_voice import load_brand_voice, load_knowledge_base
from src.web_builder.catalog import load_catalog

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "config" / "seed"

_spec = importlib.util.spec_from_file_location("seed_config", ROOT / "scripts" / "seed_config.py")
seed_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_config)


def test_uta_is_an_available_profile():
    assert "uta" in seed_config.profiles(SEED)


def test_the_seed_files_load_through_the_real_loaders():
    uta = SEED / "uta"
    bv = load_brand_voice(uta / "brand-voice.json")
    assert bv["brand"] == "UTA"
    assert bv["registers"]

    facts = load_knowledge_base(uta / "knowledge-base.json")
    assert facts and all(f["source_url"].startswith("https://") for f in facts)

    catalog = load_catalog(uta / "components.json")
    assert len(catalog) > 10


def test_seed_writes_three_files_into_an_empty_config_dir(tmp_path):
    result = seed_config.seed("uta", config_dir=tmp_path, seed_dir=SEED)
    assert result == {name: "written" for name in seed_config.CONFIG_FILES}
    for name in seed_config.CONFIG_FILES:
        assert json.loads((tmp_path / name).read_text(encoding="utf-8"))


def test_seed_never_overwrites_without_force(tmp_path):
    mine = tmp_path / "brand-voice.json"
    mine.write_text('{"mine": true}', encoding="utf-8")

    result = seed_config.seed("uta", config_dir=tmp_path, seed_dir=SEED)
    assert result["brand-voice.json"] == "kept"
    assert json.loads(mine.read_text(encoding="utf-8")) == {"mine": True}
    assert result["components.json"] == "written"

    result = seed_config.seed("uta", config_dir=tmp_path, seed_dir=SEED, force=True)
    assert result["brand-voice.json"] == "written"
    assert json.loads(mine.read_text(encoding="utf-8")).get("brand") == "UTA"


def test_unknown_profile_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError, match="unknown profile"):
        seed_config.seed("nope", config_dir=tmp_path / "cfg", seed_dir=SEED)
    assert not (tmp_path / "cfg").exists()


def test_an_invalid_seed_file_is_refused_before_anything_is_written(tmp_path):
    bad = tmp_path / "seed" / "bad"
    bad.mkdir(parents=True)
    for name in seed_config.CONFIG_FILES:
        (bad / name).write_text("{}", encoding="utf-8")
    (bad / "components.json").write_text("{not json", encoding="utf-8")

    out = tmp_path / "cfg"
    with pytest.raises(ValueError, match="not valid JSON"):
        seed_config.seed("bad", config_dir=out, seed_dir=tmp_path / "seed")
    assert not out.exists()


def test_cli_lists_profiles_and_seeds(tmp_path, capsys):
    assert seed_config.main(["--list"]) == 0
    assert "uta" in capsys.readouterr().out

    assert seed_config.main(["--config-dir", str(tmp_path)]) == 0
    assert (tmp_path / "components.json").is_file()
    assert seed_config.main(["--config-dir", str(tmp_path)]) == 0
    assert "Nothing changed" in capsys.readouterr().out
    assert seed_config.main(["--profile", "nope", "--config-dir", str(tmp_path)]) == 1
