"""Post-scheduling MCP tools, registered on import by server.py.

Instagram's API can't schedule posts natively, so these tools manage a local
queue (schedule_store) and a separate worker (scheduler.py, run by cron/launchd)
publishes each job at its time. run_due_posts lets you publish due jobs on
demand too (e.g. if you don't run the worker).

Tools: schedule_post, list_scheduled, cancel_scheduled, run_due_posts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import schedule_store
from core import InstagramAPIError, err, mcp, resolve
from publishing import publish_now, validate_media


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def schedule_post(
    publish_at: str,
    kind: str = "photo",
    account: str | None = None,
    caption: str = "",
    image_url: str | None = None,
    video_url: str | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Queue a post to publish later. Instagram has no native scheduling, so a
    worker (scheduler.py) publishes it at `publish_at`.

    `publish_at` = ISO-8601, e.g. "2026-06-20T14:00:00-03:00" or "...Z" (UTC).
    `kind` = photo | reel | carousel | story.
    Provide the media for the kind: photo/story -> image_url (or video_url for a
    video story); reel -> video_url; carousel -> image_urls (2-10). URLs must be
    public HTTPS. Returns the job id (use it to cancel).
    """
    try:
        when = schedule_store.parse_when(publish_at)
    except (ValueError, TypeError):
        return {"ok": False, "error": f"publish_at not a valid ISO-8601 datetime: {publish_at!r}"}
    now = datetime.now(timezone.utc)
    if when <= now:
        return {"ok": False, "error": "publish_at is in the past — pick a future time."}

    media: dict[str, Any] = {}
    if image_url:
        media["image_url"] = image_url
    if video_url:
        media["video_url"] = video_url
    if image_urls:
        media["image_urls"] = image_urls
    bad = validate_media(kind, media)
    if bad:
        return {"ok": False, "error": bad}

    # Resolve now so a bad account fails fast instead of at publish time.
    try:
        await resolve(account)
    except InstagramAPIError as exc:
        return err(exc)
    if not account:
        return {"ok": False, "error": "account required so the worker knows which account to post to."}

    job = schedule_store.add_job(account, kind, media, caption, when, now=now)
    return {"ok": True, "job_id": job["id"], "publish_at": job["publish_at"], "status": "pending"}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_scheduled(status: str | None = None, account: str | None = None) -> dict[str, Any]:
    """List queued posts. Filter by `status` (pending|published|failed|canceled)
    and/or `account`. Sorted by publish time.
    """
    jobs = schedule_store.list_jobs(status=status, account=account)
    return {"ok": True, "count": len(jobs), "jobs": jobs}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
async def cancel_scheduled(job_id: str) -> dict[str, Any]:
    """Cancel a pending scheduled post by its job id. Already-published posts
    can't be canceled here (delete them on Instagram).
    """
    job = schedule_store.cancel_job(job_id)
    if not job:
        return {"ok": False, "error": f"no pending job with id {job_id!r} (already ran/canceled?)."}
    return {"ok": True, "job_id": job_id, "status": "canceled"}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def run_due_posts() -> dict[str, Any]:
    """Publish every queued post whose time has passed, right now. Normally the
    scheduler.py worker does this on a cron; call this to flush due posts on
    demand (or if you don't run the worker). Safe to call repeatedly.
    """
    due = schedule_store.due_jobs()
    results = []
    for job in due:
        try:
            ig_id, token = await resolve(job["account"])
            media_id = await publish_now(ig_id, token, job["kind"], job["media"], job.get("caption", ""))
            schedule_store.mark(job["id"], "published", media_id=media_id)
            results.append({"job_id": job["id"], "ok": True, "media_id": media_id})
        except InstagramAPIError as exc:
            schedule_store.mark(job["id"], "failed", error=exc.as_text())
            results.append({"job_id": job["id"], "ok": False, "error": exc.as_text()})
    return {"ok": True, "published": sum(1 for r in results if r["ok"]), "results": results}
