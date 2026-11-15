"""Three measured ablations for the "why Gemini is essential" section. Reads only committed files; no API calls.

    uv run python -m canary.gemini.ablations          -> results/gemini/ablations.{json,md}

1. Thought-signature replay OFF vs ON (gemini-3.8-flash, thinking medium, hard tier, dev seeds 0-9).
   ON  = the committed ladder cell (results/gemini/ladder.json + ladder_episodes/ladder_ledger).
   OFF = results/gemini/ablations_sig_off/ (ladder run with --no-thought-signatures).
2. Explicit context cache: USD paid vs the counterfactual with cached tokens billed at the full input price.
3. Thinking-level sweep table from results/gemini/ladder.json.
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import time
from pathlib import Path

from canary.llm.pricing import cost

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results" / "gemini"
GALLERY_RUNS = ("atlas-20261114-185646", "atlas-20261114-185807", "atlas-20261114-185951")  # gallery_cache run_ids
SIG_CELL = ("gemini-3.8-flash", "medium", "hard")


def _jsonl(p: Path) -> list[dict]:
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def mean_ci(xs: list[float]) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "ci95": None}
    m = statistics.fmean(xs)
    h = 1.96 * statistics.stdev(xs) / math.sqrt(n) if n > 1 else float("nan")
    return {"n": n, "mean": round(m, 4), "ci95": [round(m - h, 4), round(m + h, 4)]}


def _ledger_rows() -> list[dict]:
    """All committed ledgers, de-duplicated (the ladder ledger overlaps the usage ledger)."""
    seen, out = set(), []
    for p in sorted(RES.glob("*ledger*.jsonl.gz")):
        for r in _jsonl(p):
            k = (r.get("ts"), r.get("pid"), r.get("host"), r.get("run_id"), r.get("model"), r.get("in"), r.get("out"))
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


# --------------------------------------------------------------------------- 1. thought signatures
def sig_ablation(ledger: list[dict]) -> dict:
    lad = json.loads((RES / "ladder.json").read_text())
    row = next(r for r in lad["rows"] if (r["model"], r["level"], r["tier"]) == SIG_CELL)
    run_ids = set(row["run_ids"])
    eps = [e for e in _jsonl(RES / "ladder_episodes.jsonl.gz") if e["meta"]["ladder"]["run_id"] in run_ids]
    calls = [r for r in ledger if r.get("run_id") in run_ids and r.get("kind", "generate") == "generate"]
    api_err = sum(1 for r in calls if not r.get("ok", True))
    bad = []
    for e in eps:
        bad.append(sum(1 for s in e["steps"] if (s.get("result") or {}).get("error") in ("invalid arguments", "unknown tool")))
    n_steps = sum(len(e["steps"]) for e in eps)
    correct = sum(1 for e in eps if e.get("correct"))
    on = {"source": "results/gemini/ladder.json row + ladder_episodes.jsonl.gz + ladder_ledger.jsonl.gz",
          "valid_episodes": len(eps), "seeds": sorted(e["seed"] for e in eps),
          "api_calls": len(calls), "api_errors": api_err, "api_error_rate": round(api_err / max(1, len(calls)), 4),
          "api_error_rate_ci95": wilson(api_err, len(calls)),
          "invalid_tool_calls": sum(bad), "tool_calls": n_steps,
          "invalid_tool_call_rate": round(sum(bad) / max(1, n_steps), 4),
          "invalid_tool_call_rate_ci95": wilson(sum(bad), n_steps),
          "invalid_tool_calls_per_episode": mean_ci([float(b) for b in bad]),
          "accuracy": round(correct / len(eps), 4), "accuracy_ci95": wilson(correct, len(eps)),
          "score": mean_ci([float(e["score"]) for e in eps]),
          "pct_of_solver_same_seeds": round(row["ratio"], 4), "pct_of_solver_ci95": [round(row["ratio_lo"], 4),
                                                                                    round(row["ratio_hi"], 4)],
          "solver_same_seeds_mean": row["solver_same_seeds"]}
    d = RES / "ablations_sig_off"
    off_calls = _jsonl(d / "ledger.jsonl.gz")
    prog = _jsonl(d / "progress.jsonl")
    rej = [r for r in off_calls if not r["ok"]]
    seeds_rej = sorted({r["meta"]["seed"] for r in rej})
    off = {"source": "results/gemini/ablations_sig_off/ (ladder --no-thought-signatures, run ablation-sig-off)",
           "episodes_attempted": len(prog), "valid_episodes": sum(1 for p in prog if not p.get("infra_invalid")),
           "infra_invalid_episodes": sum(1 for p in prog if p.get("infra_invalid")),
           "api_calls": len(off_calls), "api_errors": len(rej),
           "api_error_rate": round(len(rej) / max(1, len(off_calls)), 4),
           "api_error_rate_ci95": wilson(len(rej), len(off_calls)),
           "first_call_ok": sum(1 for r in off_calls if r["ok"]),
           "second_call_rejected_seeds": seeds_rej,
           "rejection_rate_of_function_call_turns": round(len(seeds_rej) / max(1, len(prog)), 4),
           "rejection_rate_ci95": wilson(len(seeds_rej), len(prog)),
           "error_class": "google.genai.errors.ClientError 400 INVALID_ARGUMENT",
           "error_message": ("Function call is missing a thought_signature in functionCall parts. This is required "
                             "for tools to work correctly, and missing thought_signature may lead to degraded model "
                             "performance. Additional data, function call `default_api:status` , position 2. Please "
                             "refer to https://aistudio.google.com/docs/thought-signatures for more details."),
           "invalid_tool_calls": None, "accuracy": None, "score": None, "pct_of_solver_same_seeds": None,
           "note": ("No episode gets past its first tool result: the 2nd request (the 1st that replays a model "
                    "function_call) is rejected on every seed, so accuracy/score/% of solver are undefined (not 0). "
                    "Infra-invalid, never scored. The arm was stopped after the first attempt of all 10 seeds.")}
    return {"cell": dict(zip(("model", "thinking_level", "tier"), SIG_CELL)), "on": on, "off": off}


# --------------------------------------------------------------------------- 2. explicit cache
def _cost_pair(rows: list[dict]) -> dict:
    paid = cf = 0.0
    cached = tin = 0
    for r in rows:
        tout = (r.get("out") or 0) + (r.get("thinking") or 0)
        c = cost(r["model"], r.get("in") or 0, tout, r.get("cached") or 0)
        mult = 0.5 if r.get("kind") == "batch" else 1.0
        paid += c.get("cost_usd_est", c["cost_usd"]) * mult
        cf += c["cost_usd"] * mult
        cached += r.get("cached") or 0
        tin += r.get("in") or 0
    return {"calls": len(rows), "input_tokens": tin, "cached_tokens": cached,
            "cached_share": round(cached / tin, 4) if tin else None,
            "usd_paid": round(paid, 2), "usd_if_uncached": round(cf, 2), "usd_saved": round(cf - paid, 2),
            "pct_saved": round(100 * (cf - paid) / cf, 1) if cf else None}


def cache_ablation(ledger: list[dict]) -> dict:
    atlas = [r for r in ledger if r.get("feature") == "atlas"]
    gallery = [r for r in atlas if r.get("run_id") in GALLERY_RUNS]
    atlas_only = [r for r in atlas if r.get("run_id") not in GALLERY_RUNS]
    by_feat: dict[str, list[dict]] = {}
    for r in ledger:
        by_feat.setdefault(r.get("feature") or "?", []).append(r)
    return {"method": ("Per ledger row: paid = canary.llm.pricing.cost(...)['cost_usd_est'] (cached tokens at "
                       "CACHED_PRICES; models without an entry use 10% of input); counterfactual = 'cost_usd' (all "
                       "input at the full price). Batch rows at 50%. Explicit-cache storage (per token-hour) is not "
                       "in the ledger and is not included. Gallery = the atlas-feature runs whose run_id the "
                       "gallery_cache records."),
            "atlas": _cost_pair(atlas_only), "gallery": _cost_pair(gallery),
            "atlas_plus_gallery": _cost_pair(atlas),
            "programme": _cost_pair(ledger),
            "by_feature": {k: _cost_pair(v) for k, v in sorted(by_feat.items())}}


# --------------------------------------------------------------------------- 3. thinking sweep
def sweep(ladder_json: Path | None = None) -> list[dict]:
    lad = json.loads((ladder_json or RES / "ladder.json").read_text())
    out = []
    for r in lad["rows"]:
        if r["tier"] not in ("hard", "medium"):
            continue
        lo, hi = r["ratio_lo"], r["ratio_hi"]
        out.append({"model": r["model"], "level": r["level"], "tier": r["tier"], "n": r["n"],
                    "pct_of_solver": round(100 * r["ratio"]), "ci95": [round(100 * lo), round(100 * hi)],
                    "ci_excludes_100": hi < 1 or lo > 1,
                    "ci_direction": "below" if hi < 1 else "above" if lo > 1 else None,
                    "thinking_tokens_per_ep": round(r["thinking_per_ep"]),
                    "thinking_is_estimate": r.get("thinking_is_estimate", False),
                    "usd_per_ep": round(r["cost_per_ep"], 3)})
    return out


def parity_sentence(sw: list[dict]) -> str:
    """'k of N cells exclude parity, all below the solver' (direction stated, never implied)."""
    below = sum(1 for r in sw if r["ci_direction"] == "below")
    above = sum(1 for r in sw if r["ci_direction"] == "above")
    k = below + above
    tail = ("all below the solver" if k and not above else "all above the solver" if k and not below
            else f"{below} below and {above} above the solver" if k else "none differ from the solver")
    return f"{k} of {len(sw)} cells exclude parity, {tail}"


def _model(m: str) -> str:
    from canary.gemini.ladder_report import display_id
    return display_id(m)


# --------------------------------------------------------------------------- report
def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _ci(c):
    return f"[{100 * c[0]:.1f}, {100 * c[1]:.1f}]"


def render_md(a: dict) -> str:
    s, c, sw = a["thought_signatures"], a["explicit_cache"], a["thinking_sweep"]
    on, off = s["on"], s["off"]
    ag, pg = c["atlas_plus_gallery"], c["programme"]
    L = [f"# Gemini ablations (generated {a['generated_at']} by `python -m canary.gemini.ablations`)", "",
         "All numbers come from committed files under results/gemini/. 95% CIs: Wilson for rates, t-normal for means, "
         "paired bootstrap from ladder.json for % of solver.", "",
         "## 1. Thought-signature replay: OFF vs ON",
         f"gemini-3.8-flash, thinking_level medium, hard tier, dev seeds 0-9. OFF strips `provider_items` (the "
         f"model's own Content, signatures included) from every assistant turn before each call "
         f"(`LedgeredClient(drop_signatures=True)`, `ladder --no-thought-signatures`). With signatures ON the agent "
         f"plays all {on['valid_episodes']} episodes: {on['api_errors']}/{on['api_calls']} API errors "
         f"({_pct(on['api_error_rate'])}, CI {_ci(on['api_error_rate_ci95'])}), "
         f"{on['invalid_tool_calls']}/{on['tool_calls']} invalid tool calls ({_pct(on['invalid_tool_call_rate'])}, "
         f"CI {_ci(on['invalid_tool_call_rate_ci95'])}), accuracy {_pct(on['accuracy'])} (CI "
         f"{_ci(on['accuracy_ci95'])}), mean score {on['score']['mean']:.3f} (CI {on['score']['ci95'][0]:.2f} to "
         f"{on['score']['ci95'][1]:.2f}), {100 * on['pct_of_solver_same_seeds']:.0f}% of the solver on the same "
         f"seeds (CI {_ci(on['pct_of_solver_ci95'])}). With signatures OFF the API rejects the first request that "
         f"replays a model function call on {len(off['second_call_rejected_seeds'])}/{off['episodes_attempted']} "
         f"seeds (Wilson CI {_ci(off['rejection_rate_ci95'])}): `{off['error_class']}`: \"{off['error_message']}\" "
         f"{off['api_errors']}/{off['api_calls']} calls failed (every first call succeeded, every second call was "
         f"rejected), so {off['valid_episodes']} episodes are playable and accuracy, score and % of solver are "
         f"undefined, not zero. All {off['infra_invalid_episodes']} OFF episodes are infra-invalid and unscored. "
         "The finding: on Gemini 3.x, multi-turn function calling does not work at all without thought-signature "
         "replay; it is a hard requirement of the API, not an optimisation.", "",
         "| arm | valid eps | API errors | invalid tool calls | accuracy | mean score | % of solver |",
         "|---|---|---|---|---|---|---|",
         f"| ON | {on['valid_episodes']} | {on['api_errors']}/{on['api_calls']} {_ci(on['api_error_rate_ci95'])} | "
         f"{on['invalid_tool_calls']}/{on['tool_calls']} {_ci(on['invalid_tool_call_rate_ci95'])} | "
         f"{_pct(on['accuracy'])} {_ci(on['accuracy_ci95'])} | {on['score']['mean']:.3f} "
         f"[{on['score']['ci95'][0]:.2f}, {on['score']['ci95'][1]:.2f}] | {100 * on['pct_of_solver_same_seeds']:.0f}% "
         f"{_ci(on['pct_of_solver_ci95'])} |",
         f"| OFF | {off['valid_episodes']} ({off['infra_invalid_episodes']} infra-invalid) | {off['api_errors']}/"
         f"{off['api_calls']} {_ci(off['api_error_rate_ci95'])} | n/a | n/a | n/a | n/a |", "",
         "## 2. Explicit context cache: cost delta (no new calls)",
         f"{c['method']} Atlas + gallery: {ag['cached_tokens']:,} of {ag['input_tokens']:,} input tokens cached "
         f"({_pct(ag['cached_share'])}); paid ${ag['usd_paid']:.2f} vs ${ag['usd_if_uncached']:.2f} uncached, "
         f"saving ${ag['usd_saved']:.2f} ({ag['pct_saved']}%). Atlas alone: ${c['atlas']['usd_paid']:.2f} vs "
         f"${c['atlas']['usd_if_uncached']:.2f} ({c['atlas']['pct_saved']}% saved); gallery alone: "
         f"${c['gallery']['usd_paid']:.2f} vs ${c['gallery']['usd_if_uncached']:.2f} ({c['gallery']['pct_saved']}% "
         f"saved). Whole programme (all {pg['calls']:,} ledgered calls, mostly implicit caching on ladder episodes): "
         f"{_pct(pg['cached_share'])} of {pg['input_tokens']:,} input tokens cached; ${pg['usd_paid']:.2f} paid vs "
         f"${pg['usd_if_uncached']:.2f}, saving ${pg['usd_saved']:.2f} ({pg['pct_saved']}%). These are exact "
         "accounting deltas over every ledgered call, not samples, so no CI applies.", "",
         "| scope | calls | input tok | cached | paid $ | uncached $ | saved $ | saved % |", "|---|---|---|---|---|---|---|---|"]
    for k in ("atlas", "gallery", "atlas_plus_gallery", "programme"):
        x = c[k]
        L.append(f"| {k} | {x['calls']:,} | {x['input_tokens']:,} | {_pct(x['cached_share'])} | {x['usd_paid']:.2f} | "
                 f"{x['usd_if_uncached']:.2f} | {x['usd_saved']:.2f} | {x['pct_saved']} |")
    regen = a.get("thinking_sweep_regenerated_at")
    L += ["", "## 3. Thinking-level sweep (no new calls)",
          (f"Regenerated {regen} from the canonical results/gemini/ladder.json"
           f"{' (git ' + a['ladder_git_sha'][:10] + ')' if a.get('ladder_git_sha') else ''}; sections 1 and 2 above "
           f"are unchanged from {a['generated_at']}. " if regen else "From results/gemini/ladder.json: ")
          + f"{len(sw)} model x thinking-level x tier cells. % of solver is paired on the same seeds. "
          f"**Bold** = the 95% CI excludes 100%: **{parity_sentence(sw)}**. gemini-3.5-flash is the requested id; "
          "the API serves gemini-3.6-flash. Thinking tokens marked * are estimates.", "",
          "| tier | model | level | n | % of solver [95% CI] | thinking tok/ep | USD/ep |", "|---|---|---|---|---|---|---|"]
    order = ["minimal", "low", "medium", "high", "xhigh", "default"]
    for r in sorted(sw, key=lambda r: (r["tier"] != "hard", r["model"],
                                       order.index(r["level"]) if r["level"] in order else 99)):
        cell = f"{r['pct_of_solver']}% [{r['ci95'][0]}, {r['ci95'][1]}]"
        if r["ci_excludes_100"]:
            cell = f"**{cell}**"
        L.append(f"| {r['tier']} | {r['model']} | {r['level']} | {r['n']} | {cell} | {r['thinking_tokens_per_ep']:,}"
                 f"{'*' if r['thinking_is_estimate'] else ''} | {r['usd_per_ep']:.3f} |")
    L += ["", "## §4 replacement (3 sentences)", "", *[f"> {x}" for x in a["section4"]], ""]
    return "\n".join(L)


def argon_clause(hard: dict, cell) -> str:
    """Direction of gemini-4-argon across its thinking levels on hard, read from the data (never asserted)."""
    lv = [x for x in ("low", "medium", "high") if ("gemini-4-argon", x) in hard]
    if len(lv) < 2:
        return "gemini-4-argon has fewer than two levels on hard"
    p = [hard[("gemini-4-argon", x)]["pct_of_solver"] for x in lv]
    lo, hi = hard[("gemini-4-argon", lv[0])], hard[("gemini-4-argon", lv[-1])]
    overlap = lo["ci95"][0] <= hi["ci95"][1] and hi["ci95"][0] <= lo["ci95"][1]
    shape = ("rises" if all(x < y for x, y in zip(p, p[1:])) else
             "falls" if all(x > y for x, y in zip(p, p[1:])) else "is non-monotone")
    return (f"gemini-4-argon {shape} across {' → '.join(lv)} ({' → '.join(f'{x}%' for x in p)}; "
            f"{cell('gemini-4-argon', lv[0])} vs {cell('gemini-4-argon', lv[-1])}"
            f"{', CIs overlap' if overlap else ''})")


def section4(a: dict) -> list[str]:
    on, off = a["thought_signatures"]["on"], a["thought_signatures"]["off"]
    ag = a["explicit_cache"]["atlas_plus_gallery"]
    pg = a["explicit_cache"]["programme"]
    hard = {(r["model"], r["level"]): r for r in a["thinking_sweep"] if r["tier"] == "hard"}
    def cell(m, lv):
        r = hard[(m, lv)]
        return (f"{r['pct_of_solver']}% [{r['ci95'][0]}, {r['ci95'][1]}] at {lv} (n={r['n']}, "
                f"{r['thinking_tokens_per_ep']:,} thinking tok, ${r['usd_per_ep']:.2f}/ep)")
    return [
        (f"**Thought signatures are load-bearing:** with signature replay stripped, the API rejected the first "
         f"function-call replay on {len(off['second_call_rejected_seeds'])}/{off['episodes_attempted']} hard-tier "
         f"episodes of gemini-3.8-flash (400 INVALID_ARGUMENT, \"Function call is missing a thought_signature\"; "
         f"Wilson 95% CI {_ci(off['rejection_rate_ci95'])}), so 0 episodes were playable, versus "
         f"{on['valid_episodes']}/{on['valid_episodes']} played with replay on "
         f"({on['api_errors']}/{on['api_calls']} API errors, accuracy {_pct(on['accuracy'])}, CI "
         f"{_ci(on['accuracy_ci95'])})."),
        (f"**Explicit context caching** cut the corpus-scale Atlas reads from ${ag['usd_if_uncached']:.2f} to "
         f"${ag['usd_paid']:.2f} ({ag['pct_saved']}% saved over all {ag['calls']} ledgered atlas/gallery calls; "
         f"{_pct(ag['cached_share'])} of {ag['input_tokens'] / 1e6:.1f}M input tokens cached; the 9 gallery calls "
         f"used no cache), and caching overall saved {pg['pct_saved']}% (${pg['usd_saved']:.2f} of "
         f"${pg['usd_if_uncached']:.2f}) across all {pg['calls']:,} ledgered calls in the programme."),
        (f"**`thinking_level` turns compute into a controlled variable on one model:** on the hard tier, "
         f"{_model('gemini-3.5-flash')} goes from {cell('gemini-3.5-flash', 'minimal')} to "
         f"{cell('gemini-3.5-flash', 'medium')} of the solver on the same seeds, while {argon_clause(hard, cell)}; "
         f"across all model x level x tier cells, {parity_sentence(a['thinking_sweep'])} (95% CIs)."),
    ]


def build() -> dict:
    ledger = _ledger_rows()
    a = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "thought_signatures": sig_ablation(ledger),
         "explicit_cache": cache_ablation(ledger), "thinking_sweep": sweep()}
    a["section4"] = section4(a)
    return a


def regenerate_sweep(ladder_json: Path | None = None, ablations_json: Path | None = None) -> dict:
    """Recompute ONLY the thinking sweep (+ its §4 sentence) from the canonical ladder.json; sections 1 and 2 are
    carried over verbatim from the committed ablations.json (no ledger re-read, no API calls)."""
    lj = ladder_json or RES / "ladder.json"
    a = json.loads((ablations_json or RES / "ablations.json").read_text())
    a["thinking_sweep"] = sweep(lj)
    a["thinking_sweep_regenerated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    a["ladder_git_sha"] = json.loads(lj.read_text()).get("git_sha")
    a["thinking_sweep_parity"] = parity_sentence(a["thinking_sweep"])
    keep = a.get("section4") or []
    a["section4"] = keep[:2] + [section4(a)[2]] if len(keep) >= 2 else section4(a)
    return a


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if "--sweep-only" in argv:
        a = regenerate_sweep()
        (RES / "ablations.json").write_text(json.dumps(a, indent=1))
        (RES / "ablations.md").write_text(render_md(a))
        print(a["section4"][2])
        return 0
    a = build()
    (RES / "ablations.json").write_text(json.dumps(a, indent=1))
    (RES / "ablations.md").write_text(render_md(a))
    print("\n".join(a["section4"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
