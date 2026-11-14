"""Harbor [[verifier.collect]] hook, run INSIDE the canary-server sidecar after the agent finishes.

Reads the sidecar-only ledger token, fetches GET /ledger from the local server and writes
/evidence/ledger.json, which Harbor then copies to the verifier as an artifact.
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

token = Path("/run/canary/ledger_token").read_text().strip()
url = "http://127.0.0.1:8765/ledger?" + urllib.parse.urlencode({"token": token})
with urllib.request.urlopen(url, timeout=30) as resp:
    payload = json.load(resp)
out = Path("/evidence/ledger.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload))
out.chmod(0o644)
print(f"collected ledger: score={payload.get('score')} done={payload.get('done')} end_reason={payload.get('end_reason')}",
      file=sys.stderr)
