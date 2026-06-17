"""Extended Instagram MCP tools, registered on import by server.py.

Four buckets:
  - Agency reports: bulk_insights, compare_accounts, top_posts,
    engagement_rate, best_time_to_post, weekly_report
  - Deeper insights: follower_growth, online_followers, reel_insights,
    story_insights, profile_activity
  - Competitor: business_discovery, business_discovery_media,
    search_hashtag, get_hashtag_media
  - Moderation + publishing+: publish_story, hide_comment, delete_comment,
    toggle_comments, get_tagged_media, get_active_stories, get_publishing_limit

All tools route to the owning token and degrade gracefully on API errors.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from core import InstagramAPIError, client, err, mcp, resolve, token_for

_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count"
)


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return None


def _engagement(m: dict[str, Any]) -> int:
    return int(m.get("like_count") or 0) + int(m.get("comments_count") or 0)


async def _media_in_window(ig_id: str, token: str, days: int, *, cap: int = 200) -> list[dict[str, Any]]:
    """Fetch media, keep those within the last `days`. Stops once older."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    raw = await client().paginate(f"{ig_id}/media", token, {"fields": _MEDIA_FIELDS, "limit": 50}, max_items=cap)
    out = []
    for m in raw:
        ts = _parse_ts(m.get("timestamp", ""))
        if ts is None or ts >= cutoff:
            out.append(m)
    return out


# ===========================================================================
# Bucket 1 — Agency reports
# ===========================================================================


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def bulk_insights(days: int = 7) -> dict[str, Any]:
    """Account insights (reach, views, interactions, accounts engaged) for
    EVERY managed account at once. Great for an agency-wide snapshot.
    `days` clamped 1-30.
    """
    days = max(1, min(int(days), 30))
    try:
        accounts = await client().list_accounts()
    except InstagramAPIError as exc:
        return err(exc)
    real = [a for a in accounts if "ig_id" in a]

    async def one(a: dict[str, Any]) -> dict[str, Any]:
        try:
            _, token = await resolve(a["username"])
            data = await client().get(
                f"{a['ig_id']}/insights",
                token,
                {"metric": "reach,views,total_interactions,accounts_engaged",
                 "metric_type": "total_value", "period": "day"},
            )
            ins = {i.get("name"): i.get("total_value", {}).get("value") for i in data.get("data", [])}
            return {"account": a["username"], "business": a["business"], "insights": ins}
        except InstagramAPIError as exc:
            return {"account": a["username"], "business": a["business"], "error": exc.as_text()}

    results = await asyncio.gather(*(one(a) for a in real))
    return {"ok": True, "period_days": days, "count": len(results), "results": list(results)}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def compare_accounts(accounts: list[str] | None = None, days: int = 7) -> dict[str, Any]:
    """Side-by-side metrics for the given accounts (or ALL if omitted):
    followers, media count, reach, interactions, engagement rate. `days` 1-30.
    """
    days = max(1, min(int(days), 30))
    try:
        if not accounts:
            disc = await client().list_accounts()
            accounts = [a["username"] for a in disc if "username" in a]
    except InstagramAPIError as exc:
        return err(exc)

    async def one(acc: str) -> dict[str, Any]:
        try:
            ig_id, token = await resolve(acc)
            info = await client().get(
                ig_id, token, {"fields": "username,followers_count,media_count"}
            )
            ins = await client().get(
                f"{ig_id}/insights", token,
                {"metric": "reach,total_interactions", "metric_type": "total_value", "period": "day"},
            )
            m = {i.get("name"): i.get("total_value", {}).get("value") for i in ins.get("data", [])}
            followers = info.get("followers_count") or 0
            reach = m.get("reach") or 0
            interactions = m.get("total_interactions") or 0
            er = round((interactions / reach) * 100, 2) if reach else None
            return {
                "account": info.get("username") or acc,
                "followers": followers,
                "media_count": info.get("media_count"),
                "reach": reach,
                "interactions": interactions,
                "engagement_rate_pct": er,
            }
        except InstagramAPIError as exc:
            return {"account": acc, "error": exc.as_text()}

    rows = await asyncio.gather(*(one(a) for a in accounts))
    return {"ok": True, "period_days": days, "comparison": list(rows)}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def top_posts(
    account: str | None = None, days: int = 30, limit: int = 5, by: str = "engagement"
) -> dict[str, Any]:
    """Top posts in the last `days`, ranked by `by` (engagement|likes|comments).
    `account` = username or ig id. `limit` 1-20, `days` 1-90.
    """
    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), 20))
    key = {
        "engagement": _engagement,
        "likes": lambda m: int(m.get("like_count") or 0),
        "comments": lambda m: int(m.get("comments_count") or 0),
    }.get(by, _engagement)
    try:
        ig_id, token = await resolve(account)
        media = await _media_in_window(ig_id, token, days)
        ranked = sorted(media, key=key, reverse=True)[:limit]
        for m in ranked:
            m["engagement"] = _engagement(m)
        return {"ok": True, "account": account, "ranked_by": by, "posts": ranked}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def engagement_rate(account: str | None = None, days: int = 30) -> dict[str, Any]:
    """Average engagement rate over the last `days`: mean of
    (likes+comments)/followers per post, as a percentage. `days` 1-90.
    """
    days = max(1, min(int(days), 90))
    try:
        ig_id, token = await resolve(account)
        info = await client().get(ig_id, token, {"fields": "username,followers_count"})
        followers = info.get("followers_count") or 0
        if not followers:
            return {"ok": False, "error": "followers_count is 0/unavailable; can't compute rate."}
        media = await _media_in_window(ig_id, token, days)
        if not media:
            return {"ok": True, "account": account, "posts": 0, "engagement_rate_pct": None}
        per_post = [(_engagement(m) / followers) * 100 for m in media]
        avg = round(sum(per_post) / len(per_post), 3)
        return {
            "ok": True,
            "account": info.get("username") or account,
            "followers": followers,
            "posts": len(media),
            "avg_engagement_per_post": round(sum(_engagement(m) for m in media) / len(media), 1),
            "engagement_rate_pct": avg,
        }
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def best_time_to_post(account: str | None = None) -> dict[str, Any]:
    """Best hours to post, from the online_followers metric (avg followers
    online per hour). Needs >=100 followers; may be unavailable on some accounts.
    """
    try:
        ig_id, token = await resolve(account)
        data = await client().get(
            f"{ig_id}/insights", token, {"metric": "online_followers", "period": "lifetime"}
        )
        by_hour: dict[int, list[int]] = {}
        for item in data.get("data", []):
            for v in item.get("values", []):
                val = v.get("value", {})
                if isinstance(val, dict):
                    for hour, count in val.items():
                        by_hour.setdefault(int(hour), []).append(int(count))
        if not by_hour:
            return {"ok": True, "account": account, "note": "no online_followers data", "best_hours": []}
        avg = {h: round(sum(c) / len(c)) for h, c in by_hour.items()}
        best = sorted(avg.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "ok": True,
            "account": account,
            "best_hours": [{"hour": h, "avg_online": v} for h, v in best],
            "by_hour": dict(sorted(avg.items())),
        }
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def weekly_report(account: str | None = None, days: int = 7) -> dict[str, Any]:
    """One-shot client report: profile, account insights, engagement rate, and
    top 3 posts for the last `days`. `days` 1-30.
    """
    days = max(1, min(int(days), 30))
    try:
        ig_id, token = await resolve(account)
        info = await client().get(
            ig_id, token,
            {"fields": "username,followers_count,follows_count,media_count"},
        )
        ins = await client().get(
            f"{ig_id}/insights", token,
            {"metric": "reach,views,total_interactions,accounts_engaged",
             "metric_type": "total_value", "period": "day"},
        )
        metrics = {i.get("name"): i.get("total_value", {}).get("value") for i in ins.get("data", [])}
        media = await _media_in_window(ig_id, token, days)
        followers = info.get("followers_count") or 0
        top = sorted(media, key=_engagement, reverse=True)[:3]
        er = None
        if followers and media:
            er = round(sum((_engagement(m) / followers) * 100 for m in media) / len(media), 3)
        return {
            "ok": True,
            "account": info.get("username") or account,
            "period_days": days,
            "profile": {
                "followers": followers,
                "following": info.get("follows_count"),
                "media_count": info.get("media_count"),
            },
            "insights": metrics,
            "posts_in_period": len(media),
            "engagement_rate_pct": er,
            "top_posts": [
                {"permalink": m.get("permalink"), "engagement": _engagement(m),
                 "caption": (m.get("caption") or "")[:80]}
                for m in top
            ],
        }
    except InstagramAPIError as exc:
        return err(exc)


# ===========================================================================
# Bucket 2 — Deeper insights
# ===========================================================================


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_follower_growth(account: str | None = None, days: int = 14) -> dict[str, Any]:
    """Daily follower-count series over the last `days` (1-30). May be
    restricted on accounts with <100 followers.
    """
    days = max(1, min(int(days), 30))
    try:
        ig_id, token = await resolve(account)
        data = await client().get(
            f"{ig_id}/insights", token, {"metric": "follower_count", "period": "day"}
        )
        series = []
        for item in data.get("data", []):
            for v in item.get("values", []):
                series.append({"date": v.get("end_time"), "value": v.get("value")})
        return {"ok": True, "account": account, "follower_count_series": series}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_reel_insights(media_id: str, account: str | None = None) -> dict[str, Any]:
    """Reel-specific insights: reach, views, interactions, plus avg watch time
    and total watch time. Pass `account` when multiple BMs configured.
    """
    try:
        token = await token_for(account)
        metrics = (
            "reach,likes,comments,saved,shares,total_interactions,views,"
            "ig_reels_avg_watch_time,ig_reels_video_view_total_time"
        )
        data = await client().get(f"{media_id}/insights", token, {"metric": metrics})
        out = {}
        for item in data.get("data", []):
            vals = item.get("values", [])
            out[item.get("name")] = vals[0].get("value") if vals else None
        return {"ok": True, "media_id": media_id, "insights": out}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_story_insights(media_id: str, account: str | None = None) -> dict[str, Any]:
    """Story insights: reach, views, replies, total interactions, navigation.
    Stories expire in 24h — query while live. Pass `account` when multi-BM.
    """
    try:
        token = await token_for(account)
        metrics = "reach,views,replies,total_interactions,navigation"
        data = await client().get(f"{media_id}/insights", token, {"metric": metrics})
        out = {}
        for item in data.get("data", []):
            vals = item.get("values", [])
            out[item.get("name")] = vals[0].get("value") if vals else None
        return {"ok": True, "media_id": media_id, "insights": out}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_profile_activity(account: str | None = None) -> dict[str, Any]:
    """Profile interactions: taps on profile links (website/email/etc.) and
    profile visits. `account` = username or ig id.
    """
    try:
        ig_id, token = await resolve(account)
        data = await client().get(
            f"{ig_id}/insights", token,
            {"metric": "profile_links_taps", "metric_type": "total_value", "period": "day"},
        )
        out = {}
        for item in data.get("data", []):
            out[item.get("name")] = item.get("total_value", {}).get("value")
        return {"ok": True, "account": account, "profile_activity": out}
    except InstagramAPIError as exc:
        return err(exc)


# ===========================================================================
# Bucket 3 — Competitor / market
# ===========================================================================


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def business_discovery(competitor_username: str, account: str | None = None) -> dict[str, Any]:
    """Public profile data of ANY business/creator account by username
    (followers, following, media count, bio). `account` = one of YOUR accounts
    used to make the query.
    """
    comp = competitor_username.strip().lstrip("@")
    try:
        ig_id, token = await resolve(account)
        fields = f"business_discovery.username({comp}){{username,name,biography,followers_count,follows_count,media_count}}"
        data = await client().get(ig_id, token, {"fields": fields})
        return {"ok": True, "competitor": comp, "data": data.get("business_discovery", {})}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def business_discovery_media(
    competitor_username: str, account: str | None = None, limit: int = 10
) -> dict[str, Any]:
    """Recent public posts of a competitor (caption, likes, comments, type).
    `account` = one of YOUR accounts. `limit` 1-25.
    """
    comp = competitor_username.strip().lstrip("@")
    limit = max(1, min(int(limit), 25))
    try:
        ig_id, token = await resolve(account)
        fields = (
            f"business_discovery.username({comp})"
            f"{{media.limit({limit}){{caption,like_count,comments_count,media_type,timestamp,permalink}}}}"
        )
        data = await client().get(ig_id, token, {"fields": fields})
        bd = data.get("business_discovery", {})
        return {"ok": True, "competitor": comp, "media": bd.get("media", {}).get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_hashtag(query: str, account: str | None = None) -> dict[str, Any]:
    """Resolve a hashtag name to its id (needed for hashtag media tools).
    `account` = one of YOUR accounts used to make the query.
    """
    q = query.strip().lstrip("#")
    try:
        ig_id, token = await resolve(account)
        data = await client().get("ig_hashtag_search", token, {"user_id": ig_id, "q": q})
        items = data.get("data", [])
        if not items:
            return {"ok": True, "query": q, "hashtag_id": None, "note": "no match"}
        return {"ok": True, "query": q, "hashtag_id": items[0].get("id")}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_hashtag_media(
    query: str, account: str | None = None, media_type: str = "top", limit: int = 12
) -> dict[str, Any]:
    """Top or recent media for a hashtag. `media_type` = top|recent.
    `account` = one of YOUR accounts. `limit` 1-30. (Meta caps unique hashtag
    queries to ~30 per 7 days per account.)
    """
    if media_type not in ("top", "recent"):
        return {"ok": False, "error": "media_type must be 'top' or 'recent'"}
    limit = max(1, min(int(limit), 30))
    q = query.strip().lstrip("#")
    try:
        ig_id, token = await resolve(account)
        search = await client().get("ig_hashtag_search", token, {"user_id": ig_id, "q": q})
        items = search.get("data", [])
        if not items:
            return {"ok": True, "query": q, "media": [], "note": "hashtag not found"}
        hid = items[0]["id"]
        edge = "top_media" if media_type == "top" else "recent_media"
        fields = "id,caption,media_type,like_count,comments_count,permalink,timestamp"
        data = await client().get(
            f"{hid}/{edge}", token, {"user_id": ig_id, "fields": fields, "limit": limit}
        )
        return {"ok": True, "query": q, "media_type": media_type, "media": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


# ===========================================================================
# Bucket 4 — Moderation + publishing+
# ===========================================================================


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def publish_story(media_url: str, account: str | None = None, is_video: bool = False) -> dict[str, Any]:
    """Publish a Story to `account`. `media_url` = public HTTPS JPEG (or MP4 if
    is_video). Stories disappear after 24h.
    """
    try:
        ig_id, token = await resolve(account)
        body = {"media_type": "STORIES"}
        body["video_url" if is_video else "image_url"] = media_url
        container = await client().post(f"{ig_id}/media", token, body)
        creation_id = container.get("id")
        if is_video:
            await client().wait_for_container(creation_id, token)
        published = await client().post(f"{ig_id}/media_publish", token, {"creation_id": creation_id})
        return {"ok": True, "account": account, "media_id": published.get("id")}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def hide_comment(comment_id: str, hide: bool = True, account: str | None = None) -> dict[str, Any]:
    """Hide (or unhide) a comment. Pass `account` when multiple BMs configured."""
    try:
        token = await token_for(account)
        data = await client().post(comment_id, token, {"hide": "true" if hide else "false"})
        return {"ok": True, "comment_id": comment_id, "hidden": hide, "result": data}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
async def delete_comment(comment_id: str, account: str | None = None) -> dict[str, Any]:
    """Delete a comment permanently. Pass `account` when multiple BMs configured."""
    try:
        token = await token_for(account)
        data = await client().delete(comment_id, token)
        return {"ok": True, "comment_id": comment_id, "deleted": data.get("success", True)}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
async def toggle_comments(media_id: str, enabled: bool, account: str | None = None) -> dict[str, Any]:
    """Enable or disable commenting on a post. Pass `account` when multi-BM."""
    try:
        token = await token_for(account)
        data = await client().post(media_id, token, {"comment_enabled": "true" if enabled else "false"})
        return {"ok": True, "media_id": media_id, "comments_enabled": enabled, "result": data}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_tagged_media(account: str | None = None, limit: int = 12) -> dict[str, Any]:
    """Posts where this account was @tagged by others. `limit` 1-50."""
    limit = max(1, min(int(limit), 50))
    try:
        ig_id, token = await resolve(account)
        fields = "id,caption,media_type,permalink,timestamp,like_count,comments_count,username"
        data = await client().get(f"{ig_id}/tags", token, {"fields": fields, "limit": limit})
        return {"ok": True, "account": account, "tagged_media": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_active_stories(account: str | None = None) -> dict[str, Any]:
    """Currently-live stories (expire after 24h). `account` = username or ig id."""
    try:
        ig_id, token = await resolve(account)
        fields = "id,media_type,media_url,permalink,timestamp"
        data = await client().get(f"{ig_id}/stories", token, {"fields": fields})
        return {"ok": True, "account": account, "stories": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_publishing_limit(account: str | None = None) -> dict[str, Any]:
    """How many posts remain in the rolling 24h publish quota (~50/day)."""
    try:
        ig_id, token = await resolve(account)
        data = await client().get(
            f"{ig_id}/content_publishing_limit", token, {"fields": "config,quota_usage"}
        )
        return {"ok": True, "account": account, "limit": data.get("data", [])}
    except InstagramAPIError as exc:
        return err(exc)
