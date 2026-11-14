from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Callable

from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import record
from canary.gemini.sdk import genai_client
from canary.llm.base import is_retryable
from canary.rules import DEV_SEEDS, tier_params, tiers_version
from canary.solver.policy import SolverPolicy
from canary.world import generate_world

FEATURE = "multimodal_evidence"
SUBROLE = "carbon_v14_trajectory_forensics"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_VERSION = "v1.4"

FAILURE_PATTERNS = [
    "none_justified_accusation",
    "fooled_wrong_suspect",
    "premature_early_accusation",
    "horizon_below_ev_stall",
    "under_canary_exploration",
    "hidden_bleed_erosion",
]

DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accused_below_ev_threshold": {
            "type": "boolean",
            "description": (
                "True if at the vertical purple dashed investigator stop line in Panel 4, the purple star "
                "marker P(accused / stop) lies strictly below the orange dashed rational EV threshold curve "
                "1/(1+V) inside the shaded sub-EV zone; false if at or above 1/(1+V)."
            ),
        },
        "estimated_accuse_day": {
            "type": "integer",
            "description": (
                "Integer day on the Day x-axis ticks at which the vertical purple dashed investigator "
                "accusation/stop line occurs."
            ),
        },
        "hidden_bleed_gap_present": {
            "type": "boolean",
            "description": (
                "True if Panel 2 shows any day where the blue known_V curve sits strictly above the red "
                "dashed true_V curve (indicated by salmon hidden-bleed shading and coral vertical bleed "
                "stems); false if known_V and true_V coincide on every day."
            ),
        },
        "entropy_lags_solver": {
            "type": "boolean",
            "description": (
                "True if in Panel 3 the blue gemini-4-carbon Investigator H(belief) curve resolves strictly "
                "after the teal dotted SolverPolicy stop day with higher entropy along the trajectory; "
                "false if the investigator resolves on or before the SolverPolicy stop day."
            ),
        },
        "fooled_step_summary": {
            "type": "string",
            "description": (
                "Concise 2 to 4 sentence visual forensic summary referencing all 4 panels: Panel 1 posterior "
                "concentration across suspects (including MOLE, DECOY, and ACCUSED row markers when shown), "
                "Panel 2 known_V vs true_V hidden bleed and 1-or-2/day canary deployments, Panel 3 Shannon "
                "entropy H(belief) vs SolverPolicy, and Panel 4 P(accused) star vs 1/(1+V) pinpointing any "
                "fooled/sub-EV step or calibrated high-EV accusation. Use plain ASCII hyphens only."
            ),
        },
        "primary_failure_pattern": {
            "type": "string",
            "enum": FAILURE_PATTERNS,
            "description": (
                "Select none_justified_accusation when [MOLE,ACCUSED] share the same suspect row and the "
                "purple star lies above 1/(1+V); fooled_wrong_suspect when [ACCUSED] is on a different row "
                "from [MOLE] and True-mole P(mole) diverges below P(accused / stop); horizon_below_ev_stall "
                "when ringed by Horizon stop (no accuse) below 1/(1+V); premature_early_accusation when an "
                "early accusation star sits strictly below 1/(1+V)."
            ),
        },
    },
    "required": [
        "accused_below_ev_threshold",
        "estimated_accuse_day",
        "hidden_bleed_gap_present",
        "entropy_lags_solver",
        "fooled_step_summary",
        "primary_failure_pattern",
    ],
}

FORENSIC_PROMPT = (
    "You are performing 4-panel visual trajectory forensics on a real v1.4 Canary insider-leak "
    "investigation episode.\n"
    "Inspect ONLY the provided PNG chart:\n"
    "- Panel 1 shows the Suspect x Day Bayesian posterior heatmap, the vertical purple dashed investigator "
    "stop/accusation day line, and row labels marking [MOLE], [DECOY], and [ACCUSED] when replayed on a dev seed.\n"
    "- Panel 2 shows known_V (blue circles) vs true_V (red dashed squares), any shaded salmon hidden-bleed "
    "gap with vertical bleed stems where known_V > true_V, and daily canary deployment markers (single "
    "orange triangle for 1 canary/day, double red-orange diamond+triangle for 2 canaries/day on v1.4 hard).\n"
    "- Panel 3 shows posterior Shannon entropy H(belief) in bits by day for the gemini-4-carbon investigator "
    "(blue circles, vertical purple dashed stop line) vs the paired SolverPolicy on the exact same tier/seed "
    "(teal dashed squares, vertical teal dotted stop line).\n"
    "- Panel 4 shows Top-suspect posterior max P(s) (green circles), True-mole P(mole) on dev seeds (blue "
    "dotted triangles), the rational EV threshold 1/(1+V) (orange dashed diamonds) with shaded sub-EV zone "
    "below it, and the purple star P(accused / stop) at the investigator stop day (ringed in red if the "
    "episode ended at the horizon without an accuse call).\n\n"
    "Read the 4 panels carefully from their axes, curves, and markers, and return the structured JSON "
    "diagnosis. Use plain ASCII hyphens only and never use em dashes."
)

_SOLVER_CACHE: dict[tuple[str, str, int], "PairedSolverSummary"] = {}


def sanitize_text(text: str) -> str:
    return text.replace(chr(0x2014), " - ").replace(chr(0x2013), "-")


def shannon_entropy_bits(probs: list[float] | tuple[float, ...]) -> float:
    val = -sum(float(p) * math.log2(float(p)) for p in probs if float(p) > 1e-12)
    return 0.0 if abs(val) < 1e-12 else max(0.0, float(val))


def rational_ev_threshold(v: float, wrong_score: float = -1.0) -> float:
    denom = v - wrong_score
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, -wrong_score / denom))


@dataclass
class PairedSolverSummary:
    days: list[int]
    entropy_bits: list[float]
    top_posterior: list[float]
    accuse_day: int
    accused_employee: str | None
    correct: bool
    score: float
    end_reason: str


@dataclass
class CarbonEpisodeTrajectory:
    source_file: str
    cohort: str
    tier: str
    seed: int
    agent: str
    tiers_version: str
    horizon_days: int
    max_canaries_per_day: int
    dev_seed_replayed: bool
    true_mole: str | None
    framed_decoy: str | None
    employees: list[str]
    days: list[int]
    posterior_matrix: list[list[float]]
    known_v: list[float]
    true_v: list[float]
    canaries_planted: list[int]
    entropy_bits: list[float]
    solver_days: list[int]
    solver_entropy_bits: list[float]
    solver_accuse_day: int
    solver_score: float
    solver_correct: bool
    top_posterior: list[float]
    true_mole_posterior: list[float] | None
    ev_threshold: list[float]
    actual_accuse_day: int
    accused_employee: str | None
    correct: bool
    score: float
    end_reason: str
    top_posterior_at_accuse: float
    accused_posterior_at_accuse: float
    known_v_at_accuse: float
    true_v_at_accuse: float
    ev_threshold_at_accuse: float
    accused_below_ev_threshold: bool
    hidden_bleed_gap_present: bool
    max_bleed_gap: float
    total_canaries_planted: int
    max_daily_canaries_planted: int
    final_entropy_bits: float
    solver_final_entropy_bits: float
    mean_entropy_gap_bits: float
    stop_day_lag_vs_solver: int
    entropy_lags_solver: bool
    fooled_by_wrong_suspect: bool

    def ground_truth(self) -> dict[str, Any]:
        return {
            "actual_accuse_day": self.actual_accuse_day,
            "accused_employee": self.accused_employee,
            "true_mole": self.true_mole,
            "framed_decoy": self.framed_decoy,
            "correct": self.correct,
            "score": round(self.score, 6),
            "end_reason": self.end_reason,
            "top_posterior_at_accuse": round(self.top_posterior_at_accuse, 6),
            "accused_posterior_at_accuse": round(self.accused_posterior_at_accuse, 6),
            "known_v_at_accuse": round(self.known_v_at_accuse, 6),
            "true_v_at_accuse": round(self.true_v_at_accuse, 6),
            "ev_threshold_at_accuse": round(self.ev_threshold_at_accuse, 6),
            "accused_below_ev_threshold": self.accused_below_ev_threshold,
            "hidden_bleed_gap_present": self.hidden_bleed_gap_present,
            "max_bleed_gap": round(self.max_bleed_gap, 6),
            "total_canaries_planted": self.total_canaries_planted,
            "max_daily_canaries_planted": self.max_daily_canaries_planted,
            "final_entropy_bits": round(self.final_entropy_bits, 6),
            "solver_accuse_day": self.solver_accuse_day,
            "solver_score": round(self.solver_score, 6),
            "solver_correct": self.solver_correct,
            "solver_final_entropy_bits": round(self.solver_final_entropy_bits, 6),
            "mean_entropy_gap_bits": round(self.mean_entropy_gap_bits, 6),
            "stop_day_lag_vs_solver": self.stop_day_lag_vs_solver,
            "entropy_lags_solver": self.entropy_lags_solver,
            "fooled_by_wrong_suspect": self.fooled_by_wrong_suspect,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _replay_steps_into_belief(
    tier: str,
    seed: int,
    steps: list[Any],
    version: str = DEFAULT_VERSION,
) -> dict[str, Any]:
    with tiers_version(version):
        params = tier_params(tier)
        env = Env(tier, seed)
        sp = SolverPolicy(params)
        sp.obs.employees = list(env._ids)

        days: list[int] = []
        cols: list[list[float]] = []
        known_vs: list[float] = []
        true_vs: list[float] = []
        canaries: list[int] = []
        entropies: list[float] = []
        top_posts: list[float] = []
        ev_thrs: list[float] = []

        day_canaries = 0
        accused_emp: str | None = None
        accused_post_at_end: float | None = None
        accuse_day: int | None = None

        def record_day_snapshot(d: int) -> dict[str, float]:
            post = sp.belief()
            kv = float(env.visible_V())
            tv = float(env.V)
            thr = rational_ev_threshold(tv, params.wrong_accusation_score)
            col = [float(post.get(emp, 0.0)) for emp in env._ids]
            days.append(int(d))
            cols.append(col)
            known_vs.append(kv)
            true_vs.append(tv)
            canaries.append(day_canaries)
            entropies.append(shannon_entropy_bits(col))
            top_posts.append(float(max(col)) if col else 0.0)
            ev_thrs.append(float(thr))
            return post

        for st in steps:
            if env.done:
                break
            step_ok = (st.result or {}).get("ok", True)
            if st.tool == "accuse" and step_ok:
                post = record_day_snapshot(env.day)
                accuse_day = int(env.day)
                accused_emp = (st.args or {}).get("employee")
                accused_post_at_end = float(post.get(accused_emp, 0.0))
                day_canaries = 0
                env.call(st.tool, st.args or {})
                sp._ingest(env.history[-1])
                break
            if st.tool == "advance_day" and step_ok:
                record_day_snapshot(env.day)
                day_canaries = 0
                env.call(st.tool, st.args or {})
                sp._ingest(env.history[-1])
                continue
            res = env.call(st.tool, st.args or {})
            if st.tool == "plant_canary" and res.ok:
                day_canaries += 1
            sp._ingest(env.history[-1])

        capped_day = min(int(env.day), int(params.n_days))
        if not days or (accuse_day is None and days[-1] != capped_day):
            post = record_day_snapshot(capped_day)
            if accused_post_at_end is None:
                accused_post_at_end = float(post.get(accused_emp, 0.0)) if accused_emp else top_posts[-1]

        final_day = accuse_day if accuse_day is not None else int(days[-1])
        if accused_post_at_end is None:
            accused_post_at_end = top_posts[-1]

        return {
            "params": params,
            "employees": list(env._ids),
            "days": days,
            "cols": cols,
            "known_vs": known_vs,
            "true_vs": true_vs,
            "canaries": canaries,
            "entropies": entropies,
            "top_posts": top_posts,
            "ev_thrs": ev_thrs,
            "final_day": final_day,
            "accused_emp": accused_emp,
            "accused_post_at_end": float(accused_post_at_end),
        }


def run_paired_solver(
    tier: str,
    seed: int,
    version: str = DEFAULT_VERSION,
) -> PairedSolverSummary:
    cache_key = (version, tier, int(seed))
    cached = _SOLVER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    with tiers_version(version):
        params = tier_params(tier)
        s_env = Env(tier, int(seed))
        s_pol = SolverPolicy(params)
        s_res = run_episode(s_env, s_pol)
        rep = _replay_steps_into_belief(tier, int(seed), list(s_res.steps), version=version)
        out = PairedSolverSummary(
            days=list(rep["days"]),
            entropy_bits=list(rep["entropies"]),
            top_posterior=list(rep["top_posts"]),
            accuse_day=int(rep["final_day"]),
            accused_employee=s_res.accused,
            correct=bool(s_res.correct),
            score=float(s_res.score),
            end_reason=str(s_res.end_reason),
        )
        _SOLVER_CACHE[cache_key] = out
        return out


def extract_carbon_trajectory(
    episode: dict[str, Any],
    source_file: str = "",
    cohort: str = "unspecified",
    version: str = DEFAULT_VERSION,
) -> CarbonEpisodeTrajectory:
    with tiers_version(version):
        ep = to_result(episode)
        rep = _replay_steps_into_belief(ep.tier, int(ep.seed), list(ep.steps), version=version)
        params = rep["params"]
        employees: list[str] = rep["employees"]
        days: list[int] = rep["days"]
        cols: list[list[float]] = rep["cols"]
        known_vs: list[float] = rep["known_vs"]
        true_vs: list[float] = rep["true_vs"]
        canaries: list[int] = rep["canaries"]
        entropies: list[float] = rep["entropies"]
        top_posts: list[float] = rep["top_posts"]
        ev_thrs: list[float] = rep["ev_thrs"]
        final_day: int = rep["final_day"]
        accused_emp = rep["accused_emp"] if rep["accused_emp"] is not None else ep.accused
        accused_post_at_end: float = rep["accused_post_at_end"]

        n_emp = len(employees)
        matrix = [[cols[c_idx][r_idx] for c_idx in range(len(days))] for r_idx in range(n_emp)]

        is_dev = int(ep.seed) in DEV_SEEDS
        true_mole: str | None = None
        framed_decoy: str | None = None
        mole_post: list[float] | None = None
        if is_dev:
            world = generate_world(ep.tier, int(ep.seed), params)
            true_mole = world.mole
            framed_decoy = world.decoy
            if true_mole in employees:
                m_idx = employees.index(true_mole)
                mole_post = [float(matrix[m_idx][c_idx]) for c_idx in range(len(days))]

        sol = run_paired_solver(ep.tier, int(ep.seed), version=version)

        max_len = max(len(entropies), len(sol.entropy_bits), 1)
        inv_ext = [entropies[min(i, len(entropies) - 1)] for i in range(max_len)]
        sol_ext = [sol.entropy_bits[min(i, len(sol.entropy_bits) - 1)] for i in range(max_len)]
        mean_h_gap = sum(a - b for a, b in zip(inv_ext, sol_ext)) / max_len
        day_lag = int(final_day) - int(sol.accuse_day)
        lags_solver = bool(
            (day_lag > 0 and mean_h_gap > 0.05)
            or (day_lag == 0 and mean_h_gap > 0.25)
        )

        gaps = [max(0.0, kv - tv) for kv, tv in zip(known_vs, true_vs)]
        max_gap = max(gaps) if gaps else 0.0
        bleed_present = bool(max_gap > 1e-6)
        below_ev = bool(accused_post_at_end < ev_thrs[-1])
        fooled_wrong = bool(ep.end_reason == "accused" and not ep.correct)

        return CarbonEpisodeTrajectory(
            source_file=source_file,
            cohort=cohort,
            tier=ep.tier,
            seed=int(ep.seed),
            agent=ep.agent,
            tiers_version=version,
            horizon_days=int(params.n_days),
            max_canaries_per_day=int(params.canaries_per_day),
            dev_seed_replayed=is_dev,
            true_mole=true_mole,
            framed_decoy=framed_decoy,
            employees=employees,
            days=days,
            posterior_matrix=matrix,
            known_v=known_vs,
            true_v=true_vs,
            canaries_planted=canaries,
            entropy_bits=entropies,
            solver_days=sol.days,
            solver_entropy_bits=sol.entropy_bits,
            solver_accuse_day=sol.accuse_day,
            solver_score=sol.score,
            solver_correct=sol.correct,
            top_posterior=top_posts,
            true_mole_posterior=mole_post,
            ev_threshold=ev_thrs,
            actual_accuse_day=final_day,
            accused_employee=accused_emp,
            correct=bool(ep.correct),
            score=float(ep.score),
            end_reason=str(ep.end_reason),
            top_posterior_at_accuse=float(top_posts[-1]),
            accused_posterior_at_accuse=float(accused_post_at_end),
            known_v_at_accuse=float(known_vs[-1]),
            true_v_at_accuse=float(true_vs[-1]),
            ev_threshold_at_accuse=float(ev_thrs[-1]),
            accused_below_ev_threshold=below_ev,
            hidden_bleed_gap_present=bleed_present,
            max_bleed_gap=float(max_gap),
            total_canaries_planted=int(sum(canaries)),
            max_daily_canaries_planted=int(max(canaries)) if canaries else 0,
            final_entropy_bits=float(entropies[-1]),
            solver_final_entropy_bits=float(sol.entropy_bits[-1]),
            mean_entropy_gap_bits=float(mean_h_gap),
            stop_day_lag_vs_solver=int(day_lag),
            entropy_lags_solver=lags_solver,
            fooled_by_wrong_suspect=fooled_wrong,
        )


def load_carbon_v14_trajectories(
    runs_dir: str | Path,
    tiers: tuple[str, ...] = ("hard", "medium"),
    model_filter: str = DEFAULT_MODEL,
    version: str = DEFAULT_VERSION,
) -> list[CarbonEpisodeTrajectory]:
    root = Path(runs_dir).resolve()
    files = sorted(
        p for p in root.rglob("episodes.jsonl")
        if "reference" not in p.parts and "superseded" not in p.parts and "_invalid" not in p.parts
    )
    trajectories: list[CarbonEpisodeTrajectory] = []
    seen_keys: set[tuple[str, str, int]] = set()
    with tiers_version(version):
        for fp in files:
            rel = fp.relative_to(root).as_posix()
            for line in fp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ep = json.loads(line)
                if (ep.get("meta") or {}).get("valid") is False:
                    continue
                tier_name = str(ep.get("tier") or "")
                if tiers and tier_name not in tiers:
                    continue
                agent_name = str(ep.get("agent") or "")
                if model_filter and model_filter not in agent_name and model_filter not in fp.as_posix():
                    continue
                key = (agent_name, tier_name, int(ep.get("seed", -1)))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                trajectories.append(extract_carbon_trajectory(ep, source_file=rel, version=version))
    return trajectories


def select_carbon_episodes(
    runs_dir: str | Path,
    n_wrong: int = 3,
    n_high: int = 4,
    version: str = DEFAULT_VERSION,
) -> list[CarbonEpisodeTrajectory]:
    all_traj = load_carbon_v14_trajectories(runs_dir, tiers=("hard", "medium"), version=version)

    wrong_pool = [t for t in all_traj if not t.correct]
    wrong_pool.sort(
        key=lambda t: (
            0 if t.end_reason == "accused" else 1,
            0 if t.accused_below_ev_threshold else 1,
            t.accused_posterior_at_accuse,
            0 if t.tier == "hard" else 1,
            t.seed,
        )
    )
    picked_wrong = wrong_pool[:n_wrong]
    if len(picked_wrong) < n_wrong:
        lag_fallback = sorted(
            [t for t in all_traj if t.correct and t.entropy_lags_solver and t not in picked_wrong],
            key=lambda t: (-t.stop_day_lag_vs_solver, -t.mean_entropy_gap_bits, t.score, t.seed),
        )
        picked_wrong.extend(lag_fallback[: n_wrong - len(picked_wrong)])
    for t in picked_wrong:
        t.cohort = "wrong_or_fooled"

    used = {(t.agent, t.tier, t.seed) for t in picked_wrong}
    high_pool = [
        t for t in all_traj
        if (t.agent, t.tier, t.seed) not in used
        and t.correct
        and not t.accused_below_ev_threshold
        and t.actual_accuse_day >= 4
    ]

    hard_lag = sorted(
        [t for t in high_pool if t.tier == "hard" and t.entropy_lags_solver and t.stop_day_lag_vs_solver >= 2],
        key=lambda t: (-t.score, -t.stop_day_lag_vs_solver, t.seed),
    )
    hard_fast = sorted(
        [t for t in high_pool if t.tier == "hard" and not t.entropy_lags_solver and t.stop_day_lag_vs_solver <= -2],
        key=lambda t: (-t.score, t.stop_day_lag_vs_solver, t.seed),
    ) or sorted(
        [t for t in high_pool if t.tier == "hard" and not t.entropy_lags_solver],
        key=lambda t: (-t.score, t.stop_day_lag_vs_solver, t.seed),
    )
    med_lag = sorted(
        [t for t in high_pool if t.tier == "medium" and t.entropy_lags_solver and t.stop_day_lag_vs_solver >= 2],
        key=lambda t: (-t.score, -t.stop_day_lag_vs_solver, t.seed),
    )
    med_fast = sorted(
        [t for t in high_pool if t.tier == "medium" and not t.entropy_lags_solver and t.stop_day_lag_vs_solver <= -2],
        key=lambda t: (-t.score, t.stop_day_lag_vs_solver, t.seed),
    ) or sorted(
        [t for t in high_pool if t.tier == "medium" and not t.entropy_lags_solver],
        key=lambda t: (-t.score, t.stop_day_lag_vs_solver, t.seed),
    )
    rest_high = sorted(high_pool, key=lambda t: (-t.score, 0 if t.tier == "hard" else 1, t.seed))

    picked_high: list[CarbonEpisodeTrajectory] = []

    def add_high(cand: CarbonEpisodeTrajectory) -> None:
        key = (cand.agent, cand.tier, cand.seed)
        if key not in used and len(picked_high) < n_high:
            used.add(key)
            cand.cohort = "high_scoring"
            picked_high.append(cand)

    for bucket in (hard_lag[:1], hard_fast[:1], med_lag[:1], med_fast[:1], rest_high):
        for cand in bucket:
            add_high(cand)
            if len(picked_high) >= n_high:
                break

    return picked_wrong + picked_high


def render_carbon_forensic_chart(
    traj: CarbonEpisodeTrajectory,
    out_path: str | Path | None = None,
    dpi: int = 160,
) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.gridspec import GridSpec
    import matplotlib.pyplot as plt
    import numpy as np

    horizon = max(
        int(traj.horizon_days),
        max(traj.days) if traj.days else 1,
        max(traj.solver_days) if traj.solver_days else 1,
    )
    n_emp = len(traj.employees)
    mat = np.full((n_emp, horizon), np.nan, dtype=float)
    for col_idx, day in enumerate(traj.days):
        for row_idx in range(n_emp):
            mat[row_idx, day - 1] = traj.posterior_matrix[row_idx][col_idx]

    fig = plt.figure(figsize=(13.8, 16.4), facecolor="white")
    gs = GridSpec(
        4,
        2,
        figure=fig,
        width_ratios=[36.0, 1.15],
        height_ratios=[1.85, 1.0, 1.05, 1.1],
        hspace=0.58,
        wspace=0.025,
    )
    ax1 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    ax3 = fig.add_subplot(gs[2, 0], sharex=ax1)
    ax4 = fig.add_subplot(gs[3, 0], sharex=ax1)

    cmap = matplotlib.colormaps["YlGnBu"].with_extremes(bad=(0.93, 0.93, 0.94))
    im = ax1.imshow(
        mat,
        aspect="auto",
        interpolation="nearest",
        vmin=0.0,
        vmax=1.0,
        cmap=cmap,
        extent=(0.5, horizon + 0.5, n_emp - 0.5, -0.5),
    )
    cbar = fig.colorbar(im, cax=cax)
    cbar.set_label("Posterior P(mole | obs)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    ax1.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.3, zorder=6)

    ylabels: list[str] = []
    ycolors: list[str] = []
    yweights: list[str] = []
    for idx, emp in enumerate(traj.employees):
        tags: list[str] = []
        col = "black"
        wt = "normal"
        if traj.dev_seed_replayed and emp == traj.true_mole:
            tags.append("MOLE")
            col = "forestgreen"
            wt = "bold"
            ax1.axhline(idx, color="limegreen", linestyle="-.", linewidth=1.15, alpha=0.85, zorder=5)
        if traj.dev_seed_replayed and emp == traj.framed_decoy:
            tags.append("DECOY")
            if col == "black":
                col = "crimson"
            wt = "bold"
            ax1.axhline(idx, color="crimson", linestyle=":", linewidth=1.15, alpha=0.85, zorder=5)
        if emp == traj.accused_employee:
            tags.append("ACCUSED")
            if col == "black":
                col = "darkviolet"
            wt = "bold"
            if emp != traj.true_mole:
                ax1.axhline(idx, color="darkviolet", linestyle=":", linewidth=1.3, alpha=0.9, zorder=5)
        lbl = f"{emp} [{','.join(tags)}]" if tags else emp
        ylabels.append(lbl)
        ycolors.append(col)
        yweights.append(wt)

    ax1.set_yticks(list(range(n_emp)))
    ax1.set_yticklabels(ylabels, fontsize=6.4 if n_emp > 25 else 8.0)
    for tick_lbl, col, wt in zip(ax1.get_yticklabels(), ycolors, yweights):
        tick_lbl.set_color(col)
        tick_lbl.set_fontweight(wt)
    ax1.set_ylabel("Suspect ID", fontsize=9.5)
    ax1.set_title(
        f"Panel 1: Suspect x Day Bayesian Posterior Heatmap ({traj.tier} tier, N={n_emp}, H={horizon}d)",
        fontsize=11,
        loc="left",
        fontweight="bold",
    )
    for x_edge in range(1, horizon):
        ax1.axvline(x_edge + 0.5, color=(0.82, 0.82, 0.84), linewidth=0.45, alpha=0.65)

    x_days = np.array(traj.days, dtype=float)
    kv = np.array(traj.known_v, dtype=float)
    tv = np.array(traj.true_v, dtype=float)

    ax2.plot(
        x_days,
        kv,
        color="royalblue",
        linewidth=2.5,
        marker="o",
        markersize=6.2,
        label="known_V (visible value)",
        zorder=4,
    )
    ax2.plot(
        x_days,
        tv,
        color="crimson",
        linewidth=2.3,
        linestyle="--",
        marker="s",
        markersize=5.4,
        label="true_V (actual value)",
        zorder=5,
    )
    gap_mask = (kv - tv) > 1e-6
    if bool(np.any(gap_mask)):
        ax2.fill_between(
            x_days,
            tv,
            kv,
            where=gap_mask,
            interpolate=True,
            color="salmon",
            alpha=0.40,
            label="Hidden bleed gap (known_V > true_V)",
            zorder=3,
        )
        ax2.vlines(
            x_days[gap_mask],
            tv[gap_mask],
            kv[gap_mask],
            colors="orangered",
            linestyles="-",
            linewidth=1.8,
            zorder=4,
        )

    vmin_plot = max(0.0, min(0.76, float(np.min(tv)) - 0.09))
    span_v = 1.05 - vmin_plot
    one_canary_days = [d for d, c in zip(traj.days, traj.canaries_planted) if c == 1]
    two_canary_days = [d for d, c in zip(traj.days, traj.canaries_planted) if c >= 2]
    if one_canary_days:
        ax2.scatter(
            one_canary_days,
            [vmin_plot + 0.03 * span_v for _ in one_canary_days],
            marker="^",
            s=80,
            color="darkorange",
            edgecolors="black",
            linewidths=0.7,
            zorder=6,
            label="1 canary deployed",
        )
    if two_canary_days:
        ax2.scatter(
            two_canary_days,
            [vmin_plot + 0.03 * span_v for _ in two_canary_days],
            marker="D",
            s=76,
            color="orangered",
            edgecolors="black",
            linewidths=0.75,
            zorder=6,
            label="2 canaries deployed (v1.4 hard)",
        )
        ax2.scatter(
            two_canary_days,
            [vmin_plot + 0.085 * span_v for _ in two_canary_days],
            marker="^",
            s=68,
            color="orangered",
            edgecolors="black",
            linewidths=0.7,
            zorder=6,
        )
    ax2.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2, label="Investigator stop day")
    ax2.set_ylim(vmin_plot, 1.05)
    ax2.set_ylabel("Company Value V", fontsize=9.5)
    h2_handles, _ = ax2.get_legend_handles_labels()
    ax2_two_rows = len(h2_handles) > 5
    ax2.set_title(
        f"Panel 2: known_V vs true_V Hidden-Bleed Gap and Daily Canaries (cap {traj.max_canaries_per_day}/day)",
        fontsize=11,
        loc="left",
        fontweight="bold",
        pad=36 if ax2_two_rows else 25,
    )
    ax2.grid(True, linestyle=":", linewidth=0.7, color=(0.78, 0.78, 0.8))
    ax2.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.015),
        borderaxespad=0.0,
        fontsize=7.8,
        framealpha=0.92,
        ncol=3 if ax2_two_rows else 5,
    )

    h_inv = np.array(traj.entropy_bits, dtype=float)
    x_sol = np.array(traj.solver_days, dtype=float)
    h_sol = np.array(traj.solver_entropy_bits, dtype=float)

    ax3.plot(
        x_days,
        h_inv,
        color="royalblue",
        linewidth=2.5,
        marker="o",
        markersize=6.0,
        label="gemini-4-carbon H(belief) [bits]",
        zorder=5,
    )
    ax3.plot(
        x_sol,
        h_sol,
        color="teal",
        linewidth=2.3,
        linestyle="--",
        marker="s",
        markersize=5.4,
        label="Paired SolverPolicy H(belief) [bits]",
        zorder=4,
    )
    if traj.actual_accuse_day > traj.solver_accuse_day and len(x_sol) > 0:
        ext_days = np.arange(1, traj.actual_accuse_day + 1, dtype=float)
        inv_interp = np.interp(ext_days, x_days, h_inv)
        sol_interp = np.interp(ext_days, x_sol, h_sol)
        ax3.plot(
            [float(traj.solver_accuse_day), float(traj.actual_accuse_day)],
            [float(h_sol[-1]), float(h_sol[-1])],
            color="teal",
            linestyle=":",
            linewidth=1.5,
            zorder=3,
        )
        lag_mask = inv_interp > (sol_interp + 1e-6)
        if bool(np.any(lag_mask)):
            ax3.fill_between(
                ext_days,
                sol_interp,
                inv_interp,
                where=lag_mask,
                interpolate=True,
                color="lightskyblue",
                alpha=0.28,
                label="Entropy lag vs SolverPolicy",
                zorder=2,
            )
    ax3.axvline(traj.solver_accuse_day, color="teal", linestyle=":", linewidth=2.1, label="SolverPolicy stop day")
    ax3.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2, label="Investigator stop day")
    max_h = max(math.log2(max(n_emp, 2)), float(np.max(h_inv)), float(np.max(h_sol))) + 0.45
    ax3.set_ylim(-0.12, max_h)
    ax3.set_ylabel("Entropy H(belief) [bits]", fontsize=9.5)
    ax3.set_title(
        "Panel 3: Posterior Shannon Entropy H(belief) vs Paired SolverPolicy",
        fontsize=11,
        loc="left",
        fontweight="bold",
        pad=25,
    )
    ax3.grid(True, linestyle=":", linewidth=0.7, color=(0.78, 0.78, 0.8))
    ax3.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.015),
        borderaxespad=0.0,
        fontsize=7.8,
        framealpha=0.92,
        ncol=5,
    )

    p_top = np.array(traj.top_posterior, dtype=float)
    ev_thr = np.array(traj.ev_threshold, dtype=float)
    ax4.fill_between(
        x_days,
        0.0,
        ev_thr,
        color="moccasin",
        alpha=0.32,
        label="Sub-EV zone (< 1/(1+V))",
        zorder=1,
    )
    ax4.plot(
        x_days,
        p_top,
        color="seagreen",
        linewidth=2.5,
        marker="o",
        markersize=6.0,
        label="Top-suspect posterior max P(s)",
        zorder=4,
    )
    if traj.true_mole_posterior is not None:
        p_mole = np.array(traj.true_mole_posterior, dtype=float)
        ax4.plot(
            x_days,
            p_mole,
            color="dodgerblue",
            linewidth=2.0,
            linestyle=":",
            marker="^",
            markersize=5.2,
            label="True-mole P(mole) [dev]",
            zorder=5,
        )
    ax4.plot(
        x_days,
        ev_thr,
        color="darkorange",
        linewidth=2.3,
        linestyle="--",
        marker="d",
        markersize=5.2,
        label="Rational EV threshold 1/(1+V)",
        zorder=6,
    )
    ax4.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2, label="Investigator stop day")
    ax4.scatter(
        [traj.actual_accuse_day],
        [traj.accused_posterior_at_accuse],
        marker="*",
        s=255,
        color="darkviolet",
        edgecolors="black",
        linewidths=0.95,
        zorder=8,
        label="P(accused / stop)",
    )
    if traj.end_reason != "accused":
        ax4.scatter(
            [traj.actual_accuse_day],
            [traj.accused_posterior_at_accuse],
            marker="o",
            s=360,
            facecolors="none",
            edgecolors="crimson",
            linewidths=2.0,
            zorder=9,
            label="Horizon stop (no accuse)",
        )
    ax4.set_ylim(-0.04, 1.06)
    ax4.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax4.set_ylabel("Probability", fontsize=9.5)
    ax4.set_xlabel("Day", fontsize=10)
    ax4.set_title(
        "Panel 4: Top-Suspect Posterior & P(accused) Star vs Rational EV Threshold 1/(1+V)",
        fontsize=11,
        loc="left",
        fontweight="bold",
        pad=42,
    )
    ax4.grid(True, linestyle=":", linewidth=0.7, color=(0.78, 0.78, 0.8))
    ax4.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.015),
        borderaxespad=0.0,
        fontsize=7.8,
        framealpha=0.92,
        markerscale=0.72,
        ncol=3,
    )

    xticks = list(range(1, horizon + 1))
    ax1.set_xlim(0.5, horizon + 0.5)
    for ax in (ax1, ax2, ax3, ax4):
        ax.set_xticks(xticks)
        ax.set_xticklabels([str(d) for d in xticks], fontsize=8.5)
        ax.tick_params(axis="x", labelbottom=True)

    fig.suptitle("Canary v1.4 Multimodal Trajectory Forensics (4-Panel)", fontsize=13.5, fontweight="bold", y=0.988)
    fig.subplots_adjust(left=0.115, right=0.94, top=0.948, bottom=0.042)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    png_bytes = buf.getvalue()
    if out_path is not None:
        dst = Path(out_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(png_bytes)
    return png_bytes


def _extract_response_text(resp: Any) -> str:
    txt = getattr(resp, "text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    cands = getattr(resp, "candidates", None) or []
    parts = getattr(getattr(cands[0], "content", None), "parts", None) or [] if cands else []
    texts = [p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
    return "".join(texts).strip()


def analyze_carbon_chart_bytes(
    png_bytes: bytes,
    model_id: str = DEFAULT_MODEL,
    run_id: str = "",
    chart_label: str = "",
    sdk_client: Any = None,
    max_retries: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from google.genai import types

    if not png_bytes or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("png_bytes must be valid PNG image bytes")

    client = sdk_client if sdk_client is not None else genai_client()
    retries = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10")) if max_retries is None else max_retries

    img_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    txt_part = types.Part(text=FORENSIC_PROMPT)
    contents = [types.Content(role="user", parts=[img_part, txt_part])]

    cfg_kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": DIAGNOSIS_SCHEMA,
        "max_output_tokens": 4096,
    }
    if model_id.startswith(("gemini-3", "gemini-4")):
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="MEDIUM", include_thoughts=False)
    config = types.GenerateContentConfig(**cfg_kwargs)

    meta = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "chart": chart_label,
        "png_sha256_12": hashlib.sha256(png_bytes).hexdigest()[:12],
    }

    fence_re = re.compile(r"^`{3}(?:json)?|`{3}$")
    attempt = 0
    while True:
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=model_id, contents=contents, config=config)
            latency_s = time.time() - t0
            row = record(
                feature=FEATURE,
                model=model_id,
                kind="generate",
                usage=getattr(resp, "usage_metadata", None),
                latency_s=latency_s,
                ok=True,
                run_id=run_id,
                meta=meta,
            )
            raw_txt = _extract_response_text(resp)
            cleaned = fence_re.sub("", raw_txt).strip()
            parsed = json.loads(cleaned)
            pattern = sanitize_text(str(parsed["primary_failure_pattern"]).strip())
            if pattern not in FAILURE_PATTERNS:
                raise ValueError(f"unexpected primary_failure_pattern: {pattern}")
            diagnosis = {
                "accused_below_ev_threshold": bool(parsed["accused_below_ev_threshold"]),
                "estimated_accuse_day": int(parsed["estimated_accuse_day"]),
                "hidden_bleed_gap_present": bool(parsed["hidden_bleed_gap_present"]),
                "entropy_lags_solver": bool(parsed["entropy_lags_solver"]),
                "fooled_step_summary": sanitize_text(str(parsed["fooled_step_summary"]).strip()),
                "primary_failure_pattern": pattern,
            }
            usage = {
                "in": int(row["in"]),
                "out": int(row["out"]),
                "thinking": int(row["thinking"]),
                "cached": int(row["cached"]),
                "cost_usd": float(row["cost_usd"]),
                "latency_s": float(row["latency_s"]),
            }
            return diagnosis, usage
        except Exception as exc:
            latency_s = time.time() - t0
            record(
                feature=FEATURE,
                model=model_id,
                kind="generate",
                usage=None,
                latency_s=latency_s,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                run_id=run_id,
                meta=meta,
            )
            retry_ok = is_retryable(exc) or isinstance(exc, (json.JSONDecodeError, KeyError, ValueError))
            if attempt >= retries or not retry_ok:
                raise
            delay = min(2.0 * (2 ** attempt), 45.0) * (1.0 + 0.1 * random.random())
            attempt += 1
            sleep_fn(delay)


def score_carbon_diagnosis(traj: CarbonEpisodeTrajectory, diagnosis: dict[str, Any]) -> dict[str, Any]:
    est_day = int(diagnosis["estimated_accuse_day"])
    act_day = int(traj.actual_accuse_day)
    err = abs(est_day - act_day)
    pat = str(diagnosis["primary_failure_pattern"])
    if traj.correct:
        outcome_ok = pat in ("none_justified_accusation", "hidden_bleed_erosion")
    else:
        outcome_ok = pat != "none_justified_accusation"
    return {
        "threshold_match": bool(diagnosis["accused_below_ev_threshold"]) == bool(traj.accused_below_ev_threshold),
        "day_abs_error": err,
        "day_within_1": err <= 1,
        "day_exact": err == 0,
        "bleed_gap_match": bool(diagnosis["hidden_bleed_gap_present"]) == bool(traj.hidden_bleed_gap_present),
        "entropy_lag_match": bool(diagnosis["entropy_lags_solver"]) == bool(traj.entropy_lags_solver),
        "outcome_pattern_match": bool(outcome_ok),
    }


def summarize_carbon_forensics(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {
            "n_charts_analyzed": 0,
            "visual_threshold_accuracy": 0.0,
            "accuse_day_within_1_accuracy": 0.0,
            "accuse_day_exact_accuracy": 0.0,
            "hidden_bleed_gap_accuracy": 0.0,
            "entropy_lag_accuracy": 0.0,
            "outcome_pattern_accuracy": 0.0,
            "usage": {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0},
        }
    thr_ok = sum(1 for r in records if r["scoring"]["threshold_match"])
    day1_ok = sum(1 for r in records if r["scoring"]["day_within_1"])
    day0_ok = sum(1 for r in records if r["scoring"]["day_exact"])
    gap_ok = sum(1 for r in records if r["scoring"]["bleed_gap_match"])
    lag_ok = sum(1 for r in records if r["scoring"]["entropy_lag_match"])
    pat_ok = sum(1 for r in records if r["scoring"]["outcome_pattern_match"])
    usage_tot = {
        "calls": n,
        "in": sum(int(r["usage"]["in"]) for r in records),
        "out": sum(int(r["usage"]["out"]) for r in records),
        "thinking": sum(int(r["usage"]["thinking"]) for r in records),
        "cached": sum(int(r["usage"]["cached"]) for r in records),
        "cost_usd": round(sum(float(r["usage"]["cost_usd"]) for r in records), 6),
        "latency_s": round(sum(float(r["usage"]["latency_s"]) for r in records), 3),
    }
    return {
        "n_charts_analyzed": n,
        "visual_threshold_accuracy": round(thr_ok / n, 6),
        "accuse_day_within_1_accuracy": round(day1_ok / n, 6),
        "accuse_day_exact_accuracy": round(day0_ok / n, 6),
        "hidden_bleed_gap_accuracy": round(gap_ok / n, 6),
        "entropy_lag_accuracy": round(lag_ok / n, 6),
        "outcome_pattern_accuracy": round(pat_ok / n, 6),
        "usage": usage_tot,
    }
