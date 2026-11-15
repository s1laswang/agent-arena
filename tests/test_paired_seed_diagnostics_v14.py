"""Offline unit, mathematical identity, and replay tests for scripts/paired_seed_diagnostics_v14.py."""
from __future__ import annotations

import copy
from dataclasses import asdict
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env

SCRIPT_PATH = ROOT / "scripts" / "paired_seed_diagnostics_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results" / "eval_v14" / "paired_seed_diagnostics_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "paired_seed_diagnostics_v14.md"
PAIRED_GEMINI_JSON = ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


def _load_module():
    spec = importlib.util.spec_from_file_location("paired_seed_diagnostics_v14", SCRIPT_PATH)
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


def test_source_artifacts_and_protected_path_hygiene(committed_payload: dict[str, Any]) -> None:
    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert HASH_CHAR not in src, f"found hash char in {py_path}"

    coauthor_marker = "Co-Authored-" + "By"
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        raw = path.read_bytes()
        txt = raw.decode("ascii")
        assert EN_DASH not in txt and EM_DASH not in txt
        assert coauthor_marker not in txt

    assert MOD._scan_forbidden_keys(committed_payload) == []
    assert MOD.scan_text_hygiene("committed_json", JSON_PATH.read_text(encoding="utf-8")) == []
    assert MOD.scan_text_hygiene("committed_md", MD_PATH.read_text(encoding="utf-8")) == []

    owned_rel_paths = (
        "scripts/paired_seed_diagnostics_v14.py",
        "results/eval_v14/paired_seed_diagnostics_v14.json",
        "docs/reports/paired_seed_diagnostics_v14.md",
        "tests/test_paired_seed_diagnostics_v14.py",
    )
    lead_owned = {
        "scripts/run_all_eval_checks.py",
        "results/eval_v14/eval_suite_index.json",
        "docs/reports/eval_suite_overview.md",
    }
    protected_prefixes: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        protected_prefixes.append(line)

    for rel_path in owned_rel_paths:
        assert rel_path not in lead_owned
        for prefix in protected_prefixes:
            if prefix.endswith("/"):
                assert not rel_path.startswith(prefix)
            else:
                assert rel_path != prefix


def test_committed_json_and_markdown_headline_and_harbor_sync(committed_payload: dict[str, Any]) -> None:
    assert committed_payload["schema_version"] == "paired_seed_diagnostics_v14.v1"
    assert committed_payload["tiers_version"] == "v1.4"
    assert committed_payload["primary_seeds"] == "0-29"
    assert committed_payload["n_primary_seeds_per_tier"] == 30

    md_text = MD_PATH.read_text(encoding="utf-8")
    assert MOD.render_markdown(committed_payload) == md_text
    assert "aa1c679e" in md_text and "5f9b3297" in md_text and "d0ead011" in md_text
    assert "131%" in md_text and "[86%, 590%]" in md_text and "28 / 29" in md_text

    rv = committed_payload["replay_verification"]
    assert rv["all_episodes_step_replayed"] is True
    assert rv["total_episodes_replayed"] == 332
    assert rv["cached_episodes_replayed"] == 272
    assert rv["inproc_baseline_episodes_replayed"] == 60
    assert rv["total_steps_verified"] == 26995
    assert rv["truncated_steps_byte_checked"] == 2
    assert rv["pre_1bc3e281_detail_stripped_steps"] == 120
    assert rv["mismatches"] == 0

    ph = committed_payload["provenance_and_honesty"]
    hs = ph["honest_headline_scope_c59ecfd0"]
    assert hs["rehearsal_final_commit"] == "aa1c679e"
    assert hs["ceo_correction_commit"] == "5f9b3297"
    assert hs["gpt55_commit"] == "ca0a0dc0"
    assert hs["gpt55_prereg_commit"] == "cf394894"

    hr = hs["harbor_judge_path_rehearsal"]
    assert hr["commit"] == "aa1c679e"
    assert hr["final_trials_branch"] == "s1-rehearsal-final"
    assert hr["final_trials_commit"] == "d0ead011"
    assert hr["valid_gemini_accusations_correct"] == "28 / 29"
    assert hr["gap_reproduced_in_judge_path"] is False
    assert hr["runs"]["opencode-1"]["ratio_pct"] == 93
    assert hr["runs"]["opencode-2"]["ratio_pct"] == 116
    assert hr["runs"]["opencode-3"]["n_valid"] == 9
    assert hr["runs"]["opencode-3"]["infra_excluded"] == 1
    assert hr["runs"]["opencode-3"]["mean"] == pytest.approx(0.626, abs=1e-9)
    assert hr["runs"]["opencode-3"]["ratio_pct"] == 131
    assert hr["runs"]["opencode-3"]["ratio_ci95_pct"] == [86, 590]
    assert hr["runs"]["opencode-3"]["snapshot_0852_n_valid"] == 7
    assert hr["runs"]["opencode-3"]["snapshot_0852_ratio_pct"] == 153
    assert hr["runs"]["do_nothing"]["mean"] == 0.0
    assert hr["runs"]["stop_early"]["mean"] == 0.0

    lock = ph["panel_fix_a_seed_lock"]
    assert lock["classification"] == "post_hoc_lock_not_preregistered"
    assert lock["lock_commit"] == "671ed96"
    assert lock["primary_runs_commit"] == "8fd4dec"
    assert lock["delay_seconds"] == 28

    sol_dirs = ph["solver_reference_20_plus_10_dirs"]
    assert len(sol_dirs["medium"]) == 2 and len(sol_dirs["hard"]) == 2
    assert all("seeds30to59" not in p for p in sol_dirs["hard"])
    assert ph["hard_access_constraints_w4_noop"]["binds_in_any_episode"] is False

    paired_ref_rows = json.loads(PAIRED_GEMINI_JSON.read_text(encoding="utf-8"))
    key_map = {
        "opencode:google/gemini-4-carbon": "opencode_carbon",
        "gemini:gemini-4-carbon": "inproc_carbon",
        "solver": "solver",
    }
    for ref in paired_ref_rows:
        if "alternative" in ref["label"]:
            continue
        ckey = key_map.get(ref["agent"])
        if ckey is None:
            continue
        tier = ref["tier"]
        got_c = committed_payload["tiers"][tier]["cohorts"][ckey]
        assert got_c["n"] == 30
        assert got_c["raw_mean"] == pytest.approx(ref["mean"], abs=1e-8)
        assert got_c["luck_adjusted_mean"] == pytest.approx(ref["post_expected"], abs=1e-8)
        if ckey != "solver":
            vs_s = committed_payload["tiers"][tier]["paired_vs_unpaired"]["vs_solver"][ckey]
            assert got_c["raw_ratio_vs_solver"] == pytest.approx(ref["ratio"], abs=1e-8)
            assert got_c["luck_ratio_vs_solver"] == pytest.approx(ref["post_expected_ratio"], abs=1e-8)
            assert vs_s["raw"]["bootstrap_10k"]["ratio_paired_ci95"] == pytest.approx(
                [ref["ratio_lo"], ref["ratio_hi"]], abs=1e-8
            )
            assert vs_s["luck_adjusted"]["bootstrap_10k"]["ratio_paired_ci95"] == pytest.approx(
                [ref["post_expected_lo"], ref["post_expected_hi"]], abs=1e-8
            )

    gpt55 = committed_payload["tiers"]["hard"]["cohorts"]["opencode_gpt55"]
    assert gpt55["n"] == 30
    assert gpt55["raw_mean"] == pytest.approx(0.503666667, abs=1e-8)
    assert round(gpt55["raw_ratio_vs_solver"] * 100) == 101
    assert round(gpt55["luck_ratio_vs_solver"] * 100) == 84
    assert hs["gpt55_mcp_only_dev_0_29"]["stopped_without_accuse_seeds"] == [0, 17]

    g1 = committed_payload["g1_extension_34_37"]
    assert g1["completed_seeds"] == [34, 37]
    assert g1["n_completed"] == 2
    assert g1["ext_2seed_summary"]["frontier_raw_mean"] == pytest.approx(0.745, abs=1e-9)
    assert g1["ext_2seed_summary"]["solver_same_2seeds_raw_mean"] == pytest.approx(0.735, abs=1e-9)
    assert g1["pooled_32seed_secondary_sensitivity"]["n"] == 32
    assert round(g1["pooled_32seed_secondary_sensitivity"]["raw_ratio"] * 100) == 68
    assert round(g1["pooled_32seed_secondary_sensitivity"]["luck_adjusted_ratio"] * 100) == 75


def test_covariance_identities_stratification_and_outcome_taxonomy(committed_payload: dict[str, Any]) -> None:
    for tier in ("medium", "hard"):
        t_blk = committed_payload["tiers"][tier]
        pvu = t_blk["paired_vs_unpaired"]
        assert pvu["n_seeds"] == 30
        for key, vs_entry in pvu["vs_solver"].items():
            for m_key in ("raw", "luck_adjusted"):
                m = vs_entry[m_key]
                vf = m["var_frontier"]
                vs = m["var_solver"]
                cov_fs = m["cov_fs"]
                vd = m["var_paired_diff"]
                assert vd == pytest.approx(vf + vs - 2.0 * cov_fs, abs=1e-7)
                assert m["se_unpaired"] == pytest.approx(math.sqrt((vf + vs) / 30.0), abs=1e-8)
                assert m["se_paired"] == pytest.approx(math.sqrt(vd / 30.0), abs=1e-8)
                assert m["se_reduction_factor"] == pytest.approx(
                    m["se_unpaired"] / m["se_paired"], abs=1e-7
                )

        ws = t_blk["world_stratification"]
        tert = ws["by_solver_isolation_tertile"]
        assert [tert[k]["n_seeds"] for k in ("fast_t1", "mid_t2", "slow_t3")] == [10, 10, 10]
        assert sorted(
            tert["fast_t1"]["seeds"] + tert["mid_t2"]["seeds"] + tert["slow_t3"]["seeds"]
        ) == list(range(30))

        leak_split = ws["by_intrinsic_regular_leak_rate"]
        assert leak_split["low_leak_half"]["n_seeds"] == 15
        assert leak_split["high_leak_half"]["n_seeds"] == 15

        win_split = ws["by_winnability"]
        assert (
            win_split["winnable_solver_gt_0"]["n_seeds"]
            + win_split["non_winnable_solver_le_0"]["n_seeds"]
            == 30
        )

        for key in t_blk["cohort_order"]:
            tx = t_blk["outcome_taxonomy"][key]
            assert tx["n"] == 30
            assert sum(tx["counts"].values()) == 30
            ps = t_blk["per_seed"][key]
            assert len(ps["score"]) == 30

    oc_comb = committed_payload["tiers"]["hard"]["paired_vs_unpaired"]["vs_solver"]["opencode_carbon"][
        "combined_tightening_raw_unpaired_to_luck_paired"
    ]
    assert oc_comb["se_reduction_factor"] == pytest.approx(2.231, abs=2e-3)
    assert oc_comb["var_reduction_factor"] == pytest.approx(4.98, abs=2e-2)

    assert (
        MOD.classify_episode_outcome(
            accused_present=False,
            correct=False,
            consistent_set_size=3,
            mole_in_strict_consistent_set=True,
            p_accused=None,
            break_even_p=0.6,
            surfaced_flips_count=0,
        )
        == "horizon_abstain"
    )
    assert (
        MOD.classify_episode_outcome(
            accused_present=True,
            correct=True,
            consistent_set_size=2,
            mole_in_strict_consistent_set=True,
            p_accused=0.5,
            break_even_p=0.7,
            surfaced_flips_count=0,
        )
        == "sub_breakeven_gamble_win"
    )
    assert (
        MOD.classify_episode_outcome(
            accused_present=True,
            correct=False,
            consistent_set_size=2,
            mole_in_strict_consistent_set=True,
            p_accused=0.5,
            break_even_p=0.7,
            surfaced_flips_count=0,
        )
        == "sub_breakeven_gamble_loss"
    )
    assert (
        MOD.classify_episode_outcome(
            accused_present=True,
            correct=False,
            consistent_set_size=1,
            mole_in_strict_consistent_set=False,
            p_accused=0.95,
            break_even_p=0.6,
            surfaced_flips_count=1,
        )
        == "5pct_flip_singleton_trap"
    )
    assert (
        MOD.classify_episode_outcome(
            accused_present=True,
            correct=False,
            consistent_set_size=2,
            mole_in_strict_consistent_set=True,
            p_accused=0.8,
            break_even_p=0.6,
            surfaced_flips_count=0,
        )
        == "unresolved_premature_loss"
    )


def test_replay_1bc3e281_compat_and_loader_guards(
    committed_payload: dict[str, Any],
    tmp_path: Path,
) -> None:
    sol_by_seed, sol_shas = MOD.load_cached_episodes(
        ROOT,
        ["data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl"],
        "hard",
        "solver",
        {0},
    )
    assert sol_shas
    base_ep = sol_by_seed[0]
    diag = MOD.replay_and_diagnose_episode(base_ep)
    assert diag["seed"] == 0
    assert diag["score"] == pytest.approx(float(base_ep["score"]), abs=1e-9)
    sol_ps = committed_payload["tiers"]["hard"]["per_seed"]["solver"]
    assert diag["score"] == pytest.approx(sol_ps["score"][0], abs=1e-8)
    assert diag["consistent_set_size"] == sol_ps["c_size"][0]

    oc_by_seed, _ = MOD.load_cached_episodes(
        ROOT,
        ["data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"],
        "hard",
        "opencode:google/gemini-4-carbon",
        {18},
    )
    diag_oc18 = MOD.replay_and_diagnose_episode(oc_by_seed[18])
    oc_ps = committed_payload["tiers"]["hard"]["per_seed"]["opencode_carbon"]
    assert diag_oc18["outcome_class"] == "sub_breakeven_gamble_loss"
    assert diag_oc18["luck_adjusted"] == pytest.approx(oc_ps["la"][18], abs=1e-6)

    gt_slice = MOD.run_and_diagnose_inproc_baseline("hard", "grok_tactics", [0])
    assert len(gt_slice) == 1
    assert gt_slice[0]["score"] == pytest.approx(
        committed_payload["tiers"]["hard"]["per_seed"]["grok_tactics"]["score"][0],
        abs=1e-8,
    )

    with pytest.raises(ValueError, match="Env replay mismatch"):
        MOD.replay_and_diagnose_episode({**base_ep, "score": float(base_ep["score"]) + 0.25})

    env_err = Env("hard", 3)
    bad_call = env_err.call("interview", {"employee": "e01", "topic": "leaks"})
    assert bad_call.ok is False and bad_call.error == "invalid arguments"
    while not env_err.done:
        env_err.call("advance_day", {})
    ep_post = asdict(env_err.result("test_agent"))
    ep_pre = copy.deepcopy(ep_post)
    ep_pre["steps"][0]["result"] = {"ok": False, "data": {}, "error": "invalid arguments"}
    diag_pre = MOD.replay_and_diagnose_episode(ep_pre)
    assert diag_pre["steps_detail_stripped"] == 1

    with pytest.raises(ValueError, match="forbidden seeds30to59"):
        MOD.load_cached_episodes(
            ROOT,
            ["data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl"],
            "hard",
            "solver",
            set(range(30)),
        )

    dup_rel = "dup/episodes.jsonl"
    dup_fp = tmp_path / dup_rel
    dup_fp.parent.mkdir(parents=True, exist_ok=True)
    dup_fp.write_text(json.dumps(base_ep) + "\n" + json.dumps(base_ep) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate seed"):
        MOD.load_cached_episodes(tmp_path, [dup_rel], "hard", "solver", {0})

    snap_root = tmp_path / "snap"
    snap_table = snap_root / MOD.HARBOR_REHEARSAL_TABLE_REL
    snap_table.parent.mkdir(parents=True, exist_ok=True)
    orig_lines = (ROOT / MOD.HARBOR_REHEARSAL_TABLE_REL).read_text(encoding="utf-8").splitlines()
    snap_only_text = "\n".join(ln for ln in orig_lines if not ln.startswith("> **Correction")) + "\n"
    snap_table.write_text(snap_only_text, encoding="utf-8")
    snap_hr = MOD.load_harbor_rehearsal_summary(snap_root)
    assert snap_hr["commit"] == "c59ecfd0"
    assert snap_hr["runs"]["opencode-3"]["n_valid"] == 7
    assert snap_hr["runs"]["opencode-3"]["ratio_pct"] == 153


def test_cli_check_json_only_and_failure_modes(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_hr = committed_payload["provenance_and_honesty"]["honest_headline_scope_c59ecfd0"][
        "harbor_judge_path_rehearsal"
    ]
    assert MOD.approx_equal(MOD.load_harbor_rehearsal_summary(ROOT), expected_hr)

    monkeypatch.setattr(MOD, "compute", lambda *a, **kw: copy.deepcopy(committed_payload))

    rc_real = MOD.main(["--check"])
    out_real = capsys.readouterr().out
    assert rc_real == 0
    assert "PASS paired_seed_diagnostics_v14 --check" in out_real

    out_json = tmp_path / "diag.json"
    out_md = tmp_path / "diag.md"
    assert MOD.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert MOD.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    only_json = tmp_path / "only.json"
    missing_md = tmp_path / "not_written.md"
    assert MOD.main(["--json-only", "--out-json", str(only_json), "--out-md", str(missing_md)]) == 0
    assert only_json.is_file() and not missing_md.is_file()
    assert MOD.main(["--check", "--json-only", "--out-json", str(only_json), "--out-md", str(missing_md)]) == 0

    jitter = json.loads(out_json.read_text(encoding="utf-8"))
    jitter["tiers"]["hard"]["cohorts"]["solver"]["raw_mean"] += 1e-12
    out_json.write_text(json.dumps(jitter, separators=(",", ":")), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["tiers"]["hard"]["cohorts"]["solver"]["raw_mean"] += 0.1
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps(tampered, separators=(",", ":")), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(bad_json), "--out-md", str(out_md)]) == 1

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(out_md.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(JSON_PATH), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (MOD.MAX_JSON_BYTES + 10), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(oversized), "--out-md", str(out_md)]) == 1

    leaked = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    leaked["mole_id"] = "redacted"
    leak_json = tmp_path / "leak.json"
    leak_json.write_text(json.dumps(leaked, separators=(",", ":")), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(leak_json), "--out-md", str(out_md)]) == 1
