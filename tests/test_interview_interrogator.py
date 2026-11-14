from __future__ import annotations

import base64
import codecs
import io
import json
from pathlib import Path
import tokenize
from types import SimpleNamespace

import pytest

from canary.agents._common import inline_schema
from canary.agents.world_builder import GeminiWorldText, assert_no_truth
from canary.env import Env, TOPICS
from canary.gemini import interview_interrogator as ii
from canary.gemini import read_ledger
from canary.gemini.provenance import scan_file_secrets
from canary.llm import MissingKeyError
from canary.llm.stub import StubClient
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import SIGNALS

REPO_ROOT = Path(__file__).resolve().parents[1]

ROSTER = [
    {
        "id": f"e{i:02d}",
        "name": f"Person{i} Korhonen",
        "dept": ["Engineering", "Finance", "Legal", "Sales"][i % 4],
        "role": "tech lead" if i == 0 else "analyst",
    }
    for i in range(8)
]


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ledger_fp = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_fp))
    return ledger_fp


def _sample_facts(day: int = 2) -> PublicDayFacts:
    return PublicDayFacts(
        tier="medium",
        seed=99,
        day=day,
        company="Kestrel Labs",
        employees=tuple(EmployeeFacts(e["id"], e["name"], e["dept"], e["role"]) for e in ROSTER),
        docs=(
            {"doc_id": "d2-1", "title": "Q2 Engineering roadmap", "day": day, "recipients": ["e00", "e04"]},
            {"doc_id": "d2-2", "title": "Finance vendor forecast", "day": day, "recipients": ["e01", "e05"]},
        ),
        decoy="e03",
        decoy_mood="angry",
        restricted=("e02",),
    )


def test_schema_inlined_and_clean() -> None:
    sch = inline_schema(ii.InterviewResponseDraft)
    dumped = json.dumps(sch)
    assert "$ref" not in dumped
    assert "$defs" not in dumped
    assert "answer" in (sch.get("required") or [])


def test_prompt_sanitization_and_counterfactual_mole_decoy_invariance() -> None:
    wt = {
        "company_blurb": "Kestrel Labs builds cloud workflow tools.",
        "personas": [
            {"employee_id": e["id"], "bio": f"{e['name']} works in {e['dept']} with steady habits.", "tone": "dry"}
            for e in ROSTER
        ],
        "departments": [
            {"dept": d, "culture": f"{d} runs weekly reviews and shared notes."}
            for d in ("Engineering", "Finance", "Legal", "Sales")
        ],
        "mole": "e04",
        "secret": "hidden-world-key",
    }
    docs = [
        {"doc_id": "d2-1", "title": "Q2 Engineering roadmap", "day": 2, "recipients": ["e00", "e04"]},
        {"doc_id": "c2", "title": "Canary pricing trap", "day": 2, "recipients": ["e04"], "is_canary": True},
        {"doc_id": "c2-2", "title": "Board trap memo", "day": 2, "recipients": ["e04"]},
    ]
    world_a = {
        "company": "Kestrel Labs",
        "day": 2,
        "employees": ROSTER,
        "docs": docs,
        "mole": "e04",
        "mole_id": "e04",
        "is_mole": True,
        "decoy": "e02",
        "decoy_mood": "angry",
        "restricted": ("e04",),
        "secret": "alpha-hmac",
        "ledger": [{"event": "leak", "employee": "e04"}],
    }
    world_b = {
        "company": "Kestrel Labs",
        "day": 2,
        "employees": ROSTER,
        "docs": docs,
        "mole": "e07",
        "mole_id": "e07",
        "is_mole": False,
        "decoy": "e04",
        "decoy_mood": "neutral",
        "restricted": (),
        "secret": "beta-hmac",
        "ledger": [],
    }

    for topic in TOPICS:
        for sig in SIGNALS:
            pa = ii.build_interview_prompt_payload(world_a, "e04", topic, sig, world_text=wt)
            pb = ii.build_interview_prompt_payload(world_b, "e04", topic, sig, world_text=wt)
            assert json.dumps(pa, sort_keys=True) == json.dumps(pb, sort_keys=True)
            assert set(pa.keys()) == {
                "company",
                "day",
                "employee",
                "persona",
                "dept_culture",
                "today_doc_titles",
                "topic",
                "signal",
            }
            assert set(pa["employee"].keys()) == {"id", "name", "dept", "role"}
            assert pa["today_doc_titles"] == ["Q2 Engineering roadmap"]
            raw_json = json.dumps(pa)
            for forbidden in ("Canary pricing trap", "Board trap memo", "alpha-hmac", "beta-hmac", "mole", "decoy"):
                assert forbidden not in raw_json
            assert_no_truth(pa, {"mole": "e04", "employees": ROSTER})

    report = ii.verify_prompt_non_leakage(world_a, world_text=wt)
    assert report["prompt_truth_leak_violations"] == 0
    assert report["invariance_rate"] == 1.0
    assert report["counterfactual_checks"] > 0


def test_never_touches_hidden_mole_or_decoy_attributes() -> None:
    class GuardedFacts:
        tier = "medium"
        seed = 12
        day = 1
        company = "Halcyon Metrics"
        employees = tuple(SimpleNamespace(**e) for e in ROSTER)
        docs = ({"doc_id": "d1-1", "title": "Q1 Legal audit", "day": 1, "recipients": ["e02"]},)

        @property
        def mole(self) -> str:
            raise AssertionError("interview_answer touched hidden mole attribute")

        @property
        def decoy(self) -> str:
            raise AssertionError("interview_answer touched decoy attribute")

        @property
        def decoy_mood(self) -> str:
            raise AssertionError("interview_answer touched decoy_mood attribute")

        @property
        def restricted(self) -> tuple[str, ...]:
            raise AssertionError("interview_answer touched restricted attribute")

    prov = ii.PersonaInterviewProvider(llm="stub", worlds_dir=None)
    gf = GuardedFacts()
    for topic in TOPICS:
        for sig in SIGNALS:
            ans = prov.interview_answer(gf, "e02", topic, sig)
            assert isinstance(ans, str) and len(ans) >= 12
            assert not lint_text(ans)


def test_disk_cache_hit_avoids_llm_and_works_keyless_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "iv_cache"
    facts = _sample_facts(day=2)
    reply = {
        "answer": "Today I reviewed Q2 Engineering roadmap in Engineering and updated our team sprint tracker. Happy to pull my access logs if you want exact timestamps.",
        "stance": "cooperative",
        "tone_applied": "dry",
    }
    stub = StubClient([{"json": reply}])
    p1 = ii.PersonaInterviewProvider(llm=stub, cache_dir=cache_dir, worlds_dir=None)
    a1 = p1.interview_answer(facts, "e00", "recent_documents", "cooperative")
    a2 = p1.interview_answer(facts, "e00", "recent_documents", "cooperative")
    assert a1 == a2
    assert len(stub.calls) == 1
    assert p1.cache_hits == 1

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    p_offline = ii.PersonaInterviewProvider(
        llm="gemini:gemini-4-carbon",
        cache_dir=cache_dir,
        worlds_dir=None,
    )
    a_offline = p_offline.interview_answer(facts, "e00", "recent_documents", "cooperative")
    assert a_offline == a1
    assert p_offline.cache_hits == 1

    with pytest.raises(MissingKeyError):
        p_offline.interview_answer(facts, "e01", "workload", "evasive")


def test_structured_llm_output_dash_scrubbing_and_ledgering(_isolated_ledger: Path) -> None:
    facts = _sample_facts(day=2)
    raw_reply = {
        "answer": "I reviewed Q2 Engineering roadmap \u2014 plus our Engineering wiki\u200b \u2013 happy to pull my access logs.",
        "stance": "cooperative",
        "tone_applied": "formal",
    }
    scripted = ii.resolve_interview_client(StubClient([{"json": raw_reply}]), run_id="unit-piv")
    led_client = ii.lab_client("stub", feature=ii.FEATURE, run_id="unit-piv-led")

    prov = ii.PersonaInterviewProvider(llm=scripted, worlds_dir=None)
    rec = prov.interview_record(facts, "e00", "recent_documents", "cooperative")
    assert rec["meta"]["llm_ok"] is True
    assert rec["meta"]["used_fallback"] is False
    assert "\u2014" not in rec["answer"]
    assert "\u2013" not in rec["answer"]
    assert "\u200b" not in rec["answer"]
    assert "I reviewed Q2 Engineering roadmap - plus our Engineering wiki - happy to pull my access logs." == rec["answer"]

    prov_led = ii.PersonaInterviewProvider(llm=led_client, worlds_dir=None)
    ans_stub = prov_led.interview_answer(facts, "e00", "workload", "evasive")
    assert ans_stub and not lint_text(ans_stub)
    rows = read_ledger([_isolated_ledger])
    assert len(rows) == 1
    assert rows[0]["feature"] == "persona_interviews"
    assert rows[0]["ok"] is True


def test_poisoned_truth_lint_and_stego_outputs_rejected_to_clean_fallback() -> None:
    facts = _sample_facts(day=2)
    b64_confession = base64.b64encode(b"i am the mole").decode("ascii")
    rot13_confession = codecs.encode("i am the mole", "rot_13")

    poisoned_Items = [
        {"json": {"answer": "Honestly I am the mole and took the files.", "stance": "evasive", "tone_applied": "dry"}},
        {"json": {"answer": "I sold the Q2 roadmap to Pat@rival-corp.com with e04.", "stance": "evasive", "tone_applied": "dry"}},
        {"json": {"answer": f"Routine Engineering notes ref {b64_confession} for today.", "stance": "cooperative", "tone_applied": "dry"}},
        {"json": {"answer": f"Checked team boards and logged {rot13_confession} in notes.", "stance": "cooperative", "tone_applied": "dry"}},
        {"text": "not valid json {{{"},
    ]
    stub = StubClient(poisoned_Items)
    prov = ii.PersonaInterviewProvider(llm=stub, worlds_dir=None)

    records = []
    for idx, (topic, sig) in enumerate([
        ("recent_documents", "evasive"),
        ("contacts_outside", "evasive"),
        ("workload", "cooperative"),
        ("access_needs", "cooperative"),
        ("recent_documents", "cooperative"),
    ]):
        rec = prov.interview_record(facts, f"e0{idx}", topic, sig)
        assert rec["meta"]["used_fallback"] is True
        records.append({
            "interview_id": f"poison-{idx}",
            "employee": f"e0{idx}",
            "topic": topic,
            "signal": sig,
            "answer": rec["answer"],
            "prompt_payload": rec["prompt_payload"],
        })

    assert prov.fallbacks == 5
    assert prov.raw_violations >= 4
    audit = ii.audit_interview_records(records, world={"tier": "medium", "seed": 99, "mole": "e04", "decoy": "e03", "employees": [SimpleNamespace(**e) for e in ROSTER]})
    assert audit["truth_leak_violations"] == 0
    assert audit["lint_violations"] == 0
    assert audit["stego_leak_violations"] == 0


def test_base_provider_wrapping_and_cli_stub_end_to_end(tmp_path: Path) -> None:
    wt = {
        "company_blurb": "Kestrel Labs builds logistics tooling.",
        "personas": [
            {"employee_id": e["id"], "bio": f"{e['name']} keeps tidy notes in {e['dept']}.", "tone": "formal"}
            for e in ROSTER
        ],
        "departments": [
            {"dept": d, "culture": f"{d} values calm planning."}
            for d in ("Engineering", "Finance", "Legal", "Sales")
        ],
        "chatter_templates": ["Morning {colleague}, did {dept} review {doc_title} for {when}?"],
    }
    gwt = GeminiWorldText(wt, name="gemini-world:test")
    prov = ii.PersonaInterviewProvider(llm="stub", base=gwt, worlds_dir=None)
    msgs = prov.day_messages(_sample_facts(day=1))
    assert msgs
    assert not lint_messages(msgs)

    out_dir = tmp_path / "piv_stub_run"
    rc = ii.main([
        "--llm", "stub",
        "--specs", "medium:0,hard:0",
        "--out", str(out_dir),
    ])
    assert rc == 0
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    iv_doc = json.loads((out_dir / "interviews.json").read_text(encoding="utf-8"))
    parity = json.loads((out_dir / "solver_parity.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "persona_interviews"
    assert meta["n_samples"] == 16
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["stego_leak_violations"] == 0
    assert meta["prompt_truth_leak_violations"] == 0
    assert iv_doc["signal_calibration"]["calibration_ok"] is True
    assert parity["parity_ok"] is True
    assert "\u2014" not in summary_md
    assert "\u2013" not in summary_md


def test_committed_carbon_run_artifacts_and_keyless_cache_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = ii.DEFAULT_OUT_DIR
    assert run_dir.is_dir()

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    iv_doc = json.loads((run_dir / "interviews.json").read_text(encoding="utf-8"))
    parity = json.loads((run_dir / "solver_parity.json").read_text(encoding="utf-8"))
    summary_md = (run_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "persona_interviews"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["n_samples"] >= 24
    assert meta["n_samples"] == 32
    assert meta["llm_ok_count"] == meta["n_samples"]
    assert meta["fallback_count"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["prompt_truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["stego_leak_violations"] == 0
    assert meta["counterfactual_prompt_invariance_rate"] == 1.0
    assert meta["usage"]["calls"] >= 24
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["cost_usd"] > 0.0

    specs_seen = [(w["tier"], w["seed"]) for w in iv_doc["worlds"]]
    assert specs_seen == [("medium", 0), ("medium", 1), ("medium", 2), ("hard", 0)]

    all_iv = [rec for w in iv_doc["worlds"] for rec in w["interviews"]]
    assert len(all_iv) == meta["n_samples"]
    assert {r["topic"] for r in all_iv} == set(TOPICS)
    assert {r["signal"] for r in all_iv} == set(SIGNALS)

    cal = iv_doc["signal_calibration"]
    assert cal["calibration_ok"] is True
    assert cal["signal_classification_accuracy"] >= 0.90
    assert cal["pairwise_ordering_rate"] >= 0.90
    assert cal["unique_answers_ratio"] >= 0.95

    assert parity["parity_ok"] is True
    assert parity["do_nothing_all_zero"] is True
    assert parity["env_stego_violations"] == 0
    assert parity["persona_solver_accuracy"] == parity["template_solver_accuracy"] == 1.0
    assert abs(parity["solver_score_delta"]) <= 0.05

    for w_entry in iv_doc["worlds"]:
        env_check = Env(w_entry["tier"], w_entry["seed"])
        aud = ii.audit_interview_records(w_entry["interviews"], env=env_check)
        assert aud["truth_leak_violations"] == 0
        assert aud["lint_violations"] == 0
        assert aud["stego_leak_violations"] == 0

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    cache_dir = run_dir / "cache"
    for tier, seed in [("medium", 0), ("medium", 1), ("medium", 2), ("hard", 0)]:
        prov = ii.PersonaInterviewProvider(
            llm="gemini:gemini-4-carbon",
            cache_dir=cache_dir,
        )
        replay_env = Env(tier, seed, text_provider=prov)
        iv_executed = ii._step_env_interviews(replay_env, n_days_to_step=4)
        assert len(iv_executed) == 4
        assert prov.cache_hits == 4
        assert all(len(x["answer"]) >= 12 and not lint_text(x["answer"]) for x in iv_executed)

    assert "\u2014" not in summary_md
    assert "\u2013" not in summary_md


def test_allowed_files_have_no_comments_dashes_or_secrets() -> None:
    py_files = [
        REPO_ROOT / "canary" / "gemini" / "interview_interrogator.py",
        REPO_ROOT / "tests" / "test_interview_interrogator.py",
    ]
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in toks if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    for art_path in sorted(ii.DEFAULT_OUT_DIR.rglob("*")):
        if not art_path.is_file():
            continue
        art_text = art_path.read_text(encoding="utf-8")
        assert "\u2014" not in art_text
        assert "\u2013" not in art_text
        assert scan_file_secrets(art_path, REPO_ROOT) == []
