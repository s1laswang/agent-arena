#!/usr/bin/env bash
# One command: tests + the reported results table (scripted reference and baselines;
# Gemini agents too if GEMINI_API_KEY is set in .env or cached responses exist).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-python3}
[ -d .venv ] || $PY -m venv .venv
VPY=.venv/bin/python; [ -x "$VPY" ] || VPY=.venv/Scripts/python
$VPY -m pip install -q -r requirements.txt
$VPY -m pytest -q
AGENTS=oracle,autopilot,do_nothing,stop_early,refuse_all,escalate_all,claim_in_chat,gemini_staff,gemini_reference
$VPY -m blindspot.eval --agents "$AGENTS" --seeds 0-29 --repeats 3 --out results/latest --quiet
