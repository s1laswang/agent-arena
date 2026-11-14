#!/bin/bash
# Harbor oracle for this episode: plays it over MCP with one of our scripted agents.
# Only Harbor's "oracle" agent ever sees this folder.
#
# PINBOX_SOLUTION picks the scripted agent (pass it with --ae PINBOX_SOLUTION=...):
#   reference (default)       the policy-following expert; must score 1
#   do_nothing                makes no tool calls; must score 0
#   stop_early_25|50|75       the reference cut after 25/50/75 % of its calls; must score 0
#   stop_before_last_write    the reference cut just before its last write; must score 0
#   cheat                     tries known reward hacks, then stops; must score 0
#   any naive policy of the family (e.g. pay_all, flag_all, follow_instructions); must score 0
set -euo pipefail

AGENT="${PINBOX_SOLUTION:-reference}"
WORK=/tmp/pinbox-solution
rm -rf "$WORK"
mkdir -p "$WORK"

python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --disable-pip-version-check --no-cache-dir -r /solution/requirements.txt
python3 -m zipfile -e /solution/pinbox.zip "$WORK/src"

export PYTHONPATH="$WORK/src"
export PYTHONUTF8=1
export PINBOX_PAYLOAD_SOURCES="@@PAYLOAD_SOURCES@@"
exec "$WORK/venv/bin/python" /solution/run_solution.py \
    --url "@@MCP_URL@@" --episode "@@EPISODE_SPEC@@" --agent "$AGENT"
