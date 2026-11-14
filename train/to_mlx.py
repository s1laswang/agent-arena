"""Convert export_sft shards into mlx-lm's chat dataset layout (DIR/train.jsonl, DIR/valid.jsonl).

    python -m train.to_mlx --train 'GLOB' --val 'GLOB' --out DIR [--max-episodes N] [--max-chars C]

Each line is {"messages": [...], "tools": [...]} straight from train.render, so the format
cannot drift from the HF path. Episodes longer than --max-chars are cut at an assistant-turn
boundary (mlx-lm truncates by tokens otherwise, which could cut mid tool call).
Note: mlx-lm's --mask-prompt masks only the prompt before the LAST assistant turn's
predecessor, not every tool turn; the HF trainer (train.lora_sft) masks exactly.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random


def trim(rec: dict, max_chars: int) -> dict:
    msgs = rec["messages"]
    keep, size = 2, sum(len(json.dumps(m)) for m in msgs[:2])
    for i in range(2, len(msgs)):
        size += len(json.dumps(msgs[i]))
        if size > max_chars:
            break
        if msgs[i]["role"] == "assistant":
            keep = i + 1
    return {"messages": msgs[:keep], "tools": rec["tools"]}


def convert(pattern: str, path: str, max_episodes: int = 0, max_chars: int = 16000) -> int:
    recs = [json.loads(l) for f in sorted(glob.glob(pattern)) for l in open(f) if l.strip()]
    random.Random(0).shuffle(recs)
    recs = recs[:max_episodes] if max_episodes else recs
    n = 0
    with open(path, "w") as f:
        for r in recs:
            t = trim(r, max_chars)
            if len(t["messages"]) > 2:
                f.write(json.dumps(t, separators=(",", ":")) + "\n")
                n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-episodes", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=16000)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    nt = convert(a.train, os.path.join(a.out, "train.jsonl"), a.max_episodes, a.max_chars)
    nv = convert(a.val, os.path.join(a.out, "valid.jsonl"), max(a.max_episodes // 10, 0), a.max_chars)
    print(json.dumps({"train": nt, "valid": nv, "out": a.out}))


if __name__ == "__main__":
    main()
