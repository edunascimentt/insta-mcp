"""JSON-backed store of scheduled posts.

Instagram's API has no native post scheduling (only Facebook Pages do), so we
keep a local queue and a worker (scheduler.py) publishes each job when its
publish_at time arrives. This module is the queue: append/list/cancel jobs and
find the ones that are due, with atomic file writes so a crash mid-write can't
corrupt the queue.

Job shape:
  {
    "id": "8 hex chars",
    "account": "username or ig id",
    "kind": "photo|reel|carousel|story",
    "media": {...},                      # see publishing.py
    "caption": "...",
    "publish_at": "2026-06-20T14:00:00+00:00",   # ISO 8601, tz-aware
    "status": "pending|published|failed|canceled",
    "created_at": "ISO",
    "published_media_id": null,
    "error": null,
    "attempts": 0
  }

The file (scheduled.json) lives next to this module and is gitignored — it can
contain client captions/URLs.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STORE_PATH = HERE / "scheduled.json"


def parse_when(value: str) -> datetime:
    """Parse an ISO-8601 string to a tz-aware UTC datetime. Naive -> assumed UTC."""
    s = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load() -> list[dict[str, Any]]:
    if not STORE_PATH.exists():
        return []
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return raw if isinstance(raw, list) else []


def _save(jobs: list[dict[str, Any]]) -> None:
    """Atomic write: dump to a temp file in the same dir, then replace."""
    tmp = STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STORE_PATH)


def add_job(
    account: str,
    kind: str,
    media: dict[str, Any],
    caption: str,
    publish_at: datetime,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append a pending job. publish_at must be tz-aware UTC."""
    now = now or datetime.now(timezone.utc)
    job = {
        "id": uuid.uuid4().hex[:8],
        "account": account,
        "kind": kind,
        "media": media,
        "caption": caption,
        "publish_at": publish_at.isoformat(),
        "status": "pending",
        "created_at": now.isoformat(),
        "published_media_id": None,
        "error": None,
        "attempts": 0,
    }
    jobs = _load()
    jobs.append(job)
    _save(jobs)
    return job


def list_jobs(*, status: str | None = None, account: str | None = None) -> list[dict[str, Any]]:
    jobs = _load()
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    if account:
        acc = account.strip().lstrip("@").lower()
        jobs = [j for j in jobs if str(j.get("account", "")).lstrip("@").lower() == acc]
    return sorted(jobs, key=lambda j: j.get("publish_at", ""))


def cancel_job(job_id: str) -> dict[str, Any] | None:
    """Mark a pending job canceled. Returns the job, or None if not found/not pending."""
    jobs = _load()
    for j in jobs:
        if j.get("id") == job_id and j.get("status") == "pending":
            j["status"] = "canceled"
            _save(jobs)
            return j
    return None


def due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    """Pending jobs whose publish_at has passed."""
    now = now or datetime.now(timezone.utc)
    out = []
    for j in _load():
        if j.get("status") != "pending":
            continue
        try:
            when = parse_when(j["publish_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if when <= now:
            out.append(j)
    return out


def mark(job_id: str, status: str, *, media_id: str | None = None, error: str | None = None) -> None:
    """Update a job's outcome (published/failed) and bump attempts."""
    jobs = _load()
    for j in jobs:
        if j.get("id") == job_id:
            j["status"] = status
            j["attempts"] = int(j.get("attempts") or 0) + 1
            if media_id is not None:
                j["published_media_id"] = media_id
            if error is not None:
                j["error"] = error
            break
    _save(jobs)
