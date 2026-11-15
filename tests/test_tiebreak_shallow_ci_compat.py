from __future__ import annotations

import ast
from concurrent.futures import ProcessPoolExecutor
import io
import multiprocessing
import os
import shutil
import subprocess
import sys
import tokenize
import zipfile
from pathlib import Path
from typing import Any

import pytest

import scripts.reproduce_tiebreak_all as rta
import scripts.tiebreak_forensics as tf
import scripts.tiebreak_verda_multiseed_audit as tvma
import scripts.verify_tiebreak_submission as vts

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = Path(__file__).resolve()

STAGED_REL_FILES: tuple[str, ...] = (
    ".github/protected-paths.txt",
    "docs/reports/TIEBREAK_INDEX.md",
    "docs/reports/tiebreak_small_model.md",
    "docs/reports/tiebreak_verda_multiseed.md",
    "train/compact_render.py",
    "train/eval_compact_hf.py",
    "train/empirical_bayes_policy.py",
    "scripts/verify_tiebreak_submission.py",
    "scripts/reproduce_tiebreak_all.py",
    "scripts/tiebreak_experiment_ledger.py",
    "scripts/tiebreak_verda_multiseed_audit.py",
    "scripts/tiebreak_context_confound_audit.py",
    "scripts/tiebreak_forensics.py",
    "scripts/tiebreak_scaling_calibration.py",
)

EXPECTED_PARTIAL_GATES: tuple[str, ...] = (
    "verify_tiebreak_submission",
    "tiebreak_experiment_ledger",
    "tiebreak_verda_multiseed_audit",
    "tiebreak_context_confound_audit",
    "tiebreak_forensics",
    "tiebreak_scaling_calibration",
)


def _git_env(home_dir: Path) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "ci-bot",
        "GIT_AUTHOR_EMAIL": "ci-bot@example.com",
        "GIT_COMMITTER_NAME": "ci-bot",
        "GIT_COMMITTER_EMAIL": "ci-bot@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(home_dir),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _run_git(cwd: Path, args: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _run_readonly_task(task: tuple[str, str]) -> dict[str, Any]:
    kind, root_str = task
    root_dir = Path(root_str)
    if kind == "vts":
        return {"strict_report": vts.run_all_checks(root=root_dir, strict=True)}
    gates_report = rta.run_all_gates(root=root_dir, allow_partial_root=True, workers=1)
    verda_errs = tvma.verify_committed_artifacts(
        root_dir / "results" / "tiebreak" / "verda_multiseed" / "multiseed_summary.json",
        root_dir / "docs" / "reports" / "tiebreak_verda_multiseed.md",
        repo_root=root_dir,
        allow_git=False,
    )
    forensics_errs = tf.verify_committed_artifacts(
        root_dir / "results" / "tiebreak" / "forensics_prior_runs.json",
        md_path=root_dir / "results" / "tiebreak" / "forensics_prior_runs.md",
    )
    return {
        "gates_report": gates_report,
        "verda_errs": verda_errs,
        "forensics_errs": forensics_errs,
    }


@pytest.fixture(scope="module")
def compat_envs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base_dir = tmp_path_factory.mktemp("tiebreak_shallow_ci")
    home_dir = base_dir / "git_home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env = _git_env(home_dir)

    upstream = base_dir / "upstream_origin"
    upstream.mkdir(parents=True, exist_ok=True)

    for rel in STAGED_REL_FILES:
        src = REPO_ROOT / rel
        dst = upstream / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    shutil.copytree(REPO_ROOT / "results" / "tiebreak", upstream / "results" / "tiebreak")
    (upstream / "README.md").write_text("Silas baseline\n", encoding="utf-8")
    (upstream / "canary").mkdir(parents=True, exist_ok=True)
    (upstream / "canary" / "env.py").write_text("ENV_BASELINE = 1\n", encoding="utf-8")
    (upstream / "results" / "judge_episodes.jsonl").write_text("{\"seed\": 900000}\n", encoding="utf-8")

    _run_git(upstream, ["init", "-b", "pr-70-merge"], env)
    _run_git(
        upstream,
        ["add", ".github/protected-paths.txt", "README.md", "canary/env.py", "results/judge_episodes.jsonl"],
        env,
    )
    _run_git(upstream, ["commit", "-m", "initial baseline commit"], env)
    _run_git(upstream, ["add", "."], env)
    _run_git(upstream, ["commit", "-m", "pr merge commit"], env)

    shallow_ci = base_dir / "actions_checkout_v4_shallow"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "pr-70-merge",
            f"file://{upstream}",
            str(shallow_ci),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    _run_git(shallow_ci, ["checkout", "--detach", "HEAD"], env)

    zip_path = base_dir / "canary_judge_export.zip"
    _run_git(upstream, ["archive", "--format=zip", "-o", str(zip_path), "HEAD"], env)
    export_dir = base_dir / "judge_unzipped_no_git"
    export_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(export_dir)

    tasks = [
        ("vts", str(shallow_ci)),
        ("rta", str(shallow_ci)),
        ("vts", str(export_dir)),
        ("rta", str(export_dir)),
    ]
    if "fork" in multiprocessing.get_all_start_methods():
        import scripts.tiebreak_context_confound_audit as _tcca
        import scripts.tiebreak_experiment_ledger as _tel
        import scripts.tiebreak_scaling_calibration as _tsc

        _ = (_tcca, _tel, _tsc)
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=4, mp_context=ctx) as pool:
            s_vts, s_rta, e_vts, e_rta = list(pool.map(_run_readonly_task, tasks))
    else:
        s_vts, s_rta, e_vts, e_rta = [_run_readonly_task(t) for t in tasks]

    shallow_suite = {**s_vts, **s_rta}
    export_suite = {**e_vts, **e_rta}

    return {
        "shallow_ci": shallow_ci,
        "zip_path": zip_path,
        "export_dir": export_dir,
        "git_env": env,
        "shallow_suite": shallow_suite,
        "export_suite": export_suite,
    }


def _assert_full_tiebreak_verifiers_pass(suite: dict[str, Any], expected_base_ref: str) -> None:
    strict_report = suite["strict_report"]
    assert strict_report["passed"] is True, strict_report
    assert strict_report["strict"] is True
    assert strict_report["checks_passed"] == 5
    assert strict_report["checks_total"] == 5
    assert strict_report["global_errors"] == []
    for name in vts.CHECK_NAMES:
        chk = strict_report["checks"][name]
        assert chk["passed"] is True, chk
        assert chk["errors"] == []
    assert strict_report["checks"]["protected_and_frozen_paths"]["metrics"]["base_ref"] == expected_base_ref

    gates_report = suite["gates_report"]
    assert gates_report["passed"] is True, gates_report
    assert gates_report["gates_total"] == len(EXPECTED_PARTIAL_GATES)
    assert gates_report["gates_passed"] == gates_report["gates_total"]
    got_gate_ids = tuple(g["gate_id"] for g in gates_report["gates"])
    assert got_gate_ids == EXPECTED_PARTIAL_GATES
    for gate_item in gates_report["gates"]:
        assert gate_item["passed"] is True, gate_item
        assert gate_item["errors"] == []

    assert suite["verda_errs"] == []
    assert suite["forensics_errs"] == []


def test_source_hygiene_and_zero_heavy_imports() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    src = SELF_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(SELF_PATH))
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))

    assert not [t for t in toks if t.type == tokenize.COMMENT]
    assert hash_char not in src
    assert em_dash not in src
    assert en_dash not in src
    assert src.isascii()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_roots
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_roots

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_shallow_github_actions_pr_checkout_passes_all_gates(compat_envs: dict[str, Any]) -> None:
    shallow_ci: Path = compat_envs["shallow_ci"]
    env: dict[str, str] = compat_envs["git_env"]

    assert (shallow_ci / ".git").is_dir()
    assert (shallow_ci / ".git" / "shallow").is_file()
    assert _run_git(shallow_ci, ["rev-list", "--count", "HEAD"], env).stdout.strip() == "1"
    assert _run_git(shallow_ci, ["rev-parse", "--abbrev-ref", "HEAD"], env).stdout.strip() == "HEAD"

    origin_silas = _run_git(shallow_ci, ["rev-parse", "--verify", "origin/justSilas"], env, check=False)
    local_silas = _run_git(shallow_ci, ["rev-parse", "--verify", "justSilas"], env, check=False)
    all_refs = _run_git(shallow_ci, ["show-ref"], env, check=False).stdout
    assert origin_silas.returncode != 0
    assert local_silas.returncode != 0
    assert "justSilas" not in all_refs

    _assert_full_tiebreak_verifiers_pass(compat_envs["shallow_suite"], expected_base_ref="HEAD")


def test_exported_judge_zip_without_git_passes_all_gates(compat_envs: dict[str, Any]) -> None:
    zip_path: Path = compat_envs["zip_path"]
    export_dir: Path = compat_envs["export_dir"]

    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) >= len(STAGED_REL_FILES)
        assert not any(name == ".git" or name.startswith(".git/") for name in names)

    assert not (export_dir / ".git").exists()
    _assert_full_tiebreak_verifiers_pass(compat_envs["export_suite"], expected_base_ref="offline_archive")


def test_shallow_checkout_dirty_edits_to_readme_and_env_rejected(compat_envs: dict[str, Any]) -> None:
    shallow_ci: Path = compat_envs["shallow_ci"]
    env: dict[str, str] = compat_envs["git_env"]

    readme_path = shallow_ci / "README.md"
    env_py_path = shallow_ci / "canary" / "env.py"
    judge_ep_path = shallow_ci / "results" / "judge_episodes.jsonl"

    orig_readme = readme_path.read_text(encoding="utf-8")
    orig_env_py = env_py_path.read_text(encoding="utf-8")
    orig_judge_ep = judge_ep_path.read_text(encoding="utf-8")

    try:
        assert _run_git(shallow_ci, ["rev-parse", "--abbrev-ref", "HEAD"], env).stdout.strip() == "HEAD"

        env_py_path.write_text(orig_env_py + "\nTAMPERED_IN_SHALLOW_CI = True\n", encoding="utf-8")
        detached_env_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert detached_env_res.passed is False
        assert detached_env_res.metrics["base_ref"] == "HEAD"
        assert detached_env_res.metrics["protected_violations"] == 1
        assert any("canary/env.py" in err and "protected path touched" in err for err in detached_env_res.errors)
        env_py_path.write_text(orig_env_py, encoding="utf-8")

        judge_ep_path.write_text(orig_judge_ep + "{\"tampered\": true}\n", encoding="utf-8")
        detached_judge_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert detached_judge_res.passed is False
        assert detached_judge_res.metrics["frozen_doc_violations"] == 1
        assert any("results/judge_episodes.jsonl" in err for err in detached_judge_res.errors)
        judge_ep_path.write_text(orig_judge_ep, encoding="utf-8")

        readme_path.write_text(orig_readme + "\nunauthorized shallow readme edit\n", encoding="utf-8")
        diff_paths, resolved_ref, diff_err = vts._git_diff_paths(shallow_ci, "origin/justSilas")
        assert diff_err is None
        assert resolved_ref == "HEAD"
        assert "README.md" in diff_paths
        explicit_readme_res = vts.check_protected_and_frozen_paths(
            root=shallow_ci,
            changed_paths=diff_paths,
            strict=True,
        )
        assert explicit_readme_res.passed is False
        assert any("README.md" in err and "frozen Silas doc touched" in err for err in explicit_readme_res.errors)
        readme_path.write_text(orig_readme, encoding="utf-8")

        _run_git(shallow_ci, ["checkout", "-B", "fr8/canary/tiebreak"], env)
        assert _run_git(shallow_ci, ["rev-list", "--count", "HEAD"], env).stdout.strip() == "1"
        assert vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True).passed is True

        readme_path.write_text(orig_readme + "\nunauthorized squad readme edit\n", encoding="utf-8")
        squad_readme_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert squad_readme_res.passed is False
        assert squad_readme_res.metrics["base_ref"] == "HEAD"
        assert squad_readme_res.metrics["frozen_doc_violations"] == 1
        assert any("README.md" in err and "frozen Silas doc touched" in err for err in squad_readme_res.errors)

        env_py_path.write_text(orig_env_py + "\nTAMPERED_ON_SQUAD_BRANCH = True\n", encoding="utf-8")
        both_dirty_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert both_dirty_res.passed is False
        assert both_dirty_res.metrics["base_ref"] == "HEAD"
        assert both_dirty_res.metrics["protected_violations"] == 1
        assert both_dirty_res.metrics["frozen_doc_violations"] == 1
        assert any("README.md" in err for err in both_dirty_res.errors)
        assert any("canary/env.py" in err for err in both_dirty_res.errors)
    finally:
        readme_path.write_text(orig_readme, encoding="utf-8")
        env_py_path.write_text(orig_env_py, encoding="utf-8")
        judge_ep_path.write_text(orig_judge_ep, encoding="utf-8")
        _run_git(shallow_ci, ["checkout", "--detach", "HEAD"], env)
        _run_git(shallow_ci, ["branch", "-D", "fr8/canary/tiebreak"], env, check=False)


def test_cross_branch_unified_scoping_and_explicit_base_ref(compat_envs: dict[str, Any]) -> None:
    shallow_ci: Path = compat_envs["shallow_ci"]
    env: dict[str, str] = compat_envs["git_env"]

    readme_path = shallow_ci / "README.md"
    env_py_path = shallow_ci / "canary" / "env.py"
    orig_readme = readme_path.read_text(encoding="utf-8")
    orig_env_py = env_py_path.read_text(encoding="utf-8")

    bad_ref_res = vts.check_protected_and_frozen_paths(
        root=shallow_ci,
        base_ref="origin/nonexistent-custom-base",
        strict=True,
    )
    assert bad_ref_res.passed is False
    assert any("failed to diff against origin/nonexistent-custom-base" in err for err in bad_ref_res.errors)

    try:
        _run_git(shallow_ci, ["checkout", "-B", "fr8/canary/main"], env)
        readme_path.write_text(orig_readme + "\ncraft unified readme sync\n", encoding="utf-8")
        unified_readme_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert unified_readme_res.passed is True
        assert unified_readme_res.metrics["base_ref"] == "HEAD"
        assert unified_readme_res.metrics["changed_count"] == 1

        env_py_path.write_text(orig_env_py + "\nILLEGAL_PROTECTED_EDIT = 1\n", encoding="utf-8")
        unified_env_res = vts.check_protected_and_frozen_paths(root=shallow_ci, strict=True)
        assert unified_env_res.passed is False
        assert any("canary/env.py" in err for err in unified_env_res.errors)
    finally:
        readme_path.write_text(orig_readme, encoding="utf-8")
        env_py_path.write_text(orig_env_py, encoding="utf-8")
        _run_git(shallow_ci, ["checkout", "--detach", "HEAD"], env)
        _run_git(shallow_ci, ["branch", "-D", "fr8/canary/main"], env, check=False)
        _run_git(shallow_ci, ["branch", "-D", "fr8/canary/tiebreak"], env, check=False)
