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
from canary.gemini.ledger import record
from canary.gemini.sdk import genai_client
from canary.llm.base import is_retryable
from canary.rules import tier_params, tiers_version
from canary.solver.policy import SolverPolicy

FEATURE = "multimodal_evidence"
SUBROLE = "belief_chart_forensics"
DEFAULT_MODEL = "gemini-4-carbon"

FAILURE_PATTERNS = [
    "none_justified_accusation",
    "premature_early_accusation",
    "horizon_forced_guess",
    "under_canary_exploration",
    "hidden_bleed_erosion",
]

DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accused_below_ev_threshold": {
            "type": "boolean",
            "description": (
                "True if at the vertical accusation marker in Panel 3, the accused posterior marker "
                "lies strictly below the rational EV threshold curve 1/(1+V); false if at or above."
            ),
        },
        "estimated_accuse_day": {
            "type": "integer",
            "description": "Integer day (from the Day x-axis ticks) at which the vertical accusation line occurs.",
        },
        "hidden_bleed_gap_present": {
            "type": "boolean",
            "description": (
                "True if Panel 2 shows any day where the known_V curve sits strictly above the true_V curve "
                "(visible separation / shaded bleed gap); false if known_V and true_V coincide on every day."
            ),
        },
        "visual_diagnosis": {
            "type": "string",
            "description": (
                "Concise 2 to 4 sentence visual forensic reading referencing all three panels: posterior "
                "concentration across suspects, known_V vs true_V bleed and canary cadence, and accusation "
                "timing relative to the 1/(1+V) threshold. Do not use em dashes."
            ),
        },
        "primary_failure_pattern": {
            "type": "string",
            "enum": FAILURE_PATTERNS,
        },
    },
    "required": [
        "accused_below_ev_threshold",
        "estimated_accuse_day",
        "hidden_bleed_gap_present",
        "visual_diagnosis",
        "primary_failure_pattern",
    ],
}

FORENSIC_PROMPT = (
    "You are performing visual trajectory forensics on a 3-panel diagnostic chart from the Canary "
    "insider-leak investigation benchmark.\n"
    "Inspect ONLY the provided PNG chart:\n"
    "- Panel 1 shows the suspect by day Bayesian posterior heatmap and a vertical dashed accusation line.\n"
    "- Panel 2 shows known_V (visible company value) vs true_V (actual company value), any shaded hidden "
    "bleed gap where known_V > true_V, and canary deployment markers.\n"
    "- Panel 3 shows the top-suspect posterior curve, the rational break-even EV threshold curve 1/(1+V), "
    "the vertical dashed accusation day marker, and the purple star marking P(accused) at accusation.\n\n"
    "Read the chart carefully from its axes, curves, and markers, and return the structured JSON diagnosis. "
    "Use plain ASCII hyphens only and never use em dashes."
)


def sanitize_text(text: str) -> str:
    return text.replace("\u2014", " - ").replace("\u2013", "-")


@dataclass
class EpisodeTrajectory:
    source_file: str
    cohort: str
    tier: str
    seed: int
    agent: str
    horizon_days: int
    employees: list[str]
    days: list[int]
    posterior_matrix: list[list[float]]
    known_v: list[float]
    true_v: list[float]
    canaries_planted: list[int]
    top_posterior: list[float]
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

    def ground_truth(self) -> dict[str, Any]:
        return {
            "actual_accuse_day": self.actual_accuse_day,
            "accused_employee": self.accused_employee,
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
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rational_ev_threshold(v: float, wrong_score: float = -1.0) -> float:
    denom = v - wrong_score
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, -wrong_score / denom))


def extract_trajectory(
    episode: dict[str, Any],
    source_file: str = "",
    cohort: str = "unspecified",
    version: str = "v1.3",
) -> EpisodeTrajectory:
    with tiers_version(version):
        ep = to_result(episode)
        params = tier_params(ep.tier)
        env = Env(ep.tier, ep.seed)
        sp = SolverPolicy(params)
        sp.obs.employees = list(env._ids)

        days: list[int] = []
        cols: list[list[float]] = []
        known_vs: list[float] = []
        true_vs: list[float] = []
        canaries: list[int] = []
        top_posts: list[float] = []
        ev_thrs: list[float] = []

        day_canaries = 0
        accused_emp: str | None = ep.accused
        accused_post_at_end: float | None = None
        accuse_day: int | None = None

        def record_day_snapshot(d: int) -> dict[str, float]:
            post = sp.belief()
            kv = float(env.visible_V())
            tv = float(env.V)
            thr = rational_ev_threshold(tv, params.wrong_accusation_score)
            days.append(int(d))
            cols.append([float(post.get(emp, 0.0)) for emp in env._ids])
            known_vs.append(kv)
            true_vs.append(tv)
            canaries.append(day_canaries)
            top_posts.append(float(max(post.values())) if post else 0.0)
            ev_thrs.append(float(thr))
            return post

        for st in ep.steps:
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

        if not days or (accuse_day is None and (not days or days[-1] != env.day)):
            post = record_day_snapshot(env.day)
            if accused_post_at_end is None:
                accused_post_at_end = float(post.get(accused_emp, 0.0)) if accused_emp else top_posts[-1]

        final_day = accuse_day if accuse_day is not None else int(days[-1])
        if accused_post_at_end is None:
            accused_post_at_end = top_posts[-1]

        n_emp = len(env._ids)
        matrix = [[cols[c_idx][r_idx] for c_idx in range(len(days))] for r_idx in range(n_emp)]
        gaps = [max(0.0, kv - tv) for kv, tv in zip(known_vs, true_vs)]
        max_gap = max(gaps) if gaps else 0.0
        bleed_present = bool(max_gap > 1e-6)
        below_ev = bool(accused_post_at_end < ev_thrs[-1])

        return EpisodeTrajectory(
            source_file=source_file,
            cohort=cohort,
            tier=ep.tier,
            seed=int(ep.seed),
            agent=ep.agent,
            horizon_days=int(params.n_days),
            employees=list(env._ids),
            days=days,
            posterior_matrix=matrix,
            known_v=known_vs,
            true_v=true_vs,
            canaries_planted=canaries,
            top_posterior=top_posts,
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
        )


def load_frontier_v13_trajectories(v13_root: str | Path) -> list[EpisodeTrajectory]:
    root = Path(v13_root)
    files = sorted(
        p for p in root.glob("*/*/episodes.jsonl")
        if "reference" not in p.parts and "superseded" not in p.parts
    )
    trajectories: list[EpisodeTrajectory] = []
    with tiers_version("v1.3"):
        for fp in files:
            rel = str(fp.relative_to(root.parents[3] if len(root.parents) >= 4 else root.parent))
            for line in fp.read_text().splitlines():
                if not line.strip():
                    continue
                ep = json.loads(line)
                if (ep.get("meta") or {}).get("valid") is False:
                    continue
                if ep.get("end_reason") != "accused":
                    continue
                trajectories.append(extract_trajectory(ep, source_file=rel, version="v1.3"))
    return trajectories


def select_forensic_episodes(
    v13_root: str | Path,
    n_wrong: int = 3,
    n_high: int = 3,
) -> list[EpisodeTrajectory]:
    all_traj = load_frontier_v13_trajectories(v13_root)
    wrong_pool = [
        t for t in all_traj
        if (not t.correct) and t.accused_below_ev_threshold
    ]
    wrong_pool.sort(key=lambda t: (t.accused_posterior_at_accuse, t.tier, t.agent, t.seed))
    picked_wrong = wrong_pool[:n_wrong]
    for t in picked_wrong:
        t.cohort = "wrong_or_premature"

    high_pool = [
        t for t in all_traj
        if t.correct and (not t.accused_below_ev_threshold) and t.actual_accuse_day >= 4
    ]
    high_hard = sorted(
        [t for t in high_pool if t.tier == "hard" and t.hidden_bleed_gap_present],
        key=lambda t: (-t.score, -t.actual_accuse_day, t.agent, t.seed),
    )
    high_no_bleed = sorted(
        [t for t in high_pool if not t.hidden_bleed_gap_present],
        key=lambda t: (-t.score, t.agent, t.seed),
    )
    high_rest = sorted(
        high_pool,
        key=lambda t: (-t.score, t.tier, t.agent, t.seed),
    )

    picked_high: list[EpisodeTrajectory] = []
    seen_keys: set[tuple[str, str, int]] = set()

    def add_candidate(cand: EpisodeTrajectory) -> None:
        key = (cand.agent, cand.tier, cand.seed)
        if key not in seen_keys and len(picked_high) < n_high:
            seen_keys.add(key)
            cand.cohort = "high_scoring"
            picked_high.append(cand)

    for grp in (high_no_bleed[:2], high_hard[:1], high_rest):
        for cand in grp:
            add_candidate(cand)
            if len(picked_high) >= n_high:
                break

    return picked_wrong + picked_high


def render_forensic_chart(
    traj: EpisodeTrajectory,
    out_path: str | Path | None = None,
    dpi: int = 160,
) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.gridspec import GridSpec
    import matplotlib.pyplot as plt
    import numpy as np

    horizon = max(traj.horizon_days, max(traj.days))
    n_emp = len(traj.employees)
    mat = np.full((n_emp, horizon), np.nan, dtype=float)
    for col_idx, day in enumerate(traj.days):
        for row_idx in range(n_emp):
            mat[row_idx, day - 1] = traj.posterior_matrix[row_idx][col_idx]

    fig = plt.figure(figsize=(12.4, 11.2), facecolor="white")
    gs = GridSpec(
        3,
        2,
        figure=fig,
        width_ratios=[34, 1.1],
        height_ratios=[1.35, 1.0, 1.0],
        hspace=0.44,
        wspace=0.025,
    )
    ax1 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    ax3 = fig.add_subplot(gs[2, 0], sharex=ax1)

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

    ax1.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2)
    ax1.set_yticks(list(range(n_emp)))
    ax1.set_yticklabels(traj.employees, fontsize=7 if n_emp > 22 else 8)
    ax1.set_ylabel("Suspect ID", fontsize=9.5)
    ax1.set_title("Panel 1: Suspect x Day Bayesian Posterior Heatmap", fontsize=11, loc="left", fontweight="bold")
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
        markersize=6.5,
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
        markersize=5.5,
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
            alpha=0.38,
            label="Hidden bleed gap (known_V > true_V)",
            zorder=3,
        )

    vmin_plot = max(0.0, min(0.72, float(np.min(tv)) - 0.10))
    canary_days = [d for d, c in zip(traj.days, traj.canaries_planted) if c > 0]
    canary_y = [vmin_plot + 0.025 * (1.04 - vmin_plot) for _ in canary_days]
    if canary_days:
        ax2.scatter(
            canary_days,
            canary_y,
            marker="^",
            s=85,
            color="darkorange",
            edgecolors="black",
            linewidths=0.7,
            zorder=6,
            label="Canary deployed",
        )
    ax2.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2, label="Accusation day")
    ax2.set_ylim(vmin_plot, 1.05)
    ax2.set_ylabel("Company Value V", fontsize=9.5)
    ax2.set_title(
        "Panel 2: known_V vs true_V and Canary Deployments",
        fontsize=11,
        loc="left",
        fontweight="bold",
    )
    ax2.grid(True, linestyle=":", linewidth=0.7, color=(0.78, 0.78, 0.8))
    ax2.legend(
        loc="lower right",
        bbox_to_anchor=(1.0, 1.015),
        borderaxespad=0.0,
        fontsize=8.0,
        framealpha=0.92,
        ncol=3,
    )

    p_top = np.array(traj.top_posterior, dtype=float)
    ev_thr = np.array(traj.ev_threshold, dtype=float)
    ax3.plot(
        x_days,
        p_top,
        color="seagreen",
        linewidth=2.5,
        marker="o",
        markersize=6.2,
        label="Top-suspect posterior max P(s)",
        zorder=4,
    )
    ax3.plot(
        x_days,
        ev_thr,
        color="darkorange",
        linewidth=2.3,
        linestyle="--",
        marker="d",
        markersize=5.2,
        label="Rational EV threshold 1/(1+V)",
        zorder=5,
    )
    ax3.axvline(traj.actual_accuse_day, color="darkviolet", linestyle="--", linewidth=2.2, label="Accusation day")
    ax3.scatter(
        [traj.actual_accuse_day],
        [traj.accused_posterior_at_accuse],
        marker="*",
        s=230,
        color="darkviolet",
        edgecolors="black",
        linewidths=0.9,
        zorder=7,
        label="P(accused) at accusation",
    )
    ax3.set_ylim(-0.03, 1.06)
    ax3.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax3.set_ylabel("Probability", fontsize=9.5)
    ax3.set_xlabel("Day", fontsize=10)
    ax3.set_title(
        "Panel 3: Top-Suspect Posterior vs Rational EV Threshold 1/(1+V)",
        fontsize=11,
        loc="left",
        fontweight="bold",
    )
    ax3.grid(True, linestyle=":", linewidth=0.7, color=(0.78, 0.78, 0.8))
    ax3.legend(
        loc="lower right",
        bbox_to_anchor=(1.0, 1.015),
        borderaxespad=0.0,
        fontsize=8.0,
        framealpha=0.92,
        ncol=2,
    )

    xticks = list(range(1, horizon + 1))
    ax1.set_xlim(0.5, horizon + 0.5)
    for ax in (ax1, ax2, ax3):
        ax.set_xticks(xticks)
        ax.set_xticklabels([str(d) for d in xticks], fontsize=9)
        ax.tick_params(axis="x", labelbottom=True)

    fig.suptitle("Canary Multimodal Trajectory Forensics", fontsize=13, fontweight="bold", y=0.985)
    fig.subplots_adjust(left=0.075, right=0.94, top=0.935, bottom=0.055)

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


def analyze_chart_bytes(
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
            cleaned = re.sub(r"^```(?:json)?|```$", "", raw_txt).strip()
            parsed = json.loads(cleaned)
            diagnosis = {
                "accused_below_ev_threshold": bool(parsed["accused_below_ev_threshold"]),
                "estimated_accuse_day": int(parsed["estimated_accuse_day"]),
                "hidden_bleed_gap_present": bool(parsed["hidden_bleed_gap_present"]),
                "visual_diagnosis": sanitize_text(str(parsed["visual_diagnosis"]).strip()),
                "primary_failure_pattern": sanitize_text(str(parsed["primary_failure_pattern"]).strip()),
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


def score_diagnosis(traj: EpisodeTrajectory, diagnosis: dict[str, Any]) -> dict[str, Any]:
    est_day = int(diagnosis["estimated_accuse_day"])
    act_day = int(traj.actual_accuse_day)
    err = abs(est_day - act_day)
    return {
        "threshold_match": bool(diagnosis["accused_below_ev_threshold"]) == bool(traj.accused_below_ev_threshold),
        "day_abs_error": err,
        "day_within_1": err <= 1,
        "day_exact": err == 0,
        "bleed_gap_match": bool(diagnosis["hidden_bleed_gap_present"]) == bool(traj.hidden_bleed_gap_present),
    }


def summarize_forensics(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {
            "n_charts_analyzed": 0,
            "visual_threshold_accuracy": 0.0,
            "accuse_day_within_1_accuracy": 0.0,
            "accuse_day_exact_accuracy": 0.0,
            "hidden_bleed_gap_accuracy": 0.0,
            "usage": {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0},
        }
    thr_ok = sum(1 for r in records if r["scoring"]["threshold_match"])
    day1_ok = sum(1 for r in records if r["scoring"]["day_within_1"])
    day0_ok = sum(1 for r in records if r["scoring"]["day_exact"])
    gap_ok = sum(1 for r in records if r["scoring"]["bleed_gap_match"])
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
        "usage": usage_tot,
    }
