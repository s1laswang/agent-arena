"""Unit and smoke tests for scripts/verify_pr_branch.py."""
from __future__ import annotations

from dataclasses import asdict
import io
import json
from pathlib import Path
import subprocess
import tokenize
from typing import Any

import pytest

from canary.env import Env
from scripts.verify_pr_branch import main, verify_branch

ROOT = Path(__file__).resolve().parents[1]
HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return res


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


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "justSilas")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    _commit_files(
        repo,
        {
            "README.md": "Canary baseline\nline two\n",
            "canary/env.py": "VALUE = 1\n",
            "canary/rules.py": "TIERS_VERSION = 'v1.4'\n",
            "canary/solver/core.py": "SOLVER = True\n",
            "canary/reproduce.py": "REPRO = True\n",
            "harbor/build.py": "HARBOR = True\n",
        },
        message="initial justSilas commit",
    )
    return repo


def _gate_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {g["name"]: g for g in report["gates"]}


def _make_episode(tier: str = "hard", seed: int = 30, agent: str = "test_agent") -> dict[str, Any]:
    env = Env(tier, seed)
    env.call("status", {})
    env.call("accuse", {"employee": "e00"})
    ep = asdict(env.result(agent))
    ep["meta"] = {"rc": 0, "valid": True}
    return ep


def test_clean_pass_and_cli_modes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feat")

    shebang = HASH_CHAR + "!/usr/bin/env python3\n"
    clean_py = (
        shebang
        + '"""Clean tool module."""\n'
        + f'HEADER = "section {HASH_CHAR} one"\n'
        + "def add(a: int, b: int) -> int:\n"
        + "    return a + b\n"
    )
    ep = _make_episode(tier="hard", seed=30, agent="opencode:google/gemini-4-carbon")
    shard = "results/selected_fleet_replication/v1.4/opencode-gemini-4-carbon/hard-s30-59"
    meta = {
        "agent": ep["agent"],
        "tier": "hard",
        "tiers_version": "v1.4",
        "seeds": [30],
    }

    _commit_files(
        repo,
        {
            "scripts/helper.py": clean_py,
            "docs/note.md": "Clean summary - see [README](../README.md) and [web](https://example.com).\n",
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps(meta, indent=2) + "\n",
            f"{shard}/transcripts/30.txt": f"step 1 ok {EN_DASH} model output\n",
        },
        message="feat: add helper and clean replication shard",
    )

    rc_json = main(["--repo", str(repo), "--base", "justSilas", "--branch", "feat", "--json"])
    out_json = capsys.readouterr().out
    assert rc_json == 0
    parsed = json.loads(out_json)
    assert parsed["ok"] is True
    assert parsed["ff_base"] is True
    assert parsed["changed_files"] == 5
    gates = _gate_map(parsed)
    assert len(gates) == 11
    assert all(g["passed"] for g in parsed["gates"])

    rc_txt = main(["--repo", str(repo), "--base", "justSilas", "--branch", "feat"])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "OVERALL: PASS (11/11 gates passed)" in out_txt


def test_merge_conflict_and_require_ff_base(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "conflict-branch")
    _commit_files(repo, {"README.md": "branch change\nline two\n"}, message="branch edit")

    _git(repo, "checkout", "justSilas")
    _commit_files(repo, {"README.md": "base conflicting change\nline two\n"}, message="base edit")

    rep_conflict = verify_branch(base="justSilas", branch="conflict-branch", repo=repo)
    assert rep_conflict["ok"] is False
    gates = _gate_map(rep_conflict)
    assert gates["merge_conflict"]["passed"] is False
    assert any("merge conflict" in e for e in gates["merge_conflict"]["errors"])

    _git(repo, "checkout", "-B", "diverged-clean", "justSilas~1")
    _commit_files(repo, {"docs/clean.md": "clean non-conflicting doc\n"}, message="clean doc")

    rep_warn = verify_branch(base="justSilas", branch="diverged-clean", repo=repo)
    assert rep_warn["ok"] is True
    assert rep_warn["ff_base"] is False
    assert len(rep_warn["warnings"]) == 1

    rep_strict = verify_branch(
        base="justSilas",
        branch="diverged-clean",
        repo=repo,
        require_ff_base=True,
    )
    assert rep_strict["ok"] is False
    assert _gate_map(rep_strict)["merge_conflict"]["passed"] is False


@pytest.mark.parametrize(
    "core_path",
    [
        "canary/env.py",
        "canary/rules.py",
        "canary/world.py",
        "canary/mcp_server.py",
        "canary/solver/core.py",
        "canary/reproduce.py",
        "harbor/build.py",
        "Makefile",
        "configs/v14.yaml",
        ".github/protected-paths.txt",
        ".github/workflows/ci.yml",
    ],
)
def test_protected_core_gate(tmp_path: Path, core_path: str) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "touch-core")
    _commit_files(repo, {core_path: "MODIFIED = True\n"}, message="touch core")

    rep = verify_branch(base="justSilas", branch="touch-core", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["protected_core"]["passed"] is False
    assert any(core_path in e for e in gates["protected_core"]["errors"])

    rep_data = verify_branch(base="justSilas", branch="touch-core", repo=repo, allow_data=True)
    assert rep_data["ok"] is False
    assert _gate_map(rep_data)["protected_core"]["passed"] is False

    rep_allowed = verify_branch(base="justSilas", branch="touch-core", repo=repo, allow_core=True)
    assert rep_allowed["ok"] is True
    assert _gate_map(rep_allowed)["protected_core"]["passed"] is True


def test_protected_paths_from_base_and_allow_data_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    protected_txt = (
        f"{HASH_CHAR} Protected list from base\n"
        "custom_guard/\n"
        "exact_guard.txt\n"
        "data/runs/committed/\n"
        "results/judge_table.md\n"
        ".github/protected-paths.txt\n"
    )
    _commit_files(
        repo,
        {".github/protected-paths.txt": protected_txt},
        message="add protected-paths.txt on base",
    )

    _git(repo, "checkout", "-b", "data-pr")
    ep = _make_episode(tier="hard", seed=30, agent="opencode:google/gemini-4-carbon")
    shard = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard-s30-33"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [30]}) + "\n",
            "results/judge_table.md": "| updated |\n",
        },
        message="stage committed data shard",
    )

    rep_blocked = verify_branch(base="justSilas", branch="data-pr", repo=repo)
    assert rep_blocked["ok"] is False
    err_blocked = "\n".join(_gate_map(rep_blocked)["protected_core"]["errors"])
    assert shard in err_blocked
    assert "results/judge_table.md" in err_blocked

    rc_allow_data = main(
        ["--repo", str(repo), "--base", "justSilas", "--branch", "data-pr", "--allow-data"]
    )
    out = capsys.readouterr().out
    assert rc_allow_data == 0, out
    assert "OVERALL: PASS" in out

    _git(repo, "checkout", "-B", "weaken-guard", "justSilas")
    _commit_files(
        repo,
        {
            ".github/protected-paths.txt": "\n",
            "custom_guard/secret.py": "X = 1\n",
            "exact_guard.txt": "changed\n",
        },
        message="attempt to weaken base guard",
    )
    rep_weaken = verify_branch(base="justSilas", branch="weaken-guard", repo=repo)
    assert rep_weaken["ok"] is False
    err_weaken = "\n".join(_gate_map(rep_weaken)["protected_core"]["errors"])
    assert "custom_guard/secret.py" in err_weaken
    assert "exact_guard.txt" in err_weaken
    assert ".github/protected-paths.txt" in err_weaken


@pytest.mark.parametrize(
    "reserved_path",
    [
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/meta.json",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json",
        "data/runs/committed/v1.4/opencode-gemini-3.5-flash/tags.json",
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/accuse.md",
    ],
)
def test_finalize_reserved_path_gate(tmp_path: Path, reserved_path: str) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "touch-reserved")
    _commit_files(repo, {reserved_path: "{}\n"}, message="write reserved finalize path")

    rep = verify_branch(base="justSilas", branch="touch-reserved", repo=repo, allow_data=True)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["protected_core"]["passed"] is True
    assert gates["finalize_reserved_path"]["passed"] is False
    assert any(reserved_path in e for e in gates["finalize_reserved_path"]["errors"])


def test_python_comments_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "with-comment")
    bad_py = "def f() -> int:\n    return 1  " + HASH_CHAR + " forbidden inline comment\n"
    _commit_files(repo, {"scripts/bad.py": bad_py}, message="add commented python")

    rep = verify_branch(base="justSilas", branch="with-comment", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["python_comments"]["passed"] is False
    assert any("scripts/bad.py:2" in e for e in gates["python_comments"]["errors"])


def test_modified_py_files_scan_only_added_lines_for_python_comments(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base_py = (
        f"{HASH_CHAR} Legacy comment on base\n"
        "def existing() -> int:\n"
        f"    return 1  {HASH_CHAR} legacy inline comment\n"
    )
    _commit_files(
        repo,
        {"tests/test_legacy.py": base_py},
        message="seed base python file with pre-existing comments",
    )

    _git(repo, "checkout", "-b", "modify-py-clean")
    clean_mod_py = (
        base_py
        + "\n"
        + "def added_helper() -> str:\n"
        + f'    return """literal\n{HASH_CHAR} inside multiline string"""\n'
    )
    _commit_files(
        repo,
        {"tests/test_legacy.py": clean_mod_py},
        message="modify existing python file without adding comments",
    )

    rep_clean = verify_branch(base="justSilas", branch="modify-py-clean", repo=repo)
    assert rep_clean["ok"] is True, rep_clean
    assert len(rep_clean["gates"]) == 11
    assert all(g["passed"] for g in rep_clean["gates"])
    assert _gate_map(rep_clean)["python_comments"]["passed"] is True

    bad_mod_py = clean_mod_py + f"{HASH_CHAR} newly added forbidden comment\n"
    _commit_files(
        repo,
        {"tests/test_legacy.py": bad_mod_py},
        message="add new comment line to modified python file",
    )

    rep_bad = verify_branch(base="justSilas", branch="modify-py-clean", repo=repo)
    assert rep_bad["ok"] is False
    errs = _gate_map(rep_bad)["python_comments"]["errors"]
    assert errs == [
        f"tests/test_legacy.py:8: unexpected comment {HASH_CHAR} newly added forbidden comment"
    ]


@pytest.mark.parametrize("dash_char,label", [(EM_DASH, "em-dash"), (EN_DASH, "en-dash")])
def test_unicode_dashes_gate(tmp_path: Path, dash_char: str, label: str) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "with-dash")
    _commit_files(
        repo,
        {"docs/report.md": f"Headline {dash_char} subclause\n"},
        message="add unicode dash",
    )

    rep = verify_branch(base="justSilas", branch="with-dash", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["unicode_dashes"]["passed"] is False
    assert any(label in e for e in gates["unicode_dashes"]["errors"])


def test_modified_files_scan_only_added_lines_for_unicode_dashes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_files(
        repo,
        {
            "docs/reports/gap.md": f"Primary seeds 0{EN_DASH}29 headline.\nLine two.\n",
            "results/harbor/rehearsal/README.md": f"Legacy note {EM_DASH} untouched.\n",
        },
        message="seed base files with pre-existing dashes",
    )

    _git(repo, "checkout", "-b", "append-clean")
    _commit_files(
        repo,
        {
            "docs/reports/gap.md": (
                f"Primary seeds 0{EN_DASH}29 headline.\n"
                "Line two.\n"
                "G1 extension block: seeds 30-59 paired cleanly.\n"
            ),
            "results/harbor/rehearsal/README.md": (
                f"Legacy note {EM_DASH} untouched.\n"
                "Step C addendum: 30/30 valid trials.\n"
            ),
        },
        message="append clean ASCII blocks to existing markdown files",
    )

    rep_clean = verify_branch(base="justSilas", branch="append-clean", repo=repo)
    assert rep_clean["ok"] is True, rep_clean
    assert _gate_map(rep_clean)["unicode_dashes"]["passed"] is True

    _commit_files(
        repo,
        {
            "docs/reports/gap.md": (
                f"Primary seeds 0{EN_DASH}29 headline.\n"
                "Line two.\n"
                "G1 extension block: seeds 30-59 paired cleanly.\n"
                f"Newly added bad range 30{EN_DASH}59.\n"
            ),
            "results/harbor/rehearsal/README.md": (
                f"Legacy note {EM_DASH} untouched.\n"
                "Step C addendum: 30/30 valid trials.\n"
                f"Newly added clause {EM_DASH} forbidden.\n"
            ),
        },
        message="introduce new unicode dashes in modified files",
    )

    rep_bad = verify_branch(base="justSilas", branch="append-clean", repo=repo)
    assert rep_bad["ok"] is False
    errs = _gate_map(rep_bad)["unicode_dashes"]["errors"]
    assert errs == [
        "docs/reports/gap.md:4: contains en-dash",
        "results/harbor/rehearsal/README.md:3: contains em-dash",
    ]


def test_harbor_machine_logs_exempt_from_unicode_dashes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "harbor-logs")
    _commit_files(
        repo,
        {
            "results/harbor/rehearsal/opencode-1/canary-hard-900000__abc/agent/opencode.txt": f"model {EM_DASH} log\n",
            "results/harbor/rehearsal/opencode-1/canary-hard-900000__abc/agent/trajectory.json": json.dumps(
                {"text": f"step {EN_DASH} output"}
            )
            + "\n",
            "results/harbor-step-c/opencode-1/canary-hard-900001__xyz/agent/notes.md": (
                f"agent scratch {EM_DASH} notes {EN_DASH} trace\n"
            ),
            "results/harbor/rehearsal/opencode-1/canary-hard-900000__abc/exception.txt": f"Error {EM_DASH} timeout\n",
            "results/harbor/rehearsal/opencode-1/canary-hard-900000__abc/trial.log": f"trial {EN_DASH} trace\n",
            "results/custom_job/run1/trial.log": f"nested trial {EM_DASH} log\n",
            "results/custom_job/run1/exception.txt": f"nested exc {EN_DASH} log\n",
            "results/harbor/rehearsal/opencode-1/canary-hard-900000__abc/result.json": json.dumps(
                {"exc": f"boom {EM_DASH} trace"}
            )
            + "\n",
            "results/harbor/rehearsal/TABLE.md": f"| task | {EM_DASH} |\n",
            "results/harbor-step-c/sub/TABLE.md": f"| task | {EN_DASH} |\n",
            "results/harbor_3x10/TABLE.md": f"| task | {EM_DASH} |\n",
            "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/accuse.md": f"| hard | {EN_DASH} |\n",
            "results/selected_fleet_replication/v1.4/accuse.md": f"| hard | {EM_DASH} |\n",
            "results/harbor/rehearsal/README.md": "Clean human protocol note.\n",
        },
        message="add harbor rehearsal machine logs, accuse tables, and clean README",
    )

    rep_ok = verify_branch(base="justSilas", branch="harbor-logs", repo=repo, allow_data=True)
    assert rep_ok["ok"] is True, rep_ok
    assert _gate_map(rep_ok)["unicode_dashes"]["passed"] is True

    _commit_files(
        repo,
        {
            "results/harbor/rehearsal/README.md": f"Human prose {EM_DASH} forbidden dash\n",
            "results/harbor-step-c/README.md": f"Step C prose {EN_DASH} forbidden dash\n",
        },
        message="add dash in harbor READMEs",
    )
    rep_bad = verify_branch(base="justSilas", branch="harbor-logs", repo=repo, allow_data=True)
    assert rep_bad["ok"] is False
    dash_errs = _gate_map(rep_bad)["unicode_dashes"]["errors"]
    assert dash_errs == [
        "results/harbor-step-c/README.md:1: contains en-dash",
        "results/harbor/rehearsal/README.md:1: contains em-dash",
    ]


def test_results_transcripts_and_jsonl_exempt_from_unicode_dashes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "results-dash-exempt")
    _commit_files(
        repo,
        {
            "results/selected_fleet_replication/v1.4/opencode/hard-s30/transcripts/30.txt": (
                f"assistant {EM_DASH} output {EN_DASH} trace\n"
            ),
            "results/custom_sweep/run1/transcripts/7.txt": f"raw {EM_DASH} log\n",
            "results/redteam_1000/attacks.jsonl": json.dumps({"note": f"probe {EM_DASH} text"}) + "\n",
        },
        message="add machine transcripts and jsonl under results",
    )
    rep_ok = verify_branch(base="justSilas", branch="results-dash-exempt", repo=repo)
    assert rep_ok["ok"] is True, rep_ok
    assert _gate_map(rep_ok)["unicode_dashes"]["passed"] is True

    _commit_files(
        repo,
        {"results/selected_fleet_replication/README.md": f"Prose {EM_DASH} forbidden\n"},
        message="add prose markdown with dash under results",
    )
    rep_bad = verify_branch(base="justSilas", branch="results-dash-exempt", repo=repo)
    assert rep_bad["ok"] is False
    errs = _gate_map(rep_bad)["unicode_dashes"]["errors"]
    assert len(errs) == 1
    assert "results/selected_fleet_replication/README.md:1" in errs[0]


def test_selected_fleet_replication_shard_gates(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "selected-fleet-bad")

    ep_bad = _make_episode(tier="hard", seed=48, agent="opencode:google/gemini-4-carbon")
    ep_bad["meta"]["rc"] = "timeout"
    ep_bad["score"] = 0.111111
    shard = "results/selected_fleet_replication/v1.4/opencode-gemini-4-carbon/hard-s48-51"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep_bad) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [48, 49]}) + "\n",
            f"{shard}/transcripts/48.txt": "ok\n",
            f"{shard}/transcripts/99.txt": "orphan\n",
        },
        message="add malformed selected_fleet_replication shard",
    )

    rep = verify_branch(base="justSilas", branch="selected-fleet-bad", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["protected_core"]["passed"] is True
    assert gates["timeout_episode"]["passed"] is False
    assert any("rc == timeout" in e for e in gates["timeout_episode"]["errors"])
    assert gates["orphan_transcript"]["passed"] is False
    assert any("meta['seeds']" in e for e in gates["orphan_transcript"]["errors"])
    assert any("transcripts/99.txt" in e for e in gates["orphan_transcript"]["errors"])
    assert gates["replay_mismatch"]["passed"] is False
    assert len(gates["replay_mismatch"]["errors"]) == 1


def test_frontier_replication_shard_replay_and_gates(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "frontier-rep-clean")

    ep_ok = _make_episode(tier="hard", seed=34, agent="opencode:google/gemini-4-carbon")
    shard = "results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep_ok) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [34]}) + "\n",
            f"{shard}/transcripts/34.txt": f"assistant {EN_DASH} trace\n",
        },
        message="add clean frontier_replication v1.4 shard",
    )

    rep_ok = verify_branch(base="justSilas", branch="frontier-rep-clean", repo=repo)
    assert rep_ok["ok"] is True, rep_ok
    gates_ok = _gate_map(rep_ok)
    assert gates_ok["timeout_episode"]["summary"] == "1 episode file(s) checked, 0 episode violation(s)"
    assert gates_ok["orphan_transcript"]["summary"] == "1 shard manifest(s) checked, 0 manifest/transcript issue(s)"
    assert "1 v1.4 episode(s) replayed, 0 mismatch(es)" in gates_ok["replay_mismatch"]["summary"]

    _git(repo, "checkout", "-B", "frontier-rep-bad", "justSilas")
    ep_bad = _make_episode(tier="hard", seed=34, agent="opencode:google/gemini-4-carbon")
    ep_bad["meta"]["rc"] = "timeout"
    ep_bad["score"] = 0.222222
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep_bad) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [34, 35]}) + "\n",
            f"{shard}/transcripts/34.txt": "ok\n",
            f"{shard}/transcripts/99.txt": "orphan\n",
        },
        message="add malformed frontier_replication v1.4 shard",
    )

    rep_bad = verify_branch(base="justSilas", branch="frontier-rep-bad", repo=repo)
    assert rep_bad["ok"] is False
    gates_bad = _gate_map(rep_bad)
    assert gates_bad["protected_core"]["passed"] is True
    assert gates_bad["timeout_episode"]["passed"] is False
    assert gates_bad["orphan_transcript"]["passed"] is False
    assert gates_bad["replay_mismatch"]["passed"] is False
    assert len(gates_bad["replay_mismatch"]["errors"]) == 1


def test_co_authored_by_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "with-coauthor")
    trailer = "Co-Authored-" + "By: Helper <helper@example.com>"
    _commit_files(
        repo,
        {"docs/clean.md": "clean text\n"},
        message=f"docs: add clean file\n\n{trailer}",
    )

    rep = verify_branch(base="justSilas", branch="with-coauthor", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["co_authored_by"]["passed"] is False
    assert len(gates["co_authored_by"]["errors"]) == 1


def test_secret_leak_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "with-secrets")
    fake_google = "AI" + "za" + ("A" * 35)
    fake_openai = "s" + "k-" + ("B" * 24)
    fake_ghp = "gh" + "p_" + ("C" * 32)
    fake_vertex = "A" + "Q." + "AbCdEf0123456789._-XyZwVu"
    _commit_files(
        repo,
        {
            "docs/keys.txt": f"g={fake_google}\no={fake_openai}\nh={fake_ghp}\nv={fake_vertex}\n",
            ".env": "FOO=bar\n",
            "data/worlds/judge/SALT": "secret-salt-value\n",
        },
        message="accidentally commit secrets",
    )

    rep = verify_branch(base="justSilas", branch="with-secrets", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["secret_leak"]["passed"] is False
    joined = "\n".join(gates["secret_leak"]["errors"])
    assert "google_api_key" in joined
    assert "openai_secret_key" in joined
    assert "github_pat" in joined
    assert "vertex_express_key" in joined
    assert ".env: forbidden secret file path" in joined
    assert "data/worlds/judge/SALT: forbidden secret file path" in joined
    assert fake_google not in joined
    assert fake_openai not in joined
    assert fake_ghp not in joined
    assert fake_vertex not in joined


def test_timeout_episode_and_duplicate_tuples_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "bad-episodes")

    ep_timeout = _make_episode(tier="medium", seed=0, agent="agent_a")
    ep_timeout["meta"]["rc"] = "timeout"

    ep_error = _make_episode(tier="medium", seed=1, agent="agent_a")
    ep_error["end_reason"] = "error"

    ep_invalid = _make_episode(tier="medium", seed=2, agent="agent_a")
    ep_invalid["meta"]["valid"] = False

    ep_dup = _make_episode(tier="medium", seed=0, agent="agent_a")

    shard_a = "data/runs/committed/v1.4/custom-lane/medium-00-02"
    shard_b = "data/runs/committed/v1.4/custom-lane/medium-dup"
    _commit_files(
        repo,
        {
            f"{shard_a}/episodes.jsonl": "\n".join(
                json.dumps(x) for x in (ep_timeout, ep_error, ep_invalid)
            ) + "\n",
            f"{shard_a}/meta.json": json.dumps(
                {"tiers_version": "v1.4", "seeds": [0, 1, 2]}
            ) + "\n",
            f"{shard_b}/episodes.jsonl": json.dumps(ep_dup) + "\n",
            f"{shard_b}/meta.json": json.dumps(
                {"tiers_version": "v1.4", "seeds": [0]}
            ) + "\n",
        },
        message="add invalid and duplicate episodes",
    )

    rep = verify_branch(
        base="justSilas", branch="bad-episodes", repo=repo, allow_data=True, skip_replay=True
    )
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["timeout_episode"]["passed"] is False
    joined = "\n".join(gates["timeout_episode"]["errors"])
    assert "rc == timeout" in joined
    assert "end_reason == error" in joined
    assert "meta.valid is False" in joined
    assert "duplicate (agent, tier, seed)" in joined


def test_orphan_transcript_and_manifest_seeds_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "orphan-shard")

    ep = _make_episode(tier="medium", seed=5, agent="agent_b")
    shard = "data/runs/committed/v1.4/custom-lane/medium-05"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [5, 6]}) + "\n",
            f"{shard}/transcripts/5.txt": "valid transcript\n",
            f"{shard}/transcripts/99.txt": "orphan transcript\n",
        },
        message="add shard with mismatched seeds and orphan transcript",
    )

    rep = verify_branch(
        base="justSilas", branch="orphan-shard", repo=repo, allow_data=True, skip_replay=True
    )
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["orphan_transcript"]["passed"] is False
    joined = "\n".join(gates["orphan_transcript"]["errors"])
    assert "meta['seeds']" in joined
    assert "transcripts/99.txt: orphan transcript" in joined


def test_replay_mismatch_and_skip_replay_gate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "tampered-replay")

    ep = _make_episode(tier="medium", seed=3, agent="agent_c")
    ep["score"] = 0.987654321
    shard = "data/runs/committed/v1.4/custom-lane/medium-03"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [3]}) + "\n",
        },
        message="add tampered episode score",
    )

    rep = verify_branch(base="justSilas", branch="tampered-replay", repo=repo, allow_data=True)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["replay_mismatch"]["passed"] is False
    assert len(gates["replay_mismatch"]["errors"]) == 1

    rep_skipped = verify_branch(
        base="justSilas",
        branch="tampered-replay",
        repo=repo,
        allow_data=True,
        skip_replay=True,
    )
    assert rep_skipped["ok"] is True
    assert _gate_map(rep_skipped)["replay_mismatch"]["passed"] is True


def test_markdown_links_gate_valid_excluded_and_fences(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "clean-links")
    md_body = "\n".join(
        [
            f"{HASH_CHAR} Guide",
            "",
            "- History table: [v1.3](../results/history/fresh_table_v1.3.md)",
            "- History folder: [history dir](../results/history/)",
            f'- Readme section: [readme](../README.md{HASH_CHAR}headline "Main Readme")',
            "- Code label: [`core.py`](../canary/solver/core.py)",
            "- Root-relative: [root](/README.md)",
            "- Chart image: ![chart](../results/gap_chart.png)",
            "- External HTTP: [plain](http://example.com/missing.md)",
            "- External HTTPS: [tls](https://example.com/missing_(1).md)",
            "- External mailto: [mail](mailto:ops@example.com)",
            f"- Intra-file anchor: [jump]({HASH_CHAR}guide)",
            "- Inline code syntax example: `[broken](does_not_exist.md)`",
            "",
            "```markdown",
            "[fenced backtick broken](missing_backtick.md)",
            "```",
            "",
            "~~~md",
            "[fenced tilde broken](missing_tilde.md)",
            "~~~",
            "",
        ]
    )
    _commit_files(
        repo,
        {
            "results/history/fresh_table_v1.3.md": "v1.3 table\n",
            "results/gap_chart.png": "placeholder\n",
            "docs/guide.md": md_body,
        },
        message="docs: add clean links and history targets",
    )

    rep = verify_branch(base="justSilas", branch="clean-links", repo=repo)
    assert rep["ok"] is True, rep
    gates = _gate_map(rep)
    assert gates["markdown_links"]["passed"] is True
    assert gates["markdown_links"]["errors"] == []
    assert "6 relative link(s), 0 broken" in gates["markdown_links"]["summary"]


def test_markdown_links_gate_catches_broken_and_moved_targets(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_files(
        repo,
        {"results/fresh_table_v1.3.md": "legacy v1.3 table\n"},
        message="add pre-PR32 table path",
    )

    _git(repo, "checkout", "-b", "stale-doc-pr")
    stale_md = "\n".join(
        [
            "Moved target: [v1.3](../results/fresh_table_v1.3.md)",
            "Missing sibling: [gone](nonexistent_doc.md)",
            "Escaped root: [outside](../../outside.md)",
            "Code-labelled missing: [`missing.py`](missing_script.py)",
            "",
        ]
    )
    _commit_files(repo, {"docs/summary.md": stale_md}, message="docs: link to legacy table")

    _git(repo, "checkout", "justSilas")
    (repo / "results" / "history").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "results/fresh_table_v1.3.md", "results/history/fresh_table_v1.3.md")
    _git(repo, "commit", "-m", "move v1.3 table to results/history")

    rep = verify_branch(base="justSilas", branch="stale-doc-pr", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["markdown_links"]["passed"] is False
    assert len(gates["markdown_links"]["errors"]) == 4
    joined = "\n".join(gates["markdown_links"]["errors"])
    assert "results/fresh_table_v1.3.md" in joined
    assert "docs/nonexistent_doc.md" in joined
    assert "../outside.md" in joined
    assert "docs/missing_script.py" in joined


def _build_opencode_artifact_episode(
    tier: str = "hard",
    seed: int = 30,
    fill_to_cap: bool = True,
    tamper: str | None = None,
) -> dict[str, Any]:
    env = Env(tier, seed)
    n_status = (env.p.tool_call_cap - 2) if fill_to_cap else 3
    for _ in range(n_status):
        env.call("status", {})
    env.call("read_access_logs", {"day_from": 999, "day_to": 999})
    env.call("accuse", {"employee": "e00"})
    ep = asdict(env.result("opencode:google/gemini-3.5-flash"))
    ep["meta"] = {"rc": 0, "valid": True}

    first_payload_bytes = len(json.dumps(ep["steps"][0]["result"]).encode("utf-8"))
    reported_bytes = first_payload_bytes + (1 if tamper == "wrong_trunc_bytes" else 0)
    ep["steps"][0]["result"] = {
        "raw": (
            f"\n\n...{reported_bytes} bytes truncated...\n\n"
            "The tool call succeeded but the output was truncated. "
            "Full output saved to: /tmp/oc/tool-output/tool_1\n"
        )
    }

    err_step = ep["steps"][-2]
    err_step["result"] = {"ok": False, "error": json.dumps(err_step["result"])}

    refused_result = {
        "ok": False,
        "error": "Model tried to call unavailable tool 'invalid'. Available tools: canary_accuse.",
    }
    if tamper == "disguised_env_call":
        ep["steps"][1]["result"] = dict(refused_result)
    elif tamper == "tampered_step_result":
        ep["steps"][1]["result"] = {"ok": True, "data": {"tampered": True}, "error": None}
    else:
        for idx, client_tool in enumerate(("bash", "read", "invalid")):
            ep["steps"].insert(
                1 + idx,
                {
                    "t": 1 + idx,
                    "day": 1,
                    "tool": client_tool,
                    "args": {"command": "ls"},
                    "result": dict(refused_result),
                },
            )
    return ep


def test_replay_accepts_opencode_client_artifacts_at_tool_cap(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "oc-artifacts-clean")

    ep = _build_opencode_artifact_episode(tier="hard", seed=30, fill_to_cap=True, tamper=None)
    shard = "results/replication/v1.4/opencode-gemini-3.5-flash/hard-s30"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [30]}) + "\n",
        },
        message="add opencode episode with client-only tools and truncated output at tool cap",
    )

    rep = verify_branch(base="justSilas", branch="oc-artifacts-clean", repo=repo)
    assert rep["ok"] is True, rep
    gates = _gate_map(rep)
    assert gates["replay_mismatch"]["passed"] is True
    assert "3 client-only skipped, 1 truncated checked" in gates["replay_mismatch"]["summary"]


@pytest.mark.parametrize(
    "tamper",
    ["wrong_trunc_bytes", "disguised_env_call", "tampered_step_result"],
)
def test_replay_catches_tampering_behind_opencode_artifacts(tmp_path: Path, tamper: str) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", f"oc-tamper-{tamper}")

    ep = _build_opencode_artifact_episode(tier="medium", seed=4, fill_to_cap=False, tamper=tamper)
    shard = "results/replication/v1.4/opencode-gemini-3.5-flash/medium-s04"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [4]}) + "\n",
        },
        message=f"add tampered opencode episode ({tamper})",
    )

    rep = verify_branch(base="justSilas", branch=f"oc-tamper-{tamper}", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["replay_mismatch"]["passed"] is False
    assert len(gates["replay_mismatch"]["errors"]) == 1
    assert "step_mismatches=" in gates["replay_mismatch"]["errors"][0]


def test_replay_accepts_pre_detail_invalid_arguments_steps(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "pre-detail-errors")

    env = Env("medium", 5)
    r_bad = env.call("interview", {"employee": "e01", "topic": "leaks"})
    assert not r_bad.ok and r_bad.error == "invalid arguments" and "detail" in r_bad.data
    steps = [
        {
            "t": 0,
            "day": 1,
            "tool": "interview",
            "args": {"employee": "e01", "topic": "leaks"},
            "result": {"ok": False, "data": {}, "error": "invalid arguments"},
        },
        {
            "t": 1,
            "day": 1,
            "tool": "interview",
            "args": {"employee": "e01", "topic": "leaks"},
            "result": {
                "ok": False,
                "error": json.dumps({"ok": False, "data": {}, "error": "invalid arguments"}),
            },
        },
    ]
    env.call("interview", {"employee": "e01", "topic": "leaks"})
    ep = {
        "agent": "opencode:google/gemini-4-carbon",
        "tier": "medium",
        "seed": 5,
        "score": env.score(),
        "accused": env.verdict()["accused"],
        "steps": steps,
        "meta": {"valid": True},
    }
    shard = "results/selected_fleet_replication/v1.4/opencode-gemini-4-carbon/medium-s05"
    _commit_files(
        repo,
        {
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps({"tiers_version": "v1.4", "seeds": [5]}) + "\n",
        },
        message="add pre-detail invalid arguments episode",
    )

    rep = verify_branch(base="justSilas", branch="pre-detail-errors", repo=repo)
    assert rep["ok"] is True, rep
    gates = _gate_map(rep)
    assert gates["replay_mismatch"]["passed"] is True


def test_self_hygiene_zero_comments_and_dashes() -> None:
    for py_rel in ("scripts/verify_pr_branch.py", "tests/test_verify_pr_branch.py"):
        raw = (ROOT / py_rel).read_bytes()
        comments = [
            tok for tok in tokenize.tokenize(io.BytesIO(raw).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], f"unexpected comments in {py_rel}: {comments}"
        txt = raw.decode("utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt


def test_live_repo_prs_smoke() -> None:
    for ref in ("origin/justSilas", "origin/fr8/afterquery/prs"):
        chk = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=str(ROOT),
            capture_output=True,
            check=False,
        )
        if chk.returncode != 0:
            pytest.skip(f"missing ref {ref}")

    report = verify_branch(
        base="origin/justSilas",
        branch="origin/fr8/afterquery/prs",
        repo=ROOT,
    )
    assert report["ok"] is True, report
