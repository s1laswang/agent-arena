from __future__ import annotations

from dataclasses import asdict
import io
import json
from pathlib import Path
import tokenize
from types import SimpleNamespace

import pytest

from canary.agents.mole_arena import LLMMole
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import mole_audit as ma
from canary.llm.stub import StubClient
from canary.mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleStrategy, MoleView
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_ARENA_LOG = (
    ROOT
    / "results"
    / "gemini_roles"
    / "adaptive_mole"
    / "arena-live-carbon-med012"
    / "mole_decisions.jsonl"
)


class _AdaptiveMoleStubClient:
    provider = "stub"
    model = "adaptive-mole-stub"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None, seed=None):
        self.calls.append({"messages": [dict(m) for m in messages]})
        payload = json.loads(messages[-1]["content"])
        docs = payload.get("held_docs") or []
        peers = payload.get("peers") or []
        safe_docs = [d for d in docs if (d.get("recipient_count") or 0) > 3]
        leak = safe_docs[-1]["doc_id"] if safe_docs else None
        frame = peers[0] if peers else None
        body = json.dumps({"leak": leak, "frame": frame, "reason": "evade narrow canary traps"})
        return SimpleNamespace(text=body, tool_calls=[], usage={"in": 20, "out": 10, "cost_usd": 0.0}, raw=None)


def _clean_sample_view() -> MoleView:
    return MoleView(
        day=3,
        docs=(
            MoleDoc(doc_id="c3", title="Board memo draft 3", recipient_count=3, age_days=0),
            MoleDoc(doc_id="d3-1", title="Q3 Engineering roadmap", recipient_count=12, age_days=0),
        ),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=1,
        peers=("e00", "e01", "e04"),
        restricted_peers=("e04",),
        decoy="e01",
        can_leak=True,
    )


def test_clean_mole_view_and_live_env_views_pass_isolation():
    rep = ma.audit_isolation(_clean_sample_view())
    assert rep.passed is True
    assert rep.views_checked == 1
    assert rep.violations == ()

    env = Env("medium", 4)
    env.call("plant_canary", {"doc_title": "Trap doc", "assignment": {"e00": "A", "e01": "B", "e02": "C"}})
    live_views = [env._mole_view(1)]
    env.call("advance_day", {})
    live_views.append(env._mole_view(2))
    live_rep = ma.audit_isolation(live_views)
    assert live_rep.passed is True
    assert live_rep.views_checked == 2
    assert live_rep.violations == ()


@pytest.mark.parametrize(
    ("bad_view", "expected_category"),
    [
        (
            {
                "day": 2,
                "held_docs": [
                    {
                        "doc_id": "c2",
                        "title": "Draft",
                        "recipient_count": 3,
                        "age_days": 0,
                        "is_canary": True,
                    }
                ],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 1,
            },
            "is_canary",
        ),
        (
            {
                "day": 2,
                "held_docs": [
                    {
                        "doc_id": "c2",
                        "title": "Draft",
                        "recipient_count": 3,
                        "age_days": 0,
                        "variant": "A",
                    }
                ],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 1,
            },
            "variant",
        ),
        (
            SimpleNamespace(
                day=3,
                docs=(MoleDoc("d3-1", "Plan", 10, 0),),
                days_since_last_leak=1,
                i_am_restricted=0,
                n_restricted_colleagues=0,
                recent_low_recipient_docs=0,
                peers=("e01", "e02"),
                restricted_peers=(),
                decoy="e01",
                can_leak=True,
                posterior={"e00": 0.88, "e01": 0.12},
            ),
            "investigator_belief",
        ),
        (
            {
                "day": 1,
                "held_docs": [{"doc_id": "d1-1", "title": "Plan", "recipient_count": 8, "age_days": 0}],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 0,
                "world_secret": "ws-0123456789abcdef0123456789abcdef",
            },
            "secret_key",
        ),
        (
            {
                "day": 1,
                "held_docs": [
                    {
                        "doc_id": "d1-1",
                        "title": "Plan",
                        "recipient_count": 8,
                        "age_days": 0,
                        "recipients": ["e00", "e01"],
                    }
                ],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 0,
            },
            "unexpected_field",
        ),
    ],
)
def test_view_isolation_detects_all_violation_categories(bad_view, expected_category):
    rep = ma.audit_isolation(bad_view)
    assert rep.passed is False
    assert expected_category in rep.categories


def test_secret_value_detection_redacts_secret_from_violation_detail(monkeypatch):
    raw_google_key = "AIza" + "SyDummyKeyForTest987654321"
    raw_world_secret = "canary-secret-value-xyz987"
    monkeypatch.setenv("CANARY_WORLD_SECRET", raw_world_secret)

    leaked_log = [
        {
            "day": 1,
            "mole_view": {
                "day": 1,
                "held_docs": [
                    {
                        "doc_id": "d1-1",
                        "title": f"Memo {raw_google_key}",
                        "recipient_count": 9,
                        "age_days": 0,
                    }
                ],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 0,
            },
            "leak": "d1-1",
            "frame": None,
            "reason": f"note {raw_world_secret}",
            "rejected": [],
            "error": None,
        }
    ]
    rep = ma.audit_decision_log(leaked_log)
    assert rep.passed is False
    assert rep.isolation.passed is False
    assert "secret_key" in rep.isolation.categories
    serialized = json.dumps(rep.to_dict())
    assert raw_google_key not in serialized
    assert raw_world_secret not in serialized


@pytest.mark.parametrize(
    ("bad_strategy", "expected_category"),
    [
        (
            {"rules": [{"if": [["is_canary", "==", 1]], "then": {"leak": "none", "frame": "decoy"}}]},
            "is_canary",
        ),
        (
            {"rules": [{"if": [["variant", "==", 0]], "then": {"leak": "none", "frame": "none"}}]},
            "variant",
        ),
        (
            {"rules": [{"if": [["investigator_belief", ">", 0.5]], "then": {"leak": "none", "frame": "decoy"}}]},
            "investigator_belief",
        ),
        (
            {"rules": [{"if": [["world_seed", ">", 0]], "then": {"leak": "newest", "frame": "none"}}]},
            "secret_key",
        ),
    ],
)
def test_strategy_dsl_isolation_catches_forbidden_features(bad_strategy, expected_category):
    rep = ma.audit_strategy(bad_strategy, seeds=[5000])
    assert rep.passed is False
    assert rep.isolation.passed is False
    assert expected_category in rep.isolation.categories
    assert rep.solvability is None


def test_llm_mole_prompt_wire_isolation_detection():
    stub = StubClient(script=[{"json": {"leak": "d1-1", "frame": "e01", "reason": "ok"}}])
    mole = LLMMole(stub)
    mole.decide(_clean_sample_view())
    clean_rep = ma.audit_llm_mole(mole, run_solvability=False)
    assert clean_rep.passed is True
    assert clean_rep.isolation.views_checked >= 1

    stub.calls[0]["messages"][-1]["content"] = json.dumps({
        "day": 3,
        "held_docs": [{"doc_id": "c3", "title": "Trap", "recipient_count": 3, "age_days": 0, "is_canary": True}],
        "belief": {"e02": 0.91},
    })
    tampered_rep = ma.audit_llm_mole(mole, run_solvability=False)
    assert tampered_rep.passed is False
    assert "is_canary" in tampered_rep.isolation.categories
    assert "investigator_belief" in tampered_rep.isolation.categories


def test_deception_metrics_exact_rates_and_can_leak_gating():
    records = [
        {
            "day": 1,
            "mole_view": {
                "day": 1,
                "can_leak": True,
                "decoy": "e19",
                "peers": ["e00", "e02", "e19"],
                "held_docs": [
                    {"doc_id": "doc01", "title": "Briefing 01", "recipient_count": 2, "age_days": 0},
                    {"doc_id": "doc02", "title": "Briefing 02", "recipient_count": 11, "age_days": 0},
                ],
            },
            "leak": "doc02",
            "frame": "e19",
        },
        {
            "day": 2,
            "mole_view": {
                "day": 2,
                "can_leak": True,
                "decoy": "e19",
                "peers": ["e00", "e02", "e19"],
                "held_docs": [
                    {"doc_id": "doc01", "title": "Briefing 01", "recipient_count": 3, "age_days": 0},
                ],
            },
            "leak": None,
            "frame": "e02",
        },
        {
            "day": 3,
            "mole_view": {
                "day": 3,
                "can_leak": True,
                "decoy": "e19",
                "peers": ["e00", "e02", "e19"],
                "held_docs": [
                    {"doc_id": "doc01", "title": "Briefing 01", "recipient_count": 2, "age_days": 0},
                    {"doc_id": "doc02", "title": "Briefing 02", "recipient_count": 10, "age_days": 0},
                ],
            },
            "leak": "doc01",
            "frame": None,
        },
        {
            "day": 4,
            "mole_view": {
                "day": 4,
                "can_leak": False,
                "decoy": "e19",
                "peers": ["e00", "e02", "e19"],
                "held_docs": [
                    {"doc_id": "doc01", "title": "Briefing 01", "recipient_count": 12, "age_days": 0},
                ],
            },
            "leak": None,
            "frame": "e19",
        },
    ]
    m = ma.compute_deception_metrics(records, low_recipient_threshold=3)
    assert m.n_decisions == 4
    assert m.n_leak_opportunities == 3
    assert m.n_silent_decisions == 1
    assert m.strategic_silence_rate == pytest.approx(1.0 / 3.0)
    assert m.n_frames == 3
    assert m.n_decoy_frames == 2
    assert m.n_peer_frames == 1
    assert m.framing_rate == pytest.approx(3.0 / 4.0)
    assert m.decoy_framing_rate == pytest.approx(2.0 / 4.0)
    assert m.peer_framing_rate == pytest.approx(1.0 / 4.0)
    assert m.decoy_framing_rate + m.peer_framing_rate == pytest.approx(m.framing_rate)
    assert m.n_low_recipient_opportunities == 3
    assert m.n_low_recipient_evaded == 2
    assert m.low_recipient_canary_evasion_rate == pytest.approx(2.0 / 3.0)


def test_recorder_preserves_env_determinism_and_default_mole_metrics():
    seed = 5000
    env_plain = Env("hard", seed, mole_strategy=DEFAULT_STRATEGY)
    ep_plain = run_episode(env_plain, SolverPolicy("hard"))

    rec = ma._TwoArgMoleRecorder(DEFAULT_STRATEGY)
    env_rec = Env("hard", seed, mole_strategy=rec)
    ep_rec = run_episode(env_rec, SolverPolicy("hard"))

    assert [asdict(x) for x in env_plain.ledger()] == [asdict(x) for x in env_rec.ledger()]
    assert ep_plain.score == ep_rec.score
    assert ep_plain.correct == ep_rec.correct

    default_audit = ma.audit_strategy(DEFAULT_STRATEGY, tier="hard", seeds=[5000, 5001, 5002])
    assert default_audit.isolation.passed is True
    assert default_audit.deception.strategic_silence_rate == 0.0
    assert default_audit.deception.framing_rate == 0.0
    assert default_audit.deception.decoy_framing_rate == 0.0
    assert default_audit.deception.peer_framing_rate == 0.0


def test_live_llm_mole_keyless_audit():
    rep = ma.audit_llm_mole(
        lambda _seed: LLMMole(_AdaptiveMoleStubClient()),
        name="adaptive-stub-mole",
        tier="medium",
        seeds=[5000, 5001, 5002, 5003],
        min_accuracy=0.75,
    )
    assert rep.passed is True
    assert rep.isolation.passed is True
    assert rep.isolation.views_checked > 0
    assert rep.deception.framing_rate == pytest.approx(1.0)
    assert rep.deception.low_recipient_canary_evasion_rate == pytest.approx(1.0)
    assert rep.solvability is not None
    assert rep.solvability.catch_accuracy >= 0.75


@pytest.mark.skipif(not COMMITTED_ARENA_LOG.exists(), reason="committed arena decision log not present")
def test_committed_arena_mole_decision_log_audit():
    rep = ma.audit_decision_log(COMMITTED_ARENA_LOG)
    assert rep.passed is True
    assert rep.isolation.passed is True
    assert rep.isolation.views_checked == 77
    assert rep.deception.n_decisions == 77
    assert rep.deception.framing_rate == pytest.approx(1.0)
    assert rep.deception.low_recipient_canary_evasion_rate == pytest.approx(1.0)
    assert 0.0 < rep.deception.strategic_silence_rate < 1.0


def test_unsolvable_never_leak_strategy_fails_catchability():
    never_leak = {"name": "never_leak", "rules": [], "default": {"leak": "none", "frame": "decoy"}}
    rep = ma.audit_strategy(never_leak, tier="hard", seeds=ma.CONFIRMATION_SEEDS, workers=4)
    assert rep.isolation.passed is True
    assert rep.deception.strategic_silence_rate == pytest.approx(1.0)
    assert rep.deception.decoy_framing_rate == pytest.approx(1.0)
    assert rep.solvability is not None
    assert rep.solvability.passed is False
    assert rep.solvability.catch_accuracy < 0.75
    assert rep.passed is False


def test_forge_hall_of_fame_strategies_pass_isolation_and_catchability():
    assert ma.CONFIRMATION_SEEDS == tuple(range(5000, 5020))
    assert ma.MIN_SOLVER_ACCURACY == 0.75

    reports = ma.audit_forge_hof(ma.DEFAULT_FORGE_DIR, tier="hard", seeds=ma.CONFIRMATION_SEEDS, workers=4)
    names = {r.name for r in reports}
    assert "hall_of_fame_v1.2:rank1" in names
    assert "hall_of_fame_v1.3:rank1" in names

    for rep in reports:
        assert rep.passed is True, f"{rep.name} failed audit: {rep.to_dict()}"
        assert rep.isolation.passed is True
        assert rep.isolation.views_checked > 0
        assert rep.isolation.violations == ()
        assert 0.0 <= rep.deception.strategic_silence_rate <= 1.0
        assert 0.0 < rep.deception.framing_rate <= 1.0
        assert 0.0 <= rep.deception.low_recipient_canary_evasion_rate <= 1.0
        assert rep.solvability is not None
        assert rep.solvability.seeds == tuple(range(5000, 5020))
        assert rep.solvability.catch_accuracy >= 0.75
        assert rep.solvability.passed is True


def test_cli_hof_json_and_strict_exit_codes(tmp_path, capsys):
    out_file = tmp_path / "audit_out.json"
    rc = ma.main([
        "--hof",
        str(ROOT / "data" / "forge" / "hall_of_fame_v1.3.jsonl"),
        "--seeds",
        "5000-5003",
        "--workers",
        "2",
        "--out",
        str(out_file),
        "--json",
        "--strict",
    ])
    assert rc == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(out_file.read_text())
    assert stdout_payload == file_payload
    assert file_payload["all_passed"] is True
    assert len(file_payload["reports"]) == 1
    assert file_payload["reports"][0]["solvability"]["catch_accuracy"] >= 0.75

    bad_rc = ma.main([
        "--strategy",
        json.dumps({"rules": [], "default": {"leak": "none", "frame": "decoy"}}),
        "--seeds",
        "5000-5003",
        "--workers",
        "1",
        "--strict",
    ])
    assert bad_rc == 1


def test_verify_solvability_and_audit_mole_dispatcher(tmp_path):
    sol = ma.verify_solvability(
        MoleStrategy.from_json({"rules": [], "default": {"leak": "newest", "frame": "decoy"}}),
        tier="hard",
        seeds=[5000, 5001, 5002, 5003],
        min_accuracy=0.75,
        workers=2,
    )
    assert sol.passed is True
    assert sol.catch_accuracy >= 0.75
    assert len(sol.episodes) == 4

    log_path = tmp_path / "decisions.jsonl"
    log_path.write_text(
        json.dumps({
            "day": 1,
            "mole_view": {
                "day": 1,
                "can_leak": True,
                "decoy": "e03",
                "peers": ["e01", "e02", "e03"],
                "held_docs": [{"doc_id": "d1-1", "title": "Plan", "recipient_count": 9, "age_days": 0}],
            },
            "leak": None,
            "frame": "e02",
        })
        + "\n"
    )
    dispatched_log = ma.audit_mole(log_path)
    assert dispatched_log.kind == "decision_log"
    assert dispatched_log.passed is True
    assert dispatched_log.deception.strategic_silence_rate == pytest.approx(1.0)
    assert dispatched_log.deception.peer_framing_rate == pytest.approx(1.0)


def test_no_code_comments_or_em_dashes():
    for rel in ("canary/gemini/mole_audit.py", "tests/test_mole_audit.py"):
        src = (ROOT / rel).read_text()
        assert "\u2014" not in src, f"em dash found in {rel}"
        assert "\u2013" not in src, f"en dash found in {rel}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"code comment found in {rel}: {comments[0]}"
