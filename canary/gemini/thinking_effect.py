"""Pooled thinking-effect estimate across the Gemini ladder (no API calls).

    python -m canary.gemini.thinking_effect [--episodes results/gemini/ladder_episodes.jsonl.gz] [--out results/gemini]

Data: the committed, keyless ladder export (valid ladder episodes only). Included: every Gemini model that the ladder
ran at >= 2 thinking levels; the imported carbon-default cell (not in the export) and hosted Gemma (separate export)
are excluded by construction, and level "default" has no step. No model or seed is hand-picked.

Outcome (main): y = agent score - solver score on the same (tier, seed), in % of the mean solver score on that tier
(i.e. pp of the solver's score). Secondary outcomes: accusation accuracy (pp) and premature-accusation regret per
episode (solver regret on steps tagged premature_accusation, split evenly over a step's tags, as in ladder_report).

Fit: OLS y ~ thinking_step + model FE + tier FE, thinking_step = minimal 0, low 1, medium 2, high 3, xhigh 4.
Dose version: thinking_step replaced by thinking tokens per episode / 10k. Per-model slopes: y ~ step + tier FE.
95% CIs: percentile bootstrap over (tier, seed) clusters (all episodes of a world move together), B resamples, fixed
RNG seed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results" / "gemini"
STEP = {"minimal": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4}
OUTCOMES = {"score_pp_of_solver": "pp of the solver's score", "accuracy_pp": "pp accuracy",
            "premature_regret_per_ep": "premature-accusation regret per episode"}


# --------------------------------------------------------------------------- data
def premature_regret(e: dict) -> float:
    from canary.gemini.ladder_report import _regret_items
    tot = 0.0
    for it in _regret_items(e):
        tags = list(it.get("tags") or [])
        if "premature_accusation" in tags:
            tot += float(it.get("regret", 0.0)) / len(tags)
    return tot


def episode_table(eps: list[dict], solver: dict[tuple[str, int], float]) -> list[dict]:
    """One row per episode of an eligible model (Gemini, >= 2 stepped levels)."""
    levels: dict[str, set] = {}
    for e in eps:
        c = e["_cell"]
        if c["model"].startswith("gemini-") and c["level"] in STEP:
            levels.setdefault(c["model"], set()).add(c["level"])
    keep = {m for m, lv in levels.items() if len(lv) >= 2}
    by_tier: dict[str, list[float]] = {}
    for (t, _s), v in solver.items():
        by_tier.setdefault(t, []).append(v)
    mean_solver = {t: float(np.mean(v)) for t, v in by_tier.items()}
    rows = []
    for e in eps:
        c = e["_cell"]
        if c["model"] not in keep or c["level"] not in STEP or (c["tier"], c["seed"]) not in solver:
            continue
        rows.append({"model": c["model"], "level": c["level"], "step": STEP[c["level"]], "tier": c["tier"],
                     "seed": c["seed"], "thinking_10k": (c.get("thinking") or 0) / 1e4,
                     "score_pp_of_solver": 100 * (e["score"] - solver[(c["tier"], c["seed"])]) / mean_solver[c["tier"]],
                     "accuracy_pp": 100.0 * bool(e.get("correct")),
                     "premature_regret_per_ep": e["_premature"] if "_premature" in e else premature_regret(e)})
    return rows


# --------------------------------------------------------------------------- estimation
def design(rows: list[dict], x: str, fe_model: bool = True) -> tuple[np.ndarray, list[str]]:
    models = sorted({r["model"] for r in rows})
    tiers = sorted({r["tier"] for r in rows})
    cols = ["intercept", x] + ([f"model:{m}" for m in models[1:]] if fe_model else []) + [f"tier:{t}" for t in tiers[1:]]
    X = np.zeros((len(rows), len(cols)))
    for i, r in enumerate(rows):
        X[i, 0], X[i, 1] = 1.0, r[x]
        if fe_model and r["model"] != models[0]:
            X[i, cols.index(f"model:{r['model']}")] = 1.0
        if r["tier"] != tiers[0]:
            X[i, cols.index(f"tier:{r['tier']}")] = 1.0
    return X, cols


def fit_slope(X: np.ndarray, y: np.ndarray) -> float:
    return float(np.linalg.lstsq(X, y, rcond=None)[0][1])


def clustered_bootstrap(rows: list[dict], x: str, y: str, B: int, rng: np.random.Generator,
                        fe_model: bool = True) -> dict:
    X, _ = design(rows, x, fe_model)
    Y = np.array([r[y] for r in rows], dtype=float)
    est = fit_slope(X, Y)
    keys = sorted({(r["tier"], r["seed"]) for r in rows})
    idx = {k: [] for k in keys}
    for i, r in enumerate(rows):
        idx[(r["tier"], r["seed"])].append(i)
    groups = [np.array(idx[k]) for k in keys]
    draws = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, len(groups), len(groups))
        ii = np.concatenate([groups[j] for j in pick])
        draws[b] = fit_slope(X[ii], Y[ii])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"slope": est, "ci95": [float(lo), float(hi)], "n_episodes": len(rows), "n_clusters": len(keys),
            "excludes_zero": bool(lo > 0 or hi < 0)}


def analyse(rows: list[dict], B: int = 10_000, seed: int = 20261115) -> dict:
    rng = np.random.default_rng(seed)
    models = sorted({r["model"] for r in rows})
    out = {"models": models, "n_episodes": len(rows), "n_clusters": len({(r["tier"], r["seed"]) for r in rows}),
           "bootstrap": {"B": B, "rng_seed": seed, "cluster": "(tier, seed)"}, "step_coding": STEP,
           "pooled_step": {}, "pooled_dose_per_10k_thinking_tokens": {}, "per_model_step": {}}
    for y in OUTCOMES:
        out["pooled_step"][y] = clustered_bootstrap(rows, "step", y, B, rng)
        out["pooled_dose_per_10k_thinking_tokens"][y] = clustered_bootstrap(rows, "thinking_10k", y, B, rng)
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        out["per_model_step"][m] = clustered_bootstrap(mr, "step", "score_pp_of_solver", B, rng, fe_model=False)
        out["per_model_step"][m]["levels"] = sorted({r["level"] for r in mr}, key=STEP.get)
    out["headline"] = headline(out)
    return out


def _f(v):
    return f"{v:+.1f}"


def headline(a: dict) -> str:
    s = a["pooled_step"]["score_pp_of_solver"]
    ci = f"{_f(s['slope'])} [{_f(s['ci95'][0])}, {_f(s['ci95'][1])}]"
    n = f"n={s['n_episodes']} episodes, {len(a['models'])} Gemini models, {s['n_clusters']} (tier, seed) worlds"
    if s["excludes_zero"]:
        verb = "adds" if s["slope"] > 0 else "removes"
        return (f"Each step up in thinking_level {verb} {ci} pp of the solver's score ({n}; OLS with model and tier "
                f"fixed effects, (tier, seed)-clustered bootstrap 95% CI).")
    return (f"Pooled over {len(a['models'])} Gemini models, one step up in thinking_level changes the score by {ci} pp "
            f"of the solver's score ({n}); the 95% CI includes zero, so the pooled effect is not distinguishable from "
            f"zero.")


# --------------------------------------------------------------------------- outputs
def to_md(a: dict) -> str:
    L = ["# Pooled thinking-effect estimate (Canary v1.4 ladder, no new calls)", "",
         f"> **{a['headline']}**", "",
         f"Generated {a['generated_at']} by `python -m canary.gemini.thinking_effect` from `{a['source']}`"
         f" (ladder.json git {a.get('ladder_git_sha', '–')[:10]}). Models with >= 2 thinking levels: "
         f"{', '.join(a['models_display'])}. Excluded by construction: the imported carbon-default cell, hosted "
         "Gemma, level `default`. Step coding: minimal 0, low 1, medium 2, high 3, xhigh 4. Outcome: agent score "
         "minus the solver's score on the same (tier, seed), in % of the solver's mean score on that tier. "
         f"95% CIs: percentile bootstrap over (tier, seed) worlds, B={a['bootstrap']['B']:,}, RNG seed "
         f"{a['bootstrap']['rng_seed']}.", "",
         "## Pooled slopes (OLS, model + tier fixed effects)", "",
         "| outcome | per thinking step [95% CI] | per 10k thinking tokens/episode [95% CI] | CI excludes 0 (step / dose) |",
         "|---|---|---|---|"]
    for y, unit in OUTCOMES.items():
        s, d = a["pooled_step"][y], a["pooled_dose_per_10k_thinking_tokens"][y]
        nd = 3 if y == "premature_regret_per_ep" else 1
        fmt = lambda v: f"{v:+.{nd}f}"  # noqa: E731
        L.append(f"| {unit} | {fmt(s['slope'])} [{fmt(s['ci95'][0])}, {fmt(s['ci95'][1])}] | {fmt(d['slope'])} "
                 f"[{fmt(d['ci95'][0])}, {fmt(d['ci95'][1])}] | {'yes' if s['excludes_zero'] else 'no'} / "
                 f"{'yes' if d['excludes_zero'] else 'no'} |")
    L += ["", f"n = {a['n_episodes']} episodes in {a['n_clusters']} (tier, seed) worlds.", "",
          "## Per-model slopes (score, pp of the solver's score per thinking step; tier fixed effect)", "",
          "| model | levels | n | slope [95% CI] |", "|---|---|---|---|"]
    for m, d in zip(a["models"], a["models_display"]):
        s = a["per_model_step"][m]
        L.append(f"| {d} | {', '.join(s['levels'])} | {s['n_episodes']} | {_f(s['slope'])} [{_f(s['ci95'][0])}, "
                 f"{_f(s['ci95'][1])}] |")
    L += ["", "Forest plot: thinking_effect.png. Data: thinking_effect.json.", ""]
    return "\n".join(L)


def forest(a: dict, out: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    items = [(d, a["per_model_step"][m]) for m, d in zip(a["models"], a["models_display"])]
    items.append(("POOLED (model + tier FE)", a["pooled_step"]["score_pp_of_solver"]))
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(items) + 1.6), constrained_layout=True)
    for i, (lab, s) in enumerate(reversed(items)):
        pooled = lab.startswith("POOLED")
        ax.errorbar(s["slope"], i, xerr=[[s["slope"] - s["ci95"][0]], [s["ci95"][1] - s["slope"]]],
                    fmt="D" if pooled else "o", color="k" if pooled else "#1f4fbf", ms=7 if pooled else 5, capsize=3)
        ax.text(s["ci95"][1], i, f"  n={s['n_episodes']}", va="center", fontsize=7)
    ax.axvline(0, ls="--", color="grey", lw=0.9)
    ax.set_yticks(range(len(items)), [lab for lab, _ in reversed(items)], fontsize=8)
    ax.set_xlabel("Δ score per thinking step (pp of solver score)\n95% CI: (tier, seed)-clustered bootstrap", fontsize=9)
    ax.set_title("Thinking effect per step, Canary v1.4 (medium + hard)", fontsize=10)
    p = out / "thinking_effect.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def main(argv=None) -> int:
    import time
    from canary.gemini.ladder_report import display_id, load_ladder, reference_episodes
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.thinking_effect", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episodes", default=str(RES / "ladder_episodes.jsonl.gz"))
    ap.add_argument("--ladder-json", default=str(RES / "ladder.json"))
    ap.add_argument("--out", default=str(RES))
    ap.add_argument("--bootstrap", type=int, default=10_000)
    a = ap.parse_args(argv)
    eps = load_ladder(Path(a.episodes))
    pairs = {(e["_cell"]["tier"], e["_cell"]["seed"]) for e in eps}
    solver = {(e["tier"], e["seed"]): e["score"] for e in reference_episodes(pairs, agents=("solver",))}
    rows = episode_table(eps, solver)
    res = analyse(rows, B=a.bootstrap)
    lj = Path(a.ladder_json)
    res.update({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "source": str(Path(a.episodes).resolve().relative_to(ROOT)) if Path(a.episodes).resolve().is_relative_to(ROOT) else a.episodes,
                "ladder_git_sha": json.loads(lj.read_text()).get("git_sha", "") if lj.exists() else "",
                "models_display": [display_id(m) for m in res["models"]]})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res["figure"] = forest(res, out)
    (out / "thinking_effect.json").write_text(json.dumps(res, indent=1) + "\n")
    (out / "thinking_effect.md").write_text(to_md(res))
    print(res["headline"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
