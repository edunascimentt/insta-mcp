"""Instagram Direct Message tools (Instagram Messaging API), registered on
import by server.py.

Needs the `instagram_manage_messages` scope on the System User token. Meta's
standard messaging window applies: you can freely message a user only within
24h of their last message; outside that, sending is restricted.

`recipient_id` is the Instagram-scoped user id (IGSID) found in a
conversation's participants — not a public @username.
"""

from __future__ import annotations

import json
from typing import Any

from core import InstagramAPIError, client, err, resolve, token_for, mcp


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_dm_conversations(account: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List recent DM conversations for `account`. Each has id, participants,
    and last-updated time. `limit` clamped 1-50.
    """
    limit = max(1, min(int(limit), 50))
    try:
        ig_id, token = await resolve(account)
        data = await client().get(
            f"{ig_id}/conversations",
            token,
            {"platform": "instagram", "fields": "id,updated_time,participants", "limit": limit},
        )
        return {"ok": True, "account": account, "conversations": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_dm_messages(
    conversation_id: str, account: str | None = None, limit: int = 25
) -> dict[str, Any]:
    """Read messages in a conversation (from list_dm_conversations).
    Returns sender, recipient, text, and time. Pass `account` when multi-BM.
    `limit` clamped 1-50.
    """
    limit = max(1, min(int(limit), 50))
    try:
        token = await token_for(account)
        fields = f"messages.limit({limit}){{id,from,to,message,created_time}}"
        data = await client().get(conversation_id, token, {"fields": fields})
        msgs = data.get("messages", {}).get("data", [])
        return {"ok": True, "conversation_id": conversation_id, "messages": msgs}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def send_dm(recipient_id: str, text: str, account: str | None = None) -> dict[str, Any]:
    """Send a DM from `account` to a user. `recipient_id` is the IGSID from a
    conversation's participants. Subject to Meta's 24h messaging window.
    """
    if not text.strip():
        return {"ok": False, "error": "text cannot be empty"}
    try:
        ig_id, token = await resolve(account)
        data = await client().post(
            f"{ig_id}/messages",
            token,
            {
                "recipient": json.dumps({"id": recipient_id}),
                "message": json.dumps({"text": text}),
            },
        )
        return {
            "ok": True,
            "account": account,
            "recipient_id": data.get("recipient_id", recipient_id),
            "message_id": data.get("message_id"),
        }
    except InstagramAPIError as exc:
        return err(exc)
