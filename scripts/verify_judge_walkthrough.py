from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_doc_commands as verify_doc_commands
from canary.redteam.anticheat import harbor_consistency

WALKTHROUGH_REL = "docs/JUDGE-WALKTHROUGH.md"
QUICKSTART_REL = "JUDGE_QUICKSTART.md"
HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

CHECK_PILLAR_1 = "Pillar 1: Frontier Gap & Rerun Claims"
CHECK_PILLAR_2 = "Pillar 2: Causal Failure Analysis & Gallery Claims"
CHECK_PILLAR_3 = "Pillar 3: Reward Integrity & Anti-Cheat Claims"
CHECK_PILLAR_4 = "Pillar 4: Craft, Hashes, Fresh-Clone Logs & Commands"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_PILLAR_1,
    CHECK_PILLAR_2,
    CHECK_PILLAR_3,
    CHECK_PILLAR_4,
)

FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
MD_LINK_RX = re.compile(r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\(([^)\n]+)\)")
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")
UNAPPROVED_FLASH_GAP_RX = re.compile(
    r"opencode[^\n]{0,40}gemini-3\.[56]-flash|gemini-3\.[56]-flash[^\n]{0,40}over\s+mcp",
    re.IGNORECASE,
)

ALWAYS_ZERO_PROBES: tuple[str, ...] = (
    "do_nothing",
    "stop_early",
    "garbage_args",
    "accuse_after_end",
    "calls_past_cap",
    "solver_cut_25",
    "solver_cut_50",
    "solver_cut_75",
)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _mean_ci(xs: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    mean_val = sum(xs) / n
    if n < 2:
        return mean_val, 0.0
    sd = math.sqrt(sum((x - mean_val) ** 2 for x in xs) / (n - 1))
    return mean_val, 1.96 * sd / math.sqrt(n)


def _pct(val: Any) -> str:
    return f"{float(val) * 100.0:.0f}%"


def _has_token(text: str, tok: str) -> bool:
    pattern = r"(?<![0-9])(?<!\d\.)" + re.escape(tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _clean_md_cell(raw: str) -> str:
    no_ticks = raw.replace("`", "")
    no_bold = no_ticks.replace("**", "").replace("*", "")
    return " ".join(no_bold.split())


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_md_cell(cell) for cell in stripped.split("|")]


def _is_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(bool(TABLE_SEP_CELL_RX.match(c.replace(" ", ""))) for c in cells)


def _parse_md_tables(md_text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
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
                if len(current) >= 2:
                    tables.append(current)
                current = []
                continue
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue

        stripped = raw_line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            cells = _split_pipe_row(stripped)
            if _is_separator_row(cells):
                continue
            current.append(cells)
        else:
            if len(current) >= 2:
                tables.append(current)
            current = []

    if len(current) >= 2:
        tables.append(current)
    return tables


def _find_table_by_header_prefix(
    tables: Sequence[list[list[str]]],
    prefix: Sequence[str],
) -> list[list[str]] | None:
    norm_prefix = [p.lower() for p in prefix]
    for tbl in tables:
        hdr = [c.lower() for c in tbl[0]]
        if len(hdr) >= len(norm_prefix) and hdr[: len(norm_prefix)] == norm_prefix:
            return tbl
    return None


def _strip_code_preserving_lines(md_text: str) -> list[str]:
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
            out.append(INLINE_CODE_RX.sub("", raw_line))
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            out.append("")
    return out


def _check_relative_links_with_targets(root: Path, doc_rel: str, md_text: str) -> tuple[int, list[str], set[str]]:
    root_norm = os.path.normpath(os.path.abspath(str(root)))
    doc_norm = os.path.normpath(os.path.join(root_norm, doc_rel))
    doc_dir = os.path.dirname(doc_norm)
    checked = 0
    broken: list[str] = []
    resolved_targets: set[str] = set()

    for lineno, line in enumerate(_strip_code_preserving_lines(md_text), 1):
        for match in MD_LINK_RX.finditer(line):
            raw = match.group(1).strip()
            if not raw:
                continue
            target = (
                raw[1 : raw.index(">")].strip()
                if (raw.startswith("<") and ">" in raw)
                else raw.split()[0].strip()
            )
            if not target:
                continue
            lower = target.lower()
            if lower.startswith(("http://", "https://", "mailto:", "tel:")) or target.startswith(HASH_CHAR):
                continue
            path_part = unquote(target.split(HASH_CHAR, 1)[0]).strip()
            if not path_part:
                continue
            checked += 1
            cand_norm = os.path.normpath(os.path.join(doc_dir, path_part))
            if os.path.commonpath([root_norm, cand_norm]) != root_norm:
                broken.append(f"{doc_rel}:{lineno}: link '{target}' escapes repository root")
                continue
            rel_path = os.path.relpath(cand_norm, root_norm).replace(os.sep, "/")
            if not os.path.exists(cand_norm):
                broken.append(f"{doc_rel}:{lineno}: link '{target}' -> missing {rel_path}")
                continue
            resolved_targets.add(rel_path)
    return checked, broken, resolved_targets


def _check_relative_links(root: Path, doc_rel: str, md_text: str) -> tuple[int, list[str]]:
    checked, broken, _ = _check_relative_links_with_targets(root, doc_rel, md_text)
    return checked, broken


def _parse_hard_meta_infra_attempts(root: Path, failures: list[str]) -> dict[str, Any] | None:
    meta_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json"
    meta_obj = _read_json(root / meta_rel, failures, meta_rel)
    if not isinstance(meta_obj, dict):
        return None
    invalid_eps = meta_obj.get("invalid_episodes")
    excluded = meta_obj.get("infra_invalid_attempts_excluded")
    if not isinstance(invalid_eps, list) or invalid_eps:
        failures.append(f"{meta_rel}: expected invalid_episodes == [], got {invalid_eps!r}")
        return None
    if not isinstance(excluded, list) or not excluded:
        failures.append(f"{meta_rel}: missing or empty infra_invalid_attempts_excluded list")
        return None

    seeds_seen: set[int] = set()
    cat_counts: dict[str, int] = {}
    for entry in excluded:
        if not isinstance(entry, str):
            failures.append(f"{meta_rel}: non-string excluded entry {entry!r}")
            return None
        m_seed = re.match(r"^opencode-hard-(\d+)-\d+:", entry)
        m_cat = re.search(r"\b(infra:[a-z0-9_]+)\b", entry)
        if m_seed is None or m_cat is None:
            failures.append(f"{meta_rel}: malformed infra_invalid_attempts_excluded entry '{entry}'")
            return None
        seeds_seen.add(int(m_seed.group(1)))
        cat = m_cat.group(1)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    expected_cats = {
        "infra:cli_error_event",
        "infra:empty_model_response",
        "infra:provider_unavailable",
    }
    if set(cat_counts.keys()) != expected_cats:
        failures.append(
            f"{meta_rel}: unexpected infra categories {sorted(cat_counts.keys())} != {sorted(expected_cats)}"
        )
        return None

    filter_test = root / "tests" / "test_integrity_valid_filter.py"
    if not filter_test.is_file():
        failures.append("missing required tamper-proof infra filter test tests/test_integrity_valid_filter.py")

    return {
        "total": len(excluded),
        "unique_seeds": len(seeds_seen),
        "cli_error_event": cat_counts["infra:cli_error_event"],
        "empty_model_response": cat_counts["infra:empty_model_response"],
        "provider_unavailable": cat_counts["infra:provider_unavailable"],
    }


def _parse_integrity_final_hunt(root: Path, failures: list[str]) -> dict[str, Any] | None:
    integ_rel = "docs/reports/integrity.md"
    integ_text = _read_text(root / integ_rel, failures, integ_rel)
    if integ_text is None:
        return None

    m_hdr = re.search(r"`afterquery-final`\s*\(([0-9a-f]{7,40})\)\s*judge-protocol\s+hunt", integ_text)
    if m_hdr is None:
        failures.append(f"{integ_rel}: missing afterquery-final judge-protocol hunt section")
        return None

    sec = integ_text[m_hdr.start() :]
    m_jh = re.search(r"judge_hunt\.py[^\n]*?\*\*(\d+)\s+of\s+(\d+)\s+held\*\*[^\n]*?\((\d+\s*s)", sec)
    m_mh = re.search(
        r"`make hunt`:[^\n]*?best non-solver score\s+\*\*([0-9.]+)\*\*\s+and\s+\*\*(\d+)\s+invariant violations\*\*[^\n]*?\((\d+\s*min\s*\d+\s*s)\)",
        sec,
    )
    m_ac = re.search(r"`make anticheat-verify`:\s*(\d+)\s+rows\s+rerun,\s*\*\*(\d+)\s+differences\*\*", sec)
    m_mt = re.search(r"`make test`:\s*([0-9,]+)\s+passed", sec)
    m_ma = re.search(r"`make accept`:\s*PASS=(\d+),\s*FAIL=(\d+)", sec)
    m_p1 = re.search(
        r"Gemini red-team phase 1[^\n]*?:\s*(\d+)\s+ledger-verified attacks on\s+([0-9a-f]{7,40}),\s*(\d+)\s+verified exploits",
        sec,
    )
    if not (m_jh and m_mh and m_ac and m_mt and m_ma and m_p1):
        failures.append(f"{integ_rel}: missing or malformed afterquery-final hunt metrics")
        return None

    jh_held = int(m_jh.group(1))
    jh_total = int(m_jh.group(2))
    jh_sec = " ".join(m_jh.group(3).split())
    mh_best = m_mh.group(1)
    mh_viol = int(m_mh.group(2))
    mh_dur = " ".join(m_mh.group(3).split())
    ac_rows = int(m_ac.group(1))
    ac_diffs = int(m_ac.group(2))
    mt_passed = m_mt.group(1)
    ma_pass = int(m_ma.group(1))
    ma_fail = int(m_ma.group(2))
    p1_attacks = int(m_p1.group(1))
    p1_sha = m_p1.group(2)
    p1_exploits = int(m_p1.group(3))

    if (
        jh_held != jh_total
        or abs(float(mh_best)) > 1e-12
        or mh_viol != 0
        or ac_diffs != 0
        or ma_pass <= 0
        or ma_fail != 0
        or p1_exploits != 0
    ):
        failures.append(
            f"{integ_rel}: final hunt invariant failed (held={jh_held}/{jh_total}, hunt={mh_best}/{mh_viol}, diffs={ac_diffs}, accept={ma_pass}/{ma_fail}, p1_exploits={p1_exploits})"
        )
        return None

    return {
        "tag_sha": m_hdr.group(1),
        "jh_held": jh_held,
        "jh_total": jh_total,
        "jh_sec": jh_sec,
        "mh_best": mh_best,
        "mh_viol": mh_viol,
        "mh_dur": mh_dur,
        "ac_rows": ac_rows,
        "ac_diffs": ac_diffs,
        "mt_passed": mt_passed,
        "ma_pass": ma_pass,
        "ma_fail": ma_fail,
        "p1_attacks": p1_attacks,
        "p1_sha": p1_sha,
        "p1_exploits": p1_exploits,
    }


def _read_json(path: Path, failures: list[str], label: str) -> Any | None:
    if not path.is_file():
        failures.append(f"missing required artifact {label} ({path})")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"failed to parse JSON {label}: {exc}")
        return None


def _read_text(path: Path, failures: list[str], label: str) -> str | None:
    if not path.is_file():
        failures.append(f"missing required artifact {label} ({path})")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"failed to read {label}: {exc}")
        return None


def _find_paired_row(
    rows: Sequence[dict[str, Any]],
    group: str,
    tier: str,
    agent: str | None = None,
    alternative: bool = False,
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("group") != group or row.get("tier") != tier:
            continue
        if agent is not None and row.get("agent") != agent:
            continue
        label_lower = str(row.get("label", "")).lower()
        is_alt = "alternative" in label_lower or "not the headline" in label_lower
        if is_alt != alternative:
            continue
        return row
    return None


def _format_pillar1_row_cells(row: dict[str, Any], solver_ci: float | None, is_solver: bool = False) -> list[str]:
    n_val = int(row["n"])
    correct_n = int(row.get("correct_count", round(float(row["accuracy"]) * n_val)))
    score_cell = f"{float(row['mean']):+.3f} +/- {float(row['ci']):.3f}"
    if is_solver:
        solver_cell = f"{float(row['solver_same_seeds']):+.3f}"
        raw_ratio_cell = "100%"
        la_ratio_cell = "100%"
    else:
        assert solver_ci is not None
        solver_cell = f"{float(row['solver_same_seeds']):+.3f} +/- {solver_ci:.3f}"
        raw_ratio_cell = f"{_pct(row['ratio'])} [{_pct(row['ratio_lo'])}, {_pct(row['ratio_hi'])}]"
        la_ratio_cell = (
            f"{_pct(row['post_expected_ratio'])} "
            f"[{_pct(row['post_expected_lo'])}, {_pct(row['post_expected_hi'])}]"
        )
    la_score_cell = f"{float(row['post_expected']):+.3f}"
    acc_cell = f"{float(row['accuracy']) * 100.0:.1f}% ({correct_n}/{n_val})"
    day_cell = f"{float(row['accuse_day']):.1f}"
    p_cell = f"{float(row['p_accused']):.2f}"
    return [
        str(n_val),
        score_cell,
        solver_cell,
        raw_ratio_cell,
        la_score_cell,
        la_ratio_cell,
        acc_cell,
        day_cell,
        p_cell,
    ]


def check_pillar1_frontier_gap(
    root: Path = ROOT,
    doc_text: str | None = None,
) -> CheckResult:
    name = CHECK_PILLAR_1
    failures: list[str] = []
    explicit_doc = doc_text is not None
    if doc_text is None:
        doc_text = _read_text(root / WALKTHROUGH_REL, failures, WALKTHROUGH_REL)
        if doc_text is None:
            return CheckResult(name, "FAIL", f"missing {WALKTHROUGH_REL}", failures)

    tables = _parse_md_tables(doc_text)
    p1_tbl = _find_table_by_header_prefix(tables, ("tier", "agent & harness", "n"))
    if p1_tbl is None:
        failures.append("missing Section 2 Pillar 1A paired results table in docs/JUDGE-WALKTHROUGH.md")

    paired_path = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
    paired_rows = _read_json(paired_path, failures, "data/runs/committed/v1.4/paired_table_gemini.json")
    gap_frontier_tokens: list[str] = []

    if isinstance(paired_rows, list):
        oc_hard = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard")
        oc_hard_alt = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard", alternative=True)
        ip_hard = _find_paired_row(paired_rows, "v1.4/inproc-gemini-4-carbon", "hard")
        sv_hard = _find_paired_row(paired_rows, "v1.4/reference", "hard", agent="solver")
        oc_med = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "medium")
        ip_med = _find_paired_row(paired_rows, "v1.4/inproc-gemini-4-carbon", "medium")
        sv_med = _find_paired_row(paired_rows, "v1.4/reference", "medium", agent="solver")
        dn_hard = _find_paired_row(paired_rows, "v1.4/reference", "hard", agent="do_nothing")

        required_rows = {
            "opencode_hard": oc_hard,
            "opencode_hard_alt": oc_hard_alt,
            "inproc_hard": ip_hard,
            "solver_hard": sv_hard,
            "opencode_medium": oc_med,
            "inproc_medium": ip_med,
            "solver_medium": sv_med,
            "do_nothing_hard": dn_hard,
        }
        missing_keys = [k for k, v in required_rows.items() if v is None]
        if missing_keys:
            failures.append(f"paired_table_gemini.json missing expected row(s): {missing_keys}")
        else:
            assert oc_hard is not None and oc_hard_alt is not None and ip_hard is not None
            assert sv_hard is not None and oc_med is not None and ip_med is not None
            assert sv_med is not None and dn_hard is not None

            sv_hard_ci = float(sv_hard["ci"])
            sv_med_ci = float(sv_med["ci"])
            expected_five = [
                ("hard", "gemini-4-carbon", _format_pillar1_row_cells(oc_hard, sv_hard_ci)),
                ("hard", "in-process", _format_pillar1_row_cells(ip_hard, sv_hard_ci)),
                ("hard", "reference solver", _format_pillar1_row_cells(sv_hard, None, is_solver=True)),
                ("medium", "opencode", _format_pillar1_row_cells(oc_med, sv_med_ci)),
                ("medium", "in-process", _format_pillar1_row_cells(ip_med, sv_med_ci)),
            ]
            if p1_tbl is not None:
                data_rows = p1_tbl[1:]
                if len(data_rows) != 5:
                    failures.append(f"Pillar 1A table expected 5 rows, found {len(data_rows)}")
                else:
                    for idx, (exp_tier, agent_sub, exp_cells) in enumerate(expected_five, 1):
                        got_row = data_rows[idx - 1]
                        if len(got_row) != 11:
                            failures.append(f"Pillar 1A row {idx} expected 11 columns, got {len(got_row)}")
                            continue
                        if got_row[0].lower() != exp_tier:
                            failures.append(
                                f"Pillar 1A row {idx} tier mismatch: doc='{got_row[0]}' vs expected='{exp_tier}'"
                            )
                        if agent_sub not in got_row[1].lower():
                            failures.append(
                                f"Pillar 1A row {idx} agent label '{got_row[1]}' missing '{agent_sub}'"
                            )
                        if got_row[2:] != exp_cells:
                            failures.append(
                                f"Pillar 1A row {idx} ({got_row[1]}) mismatch: doc={got_row[2:]} vs artifact={exp_cells}"
                            )

            headline_tokens = [
                f"{float(oc_hard['diff']):+.3f} +/- {float(oc_hard['diff_ci']):.3f}",
                f"{float(oc_hard_alt['mean']):+.3f} +/- {float(oc_hard_alt['ci']):.3f}",
                f"{_pct(oc_hard_alt['ratio'])} [{_pct(oc_hard_alt['ratio_lo'])}, {_pct(oc_hard_alt['ratio_hi'])}]",
                (
                    f"{_pct(oc_hard_alt['post_expected_ratio'])} "
                    f"[{_pct(oc_hard_alt['post_expected_lo'])}, {_pct(oc_hard_alt['post_expected_hi'])}]"
                ),
            ]
            for tok in headline_tokens:
                if not _has_token(doc_text, tok):
                    failures.append(f"docs/JUDGE-WALKTHROUGH.md missing paired_table_gemini token '{tok}'")

            if float(dn_hard["mean"]) != 0.0:
                failures.append(f"paired_table_gemini do_nothing hard mean={dn_hard['mean']} (expected 0.0)")

            raw_hl = f"{_pct(oc_hard['ratio'])} [{_pct(oc_hard['ratio_lo'])}, {_pct(oc_hard['ratio_hi'])}]"
            la_hl = (
                f"{_pct(oc_hard['post_expected_ratio'])} "
                f"[{_pct(oc_hard['post_expected_lo'])}, {_pct(oc_hard['post_expected_hi'])}]"
            )
            clean_wt_p1 = doc_text.replace("`", "").replace("**", "")
            raw_idx = clean_wt_p1.find(raw_hl)
            la_idx = clean_wt_p1.find(la_hl)
            if raw_idx == -1 or la_idx == -1 or raw_idx > la_idx:
                failures.append(
                    f"docs/JUDGE-WALKTHROUGH.md must lead with raw '{raw_hl}' before luck-adjusted '{la_hl}'"
                )
            for prov_tok in (
                "671ed96",
                "8fd4dec",
                "28 s",
                "solver-hard-20261114-121126/",
                "solver-hard-seeds20to29/",
                "1bc3e281",
                "afterquery-final",
                "cf394894",
            ):
                if prov_tok not in clean_wt_p1:
                    failures.append(f"docs/JUDGE-WALKTHROUGH.md missing Pillar 1 provenance token '{prov_tok}'")

            for f_row in (oc_hard, oc_med, ip_hard, ip_med):
                gap_frontier_tokens.append(
                    f"{_pct(f_row['ratio'])} [{_pct(f_row['ratio_lo'])}, {_pct(f_row['ratio_hi'])}]"
                )
                gap_frontier_tokens.append(
                    f"{_pct(f_row['post_expected_ratio'])} "
                    f"[{_pct(f_row['post_expected_lo'])}, {_pct(f_row['post_expected_hi'])}]"
                )

    infra_info = _parse_hard_meta_infra_attempts(root, failures)
    if infra_info is not None:
        clean_wt_infra = doc_text.replace("`", "").replace("**", "")
        infra_tokens = (
            f"{infra_info['total']} excluded infra-invalid attempts",
            f"{infra_info['unique_seeds']} unique seeds",
            f"{infra_info['cli_error_event']} infra:cli_error_event",
            f"{infra_info['empty_model_response']} infra:empty_model_response",
            f"{infra_info['provider_unavailable']} infra:provider_unavailable",
            "test_integrity_valid_filter.py",
        )
        for tok in infra_tokens:
            if not _has_token(clean_wt_infra, tok):
                failures.append(f"hard/meta.json infra claim '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")
        if not explicit_doc and (root / QUICKSTART_REL).is_file():
            qs_p1 = _read_text(root / QUICKSTART_REL, failures, QUICKSTART_REL)
            if qs_p1 is not None:
                clean_qs_p1 = qs_p1.replace("`", "").replace("**", "")
                for tok in infra_tokens:
                    if not _has_token(clean_qs_p1, tok):
                        failures.append(f"hard/meta.json infra claim '{tok}' missing from JUDGE_QUICKSTART.md")

    oracle_obj = _read_json(root / "results" / "oracle_range_v1.4.json", failures, "results/oracle_range_v1.4.json")
    if isinstance(oracle_obj, dict) and isinstance(oracle_obj.get("rows"), list):
        o_rows = oracle_obj["rows"]
        sv_or = next((r for r in o_rows if r.get("agent") == "solver" and r.get("tier") == "hard"), None)
        if sv_or is None:
            failures.append("oracle_range_v1.4.json missing solver hard row")
        else:
            k10 = sv_or["k10"]
            k2 = sv_or["k2"]
            oracle_tokens = [
                str(int(sv_or["builds"])),
                f"{float(k10['mean']):+.3f}",
                f"{float(k10['sd']):.3f}",
                f"{float(k10['p50']):+.3f}",
                f"{float(k10['p5']):+.2f}",
                f"{float(k10['p95']):+.2f}",
                f"p5 = {float(k10['p5']):+.3f}",
                f"p95 = {float(k10['p95']):+.3f}",
                f"P(mean < 0) = {float(k10['p_lt0']) * 100.0:.1f}%",
                f"P(mean < 0) = {float(k2['p_lt0']) * 100.0:.1f}%",
            ]
            for tok in oracle_tokens:
                if not _has_token(doc_text, tok):
                    failures.append(f"oracle_range_v1.4 mismatch: token '{tok}' not in docs/JUDGE-WALKTHROUGH.md")
        for zero_agent in ("do_nothing", "stop_early"):
            zr = next((r for r in o_rows if r.get("agent") == zero_agent and r.get("tier") == "hard"), None)
            if zr is None or float(zr["k10"]["mean"]) != 0.0:
                failures.append(f"oracle_range_v1.4.json {zero_agent} hard k10.mean is not 0.0")

    gd1_obj = _read_json(
        root / "results" / "solver_range" / "guess_day1_hard_judge40.json",
        failures,
        "results/solver_range/guess_day1_hard_judge40.json",
    )
    if isinstance(gd1_obj, dict):
        p_map = gd1_obj.get("p") or {}
        b_means = [float(x) for x in (gd1_obj.get("build_means") or [])]
        seeds_span = gd1_obj.get("seeds") or []
        if gd1_obj.get("agent") != "guess_day1" or gd1_obj.get("tier") != "hard":
            failures.append("guess_day1_hard_judge40.json unexpected agent/tier metadata")
        elif len(seeds_span) != 2 or int(seeds_span[1]) - int(seeds_span[0]) + 1 != 40 or not b_means:
            failures.append("guess_day1_hard_judge40.json invalid 40-seed build_means structure")
        else:
            med = float(p_map.get("0.5", float("nan")))
            calc_med = float(statistics.median(b_means))
            overall_mean = float(gd1_obj.get("mean", float("nan")))
            n_tasks = int(seeds_span[1]) - int(seeds_span[0]) + 1
            n_wins = round((med + 1.0) * n_tasks / 2.0)
            rep_scores = [1.0] * n_wins + [-1.0] * (n_tasks - n_wins)
            rep_mean, rep_ci = _mean_ci(rep_scores)
            gd1_token = f"{rep_mean:+.3f} +/- {rep_ci:.3f}"
            if abs(med - calc_med) > 1e-9 or abs(overall_mean - med) > 0.01:
                failures.append(
                    f"guess_day1_hard_judge40.json inconsistent median/mean (p50={med}, calc={calc_med}, mean={overall_mean})"
                )
            if not _has_token(doc_text, gd1_token):
                failures.append(
                    f"guess_day1_hard_judge40 mismatch: artifact implies '{gd1_token}', not found in docs/JUDGE-WALKTHROUGH.md"
                )

    reh_text = _read_text(
        root / "results" / "harbor" / "rehearsal-dry" / "TABLE.md",
        failures,
        "results/harbor/rehearsal-dry/TABLE.md",
    )
    if reh_text is not None:
        reh_tables = _parse_md_tables(reh_text)
        if len(reh_tables) < 2:
            failures.append("results/harbor/rehearsal-dry/TABLE.md expected 2 markdown tables")
        else:
            mean_row = next((r for r in reh_tables[0][1:] if "mean" in r[0].lower()), None)
            oc_reh = next((r for r in reh_tables[1][1:] if r[0].lower() == "opencode"), None)
            dn_reh = next((r for r in reh_tables[1][1:] if r[0].lower() == "do_nothing"), None)
            se_reh = next((r for r in reh_tables[1][1:] if r[0].lower() == "stop_early"), None)
            if mean_row is None or oc_reh is None or dn_reh is None or se_reh is None:
                failures.append("rehearsal-dry/TABLE.md missing mean/opencode/do_nothing/stop_early rows")
            else:
                oracle_m, oc_m, dn_m, se_m = mean_row[1], mean_row[2], mean_row[3], mean_row[4]
                ratio_reh = oc_reh[6]
                if oc_reh[4] != oc_m or oc_reh[5] != oracle_m:
                    failures.append("rehearsal-dry/TABLE.md internal mismatch between task table and summary table")
                if float(dn_m) != 0.0 or float(se_m) != 0.0 or float(dn_reh[4]) != 0.0 or float(se_reh[4]) != 0.0:
                    failures.append("rehearsal-dry/TABLE.md do_nothing/stop_early mean is not 0.000")
                for tok in (f"oracle {oracle_m}", oc_m, ratio_reh, "0.000"):
                    if not _has_token(doc_text, tok):
                        failures.append(
                            f"rehearsal-dry/TABLE.md token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md"
                        )

    gap_text = _read_text(root / "docs" / "reports" / "gap.md", failures, "docs/reports/gap.md")
    if gap_text is not None:
        clean_gap = gap_text.replace("`", "").replace("**", "")
        for tok in gap_frontier_tokens:
            if not _has_token(clean_gap, tok):
                failures.append(f"docs/reports/gap.md missing paired_table_gemini token '{tok}'")
        if "gemini-3.5-flash" not in gap_text.lower():
            clean_wt = doc_text.replace("`", "").replace("**", "")
            if UNAPPROVED_FLASH_GAP_RX.search(clean_wt):
                failures.append(
                    "docs/JUDGE-WALKTHROUGH.md cites OpenCode gemini-3.5-flash gap claim not present in docs/reports/gap.md"
                )
        m_v15 = re.search(r"v1\.5\s+biased\s+employees[^\n]*?to\s+(\d+%)\s+of\s+the\s+solver", gap_text, re.I)
        m_sv2 = re.search(
            r"solver_v2[^\n]*?([+-]\d+\.\d+)\s*(?:\+/-|\u00b1)\s*(\d+\.\d+)[^\n]*?\(n=(\d+)\)",
            gap_text,
            re.I,
        )
        m_exp = re.search(
            r"expert[^\n]*?(\d+%\s*\[\d+%,\s*\d+%\])\s+luck-adjusted\s*\(n=(\d+)",
            gap_text,
            re.I,
        )
        if not (m_v15 and m_sv2 and m_exp):
            failures.append("docs/reports/gap.md missing one or more negative ablation claims (v1.5, solver_v2, expert)")
        else:
            ablation_tokens = [
                m_v15.group(1),
                f"{m_sv2.group(1)} +/- {m_sv2.group(2)}",
                f"n={m_sv2.group(3)}",
                m_exp.group(1),
                f"n={m_exp.group(2)}",
            ]
            for tok in ablation_tokens:
                if not _has_token(doc_text, tok):
                    failures.append(
                        f"gap.md negative ablation token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md"
                    )

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} Pillar 1 claim mismatch(es)", failures)
    return CheckResult(
        name,
        "PASS",
        "verified all 5 paired v1.4 rows, 25 hard/meta.json infra attempts, gap.md alignment, oracle range, guess_day1, rehearsal-dry, and negative ablations",
    )


def check_pillar2_failure_and_fairness(
    root: Path = ROOT,
    doc_text: str | None = None,
    _fa_obj: dict[str, Any] | None = None,
) -> CheckResult:
    name = CHECK_PILLAR_2
    failures: list[str] = []
    if doc_text is None:
        doc_text = _read_text(root / WALKTHROUGH_REL, failures, WALKTHROUGH_REL)
        if doc_text is None:
            return CheckResult(name, "FAIL", f"missing {WALKTHROUGH_REL}", failures)

    tables = _parse_md_tables(doc_text)
    fa_obj = (
        _fa_obj
        if _fa_obj is not None
        else _read_json(
            root / "results" / "failure_analysis_v1.4.json",
            failures,
            "results/failure_analysis_v1.4.json",
        )
    )
    if isinstance(fa_obj, dict):
        summary = fa_obj.get("summary") or {}
        gap = summary.get("gap") or {}
        oc = summary.get("opencode") or {}
        sv = summary.get("solver") or {}
        ip = summary.get("inproc") or {}
        wd = summary.get("wrong_detail") or []

        req_gap_keys = ("penalty", "abstain", "leak", "restrict", "canary", "la_gap", "luck", "raw_gap")
        if any(k not in gap for k in req_gap_keys) or not oc or not sv:
            failures.append("results/failure_analysis_v1.4.json missing required summary.gap/opencode/solver keys")
        else:
            sum_skill = (
                float(gap["penalty"])
                + float(gap["abstain"])
                + float(gap["leak"])
                + float(gap["restrict"])
                + float(gap["canary"])
            )
            la_gap = float(gap["la_gap"])
            luck_val = float(gap["luck"])
            raw_gap = float(gap["raw_gap"])
            if abs(sum_skill - la_gap) > 1e-6:
                failures.append(f"failure_analysis_v1.4.json rows 1-5 sum={sum_skill:.6f} != la_gap={la_gap:.6f}")
            if abs((la_gap + luck_val) - raw_gap) > 1e-6:
                failures.append(
                    f"failure_analysis_v1.4.json la_gap+luck={la_gap + luck_val:.6f} != raw_gap={raw_gap:.6f}"
                )

            n_seeds = int(oc.get("n", 30))
            decomp_tbl = _find_table_by_header_prefix(tables, ("component", "v lost (30 seeds)", "per episode"))
            if decomp_tbl is None:
                failures.append("missing Section 2 Pillar 2A additive V decomposition table in docs/JUDGE-WALKTHROUGH.md")
            else:
                rows_p2a = decomp_tbl[1:]
                if len(rows_p2a) != 8:
                    failures.append(f"Pillar 2A decomposition table expected 8 rows, found {len(rows_p2a)}")
                else:
                    for idx, key in enumerate(req_gap_keys):
                        val = float(gap[key])
                        exp_v = f"{val:+.2f} V"
                        exp_ep = f"{val / n_seeds:+.3f}"
                        got_v = rows_p2a[idx][1]
                        got_ep = rows_p2a[idx][2]
                        if got_v != exp_v or got_ep != exp_ep:
                            failures.append(
                                f"Pillar 2A row {idx + 1} ({key}) mismatch: doc=({got_v}, {got_ep}) vs json=({exp_v}, {exp_ep})"
                            )

            expected_p2_tokens = [
                f"{abs(raw_gap):.2f} V",
                f"{int(round(float(oc['interviews'])))} interviews/episode",
                f"{float(oc['canaries']):.1f} vs {float(sv['canaries']):.1f}",
                f"{_pct(oc['capacity_used'])} vs {_pct(sv['capacity_used'])}",
                f"{_pct(oc['days_with_canary_share'])} vs {_pct(sv['days_with_canary_share'])}",
                f"{len(oc.get('not_isolated', []))}/{int(oc['accused'])}",
                f"{len(sv.get('not_isolated', []))}/{int(sv['accused'])}",
                f"{float(gap['penalty_not_isolated']):+.2f} V",
                f"{abs(float(gap['penalty_ev_negative'])):.2f} V",
                ", ".join(str(s) for s in oc.get("ev_negative", [])),
                f"{int(round(float(sv['calls'])))} calls/ep",
                f"{int(round(float(ip['interviews'])))} interviews/ep",
            ]
            clean_doc = doc_text.replace("`", "").replace("**", "")
            for tok in expected_p2_tokens:
                if not _has_token(clean_doc, tok):
                    failures.append(f"failure_analysis_v1.4 token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")

            wrong_tbl = _find_table_by_header_prefix(tables, ("seed", "day", "accused (true mole)"))
            if wrong_tbl is None:
                failures.append("missing Section 2 Pillar 2B wrong accusations table in docs/JUDGE-WALKTHROUGH.md")
            elif len(wd) != 4 or [int(w["seed"]) for w in wd] != [1, 15, 18, 26]:
                failures.append(
                    f"failure_analysis_v1.4.json wrong_detail seeds={[w.get('seed') for w in wd]} != [1, 15, 18, 26]"
                )
            elif len(wrong_tbl[1:]) != len(wd):
                failures.append(
                    f"Pillar 2B wrong-accusations table row count {len(wrong_tbl[1:])} != {len(wd)}"
                )
            else:
                for idx, w in enumerate(wd):
                    got = wrong_tbl[idx + 1]
                    exp_prefix = [
                        str(int(w["seed"])),
                        str(int(w["day"])),
                        f"{w['accused']} ({w['mole']})",
                        f"{float(w['p']):.2f}",
                        f"{float(w['ev']):+.2f}",
                        "{" + ", ".join(str(x) for x in w["consistent"]) + "}",
                        "Yes" if bool(w["flip"]) else "No",
                        f"{float(w['solver_score']):+.2f}",
                    ]
                    if got[:8] != exp_prefix:
                        failures.append(
                            f"Pillar 2B wrong-accusation seed {w['seed']} mismatch: doc={got[:8]} vs json={exp_prefix}"
                        )

    fg_text = _read_text(
        root / "docs" / "reports" / "failure_gallery.md",
        failures,
        "docs/reports/failure_gallery.md",
    )
    if fg_text is not None:
        m_ep = re.search(r"\*\*(\d+)\s+episodes\s+decomposed\*\*", fg_text)
        m_unexp = re.search(r"Unexplained:\s*([0-9.]+e[+-]\d+)", fg_text)
        m_res = re.search(r"largest\s+per-episode\s+residual\s+([0-9.]+e[+-]\d+)", fg_text)
        m_quotes = re.search(r"Quotes:\s*(\d+/\d+)\s+verbatim", fg_text)
        if not (m_ep and m_unexp and m_res and m_quotes):
            failures.append("docs/reports/failure_gallery.md missing episode count, residual, or quote count")
        else:
            ep_count = int(m_ep.group(1))
            unexp_tok = m_unexp.group(1)
            res_tok = m_res.group(1)
            quotes_tok = m_quotes.group(1)
            fg_tables = _parse_md_tables(fg_text)
            if fg_tables:
                hdr_nums = [
                    int(m.group(1))
                    for cell in fg_tables[0][0]
                    for m in [re.search(r"\((\d+)\s+eps", cell)]
                    if m is not None
                ]
                if hdr_nums and sum(hdr_nums) != ep_count:
                    failures.append(
                        f"failure_gallery.md per-version episode sum {sum(hdr_nums)} != {ep_count}"
                    )
            clean_doc = doc_text.replace("`", "").replace("**", "")
            for tok in (f"{ep_count} paired episodes", unexp_tok, res_tok, quotes_tok):
                if not _has_token(clean_doc, tok):
                    failures.append(f"failure_gallery.md token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} Pillar 2 claim mismatch(es)", failures)
    return CheckResult(
        name,
        "PASS",
        "verified 5.30 V additive decomposition, rates, wrong-accusation seeds [1, 15, 18, 26], and 295-episode gallery",
    )


def check_pillar3_reward_integrity(root: Path = ROOT, doc_text: str | None = None) -> CheckResult:
    name = CHECK_PILLAR_3
    failures: list[str] = []
    explicit_doc = doc_text is not None
    if doc_text is None:
        doc_text = _read_text(root / WALKTHROUGH_REL, failures, WALKTHROUGH_REL)
        if doc_text is None:
            return CheckResult(name, "FAIL", f"missing {WALKTHROUGH_REL}", failures)

    clean_doc = doc_text.replace("`", "").replace("**", "")

    ex_obj = _read_json(
        root / "results" / "anticheat" / "exploits.json",
        failures,
        "results/anticheat/exploits.json",
    )
    if isinstance(ex_obj, dict):
        rows = ex_obj.get("rows") or []
        tiers = ex_obj.get("tiers") or []
        n_rows = len(rows)
        n_tiers = len(tiers)
        n_seeds_set = {int(r.get("n", -1)) for r in rows if isinstance(r, dict)}
        if ex_obj.get("all_blocked") is not True:
            failures.append("results/anticheat/exploits.json all_blocked is not True")
        if len(n_seeds_set) != 1:
            failures.append(f"exploits.json inconsistent seed counts across rows: {sorted(n_seeds_set)}")
        else:
            seeds_per_row = next(iter(n_seeds_set))
            total_runs = n_rows * seeds_per_row
            probes_per_tier = n_rows // max(1, n_tiers)
            for tok in (
                f"{n_rows} rows",
                f"{probes_per_tier} probes x {n_tiers} tiers",
                f"{seeds_per_row} judge seeds",
                f"{total_runs:,} runs",
            ):
                if not _has_token(clean_doc, tok):
                    failures.append(f"exploits.json claim '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")
        for r in rows:
            probe = str(r.get("probe", ""))
            if probe in ALWAYS_ZERO_PROBES:
                if abs(float(r.get("mean", 1.0))) > 1e-12 or abs(float(r.get("max", 1.0))) > 1e-12:
                    failures.append(f"exploits.json always-zero probe {probe} ({r.get('tier')}) is non-zero")

        rc = ex_obj.get("replay_counts") or {}
        if rc:
            rep_tok = f"{int(rc.get('replayed', -1))}/{int(rc.get('n', -1))}"
            steps_tok = f"{int(rc.get('steps', -1)):,}"
            diff_mismatch = int(rc.get("step_mismatches", -1))
            if diff_mismatch != 0 or not _has_token(clean_doc, rep_tok) or not _has_token(clean_doc, steps_tok):
                failures.append(
                    f"exploits.json replay_counts ({rep_tok}, {steps_tok} steps, {diff_mismatch} mismatches) mismatch with walkthrough"
                )

    harbor_dir = root / "results" / "harbor"
    if not harbor_dir.is_dir():
        failures.append("missing results/harbor directory")
    else:
        iso_files = sorted(harbor_dir.rglob("isolation.txt"))
        iso_ok = 0
        for iso_f in iso_files:
            try:
                txt = iso_f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "ISOLATION OK: 11 checks passed, 0 findings" in txt:
                iso_ok += 1
        iso_ratio = f"{iso_ok}/{len(iso_files)}"
        if len(iso_files) == 0 or iso_ok != len(iso_files):
            failures.append(f"Harbor isolation.txt check failed ({iso_ratio} passed)")
        elif not _has_token(clean_doc, iso_ratio):
            failures.append(
                f"Harbor isolation.txt count '{iso_ratio}' does not match docs/JUDGE-WALKTHROUGH.md"
            )

        hb_rows = harbor_consistency(root)
        hb_trials = [r for r in hb_rows if r.get("kind", "trial") == "trial"]
        hb_jobs = [r for r in hb_rows if r.get("kind") == "job"]
        hb_bad = [r for r in hb_rows if r.get("consistent") is False]
        ok_trials = sum(1 for r in hb_trials if r.get("consistent") is True)
        ok_jobs = sum(1 for r in hb_jobs if r.get("consistent") is True)
        if hb_bad:
            failures.append(
                f"harbor_consistency found {len(hb_bad)} inconsistent item(s): {[r.get('trial') for r in hb_bad[:3]]}"
            )
        trials_tok = f"{ok_trials}/{len(hb_trials)} Harbor trials"
        jobs_tok = f"{ok_jobs}/{len(hb_jobs)} jobs"
        if not _has_token(clean_doc, trials_tok) or not _has_token(clean_doc, jobs_tok):
            failures.append(
                f"harbor_consistency ({trials_tok}, {jobs_tok}) does not match docs/JUDGE-WALKTHROUGH.md"
            )

    sw_json = _read_json(root / "results" / "gemini" / "swarm.json", failures, "results/gemini/swarm.json")
    sw_md = _read_text(root / "results" / "gemini" / "swarm.md", failures, "results/gemini/swarm.md")
    if isinstance(sw_json, dict) and sw_md is not None:
        waves = sw_json.get("waves") or []
        counts = sw_json.get("counts") or {}
        attempts = sw_json.get("attempts") or []
        pos_ctrl = sw_json.get("positive_control") or {}

        finished_all = sum(int(w.get("finished", 0)) for w in waves)
        whitebox_fin = sum(int(w.get("finished", 0)) for w in waves if w.get("mode") == "whitebox")
        blackbox_fin = sum(int(w.get("finished", 0)) for w in waves if w.get("mode") == "blackbox")
        mcp_reruns = sum(int(w.get("mcp_reruns", 0)) for w in waves)
        total_attempts = int(counts.get("attempts", -1))
        tool_calls = int(counts.get("tool_calls", -1))
        calc_calls = sum(int(a.get("n_tool_calls", 0)) for a in attempts)
        exploits_n = int(counts.get("exploits", -1))
        calc_exploits = sum(1 for a in attempts if bool(a.get("exploit")))
        violations_n = int(counts.get("invariant_violations", -1))

        if tool_calls != calc_calls or exploits_n != calc_exploits or len(attempts) != total_attempts:
            failures.append(
                f"swarm.json internal mismatch: counts=({total_attempts}, {tool_calls}, {exploits_n}) vs attempts=({len(attempts)}, {calc_calls}, {calc_exploits})"
            )
        if exploits_n != 0 or violations_n != 0:
            failures.append(f"swarm.json reports exploits={exploits_n}, invariant_violations={violations_n}")

        sw_tables = _parse_md_tables(sw_md)
        wave_tbl = _find_table_by_header_prefix(sw_tables, ("wave", "run"))
        all_waves_row = (
            next((r for r in wave_tbl[1:] if "all real waves" in r[0].lower()), None)
            if wave_tbl is not None
            else None
        )
        if all_waves_row is None:
            failures.append("results/gemini/swarm.md missing 'all real waves' summary row")
        else:
            if (
                int(all_waves_row[4]) != finished_all
                or int(all_waves_row[6]) != mcp_reruns
                or int(all_waves_row[7]) != tool_calls
                or int(all_waves_row[11]) != exploits_n
            ):
                failures.append("swarm.md 'all real waves' row disagrees with swarm.json")

        ctrl_found = int(pos_ctrl.get("verified_exploits", -1))
        ctrl_att = int(pos_ctrl.get("attackers_found", -1))
        ctrl_ep1 = int(pos_ctrl.get("episodes_at_1", -1))
        ctrl_eps = int(pos_ctrl.get("episodes", -1))
        swarm_tokens = [
            f"{finished_all}-attacker Gemini swarm",
            f"{whitebox_fin} whitebox attackers",
            f"{blackbox_fin} blackbox attackers",
            f"{mcp_reruns} MCP re-runs = {total_attempts} attempts",
            f"{tool_calls:,} tool calls",
            f"{exploits_n} verified exploits",
            f"{violations_n} invariant violations",
            f"{ctrl_found}/{ctrl_att}",
            f"{ctrl_ep1}/{ctrl_eps}",
        ]
        for tok in swarm_tokens:
            if not _has_token(clean_doc, tok):
                failures.append(f"swarm claim '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")

    corpus_text = _read_text(
        root / "results" / "anticheat" / "corpus_eval.txt",
        failures,
        "results/anticheat/corpus_eval.txt",
    )
    if corpus_text is not None:
        m_json = re.search(r"\{[\s\S]*?\}", corpus_text)
        m_foot = re.search(r"runs=(\d+)\s+changed=(\d+)\s+accepted=(\d+)", corpus_text)
        if m_json is None or m_foot is None:
            failures.append("results/anticheat/corpus_eval.txt missing JSON block or summary footer")
        else:
            try:
                c_obj = json.loads(m_json.group(0))
            except ValueError as exc:
                failures.append(f"corpus_eval.txt invalid JSON block: {exc}")
                c_obj = None
            if isinstance(c_obj, dict):
                c_rows = int(c_obj.get("rows", -1))
                c_runs = int(c_obj.get("runs", -1))
                c_acc = len(c_obj.get("accepted") or [])
                c_chg = len(c_obj.get("changed") or [])
                if (
                    int(m_foot.group(1)) != c_runs
                    or int(m_foot.group(2)) != c_chg
                    or int(m_foot.group(3)) != c_acc
                    or c_acc != 0
                    or c_chg != 0
                ):
                    failures.append(f"corpus_eval.txt inconsistent or non-zero accepted/changed ({c_obj})")
                for tok in (f"{c_rows}-row Sleeper cheat corpus", f"{c_runs:,} runs", "0 calls accepted"):
                    if not _has_token(clean_doc, tok):
                        failures.append(f"corpus_eval.txt token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")

    jh_text = _read_text(
        root / "results" / "anticheat" / "judge_hunt.md",
        failures,
        "results/anticheat/judge_hunt.md",
    )
    if jh_text is not None:
        jh_tables = _parse_md_tables(jh_text)
        hunt_tbl = _find_table_by_header_prefix(jh_tables, ("attack", "how"))
        m_held = re.search(r"\*\*(\d+)\s+of\s+(\d+)\s+held\*\*", jh_text)
        if hunt_tbl is None or m_held is None:
            failures.append("results/anticheat/judge_hunt.md missing attack table or 'N of N held' verdict")
        else:
            j_rows = hunt_tbl[1:]
            held_yes = sum(1 for r in j_rows if len(r) >= 4 and r[3].lower() == "yes")
            if int(m_held.group(1)) != held_yes or int(m_held.group(2)) != len(j_rows) or held_yes != len(j_rows):
                failures.append(
                    f"judge_hunt.md held mismatch: table={held_yes}/{len(j_rows)} vs footer={m_held.group(0)}"
                )
            hunt_tok = f"{held_yes}/{len(j_rows)} wire attacks held"
            if not _has_token(clean_doc, hunt_tok):
                failures.append(f"judge_hunt.md token '{hunt_tok}' missing from docs/JUDGE-WALKTHROUGH.md")

    integ_info = _parse_integrity_final_hunt(root, failures)
    if integ_info is not None:
        if isinstance(ex_obj, dict) and isinstance(ex_obj.get("rows"), list):
            if integ_info["ac_rows"] != len(ex_obj["rows"]):
                failures.append(
                    f"integrity.md anticheat rows={integ_info['ac_rows']} != exploits.json rows={len(ex_obj['rows'])}"
                )
        integ_tokens = (
            "58716742",
            integ_info["tag_sha"],
            f"{integ_info['jh_held']}/{integ_info['jh_total']}",
            f"held in {integ_info['jh_sec']}",
            integ_info["mh_best"],
            f"{integ_info['mh_viol']} invariant violations",
            integ_info["mh_dur"],
            f"{integ_info['ac_rows']} rows",
            f"{integ_info['ac_diffs']} differences",
            f"{integ_info['mt_passed']} passed",
            f"PASS={integ_info['ma_pass']}",
            f"FAIL={integ_info['ma_fail']}",
            f"{integ_info['p1_attacks']} ledger-verified attacks",
            integ_info["p1_sha"],
        )
        for tok in integ_tokens:
            if not _has_token(clean_doc, tok):
                failures.append(f"integrity.md final hunt token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md")
        if not explicit_doc and (root / QUICKSTART_REL).is_file():
            qs_p3 = _read_text(root / QUICKSTART_REL, failures, QUICKSTART_REL)
            if qs_p3 is not None:
                clean_qs_p3 = qs_p3.replace("`", "").replace("**", "")
                for tok in integ_tokens:
                    if not _has_token(clean_qs_p3, tok):
                        failures.append(f"integrity.md final hunt token '{tok}' missing from JUDGE_QUICKSTART.md")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} Pillar 3 claim mismatch(es)", failures)
    return CheckResult(
        name,
        "PASS",
        "verified 99x40 exploits.json, 61/61 isolation.txt, 80/80 Harbor trials (18/18 jobs), 91-attacker swarm, 1,161 corpus runs, 12/12 judge_hunt, and 58716742 integrity.md hunt",
    )


def _load_rules_module(root: Path) -> Any:
    cand = root / "canary" / "rules.py"
    default_rules = ROOT / "canary" / "rules.py"
    if cand.is_file():
        try:
            same = cand.resolve() == default_rules.resolve()
        except OSError:
            same = False
        if not same:
            mod_name = f"_walkthrough_rules_{abs(hash(str(cand)))}"
            spec = importlib.util.spec_from_file_location(mod_name, cand)
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                try:
                    spec.loader.exec_module(mod)
                finally:
                    sys.modules.pop(mod_name, None)
                return mod
    from canary import rules as default_mod

    return default_mod


def _compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]


def check_pillar4_craft_and_commands(root: Path = ROOT, doc_text: str | None = None) -> CheckResult:
    name = CHECK_PILLAR_4
    failures: list[str] = []
    explicit_doc = doc_text is not None
    if doc_text is None:
        doc_text = _read_text(root / WALKTHROUGH_REL, failures, WALKTHROUGH_REL)
        if doc_text is None:
            return CheckResult(name, "FAIL", f"missing {WALKTHROUGH_REL}", failures)

    if EM_DASH in doc_text or EN_DASH in doc_text:
        failures.append("docs/JUDGE-WALKTHROUGH.md contains em or en dash characters")

    _, broken_links, wt_targets = _check_relative_links_with_targets(root, WALKTHROUGH_REL, doc_text)
    failures.extend(broken_links)

    required_wt_links = (
        "JUDGE_QUICKSTART.md",
        "docs/PEER-REVIEW-QA.md",
        "docs/REPRODUCIBILITY.md",
        "docs/reports/integrity.md",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json",
        "tests/test_integrity_valid_filter.py",
        "results/fresh_clone/README.md",
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt",
    )
    for req_link in required_wt_links:
        if req_link not in wt_targets:
            failures.append(f"docs/JUDGE-WALKTHROUGH.md missing required relative link to '{req_link}'")

    try:
        rules_mod = _load_rules_module(root)
        v14_hash = _compute_tier_hash(rules_mod.TIERS, rules_mod.KNOWN_V_MODE)
        v13_hash = _compute_tier_hash(rules_mod.TIERS_V13, rules_mod.KNOWN_V_MODE)
        tiers_ver = str(rules_mod.TIERS_VERSION)
    except Exception as exc:
        failures.append(f"failed computing tier hashes from canary.rules: {exc}")
        v14_hash = ""
        v13_hash = ""
        tiers_ver = ""

    if v14_hash and v13_hash:
        if f'TIERS_VERSION = "{tiers_ver}"' not in doc_text or f"TIERS_VERSION={tiers_ver}" not in doc_text:
            failures.append(f"docs/JUDGE-WALKTHROUGH.md missing TIERS_VERSION={tiers_ver}")
        if not _has_token(doc_text, v14_hash):
            failures.append(f"docs/JUDGE-WALKTHROUGH.md missing v1.4 tier hash '{v14_hash}'")
        if not _has_token(doc_text, v13_hash):
            failures.append(f"docs/JUDGE-WALKTHROUGH.md missing v1.3 tier hash '{v13_hash}'")

    af_fc_tokens: tuple[str, ...] = ()
    fc_text = _read_text(
        root / "results" / "fresh_clone" / "README.md",
        failures,
        "results/fresh_clone/README.md",
    )
    for af_artifact in (
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt",
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt",
    ):
        if not (root / af_artifact).is_file():
            failures.append(f"missing fresh_clone artifact {af_artifact}")

    if fc_text is not None:
        fc_tables = _parse_md_tables(fc_text)
        mac_tbl = _find_table_by_header_prefix(fc_tables, ("run", "commit", "clone", "setup", "reproduce"))
        lin_tbl = _find_table_by_header_prefix(
            fc_tables,
            ("run", "commit", "clone", "reproduce_fast (repro_fast=1)", "reproduce (40 seeds)"),
        )
        af_tbl = _find_table_by_header_prefix(
            fc_tables,
            ("run", "commit", "clone", "reproduce_table (repro_anticheat=0)"),
        )
        m_cold = re.search(r"make setup`\s+took\s+\*\*([0-9.]+\s*s)\*\*", fc_text)
        if mac_tbl is None or lin_tbl is None or af_tbl is None or m_cold is None:
            failures.append("results/fresh_clone/README.md missing macOS/Linux/afterquery-final timing tables or cold setup timing")
        else:
            mac_row = mac_tbl[1]
            lin_row = lin_tbl[1]
            af_row = af_tbl[1]
            m_mac_setup = re.search(r"\b(\d+\s*s)\b", mac_row[3])
            m_mac_repro = re.search(r"\b(\d+\s*s)\b", mac_row[4])
            m_mac_accept = re.search(r"\b(\d+\s*s)\b", mac_row[5])
            m_mac_passed = re.search(r"\b(\d+\s+passed)\b", mac_row[6])
            m_lin_repro = re.search(r"\b(\d+\s*s)\b", lin_row[4])
            af_commit = af_row[1].strip()
            m_af_clone = re.search(r"\b(\d+\s*s)\b", af_row[2])
            m_af_table = re.search(r"\b(\d+\s*s)\b", af_row[3])
            m_af_repro = re.search(r"\b(\d+\s*s)\b", af_row[4])
            m_af_audit = re.search(r"\b(\d+\s*s)\b", af_row[5])
            m_af_summary = re.search(r"(\d+\s+PASS,\s*\d+\s+WARN,\s*\d+\s+FAIL)", af_row[5])
            m_af_test_s = re.search(r"\b(\d+\s*s)\b", af_row[6])
            m_af_test_p = re.search(r"\b(\d+\s+passed)\b", af_row[6])
            if not (
                m_mac_setup
                and m_mac_repro
                and m_mac_accept
                and m_mac_passed
                and m_lin_repro
                and af_commit
                and m_af_clone
                and m_af_table
                and m_af_repro
                and m_af_audit
                and m_af_summary
                and m_af_test_s
                and m_af_test_p
            ):
                failures.append("results/fresh_clone/README.md malformed timing cells in macOS/Linux/afterquery-final tables")
            else:
                af_fc_tokens = (
                    af_commit,
                    f"clone {m_af_clone.group(1)}",
                    f"reproduce_table {m_af_table.group(1)}",
                    f"reproduce {m_af_repro.group(1)}",
                    f"audit_submission {m_af_audit.group(1)}",
                    m_af_summary.group(1),
                    f"test_core {m_af_test_p.group(1)} in {m_af_test_s.group(1)}",
                )
                clean_doc = doc_text.replace("`", "").replace("**", "")
                for tok in (
                    m_mac_setup.group(1),
                    m_cold.group(1),
                    f"make reproduce {m_mac_repro.group(1)}",
                    f"make accept {m_mac_accept.group(1)}",
                    m_mac_passed.group(1),
                    f"make reproduce {m_lin_repro.group(1)}",
                    "0 FAIL",
                    *af_fc_tokens,
                ):
                    if not _has_token(clean_doc, tok):
                        failures.append(
                            f"fresh_clone/README.md token '{tok}' missing from docs/JUDGE-WALKTHROUGH.md"
                        )

    docs_to_check: tuple[str, ...] = (WALKTHROUGH_REL,) if explicit_doc else (WALKTHROUGH_REL, QUICKSTART_REL)
    if not explicit_doc:
        qs_text = _read_text(root / QUICKSTART_REL, failures, QUICKSTART_REL)
        if qs_text is not None:
            if EM_DASH in qs_text or EN_DASH in qs_text:
                failures.append("JUDGE_QUICKSTART.md contains em or en dash characters")
            _, qs_broken, qs_targets = _check_relative_links_with_targets(root, QUICKSTART_REL, qs_text)
            failures.extend(qs_broken)
            for req_qs in (
                "docs/JUDGE-WALKTHROUGH.md",
                "docs/PEER-REVIEW-QA.md",
                "docs/REPRODUCIBILITY.md",
                "docs/reports/integrity.md",
                "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json",
                "tests/test_integrity_valid_filter.py",
                "results/fresh_clone/README.md",
            ):
                if req_qs not in qs_targets:
                    failures.append(f"JUDGE_QUICKSTART.md missing required link to '{req_qs}'")
            clean_qs = qs_text.replace("`", "").replace("**", "")
            gap_path = root / "docs" / "reports" / "gap.md"
            if gap_path.is_file():
                gap_body = gap_path.read_text(encoding="utf-8", errors="replace")
                if "gemini-3.5-flash" not in gap_body.lower() and UNAPPROVED_FLASH_GAP_RX.search(clean_qs):
                    failures.append(
                        "JUDGE_QUICKSTART.md cites OpenCode gemini-3.5-flash gap claim not present in docs/reports/gap.md"
                    )
            raw_qs = clean_qs.find("65% [24%, 98%]")
            la_qs = clean_qs.find("72% [52%, 91%]")
            if raw_qs == -1 or la_qs == -1 or raw_qs > la_qs:
                failures.append("JUDGE_QUICKSTART.md must lead with raw '65% [24%, 98%]' before luck-adjusted '72% [52%, 91%]'")
            for tok in af_fc_tokens:
                if not _has_token(clean_qs, tok):
                    failures.append(f"fresh_clone/README.md token '{tok}' missing from JUDGE_QUICKSTART.md")

    cmd_results = verify_doc_commands.verify_repo(root=root, docs=docs_to_check)
    if not cmd_results:
        failures.append("verify_doc_commands returned no results for docs/JUDGE-WALKTHROUGH.md")
    for res in cmd_results:
        if res.status != "PASS":
            detail_str = "; ".join(res.details[:3]) if res.details else res.summary
            failures.append(f"verify_doc_commands [{res.name}] {res.status}: {detail_str}")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} Pillar 4 claim/command mismatch(es)", failures)
    return CheckResult(
        name,
        "PASS",
        "verified frozen tier hashes, 1bc3e281/macOS/Linux fresh-clone timings (118 s / 52 s / 159 s), companion links, and CLI commands",
    )


def verify_judge_walkthrough(root: Path = ROOT) -> list[CheckResult]:
    resolved = Path(os.path.abspath(str(root)))
    doc_path = resolved / WALKTHROUGH_REL
    doc_text: str | None = None
    if doc_path.is_file():
        try:
            doc_text = doc_path.read_text(encoding="utf-8")
        except OSError:
            doc_text = None
    fa_cached: dict[str, Any] | None = None
    fa_path = resolved / "results" / "failure_analysis_v1.4.json"
    if fa_path.is_file():
        try:
            parsed_fa = json.loads(fa_path.read_text(encoding="utf-8"))
            if isinstance(parsed_fa, dict):
                fa_cached = parsed_fa
        except (OSError, ValueError):
            fa_cached = None
    return [
        check_pillar1_frontier_gap(resolved, doc_text=doc_text),
        check_pillar2_failure_and_fairness(resolved, doc_text=doc_text, _fa_obj=fa_cached),
        check_pillar3_reward_integrity(resolved, doc_text=doc_text),
        check_pillar4_craft_and_commands(resolved, doc_text=doc_text),
    ]


verify_repo = verify_judge_walkthrough


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
        description="Mechanically cross-check quantitative claims and CLI commands across all 4 pillars of docs/JUDGE-WALKTHROUGH.md."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_judge_walkthrough(root=args.root)
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
