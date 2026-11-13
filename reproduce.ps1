# One command (Windows): tests + the reported results table.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -r requirements.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m blindspot.eval --agents oracle,autopilot,do_nothing,stop_early,refuse_all,escalate_all,claim_in_chat,gemini_staff,gemini_reference --seeds 0-29 --repeats 3 --out results/latest --quiet
