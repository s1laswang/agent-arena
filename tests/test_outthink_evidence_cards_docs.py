from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "demo" / "EVIDENCE_CARDS.md"
JS_PATH = ROOT / "demo" / "out-think-gemini" / "evidence_cards.js"

UNICODE_DASH_CODES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
HASH_CHAR = chr(35)
EMP_ID_RE = re.compile(r"\be\d{2}\b")


def _extract_bundle_from_js(js_text: str) -> dict[str, Any]:
    marker = "_w.OUTTHINK_EVIDENCE_CARDS"
    idx = js_text.find(marker)
    assert idx != -1, "Missing _w.OUTTHINK_EVIDENCE_CARDS in evidence_cards.js"
    start = js_text.find("{", idx)
    assert start != -1, "Missing opening brace for _w.OUTTHINK_EVIDENCE_CARDS"
    depth = 0
    in_str: str | None = None
    i = start
    n = len(js_text)
    while i < n:
        ch = js_text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(js_text[start : i + 1])
                assert isinstance(parsed, dict)
                return parsed
        i += 1
    raise AssertionError("Unbalanced braces in evidence_cards.js")


def _split_md_row(line: str) -> list[str]:
    inner = line.strip()
    assert inner.startswith("|") and inner.endswith("|"), f"Not a table row: {line!r}"
    parts = re.split(r"(?<!\\)\|", inner[1:-1])
    return [p.replace("\\|", "|").strip() for p in parts]


def _clean_cell(cell: str) -> str:
    val = cell.strip()
    val = re.sub(r"^`+|`+$", "", val).strip()
    val = re.sub(r"^\*\*+|\*\*+$", "", val).strip()
    return val


def _parse_int(cell: str) -> int:
    return int(_clean_cell(cell).replace(",", ""))


def _parse_usd(cell: str) -> float:
    cleaned = _clean_cell(cell)
    assert cleaned.startswith("$"), f"Expected USD cell starting with $: {cell!r}"
    return float(cleaned[1:].replace(",", ""))


def _parse_markdown_sections(md_text: str) -> dict[str, str]:
    h2_prefix = HASH_CHAR * 2 + " "
    sections: dict[str, str] = {}
    current_title = "_preamble"
    buf: list[str] = []
    for line in md_text.splitlines():
        if line.startswith(h2_prefix):
            sections[current_title] = "\n".join(buf)
            current_title = line[len(h2_prefix) :].strip()
            buf = []
        else:
            buf.append(line)
    sections[current_title] = "\n".join(buf)
    return sections


def _parse_first_table(section_body: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln.strip() for ln in section_body.splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 3, f"Expected markdown table with >= 3 lines, got {len(lines)}"
    headers = [_clean_cell(c) for c in _split_md_row(lines[0])]
    assert re.match(r"^\|[\s:|-]+\|$", lines[1]), f"Malformed separator row: {lines[1]!r}"
    rows = [_split_md_row(ln) for ln in lines[2:]]
    for row in rows:
        assert len(row) == len(headers), f"Row column count {len(row)} != {len(headers)}: {row!r}"
    return headers, rows


def _extract_js_helper_signatures(js_text: str) -> list[str]:
    pattern = re.compile(r"(?m)^_w\.([A-Za-z0-9_]+)\s*=\s*function\(([^)]*)\)\s*\{")
    return [f"{m.group(1)}({m.group(2).strip()})" for m in pattern.finditer(js_text)]


def _resolve_js_runtime() -> tuple[list[str], dict[str, str]] | None:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENERATIVE_AI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ]
    for cand in candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    return None


def validate_evidence_cards_doc_against_js(md_text: str, js_text: str) -> None:
    assert md_text.strip(), "EVIDENCE_CARDS.md is empty"
    for code in UNICODE_DASH_CODES:
        assert chr(code) not in md_text, f"Unicode dash U+{code:04X} found in EVIDENCE_CARDS.md"
    lower_md = md_text.lower()
    assert "&mdash;" not in lower_md and "&ndash;" not in lower_md, "HTML dash entity found in EVIDENCE_CARDS.md"
    for line_idx, ch in enumerate(md_text):
        assert ch == "\n" or (32 <= ord(ch) <= 126), f"Non-ASCII char {ch!r} at index {line_idx} in EVIDENCE_CARDS.md"

    bundle = _extract_bundle_from_js(js_text)
    summary = bundle["summary"]
    by_mod = summary["by_modality"]
    by_world = bundle["by_world"]
    runs = bundle["runs"]
    cards = bundle["cards"]
    stations = bundle["room_stations"]

    sections = _parse_markdown_sections(md_text)
    rollup_key = next((k for k in sections if k.startswith("Bundle Rollup")), None)
    assert rollup_key is not None, "Missing Bundle Rollup section"
    rollup_body = sections[rollup_key]

    assert f"schema_version = {bundle['schema_version']}" in rollup_body
    assert f'role = "{bundle["role"]}"' in rollup_body
    assert f'model_id = "{bundle["model_id"]}"' in rollup_body
    assert bundle["part_ingestion"] in rollup_body

    v14_card_count = sum(1 for c in cards if c["tiers_version"] == "v1.4")
    v13_card_count = sum(1 for c in cards if c["tiers_version"] == "v1.3")
    assert f"`{summary['total_runs']}` runs" in rollup_body
    assert f"`{summary['total_cards']}` cards" in rollup_body
    assert f"`{v14_card_count}` on `v1.4`" in rollup_body
    assert f"`{v13_card_count}` historical `v1.3`" in rollup_body
    assert f"`{summary['total_vision_calls']}` vision API calls" in rollup_body
    assert f"`{summary['total_images_read']}` PNGs read" in rollup_body
    assert f"`${summary['total_cost_usd']:.6f}` USD" in rollup_body

    tok = summary["total_tokens"]
    assert f"`{tok['in']:,}` input (`in`)" in rollup_body
    assert f"`{tok['out']:,}` output (`out`)" in rollup_body
    assert f"`{tok['thinking']:,}` thinking (`thinking`)" in rollup_body
    assert f"`{tok['cached']:,}` cached (`cached`)" in rollup_body

    med_worlds = [wk for wk in by_world if wk.startswith("medium/")]
    hard_worlds = [wk for wk in by_world if wk.startswith("hard/")]
    assert (
        f"`{summary['worlds_covered_v14']}` `v1.4` worlds (`{len(med_worlds)}` medium + `{len(hard_worlds)}` hard)"
        in rollup_body
    )

    mod_sec_key = next((k for k in sections if k.startswith("Four Modalities")), None)
    assert mod_sec_key is not None, "Missing Four Modalities section"
    _, mod_rows = _parse_first_table(sections[mod_sec_key])
    assert len(mod_rows) == 5, f"Expected 4 modality rows + 1 Total row, got {len(mod_rows)}"

    stations_by_mod = {s["modality"]: s for s in stations}
    seen_mods: list[str] = []
    sum_runs = sum_cards = sum_calls = sum_pngs = sum_in = sum_out = sum_think = 0
    sum_cost = 0.0

    for row in mod_rows[:4]:
        mod = _clean_cell(row[0])
        seen_mods.append(mod)
        assert mod in by_mod, f"Unknown modality {mod!r}"
        st = stations_by_mod[mod]
        ms = by_mod[mod]
        mod_runs = [r for r in runs if r["modality"] == mod]

        assert _clean_cell(row[1]) == st["station_id"]
        expected_sprites = (
            f"`{st['prop_sprite']}` / `{st['icon_sprite']}` / `{st['analyst_sprite']}` / `{st['badge_sprite']}`"
        )
        assert row[2].strip() == expected_sprites

        r_cnt = _parse_int(row[3])
        c_cnt = _parse_int(row[4])
        call_cnt = _parse_int(row[5])
        png_cnt = _parse_int(row[6])
        in_cnt = _parse_int(row[7])
        out_cnt = _parse_int(row[8])
        th_cnt = _parse_int(row[9])
        cost_val = _parse_usd(row[10])
        metrics_txt = row[11]

        assert r_cnt == ms["runs"] == len(mod_runs)
        assert c_cnt == ms["cards"] == st["card_count"] == len(bundle["by_modality"][mod])
        assert call_cnt == sum(int(r["usage"]["calls"]) for r in mod_runs)
        assert png_cnt == ms["images_read"] == st["images_read"]
        assert in_cnt == sum(int(r["usage"]["in"]) for r in mod_runs)
        assert out_cnt == sum(int(r["usage"]["out"]) for r in mod_runs)
        assert th_cnt == sum(int(r["usage"]["thinking"]) for r in mod_runs)
        assert cost_val == pytest.approx(float(ms["cost_usd"]), abs=1e-6)

        if mod == "scan":
            assert f"`{ms['canary_memos_decoded']}/{ms['canary_memos_decoded']}`" in metrics_txt
            assert f"`{ms['multimodal_mole_hits']}/{ms['cards']}`" in metrics_txt
            assert f"`{ms['blind_mole_hits']}/{ms['cards']}` (`{ms['blind_mole_accuracy']}`)" in metrics_txt
        elif mod == "heatmap":
            assert f"`{ms['top1_mole_hits']}/{ms['cards']}` (`{ms['top1_mole_accuracy']}`)" in metrics_txt
            assert f"`{ms['top3_mole_hits']}/{ms['cards']}`" in metrics_txt
            assert f"`0/{ms['cards']}`" in metrics_txt
        elif mod == "dossier":
            assert f"`{ms['images_per_call']}` PNGs per call" in metrics_txt
            assert f"`{ms['memo_scans_matched']}/{ms['memo_scans_total']}`" in metrics_txt
            assert f"`{ms['top1_mole_hits']}/{ms['cards']}` (`{ms['top1_mole_accuracy']}`)" in metrics_txt
            assert f"`{ms['top3_mole_hits']}/{ms['cards']}` (`{ms['top3_mole_hit_rate']}`)" in metrics_txt
            assert f"`{ms['avoided_framing_trap_hits']}/{ms['cards']}`" in metrics_txt
        elif mod == "forensics":
            assert f"`{ms['visual_threshold_hits']}/{ms['cards']}`" in metrics_txt
            assert f"`{ms['accuse_day_exact_hits']}/{ms['cards']}`" in metrics_txt
            assert f"`{ms['hidden_bleed_gap_hits']}/{ms['cards']}`" in metrics_txt

        sum_runs += r_cnt
        sum_cards += c_cnt
        sum_calls += call_cnt
        sum_pngs += png_cnt
        sum_in += in_cnt
        sum_out += out_cnt
        sum_think += th_cnt
        sum_cost += cost_val

    assert seen_mods == ["scan", "heatmap", "dossier", "forensics"]

    tot_row = mod_rows[4]
    assert _clean_cell(tot_row[0]) == "Total"
    assert _parse_int(tot_row[3]) == sum_runs == summary["total_runs"]
    assert _parse_int(tot_row[4]) == sum_cards == summary["total_cards"]
    assert _parse_int(tot_row[5]) == sum_calls == summary["total_vision_calls"]
    assert _parse_int(tot_row[6]) == sum_pngs == summary["total_images_read"]
    assert _parse_int(tot_row[7]) == sum_in == tok["in"]
    assert _parse_int(tot_row[8]) == sum_out == tok["out"]
    assert _parse_int(tot_row[9]) == sum_think == tok["thinking"]
    assert _parse_usd(tot_row[10]) == pytest.approx(sum_cost, abs=1e-6)
    assert _parse_usd(tot_row[10]) == pytest.approx(float(summary["total_cost_usd"]), abs=1e-6)

    runs_sec_key = next((k for k in sections if k.startswith("Verified Run Ledger")), None)
    assert runs_sec_key is not None, "Missing Verified Run Ledger section"
    _, run_rows = _parse_first_table(sections[runs_sec_key])
    assert len(run_rows) == len(runs) == 17
    for r_row, r_obj in zip(run_rows, runs, strict=True):
        assert _clean_cell(r_row[0]) == r_obj["run_dir"]
        assert _clean_cell(r_row[1]) == r_obj["modality"]
        assert _clean_cell(r_row[2]) == r_obj["tiers_version"]
        assert _clean_cell(r_row[3]) == r_obj["thinking_level"]
        assert _parse_int(r_row[4]) == r_obj["n_cards"]
        assert _parse_int(r_row[5]) == r_obj["n_images_read"]
        assert _parse_int(r_row[6]) == r_obj["usage"]["calls"]
        assert _parse_usd(r_row[7]) == pytest.approx(float(r_obj["usage"]["cost_usd"]), abs=1e-6)
        commit_prefix = _clean_cell(r_row[8])
        assert len(commit_prefix) == 8 and r_obj["commit"].startswith(commit_prefix)

    world_sec_key = next((k for k in sections if k.startswith("World Coverage")), None)
    assert world_sec_key is not None, "Missing World Coverage section"
    world_body = sections[world_sec_key]

    med_match = re.search(r"Medium Keys \(`(\d+)`\):\*\*\s*(.+)", world_body)
    hard_match = re.search(r"Hard Keys \(`(\d+)`\):\*\*\s*(.+)", world_body)
    assert med_match is not None and hard_match is not None
    doc_med_keys = re.findall(r"`(medium/\d+)`", med_match.group(2))
    doc_hard_keys = re.findall(r"`(hard/\d+)`", hard_match.group(2))
    assert int(med_match.group(1)) == len(doc_med_keys) == len(med_worlds)
    assert int(hard_match.group(1)) == len(doc_hard_keys) == len(hard_worlds)
    assert doc_med_keys + doc_hard_keys == list(by_world.keys())

    for mod in ("scan", "heatmap", "dossier", "forensics"):
        w_cnt = sum(1 for w in by_world.values() if mod in w["modalities"])
        c_v14 = sum(len(w["cards_by_modality"].get(mod, [])) for w in by_world.values())
        assert f"`{mod}` (`{w_cnt}`" in world_body
        assert f"`{c_v14}` `v1.4` cards)" in world_body

    four_match = re.search(r"4 modalities \(`(\d+)` worlds\):\*\*\s*(.+)", world_body)
    three_match = re.search(r"3 modalities \(`(\d+)` worlds\):\*\*\s*(.+)", world_body)
    two_match = re.search(r"2 modalities \(`(\d+)` world\):\*\*\s*(.+)", world_body)
    one_match = re.search(r"1 modality \(`(\d+)` worlds\):\*\*\s*(.+)", world_body)
    assert four_match and three_match and two_match and one_match

    doc_4 = re.findall(r"`((?:medium|hard)/\d+)`", four_match.group(2))
    doc_3 = re.findall(r"`((?:medium|hard)/\d+)`", three_match.group(2))
    doc_2 = re.findall(r"`((?:medium|hard)/\d+)`", two_match.group(2))
    doc_1 = re.findall(r"`((?:medium|hard)/\d+)`", one_match.group(2))

    assert int(four_match.group(1)) == len(doc_4)
    assert int(three_match.group(1)) == len(doc_3)
    assert int(two_match.group(1)) == len(doc_2)
    assert int(one_match.group(1)) == len(doc_1)

    assert set(doc_4) == {wk for wk, w in by_world.items() if len(w["modalities"]) == 4}
    assert set(doc_3) == {wk for wk, w in by_world.items() if len(w["modalities"]) == 3}
    assert set(doc_2) == {wk for wk, w in by_world.items() if len(w["modalities"]) == 2}
    assert set(doc_1) == {wk for wk, w in by_world.items() if len(w["modalities"]) == 1}

    cmp_sec_key = next((k for k in sections if k.startswith("Paired Low-vs-High")), None)
    assert cmp_sec_key is not None, "Missing Paired Low-vs-High Thinking Comparison section"
    cmp_body = sections[cmp_sec_key]

    low_run = next(r for r in runs if r["run_dir"] == "access-heatmap-v14-low-s8to11-carbon")
    high_run = next(r for r in runs if r["run_dir"] == "access-heatmap-v14-high-s8to11-carbon")
    assert low_run["commit"] == high_run["commit"]
    assert f"`{low_run['commit']}`" in cmp_body

    cal = by_mod["heatmap"]["thinking_calibration"]
    assert f"`{cal['low_thinking_tokens']:,}` thinking tokens" in cmp_body
    assert f"`{cal['high_thinking_tokens']:,}` thinking tokens" in cmp_body
    assert f"`${low_run['usage']['cost_usd']:.6f}` USD" in cmp_body
    assert f"`${high_run['usage']['cost_usd']:.6f}` USD" in cmp_body
    assert f"Brier `{cal['low_brier_score']:.6f}`" in cmp_body
    assert f"Brier `{cal['high_brier_score']:.6f}`" in cmp_body
    assert f"ECE `{cal['low_ece']:.6f}`" in cmp_body
    assert f"ECE `{cal['high_ece']:.6f}`" in cmp_body

    _, cmp_rows = _parse_first_table(cmp_body)
    paired_worlds = [wk for wk, w in by_world.items() if w["thinking_comparison"] is not None]
    assert len(cmp_rows) == len(paired_worlds) == 6
    cards_by_id = {c["card_id"]: c for c in cards}

    for c_row, wk in zip(cmp_rows, paired_worlds, strict=True):
        w = by_world[wk]
        tc = w["thinking_comparison"]
        lc = cards_by_id[tc["low_card_id"]]
        hc = cards_by_id[tc["high_card_id"]]
        assert _clean_cell(c_row[0]) == wk
        assert _clean_cell(c_row[1]) == w["true_mole"]
        assert _clean_cell(c_row[2]) == w["true_decoy"]
        assert _parse_int(c_row[3]) == tc["low_thinking_tokens"]
        assert _parse_int(c_row[4]) == tc["high_thinking_tokens"]
        assert float(_clean_cell(c_row[5])) == pytest.approx(float(tc["low_confidence"]), abs=1e-6)
        assert float(_clean_cell(c_row[6])) == pytest.approx(float(tc["high_confidence"]), abs=1e-6)
        assert float(_clean_cell(c_row[7])) == pytest.approx(float(tc["low_brier_score"]), abs=1e-6)
        assert float(_clean_cell(c_row[8])) == pytest.approx(float(tc["high_brier_score"]), abs=1e-6)
        assert _parse_usd(c_row[9]) == pytest.approx(float(lc["usage"]["cost_usd"]), abs=1e-6)
        assert _parse_usd(c_row[10]) == pytest.approx(float(hc["usage"]["cost_usd"]), abs=1e-6)

    help_sec_key = next((k for k in sections if k.startswith("Helper Functions")), None)
    assert help_sec_key is not None, "Missing Helper Functions section"
    _, help_rows = _parse_first_table(sections[help_sec_key])
    doc_sigs = [_clean_cell(r[0]) for r in help_rows]
    js_sigs = _extract_js_helper_signatures(js_text)
    assert doc_sigs == js_sigs == [
        "getOutthinkEvidenceCard(cardId)",
        "getOutthinkWorldEvidence(caseOrTier, seed)",
        "getOutthinkEvidenceForCase(caseOrTier, seed, modality)",
        "listOutthinkEvidenceCards(filter)",
        "listOutthinkEvidenceStations()",
    ]
    for sig in js_sigs:
        fn_name = sig.split("(", 1)[0]
        assert f"globalThis.{fn_name} = _w.{fn_name};" in js_text
        assert f"{fn_name}: _w.{fn_name}" in js_text


def test_doc_and_test_ascii_dash_and_comment_hygiene() -> None:
    assert DOC_PATH.is_file(), f"Missing {DOC_PATH}"
    md_text = DOC_PATH.read_text(encoding="utf-8")
    for code in UNICODE_DASH_CODES:
        assert chr(code) not in md_text, f"Unicode dash U+{code:04X} found in EVIDENCE_CARDS.md"
    for ch in md_text:
        assert ch == "\n" or (32 <= ord(ch) <= 126), f"Non-ASCII character {ch!r} in EVIDENCE_CARDS.md"

    self_path = Path(__file__).resolve()
    py_src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in py_src, "Hash character found in test_outthink_evidence_cards_docs.py"
    for code in UNICODE_DASH_CODES:
        assert chr(code) not in py_src, f"Unicode dash U+{code:04X} found in {self_path.name}"

    tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"Python comments found in {self_path.name}: {comments}"

    tree = ast.parse(py_src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib", "socket", "aiohttp")
    for mod in imported:
        assert not any(f in mod for f in forbidden), f"Forbidden module {mod!r} imported in {self_path.name}"


def test_all_documented_numbers_worlds_runs_and_helpers_match_live_js() -> None:
    md_text = DOC_PATH.read_text(encoding="utf-8")
    js_text = JS_PATH.read_text(encoding="utf-8")
    validate_evidence_cards_doc_against_js(md_text, js_text)


def test_helper_functions_execute_every_documented_input_shape() -> None:
    rt = _resolve_js_runtime()
    if rt is None:
        pytest.skip("No local JS runtime available")
    cmd_prefix, env = rt
    run_env = dict(env)
    run_env["OUTTHINK_EVIDENCE_JS"] = str(JS_PATH)
    script = (
        "globalThis.window = {};\n"
        "const mod = require(process.env.OUTTHINK_EVIDENCE_JS);\n"
        "const card = mod.getOutthinkEvidenceCard('  scan:scanned-evidence-ablation-carbon:medium:0  ');\n"
        "const missingCard = mod.getOutthinkEvidenceCard('nonexistent');\n"
        "const nonStrCard = mod.getOutthinkEvidenceCard(42);\n"
        "const wPair = mod.getOutthinkWorldEvidence('hard', 8);\n"
        "const wSlash = window.getOutthinkWorldEvidence('medium/3');\n"
        "const wPipe = globalThis.getOutthinkWorldEvidence('medium|3');\n"
        "const wUnder = mod.getOutthinkWorldEvidence('medium_3');\n"
        "const wDash = mod.getOutthinkWorldEvidence('medium-3');\n"
        "const wPath = mod.getOutthinkWorldEvidence('gemini-4-carbon/high/hard/8');\n"
        "const wObjKey = mod.getOutthinkWorldEvidence({ world_key: 'hard/9' });\n"
        "const wObjTier = mod.getOutthinkWorldEvidence({ tier: 'MEDIUM', seed: 3 });\n"
        "const wObjDiff = mod.getOutthinkWorldEvidence({ difficulty: 'HARD', worldSeed: 8 });\n"
        "const wObjId = mod.getOutthinkWorldEvidence({ id: 'case/hard/9' });\n"
        "const cWorldDefault = mod.getOutthinkEvidenceForCase('hard', 9);\n"
        "const cHeatPrimary = mod.getOutthinkEvidenceForCase('hard', 9, 'HEATMAP');\n"
        "const cMissingMod = mod.getOutthinkEvidenceForCase('hard', 12, 'dossier');\n"
        "const allCards = mod.listOutthinkEvidenceCards();\n"
        "const v13Cards = mod.listOutthinkEvidenceCards({ run_dir: 'belief-chart-forensics-carbon' });\n"
        "const lowHeatHard = mod.listOutthinkEvidenceCards({ modality: 'heatmap', tier: 'hard', seed: '9', thinking_level: 'LOW' });\n"
        "const stations = mod.listOutthinkEvidenceStations();\n"
        "stations.pop();\n"
        "const stationsAgain = window.listOutthinkEvidenceStations();\n"
        "process.stdout.write(JSON.stringify({\n"
        "  cardMole: card.finding.predicted_mole,\n"
        "  missingCard: missingCard,\n"
        "  nonStrCard: nonStrCard,\n"
        "  med3Equal: wSlash === wPipe && wPipe === wUnder && wUnder === wDash && wDash === wObjTier,\n"
        "  hard8Equal: wPair === wPath && wPath === wObjDiff,\n"
        "  hard9Equal: wObjKey === wObjId && wObjId === cWorldDefault,\n"
        "  primaryThinking: cHeatPrimary.thinking_level,\n"
        "  cMissingMod: cMissingMod,\n"
        "  allLen: allCards.length,\n"
        "  v13Len: v13Cards.length,\n"
        "  lowHeatHardId: lowHeatHard.length === 1 ? lowHeatHard[0].card_id : null,\n"
        "  stationsCopySafe: stationsAgain.length === 4\n"
        "}));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, script],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS execution failed: {proc.stderr}"
    res = json.loads(proc.stdout)
    assert res == {
        "cardMole": "e05",
        "missingCard": None,
        "nonStrCard": None,
        "med3Equal": True,
        "hard8Equal": True,
        "hard9Equal": True,
        "primaryThinking": "high",
        "cMissingMod": None,
        "allLen": 100,
        "v13Len": 6,
        "lowHeatHardId": "heatmap:access-heatmap-v14-low-s8to11-carbon:hard:9",
        "stationsCopySafe": True,
    }


def test_pre_decision_vs_post_reveal_field_partition_and_spoiler_isolation() -> None:
    md_text = DOC_PATH.read_text(encoding="utf-8")
    js_text = JS_PATH.read_text(encoding="utf-8")
    bundle = _extract_bundle_from_js(js_text)

    sections = _parse_markdown_sections(md_text)
    spoiler_sec_key = next((k for k in sections if k.startswith("Pre-Decision vs Post-Reveal")), None)
    assert spoiler_sec_key is not None, "Missing Pre-Decision vs Post-Reveal section"
    spoiler_body = sections[spoiler_sec_key]
    _, spoiler_rows = _parse_first_table(spoiler_body)

    pre_text = " ".join(r[2] for r in spoiler_rows if "Pre-Decision" in r[0])
    post_text = " ".join(r[2] for r in spoiler_rows if "Post-Reveal" in r[0])
    assert pre_text and post_text

    strictly_post_reveal_tokens = (
        "true_mole",
        "true_decoy",
        "predicted_mole",
        "top_suspect_ids",
        "predicted_decoy",
        "suspected_decoy_ids",
        "suspect_department",
        "naive_trapped_id",
        "image1_only_trap_pick",
        "headline",
        "gemini_quote",
        "ablation",
        "brier_score",
        "mole_correct",
        "decoy_correct",
        "expected_variant",
        "exact_match",
    )
    for tok in strictly_post_reveal_tokens:
        assert not re.search(rf"\b{re.escape(tok)}\b", pre_text), f"Spoiler field {tok!r} listed in Pre-Decision row"
        assert re.search(rf"\b{re.escape(tok)}\b", post_text), f"Spoiler field {tok!r} missing from Post-Reveal row"

    for card in bundle["cards"]:
        for key in card:
            if key in ("finding", "ground_truth", "images"):
                continue
            assert re.search(rf"\b{re.escape(key)}\b", spoiler_body), f"Card key {key!r} missing from spoiler table"
        for gt_key in card["ground_truth"]:
            assert re.search(rf"\b{re.escape(gt_key)}\b", post_text), f"ground_truth.{gt_key} missing from Post-Reveal"
        for find_key in card["finding"]:
            assert re.search(rf"\b{re.escape(find_key)}\b", spoiler_body), f"finding.{find_key} missing from spoiler table"
        for img in card["images"]:
            for img_key in img:
                assert re.search(rf"\b{re.escape(img_key)}\b", spoiler_body), f"images[].{img_key} missing from spoiler table"

    for st in bundle["room_stations"]:
        for k, v in st.items():
            assert not EMP_ID_RE.search(str(v)), f"Employee ID leaked in room_stations.{k}: {v!r}"

    pre_card_scalar_keys = (
        "card_id",
        "modality",
        "subrole",
        "station_id",
        "sprite_key",
        "prop_sprite_key",
        "analyst_sprite_key",
        "tier",
        "world_key",
        "pipe_key",
        "tiers_version",
        "model_id",
        "thinking_level",
        "run_dir",
        "ledger_run_id",
        "commit",
        "timestamp",
    )
    for card in bundle["cards"]:
        for k in pre_card_scalar_keys:
            assert not EMP_ID_RE.search(str(card[k])), f"Employee ID leaked in card.{k}: {card[k]!r}"
        assert not EMP_ID_RE.search(str(card["finding"]["title"])), (
            f"Employee ID leaked in finding.title: {card['finding']['title']!r}"
        )
        for img in card["images"]:
            for ik in ("kind", "path", "sha256", "bytes", "size", "doc_id", "day_surfaced", "predicted_variant"):
                if ik in img and img[ik] is not None:
                    assert not EMP_ID_RE.search(str(img[ik])), f"Employee ID leaked in images[].{ik}: {img[ik]!r}"
        if "decoded_watermarks" in card["finding"]:
            assert not EMP_ID_RE.search(json.dumps(card["finding"]["decoded_watermarks"]))
        if "decoded_leaked_canaries" in card["finding"]:
            assert not EMP_ID_RE.search(json.dumps(card["finding"]["decoded_leaked_canaries"]))


@pytest.mark.parametrize(
    ("mutator",),
    [
        (lambda s: s.replace("`17` runs", "`18` runs", 1),),
        (lambda s: s.replace("`100` cards", "`99` cards", 1),),
        (lambda s: s.replace("`260` PNGs read", "`259` PNGs read", 1),),
        (lambda s: s.replace("$3.521048", "$3.521049", 1),),
        (lambda s: s.replace("`hard/14`", "`hard/15`", 1),),
        (lambda s: s.replace("0.012100", "0.012200", 1),),
        (lambda s: s.replace("getOutthinkEvidenceForCase(caseOrTier, seed, modality)", "getOutthinkEvidenceForCase(caseOrTier, seed)", 1),),
        (lambda s: s + "\nForbidden dash " + chr(0x2014) + "\n",),
    ],
)
def test_doc_validator_rejects_drifted_claims_and_unicode_dashes(mutator: Any) -> None:
    md_text = DOC_PATH.read_text(encoding="utf-8")
    js_text = JS_PATH.read_text(encoding="utf-8")
    corrupted_md = mutator(md_text)
    assert corrupted_md != md_text
    with pytest.raises(AssertionError):
        validate_evidence_cards_doc_against_js(corrupted_md, js_text)
