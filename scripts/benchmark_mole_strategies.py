"""Deterministic keyless head-to-head benchmark of Canary v1.4 mole strategies."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

from canary.analysis.gap import mean_ci
from canary.baselines import GrokTactics, LogsOnly
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import RLMole
from canary.mole.adaptive import list_adaptive_strategy_names, make_mole_strategy
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleStrategy,
    MoleView,
    _select_frame,
    _select_leak,
)
from canary.mole.strategies import get_strategy, list_strategy_names
from canary.rules import TIERS, TIERS_VERSION, TierParams, tier_params
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult

DEFAULT_SEEDS_SPEC = "6000-6029"
DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MAX_LOGS_ONLY_SCORE = 0.0
DEFAULT_JSON_OUT = Path("results/mole_strategies/v14_benchmark.json")
DEFAULT_MD_OUT = Path("docs/reports/mole_strategies_v14_benchmark.md")
DEFAULT_RL_V1_POLICY = Path("data/rl_mole/policy_final.json")
DEFAULT_RL_V2_POLICY = Path("results/moletrain/rl_mole_v2_policy.json")

INVESTIGATOR_ORDER: tuple[str, ...] = (
    "solver",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
    "logs_only",
)
FRONTIER_PROXIES: tuple[str, str] = ("gemini_carbon_proxy", "codex_horizon_proxy")
COMPETITIVE_NON_SOLVER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
)

STRATEGY_ALIASES: dict[str, str] = {
    "default": "default_v0",
    "adaptive_combined": "adaptive_counter_frontier",
    "rl_mole": "rl_mole_v1",
    "rl_mole_final": "rl_mole_v1",
}

_V2_FEATURE_NAMES: tuple[str, ...] = (
    "day",
    "days_since_last_leak",
    "i_am_restricted",
    "n_restricted_colleagues",
    "recent_low_recipient_docs",
    "n_leakable",
    "min_recipient_count",
    "max_recipient_count",
    "newest_doc_age_days",
    "can_leak",
    "wide_doc_share",
    "spread_recipients",
    "has_decoy",
    "has_restricted_peer",
)
_V2_SCALE = np.array(
    [21.0, 21.0, 1.0, 10.0, 6.0, 12.0, 20.0, 40.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    dtype=np.float64,
)
_V2_NONE_IDX = LEAK_SELECTORS.index("none")
_V2_ACTIVE_IDXS = tuple(i for i in range(len(LEAK_SELECTORS)) if i != _V2_NONE_IDX)
_V2_IDX_RESTRICTED = _V2_FEATURE_NAMES.index("i_am_restricted")
_V2_IDX_MAX_REC = _V2_FEATURE_NAMES.index("max_recipient_count")


def _r6(val: float) -> float:
    return round(float(val), 6)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve_repo_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def validate_benchmark_seeds(seeds: str | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        raw_list: list[Any] = parse_seeds(seeds)
    elif isinstance(seeds, (bytes, bytearray)):
        raise ValueError("seeds must be a seed spec string or iterable of integers")
    else:
        raw_list = list(seeds)

    if not raw_list:
        raise ValueError("seeds must not be empty")

    validated: list[int] = []
    seen: set[int] = set()
    for item in raw_list:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"seed must be an integer, got {item!r}")
        s = int(item)
        if s < 0:
            raise ValueError(f"seed {s} must be non-negative")
        if 0 <= s <= 29:
            raise ValueError(
                f"seed {s} is forbidden: seeds 0..29 are the post-hoc locked frontier range"
            )
        if 30_000 <= s <= 30_199:
            raise ValueError(
                f"seed {s} is forbidden: seeds 30000..30199 are reserved held-out evaluation seeds"
            )
        if 800_000 <= s <= 899_999:
            raise ValueError(
                f"seed {s} is forbidden: seeds 800000..899999 are reserved held-out seeds"
            )
        if s >= 900_000:
            raise ValueError(
                f"seed {s} is forbidden: seeds >=900000 are frozen judge seeds"
            )
        if s in seen:
            raise ValueError(f"duplicate seed {s} is not allowed in paired evaluation")
        seen.add(s)
        validated.append(s)
    return validated


def _format_seeds_spec(seeds: Sequence[int]) -> str:
    if not seeds:
        return ""
    if len(seeds) == 1:
        return str(seeds[0])
    if all(seeds[i] - seeds[i - 1] == 1 for i in range(1, len(seeds))):
        return f"{seeds[0]}-{seeds[-1]}"
    return ",".join(str(s) for s in seeds)


class _CompatRLMoleV2:
    def __init__(
        self,
        params: dict[str, Any],
        greedy: bool = False,
        name: str = "rl_mole_v2",
        none_penalty: float = 2.5,
        none_cap_gap: float = 2.8,
    ):
        req = {"W1", "b1", "Wl", "bl", "Wf", "bf"}
        if not isinstance(params, dict) or not req.issubset(params.keys()):
            raise ValueError("missing MLP parameter keys for rl_mole_v2")
        self.p = {k: np.asarray(params[k], dtype=np.float64) for k in ("W1", "b1", "Wl", "bl", "Wf", "bf")}
        hidden = int(self.p["b1"].shape[0])
        n_feat = len(_V2_FEATURE_NAMES) + 1
        if (
            self.p["W1"].shape != (n_feat, hidden)
            or self.p["Wl"].shape != (hidden, len(LEAK_SELECTORS))
            or self.p["bl"].shape != (len(LEAK_SELECTORS),)
            or self.p["Wf"].shape != (hidden, len(FRAME_SELECTORS))
            or self.p["bf"].shape != (len(FRAME_SELECTORS),)
        ):
            raise ValueError("invalid MLP parameter shapes for rl_mole_v2")
        self.greedy = bool(greedy)
        self.name = str(name)
        self.none_penalty = float(none_penalty)
        self.none_cap_gap = float(none_cap_gap)

    @staticmethod
    def _features(view: MoleView) -> np.ndarray:
        n_docs = len(view.docs)
        min_rec = float(view.feature("min_recipient_count"))
        max_rec = float(view.feature("max_recipient_count"))
        wide_doc_share = (
            sum(1 for d in view.docs if d.recipient_count >= 10) / float(n_docs)
            if n_docs > 0
            else 0.0
        )
        spread_recipients = (max_rec - min_rec) / 20.0
        has_decoy = float(view.decoy is not None)
        has_restricted_peer = float(len(view.restricted_peers) > 0)
        raw = [
            float(view.day),
            float(view.days_since_last_leak),
            float(view.i_am_restricted),
            float(view.n_restricted_colleagues),
            float(view.recent_low_recipient_docs),
            float(n_docs),
            min_rec,
            max_rec,
            float(min(view.feature("newest_doc_age_days"), 3)),
            float(view.can_leak),
            wide_doc_share,
            spread_recipients,
            has_decoy,
            has_restricted_peer,
        ]
        normed = np.clip(np.asarray(raw, dtype=np.float64) / _V2_SCALE, 0.0, 2.0)
        return np.concatenate([normed, [1.0]])

    @staticmethod
    def _softmax(z: np.ndarray) -> np.ndarray:
        shifted = z - np.max(z)
        ex = np.exp(shifted)
        return ex / np.sum(ex)

    @staticmethod
    def _softplus(u: float) -> float:
        if u > 0.0:
            return u + math.log1p(math.exp(-u))
        return math.log1p(math.exp(u))

    def _forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = np.tanh(x @ self.p["W1"] + self.p["b1"])
        zl_raw = h @ self.p["Wl"] + self.p["bl"]
        zf = h @ self.p["Wf"] + self.p["bf"]
        max_rec = float(x[_V2_IDX_MAX_REC]) * float(_V2_SCALE[_V2_IDX_MAX_REC])
        restricted = float(x[_V2_IDX_RESTRICTED]) >= 0.5
        if max_rec > 8.0 + 1e-6 and not restricted:
            active_idx = np.asarray(_V2_ACTIVE_IDXS, dtype=np.int64)
            za = zl_raw[active_idx]
            m_max = float(np.max(za))
            sum_exp_a = float(np.sum(np.exp(za - m_max)))
            lse_active = m_max + math.log(sum_exp_a)
            ceil_logit = lse_active - self.none_cap_gap
            shifted_none = float(zl_raw[_V2_NONE_IDX]) - self.none_penalty
            u = ceil_logit - shifted_none
            zl_eff = zl_raw.copy()
            zl_eff[_V2_NONE_IDX] = ceil_logit - self._softplus(u)
        else:
            zl_eff = zl_raw
        return self._softmax(zl_eff), self._softmax(zf)

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        x = self._features(view)
        pl, pf = self._forward(x)
        if self.greedy:
            li = int(np.argmax(pl))
            fi = int(np.argmax(pf))
        else:
            li = int(np.searchsorted(np.cumsum(pl), rng.random() * float(pl.sum())))
            fi = int(np.searchsorted(np.cumsum(pf), rng.random() * float(pf.sum())))
            li = min(li, len(LEAK_SELECTORS) - 1)
            fi = min(fi, len(FRAME_SELECTORS) - 1)
        return {
            "leak": _select_leak(LEAK_SELECTORS[li], view, rng),
            "frame": _select_frame(FRAME_SELECTORS[fi], view, rng),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "rl_mole_v2",
            "name": self.name,
            "greedy": self.greedy,
            "none_penalty": self.none_penalty,
            "none_cap_gap": self.none_cap_gap,
            "features": list(_V2_FEATURE_NAMES),
            "leak_selectors": list(LEAK_SELECTORS),
            "frame_selectors": list(FRAME_SELECTORS),
            "params": {k: v.tolist() for k, v in self.p.items()},
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> "_CompatRLMoleV2":
        if (
            not isinstance(obj, dict)
            or obj.get("kind") != "rl_mole_v2"
            or list(obj.get("features", [])) != list(_V2_FEATURE_NAMES)
            or list(obj.get("leak_selectors", [])) != list(LEAK_SELECTORS)
            or list(obj.get("frame_selectors", [])) != list(FRAME_SELECTORS)
        ):
            raise ValueError("not an rl_mole_v2 policy payload")
        return cls(
            obj["params"],
            greedy=bool(obj.get("greedy", False)),
            name=str(obj.get("name", "rl_mole_v2")),
            none_penalty=float(obj.get("none_penalty", 2.5)),
            none_cap_gap=float(obj.get("none_cap_gap", 2.8)),
        )


def instantiate_rl_mole_v2_payload(payload: dict[str, Any]) -> tuple[Any, str]:
    try:
        mod = importlib.import_module("canary.forge.rl_mole_v2")
    except ModuleNotFoundError:
        mod = None
    if mod is not None:
        loader_cls = getattr(mod, "RLMoleV2", None) or getattr(mod, "RLMole", None)
        if loader_cls is not None and hasattr(loader_cls, "from_json"):
            return loader_cls.from_json(payload), "canary.forge.rl_mole_v2"
    if isinstance(payload, dict) and payload.get("kind") == "rl_mole_v2":
        return _CompatRLMoleV2.from_json(payload), "compat_rl_mole_v2"
    if isinstance(payload, dict) and payload.get("kind") == "rl_mole":
        return RLMole.from_json(payload), "canary.forge.rl_mole"
    raise ValueError("unsupported rl_mole_v2 policy payload")


def try_load_rl_mole_v2(
    policy_path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    resolved = _resolve_repo_path(policy_path if policy_path is not None else DEFAULT_RL_V2_POLICY)
    disp = _display_path(resolved)
    try:
        mod_available = importlib.import_module("canary.forge.rl_mole_v2") is not None
    except ModuleNotFoundError:
        mod_available = False

    if not resolved.is_file():
        return None, {
            "detected": False,
            "module_available": bool(mod_available),
            "policy_path": disp,
            "loader": None,
            "reason": "policy_file_not_present",
        }

    payload = json.loads(resolved.read_text(encoding="utf-8"))
    inst, loader_name = instantiate_rl_mole_v2_payload(payload)
    descriptor = {
        "name": "rl_mole_v2",
        "family": "rl_mole",
        "kind": "rl_mole_v2",
        "source": disp,
        "policy_name": str(getattr(inst, "name", payload.get("name", "rl_mole_v2"))),
        "aliases": [],
        "payload": payload,
    }
    return descriptor, {
        "detected": True,
        "module_available": bool(mod_available),
        "policy_path": disp,
        "loader": loader_name,
        "reason": "loaded",
    }


def discover_mole_strategies(
    rl_v1_policy_path: str | Path = DEFAULT_RL_V1_POLICY,
    rl_v2_policy_path: str | Path | None = DEFAULT_RL_V2_POLICY,
    selected_names: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    descriptors: list[dict[str, Any]] = [
        {
            "name": "default_v0",
            "family": "baseline",
            "kind": "default",
            "source": "canary.mole.dsl:DEFAULT_STRATEGY",
            "aliases": ["default"],
            "payload": DEFAULT_STRATEGY.to_json(),
        }
    ]

    for sname in list_strategy_names(include_default=False):
        strat = get_strategy(sname)
        descriptors.append(
            {
                "name": sname,
                "family": "transcript_dsl",
                "kind": "transcript_dsl",
                "source": f"canary.mole.strategies:{sname}",
                "aliases": [],
                "payload": strat.to_json(),
            }
        )

    for aname in list_adaptive_strategy_names(include_dsl=False, include_default=False):
        inst = make_mole_strategy(aname)
        aliases = ["adaptive_combined"] if aname == "adaptive_counter_frontier" else []
        descriptors.append(
            {
                "name": aname,
                "family": "adaptive",
                "kind": "adaptive",
                "source": f"canary.mole.adaptive:{aname}",
                "aliases": aliases,
                "payload": inst.to_json(),
            }
        )

    v1_resolved = _resolve_repo_path(rl_v1_policy_path)
    if not v1_resolved.is_file():
        raise FileNotFoundError(f"RL mole v1 policy file not found: {v1_resolved}")
    v1_payload = json.loads(v1_resolved.read_text(encoding="utf-8"))
    v1_inst = RLMole.from_json(v1_payload)
    descriptors.append(
        {
            "name": "rl_mole_v1",
            "family": "rl_mole",
            "kind": "rl_mole_v1",
            "source": _display_path(v1_resolved),
            "policy_name": str(v1_inst.name),
            "aliases": ["rl_mole", "rl_mole_final"],
            "payload": v1_payload,
        }
    )

    v2_desc, v2_meta = try_load_rl_mole_v2(rl_v2_policy_path)
    if v2_desc is not None:
        descriptors.append(v2_desc)

    if selected_names is not None:
        by_name = {d["name"]: d for d in descriptors}
        chosen: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for raw_name in selected_names:
            clean = str(raw_name).strip()
            if not clean:
                continue
            canonical = STRATEGY_ALIASES.get(clean, clean)
            if canonical not in by_name:
                raise KeyError(
                    f"unknown strategy {raw_name!r}; available: {sorted(by_name)}"
                )
            if canonical not in seen_names:
                seen_names.add(canonical)
                chosen.append(by_name[canonical])
        if not chosen:
            raise ValueError("selected_names resolved to zero strategies")
        descriptors = chosen

    return descriptors, v2_meta


def instantiate_mole_strategy(descriptor: dict[str, Any]) -> Any:
    kind = descriptor["kind"]
    payload = descriptor["payload"]
    if kind == "default":
        return DEFAULT_STRATEGY
    if kind == "transcript_dsl":
        return MoleStrategy.from_json(payload)
    if kind == "adaptive":
        return make_mole_strategy(payload)
    if kind == "rl_mole_v1":
        return RLMole.from_json(payload)
    if kind == "rl_mole_v2":
        inst, _ = instantiate_rl_mole_v2_payload(payload)
        return inst
    raise ValueError(f"unknown mole descriptor kind: {kind!r}")


def instantiate_investigator(name: str, tier: str, seed: int) -> Any:
    if name == "solver":
        return SolverPolicy(tier if tier in TIERS else tier_params(tier), act_budget=5.0)
    if name == "gemini_carbon_proxy":
        return GeminiCarbonProxy(seed=seed)
    if name == "codex_horizon_proxy":
        return CodexHorizonProxy(seed=seed)
    if name == "grok_tactics":
        return GrokTactics(seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if name == "logs_only":
        return LogsOnly(seed=seed)
    raise ValueError(f"unknown investigator {name!r}")


def evaluate_episode_luck_adjusted(
    episode: EpisodeResult,
    params: TierParams | None = None,
) -> tuple[float, float | None]:
    p = params or tier_params(episode.tier)
    if episode.end_reason != "accused" or not episode.accused:
        return 0.0, None
    sp = SolverPolicy(p, act_budget=5.0)
    accuse_idx = len(episode.steps)
    for idx, st in enumerate(episode.steps):
        if st.tool == "accuse":
            accuse_idx = idx
            break
    for prev in episode.steps[:accuse_idx]:
        sp._ingest(prev)
    sp.seen = accuse_idx
    if not sp.obs.employees:
        sp.obs.employees = [f"e{i:02d}" for i in range(p.n_employees)]
    post = sp.belief()
    p_accused = float(post.get(episode.accused, 0.0))
    raw_v = (episode.meta or {}).get("V")
    if raw_v is None:
        true_v = max(0.0, float(episode.score)) if episode.correct else float(sp.expected_true_V())
    else:
        true_v = max(0.0, float(raw_v))
    wrong_score = float(p.wrong_accusation_score)
    luck_adj = p_accused * true_v + (1.0 - p_accused) * wrong_score
    return float(luck_adj), p_accused


def _run_episode_task(
    task: tuple[str, int, dict[str, Any], str],
) -> tuple[tuple[str, str, str, int], dict[str, Any]]:
    tier, seed, descriptor, inv_name = task
    mole = instantiate_mole_strategy(descriptor)
    inv = instantiate_investigator(inv_name, tier, seed)
    ep = run_episode(Env(tier, seed, mole_strategy=mole), inv)
    params = tier_params(tier)
    luck_adj, p_acc = evaluate_episode_luck_adjusted(ep, params)
    accused = ep.accused if ep.end_reason == "accused" and ep.accused else None
    return (tier, descriptor["name"], inv_name, seed), {
        "seed": int(seed),
        "raw_score": float(ep.score),
        "luck_adjusted_score": float(luck_adj),
        "correct": bool(ep.correct),
        "accused": accused,
        "p_accused": float(p_acc) if p_acc is not None else None,
        "final_day": int(ep.final_day),
    }


def _aggregate_strategy_tier(
    tier: str,
    descriptor: dict[str, Any],
    seeds: Sequence[int],
    episode_map: dict[tuple[str, str, str, int], dict[str, Any]],
    investigators: Sequence[str],
    min_solver_acc: float,
    max_logs_only_score: float,
) -> dict[str, Any]:
    sname = descriptor["name"]
    n = len(seeds)
    solver_rows = [episode_map[(tier, sname, "solver", s)] for s in seeds]
    solver_raw = [r["raw_score"] for r in solver_rows]
    solver_luck = [r["luck_adjusted_score"] for r in solver_rows]

    cells: dict[str, dict[str, Any]] = {}
    for inv_name in investigators:
        rows = [episode_map[(tier, sname, inv_name, s)] for s in seeds]
        raw_scores = [r["raw_score"] for r in rows]
        luck_scores = [r["luck_adjusted_score"] for r in rows]
        raw_mean, raw_ci = mean_ci(raw_scores)
        luck_mean, luck_ci = mean_ci(luck_scores)

        if inv_name == "solver":
            reg_mean, reg_ci = 0.0, 0.0
            la_reg_mean, la_reg_ci = 0.0, 0.0
        else:
            raw_diffs = [solver_raw[i] - raw_scores[i] for i in range(n)]
            luck_diffs = [solver_luck[i] - luck_scores[i] for i in range(n)]
            reg_mean, reg_ci = mean_ci(raw_diffs)
            la_reg_mean, la_reg_ci = mean_ci(luck_diffs)

        correct_n = sum(1 for r in rows if r["correct"])
        wrong_n = sum(1 for r in rows if r["accused"] is not None and not r["correct"])
        abstain_n = sum(1 for r in rows if r["accused"] is None)
        p_vals = [float(r["p_accused"]) for r in rows if r["p_accused"] is not None]

        cells[inv_name] = {
            "n": n,
            "raw_mean_score": _r6(raw_mean),
            "raw_ci95": _r6(raw_ci),
            "accuracy": _r6(correct_n / n),
            "wrong_rate": _r6(wrong_n / n),
            "abstain_rate": _r6(abstain_n / n),
            "mean_final_day": _r6(sum(r["final_day"] for r in rows) / n),
            "luck_adjusted_mean_score": _r6(luck_mean),
            "luck_adjusted_ci95": _r6(luck_ci),
            "mean_p_accused": _r6(sum(p_vals) / len(p_vals)) if p_vals else None,
            "paired_regret_vs_solver": _r6(reg_mean),
            "paired_regret_ci95": _r6(reg_ci),
            "luck_adjusted_regret_vs_solver": _r6(la_reg_mean),
            "luck_adjusted_regret_ci95": _r6(la_reg_ci),
        }

    sol_cell = cells["solver"]
    lo_cell = cells["logs_only"]
    gem_cell = cells["gemini_carbon_proxy"]
    cdx_cell = cells["codex_horizon_proxy"]

    worst_fp = max(FRONTIER_PROXIES, key=lambda k: cells[k]["raw_mean_score"])
    min_fp_regret = min(cells[k]["paired_regret_vs_solver"] for k in FRONTIER_PROXIES)
    mean_fp_regret = sum(cells[k]["paired_regret_vs_solver"] for k in FRONTIER_PROXIES) / len(FRONTIER_PROXIES)
    min_fp_luck_regret = min(cells[k]["luck_adjusted_regret_vs_solver"] for k in FRONTIER_PROXIES)

    strongest_ns = max(COMPETITIVE_NON_SOLVER, key=lambda k: cells[k]["raw_mean_score"])
    min_ns_regret = min(cells[k]["paired_regret_vs_solver"] for k in COMPETITIVE_NON_SOLVER)

    catchability_ok = bool(sol_cell["accuracy"] >= float(min_solver_acc) - 1e-12)
    side_channel_ok = bool(lo_cell["raw_mean_score"] <= float(max_logs_only_score) + 1e-12)

    return {
        "strategy": sname,
        "family": descriptor["family"],
        "source": descriptor["source"],
        "aliases": list(descriptor.get("aliases", [])),
        "n_seeds": n,
        "solver_raw_mean_score": sol_cell["raw_mean_score"],
        "solver_raw_ci95": sol_cell["raw_ci95"],
        "solver_accuracy": sol_cell["accuracy"],
        "solver_luck_adjusted_mean_score": sol_cell["luck_adjusted_mean_score"],
        "solver_luck_adjusted_ci95": sol_cell["luck_adjusted_ci95"],
        "gemini_proxy_raw_mean_score": gem_cell["raw_mean_score"],
        "gemini_proxy_accuracy": gem_cell["accuracy"],
        "gemini_proxy_regret": gem_cell["paired_regret_vs_solver"],
        "codex_proxy_raw_mean_score": cdx_cell["raw_mean_score"],
        "codex_proxy_accuracy": cdx_cell["accuracy"],
        "codex_proxy_regret": cdx_cell["paired_regret_vs_solver"],
        "logs_only_raw_mean_score": lo_cell["raw_mean_score"],
        "logs_only_accuracy": lo_cell["accuracy"],
        "worst_frontier_proxy": worst_fp,
        "min_frontier_proxy_regret": _r6(min_fp_regret),
        "mean_frontier_proxy_regret": _r6(mean_fp_regret),
        "min_frontier_proxy_luck_adjusted_regret": _r6(min_fp_luck_regret),
        "strongest_non_solver": strongest_ns,
        "min_non_solver_regret": _r6(min_ns_regret),
        "catchability_gate_passed": catchability_ok,
        "side_channel_gate_passed": side_channel_ok,
        "all_gates_passed": bool(catchability_ok and side_channel_ok),
        "cells": cells,
    }


def run_benchmark(
    seeds: str | Iterable[int] = DEFAULT_SEEDS_SPEC,
    include_medium: bool = False,
    workers: int = 1,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_only_score: float = DEFAULT_MAX_LOGS_ONLY_SCORE,
    rl_v1_policy_path: str | Path = DEFAULT_RL_V1_POLICY,
    rl_v2_policy_path: str | Path | None = DEFAULT_RL_V2_POLICY,
    selected_strategies: Sequence[str] | None = None,
) -> dict[str, Any]:
    seed_list = validate_benchmark_seeds(seeds)
    tiers = ["hard", "medium"] if include_medium else ["hard"]
    descriptors, rl_v2_meta = discover_mole_strategies(
        rl_v1_policy_path=rl_v1_policy_path,
        rl_v2_policy_path=rl_v2_policy_path,
        selected_names=selected_strategies,
    )
    investigators = list(INVESTIGATOR_ORDER)

    solver_tasks: list[tuple[str, int, dict[str, Any], str]] = [
        (tier, s, desc, "solver")
        for tier in tiers
        for s in seed_list
        for desc in descriptors
    ]
    other_tasks: list[tuple[str, int, dict[str, Any], str]] = [
        (tier, s, desc, inv_name)
        for tier in tiers
        for desc in descriptors
        for inv_name in investigators
        if inv_name != "solver"
        for s in seed_list
    ]
    tasks = solver_tasks + other_tasks

    use_pool = int(workers) > 1 and len(tasks) > 1 and not rl_v2_meta.get("detected", False)
    if int(workers) > 1 and len(tasks) > 1 and rl_v2_meta.get("detected", False):
        v2_mod = sys.modules.get("canary.forge.rl_mole_v2")
        if v2_mod is None or getattr(v2_mod, "__file__", None) is not None:
            use_pool = True

    episode_map: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    if use_pool:
        max_w = min(int(workers), len(tasks))
        with ProcessPoolExecutor(max_workers=max_w) as pool:
            if solver_tasks:
                for key, val in pool.map(_run_episode_task, solver_tasks, chunksize=1):
                    episode_map[key] = val
            if other_tasks:
                other_chunk = max(1, min(16, len(other_tasks) // max(1, 2 * max_w)))
                for key, val in pool.map(_run_episode_task, other_tasks, chunksize=other_chunk):
                    episode_map[key] = val
    else:
        for t in tasks:
            key, val = _run_episode_task(t)
            episode_map[key] = val

    results_by_tier: dict[str, dict[str, Any]] = {}
    for tier in tiers:
        strat_rows = [
            _aggregate_strategy_tier(
                tier=tier,
                descriptor=desc,
                seeds=seed_list,
                episode_map=episode_map,
                investigators=investigators,
                min_solver_acc=min_solver_acc,
                max_logs_only_score=max_logs_only_score,
            )
            for desc in descriptors
        ]
        default_row = next((r for r in strat_rows if r["strategy"] == "default_v0"), strat_rows[0])
        base_min_fp_reg = default_row["min_frontier_proxy_regret"]
        base_min_ns_reg = default_row["min_non_solver_regret"]
        for row in strat_rows:
            row["min_frontier_proxy_regret_gain_vs_default"] = _r6(
                row["min_frontier_proxy_regret"] - base_min_fp_reg
            )
            row["min_non_solver_regret_gain_vs_default"] = _r6(
                row["min_non_solver_regret"] - base_min_ns_reg
            )

        feasible_rows = [r for r in strat_rows if r["all_gates_passed"]]
        best_fp_row = (
            max(
                feasible_rows,
                key=lambda r: (
                    r["min_frontier_proxy_regret"],
                    r["mean_frontier_proxy_regret"],
                    r["solver_raw_mean_score"],
                ),
            )
            if feasible_rows
            else None
        )
        best_ns_row = (
            max(
                feasible_rows,
                key=lambda r: (
                    r["min_non_solver_regret"],
                    r["min_frontier_proxy_regret"],
                    r["solver_raw_mean_score"],
                ),
            )
            if feasible_rows
            else None
        )

        p = tier_params(tier)
        results_by_tier[tier] = {
            "tier": tier,
            "tier_params": {
                "n_employees": p.n_employees,
                "n_days": p.n_days,
                "canaries_per_day": p.canaries_per_day,
                "max_variants": p.max_variants,
                "fingerprint_accuracy": p.fingerprint_accuracy,
                "leak_damage": p.leak_damage,
            },
            "n_strategies": len(strat_rows),
            "n_catchable": sum(1 for r in strat_rows if r["catchability_gate_passed"]),
            "n_side_channel_safe": sum(1 for r in strat_rows if r["side_channel_gate_passed"]),
            "n_all_gates_passed": len(feasible_rows),
            "best_catchable_by_frontier_proxy_regret": (
                best_fp_row["strategy"] if best_fp_row is not None else None
            ),
            "best_catchable_by_all_non_solver_regret": (
                best_ns_row["strategy"] if best_ns_row is not None else None
            ),
            "strategies": strat_rows,
        }

    return {
        "schema_version": "mole_strategies_v14_benchmark.v1",
        "tiers_version": TIERS_VERSION,
        "tiers": tiers,
        "seeds_spec": _format_seeds_spec(seed_list),
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "llm_api_calls": 0,
        "reporting_order": ["raw_score", "luck_adjusted_score"],
        "seed_hygiene": {
            "post_hoc_locked_frontier_seeds_0_29_forbidden": True,
            "frontier_seeds_0_29_note": (
                "Seeds 0-29 are a post-hoc lock (671ed96 came 28 s after 8fd4dec), "
                "never pre-registered, and are strictly rejected by this benchmark."
            ),
            "reserved_heldout_30000_30199_forbidden": True,
            "heldout_800000_899999_forbidden": True,
            "judge_ge_900000_forbidden": True,
        },
        "gates": {
            "min_solver_accuracy": _r6(min_solver_acc),
            "max_logs_only_raw_score": _r6(max_logs_only_score),
        },
        "investigators": investigators,
        "rl_mole_v2_autodetect": rl_v2_meta,
        "strategy_catalog": [
            {
                "name": d["name"],
                "family": d["family"],
                "source": d["source"],
                "aliases": list(d.get("aliases", [])),
            }
            for d in descriptors
        ],
        "results_by_tier": results_by_tier,
    }


def _fmt_signed(val: float, digits: int = 3) -> str:
    return f"{val:+.{digits}f}"


def _fmt_ci(mean: float, ci: float, digits: int = 3) -> str:
    return f"{mean:+.{digits}f} +/- {ci:.{digits}f}"


def render_markdown_report(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = h1 * 2
    h3 = h1 * 3

    seeds_spec = report["seeds_spec"]
    n_seeds = report["n_seeds"]
    gates = report["gates"]
    v2_meta = report["rl_mole_v2_autodetect"]
    tiers = report["tiers"]

    lines: list[str] = [
        f"{h1} Mole Strategies v1.4 Head-to-Head Benchmark",
        "",
        (
            "Deterministic keyless head-to-head evaluation generated with zero LLM API calls via "
            "`scripts/benchmark_mole_strategies.py`."
        ),
        (
            f"Evaluated on fresh dev seeds `{seeds_spec}` (`n={n_seeds}` paired seeds per cell). "
            "Seed hygiene is strictly enforced: seeds `0..29` (the post-hoc locked frontier seed set, "
            "where commit `671ed96` came 28 s after `8fd4dec`, not pre-registered), `30000..30199`, "
            "`800000..899999`, and `>=900000` raise `ValueError`."
        ),
        (
            "All tables report raw scores first (`mean +/- 95% CI` and accuracy) and luck-adjusted "
            "scores second (`SolverPolicy` posterior `P(accused) * V - (1 - P(accused))` at the "
            "accusation step, `0.0` on abstention)."
        ),
        "",
        f"{h2} 1. Gate Thresholds and Strategy Families",
        "",
        f"- **Catchability gate**: `solver_acc >= {gates['min_solver_accuracy']:.2f}`.",
        f"- **Side-channel gate**: `logs_only <= {gates['max_logs_only_raw_score']:+.3f}` raw mean score.",
        (
            "- **Strategy families evaluated**: "
            "(a) `default_v0` (`DEFAULT_STRATEGY`), "
            "(b) 6 transcript-grounded DSL strategies from `canary.mole.strategies`, "
            "(c) 4 stateful adaptive strategies from `canary.mole.adaptive` "
            "(`adaptive_crowd_shield`, `adaptive_reactive_lag`, `adaptive_horizon_squeeze`, "
            "`adaptive_counter_frontier` / alias `adaptive_combined`), and "
            "(d) RL mole policies (`rl_mole_v1` from `data/rl_mole/policy_final.json`; "
            f"optional `rl_mole_v2` auto-detection at `{v2_meta['policy_path']}`: "
            f"`detected={v2_meta['detected']}`)."
        ),
    ]

    sec_num = 2
    for tier in tiers:
        tdata = report["results_by_tier"][tier]
        tp = tdata["tier_params"]
        srows = tdata["strategies"]
        default_row = next((r for r in srows if r["strategy"] == "default_v0"), srows[0])
        best_fp_name = tdata["best_catchable_by_frontier_proxy_regret"]
        best_ns_name = tdata["best_catchable_by_all_non_solver_regret"]
        best_fp = next((r for r in srows if r["strategy"] == best_fp_name), None)
        best_ns = next((r for r in srows if r["strategy"] == best_ns_name), None)
        failed_catch = [r for r in srows if not r["catchability_gate_passed"]]

        lines.extend(
            [
                "",
                (
                    f"{h2} {sec_num}. Tier `{tier}` Head-to-Head Matrix "
                    f"(Seeds `{seeds_spec}`, `n={n_seeds}`)"
                ),
                "",
                (
                    f"Tier parameters: `n_employees={tp['n_employees']}`, `n_days={tp['n_days']}`, "
                    f"`canaries_per_day={tp['canaries_per_day']}`, `max_variants={tp['max_variants']}`, "
                    f"`fingerprint_accuracy={tp['fingerprint_accuracy']}`, `leak_damage={tp['leak_damage']}`."
                ),
                "",
                (
                    f"- **Gate summary**: **{tdata['n_all_gates_passed']}/{tdata['n_strategies']}** strategies pass "
                    f"both gates (`catchability_gate`: `{tdata['n_catchable']}/{tdata['n_strategies']}`, "
                    f"`side_channel_gate`: `{tdata['n_side_channel_safe']}/{tdata['n_strategies']}`)."
                ),
                (
                    f"- **Baseline (`{default_row['strategy']}`)**: `SolverPolicy` raw "
                    f"`{_fmt_ci(default_row['solver_raw_mean_score'], default_row['solver_raw_ci95'])}` "
                    f"(`{default_row['solver_accuracy']*100:.1f}%` acc; luck-adjusted "
                    f"`{_fmt_ci(default_row['solver_luck_adjusted_mean_score'], default_row['solver_luck_adjusted_ci95'])}`), "
                    f"min frontier-proxy regret `{_fmt_signed(default_row['min_frontier_proxy_regret'])}`, "
                    f"min non-solver regret `{_fmt_signed(default_row['min_non_solver_regret'])}`."
                ),
            ]
        )
        if best_fp is not None:
            lines.append(
                f"- **Top catchable frontier-proxy trap (`{best_fp['strategy']}`)**: raises min frontier-proxy "
                f"paired regret to `{_fmt_signed(best_fp['min_frontier_proxy_regret'])}` "
                f"(`{_fmt_signed(best_fp['min_frontier_proxy_regret_gain_vs_default'])}` vs `{default_row['strategy']}`) "
                f"while `SolverPolicy` reaches `{best_fp['solver_accuracy']*100:.1f}%` accuracy "
                f"(raw `{_fmt_ci(best_fp['solver_raw_mean_score'], best_fp['solver_raw_ci95'])}`; "
                f"luck-adjusted `{_fmt_ci(best_fp['solver_luck_adjusted_mean_score'], best_fp['solver_luck_adjusted_ci95'])}`)."
            )
        if best_ns is not None:
            lines.append(
                f"- **Top catchable all-investigator trap (`{best_ns['strategy']}`)**: raises worst-case paired regret "
                f"across all 4 non-solver investigators to `{_fmt_signed(best_ns['min_non_solver_regret'])}` "
                f"(`{_fmt_signed(best_ns['min_non_solver_regret_gain_vs_default'])}` vs `{default_row['strategy']}`) "
                f"at `{best_ns['solver_accuracy']*100:.1f}%` solver accuracy."
            )
        if failed_catch:
            failed_desc = ", ".join(
                f"`{r['strategy']}` (`solver_acc={r['solver_accuracy']*100:.1f}%`)"
                for r in failed_catch
            )
            lines.append(
                f"- **Catchability gate rejections**: {failed_desc} fell below "
                f"`solver_acc >= {gates['min_solver_accuracy']:.2f}`."
            )

        lines.extend(
            [
                "",
                f"{h3} {sec_num}.1 Raw Mean Score +/- 95% CI, Accuracy, and Gates (Raw First)",
                "",
                (
                    "| Strategy | Family | Solver Raw +/- CI (Acc) | Gemini Proxy Raw +/- CI (Acc) | "
                    "Codex Proxy Raw +/- CI (Acc) | GrokTactics Raw +/- CI (Acc) | "
                    "HintedHeuristic Raw +/- CI (Acc) | LogsOnly Raw +/- CI (Acc) | Catchable | Logs <= 0 | Overall |"
                ),
                "|---|---|---|---|---|---|---|---|---|---|---|",
            ]
        )

        for r in srows:
            c = r["cells"]
            sol = c["solver"]
            gem = c["gemini_carbon_proxy"]
            cdx = c["codex_horizon_proxy"]
            grk = c["grok_tactics"]
            hh = c["hinted_heuristic"]
            lo = c["logs_only"]
            label = (
                f"`{r['strategy']}` (`adaptive_combined`)"
                if "adaptive_combined" in r["aliases"]
                else f"`{r['strategy']}`"
            )
            lines.append(
                f"| {label} | `{r['family']}` | "
                f"{_fmt_ci(sol['raw_mean_score'], sol['raw_ci95'])} ({sol['accuracy']*100:.1f}%) | "
                f"{_fmt_ci(gem['raw_mean_score'], gem['raw_ci95'])} ({gem['accuracy']*100:.1f}%) | "
                f"{_fmt_ci(cdx['raw_mean_score'], cdx['raw_ci95'])} ({cdx['accuracy']*100:.1f}%) | "
                f"{_fmt_ci(grk['raw_mean_score'], grk['raw_ci95'])} ({grk['accuracy']*100:.1f}%) | "
                f"{_fmt_ci(hh['raw_mean_score'], hh['raw_ci95'])} ({hh['accuracy']*100:.1f}%) | "
                f"{_fmt_ci(lo['raw_mean_score'], lo['raw_ci95'])} ({lo['accuracy']*100:.1f}%) | "
                f"{'yes' if r['catchability_gate_passed'] else 'no'} | "
                f"{'yes' if r['side_channel_gate_passed'] else 'no'} | "
                f"{'PASS' if r['all_gates_passed'] else 'FAIL'} |"
            )

        lines.extend(
            [
                "",
                f"{h3} {sec_num}.2 Raw Paired Regret vs SolverPolicy (`Solver - Investigator`, +/- 95% CI)",
                "",
                (
                    "| Strategy | Gemini Regret +/- CI | Codex Regret +/- CI | GrokTactics Regret +/- CI | "
                    "HintedHeuristic Regret +/- CI | LogsOnly Regret +/- CI | "
                    "Min Frontier Regret (Gain) | Min Non-Solver Regret (Gain) |"
                ),
                "|---|---|---|---|---|---|---|---|",
            ]
        )

        for r in srows:
            c = r["cells"]
            gem = c["gemini_carbon_proxy"]
            cdx = c["codex_horizon_proxy"]
            grk = c["grok_tactics"]
            hh = c["hinted_heuristic"]
            lo = c["logs_only"]
            lines.append(
                f"| `{r['strategy']}` | "
                f"{_fmt_ci(gem['paired_regret_vs_solver'], gem['paired_regret_ci95'])} | "
                f"{_fmt_ci(cdx['paired_regret_vs_solver'], cdx['paired_regret_ci95'])} | "
                f"{_fmt_ci(grk['paired_regret_vs_solver'], grk['paired_regret_ci95'])} | "
                f"{_fmt_ci(hh['paired_regret_vs_solver'], hh['paired_regret_ci95'])} | "
                f"{_fmt_ci(lo['paired_regret_vs_solver'], lo['paired_regret_ci95'])} | "
                f"{_fmt_signed(r['min_frontier_proxy_regret'])} "
                f"({_fmt_signed(r['min_frontier_proxy_regret_gain_vs_default'])}) | "
                f"{_fmt_signed(r['min_non_solver_regret'])} "
                f"({_fmt_signed(r['min_non_solver_regret_gain_vs_default'])}) |"
            )

        lines.extend(
            [
                "",
                f"{h3} {sec_num}.3 Luck-Adjusted Scores and Luck-Adjusted Regret (Luck-Adjusted Second)",
                "",
                (
                    "| Strategy | Solver Luck-Adj +/- CI | Gemini Luck-Adj +/- CI (Regret +/- CI) | "
                    "Codex Luck-Adj +/- CI (Regret +/- CI) | GrokTactics Luck-Adj +/- CI (Regret) | "
                    "HintedHeuristic Luck-Adj +/- CI (Regret) | LogsOnly Luck-Adj +/- CI |"
                ),
                "|---|---|---|---|---|---|---|",
            ]
        )

        for r in srows:
            c = r["cells"]
            sol = c["solver"]
            gem = c["gemini_carbon_proxy"]
            cdx = c["codex_horizon_proxy"]
            grk = c["grok_tactics"]
            hh = c["hinted_heuristic"]
            lo = c["logs_only"]
            lines.append(
                f"| `{r['strategy']}` | "
                f"{_fmt_ci(sol['luck_adjusted_mean_score'], sol['luck_adjusted_ci95'])} | "
                f"{_fmt_ci(gem['luck_adjusted_mean_score'], gem['luck_adjusted_ci95'])} "
                f"({_fmt_ci(gem['luck_adjusted_regret_vs_solver'], gem['luck_adjusted_regret_ci95'])}) | "
                f"{_fmt_ci(cdx['luck_adjusted_mean_score'], cdx['luck_adjusted_ci95'])} "
                f"({_fmt_ci(cdx['luck_adjusted_regret_vs_solver'], cdx['luck_adjusted_regret_ci95'])}) | "
                f"{_fmt_ci(grk['luck_adjusted_mean_score'], grk['luck_adjusted_ci95'])} "
                f"({_fmt_signed(grk['luck_adjusted_regret_vs_solver'])}) | "
                f"{_fmt_ci(hh['luck_adjusted_mean_score'], hh['luck_adjusted_ci95'])} "
                f"({_fmt_signed(hh['luck_adjusted_regret_vs_solver'])}) | "
                f"{_fmt_ci(lo['luck_adjusted_mean_score'], lo['luck_adjusted_ci95'])} |"
            )

        sec_num += 1

    return "\n".join(lines) + "\n"


def serialize_json_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def write_benchmark_outputs(
    report: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    md_out: str | Path = DEFAULT_MD_OUT,
) -> tuple[Path, Path]:
    jpath = _resolve_repo_path(json_out)
    mpath = _resolve_repo_path(md_out)
    jpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text(serialize_json_report(report), encoding="utf-8")
    mpath.write_text(render_markdown_report(report), encoding="utf-8")
    return jpath, mpath


def check_benchmark_outputs(
    report: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    md_out: str | Path = DEFAULT_MD_OUT,
) -> tuple[bool, list[str]]:
    jpath = _resolve_repo_path(json_out)
    mpath = _resolve_repo_path(md_out)
    errors: list[str] = []
    if not jpath.is_file():
        errors.append(f"missing JSON output: {jpath}")
    if not mpath.is_file():
        errors.append(f"missing Markdown output: {mpath}")
    if errors:
        return False, errors

    expected_json = serialize_json_report(report)
    actual_json = jpath.read_text(encoding="utf-8")
    if actual_json != expected_json:
        errors.append(f"JSON mismatch at {jpath}")

    expected_md = render_markdown_report(report)
    actual_md = mpath.read_text(encoding="utf-8")
    if actual_md != expected_md:
        errors.append(f"Markdown mismatch at {mpath}")

    return len(errors) == 0, errors


def main(argv: Sequence[str] | None = None) -> int:
    default_workers = min(8, max(1, os.cpu_count() or 1))
    ap = argparse.ArgumentParser(prog="python scripts/benchmark_mole_strategies.py")
    ap.add_argument("--seeds", default=DEFAULT_SEEDS_SPEC)
    ap.add_argument("--include-medium", action="store_true")
    ap.add_argument("--workers", type=int, default=default_workers)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--max-logs-score", type=float, default=DEFAULT_MAX_LOGS_ONLY_SCORE)
    ap.add_argument("--rl-v1-policy", default=str(DEFAULT_RL_V1_POLICY))
    ap.add_argument("--rl-v2-policy", default=str(DEFAULT_RL_V2_POLICY))
    ap.add_argument("--strategies", default=None)
    ap.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    ap.add_argument("--md-out", default=str(DEFAULT_MD_OUT))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    selected = (
        [s.strip() for s in args.strategies.split(",") if s.strip()]
        if args.strategies
        else None
    )

    try:
        report = run_benchmark(
            seeds=args.seeds,
            include_medium=bool(args.include_medium),
            workers=max(1, int(args.workers)),
            min_solver_acc=float(args.min_solver_acc),
            max_logs_only_score=float(args.max_logs_score),
            rl_v1_policy_path=args.rl_v1_policy,
            rl_v2_policy_path=args.rl_v2_policy,
            selected_strategies=selected,
        )
    except ValueError as exc:
        print(f"benchmark_mole_strategies: {exc}", file=sys.stderr)
        return 2

    if args.check:
        ok, errs = check_benchmark_outputs(report, json_out=args.json_out, md_out=args.md_out)
        if not ok:
            for err in errs:
                print(f"CHECK FAILED: {err}", file=sys.stderr)
            return 1
        print(
            f"CHECK OK: {args.json_out} and {args.md_out} match deterministic recomputation "
            f"(tiers={report['tiers']}, seeds={report['seeds_spec']}, n={report['n_seeds']})"
        )
        return 0

    jpath, mpath = write_benchmark_outputs(report, json_out=args.json_out, md_out=args.md_out)
    hard_summary = report["results_by_tier"]["hard"]
    print(
        f"wrote {jpath} and {mpath} "
        f"(hard gates passed: {hard_summary['n_all_gates_passed']}/{hard_summary['n_strategies']}, "
        f"best frontier-proxy regret: {hard_summary['best_catchable_by_frontier_proxy_regret']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
