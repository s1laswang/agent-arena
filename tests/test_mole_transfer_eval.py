from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole import transfer_eval as T

SCRIPT_PATH = ROOT / "canary" / "mole" / "transfer_eval.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "cross_model_transfer.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_cross_model_transfer.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


def _collect_keys(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, out)


def test_committed_artifacts_size_schema_and_report_parity(capsys: pytest.CaptureFixture[str]) -> None:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    raw_json = JSON_PATH.read_text(encoding="utf-8")
    assert JSON_PATH.stat().st_size < 115 * 1024

    ok, msg = T.check_transfer_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = T.main(["--check", "--out", str(JSON_PATH), "--report-out", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    payload = json.loads(raw_json)
    assert payload["schema_version"] == "1.0"
    assert payload["api_calls"] == 0
    assert payload["n_bootstrap_samples"] == 1000
    assert T.format_compact_json(payload) + "\n" == raw_json

    md_text = MD_PATH.read_text(encoding="utf-8")
    assert T.render_transfer_report(payload) == md_text

    cat = payload["catalog"]
    assert len(cat) == 11
    assert len({row["behavior_hash"] for row in cat.values()}) == 9
    assert cat["hof_v14_r3"]["alias_of"] == "surgical_trap_shield"
    assert cat["hof_v14_r4"]["alias_of"] == "early_burst_midgame_pace"

    cf = payload["counterfactual"]
    assert cf["total_episodes"] == 99
    assert cf["transcript_verified_total"] == 99
    assert cf["baseline_audit_match_total"] == 99
    assert cf["strategies"]["default"]["worst_family_ev_drop"] == 0.0

    fm = payload["fresh_seed_transfer"]
    assert fm["tiers_version"] == "v1.4"
    assert fm["tier"] == "hard"
    assert fm["n_seeds"] == 30
    assert fm["seeds"] == list(range(6200, 6230))
    assert fm["all_gates_passed"] is True
    for row in fm["strategies"].values():
        assert row["gates_passed"] is True
        assert float(row["solver_acc"]) >= 0.85
        assert float(row["logs_only_acc"]) <= 0.10

    all_keys: set[str] = set()
    _collect_keys(payload, all_keys)
    for forbidden in ("true_mole", "mole_id", "secret_mole"):
        assert forbidden not in all_keys


def test_check_transfer_artifacts_catches_tampering(tmp_path: Path) -> None:
    ok_missing, msg_missing = T.check_transfer_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    md_text = MD_PATH.read_text(encoding="utf-8")
    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = T.check_transfer_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = T.check_transfer_artifacts(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash

    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    flash_md = tmp_path / "flash.md"
    flash_md.write_text(md_text + f"\n{flash_tag} at 40{solver_pct_tag}\n", encoding="utf-8")
    ok_flash, msg_flash = T.check_transfer_artifacts(json_path=JSON_PATH, md_path=flash_md)
    assert ok_flash is False
    assert flash_tag in msg_flash

    base = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    leaked = copy.deepcopy(base)
    leaked["catalog"]["default"]["true_mole"] = "e01"
    leaked_json = tmp_path / "leaked.json"
    leaked_json.write_text(T.format_compact_json(leaked) + "\n", encoding="utf-8")
    ok_leak, msg_leak = T.check_transfer_artifacts(json_path=leaked_json, md_path=MD_PATH)
    assert ok_leak is False
    assert "forbidden secret key" in msg_leak

    bad_seed = copy.deepcopy(base)
    bad_seed["fresh_seed_transfer"]["seeds"][0] = 30000
    bad_seed_json = tmp_path / "bad_seed.json"
    bad_seed_json.write_text(T.format_compact_json(bad_seed) + "\n", encoding="utf-8")
    ok_seed, msg_seed = T.check_transfer_artifacts(json_path=bad_seed_json, md_path=MD_PATH)
    assert ok_seed is False
    assert "seed hygiene" in msg_seed


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "-1",
        "0",
        "29",
        "59",
        "0-59",
        "55-62",
        "30000",
        "30199",
        "30000-30199",
        "6200,30050",
        "800000",
        "800500",
        "6200,6200",
        "6205-6201",
        "6205:6205",
    ],
)
def test_seed_hygiene_rejects_invalid_and_forbidden_seeds(bad_spec: str) -> None:
    with pytest.raises(ValueError):
        T.validate_transfer_seeds(T.parse_seed_spec(bad_spec))


def test_seed_hygiene_accepts_clean_fresh_specs() -> None:
    assert T.parse_seed_spec(3) == [6200, 6201, 6202]
    assert T.validate_transfer_seeds(T.parse_seed_spec("60")) == [60]
    assert T.validate_transfer_seeds(T.parse_seed_spec("6200:6204")) == [6200, 6201, 6202, 6203]
    assert T.validate_transfer_seeds(T.parse_seed_spec("29999,30200,799999")) == [29999, 30200, 799999]
    with pytest.raises(ValueError):
        T.parse_seed_spec(True)
    with pytest.raises(ValueError):
        T.validate_transfer_seeds([])


def test_catalog_dedup_and_committed_path_filters() -> None:
    cat = T.load_transfer_catalog(
        selected_names=["default_v0", "surgical_trap_shield", "hof_v14_r3"]
    )
    assert list(cat.keys()) == ["default", "surgical_trap_shield", "hof_v14_r3"]
    assert cat["hof_v14_r3"].alias_of == "surgical_trap_shield"
    assert cat["hof_v14_r3"].behavior_hash == cat["surgical_trap_shield"].behavior_hash

    with pytest.raises(KeyError):
        T.load_transfer_catalog(selected_names=["nonexistent_strategy"])

    assert T.is_excluded_committed_path(("superseded", "hard", "episodes.jsonl")) is True
    assert T.is_excluded_committed_path(("opencode-gemini-4-carbon-smoke", "hard", "episodes.jsonl")) is True
    assert T.is_excluded_committed_path(("opencode-gemini-4-carbon-ext", "hard", "episodes.jsonl")) is True
    assert T.is_excluded_committed_path(("opencode-gemini-4-carbon", "hard", "episodes.jsonl")) is False
    discovered = T.discover_primary_frontier_episode_files()
    assert len(discovered) >= 6


def test_fresh_investigators_and_mini_cli_end_to_end(tmp_path: Path) -> None:
    ci1 = T.paired_bootstrap_ci([0.5, 0.7, 0.9], [0.2, 0.3, 0.4], n_boot=32, seed_tag="u1")
    ci2 = T.paired_bootstrap_ci([0.5, 0.7, 0.9], [0.2, 0.3, 0.4], n_boot=32, seed_tag="u1")
    assert ci1 == ci2
    assert ci1["ci95_lo"] <= ci1["mean"] <= ci1["ci95_hi"]

    mci = T.paired_minimax_gain_bootstrap_ci(
        {"a": [0.4, 0.6, 0.8], "b": [0.5, 0.5, 0.5]},
        {"a": [0.1, 0.2, 0.3], "b": [0.2, 0.2, 0.2]},
        ["a", "b"],
        n_boot=32,
        seed_tag="m1",
    )
    assert mci["mean"] == pytest.approx(0.3)

    for inv in T.TRANSFER_INVESTIGATORS:
        p1 = T._make_investigator(inv, tier="hard", seed=6201)
        p2 = T._make_investigator(inv, tier="hard", seed=6201)
        assert p1 is not p2

    out_json = tmp_path / "mini_transfer.json"
    out_md = tmp_path / "mini_transfer.md"
    rc = T.main(
        [
            "--fresh-seeds",
            "6200",
            "--cohorts",
            "v14_gemini_opencode_hard,v13_codex_hard",
            "--cf-seeds",
            "0",
            "--strategies",
            "default,surgical_trap_shield",
            "--workers",
            "1",
            "--n-boot",
            "16",
            "--min-solver-acc",
            "0.0",
            "--min-solver-ratio",
            "0.0",
            "--out",
            str(out_json),
            "--report-out",
            str(out_md),
        ]
    )
    assert rc == 0
    ok_mini, msg_mini = T.check_transfer_artifacts(json_path=out_json, md_path=out_md)
    assert ok_mini is True, msg_mini
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["api_calls"] == 0
    assert payload["counterfactual"]["total_episodes"] == 2
    assert payload["counterfactual"]["transcript_verified_total"] == 2
    assert payload["counterfactual"]["baseline_audit_match_total"] == 2
    assert payload["fresh_seed_transfer"]["n_seeds"] == 1
    assert payload["synthesis"]["rankings_unique_non_default"]["by_fresh_panel_min_regret"] == [
        "surgical_trap_shield"
    ]
    assert T.render_transfer_report(payload) == out_md.read_text(encoding="utf-8")


def test_pr_hygiene_zero_comments_dashes_and_forbidden_gap_claims() -> None:
    coauthor_tag = "co-authored-" + "by"
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"

    for py_file in (SCRIPT_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment token found in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"hash character found in {py_file}"

    for p in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = p.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em-dash in {p}"
        assert EN_DASH not in txt, f"en-dash in {p}"
        assert coauthor_tag not in txt.lower(), f"coauthor trailer in {p}"

    for p in (JSON_PATH, MD_PATH):
        low = p.read_text(encoding="utf-8").lower()
        assert flash_tag not in low
        assert solver_pct_tag not in low
