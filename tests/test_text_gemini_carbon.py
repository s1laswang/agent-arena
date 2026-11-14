from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.gemini import DEFAULT_MODEL, GeminiProvider, GeminiWorldTextProvider, get_provider


def _make_facts(day: int = 1, seed: int = 11, tier: str = "easy") -> PublicDayFacts:
    emps = (
        EmployeeFacts("e00", "Aino Virtanen", "Eng", "engineer"),
        EmployeeFacts("e01", "Mikael Korhonen", "Eng", "lead"),
        EmployeeFacts("e02", "Sanni Lehtonen", "Sales", "manager"),
        EmployeeFacts("e03", "Oskari Niemi", "Ops", "analyst"),
    )
    docs = (
        {
            "doc_id": f"d{day}-0",
            "title": f"Architecture Roadmap v{day}",
            "day": day,
            "recipients": ["e00", "e01"],
        },
    )
    return PublicDayFacts(
        tier=tier,
        seed=seed,
        day=day,
        company="Northwind",
        employees=emps,
        docs=docs,
        decoy="e02",
        decoy_mood="angry",
    )


class ScriptedClient:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None):
        self.calls += 1
        item = self.responses.pop(0)
        if callable(item):
            return item(messages, response_schema)
        return item


def test_default_model_is_gemini_4_carbon(monkeypatch):
    assert DEFAULT_MODEL == "gemini-4-carbon"

    gp = GeminiProvider()
    assert gp.model == "gemini-4-carbon"
    assert gp.name == "gemini:gemini-4-carbon"

    gwp = GeminiWorldTextProvider()
    assert gwp.model == "gemini-4-carbon"
    assert gwp.name == "gemini-world:gemini-4-carbon"

    p1 = get_provider("gemini")
    assert isinstance(p1, GeminiProvider)
    assert p1.model == "gemini-4-carbon"
    assert p1.name == "gemini:gemini-4-carbon"

    p2 = get_provider("gemini-world")
    assert isinstance(p2, GeminiWorldTextProvider)
    assert p2.model == "gemini-4-carbon"
    assert p2.name == "gemini-world:gemini-4-carbon"

    requested_specs = []

    def fake_get_client(spec: str, **kw):
        requested_specs.append(spec)
        return SimpleNamespace(chat=lambda *a, **k: {"text": "{}"})

    monkeypatch.setattr("canary.llm.get_client", fake_get_client)
    _ = gp.client
    _ = gwp.client
    assert requested_specs == ["gemini:gemini-4-carbon", "gemini:gemini-4-carbon"]


def test_fenced_json_responses_parse_without_fallback_gemini_provider(tmp_path):
    facts = _make_facts(day=1, seed=7)
    msg_payload = {
        "messages": [
            {
                "channel": "#eng",
                "sender": "e00",
                "recipients": ["e01"],
                "subject": "Architecture Roadmap v1",
                "body": "Notes on ```pytest -q``` checks look solid before lunch.",
            }
        ]
    }
    fenced_msgs = f"```json\n{json.dumps(msg_payload, indent=2)}\n```"
    fenced_ans_1 = '  ```JSON\n{"answer": "Mostly reviewing Architecture Roadmap v1 with Mikael."}\n```  '
    fenced_ans_2 = '```\n{"answer": "Hard to say, my afternoon was packed."}\n```'

    client = ScriptedClient([
        {"text": fenced_msgs, "usage": {"in": 120, "out": 55, "cost_usd": 0.00079}},
        SimpleNamespace(text=fenced_ans_1, usage={"in": 70, "out": 25, "cost_usd": 0.00039}),
        {"text": fenced_ans_2, "usage": {"in": 65, "out": 20, "cost_usd": 0.00033}},
    ])
    provider = GeminiProvider(cache_dir=str(tmp_path), client=client)

    msgs = provider.day_messages(facts)
    ans_coop = provider.interview_answer(facts, "e00", "workload", "cooperative")
    ans_evas = provider.interview_answer(facts, "e01", "workload", "evasive")

    assert provider.fallbacks == 0
    assert client.calls == 3
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "e00"
    assert "```pytest -q```" in msgs[0]["body"]
    assert ans_coop == "Mostly reviewing Architecture Roadmap v1 with Mikael."
    assert ans_evas == "Hard to say, my afternoon was packed."


def test_fenced_json_responses_parse_without_fallback_world_text_provider(tmp_path):
    facts = _make_facts(day=1, seed=8)
    world_payload = {
        "company_blurb": "Northwind builds telemetry pipelines.",
        "personas": [
            {"employee_id": "e00", "bio": "Writes backend services.", "tone": "dry"},
            {"employee_id": "e01", "bio": "Reviews design docs.", "tone": "warm"},
            {"employee_id": "e02", "bio": "Runs enterprise renewals.", "tone": "upbeat"},
            {"employee_id": "e03", "bio": "Maintains deployment checklists.", "tone": "formal"},
        ],
        "departments": [
            {"dept": "Eng", "culture": "Async code reviews."},
            {"dept": "Sales", "culture": "Weekly forecast check-ins."},
            {"dept": "Ops", "culture": "Runbook driven."},
        ],
        "chatter_templates": ["Quick sync on {doc_title} {when} with {colleague}?"],
    }
    fenced_world = f"```json\n{json.dumps(world_payload)}\n```"
    client = ScriptedClient([
        {"text": fenced_world, "usage": {"in": 250, "out": 140, "thinking": 50, "cost_usd": 0.0019}}
    ])

    provider = GeminiWorldTextProvider(cache_dir=str(tmp_path), client=client)
    msgs = provider.day_messages(facts)
    ans = provider.interview_answer(facts, "e00", "workload", "cooperative")

    assert client.calls == 1
    assert msgs and any("Architecture Roadmap v1" in m["body"] for m in msgs)
    assert isinstance(ans, str) and ans

    cache_file = tmp_path / "easy" / "8.worldtext.json"
    saved = json.loads(cache_file.read_text())
    assert saved["meta"]["llm_ok"] is True
    assert saved["company_blurb"] == "Northwind builds telemetry pipelines."


def test_cache_hit_makes_zero_llm_calls_without_api_key(tmp_path, monkeypatch):
    facts = _make_facts(day=2, seed=19)

    seed_text_client = ScriptedClient([
        {
            "text": json.dumps({
                "messages": [{
                    "channel": "#eng",
                    "sender": "e01",
                    "recipients": ["e00"],
                    "subject": "Sync",
                    "body": "Roadmap check at 14:00.",
                }]
            }),
            "usage": {"in": 100, "out": 40, "cost_usd": 0.0006},
        },
        {
            "text": json.dumps({"answer": "Reviewed Architecture Roadmap v2 this morning."}),
            "usage": {"in": 60, "out": 20, "cost_usd": 0.00032},
        },
    ])
    seeded_text = GeminiProvider(cache_dir=str(tmp_path), client=seed_text_client)
    expected_msgs = seeded_text.day_messages(facts)
    expected_ans = seeded_text.interview_answer(facts, "e01", "recent_documents", "cooperative")
    assert seed_text_client.calls == 2

    seed_world_client = ScriptedClient([
        {
            "text": json.dumps({
                "company_blurb": "Northwind analytics team.",
                "personas": [
                    {"employee_id": "e00", "bio": "Focused engineer.", "tone": "dry"},
                    {"employee_id": "e01", "bio": "Helpful lead.", "tone": "warm"},
                    {"employee_id": "e02", "bio": "Account lead.", "tone": "chatty"},
                    {"employee_id": "e03", "bio": "Ops specialist.", "tone": "formal"},
                ],
                "departments": [
                    {"dept": "Eng", "culture": "Fast iteration."},
                    {"dept": "Sales", "culture": "Pipeline reviews."},
                    {"dept": "Ops", "culture": "Incident readiness."},
                ],
                "chatter_templates": ["{colleague}, thoughts on {doc_title} before {when}?"],
            }),
            "usage": {"in": 210, "out": 110, "cost_usd": 0.00152},
        }
    ])
    seeded_world = GeminiWorldTextProvider(cache_dir=str(tmp_path), client=seed_world_client)
    expected_world_msgs = seeded_world.day_messages(facts)
    expected_world_ans = seeded_world.interview_answer(facts, "e01", "recent_documents", "cooperative")
    assert seed_world_client.calls == 1

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    def forbid_client_creation(*args, **kwargs):
        raise AssertionError("get_client should not be called on cache hit")

    monkeypatch.setattr("canary.llm.get_client", forbid_client_creation)

    replayed_text = GeminiProvider(cache_dir=str(tmp_path))
    assert replayed_text.day_messages(facts) == expected_msgs
    assert replayed_text.interview_answer(facts, "e01", "recent_documents", "cooperative") == expected_ans
    assert replayed_text.fallbacks == 0

    replayed_world = GeminiWorldTextProvider(cache_dir=str(tmp_path))
    assert replayed_world.day_messages(facts) == expected_world_msgs
    assert replayed_world.interview_answer(facts, "e01", "recent_documents", "cooperative") == expected_world_ans


def test_model_id_and_usage_persisted_in_text_and_worldtext_caches(tmp_path):
    facts_d1 = _make_facts(day=1, seed=23)
    facts_d2 = _make_facts(day=2, seed=23)

    raw_sdk_resp = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=150,
            candidates_token_count=45,
            thoughts_token_count=35,
            cached_content_token_count=20,
        )
    )
    client_1 = ScriptedClient([
        SimpleNamespace(
            text=json.dumps({
                "messages": [{
                    "channel": "#eng",
                    "sender": "e00",
                    "recipients": ["e01"],
                    "subject": "Day 1",
                    "body": "Kicking off sprint tasks.",
                }]
            }),
            usage={"in": 150, "out": 80, "cached_in": 20, "cost_usd": 0.0011, "cost_usd_est": 0.001062},
            raw=raw_sdk_resp,
        ),
        {
            "text": json.dumps({"answer": "Working through sprint backlog items."}),
            "usage": {"in": 90, "out": 30, "thinking": 10, "cached": 0, "cost_usd": 0.00048},
        },
    ])
    p1 = GeminiProvider(cache_dir=str(tmp_path), client=client_1)
    p1.day_messages(facts_d1)
    p1.interview_answer(facts_d1, "e00", "workload", "cooperative")
    assert p1.fallbacks == 0

    text_cache_path = tmp_path / "easy" / "23.text.json"
    text_cache = json.loads(text_cache_path.read_text())
    assert text_cache["model_id"] == "gemini-4-carbon"
    assert text_cache["provider"] == "gemini:gemini-4-carbon"
    assert text_cache["usage"] == {
        "in": 240,
        "out": 110,
        "thinking": 45,
        "cached": 20,
        "calls": 2,
        "cost_usd": pytest.approx(0.001542),
    }

    client_2 = ScriptedClient([
        {
            "text": json.dumps({
                "messages": [{
                    "channel": "#eng",
                    "sender": "e01",
                    "recipients": ["e00"],
                    "subject": "Day 2",
                    "body": "Follow-up on Architecture Roadmap v2.",
                }]
            }),
            "usage": {"in": 110, "out": 50, "thinking": 15, "cached": 5, "cost_usd": 0.00071},
        }
    ])
    p2 = GeminiProvider(cache_dir=str(tmp_path), client=client_2)
    p2.day_messages(facts_d1)
    p2.day_messages(facts_d2)
    assert client_2.calls == 1

    text_cache_after = json.loads(text_cache_path.read_text())
    assert text_cache_after["model_id"] == "gemini-4-carbon"
    assert text_cache_after["usage"] == {
        "in": 350,
        "out": 160,
        "thinking": 60,
        "cached": 25,
        "calls": 3,
        "cost_usd": pytest.approx(0.002252),
    }

    world_client = ScriptedClient([
        {
            "text": json.dumps({
                "company_blurb": "Northwind cloud platform.",
                "personas": [
                    {"employee_id": "e00", "bio": "Builds APIs.", "tone": "dry"},
                    {"employee_id": "e01", "bio": "Leads architecture.", "tone": "warm"},
                    {"employee_id": "e02", "bio": "Manages accounts.", "tone": "dry"},
                    {"employee_id": "e03", "bio": "Handles reliability.", "tone": "warm"},
                ],
                "departments": [
                    {"dept": "Eng", "culture": "Design docs first."},
                    {"dept": "Sales", "culture": "Customer obsessed."},
                    {"dept": "Ops", "culture": "Steady releases."},
                ],
                "chatter_templates": ["Checking {doc_title} {when}."],
            }),
            "usage": {"in": 320, "out": 180, "thinking": 65, "cached": 30, "cost_usd": 0.002383},
        }
    ])
    wp = GeminiWorldTextProvider(cache_dir=str(tmp_path), client=world_client)
    wp.day_messages(facts_d1)

    world_cache_path = tmp_path / "easy" / "23.worldtext.json"
    world_cache = json.loads(world_cache_path.read_text())
    assert world_cache["model_id"] == "gemini-4-carbon"
    assert world_cache["provider"] == "gemini-world:gemini-4-carbon"
    assert world_cache["usage"] == {
        "in": 320,
        "out": 180,
        "thinking": 65,
        "cached": 30,
        "calls": 1,
        "cost_usd": pytest.approx(0.002383),
    }
    assert world_cache["meta"]["model_id"] == "gemini-4-carbon"
    assert world_cache["meta"]["usage"] == world_cache["usage"]

    roster = [{"id": e.id, "name": e.name, "dept": e.dept, "role": e.role} for e in facts_d1.employees]
    assert_no_truth({k: v for k, v in world_cache.items() if k != "meta"}, {"mole": "e00", "employees": roster})
