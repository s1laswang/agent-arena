from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import sys
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

import scripts.tiebreak_harbor_shell_bridge as thsb

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_harbor_shell_bridge.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "harbor_shell_bridge" / "harbor_bridge_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_harbor_shell_bridge.md"
SELF_PATH = Path(__file__).resolve()


def test_check_cli_and_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    rc_human = thsb.main(["--check"])
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert "OK: verified" in out_human
    assert "150/150 hard bridge rollouts" in out_human

    rc_json = thsb.main(["--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["schema"] == thsb.SCHEMA_VERSION
    assert payload["passed"] is True
    assert payload["errors"] == []
    assert payload["elapsed_seconds"] < 15.0

    v_res = thsb.verify_artifacts(REPO_ROOT)
    assert v_res == {"passed": True, "errors": []}


def test_shallow_ci_git_free_root_and_negative_guards(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sub_json = tmp_path / thsb.DEFAULT_OUT_JSON
    sub_md = tmp_path / thsb.DEFAULT_OUT_MD
    sub_json.parent.mkdir(parents=True, exist_ok=True)
    sub_md.parent.mkdir(parents=True, exist_ok=True)
    sub_json.write_bytes(SUMMARY_PATH.read_bytes())
    sub_md.write_bytes(REPORT_PATH.read_bytes())

    rc_ok = thsb.main(["--check", "--root", str(tmp_path), "--json"])
    res_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert res_ok["passed"] is True

    forbidden_sib = sub_json.parent / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    errs_sib = thsb.verify_committed_artifacts(repo_root=tmp_path)
    assert any("disjointness violation" in e for e in errs_sib)
    forbidden_sib.unlink()

    mutated = json.loads(sub_json.read_text(encoding="utf-8"))
    mutated["leaked_judge_id"] = 900_005
    sub_json.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")
    errs_judge = thsb.verify_committed_artifacts(repo_root=tmp_path)
    assert any("900000" in e for e in errs_judge)
    sub_json.write_bytes(SUMMARY_PATH.read_bytes())

    sub_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8") + "\nPre-registered seeds 0..29 check.\n",
        encoding="utf-8",
    )
    errs_prereg = thsb.verify_committed_artifacts(repo_root=tmp_path)
    assert any("Panel Fix A" in e for e in errs_prereg)


def test_scientific_invariants_and_harbor_reconciliation() -> None:
    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < 70 * 1024
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_json = raw_bytes.decode("utf-8")
    int_tokens = [int(m.group(0)) for m in re.finditer(r"\b\d+\b", raw_json)]
    assert all(tok < 900_000 for tok in int_tokens)

    summary = json.loads(raw_json)
    assert summary["schema"] == thsb.SCHEMA_VERSION
    assert summary["tier"] == "hard"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["dev_eval_seed_range"] == "0..29"
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["seed_isolation"]["judge_episodes_touched"] == 0
    assert summary["seed_isolation"]["dev_episodes_rolled_out"] == 0
    assert summary["seed_isolation"]["train_episodes_in_heldout_eval"] == 0

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["non_llm_policies_is_open_weight_llm"] is False

    hb = summary["harbor_vs_mcp_frontier_reconciliation"]
    mcp = hb["gemini_4_carbon_mcp_only_hard"]
    har = hb["gemini_4_carbon_harbor_shell_hard"]
    assert mcp["mean_score"] == pytest.approx(0.322, abs=1e-3)
    assert mcp["ratio_vs_solver_display"] == "65% [24%, 98%]"
    assert mcp["accusation_precision_display"] == "25/29"
    assert har["shell_used_display"] == "20/28"
    assert har["valid_accusation_display"] == "28/29"
    assert [r["mean_score"] for r in har["runs"]] == [0.472, 0.585, 0.626]
    assert [r["ratio_vs_oracle_pct"] for r in har["runs"]] == [93, 116, 131]
    assert [t["task_idx"] for t in har["sanitized_snapshot_tasks"]] == list(range(10))

    arms = summary["arms"]
    eb = arms["externalized_empirical_bayes_11p"]
    lin = arms["externalized_compact_linear_dagger_785p"]
    ev_b = arms["unexternalized_evict_k16_bayes"]
    ls_h = arms["in_context_lossless_heuristic"]
    ev_h = arms["unexternalized_evict_k12_heuristic"]

    assert eb["param_count"] == 11
    assert eb["train_seed_range"] == "102000..102779"
    assert eb["metrics"]["mean_score"] > 0.50
    assert eb["metrics"]["surfaced_canary_eviction_rate"] == 0.0
    assert eb["metrics"]["wrong_count"] == 0

    assert lin["param_count"] == 785
    assert lin["train_seed_range"] == "109000..109509"
    assert lin["metrics"]["mean_score"] > 0.45
    assert lin["metrics"]["accusation_precision"] >= 0.95

    assert ev_b["metrics"]["surfaced_canary_eviction_rate"] > 0.85
    assert ev_b["metrics"]["abstain_count"] >= 15
    assert ls_h["metrics"]["wrong_count"] >= 20
    assert ev_h["metrics"]["wrong_count"] >= 25

    pc = summary["paired_contrasts"]
    assert pc["pure_state_externalization_effect_under_bayes"]["ci95_low"] > 0.30
    assert pc["pure_arithmetic_bayes_ev_effect_under_lossless"]["ci95_low"] > 1.00
    assert pc["compact_dagger_vs_evict_heuristic"]["ci95_low"] > 1.00
    assert summary["factorial_2x2_synergy"]["interaction_ci95_low"] > 0.10


def test_live_paired_seed_reproduction_and_ast_isolation() -> None:
    from canary.text.template import TemplateProvider
    import scripts.verify_tiebreak_submission as vts

    ast_res = vts.check_ast_inference_isolation(
        root=REPO_ROOT,
        extra_paths=[SCRIPT_PATH],
        strict=True,
    )
    assert ast_res.passed is True
    assert "scripts/tiebreak_harbor_shell_bridge.py:WindowEvictingBayesPolicy" in ast_res.metrics[
        "policy_classes_checked"
    ]

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    bundle = thsb.load_policy_weights_and_params(REPO_ROOT)
    provider = TemplateProvider()

    with thsb._scoped_world_secret(thsb.HELDOUT_WORLD_SECRET):
        for arm_id in (
            "unexternalized_evict_k12_heuristic",
            "externalized_empirical_bayes_11p",
            "externalized_compact_linear_dagger_785p",
        ):
            rec = thsb.execute_single_arm_episode(
                arm_id=arm_id,
                seed=800_000,
                provider=provider,
                bundle=bundle,
                verify_replay=True,
            )
            assert rec["replay_ok"] is True
            expected_digest = summary["arms"][arm_id]["episode_digests"][0]
            assert rec["digest"] == expected_digest


def test_source_and_report_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                assert not node.module.startswith(("canary.solver", "canary.world"))

    for text_path in (SUMMARY_PATH, REPORT_PATH):
        txt = text_path.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert unicode_minus not in txt
        assert txt.isascii()

    assert _IMPORT_DELTA_HEAVY == frozenset()
