"""Verify that a gitless export of HEAD (matching GitHub's Download ZIP) works end-to-end.

Exports HEAD via ``git archive --format=tar HEAD | tar -x -C <tmp_dir>`` into a temporary
directory under ``/tmp/opencode``, confirms ``.git`` is absent, and runs six checks:

1. Keyless Mini-Reproduce Without .git
2. Harbor Build Without .git
3. Judge Analysis Scripts Without .git
4. Frozen Tier Hash Without .git
5. Git-Independent Security Tests Without .git
6. Craft Verifiers Without .git
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TMP_BASE = Path("/tmp/opencode")
HASH_CHAR = chr(35)

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
HARBOR_TIER = "hard"
HARBOR_SEED = 900000

CHECK_MINI_REPRODUCE = "Keyless Mini-Reproduce Without .git"
CHECK_HARBOR_BUILD = "Harbor Build Without .git"
CHECK_JUDGE_SCRIPTS = "Judge Analysis Scripts Without .git"
CHECK_FROZEN_TIER_HASH = "Frozen Tier Hash Without .git"
CHECK_SECURITY_TESTS = "Git-Independent Security Tests Without .git"
CHECK_CRAFT_VERIFIERS = "Craft Verifiers Without .git"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_MINI_REPRODUCE,
    CHECK_HARBOR_BUILD,
    CHECK_JUDGE_SCRIPTS,
    CHECK_FROZEN_TIER_HASH,
    CHECK_SECURITY_TESTS,
    CHECK_CRAFT_VERIFIERS,
)

CRAFT_VERIFIER_SCRIPTS: tuple[str, ...] = (
    "scripts/audit_doc_hygiene.py",
    "scripts/check_craft_consistency.py",
    "scripts/verify_artifact_numbers.py",
    "scripts/verify_commit_provenance.py",
    "scripts/verify_doc_commands.py",
    "scripts/verify_judge_walkthrough.py",
    "scripts/verify_submission_doc.py",
    "scripts/verify_submission_surfaces.py",
)

STRIPPED_ENV_KEYS: tuple[str, ...] = (
    "CANARY_WORLD_SECRET",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "REPRO_FAST",
)

FROZEN_TIER_PROBE = (
    "import hashlib, json, pathlib; "
    "from canary import rules; "
    "obj = {'tiers': {k: v.to_dict() for k, v in rules.TIERS.items()}, "
    "'known_v_mode': rules.KNOWN_V_MODE}; "
    "h = hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]; "
    "print(json.dumps({'tiers_version': rules.TIERS_VERSION, 'tier_hash': h, "
    "'rules_file': str(pathlib.Path(rules.__file__).resolve())}))"
)


class ExportError(RuntimeError):
    """Raised when exporting HEAD into a gitless archive directory fails."""


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


RunnerFn = Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess[str]]
ExporterFn = Callable[[Path, Path], None]


def has_dot_git(export_dir: Path) -> bool:
    """Return True if ``.git`` exists (directory, worktree file, or symlink) in ``export_dir``."""
    dot_git = export_dir / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _dot_git_failure(name: str, export_dir: Path) -> CheckResult:
    return CheckResult(
        name,
        "FAIL",
        ".git unexpectedly exists in archive target",
        [str(export_dir / ".git")],
    )


def _snippet(proc: subprocess.CompletedProcess[str]) -> list[str]:
    text = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if not text:
        return []
    return [text[-400:]]


def default_runner(
    cmd: list[str],
    cwd: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` inside ``cwd`` with ``PYTHONPATH=cwd`` and no ambient API or world secrets."""
    env = dict(os.environ)
    for key in STRIPPED_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def export_head(root: Path, export_dir: Path) -> None:
    """Export ``HEAD`` from ``root`` into ``export_dir`` via ``git archive | tar -x``."""
    if not root.is_dir():
        raise ExportError(f"repository root does not exist: {root}")
    if not (root / ".git").exists():
        raise ExportError(f"target root has no .git metadata: {root}")
    export_dir.mkdir(parents=True, exist_ok=True)

    r_fd, w_fd = os.pipe()
    try:
        git_proc = subprocess.Popen(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=root,
            stdout=w_fd,
            stderr=subprocess.PIPE,
        )
    finally:
        os.close(w_fd)

    try:
        tar_proc = subprocess.Popen(
            ["tar", "-x", "-C", str(export_dir)],
            stdin=r_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        git_proc.kill()
        git_proc.communicate()
        raise
    finally:
        os.close(r_fd)

    try:
        _, tar_err = tar_proc.communicate(timeout=30)
        _, git_err = git_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired as exc:
        tar_proc.kill()
        git_proc.kill()
        tar_proc.communicate()
        git_proc.communicate()
        raise ExportError("timed out running git archive | tar -x") from exc

    if git_proc.returncode != 0:
        msg = git_err.decode("utf-8", errors="replace").strip()
        raise ExportError(f"git archive failed (exit {git_proc.returncode}): {msg}")
    if tar_proc.returncode != 0:
        msg = tar_err.decode("utf-8", errors="replace").strip()
        raise ExportError(f"tar extract failed (exit {tar_proc.returncode}): {msg}")


def _find_canary_env_leaks(obj: Any, path: str = "environment") -> list[str]:
    leaks: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            cur = f"{path}.{ks}"
            if ks.upper().startswith("CANARY_"):
                leaks.append(cur)
            leaks.extend(_find_canary_env_leaks(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            cur = f"{path}[{idx}]"
            if isinstance(item, str) and re.search(r"\bCANARY_[A-Z0-9_]*", item, re.IGNORECASE):
                leaks.append(f"{cur}={item}")
            else:
                leaks.extend(_find_canary_env_leaks(item, cur))
    elif isinstance(obj, str):
        if re.search(r"\bCANARY_[A-Z0-9_]*", obj, re.IGNORECASE):
            leaks.append(f"{path}={obj}")
    return leaks


def audit_harbor_task_dir(task_dir: Path, tier: str = HARBOR_TIER, seed: int = HARBOR_SEED) -> list[str]:
    """Audit ``task.toml``, ``.dockerignore``, and ``0600`` secret files in a built Harbor task."""
    failures: list[str] = []
    if not task_dir.is_dir():
        return [f"missing built Harbor task directory: {task_dir}"]

    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        failures.append(f"missing {toml_path.name}")
    else:
        raw_toml = toml_path.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(raw_toml)
        except tomllib.TOMLDecodeError as exc:
            failures.append(f"invalid task.toml: {exc}")
            parsed = None

        if isinstance(parsed, dict):
            verifier = parsed.get("verifier")
            if not isinstance(verifier, dict):
                failures.append("task.toml missing [verifier] section")
            else:
                if verifier.get("environment_mode") != "separate":
                    failures.append(
                        f"verifier.environment_mode expected 'separate', got {verifier.get('environment_mode')!r}"
                    )
                collect = verifier.get("collect")
                if "[[verifier.collect]]" not in raw_toml or not isinstance(collect, list) or not collect:
                    failures.append("task.toml missing [[verifier.collect]] hook")

            env_section = parsed.get("environment")
            if not isinstance(env_section, dict):
                failures.append("task.toml missing [environment] section")
            else:
                leaks = _find_canary_env_leaks(env_section)
                if leaks:
                    failures.append(f"task.toml [environment] exposes CANARY_* vars: {', '.join(leaks)}")

            meta = parsed.get("metadata")
            if not isinstance(meta, dict) or meta.get("tier") != tier:
                failures.append(f"task.toml metadata.tier expected {tier!r}")

    instruction_md = task_dir / "instruction.md"
    if not instruction_md.is_file() or instruction_md.stat().st_size == 0:
        failures.append("missing or empty instruction.md")

    dockerignore = task_dir / "environment" / ".dockerignore"
    if not dockerignore.is_file():
        failures.append("missing environment/.dockerignore")
    else:
        ig_lines = [
            ln.strip()
            for ln in dockerignore.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith(HASH_CHAR)
        ]
        excludes_sidecar = any(
            ln.lstrip("/").rstrip("/") in {"canary-server", "canary-server/*"}
            for ln in ig_lines
            if not ln.startswith("!")
        )
        negates_sidecar = any(ln.startswith("!") and "canary-server" in ln for ln in ig_lines)
        if not excludes_sidecar or negates_sidecar:
            failures.append("environment/.dockerignore does not cleanly exclude canary-server")

    sidecar = task_dir / "environment" / "canary-server"
    secret_targets: tuple[tuple[str, Path, int], ...] = (
        ("SALT", sidecar / "data" / "worlds" / "judge" / "SALT", 16),
        ("episode.json", sidecar / "episode.json", 2),
        ("sidecar ledger_key", sidecar / "ledger_key", 16),
        ("verifier ledger_key", task_dir / "tests" / "ledger_key", 16),
    )
    for label, target, min_bytes in secret_targets:
        if not target.exists():
            failures.append(f"missing {label} at {target.relative_to(task_dir)}")
            continue
        if target.is_symlink() or not target.is_file():
            failures.append(f"{label} must be a regular non-symlink file")
            continue
        st = target.stat()
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            failures.append(f"{label} mode expected 0o600, got {oct(mode)}")
        if st.st_size < min_bytes:
            failures.append(f"{label} expected >= {min_bytes} bytes, got {st.st_size}")

    ep_path = sidecar / "episode.json"
    if ep_path.is_file() and not ep_path.is_symlink():
        try:
            ep_obj = json.loads(ep_path.read_text(encoding="utf-8"))
            if not isinstance(ep_obj, dict) or ep_obj.get("tier") != tier or ep_obj.get("seed") != seed:
                failures.append(f"episode.json expected tier={tier!r} seed={seed}, got {ep_obj!r}")
        except ValueError as exc:
            failures.append(f"episode.json invalid JSON: {exc}")

    sidecar_lk = sidecar / "ledger_key"
    verifier_lk = task_dir / "tests" / "ledger_key"
    if sidecar_lk.is_file() and verifier_lk.is_file():
        if sidecar_lk.read_bytes() != verifier_lk.read_bytes():
            failures.append("sidecar ledger_key does not match tests/ledger_key")

    if (task_dir / "solution" / "ledger_key").exists():
        failures.append("forbidden ledger_key in solution/")

    return failures


def check_keyless_mini_reproduce(
    export_dir: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 1: run keyless 2-seed mini-reproduce inside gitless ``export_dir``."""
    name = CHECK_MINI_REPRODUCE
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    run_fn = runner if runner is not None else default_runner
    proc = run_fn(
        [sys.executable, "-m", "canary.eval", "--reproduce"],
        export_dir,
        {"REPRO_SEEDS": "2", "REPRO_ANTICHEAT": "0"},
    )
    if proc.returncode != 0:
        return CheckResult(
            name,
            "FAIL",
            f"canary.eval --reproduce exited with {proc.returncode}",
            _snippet(proc),
        )

    failures: list[str] = []
    table_path = export_dir / "results" / "latest" / "judge_table.md"
    episodes_path = export_dir / "results" / "latest" / "judge_episodes.jsonl"

    table_text = ""
    if not table_path.is_file() or table_path.stat().st_size == 0:
        failures.append("missing or empty results/latest/judge_table.md")
    else:
        table_text = table_path.read_text(encoding="utf-8")

    episode_count = 0
    if not episodes_path.is_file() or episodes_path.stat().st_size == 0:
        failures.append("missing or empty results/latest/judge_episodes.jsonl")
    else:
        for lineno, line in enumerate(episodes_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                failures.append(f"judge_episodes.jsonl:{lineno}: invalid JSON ({exc})")
                break
            if not isinstance(rec, dict):
                failures.append(f"judge_episodes.jsonl:{lineno}: expected JSON object")
                break
            episode_count += 1
        if episode_count == 0 and not failures:
            failures.append("judge_episodes.jsonl contains 0 episode records")

    normalized_table = table_text.replace("`", "")
    normalized_stdout = (proc.stdout or "").replace("`", "")
    if "git: unknown" not in normalized_table and "git: unknown" not in normalized_stdout:
        failures.append("expected 'git: unknown' in reproduce output when .git is absent")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} reproduce check failure(s)", failures)

    return CheckResult(
        name,
        "PASS",
        f"exit 0, wrote judge_table.md + judge_episodes.jsonl ({episode_count} episodes), git: unknown",
    )


def check_harbor_build(
    export_dir: Path,
    harbor_out: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 2: run ``harbor/build.py`` inside gitless ``export_dir`` and audit task artifacts."""
    name = CHECK_HARBOR_BUILD
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    harbor_out.mkdir(parents=True, exist_ok=True)
    run_fn = runner if runner is not None else default_runner
    proc = run_fn(
        [
            sys.executable,
            "harbor/build.py",
            "--tiers",
            HARBOR_TIER,
            "--seeds",
            str(HARBOR_SEED),
            "--out",
            str(harbor_out),
        ],
        export_dir,
        {},
    )
    if proc.returncode != 0:
        return CheckResult(
            name,
            "FAIL",
            f"harbor/build.py exited with {proc.returncode}",
            _snippet(proc),
        )

    built_dir = harbor_out / f"canary-{HARBOR_TIER}-{HARBOR_SEED}"
    failures = audit_harbor_task_dir(built_dir, tier=HARBOR_TIER, seed=HARBOR_SEED)
    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} Harbor task audit failure(s)", failures)

    return CheckResult(
        name,
        "PASS",
        f"exit 0, audited {built_dir.name} (task.toml separate verifier, 0600 SALT/episode.json/ledger_key)",
    )


def check_judge_analysis_scripts(
    export_dir: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 3: run ``scripts/demo_replay.py --seed 4 --verify`` in gitless ``export_dir``."""
    name = CHECK_JUDGE_SCRIPTS
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    run_fn = runner if runner is not None else default_runner
    proc = run_fn(
        [sys.executable, "scripts/demo_replay.py", "--seed", "4", "--verify"],
        export_dir,
        {},
    )
    if proc.returncode != 0:
        return CheckResult(
            name,
            "FAIL",
            f"scripts/demo_replay.py exited with {proc.returncode}",
            _snippet(proc),
        )

    stdout = proc.stdout or ""
    matches = re.findall(r"\bMATCH\b", stdout)
    if not matches or "MISMATCH" in stdout:
        return CheckResult(
            name,
            "FAIL",
            "expected MATCH (and no MISMATCH) in demo_replay.py stdout",
            _snippet(proc),
        )

    return CheckResult(
        name,
        "PASS",
        f"exit 0, demo_replay.py --seed 4 --verify reported {len(matches)} MATCH line(s)",
    )


def check_frozen_tier_hash(
    export_dir: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 4: verify ``canary.rules.TIERS_VERSION`` and frozen tier hash from ``export_dir``."""
    name = CHECK_FROZEN_TIER_HASH
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    run_fn = runner if runner is not None else default_runner
    proc = run_fn(
        [sys.executable, "-c", FROZEN_TIER_PROBE],
        export_dir,
        {},
    )
    if proc.returncode != 0:
        return CheckResult(
            name,
            "FAIL",
            f"frozen tier hash probe exited with {proc.returncode}",
            _snippet(proc),
        )

    try:
        data = json.loads((proc.stdout or "").strip())
    except ValueError as exc:
        return CheckResult(
            name,
            "FAIL",
            f"invalid JSON from frozen tier probe: {exc}",
            _snippet(proc),
        )

    failures: list[str] = []
    tiers_version = data.get("tiers_version")
    tier_hash = data.get("tier_hash")
    rules_file = data.get("rules_file")

    if tiers_version != EXPECTED_TIERS_VERSION:
        failures.append(f"TIERS_VERSION expected {EXPECTED_TIERS_VERSION!r}, got {tiers_version!r}")
    if tier_hash != EXPECTED_V14_HASH:
        failures.append(f"tier hash expected {EXPECTED_V14_HASH}, got {tier_hash!r}")
    if isinstance(rules_file, str) and rules_file:
        try:
            Path(rules_file).resolve().relative_to(export_dir.resolve())
        except ValueError:
            failures.append(f"canary.rules loaded outside export_dir: {rules_file}")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} frozen tier mismatch(es)", failures)

    return CheckResult(
        name,
        "PASS",
        f"TIERS_VERSION={tiers_version} and tier hash {tier_hash} verified from export_dir",
    )


def check_security_tests(
    export_dir: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 5: run git-independent security pytest suite in ``export_dir``."""
    name = CHECK_SECURITY_TESTS
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    run_fn = runner if runner is not None else default_runner
    proc = run_fn(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_env_secret.py",
            "tests/test_env_frozen.py",
        ],
        export_dir,
        {},
    )
    if proc.returncode != 0:
        return CheckResult(
            name,
            "FAIL",
            f"pytest security suite exited with {proc.returncode}",
            _snippet(proc),
        )

    return CheckResult(
        name,
        "PASS",
        "exit 0 on tests/test_env_secret.py and tests/test_env_frozen.py without .git",
    )


def check_craft_verifiers(
    export_dir: Path,
    runner: RunnerFn | None = None,
) -> CheckResult:
    """Check 6: run all eight craft verifiers inside gitless ``export_dir`` and require ``0 FAIL``."""
    name = CHECK_CRAFT_VERIFIERS
    if has_dot_git(export_dir):
        return _dot_git_failure(name, export_dir)

    run_fn = runner if runner is not None else default_runner
    ceiling = str(export_dir.resolve().parent)

    def _run_one(script_rel: str) -> tuple[str, subprocess.CompletedProcess[str]]:
        proc = run_fn(
            [sys.executable, script_rel],
            export_dir,
            {"GIT_CEILING_DIRECTORIES": ceiling},
        )
        return script_rel, proc

    with ThreadPoolExecutor(max_workers=len(CRAFT_VERIFIER_SCRIPTS)) as pool:
        outcomes = list(pool.map(_run_one, CRAFT_VERIFIER_SCRIPTS))

    failures: list[str] = []
    for script_rel, proc in outcomes:
        stdout = proc.stdout or ""
        if proc.returncode != 0:
            snippets = _snippet(proc)
            tail = f" ({snippets[0]})" if snippets else ""
            failures.append(f"{script_rel} exited with {proc.returncode}{tail}")
            continue
        has_zero_fail = re.search(r"^SUMMARY:.*\b0\s+FAIL\b", stdout, re.MULTILINE) is not None
        has_nonzero_fail = (
            re.search(r"^\s*\[FAIL\]", stdout, re.MULTILINE) is not None
            or re.search(r"^SUMMARY:.*\b[1-9]\d*\s+FAIL\b", stdout, re.MULTILINE) is not None
        )
        if not has_zero_fail or has_nonzero_fail:
            snippets = _snippet(proc)
            tail = f" ({snippets[0]})" if snippets else ""
            failures.append(f"{script_rel} did not report 0 FAIL{tail}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} craft verifier failure(s) without .git",
            failures,
        )

    return CheckResult(
        name,
        "PASS",
        f"exit 0 and 0 FAIL across all {len(CRAFT_VERIFIER_SCRIPTS)} craft verifiers without .git",
    )


def verify_export_dir(
    export_dir: Path,
    harbor_out: Path,
    runner: RunnerFn | None = None,
) -> list[CheckResult]:
    """Run all six checks against an already-extracted ``export_dir``."""
    if has_dot_git(export_dir):
        return [_dot_git_failure(name, export_dir) for name in CHECK_NAMES]

    tasks: tuple[Callable[[], CheckResult], ...] = (
        lambda: check_keyless_mini_reproduce(export_dir, runner=runner),
        lambda: check_harbor_build(export_dir, harbor_out, runner=runner),
        lambda: check_judge_analysis_scripts(export_dir, runner=runner),
        lambda: check_frozen_tier_hash(export_dir, runner=runner),
        lambda: check_security_tests(export_dir, runner=runner),
        lambda: check_craft_verifiers(export_dir, runner=runner),
    )
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(fn) for fn in tasks]
        return [fut.result() for fut in futures]


def verify_zip_export(
    root: Path = ROOT,
    *,
    tmp_base: Path | None = None,
    exporter: ExporterFn | None = None,
    runner: RunnerFn | None = None,
) -> list[CheckResult]:
    """Export ``HEAD`` from ``root`` into a temporary directory under ``/tmp/opencode`` and verify."""
    resolved_root = root.resolve()
    base_dir = tmp_base if tmp_base is not None else TMP_BASE
    export_fn = exporter if exporter is not None else export_head
    base_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(base_dir), prefix="canary-zip-export-") as tmp_str:
        tmp_dir = Path(tmp_str)
        export_dir = tmp_dir / "export"
        harbor_out = tmp_dir / "harbor"
        export_dir.mkdir(parents=True, exist_ok=True)
        try:
            export_fn(resolved_root, export_dir)
        except (ExportError, OSError, subprocess.SubprocessError) as exc:
            return [
                CheckResult(name, "FAIL", f"archive export failed: {exc}")
                for name in CHECK_NAMES
            ]

        if (export_dir / ".git").exists() or has_dot_git(export_dir):
            return [_dot_git_failure(name, export_dir) for name in CHECK_NAMES]

        return verify_export_dir(export_dir, harbor_out, runner=runner)


audit_repo = verify_zip_export


def format_report(results: list[CheckResult], elapsed_s: float) -> str:
    """Format human-readable CLI output."""
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``scripts/verify_zip_export.py``."""
    ap = argparse.ArgumentParser(
        description="Verify Canary works from a gitless GitHub ZIP / git-archive export."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to export and audit")
    ap.add_argument("--tmp-root", type=Path, default=None, help="Parent directory for temporary export workspace")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_zip_export(
        root=args.root.resolve(),
        tmp_base=args.tmp_root.resolve() if args.tmp_root is not None else None,
    )
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items = [asdict(r) for r in results]
        payload = {
            "results": items,
            "checks": items,
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
