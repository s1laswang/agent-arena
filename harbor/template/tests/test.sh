#!/bin/bash
# Verifier: reward = the server-side ledger score (CONTRACT section 4), never anything the agent wrote.
#   correct accusation -> V at that moment (0..1); wrong accusation -> -1; no accusation / horizon / cap -> 0.
# Evidence sources, in order:
#   1. /evidence/ledger.json: collected from the canary-server sidecar by the [[verifier.collect]] hook
#      (separate verifier, the default).
#   2. Fallback for shared-verifier builds (build.py --verifier shared, older Harbor without collect hooks):
#      GET http://canary-server:8765/ledger with CANARY_LEDGER_TOKEN from [verifier].env.
set -uo pipefail
mkdir -p /logs/verifier

python3 - <<'PY'
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

reward = Path("/logs/verifier/reward.txt")
evidence = Path("/evidence/ledger.json")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    reward.write_text("0")
    sys.exit(1)


if evidence.is_file() and not evidence.is_symlink():
    raw = evidence.read_text()
    source = "sidecar artifact /evidence/ledger.json"
elif os.environ.get("CANARY_LEDGER_TOKEN"):
    url = "http://canary-server:8765/ledger?" + urllib.parse.urlencode({"token": os.environ["CANARY_LEDGER_TOKEN"]})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode()
    except Exception as exc:  # noqa: BLE001
        fail(f"could not fetch /ledger from the server: {type(exc).__name__}")
    source = "GET /ledger (shared verifier)"
else:
    fail("no ledger evidence: /evidence/ledger.json missing and no CANARY_LEDGER_TOKEN")

try:
    led = json.loads(raw)
    score = float(led["score"])
except Exception as exc:  # noqa: BLE001
    fail(f"malformed ledger: {type(exc).__name__}")
if not (-1.0 <= score <= 1.0):
    fail(f"score out of range: {score}")

Path("/logs/verifier/ledger.json").write_text(raw)
reward.write_text(repr(score))
print(f"reward={score!r} source={source} done={led.get('done')} end_reason={led.get('end_reason')} "
      f"final_day={led.get('final_day')} V={led.get('V')} ledger_entries={len(led.get('ledger') or [])}")
PY
