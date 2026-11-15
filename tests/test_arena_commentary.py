from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts" / "export_arena_commentary.py"
COMMENTARY_JS_PATH = ROOT / "docs" / "arena" / "data" / "transcript_commentary.js"
STALE_ROOT_JS_PATH = ROOT / "docs" / "arena" / "transcript_commentary.js"
NODE_BIN = shutil.which("node") or "/home/silas/tools/node/bin/node"

HASH_CHAR = chr(35)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

EMP_ID_RE = re.compile(r"\be\d{2,3}\b")
WINDOW_ASSIGN_RE = re.compile(
    r"(?:\b(?:window|globalThis|self)\.[A-Za-z_$][A-Za-z0-9_$]*|\b(?:const|let|var)\s+[A-Z][A-Z0-9_]{2,})\s*=\s*"
)

PRE_END_TRUTH_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "accused",
        "score",
        "world_seed",
        "_world",
        "true_v",
        "true_V",
        "trueV",
        "V",
        "is_canary",
        "leaking_sprite_employee",
        "verbatim_quote",
        "quote",
        "transcript_quotes",
    }
)

PROTECTED_EXACT = frozenset({"canary/env.py", "canary/rules.py", "canary/reproduce.py"})
PROTECTED_PREFIXES = ("canary/solver/", "harbor/")


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_arena_commentary", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_node_module(js_code: str, extra_env: dict[str, str] | None = None) -> Any:
    env = dict(os.environ)
    env["MOD_PATH"] = str(COMMENTARY_JS_PATH)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [NODE_BIN, "--input-type=module", "-e", js_code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"node failed ({proc.returncode}): {proc.stderr}"
    return json.loads(proc.stdout)


def _scan_pre_end_forbidden(obj: Any, loc: str) -> list[str]:
    issues: list[str] = []
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            issues.extend(_scan_pre_end_forbidden(item, f"{loc}[{idx}]"))
        return issues
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            child = f"{loc}.{ks}"
            if ks in PRE_END_TRUTH_KEYS:
                issues.append(f"{child}: forbidden pre-end key {ks}")
            issues.extend(_scan_pre_end_forbidden(v, child))
        return issues
    if isinstance(obj, str):
        if not obj.startswith("sealed:") and EMP_ID_RE.search(obj):
            issues.append(f"{loc}: employee id leak in {obj!r}")
    return issues


def _load_committed_episodes(tier: str) -> dict[int, dict[str, Any]]:
    ep_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / tier / "episodes.jsonl"
    out: dict[int, dict[str, Any]] = {}
    for line in ep_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[int(row["seed"])] = row
    return out


def test_owned_files_strict_hygiene_and_zero_protected_edits():
    this_file = Path(__file__).resolve()
    assert EXPORTER_PATH.is_file()
    assert COMMENTARY_JS_PATH.is_file()
    assert not STALE_ROOT_JS_PATH.exists()

    forb_coauthor = "-".join(("Co", "Authored", "By")).lower()
    forb_lock_1 = "pre" + "-reg"
    forb_lock_2 = "pre" + "reg"
    xss_sinks = (
        "inner" + "HTML",
        "outer" + "HTML",
        "insertAdjacent" + "HTML",
        "document." + "write",
    )
    key_prefixes = ("AI" + "za", "s" + "k-")

    for path in (EXPORTER_PATH, COMMENTARY_JS_PATH, this_file):
        size_bytes = path.stat().st_size
        assert 0 < size_bytes <= 130 * 1024, (path, size_bytes)
        txt = path.read_text(encoding="utf-8")
        assert txt.isascii(), path
        assert HASH_CHAR not in txt, path
        assert SLASH_SLASH not in txt, path
        assert SLASH_STAR not in txt, path
        assert STAR_SLASH not in txt, path
        assert EM_DASH not in txt, path
        assert EN_DASH not in txt, path
        assert UNICODE_MINUS not in txt, path
        assert forb_coauthor not in txt.lower(), path
        assert forb_lock_1 not in txt.lower(), path
        assert forb_lock_2 not in txt.lower(), path
        for sink in xss_sinks:
            assert sink not in txt, (path, sink)
        for kp in key_prefixes:
            assert kp not in txt, (path, kp)

    for py_path in (EXPORTER_PATH, this_file):
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)

    for git_args in (
        ["diff", "--name-only", "origin/justSilas"],
        ["diff", "--name-only", "--cached"],
        ["diff", "--name-only"],
    ):
        proc = subprocess.run(["git", *git_args], cwd=ROOT, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            for raw in proc.stdout.splitlines():
                rel = raw.strip()
                if not rel:
                    continue
                assert rel not in PROTECTED_EXACT, rel
                assert not any(rel.startswith(pfx) for pfx in PROTECTED_PREFIXES), rel


def test_exporter_cli_check_mode_and_staleness_detection(tmp_path):
    exporter = _load_exporter()
    assert exporter.main(["--check"]) == 0

    missing_js = tmp_path / "missing_commentary.js"
    assert exporter.main(["--out", str(missing_js), "--check"]) == 1
    assert not missing_js.exists()

    written_js = tmp_path / "transcript_commentary.js"
    assert exporter.main(["--out", str(written_js), "--write"]) == 0
    assert written_js.read_text(encoding="utf-8") == COMMENTARY_JS_PATH.read_text(encoding="utf-8")
    assert exporter.main(["--out", str(written_js), "--check"]) == 0

    written_js.write_text(written_js.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert exporter.main(["--out", str(written_js), "--check"]) == 1


def test_raw_js_json_payloads_zero_pre_end_spoilers_and_benchmark_seeds():
    js_text = COMMENTARY_JS_PATH.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    extracted: dict[str, Any] = {}
    for match in WINDOW_ASSIGN_RE.finditer(js_text):
        pos = match.end()
        while pos < len(js_text) and js_text[pos].isspace():
            pos += 1
        if pos < len(js_text) and js_text[pos] in "{[":
            obj, _ = decoder.raw_decode(js_text, pos)
            lhs = match.group(0).split("=")[0].strip()
            extracted[lhs] = obj

    assert "const TICKER_PACK" in extracted
    assert "const FORENSICS_SEALED_B64" in extracted

    ticker_pack = extracted["const TICKER_PACK"]
    sealed_map = extracted["const FORENSICS_SEALED_B64"]
    expected_keys = {
        "hard:6",
        "hard:26",
        "hard:4",
        "hard:18",
        "hard:15",
        "hard:11",
        "hard:5",
        "hard:23",
        "medium:0",
        "medium:12",
    }
    assert set(ticker_pack.keys()) == expected_keys
    assert set(sealed_map.keys()) == expected_keys

    assert _scan_pre_end_forbidden(ticker_pack, "TICKER_PACK") == []
    assert _scan_pre_end_forbidden(sealed_map, "FORENSICS_SEALED_B64") == []

    for key, val in ticker_pack.items():
        seed_num = int(val["seed"])
        assert 0 <= seed_num <= 29, (key, seed_num)
        assert not (900000 <= seed_num <= 900039)
        assert not (800000 <= seed_num <= 800199)
        assert not (100000 <= seed_num <= 199999)

    for key, token in sealed_map.items():
        assert isinstance(token, str) and token.startswith("sealed:"), (key, token[:16])


def test_node_v24_pre_end_zero_spoiler_day_sync_and_fail_closed_forensics():
    js_probe = """
import { pathToFileURL } from "node:url";
globalThis.window = globalThis;
const mod = await import(pathToFileURL(process.env.MOD_PATH).href);
const api = window.CanaryTranscriptCommentary;
const alias = window.CANARY_TRANSCRIPT_COMMENTARY;

const hardSeeds = api.listSeeds("hard");
const medSeeds = api.listSeeds("medium");

const closedChecks = [
  api.getPostGameForensics(6),
  api.getPostGameForensics(6, false),
  api.getPostGameForensics(6, false, "hard"),
  api.getPostGameForensics("hard", 6, false),
  api.getPostGameForensics("hard:6"),
  api.getPostGameForensics("hard:6", false),
  api.getPostGameForensics(6, { tier: "hard", humanDone: false }),
  api.getPostGameForensics(6, { tier: "hard", done: false }),
  api.getPostGameForensics({ seed: 6, tier: "hard" }),
  api.getPostGameForensics({ seed: 6, tier: "hard", humanDone: false }),
  api.unlockPostGameForensics("hard", 6, false),
  api.unlockPostGameForensics(6),
  api.byKey["hard:6"].unlockForensics(false),
  api.byKey["hard:26"].unlockForensics()
];

const preEndViews = {};
for (const [tier, seeds, maxDay] of [["hard", hardSeeds, 21], ["medium", medSeeds, 14]]) {
  for (const s of seeds) {
    const key = tier + ":" + String(s);
    const days = [];
    for (let d = 0; d <= maxDay; d += 1) {
      const v1 = api.getCommentaryView(s, d, false, tier);
      const v2 = api.getCommentaryView(tier, s, d, false);
      const v3 = api.getCommentaryView({ seed: s, tier, humanDay: d, humanDone: false });
      if (JSON.stringify(v1) !== JSON.stringify(v2) || JSON.stringify(v1) !== JSON.stringify(v3)) {
        throw new Error("view signature mismatch on " + key + " day " + String(d));
      }
      days.push({
        view: v1,
        coerced: String(v1.ticker),
        feedLen: api.getDayTickerFeed(s, d, false, tier).length
      });
    }
    preEndViews[key] = days;
  }
}

const sampleSteps = [
  { day: 1, call_idx: 0, tool: "plant_canary", args: {}, ok: true, summary: "planted", sealed: false },
  { day: 1, call_idx: 1, tool: "advance_day", args: {}, ok: true, summary: "end day", sealed: false },
  { day: 6, call_idx: 56, tool: "accuse", args: "[SEALED]", ok: true, summary: "Accusation filed [SEALED]", sealed: true }
];
const annotated = api.annotateDuelSteps(sampleSteps, 6, 6, "hard");

process.stdout.write(JSON.stringify({
  sameGlobal: api === mod.CanaryTranscriptCommentary && alias === mod.CANARY_TRANSCRIPT_COMMENTARY && api === alias && api === mod.default,
  hardSeeds,
  medSeeds,
  hasChecks: [
    api.hasSeed(6),
    api.hasSeed(26, "hard"),
    api.hasSeed("hard:4"),
    api.hasSeed("medium", 12),
    api.hasSeed(0, "medium"),
    !api.hasSeed(900000, "hard"),
    !api.hasSeed(800000, "medium"),
    !api.hasSeed(3000, "medium")
  ],
  numericAliasOk: api["6"].key === "hard:6" && api.byKey["26"].key === "hard:26" && api["12"].key === "medium:12",
  closedAllNull: closedChecks.every((x) => x === null),
  rootDump: JSON.parse(JSON.stringify(api)),
  preEndViews,
  annotated
}));
"""
    res = _run_node_module(js_probe)
    assert res["sameGlobal"] is True
    assert res["hardSeeds"] == [6, 26, 4, 18, 15, 11, 5, 23]
    assert res["medSeeds"] == [0, 12]
    assert all(res["hasChecks"])
    assert res["numericAliasOk"] is True
    assert res["closedAllNull"] is True

    assert _scan_pre_end_forbidden(res["rootDump"], "CanaryTranscriptCommentary") == []
    assert _scan_pre_end_forbidden(res["preEndViews"], "preEndViews") == []

    annotated = res["annotated"]
    assert annotated[1]["commentary"] == "Day 1: Gemini has run 5 interviews and planted 2 canaries"
    assert "commentary" not in annotated[2]
    assert annotated[2]["sealed"] is True

    hard_eps = _load_committed_episodes("hard")
    med_eps = _load_committed_episodes("medium")

    for tier, seeds, eps in (("hard", res["hardSeeds"], hard_eps), ("medium", res["medSeeds"], med_eps)):
        for seed in seeds:
            key = f"{tier}:{seed}"
            ep = eps[int(seed)]
            steps = ep["steps"]
            final_day = int(ep["final_day"])
            day_rows = res["preEndViews"][key]

            day0 = day_rows[0]["view"]
            assert day0["forensics"] is None
            assert day0["sealed"] is True
            assert day0["ticker"]["cumulative"]["interviews"] == 0
            assert day0["ticker"]["cumulative"]["canaries"] == 0
            assert day_rows[0]["feedLen"] == 0

            cum_iv = 0
            cum_cn = 0
            for d in range(1, len(day_rows)):
                if d <= final_day:
                    for st in steps:
                        if int(st["day"]) == d and bool((st.get("result") or {}).get("ok")):
                            if st["tool"] == "interview":
                                cum_iv += 1
                            elif st["tool"] == "plant_canary":
                                cum_cn += 1
                row = day_rows[d]
                view = row["view"]
                assert view["forensics"] is None
                assert view["sealed"] is True
                assert row["coerced"] == view["ticker"]["text"]
                assert view["ticker"]["cumulative"]["interviews"] == cum_iv
                assert view["ticker"]["cumulative"]["canaries"] == cum_cn
                if d < final_day:
                    assert view["ticker"]["concluded"] is False
                    assert view["ticker"]["gemini_final_day"] is None
                    assert row["feedLen"] == d
                else:
                    assert view["ticker"]["concluded"] is True
                    assert view["ticker"]["gemini_final_day"] == final_day
                    assert row["feedLen"] == final_day
                    if d > final_day:
                        assert "(verdict sealed)" in view["ticker"]["text"]


def test_node_v24_post_game_forensics_replay_scores_and_verbatim_quotes():
    js_unlock = """
import { pathToFileURL } from "node:url";
globalThis.window = globalThis;
await import(pathToFileURL(process.env.MOD_PATH).href);
const api = window.CanaryTranscriptCommentary;

const sigChecks = [
  api.getPostGameForensics(6, true),
  api.getPostGameForensics(6, true, "hard"),
  api.getPostGameForensics("hard", 6, true),
  api.getPostGameForensics("hard:6", true),
  api.getPostGameForensics(6, { tier: "hard", humanDone: true }),
  api.getPostGameForensics({ seed: 6, tier: "hard", done: true }),
  api.getCommentaryView(6, 6, true, "hard").forensics,
  api.byKey["hard:6"].unlockForensics(true)
];
const ref6 = JSON.stringify(sigChecks[0]);
const allMatch6 = sigChecks.every((x) => x && JSON.stringify(x) === ref6);

const unlocked = {};
for (const s of api.listSeeds("hard")) {
  unlocked["hard:" + String(s)] = api.getPostGameForensics(s, { tier: "hard", humanDone: true });
}
for (const s of api.listSeeds("medium")) {
  unlocked["medium:" + String(s)] = api.getPostGameForensics(s, { tier: "medium", humanDone: true });
}

process.stdout.write(JSON.stringify({ allMatch6, unlocked }));
"""
    payload = _run_node_module(js_unlock)
    assert payload["allMatch6"] is True
    unlocked = payload["unlocked"]
    assert len(unlocked) == 10

    f6 = unlocked["hard:6"]
    assert f6["done"] is True
    assert f6["true_mole"]["id"] == "e34"
    assert f6["decoy"]["id"] == "e20"
    assert f6["verdict_tag"] == "clean_catch"
    assert f6["gemini"]["accused"] == "e34"
    assert f6["gemini"]["correct"] is True
    assert f6["gemini"]["score"] == pytest.approx(0.73)
    assert f6["gemini"]["final_day"] == 6
    assert f6["gemini"]["total_calls"] == 57
    assert f6["gemini"]["interviews"] == 25
    assert f6["gemini"]["canaries_planted"] == 7
    assert f6["solver"]["score"] == pytest.approx(0.71)
    assert f6["solver"]["final_day"] == 6
    assert f6["solver"]["total_calls"] == 52
    assert f6["solver"]["canaries_planted"] == 9
    assert f6["solver"]["interviews"] == 0

    f26 = unlocked["hard:26"]
    assert f26["done"] is True
    assert f26["true_mole"]["id"] == "e08"
    assert f26["decoy"]["id"] == "e38"
    assert f26["verdict_tag"] == "wrong_accusation"
    assert f26["gemini"]["accused"] == "e04"
    assert f26["gemini"]["correct"] is False
    assert f26["gemini"]["score"] == pytest.approx(-1.0)
    assert f26["gemini"]["final_day"] == 10
    assert f26["gemini"]["total_calls"] == 91
    assert f26["gemini"]["interviews"] == 43
    assert f26["gemini"]["canaries_planted"] == 8
    assert f26["solver"]["score"] == pytest.approx(0.69)
    assert f26["solver"]["final_day"] == 7
    assert f26["solver"]["total_calls"] == 60
    assert f26["solver"]["canaries_planted"] == 11

    f4 = unlocked["hard:4"]
    assert f4["true_mole"]["id"] == "e11"
    assert f4["gemini"]["score"] == pytest.approx(0.40)
    assert f4["gemini"]["final_day"] == 16
    assert f4["gemini"]["interviews"] == 84
    assert f4["gemini"]["canaries_planted"] == 10
    assert f4["solver"]["score"] == pytest.approx(0.73)
    assert f4["solver"]["final_day"] == 5

    f11 = unlocked["hard:11"]
    assert f11["true_mole"]["id"] == "e09"
    assert f11["gemini"]["accused"] is None
    assert f11["gemini"]["score"] == pytest.approx(0.0)
    assert f11["gemini"]["final_day"] == 21
    assert f11["verdict_tag"] == "horizon_abstention"

    for lucky_key in ("hard:5", "hard:23"):
        fl = unlocked[lucky_key]
        assert fl["verdict_tag"] == "below_breakeven_lucky"
        assert fl["gemini"]["below_breakeven"] is True
        assert fl["gemini"]["p_accused_at_end"] < fl["gemini"]["breakeven_p_true"]

    assert unlocked["medium:0"]["gemini"]["score"] == pytest.approx(0.63)
    assert unlocked["medium:0"]["solver"]["score"] == pytest.approx(0.74)
    assert unlocked["medium:12"]["gemini"]["score"] == pytest.approx(0.81)
    assert unlocked["medium:12"]["solver"]["score"] == pytest.approx(0.67)

    for key, f_entry in unlocked.items():
        tier, seed_str = key.split(":")
        t_path = (
            ROOT
            / "data"
            / "runs"
            / "committed"
            / "v1.4"
            / "opencode-gemini-4-carbon"
            / tier
            / "transcripts"
            / f"{seed_str}.txt"
        )
        assert t_path.is_file(), t_path
        parsed_text_parts: list[str] = []
        for raw_line in t_path.read_text(encoding="utf-8").splitlines():
            s_line = raw_line.strip()
            if s_line.startswith("{"):
                ev = json.loads(s_line)
                if ev.get("type") == "text":
                    txt_part = str((ev.get("part") or {}).get("text") or "")
                    if txt_part:
                        parsed_text_parts.append(txt_part)
        joined_transcript_text = "\n".join(parsed_text_parts)
        assert f_entry["transcript_present"] is True
        assert isinstance(f_entry["turning_point"], str) and len(f_entry["turning_point"]) >= 20
        assert "[object Object]" not in f_entry["turning_point"]
        assert isinstance(f_entry["turning_point_detail"], dict)
        assert isinstance(f_entry["verbatim_quote"], str) and len(f_entry["verbatim_quote"]) >= 20
        assert f_entry["verbatim_quote"] == f_entry["quote"]
        assert f_entry["verbatim_quote"] in joined_transcript_text, key
        assert len(f_entry["transcript_quotes"]) >= 1
        for q_item in f_entry["transcript_quotes"]:
            assert q_item["quote"] in joined_transcript_text, (key, q_item["quote"])
