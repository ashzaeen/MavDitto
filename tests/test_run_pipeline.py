"""Tests for the shared runner and the server that exposes it.

No network: the pipeline is exercised through a stub fetcher, and the server
through its own handler.
"""

import json
import threading
import time

import pytest

from src.run_pipeline import BackgroundRun, Cancelled, Progress, RunOptions


def test_progress_fraction_is_bounded():
    assert Progress().fraction == 0.0
    assert Progress(done=1, total=4).fraction == pytest.approx(0.25)
    assert Progress(done=9, total=4).fraction == 1.0
    assert Progress(finished=True).fraction == 1.0


def test_options_cap_the_work_by_default():
    """An unbounded crawl of someone's site is a denial of service with good
    intentions, and comparing content is the slow half."""
    options = RunOptions()
    assert options.max_pages <= 500
    assert options.max_pairs <= 100
    assert options.delay_s > 0


# --- deep crawl -------------------------------------------------------------

def test_deep_crawl_is_off_by_default():
    assert RunOptions().deep_crawl is False


def test_deep_crawl_raises_the_effective_caps():
    """The GUI exposes no depth control at all, so ticking the one checkbox it
    does have is the only way to ask for a deeper crawl than the quick-run
    defaults allow."""
    from src.run_pipeline import DEEP_MIN_DEPTH, DEEP_MIN_PAGES, effective_crawl_caps

    pages, depth = effective_crawl_caps(RunOptions(deep_crawl=True))
    assert pages >= DEEP_MIN_PAGES
    assert depth >= DEEP_MIN_DEPTH


def test_deep_crawl_never_lowers_a_cap_set_higher_than_the_floor():
    from src.run_pipeline import effective_crawl_caps

    pages, depth = effective_crawl_caps(
        RunOptions(deep_crawl=True, max_pages=5000, max_depth=50))
    assert pages == 5000
    assert depth == 50


def test_deep_crawl_leaves_ordinary_caps_untouched_when_off():
    from src.run_pipeline import effective_crawl_caps

    options = RunOptions(max_pages=200, max_depth=4)
    assert effective_crawl_caps(options) == (200, 4)


def test_a_failed_run_is_reported_not_raised():
    """A GUI polls this; an exception on the worker thread would otherwise be
    lost and the form would spin forever."""
    job = BackgroundRun("not-a-url", "also-not-a-url", "data/_unused")
    job._cancel.set()          # stop before any network work
    job.start()
    for _ in range(100):
        if not job.running:
            break
        time.sleep(0.05)
    progress = job.snapshot()
    assert progress.finished and progress.failed
    assert progress.error


def test_snapshot_is_a_copy_not_the_live_object():
    """The reader is another thread; handing it the live object would let it
    observe a half-updated state."""
    job = BackgroundRun("a", "b", "data/_unused")
    first = job.snapshot()
    first.message = "mutated"
    assert job.snapshot().message != "mutated"


def test_cancel_is_honoured_between_pages():
    from src.run_pipeline import run

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        run("https://old.example.edu", "https://new.example.edu", "data/_unused",
            cancel=cancel)


# --- the server -----------------------------------------------------------

def _handler_class(tmp_path):
    from src.server import Handler

    Handler.results_dir = tmp_path
    return Handler


def test_run_endpoint_refuses_an_incomplete_request(tmp_path):
    """Validation lives on the server too: the browser form is not the only
    caller, and a half-specified run would crawl nothing for a minute."""
    from src import server

    handler = _handler_class(tmp_path)
    sent = {}

    class Fake(handler):
        def __init__(self):        # bypass the socket machinery
            self.path = "/api/run"
            self.headers = {"Content-Length": "0"}

        def _body(self):
            return sent["body"]

        def _json(self, payload, status=200):
            sent["payload"], sent["status"] = payload, status

    sent["body"] = {"old": "https://a.example", "new": ""}
    Fake().do_POST()
    assert sent["status"] == 400
    assert "required" in sent["payload"]["error"]

    sent["body"] = {"old": "https://a.example", "new": "https://a.example"}
    Fake().do_POST()
    assert sent["status"] == 400
    assert "same URL" in sent["payload"]["error"]


def test_server_binds_to_localhost_by_default():
    """The run endpoint fetches arbitrary URLs on request. That is fine from
    your own machine and is not something to expose to a network."""
    import inspect
    from src import server

    source = inspect.getsource(server.main)
    assert '"--host", default="127.0.0.1"' in source


# --- the judge, reachable without a terminal ------------------------------

def test_judging_is_off_by_default_and_capped_when_on():
    """It costs money, so it is opt-in, and the cap is checked before every
    call rather than tallied afterwards."""
    assert RunOptions().judge is False
    assert RunOptions(judge=True).judge_budget_usd > 0


def test_judge_endpoint_rejects_an_unknown_page(tmp_path):
    from src.server import Handler

    Handler.results_dir = tmp_path
    sent = {}

    class Fake(Handler):
        def __init__(self):
            self.path = "/api/judge"
            self.headers = {"Content-Length": "0"}

        def _body(self):
            return {"id": 42}

        def _json(self, payload, status=200):
            sent["payload"], sent["status"] = payload, status

    Fake().do_POST()
    assert sent["status"] == 404
    assert "No such page" in sent["payload"]["error"]


# --- alt text, reachable without a terminal --------------------------------

def _fake_post(tmp_path, path, body):
    """Drive Handler.do_POST() without a socket, the same way the judge and
    run-validation tests above do, and return (status, payload)."""
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


def test_alt_text_image_endpoint_requires_an_image_and_a_type(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/alt-text/image", {})
    assert status == 400
    assert "required" in payload["error"]


def test_alt_text_image_endpoint_rejects_undecodable_data(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/alt-text/image",
                                 {"imageBase64": "!!! not base64 !!!",
                                  "mediaType": "image/png"})
    assert status == 400
    assert "decoded" in payload["error"]


def test_alt_text_images_endpoint_requires_at_least_one_image(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/alt-text/images", {})
    assert status == 400
    assert "At least one image is required" in payload["error"]

    status, payload = _fake_post(tmp_path, "/api/alt-text/images", {"images": []})
    assert status == 400
    assert "At least one image is required" in payload["error"]


def test_alt_text_page_endpoint_requires_a_url(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/alt-text/page", {})
    assert status == 400
    assert "URL is required" in payload["error"]


def test_missing_credentials_are_explained_without_naming_a_cli_flag():
    """The message is shown in a browser, where '--judge' means nothing."""
    from src.llm_judge import NO_CREDENTIALS_MESSAGE

    assert "ANTHROPIC_API_KEY" in NO_CREDENTIALS_MESSAGE
    assert "--judge" not in NO_CREDENTIALS_MESSAGE
