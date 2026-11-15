from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_doc_commands as verify_doc_commands

README_REL = "README.md"
README_PATH = ROOT / README_REL
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)
ACCEPT_K_SD = 4.0

FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
HTML_COMMENT_RX = re.compile(r"<!--[\s\S]*?-->")
INLINE_CODE_RX = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
ATX_HEADING_RX = re.compile(r"^\s{0,3}\x23{1,6}(?:[ \t]+(.*?))?(?:[ \t]+\x23+[ \t]*)?$")
HEADING_MD_LINK_RX = re.compile(r"!?\[([^\[\]]*)\]\([^)]*\)")
HTML_TAG_RX = re.compile(r"<[^>]+>")
SLUG_STRIP_PUNCT_RX = re.compile(r"[^\w\s-]")
EXPLICIT_HTML_ID_RX = re.compile(
    r"<[A-Za-z][^>]*?\b(?:id|name)\s*=\s*(?:\"([^\"]+)\"|'([^']+)')",
    re.IGNORECASE,
)
MD_IMAGE_RX = re.compile(
    r"!\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
MD_PLAIN_LINK_RX = re.compile(
    r"(?<!!)\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")
TIER_HEADING_RX = re.compile(r"^\x23\x23\s+(easy|medium|hard)\b", re.IGNORECASE)
STALE_GAP_RX = re.compile(r"gap\s*(?:is\s+|:\s*)?not\s+established", re.IGNORECASE)
SOLVER_PM_RX = re.compile(r"([+-]\d+\.\d{3})\s*\+/-\s*(\d+\.\d{3})")

STALE_PR41_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("51-attacker", re.compile(r"(?<![0-9])51[*_`]*[-\s]+[*_`]*attacker\b", re.IGNORECASE)),
    ("51-agent swarm", re.compile(r"(?<![0-9])51[*_`]*[-\s]+[*_`]*agent[*_`]*\s+[*_`]*swarm\b", re.IGNORECASE)),
    ("35 whitebox", re.compile(r"(?<![0-9.,])35[*_`]*[-\s]+[*_`]*whitebox\b", re.IGNORECASE)),
    ("1,789 tool calls", re.compile(r"(?<![0-9])1,?789[*_`]*\s+[*_`]*tool\s+calls?\b", re.IGNORECASE)),
    (
        "68% of solver luck-adjusted",
        re.compile(
            r"(?<![0-9.])68%[*_`]*\s+of\s+(?:the\s+)?solver[*_`]*[\s,()]*luck[-\s]+adjusted\b",
            re.IGNORECASE,
        ),
    ),
)


@pytest.fixture()
def clean_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-readme-claims-") as tmp_dir:
        yield Path(tmp_dir)


def _normalize_typography(text: str) -> str:
    out = text.replace(PLUS_MINUS, "+/-")
    out = out.replace(MINUS_SIGN, "-")
    out = out.replace(EN_DASH, "-")
    out = out.replace(EM_DASH, "-")
    return out


def _strip_bold_and_code(text: str) -> str:
    return text.replace("**", "").replace("`", "")


def _pct(val: Any) -> str:
    return f"{float(val) * 100.0:.0f}%"


def _has_token(text: str, tok: str) -> bool:
    pattern = r"(?<![0-9])(?<!\d\.)" + re.escape(tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _strip_fences_and_comments(md_text: str) -> str:
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
            cleaned_lines.append(raw_line)
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            cleaned_lines.append("")
    joined = "\n".join(cleaned_lines)
    return HTML_COMMENT_RX.sub(lambda match: "\n" * match.group(0).count("\n"), joined)


def _strip_code_preserving_lines(md_text: str) -> list[str]:
    without_fences = _strip_fences_and_comments(md_text)
    return [INLINE_CODE_RX.sub("", line) for line in without_fences.split("\n")]


def _slugify_github_heading(raw_heading: str) -> str:
    txt = HEADING_MD_LINK_RX.sub(r"\1", raw_heading)
    txt = HTML_TAG_RX.sub("", txt)
    txt = txt.strip().lower()
    txt = SLUG_STRIP_PUNCT_RX.sub("", txt)
    return re.sub(r"[ \t]", "-", txt)


def _extract_heading_slugs(md_text: str) -> set[str]:
    cleaned = _strip_fences_and_comments(md_text)
    counts: dict[str, int] = {}
    used: set[str] = set()
    for line in cleaned.split("\n"):
        atx = ATX_HEADING_RX.match(line)
        if not atx:
            continue
        base = _slugify_github_heading(atx.group(1) or "")
        if not base:
            continue
        idx = counts.get(base, 0)
        candidate = base if idx == 0 else f"{base}-{idx}"
        while candidate in used:
            idx += 1
            candidate = f"{base}-{idx}"
        counts[base] = idx + 1
        used.add(candidate)
    for m in EXPLICIT_HTML_ID_RX.finditer(cleaned):
        anchor_id = (m.group(1) or m.group(2) or "").strip()
        if anchor_id:
            used.add(anchor_id)
    return used


def _parse_md_dest(angle_group: str | None, paren_group: str | None) -> str:
    if angle_group is not None:
        return angle_group.strip()
    raw = (paren_group or "").strip()
    if not raw:
        return ""
    return raw.split()[0].strip()


def _is_external_target(target: str) -> bool:
    lower = target.lower()
    return lower.startswith(("http://", "https://", "mailto:", "tel:", "data:", "//"))


def _git_tracked_sets(root: Path) -> tuple[set[str], set[str]] | None:
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
    files = {entry for entry in proc.stdout.decode("utf-8", errors="replace").split("\0") if entry}
    dirs: set[str] = set()
    for entry in files:
        parts = entry.split("/")
        for idx in range(1, len(parts)):
            dirs.add("/".join(parts[:idx]))
    return files, dirs


def check_readme_links_and_anchors(root: Path) -> tuple[list[str], set[str], set[str]]:
    root_resolved = root.resolve()
    readme_file = root_resolved / README_REL
    if not readme_file.is_file():
        return [f"missing {README_REL}"], set(), set()

    text = readme_file.read_text(encoding="utf-8")
    failures: list[str] = []
    resolved_targets: set[str] = set()
    verified_anchors: set[str] = set()
    tracked_info = _git_tracked_sets(root_resolved)
    slug_cache: dict[Path, set[str]] = {}

    for lineno, line in enumerate(_strip_code_preserving_lines(text), 1):
        if "(" not in line or "[" not in line:
            continue
        raw_targets: list[tuple[str, str]] = []
        for img_m in MD_IMAGE_RX.finditer(line):
            raw_targets.append(("img", _parse_md_dest(img_m.group(1), img_m.group(2))))
        line_no_imgs = MD_IMAGE_RX.sub("img", line)
        for link_m in MD_PLAIN_LINK_RX.finditer(line_no_imgs):
            raw_targets.append(("link", _parse_md_dest(link_m.group(1), link_m.group(2))))

        for kind, target in raw_targets:
            if not target:
                failures.append(f"README.md:{lineno}: empty {kind} target")
                continue
            if _is_external_target(target):
                continue

            has_hash = HASH_CHAR in target
            path_raw, frag_raw = target.split(HASH_CHAR, 1) if has_hash else (target, "")
            path_part = unquote(path_raw.split("?", 1)[0]).strip()
            frag = unquote(frag_raw).strip()

            if has_hash and not frag:
                failures.append(f"README.md:{lineno}: empty anchor fragment in '{target}'")
                continue

            if not path_part:
                resolved = readme_file
                rel_target = README_REL
                had_trailing_slash = False
            else:
                had_trailing_slash = path_part.endswith("/")
                resolved = (readme_file.parent / path_part).resolve()
                try:
                    rel_target = resolved.relative_to(root_resolved).as_posix()
                except ValueError:
                    failures.append(f"README.md:{lineno}: target '{target}' resolves outside root")
                    continue

            if had_trailing_slash:
                if not resolved.is_dir():
                    failures.append(f"README.md:{lineno}: directory link '{target}' missing '{rel_target}'")
                    continue
            elif not resolved.exists():
                failures.append(f"README.md:{lineno}: broken link '{target}' (missing '{rel_target}')")
                continue

            if tracked_info is not None and path_part:
                tracked_files, tracked_dirs = tracked_info
                if resolved.is_dir():
                    if rel_target not in tracked_dirs:
                        failures.append(f"README.md:{lineno}: directory target '{rel_target}' is not git-tracked")
                        continue
                elif rel_target not in tracked_files:
                    failures.append(f"README.md:{lineno}: file target '{rel_target}' is not git-tracked")
                    continue

            resolved_targets.add(rel_target + ("/" if had_trailing_slash else ""))

            if has_hash:
                if not resolved.is_file() or resolved.suffix.lower() not in {".md", ".markdown"}:
                    failures.append(f"README.md:{lineno}: unsupported anchor target '{target}'")
                    continue
                if resolved not in slug_cache:
                    slug_cache[resolved] = _extract_heading_slugs(resolved.read_text(encoding="utf-8"))
                if frag not in slug_cache[resolved]:
                    failures.append(
                        f"README.md:{lineno}: broken anchor '{target}' (missing slug '{frag}' in {rel_target})"
                    )
                    continue
                verified_anchors.add(f"{rel_target}{HASH_CHAR}{frag}")

    return failures, resolved_targets, verified_anchors


def _find_paired_row(
    rows: list[dict[str, Any]],
    group: str,
    tier: str,
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
        if "alternative" in label_lower or "not the headline" in label_lower:
            continue
        return row
    return None


def _parse_readme_result_table(readme_text: str) -> list[dict[str, str]]:
    lines = readme_text.splitlines()
    in_result = False
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith(HASH_CHAR * 2 + " "):
            if "Result (rules v1.4, hard tier)" in stripped:
                in_result = True
                headers = None
                continue
            if in_result:
                break
        if not in_result:
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            if headers is not None and rows:
                break
            continue
        cells = [_strip_bold_and_code(_normalize_typography(c.strip())) for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [c.lower() for c in cells]
            continue
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        rows.append(dict(zip(headers, cells)))
    return rows


def _parse_judge_table_rows(judge_table_text: str) -> dict[tuple[str, str, str], dict[str, str]]:
    current_tier: str | None = None
    headers: list[str] | None = None
    indexed: dict[tuple[str, str, str], dict[str, str]] = {}
    for raw_line in judge_table_text.splitlines():
        stripped = raw_line.strip()
        m_tier = TIER_HEADING_RX.match(stripped)
        if m_tier:
            current_tier = m_tier.group(1).lower()
            headers = None
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [_normalize_typography(c.strip()) for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [c.lower() for c in cells]
            continue
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        row = dict(zip(headers, cells))
        if current_tier is not None:
            key = (current_tier, row.get("kind", "").lower(), row.get("agent", ""))
            if key not in indexed:
                indexed[key] = row
    return indexed


def check_readme_numbers_and_bands(root: Path) -> list[str]:
    failures: list[str] = []
    root_resolved = root.resolve()
    readme_file = root_resolved / README_REL
    if not readme_file.is_file():
        return [f"missing {README_REL}"]

    required_files = {
        "paired": root_resolved / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json",
        "oracle": root_resolved / "results" / "oracle_range_v1.4.json",
        "gd1": root_resolved / "results" / "solver_range" / "guess_day1_hard_judge40.json",
        "solver_hard_sr": root_resolved / "results" / "solver_range" / "solver_hard_judge40.json",
        "judge_table": root_resolved / "results" / "judge_table.md",
    }
    for label, path in required_files.items():
        if not path.is_file():
            failures.append(f"missing required source file ({label}): {path.relative_to(root_resolved).as_posix()}")
    if failures:
        return failures

    raw_readme = readme_file.read_text(encoding="utf-8")
    norm_readme = _strip_bold_and_code(_normalize_typography(raw_readme))

    for lineno, line in enumerate(raw_readme.splitlines(), 1):
        m_stale = STALE_GAP_RX.search(line)
        if m_stale:
            failures.append(f"README.md:{lineno}: stale gap claim '{m_stale.group(0)}'")
    for tok_label, rx in STALE_PR41_PATTERNS:
        m_pr41 = rx.search(raw_readme)
        if m_pr41:
            failures.append(f"README.md: stale pre-PR41 token '{tok_label}'")

    paired_rows = json.loads(required_files["paired"].read_text(encoding="utf-8"))
    oracle_data = json.loads(required_files["oracle"].read_text(encoding="utf-8"))
    gd1_data = json.loads(required_files["gd1"].read_text(encoding="utf-8"))
    solver_sr = json.loads(required_files["solver_hard_sr"].read_text(encoding="utf-8"))
    judge_rows = _parse_judge_table_rows(required_files["judge_table"].read_text(encoding="utf-8"))

    oc_hard = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    oc_med = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "medium")
    ip_hard = _find_paired_row(paired_rows, "v1.4/inproc-gemini-4-carbon", "hard")
    sv_hard = _find_paired_row(paired_rows, "v1.4/reference", "hard", agent="solver")
    if oc_hard is None or oc_med is None or ip_hard is None or sv_hard is None:
        return failures + ["paired_table_gemini.json missing required primary rows"]

    if int(oc_hard["n"]) != 30 or int(sv_hard["n"]) != 30:
        failures.append(f"paired hard n mismatch: oc={oc_hard['n']} sv={sv_hard['n']} (expected 30)")
    if oc_hard.get("seeds") != list(range(30)) or sv_hard.get("seeds") != list(range(30)):
        failures.append("paired hard seeds do not match dev seeds 0-29")

    sv_mean_ci = f"{float(sv_hard['mean']):+.3f} +/- {float(sv_hard['ci']):.3f}"
    oc_mean_ci = f"{float(oc_hard['mean']):+.3f} +/- {float(oc_hard['ci']):.3f}"
    oc_ratio = _pct(oc_hard["ratio"])
    oc_lo_num = f"{float(oc_hard['ratio_lo']) * 100.0:.0f}"
    oc_hi_pct = _pct(oc_hard["ratio_hi"])
    oc_raw_ci = f"{oc_ratio} [{_pct(oc_hard['ratio_lo'])}, {oc_hi_pct}]"
    oc_la_ci = (
        f"luck-adjusted {_pct(oc_hard['post_expected_ratio'])} "
        f"[{_pct(oc_hard['post_expected_lo'])}, {_pct(oc_hard['post_expected_hi'])}]"
    )
    ip_raw_ci = f"{_pct(ip_hard['ratio'])} [{_pct(ip_hard['ratio_lo'])}, {_pct(ip_hard['ratio_hi'])}]"
    med_ratio = _pct(oc_med["ratio"])

    oracle_solver = next(
        (r for r in oracle_data.get("rows", []) if r.get("agent") == "solver" and r.get("tier") == "hard"),
        None,
    )
    if oracle_solver is None:
        return failures + ["oracle_range_v1.4.json missing solver hard row"]
    k10 = oracle_solver["k10"]
    oracle_builds = int(oracle_solver["builds"])
    or_p5 = f"{float(k10['p5']):+.2f}"
    or_p95 = f"{float(k10['p95']):+.2f}"
    or_mean = f"{float(k10['mean']):+.3f}"
    or_sd = f"{float(k10['sd']):.3f}"

    for baseline_name in ("do_nothing", "stop_early"):
        b_or = next(
            (r for r in oracle_data.get("rows", []) if r.get("agent") == baseline_name and r.get("tier") == "hard"),
            None,
        )
        if b_or is None or abs(float(b_or["k10"]["mean"])) > 1e-12 or abs(float(b_or["k10"]["sd"])) > 1e-12:
            failures.append(f"oracle_range_v1.4.json {baseline_name} hard k10 must be 0.0")

    gd1_tok = f"-{abs(float(gd1_data['mean'])):.2f}"

    required_prose_tokens = [
        ("headline ratio", oc_ratio),
        ("top-line CI", f"95% CI {oc_lo_num}-{oc_hi_pct}"),
        ("solver hard mean +/- CI", sv_mean_ci),
        ("OpenCode hard mean +/- CI", oc_mean_ci),
        ("OpenCode hard raw ratio + CI", oc_raw_ci),
        ("OpenCode hard luck-adjusted ratio + CI", oc_la_ci),
        ("paired dev seeds 0-29", "0-29"),
        ("40 judge seeds", "40 judge seeds"),
        ("in-process hard ratio + CI", ip_raw_ci),
        ("OpenCode medium ratio", med_ratio),
        ("guess_day1 hard mean", gd1_tok),
        ("oracle k10 range", f"{or_p5} to {or_p95}"),
        ("oracle k10 mean", f"mean {or_mean}"),
        ("oracle k10 sd", f"sd {or_sd}"),
        ("oracle simulated builds", f"{oracle_builds} simulated builds"),
    ]
    for label, tok in required_prose_tokens:
        if not _has_token(norm_readme, tok):
            failures.append(f"README.md missing {label}: '{tok}'")

    table_rows = _parse_readme_result_table(raw_readme)
    if len(table_rows) != 4:
        failures.append(f"README.md result table expected 4 rows, found {len(table_rows)}")
    else:
        by_agent = {r.get("agent", ""): r for r in table_rows}
        sv_row = by_agent.get("reference solver")
        oc_row = by_agent.get("gemini-4-carbon, OpenCode over MCP")
        dn_row = by_agent.get("do_nothing")
        se_row = next((r for k, r in by_agent.items() if k.startswith("stop_early")), None)
        if sv_row is None or sv_row.get("score +/- 95% ci") != sv_mean_ci or sv_row.get("% of solver [95% ci]") != "100%" or sv_row.get("n") != "30":
            failures.append(f"README.md reference solver table row mismatch: {sv_row}")
        expected_oc_pct_col = f"{oc_raw_ci}; {oc_la_ci}"
        if oc_row is None or oc_row.get("score +/- 95% ci") != oc_mean_ci or oc_row.get("% of solver [95% ci]") != expected_oc_pct_col or oc_row.get("n") != "30":
            failures.append(f"README.md OpenCode table row mismatch: {oc_row}")
        if dn_row is None or dn_row.get("score +/- 95% ci") != "+0.000 +/- 0.000" or dn_row.get("% of solver [95% ci]") != "0%" or dn_row.get("n") != "40":
            failures.append(f"README.md do_nothing table row mismatch: {dn_row}")
        if se_row is None or se_row.get("score +/- 95% ci") != "+0.000 +/- 0.000" or se_row.get("% of solver [95% ci]") != "0%" or se_row.get("n") != "40":
            failures.append(f"README.md stop_early table row mismatch: {se_row}")

    for baseline_name in ("do_nothing", "stop_early"):
        jt_base = judge_rows.get(("hard", "baseline", baseline_name))
        if jt_base is None:
            failures.append(f"results/judge_table.md missing hard baseline '{baseline_name}'")
        else:
            score_cell = next((v for k, v in jt_base.items() if k.startswith("score")), "")
            if jt_base.get("n") != "40" or score_cell != "+0.000 +/- 0.000" or jt_base.get("/ solver") != "0.00":
                failures.append(f"results/judge_table.md hard '{baseline_name}' mismatch: {jt_base}")

    jt_oc = judge_rows.get(("hard", "reported", "opencode:google/gemini-4-carbon"))
    if jt_oc is None:
        failures.append("results/judge_table.md missing hard reported opencode:google/gemini-4-carbon")
    else:
        jt_oc_score = next((v for k, v in jt_oc.items() if k.startswith("score")), "")
        if jt_oc.get("n") != "30" or jt_oc_score != oc_mean_ci:
            failures.append(f"results/judge_table.md reported OpenCode hard mismatch: {jt_oc_score} vs {oc_mean_ci}")

    jt_sv_rep = judge_rows.get(("hard", "reported", "solver"))
    if jt_sv_rep is None:
        failures.append("results/judge_table.md missing hard reported solver")
    else:
        jt_sv_rep_score = next((v for k, v in jt_sv_rep.items() if k.startswith("score")), "")
        if jt_sv_rep.get("n") != "30" or jt_sv_rep_score != sv_mean_ci:
            failures.append(f"results/judge_table.md reported solver hard mismatch: {jt_sv_rep_score} vs {sv_mean_ci}")

    sr_builds = int(solver_sr["builds"])
    sr_mean = float(solver_sr["mean"])
    sr_sd = float(solver_sr["sd"])
    sr_min = float(solver_sr["min"])
    sr_max = float(solver_sr["max"])
    band_lo = sr_mean - ACCEPT_K_SD * sr_sd
    band_hi = sr_mean + ACCEPT_K_SD * sr_sd

    if not _has_token(norm_readme, f"{sr_builds} fresh secrets"):
        failures.append(f"README.md missing solver_range '{sr_builds} fresh secrets' token")

    variation_lines = [
        _strip_bold_and_code(_normalize_typography(ln))
        for ln in raw_readme.splitlines()
        if "Run-to-run variation" in ln
    ]
    if len(variation_lines) != 1:
        failures.append(f"README.md expected 1 'Run-to-run variation' bullet, found {len(variation_lines)}")
    else:
        var_line = variation_lines[0]
        matches = SOLVER_PM_RX.findall(var_line)
        if len(matches) < 2:
            failures.append(f"README.md Run-to-run variation expected >=2 solver mean+/-CI figures, got {matches}")
        for mean_str, _ci_str in matches:
            val = float(mean_str)
            if not (band_lo < val < band_hi):
                failures.append(
                    f"README.md Run-to-run solver value {mean_str} outside make-accept 4sd band ({band_lo:.4f}, {band_hi:.4f})"
                )
            if not (sr_min < val < sr_max):
                failures.append(
                    f"README.md Run-to-run solver value {mean_str} outside 300-secret min/max ({sr_min:.4f}, {sr_max:.4f})"
                )

        fresh_clone_readme = root_resolved / "results" / "fresh_clone" / "README.md"
        if fresh_clone_readme.is_file():
            fc_norm = _normalize_typography(fresh_clone_readme.read_text(encoding="utf-8"))
            second_mean, second_ci = matches[1] if len(matches) >= 2 else ("", "")
            if second_mean and not _has_token(fc_norm, f"{second_mean} +/- {second_ci}"):
                failures.append(
                    f"fresh-clone figure '{second_mean} +/- {second_ci}' in README.md not found in results/fresh_clone/README.md"
                )

    jt_sv_paired = judge_rows.get(("hard", "reference", "solver"))
    if jt_sv_paired is None:
        failures.append("results/judge_table.md missing paired hard reference solver row")
    else:
        paired_score_cell = next((v for k, v in jt_sv_paired.items() if k.startswith("score")), "")
        m_jt = SOLVER_PM_RX.search(paired_score_cell)
        if m_jt is None:
            failures.append(f"results/judge_table.md unparsable hard solver score '{paired_score_cell}'")
        else:
            jt_val = float(m_jt.group(1))
            if not (band_lo < jt_val < band_hi):
                failures.append(
                    f"results/judge_table.md hard solver {jt_val:+.3f} outside make-accept 4sd band ({band_lo:.4f}, {band_hi:.4f})"
                )
            if not (sr_min < jt_val < sr_max):
                failures.append(
                    f"results/judge_table.md hard solver {jt_val:+.3f} outside 300-secret min/max ({sr_min:.4f}, {sr_max:.4f})"
                )

    return failures


def audit_readme_claims(root: Path = ROOT) -> list[str]:
    link_failures, _, _ = check_readme_links_and_anchors(root)
    num_failures = check_readme_numbers_and_bands(root)
    return link_failures + num_failures


def test_self_source_hygiene_and_read_only_execution() -> None:
    src = SELF_PATH.read_text(encoding="utf-8")
    assert HASH_CHAR not in src, "unexpected hash character in test_readme_claims.py"
    assert EM_DASH not in src, "unexpected em dash in test_readme_claims.py"
    assert EN_DASH not in src, "unexpected en dash in test_readme_claims.py"
    non_ascii = [ch for ch in src if ord(ch) >= 128]
    assert not non_ascii, f"unexpected non-ASCII characters in test_readme_claims.py: {non_ascii[:5]}"

    assert README_PATH.is_file()
    before_sha = hashlib.sha256(README_PATH.read_bytes()).hexdigest()
    failures = audit_readme_claims(ROOT)
    after_sha = hashlib.sha256(README_PATH.read_bytes()).hexdigest()
    assert before_sha == after_sha, "audit_readme_claims must be 100% read-only on README.md"
    assert not failures, f"README.md claim/link/number audit failed: {failures}"


def test_readme_markdown_links_anchors_and_repo_map_paths() -> None:
    failures, resolved_targets, verified_anchors = check_readme_links_and_anchors(ROOT)
    assert not failures, f"README.md link/anchor failures: {failures}"

    expected_targets = {
        "docs/gemini/SUBMISSION.md",
        "data/runs/committed/v1.4/paired_table_gemini.md",
        "docs/reports/gap.md",
        "results/judge_table.md",
        "results/solver_range/guess_day1_hard_judge40.md",
        "results/solver_range/",
        "results/fresh_clone/",
        "harbor/README.md",
        "results/oracle_range_v1.4.md",
        "docs/EXPLOITS.md",
        "docs/CONTRACT.md",
        "docs/HISTORY.md",
        "canary/rules.py",
        "results/anticheat/exploits.md",
        "configs/README.md",
        "docs/PLAN.md",
        "docs/TEAM.md",
    }
    missing = sorted(expected_targets - resolved_targets)
    assert not missing, f"README.md missing expected internal link targets: {missing}"
    assert f"harbor/README.md{HASH_CHAR}expected-oracle-range-for-a-judge-rerun" in verified_anchors

    repo_map_paths = (
        "canary/env.py",
        "canary/rules.py",
        "canary/world.py",
        "canary/solver",
        "canary/baselines.py",
        "canary/mcp_server.py",
        "harbor",
        "canary/eval.py",
        "canary/reproduce.py",
        "canary/redteam",
        "canary/gemini",
        "configs/opencode/opencode.json",
    )
    for rel in repo_map_paths:
        assert (ROOT / rel).exists(), f"missing Repo-map path referenced in README.md: {rel}"


def test_readme_line34_solver_variation_and_acceptance_band_explicit() -> None:
    raw_readme = README_PATH.read_text(encoding="utf-8")
    norm_readme = _strip_bold_and_code(_normalize_typography(raw_readme))
    assert _has_token(norm_readme, "+0.625 +/- 0.088")
    assert _has_token(norm_readme, "+0.643 +/- 0.087")

    macos_log = ROOT / "results" / "fresh_clone" / "macos_justSilas_09e7363.log.txt"
    assert macos_log.is_file()
    assert _has_token(_normalize_typography(macos_log.read_text(encoding="utf-8")), "+0.643 +/- 0.087")

    solver_sr = json.loads((ROOT / "results" / "solver_range" / "solver_hard_judge40.json").read_text(encoding="utf-8"))
    assert solver_sr["agent"] == "solver"
    assert solver_sr["tier"] == "hard"
    assert int(solver_sr["builds"]) == 300
    assert solver_sr["seeds"] == [900000, 900039]

    band_lo = float(solver_sr["mean"]) - ACCEPT_K_SD * float(solver_sr["sd"])
    band_hi = float(solver_sr["mean"]) + ACCEPT_K_SD * float(solver_sr["sd"])
    sr_min = float(solver_sr["min"])
    sr_max = float(solver_sr["max"])

    judge_rows = _parse_judge_table_rows((ROOT / "results" / "judge_table.md").read_text(encoding="utf-8"))
    jt_sv = judge_rows[("hard", "reference", "solver")]
    score_cell = next(v for k, v in jt_sv.items() if k.startswith("score"))
    m_jt = SOLVER_PM_RX.search(score_cell)
    assert m_jt is not None
    committed_jt_hard = float(m_jt.group(1))

    for label, candidate in (
        ("README line 34 historical judge_table (+0.625)", 0.625),
        ("README line 34 macOS fresh_clone (+0.643)", 0.643),
        ("results/judge_table.md committed hard solver", committed_jt_hard),
    ):
        assert band_lo < candidate < band_hi, f"{label}={candidate} not inside 4sd band ({band_lo}, {band_hi})"
        assert sr_min < candidate < sr_max, f"{label}={candidate} not inside 300-secret min/max ({sr_min}, {sr_max})"


def test_readme_rules_mcp_reproduce_harbor_and_anticheat_parity() -> None:
    from canary import reproduce, rules
    from canary.env import Env

    norm_readme = _strip_bold_and_code(_normalize_typography(README_PATH.read_text(encoding="utf-8")))

    assert rules.TIERS_VERSION == "v1.4"
    assert rules.KNOWN_V_MODE is True
    assert f'TIERS_VERSION = "{rules.TIERS_VERSION}"' in README_PATH.read_text(encoding="utf-8")

    easy = rules.TIERS["easy"]
    med = rules.TIERS["medium"]
    hard = rules.TIERS["hard"]

    assert (easy.n_employees, easy.n_days, easy.canaries_per_day, easy.max_variants, easy.delay_choices) == (
        12,
        14,
        1,
        3,
        (1,),
    )
    assert (easy.decoy, easy.framing, easy.careful_mole, easy.access_constraints) == (False, False, False, False)

    assert (med.n_employees, med.n_days, med.canaries_per_day, med.max_variants, med.leak_damage, med.delay_choices) == (
        20,
        14,
        1,
        3,
        0.04,
        (1, 2, 3),
    )
    assert (med.decoy, med.framing, med.careful_mole, med.access_constraints) == (True, True, True, False)

    assert (
        hard.n_employees,
        hard.n_days,
        hard.canaries_per_day,
        hard.max_variants,
        hard.leak_damage,
        hard.fingerprint_accuracy,
        hard.delay_choices,
    ) == (40, 21, 2, 3, 0.05, 0.95, (2, 3))
    assert (hard.decoy, hard.framing, hard.careful_mole, hard.access_constraints) == (True, True, True, True)
    assert hard.wrong_accusation_score == -1.0

    assert easy.actions_per_day == med.actions_per_day == hard.actions_per_day == 8
    assert easy.tool_call_cap == med.tool_call_cap == 300
    assert hard.tool_call_cap == 420

    for rule_tok in (
        "12 employees, 14 days",
        "20 employees, 14 days",
        "0.04 of V",
        "40 employees, 21 days",
        "0.05 of V",
        "95% of the time",
        "1-3 days on medium",
        "2-3 days on hard",
        "8 investigative calls per day",
        "300 tool calls in total (420 on hard)",
    ):
        assert _has_token(norm_readme, rule_tok), f"README.md missing rule token '{rule_tok}'"

    assert len(rules.JUDGE_SEEDS) == 40
    assert list(rules.JUDGE_SEEDS)[0] == 900000 and list(rules.JUDGE_SEEDS)[-1] == 900039
    assert reproduce.REPRO_AGENTS[0] == "solver"
    assert len(reproduce.REPRO_AGENTS) - 1 == 6
    assert reproduce.FAST_SEEDS == 5
    assert reproduce.DEFAULT_RESULTS_DIR == "results/latest"

    tools = Env("easy", 0).tools_spec()
    assert len(tools) == 13
    assert _has_token(norm_readme, "with 13 tools")
    assert "http://127.0.0.1:8765/mcp" in norm_readme

    harbor_build_tree = ast.parse((ROOT / "harbor" / "build.py").read_text(encoding="utf-8"))
    harbor_consts: dict[str, Any] = {}
    for node in harbor_build_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant):
                harbor_consts[node.targets[0].id] = node.value.value
    assert harbor_consts.get("JUDGE_SET_TIERS") == "hard"
    assert harbor_consts.get("JUDGE_SET_SEEDS") == "900000-900009"
    assert "hard x judge seeds 900000-900009" in norm_readme

    exploits_json = json.loads((ROOT / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))
    assert exploits_json.get("all_blocked") is True
    replay_by_file = {item["file"]: item for item in exploits_json.get("replay", []) if isinstance(item, dict)}
    oc_hard_replay = replay_by_file.get("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl")
    assert oc_hard_replay is not None
    assert oc_hard_replay["n"] == 30
    assert oc_hard_replay["replayed"] == 30
    assert oc_hard_replay["consistent"] == 30
    assert oc_hard_replay["step_mismatches"] == 0
    assert oc_hard_replay["replay_consistent"] is True
    assert "ANTI-CHEAT: every probe blocked" in norm_readme


def test_readme_commands_pass_doc_command_verifier() -> None:
    results = verify_doc_commands.verify_repo(root=ROOT, docs=(README_REL,))
    assert len(results) == 3
    failed = [f"{r.name}: {r.status} ({r.details})" for r in results if r.status != "PASS"]
    assert not failed, f"verify_doc_commands failed on README.md: {failed}"


def _build_synthetic_repo(repo: Path) -> dict[str, Any]:
    paired = [
        {
            "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "medium",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.713,
            "ci": 0.042,
            "solver_same_seeds": 0.645,
            "ratio": 1.1054,
            "ratio_lo": 0.9933,
            "ratio_hi": 1.2698,
            "post_expected_ratio": 1.0106,
            "post_expected_lo": 0.8532,
            "post_expected_hi": 1.1864,
        },
        {
            "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.3223333333333333,
            "ci": 0.198895372190826,
            "solver_same_seeds": 0.499,
            "ratio": 0.6459585838343352,
            "ratio_lo": 0.23819591261451728,
            "ratio_hi": 0.9833962264150943,
            "post_expected_ratio": 0.7201029448090318,
            "post_expected_lo": 0.5173025973474353,
            "post_expected_hi": 0.9120622753852026,
        },
        {
            "label": "in-process gemini-4-carbon",
            "group": "v1.4/inproc-gemini-4-carbon",
            "agent": "gemini:gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.473,
            "ci": 0.118,
            "solver_same_seeds": 0.499,
            "ratio": 0.9479,
            "ratio_lo": 0.6221,
            "ratio_hi": 1.40,
            "post_expected_ratio": 0.8433,
            "post_expected_lo": 0.6499,
            "post_expected_hi": 1.0578,
        },
        {
            "label": "reference solver",
            "group": "v1.4/reference",
            "agent": "solver",
            "tier": "hard",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.499,
            "ci": 0.11929749210686914,
            "solver_same_seeds": 0.499,
            "ratio": 1.0,
        },
    ]
    oracle = {
        "rows": [
            {
                "agent": "solver",
                "tier": "hard",
                "builds": 200,
                "k10": {"mean": 0.56938, "sd": 0.0944689, "p5": 0.393, "p95": 0.67805},
            },
            {
                "agent": "do_nothing",
                "tier": "hard",
                "builds": 200,
                "k10": {"mean": 0.0, "sd": 0.0, "p5": 0.0, "p95": 0.0},
            },
            {
                "agent": "stop_early",
                "tier": "hard",
                "builds": 200,
                "k10": {"mean": 0.0, "sd": 0.0, "p5": 0.0, "p95": 0.0},
            },
        ]
    }
    gd1 = {"agent": "guess_day1", "tier": "hard", "builds": 300, "mean": -0.9528333333333333}
    solver_sr = {
        "agent": "solver",
        "tier": "hard",
        "seeds": [900000, 900039],
        "builds": 300,
        "mean": 0.5673808333333333,
        "sd": 0.049658080148676675,
        "min": 0.406,
        "max": 0.669,
    }
    judge_table = "\n".join(
        [
            f"{HASH_CHAR} Canary judge table",
            f"{HASH_CHAR}{HASH_CHAR} hard (headline)",
            "| agent | kind | n | invalid | score +/- 95% CI | / solver |",
            "|---|---|---:|---|---:|---:|",
            "| solver | reference | 40 | 0 | +0.655 +/- 0.032 | 1.00 |",
            "| stop_early | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 |",
            "| do_nothing | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 |",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | / solver |",
            "|---|---|---:|---|---:|---:|",
            "| opencode:google/gemini-4-carbon | reported | 30 | 0 | +0.322 +/- 0.199 | - |",
            "| solver | reported | 30 | 0 | +0.499 +/- 0.119 | - |",
        ]
    ) + "\n"
    readme = "\n".join(
        [
            f"{HASH_CHAR} Canary: catch the mole",
            f"Claim: gemini-4-carbon earns 65% of the reference solver on hard (95% CI 24{EN_DASH}98%).",
            f"{HASH_CHAR}{HASH_CHAR} Result (rules v1.4, hard tier)",
            f"| agent | score {PLUS_MINUS} 95% CI | % of solver [95% CI] | n |",
            "|---|---:|---:|---:|",
            f"| reference solver | +0.499 {PLUS_MINUS} 0.119 | 100% | 30 |",
            f"| **gemini-4-carbon, OpenCode over MCP** | **+0.322 {PLUS_MINUS} 0.199** | **65% [24%, 98%]**; luck-adjusted 72% [52%, 91%] | 30 |",
            f"| do_nothing | +0.000 {PLUS_MINUS} 0.000 | 0% | 40 |",
            f"| stop_early (stops on day 1, no accusation) | +0.000 {PLUS_MINUS} 0.000 | 0% | 40 |",
            f"Paired on dev seeds 0{EN_DASH}29 in [gap](docs/reports/gap.md); 40 judge seeds in [judge](results/judge_table.md).",
            f"In-process reaches 95% [62%, 140%] on hard, OpenCode reaches 111% on medium, guess_day1 averages {MINUS_SIGN}0.95.",
            f"- **Run-to-run variation.** hard +0.625 {PLUS_MINUS} 0.088 in committed table, +0.643 {PLUS_MINUS} 0.087 in [fresh](results/fresh_clone/). Spread over 300 fresh secrets.",
            f"Oracle 10-task hard rerun: +0.39 to +0.68 (mean +0.569, sd 0.094) over 200 simulated builds: [harbor](harbor/README.md{HASH_CHAR}expected-oracle-range-for-a-judge-rerun).",
        ]
    ) + "\n"
    files = {
        "README.md": readme,
        "docs/reports/gap.md": f"{HASH_CHAR} Gap\n",
        "harbor/README.md": f"{HASH_CHAR} Harbor\n{HASH_CHAR}{HASH_CHAR} Expected oracle range for a judge rerun\n",
        "results/fresh_clone/README.md": f"solver +0.643 {PLUS_MINUS} 0.087\n",
        "results/judge_table.md": judge_table,
        "data/runs/committed/v1.4/paired_table_gemini.json": json.dumps(paired),
        "results/oracle_range_v1.4.json": json.dumps(oracle),
        "results/solver_range/guess_day1_hard_judge40.json": json.dumps(gd1),
        "results/solver_range/solver_hard_judge40.json": json.dumps(solver_sr),
    }
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return files


def test_audit_readme_claims_catches_number_link_anchor_and_band_regressions(clean_tmp: Path) -> None:
    ok_repo = clean_tmp / "ok"
    base_files = _build_synthetic_repo(ok_repo)
    assert audit_readme_claims(ok_repo) == []

    ratio_bad = clean_tmp / "ratio_bad"
    _build_synthetic_repo(ratio_bad)
    (ratio_bad / "README.md").write_text(
        base_files["README.md"].replace("65%", "58%"),
        encoding="utf-8",
    )
    errs_ratio = audit_readme_claims(ratio_bad)
    assert any("65%" in e for e in errs_ratio)

    la_bad = clean_tmp / "la_bad"
    _build_synthetic_repo(la_bad)
    (la_bad / "README.md").write_text(
        base_files["README.md"].replace("72% [52%, 91%]", "72% [49%, 91%]"),
        encoding="utf-8",
    )
    errs_la = audit_readme_claims(la_bad)
    assert any("luck-adjusted" in e for e in errs_la)

    band_bad = clean_tmp / "band_bad"
    _build_synthetic_repo(band_bad)
    (band_bad / "README.md").write_text(
        base_files["README.md"].replace("+0.625", "+0.890"),
        encoding="utf-8",
    )
    errs_band = audit_readme_claims(band_bad)
    assert any("+0.890" in e and "band" in e for e in errs_band)

    jt_band_bad = clean_tmp / "jt_band_bad"
    _build_synthetic_repo(jt_band_bad)
    (jt_band_bad / "results" / "judge_table.md").write_text(
        base_files["results/judge_table.md"].replace("+0.655", "+0.150"),
        encoding="utf-8",
    )
    errs_jt = audit_readme_claims(jt_band_bad)
    assert any("+0.150" in e and "band" in e for e in errs_jt)

    link_bad = clean_tmp / "link_bad"
    _build_synthetic_repo(link_bad)
    (link_bad / "README.md").write_text(
        base_files["README.md"].replace("docs/reports/gap.md", "docs/reports/missing_gap.md"),
        encoding="utf-8",
    )
    errs_link = audit_readme_claims(link_bad)
    assert any("missing_gap.md" in e for e in errs_link)

    anchor_bad = clean_tmp / "anchor_bad"
    _build_synthetic_repo(anchor_bad)
    (anchor_bad / "README.md").write_text(
        base_files["README.md"].replace(
            "expected-oracle-range-for-a-judge-rerun",
            "wrong-oracle-heading-anchor",
        ),
        encoding="utf-8",
    )
    errs_anchor = audit_readme_claims(anchor_bad)
    assert any("wrong-oracle-heading-anchor" in e for e in errs_anchor)

    stale_bad = clean_tmp / "stale_bad"
    copy_files = copy.deepcopy(base_files)
    _build_synthetic_repo(stale_bad)
    (stale_bad / "README.md").write_text(
        copy_files["README.md"] + "Note: v1.4 frontier gap: not established.\n51-attacker swarm.\n",
        encoding="utf-8",
    )
    errs_stale = audit_readme_claims(stale_bad)
    assert any("stale gap claim" in e for e in errs_stale)
    assert any("51-attacker" in e for e in errs_stale)
