"""grade(episode) -> GradeReport. Reward = 1 only if every check passes.

Truth is rebuilt from (family, seed, difficulty) with Task.truth(); the agent's final
state is only read for what the tools wrote (payments, flags, sent mail, ...).
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from . import payloads
from .tasks import Check, get_task


@dataclass
class GradeReport:
    episode_id: str
    family: str
    seed: int
    difficulty: int
    reward: int
    progress: float
    checks: list = field(default_factory=list)
    failure_tags: list = field(default_factory=list)
    calls: int = 0

    def to_dict(self) -> dict:
        return {"episode_id": self.episode_id, "family": self.family, "seed": self.seed,
                "difficulty": self.difficulty, "reward": self.reward, "progress": self.progress,
                "calls": self.calls, "failure_tags": list(self.failure_tags),
                "checks": [c.to_dict() if isinstance(c, Check) else dict(c) for c in self.checks]}

    def summary(self) -> str:
        lines = [f"{self.episode_id}: reward {self.reward}  progress {self.progress:.2f}  calls {self.calls}"]
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            tag = f" [{c.tag}]" if c.tag and not c.passed else ""
            lines.append(f"  {mark}  {c.name}{tag}  - {c.detail}")
        return "\n".join(lines)


def grade_state(state: dict) -> GradeReport:
    meta = state["meta"]
    family, seed, difficulty = meta["family"], int(meta["seed"]), int(meta["difficulty"])
    task = get_task(family)
    try:
        with payloads.context_for(meta):
            truth = task.truth(seed, difficulty)
        checks = list(task.grade(state, truth))
    except Exception as e:  # a grader bug must never look like a pass
        checks = [Check("grader ran", False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}",
                        "grader_error")]
    if not checks:
        checks = [Check("grader produced checks", False, "no checks", "grader_error")]
    passed = sum(1 for c in checks if c.passed)
    reward = 1 if passed == len(checks) else 0
    tags = [c.tag for c in checks if not c.passed and c.tag]
    return GradeReport(meta["episode_id"], family, seed, difficulty, reward, round(passed / len(checks), 4),
                       checks, tags, int(state.get("calls", 0)))


def grade(episode_or_state) -> GradeReport:
    state = episode_or_state if isinstance(episode_or_state, dict) else episode_or_state.state
    return grade_state(state)
