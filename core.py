"""Shared core for the Instagram MCP server: the FastMCP instance, the lazy
client singleton, and small helpers used by both the base tools (server.py)
and the extended tools (tools_extra.py).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

import config
from instagram_client import InstagramAPIError, InstagramClient

mcp = FastMCP("instagram")

_client: InstagramClient | None = None


def client() -> InstagramClient:
    global _client
    if _client is None:
        _client = InstagramClient(config.get_tokens())
    return _client


def err(exc: InstagramAPIError) -> dict[str, Any]:
    """Uniform error payload returned from a tool (never raises to transport)."""
    return {"ok": False, "error": exc.as_text(), "code": exc.code}


async def resolve(account: str | None) -> tuple[str, str]:
    """Resolve account (or IG_DEFAULT_ACCOUNT) to (ig_id, token)."""
    return await client().resolve_account(account or config.get_default_account())


async def token_for(account: str | None) -> str:
    return await client().token_for(account or config.get_default_account())


# Account-level insight metrics that use the modern total_value shape.
TOTAL_VALUE_METRICS = ["reach", "views", "total_interactions", "accounts_engaged"]

__all__ = [
    "mcp",
    "client",
    "err",
    "resolve",
    "token_for",
    "TOTAL_VALUE_METRICS",
    "InstagramAPIError",
    "config",
]
