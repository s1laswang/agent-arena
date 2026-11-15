from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.integrity_v14_v15_differential_sweep as diff_sweep


EXPECTED_STRATEGIES = (
    "do_nothing",
    "stop_early",
    "blind_seat_0",
    "accuse_most_talkative",
    "accuse_authority_role",
    "accuse_first_named_anchor",
    "accuse_lexical_hedging",
    "log_volume_outlier",
    "one_interview_accuse",
    "reference_solver",
)


@pytest.fixture(scope="module")
def v15_runtime():
    return diff_sweep.load_v15_runtime()


@pytest.fixture(scope="module")
def fast_audit_report():
    t0 = time.perf_counter()
    report = diff_sweep.run_differential_audit(
        tiers=["easy", "medium"],
        seeds=[0, 1],
        workers=1,
    )
    report["_fixture_wall_s"] = time.perf_counter() - t0
    return report


def test_isolated_git_show_v15_loader_and_v14_hash_preservation(v15_runtime) -> None:
    from canary import env as env_v14
    from canary import rules as rules_v14

    assert v15_runtime.commit_sha.startswith("de9cc50e")
    assert v15_runtime.pkg_name == "_canary_v15_isolated"
    assert v15_runtime.pkg_name in sys.modules
    assert f"{v15_runtime.pkg_name}.env" in sys.modules
    assert len(v15_runtime.finder.git_show_paths) >= 10
    assert "canary/env.py" in v15_runtime.finder.git_show_paths
    assert "canary/rules.py" in v15_runtime.finder.git_show_paths
    assert v15_runtime.status_unchanged is True

    assert env_v14.Env is not v15_runtime.env_mod.Env
    assert rules_v14.TIERS is not v15_runtime.rules.TIERS
    assert rules_v14.TIERS_VERSION == "v1.4"
    assert diff_sweep.compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE) == "a8f99c2537c91d72"

    e14 = env_v14.Env("medium", 0)
    e15 = v15_runtime.make_env("medium", 0, social_enabled=True)
    assert not hasattr(e14.p, "social")
    assert e15.p.social is True
    assert e15.p.rumour_rate == pytest.approx(2.0)
    assert e15.p.p_misforward == pytest.approx(0.15)
    assert "Office chatter and paperwork mistakes" in e15.instruction()
    assert "Office chatter and paperwork mistakes" not in e14.instruction()


def test_ten_strategies_fast_paired_sweep_invariants(fast_audit_report, v15_runtime) -> None:
    from canary.env import Env as EnvV14

    assert fast_audit_report["_fixture_wall_s"] < 5.0
    assert tuple(fast_audit_report["strategy_names"]) == EXPECTED_STRATEGIES
    assert fast_audit_report["llm_api_calls"] == 0
    assert fast_audit_report["v14_tier_hash_preserved"] is True
    assert fast_audit_report["working_tree_unchanged"] is True
    assert fast_audit_report["total_invariant_violations"] == 0
    assert fast_audit_report["total_strategy_episodes"] == 80

    for tier in ("easy", "medium"):
        tdata = fast_audit_report["strategy_sweep"]["tiers"][tier]
        strats = tdata["strategies"]
        assert set(strats) == set(EXPECTED_STRATEGIES)
        for sname in EXPECTED_STRATEGIES:
            assert strats[sname]["same_world_truth_rate"] == 1.0
            assert strats[sname]["v14"]["invariant_violations"] == 0
            assert strats[sname]["v15"]["invariant_violations"] == 0

        assert strats["do_nothing"]["v14"]["mean_score"] == 0.0
        assert strats["do_nothing"]["v15"]["mean_score"] == 0.0
        assert strats["do_nothing"]["v14"]["abstain_rate"] == 1.0
        assert strats["stop_early"]["v14"]["mean_score"] == 0.0
        assert strats["stop_early"]["v15"]["mean_score"] == 0.0
        assert strats["stop_early"]["v14"]["abstain_rate"] == 1.0
        assert strats["reference_solver"]["v14"]["mean_score"] > 0.4
        assert strats["reference_solver"]["v15"]["mean_score"] > 0.4

    se_ep_14 = diff_sweep.run_single_episode(EnvV14("easy", 0), diff_sweep.make_strategy("stop_early", 0, "v1.4"))
    se_ep_15 = diff_sweep.run_single_episode(
        v15_runtime.make_env("easy", 0, social_enabled=True),
        diff_sweep.make_strategy("stop_early", 0, "v1.5", v15_runtime),
    )
    assert se_ep_14["quit_early"] is True and se_ep_14["done"] is False and se_ep_14["score"] == 0.0
    assert se_ep_15["quit_early"] is True and se_ep_15["done"] is False and se_ep_15["score"] == 0.0


def test_lexical_hygiene_zero_knob_parity_and_interview_audit(fast_audit_report) -> None:
    lex = fast_audit_report["lexical_and_stream_audit"]
    iv = lex["interview_template_audit"]
    assert iv["evasive_templates_total"] == 16
    assert iv["cooperative_templates_total"] == 16
    assert iv["cooperative_hedge_false_positive_rate"] == 0.0
    assert iv["evasive_hedge_recall"] >= 0.80
    assert iv["evasive_contains_literal_evasive_word"] == 0
    assert iv["solver_v14_marks_template_evasive"] is False
    assert iv["solver_v15_marks_template_evasive"] is False

    for tier in ("easy", "medium"):
        tlex = lex["tiers"][tier]
        assert tlex["zero_knob_parity"]["all_exact"] is True
        assert tlex["zero_knob_parity"]["social_no_misforward_stream_identical"] is True
        assert tlex["secret_hygiene"]["clean"] is True
        assert tlex["secret_hygiene"]["mole_word_leaks"] == 0
        assert tlex["secret_hygiene"]["secret_token_leaks"] == 0
        assert tlex["secret_hygiene"]["social_messages_scanned"] > 0


def test_cli_fast_json_smoke(tmp_path: Path) -> None:
    out_file = tmp_path / "fast_diff.json"
    t0 = time.perf_counter()
    rc = diff_sweep.main(["--fast", "--seeds", "0", "--tiers", "easy", "--json-out", str(out_file)])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 5.0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["total_strategy_episodes"] == 20
    assert payload["v14_tier_hash_preserved"] is True
    assert payload["working_tree_unchanged"] is True


def test_exclusive_files_hygiene_and_report_completeness() -> None:
    script_path = REPO_ROOT / "scripts" / "integrity_v14_v15_differential_sweep.py"
    report_path = REPO_ROOT / "docs" / "reports" / "integrity_v14_v15_differential_sweep.md"
    test_path = Path(__file__).resolve()

    script_txt = script_path.read_text(encoding="utf-8")
    report_txt = report_path.read_text(encoding="utf-8")
    test_txt = test_path.read_text(encoding="utf-8")

    for forbidden_dash in ("\u2014", "\u2013"):
        assert forbidden_dash not in script_txt
        assert forbidden_dash not in report_txt
        assert forbidden_dash not in test_txt

    hash_char = chr(35)
    assert hash_char not in script_txt
    assert hash_char not in test_txt

    for sname in EXPECTED_STRATEGIES:
        assert sname in report_txt

    for required_tok in (
        "9225f2ad",
        "de9cc50e",
        "a8f99c2537c91d72",
        "_canary_v15_isolated",
        "6,000",
        "6,600",
        "ISS-DIFF-01",
        "ISS-DIFF-02",
        "ISS-DIFF-03",
        "ISS-DIFF-04",
        "ISS-DIFF-05",
    ):
        assert required_tok in report_txt
