import argparse, json, os, subprocess, sys
from pathlib import Path
from train.metrics import aggregate

def play(agent, a, out):
    lo, _, hi = a.day_ids.partition("-")
    ids = ",".join(str(i) for i in range(int(lo), int(hi or lo) + 1))
    subprocess.run([sys.executable, "-m", "lab.run", "--team", "staff", "--seat", a.seat, "--agent", agent,
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
    a = ap.parse_args()
    os.environ["SLEEPER_BASE_MODEL"] = a.model
    out = Path(a.out)
    play(f"local:{a.adapter or ''}@{a.model}", a, out / "model")
    runs = {"model": out / "model"}
    if not a.no_scripted:
        play("oracle", a, out / "scripted")
        runs["scripted"] = out / "scripted"
    m = {k: {"all": aggregate(v, a.seat), "needs_tested_seat": aggregate(v, a.seat, only_needs=True)} for k, v in runs.items()}
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    print(json.dumps(m, indent=1))

if __name__ == "__main__":
    main()
