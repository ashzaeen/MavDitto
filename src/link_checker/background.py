"""Site Scan on its own thread, with progress a GUI can poll -- the same
shape as `run_pipeline.BackgroundRun`, since the dashboard needs the same
thing here: start it, keep drawing, ask how it is going, cancel it, and
never block the server's request thread for however long a crawl takes.
"""

from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass

from ..fetch import Fetcher
from .models import LinkScanResult
from .pipeline import run_site_scan


@dataclass
class LinkScanProgress:
    stage: str = "starting"
    message: str = "queued"
    done: int = 0
    total: int = 0
    finished: bool = False
    failed: bool = False
    error: str = ""


class BackgroundLinkScan:
    def __init__(self, url: str, *, max_pages: int, include_header: bool,
                include_footer: bool, include_nav: bool, deep: bool = False):
        self.url = url
        self.max_pages = max_pages
        self.include_header = include_header
        self.include_footer = include_footer
        self.include_nav = include_nav
        self.deep = deep
        self.progress = LinkScanProgress()
        self.result: LinkScanResult | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> "BackgroundLinkScan":
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()
        return self

    def _work(self) -> None:
        def on_progress(stage: str, message: str, done: int, total: int) -> None:
            with self._lock:
                self.progress = LinkScanProgress(stage=stage, message=message,
                                                done=done, total=total)

        try:
            with Fetcher() as fetcher:
                self.result = run_site_scan(
                    self.url, fetcher, max_pages=self.max_pages,
                    include_header=self.include_header, include_footer=self.include_footer,
                    include_nav=self.include_nav, deep=self.deep,
                    cancel=self._cancel, on_progress=on_progress)
            with self._lock:
                if self._cancel.is_set():
                    self.progress = LinkScanProgress(
                        stage="stopped", message="stopped", finished=True, failed=True,
                        error="stopped before finishing")
                else:
                    self.progress = LinkScanProgress(
                        stage="done", message="finished", finished=True,
                        done=self.progress.done, total=self.progress.total)
        except Exception as exc:
            with self._lock:
                self.progress = LinkScanProgress(
                    stage="failed", message=str(exc), finished=True, failed=True,
                    error=f"{type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)

    def snapshot(self) -> LinkScanProgress:
        with self._lock:
            return LinkScanProgress(**vars(self.progress))

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
