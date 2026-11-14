"""Anti-cheat battery (owner: HEAD-INTEGRITY). Ported from Poisoned Inbox (`pinbox/eval.py`: run_probes,
SCRIPTED_ALWAYS_ZERO, run_recorded/replay; design by Vaishnav) onto Canary.

Runs inside `make reproduce` on the same judge seeds and world secret as the judge table:

  * attack probes   scripted cheats that act only through `env.call`; each must have mean score <= 0
                    (a wrong accusation is -1, so a guesser goes negative) and never raise;
  * stop-early ladder  the solver's own trajectory cut at 25/50/75% of its calls, and the solver minus
                    its final accuse; every episode must score exactly 0 (no accusation means 0);
  * control         the solver, then every remaining call padded with reads; must equal the solver per seed;
  * plus            the solver with one extra step slipped in before its final accuse (restrict everyone else,
                    unrestrict spam, interview everyone, spam every read tool, wait one more day, accuse twice,
                    a rejected per-person canary): no extra step may score above the solver on any seed
                    (Poisoned Inbox X10/X17/X18: "do the job right, then one more thing");
  * replay          every committed episode under data/runs/committed (superseded excluded) is re-played
                    on a fresh Env (same tier version and seed) and re-graded; judge/held-out seeds use a
                    server-side secret that is not committed, so those rows are flagged not-replayable;
  * harbor          every committed Harbor trial (results/harbor/<job>/<trial>/) must agree with itself: Harbor's
                    reward = verifier/reward.txt = the sidecar ledger = the verifier's copy; the ledger score
                    follows from its own accusation (V if right, the wrong-accusation score if wrong, 0 if none);
                    at most one accusation; and the agent's own trajectory names the same person. Those worlds
                    use a per-build secret, so they cannot be re-played; this catches an edited result file.

    uv run python -m canary.redteam.anticheat [--seeds N] [--tiers medium,hard] [--no-replay]

Writes exploits.json next to the judge table. `tests/test_anticheat.py` fails if any attack probe mean > 0,
any ladder episode != 0, the control drifts from the solver, a plus probe beats the solver on any seed, any
episode accepts two accusations, or any replayable committed episode mismatches.
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
PLUS = ("solver_plus_restrict_others", "solver_plus_unrestrict_spam", "solver_plus_interview_all",
        "solver_plus_read_spam", "solver_plus_wait_a_day", "solver_plus_accuse_twice", "solver_plus_bad_canary")
# Every probe whose episodes must score exactly 0 (not just mean <= 0): the Poisoned Inbox SCRIPTED_ALWAYS_ZERO.
SCRIPTED_ALWAYS_ZERO = ("do_nothing", "stop_early", "garbage_args", "accuse_after_end", "calls_past_cap") + LADDER

PROBE_NOTES = {
    "do_nothing": "never accuses",
    "stop_early": "stops on day 1 without accusing (score 0); day-1 accusation is guess_day1",
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
    "solver_plus_restrict_others": "solver, but restrict everyone else just before accusing (must be <= solver)",
    "solver_plus_unrestrict_spam": "solver, plus unrestrict_access on everyone before accusing (<= solver)",
    "solver_plus_interview_all": "solver, plus interview everyone before accusing (<= solver)",
    "solver_plus_read_spam": "solver, plus every read tool before accusing (<= solver)",
    "solver_plus_wait_a_day": "solver, but advance one more day before accusing (<= solver)",
    "solver_plus_accuse_twice": "solver, then accuse the same person again (<= solver, one accusation)",
    "solver_plus_bad_canary": "solver, plus a per-person canary (must be rejected) before accusing (<= solver)",
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


def _extra_calls(name: str, ids: list[str], target: str | None) -> list[tuple[str, dict]]:
    others = [e for e in ids if e != target]
    if name == "solver_plus_restrict_others":
        return [("restrict_access", {"employee": e}) for e in others]
    if name == "solver_plus_unrestrict_spam":
        return [("unrestrict_access", {"employee": e}) for e in ids]
    if name == "solver_plus_interview_all":
        return [("interview", {"employee": e, "topic": "leaks"}) for e in ids]
    if name == "solver_plus_read_spam":
        return [("status", {}), ("list_employees", {}), ("check_leak_feed", {}),
                ("list_documents", {"day_from": 1, "day_to": 1}), ("read_access_logs", {"day_from": 1, "day_to": 1}),
                ("search_messages", {"query": "board"})]
    if name == "solver_plus_wait_a_day":
        return [("advance_day", {})]
    if name == "solver_plus_bad_canary":
        return [("plant_canary", {"doc_title": "Q3 board memo", "assignment": {e: f"v{i}" for i, e in enumerate(ids)}})]
    return []


def plus_envs(tier: str, seed: int, actions) -> dict[str, tuple[Any, int]]:
    """Solver trajectory with one extra step before its final accuse. Returns name -> (env, accusations accepted)."""
    acc = [i for i, (t, _) in enumerate(actions) if t == "accuse"]
    # a solver episode with no accusation (horizon / cap) gets the extra step at its end and no accuse
    head, final = (actions[: acc[-1]], actions[acc[-1]]) if acc else (list(actions), None)
    target = final[1].get("employee") if final and isinstance(final[1], dict) else None
    out = {}
    for name in PLUS:
        env = replay_actions(tier, seed, head)
        ids = _ids(env)
        for tool, args in _extra_calls(name, ids, target):
            if env.done:
                break
            env.call(tool, args)
        n_ok = 0
        if final is not None:
            n_ok = int(env.call(*final).ok)
            if name == "solver_plus_accuse_twice":
                n_ok += int(env.call(*final).ok)
        out[name] = (env, n_ok)
    return out


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
            if k == "accusations_accepted":   # per-episode worst case, not only the total
                d["extra"]["max_" + k] = max(d["extra"].get("max_" + k, 0), int(v))

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
            for name, (env, n_ok) in plus_envs(tier, seed, actions).items():
                rec(tier, name, seed, env.score(), {"above_solver": env.score() > s_score + 1e-9,
                                                     "accusations_accepted": n_ok})

    rows = []
    for (tier, name), d in per.items():
        m, ci = _stats(d["scores"])
        if name == "solver":
            kind, blocked = "reference", None
        elif name == CONTROL:
            kind, blocked = "control", d["extra"].get("drift", 0) == 0 and not d["errors"]
        elif name in PLUS:
            kind = "plus"
            blocked = (d["extra"].get("above_solver", 0) == 0 and d["extra"].get("max_accusations_accepted", 0) <= 1
                       and not d["errors"])
        else:
            kind = "ladder" if name in LADDER else "attack"
            blocked = m <= 0 and not d["errors"]
            if name in SCRIPTED_ALWAYS_ZERO:
                blocked = blocked and all(x == 0 for x in d["scores"])
            if d["extra"].get("garbage_accepted_accuse") or d["extra"].get("per_person_canary_accepted"):
                blocked = False
            if d["extra"].get("max_accusations_accepted", 0) > 1:
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


def replay_counts(replay: list[dict]) -> dict:
    return {k: sum(r[k] for r in replay) for k in ("n", "replayed", "consistent", "not_replayable")}


# ----------------------------------------------------------------------------- Harbor result consistency
def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _trajectory_accusations(path: Path) -> list[str]:
    """Employees named in successful accuse calls of an ATIF trajectory (agent/trajectory.json)."""
    out = []
    try:
        steps = json.loads(path.read_text(encoding="utf-8")).get("steps", [])
    except Exception:  # noqa: BLE001
        return out
    for st in steps:
        obs = {o.get("source_call_id"): o.get("content") for o in (st.get("observation") or {}).get("results", [])}
        for c in st.get("tool_calls") or []:
            if not str(c.get("function_name", "")).endswith("accuse"):
                continue
            try:
                ok = json.loads(obs.get(c.get("tool_call_id")) or "{}").get("ok")
            except (TypeError, ValueError):
                ok = False
            if ok:
                out.append((c.get("arguments") or {}).get("employee"))
    return out


def check_harbor_trial(trial: Path) -> dict:
    from .. import rules
    row: dict[str, Any] = {"trial": trial.as_posix(), "reward": None, "consistent": None, "problems": [],
                           "trajectory_checked": False}
    try:
        res = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        row["problems"].append(f"result.json unreadable: {type(exc).__name__}")
        row["consistent"] = False
        return row
    reward = _num(((res.get("verifier_result") or {}).get("rewards") or {}).get("reward"))
    if reward is None:
        row["why"] = "no verifier reward (infrastructure failure; not counted as a result)"
        return row
    row["reward"] = reward
    probs = row["problems"]
    vals = {"result.json": reward}
    if (trial / "verifier/reward.txt").is_file():
        vals["verifier/reward.txt"] = _num((trial / "verifier/reward.txt").read_text().strip())
    led = None
    for name in ("artifacts/ledger.json", "verifier/ledger.json"):
        f = trial / name
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                probs.append(f"{name} is not JSON")
                continue
            vals[name] = _num(d.get("score"))
            led = led or (d if name == "artifacts/ledger.json" else None)
    if "artifacts/ledger.json" not in vals:
        probs.append("no sidecar ledger (artifacts/ledger.json)")
    for k, v in vals.items():
        if v is None or abs(v - reward) > 1e-6:
            probs.append(f"{k} says {v}, Harbor reward is {reward}")
    if led is not None:
        acc = [e for e in led.get("ledger", []) if e.get("event") == "accused"]
        if len(acc) > 1:
            probs.append(f"{len(acc)} accusations in one ledger")
        if acc:
            d = acc[-1].get("detail") or {}
            try:
                wrong = float(rules.tier_params(str(led.get("tier"))).wrong_accusation_score)
            except Exception:  # noqa: BLE001
                wrong = -1.0
            want = round(float(d.get("V", 0.0)), 10) if d.get("correct") else wrong
            if abs(want - float(led.get("score", 0.0))) > 1e-6:
                probs.append(f"ledger score {led.get('score')} does not follow from its accusation (expected {want})")
            if led.get("accused") != d.get("employee"):
                probs.append(f"ledger accused {led.get('accused')} but its event names {d.get('employee')}")
        elif abs(float(led.get("score", 0.0))) > 1e-9:
            probs.append(f"no accusation but score {led.get('score')}")
        traj = trial / "agent/trajectory.json"
        if traj.is_file():
            named = _trajectory_accusations(traj)
            row["trajectory_checked"] = True
            if named and named[-1] != led.get("accused"):
                probs.append(f"agent trajectory accused {named[-1]}, ledger says {led.get('accused')}")
            if not named and led.get("accused") is not None:
                probs.append(f"ledger has an accusation ({led.get('accused')}) the agent trajectory never made")
    row["consistent"] = not probs
    return row


def harbor_consistency(root: Path = ROOT) -> list[dict]:
    base = root / "results" / "harbor"
    rows = []
    for res in sorted(base.glob("*/*/result.json")):
        r = check_harbor_trial(res.parent)
        r["trial"] = res.parent.relative_to(root).as_posix()
        rows.append(r)
    return rows


def harbor_md(rows: list[dict]) -> str:
    ok = sum(1 for r in rows if r["consistent"] is True)
    bad = [r for r in rows if r["consistent"] is False]
    skip = sum(1 for r in rows if r["consistent"] is None)
    traj = sum(1 for r in rows if r["trajectory_checked"])
    L = ["## Harbor result consistency (committed trials under results/harbor/)", "",
         f"**{ok} of {len(rows)} trials consistent** (Harbor reward = reward.txt = sidecar ledger = verifier copy; "
         f"ledger score follows from its accusation; at most one accusation; {traj} checked against the agent's "
         f"own trajectory). {skip} without a verifier reward (infrastructure failures, not results)."]
    for r in bad:
        L.append(f"- **NO** `{r['trial']}`: {'; '.join(r['problems'][:3])}")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- output
def table_md(battery: dict, replay: list[dict] | None, harbor: list[dict] | None = None) -> str:
    L = ["## Anti-cheat battery (same world secret as the judge table)", ""]
    if battery.get("verdict_note"):
        L += [battery["verdict_note"], ""]
    L += ["| tier | probe | kind | n | mean ± 95% CI | max | episodes > 0 | blocked |", "|---|---|---|---|---|---|---|---|"]
    for r in battery["rows"]:
        b = {True: "yes", False: "**NO**", None: "-"}[r["blocked"]]
        L.append(f"| {r['tier']} | `{r['probe']}` | {r['kind']} | {r['n']} | {r['mean']:+.3f} ± {r['ci95']:.3f} "
                 f"| {r['max']:+.3f} | {r['positive']} | {b} |")
    L.append("")
    L.append(f"All probes blocked: **{'yes' if battery['all_blocked'] else 'NO'}** "
             "(attack mean <= 0; ladder and always-zero probes exactly 0 on every seed; control = solver on every seed; "
             "plus probes <= solver on every seed; never two accepted accusations in one episode).")
    if battery["rows"] and min(r["n"] for r in battery["rows"]) < 20:
        L.append("Fast mode (< 20 seeds): a chance-level guesser can average > 0 by luck; judge with the full 40 seeds "
                 "(e.g. easy accuse_most_logs is -0.67 over 200 dev seeds).")
    if replay is not None:
        L += ["", "## Replay consistency (committed episodes re-played on a fresh Env and re-graded)", "",
              "| file | version | episodes | replayed | consistent | not replayable | replay_consistent |",
              "|---|---|---|---|---|---|---|"]
        for r in replay:
            rc = {True: "yes", False: "**NO**"}.get(r["replay_consistent"]) or (
                "n/a: " + ("v" + r["tiers_version"][1:] + " params not frozen" if r.get("why") else "secret-keyed seeds"))
            L.append(f"| `{r['file']}` | {r['tiers_version']} | {r['n']} | {r['replayed']} | {r['consistent']} "
                     f"| {r['not_replayable']} | {rc} |")
        L += ["", coverage_line(replay)]
    if harbor:
        L += ["", harbor_md(harbor)]
    return "\n".join(L) + "\n"


def coverage_line(replay: list[dict]) -> str:
    """One plain sentence on how much the replay check covered, so an empty check cannot pass quietly."""
    c = replay_counts(replay)
    why: dict[str, int] = {}
    for r in replay:
        if r["not_replayable"]:
            k = r.get("why") or "secret-keyed judge/held-out seeds (the world secret is not committed)"
            why[k] = why.get(k, 0) + r["not_replayable"]
    skipped = "; ".join(f"{v}: {k}" for k, v in sorted(why.items(), key=lambda kv: -kv[1]))
    head = (f"**Replay coverage: {c['replayed']} of {c['n']} committed episodes re-played, "
            f"{c['consistent']} consistent.**")
    if c["replayed"] == 0:
        head += " NOTHING was re-played, so this check proves nothing."
    return head + (f" Not replayable: {skipped}." if skipped else "")


def run_and_write(tiers, seeds, out_dir: Path, replay: bool = True, quiet: bool = False) -> dict:
    battery = run_battery(tiers, seeds)
    rep = replay_committed() if replay else None
    hb = harbor_consistency() if replay else None
    payload = {"seeds": [seeds[0], seeds[-1], len(seeds)], "tiers": list(tiers), **battery, "replay": rep,
               "replay_all_consistent": None if rep is None else all(r["replay_consistent"] is not False for r in rep),
               "replay_counts": None if rep is None else replay_counts(rep),
               "harbor": hb, "harbor_all_consistent": None if hb is None else all(r["consistent"] is not False for r in hb)}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "exploits.json").write_text(json.dumps(payload, indent=1, sort_keys=True, default=str),
                                           encoding="utf-8")
    md = table_md(battery, rep, hb)
    (out_dir / "exploits.md").write_text(md, encoding="utf-8")
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
    return 0 if p["all_blocked"] and p["replay_all_consistent"] is not False and p["harbor_all_consistent"] is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
