from __future__ import annotations

import argparse
import json
from pathlib import Path

from canary.analysis.tags import WHY, load, to_result

LOSS_BELOW = 1.0


def build(eps, attribute=None):
    if attribute is None:
        from canary.solver.regret import attribute
    best, unlabelled, losses = {}, [], 0
    for e in eps:
        steps = {s["t"]: s for s in e.get("steps", [])}
        loss = float(e.get("score", 0.0)) < LOSS_BELOW
        losses += loss
        tagged = False
        for it in attribute(to_result(e)) or []:
            for tag in it.get("tags", []):
                tagged = True
                g = best.setdefault(tag, {"label": tag, "decision": WHY.get(tag, tag), "count": 0, "episodes_with": 0, "example": None, "_seen": set()})
                g["count"] += 1
                key = (e["agent"], e["tier"], e["seed"])
                if key not in g["_seen"]:
                    g["_seen"].add(key)
                    g["episodes_with"] += 1
                r = float(it.get("regret", 0.0))
                if g["example"] is None or r > g["example"]["regret"]:
                    p = it.get("p_best")
                    g["example"] = {"agent": e["agent"], "tier": e["tier"], "seed": e["seed"], "day": it.get("day"), "t": it.get("t"), "tool": it.get("action"),
                                    "args": steps.get(it.get("t"), {}).get("args", {}), "p_best": p, "regret": round(r, 4),
                                    "what_went_wrong": WHY.get(tag, tag).format(p=p or 0.0), "score": e.get("score")}
        if loss and not tagged:
            unlabelled.append({"agent": e["agent"], "tier": e["tier"], "seed": e["seed"]})
    for g in best.values():
        g.pop("_seen")
    return {"losses": losses, "unlabelled_losses": unlabelled, "labels": sorted(best.values(), key=lambda g: -g["count"])}


def check(g):
    problems = [f"loss without a label: {u}" for u in g["unlabelled_losses"]]
    problems += [f"label without an example: {x['label']}" for x in g["labels"] if not x["example"]]
    return problems


def md(g):
    L = ["# Failure gallery", "", f"{g['losses']} losing episodes, {len(g['unlabelled_losses'])} without a label.", ""]
    for x in g["labels"]:
        e = x["example"]
        L += [f"## {x['label']} ({x['count']} actions in {x['episodes_with']} episodes)", x["decision"], "",
              f"- Example: {e['agent']} {e['tier']} seed {e['seed']}, day {e['day']} step {e['t']}, {e['tool']} {json.dumps(e['args'])}",
              f"- Solver belief in its best suspect then: {e['p_best']}, regret {e['regret']}", f"- What went wrong: {e['what_went_wrong']}", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--tier")
    ap.add_argument("--agent-prefix")
    ap.add_argument("--out", default="data/analysis")
    a = ap.parse_args(argv)
    eps = [e for e in load(a.runs) if (not a.tier or e["tier"] == a.tier) and (not a.agent_prefix or e["agent"].startswith(a.agent_prefix))]
    g = build(eps)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "gallery.json").write_text(json.dumps(g, indent=1, default=str))
    (out / "gallery.md").write_text(md(g))
    bad = check(g)
    print(f"{len(eps)} episodes, {g['losses']} losses, {len(g['labels'])} labels, {len(bad)} problems")
    for p in bad:
        print(p)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
