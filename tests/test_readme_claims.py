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
MULT_SIGN = chr(0x00D7)
RIGHT_ARROW = chr(0x2192)
DELTA_CHAR = chr(0x0394)
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
PREREG_SEEDS_FALSE_CLAIM_RX = re.compile(
    r"(?:seed\s+set\s+(?:was|is)\s+pre-?register\w*"
    r"|pre-?register\w*\s+(?:dev\s+)?seeds?\s*0\s*-\s*29"
    r"|seeds?\s*0\s*-\s*29\s+(?:were|was|are)\s+pre-?register\w*"
    r"|pre-?register\w*\s+n\s*=\s*30"
    r"|n\s*=\s*30\s+(?:was|is|were)\s+pre-?register\w*)",
    re.IGNORECASE,
)
STALE_CLEARANCE_CLAIM_RX = re.compile(
    r"hard\s+adds\s+clearance\s+constraints\s+and\s+fingerprint\s+noise",
    re.IGNORECASE,
)
BAR_MET_FALSE_CLAIM_RX = re.compile(
    r"bar\b[^.\n]{0,80}\bis\s+met\b",
    re.IGNORECASE,
)

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
    out = out.replace(MULT_SIGN, "x")
    out = out.replace(MINUS_SIGN, "-")
    out = out.replace(EN_DASH, "-")
    out = out.replace(EM_DASH, "-")
    out = out.replace(RIGHT_ARROW, "->")
    out = out.replace(DELTA_CHAR, "delta")
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


def _find_alternative_paired_row(
    rows: list[dict[str, Any]],
    group: str,
    tier: str,
) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("group") != group or row.get("tier") != tier:
            continue
        label_lower = str(row.get("label", "")).lower()
        if "alternative" in label_lower:
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
        "paired_pooled": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "opencode-gemini-4-carbon-ext"
            / "paired_table_pooled0to59.json"
        ),
        "oracle": root_resolved / "results" / "oracle_range_v1.4.json",
        "gd1": root_resolved / "results" / "solver_range" / "guess_day1_hard_judge40.json",
        "solver_hard_sr": root_resolved / "results" / "solver_range" / "solver_hard_judge40.json",
        "judge_table": root_resolved / "results" / "judge_table.md",
        "rehearsal_table": root_resolved / "results" / "harbor" / "rehearsal" / "TABLE.md",
        "behaviour": root_resolved / "results" / "behaviour_compare_v1.4.md",
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
    pooled_rows = json.loads(required_files["paired_pooled"].read_text(encoding="utf-8"))
    oracle_data = json.loads(required_files["oracle"].read_text(encoding="utf-8"))
    gd1_data = json.loads(required_files["gd1"].read_text(encoding="utf-8"))
    solver_sr = json.loads(required_files["solver_hard_sr"].read_text(encoding="utf-8"))
    judge_rows = _parse_judge_table_rows(required_files["judge_table"].read_text(encoding="utf-8"))
    rehearsal_norm = _strip_bold_and_code(_normalize_typography(required_files["rehearsal_table"].read_text(encoding="utf-8")))
    behaviour_norm = _strip_bold_and_code(_normalize_typography(required_files["behaviour"].read_text(encoding="utf-8")))

    oc_hard = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    oc_med = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "medium")
    ip_hard = _find_paired_row(paired_rows, "v1.4/inproc-gemini-4-carbon", "hard")
    gpt_hard = _find_paired_row(paired_rows, "v1.4/opencode-gpt-5.5", "hard")
    sv_hard = _find_paired_row(paired_rows, "v1.4/reference", "hard", agent="solver")
    oc_pool = _find_paired_row(
        pooled_rows,
        "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
        "hard",
    )
    sv_pool = _find_paired_row(pooled_rows, "v1.4/reference", "hard", agent="solver")
    if (
        oc_hard is None
        or oc_med is None
        or ip_hard is None
        or gpt_hard is None
        or sv_hard is None
        or oc_pool is None
        or sv_pool is None
    ):
        return failures + ["paired_table_gemini.json or paired_table_pooled0to59.json missing required primary rows"]

    if int(oc_hard["n"]) != 30 or int(sv_hard["n"]) != 30 or int(gpt_hard["n"]) != 30:
        failures.append(f"paired hard n mismatch: oc={oc_hard['n']} gpt={gpt_hard['n']} sv={sv_hard['n']} (expected 30)")
    if (
        oc_hard.get("seeds") != list(range(30))
        or sv_hard.get("seeds") != list(range(30))
        or gpt_hard.get("seeds") != list(range(30))
    ):
        failures.append("paired hard seeds do not match dev seeds 0-29")

    sv_mean_ci = f"{float(sv_hard['mean']):+.3f} +/- {float(sv_hard['ci']):.3f}"
    oc_mean_ci = f"{float(oc_hard['mean']):+.3f} +/- {float(oc_hard['ci']):.3f}"
    gpt_mean_ci = f"{float(gpt_hard['mean']):+.3f} +/- {float(gpt_hard['ci']):.3f}"
    oc_pool_mean_ci = f"{float(oc_pool['mean']):+.3f} +/- {float(oc_pool['ci']):.3f}"
    sv_pool_mean_ci = f"{float(sv_pool['mean']):+.3f} +/- {float(sv_pool['ci']):.3f}"
    oc_ratio = _pct(oc_hard["ratio"])
    oc_lo_num = f"{float(oc_hard['ratio_lo']) * 100.0:.0f}"
    oc_hi_pct = _pct(oc_hard["ratio_hi"])
    oc_raw_ci = f"{oc_ratio} [{_pct(oc_hard['ratio_lo'])}, {oc_hi_pct}]"
    oc_la_ci = (
        f"luck-adjusted {_pct(oc_hard['post_expected_ratio'])} "
        f"[{_pct(oc_hard['post_expected_lo'])}, {_pct(oc_hard['post_expected_hi'])}]"
    )
    gpt_raw_ci = f"{_pct(gpt_hard['ratio'])} [{_pct(gpt_hard['ratio_lo'])}, {_pct(gpt_hard['ratio_hi'])}]"
    gpt_la_ci = (
        f"luck-adjusted {_pct(gpt_hard['post_expected_ratio'])} "
        f"[{_pct(gpt_hard['post_expected_lo'])}, {_pct(gpt_hard['post_expected_hi'])}]"
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
    if len(table_rows) != 6:
        failures.append(f"README.md result table expected 6 rows, found {len(table_rows)}")
    else:
        by_agent = {r.get("agent", ""): r for r in table_rows}
        sv_row = by_agent.get("reference solver")
        oc_row = by_agent.get("gemini-4-carbon, OpenCode over MCP")
        gpt_row = next((r for k, r in by_agent.items() if k.startswith("gpt-5.5, OpenCode over MCP")), None)
        reh_row = next((r for k, r in by_agent.items() if k.startswith("gemini-4-carbon, Harbor judge path")), None)
        dn_row = by_agent.get("do_nothing")
        se_row = next((r for k, r in by_agent.items() if k.startswith("stop_early")), None)
        if sv_row is None or sv_row.get("score +/- 95% ci") != sv_mean_ci or sv_row.get("% of solver [95% ci]") != "100%" or sv_row.get("n") != "30":
            failures.append(f"README.md reference solver table row mismatch: {sv_row}")
        expected_oc_pct_col = f"{oc_raw_ci}; {oc_la_ci}"
        if oc_row is None or oc_row.get("score +/- 95% ci") != oc_mean_ci or oc_row.get("% of solver [95% ci]") != expected_oc_pct_col or oc_row.get("n") != "30":
            failures.append(f"README.md OpenCode table row mismatch: {oc_row}")
        expected_gpt_pct_col = f"{gpt_raw_ci}; {gpt_la_ci}"
        if gpt_row is None or gpt_row.get("score +/- 95% ci") != gpt_mean_ci or gpt_row.get("% of solver [95% ci]") != expected_gpt_pct_col or gpt_row.get("n") != "30":
            failures.append(f"README.md gpt-5.5 OpenCode table row mismatch: {gpt_row}")
        if (
            reh_row is None
            or reh_row.get("score +/- 95% ci") != "+0.472 / +0.585 / +0.626"
            or reh_row.get("% of solver [95% ci]") != "93% / 116% / 131% of the oracle on the same tasks (oracle +0.506 on all 10)"
            or reh_row.get("n") != "10 / 10 / 9"
        ):
            failures.append(f"README.md Harbor judge path table row mismatch: {reh_row}")
        if dn_row is None or dn_row.get("score +/- 95% ci") != "+0.000 +/- 0.000" or dn_row.get("% of solver [95% ci]") != "0%" or dn_row.get("n") != "40":
            failures.append(f"README.md do_nothing table row mismatch: {dn_row}")
        if se_row is None or se_row.get("score +/- 95% ci") != "+0.000 +/- 0.000" or se_row.get("% of solver [95% ci]") != "0%" or se_row.get("n") != "40":
            failures.append(f"README.md stop_early table row mismatch: {se_row}")

    for reh_tok in ("+0.506", "+0.472", "+0.585", "+0.626", "93% [20%, 371%]", "116% [78%, 363%]", "131% [86%, 590%]"):
        if reh_tok not in rehearsal_norm:
            failures.append(f"results/harbor/rehearsal/TABLE.md missing expected token '{reh_tok}'")
    for beh_tok in ("17.2", "6%", "10.2", "14.1", "10.6", "8.5", "53%", "13.2"):
        if not _has_token(behaviour_norm, beh_tok) or not _has_token(norm_readme, beh_tok):
            failures.append(f"README.md / results/behaviour_compare_v1.4.md missing behaviour token '{beh_tok}'")
    if not _has_token(behaviour_norm, "68.0") or not _has_token(norm_readme, "68"):
        failures.append("README.md / results/behaviour_compare_v1.4.md missing 68 / 68.0 interviews token")
    if "-0.542 +/- 0.214 at 8k context (n=50, partial)" not in norm_readme:
        failures.append("README.md missing DAgger round 1 honest null disclosure '-0.542 +/- 0.214 at 8k context (n=50, partial)'")

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
        if jt_oc.get("n") != str(int(oc_pool["n"])) or jt_oc_score != oc_pool_mean_ci:
            failures.append(
                f"results/judge_table.md reported OpenCode hard mismatch: n={jt_oc.get('n')} {jt_oc_score} vs n={oc_pool['n']} {oc_pool_mean_ci}"
            )

    jt_gpt = judge_rows.get(("hard", "reported", "opencode:openai/gpt-5.5"))
    if jt_gpt is None:
        failures.append("results/judge_table.md missing hard reported opencode:openai/gpt-5.5")
    else:
        jt_gpt_score = next((v for k, v in jt_gpt.items() if k.startswith("score")), "")
        if jt_gpt.get("n") != str(int(gpt_hard["n"])) or jt_gpt_score != gpt_mean_ci:
            failures.append(
                f"results/judge_table.md reported gpt-5.5 hard mismatch: n={jt_gpt.get('n')} {jt_gpt_score} vs n={gpt_hard['n']} {gpt_mean_ci}"
            )

    jt_sv_rep = judge_rows.get(("hard", "reported", "solver"))
    if jt_sv_rep is None:
        failures.append("results/judge_table.md missing hard reported solver")
    else:
        jt_sv_rep_score = next((v for k, v in jt_sv_rep.items() if k.startswith("score")), "")
        if jt_sv_rep.get("n") != str(int(sv_pool["n"])) or jt_sv_rep_score != sv_pool_mean_ci:
            failures.append(
                f"results/judge_table.md reported solver hard mismatch: n={jt_sv_rep.get('n')} {jt_sv_rep_score} vs n={sv_pool['n']} {sv_pool_mean_ci}"
            )

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


def _load_valid_episodes(jsonl_path: Path) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for raw_line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        ep = json.loads(raw_line)
        meta = ep.get("meta") or {}
        if meta.get("valid") is False:
            continue
        episodes.append(ep)
    return episodes


def _extract_step_error(step: dict[str, Any]) -> str | None:
    res = step.get("result")
    if isinstance(res, str) and res.strip().startswith("{"):
        try:
            res = json.loads(res)
        except ValueError:
            return None
    if not isinstance(res, dict):
        return None
    err = res.get("error")
    if not isinstance(err, str):
        return None
    stripped = err.strip()
    if stripped.startswith("{"):
        try:
            inner = json.loads(stripped)
        except ValueError:
            return err
        if isinstance(inner, dict) and isinstance(inner.get("error"), str):
            return inner["error"]
    return err


def _parse_markdown_pipe_table(md_text: str, heading_substr: str | None = None) -> list[dict[str, str]]:
    in_section = heading_substr is None
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if heading_substr is not None and stripped.startswith(HASH_CHAR * 2 + " "):
            if heading_substr in stripped:
                in_section = True
                headers = None
                continue
            if in_section:
                break
        if not in_section:
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


def check_readme_dcd8c372_and_1bc3e281_claims(root: Path) -> list[str]:
    from canary import reproduce
    from canary.env import Env

    failures: list[str] = []
    root_resolved = root.resolve()
    readme_file = root_resolved / README_REL
    if not readme_file.is_file():
        return [f"missing {README_REL}"]

    required_files = {
        "paired_primary": root_resolved / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json",
        "paired_primary_md": root_resolved / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
        "paired_pooled": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "opencode-gemini-4-carbon-ext"
            / "paired_table_pooled0to59.json"
        ),
        "oc_hard_jsonl": (
            root_resolved / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
        ),
        "oc_ext_jsonl": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "opencode-gemini-4-carbon-ext"
            / "hard"
            / "episodes.jsonl"
        ),
        "sv_0_19_jsonl": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "reference"
            / "solver-hard-20261114-121126"
            / "episodes.jsonl"
        ),
        "sv_20_29_jsonl": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "reference"
            / "solver-hard-seeds20to29"
            / "episodes.jsonl"
        ),
        "sv_30_59_jsonl": (
            root_resolved
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "reference"
            / "solver-hard-seeds30to59"
            / "episodes.jsonl"
        ),
        "ws4_v3": root_resolved / "fr8" / "analysis" / "out" / "ws4_table_v3.md",
        "ws4_8k": root_resolved / "fr8" / "analysis" / "out" / "ws4_table_8k_s1s2.md",
        "ws4_whom": root_resolved / "fr8" / "analysis" / "out" / "ws4_whom_v3.md",
        "fr8_report": root_resolved / "docs" / "reports" / "fr8.md",
        "exploits": root_resolved / "results" / "anticheat" / "exploits.json",
        "difficulty": root_resolved / "docs" / "DIFFICULTY.md",
        "check_isolation": root_resolved / "harbor" / "check_isolation.sh",
    }
    for label, path in required_files.items():
        if not path.is_file():
            failures.append(f"missing required source file ({label}): {path.relative_to(root_resolved).as_posix()}")
    rehearsal_dir = root_resolved / "results" / "harbor" / "rehearsal"
    if not rehearsal_dir.is_dir():
        failures.append("missing required directory: results/harbor/rehearsal")
    if failures:
        return failures

    raw_readme = readme_file.read_text(encoding="utf-8")
    norm_readme = _strip_bold_and_code(_normalize_typography(raw_readme))

    pooled_rows = json.loads(required_files["paired_pooled"].read_text(encoding="utf-8"))
    primary_rows = json.loads(required_files["paired_primary"].read_text(encoding="utf-8"))

    oc_prim_row = _find_paired_row(pooled_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    oc_ext_row = _find_paired_row(pooled_rows, "v1.4/opencode-gemini-4-carbon-ext", "hard")
    oc_pool_row = _find_paired_row(
        pooled_rows,
        "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
        "hard",
    )
    sv_pool_row = _find_paired_row(pooled_rows, "v1.4/reference", "hard", agent="solver")
    sv_prim_row = _find_paired_row(primary_rows, "v1.4/reference", "hard", agent="solver")
    oc_prim_main = _find_paired_row(primary_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    oc_alt_hard = _find_alternative_paired_row(primary_rows, "v1.4/opencode-gemini-4-carbon", "hard")

    if (
        oc_prim_row is None
        or oc_ext_row is None
        or oc_pool_row is None
        or sv_pool_row is None
        or sv_prim_row is None
        or oc_prim_main is None
        or oc_alt_hard is None
    ):
        return failures + ["paired_table_pooled0to59.json or paired_table_gemini.json missing required hard rows"]

    alt_raw_ci = (
        f"{_pct(oc_alt_hard['ratio'])} "
        f"[{_pct(oc_alt_hard['ratio_lo'])}, {_pct(oc_alt_hard['ratio_hi'])}]"
    )
    alt_la_short = (
        f"{_pct(oc_alt_hard['post_expected_ratio'])} "
        f"[{_pct(oc_alt_hard['post_expected_lo'])}, {_pct(oc_alt_hard['post_expected_hi'])}]"
    )
    alt_la_ci = f"luck-adjusted {alt_la_short}"
    if alt_raw_ci not in norm_readme or alt_la_ci not in norm_readme:
        failures.append(f"README.md missing infra-retries alternative hard row '{alt_raw_ci}' / '{alt_la_ci}'")

    paired_md_rows = _parse_markdown_pipe_table(required_files["paired_primary_md"].read_text(encoding="utf-8"))
    alt_md_row = next(
        (
            r
            for r in paired_md_rows
            if r.get("tier") == "hard" and "alternative" in r.get("run", "").lower()
        ),
        None,
    )
    if alt_md_row is None:
        failures.append("paired_table_gemini.md missing hard alternative row")
    else:
        md_raw_col = next((v for k, v in alt_md_row.items() if "frontier / solver" in k), "")
        md_la_col = next((v for k, v in alt_md_row.items() if "luck-adj." in k), "")
        if md_raw_col != alt_raw_ci or md_la_col != alt_la_short:
            failures.append(
                f"paired_table_gemini.md hard alternative row mismatch: '{md_raw_col}' / '{md_la_col}' vs '{alt_raw_ci}' / '{alt_la_short}'"
            )

    tool_count = len(Env("easy", 0).tools_spec())
    if f"only the {tool_count} MCP tools" not in norm_readme or not _has_token(norm_readme, f"with {tool_count} tools"):
        failures.append(f"README.md missing '{tool_count}' MCP tool-count disclosure")

    iso_checks = len(re.findall(r'\bok\s+"', required_files["check_isolation"].read_text(encoding="utf-8")))
    if iso_checks != 11 or f"isolation check: {iso_checks}/{iso_checks}" not in norm_readme:
        failures.append(
            f"README.md / harbor/check_isolation.sh isolation check mismatch (expected 11/11, script has {iso_checks})"
        )
    if "results/harbor/rehearsal/" not in norm_readme:
        failures.append("README.md missing 'results/harbor/rehearsal/' disclosure")

    oc_prim_eps = _load_valid_episodes(required_files["oc_hard_jsonl"])
    oc_ext_eps = _load_valid_episodes(required_files["oc_ext_jsonl"])
    sv_0_19_eps = _load_valid_episodes(required_files["sv_0_19_jsonl"])
    sv_20_29_eps = _load_valid_episodes(required_files["sv_20_29_jsonl"])
    sv_30_59_eps = _load_valid_episodes(required_files["sv_30_59_jsonl"])

    if len(oc_prim_eps) != int(oc_prim_row["n"]) or len(oc_ext_eps) != int(oc_ext_row["n"]):
        failures.append(
            f"OpenCode JSONL episode count mismatch: primary={len(oc_prim_eps)} ext={len(oc_ext_eps)}"
        )
    if len(oc_prim_eps) + len(oc_ext_eps) != int(oc_pool_row["n"]):
        failures.append(
            f"OpenCode pooled episode count mismatch: {len(oc_prim_eps)}+{len(oc_ext_eps)} != {oc_pool_row['n']}"
        )

    oc_ext_seeds = sorted(int(ep["seed"]) for ep in oc_ext_eps)
    if oc_ext_seeds != [int(s) for s in oc_ext_row["seeds"]]:
        failures.append(f"OpenCode ext JSONL seeds {oc_ext_seeds} != {oc_ext_row['seeds']}")
    if len(oc_ext_seeds) == 2:
        ext_seed_phrase = f"extension seeds {oc_ext_seeds[0]} and {oc_ext_seeds[1]}"
        if ext_seed_phrase not in norm_readme:
            failures.append(f"README.md missing extension seed disclosure '{ext_seed_phrase}'")

    oc_prim_m, oc_prim_ci = reproduce.mean_ci([float(ep["score"]) for ep in oc_prim_eps])
    oc_prim_fmt = f"{float(oc_prim_main['mean']):+.3f} +/- {float(oc_prim_main['ci']):.3f}"
    if f"{oc_prim_m:+.3f} +/- {oc_prim_ci:.3f}" != oc_prim_fmt:
        failures.append(
            f"OpenCode primary JSONL mean_ci ({oc_prim_m:+.3f} +/- {oc_prim_ci:.3f}) != table ({oc_prim_fmt})"
        )

    oc_pool_m, oc_pool_ci = reproduce.mean_ci([float(ep["score"]) for ep in oc_prim_eps + oc_ext_eps])
    oc_pool_fmt = f"{float(oc_pool_row['mean']):+.3f} +/- {float(oc_pool_row['ci']):.3f}"
    if f"{oc_pool_m:+.3f} +/- {oc_pool_ci:.3f}" != oc_pool_fmt:
        failures.append(
            f"OpenCode pooled JSONL mean_ci ({oc_pool_m:+.3f} +/- {oc_pool_ci:.3f}) != table ({oc_pool_fmt})"
        )
    expected_oc_pool_prose = f"pools all {int(oc_pool_row['n'])} committed episodes ({oc_pool_fmt})"
    if expected_oc_pool_prose not in norm_readme:
        failures.append(f"README.md missing pooled OpenCode hard claim: '{expected_oc_pool_prose}'")
    if "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/" not in norm_readme:
        failures.append("README.md missing extension run dir path 'data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/'")

    seeds_0_19 = [int(ep["seed"]) for ep in sv_0_19_eps]
    seeds_20_29 = [int(ep["seed"]) for ep in sv_20_29_eps]
    seeds_30_59 = [int(ep["seed"]) for ep in sv_30_59_eps]
    if len(seeds_0_19) != 20 or len(set(seeds_0_19)) != 20 or set(seeds_0_19) != set(range(0, 20)):
        failures.append(f"solver-hard-20261114-121126 seeds do not equal 0..19 cleanly: count={len(seeds_0_19)}")
    if len(seeds_20_29) != 10 or len(set(seeds_20_29)) != 10 or set(seeds_20_29) != set(range(20, 30)):
        failures.append(f"solver-hard-seeds20to29 seeds do not equal 20..29 cleanly: count={len(seeds_20_29)}")
    if not set(seeds_0_19).isdisjoint(set(seeds_20_29)) or (set(seeds_0_19) | set(seeds_20_29)) != set(range(30)):
        failures.append("20+10 solver reference dirs do not partition {0..29} cleanly")
    if len(seeds_30_59) != 30 or len(set(seeds_30_59)) != 30 or set(seeds_30_59) != set(range(30, 60)):
        failures.append(f"solver-hard-seeds30to59 seeds do not equal 30..59 cleanly: count={len(seeds_30_59)}")
    if len(sv_0_19_eps) + len(sv_20_29_eps) + len(sv_30_59_eps) != int(sv_pool_row["n"]):
        failures.append(
            f"solver pooled episode count mismatch: 20+10+30 != {sv_pool_row['n']}"
        )

    sv_30_m, sv_30_ci = reproduce.mean_ci([float(ep["score"]) for ep in sv_0_19_eps + sv_20_29_eps])
    sv_prim_fmt = f"{float(sv_prim_row['mean']):+.3f} +/- {float(sv_prim_row['ci']):.3f}"
    if f"{sv_30_m:+.3f} +/- {sv_30_ci:.3f}" != sv_prim_fmt:
        failures.append(f"20+10 solver JSONL mean_ci ({sv_30_m:+.3f} +/- {sv_30_ci:.3f}) != primary ({sv_prim_fmt})")

    sv_pool_m, sv_pool_ci = reproduce.mean_ci(
        [float(ep["score"]) for ep in sv_0_19_eps + sv_20_29_eps + sv_30_59_eps]
    )
    sv_pool_fmt = f"{float(sv_pool_row['mean']):+.3f} +/- {float(sv_pool_row['ci']):.3f}"
    if f"{sv_pool_m:+.3f} +/- {sv_pool_ci:.3f}" != sv_pool_fmt:
        failures.append(f"solver pooled JSONL mean_ci ({sv_pool_m:+.3f} +/- {sv_pool_ci:.3f}) != table ({sv_pool_fmt})")

    expected_sv_pool_prose = f"pools seeds 0-59 ({sv_pool_fmt}, n={int(sv_pool_row['n'])})"
    if expected_sv_pool_prose not in norm_readme:
        failures.append(f"README.md missing pooled solver hard claim: '{expected_sv_pool_prose}'")

    oc_raw_ci = (
        f"{_pct(oc_prim_main['ratio'])} "
        f"[{_pct(oc_prim_main['ratio_lo'])}, {_pct(oc_prim_main['ratio_hi'])}]"
    )
    oc_la_ci = (
        f"luck-adjusted {_pct(oc_prim_main['post_expected_ratio'])} "
        f"[{_pct(oc_prim_main['post_expected_lo'])}, {_pct(oc_prim_main['post_expected_hi'])}]"
    )
    expected_headline_recomp = f"HEADLINE, recomputes it: {oc_prim_m:+.3f} vs {sv_30_m:+.3f}, {oc_raw_ci}"
    if expected_headline_recomp not in norm_readme:
        failures.append(f"README.md missing HEADLINE recomputation claim: '{expected_headline_recomp}'")

    for ref_dir_tok in (
        "seeds 0-19 in data/runs/committed/v1.4/reference/solver-hard-20261114-121126/",
        "seeds 20-29 in reference/solver-hard-seeds20to29/",
        "The paired table uses all 30.",
    ):
        if ref_dir_tok not in norm_readme:
            failures.append(f"README.md missing 20+10 solver reference disclosure '{ref_dir_tok}'")

    posthoc_lock_phrase = "locked right after those episodes were committed (a post-hoc lock against reruns and cherry-picking)"
    if posthoc_lock_phrase not in norm_readme:
        failures.append(f"README.md missing Panel Fix A post-hoc lock disclosure: '{posthoc_lock_phrase}'")
    if PREREG_SEEDS_FALSE_CLAIM_RX.search(norm_readme):
        failures.append("README.md falsely claims dev seeds 0-29 or n=30 were pre-registered")

    raw_pct_tok = _pct(oc_prim_main["ratio"])
    la_pct_tok = _pct(oc_prim_main["post_expected_ratio"])
    raw_pos = norm_readme.find(raw_pct_tok)
    la_pos = norm_readme.find(la_pct_tok)
    raw_ci_pos = norm_readme.find(oc_raw_ci)
    la_ci_pos = norm_readme.find(oc_la_ci)
    if raw_pos == -1 or la_pos == -1 or raw_pos >= la_pos or raw_ci_pos == -1 or la_ci_pos == -1 or raw_ci_pos >= la_ci_pos:
        failures.append(
            f"README.md must lead with raw {oc_raw_ci} before {oc_la_ci} (pos {raw_pos}/{raw_ci_pos} vs {la_pos}/{la_ci_pos})"
        )
    claim_lines = [
        ln
        for ln in norm_readme.splitlines()
        if ln.strip().startswith("What we measured on the hard tier (rules v1.4), stated plainly.")
        or ln.strip().startswith("Claim:")
    ]
    if not claim_lines or not _has_token(claim_lines[0], raw_pct_tok) or _has_token(claim_lines[0], la_pct_tok):
        failures.append(f"README.md top Claim line must report raw {raw_pct_tok} without leading with {la_pct_tok}")

    result_rows = _parse_readme_result_table(raw_readme)
    oc_res_row = next((r for r in result_rows if r.get("agent") == "gemini-4-carbon, OpenCode over MCP"), None)
    if oc_res_row is not None:
        pct_col = oc_res_row.get("% of solver [95% ci]", "")
        if pct_col.find(oc_raw_ci) == -1 or pct_col.find(oc_la_ci) == -1 or pct_col.find(oc_raw_ci) >= pct_col.find(oc_la_ci):
            failures.append(f"README.md result table OpenCode row must put raw {oc_raw_ci} before {oc_la_ci}: '{pct_col}'")

    if "clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4" not in norm_readme:
        failures.append("README.md missing Panel Fix A W4 disclosure 'clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4'")
    if STALE_CLEARANCE_CLAIM_RX.search(norm_readme):
        failures.append("README.md contains stale pre-Fix-A claim 'Hard adds clearance constraints and fingerprint noise'")
    diff_norm = _strip_bold_and_code(_normalize_typography(required_files["difficulty"].read_text(encoding="utf-8")))
    if "W4." not in diff_norm or "never binds" not in diff_norm:
        failures.append("docs/DIFFICULTY.md missing W4 never-binds disclosure referenced by README.md")

    total_steps = sum(len(ep.get("steps", [])) for ep in oc_prim_eps)
    inv_arg_steps = sum(
        1
        for ep in oc_prim_eps
        for st in ep.get("steps", [])
        if _extract_step_error(st) == "invalid arguments"
    )
    detail_tok = f"{inv_arg_steps} of the {total_steps:,} calls in the {len(oc_prim_eps)} headline episodes"
    if "Tool errors now carry a detail field" not in norm_readme or detail_tok not in norm_readme:
        failures.append(f"README.md missing Panel Fix D tool-error detail disclosure '{detail_tok}'")
    if "careful mole was reworded in the medium and hard instructions" not in norm_readme:
        failures.append("README.md missing Panel Fix D W1 careful-mole rewording disclosure")

    ws4_v3_rows = _parse_markdown_pipe_table(required_files["ws4_v3"].read_text(encoding="utf-8"))
    ws4_8k_rows = _parse_markdown_pipe_table(required_files["ws4_8k"].read_text(encoding="utf-8"))
    ws4_whom_rows = _parse_markdown_pipe_table(required_files["ws4_whom"].read_text(encoding="utf-8"))
    fr8_norm = _strip_bold_and_code(_normalize_typography(required_files["fr8_report"].read_text(encoding="utf-8")))

    v3_all = {r["model"]: r for r in ws4_v3_rows if r.get("tier") == "all"}
    s8k_all = {r["model"]: r for r in ws4_8k_rows if r.get("tier") == "all"}
    whom_by_run = {r.get("run", ""): r for r in ws4_whom_rows}

    if not {"base", "v2", "v3-4k-s0", "v3-8k-s2"}.issubset(v3_all):
        return failures + ["fr8/analysis/out/ws4_table_v3.md missing required tier=all rows"]
    if not {"base", "v2", "v3_4k_s0", "v3_8k_s2_H100_693st"}.issubset(s8k_all):
        return failures + ["fr8/analysis/out/ws4_table_8k_s1s2.md missing required tier=all rows"]
    if "v3-4k-s0" not in whom_by_run:
        return failures + ["fr8/analysis/out/ws4_whom_v3.md missing v3-4k-s0 row"]

    for v3_key, s8k_key in (("v2", "v2"), ("v3-4k-s0", "v3_4k_s0"), ("v3-8k-s2", "v3_8k_s2_H100_693st")):
        if v3_all[v3_key]["n"] != s8k_all[s8k_key]["n"] or v3_all[v3_key]["score +/- 95% ci"] != s8k_all[s8k_key]["score +/- 95% ci"]:
            failures.append(f"WS4 table mismatch between v3 and 8k_s1s2 on {v3_key}")
    if v3_all["base"]["valid calls"] != s8k_all["base"]["valid calls"]:
        failures.append("WS4 base valid-call share mismatch between ws4_table_v3.md and ws4_table_8k_s1s2.md")

    readme_ws4_rows = _parse_markdown_pipe_table(raw_readme, "Tiebreak: a small model trained on Canary experience")
    if len(readme_ws4_rows) != 4:
        failures.append(f"README.md Tiebreak table expected 4 rows, found {len(readme_ws4_rows)}")
    else:
        base_valid_pct = f"{float(v3_all['base']['valid calls']) * 100.0:.0f}%"
        r_base, r_v2, r_v3_4k, r_v3_8k = readme_ws4_rows
        if (
            not r_base.get("model", "").startswith("base")
            or r_base.get("n") != v3_all["base"]["n"]
            or not r_base.get("held-out score +/- 95% ci", "").startswith("0.000")
            or f"{base_valid_pct} valid tool calls" not in r_base.get("held-out score +/- 95% ci", "")
        ):
            failures.append(f"README.md Tiebreak base row mismatch: {r_base}")
        if (
            not r_v2.get("model", "").startswith("v2")
            or r_v2.get("n") != v3_all["v2"]["n"]
            or r_v2.get("held-out score +/- 95% ci") != v3_all["v2"]["score +/- 95% ci"]
        ):
            failures.append(f"README.md Tiebreak v2 row mismatch: {r_v2}")
        if (
            not r_v3_4k.get("model", "").startswith("v3-4k")
            or r_v3_4k.get("n") != v3_all["v3-4k-s0"]["n"]
            or r_v3_4k.get("held-out score +/- 95% ci") != v3_all["v3-4k-s0"]["score +/- 95% ci"]
        ):
            failures.append(f"README.md Tiebreak v3-4k row mismatch: {r_v3_4k}")
        if (
            not r_v3_8k.get("model", "").startswith("v3-8k seed 2")
            or r_v3_8k.get("n") != v3_all["v3-8k-s2"]["n"]
            or r_v3_8k.get("held-out score +/- 95% ci") != v3_all["v3-8k-s2"]["score +/- 95% ci"]
        ):
            failures.append(f"README.md Tiebreak v3-8k seed 2 row mismatch: {r_v3_8k}")

    delta_col_v3 = next((v for k, v in v3_all["v3-4k-s0"].items() if "vs v2" in k), "")
    delta_col_8k = next((v for k, v in s8k_all["v3_4k_s0"].items() if "vs v2" in k), "")
    m_delta_v3 = SOLVER_PM_RX.search(delta_col_v3)
    m_delta_8k = SOLVER_PM_RX.search(delta_col_8k)
    if m_delta_v3 is None or m_delta_8k is None or m_delta_v3.groups() != m_delta_8k.groups():
        failures.append(f"WS4 v3-4k vs v2 delta parse/agreement failure: '{delta_col_v3}' vs '{delta_col_8k}'")
    else:
        delta_fmt = f"{m_delta_v3.group(1)} +/- {m_delta_v3.group(2)}"
        recovery_tok = f"v3-4k vs v2: {delta_fmt}, two-sample"
        if recovery_tok not in norm_readme:
            failures.append(f"README.md Tiebreak missing recovery claim '{recovery_tok}'")
        if delta_fmt not in fr8_norm:
            failures.append(f"docs/reports/fr8.md missing WS4 recovery delta '{delta_fmt}'")

    whom_row = whom_by_run["v3-4k-s0"]
    first_w_cell = next((v for k, v in whom_row.items() if "first w" in k), "")
    last_w_cell = next((v for k, v in whom_row.items() if "last w" in k), "")
    m_first_w = re.search(r"\d+\.\d+", first_w_cell)
    m_last_w = re.search(r"\d+\.\d+", last_w_cell)
    if m_first_w is None or m_last_w is None:
        failures.append(f"fr8/analysis/out/ws4_whom_v3.md unparsable v3-4k-s0 whom cells: '{first_w_cell}' / '{last_w_cell}'")
    else:
        whom_arrow = f"{float(m_first_w.group(0)):.2f} -> {float(m_last_w.group(0)):.2f}"
        if f"({whom_arrow})" not in norm_readme:
            failures.append(f"README.md Tiebreak missing training-state whom claim '({whom_arrow})'")
        if whom_arrow not in fr8_norm:
            failures.append(f"docs/reports/fr8.md missing training-state whom claim '{whom_arrow}'")

    if "04:45 WS4 readout" not in norm_readme or "04:45 WS4" not in fr8_norm:
        failures.append("README.md / docs/reports/fr8.md missing '04:45 WS4 readout' cross-reference")
    for ws4_key in ("v2", "v3-4k-s0", "v3-8k-s2"):
        sc_str = v3_all[ws4_key]["score +/- 95% ci"]
        if sc_str not in fr8_norm:
            failures.append(f"docs/reports/fr8.md missing WS4 {ws4_key} score '{sc_str}'")

    v3_valid_pct = f"{float(v3_all['v3-4k-s0']['valid calls']) * 100.0:.0f}% valid calls"
    if v3_valid_pct not in norm_readme:
        failures.append(f"README.md Tiebreak missing '{v3_valid_pct}'")
    if "not met" not in norm_readme or BAR_MET_FALSE_CLAIM_RX.search(norm_readme):
        failures.append("README.md Tiebreak bar status must be 'not met' and never 'is met'")

    exploits_data = json.loads(required_files["exploits"].read_text(encoding="utf-8"))
    exp_tiers = exploits_data.get("tiers") or []
    exp_rows = exploits_data.get("rows") or []
    exp_seeds = exploits_data.get("seeds") or []
    if len(exp_seeds) < 3 or f"committed {int(exp_seeds[2])}-seed battery" not in norm_readme:
        failures.append("README.md / exploits.json committed anti-cheat battery seed count mismatch")
    if "0 differences" not in norm_readme:
        failures.append("README.md missing anti-cheat '0 differences' expectation")
    if not exp_tiers or not exp_rows:
        failures.append("results/anticheat/exploits.json missing tiers or rows")
    else:
        attack_counts = {
            t: sum(1 for r in exp_rows if r.get("tier") == t and r.get("kind") == "attack")
            for t in exp_tiers
        }
        swarm_counts = {
            t: sum(1 for r in exp_rows if r.get("tier") == t and r.get("kind") == "swarm")
            for t in exp_tiers
        }
        if len(set(attack_counts.values())) != 1 or len(set(swarm_counts.values())) != 1:
            failures.append(f"exploits.json per-tier kind counts inconsistent: attack={attack_counts} swarm={swarm_counts}")
        else:
            attack_n = next(iter(attack_counts.values()))
            swarm_n = next(iter(swarm_counts.values()))
            attack_noun = "probe" if attack_n == 1 else "probes"
            swarm_noun = "probe" if swarm_n == 1 else "probes"
            probe_phrase = f"{attack_n} scripted attack {attack_noun} and {swarm_n} swarm {swarm_noun}"
            if probe_phrase not in norm_readme:
                failures.append(f"README.md missing anti-cheat probe count phrase '{probe_phrase}'")

    return failures


def audit_readme_claims(root: Path = ROOT) -> list[str]:
    link_failures, _, _ = check_readme_links_and_anchors(root)
    num_failures = check_readme_numbers_and_bands(root)
    ext_failures = check_readme_dcd8c372_and_1bc3e281_claims(root)
    return link_failures + num_failures + ext_failures


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
        "results/harbor/rehearsal/TABLE.md",
        "data/runs/committed/v1.4/paired_table_gemini.md",
        "results/behaviour_compare_v1.4.md",
        "docs/reports/gap.md",
        "docs/DIFFICULTY.md",
        "docs/SUBMISSION.md",
        "docs/reports/fr8.md",
        "docs/reports/failure_analysis_v1.4.md",
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

    judge_table_raw = (ROOT / "results" / "judge_table.md").read_text(encoding="utf-8")
    assert "4bf5f8e8e48b" in judge_table_raw
    judge_rows = _parse_judge_table_rows(judge_table_raw)
    jt_sv = judge_rows[("hard", "reference", "solver")]
    score_cell = next(v for k, v in jt_sv.items() if k.startswith("score"))
    m_jt = SOLVER_PM_RX.search(score_cell)
    assert m_jt is not None
    committed_jt_token = f"{m_jt.group(1)} +/- {m_jt.group(2)}"
    assert committed_jt_token == "+0.513 +/- 0.120"
    committed_jt_hard = float(m_jt.group(1))

    assert _has_token(norm_readme, "+0.553 +/- 0.093")
    assert _has_token(norm_readme, "+0.643 +/- 0.087")

    macos_log = ROOT / "results" / "fresh_clone" / "macos_justSilas_09e7363.log.txt"
    assert macos_log.is_file()
    assert _has_token(_normalize_typography(macos_log.read_text(encoding="utf-8")), "+0.643 +/- 0.087")

    linux_af_log = ROOT / "results" / "fresh_clone" / "linux_x86_64_afterquery_final_1bc3e281.log.txt"
    assert linux_af_log.is_file()
    linux_af_norm = _normalize_typography(linux_af_log.read_text(encoding="utf-8"))
    assert _has_token(linux_af_norm, "+0.527 +/- 0.116")
    assert _has_token(linux_af_norm, "+0.349 +/- 0.190")

    solver_sr = json.loads((ROOT / "results" / "solver_range" / "solver_hard_judge40.json").read_text(encoding="utf-8"))
    assert solver_sr["agent"] == "solver"
    assert solver_sr["tier"] == "hard"
    assert int(solver_sr["builds"]) == 300
    assert solver_sr["seeds"] == [900000, 900039]

    band_lo = float(solver_sr["mean"]) - ACCEPT_K_SD * float(solver_sr["sd"])
    band_hi = float(solver_sr["mean"]) + ACCEPT_K_SD * float(solver_sr["sd"])
    sr_min = float(solver_sr["min"])
    sr_max = float(solver_sr["max"])

    for label, candidate in (
        ("README line 43 illustrative judge_table draw (+0.553)", 0.553),
        ("README line 43 macOS fresh_clone (+0.643)", 0.643),
        ("afterquery-final Linux x86_64 fresh_clone (+0.527)", 0.527),
        ("results/judge_table.md regenerated hard solver (+0.513)", committed_jt_hard),
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


def test_readme_panel_fixes_pooled_reproduce_and_ws4_tiebreak_explicit() -> None:
    from canary import reproduce
    from canary.env import Env

    raw_readme = README_PATH.read_text(encoding="utf-8")
    norm_readme = _strip_bold_and_code(_normalize_typography(raw_readme))

    assert norm_readme.index("65% [24%, 98%]") < norm_readme.index("72% [52%, 91%]")
    assert "locked right after those episodes were committed (a post-hoc lock against reruns and cherry-picking)" in norm_readme
    assert "clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4" in norm_readme

    paired_rows = json.loads((ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").read_text(encoding="utf-8"))
    alt_hard = _find_alternative_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    assert alt_hard is not None
    assert f"{_pct(alt_hard['ratio'])} [{_pct(alt_hard['ratio_lo'])}, {_pct(alt_hard['ratio_hi'])}]" == "56% [19%, 87%]"
    assert (
        f"{_pct(alt_hard['post_expected_ratio'])} "
        f"[{_pct(alt_hard['post_expected_lo'])}, {_pct(alt_hard['post_expected_hi'])}]"
    ) == "55% [34%, 77%]"
    assert "56% [19%, 87%]" in norm_readme
    assert "luck-adjusted 55% [34%, 77%]" in norm_readme

    assert len(Env("easy", 0).tools_spec()) == 13
    assert "isolation check: 11/11" in norm_readme
    assert (ROOT / "results" / "harbor" / "rehearsal").is_dir()
    iso_files = sorted((ROOT / "results" / "harbor").rglob("isolation.txt"))
    assert iso_files, "expected committed Harbor isolation.txt artifacts"
    assert any("ISOLATION OK: 11 checks passed, 0 findings" in p.read_text(encoding="utf-8") for p in iso_files)

    oc_eps = _load_valid_episodes(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    )
    assert len(oc_eps) == 30
    assert sum(len(ep["steps"]) for ep in oc_eps) == 3841
    inv_cnt = sum(
        1
        for ep in oc_eps
        for st in ep["steps"]
        if "invalid arguments" in str((st.get("result") or {}).get("error") or "")
    )
    assert inv_cnt == 28
    assert "28 of the 3,841 calls in the 30 headline episodes" in norm_readme

    oc_ext_eps = _load_valid_episodes(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    )
    assert [int(ep["seed"]) for ep in oc_ext_eps] == [34, 37]
    oc_pool_m, oc_pool_ci = reproduce.mean_ci([float(ep["score"]) for ep in oc_eps + oc_ext_eps])
    assert f"{oc_pool_m:+.3f} +/- {oc_pool_ci:.3f}" == "+0.349 +/- 0.190"

    sv_0_19 = _load_valid_episodes(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl"
    )
    sv_20_29 = _load_valid_episodes(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl"
    )
    sv_30_59 = _load_valid_episodes(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-seeds30to59" / "episodes.jsonl"
    )
    assert len(sv_0_19) == 20 and {int(ep["seed"]) for ep in sv_0_19} == set(range(0, 20))
    assert len(sv_20_29) == 10 and {int(ep["seed"]) for ep in sv_20_29} == set(range(20, 30))
    assert len(sv_30_59) == 30 and {int(ep["seed"]) for ep in sv_30_59} == set(range(30, 60))
    sv_30_m, sv_30_ci = reproduce.mean_ci([float(ep["score"]) for ep in sv_0_19 + sv_20_29])
    assert f"{sv_30_m:+.3f} +/- {sv_30_ci:.3f}" == "+0.499 +/- 0.119"
    sv_60_m, sv_60_ci = reproduce.mean_ci([float(ep["score"]) for ep in sv_0_19 + sv_20_29 + sv_30_59])
    assert f"{sv_60_m:+.3f} +/- {sv_60_ci:.3f}" == "+0.498 +/- 0.097"

    for ws4_tok in (
        "3% valid tool calls",
        "-0.457 +/- 0.086",
        "-0.147 +/- 0.063",
        "-0.050 +/- 0.049",
        "+0.310 +/- 0.107, two-sample",
        "100% valid calls",
        "(0.19 -> 0.89)",
        "not met",
        "14 scripted attack probes and 1 swarm probe",
        "0 differences",
    ):
        assert ws4_tok in norm_readme, f"README.md missing expected WS4 / anti-cheat token '{ws4_tok}'"


def test_readme_commands_pass_doc_command_verifier() -> None:
    results = verify_doc_commands.verify_repo(root=ROOT, docs=(README_REL,))
    assert len(results) == 4
    failed = [f"{r.name}: {r.status} ({r.details})" for r in results if r.status != "PASS"]
    assert not failed, f"verify_doc_commands failed on README.md: {failed}"


def _make_jsonl(seed_scores: list[tuple[int, float]], invalid_arg_calls_on_first: int = 0) -> str:
    lines: list[str] = []
    for idx, (seed, score) in enumerate(seed_scores):
        if idx == 0 and invalid_arg_calls_on_first > 0:
            steps = [{"result": {"error": "invalid arguments"}} for _ in range(invalid_arg_calls_on_first)] + [
                {"result": {"ok": True}}
            ]
        else:
            steps = [{"result": {"ok": True}}]
        lines.append(json.dumps({"seed": seed, "score": score, "steps": steps, "meta": {"valid": True}}))
    return "\n".join(lines) + "\n"


def _build_synthetic_repo(repo: Path) -> dict[str, Any]:
    oc_prim_pairs = [
        (0, 0.59), (1, -1.0), (2, 0.48), (3, 0.51), (4, 0.4),
        (5, 0.16), (6, 0.73), (7, 0.69), (8, 0.35), (9, 0.6),
        (10, 0.4), (11, 0.0), (12, 0.65), (13, 0.4), (14, 0.71),
        (15, -1.0), (16, 0.7), (17, 0.54), (18, -1.0), (19, 0.62),
        (20, 0.66), (21, 0.69), (22, 0.64), (23, 0.23), (24, 0.67),
        (25, 0.72), (26, -1.0), (27, 0.46), (28, 0.64), (29, 0.43),
    ]
    oc_ext_pairs = [(34, 0.79), (37, 0.7)]
    sv_0_19_pairs = [
        (0, 0.64), (1, 0.69), (2, 0.58), (3, 0.28), (4, 0.73),
        (5, 0.52), (6, 0.71), (7, 0.64), (8, 0.26), (9, 0.71),
        (10, 0.21), (11, 0.62), (12, 0.48), (13, 0.34), (14, 0.23),
        (15, -1.0), (16, 0.69), (17, 0.77), (18, 0.52), (19, 0.67),
    ]
    sv_20_29_pairs = [
        (20, 0.53), (21, 0.73), (22, 0.4), (23, 0.32), (24, 0.31),
        (25, 0.58), (26, 0.69), (27, 0.72), (28, 0.75), (29, 0.65),
    ]
    sv_30_59_pairs = [
        (30, -1.0), (31, 0.52), (32, -1.0), (33, 0.53), (34, 0.7),
        (35, 0.68), (36, 0.77), (37, 0.77), (38, 0.0), (39, 0.7),
        (40, 0.55), (41, 0.57), (42, 0.51), (43, 0.69), (44, 0.75),
        (45, 0.49), (46, 0.7), (47, 0.43), (48, 0.46), (49, 0.8),
        (50, 0.78), (51, 0.72), (52, 0.66), (53, 0.62), (54, 0.5),
        (55, 0.72), (56, 0.53), (57, 0.54), (58, 0.53), (59, 0.72),
    ]

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
            "label": "OpenCode, alternative (NOT the headline): empty model reply counted as 0",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.2786666666666667,
            "ci": 0.1804187402487618,
            "solver_same_seeds": 0.499,
            "ratio": 0.5584502338009352,
            "ratio_lo": 0.18925056775170324,
            "ratio_hi": 0.8658008658008659,
            "post_expected_ratio": 0.5545580783635652,
            "post_expected_lo": 0.34286842536141876,
            "post_expected_hi": 0.7713212108249886,
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
            "label": "OpenCode + gpt-5.5 over MCP (second frontier family)",
            "group": "v1.4/opencode-gpt-5.5",
            "agent": "opencode:openai/gpt-5.5",
            "tier": "hard",
            "n": 30,
            "seeds": list(range(30)),
            "mean": 0.5036666666666667,
            "ci": 0.06378366213659701,
            "solver_same_seeds": 0.499,
            "ratio": 1.0093520374081495,
            "ratio_lo": 0.7860335195530728,
            "ratio_hi": 1.4028906955736222,
            "post_expected_ratio": 0.8366849368111149,
            "post_expected_lo": 0.6654962408904034,
            "post_expected_hi": 1.0307646693295247,
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
    paired_md = "\n".join(
        [
            "| tier | run | n | frontier / solver [95% CI] | luck-adj. / solver's luck-adj. [95% CI] |",
            "|---|---|---:|---|---|",
            "| hard | OpenCode + gemini-4-carbon over MCP | 30 | 65% [24%, 98%] | **72% [52%, 91%]** |",
            "| hard | OpenCode, alternative (NOT the headline) | 30 | 56% [19%, 87%] | **55% [34%, 77%]** |",
        ]
    ) + "\n"
    pooled = [
        paired[1],
        {
            "label": "OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)",
            "group": "v1.4/opencode-gemini-4-carbon-ext",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 2,
            "seeds": [34, 37],
            "mean": 0.745,
            "ci": 0.0882,
        },
        {
            "label": "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
            "group": "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 32,
            "seeds": list(range(30)) + [34, 37],
            "mean": 0.34875,
            "ci": 0.18975526661907804,
        },
        {
            "label": "reference solver",
            "group": "v1.4/reference",
            "agent": "solver",
            "tier": "hard",
            "n": 60,
            "seeds": list(range(60)),
            "mean": 0.4985,
            "ci": 0.09740111755875758,
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
            "| solver | reference | 40 | 0 | +0.625 +/- 0.088 | 1.00 |",
            "| stop_early | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 |",
            "| do_nothing | baseline | 40 | 0 | +0.000 +/- 0.000 | 0.00 |",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | / solver |",
            "|---|---|---:|---|---:|---:|",
            "| opencode:google/gemini-4-carbon | reported | 32 | 0 | +0.349 +/- 0.190 | - |",
            "| opencode:openai/gpt-5.5 | reported | 30 | 0 | +0.504 +/- 0.064 | - |",
            "| solver | reported | 60 | 0 | +0.498 +/- 0.097 | - |",
        ]
    ) + "\n"
    rehearsal_table = "\n".join(
        [
            "> Correction: run 3 has 9 valid trials, mean +0.626 = 131% [86%, 590%] of the oracle.",
            f"{HASH_CHAR} Judge rehearsal on tag afterquery-final (1bc3e281)",
            "| run | n valid | mean | oracle, same tasks | run / oracle [95% paired bootstrap CI] |",
            "|---|---:|---:|---:|---|",
            "| opencode-1 | 10 | +0.472 | +0.506 | 93% [20%, 371%] |",
            "| opencode-2 | 10 | +0.585 | +0.506 | 116% [78%, 363%] |",
            "| opencode-3 | 7 | +0.656 | +0.429 | 153% [89%, 411%] |",
        ]
    ) + "\n"
    behaviour_md = "\n".join(
        [
            f"{HASH_CHAR} Behaviour compare",
            "| agent | n | score | canaries planted | interviews | share | accuse day |",
            "|---|---:|---:|---:|---:|---:|---:|",
            "| reference solver | 30 | +0.499 | 14.1 | 0.0 | 0% | 10.6 |",
            "| gpt-5.5, OpenCode over MCP | 30 | +0.504 | 17.2 | 4.2 | 6% | 10.2 |",
            "| gemini-4-carbon, OpenCode over MCP | 30 | +0.322 | 8.5 | 68.0 | 53% | 13.2 |",
        ]
    ) + "\n"
    ws4_v3 = "\n".join(
        [
            f"| model | tier | n | score {PLUS_MINUS} 95% CI | valid calls | {DELTA_CHAR} vs v2 (two-sample, n vs n) |",
            "|---|---|---:|---:|---:|---|",
            f"| base | all | 36 | 0.000 {PLUS_MINUS} 0.000 | 0.03 | +0.457 {PLUS_MINUS} 0.086 |",
            f"| v2 | all | 172 | -0.457 {PLUS_MINUS} 0.086 | 0.92 | - |",
            f"| v3-4k-s0 | all | 180 | -0.147 {PLUS_MINUS} 0.063 | 1.00 | +0.310 {PLUS_MINUS} 0.107 (180 vs 172) |",
            f"| v3-8k-s2 | all | 90 | -0.050 {PLUS_MINUS} 0.049 | 0.96 | +0.408 {PLUS_MINUS} 0.099 (90 vs 172) |",
        ]
    ) + "\n"
    ws4_8k = "\n".join(
        [
            f"| model | tier | n | score {PLUS_MINUS} 95% CI | valid calls | {DELTA_CHAR} vs v2 (two-sample, n vs n) |",
            "|---|---|---:|---:|---:|---|",
            f"| base | all | 36 | 0.000 {PLUS_MINUS} 0.000 | 0.03 | +0.457 {PLUS_MINUS} 0.086 |",
            f"| v2 | all | 172 | -0.457 {PLUS_MINUS} 0.086 | 0.92 | - |",
            f"| v3_4k_s0 | all | 180 | -0.147 {PLUS_MINUS} 0.063 | 1.00 | +0.310 {PLUS_MINUS} 0.107 (180 vs 172) |",
            f"| v3_8k_s2_H100_693st | all | 90 | -0.050 {PLUS_MINUS} 0.049 | 0.96 | +0.408 {PLUS_MINUS} 0.099 (90 vs 172) |",
        ]
    ) + "\n"
    ws4_whom = "\n".join(
        [
            "| run | train steps | forced-accuse whom-acc, first W | last W |",
            "|---|---:|---|---|",
            f"| v3-4k-s0 | 609 | 0.190 {PLUS_MINUS} 0.042 (W=100) | 0.892 {PLUS_MINUS} 0.030 (W=100) |",
        ]
    ) + "\n"
    fr8_report = "\n".join(
        [
            f"{HASH_CHAR}{HASH_CHAR} 04:45 WS4 small-model tiebreaker readout: bar NOT met",
            f"v2: -0.457 {PLUS_MINUS} 0.086, v3-4k s0: -0.147 {PLUS_MINUS} 0.063, v3-8k s2: -0.050 {PLUS_MINUS} 0.049.",
            f"v3-4k vs v2 is +0.310 {PLUS_MINUS} 0.107; whom accuracy rose 0.19 {RIGHT_ARROW} 0.89.",
        ]
    ) + "\n"
    exploits = {
        "all_blocked": True,
        "seeds": [900000, 900039, 40],
        "tiers": ["easy", "medium", "hard"],
        "rows": (
            [{"tier": t, "kind": "attack"} for t in ("easy", "medium", "hard") for _ in range(14)]
            + [{"tier": t, "kind": "swarm"} for t in ("easy", "medium", "hard")]
        ),
    }
    readme = "\n".join(
        [
            f"{HASH_CHAR} Canary: catch the mole",
            (
                f"**What we measured on the hard tier (rules v1.4), stated plainly.** (1) With only the 13 MCP tools (OpenCode), "
                f"gemini-4-carbon earns 65% of the reference solver's score (95% CI 24{EN_DASH}98%, n=30). "
                "([`results/harbor/rehearsal/TABLE.md`](results/harbor/rehearsal/TABLE.md))."
            ),
            f"{HASH_CHAR}{HASH_CHAR} Result (rules v1.4, hard tier)",
            f"| agent | score {PLUS_MINUS} 95% CI | % of solver [95% CI] | n |",
            "|---|---:|---:|---:|",
            f"| reference solver | +0.499 {PLUS_MINUS} 0.119 | 100% | 30 |",
            f"| **gemini-4-carbon, OpenCode over MCP** | **+0.322 {PLUS_MINUS} 0.199** | **65% [24%, 98%]**; luck-adjusted 72% [52%, 91%] | 30 |",
            f"| gpt-5.5, OpenCode over MCP (second frontier family) | +0.504 {PLUS_MINUS} 0.064 | 101% [79%, 140%]; luck-adjusted 84% [67%, 103%] | 30 |",
            f"| gemini-4-carbon, **Harbor judge path** (3 runs {MULT_SIGN} 10 judge tasks on the tag; run 3: 9 valid, 5 of them after the 08:30 cut-off) | +0.472 / +0.585 / +0.626 | 93% / 116% / 131% of the oracle on the same tasks (oracle +0.506 on all 10) | 10 / 10 / 9 |",
            f"| do_nothing | +0.000 {PLUS_MINUS} 0.000 | 0% | 40 |",
            f"| stop_early (stops on day 1, no accusation) | +0.000 {PLUS_MINUS} 0.000 | 0% | 40 |",
            (
                f"Paired on dev seeds 0{EN_DASH}29 in [gap](docs/reports/gap.md), locked right after those episodes "
                "were committed (a post-hoc lock against reruns and cherry-picking); 40 judge seeds in [judge](results/judge_table.md)."
            ),
            (
                "The solver reference for seeds 0-29 is two committed run dirs: seeds 0-19 in "
                "`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/` and seeds 20-29 in "
                "`reference/solver-hard-seeds20to29/`. The paired table uses all 30."
            ),
            (
                f"Behaviour ([`results/behaviour_compare_v1.4.md`](results/behaviour_compare_v1.4.md)): gpt-5.5 plants 17.2 canaries "
                "and 6% interviews on day 10.2 vs reference 14.1 canaries on day 10.6; gemini-4-carbon plants 8.5 canaries, 68 interviews (53%) on day 13.2."
            ),
            f"In-process reaches 95% [62%, 140%] on hard, OpenCode reaches 111% on medium, guess_day1 averages {MINUS_SIGN}0.95.",
            "Infra retries: alternative hard is 56% [19%, 87%] of the solver (luck-adjusted 55% [34%, 77%]).",
            "Harness: only the 13 MCP tools; Harbor isolation check: 11/11; rehearsal in `results/harbor/rehearsal/`.",
            (
                "Tool errors now carry a `detail` field (28 of the 58 calls in the 30 headline episodes). "
                "One contradictory sentence about the careful mole was reworded in the medium and hard instructions. "
                "Details: [docs/DIFFICULTY.md](docs/DIFFICULTY.md)."
            ),
            f"{HASH_CHAR}{HASH_CHAR} Reproduce: one command, no API keys",
            (
                f"In the printed judge table the replayed OpenCode hard row pools all 32 committed episodes (+0.349 {PLUS_MINUS} 0.190): "
                f"seeds 0{EN_DASH}29 plus the two extension seeds 34 and 37 (`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/`). "
                f"The replayed solver row likewise pools seeds 0{EN_DASH}59 (+0.498 {PLUS_MINUS} 0.097, n=60). "
                "The last line, `HEADLINE`, recomputes it: +0.322 vs +0.499, 65% [24%, 98%]."
            ),
            f"- **Run-to-run variation.** hard +0.553 {PLUS_MINUS} 0.093 in committed table, +0.643 {PLUS_MINUS} 0.087 in [fresh](results/fresh_clone/). Spread over 300 fresh secrets.",
            f"Oracle 10-task hard rerun: +0.39 to +0.68 (mean +0.569, sd 0.094) over 200 simulated builds: [harbor](harbor/README.md{HASH_CHAR}expected-oracle-range-for-a-judge-rerun).",
            f"{HASH_CHAR}{HASH_CHAR} Tiebreak: a small model trained on Canary experience (honest result)",
            "Full readout in [docs/reports/fr8.md](docs/reports/fr8.md) (\"04:45 WS4 readout\").",
            f"| model | held-out score {PLUS_MINUS} 95% CI | n |",
            "|---|---:|---:|",
            "| base (untrained) | 0.000 (it cannot play: 3% valid tool calls) | 36 |",
            f"| v2 (SFT on solver play) | {MINUS_SIGN}0.457 {PLUS_MINUS} 0.086 | 172 |",
            f"| v3-4k (GRPO) | {MINUS_SIGN}0.147 {PLUS_MINUS} 0.063 | 180 |",
            f"| v3-8k seed 2 (GRPO) | {MINUS_SIGN}0.050 {PLUS_MINUS} 0.049 | 90 |",
            f"- Recovery (v3-4k vs v2: +0.310 {PLUS_MINUS} 0.107, two-sample), protocol (100% valid calls), whom (0.19 {RIGHT_ARROW} 0.89).",
            f"- Bar is **not met**. DAgger honest null: {MINUS_SIGN}0.542 {PLUS_MINUS} 0.214 at 8k context (n=50, partial).",
            f"{HASH_CHAR}{HASH_CHAR} The rules, briefly",
            "Hard also lists a clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4.",
            "14 scripted attack probes and 1 swarm probe; committed 40-seed battery expects `0 differences`; MCP server with 13 tools.",
        ]
    ) + "\n"
    files = {
        "README.md": readme,
        "docs/reports/gap.md": f"{HASH_CHAR} Gap\n",
        "docs/reports/fr8.md": fr8_report,
        "docs/DIFFICULTY.md": "W4. Clearance rule never binds.\n",
        "harbor/README.md": f"{HASH_CHAR} Harbor\n{HASH_CHAR}{HASH_CHAR} Expected oracle range for a judge rerun\n",
        "harbor/check_isolation.sh": "\n".join(['ok "isolated"'] * 11) + "\n",
        "results/harbor/rehearsal/README.md": f"{HASH_CHAR} Rehearsal\n",
        "results/harbor/rehearsal/TABLE.md": rehearsal_table,
        "results/behaviour_compare_v1.4.md": behaviour_md,
        "results/fresh_clone/README.md": f"solver +0.643 {PLUS_MINUS} 0.087\n",
        "results/judge_table.md": judge_table,
        "data/runs/committed/v1.4/paired_table_gemini.json": json.dumps(paired),
        "data/runs/committed/v1.4/paired_table_gemini.md": paired_md,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json": json.dumps(pooled),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl": _make_jsonl(oc_prim_pairs, 28),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl": _make_jsonl(oc_ext_pairs),
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl": _make_jsonl(sv_0_19_pairs),
        "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl": _make_jsonl(sv_20_29_pairs),
        "data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl": _make_jsonl(sv_30_59_pairs),
        "fr8/analysis/out/ws4_table_v3.md": ws4_v3,
        "fr8/analysis/out/ws4_table_8k_s1s2.md": ws4_8k,
        "fr8/analysis/out/ws4_whom_v3.md": ws4_whom,
        "results/anticheat/exploits.json": json.dumps(exploits),
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

    order_bad = clean_tmp / "order_bad"
    _build_synthetic_repo(order_bad)
    (order_bad / "README.md").write_text(
        base_files["README.md"].replace(
            "**65% [24%, 98%]**; luck-adjusted 72% [52%, 91%]",
            "luck-adjusted 72% [52%, 91%]; **65% [24%, 98%]**",
        ),
        encoding="utf-8",
    )
    errs_order = audit_readme_claims(order_bad)
    assert any("before" in e for e in errs_order)

    prereg_bad = clean_tmp / "prereg_bad"
    _build_synthetic_repo(prereg_bad)
    (prereg_bad / "README.md").write_text(
        base_files["README.md"] + "Dev seeds 0-29 were pre-registered.\n",
        encoding="utf-8",
    )
    errs_prereg = audit_readme_claims(prereg_bad)
    assert any("pre-registered" in e for e in errs_prereg)

    clearance_bad = clean_tmp / "clearance_bad"
    _build_synthetic_repo(clearance_bad)
    (clearance_bad / "README.md").write_text(
        base_files["README.md"].replace(
            "clearance rule for canaries, but it never binds; see docs/DIFFICULTY.md W4",
            "Hard adds clearance constraints and fingerprint noise",
        ),
        encoding="utf-8",
    )
    errs_clear = audit_readme_claims(clearance_bad)
    assert any("clearance" in e for e in errs_clear)

    alt_bad = clean_tmp / "alt_bad"
    _build_synthetic_repo(alt_bad)
    (alt_bad / "README.md").write_text(
        base_files["README.md"].replace("56% [19%, 87%]", "59% [19%, 87%]"),
        encoding="utf-8",
    )
    errs_alt = audit_readme_claims(alt_bad)
    assert any("56% [19%, 87%]" in e for e in errs_alt)

    detail_bad = clean_tmp / "detail_bad"
    _build_synthetic_repo(detail_bad)
    (detail_bad / "README.md").write_text(
        base_files["README.md"].replace("28 of the 58 calls", "19 of the 58 calls"),
        encoding="utf-8",
    )
    errs_detail = audit_readme_claims(detail_bad)
    assert any("28 of the 58 calls" in e for e in errs_detail)

    pool_bad = clean_tmp / "pool_bad"
    _build_synthetic_repo(pool_bad)
    (pool_bad / "README.md").write_text(
        base_files["README.md"].replace("+0.349", "+0.322"),
        encoding="utf-8",
    )
    errs_pool = audit_readme_claims(pool_bad)
    assert any("+0.349 +/- 0.190" in e for e in errs_pool)

    sv_split_bad = clean_tmp / "sv_split_bad"
    _build_synthetic_repo(sv_split_bad)
    bad_sv_20_29 = [(19, 0.53)] + [
        (21, 0.73), (22, 0.4), (23, 0.32), (24, 0.31),
        (25, 0.58), (26, 0.69), (27, 0.72), (28, 0.75), (29, 0.65),
    ]
    (sv_split_bad / "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl").write_text(
        _make_jsonl(bad_sv_20_29),
        encoding="utf-8",
    )
    errs_sv_split = audit_readme_claims(sv_split_bad)
    assert any("20..29" in e or "partition" in e for e in errs_sv_split)

    ws4_bad = clean_tmp / "ws4_bad"
    _build_synthetic_repo(ws4_bad)
    (ws4_bad / "README.md").write_text(
        base_files["README.md"].replace("not met", "is met").replace("0.89", "0.94"),
        encoding="utf-8",
    )
    errs_ws4 = audit_readme_claims(ws4_bad)
    assert any("not met" in e for e in errs_ws4)
    assert any("0.19 -> 0.89" in e for e in errs_ws4)

    probe_bad = clean_tmp / "probe_bad"
    _build_synthetic_repo(probe_bad)
    (probe_bad / "README.md").write_text(
        base_files["README.md"].replace("14 scripted attack probes", "13 scripted attack probes"),
        encoding="utf-8",
    )
    errs_probe = audit_readme_claims(probe_bad)
    assert any("14 scripted attack probes and 1 swarm probe" in e for e in errs_probe)

    band_bad = clean_tmp / "band_bad"
    _build_synthetic_repo(band_bad)
    (band_bad / "README.md").write_text(
        base_files["README.md"].replace("+0.553", "+0.890"),
        encoding="utf-8",
    )
    errs_band = audit_readme_claims(band_bad)
    assert any("+0.890" in e and "band" in e for e in errs_band)

    jt_band_bad = clean_tmp / "jt_band_bad"
    _build_synthetic_repo(jt_band_bad)
    (jt_band_bad / "results" / "judge_table.md").write_text(
        base_files["results/judge_table.md"].replace("+0.625", "+0.150"),
        encoding="utf-8",
    )
    errs_jt = audit_readme_claims(jt_band_bad)
    assert any("+0.150" in e and "band" in e for e in errs_jt)

    gpt_bad = clean_tmp / "gpt_bad"
    _build_synthetic_repo(gpt_bad)
    (gpt_bad / "README.md").write_text(
        base_files["README.md"].replace("101% [79%, 140%]", "99% [79%, 140%]"),
        encoding="utf-8",
    )
    errs_gpt = audit_readme_claims(gpt_bad)
    assert any("gpt-5.5 OpenCode table row mismatch" in e for e in errs_gpt)

    reh_bad = clean_tmp / "reh_bad"
    _build_synthetic_repo(reh_bad)
    (reh_bad / "README.md").write_text(
        base_files["README.md"].replace("93% / 116% / 131%", "93% / 116% / 140%"),
        encoding="utf-8",
    )
    errs_reh = audit_readme_claims(reh_bad)
    assert any("Harbor judge path table row mismatch" in e for e in errs_reh)

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
