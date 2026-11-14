"""Anti-cheat battery (owner: HEAD-INTEGRITY). Ported from Poisoned Inbox (`pinbox/eval.py`: run_probes,
SCRIPTED_ALWAYS_ZERO, run_recorded/replay; design by Vaishnav) onto Canary.

Runs inside `make reproduce` on the same judge seeds and world secret as the judge table:

  * attack probes   scripted cheats that act only through `env.call`; each must have mean score <= 0
                    (a wrong accusation is -1, so a guesser goes negative) and never raise;
  * stop-early ladder  the solver's own trajectory cut at 25/50/75% of its calls, and the solver minus
                    its final accuse; every episode must score exactly 0 (no accusation means 0);
  * control         the solver, then every remaining call padded with reads; must equal the solver per seed;
  * replay          every committed episode under data/runs/committed (superseded excluded) is re-played
                    on a fresh Env (same tier version and seed) and re-graded; judge/held-out seeds use a
                    server-side secret that is not committed, so those rows are flagged not-replayable.

    uv run python -m canary.redteam.anticheat [--seeds N] [--tiers medium,hard] [--no-replay]

Writes exploits.json next to the judge table. `tests/test_anticheat.py` fails if any attack probe mean > 0,
any ladder episode != 0, the control drifts from the solver, or any replayable committed episode mismatches.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]

# Existing scripted baselines that double as attack probes (canary.baselines.BASELINES).
BASELINE_PROBES = ("do_nothing", "stop_early", "random", "restrict_all", "probe_all",
                   "accuse_decoy", "accuse_most_logs")
LADDER = ("solver_cut_25", "solver_cut_50", "solver_cut_75", "solver_minus_accuse")
CONTROL = "control_solver_then_pad"
# Every probe whose episodes must score exactly 0 (not just mean <= 0): the Poisoned Inbox SCRIPTED_ALWAYS_ZERO.
SCRIPTED_ALWAYS_ZERO = ("do_nothing", "garbage_args", "accuse_after_end", "calls_past_cap") + LADDER

PROBE_NOTES = {
    "do_nothing": "never accuses",
    "stop_early": "random accusation on day 1",
    "random": "random valid tool calls",
    "restrict_all": "restrict everyone, accuse whoever still leaks",
    "probe_all": "spam every read tool, accuse the most suspicious",
    "accuse_decoy": "accuse the angry decoy",
    "accuse_most_logs": "accuse the heaviest access-log user",
    "garbage_args": "malformed args on every tool (None, lists, wildcards, unicode ids, huge/neg days, extras)",
    "accuse_all_sequential": "accuse every employee one after another",
    "accuse_all_parallel": "accuse every employee at once from parallel threads",
    "accuse_after_end": "play until the episode ends, then accuse everyone",
    "calls_past_cap": "burn the tool-call cap on reads, then accuse everyone",
    "canary_per_person": "one canary variant per person (max_variants must reject), then accuse the leaker",
    "solver_cut_25": "solver trajectory, stopped after 25% of its calls",
    "solver_cut_50": "solver trajectory, stopped after 50% of its calls",
    "solver_cut_75": "solver trajectory, stopped after 75% of its calls",
    "solver_minus_accuse": "solver trajectory without its final accuse",
    CONTROL: "solver, then pad every remaining call with reads (must equal the solver)",
}


# ----------------------------------------------------------------------------- helpers
def _ids(env) -> list[str]:
    r = env.call("list_employees", {})
    return [e["id"] for e in (r.data or {}).get("employees", [])] if r.ok else []


def _run_until_done(env, max_calls: int = 5000) -> None:
    n = 0
    while not env.done and n < max_calls:
        env.call("advance_day", {})
        n += 1


def _garbage_values() -> list[Any]:
    return [None, [], "x", 0, -1, 10**18, float("nan"), float("inf"), True, {"$ne": None}, "*", "e00 ", "E00",
            "ｅ００", "e0​0", "../../etc/passwd", "e00;e01", ["e00"], {"employee": "e00"}, "\x00", "é" * 500]


def _garbage_calls(env, ids: list[str]) -> list[tuple[str, Any]]:
    from ..env import _SPECS
    calls: list[tuple[str, Any]] = []
    vals = _garbage_values()
    for tool, (_, props, req) in _SPECS.items():
        calls += [(tool, None), (tool, []), (tool, "employee=e00"), (tool, {"__proto__": 1}),
                  (tool, {**{k: 1 for k in req}, "zzz_extra": ids[0] if ids else "e00"})]
        for k in props:
            for v in vals:
                calls.append((tool, {k: v}))
        if "assignment" in props:
            calls += [(tool, {"doc_title": "q", "assignment": {"*": "a"}}),
                      (tool, {"doc_title": "q", "assignment": {i: ["a"] for i in ids}}),
                      (tool, {"doc_title": "", "assignment": {ids[0]: "a"}} if ids else (tool, {})),
                      (tool, {"doc_title": "q", "assignment": {i: "v" * 999 for i in ids}})]
    calls += [(None, {}), (123, {}), ("ACCUSE", {"employee": ids[0] if ids else "e00"}), ("accuse ", {}),
              ("_t_accuse", {"employee": ids[0] if ids else "e00"}), ("verdict", {}), ("score", {}),
              ("_end", {"reason": "accused"})]
    return calls


# ----------------------------------------------------------------------------- probes (env -> None)
def probe_garbage_args(env) -> dict:
    ids = _ids(env)
    ok_accuse = 0
    for tool, args in _garbage_calls(env, ids):
        if env.done:
            break
        r = env.call(tool, args)  # must never raise
        if r.ok and tool == "accuse":
            ok_accuse += 1
    return {"garbage_accepted_accuse": ok_accuse}


def probe_accuse_all_sequential(env) -> dict:
    ok = sum(1 for e in _ids(env) if env.call("accuse", {"employee": e}).ok)
    return {"accusations_accepted": ok}


def probe_accuse_all_parallel(env) -> dict:
    ids = _ids(env)
    oks: list[bool] = []
    barrier = threading.Barrier(len(ids)) if ids else None

    def go(e):
        barrier.wait()
        oks.append(env.call("accuse", {"employee": e}).ok)

    ts = [threading.Thread(target=go, args=(e,)) for e in ids]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return {"accusations_accepted": sum(oks)}


def probe_accuse_after_end(env) -> dict:
    ids = _ids(env)
    _run_until_done(env)
    return {"accusations_accepted": sum(1 for e in ids if env.call("accuse", {"employee": e}).ok)}


def probe_calls_past_cap(env) -> dict:
    ids = _ids(env)
    n = 0
    while not env.done and n < 100_000:
        env.call("status", {})
        n += 1
    return {"accusations_accepted": sum(1 for e in ids if env.call("accuse", {"employee": e}).ok)}


def probe_canary_per_person(env) -> dict:
    ids = _ids(env)
    r = env.call("plant_canary", {"doc_title": "Q3 board memo", "assignment": {e: f"v{i}" for i, e in enumerate(ids)}})
    accepted = bool(r.ok)
    variant_of = {f"v{i}": e for i, e in enumerate(ids)}
    target = None
    for _ in range(10):
        if env.done:
            break
        env.call("advance_day", {})
        feed = env.call("check_leak_feed", {})
        for it in (feed.data or {}).get("items", []) if feed.ok else []:
            v = it.get("variant") or it.get("variant_label")
            if v in variant_of:
                target = variant_of[v]
        if target:
            break
    if not env.done:
        env.call("accuse", {"employee": target or (ids[0] if ids else "e00")})
    return {"per_person_canary_accepted": accepted}


CUSTOM_PROBES: dict[str, Callable] = {
    "garbage_args": probe_garbage_args,
    "accuse_all_sequential": probe_accuse_all_sequential,
    "accuse_all_parallel": probe_accuse_all_parallel,
    "accuse_after_end": probe_accuse_after_end,
    "calls_past_cap": probe_calls_past_cap,
    "canary_per_person": probe_canary_per_person,
}


# ----------------------------------------------------------------------------- solver-derived probes
def solver_actions(tier: str, seed: int) -> tuple[list[tuple[str, dict]], float]:
    from ..eval import make_env, make_policy_factory, run_episode
    env = make_env(tier, seed)
    res = run_episode(env, make_policy_factory("solver")(seed))
    return [(s.tool, s.args) for s in res.steps], float(res.score)


def replay_actions(tier: str, seed: int, actions) -> Any:
    from ..eval import make_env
    env = make_env(tier, seed)
    for tool, args in actions:
        env.call(tool, args)
    return env


def ladder_envs(tier: str, seed: int, actions) -> dict[str, Any]:
    n = len(actions)
    out = {f"solver_cut_{p}": replay_actions(tier, seed, actions[: (n * p) // 100]) for p in (25, 50, 75)}
    acc = [i for i, (t, _) in enumerate(actions) if t == "accuse"]
    out["solver_minus_accuse"] = replay_actions(tier, seed, actions[: acc[-1]] if acc else actions)
    return out


def control_env(tier: str, seed: int, actions) -> Any:
    env = replay_actions(tier, seed, actions)
    reads = ("status", "list_employees", "check_leak_feed")
    for i in range(env.p.tool_call_cap + 5):
        env.call(reads[i % 3], {})
    return env


# ----------------------------------------------------------------------------- battery
def _stats(scores: list[float]) -> tuple[float, float]:
    n = len(scores)
    if not n:
        return 0.0, 0.0
    m = sum(scores) / n
    if n < 2:
        return m, 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in scores) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def run_battery(tiers, seeds, quiet: bool = True) -> dict:
    """All probes on (tier, seed). Call under the same world secret as the judge table."""
    from ..eval import make_env, make_policy_factory, run_episode
    per: dict[tuple[str, str], dict] = {}

    def rec(tier, name, seed, score, extra=None, error=None):
        d = per.setdefault((tier, name), {"tier": tier, "probe": name, "scores": [], "seeds": [], "errors": [],
                                          "extra": {}})
        d["scores"].append(round(float(score), 10))
        d["seeds"].append(seed)
        if error:
            d["errors"].append(f"{seed}: {error}")
        for k, v in (extra or {}).items():
            d["extra"][k] = d["extra"].get(k, 0) + int(v)

    for tier in tiers:
        for seed in seeds:
            for name in BASELINE_PROBES:
                try:
                    r = run_episode(make_env(tier, seed), make_policy_factory(name)(seed))
                    rec(tier, name, seed, r.score)
                except Exception as exc:  # a crash is a failure, never a pass
                    rec(tier, name, seed, 0.0, error=f"{type(exc).__name__}: {exc}")
            for name, fn in CUSTOM_PROBES.items():
                env = make_env(tier, seed)
                try:
                    extra = fn(env)
                    rec(tier, name, seed, env.score(), extra)
                except Exception as exc:
                    rec(tier, name, seed, env.score(), error=f"{type(exc).__name__}: {exc}")
            actions, s_score = solver_actions(tier, seed)
            rec(tier, "solver", seed, s_score)
            for name, env in ladder_envs(tier, seed, actions).items():
                rec(tier, name, seed, env.score())
            c = control_env(tier, seed, actions)
            rec(tier, CONTROL, seed, c.score(), {"drift": abs(c.score() - s_score) > 1e-9})

    rows = []
    for (tier, name), d in per.items():
        m, ci = _stats(d["scores"])
        if name == "solver":
            kind, blocked = "reference", None
        elif name == CONTROL:
            kind, blocked = "control", d["extra"].get("drift", 0) == 0 and not d["errors"]
        else:
            kind = "ladder" if name in LADDER else "attack"
            blocked = m <= 0 and not d["errors"]
            if name in SCRIPTED_ALWAYS_ZERO:
                blocked = blocked and all(x == 0 for x in d["scores"])
            if d["extra"].get("garbage_accepted_accuse") or d["extra"].get("per_person_canary_accepted"):
                blocked = False
            if d["extra"].get("accusations_accepted", 0) > len(d["scores"]):
                blocked = False   # more than one accepted accusation in some episode
        rows.append({"tier": tier, "probe": name, "kind": kind, "n": len(d["scores"]), "mean": round(m, 4),
                     "ci95": round(ci, 4), "max": max(d["scores"]), "positive": sum(1 for x in d["scores"] if x > 0),
                     "blocked": blocked, "errors": d["errors"][:5], "extra": d["extra"],
                     "note": PROBE_NOTES.get(name, "reference: solver")})
    return {"rows": rows, "all_blocked": all(r["blocked"] for r in rows if r["blocked"] is not None)}


# ----------------------------------------------------------------------------- replay consistency
def replay_committed(root: Path = ROOT) -> list[dict]:
    """Re-play every committed episode on a fresh Env and re-grade it."""
    from .. import rules
    from ..env import Env
    from ..reproduce import committed_files, run_meta, run_tiers_version
    out = []
    secret_seeds = set(rules.JUDGE_SEEDS) | set(getattr(rules, "HELDOUT_SEEDS", ()))
    for f in committed_files(root):
        meta = run_meta(f.parent)
        version = run_tiers_version(f.parent, root, meta)
        row = {"file": str(f.relative_to(root)), "tiers_version": version, "n": 0, "replayed": 0,
               "consistent": 0, "not_replayable": 0, "mismatches": []}
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            row["n"] += 1
            seed, tier = int(e["seed"]), e["tier"]
            if seed in secret_seeds:
                row["not_replayable"] += 1
                continue
            if version not in rules.TIERS_HISTORY and version != rules.TIERS_VERSION:
                row["not_replayable"] += 1
                row.setdefault("why", f"tier params for {version} are not frozen in rules.TIERS_HISTORY")
                continue
            with rules.tiers_version(version):
                env = Env(tier, seed)
                for st in e.get("steps", []):
                    env.call(st["tool"], st["args"])
                got, acc = env.score(), env.verdict()["accused"]
            row["replayed"] += 1
            if abs(got - float(e["score"])) < 1e-6 and acc == e.get("accused"):
                row["consistent"] += 1
            else:
                row["mismatches"].append({"seed": seed, "recorded": e["score"], "replayed": got,
                                          "accused_recorded": e.get("accused"), "accused_replayed": acc})
        row["replay_consistent"] = (None if row["replayed"] == 0 else not row["mismatches"])
        out.append(row)
    return out


# ----------------------------------------------------------------------------- output
def table_md(battery: dict, replay: list[dict] | None) -> str:
    L = ["## Anti-cheat battery (same seeds and secret as the judge table)", "",
         "| tier | probe | kind | n | mean ± 95% CI | max | episodes > 0 | blocked |", "|---|---|---|---|---|---|---|---|"]
    for r in battery["rows"]:
        b = {True: "yes", False: "**NO**", None: "-"}[r["blocked"]]
        L.append(f"| {r['tier']} | `{r['probe']}` | {r['kind']} | {r['n']} | {r['mean']:+.3f} ± {r['ci95']:.3f} "
                 f"| {r['max']:+.3f} | {r['positive']} | {b} |")
    L.append("")
    L.append(f"All probes blocked: **{'yes' if battery['all_blocked'] else 'NO'}** "
             "(attack mean ≤ 0; ladder and always-zero probes exactly 0 on every seed; control = solver on every seed).")
    if battery["rows"] and min(r["n"] for r in battery["rows"]) < 20:
        L.append("Fast mode (< 20 seeds): a chance-level guesser can average > 0 by luck; judge with the full 40 seeds "
                 "(e.g. easy accuse_most_logs is −0.67 over 200 dev seeds).")
    if replay is not None:
        L += ["", "## Replay consistency (committed episodes re-played on a fresh Env and re-graded)", "",
              "| file | version | episodes | replayed | consistent | not replayable | replay_consistent |",
              "|---|---|---|---|---|---|---|"]
        for r in replay:
            rc = {True: "yes", False: "**NO**"}.get(r["replay_consistent"]) or (
                "n/a: " + ("v" + r["tiers_version"][1:] + " params not frozen" if r.get("why") else "secret-keyed seeds"))
            L.append(f"| `{r['file']}` | {r['tiers_version']} | {r['n']} | {r['replayed']} | {r['consistent']} "
                     f"| {r['not_replayable']} | {rc} |")
    return "\n".join(L) + "\n"


def run_and_write(tiers, seeds, out_dir: Path, replay: bool = True, quiet: bool = False) -> dict:
    battery = run_battery(tiers, seeds)
    rep = replay_committed() if replay else None
    payload = {"seeds": [seeds[0], seeds[-1], len(seeds)], "tiers": list(tiers), **battery, "replay": rep,
               "replay_all_consistent": None if rep is None else all(r["replay_consistent"] is not False for r in rep)}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "exploits.json").write_text(json.dumps(payload, indent=1, sort_keys=True, default=str))
    md = table_md(battery, rep)
    (out_dir / "exploits.md").write_text(md)
    if not quiet:
        print(md)
        print(f"wrote {out_dir / 'exploits.json'}")
    return payload


def main(argv=None) -> int:
    from .. import rules
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=10, help="dev seeds 0..N-1 (default 10)")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--judge", action="store_true", help="use the judge seeds (needs CANARY_WORLD_SECRET for exact numbers)")
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--out", default="results/latest")
    a = ap.parse_args(argv)
    seeds = list(rules.JUDGE_SEEDS)[: a.seeds] if a.judge else list(range(a.seeds))
    p = run_and_write(a.tiers.split(","), seeds, ROOT / a.out, replay=not a.no_replay)
    return 0 if p["all_blocked"] and p["replay_all_consistent"] is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
