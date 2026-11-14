import argparse, json, random, subprocess, sys
from pathlib import Path
from train.build_data import examples, UP, KEEP, split_of
from train.eval import play
from train.metrics import seat_metrics

def keep(day, seat, harmful=None):
    m = seat_metrics(day, seat, harmful)
    return not m["fooled"] and m["false_accusations"] == 0 and m["tickets_done"] == m["tickets_total"]

def select(run_dir, seat, harmful=None):
    rows = []
    for p in sorted(Path(run_dir).rglob("days/*-t*.json")):
        d = json.loads(p.read_text())
        if split_of(d["day"]["day_id"]) == "train" and keep(d, seat, harmful):
            rows += examples(d, [seat], force=True)
    rng = random.Random(1)
    out = []
    for r in rows:
        if r["decision"]:
            out += [r] * UP
        elif rng.random() < KEEP:
            out.append(r)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--base-data", default="train/data/train.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--day-ids", default="0-99")
    ap.add_argument("--seat", default="controller")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=2)
    a = ap.parse_args()
    out = Path(a.out)
    play(f"local:{a.adapter or ''}@{a.model}", a, out / "runs")
    new = select(out / "runs", a.seat)
    data = out / "train.jsonl"
    old = Path(a.base_data).read_text() if Path(a.base_data).exists() else ""
    data.write_text(old + "".join(json.dumps(r) + "\n" for r in new))
    print({"new": len(new)})
    subprocess.run([sys.executable, "-m", "train.sft", "--model", a.model, "--data", str(data), "--out", str(out / "adapter"), "--epochs", str(a.epochs)], check=True)

if __name__ == "__main__":
    main()
