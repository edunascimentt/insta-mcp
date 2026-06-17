"""Configuration loading for the Instagram MCP server (multi-BM agency).

The agency runs ~one Business Manager (BM) per client, and a System User token
only sees its own BM. So the server holds **many** tokens — one per BM — and
routes each call to the token that owns the target account.

Token sources, in priority order:
  1. tokens.json next to this file:  [{"label": "Domino BM", "token": "EAA..."}]
  2. env IG_ACCESS_TOKENS  (comma-separated tokens)
  3. env IG_ACCESS_TOKEN   (single token — back-compat)

Secrets never hard-coded. tokens.json is gitignored.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
TOKENS_PATH = HERE / "tokens.json"

# Load .env if present; real environment variables take precedence.
load_dotenv(ENV_PATH, override=False)

# Facebook Graph API base. IG business accounts are reached as /{ig-id}/...
GRAPH_BASE = "https://graph.facebook.com"
GRAPH_VERSION = os.environ.get("IG_GRAPH_VERSION", "v22.0")


def get_tokens() -> list[dict[str, str]]:
    """Return [{'label': str, 'token': str}, ...] from the best available source."""
    # 1. tokens.json
    if TOKENS_PATH.exists():
        try:
            raw = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = []
        out: list[dict[str, str]] = []
        for i, entry in enumerate(raw if isinstance(raw, list) else []):
            if isinstance(entry, str) and entry.strip():
                out.append({"label": f"bm{i + 1}", "token": entry.strip()})
            elif isinstance(entry, dict) and entry.get("token"):
                out.append(
                    {"label": str(entry.get("label") or f"bm{i + 1}"), "token": entry["token"].strip()}
                )
        if out:
            return out

    # 2. IG_ACCESS_TOKENS (comma-separated)
    multi = os.environ.get("IG_ACCESS_TOKENS", "").strip()
    if multi:
        return [
            {"label": f"bm{i + 1}", "token": t.strip()}
            for i, t in enumerate(multi.split(","))
            if t.strip()
        ]

    # 3. single IG_ACCESS_TOKEN
    single = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if single:
        return [{"label": "default", "token": single}]

    return []


def get_default_account() -> str | None:
    """Optional default account (username or ig id) when a tool omits one."""
    val = os.environ.get("IG_DEFAULT_ACCOUNT", "").strip()
    return val or None


def get_app_id() -> str | None:
    val = os.environ.get("IG_APP_ID", "").strip()
    return val or None


def get_app_secret() -> str | None:
    val = os.environ.get("IG_APP_SECRET", "").strip()
    return val or None
