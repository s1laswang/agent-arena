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
        assert H not in src, f"unexpected hash character in {path.name}"
        assert "\u2014" not in src, f"unexpected em dash in {path.name}"
        assert "\u2013" not in src, f"unexpected en dash in {path.name}"


def test_real_repo_passes_cli_and_api(capsys):
    api_results = hygiene.audit_doc_hygiene(ROOT)
    alias_results = hygiene.audit_repo(ROOT)
    assert len(api_results) == 4
    assert [r.name for r in api_results] == list(hygiene.CHECK_NAMES)
    assert [r.status for r in api_results] == [r.status for r in alias_results]
    for item in api_results:
        assert item.status != "FAIL", f"{item.name} failed: {item.details}"

    rc_json = hygiene.main(["--root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 10.0
    assert len(payload["results"]) == 4
    assert payload["checks"] == payload["results"]
    by_name = {r["name"]: r for r in payload["results"]}
    assert set(by_name) == set(hygiene.CHECK_NAMES)
    assert by_name[hygiene.CHECK_ANCHORS]["status"] == "PASS"
    assert by_name[hygiene.CHECK_IMAGES]["status"] == "PASS"
    assert by_name[hygiene.CHECK_TRACKED_TARGETS]["status"] in {"PASS", "WARN"}
    assert by_name[hygiene.CHECK_STALE_PR41]["status"] == "PASS"

    rc_text = hygiene.main(["--root", str(ROOT)])
    text_out = capsys.readouterr().out
    assert rc_text == 0
    assert "0 FAIL" in text_out
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


def test_gitless_graceful_mode(clean_tmp: Path, capsys):
    gitless_clean = clean_tmp / "gitless_clean"
    _write_files(
        gitless_clean,
        {
            "README.md": (
                f"{H} Canary\n"
                f"See [walkthrough](docs/JUDGE-WALKTHROUGH.md{H}quick-card) and <img src=\"pitch/chart.png\">.\n"
            ),
            "docs/JUDGE-WALKTHROUGH.md": f"{H} Walkthrough\n{H}{H} Quick Card\n91-attacker Gemini swarm.\n",
            "pitch/chart.png": PNG_BYTES,
        },
    )
    assert not (gitless_clean / ".git").exists()
    results = hygiene.audit_doc_hygiene(gitless_clean)
    assert [r.status for r in results] == ["PASS", "PASS", "PASS", "PASS"]

    rc_clean = hygiene.main(["--root", str(gitless_clean), "--json"])
    payload_clean = json.loads(capsys.readouterr().out)
    assert rc_clean == 0
    assert payload_clean["passed"] is True

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
    assert any(doc_rel in d and expected_token in d for d in res.details)
