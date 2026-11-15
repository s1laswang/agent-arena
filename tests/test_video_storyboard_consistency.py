from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = Path(__file__).resolve()

STORYBOARD_PATH = ROOT / "docs" / "VIDEO-STORYBOARD.md"
VO_DIR = ROOT / "docs" / "video" / "vo"
VO_INDEX_PATH = VO_DIR / "index.json"
VIDEO_VO_SCRIPT = ROOT / "scripts" / "video_vo.py"
DEMO_REPLAY_SCRIPT = ROOT / "scripts" / "demo_replay.py"
DOC_COMMANDS_SCRIPT = ROOT / "scripts" / "verify_doc_commands.py"

JUDGE_TABLE_PATH = ROOT / "results" / "judge_table.md"
PAIRED_GEMINI_JSON_PATH = ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
HEADLINE_CHART_PNG_PATH = ROOT / "results" / "eval_v14" / "headline_gap_paired_v14.png"
TRANSCRIPT_26_PATH = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "transcripts" / "26.txt"
)
EXPLOITS_MD_PATH = ROOT / "docs" / "EXPLOITS.md"
EXPLOITS_JSON_PATH = ROOT / "results" / "anticheat" / "exploits.json"
SIGNED_CHEAT_JSON_PATH = ROOT / "results" / "harbor" / "signed-cheat" / "result.json"
CHEAT_PROBE_JSON_PATH = ROOT / "results" / "harbor" / "cheat-probe" / "result.json"
SWARM_JSON_PATH = ROOT / "results" / "gemini" / "swarm.json"
SWARM_CONTROL_JSON_PATH = ROOT / "results" / "gemini" / "swarm_control.json"
WS4_TABLE_PATH = ROOT / "fr8" / "analysis" / "out" / "ws4_table_v3.md"
GEMINI_SUBMISSION_PATH = ROOT / "docs" / "gemini" / "SUBMISSION.md"
DASHBOARD_HTML_PATH = ROOT / "results" / "gemini" / "dashboard.html"

HASH_CHAR = chr(35)
H2_PREFIX = HASH_CHAR * 2 + " "
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_OPEN_ANGLE = chr(0x27E8)
UNICODE_CLOSE_ANGLE = chr(0x27E9)


def _load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


video_vo_mod = _load_script_module("video_vo_w7", VIDEO_VO_SCRIPT)
demo_replay_mod = _load_script_module("demo_replay_w7", DEMO_REPLAY_SCRIPT)
doc_commands_mod = _load_script_module("verify_doc_commands_w7", DOC_COMMANDS_SCRIPT)


@pytest.fixture(scope="module")
def storyboard_md() -> str:
    return STORYBOARD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def storyboard_sections(storyboard_md: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key = "_preamble"
    buf: list[str] = []
    for line in storyboard_md.splitlines():
        if line.startswith(H2_PREFIX):
            sections[current_key] = "\n".join(buf)
            current_key = line[len(H2_PREFIX) :].strip()
            buf = [line]
        else:
            buf.append(line)
    sections[current_key] = "\n".join(buf)
    return sections


def _scene_block(sections: dict[str, str], scene_num: int) -> str:
    prefix = f"Scene {scene_num} "
    for heading, body in sections.items():
        if heading.startswith(prefix):
            return body
    raise AssertionError(f"missing storyboard heading starting with {prefix!r}")


def _shot_list_row(sections: dict[str, str], scene_col: str) -> list[str]:
    shot_section = sections["Shot list and assets"]
    for line in shot_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == scene_col:
            return cells
    raise AssertionError(f"missing shot list row for scene {scene_col!r}")


def _parse_hard_paired_judge_rows(judge_md: str) -> tuple[str, dict[str, str]]:
    fp_match = re.search(r"sha256 fingerprint `([0-9a-f]+)`", judge_md)
    assert fp_match is not None
    fp = fp_match.group(1)

    in_hard = False
    in_paired_table = False
    rows: dict[str, str] = {}
    hard_heading = H2_PREFIX + "hard (headline: the Harbor judge set)"
    for line in judge_md.splitlines():
        if line.startswith(H2_PREFIX):
            if line.strip() == hard_heading:
                in_hard = True
                continue
            if in_hard:
                break
        if not in_hard:
            continue
        if line.startswith("Reported agent runs:"):
            break
        if line.strip().startswith("| agent |"):
            in_paired_table = True
            continue
        if in_paired_table and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] != "---":
                rows[cells[0]] = cells[4].replace("\u00b1", "+/-")
    return fp, rows


def _pct_band(lo: float, hi: float) -> str:
    return f"[{round(lo * 100)}%, {round(hi * 100)}%]"


def _parse_ws4_all_rows(ws4_text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for line in ws4_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 12 or cells[0] in ("model", "---"):
            continue
        if cells[3] == "all":
            out[cells[0]] = {
                "n": cells[4],
                "score_ci": cells[5].replace("\u00b1", "+/-"),
                "valid_calls": cells[9],
                "delta_vs_v2": cells[11].replace("\u00b1", "+/-"),
            }
    return out


def test_self_hygiene_zero_hash_and_zero_em_en_dashes():
    self_text = SELF_PATH.read_text(encoding="utf-8")
    assert HASH_CHAR not in self_text
    assert EM_DASH not in self_text
    assert EN_DASH not in self_text


def test_recorded_vo_lines_match_index_json_verbatim_and_mp3s_exist(storyboard_md: str):
    parsed_clips = video_vo_mod.clips(storyboard_md)
    clip_ids = [cid for cid, _ in parsed_clips]
    assert clip_ids == [
        "01-hook",
        "02-env",
        "03-bar",
        "04-gap",
        "05-replay",
        "06-fooled",
        "07-why",
        "08-integrity",
        "09-small",
        "10-close",
    ]
    clips_by_id = dict(parsed_clips)

    vo_entries = json.loads(VO_INDEX_PATH.read_text(encoding="utf-8"))
    assert len(vo_entries) == 9
    recorded_ids = [entry["id"] for entry in vo_entries]
    assert recorded_ids == [
        "01-hook",
        "02-env",
        "03-bar",
        "04-gap",
        "05-replay",
        "06-fooled",
        "07-why",
        "08-integrity",
        "10-close",
    ]

    for entry in vo_entries:
        cid = entry["id"]
        assert clips_by_id[cid] == entry["text"]
        assert entry["words"] == len(entry["text"].split())
        assert entry["characters"] == len(entry["text"])
        mp3_path = VO_DIR / entry["file"]
        assert mp3_path.is_file()
        assert mp3_path.stat().st_size > 0


def test_vo_09_small_placeholder_free_and_dry_run_processes_all_10(
    storyboard_md: str,
    capsys: pytest.CaptureFixture[str],
):
    clips_by_id = dict(video_vo_mod.clips(storyboard_md))
    vo_09 = clips_by_id["09-small"]
    assert UNICODE_OPEN_ANGLE not in vo_09
    assert UNICODE_CLOSE_ANGLE not in vo_09
    assert "<PLACEHOLDER" not in vo_09.upper()
    assert "placeholder" not in vo_09.lower()
    assert "bar not met" in vo_09.lower()
    assert 35 <= len(vo_09.split()) <= 45

    rc = video_vo_mod.main(["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "09-small:" in captured.out
    assert "skip 09-small" not in captured.out
    assert "skip " not in captured.out
    out_lines = [ln.strip() for ln in captured.out.splitlines() if ln.strip()]
    assert len(out_lines) == 10
    for cid in clips_by_id:
        assert any(ln.startswith(f"{cid}: ") for ln in out_lines)


def test_scene_3_matches_judge_table_hard_paired_rows(storyboard_sections: dict[str, str]):
    scene_3 = _scene_block(storyboard_sections, 3)
    fp, rows = _parse_hard_paired_judge_rows(JUDGE_TABLE_PATH.read_text(encoding="utf-8"))
    assert fp == "4bf5f8e8e48b"
    assert fp in scene_3

    assert rows["solver"] == "+0.513 +/- 0.120"
    assert rows["heuristic"] == "-0.009 +/- 0.184"
    assert rows["logs_only"] == "-0.916 +/- 0.115"
    assert rows["random"] == "-0.825 +/- 0.119"
    assert rows["guess_day1"] == "-0.950 +/- 0.098"
    assert rows["stop_early"].startswith("+0.000")
    assert rows["do_nothing"].startswith("+0.000")

    for agent_key in ("solver", "heuristic", "logs_only", "random", "guess_day1"):
        assert agent_key in scene_3
        assert rows[agent_key] in scene_3
    assert "`stop_early` **+0.000**" in scene_3
    assert "`do_nothing` **+0.000**" in scene_3
    assert "results/judge_table.md" in scene_3

    for stale_tok in ("+0.547", "-0.044", "-0.754", "+0.553", "893b837616b9"):
        assert stale_tok not in scene_3


def test_scene_4_matches_paired_table_gemini_and_headline_chart(
    storyboard_sections: dict[str, str],
):
    scene_4 = _scene_block(storyboard_sections, 4)
    assert HEADLINE_CHART_PNG_PATH.is_file()
    png_bytes = HEADLINE_CHART_PNG_PATH.read_bytes()
    assert len(png_bytes) > 1000
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    paired_rows = json.loads(PAIRED_GEMINI_JSON_PATH.read_text(encoding="utf-8"))
    hard_oc = next(
        r
        for r in paired_rows
        if r["tier"] == "hard"
        and r["agent"] == "opencode:google/gemini-4-carbon"
        and "alternative" not in r["label"]
    )
    hard_solver = next(
        r for r in paired_rows if r["tier"] == "hard" and r["agent"] == "solver"
    )
    hard_inproc = next(
        r for r in paired_rows if r["tier"] == "hard" and r["agent"] == "gemini:gemini-4-carbon"
    )
    med_oc = next(
        r
        for r in paired_rows
        if r["tier"] == "medium"
        and r["agent"] == "opencode:google/gemini-4-carbon"
        and "alternative" not in r["label"]
    )

    assert hard_oc["n"] == 30
    assert f"{round(hard_oc['ratio'] * 100)}% of the solver [95% CI {round(hard_oc['ratio_lo'] * 100)}%, {round(hard_oc['ratio_hi'] * 100)}%]" in scene_4
    assert f"{round(hard_oc['post_expected_ratio'] * 100)}% {_pct_band(hard_oc['post_expected_lo'], hard_oc['post_expected_hi'])}" in scene_4
    assert f"**{hard_oc['accuracy']:.2f}** vs solver **{hard_solver['accuracy']:.2f}**" in scene_4
    assert f"**{hard_oc['accuse_day']:.1f}** vs **{hard_solver['accuse_day']:.1f}**" in scene_4
    assert f"{round(hard_inproc['ratio'] * 100)}% {_pct_band(hard_inproc['ratio_lo'], hard_inproc['ratio_hi'])}" in scene_4
    assert f"{round(med_oc['ratio'] * 100)}% {_pct_band(med_oc['ratio_lo'], med_oc['ratio_hi'])}" in scene_4

    assert "post-hoc seed lock" in scene_4
    assert "671ed96" in scene_4
    assert "28 s after" in scene_4
    assert "8fd4dec" in scene_4
    assert "pre-regist" not in scene_4.lower()
    assert "results/eval_v14/headline_gap_paired_v14.png" in scene_4

    row_4 = _shot_list_row(storyboard_sections, "4")
    assert "results/eval_v14/headline_gap_paired_v14.png" in row_4[2]
    assert "data/runs/committed/v1.4/paired_table_gemini.json" in row_4[2]
    assert row_4[3] == "ready"


def test_scenes_5_and_6_match_demo_replay_seeds_4_and_26(
    storyboard_sections: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    scene_5 = _scene_block(storyboard_sections, 5)
    scene_6 = _scene_block(storyboard_sections, 6)

    eps_4 = {k: demo_replay_mod.load(v, 4) for k, v in demo_replay_mod.RUNS.items()}
    mole_4 = eps_4["solver"]["accused"]
    assert eps_4["solver"]["correct"] is True and mole_4 == "e11"
    days_4 = {k: demo_replay_mod.per_day(e, mole_4) for k, e in eps_4.items()}

    s4_d5 = days_4["solver"][5]
    g4_d5 = days_4["gemini"][5]
    g4_d16 = days_4["gemini"][16]
    assert s4_d5["canaries"] == 7
    assert round(s4_d5["p_mole"], 2) == 1.00
    assert s4_d5["accused"] == "e11"
    assert g4_d5["interviews"] == 29 and g4_d5["canaries"] == 2
    assert round(g4_d5["p_mole"], 2) == 0.10
    assert eps_4["gemini"]["final_day"] == 16 and g4_d16["accused"] == "e11"
    assert round(eps_4["solver"]["score"], 2) == 0.73
    assert round(eps_4["gemini"]["score"], 2) == 0.40
    ratio_4 = round(eps_4["gemini"]["score"] / eps_4["solver"]["score"] * 100)
    assert ratio_4 == 55

    for tok in (
        "day 5",
        "7 canaries",
        "P(mole) = 1.00",
        "e11",
        "29 interviews, 2 canaries, P(mole) = 0.10",
        "day 16",
        f"0.73 vs 0.40 ({ratio_4}%)",
    ):
        assert tok in scene_5

    eps_26 = {k: demo_replay_mod.load(v, 26) for k, v in demo_replay_mod.RUNS.items()}
    mole_26 = eps_26["solver"]["accused"]
    assert eps_26["solver"]["correct"] is True and mole_26 == "e08"
    days_26 = {k: demo_replay_mod.per_day(e, mole_26) for k, e in eps_26.items()}

    assert days_26["solver"][6]["canaries"] == 11
    assert eps_26["solver"]["final_day"] == 7 and days_26["solver"][7]["accused"] == "e08"
    assert round(eps_26["solver"]["score"], 2) == 0.69
    assert round(days_26["gemini"][9]["p_mole"], 2) == 0.48
    assert round(days_26["gemini"][10]["p_mole"], 2) == 0.03
    assert days_26["gemini"][10]["accused"] == "e04"
    assert round(eps_26["gemini"]["score"], 2) == -1.00

    assert TRANSCRIPT_26_PATH.is_file()
    raw_t26 = TRANSCRIPT_26_PATH.read_text(encoding="utf-8")
    plain_t26 = raw_t26.replace("*", "").replace("`", "")
    assert "Their intersection uniquely identified e04" in plain_t26

    from canary.rules import TIERS

    assert TIERS["hard"].fingerprint_accuracy == 0.95

    for tok in (
        "Their intersection uniquely identified e04",
        "P(true mole e08) = 0.48",
        "P = 0.03",
        "e04",
        "11 canaries by day 6",
        "e08 on day 7: +0.69",
        "0.95",
    ):
        assert tok in scene_6


def test_scene_8_matches_exploits_md_harbor_and_swarm_json(
    storyboard_sections: dict[str, str],
):
    scene_8 = _scene_block(storyboard_sections, 8)
    exploits_md = EXPLOITS_MD_PATH.read_text(encoding="utf-8")

    numbered_ids = [int(m.group(1)) for m in re.finditer(r"^\|\s*(\d+)\s*\|", exploits_md, re.M)]
    j_ids = re.findall(r"^\|\s*(J\d+)\s*\|", exploits_md, re.M)
    assert numbered_ids == list(range(52))
    assert j_ids == [f"J{i}" for i in range(1, 16)]

    signed_cheat = json.loads(SIGNED_CHEAT_JSON_PATH.read_text(encoding="utf-8"))
    assert signed_cheat["n_total_trials"] == 6
    eval_entry = next(iter(signed_cheat["stats"]["evals"].values()))
    assert eval_entry["metrics"][0]["mean"] == -1.0

    cheat_probe = json.loads(CHEAT_PROBE_JSON_PATH.read_text(encoding="utf-8"))
    assert cheat_probe["n_total_trials"] == 6
    probe_eval = next(iter(cheat_probe["stats"]["evals"].values()))
    assert probe_eval["metrics"][0]["mean"] == 0.0

    exploits_json = json.loads(EXPLOITS_JSON_PATH.read_text(encoding="utf-8"))
    harbor_trials = [e for e in exploits_json["harbor"] if e.get("kind") == "trial"]
    assert len(harbor_trials) == 80 and all(t["consistent"] for t in harbor_trials)

    swarm = json.loads(SWARM_JSON_PATH.read_text(encoding="utf-8"))
    assert swarm["counts"]["attempts"] == 100
    assert swarm["counts"]["ledger_verified"] == 100
    assert swarm["counts"]["exploits"] == 0
    wb_finished = sum(w["finished"] for w in swarm["waves"] if w["mode"] == "whitebox")
    bb_finished = sum(w["finished"] for w in swarm["waves"] if w["mode"] == "blackbox")
    mcp_reruns = sum(w["mcp_reruns"] for w in swarm["waves"])
    assert (wb_finished, bb_finished, mcp_reruns) == (75, 16, 9)
    assert wb_finished + bb_finished + mcp_reruns == 100

    swarm_control = json.loads(SWARM_CONTROL_JSON_PATH.read_text(encoding="utf-8"))
    assert swarm_control["counts"]["attempts"] == 4
    assert swarm_control["counts"]["exploits"] == 4

    for tok in (
        f"52 numbered rows (`{HASH_CHAR}0` to `{HASH_CHAR}51`, plus `J1-J15`)",
        "-1.0 on 6/6 trials",
        "0.0 on 6/6",
        "80/80",
        "100 ledger-verified attacks",
        "75 whitebox + 16 blackbox + 9 MCP reruns, 0 verified exploits",
        "4/4",
        "08-integrity.mp3",
        "wave-1",
    ):
        assert tok in scene_8
    assert "35 whitebox" not in scene_8


def test_scene_9_and_shot_list_match_ws4_table_v3(
    storyboard_sections: dict[str, str],
):
    scene_9 = _scene_block(storyboard_sections, 9)
    assert UNICODE_OPEN_ANGLE not in scene_9
    assert UNICODE_CLOSE_ANGLE not in scene_9
    assert "Placeholder" not in scene_9

    ws4_text = WS4_TABLE_PATH.read_text(encoding="utf-8")
    ws4_rows = _parse_ws4_all_rows(ws4_text)
    assert ws4_rows["base"]["n"] == "36"
    assert ws4_rows["base"]["score_ci"] == "0.000 +/- 0.000"
    assert ws4_rows["base"]["valid_calls"] == "0.03"
    assert ws4_rows["v2"]["n"] == "172"
    assert ws4_rows["v2"]["score_ci"] == "-0.457 +/- 0.086"
    assert ws4_rows["v3-4k-s0"]["n"] == "180"
    assert ws4_rows["v3-4k-s0"]["score_ci"] == "-0.147 +/- 0.063"
    assert ws4_rows["v3-4k-s0"]["valid_calls"] == "1.00"
    assert ws4_rows["v3-4k-s0"]["delta_vs_v2"].startswith("+0.310 +/- 0.107")
    assert ws4_rows["v3-8k-s2"]["n"] == "90"
    assert ws4_rows["v3-8k-s2"]["score_ci"] == "-0.050 +/- 0.049"
    assert "bar NOT met" in ws4_text

    for tok in (
        "Qwen2.5-1.5B-Instruct",
        "0.000 +/- 0.000",
        "n=36",
        "3%",
        "-0.457 +/- 0.086",
        "n=172",
        "-0.147 +/- 0.063",
        "n=180",
        "+0.310 +/- 0.107",
        "100%",
        "0.19 -> 0.89",
        "-0.050 +/- 0.049",
        "n=90",
        "**bar not met**",
        "no held-out gain over base",
    ):
        assert tok in scene_9

    row_9 = _shot_list_row(storyboard_sections, "9")
    assert "fr8/analysis/out/ws4_table_v3.md" in row_9[2]
    assert "docs/reports/fr8.md" in row_9[2]
    assert row_9[3] == "ready"
    assert "placeholder" not in row_9[3].lower()


def test_scene_10_matches_gemini_submission_and_dashboard_html(
    storyboard_md: str,
    storyboard_sections: dict[str, str],
):
    scene_10 = _scene_block(storyboard_sections, 10)
    gemini_sub = GEMINI_SUBMISSION_PATH.read_text(encoding="utf-8")
    dashboard_html = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")

    data_match = re.search(
        r'<script id="data" type="application/json">(.*?)</script>',
        dashboard_html,
        re.S,
    )
    assert data_match is not None
    totals = json.loads(data_match.group(1))["usage"]["totals"]
    calls_str = f"{int(totals['calls']):,}"
    cached_pct_str = f"{totals['cached'] / totals['in'] * 100:.1f}%"
    cost_str = f"${totals['cost_usd']:.2f}"

    assert calls_str == "24,855"
    assert cached_pct_str == "85.3%"
    assert cost_str == "$226.34"

    for tok in (calls_str, cached_pct_str, cost_str):
        assert tok in gemini_sub
        assert tok in scene_10

    assert f"{calls_str} Gemini calls, {cached_pct_str} cached, {cost_str} at list price" in scene_10
    assert "11,187" not in storyboard_md
    assert "$88.75" not in storyboard_md


def test_storyboard_commands_pass_doc_command_verifier(storyboard_sections: dict[str, str]):
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    results = doc_commands_mod.verify_repo(ROOT, docs=("docs/VIDEO-STORYBOARD.md",))
    assert all(r.status != "FAIL" for r in results), [
        (r.name, r.status, r.details) for r in results if r.status == "FAIL"
    ]

    for scene_num in (3, 4, 8, 9, 10):
        body_lines = _scene_block(storyboard_sections, scene_num).splitlines()[1:]
        for ln in body_lines:
            assert EM_DASH not in ln
            assert EN_DASH not in ln
    for row_key in ("4", "9"):
        row_cells = _shot_list_row(storyboard_sections, row_key)
        assert all(EM_DASH not in c and EN_DASH not in c for c in row_cells)
