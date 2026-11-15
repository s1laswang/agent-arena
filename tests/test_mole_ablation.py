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

from canary.forge.mutate import canonical, validate_strategy
from canary.mole import ablation as A
from canary.mole.dsl import MAX_RULES
from canary.mole.strategies import get_strategy

JSON_PATH = ROOT / "results" / "mole_strategies" / "lever_ablation_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_lever_ablation_v14.md"
MODULE_PATH = ROOT / "canary" / "mole" / "ablation.py"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


def _load_committed_report() -> dict:
    assert JSON_PATH.is_file()
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_ablation_arm_construction_and_dsl_invariants() -> None:
    names = A.list_ablation_arm_names()
    assert len(names) == 12
    assert names[0] == "default_v0"
    assert names[-1] == "frontier_synthesis_v14"

    canon_seen: set[str] = set()
    for name in names:
        spec = A.get_ablation_arm_spec(name)
        sj = spec.to_json()
        ok, errs = validate_strategy(sj)
        assert ok, f"{name} failed DSL validation: {errs}"
        assert len(sj["rules"]) <= MAX_RULES
        canon = canonical(sj)
        assert canon not in canon_seen, f"duplicate canonical strategy on {name}"
        canon_seen.add(canon)

    synth_arm = A.get_ablation_arm_spec("frontier_synthesis_v14").to_strategy().to_json()
    synth_reg = get_strategy("frontier_synthesis_v14").to_json()
    assert synth_arm == synth_reg

    peer_spec = A.get_ablation_arm_spec("only_peer_framing")
    assert peer_spec.active_levers == ("non_decoy_peer_framing",)
    decoy_spec = A.get_ablation_arm_spec("only_decoy_framing")
    assert decoy_spec.active_levers == ()
    assert decoy_spec.framing_mode == "decoy"

    strats = A.ablation_strategies(["default_v0", "frontier_synthesis_v14"])
    assert list(strats.keys()) == ["default_v0", "frontier_synthesis_v14"]

    with pytest.raises(ValueError, match="framing_mode"):
        A.build_ablation_arm_json("bad_frame", (), "bogus")
    with pytest.raises(ValueError, match="leak_levers"):
        A.build_ablation_arm_json("bad_lever", ("nonexistent_lever",), "none")
    with pytest.raises(KeyError, match="unknown ablation arm"):
        A.get_ablation_arm_spec("missing_arm")


@pytest.mark.parametrize(
    "bad_seeds",
    [
        "",
        [],
        [True],
        [-1],
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
        "6600,30042",
        "800000",
        "800001",
        "900000",
        "6600,6600",
    ],
)
def test_seed_hygiene_rejects_forbidden_seeds(bad_seeds) -> None:
    with pytest.raises(ValueError):
        A.normalize_ablation_seeds(bad_seeds, enforce_hygiene=True)


def test_seed_hygiene_accepts_fresh_disjoint_seeds() -> None:
    assert A.normalize_ablation_seeds("60-60") == [60]
    assert A.normalize_ablation_seeds("6600-6639") == list(range(6600, 6640))
    assert A.normalize_ablation_seeds([60, 29999, 30200, 799999]) == [60, 29999, 30200, 799999]


def test_paired_bootstrap_ci_determinism() -> None:
    c1 = A.paired_bootstrap_ci([0.2, 0.4, 0.6, 0.8], n_boot=256, seed=42, tag="t1")
    c2 = A.paired_bootstrap_ci([0.2, 0.4, 0.6, 0.8], n_boot=256, seed=42, tag="t1")
    assert c1 == c2
    assert c1["ci_low"] <= c1["mean"] <= c1["ci_high"]

    const_ci = A.paired_bootstrap_ci([0.5, 0.5, 0.5], n_boot=128, seed=42, tag="const")
    assert const_ci["mean"] == pytest.approx(0.5)
    assert const_ci["ci_low"] == pytest.approx(0.5)
    assert const_ci["ci_high"] == pytest.approx(0.5)


def test_committed_json_and_markdown_consistency(capsys) -> None:
    assert JSON_PATH.stat().st_size < 100_000

    ok, msg = A.check_ablation_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = A.main(["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    report = _load_committed_report()
    compact = A.dumps_ablation_json(report)
    assert len(compact.encode("utf-8")) < 100_000
    assert json.loads(compact) == report

    assert report["tier"] == "hard"
    assert report["n_seeds"] == 40
    assert report["seed_range"] == "6600-6639"
    assert report["seeds"] == list(range(6600, 6640))
    assert set(report["arms"].keys()) == set(A.list_ablation_arm_names())
    assert set(report["lever_contributions"].keys()) == set(A.LEVER_IDS)
    assert "peer_vs_decoy_in_synthesis" in report["framing_control_analysis"]

    for arm_name, arm in report["arms"].items():
        assert arm["gates"]["passed_all"] is True, arm_name
        assert float(arm["policies"]["solver"]["acc"]) >= 0.85
        assert float(arm["policies"]["logs_only"]["acc"]) <= 0.10
        assert float(arm["policies"]["do_nothing"]["score"]) == 0.0
        assert float(arm["policies"]["stop_early_quit"]["score"]) == 0.0


def test_check_ablation_artifacts_catches_tampering(tmp_path: Path) -> None:
    ok_missing, msg_missing = A.check_ablation_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    bad_md = tmp_path / "drifted.md"
    md_text = MD_PATH.read_text(encoding="utf-8")
    bad_md.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = A.check_ablation_artifacts(json_path=JSON_PATH, md_path=bad_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = A.check_ablation_artifacts(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash

    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    flash_md = tmp_path / "flash.md"
    flash_md.write_text(md_text + f"\n{flash_tag} at 40{solver_pct_tag}\n", encoding="utf-8")
    ok_flash, msg_flash = A.check_ablation_artifacts(json_path=JSON_PATH, md_path=flash_md)
    assert ok_flash is False
    assert flash_tag in msg_flash

    base = _load_committed_report()
    leaked = copy.deepcopy(base)
    leaked["arms"]["default_v0"]["true_mole"] = "e01"
    leaked_json = tmp_path / "leaked.json"
    leaked_json.write_text(json.dumps(leaked), encoding="utf-8")
    ok_leak, msg_leak = A.check_ablation_artifacts(json_path=leaked_json, md_path=MD_PATH)
    assert ok_leak is False
    assert "forbidden secret key" in msg_leak

    bad_seed = copy.deepcopy(base)
    bad_seed["seeds"][0] = 30000
    bad_seed_json = tmp_path / "bad_seed.json"
    bad_seed_json.write_text(json.dumps(bad_seed), encoding="utf-8")
    ok_seed, msg_seed = A.check_ablation_artifacts(json_path=bad_seed_json, md_path=MD_PATH)
    assert ok_seed is False
    assert "seed hygiene" in msg_seed


def test_tiny_two_seed_smoke_slice(tmp_path: Path) -> None:
    out_json = tmp_path / "smoke.json"
    out_md = tmp_path / "smoke.md"
    rc = A.main([
        "--tier", "hard",
        "--seeds", "6600,6602",
        "--cf-seeds", "0,1",
        "--cf-sources", "opencode",
        "--arms", "default_v0,frontier_synthesis_v14",
        "--n-boot", "64",
        "--out", str(out_json),
        "--report-md", str(out_md),
    ])
    assert rc == 0
    ok, msg = A.check_ablation_artifacts(json_path=out_json, md_path=out_md)
    assert ok is True, msg


def test_pr_review_hygiene_gates() -> None:
    coauthor_tag = "co-authored-" + "by"
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"

    for py_file in (MODULE_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment token in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"unexpected hash character in {py_file}"

    for p in (MODULE_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        text = p.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em-dash found in {p}"
        assert EN_DASH not in text, f"en-dash found in {p}"
        assert coauthor_tag not in text.lower(), f"coauthor trailer found in {p}"

    md_lower = MD_PATH.read_text(encoding="utf-8").lower()
    assert flash_tag not in md_lower
    assert solver_pct_tag not in md_lower
