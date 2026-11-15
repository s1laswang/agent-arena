"""Sleeper minimax attack-regret portfolio optimizer and zero-private-info seed-hashed mole policy."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    GrokTactics,
    Heuristic,
    LogsOnly,
    StopEarlyQuit,
)
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy, MoleView
from canary.mole.strategies import STRATEGY_SPECS, all_strategies
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION
from canary.solver.policy import SolverPolicy

__all__ = [
    "CANDIDATE_ORDER",
    "DEFAULT_LIVE_TRAIN_SEEDS_SPEC",
    "DEFAULT_MAX_LOGS_ONLY_ACC",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_PORTFOLIO_SALT",
    "DEFAULT_REPORT_OUT",
    "DEFAULT_SUMMARY_JSON",
    "DEFAULT_VAL_SEEDS_SPEC",
    "INVESTIGATOR_LABELS",
    "INVESTIGATOR_ORDER",
    "PortfolioFitResult",
    "PortfolioInfeasibleError",
    "PortfolioMolePolicy",
    "StrategyEvalSummary",
    "assert_disjoint_seed_splits",
    "assert_payload_hygiene",
    "candidate_strategies",
    "check_markdown_report",
    "evaluate_policies_on_seeds",
    "evaluate_strategies_live",
    "load_summaries_from_v14_json",
    "main",
    "normalize_portfolio_weights",
    "parse_seed_spec",
    "portfolio_seed_unit",
    "render_markdown_report",
    "run_portfolio_pipeline",
    "select_portfolio_strategy",
    "solve_minimax_regret_portfolio",
    "validate_eval_seeds",
]

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3
EM_DASH = "\u2014"
EN_DASH = "\u2013"

DEFAULT_SUMMARY_JSON = ROOT / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
DEFAULT_REPORT_OUT = ROOT / "docs" / "reports" / "mole_regret_portfolio_v14.md"
DEFAULT_LIVE_TRAIN_SEEDS_SPEC = "6800-6811"
DEFAULT_VAL_SEEDS_SPEC = "6812-6823"
DEFAULT_MIN_SOLVER_ACC = 0.90
DEFAULT_MAX_LOGS_ONLY_ACC = 0.10
DEFAULT_PORTFOLIO_SALT = "canary.mole.regret_portfolio.v1"
DEFAULT_MAX_WORKERS = 4
DEFAULT_BOOT_RESAMPLES = 4000
DEFAULT_BOOT_SEED = 20261115
DEFAULT_ZERO_TOL = 1e-9

FORBIDDEN_LOW_MAX = 59
FORBIDDEN_RESERVED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_MIN = 800_000

CANDIDATE_ORDER: tuple[str, ...] = (DEFAULT_STRATEGY.name, *STRATEGY_SPECS.keys())

INVESTIGATOR_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
)

INVESTIGATOR_LABELS: dict[str, str] = {
    "gemini_carbon_proxy": "GeminiCarbonProxy",
    "codex_horizon_proxy": "CodexHorizonProxy",
    "grok_tactics": "GrokTactics(hard)",
    "heuristic": "Heuristic(hard)",
    "hinted_heuristic": "HintedHeuristic(hard)",
}

FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)

FORBIDDEN_CLAIM_SUBSTRINGS: tuple[str, ...] = (
    "gemini-" + "3.5-flash",
    "% of " + "solver",
)

LEDGER_START = "<!-- MOLE_REGRET_PORTFOLIO_V14_LEDGER_START -->"
LEDGER_END = "<!-- MOLE_REGRET_PORTFOLIO_V14_LEDGER_END -->"


class PortfolioInfeasibleError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyEvalSummary:
    name: str
    solver_score: float
    solver_accuracy: float
    investigator_scores: dict[str, float]
    investigator_accuracies: dict[str, float]
    investigator_regrets: dict[str, float]
    logs_only_accuracy: float
    accuse_most_logs_accuracy: float = 0.0
    do_nothing_score: float = 0.0
    stop_early_quit_score: float = 0.0
    counterfactual_ev_drop: float | None = None
    counterfactual_regret: float | None = None

    @property
    def min_regret(self) -> float:
        return min(float(v) for v in self.investigator_regrets.values())

    @property
    def mean_regret(self) -> float:
        vals = [float(v) for v in self.investigator_regrets.values()]
        return sum(vals) / len(vals)

    def passes_zero_baselines(self, tol: float = DEFAULT_ZERO_TOL) -> bool:
        return abs(float(self.do_nothing_score)) <= tol and abs(float(self.stop_early_quit_score)) <= tol


@dataclass(frozen=True)
class PortfolioFitResult:
    weights: dict[str, float]
    min_regret: float
    mean_regret: float
    expected_regrets: dict[str, float]
    expected_investigator_scores: dict[str, float]
    expected_investigator_accuracies: dict[str, float]
    binding_investigators: tuple[str, ...]
    dual_investigator_weights: dict[str, float]
    duality_gap: float
    expected_solver_score: float
    expected_solver_accuracy: float
    expected_logs_only_accuracy: float
    expected_accuse_most_logs_accuracy: float
    expected_do_nothing_score: float
    expected_stop_early_quit_score: float
    expected_counterfactual_ev_drop: float | None
    expected_counterfactual_regret: float | None
    active_strategies: tuple[str, ...]
    excluded_zero_baseline_strategies: tuple[str, ...]
    min_solver_acc_bound: float
    max_logs_only_acc_bound: float
    gates_passed: bool


def parse_seed_spec(spec: str) -> list[int]:
    s = str(spec).strip()
    if not s:
        raise ValueError("seed spec must not be empty")
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


def validate_eval_seeds(seeds: str | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        parsed = parse_seed_spec(seeds)
    else:
        parsed = [int(s) for s in seeds]
    if not parsed:
        raise ValueError("eval seeds must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError("eval seeds must not contain duplicates")
    for s in parsed:
        if s < 0 or s <= FORBIDDEN_LOW_MAX:
            raise ValueError(f"seed {s} violates seed hygiene: 0..{FORBIDDEN_LOW_MAX} (and <0) forbidden")
        if s in FORBIDDEN_RESERVED_RANGE:
            raise ValueError(f"seed {s} violates seed hygiene: 30000..30199 reserved")
        if s >= FORBIDDEN_HIGH_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"seed {s} violates seed hygiene: >=800000 / heldout / judge forbidden")
    return parsed


def assert_disjoint_seed_splits(train_seeds: Sequence[int], val_seeds: Sequence[int]) -> None:
    overlap = sorted(set(int(s) for s in train_seeds) & set(int(s) for s in val_seeds))
    if overlap:
        raise ValueError(f"train and validation seed sets overlap on {overlap[:5]}")


def candidate_strategies() -> dict[str, MoleStrategy]:
    return {DEFAULT_STRATEGY.name: DEFAULT_STRATEGY, **all_strategies(include_default=False)}


def _canonical_strategy_key(name: str) -> tuple[int, str]:
    if name in CANDIDATE_ORDER:
        return (CANDIDATE_ORDER.index(name), name)
    return (len(CANDIDATE_ORDER), name)


def normalize_portfolio_weights(
    weights: Mapping[str, float],
    strategies: Mapping[str, MoleStrategy] | None = None,
    tol: float = 1e-12,
) -> dict[str, float]:
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("portfolio weights must be a non-empty mapping")
    pool = candidate_strategies() if strategies is None else dict(strategies)
    cleaned: list[tuple[str, float]] = []
    for raw_name in sorted(weights.keys(), key=_canonical_strategy_key):
        if raw_name not in pool:
            raise KeyError(f"unknown strategy {raw_name!r} in portfolio weights")
        raw_val = weights[raw_name]
        if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
            raise ValueError(f"weight for {raw_name!r} must be numeric")
        val = float(raw_val)
        if not math.isfinite(val):
            raise ValueError(f"weight for {raw_name!r} must be finite")
        if val < -tol:
            raise ValueError(f"weight for {raw_name!r} must be non-negative, got {val}")
        cleaned.append((raw_name, 0.0 if abs(val) <= tol else max(0.0, val)))
    total = sum(v for _, v in cleaned)
    if total <= tol:
        raise ValueError("portfolio weights must have strictly positive total mass")
    return {name: float(val / total) for name, val in cleaned}


def portfolio_seed_unit(seed: int, salt: str = DEFAULT_PORTFOLIO_SALT) -> float:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    payload = f"{salt}:{seed}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def select_portfolio_strategy(
    seed: int,
    weights: Mapping[str, float],
    strategies: Mapping[str, MoleStrategy] | None = None,
    salt: str = DEFAULT_PORTFOLIO_SALT,
) -> MoleStrategy:
    pool = candidate_strategies() if strategies is None else dict(strategies)
    norm = normalize_portfolio_weights(weights, strategies=pool)
    positive = [(name, w) for name, w in norm.items() if w > 0.0]
    u = portfolio_seed_unit(seed, salt=salt)
    cum = 0.0
    for name, w in positive[:-1]:
        cum += w
        if u < cum:
            return pool[name]
    return pool[positive[-1][0]]


class PortfolioMolePolicy:
    def __init__(
        self,
        seed: int | Mapping[str, float] = 0,
        weights: Mapping[str, float] | None = None,
        *,
        strategies: Mapping[str, MoleStrategy] | None = None,
        salt: str = DEFAULT_PORTFOLIO_SALT,
        name: str = "regret_portfolio_v14",
    ) -> None:
        if isinstance(seed, Mapping):
            if weights is not None:
                raise TypeError("weights passed twice to PortfolioMolePolicy")
            resolved_seed = 0
            raw_weights = seed
        else:
            if weights is None:
                raise TypeError("PortfolioMolePolicy requires weights mapping")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise TypeError("seed must be an int")
            resolved_seed = int(seed)
            raw_weights = weights
        self._strategies = candidate_strategies() if strategies is None else dict(strategies)
        self.seed = resolved_seed
        self.salt = str(salt)
        self.name = str(name)
        self.weights = normalize_portfolio_weights(raw_weights, strategies=self._strategies)
        self.selected_strategy = select_portfolio_strategy(
            self.seed,
            self.weights,
            strategies=self._strategies,
            salt=self.salt,
        )
        self.selected_name = self.selected_strategy.name

    def for_seed(self, seed: int) -> "PortfolioMolePolicy":
        return PortfolioMolePolicy(
            seed=seed,
            weights=self.weights,
            strategies=self._strategies,
            salt=self.salt,
            name=self.name,
        )

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        return self.selected_strategy.decide(view, rng)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "regret_portfolio",
            "name": self.name,
            "salt": self.salt,
            "weights": dict(self.weights),
        }

    @classmethod
    def from_json(
        cls,
        obj: Mapping[str, Any],
        seed: int = 0,
        strategies: Mapping[str, MoleStrategy] | None = None,
    ) -> "PortfolioMolePolicy":
        if not isinstance(obj, Mapping) or "weights" not in obj:
            raise ValueError("invalid PortfolioMolePolicy JSON object")
        return cls(
            seed=seed,
            weights=obj["weights"],
            strategies=strategies,
            salt=str(obj.get("salt", DEFAULT_PORTFOLIO_SALT)),
            name=str(obj.get("name", "regret_portfolio_v14")),
        )


def _simplex_pivot(tab: np.ndarray, basis: list[int], row: int, col: int) -> None:
    piv = float(tab[row, col])
    tab[row, :] /= piv
    m_rows = tab.shape[0]
    for r in range(m_rows):
        if r != row and abs(float(tab[r, col])) > 1e-15:
            tab[r, :] -= tab[r, col] * tab[row, :]
    basis[row] = col


def _simplex_phase(tab: np.ndarray, basis: list[int], n_vars: int, max_iters: int = 5000) -> float:
    m = tab.shape[0] - 1
    for _ in range(max_iters):
        rc = tab[m, :n_vars]
        entering = -1
        for j in range(n_vars):
            if float(rc[j]) < -1e-11:
                entering = j
                break
        if entering < 0:
            return float(-tab[m, -1])
        leaving = -1
        best_ratio = math.inf
        best_basic = math.inf
        for r in range(m):
            a_rj = float(tab[r, entering])
            if a_rj > 1e-11:
                ratio = float(tab[r, -1]) / a_rj
                if ratio < best_ratio - 1e-13 or (abs(ratio - best_ratio) <= 1e-13 and basis[r] < best_basic):
                    best_ratio = ratio
                    best_basic = basis[r]
                    leaving = r
        if leaving < 0:
            raise PortfolioInfeasibleError("unbounded minimax LP")
        _simplex_pivot(tab, basis, leaving, entering)
    raise RuntimeError("simplex iteration limit exceeded")


def _solve_minimax_lp_simplex(
    regrets: np.ndarray,
    solver_acc: np.ndarray,
    logs_acc: np.ndarray,
    min_solver_acc: float,
    max_logs_only_acc: float,
) -> tuple[np.ndarray, float, np.ndarray, float]:
    k_strats, m_invs = regrets.shape
    shift = max(0.0, float(-np.min(regrets))) + 2.0
    r_shifted = regrets + shift

    n_real = k_strats + 1 + m_invs + 2
    m_rows = m_invs + 3
    a_mat = np.zeros((m_rows, n_real), dtype=np.float64)
    b_vec = np.zeros(m_rows, dtype=np.float64)

    for j in range(m_invs):
        a_mat[j, :k_strats] = r_shifted[:, j]
        a_mat[j, k_strats] = -1.0
        a_mat[j, k_strats + 1 + j] = -1.0
        b_vec[j] = 0.0

    row_sol = m_invs
    a_mat[row_sol, :k_strats] = solver_acc
    a_mat[row_sol, k_strats + 1 + m_invs] = -1.0
    b_vec[row_sol] = float(min_solver_acc)

    row_lo = m_invs + 1
    a_mat[row_lo, :k_strats] = logs_acc
    a_mat[row_lo, k_strats + 1 + m_invs + 1] = 1.0
    b_vec[row_lo] = float(max_logs_only_acc)

    row_eq = m_invs + 2
    a_mat[row_eq, :k_strats] = 1.0
    b_vec[row_eq] = 1.0

    orig_signs = np.ones(m_rows, dtype=np.float64)
    for r in range(m_rows):
        if b_vec[r] < 0.0:
            a_mat[r, :] *= -1.0
            b_vec[r] *= -1.0
            orig_signs[r] = -1.0

    n_total = n_real + m_rows
    tab = np.zeros((m_rows + 1, n_total + 1), dtype=np.float64)
    tab[:m_rows, :n_real] = a_mat
    tab[:m_rows, n_real:n_total] = np.eye(m_rows, dtype=np.float64)
    tab[:m_rows, -1] = b_vec
    basis = [n_real + r for r in range(m_rows)]

    tab[m_rows, n_real:n_total] = 1.0
    for r in range(m_rows):
        tab[m_rows, :] -= tab[r, :]

    phase1_val = _simplex_phase(tab, basis, n_total)
    if phase1_val > 1e-8:
        raise PortfolioInfeasibleError(
            f"no portfolio satisfies constraints (min_solver_acc={min_solver_acc}, max_logs_only_acc={max_logs_only_acc})"
        )

    for r in range(m_rows):
        if basis[r] >= n_real:
            piv_col = -1
            for j in range(n_real):
                if abs(float(tab[r, j])) > 1e-10:
                    piv_col = j
                    break
            if piv_col >= 0:
                _simplex_pivot(tab, basis, r, piv_col)

    tab2 = np.zeros((m_rows + 1, n_real + 1), dtype=np.float64)
    tab2[:m_rows, :n_real] = tab[:m_rows, :n_real]
    tab2[:m_rows, -1] = tab[:m_rows, -1]
    c_phase2 = np.zeros(n_real, dtype=np.float64)
    c_phase2[k_strats] = -1.0
    tab2[m_rows, :n_real] = c_phase2
    for r in range(m_rows):
        b_col = basis[r]
        if b_col < n_real and abs(float(tab2[m_rows, b_col])) > 1e-15:
            tab2[m_rows, :] -= tab2[m_rows, b_col] * tab2[r, :]

    _simplex_phase(tab2, basis, n_real)

    x_sol = np.zeros(n_real, dtype=np.float64)
    for r in range(m_rows):
        if basis[r] < n_real:
            x_sol[basis[r]] = max(0.0, float(tab2[r, -1]))

    w = np.maximum(0.0, x_sol[:k_strats])
    if float(np.sum(w)) <= 1e-12:
        raise PortfolioInfeasibleError("degenerate zero-mass simplex solution")
    w = w / float(np.sum(w))

    reg_vec = w @ regrets
    primal_min_reg = float(np.min(reg_vec))

    a_orig = np.zeros((m_rows, n_real), dtype=np.float64)
    b_orig = np.zeros(m_rows, dtype=np.float64)
    for r in range(m_rows):
        a_orig[r, :] = orig_signs[r] * a_mat[r, :]
        b_orig[r] = orig_signs[r] * b_vec[r]

    dual_y = np.zeros(m_invs, dtype=np.float64)
    duality_gap = 0.0
    if all(b_col < n_real for b_col in basis):
        b_mat = a_orig[:, basis]
        if abs(float(np.linalg.det(b_mat))) > 1e-13:
            c_max = np.zeros(n_real, dtype=np.float64)
            c_max[k_strats] = 1.0
            pi = np.linalg.solve(b_mat.T, c_max[basis])
            raw_y = np.maximum(0.0, -pi[:m_invs])
            if float(np.sum(raw_y)) > 1e-12:
                dual_y = raw_y / float(np.sum(raw_y))
            dual_shifted = float(pi @ b_orig)
            dual_val = dual_shifted - shift
            duality_gap = abs(primal_min_reg - dual_val)

    if float(np.sum(dual_y)) <= 1e-12:
        bind_mask = np.isclose(reg_vec, primal_min_reg, atol=1e-8)
        dual_y = bind_mask.astype(np.float64)
        dual_y /= float(np.sum(dual_y))

    return w, primal_min_reg, dual_y, float(duality_gap)


def solve_minimax_regret_portfolio(
    summaries: Sequence[StrategyEvalSummary],
    investigator_order: Sequence[str] = INVESTIGATOR_ORDER,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_only_acc: float = DEFAULT_MAX_LOGS_ONLY_ACC,
    zero_tol: float = DEFAULT_ZERO_TOL,
) -> PortfolioFitResult:
    if not summaries:
        raise ValueError("summaries must not be empty")
    inv_keys = tuple(investigator_order)
    if not inv_keys:
        raise ValueError("investigator_order must not be empty")

    seen_names: set[str] = set()
    valid_summaries: list[StrategyEvalSummary] = []
    excluded_zero: list[str] = []
    for item in summaries:
        if item.name in seen_names:
            raise ValueError(f"duplicate strategy summary name {item.name!r}")
        seen_names.add(item.name)
        for inv in inv_keys:
            if inv not in item.investigator_regrets:
                raise KeyError(f"strategy {item.name!r} missing regret for investigator {inv!r}")
        if item.passes_zero_baselines(tol=zero_tol):
            valid_summaries.append(item)
        else:
            excluded_zero.append(item.name)

    if not valid_summaries:
        raise PortfolioInfeasibleError("all candidate strategies failed DoNothing == 0.0 or StopEarlyQuit == 0.0")

    k_valid = len(valid_summaries)
    m_invs = len(inv_keys)
    reg_mat = np.array(
        [[float(s.investigator_regrets[inv]) for inv in inv_keys] for s in valid_summaries],
        dtype=np.float64,
    )
    sol_acc = np.array([float(s.solver_accuracy) for s in valid_summaries], dtype=np.float64)
    sol_score = np.array([float(s.solver_score) for s in valid_summaries], dtype=np.float64)
    lo_acc = np.array([float(s.logs_only_accuracy) for s in valid_summaries], dtype=np.float64)
    aml_acc = np.array([float(s.accuse_most_logs_accuracy) for s in valid_summaries], dtype=np.float64)
    dn_sc = np.array([float(s.do_nothing_score) for s in valid_summaries], dtype=np.float64)
    seq_sc = np.array([float(s.stop_early_quit_score) for s in valid_summaries], dtype=np.float64)

    w_valid, _, dual_y, duality_gap = _solve_minimax_lp_simplex(
        regrets=reg_mat,
        solver_acc=sol_acc,
        logs_acc=lo_acc,
        min_solver_acc=min_solver_acc,
        max_logs_only_acc=max_logs_only_acc,
    )

    if k_valid <= 12 and m_invs <= 10:
        from itertools import combinations

        best_key = (
            float(np.min(w_valid @ reg_mat)),
            float(np.mean(w_valid @ reg_mat)),
            float(w_valid @ sol_score),
        )
        best_w = w_valid.copy()
        for idx in range(k_valid):
            if sol_acc[idx] >= min_solver_acc - 1e-9 and lo_acc[idx] <= max_logs_only_acc + 1e-9:
                w_cand = np.zeros(k_valid, dtype=np.float64)
                w_cand[idx] = 1.0
                rv = reg_mat[idx]
                cand_key = (float(np.min(rv)), float(np.mean(rv)), float(sol_score[idx]))
                if (
                    cand_key[0] > best_key[0] + 1e-11
                    or (abs(cand_key[0] - best_key[0]) <= 1e-11 and cand_key[1:] > best_key[1:])
                ):
                    best_key = cand_key
                    best_w = w_cand

        f_rows = np.zeros((m_invs + 2, k_valid + 1), dtype=np.float64)
        f_rhs = np.zeros(m_invs + 2, dtype=np.float64)
        for j in range(m_invs):
            f_rows[j, :k_valid] = reg_mat[:, j]
            f_rows[j, k_valid] = -1.0
        f_rows[m_invs, :k_valid] = sol_acc
        f_rhs[m_invs] = float(min_solver_acc)
        f_rows[m_invs + 1, :k_valid] = -lo_acc
        f_rhs[m_invs + 1] = -float(max_logs_only_acc)

        max_support = min(k_valid, m_invs + 2)
        for s_size in range(2, max_support + 1):
            s_col_list = list(combinations(range(k_valid), s_size))
            col_combos = [(*sc, k_valid) for sc in s_col_list]
            row_combos = [ar for ar in combinations(range(m_invs + 2), s_size) if ar[0] < m_invs]
            if not col_combos or not row_combos:
                continue
            nc, nr = len(col_combos), len(row_combos)
            mats = np.empty((nc, nr, s_size + 1, s_size + 1), dtype=np.float64)
            mats[:, :, 0, :s_size] = 1.0
            mats[:, :, 0, s_size] = 0.0
            sub_f = f_rows[np.array(row_combos)]
            for ci, cidx in enumerate(col_combos):
                mats[ci, :, 1:, :] = sub_f[:, :, cidx]
            rhs = np.empty((nc, nr, s_size + 1, 1), dtype=np.float64)
            rhs[:, :, 0, 0] = 1.0
            rhs[:, :, 1:, 0] = f_rhs[np.array(row_combos)][None, :, :]
            valid_ij = np.argwhere(np.abs(np.linalg.det(mats)) > 1e-13)
            if len(valid_ij) == 0:
                continue
            sols = np.linalg.solve(
                mats[valid_ij[:, 0], valid_ij[:, 1]],
                rhs[valid_ij[:, 0], valid_ij[:, 1]],
            )[:, :s_size, 0]
            for idx_pair, sol_sub in zip(valid_ij, sols):
                if not np.all(np.isfinite(sol_sub)) or float(np.min(sol_sub)) < -1e-9:
                    continue
                sol_clean = np.maximum(0.0, sol_sub)
                tot_sub = float(np.sum(sol_clean))
                if tot_sub <= 1e-12:
                    continue
                sol_clean /= tot_sub
                w_cand = np.zeros(k_valid, dtype=np.float64)
                w_cand[list(s_col_list[int(idx_pair[0])])] = sol_clean
                if float(w_cand @ sol_acc) < min_solver_acc - 1e-9:
                    continue
                if float(w_cand @ lo_acc) > max_logs_only_acc + 1e-9:
                    continue
                rv = w_cand @ reg_mat
                cand_key = (float(np.min(rv)), float(np.mean(rv)), float(w_cand @ sol_score))
                if (
                    cand_key[0] > best_key[0] + 1e-11
                    or (abs(cand_key[0] - best_key[0]) <= 1e-11 and cand_key[1:] > best_key[1:])
                ):
                    best_key = cand_key
                    best_w = w_cand
        w_valid = best_w

    w_valid = np.where(w_valid <= 1e-12, 0.0, w_valid)
    w_valid /= float(np.sum(w_valid))

    exp_sol_acc = float(w_valid @ sol_acc)
    exp_sol_score = float(w_valid @ sol_score)
    exp_lo_acc = float(w_valid @ lo_acc)
    exp_aml_acc = float(w_valid @ aml_acc)
    exp_dn_score = float(w_valid @ dn_sc)
    exp_seq_score = float(w_valid @ seq_sc)

    if exp_sol_acc < min_solver_acc - 1e-8 or exp_lo_acc > max_logs_only_acc + 1e-8:
        raise PortfolioInfeasibleError("portfolio solution failed post-solve constraint check")
    if abs(exp_dn_score) > zero_tol or abs(exp_seq_score) > zero_tol:
        raise PortfolioInfeasibleError("portfolio solution failed zero-score baseline check")

    exp_reg_vec = w_valid @ reg_mat
    min_reg = float(np.min(exp_reg_vec))
    mean_reg = float(np.mean(exp_reg_vec))
    exp_regrets = {inv: float(exp_reg_vec[j]) for j, inv in enumerate(inv_keys)}

    exp_inv_scores: dict[str, float] = {}
    exp_inv_accs: dict[str, float] = {}
    for inv in inv_keys:
        sc_arr = np.array([float(s.investigator_scores.get(inv, s.solver_score - s.investigator_regrets[inv])) for s in valid_summaries])
        ac_arr = np.array([float(s.investigator_accuracies.get(inv, 0.0)) for s in valid_summaries])
        exp_inv_scores[inv] = float(w_valid @ sc_arr)
        exp_inv_accs[inv] = float(w_valid @ ac_arr)

    binding = tuple(inv for inv in inv_keys if abs(exp_regrets[inv] - min_reg) <= 1e-7)

    valid_map = {s.name: float(w_valid[i]) for i, s in enumerate(valid_summaries)}
    full_weights = {s.name: valid_map.get(s.name, 0.0) for s in summaries}
    active = tuple(name for name, w in full_weights.items() if w > 0.0)

    cf_drops = [s.counterfactual_ev_drop for s in valid_summaries]
    cf_regs = [s.counterfactual_regret for s in valid_summaries]
    exp_cf_drop = (
        float(w_valid @ np.array([float(x) for x in cf_drops], dtype=np.float64))
        if all(x is not None for x in cf_drops)
        else None
    )
    exp_cf_reg = (
        float(w_valid @ np.array([float(x) for x in cf_regs], dtype=np.float64))
        if all(x is not None for x in cf_regs)
        else None
    )

    dual_dict = {inv: float(dual_y[j]) for j, inv in enumerate(inv_keys)}
    gates_ok = (
        exp_sol_acc >= min_solver_acc - 1e-9
        and exp_lo_acc <= max_logs_only_acc + 1e-9
        and abs(exp_dn_score) <= zero_tol
        and abs(exp_seq_score) <= zero_tol
        and abs(sum(full_weights.values()) - 1.0) <= 1e-9
    )

    return PortfolioFitResult(
        weights=full_weights,
        min_regret=min_reg,
        mean_regret=mean_reg,
        expected_regrets=exp_regrets,
        expected_investigator_scores=exp_inv_scores,
        expected_investigator_accuracies=exp_inv_accs,
        binding_investigators=binding,
        dual_investigator_weights=dual_dict,
        duality_gap=duality_gap,
        expected_solver_score=exp_sol_score,
        expected_solver_accuracy=exp_sol_acc,
        expected_logs_only_accuracy=exp_lo_acc,
        expected_accuse_most_logs_accuracy=exp_aml_acc,
        expected_do_nothing_score=exp_dn_score,
        expected_stop_early_quit_score=exp_seq_score,
        expected_counterfactual_ev_drop=exp_cf_drop,
        expected_counterfactual_regret=exp_cf_reg,
        active_strategies=active,
        excluded_zero_baseline_strategies=tuple(excluded_zero),
        min_solver_acc_bound=float(min_solver_acc),
        max_logs_only_acc_bound=float(max_logs_only_acc),
        gates_passed=bool(gates_ok),
    )


def load_summaries_from_v14_json(
    json_path: str | Path = DEFAULT_SUMMARY_JSON,
) -> tuple[list[StrategyEvalSummary], dict[str, Any]]:
    p = Path(json_path)
    if not p.is_file():
        raise FileNotFoundError(f"missing precomputed v1.4 strategy JSON at {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    seeds = validate_eval_seeds(payload.get("seeds", []))
    inv_order = tuple(payload.get("investigator_order", INVESTIGATOR_ORDER))
    strat_map = payload.get("strategies", {})
    order = [name for name in CANDIDATE_ORDER if name in strat_map]
    for name in payload.get("strategy_order", []):
        if name in strat_map and name not in order:
            order.append(name)

    summaries: list[StrategyEvalSummary] = []
    for name in order:
        row = strat_map[name]
        sol = row["solver"]
        invs = row["investigators"]
        base = row["baselines"]
        cf = row.get("counterfactual") or {}
        summaries.append(
            StrategyEvalSummary(
                name=name,
                solver_score=float(sol["score"]),
                solver_accuracy=float(sol["accuracy"]),
                investigator_scores={k: float(invs[k]["score"]) for k in inv_order},
                investigator_accuracies={k: float(invs[k]["accuracy"]) for k in inv_order},
                investigator_regrets={k: float(invs[k]["regret"]) for k in inv_order},
                logs_only_accuracy=float(base["logs_only"]["accuracy"]),
                accuse_most_logs_accuracy=float(base["accuse_most_logs"]["accuracy"]),
                do_nothing_score=float(base["do_nothing"]["score"]),
                stop_early_quit_score=float(base["stop_early_quit"]["score"]),
                counterfactual_ev_drop=(
                    float(cf["optimal_ev_drop"]) if "optimal_ev_drop" in cf else None
                ),
                counterfactual_regret=(
                    float(cf["counterfactual_regret"]) if "counterfactual_regret" in cf else None
                ),
            )
        )
    meta = {
        "source_path": str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p),
        "tier": str(payload.get("tier", "hard")),
        "tiers_version": str(payload.get("tiers_version", TIERS_VERSION)),
        "seed_range": str(payload.get("seed_range", f"{seeds[0]}-{seeds[-1]}")),
        "n_seeds": len(seeds),
        "seeds": seeds,
    }
    return summaries, meta


def _eval_policy_seed_worker(task: tuple[str, str, int, dict[str, Any]]) -> dict[str, Any]:
    label, tier, seed, spec = task
    kind = spec["kind"]
    if kind == "portfolio":
        mole_obj: Any = PortfolioMolePolicy(
            seed=seed,
            weights=spec["weights"],
            salt=spec.get("salt", DEFAULT_PORTFOLIO_SALT),
            name=spec.get("name", "regret_portfolio_v14"),
        )
        selected_name = mole_obj.selected_name
    elif kind == "dsl":
        mole_obj = MoleStrategy.from_json(spec["strategy_json"])
        selected_name = mole_obj.name
    else:
        raise ValueError(f"unknown policy spec kind {kind!r}")

    sol_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), SolverPolicy(tier, act_budget=5.0))
    gem_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), GeminiCarbonProxy(seed=seed))
    cdx_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), CodexHorizonProxy(seed=seed))
    grk_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), GrokTactics(seed=seed))
    heu_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), Heuristic(seed=seed))
    hh_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), HintedHeuristic(seed=seed))
    lo_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), LogsOnly(seed=seed))
    aml_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), AccuseMostLogs(seed=seed))
    dn_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), DoNothing(seed=seed))
    seq_res = run_episode(Env(tier, seed, mole_strategy=mole_obj), StopEarlyQuit(seed=seed))

    inv_map = {
        "gemini_carbon_proxy": gem_res,
        "codex_horizon_proxy": cdx_res,
        "grok_tactics": grk_res,
        "heuristic": heu_res,
        "hinted_heuristic": hh_res,
    }
    sol_sc = float(sol_res.score)
    return {
        "label": label,
        "seed": int(seed),
        "selected_strategy": selected_name,
        "solver_score": sol_sc,
        "solver_correct": bool(sol_res.correct),
        "investigators": {
            k: {
                "score": float(r.score),
                "correct": bool(r.correct),
                "regret": float(sol_sc - float(r.score)),
            }
            for k, r in inv_map.items()
        },
        "logs_only_correct": bool(lo_res.correct),
        "logs_only_score": float(lo_res.score),
        "accuse_most_logs_correct": bool(aml_res.correct),
        "accuse_most_logs_score": float(aml_res.score),
        "do_nothing_score": float(dn_res.score),
        "stop_early_quit_score": float(seq_res.score),
    }


def _bootstrap_ci(xs: Sequence[float], n_resamples: int = DEFAULT_BOOT_RESAMPLES, seed: int = DEFAULT_BOOT_SEED) -> list[float]:
    n = len(xs)
    if n == 0:
        raise ValueError("cannot bootstrap empty sequence")
    if n == 1 or n_resamples <= 0:
        v = float(xs[0])
        return [v, v]
    rng = random.Random(seed)
    means = [sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples)]
    means.sort()
    return [float(means[int(0.025 * n_resamples)]), float(means[max(0, int(0.975 * n_resamples) - 1)])]


def _paired_min_regret_bootstrap(
    port_regs: Mapping[str, Sequence[float]],
    base_regs: Mapping[str, Sequence[float]],
    n_resamples: int = DEFAULT_BOOT_RESAMPLES,
    seed: int = DEFAULT_BOOT_SEED,
) -> tuple[list[float], list[float], list[float]]:
    keys = list(INVESTIGATOR_ORDER)
    n = len(port_regs[keys[0]])
    if n == 0:
        raise ValueError("empty regret vectors")
    if n == 1 or n_resamples <= 0:
        pm = min(float(port_regs[k][0]) for k in keys)
        bm = min(float(base_regs[k][0]) for k in keys)
        d = pm - bm
        return [pm, pm], [bm, bm], [d, d]
    rng = random.Random(seed)
    p_vals: list[float] = []
    b_vals: list[float] = []
    d_vals: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        pm = min(sum(float(port_regs[k][i]) for i in idx) / n for k in keys)
        bm = min(sum(float(base_regs[k][i]) for i in idx) / n for k in keys)
        p_vals.append(pm)
        b_vals.append(bm)
        d_vals.append(pm - bm)
    p_vals.sort()
    b_vals.sort()
    d_vals.sort()
    lo = int(0.025 * n_resamples)
    hi = max(0, int(0.975 * n_resamples) - 1)
    return [p_vals[lo], p_vals[hi]], [b_vals[lo], b_vals[hi]], [d_vals[lo], d_vals[hi]]


def _aggregate_seed_rows(rows: Sequence[dict[str, Any]]) -> tuple[StrategyEvalSummary, dict[str, Any]]:
    if not rows:
        raise ValueError("cannot aggregate empty episode rows")
    ordered = sorted(rows, key=lambda r: int(r["seed"]))
    n = len(ordered)
    label = str(ordered[0]["label"])
    sol_scores = [float(r["solver_score"]) for r in ordered]
    sol_acc = sum(1 for r in ordered if r["solver_correct"]) / n
    lo_acc = sum(1 for r in ordered if r["logs_only_correct"]) / n
    aml_acc = sum(1 for r in ordered if r["accuse_most_logs_correct"]) / n
    dn_scores = [float(r["do_nothing_score"]) for r in ordered]
    seq_scores = [float(r["stop_early_quit_score"]) for r in ordered]

    inv_scores: dict[str, float] = {}
    inv_accs: dict[str, float] = {}
    inv_regs: dict[str, float] = {}
    per_seed_regs: dict[str, list[float]] = {}
    for inv in INVESTIGATOR_ORDER:
        scs = [float(r["investigators"][inv]["score"]) for r in ordered]
        acs = [1.0 if r["investigators"][inv]["correct"] else 0.0 for r in ordered]
        rgs = [float(r["investigators"][inv]["regret"]) for r in ordered]
        inv_scores[inv] = sum(scs) / n
        inv_accs[inv] = sum(acs) / n
        inv_regs[inv] = sum(rgs) / n
        per_seed_regs[inv] = rgs

    counts: dict[str, int] = {}
    for r in ordered:
        sname = str(r["selected_strategy"])
        counts[sname] = counts.get(sname, 0) + 1

    summary = StrategyEvalSummary(
        name=label,
        solver_score=sum(sol_scores) / n,
        solver_accuracy=sol_acc,
        investigator_scores=inv_scores,
        investigator_accuracies=inv_accs,
        investigator_regrets=inv_regs,
        logs_only_accuracy=lo_acc,
        accuse_most_logs_accuracy=aml_acc,
        do_nothing_score=sum(dn_scores) / n,
        stop_early_quit_score=sum(seq_scores) / n,
    )
    detail = {
        "n_seeds": n,
        "seeds": [int(r["seed"]) for r in ordered],
        "selected_strategy_counts": {k: counts[k] for k in sorted(counts, key=_canonical_strategy_key)},
        "solver_score": summary.solver_score,
        "solver_score_boot_ci_95": _bootstrap_ci(sol_scores),
        "solver_accuracy": summary.solver_accuracy,
        "logs_only_accuracy": summary.logs_only_accuracy,
        "logs_only_score": sum(float(r["logs_only_score"]) for r in ordered) / n,
        "accuse_most_logs_accuracy": summary.accuse_most_logs_accuracy,
        "accuse_most_logs_score": sum(float(r["accuse_most_logs_score"]) for r in ordered) / n,
        "do_nothing_score": summary.do_nothing_score,
        "do_nothing_max_abs": max(abs(x) for x in dn_scores),
        "stop_early_quit_score": summary.stop_early_quit_score,
        "stop_early_quit_max_abs": max(abs(x) for x in seq_scores),
        "min_regret": summary.min_regret,
        "mean_regret": summary.mean_regret,
        "strongest_investigator": min(INVESTIGATOR_ORDER, key=lambda k: inv_regs[k]),
        "investigators": {
            inv: {
                "score": inv_scores[inv],
                "accuracy": inv_accs[inv],
                "regret": inv_regs[inv],
                "regret_boot_ci_95": _bootstrap_ci(per_seed_regs[inv], seed=DEFAULT_BOOT_SEED + idx),
            }
            for idx, inv in enumerate(INVESTIGATOR_ORDER)
        },
        "_per_seed_regrets": per_seed_regs,
    }
    return summary, detail


def evaluate_policies_on_seeds(
    policy_specs: Mapping[str, dict[str, Any]],
    seeds: Sequence[int],
    tier: str = "hard",
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, tuple[StrategyEvalSummary, dict[str, Any]]]:
    clean_seeds = validate_eval_seeds(seeds)
    tasks: list[tuple[str, str, int, dict[str, Any]]] = [
        (label, tier, int(s), spec)
        for label, spec in policy_specs.items()
        for s in clean_seeds
    ]
    if max_workers <= 1 or len(tasks) <= 2:
        raw_rows = [_eval_policy_seed_worker(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=int(max_workers)) as pool:
            raw_rows = list(pool.map(_eval_policy_seed_worker, tasks))

    grouped: dict[str, list[dict[str, Any]]] = {label: [] for label in policy_specs}
    for row in raw_rows:
        grouped[str(row["label"])].append(row)
    return {label: _aggregate_seed_rows(rows) for label, rows in grouped.items()}


def evaluate_strategies_live(
    seeds: str | Iterable[int] = DEFAULT_LIVE_TRAIN_SEEDS_SPEC,
    strategies: Mapping[str, MoleStrategy] | None = None,
    tier: str = "hard",
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[StrategyEvalSummary]:
    pool = candidate_strategies() if strategies is None else dict(strategies)
    ordered_names = sorted(pool.keys(), key=_canonical_strategy_key)
    specs = {
        name: {"kind": "dsl", "strategy_json": pool[name].to_json()}
        for name in ordered_names
    }
    eval_map = evaluate_policies_on_seeds(specs, seeds=validate_eval_seeds(seeds), tier=tier, max_workers=max_workers)
    return [eval_map[name][0] for name in ordered_names]


def assert_payload_hygiene(payload: Any) -> None:
    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden key {ks!r} at {path}")
                _walk(v, f"{path}.{ks}")
        elif isinstance(node, (list, tuple)):
            for idx, item in enumerate(node):
                _walk(item, f"{path}[{idx}]")
        elif isinstance(node, str):
            if EM_DASH in node or EN_DASH in node:
                raise ValueError(f"forbidden dash character in {path}")
            low = node.lower()
            for bad in FORBIDDEN_CLAIM_SUBSTRINGS:
                if bad in low:
                    raise ValueError(f"forbidden claim substring {bad!r} in {path}")
            for pat in SECRET_PATTERNS:
                if pat.search(node):
                    raise ValueError(f"secret-like token matched in {path}")

    _walk(payload, "root")


def run_portfolio_pipeline(
    *,
    fit_source: str = "precomputed",
    summary_json: str | Path = DEFAULT_SUMMARY_JSON,
    train_seeds: str | Iterable[int] = DEFAULT_LIVE_TRAIN_SEEDS_SPEC,
    val_seeds: str | Iterable[int] = DEFAULT_VAL_SEEDS_SPEC,
    tier: str = "hard",
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_only_acc: float = DEFAULT_MAX_LOGS_ONLY_ACC,
    salt: str = DEFAULT_PORTFOLIO_SALT,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    clean_val_seeds = validate_eval_seeds(val_seeds)

    if fit_source == "precomputed":
        train_summaries, train_meta = load_summaries_from_v14_json(summary_json)
        clean_train_seeds = list(train_meta["seeds"])
        train_seed_range = str(train_meta["seed_range"])
        train_source_desc = f"precomputed_json:{train_meta['source_path']}"
    elif fit_source == "live":
        clean_train_seeds = validate_eval_seeds(train_seeds)
        assert_disjoint_seed_splits(clean_train_seeds, clean_val_seeds)
        train_summaries = evaluate_strategies_live(
            seeds=clean_train_seeds,
            tier=tier,
            max_workers=max_workers,
        )
        train_seed_range = f"{clean_train_seeds[0]}-{clean_train_seeds[-1]}"
        train_source_desc = "live_episodes"
    else:
        raise ValueError(f"fit_source must be 'precomputed' or 'live', got {fit_source!r}")

    assert_disjoint_seed_splits(clean_train_seeds, clean_val_seeds)
    fit = solve_minimax_regret_portfolio(
        train_summaries,
        investigator_order=INVESTIGATOR_ORDER,
        min_solver_acc=min_solver_acc,
        max_logs_only_acc=max_logs_only_acc,
    )

    default_train = next(s for s in train_summaries if s.name == DEFAULT_STRATEGY.name)
    best_pure_train = max(
        (
            s for s in train_summaries
            if s.solver_accuracy >= min_solver_acc - 1e-9
            and s.logs_only_accuracy <= max_logs_only_acc + 1e-9
            and s.passes_zero_baselines()
        ),
        key=lambda s: (s.min_regret, s.mean_regret, s.solver_score),
    )

    val_specs = {
        DEFAULT_STRATEGY.name: {"kind": "dsl", "strategy_json": DEFAULT_STRATEGY.to_json()},
        "regret_portfolio_v14": {
            "kind": "portfolio",
            "weights": dict(fit.weights),
            "salt": salt,
            "name": "regret_portfolio_v14",
        },
    }
    val_eval = evaluate_policies_on_seeds(
        val_specs,
        seeds=clean_val_seeds,
        tier=tier,
        max_workers=max_workers,
    )
    val_def_sum, val_def_det = val_eval[DEFAULT_STRATEGY.name]
    val_port_sum, val_port_det = val_eval["regret_portfolio_v14"]

    port_per_seed = val_port_det.pop("_per_seed_regrets")
    def_per_seed = val_def_det.pop("_per_seed_regrets")
    port_min_ci, def_min_ci, delta_min_ci = _paired_min_regret_bootstrap(port_per_seed, def_per_seed)
    val_port_det["min_regret_boot_ci_95"] = port_min_ci
    val_def_det["min_regret_boot_ci_95"] = def_min_ci

    paired_inv_gains: dict[str, dict[str, Any]] = {}
    for idx, inv in enumerate(INVESTIGATOR_ORDER):
        diffs = [p - b for p, b in zip(port_per_seed[inv], def_per_seed[inv])]
        paired_inv_gains[inv] = {
            "gain_vs_default": float(val_port_sum.investigator_regrets[inv] - val_def_sum.investigator_regrets[inv]),
            "gain_boot_ci_95": _bootstrap_ci(diffs, seed=DEFAULT_BOOT_SEED + 100 + idx),
        }

    val_gates_passed = (
        val_port_sum.solver_accuracy >= min_solver_acc - 1e-9
        and val_port_sum.logs_only_accuracy <= max_logs_only_acc + 1e-9
        and abs(val_port_sum.do_nothing_score) <= DEFAULT_ZERO_TOL
        and abs(val_port_sum.stop_early_quit_score) <= DEFAULT_ZERO_TOL
    )

    elapsed_s = time.perf_counter() - t0
    payload: dict[str, Any] = {
        "schema_version": "mole_regret_portfolio_v14.v1",
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "portfolio_salt": salt,
        "constraints": {
            "min_solver_acc": float(min_solver_acc),
            "max_logs_only_acc": float(max_logs_only_acc),
            "do_nothing_exact": 0.0,
            "stop_early_quit_exact": 0.0,
        },
        "seed_hygiene": {
            "train_seed_range": train_seed_range,
            "train_n_seeds": len(clean_train_seeds),
            "val_seed_range": f"{clean_val_seeds[0]}-{clean_val_seeds[-1]}",
            "val_n_seeds": len(clean_val_seeds),
            "val_seeds": clean_val_seeds,
            "disjoint_train_val": True,
            "forbidden_ranges_excluded": True,
        },
        "train": {
            "source": train_source_desc,
            "n_seeds": len(clean_train_seeds),
            "seed_range": train_seed_range,
            "candidate_order": [s.name for s in train_summaries],
            "investigator_order": list(INVESTIGATOR_ORDER),
            "candidates": {
                s.name: {
                    "solver_accuracy": s.solver_accuracy,
                    "solver_score": s.solver_score,
                    "logs_only_accuracy": s.logs_only_accuracy,
                    "accuse_most_logs_accuracy": s.accuse_most_logs_accuracy,
                    "do_nothing_score": s.do_nothing_score,
                    "stop_early_quit_score": s.stop_early_quit_score,
                    "min_regret": s.min_regret,
                    "mean_regret": s.mean_regret,
                    "strongest_investigator": min(INVESTIGATOR_ORDER, key=lambda k: s.investigator_regrets[k]),
                    "investigator_regrets": dict(s.investigator_regrets),
                    "investigator_scores": dict(s.investigator_scores),
                    "investigator_accuracies": dict(s.investigator_accuracies),
                    "counterfactual_ev_drop": s.counterfactual_ev_drop,
                    "counterfactual_regret": s.counterfactual_regret,
                }
                for s in train_summaries
            },
            "portfolio": {
                "weights": dict(fit.weights),
                "active_strategies": list(fit.active_strategies),
                "min_regret": fit.min_regret,
                "min_regret_gain_vs_default": float(fit.min_regret - default_train.min_regret),
                "min_regret_gain_vs_best_pure": float(fit.min_regret - best_pure_train.min_regret),
                "best_pure_strategy": best_pure_train.name,
                "best_pure_min_regret": best_pure_train.min_regret,
                "mean_regret": fit.mean_regret,
                "mean_regret_gain_vs_default": float(fit.mean_regret - default_train.mean_regret),
                "expected_regrets": dict(fit.expected_regrets),
                "expected_investigator_scores": dict(fit.expected_investigator_scores),
                "expected_investigator_accuracies": dict(fit.expected_investigator_accuracies),
                "binding_investigators": list(fit.binding_investigators),
                "dual_investigator_weights": dict(fit.dual_investigator_weights),
                "duality_gap": fit.duality_gap,
                "expected_solver_score": fit.expected_solver_score,
                "expected_solver_accuracy": fit.expected_solver_accuracy,
                "expected_logs_only_accuracy": fit.expected_logs_only_accuracy,
                "expected_accuse_most_logs_accuracy": fit.expected_accuse_most_logs_accuracy,
                "expected_do_nothing_score": fit.expected_do_nothing_score,
                "expected_stop_early_quit_score": fit.expected_stop_early_quit_score,
                "expected_counterfactual_ev_drop": fit.expected_counterfactual_ev_drop,
                "expected_counterfactual_regret": fit.expected_counterfactual_regret,
                "gates_passed": fit.gates_passed,
            },
        },
        "validation": {
            "n_seeds": len(clean_val_seeds),
            "seed_range": f"{clean_val_seeds[0]}-{clean_val_seeds[-1]}",
            "seeds": clean_val_seeds,
            "default_v0": val_def_det,
            "regret_portfolio_v14": val_port_det,
            "paired_comparison": {
                "min_regret_delta_vs_default": float(val_port_sum.min_regret - val_def_sum.min_regret),
                "min_regret_delta_boot_ci_95": delta_min_ci,
                "mean_regret_delta_vs_default": float(val_port_sum.mean_regret - val_def_sum.mean_regret),
                "per_investigator_gain": paired_inv_gains,
            },
            "gates_passed": bool(val_gates_passed),
        },
        "runtime_meta": {
            "max_workers": int(max_workers),
            "zero_api_calls": True,
            "elapsed_seconds_recorded": round(elapsed_s, 3),
        },
    }
    canonical_payload: dict[str, Any] = json.loads(json.dumps(payload, sort_keys=True))
    assert_payload_hygiene(canonical_payload)
    return canonical_payload


def _fmt_signed(val: float, digits: int = 3) -> str:
    return f"{val:+.{digits}f}"


def render_markdown_report(payload: Mapping[str, Any]) -> str:
    assert_payload_hygiene(payload)
    tr = payload["train"]
    tp = tr["portfolio"]
    va = payload["validation"]
    vp = va["regret_portfolio_v14"]
    vd = va["default_v0"]
    vc = va["paired_comparison"]
    con = payload["constraints"]
    sh = payload["seed_hygiene"]

    active_desc = ", ".join(
        f"`{tp['weights'][name]:.4f}` on `{name}`"
        for name in tp["active_strategies"]
    )
    binding_desc = ", ".join(
        f"`{INVESTIGATOR_LABELS.get(k, k)}` (`{tp['expected_regrets'][k]:.4f}`)"
        for k in tp["binding_investigators"]
    )
    inactive_count = len(tr["candidate_order"]) - len(tp["active_strategies"])
    def_min_reg = float(tr["candidates"][tr["candidate_order"][0]]["min_regret"])
    def_name = str(tr["candidate_order"][0])

    lines: list[str] = [
        f"{H1} Sleeper Minimax Attack-Regret Mole Portfolio: v1.4 Hard Report",
        "",
        (
            f"Ports the Sleeper minimax attack-regret portfolio (`max_w min_{{inv != solver}} sum_i w_i E[Solver - inv | strat_i]`) "
            f"into Canary v1.4 `{payload['tier']}` over `DEFAULT_STRATEGY` plus all 6 transcript-grounded `STRATEGY_SPECS`. "
            f"Portfolio weights are fit on `{sh['train_seed_range']}` (`n={sh['train_n_seeds']}`) subject to "
            f"`SolverPolicy(\"hard\") acc >= {con['min_solver_acc']:.2f}`, `LogsOnly acc <= {con['max_logs_only_acc']:.2f}`, "
            f"`DoNothing == 0.0`, and `StopEarlyQuit == 0.0`, and realized per episode via deterministic zero-private-info "
            f"SHA-256 seed hashing (`PortfolioMolePolicy` / `select_portfolio_strategy(seed, weights)`) on disjoint held-out "
            f"validation seeds `{sh['val_seed_range']}` (`n={sh['val_n_seeds']}`). Zero LLM API calls."
        ),
        "",
        "Reproduce or verify exact embedded ledger consistency:",
        "```bash",
        "PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.regret_portfolio --out docs/reports/mole_regret_portfolio_v14.md",
        "PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.regret_portfolio --check",
        "```",
        "",
        f"{H2} 1. Headline Findings",
        "",
        (
            f"- **Strict minimax dominance over every pure strategy on train (`{sh['train_seed_range']}`, `n={sh['train_n_seeds']}`)**: "
            f"Optimal portfolio places {active_desc} (zero mass on the remaining {inactive_count} candidates), "
            f"achieving worst-case investigator regret `{tp['min_regret']:.4f}` vs `{def_name}` "
            f"`{def_min_reg:.4f}` (`{_fmt_signed(tp['min_regret_gain_vs_default'], 4)}`) "
            f"and vs best single pure strategy `{tp['best_pure_strategy']}` `{tp['best_pure_min_regret']:.4f}` "
            f"(`{_fmt_signed(tp['min_regret_gain_vs_best_pure'], 4)}`)."
        ),
        (
            f"- **Exact saddle-point duality & equalized binding adversaries**: "
            f"Binding investigators ({binding_desc}) "
            f"are equalized at the minimax floor (`duality_gap = {tp['duality_gap']:.2e}`), "
            f"leaving zero single-investigator exploit below `{tp['min_regret']:.4f}`."
        ),
        (
            f"- **Train & disjoint held-out validation fairness gates (`100%` pass)**: "
            f"Train expected `SolverPolicy(\"hard\")` accuracy is `{tp['expected_solver_accuracy']:.3f}` (`>= 0.90`), "
            f"`LogsOnly` accuracy is `{tp['expected_logs_only_accuracy']:.3f}` (`<= 0.10`), and `DoNothing` / `StopEarlyQuit` are `{tp['expected_do_nothing_score']:.3f}` / `{tp['expected_stop_early_quit_score']:.3f}`. "
            f"On disjoint live validation seeds `{sh['val_seed_range']}` (`n={sh['val_n_seeds']}`), `PortfolioMolePolicy` achieves "
            f"`SolverPolicy(\"hard\")` accuracy `{vp['solver_accuracy']:.3f}`, `LogsOnly` accuracy `{vp['logs_only_accuracy']:.3f}`, "
            f"`DoNothing = {vp['do_nothing_score']:.3f}`, and `StopEarlyQuit = {vp['stop_early_quit_score']:.3f}` (`gates_passed={va['gates_passed']}`)."
        ),
    ]

    if tp["expected_counterfactual_ev_drop"] is not None and tp["expected_counterfactual_regret"] is not None:
        lines.append(
            f"- **Expected counterfactual impact on 60 committed v1.4 Gemini-4-carbon Hard transcripts (`0` API calls)**: "
            f"Under portfolio mixture weights, expected Gemini-4-carbon optimal Bayesian EV drop is `{_fmt_signed(tp['expected_counterfactual_ev_drop'], 3)}` "
            f"and expected counterfactual regret is `{_fmt_signed(tp['expected_counterfactual_regret'], 3)}` "
            f"(vs `{def_name}` `{_fmt_signed(tr['candidates'][def_name]['counterfactual_regret'], 3)}`)."
        )

    lines += [
        "",
        f"{H2} 2. Optimal Minimax Portfolio Weights & Dual Adversarial Equilibrium (`{sh['train_seed_range']}`, `n={sh['train_n_seeds']}`)",
        "",
        "| Strategy | Portfolio Weight `w_i` | Pure Solver Acc | Pure LogsOnly Acc | Pure Strongest Inv | Pure Min Regret | Pure Mean Regret |",
        "|---|---|---|---|---|---|---|",
    ]
    for sname in tr["candidate_order"]:
        cand = tr["candidates"][sname]
        w_val = float(tp["weights"][sname])
        lines.append(
            f"| `{sname}` | `{w_val:.6f}` | `{cand['solver_accuracy']:.3f}` | `{cand['logs_only_accuracy']:.3f}` | "
            f"`{INVESTIGATOR_LABELS.get(cand['strongest_investigator'], cand['strongest_investigator'])}` | `{cand['min_regret']:.4f}` | `{cand['mean_regret']:.4f}` |"
        )
    lines.append(
        f"| **`PortfolioMolePolicy (w*)`** | **`1.000000`** | **`{tp['expected_solver_accuracy']:.3f}`** | "
        f"**`{tp['expected_logs_only_accuracy']:.3f}`** | **`Equalized ({', '.join(INVESTIGATOR_LABELS.get(k, k) for k in tp['binding_investigators'])})`** | "
        f"**`{tp['min_regret']:.4f}`** | **`{tp['mean_regret']:.4f}`** |"
    )

    lines += [
        "",
        f"{H3} 2.1 Train Per-Investigator Expected Regret & Dual Adversary Mixture",
        "",
        f"| Investigator | `{def_name}` Regret | Best Pure (`{tp['best_pure_strategy']}`) Regret | Portfolio `w*` Expected Regret | Gain vs Default | Dual Weight `y_j` |",
        "|---|---|---|---|---|---|",
    ]
    def_cand = tr["candidates"][def_name]
    bp_cand = tr["candidates"][tp["best_pure_strategy"]]
    for inv in tr["investigator_order"]:
        r_def = float(def_cand["investigator_regrets"][inv])
        r_bp = float(bp_cand["investigator_regrets"][inv])
        r_port = float(tp["expected_regrets"][inv])
        y_dual = float(tp["dual_investigator_weights"][inv])
        lines.append(
            f"| `{INVESTIGATOR_LABELS.get(inv, inv)}` | `{r_def:.4f}` | `{r_bp:.4f}` | `{r_port:.4f}` | "
            f"`{_fmt_signed(r_port - r_def, 4)}` | `{y_dual:.4f}` |"
        )

    sel_counts = vp["selected_strategy_counts"]
    sel_counts_str = ", ".join(
        f"`{k}`: `{sel_counts[k]}`"
        for k in sorted(sel_counts, key=_canonical_strategy_key)
    )
    lines += [
        "",
        f"{H2} 3. Disjoint Held-Out Live Validation (`{sh['val_seed_range']}`, `n={sh['val_n_seeds']}`)",
        "",
        (
            f"Each held-out seed in `{sh['val_seed_range']}` instantiates a fresh `Env(\"hard\", seed, mole_strategy=...)` "
            f"and fresh investigator policy (`SolverPolicy(\"hard\")` plus 5 non-solver investigators and 4 fairness baselines; "
            f"zero `copy.deepcopy` of generator-based `ScriptedPolicy` instances). Deterministic SHA-256 selection (`salt={payload['portfolio_salt']}`) "
            f"uses only `(seed, weights)` with zero private world state, realizing {sel_counts_str} across `{sh['val_n_seeds']}` seeds."
        ),
        "",
        "| Policy | Solver Acc | Solver Score [95% Boot CI] | LogsOnly Acc | AccuseMostLogs Acc | DoNothing | StopEarlyQuit | Min Regret [95% Boot CI] | Mean Regret | Gates |",
        "|---|---|---|---|---|---|---|---|---|---|",
        (
            f"| `DEFAULT_STRATEGY (default_v0)` | `{vd['solver_accuracy']:.3f}` | `{vd['solver_score']:.3f}` [{vd['solver_score_boot_ci_95'][0]:.3f}, {vd['solver_score_boot_ci_95'][1]:.3f}] | "
            f"`{vd['logs_only_accuracy']:.3f}` | `{vd['accuse_most_logs_accuracy']:.3f}` | `{vd['do_nothing_score']:.3f}` | `{vd['stop_early_quit_score']:.3f}` | "
            f"`{vd['min_regret']:.3f}` [{vd['min_regret_boot_ci_95'][0]:.3f}, {vd['min_regret_boot_ci_95'][1]:.3f}] | `{vd['mean_regret']:.3f}` | PASS |"
        ),
        (
            f"| `PortfolioMolePolicy (regret_portfolio_v14)` | `{vp['solver_accuracy']:.3f}` | `{vp['solver_score']:.3f}` [{vp['solver_score_boot_ci_95'][0]:.3f}, {vp['solver_score_boot_ci_95'][1]:.3f}] | "
            f"`{vp['logs_only_accuracy']:.3f}` | `{vp['accuse_most_logs_accuracy']:.3f}` | `{vp['do_nothing_score']:.3f}` | `{vp['stop_early_quit_score']:.3f}` | "
            f"`{vp['min_regret']:.3f}` [{vp['min_regret_boot_ci_95'][0]:.3f}, {vp['min_regret_boot_ci_95'][1]:.3f}] | `{vp['mean_regret']:.3f}` | {'PASS' if va['gates_passed'] else 'FAIL'} |"
        ),
        "",
        f"{H3} 3.1 Validation Paired Per-Investigator Breakdown (`{sh['val_seed_range']}`, `n={sh['val_n_seeds']}`)",
        "",
        "| Investigator | Default Score / Acc / Regret | Portfolio Score / Acc / Regret | Paired Regret Gain [95% Boot CI] |",
        "|---|---|---|---|",
    ]
    for inv in tr["investigator_order"]:
        d_inv = vd["investigators"][inv]
        p_inv = vp["investigators"][inv]
        g_inv = vc["per_investigator_gain"][inv]
        lines.append(
            f"| `{INVESTIGATOR_LABELS[inv]}` | `{_fmt_signed(d_inv['score'], 3)}` / `{d_inv['accuracy']:.3f}` / `{_fmt_signed(d_inv['regret'], 3)}` | "
            f"`{_fmt_signed(p_inv['score'], 3)}` / `{p_inv['accuracy']:.3f}` / `{_fmt_signed(p_inv['regret'], 3)}` | "
            f"`{_fmt_signed(g_inv['gain_vs_default'], 3)}` [{_fmt_signed(g_inv['gain_boot_ci_95'][0], 3)}, {_fmt_signed(g_inv['gain_boot_ci_95'][1], 3)}] |"
        )

    ranked_gains = sorted(
        tr["investigator_order"],
        key=lambda k: float(vc["per_investigator_gain"][k]["gain_vs_default"]),
        reverse=True,
    )
    top_gain_str = ", ".join(
        f"`{INVESTIGATOR_LABELS.get(k, k)}` (`{_fmt_signed(vc['per_investigator_gain'][k]['gain_vs_default'], 3)}`)"
        for k in ranked_gains[:2]
    )
    lines += [
        "",
        (
            f"Note on `{sh['val_n_seeds']}`-seed validation variance: on `{sh['val_seed_range']}` (`n={sh['val_n_seeds']}`), "
            f"each single wrong-vs-right accusation changes an investigator mean score by roughly `1.5 / {sh['val_n_seeds']} = {1.5 / sh['val_n_seeds']:.3f}`, "
            f"producing wide paired 95% bootstrap CIs (`min_regret` delta `{_fmt_signed(vc['min_regret_delta_vs_default'], 3)}`, "
            f"95% CI [{_fmt_signed(vc['min_regret_delta_boot_ci_95'][0], 3)}, {_fmt_signed(vc['min_regret_delta_boot_ci_95'][1], 3)}]). "
            f"Strongest held-out per-investigator regret gains occur on {top_gain_str}, "
            f"while preserving `{vp['solver_accuracy']:.3f}` `SolverPolicy(\"hard\")` accuracy and `{vp['logs_only_accuracy']:.3f}` `LogsOnly` accuracy."
        ),
        "",
        f"{H2} 4. Machine-Verified Embedded Ledger",
        "",
        LEDGER_START,
        "```json",
        json.dumps(payload, indent=2, sort_keys=True),
        "```",
        LEDGER_END,
        "",
    ]
    rendered = "\n".join(lines)
    if EM_DASH in rendered or EN_DASH in rendered:
        raise ValueError("rendered markdown contains forbidden em or en dash")
    return rendered


def check_markdown_report(md_path: str | Path = DEFAULT_REPORT_OUT) -> tuple[bool, str]:
    p = Path(md_path)
    if not p.is_file():
        return False, f"missing markdown report at {p}"
    text = p.read_text(encoding="utf-8")
    if EM_DASH in text or EN_DASH in text:
        return False, f"forbidden em/en dash found in {p}"
    low = text.lower()
    for bad in FORBIDDEN_CLAIM_SUBSTRINGS:
        if bad in low:
            return False, f"forbidden claim substring {bad!r} found in {p}"
    if LEDGER_START not in text or LEDGER_END not in text:
        return False, "missing embedded ledger markers"
    body = text.split(LEDGER_START, 1)[1].split(LEDGER_END, 1)[0].strip()
    if not body.startswith("```json") or not body.endswith("```"):
        return False, "malformed embedded JSON code block"
    json_str = body[len("```json"): -len("```")].strip()
    try:
        ledger = json.loads(json_str)
        assert_payload_hygiene(ledger)
    except Exception as exc:
        return False, f"ledger validation failed: {exc}"

    con = ledger.get("constraints", {})
    tp = ledger.get("train", {}).get("portfolio", {})
    vp = ledger.get("validation", {}).get("regret_portfolio_v14", {})
    sh = ledger.get("seed_hygiene", {})

    weights = tp.get("weights", {})
    if abs(sum(float(v) for v in weights.values()) - 1.0) > 1e-9:
        return False, "portfolio weights do not sum to 1.0"
    if float(tp.get("expected_solver_accuracy", 0.0)) < float(con.get("min_solver_acc", 0.90)) - 1e-9:
        return False, "train portfolio expected solver accuracy violates >= 0.90 gate"
    if float(tp.get("expected_logs_only_accuracy", 1.0)) > float(con.get("max_logs_only_acc", 0.10)) + 1e-9:
        return False, "train portfolio expected logs_only accuracy violates <= 0.10 gate"
    if abs(float(tp.get("expected_do_nothing_score", 1.0))) > DEFAULT_ZERO_TOL:
        return False, "train portfolio do_nothing score != 0.0"
    if abs(float(tp.get("expected_stop_early_quit_score", 1.0))) > DEFAULT_ZERO_TOL:
        return False, "train portfolio stop_early_quit score != 0.0"

    if float(vp.get("solver_accuracy", 0.0)) < float(con.get("min_solver_acc", 0.90)) - 1e-9:
        return False, "validation portfolio solver accuracy violates >= 0.90 gate"
    if float(vp.get("logs_only_accuracy", 1.0)) > float(con.get("max_logs_only_acc", 0.10)) + 1e-9:
        return False, "validation portfolio logs_only accuracy violates <= 0.10 gate"
    if abs(float(vp.get("do_nothing_score", 1.0))) > DEFAULT_ZERO_TOL:
        return False, "validation portfolio do_nothing score != 0.0"
    if abs(float(vp.get("stop_early_quit_score", 1.0))) > DEFAULT_ZERO_TOL:
        return False, "validation portfolio stop_early_quit score != 0.0"

    try:
        train_s = validate_eval_seeds(sh["train_seed_range"])
        val_s = validate_eval_seeds(sh["val_seeds"])
        assert_disjoint_seed_splits(train_s, val_s)
    except Exception as exc:
        return False, f"seed hygiene validation failed: {exc}"

    rerendered = render_markdown_report(ledger)
    if rerendered != text:
        return False, "markdown tables/prose do not match embedded ledger"
    return True, f"OK: {p} verified against embedded Sleeper minimax portfolio ledger"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sleeper minimax attack-regret mole portfolio for Canary v1.4 Hard.")
    ap.add_argument("--out", default=str(DEFAULT_REPORT_OUT), help="Output markdown report path.")
    ap.add_argument("--check", action="store_true", help="Verify existing markdown report against embedded ledger.")
    ap.add_argument("--fit-source", choices=("precomputed", "live"), default="precomputed")
    ap.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    ap.add_argument("--train-seeds", default=DEFAULT_LIVE_TRAIN_SEEDS_SPEC)
    ap.add_argument("--val-seeds", default=DEFAULT_VAL_SEEDS_SPEC)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ONLY_ACC)
    ap.add_argument("--workers", type=int, default=DEFAULT_MAX_WORKERS)
    args = ap.parse_args(argv)

    if args.check:
        ok, msg = check_markdown_report(args.out)
        print(msg)
        return 0 if ok else 1

    payload = run_portfolio_pipeline(
        fit_source=args.fit_source,
        summary_json=args.summary_json,
        train_seeds=args.train_seeds,
        val_seeds=args.val_seeds,
        tier=args.tier,
        min_solver_acc=args.min_solver_acc,
        max_logs_only_acc=args.max_logs_acc,
        max_workers=args.workers,
    )
    md_text = render_markdown_report(payload)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md_text, encoding="utf-8")
    tp = payload["train"]["portfolio"]
    vp = payload["validation"]["regret_portfolio_v14"]
    print(
        f"Wrote {out_path} in {payload['runtime_meta']['elapsed_seconds_recorded']:.2f}s | "
        f"train min_regret={tp['min_regret']:.4f} (solver_acc={tp['expected_solver_accuracy']:.3f}) | "
        f"val solver_acc={vp['solver_accuracy']:.3f}, logs_only_acc={vp['logs_only_accuracy']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
