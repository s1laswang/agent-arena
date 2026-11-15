"""Keyless CI-parity and sibling-compatibility tests for the AfterQuery PR bundle."""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_pr_branch import main, verify_branch

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

SURGICAL_PR_BRANCHES: tuple[str, ...] = (
    "origin/fr8/afterquery/fix-openai-env-test",
    "origin/fr8/afterquery/research-biases",
    "origin/fr8/afterquery/doc-sync",
    "origin/fr8/afterquery/replay",
    "origin/fr8/afterquery/v14-replication",
    "origin/fr8/afterquery/rehearsal-fr8",
)
V14_RUNS_BRANCH = "origin/fr8/afterquery/v14-runs"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=check,
    )


def _ref_exists(repo: Path, ref: str) -> bool:
    res = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    return res.returncode == 0


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _commit_files(repo: Path, files: dict[str, str], message: str = "update") -> str:
    _write_files(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_ci_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ci_repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "justSilas")
    _git(repo, "config", "user.name", "CI Parity Bot")
    _git(repo, "config", "user.email", "ci-parity@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    protected_list = "\n".join(
        [
            f"{HASH_CHAR} Protected Canary paths",
            "canary/env.py",
            "canary/rules.py",
            "canary/reproduce.py",
            "harbor/",
            "Makefile",
            "data/runs/committed/",
            "results/judge_table.md",
            ".github/protected-paths.txt",
            ".github/workflows/",
            "",
        ]
    )
    _commit_files(
        repo,
        {
            "README.md": (
                f"{HASH_CHAR} Canary Benchmark\n\n"
                f"{HASH_CHAR}{HASH_CHAR} Expected oracle range for a judge rerun\n"
                "Baseline documentation.\n"
            ),
            ".github/protected-paths.txt": protected_list,
            "canary/env.py": "FROZEN = True\n",
            "canary/rules.py": "TIERS_VERSION = 'v1.4'\n",
            "tests/test_gemini_frontier.py": "def test_env() -> None:\n    assert True\n",
        },
        message="initial justSilas baseline",
    )
    return repo


def _gate_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {g["name"]: g for g in report["gates"]}


def test_ci_parity_suite_zero_comments_and_dashes() -> None:
    for py_rel in (
        "scripts/verify_pr_branch.py",
        "tests/test_verify_pr_branch.py",
        "tests/test_pr_bundle_ci_parity.py",
    ):
        raw = (ROOT / py_rel).read_bytes()
        comments = [
            tok for tok in tokenize.tokenize(io.BytesIO(raw).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], f"unexpected comments in {py_rel}: {comments}"
        txt = raw.decode("utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt


def test_synthetic_three_way_clean_bundle_matrix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_ci_repo(tmp_path)

    _git(repo, "checkout", "-b", "pr-fix-env")
    _commit_files(
        repo,
        {
            "tests/test_gemini_frontier.py": (
                "def test_env() -> None:\n"
                "    key = 'o-test-key'\n"
                "    assert bool(key)\n"
            )
        },
        message="tests: set keyless OPENAI_API_KEY fixture",
    )

    _git(repo, "checkout", "-b", "pr-biases", "pr-fix-env")
    _commit_files(
        repo,
        {
            "docs/biases.md": (
                f"{HASH_CHAR} Organisational Biases\n\n"
                f"See [README](../README.md{HASH_CHAR}expected-oracle-range-for-a-judge-rerun).\n"
            )
        },
        message="docs: add biases synthesis",
    )

    _git(repo, "checkout", "-b", "pr-doc-sync", "pr-fix-env")
    _commit_files(
        repo,
        {"docs/reports/audit.md": f"{HASH_CHAR} Doc Sync Audit\n\nClean links.\n"},
        message="docs: add doc-sync audit",
    )

    branches = ("pr-fix-env", "pr-biases", "pr-doc-sync")
    for br in branches:
        siblings = [other for other in branches if other != br]
        cli_args = ["--repo", str(repo), "--base", "justSilas", "--branch", br, "--json"]
        for sib in siblings:
            cli_args.extend(["--with-branch", sib])
        rc = main(cli_args)
        out = capsys.readouterr().out
        assert rc == 0, out
        report = json.loads(out)
        assert report["ok"] is True
        gates = _gate_map(report)
        assert len(gates) == 12
        assert gates["protected_core"]["passed"] is True
        assert gates["sibling_compat"]["passed"] is True
        assert gates["sibling_compat"]["summary"] == "2 sibling(s) checked: 2 3-way clean"


def test_synthetic_pre_base_rename_squash_clean(tmp_path: Path) -> None:
    repo = _init_ci_repo(tmp_path)

    _git(repo, "checkout", "-b", "pre-base-fleet")
    _commit_files(
        repo,
        {
            "data/runs/committed/v1.4/fleet_raw/30.txt": "raw transcript 30\n",
            "data/runs/committed/v1.4/fleet_raw/42.txt": "raw transcript 42\n",
            "data/runs/committed/v1.4/fleet_raw/meta.json": "{\"seeds\": [30, 42]}\n",
        },
        message="stage raw fleet runs before base split",
    )

    _git(repo, "checkout", "justSilas")
    _commit_files(
        repo,
        {"docs/integrity_note.md": "Post-freeze integrity check.\n"},
        message="advance justSilas after fleet staging",
    )

    _git(repo, "checkout", "-b", "pr-v14-runs", "pre-base-fleet")
    _git(repo, "merge", "--no-edit", "justSilas")
    (repo / "data" / "runs" / "committed" / "v1.4" / "ext" / "transcripts").mkdir(
        parents=True, exist_ok=True
    )
    _git(
        repo,
        "mv",
        "data/runs/committed/v1.4/fleet_raw/30.txt",
        "data/runs/committed/v1.4/ext/transcripts/30.txt",
    )
    _git(
        repo,
        "mv",
        "data/runs/committed/v1.4/fleet_raw/42.txt",
        "data/runs/committed/v1.4/ext/transcripts/42.txt",
    )
    _git(repo, "rm", "data/runs/committed/v1.4/fleet_raw/meta.json")
    _git(repo, "commit", "-m", "package committed ext transcripts")

    _git(repo, "checkout", "-b", "pr-v14-replication", "pre-base-fleet")
    _git(repo, "merge", "--no-edit", "justSilas")
    (repo / "results" / "frontier_replication" / "v1.4" / "ext" / "transcripts").mkdir(
        parents=True, exist_ok=True
    )
    (repo / "results" / "selected_fleet_replication" / "v1.4" / "raw").mkdir(
        parents=True, exist_ok=True
    )
    _git(
        repo,
        "mv",
        "data/runs/committed/v1.4/fleet_raw/30.txt",
        "results/frontier_replication/v1.4/ext/transcripts/30.txt",
    )
    _git(
        repo,
        "mv",
        "data/runs/committed/v1.4/fleet_raw/42.txt",
        "results/frontier_replication/v1.4/ext/transcripts/42.txt",
    )
    _git(
        repo,
        "mv",
        "data/runs/committed/v1.4/fleet_raw/meta.json",
        "results/selected_fleet_replication/v1.4/raw/summary_meta.json",
    )
    _git(repo, "commit", "-m", "package zero-protected-path replication lane")

    mt_raw = _git(
        repo, "merge-tree", "--write-tree", "pr-v14-runs", "pr-v14-replication", check=False
    )
    assert mt_raw.returncode != 0

    rep_rep = verify_branch(
        base="justSilas",
        branch="pr-v14-replication",
        repo=repo,
        with_branches=["pr-v14-runs"],
    )
    assert rep_rep["ok"] is True, rep_rep
    gates_rep = _gate_map(rep_rep)
    assert gates_rep["protected_core"]["passed"] is True
    assert gates_rep["sibling_compat"]["passed"] is True
    assert "1 squash-clean onto base" in gates_rep["sibling_compat"]["summary"]

    rep_runs = verify_branch(
        base="justSilas",
        branch="pr-v14-runs",
        repo=repo,
        allow_data=True,
        with_branches=["pr-v14-replication"],
    )
    assert rep_runs["ok"] is True, rep_runs
    gates_runs = _gate_map(rep_runs)
    assert gates_runs["sibling_compat"]["passed"] is True
    assert "1 squash-clean onto base" in gates_runs["sibling_compat"]["summary"]


@pytest.mark.parametrize("conflict_kind", ["modify_modify", "add_add", "post_base_rename_rename"])
def test_synthetic_real_post_base_conflict_fails(tmp_path: Path, conflict_kind: str) -> None:
    repo = _init_ci_repo(tmp_path)
    _commit_files(repo, {"docs/existing.md": "line 1\nline 2\n"}, message="seed existing doc")

    _git(repo, "checkout", "-b", "sib-pr")
    if conflict_kind == "modify_modify":
        _commit_files(repo, {"docs/existing.md": "sib edit\nline 2\n"}, message="sib modify")
    elif conflict_kind == "add_add":
        _commit_files(repo, {"docs/new_report.md": "sibling report\n"}, message="sib add")
    else:
        _git(repo, "mv", "docs/existing.md", "docs/renamed_by_sib.md")
        _git(repo, "commit", "-m", "sib rename")

    _git(repo, "checkout", "-b", "cand-pr", "justSilas")
    if conflict_kind == "modify_modify":
        _commit_files(repo, {"docs/existing.md": "cand edit\nline 2\n"}, message="cand modify")
    elif conflict_kind == "add_add":
        _commit_files(repo, {"docs/new_report.md": "candidate report\n"}, message="cand add")
    else:
        _git(repo, "mv", "docs/existing.md", "docs/renamed_by_cand.md")
        _git(repo, "commit", "-m", "cand rename")

    rep = verify_branch(
        base="justSilas",
        branch="cand-pr",
        repo=repo,
        with_branches=["sib-pr"],
    )
    assert rep["ok"] is False
    sib_gate = _gate_map(rep)["sibling_compat"]
    assert sib_gate["passed"] is False
    assert len(sib_gate["errors"]) == 1
    assert "post-base conflict" in sib_gate["errors"][0]


def test_synthetic_markdown_anchor_pass_and_fail(tmp_path: Path) -> None:
    repo = _init_ci_repo(tmp_path)
    _git(repo, "checkout", "-b", "anchor-branch")

    h1 = HASH_CHAR
    h2 = HASH_CHAR * 2
    good_doc = "\n".join(
        [
            f"{h1} Organizational Biases Report",
            "",
            f"{h2} 1. Rumour Psychology and Attribution",
            "",
            f"{h2} 10. Canary v1.4 vs. v1.5 Synthesis",
            "",
            f"- Intra 1: [sec1]({HASH_CHAR}1-rumour-psychology-and-attribution)",
            f"- Intra 10: [sec10]({HASH_CHAR}10-canary-v14-vs-v15-synthesis)",
            f"- Cross README: [oracle](../README.md{HASH_CHAR}expected-oracle-range-for-a-judge-rerun)",
            "",
            "```markdown",
            f"[fenced broken]({HASH_CHAR}does-not-exist)",
            f"[fenced cross](../README.md{HASH_CHAR}does-not-exist)",
            "```",
            "",
        ]
    )
    _commit_files(repo, {"docs/report.md": good_doc}, message="docs: add clean anchor doc")

    rep_ok = verify_branch(base="justSilas", branch="anchor-branch", repo=repo)
    assert rep_ok["ok"] is True, rep_ok
    gates_ok = _gate_map(rep_ok)
    assert gates_ok["markdown_links"]["passed"] is True
    assert "(3 anchor(s) checked)" in gates_ok["markdown_links"]["summary"]

    bad_doc = (
        good_doc
        + f"- Bad intra: [oops]({HASH_CHAR}missing-section-slug)\n"
        + f"- Bad cross: [oops2](../README.md{HASH_CHAR}missing-readme-slug)\n"
    )
    _commit_files(repo, {"docs/report.md": bad_doc}, message="docs: break anchors")

    rep_bad = verify_branch(base="justSilas", branch="anchor-branch", repo=repo)
    assert rep_bad["ok"] is False
    gates_bad = _gate_map(rep_bad)
    assert gates_bad["markdown_links"]["passed"] is False
    errs = gates_bad["markdown_links"]["errors"]
    assert len(errs) == 2
    joined = "\n".join(errs)
    assert f"docs/report.md{HASH_CHAR}missing-section-slug" in joined
    assert f"README.md{HASH_CHAR}missing-readme-slug" in joined


@pytest.mark.parametrize("surgical_branch", SURGICAL_PR_BRANCHES)
def test_live_surgical_pr_bundle_ci_parity(
    surgical_branch: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    required = ("origin/justSilas", *SURGICAL_PR_BRANCHES)
    for ref in required:
        if not _ref_exists(ROOT, ref):
            pytest.skip(f"missing remote ref {ref}")

    siblings = [other for other in SURGICAL_PR_BRANCHES if other != surgical_branch]
    report = verify_branch(
        base="origin/justSilas",
        branch=surgical_branch,
        repo=ROOT,
        with_branches=siblings,
    )
    assert report["ok"] is True, report
    gates = _gate_map(report)
    assert len(gates) == 12
    assert all(g["passed"] for g in report["gates"])
    assert gates["protected_core"]["summary"] == "0 protected paths touched"
    assert gates["sibling_compat"]["summary"] == "5 sibling(s) checked: 5 3-way clean"


def test_live_v14_runs_squash_compat_with_all_surgical_prs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    required = ("origin/justSilas", V14_RUNS_BRANCH, *SURGICAL_PR_BRANCHES)
    for ref in required:
        if not _ref_exists(ROOT, ref):
            pytest.skip(f"missing remote ref {ref}")

    rep_runs = verify_branch(
        base="origin/justSilas",
        branch=V14_RUNS_BRANCH,
        repo=ROOT,
        allow_data=True,
        with_branches=SURGICAL_PR_BRANCHES,
    )
    assert rep_runs["ok"] is True, rep_runs
    gates_runs = _gate_map(rep_runs)
    assert len(gates_runs) == 12
    assert all(g["passed"] for g in rep_runs["gates"])
    sib_summary = gates_runs["sibling_compat"]["summary"]
    assert "5 3-way clean" in sib_summary
    assert "1 squash-clean onto base" in sib_summary

    rep_rep = verify_branch(
        base="origin/justSilas",
        branch="origin/fr8/afterquery/v14-replication",
        repo=ROOT,
        skip_replay=True,
        with_branches=[V14_RUNS_BRANCH],
    )
    assert rep_rep["ok"] is True, rep_rep
    gates_rep = _gate_map(rep_rep)
    assert gates_rep["sibling_compat"]["passed"] is True
    assert "1 squash-clean onto base" in gates_rep["sibling_compat"]["summary"]
