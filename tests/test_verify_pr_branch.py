"""Unit and smoke tests for scripts/verify_pr_branch.py."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
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
    shard = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard-s30-59"
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
            "docs/note.md": "Clean summary - ASCII hyphen only.\n",
            f"{shard}/episodes.jsonl": json.dumps(ep) + "\n",
            f"{shard}/meta.json": json.dumps(meta, indent=2) + "\n",
            f"{shard}/transcripts/30.txt": "step 1 ok\n",
        },
        message="feat: add helper and clean hard-s30-59 shard",
    )

    rc_json = main(["--repo", str(repo), "--base", "justSilas", "--branch", "feat", "--json"])
    out_json = capsys.readouterr().out
    assert rc_json == 0
    parsed = json.loads(out_json)
    assert parsed["ok"] is True
    assert parsed["ff_base"] is True
    assert parsed["changed_files"] == 5
    gates = _gate_map(parsed)
    assert len(gates) == 10
    assert all(g["passed"] for g in parsed["gates"])

    rc_txt = main(["--repo", str(repo), "--base", "justSilas", "--branch", "feat"])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "OVERALL: PASS (10/10 gates passed)" in out_txt


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
        "canary/solver/core.py",
        "canary/reproduce.py",
        "harbor/build.py",
        "harbor/new_file.txt",
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

    rep_allowed = verify_branch(base="justSilas", branch="touch-core", repo=repo, allow_core=True)
    assert rep_allowed["ok"] is True
    assert _gate_map(rep_allowed)["protected_core"]["passed"] is True


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

    rep = verify_branch(base="justSilas", branch="touch-reserved", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
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
    _commit_files(
        repo,
        {
            "docs/keys.txt": f"g={fake_google}\no={fake_openai}\nh={fake_ghp}\n",
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
    assert ".env: forbidden secret file path" in joined
    assert "data/worlds/judge/SALT: forbidden secret file path" in joined
    assert fake_google not in joined
    assert fake_openai not in joined
    assert fake_ghp not in joined


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

    rep = verify_branch(base="justSilas", branch="bad-episodes", repo=repo, skip_replay=True)
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

    rep = verify_branch(base="justSilas", branch="orphan-shard", repo=repo, skip_replay=True)
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

    rep = verify_branch(base="justSilas", branch="tampered-replay", repo=repo)
    assert rep["ok"] is False
    gates = _gate_map(rep)
    assert gates["replay_mismatch"]["passed"] is False
    assert len(gates["replay_mismatch"]["errors"]) == 1

    rep_skipped = verify_branch(
        base="justSilas",
        branch="tampered-replay",
        repo=repo,
        skip_replay=True,
    )
    assert rep_skipped["ok"] is True
    assert _gate_map(rep_skipped)["replay_mismatch"]["passed"] is True


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
