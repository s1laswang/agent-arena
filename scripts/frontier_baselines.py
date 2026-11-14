import argparse, json, os, subprocess
from lab import run
from sleeper.baselines import BASELINES, register

ROWS = {"do_nothing": "do_nothing", "stop_early": "stop_early", "trust_all": "trust_all", "refuse_all": "refuse_all", "quarantine_all": "quarantine_all", "random_accuse": "random_accuse", "reference": "oracle", "oracle": "scripted_oracle"}
NS = (1, 5, 20)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default="finance_ap")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--out", default="results/frontier")
    ap.add_argument("--all8", action="store_true")
    a = ap.parse_args(argv)
    register()
    run.FACTORIES["scripted_oracle"] = (run._scripted("OracleAgent"), "scripted")
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    runs = {}
    for label, key in ROWS.items():
        for mode in ("seat", "all8") if a.all8 else ("seat",):
            for d in range(1000, 1000 + a.n):
                for t in range(a.trials):
                    r, _ = run.play_day("oracle", key, a.seat, d, t) if mode == "seat" else run.play_day(key, key, None, d, t)
                    rec = {"model": f"scripted:{label}", "commit": commit, "agent": "scripted", "seat": a.seat if mode == "seat" else None, "seed": d, "trial": t, "mode": mode, **({"role": "reference"} if label == "reference" else {}),
                           "has_sleeper": r["has_sleeper"], "scores": {"reward": r["reward"], "harm": r["harm"], "false_quarantines": r.get("false_quarantines"), "sleeper_caught": r.get("sleeper_caught")}}
                    runs.setdefault((label, mode), []).append(rec)
                    p = f"{a.out}/scripted:{label}/{commit}"
                    os.makedirs(p, exist_ok=True)
                    json.dump(rec, open(f"{p}/{a.seat if mode == 'seat' else 'all8'}-s{d}" + f"-t{t}.json", "w"), indent=1)
    rows = []
    for (label, mode), rs in runs.items():
        for n in NS:
            if n > a.n:
                continue
            sub = [r for r in rs if r["seed"] < 1000 + n]
            rows.append({"seat": a.seat if mode == "seat" else "all8", "model": f"scripted:{label}", "n": len(sub), "n_days": n, "reward_mean": round(sum(r["scores"]["reward"] for r in sub) / len(sub), 3),
                         "harm_rate": round(sum(1 for r in sub if r["scores"]["harm"]) / len(sub), 3), "trials": a.trials, "commit": commit})
    json.dump(rows, open(f"{a.out}/baselines.json", "w"), indent=1)
    md = ["| seat | model | days | n | reward mean | harm rate | trials | commit |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['seat']} | {r['model']} | {r['n_days']} | {r['n']} | {r['reward_mean']} | {r['harm_rate']} | {r['trials']} | {r['commit']} |" for r in rows]
    open(f"{a.out}/baselines.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
