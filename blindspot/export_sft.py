"""Export reference (oracle) trajectories as chat-format SFT data for a small model.

  python -m blindspot.export_sft --seeds 100-399 --out data/sft/oracle_train.jsonl
  python -m blindspot.export_sft --seeds 0-49 --difficulty hard --out data/sft/oracle_hard.jsonl

Each line is one working day: {"seed", "difficulty", "reward", "messages": [...], "tools": [...]}.
Messages follow the common OpenAI-style tool-calling schema (system, user, assistant with
tool_calls, tool), so it loads into TRL / Unsloth / Axolotl without conversion.

Train seeds must not overlap eval seeds (eval uses 0-49 by default), so the default here
starts at 100. Only days the oracle scores 1 on are written (that is every day).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agents import STAFF_PROMPT
from .baselines import oracle
from .env import TOOL_SPECS, Env
from .eval import parse_seeds
from .verify import score


def tool_schemas() -> list[dict]:
    out = []
    for name, (desc, params) in TOOL_SPECS.items():
        props, req = {}, []
        for p, typ in params.items():
            opt = typ.endswith("?")
            t = typ.rstrip("?")
            props[p] = {"type": t} if t != "array" else {"type": "array", "items": {"type": "string"}}
            if not opt:
                req.append(p)
        out.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}})
    return out


class Recorder:
    """Wraps Env.call and records every call as an assistant tool call + tool result."""

    def __init__(self, env: Env):
        self.env = env
        self.messages: list[dict] = []
        self._orig = env.call
        env.call = self.call  # type: ignore[method-assign]

    def call(self, tool, args=None):
        out = self._orig(tool, args)
        cid = f"call_{len(self.messages) // 2 + 1:03d}"
        self.messages.append({"role": "assistant", "content": "",
                              "tool_calls": [{"id": cid, "type": "function", "function": {
                                  "name": tool, "arguments": json.dumps(args or {})}}]})
        self.messages.append({"role": "tool", "tool_call_id": cid, "name": tool,
                              "content": json.dumps(out, default=str)})
        return out


def episode(seed: int, difficulty: str = "standard") -> dict:
    plan = {} if difficulty == "standard" else {"difficulty": difficulty}
    env = Env(seed, **plan)
    rec = Recorder(env)
    oracle(env)
    s = score(env.state())
    msgs = [{"role": "system", "content": STAFF_PROMPT},
            {"role": "user", "content": "Start your working day."}] + rec.messages
    msgs.append({"role": "assistant", "content": "Day finished: every ticket has an outcome."})
    return {"seed": seed, "difficulty": difficulty, "reward": s["reward"], "messages": msgs,
            "tools": tool_schemas()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="100-399")
    ap.add_argument("--difficulty", default="standard", choices=["standard", "hard"])
    ap.add_argument("--out", default="data/sft/oracle_train.jsonl")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for seed in parse_seeds(a.seeds):
            ep = episode(seed, a.difficulty)
            if ep["reward"] == 1:
                f.write(json.dumps(ep) + "\n")
                n += 1
    print(f"wrote {n} episodes to {out}")


if __name__ == "__main__":
    main()
