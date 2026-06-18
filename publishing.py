"""Shared publish logic — one place that turns a (kind, media, caption) into a
live Instagram post via the 2-step container flow.

Reused by the scheduler worker (scheduler.py) and the run_due_posts MCP tool so
scheduled posts publish exactly like the interactive publish_* tools do.

kinds: photo | reel | carousel | story
media shape per kind:
  photo     -> {"image_url": "https://..."}
  reel      -> {"video_url": "https://..."}
  carousel  -> {"image_urls": ["https://...", ...]}   # 2-10
  story     -> {"image_url": "..."}  OR  {"video_url": "..."}
"""

from __future__ import annotations

from typing import Any

from core import InstagramAPIError, client

KINDS = ("photo", "reel", "carousel", "story")


def validate_media(kind: str, media: dict[str, Any]) -> str | None:
    """Return an error string if (kind, media) is malformed, else None."""
    if kind not in KINDS:
        return f"kind must be one of {list(KINDS)}"
    if kind == "photo":
        if not media.get("image_url"):
            return "photo needs media.image_url (public HTTPS JPEG)"
    elif kind == "reel":
        if not media.get("video_url"):
            return "reel needs media.video_url (public HTTPS MP4)"
    elif kind == "carousel":
        urls = media.get("image_urls")
        if not isinstance(urls, list) or not 2 <= len(urls) <= 10:
            return "carousel needs media.image_urls (2-10 public HTTPS JPEGs)"
    elif kind == "story":
        if not (media.get("image_url") or media.get("video_url")):
            return "story needs media.image_url or media.video_url"
    return None


async def publish_now(ig_id: str, token: str, kind: str, media: dict[str, Any], caption: str = "") -> str:
    """Publish immediately. Returns the published media id, or raises InstagramAPIError."""
    bad = validate_media(kind, media)
    if bad:
        raise InstagramAPIError(bad, hint="Fix the media payload and retry.")

    c = client()

    if kind == "photo":
        container = await c.post(f"{ig_id}/media", token, {"image_url": media["image_url"], "caption": caption})
        published = await c.post(f"{ig_id}/media_publish", token, {"creation_id": container.get("id")})
        return published.get("id")

    if kind == "reel":
        container = await c.post(
            f"{ig_id}/media",
            token,
            {"media_type": "REELS", "video_url": media["video_url"], "caption": caption},
        )
        creation_id = container.get("id")
        await c.wait_for_container(creation_id, token)
        published = await c.post(f"{ig_id}/media_publish", token, {"creation_id": creation_id})
        return published.get("id")

    if kind == "carousel":
        child_ids = []
        for url in media["image_urls"]:
            child = await c.post(f"{ig_id}/media", token, {"image_url": url, "is_carousel_item": "true"})
            child_ids.append(child.get("id"))
        parent = await c.post(
            f"{ig_id}/media",
            token,
            {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption},
        )
        published = await c.post(f"{ig_id}/media_publish", token, {"creation_id": parent.get("id")})
        return published.get("id")

    # story
    body: dict[str, Any] = {"media_type": "STORIES"}
    is_video = bool(media.get("video_url"))
    body["video_url" if is_video else "image_url"] = media.get("video_url") or media.get("image_url")
    container = await c.post(f"{ig_id}/media", token, body)
    creation_id = container.get("id")
    if is_video:
        await c.wait_for_container(creation_id, token)
    published = await c.post(f"{ig_id}/media_publish", token, {"creation_id": creation_id})
    return published.get("id")
