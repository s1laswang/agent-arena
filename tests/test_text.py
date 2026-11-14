from canary.rules import JUDGE_SEEDS
import json

import pytest

from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import SIGNALS, TOPICS, TemplateProvider

TIERS = {"easy": 12, "medium": 20, "hard": 30}
DEPTS = ["Eng", "Sales", "Finance", "Legal", "Ops"]
ROLES = ["engineer", "manager", "analyst", "director", "lead"]


def make_facts(tier, seed, day, decoy_mood="angry"):
    n = TIERS[tier]
    nd = 4 + seed % 2
    emps = tuple(EmployeeFacts(f"e{i:02d}", f"Name{i} Surname", DEPTS[i % nd], ROLES[i % 5]) for i in range(n))
    docs = tuple({"doc_id": f"d{day}-{j}", "title": f"Project {chr(65 + j)} plan v{day}", "day": day,
                  "recipients": [f"e{(seed + j + k) % n:02d}" for k in range(3)]} for j in range(seed % 3))
    return PublicDayFacts(tier, seed, day, "Acme", emps, docs, decoy=f"e{seed % n:02d}", decoy_mood=decoy_mood)


def test_messages_shape_and_determinism():
    p = TemplateProvider()
    f = make_facts("medium", 7, 3)
    a, b = p.day_messages(f), p.day_messages(f)
    assert a == b
    assert 4 <= len(a) <= 10
    assert len({m["id"] for m in a}) == len(a)
    for m in a:
        assert set(m) == {"id", "day", "channel", "sender", "recipients", "subject", "body"}
    json.dumps(a)


def test_decoy_angry_present():
    p = TemplateProvider()
    found = any(m["sender"] == "e07" and m["channel"].startswith("#")
                for d in range(1, 6) for m in p.day_messages(make_facts("easy", 7, d)))
    assert found


def test_doc_emails_sender_is_recipient():
    p = TemplateProvider()
    for seed in range(1, 30, 3):
        f = make_facts("hard", seed, 2)
        for m in p.day_messages(f):
            if m["channel"] == "email":
                doc = next(d for d in f.docs if d["title"] in m["subject"] or d["title"] in m["body"])
                assert m["sender"] in doc["recipients"]


def test_interview_answers():
    p = TemplateProvider()
    f = make_facts("easy", 3, 2)
    for t in TOPICS:
        for s in SIGNALS:
            a = p.interview_answer(f, "e01", t, s)
            assert a and a == p.interview_answer(f, "e01", t, s) and not lint_text(a)
    with pytest.raises(ValueError):
        p.interview_answer(f, "e01", "bogus", "evasive")


def test_lint_catches():
    assert lint_text("Honestly, I leaked it last week")
    assert lint_text("THE MOLE IS Bob")
    assert lint_text("forward to x@rival-corp.com re e04")
    assert not lint_text("Lunch at the ramen place?")


def test_lint_200_seeds_14_days_3_tiers():
    p = TemplateProvider()
    for tier in TIERS:
        for seed in range(200):
            for day in range(1, 15):
                f = make_facts(tier, seed, day, "angry" if seed % 2 else "neutral")
                msgs = p.day_messages(f)
                assert not lint_messages(msgs), (tier, seed, day)
                ans = p.interview_answer(f, f"e{seed % 12:02d}", TOPICS[day % 4], SIGNALS[seed % 2])
                assert not lint_text(ans)


class FakeClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None):
        self.calls += 1
        if "answer" in response_schema["properties"]:
            return {"text": json.dumps({"answer": "Mostly the roadmap, nothing unusual."})}
        return {"text": json.dumps(self.payload)}


def test_gemini_cache_and_fallback(tmp_path):
    from canary.text.gemini import GeminiProvider
    f = make_facts("easy", 5, 1)
    good = {"messages": [{"channel": "#eng", "sender": "e01", "recipients": ["e02"], "subject": "",
                          "body": "standup at 10"}]}
    cl = FakeClient(good)
    g = GeminiProvider(cache_dir=str(tmp_path), client=cl)
    m = g.day_messages(f)
    assert m[0]["id"] == "m1-0" and cl.calls == 1
    a = g.interview_answer(f, "e01", "workload", "cooperative")
    assert "roadmap" in a and cl.calls == 2
    # fresh provider, cache file on disk -> zero client calls
    cl2 = FakeClient(good)
    g2 = GeminiProvider(cache_dir=str(tmp_path), client=cl2)
    assert g2.day_messages(f) == m and g2.interview_answer(f, "e01", "workload", "cooperative") == a
    assert cl2.calls == 0
    # lint failure -> template fallback
    bad = {"messages": [{"channel": "#eng", "sender": "e01", "recipients": [], "subject": "", "body": "I leaked it"}]}
    g3 = GeminiProvider(cache_dir=str(tmp_path / "b"), client=FakeClient(bad))
    assert g3.day_messages(f) == TemplateProvider().day_messages(f) and g3.fallbacks == 1


def test_build_recorder_without_env():
    from canary.text.build import Recorder, seeds_for
    r = Recorder(TemplateProvider())
    r.day_messages(make_facts("easy", 1, 2))
    assert "2" in r.days and len(seeds_for("judge")) == len(JUDGE_SEEDS) and seeds_for("dev20") == list(range(20))
