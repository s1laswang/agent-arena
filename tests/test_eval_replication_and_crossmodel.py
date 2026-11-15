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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from canary.env import Env
from canary.eval import make_policy_factory, run_episode
import paired_v13

SCRIPT_PATH = ROOT / "scripts/eval_replication_and_crossmodel.py"
TEST_PATH = ROOT / "tests/test_eval_replication_and_crossmodel.py"
JSON_PATH = ROOT / "results/eval_v14/crossmodel_and_replication_v14.json"
MD_PATH = ROOT / "docs/reports/crossmodel_and_replication_v14.md"
PAIRED_GEMINI_JSON = ROOT / "data/runs/committed/v1.4/paired_table_gemini.json"
PAIRED_EXT_JSON = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_ext30to59.json"
PAIRED_POOLED_JSON = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"


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
    assert JSON_PATH.stat().st_size <= 50000
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_committed_json_and_markdown_invariants_and_exact_headline_numbers(committed_payload: dict[str, Any]):
    assert committed_payload["schema_version"] == "v1.4.2"
    assert committed_payload["tiers_version"] == "v1.4"
    assert committed_payload["bootstrap"] == {"n_boot": 10000, "seed": 0}
    assert committed_payload["authoritative_headline_sources"] == [
        "docs/reports/gap.md",
        "data/runs/committed/v1.4/paired_table_gemini.md",
    ]
    md_text = MD_PATH.read_text(encoding="utf-8")
    assert MOD.render_markdown(committed_payload) == md_text

    assert "post-hoc locked in `671ed96` (28 s after `8fd4dec`), not pre-registered" in md_text
    assert "docs/reports/gap.md" in md_text and "paired_table_gemini.md" in md_text
    assert "Pre-Registered Headline Scope" not in md_text
    assert "Pre-registered primary" not in md_text
    assert "f9fb7a4a" in md_text and "cf394894" in md_text and "1.19.5" in md_text
    assert "solver-hard-seeds30to59" in md_text and "access_constraints" in md_text
    raw_idx = md_text.index("65% [24%, 98%]")
    luck_idx = md_text.index("72% [52%, 91%]")
    assert raw_idx < luck_idx

    rule = committed_payload["data_rule"]
    assert rule["working_tree_only"] is True
    assert rule["step_error_detail_compat"] == "1bc3e281"
    assert "1bc3e281" in rule["step_error_detail_rule"] and "data.detail" in rule["step_error_detail_rule"]
    assert "post-hoc lock" in rule["primary_seed_lock_rule"]
    assert "671ed96" in rule["primary_seed_lock_rule"] and "8fd4dec" in rule["primary_seed_lock_rule"]
    assert "not pre-registered" in rule["primary_seed_lock_rule"]
    assert "f9fb7a4a" in rule["primary_seed_lock_rule"] and "cf394894" in rule["primary_seed_lock_rule"]
    assert "20+10" in rule["solver_reference_layout_note"]
    assert "solver-hard-seeds30to59" in rule["solver_reference_layout_note"]
    assert "access_constraints never binds" in rule["hard_access_constraints_note"]
    assert rule["total_inspected_episodes"] == 872
    assert rule["total_valid_replayed_episodes"] == 872
    assert rule["total_steps_verified"] == 42885
    assert rule["total_steps_truncated_checked"] == 2
    assert rule["total_steps_client_only"] == 1
    assert rule["rejected_episodes"] == []
    assert len(rule["committed_primary_over_3590s_clean_completions"]) == 6
    assert all(x["rc"] == 0 for x in rule["committed_primary_over_3590s_clean_completions"])

    prim = committed_payload["primary_0_29"]
    assert "post-hoc locked in commit 671ed96 (28 s after 8fd4dec), not pre-registered" in prim["seed_lock_note"]
    sol_dirs = prim["solver_reference_dirs"]
    assert [d["n"] for d in sol_dirs["medium"]] == [20, 10]
    assert [d["n"] for d in sol_dirs["hard"]] == [20, 10]
    assert all(d["dir"] != "solver-hard-seeds30to59" for d in sol_dirs["hard"])

    gpt_pre = prim["gpt_5_5_preregistration"]
    assert gpt_pre["pre_registered_commit"] == "cf394894"
    assert gpt_pre["model"] == "gpt-5.5"
    assert gpt_pre["opencode_version"] == "1.19.5"
    assert gpt_pre["env_tag"] == "afterquery-final"
    assert gpt_pre["stop_time_helsinki"] == "08:15"
    assert gpt_pre["spend_cap_usd"] == 200
    assert gpt_pre["committed_dir"] == "data/runs/committed/v1.4/opencode-gpt-5.5"

    f_prov = prim["flash_medium_provenance"]
    assert f_prov["commit_brought"] == "d4bc4f3d"
    assert [(s["shard"], s["git_sha"], s["n"]) for s in f_prov["shards"]] == [
        ("medium-00-14", "c01f371a", 15),
        ("medium-15-29", "55d9781c", 14),
        ("medium-s28", "a5d12c7e", 1),
    ]
    assert f_prov["shards"][1]["status"] == "INCOMPLETE: seed [28] pending rerun"
    assert "medium-s28" in md_text and "INCOMPLETE: seed [28] pending rerun" in md_text

    by_key = {(c["tier"], c["cohort"]): c for c in prim["cohorts"]}
    assert by_key[("medium", "solver")]["seeds"] == list(range(30))
    assert by_key[("hard", "solver")]["seeds"] == list(range(30))

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
    assert rep["solver_reference_dir"] == "data/runs/committed/v1.4/reference/solver-hard-seeds30to59"
    g1_prov = rep["g1_extension_provenance"]
    assert g1_prov["pre_registered_commit"] == "f9fb7a4a"
    assert g1_prov["completed_valid_seeds"] == [34, 37]
    assert g1_prov["infra_invalid_attempts_excluded_count"] == 31
    assert g1_prov["infra_provider_quota_attempts_count"] == 31

    ext_c = rep["opencode_gemini_4_carbon_hard_extension"]
    assert ext_c["n"] == 2
    assert ext_c["seeds"] == [34, 37]
    assert ext_c["sub_breakeven_gamble_count"] == 0
    assert [round(r["score"], 3) for r in rep["opencode_gemini_4_carbon_hard_per_seed"]] == [0.790, 0.700]

    ext_ref = json.loads(PAIRED_EXT_JSON.read_text(encoding="utf-8"))[0]
    MOD._verify_paired_table_row(ext_c, ext_ref, "test_ext")
    assert round(ext_c["ratio_vs_solver"] * 100) == 101
    assert [round(x * 100) for x in ext_c["ratio_ci95"]] == [91, 113]
    assert round(ext_c["luck_adjusted_ratio"] * 100) == 109
    assert [round(x * 100) for x in ext_c["luck_adjusted_ratio_ci95"]] == [105, 114]

    pooled = rep["secondary_pooled_sensitivity_hard"]
    assert pooled["n"] == 32
    assert pooled["seeds"] == [*range(30), 34, 37]
    assert pooled["status"] == "secondary_sensitivity_only"
    pooled_ref = next(
        r
        for r in json.loads(PAIRED_POOLED_JSON.read_text(encoding="utf-8"))
        if r.get("tier") == "hard" and "pooled" in r.get("label", "")
    )
    MOD._verify_paired_table_row(pooled, pooled_ref, "test_pooled")
    assert round(pooled["mean_score"], 3) == 0.349
    assert round(pooled["score_ci95"], 3) == 0.190
    assert round(pooled["solver_mean"], 3) == 0.514
    assert round(pooled["paired_diff"], 3) == -0.165
    assert round(pooled["paired_diff_halfwidth95"], 3) == 0.182
    assert round(pooled["ratio_vs_solver"] * 100) == 68
    assert [round(x * 100) for x in pooled["ratio_ci95"]] == [32, 100]
    assert round(pooled["luck_adjusted_ratio"] * 100) == 75
    assert [round(x * 100) for x in pooled["luck_adjusted_ratio_ci95"]] == [56, 93]

    assert rep["paired_table_crosscheck"] == {
        "checked": True,
        "ext30to59_match": True,
        "pooled0to59_match": True,
        "solver30to59_match": True,
    }

    ref_30_59 = {r["cohort"]: r for r in rep["reference_hard_30_59"]}
    assert set(ref_30_59.keys()) == set(MOD.REPLICATION_REF_ORDER)
    assert ref_30_59["solver"]["source"] == "committed_v1.4"
    assert round(ref_30_59["solver"]["mean_score"], 3) == 0.498
    assert round(ref_30_59["solver"]["score_ci95"], 3) == 0.156
    assert all(r["n"] == 30 and r["seeds"] == list(range(30, 60)) for r in ref_30_59.values())
    assert rep["post_pr16_zero_checks"]["stop_early_all_zero"] is True
    assert rep["post_pr16_zero_checks"]["do_nothing_all_zero"] is True


def test_check_mode_full_and_shallow_ci_fallback(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    rc_shallow = MOD.main(["--check", "--frontier-ref", "refs/heads/nonexistent-shallow-ci-ref-000"])
    out_shallow = capsys.readouterr().out
    assert rc_shallow == 0
    assert "working-tree Part A + Part B + MD verified" in out_shallow

    monkeypatch.setattr(MOD, "compute", lambda *a, **kw: copy.deepcopy(committed_payload))
    assert MOD.main(["--check"]) == 0
    assert MOD.main(["--check", "--frontier-ref", "origin/fr8/canary/frontier"]) == 0

    good_json = tmp_path / "good.json"
    good_md = tmp_path / "good.md"
    assert MOD.main(["--out-json", str(good_json), "--out-md", str(good_md)]) == 0
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(good_md)]) == 0
    assert (
        MOD.main([
            "--check",
            "--frontier-ref",
            "refs/heads/nonexistent-shallow-ci-ref-000",
            "--out-json",
            str(good_json),
            "--out-md",
            str(good_md),
        ])
        == 0
    )

    jittered = json.loads(good_json.read_text(encoding="utf-8"))
    jittered["primary_0_29"]["cohorts"][0]["mean_score"] += 1e-12
    good_json.write_text(json.dumps(jittered), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(good_md)]) == 0

    tampered = json.loads(good_json.read_text(encoding="utf-8"))
    tampered["primary_0_29"]["cohorts"][0]["mean_score"] += 0.05
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(bad_json), "--out-md", str(good_md)]) == 1

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(good_md.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(JSON_PATH), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (MOD.MAX_JSON_BYTES + 10), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(oversized), "--out-md", str(good_md)]) == 1

    assert MOD.main(["--check", "--out-json", str(tmp_path / "missing.json"), "--out-md", str(good_md)]) == 1

    bad_ext_ref = json.loads(PAIRED_EXT_JSON.read_text(encoding="utf-8"))[0]
    bad_ext_ref["mean"] += 0.1
    with pytest.raises(ValueError, match="Paired table cross-check mismatch"):
        MOD._verify_paired_table_row(
            committed_payload["replication_30_59"]["opencode_gemini_4_carbon_hard_extension"],
            bad_ext_ref,
            "tampered_ext",
        )


def test_validate_and_replay_data_rule_and_1bc3e281_step_detail_compat():
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

    env_err = Env("hard", 3)
    bad_call = env_err.call("interview", {"employee": "e01", "topic": "leaks"})
    assert bad_call.ok is False and bad_call.error == "invalid arguments"
    assert isinstance(bad_call.data, dict) and set(bad_call.data) == {"detail"}
    while not env_err.done:
        env_err.call("advance_day", {})
    ep_post_1bc = asdict(env_err.result("test_agent"))

    ok_post, _, _ = MOD.validate_and_replay_episode(ep_post_1bc)
    assert ok_post is True

    ep_pre_1bc = copy.deepcopy(ep_post_1bc)
    ep_pre_1bc["steps"][0]["result"] = {"ok": False, "data": {}, "error": "invalid arguments"}
    ok_pre, _, _ = MOD.validate_and_replay_episode(ep_pre_1bc)
    assert ok_pre is True

    ep_pre_mcp_wrapped = copy.deepcopy(ep_post_1bc)
    ep_pre_mcp_wrapped["steps"][0]["result"] = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {}, "error": "invalid arguments"}),
    }
    ok_pre_wrap, _, _ = MOD.validate_and_replay_episode(ep_pre_mcp_wrapped)
    assert ok_pre_wrap is True

    ep_post_mcp_wrapped = copy.deepcopy(ep_post_1bc)
    ep_post_mcp_wrapped["steps"][0]["result"] = {
        "ok": False,
        "error": json.dumps(ep_post_1bc["steps"][0]["result"]),
    }
    ok_post_wrap, _, _ = MOD.validate_and_replay_episode(ep_post_mcp_wrapped)
    assert ok_post_wrap is True

    ep_bad_detail = copy.deepcopy(ep_post_1bc)
    ep_bad_detail["steps"][0]["result"] = {
        "ok": False,
        "data": {"detail": "forged_wrong_detail"},
        "error": "invalid arguments",
    }
    with pytest.raises(ValueError, match="Step replay mismatch"):
        MOD.validate_and_replay_episode(ep_bad_detail)

    ep_bad_wrap = copy.deepcopy(ep_post_1bc)
    ep_bad_wrap["steps"][0]["result"] = {
        "ok": False,
        "error": json.dumps({
            "ok": False,
            "data": {"detail": "forged_wrong_detail"},
            "error": "invalid arguments",
        }),
    }
    with pytest.raises(ValueError, match="Step replay mismatch"):
        MOD.validate_and_replay_episode(ep_bad_wrap)


def test_synthetic_end_to_end_working_tree_and_optional_gpt55(tmp_path: Path, monkeypatch):
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
    monkeypatch.setattr(MOD, "REPLICATION_REF_ORDER", ("solver", "do_nothing", "stop_early"))
    monkeypatch.setattr(MOD, "PRIMARY_SEEDS", (0, 1))
    monkeypatch.setattr(MOD, "EXTENSION_SEEDS", (34,))
    monkeypatch.setattr(MOD, "N_BOOT", 100)

    comm = tmp_path / "committed_v14"
    front = tmp_path / "frontier_v14"
    sol_fac = make_policy_factory("solver")
    heu_fac = make_policy_factory("heuristic")

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
    gpt55_hard = [
        {**asdict(run_episode(Env("hard", s), sol_fac(s))), "agent": "opencode:openai/gpt-5.5"}
        for s in (0, 1)
    ]
    _write_jsonl(comm / "opencode-gemini-3.5-flash/hard/episodes.jsonl", fl_hard)
    _write_jsonl(comm / "opencode-gpt-5.5/hard/episodes.jsonl", gpt55_hard)
    _write_jsonl(front / "opencode-gemini-3.5-flash/medium-00-01/episodes.jsonl", fl_med)
    (front / "opencode-gemini-3.5-flash/medium-00-01/meta.json").write_text(
        json.dumps({"git_sha": "c01f371a8b54b9a0", "status": None}),
        encoding="utf-8",
    )

    ext_c = [
        {**asdict(run_episode(Env("hard", 34), sol_fac(34))), "agent": "opencode:google/gemini-4-carbon"}
    ]
    rep_sol = [asdict(run_episode(Env("hard", 34), sol_fac(34)))]
    _write_jsonl(comm / "opencode-gemini-4-carbon-ext/hard/episodes.jsonl", ext_c)
    (comm / "opencode-gemini-4-carbon-ext/hard/meta.json").write_text(
        json.dumps({
            "git_sha": "f9fb7a4adc014efd",
            "planned_seeds": [34],
            "infra_invalid_attempts_excluded": ["opencode-hard-35: invalid: infra:provider_quota"],
        }),
        encoding="utf-8",
    )
    _write_jsonl(comm / "reference/solver-hard-seeds30to59/episodes.jsonl", rep_sol)

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
    assert MOD.main(["--check", "--frontier-ref", "refs/heads/nonexistent-ref", *argv]) == 0
    synth = json.loads(out_json.read_text(encoding="utf-8"))
    assert "hard_carbon_vs_gpt55" in synth["primary_0_29"]["head_to_head"]
    assert synth["primary_0_29"]["gpt_5_5_preregistration"]["committed_present"] is True
    assert synth["primary_0_29"]["gpt_5_5_preregistration"]["completed_n_by_tier"] == {"hard": 2}
    assert [d["dir"] for d in synth["primary_0_29"]["solver_reference_dirs"]["hard"]] == ["solver-hard-synth"]
    synth_ref_sol = next(
        r for r in synth["replication_30_59"]["reference_hard_30_59"] if r["cohort"] == "solver"
    )
    assert synth_ref_sol["source"] == "committed_v1.4"
    assert synth_ref_sol["seeds"] == [34]
    assert synth["replication_30_59"]["post_pr16_zero_checks"]["do_nothing_all_zero"] is True
    assert synth["replication_30_59"]["post_pr16_zero_checks"]["stop_early_all_zero"] is True


def test_strict_style_and_secret_hygiene():
    assert JSON_PATH.stat().st_size < MOD.MAX_JSON_BYTES
    assert JSON_PATH.stat().st_size <= 50000
    assert MD_PATH.stat().st_size > 1000

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    mole_dump_rx = re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')
    secret_rx = re.compile(r"(?:AIza[0-9A-Za-z_\-]{20,}|\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b)")
    coauthor_marker = "Co-Authored-" + "By"
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        raw = path.read_bytes()
        txt = raw.decode("ascii")
        assert "\u2013" not in txt and "\u2014" not in txt, f"found unicode dash in {path}"
        assert coauthor_marker not in txt, f"found coauthor marker in {path}"
        assert not mole_dump_rx.search(txt), f"found mole dump pattern in {path}"
        assert not secret_rx.search(txt), f"found secret pattern in {path}"
