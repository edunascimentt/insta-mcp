"""Instagram MCP server (multi-BM agency, multi-token).

Exposes Instagram Graph API insights + publishing as MCP tools over stdio,
across every Instagram account reachable by a set of Business Manager System
User tokens (one per client BM). Calls auto-route to the owning token.

Base tools live here; extended tools (reports, competitor, deeper insights,
moderation) live in tools_extra.py and register on import.

Per-account tools take an `account` argument (username or ig id). Call
`list_accounts` first to see what's available. If IG_DEFAULT_ACCOUNT is set,
`account` may be omitted to use it. Tools degrade gracefully: missing/expired
token or unknown account returns a clear, actionable error.
"""

from __future__ import annotations

from typing import Any

from core import TOTAL_VALUE_METRICS, InstagramAPIError, client, config, err, mcp, resolve, token_for


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_accounts(refresh: bool = False) -> dict[str, Any]:
    """List every Instagram account across all configured client BMs.

    Each row has business (BM label), page name, ig id, username, followers.
    A BM whose token failed shows an `error` row. Use a returned `username`
    (or `ig_id`) as the `account` arg for other tools. `refresh=true` re-fetches.
    """
    try:
        accounts = await client().list_accounts(refresh=refresh)
        return {"ok": True, "count": len([a for a in accounts if "ig_id" in a]), "accounts": accounts}
    except InstagramAPIError as exc:
        return err(exc)


# ---------------------------------------------------------------------------
# Read-only tools (per account)
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_account_info(account: str | None = None) -> dict[str, Any]:
    """Get an account's profile and counts. `account` = username or ig id."""
    try:
        ig_id, token = await resolve(account)
        fields = (
            "id,username,name,biography,followers_count,follows_count,"
            "media_count,profile_picture_url,website"
        )
        data = await client().get(ig_id, token, {"fields": fields})
        return {"ok": True, "account": data}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_account_insights(account: str | None = None, days: int = 7) -> dict[str, Any]:
    """Account insights over the last N days (reach, views, interactions,
    accounts engaged). `account` = username or ig id. `days` clamped 1-30.
    Some metrics need >=100 followers.
    """
    days = max(1, min(int(days), 30))
    try:
        ig_id, token = await resolve(account)
        params = {
            "metric": ",".join(TOTAL_VALUE_METRICS),
            "metric_type": "total_value",
            "period": "day",
        }
        data = await client().get(f"{ig_id}/insights", token, params)
        results = {}
        for item in data.get("data", []):
            results[item.get("name")] = item.get("total_value", {}).get("value")
        return {"ok": True, "account": account, "period_days": days, "insights": results}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_audience_demographics(
    account: str | None = None, breakdown: str = "country"
) -> dict[str, Any]:
    """Follower demographics by country / city / age / gender.
    `account` = username or ig id. Requires >=100 followers.
    """
    valid = {"country", "city", "age", "gender"}
    if breakdown not in valid:
        return {"ok": False, "error": f"breakdown must be one of {sorted(valid)}"}
    try:
        ig_id, token = await resolve(account)
        params = {
            "metric": "follower_demographics",
            "period": "lifetime",
            "metric_type": "total_value",
            "breakdown": breakdown,
        }
        data = await client().get(f"{ig_id}/insights", token, params)
        out: dict[str, Any] = {}
        for item in data.get("data", []):
            for b in item.get("total_value", {}).get("breakdowns", []):
                for res in b.get("results", []):
                    key = ",".join(res.get("dimension_values", []))
                    out[key] = res.get("value")
        return {"ok": True, "account": account, "breakdown": breakdown, "demographics": out}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_recent_media(account: str | None = None, limit: int = 12) -> dict[str, Any]:
    """Recent posts (caption, type, likes, comments, permalink).
    `account` = username or ig id. `limit` clamped 1-50.
    """
    limit = max(1, min(int(limit), 50))
    try:
        ig_id, token = await resolve(account)
        fields = (
            "id,caption,media_type,media_url,permalink,timestamp,"
            "like_count,comments_count"
        )
        data = await client().get(f"{ig_id}/media", token, {"fields": fields, "limit": limit})
        return {"ok": True, "account": account, "media": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_media_insights(media_id: str, account: str | None = None) -> dict[str, Any]:
    """Per-post insights for a media id (from list_recent_media).
    Pass `account` (the one the media came from) when multiple BMs are configured.
    """
    try:
        token = await token_for(account)
        metrics = "reach,likes,comments,saved,shares,total_interactions,views"
        data = await client().get(f"{media_id}/insights", token, {"metric": metrics})
        results = {}
        for item in data.get("data", []):
            vals = item.get("values", [])
            value = vals[0].get("value") if vals else item.get("total_value", {}).get("value")
            results[item.get("name")] = value
        return {"ok": True, "media_id": media_id, "insights": results}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_media_comments(
    media_id: str, account: str | None = None, limit: int = 25
) -> dict[str, Any]:
    """List comments on a post. Pass `account` when multiple BMs configured.
    `limit` clamped 1-50.
    """
    limit = max(1, min(int(limit), 50))
    try:
        token = await token_for(account)
        fields = "id,text,username,timestamp,like_count"
        data = await client().get(f"{media_id}/comments", token, {"fields": fields, "limit": limit})
        return {"ok": True, "comments": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


# ---------------------------------------------------------------------------
# Publishing tools (mutating, non-destructive) — per account
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def publish_photo(
    image_url: str, caption: str = "", account: str | None = None
) -> dict[str, Any]:
    """Publish a single photo to `account`. `image_url` = public HTTPS JPEG."""
    try:
        ig_id, token = await resolve(account)
        container = await client().post(
            f"{ig_id}/media", token, {"image_url": image_url, "caption": caption}
        )
        published = await client().post(
            f"{ig_id}/media_publish", token, {"creation_id": container.get("id")}
        )
        return {"ok": True, "account": account, "media_id": published.get("id")}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def publish_reel(
    video_url: str, caption: str = "", account: str | None = None
) -> dict[str, Any]:
    """Publish a Reel to `account`. `video_url` = public HTTPS MP4."""
    try:
        ig_id, token = await resolve(account)
        container = await client().post(
            f"{ig_id}/media",
            token,
            {"media_type": "REELS", "video_url": video_url, "caption": caption},
        )
        creation_id = container.get("id")
        await client().wait_for_container(creation_id, token)
        published = await client().post(
            f"{ig_id}/media_publish", token, {"creation_id": creation_id}
        )
        return {"ok": True, "account": account, "media_id": published.get("id")}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def publish_carousel(
    image_urls: list[str], caption: str = "", account: str | None = None
) -> dict[str, Any]:
    """Publish a 2-10 photo carousel to `account`. Each url = public HTTPS JPEG."""
    if not 2 <= len(image_urls) <= 10:
        return {"ok": False, "error": "carousel needs between 2 and 10 image_urls"}
    try:
        ig_id, token = await resolve(account)
        child_ids = []
        for url in image_urls:
            child = await client().post(
                f"{ig_id}/media", token, {"image_url": url, "is_carousel_item": "true"}
            )
            child_ids.append(child.get("id"))
        parent = await client().post(
            f"{ig_id}/media",
            token,
            {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption},
        )
        published = await client().post(
            f"{ig_id}/media_publish", token, {"creation_id": parent.get("id")}
        )
        return {"ok": True, "account": account, "media_id": published.get("id")}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def reply_to_comment(
    comment_id: str, message: str, account: str | None = None
) -> dict[str, Any]:
    """Reply to a comment by its id. Pass `account` when multiple BMs configured."""
    if not message.strip():
        return {"ok": False, "error": "message cannot be empty"}
    try:
        token = await token_for(account)
        data = await client().post(f"{comment_id}/replies", token, {"message": message})
        return {"ok": True, "reply_id": data.get("id")}
    except InstagramAPIError as exc:
        return err(exc)


# Register extended tools (reports, competitor, deeper insights, moderation).
import tools_extra  # noqa: E402,F401


if __name__ == "__main__":
    mcp.run()
