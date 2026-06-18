"""Update the Instagram MCP server in place — cross-platform (macOS/Linux/Windows).

Pulls the latest code, installs any new dependencies, and reminds you to restart
Claude (the MCP loads tools at boot — no hot reload). Your tokens.json / .env /
scheduled.json are gitignored, so a pull never touches them.

Run it from anywhere:
  python update.py            (Windows)
  python3 update.py           (macOS/Linux)
or use the wrappers: update.sh (mac/Linux), update.ps1 (Windows).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command in the repo dir, capturing combined output."""
    proc = subprocess.run(
        cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def step(msg: str) -> None:
    print(f">> {msg}", flush=True)


def main() -> int:
    if not (HERE / ".git").exists():
        print("Not a git checkout — re-clone instead: gh repo clone edunascimentt/insta-mcp")
        return 1

    # 1. Pull. --ff-only so a pull never silently merges/clobbers local edits.
    step("Pulling latest code (git pull --ff-only)")
    code, out = run(["git", "pull", "--ff-only"])
    print(out.strip())
    if code != 0:
        print(
            "\nPull failed. Usually local edits diverge from origin.\n"
            "Your secrets (tokens.json/.env) are safe — they're gitignored.\n"
            "Fix: stash or discard local code changes, then re-run:\n"
            "  git stash           # park local edits\n"
            "  python update.py\n"
        )
        return code
    if "Already up to date" in out:
        step("Already on the latest version.")

    # 2. Install/refresh dependencies (new tools may need new packages).
    req = HERE / "requirements.txt"
    if req.exists():
        step("Installing dependencies")
        code, out = run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
        if code != 0:
            print(out.strip())
            print("\nDependency install failed. If you use a venv, activate it first, then re-run.")
            return code
        step("Dependencies up to date.")

    print(
        "\nUpdated. Last step: QUIT Claude completely and reopen it\n"
        "  (macOS: Cmd+Q  |  Windows: right-click tray icon -> Quit)\n"
        "so it reloads the MCP and picks up new tools.\n"
        "\nScheduled posts: if you run the worker via cron/Task Scheduler, no action needed.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
