from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import lab_client
from canary.llm import register_script
from canary.rules import tier_params
from canary.types import INVESTIGATIVE_TOOLS
from canary.world import generate_world

ROLE = "failure_analyst"
SUBROLE = "biased_chatter_decision_forensics"
FEATURE = "chatter_bias_forensics"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_THINKING_LEVEL = "high"
DEFAULT_ABLATION_DIRS: tuple[Path, ...] = (
    Path("results/gemini_roles/world_text/biased-chatter-ablation-carbon"),
    Path("results/gemini_roles/world_text/biased-chatter-ablation-hard01"),
)
DEFAULT_OUT_DIR = Path("results/gemini_roles/failure_analyst/chatter-bias-forensics-carbon")

MD_H1 = chr(35)
MD_H2 = chr(35) * 2
MD_H3 = chr(35) * 3

POLICY_ORDER = ("carbon", "solver", "obvious_heuristic")
WORLD_ORDER = ("biased", "template")
TIER_ORDER = ("easy", "medium", "hard")

MODE_ENUM = [
    "rumor_target_verification_delay",
    "canary_confirmation_overrides_chatter",
    "message_search_budget_sink",
    "exhaustive_interview_sweep_drag",
    "heuristic_decoy_and_rumor_collapse",
    "solver_bayesian_chatter_invariance",
]

POLARITY_ENUM = [
    "failure_mode",
    "resilience_mode",
    "mixed_tradeoff",
]

CHATTER_EFFECT_ENUM = [
    "resilient_override_after_rumor_check",
    "rumor_distraction_score_drag",
    "faster_canary_resolution_on_biased",
    "neutral_template_baseline",
    "chatter_invariant_bayesian",
    "heuristic_false_accusation_collapse",
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
                "copied in full without any modification or truncation from that episode block."
            ),
        },
    },
    "required": ["episode_id", "quote"],
}

CHATTER_FORENSICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": (
                "Concise quantitative synthesis comparing biased workplace chatter vs neutral template "
                "investigator decisions across medium and hard seeds. Use plain ASCII hyphens only."
            ),
        },
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mode_id": {"type": "string", "enum": MODE_ENUM},
                    "polarity": {"type": "string", "enum": POLARITY_ENUM},
                    "title": {"type": "string"},
                    "episode_ids": {"type": "array", "items": {"type": "string"}},
                    "mechanism": {"type": "string"},
                    "decision_impact": {"type": "string"},
                    "mitigation": {"type": "string"},
                    "quotes": {"type": "array", "items": QUOTE_ITEM_SCHEMA},
                },
                "required": [
                    "mode_id",
                    "polarity",
                    "title",
                    "episode_ids",
                    "mechanism",
                    "decision_impact",
                    "mitigation",
                    "quotes",
                ],
            },
        },
        "episode_diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "string"},
                    "primary_mode": {"type": "string", "enum": MODE_ENUM},
                    "chatter_effect": {"type": "string", "enum": CHATTER_EFFECT_ENUM},
                    "rationale": {"type": "string"},
                    "trigger_quote": QUOTE_ITEM_SCHEMA,
                },
                "required": [
                    "episode_id",
                    "primary_mode",
                    "chatter_effect",
                    "rationale",
                    "trigger_quote",
                ],
            },
        },
    },
    "required": ["executive_summary", "clusters", "episode_diagnoses"],
}

SYSTEM_PROMPT = (
    "You are the Biased-Workplace-Chatter Decision Forensics Analyst for the Canary insider-leak benchmark.\n"
    "You analyze paired investigator ablation episodes run on identical hidden worlds under two text providers:\n"
    "  1. 'biased' (BiasedChatterProvider): injects realistic cognitive-bias workplace messages on Day 1+ "
    "(bc1-0 unverified_rumour targeting an innocent rumour_target, bc1-1/bc1-2 grudge_bickering, "
    "bc1-3 authority_bias dismissal by manager_id, bc1-4 unplanned_doc_forward), alongside the regular decoy.\n"
    "  2. 'template' (TemplateProvider): neutral structured workplace messages on the exact same (tier, seed) world.\n"
    "Across each (tier, seed, world) cell, three policies are evaluated: 'carbon' (gemini-4-carbon LLM investigator), "
    "'solver' (exact Bayesian SolverPolicy), and 'obvious_heuristic' (surface access-log/decoy baseline).\n\n"
    "STRICT REQUIREMENTS:\n"
    "1. Synthesize 4 to 6 distinct social-chatter failure and resilience mode clusters across the paired corpus "
    "(covering rumor-target verification distraction vs canary confirmation overriding biased workplace talk, "
    "message-search budget sink including invalid whitespace/vowel queries, exhaustive interview sweep drag, "
    "heuristic collapse onto framed decoys/rumor targets, and Bayesian solver chatter invariance).\n"
    "2. Provide an episode_diagnoses entry for EVERY EPISODE in REQUIRED_EPISODE_IDS (exact same episode_id), "
    "explicitly tying its tool-call trajectory and accusation decision to its paired biased/template counterpart.\n"
    "3. EVERY quote (in clusters[].quotes and in episode_diagnoses[].trigger_quote) MUST set episode_id to an "
    "exact EPISODE id from the input and set quote to an ENTIRE numbered step line starting with [S...] copied "
    "character-for-character from start to end from that exact episode block. Never quote META/TARGETS/METRICS/THOUGHT "
    "header lines, never alter spacing, never truncate, and never invent step numbers.\n"
    "4. Never use em dashes or en dashes anywhere; use plain ASCII '-' or commas/colons instead.\n"
    "5. Output valid JSON matching the schema only."
)

OMITTED_SIG_RE = re.compile(r"<omitted_signature:\d+_chars>")
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")
SECRET_LIKE_RE = re.compile(
    r"(?:AIza[0-9A-Za-z_\-]{6,}|sk-[A-Za-z0-9_\-]{8,}|ya29\.[0-9A-Za-z_\-]{8,}|"
    r"(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*[:=]\s*\S+)"
)
STEP_PREFIX_RE = re.compile(r"^\[(S\d{3,4})\]")
BOILERPLATE_PREFIXES = (
    "here's my thought",
    "here is my thought",
    "okay, here's my",
    "okay, here is my",
    "alright, so the task",
    "okay, let's get down to brass tacks",
    "let's get down to brass tacks",
)


def sanitize_text(text: str) -> str:
    s = str(text or "")
    s = s.replace("\u2014", " - ").replace("\u2013", "-").replace("\u2012", "-").replace("\u2015", "-")
    return s


def strip_signatures_and_secrets(text: str) -> str:
    s = sanitize_text(text)
    s = OMITTED_SIG_RE.sub(" ", s)
    s = SECRET_LIKE_RE.sub("[redacted]", s)
    s = LONG_TOKEN_RE.sub(" ", s)
    return s


def _clean_inline(val: Any, max_len: int = 80) -> str:
    s = str(val if val is not None else "")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", "'").replace("\u201d", "'")
    s = s.replace("\u2026", "...")
    s = strip_signatures_and_secrets(s)
    s = s.replace('"', "'").replace("\\", "/").replace("`", "'").replace(chr(35), "")
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in s)
    s = re.sub(r" +", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s


def extract_thought_excerpt(
    raw_thought: str,
    focus_terms: Sequence[str] = (),
    max_len: int = 84,
) -> str:
    cleaned = strip_signatures_and_secrets(raw_thought)
    if not cleaned.strip():
        return ""
    lines = []
    for raw_ln in cleaned.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if ln.startswith("**") and ln.endswith("**") and len(ln) < 90:
            continue
        ln = ln.replace("**", "").replace("*", "")
        lines.append(ln)
    joined = " ".join(lines)
    raw_sents = re.split(r"(?<=[.!?])\s+", joined)
    candidates: list[str] = []
    for sent in raw_sents:
        s = _clean_inline(sent, max_len=240)
        if len(s) < 12:
            continue
        low = s.lower()
        if any(low.startswith(pref) for pref in BOILERPLATE_PREFIXES):
            continue
        candidates.append(s)
    if not candidates:
        return ""
    lowered_terms = [t.lower() for t in focus_terms if t]
    for cand in candidates:
        clow = cand.lower()
        if any(term in clow for term in lowered_terms):
            return _clean_inline(cand, max_len=max_len)
    return _clean_inline(candidates[0], max_len=max_len)


def current_git_commit(cwd: Path = ROOT) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        sha = res.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha) else "0000000"
    except Exception:
        return "0000000"


def parse_transcript_steps(transcript_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(transcript_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("steps"), list):
        steps_out: list[dict[str, Any]] = []
        for idx, st in enumerate(raw["steps"]):
            if not isinstance(st, dict):
                continue
            args = st.get("args") if isinstance(st.get("args"), dict) else {}
            res = st.get("result") if isinstance(st.get("result"), dict) else {"ok": True, "data": {}, "error": None}
            thought_raw = str(st.get("thought") or "")
            steps_out.append(
                {
                    "t": idx,
                    "day": int(st.get("day", 1) or 1),
                    "tool": str(st.get("tool", "unknown")),
                    "args": args,
                    "result": res,
                    "thought": strip_signatures_and_secrets(thought_raw) if thought_raw else "",
                }
            )
        return steps_out

    if not isinstance(raw, list):
        raise ValueError(f"unsupported transcript structure in {transcript_path}")

    tool_results: dict[str, dict[str, Any]] = {}
    for msg in raw:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        tc_id = str(msg.get("tool_call_id") or "")
        if not tc_id:
            continue
        raw_content = msg.get("content")
        if isinstance(raw_content, dict):
            parsed_res = raw_content
        else:
            try:
                parsed_res = json.loads(str(raw_content or "{}"))
            except ValueError:
                parsed_res = {"ok": False, "data": {}, "error": "unparseable_tool_result"}
        if isinstance(parsed_res, dict):
            tool_results[tc_id] = parsed_res

    steps_out = []
    cur_day = 1
    idx = 0
    for msg in raw:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        thought_chunks: list[str] = []
        for p_item in msg.get("provider_items") or []:
            if not isinstance(p_item, dict):
                continue
            for part in p_item.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("thought") and isinstance(part.get("text"), str) and part["text"].strip():
                    thought_chunks.append(strip_signatures_and_secrets(part["text"]))
        if not thought_chunks and isinstance(msg.get("content"), str) and msg["content"].strip():
            thought_chunks.append(strip_signatures_and_secrets(msg["content"]))
        combined_thought = "\n".join(thought_chunks).strip()

        tcalls = msg.get("tool_calls") or []
        for tc_pos, tc in enumerate(tcalls):
            if not isinstance(tc, dict):
                continue
            tname = str(tc.get("name") or "unknown")
            targs = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tc_id = str(tc.get("id") or "")
            tres = tool_results.get(tc_id)
            if tres is None:
                if tname == "accuse":
                    tres = {
                        "ok": True,
                        "data": {"accused": targs.get("employee"), "episode_over": True},
                        "error": None,
                    }
                else:
                    tres = {"ok": True, "data": {}, "error": None}
            data = tres.get("data") if isinstance(tres.get("data"), dict) else {}
            ok = bool(tres.get("ok", True))
            if tname == "status" and ok and isinstance(data.get("day"), int):
                cur_day = int(data["day"])
            if tname == "advance_day" and ok and isinstance(data.get("closed_day"), int):
                step_day = int(data["closed_day"])
            else:
                step_day = cur_day
            steps_out.append(
                {
                    "t": idx,
                    "day": step_day,
                    "tool": tname,
                    "args": targs,
                    "result": tres,
                    "thought": combined_thought if tc_pos == 0 else "",
                }
            )
            idx += 1
            if tname == "advance_day" and ok and isinstance(data.get("day"), int):
                cur_day = int(data["day"])
    return steps_out


def format_step_line(idx: int, step: dict[str, Any]) -> str:
    day = step.get("day", "?")
    tool = _clean_inline(step.get("tool", "unknown"), 40)
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    res = step.get("result") if isinstance(step.get("result"), dict) else {}
    ok = bool(res.get("ok", True))
    data = res.get("data") if isinstance(res.get("data"), dict) else {}

    prefix = f"[S{idx:03d}] d{day}"
    if not ok:
        err = _clean_inline(res.get("error") or "error", 64)
        arg_s = ", ".join(f"{_clean_inline(k, 20)}={_clean_inline(v, 24)}" for k, v in sorted(args.items()))
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
        counts = Counter(_clean_inline(v, 10) for v in asgn.values())
        split_items = sorted(counts.items())
        split_s = ",".join(f"{k}:{c}" for k, c in split_items[:6]) or "none"
        if len(split_items) > 6:
            split_s += f",+{len(split_items) - 6}more"
        cid = _clean_inline(data.get("canary_id", ""), 16)
        return f"{prefix} plant_canary(split={split_s}, assigned={len(asgn)}) -> ok canary_id={cid}"

    if tool == "check_leak_feed":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        leaks = [
            f"{_clean_inline(it.get('doc_id', '?'), 16)}:{_clean_inline(it.get('variant', 'base'), 10)}@d{it.get('surfaced_day', '?')}"
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
        emp_filter = _clean_inline(args.get("employee", ""), 10)
        if emp_filter:
            return (
                f"{prefix} read_access_logs(day={d_from}..{d_to}, employee={emp_filter}) "
                f"-> ok count={len(logs)} after_hours=[{top_ah}]"
            )
        return f"{prefix} read_access_logs(day={d_from}..{d_to}) -> ok count={len(logs)} after_hours=[{top_ah}]"

    if tool == "search_messages":
        msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
        q = _clean_inline(args.get("query", ""), 24)
        d_from = args.get("day_from", 1)
        d_to = args.get("day_to", day)
        mids = ",".join(
            _clean_inline(m.get("id", ""), 12) for m in msgs[:4] if isinstance(m, dict) and m.get("id")
        )
        if mids:
            return f"{prefix} search_messages(query='{q}', day={d_from}..{d_to}) -> ok matches={len(msgs)} ids=[{mids}]"
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
        ans = _clean_inline(data.get("answer", ""), 52)
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

    arg_s = ", ".join(f"{_clean_inline(k, 20)}={_clean_inline(v, 24)}" for k, v in sorted(args.items()))
    return f"{prefix} {tool}({arg_s}) -> ok"


def _resolve_world_truth(
    tier: str,
    seed: int,
    seed_episodes: Sequence[dict[str, Any]],
) -> tuple[str | None, str | None]:
    explicit_mole = next((str(e["true_mole"]) for e in seed_episodes if e.get("true_mole")), None)
    explicit_decoy = next((str(e["framed_decoy"]) for e in seed_episodes if e.get("framed_decoy")), None)
    if explicit_mole is not None or explicit_decoy is not None:
        return explicit_mole, explicit_decoy
    try:
        w = generate_world(tier, int(seed), tier_params(tier))
        return w.mole, w.decoy
    except Exception:
        inferred_mole = next(
            (str(e["accused"]) for e in seed_episodes if e.get("correct") and e.get("accused")),
            None,
        )
        return inferred_mole, None


def _classify_accused_target(
    accused: str | None,
    true_mole: str | None,
    framed_decoy: str | None,
    rumor_target: str | None,
    grudge_pair: Sequence[str],
    correct: bool,
) -> str:
    if not accused:
        return "abstained"
    if correct or (true_mole and accused == true_mole):
        return "true_mole"
    is_decoy = bool(framed_decoy and accused == framed_decoy)
    is_rumor = bool(rumor_target and accused == rumor_target)
    if is_decoy and is_rumor:
        return "framed_decoy_and_rumor_target"
    if is_decoy:
        return "framed_decoy"
    if is_rumor:
        return "rumor_target"
    if accused in set(grudge_pair):
        return "grudge_persona"
    return "other_innocent"


def compute_episode_forensics(
    ep_entry: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    tier: str,
    company: str,
    bias_spec: dict[str, Any],
    true_mole: str | None,
    framed_decoy: str | None,
    ablation_dir: Path,
) -> dict[str, Any]:
    seed = int(ep_entry.get("seed", 0))
    policy = str(ep_entry.get("policy", "unknown"))
    world_arm = str(ep_entry.get("world", "unknown"))
    rumor_target = str(bias_spec.get("rumour_target") or ep_entry.get("rumour_target") or "")
    grudge_raw = bias_spec.get("grudge_pair") or []
    grudge_pair = [str(x) for x in grudge_raw[:2]]
    manager_id = str(bias_spec.get("manager_id") or "")
    bias_personas = {x for x in [rumor_target, *grudge_pair, manager_id] if x}

    total_steps = len(steps)
    tool_counts = Counter(st["tool"] for st in steps)
    error_steps = sum(1 for st in steps if not bool(st["result"].get("ok", True)))
    inv_total = sum(1 for st in steps if st["tool"] in INVESTIGATIVE_TOOLS)
    inv_ok = sum(
        1 for st in steps if st["tool"] in INVESTIGATIVE_TOOLS and bool(st["result"].get("ok", True))
    )

    interview_steps = [st for st in steps if st["tool"] == "interview"]
    restrict_steps = [st for st in steps if st["tool"] == "restrict_access"]
    ir_total = len(interview_steps) + len(restrict_steps)

    rt_interviews = sum(1 for st in interview_steps if st["args"].get("employee") == rumor_target)
    rt_restrictions = sum(1 for st in restrict_steps if st["args"].get("employee") == rumor_target)
    rt_total = rt_interviews + rt_restrictions

    decoy_interviews = (
        sum(1 for st in interview_steps if st["args"].get("employee") == framed_decoy)
        if framed_decoy
        else 0
    )
    decoy_restrictions = (
        sum(1 for st in restrict_steps if st["args"].get("employee") == framed_decoy)
        if framed_decoy
        else 0
    )
    decoy_total = decoy_interviews + decoy_restrictions

    persona_calls = sum(
        1 for st in (interview_steps + restrict_steps) if st["args"].get("employee") in bias_personas
    )

    search_steps = [st for st in steps if st["tool"] == "search_messages"]
    search_ok = sum(1 for st in search_steps if bool(st["result"].get("ok", True)))
    search_err = len(search_steps) - search_ok
    read_msg_steps = [st for st in steps if st["tool"] == "read_message"]
    msg_calls_total = len(search_steps) + len(read_msg_steps)

    messages_read = [
        _clean_inline(st["args"].get("id", ""), 24)
        for st in read_msg_steps
        if st["args"].get("id")
    ]
    bias_msgs_read = [mid for mid in messages_read if mid.startswith("bc")]
    read_rumor_msg = "bc1-0" in messages_read
    search_queries = [
        _clean_inline(st["args"].get("query", ""), 32)
        for st in search_steps
    ]

    canary_Assignments: dict[str, dict[str, str]] = {}
    canary_splits: list[dict[str, Any]] = []
    singleton_total = 0
    assigned_total = 0
    unique_variants_total = 0

    for st in steps:
        if st["tool"] != "plant_canary" or not bool(st["result"].get("ok", True)):
            continue
        asgn_raw = st["args"].get("assignment") if isinstance(st["args"].get("assignment"), dict) else {}
        asgn = {str(emp): str(var) for emp, var in asgn_raw.items()}
        rdata = st["result"].get("data") if isinstance(st["result"].get("data"), dict) else {}
        cid = str(rdata.get("canary_id") or f"c{len(canary_splits) + 1}")
        canary_Assignments[cid] = asgn
        v_counts = Counter(asgn.values())
        singletons = sum(1 for cnt in v_counts.values() if cnt == 1)
        singleton_total += singletons
        assigned_total += len(asgn)
        unique_variants_total += len(v_counts)
        canary_splits.append(
            {
                "canary_id": cid,
                "day": st["day"],
                "assigned_count": len(asgn),
                "unique_variants": len(v_counts),
                "singleton_variants": singletons,
                "split": dict(sorted(v_counts.items())),
            }
        )

    accused_raw = ep_entry.get("accused")
    if accused_raw is None:
        acc_step = next((st for st in reversed(steps) if st["tool"] == "accuse"), None)
        if acc_step is not None:
            accused_raw = acc_step["args"].get("employee")
    accused = str(accused_raw) if accused_raw else None
    correct = bool(ep_entry.get("correct", bool(true_mole and accused == true_mole)))

    surfaced_canary_leaks: list[str] = []
    seen_canary_leaks: set[str] = set()
    canary_confirmed_mole = False
    for st in steps:
        if st["tool"] != "check_leak_feed" or not bool(st["result"].get("ok", True)):
            continue
        rdata = st["result"].get("data") if isinstance(st["result"].get("data"), dict) else {}
        for it in rdata.get("items") or []:
            if not isinstance(it, dict):
                continue
            did = str(it.get("doc_id") or "")
            var = it.get("variant")
            if did.startswith("c") and var:
                tag = f"{did}:{var}@d{it.get('surfaced_day', '?')}"
                if tag not in seen_canary_leaks:
                    seen_canary_leaks.add(tag)
                    surfaced_canary_leaks.append(tag)
                asgn = canary_Assignments.get(did) or {}
                holders = [emp for emp, v in asgn.items() if v == str(var)]
                if len(holders) == 1 and true_mole and holders[0] == true_mole:
                    canary_confirmed_mole = True

    focus_terms = [
        rumor_target,
        framed_decoy or "",
        true_mole or "",
        "bc1-0",
        "rumor",
        "rumour",
        "canary",
        "variant",
        "accuse",
        "interview",
    ]
    thought_highlights: list[dict[str, Any]] = []
    priority_tools = {
        "read_message",
        "interview",
        "restrict_access",
        "check_leak_feed",
        "accuse",
        "plant_canary",
        "search_messages",
    }
    for idx, st in enumerate(steps):
        raw_th = st.get("thought") or ""
        if not raw_th or st["tool"] not in priority_tools:
            continue
        is_key_event = (
            st["tool"] in {"read_message", "accuse"}
            or (st["tool"] == "interview" and st["args"].get("employee") in {rumor_target, framed_decoy, true_mole})
            or (st["tool"] == "check_leak_feed" and "c" in str(st["result"].get("data", {})))
            or (st["tool"] == "search_messages" and not bool(st["result"].get("ok", True)))
        )
        if not is_key_event and len(thought_highlights) >= 3:
            continue
        exc = extract_thought_excerpt(raw_th, focus_terms=focus_terms, max_len=84)
        if exc:
            thought_highlights.append(
                {
                    "step": f"S{idx:03d}",
                    "day": st["day"],
                    "tool": st["tool"],
                    "excerpt": exc,
                }
            )
        if len(thought_highlights) >= 5:
            break

    n_can = len(canary_splits)
    final_day = int(ep_entry.get("final_day") or (steps[-1]["day"] if steps else 1))
    score = round(float(ep_entry.get("score", 0.0)), 6)
    target_role = _classify_accused_target(
        accused=accused,
        true_mole=true_mole,
        framed_decoy=framed_decoy,
        rumor_target=rumor_target,
        grudge_pair=grudge_pair,
        correct=correct,
    )

    return {
        "tier": tier,
        "seed": seed,
        "company": sanitize_text(company),
        "policy": policy,
        "agent_name": sanitize_text(ep_entry.get("agent_name", policy)),
        "world_arm": world_arm,
        "ablation_dir": ablation_dir.as_posix(),
        "transcript_file": str(ep_entry.get("transcript_file", "")),
        "score": score,
        "accuracy": 1.0 if correct else 0.0,
        "correct": correct,
        "final_day": final_day,
        "end_reason": sanitize_text(ep_entry.get("end_reason", "unknown")),
        "total_steps": total_steps,
        "investigative_calls_total": inv_total,
        "paid_action_calls_ok": inv_ok,
        "error_step_count": error_steps,
        "tool_counts": dict(sorted(tool_counts.items())),
        "true_mole": true_mole,
        "framed_decoy": framed_decoy,
        "rumor_target": rumor_target,
        "decoy_equals_rumor_target": bool(framed_decoy and rumor_target and framed_decoy == rumor_target),
        "grudge_pair": grudge_pair,
        "manager_id": manager_id,
        "accused": accused,
        "accused_true_mole": bool(true_mole and accused == true_mole) or correct,
        "accused_framed_decoy": bool(framed_decoy and accused == framed_decoy),
        "accused_rumor_target": bool(rumor_target and accused == rumor_target),
        "accused_grudge_member": bool(accused and accused in set(grudge_pair)),
        "accused_target_role": target_role,
        "interview_calls": len(interview_steps),
        "restrict_calls": len(restrict_steps),
        "interview_restrict_calls": ir_total,
        "rumor_target_interviews": rt_interviews,
        "rumor_target_restrictions": rt_restrictions,
        "rumor_target_distraction_calls": rt_total,
        "rumor_target_distracted": rt_total > 0,
        "rumor_target_interview_share": round(rt_interviews / len(interview_steps), 6) if interview_steps else 0.0,
        "rumor_target_restriction_share": round(rt_restrictions / len(restrict_steps), 6) if restrict_steps else 0.0,
        "rumor_target_action_share": round(rt_total / ir_total, 6) if ir_total > 0 else 0.0,
        "rumor_target_step_share": round(rt_total / total_steps, 6) if total_steps > 0 else 0.0,
        "bias_persona_distraction_calls": persona_calls,
        "bias_persona_action_share": round(persona_calls / ir_total, 6) if ir_total > 0 else 0.0,
        "framed_decoy_interviews": decoy_interviews,
        "framed_decoy_restrictions": decoy_restrictions,
        "framed_decoy_action_share": round(decoy_total / ir_total, 6) if ir_total > 0 else 0.0,
        "search_messages_calls": len(search_steps),
        "search_messages_ok_calls": search_ok,
        "search_messages_err_calls": search_err,
        "read_message_calls": len(read_msg_steps),
        "message_calls_total": msg_calls_total,
        "message_budget_share": round(msg_calls_total / inv_total, 6) if inv_total > 0 else 0.0,
        "message_step_share": round(msg_calls_total / total_steps, 6) if total_steps > 0 else 0.0,
        "messages_read": messages_read,
        "bias_chatter_messages_read": bias_msgs_read,
        "read_rumor_message": read_rumor_msg,
        "search_queries": search_queries,
        "canaries_planted": n_can,
        "canary_assigned_total": assigned_total,
        "canary_mean_assigned": round(assigned_total / n_can, 3) if n_can > 0 else 0.0,
        "canary_mean_unique_variants": round(unique_variants_total / n_can, 3) if n_can > 0 else 0.0,
        "canary_singleton_variant_count": singleton_total,
        "canary_splits": canary_splits,
        "canary_leaks_surfaced": surfaced_canary_leaks,
        "canary_confirmed_mole": canary_confirmed_mole,
        "thought_highlights": thought_highlights,
    }


def _summarize_episode_group(
    episodes: Sequence[dict[str, Any]],
    *,
    policy: str,
    world_arm: str,
    tier: str = "all",
) -> dict[str, Any]:
    n = len(episodes)
    if n == 0:
        return {
            "tier": tier,
            "policy": policy,
            "world_arm": world_arm,
            "n": 0,
            "score_mean": 0.0,
            "accuracy": 0.0,
            "mean_final_day": 0.0,
            "mean_steps": 0.0,
            "rumor_target_distraction_rate": 0.0,
            "rumor_target_interviews_total": 0,
            "rumor_target_restrictions_total": 0,
            "rumor_target_action_share_mean": 0.0,
            "rumor_target_pooled_action_share": 0.0,
            "rumor_target_accused_rate": 0.0,
            "framed_decoy_accused_rate": 0.0,
            "message_calls_total": 0,
            "search_messages_err_total": 0,
            "message_budget_share_mean": 0.0,
            "message_step_share_mean": 0.0,
            "read_rumor_message_rate": 0.0,
            "mean_canaries_planted": 0.0,
            "canary_confirmed_rate": 0.0,
        }
    tot_ir = sum(int(e["interview_restrict_calls"]) for e in episodes)
    tot_rt = sum(int(e["rumor_target_distraction_calls"]) for e in episodes)
    return {
        "tier": tier,
        "policy": policy,
        "world_arm": world_arm,
        "n": n,
        "score_mean": round(sum(float(e["score"]) for e in episodes) / n, 6),
        "accuracy": round(sum(float(e["accuracy"]) for e in episodes) / n, 6),
        "mean_final_day": round(sum(int(e["final_day"]) for e in episodes) / n, 3),
        "mean_steps": round(sum(int(e["total_steps"]) for e in episodes) / n, 3),
        "rumor_target_distraction_rate": round(
            sum(1.0 if e["rumor_target_distracted"] else 0.0 for e in episodes) / n, 6
        ),
        "rumor_target_interviews_total": sum(int(e["rumor_target_interviews"]) for e in episodes),
        "rumor_target_restrictions_total": sum(int(e["rumor_target_restrictions"]) for e in episodes),
        "rumor_target_action_share_mean": round(
            sum(float(e["rumor_target_action_share"]) for e in episodes) / n, 6
        ),
        "rumor_target_pooled_action_share": round(tot_rt / tot_ir, 6) if tot_ir > 0 else 0.0,
        "rumor_target_accused_rate": round(
            sum(1.0 if e["accused_rumor_target"] else 0.0 for e in episodes) / n, 6
        ),
        "framed_decoy_accused_rate": round(
            sum(1.0 if e["accused_framed_decoy"] else 0.0 for e in episodes) / n, 6
        ),
        "message_calls_total": sum(int(e["message_calls_total"]) for e in episodes),
        "search_messages_err_total": sum(int(e["search_messages_err_calls"]) for e in episodes),
        "message_budget_share_mean": round(
            sum(float(e["message_budget_share"]) for e in episodes) / n, 6
        ),
        "message_step_share_mean": round(
            sum(float(e["message_step_share"]) for e in episodes) / n, 6
        ),
        "read_rumor_message_rate": round(
            sum(1.0 if e["read_rumor_message"] else 0.0 for e in episodes) / n, 6
        ),
        "mean_canaries_planted": round(sum(int(e["canaries_planted"]) for e in episodes) / n, 3),
        "canary_confirmed_rate": round(
            sum(1.0 if e["canary_confirmed_mole"] else 0.0 for e in episodes) / n, 6
        ),
    }


def _compute_paired_delta(biased_arm: dict[str, Any], template_arm: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy": biased_arm["policy"],
        "tier": biased_arm["tier"],
        "n_biased": biased_arm["n"],
        "n_template": template_arm["n"],
        "score_delta": round(float(biased_arm["score_mean"]) - float(template_arm["score_mean"]), 6),
        "accuracy_delta": round(float(biased_arm["accuracy"]) - float(template_arm["accuracy"]), 6),
        "final_day_delta": round(float(biased_arm["mean_final_day"]) - float(template_arm["mean_final_day"]), 3),
        "steps_delta": round(float(biased_arm["mean_steps"]) - float(template_arm["mean_steps"]), 3),
        "rumor_target_distraction_rate_delta": round(
            float(biased_arm["rumor_target_distraction_rate"]) - float(template_arm["rumor_target_distraction_rate"]),
            6,
        ),
        "rumor_target_action_share_delta": round(
            float(biased_arm["rumor_target_action_share_mean"]) - float(template_arm["rumor_target_action_share_mean"]),
            6,
        ),
        "rumor_target_interviews_delta": (
            int(biased_arm["rumor_target_interviews_total"]) - int(template_arm["rumor_target_interviews_total"])
        ),
        "message_calls_delta": int(biased_arm["message_calls_total"]) - int(template_arm["message_calls_total"]),
        "message_budget_share_delta": round(
            float(biased_arm["message_budget_share_mean"]) - float(template_arm["message_budget_share_mean"]),
            6,
        ),
        "canaries_planted_delta": round(
            float(biased_arm["mean_canaries_planted"]) - float(template_arm["mean_canaries_planted"]),
            3,
        ),
        "read_rumor_message_rate_biased": float(biased_arm["read_rumor_message_rate"]),
    }


def collect_paired_ablation_corpus(
    ablation_dirs: Sequence[str | Path] = DEFAULT_ABLATION_DIRS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    for raw_dir in ablation_dirs:
        adir = Path(raw_dir)
        comp_path = adir / "comparison.json"
        if not comp_path.is_file():
            raise FileNotFoundError(f"missing comparison.json in {adir}")
        comp = json.loads(comp_path.read_text(encoding="utf-8"))
        default_tier = str(comp.get("tier") or "medium")
        seed_specs = comp.get("seed_bias_specs") if isinstance(comp.get("seed_bias_specs"), dict) else {}
        ep_list = comp.get("episodes") if isinstance(comp.get("episodes"), list) else []

        by_seed: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for ep in ep_list:
            if isinstance(ep, dict):
                etier = str(ep.get("tier") or default_tier)
                eseed = int(ep.get("seed", 0))
                by_seed.setdefault((etier, eseed), []).append(ep)

        truth_cache: dict[tuple[str, int], tuple[str | None, str | None]] = {
            k: _resolve_world_truth(k[0], k[1], v) for k, v in by_seed.items()
        }

        for ep in ep_list:
            if not isinstance(ep, dict):
                continue
            tier = str(ep.get("tier") or default_tier)
            seed = int(ep.get("seed", 0))
            s_entry = seed_specs.get(str(seed)) if isinstance(seed_specs.get(str(seed)), dict) else {}
            company = str(s_entry.get("company") or "Company")
            bspec = s_entry.get("bias_spec") if isinstance(s_entry.get("bias_spec"), dict) else {}
            rel_tf = str(ep.get("transcript_file") or "")
            tf_path = adir / rel_tf
            if not tf_path.is_file():
                raise FileNotFoundError(f"missing transcript file {tf_path}")
            steps = parse_transcript_steps(tf_path)
            true_mole, framed_decoy = truth_cache[(tier, seed)]
            metrics = compute_episode_forensics(
                ep,
                steps,
                tier=tier,
                company=company,
                bias_spec=bspec,
                true_mole=true_mole,
                framed_decoy=framed_decoy,
                ablation_dir=adir,
            )
            raw_items.append({"metrics": metrics, "steps": steps})

    tier_rank = {t: i for i, t in enumerate(TIER_ORDER)}
    pol_rank = {p: i for i, p in enumerate(POLICY_ORDER)}
    w_rank = {w: i for i, w in enumerate(WORLD_ORDER)}

    raw_items.sort(
        key=lambda x: (
            tier_rank.get(x["metrics"]["tier"], 99),
            int(x["metrics"]["seed"]),
            pol_rank.get(x["metrics"]["policy"], 99),
            w_rank.get(x["metrics"]["world_arm"], 99),
        )
    )

    used_ids: set[str] = set()
    items: list[dict[str, Any]] = []
    for entry in raw_items:
        m = entry["metrics"]
        base_id = f"{m['tier']}:s{m['seed']}:{m['policy']}:{m['world_arm']}"
        eid = base_id
        dup = 2
        while eid in used_ids:
            eid = f"{base_id}:dup{dup}"
            dup += 1
        used_ids.add(eid)
        m["episode_id"] = eid
        items.append({"episode_id": eid, "metrics": m, "steps": entry["steps"]})

    metrics_list = [it["metrics"] for it in items]
    policies_present = [p for p in POLICY_ORDER if any(m["policy"] == p for m in metrics_list)]
    for m in metrics_list:
        if m["policy"] not in policies_present:
            policies_present.append(m["policy"])

    tiers_present = [t for t in TIER_ORDER if any(m["tier"] == t for m in metrics_list)]
    for m in metrics_list:
        if m["tier"] not in tiers_present:
            tiers_present.append(m["tier"])

    overall_arms: dict[str, dict[str, Any]] = {}
    paired_policy_deltas: dict[str, dict[str, Any]] = {}
    for pol in policies_present:
        for w_arm in WORLD_ORDER:
            grp = [m for m in metrics_list if m["policy"] == pol and m["world_arm"] == w_arm]
            overall_arms[f"{pol}_{w_arm}"] = _summarize_episode_group(
                grp, policy=pol, world_arm=w_arm, tier="all"
            )
        paired_policy_deltas[pol] = _compute_paired_delta(
            overall_arms[f"{pol}_biased"], overall_arms[f"{pol}_template"]
        )

    tier_arms: dict[str, dict[str, Any]] = {}
    tier_paired_deltas: dict[str, dict[str, Any]] = {}
    for t in tiers_present:
        t_map: dict[str, dict[str, Any]] = {}
        d_map: dict[str, dict[str, Any]] = {}
        for pol in policies_present:
            for w_arm in WORLD_ORDER:
                grp = [
                    m
                    for m in metrics_list
                    if m["tier"] == t and m["policy"] == pol and m["world_arm"] == w_arm
                ]
                t_map[f"{pol}_{w_arm}"] = _summarize_episode_group(
                    grp, policy=pol, world_arm=w_arm, tier=t
                )
            d_map[pol] = _compute_paired_delta(t_map[f"{pol}_biased"], t_map[f"{pol}_template"])
        tier_arms[t] = t_map
        tier_paired_deltas[t] = d_map

    pair_buckets: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
    for m in metrics_list:
        key = (m["tier"], int(m["seed"]), m["policy"])
        pair_buckets.setdefault(key, {})[m["world_arm"]] = m

    paired_seed_comparisons: list[dict[str, Any]] = []
    for (t, s, pol), arms_map in pair_buckets.items():
        b = arms_map.get("biased")
        tp = arms_map.get("template")
        if b is None or tp is None:
            continue
        b["paired_counterpart_id"] = tp["episode_id"]
        tp["paired_counterpart_id"] = b["episode_id"]
        paired_seed_comparisons.append(
            {
                "pair_id": f"{t}:s{s}:{pol}",
                "tier": t,
                "seed": s,
                "company": b["company"],
                "policy": pol,
                "true_mole": b["true_mole"],
                "framed_decoy": b["framed_decoy"],
                "rumor_target": b["rumor_target"],
                "biased_episode_id": b["episode_id"],
                "template_episode_id": tp["episode_id"],
                "score_biased": b["score"],
                "score_template": tp["score"],
                "score_delta": round(float(b["score"]) - float(tp["score"]), 6),
                "correct_biased": b["correct"],
                "correct_template": tp["correct"],
                "final_day_biased": b["final_day"],
                "final_day_template": tp["final_day"],
                "final_day_delta": int(b["final_day"]) - int(tp["final_day"]),
                "steps_biased": b["total_steps"],
                "steps_template": tp["total_steps"],
                "steps_delta": int(b["total_steps"]) - int(tp["total_steps"]),
                "rumor_interviews_biased": b["rumor_target_interviews"],
                "rumor_interviews_template": tp["rumor_target_interviews"],
                "rumor_action_share_biased": b["rumor_target_action_share"],
                "rumor_action_share_template": tp["rumor_target_action_share"],
                "rumor_action_share_delta": round(
                    float(b["rumor_target_action_share"]) - float(tp["rumor_target_action_share"]), 6
                ),
                "message_calls_biased": b["message_calls_total"],
                "message_calls_template": tp["message_calls_total"],
                "message_budget_share_biased": b["message_budget_share"],
                "message_budget_share_template": tp["message_budget_share"],
                "message_budget_share_delta": round(
                    float(b["message_budget_share"]) - float(tp["message_budget_share"]), 6
                ),
                "canaries_biased": b["canaries_planted"],
                "canaries_template": tp["canaries_planted"],
                "read_rumor_message_biased": b["read_rumor_message"],
                "accused_biased": b["accused"],
                "accused_template": tp["accused"],
                "target_role_biased": b["accused_target_role"],
                "target_role_template": tp["accused_target_role"],
            }
        )

    deterministic_summary = {
        "n_episodes": len(items),
        "n_pairs": len(paired_seed_comparisons),
        "tiers": tiers_present,
        "policies": policies_present,
        "overall_arms": overall_arms,
        "tier_arms": tier_arms,
        "paired_policy_deltas": paired_policy_deltas,
        "tier_paired_policy_deltas": tier_paired_deltas,
        "paired_seed_comparisons": paired_seed_comparisons,
        "episode_metrics": metrics_list,
    }
    return items, deterministic_summary


def pack_ablation_episodes(
    items: list[dict[str, Any]],
    max_steps_per_episode: int = 220,
) -> tuple[str, dict[str, str], dict[str, list[str]]]:
    blocks: dict[str, str] = {}
    step_lines_by_ep: dict[str, list[str]] = {}

    for item in items:
        ep_id = item["episode_id"]
        m = item["metrics"]
        raw_steps = list(item.get("steps") or [])
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

        grudge_s = ",".join(m["grudge_pair"]) or "none"
        leaks_s = ",".join(m["canary_leaks_surfaced"]) or "none"
        bmsgs_s = ",".join(m["bias_chatter_messages_read"]) or "none"
        counterpart = m.get("paired_counterpart_id") or "none"

        header_lines = [
            f"=== EPISODE {ep_id} ===",
            (
                f"META tier={m['tier']} seed={m['seed']} company='{_clean_inline(m['company'], 32)}' "
                f"policy={m['policy']} world={m['world_arm']} paired_with={counterpart} "
                f"score={m['score']:+.3f} correct={m['correct']} final_day={m['final_day']} steps={m['total_steps']}"
            ),
            (
                f"TARGETS true_mole={m['true_mole']} framed_decoy={m['framed_decoy']} "
                f"rumor_target={m['rumor_target']} grudge_pair={grudge_s} manager_id={m['manager_id']} "
                f"accused={m['accused']} accused_role={m['accused_target_role']}"
            ),
            (
                f"METRICS interviews={m['interview_calls']} restrict={m['restrict_calls']} "
                f"rumor_interviews={m['rumor_target_interviews']} rumor_restrictions={m['rumor_target_restrictions']} "
                f"rumor_action_share={m['rumor_target_action_share']:.4f} "
                f"msg_searches={m['search_messages_calls']}(err={m['search_messages_err_calls']}) "
                f"msg_reads={m['read_message_calls']}(bias_ids={bmsgs_s}) "
                f"msg_budget_share={m['message_budget_share']:.4f} "
                f"canaries={m['canaries_planted']} canary_confirmed={m['canary_confirmed_mole']} leaks=[{leaks_s}]"
            ),
        ]
        if m["thought_highlights"]:
            th_parts = [
                f"{th['step']}:'{_clean_inline(th['excerpt'], 72)}'"
                for th in m["thought_highlights"][:4]
            ]
            header_lines.append("THOUGHT_EXCERPTS " + " | ".join(th_parts))

        blocks[ep_id] = "\n".join(header_lines + step_lines)

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
    if not raw_q.startswith("[S"):
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
    step_lines = [ln for ln in block.splitlines() if ln.startswith("[S")]
    matched_line = next((ln for ln in step_lines if ln == raw_q), None)
    if matched_line is None:
        return {
            "episode_id": ep_key,
            "quote": raw_q,
            "verified": False,
            "matched_line": None,
            "reason": "not_exact_full_step_line",
        }
    return {
        "episode_id": ep_key,
        "quote": raw_q,
        "verified": True,
        "matched_line": matched_line,
        "reason": "exact_verbatim_match",
    }


def verify_forensics_payload(
    payload: dict[str, Any],
    blocks: dict[str, str],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    clusters_raw = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
    ep_diag_raw = payload.get("episode_diagnoses") if isinstance(payload.get("episode_diagnoses"), list) else []

    by_id = {it["episode_id"]: it["metrics"] for it in items}
    verified_clusters: list[dict[str, Any]] = []
    cluster_total = 0
    cluster_ok = 0

    for c_idx, c in enumerate(clusters_raw):
        if not isinstance(c, dict):
            continue
        mode_id = sanitize_text(c.get("mode_id", MODE_ENUM[0]))
        polarity = sanitize_text(c.get("polarity", "mixed_tradeoff"))
        title = sanitize_text(c.get("title", mode_id))
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
        mean_sc = round(sum(float(by_id[eid]["score"]) for eid in ep_ids) / len(ep_ids), 6) if ep_ids else 0.0
        verified_clusters.append(
            {
                "mode_id": mode_id,
                "polarity": polarity,
                "title": title,
                "episode_ids": ep_ids,
                "episode_count": len(ep_ids),
                "mean_score": mean_sc,
                "mechanism": sanitize_text(c.get("mechanism", "")),
                "decision_impact": sanitize_text(c.get("decision_impact", "")),
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
        if eid in seen_diag_ids:
            continue
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
                "paired_counterpart_id": rec.get("paired_counterpart_id"),
                "tier": rec.get("tier"),
                "seed": rec.get("seed"),
                "policy": rec.get("policy"),
                "world_arm": rec.get("world_arm"),
                "score": rec.get("score"),
                "correct": rec.get("correct"),
                "final_day": rec.get("final_day"),
                "total_steps": rec.get("total_steps"),
                "accused": rec.get("accused"),
                "true_mole": rec.get("true_mole"),
                "framed_decoy": rec.get("framed_decoy"),
                "rumor_target": rec.get("rumor_target"),
                "accused_target_role": rec.get("accused_target_role"),
                "rumor_target_interviews": rec.get("rumor_target_interviews"),
                "rumor_target_action_share": rec.get("rumor_target_action_share"),
                "message_calls_total": rec.get("message_calls_total"),
                "message_budget_share": rec.get("message_budget_share"),
                "canaries_planted": rec.get("canaries_planted"),
                "read_rumor_message": rec.get("read_rumor_message"),
                "primary_mode": sanitize_text(d.get("primary_mode", "")),
                "chatter_effect": sanitize_text(d.get("chatter_effect", "")),
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


def _select_stub_quote_for_episode(m: dict[str, Any], lines: list[str]) -> str:
    if not lines:
        return "[S000] d1 status() -> ok"
    rt = m.get("rumor_target") or ""
    if m.get("policy") == "carbon" and m.get("world_arm") == "biased":
        for ln in lines:
            if "read_message(id=bc1-0)" in ln:
                return ln
        for ln in lines:
            if f"interview(employee={rt}," in ln:
                return ln
    if m.get("policy") == "carbon" and m.get("world_arm") == "template":
        for ln in lines:
            if "check_leak_feed()" in ln and "c" in ln:
                return ln
    for ln in reversed(lines):
        if " accuse(" in ln:
            return ln
    return lines[-1]


def _heuristic_mode_and_effect(
    m: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    pol = m.get("policy")
    world_arm = m.get("world_arm")
    counterpart = by_id.get(str(m.get("paired_counterpart_id") or "")) or {}
    if pol == "solver":
        return "solver_bayesian_chatter_invariance", "chatter_invariant_bayesian"
    if pol == "obvious_heuristic":
        return "heuristic_decoy_and_rumor_collapse", "heuristic_false_accusation_collapse"
    if world_arm == "biased":
        c_score = float(counterpart.get("score", m["score"]))
        if m.get("rumor_target_interviews", 0) >= 2 or float(m["score"]) < c_score - 0.05:
            return "rumor_target_verification_delay", "rumor_distraction_score_drag"
        if float(m["score"]) > c_score + 0.03:
            return "canary_confirmation_overrides_chatter", "faster_canary_resolution_on_biased"
        return "canary_confirmation_overrides_chatter", "resilient_override_after_rumor_check"
    if int(m.get("interview_calls", 0)) >= 50 or int(m.get("total_steps", 0)) >= 110:
        return "exhaustive_interview_sweep_drag", "neutral_template_baseline"
    if int(m.get("search_messages_err_calls", 0)) > 0:
        return "message_search_budget_sink", "neutral_template_baseline"
    return "canary_confirmation_overrides_chatter", "neutral_template_baseline"


def build_stub_forensics_payload(
    items: list[dict[str, Any]],
    step_lines_by_ep: dict[str, list[str]],
) -> dict[str, Any]:
    if not items:
        return {
            "executive_summary": "No paired chatter-bias episodes were provided.",
            "clusters": [],
            "episode_diagnoses": [],
        }

    by_id = {it["episode_id"]: it["metrics"] for it in items}
    grouped: dict[str, list[dict[str, Any]]] = {}
    ep_diagnoses: list[dict[str, Any]] = []

    for it in items:
        eid = it["episode_id"]
        m = it["metrics"]
        mode_id, effect = _heuristic_mode_and_effect(m, by_id)
        grouped.setdefault(mode_id, []).append(it)
        qline = _select_stub_quote_for_episode(m, step_lines_by_ep.get(eid) or [])
        ep_diagnoses.append(
            {
                "episode_id": eid,
                "primary_mode": mode_id,
                "chatter_effect": effect,
                "rationale": (
                    f"Policy {m['policy']} on {m['world_arm']} ({m['tier']} seed {m['seed']}) finished on day "
                    f"{m['final_day']} with score {m['score']:+.3f}, accusing {m['accused']} ({m['accused_target_role']}), "
                    f"rumor_action_share={m['rumor_target_action_share']:.3f}, msg_budget_share={m['message_budget_share']:.3f}."
                ),
                "trigger_quote": {"episode_id": eid, "quote": qline},
            }
        )

    meta_by_mode: dict[str, tuple[str, str, str, str]] = {
        "rumor_target_verification_delay": (
            "failure_mode",
            "Unverified Rumor Verification Delay and Action Diversion",
            "Injected bc1-0 rumor messages trigger direct interviews of innocent rumor_target suspects.",
            "Treat single-source gossip as zero-likelihood prior noise until corroborated by access or canary evidence.",
        ),
        "canary_confirmation_overrides_chatter": (
            "resilience_mode",
            "Fingerprinted Canary Confirmation Overriding Workplace Bias",
            "Singleton canary variants uniquely identify the true mole and override misleading social chatter.",
            "Prioritize early high-entropy canary splits before spending actions on message or interview sweeps.",
        ),
        "message_search_budget_sink": (
            "failure_mode",
            "Broad Vowel and Whitespace Message-Search Budget Sink",
            "Invalid whitespace queries and single-vowel searches burn daily action budget on low-signal chatter.",
            "Validate non-empty lexical queries and cap message-search spend at 1 action per day.",
        ),
        "exhaustive_interview_sweep_drag": (
            "failure_mode",
            "Exhaustive Serial Interview Sweep Value Bleed",
            "Dozens of serial employee interviews delay canary narrowing and bleed company value V.",
            "Replace broad roster interviews with binary/multi-way canary partitioning over log-consistent suspects.",
        ),
        "heuristic_decoy_and_rumor_collapse": (
            "failure_mode",
            "Surface Heuristic Collapse onto Framed Decoys and Rumor Targets",
            "Non-Bayesian heuristic ignores canary disconfirmation and accuses framed decoys or rumor targets.",
            "Require posterior likelihood gating over leaked document recipient sets before accusing.",
        ),
        "solver_bayesian_chatter_invariance": (
            "resilience_mode",
            "Exact Bayesian Solver Invariance to Injected Workplace Chatter",
            "SolverPolicy isolates the mole via document-recipient posteriors and optimal canary splits with zero interviews.",
            "Use solver action-value gating as an upper-bound reference for chatter-resilient investigation.",
        ),
    }

    clusters: list[dict[str, Any]] = []
    for mode_id, members in grouped.items():
        polarity, title, mech, mit = meta_by_mode.get(
            mode_id,
            ("mixed_tradeoff", mode_id, "Observed across paired ablation runs.", "Gate actions by expected information gain."),
        )
        quotes = [
            {
                "episode_id": m["episode_id"],
                "quote": _select_stub_quote_for_episode(m["metrics"], step_lines_by_ep[m["episode_id"]]),
            }
            for m in members[:3]
        ]
        clusters.append(
            {
                "mode_id": mode_id,
                "polarity": polarity,
                "title": title,
                "episode_ids": [m["episode_id"] for m in members],
                "mechanism": mech,
                "decision_impact": f"Observed across {len(members)} paired ablation episodes.",
                "mitigation": mit,
                "quotes": quotes,
            }
        )

    return {
        "executive_summary": (
            f"Diagnosed {len(items)} paired biased-chatter vs neutral-template episodes across "
            f"{len(clusters)} social-chatter failure and resilience clusters."
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
    cached = int(u.get("cached_in", 0) or _um_int("cached_content_token_count"))
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


def build_user_prompt(
    det_summary: dict[str, Any],
    items: list[dict[str, Any]],
    corpus_text: str,
) -> str:
    ep_ids = [it["episode_id"] for it in items]
    arms = det_summary["overall_arms"]
    deltas = det_summary["paired_policy_deltas"]

    summary_lines = ["DETERMINISTIC PAIRED ABLATION SUMMARY (POOLED ACROSS TIERS & SEEDS):"]
    for key, arm in arms.items():
        summary_lines.append(
            f"- arm={key} n={arm['n']} score_mean={arm['score_mean']:+.3f} acc={arm['accuracy']:.2f} "
            f"mean_day={arm['mean_final_day']:.2f} mean_steps={arm['mean_steps']:.1f} "
            f"rumor_distract_rate={arm['rumor_target_distraction_rate']:.2f} "
            f"rumor_action_share={arm['rumor_target_action_share_mean']:.4f} "
            f"msg_calls={arm['message_calls_total']} msg_budget_share={arm['message_budget_share_mean']:.4f} "
            f"mean_canaries={arm['mean_canaries_planted']:.2f} "
            f"decoy_accused_rate={arm['framed_decoy_accused_rate']:.2f} "
            f"rumor_accused_rate={arm['rumor_target_accused_rate']:.2f}"
        )
    summary_lines.append("PAIRED DELTAS (BIASED MINUS TEMPLATE):")
    for pol, d in deltas.items():
        summary_lines.append(
            f"- policy={pol} score_delta={d['score_delta']:+.3f} acc_delta={d['accuracy_delta']:+.2f} "
            f"day_delta={d['final_day_delta']:+.2f} steps_delta={d['steps_delta']:+.1f} "
            f"rumor_distract_delta={d['rumor_target_distraction_rate_delta']:+.2f} "
            f"rumor_share_delta={d['rumor_target_action_share_delta']:+.4f} "
            f"msg_calls_delta={d['message_calls_delta']:+d} "
            f"read_rumor_msg_rate_biased={d['read_rumor_message_rate_biased']:.2f}"
        )

    summary_lines.extend(
        [
            f"REQUIRED_EPISODE_IDS ({len(ep_ids)}): " + ", ".join(ep_ids),
            "",
            "Analyze all paired episodes below. Every quote MUST copy an entire [S...] step line character-for-character without altering a single character:",
            "",
            corpus_text,
        ]
    )
    return "\n".join(summary_lines)


def build_repair_prompt(verified: dict[str, Any], blocks: dict[str, str]) -> str:
    bad = [c for c in verified["quote_verification"]["checks"] if not c["verified"]]
    missing = verified["missing_episodes"]
    lines = [
        "Your previous JSON output failed exact Python verification.",
        "Fix ALL issues below and return the complete corrected JSON matching the schema:",
    ]
    if missing:
        lines.append("Missing episode_diagnoses for episode_ids: " + ", ".join(missing))
    for b in bad[:30]:
        eid = b["episode_id"]
        q_sub = b["quote"]
        lines.append(
            f"- Failed at {b['source']}: episode_id={eid!r}, reason={b['reason']}, submitted_quote={q_sub!r}"
        )
        if eid in blocks:
            step_lines = [ln for ln in blocks[eid].splitlines() if ln.startswith("[S")]
            m_step = STEP_PREFIX_RE.match(q_sub)
            exact_cand = None
            if m_step:
                pref = f"[{m_step.group(1)}] "
                exact_cand = next((ln for ln in step_lines if ln.startswith(pref)), None)
            if exact_cand:
                lines.append(f"  Exact verbatim line for that step in {eid}: {exact_cand}")
            else:
                sample_steps = step_lines[-4:]
                lines.append(f"  Valid verbatim lines from {eid}: " + " | ".join(sample_steps))
    lines.append(
        "Remember: every quote MUST be an exact character-for-character full [S...] line from that exact episode_id block, with zero em/en dashes."
    )
    return "\n".join(lines)


def render_summary_md(
    meta: dict[str, Any],
    forensics_doc: dict[str, Any],
) -> str:
    det = forensics_doc["deterministic_summary"]
    qv = forensics_doc["quote_verification"]
    u = meta["usage"]
    arms = det["overall_arms"]
    deltas = det["paired_policy_deltas"]
    tier_deltas = det["tier_paired_policy_deltas"]

    lines = [
        f"{MD_H1} Role 4 ({meta['role']}) - Biased Workplace Chatter vs Neutral Template Decision Forensics ({meta['model_id']})",
        "",
        f"{MD_H2} Provenance & Verification",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}` (`thinking_level={meta['thinking_level']}`)",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Command:** `{meta['command']}`",
        f"- **Paired ablation episodes analyzed:** `{meta['n_episodes']}` (`{meta['n_pairs']}` paired `(tier, seed, policy)` comparisons across `{', '.join(det['tiers'])}`)",
        f"- **Key metric:** `{meta['key_metric']}`",
        f"- **Verbatim quote verification:** `{qv['verified_quotes']}/{qv['total_quotes']}` (`{meta['verified_quotes_pct']:.1f}%` exact character-for-character `[S...]` step-line match in Python)",
        f"- **Gemini usage:** `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd=${u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}s`",
        "- **Artifacts:** `meta.json`, `forensics.json`, `summary.md`",
        "",
        f"{MD_H2} Pooled Paired Investigator Arm Summary (`Biased` vs `Template`)",
        "",
        "| Policy | World Arm | N | Mean Score | Accuracy | Mean Day | Mean Steps | Rumor Distract Rate | Rumor Action Share | Msg Calls (Err) | Msg Budget Share | Mean Canaries | Decoy Accused | Rumor Accused |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for pol in det["policies"]:
        for w_arm in WORLD_ORDER:
            arm = arms[f"{pol}_{w_arm}"]
            lines.append(
                f"| `{pol}` | `{w_arm}` | {arm['n']} | {arm['score_mean']:+.3f} | {arm['accuracy']:.2f} "
                f"| {arm['mean_final_day']:.1f} | {arm['mean_steps']:.1f} "
                f"| {arm['rumor_target_distraction_rate']:.2f} | {arm['rumor_target_action_share_mean']:.4f} "
                f"| {arm['message_calls_total']} ({arm['search_messages_err_total']}) "
                f"| {arm['message_budget_share_mean']:.4f} | {arm['mean_canaries_planted']:.1f} "
                f"| {arm['framed_decoy_accused_rate']:.2f} | {arm['rumor_target_accused_rate']:.2f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} Paired Deltas (`Biased` minus `Template`)",
            "",
            "| Scope | Policy | Score Delta | Accuracy Delta | Day Delta | Steps Delta | Rumor Distract Delta | Rumor Share Delta | Msg Calls Delta | Msg Budget Share Delta | Read `bc1-0` Rate (Biased) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for pol in det["policies"]:
        d = deltas[pol]
        lines.append(
            f"| `all` | `{pol}` | {d['score_delta']:+.3f} | {d['accuracy_delta']:+.2f} "
            f"| {d['final_day_delta']:+.2f} | {d['steps_delta']:+.1f} "
            f"| {d['rumor_target_distraction_rate_delta']:+.2f} | {d['rumor_target_action_share_delta']:+.4f} "
            f"| {d['message_calls_delta']:+d} | {d['message_budget_share_delta']:+.4f} "
            f"| {d['read_rumor_message_rate_biased']:.2f} |"
        )
    for t in det["tiers"]:
        for pol in det["policies"]:
            d = tier_deltas[t][pol]
            lines.append(
                f"| `{t}` | `{pol}` | {d['score_delta']:+.3f} | {d['accuracy_delta']:+.2f} "
                f"| {d['final_day_delta']:+.2f} | {d['steps_delta']:+.1f} "
                f"| {d['rumor_target_distraction_rate_delta']:+.2f} | {d['rumor_target_action_share_delta']:+.4f} "
                f"| {d['message_calls_delta']:+d} | {d['message_budget_share_delta']:+.4f} "
                f"| {d['read_rumor_message_rate_biased']:.2f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} Executive Forensic Synthesis (`{meta['model_id']}`)",
            "",
            forensics_doc["executive_summary"],
            "",
            f"{MD_H2} Social-Chatter Failure & Resilience Mode Taxonomy",
            "",
        ]
    )

    for idx, cl in enumerate(forensics_doc["clusters"], start=1):
        lines.extend(
            [
                f"{MD_H3} {idx}. {cl['title']} (`{cl['mode_id']}`, `{cl['polarity']}`)",
                f"- **Episodes affected:** `{cl['episode_count']}` (`mean_score = {cl['mean_score']:+.3f}`) - {', '.join(f'`{e}`' for e in cl['episode_ids'])}",
                f"- **Causal mechanism:** {cl['mechanism']}",
                f"- **Decision impact:** {cl['decision_impact']}",
                f"- **Mitigation:** {cl['mitigation']}",
                "- **Verified verbatim quotes:**",
            ]
        )
        for q in cl["quotes"]:
            badge = "VERIFIED" if q["verified"] else "UNVERIFIED"
            lines.append(f"  - [{badge}] `{q['episode_id']}`: `{q['quote']}`")
        lines.append("")

    lines.extend(
        [
            f"{MD_H2} Paired Seed-by-Seed Comparison (`Biased` vs `Template`)",
            "",
            "| Pair ID | Mole / Decoy / Rumor | Score (B vs T, Delta) | Day (B vs T) | Steps (B vs T) | Rumor Int (B vs T) | Msg Calls (B vs T) | Read `bc1-0` | Accused (B / T) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for pr in det["paired_seed_comparisons"]:
        lines.append(
            f"| `{pr['pair_id']}` | `{pr['true_mole']}` / `{pr['framed_decoy']}` / `{pr['rumor_target']}` "
            f"| `{pr['score_biased']:+.3f}` vs `{pr['score_template']:+.3f}` (`{pr['score_delta']:+.3f}`) "
            f"| {pr['final_day_biased']} vs {pr['final_day_template']} "
            f"| {pr['steps_biased']} vs {pr['steps_template']} "
            f"| {pr['rumor_interviews_biased']} vs {pr['rumor_interviews_template']} "
            f"| {pr['message_calls_biased']} vs {pr['message_calls_template']} "
            f"| `{pr['read_rumor_message_biased']}` "
            f"| `{pr['accused_biased']}` / `{pr['accused_template']}` |"
        )

    lines.extend(
        [
            "",
            f"{MD_H2} Per-Episode Decision Forensics & Verbatim Trigger Quotes",
            "",
            "| Episode ID | Score | Day | Steps | Accused (`Role`) | Rumor Share | Msg Share | Canaries | Mode | Chatter Effect | Verbatim Trigger Quote |",
            "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for d in forensics_doc["episode_diagnoses"]:
        tq = d["trigger_quote"]["quote"]
        sc_s = f"{float(d['score']):+.3f}" if d.get("score") is not None else "NA"
        rs_s = f"{float(d['rumor_target_action_share']):.3f}" if d.get("rumor_target_action_share") is not None else "0.000"
        ms_s = f"{float(d['message_budget_share']):.3f}" if d.get("message_budget_share") is not None else "0.000"
        lines.append(
            f"| `{d['episode_id']}` | {sc_s} | {d.get('final_day')} | {d.get('total_steps')} "
            f"| `{d.get('accused')}` (`{d.get('accused_target_role')}`) | {rs_s} | {ms_s} "
            f"| {d.get('canaries_planted')} | `{d['primary_mode']}` | `{d['chatter_effect']}` | `{tq}` |"
        )

    lines.append("")
    return sanitize_text("\n".join(lines))


def _format_key_metric(det_summary: dict[str, Any], verified_pct: float) -> str:
    arms = det_summary["overall_arms"]
    cb = arms.get("carbon_biased")
    ct = arms.get("carbon_template")
    n_eps = det_summary["n_episodes"]
    n_pairs = det_summary["n_pairs"]
    if cb and ct and cb["n"] > 0 and ct["n"] > 0:
        return sanitize_text(
            f"{n_eps} paired episodes ({n_pairs} pairs), quotes {verified_pct:.1f}% verified, "
            f"carbon acc {cb['accuracy']:.0%} (biased {cb['score_mean']:+.3f} vs template {ct['score_mean']:+.3f}), "
            f"rumor distraction {cb['rumor_target_distraction_rate']:.0%} vs {ct['rumor_target_distraction_rate']:.0%}"
        )
    return sanitize_text(f"{n_eps} paired episodes ({n_pairs} pairs), quotes {verified_pct:.1f}% verified")


def run_chatter_bias_forensics(
    *,
    ablation_dirs: Sequence[str | Path] = DEFAULT_ABLATION_DIRS,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    model_id: str = DEFAULT_MODEL,
    thinking_level: str = DEFAULT_THINKING_LEVEL,
    stub: bool = False,
    max_repair_retries: int = 2,
    client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    items, det_summary = collect_paired_ablation_corpus(ablation_dirs=ablation_dirs)
    corpus_text, blocks, step_lines_by_ep = pack_ablation_episodes(items)

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    commit = current_git_commit()
    effective_model = "stub" if stub else model_id
    effective_thinking = str(thinking_level or DEFAULT_THINKING_LEVEL).lower()
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or (
        f"{FEATURE}:{effective_model}:{ts.strftime('%Y%m%dT%H%M%SZ')}"
    )

    if client is None:
        if stub:
            script_name = f"chatter_bias_forensics_stub_{int(time.time() * 1000)}_{os.getpid()}"
            stub_payload = build_stub_forensics_payload(items, step_lines_by_ep)
            register_script(script_name, [{"json": stub_payload}])
            client = lab_client(f"stub:{script_name}", feature=FEATURE, run_id=run_id)
        else:
            spec = model_id if ":" in model_id else f"gemini:{model_id}"
            client = lab_client(
                spec,
                feature=FEATURE,
                run_id=run_id,
                thinking_level=effective_thinking,
            )

    usage_totals = {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "cost_usd": 0.0,
        "latency_s": 0.0,
    }

    user_prompt = build_user_prompt(det_summary, items, corpus_text)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    t0 = time.time()
    resp = client.chat(messages, temperature=0.0, response_schema=CHATTER_FORENSICS_SCHEMA)
    usage_totals = _merge_usage(usage_totals, _extract_call_usage(resp, time.time() - t0))
    raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
    try:
        parsed = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        parsed = {}
    verified = verify_forensics_payload(parsed, blocks=blocks, items=items)

    attempt = 0
    while attempt < max_repair_retries and (
        verified["quote_verification"]["unverified_quotes"] > 0
        or len(verified["missing_episodes"]) > 0
        or (len(items) > 0 and verified["quote_verification"]["total_quotes"] == 0)
        or len(verified["clusters"]) == 0
    ):
        attempt += 1
        messages.append({"role": "assistant", "content": raw_text or "{}"})
        messages.append({"role": "user", "content": build_repair_prompt(verified, blocks)})
        t1 = time.time()
        resp = client.chat(messages, temperature=0.0, response_schema=CHATTER_FORENSICS_SCHEMA)
        usage_totals = _merge_usage(usage_totals, _extract_call_usage(resp, time.time() - t1))
        raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
        try:
            parsed = json.loads(raw_text or "{}")
        except json.JSONDecodeError:
            parsed = {}
        verified = verify_forensics_payload(parsed, blocks=blocks, items=items)

    qv = verified["quote_verification"]
    default_cmd = "PYTHONPATH=. " + " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    cmd_clean = sanitize_text(command_str or default_cmd)
    key_metric = _format_key_metric(det_summary, qv["verified_quotes_pct"])

    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "thinking_level": effective_thinking,
        "commit": commit,
        "git_sha": commit,
        "timestamp": ts_iso,
        "command": cmd_clean,
        "ledger_run_id": run_id,
        "ablation_dirs": [Path(p).as_posix() for p in ablation_dirs],
        "n_episodes": len(items),
        "n_episodes_packed": len(items),
        "n_pairs": det_summary["n_pairs"],
        "total_quotes": qv["total_quotes"],
        "verified_quotes": qv["verified_quotes"],
        "verified_quotes_pct": qv["verified_quotes_pct"],
        "key_metric": key_metric,
        "fake_env": False,
        "smoke": False,
        "stub": bool(stub),
        "usage": usage_totals,
    }
    if stub:
        meta["provider"] = "stub"

    forensics_doc: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "thinking_level": effective_thinking,
        "commit": commit,
        "timestamp": ts_iso,
        "ablation_dirs": [Path(p).as_posix() for p in ablation_dirs],
        "n_episodes": len(items),
        "n_episodes_packed": len(items),
        "n_pairs": det_summary["n_pairs"],
        "deterministic_summary": det_summary,
        "quote_verification": qv,
        "executive_summary": verified["executive_summary"],
        "clusters": verified["clusters"],
        "episode_diagnoses": verified["episode_diagnoses"],
        "usage": usage_totals,
    }

    (out_path / "meta.json").write_text(
        sanitize_text(json.dumps(meta, indent=2) + "\n"),
        encoding="utf-8",
    )
    (out_path / "forensics.json").write_text(
        sanitize_text(json.dumps(forensics_doc, indent=2) + "\n"),
        encoding="utf-8",
    )
    (out_path / "summary.md").write_text(
        render_summary_md(meta, forensics_doc),
        encoding="utf-8",
    )
    return {"meta": meta, "forensics": forensics_doc, "blocks": blocks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run biased workplace chatter vs neutral template investigator decision forensics."
    )
    ap.add_argument(
        "--ablation-dirs",
        nargs="+",
        type=Path,
        default=list(DEFAULT_ABLATION_DIRS),
    )
    ap.add_argument("--out", "--out-dir", dest="out_dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thinking-level", default=DEFAULT_THINKING_LEVEL)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--max-repair-retries", type=int, default=2)
    args = ap.parse_args(argv)

    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd_parts = [
        "PYTHONPATH=.",
        shlex.quote(sys.executable),
        "scripts/run_chatter_bias_forensics.py",
    ] + [shlex.quote(x) for x in raw_argv]
    cmd_str = " ".join(cmd_parts)

    res = run_chatter_bias_forensics(
        ablation_dirs=args.ablation_dirs,
        out_dir=args.out_dir,
        model_id=args.model,
        thinking_level=args.thinking_level,
        stub=args.stub,
        max_repair_retries=args.max_repair_retries,
        command_str=cmd_str,
    )
    m = res["meta"]
    u = m["usage"]
    print(
        f"chatter_bias_forensics: episodes={m['n_episodes']} pairs={m['n_pairs']} "
        f"quotes_verified={m['verified_quotes']}/{m['total_quotes']} ({m['verified_quotes_pct']:.1f}%) "
        f"in={u['in']} out={u['out']} thinking={u['thinking']} cost=${u['cost_usd']:.6f}"
    )
    if not args.stub and (m["verified_quotes_pct"] < 100.0 or m["total_quotes"] < m["n_episodes"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
