"""Fast keyless tests for scripts/verify_mole_strategies_gate.py and docs/reports/mole_strategies_summary.md."""
from __future__ import annotations

import ast
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tokenize

import pytest

import scripts.verify_mole_strategies_gate as gate

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_mole_strategies_gate.py"
TEST_PATH = Path(__file__).resolve()
SUMMARY_MD_PATH = ROOT / "docs" / "reports" / "mole_strategies_summary.md"


def _count_comment_tokens(py_path: Path) -> int:
    src = py_path.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    return sum(1 for tok in tokens if tok.type == tokenize.COMMENT)


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)


def test_zero_comments_and_summary_hygiene() -> None:
    assert _count_comment_tokens(SCRIPT_PATH) == 0
    assert _count_comment_tokens(TEST_PATH) == 0

    check_paths = [SCRIPT_PATH, TEST_PATH]
    if SUMMARY_MD_PATH.is_file():
        check_paths.append(SUMMARY_MD_PATH)

    for p in check_paths:
        txt = p.read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt

    if SUMMARY_MD_PATH.is_file():
        md_text = SUMMARY_MD_PATH.read_text(encoding="utf-8")
        assert gate.validate_markdown_hygiene(md_text) == []
        assert "NOT MET" in md_text
        assert "negative result" in md_text.lower()
        assert "v5_full9_cocktail" in md_text
        assert "cross_model_transfer.json" in md_text
        assert "99/99" in md_text
        assert "11/11" in md_text
        assert "canary.mole.regret_portfolio" in md_text
        assert "mole_regret_portfolio_v14.md" in md_text


def test_markdown_hygiene_rejects_violations() -> None:
    assert gate.validate_markdown_hygiene("clean summary text\n") == []
    assert gate.validate_markdown_hygiene("bad \u2014 em dash") != []
    assert gate.validate_markdown_hygiene("bad \u2013 en dash") != []
    assert gate.validate_markdown_hygiene("leaked suspect e07 in text") != []
    assert gate.validate_markdown_hygiene("gemini-3.5-flash achieved 81.2% of solver on hard") != []
    fake_key = "AIza" + "B" * 28
    assert gate.validate_markdown_hygiene(f"leaked {fake_key}") != []


def test_protected_paths_guard_real_and_synthetic(tmp_path: Path) -> None:
    real_res = gate.check_protected_paths(ROOT)
    assert real_res["passed"] is True
    assert real_res["n_protected_rules"] >= 15
    assert real_res["violations"] == []

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    gh_dir = repo / ".github"
    gh_dir.mkdir()
    (gh_dir / "protected-paths.txt").write_text(
        "canary/env.py\ncanary/solver/\n.github/protected-paths.txt\n",
        encoding="utf-8",
    )
    (repo / "canary").mkdir()
    (repo / "canary" / "env.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/justSilas", "HEAD"], cwd=repo, check=True)

    (repo / "notes.md").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "safe"], cwd=repo, check=True)
    clean_check = gate.check_protected_paths(repo, base_ref="origin/justSilas")
    assert clean_check["passed"] is True
    assert clean_check["base_ref_present"] is True
    assert clean_check["violations"] == []

    no_ref_check = gate.check_protected_paths(repo, base_ref="origin/nonexistent_branch")
    assert no_ref_check["passed"] is True
    assert no_ref_check["base_ref_present"] is False

    (repo / "canary" / "solver").mkdir()
    (repo / "canary" / "solver" / "patch.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "touch protected"], cwd=repo, check=True)
    bad_check = gate.check_protected_paths(repo, base_ref="origin/justSilas")
    assert bad_check["passed"] is False
    assert "canary/solver/patch.py" in bad_check["violations"]


def test_seed_hygiene_validation() -> None:
    assert gate.validate_fresh_seed_slice("6900-6903", "spot") == [6900, 6901, 6902, 6903]
    for forbidden in ("0-3", "29", "59", "30050", "800000", "900005", "6900,6900"):
        with pytest.raises(ValueError):
            gate.validate_fresh_seed_slice(forbidden, "bad")


def test_strategies_hof_fresh_eval_and_tamper_detection(tmp_path: Path) -> None:
    res = gate.check_strategies_and_fresh_eval(
        ROOT,
        spot_seeds=(6900,),
        spot_targets=("hof_rank1_window_crowd_stale",),
    )
    assert res["passed"] is True
    assert res["n_transcript_strategies"] == 6
    assert res["transcript_unique_behavior_hashes"] is True
    assert res["n_hof_rows"] == 4
    assert res["hof_unique_behavior_hashes"] is True
    assert res["combined_unique_behavior_hashes"] == 8
    assert res["fresh_eval_n_seeds"] == 200
    assert len(res["spot_checks"]) == 1
    assert res["spot_checks"][0]["do_nothing_zero"] is True
    assert res["spot_checks"][0]["stop_early_quit_zero"] is True
    assert res["spot_checks"][0]["solver_acc"] >= 0.75

    bad_eval = json.loads((ROOT / gate.DEFAULT_FRESH_EVAL_REL).read_text(encoding="utf-8"))
    bad_eval["strategies"]["frontier_synthesis_v14"]["solver"]["accuracy"] = 0.50
    bad_eval_path = tmp_path / "bad_v14_eval.json"
    bad_eval_path.write_text(json.dumps(bad_eval), encoding="utf-8")
    tampered = gate.check_strategies_and_fresh_eval(
        ROOT,
        fresh_eval_path=bad_eval_path,
        spot_seeds=(6900,),
        spot_targets=(),
    )
    assert tampered["passed"] is False
    assert any("frontier_synthesis_v14" in msg for msg in tampered["failures"])


def test_counterfactual_opencode_0_9_and_ablation_v16_replays(tmp_path: Path) -> None:
    with gate.offline_gate_guard() as telemetry:
        cf = gate.check_counterfactual_replay(ROOT, seeds=range(10), sources=("opencode",))
        av = gate.check_ablation_and_v16_replays(ROOT)

    assert telemetry["live_api_calls"] == 0
    assert telemetry["blocked_api_attempts"] == 0

    assert cf["passed"] is True
    assert cf["n_episodes"] == 10
    assert cf["synthesis_p_true_mole"] < cf["default_p_true_mole"]
    assert cf["p_true_mole_drop"] > 0.0
    assert cf["synthesis_optimal_ev"] < cf["default_optimal_ev"]
    assert cf["optimal_ev_drop"] > 0.0

    assert av["passed"] is True
    assert av["ablation"]["n_arms"] == 12
    assert av["ablation"]["n_passed"] == 12

    v16_partial = ROOT / "results" / "v16_social" / "partial"
    if v16_partial.is_dir() and gate._load_social_modules() is not None:
        assert av["pure_mole"] is False
        assert av["v16_episodes_replayed"] == 10
        assert av["v16_replay_mismatches"] == 0

        tampered_dir = tmp_path / "partial" / "v1_anchoring_authority_confirmation" / "hard"
        tampered_dir.mkdir(parents=True)
        orig_line = (
            v16_partial
            / "v1_anchoring_authority_confirmation"
            / "hard"
            / "episodes.jsonl"
        ).read_text(encoding="utf-8").splitlines()[0]
        rec = json.loads(orig_line)
        rec["score"] = 0.123456
        (tampered_dir / "episodes.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")

        bad_v16 = gate.check_ablation_and_v16_replays(
            ROOT,
            v16_partial_dir=tmp_path / "partial",
            expected_checkpoint_episodes=1,
        )
        assert bad_v16["passed"] is False
        assert bad_v16["v16_replay_mismatches"] >= 1
    else:
        assert av["pure_mole"] is True


def test_transfer_and_regret_portfolio_and_tamper_detection(tmp_path: Path) -> None:
    with gate.offline_gate_guard() as telemetry:
        xp = gate.check_transfer_and_regret_portfolio(ROOT)

    assert telemetry["live_api_calls"] == 0
    assert xp["passed"] is True
    assert xp["transfer"]["passed"] is True
    assert xp["transfer"]["n_catalog"] == 11
    assert xp["transfer"]["n_gates_passed"] == 11
    assert xp["transfer"]["n_unique_behaviors"] == 9
    assert xp["transfer"]["total_transcripts"] == 99
    assert xp["transfer"]["transcript_verified_total"] == 99
    assert xp["transfer"]["baseline_audit_match_total"] == 99
    assert xp["portfolio"]["passed"] is True
    assert xp["portfolio"]["train_n_seeds"] == 200
    assert xp["portfolio"]["val_n_seeds"] == 12
    assert xp["portfolio"]["val_solver_acc"] == 1.0
    assert xp["portfolio"]["selected_strategy_counts"] == {
        "gemini_midsize_shield": 1,
        "surgical_trap_shield": 11,
    }

    bad_trf_json = tmp_path / "bad_cross_model_transfer.json"
    trf_obj = json.loads((ROOT / gate.DEFAULT_TRANSFER_JSON_REL).read_text(encoding="utf-8"))
    trf_obj["counterfactual"]["transcript_verified_total"] = 98
    bad_trf_json.write_text(json.dumps(trf_obj), encoding="utf-8")
    tampered_trf = gate.check_transfer_and_regret_portfolio(ROOT, transfer_json_path=bad_trf_json)
    assert tampered_trf["passed"] is False
    assert tampered_trf["transfer"]["passed"] is False

    bad_port_md = tmp_path / "bad_mole_regret_portfolio_v14.md"
    orig_port_txt = (ROOT / gate.DEFAULT_PORTFOLIO_MD_REL).read_text(encoding="utf-8")
    bad_port_md.write_text(
        orig_port_txt.replace('"surgical_trap_shield": 11', '"surgical_trap_shield": 10'),
        encoding="utf-8",
    )
    tampered_port = gate.check_transfer_and_regret_portfolio(ROOT, portfolio_md_path=bad_port_md)
    assert tampered_port["passed"] is False
    assert tampered_port["portfolio"]["passed"] is False


def test_cli_out_and_check_roundtrip(tmp_path: Path) -> None:
    out_md = tmp_path / "summary.md"
    cli_base = ["--spot-seeds", "6900", "--spot-targets", "hof_rank1_window_crowd_stale", "--cf-seeds", "0-9"]
    rc_out = gate.main([*cli_base, "--out", str(out_md)])
    assert rc_out == 0
    assert out_md.is_file()

    rc_check = gate.main([*cli_base, "--check", str(out_md)])
    assert rc_check == 0

    out_md.write_text(out_md.read_text(encoding="utf-8") + "\nextra drift line\n", encoding="utf-8")
    rc_drift = gate.main([*cli_base, "--check", str(out_md)])
    assert rc_drift == 1


def test_pure_mole_blocks_social_modules_and_auto_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_targets.append(node.module)
    assert not any(
        m.startswith("canary.social") or m.startswith("canary.text")
        for m in imported_targets
    )

    for existing_mod in list(sys.modules):
        if existing_mod.startswith("canary.social"):
            monkeypatch.delitem(sys.modules, existing_mod, raising=False)

    blocked_modules = (
        "canary.social",
        "canary.social.variants",
        "canary.social.biases",
        "canary.social.engine",
        "canary.social.gemini_chatter",
        "canary.social_audit",
        "canary.text.llm_cache",
        "canary.text.gemini",
    )
    for mod_name in blocked_modules:
        monkeypatch.setitem(sys.modules, mod_name, None)

    reloaded = importlib.reload(gate)
    assert reloaded._load_social_modules() is None

    pure_md = tmp_path / "pure_mole_summary.md"
    pure_cli = [
        "--pure-mole",
        "--spot-seeds",
        "6900",
        "--spot-targets",
        "hof_rank1_window_crowd_stale",
        "--cf-seeds",
        "0-9",
    ]
    assert reloaded.main([*pure_cli, "--out", str(pure_md)]) == 0
    assert pure_md.is_file()
    pure_txt = pure_md.read_text(encoding="utf-8")
    assert reloaded.validate_markdown_hygiene(pure_txt) == []
    assert "Pure-Mole" in pure_txt
    assert "V1.6 Social Deception Audit" not in pure_txt
    assert reloaded.main([*pure_cli, "--check", str(pure_md)]) == 0

    for mod_name in blocked_modules:
        assert sys.modules[mod_name] is None

    fallback_blocked = reloaded.check_ablation_and_v16_replays(ROOT)
    assert fallback_blocked["passed"] is True
    assert fallback_blocked["pure_mole"] is True
    assert fallback_blocked["pure_mole_reason"] == "social_audit_unavailable"
    assert fallback_blocked["ablation"]["n_passed"] == 12
    assert fallback_blocked["v16_episodes_replayed"] == 0

    monkeypatch.setattr(
        reloaded,
        "DEFAULT_V16_PARTIAL_REL",
        Path("results") / "missing_v16_social_partial_dir",
    )
    fallback_missing = reloaded.check_ablation_and_v16_replays(ROOT)
    assert fallback_missing["passed"] is True
    assert fallback_missing["pure_mole"] is True
    assert fallback_missing["pure_mole_reason"] == "missing_v16_partial_dir"
    assert fallback_missing["ablation"]["n_passed"] == 12
