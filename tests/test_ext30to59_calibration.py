from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import posixpath
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_ext30to59_calibration as calib_mod

SCRIPT_PATH = ROOT / "scripts" / "analyze_ext30to59_calibration.py"
REPORT_PATH = ROOT / "docs" / "reports" / "frontier_ext30to59_calibration.md"
TEST_PATH = Path(__file__).resolve()

COMMITTED_V14 = ROOT / "data" / "runs" / "committed" / "v1.4"
PAIRED_GEMINI_JSON = COMMITTED_V14 / "paired_table_gemini.json"
COMMITTED_EXT_EPISODES = COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"

EXT_REPL_DIR = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
FLEET_EXT_EPISODES = EXT_REPL_DIR / "hard" / "episodes.jsonl"
FLEET7_JSON = EXT_REPL_DIR / "paired_table_fleet7.json"
EXT8_JSON = EXT_REPL_DIR / "paired_table_ext8_combined.json"
POOLED38_JSON = EXT_REPL_DIR / "paired_table_pooled38.json"

OWN_ADDED_REL_PATHS = {
    "scripts/analyze_ext30to59_calibration.py",
    "docs/reports/frontier_ext30to59_calibration.md",
    "tests/test_ext30to59_calibration.py",
}

FORBIDDEN_DASHES = tuple(chr(cp) for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))
HASH_CHAR = chr(35)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip_md(text: str) -> str:
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


def test_cli_check_json_write_md_and_tamper_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")

    out_check = io.StringIO()
    with redirect_stdout(out_check):
        rc_check = calib_mod.main(["--check"])
    assert rc_check == 0
    assert "PASS:" in out_check.getvalue()

    out_json = io.StringIO()
    with redirect_stdout(out_json):
        rc_json = calib_mod.main(["--json"])
    assert rc_json == 0
    payload = json.loads(out_json.getvalue())
    assert payload["schema_version"] == "v1.4-ext30to59-calibration-stopping-1"
    assert payload["replay_verified_distinct_count"] == 99
    assert payload["provenance"]["dedup_ext8_seeds"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert payload["provenance"]["fleet7_seeds"] == [30, 34, 42, 45, 48, 57, 58]
    assert len(payload["provenance"]["unobserved_ext22_seeds"]) == 22
    s34 = payload["provenance"]["seed34_g1_precedence"]
    assert s34["kept_source"] == "committed_g1"
    assert s34["g1_final_day"] == 5 and abs(s34["g1_raw_score"] - 0.79) < 1e-12
    assert s34["fleet_final_day"] == 8 and abs(s34["fleet_raw_score"] - 0.82) < 1e-12

    regenerated_md = tmp_path / "regenerated.md"
    out_write = io.StringIO()
    with redirect_stdout(out_write):
        rc_write = calib_mod.main(["--write-md", "--report-md", str(regenerated_md)])
    assert rc_write == 0
    assert regenerated_md.read_text(encoding="utf-8") == REPORT_PATH.read_text(encoding="utf-8")

    tampered_md = tmp_path / "tampered.md"
    tampered_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8").replace("0.1303", "0.9999", 1),
        encoding="utf-8",
    )
    out_tamper = io.StringIO()
    with redirect_stdout(out_tamper):
        rc_tamper = calib_mod.main(["--check", "--report-md", str(tampered_md)])
    assert rc_tamper == 1

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8").replace(" - ", f" {chr(0x2014)} ", 1),
        encoding="utf-8",
    )
    out_dash = io.StringIO()
    with redirect_stdout(out_dash):
        rc_dash = calib_mod.main(["--check", "--report-md", str(dash_md)])
    assert rc_dash == 1

    out_missing = io.StringIO()
    with redirect_stdout(out_missing):
        rc_missing = calib_mod.main(["--check", "--report-md", str(tmp_path / "absent.md")])
    assert rc_missing == 1


def test_dual_g1_n2_and_pr3_n8_committed_layout_compatibility(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    base_data = calib_mod.analyze_calibration(repo=ROOT)
    base_md = calib_mod.render_markdown(base_data)

    comm_eps = _read_jsonl(COMMITTED_EXT_EPISODES)
    g1_eps = [ep for ep in comm_eps if ep["seed"] in (34, 37)]
    assert [ep["seed"] for ep in g1_eps] == [34, 37]

    g1_n2_jsonl = tmp_path / "committed_g1_n2.jsonl"
    g1_n2_jsonl.write_text("\n".join(json.dumps(ep) for ep in g1_eps) + "\n", encoding="utf-8")

    if FLEET_EXT_EPISODES.is_file():
        fleet_eps = _read_jsonl(FLEET_EXT_EPISODES)
        g1_n2_data = calib_mod.analyze_calibration(
            repo=ROOT,
            committed_ext_jsonl=g1_n2_jsonl,
            fleet_ext_jsonl=FLEET_EXT_EPISODES,
        )
        assert g1_n2_data["provenance"]["committed_ext_seeds_present"] == [34, 37]
        assert g1_n2_data["cohorts"] == base_data["cohorts"]
        assert g1_n2_data["paired_comparisons"] == base_data["paired_comparisons"]
        assert calib_mod.render_markdown(g1_n2_data) == base_md

        fleet_non_g1 = [ep for ep in fleet_eps if ep["seed"] not in (34, 37)]
    else:
        fleet_eps = []
        fleet_non_g1 = [ep for ep in comm_eps if ep["seed"] not in (34, 37)]

    pr3_ext8_eps = sorted(g1_eps + fleet_non_g1, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in pr3_ext8_eps] == [30, 34, 37, 42, 45, 48, 57, 58]

    pr3_jsonl = tmp_path / "committed_pr3_ext8.jsonl"
    pr3_jsonl.write_text("\n".join(json.dumps(ep) for ep in pr3_ext8_eps) + "\n", encoding="utf-8")

    pr3_with_default_fleet = calib_mod.analyze_calibration(repo=ROOT, committed_ext_jsonl=pr3_jsonl)
    assert pr3_with_default_fleet["provenance"]["committed_ext_seeds_present"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert pr3_with_default_fleet["cohorts"] == base_data["cohorts"]
    assert pr3_with_default_fleet["paired_comparisons"] == base_data["paired_comparisons"]
    assert calib_mod.render_markdown(pr3_with_default_fleet) == base_md
    assert calib_mod.main(["--check", "--committed-ext-jsonl", str(pr3_jsonl)]) == 0

    absent_fleet = tmp_path / "missing_fleet_episodes.jsonl"
    pr3_without_fleet = calib_mod.analyze_calibration(
        repo=ROOT,
        committed_ext_jsonl=pr3_jsonl,
        fleet_ext_jsonl=absent_fleet,
    )
    assert pr3_without_fleet["provenance"]["fleet_seed34_live_loaded"] is False
    for c_got, c_want in zip(pr3_without_fleet["cohorts"], base_data["cohorts"]):
        assert c_got["id"] == c_want["id"]
        assert abs(c_got["raw_mean"] - c_want["raw_mean"]) < 1e-12
        assert abs(c_got["luck_adjusted_mean"] - c_want["luck_adjusted_mean"]) < 1e-12
        assert abs(c_got["calibration"]["brier_mean"] - c_want["calibration"]["brier_mean"]) < 1e-12
        assert abs(c_got["regret"]["total_mean"] - c_want["regret"]["total_mean"]) < 1e-12
    assert calib_mod.render_markdown(pr3_without_fleet) == base_md
    assert (
        calib_mod.main([
            "--check",
            "--committed-ext-jsonl",
            str(pr3_jsonl),
            "--fleet-ext-jsonl",
            str(absent_fleet),
        ])
        == 0
    )

    if fleet_eps:
        fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
        bad_seed34_eps = [fleet_by_seed[34] if ep["seed"] == 34 else ep for ep in pr3_ext8_eps]
    else:
        bad_ep34 = dict(pr3_ext8_eps[1], final_day=8, score=0.82)
        bad_seed34_eps = [bad_ep34 if ep["seed"] == 34 else ep for ep in pr3_ext8_eps]
    bad_jsonl = tmp_path / "bad_seed34.jsonl"
    bad_jsonl.write_text("\n".join(json.dumps(ep) for ep in bad_seed34_eps) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seed 34"):
        calib_mod.analyze_calibration(repo=ROOT, committed_ext_jsonl=bad_jsonl)


def test_algebraic_identities_and_paired_table_agreement(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    data = calib_mod.analyze_calibration(repo=ROOT)
    assert calib_mod._validate_invariants(data) == []

    accused_checked = 0
    abstained_checked = 0
    for grp, rows in data["episodes_by_group"].items():
        for r in rows:
            assert r["replay_verified"] is True
            v_val = float(r["company_value_v"])
            p_star = 1.0 / (1.0 + v_val)
            assert abs(float(r["p_star"]) - p_star) < 1e-12
            if r["abstained"]:
                abstained_checked += 1
                assert r["p_accused"] is None
                assert r["ev_margin"] is None
                assert r["brier"] is None
                assert abs(float(r["luck_adjusted_score"])) < 1e-12
                assert abs(float(r["shortfall_vs_unit"]) - 1.0) < 1e-12
            else:
                accused_checked += 1
                p_val = float(r["p_accused"])
                la = float(r["luck_adjusted_score"])
                decay = 1.0 - v_val
                uncert = (1.0 - p_val) * (1.0 + v_val)
                assert abs(float(r["value_decay_cost"]) - decay) < 1e-12
                assert abs(float(r["posterior_uncertainty_cost"]) - uncert) < 1e-12
                assert abs(la - (p_val * v_val - (1.0 - p_val))) < 1e-12
                assert abs(la - (1.0 - (1.0 - v_val) - (1.0 - p_val) * (1.0 + v_val))) < 1e-12
                assert abs(float(r["shortfall_vs_unit"]) - (decay + uncert)) < 1e-12
                assert abs(la - (1.0 + v_val) * (p_val - p_star)) < 1e-12
                assert bool(r["is_negative_ev"]) is (p_val < p_star)
                assert bool(r["is_negative_ev"]) is (la < 0.0)
                corr_num = 1.0 if r["correct"] else 0.0
                assert abs(float(r["brier"]) - (p_val - corr_num) ** 2) < 1e-12
                assert abs(decay - (r["leak_damage_cost"] + r["canary_cost"] + r["restrict_cost"])) < 1e-12
    assert accused_checked == 103
    assert abstained_checked == 2

    c_by_id = data["cohorts_by_id"]
    assert c_by_id["gemini_primary30"]["breakeven"]["negative_ev_seeds"] == [5, 18, 23]
    assert c_by_id["gemini_ext8"]["breakeven"]["negative_ev_seeds"] == []
    assert c_by_id["gemini_fleet7"]["breakeven"]["negative_ev_seeds"] == []
    assert c_by_id["gemini_pooled38"]["breakeven"]["negative_ev_seeds"] == [5, 18, 23]
    for sol_id in ("solver_primary30", "solver_ext30", "solver_all60", "solver_ext8"):
        assert c_by_id[sol_id]["breakeven"]["negative_ev_count"] == 0
        assert c_by_id[sol_id]["breakeven"]["sub_085_count"] == 0

    prim_rows = json.loads(PAIRED_GEMINI_JSON.read_text(encoding="utf-8"))
    prim_gem_ref = next(
        r for r in prim_rows if r["tier"] == "hard" and r["group"] == "v1.4/opencode-gemini-4-carbon" and "0 for empty" not in r["label"]
    )
    p_prim = data["paired_by_id"]["paired_primary30"]
    assert abs(p_prim["raw"]["gemini_mean"] - prim_gem_ref["mean"]) < 1e-12
    assert abs(p_prim["raw"]["solver_mean"] - prim_gem_ref["solver_same_seeds"]) < 1e-12
    assert abs(p_prim["raw"]["ratio"] - prim_gem_ref["ratio"]) < 1e-12
    assert abs(p_prim["raw"]["ratio_lo"] - prim_gem_ref["ratio_lo"]) < 1e-12
    assert abs(p_prim["raw"]["ratio_hi"] - prim_gem_ref["ratio_hi"]) < 1e-12
    assert abs(p_prim["luck_adjusted"]["gemini_mean"] - prim_gem_ref["post_expected"]) < 1e-12
    assert abs(p_prim["luck_adjusted"]["solver_mean"] - prim_gem_ref["solver_post_expected"]) < 1e-12
    assert abs(p_prim["luck_adjusted"]["ratio"] - prim_gem_ref["post_expected_ratio"]) < 1e-12
    assert abs(p_prim["luck_adjusted"]["ratio_lo"] - prim_gem_ref["post_expected_lo"]) < 1e-12
    assert abs(p_prim["luck_adjusted"]["ratio_hi"] - prim_gem_ref["post_expected_hi"]) < 1e-12

    if EXT8_JSON.is_file() and FLEET7_JSON.is_file() and POOLED38_JSON.is_file():
        ext8_ref = json.loads(EXT8_JSON.read_text(encoding="utf-8"))[0]
        fl7_ref = json.loads(FLEET7_JSON.read_text(encoding="utf-8"))[0]
        p38_rows = json.loads(POOLED38_JSON.read_text(encoding="utf-8"))
        p38_ref = next(
            r for r in p38_rows
            if r["tier"] == "hard" and r["group"] == "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext"
        )
        for pair_key, ref_row in (
            ("paired_ext8", ext8_ref),
            ("paired_fleet7", fl7_ref),
            ("paired_pooled38", p38_ref),
        ):
            pc = data["paired_by_id"][pair_key]
            assert pc["n"] == ref_row["n"]
            assert abs(pc["raw"]["gemini_mean"] - ref_row["mean"]) < 1e-12
            assert abs(pc["raw"]["solver_mean"] - ref_row["solver_same_seeds"]) < 1e-12
            assert abs(pc["raw"]["ratio"] - ref_row["ratio"]) < 1e-12
            assert abs(pc["luck_adjusted"]["gemini_mean"] - ref_row["post_expected"]) < 1e-12
            assert abs(pc["luck_adjusted"]["solver_mean"] - ref_row["solver_post_expected"]) < 1e-12
            assert abs(pc["luck_adjusted"]["ratio"] - ref_row["post_expected_ratio"]) < 1e-12


def test_every_markdown_table_cell_and_headline_caveat_matches_data(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    data = calib_mod.analyze_calibration(repo=ROOT)
    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert md_text == calib_mod.render_markdown(data)

    for required_phrase in (
        "Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`) remains unchanged",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "incomplete extension shards",
    ):
        assert required_phrase in md_text

    tables = _extract_markdown_tables(md_text)
    assert len(tables) == 6

    t2a_rows = tables[0][2:]
    assert len(t2a_rows) == len(data["cohorts"])
    for cells, coh in zip(t2a_rows, data["cohorts"]):
        cal = coh["calibration"]
        assert cells[0] == coh["label"]
        assert _strip_md(cells[1]) == f"{coh['n']} ({coh['accused_count']}/{coh['abstention_count']})"
        assert _strip_md(cells[2]) == f"{cal['p_accused_mean']:.3f}"
        assert _strip_md(cells[3]) == f"{100.0 * cal['empirical_accuracy_accused']:.1f}% ({coh['correct_count']}/{coh['accused_count']})"
        assert _strip_md(cells[4]) == f"{cal['calibration_gap_acc_minus_p']:+.3f}"
        assert _strip_md(cells[5]) == f"{cal['expected_wrong']:.2f} vs {cal['realized_wrong']}"
        assert _strip_md(cells[6]) == f"{cal['brier_mean']:.4f}"
        assert _strip_md(cells[7]) == f"{cal['ece_4bin']:.4f}"

    t2b_rows = tables[1][2:]
    assert len(t2b_rows) == len(data["cohorts"])
    for cells, coh in zip(t2b_rows, data["cohorts"]):
        assert cells[0] == coh["label"]
        assert int(_strip_md(cells[1])) == coh["accused_count"]
        for col_idx, bin_id in enumerate(("lt_060", "060_085", "085_095", "ge_095"), start=2):
            b = coh["calibration"]["reliability_bins_by_id"][bin_id]
            expected_cell = (
                "0 (-)"
                if b["count"] == 0
                else f"{b['count']} ({b['mean_p']:.3f} / {100.0 * b['empirical_accuracy']:.1f}%)"
            )
            assert _strip_md(cells[col_idx]) == expected_cell

    t3a_rows = tables[2][2:]
    assert len(t3a_rows) == len(data["cohorts"])
    for cells, coh in zip(t3a_rows, data["cohorts"]):
        be = coh["breakeven"]
        assert cells[0] == coh["label"]
        assert int(_strip_md(cells[1])) == coh["accused_count"]
        assert _strip_md(cells[2]) == f"{be['company_v_accused_mean']:.3f}"
        assert _strip_md(cells[3]) == f"{be['p_star_mean']:.3f}"
        assert _strip_md(cells[4]) == f"{be['ev_margin_mean']:+.3f}"
        assert _strip_md(cells[5]) == f"{be['ev_margin_median']:+.3f}"
        assert _strip_md(cells[6]) == f"{be['ev_margin_min']:+.3f} (s{be['ev_margin_min_seed']})"
        assert _strip_md(cells[7]) == f"{be['sub_085_count']}/{coh['accused_count']}"
        seeds_txt = "none" if not be["negative_ev_seeds"] else "[" + ", ".join(str(s) for s in be["negative_ev_seeds"]) + "]"
        assert _strip_md(cells[8]) == f"{be['negative_ev_count']}/{coh['accused_count']} ({seeds_txt})"
        assert _strip_md(cells[9]) == f"{be['negative_ev_luck_adj_sum']:+.3f}"

    t4a_rows = tables[3][2:]
    assert len(t4a_rows) == len(data["cohorts"])
    for cells, coh in zip(t4a_rows, data["cohorts"]):
        sd = coh["stopping_decomposition"]
        reg = coh["regret"]
        assert cells[0] == coh["label"]
        assert _strip_md(cells[1]) == f"{coh['n']} ({coh['accused_count']})"
        assert (
            _strip_md(cells[2])
            == f"{sd['accused_value_decay_mean']:.3f} ({sd['accused_leak_damage_mean']:.3f} / {sd['accused_canary_cost_mean']:.3f} / {sd['accused_restrict_cost_mean']:.3f})"
        )
        assert (
            _strip_md(cells[3])
            == f"{sd['accused_posterior_uncertainty_mean']:.3f} ({100.0 * sd['accused_uncertainty_share']:.1f}%)"
        )
        assert _strip_md(cells[4]) == f"{sd['accused_luck_adjusted_mean']:+.3f}"
        assert (
            _strip_md(cells[5])
            == f"{sd['all_seed_shortfall_mean']:.3f} ({sd['all_seed_decay_cost']:.3f} + {sd['all_seed_uncertainty_cost']:.3f} + {sd['all_seed_abstention_cost']:.3f})"
        )
        assert _strip_md(cells[6]) == f"{coh['luck_adjusted_mean']:+.3f} ({coh['raw_mean']:+.3f})"
        assert (
            _strip_md(cells[7])
            == f"{reg['total_mean']:.4f} ({reg['accuse_mean']:.4f} / {reg['plant_canary_mean']:.4f} / {reg['restrict_access_mean']:.4f})"
        )

    t4b_rows = tables[4][2:]
    assert len(t4b_rows) == len(data["paired_comparisons"])
    for cells, pc in zip(t4b_rows, data["paired_comparisons"]):
        r = pc["raw"]
        la = pc["luck_adjusted"]
        gd = pc["gap_decomposition_per_seed"]
        cr = pc["calibration_and_regret_diff"]
        assert cells[0] == pc["label"]
        assert int(_strip_md(cells[1])) == pc["n"]
        assert _strip_md(cells[2]) == f"{100.0 * r['ratio']:.1f}% [{100.0 * r['ratio_lo']:.0f}%, {100.0 * r['ratio_hi']:.0f}%]"
        assert _strip_md(cells[3]) == f"{100.0 * la['ratio']:.1f}% [{100.0 * la['ratio_lo']:.0f}%, {100.0 * la['ratio_hi']:.0f}%]"
        assert _strip_md(cells[4]) == f"{gd['solver_minus_gemini_luck_adj']:+.3f}"
        assert _strip_md(cells[5]) == f"{gd['excess_decay_gem_minus_sol']:+.3f}"
        assert _strip_md(cells[6]) == f"{gd['excess_uncertainty_gem_minus_sol']:+.3f}"
        assert _strip_md(cells[7]) == f"{gd['excess_abstention_gem_minus_sol']:+.3f}"
        assert _strip_md(cells[8]) == f"{cr['gemini_brier']:.4f} vs {cr['solver_brier']:.4f}"
        assert _strip_md(cells[9]) == f"{cr['gemini_regret_mean']:.4f} vs {cr['solver_regret_mean']:.4f}"

    t5_rows = tables[5][2:]
    assert len(t5_rows) == 17
    assert len(t5_rows) == len(data["ext_episode_rows"])
    for cells, row in zip(t5_rows, data["ext_episode_rows"]):
        assert int(_strip_md(cells[0])) == row["seed"]
        assert _strip_md(cells[1]) == row["cohort_role"]
        assert _strip_md(cells[2]) == f"d{row['accuse_day']} ({row['total_steps']})"
        assert _strip_md(cells[3]) == f"{row['canary_count']} / {row['interview_count']} / {row['leak_count']}"
        assert _strip_md(cells[4]) == f"{row['company_value_v']:.3f}"
        assert _strip_md(cells[5]) == f"{row['p_accused']:.3f}"
        assert _strip_md(cells[6]) == f"{row['p_star']:.3f}"
        assert _strip_md(cells[7]) == f"{row['ev_margin']:+.3f}"
        assert _strip_md(cells[8]) == f"{row['value_decay_cost']:.3f}"
        assert _strip_md(cells[9]) == f"{row['posterior_uncertainty_cost']:.3f}"
        assert _strip_md(cells[10]) == f"{row['luck_adjusted_score']:+.3f} ({row['raw_score']:+.3f})"
        assert _strip_md(cells[11]) == f"{row['brier']:.4f}"
        assert _strip_md(cells[12]) == f"{row['regret_total']:.4f} ({row['regret_accuse']:.4f})"


def test_strict_hygiene_tokenize_comments_dashes_and_relative_links():
    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"found comment tokens in {py_path}: {comment_tokens}"
        assert HASH_CHAR not in src, f"found literal hash character in {py_path}"

    for fpath in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        txt = fpath.read_text(encoding="utf-8")
        for bad_dash in FORBIDDEN_DASHES:
            assert bad_dash not in txt, f"forbidden unicode dash U+{ord(bad_dash):04X} in {fpath}"

    justsilas_files: set[str] | None = None
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "origin/justSilas"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        justsilas_files = set(proc.stdout.splitlines()) | OWN_ADDED_REL_PATHS

    md_text = REPORT_PATH.read_text(encoding="utf-8")
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    md_dir = "docs/reports"
    checked_links = 0
    in_fence = False
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in link_re.finditer(line):
            target = match.group(1).strip().split(HASH_CHAR, 1)[0]
            if not target or target.startswith(("http://", "https://")):
                continue
            resolved = posixpath.normpath(posixpath.join(md_dir, target))
            assert (ROOT / resolved).exists(), f"broken markdown link on workspace: {target} -> {resolved}"
            if justsilas_files is not None:
                assert resolved in justsilas_files, (
                    f"markdown link {target} -> {resolved} does not resolve on standalone origin/justSilas"
                )
            checked_links += 1
    assert checked_links >= 12
