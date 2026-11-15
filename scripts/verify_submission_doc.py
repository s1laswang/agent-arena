"""Keyless read-only verifier for docs/SUBMISSION.md and docs/gemini/SUBMISSION.md.

    python scripts/verify_submission_doc.py [--root .] [--json]

Runs four fast (<2s) read-only checks with zero API calls and zero mutations:
  1. AfterQuery SUBMISSION.md Structure & Form Bounds
  2. AfterQuery SUBMISSION.md Numeric Provenance
  3. Gemini SUBMISSION.md Provenance
  4. Post-edd4fe6d Refresh & Cross-Doc Sync
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)

CHECK_AQ_STRUCTURE = "AfterQuery SUBMISSION.md Structure & Form Bounds"
CHECK_AQ_NUMBERS = "AfterQuery SUBMISSION.md Numeric Provenance"
CHECK_GEMINI_PROV = "Gemini SUBMISSION.md Provenance"
CHECK_POST_EDD4_SYNC = "Post-edd4fe6d Refresh & Cross-Doc Sync"
CHECK_POST_EDD4_ADVISORY = CHECK_POST_EDD4_SYNC

CHECK_NAMES: tuple[str, ...] = (
    CHECK_AQ_STRUCTURE,
    CHECK_AQ_NUMBERS,
    CHECK_GEMINI_PROV,
    CHECK_POST_EDD4_SYNC,
)

MAX_TAGLINE_CHARS = 120
MAX_DESCRIPTION_CHARS = 1000
MAX_DESCRIPTION_LABEL_DELTA = 5
MAX_GEMINI_SHORT_CHARS = 600

EXTERNAL_SCHEMES: tuple[str, ...] = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "//",
)

GITIGNORED_SCRATCH_PATHS: frozenset[str] = frozenset({
    "results/latest",
    "results/latest/",
    "harbor/dataset",
    "harbor/dataset/",
})

LOCAL_PATH_PREFIXES: tuple[str, ...] = (
    "canary/",
    "scripts/",
    "tests/",
    "results/",
    "docs/",
    "data/",
    "harbor/",
    "game/",
    "fr8/",
    "pitch/",
    ".github/",
)

FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"(`+)([^`\n]+?)\1")
EXT_MD_LINK_RX = re.compile(r"!?\[[^\]]*\]\((?:https?://|mailto:)[^)\n]+\)", re.IGNORECASE)
MD_LINK_OR_IMG_RX = re.compile(
    r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _normalize_numeric_text(text: str) -> str:
    out = text.replace(MINUS_SIGN, "-").replace(EN_DASH, "-")
    out = out.replace(PLUS_MINUS, "+/-")
    return re.sub(r"[ \t]+", " ", out)


def _pct(val: float) -> str:
    return f"{float(val) * 100.0:.0f}%"


def _pct_band(ratio: float, lo: float, hi: float) -> str:
    return f"{_pct(ratio)} [{_pct(lo)}, {_pct(hi)}]"


def _pct_band_plain_ci(pct_val: int | float, lo_val: int | float, hi_val: int | float) -> str:
    return f"{int(round(float(pct_val)))}% [{int(round(float(lo_val)))}, {int(round(float(hi_val)))}]"


def _comma_int(val: int) -> str:
    return f"{int(val):,}"


def _has_token(norm_text: str, tok: str) -> bool:
    norm_tok = _normalize_numeric_text(tok)
    pat = r"(?<![0-9])(?<!\d\.)" + re.escape(norm_tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pat, norm_text) is not None


def _require_token(norm_text: str, doc_label: str, desc: str, tok: str, failures: list[str]) -> None:
    if not tok or not tok.strip():
        failures.append(f"{doc_label} empty expected token for {desc}")
        return
    if not _has_token(norm_text, tok):
        failures.append(f"{doc_label} missing {desc} '{tok}'")


def _require_any_token(
    norm_text: str,
    doc_label: str,
    desc: str,
    candidates: Sequence[str],
    failures: list[str],
) -> None:
    valid_cands = [c for c in candidates if c and c.strip()]
    if not valid_cands:
        failures.append(f"{doc_label} empty expected candidates for {desc}")
        return
    if not any(_has_token(norm_text, cand) for cand in valid_cands):
        failures.append(f"{doc_label} missing {desc} '{valid_cands[0]}'")


_TEXT_FILE_CACHE: dict[tuple[str, int, int], str] = {}
_JSON_FILE_CACHE: dict[tuple[str, int, int], Any] = {}


def _read_text(root: Path, rel: str, failures: list[str]) -> str | None:
    path = root / rel
    if not path.is_file():
        failures.append(f"missing required file: {rel}")
        return None
    ckey: tuple[str, int, int] | None = None
    try:
        real_p = os.path.realpath(path)
        st = os.stat(real_p)
        ckey = (real_p, st.st_mtime_ns, st.st_size)
        cached = _TEXT_FILE_CACHE.get(ckey)
        if cached is not None:
            return cached
        txt = path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"unreadable text file {rel}: {type(exc).__name__}")
        return None
    if not txt.strip():
        failures.append(f"empty or whitespace-only file: {rel}")
        return None
    if ckey is not None:
        _TEXT_FILE_CACHE[ckey] = txt
    return txt


def _load_json(root: Path, rel: str, failures: list[str], cache: dict[str, Any] | None = None) -> Any:
    if cache is not None and rel in cache:
        return cache[rel]
    path = root / rel
    ckey: tuple[str, int, int] | None = None
    if path.is_file():
        try:
            real_p = os.path.realpath(path)
            st = os.stat(real_p)
            ckey = (real_p, st.st_mtime_ns, st.st_size)
            if ckey in _JSON_FILE_CACHE:
                parsed = _JSON_FILE_CACHE[ckey]
                if cache is not None:
                    cache[rel] = parsed
                return parsed
        except OSError:
            ckey = None
    txt = _read_text(root, rel, failures)
    if txt is None:
        return None
    try:
        parsed = json.loads(txt)
    except ValueError as exc:
        failures.append(f"invalid JSON in {rel}: {exc}")
        return None
    if ckey is not None:
        _JSON_FILE_CACHE[ckey] = parsed
    if cache is not None:
        cache[rel] = parsed
    return parsed


def _strip_fences_preserving_lines(md_text: str) -> list[str]:
    out: list[str] = []
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
                out.append("")
                continue
            out.append(raw_line)
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            out.append("")
    return out


def _parse_md_dest(angle_group: str | None, paren_group: str | None) -> str:
    if angle_group is not None:
        return angle_group.strip()
    raw = (paren_group or "").strip()
    if not raw:
        return ""
    return raw.split()[0].strip()


def _verify_internal_links_and_paths(root: Path, doc_rel: str, md_text: str, failures: list[str]) -> tuple[int, int]:
    root_resolved = root.resolve()
    doc_path = Path(os.path.normpath(str(root_resolved / doc_rel)))
    non_fence_lines = _strip_fences_preserving_lines(md_text)
    checked_links = 0
    checked_paths = 0

    for lineno, raw_line in enumerate(non_fence_lines, 1):
        line_no_code = INLINE_CODE_RX.sub("", raw_line)
        if "[" in line_no_code and "(" in line_no_code:
            for m in MD_LINK_OR_IMG_RX.finditer(line_no_code):
                dest = _parse_md_dest(m.group(1), m.group(2))
                if not dest or dest.lower().startswith(EXTERNAL_SCHEMES) or dest.startswith(HASH_CHAR):
                    continue
                path_part = unquote(dest.split(HASH_CHAR, 1)[0].split("?", 1)[0]).strip()
                if not path_part:
                    continue
                checked_links += 1
                resolved = Path(os.path.normpath(str(doc_path.parent / path_part)))
                try:
                    rel_target = resolved.relative_to(root_resolved).as_posix()
                except ValueError:
                    failures.append(f"{doc_rel}:{lineno}: relative link '{dest}' resolves outside root")
                    continue
                if rel_target in GITIGNORED_SCRATCH_PATHS:
                    continue
                if path_part.endswith("/"):
                    if not resolved.is_dir():
                        failures.append(
                            f"{doc_rel}:{lineno}: broken directory link '{dest}' (missing '{rel_target}/')"
                        )
                elif not resolved.exists():
                    failures.append(
                        f"{doc_rel}:{lineno}: broken relative link '{dest}' (missing '{rel_target}')"
                    )

        line_no_ext = EXT_MD_LINK_RX.sub("", raw_line)
        if re.search(r"\bon\s+branch\s+`?[A-Za-z0-9_./-]+`?", line_no_ext, re.IGNORECASE):
            if "justsilas" not in line_no_ext.lower():
                continue
        for cm in INLINE_CODE_RX.finditer(line_no_ext):
            span = cm.group(2).strip()
            if not span or " " in span or "*" in span or "<" in span or ">" in span or "{" in span:
                continue
            clean_span = span.rstrip(".,;:")
            if clean_span in GITIGNORED_SCRATCH_PATHS or clean_span.rstrip("/") in GITIGNORED_SCRATCH_PATHS:
                continue
            if clean_span == "Makefile" or clean_span.startswith(LOCAL_PATH_PREFIXES):
                checked_paths += 1
                cand = Path(os.path.normpath(str(root_resolved / clean_span.rstrip("/"))))
                try:
                    cand.relative_to(root_resolved)
                except ValueError:
                    failures.append(f"{doc_rel}:{lineno}: referenced path '{clean_span}' escapes root")
                    continue
                if clean_span.endswith("/"):
                    if not cand.is_dir():
                        failures.append(
                            f"{doc_rel}:{lineno}: referenced directory `{clean_span}` missing on disk"
                        )
                elif not cand.exists():
                    failures.append(
                        f"{doc_rel}:{lineno}: referenced file `{clean_span}` missing on disk"
                    )

    return checked_links, checked_paths


def _extract_final_results_block(md_text: str) -> tuple[str, str, int] | None:
    sec_m = re.search(
        rf"^\s*{HASH_CHAR}{{2,3}}\s+Final\s+results\b([^\n]*)\n([\s\S]*?)(?=^\s*{HASH_CHAR}{{2,3}}\s+|\Z)",
        md_text,
        re.IGNORECASE | re.MULTILINE,
    )
    if sec_m is None:
        return None
    return sec_m.group(1).strip(), sec_m.group(2), sec_m.start()


def _extract_form_block(md_text: str) -> str | None:
    sec_m = re.search(
        rf"^\s*{HASH_CHAR}{{2,3}}\s+Form\s+fields\b[^\n]*\n([\s\S]*?)(?=^\s*{HASH_CHAR}{{2,3}}\s+|\Z)",
        md_text,
        re.IGNORECASE | re.MULTILINE,
    )
    if sec_m is None:
        return None
    sec_body = sec_m.group(1)
    fence_m = re.search(r"```[A-Za-z0-9_-]*\n([\s\S]*?)```", sec_body)
    return fence_m.group(1) if fence_m is not None else sec_body


def check_afterquery_structure(root: Path = ROOT) -> CheckResult:
    name = CHECK_AQ_STRUCTURE
    failures: list[str] = []
    doc_rel = "docs/SUBMISSION.md"
    sub_txt = _read_text(root, doc_rel, failures)
    if sub_txt is None:
        return CheckResult(name, "FAIL", f"missing or unreadable {doc_rel}", failures)

    form_block = _extract_form_block(sub_txt)
    form_haystack = form_block if form_block is not None else sub_txt
    if form_block is None:
        failures.append(f"{doc_rel}: missing '{HASH_CHAR}{HASH_CHAR} Form fields' section")

    if re.search(r"^\s*Project\s+name:\s*Canary\s*$", form_haystack, re.MULTILINE) is None:
        failures.append(f"{doc_rel}: missing Form field 'Project name: Canary'")

    tag_m = re.search(
        r"^\s*Tagline(?:\s*\((\d+)\s*chars?\))?:\s*\n([^\n]+)",
        form_haystack,
        re.MULTILINE,
    )
    tagline_len = 0
    if tag_m is None:
        failures.append(f"{doc_rel}: missing Form field 'Tagline' with non-empty line")
    else:
        tagline_body = tag_m.group(2).strip()
        tagline_len = len(tagline_body)
        if tagline_len == 0 or tagline_len > MAX_TAGLINE_CHARS:
            failures.append(
                f"{doc_rel}: Tagline length {tagline_len} outside [1, {MAX_TAGLINE_CHARS}] chars"
            )
        if tag_m.group(1) is not None:
            stated_tag = int(tag_m.group(1))
            if stated_tag != tagline_len:
                failures.append(
                    f"{doc_rel}: Tagline stated ({stated_tag} chars) != actual ({tagline_len} chars)"
                )

    desc_m = re.search(
        r"^\s*Description(?:\s*\((\d+)\s*chars?\))?:\s*\n([\s\S]+?)(?:\n\s*\n|\Z)",
        form_haystack,
        re.MULTILINE,
    )
    desc_len = 0
    stated_desc_note = ""
    if desc_m is None:
        failures.append(f"{doc_rel}: missing Form field 'Description' paragraph")
    else:
        desc_body = desc_m.group(2).strip()
        desc_len = len(desc_body)
        if desc_len < 50 or desc_len >= MAX_DESCRIPTION_CHARS:
            failures.append(
                f"{doc_rel}: Description length {desc_len} outside [50, {MAX_DESCRIPTION_CHARS - 1}] chars"
            )
        if desc_m.group(1) is not None:
            stated_desc = int(desc_m.group(1))
            stated_desc_note = f" (stated {stated_desc})"
            if abs(stated_desc - desc_len) > MAX_DESCRIPTION_LABEL_DELTA:
                failures.append(
                    f"{doc_rel}: Description stated ({stated_desc} chars) != actual ({desc_len} chars) "
                    f"(delta {abs(stated_desc - desc_len)} > {MAX_DESCRIPTION_LABEL_DELTA})"
                )

    if re.search(r"^\s*Track:\s*AfterQuery\b", form_haystack, re.MULTILINE) is None:
        failures.append(f"{doc_rel}: missing Form field 'Track: AfterQuery'")

    missing_secs: list[str] = []
    out_of_order: list[str] = []
    last_pos = -1
    for sec_num in range(1, 10):
        sec_rx = re.compile(rf"^\s*{HASH_CHAR}{{2,3}}\s+{sec_num}\.\s+\S", re.MULTILINE)
        m = sec_rx.search(sub_txt)
        if m is None:
            missing_secs.append(f"{HASH_CHAR}{HASH_CHAR} {sec_num}.")
        else:
            if m.start() <= last_pos:
                out_of_order.append(f"{HASH_CHAR}{HASH_CHAR} {sec_num}.")
            last_pos = m.start()
    if missing_secs:
        failures.append(f"{doc_rel}: missing numbered section(s): {', '.join(missing_secs)}")
    if out_of_order:
        failures.append(f"{doc_rel}: out-of-order numbered section(s): {', '.join(out_of_order)}")

    link_count, path_count = _verify_internal_links_and_paths(root, doc_rel, sub_txt, failures)

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} structure/form/link violation(s) in {doc_rel}",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"Form fields verified (Tagline {tagline_len} chars, Description {desc_len} chars{stated_desc_note}, Track: AfterQuery), "
        f"sections 1-9 in order, {link_count} relative links and {path_count} repo paths exist on disk",
    )


def _find_paired_row(
    rows: list[dict[str, Any]],
    group_substr: str,
    tier: str,
    *,
    alternative: bool = False,
    agent: str | None = None,
    n_expected: int | None = None,
) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict) or row.get("tier") != tier:
            continue
        grp = str(row.get("group", ""))
        if group_substr not in grp:
            continue
        if agent is not None and row.get("agent") != agent:
            continue
        if n_expected is not None and row.get("n") != n_expected:
            continue
        lbl = str(row.get("label", "")).lower()
        is_alt = "alternative" in lbl or "not the headline" in lbl
        if is_alt != alternative:
            continue
        return row
    return None


def _parse_judge_table_paired(md_text: str) -> tuple[str | None, str | None, dict[tuple[str, str], str]]:
    fp_m = re.search(r"fingerprint\s+`([0-9a-f]{8,})`", md_text)
    git_m = re.search(r"git:\s*`([0-9a-f]{7,})`", md_text)
    scores: dict[tuple[str, str], str] = {}
    cur_tier: str | None = None
    in_paired = False
    headers: list[str] | None = None
    tier_rx = re.compile(rf"^{HASH_CHAR}{HASH_CHAR}\s+(easy|medium|hard)\b", re.IGNORECASE)

    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        tm = tier_rx.match(stripped)
        if tm:
            cur_tier = tm.group(1).lower()
            in_paired = False
            headers = None
            continue
        if stripped.lower().startswith("paired runs"):
            in_paired = True
            headers = None
            continue
        if stripped.lower().startswith(("reported agent runs", "history:")):
            in_paired = False
            headers = None
            continue
        if not in_paired or cur_tier is None:
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [_normalize_numeric_text(c).lower() for c in cells]
            continue
        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        agent_name = row.get("agent", "").strip()
        score_cell = next((v for k, v in row.items() if k.startswith("score")), "").strip()
        if agent_name and score_cell:
            scores[(cur_tier, agent_name)] = _normalize_numeric_text(score_cell)

    return (
        fp_m.group(1) if fp_m else None,
        git_m.group(1) if git_m else None,
        scores,
    )


def _parse_skill_ladder_deltas(md_text: str) -> dict[tuple[str, str], str]:
    deltas: dict[tuple[str, str], str] = {}
    cur_tier: str | None = None
    headers: list[str] | None = None
    tier_rx = re.compile(rf"^{HASH_CHAR}{HASH_CHAR}\s+(easy|medium|hard)\s*$", re.IGNORECASE)

    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        tm = tier_rx.match(stripped)
        if tm:
            cur_tier = tm.group(1).lower()
            headers = None
            continue
        if stripped.startswith(f"{HASH_CHAR}{HASH_CHAR} "):
            cur_tier = None
            headers = None
            continue
        if cur_tier is None or not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [_normalize_numeric_text(c).lower() for c in cells]
            continue
        if len(cells) >= 6:
            rung = cells[0].split()[0].strip()
            delta_val = _normalize_numeric_text(cells[4]).strip()
            delta_ci = _normalize_numeric_text(cells[5]).strip()
            deltas[(cur_tier, rung)] = f"{delta_val} +/- {delta_ci}"
    return deltas


def _parse_rehearsal_table(md_text: str) -> tuple[str | None, list[tuple[str, str, int, int]], bool]:
    norm = _normalize_numeric_text(md_text)
    oracle_mean: str | None = None
    mean_row_m = re.search(
        r"\|\s*\*\*mean\s*\(valid\s+trials\)\*\*\s*\|\s*\*\*([+-]?[0-9.]+)\*\*",
        norm,
        re.IGNORECASE,
    )
    if mean_row_m:
        oracle_mean = mean_row_m.group(1)

    runs: list[tuple[str, str, int, int]] = []
    zero_ok = True
    for raw_line in norm.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if len(cells) < 7:
            continue
        rname = cells[0]
        if rname.startswith("opencode-"):
            pct_m = re.match(r"(\d+)%", cells[6])
            if pct_m and cells[1].isdigit():
                runs.append((rname, cells[4], int(cells[1]), int(pct_m.group(1))))
        elif rname in ("do_nothing", "stop_early") and cells[1].isdigit():
            if int(cells[1]) != 10 or not cells[4].startswith("+0.000"):
                zero_ok = False

    corr_m = re.search(
        r"Final:\s*run\s*3\s+has\s+(\d+)\s+valid\s+trials[^;\n]*,\s*mean\s+([+-]?[0-9.]+)\s*=\s*(\d+)%",
        norm,
        re.IGNORECASE,
    )
    if corr_m:
        c_n = int(corr_m.group(1))
        c_mean = corr_m.group(2)
        c_pct = int(corr_m.group(3))
        runs = [
            ("opencode-3", c_mean, c_n, c_pct) if r[0] == "opencode-3" else r
            for r in runs
        ]

    return oracle_mean, runs, zero_ok


def _parse_behaviour_compare(md_text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    headers: list[str] | None = None
    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [_normalize_numeric_text(c).lower() for c in cells]
            continue
        row = {headers[i]: _normalize_numeric_text(cells[i]) for i in range(min(len(headers), len(cells)))}
        ag = row.get("agent", "")
        if ag:
            out[ag] = row
    return out


def _parse_redteam_1000_summary(md_text: str) -> tuple[int | None, int | None]:
    att_m = re.search(r"\*\*(\d+)\s+Gemini\s+attackers\*\*", md_text)
    exp_m = re.search(r"Verified\s+exploits:\s*\*\*(\d+)\*\*", md_text)
    return (
        int(att_m.group(1)) if att_m else None,
        int(exp_m.group(1)) if exp_m else None,
    )


def _parse_ws4_all_rows(md_text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    headers: list[str] | None = None
    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [_normalize_numeric_text(c).lower() for c in cells]
            continue
        row = {headers[i]: _normalize_numeric_text(cells[i]) for i in range(min(len(headers), len(cells)))}
        if row.get("tier", "").lower() == "all":
            model_key = row.get("model", "").strip()
            if model_key:
                rows[model_key] = row
    return rows


def check_afterquery_provenance(
    root: Path = ROOT,
    *,
    _json_cache: dict[str, Any] | None = None,
) -> CheckResult:
    name = CHECK_AQ_NUMBERS
    failures: list[str] = []
    cache = _json_cache if _json_cache is not None else {}

    doc_rel = "docs/SUBMISSION.md"
    sub_raw = _read_text(root, doc_rel, failures)
    if sub_raw is None:
        return CheckResult(name, "FAIL", f"missing or unreadable {doc_rel}", failures)
    sub_norm = _normalize_numeric_text(sub_raw)

    paired_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    pooled_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    jt_rel = "results/judge_table.md"
    or_rel = "results/oracle_range_v1.4.json"
    sl_rel = "results/skill_ladder_v1.4.md"
    fa_rel = "results/failure_analysis_v1.4.json"
    regret_rel = "results/regret_opencode-gemini-4-carbon-v1.4.md"
    fresh_rel = "results/fresh_table_v1.4.md"
    ex_rel = "results/anticheat/exploits.json"
    corpus_rel = "results/anticheat/corpus_eval.txt"
    swarm_rel = "results/gemini/swarm.json"
    ws4_rel = "fr8/analysis/out/ws4_table_v3.md"
    ws4_hist_rel = "fr8/analysis/out/ws4_table_v3s0_n180.md"
    gap_rel = "docs/reports/gap.md"
    dry_rel = "results/harbor/rehearsal-dry/TABLE.md"
    reh_rel = "results/harbor/rehearsal/TABLE.md"
    beh_rel = "results/behaviour_compare_v1.4.md"
    rt1k_rel = "results/redteam_1000/summary.md"

    paired_obj = _load_json(root, paired_rel, failures, cache)
    pooled_obj = _load_json(root, pooled_rel, failures, cache)
    jt_txt = _read_text(root, jt_rel, failures)
    or_obj = _load_json(root, or_rel, failures, cache)
    sl_txt = _read_text(root, sl_rel, failures)
    fa_obj = _load_json(root, fa_rel, failures, cache)
    regret_txt = _read_text(root, regret_rel, failures)
    fresh_txt = _read_text(root, fresh_rel, failures)
    ex_obj = _load_json(root, ex_rel, failures, cache)
    corpus_txt = _read_text(root, corpus_rel, failures)
    swarm_obj = _load_json(root, swarm_rel, failures, cache)
    ws4_txt = _read_text(root, ws4_rel, failures)
    ws4_hist_txt = _read_text(root, ws4_hist_rel, failures) if (root / ws4_hist_rel).is_file() else None
    gap_txt = _read_text(root, gap_rel, failures)
    dry_txt = _read_text(root, dry_rel, failures)
    reh_txt = _read_text(root, reh_rel, failures)
    beh_txt = _read_text(root, beh_rel, failures)
    rt1k_txt = _read_text(root, rt1k_rel, failures)

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} missing/invalid provenance artifact(s)", failures)

    checked_metrics = 0

    assert reh_txt is not None and beh_txt is not None and rt1k_txt is not None
    reh_oracle, reh_runs, reh_zero_ok = _parse_rehearsal_table(reh_txt)
    if reh_oracle is None or len(reh_runs) < 3 or not reh_zero_ok:
        failures.append(f"{reh_rel}: missing valid oracle/opencode/zero-baseline rehearsal summary")
    else:
        _require_token(sub_norm, doc_rel, "Harbor rehearsal oracle mean", f"oracle {reh_oracle}", failures)
        for rname, rmean, rn_val, rpct in reh_runs:
            _require_token(sub_norm, doc_rel, f"Harbor rehearsal {rname} mean", rmean, failures)
            _require_token(sub_norm, doc_rel, f"Harbor rehearsal {rname} ratio", f"{rpct}%", failures)
            if rn_val < 10:
                _require_token(
                    sub_norm,
                    doc_rel,
                    f"Harbor rehearsal {rname} partial valid count",
                    f"{rn_val} valid trials",
                    failures,
                )
        if len(reh_runs) == 3:
            _require_token(
                sub_norm,
                doc_rel,
                "Harbor rehearsal 3-run ratio sequence",
                f"{reh_runs[0][3]}%, {reh_runs[1][3]}% and {reh_runs[2][3]}%",
                failures,
            )
            checked_metrics += 1
        checked_metrics += 1 + 2 * len(reh_runs)

    beh_rows = _parse_behaviour_compare(beh_txt)
    beh_gpt = next((v for k, v in beh_rows.items() if k.startswith("gpt-5.5")), None)
    beh_gem = next((v for k, v in beh_rows.items() if k.startswith("gemini-4-carbon")), None)
    if beh_gpt is None or beh_gem is None:
        failures.append(f"{beh_rel}: missing gpt-5.5 or gemini-4-carbon behaviour row")
    else:
        gem_share = beh_gem.get("share of calls that are interviews", "")
        gem_can = beh_gem.get("canaries planted", "")
        gpt_can = beh_gpt.get("canaries planted", "")
        _require_token(sub_norm, doc_rel, "behaviour compare Gemini interview share", gem_share, failures)
        _require_token(sub_norm, doc_rel, "behaviour compare Gemini canaries", f"{gem_can} canaries", failures)
        _require_token(sub_norm, doc_rel, "behaviour compare gpt-5.5 canaries", f"gpt-5.5's {gpt_can}", failures)
        checked_metrics += 3

    rt_att, rt_exp = _parse_redteam_1000_summary(rt1k_txt)
    if rt_att is None or rt_exp is None or rt_att < 1000 or rt_exp != 0:
        failures.append(f"{rt1k_rel}: expected >=1000 Gemini attackers and 0 verified exploits")
    else:
        _require_any_token(
            sub_norm,
            doc_rel,
            "red-team 1000+ sweep count",
            (f"{_comma_int(rt_att)}-attack", f"{rt_att}-attack", _comma_int(rt_att)),
            failures,
        )
        _require_token(sub_norm, doc_rel, "red-team sweep 0 exploits", "0 exploits", failures)
        checked_metrics += 2

    if not isinstance(paired_obj, list):
        failures.append(f"{paired_rel}: expected JSON list")
    else:
        oc_hard = _find_paired_row(paired_obj, "v1.4/opencode-gemini-4-carbon", "hard")
        oc_hard_alt = _find_paired_row(
            paired_obj, "v1.4/opencode-gemini-4-carbon", "hard", alternative=True
        )
        oc_med = _find_paired_row(paired_obj, "v1.4/opencode-gemini-4-carbon", "medium")
        ip_hard = _find_paired_row(paired_obj, "v1.4/inproc-gemini-4-carbon", "hard")
        ip_med = _find_paired_row(paired_obj, "v1.4/inproc-gemini-4-carbon", "medium")
        fl_hard = _find_paired_row(paired_obj, "v1.4/opencode-gemini-3.5-flash", "hard")
        gpt55_hard = _find_paired_row(paired_obj, "v1.4/opencode-gpt-5.5", "hard")
        sv_hard = _find_paired_row(paired_obj, "v1.4/reference", "hard", agent="solver")

        for label, row_obj in (
            ("OpenCode carbon hard", oc_hard),
            ("OpenCode carbon hard empty-reply=0", oc_hard_alt),
            ("OpenCode carbon medium", oc_med),
            ("in-process carbon hard", ip_hard),
            ("in-process carbon medium", ip_med),
            ("OpenCode gemini-3.5-flash hard", fl_hard),
            ("OpenCode gpt-5.5 hard", gpt55_hard),
            ("reference solver hard", sv_hard),
        ):
            if row_obj is None:
                failures.append(f"{paired_rel}: missing required row '{label}'")

        if (
            oc_hard is not None
            and oc_hard_alt is not None
            and oc_med is not None
            and ip_hard is not None
            and ip_med is not None
            and fl_hard is not None
            and gpt55_hard is not None
            and sv_hard is not None
        ):
            oc_mean_ci = f"{float(oc_hard['mean']):.3f} +/- {float(oc_hard['ci']):.3f}"
            sv_mean_ci = f"{float(sv_hard['mean']):.3f} +/- {float(sv_hard['ci']):.3f}"
            oc_raw = _pct_band(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"])
            oc_la = _pct_band(
                oc_hard["post_expected_ratio"],
                oc_hard["post_expected_lo"],
                oc_hard["post_expected_hi"],
            )
            oc_diff = f"{float(oc_hard['diff']):+.3f} +/- {float(oc_hard['diff_ci']):.3f}"
            diff_lo = f"{float(oc_hard['diff']) - float(oc_hard['diff_ci']):+.3f}"
            diff_hi = f"{float(oc_hard['diff']) + float(oc_hard['diff_ci']):+.3f}"

            alt_raw = _pct_band(oc_hard_alt["ratio"], oc_hard_alt["ratio_lo"], oc_hard_alt["ratio_hi"])
            alt_la = _pct_band(
                oc_hard_alt["post_expected_ratio"],
                oc_hard_alt["post_expected_lo"],
                oc_hard_alt["post_expected_hi"],
            )

            med_raw = _pct_band(oc_med["ratio"], oc_med["ratio_lo"], oc_med["ratio_hi"])
            med_la = _pct_band(
                oc_med["post_expected_ratio"],
                oc_med["post_expected_lo"],
                oc_med["post_expected_hi"],
            )
            med_diff = f"{float(oc_med['diff']):+.3f} +/- {float(oc_med['diff_ci']):.3f}"

            ip_h_raw = _pct_band(ip_hard["ratio"], ip_hard["ratio_lo"], ip_hard["ratio_hi"])
            ip_h_la = _pct_band(
                ip_hard["post_expected_ratio"],
                ip_hard["post_expected_lo"],
                ip_hard["post_expected_hi"],
            )
            ip_h_diff = f"{float(ip_hard['diff']):+.3f} +/- {float(ip_hard['diff_ci']):.3f}"

            ip_m_raw = _pct_band(ip_med["ratio"], ip_med["ratio_lo"], ip_med["ratio_hi"])
            ip_m_la = _pct_band(
                ip_med["post_expected_ratio"],
                ip_med["post_expected_lo"],
                ip_med["post_expected_hi"],
            )
            ip_m_diff = f"{float(ip_med['diff']):+.3f} +/- {float(ip_med['diff_ci']):.3f}"

            fl_raw = _pct_band(fl_hard["ratio"], fl_hard["ratio_lo"], fl_hard["ratio_hi"])
            fl_la = _pct_band(
                fl_hard["post_expected_ratio"],
                fl_hard["post_expected_lo"],
                fl_hard["post_expected_hi"],
            )
            fl_diff = f"{float(fl_hard['diff']):+.3f} +/- {float(fl_hard['diff_ci']):.3f}"

            gpt55_raw = _pct_band(gpt55_hard["ratio"], gpt55_hard["ratio_lo"], gpt55_hard["ratio_hi"])

            form_block = _extract_form_block(sub_raw)
            if form_block is not None:
                form_norm = _normalize_numeric_text(form_block)
                raw_pct = _pct(oc_hard["ratio"])
                raw_lo_num = f"{float(oc_hard['ratio_lo']) * 100.0:.0f}"
                raw_hi_num = f"{float(oc_hard['ratio_hi']) * 100.0:.0f}%"
                _require_token(form_norm, f"{doc_rel} (Form)", "raw ratio", raw_pct, failures)
                _require_token(
                    form_norm,
                    f"{doc_rel} (Form)",
                    "raw CI range",
                    f"CI {raw_lo_num}-{raw_hi_num}",
                    failures,
                )
                _require_token(
                    form_norm, f"{doc_rel} (Form)", "primary sample size", f"n={int(oc_hard['n'])}", failures
                )
                if reh_runs:
                    min_rp = min(r[3] for r in reh_runs)
                    max_rp = max(r[3] for r in reh_runs)
                    _require_token(
                        form_norm,
                        f"{doc_rel} (Form)",
                        "Harbor judge-path range",
                        f"{min_rp}-{max_rp}%, {len(reh_runs)} runs",
                        failures,
                    )
                _require_token(
                    form_norm,
                    f"{doc_rel} (Form)",
                    "gpt-5.5 parity summary",
                    "gpt-5.5 matches the solver",
                    failures,
                )
                _require_token(
                    form_norm,
                    f"{doc_rel} (Form)",
                    "red-team attack count",
                    "1,000+ attacks",
                    failures,
                )
                checked_metrics += 6

            paired_checks = [
                ("OpenCode carbon hard mean +/- CI", oc_mean_ci),
                ("solver hard mean +/- CI", sv_mean_ci),
                ("OpenCode carbon hard raw ratio + CI", oc_raw),
                ("OpenCode carbon hard luck-adjusted ratio + CI", oc_la),
                ("OpenCode carbon hard paired diff +/- CI", oc_diff),
                ("OpenCode carbon hard paired diff lower bound", diff_lo),
                ("OpenCode carbon hard paired diff upper bound", diff_hi),
                ("OpenCode carbon hard empty-reply=0 raw ratio + CI", alt_raw),
                ("OpenCode carbon hard empty-reply=0 luck-adjusted ratio + CI", alt_la),
                ("OpenCode carbon medium raw ratio + CI", med_raw),
                ("OpenCode carbon medium luck-adjusted ratio + CI", med_la),
                ("OpenCode carbon medium paired diff +/- CI", med_diff),
                ("in-process carbon hard raw ratio + CI", ip_h_raw),
                ("in-process carbon hard luck-adjusted ratio + CI", ip_h_la),
                ("in-process carbon hard paired diff +/- CI", ip_h_diff),
                ("in-process carbon medium raw ratio + CI", ip_m_raw),
                ("in-process carbon medium luck-adjusted ratio + CI", ip_m_la),
                ("in-process carbon medium paired diff +/- CI", ip_m_diff),
                ("gemini-3.5-flash hard raw ratio + CI", fl_raw),
                ("gemini-3.5-flash hard luck-adjusted ratio + CI", fl_la),
                ("gemini-3.5-flash hard paired diff +/- CI", fl_diff),
                ("gpt-5.5 hard raw ratio + CI", gpt55_raw),
                (
                    "OpenCode vs solver accuracy",
                    f"{float(oc_hard['accuracy']):.2f} vs {float(sv_hard['accuracy']):.2f}",
                ),
                (
                    "OpenCode vs solver mean P(accused)",
                    f"{float(oc_hard['p_accused']):.2f} vs {float(sv_hard['p_accused']):.2f}",
                ),
            ]
            for desc, tok in paired_checks:
                _require_token(sub_norm, doc_rel, desc, tok, failures)
            checked_metrics += len(paired_checks)

    if not isinstance(pooled_obj, list):
        failures.append(f"{pooled_rel}: expected JSON list")
    else:
        pooled_row = _find_paired_row(
            pooled_obj, "opencode-gemini-4-carbon-ext", "hard", n_expected=32
        )
        if pooled_row is None:
            failures.append(f"{pooled_rel}: missing pooled hard row with n=32")
        else:
            p_mean_ci = f"{float(pooled_row['mean']):+.3f} +/- {float(pooled_row['ci']):.3f}"
            p_raw = _pct_band(pooled_row["ratio"], pooled_row["ratio_lo"], pooled_row["ratio_hi"])
            p_la = _pct_band(
                pooled_row["post_expected_ratio"],
                pooled_row["post_expected_lo"],
                pooled_row["post_expected_hi"],
            )
            p_diff = f"{float(pooled_row['diff']):+.3f} +/- {float(pooled_row['diff_ci']):.3f}"
            for desc, tok in (
                ("pooled n=32 sample size", "n=32"),
                ("pooled n=32 mean +/- CI", p_mean_ci),
                ("pooled n=32 raw ratio + CI", p_raw),
                ("pooled n=32 luck-adjusted ratio + CI", p_la),
                ("pooled n=32 paired diff +/- CI", p_diff),
            ):
                _require_token(sub_norm, doc_rel, desc, tok, failures)
            checked_metrics += 5

    assert jt_txt is not None
    jt_fp, jt_git, jt_scores = _parse_judge_table_paired(jt_txt)
    if not jt_fp:
        failures.append(f"{jt_rel}: missing judge-world secret fingerprint")
    for tier in ("hard", "medium", "easy"):
        if not jt_scores.get((tier, "solver")):
            failures.append(f"{jt_rel}: missing paired solver row for {tier}")
        for zero_pol in ("do_nothing", "stop_early"):
            z_cell = jt_scores.get((tier, zero_pol), "")
            if not z_cell.startswith("+0.000"):
                failures.append(f"{jt_rel}: {tier} {zero_pol} expected '+0.000', got '{z_cell}'")
        if not jt_scores.get((tier, "guess_day1")):
            failures.append(f"{jt_rel}: missing paired guess_day1 row for {tier}")

    if jt_fp and _has_token(sub_norm, jt_fp):
        if jt_git:
            _require_token(sub_norm, doc_rel, "judge_table git SHA", jt_git, failures)
            checked_metrics += 1
        for tier in ("hard", "medium", "easy"):
            sv_cell = jt_scores.get((tier, "solver"), "")
            gd_cell = jt_scores.get((tier, "guess_day1"), "")
            if sv_cell:
                _require_token(sub_norm, doc_rel, f"judge_table {tier} solver", sv_cell, failures)
                checked_metrics += 1
            if gd_cell:
                _require_token(sub_norm, doc_rel, f"judge_table {tier} guess_day1", gd_cell, failures)
                checked_metrics += 1
        checked_metrics += 1
    else:
        hist_fp = "893b837616b9"
        hist_git = "f9fb7a4adc01"
        _require_any_token(
            sub_norm,
            doc_rel,
            "judge_table secret fingerprint",
            tuple(c for c in (jt_fp or "", hist_fp) if c),
            failures,
        )
        _require_token(sub_norm, doc_rel, "judge_table snapshot git SHA", hist_git, failures)
        hist_cells = (
            ("hard", "solver", "+0.553 +/- 0.093", 0.553),
            ("medium", "solver", "+0.634 +/- 0.086", 0.634),
            ("easy", "solver", "+0.785 +/- 0.026", 0.785),
            ("hard", "guess_day1", "-1.000 +/- 0.000", -1.000),
            ("medium", "guess_day1", "-0.950 +/- 0.098", -0.950),
            ("easy", "guess_day1", "-0.750 +/- 0.208", -0.750),
        )
        for tier, pol, cell_tok, mean_val in hist_cells:
            _require_token(sub_norm, doc_rel, f"judge_table {tier} {pol}", cell_tok, failures)
            sr_rel = f"results/solver_range/{pol}_{tier}_judge40.json"
            if (root / sr_rel).is_file():
                sr_obj = _load_json(root, sr_rel, failures, cache)
                if isinstance(sr_obj, dict) and "min" in sr_obj and "max" in sr_obj:
                    lo_b = float(sr_obj["min"]) - 1e-6
                    hi_b = float(sr_obj["max"]) + 1e-6
                    if not (lo_b <= mean_val <= hi_b):
                        failures.append(f"{doc_rel}: {tier} {pol} {mean_val} outside {sr_rel} [{lo_b:.3f}, {hi_b:.3f}]")
        checked_metrics += 8
    _require_token(sub_norm, doc_rel, "do_nothing/stop_early +0.000", "+0.000", failures)
    checked_metrics += 1

    if not isinstance(or_obj, dict) or not isinstance(or_obj.get("rows"), list):
        failures.append(f"{or_rel}: missing 'rows' list")
    else:
        or_hard = next(
            (
                r
                for r in or_obj["rows"]
                if isinstance(r, dict) and r.get("agent") == "solver" and r.get("tier") == "hard"
            ),
            None,
        )
        if or_hard is None or not isinstance(or_hard.get("k10"), dict):
            failures.append(f"{or_rel}: missing solver hard k10 entry")
        else:
            k10 = or_hard["k10"]
            for desc, tok in (
                ("oracle 10-task p5", f"{float(k10['p5']):+.2f}"),
                ("oracle 10-task p95", f"{float(k10['p95']):+.2f}"),
                ("oracle 10-task mean", f"{float(k10['mean']):+.3f}"),
                ("oracle 10-task sd", f"{float(k10['sd']):.3f}"),
                ("oracle simulated builds", f"{int(or_hard['builds'])} simulated builds"),
            ):
                _require_token(sub_norm, doc_rel, desc, tok, failures)
            checked_metrics += 5

    assert sl_txt is not None
    sl_deltas = _parse_skill_ladder_deltas(sl_txt)
    for tier in ("hard", "medium"):
        for rung_key, rung_desc in (
            ("solver-accuse_last", "accuse_last"),
            ("solver-accuse_p50", "accuse_p50"),
            ("solver-no_delay", "no_delay"),
        ):
            d_str = sl_deltas.get((tier, rung_key))
            if not d_str:
                failures.append(f"{sl_rel}: missing {tier} {rung_key} delta")
            else:
                _require_token(sub_norm, doc_rel, f"skill_ladder {tier} {rung_desc}", d_str, failures)
                checked_metrics += 1

    if not isinstance(fa_obj, dict) or not isinstance(fa_obj.get("summary"), dict):
        failures.append(f"{fa_rel}: missing 'summary' object")
    else:
        fa_sum = fa_obj["summary"]
        fa_oc = fa_sum.get("opencode")
        fa_sv = fa_sum.get("solver")
        fa_gap = fa_sum.get("gap")
        if not (isinstance(fa_oc, dict) and isinstance(fa_sv, dict) and isinstance(fa_gap, dict)):
            failures.append(f"{fa_rel}: summary missing opencode/solver/gap objects")
        else:
            oc_not_iso = len(fa_oc.get("not_isolated", []))
            oc_accused = int(fa_oc["accused"])
            sv_not_iso = len(fa_sv.get("not_isolated", []))
            sv_accused = int(fa_sv["accused"])
            fa_items: list[tuple[str, Sequence[str]]] = [
                ("OpenCode mean canaries", (f"{float(fa_oc['canaries']):.1f} canaries",)),
                ("solver mean canaries", (f"solver's {float(fa_sv['canaries']):.1f}", f"{float(fa_sv['canaries']):.1f}")),
                (
                    "first canary day OpenCode vs solver",
                    (f"day {float(fa_oc['first_canary_day']):.1f} vs {float(fa_sv['first_canary_day']):.1f}",),
                ),
                ("OpenCode interviews per episode", (f"{int(round(float(fa_oc['interviews'])))} low-value interviews",)),
                (
                    "OpenCode un-isolated accusations",
                    (f"{oc_not_iso} of {oc_accused}", f"{oc_not_iso}/{oc_accused}"),
                ),
                (
                    "solver un-isolated accusations",
                    (f"{sv_not_iso} of {sv_accused}", f"{sv_not_iso}/{sv_accused}"),
                ),
                (
                    "un-isolated accusation penalty V",
                    (f"{float(fa_gap['penalty']):.2f} V",),
                ),
                (
                    "waiting leak drain V",
                    (f"{float(fa_gap['leak']):+.2f} V", f"{float(fa_gap['leak']):.2f} V"),
                ),
                (
                    "saved canary cost V",
                    (f"{float(fa_gap['canary']):+.2f} V",),
                ),
                (
                    "mean accusation day OpenCode vs solver",
                    (f"day {float(fa_oc['accuse_day']):.1f} vs {float(fa_sv['accuse_day']):.1f}",),
                ),
            ]
            for desc, cands in fa_items:
                _require_any_token(sub_norm, doc_rel, desc, cands, failures)
            checked_metrics += len(fa_items)

    assert regret_txt is not None and fresh_txt is not None
    reg_m = re.search(r"mean\s+total\s+regret\s+([0-9.]+)", regret_txt)
    prem_m = re.search(r"\|\s*premature_accusation\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*\|", regret_txt)
    if reg_m is None or prem_m is None:
        failures.append(f"{regret_rel}: unable to parse mean total regret / premature_accusation row")
    else:
        _require_token(sub_norm, doc_rel, "mean regret per episode", f"{reg_m.group(1)} V", failures)
        _require_token(
            sub_norm,
            doc_rel,
            "premature_accusation value lost",
            f"{prem_m.group(2)} V",
            failures,
        )
        checked_metrics += 2

    fresh_norm = _normalize_numeric_text(fresh_txt)
    gt_m = re.search(
        r"\|\s*hard\s*\|\s*grok_tactics\s*\|[^|]+\|[^|]+\|\s*-?([0-9.]+\s*\+/-\s*[0-9.]+)\s*\|",
        fresh_norm,
    )
    if gt_m is None:
        failures.append(f"{fresh_rel}: missing hard grok_tactics row")
    else:
        _require_token(sub_norm, doc_rel, "grok_tactics hard gap", gt_m.group(1).strip(), failures)
        checked_metrics += 1

    if not isinstance(ex_obj, dict):
        failures.append(f"{ex_rel}: expected JSON object")
    else:
        if ex_obj.get("all_blocked") is not True:
            failures.append(f"{ex_rel}: all_blocked is not True")
        if ex_obj.get("replay_all_consistent") is not True:
            failures.append(f"{ex_rel}: replay_all_consistent is not True")
        if ex_obj.get("harbor_all_consistent") is not True:
            failures.append(f"{ex_rel}: harbor_all_consistent is not True")

        ex_rows = ex_obj.get("rows") if isinstance(ex_obj.get("rows"), list) else []
        hard_attacks = sum(1 for r in ex_rows if isinstance(r, dict) and r.get("tier") == "hard" and r.get("kind") == "attack")
        hard_swarm = sum(1 for r in ex_rows if isinstance(r, dict) and r.get("tier") == "hard" and r.get("kind") == "swarm")
        _require_token(sub_norm, doc_rel, "anti-cheat attack probe count", f"{hard_attacks} attack probes", failures)
        _require_token(sub_norm, doc_rel, "anti-cheat swarm probe count", f"{hard_swarm} swarm-found probe", failures)

        cut90 = next(
            (r for r in ex_rows if isinstance(r, dict) and r.get("tier") == "hard" and r.get("probe") == "solver_cut_90_guess"),
            None,
        )
        bat_sv = next(
            (r for r in ex_rows if isinstance(r, dict) and r.get("tier") == "hard" and r.get("probe") == "solver"),
            None,
        )
        if cut90 is None or bat_sv is None:
            failures.append(f"{ex_rel}: missing hard solver_cut_90_guess or solver row")
        else:
            _require_token(
                sub_norm,
                doc_rel,
                "effort ladder hard 90% cut",
                f"{float(cut90['mean']):+.3f} +/- {float(cut90['ci95']):.3f}",
                failures,
            )
            _require_token(
                sub_norm,
                doc_rel,
                "battery full solver hard",
                f"{float(bat_sv['mean']):+.3f} +/- {float(bat_sv['ci95']):.3f}",
                failures,
            )

        rc_map = ex_obj.get("replay_counts") if isinstance(ex_obj.get("replay_counts"), dict) else {}
        rep_done = int(rc_map.get("replayed", -1))
        rep_total = int(rc_map.get("n", -1))
        rep_steps = int(rc_map.get("steps", -1))
        rep_mismatches = int(rc_map.get("step_mismatches", -1))
        if rep_mismatches != 0:
            failures.append(f"{ex_rel}: step_mismatches expected 0, got {rep_mismatches}")

        replay_list = ex_obj.get("replay") if isinstance(ex_obj.get("replay"), list) else []
        gpt55_rep = [
            r
            for r in replay_list
            if isinstance(r, dict) and "v1.4/opencode-gpt-5.5/" in str(r.get("file", ""))
        ]
        gpt55_done = sum(int(r.get("replayed", 0)) for r in gpt55_rep)
        gpt55_total = sum(int(r.get("n", 0)) for r in gpt55_rep)
        gpt55_steps = sum(int(r.get("steps", 0)) for r in gpt55_rep)

        count_cands: list[str] = [
            f"{_comma_int(rep_done)} of {_comma_int(rep_total)}",
            f"{rep_done} of {rep_total}",
        ]
        step_cands: list[str] = [_comma_int(rep_steps), str(rep_steps)]
        if gpt55_total > 0 and "all replay-verified" in sub_norm.lower():
            pre_done = rep_done - gpt55_done
            pre_total = rep_total - gpt55_total
            pre_steps = rep_steps - gpt55_steps
            count_cands.extend([
                f"{_comma_int(pre_done)} of {_comma_int(pre_total)}",
                f"{pre_done} of {pre_total}",
            ])
            step_cands.extend([_comma_int(pre_steps), str(pre_steps)])

        _require_any_token(
            sub_norm,
            doc_rel,
            "replayable committed episode count",
            count_cands,
            failures,
        )
        _require_any_token(
            sub_norm,
            doc_rel,
            "replayed tool results step count",
            step_cands,
            failures,
        )

        harbor_items = ex_obj.get("harbor") if isinstance(ex_obj.get("harbor"), list) else []
        n_trials = sum(1 for h in harbor_items if isinstance(h, dict) and h.get("kind") == "trial")
        n_jobs = sum(1 for h in harbor_items if isinstance(h, dict) and h.get("kind") == "job")
        _require_any_token(
            sub_norm,
            doc_rel,
            "Harbor consistent trials",
            (f"{n_trials} of {n_trials}", f"{n_trials}/{n_trials}"),
            failures,
        )
        _require_any_token(
            sub_norm,
            doc_rel,
            "Harbor consistent job summaries",
            (f"{n_jobs} of {n_jobs}", f"{n_jobs}/{n_jobs}"),
            failures,
        )
        checked_metrics += 8

    assert corpus_txt is not None and dry_txt is not None
    c_rows_m = re.search(r'"rows"\s*:\s*(\d+)', corpus_txt)
    c_runs_m = re.search(r'"runs"\s*:\s*(\d+)', corpus_txt)
    if c_rows_m is None or c_runs_m is None:
        failures.append(f"{corpus_rel}: missing rows/runs JSON summary")
    else:
        _require_token(sub_norm, doc_rel, "cheat corpus rejected calls", f"{c_rows_m.group(1)} rejected calls", failures)
        _require_any_token(
            sub_norm,
            doc_rel,
            "cheat corpus widened runs",
            (f"{_comma_int(int(c_runs_m.group(1)))} runs", f"{c_runs_m.group(1)} runs"),
            failures,
        )
        checked_metrics += 2

    dry_norm = _normalize_numeric_text(dry_txt)
    if "+0.467" not in dry_norm or "+0.398" not in dry_norm or "85% [11%, 355%]" not in dry_norm:
        failures.append(f"{dry_rel}: missing expected dry rehearsal summary (+0.467, +0.398, 85% [11%, 355%])")
    else:
        for desc, tok in (
            ("dry rehearsal oracle mean", "+0.467"),
            ("dry rehearsal OpenCode mean", "+0.398"),
            ("dry rehearsal ratio + CI", "85% of the oracle [11%, 355%]"),
        ):
            _require_token(sub_norm, doc_rel, desc, tok, failures)
        checked_metrics += 3

    if not isinstance(swarm_obj, dict):
        failures.append(f"{swarm_rel}: expected JSON object")
    else:
        sw_counts = swarm_obj.get("counts") if isinstance(swarm_obj.get("counts"), dict) else {}
        sw_waves = swarm_obj.get("waves") if isinstance(swarm_obj.get("waves"), list) else []
        sw_pc = swarm_obj.get("positive_control") if isinstance(swarm_obj.get("positive_control"), dict) else {}

        wb_fin = sum(int(w.get("finished", 0)) for w in sw_waves if isinstance(w, dict) and w.get("mode") == "whitebox")
        bb_fin = sum(int(w.get("finished", 0)) for w in sw_waves if isinstance(w, dict) and w.get("mode") == "blackbox")
        mcp_re = sum(int(w.get("mcp_reruns", 0)) for w in sw_waves if isinstance(w, dict))
        sw_att = int(sw_counts.get("attempts", -1))
        sw_calls = int(sw_counts.get("tool_calls", -1))
        sw_exp = int(sw_counts.get("exploits", -1))
        sw_viol = int(sw_counts.get("invariant_violations", -1))
        pc_found = int(sw_pc.get("attackers_found", -1))
        pc_att = int(sw_pc.get("attempts", -1))

        if wb_fin + bb_fin + mcp_re != sw_att:
            failures.append(
                f"{swarm_rel}: wave split {wb_fin}+{bb_fin}+{mcp_re} != counts.attempts {sw_att}"
            )
        if sw_exp != 0 or sw_viol != 0:
            failures.append(f"{swarm_rel}: expected 0 exploits and 0 violations, got {sw_exp}, {sw_viol}")

        for desc, cands in (
            ("swarm total attempts", (f"{sw_att} Gemini attackers",)),
            ("swarm whitebox finished", (f"{wb_fin} whitebox",)),
            ("swarm blackbox finished", (f"{bb_fin} blackbox",)),
            ("swarm MCP reruns", (f"{mcp_re} re-runs", f"{mcp_re} MCP re-runs")),
            ("swarm tool calls", (f"{_comma_int(sw_calls)} tool calls", f"{sw_calls} tool calls")),
            ("swarm 0 verified exploits", ("0 verified exploits",)),
            ("swarm 0 invariant violations", ("0 invariant violations",)),
            ("swarm positive control", (f"{pc_found} of {pc_att}", f"{pc_found}/{pc_att}")),
        ):
            _require_any_token(sub_norm, doc_rel, desc, cands, failures)
        checked_metrics += 8

    assert ws4_txt is not None
    ws4_rows = _parse_ws4_all_rows(ws4_txt)
    ws4_hist_rows = _parse_ws4_all_rows(ws4_hist_txt) if ws4_hist_txt is not None else {}
    uses_hist_ws4 = "ws4_table_v3s0_n180.md" in sub_raw and bool(ws4_hist_rows)

    for req_id in ("base", "v1", "v2", "v3-4k-s0", "v3-4k-s1", "v3-8k-s1", "v3-8k-s2"):
        if req_id not in ws4_rows:
            failures.append(f"{ws4_rel}: missing tier='all' row for '{req_id}'")

    if uses_hist_ws4:
        for hist_id, label in (
            ("base", "WS4 base (ws4_table_v3s0_n180)"),
            ("v1", "WS4 v1 SFT"),
            ("v2", "WS4 v2 SFT"),
            ("v3_4k_s0", "WS4 v3-4k-s0 GRPO"),
        ):
            hrow = ws4_hist_rows.get(hist_id)
            if hrow is None:
                failures.append(f"{ws4_hist_rel}: missing tier='all' row for '{hist_id}'")
                continue
            _require_token(sub_norm, doc_rel, f"{label} score +/- CI", hrow.get("score +/- 95% ci", ""), failures)
            _require_token(sub_norm, doc_rel, f"{label} episode count", hrow.get("n", ""), failures)
            checked_metrics += 2
        s1_row = ws4_rows.get("v3-8k-s1")
        if s1_row is not None:
            _require_token(sub_norm, doc_rel, "WS4 v3-8k-s1 GRPO score +/- CI", s1_row.get("score +/- 95% ci", ""), failures)
            _require_token(sub_norm, doc_rel, "WS4 v3-8k-s1 GRPO episode count", s1_row.get("n", ""), failures)
            checked_metrics += 2
    else:
        for model_id, label in (
            ("base", "WS4 base"),
            ("v1", "WS4 v1 SFT"),
            ("v2", "WS4 v2 SFT"),
            ("v3-4k-s0", "WS4 v3-4k-s0 GRPO"),
            ("v3-4k-s1", "WS4 v3-4k-s1 GRPO partial"),
            ("v3-8k-s1", "WS4 v3-8k-s1 GRPO"),
            ("v3-8k-s2", "WS4 v3-8k-s2 GRPO"),
        ):
            wrow = ws4_rows.get(model_id)
            if wrow is None:
                continue
            score_ci = wrow.get("score +/- 95% ci", "")
            n_str = wrow.get("n", "")
            _require_token(sub_norm, doc_rel, f"{label} score +/- CI", score_ci, failures)
            _require_token(sub_norm, doc_rel, f"{label} episode count", n_str, failures)
            checked_metrics += 2

    v3_row = ws4_rows.get("v3-4k-s0")
    if v3_row is not None:
        delta_v2_col = next((v for k, v in v3_row.items() if "vs v2" in k), "")
        m_dv2 = re.match(r"([+-]?[0-9.]+\s*\+/-\s*[0-9.]+)", delta_v2_col)
        if m_dv2:
            _require_token(sub_norm, doc_rel, "WS4 v3 vs v2 two-sample delta", m_dv2.group(1), failures)
            checked_metrics += 1

    assert gap_txt is not None
    gap_norm = _normalize_numeric_text(gap_txt)
    for sha_tok, desc in (
        ("671ed96", "post-hoc seed lock commit SHA"),
        ("28 s", "post-hoc seed lock 28 s elapsed"),
        ("8fd4dec", "primary episodes commit SHA"),
    ):
        _require_token(gap_norm, gap_rel, desc, sha_tok, failures)
        _require_token(sub_norm, doc_rel, desc, sha_tok, failures)
        checked_metrics += 1
    if "not a pre-registration" not in sub_norm.lower():
        failures.append(f"{doc_rel}: missing explicit 'not a pre-registration' seed-lock disclosure")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} numeric provenance mismatch(es) in {doc_rel}",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {checked_metrics} committed metrics in {doc_rel} against paired_table_gemini.json, "
        f"rehearsal/TABLE.md, behaviour_compare_v1.4.md, redteam_1000/summary.md, pooled n=32, "
        f"judge_table/solver_range, oracle_range, skill_ladder, failure_analysis, exploits.json, swarm.json, and WS4 tables",
    )


def check_gemini_provenance(
    root: Path = ROOT,
    *,
    _json_cache: dict[str, Any] | None = None,
) -> CheckResult:
    name = CHECK_GEMINI_PROV
    failures: list[str] = []
    cache = _json_cache if _json_cache is not None else {}

    doc_rel = "docs/gemini/SUBMISSION.md"
    gsub_raw = _read_text(root, doc_rel, failures)
    if gsub_raw is None:
        return CheckResult(name, "FAIL", f"missing or unreadable {doc_rel}", failures)
    gsub_norm = _normalize_numeric_text(gsub_raw)

    ladder_rel = "results/gemini/ladder.json"
    abl_rel = "results/gemini/ablations.json"
    swarm_rel = "results/gemini/swarm.json"
    atlas_md_rel = "results/gemini/atlas_blind.md"
    atlas_json_rel = "results/gemini/atlas_blind.json"
    paired_rel = "data/runs/committed/v1.4/paired_table_gemini.json"

    ladder_obj = _load_json(root, ladder_rel, failures, cache)
    abl_obj = _load_json(root, abl_rel, failures, cache)
    swarm_obj = _load_json(root, swarm_rel, failures, cache)
    atlas_md = _read_text(root, atlas_md_rel, failures)
    paired_obj = _load_json(root, paired_rel, failures, cache)
    atlas_obj = (
        _load_json(root, atlas_json_rel, failures, cache)
        if (root / atlas_json_rel).is_file()
        else None
    )

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} missing/invalid Gemini provenance artifact(s)", failures)

    short_m = re.search(r"^\*\*Short version[^*]*\*\*\s*(.+)$", gsub_raw, re.MULTILINE)
    if short_m is None:
        failures.append(f"{doc_rel}: missing '**Short version (<= 600 chars).**' lead paragraph")
    else:
        short_len = len(short_m.group(1).strip())
        if short_len == 0 or short_len > MAX_GEMINI_SHORT_CHARS:
            failures.append(
                f"{doc_rel}: Short version length {short_len} outside [1, {MAX_GEMINI_SHORT_CHARS}] chars"
            )

    for sec_num in range(1, 5):
        if re.search(rf"^\s*{HASH_CHAR}{{2,3}}\s+{sec_num}\.\s+\S", gsub_raw, re.MULTILINE) is None:
            failures.append(f"{doc_rel}: missing section '{HASH_CHAR}{HASH_CHAR} {sec_num}.'")

    _verify_internal_links_and_paths(root, doc_rel, gsub_raw, failures)

    checked = 0

    if not isinstance(ladder_obj, dict) or not isinstance(ladder_obj.get("rows"), list):
        failures.append(f"{ladder_rel}: missing 'rows' list")
    else:
        l_rows = [r for r in ladder_obj["rows"] if isinstance(r, dict)]
        l_eps = int(ladder_obj.get("episodes", -1))
        l_cells = len(l_rows)
        if sum(int(r.get("n", 0)) for r in l_rows) != l_eps:
            failures.append(f"{ladder_rel}: sum(rows.n) disagrees with episodes={l_eps}")
        ex_parity = sum(
            1
            for r in l_rows
            if not (float(r.get("ratio_lo", 0.0)) <= 1.0 <= float(r.get("ratio_hi", 0.0)))
        )

        _require_token(gsub_norm, doc_rel, "ladder paired episodes", f"{l_eps} paired episodes", failures)
        _require_token(
            gsub_norm,
            doc_rel,
            "ladder cells excluding solver parity",
            f"{ex_parity} of {l_cells} ladder cells",
            failures,
        )
        checked += 2

        def _ladder_cell(model: str, level: str, tier: str) -> dict[str, Any] | None:
            return next(
                (r for r in l_rows if r.get("model") == model and r.get("level") == level and r.get("tier") == tier),
                None,
            )

        c_high = _ladder_cell("gemini-4-carbon", "high", "hard")
        f_high = _ladder_cell("gemini-3.5-flash", "high", "hard")
        f_med = _ladder_cell("gemini-3.5-flash", "medium", "hard")
        f_min = _ladder_cell("gemini-3.5-flash", "minimal", "hard")

        for cell_label, cell_obj in (
            ("gemini-4-carbon high hard", c_high),
            ("gemini-3.5-flash high hard", f_high),
            ("gemini-3.5-flash medium hard", f_med),
            ("gemini-3.5-flash minimal hard", f_min),
        ):
            if cell_obj is None:
                failures.append(f"{ladder_rel}: missing ladder cell '{cell_label}'")
            else:
                band = _pct_band_plain_ci(
                    float(cell_obj["ratio"]) * 100.0,
                    float(cell_obj["ratio_lo"]) * 100.0,
                    float(cell_obj["ratio_hi"]) * 100.0,
                )
                _require_token(gsub_norm, doc_rel, f"ladder {cell_label} ratio + CI", band, failures)
                checked += 1

        lite_rows = [r for r in l_rows if r.get("model") == "gemini-3.1-flash-lite"]
        lite_below = sum(1 for r in lite_rows if float(r.get("mean", 0.0)) < 0.0)
        _require_token(
            gsub_norm,
            doc_rel,
            "gemini-3.1-flash-lite below do-nothing cells",
            f"{lite_below}/{len(lite_rows)} cells",
            failures,
        )
        checked += 1

    if not isinstance(abl_obj, dict):
        failures.append(f"{abl_rel}: expected JSON object")
    else:
        ts = abl_obj.get("thought_signatures") if isinstance(abl_obj.get("thought_signatures"), dict) else {}
        ts_off = ts.get("off") if isinstance(ts.get("off"), dict) else {}
        ts_on = ts.get("on") if isinstance(ts.get("on"), dict) else {}
        ec = abl_obj.get("explicit_cache") if isinstance(abl_obj.get("explicit_cache"), dict) else {}
        ec_ag = ec.get("atlas_plus_gallery") if isinstance(ec.get("atlas_plus_gallery"), dict) else {}
        ec_prog = ec.get("programme") if isinstance(ec.get("programme"), dict) else {}

        off_rej = len(ts_off.get("second_call_rejected_seeds", []))
        off_att = int(ts_off.get("episodes_attempted", -1))
        on_val = int(ts_on.get("valid_episodes", -1))
        on_err = int(ts_on.get("api_errors", -1))
        on_calls = int(ts_on.get("api_calls", -1))
        rej_ci = ts_off.get("rejection_rate_ci95", [0.0, 0.0])

        abl_tokens: list[tuple[str, Sequence[str]]] = [
            ("thought-signature off rejection count", (f"{off_rej}/{off_att}",)),
            ("thought-signature on valid count", (f"{on_val}/{off_att} played",)),
            ("thought-signature on API error rate", (f"{on_err}/{on_calls} API errors",)),
            (
                "thought-signature Wilson 95% CI",
                (f"[{float(rej_ci[0]) * 100.0:.1f}, {float(rej_ci[1]) * 100.0:.0f}]",),
            ),
            ("Atlas explicit cache uncached USD", (f"${float(ec_ag.get('usd_if_uncached', 0.0)):.2f}",)),
            ("Atlas explicit cache paid USD", (f"${float(ec_ag.get('usd_paid', 0.0)):.2f}",)),
            ("Atlas explicit cache pct saved", (f"{float(ec_ag.get('pct_saved', 0.0)):.1f}% saved",)),
            ("Atlas explicit cache call count", (f"{int(ec_ag.get('calls', 0))} calls",)),
            ("programme explicit cache pct saved", (f"saved {float(ec_prog.get('pct_saved', 0.0)):.1f}%",)),
            ("programme explicit cache USD saved", (f"${float(ec_prog.get('usd_saved', 0.0)):.2f}",)),
            ("programme explicit cache USD uncached", (f"${float(ec_prog.get('usd_if_uncached', 0.0)):.2f}",)),
            (
                "programme ledgered calls",
                (f"{_comma_int(int(ec_prog.get('calls', 0)))} ledgered calls", f"{int(ec_prog.get('calls', 0))} ledgered calls"),
            ),
        ]
        for desc, cands in abl_tokens:
            _require_any_token(gsub_norm, doc_rel, desc, cands, failures)
        checked += len(abl_tokens)

    if isinstance(swarm_obj, dict):
        sw_counts = swarm_obj.get("counts") if isinstance(swarm_obj.get("counts"), dict) else {}
        sw_waves = swarm_obj.get("waves") if isinstance(swarm_obj.get("waves"), list) else []
        sw_pc = swarm_obj.get("positive_control") if isinstance(swarm_obj.get("positive_control"), dict) else {}
        wb_fin = sum(int(w.get("finished", 0)) for w in sw_waves if isinstance(w, dict) and w.get("mode") == "whitebox")
        bb_fin = sum(int(w.get("finished", 0)) for w in sw_waves if isinstance(w, dict) and w.get("mode") == "blackbox")
        mcp_re = sum(int(w.get("mcp_reruns", 0)) for w in sw_waves if isinstance(w, dict))
        dns_lost = sum(int(w.get("lost_infra_invalid", 0)) for w in sw_waves if isinstance(w, dict))

        for desc, tok in (
            ("Gemini swarm 100 attacks", f"{int(sw_counts.get('attempts', -1))} ledger-verified attacks"),
            ("Gemini swarm whitebox count", f"{wb_fin} whitebox"),
            ("Gemini swarm blackbox count", f"{bb_fin} blackbox"),
            ("Gemini swarm MCP reruns", f"{mcp_re} MCP re-runs"),
            ("Gemini swarm DNS lost count", f"{dns_lost} lost to DNS"),
            ("Gemini swarm 0 verified exploits", "0 verified exploits"),
            ("Gemini swarm 0 invariant violations", "0 invariant violations"),
            (
                "Gemini swarm positive control",
                f"{int(sw_pc.get('attackers_found', -1))}/{int(sw_pc.get('attempts', -1))}",
            ),
        ):
            _require_token(gsub_norm, doc_rel, desc, tok, failures)
        checked += 8

    assert atlas_md is not None
    atlas_norm = _normalize_numeric_text(atlas_md)
    rec_m = re.search(r"recovered\s+(\d+\s+of\s+\d+)\s+code-defined\s+failure\s+modes", atlas_norm)
    new_m = re.search(r"named\s+(\d+)\s+mode", atlas_norm)
    reg_cov_m = re.search(r"cover\s+(\d+%)\s+of\s+all\s+solver\s+regret", atlas_norm)
    ep_m = re.search(r"(\d+)\s+episodes,\s*([0-9,]+)\s+tokens", atlas_norm)
    if rec_m is None or new_m is None or reg_cov_m is None or ep_m is None:
        failures.append(f"{atlas_md_rel}: missing blind-atlas headline recovery metrics")
    else:
        _require_token(
            gsub_norm,
            doc_rel,
            "blind atlas recovered modes (Short version)",
            f"recovers {rec_m.group(1)} failure modes",
            failures,
        )
        _require_token(
            gsub_norm,
            doc_rel,
            "blind atlas recovered modes (Results table)",
            f"Recovers {rec_m.group(1)} code-defined failure modes",
            failures,
        )
        _require_token(gsub_norm, doc_rel, "blind atlas new modes", f"names {new_m.group(1)} new", failures)
        _require_token(gsub_norm, doc_rel, "blind atlas regret coverage", f"{reg_cov_m.group(1)} of regret", failures)
        _require_token(gsub_norm, doc_rel, "blind atlas trajectory count", f"{ep_m.group(1)} trajectories", failures)
        checked += 5

    if isinstance(atlas_obj, dict) and isinstance(atlas_obj.get("recovery"), dict):
        cited_steps = int(atlas_obj["recovery"].get("cited_steps", -1))
        _require_token(gsub_norm, doc_rel, "blind atlas cited steps", f"{cited_steps} cited steps", failures)
        checked += 1

    if isinstance(paired_obj, list):
        oc_hard = _find_paired_row(paired_obj, "v1.4/opencode-gemini-4-carbon", "hard")
        ip_hard = _find_paired_row(paired_obj, "v1.4/inproc-gemini-4-carbon", "hard")
        if oc_hard is not None and ip_hard is not None:
            _require_token(
                gsub_norm,
                doc_rel,
                "Honesty notes AfterQuery OpenCode raw ratio + CI",
                _pct_band(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"]),
                failures,
            )
            _require_token(
                gsub_norm,
                doc_rel,
                "Honesty notes AfterQuery OpenCode luck-adj ratio + CI",
                _pct_band(
                    oc_hard["post_expected_ratio"],
                    oc_hard["post_expected_lo"],
                    oc_hard["post_expected_hi"],
                ),
                failures,
            )
            _require_token(
                gsub_norm,
                doc_rel,
                "Honesty notes AfterQuery in-process raw ratio + CI",
                _pct_band(ip_hard["ratio"], ip_hard["ratio_lo"], ip_hard["ratio_hi"]),
                failures,
            )
            checked += 3

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} provenance mismatch(es) in {doc_rel}",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {checked} metrics + structure/links in {doc_rel} against ladder.json (587 eps, 42 cells), "
        f"ablations.json (10/10, 0/628, 62.9%, 75.9%, 29,150), swarm.json, and atlas_blind.md",
    )


def check_post_edd4fe6d_sync(root: Path = ROOT) -> CheckResult:
    name = CHECK_POST_EDD4_SYNC
    failures: list[str] = []
    doc_rel = "docs/SUBMISSION.md"
    sub_txt = _read_text(root, doc_rel, failures)
    if sub_txt is None:
        return CheckResult(name, "FAIL", f"missing or unreadable {doc_rel}", failures)

    if EM_DASH in sub_txt:
        failures.append(f"{doc_rel}: contains forbidden em dash character")
    if EN_DASH in sub_txt:
        failures.append(f"{doc_rel}: contains forbidden en dash character")

    sub_norm = _normalize_numeric_text(sub_txt)

    final_parsed = _extract_final_results_block(sub_txt)
    form_sec_m = re.search(rf"^\s*{HASH_CHAR}{{2,3}}\s+Form\s+fields\b", sub_txt, re.IGNORECASE | re.MULTILINE)
    sec1_m = re.search(rf"^\s*{HASH_CHAR}{{2,3}}\s+1\.\s+\S", sub_txt, re.MULTILINE)
    if final_parsed is None:
        failures.append(f"{doc_rel}: missing top '{HASH_CHAR}{HASH_CHAR} Final results' superseding section")
    else:
        final_heading_tail, final_body, final_pos = final_parsed
        if form_sec_m is not None and final_pos > form_sec_m.start():
            failures.append(f"{doc_rel}: Final results section must precede Form fields")
        if sec1_m is not None and final_pos > sec1_m.start():
            failures.append(f"{doc_rel}: Final results section must precede Section 1")
        if "supersedes older lines and todos below" not in final_heading_tail.lower():
            failures.append(
                f"{doc_rel}: Final results heading missing explicit superseding note ('supersedes older lines and TODOs below')"
            )

        final_norm = _normalize_numeric_text(final_body)
        for desc, tok in (
            ("code-freeze tag afterquery-final", "afterquery-final"),
            ("code-freeze commit SHA 1bc3e281", "1bc3e281"),
            ("code freeze note", "code freeze"),
            ("submit tag afterquery-submit", "afterquery-submit"),
            ("live Harbor rehearsal table path", "results/harbor/rehearsal/TABLE.md"),
            ("Harbor rehearsal oracle +0.506", "oracle +0.506"),
            ("Harbor rehearsal run 1 mean +0.472", "+0.472"),
            ("Harbor rehearsal run 2 mean +0.585", "+0.585"),
            ("Harbor rehearsal run 3 mean +0.626", "+0.626"),
            ("Harbor rehearsal run 3 9 valid trials", "9 valid trials"),
            ("Harbor rehearsal run 1 ratio 93%", "93%"),
            ("Harbor rehearsal run 2 ratio 116%", "116%"),
            ("Harbor rehearsal run 3 ratio 131%", "131%"),
            ("Harbor rehearsal zero baselines 10 of 10", "10 of 10"),
            ("Harbor rehearsal gap non-reproduction verdict", "did not reproduce in the judge path"),
            ("gpt-5.5 pre-registration SHA cf394894", "cf394894"),
            ("second frontier family gpt-5.5", "gpt-5.5"),
            ("v1.4 hard seeds 0-29", "seeds 0-29"),
            ("gpt-5.5 replay-verified note", "all replay-verified"),
            ("gpt-5.5 paired ratio + CI 101% [79%, 140%]", "101% [79%, 140%]"),
            ("gpt-5.5 no-gap verdict", "No gap for gpt-5.5"),
            ("gemini-4-argon 103% note", "gemini-4-argon 103%"),
            ("gemini-4-hydrogen 115% note", "gemini-4-hydrogen 115%"),
            ("MCP-only gemini-4-carbon 65% [24%, 98%]", "65% [24%, 98%]"),
            ("behaviour comparison path", "results/behaviour_compare_v1.4.md"),
            ("gemini-4-carbon 53% interviews share", "53%"),
            ("gemini-4-carbon 8.5 canaries", "8.5 canaries"),
            ("gpt-5.5 17.2 canaries", "gpt-5.5's 17.2"),
            ("judge-protocol hunt 12 of 12 held", "12 of 12 held"),
            ("make hunt 0.000 non-solver", "0.000"),
            ("1,034-attack Gemini red-team sweep", "1,034-attack"),
            ("0 exploits on tag", "0 exploits"),
            ("tiebreak bar not met verdict", "is not met"),
        ):
            _require_token(final_norm, f"{doc_rel} (Final results)", desc, tok, failures)

    form_block = _extract_form_block(sub_txt)
    if form_block is not None:
        form_norm = _normalize_numeric_text(form_block)
        for desc, tok in (
            ("Form Repo afterquery-submit link", "afterquery-submit"),
            ("Form MCP-only 65% ratio", "65%"),
            ("Form MCP-only CI 24-98%", "CI 24-98%"),
            ("Form Harbor 93-131% range", "93-131%"),
            ("Form gpt-5.5 parity note", "gpt-5.5 matches the solver"),
            ("Form 1,000+ attacks note", "1,000+ attacks found no exploit"),
        ):
            _require_token(form_norm, f"{doc_rel} (Form)", desc, tok, failures)

    for desc, tok in (
        ("Section 3 Harbor rehearsal link", "results/harbor/rehearsal/TABLE.md"),
        ("Section 5 integrity.md link", "reports/integrity.md"),
        ("Section 5 anticheat-verify 0 differences", "0 differences"),
        ("Section 7 no held-out gain over base", "no held-out gain over the base model"),
    ):
        _require_token(sub_norm, doc_rel, desc, tok, failures)

    diff_path = root / "docs" / "DIFFICULTY.md"
    if diff_path.is_file():
        diff_norm = _normalize_numeric_text(diff_path.read_text(encoding="utf-8", errors="replace"))
        for desc, tok in (
            ("DIFFICULTY.md W1 fix header", "W1 is fixed in the instruction"),
            ("DIFFICULTY.md data.detail", "data.detail"),
            ("DIFFICULTY.md 28 of 3,841 calls", "28 of 3,841"),
        ):
            _require_token(diff_norm, "docs/DIFFICULTY.md", desc, tok, failures)

    steps_rel = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt"
    steps_path = root / steps_rel
    if steps_path.is_file():
        steps_txt = steps_path.read_text(encoding="utf-8", errors="replace")
        for step_m in re.finditer(r"^([A-Za-z0-9_]+)\s+exit=(\d+)\s+seconds=(\d+)\s*$", steps_txt, re.MULTILINE):
            step_name, exit_code = step_m.group(1), int(step_m.group(2))
            if exit_code != 0:
                failures.append(f"{steps_rel}: step '{step_name}' recorded non-zero exit={exit_code}")

    demo_path = root / "docs" / "DEMO.md"
    if demo_path.is_file():
        demo_txt = demo_path.read_text(encoding="utf-8", errors="replace")
        if "bar not met" not in demo_txt.lower():
            failures.append("docs/DEMO.md: missing synced WS4 'bar not met' tiebreak verdict")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} post-edd4fe6d refresh/sync regression(s) in {doc_rel}",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        "verified Sun 15 Nov 09:00 Final results block (afterquery-final 1bc3e281, afterquery-submit, "
        "Harbor rehearsal 93%/116%/131%, gpt-5.5 101% [79%, 140%], behaviour_compare 8.5 vs 17.2, "
        "1,034-attack 0 exploits, tiebreak bar not met), Form fields, and cross-docs with 0 em/en dashes",
    )


check_post_edd4fe6d_advisories = check_post_edd4fe6d_sync


def verify_repo(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    json_cache: dict[str, Any] = {}
    return [
        check_afterquery_structure(resolved),
        check_afterquery_provenance(resolved, _json_cache=json_cache),
        check_gemini_provenance(resolved, _json_cache=json_cache),
        check_post_edd4fe6d_sync(resolved),
    ]


audit_repo = verify_repo


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
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


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless read-only structure and numeric provenance verifier for docs/SUBMISSION.md and docs/gemini/SUBMISSION.md."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_repo(root=args.root.resolve())
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
