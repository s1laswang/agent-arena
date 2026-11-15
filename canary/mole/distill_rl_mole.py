from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

from canary.analysis.gap import mean_ci
from canary.baselines import AccuseMostLogs, DoNothing, GrokTactics, Heuristic, LogsOnly
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import (
    FEATURE_NAMES,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    N_FEAT,
    N_FRAME,
    N_LEAK,
    RLMole,
    _grad_entropy,
    _grad_logp,
    _softmax,
    features,
)
from canary.forge_track import _strategy
from canary.mole.counterfactual import evaluate_counterfactual
from canary.mole.dsl import DEFAULT_STRATEGY, OPS, MoleDoc, MoleStrategy, MoleView
from canary.mole.evolve_v14 import RESERVED_HELDOUT_EVAL_SEEDS
from canary.mole.fairness_audit import CHECK_NAMES, audit_strategy
from canary.mole.strategies import get_strategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "CORE_INVESTIGATORS",
    "DEFAULT_BC_SEEDS",
    "DEFAULT_COUNTERFACTUAL_SEEDS",
    "DEFAULT_HELDOUT_SEEDS",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_REFINE_SEED_BASE",
    "DEFAULT_REPORT_PATH",
    "DEFAULT_SELECT_SEEDS",
    "DEFAULT_TEACHER",
    "FORBIDDEN_SECRET_KEYS",
    "FRONTIER_INVESTIGATORS",
    "LEDGER_END",
    "LEDGER_START",
    "MAX_POLICY_JSON_BYTES",
    "MIN_TRAIN_SEED",
    "assert_ledger_invariants",
    "build_boundary_views",
    "build_distill_ledger",
    "canonical_rl_mole_sha256",
    "check_distilled_artifacts",
    "clone_strategy_to_rl_mole",
    "coerce_mole_policy",
    "collect_mole_views",
    "evaluate_frontier_suite",
    "format_markdown_report",
    "main",
    "make_investigator",
    "normalize_seeds",
    "parse_embedded_ledger",
    "refine_constrained_cem",
    "refine_constrained_reinforce",
    "render_report_from_ledger",
    "resolve_teacher",
    "round_params",
    "selector_profile",
    "teacher_selector_indices",
    "train_and_validate",
    "validate_distilled_mole",
    "validate_eval_seeds",
    "validate_train_seeds",
    "validate_workers",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT / "data" / "forge" / "rl_mole_frontier_v14.json"
DEFAULT_REPORT_PATH = ROOT / "docs" / "reports" / "rl_mole_frontier_v14.md"

H1 = chr(35)
H2 = H1 * 2
H3 = H1 * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
MAX_POLICY_JSON_BYTES = 95_000
LEDGER_START = "<!-- DISTILL_RL_MOLE_LEDGER_START -->"
LEDGER_END = "<!-- DISTILL_RL_MOLE_LEDGER_END -->"
FORBIDDEN_GAP_RE = re.compile(
    r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
    re.IGNORECASE,
)

FORBIDDEN_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "true_mole",
        "secret_mole",
        "mole_id",
        "mole_identity",
        "world_secret",
        "world_key",
        "salt",
        "ledger_token",
        "ledger_events",
    }
)
SECRET_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)

MIN_TRAIN_SEED = 110_000
RESERVED_RL_EVAL_MIN = 200_000
RESERVED_RL_EVAL_MAX = 220_000

DEFAULT_TEACHER = "frontier_synthesis_v14"
DEFAULT_BC_SEEDS = range(110_000, 110_003)
DEFAULT_REFINE_SEED_BASE = 110_100
DEFAULT_SELECT_SEEDS = range(110_510, 110_517)
DEFAULT_HELDOUT_SEEDS = range(210_020, 210_027)
DEFAULT_COUNTERFACTUAL_SEEDS = range(0, 4)

DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_MIN_SOLVER_RATIO = 0.50

FRONTIER_INVESTIGATORS: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
)
CORE_INVESTIGATORS: tuple[str, ...] = (
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
)

_DEFAULT_SUITE_CACHE: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
_EPISODE_CACHE: dict[tuple[str, int, str, str], tuple[float, bool, int]] = {}


def validate_workers(workers: int = 1) -> int:
    w = int(workers)
    if w != 1:
        raise ValueError(f"single-process mode required (--workers 1), got workers={w}")
    return w


def _parse_seed_spec(spec: str, base: int = MIN_TRAIN_SEED) -> list[int]:
    s = str(spec).strip()
    if not s:
        raise ValueError("seeds must not be empty")
    if s.startswith("n:"):
        count = int(s[2:])
        if count <= 0:
            raise ValueError("seed count must be positive")
        return list(range(int(base), int(base) + count))
    out: list[int] = []
    for raw in s.split(","):
        part = raw.strip()
        if not part:
            raise ValueError(f"empty seed token in {spec!r}")
        if "-" in part and not part.startswith("-"):
            a_str, b_str = part.split("-", 1)
            a, b = int(a_str), int(b_str)
            if b < a:
                raise ValueError(f"reversed seed range {part!r}")
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return out


def normalize_seeds(seeds: str | int | Iterable[int], base: int = MIN_TRAIN_SEED) -> list[int]:
    if isinstance(seeds, bool):
        raise ValueError("boolean values are not valid seeds")
    if isinstance(seeds, str):
        out = _parse_seed_spec(seeds, base=base)
    elif isinstance(seeds, int):
        out = list(range(int(base), int(base) + int(seeds)))
    else:
        raw_items = list(seeds)
        if any(isinstance(s, bool) for s in raw_items):
            raise ValueError("boolean values are not valid seeds")
        out = [int(s) for s in raw_items]
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def validate_train_seeds(seeds: str | int | Iterable[int]) -> list[int]:
    seed_list = normalize_seeds(seeds, base=MIN_TRAIN_SEED)
    if len(set(seed_list)) != len(seed_list):
        raise ValueError("duplicate seeds are forbidden")
    for s in seed_list:
        if s < MIN_TRAIN_SEED:
            raise ValueError(f"training seed {s} must be >= {MIN_TRAIN_SEED}")
        if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
            raise ValueError(f"training seed {s} violates judge/heldout seed hygiene")
        if RESERVED_RL_EVAL_MIN <= s < RESERVED_RL_EVAL_MAX:
            raise ValueError(f"training seed {s} falls in reserved RL held-out range 200000..219999")
        if s in RESERVED_HELDOUT_EVAL_SEEDS:
            raise ValueError(f"training seed {s} falls in reserved held-out range 30000..30199")
    return seed_list


def validate_eval_seeds(seeds: str | int | Iterable[int], base: int = 210_000) -> list[int]:
    seed_list = normalize_seeds(seeds, base=base)
    if len(set(seed_list)) != len(seed_list):
        raise ValueError("duplicate evaluation seeds are forbidden")
    for s in seed_list:
        if s < 60:
            raise ValueError(f"evaluation seed {s} violates fresh-seed hygiene (< 60)")
        if s in RESERVED_HELDOUT_EVAL_SEEDS:
            raise ValueError(f"evaluation seed {s} falls in reserved held-out range 30000..30199")
        if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
            raise ValueError(f"evaluation seed {s} violates judge/heldout seed hygiene")
    return seed_list


def make_investigator(name: str, tier: str, seed: int) -> Any:
    if name == "solver":
        return SolverPolicy(tier if tier in TIERS else tier_params(tier))
    if name == "logs_only":
        return LogsOnly(seed=seed)
    if name == "accuse_most_logs":
        return AccuseMostLogs(seed=seed)
    if name == "do_nothing":
        return DoNothing(seed=seed)
    if name == "gemini_carbon_proxy":
        return GeminiCarbonProxy(seed=seed)
    if name == "codex_horizon_proxy":
        return CodexHorizonProxy(seed=seed)
    if name == "grok_tactics":
        return GrokTactics(seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if name == "heuristic":
        return Heuristic(seed=seed)
    raise ValueError(f"unknown investigator {name!r}")


def resolve_teacher(teacher: str | MoleStrategy | dict[str, Any] = DEFAULT_TEACHER) -> MoleStrategy:
    if isinstance(teacher, MoleStrategy):
        return teacher
    if isinstance(teacher, str):
        return get_strategy(teacher)
    if isinstance(teacher, dict):
        payload = teacher.get("strategy_json", teacher.get("strategy", teacher))
        return MoleStrategy.from_json(payload)
    raise TypeError(f"unsupported teacher type: {type(teacher).__name__}")


def coerce_mole_policy(
    policy: str | Path | MoleStrategy | RLMole | dict[str, Any],
) -> MoleStrategy | RLMole:
    if isinstance(policy, (MoleStrategy, RLMole)):
        return _strategy(policy.to_json())
    if isinstance(policy, Path):
        raw = json.loads(policy.read_text(encoding="utf-8"))
        payload = raw.get("strategy_json", raw.get("strategy", raw)) if isinstance(raw, dict) else raw
        return _strategy(payload)
    if isinstance(policy, str):
        p = Path(policy)
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
            payload = raw.get("strategy_json", raw.get("strategy", raw)) if isinstance(raw, dict) else raw
            return _strategy(payload)
        if policy in ("default", DEFAULT_STRATEGY.name):
            return DEFAULT_STRATEGY
        return get_strategy(policy)
    if isinstance(policy, dict):
        payload = policy.get("strategy_json", policy.get("strategy", policy))
        return _strategy(payload)
    raise TypeError(f"unsupported policy type: {type(policy).__name__}")


def round_params(params: dict[str, Any], decimals: int = 8) -> dict[str, np.ndarray]:
    expected = ("W1", "b1", "Wl", "bl", "Wf", "bf")
    if set(params.keys()) != set(expected):
        raise ValueError(f"params keys mismatch: {sorted(params.keys())}")
    out: dict[str, np.ndarray] = {}
    for k in expected:
        arr = np.asarray(params[k], dtype=np.float64)
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"non-finite values in parameter {k}")
        out[k] = np.round(arr, decimals=decimals)
    hidden = int(out["W1"].shape[1]) if out["W1"].ndim == 2 else -1
    if out["W1"].ndim != 2 or out["W1"].shape[0] != N_FEAT or hidden <= 0:
        raise ValueError(f"invalid W1 shape: {out['W1'].shape}")
    if out["b1"].shape != (hidden,):
        raise ValueError(f"invalid b1 shape: {out['b1'].shape}")
    if out["Wl"].shape != (hidden, N_LEAK) or out["bl"].shape != (N_LEAK,):
        raise ValueError(f"invalid leak head shapes: {out['Wl'].shape}, {out['bl'].shape}")
    if out["Wf"].shape != (hidden, N_FRAME) or out["bf"].shape != (N_FRAME,):
        raise ValueError(f"invalid frame head shapes: {out['Wf'].shape}, {out['bf'].shape}")
    return out


def teacher_selector_indices(teacher: MoleStrategy, view: MoleView) -> tuple[int, int]:
    leak_sel, frame_sel = teacher.default
    for conds, then in teacher.rules:
        if all(OPS[op](view.feature(f), n) for f, op, n in conds):
            leak_sel, frame_sel = then
            break
    return LEAK_SELECTORS.index(leak_sel), FRAME_SELECTORS.index(frame_sel)


class _ViewRecorderMole:
    def __init__(self, inner: MoleStrategy | RLMole, sink: list[MoleView]):
        self.inner = inner
        self.sink = sink

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        self.sink.append(view)
        return self.inner.decide(view, rng)


def collect_mole_views(
    teacher: str | MoleStrategy | dict[str, Any] = DEFAULT_TEACHER,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = DEFAULT_BC_SEEDS,
    workers: int = 1,
) -> list[MoleView]:
    validate_workers(workers)
    seed_list = validate_train_seeds(seeds)
    strat = resolve_teacher(teacher)
    views: list[MoleView] = []
    rollout_moles: tuple[MoleStrategy, ...] = (strat, DEFAULT_STRATEGY)
    for s in seed_list:
        for base_mole in rollout_moles:
            for inv_name in FRONTIER_INVESTIGATORS:
                rec = _ViewRecorderMole(base_mole, views)
                run_episode(Env(tier, s, mole_strategy=rec), make_investigator(inv_name, tier, s))
    return views


def build_boundary_views(tier: str = "hard") -> list[MoleView]:
    tp = tier_params(tier)
    peers = tuple(f"e{i:02d}" for i in range(1, tp.n_employees))
    decoy = peers[0] if tp.decoy and peers else None
    views: list[MoleView] = []
    days = (1, 3, 4, 5, 6, 7, 8, 9, 12, 16, tp.n_days)
    dsl_vals = (0, 1, 2, 3)
    n_rest_vals = (0, 1, 3)
    low_rc_vals = (0, 1, 2, 3)
    newest_ages = (0, 1, 2)
    doc_counts = (1, 2, 5)
    for day in days:
        for dsl in dsl_vals:
            if dsl > day:
                continue
            for n_rest in n_rest_vals:
                r_peers = peers[1 : 1 + n_rest]
                for low_rc in low_rc_vals:
                    for newest_age in newest_ages:
                        for n_docs in doc_counts:
                            if low_rc > n_docs:
                                continue
                            docs_list: list[MoleDoc] = []
                            for di in range(n_docs):
                                rc = 2 if di < low_rc else (18 if di == n_docs - 1 else 8)
                                age = newest_age if di == 0 else min(2, newest_age + 1)
                                docs_list.append(
                                    MoleDoc(
                                        doc_id=f"d_{day}_{di}",
                                        title=f"Doc {di}",
                                        recipient_count=rc,
                                        age_days=age,
                                    )
                                )
                            views.append(
                                MoleView(
                                    day=day,
                                    docs=tuple(docs_list),
                                    days_since_last_leak=dsl,
                                    i_am_restricted=0,
                                    n_restricted_colleagues=n_rest,
                                    recent_low_recipient_docs=low_rc,
                                    peers=peers,
                                    restricted_peers=r_peers,
                                    decoy=decoy,
                                    can_leak=True,
                                    select_weights=None,
                                )
                            )
    for day in (1, 6, 10):
        views.append(
            MoleView(
                day=day,
                docs=(),
                days_since_last_leak=min(2, day),
                i_am_restricted=1,
                n_restricted_colleagues=2,
                recent_low_recipient_docs=0,
                peers=peers,
                restricted_peers=peers[1:3],
                decoy=decoy,
                can_leak=False,
                select_weights=None,
            )
        )
    return views


def _dedupe_weighted_dataset(
    X: np.ndarray,
    yl: np.ndarray,
    yf: np.ndarray,
    sample_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    keys = np.hstack([np.round(X, 6), yl[:, None].astype(np.float64), yf[:, None].astype(np.float64)])
    _, first_idx, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    agg_w = np.bincount(inv, weights=sample_weights).astype(np.float64)
    agg_w /= max(float(agg_w.sum()), 1e-12)
    return X[first_idx], yl[first_idx], yf[first_idx], agg_w


def clone_strategy_to_rl_mole(
    teacher: str | MoleStrategy | dict[str, Any] = DEFAULT_TEACHER,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = DEFAULT_BC_SEEDS,
    hidden: int = 20,
    epochs: int = 650,
    lr: float = 0.05,
    weight_decay: float = 3e-4,
    label_smoothing: float = 0.03,
    boundary_weight: float = 0.15,
    seed: int = 42,
    greedy: bool = True,
    name: str = "rl_mole_bc_v14",
    include_boundary_views: bool = True,
    workers: int = 1,
) -> dict[str, Any]:
    validate_workers(workers)
    seed_list = validate_train_seeds(seeds)
    if hidden <= 0:
        raise ValueError("hidden must be positive")
    strat = resolve_teacher(teacher)

    t0 = time.time()
    rollout_views = collect_mole_views(strat, tier=tier, seeds=seed_list, workers=1)
    if not rollout_views:
        raise RuntimeError("no MoleView states collected for behavioral cloning")

    X_emp = np.stack([features(v) for v in rollout_views])
    labels_emp = [teacher_selector_indices(strat, v) for v in rollout_views]
    yl_emp = np.asarray([ pair[0] for pair in labels_emp ], dtype=np.int64)
    yf_emp = np.asarray([ pair[1] for pair in labels_emp ], dtype=np.int64)

    if include_boundary_views and boundary_weight > 0.0:
        b_views = build_boundary_views(tier=tier)
        X_bnd = np.stack([features(v) for v in b_views])
        labels_bnd = [teacher_selector_indices(strat, v) for v in b_views]
        yl_bnd = np.asarray([pair[0] for pair in labels_bnd], dtype=np.int64)
        yf_bnd = np.asarray([pair[1] for pair in labels_bnd], dtype=np.int64)

        w_emp = np.full(len(X_emp), (1.0 - boundary_weight) / len(X_emp), dtype=np.float64)
        w_bnd = np.full(len(X_bnd), boundary_weight / len(X_bnd), dtype=np.float64)
        X_comb = np.vstack([X_emp, X_bnd])
        yl_comb = np.concatenate([yl_emp, yl_bnd])
        yf_comb = np.concatenate([yf_emp, yf_bnd])
        w_comb = np.concatenate([w_emp, w_bnd])
    else:
        b_views = []
        X_comb = X_emp
        yl_comb = yl_emp
        yf_comb = yf_emp
        w_comb = np.full(len(X_emp), 1.0 / len(X_emp), dtype=np.float64)

    X_u, yl_u, yf_u, w_u = _dedupe_weighted_dataset(X_comb, yl_comb, yf_comb, w_comb)

    rng = np.random.default_rng(seed)
    params: dict[str, np.ndarray] = {
        "W1": rng.normal(0.0, 0.25, (N_FEAT, hidden)),
        "b1": np.zeros(hidden, dtype=np.float64),
        "Wl": rng.normal(0.0, 0.10, (hidden, N_LEAK)),
        "bl": np.zeros(N_LEAK, dtype=np.float64),
        "Wf": rng.normal(0.0, 0.10, (hidden, N_FRAME)),
        "bf": np.zeros(N_FRAME, dtype=np.float64),
    }

    smooth = float(np.clip(label_smoothing, 0.0, 0.25))
    target_l = np.full((len(X_u), N_LEAK), smooth / N_LEAK, dtype=np.float64)
    target_l[np.arange(len(X_u)), yl_u] += 1.0 - smooth
    target_f = np.full((len(X_u), N_FRAME), smooth / N_FRAME, dtype=np.float64)
    target_f[np.arange(len(X_u)), yf_u] += 1.0 - smooth

    m_opt = {k: np.zeros_like(v) for k, v in params.items()}
    v_opt = {k: np.zeros_like(v) for k, v in params.items()}

    for ep in range(1, int(epochs) + 1):
        H = np.tanh(X_u @ params["W1"] + params["b1"])
        zl = H @ params["Wl"] + params["bl"]
        zl = zl - zl.max(axis=1, keepdims=True)
        pl = np.exp(zl)
        pl /= pl.sum(axis=1, keepdims=True)

        zf = H @ params["Wf"] + params["bf"]
        zf = zf - zf.max(axis=1, keepdims=True)
        pf = np.exp(zf)
        pf /= pf.sum(axis=1, keepdims=True)

        dl = (pl - target_l) * w_u[:, None]
        df = (pf - target_f) * w_u[:, None]

        grads = {
            "Wl": H.T @ dl + weight_decay * params["Wl"],
            "bl": dl.sum(axis=0),
            "Wf": H.T @ df + weight_decay * params["Wf"],
            "bf": df.sum(axis=0),
        }
        dH = (dl @ params["Wl"].T + df @ params["Wf"].T) * (1.0 - H * H)
        grads["W1"] = X_u.T @ dH + weight_decay * params["W1"]
        grads["b1"] = dH.sum(axis=0)

        b1_corr = 1.0 - 0.9 ** ep
        b2_corr = 1.0 - 0.999 ** ep
        for k in params:
            m_opt[k] = 0.9 * m_opt[k] + 0.1 * grads[k]
            v_opt[k] = 0.999 * v_opt[k] + 0.001 * (grads[k] * grads[k])
            mh = m_opt[k] / b1_corr
            vh = v_opt[k] / b2_corr
            params[k] = params[k] - lr * mh / (np.sqrt(vh) + 1e-8)

    params = round_params(params, decimals=8)
    H_emp = np.tanh(X_emp @ params["W1"] + params["b1"])
    zl_emp = H_emp @ params["Wl"] + params["bl"]
    zl_emp_s = zl_emp - zl_emp.max(axis=1, keepdims=True)
    pl_emp = np.exp(zl_emp_s)
    pl_emp /= pl_emp.sum(axis=1, keepdims=True)

    zf_emp = H_emp @ params["Wf"] + params["bf"]
    zf_emp_s = zf_emp - zf_emp.max(axis=1, keepdims=True)
    pf_emp = np.exp(zf_emp_s)
    pf_emp /= pf_emp.sum(axis=1, keepdims=True)

    pred_l = zl_emp.argmax(axis=1)
    pred_f = zf_emp.argmax(axis=1)
    leak_acc = float((pred_l == yl_emp).mean())
    frame_acc = float((pred_f == yf_emp).mean())
    joint_acc = float(((pred_l == yl_emp) & (pred_f == yf_emp)).mean())
    ce_loss = float(
        -np.log(pl_emp[np.arange(len(X_emp)), yl_emp] + 1e-12).mean()
        - np.log(pf_emp[np.arange(len(X_emp)), yf_emp] + 1e-12).mean()
    )

    teacher_leak_dist = {
        LEAK_SELECTORS[i]: round(float((yl_emp == i).mean()), 4)
        for i in range(N_LEAK)
        if int((yl_emp == i).sum()) > 0
    }
    teacher_frame_dist = {
        FRAME_SELECTORS[i]: round(float((yf_emp == i).mean()), 4)
        for i in range(N_FRAME)
        if int((yf_emp == i).sum()) > 0
    }

    pol = RLMole(params, greedy=greedy, name=name)
    re_pol = _strategy(json.loads(json.dumps(pol.to_json())))
    if not isinstance(re_pol, RLMole):
        raise RuntimeError("cloned policy failed forge_track._strategy round-trip")

    return {
        "policy": re_pol,
        "params": copy.deepcopy(re_pol.p),
        "bc_metrics": {
            "teacher": strat.name,
            "tier": tier,
            "n_seeds": len(seed_list),
            "seed_range": f"{seed_list[0]}-{seed_list[-1]}",
            "n_rollout_views": int(len(X_emp)),
            "n_boundary_views": int(len(b_views)),
            "n_unique_states": int(len(X_u)),
            "hidden": int(hidden),
            "epochs": int(epochs),
            "leak_acc": leak_acc,
            "frame_acc": frame_acc,
            "joint_acc": joint_acc,
            "cross_entropy": ce_loss,
            "teacher_leak_distribution": teacher_leak_dist,
            "teacher_frame_distribution": teacher_frame_dist,
            "elapsed_sec": round(time.time() - t0, 3),
        },
    }


def _run_agent_seeds(
    mole: MoleStrategy | RLMole,
    tier: str,
    seeds: Sequence[int],
    agent_name: str,
) -> list[tuple[float, bool, int]]:
    mj = mole.to_json()
    mole_key = json.dumps({k: v for k, v in mj.items() if k != "name"}, sort_keys=True)
    rows: list[tuple[float, bool, int]] = []
    for s in seeds:
        ck = (tier, int(s), mole_key, agent_name)
        hit = _EPISODE_CACHE.get(ck)
        if hit is None:
            cloned = _strategy(mj)
            res = run_episode(Env(tier, s, mole_strategy=cloned), make_investigator(agent_name, tier, s))
            hit = (float(res.score), bool(res.correct), int(res.final_day))
            _EPISODE_CACHE[ck] = hit
        rows.append(hit)
    return rows


def _summarize_suite_from_raw(
    raw_by_agent: dict[str, list[tuple[float, bool, int]]],
    tier: str,
    seeds: Sequence[int],
    min_solver_acc: float,
    max_logs_acc: float,
    min_solver_ratio: float,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n = len(seeds)
    sol_rows = raw_by_agent["solver"]
    sol_scores = [r[0] for r in sol_rows]
    sol_score, sol_ci = mean_ci(sol_scores) if sol_scores else (0.0, 0.0)
    sol_acc = sum(1.0 if r[1] else 0.0 for r in sol_rows) / n
    sol_mean_day = sum(float(r[2]) for r in sol_rows) / n

    lo_rows = raw_by_agent["logs_only"]
    lo_score = sum(r[0] for r in lo_rows) / n
    lo_acc = sum(1.0 if r[1] else 0.0 for r in lo_rows) / n

    aml_rows = raw_by_agent["accuse_most_logs"]
    aml_score = sum(r[0] for r in aml_rows) / n
    aml_acc = sum(1.0 if r[1] else 0.0 for r in aml_rows) / n

    dn_rows = raw_by_agent.get("do_nothing")
    dn_score = sum(r[0] for r in dn_rows) / n if dn_rows is not None else 0.0
    dn_acc = sum(1.0 if r[1] else 0.0 for r in dn_rows) / n if dn_rows is not None else 0.0

    per_inv: dict[str, dict[str, float]] = {}
    for inv in FRONTIER_INVESTIGATORS:
        inv_rows = raw_by_agent[inv]
        inv_scores = [r[0] for r in inv_rows]
        iscore, ici = mean_ci(inv_scores) if inv_scores else (0.0, 0.0)
        iacc = sum(1.0 if r[1] else 0.0 for r in inv_rows) / n
        reg_list = [sol_scores[i] - inv_scores[i] for i in range(n)]
        reg_m, reg_ci = mean_ci(reg_list) if reg_list else (0.0, 0.0)
        per_inv[inv] = {
            "score": iscore,
            "ci": ici,
            "acc": iacc,
            "regret": reg_m,
            "regret_ci": reg_ci,
        }

    strongest = max(FRONTIER_INVESTIGATORS, key=lambda k: per_inv[k]["score"])
    min_regret = sol_score - per_inv[strongest]["score"]
    mean_regret = sol_score - sum(per_inv[k]["score"] for k in FRONTIER_INVESTIGATORS) / len(FRONTIER_INVESTIGATORS)
    frontier_proxy_regret = sol_score - 0.5 * (
        per_inv["gemini_carbon_proxy"]["score"] + per_inv["codex_horizon_proxy"]["score"]
    )
    core_strongest = max(CORE_INVESTIGATORS, key=lambda k: per_inv[k]["score"])
    core_min_regret = sol_score - per_inv[core_strongest]["score"]

    base_sol_score = float(baseline["solver_score"]) if baseline is not None else sol_score
    solver_ok = bool(sol_acc >= min_solver_acc and sol_score >= min_solver_ratio * base_sol_score)
    logs_ok = bool(
        lo_acc <= max_logs_acc
        and lo_score < 0.0
        and aml_acc <= max_logs_acc
        and aml_score < 0.0
        and dn_score == 0.0
        and dn_acc == 0.0
    )
    feasible = bool(solver_ok and logs_ok)

    out: dict[str, Any] = {
        "tier": tier,
        "n_seeds": n,
        "seeds": list(seeds),
        "solver_score": sol_score,
        "solver_ci": sol_ci,
        "solver_acc": sol_acc,
        "solver_mean_day": sol_mean_day,
        "logs_only_score": lo_score,
        "logs_only_acc": lo_acc,
        "accuse_most_logs_score": aml_score,
        "accuse_most_logs_acc": aml_acc,
        "do_nothing_score": dn_score,
        "do_nothing_acc": dn_acc,
        "per_investigator": per_inv,
        "strongest_investigator": strongest,
        "min_regret": min_regret,
        "mean_regret": mean_regret,
        "frontier_proxy_regret": frontier_proxy_regret,
        "core_strongest_investigator": core_strongest,
        "core_min_regret": core_min_regret,
        "min_solver_acc": float(min_solver_acc),
        "max_logs_acc": float(max_logs_acc),
        "min_solver_ratio": float(min_solver_ratio),
        "baseline_solver_score": base_sol_score,
        "solver_passed": solver_ok,
        "logs_passed": logs_ok,
        "feasible": feasible,
    }
    if baseline is not None:
        out["min_regret_gain"] = min_regret - float(baseline["min_regret"])
        out["mean_regret_gain"] = mean_regret - float(baseline["mean_regret"])
        out["frontier_proxy_regret_gain"] = frontier_proxy_regret - float(baseline["frontier_proxy_regret"])
        out["core_min_regret_gain"] = core_min_regret - float(baseline["core_min_regret"])
    else:
        out["min_regret_gain"] = 0.0
        out["mean_regret_gain"] = 0.0
        out["frontier_proxy_regret_gain"] = 0.0
        out["core_min_regret_gain"] = 0.0
    return out


def _default_suite_baseline(
    tier: str,
    seeds: Sequence[int],
    min_solver_acc: float,
    max_logs_acc: float,
    min_solver_ratio: float,
) -> dict[str, Any]:
    key = (tier, tuple(seeds))
    if key not in _DEFAULT_SUITE_CACHE:
        all_agents = ("solver", "logs_only", "accuse_most_logs", "do_nothing", *FRONTIER_INVESTIGATORS)
        raw = {a: _run_agent_seeds(DEFAULT_STRATEGY, tier, seeds, a) for a in all_agents}
        _DEFAULT_SUITE_CACHE[key] = _summarize_suite_from_raw(
            raw,
            tier=tier,
            seeds=seeds,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            baseline=None,
        )
    return copy.deepcopy(_DEFAULT_SUITE_CACHE[key])


def evaluate_frontier_suite(
    policy: str | Path | MoleStrategy | RLMole | dict[str, Any],
    tier: str = "hard",
    seeds: str | int | Iterable[int] = DEFAULT_HELDOUT_SEEDS,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    workers: int = 1,
) -> dict[str, Any]:
    validate_workers(workers)
    seed_list = validate_eval_seeds(seeds)
    parsed = coerce_mole_policy(policy)
    baseline = _default_suite_baseline(
        tier=tier,
        seeds=seed_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
    )
    if (
        isinstance(parsed, MoleStrategy)
        and parsed.rules == DEFAULT_STRATEGY.rules
        and parsed.default == DEFAULT_STRATEGY.default
    ):
        res = copy.deepcopy(baseline)
        res["name"] = parsed.name
        res["kind"] = "dsl"
        return res

    all_agents = ("solver", "logs_only", "accuse_most_logs", "do_nothing", *FRONTIER_INVESTIGATORS)
    raw = {a: _run_agent_seeds(parsed, tier, seed_list, a) for a in all_agents}
    res = _summarize_suite_from_raw(
        raw,
        tier=tier,
        seeds=seed_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        baseline=baseline,
    )
    res["name"] = getattr(parsed, "name", "custom")
    res["kind"] = "rl_mole" if isinstance(parsed, RLMole) else "dsl"
    return res


def _constrained_objective(
    metrics: dict[str, Any],
    safety_solver_acc_margin: float = 0.05,
) -> float:
    min_sol_acc = float(metrics["min_solver_acc"])
    max_lo_acc = float(metrics["max_logs_acc"])
    min_sol_score = float(metrics["min_solver_ratio"]) * float(metrics["baseline_solver_score"])
    sol_acc = float(metrics["solver_acc"])
    sol_score = float(metrics["solver_score"])
    lo_acc = float(metrics["logs_only_acc"])
    lo_score = float(metrics["logs_only_score"])
    aml_acc = float(metrics["accuse_most_logs_acc"])
    aml_score = float(metrics["accuse_most_logs_score"])

    if not metrics["feasible"]:
        pen = -10.0
        pen -= 25.0 * max(0.0, min_sol_acc - sol_acc)
        pen -= 25.0 * max(0.0, lo_acc - max_lo_acc)
        pen -= 15.0 * max(0.0, aml_acc - max_lo_acc)
        pen -= 10.0 * max(0.0, min_sol_score - sol_score)
        pen -= 5.0 * max(0.0, lo_score + 0.05)
        pen -= 5.0 * max(0.0, aml_score + 0.05)
        return float(pen + 0.10 * float(metrics["min_regret"]))

    safety_target = min(1.0, min_sol_acc + safety_solver_acc_margin)
    safety_term = 0.15 * min(0.0, sol_acc - safety_target)
    return float(
        0.35 * float(metrics["min_regret"])
        + 0.30 * float(metrics["core_min_regret"])
        + 0.20 * float(metrics["frontier_proxy_regret"])
        + 0.15 * float(metrics["mean_regret"])
        + safety_term
    )


def _evaluate_candidate_cascade(
    params: dict[str, np.ndarray],
    greedy: bool,
    tier: str,
    seeds: Sequence[int],
    baseline: dict[str, Any],
    min_solver_acc: float,
    max_logs_acc: float,
    min_solver_ratio: float,
    safety_solver_acc_margin: float,
) -> tuple[float, dict[str, Any], bool]:
    mole = RLMole(params, greedy=greedy)
    n = len(seeds)
    lo_rows = _run_agent_seeds(mole, tier, seeds, "logs_only")
    lo_acc = sum(1.0 if r[1] else 0.0 for r in lo_rows) / n
    lo_score = sum(r[0] for r in lo_rows) / n

    aml_rows = _run_agent_seeds(mole, tier, seeds, "accuse_most_logs")
    aml_acc = sum(1.0 if r[1] else 0.0 for r in aml_rows) / n
    aml_score = sum(r[0] for r in aml_rows) / n

    if lo_acc > max_logs_acc or lo_score >= 0.0 or aml_acc > max_logs_acc or aml_score >= 0.0:
        fast_metrics = {
            "feasible": False,
            "min_solver_acc": min_solver_acc,
            "max_logs_acc": max_logs_acc,
            "min_solver_ratio": min_solver_ratio,
            "baseline_solver_score": float(baseline["solver_score"]),
            "solver_acc": min_solver_acc,
            "solver_score": float(baseline["solver_score"]),
            "logs_only_acc": lo_acc,
            "logs_only_score": lo_score,
            "accuse_most_logs_acc": aml_acc,
            "accuse_most_logs_score": aml_score,
            "min_regret": -0.5,
            "mean_regret": -0.5,
            "frontier_proxy_regret": -0.5,
            "core_min_regret": -0.5,
        }
        return _constrained_objective(fast_metrics, safety_solver_acc_margin), fast_metrics, True

    mini_n = min(6, n)
    sol_mini = _run_agent_seeds(mole, tier, seeds[:mini_n], "solver")
    max_possible_acc = (sum(1.0 if r[1] else 0.0 for r in sol_mini) + (n - mini_n)) / n
    mini_acc = sum(1.0 if r[1] else 0.0 for r in sol_mini) / mini_n
    if max_possible_acc < min_solver_acc or (mini_n >= 6 and mini_acc < max(0.50, min_solver_acc - 0.20)):
        fast_metrics = {
            "feasible": False,
            "min_solver_acc": min_solver_acc,
            "max_logs_acc": max_logs_acc,
            "min_solver_ratio": min_solver_ratio,
            "baseline_solver_score": float(baseline["solver_score"]),
            "solver_acc": mini_acc,
            "solver_score": sum(r[0] for r in sol_mini) / mini_n,
            "logs_only_acc": lo_acc,
            "logs_only_score": lo_score,
            "accuse_most_logs_acc": aml_acc,
            "accuse_most_logs_score": aml_score,
            "min_regret": -0.25,
            "mean_regret": -0.25,
            "frontier_proxy_regret": -0.25,
            "core_min_regret": -0.25,
        }
        return _constrained_objective(fast_metrics, safety_solver_acc_margin), fast_metrics, True

    sol_rest = _run_agent_seeds(mole, tier, seeds[mini_n:], "solver") if mini_n < n else []
    raw: dict[str, list[tuple[float, bool, int]]] = {
        "solver": sol_mini + sol_rest,
        "logs_only": lo_rows,
        "accuse_most_logs": aml_rows,
    }
    for inv in FRONTIER_INVESTIGATORS:
        raw[inv] = _run_agent_seeds(mole, tier, seeds, inv)

    full_metrics = _summarize_suite_from_raw(
        raw,
        tier=tier,
        seeds=seeds,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        baseline=baseline,
    )
    obj = _constrained_objective(full_metrics, safety_solver_acc_margin)
    return obj, full_metrics, False


def _sample_cem_candidate(
    mu: dict[str, np.ndarray],
    sigma: dict[str, np.ndarray],
    rng: np.random.Generator,
    mode: int,
) -> dict[str, np.ndarray]:
    cand = {k: v.copy() for k, v in mu.items()}
    hidden = int(mu["W1"].shape[1])
    if mode == 0:
        for k in cand:
            cand[k] = cand[k] + sigma[k] * rng.standard_normal(cand[k].shape)
    elif mode == 1:
        n_units = max(2, hidden // 4)
        units = rng.choice(hidden, size=min(hidden, n_units), replace=False)
        cand["W1"][:, units] += 1.25 * sigma["W1"][:, units] * rng.standard_normal((N_FEAT, len(units)))
        cand["b1"][units] += 1.25 * sigma["b1"][units] * rng.standard_normal(len(units))
        cand["Wl"][units, :] += 1.25 * sigma["Wl"][units, :] * rng.standard_normal((len(units), N_LEAK))
        cand["Wf"][units, :] += 1.25 * sigma["Wf"][units, :] * rng.standard_normal((len(units), N_FRAME))
        cand["bl"] += 0.75 * sigma["bl"] * rng.standard_normal(N_LEAK)
        cand["bf"] += 0.75 * sigma["bf"] * rng.standard_normal(N_FRAME)
    else:
        for k in ("Wl", "bl", "Wf", "bf", "b1"):
            cand[k] = cand[k] + sigma[k] * rng.standard_normal(cand[k].shape)
    return round_params(cand, decimals=8)


def refine_constrained_cem(
    init_params: dict[str, np.ndarray],
    tier: str = "hard",
    iters: int = 1,
    pop_size: int = 2,
    batch_size: int = 7,
    elite_frac: float = 0.50,
    sigma_init: float = 0.15,
    sigma_min: float = 0.05,
    momentum: float = 0.65,
    train_seed_base: int = DEFAULT_REFINE_SEED_BASE,
    select_seeds: str | int | Iterable[int] = DEFAULT_SELECT_SEEDS,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    safety_solver_acc_margin: float = 0.05,
    greedy: bool = True,
    seed: int = 42,
    workers: int = 1,
    name: str = "rl_mole_frontier_v14",
) -> dict[str, Any]:
    validate_workers(workers)
    if iters < 1 or pop_size < 2 or batch_size < 2:
        raise ValueError("iters >= 1, pop_size >= 2, and batch_size >= 2 required")
    sel_seed_list = validate_train_seeds(select_seeds)
    validate_train_seeds([train_seed_base, train_seed_base + iters * batch_size])

    base_p = round_params(init_params, decimals=8)
    mu = {k: v.copy() for k, v in base_p.items()}
    sigma = {k: np.full_like(v, float(sigma_init)) for k, v in base_p.items()}
    incumbent = {k: v.copy() for k, v in base_p.items()}

    rng = np.random.default_rng(seed)
    n_elite = max(2, min(pop_size, int(round(elite_frac * pop_size))))
    curve: list[dict[str, Any]] = []
    archive: list[tuple[float, dict[str, np.ndarray]]] = []

    for it in range(iters):
        t0 = time.time()
        offset = (it * batch_size) % 360
        batch_seeds = validate_train_seeds(
            range(train_seed_base + offset, train_seed_base + offset + batch_size)
        )
        batch_base = _default_suite_baseline(
            tier=tier,
            seeds=batch_seeds,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
        )

        candidates: list[dict[str, np.ndarray]] = [
            {k: v.copy() for k, v in incumbent.items()},
        ]
        if pop_size >= 3:
            candidates.append(round_params(mu, decimals=8))
        while len(candidates) < pop_size:
            mode = (len(candidates) - 1) % 3
            candidates.append(_sample_cem_candidate(mu, sigma, rng, mode=mode))

        scored: list[tuple[float, dict[str, Any], dict[str, np.ndarray], bool]] = []
        n_screened = 0
        for cand_p in candidates:
            obj, met, fast_rejected = _evaluate_candidate_cascade(
                cand_p,
                greedy=greedy,
                tier=tier,
                seeds=batch_seeds,
                baseline=batch_base,
                min_solver_acc=min_solver_acc,
                max_logs_acc=max_logs_acc,
                min_solver_ratio=min_solver_ratio,
                safety_solver_acc_margin=safety_solver_acc_margin,
            )
            if fast_rejected:
                n_screened += 1
            scored.append((obj, met, cand_p, fast_rejected))
            if met["feasible"]:
                archive.append((obj, {k: v.copy() for k, v in cand_p.items()}))

        scored.sort(key=lambda item: (bool(item[1]["feasible"]), float(item[0])), reverse=True)
        elites = scored[:n_elite]
        best_obj, best_met, best_cand, _ = scored[0]
        if best_met["feasible"]:
            incumbent = {k: v.copy() for k, v in best_cand.items()}

        for k in mu:
            stacked = np.stack([item[2][k] for item in elites], axis=0)
            elite_mean = stacked.mean(axis=0)
            elite_std = stacked.std(axis=0)
            mu[k] = (1.0 - momentum) * mu[k] + momentum * elite_mean
            sigma[k] = np.maximum(sigma_min, (1.0 - momentum) * sigma[k] + momentum * elite_std)

        curve.append(
            {
                "iter": it,
                "objective": round(float(best_obj), 5),
                "feasible": bool(best_met["feasible"]),
                "solver_score": round(float(best_met["solver_score"]), 4),
                "solver_acc": round(float(best_met["solver_acc"]), 4),
                "logs_only_acc": round(float(best_met["logs_only_acc"]), 4),
                "min_regret": round(float(best_met["min_regret"]), 4),
                "mean_regret": round(float(best_met["mean_regret"]), 4),
                "frontier_proxy_regret": round(float(best_met["frontier_proxy_regret"]), 4),
                "core_min_regret": round(float(best_met["core_min_regret"]), 4),
                "n_screened": int(n_screened),
                "elapsed_sec": round(time.time() - t0, 3),
            }
        )

    archive.sort(key=lambda item: item[0], reverse=True)
    finalists: list[tuple[str, dict[str, np.ndarray]]] = [("bc_init", base_p)]
    seen_sigs: set[str] = {json.dumps({k: v.tolist() for k, v in base_p.items()}, sort_keys=True)}
    for cand_label, cand_p in [("incumbent", incumbent), ("cem_mean", round_params(mu, decimals=8))]:
        sig = json.dumps({k: v.tolist() for k, v in cand_p.items()}, sort_keys=True)
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            finalists.append((cand_label, cand_p))
    for idx, (_, arch_p) in enumerate(archive):
        if len(finalists) >= 6:
            break
        sig = json.dumps({k: v.tolist() for k, v in arch_p.items()}, sort_keys=True)
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            finalists.append((f"archive_{idx}", arch_p))

    sel_base = _default_suite_baseline(
        tier=tier,
        seeds=sel_seed_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
    )
    selected_rows: list[tuple[bool, float, str, dict[str, np.ndarray], dict[str, Any]]] = []
    for label, fp in finalists:
        f_pol = RLMole(fp, greedy=greedy, name=name)
        all_agents = ("solver", "logs_only", "accuse_most_logs", *FRONTIER_INVESTIGATORS)
        raw = {a: _run_agent_seeds(f_pol, tier, sel_seed_list, a) for a in all_agents}
        met = _summarize_suite_from_raw(
            raw,
            tier=tier,
            seeds=sel_seed_list,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            baseline=sel_base,
        )
        obj = _constrained_objective(met, safety_solver_acc_margin)
        beats_default = bool(
            met["feasible"]
            and met["min_regret_gain"] > 0.0
            and met["core_min_regret_gain"] > 0.0
        )
        selected_rows.append((beats_default, obj, label, fp, met))

    selected_rows.sort(
        key=lambda item: (item[0], bool(item[4]["feasible"]), item[1]),
        reverse=True,
    )
    _, best_sel_obj, best_label, best_params, best_sel_metrics = selected_rows[0]
    best_params = round_params(best_params, decimals=8)
    best_policy = RLMole.from_json(RLMole(best_params, greedy=greedy, name=name).to_json())

    return {
        "method": "cem",
        "policy": best_policy,
        "params": copy.deepcopy(best_policy.p),
        "selected_source": best_label,
        "selected_objective": float(best_sel_obj),
        "selection_metrics": best_sel_metrics,
        "curve": curve,
    }


def refine_constrained_reinforce(
    init_params: dict[str, np.ndarray],
    tier: str = "hard",
    iters: int = 12,
    batch_size: int = 12,
    lr: float = 0.015,
    entropy_coef: float = 0.005,
    lam_solver_init: float = 1.2,
    lam_logs_init: float = 1.0,
    dual_lr: float = 2.0,
    temp: float = 0.08,
    train_seed_base: int = DEFAULT_REFINE_SEED_BASE,
    select_seeds: str | int | Iterable[int] = DEFAULT_SELECT_SEEDS,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    safety_solver_acc_margin: float = 0.05,
    greedy_eval: bool = True,
    seed: int = 42,
    workers: int = 1,
    name: str = "rl_mole_frontier_v14",
) -> dict[str, Any]:
    validate_workers(workers)
    if iters < 1 or batch_size < 2:
        raise ValueError("iters >= 1 and batch_size >= 2 required")
    sel_seed_list = validate_train_seeds(select_seeds)
    validate_train_seeds([train_seed_base, train_seed_base + iters * batch_size])

    base_p = round_params(init_params, decimals=8)
    params = {k: v.copy() for k, v in base_p.items()}
    m_opt = {k: np.zeros_like(v) for k, v in params.items()}
    v_opt = {k: np.zeros_like(v) for k, v in params.items()}

    lam_sol = float(lam_solver_init)
    lam_lo = float(lam_logs_init)
    all_agents = ("solver", "logs_only", *FRONTIER_INVESTIGATORS)
    baselines: dict[str, float | None] = {a: None for a in all_agents}
    checkpoints: list[tuple[str, dict[str, np.ndarray]]] = [("bc_init", base_p)]
    curve: list[dict[str, Any]] = []

    for it in range(iters):
        t0 = time.time()
        offset = (it * batch_size) % 360
        batch_seeds = validate_train_seeds(
            range(train_seed_base + offset, train_seed_base + offset + batch_size)
        )
        ep_rows: list[dict[str, tuple[float, bool, list[tuple[np.ndarray, int, int]]]]] = []
        for s in batch_seeds:
            row_s: dict[str, tuple[float, bool, list[tuple[np.ndarray, int, int]]]] = {}
            for ag in all_agents:
                tr: list[tuple[np.ndarray, int, int]] = []
                mole = RLMole(params, greedy=False, trace=tr)
                res = run_episode(Env(tier, s, mole_strategy=mole), make_investigator(ag, tier, s))
                row_s[ag] = (float(res.score), bool(res.correct), tr)
            ep_rows.append(row_s)

        inv_means = np.asarray(
            [sum(r[a][0] for r in ep_rows) / len(ep_rows) for a in FRONTIER_INVESTIGATORS],
            dtype=np.float64,
        )
        w_inv = _softmax(inv_means / max(temp, 1e-4))
        sol_acc = sum(1.0 if r["solver"][1] else 0.0 for r in ep_rows) / len(ep_rows)
        sol_score = sum(r["solver"][0] for r in ep_rows) / len(ep_rows)
        lo_acc = sum(1.0 if r["logs_only"][1] else 0.0 for r in ep_rows) / len(ep_rows)

        grad = {k: np.zeros_like(v) for k, v in params.items()}
        for r in ep_rows:
            for ag in all_agents:
                sc, corr, tr = r[ag]
                if ag == "solver":
                    rew = sc + lam_sol * float(corr)
                    coef = 1.0
                elif ag == "logs_only":
                    rew = -sc - lam_lo * float(corr)
                    coef = 0.5
                else:
                    idx_inv = FRONTIER_INVESTIGATORS.index(ag)
                    rew = -sc
                    coef = float(w_inv[idx_inv]) * len(FRONTIER_INVESTIGATORS)
                b_val = baselines[ag] if baselines[ag] is not None else rew
                adv = coef * (rew - b_val)
                for x_vec, li, fi in tr:
                    gp, _ = _grad_logp(params, x_vec, li, fi)
                    ge = _grad_entropy(params, x_vec)
                    for k in grad:
                        grad[k] += adv * gp[k] + entropy_coef * ge[k]

        for ag in all_agents:
            if ag == "solver":
                rm = float(np.mean([r[ag][0] + lam_sol * float(r[ag][1]) for r in ep_rows]))
            elif ag == "logs_only":
                rm = float(np.mean([-r[ag][0] - lam_lo * float(r[ag][1]) for r in ep_rows]))
            else:
                rm = float(-np.mean([r[ag][0] for r in ep_rows]))
            baselines[ag] = rm if baselines[ag] is None else 0.8 * float(baselines[ag]) + 0.2 * rm

        step_num = it + 1
        b1_corr = 1.0 - 0.9 ** step_num
        b2_corr = 1.0 - 0.999 ** step_num
        for k in params:
            g_norm = grad[k] / max(1, len(ep_rows))
            m_opt[k] = 0.9 * m_opt[k] + 0.1 * g_norm
            v_opt[k] = 0.999 * v_opt[k] + 0.001 * (g_norm * g_norm)
            params[k] = params[k] + lr * (m_opt[k] / b1_corr) / (np.sqrt(v_opt[k] / b2_corr) + 1e-8)

        lam_sol = max(0.0, lam_sol + dual_lr * (min_solver_acc + safety_solver_acc_margin - sol_acc))
        lam_lo = max(0.0, lam_lo + dual_lr * (lo_acc - max(0.0, max_logs_acc - 0.025)))

        min_reg = sol_score - float(inv_means.max())
        mean_reg = sol_score - float(inv_means.mean())
        curve.append(
            {
                "iter": it,
                "solver_score": round(sol_score, 4),
                "solver_acc": round(sol_acc, 4),
                "logs_only_acc": round(lo_acc, 4),
                "min_regret": round(min_reg, 4),
                "mean_regret": round(mean_reg, 4),
                "lam_solver": round(lam_sol, 4),
                "lam_logs": round(lam_lo, 4),
                "elapsed_sec": round(time.time() - t0, 3),
            }
        )
        if it == iters - 1 or it % max(1, iters // 3) == 0:
            checkpoints.append((f"reinforce_it{it + 1}", round_params(params, decimals=8)))

    sel_base = _default_suite_baseline(
        tier=tier,
        seeds=sel_seed_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
    )
    scored_ckpts: list[tuple[bool, float, str, dict[str, np.ndarray], dict[str, Any]]] = []
    for label, cp_params in checkpoints:
        cp_pol = RLMole(cp_params, greedy=greedy_eval, name=name)
        eval_agents = ("solver", "logs_only", "accuse_most_logs", *FRONTIER_INVESTIGATORS)
        raw = {a: _run_agent_seeds(cp_pol, tier, sel_seed_list, a) for a in eval_agents}
        met = _summarize_suite_from_raw(
            raw,
            tier=tier,
            seeds=sel_seed_list,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            baseline=sel_base,
        )
        obj = _constrained_objective(met, safety_solver_acc_margin)
        beats_def = bool(met["feasible"] and met["min_regret_gain"] > 0.0 and met["core_min_regret_gain"] > 0.0)
        scored_ckpts.append((beats_def, obj, label, cp_params, met))

    scored_ckpts.sort(key=lambda item: (item[0], bool(item[4]["feasible"]), item[1]), reverse=True)
    _, best_obj, best_label, best_params, best_met = scored_ckpts[0]
    best_policy = RLMole.from_json(RLMole(best_params, greedy=greedy_eval, name=name).to_json())
    return {
        "method": "reinforce",
        "policy": best_policy,
        "params": copy.deepcopy(best_policy.p),
        "selected_source": best_label,
        "selected_objective": float(best_obj),
        "selection_metrics": best_met,
        "curve": curve,
    }


def selector_profile(
    policy: RLMole,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(210_000, 210_010),
    workers: int = 1,
) -> dict[str, Any]:
    validate_workers(workers)
    seed_list = validate_eval_seeds(seeds)
    leak_counts: Counter[str] = Counter()
    frame_counts: Counter[str] = Counter()
    probe_agents = ("solver", "gemini_carbon_proxy", "codex_horizon_proxy")
    for s in seed_list:
        for ag in probe_agents:
            tr: list[tuple[np.ndarray, int, int]] = []
            mole = RLMole(policy.p, greedy=policy.greedy, trace=tr, name=policy.name)
            run_episode(Env(tier, s, mole_strategy=mole), make_investigator(ag, tier, s))
            for _, li, fi in tr:
                leak_counts[LEAK_SELECTORS[li]] += 1
                frame_counts[FRAME_SELECTORS[fi]] += 1
    total = sum(leak_counts.values()) or 1
    return {
        "n_seeds": len(seed_list),
        "seed_range": f"{seed_list[0]}-{seed_list[-1]}",
        "total_decisions": int(sum(leak_counts.values())),
        "leak": {k: round(v / total, 4) for k, v in leak_counts.most_common()},
        "frame": {k: round(v / total, 4) for k, v in frame_counts.most_common()},
    }


def validate_distilled_mole(
    policy: str | Path | RLMole | dict[str, Any],
    tier: str = "hard",
    heldout_seeds: str | int | Iterable[int] = DEFAULT_HELDOUT_SEEDS,
    counterfactual_seeds: str | int | Iterable[int] = DEFAULT_COUNTERFACTUAL_SEEDS,
    teacher: str | MoleStrategy | dict[str, Any] = DEFAULT_TEACHER,
    bc_policy: RLMole | dict[str, Any] | None = None,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    workers: int = 1,
) -> dict[str, Any]:
    validate_workers(workers)
    heldout_list = validate_eval_seeds(heldout_seeds, base=210_000)
    cf_seed_list = normalize_seeds(counterfactual_seeds, base=0)

    coerced = coerce_mole_policy(policy)
    if not isinstance(coerced, RLMole):
        raise TypeError("validate_distilled_mole expects an RLMole policy (kind='rl_mole')")

    sj = coerced.to_json()
    from_rl = RLMole.from_json(json.loads(json.dumps(sj)))
    from_ft = _strategy(json.loads(json.dumps(sj)))
    if not isinstance(from_ft, RLMole):
        raise RuntimeError("policy failed forge_track._strategy validation")

    teacher_strat = resolve_teacher(teacher)

    heldout_default = evaluate_frontier_suite(
        DEFAULT_STRATEGY,
        tier=tier,
        seeds=heldout_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        workers=1,
    )
    heldout_teacher = evaluate_frontier_suite(
        teacher_strat,
        tier=tier,
        seeds=heldout_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        workers=1,
    )
    heldout_bc = (
        evaluate_frontier_suite(
            bc_policy,
            tier=tier,
            seeds=heldout_list,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            workers=1,
        )
        if bc_policy is not None
        else None
    )
    heldout_rl = evaluate_frontier_suite(
        from_rl,
        tier=tier,
        seeds=heldout_list,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        workers=1,
    )

    audit_heldout = audit_strategy(
        sj,
        tier=tier,
        seeds=heldout_list,
        min_solver_acc=min_solver_acc,
        min_solver_score=0.25,
        max_logs_acc=max_logs_acc,
    )

    cf_strategies: dict[str, MoleStrategy | RLMole] = {
        "default_v0": DEFAULT_STRATEGY,
        teacher_strat.name: teacher_strat,
    }
    if bc_policy is not None:
        bc_coerced = coerce_mole_policy(bc_policy)
        cf_strategies[bc_coerced.name] = bc_coerced
    cf_strategies[from_rl.name] = from_rl

    cf_raw = evaluate_counterfactual(
        strategies=cf_strategies,
        seeds=cf_seed_list,
        tier=tier,
        run_solver=True,
        sources=("opencode", "inproc"),
        workers=1,
        min_solver_acc=min_solver_acc,
    )
    cf_compact: dict[str, Any] = {
        "tier": cf_raw["tier"],
        "seed_range": f"{cf_raw['seeds'][0]}-{cf_raw['seeds'][-1]}",
        "n_seeds_per_source": len(cf_raw["seeds"]),
        "n_total_episodes": len(cf_raw["seeds"]) * len(cf_raw["sources"]),
        "sources": list(cf_raw["sources"]),
        "strategies": {},
    }
    for sname, srow in cf_raw["strategies"].items():
        comb = {k: v for k, v in srow["combined"].items() if k != "episodes"}
        per_src = {
            src: {k: v for k, v in d.items() if k != "episodes"}
            for src, d in srow["per_source"].items()
        }
        sol = {k: v for k, v in srow["solver"].items() if k != "episodes"} if srow["solver"] else None
        cf_compact["strategies"][sname] = {
            "combined": comb,
            "per_source": per_src,
            "solver": sol,
            "counterfactual_gap": srow["counterfactual_gap"],
            "counterfactual_gap_gain": srow["counterfactual_gap_gain"],
            "counterfactual_gap_by_source": srow["counterfactual_gap_by_source"],
        }

    prof = selector_profile(from_rl, tier=tier, seeds=heldout_list[: min(3, len(heldout_list))], workers=1)

    return {
        "policy_name": from_rl.name,
        "policy_kind": sj["kind"],
        "greedy": bool(from_rl.greedy),
        "hidden": int(from_rl.p["W1"].shape[1]),
        "tier": tier,
        "heldout_seed_range": f"{heldout_list[0]}-{heldout_list[-1]}",
        "n_heldout_seeds": len(heldout_list),
        "heldout": {
            "default_v0": heldout_default,
            "teacher": heldout_teacher,
            "bc_clone": heldout_bc,
            "refined": heldout_rl,
        },
        "fairness_audit": audit_heldout,
        "counterfactual_v14_hard": cf_compact,
        "selector_profile": prof,
        "all_gates_passed": bool(
            heldout_rl["feasible"]
            and audit_heldout["all_passed"]
            and cf_compact["strategies"][from_rl.name]["solver"]["feasible"]
        ),
    }


def canonical_rl_mole_sha256(policy: RLMole | dict[str, Any]) -> str:
    rl_pol = RLMole.from_json(policy) if isinstance(policy, dict) else RLMole.from_json(policy.to_json())
    round_params(rl_pol.p, decimals=8)
    canon = json.dumps(rl_pol.to_json(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _find_forbidden_secret_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in FORBIDDEN_SECRET_KEYS:
                return ks
            hit = _find_forbidden_secret_key(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for item in obj:
            hit = _find_forbidden_secret_key(item)
            if hit is not None:
                return hit
    return None


def _dumps_compact_json(obj: Any, indent: int = 2, _level: int = 0) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [
            f"{pad}{json.dumps(str(k))}: {_dumps_compact_json(obj[k], indent, _level + 1)}"
            for k in sorted(obj.keys(), key=str)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(obj, list):
        if not obj or all(not isinstance(v, (dict, list)) for v in obj):
            return json.dumps(obj, separators=(",", ":"))
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [f"{pad}{_dumps_compact_json(v, indent, _level + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


def build_distill_ledger(
    validation: dict[str, Any],
    bc_metrics: dict[str, Any] | None = None,
    refine_info: dict[str, Any] | None = None,
    policy_path: str = "data/forge/rl_mole_frontier_v14.json",
    train_config: dict[str, Any] | None = None,
    canonical_sha256: str | None = None,
) -> dict[str, Any]:
    refine_summary = (
        {
            "method": str(refine_info["method"]),
            "selected_source": str(refine_info["selected_source"]),
            "selected_objective": float(refine_info["selected_objective"]),
            "selection_metrics": copy.deepcopy(refine_info["selection_metrics"]),
            "curve": copy.deepcopy(refine_info["curve"]),
        }
        if refine_info is not None
        else None
    )
    fa_sha = str(validation["fairness_audit"]["checks"]["dsl_valid"]["canonical_sha256"])
    return {
        "schema_version": "distill_rl_mole_v14.v1",
        "policy_path": str(policy_path),
        "canonical_sha256": str(canonical_sha256 or fa_sha),
        "train_config": copy.deepcopy(train_config) if train_config is not None else None,
        "bc_metrics": copy.deepcopy(bc_metrics) if bc_metrics is not None else None,
        "refine_summary": refine_summary,
        "validation": copy.deepcopy(validation),
    }


def parse_embedded_ledger(md_text: str) -> dict[str, Any]:
    if LEDGER_START not in md_text or LEDGER_END not in md_text:
        raise ValueError("markdown report missing machine-verified ledger markers")
    start_idx = md_text.index(LEDGER_START) + len(LEDGER_START)
    end_idx = md_text.index(LEDGER_END, start_idx)
    block = md_text[start_idx:end_idx].strip()
    if not (block.startswith("```json") and block.endswith("```")):
        raise ValueError("markdown ledger block is not a fenced json block")
    inner = block[len("```json") : -len("```")].strip()
    parsed = json.loads(inner)
    if not isinstance(parsed, dict):
        raise ValueError("parsed markdown ledger is not a JSON object")
    return parsed


def assert_ledger_invariants(
    ledger: dict[str, Any],
    policy_obj: dict[str, Any] | None = None,
) -> None:
    if not isinstance(ledger, dict):
        raise ValueError("ledger must be a JSON object")
    bad_ledger_key = _find_forbidden_secret_key(ledger)
    if bad_ledger_key is not None:
        raise ValueError(f"forbidden secret key {bad_ledger_key!r} leaked in ledger")
    if ledger.get("schema_version") != "distill_rl_mole_v14.v1":
        raise ValueError(f"unexpected ledger schema_version {ledger.get('schema_version')!r}")

    validation = ledger.get("validation")
    if not isinstance(validation, dict):
        raise ValueError("ledger missing validation object")
    pname = str(validation.get("policy_name", ""))
    if not pname or validation.get("policy_kind") != "rl_mole":
        raise ValueError("validation must record policy_kind='rl_mole' and non-empty policy_name")
    hidden = int(validation.get("hidden", 0))
    if hidden <= 0:
        raise ValueError("validation hidden dimension must be positive")

    h_ref = validation.get("heldout", {}).get("refined")
    if not isinstance(h_ref, dict):
        raise ValueError("validation missing heldout.refined metrics")
    heldout_seeds = validate_eval_seeds(h_ref.get("seeds", []))
    if len(heldout_seeds) != int(validation.get("n_heldout_seeds", -1)) or len(heldout_seeds) != int(
        h_ref.get("n_seeds", -1)
    ):
        raise ValueError("held-out seed count mismatch in validation")
    expected_range = f"{heldout_seeds[0]}-{heldout_seeds[-1]}"
    if str(validation.get("heldout_seed_range")) != expected_range:
        raise ValueError(f"heldout_seed_range mismatch: {validation.get('heldout_seed_range')!r} != {expected_range!r}")

    tc = ledger.get("train_config")
    if tc is not None:
        if not isinstance(tc, dict):
            raise ValueError("train_config must be a dict when present")
        bc_s = validate_train_seeds(tc.get("bc_seeds", []))
        sel_s = validate_train_seeds(tc.get("select_seeds", []))
        t_base = int(tc.get("train_seed_base", -1))
        t_span = int(tc.get("iters", 0)) * int(tc.get("batch_size", 0))
        if t_span <= 0:
            raise ValueError("train_config iters * batch_size must be positive")
        ref_s = validate_train_seeds(range(t_base, t_base + t_span))
        if not (set(bc_s) | set(sel_s) | set(ref_s)).isdisjoint(heldout_seeds):
            raise ValueError("training and held-out seeds overlap")

    min_sol_acc = float(h_ref.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC))
    if min_sol_acc < 0.85:
        raise ValueError(f"solver catchability threshold {min_sol_acc} < 0.85")
    if float(h_ref.get("solver_acc", 0.0)) < min_sol_acc or h_ref.get("solver_passed") is not True:
        raise ValueError(f"solver catchability gate violated: solver_acc={h_ref.get('solver_acc')}")

    max_lo_acc = float(h_ref.get("max_logs_acc", DEFAULT_MAX_LOGS_ACC))
    if max_lo_acc > 0.10:
        raise ValueError(f"logs_only threshold {max_lo_acc} > 0.10")
    if float(h_ref.get("logs_only_acc", 1.0)) > max_lo_acc or float(h_ref.get("logs_only_score", 0.0)) >= 0.0:
        raise ValueError("logs_only gate violated")
    if (
        float(h_ref.get("accuse_most_logs_acc", 1.0)) > max_lo_acc
        or float(h_ref.get("accuse_most_logs_score", 0.0)) >= 0.0
    ):
        raise ValueError("accuse_most_logs gate violated")
    if float(h_ref.get("do_nothing_score", 1.0)) != 0.0 or float(h_ref.get("do_nothing_acc", 1.0)) != 0.0:
        raise ValueError("do_nothing zero-baseline gate violated")
    if h_ref.get("feasible") is not True:
        raise ValueError("held-out refined policy is not feasible")

    fa = validation.get("fairness_audit")
    if not isinstance(fa, dict) or fa.get("all_passed") is not True or fa.get("fairness_passed") is not True:
        raise ValueError("fairness_audit did not pass all 7 checks")
    if validate_eval_seeds(fa.get("seeds", [])) != heldout_seeds:
        raise ValueError("fairness_audit seeds do not match held-out seeds")
    for ck in CHECK_NAMES:
        if fa.get("checks", {}).get(ck, {}).get("passed") is not True:
            raise ValueError(f"fairness_audit check {ck!r} failed")

    fa_sha = str(fa["checks"]["dsl_valid"]["canonical_sha256"])
    if str(ledger.get("canonical_sha256")) != fa_sha:
        raise ValueError("canonical_sha256 mismatch between ledger and fairness_audit")

    cf_sol = (
        validation.get("counterfactual_v14_hard", {})
        .get("strategies", {})
        .get(pname, {})
        .get("solver")
    )
    if not isinstance(cf_sol, dict) or float(cf_sol.get("accuracy", 0.0)) < 0.85 or cf_sol.get("feasible") is not True:
        raise ValueError("counterfactual solver catchability gate violated")

    if validation.get("all_gates_passed") is not True:
        raise ValueError("validation.all_gates_passed is not True")

    if policy_obj is not None:
        if not isinstance(policy_obj, dict):
            raise ValueError("policy JSON must be an object")
        bad_pol_key = _find_forbidden_secret_key(policy_obj)
        if bad_pol_key is not None:
            raise ValueError(f"forbidden secret key {bad_pol_key!r} leaked in policy JSON")
        rl_pol = RLMole.from_json(policy_obj)
        ft_pol = _strategy(policy_obj)
        if not isinstance(ft_pol, RLMole):
            raise ValueError("forge_track._strategy did not return RLMole")
        round_params(rl_pol.p, decimals=8)
        if policy_obj != rl_pol.to_json():
            raise ValueError("policy JSON does not match canonical RLMole.to_json() representation")
        actual_sha = canonical_rl_mole_sha256(rl_pol)
        if actual_sha != fa_sha:
            raise ValueError(f"policy canonical_sha256 mismatch ({actual_sha} != {fa_sha})")
        if (
            rl_pol.name != pname
            or bool(rl_pol.greedy) != bool(validation.get("greedy"))
            or int(rl_pol.p["W1"].shape[1]) != hidden
        ):
            raise ValueError("policy metadata mismatch vs ledger validation")


def render_report_from_ledger(ledger: dict[str, Any]) -> str:
    validation = ledger["validation"]
    bc_metrics = ledger.get("bc_metrics")
    refine_info = ledger.get("refine_summary")
    policy_path = str(ledger.get("policy_path", "data/forge/rl_mole_frontier_v14.json"))
    train_config = ledger.get("train_config")

    h = validation["heldout"]
    h_def = h["default_v0"]
    h_tch = h["teacher"]
    h_bc = h["bc_clone"]
    h_ref = h["refined"]
    fa = validation["fairness_audit"]
    cf = validation["counterfactual_v14_hard"]
    prof = validation["selector_profile"]
    pname = validation["policy_name"]
    cf_ref = cf["strategies"][pname]
    cf_range = cf.get("seed_range", f"0-{cf['n_seeds_per_source'] - 1}")
    cf_n_src = int(cf["n_seeds_per_source"])
    cf_n_tot = int(cf["n_total_episodes"])
    prof_n = int(prof.get("n_seeds", validation["n_heldout_seeds"]))

    lines: list[str] = [
        f"{H1} Transcript-Distilled + Constrained Frontier RLMole (`rl_mole_frontier_v14`)",
        "",
        f"{H2} 1. Executive Summary",
        "",
        f"- **Artifact**: `{policy_path}` (`kind=\"rl_mole\"`, `name=\"{pname}\"`, `hidden={validation['hidden']}`, `greedy={validation['greedy']}`, loadable via `RLMole.from_json` and `canary.forge_track._strategy`).",
        f"- **Execution Discipline**: CPU-only `numpy`, strict `--workers 1`, `0` API calls, training seeds strictly in `110000+` (`TRAIN_SEEDS`), disjoint fresh held-out validation on `{validation['heldout_seed_range']}` (`n={validation['n_heldout_seeds']}`, strictly avoiding `0-59`, `30000-30199`, `800000+`, `900000+`), and counterfactual replay on `{cf_n_tot}` committed v1.4 Gemini-4-carbon Hard episodes (`{cf_n_src}` OpenCode MCP + `{cf_n_src}` in-proc, seeds `{cf_range}`).",
        f"- **Held-Out Frontier Regret (`{validation['heldout_seed_range']}`, `n={validation['n_heldout_seeds']}`)**: `SolverPolicy` accuracy `{h_ref['solver_acc'] * 100:.1f}%` (gate `>= 85.0%`), `SolverPolicy` score `{h_ref['solver_score']:.4f} +/- {h_ref['solver_ci']:.4f}`, `LogsOnly` accuracy `{h_ref['logs_only_acc'] * 100:.1f}%` (gate `<= 10.0%`), `DoNothing` score `{h_ref.get('do_nothing_score', 0.0):.3f}` (gate `== 0.000`), 5-investigator worst-case `min_regret = {h_ref['min_regret']:+.4f}` (`{h_ref['min_regret_gain']:+.4f}` vs `default_v0`, `{h_ref['min_regret'] - h_tch['min_regret']:+.4f}` vs `frontier_synthesis_v14`), `mean_regret = {h_ref['mean_regret']:+.4f}` (`{h_ref['mean_regret_gain']:+.4f}` vs `default_v0`).",
        f"- **7-Check `canary.mole.fairness_audit`**: `{sum(1 for k in CHECK_NAMES if fa['checks'][k]['passed'])}/7` checks passed (`all_passed={fa['all_passed']}`, `fairness_passed={fa['fairness_passed']}`, `canonical_sha256={fa['checks']['dsl_valid']['canonical_sha256']}`).",
        f"- **Counterfactual {cf_n_tot} Committed v1.4 Gemini Hard Episodes (`{cf_n_src}` OpenCode + `{cf_n_src}` in-proc, seeds `{cf_range}`)**: Posterior `P(true mole)` at accuse day drops by `{cf_ref['combined']['p_true_mole_drop']:+.4f}` (from `{cf['strategies']['default_v0']['combined']['p_true_mole']:.4f}` to `{cf_ref['combined']['p_true_mole']:.4f}`), optimal Bayesian accuse EV drops by `{cf_ref['combined']['optimal_ev_drop']:+.4f}`, and counterfactual Solver-vs-Gemini gap rises to `{cf_ref['counterfactual_gap']:+.4f}` (`{cf_ref['counterfactual_gap_gain']:+.4f}` gain over `default_v0`) while `SolverPolicy` retains `{cf_ref['solver']['accuracy'] * 100:.1f}%` accuracy (`{cf_ref['solver']['score']:+.4f}` score).",
        "",
        f"{H2} 2. Two-Stage Training Pipeline (0 API Calls, `--workers 1`, Seeds `110000+`)",
        "",
    ]

    if bc_metrics is not None:
        lines.extend(
            [
                f"{H3} 2.1 Stage 1: Behavioral Cloning of `frontier_synthesis_v14` over `MoleView` States",
                "",
                f"- **Teacher Strategy**: `{bc_metrics['teacher']}` (`canary.mole.strategies`)",
                f"- **Rollout Seed Slice**: `{bc_metrics['seed_range']}` (`n={bc_metrics['n_seeds']}` seeds, `{bc_metrics['n_rollout_views']}` rollout `MoleView` states + `{bc_metrics['n_boundary_views']}` boundary states -> `{bc_metrics['n_unique_states']}` unique weighted feature-label tuples)",
                f"- **MLP Architecture**: `11 -> {bc_metrics['hidden']} (tanh) -> (6 leak logits, 4 frame logits)` (`RLMole` exact schema)",
                f"- **Cloning Fidelity on Empirical `MoleView` Rollouts**: leak selector accuracy `{bc_metrics['leak_acc'] * 100:.2f}%`, frame selector accuracy `{bc_metrics['frame_acc'] * 100:.2f}%`, joint `(leak, frame)` exact match `{bc_metrics['joint_acc'] * 100:.2f}%`, cross-entropy `{bc_metrics['cross_entropy']:.4f}` (`{bc_metrics['elapsed_sec']:.2f}s`)",
                "",
            ]
        )

    if refine_info is not None:
        sel = refine_info["selection_metrics"]
        lines.extend(
            [
                f"{H3} 2.2 Stage 2: Constrained Single-Process `{refine_info['method'].upper()}` Refinement",
                "",
                "- **Investigator Adversary Suite**: `GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`, `HintedHeuristic`, `Heuristic`",
                f"- **Hard Constraints**: `SolverPolicy acc >= {sel['min_solver_acc']:.2f}`, `LogsOnly acc <= {sel['max_logs_acc']:.2f}`, `AccuseMostLogs acc <= {sel['max_logs_acc']:.2f}`, `DoNothing == 0.00`, `SolverPolicy score >= {sel['min_solver_ratio']:.2f} * baseline_solver_score`",
                f"- **Train-Selection Checkpoint (`{sel['seeds'][0]}-{sel['seeds'][-1]}`, `n={sel['n_seeds']}`)**: selected `{refine_info['selected_source']}` with `objective={refine_info['selected_objective']:+.4f}`, `solver_acc={sel['solver_acc'] * 100:.1f}%`, `solver_score={sel['solver_score']:+.4f}`, `logs_only_acc={sel['logs_only_acc'] * 100:.1f}%`, `min_regret={sel['min_regret']:+.4f}` (`{sel['min_regret_gain']:+.4f}` vs `default_v0`), `mean_regret={sel['mean_regret']:+.4f}`",
                "",
                "| Iter | Feasible | Objective | Solver Score | Solver Acc | LogsOnly Acc | Min Regret | Mean Regret | Elapsed (s) |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in refine_info["curve"]:
            lines.append(
                f"| {row['iter']} | {row.get('feasible', True)} | {row.get('objective', row['min_regret']):+.4f} | "
                f"{row['solver_score']:+.4f} | {row['solver_acc'] * 100:.1f}% | {row['logs_only_acc'] * 100:.1f}% | "
                f"{row['min_regret']:+.4f} | {row['mean_regret']:+.4f} | {row['elapsed_sec']:.2f} |"
            )
        lines.append("")

    lines.extend(
        [
            f"{H2} 3. Held-Out Validation on Seeds `{validation['heldout_seed_range']}` (`n={validation['n_heldout_seeds']}`, `--workers 1`)",
            "",
            f"{H3} 3.1 Summary Across Mole Policies",
            "",
            "| Mole Policy | Kind | Solver Score +/- CI | Solver Acc | LogsOnly Acc | AccuseMostLogs Acc | DoNothing | Strongest Investigator | Min Regret (Gain) | Mean Regret (Gain) | Frontier Proxy Regret | Feasible |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    summary_rows = [("default_v0", h_def), (h_tch["name"], h_tch)]
    if h_bc is not None:
        summary_rows.append((h_bc["name"], h_bc))
    summary_rows.append((h_ref["name"], h_ref))
    for label, row in summary_rows:
        lines.append(
            f"| `{label}` | `{row['kind']}` | {row['solver_score']:+.4f} +/- {row['solver_ci']:.4f} | "
            f"{row['solver_acc'] * 100:.1f}% | {row['logs_only_acc'] * 100:.1f}% | "
            f"{row['accuse_most_logs_acc'] * 100:.1f}% | {row.get('do_nothing_score', 0.0):.3f} | `{row['strongest_investigator']}` | "
            f"{row['min_regret']:+.4f} ({row['min_regret_gain']:+.4f}) | "
            f"{row['mean_regret']:+.4f} ({row['mean_regret_gain']:+.4f}) | "
            f"{row['frontier_proxy_regret']:+.4f} | {'PASS' if row['feasible'] else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            f"{H3} 3.2 Per-Investigator Breakdown on Held-Out Seeds `{validation['heldout_seed_range']}` (`n={validation['n_heldout_seeds']}`)",
            "",
            "| Investigator | `default_v0` Score (Acc) | `frontier_synthesis_v14` Score (Acc) | "
            + ("`rl_mole_bc_v14` Score (Acc) | " if h_bc is not None else "")
            + f"`{pname}` Score (Acc) | `{pname}` Regret +/- CI |",
            "|---|---|---|---|" + ("---|" if h_bc is not None else "") + "---|",
        ]
    )
    for inv in FRONTIER_INVESTIGATORS:
        d_i = h_def["per_investigator"][inv]
        t_i = h_tch["per_investigator"][inv]
        r_i = h_ref["per_investigator"][inv]
        bc_col = ""
        if h_bc is not None:
            b_i = h_bc["per_investigator"][inv]
            bc_col = f"{b_i['score']:+.4f} ({b_i['acc'] * 100:.1f}%) | "
        lines.append(
            f"| `{inv}` | {d_i['score']:+.4f} ({d_i['acc'] * 100:.1f}%) | "
            f"{t_i['score']:+.4f} ({t_i['acc'] * 100:.1f}%) | "
            f"{bc_col}"
            f"{r_i['score']:+.4f} ({r_i['acc'] * 100:.1f}%) | "
            f"{r_i['regret']:+.4f} +/- {r_i['regret_ci']:.4f} |"
        )

    leak_items = sorted(prof["leak"].items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    frame_items = sorted(prof["frame"].items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    leak_str = ", ".join(f"`{k}`: {v * 100:.1f}%" for k, v in leak_items)
    frame_str = ", ".join(f"`{k}`: {v * 100:.1f}%" for k, v in frame_items)
    lines.extend(
        [
            "",
            f"{H3} 3.3 Learned Selector Profile (`n={prof_n}` Held-Out Seeds Across Solver + Frontier Proxies)",
            "",
            f"- **Total Mole Decisions Sampled**: `{prof['total_decisions']}`",
            f"- **Leak Selector Shares**: {leak_str}",
            f"- **Frame Selector Shares**: {frame_str}",
            "",
            f"{H2} 4. 7-Check `canary.mole.fairness_audit` Verification",
            "",
            "| Check | Status | Details |",
            "|---|---|---|",
        ]
    )
    for ck in CHECK_NAMES:
        info = fa["checks"][ck]
        lines.append(f"| `{ck}` | {'PASS' if info['passed'] else 'FAIL'} | {info['summary']} |")

    lines.extend(
        [
            "",
            f"{H2} 5. Counterfactual Replay on {cf_n_tot} Committed v1.4 Gemini-4-Carbon Hard Episodes",
            "",
            f"Evaluated via `canary.mole.counterfactual.evaluate_counterfactual` across `opencode-gemini-4-carbon` (`n={cf_n_src}`, seeds `{cf_range}`) and `inproc-gemini-4-carbon` (`n={cf_n_src}`, seeds `{cf_range}`) paired with live `SolverPolicy(\"hard\")` on the same `{cf_n_src}` worlds (`--workers 1`, `0` API calls).",
            "",
            "| Strategy | Combined `P(mole)` Acc/Hor | `P(mole)` Drop | Combined Opt EV | Opt EV Drop | OpenCode Opt EV (Drop) | In-Proc Opt EV (Drop) | Surfaced Canaries / Leaks | Live Solver Score (Acc) | CF Gap (Gain vs Default) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    cf_order = ["default_v0", h_tch["name"]]
    if h_bc is not None:
        cf_order.append(h_bc["name"])
    cf_order.append(pname)
    ordered_cf_names = [k for k in cf_order if k in cf["strategies"]] + [
        k for k in sorted(cf["strategies"]) if k not in cf_order
    ]
    for sname in ordered_cf_names:
        srow = cf["strategies"][sname]
        comb = srow["combined"]
        oc = srow["per_source"]["opencode"]
        ip = srow["per_source"]["inproc"]
        sol = srow["solver"]
        lines.append(
            f"| `{sname}` | {comb['p_true_mole']:.3f} / {comb['p_true_mole_horizon']:.3f} | "
            f"{comb['p_true_mole_drop']:+.3f} | {comb['optimal_ev']:.3f} | {comb['optimal_ev_drop']:+.3f} | "
            f"{oc['optimal_ev']:.3f} ({oc['optimal_ev_drop']:+.3f}) | "
            f"{ip['optimal_ev']:.3f} ({ip['optimal_ev_drop']:+.3f}) | "
            f"{comb['surfaced_canaries']:.2f} / {comb['surfaced_total_leaks']:.2f} | "
            f"{sol['score']:+.3f} ({sol['accuracy'] * 100:.1f}%) | "
            f"{srow['counterfactual_gap']:+.3f} ({srow['counterfactual_gap_gain']:+.3f}) |"
        )

    tc = train_config or {}
    t_method = tc.get("method", "cem")
    t_teacher = tc.get("teacher", "frontier_synthesis_v14")
    t_bc_seeds = tc.get("bc_seeds", bc_metrics["seed_range"] if bc_metrics else "110000-110002")
    t_sel_seeds = tc.get(
        "select_seeds",
        f"{refine_info['selection_metrics']['seeds'][0]}-{refine_info['selection_metrics']['seeds'][-1]}"
        if refine_info
        else "110510-110516",
    )
    t_base = tc.get("train_seed_base", DEFAULT_REFINE_SEED_BASE)
    t_iters = tc.get("iters", 1)
    t_pop = tc.get("pop_size", 2)
    t_batch = tc.get("batch_size", 7)
    t_epochs = tc.get("bc_epochs", 450)
    t_hidden = tc.get("hidden", validation["hidden"])
    t_seed = tc.get("seed", 42)

    lines.extend(
        [
            "",
            f"{H2} 6. Exact Reproduction Commands",
            "",
            "```bash",
            "python -m canary.mole.distill_rl_mole train \\",
            f"  --teacher {t_teacher} --method {t_method} --workers 1 \\",
            f"  --bc-seeds {t_bc_seeds} --train-seed-base {t_base} --select-seeds {t_sel_seeds} \\",
            f"  --heldout-seeds {validation['heldout_seed_range']} --cf-seeds {cf_range} \\",
            f"  --hidden {t_hidden} --bc-epochs {t_epochs} --iters {t_iters} --pop-size {t_pop} --batch-size {t_batch} --seed {t_seed} \\",
            f"  --out {policy_path} \\",
            "  --report docs/reports/rl_mole_frontier_v14.md",
            "",
            "python -m canary.mole.distill_rl_mole --check \\",
            f"  --policy {policy_path} \\",
            "  --report docs/reports/rl_mole_frontier_v14.md",
            "",
            "python -m canary.mole.fairness_audit \\",
            f"  --strategy {policy_path} \\",
            f"  --tier {validation['tier']} --seeds {validation['heldout_seed_range']} --min-solver-acc 0.85 --max-logs-acc 0.10",
            "",
            "python -m canary.mole.counterfactual \\",
            f"  --strategy-file {policy_path} \\",
            f"  --tier {validation['tier']} --seeds {cf_range} --sources opencode,inproc --workers 1 --min-solver-acc 0.85",
            "```",
            "",
            f"{H2} 7. Machine-Verified Summary Ledger",
            "",
            LEDGER_START,
            "```json",
            _dumps_compact_json(ledger),
            "```",
            LEDGER_END,
            "",
        ]
    )
    rendered = "\n".join(lines)
    if EM_DASH in rendered or EN_DASH in rendered:
        raise ValueError("rendered markdown contains forbidden em/en dash characters")
    return rendered


def format_markdown_report(
    validation: dict[str, Any],
    bc_metrics: dict[str, Any] | None = None,
    refine_info: dict[str, Any] | None = None,
    policy_path: str = "data/forge/rl_mole_frontier_v14.json",
    train_config: dict[str, Any] | None = None,
) -> str:
    ledger = build_distill_ledger(
        validation=validation,
        bc_metrics=bc_metrics,
        refine_info=refine_info,
        policy_path=policy_path,
        train_config=train_config,
    )
    normalized = json.loads(_dumps_compact_json(ledger))
    return render_report_from_ledger(normalized)


def check_distilled_artifacts(
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    report_path: str | Path = DEFAULT_REPORT_PATH,
) -> tuple[bool, str]:
    p_fp = Path(policy_path)
    r_fp = Path(report_path)
    if not p_fp.is_file():
        return False, f"FAIL: missing policy JSON artifact: {p_fp}"
    if not r_fp.is_file():
        return False, f"FAIL: missing Markdown report: {r_fp}"

    p_bytes = p_fp.stat().st_size
    if p_bytes >= MAX_POLICY_JSON_BYTES:
        return False, f"FAIL: policy JSON {p_fp} exceeds {MAX_POLICY_JSON_BYTES} byte limit ({p_bytes} bytes)"

    p_text = p_fp.read_text(encoding="utf-8")
    r_text = r_fp.read_text(encoding="utf-8")

    coauthor_tag = "co-authored-" + "by"
    for fp, txt in ((p_fp, p_text), (r_fp, r_text)):
        if EM_DASH in txt or EN_DASH in txt or UNICODE_MINUS in txt:
            return False, f"FAIL: forbidden em/en dash or unicode minus found in {fp}"
        if coauthor_tag in txt.lower():
            return False, f"FAIL: forbidden {coauthor_tag} trailer found in {fp}"
        for rx in SECRET_KEY_PATTERNS:
            if rx.search(txt):
                return False, f"FAIL: raw API key pattern detected in {fp}"

    r_lower = r_text.lower()
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    if flash_tag in r_lower:
        return False, f"FAIL: forbidden {flash_tag} claim found in {r_fp}"
    if solver_pct_tag in r_lower or FORBIDDEN_GAP_RE.search(r_text) is not None:
        return False, f"FAIL: forbidden {solver_pct_tag} ratio claim found in {r_fp}"

    try:
        policy_obj = json.loads(p_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {p_fp}: {exc}"
    if not isinstance(policy_obj, dict):
        return False, f"FAIL: expected JSON object in {p_fp}"

    try:
        ledger = parse_embedded_ledger(r_text)
        assert_ledger_invariants(ledger, policy_obj=policy_obj)
        expected_md = render_report_from_ledger(ledger)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return False, f"FAIL: verification error: {exc}"

    if r_text != expected_md:
        return False, f"FAIL: Markdown report {r_fp} does not match embedded ledger and {p_fp}"

    return (
        True,
        f"OK: {p_fp.name} (sha256={ledger['canonical_sha256']}, {p_bytes} bytes, "
        f"n={ledger['validation']['n_heldout_seeds']} held-out seeds) matches {r_fp.name}",
    )


def train_and_validate(
    teacher: str = DEFAULT_TEACHER,
    method: str = "cem",
    tier: str = "hard",
    bc_seeds: str | int | Iterable[int] = DEFAULT_BC_SEEDS,
    train_seed_base: int = DEFAULT_REFINE_SEED_BASE,
    select_seeds: str | int | Iterable[int] = DEFAULT_SELECT_SEEDS,
    heldout_seeds: str | int | Iterable[int] = DEFAULT_HELDOUT_SEEDS,
    counterfactual_seeds: str | int | Iterable[int] = DEFAULT_COUNTERFACTUAL_SEEDS,
    hidden: int = 20,
    bc_epochs: int = 450,
    iters: int = 1,
    pop_size: int = 2,
    batch_size: int = 7,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    seed: int = 42,
    workers: int = 1,
    out_path: str | Path | None = DEFAULT_POLICY_PATH,
    report_path: str | Path | None = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    validate_workers(workers)
    bc_seed_list = validate_train_seeds(bc_seeds)
    sel_seed_list = validate_train_seeds(select_seeds)
    ref_seed_list = validate_train_seeds(range(int(train_seed_base), int(train_seed_base) + int(iters) * int(batch_size)))
    heldout_list = validate_eval_seeds(heldout_seeds, base=210_000)
    all_train_used = set(bc_seed_list) | set(sel_seed_list) | set(ref_seed_list)
    if not all_train_used.isdisjoint(heldout_list):
        raise ValueError("held-out evaluation seeds must be strictly disjoint from all training seeds")

    bc_res = clone_strategy_to_rl_mole(
        teacher=teacher,
        tier=tier,
        seeds=bc_seed_list,
        hidden=hidden,
        epochs=bc_epochs,
        seed=seed,
        greedy=True,
        name="rl_mole_bc_v14",
        workers=1,
    )
    bc_pol: RLMole = bc_res["policy"]

    if method == "cem":
        ref_res = refine_constrained_cem(
            init_params=bc_res["params"],
            tier=tier,
            iters=iters,
            pop_size=pop_size,
            batch_size=batch_size,
            train_seed_base=train_seed_base,
            select_seeds=sel_seed_list,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            greedy=True,
            seed=seed,
            workers=1,
            name="rl_mole_frontier_v14",
        )
    elif method == "reinforce":
        ref_res = refine_constrained_reinforce(
            init_params=bc_res["params"],
            tier=tier,
            iters=iters,
            batch_size=batch_size,
            train_seed_base=train_seed_base,
            select_seeds=sel_seed_list,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            greedy_eval=True,
            seed=seed,
            workers=1,
            name="rl_mole_frontier_v14",
        )
    else:
        raise ValueError(f"unknown refinement method {method!r}; expected 'cem' or 'reinforce'")

    final_pol: RLMole = ref_res["policy"]
    policy_json = final_pol.to_json()

    if out_path is not None:
        out_fp = Path(out_path)
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        out_fp.write_text(json.dumps(policy_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rel_out = str(out_fp)
    else:
        rel_out = "data/forge/rl_mole_frontier_v14.json"

    val_res = validate_distilled_mole(
        policy=final_pol,
        tier=tier,
        heldout_seeds=heldout_list,
        counterfactual_seeds=counterfactual_seeds,
        teacher=teacher,
        bc_policy=bc_pol,
        min_solver_acc=min_solver_acc,
        max_logs_acc=max_logs_acc,
        min_solver_ratio=min_solver_ratio,
        workers=1,
    )

    display_path = rel_out
    try:
        display_path = str(Path(rel_out).resolve().relative_to(ROOT))
    except ValueError:
        pass

    train_cfg = {
        "teacher": teacher if isinstance(teacher, str) else getattr(teacher, "name", DEFAULT_TEACHER),
        "method": method,
        "bc_seeds": f"{bc_seed_list[0]}-{bc_seed_list[-1]}",
        "train_seed_base": int(train_seed_base),
        "select_seeds": f"{sel_seed_list[0]}-{sel_seed_list[-1]}",
        "hidden": int(hidden),
        "bc_epochs": int(bc_epochs),
        "iters": int(iters),
        "pop_size": int(pop_size),
        "batch_size": int(batch_size),
        "seed": int(seed),
    }

    md = format_markdown_report(
        validation=val_res,
        bc_metrics=bc_res["bc_metrics"],
        refine_info=ref_res,
        policy_path=display_path,
        train_config=train_cfg,
    )
    if report_path is not None:
        rep_fp = Path(report_path)
        rep_fp.parent.mkdir(parents=True, exist_ok=True)
        rep_fp.write_text(md, encoding="utf-8")

    return {
        "policy": final_pol,
        "policy_json": policy_json,
        "bc": bc_res,
        "refinement": ref_res,
        "validation": val_res,
        "markdown": md,
    }


def _display_policy_path(raw_path: str | Path) -> str:
    s = str(raw_path)
    try:
        return str(Path(raw_path).resolve().relative_to(ROOT))
    except ValueError:
        return s


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.distill_rl_mole")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--policy", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--report-out", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=False)

    tr = sub.add_parser("train")
    tr.add_argument("--teacher", default=DEFAULT_TEACHER)
    tr.add_argument("--method", choices=("cem", "reinforce"), default="cem")
    tr.add_argument("--tier", default="hard", choices=sorted(TIERS))
    tr.add_argument("--bc-seeds", default="110000-110002")
    tr.add_argument("--train-seed-base", type=int, default=DEFAULT_REFINE_SEED_BASE)
    tr.add_argument("--select-seeds", default="110510-110516")
    tr.add_argument("--heldout-seeds", default="210020-210026")
    tr.add_argument("--cf-seeds", default="0-3")
    tr.add_argument("--hidden", type=int, default=20)
    tr.add_argument("--bc-epochs", type=int, default=450)
    tr.add_argument("--iters", type=int, default=1)
    tr.add_argument("--pop-size", type=int, default=2)
    tr.add_argument("--batch-size", type=int, default=7)
    tr.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    tr.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    tr.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    tr.add_argument("--seed", type=int, default=42)
    tr.add_argument("--workers", type=int, default=1)
    tr.add_argument("--out", type=Path, default=DEFAULT_POLICY_PATH)
    tr.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    tr.add_argument("--json", action="store_true")

    ev = sub.add_parser("eval")
    ev.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    ev.add_argument("--teacher", default=DEFAULT_TEACHER)
    ev.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ev.add_argument("--heldout-seeds", default="210020-210026")
    ev.add_argument("--cf-seeds", default="0-3")
    ev.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ev.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ev.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ev.add_argument("--workers", type=int, default=1)
    ev.add_argument("--report", type=Path, default=None)
    ev.add_argument("--json", action="store_true")

    ck = sub.add_parser("check")
    ck.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    ck.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)

    args = ap.parse_args(argv)

    if args.check or args.cmd == "check":
        p_path = args.policy or args.out or DEFAULT_POLICY_PATH
        r_path = args.report or args.report_out or DEFAULT_REPORT_PATH
        ok, msg = check_distilled_artifacts(policy_path=p_path, report_path=r_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if args.cmd is None:
        ap.error("specify a subcommand (train, eval, check) or --check")

    validate_workers(args.workers)

    if args.cmd == "train":
        bundle = train_and_validate(
            teacher=args.teacher,
            method=args.method,
            tier=args.tier,
            bc_seeds=args.bc_seeds,
            train_seed_base=args.train_seed_base,
            select_seeds=args.select_seeds,
            heldout_seeds=args.heldout_seeds,
            counterfactual_seeds=args.cf_seeds,
            hidden=args.hidden,
            bc_epochs=args.bc_epochs,
            iters=args.iters,
            pop_size=args.pop_size,
            batch_size=args.batch_size,
            min_solver_acc=args.min_solver_acc,
            max_logs_acc=args.max_logs_acc,
            min_solver_ratio=args.min_solver_ratio,
            seed=args.seed,
            workers=args.workers,
            out_path=args.out,
            report_path=args.report,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "bc_metrics": bundle["bc"]["bc_metrics"],
                        "selected_source": bundle["refinement"]["selected_source"],
                        "selected_objective": bundle["refinement"]["selected_objective"],
                        "all_gates_passed": bundle["validation"]["all_gates_passed"],
                        "heldout_refined": bundle["validation"]["heldout"]["refined"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(bundle["markdown"])
        return 0 if bundle["validation"]["all_gates_passed"] else 1

    val = validate_distilled_mole(
        policy=args.policy,
        tier=args.tier,
        heldout_seeds=args.heldout_seeds,
        counterfactual_seeds=args.cf_seeds,
        teacher=args.teacher,
        bc_policy=None,
        min_solver_acc=args.min_solver_acc,
        max_logs_acc=args.max_logs_acc,
        min_solver_ratio=args.min_solver_ratio,
        workers=args.workers,
    )
    disp_pol = _display_policy_path(args.policy)
    if args.report is not None:
        md = format_markdown_report(validation=val, policy_path=disp_pol)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md, encoding="utf-8")
    if args.json:
        print(json.dumps(val, indent=2, sort_keys=True))
    else:
        print(format_markdown_report(validation=val, policy_path=disp_pol))
    return 0 if val["all_gates_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
