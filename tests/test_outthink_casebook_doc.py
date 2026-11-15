from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from canary.gemini import outthink_casebook

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_casebook.py"
DOC_PATH = ROOT / "docs" / "demo" / "CASEBOOK.md"
JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
CASES_JS_PATH = ROOT / "demo" / "out-think-gemini" / "cases.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
H1 = HASH_CHAR
H2 = HASH_CHAR * 2
FORBIDDEN_NET = "fetch" + "("
HTML_COMMENT_OPEN = "<!" + "--"

EXPECTED_CASE_IDS = [
    "carbon-hard-1",
    "flash-lite-hard-4",
    "flash38-hard-7",
    "carbon-medium-4",
    "flash-lite-medium-1",
    "hydrogen-hard-3",
    "flash38-medium-9",
    "flash35-hard-1",
    "argon-hard-18",
    "argon-medium-6",
    "hydrogen-medium-2",
    "flash35-medium-8",
]


def _extract_table_data_rows(md_text: str, section_heading: str) -> list[str]:
    idx = md_text.index(section_heading)
    after = md_text[idx + len(section_heading) :].splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in after:
        stripped = line.strip()
        if stripped.startswith("|"):
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            break
    assert len(table_lines) >= 3
    return table_lines[2:]


def test_casebook_cli_check_and_doc_in_sync(capsys):
    assert MODULE_PATH.is_file()
    assert DOC_PATH.is_file()
    assert JSON_PATH.is_file()
    assert CASES_JS_PATH.is_file()

    rc = outthink_casebook.main(["--check"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK:" in captured.out

    report = outthink_casebook.build_casebook_report(ROOT)
    expected_md = outthink_casebook.render_casebook_markdown(report)
    assert DOC_PATH.read_text(encoding="utf-8") == expected_md


def test_casebook_provenance_and_all_12_cases_exact_numbers():
    report = outthink_casebook.build_casebook_report(ROOT)
    raw_json = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    assert report["verified"] is True
    assert report["errors"] == []

    prov = report["provenance"]
    assert prov["tiers_version"] == "v1.4"
    assert prov["json_js_identical"] is True
    assert prov["is_bootstrap_fallback"] is False
    assert prov["total_episodes"] == 550
    assert prov["ladder_corpus_episodes"] == 550
    assert prov["ledger_unique_runs"] == 618
    assert prov["corpus_cost_usd"] == pytest.approx(262.7061, abs=1e-4)
    assert prov["case_count"] == 12
    assert prov["unique_world_count"] == 11
    assert prov["hold_fire_cases"] == 8
    assert prov["accuse_cases"] == 4
    assert prov["level_run_count"] == 39
    assert prov["level_total_thinking_tokens"] == 581904
    assert prov["level_total_ledger_calls"] == 2194
    assert prov["level_total_cost_usd"] == pytest.approx(15.280309, abs=1e-6)
    assert prov["cross_model_carbon_case_count"] == 12
    assert prov["cross_model_carbon_run_count"] == 23
    assert prov["ladder_matrix_cell_count"] == 222

    cases = report["cases"]
    assert [c["case_id"] for c in cases] == EXPECTED_CASE_IDS

    for c_rep, c_raw in zip(cases, raw_json["cases"]):
        assert c_rep["case_id"] == c_raw["id"]
        assert c_rep["model"] == c_raw["model"]
        assert c_rep["tier"] == c_raw["tier"]
        assert c_rep["seed"] == c_raw["seed"]
        assert c_rep["decision_day"] == c_raw["decision_day"]
        assert c_rep["decision_step"] == c_raw["decision_step"]
        assert c_rep["value_at_decision"] == pytest.approx(c_raw["value_at_decision"], abs=1e-4)
        expected_be = 1.0 / (1.0 + c_raw["value_at_decision"])
        assert c_rep["break_even_prob"] == pytest.approx(expected_be, abs=1e-3)
        assert c_rep["top_suspect"] == c_raw["solver"]["top_suspect"]
        assert c_rep["top_prob"] == pytest.approx(c_raw["solver"]["top_prob"], abs=1e-4)
        assert c_rep["recommended_call"] == c_raw["solver"]["recommended_call"]
        assert c_rep["solver_ev"] == pytest.approx(c_raw["solver"]["final_score"], abs=1e-4)
        assert len(c_rep["thinking_levels"]) == len(c_raw["thinking_levels"]) >= 2
        assert len(c_rep["cross_model_carbon"]) == len(c_raw["cross_model_carbon"]) >= 1


def test_casebook_scoreboard_benchmarks_and_monotonic_ladder_match_vm_e2e():
    report = outthink_casebook.build_casebook_report(ROOT)
    bench = report["benchmarks"]
    assert bench["cases_played"] == 12
    assert bench["monotonic_mean_score"] is True
    assert (
        bench["ladder_progression"]
        == "minimal -0.525 -> low -0.2367 -> medium +0.307 -> high +0.6127 -> xhigh +0.705"
    )

    by_id = bench["strategies_by_id"]

    opt = by_id["optimal_judge"]
    assert opt["score_sum"] == pytest.approx(7.8, abs=1e-4)
    assert opt["mean_score"] == pytest.approx(0.65, abs=1e-4)
    assert opt["right_count"] == 12
    assert opt["optimal_count"] == 12
    assert opt["cost_usd"] == 0.0

    slv = by_id["bayesian_solver"]
    assert slv["score_sum"] == pytest.approx(7.9, abs=1e-4)
    assert slv["mean_score"] == pytest.approx(0.6583, abs=1e-4)
    assert slv["right_count"] == 12
    assert slv["optimal_count"] == 12

    hold = by_id["always_hold_fire"]
    assert hold["score_sum"] == pytest.approx(7.42, abs=1e-4)
    assert hold["mean_score"] == pytest.approx(0.6183, abs=1e-4)
    assert hold["right_count"] == 8
    assert hold["optimal_count"] == 8

    mole_now = by_id["always_accuse_mole"]
    assert mole_now["score_sum"] == pytest.approx(7.98, abs=1e-4)
    assert mole_now["mean_score"] == pytest.approx(0.665, abs=1e-4)
    assert mole_now["right_count"] == 12
    assert mole_now["optimal_count"] == 4

    opp = by_id["opposite_of_solver"]
    assert opp["score_sum"] == pytest.approx(-2.49, abs=1e-4)
    assert opp["mean_score"] == pytest.approx(-0.2075, abs=1e-4)
    assert opp["right_count"] == 2
    assert opp["optimal_count"] == 0

    wrong = by_id["wrong_accusation"]
    assert wrong["score_sum"] == pytest.approx(-12.0, abs=1e-4)
    assert wrong["mean_score"] == pytest.approx(-1.0, abs=1e-4)
    assert wrong["right_count"] == 0
    assert wrong["optimal_count"] == 0

    expected_levels = {
        "minimal": (4, -2.1, -0.525, 1, 0.25, 0.324639, 0, 3),
        "low": (12, -2.84, -0.2367, 6, 0.5, 3.863664, 37548, 11),
        "medium": (10, 3.07, 0.307, 8, 0.8, 3.454475, 157746, 6),
        "high": (11, 6.74, 0.6127, 10, 0.9091, 5.826949, 276139, 3),
        "xhigh": (2, 1.41, 0.705, 2, 1.0, 1.810582, 110471, 1),
    }
    by_lv = bench["thinking_ladder_by_level"]
    for lv_key, (cnt, s_sum, m_score, right, acc, cost, tok, outscored) in expected_levels.items():
        row = by_lv[lv_key]
        assert row["count"] == cnt
        assert row["score_sum"] == pytest.approx(s_sum, abs=1e-4)
        assert row["mean_score"] == pytest.approx(m_score, abs=1e-4)
        assert row["right_count"] == right
        assert row["accuracy"] == pytest.approx(acc, abs=1e-4)
        assert row["total_cost_usd"] == pytest.approx(cost, abs=1e-5)
        assert row["total_thinking_tokens"] == tok
        assert row["judge_outscored_count"] == outscored


def test_casebook_markdown_tables_and_judge_facing_numbers():
    md = DOC_PATH.read_text(encoding="utf-8")
    assert md.startswith(f"{H1} Out-Think Gemini: Casebook and Scoreboard Provenance\n")

    for req_token in (
        "550 recorded ladder episodes",
        "$262.7061",
        "39 paired `thinking_level` trajectories",
        "12 `cross_model_carbon` case comparisons",
        "**Optimal Judge** | `+7.80`",
        "**Bayesian Solver** | `+7.90`",
        "**Always-Hold-Fire** | `+7.42`",
        "**Opposite-of-Solver** | `-2.49`",
        "**Wrong-Accusation** | `-12.00`",
        "minimal -0.525 -> low -0.2367 -> medium +0.307 -> high +0.6127 -> xhigh +0.705",
    ):
        assert req_token in md

    case_rows = _extract_table_data_rows(
        md, f"{H2} 3. Playable 12-Case Decision Threshold and EV Master Table"
    )
    assert len(case_rows) == 12
    for cid, row_line in zip(EXPECTED_CASE_IDS, case_rows):
        assert f"| `{cid}` |" in row_line

    level_rows = _extract_table_data_rows(
        md, f"{H2} 4. Per-Level Trajectory Provenance Table (All 39 Paired Runs)"
    )
    assert len(level_rows) == 39

    carbon_rows = _extract_table_data_rows(
        md, f"{H2} 5. Cross-Model `gemini-4-carbon` Reference Strips (12 Cases, 23 Runs)"
    )
    assert len(carbon_rows) == 23
    for cid in EXPECTED_CASE_IDS:
        assert any(f"| `{cid}` |" in r for r in carbon_rows)


def test_cli_root_json_write_doc_and_tamper_detection(tmp_path: Path, capsys):
    tmp_json = tmp_path / "results" / "gemini" / "out_think_gemini.json"
    tmp_js = tmp_path / "demo" / "out-think-gemini" / "cases.js"
    tmp_doc = tmp_path / "docs" / "demo" / "CASEBOOK.md"
    tmp_json.parent.mkdir(parents=True, exist_ok=True)
    tmp_js.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(JSON_PATH, tmp_json)
    shutil.copyfile(CASES_JS_PATH, tmp_js)

    rc_missing = outthink_casebook.main(["--root", str(tmp_path), "--check"])
    err_missing = capsys.readouterr().err
    assert rc_missing != 0
    assert "missing casebook doc" in err_missing

    rc_write = outthink_casebook.main(["--root", str(tmp_path), "--write-doc"])
    out_write = capsys.readouterr().out
    assert rc_write == 0
    assert "Wrote" in out_write
    assert tmp_doc.read_text(encoding="utf-8") == DOC_PATH.read_text(encoding="utf-8")

    rc_ok = outthink_casebook.main(["--root", str(tmp_path), "--check"])
    out_ok = capsys.readouterr().out
    assert rc_ok == 0
    assert "OK:" in out_ok

    custom_doc = tmp_path / "custom_casebook.md"
    assert outthink_casebook.main(["--root", str(tmp_path), "--write-doc", str(custom_doc)]) == 0
    capsys.readouterr()
    assert outthink_casebook.main(["--root", str(tmp_path), "--check", str(custom_doc)]) == 0
    capsys.readouterr()

    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    clean_env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "canary.gemini.outthink_casebook",
            "--root",
            str(tmp_path),
            "--json",
            "--check",
        ],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    parsed_json = json.loads(proc.stdout)
    assert parsed_json["verified"] is True
    assert parsed_json["provenance"]["case_count"] == 12
    assert parsed_json["provenance"]["level_run_count"] == 39

    clean_doc_txt = tmp_doc.read_text(encoding="utf-8")
    tmp_doc.write_text(clean_doc_txt.replace("+7.80", "+7.99", 1), encoding="utf-8")
    rc_drift = outthink_casebook.main(["--root", str(tmp_path), "--check"])
    err_drift = capsys.readouterr().err
    assert rc_drift != 0
    assert "out of date" in err_drift

    tmp_doc.write_text(clean_doc_txt + EM_DASH, encoding="utf-8")
    rc_dash = outthink_casebook.main(["--root", str(tmp_path), "--check"])
    err_dash = capsys.readouterr().err
    assert rc_dash != 0
    assert "dash" in err_dash

    tmp_doc.write_text(clean_doc_txt, encoding="utf-8")
    tampered_payload = json.loads(tmp_json.read_text(encoding="utf-8"))
    tampered_payload["cases"][0]["value_at_decision"] = 0.65
    tmp_json.write_text(json.dumps(tampered_payload, indent=2) + "\n", encoding="utf-8")
    rc_mismatch = outthink_casebook.main(["--root", str(tmp_path), "--check"])
    err_mismatch = capsys.readouterr().err
    assert rc_mismatch != 0
    assert "differ" in err_mismatch


def test_hygiene_zero_comments_dashes_genai_imports_and_protected_paths():
    self_path = Path(__file__).resolve()
    py_files = (MODULE_PATH, self_path)
    all_files = (MODULE_PATH, DOC_PATH, self_path)

    forbidden_modules = ("genai", "google", "httpx", "requests", "urllib")

    for pf in py_files:
        src = pf.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"hash character found in {pf}"
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
        ]
        assert comments == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for mod_tok in forbidden_modules:
                        assert mod_tok not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for mod_tok in forbidden_modules:
                    assert mod_tok not in node.module

    for fpath in all_files:
        txt = fpath.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash found in {fpath}"
        assert EN_DASH not in txt, f"en dash found in {fpath}"
        assert FORBIDDEN_NET not in txt, f"forbidden network token found in {fpath}"
        assert HTML_COMMENT_OPEN not in txt, f"HTML comment found in {fpath}"

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    checked = {f.relative_to(ROOT).as_posix() for f in all_files}
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked.add(entry)
    diff_proc = subprocess.run(
        ["git", "diff", "--name-only", "origin/justSilas..HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if diff_proc.returncode == 0:
        for rel in diff_proc.stdout.splitlines():
            if rel.strip():
                checked.add(rel.strip())
    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected dir touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
