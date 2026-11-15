from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
import random
from typing import Any

from canary.env import Env
from canary.eval import MAX_ITERS, run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import RLMole, features as rl_features, forward as rl_forward
from canary.mole.distill_rl_mole import DEFAULT_POLICY_PATH, coerce_mole_policy
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    OPS,
    MoleDoc,
    MoleStrategy,
    MoleView,
    _select_frame,
    _select_leak,
)
from canary.mole.regret_portfolio import PortfolioMolePolicy
from canary.mole.strategies import STRATEGY_SPECS, get_strategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "ADVISOR_HINT_NAMES",
    "ALLOWED_ARENA_TIERS",
    "ARENA_SEED_MAX",
    "ARENA_SEED_MIN",
    "ArenaRevealError",
    "BeTheMoleSession",
    "INVESTIGATOR_NAMES",
    "MOLE_ADVISORS",
    "PORTFOLIO_V14_WEIGHTS",
    "check_arena_seed",
    "create_session",
    "list_mole_advisors",
]

ARENA_SEED_MIN = 3000
ARENA_SEED_MAX = 9999
ALLOWED_ARENA_TIERS: tuple[str, ...] = ("medium", "hard")
INVESTIGATOR_NAMES: tuple[str, ...] = ("gemini_proxy", "solver", "hinted_heuristic")
ADVISOR_HINT_NAMES: tuple[str, ...] = (
    "frontier_synthesis_v14",
    "portfolio_v14",
    "rl_mole_frontier_v14",
)

PORTFOLIO_V14_WEIGHTS: dict[str, float] = {
    "default_v0": 0.0,
    "surgical_trap_shield": 0.8656914893617019,
    "gemini_midsize_shield": 0.13430851063829805,
    "reactive_canary_lag": 0.0,
    "non_decoy_tiebreak_framer": 0.0,
    "early_burst_midgame_pace": 0.0,
    "frontier_synthesis_v14": 0.0,
}

_BENCHMARK_CACHE: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}


class ArenaRevealError(ValueError, RuntimeError):
    pass


def _clean_text(text: str) -> str:
    return text.replace("\u2014", "-").replace("\u2013", "-")


def check_arena_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise ValueError("boolean seed is forbidden; arena requires integer seed in 3000..9999")
    if isinstance(seed, int):
        val = int(seed)
    elif isinstance(seed, str):
        raw = seed.strip()
        if not raw:
            raise ValueError("empty arena seed")
        body = raw[1:] if raw[0] in "+-" else raw
        if not body.isdigit():
            raise ValueError(f"invalid arena seed {seed!r}")
        val = int(raw)
    else:
        raise ValueError(f"invalid arena seed type {type(seed).__name__}; expected int in 3000..9999")
    if val in HELDOUT_SEEDS or val in JUDGE_SEEDS or val >= 30_000:
        raise ValueError(f"seed {val} falls in reserved/heldout/judge space; arena allows 3000..9999 only")
    if val < ARENA_SEED_MIN or val > ARENA_SEED_MAX:
        raise ValueError(f"seed {val} outside public arena dev range {ARENA_SEED_MIN}..{ARENA_SEED_MAX}")
    return val


def _load_rl_advisor(policy_path: Path = DEFAULT_POLICY_PATH) -> MoleStrategy | RLMole:
    loaded = coerce_mole_policy(policy_path)
    if isinstance(loaded, RLMole):
        return RLMole(loaded.p, greedy=loaded.greedy, name="rl_mole_frontier_v14")
    return loaded


def _build_mole_advisors() -> dict[str, Any]:
    advisors: dict[str, Any] = {
        "default_v0": DEFAULT_STRATEGY,
        "frontier_synthesis_v14": get_strategy("frontier_synthesis_v14"),
        "surgical_trap_shield": get_strategy("surgical_trap_shield"),
        "gemini_midsize_shield": get_strategy("gemini_midsize_shield"),
        "early_burst_midgame_pace": get_strategy("early_burst_midgame_pace"),
        "reactive_canary_lag": get_strategy("reactive_canary_lag"),
        "non_decoy_tiebreak_framer": get_strategy("non_decoy_tiebreak_framer"),
        "portfolio_v14": PortfolioMolePolicy(
            seed=ARENA_SEED_MIN,
            weights=PORTFOLIO_V14_WEIGHTS,
            name="portfolio_v14",
        ),
        "rl_mole_frontier_v14": _load_rl_advisor(),
    }
    return advisors


MOLE_ADVISORS: dict[str, Any] = _build_mole_advisors()


def _advisor_for_seed(name: str, seed: int) -> Any:
    if name not in MOLE_ADVISORS:
        raise ValueError(f"unknown mole advisor {name!r}; expected one of {sorted(MOLE_ADVISORS)}")
    pol = MOLE_ADVISORS[name]
    if isinstance(pol, PortfolioMolePolicy):
        return pol.for_seed(seed)
    return pol


def list_mole_advisors() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, pol in MOLE_ADVISORS.items():
        if name == "default_v0":
            rows.append(
                {
                    "name": name,
                    "kind": "dsl",
                    "target_cohort": "baseline",
                    "description": "Uniform random leak selector within window with zero extra framing.",
                    "solver_catchability": "Reference baseline mole; fully catchable by SolverPolicy.",
                }
            )
        elif name in STRATEGY_SPECS:
            spec = STRATEGY_SPECS[name]
            rows.append(
                {
                    "name": name,
                    "kind": "dsl",
                    "target_cohort": spec.target_cohort,
                    "description": _clean_text(spec.empirical_finding),
                    "solver_catchability": _clean_text(spec.solver_catchability_rationale),
                }
            )
        elif isinstance(pol, PortfolioMolePolicy):
            rows.append(
                {
                    "name": name,
                    "kind": "portfolio",
                    "target_cohort": "frontier_all",
                    "description": (
                        "Minimax attack-regret portfolio mixing surgical_trap_shield (0.866) "
                        "and gemini_midsize_shield (0.134) via public SHA-256 seed hashing."
                    ),
                    "solver_catchability": (
                        "Enforces expected SolverPolicy accuracy >= 0.90 and LogsOnly accuracy <= 0.10."
                    ),
                }
            )
        else:
            rows.append(
                {
                    "name": name,
                    "kind": "rl_mole",
                    "target_cohort": "frontier_all",
                    "description": (
                        "Distilled and CEM-refined 1-hidden-layer neural policy over public MoleView features."
                    ),
                    "solver_catchability": (
                        "Trained with explicit SolverPolicy catchability and LogsOnly anti-cheese constraints."
                    ),
                }
            )
    return rows


@dataclass(frozen=True)
class _ResolvedHumanMove:
    leak_kind: str
    leak_value: str
    leak_doc: MoleDoc | None
    frame_kind: str
    frame_value: str


class _StepBridgeMole:
    def __init__(self) -> None:
        self._mode: str = "advisor"
        self._advisor: Any = DEFAULT_STRATEGY
        self._move: _ResolvedHumanMove | None = None
        self.last_decision: dict[str, Any] | None = None

    def set_advisor(self, advisor: Any) -> None:
        self._mode = "advisor"
        self._advisor = advisor
        self._move = None

    def set_human_move(self, move: _ResolvedHumanMove) -> None:
        self._mode = "human"
        self._move = move

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        if self._mode == "advisor":
            out = self._advisor.decide(view, rng)
            leaked = out.get("leak")
            framed = out.get("frame")
        else:
            mv = self._move
            if mv is None:
                raise RuntimeError("human move was not configured before advance_day")
            if mv.leak_kind == "selector":
                leaked = _select_leak(mv.leak_value, view, rng)
            else:
                if not view.can_leak or not view.docs:
                    leaked = None
                elif any(d.doc_id == mv.leak_value for d in view.docs):
                    leaked = mv.leak_value
                else:
                    ref = mv.leak_doc
                    assert ref is not None
                    closest = min(
                        view.docs,
                        key=lambda d: (
                            abs(d.recipient_count - ref.recipient_count),
                            abs(d.age_days - ref.age_days),
                        ),
                    )
                    leaked = closest.doc_id
            if mv.frame_kind == "selector":
                framed = _select_frame(mv.frame_value, view, rng)
            else:
                framed = mv.frame_value if mv.frame_value in view.peers else None

        self.last_decision = {
            "day": int(view.day),
            "can_leak": bool(view.can_leak),
            "leaked_doc_id": leaked,
            "framed_peer_id": framed,
        }
        return {"leak": leaked, "frame": framed}


@dataclass
class _TwinWorld:
    name: str
    env: Env
    policy: Any
    bridge: _StepBridgeMole
    pending_advance: bool = False
    pending_args: dict[str, Any] = field(default_factory=dict)
    daily_p_mole: list[float] = field(default_factory=list)
    recorded_days: set[int] = field(default_factory=set)


def _make_investigator(name: str, tier: str, seed: int) -> Any:
    if name == "gemini_proxy":
        return GeminiCarbonProxy(seed=seed)
    if name == "solver":
        return SolverPolicy(tier)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed, n_days=tier_params(tier).n_days)
    raise ValueError(f"unknown arena investigator {name!r}")


def _peek_mole_view(env: Env) -> MoleView:
    saved = env._dyn.getstate()
    try:
        return env._mole_view(env.day)
    finally:
        env._dyn.setstate(saved)


def _hinted_posterior_from_history(env: Env, q: float) -> dict[str, float]:
    emps = list(env._ids)
    docs_seen: dict[str, dict[str, Any]] = {}
    feed_items: list[dict[str, Any]] = []
    for st in env.history:
        res = st.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if st.tool == "list_documents":
            for doc in data.get("documents") or []:
                if isinstance(doc, dict) and "doc_id" in doc:
                    docs_seen[str(doc["doc_id"])] = doc
        elif st.tool == "check_leak_feed":
            feed_items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    post = {e: 1.0 for e in emps}
    for it in feed_items:
        doc = docs_seen.get(str(it.get("doc_id") or ""))
        if not doc:
            continue
        if it.get("variant") and doc.get("variants"):
            groups = {str(lab): set(ms) for lab, ms in doc["variants"].items()}
            k_var = max(2, len(groups))
            shown = str(it["variant"])
            for e in post:
                if e in groups.get(shown, set()):
                    post[e] *= q
                elif any(e in grp for grp in groups.values()):
                    post[e] *= (1.0 - q) / (k_var - 1)
                else:
                    post[e] = 0.0
        else:
            rec = {str(x) for x in doc.get("recipients") or []}
            if any(post[e] > 0.0 for e in rec if e in post):
                for e in post:
                    if e not in rec:
                        post[e] = 0.0
    total = sum(post.values()) or 1.0
    return {e: val / total for e, val in post.items()}


def _investigator_p_mole(world: _TwinWorld) -> float:
    mole_id = world.env._world.mole
    if world.name == "solver":
        trace = getattr(world.policy, "trace", None) or []
        if trace and trace[-1].get("day") == world.env.day:
            post = trace[-1]["post"]
        elif getattr(world.policy, "post", None):
            post = world.policy.post
        else:
            post = world.policy.belief()
        val = float(post.get(mole_id, 0.0))
    elif world.name == "gemini_proxy":
        if not world.policy.emps:
            val = 1.0 / max(1, len(world.env._ids) - (1 if world.env.p.decoy else 0))
        else:
            pool = world.policy._suspect_pool()
            post = world.policy._posterior(pool, world.policy._subjective_q())
            val = float(post.get(mole_id, 0.0))
    else:
        q = float(getattr(world.policy, "q", world.env.p.fingerprint_accuracy))
        post = _hinted_posterior_from_history(world.env, q)
        val = float(post.get(mole_id, 0.0))
    return round(min(1.0, max(0.0, val)), 4)


def _dsl_match_summary(strat: MoleStrategy, view: MoleView) -> tuple[str, str, str]:
    for idx, (conds, then) in enumerate(strat.rules, start=1):
        if all(OPS[op](view.feature(feat), thresh) for feat, op, thresh in conds):
            cond_desc = " and ".join(f"{f} {op} {n:g}" for f, op, n in conds)
            leak_sel, frame_sel = then
            gate_note = "" if view.can_leak else " (can_leak is False today, so no leak executes)"
            return (
                leak_sel,
                frame_sel,
                f"Rule {idx} matched ({cond_desc}): leak={leak_sel}, frame={frame_sel}{gate_note}.",
            )
    leak_sel, frame_sel = strat.default
    gate_note = "" if view.can_leak else " (can_leak is False today, so no leak executes)"
    return (
        leak_sel,
        frame_sel,
        f"Default rule matched: leak={leak_sel}, frame={frame_sel}{gate_note}.",
    )


def _compute_advisor_hint(
    advisor_name: str,
    tier: str,
    seed: int,
    view: MoleView,
) -> dict[str, Any]:
    pol = _advisor_for_seed(advisor_name, seed)
    hint_rng = random.Random(f"arena_hint:{tier}:{seed}:{view.day}:{advisor_name}")
    dec = pol.decide(view, hint_rng)
    leak_choice = dec.get("leak")
    frame_choice = dec.get("frame")

    if isinstance(pol, MoleStrategy):
        leak_sel, frame_sel, rationale = _dsl_match_summary(pol, view)
    elif isinstance(pol, PortfolioMolePolicy):
        inner = pol.selected_strategy
        leak_sel, frame_sel, rule_text = _dsl_match_summary(inner, view)
        rationale = f"Seed-hashed portfolio selected {pol.selected_name}. {rule_text}"
    elif isinstance(pol, RLMole):
        x_vec = rl_features(view)
        _, pl, pf = rl_forward(pol.p, x_vec)
        li = int(pl.argmax())
        fi = int(pf.argmax())
        leak_sel = LEAK_SELECTORS[li]
        frame_sel = FRAME_SELECTORS[fi]
        gate_note = "" if view.can_leak else " (p_leak gate closed today)"
        rationale = (
            f"Distilled MLP policy top selectors: leak={leak_sel} (p={float(pl[li]):.2f}), "
            f"frame={frame_sel} (p={float(pf[fi]):.2f}){gate_note}."
        )
    else:
        leak_sel = "random_seeded"
        frame_sel = "none"
        rationale = f"Advisor {advisor_name} recommendation from public MoleView."

    return {
        "leak_choice": leak_choice,
        "frame_choice": frame_choice,
        "leak_selector": leak_sel,
        "frame_selector": frame_sel,
        "rationale": _clean_text(rationale),
    }


def _serialize_mole_view(view: MoleView, done: bool) -> dict[str, Any]:
    if done:
        return {
            "day": int(view.day),
            "can_leak": False,
            "days_since_last_leak": int(view.days_since_last_leak),
            "i_am_restricted": int(view.i_am_restricted),
            "n_restricted_colleagues": int(view.n_restricted_colleagues),
            "recent_low_recipient_docs": 0,
            "peers": list(view.peers),
            "restricted_peers": list(view.restricted_peers),
            "decoy": view.decoy,
            "docs": [],
        }
    return {
        "day": int(view.day),
        "can_leak": bool(view.can_leak),
        "days_since_last_leak": int(view.days_since_last_leak),
        "i_am_restricted": int(view.i_am_restricted),
        "n_restricted_colleagues": int(view.n_restricted_colleagues),
        "recent_low_recipient_docs": int(view.recent_low_recipient_docs),
        "peers": list(view.peers),
        "restricted_peers": list(view.restricted_peers),
        "decoy": view.decoy,
        "docs": [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "recipient_count": int(d.recipient_count),
                "age_days": int(d.age_days),
            }
            for d in view.docs
        ],
    }


def _run_benchmark_pair(tier: str, seed: int, strat_name: str) -> dict[str, Any]:
    strat = _advisor_for_seed(strat_name, seed)
    gem_res = run_episode(Env(tier, seed, mole_strategy=strat), GeminiCarbonProxy(seed=seed))
    sol_res = run_episode(Env(tier, seed, mole_strategy=strat), SolverPolicy(tier))
    gem_score = round(float(gem_res.score), 4)
    sol_score = round(float(sol_res.score), 4)
    return {
        "gemini_proxy": {
            "score": gem_score,
            "correct": bool(gem_res.correct),
            "accused": gem_res.accused,
            "final_day": int(gem_res.final_day),
        },
        "solver": {
            "score": sol_score,
            "correct": bool(sol_res.correct),
            "accused": sol_res.accused,
            "final_day": int(sol_res.final_day),
        },
        "gap": round(sol_score - gem_score, 4),
    }


class BeTheMoleSession:
    def __init__(self, tier: str = "medium", seed: int = ARENA_SEED_MIN) -> None:
        if not isinstance(tier, str) or tier not in ALLOWED_ARENA_TIERS:
            raise ValueError(f"tier must be one of {ALLOWED_ARENA_TIERS}, got {tier!r}")
        self.tier: str = tier
        self.seed: int = check_arena_seed(seed)
        self.params = tier_params(self.tier)
        self.max_days: int = int(self.params.n_days)
        self._turn_log: list[dict[str, Any]] = []
        self._pure_advisor_used: str | None = None
        self._had_manual_step: bool = False
        self._reveal_cache: dict[str, Any] | None = None

        self._worlds: dict[str, _TwinWorld] = {}
        for inv_name in INVESTIGATOR_NAMES:
            bridge = _StepBridgeMole()
            env = Env(self.tier, self.seed, mole_strategy=bridge)
            pol = _make_investigator(inv_name, self.tier, self.seed)
            pol.reset(env.tools_spec(), env.instruction())
            tw = _TwinWorld(name=inv_name, env=env, policy=pol, bridge=bridge)
            self._advance_daytime(tw)
            self._worlds[inv_name] = tw

        self._current_view: MoleView = self._refresh_view()

    @property
    def done(self) -> bool:
        return all(w.env.done for w in self._worlds.values())

    @property
    def day(self) -> int:
        active = self._primary_active_world()
        if active is not None:
            return int(active.env.day)
        return max(int(w.env.day) for w in self._worlds.values())

    @property
    def turn_log(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._turn_log]

    def _primary_active_world(self) -> _TwinWorld | None:
        for inv_name in INVESTIGATOR_NAMES:
            w = self._worlds[inv_name]
            if not w.env.done:
                return w
        return None

    def _advance_daytime(self, world: _TwinWorld) -> None:
        guard = 0
        while not world.env.done and not world.pending_advance and guard < MAX_ITERS:
            guard += 1
            tool, args = world.policy.act(list(world.env.history))
            if tool == "advance_day":
                world.pending_advance = True
                world.pending_args = dict(args) if isinstance(args, dict) else {}
                break
            world.env.call(tool, args)
        if not world.env.done and not world.pending_advance:
            world.env._end("tool_cap")
        if world.env.day not in world.recorded_days:
            world.daily_p_mole.append(_investigator_p_mole(world))
            world.recorded_days.add(world.env.day)

    def _refresh_view(self) -> MoleView:
        active = self._primary_active_world()
        target = active if active is not None else self._worlds["gemini_proxy"]
        return _peek_mole_view(target.env)

    def _validate_human_move(
        self,
        leak: str | None,
        frame: str | None,
    ) -> _ResolvedHumanMove:
        view = self._current_view
        by_id = {d.doc_id: d for d in view.docs}

        if leak is None or (isinstance(leak, str) and leak.strip().lower() in ("", "none", "null")):
            leak_kind, leak_val, leak_doc = "selector", "none", None
        elif isinstance(leak, str) and leak in LEAK_SELECTORS:
            leak_kind, leak_val, leak_doc = "selector", leak, None
        elif isinstance(leak, str) and leak in by_id:
            leak_kind, leak_val, leak_doc = "doc", leak, by_id[leak]
        else:
            raise ValueError(
                f"invalid leak choice {leak!r}; expected None, a selector in {LEAK_SELECTORS}, "
                f"or a leakable doc_id in {sorted(by_id)}"
            )

        peer_set = set(view.peers)
        if frame is None or (isinstance(frame, str) and frame.strip().lower() in ("", "none", "null")):
            frame_kind, frame_val = "selector", "none"
        elif isinstance(frame, str) and frame in FRAME_SELECTORS:
            frame_kind, frame_val = "selector", frame
        elif isinstance(frame, str) and frame in peer_set:
            frame_kind, frame_val = "peer", frame
        else:
            raise ValueError(
                f"invalid frame choice {frame!r}; expected None, a selector in {FRAME_SELECTORS}, "
                f"or a peer employee id"
            )

        return _ResolvedHumanMove(
            leak_kind=leak_kind,
            leak_value=leak_val,
            leak_doc=leak_doc,
            frame_kind=frame_kind,
            frame_value=frame_val,
        )

    def _step_night_with_bridge_setup(self, configure_fn: Any) -> None:
        primary = self._primary_active_world()
        if primary is None:
            raise ValueError("episode is already complete")
        closing_day = int(primary.env.day)

        for inv_name in INVESTIGATOR_NAMES:
            w = self._worlds[inv_name]
            if w.env.done:
                continue
            configure_fn(w)
            w.pending_advance = False
            w.env.call("advance_day", w.pending_args)

        rec = primary.bridge.last_decision or {
            "day": closing_day,
            "can_leak": bool(self._current_view.can_leak),
            "leaked_doc_id": None,
            "framed_peer_id": None,
        }
        self._turn_log.append(
            {
                "day": int(rec["day"]),
                "can_leak": bool(rec["can_leak"]),
                "leaked_doc_id": rec["leaked_doc_id"],
                "framed_peer_id": rec["framed_peer_id"],
            }
        )

        for inv_name in INVESTIGATOR_NAMES:
            w = self._worlds[inv_name]
            if not w.env.done:
                self._advance_daytime(w)

        self._current_view = self._refresh_view()
        if self.done:
            self._reveal_cache = None

    def step_turn(
        self,
        leak: str | None = None,
        frame: str | None = None,
    ) -> dict[str, Any]:
        if self.done:
            raise ValueError("cannot call step_turn after session is done")
        resolved = self._validate_human_move(leak=leak, frame=frame)
        self._had_manual_step = True
        self._pure_advisor_used = None
        self._step_night_with_bridge_setup(lambda w: w.bridge.set_human_move(resolved))
        return self.state_dict()

    def auto_play(
        self,
        strategy_name: str = "frontier_synthesis_v14",
        max_turns: int | None = None,
    ) -> dict[str, Any]:
        advisor = _advisor_for_seed(strategy_name, self.seed)
        if max_turns is not None:
            if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 0:
                raise ValueError(f"max_turns must be a non-negative int or None, got {max_turns!r}")
        if not self._turn_log and not self._had_manual_step:
            self._pure_advisor_used = strategy_name
        elif self._pure_advisor_used != strategy_name:
            self._pure_advisor_used = None

        turns_taken = 0
        while not self.done and (max_turns is None or turns_taken < max_turns):
            self._step_night_with_bridge_setup(lambda w: w.bridge.set_advisor(advisor))
            turns_taken += 1
        return self.state_dict()

    def _company_public_dict(self) -> dict[str, Any]:
        base_world = self._worlds["gemini_proxy"].env._world
        roster: list[dict[str, Any]] = []
        for emp in base_world.employees:
            item: dict[str, Any] = {
                "id": emp.id,
                "name": emp.name,
                "dept": emp.dept,
                "role": emp.role,
            }
            if emp.clearance is not None:
                item["clearance"] = int(emp.clearance)
            roster.append(item)
        peer_set = set(self._current_view.peers)
        player_ids = [emp.id for emp in base_world.employees if emp.id not in peer_set]
        player_mole_id = player_ids[0] if player_ids else base_world.mole
        return {
            "name": base_world.company,
            "employees": roster,
            "player_mole_id": player_mole_id,
            "decoy_id": self._current_view.decoy,
        }

    def _public_surface_dict(self) -> dict[str, Any]:
        known_v: dict[str, float] = {}
        surfaced_counts: dict[str, int] = {}
        inv_status: dict[str, dict[str, Any]] = {}
        for inv_name in INVESTIGATOR_NAMES:
            env = self._worlds[inv_name].env
            known_v[inv_name] = round(float(env.visible_V()), 4)
            surfaced_counts[inv_name] = sum(
                1 for item in env._feed if int(item["surfaced_day"]) <= int(env.day)
            )
            inv_status[inv_name] = {
                "done": bool(env.done),
                "status": "case_closed" if env.done else "investigating",
                "active_day": int(env.day),
                "calls_made": len(env.history),
                "restricted_count": len(env._restricted),
            }
        return {
            "known_v_by_inv": known_v,
            "surfaced_leak_count_by_inv": surfaced_counts,
            "investigator_status": inv_status,
        }

    def _advisor_hints_dict(self) -> dict[str, dict[str, Any]]:
        if self.done:
            return {}
        return {
            adv_name: _compute_advisor_hint(adv_name, self.tier, self.seed, self._current_view)
            for adv_name in ADVISOR_HINT_NAMES
        }

    def _strategy_benchmark(self, investigators_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
        key = (self.tier, self.seed)
        cached = _BENCHMARK_CACHE.get(key)
        if cached is None:
            entry: dict[str, dict[str, Any]] = {}
            for sname in ("default_v0", "frontier_synthesis_v14"):
                if self._pure_advisor_used == sname and not self._had_manual_step:
                    gem = investigators_summary["gemini_proxy"]
                    sol = investigators_summary["solver"]
                    entry[sname] = {
                        "gemini_proxy": {
                            "score": gem["score"],
                            "correct": gem["correct"],
                            "accused": gem["accused"],
                            "final_day": gem["final_day"],
                        },
                        "solver": {
                            "score": sol["score"],
                            "correct": sol["correct"],
                            "accused": sol["accused"],
                            "final_day": sol["final_day"],
                        },
                        "gap": round(float(sol["score"]) - float(gem["score"]), 4),
                    }
                else:
                    entry[sname] = _run_benchmark_pair(self.tier, self.seed, sname)
            _BENCHMARK_CACHE[key] = entry
            cached = entry

        p_gem = investigators_summary["gemini_proxy"]
        p_sol = investigators_summary["solver"]
        return {
            "default_v0": copy.deepcopy(cached["default_v0"]),
            "frontier_synthesis_v14": copy.deepcopy(cached["frontier_synthesis_v14"]),
            "player": {
                "gemini_proxy": {
                    "score": p_gem["score"],
                    "correct": p_gem["correct"],
                    "accused": p_gem["accused"],
                    "final_day": p_gem["final_day"],
                },
                "solver": {
                    "score": p_sol["score"],
                    "correct": p_sol["correct"],
                    "accused": p_sol["accused"],
                    "final_day": p_sol["final_day"],
                },
                "gap": round(float(p_sol["score"]) - float(p_gem["score"]), 4),
            },
        }

    def reveal_dict(self) -> dict[str, Any]:
        if not self.done:
            raise ArenaRevealError("reveal_dict is forbidden before session.done is True")
        if self._reveal_cache is not None:
            return copy.deepcopy(self._reveal_cache)

        investigators: dict[str, dict[str, Any]] = {}
        for inv_name in INVESTIGATOR_NAMES:
            w = self._worlds[inv_name]
            verd = w.env.verdict()
            investigators[inv_name] = {
                "score": round(float(verd["score"]), 4),
                "accused": verd["accused"],
                "correct": bool(verd["correct"]),
                "final_day": int(verd["final_day"]),
                "end_reason": verd["end_reason"],
                "true_v": round(float(verd["V"]), 4),
                "tool_calls": len(w.env.history),
                "daily_p_mole": list(w.daily_p_mole),
            }

        g_env = self._worlds["gemini_proxy"].env
        mole_id = g_env._world.mole
        leak_day_by_doc = {
            str(entry.detail["doc_id"]): int(entry.day)
            for entry in g_env.ledger()
            if entry.event == "leak" and "doc_id" in entry.detail
        }
        frames_planted = sum(1 for entry in g_env.ledger() if entry.event == "framed")

        canary_xray: list[dict[str, Any]] = []
        canary_hits = 0
        regular_hits = 0
        for feed_item in g_env._feed:
            did = str(feed_item["doc_id"])
            doc = g_env._doc_by_id[did]
            is_can = bool(doc["is_canary"])
            if is_can:
                canary_hits += 1
                variants = {str(k): list(v) for k, v in doc.get("variants", {}).items()}
                mole_var = next((k for k, members in variants.items() if mole_id in members), None)
            else:
                regular_hits += 1
                variants = None
                mole_var = None
            canary_xray.append(
                {
                    "doc_id": did,
                    "title": str(doc["title"]),
                    "published_day": int(doc["day"]),
                    "day_leaked": leak_day_by_doc.get(did, int(doc["day"])),
                    "surfaced_day": int(feed_item["surfaced_day"]),
                    "recipient_count": len(doc["recipients"]),
                    "is_canary": is_can,
                    "doc_type": "canary" if is_can else "regular",
                    "mole_variant": mole_var,
                    "shown_variant": feed_item.get("variant"),
                    "variants": variants,
                }
            )

        mole_summary = {
            "total_leaks": canary_hits + regular_hits,
            "canary_leaks_hit": canary_hits,
            "regular_leaks_hit": regular_hits,
            "frames_planted": int(frames_planted),
            "true_v_remaining": round(float(g_env.V), 4),
        }

        gem = investigators["gemini_proxy"]
        sol = investigators["solver"]
        hh = investigators["hinted_heuristic"]

        badges: list[str] = []
        if (not gem["correct"] and float(gem["score"]) <= 0.0) and sol["correct"]:
            badges.append("FOOLED_GEMINI_FAIR_TO_SOLVER")
        if not gem["correct"]:
            badges.append("OUTLASTED_GEMINI")
        if not gem["correct"] and not sol["correct"] and not hh["correct"]:
            badges.append("CLEAN_SWEEP")
        if mole_summary["total_leaks"] >= 1 and canary_hits == 0:
            badges.append("ZERO_CANARY_HITS")
        if mole_summary["true_v_remaining"] <= 0.65:
            badges.append("VALUE_DRAIN")
        if gem["correct"] and sol["correct"] and int(gem["final_day"]) <= max(4, self.max_days // 3):
            badges.append("CAUGHT_EARLY")

        self._reveal_cache = {
            "true_mole_id": mole_id,
            "decoy_id": g_env._world.decoy,
            "investigators": investigators,
            "mole_summary": mole_summary,
            "canary_xray": canary_xray,
            "badges": badges,
            "strategy_benchmark": self._strategy_benchmark(investigators),
        }
        return copy.deepcopy(self._reveal_cache)

    def state_dict(self) -> dict[str, Any]:
        is_done = self.done
        primary = self._primary_active_world()
        return {
            "mode": "be_the_mole",
            "tier": self.tier,
            "seed": self.seed,
            "day": self.day,
            "max_days": self.max_days,
            "done": is_done,
            "primary_investigator": primary.name if primary is not None else "gemini_proxy",
            "leak_selectors": list(LEAK_SELECTORS),
            "frame_selectors": list(FRAME_SELECTORS),
            "company": self._company_public_dict(),
            "mole_view": _serialize_mole_view(self._current_view, done=is_done),
            "public_surface": self._public_surface_dict(),
            "advisor_hints": self._advisor_hints_dict(),
            "turn_log": self.turn_log,
            "reveal": self.reveal_dict() if is_done else None,
        }


def create_session(tier: str = "medium", seed: int = ARENA_SEED_MIN) -> BeTheMoleSession:
    return BeTheMoleSession(tier=tier, seed=seed)
