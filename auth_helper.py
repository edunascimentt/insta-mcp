"""Token helper CLI for the Instagram MCP server (multi-BM agency).

Recommended token per client BM: a **System User token** generated in that
BM's Business Settings (can be set non-expiring). Store them in tokens.json.

Commands:
  me                             verify every configured token, print its owner
  accounts                       list every IG account across all tokens
  exchange <short_lived_token>   user token -> long-lived (~60d); prints it

`exchange` needs IG_APP_ID + IG_APP_SECRET in .env.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

import config
from config import GRAPH_BASE, GRAPH_VERSION
from instagram_client import InstagramAPIError, InstagramClient

BASE = f"{GRAPH_BASE}/{GRAPH_VERSION}"


def cmd_exchange(short_token: str) -> int:
    app_id, app_secret = config.get_app_id(), config.get_app_secret()
    if not (app_id and app_secret):
        print("ERROR: set IG_APP_ID and IG_APP_SECRET in .env first (Meta app dashboard).")
        return 1
    resp = httpx.get(
        f"{BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30.0,
    )
    data = resp.json()
    if "access_token" not in data:
        print(f"ERROR exchanging token: {data}")
        return 1
    print(f"Long-lived token (~{data.get('expires_in', '?')}s):\n{data['access_token']}")
    print("Add it to tokens.json. (Tip: System User tokens never expire — see README.)")
    return 0


def cmd_me() -> int:
    tokens = config.get_tokens()
    if not tokens:
        print("ERROR: no tokens configured (tokens.json / IG_ACCESS_TOKEN).")
        return 1
    ok = True
    for entry in tokens:
        resp = httpx.get(
            f"{BASE}/me",
            params={"fields": "id,name", "access_token": entry["token"]},
            timeout=30.0,
        )
        data = resp.json()
        if "error" in data:
            ok = False
            print(f"  [FAIL] {entry['label']}: {data['error'].get('message')}")
        else:
            print(f"  [OK]   {entry['label']}: {data.get('name')} (id={data.get('id')})")
    return 0 if ok else 1


def cmd_accounts() -> int:
    tokens = config.get_tokens()
    if not tokens:
        print("ERROR: no tokens configured (tokens.json / IG_ACCESS_TOKEN).")
        return 1

    async def run() -> int:
        client = InstagramClient(tokens)
        try:
            accounts = await client.list_accounts()
        except InstagramAPIError as exc:
            print(f"ERROR: {exc.as_text()}")
            return 1
        finally:
            await client.aclose()

        real = [a for a in accounts if "ig_id" in a]
        errors = [a for a in accounts if "error" in a]
        print(f"Found {len(real)} Instagram account(s) across {len(tokens)} BM(s):")
        for a in real:
            print(
                f"  @{a['username']:<22} id={a['ig_id']:<18} "
                f"followers={a.get('followers_count', '?'):<8} "
                f"[{a['business']}] (page: {a['page_name']})"
            )
        for e in errors:
            print(f"  !! BM '{e['business']}' token error: {e['error']}")
        print("\nUse a @username (without @) or the id as the `account` arg.")
        return 0 if real else 1

    return asyncio.run(run())


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "exchange":
        if len(argv) < 2:
            print("usage: python auth_helper.py exchange <short_lived_token>")
            return 1
        return cmd_exchange(argv[1])
    if cmd == "me":
        return cmd_me()
    if cmd == "accounts":
        return cmd_accounts()
    print(f"unknown command: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
