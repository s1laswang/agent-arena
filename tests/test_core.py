"""Core guarantees of the Blind Spot environment.

- Determinism: a day is a pure function of the seed.
- Solvability: the scripted oracle (tools + visible text only) scores 1 on every day.
- Integrity: do-nothing, stop-early, refuse-all, escalate-all and claim-in-chat score 0
  on every day; the autopilot clerk scores 1 only on days without hazards.
- Every hazard family is caught by the oracle and missed by autopilot.
"""
import json

import pytest

from blindspot import world
from blindspot.baselines import POLICIES, autopilot, oracle
from blindspot.env import Env
from blindspot.verify import score

SEEDS = range(40)


def run(policy, seed, **kw):
    env = Env(seed, **kw)
    policy(env)
    return env, score(env.state())


def test_deterministic():
    a, _ = world.generate(7)
    b, _ = world.generate(7)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    c, _ = world.generate(8)
    assert json.dumps(a, sort_keys=True) != json.dumps(c, sort_keys=True)


@pytest.mark.parametrize("seed", SEEDS)
def test_oracle_solves_every_day(seed):
    _, s = run(oracle, seed)
    assert s["reward"] == 1, (s["harms"], {k: v for k, v in s["tickets"].items() if not v["ok"]})


@pytest.mark.parametrize("name", ["do_nothing", "stop_early", "refuse_all", "escalate_all",
                                  "claim_in_chat"])
def test_baselines_score_zero(name):
    for seed in SEEDS:
        _, s = run(POLICIES[name], seed)
        assert s["reward"] == 0, (name, seed)


def test_autopilot_only_wins_clean_days():
    wins_clean = 0
    for seed in range(80):
        env, s = run(autopilot, seed)
        if env.hidden["planted"]:
            assert s["reward"] == 0, seed
        else:
            assert s["reward"] == 1, (seed, s["harms"])
            wins_clean += 1
    assert wins_clean > 0


@pytest.mark.parametrize("fam", [f for f in world.FAMILIES])
def test_each_hazard_family(fam):
    fams = [fam] + (["ap_report"] if fam != "ap_report" else ["invoice_payment"])
    for seed in range(6):
        kw = dict(families=fams, hazards=[fam])
        env, s = run(oracle, seed, **kw)
        assert s["reward"] == 1, (fam, seed, s)
        env, s = run(autopilot, seed, **kw)
        if fam in env.hidden["planted"]:
            assert s["reward"] == 0, (fam, seed)
        # benign twin is solvable by both
        env, s = run(oracle, seed, families=fams, hazards=[])
        assert s["reward"] == 1
        env, s = run(autopilot, seed, families=fams, hazards=[])
        assert s["reward"] == 1, (fam, seed, s["harms"], s["tickets"])


def test_tools_do_not_leak_hidden_state():
    env = Env(3)
    dump = []
    for t in ["read_policy", "list_tickets", "list_emails", "list_docs", "list_vendors",
              "list_invoices", "list_payments", "list_people", "fx_rates"]:
        dump.append(json.dumps(env.call(t)))
    for t in env.world["tickets"]:
        dump.append(json.dumps(env.call("read_ticket", {"ticket_id": t["id"]})))
    text = "\n".join(dump)
    for word in ["hazard", "expect", "must_withhold", "withhold_ok", "P-FATFINGER", "fraud"]:
        assert word not in text, word


def test_ledger_is_append_only_and_day_end_locks():
    env = Env(1)
    oracle(env)
    n = len(env.ledger)
    out = env.call("pay", {"ticket_id": env.world["tickets"][0]["id"], "amount": 5,
                           "currency": "EUR", "iban": "FI0000000000000000"})
    assert not out["ok"]
    assert len(env.ledger) == n + 1 and env.ledger[-1]["ok"] is False
    assert score(env.state())["reward"] == 1


def test_hard_difficulty_solvable_and_baselines_zero():
    for seed in range(15):
        env, s = run(oracle, seed, difficulty="hard")
        assert s["reward"] == 1, (seed, s["harms"])
        assert s["tickets_total"] >= 15 and s["hazards_total"] >= 2
        for name in ["do_nothing", "stop_early", "refuse_all", "escalate_all", "claim_in_chat",
                     "autopilot"]:
            _, s = run(POLICIES[name], seed, difficulty="hard")
            assert s["reward"] == 0, (name, seed)


def test_standard_plan_unchanged_by_difficulty_param():
    assert world.plan_day(7) == world.plan_day(7, difficulty="standard")


def test_sft_export_roundtrip():
    from blindspot.export_sft import episode
    ep = episode(101)
    assert ep["reward"] == 1
    calls = [m for m in ep["messages"] if m["role"] == "assistant" and m.get("tool_calls")]
    results = [m for m in ep["messages"] if m["role"] == "tool"]
    assert len(calls) == len(results) > 10
    assert calls[-1]["tool_calls"][0]["function"]["name"] == "end_day"
    text = json.dumps(ep)
    for word in ["must_withhold", "withhold_ok", "pay_alt", "bad_ibans"]:
        assert word not in text
