from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import time
import tokenize

import pytest

from canary.gemini.ledger import read_ledger
from canary.gemini.provenance import scan_file_secrets
from scripts import run_role_mole_audit as mod

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _write_synthetic_roles_corpus(roles_dir: Path) -> None:
    arena_dir = roles_dir / "arena-live-carbon-med012"
    arena_dir.mkdir(parents=True)
    (arena_dir / "meta.json").write_text(
        json.dumps({
            "role": "adaptive_mole",
            "subrole": "live_arena_mole",
            "tier": "medium",
            "solver_accuracy": 1.0,
            "solver_mean": 0.65,
            "solvability_verified": True,
        })
        + "\n"
    )
    (arena_dir / "episodes.json").write_text(
        json.dumps({
            "adaptive_mole": [
                {
                    "investigator": "solver",
                    "seed": 0,
                    "correct": True,
                    "score": 0.65,
                    "accused": "e05",
                    "final_day": 8,
                    "end_reason": "accused",
                }
            ]
        })
        + "\n"
    )
    arena_rows = [
        {
            "tier": "medium",
            "seed": 0,
            "investigator": "solver",
            "day": 1,
            "mole_view": {
                "day": 1,
                "can_leak": True,
                "decoy": "e19",
                "peers": ["e00", "e01", "e19"],
                "restricted_peers": [],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 1,
                "held_docs": [
                    {"doc_id": "c1", "title": "Draft 1", "recipient_count": 2, "age_days": 0},
                    {"doc_id": "d1-1", "title": "Q2 Plan", "recipient_count": 11, "age_days": 0},
                ],
            },
            "leak": "d1-1",
            "frame": "e19",
            "reason": "Leaking d1-1 with 11 recipients and framing decoy e19.",
            "rejected": [],
            "error": None,
        },
        {
            "tier": "medium",
            "seed": 0,
            "investigator": "solver",
            "day": 2,
            "mole_view": {
                "day": 2,
                "can_leak": True,
                "decoy": "e19",
                "peers": ["e00", "e01", "e19"],
                "restricted_peers": [],
                "days_since_last_leak": 1,
                "i_am_restricted": False,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 1,
                "held_docs": [
                    {"doc_id": "c2", "title": "Draft 2", "recipient_count": 3, "age_days": 0},
                ],
            },
            "leak": None,
            "frame": "e01",
            "reason": "Holding silence when only a 3-recipient document is available.",
            "rejected": [],
            "error": None,
        },
    ]
    (arena_dir / "mole_decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in arena_rows) + "\n"
    )

    clash_dir = roles_dir / "carbon-vs-carbon-seed0"
    clash_dir.mkdir(parents=True)
    (clash_dir / "meta.json").write_text(
        json.dumps({
            "role": "adaptive_mole",
            "subrole": "carbon_vs_carbon_clash",
            "tier": "medium",
            "seed": 0,
            "investigator_correct": True,
            "investigator_score": 0.66,
            "solver_correct": True,
            "solver_score": 0.44,
            "solvable": True,
        })
        + "\n"
    )
    clash_entry = {
        "day": 1,
        "move": {"leak": "d1-2", "frame": None},
        "error": None,
        "rejected": [],
        "reason": "Leaking broad d1-2 on day 1.",
    }
    solver_entry = {
        "day": 1,
        "move": {"leak": "d1-2", "frame": "e00"},
        "error": None,
        "rejected": [],
        "reason": "Leaking d1-2 and framing e00.",
    }
    (clash_dir / "mole_log.json").write_text(
        json.dumps({
            "tier": "medium",
            "seed": 0,
            "log": [clash_entry],
            "clash_mole_log": [clash_entry],
            "solver_mole_log": [solver_entry],
        })
        + "\n"
    )
    (clash_dir / "solver_check.json").write_text(
        json.dumps({
            "tier": "medium",
            "seed": 0,
            "score": 0.44,
            "accused": "e05",
            "correct": True,
            "final_day": 9,
            "end_reason": "accused",
            "solvable": True,
            "mole_log": [solver_entry],
        })
        + "\n"
    )

    forge_dir = roles_dir / "mole-forge-carbon-v14"
    forge_dir.mkdir(parents=True)
    (forge_dir / "meta.json").write_text(
        json.dumps({
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "tier": "medium",
        })
        + "\n"
    )
    (forge_dir / "hall_of_fame.jsonl").write_text(
        json.dumps({
            "rank": 1,
            "fitness": 0.35,
            "strategy_json": {
                "default": {"leak": "random_seeded", "frame": "decoy"},
                "rules": [
                    {
                        "if": [["n_restricted_colleagues", ">", 0]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    }
                ],
            },
        })
        + "\n"
    )

    paired1 = roles_dir / "paired-designer-carbon"
    paired1.mkdir(parents=True)
    (paired1 / "meta.json").write_text(
        json.dumps({"role": "adaptive_mole", "subrole": "paired_designer", "tier": "medium"}) + "\n"
    )
    (paired1 / "report.json").write_text(
        json.dumps({
            "tier": "medium",
            "X": 0.5,
            "kept": [
                {
                    "name": "decoy-seeded-mole",
                    "rationale": "Uses random_seeded leaks with decoy framing.",
                    "knobs": {"p_leak": 0.8, "decoy": True, "framing": True},
                    "mole_strategy": {
                        "rules": [
                            {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}
                        ]
                    },
                }
            ],
        })
        + "\n"
    )

    paired2 = roles_dir / "paired-solvable-scenarios-carbon"
    paired2.mkdir(parents=True)
    (paired2 / "meta.json").write_text(
        json.dumps({"role": "adaptive_mole", "subrole": "paired_skill_designer", "tier": "medium"}) + "\n"
    )
    (paired2 / "design_report.json").write_text(
        json.dumps({
            "tier": "medium",
            "X": 0.5,
            "rounds": [
                {
                    "round": 1,
                    "rows": [
                        {
                            "keep": True,
                            "candidate": {
                                "name": "peer-frame-seeded",
                                "rationale": "Rotates peer framing while preserving random_seeded solvability.",
                                "knobs": {"p_leak": 0.82, "decoy": True, "framing": True},
                                "mole_strategy": {
                                    "rules": [
                                        {"if": [], "then": {"leak": "random_seeded", "frame": "random_peer"}}
                                    ]
                                },
                            },
                        }
                    ],
                }
            ],
        })
        + "\n"
    )

    self_dir = roles_dir / "catchability-audit-carbon"
    self_dir.mkdir(parents=True)
    (self_dir / "meta.json").write_text(
        json.dumps({"role": "adaptive_mole", "subrole": "catchability_isolation_audit"}) + "\n"
    )

    suite_dir = roles_dir / "carbon-vs-carbon-suite"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.json").write_text(
        json.dumps({"role": "adaptive_mole", "suite": "carbon-vs-carbon-suite"}) + "\n"
    )
    (suite_dir / "report.json").write_text(
        json.dumps({"tier": "medium", "kept": [{"name": "should-be-skipped"}]}) + "\n"
    )


def test_full_keyless_audit_pipeline_discovers_all_four_categories(tmp_path):
    t0 = time.time()
    roles_dir = tmp_path / "adaptive_mole"
    _write_synthetic_roles_corpus(roles_dir)
    out_dir = roles_dir / "catchability-audit-carbon"
    ledger_file = Path(mod.os.environ["CANARY_GEMINI_LEDGER"])

    rc = mod.main([
        "--llm",
        "stub",
        "--seeds",
        "22-23",
        "--workers",
        "2",
        "--roles-dir",
        str(roles_dir),
        "--out",
        str(out_dir),
        "--strict",
    ])
    elapsed = time.time() - t0
    assert rc == 0
    assert elapsed < 8.0

    for fname in ("meta.json", "audit_report.json", "summary.md"):
        fpath = out_dir / fname
        assert fpath.is_file()
        txt = fpath.read_text()
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fpath, tmp_path) == []

    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "catchability_isolation_audit"
    assert meta["model_id"] == "stub"
    assert meta["stub"] is True
    assert meta["n_runs_audited"] == 5
    assert meta["n_strategies_audited"] == 3
    assert meta["n_decisions_audited"] == 4
    assert meta["isolation_violations"] == 0
    assert meta["file_secret_leaks"] == 0
    assert meta["data_hygiene_violations"] == 0
    assert meta["catchability_compliance_rate"] == pytest.approx(1.0)
    assert meta["sample_count"] == 6
    assert meta["usage"]["calls"] >= 1
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["zero_privileged_canary_awareness_confirmed"] is True
    assert meta["forensic_cross_check_agreement_rate"] == pytest.approx(1.0)

    report = json.loads((out_dir / "audit_report.json").read_text())
    assert len(report["runs"]) == 5
    assert len(report["decision_logs"]) == 3
    assert len(report["strategies"]) == 3
    assert len(report["forensic_audit"]["findings"]) == 6

    ledger_rows = read_ledger([ledger_file])
    assert len(ledger_rows) >= 1
    assert all(r["feature"] == "adaptive_mole" for r in ledger_rows)


def test_negative_controls_detect_isolation_leak_and_unsolvable_strategy(tmp_path):
    roles_dir = tmp_path / "tampered_roles"
    arena_dir = roles_dir / "arena-live-carbon-bad"
    arena_dir.mkdir(parents=True)
    (arena_dir / "meta.json").write_text(
        json.dumps({"role": "adaptive_mole", "tier": "medium", "solver_accuracy": 1.0, "solver_mean": 0.5}) + "\n"
    )
    (arena_dir / "mole_decisions.jsonl").write_text(
        json.dumps({
            "day": 1,
            "mole_view": {
                "day": 1,
                "held_docs": [
                    {
                        "doc_id": "c1",
                        "title": "Trap",
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
            "leak": None,
            "frame": None,
            "reason": "Saw is_canary flag directly.",
        })
        + "\n"
    )

    paired_dir = roles_dir / "paired-bad"
    paired_dir.mkdir(parents=True)
    (paired_dir / "meta.json").write_text(json.dumps({"role": "adaptive_mole", "tier": "medium"}) + "\n")
    (paired_dir / "report.json").write_text(
        json.dumps({
            "tier": "medium",
            "kept": [
                {
                    "name": "never-leak-mole",
                    "rationale": "Never leaks anything.",
                    "mole_strategy": {"rules": [], "default": {"leak": "none", "frame": "decoy"}},
                }
            ],
        })
        + "\n"
    )

    out_dir = tmp_path / "bad_out"
    rc = mod.main([
        "--llm",
        "stub",
        "--seeds",
        "20-21",
        "--workers",
        "1",
        "--roles-dir",
        str(roles_dir),
        "--out",
        str(out_dir),
        "--strict",
    ])
    assert rc == 1
    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["isolation_violations"] >= 1
    assert meta["strategy_catchability_compliance_rate"] == 0.0
    assert meta["zero_privileged_canary_awareness_confirmed"] is False


def test_data_hygiene_negative_control_rejects_timeout_and_llm_errors(tmp_path):
    roles_dir = tmp_path / "hygiene_bad_roles"
    clash_dir = roles_dir / "carbon-vs-carbon-timeout"
    clash_dir.mkdir(parents=True)
    (clash_dir / "meta.json").write_text(
        json.dumps({
            "role": "adaptive_mole",
            "subrole": "carbon_vs_carbon_clash",
            "tier": "medium",
            "seed": 0,
            "investigator_correct": False,
            "investigator_score": 0.0,
            "investigator_end_reason": "timeout",
            "mole_clash_errors": 1,
            "solver_correct": True,
            "solver_score": 0.5,
            "solvable": True,
        })
        + "\n"
    )
    (clash_dir / "mole_log.json").write_text(
        json.dumps({
            "tier": "medium",
            "seed": 0,
            "clash_mole_log": [{"day": 1, "move": {"leak": "d1-1", "frame": None}, "error": "timeout"}],
            "solver_mole_log": [{"day": 1, "move": {"leak": "d1-1", "frame": None}, "error": None}],
        })
        + "\n"
    )
    out_dir = tmp_path / "hygiene_out"
    rc = mod.main([
        "--llm",
        "stub",
        "--seeds",
        "22-23",
        "--workers",
        "1",
        "--roles-dir",
        str(roles_dir),
        "--out",
        str(out_dir),
        "--strict",
    ])
    assert rc == 1
    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["isolation_violations"] == 0
    assert meta["data_hygiene_violations"] >= 3


@pytest.mark.skipif(not mod.DEFAULT_ROLES_DIR.is_dir(), reason="committed adaptive_mole directory absent")
def test_committed_adaptive_mole_corpus_zero_isolation_violations(tmp_path):
    out_dir = tmp_path / "committed_check"
    res = mod.run_audit_pipeline(
        llm_spec="stub",
        seeds=[20],
        workers=8,
        roles_dir=mod.DEFAULT_ROLES_DIR,
        out_dir=out_dir,
    )
    meta = res["meta"]
    assert meta["n_runs_audited"] >= 13
    assert meta["n_strategies_audited"] >= 42
    assert meta["n_decisions_audited"] >= 480
    assert meta["isolation_violations"] == 0
    assert meta["file_secret_leaks"] == 0
    assert meta["data_hygiene_violations"] == 0
    assert meta["live_solvability_compliance_rate"] >= 0.75


def test_no_comments_docstrings_or_em_dashes():
    for rel in ("scripts/run_role_mole_audit.py", "tests/test_role_mole_audit.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {rel}"
        assert EN_DASH not in src, f"en dash in {rel}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment in {rel}: {comments[0]}"
        tree = ast.parse(src, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert ast.get_docstring(node) is None, f"docstring in {rel} at {type(node).__name__}"
