# Instagram MCP Server (agency, Partners model)

Connect Claude to **all your clients' Instagram accounts at once**.

The agency runs a **central Business Manager**. Each client BM shares its Page + Instagram account into the central BM via **Partners**. One System User token in the central BM then sees every client → **a single token covers everyone**. Local **stdio MCP server** in Python.

> The server also supports **multiple tokens** (one per BM) as a fallback — see "Multiple tokens" below — but the Partners model needs just one.

## How it works

Uses the **Facebook Graph API**. The central token walks the Pages it can access (`/me/accounts` → each Page's linked `instagram_business_account`, including partner-shared ones) and builds a registry of every account (username + ig id). Per-account tools take an `account` argument; `list_accounts` shows them all.

## Tools

| Tool | What it does |
|------|--------------|
| `list_accounts` | Every IG account across all client BMs (username, id, followers, BM label) |
| `get_account_info` | Profile + counts for one account |
| `get_account_insights` | Reach, views, interactions, accounts engaged |
| `get_audience_demographics` | Follower breakdown by country / city / age / gender |
| `list_recent_media` | Recent posts (caption, type, likes, comments, permalink) |
| `get_media_insights` | Per-post reach, likes, comments, saves, shares, views |
| `get_media_comments` | Comments on a post |
| `publish_photo` / `publish_reel` / `publish_carousel` | Post to one account |
| `reply_to_comment` | Reply to a comment |

Per-account tools accept `account` (username or id). Media-level tools (`get_media_insights`, `get_media_comments`, `reply_to_comment`) also accept `account` so the server knows which BM's token to use — required when more than one BM is configured.

## Requirements (Meta's, not optional)

- Each managed Instagram account must be **Business or Creator** and linked to its Facebook Page.
- A **central Business Manager** that owns your Meta app.
- Each client BM shares its Page into the central BM via **Partners** (steps below).
- To manage accounts you don't own, the app needs **Advanced Access** (App Review) for `instagram_manage_insights` / `instagram_content_publish`.
- Some metrics (demographics, etc.) need **≥100 followers**.

---

## Setup

### 1. Get your central BM's Business ID
https://business.facebook.com/settings → **Business info** → copy the **Business Manager ID** (a long number). You'll give this to each client BM.

### 2. In EACH client BM: share the Page as a partner
Open the client's BM (https://business.facebook.com/settings → switch business):
1. **Users → Partners → Add → "Give a partner access to your assets"**.
2. Paste your **central BM's Business ID** (step 1).
3. Select that client's **Page** → grant **full control** (Manage). The linked IG account rides along.

Repeat for every client BM. (You add partners; the client BM is where assets are shared from.)

### 3. In the central BM: one System User + one token
Back in your central BM (https://business.facebook.com/settings):
1. **Users → System Users → Add** → role **Admin**.
2. **Add Assets → Apps** → your Meta app → full control.
3. **Add Assets → Pages** → you should now see the **partner-shared client Pages** → assign them (full control).
4. **Generate New Token** → your app → scopes: `instagram_basic`, `instagram_manage_insights`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`.
5. Expiration **off** → never expires. **Copy the token.**

### 4. Install + store the token

**macOS / Linux:**
```bash
cd ~/insta-mcp                       # wherever you put the folder
python3 -m pip install -r requirements.txt
python3 quickstart.py
```
**Windows (PowerShell):**
```powershell
cd C:\Users\eduardo\Desktop\insta-mcp
python -m pip install -r requirements.txt
python quickstart.py
```
(Use `python3` on macOS. If pip complains about a managed environment, make a venv first: `python3 -m venv .venv && source .venv/bin/activate`.)
In the wizard, paste the **single** central token (label it e.g. "Central"). Or set `IG_ACCESS_TOKEN=<token>` in `.env`, or put one entry in `tokens.json`.

### 5. Verify
```powershell
python auth_helper.py me         # checks the token, prints its owner
python auth_helper.py accounts   # lists every shared IG account it can see
python smoke_test.py             # runs all read tools against the first account
python smoke_test.py domino      # or target one account by username/id
```
`accounts` should list every client whose Page you shared in step 2. Missing one → that client BM didn't share its Page (or you didn't assign it in step 3.3).

### 6. Wire into Claude
`quickstart.py` prints this for you with the correct paths. **macOS** example:
```json
{
  "mcpServers": {
    "instagram": {
      "command": "python3",
      "args": ["/Users/you/insta-mcp/server.py"]
    }
  }
}
```
Windows uses `"command": "python"` and a `C:\\...\\server.py` path. Tokens load from `tokens.json` automatically.

**Claude Code (mac):**
```bash
claude mcp add instagram -- python3 /Users/you/insta-mcp/server.py
```
Restart, then: *"List my Instagram accounts, then last week's insights for @domino."*

> Tip: if you used a venv, point `command` at the venv's python (e.g. `/Users/you/insta-mcp/.venv/bin/python`) so the deps are found.

---

## Multiple tokens (fallback)
If you ever can't use Partners for some client, you can run a separate token for that BM. Put several entries in `tokens.json`:
```json
[
  { "label": "Central", "token": "EAA..." },
  { "label": "Standalone Client", "token": "EAA..." }
]
```
The server discovers all of them, tags each account by `business` label, and auto-routes every call to the right token. A broken token shows as an `error` row in `list_accounts` (tagged with its BM); the rest keep working. With more than one token, media-level tools (`get_media_insights` etc.) need an `account` to pick the token.

## Notes
- `list_accounts` is cached per process; pass `refresh=true` after sharing a new client.
- Optional `IG_DEFAULT_ACCOUNT` (in `.env`) lets tools omit `account`.
- Publishing media URLs must be **public HTTPS** (Meta fetches them server-side).

## Troubleshooting
- **account not found** → run `list_accounts(refresh=true)`; confirm the client shared its Page (step 2) and you assigned it to the System User (step 3.3).
- **partner-shared Page not visible in step 3.3** → the client BM hasn't approved/shared it yet, or shared to the wrong Business ID.
- **demographics empty** → that account has <100 followers.
