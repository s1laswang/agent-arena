"""The cross-provider control's Gemini episodes replay keyless from the committed gateway recording."""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "results" / "gemini" / "xprov-replay" / "flash"
EXPORT = ROOT / "results" / "gemini" / "xprov_episodes.jsonl.gz"


def test_committed_control_episode_replays_keyless_to_the_recorded_score(tmp_path):
    pytest.importorskip("google.genai")
    if not STORE.exists() or not EXPORT.exists():
        pytest.skip("no committed cross-provider recording")
    want = None
    with gzip.open(EXPORT, "rt") as fh:
        for line in fh:
            e = json.loads(line)
            lad = (e.get("meta") or {}).get("ladder") or {}
            if (lad.get("model"), lad.get("level"), lad.get("tier"), int(lad.get("seed", -1))) == \
                    ("gemini-3.5-flash", "medium", "hard", 0):
                want = e
    assert want is not None, "export lacks gemini-3.5-flash/medium/hard/0"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
    env["GEMINI_API_KEY"] = ""
    out = tmp_path / "replay"
    r = subprocess.run([sys.executable, "-m", "canary.gemini.with_gateway", "--replay", str(STORE),
                        "--ledger", str(tmp_path / "ledger.jsonl"), "--",
                        sys.executable, "scripts/with_tiers.py", "v1.3", "-m", "canary.gemini.ladder",
                        "--models", "gemini-3.5-flash", "--levels", "medium", "--tiers", "hard", "--seeds", "0",
                        "--concurrency", "1", "--max-attempts", "1", "--out", str(out), "--run-name", "xprov-v13"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    got = json.loads((out / "gemini-3.5-flash" / "medium" / "hard" / "0" / "episodes.jsonl").read_text().splitlines()[0])
    assert got["score"] == want["score"] and got.get("accused") == want.get("accused")
    assert len(got["steps"]) == len(want["steps"])
    assert ((got.get("meta") or {}).get("ladder") or {}).get("tiers_version") == "v1.3"
