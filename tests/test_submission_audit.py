from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from canary import reproduce as R
from canary import rules
from harbor.build import build_task

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_submission.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_submission", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit_module()


def _init_git_repo(repo: Path, files: dict[str, bytes | str], gitignore: str = "results/latest/\n") -> None:
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
    subprocess.run(["git", "add", "-f", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _write_committed_run(
    root: Path,
    rel_dir: str,
    episodes: list[dict],
    meta: dict | None = None,
) -> Path:
    run_dir = root / "data" / "runs" / "committed" / rel_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(ep) for ep in episodes) + "\n",
        encoding="utf-8",
    )
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return run_dir


def test_real_repo_passes_audit(capsys):
    rc = audit.main(["--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 30.0   # wall clock; the host can be heavily loaded during the hackathon
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["Secret & Answer-Key Hygiene"]["status"] == "PASS"
    assert by_name["Frozen Tier Hashes"]["status"] == "PASS"
    assert by_name["Committed Runs Integrity"]["status"] in {"PASS", "WARN"}
    assert by_name["Harbor Package Static Audit"]["status"] == "PASS"


def test_secret_hygiene_clean_and_leaks(tmp_path):
    clean_repo = tmp_path / "clean"
    _init_git_repo(
        clean_repo,
        {
            ".env.example": "GEMINI_API_KEY=\n",
            "src/app.py": "x = 1\n",
        },
    )
    res_clean = audit.check_secret_hygiene(clean_repo)
    assert res_clean.status == "PASS"

    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    assert audit.check_secret_hygiene(non_git).status == "FAIL"

    env_repo = tmp_path / "env_leak"
    _init_git_repo(env_repo, {".env": "SECRET=1\n"})
    res_env = audit.check_secret_hygiene(env_repo)
    assert res_env.status == "FAIL"
    assert any(".env" in d for d in res_env.details)

    salt_repo = tmp_path / "salt_leak"
    _init_git_repo(salt_repo, {"data/worlds/judge/SALT": b"0123456789abcdef0123456789abcdef"})
    res_salt = audit.check_secret_hygiene(salt_repo)
    assert res_salt.status == "FAIL"
    assert any("SALT" in d for d in res_salt.details)

    world_repo = tmp_path / "world_leak"
    _init_git_repo(world_repo, {"data/worlds/900000.world.json": json.dumps({"tier": "medium", "mole": "e04"})})
    res_world = audit.check_secret_hygiene(world_repo)
    assert res_world.status == "FAIL"
    assert any("mole" in d for d in res_world.details)

    sanitized_world_repo = tmp_path / "world_warn"
    _init_git_repo(sanitized_world_repo, {"data/worlds/900000.world.json": json.dumps({"tier": "medium"})})
    res_world_warn = audit.check_secret_hygiene(sanitized_world_repo)
    assert res_world_warn.status == "WARN"

    fake_google_key = "AI" + "za" + "SySyntheticKey" + ("X" * 22)
    fake_sk_key = "s" + "k-proj-" + ("Y" * 24)
    key_repo = tmp_path / "key_leak"
    _init_git_repo(
        key_repo,
        {
            "keys.txt": f"g={fake_google_key}\no={fake_sk_key}\n",
        },
    )
    res_key = audit.check_secret_hygiene(key_repo)
    assert res_key.status == "FAIL"
    joined = "\n".join(res_key.details)
    assert "google_api_key" in joined and "sk_api_key" in joined
    assert fake_google_key not in joined
    assert fake_sk_key not in joined


def test_frozen_tiers_catches_drift(monkeypatch):
    assert audit.check_frozen_tiers().status == "PASS"

    monkeypatch.setattr(rules, "TIERS_VERSION", "v1.5")
    res_ver = audit.check_frozen_tiers()
    assert res_ver.status == "FAIL"
    assert any("TIERS_VERSION" in d for d in res_ver.details)

    monkeypatch.setattr(rules, "TIERS_VERSION", "v1.4")
    monkeypatch.setitem(rules.TIERS, "hard", replace(rules.TIERS["hard"], n_days=99))
    res_v14 = audit.check_frozen_tiers()
    assert res_v14.status == "FAIL"
    assert any("a8f99c2537c91d72" in d for d in res_v14.details)

    monkeypatch.undo()
    monkeypatch.setitem(rules.TIERS_V13, "hard", replace(rules.TIERS_V13["hard"], n_days=99))
    res_v13 = audit.check_frozen_tiers()
    assert res_v13.status == "FAIL"
    assert any("8df71cf570bb48bc" in d for d in res_v13.details)


def test_committed_runs_clean_and_superseded_ignored(tmp_path):
    _write_committed_run(
        tmp_path,
        "v1.4/agent_a/medium",
        [
            {"tier": "medium", "seed": 900000, "agent": "agent_a", "score": 0.72, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 8, "meta": {}},
            {"tier": "medium", "seed": 900001, "agent": "agent_a", "score": -1.0, "accused": "e02", "correct": False, "end_reason": "accused", "final_day": 9, "meta": {}},
            {"tier": "medium", "seed": 900002, "agent": "agent_a", "score": 0.0, "accused": None, "correct": False, "end_reason": "horizon", "final_day": 14, "meta": {}},
            {"tier": "medium", "seed": 900003, "agent": "agent_a", "score": 0.0, "accused": "e03", "correct": True, "end_reason": "accused", "final_day": 7, "meta": {"V": 0.0}},
        ],
        meta={"tiers_version": "v1.4", "timestamp": "2026-11-14T10:00:00"},
    )
    _write_committed_run(
        tmp_path,
        "superseded/v1.4/agent_a/medium",
        [
            {"tier": "medium", "seed": 900000, "agent": "agent_a", "score": 9.99, "accused": None, "correct": True, "meta": {}},
        ],
        meta={"tiers_version": "v1.4"},
    )
    res = audit.check_committed_runs(tmp_path)
    assert res.status == "PASS"


def test_committed_runs_flags_valid_false_and_catches_inclusion(tmp_path):
    _write_committed_run(
        tmp_path,
        "v1.4/agent_b/hard",
        [
            {"tier": "hard", "seed": 900000, "agent": "agent_b", "score": 0.8, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 10, "meta": {"valid": True}},
            {"tier": "hard", "seed": 900001, "agent": "agent_b", "score": 0.0, "accused": None, "correct": False, "end_reason": "error", "final_day": 1, "meta": {"valid": False, "error": "infra:provider_quota"}},
        ],
        meta={"tiers_version": "v1.4", "timestamp": "2026-11-14T10:00:00"},
    )
    warn_res = audit.check_committed_runs(tmp_path)
    assert warn_res.status == "WARN"
    assert len(warn_res.details) == 1
    assert "infra:provider_quota" in warn_res.details[0]

    def _buggy_loader(root: Path):
        rows, labels = R.load_committed(root)
        leaked_rows = []
        for r in rows:
            bad = copy.deepcopy(r)
            bad.scores.append(0.0)
            bad.seeds.append(900001)
            bad.correct.append(False)
            leaked_rows.append(bad)
        return leaked_rows, labels

    fail_res = audit.check_committed_runs(tmp_path, load_committed_fn=_buggy_loader)
    assert fail_res.status == "FAIL"
    assert any("valid:false" in d for d in fail_res.details)

    top_level_invalid = tmp_path / "top_level"
    _write_committed_run(
        top_level_invalid,
        "v1.4/agent_c/hard",
        [
            {"tier": "hard", "seed": 900000, "agent": "agent_c", "score": 0.6, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 10, "meta": {}},
            {"tier": "hard", "seed": 900001, "agent": "agent_c", "score": 0.0, "accused": None, "correct": False, "end_reason": "error", "final_day": 1, "valid": False, "meta": {}},
        ],
        meta={"tiers_version": "v1.4"},
    )
    res_top = audit.check_committed_runs(top_level_invalid)
    assert res_top.status == "FAIL"


def test_committed_runs_catches_duplicate_seeds(tmp_path):
    same_file = tmp_path / "same_file"
    _write_committed_run(
        same_file,
        "v1.4/agent_d/medium",
        [
            {"tier": "medium", "seed": 900000, "agent": "agent_d", "score": 0.5, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 5, "meta": {}},
            {"tier": "medium", "seed": 900000, "agent": "agent_d", "score": -1.0, "accused": "e02", "correct": False, "end_reason": "accused", "final_day": 6, "meta": {}},
        ],
        meta={"tiers_version": "v1.4"},
    )
    res_same = audit.check_committed_runs(same_file)
    assert res_same.status == "FAIL"
    assert any("duplicate" in d for d in res_same.details)

    cross_dir = tmp_path / "cross_dir"
    _write_committed_run(
        cross_dir,
        "v1.4/shard1/medium",
        [{"tier": "medium", "seed": 900005, "agent": "agent_d", "score": 0.5, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 5, "meta": {}}],
        meta={"tiers_version": "v1.4", "timestamp": "2026-11-14T01:00:00"},
    )
    _write_committed_run(
        cross_dir,
        "v1.4/shard2/medium",
        [{"tier": "medium", "seed": 900005, "agent": "agent_d", "score": 0.7, "accused": "e01", "correct": True, "end_reason": "accused", "final_day": 4, "meta": {}}],
        meta={"tiers_version": "v1.4", "timestamp": "2026-11-14T02:00:00"},
    )
    res_cross = audit.check_committed_runs(cross_dir)
    assert res_cross.status == "FAIL"
    assert any("duplicate" in d for d in res_cross.details)


@pytest.mark.parametrize(
    "bad_ep",
    [
        {"tier": "medium", "seed": 1, "agent": "x", "score": 1.2, "accused": "e01", "correct": True, "meta": {}},
        {"tier": "medium", "seed": 1, "agent": "x", "score": -1.5, "accused": "e01", "correct": False, "meta": {}},
        {"tier": "medium", "seed": 1, "agent": "x", "score": 0.0, "accused": "e01", "correct": True, "meta": {}},
        {"tier": "medium", "seed": 1, "agent": "x", "score": 0.4, "accused": None, "correct": False, "meta": {}},
        {"tier": "medium", "seed": 1, "agent": "x", "score": 0.0, "accused": "e01", "correct": False, "meta": {}},
        {"tier": "medium", "seed": 1, "agent": "x", "score": 0.5, "accused": "e01", "correct": False, "meta": {}},
        {"tier": "hard", "seed": 1, "agent": "x", "score": 0.0, "accused": None, "correct": False, "end_reason": "error", "meta": {"rc": "timeout", "valid": True}},
    ],
)
def test_committed_runs_catches_score_invariant_violations(tmp_path, bad_ep):
    _write_committed_run(tmp_path, "v1.4/bad/medium", [bad_ep], meta={"tiers_version": "v1.4"})
    res = audit.check_committed_runs(tmp_path)
    assert res.status == "FAIL"


@pytest.mark.parametrize("rc,note,score,accused,expected", [
    (0, "agent stopped without ending the episode: final text only", 0.0, None, "PASS"),
    ("timeout", "agent stopped without ending the episode", 0.0, None, "FAIL"),
    (1, "agent stopped without ending the episode", 0.0, None, "FAIL"),
    (0, "provider request failed", 0.0, None, "FAIL"),
    (0, "agent stopped without ending the episode", 0.5, None, "FAIL"),
    (0, "agent stopped without ending the episode", 0.0, "e00", "FAIL"),
])
def test_clean_agent_stop_is_not_an_infrastructure_failure(tmp_path, rc, note, score, accused, expected):
    ep = {"tier": "hard", "seed": 1, "agent": "x", "score": score,
          "accused": accused, "correct": False, "end_reason": "error",
          "meta": {"rc": rc, "note": note, "valid": True}}
    _write_committed_run(tmp_path, "v1.4/agent/hard", [ep], meta={"tiers_version": "v1.4"})
    assert audit.check_committed_runs(tmp_path).status == expected


def test_harbor_package_audit_and_synthetic_failures(tmp_path):
    base_out = tmp_path / "harbor_ok"
    base_out.mkdir()
    built = build_task(base_out, "hard", 900000, "separate", b"w" * 32, b"k" * 64)
    assert audit.check_harbor_package(ROOT, task_dir=built).status == "PASS"

    def _clone_case(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(built, dst)
        (dst / "environment" / "canary-server" / "data" / "worlds" / "judge" / "SALT").chmod(0o600)
        (dst / "environment" / "canary-server" / "episode.json").chmod(0o600)
        (dst / "environment" / "canary-server" / "ledger_key").chmod(0o600)
        (dst / "tests" / "ledger_key").chmod(0o600)
        return dst

    c_shared = _clone_case("shared_mode")
    toml_txt = (c_shared / "task.toml").read_text(encoding="utf-8")
    (c_shared / "task.toml").write_text(toml_txt.replace('environment_mode = "separate"', 'environment_mode = "shared"'), encoding="utf-8")
    res_shared = audit.check_harbor_package(ROOT, task_dir=c_shared)
    assert res_shared.status == "FAIL"
    assert any("environment_mode" in d for d in res_shared.details)

    c_nocollect = _clone_case("no_collect")
    toml_no_collect = toml_txt.split("[[verifier.collect]]")[0] + "\n[agent]\ntimeout_sec = 60.0\n\n[environment]\nworkdir = \"/app\"\n"
    (c_nocollect / "task.toml").write_text(toml_no_collect, encoding="utf-8")
    res_nocollect = audit.check_harbor_package(ROOT, task_dir=c_nocollect)
    assert res_nocollect.status == "FAIL"
    assert any("verifier.collect" in d for d in res_nocollect.details)

    c_envleak = _clone_case("env_leak")
    (c_envleak / "task.toml").write_text(
        toml_txt + '\n[environment.env]\nCANARY_WORLD_SECRET = "leaked"\n',
        encoding="utf-8",
    )
    res_envleak = audit.check_harbor_package(ROOT, task_dir=c_envleak)
    assert res_envleak.status == "FAIL"
    assert any("CANARY_" in d for d in res_envleak.details)

    c_dockerfile = _clone_case("bad_dockerfile")
    df = c_dockerfile / "environment" / "Dockerfile"
    df.write_text(df.read_text(encoding="utf-8") + "\nCOPY canary /app/canary\n", encoding="utf-8")
    res_df = audit.check_harbor_package(ROOT, task_dir=c_dockerfile)
    assert res_df.status == "FAIL"
    assert any("Dockerfile" in d for d in res_df.details)

    c_dockerignore = _clone_case("bad_dockerignore")
    (c_dockerignore / "environment" / ".dockerignore").write_text("docker-compose.yaml\n", encoding="utf-8")
    res_di = audit.check_harbor_package(ROOT, task_dir=c_dockerignore)
    assert res_di.status == "FAIL"
    assert any(".dockerignore" in d for d in res_di.details)

    c_salt_perm = _clone_case("bad_salt_perm")
    salt_file = c_salt_perm / "environment" / "canary-server" / "data" / "worlds" / "judge" / "SALT"
    salt_file.chmod(0o644)
    assert stat.S_IMODE(salt_file.stat().st_mode) == 0o644
    res_salt = audit.check_harbor_package(ROOT, task_dir=c_salt_perm)
    assert res_salt.status == "FAIL"
    assert any("SALT mode expected 0o600" in d for d in res_salt.details)

    c_ep_perm = _clone_case("bad_ep_perm")
    ep_file = c_ep_perm / "environment" / "canary-server" / "episode.json"
    ep_file.chmod(0o640)
    res_ep = audit.check_harbor_package(ROOT, task_dir=c_ep_perm)
    assert res_ep.status == "FAIL"
    assert any("episode.json mode expected 0o600" in d for d in res_ep.details)

    c_lk_perm = _clone_case("bad_lk_perm")
    lk_file = c_lk_perm / "tests" / "ledger_key"
    lk_file.chmod(0o644)
    res_lk = audit.check_harbor_package(ROOT, task_dir=c_lk_perm)
    assert res_lk.status == "FAIL"
    assert any("ledger_key mode expected 0o600" in d for d in res_lk.details)


def test_clean_reproduce_audit_clean_and_dirty(tmp_path):
    clean_repo = tmp_path / "repro_clean"
    _init_git_repo(clean_repo, {"README.md": "ok\n"})

    def _good_runner(root: Path, fast: bool) -> subprocess.CompletedProcess[str]:
        assert fast is True
        out = root / "results" / "latest"
        out.mkdir(parents=True, exist_ok=True)
        (out / "judge_table.md").write_text("table\n", encoding="utf-8")
        (out / "judge_episodes.jsonl").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=["reproduce"], returncode=0, stdout="ok", stderr="")

    res_ok = audit.check_clean_reproduce(clean_repo, fast=True, runner=_good_runner)
    assert res_ok.status == "PASS"

    def _dirty_runner(root: Path, fast: bool) -> subprocess.CompletedProcess[str]:
        _good_runner(root, fast)
        (root / "results" / "judge_table.md").write_text("dirtied tracked or untracked\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=["reproduce"], returncode=0, stdout="ok", stderr="")

    res_dirty = audit.check_clean_reproduce(clean_repo, fast=True, runner=_dirty_runner)
    assert res_dirty.status == "FAIL"
    assert any("porcelain changed" in d for d in res_dirty.details)

    def _failing_runner(root: Path, fast: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["reproduce"], returncode=2, stdout="", stderr="boom")

    res_fail = audit.check_clean_reproduce(clean_repo, fast=True, runner=_failing_runner)
    assert res_fail.status == "FAIL"
    assert any("boom" in d for d in res_fail.details)
