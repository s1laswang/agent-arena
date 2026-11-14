import argparse, json, os, subprocess, sys
from pathlib import Path
from train.metrics import aggregate

def model_id(model, adapter, run_id):
    c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or os.environ.get("GIT_COMMIT", "nocommit")
    return f"{model.split('/')[-1]}+{run_id}+{c}" if adapter else f"{model.split('/')[-1]}+base+{c}"

def emit(rows, out, mid, seat):
    m, _, rest = mid.partition("+")
    c = mid.rsplit("+", 1)[-1]
    d = Path(out) / "frontier" / mid.rsplit("+", 1)[0] / c
    d.mkdir(parents=True, exist_ok=True)
    for r in rows:
        sc = {"reward": r["reward"], "harm": r["harm"], "false_quarantines": r["false_quarantine"]}
        (d / f"{seat}-s{r['day_id']}-t{r['trial']}.json").write_text(json.dumps({"model": mid.rsplit("+", 1)[0], "commit": c, "agent": "local", "seat": seat, "seed": r["day_id"], "trial": r["trial"], "mode": "seat", "team": "procedure", "sleeper": "scripted", "day_source": "day_for", "provenance": "real", "scores": sc}))

def play(agent, a, out):
    lo, _, hi = a.day_ids.partition("-")
    ids = ",".join(str(i) for i in range(int(lo), int(hi or lo) + 1))
    subprocess.run([sys.executable, "-m", "lab.run", "--team", a.team, "--seat", a.seat, "--agent", agent,
                    "--day-ids", ids, "--trials", str(a.trials), "--out", str(out)], check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--out", required=True)
    ap.add_argument("--day-ids", default="1000-1019")
    ap.add_argument("--seat", default="controller")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--filter", choices=["needs_tested_seat"])
    ap.add_argument("--no-scripted", action="store_true")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--team", default="procedure")
    a = ap.parse_args()
    os.environ["SLEEPER_BASE_MODEL"] = a.model
    os.environ["SLEEPER_MODEL_ID"] = model_id(a.model, a.adapter, a.run_id)
    os.environ["SLEEPER_ROW_LABEL"] = a.model.split("/")[-1] + (f"+adapter {a.run_id}" if a.adapter else " base")
    out = Path(a.out)
    play(f"local:{a.adapter or ''}@{a.model}", a, out / "model")
    runs = {"model": out / "model"}
    from lab.results import load_days
    emit(load_days(out / "model" / "days.jsonl"), out, os.environ["SLEEPER_MODEL_ID"], a.seat)
    os.environ.pop("SLEEPER_ROW_LABEL")
    if not a.no_scripted:
        play("oracle", a, out / "scripted")
        runs["scripted"] = out / "scripted"
    m = {k: {"all": aggregate(v, a.seat), "needs_tested_seat": aggregate(v, a.seat, only_needs=True)} for k, v in runs.items()}
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    print(json.dumps(m, indent=1))

if __name__ == "__main__":
    main()
