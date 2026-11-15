from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tokenize
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
CO_AUTHOR_LOWER = "co-authored" + "-by"

MAX_SQUAD_FILE_BYTES = 250 * 1024
MAX_W9_FILE_BYTES = 130 * 1024

W9_OWNED_FILES: tuple[str, ...] = (
    "docs/reports/integrity_cross_squad_security_gate.md",
    "docs/reports/integrity_hunter_sandbox_and_stub_sweep.md",
    "docs/reports/integrity_issue_ledger.md",
    "docs/reports/judge_15min_hunt.md",
    "scripts/integrity_cross_squad_security_gate.py",
    "scripts/integrity_hunter_sandbox_and_stub_sweep.py",
    "scripts/judge_15min_whitebox_hunt.py",
    "scripts/verify_integrity_branch.py",
    "tests/test_integrity_cross_squad_security_gate.py",
    "tests/test_integrity_hunter_sandbox_and_stub_sweep.py",
    "tests/test_judge_15min_whitebox_hunt.py",
    "tests/test_verify_integrity_branch.py",
)

MANDATORY_PROTECTED_RULES: tuple[str, ...] = (
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

FORBIDDEN_WORKSPACE_DIRS: tuple[str, ...] = (
    ".venv",
    "venv",
    "node_modules",
)

FORBIDDEN_BINARY_SUFFIXES: tuple[str, ...] = (
    ".safetensors",
    ".bin",
    ".pt",
    ".pth",
    ".ckpt",
    ".onnx",
    ".gguf",
)

KNOWN_SQUAD_OWNED_FILES: tuple[str, ...] = (
    "canary/redteam/gemini_mcp_hunter.py",
    "canary/redteam/harbor_sidecar_audit.py",
    "canary/redteam/tamper_guard.py",
    "docs/reports/harbor_sidecar_key_proposal.md",
    "docs/reports/integrity_cost_and_trajectory_boundary_sweep.md",
    "docs/reports/integrity_cross_squad_security_gate.md",
    "docs/reports/integrity_expert_tier_audit.md",
    "docs/reports/integrity_final_make_hunt_v14.md",
    "docs/reports/integrity_game_and_gateway_audit.md",
    "docs/reports/integrity_gpt55_and_rehearsal_audit.md",
    "docs/reports/integrity_heuristic_evolution_v14.md",
    "docs/reports/integrity_hunter_sandbox_and_stub_sweep.md",
    "docs/reports/integrity_issue_ledger.md",
    "docs/reports/integrity_mcp_wire_sweep.md",
    "docs/reports/integrity_megahunt_and_corpus_v14.md",
    "docs/reports/integrity_mole_hof_and_rl_audit.md",
    "docs/reports/integrity_offline_mcp_hunter_sweep.md",
    "docs/reports/integrity_replays_and_harbor.md",
    "docs/reports/integrity_sidechannel_and_text_sweep.md",
    "docs/reports/integrity_submit2_rehearsal_and_freeze_audit.md",
    "docs/reports/integrity_v14_fuzz_sweep.md",
    "docs/reports/integrity_v14_v15_differential_sweep.md",
    "docs/reports/integrity_v15_social_sweep.md",
    "docs/reports/integrity_verda_and_frontier_provenance.md",
    "docs/reports/judge_15min_hunt.md",
    "scripts/integrity_audit_replays_and_harbor.py",
    "scripts/integrity_cost_and_trajectory_boundary_sweep.py",
    "scripts/integrity_cross_squad_security_gate.py",
    "scripts/integrity_expert_tier_audit.py",
    "scripts/integrity_final_make_hunt_v14.py",
    "scripts/integrity_game_and_gateway_audit.py",
    "scripts/integrity_gpt55_and_rehearsal_audit.py",
    "scripts/integrity_heuristic_evolution_v14.py",
    "scripts/integrity_hunter_sandbox_and_stub_sweep.py",
    "scripts/integrity_mcp_wire_sweep.py",
    "scripts/integrity_megahunt_and_corpus_v14.py",
    "scripts/integrity_mole_hof_and_rl_audit.py",
    "scripts/integrity_sidechannel_and_text_sweep.py",
    "scripts/integrity_submit2_rehearsal_and_freeze_audit.py",
    "scripts/integrity_sweep_v14_fuzz.py",
    "scripts/integrity_v14_v15_differential_sweep.py",
    "scripts/integrity_v15_social_sweep.py",
    "scripts/integrity_verda_and_frontier_provenance.py",
    "scripts/judge_15min_whitebox_hunt.py",
    "scripts/verify_integrity_branch.py",
    "tests/test_gemini_mcp_hunter.py",
    "tests/test_harbor_sidecar_key_audit.py",
    "tests/test_integrity_cost_and_trajectory_boundary_sweep.py",
    "tests/test_integrity_cross_squad_security_gate.py",
    "tests/test_integrity_expert_tier_audit.py",
    "tests/test_integrity_final_make_hunt_v14.py",
    "tests/test_integrity_game_and_gateway_audit.py",
    "tests/test_integrity_gpt55_and_rehearsal_audit.py",
    "tests/test_integrity_heuristic_evolution_v14.py",
    "tests/test_integrity_hunter_sandbox_and_stub_sweep.py",
    "tests/test_integrity_mcp_wire_sweep.py",
    "tests/test_integrity_megahunt_and_corpus_v14.py",
    "tests/test_integrity_mole_hof_and_rl_audit.py",
    "tests/test_integrity_replays_and_harbor.py",
    "tests/test_integrity_sidechannel_and_text_sweep.py",
    "tests/test_integrity_submit2_rehearsal_and_freeze_audit.py",
    "tests/test_integrity_v14_fuzz_sweep.py",
    "tests/test_integrity_v14_v15_differential_sweep.py",
    "tests/test_integrity_v15_social_sweep.py",
    "tests/test_integrity_verda_and_frontier_provenance.py",
    "tests/test_judge_15min_whitebox_hunt.py",
    "tests/test_rehearsal_table_reruns.py",
    "tests/test_replay_tamper_guard.py",
    "tests/test_verify_integrity_branch.py",
)

UPSTREAM_MODIFIED_DIFF_ONLY_FILES: tuple[str, ...] = (
    "scripts/rehearsal_table.py",
)

UPSTREAM_REDTEAM_FILES: frozenset[str] = frozenset(
    {
        "canary/redteam/__init__.py",
        "canary/redteam/anticheat.py",
        "canary/redteam/corpus.py",
        "canary/redteam/encodings.py",
        "canary/redteam/fake_mcp.py",
        "canary/redteam/fuzz.py",
        "canary/redteam/harbor_cheat.py",
        "canary/redteam/hunter.py",
        "canary/redteam/mcp_client.py",
        "canary/redteam/monotonicity.py",
        "canary/redteam/seed_attack.py",
        "canary/redteam/swarm_probes.py",
        "canary/redteam/text_probe.py",
    }
)

FORBIDDEN_LLM_IMPORT_PREFIXES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "litellm",
    "google.genai",
    "google.generativeai",
    "canary.llm.openai_client",
    "canary.llm.gemini_client",
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + "s"
            + "k-"
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{20,}"
        ),
    ),
    ("hf_token", re.compile(r"(?<![0-9A-Za-z_])" + "hf" + "_" + r"[0-9A-Za-z]{24,}")),
    ("github_token", re.compile(r"(?<![0-9A-Za-z_])(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}")),
    ("aws_access_key", re.compile(r"(?<![0-9A-Z])" + "AK" + "IA" + r"[0-9A-Z]{16}(?![0-9A-Z])")),
    ("private_key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

SECRET_PREFIX_HINTS: dict[str, tuple[str, ...]] = {
    "google_api_key": ("AI" + "za",),
    "sk_api_key": ("s" + "k-",),
    "hf_token": ("hf" + "_",),
    "github_token": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"),
    "aws_access_key": ("AK" + "IA",),
    "private_key": ("PRIVATE KEY",),
}

AST_ZERO_API_HINTS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "litellm",
    "genai",
    "generativeai",
    "gemini_client",
    "get_client",
)

_STEPS_KEY_BYTES = b'"steps":'
_STEPS_TAIL_MARKERS: tuple[bytes, ...] = (
    b'], "score":',
    b'],"score":',
    b'], "tier":',
    b'],"tier":',
)

REQUIRED_LEDGER_TOKENS: tuple[str, ...] = (
    "58716742",
    "1bc3e281",
    "5f9b3297",
    "668a196b",
    "0f81e5a7",
    "65% [24%, 98%]",
    "72% [52%, 91%]",
    "post-hoc lock",
    "locked after the primary run",
    "never binds",
    "docs/EXPLOITS.md",
    "docs/reports/integrity.md",
    "docs/reports/harbor_sidecar_key_proposal.md",
    "docs/reports/integrity_cost_and_trajectory_boundary_sweep.md",
    "docs/reports/integrity_cross_squad_security_gate.md",
    "docs/reports/integrity_expert_tier_audit.md",
    "docs/reports/integrity_final_make_hunt_v14.md",
    "docs/reports/integrity_game_and_gateway_audit.md",
    "docs/reports/integrity_gpt55_and_rehearsal_audit.md",
    "docs/reports/integrity_heuristic_evolution_v14.md",
    "docs/reports/integrity_hunter_sandbox_and_stub_sweep.md",
    "docs/reports/integrity_mcp_wire_sweep.md",
    "docs/reports/integrity_megahunt_and_corpus_v14.md",
    "docs/reports/integrity_mole_hof_and_rl_audit.md",
    "docs/reports/integrity_offline_mcp_hunter_sweep.md",
    "docs/reports/integrity_replays_and_harbor.md",
    "docs/reports/integrity_sidechannel_and_text_sweep.md",
    "docs/reports/integrity_submit2_rehearsal_and_freeze_audit.md",
    "docs/reports/integrity_v14_fuzz_sweep.md",
    "docs/reports/integrity_v14_v15_differential_sweep.md",
    "docs/reports/integrity_v15_social_sweep.md",
    "docs/reports/integrity_verda_and_frontier_provenance.md",
    "docs/reports/judge_15min_hunt.md",
    "canary/gemini/lab_replay.py",
    "replay-ladder-showcase",
    "7cb16dc",
    "_bad",
    "ISSUE-W1-HARD-RL-DEPTS",
    "ISSUE-W1-TEXTPROBE-TRACKS",
    "ISSUE-W1B-1",
    "ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP",
    "ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER",
    "ISSUE-W6-ARENA-LLM-MOLE-SURFACE",
    "ISSUE-W7-1",
    "ISSUE-W8-S2-1",
    "ISSUE-W9B-01",
    "ISS-V15-01",
    "ISS-V15-02",
    "ISS-V15-03",
    "ISS-V15-04",
    "ISS-V15-05",
    "ISS-DIFF-03",
    "ISS-COST-01",
    "ISS-HUNTER-01",
    "EXP-BUG-01",
    "EXP-BUG-02",
    "EXP-BUG-03",
    "EXP-BUG-04",
    "EXP-BUG-05",
)

REQUIRED_LEDGER_IDS: tuple[str, ...] = tuple(f"INT-LEDGER-{i:02d}" for i in range(1, 26))

PREREG_PATTERN = re.compile(r"\bpre-?regist\w*", re.IGNORECASE)
PREREG_NEGATED_PATTERN = re.compile(
    r"\b(?:not|never|no|without|non)\s+(?:a\s+|an\s+|being\s+)?pre-?regist\w*|\bnon-pre-?regist\w*",
    re.IGNORECASE,
)
PREREG_ALLOWED_CONTEXT_PATTERN = re.compile(
    r"\b(?:cf394894|gpt-5\.5|rehearsal)\b",
    re.IGNORECASE,
)


def _git_lines(root: Path, args: Sequence[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _git_ref_exists(root: Path, ref: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def resolve_base_ref(root: Path, base_ref: str = "origin/justSilas") -> tuple[str | None, bool]:
    candidates: list[str] = [base_ref]
    if base_ref == "origin/justSilas":
        candidates.append("justSilas")
    elif base_ref == "justSilas":
        candidates.append("origin/justSilas")
    for cand in candidates:
        if _git_ref_exists(root, cand):
            return cand, False
    if base_ref in ("origin/justSilas", "justSilas") and _git_ref_exists(root, "HEAD"):
        return "HEAD", True
    return None, True


def _should_forbid_untracked_workspace_dirs(root: Path) -> bool:
    resolved_str = root.resolve().as_posix()
    if resolved_str.startswith("/tmp/fleet-silas/"):
        return True
    if not (root / "Makefile").is_file() and not (root / "pyproject.toml").is_file():
        return True
    return False


def load_protected_rules(root: Path) -> list[str]:
    rules: list[str] = list(MANDATORY_PROTECTED_RULES)
    pf = root / ".github" / "protected-paths.txt"
    if pf.is_file():
        for raw in pf.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(HASH_CHAR):
                continue
            if line not in rules:
                rules.append(line)
    return rules


def is_protected_path(rel_path: str, rules: Sequence[str]) -> str | None:
    norm = rel_path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    for rule in rules:
        if rule.endswith("/"):
            if norm.startswith(rule) or norm == rule.rstrip("/"):
                return rule
        elif norm == rule:
            return rule
    return None


def is_integrity_squad_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in UPSTREAM_REDTEAM_FILES:
        return False
    if norm in KNOWN_SQUAD_OWNED_FILES or norm in UPSTREAM_MODIFIED_DIFF_ONLY_FILES:
        return True
    if norm.startswith("canary/redteam/"):
        return True
    name_low = Path(norm).name.lower()
    if norm.startswith(("scripts/", "docs/reports/", "docs/arena/", "tests/")) and (
        "integrity" in name_low
        or "whitebox_hunt" in name_low
        or "tamper_guard" in name_low
        or "harbor_sidecar" in name_low
        or "mcp_hunter" in name_low
    ):
        return True
    return False


def collect_branch_changes(
    root: Path,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
) -> dict[str, str]:
    changes: dict[str, str] = {}
    resolved_ref, _ = resolve_base_ref(root, base_ref)
    if resolved_ref is not None and resolved_ref != "HEAD":
        for line in _git_lines(root, ["diff", "--name-status", f"{resolved_ref}...HEAD"]):
            parts = line.split("\t")
            status = parts[0].strip()
            if status.startswith("R") and len(parts) >= 3:
                changes[parts[1].strip()] = "D"
                changes[parts[2].strip()] = "A"
            elif len(parts) >= 2:
                changes[parts[1].strip()] = status[0]
    if include_worktree:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            for raw in proc.stdout.splitlines():
                if len(raw) < 4:
                    continue
                xy = raw[:2]
                target = raw[3:].strip()
                if " -> " in target:
                    target = target.split(" -> ", 1)[1].strip()
                if xy == "??":
                    changes.setdefault(target, "A")
                elif "D" in xy:
                    changes[target] = "D"
                else:
                    changes.setdefault(target, "M")
    return changes


def _added_diff_lines(root: Path, rel_path: str, base_ref: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    resolved_ref, _ = resolve_base_ref(root, base_ref)
    diff_specs: list[list[str]] = []
    if resolved_ref is not None and resolved_ref != "HEAD":
        diff_specs.append(["diff", "-U0", f"{resolved_ref}...HEAD", "--", rel_path])
    diff_specs.append(["diff", "-U0", "HEAD", "--", rel_path])
    for diff_args in diff_specs:
        proc = subprocess.run(
            ["git", *diff_args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            continue
        cur_line = 0
        for raw in proc.stdout.splitlines():
            if raw.startswith("@@"):
                m = re.search(r"\+(\d+)", raw)
                cur_line = int(m.group(1)) if m else 0
            elif raw.startswith("+") and not raw.startswith("+++"):
                out.append((cur_line, raw[1:]))
                cur_line += 1
    return out


def scan_python_comments(source: str) -> list[tuple[int, str]]:
    if HASH_CHAR not in source:
        return []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [(tok.start[0], tok.string) for tok in tokens if tok.type == tokenize.COMMENT]


def scan_text_hygiene(text: str, rel_path: str) -> list[str]:
    issues: list[str] = []
    if EM_DASH in text:
        issues.append(f"{rel_path}: contains em dash ({text.count(EM_DASH)} occurrence(s))")
    if EN_DASH in text:
        issues.append(f"{rel_path}: contains en dash ({text.count(EN_DASH)} occurrence(s))")
    if CO_AUTHOR_LOWER in text.lower():
        issues.append(f"{rel_path}: contains {'Co-Authored' + '-By'} line")
    for name, pat in SECRET_PATTERNS:
        hints = SECRET_PREFIX_HINTS.get(name, ())
        if hints and not any(h in text for h in hints):
            continue
        m = pat.search(text)
        if m is not None:
            issues.append(f"{rel_path}: matched secret pattern {name}")
    return issues


def scan_markdown_honesty(text: str, rel_path: str) -> list[str]:
    issues: list[str] = []
    for m in PREREG_PATTERN.finditer(text):
        win_start = max(0, m.start() - 100)
        win_end = min(len(text), m.end() + 100)
        window = text[win_start:win_end]
        if PREREG_NEGATED_PATTERN.search(window) is None and PREREG_ALLOWED_CONTEXT_PATTERN.search(window) is None:
            issues.append(f"{rel_path}: unnegated pre-registration claim near offset {m.start()}")
    if "72%" in text:
        idx_72 = text.find("72%")
        idx_65 = text.find("65%")
        if idx_65 == -1 or idx_65 > idx_72:
            issues.append(f"{rel_path}: cites luck-adjusted 72% without leading raw 65% first")
    return issues


def gate_1_protected_paths(
    root: Path,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
    changes: dict[str, str] | None = None,
) -> dict[str, Any]:
    rules = load_protected_rules(root)
    if changes is None:
        changes = collect_branch_changes(root, base_ref=base_ref, include_worktree=include_worktree)
    violations: list[str] = []

    for rel_path, st in sorted(changes.items()):
        matched = is_protected_path(rel_path, rules)
        if matched is not None:
            violations.append(f"protected path touched ({st}): {rel_path} (rule {matched})")
        lower_rel = rel_path.lower()
        for bad_suf in FORBIDDEN_BINARY_SUFFIXES:
            if lower_rel.endswith(bad_suf) and st != "D":
                violations.append(f"forbidden weight/binary artifact ({st}): {rel_path}")
        full = root / rel_path
        if st != "D" and full.is_file() and is_integrity_squad_path(rel_path):
            sz = full.stat().st_size
            if rel_path in W9_OWNED_FILES and sz > MAX_W9_FILE_BYTES:
                violations.append(f"{rel_path}: W9 file size {sz} bytes exceeds {MAX_W9_FILE_BYTES} bytes")
            elif sz > MAX_SQUAD_FILE_BYTES:
                violations.append(f"{rel_path}: file size {sz} bytes exceeds {MAX_SQUAD_FILE_BYTES} bytes")

    for w9_rel in W9_OWNED_FILES:
        w9_full = root / w9_rel
        if w9_full.is_file():
            sz = w9_full.stat().st_size
            if sz > MAX_W9_FILE_BYTES and not any(v.startswith(f"{w9_rel}:") for v in violations):
                violations.append(f"{w9_rel}: W9 file size {sz} bytes exceeds {MAX_W9_FILE_BYTES} bytes")

    tracked_forbidden = _git_lines(root, ["ls-files", "--", *FORBIDDEN_WORKSPACE_DIRS])
    for forbidden_dir in FORBIDDEN_WORKSPACE_DIRS:
        has_tracked = any(
            p == forbidden_dir or p.startswith(f"{forbidden_dir}/") for p in tracked_forbidden
        ) or any(
            (p == forbidden_dir or p.startswith(f"{forbidden_dir}/")) and st != "D"
            for p, st in changes.items()
        )
        if has_tracked:
            violations.append(f"forbidden tracked workspace directory: {forbidden_dir}")
        elif _should_forbid_untracked_workspace_dirs(root) and (root / forbidden_dir).exists():
            violations.append(f"forbidden workspace directory present: {forbidden_dir}")

    if (root / "data" / "worlds" / "judge" / "SALT").exists():
        violations.append("data/worlds/judge/SALT must never exist in checkout")

    return {
        "name": "Gate 1: Protected Paths, SALT Absence, and Disk Hygiene",
        "passed": len(violations) == 0,
        "protected_rules_count": len(rules),
        "changed_files_count": len(changes),
        "protected_touched_count": sum(1 for v in violations if v.startswith("protected path touched")),
        "violations": violations,
    }


def gate_2_squad_hygiene(
    root: Path,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
    changes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if changes is None:
        changes = collect_branch_changes(root, base_ref=base_ref, include_worktree=include_worktree)
    violations: list[str] = []

    full_check_paths: set[str] = set()
    diff_only_paths: set[str] = set()

    for rel_path in KNOWN_SQUAD_OWNED_FILES:
        if (root / rel_path).is_file():
            full_check_paths.add(rel_path)

    for rel_path, st in changes.items():
        if st == "D":
            continue
        if not is_integrity_squad_path(rel_path):
            continue
        if not (root / rel_path).is_file():
            continue
        if rel_path in UPSTREAM_MODIFIED_DIFF_ONLY_FILES or (st == "M" and rel_path not in KNOWN_SQUAD_OWNED_FILES):
            diff_only_paths.add(rel_path)
        else:
            full_check_paths.add(rel_path)

    py_checked = 0
    md_checked = 0
    total_comments = 0
    total_dashes = 0

    for rel_path in sorted(full_check_paths):
        path = root / rel_path
        text = path.read_text(encoding="utf-8")
        dash_hits = text.count(EM_DASH) + text.count(EN_DASH)
        total_dashes += dash_hits
        violations.extend(scan_text_hygiene(text, rel_path))
        if rel_path.endswith(".py"):
            py_checked += 1
            try:
                comments = scan_python_comments(text)
            except tokenize.TokenError as exc:
                violations.append(f"{rel_path}: tokenize error ({exc})")
            else:
                total_comments += len(comments)
                if comments:
                    line_no, sample = comments[0]
                    violations.append(
                        f"{rel_path}: {len(comments)} Python comment token(s) found (first at line {line_no}: {sample[:40]!r})"
                    )
        elif rel_path.endswith(".md"):
            md_checked += 1

    for rel_path in sorted(diff_only_paths):
        path = root / rel_path
        text = path.read_text(encoding="utf-8")
        if rel_path.endswith(".py"):
            py_checked += 1
            try:
                comments = scan_python_comments(text)
            except tokenize.TokenError as exc:
                violations.append(f"{rel_path}: tokenize error ({exc})")
            else:
                total_comments += len(comments)
                if comments:
                    line_no, sample = comments[0]
                    violations.append(
                        f"{rel_path}: {len(comments)} Python comment token(s) found (first at line {line_no}: {sample[:40]!r})"
                    )
        added = _added_diff_lines(root, rel_path, base_ref=base_ref)
        for line_no, line_txt in added:
            if EM_DASH in line_txt or EN_DASH in line_txt:
                total_dashes += line_txt.count(EM_DASH) + line_txt.count(EN_DASH)
                violations.append(f"{rel_path}:{line_no}: added diff line contains em/en dash")
            if CO_AUTHOR_LOWER in line_txt.lower():
                violations.append(f"{rel_path}:{line_no}: added diff line contains {'Co-Authored' + '-By'}")
            for sname, spat in SECRET_PATTERNS:
                hints = SECRET_PREFIX_HINTS.get(sname, ())
                if hints and not any(h in line_txt for h in hints):
                    continue
                if spat.search(line_txt) is not None:
                    violations.append(f"{rel_path}:{line_no}: added diff line matched secret pattern {sname}")

    coauthor_commits: list[str] = []
    scoped_paths = sorted(full_check_paths | diff_only_paths)
    resolved_ref, _ = resolve_base_ref(root, base_ref)
    if resolved_ref is not None and resolved_ref != "HEAD":
        log_cmd = ["git", "log", "--format=%h%x09%B", f"{resolved_ref}..HEAD"]
        if scoped_paths:
            log_cmd.extend(["--", *scoped_paths])
        proc = subprocess.run(
            log_cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            for chunk in proc.stdout.split("\n\n"):
                if CO_AUTHOR_LOWER in chunk.lower():
                    sha = chunk.strip().split("\t", 1)[0]
                    coauthor_commits.append(sha)
                    violations.append(f"commit {sha}: commit message contains {'Co-Authored' + '-By'}")

    return {
        "name": "Gate 2: Squad Python/Markdown/Commit/Secret Hygiene",
        "passed": len(violations) == 0,
        "full_files_checked": len(full_check_paths),
        "diff_only_files_checked": len(diff_only_paths),
        "python_files_checked": py_checked,
        "markdown_files_checked": md_checked,
        "python_comment_tokens": total_comments,
        "em_en_dash_count": total_dashes,
        "co_authored_by_commits": len(coauthor_commits),
        "violations": violations,
    }


def _scan_ast_zero_api_with_tree(source: str, rel_path: str) -> tuple[list[str], ast.Module | None]:
    issues: list[str] = []
    needs_hunter_defs = rel_path == "canary/redteam/gemini_mcp_hunter.py"
    has_api_hints = (not source.isascii()) or any(hint in source for hint in AST_ZERO_API_HINTS)
    if not needs_hunter_defs and not has_api_hints and len(source) > 8192:
        return issues, None
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return [f"{rel_path}: SyntaxError ({exc})"], None

    if not has_api_hints:
        return issues, tree

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if any(mod == p or mod.startswith(p + ".") for p in FORBIDDEN_LLM_IMPORT_PREFIXES):
                    issues.append(f"{rel_path}:{node.lineno}: forbidden live LLM SDK import {mod!r}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            candidates = [mod] + [f"{mod}.{alias.name}" if mod else alias.name for alias in node.names]
            for cand in candidates:
                if any(cand == p or cand.startswith(p + ".") for p in FORBIDDEN_LLM_IMPORT_PREFIXES):
                    issues.append(f"{rel_path}:{node.lineno}: forbidden live LLM SDK import from {cand!r}")
        elif isinstance(node, ast.Call):
            fn = node.func
            fn_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if fn_name == "get_client" and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    spec = arg0.value.strip().lower()
                    if not spec.startswith("stub"):
                        issues.append(f"{rel_path}:{node.lineno}: live get_client({arg0.value!r}) call")
    return issues, tree


def scan_ast_zero_api(source: str, rel_path: str) -> list[str]:
    issues, _ = _scan_ast_zero_api_with_tree(source, rel_path)
    return issues


def gate_3_zero_api_and_ast_safety(
    root: Path,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
    changes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if changes is None:
        changes = collect_branch_changes(root, base_ref=base_ref, include_worktree=include_worktree)
    py_targets: set[str] = {p for p in KNOWN_SQUAD_OWNED_FILES if p.endswith(".py") and (root / p).is_file()}
    for rel_path, st in changes.items():
        if st != "D" and rel_path.endswith(".py") and is_integrity_squad_path(rel_path) and (root / rel_path).is_file():
            py_targets.add(rel_path)

    violations: list[str] = []
    hunter_defs: set[str] = set()
    for rel_path in sorted(py_targets):
        src = (root / rel_path).read_text(encoding="utf-8")
        issues, tree = _scan_ast_zero_api_with_tree(src, rel_path)
        violations.extend(issues)
        if rel_path == "canary/redteam/gemini_mcp_hunter.py" and tree is not None:
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    hunter_defs.add(node.name)

    required_hunter_defs = {"LiveLLMBlockedError", "loopback_only_network_guard", "make_llm_client"}
    hunter_guard_ok = required_hunter_defs.issubset(hunter_defs)
    if (root / "canary" / "redteam" / "gemini_mcp_hunter.py").is_file() and not hunter_guard_ok:
        violations.append(
            f"canary/redteam/gemini_mcp_hunter.py: missing offline guard defs {sorted(required_hunter_defs - hunter_defs)}"
        )

    return {
        "name": "Gate 3: Zero-API AST Lock and Offline Hunter Guard",
        "passed": len(violations) == 0,
        "python_ast_files_checked": len(py_targets),
        "hunter_live_llm_blocked": hunter_guard_ok,
        "violations": violations,
    }


def C3_exploits_md_citations(root: Path) -> dict[str, Any]:
    exploits_rel = "docs/EXPLOITS.md"
    exploits_path = root / exploits_rel
    violations: list[str] = []
    if not exploits_path.is_file():
        return {
            "name": "C3_exploits_md_citations",
            "passed": False,
            "variant": "missing",
            "violations": [f"{exploits_rel}: missing upstream exploit ledger"],
        }

    txt = exploits_path.read_text(encoding="utf-8")
    iso_31_ok = "all 31 committed Harbor trials" in txt or "31 of 31 committed Harbor trials" in txt
    iso_61_ok = "all 61 committed Harbor trials" in txt or "61 of 61 committed Harbor trials" in txt
    pre_refresh_ok = "989 of 999" in txt and "49,549" in txt and iso_31_ok
    post_craft_refresh_ok = "1,021 of 1,031" in txt and "51,814" in txt and iso_61_ok
    post_gpt55_refresh_ok = ("1,051 of 1,061" in txt or "1051 of 1061" in txt) and (
        "53,889" in txt or "53889" in txt
    ) and (iso_61_ok or iso_31_ok)

    if post_gpt55_refresh_ok:
        variant = "post_gpt55_refresh"
    elif post_craft_refresh_ok:
        variant = "post_craft_refresh"
    elif pre_refresh_ok:
        variant = "pre_refresh"
    else:
        variant = "mismatch"
        violations.append(
            f"{exploits_rel}: expected pre-refresh (989 of 999 / 49,549 / 31 isolation trials), "
            "post-Craft-refresh (1,021 of 1,031 / 51,814 / 61 isolation trials), "
            "or post-gpt55-refresh (1,051 of 1,061 / 53,889)"
        )

    for anchor in (
        "80 of 80 trials and 18 of 18 job summaries consistent",
        "0.000, 0 invariant violations",
        "1,161 runs",
        "12 of 12 held",
    ):
        if anchor not in txt:
            violations.append(f"{exploits_rel}: missing citation anchor {anchor!r}")

    return {
        "name": "C3_exploits_md_citations",
        "passed": len(violations) == 0,
        "variant": variant,
        "violations": violations,
    }


def gate_4_panel_honesty_and_ledger_sync(
    root: Path,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
    changes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if changes is None:
        changes = collect_branch_changes(root, base_ref=base_ref, include_worktree=include_worktree)
    md_targets: set[str] = {p for p in KNOWN_SQUAD_OWNED_FILES if p.endswith(".md") and (root / p).is_file()}
    for rel_path, st in changes.items():
        if st != "D" and rel_path.endswith(".md") and is_integrity_squad_path(rel_path) and (root / rel_path).is_file():
            md_targets.add(rel_path)

    violations: list[str] = []
    for rel_path in sorted(md_targets):
        txt = (root / rel_path).read_text(encoding="utf-8")
        violations.extend(scan_markdown_honesty(txt, rel_path))

    c3_res: dict[str, Any] | None = None
    if (root / "docs" / "EXPLOITS.md").is_file() or (root / "canary" / "env.py").is_file():
        c3_res = C3_exploits_md_citations(root)
        violations.extend(c3_res["violations"])

    ledger_rel = "docs/reports/integrity_issue_ledger.md"
    ledger_path = root / ledger_rel
    missing_tokens: list[str] = []
    missing_ids: list[str] = []
    if not ledger_path.is_file():
        violations.append(f"{ledger_rel}: missing master integrity issue ledger")
    else:
        ledger_txt = ledger_path.read_text(encoding="utf-8")
        ledger_low = ledger_txt.lower()
        if "pre-reg" in ledger_low or "prereg" in ledger_low:
            violations.append(f"{ledger_rel}: contains forbidden pre-reg/prereg substring")
        for tok in REQUIRED_LEDGER_TOKENS:
            if tok not in ledger_txt:
                missing_tokens.append(tok)
                violations.append(f"{ledger_rel}: missing required token {tok!r}")
        for lid in REQUIRED_LEDGER_IDS:
            if lid not in ledger_txt:
                missing_ids.append(lid)
                violations.append(f"{ledger_rel}: missing issue ID {lid}")

    return {
        "name": "Gate 4: Panel Fix A/D Honesty, EXPLOITS.md Citations, and Master Ledger Sync",
        "passed": len(violations) == 0,
        "markdown_reports_checked": len(md_targets),
        "c3_exploits_md_citations": c3_res,
        "ledger_ids_verified": len(REQUIRED_LEDGER_IDS) - len(missing_ids),
        "ledger_tokens_verified": len(REQUIRED_LEDGER_TOKENS) - len(missing_tokens),
        "violations": violations,
    }


def _normalize_emp_detail(detail: str, emp_id: str) -> str:
    return re.sub(rf"\b{re.escape(emp_id)}\b", "<emp>", detail)


def gate_5_env_and_detail_invariants(root: Path) -> dict[str, Any]:
    from canary.env import ERRORS, Env
    from canary.redteam.harbor_sidecar_audit import (
        audit_harbor_sidecar_key_gating,
        gemini_api_key_compose_line,
    )
    from canary.redteam.seed_attack import public_world
    from canary.rules import TIERS_VERSION

    violations: list[str] = []
    if TIERS_VERSION != "v1.4":
        violations.append(f"expected TIERS_VERSION == 'v1.4', got {TIERS_VERSION!r}")

    env_judge = Env("hard", 900000)
    pub_judge = public_world("hard", 900000)
    judge_rost = [(e.id, e.name, e.dept) for e in env_judge._world.employees]
    pub_rost = [(e.id, e.name, e.dept) for e in pub_judge.employees]
    if judge_rost == pub_rost:
        violations.append("judge seed 900000 matched public_world roster without secret")

    parity_checks = 0
    for tier in ("easy", "medium", "hard"):
        env = Env(tier, 3000)
        mole_id = env._world.mole
        decoy_id = env._world.decoy
        innocent_id = next(
            e.id for e in env._world.employees if e.id != mole_id and e.id != decoy_id
        )
        probe_targets = [mole_id, innocent_id] + ([decoy_id] if decoy_id else [])
        call_specs = (
            ("interview", lambda eid: {"employee": eid, "topic": "invalid_topic"}),
            ("unrestrict_access", lambda eid: {"employee": eid}),
            ("accuse", lambda eid: {"employee": eid, "extra_key": 1}),
            ("plant_canary", lambda eid: {"doc_title": "probe", "variants": {"": [eid]}}),
        )
        for tool_name, arg_fn in call_specs:
            templates: set[str] = set()
            for target_id in probe_targets:
                v_before = round(env.V, 10)
                vis_before = env.visible_V()
                res = env.call(tool_name, arg_fn(target_id))
                parity_checks += 1
                if res.ok is not False:
                    violations.append(f"{tier}:{tool_name} invalid call unexpectedly succeeded")
                if res.error != "invalid arguments" or res.error not in ERRORS:
                    violations.append(f"{tier}:{tool_name} unexpected error {res.error!r}")
                if not isinstance(res.data, dict) or set(res.data.keys()) != {"detail"}:
                    violations.append(f"{tier}:{tool_name} missing 1bc3e281 data.detail shape")
                else:
                    detail = str(res.data["detail"])
                    templates.add(_normalize_emp_detail(detail, target_id))
                    if "mole" in detail.lower() or str(env._world.world_seed) in detail:
                        violations.append(f"{tier}:{tool_name} leaked truth or world_seed in detail")
                if round(env.V, 10) > v_before or env.visible_V() > vis_before:
                    violations.append(f"{tier}:{tool_name} caused V or visible_V to rise")
            if len(templates) != 1:
                violations.append(f"{tier}:{tool_name} mole/decoy/innocent detail non-parity: {templates}")

    if gemini_api_key_compose_line("template") != "":
        violations.append("gemini_api_key_compose_line('template') must return empty string")
    sidecar_res = audit_harbor_sidecar_key_gating(root)
    if not sidecar_res.get("simulation_passed"):
        violations.append("harbor_sidecar_audit simulation did not pass")

    return {
        "name": "Gate 5: v1.4 Env, 1bc3e281 Detail Role Parity, and Sidecar Key Audit",
        "passed": len(violations) == 0,
        "tiers_version": TIERS_VERSION,
        "detail_parity_checks": parity_checks,
        "sidecar_simulation_passed": bool(sidecar_res.get("simulation_passed")),
        "violations": violations,
    }


def is_valid_opencode_clean_stop(ep: dict[str, Any]) -> bool:
    raw_score = ep.get("score")
    if not (isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) and math.isfinite(float(raw_score))):
        return False
    ep_meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    return (
        ep_meta.get("rc") == 0
        and ep.get("accused") is None
        and float(raw_score) == 0.0
        and not bool(ep.get("correct"))
        and str(ep_meta.get("note") or "").startswith("agent stopped without ending the episode")
    )


def _parse_episode_header_bytes(raw_line: bytes) -> Any:
    s = raw_line.strip()
    idx = s.find(_STEPS_KEY_BYTES)
    if idx != -1:
        for marker in _STEPS_TAIL_MARKERS:
            end_idx = s.rfind(marker)
            if end_idx > idx:
                try:
                    return json.loads(s[:idx] + b'"steps":[]' + s[end_idx + 1 :])
                except ValueError:
                    break
    return json.loads(s)


def verify_committed_episode_outcomes(root: Path, unit_fast: bool = False) -> dict[str, Any]:
    from canary import reproduce as R
    from canary.env import Env
    from canary.redteam import anticheat as ac

    committed_root = root / "data" / "runs" / "committed"
    if not committed_root.is_dir():
        return {
            "passed": True,
            "files_checked": 0,
            "episodes_checked": 0,
            "valid_agent_stopped_episodes": 0,
            "gpt55_replayed_episodes": 0,
            "violations": [],
        }

    files = R.committed_files(root)
    violations: list[str] = []
    episodes_checked = 0
    valid_agent_stopped = 0

    for fpath in files:
        rel = fpath.relative_to(root).as_posix()
        for lineno, raw_line in enumerate(fpath.read_bytes().splitlines(), 1):
            if not raw_line.strip():
                continue
            loc = f"{rel}:{lineno}"
            try:
                ep = _parse_episode_header_bytes(raw_line)
            except ValueError as exc:
                violations.append(f"{loc}: invalid JSON ({exc})")
                continue
            if not isinstance(ep, dict):
                violations.append(f"{loc}: episode record must be a JSON object")
                continue

            episodes_checked += 1
            raw_score = ep.get("score")
            if not (isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) and math.isfinite(float(raw_score))):
                violations.append(f"{loc}: non-finite score {raw_score!r}")
                continue
            score = float(raw_score)
            if not (-1.0 <= score <= 1.0):
                violations.append(f"{loc}: score {score} outside [-1.0, 1.0]")

            ep_meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            is_invalid = (ep_meta.get("valid") is False) or (ep.get("valid") is False)
            if is_invalid:
                continue

            accused = ep.get("accused")
            has_accused = isinstance(accused, str) and bool(accused.strip())
            if accused is not None and not has_accused:
                violations.append(f"{loc}: invalid accused field {accused!r}")
            correct = bool(ep.get("correct"))
            if score > 0.0 and not (has_accused and correct):
                violations.append(f"{loc}: positive score {score} without valid correct accusation")
            if not has_accused and (score != 0.0 or correct):
                violations.append(f"{loc}: unaccused episode must have score=0.0 and correct=False")
            if has_accused and not correct and score != -1.0:
                violations.append(f"{loc}: wrong accusation must have score=-1.0, got {score}")

            agent_stopped = is_valid_opencode_clean_stop(ep)
            killed_stop = (
                ep.get("end_reason") == "error"
                and accused is None
                and score == 0.0
                and not correct
                and str(ep_meta.get("note") or "").startswith("agent_killed_server:")
            )
            if agent_stopped:
                valid_agent_stopped += 1
            if ep_meta.get("rc") == "timeout":
                violations.append(f"{loc}: timeout episode missing meta.valid=False")
            elif ep.get("end_reason") == "error" and not (agent_stopped or killed_stop):
                violations.append(
                    f"{loc}: end_reason='error' with rc={ep_meta.get('rc')!r} without meta.valid=False or valid clean stop"
                )

    gpt55_replayed = 0
    gpt55_path = committed_root / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    if gpt55_path.is_file():
        for lineno, raw_line in enumerate(gpt55_path.read_bytes().splitlines(), 1):
            if not raw_line.strip():
                continue
            if unit_fast and gpt55_replayed >= 2:
                ep_hdr = _parse_episode_header_bytes(raw_line)
                if not isinstance(ep_hdr, dict) or ep_hdr.get("tier") != "hard":
                    violations.append(f"opencode-gpt-5.5 line {lineno}: invalid header")
                gpt55_replayed += 1
                continue
            ep = json.loads(raw_line)
            env = Env(str(ep["tier"]), int(ep["seed"]))
            step_bad = 0
            for st in ep.get("steps", []):
                if ac._client_only_step(st):
                    continue
                res = env.call(st["tool"], st["args"])
                got_payload = {"ok": res.ok, "data": res.data, "error": res.error}
                rec = ac._norm_result(st.get("result"))
                if (
                    not res.ok
                    and isinstance(res.data, dict)
                    and set(res.data) == {"detail"}
                    and not (isinstance(rec, dict) and isinstance(rec.get("data"), dict) and "detail" in rec["data"])
                ):
                    got_payload = {"ok": res.ok, "data": {}, "error": res.error}
                trunc = ac._client_truncated_bytes(st.get("result"))
                if trunc is not None:
                    ok_step = len(json.dumps(got_payload).encode("utf-8")) == trunc
                else:
                    ok_step = rec is None or got_payload == rec or ac._canon(got_payload) == ac._canon(rec)
                if not ok_step:
                    step_bad += 1
            gpt55_replayed += 1
            if step_bad or abs(env.score() - float(ep["score"])) > 1e-6 or env.verdict()["accused"] != ep.get("accused"):
                violations.append(
                    f"opencode-gpt-5.5 seed {ep.get('seed')}: replay mismatch (step_bad={step_bad})"
                )
        if gpt55_replayed < 30:
            violations.append(f"opencode-gpt-5.5 expected >= 30 episodes, got {gpt55_replayed}")

    return {
        "passed": len(violations) == 0,
        "files_checked": len(files),
        "episodes_checked": episodes_checked,
        "valid_agent_stopped_episodes": valid_agent_stopped,
        "gpt55_replayed_episodes": gpt55_replayed,
        "violations": violations,
    }


def gate_6_rehearsal_and_tamper_guard(root: Path, unit_fast: bool = False) -> dict[str, Any]:
    from canary.env import Env
    from canary.redteam import tamper_guard as tg

    violations: list[str] = []
    rehearsal_dir = root / "results" / "harbor" / "rehearsal-dry"
    table_matches = False
    sample_trials_checked = 0

    pre1bc_replay_ok = False
    tamper_caught_ok = False
    with tempfile.TemporaryDirectory(prefix="w9_tg_gate_") as tmp_s:
        tmp_root = Path(tmp_s)
        if not rehearsal_dir.is_dir():
            violations.append("results/harbor/rehearsal-dry directory missing")
        else:
            table_file = rehearsal_dir / "TABLE.md"
            fast_hash_ok = (
                unit_fast
                and table_file.is_file()
                and hashlib.sha256(table_file.read_bytes()).hexdigest()
                == "dcc64c7c81386848e0d27e6c1f2c447ef90607f5f96ae82ba0249f71ee973844"
            )
            if fast_hash_ok:
                table_matches = True
            else:
                rt_mod = tg._load_rehearsal_table_module(root)
                tmp_table_md = tmp_root / "TABLE.md"
                with contextlib.redirect_stdout(io.StringIO()):
                    rt_mod.main([str(rehearsal_dir), "--out", str(tmp_table_md)])
                got_table = tmp_table_md.read_text(encoding="utf-8")
                want_table = table_file.read_text(encoding="utf-8")
                table_matches = got_table == want_table
                if not table_matches:
                    violations.append("scripts/rehearsal_table.py output differed from results/harbor/rehearsal-dry/TABLE.md")

            rerun_issues = tg._check_rerun_job_pair(rehearsal_dir / "opencode-infra-rerun")
            if rerun_issues:
                violations.extend(f"rehearsal-dry rerun check: {msg}" for msg in rerun_issues)

            for job_name in ("oracle", "opencode", "opencode-infra-rerun"):
                trials = sorted((rehearsal_dir / job_name).glob("canary-*"))
                if not trials:
                    violations.append(f"rehearsal-dry/{job_name}: no trial directories found")
                    continue
                tr_res = tg.check_harbor_trial(trials[0])
                sample_trials_checked += 1
                if not tr_res.get("consistent"):
                    violations.append(f"rehearsal-dry/{job_name}/{trials[0].name}: inconsistent trial ({tr_res})")

        run_dir = tmp_root / "data" / "runs" / "committed" / "v1.4" / "synthetic-check" / "easy"
        run_dir.mkdir(parents=True, exist_ok=True)
        env = Env("easy", 0)
        r_bad = env.call("search_messages", {"query": " "})
        r_acc = env.call("accuse", {"employee": env._world.mole})
        ep_clean = {
            "tier": "easy",
            "seed": 0,
            "agent": "solver",
            "score": env.score(),
            "correct": True,
            "accused": env._world.mole,
            "end_reason": "accused",
            "final_day": env.day,
            "n_calls": 2,
            "meta": {"tiers_version": "v1.4", "valid": True, "V": env.V},
            "steps": [
                {
                    "tool": "search_messages",
                    "args": {"query": " "},
                    "result": {"ok": r_bad.ok, "data": {}, "error": r_bad.error},
                },
                {
                    "tool": "accuse",
                    "args": {"employee": env._world.mole},
                    "result": {"ok": r_acc.ok, "data": r_acc.data, "error": r_acc.error},
                },
            ],
        }
        ep_file = run_dir / "episodes.jsonl"
        ep_file.write_text(json.dumps(ep_clean) + "\n", encoding="utf-8")
        rows_clean = tg.replay_committed(root=tmp_root)
        pre1bc_replay_ok = (
            len(rows_clean) == 1
            and rows_clean[0].get("replay_consistent") is True
            and rows_clean[0].get("step_mismatches") == 0
        )
        if not pre1bc_replay_ok:
            violations.append(f"pre-1bc3e281 normalized step failed tamper_guard.replay_committed: {rows_clean}")

        ep_tampered = json.loads(json.dumps(ep_clean))
        ep_tampered["steps"][0]["result"] = None
        ep_file.write_text(json.dumps(ep_tampered) + "\n", encoding="utf-8")
        rows_tampered = tg.replay_committed(root=tmp_root)
        tamper_caught_ok = len(rows_tampered) == 1 and rows_tampered[0].get("replay_consistent") is False
        if not tamper_caught_ok:
            violations.append("tamper_guard.replay_committed failed to catch wiped null step result")

    outcomes_res = verify_committed_episode_outcomes(root, unit_fast=unit_fast)
    violations.extend(outcomes_res["violations"])

    return {
        "name": "Gate 6: Rehearsal Table Parity, Committed Outcomes, and Tamper-Guard Replay",
        "passed": len(violations) == 0,
        "rehearsal_table_byte_equal": table_matches,
        "sample_harbor_trials_checked": sample_trials_checked,
        "pre1bc_detail_normalization_ok": pre1bc_replay_ok,
        "null_step_tamper_caught": tamper_caught_ok,
        "committed_outcomes_ok": outcomes_res["passed"],
        "committed_files_checked": outcomes_res["files_checked"],
        "committed_episodes_checked": outcomes_res["episodes_checked"],
        "valid_agent_stopped_episodes": outcomes_res["valid_agent_stopped_episodes"],
        "gpt55_replayed_episodes": outcomes_res["gpt55_replayed_episodes"],
        "violations": violations,
    }


def run_all_gates(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
    include_worktree: bool = True,
    unit_fast: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    resolved = root.resolve()
    resolved_base_ref, shallow_fallback = resolve_base_ref(resolved, base_ref)
    shared_changes = collect_branch_changes(resolved, base_ref=base_ref, include_worktree=include_worktree)
    gates = {
        "gate_1_protected_paths": gate_1_protected_paths(
            resolved, base_ref=base_ref, include_worktree=include_worktree, changes=shared_changes
        ),
        "gate_2_squad_hygiene": gate_2_squad_hygiene(
            resolved, base_ref=base_ref, include_worktree=include_worktree, changes=shared_changes
        ),
        "gate_3_zero_api_and_ast_safety": gate_3_zero_api_and_ast_safety(
            resolved, base_ref=base_ref, include_worktree=include_worktree, changes=shared_changes
        ),
        "gate_4_panel_honesty_and_ledger_sync": gate_4_panel_honesty_and_ledger_sync(
            resolved, base_ref=base_ref, include_worktree=include_worktree, changes=shared_changes
        ),
        "gate_5_env_and_detail_invariants": gate_5_env_and_detail_invariants(resolved),
        "gate_6_rehearsal_and_tamper_guard": gate_6_rehearsal_and_tamper_guard(resolved, unit_fast=unit_fast),
    }
    passed_count = sum(1 for g in gates.values() if g["passed"])
    elapsed_s = round(time.perf_counter() - t0, 4)
    return {
        "all_passed": passed_count == len(gates),
        "gates_passed": passed_count,
        "gates_total": len(gates),
        "elapsed_s": elapsed_s,
        "base_ref": base_ref,
        "resolved_base_ref": resolved_base_ref,
        "shallow_checkout_fallback": shallow_fallback,
        "live_llm_calls": 0,
        "c3_exploits_md_citations": gates["gate_4_panel_honesty_and_ledger_sync"].get("c3_exploits_md_citations"),
        "gates": gates,
    }


def format_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in (
        "gate_1_protected_paths",
        "gate_2_squad_hygiene",
        "gate_3_zero_api_and_ast_safety",
        "gate_4_panel_honesty_and_ledger_sync",
        "gate_5_env_and_detail_invariants",
        "gate_6_rehearsal_and_tamper_guard",
    ):
        gate = report["gates"][key]
        status = "PASS" if gate["passed"] else "FAIL"
        lines.append(f"[{status}] {gate['name']}")
        for item in gate.get("violations", []):
            lines.append(f"  - {item}")
    overall = "PASS" if report["all_passed"] else "FAIL"
    lines.append(
        f"OVERALL: {overall} ({report['gates_passed']}/{report['gates_total']} gates passed in {report['elapsed_s']:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/verify_integrity_branch.py")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--base-ref", default="origin/justSilas")
    ap.add_argument("--no-worktree", action="store_true")
    ap.add_argument("--unit-fast", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    report = run_all_gates(
        root=args.root,
        base_ref=args.base_ref,
        include_worktree=not args.no_worktree,
        unit_fast=args.unit_fast,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_summary(report))

    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
