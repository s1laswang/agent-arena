from __future__ import annotations

import copy
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole.strategies import list_strategy_names
from scripts import eval_mole_strategies_v14 as E

JSON_PATH = ROOT / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_strategies_v14.md"
SCRIPT_PATH = ROOT / "scripts" / "eval_mole_strategies_v14.py"
TEST_PATH = Path(__file__).resolve()


def _load_payload() -> dict:
    assert JSON_PATH.is_file()
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_committed_json_and_markdown_report_check_passes(capsys) -> None:
    ok, msg = E.check_report_matches_json(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = E.main(["--check", "--json-out", str(JSON_PATH), "--md-out", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out


def test_check_rejects_missing_or_tampered_artifacts(tmp_path: Path) -> None:
    ok_missing, msg_missing = E.check_report_matches_json(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    bad_md = tmp_path / "drifted.md"
    md_text = MD_PATH.read_text(encoding="utf-8")
    bad_md.write_text(md_text + "\ndrifted trailing line\n", encoding="utf-8")
    ok_drift, msg_drift = E.check_report_matches_json(json_path=JSON_PATH, md_path=bad_md)
    assert ok_drift is False
    assert "do not match embedded ledger" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + "\u2014\n", encoding="utf-8")
    ok_dash, msg_dash = E.check_report_matches_json(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "-1",
        "0",
        "29",
        "30",
        "59",
        "0-59",
        "58-62",
        "30000",
        "30100",
        "30199",
        "30000-30199",
        "6000,30042",
        "800000",
        "800001",
        "900000",
        "800000-800010",
        "6000,6000",
    ],
)
def test_seed_hygiene_rejects_forbidden_ranges(bad_spec: str) -> None:
    with pytest.raises(ValueError):
        E.validate_eval_seeds(bad_spec)


def test_seed_hygiene_accepts_disjoint_fresh_ranges() -> None:
    assert E.validate_eval_seeds("60") == [60]
    assert E.validate_eval_seeds("29999,30200,799999") == [29999, 30200, 799999]
    fresh = E.validate_eval_seeds("6000-6199")
    assert fresh == list(range(6000, 6200))
    assert len(fresh) == 200


def test_committed_schema_and_fairness_invariants() -> None:
    payload = _load_payload()
    E.assert_payload_hygiene_and_invariants(payload)

    assert payload["schema_version"] == "mole_strategies_v14_eval.v1"
    assert payload["tier"] == "hard"
    assert payload["tiers_version"] == "v1.4"
    assert payload["n_seeds"] == 200
    assert payload["seed_range"] == "6000-6199"
    assert payload["seeds"] == list(range(6000, 6200))

    gates = payload["gates"]
    assert gates["all_passed"] is True
    assert gates["seed_hygiene_passed"] is True
    assert gates["all_solver_acc_ge_085"] is True
    assert gates["all_logs_only_le_010"] is True
    assert gates["all_zero_baselines_exact"] is True
    assert gates["unique_behavior_hashes"] is True

    expected_six = list_strategy_names(include_default=False)
    assert len(expected_six) == 6
    assert payload["transcript_strategy_order"] == expected_six
    assert payload["strategy_order"] == ["default_v0", *expected_six]

    bhashes: list[str] = []
    for name in expected_six:
        row = payload["strategies"][name]
        assert row["passed"] is True
        assert float(row["solver"]["accuracy"]) >= 0.85
        assert row["solver"]["passed"] is True
        assert float(row["baselines"]["logs_only"]["accuracy"]) <= 0.10
        assert float(row["baselines"]["accuse_most_logs"]["accuracy"]) <= 0.10
        assert float(row["baselines"]["do_nothing"]["score"]) == 0.0
        assert float(row["baselines"]["stop_early_quit"]["score"]) == 0.0
        bhashes.append(str(row["behavior_hash"]))

    bhashes.append(str(payload["strategies"]["default_v0"]["behavior_hash"]))
    assert len(set(bhashes)) == 7


def test_invariant_validator_catches_gate_and_leak_violations() -> None:
    base = _load_payload()
    strat_name = base["transcript_strategy_order"][0]

    low_solver = copy.deepcopy(base)
    low_solver["strategies"][strat_name]["solver"]["accuracy"] = 0.84
    with pytest.raises(ValueError, match="solver accuracy"):
        E.assert_payload_hygiene_and_invariants(low_solver)

    high_logs = copy.deepcopy(base)
    high_logs["strategies"][strat_name]["baselines"]["logs_only"]["accuracy"] = 0.11
    with pytest.raises(ValueError, match="logs_only accuracy"):
        E.assert_payload_hygiene_and_invariants(high_logs)

    leaked_key = copy.deepcopy(base)
    leaked_key["strategies"][strat_name]["true_mole"] = "e01"
    with pytest.raises(ValueError, match="forbidden key"):
        E.assert_payload_hygiene_and_invariants(leaked_key)

    bad_seeds = copy.deepcopy(base)
    bad_seeds["seeds"][0] = 30000
    with pytest.raises(ValueError, match="seed hygiene"):
        E.assert_payload_hygiene_and_invariants(bad_seeds)


def test_zero_comments_and_zero_em_en_dashes() -> None:
    for py_file in (SCRIPT_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment token in {py_file}"

    for p in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        text = p.read_text(encoding="utf-8")
        assert "\u2014" not in text, f"em-dash found in {p}"
        assert "\u2013" not in text, f"en-dash found in {p}"
