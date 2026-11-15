from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_doc_hygiene.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_doc_hygiene", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


hygiene = _load_module()


@pytest.fixture()
def clean_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-doc-hygiene-") as tmp_str:
        yield Path(tmp_str)


def _write_files(repo: Path, files: dict[str, str | bytes]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


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
    _write_files(repo, files)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def test_source_files_have_zero_hash_and_zero_em_en_dashes():
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert src.isascii(), f"non-ASCII character in {path.name}"
        assert H not in src, f"unexpected hash character in {path.name}"
        assert chr(0x2014) not in src, f"unexpected em dash in {path.name}"
        assert chr(0x2013) not in src, f"unexpected en dash in {path.name}"


def test_real_repo_passes_cli_and_api(capsys):
    assert hygiene.audit_repo is hygiene.audit_doc_hygiene
    api_results = hygiene.audit_doc_hygiene(ROOT)
    assert len(api_results) == 5
    assert [r.name for r in api_results] == list(hygiene.CHECK_NAMES)
    for item in api_results:
        assert item.status == "PASS", f"{item.name} not PASS: {item.details}"

    rc_json = hygiene.main(["--root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 5.0
    assert len(payload["results"]) == 5
    assert payload["checks"] == payload["results"]
    by_name = {r["name"]: r for r in payload["results"]}
    assert set(by_name) == set(hygiene.CHECK_NAMES)
    assert by_name[hygiene.CHECK_ANCHORS]["status"] == "PASS"
    assert by_name[hygiene.CHECK_IMAGES]["status"] == "PASS"
    assert by_name[hygiene.CHECK_TRACKED_TARGETS]["status"] == "PASS"
    assert by_name[hygiene.CHECK_STALE_PR41]["status"] == "PASS"
    assert by_name[hygiene.CHECK_PORTABILITY_AND_ENCODING]["status"] == "PASS"

    rc_text = hygiene.main(["--root", str(ROOT)])
    text_out = capsys.readouterr().out
    assert rc_text == 0
    assert "5 PASS, 0 WARN, 0 FAIL" in text_out
    assert "SUMMARY:" in text_out


def test_duplicate_heading_anchor_suffixes_pass_and_broken_anchor_fails(clean_tmp: Path, capsys):
    ok_repo = clean_tmp / "anchors_ok"
    _init_git_repo(
        ok_repo,
        {
            "README.md": "\n".join(
                [
                    f"{H} Canary Overview",
                    f"Jump to [first notes]({H}notes), [second notes]({H}notes-1), [third notes]({H}notes-2).",
                    f"Snake and hyphen: [snake]({H}my_snake_var-32-hour-plan).",
                    f"Cross-file: [harbor range](harbor/README.md{H}expected-oracle-range-for-a-judge-rerun).",
                    f"Cross-file dup: [walkthrough second](docs/JUDGE-WALKTHROUGH.md{H}setup-1).",
                    f"Inline `[ignored]({H}does-not-exist)` is ignored.",
                    "```bash",
                    f"{H} fake-heading-in-code-fence",
                    f"[ignored_fenced]({H}missing-in-fence)",
                    "```",
                    f"{H}{H} Notes",
                    "First section.",
                    f"{H}{H} Notes",
                    "Second section.",
                    f"{H}{H} Notes",
                    "Third section.",
                    f"{H}{H} my_snake_var: 32-hour plan!",
                    "Details.",
                ]
            )
            + "\n",
            "JUDGE_QUICKSTART.md": f"{H} Quickstart\nSee [main](README.md{H}canary-overview).\n",
            "docs/JUDGE-WALKTHROUGH.md": "\n".join(
                [
                    f"{H} Walkthrough",
                    f"{H}{H} Setup",
                    "Part A.",
                    f"{H}{H} Setup",
                    "Part B.",
                ]
            )
            + "\n",
            "harbor/README.md": f"{H} Harbor\n{H}{H} Expected oracle range for a judge rerun\nRange text.\n",
            "results/latest/ignored.md": f"[broken-in-latest]({H}missing-anchor)\n",
        },
    )
    res_ok = hygiene.check_markdown_anchors(ok_repo)
    assert res_ok.status == "PASS", res_ok.details

    broken_intra = clean_tmp / "anchors_broken_intra"
    _init_git_repo(
        broken_intra,
        {
            "README.md": (
                f"{H} Canary\n"
                f"Broken intra link [missing]({H}nonexistent-heading) and [overflow]({H}notes-1).\n"
                f"{H}{H} Notes\nOnly one notes heading.\n"
            ),
        },
    )
    res_intra = hygiene.check_markdown_anchors(broken_intra)
    assert res_intra.status == "FAIL"
    assert any("nonexistent-heading" in d for d in res_intra.details)
    assert any("notes-1" in d for d in res_intra.details)

    broken_cross = clean_tmp / "anchors_broken_cross"
    _init_git_repo(
        broken_cross,
        {
            "README.md": f"{H} Canary\nSee [guide](docs/guide.md{H}wrong-fragment).\n",
            "docs/guide.md": f"{H} Guide\n{H}{H} Actual Section\nText.\n",
        },
    )
    res_cross = hygiene.check_markdown_anchors(broken_cross)
    assert res_cross.status == "FAIL"
    assert any("wrong-fragment" in d and "docs/guide.md" in d for d in res_cross.details)

    rc = hygiene.main(["--root", str(broken_cross), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_image_assets_missing_empty_and_gitignored(clean_tmp: Path):
    valid_repo = clean_tmp / "img_valid"
    _init_git_repo(
        valid_repo,
        {
            "README.md": f"{H} Canary\n![badge](https://example.com/badge.svg)\n",
            "docs/reports/failure_gallery.md": (
                f"{H} Gallery\n"
                '<img src="../../results/gemini/gallery_charts/chart1.png" width="420" alt="trace">\n'
                "![md chart](../../results/gemini/gallery_charts/chart2.png)\n"
            ),
            "results/gemini/gallery_charts/chart1.png": PNG_BYTES,
            "results/gemini/gallery_charts/chart2.png": PNG_BYTES,
        },
    )
    assert hygiene.check_image_assets(valid_repo).status == "PASS"

    missing_repo = clean_tmp / "img_missing"
    _init_git_repo(
        missing_repo,
        {
            "README.md": f"{H} Canary\n",
            "docs/reports/failure_gallery.md": (
                '<img src="../../results/gemini/gallery_charts/missing_chart.png" width="420">\n'
            ),
        },
    )
    res_missing = hygiene.check_image_assets(missing_repo)
    assert res_missing.status == "FAIL"
    assert any("missing_chart.png" in d for d in res_missing.details)

    empty_repo = clean_tmp / "img_empty"
    _init_git_repo(
        empty_repo,
        {
            "README.md": f"{H} Canary\n",
            "docs/reports/failure_gallery.md": (
                '<img src="../../results/gemini/gallery_charts/empty_chart.png" alt="empty">\n'
            ),
            "results/gemini/gallery_charts/empty_chart.png": b"",
        },
    )
    res_empty = hygiene.check_image_assets(empty_repo)
    assert res_empty.status == "FAIL"
    assert any("empty_chart.png" in d and "0 bytes" in d for d in res_empty.details)

    ignored_img_repo = clean_tmp / "img_ignored"
    _init_git_repo(
        ignored_img_repo,
        {
            "README.md": f"{H} Canary\n<img src=\"results/scratch/local.png\" alt=\"local\">\n",
        },
        gitignore="results/scratch/\n",
    )
    _write_files(ignored_img_repo, {"results/scratch/local.png": PNG_BYTES})
    res_ignored = hygiene.check_image_assets(ignored_img_repo)
    assert res_ignored.status == "WARN"
    assert any("local.png" in d for d in res_ignored.details)


def test_tracked_vs_gitignored_warn_and_untracked_fail(clean_tmp: Path, capsys):
    warn_repo = clean_tmp / "target_warn"
    _init_git_repo(
        warn_repo,
        {
            "README.md": f"{H} Canary\nSee [exploits](docs/EXPLOITS.md) and [dir](results/sub/).\n",
            "docs/EXPLOITS.md": f"{H} Exploits\nLog: [hunt](../results/anticheat/hunt.log).\n",
            "results/sub/data.json": '{"ok": true}\n',
        },
        gitignore="results/latest/\n*.log\n",
    )
    res_warn = hygiene.check_tracked_link_targets(warn_repo)
    assert res_warn.status == "WARN"
    assert any("results/anticheat/hunt.log" in d for d in res_warn.details)

    rc = hygiene.main(["--root", str(warn_repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["passed"] is True

    untracked_repo = clean_tmp / "target_untracked"
    _init_git_repo(
        untracked_repo,
        {
            "README.md": f"{H} Canary\nSee [uncommitted](docs/forgot_to_git_add.md).\n",
        },
    )
    _write_files(untracked_repo, {"docs/forgot_to_git_add.md": f"{H} Uncommitted\n"})
    res_untracked = hygiene.check_tracked_link_targets(untracked_repo)
    assert res_untracked.status == "FAIL"
    assert any("untracked" in d and "docs/forgot_to_git_add.md" in d for d in res_untracked.details)


def test_gitless_and_ceiling_graceful_mode(clean_tmp: Path, capsys, monkeypatch):
    gitless_clean = clean_tmp / "gitless_clean"
    _write_files(
        gitless_clean,
        {
            "README.md": (
                f"{H} Canary\n"
                f"See [walkthrough](docs/JUDGE-WALKTHROUGH.md{H}quick-card) and <img src=\"pitch/chart.png\">.\n"
            ),
            "docs/JUDGE-WALKTHROUGH.md": f"{H} Walkthrough\n{H}{H} Quick Card\n91-attacker Gemini swarm.\n",
            "scripts/mcp_port.sh": f"{H}!/usr/bin/env bash\nset -euo pipefail\necho 8765\n",
            "pitch/chart.png": PNG_BYTES,
        },
    )
    assert not (gitless_clean / ".git").exists()
    results = hygiene.audit_doc_hygiene(gitless_clean)
    assert [r.status for r in results] == ["PASS", "PASS", "PASS", "PASS", "PASS"]

    rc_clean = hygiene.main(["--root", str(gitless_clean), "--json"])
    payload_clean = json.loads(capsys.readouterr().out)
    assert rc_clean == 0
    assert payload_clean["passed"] is True

    broken_git_ceiling = clean_tmp / "broken_git_ceiling"
    _write_files(
        broken_git_ceiling,
        {
            ".git": "gitdir: /tmp/opencode/nonexistent-gitdir-w2b\n",
            ".gitignore": "results/latest/\n*.log\n",
            "README.md": f"{H} Canary\nSee [exploits](docs/EXPLOITS.md) and <img src=\"results/latest/plot.png\">.\n",
            "docs/EXPLOITS.md": f"{H} Exploits\nOptional log [hunt](../results/anticheat/hunt.log).\n",
            "results/latest/plot.png": PNG_BYTES,
            "results/latest/bad.sh": b"echo crlf\r\n",
        },
    )
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(broken_git_ceiling))
    ceiling_results = {r.name: r for r in hygiene.audit_doc_hygiene(broken_git_ceiling)}
    assert ceiling_results[hygiene.CHECK_ANCHORS].status == "PASS"
    assert ceiling_results[hygiene.CHECK_IMAGES].status == "WARN"
    assert ceiling_results[hygiene.CHECK_TRACKED_TARGETS].status == "WARN"
    assert ceiling_results[hygiene.CHECK_STALE_PR41].status == "PASS"
    assert ceiling_results[hygiene.CHECK_PORTABILITY_AND_ENCODING].status == "PASS"
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES", raising=False)

    gitless_with_gitignore = clean_tmp / "gitless_archive"
    _write_files(
        gitless_with_gitignore,
        {
            ".gitignore": "results/latest/\n*.log\n",
            "README.md": f"{H} Canary\nSee [exploits](docs/EXPLOITS.md).\n",
            "docs/EXPLOITS.md": f"{H} Exploits\nOptional log [hunt](../results/anticheat/hunt.log).\n",
        },
    )
    res_gitless_warn = hygiene.check_tracked_link_targets(gitless_with_gitignore)
    assert res_gitless_warn.status == "WARN"
    assert any("hunt.log" in d for d in res_gitless_warn.details)

    gitless_broken = clean_tmp / "gitless_broken"
    _write_files(
        gitless_broken,
        {
            "README.md": f"{H} Canary\nBroken [target](docs/missing_in_zip.md).\n",
        },
    )
    res_gitless_fail = hygiene.check_tracked_link_targets(gitless_broken)
    assert res_gitless_fail.status == "FAIL"
    assert any("missing_in_zip.md" in d for d in res_gitless_fail.details)


@pytest.mark.parametrize(
    ("doc_rel", "stale_snippet", "expected_token"),
    [
        ("README.md", "Zero holes in our 51-attacker red-team run.", "51-attacker"),
        ("JUDGE_QUICKSTART.md", "Audited by a 51-agent swarm on hard.", "51-agent swarm"),
        ("docs/JUDGE-WALKTHROUGH.md", "Swarm used `35` whitebox attackers.", "35 whitebox"),
        ("docs/PEER-REVIEW-QA.md", "Executed `1,789` tool calls against MCP.", "1,789 tool calls"),
        ("docs/REPRODUCIBILITY.md", "Timing: <PLACEHOLDER: fill linux timing>.", "<PLACEHOLDER"),
        ("docs/DEMO.md", "WS4 table: \u27e8PLACEHOLDER: fill held-out row\u27e9.", "<PLACEHOLDER"),
        ("docs/NUMBER-PROVENANCE-INDEX.md", "Audited by 51-attacker Gemini run.", "51-attacker"),
        (
            "docs/EXPLOITS.md",
            "Residual risk 3: Three retired builds publish their signing key next to the job.",
            "Three retired builds publish their signing key",
        ),
        (
            "docs/EXPLOITS.md",
            "ISOLATION OK in all 31 committed Harbor trials that ran solve.sh.",
            "all 31 committed Harbor trials",
        ),
        ("docs/SUBMISSION.md", "OpenCode reached 68% of solver luck-adjusted.", "68% of solver luck-adjusted"),
        ("docs/gemini/SUBMISSION.md", "OpenCode reached 68% of solver luck-adjusted.", "68% of solver luck-adjusted"),
        ("pitch/GEMINI.md", "Tested 51-attacker swarm with 35 whitebox agents.", "51-attacker"),
    ],
)
def test_stale_pre_pr41_number_detection(
    clean_tmp: Path,
    doc_rel: str,
    stale_snippet: str,
    expected_token: str,
):
    clean_repo = clean_tmp / "pr41_clean"
    _write_files(
        clean_repo,
        {
            "README.md": "OpenCode earns 65% raw, luck-adjusted 72% [52%, 91%].\n",
            "JUDGE_QUICKSTART.md": "91-attacker Gemini swarm, 75 whitebox, 4,325 tool calls.\n",
            "docs/JUDGE-WALKTHROUGH.md": "91-attacker swarm (`75` whitebox, `4,325` tool calls).\n",
            "docs/PEER-REVIEW-QA.md": "72% [52%, 91%] luck-adjusted on n=30 hard seeds.\n",
            "docs/REPRODUCIBILITY.md": "61/61 solve.sh trials passed isolation; 80/80 Harbor trials consistent.\n",
            "docs/DEMO.md": (
                "Hint ablation: \u27e8placeholder: HEAD-AGENTS' ablation in progress; cut if uncommitted.\u27e9\n"
            ),
            "docs/NUMBER-PROVENANCE-INDEX.md": "80 of 80 Harbor trials; 91 primary attackers.\n",
            "docs/EXPLOITS.md": (
                f"{H} EXPLOITS\n"
                "ISOLATION OK in all 61 committed Harbor trials that ran solve.sh.\n"
                "Eight retired job directories publish their signing key.\n"
                "| J13 | 100-attack Gemini swarm (75 whitebox + 16 blackbox, 4,325 tool calls). "
                "Wave 1 detail: 35 whitebox attackers | 0 exploits over 1,789 tool calls |\n"
                f"{H}{H} Full history\n"
                "| 49 | Historical snapshot: all 31 committed Harbor trials and Three retired builds publish their signing key |\n"
            ),
            "docs/SUBMISSION.md": "OpenCode reaches 65% raw, 72% [52%, 91%] luck-adjusted.\n",
            "docs/gemini/SUBMISSION.md": "100 attacks: 91 attackers (75 whitebox, 16 blackbox).\n",
            "pitch/GEMINI.md": "91 attackers over 4 waves.\n",
        },
    )
    assert hygiene.check_stale_pr41_numbers(clean_repo).status == "PASS"

    stale_repo = clean_tmp / "pr41_stale"
    _write_files(
        stale_repo,
        {
            "README.md": "Headline 65% raw, 72% luck-adjusted.\n",
            doc_rel: f"{H} Doc\n{stale_snippet}\n",
        },
    )
    res = hygiene.check_stale_pr41_numbers(stale_repo)
    assert res.status == "FAIL"
    assert any(doc_rel in d and expected_token in d for d in res.details), res.details


def test_exploits_placeholder_still_fails_inside_full_history(clean_tmp: Path):
    repo = clean_tmp / "exploits_hist_placeholder"
    _write_files(
        repo,
        {
            "docs/EXPLOITS.md": (
                f"{H} EXPLOITS\n"
                "Eight retired job directories publish their signing key.\n"
                f"{H}{H} Full history\n"
                "| 49 | <PLACEHOLDER: fill hunt> |\n"
            ),
        },
    )
    res = hygiene.check_stale_pr41_numbers(repo)
    assert res.status == "FAIL"
    assert any("<PLACEHOLDER" in d for d in res.details)


@pytest.mark.parametrize(
    "sh_rel",
    [
        "harbor/template/tests/test.sh",
        "scripts/judge_accept.sh",
        "fr8/verda/run_v3.sh",
    ],
)
def test_crlf_in_shell_scripts_detected(clean_tmp: Path, sh_rel: str):
    crlf_repo = clean_tmp / f"crlf_{Path(sh_rel).stem}"
    _init_git_repo(
        crlf_repo,
        {
            "README.md": f"{H} Canary\n",
            sh_rel: f"{H}!/usr/bin/env bash\r\nset -euo pipefail\r\necho ok\r\n".encode("utf-8"),
        },
    )
    res = hygiene.check_portability_and_encoding(crlf_repo)
    assert res.status == "FAIL"
    assert any(sh_rel in d and "CRLF" in d for d in res.details), res.details


@pytest.mark.parametrize(
    ("rel_path", "bad_bytes", "expected_substr"),
    [
        ("docs/UTF8_BOM.md", b"\xef\xbb\xbf" + b"Canary doc\n", "UTF-8 BOM"),
        ("scripts/bom.sh", b"\xef\xbb\xbf" + f"{H}!/usr/bin/env bash\necho ok\n".encode("utf-8"), "UTF-8 BOM"),
        ("canary/bad_utf8.py", b"x = '\xff\xfe'\n", "invalid UTF-8"),
        ("pyproject.toml", b"[project]\nname = 'canary\x00bad'\n", "NUL byte"),
        (".github/workflows/ci.yml", b"\xef\xbb\xbfname: ci\n", "UTF-8 BOM"),
    ],
)
def test_utf8_bom_invalid_utf8_and_nul_bytes_detected(
    clean_tmp: Path,
    rel_path: str,
    bad_bytes: bytes,
    expected_substr: str,
):
    bad_repo = clean_tmp / "encoding_bad"
    _write_files(
        bad_repo,
        {
            "README.md": f"{H} Canary\n",
            rel_path: bad_bytes,
        },
    )
    res = hygiene.check_portability_and_encoding(bad_repo)
    assert res.status == "FAIL"
    assert any(rel_path in d and expected_substr in d for d in res.details), res.details


def test_merge_conflict_markers_outside_vs_inside_fenced_blocks(clean_tmp: Path):
    left = "<" * 7 + " HEAD"
    mid = "=" * 7
    right = ">" * 7 + " branch"

    fenced_ok = clean_tmp / "conflict_fenced_ok"
    _init_git_repo(
        fenced_ok,
        {
            "README.md": "\n".join(
                [
                    f"{H} Canary",
                    "Example conflict inside fenced block:",
                    "```text",
                    left,
                    "ours",
                    mid,
                    "theirs",
                    right,
                    "```",
                ]
            )
            + "\n",
        },
    )
    assert hygiene.check_portability_and_encoding(fenced_ok).status == "PASS"

    prose_bad = clean_tmp / "conflict_prose_bad"
    _init_git_repo(
        prose_bad,
        {
            "README.md": "\n".join([f"{H} Canary", left, "ours", mid, "theirs", right]) + "\n",
            "scripts/helper.py": "\n".join(["x = 1", left, "y = 2", mid, "y = 3", right]) + "\n",
        },
    )
    res_bad = hygiene.check_portability_and_encoding(prose_bad)
    assert res_bad.status == "FAIL"
    assert any("README.md:2" in d and "merge-conflict" in d for d in res_bad.details), res_bad.details
    assert any("scripts/helper.py:2" in d and "merge-conflict" in d for d in res_bad.details), res_bad.details


def test_scripts_sh_shebang_pkill_and_diffutils_portability(clean_tmp: Path, capsys):
    portable_repo = clean_tmp / "sh_portable"
    _init_git_repo(
        portable_repo,
        {
            "README.md": f"{H} Canary\n",
            "scripts/accept.sh": "\n".join(
                [
                    f"{H}!/usr/bin/env bash",
                    f"{H} never run pkill or bare cmp -s in scripts",
                    "set -euo pipefail",
                    'echo "never pkill; files may diff"',
                    "git diff --quiet || true",
                    "if { ! command -v cmp >/dev/null 2>&1 || cmp -s a.md b.md; }; then",
                    "  echo matched",
                    "fi",
                    "if command -v diff >/dev/null 2>&1; then",
                    "  diff -u a.md b.md",
                    "else",
                    '  python3 -c "import difflib"',
                    "fi",
                    "python3 - <<'PY'",
                    "diff = 42",
                    "pkill = 'ignored_in_heredoc'",
                    "PY",
                ]
            )
            + "\n",
        },
    )
    res_ok = hygiene.check_portability_and_encoding(portable_repo)
    assert res_ok.status == "PASS", res_ok.details

    no_shebang = clean_tmp / "sh_no_shebang"
    _write_files(
        no_shebang,
        {
            "README.md": f"{H} Canary\n",
            "scripts/no_shebang.sh": "set -euo pipefail\necho hi\n",
        },
    )
    res_shebang = hygiene.check_portability_and_encoding(no_shebang)
    assert res_shebang.status == "FAIL"
    assert any("scripts/no_shebang.sh:1" in d and "shebang" in d for d in res_shebang.details)

    bad_pkill = clean_tmp / "sh_bad_pkill"
    _write_files(
        bad_pkill,
        {
            "README.md": f"{H} Canary\n",
            "scripts/kill_mcp.sh": f"{H}!/usr/bin/env bash\npkill -f canary.mcp_server\n",
        },
    )
    res_pkill = hygiene.check_portability_and_encoding(bad_pkill)
    assert res_pkill.status == "FAIL"
    assert any("scripts/kill_mcp.sh:2" in d and "pkill" in d for d in res_pkill.details)

    bad_cmp = clean_tmp / "sh_bad_cmp"
    _write_files(
        bad_cmp,
        {
            "README.md": f"{H} Canary\n",
            "scripts/check_table.sh": "\n".join(
                [
                    f"{H}!/usr/bin/env bash",
                    "python3 -c 'print(1)'",
                    "if [ -f a.md ]; then",
                    "  cmp -s a.md b.md",
                    "else",
                    "  python3 -c 'print(2)'",
                    "fi",
                    "diff -u a.md b.md",
                ]
            )
            + "\n",
        },
    )
    res_cmp = hygiene.check_portability_and_encoding(bad_cmp)
    assert res_cmp.status == "FAIL"
    assert any("scripts/check_table.sh:4" in d and "bare 'cmp'" in d for d in res_cmp.details), res_cmp.details
    assert any("scripts/check_table.sh:8" in d and "bare 'diff'" in d for d in res_cmp.details), res_cmp.details

    rc = hygiene.main(["--root", str(bad_cmp), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_check_makefile_diffutils_portability(clean_tmp: Path):
    unportable = clean_tmp / "mk_unportable"
    _write_files(
        unportable,
        {
            "Makefile": "\n".join(
                [
                    f"{H} Canary Makefile",
                    "UV := uv run",
                    f"reproduce: {H}{H} recompute and diff table",
                    "\t@$(UV) python scripts/paired_gemini.py",
                    "\t@if cmp -s results/latest/a.md data/a.md; then \\",
                    '\t  echo "IDENTICAL"; \\',
                    '\telse echo "MISMATCH: differs"; \\',
                    "\t  diff results/latest/a.md data/a.md | head -20; exit 1; fi",
                ]
            )
            + "\n",
        },
    )
    res_bad = hygiene.check_makefile_diffutils_portability(unportable)
    assert res_bad.status == "FAIL"
    assert any("Makefile:5" in d and "bare 'cmp'" in d for d in res_bad.details), res_bad.details
    assert any("Makefile:8" in d and "bare 'diff'" in d for d in res_bad.details), res_bad.details

    portable_cmd_v = clean_tmp / "mk_portable_cmd_v"
    _write_files(
        portable_cmd_v,
        {
            "Makefile": "\n".join(
                [
                    "UV := uv run",
                    "reproduce:",
                    "\t@if { command -v cmp >/dev/null 2>&1 && cmp -s a.md b.md; } "
                    "|| $(UV) python -c 'import pathlib,sys; sys.exit(0 if pathlib.Path(\"a.md\").read_bytes()==pathlib.Path(\"b.md\").read_bytes() else 1)'; then \\",
                    '\t  echo "OK"; \\',
                    "\telse \\",
                    "\t  if command -v diff >/dev/null 2>&1; then diff a.md b.md | head -20; "
                    "else $(UV) python -c 'import difflib'; fi; exit 1; fi",
                ]
            )
            + "\n",
        },
    )
    res_portable = hygiene.check_makefile_diffutils_portability(portable_cmd_v)
    assert res_portable.status == "PASS", res_portable.details

    pure_py = clean_tmp / "mk_pure_py"
    _write_files(
        pure_py,
        {
            "Makefile": (
                f"reproduce: {H}{H} diff via python\n"
                "\tgit diff --quiet || true\n"
                "\tpython3 -c 'import difflib'\n"
            ),
        },
    )
    assert hygiene.check_makefile_diffutils_portability(pure_py).status == "PASS"

    missing_mk = clean_tmp / "mk_missing"
    missing_mk.mkdir(parents=True, exist_ok=True)
    assert hygiene.check_makefile_diffutils_portability(missing_mk).status == "FAIL"

    real_mk_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    res_real = hygiene.check_makefile_diffutils_portability(ROOT)
    assert res_real.name == hygiene.CHECK_MAKEFILE_DIFFUTILS
    if "\t@if cmp -s " in real_mk_text and "command -v cmp" not in real_mk_text:
        assert res_real.status == "FAIL"
        assert any("bare 'cmp'" in d for d in res_real.details)
    else:
        assert res_real.status == "PASS"
