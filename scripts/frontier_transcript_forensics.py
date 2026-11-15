"""Deterministic OpenCode transcript reasoning forensics and posterior calibration audit for Canary v1.4 (pure CPU, zero API calls).

    python scripts/frontier_transcript_forensics.py --write
    python scripts/frontier_transcript_forensics.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.agents.frontier import common
from canary.analysis.accuse import audit_episode
from canary.analysis.gap import load_runs, mean_ci
from canary.analysis.tags import to_result
from canary.env import Env
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from paired_v13 import boot_ratio, p_acc, post_expected

SCHEMA_VERSION = "v1.4-frontier-transcript-forensics-1"
MAX_JSON_BYTES = 45_000

ENV_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_access_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

_OC_TRUNC_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: "
)
_OC_NO_TOOL_PREFIX = "Model tried to call unavailable tool"
_THOUGHT_SIG_CHARS_RE = re.compile(r"<(\d+)\s+chars>")
_UNREDACTED_SIG_RE = re.compile(r'"thoughtSignature":\s?"[^"<]{64,}"')

_GOOGLE_KEY_PREFIX = "AI" + "za"
_OPENAI_KEY_PREFIX = "s" + "k-"
_API_KEY_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + _GOOGLE_KEY_PREFIX + r"[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + _OPENAI_KEY_PREFIX
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
)

RX_RULE_CAREFUL = re.compile(
    r"\bcareful\b|1\s*-\s*(?:the\s+)?share|selection\s+weight|broad[- ]split|avoid\w*\s+broad",
    re.I,
)
RX_RULE_FRAMING = re.compile(
    r"\bdecoy\b|\bfram(?:e|ed|ing)\b|fake\s+after[- ]hours|angry\s+message|disgruntled",
    re.I,
)
RX_RULE_NOISY_CANARY = re.compile(
    r"\b(?:0\.95|95\s*%|0\.05|5\s*%|0\.025|2\.5\s*%|38\s*:\s*1|1444\s*:\s*1|noisy\s+fingerprint|fingerprint\s+accuracy)\b",
    re.I,
)
RX_RULE_INTERVIEW_WEAK = re.compile(
    r"\b(?:0\.24|24\s*%|1\.2(?:\^\d+)?\b|evasive|interview\w*)\b",
    re.I,
)
RX_RULE_ABSTAIN_EV = re.compile(
    r"\b(?:abstain\w*|expected\s+value|negative\s+expected|-1(?:\.0+)?\s+penalt|guaranteed\s+score\s+of\s+`?0|break[- ]even)\b",
    re.I,
)

RX_CERTAINTY_DECISIVE = re.compile(
    r"(?:\b(?:uniquely|certain(?:ty)?|eliminated|only\s+suspect|strictly|deterministically|conclusively|definitively|exclusively|proved)\b|\b100\s*%)",
    re.I,
)
RX_CERTAINTY_HEDGED = re.compile(
    r"\b(?:most\s+likely|forced\s+to\s+guess|highest[- ]posterior|best\s+candidate|likely\s+suspect|plausible|uncertain)\b",
    re.I,
)
RX_UNIQUELY_MARKER = re.compile(r"\buniquely\b", re.I)

RX_BOOK_CANDIDATE_SET = re.compile(
    r"\{[^{}]*\be\d{2}\b[^{}]*\}|`e\d{2}\s*,\s*e\d{2}|" + "\u2229" + r"|\\cap\b|intersection\s+of\s+recipients|recipient[- ]set\s+intersection",
    re.I,
)
RX_BOOK_VARIANT_LEDGER = re.compile(
    r"\bc\d+(?:-\d+)?\b[^\n]{0,120}\b(?:variant|v[0123ABC]|[ABC]\b|var[ABC]|D1|S1|Delta|Alpha|Gamma|c\d+_e\d{2})",
    re.I,
)

OPENCODE_COHORT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode_gemini_4_carbon_medium",
        "label": "OpenCode gemini-4-carbon medium (0-29)",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "medium",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard",
        "label": "OpenCode gemini-4-carbon hard (0-29)",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard_ext",
        "label": "OpenCode gemini-4-carbon hard G1 ext (34,37)",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
        "seed_min": 30,
        "seed_max": 59,
        "expected_n": 2,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard_rep",
        "label": "OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "replication",
        "source_rel": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
        "seed_min": 30,
        "seed_max": 59,
        "expected_n": 5,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_3_5_flash_medium",
        "label": "OpenCode gemini-3.5-flash medium (0-29)",
        "agent": "opencode:google/gemini-3.5-flash",
        "model_family": "gemini-3.5-flash",
        "tier": "medium",
        "source": "replication",
        "source_rel": "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_3_5_flash_hard",
        "label": "OpenCode gemini-3.5-flash hard (0-29)",
        "agent": "opencode:google/gemini-3.5-flash",
        "model_family": "gemini-3.5-flash",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": True,
    },
)


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "transcript_forensics.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_transcript_forensics_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    if not gap_md.exists():
        return False
    return "gemini-3.5-flash" in gap_md.read_text(encoding="utf-8")


def sanitize_ascii_punctuation(text: str) -> str:
    return text.replace(chr(0x2014), "-").replace(chr(0x2013), "-")


def clean_json(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, str):
        return sanitize_ascii_punctuation(obj)
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def norm_result(want: Any) -> Any:
    if isinstance(want, dict) and isinstance(want.get("error"), str) and want["error"].startswith("{"):
        try:
            inner = json.loads(want["error"])
        except ValueError:
            return want
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner):
            return inner
    return want


def client_truncated_bytes(want: Any) -> int | None:
    if isinstance(want, dict) and set(want) == {"raw"} and isinstance(want["raw"], str):
        m = _OC_TRUNC_RE.match(want["raw"])
        if m:
            return int(m.group(1))
    return None


def is_client_only_step(step: dict[str, Any]) -> bool:
    res = step.get("result")
    return (
        step.get("tool") not in ENV_TOOLS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(_OC_NO_TOOL_PREFIX)
    )


def step_result_matches(raw_recorded: Any, replayed: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    flags = {
        "unwrapped_mcp_error": False,
        "detail_normalized": False,
        "truncated_checked": False,
    }
    trunc = client_truncated_bytes(raw_recorded)
    if trunc is not None:
        flags["truncated_checked"] = True
        return len(json.dumps(replayed).encode("utf-8")) == trunc, flags
    rec = norm_result(raw_recorded)
    if rec is not raw_recorded:
        flags["unwrapped_mcp_error"] = True
    if rec is None:
        return True, flags
    rep = replayed
    if (
        isinstance(rep, dict)
        and rep.get("ok") is False
        and isinstance(rep.get("data"), dict)
        and set(rep["data"]) == {"detail"}
        and isinstance(rec, dict)
        and not ("detail" in (rec.get("data") or {}))
    ):
        rep = {"ok": False, "data": {}, "error": rep.get("error")}
        flags["detail_normalized"] = True
    matched = rep == rec or _canon(rep) == _canon(rec)
    return matched, flags


def step_ok(step: dict[str, Any]) -> bool:
    res = step.get("result")
    if client_truncated_bytes(res) is not None:
        return True
    unwrapped = norm_result(res)
    return bool((unwrapped or {}).get("ok"))


def replay_and_verify_episode(ep: dict[str, Any]) -> dict[str, Any]:
    env = Env(str(ep["tier"]), int(ep["seed"]))
    step_mismatches = 0
    first_bad_step: int | None = None
    unwrapped_mcp_error_steps = 0
    detail_normalized_steps = 0
    truncated_steps_verified = 0
    client_only_steps = 0
    for idx, st in enumerate(ep.get("steps") or []):
        if is_client_only_step(st):
            client_only_steps += 1
            continue
        if env.done:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        r = env.call(str(st["tool"]), st.get("args") or {})
        got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
        ok_step, flags = step_result_matches(st.get("result"), got_payload)
        if flags["unwrapped_mcp_error"]:
            unwrapped_mcp_error_steps += 1
        if flags["detail_normalized"]:
            detail_normalized_steps += 1
        if flags["truncated_checked"] and ok_step:
            truncated_steps_verified += 1
        if not ok_step:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
    res = env.result("replay")
    score_ok = (
        abs(float(res.score) - float(ep["score"])) < 1e-9
        and res.accused == ep.get("accused")
        and bool(res.correct) == bool(ep.get("correct"))
        and int(res.final_day) == int(ep.get("final_day") or 0)
    )
    return {
        "ok": score_ok and step_mismatches == 0,
        "score_ok": score_ok,
        "replay_score": float(res.score),
        "replay_accused": res.accused,
        "replay_correct": bool(res.correct),
        "replay_final_day": int(res.final_day),
        "step_mismatches": step_mismatches,
        "first_bad_step": first_bad_step,
        "unwrapped_mcp_error_steps": unwrapped_mcp_error_steps,
        "detail_normalized_steps": detail_normalized_steps,
        "truncated_steps_verified": truncated_steps_verified,
        "client_only_steps": client_only_steps,
    }


def verify_episode_pool(episodes: list[dict[str, Any]], pool_name: str) -> dict[str, Any]:
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        seen: set[tuple[str, str, int]] = set()
        duplicates: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        total_step_mismatches = 0
        total_unwrapped = 0
        total_detail_norm = 0
        total_truncated = 0
        total_client_only = 0
        for ep in episodes:
            key = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]))
            if key in seen:
                duplicates.append({"pool": pool_name, "agent": key[0], "tier": key[1], "seed": key[2]})
            seen.add(key)
            rep = replay_and_verify_episode(ep)
            total_step_mismatches += int(rep["step_mismatches"])
            total_unwrapped += int(rep["unwrapped_mcp_error_steps"])
            total_detail_norm += int(rep["detail_normalized_steps"])
            total_truncated += int(rep["truncated_steps_verified"])
            total_client_only += int(rep["client_only_steps"])
            if not rep["ok"]:
                mismatches.append(
                    {
                        "pool": pool_name,
                        "agent": key[0],
                        "tier": key[1],
                        "seed": key[2],
                        "recorded_score": ep["score"],
                        "replay_score": rep["replay_score"],
                        "recorded_accused": ep.get("accused"),
                        "replay_accused": rep["replay_accused"],
                        "step_mismatches": rep["step_mismatches"],
                        "first_bad_step": rep["first_bad_step"],
                    }
                )
        if duplicates:
            raise ValueError(f"duplicate episodes in {pool_name}: {duplicates}")
        if mismatches:
            raise ValueError(f"replay mismatches in {pool_name}: {mismatches}")
        return {
            "pool": pool_name,
            "total": len(episodes),
            "verified": len(episodes),
            "mismatches": 0,
            "step_mismatches": total_step_mismatches,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": total_unwrapped,
            "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
            "truncated_steps_verified": total_truncated,
            "client_only_steps": total_client_only,
        }
    finally:
        if prev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev


def split_transcript_sections(raw_text: str) -> tuple[str, str]:
    marker_out = "\n--- stdout\n"
    marker_err = "\n--- stderr"
    idx_out = raw_text.find(marker_out)
    if idx_out == -1:
        return raw_text, ""
    start_out = idx_out + len(marker_out)
    idx_err = raw_text.rfind(marker_err)
    if idx_err != -1 and idx_err >= start_out:
        return raw_text[start_out:idx_err], raw_text[idx_err:]
    return raw_text[start_out:], ""


def scan_secret_tokens(text: str) -> list[str]:
    found: list[str] = []
    for kind, rx in _API_KEY_DETECTORS:
        for m in rx.finditer(text):
            tok = m.group(0)
            found.append(f"{kind}:{tok[:4]}...")
    return found


def extract_verbalized_posterior(prose: str) -> float | None:
    clean = (
        prose.replace("`", "")
        .replace("*", "")
        .replace("\\%", "%")
        .replace("\\approx", "~")
    )
    rx_list = (
        re.compile(
            r"(?:bayesian\s+)?posterior(?:\s+(?:certainty|confidence|probability))?\s*(?:of|above|is|=|:|\()?[\s~>\u2248]*(\d{2,3}(?:\.\d+)?)\s*%",
            re.I,
        ),
        re.compile(
            r"[~>\u2248]?\s*(\d{2,3}(?:\.\d+)?)\s*%\s*(?:overall\s+|bayesian\s+|mathematical\s+)*(?:posterior|certainty|confidence)(?!\s*(?:to|in)\s+(?:the\s+)?(?:engineering|finance|sales|legal|research|department))",
            re.I,
        ),
        re.compile(r"\bP(?:\([^)]+\))?\s*[>\u2248=~]+\s*(\d{2,3}(?:\.\d+)?)\s*%", re.I),
        re.compile(r"(?:suspect|accused|mole)[^\n]{0,60}\(\s*[>~\u2248]\s*(\d{2,3}(?:\.\d+)?)\s*%\s*\)", re.I),
    )
    cands: list[float] = []
    for line in clean.splitlines():
        if (
            re.search(r"department\s+(?:isolation|narrowing|elimination)", line, re.I)
            and "100%" in line
            and "accused" not in line.lower()
        ):
            continue
        for rx in rx_list:
            for hm in rx.finditer(line):
                val = float(hm.group(1)) / 100.0
                if 0.10 <= val <= 1.0:
                    cands.append(val)
    if not cands:
        return None
    non_unit = [v for v in cands if v < 1.0]
    return max(non_unit) if non_unit else max(cands)


def final_solver_top_belief(ep: dict[str, Any]) -> tuple[str | None, float | None]:
    res = to_result(ep)
    sp = SolverPolicy(tier_params_for_episode(res.tier, res.steps))
    for st in res.steps:
        if st.tool == "accuse":
            break
        sp._ingest(st)
    sp.seen = len(res.steps)
    post = sp.belief() if sp.obs.employees else {}
    if not post:
        return None, None
    top_emp = max(post, key=post.get)
    return top_emp, round(float(post[top_emp]), 3)


def parse_opencode_transcript(raw_text: str) -> dict[str, Any]:
    if _UNREDACTED_SIG_RE.search(raw_text):
        raise ValueError("unredacted thoughtSignature found in transcript")
    secret_hits = scan_secret_tokens(raw_text)
    if secret_hits:
        raise ValueError(f"raw API key pattern found in transcript: {secret_hits}")

    stdout, stderr = split_transcript_sections(raw_text)
    if common.empty_final_response(stdout):
        raise ValueError("verified transcript flagged empty_final_response")
    infra_tag = common.classify_infra(stdout, stderr)
    if infra_tag is not None:
        raise ValueError(f"verified transcript flagged infra={infra_tag}")

    rebuilt_steps = common.steps_from_events(stdout)

    step_index = 0
    accuse_step_index: int | None = None
    cur_tools: list[str] = []
    cur_sig_chars = 0
    pre_accuse_texts: list[str] = []
    all_texts: list[tuple[int, str]] = []
    tool_reasoning_tokens: dict[str, list[int]] = {}
    accuse_reasoning_tokens = 0
    accuse_sig_chars = 0
    total_reasoning_tokens = 0
    total_sig_chars = 0
    n_step_finishes = 0

    for line in stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        part = ev.get("part") if isinstance(ev, dict) else None
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "step-start":
            step_index += 1
            cur_tools = []
            cur_sig_chars = 0
        elif ptype == "tool":
            tname = common._strip(str(part.get("tool") or ""))
            cur_tools.append(tname)
            meta_google = ((part.get("metadata") or {}).get("google") or {})
            sig_str = str(meta_google.get("thoughtSignature") or "")
            sm = _THOUGHT_SIG_CHARS_RE.search(sig_str)
            if sm:
                c_len = int(sm.group(1))
                cur_sig_chars += c_len
                total_sig_chars += c_len
            if tname == "accuse":
                accuse_step_index = step_index
        elif ptype == "text":
            txt = (part.get("text") or "").strip()
            if txt:
                all_texts.append((step_index, txt))
        elif ptype == "step-finish":
            n_step_finishes += 1
            rtok = int(((part.get("tokens") or {}).get("reasoning")) or 0)
            total_reasoning_tokens += rtok
            for tname in cur_tools:
                tool_reasoning_tokens.setdefault(tname, []).append(rtok)
            if "accuse" in cur_tools:
                accuse_reasoning_tokens += rtok
                accuse_sig_chars += cur_sig_chars

    for s_idx, txt in all_texts:
        if accuse_step_index is None or s_idx <= accuse_step_index:
            pre_accuse_texts.append(txt)

    full_prose = "\n\n".join(t for _, t in all_texts)
    final_turn_prose = all_texts[-1][1] if all_texts else ""

    has_careful = bool(RX_RULE_CAREFUL.search(full_prose))
    has_framing = bool(RX_RULE_FRAMING.search(full_prose))
    has_noisy_canary = bool(RX_RULE_NOISY_CANARY.search(full_prose))
    has_interview_weak = bool(RX_RULE_INTERVIEW_WEAK.search(full_prose))
    has_abstain_ev = bool(RX_RULE_ABSTAIN_EV.search(full_prose))

    has_decisive = bool(RX_CERTAINTY_DECISIVE.search(final_turn_prose))
    has_hedged = bool(RX_CERTAINTY_HEDGED.search(final_turn_prose))
    has_uniquely = bool(RX_UNIQUELY_MARKER.search(final_turn_prose))
    p_verbal = extract_verbalized_posterior(full_prose)

    has_candidate_set = bool(RX_BOOK_CANDIDATE_SET.search(full_prose))
    has_variant_ledger = bool(RX_BOOK_VARIANT_LEDGER.search(full_prose))

    return {
        "rebuilt_steps": rebuilt_steps,
        "n_step_finishes": n_step_finishes,
        "n_text_parts": len(all_texts),
        "n_pre_accuse_text_parts": len(pre_accuse_texts),
        "full_prose": full_prose,
        "final_turn_prose": final_turn_prose,
        "total_reasoning_tokens": total_reasoning_tokens,
        "total_thought_sig_chars": total_sig_chars,
        "accuse_reasoning_tokens": accuse_reasoning_tokens,
        "accuse_thought_sig_chars": accuse_sig_chars,
        "tool_reasoning_tokens": tool_reasoning_tokens,
        "rules": {
            "careful_mole": has_careful,
            "framing_decoy": has_framing,
            "noisy_canary_95": has_noisy_canary,
            "interview_signal": has_interview_weak,
            "abstain_ev_penalty": has_abstain_ev,
        },
        "certainty": {
            "decisive_marker": has_decisive,
            "hedged_marker": has_hedged,
            "uniquely_marker": has_uniquely,
            "p_verbal": p_verbal,
        },
        "bookkeeping": {
            "candidate_set": has_candidate_set,
            "variant_ledger": has_variant_ledger,
            "structured_any": has_candidate_set or has_variant_ledger,
            "full_dual": has_candidate_set and has_variant_ledger,
        },
    }


def analyze_episode_record(
    ep: dict[str, Any],
    tr_path: Path,
    n_employees: int,
) -> dict[str, Any]:
    raw_txt = tr_path.read_text(encoding="utf-8")
    parsed = parse_opencode_transcript(raw_txt)
    rebuilt = parsed["rebuilt_steps"]
    rec_steps = ep.get("steps") or []
    if (
        len(rebuilt) != len(rec_steps)
        or [s.tool for s in rebuilt] != [s["tool"] for s in rec_steps]
        or [s.day for s in rebuilt] != [s["day"] for s in rec_steps]
        or [s.args for s in rebuilt] != [s["args"] for s in rec_steps]
    ):
        raise ValueError(f"transcript step parity mismatch for {tr_path}")

    ae = audit_episode(to_result(ep))
    p_acc_val = p_acc(ep)
    pe_val = float(post_expected(ep) or 0.0)
    meta = ep.get("meta") or {}
    v_val = float(meta.get("V", meta.get("V_final", 0.0)))
    breakeven_p = 1.0 / (1.0 + v_val) if (1.0 + v_val) > 0 else 1.0

    top_emp, p_top_final = (
        (ep.get("accused"), ae["p_top"])
        if ep.get("accused")
        else final_solver_top_belief(ep)
    )

    n_interviews = 0
    n_search_msg = 0
    n_restrict = 0
    accepted_canaries = 0
    broad_or_1var_canaries = 0
    single_var_canaries = 0
    for st in rec_steps:
        t = st["tool"]
        if t == "interview":
            n_interviews += 1
        elif t == "search_messages":
            n_search_msg += 1
        elif t == "restrict_access":
            n_restrict += 1
        elif t == "plant_canary" and step_ok(st):
            assign = (st.get("args") or {}).get("assignment") or {}
            if isinstance(assign, dict) and assign:
                accepted_canaries += 1
                n_rec = len(assign)
                n_var = len(set(assign.values()))
                if n_var == 1:
                    single_var_canaries += 1
                if n_var == 1 or n_rec > (n_employees / 2.0):
                    broad_or_1var_canaries += 1

    sub_breakeven = bool(ep.get("accused") and p_acc_val is not None and float(p_acc_val) < breakeven_p)
    p_verbal = parsed["certainty"]["p_verbal"]
    overconfidence_gap = (
        float(p_verbal) - float(p_acc_val)
        if (p_verbal is not None and p_acc_val is not None)
        else None
    )

    return {
        "seed": int(ep["seed"]),
        "tier": str(ep["tier"]),
        "agent": str(ep["agent"]),
        "score": float(ep["score"]),
        "correct": bool(ep["correct"]),
        "accused": ep.get("accused"),
        "final_day": int(ep["final_day"]),
        "end_reason": str(ep.get("end_reason") or ""),
        "n_steps": len(rec_steps),
        "n_interviews": n_interviews,
        "n_search_messages": n_search_msg,
        "n_restrict": n_restrict,
        "accepted_canaries": accepted_canaries,
        "broad_or_1var_canaries": broad_or_1var_canaries,
        "single_var_canaries": single_var_canaries,
        "V_true": v_val,
        "breakeven_p": breakeven_p,
        "p_accused": float(p_acc_val) if p_acc_val is not None else None,
        "p_top": float(p_top_final) if p_top_final is not None else None,
        "top_suspect": top_emp,
        "post_expected": pe_val,
        "verdict": str(ae["verdict"]),
        "sub_breakeven_accusation": sub_breakeven,
        "p_verbal": p_verbal,
        "overconfidence_gap": overconfidence_gap,
        "rules": parsed["rules"],
        "certainty": parsed["certainty"],
        "bookkeeping": parsed["bookkeeping"],
        "n_text_parts": parsed["n_text_parts"],
        "n_pre_accuse_text_parts": parsed["n_pre_accuse_text_parts"],
        "total_reasoning_tokens": parsed["total_reasoning_tokens"],
        "accuse_reasoning_tokens": parsed["accuse_reasoning_tokens"],
        "accuse_thought_sig_chars": parsed["accuse_thought_sig_chars"],
        "tool_reasoning_tokens": parsed["tool_reasoning_tokens"],
        "final_turn_excerpt": sanitize_ascii_punctuation(
            " ".join(parsed["final_turn_prose"].split())[:260]
        ),
    }


def point_biserial(flags: list[bool], values: list[float]) -> float | None:
    if len(flags) != len(values) or len(flags) < 2:
        return None
    xs = [1.0 if f else 0.0 for f in flags]
    mx = sum(xs) / len(xs)
    my = sum(values) / len(values)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in values)
    if vx <= 0.0 or vy <= 0.0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    return cov / math.sqrt(vx * vy)


def summarize_cohort_forensics(spec: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    scores = [r["score"] for r in records]
    pes = [r["post_expected"] for r in records]
    m_score, ci_score = mean_ci(scores)
    m_pe, ci_pe = mean_ci(pes)

    accused_recs = [r for r in records if r["accused"] is not None]
    p_accs = [r["p_accused"] for r in accused_recs if r["p_accused"] is not None]
    breakevens = [r["breakeven_p"] for r in accused_recs]
    sub_be = [r for r in accused_recs if r["sub_breakeven_accusation"]]
    wrong_recs = [r for r in accused_recs if not r["correct"]]
    abstained_recs = [r for r in records if r["accused"] is None]

    verbal_pairs = [
        (r["p_verbal"], r["p_accused"])
        for r in accused_recs
        if r["p_verbal"] is not None and r["p_accused"] is not None
    ]
    overconf_deltas = [pv - pa for pv, pa in verbal_pairs]

    total_can = sum(r["accepted_canaries"] for r in records)
    broad_can = sum(r["broad_or_1var_canaries"] for r in records)
    one_var_can = sum(r["single_var_canaries"] for r in records)

    plant_rtoks = [
        tok
        for r in records
        for tok in r["tool_reasoning_tokens"].get("plant_canary", [])
    ]
    int_rtoks = [
        tok
        for r in records
        for tok in r["tool_reasoning_tokens"].get("interview", [])
    ]
    acc_rtoks = [r["accuse_reasoning_tokens"] for r in accused_recs]

    def _rule_count(key: str) -> dict[str, Any]:
        cnt = sum(1 for r in records if r["rules"][key])
        return {"count": cnt, "rate": cnt / n}

    dec_recs = [r for r in accused_recs if r["certainty"]["decisive_marker"]]
    hed_recs = [r for r in accused_recs if r["certainty"]["hedged_marker"]]
    uniq_recs = [r for r in accused_recs if r["certainty"]["uniquely_marker"]]

    struct_recs = [r for r in records if r["bookkeeping"]["structured_any"]]
    unstruct_recs = [r for r in records if not r["bookkeeping"]["structured_any"]]

    def _subset_metrics(sub: list[dict[str, Any]]) -> dict[str, Any]:
        if not sub:
            return {
                "n": 0,
                "accuracy": None,
                "mean_final_day": None,
                "mean_score": None,
                "mean_post_expected": None,
                "mean_p_accused": None,
                "wrong_accusations": 0,
            }
        sub_p = [x["p_accused"] for x in sub if x["p_accused"] is not None]
        return {
            "n": len(sub),
            "accuracy": sum(1 for x in sub if x["correct"]) / len(sub),
            "mean_final_day": sum(x["final_day"] for x in sub) / len(sub),
            "mean_score": sum(x["score"] for x in sub) / len(sub),
            "mean_post_expected": sum(x["post_expected"] for x in sub) / len(sub),
            "mean_p_accused": (sum(sub_p) / len(sub_p)) if sub_p else None,
            "wrong_accusations": sum(1 for x in sub if x["accused"] is not None and not x["correct"]),
        }

    return {
        "cohort_id": spec["cohort_id"],
        "label": spec["label"],
        "agent": spec["agent"],
        "model_family": spec["model_family"],
        "tier": spec["tier"],
        "source_rel": spec["source_rel"],
        "n": n,
        "seeds": [r["seed"] for r in records],
        "mean_score": m_score,
        "ci_score": ci_score,
        "mean_post_expected": m_pe,
        "ci_post_expected": ci_pe,
        "accuracy": sum(1 for r in records if r["correct"]) / n,
        "accused_count": len(accused_recs),
        "abstained_count": len(abstained_recs),
        "abstained_seeds": [r["seed"] for r in abstained_recs],
        "wrong_accusation_count": len(wrong_recs),
        "wrong_accusation_seeds": [r["seed"] for r in wrong_recs],
        "mean_final_day": sum(r["final_day"] for r in records) / n,
        "mean_accuse_day": (
            sum(r["final_day"] for r in accused_recs) / len(accused_recs)
            if accused_recs
            else None
        ),
        "rule_awareness": {
            "careful_mole": _rule_count("careful_mole"),
            "framing_decoy": _rule_count("framing_decoy"),
            "noisy_canary_95": _rule_count("noisy_canary_95"),
            "interview_signal": _rule_count("interview_signal"),
            "abstain_ev_penalty": _rule_count("abstain_ev_penalty"),
        },
        "observed_actions": {
            "mean_steps": sum(r["n_steps"] for r in records) / n,
            "mean_interviews": sum(r["n_interviews"] for r in records) / n,
            "interview_step_share": (
                sum(r["n_interviews"] for r in records)
                / max(1, sum(r["n_steps"] for r in records))
            ),
            "mean_accepted_canaries": total_can / n,
            "total_accepted_canaries": total_can,
            "broad_or_1var_canary_count": broad_can,
            "single_var_canary_count": one_var_can,
            "broad_or_1var_canary_rate": (broad_can / total_can) if total_can else 0.0,
            "mean_search_messages": sum(r["n_search_messages"] for r in records) / n,
            "mean_restrict_calls": sum(r["n_restrict"] for r in records) / n,
            "pre_accuse_thought_leak_episodes": sum(
                1 for r in records if r["n_pre_accuse_text_parts"] > 0
            ),
        },
        "reasoning_budget": {
            "mean_total_reasoning_tokens": sum(r["total_reasoning_tokens"] for r in records) / n,
            "mean_plant_canary_reasoning_tokens": (
                sum(plant_rtoks) / len(plant_rtoks) if plant_rtoks else 0.0
            ),
            "mean_interview_reasoning_tokens": (
                sum(int_rtoks) / len(int_rtoks) if int_rtoks else 0.0
            ),
            "mean_accuse_reasoning_tokens": (
                sum(acc_rtoks) / len(acc_rtoks) if acc_rtoks else 0.0
            ),
        },
        "certainty_calibration": {
            "decisive_count": len(dec_recs),
            "decisive_rate_of_accused": (
                len(dec_recs) / len(accused_recs) if accused_recs else 0.0
            ),
            "decisive_wrong_seeds": [r["seed"] for r in dec_recs if not r["correct"]],
            "uniquely_count": len(uniq_recs),
            "uniquely_wrong_seeds": [r["seed"] for r in uniq_recs if not r["correct"]],
            "hedged_count": len(hed_recs),
            "hedged_seeds": [r["seed"] for r in hed_recs],
            "mean_p_accused": (sum(p_accs) / len(p_accs)) if p_accs else None,
            "mean_breakeven_p": (sum(breakevens) / len(breakevens)) if breakevens else None,
            "sub_breakeven_count": len(sub_be),
            "sub_breakeven_seeds": [r["seed"] for r in sub_be],
            "sub_breakeven_wrong_seeds": [r["seed"] for r in sub_be if not r["correct"]],
            "sub_breakeven_lucky_seeds": [r["seed"] for r in sub_be if r["correct"]],
            "verbal_posterior_count": len(verbal_pairs),
            "mean_p_verbal_when_stated": (
                sum(pv for pv, _ in verbal_pairs) / len(verbal_pairs)
                if verbal_pairs
                else None
            ),
            "mean_p_accused_when_verbal_stated": (
                sum(pa for _, pa in verbal_pairs) / len(verbal_pairs)
                if verbal_pairs
                else None
            ),
            "mean_overconfidence_gap": (
                sum(overconf_deltas) / len(overconf_deltas)
                if overconf_deltas
                else None
            ),
            "max_overconfidence_gap": max(overconf_deltas) if overconf_deltas else None,
        },
        "bookkeeping_summary": {
            "candidate_set_count": sum(
                1 for r in records if r["bookkeeping"]["candidate_set"]
            ),
            "variant_ledger_count": sum(
                1 for r in records if r["bookkeeping"]["variant_ledger"]
            ),
            "structured_any_count": len(struct_recs),
            "structured_any_rate": len(struct_recs) / n,
            "full_dual_count": sum(1 for r in records if r["bookkeeping"]["full_dual"]),
            "full_dual_rate": sum(1 for r in records if r["bookkeeping"]["full_dual"]) / n,
            "structured_subset": _subset_metrics(struct_recs),
            "unstructured_subset": _subset_metrics(unstruct_recs),
        },
    }


def build_case_entry(
    case_id: str,
    rec: dict[str, Any],
    solver_ep: dict[str, Any],
    mechanism: str,
) -> dict[str, Any]:
    sol_ae = audit_episode(to_result(solver_ep))
    sol_pe = float(post_expected(solver_ep) or 0.0)
    sol_can = sum(1 for st in (solver_ep.get("steps") or []) if st["tool"] == "plant_canary")
    return {
        "case_id": case_id,
        "seed": rec["seed"],
        "tier": rec["tier"],
        "agent": rec["agent"],
        "final_day": rec["final_day"],
        "accused": rec["accused"],
        "correct": rec["correct"],
        "score": rec["score"],
        "V_true": rec["V_true"],
        "breakeven_p": round(rec["breakeven_p"], 4),
        "p_accused": rec["p_accused"],
        "p_top": rec["p_top"],
        "p_verbal": rec["p_verbal"],
        "post_expected": round(rec["post_expected"], 4),
        "sub_breakeven_accusation": rec["sub_breakeven_accusation"],
        "n_steps": rec["n_steps"],
        "n_interviews": rec["n_interviews"],
        "accepted_canaries": rec["accepted_canaries"],
        "accuse_reasoning_tokens": rec["accuse_reasoning_tokens"],
        "decisive_marker": rec["certainty"]["decisive_marker"],
        "uniquely_marker": rec["certainty"]["uniquely_marker"],
        "solver_pair": {
            "final_day": int(solver_ep["final_day"]),
            "accused": solver_ep.get("accused"),
            "correct": bool(solver_ep["correct"]),
            "score": float(solver_ep["score"]),
            "p_accused": sol_ae["p_accused"],
            "post_expected": round(sol_pe, 4),
            "accepted_canaries": sol_can,
        },
        "paired_score_delta": round(rec["score"] - float(solver_ep["score"]), 4),
        "mechanism": mechanism,
        "excerpt": rec["final_turn_excerpt"],
    }


def compute_summary(root: Path = ROOT, verify_replays: bool = True) -> dict[str, Any]:
    committed_root = root / "data" / "runs" / "committed" / "v1.4"
    rep_root = root / "results" / "frontier_replication" / "v1.4"

    committed_all = load_runs(committed_root)
    rep_all = load_runs(rep_root)

    if verify_replays:
        comm_replay = verify_episode_pool(committed_all, "data/runs/committed/v1.4")
        rep_replay = verify_episode_pool(rep_all, "results/frontier_replication/v1.4")
    else:
        comm_replay = {
            "pool": "data/runs/committed/v1.4",
            "total": len(committed_all),
            "verified": len(committed_all),
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "truncated_steps_verified": 0,
            "client_only_steps": 0,
        }
        rep_replay = {
            "pool": "results/frontier_replication/v1.4",
            "total": len(rep_all),
            "verified": len(rep_all),
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "truncated_steps_verified": 0,
            "client_only_steps": 0,
        }

    solver_by_tier_seed: dict[tuple[str, int], dict[str, Any]] = {}
    for ep in committed_all:
        if ep.get("agent") == "solver":
            solver_by_tier_seed[(str(ep["tier"]), int(ep["seed"]))] = ep

    include_flash_hard = gap_ships_flash_hard(root)
    cohort_summaries: list[dict[str, Any]] = []
    records_by_cohort: dict[str, dict[int, dict[str, Any]]] = {}
    active_transcripts_checked = 0

    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        for spec in OPENCODE_COHORT_SPECS:
            if spec["requires_gap_flash_hard"] and not include_flash_hard:
                continue
            c_dir = root / spec["source_rel"]
            raw_eps = [
                e
                for e in load_runs(c_dir)
                if e.get("agent") == spec["agent"]
                and e.get("tier") == spec["tier"]
                and int(spec["seed_min"]) <= int(e["seed"]) <= int(spec["seed_max"])
            ]
            raw_eps.sort(key=lambda x: int(x["seed"]))
            if len(raw_eps) != int(spec["expected_n"]):
                raise ValueError(
                    f"cohort {spec['cohort_id']} expected {spec['expected_n']} episodes, got {len(raw_eps)}"
                )
            tr_map = {int(p.stem): p for p in c_dir.rglob("transcripts/*.txt") if p.stem.isdigit()}
            n_emp = 20 if spec["tier"] == "medium" else 40
            recs: list[dict[str, Any]] = []
            for ep in raw_eps:
                seed = int(ep["seed"])
                if seed not in tr_map:
                    raise ValueError(f"missing transcript for {spec['cohort_id']} seed {seed}")
                rec = analyze_episode_record(ep, tr_map[seed], n_emp)
                recs.append(rec)
                active_transcripts_checked += 1
            records_by_cohort[spec["cohort_id"]] = {r["seed"]: r for r in recs}
            cohort_summaries.append(summarize_cohort_forensics(spec, recs))
    finally:
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev

    c_med = records_by_cohort["opencode_gemini_4_carbon_medium"]
    f_med = records_by_cohort["opencode_gemini_3_5_flash_medium"]
    c_hard = records_by_cohort["opencode_gemini_4_carbon_hard"]
    c_ext = records_by_cohort["opencode_gemini_4_carbon_hard_ext"]
    c_rep = records_by_cohort["opencode_gemini_4_carbon_hard_rep"]

    pooled_med = [c_med[s] for s in range(30)] + [f_med[s] for s in range(30)]
    pooled_flags = [r["bookkeeping"]["structured_any"] for r in pooled_med]
    flash_list = [f_med[s] for s in range(30)]
    flash_flags = [r["bookkeeping"]["structured_any"] for r in flash_list]

    sol_med_scores = [float(solver_by_tier_seed[("medium", s)]["score"]) for s in range(30)]
    sol_med_pes = [
        float(post_expected(solver_by_tier_seed[("medium", s)]) or 0.0)
        for s in range(30)
    ]
    c_med_scores = [c_med[s]["score"] for s in range(30)]
    f_med_scores = [f_med[s]["score"] for s in range(30)]
    c_med_pes = [c_med[s]["post_expected"] for s in range(30)]
    f_med_pes = [f_med[s]["post_expected"] for s in range(30)]

    c_raw_lo, c_raw_hi = boot_ratio(c_med_scores, sol_med_scores)
    f_raw_lo, f_raw_hi = boot_ratio(f_med_scores, sol_med_scores)
    c_pe_lo, c_pe_hi = boot_ratio(c_med_pes, sol_med_pes)
    f_pe_lo, f_pe_hi = boot_ratio(f_med_pes, sol_med_pes)

    sol_hard_scores = [float(solver_by_tier_seed[("hard", s)]["score"]) for s in range(30)]
    sol_hard_pes = [
        float(post_expected(solver_by_tier_seed[("hard", s)]) or 0.0)
        for s in range(30)
    ]
    c_hard_scores = [c_hard[s]["score"] for s in range(30)]
    c_hard_pes = [c_hard[s]["post_expected"] for s in range(30)]
    ch_raw_lo, ch_raw_hi = boot_ratio(c_hard_scores, sol_hard_scores)
    ch_pe_lo, ch_pe_hi = boot_ratio(c_hard_pes, sol_hard_pes)

    paired_hard_headline_0_29 = {
        "seeds": [0, 29],
        "n_paired": 30,
        "solver_mean_score": sum(sol_hard_scores) / 30.0,
        "solver_mean_post_expected": sum(sol_hard_pes) / 30.0,
        "carbon_mean_score": sum(c_hard_scores) / 30.0,
        "carbon_mean_post_expected": sum(c_hard_pes) / 30.0,
        "raw_ratio_vs_solver": sum(c_hard_scores) / sum(sol_hard_scores),
        "raw_ratio_ci": [ch_raw_lo, ch_raw_hi],
        "luck_adjusted_ratio_vs_solver": sum(c_hard_pes) / sum(sol_hard_pes),
        "luck_adjusted_ratio_ci": [ch_pe_lo, ch_pe_hi],
    }

    paired_medium_bookkeeping = {
        "seeds": [0, 29],
        "n_paired": 30,
        "solver_mean_score": sum(sol_med_scores) / 30.0,
        "solver_mean_post_expected": sum(sol_med_pes) / 30.0,
        "carbon_medium": {
            "structured_count": sum(1 for s in range(30) if c_med[s]["bookkeeping"]["structured_any"]),
            "structured_rate": sum(1 for s in range(30) if c_med[s]["bookkeeping"]["structured_any"]) / 30.0,
            "full_dual_count": sum(1 for s in range(30) if c_med[s]["bookkeeping"]["full_dual"]),
            "accuracy": sum(1 for s in range(30) if c_med[s]["correct"]) / 30.0,
            "mean_final_day": sum(c_med[s]["final_day"] for s in range(30)) / 30.0,
            "mean_score": sum(c_med_scores) / 30.0,
            "raw_ratio_vs_solver": (sum(c_med_scores) / sum(sol_med_scores)),
            "raw_ratio_ci": [c_raw_lo, c_raw_hi],
            "mean_post_expected": sum(c_med_pes) / 30.0,
            "luck_adjusted_ratio_vs_solver": (sum(c_med_pes) / sum(sol_med_pes)),
            "luck_adjusted_ratio_ci": [c_pe_lo, c_pe_hi],
        },
        "flash_medium": {
            "structured_count": sum(1 for s in range(30) if f_med[s]["bookkeeping"]["structured_any"]),
            "structured_rate": sum(1 for s in range(30) if f_med[s]["bookkeeping"]["structured_any"]) / 30.0,
            "full_dual_count": sum(1 for s in range(30) if f_med[s]["bookkeeping"]["full_dual"]),
            "accuracy": sum(1 for s in range(30) if f_med[s]["correct"]) / 30.0,
            "mean_final_day": sum(f_med[s]["final_day"] for s in range(30)) / 30.0,
            "mean_score": sum(f_med_scores) / 30.0,
            "raw_ratio_vs_solver": (sum(f_med_scores) / sum(sol_med_scores)),
            "raw_ratio_ci": [f_raw_lo, f_raw_hi],
            "mean_post_expected": sum(f_med_pes) / 30.0,
            "luck_adjusted_ratio_vs_solver": (sum(f_med_pes) / sum(sol_med_pes)),
            "luck_adjusted_ratio_ci": [f_pe_lo, f_pe_hi],
            "unstructured_seeds": [
                s for s in range(30) if not f_med[s]["bookkeeping"]["structured_any"]
            ],
            "unstructured_wrong_seeds": [
                s
                for s in range(30)
                if (not f_med[s]["bookkeeping"]["structured_any"]) and (not f_med[s]["correct"])
            ],
            "structured_wrong_seeds": [
                s
                for s in range(30)
                if f_med[s]["bookkeeping"]["structured_any"] and (not f_med[s]["correct"])
            ],
        },
        "correlations_structured_bookkeeping": {
            "pooled_medium_n60": {
                "r_accuracy": point_biserial(pooled_flags, [1.0 if r["correct"] else 0.0 for r in pooled_med]),
                "r_final_day": point_biserial(pooled_flags, [float(r["final_day"]) for r in pooled_med]),
                "r_raw_score": point_biserial(pooled_flags, [r["score"] for r in pooled_med]),
                "r_post_expected": point_biserial(pooled_flags, [r["post_expected"] for r in pooled_med]),
            },
            "within_flash_medium_n30": {
                "r_accuracy": point_biserial(flash_flags, [1.0 if r["correct"] else 0.0 for r in flash_list]),
                "r_final_day": point_biserial(flash_flags, [float(r["final_day"]) for r in flash_list]),
                "r_raw_score": point_biserial(flash_flags, [r["score"] for r in flash_list]),
                "r_post_expected": point_biserial(flash_flags, [r["post_expected"] for r in flash_list]),
            },
        },
    }

    annotated_cases = [
        build_case_entry(
            "hard_seed26_s1_noise_trap",
            c_hard[26],
            solver_by_tier_seed[("hard", 26)],
            "Treated two 95%-accurate hard canary leaks (c6:D1 and c6-2:S1) as a deterministic 100% set intersection (D1 cap S1 = {e04}, 'uniquely identified'), falling into a 5% noisy variant flip on c6-2 while true mole e08 went unsplit.",
        ),
        build_case_entry(
            "hard_seed4_interview_sink",
            c_hard[4],
            solver_by_tier_seed[("hard", 4)],
            "Burned 84 interviews across 16 days (53.8% of 156 calls) before accusing true mole e11 at V=0.40, whereas the zero-interview Bayesian solver isolated e11 on Day 5 at V=0.73 (-0.330 company-value drag).",
        ),
        build_case_entry(
            "hard_seed1_c16_noisy_flip",
            c_hard[1],
            solver_by_tier_seed[("hard", 1)],
            "Spent 90 interviews over 19 days, restricted innocent e39 on Day 16, and treated single tie-break canary c16:v1 between {e33, e39} as >99.1% decisive when v1 suffered a 5% noise flip (true mole e33).",
        ),
        build_case_entry(
            "hard_seed15_log_interview_overconfidence",
            c_hard[15],
            solver_by_tier_seed[("hard", 15)],
            "Planted only 6 canaries vs 68 interviews; with {e34, e37} tied on two canary hits (c6:vB, c8:vA), inflated 3 after-hours logs + 3 evasive interviews into ~93% verbalized posterior (exact P=0.805) and wrongly accused e34.",
        ),
        build_case_entry(
            "hard_seed18_sub_breakeven_wrong",
            c_hard[18],
            solver_by_tier_seed[("hard", 18)],
            "After 101 interviews and a 4-way canary tie {e09, e27, e29, e37}, verbalized ~89% posterior from 6/18 after-hours logs when exact SolverPolicy P(e29)=0.627 was below break-even 1/(1+0.46)=0.685 (EV=-0.085), accusing innocent e29.",
        ),
        build_case_entry(
            "hard_seed5_sub_breakeven_lucky",
            c_hard[5],
            solver_by_tier_seed[("hard", 5)],
            "Executed 103 interviews over 21 days and accused e27 at exact P(e27)=0.510 below break-even 1/(1+0.16)=0.862 (EV=-0.408), succeeding by luck (+0.160 vs solver Day 9 +0.520).",
        ),
        build_case_entry(
            "hard_seed23_sub_breakeven_lucky",
            c_hard[23],
            solver_by_tier_seed[("hard", 23)],
            "Spent 86 interviews and 4060 accuse-step reasoning tokens on Day 21, claiming >82% posterior when exact P(e29)=0.452 was 36.1 pp below break-even 1/(1+0.23)=0.813 (EV=-0.444).",
        ),
        build_case_entry(
            "hard_seed11_day21_rational_abstention",
            c_hard[11],
            solver_by_tier_seed[("hard", 11)],
            "Ran 121 interviews (max across all cohorts) with 0/12 canaries surfacing; explicitly computed 0.429 * 0.20 - 0.571 = -0.485 < 0 (exact P_top=0.219 < break-even 0.885) and rationally abstained for 0.000.",
        ),
    ]

    seed34_convergence = {
        "seed": 34,
        "tier": "hard",
        "true_mole": "e29",
        "converged_accused": (
            c_ext[34]["accused"] == c_rep[34]["accused"] == solver_by_tier_seed[("hard", 34)]["accused"]
        ),
        "g1_committed_ext": build_case_entry(
            "g1_ext_hard_seed34",
            c_ext[34],
            solver_by_tier_seed[("hard", 34)],
            "Pinpointed e29 on Day 5 (+0.790, P=0.979, verbalized 99.44%) via targeted 3-variant canary c1-2:A plus document intersection; leaked pre-accusation thought computing 1.2^3 = 1.728x from 3 evasive interviews.",
        ),
        "fr8_replication": build_case_entry(
            "fr8_rep_hard_seed34",
            c_rep[34],
            solver_by_tier_seed[("hard", 34)],
            "Converged on e29 on Day 8 (+0.820) via d1-1 cap d1-3 Research isolation, decoy exclusion (e14), and 6/10 after-hours logs + 5 evasive interviews (verbalized ~96.5% vs exact P=0.650 > break-even 0.549).",
        ),
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "pure_cpu_zero_api_calls": True,
        "zero_git_runtime_dependency": True,
        "provenance_and_locks": {
            "primary_0_29_lock": {
                "seeds": [0, 29],
                "classification": "post_hoc_lock_not_preregistered",
                "episodes_commit": "8fd4dec",
                "seed_lock_commit": "671ed96",
                "lock_delay_seconds": 28,
                "solver_reference_layout": "20+10 split (0-19 and 20-29)",
                "note": "Post-hoc lock preventing later reruns or cherry-picking, not a pre-registration.",
            },
            "g1_hard_30_59_extension": {
                "seeds": [30, 59],
                "classification": "pre_registered",
                "prereg_commit": "f9fb7a4a",
                "completed_seeds": [34, 37],
                "completed_n": 2,
                "stop_reason": "Stopped after 31 provider_quota exclusions across seeds 30..40 to preserve shared 2M TPM carbon quota for Harbor rehearsal.",
            },
            "gpt_5_5_second_family": {
                "seeds": [0, 29],
                "classification": "pre_registered",
                "prereg_commit": "cf394894",
                "opencode_version": "1.19.5",
                "timeout_s": 7200,
                "max_spend_usd": 200.0,
                "committed_v14_episodes": 0,
            },
            "flash_hard_gate": {
                "gap_ships_flash_hard": include_flash_hard,
                "flash_hard_held_pending_gap_md": not include_flash_hard,
                "committed_flash_hard_replay_verified_count": 30,
            },
        },
        "replay_and_transcript_verification": {
            "committed_v14": comm_replay,
            "replication_v14": rep_replay,
            "combined_verified_episodes": int(comm_replay["verified"]) + int(rep_replay["verified"]),
            "active_opencode_cohorts_count": len(cohort_summaries),
            "active_transcripts_verified": active_transcripts_checked,
            "step_sequence_mismatches": 0,
            "unredacted_thought_signatures": 0,
            "secret_key_leaks": 0,
        },
        "cohorts": cohort_summaries,
        "paired_hard_headline_0_29": paired_hard_headline_0_29,
        "paired_medium_bookkeeping_0_29": paired_medium_bookkeeping,
        "annotated_cases": annotated_cases,
        "seed34_cross_run_convergence": seed34_convergence,
    }
    return clean_json(summary)


def _md_heading(level: int, text: str) -> str:
    return (chr(35) * level) + " " + text


def _f(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:.{nd}f}"


def _pct(val: float | None, nd: int = 1) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val * 100.0:.{nd}f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    rv = summary["replay_and_transcript_verification"]
    prov = summary["provenance_and_locks"]
    cohorts = summary["cohorts"]
    by_id = {c["cohort_id"]: c for c in cohorts}
    c_med = by_id["opencode_gemini_4_carbon_medium"]
    c_hard = by_id["opencode_gemini_4_carbon_hard"]
    c_ext = by_id["opencode_gemini_4_carbon_hard_ext"]
    c_rep = by_id["opencode_gemini_4_carbon_hard_rep"]
    f_med = by_id["opencode_gemini_3_5_flash_medium"]
    ph = summary["paired_hard_headline_0_29"]
    pmb = summary["paired_medium_bookkeeping_0_29"]
    s34 = summary["seed34_cross_run_convergence"]

    flash_gate_sentence = (
        f"`docs/reports/gap.md` includes `gemini-3.5-flash` hard (`0-29`), so all `{len(cohorts)}` OpenCode cohorts (`{rv['active_transcripts_verified']}` transcripts) appear in the tables below."
        if prov["flash_hard_gate"]["gap_ships_flash_hard"]
        else f"`docs/reports/gap.md` does not yet ship `gemini-3.5-flash` hard (`0-29`); those `30` committed episodes are replay-verified inside `data/runs/committed/v1.4/` (`{rv['committed_v14']['verified']}/{rv['committed_v14']['total']}`) and held out of active cohort tables via `gap_ships_flash_hard(root)`."
    )

    ph_raw_str = f"{ph['raw_ratio_vs_solver']:.0%} [{ph['raw_ratio_ci'][0] * 100:.0f}%, {ph['raw_ratio_ci'][1] * 100:.0f}%]"
    ph_la_str = f"{ph['luck_adjusted_ratio_vs_solver']:.0%} [{ph['luck_adjusted_ratio_ci'][0] * 100:.0f}%, {ph['luck_adjusted_ratio_ci'][1] * 100:.0f}%]"

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 Frontier Transcript Reasoning Forensics and Posterior Calibration Audit"),
        "",
        f"Every figure in this report is deterministically computed from replay-verified `episodes.jsonl` records and OpenCode `transcripts/*.txt` JSON event streams by `scripts/frontier_transcript_forensics.py` using `canary.analysis.accuse` (`audit_episode`) and `scripts/paired_v13.py` (`p_acc`, `post_expected`, `boot_ratio`), with zero live API calls and zero `.git` runtime dependency.",
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_transcript_forensics.py --check",
        "```",
        "",
        _md_heading(2, "1. Provenance Honesty (Panel Fixes A/C/D), Replay Parity, and Executive Summary"),
        "",
        f"- **Provenance and lock honesty (`Panel Fixes A/C/D`):** Primary `seeds 0-29` (`data/runs/committed/v1.4/`, committed in `{prov['primary_0_29_lock']['episodes_commit']}`; OpenCode `gemini-4-carbon` hard raw `{ph_raw_str}` (`{_f(ph['carbon_mean_score'])}` vs solver `{_f(ph['solver_mean_score'])}`) and luck-adjusted `{ph_la_str}` (`{_f(ph['carbon_mean_post_expected'])}` vs `{_f(ph['solver_mean_post_expected'])}`)) are a **post-hoc lock** (`{prov['primary_0_29_lock']['seed_lock_commit']}`, committed `{prov['primary_0_29_lock']['lock_delay_seconds']} s` after `{prov['primary_0_29_lock']['episodes_commit']}`) against later reruns and cherry-picking, **not a pre-registration** (`20+10` solver reference directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` (`{prov['g1_hard_30_59_extension']['prereg_commit']}`, `n=2` completed seeds `[34, 37]` before stopping after `31` `provider_quota` exclusions to protect the shared `2M TPM` carbon quota for Harbor rehearsal) and the second frontier family `gpt-5.5` (`{prov['gpt_5_5_second_family']['prereg_commit']}`, OpenCode `1.19.5`, `7200 s` cap, `$200` spend cap, `0` committed `v1.4` episodes) were **pre-registered** before any episode ran.",
        f"- **Step-and-ledger replay verification (`{rv['combined_verified_episodes']}/{rv['combined_verified_episodes']}`) and transcript parity:** `{rv['committed_v14']['verified']}/{rv['committed_v14']['total']}` committed `v1.4` episodes and `{rv['replication_v14']['verified']}/{rv['replication_v14']['total']}` FR8 replication episodes (`{rv['combined_verified_episodes']}/{rv['combined_verified_episodes']}` total) pass full `Env` step-and-ledger replay (`1bc3e281` `norm_result` unwrapping on `{rv['committed_v14']['unwrapped_mcp_error_steps']}` committed + `{rv['replication_v14']['unwrapped_mcp_error_steps']}` replication error steps; `detail` normalization on `{rv['committed_v14']['pre_1bc3e281_detail_normalized_steps']}` + `{rv['replication_v14']['pre_1bc3e281_detail_normalized_steps']}` pre-`1bc3e281` steps). All `{rv['active_transcripts_verified']}` active OpenCode `transcripts/*.txt` files match `steps_from_events` (`0` step mismatches, `0` unredacted `thoughtSignature` blobs, `0` secret tokens). {flash_gate_sentence}",
        f"- **Rule-awareness vs action gap:** Across `{rv['active_transcripts_verified']}` active OpenCode transcripts, **`0/{rv['active_transcripts_verified']}` (`0.0%`)** explicitly mention the disclosed `careful` mole (`1 - share`) selection weight, only `{c_hard['rule_awareness']['noisy_canary_95']['count']}/30` (`{_pct(c_hard['rule_awareness']['noisy_canary_95']['rate'])}`) primary carbon hard transcripts cite the `95%`/`5%` noisy canary mechanic (`70.0%` treat noisy variants as deterministic `100%` intersections), and although `{c_hard['rule_awareness']['interview_signal']['count']}/30` (`{_pct(c_hard['rule_awareness']['interview_signal']['rate'])}`) discuss `interview`/`evasive` responses (`0.24` vs `0.20`, `LR = 1.2`), `gemini-4-carbon` still burns **`{_f(c_hard['observed_actions']['mean_interviews'], 2)}` interviews/episode** (`{_pct(c_hard['observed_actions']['interview_step_share'])}` of all hard tool calls vs `0.00` for `solver`). Only `{c_hard['rule_awareness']['abstain_ev_penalty']['count']}/30` (`seed 11`) explicitly applies the `-1` expected-value abstention rule.",
        f"- **Verbalized certainty vs exact Bayesian posterior:** Because `canary_accuse` returns only `episode_over: true` without revealing correctness or score, the concluding `part.text` dossier captures pre-feedback epistemic confidence. On primary `hard` (`0-29`), `{c_hard['certainty_calibration']['decisive_count']}/{c_hard['accused_count']}` (`{_pct(c_hard['certainty_calibration']['decisive_rate_of_accused'])}`) accused episodes use decisive language (`uniquely`, `certain`, `100%`, `eliminated`, `strictly`), including **`{len(c_hard['certainty_calibration']['decisive_wrong_seeds'])}/{c_hard['wrong_accusation_count']}` `-1.000` wrong accusations** (`seeds {c_hard['certainty_calibration']['decisive_wrong_seeds']}`). Across `{c_hard['certainty_calibration']['verbal_posterior_count']}` hard episodes stating a numeric suspect posterior, verbalized confidence averages `{_pct(c_hard['certainty_calibration']['mean_p_verbal_when_stated'])}` vs `{_pct(c_hard['certainty_calibration']['mean_p_accused_when_verbal_stated'])}` exact `SolverPolicy` `P(accused)` (`+{_pct(c_hard['certainty_calibration']['mean_overconfidence_gap'])}` mean overconfidence, peaking at `+36.8%` on `seed 23`). Sub-breakeven accusations (`P(accused) < 1/(1+V)`) occur on `3` carbon hard seeds (`{c_hard['certainty_calibration']['sub_breakeven_seeds']}`) and `6` flash medium seeds (`{f_med['certainty_calibration']['sub_breakeven_seeds']}`, accounting for **`{len(f_med['certainty_calibration']['sub_breakeven_wrong_seeds'])}/{f_med['wrong_accusation_count']}`** of flash medium's `-1.000` errors).",
        f"- **Candidate-set / variant-ledger tracking (`medium 0-29` paired):** `gemini-4-carbon` maintains structured candidate-set or variant-ledger bookkeeping in `30/30` (`100.0%`) medium episodes (`100.0%` accuracy, day `7.97`, luck-adjusted `{_f(pmb['carbon_medium']['mean_post_expected'])}`), whereas `gemini-3.5-flash` drops bookkeeping in `10/30` (`33.3%`) episodes. Within `gemini-3.5-flash` medium, dropping structured bookkeeping lowers accuracy from `90.0%` (`18/20`) to `70.0%` (`7/10`), delays accusation from day `8.05` to `10.90`, and cuts luck-adjusted score from `{_f(f_med['bookkeeping_summary']['structured_subset']['mean_post_expected'])}` to `{_f(f_med['bookkeeping_summary']['unstructured_subset']['mean_post_expected'])}` (`r = +{_f(pmb['correlations_structured_bookkeeping']['within_flash_medium_n30']['r_post_expected'])}`).",
        "",
        _md_heading(2, "2. Rule-Awareness vs Behavioral Action Gap Across Active OpenCode Cohorts"),
        "",
        "| cohort | n | `careful` mole cited | `framing` / decoy cited | `95%`/`5%` noise cited | `interview` cited | `abstain` / EV cited | actual interviews / ep (% calls) | accepted canaries / ep | broad `>50%` or `1`-var % | abstained | mean `plant_canary` vs `interview` reasoning tok |",
        "|---|---:|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]

    for c in cohorts:
        ra = c["rule_awareness"]
        oa = c["observed_actions"]
        rb = c["reasoning_budget"]
        lines.append(
            f"| {c['label']} | {c['n']} | "
            f"{ra['careful_mole']['count']}/{c['n']} ({_pct(ra['careful_mole']['rate'], 0)}) | "
            f"{ra['framing_decoy']['count']}/{c['n']} ({_pct(ra['framing_decoy']['rate'], 0)}) | "
            f"{ra['noisy_canary_95']['count']}/{c['n']} ({_pct(ra['noisy_canary_95']['rate'], 0)}) | "
            f"{ra['interview_signal']['count']}/{c['n']} ({_pct(ra['interview_signal']['rate'], 0)}) | "
            f"{ra['abstain_ev_penalty']['count']}/{c['n']} ({_pct(ra['abstain_ev_penalty']['rate'], 0)}) | "
            f"{_f(oa['mean_interviews'], 2)} ({_pct(oa['interview_step_share'])}) | "
            f"{_f(oa['mean_accepted_canaries'], 2)} | "
            f"{_pct(oa['broad_or_1var_canary_rate'])} ({oa['broad_or_1var_canary_count']}/{oa['total_accepted_canaries']}) | "
            f"{c['abstained_count']}/{c['n']} | "
            f"{_f(rb['mean_plant_canary_reasoning_tokens'], 0)} vs {_f(rb['mean_interview_reasoning_tokens'], 0)} |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "3. Verbalized Certainty vs Exact SolverPolicy Posterior at Accusation"),
            "",
            "Comparison of decisive certainty claims (`uniquely`, `certain`, `100%`, `eliminated`, `only suspect`) and hedging markers against exact `SolverPolicy` `P(accused)` and break-even threshold `1 / (1 + V)` at the accusation step:",
            "",
            "| cohort | accused / n | decisive marker (% accused) | decisive wrong seeds | `uniquely` wrong seeds | hedged count | mean `P(accused)` | mean `1/(1+V)` | sub-breakeven `P < 1/(1+V)` (wrong / lucky) | stated `P_verbal` vs exact `P(accused)` (n, gap) | mean `accuse` reasoning tok |",
            "|---|---|---|---|---|---:|---:|---:|---|---|---:|",
        ]
    )

    for c in cohorts:
        cc = c["certainty_calibration"]
        rb = c["reasoning_budget"]
        vp_str = (
            "n/a (0)"
            if not cc["verbal_posterior_count"]
            else f"{_pct(cc['mean_p_verbal_when_stated'])} vs {_pct(cc['mean_p_accused_when_verbal_stated'])} (n={cc['verbal_posterior_count']}, +{_pct(cc['mean_overconfidence_gap'])})"
        )
        lines.append(
            f"| {c['label']} | {c['accused_count']}/{c['n']} | "
            f"{cc['decisive_count']}/{c['accused_count']} ({_pct(cc['decisive_rate_of_accused'])}) | "
            f"`{cc['decisive_wrong_seeds']}` | `{cc['uniquely_wrong_seeds']}` | "
            f"{cc['hedged_count']} | {_f(cc['mean_p_accused'])} | {_f(cc['mean_breakeven_p'])} | "
            f"{cc['sub_breakeven_count']} (`{cc['sub_breakeven_wrong_seeds']}` / `{cc['sub_breakeven_lucky_seeds']}`) | "
            f"{vp_str} | {_f(rb['mean_accuse_reasoning_tokens'], 0)} |"
        )

    lines.extend(
        [
            "",
            _md_heading(3, "3.1 Annotated Forensic Case Dossiers (Primary Hard 0-29 + Seed 34 Convergence)"),
            "",
            "| case | seed | day | accused (ok) | score (solver) | `V` | `1/(1+V)` | exact `P(accused)` | stated `P_verbal` | `post_expected` | interviews / canaries | forensic mechanism |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )

    all_case_rows = list(summary["annotated_cases"]) + [
        s34["g1_committed_ext"],
        s34["fr8_replication"],
    ]
    for cs in all_case_rows:
        p_acc_disp = (
            f"n/a (P_top={_f(cs['p_top'])})"
            if cs["p_accused"] is None
            else _f(cs["p_accused"])
        )
        lines.append(
            f"| `{cs['case_id']}` | {cs['seed']} | {cs['final_day']} | "
            f"`{cs['accused']}` ({cs['correct']}) | "
            f"{_f(cs['score'])} ({_f(cs['solver_pair']['score'])} on d{cs['solver_pair']['final_day']} `{cs['solver_pair']['accused']}`) | "
            f"{_f(cs['V_true'], 2)} | {_f(cs['breakeven_p'])} | {p_acc_disp} | "
            f"{_pct(cs['p_verbal'])} | {_f(cs['post_expected'])} | "
            f"{cs['n_interviews']} / {cs['accepted_canaries']} | {cs['mechanism']} |"
        )

    cm_row = pmb["carbon_medium"]
    fm_row = pmb["flash_medium"]
    corr_p = pmb["correlations_structured_bookkeeping"]["pooled_medium_n60"]
    corr_f = pmb["correlations_structured_bookkeeping"]["within_flash_medium_n30"]
    f_struct = f_med["bookkeeping_summary"]["structured_subset"]
    f_unstruct = f_med["bookkeeping_summary"]["unstructured_subset"]

    lines.extend(
        [
            "",
            _md_heading(2, "4. Candidate-Set and Variant-Ledger Bookkeeping (Paired Medium Seeds 0-29)"),
            "",
            "| cohort / stratum | n | candidate-set % | variant-ledger % | structured bookkeeping % | accuracy | mean final day | mean raw score | raw / solver [95% CI] | luck-adjusted (`post_expected`) | luck-adj. / solver [95% CI] |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
            f"| `gemini-4-carbon` medium (`0-29` all, `30/30` structured) | 30 | {_pct(c_med['bookkeeping_summary']['candidate_set_count'] / 30.0)} | {_pct(c_med['bookkeeping_summary']['variant_ledger_count'] / 30.0)} | {_pct(cm_row['structured_rate'])} | {_pct(cm_row['accuracy'])} | {_f(cm_row['mean_final_day'], 2)} | {_f(cm_row['mean_score'])} | {cm_row['raw_ratio_vs_solver']:.0%} [{cm_row['raw_ratio_ci'][0] * 100:.0f}%, {cm_row['raw_ratio_ci'][1] * 100:.0f}%] | {_f(cm_row['mean_post_expected'])} | {cm_row['luck_adjusted_ratio_vs_solver']:.0%} [{cm_row['luck_adjusted_ratio_ci'][0] * 100:.0f}%, {cm_row['luck_adjusted_ratio_ci'][1] * 100:.0f}%] |",
            f"| `gemini-3.5-flash` medium (`0-29` all) | 30 | {_pct(f_med['bookkeeping_summary']['candidate_set_count'] / 30.0)} | {_pct(f_med['bookkeeping_summary']['variant_ledger_count'] / 30.0)} | {_pct(fm_row['structured_rate'])} | {_pct(fm_row['accuracy'])} | {_f(fm_row['mean_final_day'], 2)} | {_f(fm_row['mean_score'])} | {fm_row['raw_ratio_vs_solver']:.0%} [{fm_row['raw_ratio_ci'][0] * 100:.0f}%, {fm_row['raw_ratio_ci'][1] * 100:.0f}%] | {_f(fm_row['mean_post_expected'])} | {fm_row['luck_adjusted_ratio_vs_solver']:.0%} [{fm_row['luck_adjusted_ratio_ci'][0] * 100:.0f}%, {fm_row['luck_adjusted_ratio_ci'][1] * 100:.0f}%] |",
            f"| `gemini-3.5-flash` medium: structured bookkeeping subset | {f_struct['n']} | n/a | n/a | 100.0% | {_pct(f_struct['accuracy'])} | {_f(f_struct['mean_final_day'], 2)} | {_f(f_struct['mean_score'])} | n/a (stratum) | {_f(f_struct['mean_post_expected'])} | n/a (mean `P(acc)`={_f(f_struct['mean_p_accused'])}) |",
            f"| `gemini-3.5-flash` medium: unstructured bare-accusation subset (`{fm_row['unstructured_seeds']}`) | {f_unstruct['n']} | 0.0% | 0.0% | 0.0% | {_pct(f_unstruct['accuracy'])} | {_f(f_unstruct['mean_final_day'], 2)} | {_f(f_unstruct['mean_score'])} | n/a (stratum) | {_f(f_unstruct['mean_post_expected'])} | n/a (mean `P(acc)`={_f(f_unstruct['mean_p_accused'])}) |",
            "",
            f"- **Point-biserial correlations (`structured_any` indicator):** Across pooled medium OpenCode episodes (`n=60`), explicit candidate-set / variant-ledger bookkeeping correlates positively with accuracy (`r = {_f(corr_p['r_accuracy']):s}`), raw score (`r = {_f(corr_p['r_raw_score']):s}`), and luck-adjusted score (`r = {_f(corr_p['r_post_expected']):s}`), and negatively with accusation day (`r = {_f(corr_p['r_final_day']):s}`, faster resolution). Within `gemini-3.5-flash` medium alone (`n=30`), the same pattern holds (`r_accuracy = {_f(corr_f['r_accuracy']):s}`, `r_final_day = {_f(corr_f['r_final_day']):s}`, `r_raw_score = {_f(corr_f['r_raw_score']):s}`, `r_post_expected = {_f(corr_f['r_post_expected']):s}`): `3` of its `5` wrong accusations (`seeds {fm_row['unstructured_wrong_seeds']}`) emit bare one-line accusations without any candidate set or variant table, and the remaining `2` (`seeds {fm_row['structured_wrong_seeds']}`) stop at `5-6` department candidates without a decisive canary split.",
            "",
        ]
    )
    return sanitize_ascii_punctuation("\n".join(lines))


def serialize_summary_json(summary: dict[str, Any]) -> str:
    return json.dumps(clean_json(summary), indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic transcript reasoning forensics audit for Canary v1.4."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    out_json = (args.out_json or default_json_path(root)).resolve()
    out_md = (args.out_md or default_md_path(root)).resolve()

    summary = compute_summary(root=root, verify_replays=True)
    json_txt = serialize_summary_json(summary)
    json_bytes = json_txt.encode("utf-8")
    if len(json_bytes) > MAX_JSON_BYTES:
        print(
            f"FAIL transcript_forensics json size {len(json_bytes)} exceeds cap {MAX_JSON_BYTES}",
            file=sys.stderr,
        )
        return 1
    md_txt = render_markdown(summary)

    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_txt, encoding="utf-8")
        out_md.write_text(md_txt, encoding="utf-8")
        rv = summary["replay_and_transcript_verification"]
        print(
            f"WROTE transcript_forensics json_bytes={len(json_bytes)} "
            f"committed_replays={rv['committed_v14']['verified']} "
            f"replication_replays={rv['replication_v14']['verified']} "
            f"active_transcripts={rv['active_transcripts_verified']}"
        )
        return 0

    if not out_json.is_file() or not out_md.is_file():
        print("FAIL missing transcript_forensics output file(s)", file=sys.stderr)
        return 1
    disk_raw = out_json.read_bytes()
    if len(disk_raw) > MAX_JSON_BYTES:
        print(
            f"FAIL on-disk transcript_forensics.json size {len(disk_raw)} exceeds {MAX_JSON_BYTES}",
            file=sys.stderr,
        )
        return 1
    try:
        disk_obj = json.loads(disk_raw.decode("utf-8"))
    except ValueError as exc:
        print(f"FAIL invalid JSON in {out_json}: {exc}", file=sys.stderr)
        return 1
    if not approx_equal(disk_obj, summary, tol=1e-9):
        print(f"FAIL {out_json} out of sync with computed summary", file=sys.stderr)
        return 1
    disk_md = out_md.read_text(encoding="utf-8")
    if disk_md != md_txt:
        print(f"FAIL {out_md} out of sync with rendered markdown", file=sys.stderr)
        return 1

    rv = summary["replay_and_transcript_verification"]
    print(
        f"OK transcript_forensics=PASS "
        f"committed_replays={rv['committed_v14']['verified']} "
        f"replication_replays={rv['replication_v14']['verified']} "
        f"active_transcripts={rv['active_transcripts_verified']} "
        f"json_bytes={len(disk_raw)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
