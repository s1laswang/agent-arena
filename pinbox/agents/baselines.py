"""Baseline agents and the scripted-agent registry used by eval.

Generic baselines (every family):
  reference               the family's scripted expert
  do_nothing              makes no calls
  stop_early_25/50/75     the reference, cut after 25/50/75 % of its own call count on this episode
  stop_before_last_write  the reference, cut just before its last state-changing call
Per-family naive policies come from Task.naive_policies(); the skill ladder from Task.ladder().
"""
from __future__ import annotations

import re

from ..client import AgentStopped, EpisodeClient, LimitedClient
from ..tools import write_tool_names

GENERIC_AGENTS = ["reference", "do_nothing", "stop_early_25", "stop_early_50", "stop_early_75",
                  "stop_before_last_write"]


def do_nothing(client) -> None:
    return None


def reference_trajectory(episode) -> list:
    """Run the reference on a fresh scratch copy of this episode's world and return its trajectory."""
    scratch = episode.fresh()
    scratch.task.reference(EpisodeClient(scratch))
    return scratch.trajectory


def _cut_reference(task, limit: int):
    def agent(client) -> None:
        try:
            task.reference(LimitedClient(client, limit))
        except AgentStopped:
            pass
    return agent


def stop_early(frac: float, episode):
    """The reference cut after `frac` of its own call count for this episode."""
    n = len(reference_trajectory(episode))
    return _cut_reference(episode.task, int(n * frac))


def stop_before_last_write(episode):
    traj = reference_trajectory(episode)
    writes = write_tool_names(episode.family)
    last = max((r["i"] for r in traj if r.get("tool") in writes and r.get("ok")), default=None)
    if last is None:
        return do_nothing
    return _cut_reference(episode.task, int(last))


def make_agent(name: str, episode):
    """The callable agent(client) for `name` on this episode, or None if it does not apply to the family."""
    task = episode.task
    if name == "reference":
        return task.reference
    if name == "do_nothing":
        return do_nothing
    m = re.fullmatch(r"stop_early_(\d{1,3})", name)
    if m:
        return stop_early(int(m.group(1)) / 100, episode)
    if name == "stop_before_last_write":
        return stop_before_last_write(episode)
    naive = task.naive_policies()
    if name in naive:
        return naive[name]
    if name.startswith("ladder:"):
        for lname, fn in task.ladder():
            if lname == name[len("ladder:"):]:
                return fn
    return None


def known_agents() -> list[str]:
    from ..tasks import all_tasks
    names = list(GENERIC_AGENTS)
    for t in all_tasks():
        for n in t.naive_policies():
            if n not in names:
                names.append(n)
    return names


def run_agent(agent, episode) -> dict:
    """Run agent(client) on the episode in place. Returns {"error": str | None}. Never raises."""
    client = EpisodeClient(episode)
    try:
        agent(client)
    except AgentStopped:
        pass
    except Exception as e:  # a crashing scripted agent just stops; the grade shows the result
        episode.info["agent_error"] = f"{type(e).__name__}: {e}"
        return {"error": episode.info["agent_error"]}
    return {"error": None}
