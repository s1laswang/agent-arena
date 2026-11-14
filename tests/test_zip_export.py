"""Tests for ``scripts/verify_zip_export.py`` (GitHub ZIP / gitless export verifier)."""
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
SCRIPT_PATH = ROOT / "scripts" / "verify_zip_export.py"
OPENCODE_TMP = Path("/tmp/opencode")


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_zip_export", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verify_zip_export = _load_verifier()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-zip-export-") as tmp_str:
        yield Path(tmp_str)


def _write_secret(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)


def _populate_valid_harbor_task(out_dir: Path, tier: str = "hard", seed: int = 900000) -> Path:
    task_dir = out_dir / f"canary-{tier}-{seed}"
    (task_dir / "environment" / "canary-server").mkdir(parents=True, exist_ok=True)
    (task_dir / "tests").mkdir(parents=True, exist_ok=True)
    (task_dir / "solution").mkdir(parents=True, exist_ok=True)
    (task_dir / "instruction.md").write_text("Play through MCP.\n", encoding="utf-8")
    (task_dir / "environment" / ".dockerignore").write_text("canary-server\n", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        "\n".join(
            [
                '[task]',
                f'name = "canary/{tier}-{seed}"',
                "",
                "[metadata]",
                f'tier = "{tier}"',
                "",
                "[verifier]",
                'environment_mode = "separate"',
                "",
                "[[verifier.collect]]",
                'service = "canary-server"',
                'path = "/tmp/ledger.json"',
                "",
                "[environment]",
                'workdir = "/app"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    sidecar = task_dir / "environment" / "canary-server"
    _write_secret(sidecar / "data" / "worlds" / "judge" / "SALT", b"s" * 32)
    ep_file = sidecar / "episode.json"
    ep_file.write_text(json.dumps({"tier": tier, "seed": seed}), encoding="utf-8")
    ep_file.chmod(0o600)
    key_bytes = b"k" * 64
    _write_secret(sidecar / "ledger_key", key_bytes)
    _write_secret(task_dir / "tests" / "ledger_key", key_bytes)
    return task_dir


def _make_synthetic_good_runner():
    def _runner(
        cmd: list[str],
        cwd: Path,
        env_overrides: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        joined = " ".join(cmd)
        if "canary.eval" in joined and "--reproduce" in cmd:
            assert env_overrides.get("REPRO_SEEDS") == "2"
            assert env_overrides.get("REPRO_ANTICHEAT") == "0"
            latest = cwd / "results" / "latest"
            latest.mkdir(parents=True, exist_ok=True)
            table_txt = "Canary judge table\n\n- git: `unknown`, generated 2026-11-14T00:00:00+0000, 0.1 s\n"
            (latest / "judge_table.md").write_text(table_txt, encoding="utf-8")
            (latest / "judge_episodes.jsonl").write_text(
                json.dumps({"tier": "hard", "agent": "solver", "seed": 900000, "score": 0.8}) + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=table_txt, stderr="")

        if "harbor/build.py" in joined:
            out_idx = cmd.index("--out") + 1
            _populate_valid_harbor_task(Path(cmd[out_idx]))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="wrote 1 task\n", stderr="")

        if "scripts/demo_replay.py" in joined:
            out = (
                "verify solver recorded +0.73 replayed +0.73 -> MATCH\n"
                "verify gemini recorded +0.40 replayed +0.40 -> MATCH\n"
            )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr="")

        if "-c" in cmd:
            probe_out = json.dumps(
                {
                    "tiers_version": "v1.4",
                    "tier_hash": "a8f99c2537c91d72",
                    "rules_file": str((cwd / "canary" / "rules.py").resolve()),
                }
            )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=probe_out + "\n", stderr="")

        if "pytest" in joined:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="4 passed\n", stderr="")

        raise AssertionError(f"unexpected runner command: {cmd}")

    return _runner


def test_real_repo_zip_export_passes(capsys):
    before = {p.name for p in OPENCODE_TMP.glob("canary-zip-export-*")} if OPENCODE_TMP.exists() else set()
    rc = verify_zip_export.main(["--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 0
    assert payload["passed"] is True
    assert len(payload["results"]) == 5
    assert payload["checks"] == payload["results"]
    assert [r["name"] for r in payload["results"]] == list(verify_zip_export.CHECK_NAMES)
    for item in payload["results"]:
        assert item["status"] == "PASS", item

    after = {p.name for p in OPENCODE_TMP.glob("canary-zip-export-*")}
    assert after - before == set()


@pytest.mark.parametrize("dot_git_kind", ["dir", "file", "symlink"])
def test_dot_git_unexpectedly_exists_in_archive_target_fails(
    opencode_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    dot_git_kind: str,
):
    runner_called = False

    def _unexpected_runner(cmd: list[str], cwd: Path, env_overrides: dict[str, str]):
        nonlocal runner_called
        runner_called = True
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    def _bad_exporter(_root: Path, export_dir: Path) -> None:
        dot_git = export_dir / ".git"
        if dot_git_kind == "dir":
            dot_git.mkdir(parents=True, exist_ok=True)
        elif dot_git_kind == "file":
            dot_git.write_text("gitdir: /nonexistent/worktree\n", encoding="utf-8")
        else:
            dot_git.symlink_to(opencode_tmp / "dangling-git-target")

    monkeypatch.setattr(verify_zip_export, "TMP_BASE", opencode_tmp)
    monkeypatch.setattr(verify_zip_export, "export_head", _bad_exporter)
    monkeypatch.setattr(verify_zip_export, "default_runner", _unexpected_runner)

    rc = verify_zip_export.main(["--root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["passed"] is False
    assert runner_called is False
    assert len(payload["results"]) == 5
    for item in payload["results"]:
        assert item["status"] == "FAIL"
        assert ".git" in item["summary"]


def test_individual_checks_reject_dot_git_directory(opencode_tmp: Path):
    contaminated = opencode_tmp / "contaminated_export"
    (contaminated / ".git").mkdir(parents=True)
    harbor_out = opencode_tmp / "harbor_out"

    results = [
        verify_zip_export.check_keyless_mini_reproduce(contaminated),
        verify_zip_export.check_harbor_build(contaminated, harbor_out),
        verify_zip_export.check_judge_analysis_scripts(contaminated),
        verify_zip_export.check_frozen_tier_hash(contaminated),
        verify_zip_export.check_security_tests(contaminated),
    ]
    for res in results:
        assert res.status == "FAIL"
        assert ".git" in res.summary


@pytest.mark.parametrize(
    ("target_token", "expected_failed_check"),
    [
        ("canary.eval", verify_zip_export.CHECK_MINI_REPRODUCE),
        ("harbor/build.py", verify_zip_export.CHECK_HARBOR_BUILD),
        ("scripts/demo_replay.py", verify_zip_export.CHECK_JUDGE_SCRIPTS),
        (" -c ", verify_zip_export.CHECK_FROZEN_TIER_HASH),
        ("pytest", verify_zip_export.CHECK_SECURITY_TESTS),
    ],
)
def test_runner_failure_detected_for_each_check(
    opencode_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    target_token: str,
    expected_failed_check: str,
):
    good_runner = _make_synthetic_good_runner()

    def _noop_exporter(_root: Path, export_dir: Path) -> None:
        (export_dir / "canary").mkdir(parents=True, exist_ok=True)
        (export_dir / "canary" / "rules.py").write_text("TIERS_VERSION = 'v1.4'\n", encoding="utf-8")

    def _selective_failing_runner(
        cmd: list[str],
        cwd: Path,
        env_overrides: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        padded = " " + " ".join(cmd) + " "
        if target_token in padded:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=2,
                stdout="",
                stderr=f"synthetic failure for {expected_failed_check}",
            )
        return good_runner(cmd, cwd, env_overrides)

    monkeypatch.setattr(verify_zip_export, "TMP_BASE", opencode_tmp)
    monkeypatch.setattr(verify_zip_export, "export_head", _noop_exporter)
    monkeypatch.setattr(verify_zip_export, "default_runner", _selective_failing_runner)

    rc = verify_zip_export.main(["--root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name[expected_failed_check]["status"] == "FAIL"
    assert any("synthetic failure" in d for d in by_name[expected_failed_check]["details"])
    for name, item in by_name.items():
        if name != expected_failed_check:
            assert item["status"] == "PASS"


def test_content_and_permission_regressions_detected(opencode_tmp: Path):
    export_dir = opencode_tmp / "clean_export"
    (export_dir / "canary").mkdir(parents=True, exist_ok=True)
    (export_dir / "canary" / "rules.py").write_text("TIERS_VERSION = 'v1.4'\n", encoding="utf-8")

    def _repro_missing_git_unknown(cmd: list[str], cwd: Path, _env: dict[str, str]):
        latest = cwd / "results" / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        (latest / "judge_table.md").write_text("- git: `1bfb77dce970`\n", encoding="utf-8")
        (latest / "judge_episodes.jsonl").write_text('{"score": 0.5}\n', encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    res_repro = verify_zip_export.check_keyless_mini_reproduce(export_dir, runner=_repro_missing_git_unknown)
    assert res_repro.status == "FAIL"
    assert any("git: unknown" in d for d in res_repro.details)

    harbor_out = opencode_tmp / "harbor_bad_perm"

    def _harbor_bad_salt_perm(cmd: list[str], _cwd: Path, _env: dict[str, str]):
        out_dir = Path(cmd[cmd.index("--out") + 1])
        task_dir = _populate_valid_harbor_task(out_dir)
        (task_dir / "environment" / "canary-server" / "data" / "worlds" / "judge" / "SALT").chmod(0o644)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok\n", stderr="")

    res_harbor = verify_zip_export.check_harbor_build(export_dir, harbor_out, runner=_harbor_bad_salt_perm)
    assert res_harbor.status == "FAIL"
    assert any("SALT mode expected 0o600" in d for d in res_harbor.details)

    def _replay_mismatch(cmd: list[str], _cwd: Path, _env: dict[str, str]):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="verify solver recorded +0.73 replayed +0.10 -> MISMATCH\n",
            stderr="",
        )

    res_replay = verify_zip_export.check_judge_analysis_scripts(export_dir, runner=_replay_mismatch)
    assert res_replay.status == "FAIL"

    def _wrong_tier_hash(cmd: list[str], cwd: Path, _env: dict[str, str]):
        bad = json.dumps(
            {
                "tiers_version": "v1.4",
                "tier_hash": "0000000000000000",
                "rules_file": str((cwd / "canary" / "rules.py").resolve()),
            }
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=bad, stderr="")

    res_hash = verify_zip_export.check_frozen_tier_hash(export_dir, runner=_wrong_tier_hash)
    assert res_hash.status == "FAIL"
    assert any("a8f99c2537c91d72" in d for d in res_hash.details)


def test_non_git_root_and_text_report(opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    not_a_repo = opencode_tmp / "plain_dir"
    not_a_repo.mkdir()
    monkeypatch.setattr(verify_zip_export, "TMP_BASE", opencode_tmp)

    rc = verify_zip_export.main(["--root", str(not_a_repo)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "[FAIL]" in out
    assert "SUMMARY: 0 PASS, 0 WARN, 5 FAIL" in out
