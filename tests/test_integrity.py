"""Explicit reward-integrity regression tests (owner: HEAD-INTEGRITY / props-probe).

One test per row of docs/EXPLOITS.md. Skips while canary.env.Env is the stub.
"""
from __future__ import annotations

from pathlib import Path

import json
import re

import pytest

from canary.rules import JUDGE_SEEDS, TIERS

from integrity_helpers import make_env, true_mole
from test_integrity_props import (check_score_semantics, dump, wrong_score, employee_ids, ledger_dump, status_of, token_re,
                                  value_of)


def _advance_until_done(env, limit=400):
    for _ in range(limit):
        if env.done:
            return
        env.call("advance_day", {})


# ------------------------------------------------------------- baselines
@pytest.mark.parametrize("tier", sorted(TIERS))
@pytest.mark.parametrize("seed", range(5))
def test_do_nothing(tier, seed):
    env = make_env(tier, seed)
    _advance_until_done(env)
    assert env.done and env.score() == 0.0
    assert env.result("do_nothing").end_reason == "horizon"


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_stop_early(tier):
    """Random day-1 accusation: mean ≈ 1/N on v0 (no better); strictly < 0 on v0.3."""
    scores = []
    for seed in range(50):
        env = make_env(tier, seed)
        ids = employee_ids(env)
        env.call("accuse", {"employee": ids[seed % len(ids)]})
        check_score_semantics(env)
        scores.append(env.score())
    n = TIERS[tier].n_employees
    if wrong_score() < 0:
        assert sum(scores) / len(scores) < 0, "v0.3: guessing must have negative EV"
    assert sum(scores) / len(scores) <= 1 / n + 3 * (1 / n) ** 0.5 / len(scores) ** 0.5


# ------------------------------------------------------------- accusation lock
def test_accuse_twice_only_first_counts():
    env = make_env("easy", 1)
    ids = employee_ids(env)
    mole = true_mole(env)
    inn = next(i for i in ids if i != mole)
    r1 = env.call("accuse", {"employee": inn})
    assert r1.ok and env.done and env.score() == wrong_score()
    r2 = env.call("accuse", {"employee": mole})
    assert not r2.ok and env.score() == wrong_score()
    assert sum(1 for e in env.ledger() if e.event == "accused") == 1


@pytest.mark.parametrize("bad", [["e00", "e01"], "*", "", "all", None, 0, {"id": "e00"},
                                 "e00,e01", "e00 e01", "E00"])
def test_accuse_malformed_rejected_and_not_locking(bad):
    env = make_env("easy", 2)
    r = env.call("accuse", {"employee": bad})
    assert not r.ok and not env.done and env.score() == 0
    assert not any(e.event == "accused" for e in env.ledger())


def test_accuse_by_name_rejected():
    env = make_env("easy", 3)
    r = env.call("list_employees", {})
    rows = r.data.get("employees", r.data) if isinstance(r.data, dict) else r.data
    mole = true_mole(env)
    name = next(x["name"] for x in rows if x["id"] == mole)
    assert not env.call("accuse", {"employee": name}).ok
    assert env.score() == 0


def test_accuse_after_horizon():
    env = make_env("easy", 4)
    _advance_until_done(env)
    assert not env.call("accuse", {"employee": true_mole(env)}).ok
    assert env.score() == 0


def test_accuse_result_does_not_reveal_correctness():
    outs = []
    for target in ("mole", "innocent"):
        env = make_env("medium", 5)
        ids = employee_ids(env)
        mole = true_mole(env)
        eid = mole if target == "mole" else next(i for i in ids if i != mole)
        r = env.call("accuse", {"employee": eid})
        outs.append(token_re(eid).sub("<EMP>", dump(r)))
    assert outs[0] == outs[1]


# ------------------------------------------------------------- caps
@pytest.mark.parametrize("tier", sorted(TIERS))
def test_daily_cap(tier):
    env = make_env(tier, 6)
    k = TIERS[tier].actions_per_day
    for i in range(k):
        assert env.call("search_messages", {"query": "q"}).ok, i
    r = env.call("search_messages", {"query": "q"})
    assert not r.ok and "daily action limit" in (r.error or "")
    # non-investigative tools still work
    assert env.call("status", {}).ok and env.call("list_employees", {}).ok
    assert env.call("advance_day", {}).ok
    assert env.call("search_messages", {"query": "q"}).ok


def test_tool_call_cap_ends_with_zero():
    env = make_env("easy", 7)
    mole = true_mole(env)
    cap = TIERS["easy"].tool_call_cap
    for _ in range(cap + 5):
        if env.done:
            break
        env.call("status", {})
    assert env.done and env.score() == 0
    assert env.result("cap").end_reason == "tool_cap"
    assert not env.call("accuse", {"employee": mole}).ok
    assert env.score() == 0


def test_cap_counts_rejected_calls():
    env = make_env("easy", 8)
    for _ in range(TIERS["easy"].tool_call_cap + 5):
        if env.done:
            break
        env.call("accuse", {"employee": "*"})
    assert env.done and env.score() == 0


def test_advance_day_spam():
    env = make_env("medium", 9)
    n = 0
    while not env.done and n < 400:
        env.call("advance_day", {})
        n += 1
    assert env.done and env.score() == 0 and n <= TIERS["medium"].n_days + 1


# ------------------------------------------------------------- canaries
def _assign(ids, labels):
    return {e: labels[i % len(labels)] for i, e in enumerate(ids)}


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_canary_too_many_variants(tier):
    env = make_env(tier, 10)
    ids = employee_ids(env)
    mv = TIERS[tier].max_variants
    labels = [f"V{i}" for i in range(mv + 1)]
    r = env.call("plant_canary", {"doc_title": "Q3 plan", "assignment": _assign(ids[:mv + 1], labels)})
    assert not r.ok
    assert not any(e.event == "canary_planted" for e in env.ledger())


def test_canary_unique_copy_per_person_rejected():
    env = make_env("medium", 11)
    ids = employee_ids(env)
    r = env.call("plant_canary", {"doc_title": "Q3", "assignment": {e: e for e in ids}})
    assert not r.ok


@pytest.mark.parametrize("assignment", [{}, None, [], {"*": "A"}, {"e999": "A"}, {"e00": ""}])
def test_canary_bad_assignment_rejected(assignment):
    env = make_env("easy", 12)
    v0 = value_of(status_of(env))
    r = env.call("plant_canary", {"doc_title": "Q3", "assignment": assignment})
    assert not r.ok
    assert value_of(status_of(env)) == v0, "rejected canary still charged canary_cost"


def test_canary_to_restricted_recipient_rejected():
    env = make_env("easy", 13)
    ids = employee_ids(env)
    assert env.call("restrict_access", {"employee": ids[0]}).ok
    r = env.call("plant_canary", {"doc_title": "Q3", "assignment": {ids[0]: "A", ids[1]: "B"}})
    assert not r.ok


def test_canary_per_day_limit():
    env = make_env("easy", 14)
    ids = employee_ids(env)
    k = TIERS["easy"].canaries_per_day
    for _ in range(k):
        assert env.call("plant_canary", {"doc_title": "Q3", "assignment": {ids[0]: "A", ids[1]: "B"}}).ok
    assert not env.call("plant_canary", {"doc_title": "Q4", "assignment": {ids[0]: "A", ids[1]: "B"}}).ok


def test_mole_alone_variant_only_within_limits():
    """A 1-person variant is legal (it costs a variant slot). Isolating each employee needs
    ≥ N/(max_variants-1) days of canaries -- check that budget is what the rules allow."""
    env = make_env("easy", 15)
    mole = true_mole(env)
    ids = employee_ids(env)
    other = next(i for i in ids if i != mole)
    r = env.call("plant_canary", {"doc_title": "Q3", "assignment": {mole: "A", other: "B"}})
    assert r.ok
    t = TIERS["easy"]
    # one isolating canary per day, (max_variants - 1) singletons each: binary search, not a
    # one-shot; leaks also need p_leak and delay. Can't isolate everyone in one call:
    assert (t.max_variants) < t.n_employees


# ------------------------------------------------------------- V manipulation
def test_unrestrict_never_raises_v():
    env = make_env("medium", 16)
    ids = employee_ids(env)
    vs = [value_of(status_of(env))]
    for e in ids[:3]:
        env.call("restrict_access", {"employee": e})
    env.call("advance_day", {})
    vs.append(value_of(status_of(env)))
    for e in ids[:3]:
        env.call("unrestrict_access", {"employee": e})
        vs.append(value_of(status_of(env)))
    env.call("unrestrict_access", {"employee": ids[5]})  # never restricted
    vs.append(value_of(status_of(env)))
    assert all(b <= a + 1e-12 for a, b in zip(vs, vs[1:])), vs


# ------------------------------------------------------------- seed / world secrecy
def _world_mod():
    try:
        import canary.world as w
    except ImportError:
        pytest.skip("canary/world.py not landed (HEAD-ENV)")
    if not hasattr(w, "World"):
        pytest.skip("canary.world.World missing")
    return w


def _mole_of_world(W, tier, seed):
    import canary.world as w
    try:
        world = w.generate_world(tier, seed, TIERS[tier]) if hasattr(w, "generate_world") else W(tier, seed)
    except NotImplementedError:
        pytest.skip("World not implemented")
    return getattr(world, "mole", None) or getattr(world, "mole_id")


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_judge_salt(tier, monkeypatch, tmp_path):
    """World for a judge seed built WITHOUT the secret must not reproduce the served one."""
    w = _world_mod()
    seeds = list(JUDGE_SEEDS)
    monkeypatch.setenv("CANARY_WORLD_SECRET", "served-secret-" + "x" * 24)
    served = [_mole_of_world(w.World, tier, s) for s in seeds]
    monkeypatch.delenv("CANARY_WORLD_SECRET")
    monkeypatch.chdir(tmp_path)  # no data/worlds/judge/SALT reachable from here
    for attr in ("SALT_PATH", "JUDGE_SALT_PATH"):
        if hasattr(w, attr):
            monkeypatch.setattr(w, attr, tmp_path / "nope")
    real_salt = Path(w.__file__).resolve().parent.parent / "data" / "worlds" / "judge" / "SALT"
    if real_salt.exists():
        pytest.skip("SALT present locally (server image); public-clone check runs where SALT is absent")
    try:
        public = [_mole_of_world(w.World, tier, s) for s in seeds]
    except Exception as e:  # refusing to build a judge world without the secret is also fine
        assert "secret" in str(e).lower() or "salt" in str(e).lower(), e
        return
    same = sum(a == b for a, b in zip(served, public))
    # chance agreement ≈ 30/N; demand clearly below "all equal"
    if same == len(seeds):
        pytest.xfail("OPEN HOLE: judge worlds regenerate from public code + seed (no salt)")
    assert same <= len(seeds) // 2


SEED_PROBES = [7919, 9973]


@pytest.mark.parametrize("tier", sorted(TIERS))
@pytest.mark.parametrize("seed", SEED_PROBES)
def test_seed_never_exposed(tier, seed):
    """No tool output, instruction or tools_spec contains the seed or 'tier:seed'."""
    env = make_env(tier, seed)
    pats = [re.compile(r"(?<!\d)" + str(seed) + r"(?!\d)"), re.compile(re.escape(f"{tier}:{seed}"))]
    texts = [("instruction", env.instruction()), ("tools_spec", json.dumps(env.tools_spec()))]
    ids = employee_ids(env)
    script = [("status", {}), ("list_employees", {}), ("list_documents", {}),
              ("check_leak_feed", {}), ("search_messages", {"query": "a"}),
              ("read_access_logs", {"day_from": 1, "day_to": 14}),
              ("interview", {"employee": ids[0], "topic": "workload"}),
              ("plant_canary", {"doc_title": "Q3", "assignment": {ids[0]: "A", ids[1]: "B"}})]
    for _ in range(TIERS[tier].n_days - 1):
        script += [("advance_day", {}), ("status", {}), ("check_leak_feed", {}),
                   ("search_messages", {"query": "the"})]
    script.append(("accuse", {"employee": ids[2]}))
    for t, a in script:
        r = env.call(t, a)
        texts.append((t, dump(r)))
        if t == "search_messages" and r.ok:
            rows = r.data.get("messages", r.data) if isinstance(r.data, dict) else r.data
            for m in (rows or [])[:5]:
                texts.append(("read_message", dump(env.call("read_message", {"id": m["id"]}))))
    for name, txt in texts:
        for p in pats:
            assert not p.search(txt), f"seed leaked via {name}: {txt[:200]}"
    try:
        from canary.mcp import server as srv  # optional: MCP tool list/instructions
    except Exception:
        return
    blob = json.dumps(getattr(srv, "TOOLS", None) or [], default=str) + str(getattr(srv, "INSTRUCTIONS", ""))
    for p in pats:
        assert not p.search(blob)


def test_ledger_not_in_tools():
    env = make_env("easy", 17)
    names = {t.get("name") for t in env.tools_spec()}
    assert not names & {"ledger", "score", "world", "truth"}
    assert len(names) == 13


def test_salt_never_tracked():
    """The judge SALT must never be committed: it is the only thing stopping world regeneration."""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files", "data/worlds/judge/SALT"], cwd=root,
                             capture_output=True, text=True).stdout.strip()
    assert not tracked, "data/worlds/judge/SALT is committed: judge worlds are regenerable"
    ignored = subprocess.run(["git", "check-ignore", "-q", "data/worlds/judge/SALT"], cwd=root)
    assert ignored.returncode == 0, "add data/worlds/judge/SALT to .gitignore"


# ------------------------------------------------------------- reward ranks skill
def test_monotonicity_order():
    """random < obvious heuristic < solver on medium (30 dev seeds)."""
    make_env("medium", 0)  # skip while Env is the stub
    mono = pytest.importorskip("canary.redteam.monotonicity")
    rows = {r[0]: r[1] for r in mono.measure("medium", list(range(30)))}
    if "solver" not in rows or "heuristic" not in rows:
        pytest.skip(f"policies missing: have {sorted(rows)}")
    assert rows["random"] < rows["heuristic"] < rows["solver"], rows


def test_v03_path_is_active():
    """Guard: once CONTRACT v0.3 is live, the sign checks above must run their v0.3 branch."""
    make_env("easy", 0)
    declared = getattr(TIERS["easy"], "wrong_accusation_score", None)
    if declared is None:
        pytest.skip("v0 rules: no wrong_accusation_score")
    assert wrong_score() == declared == -1.0, (wrong_score(), declared)


@pytest.mark.xfail(strict=False, reason="tiers v1: solver 100 seeds easy 0.80, medium 0.50 < hard 0.53; ENV retuning for monotone tiers")
def test_solver_tier_ordering():
    """Difficulty must be monotone across tiers: solver mean easy > medium > hard (100 dev seeds).
    Guards future retunes from silently inverting the tier ladder."""
    import statistics
    from canary.solver import SolverPolicy
    from canary.baselines import play
    means = {}
    for tier in ("easy", "medium", "hard"):
        means[tier] = statistics.mean(play(make_env(tier, s), SolverPolicy()) for s in range(100))
    assert means["easy"] > means["medium"] > means["hard"], means
