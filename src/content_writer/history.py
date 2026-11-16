"""Saved Content Writer runs: one JSON file per run under
data/content_writer_history/, so a writer can reopen yesterday's draft.
Plain files, like everything else this tool persists."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HISTORY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "content_writer_history"
MAX_RUNS = 200

_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")


def _path(run_id: str, directory: Path) -> Path:
    # The id arrives from a URL -- only ids this module minted are accepted,
    # so nothing can address a file outside the history directory.
    if not _ID.match(run_id or ""):
        raise ValueError("not a valid history id")
    return directory / f"{run_id}.json"


def save(request: dict[str, Any], result: dict[str, Any], *, title: str = "",
         directory: Path = HISTORY_DIR) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    record = {"id": run_id, "createdAt": now.isoformat(timespec="seconds"),
              "title": title, "request": request, "result": result}
    _path(run_id, directory).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    _prune(directory)
    return run_id


def _prune(directory: Path) -> None:
    files = sorted(directory.glob("*.json"))
    for old in files[:-MAX_RUNS]:
        old.unlink(missing_ok=True)


def list_runs(directory: Path = HISTORY_DIR) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    out = []
    for p in sorted(directory.glob("*.json"), reverse=True):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        req, res = rec.get("request", {}), rec.get("result", {})
        out.append({"id": rec.get("id", p.stem), "createdAt": rec.get("createdAt", ""),
                    "title": rec.get("title", ""), "templateKey": req.get("templateKey", ""),
                    "variants": len(res.get("variants", [])),
                    "costUsd": res.get("costUsd", 0)})
    return out


def load(run_id: str, directory: Path = HISTORY_DIR) -> dict[str, Any]:
    p = _path(run_id, directory)
    if not p.is_file():
        raise FileNotFoundError(run_id)
    return json.loads(p.read_text(encoding="utf-8"))


def delete(run_id: str, directory: Path = HISTORY_DIR) -> None:
    _path(run_id, directory).unlink(missing_ok=True)
