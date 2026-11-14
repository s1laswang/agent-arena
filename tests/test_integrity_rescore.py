"""Independent recompute of the Canary score from the server /ledger payload (never trusting payload["score"]).

canary_rescore(payload, mole=None) uses only the ledger entries, the frozen tier params and, optionally, the
secret mole id. It cannot see the world, so "correct" is taken from the payload unless a mole id is supplied.
"""
from __future__ import annotations

import glob
import json
import random
from pathlib import Path

import pytest

from canary import rules
from canary.env import Env

ROOT = Path(__file__).resolve().parent.parent
EPS = 1e-9


def canary_rescore(payload: dict, mole: str | None = None, params=None) -> dict:
    p = params or rules.tier_params(payload["tier"])
    led = payload.get("ledger") or []
    problems: list[str] = []
    n_leak = sum(e["event"] == "leak" for e in led)
    n_canary = sum(e["event"] == "canary_planted" for e in led)
    end = [e for e in led if e["event"] == "episode_end"]
    acc = [e for e in led if e["event"] == "accused"]
    if len(end) != 1 or led[-1]["event"] != "episode_end":
        problems.append("episode_end missing, duplicated or not last")
    reason = end[0]["detail"]["reason"] if end else None
    final_day = payload.get("final_day")
    since: dict[str, int] = {}
    restrict_days = 0
    for e in led:
        if e["event"] == "restricted":
            since[e["detail"]["employee"]] = e["day"]
        elif e["event"] == "unrestricted":
            restrict_days += e["day"] - since.pop(e["detail"]["employee"])
    for a in since.values():
        restrict_days += (final_day - a) + (1 if reason == "horizon" else 0)
    v = max(0.0, 1.0 - p.leak_damage * n_leak - p.canary_cost * n_canary - p.restrict_cost_per_day * restrict_days)
    v = round(v, 10)
    if reason != payload.get("end_reason"):
        problems.append(f"end_reason {payload.get('end_reason')} vs ledger {reason}")
    if len(acc) > 1:
        problems.append("more than one accuse")
    if (reason == "accused") != bool(acc):
        problems.append("accused event inconsistent with end_reason")
    correct = None
    if acc:
        who = acc[0]["detail"]["employee"]
        if who != payload.get("accused"):
            problems.append("accused employee differs from payload")
        correct = bool(acc[0]["detail"]["correct"])
        if mole is not None and correct != (who == mole):
            problems.append(f"server says correct={correct} but mole is {mole}")
        if mole is not None:
            correct = who == mole
        if abs(acc[0]["detail"]["V"] - v) > 1e-6:
            problems.append(f"V at accusation {acc[0]['detail']['V']} vs recomputed {v}")
    score = (v if correct else float(p.wrong_accusation_score)) if acc else 0.0
    if abs(score - float(payload["score"])) > EPS:
        problems.append(f"score {payload['score']} vs recomputed {score}")
    if abs(v - float(payload["V"])) > EPS:
        problems.append(f"V {payload['V']} vs recomputed {v}")
    if end and abs(end[0]["detail"]["score"] - float(payload["score"])) > EPS:
        problems.append("episode_end score differs from payload score")
    if not -1.0 <= float(payload["score"]) <= 1.0:
        problems.append("score out of range")
    return {"score": score, "V": v, "problems": problems}


def payload_of(env: Env) -> dict:
    from dataclasses import asdict
    out = dict(env.verdict())
    out["tier"] = env.tier
    out["ledger"] = [asdict(e) for e in env.ledger()]
    return out


def test_committed_harbor_ledgers_recompute():
    files = sorted(glob.glob(str(ROOT / "results/harbor/**/verifier/ledger.json"), recursive=True))
    assert files
    bad = {}
    for f in files:
        r = canary_rescore(json.loads(Path(f).read_text()))
        if r["problems"]:
            bad[f] = r["problems"]
    print(f"{len(files)} committed Harbor ledgers, {len(bad)} mismatches")
    assert not bad, bad


def test_rescore_catches_a_forged_ledger():
    f = sorted(glob.glob(str(ROOT / "results/harbor/**/verifier/ledger.json"), recursive=True))[0]
    d = json.loads(Path(f).read_text())
    d["score"] = 1.0
    assert any("score" in x for x in canary_rescore(d)["problems"])
    d = json.loads(Path(f).read_text())
    d["ledger"] = [e for e in d["ledger"] if e["event"] != "leak"]
    assert canary_rescore(d)["problems"]


def _replay(ep, ver):
    p = rules.TIERS_HISTORY[ver][rules.TRACKS.get(ep["tier"], ep["tier"])] if ver != rules.TIERS_VERSION else rules.tier_params(ep["tier"])
    with rules.tiers_version(ver):
        env = Env(ep["tier"], ep["seed"])
        for st in ep["steps"]:
            env.call(st["tool"], st["args"])
    return env, p


def test_committed_episodes_replay_equals_recorded():
    files = glob.glob(str(ROOT / "data/runs/committed/**/episodes.jsonl"), recursive=True)
    n = skipped = unfinished = 0
    msgs = []
    for f in files:
        for line in open(f):
            ep = json.loads(line)
            if ep["seed"] >= 900000:
                skipped += 1
                continue
            n += 1
            ok = False
            for ver in (rules.TIERS_VERSION, "v1.3"):
                env, p = _replay(ep, ver)
                same = abs(env.score() - ep["score"]) < 1e-6 and env._accused == ep["accused"]
                if env.done:
                    r = canary_rescore(payload_of(env), mole=env._world.mole, params=p)
                    if same and env.day == ep["final_day"] and not r["problems"]:
                        ok = True
                        break
                elif same and ep["accused"] is None and ep["score"] == 0.0 and ep["end_reason"] == "error":
                    ok = True
                    unfinished += 1
                    break
            if not ok:
                msgs.append((f, ep["seed"], ep["agent"], ep["score"], ep["end_reason"]))
    print(f"{n} committed episodes replayed ({skipped} judge-seed episodes skipped: per-process secret; {unfinished} recorded as error, never ended), {len(msgs)} mismatches")
    assert n > 500
    assert not msgs, msgs[:5]


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_fuzz_served_score_equals_recomputed(tier):
    rng = random.Random(7)
    tools = ["status", "list_employees", "list_documents", "read_access_logs", "search_messages", "read_message",
             "interview", "plant_canary", "check_leak_feed", "restrict_access", "unrestrict_access", "advance_day", "accuse"]
    bad = []
    for seed in range(12):
        env = Env(tier, seed)
        ids = env._ids
        for _ in range(600):
            if env.done:
                break
            tool = rng.choice(tools + ["advance_day"] * 3 + ["restrict_access", "unrestrict_access"])
            e = rng.choice(ids)
            args = {
                "read_access_logs": {"employee": e}, "search_messages": {"query": "report"}, "read_message": {"message_id": "m0"},
                "interview": {"employee": e, "topic": rng.choice(["recent_documents", "contacts_outside", "workload", "access_needs"])},
                "plant_canary": {"doc_title": "T%d" % rng.randrange(99), "assignment": {x: rng.choice("ABC") for x in rng.sample(ids, 3)}},
                "restrict_access": {"employee": e}, "unrestrict_access": {"employee": e},
                "accuse": {"employee": e}, "list_documents": {}, "list_employees": {}, "status": {}, "check_leak_feed": {}, "advance_day": {},
            }[tool]
            if tool == "accuse" and rng.random() < 0.97:
                tool, args = "advance_day", {}
            env.call(tool, args)
        r = canary_rescore(payload_of(env), mole=env._world.mole)
        if r["problems"]:
            bad.append((tier, seed, r["problems"]))
    assert not bad, bad[:3]


def _episode(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    from canary.mcp_server import Episode
    return Episode("medium", 1)


def test_server_exception_mid_episode_fails_closed(monkeypatch):
    ep = _episode(monkeypatch)
    ep.call("advance_day", {})
    real = ep.env._dispatch
    monkeypatch.setattr(ep.env, "_dispatch", lambda t, a: (_ for _ in ()).throw(RuntimeError("boom")))
    r = ep.call("accuse", {"employee": ep.env._world.mole})
    assert not r.ok and r.error
    pay = ep.ledger_payload()
    assert pay["score"] == 0.0 and pay["done"] is False and pay["accused"] is None
    assert canary_rescore(pay)["score"] == 0.0
    monkeypatch.setattr(ep.env, "_dispatch", real)
    assert ep.call("accuse", {"employee": ep.env._world.mole}).ok
    pay = ep.ledger_payload()
    assert pay["score"] > 0 and canary_rescore(pay, mole=ep.env._world.mole)["problems"] == []


def test_exception_inside_score_makes_ledger_unavailable_not_a_reward(monkeypatch):
    ep = _episode(monkeypatch)
    monkeypatch.setattr(ep.env, "score", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        ep.ledger_payload()


def _run_test_sh(tmp_path, ledger_text):
    import subprocess
    import sys
    src = (ROOT / "harbor/template/tests/test.sh").read_text()
    body = src.split("python3 - <<'PY'\n")[1].split("\nPY")[0]
    body = body.replace("/logs/verifier", str(tmp_path / "out")).replace("/evidence/ledger.json", str(tmp_path / "ledger.json"))
    (tmp_path / "out").mkdir()
    (tmp_path / "ledger.json").write_text(ledger_text)
    subprocess.run([sys.executable, "-c", body], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return (tmp_path / "out" / "reward.txt").read_text()


@pytest.mark.parametrize("text,expect", [("{", "0"), ('{"x": 1}', "0"), ('{"score": 5.0}', "0"), ('{"score": NaN}', "0"), ('{"score": "abc"}', "0")])
def test_harbor_test_sh_fails_closed_on_bad_ledger(tmp_path, text, expect):
    assert _run_test_sh(tmp_path, text) == expect


def test_harbor_test_sh_trusts_the_served_score_without_recompute(tmp_path):
    f = sorted(glob.glob(str(ROOT / "results/harbor/**/verifier/ledger.json"), recursive=True))[0]
    d = json.loads(Path(f).read_text())
    d["score"] = 1.0
    d["V"] = 1.0
    assert canary_rescore(d)["problems"]
    assert _run_test_sh(tmp_path, json.dumps(d)) == "1.0"
