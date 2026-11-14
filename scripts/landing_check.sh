#!/bin/sh
set -e
PY=.venv/bin/python
git fetch -q origin
git merge --no-edit "${1:-origin/momin}" || { git merge --abort; echo "MERGE CONFLICT"; exit 1; }
$PY -m sleeper.baselines
$PY -m pytest tests/test_seat_gate.py tests/test_baselines.py -q -k "gate or seat" 2>&1 | tail -15
