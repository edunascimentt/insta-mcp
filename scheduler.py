"""Scheduled-post worker.

Instagram's API can't schedule posts, so this process publishes queued jobs
(schedule_store) when their time arrives. Run it one of two ways:

  python scheduler.py --once     # publish anything due now, then exit (for cron)
  python scheduler.py --watch    # loop forever, checking every 60s (for launchd/service)

Cron (mac/Linux), every minute:
  * * * * * cd /Users/you/insta-mcp && /usr/bin/python3 scheduler.py --once >> scheduler.log 2>&1

Windows Task Scheduler: action `python C:\path\insta-mcp\scheduler.py --once`,
trigger "every 1 minute".

It uses the same tokens/registry as the MCP server, so a job posts exactly like
the interactive publish_* tools.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import schedule_store
from core import InstagramAPIError, client, resolve
from publishing import publish_now


def _log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{stamp}] {msg}", flush=True)


async def run_once() -> int:
    """Publish every due job. Returns count published successfully."""
    due = schedule_store.due_jobs()
    if not due:
        return 0
    published = 0
    for job in due:
        jid = job.get("id")
        try:
            ig_id, token = await resolve(job["account"])
            media_id = await publish_now(ig_id, token, job["kind"], job["media"], job.get("caption", ""))
            schedule_store.mark(jid, "published", media_id=media_id)
            _log(f"published job {jid} ({job['kind']} -> {job['account']}) media_id={media_id}")
            published += 1
        except InstagramAPIError as exc:
            schedule_store.mark(jid, "failed", error=exc.as_text())
            _log(f"FAILED job {jid} ({job['kind']} -> {job.get('account')}): {exc.as_text()}")
        except Exception as exc:  # never let one bad job kill the worker
            schedule_store.mark(jid, "failed", error=str(exc))
            _log(f"ERROR job {jid}: {exc}")
    return published


async def watch(interval: float = 60.0) -> None:
    _log(f"watcher started (every {interval:.0f}s)")
    try:
        while True:
            try:
                n = await run_once()
                if n:
                    _log(f"cycle published {n}")
            except Exception as exc:
                _log(f"cycle error: {exc}")
            await asyncio.sleep(interval)
    finally:
        await client().aclose()


def main() -> int:
    ap = argparse.ArgumentParser(description="Instagram scheduled-post worker")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="publish due jobs once, then exit (cron)")
    g.add_argument("--watch", action="store_true", help="loop forever, checking periodically")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between checks in --watch")
    args = ap.parse_args()

    if args.watch:
        try:
            asyncio.run(watch(args.interval))
        except KeyboardInterrupt:
            _log("watcher stopped")
        return 0

    # default + --once
    async def _go() -> int:
        try:
            return await run_once()
        finally:
            await client().aclose()

    n = asyncio.run(_go())
    _log(f"done - published {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
