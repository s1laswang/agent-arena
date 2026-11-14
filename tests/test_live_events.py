from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from canary.agents._common import inline_schema
from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import live_events, read_ledger
from canary.llm.stub import StubClient
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_messages, lint_text

ROSTER = [
    {"id": f"e{i:02d}", "name": f"Staff{i} Member", "dept": ["Engineering", "Finance", "Legal", "Sales"][i % 4], "role": "lead" if i < 2 else "analyst"}
    for i in range(8)
]


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    return led


def test_schema_has_no_refs():
    sch = inline_schema(live_events.IncidentEventDraft)
    assert "$ref" not in json.dumps(sch)
    required = set(sch.get("required") or ())
    assert {"category", "headline", "summary", "affected_departments", "referenced_documents", "bulletin", "reactions"} <= required


def test_stub_mode_deterministic_and_ledgered(_isolated_ledger):
    env1 = Env("medium", 3)
    env2 = Env("medium", 3)
    ev1 = live_events.generate_mid_episode_events(env1, days=(3, 6, 10), llm="stub")
    ev2 = live_events.generate_mid_episode_events(env2, days=(3, 6, 10), llm="stub")
    assert [b["day"] for b in ev1] == [3, 6, 10]
    for b1, b2 in zip(ev1, ev2):
        assert {k: v for k, v in b1.items() if k != "meta"} == {k: v for k, v in b2.items() if k != "meta"}
        assert b1["category"] in live_events.EVENT_CATEGORIES
        assert set(b1["bulletin"]) == {"id", "day", "channel", "sender", "recipients", "subject", "body"}
        assert len(b1["reactions"]) >= 2
        assert not lint_messages(b1["messages"])
        assert_no_truth(b1, env1._world)

    rows = read_ledger([_isolated_ledger])
    assert len(rows) == 6
    assert all(r["feature"] == "live_events" and r["ok"] for r in rows)


def test_all_four_incident_categories_covered_across_seeds():
    seen = set()
    for seed in (3, 4, 5):
        bundles = live_events.generate_mid_episode_events(Env("medium", seed), days=(3, 6, 10), llm="stub")
        seen.update(b["category"] for b in bundles)
    assert seen == set(live_events.EVENT_CATEGORIES)


def test_truth_isolation_never_sends_secrets_or_future_docs_or_canaries():
    facts = {
        "company": "Borealis Dynamics",
        "tier": "medium",
        "seed": 42,
        "employees": ROSTER,
        "docs": [
            {"doc_id": "d2-1", "title": "Q2 Engineering roadmap", "day": 2, "recipients": ["e00", "e04"]},
            {"doc_id": "c3", "title": "Canary pricing trap", "day": 3, "recipients": ["e04"], "is_canary": True},
            {"doc_id": "d8-1", "title": "Future Day 8 merger memo", "day": 8, "recipients": ["e01", "e05"]},
        ],
        "mole": "e04",
        "mole_id": "e04",
        "decoy": "e02",
        "secret": "top-secret-hmac",
        "ledger": [{"event": "leak"}],
    }
    stub = StubClient()
    bundles = live_events.generate_mid_episode_events(facts, days=(3, 8), llm=stub)
    assert len(stub.calls) == 2

    day3_prompt = stub.calls[0]["messages"][-1]["content"]
    day8_prompt = stub.calls[1]["messages"][-1]["content"]
    for bad_key in ('"mole"', '"mole_id"', '"decoy"', '"secret"', '"ledger"', "top-secret-hmac", "Canary pricing trap"):
        assert bad_key not in day3_prompt
        assert bad_key not in day8_prompt
    assert "Q2 Engineering roadmap" in day3_prompt
    assert "Future Day 8 merger memo" not in day3_prompt
    assert "Future Day 8 merger memo" in day8_prompt

    audit = live_events.audit_event_bundles(bundles, world={"mole": "e04", "employees": ROSTER})
    assert audit["truth_leak_violations"] == 0
    assert audit["lint_violations"] == 0


def test_never_touches_hidden_truth_properties():
    class GuardedWorld:
        company = "Kestrel Labs"
        employees = [SimpleNamespace(**e) for e in ROSTER]
        planned_docs = {1: [{"doc_id": "d1-1", "title": "Q1 Finance budget", "day": 1, "recipients": ["e01", "e05"]}]}

        @property
        def mole(self):
            raise AssertionError("generator read hidden mole attribute")

        @property
        def decoy(self):
            raise AssertionError("generator read hidden decoy attribute")

    guarded_env = SimpleNamespace(tier="medium", seed=7, docs=[], _world=GuardedWorld())
    bundles = live_events.generate_mid_episode_events(guarded_env, days=(3,), llm="stub")
    assert len(bundles) == 1
    assert not lint_messages(bundles[0]["messages"])

    real_env = Env("medium", 3)
    proxy_env = SimpleNamespace(tier="medium", seed=3, company="Halcyon Metrics", call=real_env.call)
    proxy_bundles = live_events.generate_mid_episode_events(proxy_env, days=(3,), llm="stub")
    assert len(proxy_bundles) == 1
    assert not lint_messages(proxy_bundles[0]["messages"])


def test_valid_llm_structured_json_preserved_and_em_dash_normalized():
    payload = {
        "category": "vendor_offboarding",
        "headline": "CloudBridge analytics offboarding \u2014 token rotation",
        "summary": "CloudBridge contractor offboarding completed on Day 6 \u2014 shared tokens rotated.",
        "affected_departments": ["Engineering", "Legal"],
        "referenced_documents": ["Q1 Finance budget"],
        "bulletin": {
            "sender": "e02",
            "channel": "email",
            "subject": "[Ops] CloudBridge offboarding \u2014 Day 6",
            "body": "All Engineering and Legal teams \u2014 CloudBridge credentials linked to Q1 Finance budget were rotated.",
        },
        "reactions": [
            {"sender": "e00", "channel": "#engineering", "body": "Updated the CI token in our Engineering job; sync green."},
            {"sender": "e06", "channel": "#legal", "body": "Archived the termination notice in Legal records."},
        ],
    }
    facts = PublicDayFacts(
        tier="medium",
        seed=9,
        day=6,
        company="Nordlys Systems",
        employees=tuple(EmployeeFacts(e["id"], e["name"], e["dept"], e["role"]) for e in ROSTER),
        docs=({"doc_id": "d1-1", "title": "Q1 Finance budget", "day": 1, "recipients": ["e01", "e02"]},),
    )
    stub = StubClient([{"json": payload}])
    bundles = live_events.generate_mid_episode_events(facts, days=(6,), llm=stub, seed=9)
    ev = bundles[0]
    assert ev["meta"]["llm_ok"] is True
    assert ev["meta"]["used_fallback"] is False
    assert ev["meta"]["repaired"] is False
    assert ev["category"] == "vendor_offboarding"
    assert "\u2014" not in json.dumps(ev)
    assert "CloudBridge analytics offboarding - token rotation" == ev["headline"]
    assert ev["referenced_documents"] == ["Q1 Finance budget"]
    assert_no_truth(ev, {"mole": "e04", "employees": ROSTER})


def test_poisoned_and_malformed_llm_outputs_repaired_cleanly():
    poisoned = {
        "category": "compliance_audit",
        "headline": "Urgent spy hunt: the mole is e04",
        "summary": "I leaked it to x@rival-corp.com with e04",
        "affected_departments": ["NonExistentDept"],
        "referenced_documents": ["Invented Secret Doc"],
        "bulletin": {
            "sender": "e99",
            "channel": "#badchannel",
            "subject": "We leaked the Q3 plan",
            "body": "Insider threat culprit e04 sold the roadmap; please raise a ticket.",
        },
        "reactions": [
            {"sender": "e99", "channel": "#eng", "body": "Invented employee reaction"},
            {"sender": "e01", "channel": "#finance", "body": "I am updating my CV after the recruiter call"},
        ],
    }
    facts = {"company": "Aurora Freight", "tier": "medium", "seed": 5, "employees": ROSTER, "docs": []}
    stub = StubClient([{"json": poisoned}, {"text": "not valid json {{"}])
    bundles = live_events.generate_mid_episode_events(facts, days=(3, 6), llm=stub)
    assert len(bundles) == 2
    assert bundles[0]["meta"]["raw_violations"] > 0
    assert bundles[0]["meta"]["repaired"] is True
    assert bundles[1]["meta"]["used_fallback"] is True

    world = {"mole": "e04", "employees": ROSTER}
    audit = live_events.audit_event_bundles(bundles, world=world)
    assert audit["truth_leak_violations"] == 0
    assert audit["lint_violations"] == 0
    assert audit["raw_llm_violations"] > 0
    for b in bundles:
        assert_no_truth(b, world)
        for m in b["messages"]:
            assert not lint_text(m["body"])
            assert m["sender"] in {e["id"] for e in ROSTER}


def test_live_events_text_provider_delivers_searchable_messages_in_env():
    base_env = Env("medium", 3)
    bundles = live_events.generate_mid_episode_events(base_env, days=(3, 6), llm="stub")
    provider = live_events.LiveEventsTextProvider(bundles)
    env = Env("medium", 3, text_provider=provider)
    for _ in range(3):
        env.call("advance_day", {})
    res = env.call("read_message", {"id": "ev3-0"})
    assert res.ok is True
    assert res.data["message"]["day"] == 3
    search_word = bundles[0]["bulletin"]["body"].split()[0]
    sr = env.call("search_messages", {"query": search_word, "day_from": 3, "day_to": 3})
    assert sr.ok is True
    assert any(m["id"].startswith("ev3-") for m in sr.data["messages"])


def test_solver_parity_and_cli_keyless(tmp_path):
    out_dir = tmp_path / "run_out"
    rc = live_events.main([
        "--llm", "stub",
        "--tier", "medium",
        "--seeds", "3,4",
        "--days", "3,6,10",
        "--out", str(out_dir),
    ])
    assert rc == 0
    meta = json.loads((out_dir / "meta.json").read_text())
    events_doc = json.loads((out_dir / "events.json").read_text())
    parity = json.loads((out_dir / "solver_parity.json").read_text())
    summary_md = (out_dir / "summary.md").read_text()

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "dynamic_mid_episode_events"
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["n_events_generated"] == 6
    assert events_doc["n_events_generated"] == 6
    assert parity["parity_ok"] is True
    assert parity["do_nothing_all_zero"] is True
    assert parity["live_events_solver_mean_score"] > parity["live_events_obvious_heuristic_mean_score"]
    assert "SolverPolicy vs ObviousHeuristic" in summary_md
    assert "\u2014" not in summary_md


def test_day_mapping_and_sequence_inputs():
    emps = tuple(EmployeeFacts(e["id"], e["name"], e["dept"], e["role"]) for e in ROSTER)
    f3 = PublicDayFacts("medium", 11, 3, "Halcyon Metrics", emps, ({"doc_id": "d3-1", "title": "Q1 Legal audit", "day": 3, "recipients": ["e02"]},))
    f6 = PublicDayFacts("medium", 11, 6, "Halcyon Metrics", emps, ({"doc_id": "d6-1", "title": "Q2 Sales plan", "day": 6, "recipients": ["e03"]},))
    by_map = live_events.generate_mid_episode_events({3: f3, 6: f6}, days=(3, 6), llm="stub")
    by_seq = live_events.generate_mid_episode_events([f3, f6], days=(3, 6), llm="stub")
    assert [b["day"] for b in by_map] == [3, 6]
    assert [b["day"] for b in by_seq] == [3, 6]
    for b in by_map + by_seq:
        assert not lint_messages(b["messages"])
        assert_no_truth(b, {"mole": "e05", "employees": ROSTER})


def test_default_gemini_client_raises_missing_key_when_blank(monkeypatch):
    from canary.llm import MissingKeyError

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    with pytest.raises(MissingKeyError):
        live_events.generate_mid_episode_events(Env("medium", 3), days=(3,))


def test_committed_carbon_run_artifacts():
    run_dir = live_events.REPO / "results" / "gemini_roles" / "world_text" / "dynamic-events-carbon"
    meta = json.loads((run_dir / "meta.json").read_text())
    events_doc = json.loads((run_dir / "events.json").read_text())
    parity = json.loads((run_dir / "solver_parity.json").read_text())
    summary_md = (run_dir / "summary.md").read_text()

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "dynamic_mid_episode_events"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["n_events_generated"] == 9
    assert meta["usage"]["calls"] == 9
    assert meta["usage"]["total_tokens"] > 0
    assert parity["parity_ok"] is True
    assert "\u2014" not in summary_md

    for seed_entry in events_doc["seeds"]:
        seed = seed_entry["seed"]
        world = Env("medium", seed)._world
        audit = live_events.audit_event_bundles(seed_entry["events"], world=world)
        assert audit["truth_leak_violations"] == 0
        assert audit["lint_violations"] == 0


