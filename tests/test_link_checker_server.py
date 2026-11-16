"""Broken Link Inspector server routes -- validation paths only, the same
scope test_run_pipeline.py's alt-text route tests cover: driving
Handler.do_POST()/do_GET() without a socket to check the plumbing, not
re-testing pipeline.py's own logic (already covered in
test_link_checker_pipeline.py)."""


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


def test_link_check_page_endpoint_requires_a_url(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/link-check/page", {})
    assert status == 400
    assert "URL is required" in payload["error"]


def test_link_check_site_endpoint_requires_a_url(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/link-check/site", {})
    assert status == 400
    assert "URL is required" in payload["error"]


def test_link_check_site_progress_is_idle_before_any_scan_starts(tmp_path):
    import src.server as server_module
    server_module._link_state["job"] = None
    status, payload = _fake_get(tmp_path, "/api/link-check/site")
    assert status == 200
    assert payload["state"] == "idle"


def test_link_check_site_cancel_is_a_no_op_before_any_scan_starts(tmp_path):
    import src.server as server_module
    server_module._link_state["job"] = None
    status, payload = _fake_post(tmp_path, "/api/link-check/site/cancel", {})
    assert status == 200
    assert payload["state"] == "cancelling"
