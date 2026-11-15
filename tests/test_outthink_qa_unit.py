"""Keyless, airgapped unit tests for canary.gemini.outthink_qa."""
from __future__ import annotations

import ast
import base64
import gzip
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tokenize
from typing import Any
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import outthink_qa as qa

QA_MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_qa.py"
SELF_TEST_PATH = Path(__file__).resolve()
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"
HASH_CHAR = chr(35)
SLASH_CHAR = chr(47)
STAR_CHAR = chr(42)


@pytest.fixture(autouse=True)
def _airgap_network_and_strip_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key_name in qa.API_KEY_ENV_VARS:
        monkeypatch.delenv(key_name, raising=False)

    def _blocked_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("OfflineGuardError: network socket creation is forbidden in outthink_qa unit tests")

    def _blocked_connect(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("OfflineGuardError: network connection is forbidden in outthink_qa unit tests")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_connect)


@pytest.fixture(scope="module")
def committed_gt() -> dict[str, Any]:
    return qa.load_ladder_ground_truth(ROOT)


def _make_png_bytes(width: int = 4, height: int = 4, rgba: tuple[int, int, int, int] = (24, 160, 220, 255)) -> bytes:
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + bytes(rgba) * width
    raw_scanlines = row * height
    idat = zlib.compress(raw_scanlines, level=6)
    return qa.PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _make_minimal_engine_js() -> str:
    return (
        "(function (root) {\n"
        "  function computeBreakEvenProb(v, solver) {\n"
        "    const val = Number(v || 0);\n"
        "    const hold = solver && Number(solver.ev_hold_fire) > 0 ? Number(solver.ev_hold_fire) : 0;\n"
        "    if (val <= 0) return 1.0;\n"
        "    return Math.min(1.0, Math.max(0.0, (1.0 + hold) / (1.0 + val)));\n"
        "  }\n"
        "  function computeAccusationEv(p, v) {\n"
        "    const prob = Number(p || 0);\n"
        "    const val = Number(v || 0);\n"
        "    return prob * val - (1.0 - prob);\n"
        "  }\n"
        "  function normalizeCase(raw) {\n"
        "    return Object.assign({ suspects: [], thinking_levels: [] }, raw || {});\n"
        "  }\n"
        "  function loadDataset(input) {\n"
        "    const src = (input && input.cases) ? input.cases : [];\n"
        "    const cases = src.map(normalizeCase);\n"
        "    return { cases: cases, count: cases.length };\n"
        "  }\n"
        "  function evaluateCall(caseObj, call) {\n"
        "    const act = call && call.action ? String(call.action) : 'hold_fire';\n"
        "    if (act === 'accuse') {\n"
        "      const hit = String(call.suspectId || '') === String(caseObj.true_mole || '');\n"
        "      return { action: 'accuse', correct: hit, score: hit ? Number(caseObj.value_at_decision) : -1.0 };\n"
        "    }\n"
        "    return { action: 'hold_fire', correct: false, score: 0.0 };\n"
        "  }\n"
        "  function createScoreboard() {\n"
        "    const seen = Object.create(null);\n"
        "    return {\n"
        "      record: function (id, res) { seen[String(id)] = res; },\n"
        "      getSummary: function () { return { casesPlayed: Object.keys(seen).length }; },\n"
        "      reset: function () { for (const k of Object.keys(seen)) delete seen[k]; }\n"
        "    };\n"
        "  }\n"
        "  const api = {\n"
        "    computeBreakEvenProb: computeBreakEvenProb,\n"
        "    computeAccusationEv: computeAccusationEv,\n"
        "    normalizeCase: normalizeCase,\n"
        "    loadDataset: loadDataset,\n"
        "    evaluateCall: evaluateCall,\n"
        "    createScoreboard: createScoreboard\n"
        "  };\n"
        "  if (typeof module !== 'undefined' && module.exports) module.exports = api;\n"
        "  if (root) root.OutThinkEngine = api;\n"
        "})(typeof globalThis !== 'undefined' ? globalThis : this);\n"
    )


def _load_protected_rules() -> list[str]:
    assert PROTECTED_PATHS_FILE.is_file()
    rules: list[str] = []
    for raw in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        rules.append(line)
    return rules


def _is_protected(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/"):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def test_outthink_qa_source_hygiene_and_protected_paths() -> None:
    for target in (QA_MODULE_PATH, SELF_TEST_PATH):
        assert target.is_file()
        src = target.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"Forbidden comment character found in {target}"
        assert qa.find_forbidden_dashes(src) == [], f"Forbidden dash found in {target}"
        comments = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == []

        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden_mod in ("genai", "google", "openai", "anthropic"):
                        assert forbidden_mod not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for forbidden_mod in ("genai", "google", "openai", "anthropic"):
                    assert forbidden_mod not in node.module

    rules = _load_protected_rules()
    assert rules
    for target in (QA_MODULE_PATH, SELF_TEST_PATH):
        rel = target.relative_to(ROOT).as_posix()
        assert not _is_protected(rel, rules), f"Protected path touched: {rel}"


def test_find_forbidden_dashes() -> None:
    assert qa.find_forbidden_dashes("plain-ascii-hyphen and minus -1.0") == []
    for cp in qa.FORBIDDEN_DASH_CODEPOINTS:
        hits = qa.find_forbidden_dashes(f"prefix {chr(cp)} suffix")
        assert hits == [f"U+{cp:04X}"]


def test_validate_png_bytes_valid_and_corrupt_cases() -> None:
    valid_png = _make_png_bytes(width=6, height=3)
    meta = qa.validate_png_bytes(valid_png)
    assert meta["width"] == 6
    assert meta["height"] == 3
    assert meta["bit_depth"] == 8
    assert meta["color_type"] == 6
    assert meta["bytes"] == len(valid_png)

    with pytest.raises(ValueError, match="too short"):
        qa.validate_png_bytes(b"\x89PNG\r\n\x1a\nshort")

    with pytest.raises(ValueError, match="8-byte signature"):
        qa.validate_png_bytes(b"NOTAPNG!" + valid_png[8:])

    bad_crc = bytearray(valid_png)
    bad_crc[28] ^= 0xFF
    with pytest.raises(ValueError, match="CRC mismatch"):
        qa.validate_png_bytes(bytes(bad_crc))

    with pytest.raises(ValueError, match="Trailing bytes"):
        qa.validate_png_bytes(valid_png + b"extra")

    corrupt_idat_data = b"not-valid-zlib"
    corrupt_idat_crc = zlib.crc32(b"IDAT" + corrupt_idat_data) & 0xFFFFFFFF
    ihdr_segment = valid_png[:33]
    iend_segment = valid_png[-12:]
    corrupt_png = (
        ihdr_segment
        + struct.pack(">I", len(corrupt_idat_data))
        + b"IDAT"
        + corrupt_idat_data
        + struct.pack(">I", corrupt_idat_crc)
        + iend_segment
    )
    with pytest.raises(ValueError, match="Corrupt PNG IDAT"):
        qa.validate_png_bytes(corrupt_png)


def test_load_ladder_ground_truth_committed_and_synthetic(
    committed_gt: dict[str, Any], tmp_path: Path
) -> None:
    episodes = committed_gt["episodes"]
    assert len(episodes) == 550
    assert len(committed_gt["by_run_id"]) == 550
    assert len(committed_gt["by_key"]) == 550
    for ep in episodes:
        assert ep["cost_usd"] > 0.0
        assert ep["model"]
        assert ep["level"]
        assert ep["tier"]

    ep_gz = tmp_path / "episodes.jsonl.gz"
    led_jsonl = tmp_path / "ledger.jsonl"
    rows = [
        {
            "accused": "e04",
            "correct": True,
            "score": 0.72,
            "final_day": 7,
            "end_reason": "accused",
            "steps": [{"day": 3, "tool": "plant_canary"}],
            "meta": {
                "valid": True,
                "ladder": {
                    "run_id": "ladder:test:gemini-4-carbon/high/hard/1",
                    "model": "gemini-4-carbon",
                    "level": "high",
                    "tier": "hard",
                    "seed": 1,
                    "tokens": {"in": 1000, "out": 200, "thinking": 500, "cached": 100, "calls": 4},
                },
            },
        },
        {
            "accused": "e01",
            "correct": False,
            "score": -1.0,
            "final_day": 5,
            "end_reason": "accused",
            "meta": {
                "valid": True,
                "ladder": {
                    "run_id": "ladder:test:dup",
                    "model": "gemini-4-carbon",
                    "level": "high",
                    "tier": "hard",
                    "seed": 1,
                },
            },
        },
        {
            "accused": None,
            "correct": False,
            "score": 0.0,
            "end_reason": "error",
            "meta": {"valid": True, "ladder": {"model": "gemini-4-carbon", "level": "low", "tier": "hard", "seed": 2}},
        },
        {
            "accused": "e02",
            "correct": False,
            "score": -1.0,
            "end_reason": "accused",
            "meta": {"valid": False, "ladder": {"model": "gemini-4-carbon", "level": "low", "tier": "hard", "seed": 3}},
        },
    ]
    with gzip.open(ep_gz, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    led_jsonl.write_text(
        json.dumps(
            {
                "run_id": "ladder:test:gemini-4-carbon/high/hard/1",
                "cost_usd": 0.4321,
                "in": 1000,
                "out": 200,
                "thinking": 500,
                "cached": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    syn_gt = qa.load_ladder_ground_truth(tmp_path, episodes_path=ep_gz, ledger_path=led_jsonl)
    assert len(syn_gt["episodes"]) == 1
    only = syn_gt["episodes"][0]
    assert only["run_id"] == "ladder:test:gemini-4-carbon/high/hard/1"
    assert only["cost_usd"] == pytest.approx(0.4321)
    assert only["ledger_calls"] == 1


def test_js_helpers_comments_network_and_json_extraction() -> None:
    line_c = SLASH_CHAR + SLASH_CHAR
    block_open = SLASH_CHAR + STAR_CHAR
    block_close = STAR_CHAR + SLASH_CHAR
    safe_js = (
        f"{line_c} fetch('https://ignored.invalid')\n"
        f"{block_open} XMLHttpRequest navigator.sendBeacon('x') {block_close}\n"
        "const label = 'https://docs.example.org/path';\n"
    )
    assert qa._find_forbidden_js_network_calls(safe_js) == []

    bad_js = (
        "function leak() { return fetch('https://api.example.org'); }\n"
        "const xhr = new XMLHttpRequest();\n"
        "navigator.sendBeacon('/ping');\n"
        "axios.post('/collect', {});\n"
    )
    hits = qa._find_forbidden_js_network_calls(bad_js)
    assert set(hits) == {"fetch()", "XMLHttpRequest", "navigator.sendBeacon()", "axios"}

    indirected = 'const PAYLOAD = {"cases": [{"id": "c1"}]};\nwindow.OUTTHINK_DATA = PAYLOAD;\n'
    parsed = qa._extract_js_global_json(indirected, ("OUTTHINK_DATA",))
    assert parsed == {"cases": [{"id": "c1"}]}

    with pytest.raises(ValueError, match="Could not parse JSON payload"):
        qa._extract_js_global_json("const UNRELATED = 42;", ("OUTTHINK_DATA",))


def test_check_static_page_offline_airgap_and_tamper_guards(tmp_path: Path) -> None:
    demo = tmp_path / "demo" / "out-think-gemini"
    demo.mkdir(parents=True)
    png_bytes = _make_png_bytes()
    b64_png = base64.b64encode(png_bytes).decode("ascii")
    (demo / "badge.png").write_bytes(png_bytes)
    (demo / "style.css").write_text("body { background: rgb(10, 14, 22); }\n", encoding="utf-8")
    (demo / "cases.js").write_text('window.OUTTHINK_DATA = {"cases": [{"id": "c1"}]};\n', encoding="utf-8")
    (demo / "engine.js").write_text(_make_minimal_engine_js(), encoding="utf-8")
    (demo / "game.js").write_text("const ready = true;\n", encoding="utf-8")
    (demo / "index.html").write_text(
        "<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body>"
        f"<img src='badge.png'><img src='data:image/png;base64,{b64_png}'>"
        "<script src='personas.js'></script>"
        "<script src='cases.js'></script>"
        "<script src='engine.js'></script>"
        "<script src='game.js'></script>"
        "</body></html>",
        encoding="utf-8",
    )

    ok_res = qa.check_static_page(tmp_path)
    assert ok_res["passed"] is True
    assert ok_res["errors"] == []
    assert ok_res["optional_missing_scripts"] == ["personas.js"]

    strict_opt = qa.check_static_page(tmp_path, allow_optional_scripts=False)
    assert strict_opt["passed"] is False
    assert any("personas.js" in e for e in strict_opt["errors"])

    bad_dir = tmp_path / "bad_demo"
    bad_dir.mkdir()
    em_dash = chr(0x2014)
    (bad_dir / "index.html").write_text(
        f"<!DOCTYPE html><html><head><link rel='stylesheet' href='/abs.css'></head><body>"
        f"<p>Bad dash {em_dash}</p>"
        "<img src='http://insecure.example.org/a.png'>"
        "<script type='module' src='mod.js'></script>"
        "<script src='../escape.js'></script>"
        "<script src='missing_core.js'></script>"
        "<script>fetch('https://leak.invalid');</script>"
        "</body></html>",
        encoding="utf-8",
    )
    (bad_dir / "mod.js").write_text("const x = 1;\n", encoding="utf-8")

    bad_res = qa.check_static_page(bad_dir)
    assert bad_res["passed"] is False
    joined = "\n".join(bad_res["errors"])
    assert "Forbidden dash" in joined
    assert "Root-relative" in joined
    assert "Non-portable" in joined
    assert "ES module script" in joined
    assert "escapes demo directory" in joined
    assert "Missing local script file 'missing_core.js'" in joined
    assert "Forbidden offline network call" in joined


def test_check_assets_and_licenses_provenance_and_tamper_guards(tmp_path: Path) -> None:
    demo = tmp_path / "demo" / "out-think-gemini"
    sprites = demo / "assets" / "sprites"
    sprites.mkdir(parents=True)
    docs_demo = tmp_path / "docs" / "demo"
    docs_demo.mkdir(parents=True)

    png_bytes = _make_png_bytes()
    b64_png = base64.b64encode(png_bytes).decode("ascii")
    (sprites / "desk.png").write_bytes(png_bytes)
    (demo / "assets" / "manifest.js").write_text(
        "window.OUTTHINK_ASSETS = "
        + json.dumps(
            {
                "version": 1,
                "sprites": {
                    "desk": "sprites/desk.png",
                    "inline_icon": f"data:image/png;base64,{b64_png}",
                },
            }
        )
        + ";\n",
        encoding="utf-8",
    )
    (demo / "index.html").write_text(
        "<!DOCTYPE html><html><body><footer>Sprites by Kenney Vleugels and Buch</footer></body></html>",
        encoding="utf-8",
    )
    (docs_demo / "ASSETS.md").write_text(
        "Asset Provenance Ledger\n\n"
        "| Pack ID | Author | License | Source URL |\n"
        "| --- | --- | --- | --- |\n"
        "| `kenney_ui` | Kenney Vleugels | `CC0 1.0` | https://kenney.nl/assets |\n"
        "| `oga_office` | Buch | `CC-BY 4.0` | https://opengameart.org/content/office |\n",
        encoding="utf-8",
    )

    clean = qa.check_assets_and_licenses(tmp_path)
    assert clean["passed"] is True
    assert clean["errors"] == []
    assert clean["manifest_sprites"] == 2

    budget_fail = qa.check_assets_and_licenses(tmp_path, max_png_bytes=10)
    assert budget_fail["passed"] is False
    assert any("max_png_bytes" in e for e in budget_fail["errors"])

    (docs_demo / "ASSETS.md").write_text(
        "| Pack ID | Author | License | Source URL |\n"
        "| --- | --- | --- | --- |\n"
        "| `bad1` | unknown | `CC-BY-NC 4.0` | http://shutterstock.com/pack |\n"
        "| `bad2` | Alice Artist | `CC-BY 4.0` | https://opengameart.org/content/missing-credit |\n",
        encoding="utf-8",
    )
    bad = qa.check_assets_and_licenses(tmp_path)
    assert bad["passed"] is False
    err_blob = "\n".join(bad["errors"])
    assert "placeholder author" in err_blob
    assert "https:// Source URL" in err_blob
    assert "Forbidden license" in err_blob
    assert "not credited in index.html" in err_blob


def test_check_ladder_provenance_exact_match_and_anti_cheat(
    committed_gt: dict[str, Any], tmp_path: Path
) -> None:
    ep_a, ep_b = committed_gt["episodes"][0], committed_gt["episodes"][1]
    demo = tmp_path / "demo" / "out-think-gemini"
    demo.mkdir(parents=True)

    valid_cases = {
        "cases": [
            {
                "id": "prov-a",
                "model": ep_a["model"],
                "tier": ep_a["tier"],
                "seed": ep_a["seed"],
                "decision_day": 5,
                "tool_steps": [{"day": 4, "tool": "plant_canary"}],
                "thinking_levels": [
                    {
                        "run_id": ep_a["run_id"],
                        "level": ep_a["level"],
                        "tier": ep_a["tier"],
                        "seed": ep_a["seed"],
                        "accused": ep_a["accused"],
                        "correct": ep_a["correct"],
                        "score": ep_a["score"],
                        "cost_usd": ep_a["cost_usd"],
                    }
                ],
            },
            {
                "id": "prov-b",
                "model": ep_b["model"],
                "tier": ep_b["tier"],
                "seed": ep_b["seed"],
                "decision_day": 6,
                "thinking_levels": {
                    ep_b["level"]: {
                        "model": ep_b["model"],
                        "tier": ep_b["tier"],
                        "seed": ep_b["seed"],
                        "accused": ep_b["accused"],
                        "correct": ep_b["correct"],
                        "score": ep_b["score"],
                        "cost_usd": ep_b["cost_usd"],
                    }
                },
            },
        ]
    }
    (demo / "cases.js").write_text(
        "window.OUTTHINK_DATA = " + json.dumps(valid_cases) + ";\n", encoding="utf-8"
    )

    ok_prov = qa.check_ladder_provenance(tmp_path, committed_gt)
    assert ok_prov["passed"] is True
    assert ok_prov["cases_checked"] == 2
    assert ok_prov["runs_checked"] == 2

    tampered = {
        "cases": [
            {
                "id": "cheat-case",
                "tier": ep_a["tier"],
                "seed": ep_a["seed"],
                "decision_day": 3,
                "tool_steps": [
                    {"day": 3, "tool": "accuse"},
                    {"day": 5, "tool": "read_logs"},
                ],
                "thinking_levels": [
                    {
                        "run_id": ep_a["run_id"],
                        "accused": "e99",
                        "correct": not ep_a["correct"],
                        "score": ep_a["score"] + 0.5,
                        "cost_usd": 0.0,
                    },
                    {
                        "run_id": "ladder:fabricated:nonexistent/run/0",
                        "accused": "e01",
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.25,
                    },
                ],
            }
        ]
    }
    (demo / "cases.js").write_text(
        "window.OUTTHINK_DATA = " + json.dumps(tampered) + ";\n", encoding="utf-8"
    )
    bad_prov = qa.check_ladder_provenance(tmp_path, committed_gt)
    assert bad_prov["passed"] is False
    blob = "\n".join(bad_prov["errors"])
    assert "leaks 'accuse' step" in blob
    assert "> decision_day" in blob
    assert "accused mismatch" in blob
    assert "correct mismatch" in blob
    assert "score " in blob
    assert "non-positive cost_usd" in blob
    assert "unknown run_id" in blob


def test_verify_case_math_bayesian_and_breakeven() -> None:
    good_cases = [
        {
            "id": "math-accuse",
            "value_at_decision": 0.6,
            "solver": {
                "posterior": {"e01": 0.15, "e02": 0.85},
                "top_suspect": "e02",
                "top_prob": 0.85,
                "break_even_prob": 0.625,
                "ev_accuse_top": 0.36,
                "ev_hold_fire": 0.0,
                "recommended_call": "accuse",
            },
        },
        {
            "id": "math-hold",
            "value_at_decision": 0.6,
            "solver": {
                "posterior": {"e01": 0.5, "e02": 0.5},
                "top_suspect": "e02",
                "top_prob": 0.5,
                "break_even_prob": 0.75,
                "ev_accuse_top": -0.2,
                "ev_hold_fire": 0.2,
                "recommended_call": "hold_fire",
            },
        },
    ]
    res_ok = qa.verify_case_math(good_cases)
    assert res_ok["passed"] is True
    assert res_ok["cases_checked"] == 2

    bad_case = {
        "id": "math-broken",
        "value_at_decision": 0.6,
        "solver": {
            "posterior": {"e01": 0.4, "e02": 0.4},
            "top_suspect": "e01",
            "top_prob": 0.9,
            "break_even_prob": 0.2,
            "ev_accuse_top": 0.99,
            "ev_hold_fire": 0.0,
            "recommended_call": "hold_fire",
        },
    }
    res_bad = qa.verify_case_math(bad_case)
    assert res_bad["passed"] is False
    joined = "\n".join(res_bad["errors"])
    assert "posterior sum" in joined
    assert "max(posterior)" in joined
    assert "break_even_prob" in joined
    assert "ev_accuse_top" in joined
    assert "recommended_call" in joined


def test_audit_js_engine_runtime_and_tamper_detection(tmp_path: Path) -> None:
    good_engine = tmp_path / "engine.js"
    good_engine.write_text(_make_minimal_engine_js(), encoding="utf-8")

    ok = qa.audit_js_engine(good_engine)
    assert ok["passed"] is True
    assert ok["errors"] == []
    if qa._find_js_runtime() is not None:
        assert ok["runtime_executed"] is True

    wrong_math = tmp_path / "wrong_engine.js"
    wrong_math.write_text(
        _make_minimal_engine_js().replace("(1.0 + hold) / (1.0 + val)", "0.1234"),
        encoding="utf-8",
    )
    bad_math = qa.audit_js_engine(wrong_math)
    if qa._find_js_runtime() is not None:
        assert bad_math["passed"] is False
        assert any("computeBreakEvenProb" in e for e in bad_math["errors"])

    missing_fn = tmp_path / "incomplete_engine.js"
    missing_fn.write_text("module.exports = { computeBreakEvenProb: function () { return 0.5; } };\n", encoding="utf-8")
    bad_exports = qa.audit_js_engine(missing_fn)
    assert bad_exports["passed"] is False
    assert any("missing required export" in e for e in bad_exports["errors"])


def test_audit_outthink_bundle_and_cli_strict_vs_non_strict(
    committed_gt: dict[str, Any], tmp_path: Path
) -> None:
    repo_res = qa.run_outthink_qa(ROOT, strict=False)
    assert repo_res["passed"] is True
    assert repo_res["ground_truth_episodes"] == 550
    assert qa.main(["--root", str(ROOT)]) == 0
    if (ROOT / "demo" / "out-think-gemini" / "index.html").is_file():
        assert qa.main(["--root", str(ROOT), "--strict"]) == 0

    bare_root = tmp_path / "bare_repo"
    (bare_root / "results").mkdir(parents=True)
    os.symlink(ROOT / "results" / "gemini", bare_root / "results" / "gemini")

    non_strict = qa.audit_outthink_bundle(bare_root, strict=False)
    assert non_strict["passed"] is True
    assert non_strict["checks"]["static_page"]["skipped"] is True
    assert qa.main(["--root", str(bare_root), "--strict"]) == 1

    demo = bare_root / "demo" / "out-think-gemini"
    sprites = demo / "assets" / "sprites"
    sprites.mkdir(parents=True)
    docs_demo = bare_root / "docs" / "demo"
    docs_demo.mkdir(parents=True)

    png_bytes = _make_png_bytes()
    (sprites / "agent.png").write_bytes(png_bytes)
    (demo / "assets" / "manifest.js").write_text(
        'window.OUTTHINK_ASSETS = {"sprites": {"agent": "sprites/agent.png"}};\n',
        encoding="utf-8",
    )
    (docs_demo / "ASSETS.md").write_text(
        "| Pack ID | Author | License | Source URL |\n"
        "| --- | --- | --- | --- |\n"
        "| `core` | Kenney Vleugels | `CC0 1.0` | https://kenney.nl/assets |\n",
        encoding="utf-8",
    )
    ep0 = committed_gt["episodes"][0]
    (demo / "cases.js").write_text(
        "window.OUTTHINK_DATA = "
        + json.dumps(
            {
                "cases": [
                    {
                        "id": "e2e-1",
                        "model": ep0["model"],
                        "tier": ep0["tier"],
                        "seed": ep0["seed"],
                        "decision_day": 5,
                        "value_at_decision": 0.6,
                        "true_mole": "e02",
                        "solver": {
                            "posterior": {"e01": 0.2, "e02": 0.8},
                            "top_suspect": "e02",
                            "top_prob": 0.8,
                            "break_even_prob": 0.625,
                            "ev_accuse_top": 0.28,
                            "ev_hold_fire": 0.0,
                            "recommended_call": "accuse",
                        },
                        "thinking_levels": [
                            {
                                "run_id": ep0["run_id"],
                                "level": ep0["level"],
                                "accused": ep0["accused"],
                                "correct": ep0["correct"],
                                "score": ep0["score"],
                                "cost_usd": ep0["cost_usd"],
                            }
                        ],
                    }
                ]
            }
        )
        + ";\n",
        encoding="utf-8",
    )
    (demo / "engine.js").write_text(_make_minimal_engine_js(), encoding="utf-8")
    (demo / "style.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (demo / "index.html").write_text(
        "<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body>"
        "<script src='assets/manifest.js'></script>"
        "<script src='cases.js'></script>"
        "<script src='engine.js'></script>"
        "</body></html>",
        encoding="utf-8",
    )

    full_strict = qa.audit_outthink_bundle(bare_root, strict=True)
    assert full_strict["passed"] is True, f"Unexpected errors: {full_strict['errors']}"
    assert qa.main(["--root", str(bare_root), "--strict"]) == 0
