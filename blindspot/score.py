"""Score a saved day: python -m blindspot.score runs/state.json [--json]

The state file holds only what the agent's actions produced (world + ledger).
The answer key is regenerated from the seed, so the agent never sees it.
"""
from __future__ import annotations

import argparse
import json

from . import world as worldmod
from .verify import score


def score_file(path: str) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    _, hidden = worldmod.generate(data["seed"], **(data.get("plan") or {}))
    return score({"world": data["world"], "hidden": hidden, "ledger": data.get("ledger", [])})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    s = score_file(a.path)
    if a.json:
        print(json.dumps(s, indent=1))
        return
    print(f"reward={s['reward']}  tickets {s['tickets_ok']}/{s['tickets_total']}  "
          f"hazards caught {s['hazards_caught']}/{s['hazards_total']}  EUR lost {s['eur_lost']:,.2f}")
    for h in s["harms"]:
        print("  HARM:", h)
    for tid, t in s["tickets"].items():
        if not t["ok"]:
            print(f"  {tid} [{t['family']}{' HAZARD' if t['hazard'] else ''}]: {'; '.join(t['reasons'])}")


if __name__ == "__main__":
    main()
