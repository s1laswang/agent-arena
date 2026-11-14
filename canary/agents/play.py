"""Play LLMPolicy over seeds.

    python -m canary.agents.play --agent openai:gpt-5-mini --tier medium --seeds 0-9 [--out DIR] [--hint TAG] [--fake]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.agents.runlog import RunWriter, git_sha, parse_seeds, run_id, split_spec


def resolve_agent(agent: str | None) -> str:
    """Fill in the frontier default model so meta.json always records the exact model id."""
    if agent in (None, "", "openai", "openai:"):
        from canary.llm import default_openai_model
        return f"openai:{default_openai_model()}"
    return agent


def make_env(tier: str, seed: int, fake: bool):
    if fake:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
        from fake_env import FakeEnv
        return FakeEnv(tier=tier, seed=seed)
    from canary.env import Env
    return Env(tier=tier, seed=seed)


def main(argv=None, client=None) -> Path:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=None, help="openai:<model> (default openai:<canary.llm.default_openai_model()>), gemini:<model>, stub")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hint", default=None)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--smoke", action="store_true", help="tag meta.json smoke=true (small models / quick checks)")
    ap.add_argument("--fake", action="store_true", help="use tests/fake_env.FakeEnv (testing only)")
    a = ap.parse_args(argv)
    a.agent = resolve_agent(a.agent)
    seeds = parse_seeds(a.seeds)
    out = Path(a.out) if a.out else Path("data/runs") / run_id(a.agent, a.tier)
    w = RunWriter(out)
    provider, model = split_spec(a.agent)
    total = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0}
    for seed in seeds:
        env = make_env(a.tier, seed, a.fake)
        pol = LLMPolicy(a.agent, hint=a.hint, temperature=a.temperature, max_turns=a.max_turns, client=client)
        try:
            res = run_episode(env, pol, pol.name)
        except Exception as e:  # keep the run going; record the failure
            print(f"seed {seed}: error {e!r}", file=sys.stderr)
            res = env.result(pol.name)
            res.end_reason, res.meta = "error", {**res.meta, "error": repr(e)}
        res.meta = {**(res.meta or {}), "usage": pol.usage, "hint": a.hint}
        w.episode(res)
        w.transcript(seed, pol.transcript)
        for k in total:
            total[k] += pol.usage.get(k, 0)
        print(f"seed {seed}: score={res.score:.3f} correct={res.correct} accused={res.accused} day={res.final_day}")
    w.meta({"agent": a.agent, "model": model, "provider": provider, "git_sha": git_sha(), "tier": a.tier,
            "seeds": seeds, "hint": a.hint, "usage": total, "fake_env": a.fake, "smoke": bool(a.smoke or a.fake)})
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    main()
