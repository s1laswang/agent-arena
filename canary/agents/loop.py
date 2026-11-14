"""Fallback episode runner. Prefer canary.eval.run_episode (HARNESS) when it exists."""
from __future__ import annotations

from canary.types import EpisodeResult

HARD_STOP = 1000  # guard against a non-terminating env/policy pair


def _local_run_episode(env, policy, agent_name: str | None = None) -> EpisodeResult:
    policy.reset(env.tools_spec(), env.instruction())
    n = 0
    while not env.done and n < HARD_STOP:
        tool, args = policy.act(env.history)
        env.call(tool, args)
        n += 1
    return env.result(agent_name or policy.name)


def run_episode(env, policy, agent_name: str | None = None) -> EpisodeResult:
    try:
        from canary.eval import run_episode as harness_run  # type: ignore
    except Exception:
        return _local_run_episode(env, policy, agent_name)
    try:
        return harness_run(env, policy, agent_name) if agent_name else harness_run(env, policy)
    except TypeError:
        return harness_run(env, policy)
