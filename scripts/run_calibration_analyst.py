from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import calibration, lab_client
from canary.llm import register_script

ROLE = "failure_analyst"
SUBROLE = "bayesian_calibration_analyst"
FEATURE = "calibration_analyst"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_RUNS_DIR = Path("data/runs/committed")
DEFAULT_OUT_DIR = Path("results/gemini_roles/failure_analyst/calibration-ev-carbon")

MD_H1 = chr(35)
MD_H2 = chr(35) * 2
MD_H3 = chr(35) * 3

TRIGGER_ENUM = [
    "horizon_deadline_panic",
    "value_bleed_threshold_blindness",
    "framing_decoy_suboptimal_target",
    "early_snap_accusation",
    "under_informative_canary_design",
]

QUOTE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode_id": {
            "type": "string",
            "description": "Exact EPISODE identifier from the === EPISODE <id> === header.",
        },
        "quote": {
            "type": "string",
            "description": (
                "Exact character-for-character verbatim numbered step line starting with [S...] "
                "copied without any modification or ellipsis from that episode block."
            ),
        },
    },
    "required": ["episode_id", "quote"],
}

CALIBRATION_DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": (
                "Concise quantitative synthesis of why frontier investigators commit prematurely "
                "below the rational Bayesian break-even threshold 1 / (1 + V_true). Use plain ASCII hyphens only."
            ),
        },
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "trigger_id": {"type": "string", "enum": TRIGGER_ENUM},
                    "title": {"type": "string"},
                    "episode_ids": {"type": "array", "items": {"type": "string"}},
                    "mechanism": {"type": "string"},
                    "mitigation": {"type": "string"},
                    "quotes": {"type": "array", "items": QUOTE_ITEM_SCHEMA},
                },
                "required": ["trigger_id", "title", "episode_ids", "mechanism", "mitigation", "quotes"],
            },
        },
        "episode_diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "string"},
                    "primary_trigger": {"type": "string", "enum": TRIGGER_ENUM},
                    "rationale": {"type": "string"},
                    "trigger_quote": QUOTE_ITEM_SCHEMA,
                },
                "required": ["episode_id", "primary_trigger", "rationale", "trigger_quote"],
            },
        },
    },
    "required": ["executive_summary", "clusters", "episode_diagnoses"],
}

SYSTEM_PROMPT = (
    "You are the Bayesian Calibration Failure Analyst for the Canary insider-leak benchmark.\n"
    "In Canary, accusing the true mole yields +V_true (remaining company value in [0, 1]), "
    "accusing an innocent employee yields -1.0, and abstaining yields 0.0.\n"
    "Therefore accusing suspect e with exact Bayesian posterior P(e == mole) has expected value:\n"
    "  EV(accuse e) = P * V_true - (1 - P) = P * (1 + V_true) - 1.\n"
    "Rational accusation requires P(accused == mole) >= 1 / (1 + V_true). Whenever V_true bleeds "
    "down from 1.0 toward 0.5, the break-even posterior rises from 0.500 to 0.667.\n\n"
    "You are given ALL committed frontier episodes that violated rational EV gating "
    "(P_accused < 1 / (1 + V_true)), packed with their exact solver-computed calibration header "
    "and numbered verbatim tool-step lines [S000], [S001], ...\n\n"
    "STRICT REQUIREMENTS:\n"
    "1. Diagnose 3 to 5 distinct premature-commit failure trigger clusters across the corpus.\n"
    "2. Provide an episode_diagnoses entry for EVERY EPISODE in the input corpus (exact same episode_id).\n"
    "3. EVERY quote (in clusters[].quotes and in episode_diagnoses[].trigger_quote) MUST set episode_id "
    "to an exact EPISODE id from the input and set quote to an ENTIRE numbered step line starting with "
    "[S...] copied character-for-character from that exact episode block. Never alter spacing, never "
    "truncate with '...', and never invent step numbers or lines.\n"
    "4. Never use em dashes or en dashes anywhere; use plain ASCII '-' or commas/colons instead.\n"
    "5. Output valid JSON matching the schema only."
)


def sanitize_text(text: str) -> str:
    s = str(text or "")
    s = s.replace("\u2014", " - ").replace("\u2013", "-").replace("\u2012", "-").replace("\u2015", "-")
    return s


def _clean_inline(val: Any, max_len: int = 80) -> str:
    s = str(val if val is not None else "")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", "'").replace("\u201d", "'")
    s = s.replace("\u2026", "...")
    s = sanitize_text(s)
    s = s.replace('"', "'").replace("\\", "/").replace("`", "'").replace(chr(35), "")
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in s)
    s = re.sub(r" +", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s


def current_git_commit(cwd: Path = ROOT) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return res.stdout.strip()


def _step_to_dict(st: Any) -> dict[str, Any]:
    if isinstance(st, dict):
        return st
    if is_dataclass(st):
        return asdict(st)
    return {
        "t": getattr(st, "t", None),
        "day": getattr(st, "day", None),
        "tool": getattr(st, "tool", None),
        "args": getattr(st, "args", None),
        "result": getattr(st, "result", None),
    }


def format_step_line(idx: int, raw_step: Any) -> str:
    step = _step_to_dict(raw_step)
    day = step.get("day", "?")
    tool = _clean_inline(step.get("tool", "unknown"), 40)
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    res = step.get("result") if isinstance(step.get("result"), dict) else {}
    ok = bool(res.get("ok", True))
    data = res.get("data") if isinstance(res.get("data"), dict) else {}

    prefix = f"[S{idx:03d}] d{day}"
    if not ok:
        err = _clean_inline(res.get("error") or "error", 72)
        arg_s = ", ".join(f"{_clean_inline(k, 20)}={_clean_inline(v, 28)}" for k, v in sorted(args.items()))
        return f"{prefix} {tool}({arg_s}) -> ERR {err}"

    if tool == "list_employees":
        emps = data.get("employees") if isinstance(data.get("employees"), list) else []
        return f"{prefix} list_employees() -> ok count={len(emps)}"

    if tool == "list_documents":
        docs = data.get("documents") if isinstance(data.get("documents"), list) else []
        doc_ids = ",".join(
            _clean_inline(d.get("doc_id", ""), 16) for d in docs[:6] if isinstance(d, dict)
        )
        d_from = args.get("day_from", day)
        d_to = args.get("day_to", day)
        return f"{prefix} list_documents(day={d_from}..{d_to}) -> ok count={len(docs)} docs=[{doc_ids}]"

    if tool == "plant_canary":
        asgn = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
        counts = Counter(_clean_inline(v, 8) for v in asgn.values())
        split_s = ",".join(f"{k}:{c}" for k, c in sorted(counts.items())) or "none"
        cid = _clean_inline(data.get("canary_id", ""), 20)
        return f"{prefix} plant_canary(split={split_s}, assigned={len(asgn)}) -> ok canary_id={cid}"

    if tool == "check_leak_feed":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        leaks = [
            f"{_clean_inline(it.get('doc_id', '?'), 16)}:{_clean_inline(it.get('variant', 'base'), 8)}@d{it.get('surfaced_day', '?')}"
            for it in items[:6]
            if isinstance(it, dict)
        ]
        return f"{prefix} check_leak_feed() -> ok leaks=[{', '.join(leaks)}]"

    if tool == "read_access_logs":
        logs = data.get("logs") if isinstance(data.get("logs"), list) else []
        ah_counts = Counter(
            _clean_inline(lg.get("employee", "?"), 10)
            for lg in logs
            if isinstance(lg, dict) and lg.get("after_hours")
        )
        top_ah = ",".join(
            f"{emp}:{cnt}" for emp, cnt in sorted(ah_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        )
        d_from = args.get("day_from", day)
        d_to = args.get("day_to", day)
        return f"{prefix} read_access_logs(day={d_from}..{d_to}) -> ok count={len(logs)} after_hours=[{top_ah}]"

    if tool == "search_messages":
        msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
        q = _clean_inline(args.get("query", ""), 28)
        d_from = args.get("day_from", day)
        d_to = args.get("day_to", day)
        return f"{prefix} search_messages(query='{q}', day={d_from}..{d_to}) -> ok matches={len(msgs)}"

    if tool == "read_message":
        mid = _clean_inline(args.get("id", ""), 20)
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        sender = _clean_inline(msg.get("sender", "?"), 12)
        ch = _clean_inline(msg.get("channel", ""), 20)
        return f"{prefix} read_message(id={mid}) -> ok sender={sender} channel={ch}"

    if tool == "interview":
        emp = _clean_inline(args.get("employee", "?"), 12)
        topic = _clean_inline(args.get("topic", "?"), 24)
        ans = _clean_inline(data.get("answer", ""), 60)
        return f"{prefix} interview(employee={emp}, topic={topic}) -> ok ans='{ans}'"

    if tool == "restrict_access":
        emp = _clean_inline(args.get("employee") or data.get("restricted") or "?", 12)
        return f"{prefix} restrict_access(employee={emp}) -> ok restricted={emp}"

    if tool == "unrestrict_access":
        emp = _clean_inline(args.get("employee") or data.get("unrestricted") or "?", 12)
        return f"{prefix} unrestrict_access(employee={emp}) -> ok unrestricted={emp}"

    if tool == "advance_day":
        nd = data.get("day", "?")
        v_val = data.get("V")
        v_str = f"{float(v_val):.3f}" if isinstance(v_val, (int, float)) else "?"
        return f"{prefix} advance_day() -> ok next_day={nd} V={v_str}"

    if tool == "status":
        v_val = data.get("V")
        v_str = f"{float(v_val):.3f}" if isinstance(v_val, (int, float)) else "?"
        acts = data.get("actions_left_today", "?")
        cans = len(data.get("canaries_planted") or [])
        rest = len(data.get("restricted") or [])
        return f"{prefix} status() -> ok V={v_str} actions_left={acts} canaries={cans} restricted={rest}"

    if tool == "accuse":
        emp = _clean_inline(args.get("employee") or data.get("accused") or "?", 12)
        return f"{prefix} accuse(employee={emp}) -> ok accused={emp}"

    arg_s = ", ".join(f"{_clean_inline(k, 20)}={_clean_inline(v, 28)}" for k, v in sorted(args.items()))
    return f"{prefix} {tool}({arg_s}) -> ok"


def collect_premature_episodes(
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    include_reference: bool = False,
    tier: str | None = None,
    agent_prefix: str = "",
    extra_runs: list[str | Path] | tuple[str | Path, ...] = (),
) -> list[dict[str, Any]]:
    roots = [runs_dir, *extra_runs]
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for root in roots:
        rparts = Path(root).parts
        for ep, rel_parts, dir_meta in calibration._scan_root(root):
            if tier and ep.get("tier") != tier:
                continue
            if agent_prefix and not str(ep.get("agent", "")).startswith(agent_prefix):
                continue
            rec = calibration.analyze_episode(ep, rel_parts=rel_parts, dir_meta=dir_meta, root_parts=rparts)
            if rec["family"] == "reference" and not include_reference:
                continue
            p_acc = rec.get("p_accused")
            thr = float(rec["threshold"])
            if rec["did_accuse"] and p_acc is not None and float(p_acc) < thr and rec["premature_commit"]:
                found.append((ep, rec))

    found.sort(
        key=lambda pair: (
            -float(pair[1]["ev_lost"]),
            str(pair[1].get("version") or ""),
            str(pair[1].get("agent") or ""),
            str(pair[1].get("thinking_level") or ""),
            str(pair[1].get("tier") or ""),
            int(pair[1].get("seed") or 0),
        )
    )

    used_ids: set[str] = set()
    items: list[dict[str, Any]] = []
    for ep, rec in found:
        base_id = f"{rec['version']}:{rec['agent']}:{rec['tier']}:s{rec['seed']}"
        ep_id = base_id
        dup = 2
        while ep_id in used_ids:
            ep_id = f"{base_id}:dup{dup}"
            dup += 1
        used_ids.add(ep_id)
        items.append({"episode_id": ep_id, "episode": ep, "calibration": rec})
    return items


def pack_premature_episodes(
    items: list[dict[str, Any]],
    max_steps_per_episode: int = 200,
) -> tuple[str, dict[str, str], dict[str, list[str]]]:
    blocks: dict[str, str] = {}
    step_lines_by_ep: dict[str, list[str]] = {}

    for item in items:
        ep_id = item["episode_id"]
        ep = item["episode"]
        rec = item["calibration"]
        raw_steps = list(ep.get("steps") or [])
        if len(raw_steps) > max_steps_per_episode:
            head_n = max_steps_per_episode // 2
            tail_n = max_steps_per_episode - head_n
            indexed_steps = [(i, raw_steps[i]) for i in range(head_n)] + [
                (i, raw_steps[i]) for i in range(len(raw_steps) - tail_n, len(raw_steps))
            ]
        else:
            indexed_steps = list(enumerate(raw_steps))

        step_lines = [format_step_line(idx, st) for idx, st in indexed_steps]
        step_lines_by_ep[ep_id] = step_lines

        header_lines = [
            f"=== EPISODE {ep_id} ===",
            (
                f"META version={rec['version']} family={rec['family']} agent={rec['agent']} "
                f"tier={rec['tier']} seed={rec['seed']} verdict={rec['verdict']} score={rec['score']:+.3f}"
            ),
            (
                f"CALIBRATION decision_step={rec['decision_step']} decision_day={rec['decision_day']} "
                f"accused={rec['accused']} P_accused={rec['p_accused']:.4f} "
                f"top_employee={rec['top_employee']} P_top={rec['p_top']:.4f} "
                f"suboptimal_target={rec['suboptimal_target']} V_true={rec['v_true']:.4f} "
                f"threshold={rec['threshold']:.4f} EV_accuse={rec['ev_accuse']:+.4f} EV_lost={rec['ev_lost']:.4f}"
            ),
        ]
        block = "\n".join(header_lines + step_lines)
        blocks[ep_id] = block

    corpus_text = "\n\n".join(blocks.values())
    return corpus_text, blocks, step_lines_by_ep


def verify_quote(episode_id: str, quote: str, blocks: dict[str, str]) -> dict[str, Any]:
    ep_key = str(episode_id or "").strip()
    raw_q = str(quote or "").strip()
    if ep_key not in blocks:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "unknown_episode_id",
        }
    if len(raw_q) < 12 or "\n" in raw_q or "\r" in raw_q:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "invalid_quote_length_or_newline",
        }
    if "[S" not in raw_q:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "missing_step_number_marker",
        }
    block = blocks[ep_key]
    if raw_q not in block:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "substring_not_in_episode_block",
        }
    matched_line = next((ln for ln in block.splitlines() if ln.startswith("[S") and raw_q in ln), None)
    if matched_line is None:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "not_in_numbered_step_line",
        }
    return {
        "episode_id": ep_key,
        "quote": raw_q,
        "verified": True,
        "matched_line": matched_line,
        "reason": "exact_verbatim_match",
    }


def verify_diagnosis_payload(
    payload: dict[str, Any],
    blocks: dict[str, str],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    clusters_raw = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
    ep_diag_raw = payload.get("episode_diagnoses") if isinstance(payload.get("episode_diagnoses"), list) else []

    by_id = {it["episode_id"]: it["calibration"] for it in items}
    verified_clusters: list[dict[str, Any]] = []
    cluster_total = 0
    cluster_ok = 0

    for c_idx, c in enumerate(clusters_raw):
        if not isinstance(c, dict):
            continue
        trig_id = sanitize_text(c.get("trigger_id", "horizon_deadline_panic"))
        title = sanitize_text(c.get("title", trig_id))
        ep_ids = [str(eid).strip() for eid in (c.get("episode_ids") or []) if str(eid).strip() in by_id]
        q_out: list[dict[str, Any]] = []
        for q_idx, q in enumerate(c.get("quotes") or []):
            if not isinstance(q, dict):
                continue
            chk = verify_quote(q.get("episode_id", ""), q.get("quote", ""), blocks)
            chk["source"] = f"cluster[{c_idx}].quotes[{q_idx}]"
            checks.append(chk)
            cluster_total += 1
            if chk["verified"]:
                cluster_ok += 1
            q_out.append(chk)
        ev_sum = round(sum(float(by_id[eid]["ev_lost"]) for eid in ep_ids), 6)
        verified_clusters.append(
            {
                "trigger_id": trig_id,
                "title": title,
                "episode_ids": ep_ids,
                "episode_count": len(ep_ids),
                "ev_lost_sum": ev_sum,
                "mechanism": sanitize_text(c.get("mechanism", "")),
                "mitigation": sanitize_text(c.get("mitigation", "")),
                "quotes": q_out,
            }
        )

    verified_ep_diags: list[dict[str, Any]] = []
    ep_total = 0
    ep_ok = 0
    seen_diag_ids: set[str] = set()

    for d_idx, d in enumerate(ep_diag_raw):
        if not isinstance(d, dict):
            continue
        eid = str(d.get("episode_id", "")).strip()
        seen_diag_ids.add(eid)
        tq = d.get("trigger_quote") if isinstance(d.get("trigger_quote"), dict) else {}
        tq_ep = str(tq.get("episode_id") or eid).strip()
        chk = verify_quote(tq_ep, tq.get("quote", ""), blocks)
        if tq_ep != eid:
            chk = {
                "episode_id": tq_ep,
                "quote": str(tq.get("quote") or "").strip(),
                "verified": False,
                "matched_line": None,
                "reason": "episode_id_mismatch_with_diagnosis",
            }
        chk["source"] = f"episode_diagnoses[{d_idx}].trigger_quote"
        checks.append(chk)
        ep_total += 1
        if chk["verified"]:
            ep_ok += 1
        rec = by_id.get(eid) or {}
        verified_ep_diags.append(
            {
                "episode_id": eid,
                "version": rec.get("version"),
                "agent": rec.get("agent"),
                "tier": rec.get("tier"),
                "seed": rec.get("seed"),
                "decision_day": rec.get("decision_day"),
                "decision_step": rec.get("decision_step"),
                "accused": rec.get("accused"),
                "top_employee": rec.get("top_employee"),
                "p_accused": rec.get("p_accused"),
                "p_top": rec.get("p_top"),
                "v_true": rec.get("v_true"),
                "threshold": rec.get("threshold"),
                "ev_accuse": rec.get("ev_accuse"),
                "ev_lost": rec.get("ev_lost"),
                "suboptimal_target": rec.get("suboptimal_target"),
                "verdict": rec.get("verdict"),
                "score": rec.get("score"),
                "primary_trigger": sanitize_text(d.get("primary_trigger", "")),
                "rationale": sanitize_text(d.get("rationale", "")),
                "trigger_quote": chk,
            }
        )

    missing_episodes = [it["episode_id"] for it in items if it["episode_id"] not in seen_diag_ids]
    total_quotes = cluster_total + ep_total
    verified_quotes = cluster_ok + ep_ok
    unverified_quotes = total_quotes - verified_quotes
    if not items and total_quotes == 0:
        pct = 100.0
    elif total_quotes == 0:
        pct = 0.0
    else:
        pct = round(100.0 * verified_quotes / total_quotes, 2)

    return {
        "executive_summary": sanitize_text(payload.get("executive_summary", "")),
        "clusters": verified_clusters,
        "episode_diagnoses": verified_ep_diags,
        "missing_episodes": missing_episodes,
        "quote_verification": {
            "total_quotes": total_quotes,
            "verified_quotes": verified_quotes,
            "unverified_quotes": unverified_quotes,
            "verified_quotes_pct": pct,
            "cluster_quotes_total": cluster_total,
            "cluster_quotes_verified": cluster_ok,
            "episode_quotes_total": ep_total,
            "episode_quotes_verified": ep_ok,
            "checks": checks,
        },
    }


def _heuristic_trigger_for_item(rec: dict[str, Any]) -> str:
    if rec.get("suboptimal_target"):
        return "framing_decoy_suboptimal_target"
    p_acc = float(rec.get("p_accused") or 0.0)
    if p_acc >= 0.48:
        return "value_bleed_threshold_blindness"
    if int(rec.get("decision_day") or 0) <= 10:
        return "early_snap_accusation"
    return "horizon_deadline_panic"


def build_stub_diagnosis_payload(
    items: list[dict[str, Any]],
    step_lines_by_ep: dict[str, list[str]],
) -> dict[str, Any]:
    if not items:
        return {
            "executive_summary": "No premature-commit episodes violated the Bayesian EV threshold 1 / (1 + V_true).",
            "clusters": [],
            "episode_diagnoses": [],
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    ep_diagnoses: list[dict[str, Any]] = []
    for it in items:
        eid = it["episode_id"]
        rec = it["calibration"]
        trig = _heuristic_trigger_for_item(rec)
        grouped.setdefault(trig, []).append(it)
        lines = step_lines_by_ep.get(eid) or []
        accuse_line = next((ln for ln in reversed(lines) if " accuse(" in ln), lines[-1])
        ep_diagnoses.append(
            {
                "episode_id": eid,
                "primary_trigger": trig,
                "rationale": (
                    f"Accused {rec['accused']} on day {rec['decision_day']} with P_accused={rec['p_accused']:.3f} "
                    f"below 1/(1+V_true)={rec['threshold']:.3f}, losing {rec['ev_lost']:.3f} expected score vs abstaining."
                ),
                "trigger_quote": {"episode_id": eid, "quote": accuse_line},
            }
        )

    titles = {
        "horizon_deadline_panic": "Final-Day Horizon Panic Accusation",
        "value_bleed_threshold_blindness": "Value-Bleed EV Threshold Blindness",
        "framing_decoy_suboptimal_target": "Framing Decoy and Non-Argmax Target Selection",
        "early_snap_accusation": "Early Low-Posterior Snap Accusation",
        "under_informative_canary_design": "Under-Informative Canary Splitting",
    }
    clusters: list[dict[str, Any]] = []
    for trig, members in grouped.items():
        quotes = []
        for m in members[:3]:
            meid = m["episode_id"]
            mlines = step_lines_by_ep[meid]
            qline = next((ln for ln in reversed(mlines) if " accuse(" in ln), mlines[-1])
            quotes.append({"episode_id": meid, "quote": qline})
        clusters.append(
            {
                "trigger_id": trig,
                "title": titles.get(trig, trig),
                "episode_ids": [m["episode_id"] for m in members],
                "mechanism": (
                    f"Observed across {len(members)} premature-commit episodes where P_accused remained "
                    "strictly below 1 / (1 + V_true) at accusation."
                ),
                "mitigation": "Gate accusation on exact Bayesian posterior P(e) >= 1 / (1 + V_est) and abstain otherwise.",
                "quotes": quotes,
            }
        )

    return {
        "executive_summary": (
            f"Diagnosed {len(items)} premature-commit episodes violating P_accused >= 1 / (1 + V_true) "
            f"across {len(clusters)} failure trigger clusters."
        ),
        "clusters": clusters,
        "episode_diagnoses": ep_diagnoses,
    }


def _extract_call_usage(resp: Any, elapsed_s: float) -> dict[str, Any]:
    u = resp.get("usage", {}) if isinstance(resp, dict) else getattr(resp, "usage", {}) or {}
    raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _um_int(attr: str) -> int:
        val = getattr(um, attr, 0) if um is not None else 0
        return val if isinstance(val, int) and val > 0 else 0

    tin = int(u.get("in", 0) or _um_int("prompt_token_count"))
    tout_combined = int(u.get("out", 0) or 0)
    thinking = _um_int("thoughts_token_count")
    candidates = _um_int("candidates_token_count")
    cached = _um_int("cached_content_token_count")
    out_tokens = candidates if candidates > 0 else max(0, tout_combined - thinking)
    if out_tokens == 0 and tout_combined > 0:
        out_tokens = tout_combined
    usd = float(u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0)
    return {
        "calls": 1,
        "in": tin,
        "out": out_tokens,
        "thinking": thinking,
        "cached": cached,
        "cost_usd": round(usd, 6),
        "latency_s": round(elapsed_s, 3),
    }


def _merge_usage(acc: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "calls": int(acc.get("calls", 0)) + int(delta.get("calls", 0)),
        "in": int(acc.get("in", 0)) + int(delta.get("in", 0)),
        "out": int(acc.get("out", 0)) + int(delta.get("out", 0)),
        "thinking": int(acc.get("thinking", 0)) + int(delta.get("thinking", 0)),
        "cached": int(acc.get("cached", 0)) + int(delta.get("cached", 0)),
        "cost_usd": round(float(acc.get("cost_usd", 0.0)) + float(delta.get("cost_usd", 0.0)), 6),
        "latency_s": round(float(acc.get("latency_s", 0.0)) + float(delta.get("latency_s", 0.0)), 3),
    }


def build_user_prompt(cal_report: dict[str, Any], items: list[dict[str, Any]], corpus_text: str) -> str:
    s = cal_report["summary"]
    ep_ids = [it["episode_id"] for it in items]
    lines = [
        "CORPUS CALIBRATION SUMMARY:",
        (
            f"total_frontier_episodes={s['n_episodes']} accused={s['n_accused']} abstained={s['n_abstained']} "
            f"premature_commits={s['premature_count']} total_ev_lost={s['ev_lost_total']:.4f} "
            f"mean_v_true={s['mean_v_true'] if s['mean_v_true'] is not None else 0.0:.4f} "
            f"mean_threshold={s['mean_threshold'] if s['mean_threshold'] is not None else 0.0:.4f} "
            f"ece={s['ece'] if s['ece'] is not None else 0.0:.4f} "
            f"brier={s['brier_score'] if s['brier_score'] is not None else 0.0:.4f}"
        ),
        f"REQUIRED_EPISODE_IDS ({len(ep_ids)}): " + ", ".join(ep_ids),
        "",
        "Analyze every premature-commit episode below. Copy numbered step quotes [S...] verbatim without changing a single character:",
        "",
        corpus_text,
    ]
    return "\n".join(lines)


def build_repair_prompt(verified: dict[str, Any], blocks: dict[str, str]) -> str:
    bad = [c for c in verified["quote_verification"]["checks"] if not c["verified"]]
    missing = verified["missing_episodes"]
    lines = [
        "Your previous JSON output had verification failures in Python exact-match checking.",
        "Fix ALL issues below and return the complete corrected JSON matching the schema:",
    ]
    if missing:
        lines.append("Missing episode_diagnoses for episode_ids: " + ", ".join(missing))
    for b in bad[:25]:
        eid = b["episode_id"]
        lines.append(
            f"- Failed at {b['source']}: episode_id={eid!r}, reason={b['reason']}, submitted_quote={b['quote']!r}"
        )
        if eid in blocks:
            sample_steps = [ln for ln in blocks[eid].splitlines() if ln.startswith("[S")][-4:]
            lines.append(f"  Valid verbatim lines from {eid}: " + " | ".join(sample_steps))
    lines.append(
        "Remember: every quote MUST be an exact character-for-character [S...] line from that exact episode_id block, with no em dashes."
    )
    return "\n".join(lines)


def render_summary_md(
    meta: dict[str, Any],
    cal_report: dict[str, Any],
    diagnosis: dict[str, Any],
) -> str:
    s = cal_report["summary"]
    qv = diagnosis["quote_verification"]
    u = meta["usage"]
    ece_s = f"{s['ece']:.4f}" if s.get("ece") is not None else "NA"
    brier_s = f"{s['brier_score']:.4f}" if s.get("brier_score") is not None else "NA"
    p_acc_s = f"{s['mean_p_accused']:.3f}" if s.get("mean_p_accused") is not None else "NA"
    acc_w_s = f"{s['accuracy_when_accused']:.3f}" if s.get("accuracy_when_accused") is not None else "NA"
    vt_s = f"{s['mean_v_true']:.3f}" if s.get("mean_v_true") is not None else "NA"
    thr_s = f"{s['mean_threshold']:.3f}" if s.get("mean_threshold") is not None else "NA"

    lines = [
        f"{MD_H1} Role 4 ({meta['role']}) - Bayesian Calibration & Premature-Commit EV Diagnosis ({meta['model_id']})",
        "",
        f"{MD_H2} Provenance & Verification",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}`",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Command:** `{meta['command']}`",
        f"- **Committed frontier episodes calibrated:** `{meta['n_calibrated_episodes']}` (`{s['n_accused']}` accusations, `{s['n_abstained']}` abstentions)",
        f"- **Premature-commit episodes diagnosed (`P_accuse < 1 / (1 + V_true)`):** `{meta['n_episodes']}`",
        f"- **Verbatim quote verification:** `{qv['verified_quotes']}/{qv['total_quotes']}` (`{meta['verified_quotes_pct']:.1f}%` exact substring + step-line match in Python)",
        f"- **Gemini usage:** `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd=${u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}s`",
        f"- **Artifacts:** `calibration_curve.png`, `calibration.json`, `calibration.md`, `diagnosis.json`, `meta.json`",
        "",
        f"{MD_H2} Exact Bayesian Calibration Headline (`data/runs/committed/`)",
        f"- **Mean posterior `P(accused == mole)` at accusation:** `{p_acc_s}` vs empirical accuracy `{acc_w_s}`",
        f"- **Reliability metrics:** Brier `{brier_s}`, 10-bin ECE `{ece_s}`",
        f"- **Mean `V_true` at decision:** `{vt_s}`; **mean rational break-even threshold `1 / (1 + V_true)`:** `{thr_s}`",
        f"- **Premature commits (`P(accused) < 1 / (1 + V_true)`):** `{s['premature_count']}/{s['n_episodes']}` episodes (`{s['premature_rate_accusations']:.1%}` of accusations), losing `{s['ev_lost_total']:.3f}` total EV vs abstaining (`{s['ev_lost_per_premature']:.3f}` EV lost per premature commit)",
        f"- **Counterfactual EV-gated score:** `{s['mean_gated_score']:.3f}` vs realized `{s['mean_score']:.3f}` (`{s['realized_abstain_gain']:+.3f}` per episode)",
        "",
        f"{MD_H2} Executive Diagnosis (`{meta['model_id']}`)",
        "",
        diagnosis["executive_summary"],
        "",
        f"{MD_H2} Premature-Commit Failure Trigger Taxonomy",
        "",
    ]

    for idx, cl in enumerate(diagnosis["clusters"], start=1):
        lines.extend(
            [
                f"{MD_H3} {idx}. {cl['title']} (`{cl['trigger_id']}`)",
                f"- **Episodes affected:** `{cl['episode_count']}` (`EV lost = {cl['ev_lost_sum']:.3f}`) - {', '.join(f'`{e}`' for e in cl['episode_ids'])}",
                f"- **Causal mechanism:** {cl['mechanism']}",
                f"- **Policy mitigation:** {cl['mitigation']}",
                "- **Verified verbatim quotes:**",
            ]
        )
        for q in cl["quotes"]:
            badge = "VERIFIED" if q["verified"] else "UNVERIFIED"
            lines.append(f"  - [{badge}] `{q['episode_id']}`: `{q['quote']}`")
        lines.append("")

    lines.extend(
        [
            f"{MD_H2} Per-Episode Premature-Commit EV Diagnosis",
            "",
            "| Episode ID | Day | Accused (P) | Top (P) | V_true | 1/(1+V) | EV Lost | Outcome | Trigger | Verbatim Trigger Quote |",
            "|---|---:|---|---|---:|---:|---:|---|---|---|",
        ]
    )
    for d in diagnosis["episode_diagnoses"]:
        p_acc = f"{d['p_accused']:.3f}" if d.get("p_accused") is not None else "NA"
        p_top = f"{d['p_top']:.3f}" if d.get("p_top") is not None else "NA"
        vt = f"{d['v_true']:.3f}" if d.get("v_true") is not None else "NA"
        thr = f"{d['threshold']:.3f}" if d.get("threshold") is not None else "NA"
        evl = f"{d['ev_lost']:.3f}" if d.get("ev_lost") is not None else "NA"
        tq = d["trigger_quote"]["quote"]
        lines.append(
            f"| `{d['episode_id']}` | {d.get('decision_day')} | `{d.get('accused')}` ({p_acc}) | "
            f"`{d.get('top_employee')}` ({p_top}) | {vt} | {thr} | {evl} | `{d.get('verdict')}` | "
            f"`{d['primary_trigger']}` | `{tq}` |"
        )

    lines.append("")
    return sanitize_text("\n".join(lines))


def run_calibration_analyst(
    *,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    model_id: str = DEFAULT_MODEL,
    stub: bool = False,
    n_bins: int = 10,
    include_reference: bool = False,
    tier: str | None = None,
    agent_prefix: str = "",
    thinking_level: str | None = None,
    max_repair_retries: int = 2,
    client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cal_report = calibration.run_calibration(
        runs_dir=runs_dir,
        out_dir=out_path,
        n_bins=n_bins,
        include_reference=include_reference,
        tier=tier,
        agent_prefix=agent_prefix,
    )
    (out_path / "calibration.json").write_text(
        sanitize_text((out_path / "calibration.json").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    (out_path / "calibration.md").write_text(
        sanitize_text((out_path / "calibration.md").read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    items = collect_premature_episodes(
        runs_dir=runs_dir,
        include_reference=include_reference,
        tier=tier,
        agent_prefix=agent_prefix,
    )
    corpus_text, blocks, step_lines_by_ep = pack_premature_episodes(items)

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    commit = current_git_commit()
    effective_model = "stub" if stub else model_id
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or (
        f"{FEATURE}:{effective_model}:{ts.strftime('%Y%m%dT%H%M%SZ')}"
    )

    if client is None:
        if stub:
            script_name = f"calibration_analyst_stub_{int(time.time() * 1000)}_{os.getpid()}"
            stub_payload = build_stub_diagnosis_payload(items, step_lines_by_ep)
            register_script(script_name, [{"json": stub_payload}])
            client = lab_client(f"stub:{script_name}", feature=FEATURE, run_id=run_id)
        else:
            spec = model_id if ":" in model_id else f"gemini:{model_id}"
            kw: dict[str, Any] = {}
            if thinking_level:
                kw["thinking_level"] = thinking_level
            if spec == "gemini:gemini-4-carbon" and not kw:
                client = lab_client("gemini:gemini-4-carbon", feature="calibration_analyst")
            else:
                client = lab_client(spec, feature=FEATURE, run_id=run_id, **kw)

    usage_totals = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}

    if not items and stub and client is None:
        verified = verify_diagnosis_payload(
            build_stub_diagnosis_payload([], {}),
            blocks={},
            items=[],
        )
    else:
        user_prompt = build_user_prompt(cal_report, items, corpus_text)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        t0 = time.time()
        resp = client.chat(messages, temperature=0.0, response_schema=CALIBRATION_DIAGNOSIS_SCHEMA)
        usage_totals = _merge_usage(usage_totals, _extract_call_usage(resp, time.time() - t0))
        raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
        parsed = json.loads(raw_text or "{}")
        verified = verify_diagnosis_payload(parsed, blocks=blocks, items=items)

        attempt = 0
        while attempt < max_repair_retries and (
            verified["quote_verification"]["unverified_quotes"] > 0
            or len(verified["missing_episodes"]) > 0
            or (len(items) > 0 and verified["quote_verification"]["total_quotes"] == 0)
        ):
            attempt += 1
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": build_repair_prompt(verified, blocks)})
            t1 = time.time()
            resp = client.chat(messages, temperature=0.0, response_schema=CALIBRATION_DIAGNOSIS_SCHEMA)
            usage_totals = _merge_usage(usage_totals, _extract_call_usage(resp, time.time() - t1))
            raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
            parsed = json.loads(raw_text or "{}")
            verified = verify_diagnosis_payload(parsed, blocks=blocks, items=items)

    qv = verified["quote_verification"]
    cal_summary = cal_report["summary"]
    default_cmd = "PYTHONPATH=. " + " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    cmd_clean = sanitize_text(command_str or default_cmd)

    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "commit": commit,
        "git_sha": commit,
        "timestamp": ts_iso,
        "command": cmd_clean,
        "ledger_run_id": run_id,
        "runs_dir": str(runs_dir),
        "n_episodes": len(items),
        "n_calibrated_episodes": int(cal_summary["n_episodes"]),
        "n_premature_episodes": len(items),
        "ev_lost_total": round(float(cal_summary["ev_lost_total"]), 6),
        "ece": round(float(cal_summary["ece"]), 6) if cal_summary.get("ece") is not None else None,
        "brier_score": round(float(cal_summary["brier_score"]), 6) if cal_summary.get("brier_score") is not None else None,
        "total_quotes": qv["total_quotes"],
        "verified_quotes": qv["verified_quotes"],
        "verified_quotes_pct": qv["verified_quotes_pct"],
        "fake_env": False,
        "smoke": False,
        "usage": usage_totals,
    }
    if stub:
        meta["stub"] = True
        meta["provider"] = "stub"

    diagnosis_doc: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "commit": commit,
        "timestamp": ts_iso,
        "runs_dir": str(runs_dir),
        "n_calibrated_episodes": int(cal_summary["n_episodes"]),
        "n_premature_episodes": len(items),
        "calibration_summary": cal_summary,
        "quote_verification": qv,
        "executive_summary": verified["executive_summary"],
        "clusters": verified["clusters"],
        "episode_diagnoses": verified["episode_diagnoses"],
        "usage": usage_totals,
    }

    (out_path / "meta.json").write_text(sanitize_text(json.dumps(meta, indent=2) + "\n"), encoding="utf-8")
    (out_path / "diagnosis.json").write_text(
        sanitize_text(json.dumps(diagnosis_doc, indent=2) + "\n"),
        encoding="utf-8",
    )
    (out_path / "summary.md").write_text(
        render_summary_md(meta, cal_report, diagnosis_doc),
        encoding="utf-8",
    )
    return {"meta": meta, "calibration": cal_report, "diagnosis": diagnosis_doc, "blocks": blocks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run Bayesian accusation calibration and premature-commit EV failure diagnosis."
    )
    ap.add_argument("--runs-dir", "--runs", dest="runs_dir", type=Path, default=DEFAULT_RUNS_DIR)
    ap.add_argument("--out", "--out-dir", dest="out_dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--tier", default=None)
    ap.add_argument("--agent-prefix", default="")
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--max-repair-retries", type=int, default=2)
    ap.add_argument("--include-reference", action="store_true")
    args = ap.parse_args(argv)

    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd_parts = ["PYTHONPATH=.", shlex.quote(sys.executable), "scripts/run_calibration_analyst.py"] + [
        shlex.quote(x) for x in raw_argv
    ]
    cmd_str = " ".join(cmd_parts)

    res = run_calibration_analyst(
        runs_dir=args.runs_dir,
        out_dir=args.out_dir,
        model_id=args.model,
        stub=args.stub,
        n_bins=args.bins,
        include_reference=args.include_reference,
        tier=args.tier,
        agent_prefix=args.agent_prefix,
        thinking_level=args.thinking_level,
        max_repair_retries=args.max_repair_retries,
        command_str=cmd_str,
    )
    m = res["meta"]
    u = m["usage"]
    print(
        f"calibration_analyst: calibrated={m['n_calibrated_episodes']} "
        f"premature={m['n_premature_episodes']} quotes_verified={m['verified_quotes']}/{m['total_quotes']} "
        f"({m['verified_quotes_pct']:.1f}%) in={u['in']} out={u['out']} cost=${u['cost_usd']:.6f}"
    )
    if not args.stub and m["verified_quotes_pct"] < 100.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
