from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import tokenize

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import DoNothing
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import RLMole
from canary.forge_track import _strategy
from canary.mole import distill_rl_mole as D
from canary.mole.fairness_audit import CHECK_NAMES
from canary.solver.policy import SolverPolicy

MODULE_PATH = ROOT / "canary" / "mole" / "distill_rl_mole.py"
POLICY_PATH = ROOT / "data" / "forge" / "rl_mole_frontier_v14.json"
REPORT_PATH = ROOT / "docs" / "reports" / "rl_mole_frontier_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)
COAUTHOR_TAG = "co-authored-" + "by"
FLASH_TAG = "gemini-3.5-" + "flash"
SOLVER_PCT_TAG = "% of " + "solver"


def test_committed_artifacts_and_check_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert POLICY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert D.MAX_POLICY_JSON_BYTES <= 95_000
    assert POLICY_PATH.stat().st_size < 95_000
    assert REPORT_PATH.stat().st_size < 95_000

    ok, msg = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=REPORT_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    for argv in (
        ["--check"],
        ["check", "--policy", str(POLICY_PATH), "--report", str(REPORT_PATH)],
        ["--check", "--out", str(POLICY_PATH), "--report-out", str(REPORT_PATH)],
    ):
        rc = D.main(argv)
        captured = capsys.readouterr()
        assert rc == 0
        assert "OK:" in captured.out

    raw_policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    pol_rl = RLMole.from_json(raw_policy)
    pol_ft = _strategy(raw_policy)
    pol_coerced = D.coerce_mole_policy(POLICY_PATH)
    assert isinstance(pol_rl, RLMole)
    assert isinstance(pol_ft, RLMole)
    assert isinstance(pol_coerced, RLMole)
    assert pol_rl.to_json() == raw_policy
    assert pol_rl.name == "rl_mole_frontier_v14"
    assert pol_rl.greedy is True
    assert int(pol_rl.p["W1"].shape[1]) == 20

    md_text = REPORT_PATH.read_text(encoding="utf-8")
    ledger = D.parse_embedded_ledger(md_text)
    D.assert_ledger_invariants(ledger, policy_obj=raw_policy)
    assert D.render_report_from_ledger(ledger) == md_text
    assert D.canonical_rl_mole_sha256(pol_rl) == ledger["canonical_sha256"]

    val = ledger["validation"]
    assert val["all_gates_passed"] is True
    assert val["heldout"]["refined"]["feasible"] is True
    assert val["heldout"]["refined"]["solver_acc"] >= 0.85
    assert val["heldout"]["refined"]["logs_only_acc"] <= 0.10
    assert val["heldout"]["refined"]["accuse_most_logs_acc"] <= 0.10
    assert val["heldout"]["refined"]["do_nothing_score"] == 0.0
    assert val["heldout"]["refined"]["min_regret_gain"] > 0.0
    assert val["heldout"]["refined"]["mean_regret_gain"] > 0.15

    fa = val["fairness_audit"]
    assert fa["all_passed"] is True
    assert fa["fairness_passed"] is True
    for ck in CHECK_NAMES:
        assert fa["checks"][ck]["passed"] is True

    cf = val["counterfactual_v14_hard"]
    assert cf["n_total_episodes"] == 8
    cf_strat = cf["strategies"]["rl_mole_frontier_v14"]
    assert cf_strat["combined"]["p_true_mole_drop"] > 0.25
    assert cf_strat["combined"]["optimal_ev_drop"] > 0.25
    assert cf_strat["counterfactual_gap_gain"] > 0.35
    assert cf_strat["solver"]["accuracy"] >= 0.85
    assert cf_strat["solver"]["feasible"] is True


def test_tamper_and_hygiene_rejection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok_miss_p, msg_miss_p = D.check_distilled_artifacts(
        policy_path=tmp_path / "missing.json",
        report_path=REPORT_PATH,
    )
    assert ok_miss_p is False
    assert "missing policy" in msg_miss_p

    ok_miss_r, msg_miss_r = D.check_distilled_artifacts(
        policy_path=POLICY_PATH,
        report_path=tmp_path / "missing.md",
    )
    assert ok_miss_r is False
    assert "missing Markdown" in msg_miss_r

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * D.MAX_POLICY_JSON_BYTES, encoding="utf-8")
    ok_big, msg_big = D.check_distilled_artifacts(policy_path=oversized, report_path=REPORT_PATH)
    assert ok_big is False
    assert "byte limit" in msg_big

    md_text = REPORT_PATH.read_text(encoding="utf-8")
    drifted = tmp_path / "drifted.md"
    drifted.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=drifted)
    assert ok_drift is False
    assert "does not match" in msg_drift

    for bad_char in (EM_DASH, EN_DASH, UNICODE_MINUS):
        bad_md = tmp_path / f"char_{ord(bad_char)}.md"
        bad_md.write_text(md_text + "\n" + bad_char + "\n", encoding="utf-8")
        ok_c, msg_c = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=bad_md)
        assert ok_c is False
        assert "FAIL:" in msg_c

    coauthor_md = tmp_path / "coauthor.md"
    coauthor_md.write_text(md_text + f"\n{COAUTHOR_TAG}: Test\n", encoding="utf-8")
    ok_co, _ = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=coauthor_md)
    assert ok_co is False

    flash_md = tmp_path / "flash.md"
    flash_md.write_text(md_text + f"\n{FLASH_TAG}\n", encoding="utf-8")
    ok_fl, msg_fl = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=flash_md)
    assert ok_fl is False
    assert FLASH_TAG in msg_fl

    ratio_md = tmp_path / "ratio.md"
    ratio_claim = "frontier" + " / " + "solver"
    ratio_md.write_text(md_text + f"\n{ratio_claim}\n", encoding="utf-8")
    ok_rt, _ = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=ratio_md)
    assert ok_rt is False

    fake_key = "AI" + "za" + "fixture0123456789abcdefghij"
    key_md = tmp_path / "key.md"
    key_md.write_text(md_text + f"\n{fake_key}\n", encoding="utf-8")
    ok_key, msg_key = D.check_distilled_artifacts(policy_path=POLICY_PATH, report_path=key_md)
    assert ok_key is False
    assert "API key" in msg_key

    raw_policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    tampered_pol = copy.deepcopy(raw_policy)
    tampered_pol["params"]["b1"][0] = round(float(tampered_pol["params"]["b1"][0]) + 0.125, 8)
    tampered_path = tmp_path / "tampered_policy.json"
    tampered_path.write_text(json.dumps(tampered_pol, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rc_tamper = D.main(["--check", "--policy", str(tampered_path), "--report", str(REPORT_PATH)])
    captured_err = capsys.readouterr()
    assert rc_tamper == 1
    assert "sha256" in captured_err.err

    ledger = D.parse_embedded_ledger(md_text)
    leaked_ledger = copy.deepcopy(ledger)
    leaked_ledger["true_mole"] = "e01"
    with pytest.raises(ValueError, match="forbidden secret key"):
        D.assert_ledger_invariants(leaked_ledger)

    bad_sol_ledger = copy.deepcopy(ledger)
    bad_sol_ledger["validation"]["heldout"]["refined"]["solver_acc"] = 0.50
    with pytest.raises(ValueError, match="solver catchability"):
        D.assert_ledger_invariants(bad_sol_ledger)

    bad_overlap = copy.deepcopy(ledger)
    bad_overlap["train_config"]["bc_seeds"] = "110000-110002"
    bad_overlap["validation"]["heldout"]["refined"]["seeds"][0] = 110001
    with pytest.raises(ValueError):
        D.assert_ledger_invariants(bad_overlap)


@pytest.mark.parametrize(
    "bad_train",
    [
        "",
        "0",
        "59",
        "60",
        "30000",
        "109999",
        "200000",
        "210020",
        "219999",
        "800000",
        "900000",
        "110005-110001",
        "110000,110000",
    ],
)
def test_train_and_eval_seed_hygiene(bad_train: str) -> None:
    with pytest.raises(ValueError):
        D.validate_train_seeds(bad_train)


def test_worker_and_seed_validators() -> None:
    assert D.validate_workers(1) == 1
    for bad_w in (0, 2, -1):
        with pytest.raises(ValueError, match="single-process"):
            D.validate_workers(bad_w)

    with pytest.raises(ValueError):
        D.normalize_seeds(True)
    with pytest.raises(ValueError):
        D.normalize_seeds([110000, False])

    assert D.validate_train_seeds("110000-110002") == [110000, 110001, 110002]
    assert D.validate_train_seeds("n:2") == [110000, 110001]
    assert D.validate_eval_seeds("60,29999,30200,210020,799999") == [60, 29999, 30200, 210020, 799999]

    for bad_eval in ("0", "59", "30000", "30199", "800000", "900000", "210020,210020"):
        with pytest.raises(ValueError):
            D.validate_eval_seeds(bad_eval)


def test_fast_bc_refinement_and_episode_determinism() -> None:
    bc = D.clone_strategy_to_rl_mole(
        teacher="frontier_synthesis_v14",
        tier="easy",
        seeds=[110000],
        hidden=8,
        epochs=35,
        include_boundary_views=False,
        seed=7,
        workers=1,
    )
    bc_pol = bc["policy"]
    assert isinstance(bc_pol, RLMole)
    assert bc["bc_metrics"]["n_rollout_views"] > 0
    assert np.isfinite(bc["bc_metrics"]["cross_entropy"])

    cem = D.refine_constrained_cem(
        init_params=bc["params"],
        tier="easy",
        iters=1,
        pop_size=2,
        batch_size=2,
        train_seed_base=110200,
        select_seeds=[110200, 110201],
        min_solver_acc=0.0,
        max_logs_acc=1.0,
        min_solver_ratio=0.0,
        seed=7,
        workers=1,
    )
    assert isinstance(cem["policy"], RLMole)
    assert len(cem["curve"]) == 1

    rf = D.refine_constrained_reinforce(
        init_params=bc["params"],
        tier="easy",
        iters=1,
        batch_size=2,
        train_seed_base=110200,
        select_seeds=[110200, 110201],
        min_solver_acc=0.0,
        max_logs_acc=1.0,
        min_solver_ratio=0.0,
        seed=7,
        workers=1,
    )
    assert isinstance(rf["policy"], RLMole)
    assert len(rf["curve"]) == 1

    committed_pol = D.coerce_mole_policy(POLICY_PATH)
    ep1 = run_episode(Env("easy", 210050, mole_strategy=committed_pol), SolverPolicy("easy"))
    ep2 = run_episode(Env("easy", 210050, mole_strategy=committed_pol), SolverPolicy("easy"))
    dn = run_episode(Env("easy", 210050, mole_strategy=committed_pol), DoNothing(seed=210050))
    assert ep1.score == ep2.score
    assert ep1.final_day == ep2.final_day
    assert ep1.correct is True
    assert dn.score == 0.0


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

    for path in (MODULE_PATH, TEST_PATH, POLICY_PATH, REPORT_PATH):
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em-dash found in {path}"
        assert EN_DASH not in text, f"en-dash found in {path}"
        assert UNICODE_MINUS not in text, f"unicode minus found in {path}"
        assert all(ord(ch) < 128 for ch in text), f"non-ASCII character found in {path}"
        assert COAUTHOR_TAG not in text.lower(), f"coauthor trailer found in {path}"
        assert FLASH_TAG not in text.lower(), f"forbidden flash claim in {path}"
        assert SOLVER_PCT_TAG not in text.lower(), f"forbidden solver pct claim in {path}"
        assert forbidden_gap_re.search(text) is None, f"forbidden gap ratio claim in {path}"
