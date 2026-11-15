from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
MD_LINK_RX = re.compile(r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\(([^)\n]+)\)")
STALE_GAP_RX = re.compile(r"gap\s*(?:is\s+|:\s*)?not\s+established", re.IGNORECASE)
TIER_HEADING_RX = re.compile(r"^\x23\x23\s+(easy|medium|hard)\b", re.IGNORECASE)
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")
FALSE_PREREG_0_29_RX = re.compile(
    r"(?:"
    r"(?:primary\s+)?seed\s+set\s+(?:was|is|were)\s+pre-?register\w*"
    r"|pre-?register\w*\s+(?:the\s+)?(?:locked\s+|primary\s+)?(?:dev\s+)?seeds?\s*0\s*(?:-|\.\.)\s*29\b"
    r"|(?:dev\s+)?seeds?\s*0\s*(?:-|\.\.)\s*29\s+(?:were|was|are|is)\s+pre-?register\w*"
    r"|pre-?register\w*\s+(?:the\s+)?(?:primary\s+|headline\s+)?n\s*=\s*30\b"
    r"|\bn\s*=\s*30\s+(?:headline\s+|primary\s+|set\s+|row\s+)?(?:was|is|were|are)\s+pre-?register\w*"
    r")",
    re.IGNORECASE,
)
FALSE_TIEBREAK_BAR_MET_RX = re.compile(
    r"(?:"
    r"\bbar\b[^.\n?!]{0,90}\b(?:is|was)\s+(?:fully\s+|clearly\s+)?met\b"
    r"|\bmet\s+the\s+(?:ws4\s+|small-model\s+)?tiebreak(?:er)?\s+bar\b"
    r"|\btiebreak(?:er)?\s+bar\s*:\s*met\b"
    r"|(?<!\bno\s)(?<!\bnot\s)\bclaim\s+a\s+(?:held-out\s+)?(?:tiebreak(?:er)?\s+)?(?:reward\s+)?gain\b"
    r"|(?<!\bno\s)(?<!\bwithout\s)\bheld-out\s+(?:reward\s+)?gain\s+over\s+(?:the\s+)?base\b"
    r")",
    re.IGNORECASE,
)
POOLED_MENTION_RX = re.compile(
    r"(?:\bpooled\b|\bn\s*=\s*32\b|\bn\s*=\s*60\b|opencode-gemini-4-carbon-ext|paired_table_pooled0to59)",
    re.IGNORECASE,
)
STEP_EXIT_RX = re.compile(r"\bexit=(-?\d+)\b")

ACTIVE_HEADLINE_DOCS: tuple[str, ...] = (
    "README.md",
    "JUDGE_QUICKSTART.md",
    "docs/CONTRACT.md",
    "docs/EXPLOITS.md",
    "docs/DIFFICULTY.md",
    "docs/JUDGE-WALKTHROUGH.md",
    "docs/REPRODUCIBILITY.md",
    "docs/PEER-REVIEW-QA.md",
    "docs/SUBMISSION.md",
    "docs/reports/gap.md",
    "docs/reports/failure_analysis_v1.4.md",
    "docs/reports/reference_optimality.md",
    "docs/reports/integrity.md",
    "docs/gemini/SUBMISSION.md",
    "results/judge_table.md",
)

SECONDARY_GAP_DOCS: tuple[str, ...] = (
    "harbor/README.md",
    "pitch/GEMINI.md",
    "HANDOFF.md",
)

EXEMPT_GAP_PATTERNS: tuple[str, ...] = (
    "docs/HISTORY.md",
    "docs/PLAN*.md",
    "docs/DEMO.md",
    "docs/reports/judge_sim.md",
    "docs/reports/number_audit.md",
    "results/fresh_clone/*.log.txt",
)

FRESH_CLONE_AF_STEPS_REL = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt"
FRESH_CLONE_AF_LOG_REL = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt"
FRESH_CLONE_README_REL = "results/fresh_clone/README.md"

LEGACY_RESULTS_PATTERNS: tuple[str, ...] = (
    "regret_*-v1.json",
    "regret_*-v1.md",
    "regret_*-v1.2.*",
    "regret_*-v1.3.*",
    "fresh_table_v1.2.md",
    "fresh_table_v1.3.md",
)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _has_dot_git(root: Path) -> bool:
    dot_git = root / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    ceiling = str(root.resolve().parent)
    existing = env.get("GIT_CEILING_DIRECTORIES", "")
    env["GIT_CEILING_DIRECTORIES"] = f"{ceiling}{os.pathsep}{existing}" if existing else ceiling
    return env


def _git_ls_files(root: Path) -> list[str] | None:
    if not _has_dot_git(root):
        return None
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [entry for entry in raw.split("\0") if entry]


def _parse_gitignore_fallback_rules(root: Path) -> list[tuple[bool, bool, bool, str]]:
    gi_path = root / ".gitignore"
    if not gi_path.is_file():
        return []
    try:
        lines = gi_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rules: list[tuple[bool, bool, bool, str]] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        negated = stripped.startswith("!")
        body = stripped[1:].strip() if negated else stripped
        if not body:
            continue
        dir_only = body.endswith("/")
        pat = body.strip("/")
        if not pat:
            continue
        anchored = ("/" in pat) or raw.lstrip(" !").startswith("/")
        rules.append((negated, dir_only, anchored, pat))
    return rules


@functools.lru_cache(maxsize=512)
def _compile_anchored_gitignore_pat(pat: str) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    n = len(pat)
    while i < n:
        if pat[i : i + 3] == "**/":
            parts.append("(?:.+/)?")
            i += 3
        elif pat[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pat[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(parts))


def _gitignore_pat_matches(pat: str, rel_pos: str, name: str, anchored: bool) -> bool:
    if not anchored:
        return fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(rel_pos, pat)
    if "**/" in pat and _gitignore_pat_matches(pat.replace("**/", ""), rel_pos, name, True):
        return True
    return _compile_anchored_gitignore_pat(pat).fullmatch(rel_pos) is not None


def _fallback_is_ignored(
    rules: list[tuple[bool, bool, bool, str]],
    rel_path: str,
    is_dir: bool = False,
) -> bool:
    if not rules:
        return False
    clean = rel_path.strip("/")
    if not clean or clean == ".":
        return False
    segments = clean.split("/")
    total = len(segments)
    for depth in range(1, total + 1):
        sub = "/".join(segments[:depth])
        sub_name = segments[depth - 1]
        sub_is_dir = True if depth < total else is_dir
        ignored = False
        for negated, dir_only, anchored, pat in rules:
            if dir_only and not sub_is_dir:
                continue
            if _gitignore_pat_matches(pat, sub, sub_name, anchored):
                ignored = not negated
        if ignored and depth < total:
            return True
        if depth == total:
            return ignored
    return False


def _git_is_ignored(root: Path, rel_path: str) -> bool:
    if not _has_dot_git(root):
        rules = _parse_gitignore_fallback_rules(root)
        return _fallback_is_ignored(rules, rel_path, is_dir=rel_path.endswith("/"))
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", rel_path],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        rules = _parse_gitignore_fallback_rules(root)
        return _fallback_is_ignored(rules, rel_path, is_dir=rel_path.endswith("/"))
    if proc.returncode not in (0, 1):
        rules = _parse_gitignore_fallback_rules(root)
        return _fallback_is_ignored(rules, rel_path, is_dir=rel_path.endswith("/"))
    return proc.returncode == 0


def _git_ignored_batch(root: Path, rel_paths: list[str]) -> set[str]:
    if not rel_paths:
        return set()
    unique_paths = sorted(set(rel_paths))
    if not _has_dot_git(root):
        rules = _parse_gitignore_fallback_rules(root)
        return {
            p
            for p in unique_paths
            if _fallback_is_ignored(rules, p, is_dir=p.endswith("/"))
        }
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=root,
            env=_git_env(root),
            input="\n".join(unique_paths) + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        rules = _parse_gitignore_fallback_rules(root)
        return {
            p
            for p in unique_paths
            if _fallback_is_ignored(rules, p, is_dir=p.endswith("/"))
        }
    if proc.returncode not in (0, 1):
        rules = _parse_gitignore_fallback_rules(root)
        return {
            p
            for p in unique_paths
            if _fallback_is_ignored(rules, p, is_dir=p.endswith("/"))
        }
    return {ln for ln in proc.stdout.splitlines() if ln}


def _strip_markdown_code_preserving_lines(md_text: str) -> list[str]:
    cleaned_lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for raw_line in md_text.splitlines():
        m = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if m:
                marker = m.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                cleaned_lines.append("")
                continue
            cleaned_lines.append(INLINE_CODE_RX.sub("", raw_line))
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            cleaned_lines.append("")
    return cleaned_lines


def _collect_markdown_files(root: Path) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    def _add(p: Path) -> None:
        if not p.is_file():
            return
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(p)

    _add(root / "README.md")
    _add(root / "JUDGE_QUICKSTART.md")
    _add(root / "HANDOFF.md")
    _add(root / "docs" / "JUDGE-WALKTHROUGH.md")
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.rglob("*.md")):
            _add(p)
    _add(root / "harbor" / "README.md")
    results_dir = root / "results"
    if results_dir.is_dir():
        for p in sorted(results_dir.rglob("*.md")):
            if "latest" in p.relative_to(results_dir).parts:
                continue
            _add(p)
    pitch_dir = root / "pitch"
    if pitch_dir.is_dir():
        for p in sorted(pitch_dir.rglob("*.md")):
            _add(p)
    return ordered


def _parse_link_target(raw_inside_parens: str) -> str:
    raw = raw_inside_parens.strip()
    if not raw:
        return ""
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")].strip()
    return raw.split()[0].strip()


def check_markdown_links(root: Path) -> CheckResult:
    name = "Internal Markdown Links"
    root_resolved = root.resolve()
    md_files = _collect_markdown_files(root_resolved)
    if not md_files:
        return CheckResult(name, "FAIL", "no markdown files found to scan")

    failures: list[str] = []
    pending_missing: list[tuple[str, int, str, str, list[str]]] = []
    total_links = 0

    for md_file in md_files:
        md_rel = md_file.relative_to(root_resolved).as_posix()
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failures.append(f"{md_rel}: unreadable markdown file ({type(exc).__name__})")
            continue

        cleaned_lines = _strip_markdown_code_preserving_lines(content)
        for lineno, line in enumerate(cleaned_lines, 1):
            if "(" not in line or "[" not in line:
                continue
            for match in MD_LINK_RX.finditer(line):
                target = _parse_link_target(match.group(1))
                if not target:
                    continue
                lower_target = target.lower()
                if lower_target.startswith(("http://", "https://", "mailto:")) or target.startswith(HASH_CHAR):
                    continue
                path_part = unquote(target.split(HASH_CHAR, 1)[0]).strip()
                if not path_part:
                    continue

                total_links += 1
                had_trailing_slash = path_part.endswith("/")
                resolved = (md_file.parent / path_part).resolve()
                if resolved.exists():
                    continue

                try:
                    rel_target = resolved.relative_to(root_resolved).as_posix()
                except ValueError:
                    failures.append(f"{md_rel}:{lineno}: broken link '{target}' resolves outside root")
                    continue

                probe_keys = [rel_target]
                if had_trailing_slash and not rel_target.endswith("/"):
                    probe_keys.append(rel_target + "/")
                pending_missing.append((md_rel, lineno, target, rel_target, probe_keys))

    all_probes = [k for _, _, _, _, keys in pending_missing for k in keys]
    ignored_probes = _git_ignored_batch(root_resolved, all_probes)

    warnings: list[str] = []
    for md_rel, lineno, target, rel_target, probe_keys in pending_missing:
        if any(k in ignored_probes for k in probe_keys):
            warnings.append(f"{md_rel}:{lineno}: link '{target}' points to gitignored path '{rel_target}'")
        else:
            failures.append(f"{md_rel}:{lineno}: broken relative link '{target}' (missing '{rel_target}')")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} broken markdown link(s) across {len(md_files)} file(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"scanned {len(md_files)} file(s), {total_links} link(s); 0 broken, {len(warnings)} gitignored target(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(md_files)} file(s), {total_links} internal link(s); 0 broken",
    )


def _load_json_file(path: Path, rel_label: str, failures: list[str]) -> Any:
    if not path.is_file():
        failures.append(f"missing required JSON artifact: {rel_label}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"invalid or unreadable JSON in {rel_label}: {exc}")
        return None


def _find_paired_row(
    rows: list[dict[str, Any]],
    group: str,
    tier: str,
    primary: bool = True,
    agent: str | None = None,
) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("group") != group or row.get("tier") != tier:
            continue
        if agent is not None and row.get("agent") != agent:
            continue
        label_lower = str(row.get("label", "")).lower()
        is_alt = "alternative" in label_lower or "not the headline" in label_lower
        if primary and is_alt:
            continue
        return row
    return None


def _pct(val: Any) -> str:
    return f"{float(val) * 100.0:.0f}%"


def _has_token(text: str, tok: str) -> bool:
    pattern = r"(?<![0-9])(?<!\d\.)" + re.escape(tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _require_tokens(text: str, doc_label: str, items: list[tuple[str, str]], failures: list[str]) -> None:
    for desc, tok in items:
        if not _has_token(text, tok):
            failures.append(f"{doc_label} missing {desc} '{tok}'")


def _normalize_doc_text(text: str) -> str:
    norm = (
        text.replace("\u00b1", "+/-")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return norm.replace("**", "").replace("`", "")


def _has_pos_number(text: str, abs_tok: str) -> bool:
    pattern = r"(?<![0-9\-\u2212])(?<!\d\.)\+?" + re.escape(abs_tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _has_pm_ci(text: str, ci_tok: str) -> bool:
    pattern = r"\+/-\s*" + re.escape(ci_tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _has_int_count(text: str, val: int) -> bool:
    for cand in {str(val), f"{val:,}"}:
        pattern = r"(?<![0-9])(?<!\d\.)(?<!\d,)" + re.escape(cand) + r"(?![0-9])(?!\.\d)(?!,\d)"
        if re.search(pattern, text) is not None:
            return True
    return False


def _check_panel_fix_a_honesty(norm_text: str, doc_label: str, failures: list[str]) -> None:
    m_prereg = FALSE_PREREG_0_29_RX.search(norm_text)
    if m_prereg:
        failures.append(
            f"{doc_label} falsely claims dev seeds 0-29 / primary n=30 were pre-registered ('{m_prereg.group(0)}')"
        )
    m_bar = FALSE_TIEBREAK_BAR_MET_RX.search(norm_text)
    if m_bar:
        failures.append(
            f"{doc_label} falsely claims WS4 tiebreak bar is met ('{m_bar.group(0)}')"
        )


def check_headline_numbers(root: Path) -> CheckResult:
    name = "Headline Number Provenance"
    failures: list[str] = []

    paired_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    fa_rel = "results/failure_analysis_v1.4.json"
    oracle_rel = "results/oracle_range_v1.4.json"
    gd1_rel = "results/solver_range/guess_day1_hard_judge40.json"

    paired_data = _load_json_file(root / paired_rel, paired_rel, failures)
    fa_data = _load_json_file(root / fa_rel, fa_rel, failures)
    oracle_data = _load_json_file(root / oracle_rel, oracle_rel, failures)
    gd1_data = _load_json_file(root / gd1_rel, gd1_rel, failures)

    readme_path = root / "README.md"
    gap_path = root / "docs" / "reports" / "gap.md"
    fa_md_path = root / "docs" / "reports" / "failure_analysis_v1.4.md"
    walkthrough_path = root / "docs" / "JUDGE-WALKTHROUGH.md"

    for rel_doc, doc_path in (
        ("README.md", readme_path),
        ("docs/reports/gap.md", gap_path),
        ("docs/reports/failure_analysis_v1.4.md", fa_md_path),
    ):
        if not doc_path.is_file():
            failures.append(f"missing required headline document: {rel_doc}")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} missing/invalid headline input(s)", failures)

    if not isinstance(paired_data, list):
        return CheckResult(name, "FAIL", f"{paired_rel} must contain a JSON list", [f"{paired_rel}: not a list"])
    if not isinstance(fa_data, dict) or not isinstance(fa_data.get("summary"), dict):
        return CheckResult(name, "FAIL", f"{fa_rel} missing 'summary' object", [f"{fa_rel}: missing summary"])
    if not isinstance(oracle_data, dict) or not isinstance(oracle_data.get("rows"), list):
        return CheckResult(name, "FAIL", f"{oracle_rel} missing 'rows' list", [f"{oracle_rel}: missing rows"])
    if not isinstance(gd1_data, dict) or "mean" not in gd1_data:
        return CheckResult(name, "FAIL", f"{gd1_rel} missing 'mean' field", [f"{gd1_rel}: missing mean"])

    oc_hard = _find_paired_row(paired_data, "v1.4/opencode-gemini-4-carbon", "hard", primary=True)
    oc_med = _find_paired_row(paired_data, "v1.4/opencode-gemini-4-carbon", "medium", primary=True)
    ip_hard = _find_paired_row(paired_data, "v1.4/inproc-gemini-4-carbon", "hard", primary=True)
    sv_hard = _find_paired_row(paired_data, "v1.4/reference", "hard", primary=True, agent="solver")

    for row_label, row_obj in (
        ("OpenCode hard primary", oc_hard),
        ("OpenCode medium primary", oc_med),
        ("in-process hard", ip_hard),
        ("reference solver hard", sv_hard),
    ):
        if row_obj is None:
            failures.append(f"{paired_rel} missing {row_label} row")

    oracle_solver_hard = next(
        (
            r
            for r in oracle_data["rows"]
            if isinstance(r, dict) and r.get("agent") == "solver" and r.get("tier") == "hard"
        ),
        None,
    )
    if oracle_solver_hard is None or not isinstance(oracle_solver_hard.get("k10"), dict):
        failures.append(f"{oracle_rel} missing solver hard k10 entry")

    summary = fa_data["summary"]
    fa_oc = summary.get("opencode")
    fa_sv = summary.get("solver")
    fa_gap = summary.get("gap")
    if not isinstance(fa_oc, dict) or not isinstance(fa_sv, dict) or not isinstance(fa_gap, dict):
        failures.append(f"{fa_rel} summary missing opencode/solver/gap sections")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} schema mismatch(es) in headline JSONs", failures)

    assert oc_hard is not None and oc_med is not None and ip_hard is not None and sv_hard is not None
    assert oracle_solver_hard is not None
    assert isinstance(fa_oc, dict) and isinstance(fa_sv, dict) and isinstance(fa_gap, dict)

    try:
        oc_hard_n = int(oc_hard["n"])
        if oc_hard_n != 30:
            failures.append(f"{paired_rel}: OpenCode hard n expected 30, got {oc_hard_n}")

        oc_mean_pos = f"{float(oc_hard['mean']):+.3f}"
        oc_mean_abs = f"{float(oc_hard['mean']):.3f}"
        oc_ci = f"{float(oc_hard['ci']):.3f}"
        sv_same_pos = f"{float(oc_hard['solver_same_seeds']):+.3f}"
        sv_same_abs = f"{float(oc_hard['solver_same_seeds']):.3f}"
        sv_ci = f"{float(sv_hard['ci']):.3f}"

        if abs(float(sv_hard["mean"]) - float(oc_hard["solver_same_seeds"])) > 1e-6:
            failures.append(
                f"{paired_rel}: solver hard mean {sv_hard['mean']} != solver_same_seeds {oc_hard['solver_same_seeds']}"
            )

        oc_ratio = _pct(oc_hard["ratio"])
        oc_lo = _pct(oc_hard["ratio_lo"])
        oc_hi = _pct(oc_hard["ratio_hi"])
        oc_la_ratio = _pct(oc_hard["post_expected_ratio"])
        oc_la_lo = _pct(oc_hard["post_expected_lo"])
        oc_la_hi = _pct(oc_hard["post_expected_hi"])

        ip_ratio = _pct(ip_hard["ratio"])
        ip_lo = _pct(ip_hard["ratio_lo"])
        ip_hi = _pct(ip_hard["ratio_hi"])

        med_ratio = _pct(oc_med["ratio"])
        med_lo = _pct(oc_med["ratio_lo"])
        med_hi = _pct(oc_med["ratio_hi"])

        fa_oc_score = f"{float(fa_oc['score']):.3f}"
        fa_sv_score = f"{float(fa_sv['score']):.3f}"
        if fa_oc_score != oc_mean_abs:
            failures.append(
                f"cross-JSON drift: {fa_rel} opencode.score={fa_oc_score} vs {paired_rel} mean={oc_mean_abs}"
            )
        if fa_sv_score != sv_same_abs:
            failures.append(
                f"cross-JSON drift: {fa_rel} solver.score={fa_sv_score} vs {paired_rel} solver_same_seeds={sv_same_abs}"
            )

        fa_oc_canaries = f"{float(fa_oc['canaries']):.1f}"
        fa_sv_canaries = f"{float(fa_sv['canaries']):.1f}"
        fa_oc_accuse_day = f"{float(fa_oc['accuse_day']):.1f}"
        fa_sv_accuse_day = f"{float(fa_sv['accuse_day']):.1f}"
        fa_oc_wrong = str(int(fa_oc["wrong"]))
        fa_raw_gap = f"{float(fa_gap['raw_gap']):.2f}"
        fa_la_gap = f"{float(fa_gap['la_gap']):.2f}"

        k10 = oracle_solver_hard["k10"]
        or_mean = f"{float(k10['mean']):+.3f}"
        or_sd = f"{float(k10['sd']):.3f}"
        or_p5 = f"{float(k10['p5']):+.2f}"
        or_p95 = f"{float(k10['p95']):+.2f}"

        gd1_mean = float(gd1_data["mean"])
        if gd1_mean >= 0.0:
            failures.append(f"{gd1_rel}: expected negative guess_day1 mean, got {gd1_mean}")
        gd1_abs = f"{abs(gd1_mean):.2f}"
    except (KeyError, TypeError, ValueError) as exc:
        return CheckResult(name, "FAIL", f"malformed numeric field in headline JSONs: {exc}", [str(exc)])

    readme_txt = readme_path.read_text(encoding="utf-8", errors="replace")
    gap_txt = gap_path.read_text(encoding="utf-8", errors="replace")
    fa_md_txt = fa_md_path.read_text(encoding="utf-8", errors="replace")

    _require_tokens(
        readme_txt,
        "README.md",
        [
            ("OpenCode hard mean", oc_mean_pos),
            ("OpenCode hard CI", oc_ci),
            ("solver hard mean", sv_same_pos),
            ("solver hard CI", sv_ci),
            ("OpenCode hard raw ratio", oc_ratio),
            ("OpenCode hard luck-adjusted ratio", oc_la_ratio),
            ("in-process hard ratio", ip_ratio),
            ("OpenCode medium ratio", med_ratio),
            ("oracle k10 mean", or_mean),
            ("oracle k10 sd", or_sd),
            ("oracle k10 p5", or_p5),
            ("oracle k10 p95", or_p95),
        ],
        failures,
    )
    if not (_has_token(readme_txt, f"-{gd1_abs}") or _has_token(readme_txt, f"\u2212{gd1_abs}")):
        failures.append(f"README.md missing guess_day1 hard mean '-{gd1_abs}'")

    _require_tokens(
        gap_txt,
        "docs/reports/gap.md",
        [
            ("OpenCode hard raw ratio + CI", f"{oc_ratio} [{oc_lo}, {oc_hi}]"),
            ("OpenCode hard luck-adjusted ratio + CI", f"{oc_la_ratio} [{oc_la_lo}, {oc_la_hi}]"),
            ("in-process hard ratio + CI", f"{ip_ratio} [{ip_lo}, {ip_hi}]"),
            ("OpenCode medium ratio + CI", f"{med_ratio} [{med_lo}, {med_hi}]"),
        ],
        failures,
    )

    _require_tokens(
        fa_md_txt,
        "docs/reports/failure_analysis_v1.4.md",
        [
            ("OpenCode hard mean", oc_mean_abs),
            ("solver hard mean", sv_same_abs),
            ("OpenCode canaries", fa_oc_canaries),
            ("solver canaries", fa_sv_canaries),
            ("OpenCode accuse_day", fa_oc_accuse_day),
            ("solver accuse_day", fa_sv_accuse_day),
            ("OpenCode wrong count", fa_oc_wrong),
            ("raw_gap", fa_raw_gap),
            ("la_gap", fa_la_gap),
        ],
        failures,
    )

    checked_docs = ["README.md", "docs/reports/gap.md", "docs/reports/failure_analysis_v1.4.md"]
    readme_norm = _normalize_doc_text(readme_txt)
    _check_panel_fix_a_honesty(readme_norm, "README.md", failures)

    optional_headline_docs: tuple[tuple[str, Path], ...] = (
        ("docs/JUDGE-WALKTHROUGH.md", walkthrough_path),
        ("JUDGE_QUICKSTART.md", root / "JUDGE_QUICKSTART.md"),
        ("docs/REPRODUCIBILITY.md", root / "docs" / "REPRODUCIBILITY.md"),
        ("docs/PEER-REVIEW-QA.md", root / "docs" / "PEER-REVIEW-QA.md"),
        ("docs/SUBMISSION.md", root / "docs" / "SUBMISSION.md"),
    )
    loaded_optional_docs: dict[str, str] = {}
    for doc_rel, doc_path in optional_headline_docs:
        if not doc_path.is_file():
            continue
        checked_docs.append(doc_rel)
        raw_doc = doc_path.read_text(encoding="utf-8", errors="replace")
        norm_doc = _normalize_doc_text(raw_doc)
        loaded_optional_docs[doc_rel] = norm_doc
        _require_tokens(
            norm_doc,
            doc_rel,
            [
                ("OpenCode hard raw ratio", oc_ratio),
                ("OpenCode hard luck-adjusted ratio", oc_la_ratio),
            ],
            failures,
        )
        if not _has_pos_number(norm_doc, oc_mean_abs):
            failures.append(f"{doc_rel} missing OpenCode hard mean '{oc_mean_pos}' / '{oc_mean_abs}'")
        if not _has_pos_number(norm_doc, sv_same_abs):
            failures.append(f"{doc_rel} missing solver hard mean '{sv_same_pos}' / '{sv_same_abs}'")
        _check_panel_fix_a_honesty(norm_doc, doc_rel, failures)

    pooled_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    pooled_path = root / pooled_rel
    if pooled_path.is_file():
        pooled_data = _load_json_file(pooled_path, pooled_rel, failures)
        if not isinstance(pooled_data, list):
            failures.append(f"{pooled_rel}: expected JSON list")
        else:
            oc_pool = _find_paired_row(
                pooled_data,
                "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
                "hard",
                primary=True,
            )
            if oc_pool is None:
                oc_pool = next(
                    (
                        r
                        for r in pooled_data
                        if isinstance(r, dict)
                        and r.get("tier") == "hard"
                        and r.get("agent") == "opencode:google/gemini-4-carbon"
                        and "pooled" in str(r.get("label", "")).lower()
                    ),
                    None,
                )
            sv_pool = _find_paired_row(pooled_data, "v1.4/reference", "hard", primary=True, agent="solver")
            if oc_pool is None:
                failures.append(f"{pooled_rel} missing pooled hard OpenCode row")
            if sv_pool is None:
                failures.append(f"{pooled_rel} missing pooled hard reference solver row")
            if oc_pool is not None and sv_pool is not None:
                try:
                    oc_pool_n = int(oc_pool["n"])
                    sv_pool_n = int(sv_pool["n"])
                    if oc_pool_n != 32:
                        failures.append(f"{pooled_rel}: pooled OpenCode hard n expected 32, got {oc_pool_n}")
                    if sv_pool_n != 60:
                        failures.append(f"{pooled_rel}: pooled solver hard n expected 60, got {sv_pool_n}")
                    oc_pool_pos = f"{float(oc_pool['mean']):+.3f}"
                    oc_pool_abs = f"{float(oc_pool['mean']):.3f}"
                    oc_pool_ci = f"{float(oc_pool['ci']):.3f}"
                    sv_pool_pos = f"{float(sv_pool['mean']):+.3f}"
                    sv_pool_abs = f"{float(sv_pool['mean']):.3f}"
                    sv_pool_ci = f"{float(sv_pool['ci']):.3f}"
                except (KeyError, TypeError, ValueError) as exc:
                    failures.append(f"{pooled_rel}: malformed pooled numeric field ({exc})")
                else:
                    pooled_targets: list[tuple[str, str]] = [("README.md", readme_norm)]
                    for opt_rel in ("JUDGE_QUICKSTART.md", "docs/PEER-REVIEW-QA.md"):
                        if opt_rel in loaded_optional_docs:
                            pooled_targets.append((opt_rel, loaded_optional_docs[opt_rel]))
                    repro_norm = loaded_optional_docs.get("docs/REPRODUCIBILITY.md")
                    if repro_norm is not None and POOLED_MENTION_RX.search(repro_norm):
                        pooled_targets.append(("docs/REPRODUCIBILITY.md", repro_norm))

                    for target_rel, target_norm in pooled_targets:
                        if not _has_int_count(target_norm, oc_pool_n):
                            failures.append(f"{target_rel} missing pooled OpenCode n='{oc_pool_n}'")
                        if not _has_pos_number(target_norm, oc_pool_abs):
                            failures.append(
                                f"{target_rel} missing pooled OpenCode hard mean '{oc_pool_pos}' / '{oc_pool_abs}'"
                            )
                        if not _has_pm_ci(target_norm, oc_pool_ci):
                            failures.append(f"{target_rel} missing pooled OpenCode hard CI '+/- {oc_pool_ci}'")
                        if not _has_int_count(target_norm, sv_pool_n):
                            failures.append(f"{target_rel} missing pooled solver n='{sv_pool_n}'")
                        if not _has_pos_number(target_norm, sv_pool_abs):
                            failures.append(
                                f"{target_rel} missing pooled solver hard mean '{sv_pool_pos}' / '{sv_pool_abs}'"
                            )
                        if not _has_pm_ci(target_norm, sv_pool_ci):
                            failures.append(f"{target_rel} missing pooled solver hard CI '+/- {sv_pool_ci}'")

    exploits_rel = "results/anticheat/exploits.json"
    exploits_path = root / exploits_rel
    if exploits_path.is_file():
        exploits_data = _load_json_file(exploits_path, exploits_rel, failures)
        if not isinstance(exploits_data, dict):
            failures.append(f"{exploits_rel}: expected JSON object")
        else:
            rc_obj = exploits_data.get("replay_counts")
            harbor_list = exploits_data.get("harbor")
            rows_list = exploits_data.get("rows")
            if not isinstance(rc_obj, dict) or not isinstance(harbor_list, list) or not isinstance(rows_list, list):
                failures.append(f"{exploits_rel}: missing replay_counts/harbor/rows sections")
            else:
                try:
                    replayed_cnt = int(rc_obj["replayed"])
                    consistent_cnt = int(rc_obj["consistent"])
                    total_eps_cnt = int(rc_obj["n"])
                    steps_cnt = int(rc_obj["steps"])
                    harbor_trials_cnt = sum(
                        1 for item in harbor_list if isinstance(item, dict) and item.get("kind") == "trial"
                    )
                    harbor_jobs_cnt = sum(
                        1 for item in harbor_list if isinstance(item, dict) and item.get("kind") == "job"
                    )
                    battery_rows_cnt = len(rows_list)
                except (KeyError, TypeError, ValueError) as exc:
                    failures.append(f"{exploits_rel}: malformed count field ({exc})")
                else:
                    if consistent_cnt != replayed_cnt or exploits_data.get("replay_all_consistent") is not True:
                        failures.append(
                            f"{exploits_rel}: replay consistency failed (consistent={consistent_cnt}, replayed={replayed_cnt})"
                        )
                    if exploits_data.get("harbor_all_consistent") is not True:
                        failures.append(f"{exploits_rel}: harbor_all_consistent is not true")
                    if exploits_data.get("all_blocked") is not True:
                        failures.append(f"{exploits_rel}: all_blocked is not true")

                    count_specs = [
                        ("replayed episodes count", replayed_cnt),
                        ("total committed episodes count", total_eps_cnt),
                        ("replayed tool steps count", steps_cnt),
                        ("Harbor trials count", harbor_trials_cnt),
                        ("Harbor job summaries count", harbor_jobs_cnt),
                        ("anti-cheat battery rows count", battery_rows_cnt),
                    ]
                    for exp_doc_rel in ("docs/REPRODUCIBILITY.md", "docs/PEER-REVIEW-QA.md"):
                        exp_norm = loaded_optional_docs.get(exp_doc_rel)
                        if exp_norm is None:
                            continue
                        for desc, cnt_val in count_specs:
                            if not _has_int_count(exp_norm, cnt_val):
                                failures.append(
                                    f"{exp_doc_rel} missing {desc} '{cnt_val}' (or '{cnt_val:,}') from {exploits_rel}"
                                )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} headline number provenance drift(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {oc_ratio} [{oc_lo}, {oc_hi}] (luck-adj {oc_la_ratio} [{oc_la_lo}, {oc_la_hi}]), "
        f"{oc_mean_pos} vs {sv_same_pos} across {len(checked_docs)} doc(s)",
    )


def _is_exempt_gap_archive(rel_path: str) -> bool:
    return any(fnmatch.fnmatch(rel_path, pat) for pat in EXEMPT_GAP_PATTERNS)


def check_stale_gap_claims(root: Path) -> CheckResult:
    name = "Stale Gap-Claim Guard"
    failures: list[str] = []
    warnings: list[str] = []
    active_scanned = 0

    for rel in ACTIVE_HEADLINE_DOCS:
        fp = root / rel
        if not fp.is_file():
            continue
        active_scanned += 1
        txt = fp.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(txt.splitlines(), 1):
            m = STALE_GAP_RX.search(line)
            if m:
                failures.append(f"{rel}:{lineno}: stale gap claim '{m.group(0)}' in active headline doc")

    if active_scanned == 0:
        return CheckResult(name, "FAIL", "no active headline docs found to scan")

    secondary_candidates: list[str] = list(SECONDARY_GAP_DOCS)
    for sub in ("docs", "results"):
        sub_dir = root / sub
        if not sub_dir.is_dir():
            continue
        for p in sorted(sub_dir.rglob("*.md")):
            if sub == "results" and "latest" in p.relative_to(sub_dir).parts:
                continue
            rel = p.relative_to(root).as_posix()
            if rel not in ACTIVE_HEADLINE_DOCS and rel not in secondary_candidates:
                secondary_candidates.append(rel)

    for rel in secondary_candidates:
        if _is_exempt_gap_archive(rel):
            continue
        fp = root / rel
        if not fp.is_file():
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(txt.splitlines(), 1):
            m = STALE_GAP_RX.search(line)
            if m:
                warnings.append(f"{rel}:{lineno}: stale gap claim '{m.group(0)}' in secondary doc")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} stale gap claim(s) found in active headline doc(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"0 stale claims in {active_scanned} active doc(s); {len(warnings)} advisory match(es) in secondary doc(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 stale gap claims across {active_scanned} active headline doc(s) and secondary docs",
    )


def _is_numeric_ratio_cell(val: str) -> bool:
    cleaned = val.strip()
    if not cleaned:
        return False
    norm = cleaned.replace("\u2212", "-").rstrip("%").strip()
    try:
        num = float(norm)
        if math.isfinite(num):
            return True
    except ValueError:
        pass
    return re.search(r"\d", cleaned) is not None


def _audit_judge_table(judge_table_path: Path, failures: list[str]) -> None:
    text = judge_table_path.read_text(encoding="utf-8", errors="replace")
    current_tier: str | None = None
    headers: list[str] | None = None
    paired_scores: dict[tuple[str, str], list[tuple[int, str]]] = {}

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        heading_match = TIER_HEADING_RX.match(stripped)
        if heading_match:
            current_tier = heading_match.group(1).lower()
            headers = None
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue

        raw_inner = stripped[1:-1]
        if headers is None:
            cells = [c.strip() for c in raw_inner.split("|")]
            if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
                continue
            headers = [c.lower() for c in cells]
            continue

        raw_cells = [c.strip() for c in raw_inner.split("|", max(0, len(headers) - 1))]
        if raw_cells and all(TABLE_SEP_CELL_RX.match(c) for c in raw_cells if c):
            continue
        if len(raw_cells) < len(headers):
            raw_cells.extend([""] * (len(headers) - len(raw_cells)))

        row = dict(zip(headers, raw_cells))
        agent = row.get("agent", "")
        kind = row.get("kind", "").lower()
        score_col = next((v for k, v in row.items() if k.startswith("score")), "")
        solver_col = row.get("/ solver", "")

        if kind == "reported":
            if _is_numeric_ratio_cell(solver_col):
                failures.append(
                    f"results/judge_table.md:{lineno}: reported row '{agent}' has numeric '/ solver' value '{solver_col}'"
                )
        elif current_tier in {"easy", "medium", "hard"} and agent in {"do_nothing", "stop_early"}:
            paired_scores.setdefault((current_tier, agent), []).append((lineno, score_col))

    for tier in ("medium", "hard", "easy"):
        for baseline in ("do_nothing", "stop_early"):
            entries = paired_scores.get((tier, baseline), [])
            if not entries:
                failures.append(f"results/judge_table.md: missing paired '{baseline}' row in tier '{tier}'")
                continue
            for lineno, score_col in entries:
                mean_tok = score_col.split()[0] if score_col.split() else ""
                if mean_tok != "+0.000":
                    failures.append(
                        f"results/judge_table.md:{lineno}: paired '{baseline}' on '{tier}' expected '+0.000', got '{score_col}'"
                    )


def check_results_hygiene(root: Path) -> CheckResult:
    name = "Results & Judge Table Hygiene"
    failures: list[str] = []

    if _has_dot_git(root):
        tracked = _git_ls_files(root)
        if tracked is None:
            failures.append("git ls-files failed")
        else:
            for rel in tracked:
                if rel == "results/latest" or rel.startswith("results/latest/"):
                    failures.append(f"git-tracked file under results/latest/: {rel}")
        if not _git_is_ignored(root, "results/latest/judge_table.md"):
            failures.append("results/latest/judge_table.md is not gitignored")
    elif (root / ".gitignore").is_file():
        if not _git_is_ignored(root, "results/latest/judge_table.md"):
            failures.append("results/latest/judge_table.md is not gitignored")

    results_dir = root / "results"
    if not results_dir.is_dir():
        failures.append("missing results/ directory")
    else:
        for child in sorted(results_dir.iterdir()):
            if not child.is_file():
                continue
            if any(fnmatch.fnmatch(child.name, pat) for pat in LEGACY_RESULTS_PATTERNS):
                failures.append(
                    f"legacy artifact in top-level results/ (must be in results/history/): results/{child.name}"
                )

    for agent in ("solver", "guess_day1"):
        for tier in ("easy", "medium", "hard"):
            rel_sr = f"results/solver_range/{agent}_{tier}_judge40.json"
            sr_path = root / rel_sr
            if not sr_path.is_file():
                failures.append(f"missing solver_range file: {rel_sr}")
                continue
            try:
                sr_obj = json.loads(sr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                failures.append(f"invalid JSON in {rel_sr}: {exc}")
                continue
            builds = sr_obj.get("builds") if isinstance(sr_obj, dict) else None
            if not isinstance(builds, (int, float)) or isinstance(builds, bool) or builds < 100:
                failures.append(f"{rel_sr}: expected builds >= 100, got {builds!r}")

    judge_table_path = root / "results" / "judge_table.md"
    if not judge_table_path.is_file():
        failures.append("missing results/judge_table.md")
    else:
        _audit_judge_table(judge_table_path, failures)

    af_steps_path = root / FRESH_CLONE_AF_STEPS_REL
    af_log_path = root / FRESH_CLONE_AF_LOG_REL
    if af_steps_path.is_file() or af_log_path.is_file():
        if not af_steps_path.is_file():
            failures.append(f"missing fresh-clone steps file: {FRESH_CLONE_AF_STEPS_REL}")
        else:
            steps_txt = af_steps_path.read_text(encoding="utf-8", errors="replace")
            step_lines = [ln.strip() for ln in steps_txt.splitlines() if ln.strip()]
            if not step_lines:
                failures.append(f"empty fresh-clone steps file: {FRESH_CLONE_AF_STEPS_REL}")
            else:
                for idx, step_ln in enumerate(step_lines, 1):
                    m_exit = STEP_EXIT_RX.search(step_ln)
                    if m_exit is None:
                        failures.append(
                            f"{FRESH_CLONE_AF_STEPS_REL}:{idx}: missing exit=<int> in '{step_ln}'"
                        )
                    elif int(m_exit.group(1)) != 0:
                        failures.append(
                            f"{FRESH_CLONE_AF_STEPS_REL}:{idx}: non-zero exit code {m_exit.group(1)} in '{step_ln}'"
                        )

        if not af_log_path.is_file():
            failures.append(f"missing fresh-clone log file: {FRESH_CLONE_AF_LOG_REL}")
        else:
            log_txt = af_log_path.read_text(encoding="utf-8", errors="replace")
            if not log_txt.strip():
                failures.append(f"empty fresh-clone log file: {FRESH_CLONE_AF_LOG_REL}")

        fc_readme_path = root / FRESH_CLONE_README_REL
        if fc_readme_path.is_file():
            fc_readme_txt = fc_readme_path.read_text(encoding="utf-8", errors="replace")
            if "1bc3e281" not in fc_readme_txt:
                failures.append(f"{FRESH_CLONE_README_REL} missing commit citation '1bc3e281'")
            if "afterquery-final" not in fc_readme_txt:
                failures.append(f"{FRESH_CLONE_README_REL} missing tag citation 'afterquery-final'")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} results/judge_table hygiene violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        "results/latest gitignored and untracked, 0 top-level legacy files, 6 solver_range files (builds>=100), judge_table baselines & reported ratios clean",
    )


def audit_craft_consistency(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    return [
        check_markdown_links(resolved),
        check_headline_numbers(resolved),
        check_stale_gap_claims(resolved),
        check_results_hygiene(resolved),
    ]


audit_repo = audit_craft_consistency


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
    ap = argparse.ArgumentParser(description="Automated craft consistency and provenance guard for Canary.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to check")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = audit_craft_consistency(root=args.root.resolve())
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
