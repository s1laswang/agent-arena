from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)

COMMENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("line comment //", SLASH_SLASH),
    ("block comment open /*", SLASH_STAR),
    ("block comment close */", STAR_SLASH),
)

XSS_SINKS: tuple[str, ...] = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
)

DOC_WRITE_SPACED_RX = re.compile(r"\bdocument\s*\.\s*write\b")

PROTECTED_EXACT: frozenset[str] = frozenset({
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
})

PROTECTED_PREFIXES: tuple[str, ...] = (
    "canary/solver/",
    "harbor/",
)

PROTECTED_GIT_TARGETS: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver",
    "harbor",
)

DEFAULT_BASE_CANDIDATES: tuple[str, ...] = (
    "origin/justSilas",
    "justSilas",
    "origin/fr8/canary/craft-arena",
    "HEAD",
)

EXPECTED_V14_HASH = "a8f99c2537c91d72"


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def is_protected_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in PROTECTED_EXACT or norm in {"canary/solver", "harbor"}:
        return True
    return any(norm.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def discover_ui_files(root: Path) -> tuple[Path, list[Path]]:
    ui_dir = root / "docs" / "arena" / "ui"
    if not ui_dir.is_dir():
        return ui_dir, []
    files = sorted(p for p in ui_dir.rglob("*") if p.is_file())
    return ui_dir, files


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_ui_sources(
    root: Path,
    ui_files: Sequence[Path],
) -> tuple[list[tuple[str, str]], list[str]]:
    loaded: list[tuple[str, str]] = []
    errors: list[str] = []
    for fpath in ui_files:
        rel = _rel_posix(root, fpath)
        try:
            raw_bytes = fpath.read_bytes()
        except OSError as exc:
            errors.append(f"{rel}: unreadable file ({exc})")
            continue
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(
                f"{rel}: invalid UTF-8 / non-ASCII byte at offset {exc.start}"
            )
            continue
        if not text.strip():
            errors.append(f"{rel}: empty UI file")
        loaded.append((rel, text))
    return loaded, errors


def check_ui_ascii_and_em_dashes(
    root: Path,
    ui_dir_exists: bool,
    loaded_files: Sequence[tuple[str, str]],
    read_errors: Sequence[str],
) -> CheckResult:
    name = "UI Pure ASCII & Zero Em-Dash Check"
    if not ui_dir_exists:
        return CheckResult(
            name,
            "FAIL",
            "docs/arena/ui directory does not exist",
            ["missing directory: docs/arena/ui"],
        )
    if not loaded_files and not read_errors:
        return CheckResult(
            name,
            "FAIL",
            "docs/arena/ui contains 0 files",
            ["expected at least 1 UI file under docs/arena/ui/**"],
        )

    violations: list[str] = list(read_errors)
    for rel, text in loaded_files:
        for lineno, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                col = line.index(EM_DASH) + 1
                violations.append(f"{rel}:{lineno}:{col}: em dash (U+2014) / non-ASCII character")
            if EN_DASH in line:
                col = line.index(EN_DASH) + 1
                violations.append(f"{rel}:{lineno}:{col}: en dash (U+2013) / non-ASCII character")
            if UNICODE_MINUS in line:
                col = line.index(UNICODE_MINUS) + 1
                violations.append(f"{rel}:{lineno}:{col}: unicode minus (U+2212) / non-ASCII character")
            if not line.isascii():
                for col, ch in enumerate(line, 1):
                    if ord(ch) > 127 and ch not in {EM_DASH, EN_DASH, UNICODE_MINUS}:
                        violations.append(
                            f"{rel}:{lineno}:{col}: non-ASCII character U+{ord(ch):04X}"
                        )
                        break

    walkthrough_path = root / "docs" / "arena" / "WALKTHROUGH.md"
    walkthrough_checked = False
    if walkthrough_path.is_file():
        walkthrough_checked = True
        try:
            wt_text = walkthrough_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"docs/arena/WALKTHROUGH.md: unreadable or invalid UTF-8 ({exc})")
            wt_text = ""
        if wt_text:
            for lineno, line in enumerate(wt_text.splitlines(), 1):
                if EM_DASH in line:
                    col = line.index(EM_DASH) + 1
                    violations.append(
                        f"docs/arena/WALKTHROUGH.md:{lineno}:{col}: em dash (U+2014) / non-ASCII"
                    )
                if EN_DASH in line:
                    col = line.index(EN_DASH) + 1
                    violations.append(
                        f"docs/arena/WALKTHROUGH.md:{lineno}:{col}: en dash (U+2013) / non-ASCII"
                    )
                if not line.isascii():
                    for col, ch in enumerate(line, 1):
                        if ord(ch) > 127 and ch not in {EM_DASH, EN_DASH}:
                            violations.append(
                                f"docs/arena/WALKTHROUGH.md:{lineno}:{col}: non-ASCII U+{ord(ch):04X}"
                            )
                            break

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} ASCII or dash violation(s) across {len(loaded_files)} UI file(s)",
            violations,
        )
    extra = " + docs/arena/WALKTHROUGH.md" if walkthrough_checked else ""
    return CheckResult(
        name,
        "PASS",
        f"all {len(loaded_files)} file(s) in docs/arena/ui/**{extra} are pure ASCII with 0 em dashes",
    )


def check_ui_zero_comments(
    ui_dir_exists: bool,
    loaded_files: Sequence[tuple[str, str]],
) -> CheckResult:
    name = "UI Zero Comments Check"
    if not ui_dir_exists or not loaded_files:
        return CheckResult(
            name,
            "FAIL",
            "no readable files in docs/arena/ui/** to verify",
            ["docs/arena/ui/** has 0 readable files"],
        )

    violations: list[str] = []
    for rel, text in loaded_files:
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, marker in COMMENT_MARKERS:
                if marker in line:
                    col = line.index(marker) + 1
                    violations.append(f"{rel}:{lineno}:{col}: forbidden {label}")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} comment marker violation(s) across {len(loaded_files)} UI file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 comment markers (//, /*, */) across {len(loaded_files)} file(s) in docs/arena/ui/**",
    )


def check_ui_zero_xss_sinks(
    ui_dir_exists: bool,
    loaded_files: Sequence[tuple[str, str]],
) -> CheckResult:
    name = "UI Zero XSS Sinks Check"
    if not ui_dir_exists or not loaded_files:
        return CheckResult(
            name,
            "FAIL",
            "no readable files in docs/arena/ui/** to verify",
            ["docs/arena/ui/** has 0 readable files"],
        )

    violations: list[str] = []
    for rel, text in loaded_files:
        for lineno, line in enumerate(text.splitlines(), 1):
            for sink in XSS_SINKS:
                if sink in line:
                    col = line.index(sink) + 1
                    violations.append(f"{rel}:{lineno}:{col}: forbidden XSS sink '{sink}'")
            if "document.write" not in line:
                m_spaced = DOC_WRITE_SPACED_RX.search(line)
                if m_spaced is not None:
                    violations.append(
                        f"{rel}:{lineno}:{m_spaced.start() + 1}: forbidden XSS sink 'document.write'"
                    )

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} XSS sink violation(s) across {len(loaded_files)} UI file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 XSS sinks (innerHTML, outerHTML, insertAdjacentHTML, document.write) across {len(loaded_files)} UI file(s)",
    )


def _run_git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _resolve_base_ref(root: Path, explicit_base: str | None) -> tuple[str | None, str | None]:
    if explicit_base is not None:
        proc = _run_git(root, ["rev-parse", "--verify", f"{explicit_base}^{{commit}}"])
        if proc is None or proc.returncode != 0:
            return None, f"explicit --base-ref '{explicit_base}' could not be resolved"
        return explicit_base, None

    for candidate in DEFAULT_BASE_CANDIDATES:
        proc = _run_git(root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
        if proc is not None and proc.returncode == 0:
            return candidate, None
    return None, None


def check_protected_paths_unmodified(
    root: Path,
    base_ref: str | None = None,
) -> CheckResult:
    name = "Protected Paths Unmodified Check"
    violations: list[str] = []

    rules_path = root / "canary" / "rules.py"
    if rules_path.is_file():
        try:
            rules_txt = rules_path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"canary/rules.py: unreadable ({exc})")
            rules_txt = ""
        if rules_txt and 'TIERS_VERSION = "v1.4"' not in rules_txt:
            violations.append(
                'canary/rules.py: missing frozen TIERS_VERSION = "v1.4"'
            )
        if root.resolve() == ROOT.resolve():
            from canary import rules as live_rules

            tier_obj: dict[str, Any] = {
                "tiers": {k: v.to_dict() for k, v in live_rules.TIERS.items()},
                "known_v_mode": live_rules.KNOWN_V_MODE,
            }
            v14_hash = hashlib.sha256(
                json.dumps(tier_obj, sort_keys=True, default=list).encode("utf-8")
            ).hexdigest()[:16]
            if v14_hash != EXPECTED_V14_HASH:
                violations.append(
                    f"canary/rules.py: frozen v1.4 hash expected {EXPECTED_V14_HASH}, got {v14_hash}"
                )

    if not (root / ".git").exists():
        if base_ref is not None:
            violations.append(
                f"cannot verify --base-ref '{base_ref}' because {root} has no .git metadata"
            )
        if violations:
            return CheckResult(
                name,
                "FAIL",
                f"{len(violations)} protected-path violation(s)",
                violations,
            )
        return CheckResult(
            name,
            "PASS",
            "0 protected paths modified (non-git directory check)",
        )

    resolved_ref, err = _resolve_base_ref(root, base_ref)
    if err is not None:
        return CheckResult(name, "FAIL", err, [err])

    touched: dict[str, set[str]] = {}

    if resolved_ref is not None:
        mb_proc = _run_git(root, ["merge-base", resolved_ref, "HEAD"])
        diff_base = (
            mb_proc.stdout.strip()
            if (mb_proc is not None and mb_proc.returncode == 0 and mb_proc.stdout.strip())
            else resolved_ref
        )
        committed_proc = _run_git(root, ["diff", "--name-only", f"{diff_base}..HEAD"])
        if committed_proc is not None and committed_proc.returncode == 0:
            for line in committed_proc.stdout.splitlines():
                p = line.strip()
                if p and is_protected_path(p):
                    touched.setdefault(p, set()).add(f"committed vs {resolved_ref}")

    for label, git_args in (
        ("staged", ["diff", "--name-only", "--cached"]),
        ("worktree", ["diff", "--name-only"]),
        (
            "untracked",
            ["ls-files", "--others", "--exclude-standard", "--", *PROTECTED_GIT_TARGETS],
        ),
    ):
        proc = _run_git(root, git_args)
        if proc is not None and proc.returncode == 0:
            for line in proc.stdout.splitlines():
                p = line.strip()
                if p and is_protected_path(p):
                    touched.setdefault(p, set()).add(label)

    for path_key in sorted(touched):
        reasons = ", ".join(sorted(touched[path_key]))
        violations.append(f"protected path modified: {path_key} ({reasons})")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} protected-path violation(s) detected",
            violations,
        )

    ref_note = f" against {resolved_ref}" if resolved_ref else ""
    return CheckResult(
        name,
        "PASS",
        f"0 protected paths modified{ref_note} (canary/env.py, canary/rules.py, canary/solver/, canary/reproduce.py, harbor/)",
    )


def verify_arena_ui_contract(
    root: Path = ROOT,
    base_ref: str | None = None,
) -> list[CheckResult]:
    resolved_root = root.resolve()
    ui_dir, ui_files = discover_ui_files(resolved_root)
    ui_dir_exists = ui_dir.is_dir()
    loaded_files, read_errors = _read_ui_sources(resolved_root, ui_files)
    return [
        check_ui_ascii_and_em_dashes(resolved_root, ui_dir_exists, loaded_files, read_errors),
        check_ui_zero_comments(ui_dir_exists, loaded_files),
        check_ui_zero_xss_sinks(ui_dir_exists, loaded_files),
        check_protected_paths_unmodified(resolved_root, base_ref=base_ref),
    ]


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
        lines.append(f"[{res.status}] {res.name}: {res.summary}")
        for detail in res.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify Canary Arena UI files are pure ASCII, comment-free, em-dash-free, XSS-safe, and touch 0 protected paths."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Run strict UI contract checks and exit non-zero on any violation",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root directory to verify",
    )
    ap.add_argument(
        "--base-ref",
        default=None,
        help="Optional git base ref for protected-path diff check",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON verification report",
    )
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_arena_ui_contract(root=args.root, base_ref=args.base_ref)
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        payload = {
            "check_mode": bool(args.check or True),
            "passed": passed,
            "elapsed_s": round(elapsed, 4),
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
