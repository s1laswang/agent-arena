from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"
ALLOWED_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
API_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("sk_api_key", re.compile(r"(?<![0-9A-Za-z_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}")),
)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _redact_token(val: str) -> str:
    if len(val) <= 8:
        return val[:3] + "..."
    return val[:6] + "..."


def _git_ls_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [entry for entry in raw.split("\0") if entry]


def check_secret_hygiene(root: Path) -> CheckResult:
    name = "Secret & Answer-Key Hygiene"
    tracked = _git_ls_files(root)
    if tracked is None:
        return CheckResult(name, "FAIL", "git ls-files failed; target is not a git repository")

    violations: list[str] = []
    warnings: list[str] = []

    for rel in tracked:
        p = Path(rel)
        if p.name == ".env" or (p.name.startswith(".env.") and p.name not in ALLOWED_ENV_TEMPLATES):
            violations.append(f"tracked env file: {rel}")
        if p.name == "SALT" or "SALT" in p.parts:
            violations.append(f"tracked SALT file: {rel}")

        fp = root / rel
        if not fp.is_file():
            continue
        try:
            raw = fp.read_bytes()
        except OSError as exc:
            violations.append(f"unreadable tracked file {rel}: {type(exc).__name__}")
            continue

        if rel.endswith(".world.json"):
            txt = raw.decode("utf-8", errors="replace")
            has_mole = '"mole"' in txt
            if not has_mole:
                try:
                    parsed_world = json.loads(txt)
                    has_mole = isinstance(parsed_world, dict) and "mole" in parsed_world
                except ValueError:
                    has_mole = False
            if has_mole:
                violations.append(f"tracked world file containing mole answer key: {rel}")
            else:
                warnings.append(f"tracked world file (no mole field found): {rel}")

        if b"\x00" in raw:
            continue
        if b"AIza" not in raw and b"sk-" not in raw:
            continue
        txt = raw.decode("utf-8", errors="replace")
        for kind, rx in API_KEY_PATTERNS:
            for match in rx.finditer(txt):
                violations.append(f"tracked raw API key ({kind}: {_redact_token(match.group(0))}) in {rel}")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} secret/answer-key violation(s) across {len(tracked)} tracked files",
            violations,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"scanned {len(tracked)} tracked files; 0 secrets, {len(warnings)} warning(s)",
            warnings,
        )
    return CheckResult(name, "PASS", f"scanned {len(tracked)} tracked files; 0 secrets or answer keys")


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]


def check_frozen_tiers() -> CheckResult:
    name = "Frozen Tier Hashes"
    from canary import rules

    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    failures: list[str] = []

    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        failures.append(f"TIERS_VERSION expected {EXPECTED_TIERS_VERSION!r}, got {rules.TIERS_VERSION!r}")
    if v14_hash != EXPECTED_V14_HASH:
        failures.append(f"TIERS ({rules.TIERS_VERSION}) hash expected {EXPECTED_V14_HASH}, got {v14_hash}")
    if v13_hash != EXPECTED_V13_HASH:
        failures.append(f"TIERS_V13 hash expected {EXPECTED_V13_HASH}, got {v13_hash}")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} frozen tier mismatch(es)", failures)
    return CheckResult(
        name,
        "PASS",
        f"TIERS_VERSION={rules.TIERS_VERSION} ({v14_hash}), TIERS_V13 ({v13_hash})",
    )


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _check_score_invariants(ep: dict[str, Any], loc: str, is_invalid: bool) -> list[str]:
    errs: list[str] = []
    raw_score = ep.get("score")
    if not _is_finite_number(raw_score):
        return [f"{loc}: score is not a finite number: {raw_score!r}"]
    score = float(raw_score)
    if not (-1.0 <= score <= 1.0):
        errs.append(f"{loc}: score {score} outside [-1.0, 1.0]")
    if is_invalid:
        return errs

    accused = ep.get("accused")
    has_accused = isinstance(accused, str) and bool(accused.strip())
    if accused is not None and not has_accused:
        errs.append(f"{loc}: invalid accused value {accused!r}")
    correct = bool(ep.get("correct"))
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}

    if score > 0.0 and not (has_accused and correct):
        errs.append(f"{loc}: score={score} > 0 requires accused and correct (accused={accused!r}, correct={correct})")
    if has_accused and correct:
        zero_v = score == 0.0 and "V" in meta and meta.get("V") == 0.0
        if not (score > 0.0 or zero_v):
            errs.append(f"{loc}: accused and correct requires score > 0 (or V==0.0), got score={score}")
    if not has_accused:
        if score != 0.0:
            errs.append(f"{loc}: not accused requires score == 0.0, got score={score}")
        if correct:
            errs.append(f"{loc}: not accused cannot have correct=True")
    if has_accused and not correct and score != -1.0:
        errs.append(f"{loc}: accused and not correct requires score == -1.0, got score={score}")
    return errs


def check_committed_runs(
    root: Path,
    load_committed_fn: Callable[[Path], tuple[list[Any], list[str]]] | None = None,
) -> CheckResult:
    name = "Committed Runs Integrity"
    from canary import reproduce as R

    committed_root = root / "data" / "runs" / "committed"
    if not committed_root.exists():
        return CheckResult(name, "WARN", "no data/runs/committed directory found")

    all_files = sorted(committed_root.rglob("episodes.jsonl"))
    files: list[Path] = []
    for f in all_files:
        rel_parts = f.parent.relative_to(committed_root).parts
        if "superseded" in rel_parts:
            continue
        files.append(f)

    repro_files = R.committed_files(root)
    failures: list[str] = []
    if [p.resolve() for p in files] != [p.resolve() for p in repro_files]:
        failures.append("canary.reproduce.committed_files mismatch with non-superseded episodes.jsonl list")

    seen: dict[tuple[str, str, str, int], list[str]] = defaultdict(list)
    expected_valid: dict[tuple[str, str, str], list[tuple[int, float]]] = defaultdict(list)
    invalid_by_key: dict[tuple[str, str, str], list[tuple[int, str, str]]] = defaultdict(list)
    invalid_flags: list[str] = []
    total_episodes = 0

    for f in files:
        meta = R.run_meta(f.parent)
        version = R.run_tiers_version(f.parent, root, meta)
        rel = str(f.relative_to(root))
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            loc = f"{rel}:{lineno}"
            try:
                ep = json.loads(line)
            except ValueError as exc:
                failures.append(f"{loc}: invalid JSON ({exc})")
                continue
            if not isinstance(ep, dict):
                failures.append(f"{loc}: episode record must be a JSON object")
                continue

            total_episodes += 1
            agent = str(ep.get("agent") or "")
            tier = str(ep.get("tier") or "")
            if not agent or not tier or "seed" not in ep or isinstance(ep.get("seed"), bool):
                failures.append(f"{loc}: missing agent/tier/seed fields")
                continue
            try:
                seed = int(ep["seed"])
            except (TypeError, ValueError):
                failures.append(f"{loc}: non-integer seed {ep.get('seed')!r}")
                continue

            ep_meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            is_invalid = (ep_meta.get("valid") is False) or (ep.get("valid") is False)

            seen[(agent, tier, version, seed)].append(loc)
            failures.extend(_check_score_invariants(ep, loc, is_invalid))

            group_key = (tier, version, agent)
            if is_invalid:
                reason = R.invalid_reason(ep) or "valid:false"
                invalid_by_key[group_key].append((seed, loc, reason))
                invalid_flags.append(f"{loc} ({agent}, {tier}, {version}, seed={seed}): {reason}")
            elif _is_finite_number(ep.get("score")):
                expected_valid[group_key].append((seed, float(ep["score"])))

    for (agent, tier, version, seed), locs in sorted(seen.items()):
        if len(locs) > 1:
            failures.append(
                f"duplicate (agent={agent}, tier={tier}, version={version}, seed={seed}) in {', '.join(locs)}"
            )

    loader = load_committed_fn if load_committed_fn is not None else R.load_committed
    rows, _ = loader(root)
    rows_by_key: dict[tuple[str, str, str], Any] = {}
    for row in rows:
        rkey = (row.tier, str((row.extra or {}).get("tiers_version") or ""), row.agent)
        if rkey in rows_by_key:
            failures.append(f"canary.reproduce produced duplicate row for {rkey}")
        rows_by_key[rkey] = row

    all_keys = sorted(set(expected_valid) | set(invalid_by_key))
    for key in all_keys:
        exp_pairs = sorted(expected_valid.get(key, []))
        inv_items = invalid_by_key.get(key, [])
        row = rows_by_key.get(key)
        if row is None:
            if exp_pairs or inv_items:
                failures.append(f"canary.reproduce missing row for {key}")
            continue
        got_pairs = sorted(zip([int(s) for s in row.seeds], [float(x) for x in row.scores]))
        if got_pairs != exp_pairs:
            failures.append(
                f"canary.reproduce scores/seeds mismatch for {key}: got {len(got_pairs)} item(s), "
                f"expected {len(exp_pairs)} valid item(s) (valid:false episodes must be excluded)"
            )
        if inv_items:
            inv_seeds = {sd for sd, _, _ in inv_items}
            valid_seeds = {sd for sd, _ in exp_pairs}
            leaked_seeds = sorted((set(int(s) for s in row.seeds) & inv_seeds) - valid_seeds)
            if leaked_seeds:
                failures.append(f"canary.reproduce included valid:false seed(s) {leaked_seeds} in scores for {key}")
            recorded_inv = (row.extra or {}).get("invalid") or []
            if len(recorded_inv) != len(inv_items):
                failures.append(
                    f"canary.reproduce invalid count mismatch for {key}: "
                    f"got {len(recorded_inv)}, expected {len(inv_items)}"
                )
        if exp_pairs:
            exp_mean = sum(s for _, s in exp_pairs) / len(exp_pairs)
            got_mean = R.mean(row.scores)
            if not (math.isfinite(got_mean) and abs(got_mean - exp_mean) < 1e-12):
                failures.append(
                    f"canary.reproduce mean mismatch for {key}: got {got_mean}, expected {exp_mean}"
                )
        elif row.scores:
            failures.append(f"canary.reproduce expected empty scores for invalid-only group {key}, got {row.scores}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} integrity issue(s) across {len(files)} committed file(s)",
            failures,
        )
    if invalid_flags:
        return CheckResult(
            name,
            "WARN",
            f"{len(files)} files, {total_episodes} episodes audited; "
            f"{len(invalid_flags)} valid:false episode(s) flagged and verified excluded from canary.reproduce means",
            invalid_flags,
        )
    return CheckResult(
        name,
        "PASS",
        f"{len(files)} files, {total_episodes} episodes audited; 0 duplicates, 0 valid:false, all score invariants hold",
    )


def _dockerfile_instructions(text: str) -> list[str]:
    logical: list[str] = []
    buf = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        if stripped.endswith("\\"):
            buf += stripped[:-1].strip() + " "
        else:
            buf += stripped
            logical.append(buf.strip())
            buf = ""
    if buf.strip():
        logical.append(buf.strip())
    return logical


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


def audit_harbor_task_dir(task_dir: Path) -> list[str]:
    failures: list[str] = []
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        return [f"missing {toml_path}"]

    raw_toml = toml_path.read_text(encoding="utf-8")
    try:
        parsed = tomllib.loads(raw_toml)
    except tomllib.TOMLDecodeError as exc:
        return [f"invalid task.toml: {exc}"]

    verifier = parsed.get("verifier")
    if not isinstance(verifier, dict):
        failures.append("task.toml missing [verifier] section")
    else:
        if verifier.get("environment_mode") != "separate":
            failures.append(
                f"task.toml verifier.environment_mode expected 'separate', got {verifier.get('environment_mode')!r}"
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
            failures.append(f"task.toml [environment] exposes CANARY_* to agent container: {', '.join(leaks)}")

    dockerfile = task_dir / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        failures.append("missing environment/Dockerfile")
    else:
        for inst in _dockerfile_instructions(dockerfile.read_text(encoding="utf-8")):
            try:
                parts = shlex.split(inst)
            except ValueError:
                parts = inst.split()
            if not parts:
                continue
            op = parts[0].upper()
            args = [tok for tok in parts[1:] if not tok.startswith("--")]
            if op in {"COPY", "ADD"}:
                for tok in args[:-1] if len(args) >= 2 else args:
                    norm = tok.strip("/")
                    segs = set(Path(norm).parts) if norm else {"."}
                    if norm in {"", "."} or "canary" in segs or "canary-server" in segs or "SALT" in segs or "episode.json" in segs:
                        failures.append(f"agent environment/Dockerfile copies forbidden source '{tok}': {inst}")
                if args:
                    dst_segs = set(Path(args[-1].strip("/")).parts)
                    if "canary" in dst_segs or "canary-server" in dst_segs:
                        failures.append(f"agent environment/Dockerfile copies into canary target '{args[-1]}': {inst}")
            elif op == "ENV":
                if re.search(r"\bCANARY_[A-Z0-9_]*", inst):
                    failures.append(f"agent environment/Dockerfile sets CANARY_* env var: {inst}")
            elif op == "RUN":
                if re.search(r"\bpip\s+install\b.*\bcanary\b", inst):
                    failures.append(f"agent environment/Dockerfile installs canary package: {inst}")

    env_dir = task_dir / "environment"
    if env_dir.is_dir():
        for child in env_dir.iterdir():
            if child.name == "canary-server":
                continue
            if child.name in {"canary", "SALT", "episode.json"} or child.name.endswith(".world.json"):
                failures.append(f"forbidden file/dir in agent environment build context: {child.name}")

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
        negates_sidecar = any(
            ln.startswith("!") and "canary-server" in ln
            for ln in ig_lines
        )
        if not excludes_sidecar or negates_sidecar:
            failures.append("environment/.dockerignore does not cleanly exclude canary-server")

    sidecar = task_dir / "environment" / "canary-server"
    for label, rel_path in (
        ("SALT", Path("data/worlds/judge/SALT")),
        ("episode.json", Path("episode.json")),
    ):
        target = sidecar / rel_path
        if not target.exists():
            failures.append(f"missing sidecar {label} at {rel_path}")
            continue
        if target.is_symlink() or not target.is_file():
            failures.append(f"sidecar {label} must be a regular non-symlink file")
            continue
        st = target.stat()
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            failures.append(f"sidecar {label} mode expected 0o600, got {oct(mode)}")
        if st.st_size == 0:
            failures.append(f"sidecar {label} is empty")

    ep_path = sidecar / "episode.json"
    if ep_path.is_file() and not ep_path.is_symlink():
        try:
            ep_obj = json.loads(ep_path.read_text(encoding="utf-8"))
            if not isinstance(ep_obj, dict) or "tier" not in ep_obj or "seed" not in ep_obj:
                failures.append("sidecar episode.json missing tier/seed keys")
        except ValueError as exc:
            failures.append(f"sidecar episode.json invalid JSON: {exc}")

    return failures


def check_harbor_package(
    root: Path,
    task_dir: Path | None = None,
    tier: str = "medium",
    seed: int = 900000,
) -> CheckResult:
    name = "Harbor Package Static Audit"
    if task_dir is not None:
        failures = audit_harbor_task_dir(task_dir)
        if failures:
            return CheckResult(name, "FAIL", f"{len(failures)} Harbor isolation/package failure(s)", failures)
        return CheckResult(
            name,
            "PASS",
            f"{task_dir.name} verified (separate verifier, [[verifier.collect]], clean Dockerfile/.dockerignore, 0600 SALT & episode.json, 0 CANARY_* agent env vars)",
        )

    build_py = root / "harbor" / "build.py"
    if not build_py.is_file():
        return CheckResult(name, "FAIL", f"missing {build_py}")

    with tempfile.TemporaryDirectory(prefix="canary-audit-harbor-") as tmp:
        env = {**os.environ, "PYTHONPATH": str(root)}
        proc = subprocess.run(
            [sys.executable, str(build_py), "--tiers", tier, "--seeds", str(seed), "--out", tmp],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-400:]
            return CheckResult(name, "FAIL", f"harbor/build.py exited with {proc.returncode}", [err] if err else [])
        built = Path(tmp) / f"canary-{tier}-{seed}"
        failures = audit_harbor_task_dir(built)
        if failures:
            return CheckResult(name, "FAIL", f"{len(failures)} Harbor isolation/package failure(s)", failures)
        return CheckResult(
            name,
            "PASS",
            f"{built.name} verified (separate verifier, [[verifier.collect]], clean Dockerfile/.dockerignore, 0600 SALT & episode.json, 0 CANARY_* agent env vars)",
        )


def _git_status_porcelain(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _default_reproduce_runner(root: Path, fast: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    if fast:
        env["REPRO_FAST"] = "1"
        env.pop("REPRO_SEEDS", None)
    else:
        env.pop("REPRO_FAST", None)
    return subprocess.run(
        [sys.executable, "-m", "canary.eval", "--reproduce"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _finalize_clean_reproduce(
    root: Path,
    before: str,
    proc: subprocess.CompletedProcess[str],
    elapsed: float,
    fast: bool,
) -> CheckResult:
    name = "Clean-Tree Reproduce Audit"
    if proc.returncode != 0:
        snippet = (proc.stderr or proc.stdout or "").strip()[-400:]
        return CheckResult(
            name,
            "FAIL",
            f"reproduce failed with exit code {proc.returncode}",
            [snippet] if snippet else [],
        )

    failures: list[str] = []
    for artifact in ("judge_table.md", "judge_episodes.jsonl"):
        ap = root / "results" / "latest" / artifact
        if not ap.is_file():
            failures.append(f"missing expected reproduce output: results/latest/{artifact}")

    after = _git_status_porcelain(root)
    if after is None:
        failures.append("git status --porcelain failed after reproduce")
    elif after != before:
        before_lines = set(before.splitlines())
        after_lines = set(after.splitlines())
        changed = sorted(before_lines ^ after_lines)
        failures.append(f"git status --porcelain changed ({len(changed)} line(s)): {', '.join(changed[:10])}")

    if failures:
        return CheckResult(name, "FAIL", "reproduce dirtied working tree or missed outputs", failures)

    mode_label = "REPRO_FAST=1" if fast else "full"
    return CheckResult(
        name,
        "PASS",
        f"{mode_label} reproduce succeeded in {elapsed:.2f}s; git status --porcelain unchanged",
    )


def check_clean_reproduce(
    root: Path,
    fast: bool = True,
    runner: Callable[[Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> CheckResult:
    before = _git_status_porcelain(root)
    if before is None:
        return CheckResult("Clean-Tree Reproduce Audit", "FAIL", "git status --porcelain failed before reproduce")

    t0 = time.monotonic()
    run_fn = runner if runner is not None else _default_reproduce_runner
    proc = run_fn(root, fast)
    elapsed = time.monotonic() - t0
    return _finalize_clean_reproduce(root, before, proc, elapsed, fast)


def audit_repo(
    root: Path = ROOT,
    run_reproduce: bool = False,
    fast_reproduce: bool = True,
) -> list[CheckResult]:
    if not run_reproduce:
        return [
            check_secret_hygiene(root),
            check_frozen_tiers(),
            check_committed_runs(root),
            check_harbor_package(root),
        ]

    before = _git_status_porcelain(root)
    if before is None:
        return [
            check_secret_hygiene(root),
            check_frozen_tiers(),
            check_committed_runs(root),
            check_harbor_package(root),
            CheckResult("Clean-Tree Reproduce Audit", "FAIL", "git status --porcelain failed before reproduce"),
        ]

    def _timed_repro() -> tuple[subprocess.CompletedProcess[str], float]:
        t0 = time.monotonic()
        proc = _default_reproduce_runner(root, fast_reproduce)
        return proc, time.monotonic() - t0

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_timed_repro)
        results = [
            check_secret_hygiene(root),
            check_frozen_tiers(),
            check_committed_runs(root),
            check_harbor_package(root),
        ]
        proc, repro_elapsed = fut.result()

    results.append(_finalize_clean_reproduce(root, before, proc, repro_elapsed, fast_reproduce))
    return results


def format_report(results: list[CheckResult], elapsed_s: float) -> str:
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
    ap = argparse.ArgumentParser(description="Automated submission hygiene and integrity audit for Canary.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to audit")
    ap.add_argument("--run-reproduce", action="store_true", help="Run REPRO_FAST=1 reproduce and verify clean git status")
    ap.add_argument("--full-reproduce", action="store_true", help="Disable REPRO_FAST=1 when --run-reproduce is set")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = audit_repo(
        root=args.root.resolve(),
        run_reproduce=args.run_reproduce,
        fast_reproduce=not args.full_reproduce,
    )
    elapsed = time.monotonic() - t0

    if args.json:
        payload = {
            "results": [asdict(r) for r in results],
            "elapsed_s": round(elapsed, 4),
            "passed": not any(r.status == "FAIL" for r in results),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
