import json, sys
from pathlib import Path

TRAIN_MAX, HELD_MIN = 99, 1000

def system_for(step):
    return step.get("system") or f"You are the {step['seat']} seat of a company. Use one tool per turn and reply with a JSON tool call."

def examples(day):
    if day.get("reward") != 1:
        return []
    bad = day.get("sleeper_seat")
    out = []
    for s in day.get("steps", []):
        if s["seat"] == bad or "tool" not in s:
            continue
        call = json.dumps({"tool": s["tool"], "args": s.get("args", {})}, sort_keys=True)
        out.append({"messages": [{"role": "system", "content": system_for(s)},
                                 {"role": "user", "content": s["obs"]},
                                 {"role": "assistant", "content": call}]})
    return out

def split_of(seed):
    return "train" if seed <= TRAIN_MAX else "val" if seed >= HELD_MIN else None

def build(results_dir, out_dir):
    buckets = {"train": [], "val": []}
    for p in sorted(Path(results_dir).glob("days/*.json")):
        day = json.loads(p.read_text())
        k = split_of(day["seed"])
        if k:
            buckets[k] += examples(day)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for k, rows in buckets.items():
        (out / f"{k}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {k: len(v) for k, v in buckets.items()}

if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "train/data"))
