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
    if agent in ("gemini", "gemini:"):
        from canary.llm import default_gemini_model
        return f"gemini:{default_gemini_model()}"
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
    ap.add_argument("--context", choices=["full", "window"], default="full",
                    help="full (default): whole transcript; window: legacy last-N turns + truncated tool results")
    ap.add_argument("--reasoning-effort", default=None,
                    help="openai reasoning effort (default: medium = Codex's default for gpt-5.5)")
    ap.add_argument("--api", choices=["responses", "chat"], default=None,
                    help="openai API (default: responses for gpt-5*/o*, else chat)")
    ap.add_argument("--smoke", action="store_true", help="tag meta.json smoke=true (small models / quick checks)")
    ap.add_argument("--fake", action="store_true", help="use tests/fake_env.FakeEnv (testing only)")
    a = ap.parse_args(argv)
    a.agent = resolve_agent(a.agent)
    seeds = parse_seeds(a.seeds)
    out = Path(a.out) if a.out else Path("data/runs") / run_id(a.agent, a.tier)
    w = RunWriter(out)
    provider, model = split_spec(a.agent)
    from canary.agents.llm_policy import DEFAULT_REASONING_EFFORT
    effort = a.reasoning_effort or DEFAULT_REASONING_EFFORT
    api_used = None
    provider_settings = None
    total = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0, "cached_in": 0, "cost_usd_est": 0.0}
    for seed in seeds:
        env = make_env(a.tier, seed, a.fake)
        pol = LLMPolicy(a.agent, hint=a.hint, temperature=a.temperature, max_turns=a.max_turns, client=client,
                        context=a.context, reasoning_effort=effort, api=a.api)
        try:
            res = run_episode(env, pol, pol.name)
        except Exception as e:  # keep the run going; record the failure
            print(f"seed {seed}: error {e!r}", file=sys.stderr)
            res = env.result(pol.name)
            res.end_reason, res.meta = "error", {**res.meta, "error": repr(e)}
        api_used = getattr(pol._client, "api", api_used)
        if hasattr(pol._client, "settings"):  # gemini: thinking level / temperature / signature replay
            provider_settings = pol._client.settings()
            api_used = provider_settings.get("api", api_used)
        res.meta = {**(res.meta or {}), "usage": pol.usage, "hint": a.hint, "context": a.context,
                    "reasoning_effort": effort if provider == "openai" else None, "api": api_used}
        if provider_settings:
            res.meta["provider_settings"] = provider_settings
            res.meta["finish_reasons"] = dict(getattr(pol._client, "finish_reasons", {}) or {})
        w.episode(res)
        w.transcript(seed, pol.transcript)
        for k in total:
            total[k] += pol.usage.get(k, 0)
        print(f"seed {seed}: score={res.score:.3f} correct={res.correct} accused={res.accused} day={res.final_day}")
    w.meta({"agent": a.agent, "model": model, "provider": provider, "git_sha": git_sha(), "tier": a.tier,
            "seeds": seeds, "hint": a.hint, "usage": total, "fake_env": a.fake, "smoke": bool(a.smoke or a.fake), "context": a.context,
            "reasoning_effort": effort if provider == "openai" else None,
            "reasoning_effort_source": (None if provider != "openai" else "default: Codex 0.167 models catalog default_reasoning_level for gpt-5.5" if not a.reasoning_effort else "cli"),
            "api": api_used or a.api, "max_turns": a.max_turns if a.context == "window" else None,
            "provider_settings": provider_settings})
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    main()
