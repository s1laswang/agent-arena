"""Hint ablations: LLMPolicy(hint=tag) per tag + a no-hint control; table of tag rate and mean score per arm.

    python -m canary.agents.ablate --tier hard --seeds 0-4 --tags premature_accusation,ignored_delay,decoy_chase \
        [--agent openai:gpt-5.5] [--budget 40] [--fake] [--out data/runs/ablate-<tier>-<stamp>]

Each arm is written as its own data/runs-style dir (<out>/<arm>/episodes.jsonl, meta.json, transcripts/).
Running cost is printed after every episode; the run stops before the next episode once cost >= --budget.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from canary.agents.llm_policy import HINTS, LLMPolicy
from canary.agents.loop import run_episode
from canary.agents.play import make_env, resolve_agent
from canary.agents.runlog import RunWriter, git_sha, parse_seeds, split_spec


def main(argv=None, client_factory=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=None)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--tags", required=True, help="comma list of hint tags")
    ap.add_argument("--budget", type=float, default=40.0, help="USD; stop starting new episodes past this")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--hint-set", default="v1", choices=["v1", "v2"])
    ap.add_argument("--no-control", action="store_true", help="skip the control arm (run arms as parallel processes)")
    a = ap.parse_args(argv)
    agent = resolve_agent(a.agent)
    tags = [t.strip() for t in a.tags.split(",") if t.strip()]
    from canary.agents.llm_policy import HINT_SETS
    bad = [t for t in tags if t not in HINT_SETS[a.hint_set]]
    if bad:
        ap.error(f"unknown tags {bad}; known {sorted(HINTS)}")
    seeds = parse_seeds(a.seeds)
    out = Path(a.out or f"data/runs/ablate-{a.tier}-{time.strftime('%Y%m%d-%H%M')}")
    provider, model = split_spec(agent)
    arms = ([] if a.no_control else [("control", None)]) + [(t, t) for t in tags]
    cost, stopped = 0.0, False
    results: dict[str, list] = {}
    for arm, hint in arms:
        w = RunWriter(out / arm)
        results[arm] = []
        usage = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0}
        for seed in seeds:
            if cost >= a.budget:
                stopped = True
                break
            pol = LLMPolicy(agent, hint=hint, hint_set=a.hint_set, client=client_factory() if client_factory else None)
            env = make_env(a.tier, seed, a.fake)
            try:
                res = run_episode(env, pol, pol.name)
            except Exception as e:
                res = env.result(pol.name)
                res.end_reason, res.meta = "error", {**(res.meta or {}), "error": repr(e)}
            res.meta = {**(res.meta or {}), "usage": pol.usage, "hint": hint, "arm": arm}
            w.episode(res)
            w.transcript(seed, pol.transcript)
            for k in usage:
                usage[k] += pol.usage.get(k, 0)
            cost += pol.usage.get("cost_usd", 0.0) or 0.0
            results[arm].append(res)
            print(f"[{arm}] seed {seed}: score={res.score:+.3f} correct={res.correct}  running cost ${cost:.2f}", flush=True)
        w.meta({"agent": agent, "model": model, "provider": provider, "git_sha": git_sha(), "tier": a.tier,
                "seeds": seeds, "hint": hint, "hint_set": a.hint_set, "arm": arm, "usage": usage, "smoke": bool(a.smoke or a.fake),
                "fake_env": a.fake})
        if stopped:
            print(f"budget ${a.budget:.2f} reached; stopping")
            break
    table = summarize(out, arms, tags, a.fake)
    (out / "ablation.json").write_text(json.dumps({"agent": agent, "tier": a.tier, "seeds": seeds, "cost_usd": cost,
                                                   "budget_stopped": stopped, "table": table}, indent=1))
    md = render(table, tags)
    (out / "ablation.md").write_text(md)
    print(md)
    print(f"total cost ${cost:.2f}; wrote {out}")
    return table


def summarize(out: Path, arms, tags, fake: bool) -> dict:
    from canary.analysis.gap import load_runs
    from canary.analysis.tags import tag_report
    attribute = (lambda ep: []) if fake else None  # fake episodes are not solver-replayable
    table = {}
    for arm, _ in arms:
        eps = _load_arm(out / arm)
        if not eps:
            continue
        rep = tag_report(eps, attribute)
        agent_rep = next(iter(rep.values()))
        table[arm] = {"n": len(eps), "score_mean": agent_rep["score_mean"],
                      "accuracy": round(sum(e["correct"] for e in eps) / len(eps), 3),
                      "tag_rate": {t: agent_rep["tags"].get(t, {}).get("rate", 0.0) for t in tags},
                      "regret_total": agent_rep["regret_total"]}
    return table


def _load_arm(d: Path) -> list[dict]:
    f = d / "episodes.jsonl"
    if not f.exists():
        return []
    eps = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    for e in eps:
        e.setdefault("meta", {})["run_id"] = d.name
    return eps


def render(table: dict, tags: list[str]) -> str:
    head = "| arm | n | mean score | accuracy | " + " | ".join(f"{t} rate" for t in tags) + " |"
    sep = "|" + "---|" * (4 + len(tags))
    rows = [f"| {arm} | {r['n']} | {r['score_mean']:+.3f} | {r['accuracy']:.2f} | "
            + " | ".join(f"{r['tag_rate'][t]:.2f}" for t in tags) + " |" for arm, r in table.items()]
    return "\n".join([head, sep, *rows])


if __name__ == "__main__":
    main()
