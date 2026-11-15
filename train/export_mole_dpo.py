from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import random
import statistics
import time

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

DPO_SEED_START = 130_000
DPO_SEED_END = 145_000
DPO_TRAIN_SEEDS = range(DPO_SEED_START, DPO_SEED_END)
VAL_SEED_MIN = 190_000
WS3_HELDOUT_MIN = 200_000

ALLOWED_TIERS = ("hard", "medium")
DEFAULT_HORIZON = 3
DEFAULT_MIN_MARGIN = 0.10
DEFAULT_MIN_SOLVER_SCORE = 0.25
DEFAULT_MAX_PAIRS_PER_STATE = 4

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
    ("none", "none"),
)


def guard_dpo_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in rules.JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"forbidden JUDGE_SEEDS seed: {seed}")
    if seed in rules.HELDOUT_SEEDS or seed >= 800_000:
        raise ValueError(f"forbidden HELDOUT_SEEDS seed: {seed}")
    if seed >= WS3_HELDOUT_MIN:
        raise ValueError(f"forbidden WS3_HELDOUT or post-train seed: {seed}")
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


def action_to_json(action: tuple[str, str] | list[str]) -> str:
    if len(action) != 2:
        raise ValueError(f"expected (leak, frame) pair, got {action!r}")
    leak, frame = str(action[0]), str(action[1])
    if leak not in LEAK_SELECTORS or frame not in FRAME_SELECTORS:
        raise ValueError(f"invalid Mole DSL selectors: {(leak, frame)!r}")
    return json.dumps({"leak": leak, "frame": frame})


def _load_base_strategy(path: str | None):
    if not path:
        return DEFAULT_STRATEGY
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("kind") == "rl_mole_v2":
        from canary.forge.rl_mole_v2 import RLMoleV2

        return RLMoleV2.from_json(payload)
    return RLMole.from_json(payload)


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
        self.base = base
        self.start_day = int(start_day)
        self.horizon = int(horizon)
        self.action = (str(action[0]), str(action[1]))

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        if self.start_day <= view.day < self.start_day + self.horizon:
            return {
                "leak": _select_leak(self.action[0], view, rng),
                "frame": _select_frame(self.action[1], view, rng),
            }
        return _decide_base(self.base, view, rng)


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
        collected_for_tier = 0
        while collected_for_tier < n_per_tier:
            guard_dpo_seed(cur_seed)
            views: list[MoleView] = []
            run_episode(
                Env(tier, cur_seed, mole_strategy=RecorderMole(base, views)),
                SolverPolicy(tier),
            )
            rich = [v for v in views if len(v.docs) >= 2 and v.can_leak and not v.i_am_restricted]
            active = rich if rich else [v for v in views if v.docs and v.can_leak]
            if active:
                chosen_view = rng.choice(active)
                states.append(
                    {
                        "seed": cur_seed,
                        "day": int(chosen_view.day),
                        "tier": tier,
                        "prompt": render_view(chosen_view),
                        "n_docs": len(chosen_view.docs),
                        "i_am_restricted": int(chosen_view.i_am_restricted),
                        "base_policy": base_policy,
                    }
                )
                collected_for_tier += 1
            cur_seed += 1
    return states


def score_candidate_action(task: tuple) -> dict:
    seed, day, tier, horizon, act, base_policy = task
    guard_dpo_seed(seed)
    validate_tier(tier)
    if int(horizon) < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    base = _load_base_strategy(base_policy)
    ov = HorizonOverrideMole(base, int(day), int(horizon), (act[0], act[1]))
    res: dict[str, tuple[float, bool]] = {}
    for ag in ("solver",) + INVESTIGATORS:
        ep = run_episode(Env(tier, seed, mole_strategy=ov), _agent(ag, tier, seed))
        res[ag] = (float(ep.score), bool(ep.correct))
    regret = res["solver"][0] - max(res[a][0] for a in INVESTIGATORS)
    return {
        "action": [str(act[0]), str(act[1])],
        "regret": float(regret),
        "solver_score": float(res["solver"][0]),
        "solver_correct": bool(res["solver"][1]),
        "inv": {a: float(res[a][0]) for a in INVESTIGATORS},
        "inv_correct": {a: bool(res[a][1]) for a in INVESTIGATORS},
    }


def is_catchable_chosen(
    cand: dict,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
) -> bool:
    act = cand["action"]
    if act[0] == "none":
        return False
    if not bool(cand["solver_correct"]):
        return False
    if float(cand["solver_score"]) < float(min_solver_score):
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
    if cand["action"][0] == "none":
        reasons.append("silent_none")
    return reasons


def primary_rejected_reason(reasons: list[str]) -> str:
    for kind in ("uncatchable", "silent_none", "negative_regret"):
        if kind in reasons:
            return kind
    raise ValueError("empty rejected reasons")


def build_pairs_for_state(
    state: dict,
    scored: list[dict],
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    horizon: int = DEFAULT_HORIZON,
) -> list[dict]:
    seed = guard_dpo_seed(int(state["seed"]))
    tier = validate_tier(str(state["tier"]))
    day = int(state["day"])

    chosen_pool = [c for c in scored if is_catchable_chosen(c, min_solver_score=min_solver_score)]
    if not chosen_pool or max_pairs_per_state <= 0:
        return []

    best_chosen = max(
        chosen_pool,
        key=lambda c: (float(c["regret"]), float(c["solver_score"]), tuple(c["action"])),
    )
    chosen_act = tuple(best_chosen["action"])
    chosen_regret = float(best_chosen["regret"])

    qualifying: list[tuple[float, str, list[str], dict]] = []
    seen_rejected: set[tuple[str, str]] = set()
    for cand in scored:
        r_act = (str(cand["action"][0]), str(cand["action"][1]))
        if r_act == chosen_act or r_act in seen_rejected:
            continue
        reasons = classify_rejected_reasons(cand, min_solver_score=min_solver_score)
        if not reasons:
            continue
        margin = chosen_regret - float(cand["regret"])
        if margin + 1e-9 < float(min_margin):
            continue
        seen_rejected.add(r_act)
        qualifying.append((margin, primary_rejected_reason(reasons), reasons, cand))

    if not qualifying:
        return []

    qualifying.sort(key=lambda item: (-item[0], tuple(item[3]["action"])))

    selected: list[tuple[float, str, list[str], dict]] = []
    used_actions: set[tuple[str, str]] = set()
    for target_reason in ("uncatchable", "silent_none", "negative_regret"):
        if len(selected) >= max_pairs_per_state:
            break
        for item in qualifying:
            r_act = tuple(item[3]["action"])
            if item[1] == target_reason and r_act not in used_actions:
                selected.append(item)
                used_actions.add(r_act)
                break

    for item in qualifying:
        if len(selected) >= max_pairs_per_state:
            break
        r_act = tuple(item[3]["action"])
        if r_act not in used_actions:
            selected.append(item)
            used_actions.add(r_act)

    chosen_json = action_to_json(best_chosen["action"])
    pairs: list[dict] = []
    for margin, reason, reasons, rej in selected:
        pairs.append(
            {
                "seed": seed,
                "day": day,
                "tier": tier,
                "horizon": int(horizon),
                "system": SYSTEM,
                "prompt": str(state["prompt"]),
                "chosen": chosen_json,
                "rejected": action_to_json(rej["action"]),
                "chosen_action": [str(best_chosen["action"][0]), str(best_chosen["action"][1])],
                "rejected_action": [str(rej["action"][0]), str(rej["action"][1])],
                "chosen_regret": round(chosen_regret, 6),
                "rejected_regret": round(float(rej["regret"]), 6),
                "margin": round(float(margin), 6),
                "chosen_solver_score": round(float(best_chosen["solver_score"]), 6),
                "chosen_solver_correct": bool(best_chosen["solver_correct"]),
                "rejected_solver_score": round(float(rej["solver_score"]), 6),
                "rejected_solver_correct": bool(rej["solver_correct"]),
                "rejected_reason": reason,
                "rejected_reasons": reasons,
            }
        )
    return pairs


def _profile_from_actions(actions: list[tuple[str, str]]) -> dict[str, float]:
    if not actions:
        return {}
    counts = Counter(actions)
    total = len(actions)
    return {"/".join(act): round(cnt / total, 4) for act, cnt in counts.most_common()}


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


def summarize_dpo_dataset(
    states: list[dict],
    pairs: list[dict],
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    horizon: int = DEFAULT_HORIZON,
) -> dict:
    for st in states:
        guard_dpo_seed(int(st["seed"]))
    for pr in pairs:
        guard_dpo_seed(int(pr["seed"]))

    seeds_seen = [int(st["seed"]) for st in states] + [int(pr["seed"]) for pr in pairs]
    seed_range = (
        [min(seeds_seen), max(seeds_seen)]
        if seeds_seen
        else [DPO_SEED_START, DPO_SEED_START]
    )
    tiers_ordered = list(dict.fromkeys(str(st["tier"]) for st in states))

    n_pairs = len(pairs)
    chosen_acts = [(str(p["chosen_action"][0]), str(p["chosen_action"][1])) for p in pairs]
    rejected_acts = [(str(p["rejected_action"][0]), str(p["rejected_action"][1])) for p in pairs]
    reason_counts = Counter(str(p["rejected_reason"]) for p in pairs)

    mean_chosen_regret = (
        round(statistics.fmean(float(p["chosen_regret"]) for p in pairs), 4) if pairs else 0.0
    )
    mean_rejected_regret = (
        round(statistics.fmean(float(p["rejected_regret"]) for p in pairs), 4) if pairs else 0.0
    )
    mean_margin = (
        round(statistics.fmean(float(p["margin"]) for p in pairs), 4) if pairs else 0.0
    )

    by_tier: dict[str, dict] = {}
    for tier in tiers_ordered:
        t_states = [s for s in states if s["tier"] == tier]
        t_pairs = [p for p in pairs if p["tier"] == tier]
        t_seeds = [int(s["seed"]) for s in t_states]
        by_tier[tier] = {
            "n_states": len(t_states),
            "states_with_pairs": len({(p["seed"], p["day"]) for p in t_pairs}),
            "n_pairs": len(t_pairs),
            "seed_range": [min(t_seeds), max(t_seeds)] if t_seeds else [],
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
                round(statistics.fmean(float(p["margin"]) for p in t_pairs), 4)
                if t_pairs
                else 0.0
            ),
        }

    return {
        "n_states": len(states),
        "states_with_pairs": len({(p["tier"], p["seed"], p["day"]) for p in pairs}),
        "n_pairs": n_pairs,
        "tiers": tiers_ordered,
        "horizon_days": int(horizon),
        "min_margin": float(min_margin),
        "min_solver_score": float(min_solver_score),
        "investigators": list(INVESTIGATORS),
        "seed_range": seed_range,
        "allowed_seed_window": [DPO_SEED_START, DPO_SEED_END],
        "mean_chosen_regret": mean_chosen_regret,
        "mean_rejected_regret": mean_rejected_regret,
        "mean_margin": mean_margin,
        "min_observed_margin": (
            round(min(float(p["margin"]) for p in pairs), 4) if pairs else 0.0
        ),
        "chosen_solver_acc": (
            round(statistics.fmean(1.0 if p["chosen_solver_correct"] else 0.0 for p in pairs), 4)
            if pairs
            else 0.0
        ),
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
    }


def export_mole_dpo(
    out_pairs: str | Path = "/tmp/opencode/w5_dpo/pairs.jsonl",
    stats_out: str | Path = "results/moletrain/mole_dpo_stats.json",
    n_per_tier: int = 30,
    tiers: tuple[str, ...] | list[str] = ALLOWED_TIERS,
    seed_start: int = DPO_SEED_START,
    horizon: int = DEFAULT_HORIZON,
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    max_pairs_per_state: int = DEFAULT_MAX_PAIRS_PER_STATE,
    candidates: tuple[tuple[str, str], ...] = CANDIDATE_ACTIONS,
    workers: int = 2,
    rng_seed: int = 0,
    base_policy: str | None = None,
) -> dict:
    t0 = time.time()
    states = sample_active_states(
        n_per_tier=n_per_tier,
        tiers=tiers,
        seed_start=seed_start,
        rng_seed=rng_seed,
        base_policy=base_policy,
    )
    tasks = [
        (st["seed"], st["day"], st["tier"], horizon, act, base_policy)
        for st in states
        for act in candidates
    ]
    if workers > 1 and tasks:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            scored_flat = list(ex.map(score_candidate_action, tasks))
    else:
        scored_flat = [score_candidate_action(t) for t in tasks]

    k = len(candidates)
    all_pairs: list[dict] = []
    for idx, st in enumerate(states):
        chunk = scored_flat[idx * k : (idx + 1) * k]
        all_pairs.extend(
            build_pairs_for_state(
                state=st,
                scored=chunk,
                min_margin=min_margin,
                min_solver_score=min_solver_score,
                max_pairs_per_state=max_pairs_per_state,
                horizon=horizon,
            )
        )

    pairs_path = Path(out_pairs)
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
        horizon=horizon,
    )
    stats["n_candidates_per_state"] = len(candidates)
    stats["elapsed_sec"] = round(time.time() - t0, 2)

    stats_path = Path(stats_out)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.export_mole_dpo")
    ap.add_argument("--out-pairs", default="/tmp/opencode/w5_dpo/pairs.jsonl")
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
        default=min(4, max(1, int(os.environ.get("SLURM_CPUS_PER_TASK", "2")))),
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--base-policy", default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    stats = export_mole_dpo(
        out_pairs=args.out_pairs,
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
    )
    print(json.dumps(stats, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
