#!/bin/bash
# Verifier: reward = the server-side ledger score (CONTRACT section 4), never anything the agent wrote.
#   correct accusation -> V at that moment (0..1); wrong accusation -> -1; no accusation / horizon / cap -> 0.
# Evidence source, by build mode:
#   * shared-verifier build (build.py --verifier shared; CANARY_LEDGER_TOKEN is set in [verifier].env): this
#     script runs INSIDE the agent container, where any file (including /evidence and reward files) is
#     agent-writable. So it first kills every process the agent left behind, then grades ONLY from
#     GET http://canary-server:8765/ledger with the token and never reads /evidence (EXPLOITS #42).
#   * separate verifier (the default; no token): /evidence/ledger.json, collected from the canary-server
#     sidecar by the [[verifier.collect]] hook and copied into this separate verifier container.
# Harbor reads reward.json BEFORE reward.txt, so every outcome writes both. python3 runs with -I -S: no
# sitecustomize/usercustomize, no PYTHON* variables, no current-directory imports.
# Fails closed (reward 0 and a FAIL line) unless the ledger carries a valid HMAC-SHA256 signature under the
# build-time key (/tests/ledger_key, or CANARY_LEDGER_KEY for shared builds) and its score is in
# {-1, 0} U (0, 1]. The canonical form matches canary.mcp_server.sign_ledger (tests/test_harbor_ledger_sig.py).
set -uo pipefail
mkdir -p /logs/verifier

# Shared-verifier builds only: stop every process the agent left behind (e.g. a loop that keeps rewriting
# /logs/verifier/reward.{txt,json}). PID 1, this shell and its parent chain (Harbor's exec wrapper) stay:
# killing the wrapper would end the verifier session early.
if [ -n "${CANARY_LEDGER_TOKEN:-}" ]; then
  keep=" 1 $$ "
  p=$$
  while [ -r "/proc/$p/status" ]; do
    pp=""
    while read -r k v _; do if [ "$k" = "PPid:" ]; then pp="$v"; fi; done < "/proc/$p/status"
    if [ -z "$pp" ] || [ "$pp" = "0" ] || [ "$pp" = "1" ]; then break; fi
    keep="$keep$pp "
    p="$pp"
  done
  for pass in 1 2 3 4 5; do   # repeat: a process that forks while we kill must not survive
    if command -v ps >/dev/null 2>&1; then pids=$(ps -eo pid= 2>/dev/null); else pids=$(ls /proc | grep -E '^[0-9]+$'); fi
    left=0
    for q in $pids; do
      case "$keep" in *" $q "*) ;; *) if kill -9 "$q" 2>/dev/null; then left=1; fi ;; esac
    done
    [ "$left" = 0 ] && break
    sleep 0.2
  done
  rm -f /logs/verifier/reward.txt /logs/verifier/reward.json
fi

python3 -I -S - <<'PY'
import hashlib
import hmac
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

reward = Path("/logs/verifier/reward.txt")
reward_json = Path("/logs/verifier/reward.json")   # Harbor reads reward.json BEFORE reward.txt: always write both
evidence = Path("/evidence/ledger.json")
key_file = Path("/tests/ledger_key")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", flush=True)
    reward.write_text("0")
    reward_json.write_text('{"reward": 0}')
    sys.exit(1)


reward.write_text("0")  # fail closed even if this script dies before the end
reward_json.write_text('{"reward": 0}')

# [verifier].env (shared builds only) wins: in a shared verifier /tests sits in the agent's container.
key = None
if os.environ.get("CANARY_LEDGER_KEY"):
    key = os.environ["CANARY_LEDGER_KEY"].strip().encode() or None
elif key_file.is_file() and not key_file.is_symlink():
    key = key_file.read_text().strip().encode() or None
if not key:
    fail("no ledger signing key (/tests/ledger_key or CANARY_LEDGER_KEY): cannot verify the ledger")

if os.environ.get("CANARY_LEDGER_TOKEN"):  # shared verifier: never trust a file in the agent's container
    url = "http://canary-server:8765/ledger?" + urllib.parse.urlencode({"token": os.environ["CANARY_LEDGER_TOKEN"]})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode()
    except Exception as exc:  # noqa: BLE001
        fail(f"could not fetch /ledger from the server: {type(exc).__name__}")
    source = "GET /ledger (shared verifier; /evidence ignored)"
elif evidence.is_file() and not evidence.is_symlink():
    raw = evidence.read_text()
    source = "sidecar artifact /evidence/ledger.json"
else:
    fail("no ledger evidence: /evidence/ledger.json missing and no CANARY_LEDGER_TOKEN")

try:
    led = json.loads(raw)
except Exception as exc:  # noqa: BLE001
    fail(f"malformed ledger: {type(exc).__name__}")
if not isinstance(led, dict):
    fail("malformed ledger: not a JSON object")

sig = led.get("sig")
if not isinstance(sig, dict) or not isinstance(sig.get("mac"), str):
    fail("ledger is not signed (no sig.mac)")
if sig.get("alg") != "HMAC-SHA256":
    fail(f"unsupported ledger signature algorithm: {sig.get('alg')!r}")
body = {k: v for k, v in led.items() if k != "sig"}
canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
if not hmac.compare_digest(hmac.new(key, canonical, hashlib.sha256).hexdigest(), sig["mac"]):
    fail("bad ledger signature: the ledger was not written by this task's canary-server, or was edited")

score = led.get("score")
if isinstance(score, bool) or not isinstance(score, (int, float)):
    fail(f"malformed ledger: score is {type(score).__name__}, not a number")
score = float(score)
if not math.isfinite(score) or not (score == -1.0 or 0.0 <= score <= 1.0):
    fail(f"score outside {{-1, 0}} U (0, 1]: {score!r}")

Path("/logs/verifier/ledger.json").write_text(raw)
reward.write_text(repr(score))
reward_json.write_text(json.dumps({"reward": score}))
print(f"reward={score!r} source={source} signature=ok done={led.get('done')} end_reason={led.get('end_reason')} "
      f"final_day={led.get('final_day')} V={led.get('V')} ledger_entries={len(led.get('ledger') or [])}")
PY
