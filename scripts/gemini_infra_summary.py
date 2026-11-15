"""Infra-invalid attempt counts (k/n) per harness/tier from a gemini_runner staging dir, with raw evidence.

    python scripts/gemini_infra_summary.py data/runs/staging-gemini-v1.4 [--seeds 0-29]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def classify(reason: str) -> str:
    if "empty_model_response" in reason:
        return "empty model reply (finish=stop, no text, no tool call)"
    if "model turn are not supported" in reason or "cli_error_event" in reason:
        return "CLI error event (API 400 'ends with a model turn' / TLS handshake)"
    if "provider_unavailable" in reason:
        return "provider unavailable"
    if "api:" in reason:
        return "in-process API error"
    return reason[:60]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("staging")
    ap.add_argument("--seeds", default="0-29")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split("-"))
    st = Path(a.staging)
    valid: Counter = Counter()
    nores: Counter = Counter()
    inv: dict = defaultdict(Counter)
    for h in ("opencode", "inproc"):
        for t in ("medium", "hard"):
            for d in (st / h / t).glob("*") if (st / h / t).exists() else []:
                f = d / "episodes.jsonl"
                if d.name.isdigit() and lo <= int(d.name) <= hi and f.exists() and f.read_text().strip():
                    e = json.loads(f.read_text().splitlines()[-1])
                    valid[(h, t)] += 1
                    if not e.get("accused"):
                        nores[(h, t)] += 1
    for d in (st / "invalid").glob("*") if (st / "invalid").exists() else []:
        h, t, s = d.name.split("-")[:3]
        if not (lo <= int(s) <= hi):
            continue
        reason = (d / "INVALID.txt").read_text() if (d / "INVALID.txt").exists() else ""
        tr = " ".join(p.read_text(errors="replace") for p in (d / "transcripts").glob("*.txt")) if (d / "transcripts").exists() else ""
        m = re.search(r'"message":"([^"]{0,80})', tr)
        inv[(h, t)][classify(reason + " " + (m.group(1) if m else ""))] += 1
    for key in sorted(set(valid) | set(inv)):
        n_inv = sum(inv[key].values())
        print(f"{key[0]} {key[1]}: valid episodes {valid[key]} (of which ended without an accusation: {nores[key]}); "
              f"infra-invalid attempts {n_inv} of {valid[key] + n_inv} attempts")
        for k, v in inv[key].most_common():
            print(f"    {v:3d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
