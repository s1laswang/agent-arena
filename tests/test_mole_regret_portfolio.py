from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import DoNothing, StopEarlyQuit
from canary.env import Env
from canary.eval import run_episode
from canary.mole import regret_portfolio as RP
from canary.solver.policy import SolverPolicy

MODULE_PATH = ROOT / "canary" / "mole" / "regret_portfolio.py"
REPORT_PATH = ROOT / "docs" / "reports" / "mole_regret_portfolio_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)
COAUTHOR_TAG = "co-authored-" + "by"
FLASH_TAG = "gemini-3.5-" + "flash"
SOLVER_PCT_TAG = "% of " + "solver"


def _extract_embedded_ledger(md_text: str) -> dict:
    body = md_text.split(RP.LEDGER_START, 1)[1].split(RP.LEDGER_END, 1)[0].strip()
    json_str = body[len("```json") : -len("```")].strip()
    return json.loads(json_str)


def test_minimax_lp_analytic_duality_and_constraints() -> None:
    inv_order = ("inv_a", "inv_b")
    s1 = RP.StrategyEvalSummary(
        name="strat_1",
        solver_score=0.60,
        solver_accuracy=0.96,
        investigator_scores={"inv_a": 0.20, "inv_b": 0.50},
        investigator_accuracies={"inv_a": 0.80, "inv_b": 0.90},
        investigator_regrets={"inv_a": 0.40, "inv_b": 0.10},
        logs_only_accuracy=0.02,
    )
    s2 = RP.StrategyEvalSummary(
        name="strat_2",
        solver_score=0.58,
        solver_accuracy=0.94,
        investigator_scores={"inv_a": 0.48, "inv_b": 0.18},
        investigator_accuracies={"inv_a": 0.88, "inv_b": 0.78},
        investigator_regrets={"inv_a": 0.10, "inv_b": 0.40},
        logs_only_accuracy=0.04,
    )
    s_bad_zero = RP.StrategyEvalSummary(
        name="strat_dirty_zero",
        solver_score=0.80,
        solver_accuracy=1.00,
        investigator_scores={"inv_a": 0.00, "inv_b": 0.00},
        investigator_accuracies={"inv_a": 0.50, "inv_b": 0.50},
        investigator_regrets={"inv_a": 0.80, "inv_b": 0.80},
        logs_only_accuracy=0.00,
        do_nothing_score=0.05,
    )

    fit = RP.solve_minimax_regret_portfolio(
        [s1, s2, s_bad_zero],
        investigator_order=inv_order,
        min_solver_acc=0.90,
        max_logs_only_acc=0.10,
    )
    assert fit.gates_passed is True
    assert fit.excluded_zero_baseline_strategies == ("strat_dirty_zero",)
    assert fit.weights["strat_dirty_zero"] == 0.0
    assert fit.weights["strat_1"] == pytest.approx(0.5, abs=1e-9)
    assert fit.weights["strat_2"] == pytest.approx(0.5, abs=1e-9)
    assert fit.min_regret == pytest.approx(0.25, abs=1e-9)
    assert fit.min_regret > max(s1.min_regret, s2.min_regret)
    assert set(fit.binding_investigators) == {"inv_a", "inv_b"}
    assert fit.dual_investigator_weights["inv_a"] == pytest.approx(0.5, abs=1e-6)
    assert fit.dual_investigator_weights["inv_b"] == pytest.approx(0.5, abs=1e-6)
    assert fit.duality_gap == pytest.approx(0.0, abs=1e-10)

    s_high_reg_low_sol = RP.StrategyEvalSummary(
        name="aggressive",
        solver_score=0.50,
        solver_accuracy=0.80,
        investigator_scores={"inv_a": 0.00, "inv_b": 0.00},
        investigator_accuracies={"inv_a": 0.60, "inv_b": 0.60},
        investigator_regrets={"inv_a": 0.50, "inv_b": 0.50},
        logs_only_accuracy=0.02,
    )
    s_safe = RP.StrategyEvalSummary(
        name="safe",
        solver_score=0.60,
        solver_accuracy=0.95,
        investigator_scores={"inv_a": 0.40, "inv_b": 0.40},
        investigator_accuracies={"inv_a": 0.85, "inv_b": 0.85},
        investigator_regrets={"inv_a": 0.20, "inv_b": 0.20},
        logs_only_accuracy=0.02,
    )
    constrained = RP.solve_minimax_regret_portfolio(
        [s_high_reg_low_sol, s_safe],
        investigator_order=inv_order,
        min_solver_acc=0.90,
        max_logs_only_acc=0.10,
    )
    assert constrained.expected_solver_accuracy == pytest.approx(0.90, abs=1e-9)
    assert constrained.weights["aggressive"] == pytest.approx(1.0 / 3.0, abs=1e-8)
    assert constrained.weights["safe"] == pytest.approx(2.0 / 3.0, abs=1e-8)
    assert constrained.min_regret == pytest.approx(0.30, abs=1e-8)

    with pytest.raises(RP.PortfolioInfeasibleError):
        RP.solve_minimax_regret_portfolio(
            [s1, s2],
            investigator_order=inv_order,
            min_solver_acc=0.99,
            max_logs_only_acc=0.10,
        )
    with pytest.raises(RP.PortfolioInfeasibleError):
        RP.solve_minimax_regret_portfolio([s_bad_zero], investigator_order=inv_order)
    with pytest.raises(ValueError, match="empty"):
        RP.solve_minimax_regret_portfolio([], investigator_order=inv_order)
    with pytest.raises(ValueError, match="duplicate"):
        RP.solve_minimax_regret_portfolio([s1, s1], investigator_order=inv_order)


def test_v14_precomputed_fit_matches_committed_report_and_dominates_pure() -> None:
    summaries, meta = RP.load_summaries_from_v14_json()
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["n_seeds"] == 200
    assert meta["seed_range"] == "6000-6199"
    assert len(summaries) == 7

    fit = RP.solve_minimax_regret_portfolio(summaries)
    assert fit.gates_passed is True
    assert fit.active_strategies == ("surgical_trap_shield", "gemini_midsize_shield")
    assert sum(fit.weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert fit.expected_solver_accuracy >= 0.90
    assert fit.expected_logs_only_accuracy <= 0.10
    assert fit.expected_do_nothing_score == 0.0
    assert fit.expected_stop_early_quit_score == 0.0
    assert fit.duality_gap < 1e-12

    best_pure_min = max(s.min_regret for s in summaries)
    assert fit.min_regret > best_pure_min + 0.009
    assert set(fit.binding_investigators) == {"gemini_carbon_proxy", "hinted_heuristic"}
    assert fit.expected_regrets["gemini_carbon_proxy"] == pytest.approx(
        fit.expected_regrets["hinted_heuristic"],
        abs=1e-9,
    )

    ledger = _extract_embedded_ledger(REPORT_PATH.read_text(encoding="utf-8"))
    assert ledger["train"]["portfolio"]["weights"] == pytest.approx(fit.weights, abs=1e-12)
    assert ledger["train"]["portfolio"]["min_regret"] == pytest.approx(fit.min_regret, abs=1e-12)
    assert ledger["validation"]["gates_passed"] is True
    assert ledger["validation"]["regret_portfolio_v14"]["solver_accuracy"] >= 0.90
    assert ledger["validation"]["regret_portfolio_v14"]["logs_only_accuracy"] <= 0.10
    assert ledger["validation"]["regret_portfolio_v14"]["do_nothing_score"] == 0.0
    assert ledger["validation"]["regret_portfolio_v14"]["stop_early_quit_score"] == 0.0


def test_seed_hashing_and_portfolio_mole_policy_episode() -> None:
    weights = {
        "surgical_trap_shield": 0.75,
        "gemini_midsize_shield": 0.25,
        "default_v0": 0.0,
    }
    norm = RP.normalize_portfolio_weights({"gemini_midsize_shield": 1.0, "surgical_trap_shield": 3.0})
    assert list(norm.keys()) == ["surgical_trap_shield", "gemini_midsize_shield"]
    assert norm["surgical_trap_shield"] == pytest.approx(0.75)
    assert norm["gemini_midsize_shield"] == pytest.approx(0.25)

    for bad_w in (
        {},
        {"unknown_strat": 1.0},
        {"default_v0": True},
        {"default_v0": -0.1, "surgical_trap_shield": 1.1},
        {"default_v0": 0.0},
        {"default_v0": float("nan")},
    ):
        with pytest.raises((KeyError, ValueError)):
            RP.normalize_portfolio_weights(bad_w)

    with pytest.raises(TypeError):
        RP.portfolio_seed_unit(True)

    u1 = RP.portfolio_seed_unit(6812)
    u2 = RP.portfolio_seed_unit(6812)
    assert u1 == u2
    assert 0.0 <= u1 < 1.0
    assert RP.portfolio_seed_unit(6812, salt="alt") != u1

    hits = sum(
        1
        for s in range(10_000, 12_000)
        if RP.select_portfolio_strategy(s, weights).name == "surgical_trap_shield"
    )
    assert abs(hits / 2000.0 - 0.75) < 0.03

    base_policy = RP.PortfolioMolePolicy(weights)
    seeded_policy = base_policy.for_seed(6812)
    roundtrip = RP.PortfolioMolePolicy.from_json(seeded_policy.to_json(), seed=6812)
    assert roundtrip.selected_name == seeded_policy.selected_name
    assert roundtrip.weights == seeded_policy.weights

    with pytest.raises(TypeError):
        RP.PortfolioMolePolicy(6812)
    with pytest.raises(TypeError):
        RP.PortfolioMolePolicy(weights, weights)
    with pytest.raises(ValueError):
        RP.PortfolioMolePolicy.from_json({})

    sol_ep = run_episode(
        Env("easy", 6812, mole_strategy=seeded_policy),
        SolverPolicy("easy", act_budget=5.0),
    )
    dn_ep = run_episode(Env("easy", 6812, mole_strategy=seeded_policy), DoNothing(seed=6812))
    seq_ep = run_episode(Env("easy", 6812, mole_strategy=seeded_policy), StopEarlyQuit(seed=6812))
    assert sol_ep.correct is True
    assert dn_ep.score == 0.0
    assert seq_ep.score == 0.0


@pytest.mark.parametrize(
    "bad_seeds",
    [
        "",
        "70-65",
        "6800,",
        "-1",
        "0",
        "29",
        "59",
        "0-59",
        "30000",
        "30199",
        "30000-30199",
        "800000",
        "900000",
        "6812,6812",
    ],
)
def test_seed_hygiene_and_disjoint_splits(bad_seeds: str) -> None:
    with pytest.raises(ValueError):
        RP.validate_eval_seeds(bad_seeds)

    assert RP.validate_eval_seeds("60,29999,30200,799999") == [60, 29999, 30200, 799999]
    RP.assert_disjoint_seed_splits([6000, 6001], [6812, 6813])
    with pytest.raises(ValueError, match="overlap"):
        RP.assert_disjoint_seed_splits([6000, 6812], [6812, 6813])


def test_committed_markdown_check_and_tamper_rejection(tmp_path: Path, capsys) -> None:
    assert REPORT_PATH.is_file()
    assert REPORT_PATH.stat().st_size < 120_000

    ok, msg = RP.check_markdown_report(REPORT_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = RP.main(["--check", "--out", str(REPORT_PATH)])
    assert rc == 0
    assert "OK:" in capsys.readouterr().out

    ok_miss, msg_miss = RP.check_markdown_report(tmp_path / "missing.md")
    assert ok_miss is False
    assert "missing" in msg_miss

    md_text = REPORT_PATH.read_text(encoding="utf-8")
    drifted = tmp_path / "drifted.md"
    drifted.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = RP.check_markdown_report(drifted)
    assert ok_drift is False
    assert "do not match" in msg_drift

    dashed = tmp_path / "dashed.md"
    dashed.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = RP.check_markdown_report(dashed)
    assert ok_dash is False
    assert "dash" in msg_dash

    claimed = tmp_path / "claimed.md"
    claimed.write_text(md_text + f"\n{FLASH_TAG} {SOLVER_PCT_TAG}\n", encoding="utf-8")
    ok_claim, msg_claim = RP.check_markdown_report(claimed)
    assert ok_claim is False
    assert "forbidden claim" in msg_claim

    ledger = _extract_embedded_ledger(md_text)
    bad_gate = copy.deepcopy(ledger)
    bad_gate["validation"]["regret_portfolio_v14"]["solver_accuracy"] = 0.50
    bad_gate_md = tmp_path / "bad_gate.md"
    bad_gate_md.write_text(RP.render_markdown_report(bad_gate), encoding="utf-8")
    ok_gate, msg_gate = RP.check_markdown_report(bad_gate_md)
    assert ok_gate is False
    assert "solver accuracy" in msg_gate

    leaked = copy.deepcopy(ledger)
    leaked["true_mole"] = "e01"
    with pytest.raises(ValueError, match="forbidden key"):
        RP.assert_payload_hygiene(leaked)

    fake_tok = "AI" + "za" + "fixture0123456789abcdefghij"
    with pytest.raises(ValueError, match="secret-like token"):
        RP.assert_payload_hygiene({"note": fake_tok})


def test_single_seed_pipeline_smoke(tmp_path: Path, capsys) -> None:
    smoke_md = tmp_path / "smoke_portfolio.md"
    rc = RP.main(["--out", str(smoke_md), "--tier", "easy", "--val-seeds", "6850", "--workers", "1"])
    assert rc == 0
    capsys.readouterr()
    assert smoke_md.is_file()
    assert smoke_md.stat().st_size < 120_000
    ok, msg = RP.check_markdown_report(smoke_md)
    assert ok is True, msg


def test_pr42_hygiene_gates() -> None:
    forbidden_gap_re = re.compile(
        r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
        re.IGNORECASE,
    )
    for py_file in (MODULE_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment token in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"unexpected raw hash character in {py_file}"

    for path in (MODULE_PATH, TEST_PATH, REPORT_PATH):
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em-dash found in {path}"
        assert EN_DASH not in text, f"en-dash found in {path}"
        assert UNICODE_MINUS not in text, f"unicode minus found in {path}"
        assert all(ord(ch) < 128 for ch in text), f"non-ASCII character found in {path}"
        assert COAUTHOR_TAG not in text.lower(), f"coauthor trailer found in {path}"
        assert FLASH_TAG not in text.lower(), f"forbidden flash claim in {path}"
        assert SOLVER_PCT_TAG not in text.lower(), f"forbidden solver pct claim in {path}"
        assert forbidden_gap_re.search(text) is None, f"forbidden gap ratio claim in {path}"
