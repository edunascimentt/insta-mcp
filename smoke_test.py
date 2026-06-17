"""Live, read-only smoke test for the Instagram MCP server.

Run AFTER putting IG_ACCESS_TOKEN in .env:

    python smoke_test.py                 # tests the first discovered account
    python smoke_test.py <account>       # tests a specific username or ig id

Exercises only non-destructive tools (no publishing). Prints a pass/fail line
per check so you can see exactly what works against the real API.
"""

from __future__ import annotations

import asyncio
import sys

import server


def _show(label: str, result: dict) -> bool:
    ok = bool(result.get("ok"))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}")
    if not ok:
        print(f"       -> {result.get('error')}")
    return ok


async def run(account_arg: str | None) -> int:
    print("== Instagram MCP smoke test (read-only) ==\n")

    # 1. Discover accounts.
    accounts = await server.list_accounts()
    if not _show("list_accounts", accounts):
        print("\nCannot continue without account discovery. Check token + asset access.")
        return 1
    found = accounts["accounts"]
    print(f"       found {len(found)} account(s): " + ", ".join("@" + a["username"] for a in found))

    # Pick the account to drill into.
    account = account_arg or (found[0]["username"] if found else None)
    if not account:
        print("\nNo accounts to test.")
        return 1
    print(f"\n-- drilling into: {account} --")

    # 2. Account info.
    _show("get_account_info", await server.get_account_info(account))

    # 3. Account insights (last 7 days).
    _show("get_account_insights", await server.get_account_insights(account, days=7))

    # 4. Demographics (needs >=100 followers).
    _show("get_audience_demographics", await server.get_audience_demographics(account, "country"))

    # 5. Recent media.
    media = await server.list_recent_media(account, limit=5)
    _show("list_recent_media", media)

    # 6. Per-post insights + comments on the newest post, if any.
    posts = media.get("media", []) if media.get("ok") else []
    if posts:
        mid = posts[0]["id"]
        print(f"       newest media id: {mid}")
        _show("get_media_insights", await server.get_media_insights(mid, account=account))
        _show("get_media_comments", await server.get_media_comments(mid, account=account, limit=5))
    else:
        print("[skip] media insights/comments — no posts found")

    print("\nDone. (Publishing tools not tested — run those manually when ready.)")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(asyncio.run(run(arg)))
