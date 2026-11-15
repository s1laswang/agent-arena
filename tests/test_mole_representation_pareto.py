from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import time
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.forge.rl_mole import RLMole
from canary.mole import representation_pareto as RP
from canary.mole.dsl import MoleStrategy
from canary.mole.regret_portfolio import PortfolioMolePolicy

MODULE_PATH = ROOT / "canary" / "mole" / "representation_pareto.py"
JSON_PATH = RP.DEFAULT_OUT_PATH
MD_PATH = RP.DEFAULT_REPORT_MD_PATH
TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
COAUTHOR_TAG = "co-authored-" + "by"
FLASH_TAG = "gemini-3.5-" + "flash"
SOLVER_PCT_TAG = "% of " + "solver"


def test_committed_artifacts_and_fast_check_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    assert RP.MAX_JSON_BYTES == 90_000
    assert JSON_PATH.stat().st_size < 90_000

    t0 = time.perf_counter()
    ok, msg = RP.check_representation_pareto_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    elapsed = time.perf_counter() - t0
    assert ok is True, msg
    assert "OK:" in msg
    assert elapsed < 2.0

    for argv in (
        ["--check"],
        ["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)],
    ):
        rc = RP.main(argv)
        captured = capsys.readouterr()
        assert rc == 0
        assert "OK:" in captured.out

    report = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert report["tier"] == "hard"
    assert report["tiers_version"] == "v1.4"
    assert report["api_calls"] == 0
    assert report["bootstrap_config"]["n_boot"] == 2000

    sh = report["seed_hygiene"]
    assert sh["live_seed_range"] == "7400-7459"
    assert sh["live_n_seeds"] == 60
    assert sh["live_seeds"] == list(range(7400, 7460))
    assert sh["counterfactual_n_transcripts"] == 60
    assert sh["counterfactual_sources"] == ["opencode", "inproc"]

    expected_policies = [
        "default_v0",
        "surgical_trap_shield",
        "gemini_midsize_shield",
        "early_burst_midgame_pace",
        "frontier_synthesis_v14",
        "hof_v14_r1",
        "rl_mole_frontier_v14",
        "rl_mole_frontier_v14_softmax",
        "regret_portfolio_v14",
    ]
    assert report["policy_order"] == expected_policies
    assert report["summary"]["n_policies"] == 9
    assert report["summary"]["n_non_baseline_policies"] == 8
    assert report["summary"]["n_families"] == 3
    assert report["summary"]["all_fairness_gates_passed"] is True

    pols = report["policies"]
    assert pols["default_v0"]["complexity"]["n_rules"] == 0
    assert pols["default_v0"]["complexity"]["effective_param_count"] == 0
    assert pols["hof_v14_r1"]["alias"] == "window_crowd_stale"
    assert pols["hof_v14_r1"]["complexity"]["n_rules"] == 5
    assert pols["rl_mole_frontier_v14"]["complexity"]["n_continuous_weights"] == 450
    assert pols["rl_mole_frontier_v14_softmax"]["complexity"]["n_continuous_weights"] == 450
    assert pols["regret_portfolio_v14"]["complexity"]["mixture_support_size"] == 2

    for pkey in expected_policies:
        lv = pols[pkey]["live"]
        fg = pols[pkey]["fairness_gates"]
        assert fg["passed"] is True
        assert lv["solver_acc"] >= 0.85
        assert lv["logs_only_acc"] <= 0.10
        assert lv["do_nothing_max_abs"] == 0.0
        assert lv["stop_early_quit_max_abs"] == 0.0

    p_live = report["pareto_frontiers"]["live_proxy_pareto"]
    p_cf = report["pareto_frontiers"]["counterfactual_catchability_pareto"]
    assert set(p_live["frontier_families"]) >= {"symbolic_dsl", "continuous_rl_mole", "minimax_portfolio"}
    assert len(p_cf["frontier"]) >= 1
    assert RP.format_markdown_report(report) == MD_PATH.read_text(encoding="utf-8")


def test_tamper_and_hygiene_rejection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok_mj, msg_mj = RP.check_representation_pareto_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_mj is False
    assert "missing JSON" in msg_mj

    ok_mm, msg_mm = RP.check_representation_pareto_artifacts(
        json_path=JSON_PATH,
        md_path=tmp_path / "missing.md",
    )
    assert ok_mm is False
    assert "missing Markdown" in msg_mm

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * RP.MAX_JSON_BYTES, encoding="utf-8")
    ok_big, msg_big = RP.check_representation_pareto_artifacts(json_path=oversized, md_path=MD_PATH)
    assert ok_big is False
    assert "byte limit" in msg_big

    md_orig = MD_PATH.read_text(encoding="utf-8")
    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_orig + "\nextra line\n", encoding="utf-8")
    ok_drift, msg_drift = RP.check_representation_pareto_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    for idx, bad_text in enumerate(
        (
            EM_DASH,
            EN_DASH,
            UNICODE_MINUS,
            FLASH_TAG,
            SOLVER_PCT_TAG,
            "frontier" + " / " + "solver",
            COAUTHOR_TAG + ": Bot",
            "e" + "07",
            "AI" + "za" + "fixture0123456789abcdefghij",
        )
    ):
        bad_md = tmp_path / f"bad_{idx}.md"
        bad_md.write_text(md_orig + f"\n{bad_text}\n", encoding="utf-8")
        ok_b, msg_b = RP.check_representation_pareto_artifacts(json_path=JSON_PATH, md_path=bad_md)
        assert ok_b is False
        assert "FAIL:" in msg_b

    base_report = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    gate_tamper = copy.deepcopy(base_report)
    gate_tamper["policies"]["default_v0"]["live"]["solver_acc"] = 0.50
    gate_json = tmp_path / "gate_tamper.json"
    gate_json.write_text(RP.dumps_compact_json(gate_tamper) + "\n", encoding="utf-8")
    rc_gate = RP.main(["--check", "--out", str(gate_json), "--report-md", str(MD_PATH)])
    err_gate = capsys.readouterr().err
    assert rc_gate == 1
    assert "fairness_gates" in err_gate

    pareto_tamper = copy.deepcopy(base_report)
    pareto_tamper["pareto_frontiers"]["live_proxy_pareto"]["frontier"] = ["default_v0"]
    pareto_json = tmp_path / "pareto_tamper.json"
    pareto_json.write_text(RP.dumps_compact_json(pareto_tamper) + "\n", encoding="utf-8")
    ok_pt, msg_pt = RP.check_representation_pareto_artifacts(json_path=pareto_json, md_path=MD_PATH)
    assert ok_pt is False
    assert "pareto_frontiers" in msg_pt

    for bad_key in ("true_mole", "mole_strategy", "salt", "posterior"):
        leaked = copy.deepcopy(base_report)
        leaked[bad_key] = 1
        with pytest.raises(ValueError, match="forbidden secret key"):
            RP.assert_artifact_hygiene(leaked)


def test_pareto_dominance_and_frontier_peeling() -> None:
    assert RP.pareto_dominates((0.60, 0.25), (0.55, 0.25)) is True
    assert RP.pareto_dominates((0.60, 0.25), (0.60, 0.20)) is True
    assert RP.pareto_dominates((0.60, 0.25), (0.50, 0.10)) is True
    assert RP.pareto_dominates((0.60, 0.25), (0.60, 0.25)) is False
    assert RP.pareto_dominates((0.60, 0.25), (0.60 + 1e-13, 0.25 - 1e-13)) is False
    assert RP.pareto_dominates((0.65, 0.15), (0.55, 0.25)) is False
    assert RP.pareto_dominates((0.55, 0.25), (0.65, 0.15)) is False

    synthetic = {
        "dsl_high_x": {"x": 0.65, "y": 0.15, "feasible": True, "family": "symbolic_dsl"},
        "port_mid": {"x": 0.60, "y": 0.21, "feasible": True, "family": "minimax_portfolio"},
        "rl_high_y": {"x": 0.54, "y": 0.28, "feasible": True, "family": "continuous_rl_mole"},
        "rl_tie": {"x": 0.54, "y": 0.28, "feasible": True, "family": "continuous_rl_mole"},
        "dom_layer2": {"x": 0.58, "y": 0.18, "feasible": True, "family": "symbolic_dsl"},
        "dom_layer3": {"x": 0.50, "y": 0.10, "feasible": True, "family": "baseline"},
        "unfair_super": {"x": 0.99, "y": 0.99, "feasible": False, "family": "symbolic_dsl"},
    }
    res = RP.compute_pareto_frontier(synthetic, x_key="x", y_key="y", feasible_key="feasible")
    assert res["frontier"] == ["dsl_high_x", "port_mid", "rl_high_y", "rl_tie"]
    assert res["infeasible"] == ["unfair_super"]
    assert res["dominated"] == ["dom_layer2", "dom_layer3"]
    assert res["n_layers"] == 3
    assert res["frontier_families"] == ["continuous_rl_mole", "minimax_portfolio", "symbolic_dsl"]

    pp = res["per_policy"]
    assert pp["unfair_super"]["pareto_optimal"] is False
    assert pp["unfair_super"]["pareto_rank"] is None
    assert pp["dom_layer2"]["pareto_rank"] == 2
    assert pp["dom_layer2"]["dominated_by"] == ["port_mid"]
    assert pp["dom_layer3"]["pareto_rank"] == 3
    assert set(pp["dom_layer3"]["dominated_by"]) == {
        "dsl_high_x",
        "port_mid",
        "rl_high_y",
        "rl_tie",
        "dom_layer2",
    }


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "-1",
        "0",
        "59",
        "6000",
        "6199",
        "6999",
        "30000",
        "30199",
        "110000",
        "110999",
        "800000",
        "900000",
        "7405-7400",
        "7400,7400",
    ],
)
def test_seed_hygiene_validators(bad_spec: str) -> None:
    with pytest.raises(ValueError):
        RP.validate_pareto_seeds(bad_spec)


def test_valid_seeds_policy_instantiation_and_cf_replay() -> None:
    assert RP.validate_pareto_seeds("7400-7402") == [7400, 7401, 7402]
    assert RP.validate_pareto_seeds("60,5999,7000,29999,30200,799999") == [
        60,
        5999,
        7000,
        29999,
        30200,
        799999,
    ]
    with pytest.raises(ValueError):
        RP.validate_pareto_seeds(True)
    with pytest.raises(ValueError):
        RP.validate_pareto_seeds([7400, False])

    specs = RP.load_representative_policies(
        selected_keys=["window_crowd_stale", "rl_mole_frontier_v14", "rl_mole_frontier_v14_softmax", "regret_portfolio_v14"]
    )
    assert list(specs.keys()) == [
        "default_v0",
        "hof_v14_r1",
        "rl_mole_frontier_v14",
        "rl_mole_frontier_v14_softmax",
        "regret_portfolio_v14",
    ]
    assert isinstance(RP.instantiate_mole_policy(specs["hof_v14_r1"].worker_payload, 7400), MoleStrategy)
    rl_g = RP.instantiate_mole_policy(specs["rl_mole_frontier_v14"].worker_payload, 7400)
    rl_s = RP.instantiate_mole_policy(specs["rl_mole_frontier_v14_softmax"].worker_payload, 7400)
    port = RP.instantiate_mole_policy(specs["regret_portfolio_v14"].worker_payload, 7400)
    assert isinstance(rl_g, RLMole) and rl_g.greedy is True
    assert isinstance(rl_s, RLMole) and rl_s.greedy is False
    assert isinstance(port, PortfolioMolePolicy) and port.seed == 7400

    payload_subset = {
        k: specs[k].worker_payload
        for k in ("default_v0", "rl_mole_frontier_v14", "regret_portfolio_v14")
    }
    cf_out = RP._eval_cf_transcript_worker(("hard", "opencode", 0, payload_subset))
    assert cf_out["source"] == "opencode"
    assert cf_out["seed"] == 0
    for k in payload_subset:
        assert 0.0 <= cf_out["policies"][k]["p_true_mole"] <= 1.0
        assert cf_out["policies"][k]["optimal_ev"] >= 0.0


def test_bootstrap_fairness_gates_and_summary_helpers() -> None:
    ci_a = RP.paired_bootstrap_ci([0.1, 0.2, 0.3, 0.4], n_boot=500, seed=123, tag="unit")
    ci_b = RP.paired_bootstrap_ci([0.1, 0.2, 0.3, 0.4], n_boot=500, seed=123, tag="unit")
    assert ci_a == ci_b
    assert ci_a["ci_low"] <= ci_a["mean"] <= ci_a["ci_high"]

    cur_regs = {"gemini_carbon_proxy": [0.20, 0.30, 0.25], "codex_horizon_proxy": [0.35, 0.25, 0.30]}
    base_regs = {"gemini_carbon_proxy": [0.10, 0.20, 0.15], "codex_horizon_proxy": [0.30, 0.20, 0.25]}
    min_ci, gain_ci = RP.paired_minimax_bootstrap_ci(
        cur_regs,
        base_regs,
        RP.FRONTIER_PROXY_ORDER,
        n_boot=500,
        seed=123,
        tag="minimax",
    )
    assert min_ci["mean"] == 0.25
    assert gain_ci["mean"] == 0.10
    assert gain_ci["ci_low"] > 0.0

    assert RP.evaluate_fairness_gates(
        solver_acc=0.85,
        logs_only_acc=0.10,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.0,
    )["passed"] is True
    assert RP.evaluate_fairness_gates(
        solver_acc=0.84,
        logs_only_acc=0.10,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.0,
    )["passed"] is False
    assert RP.evaluate_fairness_gates(
        solver_acc=0.95,
        logs_only_acc=0.11,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.0,
    )["passed"] is False
    assert RP.evaluate_fairness_gates(
        solver_acc=0.95,
        logs_only_acc=0.0,
        do_nothing_max_abs=0.01,
        stop_early_quit_max_abs=0.0,
    )["passed"] is False
    assert RP.evaluate_fairness_gates(
        solver_acc=0.95,
        logs_only_acc=0.0,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.01,
    )["passed"] is False

    rep = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    term = RP.format_terminal_summary(rep)
    assert "Mole Representation Pareto Benchmark v1.4" in term
    assert "regret_portfolio_v14" in term


def test_zero_comments_zero_hash_and_artifact_hygiene() -> None:
    emp_re = re.compile(r"\be\d{2}\b")
    gap_re = re.compile(
        r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
        re.IGNORECASE,
    )
    for py_path in (MODULE_PATH, TEST_PATH):
        with py_path.open("rb") as fh:
            comment_tokens = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"comment token found in {py_path}"
        py_src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_src, f"raw hash character found in {py_path}"

    for doc_path in (MODULE_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = doc_path.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert UNICODE_MINUS not in txt
        assert txt.isascii()
        assert COAUTHOR_TAG not in txt.lower()
        assert FLASH_TAG not in txt.lower()
        assert SOLVER_PCT_TAG not in txt.lower()
        assert gap_re.search(txt) is None

    for report_artifact in (JSON_PATH, MD_PATH):
        art_txt = report_artifact.read_text(encoding="utf-8")
        assert emp_re.search(art_txt) is None, f"employee ID leaked in {report_artifact}"
