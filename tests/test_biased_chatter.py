from __future__ import annotations

import json
from pathlib import Path

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import read_ledger
from canary.gemini.biased_chatter import (
    BIAS_KINDS,
    CHATTER_SCHEMA,
    BiasEventSpec,
    BiasedChatterProvider,
    build_bias_event_spec,
    generate_biased_chatter,
    public_facts_from_env,
    run_seeds,
    sanitize_public_facts,
    validate_biased_chatter,
)
from canary.llm import register_script
from canary.text.lint import lint_messages

ROSTER = [
    {"id": "e00", "name": "Ville Tuominen", "dept": "Engineering", "role": "senior engineer"},
    {"id": "e01", "name": "Nea Lehtonen", "dept": "Finance", "role": "controller"},
    {"id": "e02", "name": "Kalle Lehtinen", "dept": "Sales", "role": "sales manager"},
    {"id": "e03", "name": "Kaisa Nieminen", "dept": "Legal", "role": "compliance officer"},
    {"id": "e04", "name": "Mikko Virtanen", "dept": "Engineering", "role": "engineer"},
    {"id": "e05", "name": "Sanna Korhonen", "dept": "Finance", "role": "analyst"},
]

DOCS = [
    {
        "doc_id": "d1-1",
        "title": "Q2 Sales budget forecast",
        "day": 1,
        "recipients": ["e01", "e02", "e05"],
        "is_canary": True,
        "variants": {"A": ["e01"], "B": ["e02", "e05"]},
    }
]


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    return led


def _poisoned_facts(mole: str = "e04", decoy: str = "e03") -> dict:
    emps = [dict(e, is_mole=(e["id"] == mole), is_decoy=(e["id"] == decoy)) for e in ROSTER]
    return {
        "company": "Borealis Dynamics",
        "tier": "medium",
        "seed": 42,
        "day": 1,
        "employees": emps,
        "docs": DOCS,
        "mole": mole,
        "mole_id": mole,
        "decoy": decoy,
        "mole_strategy": {"rules": []},
        "secret": "top-secret-salt",
        "truth": {"mole": mole},
    }


def test_sanitize_and_truth_invariance(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    f1 = _poisoned_facts(mole="e00", decoy="e05")
    f2 = _poisoned_facts(mole="e04", decoy="e01")

    pub1 = sanitize_public_facts(f1)
    pub2 = sanitize_public_facts(f2)
    assert pub1 == pub2
    assert_no_truth(pub1, {"mole": "e00", "employees": ROSTER})

    spec1 = build_bias_event_spec(f1, seed=10)
    spec2 = build_bias_event_spec(f2, seed=10)
    assert spec1 == spec2
    assert spec1.manager_id in {"e01", "e02"}

    out1 = generate_biased_chatter(f1, seed=10, world_for_check={"mole": "e00", "employees": ROSTER})
    out2 = generate_biased_chatter(f2, seed=10, world_for_check={"mole": "e04", "employees": ROSTER})
    assert out1 == out2
    assert not lint_messages(out1["messages"])


def test_explicit_bias_spec_and_validation():
    pub = sanitize_public_facts(_poisoned_facts())
    explicit = BiasEventSpec(
        rumour_target="e04",
        grudge_pair=("e00", "e05"),
        manager_id="e02",
        forwarded_doc_title="Q2 Sales budget forecast",
    )
    built = build_bias_event_spec(pub, seed=7, explicit=explicit)
    assert built == explicit

    with pytest.raises(ValueError):
        build_bias_event_spec(pub, explicit={"rumour_target": "e99"})
    with pytest.raises(ValueError):
        build_bias_event_spec(pub, explicit={"grudge_pair": ["e01", "e01"]})
    with pytest.raises(ValueError):
        build_bias_event_spec(pub, explicit={"manager_id": "missing"})
    with pytest.raises(ValueError):
        build_bias_event_spec(pub, explicit={"forwarded_doc_title": "I leaked it yesterday"})


def test_keyless_default_model_routes_via_lab_client(monkeypatch, _isolated_ledger):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    explicit = {
        "rumour_target": "e04",
        "grudge_pair": ["e00", "e05"],
        "manager_id": "e02",
        "forwarded_doc_title": "Q2 Sales budget forecast",
    }
    res = generate_biased_chatter(
        _poisoned_facts(mole="e04"),
        bias_spec=explicit,
        model="gemini-4-carbon",
        seed=10,
        world_for_check={"mole": "e04", "employees": ROSTER},
    )
    assert res["source"] == "stub:keyless_fallback"
    assert len(res["messages"]) == 5
    kinds = [m["bias_type"] for m in res["messages"]]
    assert set(kinds) == set(BIAS_KINDS)
    assert kinds.count("grudge_bickering") == 2
    assert res["n_fallback_messages"] == 5
    assert res["truth_leak_violations"] == 0
    assert res["lint_violations"] == 0

    rows = read_ledger([_isolated_ledger])
    assert len(rows) == 1
    assert rows[0]["feature"] == "biased_chatter"
    assert rows[0]["ok"] is True


def test_scripted_structured_output_via_lab_client(_isolated_ledger):
    llm_payload = {
        "messages": [
            {
                "bias_type": "unverified_rumour",
                "channel": "\x23engineering",
                "sender": "e00",
                "recipients": ["e03"],
                "subject": "Calendar blocks",
                "body": "Heard Mikko Virtanen (e04) stepped out twice\u2014maybe external recruiter chats.",
            },
            {
                "bias_type": "grudge_bickering",
                "channel": "\x23cross-team",
                "sender": "e00",
                "recipients": ["e05"],
                "subject": "Late sheet",
                "body": "Sanna Korhonen, your Finance tab broke our import script again.",
            },
            {
                "bias_type": "grudge_bickering",
                "channel": "\x23cross-team",
                "sender": "e05",
                "recipients": ["e00"],
                "subject": "Re: Late sheet",
                "body": "Ville Tuominen, Engineering changed the column headers without telling anyone.",
            },
            {
                "bias_type": "authority_bias",
                "channel": "\x23sales",
                "sender": "e02",
                "recipients": ["e01", "e03"],
                "subject": "Audit sign-off",
                "body": "I run Sales and vouch 100 percent for those batch exports, no need to check logs.",
            },
            {
                "bias_type": "unplanned_doc_forward",
                "channel": "email",
                "sender": "e01",
                "recipients": ["e03"],
                "subject": "Fwd: Q2 Sales budget forecast",
                "body": "Looping you in on Q2 Sales budget forecast so Legal has the latest table.",
            },
        ]
    }
    register_script("biased_ok", [{"json": llm_payload}])
    res = generate_biased_chatter(
        _poisoned_facts(mole="e04"),
        bias_spec={
            "rumour_target": "e04",
            "grudge_pair": ["e00", "e05"],
            "manager_id": "e02",
            "forwarded_doc_title": "Q2 Sales budget forecast",
        },
        model="stub:biased_ok",
        seed=11,
        world_for_check={"mole": "e04", "employees": ROSTER},
    )
    assert res["n_llm_messages"] == 5
    assert res["n_fallback_messages"] == 0
    assert "\u2014" not in json.dumps(res)
    rows = read_ledger([_isolated_ledger])
    assert len(rows) == 1 and rows[0]["feature"] == "biased_chatter"


def test_poisoned_llm_outputs_rejected_and_guards_enforced():
    bad_payload = {
        "messages": [
            {
                "bias_type": "unverified_rumour",
                "channel": "\x23engineering",
                "sender": "e00",
                "recipients": ["e03"],
                "subject": "Gossip",
                "body": "Everyone says e04 is the mole and culprit.",
            },
            {
                "bias_type": "grudge_bickering",
                "channel": "\x23engineering",
                "sender": "e99",
                "recipients": ["e05"],
                "subject": "Invented",
                "body": "Sanna missed the review.",
            },
            {
                "bias_type": "authority_bias",
                "channel": "\x23sales",
                "sender": "e00",
                "recipients": ["e01"],
                "subject": "Wrong sender",
                "body": "Pretending to be the manager.",
            },
            {
                "bias_type": "unplanned_doc_forward",
                "channel": "email",
                "sender": "e01",
                "recipients": ["e03"],
                "subject": "Fwd: Q2 Sales budget forecast",
                "body": "I leaked it to x@rival-corp.com for e04.",
            },
        ]
    }
    register_script("biased_bad", [{"json": bad_payload}])
    res = generate_biased_chatter(
        _poisoned_facts(mole="e04"),
        bias_spec={
            "rumour_target": "e04",
            "grudge_pair": ["e00", "e05"],
            "manager_id": "e02",
            "forwarded_doc_title": "Q2 Sales budget forecast",
        },
        model="stub:biased_bad",
        seed=12,
        world_for_check={"mole": "e04", "employees": ROSTER},
    )
    assert res["n_llm_messages"] == 0
    assert res["n_fallback_messages"] == 5
    assert not lint_messages(res["messages"])

    with pytest.raises(AssertionError):
        validate_biased_chatter(
            {
                "messages": [
                    {
                        "id": "m1",
                        "day": 1,
                        "channel": "\x23eng",
                        "sender": "e00",
                        "recipients": ["e01"],
                        "subject": "Confession",
                        "body": "I leaked it yesterday.",
                    }
                ]
            },
            world={"mole": "e04", "employees": ROSTER},
        )
    with pytest.raises(AssertionError):
        validate_biased_chatter(
            {
                "mole": "e04",
                "messages": res["messages"],
            },
            world={"mole": "e04", "employees": ROSTER},
        )


def test_provider_and_run_seeds_keyless(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    assert "$ref" not in json.dumps(CHATTER_SCHEMA)

    provider = BiasedChatterProvider(model="stub")
    env = Env("medium", 10, text_provider=provider)
    pub = public_facts_from_env(env)
    assert len(pub["employees"]) == 20
    env.call("advance_day", {})
    srch = env.call("search_messages", {"query": "a"})
    assert srch.ok and srch.data["messages"]

    out_dir = tmp_path / "run_out"
    meta = run_seeds(out_dir, tier="medium", seeds=(10, 11), day=1, model="stub")
    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter"
    assert meta["truth_leak_violations"] == 0
    assert (out_dir / "meta.json").exists()
    assert (out_dir / "chatter_samples.json").exists()
    assert (out_dir / "summary.md").exists()


def test_committed_carbon_run_artifacts_if_present():
    run_dir = Path(__file__).resolve().parent.parent / "results" / "gemini_roles" / "world_text" / "biased-chatter-carbon"
    if not run_dir.exists():
        return
    meta = json.loads((run_dir / "meta.json").read_text())
    samples = json.loads((run_dir / "chatter_samples.json").read_text())
    summary = (run_dir / "summary.md").read_text()

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter"
    assert meta["model_id"] == "gemini-4-carbon"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "unknown"
    assert meta["timestamp"]
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["usage"]["calls"] >= 2
    assert meta["usage"]["input_tokens"] > 0
    assert meta["usage"]["total_tokens"] > 0
    assert summary.strip()

    assert [s["seed"] for s in samples["samples"]] == [10, 11]
    for s in samples["samples"]:
        assert s["n_llm_messages"] == 5
        assert s["n_fallback_messages"] == 0
        assert not lint_messages(s["messages"])
        env = Env("medium", s["seed"])
        emps = env.call("list_employees", {}).data["employees"]
        assert_no_truth(s, {"mole": env._world.mole, "employees": emps})

