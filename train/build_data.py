import json, sys
from train.window import SYSTEM, prompt, call_json
from pathlib import Path

TRAIN_MAX, HELD_MIN = 99, 1000

def system_for(step):
    return SYSTEM

def examples(day, seats=None):
    if day["result"]["reward"] != 1:
        return []
    bad = day["day"]["sleeper_seat"]
    out, hist = [], {}
    for s in day["steps"]:
        if s["seat"] == bad or (seats and s["seat"] not in seats):
            continue
        h = hist.setdefault(s["seat"], [])
        msgs = prompt(system_for(s), s["seat"], h, s["view"])
        msgs.append({"role": "assistant", "content": call_json(s["tool"], s.get("args") or {})})
        out.append({"messages": msgs})
        h.append(s)
    return out

def split_of(seed):
    return "train" if seed <= TRAIN_MAX else "val" if seed >= HELD_MIN else None

def build(results_dir, out_dir, seats=None):
    buckets = {"train": [], "val": []}
    for p in sorted(Path(results_dir).glob("days/*-t*.json")):
        day = json.loads(p.read_text())
        k = split_of(day["day"]["day_id"])
        if k:
            buckets[k] += examples(day, seats)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for k, rows in buckets.items():
        (out / f"{k}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {k: len(v) for k, v in buckets.items()}

if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "train/data", sys.argv[3:] or None))
