"""`make reproduce`: the judge table on the frozen judge seeds, no API keys needed. Owner: HARNESS.

    python -m canary.eval --reproduce [--repro-seeds N] [--results-dir DIR | --update-committed]

Runs the reference solver and the baselines in-process on JUDGE_SEEDS for every tier, replays any
committed frontier-agent episodes from data/runs/committed/**/episodes.jsonl (grouped by tier version,
current rules first, never pooled; data/runs/committed/superseded/ skipped), then writes
judge_table.md, judge_episodes.jsonl and gap_chart.png (needs matplotlib, the `plot` extra; skipped
with a note if missing) and prints the table.

Output goes to results/latest/ (gitignored) by default, so a judge's clone stays clean and the
committed results/*.md|png|jsonl stay untouched. `--update-committed` writes to results/ instead
(team use only, to refresh the committed copies).

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
import re
import signal
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
TIER_ORDER = ("medium", "hard", "easy")          # medium + hard are the headline tiers; easy = sanity
HEADLINE_TIERS = ("medium", "hard")
# In-process agents, in table order (the frontier replays are inserted after the solver).
REPRO_AGENTS = ("solver", "heuristic", "logs_only", "random", "guess_day1", "stop_early", "do_nothing")
AGENT_NOTES = {
    "solver": "reference: tuned Bayesian canary-trap solver",
    "heuristic": "canary bisection, no Bayes, no V timing",
    "logs_only": "strongest no-canary log reader",
    "random": "random valid tool calls",
    "guess_day1": "random accusation on day 1 (EV < 0 by design)",
    "stop_early": "stops on day 1 without accusing",
    "do_nothing": "never accuses",
}
FAST_SEEDS = 5
EPISODE_TIMEOUT_S = 60.0   # per-episode guard (env REPRO_EPISODE_TIMEOUT); a timed-out episode scores 0 and is reported
COMMITTED_GLOB = "data/runs/committed/**/episodes.jsonl"
COMMITTED_DIR = "data/runs/committed"
SUPERSEDED_DIR = "superseded"           # data/runs/committed/superseded/** is never replayed
LEGACY_TIERS_VERSION = "v1.2"           # committed runs with no version segment and no meta tiers_version
_VERSION_SEG = re.compile(r"^v\d+(\.\d+)*$")
DEFAULT_RESULTS_DIR = "results/latest"  # gitignored; what `make reproduce` writes by default
COMMITTED_RESULTS_DIR = "results"       # the committed copies; only --update-committed writes here


def results_dir_for(update_committed: bool = False, results_dir: str | Path | None = None) -> str | Path:
    """CLI resolution: an explicit --results-dir wins, then --update-committed, else results/latest/."""
    if results_dir is not None and update_committed:
        raise ValueError("use either --results-dir or --update-committed, not both")
    if results_dir is not None:
        return results_dir
    return COMMITTED_RESULTS_DIR if update_committed else DEFAULT_RESULTS_DIR


@dataclass
class Row:
    tier: str
    agent: str
    kind: str                      # reference | baseline | reported (replayed agent runs)
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


def anticheat_seeds(table_seeds: list[int]) -> list[int]:
    """Seeds for the anti-cheat verdict on the same world secret as the table.

    REPRO_FAST prints a 5-seed table. On those five judge seeds, easy accuse_most_logs
    (negative on the 800-seed confirmation table in results/fresh_table_v1.4.md) still
    averaged above 0 on 6 of 30 fresh secrets. The mean<=0 rule is unchanged. Below 20
    table seeds the fast path scores the verdict on every judge seed, where that probe's
    mean stayed negative.
    """
    from .rules import JUDGE_SEEDS
    fast = os.environ.get("REPRO_FAST", "").strip() not in ("", "0")
    if fast and len(table_seeds) < 20:
        return list(JUDGE_SEEDS)
    return list(table_seeds)


def world_secret_mode() -> tuple[str, str, bool]:
    """Returns (mode, fingerprint, generated) and installs this invocation's judge-world secret.

    mode = "exact" (CANARY_WORLD_SECRET / SALT) or "statistical" (one fresh os.urandom secret,
    installed in-process with world.set_world_secret, never put in the environment or printed).
    The fingerprint is a sha256 prefix: safe to print, identifies the secret, reveals nothing.
    Call restore_world_secret() afterwards.
    """
    from . import world
    global _PREV_SET_SECRET
    _PREV_SET_SECRET = getattr(world, "_SET_SECRET", None)
    has_set = hasattr(world, "set_world_secret")
    env = os.environ.get("CANARY_WORLD_SECRET")
    salt = ROOT / "data" / "worlds" / "judge" / "SALT"
    if env or salt.exists():
        if has_set:
            world.set_world_secret(None)  # an earlier in-process secret must not shadow the user's
        if env:
            return "exact", hashlib.sha256(env.encode()).hexdigest()[:12], False
        return "exact (SALT file)", hashlib.sha256(salt.read_bytes()).hexdigest()[:12], False
    fresh = os.urandom(32)
    if has_set:
        world.set_world_secret(fresh)
    else:  # older canary.world without the in-process setter
        os.environ["CANARY_WORLD_SECRET"] = fresh.hex()
        fresh = fresh.hex().encode()
    return "statistical", hashlib.sha256(fresh).hexdigest()[:12], True


_PREV_SET_SECRET: bytes | None = None


def restore_world_secret(generated: bool, prev_env: str | None) -> None:
    from . import world
    if hasattr(world, "set_world_secret"):
        world.set_world_secret(_PREV_SET_SECRET)
    if generated and not hasattr(world, "set_world_secret"):
        if prev_env is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_env


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
class EpisodeTimeout(BaseException):
    """BaseException so run_episode's `except Exception` (policy crash) cannot swallow it."""


def episode_timeout_s() -> float:
    v = os.environ.get("REPRO_EPISODE_TIMEOUT", "").strip()
    return float(v) if v else EPISODE_TIMEOUT_S


@contextmanager
def time_limit(seconds: float):
    """SIGALRM wall-clock guard (POSIX main thread); a no-op elsewhere."""
    usable = (seconds > 0 and hasattr(signal, "setitimer")
              and threading.current_thread() is threading.main_thread())
    if not usable:
        yield
        return

    def _raise(signum, frame):
        raise EpisodeTimeout()

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def run_in_process(tiers: Iterable[str], seeds: list[int], agents: Iterable[str] = REPRO_AGENTS,
                   episodes_out: list[dict] | None = None, timeout_s: float | None = None) -> list[Row]:
    """Paired runs: every agent plays the same (tier, seed) worlds under this process's secret."""
    from .eval import make_env, make_policy_factory, run_episode
    limit = episode_timeout_s() if timeout_s is None else timeout_s
    rows: list[Row] = []
    for tier in tiers:
        for agent in agents:
            factory = make_policy_factory(agent)
            row = Row(tier, agent, "reference" if agent == "solver" else "baseline",
                      [], [], [], [], note=AGENT_NOTES.get(agent, ""))
            for seed in seeds:
                try:
                    with time_limit(limit):
                        res = run_episode(make_env(tier, seed), factory(seed))
                    rec = {"score": float(res.score), "correct": bool(res.correct), "accused": res.accused,
                           "final_day": res.final_day, "end_reason": res.end_reason, "tool_calls": len(res.steps)}
                except EpisodeTimeout:
                    rec = {"score": 0.0, "correct": False, "accused": None, "final_day": None,
                           "end_reason": "timeout", "tool_calls": None}
                    row.extra.setdefault("timeouts", []).append(seed)
                row.scores.append(rec["score"])
                row.correct.append(rec["correct"])
                row.seeds.append(seed)
                if rec["end_reason"] == "accused":
                    row.accuse_days.append(rec["final_day"])
                if episodes_out is not None:
                    episodes_out.append({"tier": tier, "agent": agent, "seed": seed,
                                         **rec, "score": round(rec["score"], 6)})
            if row.extra.get("timeouts"):
                row.note += f"; TIMEOUT (> {limit:g} s, scored 0) on seeds {row.extra['timeouts']}"
            rows.append(row)
    return rows


def current_tiers_version() -> str:
    from .rules import TIERS_VERSION
    return TIERS_VERSION


def version_key(v: str) -> tuple[int, ...]:
    """'v1.10' -> (1, 10); unparseable versions sort first (oldest)."""
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (-1,)


def _rel_committed(run_dir: Path, root: Path) -> Path:
    try:
        return run_dir.relative_to(root / COMMITTED_DIR)
    except ValueError:
        return run_dir


def is_superseded(run_dir: Path, root: Path = ROOT) -> bool:
    """True for anything under data/runs/committed/superseded/ (any `superseded` path segment)."""
    return SUPERSEDED_DIR in _rel_committed(run_dir, root).parts


def run_meta(run_dir: Path) -> dict[str, Any]:
    try:
        meta = json.loads((run_dir / "meta.json").read_text())
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def run_tiers_version(run_dir: Path, root: Path = ROOT, meta: dict[str, Any] | None = None) -> str:
    """Tier version of one committed run: meta.json tiers_version, else a `vX.Y/` path segment under
    data/runs/committed/, else v1.2 (the runs committed before versioned folders existed)."""
    meta = run_meta(run_dir) if meta is None else meta
    v = meta.get("tiers_version")
    if isinstance(v, str) and v.strip():
        return v.strip()
    for seg in _rel_committed(run_dir, root).parts:
        if _VERSION_SEG.match(seg):
            return seg
    return LEGACY_TIERS_VERSION


def committed_files(root: Path = ROOT) -> list[Path]:
    """Committed episode files, superseded builds excluded."""
    return [f for f in sorted(root.glob(COMMITTED_GLOB)) if not is_superseded(f.parent, root)]


def invalid_reason(e: dict[str, Any]) -> str | None:
    """None for a valid episode; else a short reason for an infra failure (meta.valid == false)."""
    meta = e.get("meta") or {}
    if meta.get("valid") is not False:
        return None
    err = str(meta.get("error") or e.get("end_reason") or "unknown")
    if err.startswith("infra:"):
        return err
    if "server died" in err:
        return "mcp server died"
    return err[:40]


def run_recency(run_dir: Path, meta: dict[str, Any]) -> tuple[str, str]:
    """Sort key for "newest run wins": meta.json timestamp (ISO, sortable), then the path as tiebreak.
    File mtimes are not used, because a fresh clone gives every file the same mtime."""
    return (str(meta.get("timestamp") or ""), str(run_dir))


def load_committed(root: Path = ROOT) -> tuple[list[Row], list[str]]:
    """Replay committed frontier-agent episodes (scores were computed server-side when recorded).

    One row per (tier, tiers_version, agent): runs from different tier versions are never pooled,
    and data/runs/committed/superseded/ is skipped. Each row carries extra["tiers_version"] and
    extra["git_shas"] (from meta.json, where present).

    Integrity rules for the means:
      * invalid episodes (meta.valid == false: provider quota, a killed MCP server, ...) are left out of
        the mean and listed in extra["invalid"] as (seed, reason), shown in the `invalid` column;
      * per (tier, version, agent, seed) only the NEWEST run directory counts (run_recency), so a smoke
        run and a later full run never double-count a seed. Repeats of a seed WITHIN one run directory
        are kept (that is how pass^k is measured), and the note then warns that n != distinct seeds."""
    from .rules import JUDGE_SEEDS
    files = committed_files(root)
    labels: list[str] = []
    # (tier, version, agent) -> seed -> list of (recency, run_dir, sha, episode)
    found: dict[tuple[str, str, str], dict[int, list[tuple[tuple[str, str], str, str, dict]]]] = {}
    invalid: dict[tuple[str, str, str], list[tuple[int, str]]] = defaultdict(list)
    for f in files:
        meta = run_meta(f.parent)
        version = run_tiers_version(f.parent, root, meta)
        sha = str(meta.get("git_sha") or "").strip()[:7]
        rec = run_recency(f.parent, meta)
        rel = str(f.parent.relative_to(root))
        labels.append(f"{f.relative_to(root)} [{version}]")
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            key = (e["tier"], version, e["agent"])
            reason = invalid_reason(e)
            if reason is not None:
                invalid[key].append((int(e["seed"]), reason))
                found.setdefault(key, {})
                continue
            found.setdefault(key, {}).setdefault(int(e["seed"]), []).append((rec, rel, sha, e))

    rows: list[Row] = []
    for key, by_seed in found.items():
        tier, version, agent = key
        r = Row(tier, agent, "reported", [], [], [], [], note="replayed",
                extra={"tiers_version": version, "git_shas": set(), "runs": set(),
                       "invalid": sorted(invalid.get(key, [])), "dropped_duplicates": []})
        for seed in sorted(by_seed):
            entries = by_seed[seed]
            newest = max(entries, key=lambda x: x[0])[1]
            for rec, rel, sha, e in entries:
                if rel != newest:
                    r.extra["dropped_duplicates"].append((seed, rel))
                    continue
                r.scores.append(float(e["score"]))
                r.correct.append(bool(e["correct"]))
                r.seeds.append(seed)
                if e.get("end_reason") == "accused":
                    r.accuse_days.append(int(e["final_day"]))
                r.extra["runs"].add(rel)
                if sha:
                    r.extra["git_shas"].add(sha)
        if not r.scores and not r.extra["invalid"]:
            continue
        judge = bool(r.seeds) and all(s in JUDGE_SEEDS for s in r.seeds)
        shas = sorted(r.extra["git_shas"])
        n_distinct = len(set(r.seeds))
        r.note = (f"replayed, {'judge' if judge else 'NON-judge'} seeds, {n_distinct} seeds, "
                  f"git {', '.join(shas) if shas else 'unknown'} ({', '.join(sorted(r.extra['runs']))})")
        if agent == "stop_early":
            r.note += ("; these episodes accused on day 1 under the old stop_early script "
                       "(that policy is now guess_day1; current stop_early scores 0)")
        if r.n != n_distinct:
            r.note += f"; WARNING n={r.n} != {n_distinct} distinct seeds (repeats within one run)"
        if r.extra["dropped_duplicates"]:
            older = sorted({rel for _, rel in r.extra["dropped_duplicates"]})
            r.note += (f"; {len(r.extra['dropped_duplicates'])} older duplicate episode(s) dropped "
                       f"(newest run per seed kept; from {', '.join(older)})")
        rows.append(r)
    return rows, labels


def pending_rows(tiers: Iterable[str]) -> list[Row]:
    v = current_tiers_version()
    return [Row(t, "frontier agents (gpt-5.5, gpt-5.6-sol)", "reported", [], [], [], [],
                note=(f"gap not established: no {v} frontier episodes in {COMMITTED_DIR}/. "
                      "In-process bake-off n=10: gemini-4-carbon matches or beats the solver"),
                pending=True,
                extra={"tiers_version": v})
            for t in tiers if t in HEADLINE_TIERS]


def reported_groups(rows: list[Row], current: str | None = None) -> list[tuple[str, str, list[Row]]]:
    """Reported rows split by tier version: [(version, heading, rows)], current version first, then
    the other versions newest first. Never pools across versions."""
    current = current or current_tiers_version()
    by_v: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_v[r.extra.get("tiers_version") or current].append(r)
    out = []
    if current in by_v:
        out.append((current, f"Reported agent runs: {current} (current rules)", by_v.pop(current)))
    for v in sorted(by_v, key=version_key, reverse=True):
        rel = "earlier" if version_key(v) < version_key(current) else "other"
        out.append((v, f"History: {v} ({rel} rules, not comparable to the paired table)", by_v[v]))
    return out


# --------------------------------------------------------------------------- report
def _f(x: float, nd: int = 3, sign: bool = False) -> str:
    if x is None or x != x:
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def order_rows(rows: list[Row]) -> list[Row]:
    rank = {"reference": 0, "baseline": 1, "reported": 2}
    base = {a: i for i, a in enumerate(REPRO_AGENTS)}
    return sorted(rows, key=lambda r: (TIER_ORDER.index(r.tier) if r.tier in TIER_ORDER else 9,
                                       rank[r.kind], base.get(r.agent, 0), r.agent))


COLS = ("| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |\n"
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|")


def _invalid_md(r: Row) -> str:
    """'0', or 'k (reason ×m, ...)' for replayed episodes excluded as infra failures (meta.valid == false)."""
    inv = r.extra.get("invalid") or []
    if not inv:
        return "0"
    counts: dict[str, int] = defaultdict(int)
    for _seed, reason in inv:
        counts[reason] += 1
    return f"{len(inv)} (" + ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in sorted(counts.items())) + ")"


def _row_md(r: Row, solver_mean: float | None, compare: bool = True) -> str:
    if r.pending:
        return f"| {r.agent} | {r.kind} | 0 | – | pending | – | – | – | – | – | {r.note} |"
    m, h = mean_ci(r.scores)
    if r.agent == "solver" and r.kind == "reference":
        norm = 1.0
    elif not compare:  # earlier-rules history: a ratio to this run's solver would mislead
        norm = float("nan")
    else:
        norm = m / solver_mean if solver_mean and solver_mean > 0 else float("nan")
    pk = pass_k(r)
    return (f"| {r.agent} | {r.kind} | {r.n} | {_invalid_md(r)} | {_f(m, sign=True)} ± {_f(h)} | {_f(mean(r.correct), 2)} | "
            f"{len(r.accuse_days)}/{r.n} | {_f(mean(r.accuse_days), 1)} | {_f(norm, 2)} | "
            f"{f'pass^{pk[0]}={pk[1]:.2f}' if pk else '–'} | {r.note} |")


def table_md(rows: list[Row], header: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("# Canary judge table")
    out.append("")
    out.append(f"- seeds: {header['n_seeds']} judge seeds per tier ({header['seed_range']})"
               + ("  **[FAST MODE: not the reported numbers]**" if header["fast"] else ""))
    note = ("statistical reproduction; set CANARY_WORLD_SECRET for exact numbers" if header.get("generated")
            else "exact: same secret, same numbers")
    out.append(f"- judge-world secret: {header['mode']}, sha256 fingerprint `{header['fingerprint']}` ({note})")
    out.append(f"- git: `{header['git_sha'][:12]}`, generated {header['timestamp']}, {header['seconds']:.1f} s")
    out.append("- reward: true V at accusation if correct (V starts at 1.0 and drops with every leak, "
               "including leaks that have not surfaced yet; v1.3 `status` shows only surfaced damage), "
               "-1 if wrong, 0 if no accusation")
    out.append("- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation")
    out.append("- `/ solver` = agent mean / solver mean on the same tier (ratio of means); "
               "`pass^k` only for agents with k repeated runs per seed")
    cur = header.get("tiers_version") or current_tiers_version()
    out.append("- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). "
               "**reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the "
               "team's worlds, so they are NOT paired with this run; compare them by mean ± CI only")
    if any(r.pending for r in rows):
        out.append(f"- **{cur} frontier gap: not established.** This table has no committed {cur} frontier episodes.")
    else:
        out.append(f"- **{cur} frontier vs solver, paired on the same seeds:** "
                   f"`data/runs/committed/{cur}/paired_table_gemini.md`, explained in `docs/reports/gap.md`. "
                   f"The {cur} reported rows below replay those committed episodes (played on dev seeds under the "
                   "team's secret), so they are not paired with this invocation's judge worlds.")
    out.append(f"- reported runs are grouped by tier version and never pooled: {cur} (current rules) first, then "
               "earlier versions as history (not comparable to the paired table; `/ solver` left blank). "
               f"Builds under {COMMITTED_DIR}/{SUPERSEDED_DIR}/ are excluded")
    timeouts = [(r.tier, r.agent, s) for r in rows for s in r.extra.get("timeouts", [])]
    out.append(f"- per-episode timeout guard: {header.get('timeout_s', EPISODE_TIMEOUT_S):g} s; "
               + (f"**{len(timeouts)} timed out (scored 0)**: "
                  + ", ".join(f"{t}/{a}/{s}" for t, a, s in timeouts) if timeouts else "no episode timed out"))
    sol = {r.tier: mean(r.scores) for r in rows if r.agent == "solver" and r.kind == "reference"}
    for tier in TIER_ORDER:
        paired = [r for r in rows if r.tier == tier and r.kind != "reported"]
        reported = [r for r in rows if r.tier == tier and r.kind == "reported"]
        if not paired and not reported:
            continue
        label = "headline" if tier in HEADLINE_TIERS else "sanity tier"
        out += ["", f"## {tier} ({label})"]
        if paired:
            out += ["", "Paired runs (this invocation, same worlds):", "", COLS]
            out += [_row_md(r, sol.get(tier)) for r in paired]
        for version, heading, grp in reported_groups(reported, cur):
            out += ["", f"{heading}:", "", COLS]
            out += [_row_md(r, sol.get(tier), compare=False) for r in grp]
            if version == cur:
                out += ["", f"`/ solver` is blank for reported runs: they were played on dev seeds under the team's "
                        f"secret, so a ratio to this invocation's judge-world solver would mislead. The paired ratios "
                        f"(same seeds as the solver) are in `data/runs/committed/{cur}/paired_table_gemini.md` "
                        f"and `docs/reports/gap.md`."]
    return "\n".join(out) + "\n"


def exact_match_text(mode: str, generated: bool, fingerprint: str = "") -> str:
    if generated:
        return (f"Statistical reproduction; set CANARY_WORLD_SECRET for exact numbers.\n"
                f"No CANARY_WORLD_SECRET was set, so this invocation drew ONE fresh random judge-world secret\n"
                f"(sha256 fingerprint {fingerprint}; the secret itself is never printed or written) and used it for\n"
                "every agent, so the comparison is paired. Expect each mean inside the published ± 95% CI, not\n"
                "bit-for-bit equality. For exact, repeatable numbers:\n"
                "    CANARY_WORLD_SECRET=<any string> make reproduce   # same string -> identical judge_episodes.jsonl\n"
                "(the secret behind the team's Harbor worlds stays private: it would reveal the judge-world moles).")
    return (f"Exact reproduction: judge-world secret mode = {mode} (fingerprint {fingerprint}). Rerunning with the\n"
            "same secret gives identical per-episode results (judge_episodes.jsonl) and the same table.")


def gap_chart(rows: list[Row], path: Path) -> str | None:
    """Small multiples (one panel per tier), mean ± 95% CI per agent. Returns a skip reason or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "matplotlib not installed (uv sync --extra plot); skipped gap_chart.png"
    cur = current_tiers_version()  # earlier-rules history rows are table-only, never charted
    rows = [r for r in rows if r.kind != "reported" or r.extra.get("tiers_version", cur) == cur]
    tiers = [t for t in TIER_ORDER if any(r.tier == t and not r.pending for r in rows)]
    colors = {"reference": "#2a78d6", "reported": "#eb6834", "baseline": "#9a9893"}
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
        fig.text(0.01, 0.005, "v1.4 frontier gap not established: no committed frontier runs",
                 fontsize=8, color="#52514e", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return None


def reproduce(n_seeds: int | None = None, results_dir: str | Path = DEFAULT_RESULTS_DIR,
              tiers: Iterable[str] = TIER_ORDER, root: Path = ROOT, quiet: bool = False) -> dict[str, Any]:
    from .eval import git_sha
    t0 = time.time()
    seeds = seeds_per_tier(n_seeds)
    prev = os.environ.get("CANARY_WORLD_SECRET")
    mode, fingerprint, generated = world_secret_mode()
    try:
        episodes: list[dict] = []
        rows = run_in_process(tiers, seeds, episodes_out=episodes)
        anticheat = None
        if os.environ.get("REPRO_ANTICHEAT", "1") != "0":   # INTEGRITY: anti-cheat battery, same secret as the table
            from .redteam.anticheat import run_battery
            ac_seeds = anticheat_seeds(seeds)
            anticheat = run_battery(list(tiers), ac_seeds)
            if ac_seeds != list(seeds):
                anticheat["verdict_note"] = (
                    f"Anti-cheat verdict uses all {len(ac_seeds)} judge seeds on this secret. "
                    f"The table above uses {len(seeds)} (REPRO_FAST). "
                    "A 5-seed mean can sit above 0 for a negative-EV probe "
                    "(easy accuse_most_logs did, while its 800-seed confirmation mean is negative). "
                    "The blocked rule is still mean <= 0."
                )
    finally:  # never leak this invocation's secret into the rest of the process (tests, MCP, ...)
        restore_world_secret(generated, prev)
    committed, files = load_committed(root)
    tiers = list(tiers)
    committed = [r for r in committed if r.tier in tiers]
    current = current_tiers_version()
    if not any(r.extra.get("tiers_version") == current for r in committed):
        rows += pending_rows(tiers)
    rows = order_rows(rows + committed)
    from .rules import JUDGE_SEEDS
    header = {"n_seeds": len(seeds), "seed_range": f"{seeds[0]}..{seeds[-1]}",
              "fast": len(seeds) < len(JUDGE_SEEDS), "mode": mode, "fingerprint": fingerprint,
              "generated": generated, "timeout_s": episode_timeout_s(), "tiers_version": current,
              "git_sha": git_sha(), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "seconds": time.time() - t0}
    out = Path(results_dir)
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    md = table_md(rows, header)
    (out / "judge_table.md").write_text(md, encoding="utf-8")
    with open(out / "judge_episodes.jsonl", "w", encoding="utf-8") as fh:
        for e in episodes:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    skip = gap_chart(rows, out / "gap_chart.png")
    ac_md = ""
    if anticheat is not None:
        from .redteam.anticheat import harbor_consistency, replay_committed, replay_counts, table_md as ac_table_md
        replay = replay_committed(root)
        harbor = harbor_consistency(root)
        anticheat.update(replay=replay, seeds=[seeds[0], seeds[-1], len(seeds)], tiers=list(tiers),
                         replay_all_consistent=all(r["replay_consistent"] is not False for r in replay),
                         replay_counts=replay_counts(replay), harbor=harbor,
                         harbor_all_consistent=all(r["consistent"] is not False for r in harbor))
        (out / "exploits.json").write_text(json.dumps(anticheat, indent=1, sort_keys=True, default=str),
                                           encoding="utf-8")
        ac_md = ac_table_md(anticheat, replay, harbor)
        (out / "exploits.md").write_text(ac_md, encoding="utf-8")
    header["seconds"] = time.time() - t0
    ac_bad: list[str] = []
    if anticheat is not None:   # computed even when quiet: eval --reproduce exits 1 on any of these
        ac_bad = [f"{r['tier']}/{r['probe']}" for r in anticheat["rows"] if r["blocked"] is False]
        ac_bad += [f"replay:{r['file']}" for r in anticheat.get("replay") or [] if r["replay_consistent"] is False]
        ac_bad += [f"harbor:{r['trial']}" for r in anticheat.get("harbor") or [] if r["consistent"] is False]
    if not quiet:
        print(md)
        if ac_md:
            print(ac_md)
            print(f"anti-cheat: wrote {out / 'exploits.json'}, {out / 'exploits.md'}")
        print(f"committed agent episode files: {len(files)} (excluding {COMMITTED_DIR}/{SUPERSEDED_DIR}/)"
              + ("".join(f"\n  {f}" for f in files) if files else
                 f" (frontier rows pending until {COMMITTED_GLOB} exists)"))
        print(exact_match_text(mode, generated, fingerprint))
        print(f"\nwrote {out / 'judge_table.md'}, {out / 'judge_episodes.jsonl'}"
              + (f"\nNOTE: {skip}" if skip else f", {out / 'gap_chart.png'}"))
        if out.resolve() == (root / DEFAULT_RESULTS_DIR).resolve():
            print(f"(the committed copies in {COMMITTED_RESULTS_DIR}/ are untouched; "
                  "the team refreshes them with --update-committed)")
        print(f"total {header['seconds']:.1f} s")
        if anticheat is not None:   # last line on purpose: a probe that gets through must not scroll away
            print("ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent" if not ac_bad
                  else f"ANTI-CHEAT FAILURE: {len(ac_bad)} not blocked / inconsistent: {', '.join(ac_bad[:12])} "
                       "(exit code 1)")
    return {"rows": rows, "header": header, "markdown": md, "anticheat": anticheat,
            "anticheat_ok": None if anticheat is None else not ac_bad, "chart_skipped": skip,
            "committed_files": files, "results_dir": out}
