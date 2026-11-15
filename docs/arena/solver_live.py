from __future__ import annotations

import copy
import json
import math
import os
from typing import Any

from canary.env import Env
from canary.solver.policy import SolverPolicy

ALLOWED_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
DUEL_SEED_MIN = 0
DUEL_SEED_MAX = 29
PUBLIC_DEV_SEED_MIN = 3000
PUBLIC_DEV_SEED_MAX = 9999
MAX_SOLVER_ITERS = 1000

PRE_END_KEYS: tuple[str, ...] = (
    "seed",
    "tier",
    "day",
    "visible_V",
    "canaries_planted",
    "interviews_done",
    "restricted_count",
    "tool_calls_so_far",
    "top_posterior_prob",
    "entropy_bits",
    "status",
    "sealed_day",
)

POST_END_KEYS: tuple[str, ...] = PRE_END_KEYS + (
    "accused",
    "correct",
    "final_day",
    "tool_calls",
    "score",
    "end_reason",
    "daily_trace",
)


def validate_tier_and_seed(tier: Any, seed: Any) -> tuple[str, int]:
    if not isinstance(tier, str) or tier not in ALLOWED_TIERS:
        raise ValueError(f"tier must be one of {ALLOWED_TIERS}, got {tier!r}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an int in 0..29 or 3000..9999, got {seed!r}")
    in_duel = DUEL_SEED_MIN <= seed <= DUEL_SEED_MAX
    in_public_dev = PUBLIC_DEV_SEED_MIN <= seed <= PUBLIC_DEV_SEED_MAX
    if not (in_duel or in_public_dev):
        raise ValueError(
            f"seed {seed} refused: allowed ranges are 0..29 (duel) or 3000..9999 (public dev)"
        )
    return tier, int(seed)


def validate_human_day(human_day: Any) -> int:
    if isinstance(human_day, bool) or not isinstance(human_day, int):
        raise ValueError(f"human_day must be an int, got {human_day!r}")
    return int(human_day)


def _posterior_stats(post: dict[str, float]) -> tuple[float, float, str | None]:
    if not post:
        return 0.0, 0.0, None
    probs = [float(v) for v in post.values() if v > 0.0]
    top_prob = float(max(probs)) if probs else 0.0
    if len(probs) <= 1:
        entropy = 0.0
    else:
        raw_ent = -sum(p * math.log2(p) for p in probs)
        entropy = 0.0 if raw_ent <= 0.0 else float(raw_ent)
    top_emp = max(sorted(post.keys()), key=lambda emp_id: post[emp_id])
    return top_prob, entropy, top_emp


class LiveSolverSession:
    def __init__(self, tier: str, seed: int) -> None:
        tier_val, seed_val = validate_tier_and_seed(tier, seed)
        self.tier: str = tier_val
        self.seed: int = seed_val

        os.environ.setdefault("CANARY_ALLOW_DEV", "1")
        env = Env(tier_val, seed_val)
        pol = SolverPolicy(tier_val)
        pol.reset(env.tools_spec(), env.instruction())

        day_visible_v: dict[int, float] = {}
        error: str | None = None
        for _ in range(MAX_SOLVER_ITERS):
            if env.done:
                break
            cur_day = int(env.day)
            try:
                tool, args = pol.act(list(env.history))
            except Exception as exc:
                error = f"policy error: {type(exc).__name__}: {exc}"
                break
            if tool == "advance_day":
                day_visible_v[cur_day] = float(env.visible_V())
            env.call(tool, args)
            if env.done and int(env.day) not in day_visible_v:
                day_visible_v[int(env.day)] = float(env.visible_V())

        res = env.result(getattr(pol, "name", type(pol).__name__))
        if not env.done:
            res.end_reason = "error"
            res.meta["error"] = error or f"no episode end after {MAX_SOLVER_ITERS} iterations"
            if error:
                res.meta["valid"] = False

        self.accused: str | None = res.accused
        self.correct: bool = bool(res.correct)
        self.final_day: int = int(res.final_day)
        self.tool_calls: int = len(res.steps)
        self.score: float = float(res.score)
        self.end_reason: str = str(res.end_reason)

        n_emp = int(env.p.n_employees)
        uniform_post = {f"e{i:02d}": 1.0 / n_emp for i in range(n_emp)}
        trace_by_day: dict[int, dict[str, float]] = {}
        for entry in pol.trace:
            if isinstance(entry, dict) and "day" in entry and isinstance(entry.get("post"), dict):
                trace_by_day[int(entry["day"])] = dict(entry["post"])

        steps_by_day: dict[int, list[Any]] = {d: [] for d in range(1, self.final_day + 1)}
        for st in res.steps:
            d_idx = min(max(1, int(st.day)), self.final_day)
            steps_by_day[d_idx].append(st)

        self._snapshots: dict[int, dict[str, Any]] = {}
        self._daily_trace: list[dict[str, Any]] = []

        canaries_planted = 0
        interviews_done = 0
        restricted_active: set[str] = set()
        tool_calls_so_far = 0
        last_vis_v = 1.0
        last_post: dict[str, float] = dict(uniform_post)

        for d in range(1, self.final_day + 1):
            day_steps = steps_by_day.get(d, [])
            day_actions: list[str] = []
            status_vis_v: float | None = None
            for st in day_steps:
                tool_calls_so_far += 1
                day_actions.append(str(st.tool))
                st_res = st.result if isinstance(st.result, dict) else {}
                ok = bool(st_res.get("ok"))
                data = st_res.get("data") if isinstance(st_res.get("data"), dict) else {}
                st_args = st.args if isinstance(st.args, dict) else {}
                if ok:
                    if st.tool == "plant_canary":
                        canaries_planted += 1
                    elif st.tool == "interview":
                        interviews_done += 1
                    elif st.tool == "restrict_access":
                        emp = st_args.get("employee")
                        if isinstance(emp, str):
                            restricted_active.add(emp)
                    elif st.tool == "unrestrict_access":
                        emp = st_args.get("employee")
                        if isinstance(emp, str):
                            restricted_active.discard(emp)
                    elif st.tool == "status" and "V" in data:
                        status_vis_v = float(data["V"])

            if d in day_visible_v:
                vis_v = day_visible_v[d]
            elif status_vis_v is not None:
                vis_v = status_vis_v
            else:
                vis_v = last_vis_v
            last_vis_v = vis_v

            day_post = trace_by_day.get(d, last_post)
            last_post = day_post
            top_prob, ent_bits, top_emp = _posterior_stats(day_post)

            snap = {
                "day": d,
                "visible_V": float(vis_v),
                "canaries_planted": int(canaries_planted),
                "interviews_done": int(interviews_done),
                "restricted_count": int(len(restricted_active)),
                "tool_calls_so_far": int(tool_calls_so_far),
                "top_posterior_prob": float(top_prob),
                "entropy_bits": float(ent_bits),
            }
            self._snapshots[d] = snap
            self._daily_trace.append(
                {
                    "day": d,
                    "visible_V": float(vis_v),
                    "canaries_planted": int(canaries_planted),
                    "interviews_done": int(interviews_done),
                    "restricted_count": int(len(restricted_active)),
                    "tool_calls_so_far": int(tool_calls_so_far),
                    "top_posterior_prob": float(top_prob),
                    "entropy_bits": float(ent_bits),
                    "top_suspect": top_emp,
                    "actions": day_actions,
                }
            )

    def get_solver_day_state(self, human_day: int, human_done: bool = False) -> dict[str, Any]:
        h_day = validate_human_day(human_day)
        unlocked = human_done is True
        clamped_day = min(max(1, h_day), self.final_day)
        snap = self._snapshots[clamped_day]

        if not unlocked:
            is_sealed = h_day >= self.final_day
            return {
                "seed": self.seed,
                "tier": self.tier,
                "day": int(snap["day"]),
                "visible_V": float(snap["visible_V"]),
                "canaries_planted": int(snap["canaries_planted"]),
                "interviews_done": int(snap["interviews_done"]),
                "restricted_count": int(snap["restricted_count"]),
                "tool_calls_so_far": int(snap["tool_calls_so_far"]),
                "top_posterior_prob": float(snap["top_posterior_prob"]),
                "entropy_bits": float(snap["entropy_bits"]),
                "status": "sealed_accusation" if is_sealed else "hunting",
                "sealed_day": int(self.final_day) if is_sealed else None,
            }

        final_snap = self._snapshots[self.final_day]
        return {
            "seed": self.seed,
            "tier": self.tier,
            "day": int(self.final_day),
            "visible_V": float(final_snap["visible_V"]),
            "canaries_planted": int(final_snap["canaries_planted"]),
            "interviews_done": int(final_snap["interviews_done"]),
            "restricted_count": int(final_snap["restricted_count"]),
            "tool_calls_so_far": int(self.tool_calls),
            "top_posterior_prob": float(final_snap["top_posterior_prob"]),
            "entropy_bits": float(final_snap["entropy_bits"]),
            "status": "revealed",
            "sealed_day": int(self.final_day) if self.accused is not None else None,
            "accused": self.accused,
            "correct": bool(self.correct),
            "final_day": int(self.final_day),
            "tool_calls": int(self.tool_calls),
            "score": float(self.score),
            "end_reason": self.end_reason,
            "daily_trace": copy.deepcopy(self._daily_trace),
        }

    def get_solver_day_state_json(self, human_day: int, human_done: bool = False) -> str:
        return json.dumps(self.get_solver_day_state(human_day, human_done), sort_keys=True)


_SESSION_CACHE: dict[tuple[str, int], LiveSolverSession] = {}
_ACTIVE_SESSION: LiveSolverSession | None = None


def start_solver_session(tier: str, seed: int) -> LiveSolverSession:
    global _ACTIVE_SESSION
    key = validate_tier_and_seed(tier, seed)
    session = _SESSION_CACHE.get(key)
    if session is None:
        session = LiveSolverSession(key[0], key[1])
        _SESSION_CACHE[key] = session
    _ACTIVE_SESSION = session
    return session


def get_solver_day_state(
    human_day: int,
    human_done: bool = False,
    tier: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    if tier is not None or seed is not None:
        if tier is None or seed is None:
            raise ValueError("both tier and seed must be provided when selecting a session")
        session = start_solver_session(tier, seed)
    elif _ACTIVE_SESSION is not None:
        session = _ACTIVE_SESSION
    else:
        raise RuntimeError("no active solver session; call start_solver_session(tier, seed) first")
    return session.get_solver_day_state(human_day, human_done)


def get_solver_day_state_json(
    human_day: int,
    human_done: bool = False,
    tier: str | None = None,
    seed: int | None = None,
) -> str:
    return json.dumps(
        get_solver_day_state(human_day, human_done, tier=tier, seed=seed),
        sort_keys=True,
    )
