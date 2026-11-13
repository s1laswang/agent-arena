import argparse, json, os, subprocess, sys
from pathlib import Path
from train.metrics import aggregate

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--out", required=True)
    ap.add_argument("--day-ids", default="1000-1019")
    ap.add_argument("--seat", default="controller")
    ap.add_argument("--trials", type=int, default=1)
    a = ap.parse_args()
    os.environ["SLEEPER_BASE_MODEL"] = a.model
    run_dir = Path(a.out)
    spec = f"local:{a.adapter or ''}@{a.model}"
    lo, _, hi = a.day_ids.partition("-")
    ids_arg = ",".join(str(i) for i in range(int(lo), int(hi or lo) + 1))
    subprocess.run([sys.executable, "-m", "lab.run", "--team", "staff", "--seat", a.seat, "--agent", spec,
                    "--day-ids", ids_arg, "--trials", str(a.trials), "--out", str(run_dir)], check=True)
    runs = [p for p in run_dir.iterdir() if (p / "days").is_dir()]
    m = aggregate(runs[0], a.seat)
    (run_dir / "metrics.json").write_text(json.dumps(m))
    print(json.dumps(m))

if __name__ == "__main__":
    main()
