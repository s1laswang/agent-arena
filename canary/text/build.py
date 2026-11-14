"""Prerender world text: python -m canary.text.build --provider template|gemini[:model] --seeds judge|dev20 [--tier all]

Drives canary.env.Env with only advance_day and records every day's messages into
<out>/<tier>/<seed>.text.json (default out: data/worlds/judge for judge seeds, data/worlds/dev otherwise).
"""
from __future__ import annotations

import argparse
import json
import os

from .gemini import get_provider

TIERS = ("easy", "medium", "hard")


class Recorder:
    def __init__(self, inner):
        self.inner, self.name, self.days = inner, inner.name, {}

    def day_messages(self, facts):
        msgs = self.inner.day_messages(facts)
        self.days[str(facts.day)] = msgs
        return msgs

    def interview_answer(self, facts, employee, topic, signal):
        return self.inner.interview_answer(facts, employee, topic, signal)


def seeds_for(name: str):
    if name == "judge":
        from canary.rules import JUDGE_SEEDS
        return list(JUDGE_SEEDS)
    if name == "dev20":
        return list(range(20))
    return [int(s) for s in name.split(",")]


def build_one(tier: str, seed: int, provider_spec: str, out: str, max_steps: int = 1000) -> str:
    from canary.env import Env
    kw = {"cache_dir": os.path.join(out, "_gemini_cache")} if provider_spec != "template" else {}
    rec = Recorder(get_provider(provider_spec, **kw))
    env = Env(tier, seed, text_provider=rec)
    for _ in range(max_steps):
        if env.done:
            break
        r = env.call("advance_day", {})
        if not getattr(r, "ok", True):
            break
    path = os.path.join(out, tier, f"{seed}.text.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"tier": tier, "seed": seed, "provider": rec.name, "days": rec.days}, fh, indent=1, sort_keys=True)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="template")
    ap.add_argument("--seeds", default="judge")
    ap.add_argument("--tier", default="all")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = a.out or os.path.join("data", "worlds", "judge" if a.seeds == "judge" else "dev")
    tiers = TIERS if a.tier == "all" else (a.tier,)
    for t in tiers:
        for s in seeds_for(a.seeds):
            print(build_one(t, s, a.provider, out))


if __name__ == "__main__":
    main()
