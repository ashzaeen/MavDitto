"""Content Writer server routes -- validation paths only, same scope as
test_link_checker_server.py: driving Handler.do_POST() without a socket."""


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


def test_rewrite_endpoint_requires_a_valid_kind(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/rewrite", {"kind": "bogus"})
    assert status == 400
    assert "valid input kind" in payload["error"]


def test_rewrite_endpoint_requires_a_url_for_kind_url(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/rewrite", {"kind": "url"})
    assert status == 400
    assert "URL is required" in payload["error"]


def test_rewrite_endpoint_requires_file_data_for_a_file_kind(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/rewrite", {"kind": "pdf"})
    assert status == 400
    assert "File data is required" in payload["error"]


def test_rewrite_endpoint_rejects_undecodable_file_data(tmp_path):
    status, payload = _fake_post(
        tmp_path, "/api/content-writer/rewrite",
        {"kind": "pdf", "fileBase64": "!!! not base64 !!!"})
    assert status == 400
    assert "could not be decoded" in payload["error"]


def _no_llm(monkeypatch, *, critic_passes=True):
    """Stub every LLM touchpoint the Content Writer routes reach: the
    section rewrite and the review's critic. Deterministic rule checks still
    run for real."""
    from src.content_writer import generate as gen_module
    from src.content_writer import review as review_module

    def fake_rewrite_section(section, **kw):
        return section, 0.001

    real_review = review_module.review

    def review_without_critic(units, bv, **kw):
        kw["use_critic"] = False
        return real_review(units, bv, **kw)

    monkeypatch.setattr("src.content_writer.rewrite.rewrite_section", fake_rewrite_section)
    monkeypatch.setattr(gen_module, "review", review_without_critic)


def test_regenerate_section_endpoint_reaches_the_pipeline(tmp_path, monkeypatch):
    _no_llm(monkeypatch)
    status, payload = _fake_post(
        tmp_path, "/api/content-writer/regenerate-section",
        {"section": {"heading": "H", "body": "B", "kind": "body"}, "pageTitle": "T",
         "register": "institutional"})
    assert status == 200
    assert payload["section"]["heading"] == "H"
    assert "review" in payload


def test_regenerate_section_keeps_links_and_media(tmp_path, monkeypatch):
    """The route used to rebuild the Section from heading/body/kind only,
    dropping every link and media reference on each regenerate."""
    _no_llm(monkeypatch)
    status, payload = _fake_post(
        tmp_path, "/api/content-writer/regenerate-section",
        {"section": {"heading": "H", "body": "B", "kind": "cta",
                     "links": [{"text": "Apply", "url": "https://e.edu/apply", "isButton": True}],
                     "mediaRefs": ["a campus photo"]},
         "pageTitle": "T", "register": "institutional"})
    assert status == 200
    assert payload["section"]["links"][0]["url"] == "https://e.edu/apply"
    assert payload["section"]["links"][0]["isButton"] is True
    assert payload["section"]["mediaRefs"] == ["a campus photo"]


def test_regenerate_section_requires_some_text(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/regenerate-section",
                                 {"section": {}})
    assert status == 400


def _fake_get(tmp_path, path):
    from src.server import Handler

    Handler.results_dir = tmp_path
    sent = {}

    class Fake(Handler):
        def __init__(self):
            self.path = path
            self.headers = {"Content-Length": "0"}

        def _json(self, payload, status=200):
            sent["payload"], sent["status"] = payload, status

    Fake().do_GET()
    return sent["status"], sent["payload"]


def test_templates_endpoint_serves_the_registry_and_brand_profile(tmp_path):
    status, payload = _fake_get(tmp_path, "/api/content-writer/templates")
    assert status == 200
    keys = {t["key"] for t in payload["templates"]}
    assert {"rewrite-page", "news-story", "meta-descriptions", "compose-page"} <= keys
    assert payload["brand"]["isUta"] is True
    assert payload["audiences"]
    assert set(payload["toneDimensions"]) == {"formality", "energy", "technical_depth"}
    assert {o["key"] for o in payload["strictnessOptions"]} == {"mockup", "publish-ready"}


def test_templates_endpoint_only_lists_providers_with_credentials(tmp_path, monkeypatch):
    from src import llm_config, llm_provider

    # llm_config.load_config() syncs keys into os.environ as a side effect
    # (so the SDKs pick them up); an earlier real call in this process may
    # have already populated these, so clear them for a hermetic check.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm_config, "load_config", lambda: {
        "active_provider": "openai", "openai_api_key": "sk-real",
        "gemini_api_key": "", "claude_api_key": "",
    })
    status, payload = _fake_get(tmp_path, "/api/content-writer/templates")
    assert status == 200
    providers = {p["key"] for p in payload["modelProviders"]}
    assert providers == {"openai"}
    openai_entry = payload["modelProviders"][0]
    assert openai_entry["active"] is True
    assert [m["id"] for m in openai_entry["models"]] == [
        m["id"] for m in llm_provider.MODEL_CATALOG["openai"]]
    # The recommended default is deliberately not the top/most-expensive
    # tier -- see llm_provider.MODEL_CATALOG's module comment.
    assert openai_entry["defaultModel"] == llm_provider.recommended_model("openai")
    assert openai_entry["defaultModel"] != openai_entry["models"][-1]["id"]


def test_generate_resolves_and_forwards_the_writers_chosen_model(tmp_path, monkeypatch):
    """The model picker's whole point is that a request naming a model id
    actually reaches generate() -- not just that it parses into settings."""
    from src import llm_provider
    from src.content_writer import generate as gen_module
    from src.content_writer.generate import GenerationResult

    captured = {}

    def fake_generate(req, *, fetcher=None, budget=None, model=None, **kw):
        captured["model"] = model
        return GenerationResult(template_key=req.template_key)

    monkeypatch.setattr(gen_module, "generate", fake_generate)
    monkeypatch.setattr(llm_provider, "active_provider", lambda: "claude")

    picked = "claude-opus-5"
    status, payload = _fake_post(tmp_path, "/api/content-writer/generate", {
        "templateKey": "new-page", "brief": {"topic": "x"},
        "settings": {"model": picked}, "saveHistory": False})
    assert status == 200
    assert captured["model"] == picked


def test_generate_falls_back_to_the_recommended_model_when_none_chosen(tmp_path, monkeypatch):
    from src import llm_provider
    from src.content_writer import generate as gen_module
    from src.content_writer.generate import GenerationResult

    captured = {}

    def fake_generate(req, *, fetcher=None, budget=None, model=None, **kw):
        captured["model"] = model
        return GenerationResult(template_key=req.template_key)

    monkeypatch.setattr(gen_module, "generate", fake_generate)
    monkeypatch.setattr(llm_provider, "active_provider", lambda: "openai")

    status, payload = _fake_post(tmp_path, "/api/content-writer/generate", {
        "templateKey": "new-page", "brief": {"topic": "x"}, "saveHistory": False})
    assert status == 200
    assert captured["model"] == llm_provider.recommended_model("openai")
    # Recommended is deliberately not the top/most-expensive tier -- see
    # MODEL_CATALOG's module comment.
    assert captured["model"] != llm_provider.strongest_model("openai")


def test_generate_rejects_an_unknown_template(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/generate",
                                 {"templateKey": "sonnet", "brief": {}})
    assert status == 400
    assert "unknown template" in payload["error"]


def test_generate_reports_missing_brief_fields(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/generate",
                                 {"templateKey": "event-announcement", "brief": {"event_name": "Preview Day"}})
    assert status == 400
    assert "Date and time" in payload["error"] and "Location" in payload["error"]


def test_generate_rejects_a_bad_source(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/generate",
                                 {"templateKey": "rewrite-page", "source": {"kind": "url"}})
    assert status == 400
    assert "URL is required" in payload["error"]


def test_refine_rejects_an_unknown_action(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/refine",
                                 {"text": "Hello.", "action": "sparkle"})
    assert status == 400
    assert "unknown action" in payload["error"]


def test_refine_custom_needs_an_instruction(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/refine",
                                 {"text": "Hello.", "action": "custom"})
    assert status == 400


def test_review_endpoint_runs_the_rules_without_the_critic(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/review", {
        "templateKey": "meta-descriptions", "useCritic": False,
        "items": ["A world-class university. " + "x" * 200]})
    assert status == 200
    messages = [i["message"] for i in payload["review"]["issues"]]
    assert any("banned" in m for m in messages)
    assert any("character limit" in m for m in messages)
    assert payload["review"]["passes"] is False


def test_export_returns_a_word_file(tmp_path):
    import base64
    status, payload = _fake_post(tmp_path, "/api/content-writer/export", {
        "format": "docx", "title": "Preview Day",
        "sections": [{"heading": "When", "body": "Oct. 12\n\n- Tours\n- Lunch"}]})
    assert status == 200
    assert payload["filename"] == "preview-day.docx"
    assert base64.b64decode(payload["base64"])[:2] == b"PK"


def test_export_rejects_an_unknown_format(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/export",
                                 {"format": "epub", "title": "T"})
    assert status == 400


def test_history_rejects_an_id_that_could_escape_the_directory(tmp_path):
    status, payload = _fake_get(tmp_path, "/api/content-writer/history/..%2F..%2Fconfig")
    assert status == 400


# --- Compose mode ------------------------------------------------------------

def test_generate_reports_a_missing_prompt_for_compose_page(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/generate",
                                 {"templateKey": "compose-page", "brief": {}})
    assert status == 400
    assert "a description of the page" in payload["error"]


def _no_llm_compose(monkeypatch):
    """Same idea as _no_llm, for the compose-page path: stub the block
    redraft and the critic, keep deterministic rule checks live."""
    from src.content_writer import compose as compose_module
    from src.content_writer import review as review_module

    def fake_regenerate_block(block, **kw):
        from src.content_writer.review import ReviewResult
        return block, ReviewResult(passes=True), 0.001

    real_review = review_module.review

    def review_without_critic(units, bv, **kw):
        kw["use_critic"] = False
        return real_review(units, bv, **kw)

    # server.py imports regenerate_block locally inside the handler, so
    # patching it here on the compose module is picked up on every call.
    monkeypatch.setattr(compose_module, "regenerate_block", fake_regenerate_block)
    monkeypatch.setattr(review_module, "review", review_without_critic)


def test_regenerate_block_endpoint_reaches_the_pipeline(tmp_path, monkeypatch):
    _no_llm_compose(monkeypatch)
    status, payload = _fake_post(tmp_path, "/api/content-writer/regenerate-block", {
        "block": {"type": "stat", "statValue": "41,613", "statLabel": "Enrollment"},
        "index": 0, "allBlocks": [{"type": "stat", "statValue": "41,613", "statLabel": "Enrollment"}],
        "pageTitle": "T", "prompt": "A page about UTA"})
    assert status == 200
    assert payload["block"]["statValue"] == "41,613"
    assert "review" in payload


def test_regenerate_block_requires_some_content(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/regenerate-block",
                                 {"block": {"type": "text"}, "index": 0})
    assert status == 400
    assert "content" in payload["error"]


def test_regenerate_block_requires_an_index(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/regenerate-block",
                                 {"block": {"type": "text", "body": "Hi"}})
    assert status == 400
    assert "index" in payload["error"]


def test_review_endpoint_accepts_blocks(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/review", {
        "templateKey": "compose-page", "useCritic": False,
        "blocks": [{"type": "image", "imageAlt": "", "isPlaceholder": False}]})
    assert status == 200
    assert any("no alt text" in i["message"] for i in payload["review"]["issues"])


def test_review_endpoint_exempts_a_labeled_placeholder_block(tmp_path):
    status, payload = _fake_post(tmp_path, "/api/content-writer/review", {
        "templateKey": "compose-page", "useCritic": False,
        "blocks": [{"type": "quote", "quoteText": "Made up.", "quoteAttribution": "Nobody",
                   "isPlaceholder": True, "placeholderNote": "illustrative"}]})
    assert status == 200
    assert payload["review"]["passes"] is True


def test_export_accepts_blocks_and_pdf(tmp_path):
    import base64
    status, payload = _fake_post(tmp_path, "/api/content-writer/export", {
        "format": "pdf", "title": "What Makes UTA Great", "subtitle": "Discover the Maverick Difference",
        "blocks": [{"type": "hero", "heading": "What Makes UTA Great"}]})
    assert status == 200
    assert payload["filename"] == "what-makes-uta-great.pdf"
    assert base64.b64decode(payload["base64"])[:5] == b"%PDF-"
