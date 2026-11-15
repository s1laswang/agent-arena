from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
UNICODE_MINUS = chr(0x2212)
PLUS_MINUS = chr(0x00B1)
DAGGER = chr(0x2020)

CHECK_COMPANION = "JSON-to-Markdown Companion Parity"
CHECK_GIT = "Recorded Git SHA & Tag Provenance"
CHECK_WS4 = "WS4 Tiebreak Artifact Consistency"
CHECK_INDEX = "Provenance Index Self-Check"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_COMPANION,
    CHECK_GIT,
    CHECK_WS4,
    CHECK_INDEX,
)

KEY_CITED_COMMITS: tuple[str, ...] = (
    "8fd4dec",
    "671ed96",
    "09e7363",
    "2b301cea",
    "f9fb7a4a",
    "92708834",
    "dcd8c372",
    "1bc3e281",
    "cf394894",
    "58716742",
)

AUDIT_CLOSURE_COMMITS: tuple[str, ...] = (
    "bd535a45",
    "edd4fe6d",
    "8522baea",
    "ca90d0b2",
    "92708834",
    "1bc3e281",
    "58716742",
)

TAG_AFTERQUERY_FINAL = "afterquery-final"
TAG_AFTERQUERY_PREFIX = "1bc3e281"

FRESH_CLONE_README_REL = "results/fresh_clone/README.md"
FRESH_CLONE_AF_LOG_REL = "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt"
FRESH_CLONE_SPECS: tuple[tuple[str, str, tuple[tuple[str, int], ...], str], ...] = (
    (
        "results/fresh_clone/macos_justSilas_09e7363.steps.txt",
        "09e7363",
        (("clone", 8), ("setup", 2), ("reproduce", 52), ("accept", 142), ("test", 905)),
        "967 passed",
    ),
    (
        "results/fresh_clone/linux_x86_64_justSilas_2b301cea.steps.txt",
        "2b301cea",
        (("clone", 5), ("reproduce_fast", 83), ("reproduce", 159), ("audit", 202), ("test", 263)),
        "115 passed",
    ),
    (
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt",
        "1bc3e281",
        (("clone", 3), ("reproduce_table", 27), ("reproduce", 118), ("audit", 4), ("test_core", 175)),
        "100 passed",
    ),
)
FRESH_CLONE_STEP_RX = re.compile(r"^([a-z0-9_]+)\s+exit=(-?\d+)\s+seconds=(\d+)$")

SOLVER_RANGE_STEMS: tuple[str, ...] = (
    "solver_easy_judge40",
    "solver_medium_judge40",
    "solver_hard_judge40",
    "guess_day1_easy_judge40",
    "guess_day1_medium_judge40",
    "guess_day1_hard_judge40",
)

REQUIRED_ORACLE_KEYS: tuple[tuple[str, str, int], ...] = (
    ("solver", "hard", 2),
    ("solver", "hard", 3),
    ("solver", "hard", 10),
    ("solver", "hard", 20),
    ("solver", "medium", 10),
)

PROVENANCE_INDEX_REL = "docs/NUMBER-PROVENANCE-INDEX.md"

KNOWN_REPO_ROOT_ENTRIES: frozenset[str] = frozenset(
    {
        "README.md",
        "JUDGE_QUICKSTART.md",
        "Makefile",
        "HANDOFF.md",
        "pyproject.toml",
    }
)

KNOWN_REPO_PREFIXES: tuple[str, ...] = (
    "canary/",
    "configs/",
    "data/",
    "docs/",
    "fr8/",
    "game/",
    "harbor/",
    "pitch/",
    "results/",
    "scripts/",
    "tests/",
)

HEX_SHA_RX = re.compile(r"^[0-9a-f]{7,40}$")
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")
FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"(`+)([^`\n]+?)\1")
MD_LINK_RX = re.compile(
    r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
MEAN_CI_RX = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*(?:\+/-|" + re.escape(PLUS_MINUS) + r")\s*([+-]?\d+(?:\.\d+)?)"
)
PCT_CI_RX = re.compile(
    r"([+-]?\d+(?:\.\d+)?)%\s*\[\s*([+-]?\d+(?:\.\d+)?)%\s*,\s*([+-]?\d+(?:\.\d+)?)%\s*\]"
)
RANGE_BRACKET_RX = re.compile(
    r"\[\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\]"
)
REPLAY_COVERAGE_RX = re.compile(
    r"Replay\s+coverage:\s*([\d,]+)\s+of\s+([\d,]+)\s+committed\s+episodes\s+re-played,\s*"
    r"([\d,]+)\s+consistent;\s*([\d,]+)\s+recorded\s+tool\s+results\s+compared\s+step\s+by\s+step,\s*"
    r"([\d,]+)\s+differ",
    re.IGNORECASE,
)
HARBOR_SUMMARY_RX = re.compile(
    r"(\d+)\s+of\s+(\d+)\s+trials\s+and\s+(\d+)\s+of\s+(\d+)\s+job\s+summaries\s+consistent",
    re.IGNORECASE,
)
LADDER_SUMMARY_RX = re.compile(
    r"(\d+)\s+valid\s+Gemini\s+episodes\s+in\s+(\d+)\s+cells;\s+ledger:\s*([\d,]+)\s+calls",
    re.IGNORECASE,
)
SWARM_EXPLOITS_RX = re.compile(
    r"Verified\s+exploits:\s*\*{0,2}(\d+)\*{0,2}",
    re.IGNORECASE,
)
SWARM_CALLS_RX = re.compile(
    r"Tool\s+calls\s+executed:\s*\*{0,2}([\d,]+)\*{0,2}",
    re.IGNORECASE,
)
JUDGE_TABLE_HEADER_GIT_RX = re.compile(r"-\s*git:\s*`([^`]+)`")
JUDGE_TABLE_ROW_GIT_RX = re.compile(r"\bgit\s+([^(\n;|]+)")
NUMBER_TOKEN_RX = re.compile(r"(?<![A-Za-z0-9_.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?%?)(?![A-Za-z0-9_])")


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class _ParsedTable:
    heading: str
    headers: list[str]
    rows: list[list[str]]


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite(val: Any) -> bool:
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and math.isfinite(float(val))
    )


def _norm_num_text(raw: str) -> str:
    cleaned = raw.replace(UNICODE_MINUS, "-")
    cleaned = re.sub(r"[*`]", "", cleaned)
    return cleaned.strip()


def _strip_md_decor(raw: str) -> str:
    return re.sub(r"[*`]", "", raw).strip()


def _is_dash_cell(raw: str) -> bool:
    cleaned = _strip_md_decor(raw)
    return cleaned in {"-", EN_DASH, EM_DASH}


def _parse_float_token(raw: str) -> float | None:
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", _norm_num_text(raw))
    m = re.search(r"[+-]?\d+(?:\.\d+)?", cleaned)
    if m is None:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_int_token(raw: str) -> int | None:
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", _norm_num_text(raw))
    if re.fullmatch(r"[+-]?\d+", cleaned):
        return int(cleaned)
    return None


def _parse_mean_ci(raw: str) -> tuple[float, float] | None:
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", _norm_num_text(raw))
    m = MEAN_CI_RX.search(cleaned)
    if m is None:
        return None
    return float(m.group(1)), float(m.group(2))


def _parse_pct_ci(raw: str) -> tuple[float, float, float] | None:
    cleaned = _norm_num_text(raw)
    m = PCT_CI_RX.search(cleaned)
    if m is None:
        return None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def _parse_range_brackets(raw: str) -> tuple[float, float] | None:
    cleaned = _norm_num_text(raw)
    m = RANGE_BRACKET_RX.search(cleaned)
    if m is None:
        return None
    return float(m.group(1)), float(m.group(2))


def _require_text_file(root: Path, rel: str, failures: list[str]) -> str | None:
    path = root / rel
    if not path.is_file():
        failures.append(f"missing required file: {rel}")
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"unreadable file {rel}: {type(exc).__name__}")
        return None
    if not text.strip():
        failures.append(f"empty or whitespace-only file: {rel}")
        return None
    return text


def _require_json_file(root: Path, rel: str, failures: list[str]) -> Any:
    text = _require_text_file(root, rel, failures)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        failures.append(f"invalid JSON in {rel}: {exc}")
        return None


def _parse_markdown_tables(md_text: str) -> list[_ParsedTable]:
    tables: list[_ParsedTable] = []
    headings: dict[int, str] = {}
    cur_headers: list[str] | None = None
    cur_rows: list[list[str]] = []
    cur_heading = ""
    in_fence = False
    fence_char = ""
    fence_len = 0

    def _flush() -> None:
        nonlocal cur_headers, cur_rows
        if cur_headers is not None and cur_rows:
            tables.append(_ParsedTable(cur_heading, cur_headers, cur_rows))
        cur_headers = None
        cur_rows = []

    for raw_line in md_text.splitlines():
        fm = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if fm:
                _flush()
                marker = fm.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                continue
        else:
            if fm:
                marker = fm.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue

        stripped = raw_line.strip()
        if stripped.startswith(HASH_CHAR):
            _flush()
            hashes = len(stripped) - len(stripped.lstrip(HASH_CHAR))
            if 1 <= hashes <= 6 and (len(stripped) == hashes or stripped[hashes].isspace()):
                title = stripped[hashes:].strip()
                for lvl in list(headings):
                    if lvl >= hashes:
                        del headings[lvl]
                headings[hashes] = title
            continue

        if not (stripped.startswith("|") and stripped.endswith("|")):
            _flush()
            continue

        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if cur_headers is None:
            cur_headers = [_strip_md_decor(c).lower() for c in cells]
            cur_rows = []
            cur_heading = " > ".join(headings[k] for k in sorted(headings))
        else:
            if len(cells) < len(cur_headers):
                cells.extend([""] * (len(cur_headers) - len(cells)))
            cur_rows.append(cells)

    _flush()
    return tables


def _norm_label_key(s: str) -> str:
    cleaned = _strip_md_decor(s).replace(UNICODE_MINUS, "-").replace(EN_DASH, "-").replace(EM_DASH, "-")
    return " ".join(cleaned.lower().split())


def _verify_paired_table_pair(
    root: Path,
    json_rel: str,
    md_rel: str,
    failures: list[str],
    *,
    require_pooled_row: bool = False,
) -> int:
    data = _require_json_file(root, json_rel, failures)
    md_txt = _require_text_file(root, md_rel, failures)
    if data is None or md_txt is None:
        return 0
    if not isinstance(data, list) or not data:
        failures.append(f"{json_rel}: expected non-empty JSON list")
        return 0

    tables = _parse_markdown_tables(md_txt)
    if not tables:
        failures.append(f"{md_rel}: missing markdown table")
        return 0
    tbl = tables[0]
    if len(tbl.rows) != len(data):
        failures.append(
            f"{md_rel}: row count {len(tbl.rows)} != {json_rel} row count {len(data)}"
        )

    md_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for cells in tbl.rows:
        row_map = dict(zip(tbl.headers, cells))
        t_key = _strip_md_decor(row_map.get("tier", "")).lower()
        l_key = _norm_label_key(row_map.get("run", ""))
        key = (t_key, l_key)
        if key in md_by_key:
            failures.append(f"{md_rel}: duplicate row key {key}")
        md_by_key[key] = row_map

    checked = 0
    found_pooled_32 = False
    found_solver_60 = False

    for idx, jrow in enumerate(data):
        if not isinstance(jrow, dict):
            failures.append(f"{json_rel}[{idx}]: expected object")
            continue
        tier = str(jrow.get("tier", "")).strip().lower()
        label = str(jrow.get("label", "")).strip()
        key = (tier, _norm_label_key(label))
        mrow = md_by_key.get(key)
        if mrow is None:
            failures.append(f"{md_rel}: missing companion row for ({tier!r}, {label!r})")
            continue

        n_json = jrow.get("n")
        n_md = _parse_int_token(mrow.get("n", ""))
        if not _is_int(n_json) or n_md != int(n_json):
            failures.append(f"{md_rel} ({tier}, {label[:32]}): n={n_md!r} != JSON {n_json!r}")
            continue

        score_col = next((v for k, v in mrow.items() if k.startswith("score")), "")
        mci = _parse_mean_ci(score_col)
        mean_json = jrow.get("mean")
        ci_json = jrow.get("ci")
        if mci is None or not _is_finite(mean_json) or not _is_finite(ci_json):
            failures.append(f"{md_rel} ({tier}, {label[:32]}): malformed score/CI cell {score_col!r}")
            continue
        if abs(mci[0] - float(mean_json)) > 0.0015 or abs(mci[1] - float(ci_json)) > 0.0015:
            failures.append(
                f"{md_rel} ({tier}, {label[:32]}): score/CI {mci} drifts from JSON ({mean_json:.4f}, {ci_json:.4f})"
            )

        sol_col = next((v for k, v in mrow.items() if "solver" in k and "same" in k), "")
        sol_md = _parse_float_token(sol_col)
        sol_json = jrow.get("solver_same_seeds")
        if sol_md is None or not _is_finite(sol_json) or abs(sol_md - float(sol_json)) > 0.0015:
            failures.append(
                f"{md_rel} ({tier}, {label[:32]}): solver_same_seeds {sol_col!r} drifts from JSON {sol_json!r}"
            )

        la_score_col = mrow.get("luck-adjusted score", "")
        la_score_md = _parse_float_token(la_score_col)
        la_score_json = jrow.get("post_expected")
        if (
            la_score_md is None
            or not _is_finite(la_score_json)
            or abs(la_score_md - float(la_score_json)) > 0.0015
        ):
            failures.append(
                f"{md_rel} ({tier}, {label[:32]}): luck-adjusted score {la_score_col!r} drifts from JSON {la_score_json!r}"
            )

        raw_pct_col = next((v for k, v in mrow.items() if "frontier / solver" in k), "")
        la_pct_col = next((v for k, v in mrow.items() if k.startswith("luck-adj.")), "")
        is_solver_row = str(jrow.get("agent", "")) == "solver"

        if is_solver_row:
            if not _is_dash_cell(raw_pct_col) or not _is_dash_cell(la_pct_col):
                failures.append(
                    f"{md_rel} ({tier}, solver): expected dash cells for solver ratios, got {raw_pct_col!r} / {la_pct_col!r}"
                )
        else:
            raw_pci = _parse_pct_ci(raw_pct_col)
            r_val, r_lo, r_hi = jrow.get("ratio"), jrow.get("ratio_lo"), jrow.get("ratio_hi")
            if raw_pci is None or not (_is_finite(r_val) and _is_finite(r_lo) and _is_finite(r_hi)):
                failures.append(
                    f"{md_rel} ({tier}, {label[:32]}): malformed raw ratio cell {raw_pct_col!r}"
                )
            elif (
                abs(raw_pci[0] - float(r_val) * 100.0) > 1.0
                or abs(raw_pci[1] - float(r_lo) * 100.0) > 1.0
                or abs(raw_pci[2] - float(r_hi) * 100.0) > 1.0
            ):
                failures.append(
                    f"{md_rel} ({tier}, {label[:32]}): raw ratio {raw_pci} drifts from JSON "
                    f"({float(r_val)*100.0:.2f}%, [{float(r_lo)*100.0:.2f}%, {float(r_hi)*100.0:.2f}%])"
                )

            la_pci = _parse_pct_ci(la_pct_col)
            p_val = jrow.get("post_expected_ratio")
            p_lo = jrow.get("post_expected_lo")
            p_hi = jrow.get("post_expected_hi")
            if la_pci is None or not (_is_finite(p_val) and _is_finite(p_lo) and _is_finite(p_hi)):
                failures.append(
                    f"{md_rel} ({tier}, {label[:32]}): malformed luck-adj ratio cell {la_pct_col!r}"
                )
            elif (
                abs(la_pci[0] - float(p_val) * 100.0) > 1.0
                or abs(la_pci[1] - float(p_lo) * 100.0) > 1.0
                or abs(la_pci[2] - float(p_hi) * 100.0) > 1.0
            ):
                failures.append(
                    f"{md_rel} ({tier}, {label[:32]}): luck-adj ratio {la_pci} drifts from JSON "
                    f"({float(p_val)*100.0:.2f}%, [{float(p_lo)*100.0:.2f}%, {float(p_hi)*100.0:.2f}%])"
                )

            if require_pooled_row and tier == "hard" and "pooled" in label.lower():
                if (
                    int(n_json) == 32
                    and raw_pci == (68.0, 32.0, 100.0)
                    and la_pci == (75.0, 56.0, 93.0)
                ):
                    found_pooled_32 = True
                else:
                    failures.append(
                        f"{md_rel}: pooled hard row expected n=32, 68% [32%, 100%] raw, 75% [56%, 93%] luck-adj; "
                        f"got n={n_json}, raw={raw_pci}, luck-adj={la_pci}"
                    )

        if require_pooled_row and tier == "hard" and is_solver_row and int(n_json) == 60:
            found_solver_60 = True

        checked += 1

    if require_pooled_row:
        if not found_pooled_32:
            failures.append(f"{md_rel}: missing verified pooled hard n=32 row")
        if not found_solver_60:
            failures.append(f"{md_rel}: missing verified reference solver hard n=60 row")

    return checked


def _verify_oracle_range(root: Path, failures: list[str]) -> int:
    json_rel = "results/oracle_range_v1.4.json"
    md_rel = "results/oracle_range_v1.4.md"
    obj = _require_json_file(root, json_rel, failures)
    md_txt = _require_text_file(root, md_rel, failures)
    if obj is None or md_txt is None:
        return 0
    if not isinstance(obj, dict) or not isinstance(obj.get("rows"), list):
        failures.append(f"{json_rel}: missing 'rows' list")
        return 0

    tables = _parse_markdown_tables(md_txt)
    if not tables:
        failures.append(f"{md_rel}: missing markdown table")
        return 0
    tbl = tables[0]
    md_rows: dict[tuple[str, str, int], dict[str, str]] = {}
    for cells in tbl.rows:
        rmap = dict(zip(tbl.headers, cells))
        ag = _strip_md_decor(rmap.get("agent", "")).lower()
        tr = _strip_md_decor(rmap.get("tier", "")).lower()
        k_val = _parse_int_token(rmap.get("k tasks", ""))
        if ag and tr and k_val is not None:
            md_rows[(ag, tr, k_val)] = rmap

    seen_keys: set[tuple[str, str, int]] = set()
    for idx, jrow in enumerate(obj["rows"]):
        if not isinstance(jrow, dict):
            failures.append(f"{json_rel}.rows[{idx}]: expected object")
            continue
        ag = str(jrow.get("agent", "")).strip().lower()
        tr = str(jrow.get("tier", "")).strip().lower()
        for k_num in (2, 3, 10, 20):
            k_field = f"k{k_num}"
            if k_field not in jrow:
                continue
            kobj = jrow.get(k_field)
            if not isinstance(kobj, dict):
                failures.append(f"{json_rel} ({ag}, {tr}, {k_field}): expected object")
                continue
            key = (ag, tr, k_num)
            mrow = md_rows.get(key)
            if mrow is None:
                failures.append(f"{md_rel}: missing row for {key}")
                continue
            for col_name, json_key in (
                ("mean", "mean"),
                ("sd", "sd"),
                ("p5", "p5"),
                ("p50", "p50"),
                ("p95", "p95"),
            ):
                md_v = _parse_float_token(mrow.get(col_name, ""))
                j_v = kobj.get(json_key)
                if md_v is None or not _is_finite(j_v) or abs(md_v - float(j_v)) > 0.0015:
                    failures.append(
                        f"{md_rel} {key} {col_name}: md={mrow.get(col_name)!r} vs json={j_v!r}"
                    )
            pneg_col = next((v for hdr, v in mrow.items() if "p(mean<0)" in hdr), "")
            pneg_md = _parse_float_token(pneg_col)
            pneg_j = kobj.get("p_lt0")
            if (
                pneg_md is None
                or not _is_finite(pneg_j)
                or abs(pneg_md - float(pneg_j) * 100.0) > 0.15
            ):
                failures.append(
                    f"{md_rel} {key} P(mean<0): md={pneg_col!r} vs json={pneg_j!r}"
                )
            seen_keys.add(key)

    for req_key in REQUIRED_ORACLE_KEYS:
        if req_key not in seen_keys:
            failures.append(f"{md_rel}: required oracle range cell {req_key} not verified")

    return len(seen_keys)


def _verify_solver_range(root: Path, failures: list[str]) -> int:
    sr_dir = root / "results" / "solver_range"
    if not sr_dir.is_dir():
        failures.append("missing directory: results/solver_range")
        return 0

    json_stems = {p.stem for p in sr_dir.glob("*.json")}
    md_stems = {p.stem for p in sr_dir.glob("*.md")}
    all_stems = sorted(set(SOLVER_RANGE_STEMS) | json_stems | md_stems)

    checked = 0
    for stem in all_stems:
        j_rel = f"results/solver_range/{stem}.json"
        m_rel = f"results/solver_range/{stem}.md"
        obj = _require_json_file(root, j_rel, failures)
        md_txt = _require_text_file(root, m_rel, failures)
        if obj is None or md_txt is None:
            continue
        if not isinstance(obj, dict):
            failures.append(f"{j_rel}: expected JSON object")
            continue

        builds = obj.get("builds")
        if not _is_int(builds) or int(builds) != 300:
            failures.append(f"{j_rel}: expected builds=300, got {builds!r}")
        if re.search(r"(?<![0-9.])300(?![0-9.])", md_txt) is None:
            failures.append(f"{m_rel}: missing builds=300 in companion markdown")

        tables = _parse_markdown_tables(md_txt)
        if not tables:
            failures.append(f"{m_rel}: missing statistic markdown table")
            continue
        stat_map: dict[str, str] = {}
        for cells in tables[0].rows:
            if len(cells) >= 2:
                stat_map[_strip_md_decor(cells[0]).lower()] = cells[1]

        md_mean = _parse_float_token(stat_map.get("mean over builds", ""))
        md_sd = _parse_float_token(stat_map.get("standard deviation over builds", ""))
        md_med = _parse_float_token(stat_map.get("median", ""))
        j_mean = obj.get("mean")
        j_sd = obj.get("sd")
        p_obj = obj.get("p") if isinstance(obj.get("p"), dict) else {}
        j_med = p_obj.get("0.5")
        j_p5 = p_obj.get("0.05")
        j_p95 = p_obj.get("0.95")

        if md_mean is None or not _is_finite(j_mean) or abs(md_mean - float(j_mean)) > 0.0015:
            failures.append(f"{m_rel}: mean {stat_map.get('mean over builds')!r} != JSON {j_mean!r}")
        if md_sd is None or not _is_finite(j_sd) or abs(md_sd - float(j_sd)) > 0.0015:
            failures.append(
                f"{m_rel}: sd {stat_map.get('standard deviation over builds')!r} != JSON {j_sd!r}"
            )
        if md_med is None or not _is_finite(j_med) or abs(md_med - float(j_med)) > 0.0015:
            failures.append(f"{m_rel}: median {stat_map.get('median')!r} != JSON {j_med!r}")

        range90_cell = next((v for k, v in stat_map.items() if "90% range" in k), "")
        r90 = _parse_range_brackets(range90_cell)
        if (
            r90 is None
            or not _is_finite(j_p5)
            or not _is_finite(j_p95)
            or abs(r90[0] - float(j_p5)) > 0.01
            or abs(r90[1] - float(j_p95)) > 0.01
        ):
            failures.append(
                f"{m_rel}: 90% range {range90_cell!r} != JSON [{j_p5!r}, {j_p95!r}]"
            )

        checked += 1

    return checked


def _verify_anticheat_exploits(root: Path, failures: list[str]) -> None:
    json_rel = "results/anticheat/exploits.json"
    md_rel = "results/anticheat/exploits.md"
    obj = _require_json_file(root, json_rel, failures)
    md_txt = _require_text_file(root, md_rel, failures)
    if obj is None or md_txt is None:
        return
    if not isinstance(obj, dict):
        failures.append(f"{json_rel}: expected JSON object")
        return

    rows = obj.get("rows")
    if not isinstance(rows, list) or len(rows) != 99:
        failures.append(
            f"{json_rel}: expected 99 anti-cheat rows, got {len(rows) if isinstance(rows, list) else type(rows).__name__}"
        )
        return

    tables = _parse_markdown_tables(md_txt)
    probe_tbl = next((t for t in tables if "probe" in t.headers and "blocked" in t.headers), None)
    if probe_tbl is None:
        failures.append(f"{md_rel}: missing anti-cheat probe table")
    else:
        if len(probe_tbl.rows) != len(rows):
            failures.append(
                f"{md_rel}: probe row count {len(probe_tbl.rows)} != JSON {len(rows)}"
            )
        md_probes: dict[tuple[str, str], dict[str, str]] = {}
        for cells in probe_tbl.rows:
            rmap = dict(zip(probe_tbl.headers, cells))
            tr = _strip_md_decor(rmap.get("tier", "")).lower()
            pr = _strip_md_decor(rmap.get("probe", ""))
            md_probes[(tr, pr)] = rmap

        for idx, jrow in enumerate(rows):
            if not isinstance(jrow, dict):
                failures.append(f"{json_rel}.rows[{idx}]: expected object")
                continue
            tr = str(jrow.get("tier", "")).lower()
            pr = str(jrow.get("probe", ""))
            mrow = md_probes.get((tr, pr))
            if mrow is None:
                failures.append(f"{md_rel}: missing probe row ({tr}, {pr})")
                continue
            n_md = _parse_int_token(mrow.get("n", ""))
            if n_md != jrow.get("n"):
                failures.append(f"{md_rel} ({tr}, {pr}): n={n_md!r} != JSON {jrow.get('n')!r}")
            mci_col = next((v for k, v in mrow.items() if "mean" in k), "")
            mci = _parse_mean_ci(mci_col)
            if (
                mci is None
                or not _is_finite(jrow.get("mean"))
                or not _is_finite(jrow.get("ci95"))
                or abs(mci[0] - float(jrow["mean"])) > 0.0015
                or abs(mci[1] - float(jrow["ci95"])) > 0.0015
            ):
                failures.append(f"{md_rel} ({tr}, {pr}): mean/CI {mci_col!r} != JSON")
            max_md = _parse_float_token(mrow.get("max", ""))
            if max_md is None or not _is_finite(jrow.get("max")) or abs(max_md - float(jrow["max"])) > 0.0015:
                failures.append(f"{md_rel} ({tr}, {pr}): max {mrow.get('max')!r} != JSON {jrow.get('max')!r}")
            pos_md = _parse_int_token(mrow.get("episodes > 0", ""))
            if pos_md != jrow.get("positive"):
                failures.append(
                    f"{md_rel} ({tr}, {pr}): episodes>0 {pos_md!r} != JSON {jrow.get('positive')!r}"
                )
            blk_cell = _strip_md_decor(mrow.get("blocked", "")).lower()
            if jrow.get("kind") == "reference":
                if not _is_dash_cell(mrow.get("blocked", "")):
                    failures.append(f"{md_rel} ({tr}, {pr}): reference row blocked expected '-', got {blk_cell!r}")
            else:
                expected_blk = "yes" if bool(jrow.get("blocked")) else "no"
                if blk_cell != expected_blk:
                    failures.append(
                        f"{md_rel} ({tr}, {pr}): blocked={blk_cell!r} != JSON {expected_blk!r}"
                    )

    rc = obj.get("replay_counts")
    replay_list = obj.get("replay")
    if not isinstance(rc, dict) or not isinstance(replay_list, list):
        failures.append(f"{json_rel}: missing replay_counts or replay list")
    else:
        j_replayed = rc.get("replayed")
        j_total = rc.get("n")
        j_cons = rc.get("consistent")
        j_steps = rc.get("steps")
        j_diff = rc.get("step_mismatches")
        if (j_replayed, j_total, j_cons, j_steps, j_diff) != (1021, 1031, 1021, 51814, 0):
            failures.append(
                f"{json_rel}: replay_counts expected (1021, 1031, 1021, 51814, 0), got "
                f"{(j_replayed, j_total, j_cons, j_steps, j_diff)}"
            )
        sum_rep = sum(int(x.get("replayed", 0)) for x in replay_list if isinstance(x, dict))
        sum_n = sum(int(x.get("n", 0)) for x in replay_list if isinstance(x, dict))
        sum_steps = sum(int(x.get("steps", 0)) for x in replay_list if isinstance(x, dict))
        if (sum_rep, sum_n, sum_steps) != (j_replayed, j_total, j_steps):
            failures.append(
                f"{json_rel}: sum(replay) {(sum_rep, sum_n, sum_steps)} != replay_counts {(j_replayed, j_total, j_steps)}"
            )

        m_rep = REPLAY_COVERAGE_RX.search(md_txt)
        if m_rep is None:
            failures.append(f"{md_rel}: missing 'Replay coverage: ...' summary line")
        else:
            md_tuple = tuple(int(g.replace(",", "")) for g in m_rep.groups())
            if md_tuple != (j_replayed, j_total, j_cons, j_steps, j_diff):
                failures.append(
                    f"{md_rel}: replay summary {md_tuple} != JSON {(j_replayed, j_total, j_cons, j_steps, j_diff)}"
                )

    harbor_list = obj.get("harbor")
    if not isinstance(harbor_list, list):
        failures.append(f"{json_rel}: missing 'harbor' list")
    else:
        trials = [h for h in harbor_list if isinstance(h, dict) and h.get("kind") == "trial"]
        jobs = [h for h in harbor_list if isinstance(h, dict) and h.get("kind") == "job"]
        cons_trials = sum(1 for h in trials if bool(h.get("consistent")))
        cons_jobs = sum(1 for h in jobs if bool(h.get("consistent")))
        if (cons_trials, len(trials), cons_jobs, len(jobs)) != (80, 80, 18, 18):
            failures.append(
                f"{json_rel}: harbor counts expected (80, 80, 18, 18), got {(cons_trials, len(trials), cons_jobs, len(jobs))}"
            )
        m_hb = HARBOR_SUMMARY_RX.search(md_txt)
        if m_hb is None:
            failures.append(f"{md_rel}: missing Harbor trial/job consistency summary line")
        else:
            md_hb = tuple(int(g) for g in m_hb.groups())
            if md_hb != (cons_trials, len(trials), cons_jobs, len(jobs)):
                failures.append(
                    f"{md_rel}: Harbor summary {md_hb} != JSON {(cons_trials, len(trials), cons_jobs, len(jobs))}"
                )


def _verify_failure_analysis(root: Path, failures: list[str]) -> None:
    json_rel = "results/failure_analysis_v1.4.json"
    md_rel = "docs/reports/failure_analysis_v1.4.md"
    obj = _require_json_file(root, json_rel, failures)
    md_txt = _require_text_file(root, md_rel, failures)
    if obj is None or md_txt is None:
        return
    summary = obj.get("summary") if isinstance(obj, dict) else None
    if not isinstance(summary, dict):
        failures.append(f"{json_rel}: missing 'summary' object")
        return
    gap = summary.get("gap")
    oc = summary.get("opencode")
    sv = summary.get("solver")
    if not isinstance(gap, dict) or not isinstance(oc, dict) or not isinstance(sv, dict):
        failures.append(f"{json_rel}: summary missing gap/opencode/solver objects")
        return

    try:
        raw_gap = float(gap["raw_gap"])
        la_gap = float(gap["la_gap"])
        luck = float(gap["luck"])
        penalty = float(gap["penalty"])
        abstain = float(gap["abstain"])
        leak = float(gap["leak"])
        restrict = float(gap["restrict"])
        canary = float(gap["canary"])
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"{json_rel}: malformed gap component field: {exc}")
        return

    if abs(raw_gap - 5.30) > 0.015 or abs(la_gap - 4.19) > 0.015 or abs(luck - 1.11) > 0.015:
        failures.append(
            f"{json_rel}: expected 5.30 = 4.19 + 1.11 gap decomposition, got raw={raw_gap:.4f}, la={la_gap:.4f}, luck={luck:.4f}"
        )
    if abs((la_gap + luck) - raw_gap) > 1e-4:
        failures.append(f"{json_rel}: la_gap + luck ({la_gap + luck:.6f}) != raw_gap ({raw_gap:.6f})")
    comp_sum = penalty + abstain + leak + restrict + canary
    if abs(comp_sum - la_gap) > 1e-4:
        failures.append(f"{json_rel}: sum of 5 mistake components ({comp_sum:.6f}) != la_gap ({la_gap:.6f})")

    tables = _parse_markdown_tables(md_txt)
    mistake_tbl = next(
        (t for t in tables if any("v lost" in h for h in t.headers)),
        None,
    )
    if mistake_tbl is None:
        failures.append(f"{md_rel}: missing mistake decomposition table")
        return

    found_rows: dict[str, tuple[float, float]] = {}
    for cells in mistake_tbl.rows:
        if len(cells) < 4:
            continue
        num_id = _strip_md_decor(cells[0])
        desc = _strip_md_decor(cells[1]).lower()
        v_tot = _parse_float_token(cells[2])
        v_ep = _parse_float_token(cells[3])
        if v_tot is None or v_ep is None:
            continue
        if num_id in {"1", "2", "3", "4", "5"}:
            found_rows[f"row{num_id}"] = (v_tot, v_ep)
        elif "luck-adjusted gap" in desc:
            found_rows["la_gap"] = (v_tot, v_ep)
        elif "bad luck" in desc:
            found_rows["luck"] = (v_tot, v_ep)
        elif "raw gap" in desc:
            found_rows["raw_gap"] = (v_tot, v_ep)

    expected_components: tuple[tuple[str, float], ...] = (
        ("row1", penalty),
        ("row2", abstain),
        ("row3", leak),
        ("row4", restrict),
        ("row5", canary),
        ("la_gap", la_gap),
        ("luck", luck),
        ("raw_gap", raw_gap),
    )
    for tag, jval in expected_components:
        pair = found_rows.get(tag)
        if pair is None:
            failures.append(f"{md_rel}: missing decomposition row '{tag}'")
            continue
        if abs(pair[0] - jval) > 0.015:
            failures.append(
                f"{md_rel}: component '{tag}' V_lost={pair[0]:.2f} drifts from JSON {jval:.4f}"
            )
        if abs(pair[1] - (jval / 30.0)) > 0.002:
            failures.append(
                f"{md_rel}: component '{tag}' per_episode={pair[1]:.3f} drifts from JSON {jval / 30.0:.4f}"
            )


def _norm_ladder_model(raw_cell: str) -> str:
    clean = _strip_md_decor(raw_cell).replace(DAGGER, "").strip().lower()
    if "3.5-flash" in clean or "3.6-flash" in clean:
        return "gemini-3.5-flash"
    if clean.startswith("gemini-4-carbon"):
        return "gemini-4-carbon"
    return clean.split()[0] if clean else ""


def _verify_gemini_companions(root: Path, failures: list[str]) -> None:
    l_json_rel = "results/gemini/ladder.json"
    l_md_rel = "results/gemini/ladder.md"
    l_obj = _require_json_file(root, l_json_rel, failures)
    l_md = _require_text_file(root, l_md_rel, failures)
    if l_obj is not None and l_md is not None:
        if not isinstance(l_obj, dict) or not isinstance(l_obj.get("rows"), list):
            failures.append(f"{l_json_rel}: missing 'rows' list")
        else:
            j_eps = l_obj.get("episodes")
            j_rows = l_obj["rows"]
            sum_n = sum(int(r.get("n", 0)) for r in j_rows if isinstance(r, dict))
            if not _is_int(j_eps) or int(j_eps) != 587 or sum_n != int(j_eps):
                failures.append(
                    f"{l_json_rel}: expected episodes=587 == sum(rows.n), got episodes={j_eps!r}, sum={sum_n}"
                )
            ledger = l_obj.get("ledger") if isinstance(l_obj.get("ledger"), dict) else {}
            j_calls = ledger.get("calls")

            m_lad = LADDER_SUMMARY_RX.search(l_md)
            if m_lad is None:
                failures.append(f"{l_md_rel}: missing '587 valid Gemini episodes in 42 cells...' summary line")
            else:
                md_eps = int(m_lad.group(1))
                md_cells = int(m_lad.group(2))
                md_calls = int(m_lad.group(3).replace(",", ""))
                if md_eps != int(j_eps) or md_cells != len(j_rows):
                    failures.append(
                        f"{l_md_rel}: summary ({md_eps} eps, {md_cells} cells) != JSON ({j_eps}, {len(j_rows)})"
                    )
                if _is_int(j_calls) and md_calls != int(j_calls):
                    failures.append(f"{l_md_rel}: ledger calls {md_calls} != JSON {j_calls}")

            tables = _parse_markdown_tables(l_md)
            md_cell_map: dict[tuple[str, str, str], dict[str, str]] = {}
            for tbl in tables:
                if "thinking" not in tbl.headers or "model" not in tbl.headers:
                    continue
                tier = ""
                h_low = tbl.heading.lower()
                if h_low.endswith("medium") or " > medium" in h_low:
                    tier = "medium"
                elif h_low.endswith("hard") or " > hard" in h_low:
                    tier = "hard"
                if not tier:
                    continue
                for cells in tbl.rows:
                    rmap = dict(zip(tbl.headers, cells))
                    mod = _norm_ladder_model(rmap.get("model", ""))
                    lvl = _strip_md_decor(rmap.get("thinking", "")).lower()
                    md_cell_map[(tier, mod, lvl)] = rmap

            for idx, jrow in enumerate(j_rows):
                if not isinstance(jrow, dict):
                    continue
                key = (
                    str(jrow.get("tier", "")).lower(),
                    str(jrow.get("model", "")).lower(),
                    str(jrow.get("level", "")).lower(),
                )
                mrow = md_cell_map.get(key)
                if mrow is None:
                    failures.append(f"{l_md_rel}: missing ladder table cell {key}")
                    continue
                if _parse_int_token(mrow.get("n", "")) != jrow.get("n"):
                    failures.append(f"{l_md_rel} {key}: n mismatch vs JSON")
                score_col = next((v for k, v in mrow.items() if k.startswith("score") and "solver" not in k), "")
                mci = _parse_mean_ci(score_col)
                if (
                    mci is None
                    or abs(mci[0] - float(jrow["mean"])) > 0.002
                    or abs(mci[1] - float(jrow["ci"])) > 0.01
                ):
                    failures.append(f"{l_md_rel} {key}: score/CI {score_col!r} drifts from JSON")
                raw_col = next((v for k, v in mrow.items() if "score / solver" in k), "")
                pci = _parse_pct_ci(raw_col)
                if pci is None or abs(pci[0] - float(jrow["ratio"]) * 100.0) > 1.0:
                    failures.append(f"{l_md_rel} {key}: ratio {raw_col!r} drifts from JSON")
                sol_col = next((v for k, v in mrow.items() if "solver" in k and "same" in k), "")
                sol_md = _parse_float_token(sol_col)
                if sol_md is None or abs(sol_md - float(jrow["solver_same_seeds"])) > 0.002:
                    failures.append(f"{l_md_rel} {key}: solver_same_seeds {sol_col!r} drifts from JSON")
                la_col = next((v for k, v in mrow.items() if "luck-adj." in k), "")
                la_pci = _parse_pct_ci(la_col)
                if la_pci is None or abs(la_pci[0] - float(jrow["luck_adj_ratio"]) * 100.0) > 1.0:
                    failures.append(f"{l_md_rel} {key}: luck_adj_ratio {la_col!r} drifts from JSON")

    s_json_rel = "results/gemini/swarm.json"
    s_md_rel = "results/gemini/swarm.md"
    s_obj = _require_json_file(root, s_json_rel, failures)
    s_md = _require_text_file(root, s_md_rel, failures)
    if s_obj is not None and s_md is not None:
        if not isinstance(s_obj, dict):
            failures.append(f"{s_json_rel}: expected JSON object")
            return
        counts = s_obj.get("counts")
        waves = s_obj.get("waves")
        if not isinstance(counts, dict) or not isinstance(waves, list) or not waves:
            failures.append(f"{s_json_rel}: missing counts or waves")
            return
        fin_sum = sum(int(w.get("finished", 0)) for w in waves if isinstance(w, dict))
        calls_j = counts.get("tool_calls")
        exp_j = counts.get("exploits")
        if (fin_sum, calls_j, exp_j) != (91, 4325, 0):
            failures.append(
                f"{s_json_rel}: expected (finished=91, tool_calls=4325, exploits=0), got {(fin_sum, calls_j, exp_j)}"
            )

        m_exp = SWARM_EXPLOITS_RX.search(s_md)
        if m_exp is None or int(m_exp.group(1)) != int(exp_j):
            failures.append(f"{s_md_rel}: 'Verified exploits' mismatch vs JSON ({exp_j})")
        m_calls = SWARM_CALLS_RX.search(s_md)
        if m_calls is None or int(m_calls.group(1).replace(",", "")) != int(calls_j):
            failures.append(f"{s_md_rel}: 'Tool calls executed' mismatch vs JSON ({calls_j})")

        tables = _parse_markdown_tables(s_md)
        found_all_waves = False
        for tbl in tables:
            if "finished" not in tbl.headers or "tool calls" not in tbl.headers:
                continue
            for cells in tbl.rows:
                rmap = dict(zip(tbl.headers, cells))
                if "all real waves" in _strip_md_decor(rmap.get("wave", "")).lower():
                    found_all_waves = True
                    md_fin = _parse_int_token(rmap.get("finished", ""))
                    md_tc = _parse_int_token(rmap.get("tool calls", ""))
                    md_ve = _parse_int_token(rmap.get("verified exploits", ""))
                    if (md_fin, md_tc, md_ve) != (fin_sum, int(calls_j), int(exp_j)):
                        failures.append(
                            f"{s_md_rel}: 'all real waves' {(md_fin, md_tc, md_ve)} != JSON {(fin_sum, calls_j, exp_j)}"
                        )
        if not found_all_waves:
            failures.append(f"{s_md_rel}: missing 'all real waves' summary row")


def _verify_fresh_clone_logs(root: Path, failures: list[str]) -> int:
    fc_readme = _require_text_file(root, FRESH_CLONE_README_REL, failures)
    af_log = _require_text_file(root, FRESH_CLONE_AF_LOG_REL, failures)
    verified = 0

    for steps_rel, commit_tag, expected_steps, passed_marker in FRESH_CLONE_SPECS:
        steps_txt = _require_text_file(root, steps_rel, failures)
        if steps_txt is None:
            continue
        parsed: list[tuple[str, int, int]] = []
        malformed = False
        for raw_ln in steps_txt.splitlines():
            ln = raw_ln.strip()
            if not ln:
                continue
            m_step = FRESH_CLONE_STEP_RX.match(ln)
            if m_step is None:
                failures.append(f"{steps_rel}: malformed step line {ln!r}")
                malformed = True
                break
            parsed.append((m_step.group(1), int(m_step.group(2)), int(m_step.group(3))))
        if malformed:
            continue

        expected_full = [(nm, 0, sec) for nm, sec in expected_steps]
        if parsed != expected_full:
            failures.append(f"{steps_rel}: steps {parsed} != expected {expected_full}")
            continue

        if fc_readme is not None:
            if commit_tag not in fc_readme:
                failures.append(f"{FRESH_CLONE_README_REL}: missing fresh-clone commit '{commit_tag}'")
            if passed_marker not in fc_readme:
                failures.append(
                    f"{FRESH_CLONE_README_REL}: missing '{passed_marker}' for {commit_tag}"
                )
            for step_name, sec in expected_steps:
                if f"{sec} s" not in fc_readme:
                    failures.append(
                        f"{FRESH_CLONE_README_REL}: missing '{sec} s' ({step_name}) from {steps_rel}"
                    )

        if commit_tag == TAG_AFTERQUERY_PREFIX and af_log is not None:
            for req_marker in (
                TAG_AFTERQUERY_PREFIX,
                passed_marker,
                "SUMMARY: 3 PASS, 1 WARN, 0 FAIL",
            ):
                if req_marker not in af_log:
                    failures.append(f"{FRESH_CLONE_AF_LOG_REL}: missing '{req_marker}'")
            for step_name, sec in expected_steps:
                footer = f"=== {step_name}: exit 0, {sec} s"
                if footer not in af_log:
                    failures.append(f"{FRESH_CLONE_AF_LOG_REL}: missing step footer {footer!r}")

        verified += 1

    return verified


def check_companion_parity(root: Path = ROOT) -> CheckResult:
    name = CHECK_COMPANION
    resolved = root.resolve()
    failures: list[str] = []

    n_pt = _verify_paired_table_pair(
        resolved,
        "data/runs/committed/v1.4/paired_table_gemini.json",
        "data/runs/committed/v1.4/paired_table_gemini.md",
        failures,
        require_pooled_row=False,
    )
    n_pool = _verify_paired_table_pair(
        resolved,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md",
        failures,
        require_pooled_row=True,
    )
    n_or = _verify_oracle_range(resolved, failures)
    n_sr = _verify_solver_range(resolved, failures)
    _verify_anticheat_exploits(resolved, failures)
    _verify_failure_analysis(resolved, failures)
    _verify_gemini_companions(resolved, failures)
    n_fc = _verify_fresh_clone_logs(resolved, failures)

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} JSON-to-Markdown companion parity violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"paired tables ({n_pt}+{n_pool} rows), oracle_range ({n_or} cells), solver_range ({n_sr} files), "
        f"anticheat (99 probes, 1021/1031 replay, 80/80 Harbor), failure_analysis (5.30=4.19+1.11 V), "
        f"Gemini ladder (587 eps) + swarm (91 attackers, 4325 calls, 0 exploits), and fresh_clone ({n_fc} logs incl. 1bc3e281) match",
    )


def _has_dot_git(root: Path) -> bool:
    dot_git = root / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    parent_str = str(root.parent)
    existing = env.get("GIT_CEILING_DIRECTORIES", "").strip()
    if existing:
        parts = [p for p in existing.split(os.pathsep) if p]
        if parent_str not in parts:
            parts.append(parent_str)
        env["GIT_CEILING_DIRECTORIES"] = os.pathsep.join(parts)
    else:
        env["GIT_CEILING_DIRECTORIES"] = parent_str
    return env


def _is_blocked_by_git_ceiling(root: Path) -> bool:
    raw = os.environ.get("GIT_CEILING_DIRECTORIES", "").strip()
    if not raw:
        return False
    resolved_root = root.resolve()
    for entry in raw.split(os.pathsep):
        cleaned = entry.strip()
        if not cleaned:
            continue
        try:
            if Path(cleaned).resolve() == resolved_root:
                return True
        except OSError:
            continue
    return False


def _git_probe_state(root: Path) -> tuple[bool, str]:
    if not _has_dot_git(root):
        return False, ".git absent"
    if _is_blocked_by_git_ceiling(root):
        return False, "GIT_CEILING_DIRECTORIES blocks repo root"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-dir", "--is-shallow-repository"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "git rev-parse unavailable"
    if proc.returncode != 0:
        return False, "git rev-parse blocked"
    lines = [ln.strip().lower() for ln in proc.stdout.splitlines() if ln.strip()]
    if lines and lines[-1] == "true":
        return False, "shallow git clone"
    return True, "active"


def _git_cat_file_exists(root: Path, rev: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "cat-file", "-e", rev],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _git_batch_verify_commits(root: Path, shas: Sequence[str]) -> set[str]:
    unique = sorted(set(shas))
    if not unique:
        return set()
    payload = "\n".join(f"{s}^{{commit}}" for s in unique) + "\n"
    try:
        proc = subprocess.run(
            ["git", "cat-file", "--batch-check"],
            cwd=root,
            env=_git_env(root),
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {s for s in unique if not _git_cat_file_exists(root, f"{s}^{{commit}}")}
    if proc.returncode != 0:
        return {s for s in unique if not _git_cat_file_exists(root, f"{s}^{{commit}}")}

    out_lines = proc.stdout.splitlines()
    if len(out_lines) != len(unique):
        return {s for s in unique if not _git_cat_file_exists(root, f"{s}^{{commit}}")}

    missing: set[str] = set()
    for sha, line in zip(unique, out_lines):
        parts = line.split()
        if len(parts) < 2 or parts[1] != "commit":
            if not _git_cat_file_exists(root, f"{sha}^{{commit}}"):
                missing.add(sha)
    return missing


def _git_resolve_tag_commit(root: Path, tag_name: str) -> str | None:
    tag_ref = f"refs/tags/{tag_name}"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{tag_ref}^{{commit}}"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().lower()


def check_git_provenance(
    root: Path = ROOT,
    *,
    _git_state: tuple[bool, str] | None = None,
) -> CheckResult:
    name = CHECK_GIT
    resolved = root.resolve()
    failures: list[str] = []
    sha_sources: list[tuple[str, str]] = []

    v14_dir = resolved / "data" / "runs" / "committed" / "v1.4"
    meta_files = sorted(v14_dir.rglob("meta.json")) if v14_dir.is_dir() else []
    if not meta_files:
        failures.append("missing data/runs/committed/v1.4/**/meta.json files")
    for mp in meta_files:
        rel = mp.relative_to(resolved).as_posix()
        obj = _require_json_file(resolved, rel, failures)
        if not isinstance(obj, dict):
            if obj is not None:
                failures.append(f"{rel}: expected JSON object")
            continue
        gsha = obj.get("git_sha")
        if not isinstance(gsha, str) or not HEX_SHA_RX.fullmatch(gsha.strip()):
            failures.append(f"{rel}: invalid git_sha {gsha!r}")
        else:
            sha_sources.append((f"{rel}:git_sha", gsha.strip()))

        gshas = obj.get("git_shas")
        if gshas is not None:
            if not isinstance(gshas, list) or not gshas:
                failures.append(f"{rel}: git_shas must be a non-empty list when present")
            else:
                for idx, entry in enumerate(gshas):
                    if not isinstance(entry, str) or not HEX_SHA_RX.fullmatch(entry.strip()):
                        failures.append(f"{rel}: invalid git_shas[{idx}] {entry!r}")
                    else:
                        sha_sources.append((f"{rel}:git_shas[{idx}]", entry.strip()))
                if isinstance(gsha, str) and gsha.strip() not in [str(x).strip() for x in gshas]:
                    failures.append(f"{rel}: git_sha {gsha!r} missing from git_shas")

    jt_rel = "results/judge_table.md"
    jt_txt = _require_text_file(resolved, jt_rel, failures)
    if jt_txt is not None:
        m_hdr = JUDGE_TABLE_HEADER_GIT_RX.search(jt_txt)
        if m_hdr is None:
            failures.append(f"{jt_rel}: missing '- git: `<sha>`' header line")
        else:
            hdr_sha = m_hdr.group(1).strip()
            if not HEX_SHA_RX.fullmatch(hdr_sha):
                failures.append(f"{jt_rel}: invalid header git SHA {hdr_sha!r}")
            else:
                sha_sources.append((f"{jt_rel}:header", hdr_sha))

        row_git_count = 0
        for lineno, line in enumerate(jt_txt.splitlines(), 1):
            if not line.strip().startswith("|") or "replayed," not in line:
                continue
            for gm in JUDGE_TABLE_ROW_GIT_RX.finditer(line):
                raw_chunk = gm.group(1).strip().rstrip(",;.")
                if raw_chunk.lower() == "unknown":
                    continue
                for tok in raw_chunk.split(","):
                    clean_tok = _strip_md_decor(tok).strip()
                    if not clean_tok:
                        continue
                    row_git_count += 1
                    if not HEX_SHA_RX.fullmatch(clean_tok):
                        failures.append(f"{jt_rel}:{lineno}: invalid row git SHA {clean_tok!r}")
                    else:
                        sha_sources.append((f"{jt_rel}:{lineno}", clean_tok))
        if row_git_count == 0:
            failures.append(f"{jt_rel}: found 0 reported-run git SHAs")

    for csha in KEY_CITED_COMMITS:
        if not HEX_SHA_RX.fullmatch(csha):
            failures.append(f"key cited commit invalid hex format: {csha!r}")
        else:
            sha_sources.append(("cited_commit", csha))

    if not HEX_SHA_RX.fullmatch(TAG_AFTERQUERY_PREFIX):
        failures.append(f"expected tag target prefix invalid hex: {TAG_AFTERQUERY_PREFIX!r}")
    else:
        sha_sources.append((f"tag:{TAG_AFTERQUERY_FINAL}", TAG_AFTERQUERY_PREFIX))

    unique_shas = sorted({s for _, s in sha_sources})
    git_active, git_reason = _git_state if _git_state is not None else _git_probe_state(resolved)

    if git_active:
        missing_shas = _git_batch_verify_commits(resolved, unique_shas)
        if missing_shas:
            for src, s in sha_sources:
                if s in missing_shas:
                    failures.append(f"unresolved git commit {s!r} referenced in {src}")

        tag_commit = _git_resolve_tag_commit(resolved, TAG_AFTERQUERY_FINAL)
        if tag_commit is None:
            failures.append(f"missing git tag '{TAG_AFTERQUERY_FINAL}'")
        elif not tag_commit.startswith(TAG_AFTERQUERY_PREFIX):
            failures.append(
                f"git tag '{TAG_AFTERQUERY_FINAL}' points to {tag_commit[:12]}, expected {TAG_AFTERQUERY_PREFIX}*"
            )

        if failures:
            return CheckResult(
                name,
                "FAIL",
                f"{len(failures)} git SHA/tag provenance violation(s)",
                failures,
            )
        return CheckResult(
            name,
            "PASS",
            f"verified {len(unique_shas)} distinct git SHAs across {len(meta_files)} v1.4 meta.json files, "
            f"judge_table.md, and cited commits, plus tag {TAG_AFTERQUERY_FINAL} -> {TAG_AFTERQUERY_PREFIX}",
        )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"gitless zip fallback ({git_reason}): {len(failures)} SHA format/schema violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"gitless zip fallback ({git_reason}): hex-format validated {len(unique_shas)} distinct SHAs across "
        f"{len(meta_files)} v1.4 meta.json files, judge_table.md, cited commits, and {TAG_AFTERQUERY_FINAL} -> {TAG_AFTERQUERY_PREFIX}",
    )


def _extract_ws4_rows(
    md_txt: str, rel: str, failures: list[str]
) -> dict[tuple[str, str], dict[str, str]]:
    tables = _parse_markdown_tables(md_txt)
    if not tables:
        failures.append(f"{rel}: missing WS4 markdown table")
        return {}
    tbl = tables[0]
    out: dict[tuple[str, str], dict[str, str]] = {}
    for cells in tbl.rows:
        rmap = dict(zip(tbl.headers, cells))
        mod = _strip_md_decor(rmap.get("model", "")).strip()
        tr = _strip_md_decor(rmap.get("tier", "")).strip().lower()
        if mod and tr:
            out[(mod, tr)] = rmap
    return out


def check_ws4_tiebreak(root: Path = ROOT) -> CheckResult:
    name = CHECK_WS4
    resolved = root.resolve()
    failures: list[str] = []

    readme_rel = "README.md"
    v3_rel = "fr8/analysis/out/ws4_table_v3.md"
    s1s2_rel = "fr8/analysis/out/ws4_table_8k_s1s2.md"
    sum_rel = "data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json"

    readme_txt = _require_text_file(resolved, readme_rel, failures)
    v3_txt = _require_text_file(resolved, v3_rel, failures)
    s1s2_txt = _require_text_file(resolved, s1s2_rel, failures)
    sum_obj = _require_json_file(resolved, sum_rel, failures)
    if readme_txt is None or v3_txt is None or s1s2_txt is None or sum_obj is None:
        return CheckResult(name, "FAIL", f"{len(failures)} missing WS4 tiebreak input(s)", failures)

    tables = _parse_markdown_tables(readme_txt)
    tiebreak_tbl = next(
        (t for t in tables if "tiebreak" in t.heading.lower() and "model" in t.headers),
        None,
    )
    if tiebreak_tbl is None:
        failures.append("README.md: missing Tiebreak markdown table")
        return CheckResult(name, "FAIL", "README.md missing Tiebreak table", failures)

    readme_rows: dict[str, tuple[int | None, str]] = {}
    for cells in tiebreak_tbl.rows:
        rmap = dict(zip(tiebreak_tbl.headers, cells))
        mod_raw = _strip_md_decor(rmap.get("model", "")).lower()
        score_cell = next((v for k, v in rmap.items() if "held-out score" in k or "score" in k), "")
        n_val = _parse_int_token(rmap.get("n", ""))
        if mod_raw.startswith("base"):
            readme_rows["base"] = (n_val, score_cell)
        elif mod_raw.startswith("v2"):
            readme_rows["v2"] = (n_val, score_cell)
        elif mod_raw.startswith("v3-4k"):
            readme_rows["v3_4k"] = (n_val, score_cell)
        elif "v3-8k" in mod_raw and "seed 2" in mod_raw:
            readme_rows["v3_8k_s2"] = (n_val, score_cell)

    for req in ("base", "v2", "v3_4k", "v3_8k_s2"):
        if req not in readme_rows:
            failures.append(f"README.md Tiebreak table missing '{req}' row")

    v3_map = _extract_ws4_rows(v3_txt, v3_rel, failures)
    s1s2_map = _extract_ws4_rows(s1s2_txt, s1s2_rel, failures)

    if "base" in readme_rows:
        r_n, r_sc = readme_rows["base"]
        r_mean = _parse_float_token(r_sc)
        v3_base = v3_map.get(("base", "all"))
        if v3_base is None:
            failures.append(f"{v3_rel}: missing ('base', 'all') row")
        else:
            v3_n = _parse_int_token(v3_base.get("n", ""))
            v3_mci = _parse_mean_ci(next((v for k, v in v3_base.items() if k.startswith("score")), ""))
            v3_valid = _parse_float_token(v3_base.get("valid calls", ""))
            if r_n != 36 or v3_n != 36:
                failures.append(f"WS4 base n mismatch: README={r_n!r}, {v3_rel}={v3_n!r} (expected 36)")
            if r_mean is None or v3_mci is None or abs(r_mean - 0.0) > 1e-6 or abs(v3_mci[0] - 0.0) > 1e-6:
                failures.append(f"WS4 base score mismatch: README={r_sc!r}, {v3_rel}={v3_mci!r}")
            if "3%" in r_sc and (v3_valid is None or abs(v3_valid - 0.03) > 0.005):
                failures.append(f"WS4 base valid calls mismatch: README='3%', {v3_rel}={v3_valid!r}")

    for key_id, v3_name, s1s2_name, exp_n, exp_mean, exp_ci in (
        ("v2", "v2", "v2", 172, -0.457, 0.086),
        ("v3_4k", "v3-4k-s0", "v3_4k_s0", 180, -0.147, 0.063),
        ("v3_8k_s2", "v3-8k-s2", "v3_8k_s2_H100_693st", 90, -0.050, 0.049),
    ):
        if key_id not in readme_rows:
            continue
        r_n, r_sc = readme_rows[key_id]
        r_mci = _parse_mean_ci(r_sc)
        if r_n != exp_n or r_mci is None or abs(r_mci[0] - exp_mean) > 0.0015 or abs(r_mci[1] - exp_ci) > 0.0015:
            failures.append(
                f"README.md {key_id}: got (n={r_n}, {r_sc!r}), expected (n={exp_n}, {exp_mean:+.3f} +/- {exp_ci:.3f})"
            )
            continue

        for tbl_rel, tbl_map, row_name in (
            (v3_rel, v3_map, v3_name),
            (s1s2_rel, s1s2_map, s1s2_name),
        ):
            trow = tbl_map.get((row_name, "all"))
            if trow is None:
                failures.append(f"{tbl_rel}: missing ({row_name!r}, 'all') row")
                continue
            tn = _parse_int_token(trow.get("n", ""))
            tmci = _parse_mean_ci(next((v for k, v in trow.items() if k.startswith("score")), ""))
            if tn != r_n or tmci is None or abs(tmci[0] - r_mci[0]) > 0.0015 or abs(tmci[1] - r_mci[1]) > 0.0015:
                failures.append(
                    f"{tbl_rel} ({row_name}, all): got (n={tn}, {tmci}), disagrees with README (n={r_n}, {r_mci})"
                )

    m_delta = re.search(
        r"v3-4k\s+vs\s+v2:\s*([+-]?\d+\.\d+)\s*(?:\+/-|" + re.escape(PLUS_MINUS) + r")\s*(\d+\.\d+)",
        _norm_num_text(readme_txt),
        re.IGNORECASE,
    )
    if m_delta is None:
        failures.append("README.md: missing 'v3-4k vs v2: +0.310 +/- 0.107' Tiebreak delta")
    else:
        rd_m, rd_ci = float(m_delta.group(1)), float(m_delta.group(2))
        if abs(rd_m - 0.310) > 0.0015 or abs(rd_ci - 0.107) > 0.0015:
            failures.append(f"README.md v3-4k vs v2 delta ({rd_m}, {rd_ci}) != (+0.310, 0.107)")
        for tbl_rel, tbl_map, row_name in (
            (v3_rel, v3_map, "v3-4k-s0"),
            (s1s2_rel, s1s2_map, "v3_4k_s0"),
        ):
            trow = tbl_map.get((row_name, "all"))
            if trow is not None:
                d_col = next((v for k, v in trow.items() if "vs v2" in k), "")
                dmci = _parse_mean_ci(d_col)
                if dmci is None or abs(dmci[0] - rd_m) > 0.0015 or abs(dmci[1] - rd_ci) > 0.0015:
                    failures.append(
                        f"{tbl_rel} ({row_name}, all) vs v2 delta {d_col!r} disagrees with README ({rd_m:+.3f} +/- {rd_ci:.3f})"
                    )

    by_tier = sum_obj.get("by_tier") if isinstance(sum_obj, dict) else None
    if not isinstance(by_tier, dict):
        failures.append(f"{sum_rel}: missing 'by_tier' object")
    else:
        all_t = by_tier.get("all")
        if not isinstance(all_t, dict):
            failures.append(f"{sum_rel}: missing by_tier.all")
        else:
            sn = all_t.get("n")
            sm = all_t.get("mean_score")
            sci = all_t.get("ci95")
            if sn != 90 or not _is_finite(sm) or not _is_finite(sci):
                failures.append(f"{sum_rel}: invalid by_tier.all ({sn!r}, {sm!r}, {sci!r})")
            elif abs(float(sm) - (-0.050)) > 0.0015 or abs(float(sci) - 0.049) > 0.0015:
                failures.append(
                    f"{sum_rel}: by_tier.all ({sm}, {sci}) drifts from -0.050 +/- 0.049"
                )
        for tier_name in ("easy", "medium", "hard"):
            tb = by_tier.get(tier_name)
            if not isinstance(tb, dict):
                failures.append(f"{sum_rel}: missing by_tier.{tier_name}")
                continue
            tm = tb.get("mean_score")
            tci = tb.get("ci95")
            tn = tb.get("n")
            for tbl_rel, tbl_map, row_name in (
                (v3_rel, v3_map, "v3-8k-s2"),
                (s1s2_rel, s1s2_map, "v3_8k_s2_H100_693st"),
            ):
                trow = tbl_map.get((row_name, tier_name))
                if trow is None:
                    failures.append(f"{tbl_rel}: missing ({row_name}, {tier_name}) row")
                    continue
                md_tn = _parse_int_token(trow.get("n", ""))
                md_tmci = _parse_mean_ci(next((v for k, v in trow.items() if k.startswith("score")), ""))
                if (
                    md_tn != tn
                    or md_tmci is None
                    or not _is_finite(tm)
                    or not _is_finite(tci)
                    or abs(md_tmci[0] - float(tm)) > 0.0015
                    or abs(md_tmci[1] - float(tci)) > 0.0015
                ):
                    failures.append(
                        f"{tbl_rel} ({row_name}, {tier_name}) disagrees with {sum_rel} ({tn}, {tm}, {tci})"
                    )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} WS4 tiebreak consistency violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        "README Tiebreak table (base n=36 0.000, v2 n=172 -0.457+/-0.086, v3-4k n=180 -0.147+/-0.063, "
        "v3-8k s2 n=90 -0.050+/-0.049, v3-4k vs v2 +0.310+/-0.107) matches ws4_table_v3.md, ws4_table_8k_s1s2.md, and summary.json",
    )


def _collect_json_numbers(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        fval = float(obj)
        if math.isfinite(fval):
            out.append(fval)
        return
    if isinstance(obj, list):
        out.append(float(len(obj)))
        for item in obj:
            _collect_json_numbers(item, out)
        return
    if isinstance(obj, dict):
        if "waves" in obj and isinstance(obj["waves"], list):
            fin = sum(
                int(w["finished"])
                for w in obj["waves"]
                if isinstance(w, dict) and _is_int(w.get("finished"))
            )
            out.append(float(fin))
        if "harbor" in obj and isinstance(obj["harbor"], list):
            trials = [h for h in obj["harbor"] if isinstance(h, dict) and h.get("kind") == "trial"]
            jobs = [h for h in obj["harbor"] if isinstance(h, dict) and h.get("kind") == "job"]
            out.append(float(len(trials)))
            out.append(float(len(jobs)))
        for val in obj.values():
            _collect_json_numbers(val, out)


class _ArtifactValueIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[set[str], list[float]]] = {}

    def _load_one(self, rel: str) -> tuple[set[str], list[float]]:
        if rel in self._cache:
            return self._cache[rel]
        path = self.root / rel
        tokens: set[str] = set()
        nums: list[float] = []
        if not path.is_file():
            self._cache[rel] = (tokens, nums)
            return tokens, nums

        suffix = path.suffix.lower()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._cache[rel] = (tokens, nums)
            return tokens, nums

        if suffix == ".json":
            try:
                parsed = json.loads(raw)
                _collect_json_numbers(parsed, nums)
            except ValueError:
                pass
        elif suffix == ".jsonl":
            lines = [ln for ln in raw.splitlines() if ln.strip()]
            nums.append(float(len(lines)))
            valid_count = 0
            for ln in lines:
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("valid", True) is not False:
                    valid_count += 1
                if isinstance(rec, dict) and _is_finite(rec.get("score")):
                    nums.append(float(rec["score"]))
            nums.append(float(valid_count))
        else:
            norm = raw.replace(UNICODE_MINUS, "-")
            for m in NUMBER_TOKEN_RX.finditer(norm):
                tok = m.group(1).replace(",", "")
                tokens.add(tok)
                if tok.startswith("+"):
                    tokens.add(tok[1:])
                raw_num = tok[:-1] if tok.endswith("%") else tok
                try:
                    nums.append(float(raw_num))
                except ValueError:
                    pass

        self._cache[rel] = (tokens, nums)
        return tokens, nums

    def matches_token(self, rel_paths: Sequence[str], raw_tok: str) -> bool:
        tok = raw_tok.replace(UNICODE_MINUS, "-").replace(",", "").strip()
        is_pct = tok.endswith("%")
        num_str = tok[:-1] if is_pct else tok
        try:
            target = float(num_str)
        except ValueError:
            return False
        decimals = len(num_str.split(".", 1)[1]) if "." in num_str else 0
        tol = 0.5 * (10.0 ** (-decimals)) + 1e-6
        unsigned = tok.lstrip("+")

        for rel in rel_paths:
            tokens, nums = self._load_one(rel)
            if tok in tokens or unsigned in tokens or f"+{unsigned}" in tokens:
                return True
            for candidate in nums:
                if abs(candidate - target) <= tol or abs(abs(candidate) - abs(target)) <= 1e-9 and target == 0.0:
                    return True
                if is_pct and abs(candidate * 100.0 - target) <= max(tol, 1.0):
                    return True
        return False


def _load_verify_doc_commands_module():
    mod_name = "verify_doc_commands"
    existing = sys.modules.get(mod_name)
    if existing is not None and hasattr(existing, "verify_repo"):
        return existing
    vdc_path = SCRIPT_DIR / "verify_doc_commands.py"
    spec = importlib.util.spec_from_file_location(mod_name, vdc_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {vdc_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _looks_like_repo_path(span: str) -> bool:
    clean = span.strip().rstrip(",;:")
    if not clean or " " in clean or "<" in clean or ">" in clean or "*" in clean or "{" in clean:
        return False
    if clean in KNOWN_REPO_ROOT_ENTRIES:
        return True
    return clean.startswith(KNOWN_REPO_PREFIXES)


def check_provenance_index(
    root: Path = ROOT,
    *,
    _git_state: tuple[bool, str] | None = None,
) -> CheckResult:
    name = CHECK_INDEX
    resolved = root.resolve()
    failures: list[str] = []

    idx_txt = _require_text_file(resolved, PROVENANCE_INDEX_REL, failures)
    if idx_txt is None:
        return CheckResult(name, "FAIL", f"missing {PROVENANCE_INDEX_REL}", failures)

    if EN_DASH in idx_txt or EM_DASH in idx_txt:
        failures.append(f"{PROVENANCE_INDEX_REL}: contains forbidden en/em dash character")

    idx_file = resolved / PROVENANCE_INDEX_REL
    checked_paths: set[str] = set()

    in_fence = False
    fence_char = ""
    fence_len = 0
    for lineno, raw_line in enumerate(idx_txt.splitlines(), 1):
        fm = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if fm:
                marker = fm.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                continue
        else:
            if fm:
                marker = fm.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue

        for im in INLINE_CODE_RX.finditer(raw_line):
            span = im.group(2).strip()
            if _looks_like_repo_path(span):
                clean_rel = span.rstrip("/")
                target = Path(os.path.normpath(str(resolved / clean_rel)))
                try:
                    norm_rel = target.relative_to(resolved).as_posix()
                except ValueError:
                    failures.append(f"{PROVENANCE_INDEX_REL}:{lineno}: path `{span}` escapes root")
                    continue
                if not target.exists():
                    failures.append(f"{PROVENANCE_INDEX_REL}:{lineno}: cited path `{span}` missing on disk")
                elif target.is_file() and target.stat().st_size <= 0:
                    failures.append(f"{PROVENANCE_INDEX_REL}:{lineno}: cited file `{span}` is empty (0 bytes)")
                else:
                    checked_paths.add(norm_rel)

        line_no_code = INLINE_CODE_RX.sub("", raw_line)
        for lm in MD_LINK_RX.finditer(line_no_code):
            dest = (lm.group(1) if lm.group(1) is not None else (lm.group(2) or "")).strip()
            if not dest:
                continue
            dest = dest.split()[0].strip()
            if dest.lower().startswith(("http://", "https://", "mailto:")) or dest.startswith(HASH_CHAR):
                continue
            path_part = unquote(dest.split(HASH_CHAR, 1)[0].split("?", 1)[0]).strip()
            if not path_part:
                continue
            target = Path(os.path.normpath(str(idx_file.parent / path_part)))
            try:
                norm_rel = target.relative_to(resolved).as_posix()
            except ValueError:
                failures.append(f"{PROVENANCE_INDEX_REL}:{lineno}: link '{dest}' escapes root")
                continue
            if not target.exists():
                failures.append(f"{PROVENANCE_INDEX_REL}:{lineno}: broken link '{dest}' ('{norm_rel}')")
            else:
                checked_paths.add(norm_rel)

    required_sections = (
        "frontier gap",
        "causal failure analysis",
        "reward integrity",
        "harbor oracle",
        "craft",
        "ws4 tiebreak",
        "gemini lab",
        "number_audit",
    )
    lower_txt = idx_txt.lower()
    for sec_kw in required_sections:
        if sec_kw not in lower_txt:
            failures.append(f"{PROVENANCE_INDEX_REL}: missing required section/topic '{sec_kw}'")

    for m_idx in range(1, 11):
        m_tok = f"M{m_idx}"
        if re.search(rf"\b{m_tok}\b", idx_txt) is None:
            failures.append(f"{PROVENANCE_INDEX_REL}: missing number_audit closure item '{m_tok}'")

    for req_sha in dict.fromkeys((*AUDIT_CLOSURE_COMMITS, *KEY_CITED_COMMITS)):
        if req_sha not in idx_txt:
            failures.append(f"{PROVENANCE_INDEX_REL}: missing required provenance commit '{req_sha}'")
    if TAG_AFTERQUERY_FINAL not in idx_txt:
        failures.append(f"{PROVENANCE_INDEX_REL}: missing '{TAG_AFTERQUERY_FINAL}' tag provenance")
    for steps_rel, _, _, _ in FRESH_CLONE_SPECS:
        if steps_rel not in idx_txt:
            failures.append(f"{PROVENANCE_INDEX_REL}: missing fresh-clone step log '{steps_rel}'")

    tables = _parse_markdown_tables(idx_txt)
    val_index = _ArtifactValueIndex(resolved)
    ledger_row_count = 0
    verified_num_count = 0
    doc_shas: list[str] = []

    for tbl in tables:
        if (
            "verified value" in tbl.headers
            and "source artifact" in tbl.headers
            and "producing commit" in tbl.headers
        ):
            for cells in tbl.rows:
                rmap = dict(zip(tbl.headers, cells))
                metric = _strip_md_decor(rmap.get("metric", cells[0] if cells else ""))
                val_cell = rmap.get("verified value", "")
                src_cell = rmap.get("source artifact", "")
                sha_cell = rmap.get("producing commit", "")
                cmd_cell = rmap.get("recompute command", "")

                src_paths = [
                    m.group(2).strip().rstrip("/")
                    for m in INLINE_CODE_RX.finditer(src_cell)
                    if _looks_like_repo_path(m.group(2).strip())
                ]
                if not src_paths:
                    failures.append(
                        f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' missing backticked source artifact path"
                    )
                    continue

                num_tokens = [m.group(1) for m in NUMBER_TOKEN_RX.finditer(val_cell)]
                if not num_tokens:
                    failures.append(
                        f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' has 0 numeric tokens in Verified Value"
                    )
                for ntok in num_tokens:
                    if not val_index.matches_token(src_paths, ntok):
                        failures.append(
                            f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' value '{ntok}' not grounded in {src_paths}"
                        )
                    else:
                        verified_num_count += 1

                sha_tokens = [m.group(2).strip() for m in INLINE_CODE_RX.finditer(sha_cell)]
                if not sha_tokens:
                    failures.append(
                        f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' missing backticked commit SHA"
                    )
                for stok in sha_tokens:
                    if stok == TAG_AFTERQUERY_FINAL:
                        continue
                    if not HEX_SHA_RX.fullmatch(stok):
                        failures.append(
                            f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' invalid commit SHA {stok!r}"
                        )
                    else:
                        doc_shas.append(stok)

                if INLINE_CODE_RX.search(cmd_cell) is None:
                    failures.append(
                        f"{PROVENANCE_INDEX_REL}: ledger row '{metric}' missing backticked CLI command"
                    )

                ledger_row_count += 1

        elif "closing commit" in tbl.headers:
            for cells in tbl.rows:
                rmap = dict(zip(tbl.headers, cells))
                item_id = _strip_md_decor(rmap.get("item", cells[0] if cells else ""))
                c_cell = rmap.get("closing commit", "")
                sha_tokens = [m.group(2).strip() for m in INLINE_CODE_RX.finditer(c_cell)]
                if not sha_tokens:
                    failures.append(f"{PROVENANCE_INDEX_REL}: closure row '{item_id}' missing commit SHA")
                for stok in sha_tokens:
                    if not HEX_SHA_RX.fullmatch(stok):
                        failures.append(
                            f"{PROVENANCE_INDEX_REL}: closure row '{item_id}' invalid commit SHA {stok!r}"
                        )
                    else:
                        doc_shas.append(stok)

    if ledger_row_count < 10:
        failures.append(
            f"{PROVENANCE_INDEX_REL}: expected >= 10 master ledger rows, found {ledger_row_count}"
        )

    git_active, _ = _git_state if _git_state is not None else _git_probe_state(resolved)
    if git_active and doc_shas:
        missing_doc_shas = _git_batch_verify_commits(resolved, doc_shas)
        for bad_sha in sorted(missing_doc_shas):
            failures.append(f"{PROVENANCE_INDEX_REL}: cited commit {bad_sha!r} missing in git repository")

    vdc = _load_verify_doc_commands_module()
    docs_tuple = (PROVENANCE_INDEX_REL,)
    present_docs, m_inv, t_inv, h_inv = vdc.extract_invocations(resolved, docs_tuple)
    if not present_docs or (len(m_inv) + len(t_inv) + len(h_inv)) == 0:
        failures.append(f"{PROVENANCE_INDEX_REL}: 0 verifiable CLI/make commands extracted")
    vdc_results = [
        vdc.check_makefile_targets(resolved, present_docs, m_inv),
        vdc.check_script_and_module_paths(resolved, present_docs, t_inv),
        vdc.check_cli_long_flags(resolved, t_inv, frozenset(docs_tuple)),
        vdc.check_harbor_commands(h_inv, present_docs),
    ]
    for vr in vdc_results:
        if vr.status != "PASS":
            for detail in vr.details or [vr.summary]:
                failures.append(f"verify_doc_commands [{vr.name}]: {detail}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} provenance index violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"{PROVENANCE_INDEX_REL} verified: {ledger_row_count} ledger rows, {verified_num_count} grounded numbers, "
        f"{len(checked_paths)} disk paths, M1-M10 closures, and {len(m_inv) + len(t_inv) + len(h_inv)} CLI/make commands PASS",
    )


def verify_artifact_numbers(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    git_state = _git_probe_state(resolved)
    return [
        check_companion_parity(resolved),
        check_git_provenance(resolved, _git_state=git_state),
        check_ws4_tiebreak(resolved),
        check_provenance_index(resolved, _git_state=git_state),
    ]


audit_repo = verify_artifact_numbers


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
        description="Verify JSON-to-Markdown companion parity, git SHA/tag provenance, WS4 tiebreak consistency, and the number provenance index."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to check")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_artifact_numbers(root=args.root.resolve())
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
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
