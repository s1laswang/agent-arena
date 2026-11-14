"""Every committed Canary Lab results JSON must parse (the dashboard and the submission read them)."""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_results_json_parse():
    files = [f for f in glob.glob(str(ROOT / "results" / "gemini" / "**" / "*.json"), recursive=True)
             if "/_cache/" not in f and "/replay" not in f and "_cache/" not in f]
    assert files
    bad = []
    for f in files:
        try:
            json.load(open(f))
        except Exception as e:  # noqa: BLE001
            bad.append(f"{f}: {e}")
    assert not bad, "\n".join(bad)
