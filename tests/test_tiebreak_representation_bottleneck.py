from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_representation_bottleneck_audit as trba

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_representation_bottleneck_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "representation_bottleneck" / "bottleneck_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_representation_bottleneck.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_script_roots = {"torch", "transformers", "subprocess"}
    forbidden_test_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = trba.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

        tree = ast.parse(src, filename=str(py_path))
        bad_roots = forbidden_script_roots if py_path == SCRIPT_PATH else forbidden_test_roots
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in bad_roots
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in bad_roots
                assert not node.module.startswith(("canary.solver", "canary.world"))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    test_toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in test_toks if t.type == tokenize.COMMENT]

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_representation_bottleneck_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    assert "scripts/tiebreak_representation_bottleneck_audit.py:FeatureBottleneckPolicy" in checked
    assert "scripts/tiebreak_representation_bottleneck_audit.py:BottleneckCompactLinearDAggerPolicy" in checked
    assert "scripts/tiebreak_representation_bottleneck_audit.py:BottleneckTinyMLPPolicy" in checked


def test_check_cli_json_mode_and_bottleneck_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < trba.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_default = trba.main([])
    dt_def = time.perf_counter() - t0
    out_def = capsys.readouterr().out
    assert rc_default == 0
    assert dt_def < 10.0
    assert "OK: verified" in out_def
    assert "1080 episodes" in out_def

    rc_json = trba.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == trba.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert trba.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == trba.render_markdown_report(summary)
    assert trba._scan_json_for_judge_numbers(summary, raw_json) == []
    for dig_match in re.finditer(r"\d+", raw_json):
        assert int(dig_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_condition"] == 90
    assert summary["bottleneck_modes"] == list(trba.BOTTLENECK_MODES)

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_rolled_out"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["compact_policies_are_open_weight_llm"] is False

    qwen = summary["cross_track_qwen_contrast"]
    assert qwen["is_open_weight_llm"] is True
    assert qwen["raw_4k_canary_eviction_pct_display"] == "98.0%"
    assert qwen["raw_4k_canary_evicted_count"] == 1162
    assert qwen["pooled_canary_calls_total"] == 1186
    assert qwen["compact_canary_evicted_count"] == 0

    eb = summary["sufficient_stat_baselines"]["empirical_bayes"]
    sc = summary["sufficient_stat_baselines"]["scaling_logistic"]
    assert eb["param_count"] == 11
    assert eb["is_open_weight_llm"] is False
    assert eb["overall"]["mean_score"] == pytest.approx(0.62233, abs=2e-4)
    assert sc["param_count"] == 82
    assert sc["is_open_weight_llm"] is False
    assert sc["overall"]["mean_score"] == pytest.approx(0.61067, abs=2e-4)

    cld = summary["masked_policies"]["compact_linear_dagger"]
    mlp = summary["masked_policies"]["tiny_mlp"]
    assert cld["param_count"] == 785
    assert cld["is_open_weight_llm"] is False
    assert mlp["param_count"] == 12293
    assert mlp["is_open_weight_llm"] is False

    for pb in (cld, mlp):
        conds = pb["conditions"]
        assert conds["full_28d"]["overall"]["action_agreement_rate"] == 1.0
        assert conds["full_28d"]["overall"]["terminal_agreement_rate"] == 1.0
        assert conds["core_sufficient_stats"]["overall"]["mean_score"] > 0.50
        assert conds["posterior_only"]["overall"]["mean_score"] > 0.40
        assert conds["posterior_only"]["overall"]["accusation_precision"] < conds["full_28d"]["overall"]["accusation_precision"]
        assert conds["horizon_value_only"]["overall"]["mean_score"] == pytest.approx(0.0, abs=1e-5)
        assert conds["horizon_value_only"]["overall"]["abstain_rate"] == 1.0
        assert conds["no_canary_aux_only"]["overall"]["mean_score"] == pytest.approx(0.0, abs=1e-5)
        assert conds["no_canary_aux_only"]["overall"]["abstain_rate"] == 1.0

    totals = summary["totals"]
    assert totals["total_live_episodes"] == 1080
    assert totals["fresh_env_replays_verified"] == 1080


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/representation_bottleneck/bottleneck_summary.json",
        "docs/reports/tiebreak_representation_bottleneck.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert trba.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert trba.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("c445a4ca\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("c445a4ca\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "representation_bottleneck" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_representation_bottleneck.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = shallow_root / "results" / "tiebreak" / "representation_bottleneck" / "bottleneck_summary.json"
    orig_json_txt = json_copy.read_text(encoding="utf-8")
    bad_summary = json.loads(orig_json_txt)
    bad_summary["masked_policies"]["tiny_mlp"]["conditions"]["full_28d"]["overall"]["action_agreement_rate"] = 0.5
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 1
    assert "action_agreement_rate" in capsys.readouterr().err

    bad_judge = json.loads(orig_json_txt)
    bad_judge["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_judge, indent=2) + "\n", encoding="utf-8")
    assert trba.main(["--check", "--root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_bottleneck_policy_unit_mechanics_and_fast_live_spot_replay() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    from scripts.verify_replay import replay_episode

    with pytest.raises(ValueError):
        trba.FeatureBottleneckPolicy("unknown_kind", "full_28d")
    with pytest.raises(ValueError):
        trba.FeatureBottleneckPolicy("compact_linear_dagger", "unknown_mode")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    bnd = trba.load_masked_weights(REPO_ROOT)
    provider = TemplateProvider()

    with trba._fast_compact_dagger_features(), trba._scoped_world_secret(trba.HELDOUT_WORLD_SECRET):
        pol_cld = trba.BottleneckCompactLinearDAggerPolicy(weights=bnd["cld_weights"], mode="full_28d")
        ep_cld = run_episode(Env("easy", 800_000, text_provider=provider), pol_cld)
        rep = replay_episode(
            {"tier": ep_cld.tier, "seed": ep_cld.seed, "steps": [{"tool": st.tool, "args": st.args} for st in ep_cld.steps]}
        )
        assert rep["score"] == pytest.approx(ep_cld.score, abs=1e-9)
        assert rep["accused"] == ep_cld.accused
        first_cld = float(summary["masked_policies"]["compact_linear_dagger"]["conditions"]["full_28d"]["episode_scores_csv"].split(",")[0])
        assert round(float(ep_cld.score), 4) == pytest.approx(first_cld, abs=1e-4)

        pol_mlp = trba.BottleneckTinyMLPPolicy(weights=bnd["mlp_weights"], mode="core_sufficient_stats", seed=800_000)
        ep_mlp = run_episode(Env("easy", 800_000, text_provider=provider), pol_mlp)
        first_mlp = float(summary["masked_policies"]["tiny_mlp"]["conditions"]["core_sufficient_stats"]["episode_scores_csv"].split(",")[0])
        assert round(float(ep_mlp.score), 4) == pytest.approx(first_mlp, abs=1e-4)

        pol_hvo = trba.BottleneckCompactLinearDAggerPolicy(weights=bnd["cld_weights"], mode="horizon_value_only")
        ep_hvo = run_episode(Env("easy", 800_000, text_provider=provider), pol_hvo)
        assert ep_hvo.accused is None
        assert ep_hvo.score == 0.0

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
