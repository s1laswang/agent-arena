"""`make reproduce`: the judge table on the frozen judge seeds, no API keys needed. Owner: HARNESS.

    python -m canary.eval --reproduce [--repro-seeds N] [--results-dir results]

Runs the reference solver and the baselines in-process on JUDGE_SEEDS for every tier, replays any
committed frontier-agent episodes from data/runs/committed/**/episodes.jsonl, then writes
results/judge_table.md, results/judge_episodes.jsonl and results/gap_chart.png (needs matplotlib,
the `plot` extra; skipped with a note if missing) and prints the table.

Seeds per tier: --repro-seeds N > env REPRO_SEEDS=N > env REPRO_FAST=1 (5 seeds) > all JUDGE_SEEDS.

Judge worlds are keyed by a secret (CONTRACT v0.2/v0.5). Without CANARY_WORLD_SECRET (or the
uncommitted data/worlds/judge/SALT) this run draws one fresh random secret, shared by every agent in
the run so per-seed comparisons stay fair, and never printed. Results are then reproducible
statistically (mean ± 95% CI), not bit-for-bit. With CANARY_WORLD_SECRET set, two runs are identical.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
TIER_ORDER = ("medium", "hard", "easy")          # medium + hard are the headline tiers; easy = sanity
HEADLINE_TIERS = ("medium", "hard")
# In-process agents, in table order (the frontier replays are inserted after the solver).
REPRO_AGENTS = ("solver", "heuristic", "logs_only", "random", "stop_early", "do_nothing")
AGENT_NOTES = {
    "solver": "reference: tuned Bayesian canary-trap solver",
    "heuristic": "canary bisection, no Bayes, no V timing",
    "logs_only": "strongest no-canary log reader",
    "random": "random valid tool calls",
    "stop_early": "random accusation on day 1",
    "do_nothing": "never accuses",
}
FAST_SEEDS = 5
COMMITTED_GLOB = "data/runs/committed/**/episodes.jsonl"


@dataclass
class Row:
    tier: str
    agent: str
    kind: str                      # reference | frontier | baseline
    scores: list[float]
    correct: list[bool]
    accuse_days: list[int]
    seeds: list[int]
    note: str = ""
    pending: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.scores)


# --------------------------------------------------------------------------- config
def seeds_per_tier(cli: int | None = None) -> list[int]:
    from .rules import JUDGE_SEEDS
    judge = list(JUDGE_SEEDS)
    n = cli
    if n is None and os.environ.get("REPRO_SEEDS", "").strip():
        n = int(os.environ["REPRO_SEEDS"])
    if n is None and os.environ.get("REPRO_FAST", "").strip() not in ("", "0"):
        n = FAST_SEEDS
    if n is None or n >= len(judge):
        return judge
    return judge[:max(1, n)]


def world_secret_mode() -> tuple[str, str, bool]:
    """Returns (mode, fingerprint, generated). Sets CANARY_WORLD_SECRET for this process if absent.

    mode = "exact" (secret given by the user / SALT) or "statistical" (fresh random secret).
    The fingerprint is a sha256 prefix: safe to print, identifies the secret, reveals nothing.
    """
    env = os.environ.get("CANARY_WORLD_SECRET")
    if env:
        return "exact", hashlib.sha256(env.encode()).hexdigest()[:12], False
    salt = ROOT / "data" / "worlds" / "judge" / "SALT"
    if salt.exists():
        return "exact (SALT file)", hashlib.sha256(salt.read_bytes()).hexdigest()[:12], False
    fresh = secrets.token_hex(32)
    os.environ["CANARY_WORLD_SECRET"] = fresh
    return "statistical", hashlib.sha256(fresh.encode()).hexdigest()[:12], True


# --------------------------------------------------------------------------- stats
def mean_ci(xs: list[float]) -> tuple[float, float]:
    from .analysis.gap import mean_ci as _mc
    return _mc(xs)


def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def pass_k(row: Row) -> tuple[int, float] | None:
    """pass^k over repeated runs of the same seed (k = fewest runs per seed, >= 2), else None."""
    from .analysis.gap import pass_hat_k
    by_seed: dict[int, list[bool]] = defaultdict(list)
    for s, c in zip(row.seeds, row.correct):
        by_seed[s].append(c)
    if not by_seed:
        return None
    k = min(len(v) for v in by_seed.values())
    if k < 2:
        return None
    return k, pass_hat_k(by_seed, k)


# --------------------------------------------------------------------------- runs
def run_in_process(tiers: Iterable[str], seeds: list[int], agents: Iterable[str] = REPRO_AGENTS,
                   episodes_out: list[dict] | None = None) -> list[Row]:
    from .eval import make_env, make_policy_factory, run_episode
    rows: list[Row] = []
    for tier in tiers:
        for agent in agents:
            factory = make_policy_factory(agent)
            row = Row(tier, agent, "reference" if agent == "solver" else "baseline",
                      [], [], [], [], note=AGENT_NOTES.get(agent, ""))
            for seed in seeds:
                res = run_episode(make_env(tier, seed), factory(seed))
                row.scores.append(float(res.score))
                row.correct.append(bool(res.correct))
                row.seeds.append(seed)
                if res.end_reason == "accused":
                    row.accuse_days.append(res.final_day)
                if episodes_out is not None:
                    episodes_out.append({"tier": tier, "agent": agent, "seed": seed,
                                         "score": round(float(res.score), 6), "correct": bool(res.correct),
                                         "accused": res.accused, "final_day": res.final_day,
                                         "end_reason": res.end_reason, "tool_calls": len(res.steps)})
            rows.append(row)
    return rows


def load_committed(root: Path = ROOT) -> tuple[list[Row], list[str]]:
    """Replay committed frontier-agent episodes (scores were computed server-side when recorded)."""
    from .rules import JUDGE_SEEDS
    files = sorted(root.glob(COMMITTED_GLOB))
    groups: dict[tuple[str, str], Row] = {}
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            key = (e["tier"], e["agent"])
            if key not in groups:
                groups[key] = Row(e["tier"], e["agent"], "frontier", [], [], [], [], note="replayed")
            r = groups[key]
            r.scores.append(float(e["score"]))
            r.correct.append(bool(e["correct"]))
            r.seeds.append(int(e["seed"]))
            if e.get("end_reason") == "accused":
                r.accuse_days.append(int(e["final_day"]))
            r.extra.setdefault("runs", set()).add(str(f.parent.relative_to(root)))
    for r in groups.values():
        judge = all(s in JUDGE_SEEDS for s in r.seeds)
        r.note = f"replayed, {'judge' if judge else 'non-judge'} seeds, {len(set(r.seeds))} seeds"
    return list(groups.values()), [str(f.relative_to(root)) for f in files]


def pending_rows(tiers: Iterable[str]) -> list[Row]:
    return [Row(t, "frontier agents (gpt-5.5, gpt-5.6-sol)", "frontier", [], [], [], [],
                note=f"pending: no {COMMITTED_GLOB} yet", pending=True)
            for t in tiers if t in HEADLINE_TIERS]


# --------------------------------------------------------------------------- report
def _f(x: float, nd: int = 3, sign: bool = False) -> str:
    if x is None or x != x:
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def order_rows(rows: list[Row]) -> list[Row]:
    rank = {"reference": 0, "frontier": 1, "baseline": 2}
    base = {a: i for i, a in enumerate(REPRO_AGENTS)}
    return sorted(rows, key=lambda r: (TIER_ORDER.index(r.tier) if r.tier in TIER_ORDER else 9,
                                       rank[r.kind], base.get(r.agent, 0), r.agent))


def table_md(rows: list[Row], header: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("# Canary judge table")
    out.append("")
    out.append(f"- seeds: {header['n_seeds']} judge seeds per tier ({header['seed_range']})"
               + ("  **[FAST MODE: not the reported numbers]**" if header["fast"] else ""))
    out.append(f"- judge-world secret: {header['mode']} (sha256 prefix `{header['fingerprint']}`)")
    out.append(f"- git: `{header['git_sha'][:12]}`, generated {header['timestamp']}, {header['seconds']:.1f} s")
    out.append("- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), "
               "-1 if wrong, 0 if no accusation")
    out.append("- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation\n"
               "- `/ solver` = agent mean / solver mean on the same tier (ratio of means); "
               "`pass^k` only for agents with k repeated runs per seed")
    sol = {r.tier: mean(r.scores) for r in rows if r.agent == "solver"}
    for tier in TIER_ORDER:
        trs = [r for r in rows if r.tier == tier]
        if not trs:
            continue
        label = "headline" if tier in HEADLINE_TIERS else "sanity tier"
        out += ["", f"## {tier} ({label})", "",
                "| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for r in trs:
            if r.pending:
                out.append(f"| {r.agent} | {r.kind} | 0 | pending | – | – | – | – | – | {r.note} |")
                continue
            m, h = mean_ci(r.scores)
            norm = m / sol[tier] if sol.get(tier, 0) > 0 and r.agent != "solver" else (1.0 if r.agent == "solver" else float("nan"))
            pk = pass_k(r)
            out.append(f"| {r.agent} | {r.kind} | {r.n} | {_f(m, sign=True)} ± {_f(h)} | "
                       f"{_f(mean(r.correct), 2)} | {len(r.accuse_days)}/{r.n} | {_f(mean(r.accuse_days), 1)} | {_f(norm, 2)} | "
                       f"{f'pass^{pk[0]}={pk[1]:.2f}' if pk else '–'} | {r.note} |")
    return "\n".join(out) + "\n"


def exact_match_text(mode: str, generated: bool) -> str:
    if generated:
        return ("Reproducibility: no CANARY_WORLD_SECRET was set, so this run used a fresh random judge-world\n"
                "secret (CONTRACT v0.5, fail-closed). The numbers are statistically reproducible: expect each\n"
                "mean inside the published ± 95% CI, not bit-for-bit equality. For exact, repeatable numbers:\n"
                "    CANARY_WORLD_SECRET=<any string> make reproduce   # same string -> identical judge_table\n"
                "(the secret behind our published numbers stays private: it would reveal the judge-world moles).")
    return (f"Reproducibility: judge-world secret mode = {mode}. Rerunning with the same secret gives\n"
            "identical per-episode results (results/judge_episodes.jsonl) and an identical table.")


def gap_chart(rows: list[Row], path: Path) -> str | None:
    """Small multiples (one panel per tier), mean ± 95% CI per agent. Returns a skip reason or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "matplotlib not installed (uv sync --extra plot); skipped results/gap_chart.png"
    tiers = [t for t in TIER_ORDER if any(r.tier == t and not r.pending for r in rows)]
    colors = {"reference": "#2a78d6", "frontier": "#eb6834", "baseline": "#9a9893"}
    fig, axes = plt.subplots(1, len(tiers), figsize=(4.6 * len(tiers), 3.9), sharey=False, squeeze=False)
    for ax, tier in zip(axes[0], tiers):
        trs = [r for r in rows if r.tier == tier and not r.pending]
        names = [r.agent for r in trs][::-1]
        stats = [mean_ci(r.scores) for r in trs][::-1]
        kinds = [r.kind for r in trs][::-1]
        y = range(len(trs))
        ax.barh(list(y), [m for m, _ in stats], xerr=[h for _, h in stats], height=0.62,
                color=[colors[k] for k in kinds], error_kw={"ecolor": "#3d3c39", "elinewidth": 1, "capsize": 2})
        ax.axvline(0, color="#3d3c39", linewidth=0.8)
        ax.set_yticks(list(y), names, fontsize=9)
        ax.set_xlim(-1.1, 1.1)
        ax.set_title(f"{tier}" + ("" if tier in HEADLINE_TIERS else " (sanity)"), fontsize=11, loc="left")
        ax.grid(axis="x", color="#e6e5e1", linewidth=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for yi, (m, h) in zip(y, stats):
            ax.text(1.08, yi, f"{m:+.2f}", va="center", ha="right", fontsize=8, color="#52514e")
        ax.set_xlabel("mean score (V if right, -1 if wrong, 0 if none)", fontsize=8, color="#52514e")
    fig.suptitle("Canary: reference solver vs agents on judge seeds (mean ± 95% CI)", fontsize=11, x=0.01, ha="left")
    if any(r.pending for r in rows):
        fig.text(0.01, 0.005, "frontier-agent rows pending: no committed runs in data/runs/committed/ yet",
                 fontsize=8, color="#52514e", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return None


def reproduce(n_seeds: int | None = None, results_dir: str | Path = "results",
              tiers: Iterable[str] = TIER_ORDER, root: Path = ROOT, quiet: bool = False) -> dict[str, Any]:
    from .eval import git_sha
    t0 = time.time()
    seeds = seeds_per_tier(n_seeds)
    prev = os.environ.get("CANARY_WORLD_SECRET")
    mode, fingerprint, generated = world_secret_mode()
    try:
        episodes: list[dict] = []
        rows = run_in_process(tiers, seeds, episodes_out=episodes)
    finally:  # never leak a generated secret into the rest of this process (tests, MCP, ...)
        if generated:
            if prev is None:
                os.environ.pop("CANARY_WORLD_SECRET", None)
            else:
                os.environ["CANARY_WORLD_SECRET"] = prev
    committed, files = load_committed(root)
    tiers = list(tiers)
    committed = [r for r in committed if r.tier in tiers]
    if not committed:
        rows += pending_rows(tiers)
    rows = order_rows(rows + committed)
    from .rules import JUDGE_SEEDS
    header = {"n_seeds": len(seeds), "seed_range": f"{seeds[0]}..{seeds[-1]}",
              "fast": len(seeds) < len(JUDGE_SEEDS), "mode": mode, "fingerprint": fingerprint,
              "git_sha": git_sha(), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "seconds": time.time() - t0}
    out = Path(results_dir)
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    md = table_md(rows, header)
    (out / "judge_table.md").write_text(md)
    with open(out / "judge_episodes.jsonl", "w") as fh:
        for e in episodes:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    skip = gap_chart(rows, out / "gap_chart.png")
    header["seconds"] = time.time() - t0
    if not quiet:
        print(md)
        print(f"committed agent episode files: {len(files)}" + ("".join(f"\n  {f}" for f in files) if files else
              f" (frontier rows pending until {COMMITTED_GLOB} exists)"))
        print(exact_match_text(mode, generated))
        print(f"\nwrote {out / 'judge_table.md'}, {out / 'judge_episodes.jsonl'}"
              + (f"\nNOTE: {skip}" if skip else f", {out / 'gap_chart.png'}"))
        print(f"total {header['seconds']:.1f} s")
    return {"rows": rows, "header": header, "markdown": md, "chart_skipped": skip,
            "committed_files": files, "results_dir": out}
