"""Serve the dashboard and let it start runs.

    python -m src.server                 # http://127.0.0.1:8000

The React app is a static bundle, so on its own it can only display results
someone already produced from a terminal. That makes the tool unusable by the
reviewer it was written for. This adds the smallest backend that fixes it: it
serves the built app and exposes four endpoints for starting, watching and
stopping a run.

Standard library only. This is a single-user tool on localhost, and a web
framework would be a dependency earning nothing.

    GET  /api/data           the current results, same shape as data.json
    POST /api/run            {old, new, ...options} -> starts a run
    GET  /api/run            progress of the current run
    POST /api/run/cancel     stop it
    POST /api/judge          {id} -> read one page with the LLM judge
    POST /api/alt-text/image {imageBase64, mediaType} -> alt text for one image
    POST /api/alt-text/images {images:[{imageBase64, mediaType, name}], budget}
                              -> alt text for a batch of pasted/uploaded images
    POST /api/alt-text/page  {url} -> alt text for every image on one page
    POST /api/link-check/page       {url, ...} -> link health for one page
    POST /api/link-check/site       {url, ...} -> starts a Site Scan
    GET  /api/link-check/site       progress of the current Site Scan
    POST /api/link-check/site/cancel   stop it
    POST /api/content-writer/rewrite  {kind, url|fileBase64, tone, length, ...} -> rewritten StructuredContent
    POST /api/content-writer/regenerate-section  {section, pageTitle, register, settings} -> one reviewed Section
    POST /api/content-writer/regenerate-block  {block, index, allBlocks, pageTitle, prompt, settings}
                              -> one reviewed Block (Compose mode)
    GET  /api/content-writer/templates  -> templates + the brand profile's audiences, dials, matrix
    POST /api/content-writer/generate   {templateKey, brief, settings, source?} -> reviewed variants
         (templateKey "compose-page": brief.prompt is free text -> ComposedPage of typed blocks)
    POST /api/content-writer/refine     {text, action, instruction?, contextText, settings} -> refined text
    POST /api/content-writer/review     {templateKey, sections|items|blocks, settings} -> review of an edited draft
    POST /api/content-writer/export     {format: md|txt|html|docx|pdf, title, subtitle?, sections|items|blocks}
                              -> file (base64)
    GET  /api/content-writer/history[/id]        saved runs
    POST /api/content-writer/history/delete {id}
    GET/POST /api/config/knowledge-base  verified facts the writer may cite
    GET  /api/config/brand-voice     the normalized brand profile, for the Settings editor
    POST /api/web-builder/extract     {kind, url|fileBase64, ...} -> plain StructuredContent, no rewrite
    POST /api/web-builder/plan        {structuredContent} -> layout plan (Phase 1)
    POST /api/web-builder/populate    {structuredContent, plan} -> populated fields + validation problems (Phase 2)
    POST /api/web-builder/regenerate-component  {structuredContent, row} -> one re-populated component
    GET  /api/config/status          {brandVoice, components} -> whether each config file exists
    GET  /api/web-builder/catalog    -> [{name, category, purpose, visualVariant, screenshotAsset,
                                          specialFeatures}] for every catalog component
    POST /api/setup/ingest-brand-voice   {inputs} -> a draft brand-voice.json shape, not yet saved
    POST /api/setup/ingest-components    {inputs} -> a draft components.json shape, not yet saved
    POST /api/setup/save             {brandVoice?, components?} -> writes the reviewed draft(s) to /config

It binds to 127.0.0.1 and never to a public interface: the run endpoint fetches
arbitrary URLs on request, which is fine from your own machine and is not
something to expose to a network.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .export_web import build_payload
from .run_pipeline import BackgroundRun, RunOptions
from .store import load_discovery, load_results
from .llm_config import load_config, get_status, save_config, verify_provider_key

# Synchronize local LLM API keys with os.environ on startup
load_config()

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dashboard-react" / "dist"
DEV_PUBLIC = ROOT / "dashboard-react" / "public"

# One run at a time. Two crawls racing would interleave their writes into the
# same results folder, and a second "Run" click is far more likely to be
# impatience than a genuine request for concurrency.
_state: dict[str, object] = {"job": None, "results_dir": None}
_lock = threading.Lock()

# A separate single-job slot for the Broken Link Inspector's Site Scan --
# independent of the migration run above, since auditing a site's links has
# nothing to do with comparing two of them and the two should be startable
# at the same time.
_link_state: dict[str, object] = {"job": None}
_link_lock = threading.Lock()


def _payload(directory: Path) -> dict:
    return build_payload(load_results(directory), load_discovery(directory))


def _outcome_json(outcome) -> dict:
    """An AltTextOutcome as the camelCase shape the dashboard reads -- the
    same snake-to-camel boundary export_web.py draws for judge output, kept
    here since this feature has no export step of its own."""
    return {
        "generated": outcome.generated,
        "altText": outcome.alt_text,
        "isDecorative": outcome.is_decorative,
        "rationale": outcome.rationale,
        "model": outcome.model,
        "costUsd": round(outcome.cost_usd, 6),
        "cached": outcome.cached,
        "skippedReason": outcome.skipped_reason,
    }


def _budget(data: dict, default: float):
    from .llm_cost import Budget
    try:
        usd = float(data.get("budget") or default)
    except (TypeError, ValueError):
        usd = default
    return Budget(max_usd=max(0.01, min(usd, 50.0)))


def _content_input(src):
    """Optional source material ({kind, url | fileBase64, mediaType}) ->
    (ContentInput | None, error message | None)."""
    import base64

    from .content_writer.pipeline import INPUT_KINDS, ContentInput

    if not src:
        return None, None
    kind = str(src.get("kind") or "").strip()
    if kind not in INPUT_KINDS:
        return None, f"A valid source kind is required (one of {', '.join(INPUT_KINDS)})."
    if kind == "url":
        url = str(src.get("url") or "").strip()
        return (ContentInput(kind="url", url=url), None) if url else (None, "A URL is required.")
    b64 = str(src.get("fileBase64") or "")
    if not b64:
        return None, "File data is required for this source kind."
    try:
        blob = base64.b64decode(b64)
    except Exception:
        return None, "The file data could not be decoded."
    return ContentInput(kind=kind, data=blob,
                        media_type=str(src.get("mediaType") or "") or None), None


class Handler(SimpleHTTPRequestHandler):
    """Static files from the built app, plus the run API."""

    results_dir = ROOT / "data" / "run"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_web_root()), **kwargs)

    # -- helpers ---------------------------------------------------------

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):
        # The default logs every static asset, which buries the run lines.
        if "/api/" in (self.path or ""):
            sys.stderr.write(f"{self.command} {self.path}\n")

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        if self.path.startswith("/api/config/llm"):
            return self._json(get_status())
        if self.path.startswith("/api/data"):
            try:
                return self._json(_payload(self.results_dir))
            except Exception as exc:
                return self._json({"error": str(exc)}, 500)

        if self.path.startswith("/api/run"):
            with _lock:
                job = _state["job"]
            if job is None:
                return self._json({"state": "idle"})
            progress = job.snapshot()
            return self._json({
                "state": "running" if job.running else "finished",
                "progress": asdict(progress),
                "result": asdict(job.result) | {"out_dir": str(job.result.out_dir)}
                if job.result else None,
            })

        if self.path.startswith("/api/link-check/site"):
            with _link_lock:
                job = _link_state["job"]
            if job is None:
                return self._json({"state": "idle"})
            progress = job.snapshot()
            return self._json({
                "state": "running" if job.running else "finished",
                "progress": asdict(progress),
                "result": job.result.to_dict() if job.result else None,
            })

        if self.path.startswith("/api/config/status"):
            from .setup_engine.config_io import config_status
            return self._json(config_status())

        if self.path.startswith("/api/config/knowledge-base"):
            return self._config_knowledge_base_get()

        if self.path.startswith("/api/config/brand-voice"):
            return self._config_brand_voice_get()

        if self.path.startswith("/api/content-writer/templates"):
            return self._content_writer_templates()

        if self.path.startswith("/api/content-writer/history"):
            return self._content_writer_history_get()

        if self.path.startswith("/api/web-builder/catalog"):
            # Purpose blurbs for Phase 1's swap picker -- name/category/
            # purpose plus enough to render the New/Classic badge and a
            # thumbnail, not the full fields[] a card doesn't need.
            from .web_builder.catalog import load_catalog
            try:
                catalog = load_catalog()
            except OSError:
                return self._json({"components": []})
            return self._json({"components": [
                {"name": c.name, "category": c.category, "purpose": c.purpose,
                 "visualVariant": c.visual_variant, "screenshotAsset": c.screenshot_asset,
                 "specialFeatures": [sf.to_dict() for sf in c.special_features]}
                for c in catalog
            ]})

        # Client-side routes (/missing, /pages/3) are not files on disk, so
        # anything that is not an asset falls through to the app shell.
        path = self.translate_path(self.path)
        if not Path(path).is_file() and "." not in Path(self.path).name:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") == "/api/config/llm":
            data = self._body()
            return self._json(save_config(data))

        if self.path.rstrip("/") == "/api/config/llm/test":
            data = self._body()
            return self._json(verify_provider_key(data.get("provider", ""), data.get("key", "")))
        if self.path.rstrip("/") == "/api/run/cancel":
            with _lock:
                job = _state["job"]
            if job is not None:
                job.cancel()
            return self._json({"state": "cancelling"})

        if self.path.rstrip("/") == "/api/judge":
            return self._judge()

        if self.path.rstrip("/") == "/api/alt-text/image":
            return self._alt_text_image()

        if self.path.rstrip("/") == "/api/alt-text/images":
            return self._alt_text_images()

        if self.path.rstrip("/") == "/api/alt-text/page":
            return self._alt_text_page()

        if self.path.rstrip("/") == "/api/link-check/page":
            return self._link_check_page()

        if self.path.rstrip("/") == "/api/link-check/site/cancel":
            with _link_lock:
                job = _link_state["job"]
            if job is not None:
                job.cancel()
            return self._json({"state": "cancelling"})

        if self.path.rstrip("/") == "/api/link-check/site":
            return self._link_check_site()

        if self.path.rstrip("/") == "/api/content-writer/rewrite":
            return self._content_writer_rewrite()

        if self.path.rstrip("/") == "/api/content-writer/regenerate-section":
            return self._content_writer_regenerate_section()

        if self.path.rstrip("/") == "/api/content-writer/regenerate-block":
            return self._content_writer_regenerate_block()

        if self.path.rstrip("/") == "/api/content-writer/generate":
            return self._content_writer_generate()

        if self.path.rstrip("/") == "/api/content-writer/refine":
            return self._content_writer_refine()

        if self.path.rstrip("/") == "/api/content-writer/review":
            return self._content_writer_review()

        if self.path.rstrip("/") == "/api/content-writer/export":
            return self._content_writer_export()

        if self.path.rstrip("/") == "/api/content-writer/history/delete":
            return self._content_writer_history_delete()

        if self.path.rstrip("/") == "/api/config/knowledge-base":
            return self._config_knowledge_base_save()

        if self.path.rstrip("/") == "/api/web-builder/extract":
            return self._web_builder_extract()

        if self.path.rstrip("/") == "/api/web-builder/plan":
            return self._web_builder_plan()

        if self.path.rstrip("/") == "/api/web-builder/populate":
            return self._web_builder_populate()

        if self.path.rstrip("/") == "/api/web-builder/regenerate-component":
            return self._web_builder_regenerate_component()

        if self.path.rstrip("/") == "/api/setup/ingest-brand-voice":
            return self._setup_ingest_brand_voice()

        if self.path.rstrip("/") == "/api/setup/ingest-components":
            return self._setup_ingest_components()

        if self.path.rstrip("/") == "/api/setup/save":
            return self._setup_save()

        if self.path.rstrip("/") != "/api/run":
            return self._json({"error": "not found"}, 404)

        data = self._body()
        old_url = str(data.get("old") or "").strip()
        new_url = str(data.get("new") or "").strip()
        if not old_url or not new_url:
            return self._json({"error": "Both site roots are required."}, 400)
        if old_url == new_url:
            return self._json(
                {"error": "Those are the same URL - there is nothing to compare."},
                400)

        with _lock:
            job = _state["job"]
            if job is not None and job.running:
                return self._json(
                    {"error": "A run is already going. Stop it first."}, 409)

            options = RunOptions(
                max_pages=int(data.get("maxPages") or RunOptions.max_pages),
                max_pairs=int(data.get("maxPairs") or RunOptions.max_pairs),
                check_live=bool(data.get("checkLive", True)),
                match_titles=bool(data.get("matchTitles", True)),
                semantic=bool(data.get("semantic", True)),
                respect_robots=bool(data.get("respectRobots", False)),
                judge=bool(data.get("judge", False)),
                judge_budget_usd=float(data.get("judgeBudget") or 1.0),
                deep_crawl=bool(data.get("deepCrawl", False)),
            )
            _state["job"] = BackgroundRun(
                old_url, new_url, self.results_dir, options).start()

        return self._json({"state": "running"})


    def _judge(self):
        """Read one page with the LLM judge, on request.

        Per page rather than per run: it costs money, and the pages worth
        spending it on are the ones a reviewer has already opened and found
        ambiguous. Running it over a whole batch up front spends the most on
        the pages nobody looks at.
        """
        from .llm_judge import Judge, should_judge
        from .store import build_result, load_results, save_result

        data = self._body()
        try:
            wanted = int(data.get("id") or 0)
        except (TypeError, ValueError):
            wanted = 0

        results = load_results(self.results_dir)
        if not 1 <= wanted <= len(results):
            return self._json({"error": "No such page in this run."}, 404)

        result = results[wanted - 1]
        if not result.semantic.get("passages"):
            return self._json(
                {"error": "This pair has no passage comparison to read."}, 400)
        if not should_judge(result.tier, result.semantic):
            return self._json(
                {"error": "Nothing on this page is ambiguous enough to need the "
                          "judge."}, 400)

        outcome = Judge().judge_page(result.semantic["passages"],
                                     title=result.title)
        if not outcome.judged:
            # Missing credentials and a refusal both arrive here; the judge
            # already phrases them for a reader.
            return self._json({"error": outcome.skipped_reason}, 400)

        result.judge = outcome.to_dict()
        save_result(self.results_dir, result)
        return self._json({"state": "judged", "summary": outcome.summary,
                           "cost_usd": outcome.cost_usd})

    def _alt_text_image(self):
        """Describe one uploaded image, on request.

        The image travels as base64 in the JSON body rather than a multipart
        upload -- this server has no multipart parser, and adding one for a
        single-file form is not worth a dependency the rest of the project
        goes out of its way to avoid.
        """
        import base64
        from .alt_text import AltTextGenerator

        data = self._body()
        b64 = str(data.get("imageBase64") or "")
        media_type = str(data.get("mediaType") or "")
        if not b64 or not media_type:
            return self._json({"error": "An image and its file type are required."}, 400)
        try:
            image_bytes = base64.b64decode(b64)
        except Exception:
            return self._json({"error": "The image data could not be decoded."}, 400)

        outcome = AltTextGenerator().generate(image_bytes, media_type)
        if not outcome.generated:
            return self._json({"error": outcome.skipped_reason}, 400)
        return self._json({"state": "generated", **_outcome_json(outcome)})

    def _alt_text_images(self):
        """Describe a batch of directly-supplied images in one request --
        the Image Scan panel's "paste up to 20" / "upload up to 50" flows,
        both of which land here rather than N separate round trips so the
        whole batch shares one Budget the way one page scan does.

        Synchronous like the other alt-text endpoints: MAX_BATCH_IMAGES
        bounds the work, so this is not something /api/run's background job
        exists for.
        """
        import base64
        from .alt_text import AltTextGenerator, MAX_BATCH_IMAGES, generate_batch
        from .llm_cost import Budget

        data = self._body()
        items = data.get("images")
        if not isinstance(items, list) or not items:
            return self._json({"error": "At least one image is required."}, 400)

        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0

        decoded: list[tuple[str, bytes, str]] = []
        for i, item in enumerate(items):
            item = item if isinstance(item, dict) else {}
            name = str(item.get("name") or f"image {i + 1}")
            media_type = str(item.get("mediaType") or "")
            b64 = str(item.get("imageBase64") or "")
            try:
                image_bytes = base64.b64decode(b64) if b64 else b""
            except Exception:
                image_bytes = b""
            decoded.append((name, image_bytes, media_type))

        # A retry-heavy batch can burn up to 2 calls per image (see
        # AltTextGenerator.generate's degenerate-result retry) -- size the
        # call cap off the batch itself rather than the generic default of
        # 50, which a single 50-image batch could exhaust on its own even
        # with zero retries. The dollar Budget stays the real backstop.
        generator = AltTextGenerator(
            budget=Budget(max_usd=budget_usd, max_calls=max(100, len(decoded) * 2)))
        results = generate_batch(decoded, generator, max_images=MAX_BATCH_IMAGES)
        return self._json({
            "state": "generated",
            "images": [{"name": r.name, "outcome": _outcome_json(r.outcome)} for r in results],
            "budget": generator.budget.summary(noun="image described"),
        })

    def _alt_text_page(self):
        """Describe every non-decorative image on one page, on request.

        Synchronous like /api/judge: a page's image count is bounded by
        maxImages, so this is at most a couple of minutes of vision calls, not
        the many-page crawl /api/run exists to run in the background for.
        """
        from .alt_text import AltTextGenerator, DEFAULT_MAX_PAGE_IMAGES, scan_page
        from .fetch import Fetcher
        from .llm_cost import Budget

        data = self._body()
        url = str(data.get("url") or "").strip()
        if not url:
            return self._json({"error": "A page URL is required."}, 400)

        try:
            max_images = int(data.get("maxImages") or DEFAULT_MAX_PAGE_IMAGES)
        except (TypeError, ValueError):
            max_images = DEFAULT_MAX_PAGE_IMAGES
        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0
        include_header = bool(data.get("includeHeader"))
        include_footer = bool(data.get("includeFooter"))

        generator = AltTextGenerator(budget=Budget(max_usd=budget_usd))
        try:
            with Fetcher() as fetcher:
                page, results = scan_page(url, fetcher, generator, max_images=max_images,
                                          include_header=include_header,
                                          include_footer=include_footer)
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "scanned",
            "page": {"url": page.url, "title": page.title},
            "images": [
                {"src": r.src, "currentAlt": r.current_alt, "kind": r.kind,
                 "region": r.region,
                 "outcome": _outcome_json(r.outcome) if r.outcome else None}
                for r in results
            ],
            "budget": generator.budget.summary(noun="image described"),
        })

    def _link_check_page(self):
        """Check every link on one page, on request.

        Synchronous, like /api/alt-text/page: a single page's link count is
        bounded, so this is at most a couple dozen HTTP checks, not the
        many-page crawl Site Scan exists to run in the background for.
        """
        from .link_checker.pipeline import run_page_scan
        from .fetch import Fetcher

        data = self._body()
        url = str(data.get("url") or "").strip()
        if not url:
            return self._json({"error": "A page URL is required."}, 400)

        try:
            with Fetcher() as fetcher:
                result = run_page_scan(
                    url, fetcher,
                    include_header=bool(data.get("includeHeader")),
                    include_footer=bool(data.get("includeFooter")),
                    include_nav=bool(data.get("includeNav")))
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({"state": "scanned", **result.to_dict()})

    def _link_check_site(self):
        """Start a Site Scan in the background -- see /api/link-check/site
        (GET) for progress and /api/link-check/site/cancel to stop it."""
        from .link_checker.background import BackgroundLinkScan
        from .link_checker.crawl_site import DEFAULT_MAX_PAGES

        data = self._body()
        url = str(data.get("url") or "").strip()
        if not url:
            return self._json({"error": "A starting URL is required."}, 400)

        with _link_lock:
            job = _link_state["job"]
            if job is not None and job.running:
                return self._json(
                    {"error": "A link scan is already going. Stop it first."}, 409)

            try:
                max_pages = int(data.get("maxPages") or DEFAULT_MAX_PAGES)
            except (TypeError, ValueError):
                max_pages = DEFAULT_MAX_PAGES

            _link_state["job"] = BackgroundLinkScan(
                url, max_pages=max_pages,
                include_header=bool(data.get("includeHeader")),
                include_footer=bool(data.get("includeFooter")),
                include_nav=bool(data.get("includeNav")),
                deep=bool(data.get("deepCrawl")),
            ).start()

        return self._json({"state": "running"})

    def _content_writer_rewrite(self):
        """Rewrite a URL or uploaded file into the brand voice, on request.

        Synchronous, like /api/alt-text/page: bounded by how many sections a
        single page/file has, not an open-ended crawl.
        """
        import base64

        from .content_writer.models import RewriteOptions
        from .content_writer.pipeline import INPUT_KINDS, ContentInput, write_page
        from .fetch import Fetcher
        from .llm_cost import Budget

        data = self._body()
        kind = str(data.get("kind") or "").strip()
        if kind not in INPUT_KINDS:
            return self._json(
                {"error": f"A valid input kind is required (one of {', '.join(INPUT_KINDS)})."}, 400)

        url = str(data.get("url") or "").strip()
        file_bytes = None
        if kind == "url":
            if not url:
                return self._json({"error": "A URL is required."}, 400)
        else:
            b64 = str(data.get("fileBase64") or "")
            if not b64:
                return self._json({"error": "File data is required for this input kind."}, 400)
            try:
                file_bytes = base64.b64decode(b64)
            except Exception:
                return self._json({"error": "The file data could not be decoded."}, 400)

        input_ = ContentInput(
            kind=kind, url=url or None, data=file_bytes,
            media_type=str(data.get("mediaType") or "") or None)
        options = RewriteOptions(
            tone=[str(t) for t in (data.get("tone") or [])],
            length=str(data.get("length") or "Match original"),
            register_override=str(data.get("registerOverride") or "") or None,
        )
        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0

        try:
            with Fetcher() as fetcher:
                result = write_page(input_, options, fetcher=fetcher,
                                    budget=Budget(max_usd=budget_usd))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({"state": "rewritten", **result.to_dict()})

    def _content_writer_regenerate_section(self):
        """Regenerate one section without redoing the whole page. The whole
        section dict round-trips through Section.from_dict, so its links and
        media survive, and the redraft is reviewed like any other."""
        from . import llm_provider
        from .content_writer.generate import regenerate_section
        from .content_writer.models import Section, VoiceSettings

        data = self._body()
        section = Section.from_dict(data.get("section") or {})
        if not section.body.strip() and not (section.heading or "").strip():
            return self._json({"error": "A section with some text is required."}, 400)
        settings = VoiceSettings.from_dict(data.get("settings"))
        # The v1 frontend sent tone/length/registerOverride at the top level.
        if not data.get("settings"):
            settings.tone = [str(t) for t in (data.get("tone") or [])]
            settings.length = str(data.get("length") or "")
            settings.register = str(data.get("registerOverride") or "") or None

        try:
            new_section, rv, cost = regenerate_section(
                section, page_title=str(data.get("pageTitle") or ""),
                register=str(data.get("register") or "institutional"),
                settings=settings, template_key=str(data.get("templateKey") or "rewrite-page"),
                context_text=str(data.get("contextText") or ""),
                model=llm_provider.resolve_model(settings.model),
                budget=_budget(data, 0.50))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "rewritten",
            "section": new_section.to_dict(),
            "review": rv.to_dict(),
            "costUsd": round(cost, 6),
        })

    def _content_writer_regenerate_block(self):
        """Compose mode's per-block counterpart to regenerate-section: one
        block redrafted with the rest of the page as context, reviewed like
        any other draft."""
        from . import llm_provider
        from .content_writer.compose import regenerate_block
        from .content_writer.models import Block, VoiceSettings

        data = self._body()
        block = Block.from_dict(data.get("block") or {})
        if not (block.heading or block.body or block.quote_text or block.stat_value
                or block.links or block.image_alt):
            return self._json({"error": "A block with some content is required."}, 400)
        try:
            index = int(data.get("index"))
        except (TypeError, ValueError):
            return self._json({"error": "A block index is required."}, 400)
        all_blocks = [Block.from_dict(b) for b in (data.get("allBlocks") or [])]
        settings = VoiceSettings.from_dict(data.get("settings"))

        try:
            new_block, rv, cost = regenerate_block(
                block, index=index, page_title=str(data.get("pageTitle") or ""),
                all_blocks=all_blocks or [block], prompt=str(data.get("prompt") or ""),
                settings=settings, model=llm_provider.resolve_model(settings.model),
                budget=_budget(data, 0.50))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "rewritten",
            "block": new_block.to_dict(),
            "review": rv.to_dict(),
            "costUsd": round(cost, 6),
        })

    # -- Content Writer v2 ---------------------------------------------------

    def _content_writer_templates(self):
        from . import llm_provider
        from .content_writer import refine, templates
        from .content_writer.brand_voice import (
            brand_full_name, brand_name, is_uta, load_brand_voice, load_knowledge_base,
        )
        from .content_writer.models import (
            GOALS, LANGUAGES, MAX_ITEMS, MAX_VARIANTS, POINTS_OF_VIEW, READING_LEVELS,
            STRICTNESS_OPTIONS, TONE_OPTIONS,
        )

        try:
            bv = load_brand_voice()
        except (OSError, ValueError):
            return self._json({"error": "No brand voice is configured yet -- run setup first."}, 400)
        active = llm_provider.active_provider()
        model_providers = [
            {"key": p, "label": llm_provider.PROVIDER_LABELS.get(p, p),
             "models": llm_provider.MODEL_CATALOG.get(p, []),
             "defaultModel": llm_provider.recommended_model(p), "active": p == active}
            for p in llm_provider.configured_providers()
        ]
        return self._json({
            "brand": {"name": brand_name(bv), "fullName": brand_full_name(bv), "isUta": is_uta(bv)},
            "groups": list(templates.GROUPS),
            "templates": [t.to_dict() for t in templates.TEMPLATES],
            "audiences": bv["audiences"],
            "registers": [{"key": k.replace("_", "-"), "label": r.get("label", k)}
                          for k, r in bv["registers"].items()],
            "toneDimensions": bv["tone_dimensions"],
            "toneByContext": bv["tone_by_context"],
            "toneOptions": list(TONE_OPTIONS),
            "goals": [{"key": k, "label": v} for k, v in GOALS.items()],
            "readingLevels": list(READING_LEVELS),
            "pointsOfView": [{"key": k, "label": v} for k, v in POINTS_OF_VIEW.items()],
            "languages": list(LANGUAGES),
            "strictnessOptions": [{"key": k, "label": v} for k, v in STRICTNESS_OPTIONS.items()],
            "modelProviders": model_providers,
            "refineActions": [{"key": k, "label": refine.ACTION_LABELS[k]} for k in refine.ACTIONS],
            "knowledgeBaseCount": len(load_knowledge_base()),
            "maxVariants": MAX_VARIANTS,
            "maxItems": MAX_ITEMS,
        })

    def _content_writer_generate(self):
        """Any template: brief + settings (+ optional source) -> reviewed variants.
        Synchronous: bounded by MAX_VARIANTS drafts and their review retries."""
        from . import llm_provider
        from .content_writer import history
        from .content_writer.generate import GenerationRequest, generate
        from .content_writer.models import VoiceSettings
        from .fetch import Fetcher

        data = self._body()
        template_key = str(data.get("templateKey") or "").strip()
        brief = {str(k): str(v) for k, v in (data.get("brief") or {}).items()
                 if v is not None and str(v).strip()}
        source, err = _content_input(data.get("source"))
        if err:
            return self._json({"error": err}, 400)
        req = GenerationRequest(template_key=template_key, brief=brief,
                                settings=VoiceSettings.from_dict(data.get("settings")),
                                source=source)
        model = llm_provider.resolve_model(req.settings.model)
        try:
            with Fetcher() as fetcher:
                result = generate(req, fetcher=fetcher, budget=_budget(data, 2.0), model=model)
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        payload = result.to_dict()
        if data.get("saveHistory", True) and result.variants:
            first = result.variants[0]
            title = (first.page.page_title if first.page else
                     first.composed.title if first.composed else
                     (first.items[0]["text"] if first.items else template_key))
            request_record = {"templateKey": template_key, "brief": brief,
                              "settings": req.settings.to_dict(),
                              "source": {k: v for k, v in (data.get("source") or {}).items()
                                         if k != "fileBase64"}}
            try:
                payload["historyId"] = history.save(request_record, payload, title=title)
            except OSError:
                pass     # a history write failure never costs the writer their draft
        return self._json({"state": "generated", **payload})

    def _content_writer_refine(self):
        from . import llm_provider
        from .content_writer.models import VoiceSettings
        from .content_writer.refine import refine

        data = self._body()
        settings = VoiceSettings.from_dict(data.get("settings"))
        try:
            result = refine(
                str(data.get("text") or ""), str(data.get("action") or ""),
                instruction=str(data.get("instruction") or ""),
                context_text=str(data.get("contextText") or ""),
                template_key=str(data.get("templateKey") or "new-page"),
                settings=settings, model=llm_provider.resolve_model(settings.model),
                budget=_budget(data, 0.50))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"state": "refined", **result.to_dict()})

    def _content_writer_review(self):
        """Re-check a draft after the writer has edited it by hand."""
        from . import llm_provider
        from .content_writer import templates
        from .content_writer.brand_voice import load_brand_voice, load_knowledge_base
        from .content_writer.generate import AP_STYLE_TEMPLATES, allowed_corpus, request_summary
        from .content_writer.models import VoiceSettings
        from .content_writer.review import review

        data = self._body()
        try:
            t = templates.get(str(data.get("templateKey") or "new-page"))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        settings = VoiceSettings.from_dict(data.get("settings"))
        if data.get("blocks"):
            from .content_writer.models import Block
            from .content_writer.compose import units_from_blocks
            units = units_from_blocks([Block.from_dict(b) for b in data["blocks"]])
            kind = "blocks"
        elif data.get("items"):
            units = [{"text": str(i)} for i in data["items"]]
            kind = "items"
        else:
            units = [{"heading": s.get("heading"), "body": str(s.get("body") or "")}
                     for s in (data.get("sections") or [])]
            kind = "page"
        if not units:
            return self._json({"error": "There is nothing to review."}, 400)
        facts = load_knowledge_base() if settings.use_knowledge_base else []
        bv = load_brand_voice()
        corpus = allowed_corpus({str(k): str(v) for k, v in (data.get("brief") or {}).items()},
                                None, facts, settings, bv) + "\n" + str(data.get("sourceText") or "")
        try:
            rv = review(units, bv, output_kind=kind, char_limit=t.char_limit,
                        keywords=settings.keywords, reading_level=settings.reading_level,
                        allowed_corpus=corpus, request_summary=request_summary(t, settings),
                        ap_style=t.key in AP_STYLE_TEMPLATES, strictness=settings.strictness,
                        use_critic=bool(data.get("useCritic", True)),
                        model=llm_provider.resolve_model(settings.model),
                        budget=_budget(data, 0.25))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"state": "reviewed", "review": rv.to_dict()})

    def _content_writer_export(self):
        import base64

        from .content_writer.export import render

        data = self._body()
        try:
            name, mime, blob = render(
                str(data.get("format") or ""), title=str(data.get("title") or "Content"),
                subtitle=str(data.get("subtitle") or ""),
                sections=[{"heading": s.get("heading"), "body": str(s.get("body") or "")}
                          for s in (data.get("sections") or [])],
                items=[str(i) for i in (data.get("items") or [])],
                blocks=data.get("blocks") or None)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"filename": name, "mime": mime,
                           "base64": base64.b64encode(blob).decode("ascii")})

    def _content_writer_history_get(self):
        from .content_writer import history

        run_id = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if run_id == "history":
            return self._json({"runs": history.list_runs()})
        try:
            return self._json(history.load(run_id))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except FileNotFoundError:
            return self._json({"error": "No saved run with that id."}, 404)

    def _content_writer_history_delete(self):
        from .content_writer import history

        try:
            history.delete(str(self._body().get("id") or ""))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"state": "deleted", "runs": history.list_runs()})

    def _config_knowledge_base_get(self):
        from .content_writer.brand_voice import load_knowledge_base
        try:
            return self._json({"facts": load_knowledge_base()})
        except (OSError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

    def _config_knowledge_base_save(self):
        from .content_writer.brand_voice import load_knowledge_base, save_knowledge_base

        facts = self._body().get("facts")
        if not isinstance(facts, list):
            return self._json({"error": "facts must be a list."}, 400)
        save_knowledge_base([f for f in facts if isinstance(f, dict)])
        return self._json({"state": "saved", "facts": load_knowledge_base()})

    def _config_brand_voice_get(self):
        from .content_writer.brand_voice import load_brand_voice
        try:
            return self._json({"brandVoice": load_brand_voice()})
        except (OSError, ValueError):
            return self._json({"error": "No brand voice is configured yet."}, 404)

    def _web_builder_extract(self):
        """Turn a raw URL/file straight into a plain StructuredContent Web
        Builder can plan against -- for someone who already has good copy
        and just wants layout help, without running it through Content
        Writer's rewrite at all. No LLM call, no cost."""
        import base64

        from .content_writer.models import StructuredContent
        from .content_writer.pipeline import INPUT_KINDS, ContentInput, extract_content
        from .fetch import Fetcher

        data = self._body()
        kind = str(data.get("kind") or "").strip()
        if kind not in INPUT_KINDS:
            return self._json(
                {"error": f"A valid input kind is required (one of {', '.join(INPUT_KINDS)})."}, 400)

        url = str(data.get("url") or "").strip()
        file_bytes = None
        if kind == "url":
            if not url:
                return self._json({"error": "A URL is required."}, 400)
        else:
            b64 = str(data.get("fileBase64") or "")
            if not b64:
                return self._json({"error": "File data is required for this input kind."}, 400)
            try:
                file_bytes = base64.b64decode(b64)
            except Exception:
                return self._json({"error": "The file data could not be decoded."}, 400)

        input_ = ContentInput(
            kind=kind, url=url or None, data=file_bytes,
            media_type=str(data.get("mediaType") or "") or None)
        try:
            with Fetcher() as fetcher:
                extracted = extract_content(input_, fetcher=fetcher)
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        structured = StructuredContent(
            page_title=extracted.page_title, register="institutional",
            sections=list(extracted.sections), original_sections=list(extracted.sections),
            source_note=extracted.source_note, cost_usd=0.0,
            page_chrome_context=extracted.page_chrome_context)
        return self._json({"state": "extracted", **structured.to_dict()})

    def _web_builder_plan(self):
        """Phase 1: propose a layout plan for a piece of Content Writer
        output (or any StructuredContent-shaped body) -- one LLM call over
        the whole page's content plus the full component catalog from
        config/components.json, judging fit rather than keyword-matching."""
        from .content_writer.models import StructuredContent
        from .llm_cost import Budget
        from .web_builder.pipeline import make_plan

        data = self._body()
        structured = data.get("structuredContent")
        if not structured:
            return self._json({"error": "structuredContent is required."}, 400)

        content = StructuredContent.from_dict(structured)
        try:
            budget_usd = float(data.get("budget") or 0.5)
        except (TypeError, ValueError):
            budget_usd = 0.5

        try:
            plan = make_plan(content, budget=Budget(max_usd=budget_usd))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "planned", "costUsd": round(content.cost_usd, 6), **plan.to_dict()})

    def _web_builder_populate(self):
        """Phase 2: populate fields for an approved layout plan -- one
        model-driven, type-aware call per component -- then validate the
        result against the catalog's real constraints."""
        from .content_writer.models import StructuredContent
        from .llm_cost import Budget
        from .web_builder.models import LayoutPlan
        from .web_builder.pipeline import populate_approved_plan

        data = self._body()
        structured = data.get("structuredContent")
        plan_data = data.get("plan")
        if not structured or not plan_data:
            return self._json({"error": "structuredContent and plan are both required."}, 400)

        content = StructuredContent.from_dict(structured)
        plan = LayoutPlan.from_dict(plan_data)
        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0

        try:
            populated, problems = populate_approved_plan(content, plan, budget=Budget(max_usd=budget_usd))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "populated", "costUsd": round(content.cost_usd, 6),
            "components": [p.to_dict() for p in populated],
            "problems": problems,
        })

    def _web_builder_regenerate_component(self):
        """Per-card "Regenerate this component" -- re-populates just one
        approved row, leaving every other card untouched."""
        from .content_writer.models import StructuredContent
        from .llm_cost import Budget
        from .web_builder.models import LayoutPlanRow
        from .web_builder.pipeline import populate_one_component

        data = self._body()
        structured = data.get("structuredContent")
        row_data = data.get("row")
        if not structured or not row_data:
            return self._json({"error": "structuredContent and row are both required."}, 400)

        content = StructuredContent.from_dict(structured)
        row = LayoutPlanRow.from_dict(row_data)
        try:
            budget_usd = float(data.get("budget") or 0.25)
        except (TypeError, ValueError):
            budget_usd = 0.25

        try:
            populated = populate_one_component(content, row, budget=Budget(max_usd=budget_usd))
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({
            "state": "populated", "costUsd": round(content.cost_usd, 6),
            "component": populated.to_dict(),
        })

    @staticmethod
    def _parse_setup_inputs(raw_inputs) -> tuple[list, str]:
        """(inputs, error) -- shared by both ingest routes: each entry in the
        request's `inputs` array is the same {kind, url|fileBase64,
        mediaType} shape Content Writer's own upload already uses."""
        import base64

        from .content_writer.pipeline import INPUT_KINDS, ContentInput

        if not raw_inputs:
            return [], "At least one input (a URL or an uploaded file) is required."

        inputs = []
        for item in raw_inputs:
            kind = str(item.get("kind") or "").strip()
            if kind not in INPUT_KINDS:
                return [], f"A valid input kind is required (one of {', '.join(INPUT_KINDS)})."
            url = str(item.get("url") or "").strip()
            file_bytes = None
            if kind == "url":
                if not url:
                    return [], "A URL is required for a url-kind input."
            else:
                b64 = str(item.get("fileBase64") or "")
                if not b64:
                    return [], "File data is required for this input kind."
                try:
                    file_bytes = base64.b64decode(b64)
                except Exception:
                    return [], "The file data could not be decoded."
            inputs.append(ContentInput(
                kind=kind, url=url or None, data=file_bytes,
                media_type=str(item.get("mediaType") or "") or None))
        return inputs, ""

    def _setup_ingest_brand_voice(self):
        """Freeform brand-voice material -> a draft config shape, for the
        setup wizard's review screen. Not saved until /api/setup/save."""
        from .fetch import Fetcher
        from .llm_cost import Budget
        from .setup_engine.ingest_brand_voice import ingest_brand_voice

        data = self._body()
        inputs, error = self._parse_setup_inputs(data.get("inputs"))
        if error:
            return self._json({"error": error}, 400)

        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0

        try:
            with Fetcher() as fetcher:
                draft = ingest_brand_voice(inputs, fetcher=fetcher, budget=Budget(max_usd=budget_usd))
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({"state": "drafted", "draft": draft})

    def _setup_ingest_components(self):
        """Freeform component-library material -> a draft config shape."""
        from .fetch import Fetcher
        from .llm_cost import Budget
        from .setup_engine.ingest_components import ingest_components

        data = self._body()
        inputs, error = self._parse_setup_inputs(data.get("inputs"))
        if error:
            return self._json({"error": error}, 400)

        try:
            budget_usd = float(data.get("budget") or 1.0)
        except (TypeError, ValueError):
            budget_usd = 1.0

        try:
            with Fetcher() as fetcher:
                draft = ingest_components(inputs, fetcher=fetcher, budget=Budget(max_usd=budget_usd))
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 400)

        return self._json({"state": "drafted", "draft": draft})

    def _setup_save(self):
        """Writes a reviewed draft to /config -- the person has already seen
        and confirmed it on the review screen before this is called."""
        from .setup_engine.config_io import save_config

        data = self._body()
        brand_voice = data.get("brandVoice")
        components = data.get("components")
        if brand_voice is None and components is None:
            return self._json({"error": "Nothing to save -- provide brandVoice and/or components."}, 400)

        status = save_config(brand_voice=brand_voice, components=components)
        return self._json({"state": "saved", **status})


def _web_root() -> Path:
    """Prefer the built app; fall back to public/ so the API works before a build."""
    return DIST if (DIST / "index.html").is_file() else DEV_PUBLIC


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.server",
        description="Serve the MavDitto dashboard and run comparisons from it.")
    ap.add_argument("--results", default=str(ROOT / "data" / "run"), metavar="DIR",
                    help="where runs read and write results")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="localhost by default; the run endpoint fetches "
                         "arbitrary URLs on request, so do not expose it")
    args = ap.parse_args(argv)

    Handler.results_dir = Path(args.results)
    Handler.results_dir.mkdir(parents=True, exist_ok=True)

    if not (DIST / "index.html").is_file():
        print("note: dashboard-react/dist not found - build it with "
              "`cd dashboard-react && npm run build`", file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MavDitto on http://{args.host}:{args.port}")
    print(f"results in {Handler.results_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
