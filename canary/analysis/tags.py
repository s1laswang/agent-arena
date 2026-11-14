"""Failure tagging over data/runs/*/episodes.jsonl using ENV's canary.solver.regret.attribute.

    python -m canary.analysis.tags [--runs data/runs] [--tier hard] [--agent-prefix openai:] [--out data/analysis/tags.json]

Output JSON: {agent: {"episodes": n, "tier": {...}, "tags": {tag: {"count", "episodes_with", "rate",
"regret_sum", "worst": {run_id, seed, t, day, tool, args, regret, p_best, why}}}, "regret_total"}}
`rate` = share of that agent's episodes with >= 1 instance of the tag.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from canary.types import EpisodeResult, Step

WHY = {
    "premature_accusation": "accused before the evidence was decisive (solver top-suspect belief {p:.2f} < 0.6)",
    "decoy_chase": "acted against the decoy (the loud innocent)",
    "ignored_delay": "accused while a leak could still surface in the feed",
    "uninformative_canary": "canary variants split the suspects poorly (low information)",
    "over_restriction": "restricted an employee the evidence says is very unlikely the mole",
    "budget_waste": "repeated or failed call that used budget without new information",
    "no_accusation": "episode ended without an accusation (best belief {p:.2f})",
}


def to_result(e: dict) -> EpisodeResult:
    steps = [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in e.get("steps", [])]
    return EpisodeResult(tier=e["tier"], seed=e["seed"], agent=e["agent"], steps=steps, score=e["score"],
                         accused=e.get("accused"), correct=e.get("correct", False), final_day=e.get("final_day", 0),
                         end_reason=e.get("end_reason", "error"), meta=e.get("meta") or {})


def load(root: str | Path) -> list[dict]:
    from canary.analysis.gap import load_runs
    return load_runs(root)


def tag_report(eps: list[dict], attribute: Callable[[EpisodeResult], list[dict]] | None = None) -> dict[str, Any]:
    if attribute is None:
        from canary.solver.regret import attribute as attribute  # ENV's
    rep: dict[str, Any] = {}
    for e in eps:
        a = rep.setdefault(e["agent"], {"episodes": 0, "tiers": defaultdict(int), "regret_total": 0.0, "tags": {},
                                        "score_mean": 0.0, "_scores": []})
        a["episodes"] += 1
        a["tiers"][e["tier"]] += 1
        a["_scores"].append(float(e.get("score", 0.0)))
        steps_by_t = {s["t"]: s for s in e.get("steps", [])}
        seen_tags = set()
        for item in attribute(to_result(e)) or []:
            r = float(item.get("regret", 0.0))
            a["regret_total"] += r
            for tag in item.get("tags", []):
                d = a["tags"].setdefault(tag, {"count": 0, "episodes_with": 0, "regret_sum": 0.0, "worst": None})
                d["count"] += 1
                d["regret_sum"] += r
                if tag not in seen_tags:
                    d["episodes_with"] += 1
                    seen_tags.add(tag)
                if d["worst"] is None or r > d["worst"]["regret"]:
                    st = steps_by_t.get(item.get("t"), {})
                    p = item.get("p_best") or 0.0
                    d["worst"] = {"run_id": (e.get("meta") or {}).get("run_id"), "seed": e["seed"], "t": item.get("t"),
                                  "day": item.get("day"), "tool": item.get("action"), "args": st.get("args", {}),
                                  "regret": round(r, 4), "p_best": item.get("p_best"),
                                  "why": WHY.get(tag, tag).format(p=p)}
    for a in rep.values():
        a["tiers"] = dict(a["tiers"])
        s = a.pop("_scores")
        a["score_mean"] = round(sum(s) / len(s), 4) if s else 0.0
        a["regret_total"] = round(a["regret_total"], 4)
        for d in a["tags"].values():
            d["rate"] = round(d["episodes_with"] / a["episodes"], 3)
            d["regret_sum"] = round(d["regret_sum"], 4)
        a["tags"] = dict(sorted(a["tags"].items(), key=lambda kv: -kv[1]["regret_sum"]))
    return rep


def top_tags(rep: dict, agent: str, k: int = 3) -> list[str]:
    tags = rep.get(agent, {}).get("tags", {})
    return sorted(tags, key=lambda t: (-tags[t]["rate"], -tags[t]["regret_sum"]))[:k]


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--tier", default=None)
    ap.add_argument("--agent-prefix", default=None)
    ap.add_argument("--out", default="data/analysis/tags.json")
    a = ap.parse_args(argv)
    eps = [e for e in load(a.runs) if (not a.tier or e["tier"] == a.tier)
           and (not a.agent_prefix or e["agent"].startswith(a.agent_prefix))]
    rep = tag_report(eps)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=str))
    for agent, d in sorted(rep.items()):
        top = ", ".join(f"{t}={v['rate']:.2f}/{v['regret_sum']:.2f}" for t, v in list(d["tags"].items())[:4])
        print(f"{agent:32s} n={d['episodes']:3d} score={d['score_mean']:.3f} regret={d['regret_total']:.2f}  {top}")
    print(f"wrote {a.out}")
    return rep


if __name__ == "__main__":
    main()
