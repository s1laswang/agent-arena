from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
import tempfile

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
logging.getLogger("canary.solver").setLevel(logging.ERROR)

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import INVESTIGATORS, RLMole, _agent
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleView,
    _select_frame,
    _select_leak,
)
from canary.solver.policy import SolverPolicy
from train.grpo_mole import SYSTEM, render_view

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "mole_dpo_stats_v2"
DPO_SEED_START = 125_000
DPO_SEED_END = 190_000
DPO_TRAIN_SEEDS = range(DPO_SEED_START, DPO_SEED_END)
VAL_SEED_MIN = 190_000
QWEN_VAL_SEED_MIN = 195_000
WS3_HELDOUT_MIN = 200_000
EVAL_MOLE_HELDOUT_MIN = 400_000

ALLOWED_TIERS = ("hard", "medium")
SUPPORTED_HORIZONS = (1, 3)
DEFAULT_HORIZON = 3
DEFAULT_MIN_MARGIN = 0.10
DEFAULT_MIN_SOLVER_SCORE = 0.25
DEFAULT_MAX_PAIRS_PER_STATE = 5
MIN_CHOSEN_SOLVER_ACC = 0.90
MIN_CATCHABLE_ACC = 0.85
MAX_STATS_BYTES = 50 * 1024

DIAGNOSTIC_BUCKETS: tuple[str, ...] = (
    "anti_silence_collapse",
    "anti_canary_trap",
    "anti_hinted_heuristic",
)

CANDIDATE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("most_recipients", "decoy"),
    ("most_recipients", "most_restricted_peer"),
    ("most_recipients", "random_peer"),
    ("newest", "decoy"),
    ("newest", "most_restricted_peer"),
    ("newest", "random_peer"),
    ("oldest", "decoy"),
    ("oldest", "random_peer"),
    ("random_seeded", "most_restricted_peer"),
    ("random_seeded", "none"),
    ("fewest_recipients", "decoy"),
    ("fewest_recipients", "none"),
    ("none", "decoy"),
    ("none", "none"),
)

_RECIPIENTS_RE = re.compile(r":\s*(\d+)\s+recipients\b")
_BASE_STRATEGY_CACHE: dict[str, object] = {}


def guard_dpo_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in rules.DEV_SEEDS or (0 <= seed < 10_000):
        raise ValueError(f"forbidden DEV_SEEDS seed: {seed}")
    if seed in rules.JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"forbidden JUDGE_SEEDS seed: {seed}")
    if seed in rules.HELDOUT_SEEDS or (800_000 <= seed < 900_000):
        raise ValueError(f"forbidden HELDOUT_SEEDS seed: {seed}")
    if seed >= EVAL_MOLE_HELDOUT_MIN:
        raise ValueError(f"forbidden eval_mole held-out seed: {seed}")
    if seed >= WS3_HELDOUT_MIN:
        raise ValueError(f"forbidden WS3_HELDOUT or post-train seed: {seed}")
    if seed >= QWEN_VAL_SEED_MIN:
        raise ValueError(f"forbidden Qwen VAL seed (>= {QWEN_VAL_SEED_MIN}): {seed}")
    if seed >= VAL_SEED_MIN:
        raise ValueError(f"forbidden VAL seed (>= {VAL_SEED_MIN}): {seed}")
    if seed not in rules.TRAIN_SEEDS or not (DPO_SEED_START <= seed < DPO_SEED_END):
        raise ValueError(
            f"seed {seed} must lie in DPO TRAIN_SEEDS [{DPO_SEED_START}, {DPO_SEED_END})"
        )
    return seed


def validate_tier(tier: str) -> str:
    if tier not in ALLOWED_TIERS:
        raise ValueError(f"tier {tier!r} must be one of {ALLOWED_TIERS}")
    return tier


def validate_horizon(horizon: int) -> int:
    if isinstance(horizon, bool) or not isinstance(horizon, int):
        raise ValueError(f"horizon must be int >= 1, got {horizon!r}")
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    return horizon


def guard_out_jsonl_path(out_path: str | Path) -> Path:
    p = Path(out_path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    repo_resolved = REPO_ROOT.resolve()
    try:
        p.relative_to(repo_resolved)
    except ValueError:
        pass
    else:
        raise ValueError(f"DPO JSONL path must reside under {tmp_root}, never inside workspace: {p}")
    try:
        p.relative_to(tmp_root)
    except ValueError as exc:
        raise ValueError(f"DPO JSONL path must reside under {tmp_root}: {p}") from exc
    return p


def wide_recipient_floor(tier: str) -> int:
    validate_tier(tier)
    n_emp = int(rules.tier_params(tier).n_employees)
    return max(8, n_emp // 4)


def narrow_canary_cap(tier: str) -> int:
    validate_tier(tier)
    n_emp = int(rules.tier_params(tier).n_employees)
    return 10 if n_emp >= 35 else 7


def max_causal_day(tier: str) -> int:
    validate_tier(tier)
    n_days = int(rules.tier_params(tier).n_days)
    return 6 if n_days >= 20 else 5


def action_to_json(action: tuple[str, str] | list[str]) -> str:
    if len(action) != 2:
        raise ValueError(f"expected (leak, frame) pair, got {action!r}")
    leak, frame = str(action[0]), str(action[1])
    if leak not in LEAK_SELECTORS or frame not in FRAME_SELECTORS:
        raise ValueError(f"invalid Mole DSL selectors: {(leak, frame)!r}")
    return json.dumps({"leak": leak, "frame": frame})


def _load_base_strategy(path: str | None):
    key = "" if not path else str(Path(path).resolve())
    cached = _BASE_STRATEGY_CACHE.get(key)
    if cached is not None:
        return cached
    if not path:
        strat = DEFAULT_STRATEGY
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("kind") == "rl_mole_v2":
            from canary.forge.rl_mole_v2 import RLMoleV2

            strat = RLMoleV2.from_json(payload)
        else:
            strat = RLMole.from_json(payload)
    _BASE_STRATEGY_CACHE[key] = strat
    return strat


def _decide_base(base, view: MoleView, rng: random.Random) -> dict:
    try:
        return base.decide(view, rng)
    except TypeError:
        return base.decide(view)


class RecorderMole:
    def __init__(self, base, views: list[MoleView]):
        self.base = base
        self.views = views

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        self.views.append(view)
        return _decide_base(self.base, view, rng)


class HorizonOverrideMole:
    def __init__(self, base, start_day: int, horizon: int, action: tuple[str, str]):
        if len(action) != 2:
            raise ValueError(f"expected (leak, frame) pair, got {action!r}")
        leak, frame = str(action[0]), str(action[1])
        if leak not in LEAK_SELECTORS or frame not in FRAME_SELECTORS:
            raise ValueError(f"invalid Mole DSL selectors: {(leak, frame)!r}")
        self.base = base
        self.start_day = int(start_day)
        self.horizon = validate_horizon(horizon)
        self.action = (leak, frame)

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        if self.start_day <= view.day < self.start_day + self.horizon:
            return {
                "leak": _select_leak(self.action[0], view, rng),
                "frame": _select_frame(self.action[1], view, rng),
            }
        return _decide_base(self.base, view, rng)


def _deterministic_selector_recipients(view: MoleView) -> dict[str, int]:
    if not view.docs:
        return {}
    docs = view.docs
    return {
        "most_recipients": int(min(docs, key=lambda d: -d.recipient_count).recipient_count),
        "newest": int(min(docs, key=lambda d: d.age_days).recipient_count),
        "oldest": int(min(docs, key=lambda d: -d.age_days).recipient_count),
        "fewest_recipients": int(min(docs, key=lambda d: d.recipient_count).recipient_count),
    }


def sample_active_states(
    n_per_tier: int,
    tiers: tuple[str, ...] | list[str] = ALLOWED_TIERS,
    seed_start: int = DPO_SEED_START,
    rng_seed: int = 0,
    base_policy: str | None = None,
) -> list[dict]:
    if n_per_tier < 0:
        raise ValueError("n_per_tier must be >= 0")
    checked_tiers = tuple(validate_tier(t) for t in tiers)
    if not checked_tiers:
        raise ValueError("tiers must be non-empty")
    guard_dpo_seed(seed_start)
    rng = random.Random(rng_seed)
    base = _load_base_strategy(base_policy)
    states: list[dict] = []
    cur_seed = int(seed_start)
    for tier in checked_tiers:
        wide_floor = wide_recipient_floor(tier)
        narrow_cap = narrow_canary_cap(tier)
        causal_day_cap = max_causal_day(tier)
        collected_for_tier = 0
        while collected_for_tier < n_per_tier:
            guard_dpo_seed(cur_seed)
            views: list[MoleView] = []
            run_episode(
                Env(tier, cur_seed, mole_strategy=RecorderMole(base, views)),
                SolverPolicy(tier),
            )
            rich = [v for v in views if len(v.docs) >= 2 and v.can_leak and not v.i_am_restricted]
            spread = [
                v
                for v in rich
                if min(d.recipient_count for d in v.docs) <= narrow_cap
                and max(d.recipient_count for d in v.docs) >= wide_floor
                and max(d.recipient_count for d in v.docs) > min(d.recipient_count for d in v.docs)
            ]
            early_spread = [v for v in spread if v.day <= causal_day_cap]
            early_rich = [v for v in rich if v.day <= causal_day_cap]
            active = (
                early_spread
                or spread
                or early_rich
                or rich
                or [v for v in views if v.docs and v.can_leak]
            )
            if active:
                chosen_view = rng.choice(active)
                min_rc = min((d.recipient_count for d in chosen_view.docs), default=0)
                max_rc = max((d.recipient_count for d in chosen_view.docs), default=0)
                states.append(
                    {
                        "seed": cur_seed,
                        "day": int(chosen_view.day),
                        "tier": tier,
                        "prompt": render_view(chosen_view),
                        "n_docs": len(chosen_view.docs),
                        "can_leak": bool(chosen_view.can_leak),
                        "i_am_restricted": int(chosen_view.i_am_restricted),
                        "n_restricted_colleagues": int(chosen_view.n_restricted_colleagues),
                        "recent_low_recipient_docs": int(chosen_view.recent_low_recipient_docs),
                        "min_recipient_count": int(min_rc),
                        "max_recipient_count": int(max_rc),
                        "selector_recipient_counts": _deterministic_selector_recipients(chosen_view),
                        "is_wide_unrestricted": bool(
                            chosen_view.can_leak
                            and not chosen_view.i_am_restricted
                            and max_rc >= wide_floor
                        ),
                        "is_narrow_canary_state": bool(
                            len(chosen_view.docs) >= 2
                            and (min_rc <= narrow_cap or chosen_view.recent_low_recipient_docs >= 1)
                            and max_rc >= wide_floor
                            and max_rc > min_rc
                        ),
                        "base_policy": base_policy,
                    }
                )
                collected_for_tier += 1
            cur_seed += 1
    return states


def score_candidate_action(task: tuple) -> dict:
    seed, day, tier, horizon, act, base_policy = task
    guard_dpo_seed(int(seed))
    validate_tier(str(tier))
    checked_horizon = validate_horizon(horizon)
    base = _load_base_strategy(base_policy)
    ov = HorizonOverrideMole(base, int(day), checked_horizon, (act[0], act[1]))
    res: dict[str, tuple[float, bool]] = {}
    for ag in ("solver",) + INVESTIGATORS:
        ep = run_episode(Env(tier, int(seed), mole_strategy=ov), _agent(ag, tier, int(seed)))
        res[ag] = (float(ep.score), bool(ep.correct))
    solver_score = float(res["solver"][0])
    solver_correct = bool(res["solver"][1])
    max_inv_score = max(res[a][0] for a in INVESTIGATORS)
    regret = solver_score - max_inv_score
    hinted_gap = solver_score - float(res["hinted_heuristic"][0])
    return {
        "action": [str(act[0]), str(act[1])],
        "regret": float(regret),
        "solver_score": solver_score,
        "solver_correct": solver_correct,
        "hinted_gap": float(hinted_gap),
        "beats_all_investigators": bool(solver_score > max_inv_score),
        "inv": {a: float(res[a][0]) for a in INVESTIGATORS},
        "inv_correct": {a: bool(res[a][1]) for a in INVESTIGATORS},
    }


def _prompt_recipient_counts(state: dict) -> list[int]:
    prompt = str(state.get("prompt") or "")
    return [int(m.group(1)) for m in _RECIPIENTS_RE.finditer(prompt)]


def _state_min_recipients(state: dict) -> int:
    if "min_recipient_count" in state and state["min_recipient_count"] is not None:
        return int(state["min_recipient_count"])
    parsed = _prompt_recipient_counts(state)
    return min(parsed) if parsed else 0


def _state_max_recipients(state: dict) -> int:
    if "max_recipient_count" in state and state["max_recipient_count"] is not None:
        return int(state["max_recipient_count"])
    parsed = _prompt_recipient_counts(state)
    if parsed:
        return max(parsed)
    if int(state.get("n_docs", 1)) >= 1:
        return wide_recipient_floor(str(state["tier"]))
    return 0


def is_wide_unrestricted_state(state: dict) -> bool:
    tier = validate_tier(str(state["tier"]))
    if not bool(state.get("can_leak", True)):
        return False
    if int(state.get("i_am_restricted", 0)) != 0:
        return False
    return _state_max_recipients(state) >= wide_recipient_floor(tier)


def is_narrow_canary_state(state: dict) -> bool:
    tier = validate_tier(str(state["tier"]))
    n_docs = int(state.get("n_docs", len(_prompt_recipient_counts(state))))
    if n_docs < 2:
        return False
    min_rc = _state_min_recipients(state)
    max_rc = _state_max_recipients(state)
    low_docs = int(state.get("recent_low_recipient_docs", 0))
    return (
        (min_rc <= narrow_canary_cap(tier) or low_docs >= 1)
        and max_rc >= wide_recipient_floor(tier)
        and max_rc > min_rc
    )


def is_wide_recipient_leak(state: dict, action: tuple[str, str] | list[str]) -> bool:
    tier = validate_tier(str(state["tier"]))
    leak_sel = str(action[0])
    wide_floor = wide_recipient_floor(tier)
    min_rc = _state_min_recipients(state)
    max_rc = _state_max_recipients(state)
    if leak_sel == "most_recipients":
        return max_rc >= wide_floor and max_rc > min_rc
    sel_map = state.get("selector_recipient_counts")
    if leak_sel in ("newest", "oldest") and isinstance(sel_map, dict) and leak_sel in sel_map:
        rc = int(sel_map[leak_sel])
        return rc >= wide_floor and rc > min_rc
    return False


def is_catchable_chosen(
    cand: dict,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
) -> bool:
    act = cand["action"]
    if str(act[0]) == "none":
        return False
    if not bool(cand["solver_correct"]):
        return False
    solver_score = float(cand["solver_score"])
    if solver_score < float(min_solver_score):
        return False
    inv = cand.get("inv")
    if isinstance(inv, dict) and inv:
        if any(solver_score <= float(inv[a]) for a in INVESTIGATORS if a in inv):
            return False
    if float(cand["regret"]) <= 0.0:
        return False
    return True


def classify_rejected_reasons(
    cand: dict,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
) -> list[str]:
    reasons: list[str] = []
    if (not bool(cand["solver_correct"])) or float(cand["solver_score"]) < float(min_solver_score):
        reasons.append("uncatchable")
    if float(cand["regret"]) < 0.0:
        reasons.append("negative_regret")
    inv = cand.get("inv")
    if isinstance(inv, dict) and "hinted_heuristic" in inv:
        if float(cand["solver_score"]) <= float(inv["hinted_heuristic"]):
            reasons.append("beaten_by_hinted_heuristic")
    if str(cand["action"][0]) == "none":
        reasons.append("silent_none")
    if str(cand["action"][0]) == "fewest_recipients":
        reasons.append("narrow_canary_selector")
    return reasons


def primary_rejected_reason(reasons: list[str]) -> str:
    for kind in (
        "uncatchable",
        "silent_none",
        "narrow_canary_selector",
        "beaten_by_hinted_heuristic",
        "negative_regret",
        "suboptimal_margin",
    ):
        if kind in reasons:
            return kind
    raise ValueError("empty rejected reasons")


def _hinted_gap_of(cand: dict) -> float | None:
    if "hinted_gap" in cand and cand["hinted_gap"] is not None:
        return float(cand["hinted_gap"])
    inv = cand.get("inv")
    if isinstance(inv, dict) and "hinted_heuristic" in inv:
        return float(cand["solver_score"]) - float(inv["hinted_heuristic"])
    return None


def classify_pair_buckets(
    state: dict,
    chosen: dict,
    rejected: dict,
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
) -> list[str]:
    if not is_catchable_chosen(chosen, min_solver_score=min_solver_score):
        return []
    c_act = (str(chosen["action"][0]), str(chosen["action"][1]))
    r_act = (str(rejected["action"][0]), str(rejected["action"][1]))
    if c_act == r_act:
        return []
    margin = float(chosen["regret"]) - float(rejected["regret"])
    if margin + 1e-9 < float(min_margin):
        return []

    buckets: list[str] = []
    if r_act[0] == "none" and is_wide_unrestricted_state(state):
        buckets.append("anti_silence_collapse")
    if (
        r_act[0] == "fewest_recipients"
        and is_narrow_canary_state(state)
        and is_wide_recipient_leak(state, c_act)
    ):
        buckets.append("anti_canary_trap")

    c_hgap = _hinted_gap_of(chosen)
    r_hgap = _hinted_gap_of(rejected)
    hinted_beats_or_ties_rej = r_hgap is not None and r_hgap <= 0.0
    hinted_advantage_drop = (
        c_hgap is not None
        and r_hgap is not None
        and (c_hgap - r_hgap) + 1e-9 >= float(min_margin)
    )
    rej_fails_inv_or_catch = (
        float(rejected["regret"]) <= 0.0
        or (not bool(rejected["solver_correct"]))
        or float(rejected["solver_score"]) < float(min_solver_score)
    )
    if (c_hgap is None or c_hgap > 0.0) and (
        hinted_beats_or_ties_rej or hinted_advantage_drop or rej_fails_inv_or_catch
    ):
        buckets.append("anti_hinted_heuristic")
    return buckets


def primary_pair_bucket(buckets: list[str]) -> str:
    for b in DIAGNOSTIC_BUCKETS:
        if b in buckets:
            return b
    raise ValueError(f"no recognized diagnostic bucket in {buckets!r}")


def _pair_record(
    state: dict,
    chosen: dict,
    rejected: dict,
    bucket: str,
    buckets: list[str],
    horizon: int,
    min_solver_score: float,
) -> dict:
    reasons = classify_rejected_reasons(rejected, min_solver_score=min_solver_score)
    if not reasons:
        reasons = ["suboptimal_margin"]
    reason = primary_rejected_reason(reasons)
    chosen_regret = float(chosen["regret"])
    rejected_regret = float(rejected["regret"])
    margin = chosen_regret - rejected_regret
    c_hgap = _hinted_gap_of(chosen)
    r_hgap = _hinted_gap_of(rejected)
    c_inv = chosen.get("inv") or {}
    r_inv = rejected.get("inv") or {}
    return {
        "seed": int(state["seed"]),
        "day": int(state["day"]),
        "tier": str(state["tier"]),
        "horizon": int(horizon),
        "bucket": bucket,
        "buckets": list(buckets),
        "system": SYSTEM,
        "prompt": str(state["prompt"]),
        "chosen": action_to_json(chosen["action"]),
        "rejected": action_to_json(rejected["action"]),
        "chosen_action": [str(chosen["action"][0]), str(chosen["action"][1])],
        "rejected_action": [str(rejected["action"][0]), str(rejected["action"][1])],
        "chosen_regret": round(chosen_regret, 6),
        "rejected_regret": round(rejected_regret, 6),
        "margin": round(margin, 6),
        "chosen_solver_score": round(float(chosen["solver_score"]), 6),
        "chosen_solver_correct": bool(chosen["solver_correct"]),
        "rejected_solver_score": round(float(rejected["solver_score"]), 6),
        "rejected_solver_correct": bool(rejected["solver_correct"]),
        "chosen_hinted_gap": round(float(c_hgap if c_hgap is not None else chosen_regret), 6),
        "rejected_hinted_gap": round(float(r_hgap if r_hgap is not None else rejected_regret), 6),
        "chosen_inv": {k: round(float(v), 6) for k, v in sorted(c_inv.items())},
        "rejected_inv": {k: round(float(v), 6) for k, v in sorted(r_inv.items())},
        "rejected_reason": reason,
        "rejected_reasons": reasons,
    }


def build_pairs_for_state(
    state: dict,
    scored: list[dict],
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    horizon: int = DEFAULT_HORIZON,
) -> list[dict]:
    guard_dpo_seed(int(state["seed"]))
    validate_tier(str(state["tier"]))
    checked_horizon = validate_horizon(horizon)

    chosen_pool = [c for c in scored if is_catchable_chosen(c, min_solver_score=min_solver_score)]
    if not chosen_pool or max_pairs_per_state <= 0:
        return []

    best_chosen = max(
        chosen_pool,
        key=lambda c: (float(c["regret"]), float(c["solver_score"]), tuple(c["action"])),
    )
    wide_chosen_pool = [c for c in chosen_pool if is_wide_recipient_leak(state, c["action"])]
    best_wide_chosen = (
        max(
            wide_chosen_pool,
            key=lambda c: (
                1 if str(c["action"][0]) == "most_recipients" else 0,
                float(c["regret"]),
                float(c["solver_score"]),
                tuple(c["action"]),
            ),
        )
        if wide_chosen_pool
        else None
    )

    dedup_scored: list[dict] = []
    seen_cand: set[tuple[str, str]] = set()
    for cand in scored:
        key = (str(cand["action"][0]), str(cand["action"][1]))
        if key not in seen_cand:
            seen_cand.add(key)
            dedup_scored.append(cand)

    candidates_by_bucket: dict[str, list[tuple[float, int, dict, dict, list[str]]]] = {
        b: [] for b in DIAGNOSTIC_BUCKETS
    }

    for cand in dedup_scored:
        r_act = (str(cand["action"][0]), str(cand["action"][1]))
        if r_act[0] == "none":
            b_list = classify_pair_buckets(
                state,
                best_chosen,
                cand,
                min_margin=min_margin,
                min_solver_score=min_solver_score,
            )
            if "anti_silence_collapse" in b_list:
                margin = float(best_chosen["regret"]) - float(cand["regret"])
                candidates_by_bucket["anti_silence_collapse"].append(
                    (margin, 1, best_chosen, cand, b_list)
                )
                continue

        if r_act[0] == "fewest_recipients" and best_wide_chosen is not None:
            b_list_trap = classify_pair_buckets(
                state,
                best_wide_chosen,
                cand,
                min_margin=min_margin,
                min_solver_score=min_solver_score,
            )
            if "anti_canary_trap" in b_list_trap:
                margin_trap = float(best_wide_chosen["regret"]) - float(cand["regret"])
                candidates_by_bucket["anti_canary_trap"].append(
                    (margin_trap, 1, best_wide_chosen, cand, b_list_trap)
                )
                continue

        b_list_hh = classify_pair_buckets(
            state,
            best_chosen,
            cand,
            min_margin=min_margin,
            min_solver_score=min_solver_score,
        )
        if "anti_hinted_heuristic" in b_list_hh:
            margin_hh = float(best_chosen["regret"]) - float(cand["regret"])
            r_hgap = _hinted_gap_of(cand)
            hard_flag = 1 if (r_hgap is not None and r_hgap <= 0.0) or float(cand["regret"]) <= 0.0 else 0
            candidates_by_bucket["anti_hinted_heuristic"].append(
                (margin_hh, hard_flag, best_chosen, cand, b_list_hh)
            )

    for b in DIAGNOSTIC_BUCKETS:
        candidates_by_bucket[b].sort(
            key=lambda item: (-item[1], -item[0], tuple(item[3]["action"]))
        )

    selected_specs: list[tuple[str, dict, dict, list[str], float]] = []
    used_pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    bucket_cursors: dict[str, int] = {b: 0 for b in DIAGNOSTIC_BUCKETS}

    while len(selected_specs) < max_pairs_per_state:
        progressed = False
        for b in DIAGNOSTIC_BUCKETS:
            if len(selected_specs) >= max_pairs_per_state:
                break
            b_cands = candidates_by_bucket[b]
            cur = bucket_cursors[b]
            while cur < len(b_cands):
                margin, _flag, ch_cand, rej_cand, b_list = b_cands[cur]
                cur += 1
                pair_key = (tuple(ch_cand["action"]), tuple(rej_cand["action"]))
                if pair_key not in used_pairs:
                    used_pairs.add(pair_key)
                    selected_specs.append((b, ch_cand, rej_cand, b_list, margin))
                    progressed = True
                    break
            bucket_cursors[b] = cur
        if not progressed:
            break

    return [
        _pair_record(
            state=state,
            chosen=ch_cand,
            rejected=rej_cand,
            bucket=b,
            buckets=b_list,
            horizon=checked_horizon,
            min_solver_score=min_solver_score,
        )
        for b, ch_cand, rej_cand, b_list, _margin in selected_specs
    ]


def _profile_from_actions(actions: list[tuple[str, str]], limit: int | None = None) -> dict[str, float]:
    if not actions:
        return {}
    counts = Counter(actions)
    total = len(actions)
    items = counts.most_common(limit)
    return {"/".join(act): round(cnt / total, 4) for act, cnt in items}


def _marginals_from_actions(actions: list[tuple[str, str]]) -> dict[str, dict[str, float]]:
    if not actions:
        return {"leak": {}, "frame": {}}
    total = len(actions)
    leak_c = Counter(a[0] for a in actions)
    frame_c = Counter(a[1] for a in actions)
    return {
        "leak": {k: round(v / total, 4) for k, v in leak_c.most_common()},
        "frame": {k: round(v / total, 4) for k, v in frame_c.most_common()},
    }


def _quantile_sorted(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def bootstrap_mean_ci(
    values: list[float],
    resamples: int = 2000,
    boot_seed: int = 20261115,
) -> list[float]:
    if not values:
        return [0.0, 0.0]
    n = len(values)
    mean_v = statistics.fmean(values)
    if n == 1:
        val = round(mean_v, 4)
        return [val, val]
    rng = random.Random(boot_seed)
    means = sorted(
        statistics.fmean(values[rng.randrange(n)] for _ in range(n))
        for _ in range(resamples)
    )
    lo = min(mean_v, _quantile_sorted(means, 0.025))
    hi = max(mean_v, _quantile_sorted(means, 0.975))
    mean_r = round(mean_v, 4)
    lo_r = min(mean_r, round(lo, 4))
    hi_r = max(mean_r, round(hi, 4))
    return [lo_r, hi_r]


def summarize_distribution(
    values: list[float],
    boot_seed: int = 20261115,
) -> dict:
    if not values:
        return {
            "n": 0,
            "mean": 0.0,
            "ci95": [0.0, 0.0],
            "std": 0.0,
            "min": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "max": 0.0,
        }
    sv = sorted(float(x) for x in values)
    mean_v = round(statistics.fmean(sv), 4)
    std_v = round(statistics.pstdev(sv), 4) if len(sv) > 1 else 0.0
    ci95 = bootstrap_mean_ci(sv, boot_seed=boot_seed)
    ci95[0] = min(ci95[0], mean_v)
    ci95[1] = max(ci95[1], mean_v)
    return {
        "n": len(sv),
        "mean": mean_v,
        "ci95": ci95,
        "std": std_v,
        "min": round(sv[0], 4),
        "p10": round(_quantile_sorted(sv, 0.10), 4),
        "p25": round(_quantile_sorted(sv, 0.25), 4),
        "median": round(_quantile_sorted(sv, 0.50), 4),
        "p75": round(_quantile_sorted(sv, 0.75), 4),
        "p90": round(_quantile_sorted(sv, 0.90), 4),
        "max": round(sv[-1], 4),
    }


def compute_state_manifest_sha256(states: list[dict]) -> str:
    canonical = [
        {
            "tier": str(st["tier"]),
            "seed": int(st["seed"]),
            "day": int(st["day"]),
            "n_docs": int(st.get("n_docs", 0)),
            "i_am_restricted": int(st.get("i_am_restricted", 0)),
            "min_recipient_count": _state_min_recipients(st),
            "max_recipient_count": _state_max_recipients(st),
            "prompt_sha16": hashlib.sha256(str(st["prompt"]).encode("utf-8")).hexdigest()[:16],
        }
        for st in states
    ]
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute_pairs_sha256(pairs: list[dict]) -> str:
    lines = "".join(json.dumps(p, sort_keys=True, separators=(",", ":")) + "\n" for p in pairs)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _select_exemplar_pairs(pairs: list[dict], per_bucket: int = 2) -> list[dict]:
    exemplars: list[dict] = []
    for b in DIAGNOSTIC_BUCKETS:
        b_pairs = [p for p in pairs if p.get("bucket") == b]
        b_pairs.sort(key=lambda p: (-float(p["margin"]), int(p["seed"]), int(p["day"])))
        picked: list[dict] = []
        seen_tiers: set[str] = set()
        for p in b_pairs:
            if len(picked) >= per_bucket:
                break
            if str(p["tier"]) not in seen_tiers:
                picked.append(p)
                seen_tiers.add(str(p["tier"]))
        for p in b_pairs:
            if len(picked) >= per_bucket:
                break
            if p not in picked:
                picked.append(p)
        for p in picked:
            exemplars.append(
                {
                    "bucket": str(p["bucket"]),
                    "buckets": list(p.get("buckets") or [p["bucket"]]),
                    "tier": str(p["tier"]),
                    "seed": int(p["seed"]),
                    "day": int(p["day"]),
                    "horizon": int(p["horizon"]),
                    "chosen_action": list(p["chosen_action"]),
                    "rejected_action": list(p["rejected_action"]),
                    "chosen_regret": float(p["chosen_regret"]),
                    "rejected_regret": float(p["rejected_regret"]),
                    "margin": float(p["margin"]),
                    "chosen_solver_score": float(p["chosen_solver_score"]),
                    "chosen_solver_correct": bool(p["chosen_solver_correct"]),
                    "rejected_solver_score": float(p["rejected_solver_score"]),
                    "rejected_solver_correct": bool(p["rejected_solver_correct"]),
                    "chosen_inv": dict(p.get("chosen_inv") or {}),
                    "rejected_inv": dict(p.get("rejected_inv") or {}),
                }
            )
    return exemplars


def summarize_dpo_dataset(
    states: list[dict],
    pairs: list[dict],
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    horizon: int = DEFAULT_HORIZON,
    seed_start: int = DPO_SEED_START,
    rng_seed: int = 0,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    base_policy: str | None = None,
) -> dict:
    checked_horizon = validate_horizon(horizon)
    for st in states:
        guard_dpo_seed(int(st["seed"]))
    for pr in pairs:
        guard_dpo_seed(int(pr["seed"]))

    seeds_seen = [int(st["seed"]) for st in states] + [int(pr["seed"]) for pr in pairs]
    seed_range = (
        [min(seeds_seen), max(seeds_seen)]
        if seeds_seen
        else [int(seed_start), int(seed_start)]
    )
    tiers_ordered = list(dict.fromkeys(str(st["tier"]) for st in states))

    n_pairs = len(pairs)
    chosen_acts = [(str(p["chosen_action"][0]), str(p["chosen_action"][1])) for p in pairs]
    rejected_acts = [(str(p["rejected_action"][0]), str(p["rejected_action"][1])) for p in pairs]
    reason_counts = Counter(str(p["rejected_reason"]) for p in pairs)

    margins = [float(p["margin"]) for p in pairs]
    chosen_regrets = [float(p["chosen_regret"]) for p in pairs]
    rejected_regrets = [float(p["rejected_regret"]) for p in pairs]
    chosen_acc_vals = [1.0 if p["chosen_solver_correct"] else 0.0 for p in pairs]

    chosen_solver_acc = round(statistics.fmean(chosen_acc_vals), 4) if pairs else 0.0
    chosen_acc_ci = bootstrap_mean_ci(chosen_acc_vals, boot_seed=20261116)
    chosen_acc_ci[0] = min(chosen_acc_ci[0], chosen_solver_acc)
    chosen_acc_ci[1] = max(chosen_acc_ci[1], chosen_solver_acc)

    bucket_counts = {b: 0 for b in DIAGNOSTIC_BUCKETS}
    bucket_multi_counts = {b: 0 for b in DIAGNOSTIC_BUCKETS}
    for p in pairs:
        b_primary = str(p.get("bucket") or "")
        if b_primary in bucket_counts:
            bucket_counts[b_primary] += 1
        for b_tag in p.get("buckets") or ([b_primary] if b_primary else []):
            if str(b_tag) in bucket_multi_counts:
                bucket_multi_counts[str(b_tag)] += 1

    diagnostic_buckets: dict[str, dict] = {}
    for idx_b, b in enumerate(DIAGNOSTIC_BUCKETS):
        b_pairs = [p for p in pairs if p.get("bucket") == b]
        b_margins = [float(p["margin"]) for p in b_pairs]
        b_ch_acts = [(str(p["chosen_action"][0]), str(p["chosen_action"][1])) for p in b_pairs]
        b_rj_acts = [(str(p["rejected_action"][0]), str(p["rejected_action"][1])) for p in b_pairs]
        b_ch_acc = (
            round(statistics.fmean(1.0 if p["chosen_solver_correct"] else 0.0 for p in b_pairs), 4)
            if b_pairs
            else 0.0
        )
        b_rj_acc = (
            round(statistics.fmean(1.0 if p["rejected_solver_correct"] else 0.0 for p in b_pairs), 4)
            if b_pairs
            else 0.0
        )
        diagnostic_buckets[b] = {
            "count": len(b_pairs),
            "multi_label_count": bucket_multi_counts[b],
            "share": round(len(b_pairs) / n_pairs, 4) if n_pairs else 0.0,
            "states_covered": len({(p["tier"], p["seed"], p["day"]) for p in b_pairs}),
            "chosen_solver_acc": b_ch_acc,
            "rejected_solver_acc": b_rj_acc,
            "mean_chosen_regret": (
                round(statistics.fmean(float(p["chosen_regret"]) for p in b_pairs), 4)
                if b_pairs
                else 0.0
            ),
            "mean_rejected_regret": (
                round(statistics.fmean(float(p["rejected_regret"]) for p in b_pairs), 4)
                if b_pairs
                else 0.0
            ),
            "mean_chosen_hinted_gap": (
                round(
                    statistics.fmean(
                        float(p.get("chosen_hinted_gap", p["chosen_regret"])) for p in b_pairs
                    ),
                    4,
                )
                if b_pairs
                else 0.0
            ),
            "mean_rejected_hinted_gap": (
                round(
                    statistics.fmean(
                        float(p.get("rejected_hinted_gap", p["rejected_regret"])) for p in b_pairs
                    ),
                    4,
                )
                if b_pairs
                else 0.0
            ),
            "margin_distribution": summarize_distribution(b_margins, boot_seed=20261120 + idx_b),
            "top_chosen_actions": _profile_from_actions(b_ch_acts, limit=5),
            "top_rejected_actions": _profile_from_actions(b_rj_acts, limit=5),
        }

    by_tier: dict[str, dict] = {}
    for idx_t, tier in enumerate(tiers_ordered):
        t_states = [s for s in states if s["tier"] == tier]
        t_pairs = [p for p in pairs if p["tier"] == tier]
        t_seeds = [int(s["seed"]) for s in t_states]
        t_margins = [float(p["margin"]) for p in t_pairs]
        t_bcounts = {b: sum(1 for p in t_pairs if p.get("bucket") == b) for b in DIAGNOSTIC_BUCKETS}
        by_tier[tier] = {
            "n_states": len(t_states),
            "wide_unrestricted_states": sum(1 for s in t_states if is_wide_unrestricted_state(s)),
            "narrow_canary_states": sum(1 for s in t_states if is_narrow_canary_state(s)),
            "states_with_pairs": len({(p["seed"], p["day"]) for p in t_pairs}),
            "n_pairs": len(t_pairs),
            "seed_range": [min(t_seeds), max(t_seeds)] if t_seeds else [],
            "chosen_solver_acc": (
                round(statistics.fmean(1.0 if p["chosen_solver_correct"] else 0.0 for p in t_pairs), 4)
                if t_pairs
                else 0.0
            ),
            "mean_chosen_regret": (
                round(statistics.fmean(float(p["chosen_regret"]) for p in t_pairs), 4)
                if t_pairs
                else 0.0
            ),
            "mean_rejected_regret": (
                round(statistics.fmean(float(p["rejected_regret"]) for p in t_pairs), 4)
                if t_pairs
                else 0.0
            ),
            "mean_margin": (
                round(statistics.fmean(t_margins), 4)
                if t_pairs
                else 0.0
            ),
            "bucket_counts": t_bcounts,
            "margin_distribution": summarize_distribution(t_margins, boot_seed=20261130 + idx_t),
        }

    n_per_tier_inferred = (
        len([s for s in states if s["tier"] == tiers_ordered[0]])
        if tiers_ordered
        else 0
    )

    beats_all_rate = (
        round(
            statistics.fmean(
                1.0
                if (
                    bool(p["chosen_solver_correct"])
                    and float(p["chosen_regret"]) > 0.0
                    and all(
                        float(p["chosen_solver_score"]) > float(v)
                        for v in (p.get("chosen_inv") or {}).values()
                    )
                )
                else 0.0
                for p in pairs
            ),
            4,
        )
        if pairs
        else 0.0
    )

    margin_dist = summarize_distribution(margins, boot_seed=20261115)
    chosen_regret_dist = summarize_distribution(chosen_regrets, boot_seed=20261117)
    rejected_regret_dist = summarize_distribution(rejected_regrets, boot_seed=20261118)

    return {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": rules.TIERS_VERSION,
        "n_states": len(states),
        "n_per_tier": n_per_tier_inferred,
        "states_with_pairs": len({(p["tier"], p["seed"], p["day"]) for p in pairs}),
        "wide_unrestricted_states": sum(1 for s in states if is_wide_unrestricted_state(s)),
        "narrow_canary_states": sum(1 for s in states if is_narrow_canary_state(s)),
        "n_pairs": n_pairs,
        "tiers": tiers_ordered,
        "horizon_days": checked_horizon,
        "supported_horizons": list(SUPPORTED_HORIZONS),
        "seed_start": int(seed_start),
        "rng_seed": int(rng_seed),
        "base_policy": base_policy,
        "min_margin": float(min_margin),
        "min_solver_score": float(min_solver_score),
        "max_pairs_per_state": int(max_pairs_per_state),
        "investigators": list(INVESTIGATORS),
        "seed_range": seed_range,
        "seed_ranges": {"train": seed_range},
        "allowed_seed_window": [DPO_SEED_START, DPO_SEED_END],
        "seed_hygiene": {
            "in_train_seeds": all(s in rules.TRAIN_SEEDS for s in seeds_seen),
            "disjoint_from_dev_seeds": all(
                s not in rules.DEV_SEEDS and not (0 <= s < 10_000) for s in seeds_seen
            ),
            "min_seed_ge_125000": (min(seeds_seen) >= DPO_SEED_START) if seeds_seen else True,
            "max_seed_lt_195000": (max(seeds_seen) < QWEN_VAL_SEED_MIN) if seeds_seen else True,
            "max_seed_lt_200000": (max(seeds_seen) < WS3_HELDOUT_MIN) if seeds_seen else True,
            "disjoint_from_heldout_seeds": all(
                s not in rules.HELDOUT_SEEDS and not (800_000 <= s < 900_000) for s in seeds_seen
            ),
            "disjoint_from_judge_seeds": all(
                s not in rules.JUDGE_SEEDS and s < 900_000 for s in seeds_seen
            ),
        },
        "mean_chosen_regret": round(statistics.fmean(chosen_regrets), 4) if pairs else 0.0,
        "mean_chosen_regret_ci95": list(chosen_regret_dist["ci95"]),
        "mean_rejected_regret": round(statistics.fmean(rejected_regrets), 4) if pairs else 0.0,
        "mean_rejected_regret_ci95": list(rejected_regret_dist["ci95"]),
        "mean_margin": round(statistics.fmean(margins), 4) if pairs else 0.0,
        "mean_margin_ci95": list(margin_dist["ci95"]),
        "min_observed_margin": round(min(margins), 4) if pairs else 0.0,
        "margin_distribution": margin_dist,
        "chosen_regret_distribution": chosen_regret_dist,
        "rejected_regret_distribution": rejected_regret_dist,
        "chosen_solver_acc": chosen_solver_acc,
        "chosen_solver_acc_ci95": chosen_acc_ci,
        "chosen_catch_floor_90": bool(chosen_solver_acc >= MIN_CHOSEN_SOLVER_ACC) if pairs else False,
        "catchable_85": bool(chosen_solver_acc >= MIN_CATCHABLE_ACC) if pairs else True,
        "solver_acc_point": chosen_solver_acc if pairs else 1.0,
        "chosen_beats_all_investigators_rate": beats_all_rate,
        "min_chosen_solver_score": (
            round(min(float(p["chosen_solver_score"]) for p in pairs), 4) if pairs else 0.0
        ),
        "mean_chosen_solver_score": (
            round(statistics.fmean(float(p["chosen_solver_score"]) for p in pairs), 4)
            if pairs
            else 0.0
        ),
        "rejected_solver_acc": (
            round(statistics.fmean(1.0 if p["rejected_solver_correct"] else 0.0 for p in pairs), 4)
            if pairs
            else 0.0
        ),
        "mean_rejected_solver_score": (
            round(statistics.fmean(float(p["rejected_solver_score"]) for p in pairs), 4)
            if pairs
            else 0.0
        ),
        "bucket_counts": bucket_counts,
        "bucket_multi_label_counts": bucket_multi_counts,
        "bucket_profile": (
            {b: round(bucket_counts[b] / n_pairs, 4) for b in DIAGNOSTIC_BUCKETS}
            if n_pairs
            else {b: 0.0 for b in DIAGNOSTIC_BUCKETS}
        ),
        "diagnostic_buckets": diagnostic_buckets,
        "chosen_action_profile": _profile_from_actions(chosen_acts),
        "rejected_action_profile": _profile_from_actions(rejected_acts),
        "chosen_selector_marginals": _marginals_from_actions(chosen_acts),
        "rejected_selector_marginals": _marginals_from_actions(rejected_acts),
        "rejected_reason_profile": (
            {k: round(v / n_pairs, 4) for k, v in reason_counts.most_common()}
            if n_pairs
            else {}
        ),
        "by_tier": by_tier,
        "reproducibility": {
            "state_manifest_sha256": compute_state_manifest_sha256(states),
            "pairs_sha256": compute_pairs_sha256(pairs),
            "exemplar_pairs": _select_exemplar_pairs(pairs, per_bucket=2),
        },
    }


def _score_states(
    states: list[dict],
    horizon: int,
    candidates: tuple[tuple[str, str], ...],
    workers: int,
    base_policy: str | None,
) -> list[dict]:
    checked_horizon = validate_horizon(horizon)
    tasks = [
        (st["seed"], st["day"], st["tier"], checked_horizon, act, base_policy)
        for st in states
        for act in candidates
    ]
    if workers > 1 and tasks:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(score_candidate_action, tasks))
    return [score_candidate_action(t) for t in tasks]


def _preferred_tmp_dir() -> str | None:
    opencode_tmp = Path("/tmp/opencode")
    return str(opencode_tmp) if opencode_tmp.is_dir() else None


def build_horizon_comparison(
    states: list[dict],
    probe_per_tier: int = 4,
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    candidates: tuple[tuple[str, str], ...] = CANDIDATE_ACTIONS,
    workers: int = 4,
    base_policy: str | None = None,
    pre_scored_by_state: dict[tuple[str, int, int], list[dict]] | None = None,
    pre_scored_horizon: int | None = None,
) -> dict:
    tiers_ordered = list(dict.fromkeys(str(st["tier"]) for st in states))
    probe_states: list[dict] = []
    for tier in tiers_ordered:
        t_states = [st for st in states if st["tier"] == tier][: max(1, int(probe_per_tier))]
        probe_states.extend(t_states)

    k = len(candidates)
    out: dict[str, dict] = {}
    for h in SUPPORTED_HORIZONS:
        probe_keys = [(str(st["tier"]), int(st["seed"]), int(st["day"])) for st in probe_states]
        if (
            pre_scored_by_state is not None
            and pre_scored_horizon == h
            and all(pk in pre_scored_by_state for pk in probe_keys)
        ):
            chunks = [pre_scored_by_state[pk] for pk in probe_keys]
        else:
            scored_flat = _score_states(probe_states, h, candidates, workers, base_policy)
            chunks = [scored_flat[idx * k : (idx + 1) * k] for idx in range(len(probe_states))]

        h_pairs: list[dict] = []
        for idx, st in enumerate(probe_states):
            h_pairs.extend(
                build_pairs_for_state(
                    state=st,
                    scored=chunks[idx],
                    min_margin=min_margin,
                    min_solver_score=min_solver_score,
                    max_pairs_per_state=max_pairs_per_state,
                    horizon=h,
                )
            )
        margins = [float(p["margin"]) for p in h_pairs]
        out[f"horizon_{h}"] = {
            "horizon_days": h,
            "n_states": len(probe_states),
            "states_with_pairs": len({(p["tier"], p["seed"], p["day"]) for p in h_pairs}),
            "n_pairs": len(h_pairs),
            "chosen_solver_acc": (
                round(statistics.fmean(1.0 if p["chosen_solver_correct"] else 0.0 for p in h_pairs), 4)
                if h_pairs
                else 0.0
            ),
            "mean_margin": round(statistics.fmean(margins), 4) if h_pairs else 0.0,
            "median_margin": (
                round(_quantile_sorted(sorted(margins), 0.50), 4) if h_pairs else 0.0
            ),
            "bucket_counts": {
                b: sum(1 for p in h_pairs if p.get("bucket") == b) for b in DIAGNOSTIC_BUCKETS
            },
            "pairs_sha256": compute_pairs_sha256(h_pairs),
        }
    return {
        "probe_per_tier": int(probe_per_tier),
        "probe_seeds": [int(s["seed"]) for s in probe_states],
        **out,
    }


def export_mole_dpo(
    out_jsonl: str | Path | None = None,
    stats_out: str | Path = "results/moletrain/mole_dpo_stats.json",
    n_per_tier: int = 30,
    tiers: tuple[str, ...] | list[str] = ALLOWED_TIERS,
    seed_start: int = DPO_SEED_START,
    horizon: int = DEFAULT_HORIZON,
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    candidates: tuple[tuple[str, str], ...] = CANDIDATE_ACTIONS,
    workers: int = 4,
    rng_seed: int = 0,
    base_policy: str | None = None,
    out_pairs: str | Path | None = None,
    include_horizon_comparison: bool = False,
    horizon_probe_per_tier: int = 4,
) -> dict:
    checked_horizon = validate_horizon(horizon)
    target_jsonl = out_jsonl if out_jsonl is not None else out_pairs
    auto_tmp: tempfile.TemporaryDirectory[str] | None = None
    if target_jsonl is None:
        auto_tmp = tempfile.TemporaryDirectory(
            prefix="mole_dpo_pairs_",
            dir=_preferred_tmp_dir(),
        )
        target_jsonl = Path(auto_tmp.name) / "pairs.jsonl"

    try:
        pairs_path = guard_out_jsonl_path(target_jsonl)

        states = sample_active_states(
            n_per_tier=n_per_tier,
            tiers=tiers,
            seed_start=seed_start,
            rng_seed=rng_seed,
            base_policy=base_policy,
        )
        scored_flat = _score_states(states, checked_horizon, candidates, workers, base_policy)

        k = len(candidates)
        all_pairs: list[dict] = []
        slice_pairs: list[dict] = []
        scored_by_state: dict[tuple[str, int, int], list[dict]] = {}
        slice_per_tier = min(1, n_per_tier)
        slice_state_keys = {
            (str(st["tier"]), int(st["seed"]), int(st["day"]))
            for tier in dict.fromkeys(str(s["tier"]) for s in states)
            for st in [s for s in states if s["tier"] == tier][:slice_per_tier]
        }

        for idx, st in enumerate(states):
            chunk = scored_flat[idx * k : (idx + 1) * k]
            st_key = (str(st["tier"]), int(st["seed"]), int(st["day"]))
            scored_by_state[st_key] = chunk
            st_pairs = build_pairs_for_state(
                state=st,
                scored=chunk,
                min_margin=min_margin,
                min_solver_score=min_solver_score,
                max_pairs_per_state=max_pairs_per_state,
                horizon=checked_horizon,
            )
            all_pairs.extend(st_pairs)
            if st_key in slice_state_keys:
                slice_pairs.extend(st_pairs)

        pairs_path.parent.mkdir(parents=True, exist_ok=True)
        pairs_path.write_text(
            "".join(json.dumps(p) + "\n" for p in all_pairs),
            encoding="utf-8",
        )

        stats = summarize_dpo_dataset(
            states=states,
            pairs=all_pairs,
            min_margin=min_margin,
            min_solver_score=min_solver_score,
            horizon=checked_horizon,
            seed_start=seed_start,
            rng_seed=rng_seed,
            max_pairs_per_state=max_pairs_per_state,
            base_policy=base_policy,
        )
        stats["n_candidates_per_state"] = len(candidates)

        if slice_per_tier > 0:
            stats["reproducibility"]["slice_probe"] = {
                "n_per_tier": slice_per_tier,
                "n_pairs": len(slice_pairs),
                "pairs_sha256": compute_pairs_sha256(slice_pairs),
                "bucket_counts": {
                    b: sum(1 for p in slice_pairs if p.get("bucket") == b)
                    for b in DIAGNOSTIC_BUCKETS
                },
            }

        if include_horizon_comparison and states:
            stats["horizon_comparison"] = build_horizon_comparison(
                states=states,
                probe_per_tier=min(int(horizon_probe_per_tier), max(1, n_per_tier)),
                min_margin=min_margin,
                min_solver_score=min_solver_score,
                max_pairs_per_state=max_pairs_per_state,
                candidates=candidates,
                workers=workers,
                base_policy=base_policy,
                pre_scored_by_state=scored_by_state,
                pre_scored_horizon=checked_horizon,
            )

        serialized = json.dumps(stats, indent=2) + "\n"
        encoded = serialized.encode("utf-8")
        if len(encoded) > MAX_STATS_BYTES:
            raise ValueError(
                f"stats JSON size {len(encoded)} bytes exceeds {MAX_STATS_BYTES} byte limit"
            )

        stats_path = Path(stats_out)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(serialized, encoding="utf-8")
        return stats
    finally:
        if auto_tmp is not None:
            auto_tmp.cleanup()


def _validate_dist_block(dist: object, label: str, expected_n: int | None = None) -> None:
    if not isinstance(dist, dict):
        raise ValueError(f"missing or invalid distribution {label}")
    n_val = int(dist.get("n", -1))
    if expected_n is not None and n_val != expected_n:
        raise ValueError(f"{label}.n={n_val} expected {expected_n}")
    ci = dist.get("ci95")
    if not isinstance(ci, list) or len(ci) != 2:
        raise ValueError(f"{label}.ci95 missing")
    mean_v = float(dist["mean"])
    lo_v, hi_v = float(ci[0]), float(ci[1])
    if not (lo_v - 1e-6 <= mean_v <= hi_v + 1e-6 and lo_v <= hi_v + 1e-6):
        raise ValueError(f"{label}.ci95 {ci} violates lo <= mean <= hi for mean={mean_v}")
    q_chain = [
        float(dist["min"]),
        float(dist["p10"]),
        float(dist["p25"]),
        float(dist["median"]),
        float(dist["p75"]),
        float(dist["p90"]),
        float(dist["max"]),
    ]
    if any(q_chain[i] > q_chain[i + 1] + 1e-6 for i in range(len(q_chain) - 1)):
        raise ValueError(f"non-monotone quantiles in {label}: {q_chain}")


def _validate_point_ci(doc: dict, base_key: str, ci_key: str) -> None:
    if ci_key not in doc:
        return
    ci = doc.get(ci_key)
    if not isinstance(ci, list) or len(ci) != 2:
        raise ValueError(f"invalid {ci_key}: {ci!r}")
    pt = float(doc[base_key])
    lo_v, hi_v = float(ci[0]), float(ci[1])
    if not (lo_v - 1e-6 <= pt <= hi_v + 1e-6 and lo_v <= hi_v + 1e-6):
        raise ValueError(f"{ci_key}={ci} violates lo <= {base_key} <= hi ({pt})")


def validate_stats_payload(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("stats JSON root must be an object")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unexpected schema_version: {doc.get('schema_version')!r}")
    horizon = validate_horizon(doc.get("horizon_days"))
    seed_start = guard_dpo_seed(int(doc["seed_start"]))
    sr = doc.get("seed_range")
    if not isinstance(sr, list) or len(sr) != 2:
        raise ValueError(f"invalid seed_range: {sr!r}")
    lo_seed = guard_dpo_seed(int(sr[0]))
    hi_seed = guard_dpo_seed(int(sr[1]))
    if lo_seed > hi_seed:
        raise ValueError(f"inverted seed_range: {sr!r}")
    if hi_seed >= WS3_HELDOUT_MIN:
        raise ValueError(f"seed_range upper bound {hi_seed} violates < {WS3_HELDOUT_MIN}")

    sh = doc.get("seed_hygiene") or {}
    for flag_key in (
        "in_train_seeds",
        "disjoint_from_dev_seeds",
        "min_seed_ge_125000",
        "max_seed_lt_195000",
        "max_seed_lt_200000",
        "disjoint_from_heldout_seeds",
        "disjoint_from_judge_seeds",
    ):
        if flag_key in sh and sh.get(flag_key) is not True:
            raise ValueError(f"seed_hygiene.{flag_key} must be True, got {sh.get(flag_key)!r}")
    for req_key in (
        "in_train_seeds",
        "min_seed_ge_125000",
        "max_seed_lt_195000",
        "disjoint_from_heldout_seeds",
        "disjoint_from_judge_seeds",
    ):
        if sh.get(req_key) is not True:
            raise ValueError(f"seed_hygiene.{req_key} must be True, got {sh.get(req_key)!r}")

    n_pairs = int(doc.get("n_pairs", 0))
    if n_pairs <= 0:
        raise ValueError("stats artifact must contain n_pairs > 0")

    chosen_acc = float(doc.get("chosen_solver_acc", 0.0))
    if chosen_acc + 1e-9 < MIN_CHOSEN_SOLVER_ACC:
        raise ValueError(
            f"chosen_solver_acc={chosen_acc:.4f} below required {MIN_CHOSEN_SOLVER_ACC}"
        )
    if doc.get("chosen_catch_floor_90") is not True:
        raise ValueError("chosen_catch_floor_90 must be True")
    if doc.get("catchable_85") is not True:
        raise ValueError("catchable_85 must be True")

    min_solver_cfg = float(doc.get("min_solver_score", DEFAULT_MIN_SOLVER_SCORE))
    min_chosen_solver = float(doc.get("min_chosen_solver_score", 0.0))
    if min_chosen_solver + 1e-6 < min_solver_cfg:
        raise ValueError(
            f"min_chosen_solver_score={min_chosen_solver} below min_solver_score={min_solver_cfg}"
        )

    _validate_dist_block(doc.get("margin_distribution"), "margin_distribution", expected_n=n_pairs)
    _validate_dist_block(
        doc.get("chosen_regret_distribution"),
        "chosen_regret_distribution",
        expected_n=n_pairs,
    )
    _validate_dist_block(
        doc.get("rejected_regret_distribution"),
        "rejected_regret_distribution",
        expected_n=n_pairs,
    )
    for base_k in (
        "chosen_solver_acc",
        "mean_margin",
        "mean_chosen_regret",
        "mean_rejected_regret",
    ):
        _validate_point_ci(doc, base_k, f"{base_k}_ci95")

    md = doc["margin_distribution"]
    min_margin_cfg = float(doc.get("min_margin", DEFAULT_MIN_MARGIN))
    if float(md["min"]) + 1e-6 < min_margin_cfg:
        raise ValueError(f"min margin {md['min']} below configured min_margin {min_margin_cfg}")

    bcounts = doc.get("bucket_counts")
    dbuckets = doc.get("diagnostic_buckets")
    if not isinstance(bcounts, dict) or not isinstance(dbuckets, dict):
        raise ValueError("missing bucket_counts or diagnostic_buckets")
    if set(bcounts.keys()) != set(DIAGNOSTIC_BUCKETS) or set(dbuckets.keys()) != set(DIAGNOSTIC_BUCKETS):
        raise ValueError("diagnostic bucket keys mismatch")
    if sum(int(bcounts[b]) for b in DIAGNOSTIC_BUCKETS) != n_pairs:
        raise ValueError("sum of primary bucket_counts does not equal n_pairs")

    n_states = int(doc.get("n_states", 0))
    for b in DIAGNOSTIC_BUCKETS:
        cnt = int(bcounts[b])
        b_info = dbuckets[b]
        if int(b_info.get("count", -1)) != cnt:
            raise ValueError(f"bucket {b} count mismatch")
        if n_states >= 10 and cnt <= 0:
            raise ValueError(f"diagnostic bucket {b} has 0 pairs on n_states={n_states}")
        if cnt > 0 and float(b_info.get("chosen_solver_acc", 0.0)) + 1e-9 < MIN_CHOSEN_SOLVER_ACC:
            raise ValueError(f"bucket {b} chosen_solver_acc below {MIN_CHOSEN_SOLVER_ACC}")
        _validate_dist_block(
            b_info.get("margin_distribution"),
            f"diagnostic_buckets.{b}.margin_distribution",
            expected_n=cnt,
        )

    by_tier = doc.get("by_tier") or {}
    if isinstance(by_tier, dict):
        for tier_k, tier_info in by_tier.items():
            if isinstance(tier_info, dict) and "margin_distribution" in tier_info:
                _validate_dist_block(
                    tier_info["margin_distribution"],
                    f"by_tier.{tier_k}.margin_distribution",
                    expected_n=int(tier_info.get("n_pairs", 0)),
                )

    rr_prof = doc.get("rejected_reason_profile")
    if not isinstance(rr_prof, dict) or not rr_prof:
        raise ValueError("missing rejected_reason_profile")
    if n_states >= 10:
        for req_reason in ("uncatchable", "silent_none", "negative_regret"):
            if float(rr_prof.get(req_reason, 0.0)) <= 0.0:
                raise ValueError(f"rejected_reason_profile missing {req_reason}")

    return {
        "horizon_days": horizon,
        "seed_start": seed_start,
        "seed_range": [lo_seed, hi_seed],
        "n_states": n_states,
        "n_pairs": n_pairs,
        "chosen_solver_acc": chosen_acc,
        "bucket_counts": {b: int(bcounts[b]) for b in DIAGNOSTIC_BUCKETS},
    }


def check_dpo_stats(
    stats_path: str | Path = "results/moletrain/mole_dpo_stats.json",
    replay: bool = True,
    recompute_all: bool = False,
    workers: int = 4,
) -> dict:
    p = Path(stats_path)
    if not p.is_file():
        raise ValueError(f"stats file not found: {p}")
    raw_bytes = p.read_bytes()
    sz = len(raw_bytes)
    if sz <= 0 or sz > MAX_STATS_BYTES:
        raise ValueError(f"stats file size {sz} bytes violates 0 < size <= {MAX_STATS_BYTES}")
    raw_txt = raw_bytes.decode("utf-8")
    if chr(0x2014) in raw_txt:
        raise ValueError(f"{p}: contains forbidden em-dash character")
    doc = json.loads(raw_txt)
    if chr(0x2014) in json.dumps(doc, ensure_ascii=False):
        raise ValueError(f"{p}: contains JSON-escaped em-dash character")

    summary = validate_stats_payload(doc)
    repro = doc.get("reproducibility")
    if not isinstance(repro, dict):
        raise ValueError("missing reproducibility block")

    replayed_exemplars = 0
    slice_verified = False

    if replay:
        tiers = tuple(str(t) for t in doc["tiers"])
        n_per_tier = int(doc["n_per_tier"])
        seed_start = int(doc["seed_start"])
        rng_seed = int(doc.get("rng_seed", 0))
        base_policy = doc.get("base_policy")
        states = sample_active_states(
            n_per_tier=n_per_tier,
            tiers=tiers,
            seed_start=seed_start,
            rng_seed=rng_seed,
            base_policy=base_policy,
        )
        got_state_sha = compute_state_manifest_sha256(states)
        exp_state_sha = str(repro.get("state_manifest_sha256") or "")
        if got_state_sha != exp_state_sha:
            raise ValueError(
                f"state_manifest_sha256 mismatch: expected {exp_state_sha}, got {got_state_sha}"
            )

        exemplars = repro.get("exemplar_pairs") or []
        if not exemplars:
            raise ValueError("reproducibility.exemplar_pairs must be non-empty")
        ex_tasks: list[tuple] = []
        for ex in exemplars:
            guard_dpo_seed(int(ex["seed"]))
            ex_tasks.append(
                (
                    int(ex["seed"]),
                    int(ex["day"]),
                    str(ex["tier"]),
                    int(ex["horizon"]),
                    tuple(ex["chosen_action"]),
                    base_policy,
                )
            )
            ex_tasks.append(
                (
                    int(ex["seed"]),
                    int(ex["day"]),
                    str(ex["tier"]),
                    int(ex["horizon"]),
                    tuple(ex["rejected_action"]),
                    base_policy,
                )
            )
        if workers > 1 and ex_tasks:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                ex_scored = list(pool.map(score_candidate_action, ex_tasks))
        else:
            ex_scored = [score_candidate_action(t) for t in ex_tasks]

        state_lookup = {(str(s["tier"]), int(s["seed"]), int(s["day"])): s for s in states}
        for idx, ex in enumerate(exemplars):
            ch_res = ex_scored[2 * idx]
            rj_res = ex_scored[2 * idx + 1]
            if abs(float(ch_res["regret"]) - float(ex["chosen_regret"])) > 1e-5:
                raise ValueError(f"exemplar {idx} chosen_regret drift")
            if abs(float(rj_res["regret"]) - float(ex["rejected_regret"])) > 1e-5:
                raise ValueError(f"exemplar {idx} rejected_regret drift")
            got_margin = float(ch_res["regret"]) - float(rj_res["regret"])
            if abs(got_margin - float(ex["margin"])) > 1e-5:
                raise ValueError(f"exemplar {idx} margin drift")
            if bool(ch_res["solver_correct"]) != bool(ex["chosen_solver_correct"]):
                raise ValueError(f"exemplar {idx} chosen_solver_correct mismatch")
            if bool(rj_res["solver_correct"]) != bool(ex["rejected_solver_correct"]):
                raise ValueError(f"exemplar {idx} rejected_solver_correct mismatch")
            st_obj = state_lookup.get((str(ex["tier"]), int(ex["seed"]), int(ex["day"])))
            if st_obj is not None:
                got_buckets = classify_pair_buckets(
                    st_obj,
                    ch_res,
                    rj_res,
                    min_margin=float(doc["min_margin"]),
                    min_solver_score=float(doc["min_solver_score"]),
                )
                if str(ex["bucket"]) not in got_buckets:
                    raise ValueError(
                        f"exemplar {idx} bucket {ex['bucket']!r} not reproduced in {got_buckets!r}"
                    )
            replayed_exemplars += 1

        if recompute_all:
            with tempfile.TemporaryDirectory(
                prefix="mole_dpo_check_",
                dir=_preferred_tmp_dir(),
            ) as tmp_dir:
                tmp_jsonl = Path(tmp_dir) / "pairs.jsonl"
                tmp_stats = Path(tmp_dir) / "stats.json"
                recomputed = export_mole_dpo(
                    out_jsonl=tmp_jsonl,
                    stats_out=tmp_stats,
                    n_per_tier=n_per_tier,
                    tiers=tiers,
                    seed_start=seed_start,
                    horizon=int(doc["horizon_days"]),
                    min_margin=float(doc["min_margin"]),
                    min_solver_score=float(doc["min_solver_score"]),
                    max_pairs_per_state=int(doc["max_pairs_per_state"]),
                    workers=workers,
                    rng_seed=rng_seed,
                    base_policy=base_policy,
                )
                if recomputed["reproducibility"]["pairs_sha256"] != repro.get("pairs_sha256"):
                    raise ValueError("full recompute pairs_sha256 mismatch")
                slice_verified = True
        elif isinstance(repro.get("slice_probe"), dict):
            sp = repro["slice_probe"]
            probe_n = int(sp["n_per_tier"])
            probe_states = [
                st
                for tier in tiers
                for st in [s for s in states if s["tier"] == tier][:probe_n]
            ]
            scored_probe = _score_states(
                probe_states,
                int(doc["horizon_days"]),
                CANDIDATE_ACTIONS,
                workers,
                base_policy,
            )
            k = len(CANDIDATE_ACTIONS)
            probe_pairs: list[dict] = []
            for idx_s, st in enumerate(probe_states):
                chunk = scored_probe[idx_s * k : (idx_s + 1) * k]
                probe_pairs.extend(
                    build_pairs_for_state(
                        state=st,
                        scored=chunk,
                        min_margin=float(doc["min_margin"]),
                        min_solver_score=float(doc["min_solver_score"]),
                        max_pairs_per_state=int(doc["max_pairs_per_state"]),
                        horizon=int(doc["horizon_days"]),
                    )
                )
            if compute_pairs_sha256(probe_pairs) != str(sp.get("pairs_sha256") or ""):
                raise ValueError("slice_probe pairs_sha256 mismatch")
            if len(probe_pairs) != int(sp.get("n_pairs", -1)):
                raise ValueError("slice_probe n_pairs mismatch")
            slice_verified = True

    return {
        "ok": True,
        "path": str(p),
        "size_bytes": sz,
        "replayed_exemplars": replayed_exemplars,
        "slice_verified": slice_verified,
        **summary,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.export_mole_dpo")
    ap.add_argument(
        "--out-jsonl",
        "--out-pairs",
        dest="out_jsonl",
        default=None,
    )
    ap.add_argument("--stats-out", default="results/moletrain/mole_dpo_stats.json")
    ap.add_argument("--n-per-tier", type=int, default=30)
    ap.add_argument("--tiers", default="hard,medium")
    ap.add_argument("--seed-start", type=int, default=DPO_SEED_START)
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--min-margin", type=float, default=DEFAULT_MIN_MARGIN)
    ap.add_argument("--min-solver-score", type=float, default=DEFAULT_MIN_SOLVER_SCORE)
    ap.add_argument("--max-pairs-per-state", type=int, default=DEFAULT_MAX_PAIRS_PER_STATE)
    ap.add_argument(
        "--workers",
        type=int,
        default=min(8, max(1, int(os.environ.get("SLURM_CPUS_PER_TASK", "4")))),
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--base-policy", default=None)
    ap.add_argument(
        "--include-horizon-comparison",
        dest="include_horizon_comparison",
        action="store_true",
        default=True,
    )
    ap.add_argument(
        "--no-horizon-comparison",
        dest="include_horizon_comparison",
        action="store_false",
    )
    ap.add_argument("--horizon-probe-per-tier", type=int, default=4)
    ap.add_argument("--delete-tmp-jsonl", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--recompute-all", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        try:
            report = check_dpo_stats(
                stats_path=args.stats_out,
                replay=True,
                recompute_all=bool(args.recompute_all),
                workers=args.workers,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(
                json.dumps({"ok": False, "path": str(args.stats_out), "error": str(exc)}),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(report, indent=2), flush=True)
        return 0

    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    if args.out_jsonl is None:
        with tempfile.TemporaryDirectory(
            prefix="mole_dpo_export_",
            dir=_preferred_tmp_dir(),
        ) as tmp_dir:
            tmp_jsonl = Path(tmp_dir) / "pairs.jsonl"
            stats = export_mole_dpo(
                out_jsonl=tmp_jsonl,
                stats_out=args.stats_out,
                n_per_tier=args.n_per_tier,
                tiers=tiers,
                seed_start=args.seed_start,
                horizon=args.horizon,
                min_margin=args.min_margin,
                min_solver_score=args.min_solver_score,
                max_pairs_per_state=args.max_pairs_per_state,
                workers=args.workers,
                rng_seed=args.seed,
                base_policy=args.base_policy,
                include_horizon_comparison=bool(args.include_horizon_comparison),
                horizon_probe_per_tier=args.horizon_probe_per_tier,
            )
    else:
        jsonl_path = guard_out_jsonl_path(args.out_jsonl)
        try:
            stats = export_mole_dpo(
                out_jsonl=jsonl_path,
                stats_out=args.stats_out,
                n_per_tier=args.n_per_tier,
                tiers=tiers,
                seed_start=args.seed_start,
                horizon=args.horizon,
                min_margin=args.min_margin,
                min_solver_score=args.min_solver_score,
                max_pairs_per_state=args.max_pairs_per_state,
                workers=args.workers,
                rng_seed=args.seed,
                base_policy=args.base_policy,
                include_horizon_comparison=bool(args.include_horizon_comparison),
                horizon_probe_per_tier=args.horizon_probe_per_tier,
            )
        finally:
            if args.delete_tmp_jsonl and jsonl_path.exists():
                jsonl_path.unlink()
    print(json.dumps(stats, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
