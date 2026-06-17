"""Async Instagram Graph API client — multi-token (one System User per BM).

The agency runs one Business Manager per client, and a token only sees its own
BM. So this client holds several tokens, discovers each token's IG accounts,
and builds a registry that maps every account (username + ig id) to the token
that owns it. Per-account calls auto-route to the right token.

All Graph calls funnel through `_request`, which attaches the chosen token and
raises `InstagramAPIError` with an actionable hint on failure.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config import GRAPH_BASE, GRAPH_VERSION


class InstagramAPIError(Exception):
    def __init__(self, message: str, *, code: int | None = None, hint: str | None = None):
        self.code = code
        self.hint = hint
        super().__init__(message)

    def as_text(self) -> str:
        parts = [str(self)]
        if self.code is not None:
            parts.append(f"(Graph error code {self.code})")
        if self.hint:
            parts.append(f"Next step: {self.hint}")
        return " ".join(parts)


class InstagramClient:
    """Graph wrapper with multi-token discovery, resolution, and routing."""

    def __init__(self, tokens: list[dict[str, str]] | None, *, timeout: float = 30.0):
        # tokens: [{'label': str, 'token': str}, ...]
        self._tokens = tokens or []
        self._http = httpx.AsyncClient(
            base_url=f"{GRAPH_BASE}/{GRAPH_VERSION}", timeout=timeout
        )
        # Cached public registry (no token values) + internal routing maps.
        self._accounts: list[dict[str, Any]] | None = None
        self._by_username: dict[str, dict[str, str]] = {}  # uname -> {ig_id, token}
        self._by_id: dict[str, str] = {}  # ig_id -> token

    async def aclose(self) -> None:
        await self._http.aclose()

    def _require_tokens(self) -> list[dict[str, str]]:
        if not self._tokens:
            raise InstagramAPIError(
                "No access tokens configured.",
                hint="Add System User tokens to tokens.json (run `python quickstart.py`).",
            )
        return self._tokens

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        params["access_token"] = token
        try:
            resp = await self._http.request(method, path, params=params, data=data)
        except httpx.RequestError as exc:
            raise InstagramAPIError(
                f"Network error talking to Graph API: {exc}",
                hint="Check internet connectivity and try again.",
            ) from exc

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if resp.status_code >= 400 or "error" in payload:
            err = payload.get("error", {}) if isinstance(payload, dict) else {}
            msg = err.get("message") or f"HTTP {resp.status_code}"
            code = err.get("code")
            raise InstagramAPIError(msg, code=code, hint=self._hint_for(code, msg))
        return payload

    @staticmethod
    def _hint_for(code: int | None, message: str) -> str | None:
        lowered = message.lower()
        if code in (190, 102, 463, 467) or "expired" in lowered or "session" in lowered:
            return "A token is invalid/expired — regenerate that BM's System User token."
        if code in (10, 200) or "permission" in lowered:
            return (
                "Missing permission/asset access — assign the IG account + Page to the "
                "System User and grant scopes instagram_basic, instagram_manage_insights, "
                "instagram_content_publish, pages_show_list."
            )
        if code in (4, 17, 32) or "limit" in lowered:
            return "Rate limit hit — wait before retrying."
        return None

    # Account-keyed get/post (resolve account -> ig_id + token, then call).
    async def get(self, path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, token, params=params)

    async def post(self, path: str, token: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, token, data=data)

    # --- Discovery across all tokens ---------------------------------------

    async def _accounts_for_token(self, token: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        params = {
            "fields": "name,instagram_business_account{id,username,followers_count}",
            "limit": 100,
        }
        path: str | None = "me/accounts"
        next_params: dict[str, Any] = params
        while path:
            page = await self._request("GET", path, token, params=next_params)
            for item in page.get("data", []):
                iba = item.get("instagram_business_account")
                if not iba:
                    continue
                out.append(
                    {
                        "page_name": item.get("name"),
                        "ig_id": iba.get("id"),
                        "username": iba.get("username"),
                        "followers_count": iba.get("followers_count"),
                    }
                )
            after = page.get("paging", {}).get("cursors", {}).get("after")
            if page.get("paging", {}).get("next") and after:
                next_params = {**params, "after": after}
            else:
                path = None
        return out

    async def list_accounts(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Discover IG accounts across every configured token. Cached.

        A bad token doesn't sink the rest — it surfaces as an error row tagged
        with its BM label.
        """
        if self._accounts is not None and not refresh:
            return self._accounts

        self._require_tokens()
        accounts: list[dict[str, Any]] = []
        by_username: dict[str, dict[str, str]] = {}
        by_id: dict[str, str] = {}

        # Discover all tokens concurrently.
        async def discover(entry: dict[str, str]):
            try:
                found = await self._accounts_for_token(entry["token"])
                return entry, found, None
            except InstagramAPIError as exc:
                return entry, [], exc

        results = await asyncio.gather(*(discover(e) for e in self._tokens))
        for entry, found, exc in results:
            label = entry["label"]
            if exc is not None:
                accounts.append({"business": label, "error": exc.as_text()})
                continue
            for a in found:
                row = {"business": label, **a}
                accounts.append(row)
                if a.get("username"):
                    by_username[a["username"].lower()] = {"ig_id": a["ig_id"], "token": entry["token"]}
                if a.get("ig_id"):
                    by_id[a["ig_id"]] = entry["token"]

        self._accounts, self._by_username, self._by_id = accounts, by_username, by_id
        return accounts

    # --- Resolution + routing ----------------------------------------------

    async def resolve_account(self, account: str | None) -> tuple[str, str]:
        """Resolve a username/id to (ig_id, token_that_owns_it)."""
        if not account:
            raise InstagramAPIError(
                "No account specified.",
                hint="Pass `account` (username or ig id); call list_accounts to see options.",
            )
        account = account.strip().lstrip("@")
        await self.list_accounts()
        if account.isdigit():
            token = self._by_id.get(account)
            if token:
                return account, token
            if len(self._tokens) == 1:
                return account, self._tokens[0]["token"]
            raise InstagramAPIError(
                f"ig id '{account}' not found in any configured BM.",
                hint="Run list_accounts(refresh=true), or check the id.",
            )
        entry = self._by_username.get(account.lower())
        if entry:
            return entry["ig_id"], entry["token"]
        known = ", ".join(sorted(self._by_username)) or "(none discovered)"
        raise InstagramAPIError(
            f"Unknown account '{account}'.",
            hint=f"Known usernames: {known}. Or pass the numeric ig id.",
        )

    async def token_for(self, account: str | None) -> str:
        """Pick the token for a media-level call (media_id has no account)."""
        if account:
            _, token = await self.resolve_account(account)
            return token
        toks = self._require_tokens()
        if len(toks) == 1:
            return toks[0]["token"]
        raise InstagramAPIError(
            "Multiple BMs configured — can't tell which client this media belongs to.",
            hint="Pass `account` (the username/id the media came from).",
        )

    # --- Publishing helper --------------------------------------------------

    async def wait_for_container(
        self, creation_id: str, token: str, *, attempts: int = 30, delay: float = 2.0
    ) -> None:
        for _ in range(attempts):
            status = await self._request(
                "GET", creation_id, token, params={"fields": "status_code,status"}
            )
            code = status.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramAPIError(
                    f"Media container failed processing (status_code={code}).",
                    hint="Check the media URL is a public, valid video/image.",
                )
            await asyncio.sleep(delay)
        raise InstagramAPIError(
            "Media container did not finish processing in time.",
            hint="Large videos may take longer; retry the publish.",
        )
