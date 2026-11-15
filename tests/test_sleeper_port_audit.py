from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.sleeper_port_audit as spa
from scripts.sleeper_port_audit import (
    BASE_COMMIT,
    DEFAULT_JSON_OUT,
    DEFAULT_MD_OUT,
    MAX_JSON_BYTES,
    ROOT,
    compute_port_audit,
    main,
    render_json,
    render_markdown,
)


@pytest.fixture(scope="module")
def audit_payload():
    return compute_port_audit(ROOT)


def test_scope_hygiene_and_file_manifest(audit_payload):
    assert audit_payload["base_branch"] == "origin/justSilas"
    assert audit_payload["base_commit"] == BASE_COMMIT == "5f9b3297"
    assert audit_payload["shipped_tiers_version"] == "v1.4"
    assert audit_payload["known_v_mode"] is True
    assert audit_payload["v16_social_files_count"] == 0
    assert audit_payload["gemini_api_calls"] == 0
    assert audit_payload["all_invariants_pass"] is True

    hygiene = audit_payload["scope_hygiene"]
    assert hygiene["passed"] is True
    assert hygiene["v16_social_files"] == []
    assert hygiene["missing_files"] == []
    assert hygiene["counterpart_files_present"] == hygiene["counterpart_files_expected"] == 39


def test_all_five_flagship_ideas_and_supporting_ports_mapped(audit_payload):
    summary = audit_payload["summary"]
    assert summary["flagship_ideas_mapped"] == 5
    assert summary["supporting_ports_mapped"] == 2
    assert summary["total_entries"] == 7
    assert summary["fairness_invariants_passed"] == summary["fairness_invariants_checked"] == 15
    assert summary["catchability_invariants_passed"] == summary["catchability_invariants_checked"] == 7

    ideas = {item["id"]: item for item in audit_payload["ideas"]}
    expected_flagship = {
        "cheat_corpus",
        "multi_employee_social_chains",
        "surface_tells_audit",
        "failure_gallery_breakeven_spotlight",
        "office_replay_dashboard",
    }
    expected_supporting = {
        "salted_sidecar_and_signed_ledger",
        "catchability_constrained_mole_adversary",
    }
    assert set(ideas) == expected_flagship | expected_supporting

    for idea_id, item in ideas.items():
        expected_cat = "flagship" if idea_id in expected_flagship else "supporting_port"
        assert item["category"] == expected_cat
        assert item["all_pass"] is True
        assert item["canary_v14_counterpart"]["status"] == "shipped"
        assert item["canary_v15_counterpart"]["status"] == "evaluated_dropped_at_gate_b"
        assert len(item["sleeper_origin"]["modules"]) >= 1
        assert len(item["canary_v14_counterpart"]["modules"]) >= 1
        assert len(item["one_agent_adaptation_rationale"]) > 20
        assert len(item["fairness_invariants"]) >= 1
        assert len(item["catchability_invariants"]) >= 1
        assert all(inv["passed"] is True for inv in item["fairness_invariants"])
        assert all(inv["passed"] is True for inv in item["catchability_invariants"])


def test_fairness_and_catchability_numerical_invariants(audit_payload):
    ideas = {item["id"]: item for item in audit_payload["ideas"]}

    corp = ideas["cheat_corpus"]["measured_evidence"]
    assert corp["corpus_rows"] == 129
    assert len(corp["foreign_tools"]) == 10
    assert corp["historical_attempt_count"] == 782
    assert corp["committed_injection_runs"] == 1161
    assert corp["solver_judge40_means"] == {"easy": 0.765, "medium": 0.671, "hard": 0.545}

    soc = ideas["multi_employee_social_chains"]["measured_evidence"]
    assert soc["sourced_corporate_failure_cases"] == 44
    assert soc["rl_heldout_n100"]["solver_acc"] == pytest.approx(0.75, abs=1e-6)
    assert soc["rl_heldout_n100"]["solver_score"] == pytest.approx(0.3954, abs=1e-4)
    assert soc["rl_heldout_n100"]["solver_score"] > soc["rl_heldout_n100"]["grok_tactics_score"]
    assert soc["v15_gate_b_spotcheck_n10"]["decision"] == "dropped_at_gate_b"
    assert soc["v15_gate_b_spotcheck_n10"]["ratio_vs_solver"] == pytest.approx(1.08, abs=1e-4)

    tells = ideas["surface_tells_audit"]["measured_evidence"]
    assert tells["instruction_fields_verified"] == {"easy": 34, "medium": 34, "hard": 34}
    assert tells["tool_smoke_passed"] == "39/39"
    assert tells["hidden_leak_states_verified"] >= 15
    assert tells["skill_ladder_n400_solver"]["hard"]["n"] == 400
    assert tells["skill_ladder_n400_solver"]["hard"]["acc_when_accusing"] == pytest.approx(0.9647, abs=1e-4)
    assert tells["skill_ladder_n400_solver"]["hard"]["mean_score"] == pytest.approx(0.5645, abs=1e-4)

    gal = ideas["failure_gallery_breakeven_spotlight"]["measured_evidence"]
    assert gal["gallery_episodes_decomposed"] == 295
    assert gal["gallery_v14_episodes"] == 196
    assert gal["gallery_v14_net_gap"] == pytest.approx(72.27, abs=1e-6)
    assert gal["opencode_carbon_hard30"]["below_breakeven_seeds"] == [5, 18, 23]
    assert gal["opencode_carbon_hard30"]["decision_ev_sum"] == pytest.approx(-0.9348, abs=1e-4)
    assert gal["opencode_carbon_hard30"]["share_of_penalty_gap"] == pytest.approx(0.4846, abs=1e-4)
    assert gal["solver_hard30"]["below_breakeven_count"] == 0
    assert gal["solver_hard30"]["min_margin_exp"] == pytest.approx(0.1160, abs=1e-3)

    rep = ideas["office_replay_dashboard"]["measured_evidence"]
    assert rep["canonical_replays"]["4"]["solver"]["score"] == pytest.approx(0.73, abs=1e-6)
    assert rep["canonical_replays"]["18"]["gemini"]["score"] == pytest.approx(-1.0, abs=1e-6)
    assert rep["canonical_replays"]["26"]["solver"]["score"] == pytest.approx(0.69, abs=1e-6)
    assert rep["browser_game_seed3000"] == {"score": 0.79, "correct": True, "final_day": 6, "tool_calls": 48}

    salt = ideas["salted_sidecar_and_signed_ledger"]["measured_evidence"]
    assert salt["harbor_trials_verified"] == 80
    assert salt["harbor_jobs_verified"] == 18
    assert salt["replayed_episodes_consistent"] == 1051
    assert salt["replayed_tool_steps_compared"] == 53889
    assert salt["c1_tamper_negative_control_reward"] == 0

    mole = ideas["catchability_constrained_mole_adversary"]["measured_evidence"]
    assert mole["dsl_max_rules"] == 12
    assert mole["heldout_n100_default_vs_rl"]["rl_heuristic_regret"] > mole["heldout_n100_default_vs_rl"]["default_heuristic_regret"]


def test_committed_json_size_cap_and_markdown_parity(audit_payload):
    assert DEFAULT_JSON_OUT.is_file()
    assert DEFAULT_MD_OUT.is_file()

    json_txt = render_json(audit_payload)
    md_txt = render_markdown(audit_payload)

    raw_bytes = DEFAULT_JSON_OUT.read_bytes()
    assert len(raw_bytes) <= MAX_JSON_BYTES == 40960
    assert DEFAULT_JSON_OUT.read_text(encoding="utf-8") == json_txt
    assert DEFAULT_MD_OUT.read_text(encoding="utf-8") == md_txt

    parsed = json.loads(raw_bytes.decode("utf-8"))
    assert parsed == audit_payload

    with pytest.raises(ValueError, match="exceeds"):
        render_json({"oversized": "x" * (MAX_JSON_BYTES + 128)})


def test_cli_check_keyless_and_drift_detection(audit_payload, tmp_path, monkeypatch):
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENERATIVE_AI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }
    }
    clean_env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sleeper_port_audit.py"), "--check"],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK: sleeper_port_audit reproduces" in proc.stdout

    monkeypatch.setattr(spa, "compute_port_audit", lambda _root=ROOT: audit_payload)
    tmp_json = tmp_path / "sleeper_port_matrix.json"
    tmp_md = tmp_path / "sleeper_to_canary_port_matrix.md"
    assert main(["--json-out", str(tmp_json), "--md-out", str(tmp_md)]) == 0
    assert main(["--json-out", str(tmp_json), "--md-out", str(tmp_md), "--check"]) == 0

    tmp_md.write_text(tmp_md.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert main(["--json-out", str(tmp_json), "--md-out", str(tmp_md), "--check"]) == 1


def test_zero_comments_zero_forbidden_dashes_and_zero_network_imports():
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    py_files = [
        ROOT / "scripts" / "sleeper_port_audit.py",
        Path(__file__).resolve(),
    ]
    all_files = [*py_files, DEFAULT_JSON_OUT, DEFAULT_MD_OUT]

    for path in all_files:
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, f"em dash found in {path}"
        assert en_dash not in txt, f"en dash found in {path}"

    for py_path in py_files:
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment tokens found in {py_path}: {comments}"
        assert chr(35) not in src, f"hash char found in {py_path}"

    tree = ast.parse((ROOT / "scripts" / "sleeper_port_audit.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("google", "genai", "openai", "anthropic", "atlas_gemini", "gateway", "httpx", "requests", "urllib")
    for mod in imported:
        assert not any(f in mod for f in forbidden), f"forbidden module imported: {mod}"
