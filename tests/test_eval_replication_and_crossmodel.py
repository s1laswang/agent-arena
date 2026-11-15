"""Offline unit and replay verification tests for scripts/eval_replication_and_crossmodel.py."""
from __future__ import annotations

import copy
from dataclasses import asdict
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import sys
import tokenize
from typing import Any

import pytest

from canary.env import Env
from canary.eval import make_policy_factory, run_episode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import paired_v13

SCRIPT_PATH = ROOT / "scripts/eval_replication_and_crossmodel.py"
TEST_PATH = ROOT / "tests/test_eval_replication_and_crossmodel.py"
JSON_PATH = ROOT / "results/eval_v14/crossmodel_and_replication_v14.json"
MD_PATH = ROOT / "docs/reports/crossmodel_and_replication_v14.md"
PAIRED_GEMINI_JSON = ROOT / "data/runs/committed/v1.4/paired_table_gemini.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("eval_replication_and_crossmodel", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


@pytest.fixture(scope="module")
def committed_payload() -> dict[str, Any]:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    assert JSON_PATH.stat().st_size < MOD.MAX_JSON_BYTES
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_committed_json_and_markdown_invariants_and_exact_headline_numbers(committed_payload: dict[str, Any]):
    assert committed_payload["tiers_version"] == "v1.4"
    assert committed_payload["bootstrap"] == {"n_boot": 10000, "seed": 0}
    assert MOD.render_markdown(committed_payload) == MD_PATH.read_text(encoding="utf-8")

    rule = committed_payload["data_rule"]
    assert rule["total_inspected_episodes"] == 875
    assert rule["total_valid_replayed_episodes"] == 875
    assert rule["rejected_episodes"] == []
    assert isinstance(rule["frontier_subpath_commit"], str) and len(rule["frontier_subpath_commit"]) == 40
    assert len(rule["committed_primary_over_3590s_clean_completions"]) == 6
    assert all(x["rc"] == 0 for x in rule["committed_primary_over_3590s_clean_completions"])

    prim = committed_payload["primary_0_29"]
    by_key = {(c["tier"], c["cohort"]): c for c in prim["cohorts"]}

    paired_ref_rows = json.loads(PAIRED_GEMINI_JSON.read_text(encoding="utf-8"))
    cohort_map = {
        "opencode:google/gemini-4-carbon": "opencode-gemini-4-carbon",
        "gemini:gemini-4-carbon": "inproc-gemini-4-carbon",
        "solver": "solver",
    }
    for ref in paired_ref_rows:
        if "alternative" in ref["label"]:
            continue
        mapped = cohort_map.get(ref["agent"])
        if mapped is None:
            continue
        got = by_key[(ref["tier"], mapped)]
        assert got["n"] == ref["n"] == 30
        assert math.isclose(got["mean_score"], ref["mean"], abs_tol=1e-9)
        assert math.isclose(got["luck_adjusted_score"], ref["post_expected"], abs_tol=1e-9)
        if mapped != "solver":
            assert math.isclose(got["ratio_vs_solver"], ref["ratio"], abs_tol=1e-9)
            assert math.isclose(got["ratio_ci95"][0], ref["ratio_lo"], abs_tol=1e-9)
            assert math.isclose(got["ratio_ci95"][1], ref["ratio_hi"], abs_tol=1e-9)
            assert math.isclose(got["luck_adjusted_ratio"], ref["post_expected_ratio"], abs_tol=1e-9)
            assert math.isclose(got["luck_adjusted_ratio_ci95"][0], ref["post_expected_lo"], abs_tol=1e-9)
            assert math.isclose(got["luck_adjusted_ratio_ci95"][1], ref["post_expected_hi"], abs_tol=1e-9)

    flash_hard = by_key[("hard", "opencode-gemini-3.5-flash")]
    assert flash_hard["n"] == 30
    assert round(flash_hard["mean_score"], 3) == 0.373
    assert round(flash_hard["ratio_vs_solver"] * 100) == 75
    assert [round(x * 100) for x in flash_hard["ratio_ci95"]] == [36, 123]
    assert round(flash_hard["luck_adjusted_score"], 3) == 0.110
    assert round(flash_hard["luck_adjusted_ratio"] * 100) == 22
    assert [round(x * 100) for x in flash_hard["luck_adjusted_ratio_ci95"]] == [-23, 63]
    assert flash_hard["sub_breakeven_gamble_count"] == 10
    assert flash_hard["sub_breakeven_lucky_hits"] == 7
    assert round(flash_hard["realized_luck"], 3) == 0.263

    flash_med = by_key[("medium", "opencode-gemini-3.5-flash")]
    assert flash_med["n"] == 30
    assert flash_med["seeds"] == list(range(30))
    assert round(flash_med["mean_score"], 3) == 0.434
    assert round(flash_med["ratio_vs_solver"] * 100) == 67
    assert [round(x * 100) for x in flash_med["ratio_ci95"]] == [29, 103]
    assert round(flash_med["luck_adjusted_score"], 3) == 0.485
    assert round(flash_med["luck_adjusted_ratio"] * 100) == 75
    assert [round(x * 100) for x in flash_med["luck_adjusted_ratio_ci95"]] == [45, 105]

    h2h_hard = prim["head_to_head"]["hard"]
    assert h2h_hard["n"] == 30
    assert round(h2h_hard["paired_luck_adjusted_diff"], 3) == 0.250
    assert h2h_hard["paired_luck_adjusted_diff_ci95"][0] > 0.0
    assert h2h_hard["accuracy_concordance"] == {
        "both_correct": 23,
        "a_only_correct": 2,
        "b_only_correct": 4,
        "neither_correct": 1,
    }
    assert h2h_hard["sub_breakeven_gamble_concordance"]["both_gamble"] == 2
    assert h2h_hard["sub_breakeven_gamble_concordance"]["b_only_gamble"] == 8

    h2h_med = prim["head_to_head"]["medium"]
    assert h2h_med["n"] == 30
    assert round(h2h_med["paired_raw_diff"], 3) == 0.279
    assert h2h_med["paired_raw_diff_ci95"][0] > 0.0

    rep = committed_payload["replication_30_59"]
    rep_c = rep["opencode_gemini_4_carbon_hard_replication"]
    assert rep_c["n"] == 5
    assert rep_c["seeds"] == [30, 34, 42, 45, 57]
    assert rep_c["sub_breakeven_gamble_count"] == 0

    pooled = rep["secondary_pooled_sensitivity_hard"]
    assert pooled["n"] == 35
    assert pooled["status"] == "secondary_sensitivity_only"
    assert pooled["luck_adjusted_ratio_ci95"][1] < 1.0

    ref_30_59 = {r["cohort"]: r for r in rep["reference_hard_30_59"]}
    assert set(ref_30_59.keys()) == set(MOD.REPLICATION_REF_ORDER)
    assert all(r["n"] == 30 and r["seeds"] == list(range(30, 60)) for r in ref_30_59.values())
    assert rep["post_pr16_zero_checks"]["stop_early_all_zero"] is True
    assert rep["post_pr16_zero_checks"]["do_nothing_all_zero"] is True


def test_check_mode_full_and_shallow_ci_fallback(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(MOD, "DETERMINISTIC_BASELINES_0_29", ("do_nothing",))
    cached_cohorts: list[dict[str, Any]] = []
    orig_load = MOD._load_committed_cohorts

    def _cached_load(committed_dir: Path, audit_log: dict[str, Any]):
        if not cached_cohorts:
            cached_cohorts.append(orig_load(committed_dir, audit_log))
        return cached_cohorts[0]

    monkeypatch.setattr(MOD, "_load_committed_cohorts", _cached_load)
    rc_shallow = MOD.main(["--check", "--frontier-ref", "refs/heads/nonexistent-shallow-ci-ref-000"])
    out_shallow = capsys.readouterr().out
    assert rc_shallow == 0
    assert "shallow CI mode" in out_shallow

    monkeypatch.setattr(MOD, "compute", lambda *a, **kw: copy.deepcopy(committed_payload))
    monkeypatch.setattr(MOD, "load_frontier_tree", lambda *a, **kw: {"stub": ""})
    monkeypatch.setattr(
        MOD,
        "git_subpath_commit",
        lambda *a, **kw: committed_payload["data_rule"]["frontier_subpath_commit"],
    )

    good_json = tmp_path / "good.json"
    good_md = tmp_path / "good.md"
    assert MOD.main(["--out-json", str(good_json), "--out-md", str(good_md)]) == 0
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(good_md)]) == 0

    jittered = json.loads(good_json.read_text(encoding="utf-8"))
    jittered["primary_0_29"]["cohorts"][0]["mean_score"] += 1e-12
    good_json.write_text(json.dumps(jittered), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(good_md)]) == 0

    tampered = json.loads(good_json.read_text(encoding="utf-8"))
    tampered["primary_0_29"]["cohorts"][0]["mean_score"] += 0.05
    bad_json = tmp_path / "bad.json"
    matching_bad_md = tmp_path / "matching_bad.md"
    bad_json.write_text(json.dumps(tampered), encoding="utf-8")
    matching_bad_md.write_text(MOD.render_markdown(tampered), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(bad_json), "--out-md", str(good_md)]) == 1
    assert MOD.check_shallow_ci(ROOT / MOD.DEFAULT_COMMITTED_DIR, bad_json, matching_bad_md) == 1

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(good_md.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(JSON_PATH), "--out-md", str(bad_md)]) == 1
    assert MOD.check_shallow_ci(ROOT / MOD.DEFAULT_COMMITTED_DIR, JSON_PATH, bad_md) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (MOD.MAX_JSON_BYTES + 10), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(oversized), "--out-md", str(good_md)]) == 1
    assert MOD.check_shallow_ci(ROOT / MOD.DEFAULT_COMMITTED_DIR, oversized, good_md) == 1

    assert MOD.main(["--check", "--out-json", str(tmp_path / "missing.json"), "--out-md", str(good_md)]) == 1
    assert MOD.check_shallow_ci(ROOT / MOD.DEFAULT_COMMITTED_DIR, tmp_path / "missing.json", good_md) == 1


def test_validate_and_replay_data_rule_and_tamper_rejection():
    solver_factory = make_policy_factory("solver")
    base_ep = asdict(run_episode(Env("hard", 0), solver_factory(0)))

    ok, reason, info = MOD.validate_and_replay_episode(base_ep, enforce_wall_cap=True)
    assert ok is True and reason is None and info is not None
    assert math.isclose(info["score"], float(base_ep["score"]), abs_tol=1e-9)

    ok_inv, r_inv, _ = MOD.validate_and_replay_episode({**base_ep, "valid": False})
    assert ok_inv is False and r_inv == "invalid_flag"

    ok_err, r_err, _ = MOD.validate_and_replay_episode({**base_ep, "end_reason": "timeout"})
    assert ok_err is False and r_err == "end_reason_timeout"

    ok_rc, r_rc, _ = MOD.validate_and_replay_episode({**base_ep, "rc": 2})
    assert ok_rc is False and r_rc == "rc_nonzero_2"

    ok_ver, r_ver, _ = MOD.validate_and_replay_episode({**base_ep, "tiers_version": "v1.3"})
    assert ok_ver is False and r_ver == "tiers_version_v1.3"

    ok_wall, r_wall, _ = MOD.validate_and_replay_episode({**base_ep, "wall_s": 3595.0}, enforce_wall_cap=True)
    assert ok_wall is False and r_wall == "wall_s_ge_3590"

    ok_prim, r_prim, info_prim = MOD.validate_and_replay_episode(
        {**base_ep, "wall_s": 3595.0, "rc": 0},
        enforce_wall_cap=False,
    )
    assert ok_prim is True and r_prim is None and info_prim is not None

    with pytest.raises(ValueError, match="Replay mismatch"):
        MOD.validate_and_replay_episode({**base_ep, "score": float(base_ep["score"]) + 0.25})


def test_synthetic_end_to_end_frontier_dir_and_bootstrap_edge_cases(tmp_path: Path, monkeypatch):
    assert MOD.paired_bootstrap_stats([], [])["ratio"] is None
    one = MOD.paired_bootstrap_stats([0.4], [0.8])
    assert math.isclose(one["ratio"], 0.5, abs_tol=1e-12)
    assert one["ratio_ci95"] == [0.5, 0.5]
    neg_denom = MOD.paired_bootstrap_stats([0.2, 0.3], [-1.0, 0.0], n_boot=200, seed=0)
    assert neg_denom["ratio"] is None and neg_denom["ratio_ci95"] is None

    f_vals = [0.6, 0.8, -1.0, 0.7, 0.5, 0.9]
    s_vals = [0.8, 0.8, 0.7, 0.8, 0.6, 0.9]
    got_boot = MOD.paired_bootstrap_stats(f_vals, s_vals, n_boot=1000, seed=0)
    exp_lo, exp_hi = paired_v13.boot_ratio(f_vals, s_vals, B=1000, rng_seed=0)
    assert math.isclose(got_boot["ratio_ci95"][0], exp_lo, abs_tol=1e-12)
    assert math.isclose(got_boot["ratio_ci95"][1], exp_hi, abs_tol=1e-12)

    monkeypatch.setattr(MOD, "DETERMINISTIC_BASELINES_0_29", ("do_nothing", "stop_early"))

    comm = tmp_path / "committed_v14"
    front = tmp_path / "frontier_v14"
    sol_fac = make_policy_factory("solver")
    heu_fac = make_policy_factory("heuristic")
    dn_fac = make_policy_factory("do_nothing")
    se_fac = make_policy_factory("stop_early")

    for tier in ("medium", "hard"):
        sol_eps = [asdict(run_episode(Env(tier, s), sol_fac(s))) for s in (0, 1)]
        c_eps = [
            {**asdict(run_episode(Env(tier, s), sol_fac(s))), "agent": "opencode:google/gemini-4-carbon"}
            for s in (0, 1)
        ]
        ip_eps = [
            {**asdict(run_episode(Env(tier, s), heu_fac(s))), "agent": "gemini:gemini-4-carbon"}
            for s in (0, 1)
        ]
        _write_jsonl(comm / f"reference/solver-{tier}-synth/episodes.jsonl", sol_eps)
        _write_jsonl(comm / f"opencode-gemini-4-carbon/{tier}/episodes.jsonl", c_eps)
        _write_jsonl(comm / f"inproc-gemini-4-carbon/{tier}/episodes.jsonl", ip_eps)

    fl_hard = [
        {**asdict(run_episode(Env("hard", s), heu_fac(s))), "agent": "opencode:google/gemini-3.5-flash"}
        for s in (0, 1)
    ]
    fl_med = [
        {**asdict(run_episode(Env("medium", s), heu_fac(s))), "agent": "opencode:google/gemini-3.5-flash"}
        for s in (0, 1)
    ]
    _write_jsonl(comm / "opencode-gemini-3.5-flash/hard/episodes.jsonl", fl_hard)
    _write_jsonl(front / "opencode-gemini-3.5-flash/medium-00-01/episodes.jsonl", fl_med)

    rep_c = [
        {**asdict(run_episode(Env("hard", 30), sol_fac(30))), "agent": "opencode:google/gemini-4-carbon"}
    ]
    rep_sol = [asdict(run_episode(Env("hard", 30), sol_fac(30)))]
    rep_dn = [asdict(run_episode(Env("hard", 30), dn_fac(30)))]
    rep_se = [asdict(run_episode(Env("hard", 30), se_fac(30)))]
    _write_jsonl(front / "opencode-gemini-4-carbon/hard-s30/episodes.jsonl", rep_c)
    _write_jsonl(front / "reference/solver-hard-seeds30to59/episodes.jsonl", rep_sol)
    _write_jsonl(front / "reference/do_nothing-hard-seeds30to59/episodes.jsonl", rep_dn)
    _write_jsonl(front / "reference/stop_early-hard-seeds30to59/episodes.jsonl", rep_se)

    def _fast_replay(agent: str, tier: str, seeds: list[int], audit_log: dict[str, Any]):
        fac = make_policy_factory(agent)
        eps = [asdict(run_episode(Env(tier, s), fac(s))) for s in [0, 1]]
        return MOD._collect_validated(eps, "inproc_deterministic_v1.4", agent, True, audit_log, tier)

    monkeypatch.setattr(MOD, "replay_deterministic_policy", _fast_replay)
    monkeypatch.setattr(MOD, "N_BOOT", 100)

    out_json = tmp_path / "out/crossmodel.json"
    out_md = tmp_path / "out/crossmodel.md"
    argv = [
        "--committed-dir", str(comm),
        "--frontier-dir", str(front),
        "--out-json", str(out_json),
        "--out-md", str(out_md),
    ]
    assert MOD.main(argv) == 0
    assert MOD.main(["--check", *argv]) == 0
    synth = json.loads(out_json.read_text(encoding="utf-8"))
    assert synth["replication_30_59"]["post_pr16_zero_checks"]["do_nothing_all_zero"] is True
    assert synth["replication_30_59"]["post_pr16_zero_checks"]["stop_early_all_zero"] is True


def test_strict_style_and_secret_hygiene():
    assert JSON_PATH.stat().st_size < MOD.MAX_JSON_BYTES
    assert MD_PATH.stat().st_size > 1000

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    mole_dump_rx = re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        raw = path.read_bytes()
        txt = raw.decode("ascii")
        assert "\u2013" not in txt and "\u2014" not in txt, f"found unicode dash in {path}"
        assert not mole_dump_rx.search(txt), f"found mole dump pattern in {path}"
