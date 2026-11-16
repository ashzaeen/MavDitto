"""Web Builder server routes -- driving Handler.do_POST() without a socket,
same pattern as test_content_writer_server.py."""


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


def _structured_content():
    return {
        "pageTitle": "Campus Life",
        "register": "institutional",
        "sections": [{"heading": "How do I apply?", "body": "Short answer.",
                     "kind": "faq-item", "links": [], "mediaRefs": []}],
        "originalSections": [],
        "sourceNote": "test",
        "costUsd": 0.0,
    }


def test_extract_endpoint_requires_a_valid_kind(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/web-builder/extract", {"kind": "bogus"})
    assert status == 400
    assert "valid input kind" in payload["error"]


def test_extract_endpoint_turns_markdown_into_structured_content(tmp_path):
    import base64

    md = base64.b64encode(b"# Campus Life\n\n## Housing\n\nDetails.\n").decode()
    status, payload = _fake_post(
        tmp_path, "/api/web-builder/extract", {"kind": "markdown", "fileBase64": md})
    assert status == 200
    assert payload["pageTitle"] == "Campus Life"
    assert payload["costUsd"] == 0.0
    assert any(s["heading"] == "Housing" for s in payload["sections"])


def test_extract_endpoint_carries_page_chrome_context_through(tmp_path, monkeypatch):
    """This used to be silently dropped -- extract_content's own
    page_chrome_context never made it into the route's StructuredContent."""
    from src.content_writer.models import ExtractedContent, Section

    def fake_extract_content(input_, **kw):
        return ExtractedContent(
            page_title="T", sections=[Section(heading="H", body="B", kind="body")],
            source_note="test", page_chrome_context="Nav: Admissions")

    monkeypatch.setattr("src.content_writer.pipeline.extract_content", fake_extract_content)
    status, payload = _fake_post(
        tmp_path, "/api/web-builder/extract", {"kind": "url", "url": "https://e.edu/x"})
    assert status == 200
    assert payload["pageChromeContext"] == "Nav: Admissions"


def test_plan_endpoint_requires_structured_content(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/web-builder/plan", {})
    assert status == 400
    assert "structuredContent is required" in payload["error"]


def _stub_plan(monkeypatch, component="Accordion"):
    """The plan route now makes a real LLM call -- stub the pipeline
    function itself, the same way test_content_writer_server.py stubs
    rewrite_section for its one success-path test."""
    from src.web_builder.models import LayoutPlan, LayoutPlanRow

    def fake_make_plan(content, **kw):
        return LayoutPlan(rows=[
            LayoutPlanRow(order=1, component=component, section_indices=[0],
                         maps_to="How do I apply?", rationale="stubbed for the test"),
        ])

    monkeypatch.setattr("src.web_builder.pipeline.make_plan", fake_make_plan)


def test_plan_endpoint_returns_a_real_plan(tmp_path, monkeypatch):
    _stub_plan(monkeypatch)
    status, payload = _fake_post(
        tmp_path, "/api/web-builder/plan", {"structuredContent": _structured_content()})
    assert status == 200
    assert payload["state"] == "planned"
    assert len(payload["rows"]) >= 1
    assert payload["rows"][0]["component"] == "Accordion"


def test_populate_endpoint_requires_both_fields(tmp_path):
    status, payload = _fake_post(
        tmp_path, "/api/web-builder/populate", {"structuredContent": _structured_content()})
    assert status == 400
    assert "both required" in payload["error"]


def _stub_populate(monkeypatch, component="Accordion"):
    """Same reasoning as `_stub_plan` -- this route now makes a real,
    type-aware LLM call per component; stub the pipeline function itself
    rather than depending on live model output for a plumbing test."""
    from src.web_builder.models import PopulatedComponent, PopulatedField

    def fake_populate_approved_plan(content, plan, **kw):
        populated = [
            PopulatedComponent(component=component, section_indices=[0], status="valid", fields=[
                PopulatedField(name="Title", field_type="plaintext", text="How do I apply?"),
            ])
            for _ in plan.rows
        ]
        return populated, []

    monkeypatch.setattr("src.web_builder.pipeline.populate_approved_plan", fake_populate_approved_plan)


def test_populate_endpoint_returns_populated_fields(tmp_path, monkeypatch):
    _stub_plan(monkeypatch)
    _stub_populate(monkeypatch)
    content = _structured_content()
    plan_status, plan_payload = _fake_post(
        tmp_path, "/api/web-builder/plan", {"structuredContent": content})
    assert plan_status == 200

    status, payload = _fake_post(
        tmp_path, "/api/web-builder/populate",
        {"structuredContent": content,
         "plan": {"rows": plan_payload["rows"], "unmatchedNotes": plan_payload["unmatchedNotes"]}})
    assert status == 200
    assert payload["state"] == "populated"
    assert payload["problems"] == []
    assert len(payload["components"]) == len(plan_payload["rows"])
