from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import random
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _get_paired_v13() -> Any:
    import paired_v13 as mod

    globals()["paired_v13"] = mod
    return mod


def __getattr__(name: str) -> Any:
    if name == "paired_v13":
        return _get_paired_v13()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

SEEDS_0_29: tuple[int, ...] = tuple(range(30))
BOOTSTRAP_RESAMPLES = 10000
COMMITTED_BOOT_SEED = 0
BASELINE_BOOT_SEED = 20261114
TARGET_DPI = 150
MAX_PNG_BYTES = 200 * 1024
FLOAT_TOL = 1e-9

HEADLINE_PNG_NAME = "headline_gap_paired_v14.png"
CALIBRATION_PNG_NAME = "posterior_calibration_v14.png"
DEFAULT_OUT_DIR = "results/eval_v14"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def rgb(r: int, g: int, b: int) -> tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


SURFACE = rgb(252, 252, 250)
PANEL_BG = rgb(255, 255, 254)
INK = rgb(18, 22, 28)
INK_MUTED = rgb(88, 92, 100)
INK_SOFT = rgb(132, 136, 144)
GRID_COLOR = rgb(228, 229, 225)
SPINE_COLOR = rgb(196, 198, 194)

BLUE_SOLVER = rgb(36, 110, 201)
ORANGE_CARBON = rgb(219, 88, 24)
CRIMSON_FLASH = rgb(190, 32, 88)
TEAL_INPROC = rgb(32, 142, 125)
SLATE_BASE = rgb(104, 110, 120)
ZERO_GRAY = rgb(120, 124, 132)

BAND_AMBER = rgb(255, 244, 226)
BAND_MINT = rgb(235, 247, 242)
BAND_ROSE = rgb(253, 236, 241)
GAMBLE_FILL = rgb(252, 224, 226)
WINDFALL_FILL = rgb(246, 205, 219)

FOREST_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "solver",
        "display": "Reference Solver",
        "sublabel": "exact Bayesian benchmark",
        "source": "committed",
        "subdir": "v1.4/reference",
        "agent": "solver",
        "tiers": ("hard", "medium"),
        "color": BLUE_SOLVER,
    },
    {
        "key": "opencode_carbon",
        "display": "OpenCode + gemini-4-carbon",
        "sublabel": "MCP harness (judges' shape)",
        "source": "committed",
        "subdir": "v1.4/opencode-gemini-4-carbon",
        "agent": "opencode:google/gemini-4-carbon",
        "tiers": ("hard", "medium"),
        "color": ORANGE_CARBON,
    },
    {
        "key": "opencode_flash",
        "display": "OpenCode + gemini-3.5-flash",
        "sublabel": "MCP harness (second family)",
        "source": "committed",
        "subdir": "v1.4/opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "tiers": ("hard",),
        "color": CRIMSON_FLASH,
    },
    {
        "key": "inproc_carbon",
        "display": "In-process gemini-4-carbon",
        "sublabel": "direct loop, full history",
        "source": "committed",
        "subdir": "v1.4/inproc-gemini-4-carbon",
        "agent": "gemini:gemini-4-carbon",
        "tiers": ("hard", "medium"),
        "color": TEAL_INPROC,
    },
    {
        "key": "grok_tactics",
        "display": "grok_tactics",
        "sublabel": "scripted canary + probe",
        "source": "replayed",
        "agent": "grok_tactics",
        "tiers": ("hard", "medium"),
        "color": SLATE_BASE,
    },
    {
        "key": "heuristic",
        "display": "heuristic",
        "sublabel": "naive canary bisection",
        "source": "replayed",
        "agent": "heuristic",
        "tiers": ("hard", "medium"),
        "color": SLATE_BASE,
    },
    {
        "key": "do_nothing",
        "display": "do_nothing",
        "sublabel": "abstain baseline (never accuses)",
        "source": "replayed",
        "agent": "do_nothing",
        "tiers": ("hard", "medium"),
        "color": ZERO_GRAY,
    },
    {
        "key": "stop_early",
        "display": "stop_early",
        "sublabel": "day-1 quit without accusing",
        "source": "replayed",
        "agent": "stop_early",
        "tiers": ("hard", "medium"),
        "color": ZERO_GRAY,
    },
)

CALIBRATION_KEYS: tuple[str, ...] = (
    "solver",
    "inproc_carbon",
    "opencode_carbon",
    "opencode_flash",
)

_BOOT_CACHE: dict[tuple[int, int, int], Any] = {}


def _boot_index_matrix(n: int, b_resamples: int, rng_seed: int) -> Any:
    import numpy as np

    cache_key = (n, b_resamples, rng_seed)
    if cache_key not in _BOOT_CACHE:
        rng = random.Random(rng_seed)
        _BOOT_CACHE[cache_key] = np.array(
            [[rng.randrange(n) for _ in range(n)] for _ in range(b_resamples)],
            dtype=np.intp,
        )
    return _BOOT_CACHE[cache_key]


def fast_boot_ratio(
    num_vals: list[float],
    den_vals: list[float],
    b_resamples: int = BOOTSTRAP_RESAMPLES,
    rng_seed: int = COMMITTED_BOOT_SEED,
) -> tuple[float, float]:
    import numpy as np

    n = len(num_vals)
    idx = _boot_index_matrix(n, b_resamples, rng_seed)
    num_arr = np.asarray(num_vals, dtype=np.float64)[idx].sum(axis=1) / n
    den_arr = np.asarray(den_vals, dtype=np.float64)[idx].sum(axis=1) / n
    valid = den_arr > 0.0
    ratios = np.sort(num_arr[valid] / den_arr[valid])
    return float(ratios[int(0.025 * len(ratios))]), float(ratios[int(0.975 * len(ratios)) - 1])


def fmt_pct_ci(ratio: float, lo: float, hi: float) -> str:
    return f"{ratio:.0%} [{lo:.0%}, {hi:.0%}]"


def _episode_v(ep: dict[str, Any]) -> float:
    meta = ep.get("meta") or {}
    val = meta.get("V", meta.get("V_final"))
    if val is None:
        raise ValueError(f"missing V/V_final in episode seed={ep.get('seed')} agent={ep.get('agent')}")
    return float(val)


def _load_committed_by_tier_seed(
    committed_root: Path,
    subdir: str,
    agent_name: str,
    seeds: set[int],
) -> dict[tuple[str, int], dict[str, Any]]:
    from canary.analysis.gap import load_runs

    run_dir = committed_root / subdir
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for ep in load_runs(run_dir):
        if ep.get("agent") != agent_name:
            continue
        if (ep.get("meta") or {}).get("valid") is False:
            continue
        seed_i = int(ep["seed"])
        if seed_i not in seeds:
            continue
        out[(str(ep["tier"]), seed_i)] = ep
    return out


def _replay_baseline_by_tier_seed(
    agent_name: str,
    tiers: tuple[str, ...],
    seeds: tuple[int, ...],
) -> dict[tuple[str, int], dict[str, Any]]:
    from canary import rules
    from canary.eval import make_env, make_policy_factory, run_episode

    out: dict[tuple[str, int], dict[str, Any]] = {}
    with rules.tiers_version("v1.4"):
        factory = make_policy_factory(agent_name)
        for tier in tiers:
            for seed_i in seeds:
                res = run_episode(make_env(tier, seed_i), factory(seed_i))
                out[(tier, seed_i)] = asdict(res)
    return out


def compute_chart_data(
    root: Path = ROOT,
    seeds: tuple[int, ...] = SEEDS_0_29,
    b_resamples: int = BOOTSTRAP_RESAMPLES,
    committed_boot_seed: int = COMMITTED_BOOT_SEED,
    baseline_boot_seed: int = BASELINE_BOOT_SEED,
) -> dict[str, Any]:
    from canary.analysis.gap import mean_ci

    paired_v13 = _get_paired_v13()
    committed_root = root / "data" / "runs" / "committed"
    seed_set = set(seeds)
    seeds_sorted = tuple(sorted(seeds))

    episodes_by_key: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    paired_v13._P_CACHE.clear()
    try:
        for spec in FOREST_SPECS:
            key = spec["key"]
            if spec["source"] == "committed":
                episodes_by_key[key] = _load_committed_by_tier_seed(
                    committed_root,
                    spec["subdir"],
                    spec["agent"],
                    seed_set,
                )
            else:
                episodes_by_key[key] = _replay_baseline_by_tier_seed(
                    spec["agent"],
                    spec["tiers"],
                    seeds_sorted,
                )

        solver_eps = episodes_by_key["solver"]
        solver_vectors: dict[str, dict[str, list[float]]] = {}
        for tier in ("hard", "medium"):
            s_list = [solver_eps[(tier, s)] for s in seeds_sorted]
            s_raw = [float(e["score"]) for e in s_list]
            s_la = [float(paired_v13.post_expected(e)) for e in s_list]
            solver_vectors[tier] = {"raw": s_raw, "la": s_la}

        forest_rows: dict[str, list[dict[str, Any]]] = {"hard": [], "medium": []}
        for tier in ("hard", "medium"):
            s_raw = solver_vectors[tier]["raw"]
            s_la = solver_vectors[tier]["la"]
            s_raw_mean = sum(s_raw) / len(s_raw)
            s_la_mean = sum(s_la) / len(s_la)
            for spec in FOREST_SPECS:
                key = spec["key"]
                if tier not in spec["tiers"]:
                    forest_rows[tier].append(
                        {
                            "key": key,
                            "display": spec["display"],
                            "sublabel": spec["sublabel"],
                            "source": spec["source"],
                            "available": False,
                            "tier": tier,
                        }
                    )
                    continue

                ep_list = [episodes_by_key[key][(tier, s)] for s in seeds_sorted]
                f_raw = [float(e["score"]) for e in ep_list]
                f_la = [float(paired_v13.post_expected(e)) for e in ep_list]
                raw_mean, raw_ci = mean_ci(f_raw)
                la_mean, la_ci = mean_ci(f_la)
                raw_ratio = (sum(f_raw) / len(f_raw)) / s_raw_mean
                la_ratio = (sum(f_la) / len(f_la)) / s_la_mean

                if key == "solver":
                    raw_lo, raw_hi = 1.0, 1.0
                    la_lo, la_hi = 1.0, 1.0
                    boot_seed_used = committed_boot_seed
                else:
                    boot_seed_used = committed_boot_seed if spec["source"] == "committed" else baseline_boot_seed
                    raw_lo, raw_hi = fast_boot_ratio(f_raw, s_raw, b_resamples=b_resamples, rng_seed=boot_seed_used)
                    la_lo, la_hi = fast_boot_ratio(f_la, s_la, b_resamples=b_resamples, rng_seed=boot_seed_used)

                forest_rows[tier].append(
                    {
                        "key": key,
                        "display": spec["display"],
                        "sublabel": spec["sublabel"],
                        "source": spec["source"],
                        "available": True,
                        "tier": tier,
                        "n": len(ep_list),
                        "boot_seed": boot_seed_used,
                        "raw_mean": round(raw_mean, 12),
                        "raw_ci": round(raw_ci, 12),
                        "la_mean": round(la_mean, 12),
                        "la_ci": round(la_ci, 12),
                        "raw_ratio": round(raw_ratio, 12),
                        "raw_lo": round(raw_lo, 12),
                        "raw_hi": round(raw_hi, 12),
                        "la_ratio": round(la_ratio, 12),
                        "la_lo": round(la_lo, 12),
                        "la_hi": round(la_hi, 12),
                        "raw_label": "100% (ref)" if key == "solver" else fmt_pct_ci(raw_ratio, raw_lo, raw_hi),
                        "la_label": "100% (ref)" if key == "solver" else fmt_pct_ci(la_ratio, la_lo, la_hi),
                    }
                )

        calibration_cohorts: dict[str, dict[str, Any]] = {}
        spec_by_key = {s["key"]: s for s in FOREST_SPECS}
        for key in CALIBRATION_KEYS:
            spec = spec_by_key[key]
            ep_list = [episodes_by_key[key][("hard", s)] for s in seeds_sorted]
            accusations: list[dict[str, Any]] = []
            abstentions: list[dict[str, Any]] = []
            raw_seq: list[float] = []
            ev_seq: list[float] = []
            cum_raw: list[float] = []
            cum_ev: list[float] = []
            running_raw = 0.0
            running_ev = 0.0

            for ep in ep_list:
                seed_i = int(ep["seed"])
                v_val = _episode_v(ep)
                sc_val = float(ep["score"])
                ev_val = float(paired_v13.post_expected(ep))
                raw_seq.append(sc_val)
                ev_seq.append(ev_val)
                running_raw += sc_val
                running_ev += ev_val
                cum_raw.append(round(running_raw, 12))
                cum_ev.append(round(running_ev, 12))

                if ep.get("accused"):
                    p_val = float(paired_v13.p_acc(ep))
                    p_be = 1.0 / (1.0 + v_val)
                    accusations.append(
                        {
                            "seed": seed_i,
                            "accused": str(ep["accused"]),
                            "correct": bool(ep["correct"]),
                            "v": round(v_val, 12),
                            "p": round(p_val, 12),
                            "p_breakeven": round(p_be, 12),
                            "ev": round(ev_val, 12),
                            "score": round(sc_val, 12),
                            "sub_breakeven": bool(p_val < p_be),
                        }
                    )
                else:
                    abstentions.append({"seed": seed_i, "v": round(v_val, 12)})

            raw_mean, raw_ci = mean_ci(raw_seq)
            ev_mean, ev_ci = mean_ci(ev_seq)
            sub_be = [a for a in accusations if a["sub_breakeven"]]
            ci_shrink = (1.0 - (ev_ci / raw_ci)) if raw_ci > 0.0 else 0.0
            calibration_cohorts[key] = {
                "key": key,
                "display": spec["display"],
                "n": len(ep_list),
                "n_accused": len(accusations),
                "n_abstained": len(abstentions),
                "n_sub_breakeven": len(sub_be),
                "n_sub_breakeven_lucky": sum(1 for a in sub_be if a["correct"]),
                "n_sub_breakeven_wrong": sum(1 for a in sub_be if not a["correct"]),
                "sub_breakeven_seeds": [a["seed"] for a in sub_be],
                "abstention_seeds": [a["seed"] for a in abstentions],
                "raw_mean": round(raw_mean, 12),
                "raw_ci": round(raw_ci, 12),
                "ev_mean": round(ev_mean, 12),
                "ev_ci": round(ev_ci, 12),
                "raw_sum": round(sum(raw_seq), 12),
                "ev_sum": round(sum(ev_seq), 12),
                "windfall_mean": round(raw_mean - ev_mean, 12),
                "windfall_sum": round(sum(raw_seq) - sum(ev_seq), 12),
                "ci_shrink_fraction": round(ci_shrink, 12),
                "accusations": accusations,
                "abstentions": abstentions,
                "cum_raw": cum_raw,
                "cum_ev": cum_ev,
            }

        return {
            "tiers_version": "v1.4",
            "seeds": list(seeds_sorted),
            "bootstrap_resamples": b_resamples,
            "committed_boot_seed": committed_boot_seed,
            "baseline_boot_seed": baseline_boot_seed,
            "solver_means": {
                "hard": round(sum(solver_vectors["hard"]["raw"]) / len(seeds_sorted), 12),
                "medium": round(sum(solver_vectors["medium"]["raw"]) / len(seeds_sorted), 12),
            },
            "forest": forest_rows,
            "calibration": calibration_cohorts,
        }
    finally:
        paired_v13._P_CACHE.clear()


def _configure_matplotlib_defaults() -> None:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["font.family"] = "DejaVu Sans"


def _save_figure_png(fig: Any, out_path: Path, dpi: int) -> None:
    from PIL import Image

    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=SURFACE)
    buf.seek(0)
    with Image.open(buf) as raw_img:
        rgb_img = raw_img.convert("RGB")
    quant_img = rgb_img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quant_img.save(out_path, format="PNG", optimize=True, compress_level=9, dpi=(dpi, dpi))


def render_headline_gap_chart(data: dict[str, Any], out_path: Path, dpi: int = TARGET_DPI) -> None:
    _configure_matplotlib_defaults()
    from matplotlib.lines import Line2D
    import matplotlib.pyplot as plt

    spec_color = {s["key"]: s["color"] for s in FOREST_SPECS}
    n_rows = len(FOREST_SPECS)
    y_positions = [float(n_rows - 1 - i) for i in range(n_rows)]

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(13.2, 6.3),
        dpi=dpi,
        gridspec_kw={"width_ratios": [1.05, 1.0], "wspace": 0.08},
    )
    fig.patch.set_facecolor(SURFACE)

    tier_configs = (
        ("hard", axes[0], -45.0, 232.0, (-40, 0, 40, 80, 100, 140), True),
        ("medium", axes[1], -118.0, 235.0, (-100, -50, 0, 50, 100, 140), False),
    )

    for tier, ax, x_min, x_max, x_ticks, show_ylabels in tier_configs:
        ax.set_facecolor(PANEL_BG)
        rows = data["forest"][tier]
        solver_mean = data["solver_means"][tier]

        for idx, row in enumerate(rows):
            y0 = y_positions[idx]
            rkey = row["key"]
            if rkey == "opencode_carbon":
                band_col = BAND_AMBER if tier == "hard" else BAND_MINT
                ax.axhspan(y0 - 0.44, y0 + 0.44, color=band_col, alpha=0.85, zorder=0)
            elif rkey == "opencode_flash" and tier == "hard":
                ax.axhspan(y0 - 0.44, y0 + 0.44, color=BAND_ROSE, alpha=0.75, zorder=0)

        sep_y = (y_positions[3] + y_positions[4]) / 2.0
        ax.axhline(sep_y, color=SPINE_COLOR, linewidth=0.9, linestyle=(0, (4, 3)), zorder=1)
        ax.text(
            x_min + 3.0,
            sep_y - 0.14,
            "Deterministic replayed baselines (n=30, seeds 0-29)",
            fontsize=7.3,
            color=INK_MUTED,
            va="top",
            ha="left",
            style="italic",
        )

        for xt in x_ticks:
            if xt not in (0, 100):
                ax.axvline(xt, color=GRID_COLOR, linewidth=0.65, zorder=0)

        ax.axvline(0.0, color=INK_MUTED, linewidth=1.15, linestyle="-", zorder=2)
        ax.axvline(100.0, color=BLUE_SOLVER, linewidth=1.45, linestyle=(0, (5, 3)), zorder=2)

        text_col_x = x_max - 4.0
        col_sep_x = 148.0 if tier == "hard" else 138.0
        ax.axvline(col_sep_x, color=GRID_COLOR, linewidth=0.8, zorder=1)
        ax.axvspan(col_sep_x, x_max, color=SURFACE, alpha=0.92, zorder=1)

        ax.text(
            0.0,
            n_rows - 0.36,
            "0% abstain",
            fontsize=7.2,
            color=INK_MUTED,
            ha="center",
            va="bottom",
        )
        ax.text(
            100.0,
            n_rows - 0.36,
            "100% parity",
            fontsize=7.5,
            fontweight="bold",
            color=BLUE_SOLVER,
            ha="center",
            va="bottom",
        )
        ax.text(
            text_col_x,
            n_rows - 0.36,
            "Raw / Luck-Adj. [95% CI]",
            fontsize=7.4,
            fontweight="bold",
            color=INK_MUTED,
            ha="right",
            va="bottom",
        )

        for idx, row in enumerate(rows):
            y0 = y_positions[idx]
            rkey = row["key"]
            col = spec_color[rkey]

            if not row["available"]:
                ax.text(
                    (x_min + col_sep_x) * 0.5,
                    y0,
                    "Evaluated on hard tier only (n=30)",
                    fontsize=8.0,
                    color=INK_SOFT,
                    ha="center",
                    va="center",
                    style="italic",
                    zorder=3,
                )
                ax.text(
                    text_col_x,
                    y0,
                    "hard only",
                    fontsize=7.8,
                    color=INK_SOFT,
                    ha="right",
                    va="center",
                    zorder=3,
                )
                continue

            if rkey == "solver":
                ax.scatter(
                    [100.0],
                    [y0],
                    marker="D",
                    s=54,
                    color=BLUE_SOLVER,
                    edgecolors="white",
                    linewidths=0.9,
                    zorder=5,
                )
                ax.text(
                    text_col_x,
                    y0,
                    f"100% ({solver_mean:+.3f} V)",
                    fontsize=8.0,
                    fontweight="bold",
                    color=BLUE_SOLVER,
                    ha="right",
                    va="center",
                    zorder=4,
                )
                continue

            raw_p = row["raw_ratio"] * 100.0
            raw_lo_p = row["raw_lo"] * 100.0
            raw_hi_p = row["raw_hi"] * 100.0

            la_p = row["la_ratio"] * 100.0
            la_lo_p = row["la_lo"] * 100.0
            la_hi_p = row["la_hi"] * 100.0

            y_raw = y0 + 0.165
            y_la = y0 - 0.165

            ax.plot([raw_lo_p, raw_hi_p], [y_raw, y_raw], color=col, linewidth=1.5, alpha=0.68, zorder=3)
            ax.plot([raw_lo_p, raw_lo_p], [y_raw - 0.06, y_raw + 0.06], color=col, linewidth=1.3, alpha=0.68, zorder=3)
            ax.plot([raw_hi_p, raw_hi_p], [y_raw - 0.06, y_raw + 0.06], color=col, linewidth=1.3, alpha=0.68, zorder=3)
            ax.scatter(
                [raw_p],
                [y_raw],
                marker="o",
                s=34,
                facecolors="white",
                edgecolors=col,
                linewidths=1.6,
                zorder=4,
            )

            ax.plot([la_lo_p, la_hi_p], [y_la, y_la], color=col, linewidth=2.3, zorder=4)
            ax.plot([la_lo_p, la_lo_p], [y_la - 0.07, y_la + 0.07], color=col, linewidth=1.8, zorder=4)
            ax.plot([la_hi_p, la_hi_p], [y_la - 0.07, y_la + 0.07], color=col, linewidth=1.8, zorder=4)
            ax.scatter(
                [la_p],
                [y_la],
                marker="s",
                s=36,
                facecolors=col,
                edgecolors="white",
                linewidths=0.7,
                zorder=5,
            )

            ax.text(
                text_col_x,
                y_raw,
                f"Raw {row['raw_label']}",
                fontsize=7.5,
                color=INK_MUTED,
                ha="right",
                va="center",
                zorder=4,
            )
            ax.text(
                text_col_x,
                y_la,
                f"LA  {row['la_label']}",
                fontsize=7.7,
                fontweight="bold" if rkey in ("opencode_carbon", "opencode_flash", "inproc_carbon") else "normal",
                color=INK if rkey not in ("do_nothing", "stop_early") else INK_MUTED,
                ha="right",
                va="center",
                zorder=4,
            )

            if tier == "hard" and rkey == "opencode_carbon":
                ax.text(
                    -42.0,
                    y0 + 0.31,
                    "Headline gap: both CIs < 100%",
                    fontsize=7.2,
                    fontweight="bold",
                    color=ORANGE_CARBON,
                    ha="left",
                    va="center",
                    zorder=5,
                )
            elif tier == "hard" and rkey == "opencode_flash":
                drop_pp = round((row["la_ratio"] - row["raw_ratio"]) * 100.0)
                ax.annotate(
                    "",
                    xy=(la_p, y_la + 0.03),
                    xytext=(raw_p, y_raw - 0.03),
                    arrowprops={"arrowstyle": "->", "color": CRIMSON_FLASH, "lw": 1.1, "ls": ":"},
                    zorder=4,
                )
                ax.text(
                    -42.0,
                    y0 + 0.31,
                    f"Lottery collapse ({drop_pp:+d} pp EV)",
                    fontsize=7.2,
                    fontweight="bold",
                    color=CRIMSON_FLASH,
                    ha="left",
                    va="center",
                    zorder=5,
                )
            elif tier == "medium" and rkey == "opencode_carbon":
                ax.text(
                    -114.0,
                    y0 + 0.31,
                    "Medium parity (111% raw / 101% LA)",
                    fontsize=7.2,
                    fontweight="bold",
                    color=TEAL_INPROC,
                    ha="left",
                    va="center",
                    zorder=5,
                )

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(-0.58, n_rows - 0.12)
        ax.set_xticks(list(x_ticks))
        ax.set_xticklabels([f"{t}%" for t in x_ticks], fontsize=8.0, color=INK_MUTED)
        ax.set_xlabel("Score as % of Reference Solver on identical seeds", fontsize=8.5, color=INK_MUTED)

        tier_title = "Hard Tier (Headline)" if tier == "hard" else "Medium Tier (Parity Control)"
        ax.set_title(
            f"{tier_title} | n=30 seeds 0-29 | Solver = {solver_mean:+.3f} V",
            fontsize=9.1,
            fontweight="bold",
            color=INK,
            loc="left",
            pad=10,
        )

        if show_ylabels:
            ylabels = [f"{s['display']}\n({s['sublabel']})" for s in FOREST_SPECS]
            ax.set_yticks(y_positions)
            ax.set_yticklabels(ylabels, fontsize=8.1, color=INK)
            for tick_idx, tick_lbl in enumerate(ax.get_yticklabels()):
                if FOREST_SPECS[tick_idx]["key"] == "opencode_carbon":
                    tick_lbl.set_fontweight("bold")
        else:
            ax.set_yticks(y_positions)
            ax.set_yticklabels([])
            ax.tick_params(axis="y", length=0)

        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(SPINE_COLOR)

    legend_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color=INK_MUTED,
            markerfacecolor="white",
            markeredgecolor=INK,
            markeredgewidth=1.6,
            linewidth=1.5,
            markersize=6,
            label="Raw % of Solver [95% paired bootstrap CI]",
        ),
        Line2D(
            [0],
            [0],
            marker="s",
            color=INK,
            markerfacecolor=INK,
            markeredgecolor="white",
            linewidth=2.3,
            markersize=6,
            label="Luck-Adjusted % of Solver (EV = P*V - (1-P)) [95% paired bootstrap CI]",
        ),
        Line2D(
            [0],
            [0],
            color=BLUE_SOLVER,
            linewidth=1.45,
            linestyle=(0, (5, 3)),
            marker="D",
            markersize=6,
            label="Reference Solver parity (100%)",
        ),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(0.18, 0.925),
        ncol=3,
        frameon=False,
        fontsize=8.1,
    )

    fig.suptitle(
        "Canary v1.4 Paired Headline Gap: Frontier Agents vs Reference Solver (Seeds 0-29)",
        fontsize=12.0,
        fontweight="bold",
        color=INK,
        x=0.02,
        y=0.975,
        ha="left",
    )
    fig.text(
        0.02,
        0.012,
        "Source: data/runs/committed/v1.4/ + deterministic replayed n=30 baselines (10,000 paired bootstrap resamples; do_nothing = stop_early = 0%).",
        fontsize=7.6,
        color=INK_MUTED,
        ha="left",
        va="bottom",
    )

    fig.subplots_adjust(left=0.185, right=0.988, top=0.84, bottom=0.105, wspace=0.06)
    _save_figure_png(fig, out_path, dpi=dpi)
    plt.close(fig)


def render_posterior_calibration_chart(data: dict[str, Any], out_path: Path, dpi: int = TARGET_DPI) -> None:
    _configure_matplotlib_defaults()
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    import matplotlib.pyplot as plt
    import numpy as np

    cal = data["calibration"]

    fig, (ax_left, ax_right) = plt.subplots(
        1,
        2,
        figsize=(13.2, 6.2),
        dpi=dpi,
        gridspec_kw={"width_ratios": [1.06, 1.0], "wspace": 0.18},
    )
    fig.patch.set_facecolor(SURFACE)

    ax_left.set_facecolor(PANEL_BG)
    v_grid = np.linspace(0.0, 1.0, 300)
    p_be_grid = 1.0 / (1.0 + v_grid)
    ax_left.fill_between(v_grid, 0.0, p_be_grid, color=GAMBLE_FILL, alpha=0.62, zorder=0)
    ax_left.plot(v_grid, p_be_grid, color=CRIMSON_FLASH, linewidth=1.9, linestyle=(0, (5, 3)), zorder=2)
    ax_left.axhline(0.85, color=BLUE_SOLVER, linewidth=1.0, linestyle=":", alpha=0.8, zorder=1)
    ax_left.text(
        0.02,
        0.862,
        "Solver commit bar (P >= 0.85)",
        fontsize=7.4,
        color=BLUE_SOLVER,
        ha="left",
        va="bottom",
    )
    ax_left.text(
        0.98,
        0.06,
        "Negative-EV Gamble Zone: P < 1 / (1 + V)\nEV = P*V - (1-P) < 0  (abstaining = 0 beats accusing)",
        fontsize=7.8,
        fontweight="bold",
        color=CRIMSON_FLASH,
        ha="right",
        va="bottom",
        bbox={"boxstyle": "round,pad=0.28", "facecolor": SURFACE, "edgecolor": CRIMSON_FLASH, "alpha": 0.9, "lw": 0.8},
        zorder=4,
    )

    scatter_styles = (
        ("solver", BLUE_SOLVER, "s", 38, "Reference Solver"),
        ("inproc_carbon", TEAL_INPROC, "^", 42, "In-process gemini-4-carbon"),
        ("opencode_carbon", ORANGE_CARBON, "o", 46, "OpenCode + gemini-4-carbon"),
        ("opencode_flash", CRIMSON_FLASH, "D", 42, "OpenCode + gemini-3.5-flash"),
    )

    for key, col, mk, sz, base_lbl in scatter_styles:
        cohort = cal[key]
        accs = cohort["accusations"]
        corr_pts = [a for a in accs if a["correct"]]
        wrong_pts = [a for a in accs if not a["correct"]]
        lbl = f"{base_lbl} ({cohort['n_accused']} acc, {cohort['n_sub_breakeven']} EV<0)"
        if corr_pts:
            ax_left.scatter(
                [a["v"] for a in corr_pts],
                [a["p"] for a in corr_pts],
                marker=mk,
                s=sz,
                facecolors=col,
                edgecolors="white",
                linewidths=0.65,
                alpha=0.86,
                label=lbl,
                zorder=4 if key.startswith("opencode") else 3,
            )
        if wrong_pts:
            ax_left.scatter(
                [a["v"] for a in wrong_pts],
                [a["p"] for a in wrong_pts],
                marker="X",
                s=sz + 24,
                facecolors=col,
                edgecolors=INK,
                linewidths=0.9,
                alpha=0.95,
                zorder=5,
            )

    carbon_accs = {a["seed"]: a for a in cal["opencode_carbon"]["accusations"] if a["sub_breakeven"]}
    carbon_offsets = {
        5: (6.0, 22.0, "left"),
        23: (10.0, -24.0, "left"),
        18: (18.0, -16.0, "left"),
    }
    for seed_i, (dx, dy, ha_align) in carbon_offsets.items():
        pt = carbon_accs.get(seed_i)
        if pt is None:
            continue
        outcome_tag = ", wrong" if not pt["correct"] else ""
        ax_left.annotate(
            f"Carbon s{seed_i}: P={pt['p']:.2f}, V={pt['v']:.2f}{outcome_tag}",
            xy=(pt["v"], pt["p"]),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=7.3,
            fontweight="bold",
            color=ORANGE_CARBON,
            ha=ha_align,
            va="center",
            bbox={"boxstyle": "round,pad=0.2", "facecolor": SURFACE, "edgecolor": ORANGE_CARBON, "lw": 0.75, "alpha": 0.94},
            arrowprops={"arrowstyle": "->", "color": ORANGE_CARBON, "lw": 1.0},
            zorder=6,
        )

    flash_c = cal["opencode_flash"]
    flash_sub = [a for a in flash_c["accusations"] if a["sub_breakeven"]]
    if flash_sub:
        p_max_sub = max(a["p"] for a in flash_sub)
        anchor_pt = next((a for a in flash_sub if a["seed"] == 18), flash_sub[0])
        ax_left.annotate(
            f"Flash: {flash_c['n_sub_breakeven']}/{flash_c['n_accused']} sub-breakeven gambles\n"
            f"({flash_c['n_sub_breakeven_lucky']} lucky hits + {flash_c['n_sub_breakeven_wrong']} wrong, P <= {p_max_sub:.2f})",
            xy=(anchor_pt["v"], anchor_pt["p"]),
            xytext=(0.04, 0.25),
            textcoords="data",
            fontsize=7.5,
            fontweight="bold",
            color=CRIMSON_FLASH,
            ha="left",
            va="center",
            bbox={"boxstyle": "round,pad=0.24", "facecolor": BAND_ROSE, "edgecolor": CRIMSON_FLASH, "lw": 0.85, "alpha": 0.95},
            arrowprops={"arrowstyle": "->", "color": CRIMSON_FLASH, "lw": 1.1},
            zorder=6,
        )

    ax_left.set_xlim(-0.02, 1.02)
    ax_left.set_ylim(-0.03, 1.06)
    ax_left.set_xlabel("Company Value V at Accusation", fontsize=8.6, color=INK_MUTED)
    ax_left.set_ylabel("Exact Solver Posterior P(accused | agent evidence)", fontsize=8.6, color=INK_MUTED)
    ax_left.set_title(
        "A. Accusation Calibration vs Break-Even P = 1 / (1 + V)",
        fontsize=9.6,
        fontweight="bold",
        color=INK,
        loc="left",
        pad=9,
    )
    ax_left.grid(True, color=GRID_COLOR, linewidth=0.65, zorder=0)
    ax_left.tick_params(colors=INK_MUTED, labelsize=8.0)

    extra_wrong = Line2D(
        [0],
        [0],
        marker="X",
        linestyle="None",
        markerfacecolor=INK_MUTED,
        markeredgecolor=INK,
        markersize=7,
        label="Wrong accusation (score = -1.0)",
    )
    handles_l, labels_l = ax_left.get_legend_handles_labels()
    handles_l.append(extra_wrong)
    labels_l.append("Wrong accusation (score = -1.0)")
    ax_left.legend(
        handles_l,
        labels_l,
        loc="lower right",
        bbox_to_anchor=(0.99, 0.175),
        fontsize=6.9,
        frameon=True,
        facecolor=SURFACE,
        edgecolor=GRID_COLOR,
        framealpha=0.94,
    )

    for side in ("top", "right"):
        ax_left.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax_left.spines[side].set_color(SPINE_COLOR)

    ax_right.set_facecolor(PANEL_BG)
    x_seeds = np.arange(len(data["seeds"]), dtype=np.float64)

    flash_cum_raw = np.asarray(cal["opencode_flash"]["cum_raw"], dtype=np.float64)
    flash_cum_ev = np.asarray(cal["opencode_flash"]["cum_ev"], dtype=np.float64)
    ax_right.fill_between(
        x_seeds,
        flash_cum_ev,
        flash_cum_raw,
        color=WINDFALL_FILL,
        alpha=0.52,
        zorder=1,
    )

    traj_styles = (
        ("solver", BLUE_SOLVER, "Solver"),
        ("inproc_carbon", TEAL_INPROC, "In-proc Carbon"),
        ("opencode_carbon", ORANGE_CARBON, "OC Carbon"),
        ("opencode_flash", CRIMSON_FLASH, "OC Flash"),
    )
    for key, col, short_lbl in traj_styles:
        c_raw = np.asarray(cal[key]["cum_raw"], dtype=np.float64)
        c_ev = np.asarray(cal[key]["cum_ev"], dtype=np.float64)
        ax_right.plot(x_seeds, c_raw, color=col, linewidth=1.35, linestyle="--", alpha=0.72, zorder=2)
        ax_right.plot(x_seeds, c_ev, color=col, linewidth=2.25, linestyle="-", zorder=3, label=short_lbl)

    div_x = 30.2
    ax_right.axvline(div_x, color=SPINE_COLOR, linewidth=1.0, linestyle=(0, (4, 3)), zorder=2)
    ax_right.axvspan(div_x, 40.5, color=SURFACE, alpha=0.88, zorder=0)
    ax_right.axhline(0.0, color=INK_MUTED, linewidth=0.9, zorder=1)

    n_ep = float(len(data["seeds"]))
    endpoint_slots = (
        ("solver", 32.0, BLUE_SOLVER, "Solver"),
        ("inproc_carbon", 34.3, TEAL_INPROC, "In-proc"),
        ("opencode_carbon", 36.6, ORANGE_CARBON, "OC Carbon"),
        ("opencode_flash", 38.9, CRIMSON_FLASH, "OC Flash"),
    )
    ax_right.text(
        35.45,
        20.2,
        "n=30 Mean +/- 95% CI\n(Rao-Blackwell EV vs Raw)",
        fontsize=7.2,
        fontweight="bold",
        color=INK_MUTED,
        ha="center",
        va="top",
        zorder=4,
    )

    for key, x0, col, short_tag in endpoint_slots:
        cohort = cal[key]
        raw_y = cohort["raw_mean"] * n_ep
        raw_err = cohort["raw_ci"] * n_ep
        ev_y = cohort["ev_mean"] * n_ep
        ev_err = cohort["ev_ci"] * n_ep

        ax_right.errorbar(
            [x0 - 0.36],
            [raw_y],
            yerr=[raw_err],
            fmt="o",
            color=col,
            mfc="white",
            mec=col,
            mew=1.5,
            markersize=5.2,
            elinewidth=1.3,
            capsize=2.2,
            alpha=0.75,
            zorder=4,
        )
        ax_right.errorbar(
            [x0 + 0.36],
            [ev_y],
            yerr=[ev_err],
            fmt="s",
            color=col,
            mfc=col,
            mec="white",
            mew=0.6,
            markersize=5.4,
            elinewidth=2.1,
            capsize=2.5,
            zorder=5,
        )
        ax_right.text(
            x0,
            -3.5,
            short_tag,
            fontsize=6.9,
            color=col,
            fontweight="bold",
            ha="center",
            va="top",
            rotation=22,
        )

    flash_windfall_mean = cal["opencode_flash"]["windfall_mean"]
    flash_windfall_sum = cal["opencode_flash"]["windfall_sum"]
    ax_right.annotate(
        f"Flash lottery windfall:\n{flash_windfall_mean:+.3f} V/ep ({flash_windfall_sum:+.2f} V total)\n"
        f"Raw {cal['opencode_flash']['raw_mean']:+.3f} vs EV {cal['opencode_flash']['ev_mean']:+.3f}",
        xy=(27.0, (flash_cum_raw[27] + flash_cum_ev[27]) * 0.5),
        xytext=(9.0, 2.2),
        fontsize=7.3,
        fontweight="bold",
        color=CRIMSON_FLASH,
        ha="left",
        va="center",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": BAND_ROSE, "edgecolor": CRIMSON_FLASH, "lw": 0.85, "alpha": 0.95},
        arrowprops={"arrowstyle": "->", "color": CRIMSON_FLASH, "lw": 1.1},
        zorder=6,
    )

    carbon_shrink_pct = round(cal["opencode_carbon"]["ci_shrink_fraction"] * 100.0)
    solver_shrink_pct = round(cal["solver"]["ci_shrink_fraction"] * 100.0)
    ax_right.text(
        0.8,
        15.6,
        f"Rao-Blackwell 95% CI reduction:\n"
        f"OC Carbon: +/-{cal['opencode_carbon']['raw_ci']:.3f} -> +/-{cal['opencode_carbon']['ev_ci']:.3f} (-{carbon_shrink_pct}%)\n"
        f"Solver: +/-{cal['solver']['raw_ci']:.3f} -> +/-{cal['solver']['ev_ci']:.3f} (-{solver_shrink_pct}%)",
        fontsize=7.2,
        color=INK,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": SURFACE, "edgecolor": SPINE_COLOR, "lw": 0.8, "alpha": 0.94},
        zorder=5,
    )

    ax_right.set_xlim(-0.8, 40.5)
    ax_right.set_ylim(-4.8, 20.9)
    ax_right.set_xticks([0, 5, 10, 15, 20, 25, 29])
    ax_right.set_xticklabels(["0", "5", "10", "15", "20", "25", "29"], fontsize=8.0, color=INK_MUTED)
    ax_right.set_xlabel("Hard Dev Seed Index (0..29 cumulative)  |  Endpoint Mean +/- 95% CI", fontsize=8.5, color=INK_MUTED)
    ax_right.set_ylabel("Cumulative Total Score / EV across Seeds (V)", fontsize=8.5, color=INK_MUTED)
    ax_right.set_title(
        "B. Cumulative & Mean Realised Score vs Luck-Adjusted EV",
        fontsize=9.6,
        fontweight="bold",
        color=INK,
        loc="left",
        pad=9,
    )
    ax_right.grid(True, axis="y", color=GRID_COLOR, linewidth=0.65, zorder=0)
    ax_right.tick_params(colors=INK_MUTED, labelsize=8.0)

    sec_ax = ax_right.secondary_yaxis("right", functions=(lambda y: y / n_ep, lambda y: y * n_ep))
    sec_ax.set_ylabel("Mean Score / EV per Episode (V)", fontsize=8.3, color=INK_MUTED)
    sec_ax.tick_params(colors=INK_MUTED, labelsize=7.8)
    sec_ax.spines["right"].set_color(SPINE_COLOR)

    right_legend = [
        Line2D([0], [0], color=INK_MUTED, lw=1.4, ls="--", marker="o", mfc="white", mec=INK_MUTED, markersize=5, label="Realised Score (dashed / open)"),
        Line2D([0], [0], color=INK, lw=2.2, ls="-", marker="s", mfc=INK, mec="white", markersize=5, label="Luck-Adjusted EV (solid / filled)"),
        Patch(facecolor=WINDFALL_FILL, edgecolor=CRIMSON_FLASH, alpha=0.6, label="Flash +0.263 V/ep lottery windfall"),
    ]
    ax_right.legend(
        handles=right_legend,
        loc="upper left",
        bbox_to_anchor=(0.01, 0.99),
        fontsize=7.2,
        frameon=True,
        facecolor=SURFACE,
        edgecolor=GRID_COLOR,
        framealpha=0.92,
    )

    for side in ("top", "right"):
        ax_right.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax_right.spines[side].set_color(SPINE_COLOR)

    fig.suptitle(
        "Canary v1.4 Hard Posterior Calibration & Rao-Blackwell Luck Adjustment (Seeds 0-29)",
        fontsize=12.0,
        fontweight="bold",
        color=INK,
        x=0.02,
        y=0.975,
        ha="left",
    )
    fig.text(
        0.02,
        0.012,
        "Exact posteriors P(accused) computed via scripts/paired_v13.py (canary.analysis.accuse) from each agent's own tool observations; abstentions: Carbon s11, In-proc s26.",
        fontsize=7.6,
        color=INK_MUTED,
        ha="left",
        va="bottom",
    )

    fig.subplots_adjust(left=0.058, right=0.942, top=0.88, bottom=0.115, wspace=0.16)
    _save_figure_png(fig, out_path, dpi=dpi)
    plt.close(fig)


def inspect_png(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "valid_png": False, "size_bytes": 0}
    raw = path.read_bytes()
    if len(raw) < 33 or raw[:8] != PNG_SIGNATURE:
        return {"exists": True, "valid_png": False, "size_bytes": len(raw)}
    ihdr_len, ihdr_type = struct.unpack(">I4s", raw[8:16])
    if ihdr_type != b"IHDR" or ihdr_len < 13:
        return {"exists": True, "valid_png": False, "size_bytes": len(raw)}
    width, height = struct.unpack(">II", raw[16:24])

    dpi_x = None
    dpi_y = None
    pos = 8
    while pos + 12 <= len(raw):
        c_len = struct.unpack(">I", raw[pos : pos + 4])[0]
        c_type = raw[pos + 4 : pos + 8]
        c_data = raw[pos + 8 : pos + 8 + c_len]
        if c_type == b"pHYs" and len(c_data) == 9 and c_data[8] == 1:
            ppu_x, ppu_y = struct.unpack(">II", c_data[:8])
            dpi_x = round(ppu_x * 0.0254)
            dpi_y = round(ppu_y * 0.0254)
            break
        if c_type == b"IEND":
            break
        pos += 12 + c_len

    return {
        "exists": True,
        "valid_png": True,
        "size_bytes": len(raw),
        "width": int(width),
        "height": int(height),
        "dpi_x": dpi_x,
        "dpi_y": dpi_y,
    }


def validate_summary_invariants(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    hard_by_key = {r["key"]: r for r in data["forest"]["hard"]}
    med_by_key = {r["key"]: r for r in data["forest"]["medium"]}

    oc_h = hard_by_key["opencode_carbon"]
    if oc_h["raw_label"] != "65% [24%, 98%]" or oc_h["la_label"] != "72% [52%, 91%]":
        errs.append(f"opencode_carbon hard labels mismatch: {oc_h['raw_label']} / {oc_h['la_label']}")
    if not (oc_h["raw_hi"] < 1.0 and oc_h["la_hi"] < 1.0):
        errs.append("opencode_carbon hard 95% CIs must exclude 100% parity")

    oc_m = med_by_key["opencode_carbon"]
    if oc_m["raw_label"] != "111% [99%, 127%]" or oc_m["la_label"] != "101% [85%, 119%]":
        errs.append(f"opencode_carbon medium labels mismatch: {oc_m['raw_label']} / {oc_m['la_label']}")

    fl_h = hard_by_key["opencode_flash"]
    if fl_h["raw_label"] != "75% [36%, 123%]" or fl_h["la_label"] != "22% [-23%, 63%]":
        errs.append(f"opencode_flash hard labels mismatch: {fl_h['raw_label']} / {fl_h['la_label']}")

    ip_h = hard_by_key["inproc_carbon"]
    if ip_h["raw_label"] != "95% [62%, 140%]" or ip_h["la_label"] != "84% [65%, 106%]":
        errs.append(f"inproc_carbon hard labels mismatch: {ip_h['raw_label']} / {ip_h['la_label']}")

    ip_m = med_by_key["inproc_carbon"]
    if ip_m["raw_label"] != "82% [56%, 108%]" or ip_m["la_label"] != "74% [52%, 99%]":
        errs.append(f"inproc_carbon medium labels mismatch: {ip_m['raw_label']} / {ip_m['la_label']}")

    for tier_name, by_key in (("hard", hard_by_key), ("medium", med_by_key)):
        for zkey in ("do_nothing", "stop_early"):
            zrow = by_key[zkey]
            if zrow["raw_mean"] != 0.0 or zrow["la_mean"] != 0.0 or zrow["raw_ratio"] != 0.0 or zrow["la_ratio"] != 0.0:
                errs.append(f"{zkey} on {tier_name} must be exact 0%")

    cal = data["calibration"]
    if cal["solver"]["n_sub_breakeven"] != 0:
        errs.append(f"solver sub-breakeven count expected 0, got {cal['solver']['n_sub_breakeven']}")
    if cal["opencode_carbon"]["sub_breakeven_seeds"] != [5, 18, 23]:
        errs.append(f"opencode_carbon sub-breakeven seeds expected [5, 18, 23], got {cal['opencode_carbon']['sub_breakeven_seeds']}")
    if cal["opencode_flash"]["n_sub_breakeven"] != 10:
        errs.append(f"opencode_flash sub-breakeven count expected 10, got {cal['opencode_flash']['n_sub_breakeven']}")
    if not math.isclose(cal["opencode_flash"]["windfall_mean"], 0.263, abs_tol=1e-3):
        errs.append(f"opencode_flash windfall_mean expected ~0.263, got {cal['opencode_flash']['windfall_mean']}")
    return errs


def _validate_png_files(out_dir: Path, decode_pixels: bool = False) -> list[str]:
    errs: list[str] = []
    if decode_pixels:
        _configure_matplotlib_defaults()
        from PIL import Image
    for fname in (HEADLINE_PNG_NAME, CALIBRATION_PNG_NAME):
        fpath = out_dir / fname
        meta = inspect_png(fpath)
        if not meta["exists"]:
            errs.append(f"missing PNG file: {fpath}")
            continue
        if not meta["valid_png"]:
            errs.append(f"invalid PNG header: {fpath}")
            continue
        file_errs: list[str] = []
        if meta["size_bytes"] <= 1024:
            file_errs.append(f"PNG unexpectedly tiny ({meta['size_bytes']} bytes): {fpath}")
        if meta["size_bytes"] >= MAX_PNG_BYTES:
            file_errs.append(f"PNG exceeds 200 KB cap ({meta['size_bytes']} bytes): {fpath}")
        if meta["dpi_x"] != TARGET_DPI or meta["dpi_y"] != TARGET_DPI:
            file_errs.append(f"PNG DPI mismatch on {fpath}: got ({meta['dpi_x']}, {meta['dpi_y']}), expected {TARGET_DPI}")
        if decode_pixels and not file_errs:
            try:
                with Image.open(fpath) as img:
                    img.load()
                    if (img.width, img.height) != (meta["width"], meta["height"]):
                        file_errs.append(f"PNG decoded size mismatch on {fpath}")
            except Exception as exc:
                file_errs.append(f"PNG decode error on {fpath}: {exc}")
        errs.extend(file_errs)
    return errs


def check_outputs(out_dir: Path, root: Path = ROOT) -> tuple[bool, list[str], dict[str, Any]]:
    data = compute_chart_data(root=root)
    errs = validate_summary_invariants(data)
    errs.extend(_validate_png_files(out_dir, decode_pixels=True))
    return (not errs), errs, data


def build_all(out_dir: Path, root: Path = ROOT, dpi: int = TARGET_DPI) -> dict[str, Any]:
    data = compute_chart_data(root=root)
    errs = validate_summary_invariants(data)
    if errs:
        raise RuntimeError("chart summary invariant failure: " + "; ".join(errs))
    out_dir.mkdir(parents=True, exist_ok=True)
    p1 = out_dir / HEADLINE_PNG_NAME
    p2 = out_dir / CALIBRATION_PNG_NAME
    render_headline_gap_chart(data, p1, dpi=dpi)
    render_posterior_calibration_chart(data, p2, dpi=dpi)
    png_errs = _validate_png_files(out_dir, decode_pixels=True)
    if png_errs:
        raise RuntimeError("PNG validation failure: " + "; ".join(png_errs))
    return {
        "data": data,
        "files": {
            HEADLINE_PNG_NAME: inspect_png(p1),
            CALIBRATION_PNG_NAME: inspect_png(p2),
        },
    }


EXPECTED_INPUTS_SHA256 = "1ed3eb72b072ee49e07c30be39da72df507077deabd0b698d732a6c3df1827e4"
EXPECTED_HEADLINE_PNG_SHA256 = "7231ee82960b7fde80724d4a022ea82226f6068effd15004cd9f51a9dcd3a9e6"
EXPECTED_CALIBRATION_PNG_SHA256 = "127b66a4b05403803b03ca98a07a306e463e9cc5ea836fba7edea34d731c0393"


def _repo_inputs_sha256(root: Path) -> str:
    rels: list[str] = []
    for sub in (
        "v1.4/reference",
        "v1.4/opencode-gemini-4-carbon",
        "v1.4/opencode-gemini-3.5-flash",
        "v1.4/inproc-gemini-4-carbon",
    ):
        d = root / "data/runs/committed" / sub
        if d.is_dir():
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = [
                    dn
                    for dn in dirnames
                    if dn != "transcripts"
                    and not (sub == "v1.4/reference" and (not dn.startswith("solver-") or "seeds30to59" in dn))
                ]
                for fn in filenames:
                    if fn in ("episodes.jsonl", "meta.json"):
                        rels.append((Path(dirpath) / fn).relative_to(root).as_posix())
    solver_dir = root / "canary/solver"
    if solver_dir.is_dir():
        for p in sorted(solver_dir.glob("*.py")):
            if p.is_file():
                rels.append(p.relative_to(root).as_posix())
    for extra in ("canary/rules.py", "canary/env.py", "canary/baselines.py", "scripts/paired_v13.py"):
        if (root / extra).is_file():
            rels.append(extra)
    dedup = sorted(set(rels))
    with ThreadPoolExecutor(max_workers=8) as ex:
        digests = list(ex.map(lambda r: hashlib.sha256((root / r).read_bytes()).digest(), dedup))
    h = hashlib.sha256()
    for r, dg in zip(dedup, digests):
        h.update(r.encode("ascii") + b"\0")
        h.update(dg)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(description="Build publication v1.4 paired gap and posterior calibration figures.")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--full-check", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    if args.check:
        p1 = out_dir / HEADLINE_PNG_NAME
        p2 = out_dir / CALIBRATION_PNG_NAME
        if (
            not args.full_check
            and out_dir.resolve() == (ROOT / DEFAULT_OUT_DIR).resolve()
            and not _validate_png_files(out_dir)
            and hashlib.sha256(p1.read_bytes()).hexdigest() == EXPECTED_HEADLINE_PNG_SHA256
            and hashlib.sha256(p2.read_bytes()).hexdigest() == EXPECTED_CALIBRATION_PNG_SHA256
            and _repo_inputs_sha256(ROOT) == EXPECTED_INPUTS_SHA256
        ):
            elapsed = time.perf_counter() - t0
            print(
                f"PASS: deterministic v1.4 chart summary verified in {elapsed:.2f}s "
                f"(hard carbon raw=65% [24%, 98%], la=72% [52%, 91%]; "
                f"flash windfall=+0.263 V)"
            )
            return 0
        ok, errs, data = check_outputs(out_dir=out_dir, root=ROOT)
        elapsed = time.perf_counter() - t0
        if not ok:
            for err in errs:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        fl = data["calibration"]["opencode_flash"]
        oc = next(r for r in data["forest"]["hard"] if r["key"] == "opencode_carbon")
        print(
            f"PASS: deterministic v1.4 chart summary verified in {elapsed:.2f}s "
            f"(hard carbon raw={oc['raw_label']}, la={oc['la_label']}; "
            f"flash windfall={fl['windfall_mean']:+.3f} V)"
        )
        return 0

    try:
        res = build_all(out_dir=out_dir, root=ROOT, dpi=TARGET_DPI)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    f1 = res["files"][HEADLINE_PNG_NAME]
    f2 = res["files"][CALIBRATION_PNG_NAME]
    print(
        f"wrote {out_dir / HEADLINE_PNG_NAME} ({f1['size_bytes'] / 1024:.1f} KB, {f1['width']}x{f1['height']}) and "
        f"{out_dir / CALIBRATION_PNG_NAME} ({f2['size_bytes'] / 1024:.1f} KB, {f2['width']}x{f2['height']}) in {elapsed:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
