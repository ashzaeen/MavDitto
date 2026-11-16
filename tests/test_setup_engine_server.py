"""Setup engine server routes -- driving Handler.do_GET()/do_POST() without a
socket, same pattern as the other *_server.py test files. save_config() is
redirected to tmp_path via monkeypatching config_io's module-level paths, so
these tests never touch the real committed /config files.
"""

import pytest


def _fake_post(tmp_path, path, body):
    from src.server import Handler

    Handler.results_dir = tmp_path
    sent = {}

    class Fake(Handler):
        def __init__(self):
            self.path = path
            self.headers = {"Content-Length": "0"}

        def _body(self):
            return body

        def _json(self, payload, status=200):
            sent["payload"], sent["status"] = payload, status

    Fake().do_POST()
    return sent["status"], sent["payload"]


def _fake_get(tmp_path, path):
    from src.server import Handler

    Handler.results_dir = tmp_path
    sent = {}

    class Fake(Handler):
        def __init__(self):
            self.path = path

        def _json(self, payload, status=200):
            sent["payload"], sent["status"] = payload, status

    Fake().do_GET()
    return sent["status"], sent["payload"]


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Points config_io at a scratch directory so a save test never touches
    the real, committed UTA config."""
    import src.setup_engine.config_io as config_io

    config_dir = tmp_path / "config"
    monkeypatch.setattr(config_io, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_io, "BRAND_VOICE_PATH", config_dir / "brand-voice.json")
    monkeypatch.setattr(config_io, "COMPONENTS_PATH", config_dir / "components.json")
    return config_dir


def test_config_status_reports_the_real_committed_files(tmp_path):
    status, payload = _fake_get(tmp_path, "/api/config/status")
    assert status == 200
    assert payload["brandVoice"] is True
    assert payload["components"] is True


def test_config_status_reports_false_for_a_missing_config(tmp_path, isolated_config):
    status, payload = _fake_get(tmp_path, "/api/config/status")
    assert payload["brandVoice"] is False
    assert payload["components"] is False


def test_ingest_brand_voice_requires_at_least_one_input(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/setup/ingest-brand-voice", {"inputs": []})
    assert status == 400
    assert "At least one input" in payload["error"]


def test_ingest_brand_voice_requires_a_valid_kind(tmp_path):
    status, payload = _fake_post(
        tmp_path, "/api/setup/ingest-brand-voice", {"inputs": [{"kind": "bogus"}]})
    assert status == 400
    assert "valid input kind" in payload["error"]


def test_ingest_components_requires_at_least_one_input(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/setup/ingest-components", {"inputs": []})
    assert status == 400
    assert "At least one input" in payload["error"]


def test_setup_save_requires_something_to_save(tmp_path, isolated_config):
    status, payload = _fake_post(tmp_path, "/api/setup/save", {})
    assert status == 400
    assert "Nothing to save" in payload["error"]


def test_setup_save_writes_brand_voice_and_reports_status(tmp_path, isolated_config):
    status, payload = _fake_post(
        tmp_path, "/api/setup/save", {"brandVoice": {"brand": "Acme"}})
    assert status == 200
    assert payload["brandVoice"] is True
    assert payload["components"] is False
    assert (isolated_config / "brand-voice.json").is_file()


def test_setup_save_writes_components_independently(tmp_path, isolated_config):
    _fake_post(tmp_path, "/api/setup/save", {"brandVoice": {"brand": "Acme"}})
    status, payload = _fake_post(
        tmp_path, "/api/setup/save", {"components": {"components": []}})
    assert status == 200
    assert payload["brandVoice"] is True
    assert payload["components"] is True
