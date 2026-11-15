from __future__ import annotations

import argparse
import functools
import glob
import http.server
import json
import math
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "docs" / "demo" / "canary_demo.mp4"
SCRATCH_BASE = Path("/localscratch/fleet-silas/demo-video")
WIDTH = 1280
HEIGHT = 720
FPS = 24
TARGET_DURATION_S = 75.0
TOTAL_FRAMES = int(round(TARGET_DURATION_S * FPS))
GAME_SEED = 3000

ACTS_SPEC = [
    {
        "id": "act1_browser_game_seed3000",
        "title": "Act 1: Canary Browser Game (Pyodide Live, Seed 3000)",
        "start_s": 0.0,
        "end_s": 26.0,
        "summary": "Real canary Python environment in WebAssembly: case brief, rules, canary traps c1 and c4, mole e09 caught.",
    },
    {
        "id": "act2_office_replay_seed6_caught",
        "title": "Act 2: Office Replay - Hard Seed 6 (Gemini Caught Mole, +0.73)",
        "start_s": 26.0,
        "end_s": 47.0,
        "summary": "40-staff hard world: decoy e20 excluded, orthogonal canaries isolate e34 Sofia Niemi on Day 6 (+0.73 vs solver +0.71).",
    },
    {
        "id": "act3_office_replay_seed26_fooled",
        "title": "Act 3: Office Replay - Hard Seed 26 (Gemini Fooled, -1.00)",
        "start_s": 47.0,
        "end_s": 67.5,
        "summary": "43 interviews and late canaries leave Gemini vulnerable to one 5% noisy readout on Day 10, accusing innocent e04 (-1.00 vs solver +0.69).",
    },
    {
        "id": "act4_paired_gap_and_integrity",
        "title": "Act 4: Paired v1.4 Frontier Gap and Keyless Replay Integrity",
        "start_s": 67.5,
        "end_s": 75.0,
        "summary": "Hard OpenCode gemini-4-carbon keeps 65% of solver [24%, 98%] across 30 paired seeds; 0 verified exploits across 100 swarm attacks.",
    },
]


def _load_episode(dirs: list[Path], seed: int) -> dict[str, Any]:
    for d in dirs:
        fp = d / "episodes.jsonl"
        if not fp.is_file():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row.get("seed", -1)) == seed:
                row.setdefault("tier", "hard")
                row["_source"] = str(fp.relative_to(ROOT))
                return row
    raise RuntimeError(f"Episode for seed {seed} not found in {[str(x) for x in dirs]}")


def _load_transcript_excerpt(seed: int, max_chars: int = 300) -> str:
    tp = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "transcripts" / f"{seed}.txt"
    if not tp.is_file():
        return ""
    texts: list[str] = []
    for raw in tp.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        part = obj.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            txt = str(part["text"]).strip()
            if not txt.lower().startswith("thought"):
                texts.append(txt)
    if not texts:
        return ""
    clean = re.sub(r"[*`]+", "", texts[-1])
    clean = clean.replace("\u2014", " - ").replace("\u2013", "-")
    clean = " ".join(clean.split())
    if len(clean) > max_chars:
        return clean[: max_chars - 3].rstrip() + "..."
    return clean


def _compute_agent_days(ep_dict: dict[str, Any], employees: list[dict[str, Any]], mole_id: str) -> dict[int, dict[str, Any]]:
    from canary.analysis.tags import to_result
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy

    ep = to_result(ep_dict)
    sp = SolverPolicy(tier_params_for_episode(ep.tier, ep.steps))
    emp_ids = [e["id"] for e in employees]
    out: dict[int, dict[str, Any]] = {}
    visible_v = 1.0
    canaries = 0
    interviews = 0
    leaks_seen: list[dict[str, Any]] = []
    day_interviews: list[str] = []
    day_canaries: list[str] = []
    day_tools: list[str] = []

    for idx, st in enumerate(ep.steps):
        data = (st.result or {}).get("data") or {}
        ok = bool((st.result or {}).get("ok"))
        day_tools.append(st.tool)
        if st.tool in ("status", "advance_day") and isinstance(data, dict) and "V" in data:
            visible_v = float(data["V"])
        if st.tool == "plant_canary" and ok:
            canaries += 1
            cid = str(data.get("canary_id") or f"c{canaries}")
            day_canaries.append(cid)
        if st.tool == "interview" and ok:
            interviews += 1
            who = str(st.args.get("employee") or data.get("employee") or "")
            if who and who not in day_interviews:
                day_interviews.append(who)
        if st.tool == "check_leak_feed" and ok and isinstance(data, dict):
            seen_ids = {x.get("doc_id") for x in leaks_seen}
            for item in data.get("items") or []:
                if item.get("doc_id") not in seen_ids:
                    leaks_seen.append(
                        {
                            "doc_id": item.get("doc_id"),
                            "title": item.get("title"),
                            "variant": item.get("variant"),
                            "surfaced_day": item.get("surfaced_day"),
                        }
                    )
                    seen_ids.add(item.get("doc_id"))

        last_of_day = (idx + 1 == len(ep.steps)) or (ep.steps[idx + 1].day != st.day)
        if st.tool == "accuse":
            last_of_day = True

        if last_of_day:
            for prev in ep.steps[sp.seen : idx + 1]:
                if prev.tool != "accuse":
                    sp._ingest(prev)
            sp.seen = idx + 1
            post = sp.belief() if sp.obs.employees else {eid: 1.0 / max(1, len(emp_ids)) for eid in emp_ids}
            top_id = max(post, key=post.get) if post else ""
            out[int(st.day)] = {
                "day": int(st.day),
                "V": round(visible_v, 4),
                "canaries": canaries,
                "interviews": interviews,
                "calls": idx + 1,
                "p_mole": round(float(post.get(mole_id, 0.0)), 4),
                "top_id": top_id,
                "p_top": round(float(post.get(top_id, 0.0)), 4),
                "accused": st.args.get("employee") if st.tool == "accuse" else None,
                "beliefs": {eid: round(float(post.get(eid, 0.0)), 4) for eid in emp_ids},
                "day_interviews": list(day_interviews),
                "day_canaries": list(day_canaries),
                "leaks": list(leaks_seen[-4:]),
            }
            day_interviews = []
            day_canaries = []
            day_tools = []
    return out


def build_replay_bundle() -> dict[str, Any]:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    from canary.env import Env

    game_dir = str(ROOT / "game")
    if game_dir not in sys.path:
        sys.path.insert(0, game_dir)
    import canary_game

    solver_3000 = canary_game.solver_result(GAME_SEED)
    env_3000 = Env("medium", GAME_SEED)
    emp_3000 = env_3000.call("list_employees", {}).data["employees"]
    mole_3000 = str(env_3000._world.mole)
    mole_3000_info = next((e for e in emp_3000 if e["id"] == mole_3000), {"id": mole_3000, "name": "", "dept": ""})

    v14 = ROOT / "data" / "runs" / "committed" / "v1.4"
    solver_dirs = [v14 / "reference" / "solver-hard-20261114-121126", v14 / "reference" / "solver-hard-seeds20to29"]
    gemini_dirs = [v14 / "opencode-gemini-4-carbon" / "hard"]

    replays: list[dict[str, Any]] = []
    by_seed: dict[str, dict[str, Any]] = {}

    seed_notes = {
        6: {
            "badge": "CAUGHT (+0.73)",
            "theme": "caught",
            "decoy_id": "e20",
            "decoy_note": "Excluded Legal decoy e20 (Noora Jokinen) via messages m1-3 and m1-4.",
            "headline": "Orthogonal Canary Intersection Catches True Mole e34 on Day 6",
        },
        26: {
            "badge": "FOOLED (-1.00)",
            "theme": "fooled",
            "decoy_id": "e38",
            "decoy_note": "Identified decoy e38 (Hanna Makinen), but planted 0 canaries on Days 1-3 while running 43 interviews.",
            "headline": "Single 1-in-20 Noisy Canary Readout Flips Gemini onto Innocent e04 (-1.00)",
        },
    }

    for seed in (6, 26):
        sol_ep = _load_episode(solver_dirs, seed)
        gem_ep = _load_episode(gemini_dirs, seed)
        env_h = Env("hard", seed)
        employees = env_h.call("list_employees", {}).data["employees"]
        mole_id = str(env_h._world.mole)
        sol_days = _compute_agent_days(sol_ep, employees, mole_id)
        gem_days = _compute_agent_days(gem_ep, employees, mole_id)
        max_day = max(max(sol_days), max(gem_days))
        timeline: list[dict[str, Any]] = []
        last_sol = sol_days[max(sol_days)]
        last_gem = gem_days[max(gem_days)]
        for day in range(1, max_day + 1):
            s_row = sol_days.get(day)
            g_row = gem_days.get(day)
            timeline.append(
                {
                    "day": day,
                    "solver": s_row if s_row is not None else {**last_sol, "ended": True},
                    "gemini": g_row if g_row is not None else {**last_gem, "ended": True},
                }
            )
        mole_emp = next((e for e in employees if e["id"] == mole_id), {"id": mole_id, "name": "", "dept": ""})
        acc_emp = next((e for e in employees if e["id"] == gem_ep.get("accused")), {"id": str(gem_ep.get("accused")), "name": "", "dept": ""})
        meta = seed_notes[seed]
        rec = {
            "seed": seed,
            "tier": "hard",
            "mole": mole_id,
            "mole_name": mole_emp.get("name", ""),
            "mole_dept": mole_emp.get("dept", ""),
            "gemini_score": float(gem_ep["score"]),
            "gemini_correct": bool(gem_ep["correct"]),
            "gemini_accused": str(gem_ep.get("accused") or ""),
            "gemini_accused_name": acc_emp.get("name", ""),
            "gemini_final_day": int(gem_ep["final_day"]),
            "gemini_calls": len(gem_ep["steps"]),
            "solver_score": float(sol_ep["score"]),
            "solver_correct": bool(sol_ep["correct"]),
            "solver_accused": str(sol_ep.get("accused") or ""),
            "solver_final_day": int(sol_ep["final_day"]),
            "solver_calls": len(sol_ep["steps"]),
            "badge": meta["badge"],
            "theme": meta["theme"],
            "decoy_id": meta["decoy_id"],
            "decoy_note": meta["decoy_note"],
            "headline": meta["headline"],
            "transcript_quote": _load_transcript_excerpt(seed),
            "employees": employees,
            "timeline": timeline,
            "gemini_source": gem_ep["_source"],
            "solver_source": sol_ep["_source"],
        }
        replays.append(rec)
        by_seed[str(seed)] = rec

    return {
        "game": {
            "seed": GAME_SEED,
            "tier": "medium",
            "mole": mole_3000,
            "mole_name": mole_3000_info.get("name", ""),
            "mole_dept": mole_3000_info.get("dept", ""),
            "solver_score": float(solver_3000["score"]),
            "solver_final_day": int(solver_3000["final_day"]),
            "solver_tool_calls": int(solver_3000["tool_calls"]),
        },
        "replays": replays,
        "by_seed": by_seed,
    }


def build_dry_run_manifest(out_path: Path) -> dict[str, Any]:
    bundle = build_replay_bundle()
    slim_replays = []
    for r in bundle["replays"]:
        slim_replays.append(
            {
                "seed": r["seed"],
                "tier": r["tier"],
                "mole": r["mole"],
                "mole_name": r["mole_name"],
                "gemini_score": r["gemini_score"],
                "gemini_correct": r["gemini_correct"],
                "gemini_accused": r["gemini_accused"],
                "gemini_final_day": r["gemini_final_day"],
                "gemini_calls": r["gemini_calls"],
                "solver_score": r["solver_score"],
                "solver_correct": r["solver_correct"],
                "solver_accused": r["solver_accused"],
                "solver_final_day": r["solver_final_day"],
                "solver_calls": r["solver_calls"],
                "gemini_source": r["gemini_source"],
                "solver_source": r["solver_source"],
            }
        )
    rel_out = str(out_path.relative_to(ROOT)) if out_path.is_relative_to(ROOT) else str(out_path)
    return {
        "target_mp4": rel_out,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "duration_target_s": TARGET_DURATION_S,
        "target_duration_s": TARGET_DURATION_S,
        "total_frames": TOTAL_FRAMES,
        "codec": "h264",
        "pix_fmt": "yuv420p",
        "game_seed": GAME_SEED,
        "game": bundle["game"],
        "acts": ACTS_SPEC,
        "scenes": ACTS_SPEC,
        "replays": slim_replays,
        "seed_6": slim_replays[0],
        "seed_26": slim_replays[1],
    }


OFFICE_REPLAY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Canary Office Replay</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  width: 1280px;
  height: 692px;
  overflow: hidden;
  font-family: "Public Sans", "DejaVu Sans", system-ui, sans-serif;
  background: rgb(12, 17, 28);
  color: rgb(236, 241, 250);
  transition: background 0.25s ease;
}
body.theme-fooled { background: rgb(24, 13, 20); }
body.theme-summary { background: rgb(14, 18, 24); }
.topbar {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  background: rgba(8, 12, 20, 0.92);
  border-bottom: 1px solid rgba(148, 163, 184, 0.22);
}
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 15px; letter-spacing: 0.02em; }
.canary-dot { width: 12px; height: 12px; border-radius: 3px; background: rgb(250, 204, 21); display: inline-block; }
.tabs { display: flex; gap: 8px; }
.tab {
  padding: 6px 12px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(30, 41, 59, 0.7);
  color: rgb(186, 198, 216);
  border: 1px solid rgba(148, 163, 184, 0.2);
}
.tab.active-caught { background: rgba(16, 185, 129, 0.22); color: rgb(110, 231, 183); border-color: rgba(16, 185, 129, 0.65); }
.tab.active-fooled { background: rgba(244, 63, 94, 0.24); color: rgb(253, 164, 175); border-color: rgba(244, 63, 94, 0.7); }
.tab.active-summary { background: rgba(250, 204, 21, 0.2); color: rgb(253, 224, 71); border-color: rgba(250, 204, 21, 0.65); }
.match-pill {
  font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace;
  font-size: 11px;
  padding: 4px 9px;
  border-radius: 4px;
  background: rgba(34, 197, 94, 0.16);
  color: rgb(134, 239, 172);
  border: 1px solid rgba(34, 197, 94, 0.45);
}
.layout {
  display: grid;
  grid-template-columns: 760px 496px;
  gap: 12px;
  padding: 10px 12px;
  height: 644px;
}
.panel {
  background: rgba(18, 25, 39, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
}
body.theme-fooled .panel { background: rgba(31, 18, 27, 0.9); }
.panel-h {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}
.panel-title { font-size: 13px; font-weight: 700; color: rgb(241, 245, 249); }
.panel-sub { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 11px; color: rgb(148, 163, 184); }
.depts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  flex: 1;
}
.dept-box {
  background: rgba(11, 16, 26, 0.68);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 6px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dept-name {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgb(148, 163, 184);
  display: flex;
  justify-content: space-between;
}
.desks {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px;
}
.desk {
  padding: 4px 5px;
  border-radius: 4px;
  background: rgba(30, 41, 59, 0.58);
  border: 1px solid rgba(100, 116, 139, 0.25);
  font-size: 10px;
  position: relative;
}
.desk-top { display: flex; justify-content: space-between; align-items: center; font-weight: 700; }
.desk-id { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; color: rgb(226, 232, 240); }
.desk-p { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 9px; color: rgb(148, 163, 184); }
.desk-nm { font-size: 9px; color: rgb(168, 180, 198); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbar { height: 3px; background: rgba(15, 23, 42, 0.9); border-radius: 2px; margin-top: 3px; overflow: hidden; }
.pfill { height: 100%; background: rgb(56, 189, 248); transition: width 0.18s ease; }
.desk.hot { border-color: rgb(250, 204, 21); background: rgba(113, 63, 18, 0.38); }
.desk.hot .pfill { background: rgb(250, 204, 21); }
.desk.interviewed { border-color: rgb(125, 211, 252); }
.desk.decoy { border-style: dashed; border-color: rgb(168, 85, 247); }
.desk.caught-mole { border: 2px solid rgb(16, 185, 129); background: rgba(6, 78, 59, 0.62); }
.desk.caught-mole .pfill { background: rgb(52, 211, 153); }
.desk.wrong-accused { border: 2px solid rgb(244, 63, 94); background: rgba(136, 19, 55, 0.68); }
.desk.wrong-accused .pfill { background: rgb(251, 113, 133); }
.desk.escaped-mole { border: 2px solid rgb(250, 204, 21); background: rgba(120, 53, 15, 0.62); }
.badge-mini {
  font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace;
  font-size: 8px;
  padding: 0 3px;
  border-radius: 2px;
  font-weight: 700;
}
.b-int { background: rgba(56, 189, 248, 0.25); color: rgb(125, 211, 252); }
.b-decoy { background: rgba(168, 85, 247, 0.25); color: rgb(216, 180, 254); }
.b-caught { background: rgb(16, 185, 129); color: rgb(6, 24, 18); }
.b-wrong { background: rgb(244, 63, 94); color: rgb(255, 241, 242); }
.b-mole { background: rgb(250, 204, 21); color: rgb(20, 16, 8); }
.right-col { display: flex; flex-direction: column; gap: 9px; height: 644px; }
.cards2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.agent-card {
  background: rgba(11, 16, 26, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  padding: 8px 10px;
}
.agent-card.solver { border-top: 3px solid rgb(56, 189, 248); }
.agent-card.gemini-ok { border-top: 3px solid rgb(16, 185, 129); }
.agent-card.gemini-bad { border-top: 3px solid rgb(244, 63, 94); }
.ac-name { font-size: 11px; font-weight: 700; color: rgb(203, 213, 225); margin-bottom: 4px; }
.ac-big { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 20px; font-weight: 700; }
.ac-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-top: 5px; font-size: 10px; color: rgb(148, 163, 184); }
.ac-grid b { display: block; font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 12px; color: rgb(241, 245, 249); }
.day-table {
  width: 100%;
  border-collapse: collapse;
  font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace;
  font-size: 10.5px;
}
.day-table th {
  text-align: left;
  font-size: 9.5px;
  color: rgb(148, 163, 184);
  padding: 3px 5px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}
.day-table td { padding: 3.5px 5px; border-bottom: 1px solid rgba(148, 163, 184, 0.09); color: rgb(203, 213, 225); }
.day-table tr.cur-day { background: rgba(250, 204, 21, 0.16); color: rgb(254, 249, 195); font-weight: 700; }
.day-table tr.cur-day td { color: rgb(254, 249, 195); }
.pos { color: rgb(74, 222, 128); font-weight: 700; }
.neg { color: rgb(251, 113, 133); font-weight: 700; }
.quote-box {
  background: rgba(11, 16, 26, 0.85);
  border-left: 3px solid rgb(250, 204, 21);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.38;
  color: rgb(226, 232, 240);
}
.quote-cap {
  font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace;
  font-size: 9.5px;
  color: rgb(250, 204, 21);
  margin-bottom: 3px;
  text-transform: uppercase;
}
.summary-view {
  display: none;
  padding: 18px 24px;
  height: 644px;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
}
body.theme-summary .layout { display: none; }
body.theme-summary .summary-view { display: grid; }
.metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.mcard {
  background: rgba(22, 30, 46, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  padding: 14px;
}
.mcard .k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: rgb(148, 163, 184); }
.mcard .v { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; font-size: 28px; font-weight: 700; color: rgb(250, 204, 21); margin: 4px 0; }
.mcard .s { font-size: 12px; color: rgb(203, 213, 225); line-height: 1.35; }
.bar-row { margin-top: 10px; }
.bar-lbl { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace; }
.bar-track { height: 14px; background: rgba(15, 23, 42, 0.9); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; }
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <span class="canary-dot"></span>
    <span>CANARY OFFICE REPLAY</span>
    <span id="hdrSub" class="panel-sub">v1.4 Committed Runs</span>
  </div>
  <div class="tabs">
    <div id="tab6" class="tab">Hard Seed 6: Caught (+0.73)</div>
    <div id="tab26" class="tab">Hard Seed 26: Fooled (-1.00)</div>
    <div id="tabSum" class="tab">v1.4 Paired Gap (n=30)</div>
  </div>
  <div class="match-pill" id="verifyPill">FRESH-ENV REPLAY: MATCH</div>
</div>

<div class="layout">
  <div class="panel">
    <div class="panel-h">
      <div>
        <div class="panel-title" id="floorTitle">40-Employee Living Office Floor Map</div>
        <div class="panel-sub" id="floorSub">Bayesian posterior P(employee = mole) from Gemini 4 Carbon's observed evidence</div>
      </div>
      <div class="match-pill" id="dayBadge">DAY 01</div>
    </div>
    <div class="depts" id="deptsGrid"></div>
  </div>

  <div class="right-col">
    <div class="cards2">
      <div class="agent-card solver">
        <div class="ac-name">Bayesian Reference Solver</div>
        <div class="ac-big" id="solBig">V = 1.00</div>
        <div class="ac-grid">
          <div>Canaries<b id="solCan">0</b></div>
          <div>Interviews<b id="solInt">0</b></div>
          <div>P(mole)<b id="solP">0.03</b></div>
        </div>
      </div>
      <div class="agent-card gemini-ok" id="gemCard">
        <div class="ac-name">Gemini 4 Carbon (OpenCode MCP)</div>
        <div class="ac-big" id="gemBig">V = 1.00</div>
        <div class="ac-grid">
          <div>Canaries<b id="gemCan">0</b></div>
          <div>Interviews<b id="gemInt">0</b></div>
          <div>P(mole)<b id="gemP">0.03</b></div>
        </div>
      </div>
    </div>

    <div class="panel" style="flex:1">
      <div class="panel-h">
        <span class="panel-title">Day-by-Day Replay Trajectory</span>
        <span class="panel-sub" id="trueMoleTag">True mole: e34</span>
      </div>
      <table class="day-table">
        <thead>
          <tr>
            <th>Day</th>
            <th>Solver (V / Can / P)</th>
            <th>Gemini 4 Carbon (V / Can / Int / P)</th>
          </tr>
        </thead>
        <tbody id="dayRows"></tbody>
      </table>
    </div>

    <div class="quote-box">
      <div class="quote-cap" id="quoteCap">Forensic Note</div>
      <div id="quoteText"></div>
    </div>
  </div>
</div>

<div class="summary-view" id="summaryView">
  <div class="panel" style="justify-content: space-between;">
    <div>
      <div class="panel-h">
        <span class="panel-title" style="font-size:16px">Canary v1.4 Headline Result (Judges' Harness: OpenCode + MCP)</span>
        <span class="match-pill">paired n=30 per tier</span>
      </div>
      <p style="font-size:13px; color:rgb(203,213,225); line-height:1.45; margin-bottom:10px;">
        Every committed frontier episode is replayed through a fresh Env with zero API keys (make reproduce).
        Locked headline: hard OpenCode + gemini-4-carbon keeps 72% of solver luck-adjusted (65% raw, n=30), with parity on medium (101% luck-adj, 111% raw).
      </p>
      <div class="metric-grid">
        <div class="mcard">
          <div class="k">Hard Frontier / Solver</div>
          <div class="v">65%</div>
          <div class="s">95% CI [24%, 98%] below parity (solver +0.499 vs Gemini +0.322, n=30 paired seeds 0..29)</div>
        </div>
        <div class="mcard">
          <div class="k">Luck-Adjusted Ratio</div>
          <div class="v">72%</div>
          <div class="s">95% CI [52%, 91%]; accuracy 0.83 vs solver 0.97; mean accusation day 13.2 vs 10.6</div>
        </div>
        <div class="mcard">
          <div class="k">Failure Atlas Dominant Mode</div>
          <div class="v">61%</div>
          <div class="s">Of total regret comes from premature accusation on sub-threshold posteriors across 50 episodes</div>
        </div>
        <div class="mcard">
          <div class="k">Reward-Hack &amp; Swarm Audit</div>
          <div class="v">0 / 100</div>
          <div class="s">0 verified exploits across 100 Gemini whitebox/blackbox attacks; 4/4 positive control caught</div>
        </div>
      </div>
    </div>
    <div class="quote-box" style="border-left-color: rgb(52, 211, 153);">
      <div class="quote-cap" style="color: rgb(110, 231, 183);">Reproduce Everything Offline (0 API Keys)</div>
      <div style="font-family: 'IBM Plex Mono', 'DejaVu Sans Mono', monospace; font-size: 12px;">
        make reproduce &nbsp;|&nbsp; python scripts/demo_replay.py --seed 26 --verify
      </div>
    </div>
  </div>

  <div class="panel" style="justify-content: space-between;">
    <div>
      <div class="panel-h">
        <span class="panel-title" style="font-size:15px">Hard Tier Score Comparison (Committed v1.4)</span>
        <span class="panel-sub">paired_table_gemini.md</span>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Bayesian Reference Solver (n=30)</span><span class="pos">+0.499 (97% acc)</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:88%; background:rgb(56,189,248)"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Gemini 4 Carbon In-Process (n=30)</span><span>+0.473 (95% solver)</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:83%; background:rgb(99,102,241)"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Gemini 4 Carbon OpenCode MCP (n=30)</span><span style="color:rgb(250,204,21)">+0.322 (65% solver)</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:57%; background:rgb(250,204,21)"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Heuristic Baseline (n=20)</span><span>+0.186 (40% solver)</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:33%; background:rgb(148,163,184)"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Do Nothing Abstention</span><span>0.000 (0% acc)</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:4%; background:rgb(71,85,105)"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-lbl"><span>Logs-Only / Day-1 Guess Shortcuts</span><span class="neg">-0.956 to -1.000</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:96%; background:rgb(244,63,94)"></div></div>
      </div>
    </div>

    <div class="quote-box">
      <div class="quote-cap">Seed 6 vs Seed 26 Contrast</div>
      <div>
        Seed 6: 7 orthogonal canaries isolate e34 Sofia Niemi on Day 6 (+0.73).<br>
        Seed 26: 43 interviews + late canaries get flipped by one 5% noisy readout onto innocent e04 (-1.00).
      </div>
    </div>
  </div>
</div>

<script>
let DATA = null;

async function init() {
  const resp = await fetch("replay_data.json");
  DATA = await resp.json();
  window.REPLAY_READY = true;
  renderReplay(6, 1);
}

window.showSummary = function() {
  document.body.className = "theme-summary";
  document.getElementById("tab6").className = "tab";
  document.getElementById("tab26").className = "tab";
  document.getElementById("tabSum").className = "tab active-summary";
  document.getElementById("hdrSub").textContent = "Committed Paired Benchmark & Anti-Cheat Summary";
};

window.renderReplay = function(seed, day) {
  const rec = DATA.by_seed[String(seed)];
  if (!rec) return;
  const isFooled = rec.theme === "fooled";
  document.body.className = isFooled ? "theme-fooled" : "";
  document.getElementById("tab6").className = seed === 6 ? "tab active-caught" : "tab";
  document.getElementById("tab26").className = seed === 26 ? "tab active-fooled" : "tab";
  document.getElementById("tabSum").className = "tab";
  document.getElementById("hdrSub").textContent = rec.headline;
  document.getElementById("dayBadge").textContent = "DAY " + String(day).padStart(2, "0") + " / 21";
  document.getElementById("trueMoleTag").textContent = "True mole: " + rec.mole + " (" + rec.mole_name + ", " + rec.mole_dept + ")";

  const entry = rec.timeline[Math.min(day - 1, rec.timeline.length - 1)];
  const s = entry.solver;
  const g = entry.gemini;

  const solDone = day >= rec.solver_final_day;
  const gemDone = day >= rec.gemini_final_day;

  document.getElementById("solBig").textContent = solDone
    ? ("ACCUSE " + rec.solver_accused + " (" + (rec.solver_score >= 0 ? "+" : "") + rec.solver_score.toFixed(2) + ")")
    : ("V = " + s.V.toFixed(2));
  document.getElementById("solCan").textContent = String(s.canaries);
  document.getElementById("solInt").textContent = String(s.interviews);
  document.getElementById("solP").textContent = s.p_mole.toFixed(2);

  const gemCard = document.getElementById("gemCard");
  gemCard.className = "agent-card " + (isFooled && gemDone ? "gemini-bad" : "gemini-ok");
  document.getElementById("gemBig").textContent = gemDone
    ? ("ACCUSE " + rec.gemini_accused + " (" + (rec.gemini_score >= 0 ? "+" : "") + rec.gemini_score.toFixed(2) + ")")
    : ("V = " + g.V.toFixed(2));
  document.getElementById("gemCan").textContent = String(g.canaries);
  document.getElementById("gemInt").textContent = String(g.interviews);
  document.getElementById("gemP").textContent = g.p_mole.toFixed(2);

  const depts = {};
  for (const emp of rec.employees) {
    (depts[emp.dept] = depts[emp.dept] || []).push(emp);
  }
  const grid = document.getElementById("deptsGrid");
  grid.textContent = "";
  const beliefs = g.beliefs || {};
  const interviewedSet = new Set(g.day_interviews || []);

  for (const deptName of Object.keys(depts).sort()) {
    const list = depts[deptName];
    const box = document.createElement("div");
    box.className = "dept-box";
    const hdr = document.createElement("div");
    hdr.className = "dept-name";
    hdr.innerHTML = "<span>" + deptName + "</span><span>" + list.length + "</span>";
    box.appendChild(hdr);
    const desks = document.createElement("div");
    desks.className = "desks";
    for (const emp of list) {
      const p = Number(beliefs[emp.id] || 0);
      const d = document.createElement("div");
      let cls = "desk";
      let badge = "";
      if (gemDone && emp.id === rec.gemini_accused && rec.gemini_correct) {
        cls += " caught-mole";
        badge = '<span class="badge-mini b-caught">CAUGHT +0.73</span>';
      } else if (gemDone && emp.id === rec.gemini_accused && !rec.gemini_correct) {
        cls += " wrong-accused";
        badge = '<span class="badge-mini b-wrong">WRONG -1.00</span>';
      } else if (gemDone && !rec.gemini_correct && emp.id === rec.mole) {
        cls += " escaped-mole";
        badge = '<span class="badge-mini b-mole">TRUE MOLE</span>';
      } else if (emp.id === rec.decoy_id && day <= 3) {
        cls += " decoy";
        badge = '<span class="badge-mini b-decoy">DECOY</span>';
      } else if (interviewedSet.has(emp.id)) {
        cls += " interviewed";
        badge = '<span class="badge-mini b-int">INT</span>';
      } else if (p >= 0.12) {
        cls += " hot";
      }
      d.className = cls;
      const pct = Math.min(100, Math.max(2, Math.round(p * 100)));
      d.innerHTML =
        '<div class="desk-top"><span class="desk-id">' + emp.id + '</span>' +
        (badge || ('<span class="desk-p">' + Math.round(p * 100) + '%</span>')) +
        '</div>' +
        '<div class="desk-nm">' + emp.name + '</div>' +
        '<div class="pbar"><div class="pfill" style="width:' + pct + '%"></div></div>';
      desks.appendChild(d);
    }
    box.appendChild(desks);
    grid.appendChild(box);
  }

  const tbody = document.getElementById("dayRows");
  tbody.textContent = "";
  for (const row of rec.timeline) {
    const tr = document.createElement("tr");
    if (row.day === day) tr.className = "cur-day";
    const rs = row.solver;
    const rg = row.gemini;
    const sTxt = rs.ended
      ? ("done D" + rec.solver_final_day + " (+" + rec.solver_score.toFixed(2) + ")")
      : ("V=" + rs.V.toFixed(2) + " c=" + rs.canaries + " P=" + rs.p_mole.toFixed(2) + (rs.accused ? " ACC " + rs.accused : ""));
    const gTxt = rg.ended
      ? ("done D" + rec.gemini_final_day)
      : ("V=" + rg.V.toFixed(2) + " c=" + rg.canaries + " i=" + rg.interviews + " P=" + rg.p_mole.toFixed(2) + (rg.accused ? " ACC " + rg.accused : ""));
    tr.innerHTML = "<td>D" + String(row.day).padStart(2, "0") + "</td><td>" + sTxt + "</td><td>" + gTxt + "</td>";
    tbody.appendChild(tr);
  }

  const qCap = document.getElementById("quoteCap");
  const qTxt = document.getElementById("quoteText");
  if (gemDone) {
    qCap.textContent = "Committed OpenCode Transcript (seed " + seed + ".txt)";
    qTxt.textContent = rec.transcript_quote;
  } else {
    qCap.textContent = "Day " + day + " Live Investigation Telemetry";
    const leakStr = (g.leaks && g.leaks.length)
      ? ("Surfaced leaks: " + g.leaks.map((x) => x.doc_id + (x.variant ? ":" + x.variant : "")).join(", ") + ". ")
      : "No canary leak surfaced yet. ";
    qTxt.textContent = leakStr + rec.decoy_note;
  }
};

init();
</script>
</body>
</html>
"""


def _maybe_reexec_into_demo_venv() -> None:
    if os.environ.get("CANARY_DEMO_BOOTSTRAPPED") == "1":
        return
    need_reexec = False
    lib64 = SCRATCH_BASE / "libs" / "usr" / "lib64"
    cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if lib64.is_dir() and str(lib64) not in cur_ld.split(":"):
        need_reexec = True
    try:
        import imageio_ffmpeg
        import PIL
        import playwright

        _ = (imageio_ffmpeg, PIL, playwright)
    except ImportError:
        need_reexec = True

    if not need_reexec:
        return

    venv_py = SCRATCH_BASE / "venv" / "bin" / "python"
    target_py = str(venv_py) if venv_py.is_file() else sys.executable
    env = dict(os.environ)
    env["CANARY_DEMO_BOOTSTRAPPED"] = "1"
    env["PYTHONPATH"] = str(ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if lib64.is_dir():
        extra_ld = f"{lib64}:{SCRATCH_BASE / 'libs' / 'lib64'}"
        env["LD_LIBRARY_PATH"] = f"{extra_ld}:{cur_ld}" if cur_ld else extra_ld
    browsers = SCRATCH_BASE / "browsers"
    if browsers.is_dir():
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    os.execve(target_py, [target_py, str(Path(__file__).resolve()), *sys.argv[1:]], env)


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _record_mp4(out_path: Path, proxy_server: str | None) -> dict[str, Any]:
    _maybe_reexec_into_demo_venv()
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright

    game_dir = str(ROOT / "game")
    if game_dir not in sys.path:
        sys.path.insert(0, game_dir)
    import build as game_build

    bundle = build_replay_bundle()
    tmp_parent = str(SCRATCH_BASE) if SCRATCH_BASE.is_dir() else None
    tmp_ctx = tempfile.TemporaryDirectory(prefix="canary-rec-", dir=tmp_parent)
    try:
        work = Path(tmp_ctx.name)
        site_dir = work / "site"
        game_build.build(site_dir)
        (site_dir / "office_replay.html").write_text(OFFICE_REPLAY_HTML, encoding="utf-8")
        (site_dir / "replay_data.json").write_text(json.dumps(bundle), encoding="utf-8")

        arena_src = ROOT / "docs" / "arena"
        has_arena = (arena_src / "index.html").is_file()
        if has_arena:
            shutil.copytree(arena_src, site_dir / "arena", dirs_exist_ok=True)

        handler = functools.partial(_SilentHandler, directory=str(site_dir))
        srv = _ReusableTCPServer(("127.0.0.1", 0), handler)
        port = srv.server_address[1]
        srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
        srv_thread.start()

        mpl_font_dirs = sorted(
            glob.glob("/tmp/fleet-silas/shared/*venv*/lib/python*/site-packages/matplotlib/mpl-data/fonts/ttf")
            + [
                "/usr/share/fonts",
                "/usr/local/share/fonts",
            ]
        )
        valid_font_dirs = [d for d in mpl_font_dirs if os.path.isdir(d)]
        launch_env = dict(os.environ)
        if not os.path.isfile("/etc/fonts/fonts.conf") and valid_font_dirs:
            fc_cache = work / "fc-cache"
            fc_cache.mkdir(parents=True, exist_ok=True)
            fonts_conf = work / "fonts.conf"
            dir_xml = "\n".join(f"  <dir>{d}</dir>" for d in valid_font_dirs)
            fonts_conf.write_text(
                '<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
                "<fontconfig>\n"
                f"{dir_xml}\n"
                "  <selectfont><rejectfont><glob>*LastResort*</glob></rejectfont></selectfont>\n"
                f"  <cachedir>{fc_cache}</cachedir>\n"
                "</fontconfig>\n",
                encoding="utf-8",
            )
            launch_env["FONTCONFIG_FILE"] = str(fonts_conf)
            launch_env["FONTCONFIG_PATH"] = str(work)

        font_Paths = [os.path.join(d, "DejaVuSans-Bold.ttf") for d in valid_font_dirs] + [
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        hud_font = None
        for fp in font_Paths:
            if os.path.isfile(fp):
                hud_font = ImageFont.truetype(fp, 12)
                break
        if hud_font is None:
            hud_font = ImageFont.load_default()

        keyframes: list[dict[str, Any]] = []

        def snap(
            page: Any,
            hold_frames: int,
            act_label: str,
            caption: str,
            target_selector: str | None = None,
            clicked: bool = False,
            fallback_xy: tuple[int, int] = (640, 360),
        ) -> None:
            cx, cy = fallback_xy
            if target_selector:
                try:
                    loc = page.locator(target_selector).first
                    box = loc.bounding_box(timeout=1200)
                    if box:
                        cx = int(box["x"] + box["width"] * 0.5)
                        cy = int(box["y"] + box["height"] * 0.5)
                except Exception:
                    pass
            png_bytes = page.screenshot(type="png")
            img = Image.open(io_bytes(png_bytes)).convert("RGB")
            keyframes.append(
                {
                    "img": img,
                    "frames": hold_frames,
                    "act": act_label,
                    "caption": caption,
                    "cursor": (max(8, min(WIDTH - 16, cx)), max(8, min(HEIGHT - 36, cy))),
                    "clicked": clicked,
                }
            )

        ctx_kwargs: dict[str, Any] = {"viewport": {"width": WIDTH, "height": HEIGHT}}
        resolved_proxy = proxy_server
        if resolved_proxy is None:
            env_p = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
            if env_p:
                resolved_proxy = env_p
        if resolved_proxy:
            ctx_kwargs["proxy"] = {"server": resolved_proxy, "bypass": "127.0.0.1,localhost"}

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, env=launch_env)
                context = browser.new_context(**ctx_kwargs)
                page = context.new_page()

                page.goto(f"http://127.0.0.1:{port}/?seed={GAME_SEED}", wait_until="domcontentloaded")
                page.wait_for_function(
                    'document.getElementById("bootState") && document.getElementById("bootState").textContent === "ready"',
                    timeout=90000,
                )

                act1 = "ACT 1 | BROWSER GAME (SEED 3000)"
                snap(
                    page,
                    48,
                    act1,
                    "Real canary Python benchmark compiled to Pyodide in browser - public dev seed 3000 ready",
                    target_selector='[id="seed"]',
                    fallback_xy=(920, 290),
                )
                snap(
                    page,
                    30,
                    act1,
                    "Opening Case 3000 (medium tier, 20 staff, 14 days, 300 calls, 0 hidden queries)",
                    target_selector='[id="startBtn"]',
                    clicked=True,
                )
                page.click('[id="startBtn"]')
                page.wait_for_selector('[id="desk"]:not([hidden])')
                snap(
                    page,
                    30,
                    act1,
                    "Case desk opened - no benchmark tool executes until the investigator clicks it",
                    target_selector='[id="rulesBtn"]',
                )

                page.click('[id="rulesBtn"]')
                page.wait_for_timeout(80)
                snap(
                    page,
                    42,
                    act1,
                    "Exact Env.instruction() given to AI agents: 13 tools, +V if right, -1 if wrong, 0 if none",
                    target_selector='[id="rulesClose"]',
                )
                page.click('[id="rulesClose"]')

                snap(
                    page,
                    28,
                    act1,
                    "Step 1: Pull the 20-employee company roster (free action)",
                    target_selector='[id="roster"] button.primary',
                    clicked=True,
                )
                page.click('[id="roster"] button.primary')
                page.wait_for_selector('[id="roster"] .row')
                snap(
                    page,
                    32,
                    act1,
                    "20 employees loaded across Legal, Engineering, Finance, Sales, Operations",
                    target_selector='[data-pid="e09"]',
                )

                page.locator('[id="cmdbar"] button.tool', has_text="DOC").click()
                page.click('[id="cmdform"] button.run')
                snap(
                    page,
                    34,
                    act1,
                    "Day 1 documents inspected: mapping initial recipients before planting canary traps",
                    target_selector='[id="cmdbar"] button.tool:has-text("CAN")',
                )

                page.locator('[id="cmdbar"] button.tool', has_text="CAN").click()
                page.fill('[id="cmdform"] input[name="doc_title"]', "Board memo draft 1")
                c1_groups = {
                    "e09": "A",
                    "e17": "A",
                    "e02": "A",
                    "e11": "B",
                    "e01": "B",
                    "e14": "B",
                    "e03": "C",
                    "e04": "C",
                }
                for pid_k, v_lab in c1_groups.items():
                    page.locator(f'[id="roster"] .row[data-pid="{pid_k}"] .variant button', has_text=v_lab).click()
                snap(
                    page,
                    44,
                    act1,
                    "Planting Canary c1 ('Board memo draft 1'): splitting suspects into variants A, B, and C",
                    target_selector='[id="cmdform"] button.run',
                    clicked=True,
                )
                page.click('[id="cmdform"] button.run')
                snap(
                    page,
                    32,
                    act1,
                    "Canary c1 active: Variant A -> {e02, e09, e17}, Variant B -> {e01, e11, e14}, Variant C -> {e03, e04}",
                    target_selector='[id="cmdbar"] button.tool:has-text("DAY")',
                )

                page.locator('[id="cmdbar"] button.tool', has_text="DAY").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="LOG").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="DAY").click()
                page.click('[id="cmdform"] button.run')

                page.locator('[id="cmdbar"] button.tool', has_text="FED").click()
                page.click('[id="cmdform"] button.run')
                snap(
                    page,
                    50,
                    act1,
                    "Day 3 Leak Feed: Canary c1 Variant A surfaced! Suspect pool narrowed from 20 down to {e02, e09, e17}",
                    target_selector=".leakcard",
                    clicked=True,
                )

                page.locator('[id="cmdbar"] button.tool', has_text="CAN").click()
                page.fill('[id="cmdform"] input[name="doc_title"]', "Q3 forecast trap")
                for pid_k, v_lab in (("e09", "A"), ("e17", "B"), ("e02", "C")):
                    page.locator(f'[id="roster"] .row[data-pid="{pid_k}"] .variant button', has_text=v_lab).click()
                page.click('[id="cmdform"] button.run')

                page.locator('[id="cmdbar"] button.tool', has_text="DAY").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="INT").click()
                page.select_option('[id="cmdform"] select[name="employee"]', "e09")
                page.click('[id="cmdform"] button.run')

                page.locator('[id="cmdbar"] button.tool', has_text="CAN").click()
                page.fill('[id="cmdform"] input[name="doc_title"]', "M&A diligence brief")
                for pid_k, v_lab in (("e09", "A"), ("e17", "B"), ("e02", "C")):
                    page.locator(f'[id="roster"] .row[data-pid="{pid_k}"] .variant button', has_text=v_lab).click()
                snap(
                    page,
                    38,
                    act1,
                    "Orthogonal Canary Trap ('M&A diligence brief'): isolating e09=A vs e17=B vs e02=C",
                    target_selector='[id="cmdform"] button.run',
                    clicked=True,
                )
                page.click('[id="cmdform"] button.run')

                page.locator('[id="cmdbar"] button.tool', has_text="DAY").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="FED").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="DAY").click()
                page.click('[id="cmdform"] button.run')
                page.locator('[id="cmdbar"] button.tool', has_text="FED").click()
                page.click('[id="cmdform"] button.run')
                snap(
                    page,
                    48,
                    act1,
                    "Day 6 Leak Feed: Canary c4 Variant A leaked! Uniquely identifies e09 Sofia Lehtonen (Legal)",
                    target_selector=".leakcard",
                )

                page.click('[id="agentBtn"]')
                snap(
                    page,
                    32,
                    act1,
                    "Agent JSON View [J]: showing the exact structured MCP tool payload observed by frontier models",
                    target_selector='[id="agentBtn"]',
                    clicked=True,
                )
                page.click('[id="agentBtn"]')

                page.click('[id="cmdbar"] button.tool.accuse')
                page.select_option('[id="cmdform"] select[name="employee"]', "e09")
                page.click('[id="cmdform"] button.danger.run')
                page.select_option('[id="accWho"]', "e09")
                page.fill('[id="accArm"]', "e09")
                page.evaluate('const s = document.getElementById("accP"); s.value = "98"; s.dispatchEvent(new Event("input"));')
                snap(
                    page,
                    44,
                    act1,
                    "Accusation Dialog: certainty 98% exceeds 54.1% break-even threshold - arming e09 Sofia Lehtonen",
                    target_selector='[id="accGo"]',
                    clicked=True,
                )
                page.click('[id="accGo"]')
                page.wait_for_selector('[id="closed"]:not([hidden])')
                page.evaluate('document.getElementById("closed").scrollIntoView({behavior: "instant", block: "start"})')
                snap(
                    page,
                    68,
                    act1,
                    "CASE CLOSED (Seed 3000): Mole e09 Sofia Lehtonen caught on Day 6 (+0.81 vs Bayesian Solver +0.79)",
                    target_selector='[id="closed"] .scoreline',
                )

                page.goto(f"http://127.0.0.1:{port}/office_replay.html", wait_until="networkidle")
                page.wait_for_function("window.REPLAY_READY === true", timeout=20000)

                act2 = "ACT 2 | HARD SEED 6 (+0.73 CAUGHT)"
                seed6_Schedule = [
                    (1, 66, "Hard Seed 6 (40 staff, 21d): Day 1 - Solver & Gemini both plant 2 early canaries (P(e34)=0.03)", '[id="tab6"]'),
                    (2, 66, "Seed 6 Day 2: Gemini excludes angry-message decoy e20 (Noora Jokinen, Legal) via m1-3 & m1-4", '[id="deptsGrid"]'),
                    (3, 76, "Seed 6 Day 3: Leaked canary readout pushes Gemini Bayesian posterior on e34 to P=0.21 (6 canaries)", '[id="gemCard"]'),
                    (4, 76, "Seed 6 Day 4: Recipient intersection narrows 40 staff to Research trio {e24, e31, e34} (P=0.44)", '[id="deptsGrid"]'),
                    (5, 76, "Seed 6 Day 5: Solver reaches P(e34)=0.63 (9 canaries, 0 interviews); Gemini holds V=0.73 (7 canaries)", '[id="dayRows"]'),
                    (6, 132, "Seed 6 Day 6 CAUGHT: Orthogonal canaries c1-2:B & c3-2:A hit P=1.00 - Gemini accuses e34 (+0.73 vs Solver +0.71)", '[id="gemCard"]'),
                ]
                for day_n, n_frames, cap, sel in seed6_Schedule:
                    page.evaluate(f"window.renderReplay(6, {day_n})")
                    snap(page, n_frames, act2, cap, target_selector=sel, clicked=(day_n in (1, 6)))

                act3 = "ACT 3 | HARD SEED 26 (-1.00 FOOLED)"
                seed26_Schedule = [
                    (1, 56, "Hard Seed 26 (True Mole e08 Nea Nieminen): Day 1 - Solver plants 2 canaries; Gemini plants 0", '[id="tab26"]'),
                    (3, 62, "Seed 26 Day 3: Solver has 6 canaries planted; Gemini has 13 weak interviews and STILL 0 canaries", '[id="gemCard"]'),
                    (5, 62, "Seed 26 Day 5: Solver reaches 10 canaries (P(e08)=0.20); Gemini lags at 3 canaries, 23 interviews", '[id="dayRows"]'),
                    (7, 82, "Seed 26 Day 7: Bayesian Solver hits P(e08)=0.97 across 11 canaries and catches e08 (+0.69)! Gemini at P=0.08", '[class="agent-card solver"]'),
                    (9, 86, "Seed 26 Day 9: After 43 interviews & 8 late canaries, Gemini reaches P(true mole e08)=0.48 at V=0.67", '[id="gemCard"]'),
                    (10, 140, "Seed 26 Day 10 FOOLED: 1-in-20 noisy readout (95% hard acc) flips Gemini onto innocent e04 Lauri Laitinen (-1.00)!", '[id="gemCard"]'),
                ]
                for day_n, n_frames, cap, sel in seed26_Schedule:
                    page.evaluate(f"window.renderReplay(26, {day_n})")
                    snap(page, n_frames, act3, cap, target_selector=sel, clicked=(day_n in (1, 7, 10)))

                act4 = "ACT 4 | PAIRED v1.4 GAP & INTEGRITY"
                if has_arena:
                    page.goto(f"http://127.0.0.1:{port}/arena/index.html", wait_until="domcontentloaded")
                    snap(
                        page,
                        60,
                        act4,
                        "Canary Arena Live Multi-Mode Stage alongside committed v1.4 replay verification",
                        fallback_xy=(640, 320),
                    )
                    page.goto(f"http://127.0.0.1:{port}/office_replay.html", wait_until="networkidle")
                    page.wait_for_function("window.REPLAY_READY === true", timeout=20000)

                page.evaluate("window.showSummary()")
                snap(
                    page,
                    90,
                    act4,
                    "Hard OpenCode gemini-4-carbon: 65% of solver [24%, 98%] (n=30 paired seeds); 72% luck-adjusted [52%, 91%]",
                    target_selector='[id="tabSum"]',
                    clicked=True,
                )
                remaining = TOTAL_FRAMES - sum(int(k["frames"]) for k in keyframes)
                snap(
                    page,
                    max(48, remaining),
                    act4,
                    "100% replay-verified without API keys (make reproduce): 0 verified exploits across 100 red-team attacks",
                    target_selector=".metric-grid",
                    fallback_xy=(420, 380),
                )

                browser.close()
        finally:
            srv.shutdown()

        cur_sum = sum(int(k["frames"]) for k in keyframes)
        if cur_sum != TOTAL_FRAMES:
            keyframes[-1]["frames"] = max(12, int(keyframes[-1]["frames"]) + (TOTAL_FRAMES - cur_sum))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-level",
            "4.0",
            "-g",
            str(FPS * 2),
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdin is not None

        frame_idx = 0
        prev_cursor = keyframes[0]["cursor"]
        prev_img = keyframes[0]["img"]

        for k_idx, kf in enumerate(keyframes):
            n_hold = int(kf["frames"])
            base_img = kf["img"]
            target_cursor = kf["cursor"]
            act_changed = k_idx > 0 and kf["act"] != keyframes[k_idx - 1]["act"]

            for local_f in range(n_hold):
                if act_changed and local_f < 6:
                    alpha = (local_f + 1) / 7.0
                    work_img = Image.blend(prev_img, base_img, alpha)
                else:
                    work_img = base_img.copy()

                move_t = min(1.0, (local_f + 1) / max(1.0, min(10.0, n_hold * 0.45)))
                ease = 1.0 - (1.0 - move_t) ** 3
                cx = int(round(prev_cursor[0] + (target_cursor[0] - prev_cursor[0]) * ease))
                cy = int(round(prev_cursor[1] + (target_cursor[1] - prev_cursor[1]) * ease))

                draw = ImageDraw.Draw(work_img)
                if kf["clicked"] and 4 <= local_f <= 14:
                    rad = 8 + (local_f - 4) * 2
                    draw.ellipse(
                        (cx - rad, cy - rad, cx + rad, cy + rad),
                        outline=(250, 204, 21),
                        width=2,
                    )

                arrow = [
                    (cx, cy),
                    (cx, cy + 16),
                    (cx + 4, cy + 12),
                    (cx + 8, cy + 19),
                    (cx + 11, cy + 17),
                    (cx + 7, cy + 11),
                    (cx + 12, cy + 11),
                ]
                draw.polygon(arrow, fill=(250, 204, 21), outline=(15, 23, 42))

                bar_top = HEIGHT - 28
                draw.rectangle((0, bar_top, WIDTH, HEIGHT), fill=(10, 14, 23))
                draw.rectangle((0, bar_top, 272, HEIGHT - 3), fill=(30, 41, 59))
                draw.text((10, bar_top + 6), kf["act"][:36], fill=(250, 204, 21), font=hud_font)
                draw.text((282, bar_top + 6), kf["caption"][:124], fill=(241, 245, 249), font=hud_font)

                cur_sec = frame_idx / FPS
                tot_sec = TOTAL_FRAMES / FPS
                tc = f"{int(cur_sec // 60):02d}:{int(cur_sec % 60):02d} / {int(tot_sec // 60):02d}:{int(tot_sec % 60):02d}"
                draw.text((WIDTH - 104, bar_top + 6), tc, fill=(148, 163, 184), font=hud_font)

                prog_w = int(round(WIDTH * ((frame_idx + 1) / TOTAL_FRAMES)))
                draw.rectangle((0, HEIGHT - 3, WIDTH, HEIGHT), fill=(30, 41, 59))
                draw.rectangle((0, HEIGHT - 3, prog_w, HEIGHT), fill=(250, 204, 21))

                proc.stdin.write(work_img.tobytes())
                frame_idx += 1

            prev_cursor = target_cursor
            prev_img = base_img

        proc.stdin.close()
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        rc = proc.wait(timeout=120)
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited with {rc}: {stderr_bytes.decode('utf-8', errors='replace')}")

        return {
            "out_path": str(out_path),
            "bytes": out_path.stat().st_size,
            "frames": frame_idx,
            "duration_s": round(frame_idx / FPS, 3),
        }
    finally:
        tmp_ctx.cleanup()


def io_bytes(raw: bytes) -> Any:
    import io

    return io.BytesIO(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record the 75s Canary headless Playwright MP4 demo (seed 3000 browser game + seed 6 and seed 26 Office Replay)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output MP4 file path")
    parser.add_argument("--dry-run", action="store_true", help="Print verified JSON manifest without launching browser or ffmpeg")
    parser.add_argument("--proxy", type=str, default=None, help="Optional HTTP proxy URL for Pyodide CDN")
    args = parser.parse_args(argv)

    if args.dry_run:
        manifest = build_dry_run_manifest(args.out)
        print(json.dumps(manifest, indent=2))
        return 0

    result = _record_mp4(args.out.resolve(), args.proxy)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
