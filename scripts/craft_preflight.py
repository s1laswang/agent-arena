from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
OPENCODE_TMP = Path("/tmp/opencode")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EN_DASH_CHAR = chr(0x2013)
PLUS_MINUS_CHAR = chr(0x00B1)
DEFAULT_BASE = "origin/justSilas"

CHECK_PROTECTED_PATHS = "Protected Paths Guard"
CHECK_HEADLINE_PAIRED = "Makefile HEADLINE & Paired-Table Integrity"
CHECK_UNAPPROVED_GAP = "Unapproved Gap-Row & Honesty Guard"

GATE_PROTECTED = "Protected Paths Compliance"
GATE_HEADLINE = "Makefile HEADLINE & Paired Tables"
GATE_CONSISTENCY = "Craft Consistency & Provenance"
GATE_DOC_COMMANDS = "Doc Commands, Paths & CLI Flags"
GATE_DOC_HYGIENE = "Documentation Hygiene Audit"
GATE_WALKTHROUGH = "Judge Walkthrough 4-Pillar Verification"
GATE_SURFACES = "Cross-Track Submission Surfaces"
GATE_GAP_GUARD = "Unapproved Gap-Row & Honesty Guard"
GATE_SUBMISSION = "Submission Static & Hygiene Audit"
GATE_ZIP_EXPORT = "Gitless ZIP Export Verification"

OPTIONAL_SIBLING_VERIFIERS: tuple[tuple[str, str], ...] = (
    ("verify_commit_provenance", "Commit Provenance Verification"),
    ("verify_submission_doc", "Submission Document Verification"),
    ("verify_artifact_numbers", "Artifact Number Provenance Verification"),
)

DEFAULT_GATE_NAMES: tuple[str, ...] = (
    GATE_PROTECTED,
    GATE_HEADLINE,
    GATE_CONSISTENCY,
    GATE_DOC_COMMANDS,
    GATE_DOC_HYGIENE,
    GATE_WALKTHROUGH,
    GATE_SURFACES,
    GATE_GAP_GUARD,
)

FALLBACK_PROTECTED_RULES: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/world.py",
    "canary/types.py",
    "canary/eval.py",
    "canary/reproduce.py",
    "canary/mcp_server.py",
    "canary/solver/",
    "harbor/",
    "Makefile",
    "configs/",
    "data/runs/committed/",
    "results/judge_table.md",
    ".github/protected-paths.txt",
    ".github/workflows/",
)

JUDGE_FACING_GAP_DOCS: tuple[str, ...] = (
    "README.md",
    "JUDGE_QUICKSTART.md",
    "docs/JUDGE-WALKTHROUGH.md",
    "docs/PEER-REVIEW-QA.md",
    "docs/REPRODUCIBILITY.md",
    "docs/DIFFICULTY.md",
    "docs/CONTRACT.md",
    "docs/EXPLOITS.md",
    "docs/gemini/SUBMISSION.md",
    "pitch/GEMINI.md",
    "harbor/README.md",
)

STRICT_JUDGE_SUMMARY_DOCS: frozenset[str] = frozenset(
    {
        "JUDGE_QUICKSTART.md",
        "docs/JUDGE-WALKTHROUGH.md",
        "docs/PEER-REVIEW-QA.md",
        "docs/REPRODUCIBILITY.md",
    }
)

PANEL_FIX_A_DOCS: frozenset[str] = frozenset(
    {
        "README.md",
        "JUDGE_QUICKSTART.md",
        "docs/JUDGE-WALKTHROUGH.md",
        "docs/PEER-REVIEW-QA.md",
        "docs/REPRODUCIBILITY.md",
    }
)

PAIRED_TABLE_EXTENDED_DOCS: frozenset[str] = frozenset(
    {
        "docs/PEER-REVIEW-QA.md",
    }
)

GAP_HISTORY_SPLIT_RX = re.compile(r"(?m)^\s*(?:---|\x23\s+History\b)")
RAW_HEADLINE_CI_RX = re.compile(r"65%\s*\[\s*24%\s*,\s*98%\s*\]")
LA_HEADLINE_CI_RX = re.compile(r"72%\s*\[\s*52%\s*,\s*91%\s*\]")
BAD_PREREG_029_RX = re.compile(
    r"(?:pre-register\w*[^\n]{0,45}\b0(?:-|\u2013)29\b|\b0(?:-|\u2013)29\b[^\n]{0,45}pre-register\w*)",
    re.IGNORECASE,
)
EXEMPT_PREREG_029_RX = re.compile(
    r"(?:gpt-5\.5|not\s+(?:a\s+)?pre-register|post-hoc\s+lock)",
    re.IGNORECASE,
)
INTERROGATIVE_PREREG_029_RX = re.compile(
    r"\b(?:were|was|are|is)\s+(?:the\s+)?(?:primary\s+|locked\s+)?(?:dev\s+)?seeds?\s+`?0(?:-|\u2013)29`?\s+pre-register\w*[^\n?]*\?",
    re.IGNORECASE,
)

FLASH_GAP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("75% [36%, 123%]", re.compile(r"75%\s*\[\s*36%\s*,\s*123%\s*\]")),
    ("22% [-23%, 63%]", re.compile(r"22%\s*\[\s*[-\u2212]23%\s*,\s*63%\s*\]")),
    (
        "+0.373 +/- 0.177",
        re.compile(r"[+]?0\.373\s*(?:\+/-|\u00b1)\s*0\.177"),
    ),
    (
        "opencode:google/gemini-3.5-flash",
        re.compile(r"opencode:google/gemini-3\.5-flash", re.IGNORECASE),
    ),
    (
        "opencode-gemini-3.5-flash",
        re.compile(r"opencode-gemini-3\.5-flash", re.IGNORECASE),
    ),
    (
        "OpenCode + gemini-3.5-flash",
        re.compile(
            r"OpenCode\s*\+\s*(?:`?google/)?`?gemini-3\.5-flash`?",
            re.IGNORECASE,
        ),
    ),
    (
        "gemini-3.5-flash OpenCode gap row",
        re.compile(
            r"gemini-3\.5-flash[^\n]{0,100}(?:75%|22%|\+0\.373|\+0\.110)",
            re.IGNORECASE,
        ),
    ),
)

OPENCODE_MODEL_ROW_RX = re.compile(
    r"(?:OpenCode\s*\+\s*`?(?:[a-z][a-z0-9_-]*/)?([a-z][a-z0-9._-]+)`?)"
    r"|(?:opencode:([a-z][a-z0-9_-]*/[a-z][a-z0-9._-]+))",
    re.IGNORECASE,
)

MAKEFILE_HEADLINE_GREP = "| hard | OpenCode + gemini-4-carbon over MCP (judges' shape)"


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class GateResult:
    gate: str
    name: str
    status: str
    summary: str
    checks: list[CheckResult] = field(default_factory=list)


def _load_module_from_path(module_name: str, target: Path) -> ModuleType:
    resolved_target = target.resolve()
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None):
        try:
            if Path(existing.__file__).resolve() == resolved_target:
                return existing
        except OSError:
            pass
    spec = importlib.util.spec_from_file_location(module_name, resolved_target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {resolved_target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_script_module(module_name: str, filename: str) -> ModuleType:
    target = (SCRIPTS_DIR / filename).resolve()
    mod = _load_module_from_path(module_name, target)
    pkg_name = f"scripts.{module_name}"
    if pkg_name not in sys.modules:
        sys.modules[pkg_name] = mod
    return mod


def _coerce_check(item: object) -> CheckResult:
    if isinstance(item, dict):
        return CheckResult(
            name=str(item.get("name", "Check")),
            status=str(item.get("status", "FAIL")),
            summary=str(item.get("summary", "")),
            details=[str(x) for x in item.get("details", [])],
        )
    return CheckResult(
        name=str(getattr(item, "name")),
        status=str(getattr(item, "status")),
        summary=str(getattr(item, "summary")),
        details=[str(x) for x in getattr(item, "details", [])],
    )


def _coerce_checks(raw_checks: Sequence[object]) -> list[CheckResult]:
    return [_coerce_check(item) for item in raw_checks]


def _aggregate_gate(gate_code: str, gate_name: str, checks: list[CheckResult]) -> GateResult:
    statuses = {c.status for c in checks}
    if not checks or "FAIL" in statuses:
        status = "FAIL"
    elif "WARN" in statuses:
        status = "WARN"
    else:
        status = "PASS"
    if len(checks) == 1 and checks[0].name in {gate_name, CHECK_PROTECTED_PATHS, CHECK_HEADLINE_PAIRED, CHECK_UNAPPROVED_GAP}:
        summary = checks[0].summary
    else:
        p = sum(1 for c in checks if c.status == "PASS")
        w = sum(1 for c in checks if c.status == "WARN")
        f = sum(1 for c in checks if c.status == "FAIL")
        summary = f"{p} PASS, {w} WARN, {f} FAIL across {len(checks)} check(s)"
    return GateResult(gate=gate_code, name=gate_name, status=status, summary=summary, checks=checks)


def _has_dot_git(root: Path) -> bool:
    dot_git = root / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return env


def _parse_protected_rules(text: str) -> list[str]:
    rules: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        rules.append(stripped)
    return rules


def _match_protected_rule(rel_path: str, rules: Sequence[str]) -> str | None:
    norm = rel_path.strip().lstrip("./")
    if not norm:
        return None
    for rule in rules:
        if rule.endswith("/"):
            if norm == rule.rstrip("/") or norm.startswith(rule):
                return rule
        elif norm == rule:
            return rule
    return None


def _git_ref_exists(root: Path, ref: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _git_current_branch(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _parse_name_status_z(raw_bytes: bytes) -> list[tuple[str, str, str | None]]:
    text = raw_bytes.decode("utf-8", errors="replace")
    tokens = text.split("\0")
    entries: list[tuple[str, str, str | None]] = []
    idx = 0
    while idx < len(tokens) and tokens[idx]:
        status_tok = tokens[idx]
        idx += 1
        code = status_tok[0]
        if code in {"R", "C"}:
            if idx + 1 < len(tokens):
                old_p = tokens[idx]
                new_p = tokens[idx + 1]
                idx += 2
                entries.append((code, new_p, old_p))
        else:
            if idx < len(tokens):
                path = tokens[idx]
                idx += 1
                entries.append((code, path, None))
    return entries


def _working_tree_entries(root: Path) -> set[str]:
    all_touched: set[str] = set()
    env = _git_env(root)
    for cmd in (
        ["git", "diff", "-z", "--name-status"],
        ["git", "diff", "-z", "--cached", "--name-status"],
    ):
        try:
            proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            for _, path, old_p in _parse_name_status_z(proc.stdout):
                if path:
                    all_touched.add(path)
                if old_p:
                    all_touched.add(old_p)

    try:
        untracked = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard"],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        untracked = None
    if untracked is not None and untracked.returncode == 0:
        for rel in untracked.stdout.decode("utf-8", errors="replace").split("\0"):
            if rel:
                all_touched.add(rel)

    return all_touched


def _load_ref_protected_rules(root: Path, ref: str) -> list[str]:
    try:
        show_proc = subprocess.run(
            ["git", "show", f"{ref}:.github/protected-paths.txt"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if show_proc.returncode != 0:
        return []
    return _parse_protected_rules(show_proc.stdout)


def check_protected_paths(
    root: Path = ROOT,
    check_protected_vs: str | None = None,
    *,
    base: str | None = None,
) -> CheckResult:
    name = CHECK_PROTECTED_PATHS
    resolved = root.resolve()
    explicit_ref = check_protected_vs if check_protected_vs is not None else base

    rules_set: set[str] = set()
    protected_file = resolved / ".github" / "protected-paths.txt"
    has_local_rules = False
    if protected_file.is_file():
        parsed_local = _parse_protected_rules(
            protected_file.read_text(encoding="utf-8", errors="replace")
        )
        if parsed_local:
            rules_set.update(parsed_local)
            has_local_rules = True

    if not _has_dot_git(resolved):
        if explicit_ref:
            return CheckResult(
                name,
                "FAIL",
                f"cannot diff --check-protected-vs '{explicit_ref}': .git absent",
            )
        if not has_local_rules:
            return CheckResult(
                name,
                "FAIL",
                "missing or empty .github/protected-paths.txt in gitless directory",
            )
        return CheckResult(
            name,
            "WARN",
            f"gitless directory (.git absent); {len(rules_set)} protected rule(s) verified in .github/protected-paths.txt",
        )

    target_ref: str | None = None
    if explicit_ref:
        if not _git_ref_exists(resolved, explicit_ref):
            return CheckResult(
                name,
                "FAIL",
                f"protected-paths ref '{explicit_ref}' not found",
            )
        target_ref = explicit_ref
    else:
        branch = _git_current_branch(resolved)
        if branch and branch != "justSilas" and _git_ref_exists(resolved, DEFAULT_BASE):
            target_ref = DEFAULT_BASE

    if target_ref is not None:
        rules_set.update(_load_ref_protected_rules(resolved, target_ref))

    if not rules_set:
        if explicit_ref:
            rules_set.update(FALLBACK_PROTECTED_RULES)
        else:
            return CheckResult(
                name,
                "FAIL",
                "missing or empty .github/protected-paths.txt",
            )

    rules = sorted(rules_set)
    changed_paths: set[str] = _working_tree_entries(resolved)
    scope_desc = "working tree"

    if target_ref is not None:
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "-z", "--name-status", f"{target_ref}...HEAD"],
                cwd=resolved,
                env=_git_env(resolved),
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            diff_proc = None
        if diff_proc is None or diff_proc.returncode != 0:
            if explicit_ref:
                return CheckResult(
                    name,
                    "FAIL",
                    f"git diff {explicit_ref}...HEAD failed (shallow or unrelated history)",
                )
        else:
            for _, path, old_p in _parse_name_status_z(diff_proc.stdout):
                if path:
                    changed_paths.add(path)
                if old_p:
                    changed_paths.add(old_p)
            scope_desc = f"{target_ref} + working tree"

    violations: list[str] = []
    for rel in sorted(changed_paths):
        matched_rule = _match_protected_rule(rel, rules)
        if matched_rule is not None:
            violations.append(f"{rel} (matches protected rule '{matched_rule}')")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} protected path(s) touched vs {scope_desc}",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 protected paths touched across {len(changed_paths)} changed file(s) ({len(rules)} rules, {scope_desc})",
    )


def _is_nan(val: Any) -> bool:
    return val is None or (isinstance(val, float) and math.isnan(val))


def _is_finite_float(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _fmt_paired_num(val: Any, digits: int = 3) -> str:
    if _is_nan(val):
        return EN_DASH_CHAR
    return f"{float(val):.{digits}f}"


def _fmt_paired_luck(row: dict[str, Any]) -> str:
    pe_r = row.get("post_expected_ratio")
    pe_lo = row.get("post_expected_lo")
    pe_hi = row.get("post_expected_hi")
    if row.get("agent") == "solver" or _is_nan(pe_r):
        return EN_DASH_CHAR
    if _is_nan(pe_lo) or _is_nan(pe_hi):
        return f"{float(pe_r):.0%}"
    return f"**{float(pe_r):.0%} [{float(pe_lo):.0%}, {float(pe_hi):.0%}]**"


def _render_paired_md_row(row: dict[str, Any]) -> str:
    is_solver = row.get("agent") == "solver"
    rat = row.get("ratio")
    r_lo = row.get("ratio_lo")
    r_hi = row.get("ratio_hi")
    if is_solver or _is_nan(rat):
        ratio_str = EN_DASH_CHAR
    elif _is_nan(r_lo) or _is_nan(r_hi):
        ratio_str = f"{float(rat):.0%}"
    else:
        ratio_str = f"{float(rat):.0%} [{float(r_lo):.0%}, {float(r_hi):.0%}]"
    diff_str = (
        EN_DASH_CHAR
        if is_solver
        else f"{_fmt_paired_num(row.get('diff'))} {PLUS_MINUS_CHAR} {_fmt_paired_num(row.get('diff_ci'))}"
    )
    return (
        f"| {row['tier']} | {row['label']} | {int(row['n'])} | "
        f"{_fmt_paired_num(row['mean'])} {PLUS_MINUS_CHAR} {_fmt_paired_num(row['ci'])} | "
        f"{float(row['accuracy']):.2f} | {float(row['accused_rate']):.2f} | "
        f"{float(row['accuse_day']):.1f} | {_fmt_paired_num(row.get('p_accused'), 2)} | "
        f"{_fmt_paired_num(row['solver_same_seeds'])} | {ratio_str} | {diff_str} | "
        f"{_fmt_paired_num(row['post_expected'])} | {_fmt_paired_luck(row)} |"
    )


def _extract_md_pipe_data_rows(md_text: str) -> list[str]:
    pipe_lines = [
        ln.strip()
        for ln in md_text.splitlines()
        if ln.strip().startswith("|") and ln.strip().endswith("|")
    ]
    if len(pipe_lines) < 2:
        return []
    return pipe_lines[2:]


def _find_primary_row(rows: Sequence[dict[str, Any]], group: str, tier: str) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("group") != group or row.get("tier") != tier:
            continue
        lbl = str(row.get("label", "")).lower()
        if "alternative" in lbl or "not the headline" in lbl:
            continue
        return row
    return None


def check_headline_paired_tables(root: Path = ROOT) -> CheckResult:
    name = CHECK_HEADLINE_PAIRED
    resolved = root.resolve()
    failures: list[str] = []

    makefile_path = resolved / "Makefile"
    if not makefile_path.is_file():
        failures.append("missing Makefile")
    else:
        mk_text = makefile_path.read_text(encoding="utf-8", errors="replace")
        for req_tok in (
            "scripts/paired_gemini.py",
            "data/runs/committed/v1.4/paired_table_gemini.md",
            "HEADLINE",
            MAKEFILE_HEADLINE_GREP,
        ):
            if req_tok not in mk_text:
                failures.append(f"Makefile reproduce recipe missing '{req_tok}'")

    gem_json_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    gem_md_rel = "data/runs/committed/v1.4/paired_table_gemini.md"
    ext_json_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    ext_md_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md"

    gem_json_path = resolved / gem_json_rel
    gem_md_path = resolved / gem_md_rel
    ext_json_path = resolved / ext_json_rel
    ext_md_path = resolved / ext_md_rel

    gem_rows: list[dict[str, Any]] | None = None
    if not gem_json_path.is_file():
        failures.append(f"missing {gem_json_rel}")
    else:
        try:
            parsed_gem = json.loads(gem_json_path.read_text(encoding="utf-8"))
            if not isinstance(parsed_gem, list) or not parsed_gem:
                failures.append(f"{gem_json_rel} must be a non-empty JSON list")
            else:
                gem_rows = parsed_gem
        except (OSError, ValueError) as exc:
            failures.append(f"{gem_json_rel}: invalid JSON ({exc})")

    gem_md_text = ""
    if not gem_md_path.is_file():
        failures.append(f"missing {gem_md_rel}")
    else:
        try:
            gem_md_text = gem_md_path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{gem_md_rel}: unreadable ({exc})")

    oc_hard_gem: dict[str, Any] | None = None
    if gem_rows is not None:
        oc_hard_gem = _find_primary_row(gem_rows, "v1.4/opencode-gemini-4-carbon", "hard")
        if oc_hard_gem is None:
            failures.append(f"{gem_json_rel}: missing primary v1.4/opencode-gemini-4-carbon hard row")
        else:
            if oc_hard_gem.get("n") != 30 or oc_hard_gem.get("seeds") != list(range(30)):
                failures.append(f"{gem_json_rel}: primary hard row expected n=30 and seeds 0..29")
            req_fields = (
                "mean",
                "ci",
                "solver_same_seeds",
                "ratio",
                "ratio_lo",
                "ratio_hi",
                "diff",
                "diff_ci",
                "post_expected",
                "post_expected_ratio",
                "post_expected_lo",
                "post_expected_hi",
                "solver_post_expected",
            )
            if not all(_is_finite_float(oc_hard_gem.get(k)) for k in req_fields):
                failures.append(f"{gem_json_rel}: non-finite numeric field in primary hard row")
            else:
                m_val = float(oc_hard_gem["mean"])
                s_val = float(oc_hard_gem["solver_same_seeds"])
                r_val = float(oc_hard_gem["ratio"])
                r_lo = float(oc_hard_gem["ratio_lo"])
                r_hi = float(oc_hard_gem["ratio_hi"])
                d_val = float(oc_hard_gem["diff"])
                pe_val = float(oc_hard_gem["post_expected"])
                spe_val = float(oc_hard_gem["solver_post_expected"])
                per_val = float(oc_hard_gem["post_expected_ratio"])
                per_lo = float(oc_hard_gem["post_expected_lo"])
                per_hi = float(oc_hard_gem["post_expected_hi"])
                if s_val <= 0.0 or abs(m_val / s_val - r_val) > 1e-6:
                    failures.append(f"{gem_json_rel}: mean / solver_same_seeds != ratio")
                if abs((m_val - s_val) - d_val) > 1e-6:
                    failures.append(f"{gem_json_rel}: mean - solver_same_seeds != diff")
                if spe_val <= 0.0 or abs(pe_val / spe_val - per_val) > 1e-6:
                    failures.append(f"{gem_json_rel}: post_expected / solver_post_expected != post_expected_ratio")
                if not (r_lo <= r_val <= r_hi < 1.0):
                    failures.append(f"{gem_json_rel}: raw ratio CI [{r_lo}, {r_hi}] invalid or includes parity")
                if not (per_lo <= per_val <= per_hi < 1.0):
                    failures.append(
                        f"{gem_json_rel}: luck-adjusted ratio CI [{per_lo}, {per_hi}] invalid or includes parity"
                    )

        if gem_md_text:
            if MAKEFILE_HEADLINE_GREP not in gem_md_text:
                failures.append(f"{gem_md_rel}: missing Makefile HEADLINE grep target '{MAKEFILE_HEADLINE_GREP}'")
            try:
                rendered_gem = sorted(_render_paired_md_row(r) for r in gem_rows)
                md_gem_rows = sorted(_extract_md_pipe_data_rows(gem_md_text))
                if rendered_gem != md_gem_rows:
                    failures.append(
                        f"{gem_md_rel} out of sync with {gem_json_rel} "
                        f"({len(md_gem_rows)} md row(s) vs {len(rendered_gem)} json row(s))"
                    )
            except (KeyError, TypeError, ValueError) as exc:
                failures.append(f"{gem_json_rel}: row formatting error ({exc})")

    if not ext_json_path.is_file():
        failures.append(f"missing {ext_json_rel}")
    else:
        try:
            ext_rows = json.loads(ext_json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"{ext_json_rel}: invalid JSON ({exc})")
            ext_rows = None

        if not isinstance(ext_rows, list) or not ext_rows:
            if ext_rows is not None:
                failures.append(f"{ext_json_rel} must be a non-empty JSON list")
        else:
            p_row = _find_primary_row(ext_rows, "v1.4/opencode-gemini-4-carbon", "hard")
            e_row = _find_primary_row(ext_rows, "v1.4/opencode-gemini-4-carbon-ext", "hard")
            pool_row = _find_primary_row(
                ext_rows,
                "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
                "hard",
            )
            if p_row is None or e_row is None or pool_row is None:
                failures.append(f"{ext_json_rel}: missing primary, extension, or pooled hard row")
            else:
                p_seeds = p_row.get("seeds")
                e_seeds = e_row.get("seeds")
                pool_seeds = pool_row.get("seeds")
                if not (
                    isinstance(p_seeds, list)
                    and isinstance(e_seeds, list)
                    and isinstance(pool_seeds, list)
                ):
                    failures.append(f"{ext_json_rel}: seeds must be lists on primary/extension/pooled rows")
                else:
                    if p_seeds != list(range(30)) or int(p_row.get("n", -1)) != 30:
                        failures.append(f"{ext_json_rel}: primary row expected n=30 and seeds 0..29")
                    if not e_seeds or int(e_row.get("n", -1)) != len(e_seeds):
                        failures.append(f"{ext_json_rel}: extension row invalid seed count")
                    if any((not isinstance(s, int) or isinstance(s, bool) or not (30 <= s <= 59)) for s in e_seeds):
                        failures.append(f"{ext_json_rel}: extension seeds {e_seeds} outside 30..59")
                    if set(p_seeds) & set(e_seeds):
                        failures.append(f"{ext_json_rel}: primary and extension seed sets overlap")
                    if pool_seeds != sorted([*p_seeds, *e_seeds]) or int(pool_row.get("n", -1)) != len(pool_seeds):
                        failures.append(f"{ext_json_rel}: pooled seeds/n do not equal union of primary + extension")

                try:
                    n_p = int(p_row["n"])
                    n_e = int(e_row["n"])
                    n_pool = int(pool_row["n"])
                    if n_pool > 0:
                        exp_mean = (n_p * float(p_row["mean"]) + n_e * float(e_row["mean"])) / n_pool
                        exp_sv = (
                            n_p * float(p_row["solver_same_seeds"]) + n_e * float(e_row["solver_same_seeds"])
                        ) / n_pool
                        exp_pe = (
                            n_p * float(p_row["post_expected"]) + n_e * float(e_row["post_expected"])
                        ) / n_pool
                        if abs(exp_mean - float(pool_row["mean"])) > 1e-9:
                            failures.append(f"{ext_json_rel}: pooled mean {pool_row['mean']} != weighted {exp_mean}")
                        if abs(exp_sv - float(pool_row["solver_same_seeds"])) > 1e-9:
                            failures.append(
                                f"{ext_json_rel}: pooled solver_same_seeds {pool_row['solver_same_seeds']} != weighted {exp_sv}"
                            )
                        if abs(exp_pe - float(pool_row["post_expected"])) > 1e-9:
                            failures.append(
                                f"{ext_json_rel}: pooled post_expected {pool_row['post_expected']} != weighted {exp_pe}"
                            )
                        if abs(float(pool_row["mean"]) / float(pool_row["solver_same_seeds"]) - float(pool_row["ratio"])) > 1e-6:
                            failures.append(f"{ext_json_rel}: pooled mean / solver_same_seeds != ratio")
                    if oc_hard_gem is not None:
                        for shared_k in ("mean", "solver_same_seeds", "ratio", "post_expected_ratio"):
                            if abs(float(p_row[shared_k]) - float(oc_hard_gem[shared_k])) > 1e-9:
                                failures.append(
                                    f"cross-table drift on primary hard {shared_k}: "
                                    f"{ext_json_rel}={p_row[shared_k]} vs {gem_json_rel}={oc_hard_gem[shared_k]}"
                                )
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                    failures.append(f"{ext_json_rel}: malformed pooled numeric fields ({exc})")

            if ext_md_path.is_file():
                try:
                    ext_md_text = ext_md_path.read_text(encoding="utf-8")
                    rendered_ext = sorted(_render_paired_md_row(r) for r in ext_rows)
                    md_ext_rows = sorted(_extract_md_pipe_data_rows(ext_md_text))
                    if rendered_ext != md_ext_rows:
                        failures.append(f"{ext_md_rel} out of sync with {ext_json_rel}")
                except (OSError, KeyError, TypeError, ValueError) as exc:
                    failures.append(f"{ext_md_rel}: verification error ({exc})")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Makefile HEADLINE / paired-table integrity failure(s)",
            failures,
        )
    assert oc_hard_gem is not None
    raw_pct = f"{float(oc_hard_gem['ratio']):.0%} [{float(oc_hard_gem['ratio_lo']):.0%}, {float(oc_hard_gem['ratio_hi']):.0%}]"
    la_pct = (
        f"{float(oc_hard_gem['post_expected_ratio']):.0%} "
        f"[{float(oc_hard_gem['post_expected_lo']):.0%}, {float(oc_hard_gem['post_expected_hi']):.0%}]"
    )
    return CheckResult(
        name,
        "PASS",
        f"Makefile HEADLINE, paired_table_gemini (.json/.md, {raw_pct} raw, {la_pct} luck-adj), and paired_table_pooled0to59 verified",
    )


def _gitless_secret_hygiene(root: Path, sub_mod: ModuleType) -> CheckResult:
    name = "Secret & Answer-Key Hygiene"
    violations: list[str] = []
    warnings: list[str] = []
    scanned = 0
    allowed_templates = getattr(
        sub_mod,
        "ALLOWED_ENV_TEMPLATES",
        frozenset({".env.example", ".env.sample", ".env.template"}),
    )
    key_patterns = getattr(sub_mod, "API_KEY_PATTERNS", ())
    fixture_markers = getattr(sub_mod, "TEST_FIXTURE_MARKERS", ())

    for fp in sorted(root.rglob("*")):
        if not fp.is_file() or fp.is_symlink():
            continue
        rel_parts = fp.relative_to(root).parts
        if rel_parts[:2] == ("results", "latest"):
            continue
        rel = fp.relative_to(root).as_posix()
        scanned += 1
        if fp.name == ".env" or (fp.name.startswith(".env.") and fp.name not in allowed_templates):
            violations.append(f"env file in gitless tree: {rel}")
        if fp.name == "SALT" or "SALT" in rel_parts:
            violations.append(f"SALT file in gitless tree: {rel}")
        try:
            raw = fp.read_bytes()
        except OSError as exc:
            violations.append(f"unreadable file {rel}: {type(exc).__name__}")
            continue
        if rel.endswith(".world.json"):
            txt = raw.decode("utf-8", errors="replace")
            if '"mole"' in txt:
                violations.append(f"world file containing mole answer key: {rel}")
            else:
                warnings.append(f"world file (no mole field found): {rel}")
        if b"\x00" in raw or (b"AIza" not in raw and b"sk-" not in raw):
            continue
        txt = raw.decode("utf-8", errors="replace")
        for kind, rx in key_patterns:
            for match in rx.finditer(txt):
                tok = match.group(0)
                if rel.startswith("tests/") and any(m in tok.lower() for m in fixture_markers):
                    continue
                violations.append(f"raw API key ({kind}: {tok[:6]}...) in {rel}")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"gitless fallback: {len(violations)} secret/answer-key violation(s) across {scanned} file(s)",
            violations,
        )
    return CheckResult(
        name,
        "WARN",
        f"gitless fallback (.git absent): scanned {scanned} file(s); 0 secrets or answer keys",
        warnings,
    )


def _run_harbor_check_in_tmp(
    root: Path,
    sub_mod: ModuleType,
    tmp_base: Path,
    tier: str = "hard",
    seed: int = 900000,
) -> CheckResult:
    build_py = root / "harbor" / "build.py"
    if not build_py.is_file():
        return _coerce_check(sub_mod.check_harbor_package(root, tier=tier, seed=seed))
    tmp_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix="canary-preflight-harbor-") as tmp_str:
        env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run(
                [sys.executable, str(build_py), "--tiers", tier, "--seeds", str(seed), "--out", tmp_str],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult("Harbor Package Static Audit", "FAIL", f"harbor/build.py failed: {exc}")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-400:]
            return CheckResult(
                "Harbor Package Static Audit",
                "FAIL",
                f"harbor/build.py exited with {proc.returncode}",
                [err] if err else [],
            )
        built = Path(tmp_str) / f"canary-{tier}-{seed}"
        return _coerce_check(sub_mod.check_harbor_package(root, task_dir=built, tier=tier, seed=seed))


def _discover_unapproved_v14_models(root: Path, active_gap_lower: str) -> list[tuple[str, str]]:
    unapproved: list[tuple[str, str]] = []
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    if not v14_dir.is_dir():
        return unapproved
    for entry in sorted(v14_dir.iterdir()):
        if not entry.is_dir() or entry.name == "reference":
            continue
        model_id = ""
        for sub_tier in ("hard", "medium", "easy"):
            meta_fp = entry / sub_tier / "meta.json"
            if meta_fp.is_file():
                try:
                    meta_obj = json.loads(meta_fp.read_text(encoding="utf-8"))
                    if isinstance(meta_obj, dict):
                        raw_mid = str(meta_obj.get("model_id") or meta_obj.get("model") or "").strip()
                        if "/" in raw_mid:
                            raw_mid = raw_mid.split("/", 1)[1]
                        if raw_mid:
                            model_id = raw_mid
                            break
                except (OSError, ValueError):
                    continue
        if not model_id:
            for prefix in ("opencode-", "inproc-"):
                if entry.name.startswith(prefix):
                    model_id = entry.name[len(prefix) :]
                    break
        if model_id and model_id.lower() not in active_gap_lower:
            unapproved.append((entry.name, model_id))
    return unapproved


def _discover_paired_table_models(root: Path) -> set[str]:
    paired_json = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
    if not paired_json.is_file():
        return set()
    try:
        rows = json.loads(paired_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(rows, list):
        return set()
    found: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        agent_str = str(row.get("agent") or "").strip()
        if ":" in agent_str:
            agent_str = agent_str.split(":", 1)[1]
        if "/" in agent_str:
            agent_str = agent_str.split("/", 1)[1]
        if agent_str and agent_str.lower() not in {"solver", "heuristic", "do_nothing", "stop_early", "guess_day1"}:
            found.add(agent_str.lower())
    return found


def check_unapproved_gap_rows(root: Path = ROOT) -> CheckResult:
    name = CHECK_UNAPPROVED_GAP
    resolved = root.resolve()
    gap_path = resolved / "docs" / "reports" / "gap.md"
    if not gap_path.is_file():
        return CheckResult(
            name,
            "FAIL",
            "missing docs/reports/gap.md (sole source for AfterQuery frontier-gap rows)",
        )

    try:
        full_gap_text = gap_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return CheckResult(name, "FAIL", f"unreadable docs/reports/gap.md ({type(exc).__name__})")

    active_gap_text = GAP_HISTORY_SPLIT_RX.split(full_gap_text, maxsplit=1)[0]
    active_gap_lower = active_gap_text.lower()
    full_gap_lower = full_gap_text.lower()

    flash_approved = "gemini-3.5-flash" in active_gap_lower
    paired_table_models = _discover_paired_table_models(resolved)
    unapproved_v14 = _discover_unapproved_v14_models(resolved, active_gap_lower)

    failures: list[str] = []
    scanned_docs = 0

    for rel in JUDGE_FACING_GAP_DOCS:
        doc_path = resolved / rel
        if not doc_path.is_file():
            continue
        scanned_docs += 1
        try:
            doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failures.append(f"{rel}: unreadable judge-facing doc ({type(exc).__name__})")
            continue

        is_strict_summary = rel in STRICT_JUDGE_SUMMARY_DOCS
        check_panel_fix_a = rel in PANEL_FIX_A_DOCS
        allows_paired_table = rel in PAIRED_TABLE_EXTENDED_DOCS
        doc_flash_approved = flash_approved or (
            allows_paired_table and "gemini-3.5-flash" in paired_table_models
        )

        for lineno, raw_line in enumerate(doc_text.splitlines(), 1):
            if not doc_flash_approved:
                for label, rx in FLASH_GAP_PATTERNS:
                    if rx.search(raw_line):
                        failures.append(
                            f"{rel}:{lineno}: unapproved gemini-3.5-flash gap claim '{label}' "
                            "(not in active docs/reports/gap.md)"
                        )
                        break
                else:
                    if is_strict_summary and re.search(r"(?<![0-9.])\+0\.373(?![0-9])", raw_line):
                        failures.append(
                            f"{rel}:{lineno}: unapproved '+0.373' gap claim "
                            "(not in active docs/reports/gap.md)"
                        )

            for dir_name, model_id in unapproved_v14:
                if model_id.lower() == "gemini-3.5-flash":
                    continue
                if allows_paired_table and model_id.lower() in paired_table_models:
                    continue
                model_esc = re.escape(model_id)
                dir_esc = re.escape(dir_name)
                if re.search(
                    rf"(?:{dir_esc}|OpenCode\s*\+\s*(?:`?[a-z0-9_-]+/)?`?{model_esc}`?|opencode:[a-z0-9_-]+/{model_esc})",
                    raw_line,
                    re.IGNORECASE,
                ):
                    failures.append(
                        f"{rel}:{lineno}: unapproved v1.4 frontier-gap model '{model_id}' "
                        "(not in active docs/reports/gap.md)"
                    )

            for m in OPENCODE_MODEL_ROW_RX.finditer(raw_line):
                raw_model = (m.group(1) or m.group(2) or "").strip("`")
                if "/" in raw_model:
                    raw_model = raw_model.split("/", 1)[1]
                low_model = raw_model.lower()
                if not low_model or low_model in {"model", "provider"}:
                    continue
                if low_model in active_gap_lower:
                    continue
                if allows_paired_table and low_model in paired_table_models:
                    continue
                if low_model in full_gap_lower and re.search(r"\bv1\.[23]\b", raw_line, re.IGNORECASE):
                    continue
                if low_model == "gemini-3.5-flash" and not doc_flash_approved:
                    continue
                failures.append(
                    f"{rel}:{lineno}: OpenCode model '{raw_model}' cited outside active docs/reports/gap.md"
                )

            if check_panel_fix_a:
                m_raw_ci = RAW_HEADLINE_CI_RX.search(raw_line)
                m_la_ci = LA_HEADLINE_CI_RX.search(raw_line)
                if m_raw_ci and m_la_ci and m_la_ci.start() < m_raw_ci.start():
                    failures.append(
                        f"{rel}:{lineno}: Panel Fix A violation (lead with raw '65% [24%, 98%]' before luck-adjusted '72% [52%, 91%]')"
                    )
                non_q_line = INTERROGATIVE_PREREG_029_RX.sub("", raw_line)
                if BAD_PREREG_029_RX.search(non_q_line) and not EXEMPT_PREREG_029_RX.search(non_q_line):
                    failures.append(
                        f"{rel}:{lineno}: Panel Fix A violation (Gemini dev seeds 0-29 are a post-hoc lock, not pre-registered)"
                    )

    if scanned_docs == 0:
        return CheckResult(name, "FAIL", "no judge-facing docs found to scan against docs/reports/gap.md")
    if failures:
        deduped = list(dict.fromkeys(failures))
        return CheckResult(
            name,
            "FAIL",
            f"{len(deduped)} unapproved frontier-gap or Panel Fix A violation(s) across {scanned_docs} doc(s)",
            deduped,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 unapproved frontier-gap rows and 0 Panel Fix A violations across {scanned_docs} judge-facing doc(s)",
    )


def run_submission_audit(root: Path = ROOT, tmp_base: Path = OPENCODE_TMP) -> list[CheckResult]:
    resolved = root.resolve()
    sub_mod = _load_script_module("audit_submission", "audit_submission.py")
    sec = (
        _coerce_check(sub_mod.check_secret_hygiene(resolved))
        if _has_dot_git(resolved)
        else _gitless_secret_hygiene(resolved, sub_mod)
    )
    frz = _coerce_check(sub_mod.check_frozen_tiers())
    com = _coerce_check(sub_mod.check_committed_runs(resolved))
    har = _run_harbor_check_in_tmp(resolved, sub_mod, tmp_base=tmp_base)
    return [sec, frz, com, har]


def run_craft_consistency(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("check_craft_consistency", "check_craft_consistency.py")
    fn = getattr(mod, "audit_repo", None) or getattr(mod, "audit_craft_consistency")
    return _coerce_checks(fn(root=resolved))


def run_doc_commands(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("verify_doc_commands", "verify_doc_commands.py")
    fn = getattr(mod, "verify_repo", None) or getattr(mod, "audit_repo")
    return _coerce_checks(fn(root=resolved))


def run_doc_hygiene(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("audit_doc_hygiene", "audit_doc_hygiene.py")
    fn = getattr(mod, "audit_repo", None) or getattr(mod, "audit_doc_hygiene")
    return _coerce_checks(fn(root=resolved))


def run_judge_walkthrough(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("verify_judge_walkthrough", "verify_judge_walkthrough.py")
    fn = getattr(mod, "verify_repo", None) or getattr(mod, "verify_judge_walkthrough")
    return _coerce_checks(fn(root=resolved))


def run_submission_surfaces(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("verify_submission_surfaces", "verify_submission_surfaces.py")
    fn = getattr(mod, "audit_repo", None) or getattr(mod, "verify_submission_surfaces")
    return _coerce_checks(fn(root=resolved))


def run_zip_export(root: Path = ROOT, tmp_base: Path = OPENCODE_TMP) -> list[CheckResult]:
    resolved = root.resolve()
    mod = _load_script_module("verify_zip_export", "verify_zip_export.py")
    return _coerce_checks(mod.verify_zip_export(root=resolved, tmp_base=tmp_base.resolve()))


def discover_optional_verifiers(root: Path = ROOT) -> dict[str, Path]:
    resolved = root.resolve()
    found: dict[str, Path] = {}
    scripts_dir = resolved / "scripts"
    for stem, _ in OPTIONAL_SIBLING_VERIFIERS:
        cand = scripts_dir / f"{stem}.py"
        if cand.is_file():
            found[stem] = cand.resolve()
    return found


def _coerce_optional_return(raw: object) -> list[CheckResult] | None:
    if isinstance(raw, dict):
        seq = raw.get("results") if isinstance(raw.get("results"), list) else raw.get("checks")
        if isinstance(seq, list):
            return _coerce_checks(seq)
        return None
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        if not raw:
            return []
        first = raw[0]
        if isinstance(first, dict) or (hasattr(first, "name") and hasattr(first, "status")):
            return _coerce_checks(raw)
        return None
    if hasattr(raw, "name") and hasattr(raw, "status"):
        return [_coerce_check(raw)]
    return None


def run_optional_verifier(
    stem: str,
    script_path: Path,
    root: Path = ROOT,
    gate_label: str | None = None,
) -> list[CheckResult]:
    resolved = root.resolve()
    fallback_name = gate_label or stem
    try:
        st = script_path.stat()
        stamp = f"{st.st_mtime_ns}_{st.st_size}"
    except OSError:
        stamp = "missing"
    mod_key = f"_craft_opt_{stem}_{abs(hash(str(script_path.resolve())))}_{stamp}"
    try:
        mod = _load_module_from_path(mod_key, script_path)
    except Exception as exc:
        return [CheckResult(fallback_name, "FAIL", f"failed loading {stem}.py: {type(exc).__name__}: {exc}")]

    short = stem.removeprefix("verify_").removeprefix("audit_").removeprefix("check_")
    candidate_names = (
        "audit_repo",
        "verify_repo",
        stem,
        f"verify_{short}",
        f"audit_{short}",
        f"check_{short}",
        "run_checks",
        "check_all",
    )
    for attr_name in candidate_names:
        fn = getattr(mod, attr_name, None)
        if not callable(fn):
            continue
        try:
            try:
                raw_out = fn(root=resolved)
            except TypeError:
                try:
                    raw_out = fn(resolved)
                except TypeError:
                    raw_out = fn()
        except Exception as exc:
            return [CheckResult(fallback_name, "FAIL", f"{stem}.{attr_name} raised {type(exc).__name__}: {exc}")]
        coerced = _coerce_optional_return(raw_out)
        if coerced is not None and len(coerced) > 0:
            return coerced

    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--root", str(resolved), "--json"],
            cwd=resolved,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [CheckResult(fallback_name, "FAIL", f"{stem}.py CLI invocation failed: {exc}")]

    stdout_txt = (proc.stdout or "").strip()
    if stdout_txt:
        try:
            parsed_cli = json.loads(stdout_txt)
            coerced_cli = _coerce_optional_return(parsed_cli)
            if coerced_cli:
                return coerced_cli
        except ValueError:
            pass

    status = "PASS" if proc.returncode == 0 else "FAIL"
    snippet = (proc.stderr or proc.stdout or "").strip().splitlines()
    summary = snippet[-1] if snippet else f"{stem}.py exited with {proc.returncode}"
    return [CheckResult(fallback_name, status, summary)]


def _gate_letter(idx: int) -> str:
    return chr(ord("a") + idx)


def run_craft_preflight_gates(
    root: Path = ROOT,
    *,
    check_protected_vs: str | None = None,
    base: str | None = None,
    with_zip: bool = False,
    include_zip_export: bool = False,
    with_submission_audit: bool = False,
    tmp_base: Path | None = None,
) -> list[GateResult]:
    resolved = root.resolve()
    effective_ref = check_protected_vs if check_protected_vs is not None else base
    effective_zip = bool(with_zip or include_zip_export)
    effective_tmp = (tmp_base if tmp_base is not None else OPENCODE_TMP).resolve()
    effective_tmp.mkdir(parents=True, exist_ok=True)

    for mod_name, filename in (
        ("verify_doc_commands", "verify_doc_commands.py"),
        ("check_craft_consistency", "check_craft_consistency.py"),
        ("audit_doc_hygiene", "audit_doc_hygiene.py"),
        ("verify_judge_walkthrough", "verify_judge_walkthrough.py"),
        ("verify_submission_surfaces", "verify_submission_surfaces.py"),
    ):
        _load_script_module(mod_name, filename)

    optional_found = discover_optional_verifiers(resolved)

    tasks: list[tuple[str, Callable[[], list[CheckResult]]]] = [
        (GATE_PROTECTED, lambda: [check_protected_paths(resolved, check_protected_vs=effective_ref)]),
        (GATE_HEADLINE, lambda: [check_headline_paired_tables(resolved)]),
        (GATE_CONSISTENCY, lambda: run_craft_consistency(resolved)),
        (GATE_DOC_COMMANDS, lambda: run_doc_commands(resolved)),
        (GATE_DOC_HYGIENE, lambda: run_doc_hygiene(resolved)),
        (GATE_WALKTHROUGH, lambda: run_judge_walkthrough(resolved)),
        (GATE_SURFACES, lambda: run_submission_surfaces(resolved)),
        (GATE_GAP_GUARD, lambda: [check_unapproved_gap_rows(resolved)]),
    ]

    for stem, label in OPTIONAL_SIBLING_VERIFIERS:
        if stem in optional_found:
            script_path = optional_found[stem]
            tasks.append(
                (
                    label,
                    lambda s=stem, p=script_path, lbl=label: run_optional_verifier(
                        s, p, root=resolved, gate_label=lbl
                    ),
                )
            )

    with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool:
        futs = [(gate_name, pool.submit(fn)) for gate_name, fn in tasks]
        ordered_results: list[tuple[str, list[CheckResult]]] = [
            (gate_name, fut.result()) for gate_name, fut in futs
        ]

    if with_submission_audit:
        ordered_results.append((GATE_SUBMISSION, run_submission_audit(resolved, tmp_base=effective_tmp)))

    if effective_zip:
        ordered_results.append((GATE_ZIP_EXPORT, run_zip_export(resolved, tmp_base=effective_tmp)))

    return [
        _aggregate_gate(_gate_letter(idx), gate_name, checks)
        for idx, (gate_name, checks) in enumerate(ordered_results)
    ]


def flatten_checks(gates: Sequence[GateResult]) -> list[CheckResult]:
    return [chk for gate in gates for chk in gate.checks]


def run_craft_preflight(
    root: Path = ROOT,
    *,
    check_protected_vs: str | None = None,
    base: str | None = None,
    with_zip: bool = False,
    include_zip_export: bool = False,
    with_submission_audit: bool = False,
    tmp_base: Path | None = None,
) -> list[CheckResult]:
    gates = run_craft_preflight_gates(
        root=root,
        check_protected_vs=check_protected_vs,
        base=base,
        with_zip=with_zip,
        include_zip_export=include_zip_export,
        with_submission_audit=with_submission_audit,
        tmp_base=tmp_base,
    )
    return flatten_checks(gates)


audit_repo = run_craft_preflight
verify_repo = run_craft_preflight


def format_report(gates: Sequence[GateResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for gate in gates:
        lines.append(f"[{gate.status}] Gate ({gate.gate}) {gate.name}: {gate.summary}")
        multi = len(gate.checks) > 1
        for chk in gate.checks:
            counts[chk.status] = counts.get(chk.status, 0) + 1
            if multi:
                lines.append(f"  [{chk.status}] {chk.name}: {chk.summary}")
            for detail in chk.details:
                indent = "         - " if multi else "       - "
                lines.append(f"{indent}{detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Unified keyless one-command Craft preflight gate for Canary."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to audit")
    ap.add_argument(
        "--check-protected-vs",
        "--base",
        dest="check_protected_vs",
        type=str,
        default=None,
        help="Git ref to diff against .github/protected-paths.txt",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument(
        "--with-zip",
        "--include-zip-export",
        dest="with_zip",
        action="store_true",
        help="Also run gitless ZIP export verification under /tmp/opencode",
    )
    ap.add_argument(
        "--with-submission-audit",
        dest="with_submission_audit",
        action="store_true",
        help="Also run full submission static and committed-runs audit",
    )
    ap.add_argument(
        "--tmp-root",
        type=Path,
        default=OPENCODE_TMP,
        help="Temporary directory root under /tmp/opencode",
    )
    args = ap.parse_args(argv)

    resolved_root = args.root.resolve()
    t0 = time.monotonic()
    gates = run_craft_preflight_gates(
        root=resolved_root,
        check_protected_vs=args.check_protected_vs,
        with_zip=args.with_zip,
        with_submission_audit=args.with_submission_audit,
        tmp_base=args.tmp_root.resolve(),
    )
    elapsed = time.monotonic() - t0
    checks = flatten_checks(gates)
    counts = {
        "PASS": sum(1 for c in checks if c.status == "PASS"),
        "WARN": sum(1 for c in checks if c.status == "WARN"),
        "FAIL": sum(1 for c in checks if c.status == "FAIL"),
    }
    passed = counts["FAIL"] == 0
    discovered = discover_optional_verifiers(resolved_root)
    optional_status = {
        stem: ("present" if stem in discovered else "absent")
        for stem, _ in OPTIONAL_SIBLING_VERIFIERS
    }

    if args.json:
        items = [asdict(c) for c in checks]
        payload = {
            "passed": passed,
            "elapsed_s": round(elapsed, 4),
            "check_protected_vs": args.check_protected_vs,
            "with_zip": bool(args.with_zip),
            "include_zip_export": bool(args.with_zip),
            "with_submission_audit": bool(args.with_submission_audit),
            "optional_verifiers": optional_status,
            "counts": counts,
            "gates": [asdict(g) for g in gates],
            "results": items,
            "checks": items,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(gates, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
