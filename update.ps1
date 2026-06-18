# Update the Instagram MCP server (Windows). Run: .\update.ps1
# If blocked: powershell -ExecutionPolicy Bypass -File .\update.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = "python"
# Prefer the venv's python if one exists, so deps land in the right place.
if (Test-Path ".venv\Scripts\python.exe") { $py = ".venv\Scripts\python.exe" }

& $py update.py
exit $LASTEXITCODE
