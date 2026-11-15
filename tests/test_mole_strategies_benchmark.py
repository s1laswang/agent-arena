from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import tokenize

import numpy as np
import pytest

from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS
from canary.rules import TIERS_VERSION
import scripts.benchmark_mole_strategies as bms
from scripts.benchmark_mole_strategies import (
    INVESTIGATOR_ORDER,
    _CompatRLMoleV2,
    _V2_FEATURE_NAMES,
    check_benchmark_outputs,
    discover_mole_strategies,
    main,
    render_markdown_report,
    serialize_json_report,
    try_load_rl_mole_v2,
    validate_benchmark_seeds,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "benchmark_mole_strategies.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "v14_benchmark.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_strategies_v14_benchmark.md"
TEST_PATH = ROOT / "tests" / "test_mole_strategies_benchmark.py"


def test_owned_files_hygiene_and_zero_social_imports() -> None:
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_ref = "solver_" + "v2"
    forbidden_import_substrings = ("social", "google", "openai", "anthropic", "canary.gemini")

    owned_all = (SCRIPT_PATH, JSON_PATH, MD_PATH, TEST_PATH)
    for path in owned_all:
        assert path.is_file(), f"missing owned file: {path}"
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, str(path)
        assert en_dash not in txt, str(path)
        assert forbidden_ref not in txt, str(path)
        assert all(ord(ch) < 128 for ch in txt), str(path)

    for no_hash_path in (SCRIPT_PATH, JSON_PATH, TEST_PATH):
        txt = no_hash_path.read_text(encoding="utf-8")
        assert hash_ch not in txt, str(no_hash_path)

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], (str(py_path), comments)

        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for bad in forbidden_import_substrings:
                    assert bad not in node.module, (str(py_path), node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden_import_substrings:
                        assert bad not in alias.name, (str(py_path), alias.name)

    assert JSON_PATH.stat().st_size <= 75 * 1024


def test_committed_v14_benchmark_schema_and_invariants() -> None:
    raw_json = JSON_PATH.read_text(encoding="utf-8")
    raw_md = MD_PATH.read_text(encoding="utf-8")
    data = json.loads(raw_json)

    assert serialize_json_report(data) == raw_json
    assert render_markdown_report(data) == raw_md

    assert data["schema_version"] == "mole_strategies_v14_benchmark.v1"
    assert data["tiers_version"] == TIERS_VERSION
    assert data["llm_api_calls"] == 0
    assert data["reporting_order"] == ["raw_score", "luck_adjusted_score"]
    assert data["investigators"] == list(INVESTIGATOR_ORDER)
    assert "hard" in data["tiers"]

    seeds = data["seeds"]
    assert data["n_seeds"] >= 30
    assert len(seeds) == data["n_seeds"]
    assert validate_benchmark_seeds(seeds) == seeds
    assert validate_benchmark_seeds(data["seeds_spec"]) == seeds

    sh = data["seed_hygiene"]
    assert sh["post_hoc_locked_frontier_seeds_0_29_forbidden"] is True
    assert sh["reserved_heldout_30000_30199_forbidden"] is True
    assert sh["heldout_800000_899999_forbidden"] is True
    assert sh["judge_ge_900000_forbidden"] is True
    assert "671ed96" in sh["frontier_seeds_0_29_note"]
    assert "8fd4dec" in sh["frontier_seeds_0_29_note"]

    gates = data["gates"]
    assert gates["min_solver_accuracy"] == pytest.approx(0.85)
    assert gates["max_logs_only_raw_score"] <= 0.0

    descs, v2_meta = discover_mole_strategies()
    expected_catalog = [
        {
            "name": d["name"],
            "family": d["family"],
            "source": d["source"],
            "aliases": list(d.get("aliases", [])),
        }
        for d in descs
    ]
    assert data["strategy_catalog"] == expected_catalog
    assert data["rl_mole_v2_autodetect"]["policy_path"] == v2_meta["policy_path"]

    hard = data["results_by_tier"]["hard"]
    srows = hard["strategies"]
    assert hard["n_strategies"] == len(srows) >= 12
    assert hard["n_side_channel_safe"] == hard["n_strategies"]
    assert hard["n_catchable"] >= 10
    assert hard["n_all_gates_passed"] == hard["n_catchable"]

    by_name = {r["strategy"]: r for r in srows}
    assert "default_v0" in by_name
    assert "frontier_synthesis_v14" in by_name
    assert "gemini_midsize_shield" in by_name
    assert "adaptive_counter_frontier" in by_name
    assert "rl_mole_v1" in by_name

    for row in srows:
        assert row["n_seeds"] == data["n_seeds"]
        assert row["logs_only_raw_mean_score"] <= gates["max_logs_only_raw_score"]
        assert row["side_channel_gate_passed"] is True

        if row["catchability_gate_passed"]:
            assert row["solver_accuracy"] >= gates["min_solver_accuracy"]
            assert row["all_gates_passed"] is True
            assert row["gemini_proxy_regret"] > 0.0
            assert row["codex_proxy_regret"] > 0.0
            assert row["min_frontier_proxy_regret"] > 0.0
            assert row["min_frontier_proxy_luck_adjusted_regret"] > 0.0
        else:
            assert row["solver_accuracy"] < gates["min_solver_accuracy"]
            assert row["all_gates_passed"] is False

        sol = row["cells"]["solver"]
        assert sol["paired_regret_vs_solver"] == 0.0
        assert sol["luck_adjusted_regret_vs_solver"] == 0.0
        for inv_name in INVESTIGATOR_ORDER:
            cell = row["cells"][inv_name]
            assert cell["n"] == data["n_seeds"]
            total_rate = cell["accuracy"] + cell["wrong_rate"] + cell["abstain_rate"]
            assert total_rate == pytest.approx(1.0, abs=5e-6)
            if inv_name != "solver":
                exp_raw_reg = sol["raw_mean_score"] - cell["raw_mean_score"]
                exp_la_reg = sol["luck_adjusted_mean_score"] - cell["luck_adjusted_mean_score"]
                assert cell["paired_regret_vs_solver"] == pytest.approx(exp_raw_reg, abs=5e-6)
                assert cell["luck_adjusted_regret_vs_solver"] == pytest.approx(exp_la_reg, abs=5e-6)

        assert f"`{row['strategy']}`" in raw_md

    best_fp = by_name[hard["best_catchable_by_frontier_proxy_regret"]]
    assert best_fp["all_gates_passed"] is True
    assert best_fp["min_frontier_proxy_regret"] > by_name["default_v0"]["min_frontier_proxy_regret"]
    assert best_fp["min_frontier_proxy_regret_gain_vs_default"] > 0.15

    best_ns = by_name[hard["best_catchable_by_all_non_solver_regret"]]
    assert best_ns["all_gates_passed"] is True
    assert best_ns["min_non_solver_regret"] > by_name["default_v0"]["min_non_solver_regret"]
    assert best_ns["min_non_solver_regret_gain_vs_default"] > 0.10

    raw_sec_idx = raw_md.index("2.1 Raw Mean Score")
    reg_sec_idx = raw_md.index("2.2 Raw Paired Regret")
    luck_sec_idx = raw_md.index("2.3 Luck-Adjusted Scores")
    assert raw_sec_idx < reg_sec_idx < luck_sec_idx
    assert "671ed96" in raw_md and "8fd4dec" in raw_md


def test_seed_hygiene_and_alias_resolution(tmp_path: Path) -> None:
    for bad in (
        "0",
        "29",
        "0-29",
        "30000",
        "30199",
        "800000",
        "899999",
        "900000",
        "6000,6000",
        "",
    ):
        with pytest.raises(ValueError):
            validate_benchmark_seeds(bad)

    for bad_seq in ([-1], [True], b"6000"):
        with pytest.raises(ValueError):
            validate_benchmark_seeds(bad_seq)

    rc_bad = main(
        [
            "--seeds",
            "0-1",
            "--strategies",
            "default_v0",
            "--workers",
            "1",
            "--json-out",
            str(tmp_path / "unused.json"),
            "--md-out",
            str(tmp_path / "unused.md"),
        ]
    )
    assert rc_bad == 2

    aliased, _ = discover_mole_strategies(
        selected_names=["default", "adaptive_combined", "rl_mole"]
    )
    assert [d["name"] for d in aliased] == [
        "default_v0",
        "adaptive_counter_frontier",
        "rl_mole_v1",
    ]
    with pytest.raises(KeyError):
        discover_mole_strategies(selected_names=["nonexistent_strategy"])


def test_rl_mole_v2_compat_autodetect_loader(tmp_path: Path) -> None:
    n_feat = len(_V2_FEATURE_NAMES) + 1
    hidden = 4
    params = {
        "W1": np.zeros((n_feat, hidden), dtype=np.float64),
        "b1": np.zeros((hidden,), dtype=np.float64),
        "Wl": np.zeros((hidden, len(LEAK_SELECTORS)), dtype=np.float64),
        "bl": np.zeros((len(LEAK_SELECTORS),), dtype=np.float64),
        "Wf": np.zeros((hidden, len(FRAME_SELECTORS)), dtype=np.float64),
        "bf": np.zeros((len(FRAME_SELECTORS),), dtype=np.float64),
    }
    pol = _CompatRLMoleV2(params, greedy=True, name="unit_rl_mole_v2")
    pol_path = tmp_path / "rl_mole_v2_policy.json"
    pol_path.write_text(json.dumps(pol.to_json()), encoding="utf-8")

    desc, meta = try_load_rl_mole_v2(pol_path)
    assert desc is not None
    assert meta["detected"] is True
    assert desc["name"] == "rl_mole_v2"
    assert desc["policy_name"] == "unit_rl_mole_v2"

    chosen, meta2 = discover_mole_strategies(
        rl_v2_policy_path=pol_path,
        selected_names=["rl_mole_v2"],
    )
    assert meta2["detected"] is True
    assert len(chosen) == 1 and chosen[0]["name"] == "rl_mole_v2"


def test_two_seed_cli_smoke_and_check_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_out = tmp_path / "smoke_v14.json"
    md_out = tmp_path / "smoke_v14.md"
    cli_args = [
        "--seeds",
        "6000-6001",
        "--strategies",
        "frontier_synthesis_v14",
        "--workers",
        "1",
        "--json-out",
        str(json_out),
        "--md-out",
        str(md_out),
    ]
    rc_write = main(cli_args)
    assert rc_write == 0
    assert json_out.is_file() and md_out.is_file()

    smoke_report = json.loads(json_out.read_text(encoding="utf-8"))
    assert smoke_report["n_seeds"] == 2
    assert smoke_report["seeds"] == [6000, 6001]
    assert [s["name"] for s in smoke_report["strategy_catalog"]] == [
        "frontier_synthesis_v14",
    ]

    rc_check = main(["--check", *cli_args])
    assert rc_check == 0

    md_out.write_text(md_out.read_text(encoding="utf-8") + "\ntamper\n", encoding="utf-8")
    ok_tampered, errs_tampered = check_benchmark_outputs(
        smoke_report, json_out=json_out, md_out=md_out
    )
    assert ok_tampered is False
    assert any("Markdown mismatch" in e for e in errs_tampered)

    ok_missing, errs_missing = check_benchmark_outputs(
        smoke_report, json_out=tmp_path / "missing.json", md_out=md_out
    )
    assert ok_missing is False
    assert any("missing JSON output" in e for e in errs_missing)

    monkeypatch.setattr(bms, "run_benchmark", lambda **_kw: smoke_report)
    assert main(["--check", *cli_args]) == 1


