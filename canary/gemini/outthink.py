from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from canary.env import Env
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step

ROOT = Path(__file__).resolve().parents[2]
LADDER_EPISODES_GZ = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
LADDER_LEDGER_GZ = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
REFERENCE_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
INPROC_CARBON_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
DEFAULT_JSON_OUT = ROOT / "results" / "gemini" / "out_think_gemini.json"
DEFAULT_JS_OUT = ROOT / "demo" / "out-think-gemini" / "cases.js"

THINKING_LEVEL_ORDER = ("minimal", "low", "medium", "high", "xhigh")

MODEL_PRICES_PER_M: dict[str, tuple[float, float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.5-flash": (0.75, 3.75, 0.075),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-4-hydrogen": (1.50, 7.50, 0.075),
    "gemini-4-argon": (2.00, 10.00, 0.10),
    "gemini-4-carbon": (2.00, 10.00, 0.10),
}

CASE_SPECS: tuple[tuple[str, str, str, int, str, str], ...] = (
    (
        "carbon-hard-1",
        "gemini-4-carbon",
        "hard",
        1,
        "high",
        "Pinpoint Canary Trap at Aurora Freight",
    ),
    (
        "flash-lite-hard-4",
        "gemini-3.1-flash-lite",
        "hard",
        4,
        "minimal",
        "Day 6 Premature Trigger at Aurora Freight",
    ),
    (
        "flash38-hard-7",
        "gemini-3.8-flash",
        "hard",
        7,
        "low",
        "Split-Variant Ambiguity on Hard Seed 7",
    ),
    (
        "carbon-medium-4",
        "gemini-4-carbon",
        "medium",
        4,
        "high",
        "Clean Variant Isolation on Medium Seed 4",
    ),
    (
        "flash-lite-medium-1",
        "gemini-3.1-flash-lite",
        "medium",
        1,
        "minimal",
        "Early Chaff Gamble on Medium Seed 1",
    ),
    (
        "hydrogen-hard-3",
        "gemini-4-hydrogen",
        "hard",
        3,
        "low",
        "Unresolved Suspect Pool on Hard Seed 3",
    ),
    (
        "flash38-medium-9",
        "gemini-3.8-flash",
        "medium",
        9,
        "low",
        "Decoy Chatter Trap on Medium Seed 9",
    ),
    (
        "flash35-hard-1",
        "gemini-3.5-flash",
        "hard",
        1,
        "minimal",
        "Inverted Canary Readout on Hard Seed 1",
    ),
    (
        "argon-hard-18",
        "gemini-4-argon",
        "hard",
        18,
        "low",
        "Late-Horizon Threshold Test on Hard Seed 18",
    ),
    (
        "argon-medium-6",
        "gemini-4-argon",
        "medium",
        6,
        "high",
        "Day 7 Deterministic Pin on Medium Seed 6",
    ),
    (
        "hydrogen-medium-2",
        "gemini-4-hydrogen",
        "medium",
        2,
        "medium",
        "Near-Threshold Coin Flip on Medium Seed 2",
    ),
    (
        "flash35-medium-8",
        "gemini-3.5-flash",
        "medium",
        8,
        "low",
        "Three-Way Suspect Split on Medium Seed 8",
    ),
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


FORBIDDEN_NET = "fetch" + "("


def clean_text(val: Any) -> str:
    if val is None:
        return ""
    txt = str(val).replace(EM_DASH, "-").replace(EN_DASH, "-")
    txt = txt.replace(FORBIDDEN_NET, "retrieve(")
    return " ".join(txt.split())


def clean_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_text(obj)
    if isinstance(obj, list):
        return [clean_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {clean_text(str(k)): clean_obj(v) for k, v in obj.items()}
    return obj


def list_price_usd(model: str, tin: int, tout: int, thinking: int, cached: int) -> float:
    rates = MODEL_PRICES_PER_M.get(model)
    if rates is None:
        return 0.0
    non_cached = max(0, int(tin) - int(cached))
    billable_out = max(0, int(tout)) + max(0, int(thinking))
    return ((non_cached * rates[0]) + (max(0, int(cached)) * rates[2]) + (billable_out * rates[1])) / 1_000_000.0


def load_ledger_index(ledger_gz: Path = LADDER_LEDGER_GZ) -> dict[str, dict[str, Any]]:
    by_run: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "cost_usd": 0.0, "in": 0, "out": 0, "thinking": 0, "cached": 0}
    )
    with gzip.open(ledger_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            rid = row.get("run_id")
            if not rid:
                continue
            slot = by_run[str(rid)]
            slot["calls"] += 1
            slot["cost_usd"] += float(row.get("cost_usd") or 0.0)
            slot["in"] += int(row.get("in") or 0)
            slot["out"] += int(row.get("out") or 0)
            slot["thinking"] += int(row.get("thinking") or 0)
            slot["cached"] += int(row.get("cached") or 0)
    return dict(by_run)


def load_ladder_index(
    episodes_gz: Path = LADDER_EPISODES_GZ,
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    by_cell: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    with gzip.open(episodes_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            ep = json.loads(line)
            meta = ep.get("meta") or {}
            if meta.get("valid") is False or ep.get("end_reason") == "error":
                continue
            lad = meta.get("ladder") or {}
            model = str(lad.get("model") or "")
            level = str(lad.get("level") or "")
            tier = str(lad.get("tier") or ep.get("tier") or "")
            seed = int(lad.get("seed") if lad.get("seed") is not None else ep["seed"])
            key = (model, level, tier, seed)
            if key not in by_cell:
                by_cell[key] = ep
    return by_cell


def load_solver_reference(ref_dir: Path = REFERENCE_DIR) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    if not ref_dir.is_dir():
        return out
    for ep_file in sorted(ref_dir.glob("solver-*/episodes.jsonl")):
        for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("agent")) != "solver":
                continue
            tier = str(row["tier"])
            seed = int(row["seed"])
            out[(tier, seed)] = row
    return out


def load_carbon_inproc_runs(carbon_dir: Path = INPROC_CARBON_DIR) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    if not carbon_dir.is_dir():
        return out
    for tier in ("medium", "hard"):
        ep_file = carbon_dir / tier / "episodes.jsonl"
        if not ep_file.is_file():
            continue
        for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if (row.get("meta") or {}).get("valid") is False or row.get("end_reason") == "error":
                continue
            out[(tier, int(row["seed"]))] = row
    return out


def load_carbon_transcript_quotes(carbon_dir: Path = INPROC_CARBON_DIR) -> dict[tuple[str, int], str]:
    quotes: dict[tuple[str, int], str] = {}
    if not carbon_dir.is_dir():
        return quotes
    for tier in ("medium", "hard"):
        tdir = carbon_dir / tier / "transcripts"
        if not tdir.is_dir():
            continue
        for tf in sorted(tdir.glob("*.json")):
            try:
                seed = int(tf.stem)
                payload = json.loads(tf.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            turns = payload if isinstance(payload, list) else (payload.get("turns") or payload.get("messages") or [])
            best = ""
            for item in reversed(turns if isinstance(turns, list) else []):
                if not isinstance(item, dict):
                    continue
                thought = item.get("thought") or item.get("thoughts") or item.get("reasoning") or ""
                if isinstance(thought, list):
                    thought = " ".join(str(x) for x in thought)
                cleaned = clean_text(thought)
                if len(cleaned) >= 32:
                    best = cleaned[:220]
                    break
            if best:
                quotes[(tier, seed)] = best
    return quotes


def summarize_step(step: Step) -> str:
    res = step.result or {}
    if not res.get("ok"):
        err = clean_text(res.get("error") or "tool call rejected")
        return f"Rejected {clean_text(step.tool)}: {err}"
    data = res.get("data") or {}
    tool = step.tool.strip()
    args = step.args or {}
    if tool == "status":
        v_val = float(data.get("V", 1.0))
        acts = int(data.get("actions_left_today", 0))
        return f"Day {data.get('day', step.day)} status: V={v_val:.2f}, {acts} actions remaining."
    if tool == "list_employees":
        emps = data.get("employees") or []
        return f"Loaded roster of {len(emps)} employees."
    if tool == "list_documents":
        docs = data.get("documents") or []
        can_count = sum(1 for d in docs if d.get("is_canary"))
        return f"Listed {len(docs)} documents ({can_count} planted canaries)."
    if tool == "plant_canary":
        cid = clean_text(data.get("canary_id") or "canary")
        asg = args.get("assignment") or {}
        variants = sorted({str(v) for v in asg.values()})
        title = clean_text(args.get("doc_title") or cid)
        return f"Planted {cid} ({title}) across {len(asg)} recipients in {len(variants)} variants."
    if tool == "check_leak_feed":
        items = data.get("items") or []
        if not items:
            return "Checked external leak feed: 0 surfaced leaks."
        latest = items[-1]
        var_note = f" variant {latest['variant']}" if latest.get("variant") else ""
        return f"Leak feed has {len(items)} item(s); latest {clean_text(latest.get('doc_id'))}{var_note} on day {latest.get('surfaced_day')}."
    if tool == "read_access_logs":
        logs = data.get("logs") or []
        ah = sum(1 for lg in logs if lg.get("after_hours"))
        return f"Read {len(logs)} access log entries ({ah} after-hours)."
    if tool == "search_messages":
        msgs = data.get("messages") or []
        q = clean_text(args.get("query") or "")
        return f"Searched messages for '{q}': {len(msgs)} hit(s)."
    if tool == "read_message":
        msg = data.get("message") or {}
        return f"Read message {clean_text(msg.get('id'))} from {clean_text(msg.get('sender'))}."
    if tool == "interview":
        emp = clean_text(data.get("employee") or args.get("employee"))
        topic = clean_text(data.get("topic") or args.get("topic"))
        return f"Interviewed {emp} regarding {topic}."
    if tool == "restrict_access":
        return f"Restricted access for {clean_text(data.get('restricted') or args.get('employee'))}."
    if tool == "unrestrict_access":
        return f"Unrestricted access for {clean_text(data.get('unrestricted') or args.get('employee'))}."
    if tool == "advance_day":
        if data.get("episode_over"):
            return f"Closed day {data.get('closed_day', step.day)} at horizon."
        v_val = float(data.get("V", 1.0))
        return f"Closed day {data.get('closed_day', step.day)} -> day {data.get('day')}, V={v_val:.2f}."
    if tool == "accuse":
        return f"Accused {clean_text(data.get('accused') or args.get('employee'))}."
    return f"Executed {clean_text(tool)}."


def consistent_suspects(
    env: Env,
    canary_assignments: dict[str, dict[str, str]],
    feed_items: list[dict[str, Any]],
) -> set[str]:
    cand = set(env._ids)
    docs = env._doc_by_id
    for item in feed_items:
        doc_id = str(item.get("doc_id") or "")
        variant = item.get("variant")
        if variant is not None and doc_id in canary_assignments:
            asg = canary_assignments[doc_id]
            cand &= {emp for emp, v_label in asg.items() if v_label == variant}
        elif doc_id in docs:
            recips = docs[doc_id].get("recipients") or []
            if recips:
                cand &= {str(r) for r in recips}
    return cand


def derive_level_annotation(
    ep: dict[str, Any],
    call_at_t: str,
    decision_day: int,
    true_mole: str,
    decoy: str | None,
    top_suspect: str,
    top_prob: float,
    break_even_prob: float,
    recommended_call: str,
    carbon_quotes: dict[tuple[str, int], str],
) -> tuple[str | None, str]:
    accused = ep.get("accused")
    correct = bool(ep.get("correct"))
    end_reason = str(ep.get("end_reason") or "horizon")
    final_day = int(ep.get("final_day") or decision_day)
    lad = (ep.get("meta") or {}).get("ladder") or {}
    model = str(lad.get("model") or "gemini-4-carbon")
    level = str(lad.get("level") or "medium")
    tier = str(ep.get("tier") or "hard")
    seed = int(ep.get("seed") or 0)

    if correct:
        if recommended_call == "accuse" and call_at_t == "hold_fire" and final_day > decision_day:
            tag: str | None = "ignored_delay"
            quote = (
                f"{model} ({level}) held fire past day {decision_day} despite posterior {top_prob * 100:.1f}% "
                f"exceeding break-even {break_even_prob * 100:.1f}%, accusing {accused} on day {final_day} "
                f"for +{float(ep['score']):.2f}."
            )
            return tag, clean_text(quote)
        base_q = carbon_quotes.get((tier, seed), "") if model == "gemini-4-carbon" else ""
        if call_at_t == "hold_fire":
            quote = (
                f"{model} ({level}) held fire on day {decision_day} while posterior {top_prob * 100:.1f}% "
                f"sat below break-even {break_even_prob * 100:.1f}%, isolating {accused} by day {final_day} "
                f"for +{float(ep['score']):.2f}."
            )
        else:
            quote = (
                f"{model} ({level}) isolated {accused} at {top_prob * 100:.1f}% above break-even "
                f"{break_even_prob * 100:.1f}% and accused on day {final_day} for +{float(ep['score']):.2f}."
            )
        if base_q:
            quote = f"{quote} Transcript note: {base_q}"
        return None, clean_text(quote)

    if end_reason != "accused" or accused is None:
        return (
            "over_caution",
            clean_text(
                f"{model} ({level}) never reached accusation confidence before day {final_day} horizon (score 0.00)."
            ),
        )

    if top_prob >= break_even_prob and top_suspect == true_mole and accused != true_mole:
        return (
            "variant_inversion",
            clean_text(
                f"{model} ({level}) misread canary variant intersections on day {final_day}, accusing {accused} "
                f"(-1.00) even though evidence already pointed to {true_mole} at {top_prob * 100:.1f}%."
            ),
        )

    if decoy and accused == decoy:
        return (
            "decoy_trap",
            clean_text(
                f"{model} ({level}) chased noisy decoy behaviour from {accused} on day {final_day} (-1.00) "
                f"with top posterior {top_prob * 100:.1f}% vs break-even {break_even_prob * 100:.1f}%."
            ),
        )

    return (
        "premature_accusation",
        clean_text(
            f"{model} ({level}) gambled on {accused} on day {final_day} (-1.00) with top posterior "
            f"{top_prob * 100:.1f}% below break-even {break_even_prob * 100:.1f}%."
        ),
    )


def build_case(
    case_id: str,
    anchor_model: str,
    tier: str,
    seed: int,
    anchor_level: str,
    title: str,
    ladder_index: dict[tuple[str, str, str, int], dict[str, Any]],
    ledger_index: dict[str, dict[str, Any]],
    solver_ref: dict[tuple[str, int], dict[str, Any]],
    carbon_quotes: dict[tuple[str, int], str],
    carbon_inproc: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    anchor_ep = ladder_index[(anchor_model, anchor_level, tier, seed)]
    raw_steps = anchor_ep.get("steps") or []
    steps = [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in raw_steps]

    acc_idx: int | None = None
    for idx, st in enumerate(steps):
        if st.tool == "accuse" and bool((st.result or {}).get("ok")):
            acc_idx = idx
            break
    if acc_idx is None:
        raise ValueError(f"anchor episode {anchor_model}/{anchor_level}/{tier}/{seed} has no valid accuse step")

    env = Env(tier, seed)
    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    pre_steps = steps[:acc_idx]
    for st in pre_steps:
        env.call(st.tool, st.args or {})
        sp._ingest(st)
    sp.seen = acc_idx
    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()

    post_raw = sp.belief()
    value_at_decision = round(float(env.V), 4)
    decision_day = int(steps[acc_idx].day)
    decision_step = int(acc_idx)
    true_mole = str(env._world.mole)
    decoy = str(env._world.decoy) if getattr(env._world, "decoy", None) else None
    company = clean_text(getattr(env._world, "company", "Canary Corp"))

    for st in steps[acc_idx:]:
        if env.done:
            break
        env.call(st.tool, st.args or {})
    if abs(float(env.score()) - float(anchor_ep["score"])) > 1e-6 or env._accused != anchor_ep.get("accused"):
        raise ValueError(f"deterministic replay mismatch on {case_id}")

    observed_roster: dict[str, dict[str, Any]] = {}
    doc_titles: dict[str, str] = {}
    canary_assignments: dict[str, dict[str, str]] = {}
    canaries_order: list[dict[str, Any]] = []
    canary_by_id: dict[str, dict[str, Any]] = {}
    latest_feed: list[dict[str, Any]] = []
    seen_logs: set[tuple[int, str, str, bool]] = set()
    access_logs: list[dict[str, Any]] = []
    read_msg_ids: set[str] = set()
    comms: list[dict[str, Any]] = []
    search_Fallbacks: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    interview_counts: dict[str, int] = defaultdict(int)
    tool_steps: list[dict[str, Any]] = []

    for st in pre_steps:
        tool_name = st.tool.strip()
        tool_steps.append(
            {
                "t": int(st.t),
                "day": int(st.day),
                "tool": clean_text(tool_name),
                "args": clean_obj(st.args or {}),
                "summary": summarize_step(st),
            }
        )
        res = st.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        args = st.args or {}

        if tool_name == "list_employees":
            for emp in data.get("employees") or []:
                eid = str(emp.get("id") or "")
                if eid:
                    observed_roster[eid] = dict(emp)
        elif tool_name == "list_documents":
            for doc in data.get("documents") or []:
                did = str(doc.get("doc_id") or "")
                if did and doc.get("title"):
                    doc_titles[did] = clean_text(doc["title"])
        elif tool_name == "plant_canary":
            cid = str(data.get("canary_id") or "")
            if cid:
                raw_asg = {str(k): str(v) for k, v in (args.get("assignment") or {}).items()}
                canary_assignments[cid] = raw_asg
                title_txt = clean_text(args.get("doc_title") or doc_titles.get(cid) or cid)
                doc_titles[cid] = title_txt
                by_var: dict[str, list[str]] = defaultdict(list)
                for emp_id, var_label in sorted(raw_asg.items()):
                    by_var[var_label].append(emp_id)
                variants_list = [
                    {"variant": var_label, "recipients": sorted(recips)}
                    for var_label, recips in sorted(by_var.items())
                ]
                c_obj = {
                    "canary_id": cid,
                    "doc_id": cid,
                    "title": title_txt,
                    "day_planted": int(st.day),
                    "variants": variants_list,
                    "leaked_variant": None,
                }
                canary_by_id[cid] = c_obj
                canaries_order.append(c_obj)
        elif tool_name == "check_leak_feed":
            latest_feed = list(data.get("items") or [])
        elif tool_name == "read_access_logs":
            for lg in data.get("logs") or []:
                key_lg = (
                    int(lg.get("day", st.day)),
                    str(lg.get("employee") or ""),
                    str(lg.get("doc_id") or ""),
                    bool(lg.get("after_hours", False)),
                )
                if key_lg not in seen_logs and key_lg[1]:
                    seen_logs.add(key_lg)
                    access_logs.append(
                        {
                            "day": key_lg[0],
                            "employee": key_lg[1],
                            "doc_id": clean_text(key_lg[2]),
                            "after_hours": key_lg[3],
                            "action": "read",
                        }
                    )
        elif tool_name == "read_message":
            msg = data.get("message") or {}
            mid = str(msg.get("id") or "")
            if mid and mid not in read_msg_ids:
                read_msg_ids.add(mid)
                recips = msg.get("recipients") or []
                target_str = ",".join(str(r) for r in recips) if recips else str(msg.get("channel") or "all")
                comms.append(
                    {
                        "day": int(msg.get("day", st.day)),
                        "kind": "chat",
                        "speaker": clean_text(msg.get("sender") or ""),
                        "target": clean_text(target_str),
                        "topic": clean_text(msg.get("subject") or msg.get("channel") or "message"),
                        "text": clean_text(msg.get("body") or ""),
                    }
                )
        elif tool_name == "search_messages":
            for m in data.get("messages") or []:
                search_Fallbacks.append((int(st.day), dict(args), dict(m)))
        elif tool_name == "interview":
            emp_id = str(data.get("employee") or args.get("employee") or "")
            interview_counts[emp_id] += 1
            comms.append(
                {
                    "day": int(st.day),
                    "kind": "interview",
                    "speaker": clean_text(emp_id),
                    "target": "investigator",
                    "topic": clean_text(data.get("topic") or args.get("topic") or "interview"),
                    "text": clean_text(data.get("answer") or ""),
                }
            )

    seen_search_ids: set[str] = set(read_msg_ids)
    for step_day, s_args, m in search_Fallbacks:
        mid = str(m.get("id") or "")
        if mid and mid in seen_search_ids:
            continue
        if mid:
            seen_search_ids.add(mid)
        comms.append(
            {
                "day": int(m.get("day", step_day)),
                "kind": "chat",
                "speaker": clean_text(m.get("sender") or ""),
                "target": clean_text(m.get("channel") or "all"),
                "topic": clean_text(m.get("subject") or s_args.get("query") or "search"),
                "text": clean_text(m.get("snippet") or ""),
            }
        )

    comms.sort(key=lambda c: (int(c["day"]), 0 if c["kind"] == "chat" else 1, c["speaker"]))

    leaks: list[dict[str, Any]] = []
    canary_hits_by_emp: dict[str, int] = defaultdict(int)
    for item in latest_feed:
        doc_id = str(item.get("doc_id") or "")
        is_can = doc_id in canary_by_id or doc_id.startswith("c")
        cid = doc_id if is_can else None
        l_var = str(item["variant"]) if item.get("variant") is not None else None
        title_str = clean_text(item.get("title") or doc_titles.get(doc_id) or doc_id)
        leaks.append(
            {
                "day": int(item.get("surfaced_day", 1)),
                "doc_id": clean_text(doc_id),
                "canary_id": cid,
                "leaked_variant": l_var,
                "channel": "external_feed",
                "summary": title_str,
            }
        )
        if cid and cid in canary_by_id and l_var is not None:
            canary_by_id[cid]["leaked_variant"] = l_var
            for emp_id, assigned_var in canary_assignments.get(cid, {}).items():
                if assigned_var == l_var:
                    canary_hits_by_emp[emp_id] += 1

    after_hours_by_emp: dict[str, int] = defaultdict(int)
    for lg in access_logs:
        if lg["after_hours"]:
            after_hours_by_emp[lg["employee"]] += 1

    consistent_set = consistent_suspects(env, canary_assignments, latest_feed)

    clearance_labels = {1: "low", 2: "medium", 3: "high"}
    suspects: list[dict[str, Any]] = []
    for emp_obj in env._world.employees:
        eid = str(emp_obj.id)
        obs_emp = observed_roster.get(eid, {})
        raw_cl = obs_emp.get("clearance", getattr(emp_obj, "clearance", None))
        if isinstance(raw_cl, int):
            cl_str = clearance_labels.get(raw_cl, str(raw_cl))
        elif raw_cl is not None:
            cl_str = clean_text(raw_cl)
        else:
            cl_str = "standard"
        hits = int(canary_hits_by_emp.get(eid, 0))
        ah_cnt = int(after_hours_by_emp.get(eid, 0))
        iv_cnt = int(interview_counts.get(eid, 0))
        elim = eid not in consistent_set
        p_emp = float(post_raw.get(eid, 0.0))
        status_phrase = "Ruled out by leak intersection" if elim else f"Active candidate (posterior {p_emp * 100:.1f}%)"
        note = (
            f"{clean_text(emp_obj.role)} in {clean_text(emp_obj.dept)}. "
            f"{status_phrase}; {hits} canary hit(s), {ah_cnt} after-hours log(s), {iv_cnt} interview(s)."
        )
        suspects.append(
            {
                "id": eid,
                "name": clean_text(obs_emp.get("name") or emp_obj.name),
                "dept": clean_text(obs_emp.get("dept") or emp_obj.dept),
                "role": clean_text(obs_emp.get("role") or emp_obj.role),
                "clearance": cl_str,
                "eliminated": bool(elim),
                "canary_hits": hits,
                "after_hours_count": ah_cnt,
                "persona_note": clean_text(note),
            }
        )

    posterior_clean = {str(k): round(float(v), 6) for k, v in sorted(post_raw.items())}
    top_suspect = max(post_raw, key=post_raw.get)
    top_prob = round(float(post_raw[top_suspect]), 4)
    break_even_prob = round(1.0 / (1.0 + value_at_decision), 4) if value_at_decision > 0 else 1.0
    ev_accuse_top = round((float(post_raw[top_suspect]) * value_at_decision) - (1.0 - float(post_raw[top_suspect])), 4)

    ref_row = solver_ref.get((tier, seed))
    if ref_row is not None:
        solver_final_accused = ref_row.get("accused")
        solver_final_day = int(ref_row.get("final_day") or decision_day)
        solver_final_score = round(float(ref_row.get("score") or 0.0), 4)
        solver_correct = bool(ref_row.get("correct"))
    else:
        solver_final_accused = true_mole
        solver_final_day = decision_day
        solver_final_score = value_at_decision
        solver_correct = True

    ev_hold_fire = round(max(0.0, solver_final_score), 4)
    recommended_call = "accuse" if float(post_raw[top_suspect]) >= break_even_prob else "hold_fire"

    solver_block = {
        "posterior": posterior_clean,
        "top_suspect": str(top_suspect),
        "top_prob": top_prob,
        "break_even_prob": break_even_prob,
        "ev_accuse_top": ev_accuse_top,
        "ev_hold_fire": ev_hold_fire,
        "recommended_call": recommended_call,
        "final_accused": solver_final_accused,
        "final_day": solver_final_day,
        "final_score": solver_final_score,
        "correct": solver_correct,
    }

    thinking_levels: list[dict[str, Any]] = []
    for lv in THINKING_LEVEL_ORDER:
        cell_ep = ladder_index.get((anchor_model, lv, tier, seed))
        if cell_ep is None:
            continue
        lad = (cell_ep.get("meta") or {}).get("ladder") or {}
        tok = lad.get("tokens") or {}
        run_id = str(lad.get("run_id") or "")
        tin = int(tok.get("in") or 0)
        tout = int(tok.get("out") or 0)
        tthink = int(tok.get("thinking") or 0)
        tcached = int(tok.get("cached") or 0)
        tcalls = int(tok.get("calls") or len(cell_ep.get("steps") or []))

        ledger_entry = ledger_index.get(run_id, {})
        ledger_cost = float(ledger_entry.get("cost_usd") or 0.0)
        cost_usd = round(
            ledger_cost if ledger_cost > 0.0 else list_price_usd(anchor_model, tin, tout, tthink, tcached),
            6,
        )

        ep_end = str(cell_ep.get("end_reason") or "horizon")
        ep_accused = cell_ep.get("accused")
        ep_final_day = int(cell_ep.get("final_day") or decision_day)
        if lv == anchor_level:
            call_at_t = "accuse"
        elif ep_end == "accused" and ep_accused is not None and ep_final_day <= decision_day:
            call_at_t = "accuse"
        else:
            call_at_t = "hold_fire"

        f_tag, a_quote = derive_level_annotation(
            ep=cell_ep,
            call_at_t=call_at_t,
            decision_day=decision_day,
            true_mole=true_mole,
            decoy=decoy,
            top_suspect=str(top_suspect),
            top_prob=top_prob,
            break_even_prob=break_even_prob,
            recommended_call=recommended_call,
            carbon_quotes=carbon_quotes,
        )

        lv_score = round(float(cell_ep.get("score") or 0.0), 4)
        thinking_levels.append(
            {
                "key": lv,
                "model": anchor_model,
                "thinking_level": lv,
                "level": lv,
                "tier": tier,
                "seed": seed,
                "call_at_t": call_at_t,
                "accused": str(ep_accused) if ep_accused is not None else None,
                "accused_day": ep_final_day if ep_accused is not None else None,
                "end_reason": ep_end,
                "correct": bool(cell_ep.get("correct")),
                "score": lv_score,
                "cost_usd": cost_usd,
                "thinking_tokens": tthink,
                "input_tokens": tin,
                "output_tokens": tout,
                "cached_tokens": tcached,
                "calls": tcalls,
                "ledger_calls": int(ledger_entry.get("calls") or 0),
                "run_id": run_id,
                "failure_tag": f_tag,
                "analyst_quote": a_quote,
                "regret_total": round(max(0.0, solver_final_score - lv_score), 4),
                "source_file": "results/gemini/ladder_episodes.jsonl.gz",
            }
        )

    cross_model_carbon: list[dict[str, Any]] = []
    for c_lv in ("low", "high"):
        c_ep = ladder_index.get(("gemini-4-carbon", c_lv, tier, seed))
        if c_ep is None:
            continue
        c_lad = (c_ep.get("meta") or {}).get("ladder") or {}
        c_tok = c_lad.get("tokens") or {}
        c_rid = str(c_lad.get("run_id") or "")
        c_led = ledger_index.get(c_rid, {})
        c_cost = float(c_led.get("cost_usd") or 0.0)
        if c_cost <= 0.0:
            c_cost = list_price_usd(
                "gemini-4-carbon",
                int(c_tok.get("in") or 0),
                int(c_tok.get("out") or 0),
                int(c_tok.get("thinking") or 0),
                int(c_tok.get("cached") or 0),
            )
        c_acc = c_ep.get("accused")
        cross_model_carbon.append(
            {
                "model": "gemini-4-carbon",
                "thinking_level": c_lv,
                "accused": str(c_acc) if c_acc is not None else None,
                "accused_day": int(c_ep.get("final_day") or 0) if c_acc is not None else None,
                "cost_usd": round(c_cost, 6),
                "thinking_tokens": int(c_tok.get("thinking") or 0),
                "score": round(float(c_ep.get("score") or 0.0), 4),
                "correct": bool(c_ep.get("correct")),
                "run_id": c_rid,
            }
        )
    if not cross_model_carbon and (tier, seed) in carbon_inproc:
        in_ep = carbon_inproc[(tier, seed)]
        in_u = (in_ep.get("meta") or {}).get("usage") or {}
        in_cost = float(in_u.get("cost_usd") or 0.0)
        if in_cost <= 0.0:
            in_cost = list_price_usd(
                "gemini-4-carbon",
                int(in_u.get("in") or 0),
                0,
                int(in_u.get("out") or 0),
                int(in_u.get("cached_in") or 0),
            )
        in_acc = in_ep.get("accused")
        cross_model_carbon.append(
            {
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "accused": str(in_acc) if in_acc is not None else None,
                "accused_day": int(in_ep.get("final_day") or 0) if in_acc is not None else None,
                "cost_usd": round(in_cost, 6),
                "thinking_tokens": int(in_u.get("out") or 0),
                "score": round(float(in_ep.get("score") or 0.0), 4),
                "correct": bool(in_ep.get("correct")),
                "run_id": f"inproc:v1.4:gemini-4-carbon/{tier}/{seed}",
            }
        )

    ladder_matrix: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (m_name, m_lv, m_tier, m_seed), m_ep in sorted(ladder_index.items()):
        if m_tier != tier or m_seed != seed:
            continue
        m_lad = (m_ep.get("meta") or {}).get("ladder") or {}
        m_tok = m_lad.get("tokens") or {}
        m_rid = str(m_lad.get("run_id") or "")
        m_led = ledger_index.get(m_rid, {})
        m_cost = float(m_led.get("cost_usd") or 0.0)
        if m_cost <= 0.0:
            m_cost = list_price_usd(
                m_name,
                int(m_tok.get("in") or 0),
                int(m_tok.get("out") or 0),
                int(m_tok.get("thinking") or 0),
                int(m_tok.get("cached") or 0),
            )
        ladder_matrix[m_name][m_lv] = {
            "score": round(float(m_ep.get("score") or 0.0), 4),
            "correct": bool(m_ep.get("correct")),
            "accused": m_ep.get("accused"),
            "final_day": int(m_ep.get("final_day") or 0),
            "end_reason": str(m_ep.get("end_reason") or "horizon"),
            "thinking_tokens": int(m_tok.get("thinking") or 0),
            "cost_usd": round(m_cost, 6),
            "run_id": m_rid,
        }

    return {
        "id": case_id,
        "title": clean_text(title),
        "model": anchor_model,
        "anchor_level": anchor_level,
        "tier": tier,
        "seed": seed,
        "company": company,
        "decision_day": decision_day,
        "decision_step": decision_step,
        "value_at_decision": value_at_decision,
        "suspects": suspects,
        "canaries": canaries_order,
        "leaks": leaks,
        "access_logs": access_logs,
        "comms": comms,
        "tool_steps": tool_steps,
        "true_mole": true_mole,
        "solver": solver_block,
        "thinking_levels": thinking_levels,
        "cross_model_carbon": cross_model_carbon,
        "ladder_matrix": dict(ladder_matrix),
    }


def build_payload() -> dict[str, Any]:
    ladder_index = load_ladder_index()
    ledger_index = load_ledger_index()
    solver_ref = load_solver_reference()
    carbon_quotes = load_carbon_transcript_quotes()
    carbon_inproc = load_carbon_inproc_runs()

    corpus_cost_usd = 0.0
    for (m_name, _lv, _tr, _sd), m_ep in ladder_index.items():
        m_lad = (m_ep.get("meta") or {}).get("ladder") or {}
        m_tok = m_lad.get("tokens") or {}
        m_rid = str(m_lad.get("run_id") or "")
        m_led = ledger_index.get(m_rid, {})
        c_val = float(m_led.get("cost_usd") or 0.0)
        if c_val <= 0.0:
            c_val = list_price_usd(
                m_name,
                int(m_tok.get("in") or 0),
                int(m_tok.get("out") or 0),
                int(m_tok.get("thinking") or 0),
                int(m_tok.get("cached") or 0),
            )
        corpus_cost_usd += c_val

    cases: list[dict[str, Any]] = []
    models_seen: list[str] = []
    levels_seen: set[str] = set()
    hold_fire_count = 0
    accuse_count = 0
    total_level_runs = 0

    for case_id, model, tier, seed, anchor_level, title in CASE_SPECS:
        case_obj = build_case(
            case_id=case_id,
            anchor_model=model,
            tier=tier,
            seed=seed,
            anchor_level=anchor_level,
            title=title,
            ladder_index=ladder_index,
            ledger_index=ledger_index,
            solver_ref=solver_ref,
            carbon_quotes=carbon_quotes,
            carbon_inproc=carbon_inproc,
        )
        cases.append(case_obj)
        if model not in models_seen:
            models_seen.append(model)
        for lv in case_obj["thinking_levels"]:
            levels_seen.add(lv["thinking_level"])
            total_level_runs += 1
        if case_obj["solver"]["recommended_call"] == "hold_fire":
            hold_fire_count += 1
        else:
            accuse_count += 1

    ordered_levels = [lv for lv in THINKING_LEVEL_ORDER if lv in levels_seen]
    return {
        "meta": {
            "title": "Out-Think Gemini: Committed Thinking-Ladder Decision Suite",
            "tiers_version": "v1.4",
            "source_episodes": "results/gemini/ladder_episodes.jsonl.gz",
            "source_ledger": "results/gemini/ladder_ledger.jsonl.gz",
            "source_solver": "data/runs/committed/v1.4/reference",
            "total_episodes": len(ladder_index),
            "total_cost_usd": round(corpus_cost_usd, 4),
            "ladder_corpus_episodes": len(ladder_index),
            "ledger_unique_runs": len(ledger_index),
            "case_count": len(cases),
            "level_run_count": total_level_runs,
            "hold_fire_cases": hold_fire_count,
            "accuse_cases": accuse_count,
            "models": models_seen,
            "thinking_levels": ordered_levels,
            "isBootstrapFallback": False,
        },
        "cases": cases,
    }


def render_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=True) + "\n"


def render_cases_js(payload: dict[str, Any]) -> str:
    compact = json.dumps(payload, separators=(",", ":"), sort_keys=False, ensure_ascii=True)
    lines = [
        "(function (root) {",
        f"  var data = {compact};",
        '  if (typeof window !== "undefined" && window) {',
        "    window.OUTTHINK_DATA = data;",
        "    window.OUTTHINK_CASES = data.cases;",
        "  }",
        '  if (root && typeof root === "object") {',
        "    root.OUTTHINK_DATA = data;",
        "    root.OUTTHINK_CASES = data.cases;",
        "  }",
        '  if (typeof module !== "undefined" && module.exports) {',
        "    module.exports = data;",
        "  }",
        '})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);',
        "",
    ]
    return "\n".join(lines)


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = payload.get("meta")
    cases = payload.get("cases")
    if not isinstance(meta, dict):
        return ["missing meta dict"]
    if not isinstance(cases, list) or len(cases) < 8:
        return ["cases must be a list of at least 8 decision points"]

    seen_ids: set[str] = set()
    rec_calls: set[str] = set()
    levels_covered: set[str] = set()

    for idx, c in enumerate(cases):
        cid = str(c.get("id") or f"idx_{idx}")
        if cid in seen_ids:
            errors.append(f"duplicate case id {cid}")
        seen_ids.add(cid)

        for req_key in (
            "id",
            "title",
            "tier",
            "seed",
            "company",
            "decision_day",
            "decision_step",
            "value_at_decision",
            "suspects",
            "canaries",
            "leaks",
            "access_logs",
            "comms",
            "tool_steps",
            "true_mole",
            "solver",
            "thinking_levels",
        ):
            if req_key not in c:
                errors.append(f"{cid}: missing key {req_key}")

        suspect_ids = {s["id"] for s in c.get("suspects", [])}
        if c.get("true_mole") not in suspect_ids:
            errors.append(f"{cid}: true_mole not in suspects")
        if int(c.get("decision_step", 0)) != len(c.get("tool_steps", [])):
            errors.append(f"{cid}: decision_step must equal len(tool_steps)")

        solver = c.get("solver") or {}
        post = solver.get("posterior") or {}
        p_sum = sum(float(v) for v in post.values())
        if abs(p_sum - 1.0) > 1e-3:
            errors.append(f"{cid}: solver posterior sum {p_sum} != 1.0")
        rec_calls.add(str(solver.get("recommended_call") or ""))

        t_levels = c.get("thinking_levels") or []
        if len(t_levels) < 2:
            errors.append(f"{cid}: fewer than 2 thinking_levels")
        for lv in t_levels:
            levels_covered.add(str(lv.get("thinking_level") or ""))
            if not lv.get("run_id"):
                errors.append(f"{cid}/{lv.get('key')}: missing run_id")
            if int(lv.get("ledger_calls") or 0) <= 0:
                errors.append(f"{cid}/{lv.get('key')}: zero ledger_calls")
            if lv.get("call_at_t") not in {"accuse", "hold_fire"}:
                errors.append(f"{cid}/{lv.get('key')}: invalid call_at_t")

    if rec_calls != {"accuse", "hold_fire"}:
        errors.append(f"expected both accuse and hold_fire recommended_call values, got {sorted(rec_calls)}")
    for req_lv in THINKING_LEVEL_ORDER:
        if req_lv not in levels_covered:
            errors.append(f"missing thinking level {req_lv} across cases")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary.gemini.outthink")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--js-out", type=Path, default=DEFAULT_JS_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    payload = build_payload()
    errors = validate_payload(payload)
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    expected_json = render_json_text(payload)
    expected_js = render_cases_js(payload)

    for label, txt in (("json", expected_json), ("js", expected_js)):
        if EM_DASH in txt or EN_DASH in txt:
            sys.stderr.write(f"ERROR: dash character found in {label}\n")
            return 1
        if FORBIDDEN_NET in txt:
            sys.stderr.write(f"ERROR: forbidden network call token in {label}\n")
            return 1

    if args.check:
        if not args.json_out.is_file():
            sys.stderr.write(f"ERROR: missing {args.json_out}\n")
            return 1
        if not args.js_out.is_file():
            sys.stderr.write(f"ERROR: missing {args.js_out}\n")
            return 1
        actual_json = args.json_out.read_text(encoding="utf-8")
        actual_js = args.js_out.read_text(encoding="utf-8")
        if actual_json != expected_json:
            sys.stderr.write(f"ERROR: {args.json_out} is out of date with deterministic build\n")
            return 1
        if actual_js != expected_js:
            sys.stderr.write(f"ERROR: {args.js_out} is out of date with deterministic build\n")
            return 1
        sys.stdout.write(
            f"OK: {len(payload['cases'])} cases, {payload['meta']['level_run_count']} ladder runs verified.\n"
        )
        return 0

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.js_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(expected_json, encoding="utf-8")
    args.js_out.write_text(expected_js, encoding="utf-8")
    sys.stdout.write(
        f"Wrote {args.json_out} and {args.js_out} ({len(payload['cases'])} cases).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
