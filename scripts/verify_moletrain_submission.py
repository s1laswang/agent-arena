from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
_ROOT_STR = str(ROOT)
if sys.path[:1] != [_ROOT_STR]:
    if _ROOT_STR in sys.path:
        sys.path.remove(_ROOT_STR)
    sys.path.insert(0, _ROOT_STR)
for _mod_name in [
    k for k in list(sys.modules) if k in {"canary", "train"} or k.startswith(("canary.", "train."))
]:
    _mod_file = str(getattr(sys.modules[_mod_name], "__file__", "") or "")
    if not _mod_file.startswith(_ROOT_STR):
        sys.modules.pop(_mod_name, None)

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
CO_AUTHOR_LOWER = "co-authored" + "-by"

MAX_ARTIFACT_BYTES = 100 * 1024
MAX_GATE_REPORT_BYTES = 25 * 1024
DEFAULT_GATE_REL = "results/moletrain/submission_gate.json"
MIN_CATCHABLE_ACC = 0.85
CI_TOL = 1e-6

REPLAY_EASY_SEEDS = (200_000, 200_001)

FORBIDDEN_WEIGHT_SUFFIXES: tuple[str, ...] = (
    ".safetensors",
    ".bin",
    ".pt",
)

V100_EVAL_RUN_SPECS: tuple[tuple[str, int], ...] = (
    ("canary-qwen-mole-v1", 1),
    ("canary-qwen3-0p6b-mole-v1", 2),
    ("canary-qwen3-1p7b-mole-v1", 2),
)

MOLETRAIN_PY_FILES: tuple[str, ...] = (
    "canary/forge/rl_mole_v2.py",
    "canary/mole/distill_dsl.py",
    "train/qwen_diverse_mole.py",
    "train/batched_mole_eval.py",
    "train/export_mole_dpo.py",
    "train/eval_mole.py",
    "train/eval_grpo_mole.py",
    "scripts/audit_verda_and_ws3_moles.py",
    "scripts/build_qwen_mole_report.py",
    "scripts/eval_mole_vs_frontier_proxy.py",
    "scripts/verify_moletrain_submission.py",
    "tests/test_rl_mole_v2.py",
    "tests/test_distill_dsl.py",
    "tests/test_qwen_diverse_mole.py",
    "tests/test_qwen25_dpo_grpo_v2.py",
    "tests/test_batched_mole_eval.py",
    "tests/test_export_mole_dpo.py",
    "tests/test_eval_mole.py",
    "tests/test_eval_grpo_mole.py",
    "tests/test_verda_mole_audit.py",
    "tests/test_qwen_mole_report.py",
    "tests/test_eval_mole_vs_frontier_proxy.py",
    "tests/test_verify_moletrain_submission.py",
)

PREEXISTING_SILAS_FILES: tuple[str, ...] = (
    "train/grpo_mole.py",
    "canary/forge/rl_mole.py",
)

CROSS_SQUAD_PY_PREFIXES: tuple[str, ...] = (
    "frontier_",
    "test_frontier_",
    "integrity_",
    "test_integrity_",
    "tiebreak_",
    "test_tiebreak_",
    "craft_",
    "test_craft_",
    "sleeper_",
    "test_sleeper_",
    "v15_",
    "test_v15_",
    "v16_",
    "test_v16_",
    "arena_",
    "test_arena_",
)

CROSS_SQUAD_PY_SUBSTRINGS: tuple[str, ...] = (
    "research",
    "strategies",
    "tiebreak",
    "dagger",
    "staffai",
    "sleeper",
    "arena",
    "transcript_miner",
    "mole_adaptive",
    "mole_beatability",
    "mole_counterfactual",
    "mole_fairness",
    "mole_trap",
    "mole_hof",
    "mole_evolve",
    "mole_ladder",
    "mole_grudge",
    "fr8_grudge",
    "hof_v14",
    "evolve_v14",
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + "s"
            + "k-"
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    ("hf_token", re.compile(r"(?<![0-9A-Za-z_])" + "hf" + "_" + r"[0-9A-Za-z]{24,}")),
    ("github_token", re.compile(r"(?<![0-9A-Za-z_])(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}")),
    ("aws_access_key", re.compile(r"(?<![0-9A-Z])" + "AK" + "IA" + r"[0-9A-Z]{16}(?![0-9A-Z])")),
    ("private_key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

SEEDS_0_29_PATTERN = re.compile(
    r"(?<![0-9])0\s*(?:-|to|\.\.+|" + EN_DASH + r")\s*29(?![0-9])",
    re.IGNORECASE,
)
PREREG_PATTERN = re.compile(
    r"\bpre-?regist(?:er|ered|ering|ration|rations)\b",
    re.IGNORECASE,
)
NEGATED_PREREG_PATTERN = re.compile(
    r"\b(?:not|never|neither|nor|rather\s+than)\s+(?:a\s+|an\s+|being\s+)?pre-?regist",
    re.IGNORECASE,
)
FENCED_CODE_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")
MD_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")

PRIMARY_EVAL_MODEL_KEYS: tuple[str, ...] = (
    "rl_mole_v2",
    "grpo_mole",
    "qwen_mole",
    "heldout_800k_summary",
    "heldout_200k_summary",
    "winner",
    "selected",
    "selected_model",
    "selected_policy",
    "best_model",
    "best_run",
    "primary_mole",
    "distilled_mole",
    "hof_winner",
    "carbon_sft_mole",
)

NON_PRIMARY_COLLECTION_KEYS: frozenset[str] = frozenset(
    {
        "rl_mole_v1",
        "default_mole",
        "baseline",
        "base",
        "val_candidates",
        "candidates",
        "ablations",
        "verda_runs",
        "all_runs",
        "historical_baselines",
        "rejected_candidates",
    }
)


def _redact_secret(token: str) -> str:
    if len(token) <= 8:
        return token[:3] + "..."
    return token[:6] + "..."


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _is_strict_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_protected_paths(protected_txt: Path) -> list[str]:
    rules_out: list[str] = []
    for raw_line in protected_txt.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        rules_out.append(line)
    return rules_out


def match_protected_rule(rel_path: str, rules_list: Sequence[str]) -> str | None:
    norm = rel_path.replace("\\", "/").strip().lstrip("./")
    if not norm:
        return None
    for rule in rules_list:
        if rule.endswith("/"):
            if norm.startswith(rule):
                return rule
        elif norm == rule:
            return rule
    return None


def _run_git_lines(root: Path, args: Sequence[str]) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def collect_changed_files(
    root: Path,
    base_ref: str = "origin/justSilas",
    extra_in_repo_rels: Sequence[str] = (),
) -> tuple[str, list[str], str | None]:
    if not (root / ".git").exists():
        return (
            "fallback_no_git",
            [],
            "git metadata unavailable; parsed protected-paths.txt in archive/shallow fallback mode",
        )

    extra_clean = {p.replace("\\", "/").lstrip("./") for p in extra_in_repo_rels if p}
    untracked = _run_git_lines(root, ["ls-files", "--others", "--exclude-standard"]) or []

    ref_candidates = [base_ref]
    if base_ref != "justSilas":
        ref_candidates.append("justSilas")

    for ref in ref_candidates:
        branch_diff = _run_git_lines(root, ["diff", "--name-only", f"{ref}...HEAD"])
        if branch_diff is not None:
            wt_diff = _run_git_lines(root, ["diff", "--name-only", "HEAD"]) or []
            staged_diff = _run_git_lines(root, ["diff", "--name-only", "--cached"]) or []
            combined = sorted(
                set(branch_diff) | set(wt_diff) | set(staged_diff) | set(untracked) | extra_clean
            )
            return f"git_diff:{ref}...HEAD", combined, None

    wt_diff = _run_git_lines(root, ["diff", "--name-only", "HEAD"])
    staged_diff = _run_git_lines(root, ["diff", "--name-only", "--cached"])
    if wt_diff is not None or staged_diff is not None:
        combined = sorted(set(wt_diff or []) | set(staged_diff or []) | set(untracked) | extra_clean)
        return (
            "fallback_working_tree",
            combined,
            f"base ref {base_ref} unavailable in shallow clone; verified working tree and index",
        )

    return (
        "fallback_shallow_no_head",
        [],
        f"base ref {base_ref} and HEAD diff unavailable; graceful shallow CI fallback",
    )


def is_moletrain_scoped_py(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").strip().lstrip("./")
    if not norm.endswith(".py"):
        return False
    if norm in PREEXISTING_SILAS_FILES:
        return False
    if norm in MOLETRAIN_PY_FILES:
        return True
    p = Path(norm)
    parent = p.parent.as_posix()
    name = p.name
    if name.startswith(CROSS_SQUAD_PY_PREFIXES):
        return False
    if any(tok in name for tok in CROSS_SQUAD_PY_SUBSTRINGS):
        return False
    if parent == "canary/forge":
        return fnmatchcase(name, "rl_mole_*.py") or fnmatchcase(name, "*moletrain*.py")
    if parent == "canary/mole":
        return fnmatchcase(name, "distill_*.py") or fnmatchcase(name, "*moletrain*.py")
    if parent == "train":
        return fnmatchcase(name, "*mole*.py")
    if parent == "scripts":
        return fnmatchcase(name, "*mole*.py")
    if parent == "tests":
        return (
            fnmatchcase(name, "test_*mole*.py")
            or fnmatchcase(name, "test_*qwen*mole*.py")
            or name == "test_qwen25_dpo_grpo_v2.py"
        )
    return False


def discover_moletrain_py_files(
    root: Path,
    base_ref: str = "origin/justSilas",
    py_files: Sequence[str] = MOLETRAIN_PY_FILES,
) -> tuple[list[str], list[str], list[str]]:
    _, changed_files, _ = collect_changed_files(root, base_ref=base_ref)
    ordered = [p.replace("\\", "/").lstrip("./") for p in py_files]
    seen = set(ordered)
    discovered_extra: list[str] = []
    for rel in changed_files:
        norm = rel.replace("\\", "/").lstrip("./")
        if norm in seen or not is_moletrain_scoped_py(norm):
            continue
        if (root / norm).is_file():
            seen.add(norm)
            ordered.append(norm)
            discovered_extra.append(norm)
    return ordered, discovered_extra, changed_files


def check_gate1_protected_paths(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
    extra_in_repo_rels: Sequence[str] = (),
) -> dict[str, Any]:
    protected_file = root / ".github" / "protected-paths.txt"
    if not protected_file.is_file():
        return {
            "gate": "gate_1_protected_paths",
            "name": "Protected Paths",
            "passed": False,
            "mode": "missing_protected_paths_file",
            "protected_rules_count": 0,
            "changed_files_count": 0,
            "protected_hits": [],
            "violations": ["missing .github/protected-paths.txt"],
        }

    rules_list = parse_protected_paths(protected_file)
    if not rules_list:
        return {
            "gate": "gate_1_protected_paths",
            "name": "Protected Paths",
            "passed": False,
            "mode": "empty_protected_paths_file",
            "protected_rules_count": 0,
            "changed_files_count": 0,
            "protected_hits": [],
            "violations": [".github/protected-paths.txt contains 0 rules"],
        }

    mode, changed_files, note = collect_changed_files(
        root,
        base_ref=base_ref,
        extra_in_repo_rels=extra_in_repo_rels,
    )
    hits: list[str] = []
    violations: list[str] = []
    for rel in changed_files:
        matched = match_protected_rule(rel, rules_list)
        if matched is not None:
            hits.append(rel)
            violations.append(f"{rel} matches protected rule {matched!r}")

    out: dict[str, Any] = {
        "gate": "gate_1_protected_paths",
        "name": "Protected Paths",
        "passed": len(violations) == 0,
        "mode": mode,
        "protected_rules_count": len(rules_list),
        "changed_files_count": len(changed_files),
        "protected_hits": hits,
        "violations": violations,
    }
    if note is not None:
        out["note"] = note
    return out


def _scan_text_hygiene(
    text: str,
    rel_label: str,
    *,
    forbid_hash: bool,
) -> list[str]:
    issues: list[str] = []
    if forbid_hash and HASH_CHAR in text:
        count = text.count(HASH_CHAR)
        first_line = next(
            (idx for idx, ln in enumerate(text.splitlines(), 1) if HASH_CHAR in ln),
            1,
        )
        issues.append(f"{rel_label}: contains {count} '{HASH_CHAR}' character(s) (first at line {first_line})")

    if EM_DASH in text:
        count = text.count(EM_DASH)
        first_line = next(
            (idx for idx, ln in enumerate(text.splitlines(), 1) if EM_DASH in ln),
            1,
        )
        issues.append(f"{rel_label}: contains {count} U+2014 em-dash character(s) (first at line {first_line})")

    if CO_AUTHOR_LOWER in text.lower():
        issues.append(f"{rel_label}: contains forbidden Co-Authored" + "-By string")

    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            tok = match.group(0)
            issues.append(f"{rel_label}: contains secret pattern ({kind}: {_redact_secret(tok)})")

    return issues


def _scan_panel_fix_a_honesty(text: str, rel_label: str) -> list[str]:
    issues: list[str] = []
    flagged_lines: set[int] = set()

    for idx, line in enumerate(text.splitlines(), 1):
        if SEEDS_0_29_PATTERN.search(line) and PREREG_PATTERN.search(line):
            if not NEGATED_PREREG_PATTERN.search(line):
                flagged_lines.add(idx)
                issues.append(
                    f"{rel_label}: Panel Fix A violation at line {idx} (seeds 0-29 must not be called pre-registered)"
                )

    for para in re.split(r"\n\s*\n", text):
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            if SEEDS_0_29_PATTERN.search(sentence) and PREREG_PATTERN.search(sentence):
                if not NEGATED_PREREG_PATTERN.search(sentence):
                    snippet = sentence.strip().splitlines()[0] if sentence.strip() else ""
                    line_idx = next(
                        (i for i, ln in enumerate(text.splitlines(), 1) if snippet and snippet in ln),
                        1,
                    )
                    if line_idx not in flagged_lines:
                        flagged_lines.add(line_idx)
                        issues.append(
                            f"{rel_label}: Panel Fix A violation at line {line_idx} (seeds 0-29 must not be called pre-registered)"
                        )
    return issues


def _normalize_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _scan_markdown_relative_links(
    text: str,
    md_path: Path,
    root: Path,
    rel_label: str,
    allowed_rel_paths: frozenset[str] = frozenset(),
) -> list[str]:
    issues: list[str] = []
    stripped = FENCED_CODE_PATTERN.sub(" ", text)
    stripped = INLINE_CODE_PATTERN.sub(" ", stripped)
    root_resolved = root.resolve()
    for match in MD_LINK_PATTERN.finditer(stripped):
        raw_target = match.group(1).strip().strip("<>")
        if not raw_target or raw_target.startswith(("http://", "https://", "mailto:", HASH_CHAR)):
            continue
        target_part = raw_target.split(HASH_CHAR, 1)[0].strip()
        if not target_part:
            continue
        resolved = (md_path.parent / target_part).resolve()
        try:
            tgt_rel = resolved.relative_to(root_resolved).as_posix()
        except ValueError:
            issues.append(f"{rel_label}: relative markdown link escapes repo root ({raw_target})")
            continue
        if not resolved.exists() and tgt_rel not in allowed_rel_paths:
            issues.append(f"{rel_label}: broken relative markdown link ({raw_target} -> {tgt_rel})")
    return issues


def _scan_forbidden_weight_files(root: Path, changed_files: Sequence[str]) -> list[str]:
    candidates: set[str] = set()
    if (root / ".git").exists():
        tracked = _run_git_lines(root, ["ls-files"]) or []
        for rel in tracked:
            candidates.add(rel.replace("\\", "/").lstrip("./"))
        for rel in changed_files:
            norm = rel.replace("\\", "/").lstrip("./")
            if (root / norm).exists():
                candidates.add(norm)
        moletrain_dir = root / "results" / "moletrain"
        if moletrain_dir.is_dir():
            for fp in moletrain_dir.rglob("*"):
                if fp.is_file():
                    candidates.add(_normalize_rel(fp, root))
    else:
        for fp in root.rglob("*"):
            if fp.is_file():
                candidates.add(_normalize_rel(fp, root))

    hits: list[str] = []
    for rel in sorted(candidates):
        suf = Path(rel).suffix.lower()
        if suf in FORBIDDEN_WEIGHT_SUFFIXES and (root / rel).is_file():
            hits.append(rel)
    return hits


def check_gate2_hygiene(
    root: Path = ROOT,
    py_files: Sequence[str] = MOLETRAIN_PY_FILES,
    exclude_rel_paths: Sequence[str] = ("results/moletrain/submission_gate.json",),
    base_ref: str = "origin/justSilas",
) -> dict[str, Any]:
    excluded = {p.replace("\\", "/").lstrip("./") for p in exclude_rel_paths}
    violations: list[str] = []
    checked_py: list[str] = []
    checked_results_files: list[dict[str, Any]] = []
    checked_report_mds: list[str] = []

    effective_py_files, discovered_extra_py, changed_files = discover_moletrain_py_files(
        root=root,
        base_ref=base_ref,
        py_files=py_files,
    )

    for rel in effective_py_files:
        fp = root / rel
        if not fp.is_file():
            violations.append(f"missing moletrain python file: {rel}")
            continue
        checked_py.append(rel)
        txt = fp.read_text(encoding="utf-8")
        violations.extend(_scan_text_hygiene(txt, rel, forbid_hash=True))

    weight_hits = _scan_forbidden_weight_files(root, changed_files)
    for w_rel in weight_hits:
        violations.append(f"{w_rel}: forbidden model weight file ({Path(w_rel).suffix.lower()}) committed")

    moletrain_dir = root / "results" / "moletrain"
    if moletrain_dir.is_dir():
        candidates = sorted(
            p
            for p in moletrain_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".md"}
        )
        for fp in candidates:
            rel = _normalize_rel(fp, root)
            if rel in excluded:
                continue
            raw_bytes = fp.read_bytes()
            sz = len(raw_bytes)
            checked_results_files.append({"path": rel, "bytes": sz})
            if sz >= MAX_ARTIFACT_BYTES:
                violations.append(
                    f"{rel}: size {sz} bytes exceeds 100 KB limit ({MAX_ARTIFACT_BYTES} bytes)"
                )
            try:
                txt = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                violations.append(f"{rel}: invalid UTF-8 ({exc})")
                continue
            violations.extend(_scan_text_hygiene(txt, rel, forbid_hash=False))
            suf = fp.suffix.lower()
            if suf == ".json":
                try:
                    parsed = json.loads(txt)
                except ValueError as exc:
                    violations.append(f"{rel}: invalid JSON ({exc})")
                else:
                    unpacked = json.dumps(parsed, ensure_ascii=False)
                    if EM_DASH in unpacked and EM_DASH not in txt:
                        violations.append(f"{rel}: contains JSON-escaped U+2014 em-dash")
            elif suf == ".jsonl":
                nonempty_lines = 0
                escaped_em_flagged = False
                for line_no, raw_ln in enumerate(txt.splitlines(), 1):
                    stripped = raw_ln.strip()
                    if not stripped:
                        continue
                    nonempty_lines += 1
                    try:
                        row = json.loads(stripped)
                    except ValueError as exc:
                        violations.append(f"{rel}:{line_no}: invalid JSONL record ({exc})")
                        continue
                    if not isinstance(row, dict):
                        violations.append(f"{rel}:{line_no}: JSONL record must be an object")
                        continue
                    unpacked_row = json.dumps(row, ensure_ascii=False)
                    if not escaped_em_flagged and EM_DASH in unpacked_row and EM_DASH not in stripped:
                        escaped_em_flagged = True
                        violations.append(f"{rel}:{line_no}: contains JSON-escaped U+2014 em-dash")
                if nonempty_lines == 0:
                    violations.append(f"{rel}: JSONL file contains 0 records")

    reports_dir = root / "docs" / "reports"
    if reports_dir.is_dir():
        report_paths = (
            set(reports_dir.glob("moletrain_*.md"))
            | set(reports_dir.glob("*qwen*mole*.md"))
        )
        qwen_rep = reports_dir / "qwen_mole_training.md"
        if qwen_rep.is_file():
            report_paths.add(qwen_rep)
        allowed_links = frozenset(excluded | {DEFAULT_GATE_REL})
        for fp in sorted(report_paths, key=lambda p: _normalize_rel(p, root)):
            if not fp.is_file():
                continue
            rel = _normalize_rel(fp, root)
            checked_report_mds.append(rel)
            txt = fp.read_text(encoding="utf-8")
            violations.extend(_scan_text_hygiene(txt, rel, forbid_hash=False))
            violations.extend(_scan_panel_fix_a_honesty(txt, rel))
            if fp.name.startswith("moletrain_") or fp.name == "qwen_mole_training.md":
                violations.extend(
                    _scan_markdown_relative_links(txt, fp, root, rel, allowed_rel_paths=allowed_links)
                )

    if (root / ".git").exists():
        log_lines = _run_git_lines(root, ["log", f"{base_ref}..HEAD", "--format=%H %B"])
        if log_lines is not None:
            joined_log = "\n".join(log_lines)
            if CO_AUTHOR_LOWER in joined_log.lower():
                violations.append(f"git log {base_ref}..HEAD contains forbidden Co-Authored" + "-By trailer")

    return {
        "gate": "gate_2_hygiene",
        "name": "Code & Artifact Hygiene",
        "passed": len(violations) == 0,
        "checked_py_files": checked_py,
        "auto_discovered_py_files": discovered_extra_py,
        "silas_preexisting_exempt": [
            p for p in PREEXISTING_SILAS_FILES if p not in checked_py
        ],
        "checked_moletrain_artifacts": checked_results_files,
        "checked_report_markdowns": checked_report_mds,
        "forbidden_weight_files_found": weight_hits,
        "max_artifact_bytes": MAX_ARTIFACT_BYTES,
        "violations": violations,
    }


def _intervals_overlap(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int] | None:
    lo = max(int(a[0]), int(b[0]))
    hi = min(int(a[1]), int(b[1]))
    if lo <= hi:
        return (lo, hi)
    return None


def _interval_subset_of_any(
    sub: tuple[int, int],
    containers: Sequence[tuple[int, int]],
) -> bool:
    if sub[0] > sub[1]:
        return False
    return any(c[0] <= sub[0] and sub[1] <= c[1] for c in containers)


def check_gate3_seed_disjointness(
    root: Path = ROOT,
    exclude_rel_paths: Sequence[str] = ("results/moletrain/submission_gate.json",),
) -> dict[str, Any]:
    from canary import rules
    from canary.forge import rl_mole, rl_mole_v2
    from train import eval_grpo_mole, eval_mole, grpo_mole, qwen_diverse_mole

    violations: list[str] = []

    dev_iv = (int(rules.DEV_SEEDS.start), int(rules.DEV_SEEDS.stop) - 1)
    judge_iv = (int(rules.JUDGE_SEEDS.start), int(rules.JUDGE_SEEDS.stop) - 1)
    rules_ho_iv = (int(rules.HELDOUT_SEEDS.start), int(rules.HELDOUT_SEEDS.stop) - 1)

    partitions: dict[str, list[tuple[int, int]]] = {
        "rules_dev": [dev_iv],
        "train_counterfactual": [(100_000, 189_999), (300_000, 399_999)],
        "validation": [(190_000, 199_999)],
        "ws3_heldout": [(200_000, 299_999)],
        "eval_mole_heldout": [(400_000, 499_999)],
        "rules_heldout": [(800_000, 899_999)],
        "rules_judge": [judge_iv],
    }

    for name, ivs in partitions.items():
        for lo, hi in ivs:
            if lo > hi:
                violations.append(f"invalid empty/inverted interval in {name}: [{lo}, {hi}]")

    names = list(partitions.keys())
    pairs_checked = 0
    for i, k1 in enumerate(names):
        for k2 in names[i + 1 :]:
            pairs_checked += 1
            for iv1 in partitions[k1]:
                for iv2 in partitions[k2]:
                    ov = _intervals_overlap(iv1, iv2)
                    if ov is not None:
                        violations.append(
                            f"partition overlap between {k1} {iv1} and {k2} {iv2} on [{ov[0]}, {ov[1]}]"
                        )

    if not _interval_subset_of_any(rules_ho_iv, partitions["rules_heldout"]):
        violations.append(
            f"rules.HELDOUT_SEEDS [{rules_ho_iv[0]}, {rules_ho_iv[1]}] outside [800000, 899999]"
        )

    v2_train_iv = (int(rl_mole_v2.TRAIN_SEEDS.start), int(rl_mole_v2.TRAIN_SEEDS.stop) - 1)
    v2_val_iv = (int(rl_mole_v2.VAL_SEEDS.start), int(rl_mole_v2.VAL_SEEDS.stop) - 1)
    v2_ws3_iv = (int(rl_mole_v2.WS3_HELDOUT_SEEDS.start), int(rl_mole_v2.WS3_HELDOUT_SEEDS.stop) - 1)
    v2_rules_iv = (int(rl_mole_v2.RULES_HELDOUT_SEEDS.start), int(rl_mole_v2.RULES_HELDOUT_SEEDS.stop) - 1)

    if not _interval_subset_of_any(v2_train_iv, partitions["train_counterfactual"]):
        violations.append(f"rl_mole_v2.TRAIN_SEEDS {v2_train_iv} outside train_counterfactual")
    if not _interval_subset_of_any(v2_val_iv, partitions["validation"]):
        violations.append(f"rl_mole_v2.VAL_SEEDS {v2_val_iv} outside validation [190000, 199999]")
    if not _interval_subset_of_any(v2_ws3_iv, partitions["ws3_heldout"]):
        violations.append(f"rl_mole_v2.WS3_HELDOUT_SEEDS {v2_ws3_iv} outside ws3_heldout [200000, 299999]")
    if not _interval_subset_of_any(v2_rules_iv, [rules_ho_iv]):
        violations.append(f"rl_mole_v2.RULES_HELDOUT_SEEDS {v2_rules_iv} outside rules.HELDOUT_SEEDS {rules_ho_iv}")

    v1_train_iv = (int(rl_mole.TRAIN_SEED_BASE), int(rl_mole.TRAIN_SEED_BASE) + 50_000 - 1)
    v1_eval_iv = (int(rl_mole.EVAL_SEED_BASE), int(rl_mole.EVAL_SEED_BASE) + 99)
    if not _interval_subset_of_any(v1_train_iv, partitions["train_counterfactual"]):
        violations.append(f"rl_mole v1 train range {v1_train_iv} outside train_counterfactual")
    if not _interval_subset_of_any(v1_eval_iv, partitions["ws3_heldout"]):
        violations.append(f"rl_mole v1 eval range {v1_eval_iv} outside ws3_heldout")

    cf_base = int(qwen_diverse_mole.COUNTERFACTUAL_SEED_BASE)
    qwen_val_base = int(qwen_diverse_mole.VAL_SEED_BASE)
    if not _interval_subset_of_any((cf_base, cf_base + 999), [(100_000, 189_999)]):
        violations.append(
            f"qwen_diverse_mole.COUNTERFACTUAL_SEED_BASE {cf_base} (+999) outside [100000, 189999]"
        )
    if not _interval_subset_of_any((qwen_val_base, qwen_val_base + 999), partitions["validation"]):
        violations.append(
            f"qwen_diverse_mole.VAL_SEED_BASE {qwen_val_base} (+999) outside validation [190000, 199999]"
        )

    grpo_base = int(grpo_mole.PROMPT_SEED_BASE)
    if not _interval_subset_of_any((grpo_base, grpo_base + 999), [(300_000, 399_999)]):
        violations.append(f"grpo_mole.PROMPT_SEED_BASE {grpo_base} outside [300000, 399999]")

    eval_mole_base = int(eval_mole.HELDOUT_SEED_BASE)
    if not _interval_subset_of_any((eval_mole_base, eval_mole_base + 999), partitions["eval_mole_heldout"]):
        violations.append(f"eval_mole.HELDOUT_SEED_BASE {eval_mole_base} outside [400000, 499999]")

    eg_heldout = eval_grpo_mole.parse_seeds("heldout", 50)
    eg_ws3 = eval_grpo_mole.parse_seeds("ws3", 50)
    eg_dev = eval_grpo_mole.parse_seeds("dev", 50)
    if not eg_heldout or not _interval_subset_of_any((min(eg_heldout), max(eg_heldout)), [rules_ho_iv]):
        violations.append("eval_grpo_mole.parse_seeds('heldout', 50) outside rules.HELDOUT_SEEDS")
    if not eg_ws3 or not _interval_subset_of_any((min(eg_ws3), max(eg_ws3)), partitions["ws3_heldout"]):
        violations.append("eval_grpo_mole.parse_seeds('ws3', 50) outside ws3_heldout [200000, 299999]")
    if not eg_dev or not _interval_subset_of_any((min(eg_dev), max(eg_dev)), partitions["rules_dev"]):
        violations.append("eval_grpo_mole.parse_seeds('dev', 50) outside rules.DEV_SEEDS")

    try:
        qwen_diverse_mole.guard_counterfactual_seed(cf_base)
    except ValueError as exc:
        violations.append(f"qwen_diverse_mole.guard_counterfactual_seed rejected {cf_base}: {exc}")

    forbidden_probes = (
        ("validation", qwen_val_base),
        ("ws3_heldout", 200_000),
        ("eval_mole_heldout", eval_mole_base),
        ("rules_heldout", rules_ho_iv[0]),
        ("rules_judge", judge_iv[0]),
    )
    for label, probe in forbidden_probes:
        for fn_name, fn in (
            ("guard_train_seed", qwen_diverse_mole.guard_train_seed),
            ("guard_counterfactual_seed", qwen_diverse_mole.guard_counterfactual_seed),
        ):
            try:
                fn(probe)
            except ValueError:
                pass
            else:
                violations.append(f"qwen_diverse_mole.{fn_name} failed to reject {label} seed {probe}")

    excluded = {p.replace("\\", "/").lstrip("./") for p in exclude_rel_paths}
    moletrain_dir = root / "results" / "moletrain"
    artifact_seed_checks = 0
    if moletrain_dir.is_dir():
        for fp in sorted(moletrain_dir.rglob("*.json")):
            rel = _normalize_rel(fp, root)
            if rel in excluded or fp.name == "rl_mole_v2_policy.json":
                continue
            try:
                doc = json.loads(fp.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(doc, dict):
                continue
            sr = doc.get("seed_ranges")
            if isinstance(sr, dict):
                expected_bucket_map = {
                    "dev": partitions["rules_dev"],
                    "train": partitions["train_counterfactual"],
                    "val": partitions["validation"],
                    "ws3_heldout": partitions["ws3_heldout"],
                    "heldout_200k": partitions["ws3_heldout"],
                    "eval_400k": partitions["eval_mole_heldout"],
                    "rules_heldout": partitions["rules_heldout"],
                    "heldout_800k": partitions["rules_heldout"],
                    "judge": partitions["rules_judge"],
                }
                seen_sr: list[tuple[str, tuple[int, int]]] = []
                for k, bounds in sr.items():
                    if isinstance(bounds, list) and len(bounds) == 2 and all(_is_strict_int(x) for x in bounds):
                        iv = (int(bounds[0]), int(bounds[1]))
                        artifact_seed_checks += 1
                        if k in expected_bucket_map and not _interval_subset_of_any(iv, expected_bucket_map[k]):
                            violations.append(f"{rel}: seed_ranges.{k}={list(iv)} outside canonical {k} partition")
                        if not k.startswith(("combined", "all_")):
                            seen_sr.append((k, iv))
                for idx, (k1, iv1) in enumerate(seen_sr):
                    for k2, iv2 in seen_sr[idx + 1 :]:
                        ov = _intervals_overlap(iv1, iv2)
                        if ov is not None:
                            violations.append(
                                f"{rel}: seed_ranges.{k1} overlaps seed_ranges.{k2} on [{ov[0]}, {ov[1]}]"
                            )

    return {
        "gate": "gate_3_seed_disjointness",
        "name": "Seed Disjointness",
        "passed": len(violations) == 0,
        "partitions": {k: [[lo, hi] for lo, hi in v] for k, v in partitions.items()},
        "pairwise_partition_checks": pairs_checked,
        "module_seed_bindings": {
            "rl_mole_v2": {
                "train": list(v2_train_iv),
                "val": list(v2_val_iv),
                "ws3_heldout": list(v2_ws3_iv),
                "rules_heldout": list(v2_rules_iv),
            },
            "qwen_diverse_mole": {
                "counterfactual_seed_base": cf_base,
                "val_seed_base": qwen_val_base,
            },
            "grpo_mole": {"prompt_seed_base": grpo_base},
            "eval_grpo_mole": {
                "heldout_sample": [eg_heldout[0], eg_heldout[-1]],
                "ws3_sample": [eg_ws3[0], eg_ws3[-1]],
                "dev_sample": [eg_dev[0], eg_dev[-1]],
            },
            "eval_mole": {"heldout_seed_base": eval_mole_base},
        },
        "artifact_seed_range_checks": artifact_seed_checks,
        "violations": violations,
    }


def _is_three_num_list(val: Any) -> bool:
    return isinstance(val, list) and len(val) == 3 and all(_is_finite_num(x) for x in val)


def _is_two_num_list(val: Any) -> bool:
    return isinstance(val, list) and len(val) == 2 and all(_is_finite_num(x) for x in val)


def _is_ci_triple_key(key: str, parent_key: str) -> bool:
    if parent_key == "regret":
        return True
    if key in {"score", "acc", "solver_acc", "solver_score"}:
        return True
    if key.endswith(("_score", "_acc", "_ci", "_ci95")):
        return True
    if key.startswith("regret_"):
        return True
    return False


def _validate_cis_recursive(
    obj: Any,
    loc: str,
    *,
    triple_order: str,
    parent_key: str,
    violations: list[str],
) -> int:
    checked = 0
    if isinstance(obj, dict):
        if parent_key in {"params", "seed_ranges"}:
            return 0

        if _is_finite_num(obj.get("mean")):
            mean_val = float(obj["mean"])
            for ci_key in ("ci95", "ci"):
                if ci_key in obj and _is_two_num_list(obj[ci_key]):
                    lo_val, hi_val = float(obj[ci_key][0]), float(obj[ci_key][1])
                    checked += 1
                    if not (lo_val - CI_TOL <= mean_val <= hi_val + CI_TOL and lo_val <= hi_val + CI_TOL):
                        violations.append(
                            f"{loc}.{ci_key}: lo <= mean <= hi violated (lo={lo_val}, mean={mean_val}, hi={hi_val})"
                        )
            for lo_k, hi_k in (("lo", "hi"), ("ci_lo", "ci_hi"), ("lo95", "hi95")):
                if _is_finite_num(obj.get(lo_k)) and _is_finite_num(obj.get(hi_k)):
                    lo_val, hi_val = float(obj[lo_k]), float(obj[hi_k])
                    checked += 1
                    if not (lo_val - CI_TOL <= mean_val <= hi_val + CI_TOL and lo_val <= hi_val + CI_TOL):
                        violations.append(
                            f"{loc}: lo <= mean <= hi violated (lo={lo_val}, mean={mean_val}, hi={hi_val})"
                        )

        for k, v in obj.items():
            sub_loc = f"{loc}.{k}"
            if k in {"params", "seed_ranges", "action_profile", "leak", "frame"}:
                continue
            if _is_three_num_list(v) and _is_ci_triple_key(k, parent_key):
                if triple_order == "lo_mean_hi":
                    lo_val, mean_val, hi_val = float(v[0]), float(v[1]), float(v[2])
                else:
                    mean_val, lo_val, hi_val = float(v[0]), float(v[1]), float(v[2])
                checked += 1
                if not (lo_val - CI_TOL <= mean_val <= hi_val + CI_TOL and lo_val <= hi_val + CI_TOL):
                    violations.append(
                        f"{sub_loc}: bootstrap CI lo <= mean <= hi violated (lo={lo_val}, mean={mean_val}, hi={hi_val})"
                    )
                for suf in ("_ci95", "_ci"):
                    if k.endswith(suf):
                        base_k = k[: -len(suf)]
                        if _is_finite_num(obj.get(base_k)):
                            pt = float(obj[base_k])
                            if not (lo_val - CI_TOL <= pt <= hi_val + CI_TOL):
                                violations.append(
                                    f"{sub_loc}: sibling {base_k}={pt} outside CI [{lo_val}, {hi_val}]"
                                )
            elif _is_two_num_list(v) and k.endswith(("_ci95", "_ci")):
                base_k = k[:-5] if k.endswith("_ci95") else k[:-3]
                if _is_finite_num(obj.get(base_k)):
                    pt = float(obj[base_k])
                    lo_val, hi_val = float(v[0]), float(v[1])
                    checked += 1
                    if not (lo_val - CI_TOL <= pt <= hi_val + CI_TOL and lo_val <= hi_val + CI_TOL):
                        violations.append(
                            f"{sub_loc}: CI [{lo_val}, {hi_val}] does not bracket {base_k}={pt}"
                        )
            elif isinstance(v, (dict, list)):
                checked += _validate_cis_recursive(
                    v,
                    sub_loc,
                    triple_order=triple_order,
                    parent_key=k,
                    violations=violations,
                )
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                checked += _validate_cis_recursive(
                    item,
                    f"{loc}[{idx}]",
                    triple_order=triple_order,
                    parent_key=parent_key,
                    violations=violations,
                )
    return checked


def _extract_solver_acc(block: dict[str, Any]) -> float | None:
    if _is_finite_num(block.get("solver_acc_point")):
        return float(block["solver_acc_point"])
    solver = block.get("solver")
    if isinstance(solver, dict) and "acc" in solver:
        acc_val = solver["acc"]
        if _is_finite_num(acc_val):
            return float(acc_val)
        if _is_three_num_list(acc_val):
            return float(acc_val[0])
        if isinstance(acc_val, dict) and _is_finite_num(acc_val.get("mean")):
            return float(acc_val["mean"])
    if "solver_acc" in block:
        sa = block["solver_acc"]
        if _is_finite_num(sa):
            return float(sa)
        if _is_three_num_list(sa):
            return float(sa[0])
        if isinstance(sa, dict) and _is_finite_num(sa.get("mean")):
            return float(sa["mean"])
    if "solver_catch" in block:
        sc = block["solver_catch"]
        if _is_finite_num(sc):
            return float(sc)
        if isinstance(sc, dict) and _is_finite_num(sc.get("mean")):
            return float(sc["mean"])
    return None


def _audit_catchable_truthfulness_recursive(
    obj: Any,
    loc: str,
    violations: list[str],
) -> None:
    if isinstance(obj, dict):
        if "catchable_85" in obj:
            c85 = obj["catchable_85"]
            if not isinstance(c85, bool):
                violations.append(f"{loc}.catchable_85 must be boolean, got {type(c85).__name__}")
            elif c85 is True:
                s_acc = _extract_solver_acc(obj)
                if s_acc is not None and s_acc < MIN_CATCHABLE_ACC - 1e-9:
                    violations.append(
                        f"{loc}: catchable_85 is True but solver_acc={s_acc:.4f} < {MIN_CATCHABLE_ACC}"
                    )
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _audit_catchable_truthfulness_recursive(v, f"{loc}.{k}", violations)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                _audit_catchable_truthfulness_recursive(item, f"{loc}[{idx}]", violations)


def _check_primary_model_block(
    block: dict[str, Any],
    loc: str,
    violations: list[str],
    verified_models: list[dict[str, Any]],
) -> None:
    s_acc = _extract_solver_acc(block)
    if s_acc is None:
        return
    has_c85 = "catchable_85" in block
    has_c = "catchable" in block
    if has_c85 and block["catchable_85"] is not True:
        violations.append(f"{loc}: catchable_85 expected True, got {block['catchable_85']!r}")
    elif not has_c85 and has_c and block["catchable"] is not True:
        violations.append(f"{loc}: catchable expected True, got {block['catchable']!r}")
    if s_acc < MIN_CATCHABLE_ACC - 1e-9:
        violations.append(
            f"{loc}: solver_acc={s_acc:.4f} below catchability threshold {MIN_CATCHABLE_ACC}"
        )
    verified_models.append(
        {
            "location": loc,
            "solver_acc": round(s_acc, 4),
            "catchable_85": bool(block["catchable_85"]) if has_c85 else (s_acc >= MIN_CATCHABLE_ACC - 1e-9),
        }
    )


def _inspect_eval_artifact(
    doc: dict[str, Any],
    rel: str,
    violations: list[str],
    verified_models: list[dict[str, Any]],
) -> int:
    ci_fmt = str(doc.get("ci_format") or "")
    triple_order = "lo_mean_hi" if ci_fmt.strip().lower().startswith("[lo") else "mean_lo_hi"
    ci_count = _validate_cis_recursive(
        doc,
        rel,
        triple_order=triple_order,
        parent_key="",
        violations=violations,
    )
    _audit_catchable_truthfulness_recursive(doc, rel, violations)

    for top_bool in ("catchable_85", "catchable_85_both_sets", "all_heldout_catchable"):
        if top_bool in doc and doc[top_bool] is not True:
            violations.append(f"{rel}.{top_bool} expected True, got {doc[top_bool]!r}")

    for set_key in ("ws3_heldout", "rules_heldout", "heldout", "eval"):
        sub = doc.get(set_key)
        if isinstance(sub, dict):
            for mkey in PRIMARY_EVAL_MODEL_KEYS:
                if mkey in sub and isinstance(sub[mkey], dict):
                    _check_primary_model_block(
                        sub[mkey],
                        f"{rel}.{set_key}.{mkey}",
                        violations,
                        verified_models,
                    )

    for mkey in PRIMARY_EVAL_MODEL_KEYS:
        if mkey in NON_PRIMARY_COLLECTION_KEYS:
            continue
        sub = doc.get(mkey)
        if isinstance(sub, dict):
            _check_primary_model_block(sub, f"{rel}.{mkey}", violations, verified_models)

    for paired_key, paired_val in doc.items():
        if paired_key.startswith("paired_") and isinstance(paired_val, dict):
            q_sub = paired_val.get("qwen_mole")
            if isinstance(q_sub, dict):
                _check_primary_model_block(
                    q_sub,
                    f"{rel}.{paired_key}.qwen_mole",
                    violations,
                    verified_models,
                )

    if isinstance(doc.get("adapter_result"), dict):
        _check_primary_model_block(
            doc["adapter_result"],
            f"{rel}.adapter_result",
            violations,
            verified_models,
        )

    if "solver" in doc and isinstance(doc["solver"], dict):
        _check_primary_model_block(doc, rel, violations, verified_models)

    return ci_count


def _verify_v100_eval_summaries(
    moletrain_dir: Path,
    root: Path,
    violations: list[str],
) -> list[dict[str, Any]]:
    summary_index: dict[str, dict[str, Any]] = {}
    qwen_summary_path = moletrain_dir / "qwen_mole_summary.json"
    if qwen_summary_path.is_file():
        try:
            qsum_doc = json.loads(qwen_summary_path.read_text(encoding="utf-8"))
        except ValueError:
            qsum_doc = None
        if isinstance(qsum_doc, dict):
            v100_sec = qsum_doc.get("v100_regularized_sft_grpo")
            if isinstance(v100_sec, dict) and isinstance(v100_sec.get("runs"), list):
                for entry in v100_sec["runs"]:
                    if isinstance(entry, dict) and isinstance(entry.get("run_id"), str):
                        summary_index[entry["run_id"]] = entry

    checked_runs: list[dict[str, Any]] = []
    for run_name, min_distinct in V100_EVAL_RUN_SPECS:
        run_dir = moletrain_dir / run_name
        eval_fp = run_dir / "eval_summary.json"
        rel_eval = _normalize_rel(eval_fp, root)
        if not eval_fp.is_file():
            violations.append(f"missing V100 evaluation artifact: results/moletrain/{run_name}/eval_summary.json")
            continue

        for curve_name in ("sft_curve.jsonl", "grpo_curve.jsonl"):
            cfp = run_dir / curve_name
            if not cfp.is_file():
                violations.append(f"missing V100 training curve: results/moletrain/{run_name}/{curve_name}")

        try:
            doc = json.loads(eval_fp.read_text(encoding="utf-8"))
        except ValueError as exc:
            violations.append(f"{rel_eval}: invalid JSON ({exc})")
            continue
        if not isinstance(doc, dict):
            violations.append(f"{rel_eval}: top-level JSON value must be an object")
            continue

        if doc.get("name") != run_name:
            violations.append(f"{rel_eval}: expected name={run_name!r}, got {doc.get('name')!r}")
        if doc.get("smoke_tiny") is not False:
            violations.append(f"{rel_eval}: expected smoke_tiny=False, got {doc.get('smoke_tiny')!r}")

        val_cands = doc.get("val_candidates")
        winner_ckpt = doc.get("winner_checkpoint")
        if not isinstance(val_cands, dict) or not val_cands:
            violations.append(f"{rel_eval}: missing or empty val_candidates")
        else:
            if not isinstance(winner_ckpt, str) or winner_ckpt not in val_cands:
                violations.append(
                    f"{rel_eval}: winner_checkpoint={winner_ckpt!r} missing from val_candidates"
                )
            for ckpt_name, ckpt_block in val_cands.items():
                if not isinstance(ckpt_block, dict):
                    violations.append(f"{rel_eval}.val_candidates.{ckpt_name}: must be an object")
                    continue
                inv_gen = ckpt_block.get("invalid_generations")
                if not _is_strict_int(inv_gen) or int(inv_gen) != 0:
                    violations.append(
                        f"{rel_eval}.val_candidates.{ckpt_name}: invalid_generations expected 0, got {inv_gen!r}"
                    )

        split_stats: dict[str, dict[str, Any]] = {}
        for split_key, paired_key in (
            ("heldout_800k_summary", "paired_800k_vs_default"),
            ("heldout_200k_summary", "paired_200k_vs_default"),
        ):
            sub = doc.get(split_key)
            loc = f"{rel_eval}.{split_key}"
            if not isinstance(sub, dict):
                violations.append(f"{loc}: missing held-out summary object")
                continue

            c85 = sub.get("catchable_85")
            if c85 is not True:
                violations.append(f"{loc}: catchable_85 expected True, got {c85!r}")

            s_acc = _extract_solver_acc(sub)
            if s_acc is None or s_acc < MIN_CATCHABLE_ACC - 1e-9:
                violations.append(
                    f"{loc}: solver_acc={s_acc!r} below catchability threshold {MIN_CATCHABLE_ACC}"
                )

            inv_gen = sub.get("invalid_generations")
            if not _is_strict_int(inv_gen) or int(inv_gen) != 0:
                violations.append(f"{loc}: invalid_generations expected 0, got {inv_gen!r}")

            dist_act = sub.get("distinct_actions")
            if not _is_strict_int(dist_act) or int(dist_act) < min_distinct:
                violations.append(
                    f"{loc}: distinct_actions expected >= {min_distinct}, got {dist_act!r}"
                )

            paired_obj = doc.get(paired_key)
            if not isinstance(paired_obj, dict) or not isinstance(paired_obj.get("qwen_mole"), dict):
                violations.append(f"{rel_eval}.{paired_key}.qwen_mole: missing paired evaluation block")
            else:
                q_solver = paired_obj["qwen_mole"].get("solver")
                s_solver = sub.get("solver")
                if isinstance(q_solver, dict) and isinstance(s_solver, dict):
                    if _is_three_num_list(q_solver.get("acc")) and _is_finite_num(s_solver.get("acc")):
                        if abs(float(q_solver["acc"][0]) - float(s_solver["acc"])) > 1e-4:
                            violations.append(
                                f"{rel_eval}: {split_key}.solver.acc={s_solver['acc']} mismatches {paired_key} {q_solver['acc'][0]}"
                            )
                    if _is_three_num_list(q_solver.get("score")) and _is_finite_num(s_solver.get("score")):
                        if abs(float(q_solver["score"][0]) - float(s_solver["score"])) > 1e-4:
                            violations.append(
                                f"{rel_eval}: {split_key}.solver.score={s_solver['score']} mismatches {paired_key} {q_solver['score'][0]}"
                            )

            split_stats[split_key] = {
                "solver_acc": round(float(s_acc), 4) if s_acc is not None else None,
                "min_regret": round(float(sub["min_regret"]), 4) if _is_finite_num(sub.get("min_regret")) else None,
                "distinct_actions": int(dist_act) if _is_strict_int(dist_act) else None,
                "invalid_generations": int(inv_gen) if _is_strict_int(inv_gen) else None,
                "catchable_85": c85 is True,
            }

        if run_name in summary_index:
            s_entry = summary_index[run_name]
            if s_entry.get("status") != "completed":
                violations.append(
                    f"qwen_mole_summary.json: {run_name} status expected 'completed', got {s_entry.get('status')!r}"
                )
            es_sub = s_entry.get("eval_summary")
            if not isinstance(es_sub, dict):
                violations.append(f"qwen_mole_summary.json: {run_name} missing eval_summary block")
            else:
                if es_sub.get("winner_checkpoint") != winner_ckpt:
                    violations.append(
                        f"qwen_mole_summary.json: {run_name} winner_checkpoint={es_sub.get('winner_checkpoint')!r} != {winner_ckpt!r}"
                    )
                for sum_k, raw_k in (("heldout_800k", "heldout_800k_summary"), ("heldout_200k", "heldout_200k_summary")):
                    q_ho = es_sub.get(sum_k)
                    r_ho = split_stats.get(raw_k)
                    if not isinstance(q_ho, dict) or r_ho is None:
                        violations.append(f"qwen_mole_summary.json: {run_name} missing {sum_k}")
                        continue
                    if q_ho.get("catchable_85") is not True:
                        violations.append(f"qwen_mole_summary.json: {run_name}.{sum_k}.catchable_85 != True")
                    if _is_finite_num(q_ho.get("qwen_solver_acc")) and r_ho["solver_acc"] is not None:
                        if abs(float(q_ho["qwen_solver_acc"]) - float(r_ho["solver_acc"])) > 1e-4:
                            violations.append(
                                f"qwen_mole_summary.json: {run_name}.{sum_k}.qwen_solver_acc mismatches eval_summary.json"
                            )
                    if _is_finite_num(q_ho.get("qwen_min_regret")) and r_ho["min_regret"] is not None:
                        if abs(float(q_ho["qwen_min_regret"]) - float(r_ho["min_regret"])) > 1e-4:
                            violations.append(
                                f"qwen_mole_summary.json: {run_name}.{sum_k}.qwen_min_regret mismatches eval_summary.json"
                            )
                    if q_ho.get("distinct_actions") != r_ho["distinct_actions"]:
                        violations.append(
                            f"qwen_mole_summary.json: {run_name}.{sum_k}.distinct_actions mismatches eval_summary.json"
                        )

        s800 = split_stats.get("heldout_800k_summary", {})
        s200 = split_stats.get("heldout_200k_summary", {})
        checked_runs.append(
            {
                "run_id": run_name,
                "winner_checkpoint": winner_ckpt,
                "acc_800k": s800.get("solver_acc"),
                "acc_200k": s200.get("solver_acc"),
                "min_regret_800k": s800.get("min_regret"),
                "min_regret_200k": s200.get("min_regret"),
                "distinct_800k": s800.get("distinct_actions"),
                "distinct_200k": s200.get("distinct_actions"),
                "catchable_85_both": bool(s800.get("catchable_85") and s200.get("catchable_85")),
            }
        )

    return checked_runs


def _replay_rl_mole_v2_policy(
    policy_path: Path,
    seeds: Sequence[int] = REPLAY_EASY_SEEDS,
) -> tuple[list[dict[str, Any]], list[str]]:
    import numpy as np

    from canary import rules
    from canary.env import Env
    from canary.eval import run_episode
    from canary.forge.rl_mole_v2 import RLMoleV2
    from canary.solver.policy import SolverPolicy

    violations: list[str] = []
    replays: list[dict[str, Any]] = []

    try:
        pol_obj = json.loads(policy_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [], [f"{policy_path.name}: invalid JSON ({exc})"]

    try:
        pol_base = RLMoleV2.from_json(pol_obj)
        pol_roundtrip = RLMoleV2.from_json(pol_base.to_json())
    except (ValueError, KeyError, TypeError) as exc:
        return [], [f"{policy_path.name}: RLMoleV2.from_json failed ({exc})"]

    for key in ("W1", "b1", "Wl", "bl", "Wf", "bf"):
        arr = pol_base.p[key]
        if not bool(np.all(np.isfinite(arr))):
            violations.append(f"{policy_path.name}: non-finite values in parameter {key}")
        if not bool(np.allclose(arr, pol_roundtrip.p[key], rtol=0.0, atol=1e-15)):
            violations.append(f"{policy_path.name}: roundtrip mismatch in parameter {key}")

    judge_set = set(rules.JUDGE_SEEDS)
    for seed in seeds:
        s = int(seed)
        if s in judge_set:
            violations.append(f"replay seed {s} is in JUDGE_SEEDS")
            continue
        tr_a: list = []
        tr_b: list = []
        p_a = RLMoleV2.from_json(pol_obj)
        p_a.trace = tr_a
        p_b = RLMoleV2.from_json(pol_obj)
        p_b.trace = tr_b

        ep_a = run_episode(Env("easy", s, mole_strategy=p_a), SolverPolicy("easy"))
        ep_b = run_episode(Env("easy", s, mole_strategy=p_b), SolverPolicy("easy"))

        tup_a = (float(ep_a.score), bool(ep_a.correct), ep_a.accused, int(ep_a.final_day))
        tup_b = (float(ep_b.score), bool(ep_b.correct), ep_b.accused, int(ep_b.final_day))

        trace_match = len(tr_a) == len(tr_b) and len(tr_a) > 0
        if trace_match:
            for (x1, l1, f1), (x2, l2, f2) in zip(tr_a, tr_b):
                if l1 != l2 or f1 != f2 or not bool(np.array_equal(x1, x2)):
                    trace_match = False
                    break

        exact = (tup_a == tup_b) and trace_match and (-1.0 <= tup_a[0] <= 1.0)
        if not exact:
            violations.append(
                f"RLMoleV2 easy seed {s} replay mismatch: runA={tup_a} (steps={len(tr_a)}) vs runB={tup_b} (steps={len(tr_b)})"
            )
        replays.append(
            {
                "tier": "easy",
                "seed": s,
                "score": round(tup_a[0], 6),
                "correct": tup_a[1],
                "accused": tup_a[2],
                "final_day": tup_a[3],
                "mole_decisions": len(tr_a),
                "reproducible": exact,
            }
        )

    return replays, violations


def check_gate4_catchability_and_provenance(
    root: Path = ROOT,
    exclude_rel_paths: Sequence[str] = ("results/moletrain/submission_gate.json",),
    replay_seeds: Sequence[int] = REPLAY_EASY_SEEDS,
) -> dict[str, Any]:
    excluded = {p.replace("\\", "/").lstrip("./") for p in exclude_rel_paths}
    moletrain_dir = root / "results" / "moletrain"
    violations: list[str] = []

    if not moletrain_dir.is_dir():
        return {
            "gate": "gate_4_catchability_and_provenance",
            "name": "Catchability & CI Provenance",
            "passed": False,
            "artifacts_inspected": [],
            "bootstrap_cis_checked": 0,
            "verified_catchable_models": [],
            "v100_eval_summaries_checked": [],
            "rl_mole_v2_replay": [],
            "violations": ["missing results/moletrain directory"],
        }

    pol_path = moletrain_dir / "rl_mole_v2_policy.json"
    ho_path = moletrain_dir / "rl_mole_v2_heldout.json"
    if not pol_path.is_file():
        violations.append("missing results/moletrain/rl_mole_v2_policy.json")
    if not ho_path.is_file():
        violations.append("missing results/moletrain/rl_mole_v2_heldout.json")

    artifacts_meta: list[dict[str, Any]] = []
    verified_models: list[dict[str, Any]] = []
    total_cis = 0

    for fp in sorted(moletrain_dir.rglob("*.json")):
        rel = _normalize_rel(fp, root)
        if rel in excluded:
            continue
        raw = fp.read_bytes()
        artifacts_meta.append(
            {
                "path": rel,
                "bytes": len(raw),
                "sha256_16": _sha256_bytes(raw)[:16],
            }
        )
        if fp.name == "rl_mole_v2_policy.json":
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            violations.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(doc, dict):
            violations.append(f"{rel}: top-level JSON value must be an object")
            continue
        total_cis += _inspect_eval_artifact(doc, rel, violations, verified_models)

    if ho_path.is_file():
        try:
            ho_doc = json.loads(ho_path.read_text(encoding="utf-8"))
        except ValueError:
            ho_doc = None
        if isinstance(ho_doc, dict):
            for set_key in ("ws3_heldout", "rules_heldout"):
                sub = ho_doc.get(set_key)
                if not isinstance(sub, dict) or not isinstance(sub.get("rl_mole_v2"), dict):
                    violations.append(f"rl_mole_v2_heldout.json missing {set_key}.rl_mole_v2 block")

    v100_checked = _verify_v100_eval_summaries(moletrain_dir, root, violations)

    if total_cis == 0:
        violations.append("0 bootstrap CIs found across results/moletrain/**/*.json")
    if not verified_models:
        violations.append("0 primary catchable mole evaluation blocks verified in results/moletrain/**/*.json")

    replays: list[dict[str, Any]] = []
    if pol_path.is_file():
        replays, rep_violations = _replay_rl_mole_v2_policy(pol_path, seeds=replay_seeds)
        violations.extend(rep_violations)

    return {
        "gate": "gate_4_catchability_and_provenance",
        "name": "Catchability & CI Provenance",
        "passed": len(violations) == 0,
        "min_solver_acc_threshold": MIN_CATCHABLE_ACC,
        "artifacts_inspected": artifacts_meta,
        "bootstrap_cis_checked": total_cis,
        "verified_catchable_models": verified_models,
        "v100_eval_summaries_checked": v100_checked,
        "rl_mole_v2_replay": replays,
        "violations": violations,
    }


def run_all_gates(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
    out_path: Path | None = None,
    py_files: Sequence[str] = MOLETRAIN_PY_FILES,
    replay_seeds: Sequence[int] = REPLAY_EASY_SEEDS,
) -> dict[str, Any]:
    from canary import rules

    exclude_rels = ["results/moletrain/submission_gate.json"]
    extra_in_repo: list[str] = []
    if out_path is not None:
        try:
            out_rel = out_path.resolve().relative_to(root.resolve()).as_posix()
            extra_in_repo.append(out_rel)
        except ValueError:
            out_rel = _normalize_rel(out_path, root)
        if out_rel not in exclude_rels:
            exclude_rels.append(out_rel)

    g1 = check_gate1_protected_paths(
        root=root,
        base_ref=base_ref,
        extra_in_repo_rels=extra_in_repo,
    )
    g2 = check_gate2_hygiene(
        root=root,
        py_files=py_files,
        exclude_rel_paths=exclude_rels,
        base_ref=base_ref,
    )
    g3 = check_gate3_seed_disjointness(root=root, exclude_rel_paths=exclude_rels)
    g4 = check_gate4_catchability_and_provenance(
        root=root,
        exclude_rel_paths=exclude_rels,
        replay_seeds=replay_seeds,
    )

    gates = [g1, g2, g3, g4]
    all_passed = all(bool(g["passed"]) for g in gates)

    report: dict[str, Any] = {
        "schema": "moletrain_submission_gate_v1",
        "tiers_version": rules.TIERS_VERSION,
        "all_passed": all_passed,
        "gates_passed": sum(1 for g in gates if g["passed"]),
        "gates_total": len(gates),
        "gates": {
            "gate_1_protected_paths": g1,
            "gate_2_hygiene": g2,
            "gate_3_seed_disjointness": g3,
            "gate_4_catchability_and_provenance": g4,
        },
    }

    serialized = json.dumps(report, indent=2) + "\n"
    encoded = serialized.encode("utf-8")
    self_issues = _scan_text_hygiene(serialized, "submission_gate.json", forbid_hash=False)
    if len(encoded) > MAX_GATE_REPORT_BYTES:
        self_issues.append(
            f"submission_gate.json size {len(encoded)} bytes > 25 KB ({MAX_GATE_REPORT_BYTES} bytes)"
        )
    if self_issues:
        g2["violations"].extend(self_issues)
        g2["passed"] = False
        report["all_passed"] = False
        report["gates_passed"] = sum(1 for g in gates if g["passed"])
        serialized = json.dumps(report, indent=2) + "\n"

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized, encoding="utf-8")
    else:
        existing_gate = root / DEFAULT_GATE_REL
        if existing_gate.is_file():
            raw_existing = existing_gate.read_bytes()
            ex_issues: list[str] = []
            if len(raw_existing) > MAX_GATE_REPORT_BYTES:
                ex_issues.append(
                    f"{DEFAULT_GATE_REL} size {len(raw_existing)} bytes > 25 KB"
                )
            ex_txt = raw_existing.decode("utf-8")
            ex_issues.extend(_scan_text_hygiene(ex_txt, DEFAULT_GATE_REL, forbid_hash=False))
            try:
                ex_doc = json.loads(ex_txt)
            except ValueError as exc:
                ex_issues.append(f"{DEFAULT_GATE_REL}: invalid JSON ({exc})")
            else:
                if not isinstance(ex_doc, dict) or ex_doc.get("all_passed") is not True:
                    ex_issues.append(f"{DEFAULT_GATE_REL}: committed gate report has all_passed != True")
            if ex_issues:
                g2["violations"].extend(ex_issues)
                g2["passed"] = False
                report["all_passed"] = False
                report["gates_passed"] = sum(1 for g in gates if g["passed"])

    return report


def format_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in (
        "gate_1_protected_paths",
        "gate_2_hygiene",
        "gate_3_seed_disjointness",
        "gate_4_catchability_and_provenance",
    ):
        g = report["gates"][key]
        tag = "PASS" if g["passed"] else "FAIL"
        lines.append(f"[{tag}] {g['name']}")
        for v in g.get("violations", []):
            lines.append(f"  - {v}")
    overall = "PASS" if report["all_passed"] else "FAIL"
    lines.append(f"OVERALL: {overall} ({report['gates_passed']}/{report['gates_total']} gates passed)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/verify_moletrain_submission.py")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--base-ref", default="origin/justSilas")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root_resolved = args.root.resolve()
    if args.out is not None:
        out_resolved: Path | None = args.out if args.out.is_absolute() else Path.cwd() / args.out
    elif args.write or not args.check:
        out_resolved = root_resolved / DEFAULT_GATE_REL
    else:
        out_resolved = None

    report = run_all_gates(
        root=root_resolved,
        base_ref=args.base_ref,
        out_path=out_resolved,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_summary(report))

    if args.check and not report["all_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
