"""Unit and end-to-end replay tests for scripts/headline_gap_table.py and committed v1.4 headline artifacts."""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import headline_gap_table as hgt
from canary.env import Env
from canary.gemini import dashboard as gemini_dashboard
from canary.redteam.anticheat import _client_only_step

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
THIS_TEST_PATH = Path(__file__).resolve()
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"


def test_source_and_artifact_hygiene():
    owned_rel_paths = (
        "scripts/headline_gap_table.py",
        "results/eval_v14/headline_gap_table_v14.json",
        "results/leaderboard_v14_hard.json",
        "docs/reports/headline_gap_table_v14.md",
        "tests/test_headline_gap_table.py",
    )
    for rel in ("scripts/headline_gap_table.py", "tests/test_headline_gap_table.py"):
        py_text = (ROOT / rel).read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"comment char found in {rel}"

    stale_phrase = "pre-registered" + " dev seeds"
    for rel in owned_rel_paths:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash found in {rel}"
        assert EN_DASH not in txt, f"en dash found in {rel}"
        assert stale_phrase not in txt.lower(), f"stale {stale_phrase} phrasing in {rel}"

    md_text = hgt.OUT_MD.read_text(encoding="utf-8")
    assert "post-hoc locked dev seeds 0-29" in md_text
    assert "671ed96" in md_text and "28 s after" in md_text and "8fd4dec" in md_text

    protected_prefixes: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        protected_prefixes.append(line)

    for rel_path in owned_rel_paths:
        for prefix in protected_prefixes:
            if prefix.endswith("/"):
                assert not rel_path.startswith(prefix)
            else:
                assert rel_path != prefix


def test_wilson_ci_bounds_and_symmetry():
    lo0, hi0 = hgt.wilson_ci(0.0, 30)
    lo1, hi1 = hgt.wilson_ci(1.0, 30)
    assert lo0 == 0.0
    assert hi1 == 1.0
    assert math.isclose(hi0, 1.0 - lo1, abs_tol=1e-12)
    assert 0.10 < hi0 < 0.13

    lom, him = hgt.wilson_ci(0.80, 30)
    assert 0.62 < lom < 0.64
    assert 0.90 < him < 0.91

    lon, hin = hgt.wilson_ci(0.5, 0)
    assert math.isnan(lon) and math.isnan(hin)


def test_boot_ratio_deterministic_and_edge_cases():
    f = [0.6, 0.8, -1.0, 0.7, 0.5, 0.9, 0.65, 0.75, 0.8, 0.7]
    s = [0.8, 0.8, 0.7, 0.8, 0.6, 0.9, 0.7, 0.8, 0.8, 0.8]
    lo_a, hi_a = hgt.boot_ratio(f, s, B=2000, rng_seed=0)
    lo_b, hi_b = hgt.boot_ratio(f, s, B=2000, rng_seed=0)
    assert lo_a == lo_b and hi_a == hi_b
    point = (sum(f) / len(f)) / (sum(s) / len(s))
    assert lo_a < point < hi_a

    lo_ident, hi_ident = hgt.boot_ratio(s, s, B=1000, rng_seed=0)
    assert math.isclose(lo_ident, 1.0, abs_tol=1e-12)
    assert math.isclose(hi_ident, 1.0, abs_tol=1e-12)

    lo_one, hi_one = hgt.boot_ratio([0.5], [0.6])
    assert math.isnan(lo_one) and math.isnan(hi_one)

    lo_neg, hi_neg = hgt.boot_ratio([0.1, 0.2, 0.3], [-1.0, -0.5, 0.0], B=500, rng_seed=0)
    assert math.isnan(lo_neg) and math.isnan(hi_neg)


def test_paired_wilcoxon_and_sign_test():
    assert math.isclose(hgt.wilcoxon_pvalue([1.0, 2.0, 3.0, 4.0, 5.0]), 0.0625, abs_tol=1e-12)
    assert math.isclose(hgt.sign_test_pvalue([1.0, 2.0, 3.0, 4.0, 5.0]), 0.0625, abs_tol=1e-12)
    assert math.isclose(hgt.wilcoxon_pvalue([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 0.03125, abs_tol=1e-12)
    assert math.isclose(hgt.sign_test_pvalue([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 0.03125, abs_tol=1e-12)
    assert hgt.wilcoxon_pvalue([0.0, 0.0, 0.0]) == 1.0
    assert hgt.sign_test_pvalue([0.0, 0.0, 0.0]) == 1.0
    assert math.isclose(hgt.wilcoxon_pvalue([-2.0, -1.0, 1.0, 2.0]), 1.0, abs_tol=1e-12)
    p_ties = hgt.wilcoxon_pvalue([0.5, 0.5, 0.5, 0.5, -0.1])
    assert 0.0 < p_ties < 0.25


def test_luck_adjusted_ev_and_posterior_pass3():
    assert hgt.luck_adjusted_ev(None, None, 0.85) == 0.0
    assert hgt.luck_adjusted_ev(None, 0.9, 0.85) == 0.0
    assert hgt.luck_adjusted_ev("e01", None, 0.85) is None
    assert math.isclose(hgt.luck_adjusted_ev("e01", 1.0, 0.72), 0.72, abs_tol=1e-12)
    assert math.isclose(hgt.luck_adjusted_ev("e01", 0.0, 0.72), -1.0, abs_tol=1e-12)
    assert math.isclose(hgt.luck_adjusted_ev("e01", 0.5, 0.80), -0.10, abs_tol=1e-12)

    p3 = hgt.posterior_pass_k([1.0, 0.5, 0.0], k=3)
    assert math.isclose(p3, (1.0 + 0.125 + 0.0) / 3.0, abs_tol=1e-12)


def test_winnable_world_filter():
    f_scores = [0.6, -1.0, 0.8, 0.5, 0.7]
    s_scores = [0.8, 0.0, 0.8, -1.0, 0.7]
    seeds = [0, 1, 2, 3, 4]
    w = hgt.winnable_filter(f_scores, s_scores, seeds, B=1000, rng_seed=0)
    assert w["winnable_n"] == 3
    assert w["excluded_n"] == 2
    assert w["excluded_seeds"] == [1, 3]
    expected_ratio = ((0.6 + 0.8 + 0.7) / 3.0) / ((0.8 + 0.8 + 0.7) / 3.0)
    assert math.isclose(w["winnable_ratio"], expected_ratio, abs_tol=1e-12)
    assert w["winnable_ratio_lo"] <= w["winnable_ratio"] <= w["winnable_ratio_hi"]


def test_committed_artifacts_section_a_b1_b2_g1_and_headline_numbers():
    assert hgt.OUT_JSON.exists()
    assert hgt.OUT_MD.exists()
    raw_bytes = hgt.OUT_JSON.read_bytes()
    assert len(raw_bytes) <= hgt.MAX_JSON_BYTES

    data = json.loads(raw_bytes.decode("utf-8"))
    assert "post-hoc locked dev seeds 0-29" in data["primary_seeds_lock_note"]
    assert "671ed96" in data["primary_seeds_lock_note"]
    assert "8fd4dec" in data["primary_seeds_lock_note"]

    sec_a = data["section_a"]
    sec_b1 = data["section_b1"]
    sec_b2 = data["section_b2"]
    ver = data["verification"]
    g1 = data["g1_extension_sensitivity"]

    hgt.check_section_a_invariants(sec_a, root=ROOT)
    hgt.check_section_b1_invariants(sec_b1, root=ROOT)
    hgt.check_section_b2_invariants(sec_b2, root=ROOT)

    assert all(r["n"] == 30 and r["seeds"] == list(range(30)) for r in sec_a)
    assert len(sec_a) == 24
    assert len(sec_b1) == 3
    assert len(sec_b2) == 39
    assert ver["section_b_rows"] == 42
    assert ver["stored_solver_episodes_replayed"] == 60
    assert ver["stored_solver_extension_episodes_replayed"] == 30
    assert ver["replication_cached_episodes_replayed"] == 30
    assert ver["g1_extension_episodes_replayed"] == 2
    assert ver["ladder_cached_episodes_replayed"] == 550
    assert ver["ladder_gemma_episodes_replayed"] == 5
    assert ver["ladder_imported_inproc_episodes"] == 37
    assert ver["ladder_total_reported_episodes"] == 587
    assert ver["ladder_total_reported_cells"] == 42
    assert ver["pre_1bc3e281_detail_steps_stripped"] == 291

    assert all(r["n"] >= 30 for r in sec_b1)
    assert all(1 <= r["n"] < 30 and r["small_n_directional"] is True for r in sec_b2)

    sol_med = next(r for r in sec_a if r["agent"] == "solver" and r["tier"] == "medium" and r["kind"] == "reference")
    sol_hard = next(r for r in sec_a if r["agent"] == "solver" and r["tier"] == "hard" and r["kind"] == "reference")
    assert sol_med["n"] == 30 and sol_med["seeds"] == list(range(30)) and round(sol_med["mean"], 3) == 0.645
    assert sol_hard["n"] == 30 and sol_hard["seeds"] == list(range(30)) and round(sol_hard["mean"], 3) == 0.499

    assert g1["present"] is True
    assert g1["extension_seeds"] == [34, 37]
    assert g1["extension_n"] == 2
    assert g1["extension_infra_excluded"] == 31
    assert g1["pooled_n"] == 32
    assert round(g1["pooled_ratio"] * 100) == 68
    assert [round(x * 100) for x in g1["pooled_ratio_ci"]] == [32, 100]
    assert round(g1["pooled_luck_adj_ratio"] * 100) == 75
    assert [round(x * 100) for x in g1["pooled_luck_adj_ci"]] == [56, 93]
    assert round(g1["pooled_paired_diff"], 3) == -0.165
    assert round(g1["pooled_paired_diff_ci"], 3) == 0.182

    rep_flash_med = next(r for r in sec_b1 if r["kind"] == "replication" and r["tier"] == "medium")
    assert rep_flash_med["n"] == 30
    assert round(rep_flash_med["ratio"] * 100) == 67
    assert round(rep_flash_med["luck_adj_ratio"] * 100) == 75
    assert "seed 28" in rep_flash_med["caveat"]

    bad_n = copy.deepcopy(sec_a)
    bad_n[0]["n"] = 29
    with pytest.raises(ValueError, match="n=29 < 30"):
        hgt.check_section_a_invariants(bad_n, root=ROOT)

    bad_cache = copy.deepcopy(sec_a)
    bad_cache[0]["cache_path"] = "data/runs/committed/v1.4/nonexistent/episodes.jsonl"
    with pytest.raises(ValueError, match="Missing committed cache path"):
        hgt.check_section_a_invariants(bad_cache, root=ROOT)

    bad_b1 = copy.deepcopy(sec_b1)
    bad_b1[0]["n"] = 25
    with pytest.raises(ValueError, match="n=25 < 30"):
        hgt.check_section_b1_invariants(bad_b1, root=ROOT)

    bad_b2 = copy.deepcopy(sec_b2)
    bad_b2[0]["n"] = 30
    with pytest.raises(ValueError, match="outside \\[1, 29\\]"):
        hgt.check_section_b2_invariants(bad_b2, root=ROOT)

    flash = next(r for r in sec_a if r["agent"] == "opencode:google/gemini-3.5-flash" and r["tier"] == "hard")
    assert flash["n"] == 30
    assert round(flash["mean"], 3) == 0.373
    assert round(flash["score_ci"], 3) == 0.177
    assert round(flash["ratio"] * 100) == 75
    assert round(flash["ratio_lo"] * 100) == 36
    assert round(flash["ratio_hi"] * 100) == 123
    assert round(flash["mean_p_accused"], 2) == 0.71
    assert round(flash["luck_adjusted_score"], 3) == 0.110
    assert round(flash["luck_adj_ratio"] * 100) == 22
    assert round(flash["luck_adj_lo"] * 100) == -23
    assert round(flash["luck_adj_hi"] * 100) == 63

    oc_hard = next(
        r for r in sec_a if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["kind"] == "frontier"
    )
    assert round(oc_hard["ratio"] * 100) == 65
    assert round(oc_hard["luck_adj_ratio"] * 100) == 72

    assert hgt.render_md(data) + "\n" == hgt.OUT_MD.read_text(encoding="utf-8")


def test_leaderboard_v14_hard_schema_and_dashboard_compat():
    assert hgt.OUT_LEADERBOARD.exists()
    lb = json.loads(hgt.OUT_LEADERBOARD.read_text(encoding="utf-8"))
    assert lb["tier"] == "hard"
    assert lb["tiers_version"] == "v1.4"
    assert lb["seeds"] == "0-29"
    hgt.check_leaderboard_v14_hard(lb)

    rows = lb["rows"]
    assert len(rows) == 12
    by_name = {r["name"]: r for r in rows}
    assert "opencode:openai/gpt-5.5" in by_name
    assert round(by_name["opencode:openai/gpt-5.5"]["score"], 3) == 0.504
    assert round(by_name["opencode:openai/gpt-5.5"]["pct_solver"] * 100) == 101
    assert round(by_name["opencode:openai/gpt-5.5"]["luck_adjusted_pct_solver"] * 100) == 84
    for req in hgt.LEADERBOARD_REQUIRED_NAMES:
        assert req in by_name
        assert by_name[req]["n"] == 30
        assert tuple(by_name[req].keys()) == hgt.LEADERBOARD_KEYS

    oc_carbon = by_name["opencode:google/gemini-4-carbon"]
    assert round(oc_carbon["score"], 3) == 0.322
    assert round(oc_carbon["pct_solver"] * 100) == 65
    assert [round(x * 100) for x in oc_carbon["pct_solver_ci"]] == [24, 98]
    assert round(oc_carbon["luck_adjusted_score"], 3) == 0.360
    assert round(oc_carbon["luck_adjusted_pct_solver"] * 100) == 72
    assert [round(x * 100) for x in oc_carbon["luck_adjusted_pct_solver_ci"]] == [52, 91]

    oc_flash = by_name["opencode:google/gemini-3.5-flash"]
    assert round(oc_flash["score"], 3) == 0.373
    assert round(oc_flash["pct_solver"] * 100) == 75
    assert round(oc_flash["luck_adjusted_pct_solver"] * 100) == 22

    inproc_carbon = by_name["gemini:gemini-4-carbon"]
    assert round(inproc_carbon["score"], 3) == 0.473
    assert round(inproc_carbon["pct_solver"] * 100) == 95
    assert round(inproc_carbon["luck_adjusted_pct_solver"] * 100) == 84

    sol = by_name["reference solver"]
    assert round(sol["score"], 3) == 0.499
    assert sol["pct_solver"] == 1.0
    assert sol["pct_solver_ci"] is None
    assert sol["luck_adjusted_pct_solver"] == 1.0
    assert sol["luck_adjusted_pct_solver_ci"] is None

    slim = gemini_dashboard.slim_leaderboard(
        {
            "kind": "leaderboard",
            "source": "results/leaderboard_v14_hard.json",
            "source_sha": "deadbeef",
            "source_json": lb,
        }
    )
    assert slim["rows"] == rows

    bad_nested = copy.deepcopy(lb)
    bad_nested["rows"][0]["compute"] = {"gpu": 0}
    with pytest.raises(ValueError, match="not scalar or \\[lo, hi\\]"):
        hgt.check_leaderboard_v14_hard(bad_nested)

    bad_missing = copy.deepcopy(lb)
    bad_missing["rows"] = [r for r in bad_missing["rows"] if r["name"] != "grok_tactics"]
    with pytest.raises(ValueError, match="missing required hard n=30 cohorts"):
        hgt.check_leaderboard_v14_hard(bad_missing)


def test_env_replay_truncated_and_tamper_detection():
    ep_path = ROOT / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"
    seed2 = next(
        json.loads(line)
        for line in ep_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["seed"] == 2
    )
    rec = hgt.replay_verify_episode(seed2)
    assert rec["steps_truncated_checked"] == 1
    assert rec["steps_client_only"] == 1
    assert math.isclose(rec["score"], float(seed2["score"]), abs_tol=1e-9)

    tampered = copy.deepcopy(seed2)
    tampered["score"] = float(seed2["score"]) + 0.25
    with pytest.raises(ValueError, match="Env replay mismatch"):
        hgt.replay_verify_episode(tampered)


def test_replay_verify_1bc3e281_data_detail_compatibility():
    ep_path = ROOT / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"
    pre_ep = next(
        json.loads(line)
        for line in ep_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["seed"] == 3
    )
    rec_pre = hgt.replay_verify_episode(pre_ep)
    assert rec_pre["steps_detail_stripped"] == 2
    assert math.isclose(rec_pre["score"], float(pre_ep["score"]), abs_tol=1e-9)

    post_ep = copy.deepcopy(pre_ep)
    mcp_wrapped_ep = copy.deepcopy(pre_ep)
    bad_detail_ep = copy.deepcopy(pre_ep)
    env = Env(str(pre_ep["tier"]), int(pre_ep["seed"]))
    patched_steps = 0
    for idx, st in enumerate(pre_ep["steps"]):
        if _client_only_step(st):
            continue
        r = env.call(st["tool"], st.get("args") or {})
        if not r.ok and isinstance(r.data, dict) and set(r.data) == {"detail"}:
            exact_payload = {"ok": r.ok, "data": dict(r.data), "error": r.error}
            post_ep["steps"][idx]["result"] = exact_payload
            mcp_wrapped_ep["steps"][idx]["result"] = {"error": json.dumps(exact_payload)}
            bad_detail_ep["steps"][idx]["result"] = {
                "ok": r.ok,
                "data": {"detail": "tampered_detail_mismatch"},
                "error": r.error,
            }
            patched_steps += 1
    assert patched_steps == 2

    rec_post = hgt.replay_verify_episode(post_ep)
    assert rec_post["steps_detail_stripped"] == 0
    assert math.isclose(rec_post["score"], rec_pre["score"], abs_tol=1e-9)

    rec_wrapped = hgt.replay_verify_episode(mcp_wrapped_ep)
    assert rec_wrapped["steps_detail_stripped"] == 0
    assert math.isclose(rec_wrapped["score"], rec_pre["score"], abs_tol=1e-9)

    with pytest.raises(ValueError, match="Env replay mismatch"):
        hgt.replay_verify_episode(bad_detail_ep)


def test_direct_main_check_unmocked(capsys):
    assert hgt.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "headline_gap_table_v14 check OK" in out


def test_check_flag_mode_and_float_tolerance(tmp_path, monkeypatch):
    stored = json.loads(hgt.OUT_JSON.read_text(encoding="utf-8"))
    monkeypatch.setattr(hgt, "compute", lambda _root=ROOT: copy.deepcopy(stored))

    assert hgt.main(["--check"]) == 0

    j_path = tmp_path / "table.json"
    m_path = tmp_path / "table.md"
    lb_path = tmp_path / "leaderboard_v14_hard.json"
    out_flags = ["--out-json", str(j_path), "--out-md", str(m_path), "--out-leaderboard", str(lb_path)]
    assert hgt.main(out_flags) == 0
    assert hgt.main(["--check", *out_flags]) == 0

    jittered = json.loads(j_path.read_text(encoding="utf-8"))
    jittered["section_a"][0]["mean"] += 1e-12
    j_path.write_text(hgt._format_compact_json(jittered), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 0

    drifted = json.loads(j_path.read_text(encoding="utf-8"))
    drifted["section_a"][0]["mean"] += 1e-4
    j_path.write_text(hgt._format_compact_json(drifted), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    oversize_path = tmp_path / "oversize.json"
    oversize_path.write_text(" " * (hgt.MAX_JSON_BYTES + 10) + "{}", encoding="utf-8")
    assert hgt.main(["--check", "--out-json", str(oversize_path), "--out-md", str(m_path), "--out-leaderboard", str(lb_path)]) == 1

    j_path.write_text(hgt.OUT_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    drifted_lb = json.loads(lb_path.read_text(encoding="utf-8"))
    drifted_lb["rows"][0]["score"] += 1e-4
    lb_path.write_text(json.dumps(drifted_lb), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    lb_path.write_text(hgt.OUT_LEADERBOARD.read_text(encoding="utf-8"), encoding="utf-8")
    m_path.write_text(m_path.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    assert hgt.main(["--check", "--out-json", str(tmp_path / "missing.json"), "--out-md", str(m_path), "--out-leaderboard", str(lb_path)]) == 1
    assert hgt.main(["--check", "--out-json", str(j_path), "--out-md", str(m_path), "--out-leaderboard", str(tmp_path / "missing_lb.json")]) == 1
