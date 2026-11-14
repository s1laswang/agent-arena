"""Held-out paired comparison: RL mole vs the default mole on the SAME seeds (hard tier).
Per seed: solver score/correct, each investigator's score, and regret_k = solver - investigator_k.
Paired bootstrap 95% CIs (2000 resamples, seeded) on the per-seed differences RL - default.
    uv run python scripts/rl_mole_heldout.py --policy data/rl_mole/policy_final.json --n 100 --workers 3
"""
import argparse, json, random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from canary.forge.rl_mole import EVAL_SEED_BASE, INVESTIGATORS, RLMole, _default_rollout, rollout

AG = ("solver",) + INVESTIGATORS


def boot(xs, B=2000, seed=0):
    r = random.Random(seed); n = len(xs)
    ms = sorted(sum(xs[r.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return [round(sum(xs) / n, 4), round(ms[int(.025 * B)], 4), round(ms[int(.975 * B)], 4)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="data/rl_mole/policy_final.json")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default="data/rl_mole/heldout_paired.json")
    a = ap.parse_args()
    pol = RLMole.from_json(json.loads(Path(a.policy).read_text()))
    seeds = list(range(EVAL_SEED_BASE, EVAL_SEED_BASE + a.n))
    with ProcessPoolExecutor(a.workers) as ex:
        d = list(ex.map(_default_rollout, [(None, "hard", s) for s in seeds]))
        r = list(ex.map(rollout, [(pol.p, "hard", s, AG, False) for s in seeds]))
    out = {"seeds": f"{seeds[0]}-{seeds[-1]}", "n": a.n, "policy": a.policy, "ci": "paired bootstrap 95%, [mean, lo, hi]"}
    for name, rows in (("default", d), ("rl", r)):
        out[name] = {ag: {"score": boot([x[ag][0] for x in rows]), "acc": boot([float(x[ag][1]) for x in rows])} for ag in AG}
        out[name]["regret"] = {k: boot([x["solver"][0] - x[k][0] for x in rows]) for k in INVESTIGATORS}
    out["diff_rl_minus_default"] = {
        **{f"{ag}_score": boot([y[ag][0] - x[ag][0] for x, y in zip(d, r)]) for ag in AG},
        "solver_acc": boot([float(y["solver"][1]) - float(x["solver"][1]) for x, y in zip(d, r)]),
        **{f"regret_{k}": boot([(y["solver"][0] - y[k][0]) - (x["solver"][0] - x[k][0]) for x, y in zip(d, r)])
           for k in INVESTIGATORS}}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out["diff_rl_minus_default"], indent=1))
    print("solver acc default/rl:", out["default"]["solver"]["acc"], out["rl"]["solver"]["acc"])
    print("regret default:", out["default"]["regret"]); print("regret rl:", out["rl"]["regret"])


if __name__ == "__main__":
    main()
