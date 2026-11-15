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

import scripts.tiebreak_pareto_efficiency as tpe

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_pareto_efficiency.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "pareto_efficiency" / "pareto_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_pareto_efficiency.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_script_roots = {"torch", "transformers", "subprocess"}
    forbidden_test_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tpe.check_python_source_hygiene(py_path, run_tokenize=True)
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
        "scripts/tiebreak_pareto_efficiency.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    assert "scripts/tiebreak_pareto_efficiency.py:BudgetCappedPolicy" in checked
    assert "scripts/tiebreak_pareto_efficiency.py:BudgetCappedEmpiricalBayesPolicy" in checked
    assert "scripts/tiebreak_pareto_efficiency.py:BudgetCappedCompactLinearDAggerPolicy" in checked


def test_check_cli_json_mode_and_cross_architecture_pareto_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tpe.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_human = tpe.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "1440 episodes" in out_human

    rc_json = tpe.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tpe.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert tpe.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == tpe.render_markdown_report(summary)
    assert tpe._scan_json_for_judge_numbers(summary, raw_json) == []
    for dig_match in re.finditer(r"\d+", raw_json):
        assert int(dig_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_cap"] == 90
    assert summary["budget_caps"] == [4, 8, 16, 24, 36, 48, 96, 420]

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
    assert pe["audited_budget_policies_are_open_weight_llm"] is False

    cross = summary["cross_architecture_tables"]
    compact_by_id = {r["row_id"]: r for r in cross["non_llm_compact_heldout"]}
    assert compact_by_id["do_nothing"]["param_count"] == 0
    assert compact_by_id["do_nothing"]["primary_mean_score"] == pytest.approx(0.0, abs=1e-5)
    assert compact_by_id["empirical_bayes"]["param_count"] == 11
    assert compact_by_id["empirical_bayes"]["primary_mean_score"] == pytest.approx(0.60728, abs=2e-4)
    assert compact_by_id["empirical_bayes"]["n90_mean_score"] == pytest.approx(0.62233, abs=2e-4)
    assert compact_by_id["scaling_logistic"]["param_count"] == 82
    assert compact_by_id["scaling_logistic"]["primary_mean_score"] == pytest.approx(0.61067, abs=2e-4)
    assert compact_by_id["compact_linear_dagger"]["param_count"] == 785
    assert compact_by_id["compact_linear_dagger"]["primary_mean_score"] == pytest.approx(0.62672, abs=2e-4)
    assert compact_by_id["tiny_mlp"]["param_count"] == 12293
    assert compact_by_id["tiny_mlp"]["primary_mean_score"] == pytest.approx(0.61406, abs=2e-4)
    assert compact_by_id["tiny_mlp"]["is_param_score_pareto_optimal"] is False

    llm_by_id = {r["row_id"]: r for r in cross["open_weight_llm_heldout"]}
    assert set(llm_by_id) == set(tpe.OPEN_WEIGHT_LLM_ROW_IDS)
    assert llm_by_id["WS4-base-pooled"]["mean_score"] == pytest.approx(0.0, abs=1e-4)
    assert llm_by_id["WS4-v2"]["mean_score"] == pytest.approx(-0.457, abs=1e-3)
    assert llm_by_id["WS4-v3-verda-s0-eval"]["mean_score"] == pytest.approx(-0.147, abs=1e-3)
    assert llm_by_id["WS4-v3-8k-s2-dbd0"]["mean_score"] == pytest.approx(-0.050, abs=1e-3)
    assert llm_by_id["WS4-dagger-r1-8k-verda"]["mean_score"] == pytest.approx(-0.542, abs=1e-3)
    assert llm_by_id["WS4-dagger-r1-4k-verda"]["mean_score"] == pytest.approx(-0.101, abs=1e-3)
    assert all(r["is_open_weight_llm"] is True for r in llm_by_id.values())
    assert all(r["mean_score"] <= 0.0 for r in llm_by_id.values())

    dev_panel = cross["frontier_dev_hard_posthoc_panel"]
    assert dev_panel["protocol_status"] == "post-hoc locked, not pre-registered"
    dev_by_id = {r["cohort_id"]: r for r in dev_panel["rows"]}
    assert dev_by_id["opencode_gemini_4_carbon_hard"]["mean_score"] == pytest.approx(0.3223, abs=1e-3)
    assert dev_by_id["opencode_gemini_4_carbon_hard"]["interviews_per_ep"] == pytest.approx(67.97, abs=0.1)
    assert dev_by_id["opencode_gemini_4_carbon_hard"]["canaries_planted_per_ep"] == pytest.approx(8.47, abs=0.05)
    assert dev_by_id["opencode_gpt_5_5_hard"]["mean_score"] == pytest.approx(0.5037, abs=1e-3)
    assert dev_by_id["opencode_gpt_5_5_hard"]["interviews_per_ep"] == pytest.approx(4.13, abs=0.1)
    assert dev_by_id["opencode_gpt_5_5_hard"]["canaries_planted_per_ep"] == pytest.approx(17.13, abs=0.05)
    assert dev_by_id["opencode_gemini_3_5_flash_hard"]["mean_score"] == pytest.approx(0.373, abs=1e-3)
    assert dev_by_id["solver_reference_hard"]["mean_score"] == pytest.approx(0.499, abs=1e-3)

    curve = summary["budget_pareto_curve"]
    assert len(curve) == 16
    assert [r["is_pareto_optimal"] for r in curve] == tpe.compute_pareto_membership(curve)

    totals = summary["totals"]
    assert totals["total_live_episodes"] == 1440
    assert totals["fresh_env_replays_verified"] == 1440

    eb_caps = summary["policies"]["empirical_bayes"]["caps"]
    cd_caps = summary["policies"]["compact_linear_dagger"]["caps"]
    assert eb_caps["420"]["overall"]["mean_score"] == pytest.approx(0.62233, abs=2e-4)
    assert cd_caps["420"]["overall"]["mean_score"] == pytest.approx(0.66322, abs=2e-4)
    assert eb_caps["4"]["overall"]["wrong_accuse_rate"] == 0.0
    assert cd_caps["4"]["overall"]["wrong_accuse_rate"] == 0.0


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/pareto_efficiency/pareto_summary.json",
        "docs/reports/tiebreak_pareto_efficiency.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tpe.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert tpe.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("47888e4f\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("47888e4f\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "pareto_efficiency" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_pareto_efficiency.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = shallow_root / "results" / "tiebreak" / "pareto_efficiency" / "pareto_summary.json"
    orig_json_txt = json_copy.read_text(encoding="utf-8")
    bad_summary = json.loads(orig_json_txt)
    bad_summary["budget_pareto_curve"][0]["is_pareto_optimal"] = not bool(
        bad_summary["budget_pareto_curve"][0]["is_pareto_optimal"]
    )
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 1
    assert "is_pareto_optimal" in capsys.readouterr().err

    bad_judge = json.loads(orig_json_txt)
    bad_judge["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_judge, indent=2) + "\n", encoding="utf-8")
    assert tpe.main(["--check", "--root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_budget_capped_policy_unit_mechanics_and_live_spot_reproduction() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp
    from scripts.verify_replay import replay_episode

    with pytest.raises(ValueError):
        tpe.BudgetCappedPolicy("empirical_bayes", budget_cap=-1)
    with pytest.raises(ValueError):
        tpe.BudgetCappedPolicy("unknown_policy_kind", budget_cap=4)

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    eb_fac, eb_meta = tpe.load_policy_factory("empirical_bayes", repo_root=REPO_ROOT)
    cd_fac, cd_meta = tpe.load_policy_factory("compact_linear_dagger", repo_root=REPO_ROOT)
    assert eb_meta["is_open_weight_llm"] is False
    assert cd_meta["is_open_weight_llm"] is False

    zero_cap_pol = eb_fac(800_000, budget_cap=0, name="eb:B0")
    with tpe._scoped_world_secret(tpe.HELDOUT_WORLD_SECRET):
        ep_zero = run_episode(Env("easy", 800_000, text_provider=provider), zero_cap_pol)
    assert sum(1 for st in ep_zero.steps if st.tool in tpe.INVESTIGATIVE_MCP_TOOLS) == 0
    assert {st.tool for st in ep_zero.steps}.issubset({"advance_day", "accuse"})
    assert ep_zero.score == 0.0

    spot_cases = (
        ("empirical_bayes", eb_fac, 8),
        ("empirical_bayes", eb_fac, 420),
        ("compact_linear_dagger", cd_fac, 8),
        ("compact_linear_dagger", cd_fac, 420),
    )
    with tpe._fast_compact_dagger_features(), tpe._scoped_world_secret(tpe.HELDOUT_WORLD_SECRET):
        for pid, fac, b_cap in spot_cases:
            pol = fac(800_000, budget_cap=b_cap, name=f"{pid}:B{b_cap}")
            ep = run_episode(Env("easy", 800_000, text_provider=provider), pol)
            rtp.verify_episode_replay(ep, text_provider=provider)
            rep_dict = replay_episode(
                {
                    "tier": ep.tier,
                    "seed": ep.seed,
                    "steps": [{"tool": st.tool, "args": st.args} for st in ep.steps],
                }
            )
            assert rep_dict["score"] == pytest.approx(ep.score, abs=1e-9)
            assert rep_dict["accused"] == ep.accused

            inv_seen = 0
            for st in ep.steps:
                if inv_seen >= b_cap:
                    assert st.tool in ("accuse", "advance_day")
                if st.tool in tpe.INVESTIGATIVE_MCP_TOOLS:
                    inv_seen += 1
            assert inv_seen <= b_cap

            cap_block = summary["policies"][pid]["caps"][str(b_cap)]
            first_score = float(cap_block["episode_scores_csv"].split(",")[0])
            first_inv = int(cap_block["episode_inv_calls_csv"].split(",")[0])
            assert round(float(ep.score), 4) == pytest.approx(first_score, abs=1e-4)
            assert inv_seen == first_inv

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
