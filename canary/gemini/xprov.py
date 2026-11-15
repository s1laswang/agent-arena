"""Cross-provider control on identical worlds: committed GPT-5.5 episodes vs Gemini, Canary v1.3 rules.

The GPT-5.5 episodes were played on Sat 14 Nov under the v1.3 rules on public dev seeds and are committed with
their token usage. The Gemini episodes are played on the SAME (tier, seed) worlds under the frozen v1.3 rules:

    python scripts/with_tiers.py v1.3 -m canary.gemini.ladder --models ... --tiers hard,medium --seeds 0-10 --out DIR
    python scripts/with_tiers.py v1.3 -m canary.gemini.xprov --gemini-runs DIR [--out results/gemini]

Inputs
  data/runs/committed/v1.3/gpt-5.5-full        GPT-5.5, in-process LLMPolicy: the SAME harness as the Gemini ladder
  data/runs/committed/v1.3/codex-gpt-5.5-full  GPT-5.5 via the Codex CLI over MCP: a DIFFERENT harness (shown, labelled)
  data/runs/committed/v1.3/reference/solver-*  the reference solver on the same seeds (the pairing baseline)
  --gemini-runs                                canary.gemini.ladder output under with_tiers v1.3

Checks done in code (reported in xprov.json["checks"]): the Gemini and GPT episodes of a (tier, seed) saw the same
employee roster (same world); every Gemini episode replays to its recorded score; the solver replayed in-process
under v1.3 reproduces the committed reference scores. Cost = recorded token usage at list prices, cached input at
the cached price. This module makes no API calls.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "data" / "runs" / "committed" / "v1.3"
TIERS = ("hard", "medium")
GPT_SAME = "GPT-5.5 (in-process, effort medium)"
GPT_MCP = "GPT-5.5 (Codex CLI over MCP)"
SAME_HARNESS = "in-process LLMPolicy"
MCP_HARNESS = "Codex CLI over MCP"


# ----------------------------------------------------------------------------------------- loading
def _jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def openai_cost(model: str, usage: dict) -> float:
    """List-price USD for one committed episode's usage ({in, cached_in, out})."""
    if usage.get("cost_usd_est") is not None:  # recorded per episode by the measurement (same price table)
        return float(usage["cost_usd_est"])
    from canary.llm.pricing import cost
    tin, tout = int(usage.get("in") or 0), int(usage.get("out") or 0)
    cached = int(usage.get("cached_in") or usage.get("cached") or 0)
    c = cost(model, tin, tout, cached)
    return float(c.get("cost_usd_est", c.get("cost_usd", float("nan"))))


def roster(e: dict):
    for s in e.get("steps") or []:
        if s.get("tool") == "list_employees" and (s.get("result") or {}).get("ok"):
            return tuple(x.get("id") + "|" + str(x.get("name")) for x in s["result"]["data"]["employees"])
    return None


def load_committed(sub: str, label: str, harness: str, model: str = "gpt-5.5", root: Path = COMMITTED) -> list[dict]:
    out = []
    for tier in TIERS:
        d = root / sub / tier
        if not (d / "episodes.jsonl").exists():
            continue
        meta = json.loads((d / "meta.json").read_text())
        seen = set()
        for e in _jsonl(d / "episodes.jsonl"):
            em = e.get("meta") or {}
            if em.get("valid") is False or e.get("end_reason") == "error" or e["seed"] in seen:
                continue
            seen.add(e["seed"])
            out.append({"label": label, "provider": "openai", "model": model, "level": meta.get("reasoning_effort") or "default",
                        "harness": harness, "tier": tier, "seed": int(e["seed"]), "score": float(e["score"]),
                        "correct": bool(e.get("correct")), "accused": bool(e.get("accused")),
                        "final_day": e.get("final_day"), "cost_usd": openai_cost(model, em.get("usage") or {}),
                        "in_tok": (em.get("usage") or {}).get("in"),
                        "cached_tok": (em.get("usage") or {}).get("cached_in"),
                        "out_tok": (em.get("usage") or {}).get("out"), "roster": roster(e), "git_sha": meta.get("git_sha"), "source": str(d.relative_to(ROOT))})
    return out


def load_gemini(runs: list[str], expect_version: str | None = None) -> tuple[list[dict], dict]:
    from canary.gemini import ladder_report as lr
    eps = lr.load_ladder([Path(r).expanduser() for r in runs])
    out, versions = [], defaultdict(int)
    for e in eps:
        c = e["_cell"]
        versions[str(c.get("tiers_version"))] += 1
        out.append({"label": f"{lr.display_id(c['model'])} · thinking {c['level']}", "provider": "google",
                    "model": c["model"], "level": c["level"], "harness": SAME_HARNESS, "tier": c["tier"],
                    "seed": int(c["seed"]), "score": float(e["score"]), "correct": bool(e.get("correct")),
                    "accused": bool(e.get("accused")), "final_day": e.get("final_day"), "cost_usd": c.get("cost_usd"),
                    "in_tok": c.get("in"), "cached_tok": c.get("cached"),
                    "out_tok": (c.get("out") or 0) + (c.get("thinking") or 0), "roster": roster(e), "git_sha": c.get("launch_git_sha"), "run_id": c.get("run_id"),
                    "thinking": c.get("thinking"), "calls": c.get("calls"), "wall_s": c.get("wall_s"),
                    "model_versions": c.get("model_versions") or [], "_episode": e})
    if expect_version and set(versions) - {expect_version}:
        raise SystemExit(f"Gemini runs are not all {expect_version}: {dict(versions)} (run the ladder under with_tiers)")
    return out, dict(versions)


def committed_solver(root: Path = COMMITTED) -> dict[tuple[str, int], float]:
    out = {}
    for tier in TIERS:
        for d in sorted((root / "reference").glob(f"solver-{tier}-*")):
            for e in _jsonl(d / "episodes.jsonl"):
                out.setdefault((tier, int(e["seed"])), float(e["score"]))
    return out


# ----------------------------------------------------------------------------------------- stats
def mean(xs):
    xs = [x for x in xs if x is not None and x == x]
    return sum(xs) / len(xs) if xs else float("nan")


def boot_ratio(f: list[float], s: list[float], B: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
    """Paired bootstrap CI of mean(f)/mean(s) (same resampling as scripts/paired_v13.boot_ratio)."""
    rng, n, vals = random.Random(rng_seed), len(f), []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(s[i] for i in idx) / n
        if ms > 0:
            vals.append(sum(f[i] for i in idx) / n / ms)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if vals else (float("nan"), float("nan"))


def boot_diff(a: list[float], b: list[float], B: int = 10000, rng_seed: int = 0) -> tuple[float, float, float]:
    """Paired bootstrap of mean(a - b): (mean, lo, hi)."""
    d = [x - y for x, y in zip(a, b)]
    if not d:
        return float("nan"), float("nan"), float("nan")
    rng, n, vals = random.Random(rng_seed), len(d), []
    for _ in range(B):
        vals.append(sum(d[rng.randrange(n)] for _ in range(n)) / n)
    vals.sort()
    return sum(d) / n, vals[int(0.025 * B)], vals[int(0.975 * B) - 1]


def summarize(eps: list[dict], solver: dict[tuple[str, int], float], B: int = 10000) -> list[dict]:
    """One row per (label, tier): score, accuracy, % of the solver on the same seeds (paired bootstrap), $/episode."""
    groups = defaultdict(list)
    for e in eps:
        groups[(e["label"], e["tier"])].append(e)
    rows = []
    for (label, tier), es in groups.items():
        es.sort(key=lambda e: e["seed"])
        paired = [e for e in es if (tier, e["seed"]) in solver]
        f = [e["score"] for e in paired]
        s = [solver[(tier, e["seed"])] for e in paired]
        ms = mean(s)
        lo, hi = boot_ratio(f, s, B) if len(f) > 1 and ms > 0 else (float("nan"), float("nan"))
        e0 = es[0]
        rows.append({"label": label, "provider": e0["provider"], "model": e0["model"], "level": e0["level"],
                     "harness": e0["harness"], "tier": tier, "n": len(es), "seeds": [e["seed"] for e in es],
                     "score_mean": mean([e["score"] for e in es]),
                     "accuracy": sum(e["correct"] for e in es) / len(es), "correct": sum(e["correct"] for e in es),
                     "accused": sum(e["accused"] for e in es), "solver_same_seeds": ms,
                     "pct_solver": (mean(f) / ms) if f and ms > 0 else float("nan"), "pct_lo": lo, "pct_hi": hi,
                     "cost_per_ep": mean([e.get("cost_usd") for e in es]),
                     "in_per_ep": mean([e.get("in_tok") for e in es]),
                     "cached_share": (sum(e.get("cached_tok") or 0 for e in es) / sum(e.get("in_tok") or 0 for e in es))
                     if sum(e.get("in_tok") or 0 for e in es) else float("nan"),
                     "out_per_ep": mean([e.get("out_tok") for e in es]),
                     "thinking_per_ep": mean([e.get("thinking") for e in es]),
                     "wall_min_per_ep": mean([e.get("wall_s") for e in es]) / 60,
                     "model_versions": sorted({v for e in es for v in e.get("model_versions") or []}),
                     "git_shas": sorted({str(e.get("git_sha"))[:10] for e in es if e.get("git_sha")}),
                     "run_ids": sorted({e["run_id"] for e in es if e.get("run_id")})})
    order = {GPT_SAME: 0, GPT_MCP: 1}
    return sorted(rows, key=lambda r: (TIERS.index(r["tier"]), order.get(r["label"], 2), r["label"]))


def versus(eps: list[dict], base_label: str, B: int = 10000) -> list[dict]:
    """Each non-base agent vs the base agent on the seeds both played: paired score difference and cost ratio."""
    by = defaultdict(dict)
    for e in eps:
        by[(e["label"], e["tier"])][e["seed"]] = e
    out = []
    for (label, tier), mine in by.items():
        base = by.get((base_label, tier))
        if label == base_label or not base:
            continue
        shared = sorted(set(mine) & set(base))
        if len(shared) < 2:
            continue
        a = [mine[s]["score"] for s in shared]
        b = [base[s]["score"] for s in shared]
        d, lo, hi = boot_diff(a, b, B)
        ca, cb = mean([mine[s].get("cost_usd") for s in shared]), mean([base[s].get("cost_usd") for s in shared])
        verdict = "higher" if lo > 0 else "lower" if hi < 0 else "not distinguishable"
        out.append({"label": label, "tier": tier, "level": mine[shared[0]].get("level"), "model": mine[shared[0]].get("model"),
                    "base": base_label, "shared_seeds": shared, "n": len(shared),
                    "score": mean(a), "base_score": mean(b), "diff": d, "diff_lo": lo, "diff_hi": hi, "verdict": verdict,
                    "correct": sum(mine[s]["correct"] for s in shared), "base_correct": sum(base[s]["correct"] for s in shared),
                    "cost_per_ep": ca, "base_cost_per_ep": cb, "base_cost_ratio": (cb / ca) if ca and ca == ca and ca > 0 else float("nan")})
    return sorted(out, key=lambda r: (TIERS.index(r["tier"]), r["label"]))


MIN_SHARED = 5   # a comparison needs at least this many shared seeds to appear in the headline
MIN_ROW_N = 5    # cells with fewer episodes are listed as incomplete, not tabulated or plotted
MATCHED_LEVEL = "medium"   # GPT-5.5 ran at reasoning effort medium


def headline(vs: list[dict], tier: str = "hard", level: str = MATCHED_LEVEL) -> str:
    """CI-gated sentence for a PRE-SPECIFIED comparison, so nothing is selected on the outcome: every Gemini model
    at the matched setting (thinking `level`) against GPT-5.5 in the same harness on `tier`, for cells with at
    least MIN_SHARED shared seeds. The verdict of each clause comes from the paired bootstrap."""
    cand = sorted([v for v in vs if v["tier"] == tier and v.get("level") == level and v["n"] >= MIN_SHARED],
                  key=lambda v: v["label"])
    if not cand:
        return ""
    rel = {"higher": "scores higher", "lower": "scores lower", "not distinguishable": "is not distinguishable"}
    parts = []
    for v in cand:
        cost = ""
        if v["base_cost_ratio"] == v["base_cost_ratio"]:
            r = v["base_cost_ratio"]
            cost = (f", ${v['cost_per_ep']:.2f} vs ${v['base_cost_per_ep']:.2f} per episode"
                    + (f" ({r:.1f}x cheaper)" if r >= 1 else f" ({1 / r:.1f}x dearer)"))
        parts.append(f"{v['label'].split(' · ')[0]} {rel[v['verdict']]} (mean score {v['score']:+.2f} vs {v['base_score']:+.2f}, "
                     f"paired difference {v['diff']:+.2f} [{v['diff_lo']:+.2f}, {v['diff_hi']:+.2f}], n={v['n']} shared seeds, "
                     f"{v['correct']}/{v['n']} vs {v['base_correct']}/{v['n']} correct{cost})")
    return (f"On identical Canary v1.3 {tier} worlds, in the same harness and at matched {level} effort, against GPT-5.5: "
            + "; ".join(parts) + ".")


# ----------------------------------------------------------------------------------------- checks
def check_same_world(eps: list[dict]) -> dict:
    ref, same, diff, missing = {}, 0, [], 0
    for e in eps:
        if e["provider"] == "openai" and e.get("roster"):
            ref.setdefault((e["tier"], e["seed"]), e["roster"])
    for e in eps:
        if e["provider"] != "google":
            continue
        r0 = ref.get((e["tier"], e["seed"]))
        if r0 is None or e.get("roster") is None:
            missing += 1
        elif r0 == e["roster"]:
            same += 1
        else:
            diff.append([e["label"], e["tier"], e["seed"]])
    return {"same_roster": same, "different_roster": diff, "not_comparable": missing}


def check_replay(gem: list[dict]) -> dict:
    sd = str(ROOT / "scripts")
    if sd not in sys.path:
        sys.path.insert(0, sd)
    import verify_replay
    ok, bad = 0, []
    for e in gem:
        try:
            r = verify_replay.replay_episode(e["_episode"])
            if abs(r["score"] - e["score"]) < 1e-9:
                ok += 1
            else:
                bad.append([e["label"], e["tier"], e["seed"], e["score"], r["score"]])
        except Exception as ex:  # noqa: BLE001
            bad.append([e["label"], e["tier"], e["seed"], f"{type(ex).__name__}: {ex}"[:120]])
    return {"replay_verified": ok, "n": len(gem), "failed": bad}


def check_solver(solver: dict[tuple[str, int], float], pairs: set[tuple[str, int]]) -> dict:
    from canary.eval import make_env, make_policy_factory, run_episode
    fac = make_policy_factory("solver")
    same, diff = 0, []
    for tier, seed in sorted(pairs):
        if (tier, seed) not in solver:
            continue
        r = run_episode(make_env(tier, seed), fac(seed))
        if abs(r.score - solver[(tier, seed)]) < 1e-9:
            same += 1
        else:
            diff.append([tier, seed, solver[(tier, seed)], r.score])
    return {"reproduced": same, "n": same + len(diff), "different": diff}


# ----------------------------------------------------------------------------------------- output
def _pct(x):
    return "–" if x != x else f"{100 * x:.0f}%"


def _tok(x):
    return "–" if x is None or x != x else (f"{x / 1e6:.2f}M" if x >= 1e6 else f"{x / 1e3:.0f}k")


def _money(x):
    return "–" if x is None or x != x else f"${x:.2f}"


def _short_label(r: dict) -> str:
    if r["provider"] == "google":
        m = r["label"].split(" (")[0].split(" · ")[0].replace("gemini-", "")
        return f"{m} · {r['level']}"
    return "GPT-5.5 · same harness" if r["harness"] == SAME_HARNESS else "GPT-5.5 · Codex over MCP"


def figure(rows: list[dict], out: Path) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    tiers = [t for t in TIERS if any(r["tier"] == t for r in rows)]
    fig, axes = plt.subplots(1, len(tiers), figsize=(7.6 * len(tiers), 5.0), squeeze=False)
    for ax, tier in zip(axes[0], tiers):
        pts = [r for r in rows if r["tier"] == tier and r["n"] >= MIN_ROW_N
               and r["cost_per_ep"] == r["cost_per_ep"] and r["pct_solver"] == r["pct_solver"]]
        pts.sort(key=lambda r: r["cost_per_ep"])
        for k, r in enumerate(pts):
            google = r["provider"] == "google"
            color = "#1a73e8" if google else "#333333"
            marker = "o" if google else ("s" if r["harness"] == SAME_HARNESS else "D")
            face = color if (google or r["harness"] == SAME_HARNESS) else "none"
            y, lo, hi = 100 * r["pct_solver"], 100 * r["pct_lo"], 100 * r["pct_hi"]
            if lo == lo and hi == hi:
                ax.plot([r["cost_per_ep"]] * 2, [lo, hi], color=color, lw=1.3, alpha=0.55)
            ax.scatter([r["cost_per_ep"]], [y], s=80, marker=marker, facecolors=face, edgecolors=color, zorder=3)
            dy = 12 if k % 2 == 0 else -20                     # alternate above/below so neighbours do not collide
            right = k >= len(pts) - 2                          # the two dearest points: label to the left
            ax.annotate(f"{_short_label(r)}  (n={r['n']})", (r["cost_per_ep"], y), textcoords="offset points",
                        xytext=(-7 if right else 7, dy), ha="right" if right else "left", fontsize=8.5, color=color)
        ax.axhline(100, color="#999999", lw=1, ls="--")
        ax.text(0.99, 100, " reference solver", transform=ax.get_yaxis_transform(), ha="right", va="bottom",
                fontsize=7.5, color="#777777")
        ax.set_xscale("log")
        ticks = [t for t in (0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0) if pts and pts[0]["cost_per_ep"] * 0.8 <= t <= pts[-1]["cost_per_ep"] * 1.25]
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"${t:g}" for t in ticks])
        ax.minorticks_off()
        if pts:
            ax.set_xlim(pts[0]["cost_per_ep"] * 0.8, pts[-1]["cost_per_ep"] * 1.25)
        ax.set_xlabel("USD per episode (list price, log scale)")
        ax.set_ylabel("% of the reference solver on the same seeds (95% CI)")
        ax.set_title(f"Canary v1.3 {tier}: identical worlds, Gemini vs GPT-5.5", fontsize=10.5)
        ax.grid(alpha=0.25)
    fig.text(0.01, 0.01, "Circles: Gemini, same in-process harness. Filled square: GPT-5.5, same harness, effort medium. "
                         "Hollow diamond: GPT-5.5 via Codex CLI over MCP (a different harness).", fontsize=7.5, color="#555555")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    p = out / "xprov.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    return p.name


def to_md(doc: dict) -> str:
    L = ["# Cross-provider control: Gemini vs GPT-5.5 on identical Canary worlds (v1.3 rules)", "",
         f"*Generated {doc['generated_at']} at `{doc['git_sha'][:10]}`. No API calls: committed GPT-5.5 episodes "
         f"(Sat 14 Nov, `{doc['inputs']['gpt_git_sha']}`) and Gemini episodes played under the frozen v1.3 rules "
         "(`scripts/with_tiers.py v1.3`) on the same public dev seeds.*", ""]
    if doc.get("headline"):
        L += [f"> **{doc['headline']}**", ""]
    L += ["![Same worlds: % of the solver vs cost per episode](xprov.png)", "",
          "## What is compared", "",
          "- **Same worlds.** Canary v1.3 rules (hard = 30 staff, 14 days, 1 canary a day), public dev seeds. "
          f"World identity check: {doc['checks']['same_world']['same_roster']} Gemini episodes saw exactly the employee "
          f"roster the GPT-5.5 episode of the same (tier, seed) saw; {len(doc['checks']['same_world']['different_roster'])} differ.",
          f"- **Same harness for the headline.** `{GPT_SAME}` and every Gemini row use the same in-process `LLMPolicy` "
          "(full history, same instructions and 13 tools). GPT-5.5 ran at reasoning effort medium; Gemini is shown at "
          "thinking medium (matched) and high.",
          f"- **Different harness, shown for completeness.** `{GPT_MCP}` is the judges' harness shape; it is not "
          "comparable one-to-one with the in-process rows.",
          "- **Pairing.** % of solver = mean agent score / mean reference-solver score on the same seeds "
          "(committed v1.3 reference), 95% paired bootstrap CI.",
          "- **Cost.** Computed from the token usage each API call reported (input, cached input, output including "
          "reasoning/thinking tokens), priced at list prices with cached input at the cached price. GPT-5.5: $5 / $0.50 "
          "cached / $30 per 1M tokens (`canary/llm/pricing.py`; the per-episode figure recorded with the run). Gemini: "
          "the ladder's price table (`canary/gemini/ladder_report.py`). Token counts per episode are in the tables.",
          "- **Effort.** GPT-5.5 ran at its default reasoning effort (medium). Gemini rows show thinking level medium "
          "(the matched setting) and high. The two dials are not the same mechanism; treat 'medium vs medium' as nominal.",
          f"- **Checks.** Replay: {doc['checks']['replay']['replay_verified']}/{doc['checks']['replay']['n']} Gemini episodes "
          f"replay to their recorded score. Solver: {doc['checks']['solver']['reproduced']}/{doc['checks']['solver']['n']} "
          "committed reference scores reproduce in-process under v1.3.", ""]
    for tier in TIERS:
        all_rows = [r for r in doc["rows"] if r["tier"] == tier]
        rows = [r for r in all_rows if r["n"] >= MIN_ROW_N]
        small = [r for r in all_rows if r["n"] < MIN_ROW_N]
        if not rows:
            continue
        L += [f"## {tier}", "",
              "| agent | harness | n | mean score | correct | % of solver [95% CI] | $/episode | input tok/ep (cached) | output tok/ep |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['label']} | {r['harness']} | {r['n']} | {r['score_mean']:+.3f} | {r['correct']}/{r['n']} | "
                     f"**{_pct(r['pct_solver'])}** [{_pct(r['pct_lo'])}, {_pct(r['pct_hi'])}] | {_money(r['cost_per_ep'])} | "
                     f"{_tok(r['in_per_ep'])} ({_pct(r['cached_share'])}) | {_tok(r['out_per_ep'])} |")
        if small:
            L += ["", "Incomplete cells (fewer than " + str(MIN_ROW_N) + " episodes; not tabulated or plotted): "
                  + "; ".join(f"{r['label']} n={r['n']} (mean score {r['score_mean']:+.2f})" for r in small) + "."]
        vs = [v for v in doc["versus"] if v["tier"] == tier and v["n"] >= MIN_ROW_N]
        if vs:
            L += ["", f"Paired against `{GPT_SAME}` on the seeds both played:", "",
                  "| Gemini agent | shared seeds | score vs GPT-5.5 | paired difference [95% CI] | verdict | cost vs GPT-5.5 |",
                  "|---|---|---|---|---|---|"]
            for v in vs:
                ratio = f"{v['base_cost_ratio']:.1f}x cheaper" if v["base_cost_ratio"] == v["base_cost_ratio"] and v["base_cost_ratio"] >= 1 else \
                    (f"{1 / v['base_cost_ratio']:.1f}x dearer" if v["base_cost_ratio"] == v["base_cost_ratio"] and v["base_cost_ratio"] > 0 else "–")
                L.append(f"| {v['label']} | {v['n']} | {v['score']:+.2f} vs {v['base_score']:+.2f} | {v['diff']:+.2f} "
                         f"[{v['diff_lo']:+.2f}, {v['diff_hi']:+.2f}] | {v['verdict']} | {_money(v['cost_per_ep'])} vs "
                         f"{_money(v['base_cost_per_ep'])} ({ratio}) |")
        L.append("")
    L += ["## Limits", "",
          "- Small n (8 to 11 seeds per row): the intervals are wide, and a wrong accusation scores -1, so one episode moves a mean a lot.",
          "- v1.3 is the earlier rule set (the judged AfterQuery tier is v1.4). It is used here because it is the only rule "
          "set with committed GPT-5.5 episodes; this is a control for the Gemini entry, not an AfterQuery claim.",
          "- One non-Gemini frontier model, one day of its API behaviour, default reasoning effort. No Anthropic model was run.",
          "- The GPT-5.5 and Gemini episodes were played about a day apart at different commits; the env is identical "
          "(roster and replay checks above), the policy code may differ in small ways.", ""]
    return "\n".join(L)


def _clean(x):
    if isinstance(x, float) and x != x:
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def build(gemini_runs: list[str], B: int = 10000, checks: bool = True) -> dict:
    from canary import rules
    gpt = load_committed("gpt-5.5-full", GPT_SAME, SAME_HARNESS) + load_committed("codex-gpt-5.5-full", GPT_MCP, MCP_HARNESS)
    gem, versions = load_gemini(gemini_runs, expect_version="v1.3")
    solver = committed_solver()
    eps = gpt + gem
    rows = summarize(eps, solver, B)
    vs = versus([e for e in eps if e["harness"] == SAME_HARNESS], GPT_SAME, B)
    pairs = {(e["tier"], e["seed"]) for e in eps}
    chk = {"same_world": check_same_world(eps),
           "replay": check_replay(gem) if checks else {"replay_verified": 0, "n": len(gem), "failed": [], "skipped": True},
           "solver": check_solver(solver, pairs) if checks else {"reproduced": 0, "n": 0, "different": [], "skipped": True},
           "rules_version_in_process": rules.TIERS_VERSION, "gemini_tiers_versions": versions}
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": _git_sha(),
            "inputs": {"gpt_same_harness": "data/runs/committed/v1.3/gpt-5.5-full",
                       "gpt_mcp": "data/runs/committed/v1.3/codex-gpt-5.5-full",
                       "solver": "data/runs/committed/v1.3/reference/solver-*",
                       "gpt_git_sha": sorted({str(e.get("git_sha"))[:10] for e in gpt if e.get("git_sha")})[0] if gpt else "",
                       "gemini_runs": [str(r) for r in gemini_runs]},
            "headline": headline(vs, "hard"), "headline_medium": headline(vs, "medium"),
            "rows": rows, "versus": vs, "checks": chk,
            "ledger_run_ids": sorted({e["run_id"] for e in gem if e.get("run_id")}),
            "episodes": {"gpt": len(gpt), "gemini": len(gem)}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gemini-runs", action="append", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "gemini"))
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--no-checks", action="store_true")
    ap.add_argument("--export", action="store_true", help="also write xprov_episodes.jsonl.gz (keyless rebuild input)")
    a = ap.parse_args(argv)
    from canary import rules
    if rules.TIERS_VERSION != "v1.3":
        raise SystemExit("run under the frozen rules: python scripts/with_tiers.py v1.3 -m canary.gemini.xprov ...")
    doc = build(a.gemini_runs, a.bootstrap, checks=not a.no_checks)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    doc["figure"] = figure(doc["rows"], out)
    if a.export:  # keyless rebuild inputs: the Gemini episodes and their ledger rows (counts only, no prompts)
        import gzip
        from canary.gemini import ladder_report as lr
        runs = [Path(r).expanduser() for r in a.gemini_runs]
        with gzip.open(out / "xprov_episodes.jsonl.gz", "wt") as fh:
            for e in lr.load_ladder(runs):
                fh.write(json.dumps({k: v for k, v in e.items() if k != "_cell"}, sort_keys=True) + "\n")
        with gzip.open(out / "xprov_ledger.jsonl.gz", "wt") as fh:
            for r in lr.load_ledger(runs, []):
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    (out / "xprov.json").write_text(json.dumps(_clean(doc), indent=1) + "\n")
    (out / "xprov.md").write_text(to_md(doc))
    print(doc["headline"] or "(no same-harness comparison yet)")
    print(f"rows={len(doc['rows'])} gemini={doc['episodes']['gemini']} gpt={doc['episodes']['gpt']} checks={json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if not isinstance(vv, list)}) for k, v in doc['checks'].items()})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
