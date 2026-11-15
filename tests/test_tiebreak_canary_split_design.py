from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

import scripts.tiebreak_canary_split_design_audit as tcsda

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_canary_split_design_audit.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "canary_split_design" / "canary_split_design_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_canary_split_design.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_policy_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_script_roots = {"torch", "transformers", "subprocess"}
    forbidden_test_roots = {"torch", "transformers"}

    bad_w_mod = "canary." + "world"
    bad_s_mod = "canary." + "solver"
    bad_priv_w = "_" + "world"
    bad_gen_w = "generate_" + "world"
    bad_set_w = "set_" + "world_secret"

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tcsda.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()
        assert bad_priv_w not in src
        assert bad_w_mod not in src
        assert bad_gen_w not in src
        assert bad_set_w not in src

        tree = ast.parse(src, filename=str(py_path))
        bad_roots = forbidden_script_roots if py_path == SCRIPT_PATH else forbidden_test_roots
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in bad_roots
                    assert not alias.name.startswith((bad_s_mod, bad_w_mod))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in bad_roots
                assert not node.module.startswith((bad_s_mod, bad_w_mod))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_canary_split_design_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    for cls_name in tcsda.POLICY_CLASS_NAMES:
        assert f"scripts/tiebreak_canary_split_design_audit.py:{cls_name}" in checked


def test_analytical_mi_surface_and_check_cli_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tcsda.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_check = tcsda.main(["--check"])
    dt = time.perf_counter() - t0
    out_check = capsys.readouterr().out
    assert rc_check == 0
    assert dt < 0.25
    assert "OK: verified" in out_check

    rc_default = tcsda.main([])
    _ = capsys.readouterr()
    assert rc_default == 0

    rc_json = tcsda.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tcsda.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []

    assert tcsda.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == tcsda.render_markdown_report(summary)
    assert tcsda._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d+\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    mi = summary["analytical_mi_surface"]
    assert mi["exact_3arm_cond_ig_nats"] == pytest.approx(math.log(3.0), abs=1e-5)
    assert mi["exact_2arm_cond_ig_nats"] == pytest.approx(math.log(2.0), abs=1e-5)
    assert mi["exact_ternary_vs_binary_cond_ratio"] == pytest.approx(
        math.log(3.0) / math.log(2.0), abs=1e-4
    )
    assert mi["hard_fp95_balanced_ternary_vs_binary_cond_ratio"] > 1.38
    assert mi["hard_fp95_cov65_total_surfaced_kl_ratio"] > 1.38
    assert mi["easy_careful_off_optimal_variant_k"] == 12
    assert mi["medium_careful_on_optimal_hit_k"] == 10
    assert mi["hard_careful_on_optimal_hit_k"] == 20
    assert mi["medium_full_staff_leak_prob"] == 0.0
    assert mi["hard_full_staff_leak_prob"] == 0.0
    assert mi["by_tier"]["medium"]["arms"]["3_arm"]["max_p_hit"] == pytest.approx(0.1875, abs=1e-5)
    assert mi["by_tier"]["hard"]["arms"]["3_arm"]["max_p_hit"] == pytest.approx(0.1625, abs=1e-5)

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["train_seed_range"] == "102000..102779"
    assert summary["episodes_per_design"] == 90

    dev = summary["dev"]
    assert dev["dev_eval_seed_range"] == "0..29"
    assert dev["protocol_status"] == "post-hoc locked, not pre-registered"
    assert dev["hard_cohorts"]["opencode_gpt_5_5_hard"]["mean_diagnostic_variants_planted"] == pytest.approx(48.10, abs=1e-2)
    assert dev["hard_cohorts"]["opencode_gemini_4_carbon_hard"]["mean_diagnostic_variants_planted"] == pytest.approx(25.40, abs=1e-2)
    assert dev["hard_cohorts"]["solver_reference_hard"]["mean_diagnostic_variants_planted"] == pytest.approx(42.40, abs=1e-2)

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["qwen25_diagnostic_variant_arms_min"] == pytest.approx(6.24, abs=1e-2)
    assert pe["qwen25_diagnostic_variant_arms_max"] == pytest.approx(9.31, abs=1e-2)
    assert pe["eval_hf_default_max_new_tokens"] == 96
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["audited_policies_are_open_weight_llm"] is False

    designs = summary["partition_designs"]
    trn = designs["trained_adaptive_ternary"]
    bin2 = designs["adaptive_binary_2arm"]
    sng = designs["singleton_3suspect_microprobe"]
    rnd = designs["random_half_staff_3arm"]
    ful = designs["full_staff_naive_3arm"]
    brd = designs["broadcast_1arm_anti_pattern"]

    assert trn["overall"]["mean_score"] > bin2["overall"]["mean_score"] + 0.10
    assert trn["overall"]["mean_score"] > rnd["overall"]["mean_score"] + 0.05
    assert trn["by_tier"]["hard"]["mean_score"] > sng["by_tier"]["hard"]["mean_score"] + 0.10
    assert ful["by_tier"]["easy"]["mean_score"] > 0.70
    assert ful["by_tier"]["medium"]["mean_surfaced_canary_leaks"] == 0.0
    assert ful["by_tier"]["hard"]["mean_surfaced_canary_leaks"] == 0.0
    assert brd["overall"]["mean_diagnostic_variants_planted"] == 0.0
    assert summary["totals"]["primary_partition_episodes"] == 540
    assert summary["totals"]["total_episodes"] == 720
    assert summary["totals"]["fresh_env_replays_verified"] >= 120


def test_gitless_shallow_tmp_path_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/canary_split_design/canary_split_design_summary.json",
        "docs/reports/tiebreak_canary_split_design.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tcsda.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert tcsda.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("47888e4f\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("47888e4f\n", encoding="utf-8")
    assert tcsda.main(["--check", "--repo-root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "canary_split_design" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tcsda.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_canary_split_design.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert tcsda.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert tcsda.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = (
        shallow_root / "results" / "tiebreak" / "canary_split_design" / "canary_split_design_summary.json"
    )
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tcsda.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_partition_policies_unit_mechanics_and_live_replay() -> None:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    eb_params, _ = tcsda.load_trained_eb_params(repo_root=REPO_ROOT)

    with pytest.raises(ValueError):
        tcsda.make_partition_policy("unknown_design", eb_params, seed=800_000)

    provider = TemplateProvider()
    with tcsda._scoped_env_secret(tcsda.HELDOUT_SECRET_VALUE):
        env_med = Env("medium", 800_000, text_provider=provider)
        spec = env_med.tools_spec()
        instr = env_med.instruction()
    emps = [f"e{i:02d}" for i in range(20)]
    unif_post = {e: 1.0 / 20.0 for e in emps}

    for did in tcsda.DESIGN_ORDER:
        pol = tcsda.make_partition_policy(did, eb_params, seed=800_000)
        pol.reset(spec, instr)
        pol.tracker.employees = list(emps)
        asgs = pol._plan_canaries(unif_post)
        assert len(asgs) == 1
        asg = asgs[0]
        if did == "adaptive_binary_2arm":
            assert set(asg.values()) == {"A", "B"}
        elif did == "singleton_3suspect_microprobe":
            assert len(asg) == 3
            assert set(asg.values()) == {"A", "B", "C"}
        elif did == "random_half_staff_3arm":
            assert len(asg) == 10
            assert set(asg.values()) == {"A", "B", "C"}
        elif did == "full_staff_naive_3arm":
            assert len(asg) == 20
            assert set(asg.values()) == {"A", "B", "C"}
        elif did == "broadcast_1arm_anti_pattern":
            assert len(asg) == 20
            assert set(asg.values()) == {"A"}
        else:
            assert set(asg.values()) == {"A", "B", "C"}
            assert 3 <= len(asg) < 20

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    with tcsda._scoped_env_secret(tcsda.HELDOUT_SECRET_VALUE):
        for did in ("trained_adaptive_ternary", "adaptive_binary_2arm", "full_staff_naive_3arm"):
            pol = tcsda.make_partition_policy(did, eb_params, seed=800_000)
            ep = run_episode(Env("easy", 800_000, text_provider=provider), pol)
            rtp.verify_episode_replay(ep, text_provider=provider)
            first_csv = float(summary["partition_designs"][did]["episode_scores_csv"].split(",")[0])
            assert round(float(ep.score), 4) == pytest.approx(first_csv, abs=1e-4)
