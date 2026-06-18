#!/usr/bin/env bash
# Update the Instagram MCP server (macOS/Linux). Double-click or run ./update.sh
set -e
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Python not found. Install Python 3 and retry."
  exit 1
fi
# Prefer the venv's python if one exists, so deps land in the right place.
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
exec "$PY" update.py
