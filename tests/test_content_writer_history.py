"""Saved runs: plain JSON files, newest first, capped, and unaddressable
outside their own directory."""

import pytest

from src.content_writer import history


def test_save_list_load_delete(tmp_path):
    run_id = history.save({"templateKey": "news-story"}, {"variants": [{}, {}], "costUsd": 0.01},
                          title="Library opens", directory=tmp_path)
    runs = history.list_runs(tmp_path)
    assert runs[0]["id"] == run_id and runs[0]["title"] == "Library opens"
    assert runs[0]["variants"] == 2 and runs[0]["templateKey"] == "news-story"
    assert history.load(run_id, tmp_path)["request"]["templateKey"] == "news-story"
    history.delete(run_id, tmp_path)
    assert history.list_runs(tmp_path) == []


def test_ids_that_could_escape_the_directory_are_refused(tmp_path):
    for bad in ("../config/brand-voice", "..\\x", "20260101T000000-zzzzzzzz", ""):
        with pytest.raises(ValueError):
            history.load(bad, tmp_path)


def test_a_missing_run_is_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        history.load("20260101T000000-deadbeef", tmp_path)


def test_old_runs_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MAX_RUNS", 3)
    for i in range(5):
        (tmp_path / f"2026010{i}T000000-0000000{i}.json").write_text("{}", encoding="utf-8")
    history.save({}, {}, directory=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_a_corrupt_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "20260101T000000-deadbeef.json").write_text("{not json", encoding="utf-8")
    assert history.list_runs(tmp_path) == []
