import json, random, sys
from collections import Counter
from train.window import SYSTEM, prompt, call_json
from pathlib import Path

TRAIN_MAX, HELD_MIN = 99, 1000
ACTS = ('approve_payment', 'quarantine', 'report_insider', 'pay', 'add_vendor', 'update_vendor_bank', 'share_doc_external', 'grant_role', 'create_account', 'edit_contract')
UP, KEEP = 5, 0.25

def is_decision(step, hist):
    if step['tool'] in ACTS:
        return True
    last = hist[-1] if hist else None
    return bool(last and last['tool'] in ('list_payments', 'read_audit_log') and '"status": "pending"' in json.dumps(last['effect']))


def system_for(step):
    return SYSTEM

def examples(day, seats=None, force=False):
    if not force and day["result"]["reward"] != 1:
        return []
    bad = day["day"]["sleeper_seat"]
    out, hist = [], {}
    for s in day["steps"]:
        if s["seat"] == bad or (seats and s["seat"] not in seats):
            continue
        h = hist.setdefault(s["seat"], [])
        msgs = prompt(system_for(s), s["seat"], h, s["view"])
        msgs.append({"role": "assistant", "content": call_json(s["tool"], s.get("args") or {})})
        out.append({"messages": msgs, "decision": is_decision(s, h)})
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
    rng = random.Random(0)
    for k in buckets:
        mixed = []
        for r in buckets[k]:
            if r['decision']:
                mixed += [r] * UP
            elif rng.random() < KEEP:
                mixed.append(r)
        rng.shuffle(mixed)
        buckets[k] = mixed
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for k, rows in buckets.items():
        (out / f"{k}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {k: {"n": len(v), "decision": sum(r["decision"] for r in v)} for k, v in buckets.items()}

if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "train/data", sys.argv[3:] or None))
