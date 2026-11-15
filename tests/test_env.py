import json
import random
import time
from dataclasses import asdict

import pytest

from canary.env import Env

TIERS = ["easy", "medium", "hard"]


def random_policy(env, rng, max_calls=400):
    ids = [f"e{i:02d}" for i in range(env.p.n_employees)]
    tools = ["status", "list_employees", "list_documents", "read_access_logs", "search_messages",
             "interview", "plant_canary", "check_leak_feed", "restrict_access", "unrestrict_access",
             "advance_day", "advance_day", "advance_day"]
    for _ in range(max_calls):
        if env.done:
            break
        t = rng.choice(tools)
        if rng.random() < 0.01:
            t = "accuse"
        a = {}
        if t in ("restrict_access", "unrestrict_access", "accuse"):
            a = {"employee": rng.choice(ids)}
        elif t == "interview":
            a = {"employee": rng.choice(ids), "topic": "workload"}
        elif t == "read_access_logs":
            a = {"day_from": 1, "day_to": env.day}
        elif t == "search_messages":
            a = {"query": rng.choice(["update", "fed up", "project"])}
        elif t == "plant_canary":
            a = {"doc_title": "Secret", "assignment": {e: rng.choice("AB") for e in rng.sample(ids, 4)}}
        env.call(t, a)


def run_script(tier, seed):
    env = Env(tier, seed)
    random_policy(env, random.Random(7))
    return env


@pytest.mark.parametrize("tier", TIERS)
def test_determinism(tier):
    a, b = run_script(tier, 3), run_script(tier, 3)
    assert [asdict(s) for s in a.history] == [asdict(s) for s in b.history]
    assert [asdict(x) for x in a.ledger()] == [asdict(x) for x in b.ledger()]


def test_do_nothing_horizon():
    env = Env("medium", 1)
    while not env.done:
        assert env.call("advance_day", {}).ok
    r = env.result("do_nothing")
    assert r.end_reason == "horizon" and r.score == 0 and r.final_day == env.p.n_days


def test_daily_cap():
    env = Env("easy", 1)
    for _ in range(env.p.actions_per_day):
        assert env.call("check_leak_feed", {}).ok
    r = env.call("check_leak_feed", {})
    assert not r.ok and r.error == "daily action limit; call advance_day"
    env.call("advance_day", {})
    assert env.call("check_leak_feed", {}).ok


def test_global_cap():
    env = Env("easy", 1)
    for _ in range(env.p.tool_call_cap):
        env.call("status", {})
    assert env.done and env.result("x").end_reason == "tool_cap" and env.score() == 0


def test_correct_accusation_and_lock():
    env = Env("hard", 5)
    env.call("advance_day", {})
    mole = env._world.mole
    r = env.call("accuse", {"employee": mole})
    assert r.ok and r.data == {"accused": mole, "episode_over": True}
    s = env.score()
    assert 0 < s <= 1
    r2 = env.call("accuse", {"employee": "e00"})
    assert not r2.ok and r2.error == "episode over" and env.score() == s
    n = len(env.ledger())
    assert not env.call("advance_day", {}).ok and len(env.ledger()) == n
    assert len(env.history) == 4


def test_wrong_accusation_negative():
    env = Env("easy", 5)
    wrong = next(e for e in env._world.ids if e != env._world.mole)
    env.call("accuse", {"employee": wrong})
    assert env.score() == -1.0 and env.done


@pytest.mark.parametrize("tool,args", [
    ("nope", {}), ("status", {"x": 1}), ("interview", {"employee": "e01"}),
    ("interview", {"employee": ["e01"], "topic": "workload"}), ("accuse", {"employee": "*"}),
    ("accuse", {"employee": "e1"}), ("restrict_access", {"employee": "Aino Virtanen"}),
    ("read_access_logs", {"day_from": "1", "day_to": 2}), ("read_access_logs", {"day_from": True, "day_to": 2}),
    ("read_access_logs", {"day_from": 3, "day_to": 2}), ("interview", {"employee": "e01", "topic": "x"}),
    ("plant_canary", {"doc_title": "", "assignment": {"e01": "A"}}),
    ("plant_canary", {"doc_title": "t", "assignment": {}}),
    ("plant_canary", {"doc_title": "t", "assignment": {"e01": "A", "e02": "B", "e03": "C", "e04": "D"}}),
    ("search_messages", {"query": "*"}), ("read_message", {"id": "zzz"}), ("status", None),
])
def test_validation(tool, args):
    env = Env("easy", 2)
    r = env.call(tool, args)
    assert not r.ok and (r.data == {} or set(r.data) == {"detail"}) and "mole" not in (r.error or "")
    assert "mole" not in str(r.data).lower()
    assert not env.done


def test_canary_rules():
    env = Env("medium", 4)
    assert env.call("restrict_access", {"employee": "e01"}).ok
    assert not env.call("restrict_access", {"employee": "e01"}).ok
    assert not env.call("plant_canary", {"doc_title": "t", "assignment": {"e01": "A"}}).ok
    r = env.call("plant_canary", {"doc_title": "t", "assignment": {"e02": "A", "e03": "B"}})
    assert r.ok and r.data == {"canary_id": "c1"}
    assert not env.call("plant_canary", {"doc_title": "t", "assignment": {"e02": "A"}}).ok
    docs = env.call("list_documents", {}).data["documents"]
    c = [d for d in docs if d["is_canary"]][0]
    assert c["variants"] == {"A": ["e02"], "B": ["e03"]}


def test_integrity_scan():
    for seed in range(200):
        tier = TIERS[seed % 3]
        env = Env(tier, seed)
        random_policy(env, random.Random(seed))
        for s in env.history:
            blob = json.dumps(s.result).lower()
            assert '"mole' not in blob and "truth" not in blob and "correct" not in blob
        emps = Env(tier, seed).call("list_employees", {}).data["employees"]
        assert len({tuple(sorted(e.keys())) for e in emps}) == 1


def test_performance():
    t0 = time.time()
    for seed in range(1000):
        env = Env(TIERS[seed % 3], seed)
        random_policy(env, random.Random(seed))
    dt = time.time() - t0
    print(f"1000 random episodes: {dt:.2f}s")
    assert dt < 30


def test_judge_secret_changes_world(monkeypatch):
    from canary.world import generate_world
    from canary.rules import TIERS as T
    monkeypatch.delenv("CANARY_WORLD_SECRET", raising=False)
    import canary.world as w
    monkeypatch.setattr(w, "_key", lambda s: b"public")
    pub = generate_world("hard", 900_000, T["hard"])
    monkeypatch.undo()
    monkeypatch.setenv("CANARY_WORLD_SECRET", "s3cret")
    sec = generate_world("hard", 900_000, T["hard"])
    assert pub.world_seed != sec.world_seed
    assert (pub.mole, pub.planned_docs) != (sec.mole, sec.planned_docs)


def test_accuse_payload_parity():
    payloads = set()
    for e in [f"e{i:02d}" for i in range(12)]:
        env = Env("easy", 9)
        r = env.call("accuse", {"employee": e})
        payloads.add(json.dumps({"ok": r.ok, "error": r.error, "keys": sorted(r.data), "over": r.data["episode_over"]}))
    assert len(payloads) == 1


def test_error_parity_and_no_seed():
    from canary.env import ERRORS
    errs = set()
    for seed in range(30):
        env = Env("medium", seed)
        random_policy(env, random.Random(seed))
        for s in env.history:
            if s.result["error"] is not None:
                errs.add(s.result["error"])
            assert str(env._world.world_seed) not in json.dumps(s.result)
        for e in env._world.ids:
            r = Env("medium", seed).call("restrict_access", {"employee": e + "x"})
            errs.add(r.error)
    assert errs <= ERRORS


def test_invalid_arguments_carry_a_specific_detail():
    """The error string is unchanged (committed episodes replay); data.detail says what was wrong."""
    env = Env("hard", 3)
    r = env.call("interview", {"employee": "e01", "topic": "leaks"})
    assert not r.ok and r.error == "invalid arguments" and "topic must be one of" in r.data["detail"]
    r = env.call("interview", {"employee": "e01"})
    assert r.error == "invalid arguments" and "missing required" in r.data["detail"]
    r = env.call("status", {"x": 1})
    assert "unknown argument" in r.data["detail"]
    r = env.call("read_access_logs", {"day_from": 3, "day_to": 2})
    assert "day_from must not be after day_to" in r.data["detail"]
    r = env.call("accuse", {"employee": "nobody"})
    assert "list_employees" in r.data["detail"] and not env.done


def test_error_detail_does_not_depend_on_who_the_mole_is():
    """Same call shape against the mole and an innocent: identical detail apart from the id itself."""
    env = Env("medium", 4)
    mole = env._world.mole
    innocent = next(e for e in env._world.ids if e != mole)
    out = {}
    for e in (mole, innocent):
        assert env.call("restrict_access", {"employee": e}).ok
        r = env.call("restrict_access", {"employee": e})
        assert not r.ok and r.error == "invalid arguments"
        out[e] = r.data["detail"].replace(e, "<id>")
        r = env.call("plant_canary", {"doc_title": "t", "assignment": {e: "A"}})
        out[e] += " | " + r.data["detail"].replace(e, "<id>")
    assert out[mole] == out[innocent]
