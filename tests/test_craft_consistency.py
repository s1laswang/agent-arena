from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_craft_consistency.py"
H = chr(35)


def _load_craft_module():
    spec = importlib.util.spec_from_file_location("check_craft_consistency", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


craft = _load_craft_module()


def _init_git_repo(
    repo: Path,
    files: dict[str, str | bytes],
    gitignore: str = "results/latest/\n*.log\n",
) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _synthetic_headline_files() -> tuple[list[dict], dict, dict, dict, dict[str, str]]:
    paired = [
        {
            "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "medium",
            "n": 30,
            "mean": 0.713,
            "ci": 0.042,
            "solver_same_seeds": 0.645,
            "ratio": 1.1054,
            "ratio_lo": 0.9933,
            "ratio_hi": 1.2698,
            "post_expected_ratio": 1.0106,
            "post_expected_lo": 0.8532,
            "post_expected_hi": 1.1864,
        },
        {
            "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "mean": 0.3223333333333333,
            "ci": 0.198895372190826,
            "solver_same_seeds": 0.499,
            "ratio": 0.6459585838343352,
            "ratio_lo": 0.23819591261451728,
            "ratio_hi": 0.9833962264150943,
            "post_expected_ratio": 0.7201029448090318,
            "post_expected_lo": 0.5173025973474353,
            "post_expected_hi": 0.9120622753852026,
        },
        {
            "label": "OpenCode, alternative (NOT the headline)",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "mean": 0.2786666666666667,
            "ci": 0.1804,
            "solver_same_seeds": 0.499,
            "ratio": 0.5585,
            "ratio_lo": 0.1893,
            "ratio_hi": 0.8658,
            "post_expected_ratio": 0.5546,
            "post_expected_lo": 0.3429,
            "post_expected_hi": 0.7713,
        },
        {
            "label": "in-process gemini-4-carbon",
            "group": "v1.4/inproc-gemini-4-carbon",
            "agent": "gemini:gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "mean": 0.473,
            "ci": 0.1178,
            "solver_same_seeds": 0.499,
            "ratio": 0.9479,
            "ratio_lo": 0.6221,
            "ratio_hi": 1.40,
            "post_expected_ratio": 0.8433,
            "post_expected_lo": 0.6499,
            "post_expected_hi": 1.0578,
        },
        {
            "label": "reference solver",
            "group": "v1.4/reference",
            "agent": "solver",
            "tier": "hard",
            "n": 30,
            "mean": 0.499,
            "ci": 0.11929749210686914,
            "solver_same_seeds": 0.499,
            "ratio": 1.0,
            "ratio_lo": float("nan"),
            "ratio_hi": float("nan"),
        },
    ]
    fa = {
        "summary": {
            "opencode": {
                "n": 30,
                "score": 0.3223333333333333,
                "canaries": 8.466666666666667,
                "accuse_day": 13.172413793103448,
                "wrong": 4,
            },
            "solver": {
                "n": 30,
                "score": 0.499,
                "canaries": 14.133333333333333,
                "accuse_day": 10.6,
                "wrong": 1,
            },
            "gap": {
                "raw_gap": 5.3,
                "la_gap": 4.189683952467997,
            },
        }
    }
    oracle = {
        "rows": [
            {
                "agent": "solver",
                "tier": "hard",
                "builds": 200,
                "k10": {
                    "mean": 0.56938,
                    "sd": 0.09446892339514189,
                    "p5": 0.393,
                    "p95": 0.67805,
                },
            }
        ]
    }
    gd1 = {"agent": "guess_day1", "tier": "hard", "builds": 300, "mean": -0.9528333333333333}
    docs = {
        "README.md": (
            f"{H} Canary\n"
            "| solver | +0.499 +/- 0.119 | 100% | 30 |\n"
            "| opencode | +0.322 +/- 0.199 | 65% [24%, 98%]; luck-adjusted 72% [52%, 91%] | 30 |\n"
            "In-process reaches 95% [62%, 140%] on hard, OpenCode reaches 111% on medium, guess_day1 averages \u22120.95.\n"
            "Oracle 10-task hard range +0.39 to +0.68 (mean +0.569, sd 0.094).\n"
        ),
        "docs/reports/gap.md": (
            f"{H} Gap\n"
            "| OpenCode | hard | 30 | 65% [24%, 98%] | 72% [52%, 91%] |\n"
            "| OpenCode | medium | 30 | 111% [99%, 127%] | 101% [85%, 119%] |\n"
            "| in-process | hard | 30 | 95% [62%, 140%] | 84% [65%, 106%] |\n"
        ),
        "docs/reports/failure_analysis_v1.4.md": (
            f"{H} Failure analysis\n"
            "Mean score 0.322 vs solver 0.499. Canaries 8.5 vs 14.1, accuse day 13.2 vs 10.6, "
            "wrong 4, raw gap 5.30, luck-adjusted gap 4.19.\n"
        ),
    }
    return paired, fa, oracle, gd1, docs


def _write_headline_repo(
    repo: Path,
    paired: list[dict],
    fa: dict,
    oracle: dict,
    gd1: dict,
    docs: dict[str, str],
) -> None:
    all_files: dict[str, str] = {
        "data/runs/committed/v1.4/paired_table_gemini.json": json.dumps(paired),
        "results/failure_analysis_v1.4.json": json.dumps(fa),
        "results/oracle_range_v1.4.json": json.dumps(oracle),
        "results/solver_range/guess_day1_hard_judge40.json": json.dumps(gd1),
        **docs,
    }
    for rel, content in all_files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _synthetic_judge_table(
    stop_early_hard_score: str = "+0.000 +/- 0.000",
    reported_solver_cell: str = "\u2013",
) -> str:
    return "\n".join(
        [
            f"{H} Canary judge table",
            "",
            f"{H}{H} medium (headline)",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
            "| solver | reference | 40 | 0 | +0.609 +/- 0.092 | 0.82 | 33/40 | 7.5 | 1.00 | \u2013 | ref |",
            "| stop_early | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "| do_nothing | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
            f"| opencode:google/gemini-4-carbon | reported | 30 | 0 | +0.713 +/- 0.042 | 1.00 | 30/30 | 8.0 | {reported_solver_cell} | \u2013 | replayed |",
            "| stop_early | reported | 20 | 0 | -1.000 +/- 0.000 | 0.00 | 20/20 | 1.0 | \u2013 | \u2013 | historical |",
            "",
            f"{H}{H} hard (headline)",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
            "| solver | reference | 40 | 0 | +0.655 +/- 0.032 | 1.00 | 40/40 | 7.9 | 1.00 | \u2013 | ref |",
            f"| stop_early | baseline | 40 | 0 | {stop_early_hard_score} | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "| do_nothing | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
            f"| opencode:google/gemini-4-carbon | reported | 30 | 0 | +0.322 +/- 0.199 | 0.83 | 29/30 | 13.2 | {reported_solver_cell} | \u2013 | replayed |",
            "",
            f"{H}{H} easy (sanity tier)",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
            "| solver | reference | 40 | 0 | +0.791 +/- 0.034 | 1.00 | 40/40 | 4.8 | 1.00 | \u2013 | ref |",
            "| stop_early | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "| do_nothing | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 | 0/40 | \u2013 | 0.00 | \u2013 | base |",
            "",
        ]
    )


def _base_results_files() -> dict[str, str]:
    files: dict[str, str] = {
        "results/judge_table.md": _synthetic_judge_table(),
        "results/history/regret_gpt-5.5-v1.3.md": "archived\n",
        "results/regret_opencode-gemini-4-carbon-v1.4.md": "current v1.4\n",
    }
    for agent in ("solver", "guess_day1"):
        for tier in ("easy", "medium", "hard"):
            files[f"results/solver_range/{agent}_{tier}_judge40.json"] = json.dumps(
                {"agent": agent, "tier": tier, "builds": 300, "mean": 0.5}
            )
    return files


def test_real_repo_passes_craft_consistency(capsys):
    rc = craft.main(["--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 10.0
    by_name = {r["name"]: r for r in payload["results"]}
    assert set(by_name) == {
        "Internal Markdown Links",
        "Headline Number Provenance",
        "Stale Gap-Claim Guard",
        "Results & Judge Table Hygiene",
    }
    for check_name, result in by_name.items():
        assert result["status"] != "FAIL", f"{check_name} failed: {result['details']}"

    rc_text = craft.main(["--root", str(ROOT)])
    text_out = capsys.readouterr().out
    assert rc_text == 0
    assert "SUMMARY:" in text_out


def test_markdown_links_pass_warn_and_fail(tmp_path):
    clean_repo = tmp_path / "links_clean"
    _init_git_repo(
        clean_repo,
        {
            "README.md": (
                f"{H} Readme\n"
                f"See [contract](docs/CONTRACT.md{H}rules \"Contract\"), [ext](https://example.com), "
                f"[mail](mailto:test@example.com), [anchor]({H}top).\n"
                "Inline `[fake](missing_inline.md)` is ignored.\n"
                "```markdown\n"
                "[fenced](missing_fenced.md)\n"
                "```\n"
            ),
            "docs/CONTRACT.md": f"{H} Contract\nBack to [readme](../README.md).\n",
        },
    )
    res_pass = craft.check_markdown_links(clean_repo)
    assert res_pass.status == "PASS"

    warn_repo = tmp_path / "links_warn"
    _init_git_repo(
        warn_repo,
        {
            "README.md": "See [exploits](docs/EXPLOITS.md).\n",
            "docs/EXPLOITS.md": "Log at [hunt](../results/anticheat/hunt.log).\n",
        },
        gitignore="results/latest/\n*.log\n",
    )
    res_warn = craft.check_markdown_links(warn_repo)
    assert res_warn.status == "WARN"
    assert any("hunt.log" in d for d in res_warn.details)

    fail_repo = tmp_path / "links_fail"
    _init_git_repo(
        fail_repo,
        {
            "README.md": "Broken [target](docs/does_not_exist.md).\n",
        },
    )
    res_fail = craft.check_markdown_links(fail_repo)
    assert res_fail.status == "FAIL"
    assert any("does_not_exist.md" in d for d in res_fail.details)


def test_headline_numbers_pass_and_drift_fails(tmp_path):
    ok_repo = tmp_path / "hl_ok"
    paired, fa, oracle, gd1, docs = _synthetic_headline_files()
    _write_headline_repo(ok_repo, paired, fa, oracle, gd1, docs)
    assert craft.check_headline_numbers(ok_repo).status == "PASS"

    readme_drift = tmp_path / "hl_readme_drift"
    bad_docs = dict(docs)
    bad_docs["README.md"] = docs["README.md"].replace("65%", "58%")
    _write_headline_repo(readme_drift, paired, fa, oracle, gd1, bad_docs)
    res_readme = craft.check_headline_numbers(readme_drift)
    assert res_readme.status == "FAIL"
    assert any("README.md" in d and "65%" in d for d in res_readme.details)

    json_drift = tmp_path / "hl_json_drift"
    bad_paired = copy.deepcopy(paired)
    bad_paired[1]["mean"] = 0.250
    bad_paired[1]["ratio"] = 0.501
    _write_headline_repo(json_drift, bad_paired, fa, oracle, gd1, docs)
    res_json = craft.check_headline_numbers(json_drift)
    assert res_json.status == "FAIL"

    n_drift = tmp_path / "hl_n_drift"
    bad_n_paired = copy.deepcopy(paired)
    bad_n_paired[1]["n"] = 20
    _write_headline_repo(n_drift, bad_n_paired, fa, oracle, gd1, docs)
    res_n = craft.check_headline_numbers(n_drift)
    assert res_n.status == "FAIL"
    assert any("expected 30" in d for d in res_n.details)

    wt_ok = tmp_path / "hl_wt_ok"
    wt_docs = dict(docs)
    wt_docs["docs/JUDGE-WALKTHROUGH.md"] = "Headline: 65% raw, 72% luck-adjusted (+0.322 vs +0.499).\n"
    _write_headline_repo(wt_ok, paired, fa, oracle, gd1, wt_docs)
    assert craft.check_headline_numbers(wt_ok).status == "PASS"

    wt_bad = tmp_path / "hl_wt_bad"
    wt_bad_docs = dict(docs)
    wt_bad_docs["docs/JUDGE-WALKTHROUGH.md"] = "Headline: 50% raw, 72% luck-adjusted (+0.322 vs +0.499).\n"
    _write_headline_repo(wt_bad, paired, fa, oracle, gd1, wt_bad_docs)
    res_wt = craft.check_headline_numbers(wt_bad)
    assert res_wt.status == "FAIL"
    assert any("JUDGE-WALKTHROUGH.md" in d for d in res_wt.details)

    gap_drift = tmp_path / "hl_gap_drift"
    gap_bad_docs = dict(docs)
    gap_bad_docs["docs/reports/gap.md"] = docs["docs/reports/gap.md"].replace("72% [52%, 91%]", "70% [52%, 91%]")
    _write_headline_repo(gap_drift, paired, fa, oracle, gd1, gap_bad_docs)
    assert craft.check_headline_numbers(gap_drift).status == "FAIL"

    fa_drift = tmp_path / "hl_fa_drift"
    fa_bad_docs = dict(docs)
    fa_bad_docs["docs/reports/failure_analysis_v1.4.md"] = docs["docs/reports/failure_analysis_v1.4.md"].replace("5.30", "4.80")
    _write_headline_repo(fa_drift, paired, fa, oracle, gd1, fa_bad_docs)
    assert craft.check_headline_numbers(fa_drift).status == "FAIL"


def test_stale_gap_claims_guard(tmp_path):
    clean_repo = tmp_path / "gap_clean"
    _init_git_repo(
        clean_repo,
        {
            "README.md": "65% of solver on hard.\n",
            "docs/reports/gap.md": "Demonstrated gap on hard.\n",
            "docs/HISTORY.md": "Earlier note: v1.4 frontier gap: not established.\n",
            "docs/PLAN-95.md": "1. A v1.4 frontier gap is not established.\n",
            "docs/DEMO.md": "Old output said v1.4 frontier gap: not established.\n",
            "results/fresh_clone/macos.log.txt": "v1.4 frontier gap: not established.\n",
        },
    )
    assert craft.check_stale_gap_claims(clean_repo).status == "PASS"

    secondary_warn = tmp_path / "gap_warn"
    _init_git_repo(
        secondary_warn,
        {
            "README.md": "65% of solver on hard.\n",
            "harbor/README.md": "6-task demo. Gap not established.\n",
        },
    )
    res_warn = craft.check_stale_gap_claims(secondary_warn)
    assert res_warn.status == "WARN"
    assert any("harbor/README.md" in d for d in res_warn.details)

    readme_fail = tmp_path / "gap_fail_readme"
    _init_git_repo(
        readme_fail,
        {
            "README.md": "Status: v1.4 frontier gap: not established.\n",
            "docs/reports/gap.md": "Clean.\n",
        },
    )
    res_fail_readme = craft.check_stale_gap_claims(readme_fail)
    assert res_fail_readme.status == "FAIL"
    assert any("README.md" in d for d in res_fail_readme.details)

    gap_doc_fail = tmp_path / "gap_fail_doc"
    _init_git_repo(
        gap_doc_fail,
        {
            "README.md": "Clean.\n",
            "docs/reports/gap.md": "Note: v1.4 frontier gap: not established.\n",
        },
    )
    res_fail_doc = craft.check_stale_gap_claims(gap_doc_fail)
    assert res_fail_doc.status == "FAIL"
    assert any("docs/reports/gap.md" in d for d in res_fail_doc.details)


def test_results_hygiene_pass_and_violations(tmp_path):
    clean_repo = tmp_path / "res_clean"
    _init_git_repo(clean_repo, _base_results_files())
    assert craft.check_results_hygiene(clean_repo).status == "PASS"

    legacy_repo = tmp_path / "res_legacy"
    legacy_files = _base_results_files()
    legacy_files["results/regret_gpt-5.5-v1.3.md"] = "misplaced legacy file\n"
    _init_git_repo(legacy_repo, legacy_files)
    res_legacy = craft.check_results_hygiene(legacy_repo)
    assert res_legacy.status == "FAIL"
    assert any("regret_gpt-5.5-v1.3.md" in d for d in res_legacy.details)

    tracked_latest_repo = tmp_path / "res_tracked_latest"
    _init_git_repo(tracked_latest_repo, _base_results_files())
    latest_file = tracked_latest_repo / "results" / "latest" / "foo.txt"
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.write_text("tracked accidentally\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "results/latest/foo.txt"], cwd=tracked_latest_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "track latest"], cwd=tracked_latest_repo, check=True)
    res_tracked = craft.check_results_hygiene(tracked_latest_repo)
    assert res_tracked.status == "FAIL"
    assert any("results/latest/foo.txt" in d for d in res_tracked.details)

    bad_stop_repo = tmp_path / "res_bad_stop_early"
    bad_stop_files = _base_results_files()
    bad_stop_files["results/judge_table.md"] = _synthetic_judge_table(stop_early_hard_score="-1.000 +/- 0.000")
    _init_git_repo(bad_stop_repo, bad_stop_files)
    res_stop = craft.check_results_hygiene(bad_stop_repo)
    assert res_stop.status == "FAIL"
    assert any("stop_early" in d and "hard" in d for d in res_stop.details)

    bad_ratio_repo = tmp_path / "res_bad_reported_ratio"
    bad_ratio_files = _base_results_files()
    bad_ratio_files["results/judge_table.md"] = _synthetic_judge_table(reported_solver_cell="0.65")
    _init_git_repo(bad_ratio_repo, bad_ratio_files)
    res_ratio = craft.check_results_hygiene(bad_ratio_repo)
    assert res_ratio.status == "FAIL"
    assert any("reported row" in d and "0.65" in d for d in res_ratio.details)

    unignored_latest = tmp_path / "res_unignored_latest"
    _init_git_repo(unignored_latest, _base_results_files(), gitignore="*.log\n")
    res_unig = craft.check_results_hygiene(unignored_latest)
    assert res_unig.status == "FAIL"
    assert any("not gitignored" in d for d in res_unig.details)

    low_builds_repo = tmp_path / "res_low_builds"
    low_files = _base_results_files()
    low_files["results/solver_range/solver_hard_judge40.json"] = json.dumps(
        {"agent": "solver", "tier": "hard", "builds": 50, "mean": 0.56}
    )
    _init_git_repo(low_builds_repo, low_files)
    res_builds = craft.check_results_hygiene(low_builds_repo)
    assert res_builds.status == "FAIL"
    assert any("builds >= 100" in d for d in res_builds.details)


def test_cli_exits_nonzero_on_failure(tmp_path, capsys):
    broken_repo = tmp_path / "cli_fail"
    _init_git_repo(broken_repo, {"README.md": "Broken [link](missing.md).\n"})
    rc = craft.main(["--root", str(broken_repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_gitless_gitignore_fallback_without_dot_git(tmp_path):
    gitless_warn = tmp_path / "gitless_warn"
    gitless_warn.mkdir(parents=True, exist_ok=True)
    (gitless_warn / ".gitignore").write_text(
        f"{H} comment line\nresults/latest/\n*.log\n!keep.log\n",
        encoding="utf-8",
    )
    (gitless_warn / "README.md").write_text("See [exploits](docs/EXPLOITS.md).\n", encoding="utf-8")
    (gitless_warn / "docs").mkdir(parents=True, exist_ok=True)
    (gitless_warn / "docs" / "EXPLOITS.md").write_text(
        "Ignored log [hunt](../results/anticheat/hunt.log) and [latest](../results/latest/judge_table.md).\n",
        encoding="utf-8",
    )
    assert not (gitless_warn / ".git").exists()

    res_links = craft.check_markdown_links(gitless_warn)
    assert res_links.status == "WARN"
    assert any("hunt.log" in d for d in res_links.details)
    assert any("results/latest/judge_table.md" in d for d in res_links.details)

    gitless_negated = tmp_path / "gitless_negated"
    gitless_negated.mkdir(parents=True, exist_ok=True)
    (gitless_negated / ".gitignore").write_text("*.log\n!keep.log\n", encoding="utf-8")
    (gitless_negated / "README.md").write_text(
        "Unignored missing [keep](keep.log) must fail.\n",
        encoding="utf-8",
    )
    res_negated = craft.check_markdown_links(gitless_negated)
    assert res_negated.status == "FAIL"
    assert any("keep.log" in d for d in res_negated.details)

    gitless_res = tmp_path / "gitless_res"
    gitless_res.mkdir(parents=True, exist_ok=True)
    (gitless_res / ".gitignore").write_text("*.log\n", encoding="utf-8")
    for rel, content in _base_results_files().items():
        p = gitless_res / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    res_hyg_fail = craft.check_results_hygiene(gitless_res)
    assert res_hyg_fail.status == "FAIL"
    assert any("not gitignored" in d for d in res_hyg_fail.details)

    (gitless_res / ".gitignore").write_text("results/latest/\n*.log\n", encoding="utf-8")
    res_hyg_pass = craft.check_results_hygiene(gitless_res)
    assert res_hyg_pass.status == "PASS"

    for py_path in (SCRIPT_PATH, Path(__file__).resolve()):
        raw = py_path.read_text(encoding="utf-8")
        assert H not in raw, f"unexpected hash character in {py_path.name}"
        assert chr(0x2014) not in raw, f"unexpected em dash in {py_path.name}"
        assert chr(0x2013) not in raw, f"unexpected en dash in {py_path.name}"


def _synthetic_pooled_rows() -> list[dict]:
    return [
        {
            "label": "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
            "group": "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 32,
            "mean": 0.34875,
            "ci": 0.18975526661907804,
            "solver_same_seeds": 0.51375,
        },
        {
            "label": "reference solver",
            "group": "v1.4/reference",
            "agent": "solver",
            "tier": "hard",
            "n": 60,
            "mean": 0.4985,
            "ci": 0.09740111755875758,
            "solver_same_seeds": 0.4985,
        },
    ]


def _synthetic_exploits_json() -> dict:
    harbor_items = [{"kind": "trial", "consistent": True} for _ in range(80)] + [
        {"kind": "job", "consistent": True} for _ in range(18)
    ]
    rows_items = [{"probe": f"probe_{i}", "blocked": True} for i in range(99)]
    return {
        "all_blocked": True,
        "harbor_all_consistent": True,
        "replay_all_consistent": True,
        "replay_counts": {
            "consistent": 1021,
            "n": 1031,
            "not_replayable": 10,
            "replayed": 1021,
            "step_mismatches": 0,
            "steps": 51814,
        },
        "harbor": harbor_items,
        "rows": rows_items,
    }


def test_markdown_links_scans_judge_quickstart_and_handoff(tmp_path):
    clean_repo = tmp_path / "root_docs_clean"
    _init_git_repo(
        clean_repo,
        {
            "README.md": f"{H} Canary\nSee [quickstart](JUDGE_QUICKSTART.md) and [handoff](HANDOFF.md).\n",
            "JUDGE_QUICKSTART.md": f"{H} Quickstart\nSee [contract](docs/CONTRACT.md).\n",
            "HANDOFF.md": f"{H} Handoff\nSee [readme](README.md).\n",
            "docs/CONTRACT.md": f"{H} Contract\nClean.\n",
        },
    )
    collected_rels = [p.relative_to(clean_repo.resolve()).as_posix() for p in craft._collect_markdown_files(clean_repo)]
    assert "JUDGE_QUICKSTART.md" in collected_rels
    assert "HANDOFF.md" in collected_rels
    assert craft.check_markdown_links(clean_repo).status == "PASS"

    qs_fail = tmp_path / "qs_broken_link"
    _init_git_repo(
        qs_fail,
        {
            "README.md": f"{H} Canary\n",
            "JUDGE_QUICKSTART.md": "Broken [walkthrough](docs/missing_walkthrough.md).\n",
        },
    )
    res_qs = craft.check_markdown_links(qs_fail)
    assert res_qs.status == "FAIL"
    assert any("JUDGE_QUICKSTART.md" in d and "missing_walkthrough.md" in d for d in res_qs.details)

    ho_fail = tmp_path / "ho_broken_link"
    _init_git_repo(
        ho_fail,
        {
            "README.md": f"{H} Canary\n",
            "HANDOFF.md": "Broken [patch](docs/missing_patch.md).\n",
        },
    )
    res_ho = craft.check_markdown_links(ho_fail)
    assert res_ho.status == "FAIL"
    assert any("HANDOFF.md" in d and "missing_patch.md" in d for d in res_ho.details)


def test_headline_optional_judge_docs_and_panel_fix_a_honesty(tmp_path):
    paired, fa, oracle, gd1, base_docs = _synthetic_headline_files()
    opt_docs = {
        **base_docs,
        "docs/JUDGE-WALKTHROUGH.md": "Walkthrough: +0.322 vs +0.499, 65% raw, 72% luck-adjusted. Bar is not met.\n",
        "JUDGE_QUICKSTART.md": (
            "Quickstart: locked dev seeds 0-29 (post-hoc lock), +0.322 +/- 0.199 vs +0.499 +/- 0.119, "
            "65% [24%, 98%] raw, 72% [52%, 91%] luck-adjusted.\n"
        ),
        "docs/REPRODUCIBILITY.md": (
            "Reproducibility: HEADLINE +0.322 +/- 0.199 vs +0.499, 65% [24%, 98%], luck-adjusted 72% [52%, 91%]. "
            "Commit cf394894 pre-registers gpt-5.5 on hard seeds 0-29.\n"
        ),
        "docs/PEER-REVIEW-QA.md": (
            "Were dev seeds 0-29 pre-registered? No, post-hoc lock, not pre-registered. "
            "Scores: +0.322 vs +0.499, 65% raw, 72% luck-adjusted. The tiebreaker bar is NOT met.\n"
        ),
        "docs/SUBMISSION.md": (
            "Submission: 72% [52%, 91%] luck-adjusted and 65% [24%, 98%] raw; 0.322 vs 0.499. "
            "No held-out gain over the base model. We do not claim a tiebreak gain.\n"
        ),
    }

    ok_repo = tmp_path / "opt_hl_ok"
    _write_headline_repo(ok_repo, paired, fa, oracle, gd1, opt_docs)
    res_ok = craft.check_headline_numbers(ok_repo)
    assert res_ok.status == "PASS", res_ok.details
    assert "8 doc(s)" in res_ok.summary

    for idx, target_doc in enumerate(
        ("JUDGE_QUICKSTART.md", "docs/REPRODUCIBILITY.md", "docs/PEER-REVIEW-QA.md", "docs/SUBMISSION.md")
    ):
        drift_raw = tmp_path / f"opt_drift_raw_{idx}"
        bad = dict(opt_docs)
        bad[target_doc] = opt_docs[target_doc].replace("65%", "59%")
        _write_headline_repo(drift_raw, paired, fa, oracle, gd1, bad)
        res = craft.check_headline_numbers(drift_raw)
        assert res.status == "FAIL"
        assert any(target_doc in d and "65%" in d for d in res.details)

        drift_mean = tmp_path / f"opt_drift_mean_{idx}"
        bad_m = dict(opt_docs)
        bad_m[target_doc] = opt_docs[target_doc].replace("+0.322", "-0.322").replace("0.322", "-0.322").replace("--", "-")
        _write_headline_repo(drift_mean, paired, fa, oracle, gd1, bad_m)
        res_m = craft.check_headline_numbers(drift_mean)
        assert res_m.status == "FAIL"
        assert any(target_doc in d and "0.322" in d for d in res_m.details)

    false_prereg_cases = [
        ("README.md", "\nThe primary seed set was pre-registered before any run.\n"),
        ("JUDGE_QUICKSTART.md", "\nEvaluated on pre-registered dev seeds 0-29.\n"),
        ("docs/PEER-REVIEW-QA.md", "\nDev seeds 0-29 were pre-registered.\n"),
        ("docs/SUBMISSION.md", "\nOur n=30 headline was pre-registered.\n"),
    ]
    for idx, (doc_rel, bad_line) in enumerate(false_prereg_cases):
        bad_repo = tmp_path / f"false_prereg_{idx}"
        bad = dict(opt_docs)
        bad[doc_rel] = opt_docs[doc_rel] + bad_line
        _write_headline_repo(bad_repo, paired, fa, oracle, gd1, bad)
        res_p = craft.check_headline_numbers(bad_repo)
        assert res_p.status == "FAIL"
        assert any(doc_rel in d and "pre-registered" in d for d in res_p.details)

    false_bar_cases = [
        ("README.md", "\nThe WS4 tiebreak bar (above base) is met.\n"),
        ("docs/PEER-REVIEW-QA.md", "\nAnswer: the tiebreaker bar is clearly met.\n"),
        ("docs/SUBMISSION.md", "\nWe claim a tiebreak gain on held-out seeds.\n"),
        ("docs/REPRODUCIBILITY.md", "\nShows held-out reward gain over base.\n"),
    ]
    for idx, (doc_rel, bad_line) in enumerate(false_bar_cases):
        bad_repo = tmp_path / f"false_bar_{idx}"
        bad = dict(opt_docs)
        bad[doc_rel] = opt_docs[doc_rel] + bad_line
        _write_headline_repo(bad_repo, paired, fa, oracle, gd1, bad)
        res_b = craft.check_headline_numbers(bad_repo)
        assert res_b.status == "FAIL"
        assert any(doc_rel in d and "tiebreak bar" in d for d in res_b.details)


def test_headline_pooled_n32_n60_provenance_and_tamper(tmp_path):
    paired, fa, oracle, gd1, base_docs = _synthetic_headline_files()
    pooled_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    pooled_rows = _synthetic_pooled_rows()

    pooled_docs = dict(base_docs)
    pooled_docs["README.md"] = (
        base_docs["README.md"]
        + "Reproduce pools all 32 committed episodes (+0.349 \u00b1 0.190) and solver pools seeds 0-59 (+0.498 \u00b1 0.097, n=60).\n"
    )
    pooled_docs["JUDGE_QUICKSTART.md"] = (
        "Headline +0.322 vs +0.499, 65% raw, 72% luck-adjusted. "
        "Table pools n=32 OpenCode +0.349 +/- 0.190 and n=60 solver +0.498 +/- 0.097.\n"
    )
    pooled_docs["docs/PEER-REVIEW-QA.md"] = (
        "Headline +0.322 vs +0.499, 65% raw, 72% luck-adjusted. "
        "Judge table pools n=32 (+0.349 +/- 0.190) and n=60 (+0.498 +/- 0.097).\n"
    )
    pooled_docs["docs/REPRODUCIBILITY.md"] = (
        "HEADLINE +0.322 vs +0.499, 65% raw, 72% luck-adjusted. "
        "Pooled n=32 reads 0.349 +/- 0.190 and solver n=60 reads 0.498 +/- 0.097.\n"
    )

    def _write_with_pooled(repo: Path, docs_map: dict[str, str], p_rows: list[dict]) -> None:
        _write_headline_repo(repo, paired, fa, oracle, gd1, docs_map)
        pp = repo / pooled_rel
        pp.parent.mkdir(parents=True, exist_ok=True)
        pp.write_text(json.dumps(p_rows), encoding="utf-8")

    ok_repo = tmp_path / "pooled_ok"
    _write_with_pooled(ok_repo, pooled_docs, pooled_rows)
    assert craft.check_headline_numbers(ok_repo).status == "PASS"

    no_repro_pool = tmp_path / "pooled_repro_unmentioned_ok"
    alt_docs = dict(pooled_docs)
    alt_docs["docs/REPRODUCIBILITY.md"] = "HEADLINE +0.322 vs +0.499, 65% raw, 72% luck-adjusted.\n"
    _write_with_pooled(no_repro_pool, alt_docs, pooled_rows)
    assert craft.check_headline_numbers(no_repro_pool).status == "PASS"

    tamper_cases = [
        ("README.md", "+0.349", "+0.341", "0.349"),
        ("JUDGE_QUICKSTART.md", "0.190", "0.210", "0.190"),
        ("docs/PEER-REVIEW-QA.md", "n=60", "n=50", "60"),
        ("docs/REPRODUCIBILITY.md", "0.498", "0.455", "0.498"),
        ("docs/REPRODUCIBILITY.md", "0.097", "0.125", "0.097"),
    ]
    for idx, (doc_rel, old_tok, new_tok, expected_substr) in enumerate(tamper_cases):
        bad_repo = tmp_path / f"pooled_tamper_{idx}"
        bad_docs = dict(pooled_docs)
        bad_docs[doc_rel] = pooled_docs[doc_rel].replace(old_tok, new_tok)
        _write_with_pooled(bad_repo, bad_docs, pooled_rows)
        res = craft.check_headline_numbers(bad_repo)
        assert res.status == "FAIL"
        assert any(doc_rel in d and expected_substr in d for d in res.details)

    bad_json_repo = tmp_path / "pooled_json_bad_n"
    bad_rows = copy.deepcopy(pooled_rows)
    bad_rows[0]["n"] = 30
    _write_with_pooled(bad_json_repo, pooled_docs, bad_rows)
    res_json = craft.check_headline_numbers(bad_json_repo)
    assert res_json.status == "FAIL"
    assert any("expected 32" in d for d in res_json.details)


def test_headline_exploits_json_counts_provenance_and_tamper(tmp_path):
    paired, fa, oracle, gd1, base_docs = _synthetic_headline_files()
    exploits_rel = "results/anticheat/exploits.json"
    exp_obj = _synthetic_exploits_json()

    exp_docs = dict(base_docs)
    exp_docs["docs/REPRODUCIBILITY.md"] = (
        "HEADLINE +0.322 vs +0.499, 65% raw, 72% luck-adjusted. "
        "Replays 1,021 of 1,031 committed episodes across 51,814 tool results; "
        "80/80 Harbor trials, 18/18 job summaries, and 99 anti-cheat rows.\n"
    )
    exp_docs["docs/PEER-REVIEW-QA.md"] = (
        "HEADLINE +0.322 vs +0.499, 65% raw, 72% luck-adjusted. "
        "Replays 1021/1031 episodes (51814 steps), 80 Harbor trials, 18 jobs, 99 battery rows.\n"
    )

    def _write_with_exploits(repo: Path, docs_map: dict[str, str], payload: dict) -> None:
        _write_headline_repo(repo, paired, fa, oracle, gd1, docs_map)
        ep = repo / exploits_rel
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text(json.dumps(payload), encoding="utf-8")

    ok_repo = tmp_path / "exp_ok"
    _write_with_exploits(ok_repo, exp_docs, exp_obj)
    assert craft.check_headline_numbers(ok_repo).status == "PASS"

    tamper_pairs = [
        ("docs/REPRODUCIBILITY.md", "1,021", "989", "1021"),
        ("docs/REPRODUCIBILITY.md", "1,031", "999", "1031"),
        ("docs/REPRODUCIBILITY.md", "51,814", "49,549", "51814"),
        ("docs/REPRODUCIBILITY.md", "80/80", "80,000", "80"),
        ("docs/PEER-REVIEW-QA.md", "18 jobs", "13 jobs", "18"),
        ("docs/PEER-REVIEW-QA.md", "99 battery", "96 battery", "99"),
    ]
    for idx, (doc_rel, old_s, new_s, expected_num) in enumerate(tamper_pairs):
        bad_repo = tmp_path / f"exp_tamper_{idx}"
        bad_docs = dict(exp_docs)
        bad_docs[doc_rel] = exp_docs[doc_rel].replace(old_s, new_s)
        _write_with_exploits(bad_repo, bad_docs, exp_obj)
        res = craft.check_headline_numbers(bad_repo)
        assert res.status == "FAIL"
        assert any(doc_rel in d and expected_num in d for d in res.details)

    unblocked_repo = tmp_path / "exp_unblocked"
    bad_payload = copy.deepcopy(exp_obj)
    bad_payload["all_blocked"] = False
    _write_with_exploits(unblocked_repo, exp_docs, bad_payload)
    res_unblocked = craft.check_headline_numbers(unblocked_repo)
    assert res_unblocked.status == "FAIL"
    assert any("all_blocked" in d for d in res_unblocked.details)


def test_stale_gap_claims_new_active_docs_and_exempt_meta_audits(tmp_path):
    for required_active in (
        "JUDGE_QUICKSTART.md",
        "docs/REPRODUCIBILITY.md",
        "docs/PEER-REVIEW-QA.md",
        "docs/SUBMISSION.md",
    ):
        assert required_active in craft.ACTIVE_HEADLINE_DOCS
    assert "docs/reports/judge_sim.md" in craft.EXEMPT_GAP_PATTERNS
    assert "docs/reports/number_audit.md" in craft.EXEMPT_GAP_PATTERNS

    exempt_repo = tmp_path / "gap_exempt_meta"
    _init_git_repo(
        exempt_repo,
        {
            "README.md": "65% of solver on hard.\n",
            "JUDGE_QUICKSTART.md": "65% raw, 72% luck-adjusted.\n",
            "docs/REPRODUCIBILITY.md": "Deterministic replay.\n",
            "docs/PEER-REVIEW-QA.md": "All objections answered.\n",
            "docs/SUBMISSION.md": "Main submission.\n",
            "docs/reports/judge_sim.md": "Historical friction item: Gap not established in old README.\n",
            "docs/reports/number_audit.md": "Historical claim: v1.4 frontier gap: not established.\n",
        },
    )
    res_exempt = craft.check_stale_gap_claims(exempt_repo)
    assert res_exempt.status == "PASS", res_exempt.details

    for idx, active_rel in enumerate(
        ("JUDGE_QUICKSTART.md", "docs/REPRODUCIBILITY.md", "docs/PEER-REVIEW-QA.md", "docs/SUBMISSION.md")
    ):
        fail_repo = tmp_path / f"gap_active_fail_{idx}"
        _init_git_repo(
            fail_repo,
            {
                "README.md": "Clean.\n",
                active_rel: "Stale note: gap not established.\n",
            },
        )
        res_fail = craft.check_stale_gap_claims(fail_repo)
        assert res_fail.status == "FAIL"
        assert any(active_rel in d for d in res_fail.details)


def test_results_hygiene_fresh_clone_afterquery_final_and_git_ceiling(tmp_path):
    steps_rel = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt"
    log_rel = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt"
    fc_readme_rel = "results/fresh_clone/README.md"

    good_files = {
        **_base_results_files(),
        steps_rel: "clone exit=0 seconds=3\nreproduce exit=0 seconds=118\ntest_core exit=0 seconds=175\n",
        log_rel: "HEAD short: 1bc3e281\ntag: afterquery-final\n",
        fc_readme_rel: "Linux x86_64 at tag afterquery-final (`1bc3e281`): 118 s reproduce.\n",
    }
    good_repo = tmp_path / "fc_af_good"
    _init_git_repo(good_repo, good_files)
    assert craft.check_results_hygiene(good_repo).status == "PASS"

    nonzero_repo = tmp_path / "fc_af_nonzero"
    bad_step_files = dict(good_files)
    bad_step_files[steps_rel] = "clone exit=0 seconds=3\nreproduce exit=1 seconds=118\n"
    _init_git_repo(nonzero_repo, bad_step_files)
    res_nz = craft.check_results_hygiene(nonzero_repo)
    assert res_nz.status == "FAIL"
    assert any("non-zero exit code 1" in d for d in res_nz.details)

    empty_log_repo = tmp_path / "fc_af_empty_log"
    empty_log_files = dict(good_files)
    empty_log_files[log_rel] = "   \n"
    _init_git_repo(empty_log_repo, empty_log_files)
    res_empty = craft.check_results_hygiene(empty_log_repo)
    assert res_empty.status == "FAIL"
    assert any("empty fresh-clone log" in d for d in res_empty.details)

    missing_sha_repo = tmp_path / "fc_af_missing_sha"
    bad_readme_files = dict(good_files)
    bad_readme_files[fc_readme_rel] = "Linux x86_64 fresh clone at 09e7363 only.\n"
    _init_git_repo(missing_sha_repo, bad_readme_files)
    res_sha = craft.check_results_hygiene(missing_sha_repo)
    assert res_sha.status == "FAIL"
    assert any("1bc3e281" in d for d in res_sha.details)
    assert any("afterquery-final" in d for d in res_sha.details)

    parent_git = tmp_path / "parent_git_repo"
    _init_git_repo(
        parent_git,
        {"README.md": "Parent repo.\n"},
        gitignore="results/latest/\n*.parent_ignored\n",
    )
    nested_gitless = parent_git / "nested_export"
    nested_gitless.mkdir(parents=True, exist_ok=True)
    (nested_gitless / ".gitignore").write_text("*.child_only\n", encoding="utf-8")
    for rel, content in _base_results_files().items():
        p = nested_gitless / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    env_map = craft._git_env(nested_gitless)
    assert env_map["GIT_CEILING_DIRECTORIES"].split(":")[0] == str(nested_gitless.resolve().parent)
    assert craft._git_ls_files(nested_gitless) is None
    assert craft._git_is_ignored(nested_gitless, "foo.parent_ignored") is False
    assert craft._git_is_ignored(nested_gitless, "bar.child_only") is True

    (nested_gitless / ".git").mkdir(parents=True, exist_ok=True)
    assert craft._git_ls_files(nested_gitless) is None
    assert craft._git_is_ignored(nested_gitless, "foo.parent_ignored") is False
    assert craft._git_is_ignored(nested_gitless, "bar.child_only") is True
    assert craft._git_ignored_batch(nested_gitless, ["foo.parent_ignored", "bar.child_only"]) == {"bar.child_only"}
