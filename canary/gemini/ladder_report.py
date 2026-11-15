"""Gemini Ladder report: score / solver by model x thinking level, the thinking-to-competence curve, the cost
frontier and "which mistakes does thinking fix" (regret by failure tag), all paired with the reference solver on
the same v1.4 dev seeds.

    python -m canary.gemini.ladder_report --runs ~/agent-arena-data/gemini/ladder/ladder-v14 \
        [--import-cell gemini-4-carbon:default=<path to data/runs/committed/v1.4/inproc-gemini-4-carbon>] \
        [--ledger <extra ledger jsonl or dir> ...] [--out results/gemini] [--min-n 1]

Inputs
- ladder cells: RUNS/<model>/<level>/<tier>/<seed>/episodes.jsonl (canary.gemini.ladder; valid episodes only);
- imported cells (read-only), e.g. the AfterQuery measurement's gemini-4-carbon at the model-default thinking
  level (same in-process harness, same dev seeds); their thinking tokens are not split out, so the curve uses
  their output tokens incl. thinking and marks the point;
- reference: the solver and scripted baselines replayed in-process on exactly the same (tier, seed) worlds
  (dev seeds use the public HMAC key, so these are the worlds the agent saw; checked against the measurement's
  committed reference run);
- ledger rows (RUNS/_ledger/*.jsonl + --ledger): calls, tokens and list-price cost by ladder run_id.

Outputs (OUT = results/gemini): ladder.md, ladder.json (generated_at, git_sha, ledger_run_ids, rows, tags,
probe), ladder_heatmap.png, ladder_curve.png, ladder_cost.png, ladder_tags.png.
Paired statistics reuse scripts/paired_v13.py (boot_ratio: paired bootstrap over seeds, 10,000 resamples;
post_expected: luck-adjusted score under the solver's exact posterior), as scripts/paired_gemini.py does.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEVEL_ORDER = ["minimal", "low", "medium", "high", "xhigh", "default"]
MODEL_ORDER = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-4-hydrogen",
               "gemini-4-argon", "gemini-4-carbon"]
REFERENCE_AGENTS = ("solver", "grok_tactics", "heuristic", "do_nothing")
# USD / 1M tokens (input, output incl. thinking, cached input), standard paid tier,
# aistudio.google.com/docs/pricing checked 2026-11-14 14:20 EET. gemini-3.5-flash is served as gemini-3.6-flash
# (the API's modelVersion) and billed at the 3.6 Flash price. canary.llm.pricing lacks the two flash rows, so the
# ledger's own cost_usd is 0 (cost_unknown) for them; the report prices tokens itself.
PRICES = {"gemini-3.1-flash-lite": (0.25, 1.50, 0.025), "gemini-3.5-flash": (0.75, 3.75, 0.075),
          "gemini-3.8-flash": (0.75, 3.75, 0.075), "gemini-4-hydrogen": (1.50, 7.50, 0.075),
          "gemini-4-argon": (2.00, 10.00, 0.10), "gemini-4-carbon": (2.00, 10.00, 0.10)}
TIERS = ("medium", "hard")


def _paired():
    sd = str(ROOT / "scripts")
    if sd not in sys.path:
        sys.path.insert(0, sd)
    import paired_v13
    return paired_v13


def price(model: str, tin: int, tout_incl_thinking: int, cached: int) -> float:
    p = PRICES.get(model)
    if p is None:
        return float("nan")
    return ((tin - cached) * p[0] + cached * p[2] + tout_incl_thinking * p[1]) / 1e6


# --------------------------------------------------------------------------- loading
def _ladder_lines(runs: Path):
    """(model, level, tier, seed, line) from a ladder dir, or from an exported ladder_episodes.jsonl.gz."""
    runs = Path(runs)
    if runs.is_file():
        import gzip
        with gzip.open(runs, "rt") as fh:
            for line in fh:
                if line.strip():
                    lad = (json.loads(line).get("meta") or {}).get("ladder") or {}
                    yield lad["model"], lad["level"], lad["tier"], str(lad["seed"]), line
        return
    for f in sorted(runs.glob("*/*/*/*/episodes.jsonl")):
        model, level, tier, seed = f.parent.relative_to(runs).parts
        if model.startswith("_"):
            continue
        for line in f.read_text().splitlines():
            yield model, level, tier, seed, line


def _iter_run_paths(runs: Path | str | list[Path | str]) -> list[Path]:
    items = [str(runs)] if isinstance(runs, (str, Path)) else [str(x) for x in runs]
    out: list[Path] = []
    for it in items:
        for part in it.split(","):
            if part.strip():
                out.append(Path(part.strip()).expanduser())
    return out


def load_ladder(runs: Path | str | list[Path | str]) -> list[dict]:
    """Valid ladder episodes across one or more run dirs/exports, deduplicated per (model, level, tier, seed)."""
    by_cell: dict[tuple[str, str, str, int], dict] = {}
    for rpath in _iter_run_paths(runs):
        for model, level, tier, seed, line in _ladder_lines(rpath):
            if not line.strip():
                continue
            e = json.loads(line)
            if (e.get("meta") or {}).get("valid") is False or e.get("end_reason") == "error":
                continue
            lad = (e.get("meta") or {}).get("ladder") or {}
            tok = lad.get("tokens") or {}
            s_int = int(seed)
            e["_cell"] = {"model": model, "level": level, "tier": tier, "seed": s_int, "source": "ladder",
                          "run_id": lad.get("run_id"), "thinking": tok.get("thinking"), "calls": tok.get("calls"),
                          "in": tok.get("in"), "out": tok.get("out"), "cached": tok.get("cached"),
                          "wall_s": lad.get("wall_s"), "thinking_is_estimate": False,
                          "tiers_version": lad.get("tiers_version"), "launch_git_sha": lad.get("launch_git_sha"),
                          "code_fingerprint": lad.get("code_fingerprint"),
                          "model_versions": sorted((tok.get("model_versions") or {}).keys())}
            t = e["_cell"]
            t["cost_usd"] = price(model, t["in"] or 0, (t["out"] or 0) + (t["thinking"] or 0), t["cached"] or 0)
            key = (model, level, tier, s_int)
            if key not in by_cell:
                by_cell[key] = e
    return list(by_cell.values())


def load_import(spec: str) -> list[dict]:
    """'<model>:<level>=<data/runs dir>': read-only import of another run of the same in-process harness."""
    lhs, _, path = spec.partition("=")
    model, _, level = lhs.partition(":")
    from canary.analysis.gap import load_runs
    out = []
    for e in load_runs(path):
        if e.get("end_reason") == "error" or e["tier"] not in TIERS:
            continue
        mf = next(iter(Path(path).rglob(f"{e['meta'].get('run_id')}/meta.json")), None)
        if mf is None:
            mf = Path(path) / e["tier"] / "meta.json"
        msha = json.loads(mf.read_text()).get("git_sha") if mf.exists() else None
        u = (e.get("meta") or {}).get("usage") or {}
        e["_cell"] = {"model": model, "level": level, "tier": e["tier"], "seed": int(e["seed"]),
                      "source": "import:" + str(path).replace(str(Path.home()), "~"), "run_id": None, "thinking": u.get("out"), "calls": u.get("calls"),
                      "in": u.get("in"), "out": None, "cached": u.get("cached_in"), "wall_s": None,
                      "thinking_is_estimate": True, "tiers_version": "v1.4 (imported dir)",
                      "launch_git_sha": msha, "code_fingerprint": None,
                      "model_versions": [],
                      "cost_usd": u.get("cost_usd_est", u.get("cost_usd"))}
        out.append(e)
    return out


def reference_episodes(pairs: set[tuple[str, int]], agents=REFERENCE_AGENTS) -> list[dict]:
    """Solver and baselines replayed in-process on the exact (tier, seed) worlds the ladder used."""
    import dataclasses
    from canary.eval import make_env, make_policy_factory, run_episode
    out = []
    for agent in agents:
        fac = make_policy_factory(agent)
        for tier, seed in sorted(pairs):
            r = run_episode(make_env(tier, seed), fac(seed))
            d = json.loads(json.dumps(dataclasses.asdict(r), default=str))
            d["agent"] = agent
            out.append(d)
    return out


def load_ledger(runs: Path | str | list[Path | str], extra: list[str]) -> list[dict]:
    import gzip
    files: list[str] = []
    for rp in _iter_run_paths(runs):
        if rp.is_dir():
            files += glob.glob(str(rp / "_ledger" / "*.jsonl"))
    for x in extra or []:
        p = Path(x).expanduser()
        files += glob.glob(str(p / "**" / "*.jsonl"), recursive=True) if p.is_dir() else [str(p)]
    rows = []
    for fp in sorted(set(files)):
        with (gzip.open(fp, "rt") if fp.endswith(".gz") else open(fp)) as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if r.get("feature") == "ladder"]


# --------------------------------------------------------------------------- stats
def _mean(xs):
    xs = [x for x in xs if x is not None and x == x]
    return sum(xs) / len(xs) if xs else float("nan")


def cell_rows(eps: list[dict], solver: dict, B: int = 10000) -> list[dict]:
    from canary.analysis.gap import mean_ci
    pv = _paired()
    groups = defaultdict(list)
    for e in eps:
        c = e["_cell"]
        groups[(c["model"], c["level"], c["tier"])].append(e)
    rows = []
    for (model, level, tier), es in groups.items():
        es.sort(key=lambda e: e["_cell"]["seed"])
        paired = [e for e in es if (tier, e["_cell"]["seed"]) in solver]
        f = [e["score"] for e in paired]
        s = [solver[(tier, e["_cell"]["seed"])]["score"] for e in paired]
        m, h = mean_ci([e["score"] for e in es])
        ms = _mean(s)
        dm, dh = mean_ci([a - b for a, b in zip(f, s)]) if f else (float("nan"), float("nan"))
        lo, hi = pv.boot_ratio(f, s, B=B) if len(f) > 1 and ms > 0 else (float("nan"), float("nan"))
        pe = [pv.post_expected(e) for e in paired]
        pe_s = [pv.post_expected(solver[(tier, e["_cell"]["seed"])]) for e in paired]
        pe_ok = bool(pe) and None not in pe + pe_s and sum(pe_s) > 0
        pe_ratio = sum(pe) / sum(pe_s) if pe_ok else float("nan")
        pe_lo, pe_hi = pv.boot_ratio(pe, pe_s, B=B) if pe_ok and len(pe) > 1 else (float("nan"), float("nan"))
        acc = [e for e in es if e.get("accused")]
        cs = [e["_cell"] for e in es]
        rows.append(dict(
            model=model, level=level, tier=tier, n=len(es), seeds=[c["seed"] for c in cs],
            source=cs[0]["source"], mean=m, ci=h, accuracy=sum(bool(e.get("correct")) for e in es) / len(es),
            accused_rate=len(acc) / len(es), accuse_day=_mean([e.get("final_day") for e in acc]),
            solver_same_seeds=ms, ratio=(_mean(f) / ms) if f and ms > 0 else float("nan"), ratio_lo=lo, ratio_hi=hi,
            diff=dm, diff_ci=dh, luck_adj_ratio=pe_ratio, luck_adj_lo=pe_lo, luck_adj_hi=pe_hi,
            thinking_per_ep=_mean([c["thinking"] for c in cs]), thinking_is_estimate=cs[0]["thinking_is_estimate"],
            calls_per_ep=_mean([c["calls"] for c in cs]), in_per_ep=_mean([c["in"] for c in cs]),
            cost_per_ep=_mean([c["cost_usd"] for c in cs]), wall_min_per_ep=_mean([c["wall_s"] for c in cs]) / 60,
            run_ids=[c["run_id"] for c in cs if c["run_id"]],
            tiers_versions=sorted({str(c.get("tiers_version")) for c in cs}),
            launch_git_shas=sorted({str(c.get("launch_git_sha")) for c in cs}),
            code_fingerprints=sorted({str(c.get("code_fingerprint")) for c in cs}),
            model_versions=sorted({v for c in cs for v in c.get("model_versions") or []})))
    key = lambda r: (TIERS.index(r["tier"]) if r["tier"] in TIERS else 9,  # noqa: E731
                     MODEL_ORDER.index(r["model"]) if r["model"] in MODEL_ORDER else 99,
                     LEVEL_ORDER.index(r["level"]) if r["level"] in LEVEL_ORDER else 99)
    return sorted(rows, key=key)


def reference_rows(ref: list[dict], pairs: set[tuple[str, int]]) -> list[dict]:
    from canary.analysis.gap import mean_ci
    rows = []
    for agent in REFERENCE_AGENTS:
        for tier in TIERS:
            es = [e for e in ref if e["agent"] == agent and e["tier"] == tier and (tier, e["seed"]) in pairs]
            if es:
                m, h = mean_ci([e["score"] for e in es])
                rows.append(dict(agent=agent, tier=tier, n=len(es), mean=m, ci=h,
                                 accuracy=sum(bool(e["correct"]) for e in es) / len(es)))
    return rows


def _regret_items(e: dict) -> list[dict]:
    from canary.analysis.tags import to_result
    from canary.solver.regret import attribute
    try:
        return attribute(to_result(e)) or []
    except Exception:  # noqa: BLE001
        return []


def _bucket(items_by_ep: list[list[dict]]) -> dict:
    """Regret per episode by failure tag. Each step's regret is split evenly over its tags; steps the tagger leaves
    untagged go to `other:<tool>` (e.g. other:accuse = accusing at a belief the tagger does not call premature),
    so the buckets sum to the total solver regret."""
    n = len(items_by_ep)
    agg: dict = defaultdict(lambda: {"regret": 0.0, "eps": 0})
    for items in items_by_ep:
        seen = set()
        for it in items:
            r = float(it.get("regret", 0.0))
            if r <= 0:
                continue
            keys = list(it.get("tags") or []) or [f"other:{it.get('action')}"]
            for k in keys:
                agg[k]["regret"] += r / len(keys)
                if k not in seen:
                    agg[k]["eps"] += 1
                    seen.add(k)
    total = sum(v["regret"] for v in agg.values())
    return {"episodes": n, "regret_per_ep": round(total / max(1, n), 4),
            "tags": {k: {"regret_per_ep": round(v["regret"] / max(1, n), 4), "rate": round(v["eps"] / max(1, n), 3)}
                     for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["regret"])}}


def tag_tables(eps: list[dict]) -> dict:
    """Solver regret (canary.solver.regret.attribute, the attribution canary.analysis.tags uses) by failure tag,
    per (model, level, tier) and pooled per (level, tier) over the models that ran every one of low/medium/high."""
    items = {id(e): _regret_items(e) for e in eps}
    per_cell: dict = defaultdict(list)
    for e in eps:
        c = e["_cell"]
        per_cell[f"{c['model']}@{c['level']}|{c['tier']}"].append(items[id(e)])
    have = defaultdict(set)
    for e in eps:
        have[e["_cell"]["model"]].add(e["_cell"]["level"])
    common = sorted(m for m, ls in have.items() if {"low", "medium", "high"} <= ls)
    pooled: dict = defaultdict(list)
    for e in eps:
        c = e["_cell"]
        if c["model"] in common and c["level"] in ("low", "medium", "high"):
            pooled[f"{c['level']}|{c['tier']}"].append(items[id(e)])
    return {"per_cell": {k: _bucket(v) for k, v in per_cell.items()}, "pooled_common_models": common,
            "pooled": {k: _bucket(v) for k, v in pooled.items()}}


# --------------------------------------------------------------------------- figures
def figures(rows: list[dict], ref_rows: list[dict], tags: dict, out: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    written = []
    models = [m for m in MODEL_ORDER if any(r["model"] == m for r in rows)] + \
        sorted({r["model"] for r in rows} - set(MODEL_ORDER))
    levels = [lv for lv in LEVEL_ORDER if any(r["level"] == lv for r in rows)]
    colors = dict(zip(MODEL_ORDER, ["#9aa5b1", "#5b8def", "#1f4fbf", "#f2a541", "#d9603b", "#8e1b1b"]))
    solver_mean = {r["tier"]: r["mean"] for r in ref_rows if r["agent"] == "solver"}

    # (a) heatmap: score / solver
    fig, axes = plt.subplots(1, 2, figsize=(12, 0.55 * len(models) + 2.2), squeeze=False, sharey=True,
                             constrained_layout=True)
    for ax, tier in zip(axes[0], TIERS):
        grid = [[float("nan")] * len(levels) for _ in models]
        for r in rows:
            if r["tier"] == tier and r["model"] in models:
                grid[models.index(r["model"])][levels.index(r["level"])] = r["ratio"]
        im = ax.imshow(grid, cmap="RdYlGn", vmin=-0.5, vmax=1.2, aspect="auto")
        ax.set_xticks(range(len(levels)), levels)
        ax.set_yticks(range(len(models)), models)
        if tier != TIERS[0]:
            ax.tick_params(labelleft=False)
        for r in rows:
            if r["tier"] == tier and r["model"] in models:
                ax.text(levels.index(r["level"]), models.index(r["model"]),
                        f"{r['ratio']:.0%}\nn={r['n']}" if r["ratio"] == r["ratio"] else f"n={r['n']}",
                        ha="center", va="center", fontsize=7)
        ax.set_title(f"{tier}: mean score / solver (same seeds)")
        ax.set_xlabel("thinking level")
    fig.colorbar(im, ax=axes[0].tolist(), shrink=0.8)
    p = out / "ladder_heatmap.png"
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    written.append(p.name)

    # (b) curve: mean score vs mean thinking tokens per episode
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), squeeze=False)
    for ax, tier in zip(axes[0], TIERS):
        for m in models:
            pts = sorted([r for r in rows if r["tier"] == tier and r["model"] == m
                          and r["thinking_per_ep"] == r["thinking_per_ep"]], key=lambda r: r["thinking_per_ep"])
            if not pts:
                continue
            xs = [r["thinking_per_ep"] for r in pts]
            ax.errorbar(xs, [r["mean"] for r in pts], yerr=[r["ci"] for r in pts], marker="o", capsize=2,
                        color=colors.get(m), label=m, alpha=0.9)
            for r, x in zip(pts, xs):
                ax.annotate(r["level"] + ("*" if r["thinking_is_estimate"] else ""), (x, r["mean"]), fontsize=7,
                            xytext=(3, 3), textcoords="offset points")
        if tier in solver_mean:
            ax.axhline(solver_mean[tier], ls="--", color="k", lw=1, label="reference solver")
        ax.axhline(0, color="#999", lw=0.6)
        ax.set_xscale("symlog", linthresh=1000)
        ax.set_xlim(-200, 150000)
        ax.set_xticks([0, 1000, 10000, 100000], ["0", "1k", "10k", "100k"])
        ax.set_xlabel("mean thinking tokens per episode (symlog; 0 = no thinking)")
        ax.set_ylabel("mean score (true V if correct, -1 wrong)")
        ax.set_title(f"{tier}: thinking-to-competence")
    axes[0][0].legend(fontsize=7, loc="lower right")
    fig.text(0.01, -0.02, "* imported cell: output tokens incl. thinking (thinking not split out)", fontsize=7)
    p = out / "ladder_curve.png"
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    written.append(p.name)

    # (c) cost frontier: score vs $ per episode
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), squeeze=False)
    for ax, tier in zip(axes[0], TIERS):
        pts = [r for r in rows if r["tier"] == tier and r["cost_per_ep"] == r["cost_per_ep"] and r["cost_per_ep"] > 0]
        for r in pts:
            ax.scatter(r["cost_per_ep"], r["mean"], color=colors.get(r["model"]), s=30)
            ax.annotate(f"{r['model'].replace('gemini-', '')}@{r['level']}", (r["cost_per_ep"], r["mean"]),
                        fontsize=6, xytext=(3, 2), textcoords="offset points")
        front, best = [], -9.0
        for r in sorted(pts, key=lambda r: r["cost_per_ep"]):
            if r["mean"] > best:
                front.append(r)
                best = r["mean"]
        if front:
            ax.plot([r["cost_per_ep"] for r in front], [r["mean"] for r in front], "k-", lw=0.8, alpha=0.6,
                    label="Pareto frontier")
        if tier in solver_mean:
            ax.axhline(solver_mean[tier], ls="--", color="k", lw=1, label="reference solver")
        ax.set_xscale("log")
        ax.set_xlabel("list-price $ per episode (log)")
        ax.set_ylabel("mean score")
        ax.set_title(f"{tier}: cost frontier")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7, loc="lower right")
    p = out / "ladder_cost.png"
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    written.append(p.name)

    # (d) regret per episode by failure tag, per level (pooled over models that ran low/medium/high)
    pooled = tags.get("pooled") or {}
    if pooled:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), squeeze=False)
        all_tags = sorted({t for v in pooled.values() for t in v["tags"]})
        for ax, tier in zip(axes[0], TIERS):
            lv = [x for x in ("low", "medium", "high") if f"{x}|{tier}" in pooled]
            w = 0.8 / max(1, len(lv))
            for i, x in enumerate(lv):
                d = pooled[f"{x}|{tier}"]["tags"]
                ax.bar([j + i * w for j in range(len(all_tags))], [d.get(t, {}).get("regret_per_ep", 0) for t in all_tags],
                       width=w, label=f"{x} (n={pooled[f'{x}|{tier}']['episodes']})",
                       color=["#9ecae1", "#4292c6", "#08306b"][("low", "medium", "high").index(x)])
            ax.set_xticks([j + 0.4 - w / 2 for j in range(len(all_tags))], all_tags, rotation=30, ha="right", fontsize=7)
            ax.set_ylabel("solver regret per episode")
            ax.set_title(f"{tier}: which mistakes does thinking fix?")
            if ax.get_legend_handles_labels()[0]:
                ax.legend(fontsize=7)
        fig.text(0.01, -0.06, "pooled over " + ", ".join(tags.get("pooled_common_models", [])), fontsize=7)
        p = out / "ladder_tags.png"
        fig.savefig(p, dpi=130, bbox_inches="tight")
        plt.close(fig)
        written.append(p.name)
    return written


SERVED_AS = {"gemini-3.5-flash": "gemini-3.6-flash"}  # requested id -> API-served modelVersion (see PRICES note)
FRONTIER_TITLE = "Thinking is a dial along the competence-per-dollar frontier (Canary v1.4 {tier})"


def _short(model: str) -> str:
    s = model.replace("gemini-", "")
    return f"{s} (served {SERVED_AS[model].replace('gemini-', '')})" if model in SERVED_AS else s


def frontier_points(rows: list[dict], gemma_rows: list[dict] | None, tier: str) -> list[dict]:
    """One point per cell on `tier`: % of the solver (paired, 95% CI) vs list-price $ per episode (None = no list price)."""
    pts = []
    for r, kind in [(r, "gemini") for r in rows] + [(r, "gemma") for r in gemma_rows or []]:
        if r["tier"] != tier or r["ratio"] != r["ratio"]:
            continue
        imported = r["source"].startswith("import")
        cost = r["cost_per_ep"] if r["cost_per_ep"] == r["cost_per_ep"] and r["cost_per_ep"] > 0 else None
        pts.append({"model": r["model"], "level": r["level"], "tier": tier, "n": r["n"], "kind": kind,
                    "imported": imported, "cost_per_ep_usd": cost, "ratio": r["ratio"],
                    "ratio_lo": None if r["ratio_lo"] != r["ratio_lo"] else r["ratio_lo"],
                    "ratio_hi": None if r["ratio_hi"] != r["ratio_hi"] else r["ratio_hi"],
                    "served_model_versions": r.get("model_versions") or [],
                    "label": (f"{r['model']} via Gemini API (hosted Gemma)" if kind == "gemma" else
                              f"{_short(r['model'])} {r['level']}" + (" (in-process, imported)" if imported else ""))})
    return pts


def frontier(rows: list[dict], gemma_rows: list[dict] | None, out: Path, tiers=TIERS) -> list[str]:
    """frontier.png (hard) [+ frontier_<tier>.png] and frontier.json: the headline competence-per-dollar chart."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    colors = dict(zip(MODEL_ORDER, ["#9aa5b1", "#5b8def", "#1f4fbf", "#f2a541", "#d9603b", "#8e1b1b"]))
    written, doc = [], {"title": {}, "x": "list-price USD per episode (log)", "y": "score / solver on the same seeds "
                        "(paired bootstrap 95% CI)", "points": {}}
    for tier in tiers:
        pts = frontier_points(rows, gemma_rows, tier)
        if not pts:
            continue
        doc["points"][tier] = pts
        doc["title"][tier] = FRONTIER_TITLE.format(tier=tier)
        unpriced = [p for p in pts if p["cost_per_ep_usd"] is None]
        fig = plt.figure(figsize=(10, 6.2), constrained_layout=True)
        gs = fig.add_gridspec(1, 2, width_ratios=[1, 9] if unpriced else [0.001, 9])
        ax = fig.add_subplot(gs[1])
        ax0 = fig.add_subplot(gs[0], sharey=ax)
        err = lambda p: ([[max(0, p["ratio"] - p["ratio_lo"])], [max(0, p["ratio_hi"] - p["ratio"])]]  # noqa: E731
                         if p["ratio_lo"] is not None else None)
        models = [m for m in MODEL_ORDER if any(p["model"] == m and p["kind"] == "gemini" and not p["imported"]
                                                    for p in pts)]
        for m in models:
            line = sorted([p for p in pts if p["model"] == m and p["kind"] == "gemini" and not p["imported"]
                           and p["cost_per_ep_usd"]], key=lambda p: LEVEL_ORDER.index(p["level"]))
            ax.plot([p["cost_per_ep_usd"] for p in line], [p["ratio"] for p in line], "-", color=colors.get(m),
                    lw=1.4, alpha=0.8, label=_short(m) + ": " + " → ".join(p["level"] for p in line))
            for p in line:
                ax.errorbar(p["cost_per_ep_usd"], p["ratio"], yerr=err(p), fmt="o", color=colors.get(m), ms=5,
                            capsize=2, lw=0.8)
                ax.annotate(p["level"], (p["cost_per_ep_usd"], p["ratio"]), fontsize=6.5, xytext=(4, 3),
                            textcoords="offset points", color=colors.get(m))
        for p in [p for p in pts if p["imported"] and p["cost_per_ep_usd"]]:
            ax.errorbar(p["cost_per_ep_usd"], p["ratio"], yerr=err(p), fmt="D", mfc="white", color=colors.get(p["model"], "k"),
                        ms=7, capsize=2, lw=0.8, label=f"{_short(p['model'])} default (in-process measurement, imported)")
        gm = ["s", "^", "v", "P"]
        for i, p in enumerate(unpriced):
            ax0.errorbar(i, p["ratio"], yerr=err(p), fmt=gm[i % len(gm)], color="#2e7d32", ms=8, capsize=2, lw=0.8)
            ax.plot([], [], gm[i % len(gm)], color="#2e7d32", ms=8, label=p["label"] + " (no list price; left strip)")
        ax0.set_xlim(-0.6, max(0.6, len(unpriced) - 0.4))
        ax0.set_xticks([])
        ax0.set_xlabel("no list\nprice", fontsize=7)
        ax0.set_ylabel("score / solver, same seeds (95% CI)")
        if not unpriced:
            ax0.set_axis_off()
            ax.set_ylabel("score / solver, same seeds (95% CI)")
        for a_ in (ax0, ax):
            a_.axhline(1.0, ls="--", color="k", lw=0.9)
            a_.axhline(0.0, ls=":", color="grey", lw=0.8)
        ax.set_xscale("log")
        ax.set_xlabel("list-price USD per episode (log)")
        ylo = min([p["ratio_lo"] if p["ratio_lo"] is not None else p["ratio"] for p in pts] + [-0.2])
        yhi = max([p["ratio_hi"] if p["ratio_hi"] is not None else p["ratio"] for p in pts] + [1.3])
        ax.set_ylim(max(ylo, -2.0) - 0.05, min(yhi, 2.0) + 0.05)
        from matplotlib.ticker import PercentFormatter
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.plot([], [], "--", color="k", lw=0.9, label="reference solver (100%)")
        ax.plot([], [], ":", color="grey", lw=0.8, label="do-nothing (0%)")
        if unpriced:
            ax.tick_params(labelleft=False)
        ax.legend(fontsize=7, loc="lower right", framealpha=0.9)
        fig.suptitle(doc["title"][tier], fontsize=11)
        ns = sorted({p["n"] for p in pts})
        served = sorted({v for p in pts for v in p["served_model_versions"]})
        note = (f"n per point (paired seeds) = {', '.join(map(str, ns))} (exact n per point in frontier.json). "
                f"Dashed line = reference solver (100%); dotted = do-nothing (0). Requested gemini-3.5-flash is served "
                f"as gemini-3.6-flash. API-served model versions: {', '.join(served) or '–'}. Costs: list-price USD from "
                f"token counts (PRICES in canary/gemini/ladder_report.py). Error bars clipped to the axis at ±200%.")
        fig.text(0.01, -0.035, note, fontsize=6.5, wrap=True, ha="left", va="top")
        name = "frontier.png" if tier == "hard" else f"frontier_{tier}.png"
        fig.savefig(out / name, dpi=150, bbox_inches="tight")
        plt.close(fig)
        written.append(name)
    (out / "frontier.json").write_text(json.dumps(_nan_to_none(doc), indent=1) + "\n")
    return written


# --------------------------------------------------------------------------- markdown
def _f(x, nd=3):
    return "–" if x is None or x != x else f"{x:+.{nd}f}" if nd == 3 else f"{x:.{nd}f}"


def _pct(r, k):
    v, lo, hi = r[k], r[k.replace("ratio", "lo") if k == "luck_adj_ratio" else "ratio_lo"], \
        r[k.replace("ratio", "hi") if k == "luck_adj_ratio" else "ratio_hi"]
    if v != v:
        return "–"
    return f"{v:.0%}" if lo != lo else f"{v:.0%} [{lo:.0%}, {hi:.0%}]"


def to_md(doc: dict) -> str:
    rows, ref = doc["rows"], doc["reference"]
    head = Path(doc.get("headline_file") or "")
    hl = head.read_text().rstrip() if head.is_file() else headline(rows, doc.get("tags") or {})
    figs = doc.get("figures") or []
    chart = [f"![{FRONTIER_TITLE.format(tier='hard')}](frontier.png)", "",
             "Hard tier. Medium tier: [frontier_medium.png](frontier_medium.png). Points and n: frontier.json.", ""] \
        if "frontier.png" in figs else []
    L = [f"# Gemini Ladder (Canary v1.4)", "", hl, ""] + chart + [
         f"Generated {doc['generated_at']} at git `{doc['git_sha'][:10]}` from `{doc['runs']}`. "
         f"{doc['episodes']} valid Gemini episodes in {len(rows)} cells; ledger: {doc['ledger']['calls']} calls, "
         f"{doc['ledger']['run_ids']} run ids, list price ${doc['ledger']['cost_usd_priced']:.2f}.", "",
         "Every cell is one (model, thinking level, tier) played by the in-process `LLMPolicy` (full history, "
         "thought-signature replay) through `canary.agents.play`, the frontier measurement's own runner, on v1.4 "
         "dev seeds. The solver and baselines are replayed on exactly the same worlds. "
         "**ratio** = mean score / solver's mean on the same seeds, with a paired bootstrap 95% CI over seeds; "
         "**luck-adj.** scores each accusation as P·V − (1−P) under the solver's exact posterior at that step.", ""]
    for tier in TIERS:
        tr = [r for r in rows if r["tier"] == tier]
        if not tr:
            continue
        L += [f"## {tier}", "",
              "| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | "
              "paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in tr:
            th = "–" if r["thinking_per_ep"] != r["thinking_per_ep"] else f"{r['thinking_per_ep']:,.0f}" + \
                ("*" if r["thinking_is_estimate"] else "")
            src = " (imported†)" if r["source"].startswith("import") else ""
            L.append(f"| {model_label(r)}{src} | {r['level']} | {r['n']} | {_f(r['mean'])} ± {_f(r['ci'], 2)} | "
                     f"{r['accuracy']:.2f} | {_f(r['accuse_day'], 1)} | {_f(r['solver_same_seeds'])} | "
                     f"**{_pct(r, 'ratio')}** | {_f(r['diff'])} ± {_f(r['diff_ci'], 2)} | {_pct(r, 'luck_adj_ratio')} | "
                     f"{th} | {_f(r['calls_per_ep'], 0)} | {_f(r['cost_per_ep'], 2)} | {_f(r['wall_min_per_ep'], 1)} |")
        L.append("")
        rr = [r for r in ref if r["tier"] == tier]
        L += ["Reference on the union of these seeds: " + "; ".join(
            f"{r['agent']} {_f(r['mean'])} ± {_f(r['ci'], 2)} (n={r['n']}, acc {r['accuracy']:.2f})" for r in rr), ""]
    tv = sorted({t for r in rows for t in r["tiers_versions"]})
    shas = sorted({t for r in rows for t in r["launch_git_shas"]})
    fps = sorted({t for r in rows for t in r["code_fingerprints"]})
    mv = sorted({t for r in rows for t in r["model_versions"]})
    L += [f"Provenance: tiers {', '.join(tv)}; launch commits {', '.join(x[:10] for x in shas)}; code fingerprints "
          f"(env/harness/client files) {', '.join(fps)}; API-served model versions {', '.join(mv) or '–'}.", ""]
    L += ["\\* imported cell: output tokens incl. thinking (the measurement's usage does not split thinking out).",
          "† imported read-only from the AfterQuery measurement (branch justSilas-gemini); not rerun by the ladder.", ""]
    tags = doc.get("tags") or {}
    pooled = tags.get("pooled") or {}
    if pooled:
        L += ["## Which mistakes does thinking fix?", "",
              f"Solver regret per episode by failure tag (`canary.solver.regret.attribute`), pooled over the models "
              f"that ran low, medium and high: {', '.join(display_id(m) for m in tags.get('pooled_common_models', []))}. "
              "Δ = high − low (negative = thinking fixes it).", ""]
        for tier in TIERS:
            lv = [x for x in ("low", "medium", "high") if f"{x}|{tier}" in pooled]
            if not lv:
                continue
            all_tags = sorted({t for x in lv for t in pooled[f"{x}|{tier}"]["tags"]})
            L += [f"**{tier}**", "", "| tag | " + " | ".join(f"{x} (n={pooled[f'{x}|{tier}']['episodes']})" for x in lv)
                  + " | Δ high−low |", "|---|" + "---|" * (len(lv) + 1)]
            for t in all_tags:
                vals = [pooled[f"{x}|{tier}"]["tags"].get(t, {}).get("regret_per_ep", 0.0) for x in lv]
                rates = [pooled[f"{x}|{tier}"]["tags"].get(t, {}).get("rate", 0.0) for x in lv]
                delta = (vals[-1] - vals[0]) if "low" in lv and "high" in lv else float("nan")
                L.append(f"| {t} | " + " | ".join(f"{v:.3f} ({r:.0%} eps)" for v, r in zip(vals, rates))
                         + f" | {_f(delta)} |")
            L.append("")
    L += gemma_md(doc.get("gemma"))
    if doc.get("probe"):
        acc = defaultdict(list)
        for r in doc["probe"]:
            if r["ok"] and r["level"] != "default":
                acc[r["model"]].append(r["level"])
        L += ["## Thinking levels each model accepts (probe)", "",
              "| model | accepted thinking_level |", "|---|---|"] + \
             [f"| {display_id(m)} | {', '.join(v)} |" for m, v in acc.items()] + [""]
    L += [f"Figures: {', '.join(doc['figures'])}. Data: ladder.json (rows, tags, ledger run ids).", ""]
    return "\n".join(L)


GEMMA_LABEL = "via Gemini API (hosted Gemma)"


def gemma_md(g: dict | None) -> list[str]:
    """The open-weight Gemma section: same LLMPolicy, same v1.4 dev seeds and solver pairing as the Gemini cells."""
    if not g or not g.get("rows"):
        return []
    ids = g["ledger_run_ids"]
    L = ["## Open-weight Gemma (hosted Gemma via the Gemini API)", "",
         "Gemma 4 open-weight models served by Google's hosted Gemini API (not self-hosted), played by the same "
         "`LLMPolicy` with native function calling on the same v1.4 dev seeds; ratios are paired against the solver "
         f"on the same seeds. Gemma gets no thinking config (level `default`). {g['episodes']} valid episodes from "
         f"`{g['runs']}`; ledger: {g['ledger']['calls']} calls, {g['ledger']['errors']} errors, {len(ids)} run ids "
         f"(e.g. {', '.join(ids[:2]) or '–'}). $/ep is not shown: our price table has no hosted-Gemma list price.", ""]
    for tier in TIERS:
        tr = [r for r in g["rows"] if r["tier"] == tier]
        if not tr:
            continue
        L += [f"**{tier}**", "", "| model | n | score ± 95% CI | acc. | accuse day | solver, same seeds | "
              "**score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | calls/ep | min/ep |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in tr:
            L.append(f"| {r['model']} {GEMMA_LABEL} | {r['n']} | {_f(r['mean'])} ± {_f(r['ci'], 2)} | "
                     f"{r['accuracy']:.2f} | {_f(r['accuse_day'], 1)} | {_f(r['solver_same_seeds'])} | "
                     f"**{_pct(r, 'ratio')}** | {_f(r['diff'])} ± {_f(r['diff_ci'], 2)} | {_pct(r, 'luck_adj_ratio')} | "
                     f"{_f(r['calls_per_ep'], 0)} | {_f(r['wall_min_per_ep'], 1)} |")
        L.append("")
    fps = sorted({t for r in g["rows"] for t in r["code_fingerprints"] if t})
    mv = sorted({t for r in g["rows"] for t in r["model_versions"]})
    shas = sorted({t for r in g["rows"] for t in r["launch_git_shas"] if t})
    L += [f"Gemma provenance: launch commits {', '.join(x[:10] for x in shas)}; code fingerprints {', '.join(fps)}; "
          f"API-served model versions {', '.join(mv) or '–'}.", ""]
    return L


def display_id(model: str) -> str:
    """The id a reader should see. gemini-3.5-flash is served as gemini-3.6-flash."""
    if model == "gemini-3.5-flash":
        return "gemini-3.6-flash (requested as 3.5-flash)"
    return model


def model_label(row: dict) -> str:
    """Request id, or the served model when the API substituted one."""
    requested = row["model"]
    served = row.get("model_versions") or []
    if requested == "gemini-3.5-flash" and (not served or "gemini-3.6-flash" in served):
        return display_id(requested)
    return requested


def headline_verb(a: dict, b: dict) -> str:
    """CI-gated wording: 'matches' needs both CIs to contain 100% AND both lower bounds >= 80%."""
    has = lambda x: x["ratio_lo"] == x["ratio_lo"]  # noqa: E731
    contains = all(has(x) and x["ratio_lo"] <= 1.0 <= x["ratio_hi"] for x in (a, b))
    if contains and all(x["ratio_lo"] >= 0.8 for x in (a, b)):
        return "matches the reference solver on hard"
    if contains:
        return "is not distinguishable from the reference solver on hard, but the CIs are wide"
    if all(x["ratio"] >= 0.8 for x in (a, b)):
        return "comes close to the reference solver on hard"
    return "reaches part of the reference solver's score on hard"


def _pc(r) -> str:
    if r["ratio"] != r["ratio"]:
        return "–"
    return f"{r['ratio']:.0%}" if r["ratio_lo"] != r["ratio_lo"] else f"{r['ratio']:.0%} [{r['ratio_lo']:.0%}, {r['ratio_hi']:.0%}]"


def headline(rows: list[dict], tags: dict) -> str:
    """Three findings, every number read from the rows/tags; wording is chosen by the CIs, never asserted."""
    R = {(r["model"], r["level"], r["tier"]): r for r in rows if not r["source"].startswith("import")}
    ns = [r["n"] for r in R.values()]
    out = [f"> **Headline findings** (auto-generated from the table below: {min(ns) if ns else 0}–{max(ns) if ns else 0} "
           "paired seeds per cell; 95% CIs are wide, so read them as directions)."]
    a, b = R.get(("gemini-3.5-flash", "medium", "hard")), R.get(("gemini-3.5-flash", "high", "hard"))
    if a and b:
        verb = headline_verb(a, b)
        k = sum(round(x["accuracy"] * x["n"]) for x in (a, b))
        c = R.get(("gemini-4-carbon", "high", "hard"))
        cost = f"${min(a['cost_per_ep'], b['cost_per_ep']):.2f}–{max(a['cost_per_ep'], b['cost_per_ep']):.2f} per episode"
        if c:
            cost += (f", versus ${c['cost_per_ep']:.2f} for gemini-4-carbon at high thinking ({_pc(c)}, n={c['n']}"
                     + ("" if c["n"] == a["n"] == b["n"] else "; different n, so the seed sets differ") + ")")
        out.append(f"> **gemini-3.5-flash (requested ID; the API serves gemini-3.6-flash) with medium or high thinking {verb}:** {_pc(a)} and {_pc(b)} of the solver "
                   f"on the same seeds (n={a['n']}, {b['n']}), {k}/{a['n'] + b['n']} correct accusations, {cost}.")
    lite = [r for (m, _, _), r in R.items() if m == "gemini-3.1-flash-lite"]
    if lite:
        neg = sum(r["mean"] < 0 for r in lite)
        mn = [r for r in lite if r["level"] == "minimal"]
        wrong = sum(round((1 - r["accuracy"]) * r["n"]) for r in mn if r["accused_rate"] == 1)
        tot = sum(r["n"] for r in mn)
        tail = f"; at minimal thinking it accused the wrong employee in {wrong}/{tot} episodes" if mn else ""
        verb = "fails at every thinking level" if neg == len(lite) else f"is below zero in {neg}/{len(lite)} cells"
        out.append(f"> **gemini-3.1-flash-lite {verb}:** its mean score is below the do-nothing score (0) in "
                   f"{neg}/{len(lite)} (level, tier) cells{tail}.")
    lo_m, hi_m = R.get(("gemini-3.8-flash", "low", "medium")), R.get(("gemini-3.8-flash", "high", "medium"))
    lo_h, hi_h = R.get(("gemini-3.8-flash", "low", "hard")), R.get(("gemini-3.8-flash", "high", "hard"))
    if lo_m and hi_m:
        s3 = (f"> **gemini-3.8-flash gains from thinking on medium** ({_pc(lo_m)} at low → {_pc(hi_m)} at high)"
              + (f" **but not on hard** ({_pc(lo_h)} → {_pc(hi_h)})" if lo_h and hi_h and hi_h["ratio"] <= lo_h["ratio"] + 0.1
                 else (f"; on hard {_pc(lo_h)} → {_pc(hi_h)}" if lo_h and hi_h else "")) + ".")
        P = (tags or {}).get("pooled") or {}
        d = []
        for tier in TIERS:
            lo, hi = P.get(f"low|{tier}"), P.get(f"high|{tier}")
            if lo and hi:
                g = lambda x, t: x["tags"].get(t, {}).get("regret_per_ep", 0.0)  # noqa: E731
                d.append((tier, g(hi, "premature_accusation") - g(lo, "premature_accusation"),
                          g(lo, "uninformative_canary"), g(hi, "uninformative_canary")))
        if d:
            s3 += (" Pooled over the flash models, low → high thinking changes premature-accusation regret by "
                   + ", ".join(f"{x[1]:+.2f}/episode on {x[0]}" for x in d)
                   + "; uninformative-canary regret goes " + ", ".join(f"{x[2]:.3f} → {x[3]:.3f} on {x[0]}" for x in d)
                   + " (thinking buys commit timing more than experiment design).")
        out.append(s3)
    return "\n>\n".join(out)


def _nan_to_none(x):
    if isinstance(x, float) and x != x:
        return None
    if isinstance(x, dict):
        return {k: _nan_to_none(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_nan_to_none(v) for v in x]
    return x


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.ladder_report", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", action="append", required=True,
                    help="ladder run dir(s) or exported jsonl.gz (repeatable or comma-separated)")
    ap.add_argument("--import-cell", action="append", default=[], help="<model>:<level>=<data/runs dir> (read-only)")
    ap.add_argument("--ledger", action="append", default=[])
    ap.add_argument("--probe", default=str(ROOT / "results" / "gemini" / "ladder_probe.json"))
    ap.add_argument("--out", default=str(ROOT / "results" / "gemini"))
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--no-tags", action="store_true")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--export", default=None, help="also write <dir>/ladder_episodes.jsonl.gz and ladder_ledger.jsonl.gz "
                    "(valid ladder episodes + feature=ladder ledger rows; --runs/--ledger can read them back)")
    ap.add_argument("--gemma-runs", default=None,
                    help="open-weight Gemma cells (hosted Gemma via the Gemini API; a ladder dir or exported "
                    "ladder_gemma_episodes.jsonl.gz), reported in their own section against the same solver seeds")
    ap.add_argument("--gemma-ledger", action="append", default=[])
    ap.add_argument("--headline", default=None,
                    help="hand-written findings block for the top of ladder.md (default: generated from the table)")
    a = ap.parse_args(argv)
    run_paths = _iter_run_paths(a.runs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    eps = load_ladder(run_paths)
    if a.export:
        import gzip
        ex = Path(a.export)
        ex.mkdir(parents=True, exist_ok=True)
        with gzip.open(ex / "ladder_episodes.jsonl.gz", "wt") as fh:
            for e in eps:
                fh.write(json.dumps({k: v for k, v in e.items() if k != "_cell"}, sort_keys=True) + "\n")
    for spec in a.import_cell:
        eps += load_import(spec)
    g_runs = Path(a.gemma_runs).expanduser() if a.gemma_runs else None
    g_eps = load_ladder(g_runs) if g_runs else []
    if a.export and g_runs:
        with gzip.open(ex / "ladder_gemma_episodes.jsonl.gz", "wt") as fh:
            for e in g_eps:
                fh.write(json.dumps({k: v for k, v in e.items() if k != "_cell"}, sort_keys=True) + "\n")
    pairs = {(e["_cell"]["tier"], e["_cell"]["seed"]) for e in eps + g_eps}
    ref = reference_episodes(pairs)
    solver = {(e["tier"], e["seed"]): e for e in ref if e["agent"] == "solver"}
    rows = cell_rows(eps, solver, B=a.bootstrap)
    ref_rows = reference_rows(ref, pairs)
    tags = {} if a.no_tags or not eps else tag_tables(eps)
    led = load_ledger(run_paths, a.ledger)
    if a.export:
        with gzip.open(Path(a.export) / "ladder_ledger.jsonl.gz", "wt") as fh:
            for r in led:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    run_ids = sorted({r.get("run_id", "") for r in led if r.get("run_id")})
    led_sum = {"calls": len(led), "errors": sum(not r.get("ok", True) for r in led), "run_ids": len(run_ids),
               "tokens_in": sum(r.get("in", 0) for r in led), "tokens_thinking": sum(r.get("thinking", 0) for r in led),
               "cost_usd_ledger": round(sum(r.get("cost_usd", 0) for r in led), 2),
               "cost_usd_priced": round(sum(price(r["model"], r.get("in", 0), r.get("out", 0) + r.get("thinking", 0),
                                                  r.get("cached", 0)) for r in led if r["model"] in PRICES), 2)}
    from canary.agents.runlog import git_sha
    probe = None
    if Path(a.probe).exists():
        probe = json.loads(Path(a.probe).read_text()).get("rows")
    runs_label = ", ".join(str(p).replace(str(Path.home()), "~") for p in run_paths)
    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": git_sha(), "runs": runs_label,
           "imports": [x.replace(str(Path.home()), "~") for x in a.import_cell], "ledger_run_ids": run_ids, "ledger": led_sum, "prices_usd_per_1m": PRICES,
           "episodes": len(eps), "headline_file": a.headline, "rows": rows, "reference": ref_rows, "tags": tags, "probe": probe, "figures": []}
    if g_runs:
        g_led = load_ledger(g_runs, a.gemma_ledger)
        if a.export:
            with gzip.open(Path(a.export) / "ladder_gemma_ledger.jsonl.gz", "wt") as fh:
                for r in g_led:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
        doc["gemma"] = {"runs": str(a.gemma_runs).replace(str(Path.home()), "~"), "episodes": len(g_eps),
                        "rows": cell_rows(g_eps, solver, B=a.bootstrap),
                        "ledger_run_ids": sorted({r.get("run_id", "") for r in g_led if r.get("run_id")}),
                        "ledger": {"calls": len(g_led), "errors": sum(not r.get("ok", True) for r in g_led),
                                   "cost_usd_ledger": round(sum(r.get("cost_usd", 0) for r in g_led), 2),
                                   "cost_unknown_calls": sum(bool(r.get("cost_unknown")) for r in g_led)}}
    doc["figures"] = [] if a.no_figures else \
        frontier(rows, (doc.get("gemma") or {}).get("rows"), out) + figures(rows, ref_rows, tags, out)
    clean = _nan_to_none(json.loads(json.dumps(doc, default=str)))
    (out / "ladder.json").write_text(json.dumps(clean, indent=1) + "\n")
    (out / "ladder.md").write_text(to_md(doc))
    print(to_md(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
