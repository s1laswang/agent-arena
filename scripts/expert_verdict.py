"""Track 2 verdict: gemini-4-carbon (OpenCode over MCP) vs the reference solver on the EXPERT tier, paired by seed.

    uv run --extra llm python scripts/expert_verdict.py --staging data/runs/staging-gemini-v1.4-expert \
        [--staging data/runs/staging-gemini-v1.4-expert-b] --out results/expert_verdict

Reports (same method as scripts/paired_gemini.py / docs/reports/gap.md):
  * ratio = mean_Gemini / mean_solver on shared seeds, paired bootstrap 95% CI (10,000 resamples)
  * luck-adjusted ratio: each accusation scored P*V - (1-P) under the solver's exact posterior at that step
  * single-canary-hit accusations: the accused was implicated by exactly ONE leaked canary label seen before accusing
    (at fingerprint accuracy 0.70 one label is weak evidence). Same statistic for the solver on the same seeds.
The solver is rerun in-process on the same seeds (deterministic). Only VALID Gemini episodes are used (the runner moves
infra failures to <staging>/invalid/ and retries them).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from canary.analysis.gap import load_runs  # noqa: E402
from paired_v13 import boot_ratio, p_acc, post_expected  # noqa: E402

TIER = "expert"


def gemini_episodes(stagings: list[str]) -> list[dict]:
    eps = {}
    for st in stagings:
        base = Path(st) / "opencode" / TIER
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if (d / "episodes.jsonl").exists() or any(d.rglob("episodes.jsonl")):
                for e in load_runs(d):
                    if e["tier"] == TIER and e.get("end_reason") != "error":
                        eps[e["seed"]] = e
    return [eps[s] for s in sorted(eps)]


def solver_episodes(seeds: list[int]) -> dict[int, dict]:
    from dataclasses import asdict
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy
    out = {}
    for s in seeds:
        r = run_episode(Env(TIER, s), SolverPolicy(None))
        e = asdict(r)
        e["accused"] = r.end_reason == "accused"
        out[s] = e
    return out


def _get(st, k):
    return st.get(k) if isinstance(st, dict) else getattr(st, k)


def single_canary_hit(e: dict) -> bool | None:
    """Accused employee implicated by exactly one leaked canary label in the feed seen before the accusation."""
    steps = e.get("steps") or []
    acc = next((s for s in reversed(steps) if _get(s, "tool") == "accuse"), None)
    if acc is None:
        return None
    who = (_get(acc, "args") or {}).get("employee")
    docs, hits = {}, set()
    for s in steps:
        tool, res = _get(s, "tool"), _get(s, "result") or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if tool == "list_documents":
            for d in data.get("documents", []):
                docs[d.get("doc_id")] = d
        if tool == "plant_canary":
            did = data.get("doc_id")
            asg = (_get(s, "args") or {}).get("assignment") or {}
            if did:
                groups = {}
                for emp, lab in asg.items():
                    groups.setdefault(lab, []).append(emp)
                docs[did] = {"doc_id": did, "variants": groups}
        if tool == "check_leak_feed":
            for it in data.get("items", []):
                lab, did = it.get("variant"), it.get("doc_id")
                if lab and did in docs and who in (docs[did].get("variants") or {}).get(lab, []):
                    hits.add((did, lab))
        if s is acc:
            break
    return len(hits) == 1


def summarise(gem: list[dict], sol: dict[int, dict]) -> dict:
    seeds = [e["seed"] for e in gem if e["seed"] in sol]
    g = [e for e in gem if e["seed"] in sol]
    s = [sol[x] for x in seeds]
    f, r = [e["score"] for e in g], [e["score"] for e in s]
    n = len(g)
    lo, hi = boot_ratio(f, r) if n > 1 else (float("nan"), float("nan"))
    lg, ls = [post_expected(e) for e in g], [post_expected(e) for e in s]
    ok = [i for i in range(n) if lg[i] is not None and ls[i] is not None]
    lf, lr = [lg[i] for i in ok], [ls[i] for i in ok]
    llo, lhi = boot_ratio(lf, lr) if len(ok) > 1 else (float("nan"), float("nan"))

    def acc_stats(es):
        accd = [e for e in es if e.get("accused") or e.get("end_reason") == "accused"]
        ps = [p_acc(e) for e in accd]
        ps = [p for p in ps if p is not None]
        sch = [single_canary_hit(e) for e in accd]
        return {"accused_rate": len(accd) / len(es) if es else None,
                "accuracy_among_accused": sum(e["correct"] for e in accd) / len(accd) if accd else None,
                "mean_P_at_accusation": sum(ps) / len(ps) if ps else None,
                "below_break_even": sum(1 for e in accd if (p_acc(e) is not None and (e.get("meta") or {}).get("V") is not None
                                                           and p_acc(e) < 1 / (1 + float(e["meta"]["V"])))),
                "single_canary_hit_accusations": sum(1 for x in sch if x), "n_accused": len(accd)}

    return {"tier": TIER, "n": n, "seeds": seeds,
            "gemini_mean": sum(f) / n if n else None, "solver_mean_same_seeds": sum(r) / n if n else None,
            "ratio": (sum(f) / sum(r)) if n and sum(r) else None, "ratio_ci": [lo, hi],
            "luck_adj_gemini": sum(lf) / len(lf) if lf else None, "luck_adj_solver": sum(lr) / len(lr) if lr else None,
            "luck_adj_ratio": (sum(lf) / sum(lr)) if lf and sum(lr) else None, "luck_adj_ratio_ci": [llo, lhi],
            "gemini": acc_stats(g), "solver": acc_stats(s),
            "per_seed": [{"seed": x, "gemini": e["score"], "gemini_correct": e["correct"], "solver": sol[x]["score"],
                          "gemini_P": p_acc(e), "gemini_single_canary_hit": single_canary_hit(e)}
                         for x, e in zip(seeds, g)]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", action="append", required=True)
    ap.add_argument("--out", default="results/expert_verdict")
    a = ap.parse_args(argv)
    gem = gemini_episodes(a.staging)
    sol = solver_episodes([e["seed"] for e in gem])
    res = summarise(gem, sol)
    Path(a.out + ".json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "per_seed"}, indent=1, default=str))
    for row in res["per_seed"]:
        print(row)


if __name__ == "__main__":
    main()
