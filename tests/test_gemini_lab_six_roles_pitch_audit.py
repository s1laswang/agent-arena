from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tokenize
from typing import Any

import pytest

from canary import rules
from canary.gemini import carbon_roles as cr

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_TEST_PATH = Path(__file__).resolve()
ROLES_CARBON_DIR = REPO_ROOT / "results" / "gemini" / "roles_carbon"
ROLES_MD_PATH = REPO_ROOT / "docs" / "gemini" / "ROLES_CARBON.md"
SIX_ROLES_SUBMISSION_MD_PATH = REPO_ROOT / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md"
PITCH_SIX_ROLES_MD_PATH = REPO_ROOT / "pitch" / "GEMINI_SIX_ROLES.md"
MAIN_SUBMISSION_MD_PATH = REPO_ROOT / "docs" / "gemini" / "SUBMISSION.md"
VALIDATION_MD_PATH = REPO_ROOT / "docs" / "gemini" / "validation.md"
CARBON_ROLES_PY_PATH = REPO_ROOT / "canary" / "gemini" / "carbon_roles.py"
CARBON_ROLES_TEST_PATH = REPO_ROOT / "tests" / "test_gemini_lab_carbon_roles.py"

HASH_CHAR = chr(35)
H2_PREFIX = (HASH_CHAR * 2) + " "
FORBIDDEN_UNICODE_DASHES: tuple[str, ...] = tuple(
    chr(cp)
    for cp in (
        0x2010,
        0x2011,
        0x2012,
        0x2013,
        0x2014,
        0x2015,
        0x2212,
        0xFE58,
        0xFE63,
        0xFF0D,
    )
)

EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"

PROTECTED_PATHS: tuple[str, ...] = (
    "docs/gemini/validation.md",
    "canary/rules.py",
    "canary/env.py",
    "canary/scoring.py",
    "harbor",
    "data/worlds",
    "data/runs/committed",
    "results/judge_table.md",
    "results/judge_episodes.jsonl",
)

API_KEY_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)

PLACEHOLDER_WORD_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|DRAFT|XXX|STUB|PLACEHOLDER|LOREM|IPSUM)\b",
    re.IGNORECASE,
)
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_.\-/ ]+>")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_SPAN_RE = re.compile(r"`([^`\r\n]+)`")

EXPECTED_17_MM_RUNS = frozenset({
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
})

EXPECTED_2_EH_RUNS = frozenset({
    "blackbox-swarm-carbon",
    "whitebox-swarm-carbon",
})


@pytest.fixture(autouse=True)
def _keyless_zero_live_api(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in API_KEY_ENV_VARS:
        monkeypatch.setenv(var, "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    def _blocked_network(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Live network access blocked in keyless six-roles pitch audit")

    monkeypatch.setattr(socket.socket, "connect", _blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_network)
    monkeypatch.setattr(socket, "create_connection", _blocked_network)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _parse_md_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("|") and line.endswith("|") and idx + 1 < len(lines):
            sep = lines[idx + 1].strip()
            if sep.startswith("|") and "-" in sep:
                headers = [c.strip() for c in line.strip("|").split("|")]
                rows: list[list[str]] = []
                idx += 2
                while idx < len(lines):
                    rline = lines[idx].strip()
                    if not (rline.startswith("|") and rline.endswith("|")):
                        break
                    rows.append([c.strip() for c in rline.strip("|").split("|")])
                    idx += 1
                tables.append((headers, rows))
                continue
        idx += 1
    return tables


def _extract_h2_section(md_text: str, heading_fragment: str) -> str:
    lines = md_text.splitlines()
    start_idx: int | None = None
    needle = heading_fragment.lower()
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith(H2_PREFIX):
            title = stripped[len(H2_PREFIX):].strip().lower()
            if needle in title:
                start_idx = idx + 1
                break
    if start_idx is None:
        raise AssertionError(f"H2 section containing {heading_fragment!r} not found")
    collected: list[str] = []
    for raw in lines[start_idx:]:
        if raw.strip().startswith(H2_PREFIX):
            break
        collected.append(raw)
    return "\n".join(collected).strip()


def _resolve_doc_crosslinks(doc_path: Path, md_text: str, root_path: Path) -> set[str]:
    resolved_labels: set[str] = set()

    for match in MD_LINK_RE.finditer(md_text):
        raw_href = match.group(1).strip()
        if not raw_href or raw_href.startswith(("http://", "https://", "mailto:")):
            continue
        clean_href = raw_href.split(HASH_CHAR, 1)[0].strip()
        if not clean_href:
            continue
        rel_candidate = (doc_path.parent / clean_href).resolve()
        root_candidate = (root_path / clean_href).resolve()
        assert rel_candidate.exists() or root_candidate.exists(), (
            f"Unresolved markdown link {raw_href!r} in {doc_path}"
        )
        resolved_labels.add(clean_href)

    for match in CODE_SPAN_RE.finditer(md_text):
        tok = match.group(1).strip()
        if not tok or " " in tok or "(" in tok or "=" in tok:
            continue
        clean_tok = tok.split(HASH_CHAR, 1)[0].rstrip("/")
        if not clean_tok:
            continue

        if clean_tok.endswith((".md", ".py", ".json", ".jsonl", ".html")):
            if "/" in clean_tok:
                target = root_path / clean_tok
                rel_target = doc_path.parent / clean_tok
                assert (target.is_file() and target.stat().st_size > 0) or (
                    rel_target.is_file() and rel_target.stat().st_size > 0
                ), f"Unresolved file reference {tok!r} in {doc_path}"
            else:
                sib_target = doc_path.parent / clean_tok
                root_target = root_path / clean_tok
                assert (sib_target.is_file() and sib_target.stat().st_size > 0) or (
                    root_target.is_file() and root_target.stat().st_size > 0
                ), f"Unresolved sibling/root file reference {tok!r} in {doc_path}"
            resolved_labels.add(clean_tok)
        elif clean_tok.startswith("results/gemini/roles_carbon"):
            target_dir = root_path / clean_tok
            assert target_dir.is_dir(), f"Unresolved roles_carbon directory {tok!r} in {doc_path}"
            parts = Path(clean_tok).parts
            if len(parts) >= 5:
                assert (target_dir / "meta.json").is_file(), f"Run dir missing meta.json: {target_dir}"
            resolved_labels.add(clean_tok)
        elif clean_tok.startswith("roles_carbon/"):
            target_dir = root_path / "results" / "gemini" / clean_tok
            assert target_dir.is_dir(), f"Unresolved short roles_carbon path {tok!r} in {doc_path}"
            resolved_labels.add(clean_tok)

    return resolved_labels


def _assert_why_gemini_five_pillars(
    md_text: str,
    report: dict[str, Any],
    doc_label: str,
) -> None:
    sec = _extract_h2_section(md_text, "Why Gemini Is Essential")
    bullets = [ln.strip() for ln in sec.splitlines() if ln.strip().startswith("- **")]
    assert len(bullets) == 5, f"{doc_label}: expected 5 Why-Gemini-Is-Essential bullets, got {len(bullets)}"

    tot = report["totals"]
    mm = report["multimodal_summary"]
    eh = report["exploit_summary"]
    pooled = mm.get("pooled_ablation")

    b_think, b_sig, b_cache, b_longctx, b_vision = bullets

    assert "Controlled `thinking_level` on one model:" in b_think
    assert "thinking_level" in b_think or "thinking tokens" in b_think
    inv_runs = report["roles"]["investigators"]["runs"]
    hard_lad = next((r for r in inv_runs if r["run_name"] == "thinking-ladder-carbon-hard0"), None)
    if hard_lad is not None:
        assert hard_lad["run_folder"] in b_think
        assert hard_lad["commit"] in b_think
        assert f"{hard_lad['thinking_tokens']:,}" in b_think
    else:
        assert f"{tot['thinking_tokens']:,}" in b_think
        assert f"{tot['verified_runs']:,}" in b_think

    assert "Load-bearing `thought_signature` replay:" in b_sig
    assert "thought_signature" in b_sig
    assert "400 INVALID_ARGUMENT" in b_sig
    assert "canary.gemini.ablations" in b_sig
    assert f"{tot['calls']:,}" in b_sig

    assert "Explicit and prefix context caching:" in b_cache
    assert f"**{tot['cached_tokens']:,}**" in b_cache
    assert f"**{tot['tokens_in']:,}**" in b_cache
    assert f"**{tot['cache_hit_pct']:.1f}%**" in b_cache
    assert f"**${tot['cost_usd']:.4f}**" in b_cache
    assert f"**${tot['list_cost_usd']:.4f}**" in b_cache

    assert "1M-token long context:" in b_longctx
    assert "without lossy RAG chunking" in b_longctx
    assert "checked deterministically in Python" in b_longctx
    if eh["max_pack_files"] > 0:
        assert f"`{eh['max_pack_files']}` files" in b_longctx
        assert f"`{eh['max_pack_tokens']:,}` tokens" in b_longctx
    fa_in = report["roles"]["failure_analyst"]["tokens_in"]
    if fa_in > 0:
        assert f"`{fa_in:,}` failure-analyst input tokens" in b_longctx

    assert "Native multimodal vision (`Part.from_bytes`):" in b_vision
    assert 'Part.from_bytes(mime_type="image/png")' in b_vision
    assert f"`{int(mm.get('total_images') or 0):,}`" in b_vision
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        assert f"`n={pooled['n_episodes']}`" in b_vision
        assert f"`{pooled['n_scans']}` PNG scans" in b_vision
        assert f"`{pooled['paired_diff']:+.4f} +/- {pooled['diff_ci']:.4f}`" in b_vision
        assert "95% CI" in b_vision
        assert "100.0%` Bayesian text-oracle recovery" in b_vision


def _assert_three_doc_rubric(
    root_path: Path,
    report: dict[str, Any],
    *,
    expect_strict_six: bool,
) -> None:
    roles_md_path = root_path / "docs" / "gemini" / "ROLES_CARBON.md"
    sub_md_path = root_path / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md"
    pitch_md_path = root_path / "pitch" / "GEMINI_SIX_ROLES.md"
    main_sub_path = root_path / "docs" / "gemini" / "SUBMISSION.md"
    val_md_path = root_path / "docs" / "gemini" / "validation.md"

    for required_file in (roles_md_path, sub_md_path, pitch_md_path, main_sub_path, val_md_path):
        assert required_file.is_file() and required_file.stat().st_size > 0, required_file

    roles_md = roles_md_path.read_text(encoding="utf-8")
    sub_md = sub_md_path.read_text(encoding="utf-8")
    pitch_md = pitch_md_path.read_text(encoding="utf-8")

    assert roles_md == cr.render_roles_carbon_md(report)
    assert sub_md == cr.render_six_roles_submission_md(report)
    assert pitch_md == cr.render_pitch_six_roles_md(report)

    assert cr.validate_rendered_doc(roles_md, root_path, report, kind="roles") == []
    assert cr.validate_rendered_doc(sub_md, root_path, report, kind="submission") == []
    assert cr.validate_rendered_doc(pitch_md, root_path, report, kind="pitch") == []

    for doc_path, doc_txt in (
        (roles_md_path, roles_md),
        (sub_md_path, sub_md),
        (pitch_md_path, pitch_md),
    ):
        assert PLACEHOLDER_WORD_RE.findall(doc_txt) == [], doc_path
        assert ANGLE_PLACEHOLDER_RE.findall(doc_txt) == [], doc_path
        assert cr.STALE_ROLES_PREFIX not in doc_txt, doc_path
        assert "scripts/" not in doc_txt, doc_path
        for dash in FORBIDDEN_UNICODE_DASHES:
            assert dash not in doc_txt, f"Unicode dash U+{ord(dash):04X} in {doc_path}"
        assert cr.scan_file_hygiene(doc_path, root_path) == [], doc_path
        for role in cr.REQUIRED_ROLES:
            assert f"`{role}`" in doc_txt, (doc_path, role)

    sub_summary = cr.extract_platform_summary(sub_md)
    pitch_summary = cr.extract_platform_summary(pitch_md)
    assert sub_summary == pitch_summary == report["platform_summary"]
    assert 100 <= len(sub_summary) <= 600
    assert re.search(r"\bn=[1-9]\d*\b", sub_summary) is not None
    assert "95% CI" in sub_summary
    assert "+/-" in sub_summary
    assert "gemini-4-carbon" in sub_summary
    assert "Part.from_bytes" in sub_summary
    assert HASH_CHAR not in sub_summary
    assert PLACEHOLDER_WORD_RE.findall(sub_summary) == []
    for dash in FORBIDDEN_UNICODE_DASHES:
        assert dash not in sub_summary

    sub_links = _resolve_doc_crosslinks(sub_md_path, sub_md, root_path)
    roles_links = _resolve_doc_crosslinks(roles_md_path, roles_md, root_path)
    pitch_links = _resolve_doc_crosslinks(pitch_md_path, pitch_md, root_path)

    assert {"docs/gemini/SUBMISSION.md", "docs/gemini/ROLES_CARBON.md", "docs/gemini/validation.md"}.issubset(sub_links)
    assert "canary/gemini/carbon_roles.py" in sub_links
    assert "docs/gemini/validation.md" in roles_links
    assert {
        "docs/gemini/SUBMISSION.md",
        "docs/gemini/SIX_ROLES_SUBMISSION.md",
        "docs/gemini/ROLES_CARBON.md",
        "docs/gemini/validation.md",
    }.issubset(pitch_links)

    assert (sub_md_path.parent / "SUBMISSION.md").is_file()
    assert (sub_md_path.parent / "SIX_ROLES_SUBMISSION.md").is_file()
    assert (sub_md_path.parent / "ROLES_CARBON.md").is_file()
    assert (sub_md_path.parent / "validation.md").is_file()
    assert (pitch_md_path.parent / ".." / "docs" / "gemini" / "SUBMISSION.md").resolve() == main_sub_path.resolve()
    assert (pitch_md_path.parent / ".." / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md").resolve() == sub_md_path.resolve()
    assert (pitch_md_path.parent / ".." / "docs" / "gemini" / "ROLES_CARBON.md").resolve() == roles_md_path.resolve()

    eh = report["exploit_summary"]
    assert eh["total_attempts"] > 0
    assert eh["inproc_attempts"] + eh["mcp_attempts"] == eh["total_attempts"]
    inproc_tag = f"**{eh['inproc_attempts']} of {eh['total_attempts']}**"
    mcp_tag = f"**{eh['mcp_attempts']} of {eh['total_attempts']}**"
    ledger_tag = f"{eh['ledger_verified']}/{eh['total_attempts']} server-ledger verified"
    suite_ratio = (
        f"suite channels: {eh['inproc_attempts']}/{eh['total_attempts']} in-process, "
        f"{eh['mcp_attempts']}/{eh['total_attempts']} live HTTP MCP"
    )
    for doc_txt in (roles_md, sub_md, pitch_md):
        assert inproc_tag in doc_txt
        assert mcp_tag in doc_txt
        assert "in-process against `canary.env.Env`" in doc_txt
        assert "executed over live HTTP MCP" in doc_txt
        assert ledger_tag in doc_txt
        assert "public `v1.4` dev seeds" in doc_txt
        assert "900000+" in doc_txt
        assert "`v1.5` candidate" in doc_txt
        assert "arena mode" in doc_txt
        assert "docs/gemini/validation.md" in doc_txt
        assert "human labeller Ivar" in doc_txt
    assert suite_ratio in sub_md
    assert suite_ratio in pitch_md

    _assert_why_gemini_five_pillars(sub_md, report, "SIX_ROLES_SUBMISSION.md")
    _assert_why_gemini_five_pillars(pitch_md, report, "pitch/GEMINI_SIX_ROLES.md")

    sub_tables = _parse_md_tables(sub_md)
    pitch_tables = _parse_md_tables(pitch_md)
    roles_tables = _parse_md_tables(roles_md)
    assert len(sub_tables) == 1
    assert len(pitch_tables) == 1
    assert len(roles_tables) >= 2

    _, sub_rows = sub_tables[0]
    _, pitch_rows = pitch_tables[0]
    _, role_tot_rows = roles_tables[0]
    _, role_canon_rows = roles_tables[1]

    assert [r[0] for r in sub_rows] == [f"`{role}`" for role in cr.REQUIRED_ROLES]
    assert [r[0] for r in pitch_rows] == [f"`{role}`" for role in cr.REQUIRED_ROLES]
    assert [r[0] for r in role_canon_rows] == [f"`{role}`" for role in cr.REQUIRED_ROLES]
    assert len(role_tot_rows) == 7
    assert role_tot_rows[-1][0] == "**Total**"

    def _parse_int_cell(cell: str) -> int:
        return int(cell.replace("*", "").replace(",", "").strip())

    def _parse_usd_cell(cell: str) -> float:
        return float(cell.replace("*", "").replace("$", "").replace(",", "").strip())

    sum_runs = 0
    sum_eps = 0
    sum_calls = 0
    sum_in = 0
    sum_out = 0
    sum_think = 0
    sum_cached = 0
    for role, row_t in zip(cr.REQUIRED_ROLES, role_tot_rows[:6]):
        ri = report["roles"][role]
        assert row_t[0] == f"`{role}`"
        assert _parse_int_cell(row_t[2]) == ri["n_verified"]
        assert _parse_int_cell(row_t[3]) == ri["count"]
        assert _parse_int_cell(row_t[4]) == ri["calls"]
        assert _parse_int_cell(row_t[5]) == ri["tokens_in"]
        assert _parse_int_cell(row_t[6]) == ri["tokens_out"]
        assert _parse_int_cell(row_t[7]) == ri["thinking_tokens"]
        assert _parse_int_cell(row_t[8]) == ri["cached_tokens"]
        assert row_t[9] == f"${ri['cost_usd']:.4f}"
        sum_runs += ri["n_verified"]
        sum_eps += ri["count"]
        sum_calls += ri["calls"]
        sum_in += ri["tokens_in"]
        sum_out += ri["tokens_out"]
        sum_think += ri["thinking_tokens"]
        sum_cached += ri["cached_tokens"]

    tot = report["totals"]
    tot_row = role_tot_rows[6]
    assert _parse_int_cell(tot_row[2]) == sum_runs == tot["verified_runs"]
    assert _parse_int_cell(tot_row[3]) == sum_eps == tot["count"]
    assert _parse_int_cell(tot_row[4]) == sum_calls == tot["calls"]
    assert _parse_int_cell(tot_row[5]) == sum_in == tot["tokens_in"]
    assert _parse_int_cell(tot_row[6]) == sum_out == tot["tokens_out"]
    assert _parse_int_cell(tot_row[7]) == sum_think == tot["thinking_tokens"]
    assert _parse_int_cell(tot_row[8]) == sum_cached == tot["cached_tokens"]
    assert _parse_usd_cell(tot_row[9]) == pytest.approx(tot["cost_usd"], abs=1e-4)

    for role, row_s, row_p, row_r in zip(cr.REQUIRED_ROLES, sub_rows, pitch_rows, role_canon_rows):
        canon = report["roles"][role]["canonical_run"]
        assert row_s[6] == row_p[6]
        if canon is None:
            assert row_s[2] == row_p[2] == row_r[2] == "none"
            assert row_s[6] == "not populated on this branch"
        else:
            expected_sub_usage = (
                f"{canon['calls']:,} / {canon['tokens_in']:,} / {canon['tokens_out']:,} / "
                f"{canon['thinking_tokens']:,} / ${canon['cost_usd']:.4f}"
            )
            expected_pitch_usage = f"{canon['calls']:,} / ${canon['cost_usd']:.4f}"
            assert row_s[2] == row_p[2] == row_r[2] == f"`{canon['run_folder']}`"
            assert row_s[3] == row_p[3] == row_r[3] == "`gemini-4-carbon`"
            assert row_s[4] == row_p[4] == row_r[4] == f"`{canon['commit']}`"
            assert row_s[5] == expected_sub_usage
            assert row_p[5] == expected_pitch_usage
            assert (root_path / canon["run_folder"] / "meta.json").is_file()

    if expect_strict_six:
        assert report["strict_ok"] is True
        assert report["verified_roles_count"] == 6
        assert report["missing_roles"] == []
        assert "STRICT 6/6 VERIFIED" in roles_md
        assert "six essential roles" in sub_summary
        for doc_txt in (roles_md, sub_md, pitch_md):
            assert "not populated on this branch" not in doc_txt
        for row_s, row_p, row_r in zip(sub_rows, pitch_rows, role_canon_rows):
            assert row_s[2].startswith("`results/gemini/roles_carbon/")
            assert row_s[2] == row_p[2] == row_r[2]
            assert row_s[3] == row_p[3] == row_r[3] == "`gemini-4-carbon`"
            commit_val = row_s[4].strip("`")
            assert cr.COMMIT_RE.fullmatch(commit_val) is not None
            assert row_s[4] == row_p[4] == row_r[4]
            run_rel = row_s[2].strip("`")
            assert (root_path / run_rel / "meta.json").is_file()


def _build_six_role_synthetic_fixture(base_dir: Path) -> Path:
    stage_root = base_dir / "six_role_stage"
    stage_roles = stage_root / "results" / "gemini" / "roles_carbon"
    stage_roles.mkdir(parents=True)

    (stage_root / "data").symlink_to(REPO_ROOT / "data", target_is_directory=True)
    (stage_root / "canary").symlink_to(REPO_ROOT / "canary", target_is_directory=True)
    (stage_root / "tests").mkdir(parents=True, exist_ok=True)
    (stage_root / "tests" / "test_gemini_lab_carbon_roles.py").symlink_to(CARBON_ROLES_TEST_PATH)

    stage_docs = stage_root / "docs" / "gemini"
    stage_docs.mkdir(parents=True, exist_ok=True)
    (stage_docs / "SUBMISSION.md").symlink_to(MAIN_SUBMISSION_MD_PATH)
    shutil.copy2(VALIDATION_MD_PATH, stage_docs / "validation.md")

    shutil.copytree(ROLES_CARBON_DIR / "exploit_hunter", stage_roles / "exploit_hunter")
    shutil.copytree(ROLES_CARBON_DIR / "multimodal_evidence", stage_roles / "multimodal_evidence")

    _write_json(
        stage_roles / "world_text" / "persona-interviews-carbon" / "meta.json",
        {
            "role": "world_text",
            "subrole": "live_persona_interviews",
            "model_id": "gemini-4-carbon",
            "commit": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
            "n_interviews": 32,
            "truth_leak_violations": 0,
            "fake_env": False,
            "smoke": False,
            "stub": False,
            "usage": {
                "calls": 32,
                "in": 31496,
                "out": 2345,
                "thinking": 6957,
                "cached": 18200,
                "cost_usd": 0.156,
            },
        },
    )
    _write_json(
        stage_roles / "world_text" / "biased-chatter-ablation-carbon" / "meta.json",
        {
            "role": "world_text",
            "subrole": "biased_chatter_ablation",
            "model_id": "gemini-4-carbon",
            "commit": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
            "n_messages": 48,
            "carbon_biased_mean": 0.612,
            "carbon_template_mean": 0.648,
            "truth_leak_violations": 0,
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 16,
                "in": 44200,
                "out": 3890,
                "thinking": 4100,
                "cached": 22000,
                "cost_usd": 0.142,
            },
        },
    )
    _write_json(
        stage_roles / "world_text" / "worldtext-carbon-suite" / "summary.json",
        {"consolidated": True},
    )

    _write_json(
        stage_roles / "adaptive_mole" / "paired-skill-designer-carbon-hard" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "paired_skill_designer",
            "model_id": "gemini-4-carbon",
            "commit": "b2c3d4e5f60718293a4b5c6d7e8f90123456789a",
            "n_kept": 6,
            "n_llm_valid": 6,
            "eval_full_solver_mean": 0.628,
            "fake_env": False,
            "smoke": False,
            "stub": False,
            "usage": {
                "calls": 18,
                "in": 74000,
                "out": 9100,
                "thinking": 11200,
                "cached": 30000,
                "cost_usd": 0.318,
            },
        },
    )
    _write_json(
        stage_roles / "adaptive_mole" / "carbon-vs-carbon-suite" / "suite.json",
        {"consolidated": True},
    )

    inv_paired_dir = stage_roles / "investigators" / "v14-paired-dev-seeds"
    _write_json(
        inv_paired_dir / "meta.json",
        {
            "role": "investigators",
            "subrole": "v14_frontier_investigator",
            "model_id": "gemini-4-carbon",
            "commit": "c3d4e5f60718293a4b5c6d7e8f90123456789ab1",
            "tier": "hard",
            "seeds": [0, 1, 2],
            "mean_score": 0.61,
            "accuracy": 1.0,
            "fake_env": False,
            "smoke": False,
            "stub": False,
            "usage": {
                "calls": 120,
                "in": 920000,
                "out": 24500,
                "thinking": 48200,
                "cached": 760000,
                "cost_usd": 1.845,
            },
        },
    )
    paired_eps = [
        {"tier": "medium", "seed": 0, "score": 0.68, "accused": "e01", "correct": True, "final_day": 8},
        {"tier": "medium", "seed": 1, "score": 0.64, "accused": "e02", "correct": True, "final_day": 9},
        {"tier": "medium", "seed": 2, "score": 0.70, "accused": "e03", "correct": True, "final_day": 7},
        {"tier": "hard", "seed": 0, "score": 0.58, "accused": "e04", "correct": True, "final_day": 11},
        {"tier": "hard", "seed": 1, "score": 0.52, "accused": "e05", "correct": True, "final_day": 12},
        {"tier": "hard", "seed": 2, "score": 0.62, "accused": "e06", "correct": True, "final_day": 10},
    ]
    (inv_paired_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(ep) for ep in paired_eps) + "\n",
        encoding="utf-8",
    )

    _write_json(
        stage_roles / "investigators" / "thinking-ladder-carbon-hard0" / "meta.json",
        {
            "role": "investigators",
            "subrole": "thinking_level_ablation",
            "model_id": "gemini-4-carbon",
            "commit": "d4e5f60718293a4b5c6d7e8f90123456789ab1c2",
            "episode_count": 2,
            "levels_summary": {
                "low": {"mean_score": 0.42},
                "high": {"mean_score": 0.68},
            },
            "solver_baseline": {"mean_score": 0.64},
            "fake_env": False,
            "smoke": False,
            "stub": False,
            "usage": {
                "calls": 163,
                "in": 6499263,
                "out": 5422,
                "thinking": 52968,
                "cached": 6200000,
                "cost_usd": 1.9892,
            },
        },
    )

    _write_json(
        stage_roles / "failure_analyst" / "atlas-carbon" / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "long_context_failure_atlas",
            "model_id": "gemini-4-carbon",
            "commit": "e5f60718293a4b5c6d7e8f90123456789ab1c2d3",
            "n_episodes_packed": 101,
            "n_clusters": 5,
            "verified_quotes_pct": 100.0,
            "agreement_rate": 0.933,
            "fake_env": False,
            "smoke": False,
            "stub": False,
            "usage": {
                "calls": 2,
                "in": 596862,
                "out": 3191,
                "thinking": 13356,
                "cached": 298000,
                "cost_usd": 1.3592,
            },
        },
    )

    _write_json(
        stage_roles / "multimodal_evidence" / "multimodal-carbon-suite" / "summary.json",
        {"consolidated": True},
    )

    for role in cr.REQUIRED_ROLES:
        idx_path = stage_roles / role / "index.json"
        if not idx_path.is_file():
            _write_json(
                idx_path,
                {
                    "role": role,
                    "target_model": "gemini-4-carbon",
                    "verified": True,
                    "secret_hygiene_clean": True,
                },
            )

    return stage_root


def test_live_repo_root_six_roles_pitch_and_submission_audit(tmp_path: Path) -> None:
    report = cr.audit_carbon_roles(REPO_ROOT)
    assert report["ok"] is True
    assert report["invalid_runs"] == []
    assert report["secret_leaks"] == []

    sync_res = cr.sync_carbon_roles_docs(REPO_ROOT, check=True)
    assert sync_res["ok"] is True
    assert sync_res["out_of_sync"] == []
    assert sync_res["missing_files"] == []
    assert sync_res["disk_leaks"] == []
    assert sync_res["validation_errors"] == {
        "roles_md": [],
        "submission_md": [],
        "pitch_md": [],
    }
    assert cr.main(["--root", str(REPO_ROOT), "--check"]) == 0

    eh_role = report["roles"]["exploit_hunter"]
    mm_role = report["roles"]["multimodal_evidence"]
    eh_by_name = {r["run_name"]: r for r in eh_role["runs"]}
    mm_by_name = {r["run_name"]: r for r in mm_role["runs"]}
    assert EXPECTED_2_EH_RUNS.issubset(set(eh_by_name))
    assert EXPECTED_17_MM_RUNS.issubset(set(mm_by_name))
    eh_core_calls = sum(eh_by_name[n]["calls"] for n in EXPECTED_2_EH_RUNS)
    mm_core_calls = sum(mm_by_name[n]["calls"] for n in EXPECTED_17_MM_RUNS)
    eh_core_cost = sum(eh_by_name[n]["cost_usd"] for n in EXPECTED_2_EH_RUNS)
    mm_core_cost = sum(mm_by_name[n]["cost_usd"] for n in EXPECTED_17_MM_RUNS)
    assert eh_core_calls == 215
    assert mm_core_calls == 226
    assert eh_core_calls + mm_core_calls == 441
    assert f"{eh_core_cost + mm_core_cost:.4f}" == "6.7655"
    if eh_role["n_verified"] == 2 and mm_role["n_verified"] == 17:
        assert eh_role["n_verified"] + mm_role["n_verified"] == 19
        assert eh_role["calls"] + mm_role["calls"] == 441
        assert f"{eh_role['cost_usd'] + mm_role['cost_usd']:.4f}" == "6.7655"

    expected_live_indices = {
        "results/gemini/roles_carbon/exploit_hunter/index.json",
        "results/gemini/roles_carbon/multimodal_evidence/index.json",
    }
    for role in cr.REQUIRED_ROLES:
        if (ROLES_CARBON_DIR / role / "index.json").is_file():
            expected_live_indices.add(f"results/gemini/roles_carbon/{role}/index.json")
    assert expected_live_indices.issubset(set(report["skipped_non_dirs"]))
    scanned_folders = {r["run_folder"] for r in report["runs"]}
    assert expected_live_indices.isdisjoint(scanned_folders)

    if set(report["verified_roles"]) == {"exploit_hunter", "multimodal_evidence"}:
        tot = report["totals"]
        assert report["strict_ok"] is False
        assert report["verified_roles_count"] == 2
        assert tot["verified_roles_count"] == 2
        assert tot["required_roles_count"] == 6
        assert tot["verified_runs"] == 19
        assert tot["scanned_runs"] == 19
        assert tot["count"] == 111
        assert tot["calls"] == 441
        assert tot["tokens_in"] == 3580516
        assert tot["tokens_out"] == 84772
        assert tot["thinking_tokens"] == 206845
        assert tot["cached_tokens"] == 1742975
        assert f"{tot['cost_usd']:.4f}" == "6.7655"
        assert f"{tot['list_cost_usd']:.4f}" == "10.0772"

        roles_md = ROLES_MD_PATH.read_text(encoding="utf-8")
        sub_md = SIX_ROLES_SUBMISSION_MD_PATH.read_text(encoding="utf-8")
        pitch_md = PITCH_SIX_ROLES_MD_PATH.read_text(encoding="utf-8")
        assert "PARTIAL SUITE CLEAN (2/6 roles populated)" in roles_md
        assert "**2 / 6** (`exploit_hunter`, `multimodal_evidence`)" in roles_md
        assert "**19**" in roles_md and "**441**" in roles_md and "**$6.7655**" in roles_md
        assert "**2/6** roles populated, **19** verified run folders, **441** API calls, **$6.7655**" in sub_md
        assert "**19 verified runs** (**2/6** roles populated), **441 API calls**" in pitch_md
        assert "**$6.7655**" in pitch_md
        assert "Across 19 verified gemini-4-carbon runs (441 API calls, $6.77 USD) in 2/6 populated carbon roles" in report["platform_summary"]
    else:
        partial_stage = tmp_path / "two_of_six_live_subset"
        partial_roles = partial_stage / "results" / "gemini" / "roles_carbon"
        shutil.copytree(ROLES_CARBON_DIR / "exploit_hunter", partial_roles / "exploit_hunter")
        shutil.copytree(ROLES_CARBON_DIR / "multimodal_evidence", partial_roles / "multimodal_evidence")
        partial_rep = cr.audit_carbon_roles(partial_stage)
        assert partial_rep["verified_roles_count"] == 2
        assert partial_rep["totals"]["verified_runs"] == 19
        assert partial_rep["totals"]["calls"] == 441
        assert f"{partial_rep['totals']['cost_usd']:.4f}" == "6.7655"
        assert {
            "results/gemini/roles_carbon/exploit_hunter/index.json",
            "results/gemini/roles_carbon/multimodal_evidence/index.json",
        }.issubset(set(partial_rep["skipped_non_dirs"]))

    _assert_three_doc_rubric(
        REPO_ROOT,
        report,
        expect_strict_six=(report["verified_roles_count"] == 6),
    )


def test_full_six_role_synthetic_fixture_rubric_and_strict_sync(tmp_path: Path) -> None:
    stage_root = _build_six_role_synthetic_fixture(tmp_path)
    stage_val_md = stage_root / "docs" / "gemini" / "validation.md"
    val_sha_before = _sha256_file(stage_val_md)

    manifest_path = stage_root / "results" / "gemini" / "roles_carbon_manifest.json"
    rc_write = cr.main(
        [
            "--root",
            str(stage_root),
            "--out-json",
            str(manifest_path),
            "--strict",
        ]
    )
    assert rc_write == 0
    assert manifest_path.is_file()
    assert cr.main(["--root", str(stage_root), "--strict", "--check"]) == 0
    assert _sha256_file(stage_val_md) == val_sha_before

    report = cr.audit_carbon_roles(stage_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert report == manifest
    assert report["ok"] is True
    assert report["strict_ok"] is True
    assert report["verified_roles_count"] == 6
    assert report["missing_roles"] == []
    assert report["invalid_runs"] == []
    assert report["secret_leaks"] == []
    assert report["totals"]["verified_runs"] == 25
    assert report["totals"]["calls"] == 792

    expected_six_indices = {f"results/gemini/roles_carbon/{r}/index.json" for r in cr.REQUIRED_ROLES}
    assert expected_six_indices.issubset(set(report["skipped_non_dirs"]))
    expected_suite_skips = {
        "results/gemini/roles_carbon/world_text/worldtext-carbon-suite",
        "results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-suite",
        "results/gemini/roles_carbon/multimodal_evidence/multimodal-carbon-suite",
    }
    assert expected_suite_skips.issubset(set(report["skipped_suite_dirs"]))

    v14_overall = report["v14_paired"]["overall"]
    assert isinstance(v14_overall, dict)
    assert v14_overall["n"] == 6
    assert [t["tier"] for t in report["v14_paired"]["tiers"]] == ["medium", "hard"]

    _assert_three_doc_rubric(stage_root, report, expect_strict_six=True)

    roles_md = (stage_root / "docs" / "gemini" / "ROLES_CARBON.md").read_text(encoding="utf-8")
    sub_md = (stage_root / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md").read_text(encoding="utf-8")
    pitch_md = (stage_root / "pitch" / "GEMINI_SIX_ROLES.md").read_text(encoding="utf-8")
    assert "Paired `gemini-4-carbon` vs `SolverPolicy` Benchmark (`v1.4`)" in roles_md
    assert "| **Overall** | **6** |" in roles_md
    assert "paired v1.4 n=6:" in report["platform_summary"]
    assert "including all `n=6` paired `investigators` episodes" in sub_md
    assert "including all `n=6` paired `investigators` episodes" in pitch_md
    assert "including all `n=6` paired `investigators` episodes" in roles_md


def test_platform_summary_bounds_and_hostile_validator_gates(tmp_path: Path) -> None:
    report = cr.audit_carbon_roles(REPO_ROOT)
    base_sub = cr.render_six_roles_submission_md(report)
    base_pitch = cr.render_pitch_six_roles_md(report)
    base_roles = cr.render_roles_carbon_md(report)

    for calls_n, usd_val, runs_n in ((441, 6.7655, 19), (11180, 88.72, 108), (24855, 226.34, 240)):
        synth_summary = cr.build_platform_summary(
            totals={
                "verified_runs": runs_n,
                "verified_roles_count": 6,
                "required_roles_count": 6,
                "calls": calls_n,
                "cost_usd": usd_val,
            },
            v14_paired={
                "overall": {
                    "n": 34,
                    "paired_diff": -0.0538,
                    "diff_ci": 0.1319,
                    "ratio": 0.9154,
                }
            },
            mm_summary={"pooled_ablation": None},
        )
        assert 100 <= len(synth_summary) <= 600
        assert "n=34" in synth_summary
        assert "95% CI" in synth_summary
        assert "+/-" in synth_summary
        assert f"{calls_n:,}" in synth_summary
        assert HASH_CHAR not in synth_summary
        for dash in FORBIDDEN_UNICODE_DASHES:
            assert dash not in synth_summary

    bloated_summary = "Canary benchmark summary n=27 +/- 0.122 95% CI. " + ("X" * 620)
    over_len_doc = base_sub.replace(report["platform_summary"], bloated_summary)
    errs_len = cr.validate_rendered_doc(over_len_doc, REPO_ROOT, report, kind="submission")
    assert any(e.startswith("platform_summary_len:") for e in errs_len)

    no_ci_summary = (
        "Canary is a Bayesian insider-threat RL benchmark across 19 verified gemini-4-carbon runs "
        "and 441 API calls in six roles with Part.from_bytes scan vision and keyless offline replay."
    )
    no_ci_doc = base_pitch.replace(report["platform_summary"], no_ci_summary)
    errs_ci = cr.validate_rendered_doc(no_ci_doc, REPO_ROOT, report, kind="pitch")
    assert "platform_summary_missing_n_or_ci" in errs_ci

    todo_doc = base_sub + "\nPending TODO item\n"
    assert "placeholder_marker_found" in cr.validate_rendered_doc(todo_doc, REPO_ROOT, report, kind="submission")

    angle_doc = base_pitch + "\nFill <insert_metric_here> before submit.\n"
    assert "ascii_angle_placeholder_found" in cr.validate_rendered_doc(angle_doc, REPO_ROOT, report, kind="pitch")

    stale_doc = base_roles + "\nSee results/gemini_roles/multimodal_evidence/old-run\n"
    assert "stale_gemini_roles_path" in cr.validate_rendered_doc(stale_doc, REPO_ROOT, report, kind="roles")

    em_dash_doc = base_pitch + f"\nClause {chr(0x2014)} with forbidden dash.\n"
    assert "unicode_dash_found" in cr.validate_rendered_doc(em_dash_doc, REPO_ROOT, report, kind="pitch")

    ghost_run_doc = base_sub + "\n`results/gemini/roles_carbon/world_text/nonexistent-run`\n"
    errs_ghost = cr.validate_rendered_doc(ghost_run_doc, REPO_ROOT, report, kind="submission")
    assert "missing_cited_dir:results/gemini/roles_carbon/world_text/nonexistent-run" in errs_ghost

    stripped_pillar_doc = base_pitch.replace("thought_signature", "redacted_token_field")
    errs_pillar = cr.validate_rendered_doc(stripped_pillar_doc, REPO_ROOT, report, kind="pitch")
    assert "missing_essential_pillar:thought_signature" in errs_pillar

    fake_key = "AI" + "za" + "SyFakeFixtureKeyToken1234567890"
    leaked_doc = base_roles + f"\n{fake_key}\n"
    assert "secret_leak_in_doc" in cr.validate_rendered_doc(leaked_doc, REPO_ROOT, report, kind="roles")
    assert tmp_path.is_dir()


def test_exploit_channel_counts_and_untouched_validation_contract() -> None:
    bb_swarm = json.loads(
        (ROLES_CARBON_DIR / "exploit_hunter" / "blackbox-swarm-carbon" / "swarm.json").read_text(encoding="utf-8")
    )
    wb_swarm = json.loads(
        (ROLES_CARBON_DIR / "exploit_hunter" / "whitebox-swarm-carbon" / "swarm.json").read_text(encoding="utf-8")
    )
    bb_attempts = bb_swarm["attempts"]
    wb_attempts = wb_swarm["attempts"]
    assert len(bb_attempts) == 6
    assert len(wb_attempts) == 5

    bb_mcp = sum(1 for a in bb_attempts if a.get("channel") == "mcp")
    bb_inproc = len(bb_attempts) - bb_mcp
    wb_mcp = sum(1 for a in wb_attempts if a.get("channel") == "mcp")
    wb_inproc = len(wb_attempts) - wb_mcp
    assert (bb_inproc, bb_mcp) == (4, 2)
    assert (wb_inproc, wb_mcp) == (4, 1)
    assert (bb_inproc + wb_inproc, bb_mcp + wb_mcp) == (8, 3)

    eh_index = json.loads((ROLES_CARBON_DIR / "exploit_hunter" / "index.json").read_text(encoding="utf-8"))
    assert eh_index["totals"]["attempts"] == 11
    assert eh_index["totals"]["inproc_attempts"] == 8
    assert eh_index["totals"]["mcp_attempts"] == 3
    assert eh_index["totals"]["ledger_verified"] == 11
    assert eh_index["totals"]["tool_calls"] == 655

    mm_index = json.loads((ROLES_CARBON_DIR / "multimodal_evidence" / "index.json").read_text(encoding="utf-8"))
    assert mm_index["totals"]["run_count"] == 17
    assert mm_index["totals"]["images_read_by_model"] == 260
    assert mm_index["totals"]["usage"]["calls"] == 226
    assert mm_index["hygiene"]["judge_seed_count"] == 0

    val_text = VALIDATION_MD_PATH.read_text(encoding="utf-8")
    assert "human labeller: Ivar" in val_text
    for row_num in range(1, 31):
        assert f"| {row_num} |" in val_text

    assert rules.TIERS_VERSION == "v1.4"
    v14_obj = {"tiers": {k: v.to_dict() for k, v in rules.TIERS.items()}, "known_v_mode": rules.KNOWN_V_MODE}
    v13_obj = {"tiers": {k: v.to_dict() for k, v in rules.TIERS_V13.items()}, "known_v_mode": rules.KNOWN_V_MODE}
    v14_hash = hashlib.sha256(json.dumps(v14_obj, sort_keys=True, default=list).encode()).hexdigest()[:16]
    v13_hash = hashlib.sha256(json.dumps(v13_obj, sort_keys=True, default=list).encode()).hexdigest()[:16]
    assert v14_hash == EXPECTED_V14_HASH
    assert v13_hash == EXPECTED_V13_HASH

    if (REPO_ROOT / ".git").exists():
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", *PROTECTED_PATHS],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert proc.stdout.strip() == ""


def test_pooled_watermark_ablation_and_relative_crosslink_resolution(tmp_path: Path) -> None:
    report = cr.audit_carbon_roles(REPO_ROOT)
    mm_sum = report["multimodal_summary"]
    pooled = mm_sum["pooled_ablation"]
    assert isinstance(pooled, dict)
    assert mm_sum["total_images"] >= 260
    assert pooled["n_episodes"] == 27
    assert pooled["n_scans"] == 140
    assert pooled["vision_exact"] == 140
    assert pooled["vision_accuracy"] == pytest.approx(1.0, abs=1e-6)
    assert pooled["multimodal_mean"] == pytest.approx(0.6263, abs=1e-4)
    assert pooled["multimodal_ci"] == pytest.approx(0.0724, abs=1e-4)
    assert pooled["blind_mean"] == pytest.approx(0.1822, abs=1e-4)
    assert pooled["blind_ci"] == pytest.approx(0.0978, abs=1e-4)
    assert pooled["paired_diff"] == pytest.approx(0.4441, abs=1e-4)
    assert pooled["diff_ci"] == pytest.approx(0.1219, abs=1e-4)
    assert pooled["oracle_recovery"] == pytest.approx(1.0, abs=1e-6)

    roles_md = ROLES_MD_PATH.read_text(encoding="utf-8")
    sub_md = SIX_ROLES_SUBMISSION_MD_PATH.read_text(encoding="utf-8")
    pitch_md = PITCH_SIX_ROLES_MD_PATH.read_text(encoding="utf-8")

    for doc_txt in (roles_md, sub_md, pitch_md):
        assert "n=27" in doc_txt
        assert "140" in doc_txt
        assert "+0.6263" in doc_txt
        assert "+0.1822" in doc_txt
        assert "+0.4441 +/- 0.1219" in doc_txt
        assert "100.0%" in doc_txt

    broken_doc_path = tmp_path / "pitch" / "BROKEN.md"
    broken_doc_path.parent.mkdir(parents=True, exist_ok=True)
    broken_md = "See [missing](../docs/gemini/DOES_NOT_EXIST.md) for details.\n"
    broken_doc_path.write_text(broken_md, encoding="utf-8")
    with pytest.raises(AssertionError, match="Unresolved markdown link"):
        _resolve_doc_crosslinks(broken_doc_path, broken_md, tmp_path)

    broken_code_md = "Main overview: `docs/gemini/MISSING_SUBMISSION.md`.\n"
    with pytest.raises(AssertionError, match="Unresolved file reference"):
        _resolve_doc_crosslinks(broken_doc_path, broken_code_md, tmp_path)


def test_self_code_hygiene_zero_comments_and_zero_unicode_dashes() -> None:
    for py_path in (SELF_TEST_PATH, CARBON_ROLES_PY_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"Forbidden literal hash character in {py_path}"
        for dash in FORBIDDEN_UNICODE_DASHES:
            assert dash not in src, f"Forbidden unicode dash U+{ord(dash):04X} in {py_path}"
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in toks if tok.type == tokenize.COMMENT]
        assert comments == [], f"Comment tokens found in {py_path}: {comments}"
        assert cr.scan_file_hygiene(py_path, REPO_ROOT) == []

    env = dict(os.environ)
    for var in API_KEY_ENV_VARS:
        env[var] = ""
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.carbon_roles", "--root", str(REPO_ROOT), "--check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok=True" in proc.stdout
