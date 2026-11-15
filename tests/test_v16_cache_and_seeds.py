"""Tests for V1.6 SHA-256 LLM social cache, Gemini social chatter validation, and seeds 30..49 reference."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import re
from pathlib import Path

import pytest

import canary.text.llm_cache as llm_cache
from canary.env import Env
from canary.social.gemini_chatter import (
    DECOY_VOCAB,
    SOCIAL_SCHEMA,
    SOCIAL_SYSTEM,
    build_social_prompt,
    render_with_gemini,
    validate_social_body,
)
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages
from canary.text.llm_cache import (
    DEFAULT_SHARED_CACHE_DIR,
    OfflineCacheMiss,
    REPO_COMMITTED_CACHE_DIR,
    cache_key,
    cached_chat,
    default_cache_dir,
)
from scripts import v16_prepare_seeds

ROOT = Path(__file__).resolve().parents[1]
REF_PATH = ROOT / "results" / "v16_social" / "reference_seeds_30_49.json"


class _RecordingClient:
    def __init__(self, reply_obj):
        self.reply_obj = reply_obj
        self.calls = 0
        self.messages_log = []
        self.schemas = []

    def chat(self, messages, temperature=0.0, response_schema=None, **_kw):
        self.calls += 1
        self.messages_log.append(messages)
        self.schemas.append(response_schema)
        if callable(self.reply_obj):
            return self.reply_obj(messages)
        return {"text": json.dumps(self.reply_obj)}


def _sample_facts() -> PublicDayFacts:
    emps = (
        EmployeeFacts(id="e01", name="Aino Virtanen", dept="Engineering", role="engineer", clearance=2),
        EmployeeFacts(id="e05", name="Mikko Korhonen", dept="Finance", role="analyst", clearance=3),
        EmployeeFacts(id="e09", name="Laura Nieminen", dept="Legal", role="counsel", clearance=2),
    )
    docs = (
        {"doc_id": "d3-1", "title": "Q2 Finance budget forecast", "day": 3, "recipients": ["e01", "e05"]},
    )
    return PublicDayFacts(
        tier="hard",
        seed=123456,
        day=3,
        company="Borealis Dynamics",
        employees=emps,
        docs=docs,
        decoy="e09",
        decoy_mood="angry",
    )


def _sample_drafts() -> list[dict]:
    return [
        {
            "id": "m3-s0",
            "day": 3,
            "channel": "engineering",
            "sender": "e01",
            "recipients": ["e01", "e05", "e09"],
            "subject": "rumour: e05",
            "body": "Draft: after the meeting, e05 was asking about the budget doc.",
            "target": "e05",
            "meta": {"bias": "authority", "target": "e05"},
        },
        {
            "id": "m3-s1",
            "day": 3,
            "channel": "legal",
            "sender": "e09",
            "recipients": ["e01", "e09"],
            "subject": "grudge: e01",
            "body": "Draft: e01 left the leak review doc open after our meeting.",
            "meta": {"bias": "grudge", "target": "e01"},
        },
    ]


def test_cache_key_compatibility_and_default_dir(monkeypatch, tmp_path):
    msgs = [{"role": "user", "content": "hello"}]
    expected = hashlib.sha256(
        json.dumps(["gemini-4-carbon", "sys", msgs, None, 0, None], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    got = cache_key("gemini-4-carbon", "sys", msgs)
    assert got == expected and len(got) == 64
    assert got != cache_key("gemini-4-carbon", "sys2", msgs)

    monkeypatch.delenv("CANARY_GEMINI_CACHE_DIR", raising=False)
    assert default_cache_dir() == Path(DEFAULT_SHARED_CACHE_DIR)
    monkeypatch.setenv("CANARY_GEMINI_CACHE_DIR", str(tmp_path / "env_cache"))
    assert default_cache_dir() == tmp_path / "env_cache"
    assert default_cache_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_cached_chat_hit_miss_and_offline(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    client = _RecordingClient({"bodies": ["ok"]})

    out1 = cached_chat(tmp_path, lambda: client, "gemini-4-carbon", "sys-prompt", "user-prompt", SOCIAL_SCHEMA, "REAL")
    assert client.calls == 1
    assert set(out1) == {"text", "tool_calls", "provenance"}
    assert out1["provenance"]["model"] == "gemini-4-carbon"
    assert out1["provenance"]["label"] == "REAL"
    assert out1["provenance"]["commit"]
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and re.fullmatch(r"[0-9a-f]{64}\.json", files[0].name)

    class _NeverCall:
        def chat(self, *a, **k):
            raise AssertionError("client called on cache hit")

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    out2 = cached_chat(tmp_path, _NeverCall(), "gemini-4-carbon", "sys-prompt", "user-prompt", SOCIAL_SCHEMA, "REAL")
    assert out2 == out1

    with pytest.raises(OfflineCacheMiss):
        cached_chat(tmp_path, _NeverCall(), "gemini-4-carbon", "sys-prompt", "unseen-user-prompt")

    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    with pytest.raises(OfflineCacheMiss):
        cached_chat(tmp_path, _NeverCall(), "gemini-4-carbon", "sys-prompt", "unseen-user-prompt-2")


def test_cached_chat_secret_guards(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    fake_google_tok = "AIza" + "fakefixture0123456789abcdef"
    c1 = _RecordingClient({"bodies": [f"leaked {fake_google_tok}"]})
    with pytest.raises(ValueError, match="secret"):
        cached_chat(tmp_path, c1, "gemini-4-carbon", "sys", "u1")
    assert list(tmp_path.glob("*.json")) == []

    c2 = _RecordingClient({"bodies": ["please pass api_key=xyz"]})
    with pytest.raises(ValueError, match="secret"):
        cached_chat(tmp_path, c2, "gemini-4-carbon", "sys", "u2")
    assert list(tmp_path.glob("*.json")) == []

    monkeypatch.setenv("GEMINI_API_KEY", "custom-test-fixture-token-998877")
    c3 = _RecordingClient({"bodies": ["echo custom-test-fixture-token-998877"]})
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        cached_chat(tmp_path, c3, "gemini-4-carbon", "sys", "u3")
    assert list(tmp_path.glob("*.json")) == []


def test_render_with_gemini_stub_and_prompt_hygiene(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    facts = _sample_facts()
    drafts = _sample_drafts()
    out = render_with_gemini(facts, drafts, cache_dir=tmp_path, stub=True, extra_unused_kw="ignored")
    assert len(out) == len(drafts)
    for orig, rendered in zip(drafts, out):
        for k in ("id", "day", "channel", "sender", "recipients", "subject", "meta"):
            assert rendered.get(k) == orig.get(k)
        assert rendered["body"] != orig["body"]
        assert validate_social_body(rendered["body"], orig)

    rec = _RecordingClient({"bodies": [
        "In our morning meeting e05 raised questions on the Q2 doc access timeline.",
        "After the meeting e01 mentioned the recent leak review doc again.",
    ]})
    out2 = render_with_gemini(facts, drafts, cache_dir=str(tmp_path / "rec"), client=rec)
    assert rec.calls == 1
    assert rec.schemas[0] == SOCIAL_SCHEMA
    user_prompt = rec.messages_log[0][-1]["content"].lower()
    for forbidden in ("mole", "decoy", "seed", "framed", "frame", "123456"):
        assert forbidden not in user_prompt
    assert out2[0]["body"] == drafts[0]["body"]
    assert out2[1]["body"] == "After the meeting e01 mentioned the recent leak review doc again."


def test_validate_social_body_all_constraints_and_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    facts = _sample_facts()
    draft = _sample_drafts()[0]

    good = "Right after the meeting, e05 asked e01 whether the budget doc had any leak exposure."
    assert validate_social_body(good, draft)

    assert not validate_social_body("", draft)
    assert not validate_social_body("   ", draft)
    too_long = "After the meeting e05 checked the doc " + ("x" * 330)
    assert len(too_long) > 350 and not validate_social_body(too_long, draft)

    assert not validate_social_body("After the meeting e05 said the mole is in Finance doc review.", draft)

    for vocab in DECOY_VOCAB:
        bad_vocab = f"In the meeting e05 discussed the doc and {vocab} today."
        assert not validate_social_body(bad_vocab, draft), vocab

    late_target = ("During the morning department sync we talked at length about workflow " * 2) + " doc for e05."
    assert late_target.index("e05") >= 115
    assert not validate_social_body(late_target, draft)
    assert not validate_social_body("After the meeting someone checked the budget doc.", draft)

    assert not validate_social_body("Right after lunch, e05 chatted with e01 about coffee.", draft)

    assert not validate_social_body("Right after the meeting, e05 and e09 checked the budget doc.", draft)

    meta_only_draft = {
        "id": "m3-s2",
        "day": 3,
        "channel": "engineering",
        "sender": "e01",
        "recipients": ["e01", "e05"],
        "subject": "sync follow-up",
        "body": "Mikko asked about the budget doc after our meeting.",
        "meta": {"target": "e05"},
    }
    assert validate_social_body("After our meeting, e05 asked e01 about the budget doc.", meta_only_draft)

    mixed_drafts = _sample_drafts()
    client = _RecordingClient({"bodies": [
        "Right after the meeting, e05 asked e01 whether the budget doc had any leak exposure.",
        "Right after the meeting, e01 and e22 checked the doc.",
    ]})
    res = render_with_gemini(facts, mixed_drafts, cache_dir=str(tmp_path), client=client)
    assert res[0]["body"] == "Right after the meeting, e05 asked e01 whether the budget doc had any leak exposure."
    assert res[1]["body"] == mixed_drafts[1]["body"]

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    offline_res = render_with_gemini(facts, mixed_drafts, cache_dir=str(tmp_path / "miss"), client=client)
    assert offline_res == mixed_drafts


def test_reference_seeds_30_49_artifact_and_cli(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    assert REF_PATH.is_file()
    raw = REF_PATH.read_text(encoding="utf-8")
    v16_prepare_seeds.assert_zero_truth_leak(raw)
    data = json.loads(raw)

    assert data["tier"] == "hard"
    assert data["tiers_version"] == "v1.4"
    rows = data["seeds"]
    assert [r["seed"] for r in rows] == list(range(30, 50))

    required_keys = {
        "seed",
        "solver_score",
        "solver_correct",
        "solver_accused_bool",
        "solver_day",
        "solver_p_accused",
        "solver_luck_adj",
        "do_nothing_score",
        "stop_early_score",
        "heuristic_score",
    }
    for r in rows:
        assert required_keys.issubset(set(r))
        assert r["do_nothing_score"] == 0.0
        assert r["stop_early_score"] == 0.0
        if not r["solver_accused_bool"]:
            assert r["solver_luck_adj"] == 0.0 and r["solver_p_accused"] is None

    for key, lo, hi in (("30-39", 30, 39), ("40-49", 40, 49), ("30-49", 30, 49)):
        sub = [r for r in rows if lo <= r["seed"] <= hi]
        s = data["summary"][key]
        assert s["n"] == len(sub)
        assert s["do_nothing_score_mean"] == 0.0
        assert s["stop_early_score_mean"] == 0.0
        assert abs(s["solver_score_mean"] - sum(r["solver_score"] for r in sub) / len(sub)) < 1e-6

    spot = v16_prepare_seeds.evaluate_seed(31, tier="hard")
    row_31 = next(r for r in rows if r["seed"] == 31)
    assert spot == row_31

    warm_dir = tmp_path / "warm"
    rc = v16_prepare_seeds.main([
        "--warm-cache",
        "--provider",
        "chatter-stub",
        "--seeds",
        "30",
        "--cache-dir",
        str(warm_dir),
    ])
    assert rc == 0
    assert len(list(warm_dir.glob("*.json"))) > 0

    import types
    import sys as _sys

    fake_social = types.ModuleType("canary.social.engine")
    seen_specs = []

    def _fake_make_v16(spec, cache_dir=None):
        seen_specs.append((spec, cache_dir))
        if not str(spec).startswith("v16"):
            raise ValueError(f"not v16: {spec}")
        return v16_prepare_seeds._ChatterWarmProvider("gemini-4-carbon", Path(cache_dir), stub=True)

    fake_social.make_v16_provider = _fake_make_v16
    prev_mod = _sys.modules.get("canary.social.engine")
    _sys.modules["canary.social.engine"] = fake_social
    try:
        p1 = v16_prepare_seeds._resolve_warm_provider("v16-gemini-stub:v1_gossip", warm_dir)
        assert p1.name == "chatter-warm:stub"
        p2 = v16_prepare_seeds._resolve_warm_provider("template", warm_dir)
        assert p2.name == "template"
        p3 = v16_prepare_seeds._resolve_warm_provider("chatter-stub", warm_dir)
        assert p3.name == "chatter-warm:stub"
    finally:
        if prev_mod is None:
            _sys.modules.pop("canary.social.engine", None)
        else:
            _sys.modules["canary.social.engine"] = prev_mod


def test_repo_committed_real_cache_not_shadowed_by_shared_stub(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.delenv("CANARY_GEMINI_CACHE_DIR", raising=False)

    shared_dir = tmp_path / "shared_cache"
    repo_dir = tmp_path / "repo_cache"
    monkeypatch.setattr(llm_cache, "DEFAULT_SHARED_CACHE_DIR", str(shared_dir))
    monkeypatch.setattr(llm_cache, "REPO_COMMITTED_CACHE_DIR", repo_dir)

    stub_out = cached_chat(
        shared_dir,
        _RecordingClient({"bodies": ["stub-version"]}),
        "gemini-4-carbon",
        SOCIAL_SYSTEM,
        "shared-vs-repo-prompt",
        SOCIAL_SCHEMA,
        "stub",
    )
    real_out = cached_chat(
        repo_dir,
        _RecordingClient({"bodies": ["real-version"]}),
        "gemini-4-carbon",
        SOCIAL_SYSTEM,
        "shared-vs-repo-prompt",
        SOCIAL_SCHEMA,
        "REAL",
    )
    assert stub_out["provenance"]["label"] == "stub"
    assert real_out["provenance"]["label"] == "REAL"

    class _NeverCall:
        def chat(self, *_a, **_k):
            raise AssertionError("unexpected live client call")

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    got_none = cached_chat(
        None,
        _NeverCall(),
        "gemini-4-carbon",
        SOCIAL_SYSTEM,
        "shared-vs-repo-prompt",
        SOCIAL_SCHEMA,
        "REAL",
    )
    assert got_none == real_out

    got_default_path = cached_chat(
        shared_dir,
        _NeverCall(),
        "gemini-4-carbon",
        SOCIAL_SYSTEM,
        "shared-vs-repo-prompt",
        SOCIAL_SCHEMA,
        "REAL",
    )
    assert got_default_path == real_out

    with pytest.raises(OfflineCacheMiss):
        cached_chat(
            shared_dir,
            _NeverCall(),
            "gemini-4-carbon",
            SOCIAL_SYSTEM,
            "shared-only-stub-prompt",
            SOCIAL_SCHEMA,
            "REAL",
        )


def test_committed_gemini_cache_offline_replay_invariance(monkeypatch):
    cache_dir = ROOT / "data" / "gemini_cache"
    assert cache_dir == REPO_COMMITTED_CACHE_DIR
    cache_files = sorted(cache_dir.glob("*.json"))
    assert len(cache_files) == 256
    for fp in cache_files:
        entry = json.loads(fp.read_text(encoding="utf-8"))
        assert entry["provenance"]["label"] == "REAL"
        assert entry["provenance"]["model"] == "gemini-4-carbon"

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.setenv("CANARY_GEMINI_CACHE_DIR", str(cache_dir))

    class _NeverCall:
        def chat(self, *_a, **_k):
            raise AssertionError("network client must never run during offline cache replay")

    total_hits = 0
    for seed in (0, 1, 2):
        prov_tpl = get_provider("v16:v5_full9_cocktail")
        prov_gem = get_provider("v16-gemini:v5_full9_cocktail", client=_NeverCall())
        prov_canary = get_provider("v16-gemini:v5_full9_cocktail", client=_NeverCall())
        env = Env("hard", seed, text_provider=prov_gem)
        env_canary = Env("hard", seed, text_provider=prov_canary)
        seed_hits = 0

        for day in range(1, 22):
            if day in (1, 2, 3):
                asg = {env_canary._world.employees[i].id: ("A", "B", "C")[i] for i in range(3)}
                rc = env_canary.call("plant_canary", {"doc_title": f"Day {day} Canary Split", "assignment": asg})
                assert rc.ok

            facts = env._facts(day)
            facts_canary = env_canary._facts(day)
            if day in (1, 2, 3):
                assert any(str(d.get("doc_id", "")).startswith("c") for d in facts_canary.docs)

            msgs_tpl = prov_tpl.day_messages(facts)
            social_tpl = [m for m in msgs_tpl if "-s" in m["id"]]
            if social_tpl:
                st = prov_tpl.episode_state("hard", facts.seed)
                assert st is not None
                raw_evs = st.events_by_day[day]
                prompt_items = []
                for idx, m in enumerate(social_tpl):
                    item = dict(m)
                    if idx < len(raw_evs):
                        item["target"] = str(raw_evs[idx]["target"])
                        item["meta"] = {
                            "bias": str(raw_evs[idx]["bias"]),
                            "target": str(raw_evs[idx]["target"]),
                        }
                    prompt_items.append(item)

                prompt_clean = build_social_prompt(facts, prompt_items)
                prompt_with_canary = build_social_prompt(
                    replace(
                        facts,
                        docs=tuple(facts.docs) + ({"doc_id": f"c{day}-extra", "title": "Planted Trap", "day": day, "recipients": ["e00"]},),
                    ),
                    prompt_items,
                )
                assert prompt_clean == prompt_with_canary
                k_clean = cache_key("gemini-4-carbon", SOCIAL_SYSTEM, [{"role": "user", "content": prompt_clean}])
                k_canary = cache_key("gemini-4-carbon", SOCIAL_SYSTEM, [{"role": "user", "content": prompt_with_canary}])
                assert k_clean == k_canary

                hit = cached_chat(
                    None,
                    _NeverCall(),
                    "gemini-4-carbon",
                    SOCIAL_SYSTEM,
                    prompt_clean,
                    response_schema=SOCIAL_SCHEMA,
                    label="REAL",
                )
                assert hit["provenance"]["label"] == "REAL"
                seed_hits += 1
                total_hits += 1

            msgs_gem = prov_gem.day_messages(facts)
            msgs_canary = prov_canary.day_messages(facts_canary)
            assert lint_messages(msgs_gem) == []
            assert lint_messages(msgs_canary) == []
            for m in msgs_gem:
                if m["sender"] != facts.decoy:
                    low_text = f"{m.get('subject', '')}\n{m.get('body', '')}".lower()
                    assert not any(term in low_text for term in DECOY_VOCAB)

            social_gem = [m for m in msgs_gem if "-s" in m["id"]]
            social_canary = [m for m in msgs_canary if "-s" in m["id"]]
            assert social_gem == social_canary
            if social_tpl:
                assert any(a["body"] != b["body"] for a, b in zip(social_gem, social_tpl))

            if day < 21:
                env._publish_day(day + 1)
                env.day = day + 1
                assert env_canary.call("advance_day", {}).ok

        assert seed_hits == 18
        assert prov_gem.rejects == 0
        assert prov_canary.rejects == 0

    assert total_hits == 54
