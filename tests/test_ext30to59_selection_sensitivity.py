from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import math
import posixpath
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_ext30to59_selection as selection_mod

SCRIPT_PATH = ROOT / "scripts" / "analyze_ext30to59_selection.py"
REPORT_PATH = ROOT / "docs" / "reports" / "frontier_ext30to59_selection_sensitivity.md"
POOLED38_JSON_PATH = (
    ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "paired_table_pooled38.json"
)
COMMITTED_EXT_EPISODES = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
)
FLEET_EXT_EPISODES = (
    ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
MINUS_SIGN = chr(0x2212)
HASH_CHAR = chr(35)


def _load_module():
    return selection_mod


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip_ticks_and_bold(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def _extract_markdown_tables(md_text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            cur.append(cells)
        else:
            if len(cur) >= 3:
                tables.append(cur)
            cur = []
    if len(cur) >= 3:
        tables.append(cur)
    return tables


def test_cli_check_and_json_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    mod = _load_module()

    out_check = io.StringIO()
    with redirect_stdout(out_check):
        rc_check = mod.main(["--check"])
    assert rc_check == 0
    assert "PASS:" in out_check.getvalue()

    out_json = io.StringIO()
    with redirect_stdout(out_json):
        rc_json = mod.main(["--json"])
    assert rc_json == 0
    payload = json.loads(out_json.getvalue())
    assert payload["schema_version"] == "v1.4-ext30to59-selection-sensitivity-1"
    assert payload["provenance"]["dedup_ext8_seeds"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert len(payload["provenance"]["unobserved_ext22_seeds"]) == 22
    assert payload["provenance"]["seed34_g1_precedence"]["g1_final_day"] == 5
    assert abs(payload["provenance"]["seed34_g1_precedence"]["g1_raw_score"] - 0.79) < 1e-12

    tampered_md = tmp_path / "tampered.md"
    tampered_md.write_text(REPORT_PATH.read_text(encoding="utf-8").replace("75.4%", "99.9%", 1), encoding="utf-8")
    out_fail = io.StringIO()
    with redirect_stdout(out_fail):
        rc_fail = mod.main(["--check", "--report-md", str(tampered_md)])
    assert rc_fail == 1


def test_pr3_ext8_committed_compatibility_and_seed34_g1_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    mod = _load_module()

    base_data = mod.analyze_selection(repo=ROOT)
    comm_eps = _read_jsonl(COMMITTED_EXT_EPISODES)
    fleet_eps = _read_jsonl(FLEET_EXT_EPISODES)
    g1_by_seed = {ep["seed"]: ep for ep in comm_eps if ep["seed"] in (34, 37)}
    fleet_new = [ep for ep in fleet_eps if ep["seed"] not in (34, 37)]
    pr3_ext8_eps = sorted(list(g1_by_seed.values()) + fleet_new, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in pr3_ext8_eps] == [30, 34, 37, 42, 45, 48, 57, 58]

    pr3_jsonl = tmp_path / "committed_pr3_episodes.jsonl"
    pr3_jsonl.write_text("\n".join(json.dumps(ep) for ep in pr3_ext8_eps) + "\n", encoding="utf-8")

    pr3_with_fleet = mod.analyze_selection(repo=ROOT, committed_ext_jsonl=pr3_jsonl)
    assert pr3_with_fleet["provenance"]["committed_ext_seeds_present"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert pr3_with_fleet["provenance"]["seed34_g1_precedence"]["g1_final_day"] == 5
    assert abs(pr3_with_fleet["provenance"]["seed34_g1_precedence"]["g1_raw_score"] - 0.79) < 1e-12
    assert pr3_with_fleet["scenarios"] == base_data["scenarios"]
    assert pr3_with_fleet["solver_cohorts"] == base_data["solver_cohorts"]
    assert pr3_with_fleet["gemini_cohorts"] == base_data["gemini_cohorts"]
    assert mod.render_markdown(pr3_with_fleet) == mod.render_markdown(base_data)
    assert mod.main(["--check", "--committed-ext-jsonl", str(pr3_jsonl)]) == 0

    missing_fleet = tmp_path / "absent_fleet_episodes.jsonl"
    pr3_without_fleet = mod.analyze_selection(
        repo=ROOT,
        committed_ext_jsonl=pr3_jsonl,
        fleet_ext_jsonl=missing_fleet,
    )
    assert pr3_without_fleet["scenarios"] == base_data["scenarios"]
    assert mod.render_markdown(pr3_without_fleet) == mod.render_markdown(base_data)
    assert (
        mod.main([
            "--check",
            "--committed-ext-jsonl",
            str(pr3_jsonl),
            "--fleet-ext-jsonl",
            str(missing_fleet),
        ])
        == 0
    )

    fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
    bad_seed34_eps = [fleet_by_seed[34] if ep["seed"] == 34 else ep for ep in pr3_ext8_eps]
    bad_jsonl = tmp_path / "bad_seed34_episodes.jsonl"
    bad_jsonl.write_text("\n".join(json.dumps(ep) for ep in bad_seed34_eps) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seed 34"):
        mod.analyze_selection(repo=ROOT, committed_ext_jsonl=bad_jsonl)


def test_scenarios_and_identities_match_pooled38_and_bounds(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    mod = _load_module()
    data = mod.analyze_selection(repo=ROOT)

    pooled38_rows = json.loads(POOLED38_JSON_PATH.read_text(encoding="utf-8"))
    hard_rows = {(r["group"], r["label"]): r for r in pooled38_rows if r["tier"] == "hard"}
    ref_prim = hard_rows[("v1.4/opencode-gemini-4-carbon", "OpenCode + gemini-4-carbon over MCP (judges' shape)")]
    ref_pool38 = hard_rows[
        (
            "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
        )
    ]
    ref_sol60 = hard_rows[("v1.4/reference", "reference solver")]

    by_id = data["scenarios_by_id"]
    for sc_key, ref_row in (("baseline_primary30", ref_prim), ("s1_observed_pool38", ref_pool38)):
        sc = by_id[sc_key]
        assert sc["n"] == ref_row["n"]
        assert abs(sc["raw"]["gemini_mean"] - ref_row["mean"]) < 1e-12
        assert abs(sc["raw"]["gemini_ci"] - ref_row["ci"]) < 1e-12
        assert abs(sc["raw"]["solver_mean"] - ref_row["solver_same_seeds"]) < 1e-12
        assert abs(sc["raw"]["diff"] - ref_row["diff"]) < 1e-12
        assert abs(sc["raw"]["diff_ci"] - ref_row["diff_ci"]) < 1e-12
        assert abs(sc["raw"]["ratio"] - ref_row["ratio"]) < 1e-12
        assert abs(sc["raw"]["ratio_lo"] - ref_row["ratio_lo"]) < 1e-12
        assert abs(sc["raw"]["ratio_hi"] - ref_row["ratio_hi"]) < 1e-12
        assert abs(sc["luck_adjusted"]["gemini_mean"] - ref_row["post_expected"]) < 1e-12
        assert abs(sc["luck_adjusted"]["solver_mean"] - ref_row["solver_post_expected"]) < 1e-12
        assert abs(sc["luck_adjusted"]["ratio"] - ref_row["post_expected_ratio"]) < 1e-12
        assert abs(sc["luck_adjusted"]["ratio_lo"] - ref_row["post_expected_lo"]) < 1e-12
        assert abs(sc["luck_adjusted"]["ratio_hi"] - ref_row["post_expected_hi"]) < 1e-12

    for sc_key in (
        "s2_primary_mean_continuation",
        "s3a_stratified_steps_median",
        "s3b_stratified_day_median",
        "s4a_conservative_slow_steps_gt72",
        "s4a_strict_slow_steps_ge72",
        "s4b_optimistic_ext8_mean",
        "s4c_manski_lower_abstain_zero",
        "s4d_manski_lower_wrong_minus1",
        "s4e_manski_upper_solver_v",
        "s4f_manski_upper_unit_v",
    ):
        sc = by_id[sc_key]
        assert sc["n"] == 60
        assert sc["observed_n"] == 38 and sc["imputed_n"] == 22
        assert abs(sc["raw"]["solver_mean"] - ref_sol60["mean"]) < 1e-12
        assert abs(sc["luck_adjusted"]["solver_mean"] - ref_sol60["post_expected"]) < 1e-12

    obs38_raw_sum = 38.0 * by_id["s1_observed_pool38"]["raw"]["gemini_mean"]
    obs38_la_sum = 38.0 * by_id["s1_observed_pool38"]["luck_adjusted"]["gemini_mean"]
    assert abs(by_id["s4c_manski_lower_abstain_zero"]["raw"]["gemini_mean"] - obs38_raw_sum / 60.0) < 1e-12
    assert abs(by_id["s4c_manski_lower_abstain_zero"]["luck_adjusted"]["gemini_mean"] - obs38_la_sum / 60.0) < 1e-12
    assert abs(by_id["s4d_manski_lower_wrong_minus1"]["raw"]["gemini_mean"] - (obs38_raw_sum - 22.0) / 60.0) < 1e-12
    assert abs(by_id["s4d_manski_lower_wrong_minus1"]["luck_adjusted"]["gemini_mean"] - (obs38_la_sum - 22.0) / 60.0) < 1e-12
    assert abs(by_id["s4f_manski_upper_unit_v"]["raw"]["gemini_mean"] - (obs38_raw_sum + 22.0) / 60.0) < 1e-12

    unobs_v_sum = sum(
        row["solver_company_v"] for row in data["per_seed_30to59"] if row["status"] == "unobserved"
    )
    assert abs(by_id["s4e_manski_upper_solver_v"]["raw"]["gemini_mean"] - (obs38_raw_sum + unobs_v_sum) / 60.0) < 1e-12
    assert abs(by_id["s4e_manski_upper_solver_v"]["luck_adjusted"]["gemini_mean"] - (obs38_la_sum + unobs_v_sum) / 60.0) < 1e-12


def test_every_markdown_table_and_numeric_claim_matches_script_output(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    mod = _load_module()
    data = mod.analyze_selection(repo=ROOT)

    assert REPORT_PATH.is_file()
    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in md_text and EN_DASH not in md_text and MINUS_SIGN not in md_text
    assert md_text == mod.render_markdown(data)

    for py_path in (SCRIPT_PATH, Path(__file__).resolve()):
        py_txt = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_txt
        assert EM_DASH not in py_txt and EN_DASH not in py_txt and MINUS_SIGN not in py_txt

    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    md_dir = "docs/reports"
    checked_links = 0
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            continue
        for match in link_re.finditer(line):
            target = match.group(1).strip().split(HASH_CHAR, 1)[0]
            if not target or target.startswith(("http://", "https://")):
                continue
            resolved = posixpath.normpath(posixpath.join(md_dir, target))
            assert (ROOT / resolved).exists(), f"broken markdown link {target} -> {resolved}"
            checked_links += 1
    assert checked_links >= 10

    tables = _extract_markdown_tables(md_text)
    assert len(tables) == 6

    t2a_rows = tables[0][2:]
    expected_cohorts = [
        data["solver_cohorts"]["g1_observed2"],
        data["solver_cohorts"]["g1_unobserved28"],
        data["solver_cohorts"]["observed_ext8"],
        data["solver_cohorts"]["unobserved_ext22"],
        data["solver_cohorts"]["ext30to59_all"],
        data["solver_cohorts"]["primary0to29"],
        data["solver_cohorts"]["pooled0to59_all"],
    ]
    assert len(t2a_rows) == len(expected_cohorts)
    for cells, coh in zip(t2a_rows, expected_cohorts):
        assert int(cells[1]) == coh["n"]
        assert _strip_ticks_and_bold(cells[2]) == f"{coh['raw_mean']:+.3f} +/- {coh['raw_ci']:.3f}"
        assert _strip_ticks_and_bold(cells[3]) == f"{coh['luck_adjusted_mean']:+.3f} +/- {coh['luck_adjusted_ci']:.3f}"
        assert _strip_ticks_and_bold(cells[4]) == f"{coh['accuse_day_mean']:.2f} ({coh['accuse_day_n']})"
        assert _strip_ticks_and_bold(cells[5]) == f"{coh['horizon_day_mean']:.2f}"
        assert (
            _strip_ticks_and_bold(cells[6])
            == f"{coh['steps_mean']:.2f} +/- {coh['steps_ci']:.2f} ({coh['steps_median']:.1f})"
        )
        assert _strip_ticks_and_bold(cells[7]) == f"{coh['canary_mean']:.2f} +/- {coh['canary_ci']:.2f}"
        assert _strip_ticks_and_bold(cells[8]) == f"{100.0 * coh['accuracy']:.1f}% ({coh['correct_count']}/{coh['n']})"
        assert _strip_ticks_and_bold(cells[9]) == f"{coh['abstention_count']} / {coh['wrong_count']}"

    t2b_rows = tables[1][2:]
    expected_t2b = [
        ("raw_score", 3),
        ("luck_adjusted_score", 3),
        ("accuse_day_accused_only", 2),
        ("horizon_day", 2),
        ("total_steps", 2),
        ("canary_count", 2),
        ("company_value_v", 3),
        ("accuracy", 3),
        ("abstention_rate", 3),
    ]
    assert len(t2b_rows) == len(expected_t2b)
    for cells, (mkey, nd) in zip(t2b_rows, expected_t2b):
        m = data["obs8_vs_unobs22"][mkey]
        assert _strip_ticks_and_bold(cells[1]) == f"{m['obs8_mean']:.{nd}f}"
        assert _strip_ticks_and_bold(cells[2]) == f"{m['unobs22_mean']:.{nd}f}"
        assert _strip_ticks_and_bold(cells[3]) == f"{m['diff_obs_minus_unobs']:+.{nd}f}"
        assert _strip_ticks_and_bold(cells[4]) == f"{m['perm_p_two_sided']:.4f}"

    t3_rows = tables[2][2:]
    expected_strata = [
        data["stratification"]["steps_le_median"],
        data["stratification"]["steps_lt_median"],
        data["stratification"]["day_le_median"],
    ]
    assert len(t3_rows) == len(expected_strata)
    for cells, st in zip(t3_rows, expected_strata):
        assert _strip_ticks_and_bold(cells[1]) == f"{st['primary_fast_n']} / {st['primary_slow_n']}"
        assert _strip_ticks_and_bold(cells[2]) == f"{st['primary_fast_gemini_raw']:+.3f} / {st['primary_fast_gemini_la']:+.3f}"
        assert _strip_ticks_and_bold(cells[3]) == f"{st['primary_slow_gemini_raw']:+.3f} / {st['primary_slow_gemini_la']:+.3f}"
        assert _strip_ticks_and_bold(cells[4]) == f"{st['primary_fast_solver_raw']:+.3f} / {st['primary_fast_solver_la']:+.3f}"
        assert _strip_ticks_and_bold(cells[5]) == f"{st['primary_slow_solver_raw']:+.3f} / {st['primary_slow_solver_la']:+.3f}"
        assert _strip_ticks_and_bold(cells[6]) == f"{st['unobs22_fast_n']} / {st['unobs22_slow_n']}"

    t4a_rows = tables[3][2:]
    assert len(t4a_rows) == len(data["scenarios"])
    for cells, sc in zip(t4a_rows, data["scenarios"]):
        r = sc["raw"]
        la = sc["luck_adjusted"]
        assert cells[0] == sc["label"]
        assert _strip_ticks_and_bold(cells[1]) == f"{sc['n']} ({sc['observed_n']}+{sc['imputed_n']})"
        assert _strip_ticks_and_bold(cells[2]) == f"{r['gemini_mean']:+.3f}"
        assert _strip_ticks_and_bold(cells[3]) == f"{r['solver_mean']:+.3f}"
        assert _strip_ticks_and_bold(cells[4]) == f"{r['diff']:+.3f}"
        assert _strip_ticks_and_bold(cells[5]) == f"{100.0 * r['ratio']:.1f}% [{100.0 * r['ratio_lo']:.0f}%, {100.0 * r['ratio_hi']:.0f}%]"
        assert _strip_ticks_and_bold(cells[6]) == f"{la['gemini_mean']:+.3f}"
        assert _strip_ticks_and_bold(cells[7]) == f"{la['solver_mean']:+.3f}"
        assert _strip_ticks_and_bold(cells[8]) == f"{la['diff']:+.3f}"
        assert _strip_ticks_and_bold(cells[9]) == f"{100.0 * la['ratio']:.1f}% [{100.0 * la['ratio_lo']:.0f}%, {100.0 * la['ratio_hi']:.0f}%]"

    t4b_rows = tables[4][2:]
    donor_scenarios = [sc for sc in data["scenarios"] if "donor_boot_ratio_lo" in sc["raw"]]
    assert len(t4b_rows) == len(donor_scenarios)
    for cells, sc in zip(t4b_rows, donor_scenarios):
        r = sc["raw"]
        la = sc["luck_adjusted"]
        assert cells[0] == sc["label"]
        assert _strip_ticks_and_bold(cells[3]) == f"[{100.0 * r['donor_boot_ratio_lo']:.0f}%, {100.0 * r['donor_boot_ratio_hi']:.0f}%]"
        assert _strip_ticks_and_bold(cells[5]) == f"[{100.0 * la['donor_boot_ratio_lo']:.0f}%, {100.0 * la['donor_boot_ratio_hi']:.0f}%]"

    t5_rows = tables[5][2:]
    assert len(t5_rows) == 30
    for cells, row in zip(t5_rows, data["per_seed_30to59"]):
        assert int(cells[0]) == row["seed"]
        assert _strip_ticks_and_bold(cells[1]) == row["status"]
        assert _strip_ticks_and_bold(cells[2]) == f"{row['solver_raw']:+.3f}"
        assert _strip_ticks_and_bold(cells[3]) == f"{row['solver_luck_adjusted']:+.3f}"
        assert _strip_ticks_and_bold(cells[5]) == f"{row['solver_steps']} ({row['steps_stratum']})"
        assert int(_strip_ticks_and_bold(cells[6])) == row["solver_canaries"]
        assert _strip_ticks_and_bold(cells[7]) == f"{row['solver_company_v']:.3f}"
        if row["gemini_raw"] is None:
            assert cells[9] == "-" and cells[10] == "-" and cells[11] == "-"
        else:
            assert _strip_ticks_and_bold(cells[9]) == f"{row['gemini_raw']:+.3f}"
            assert _strip_ticks_and_bold(cells[10]) == f"{row['gemini_luck_adjusted']:+.3f}"
            assert _strip_ticks_and_bold(cells[11]) == f"d{row['gemini_accuse_day']} / {row['gemini_steps']}"
    assert math.isfinite(data["g1_exact_pair_test"]["frac_le_g1_steps"])
