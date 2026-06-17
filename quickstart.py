"""Interactive setup wizard for the Instagram MCP server (multi-BM agency).

    python quickstart.py

Walks you through: dependency check -> collect one System User token per
client BM (saved to tokens.json) -> verify each token live -> list every
managed IG account -> print (and optionally write) the Claude MCP config.

Re-runnable: shows existing tokens and lets you keep or add to them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKENS_PATH = HERE / "tokens.json"
SERVER_PATH = HERE / "server.py"


def yesno(label: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = input(f"{label} ({d}): ").strip().lower()
    return default if not val else val in ("y", "yes")


def step_deps() -> None:
    print("\n[1/4] Checking dependencies...")
    try:
        import httpx  # noqa: F401
        import mcp  # noqa: F401
        from dotenv import load_dotenv  # noqa: F401
        print("  dependencies present.")
    except ImportError:
        print("  installing requirements...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(HERE / "requirements.txt")],
            check=True,
        )
        print("  done.")


def load_tokens() -> list[dict[str, str]]:
    if TOKENS_PATH.exists():
        try:
            data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
            return [e for e in data if isinstance(e, dict) and e.get("token")]
        except json.JSONDecodeError:
            pass
    return []


def step_tokens() -> list[dict[str, str]]:
    print("\n[2/4] System User tokens (one per client Business Manager)")
    tokens = load_tokens()
    if tokens:
        print(f"  {len(tokens)} token(s) already in tokens.json: " + ", ".join(t["label"] for t in tokens))
        if not yesno("  Add more?", default=False):
            return tokens

    print("  For each client BM: generate a System User token (Business Settings ->")
    print("  Users -> System Users -> Generate token) with scopes instagram_basic,")
    print("  instagram_manage_insights, instagram_content_publish, pages_show_list,")
    print("  pages_read_engagement, business_management.")
    print("  Enter a blank label when done.\n")

    while True:
        label = input("  BM label (e.g. 'Domino BM') [blank = done]: ").strip()
        if not label:
            break
        token = input(f"  token for '{label}': ").strip()
        if not token:
            print("  (skipped — empty token)")
            continue
        tokens.append({"label": label, "token": token})
        print(f"  added '{label}'. ({len(tokens)} total)")

    TOKENS_PATH.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {TOKENS_PATH} ({len(tokens)} token(s)).")
    return tokens


def step_verify() -> bool:
    print("\n[3/4] Verifying tokens + discovering accounts (live)...")
    import importlib
    import config
    importlib.reload(config)
    import auth_helper
    importlib.reload(auth_helper)
    if auth_helper.cmd_me() != 0:
        print("  ! at least one token failed above.")
    rc = auth_helper.cmd_accounts()
    return rc == 0


def step_config() -> None:
    print("\n[4/4] Claude MCP config")
    snippet = {
        "mcpServers": {
            "instagram": {"command": sys.executable, "args": [str(SERVER_PATH)]}
        }
    }
    text = json.dumps(snippet, indent=2)
    print("  Paste into your Claude (Cowork / Desktop) MCP config:\n")
    print(text)
    print("\n  Claude Code one-liner:")
    print(f'    claude mcp add instagram -- "{sys.executable}" "{SERVER_PATH}"')
    if yesno("\n  Also write this to mcp_config.json here?", default=True):
        out = HERE / "mcp_config.json"
        out.write_text(text + "\n", encoding="utf-8")
        print(f"  wrote {out}")


def main() -> int:
    print("=== Instagram MCP - Quickstart (multi-BM) ===")
    step_deps()
    tokens = step_tokens()
    if not tokens:
        print("\nNo tokens entered. Re-run when you have at least one. See README.")
        return 1
    ok = step_verify()
    if not ok:
        print("\nNo accounts discovered. Check token scopes + asset assignment (README).")
        # Still print config — server runs, tools just error until fixed.
    step_config()
    print("\nTest read-only tools any time:  python smoke_test.py")
    print("Then restart Claude and ask it to list your Instagram accounts.")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        raise SystemExit(130)
