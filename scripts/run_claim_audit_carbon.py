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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import lab_client
from canary.gemini.sdk import genai_client
from canary.llm import register_script

ROLE = "failure_analyst"
SUBROLE = "atlas_claim_audit_carbon"
FEATURE = "claim_audit_carbon"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_THINKING_LEVEL = "medium"
DEFAULT_BATCH_SIZE = 10
DEFAULT_REQUEST_TIMEOUT_S = 600.0
AUDITOR_LABEL = "gemini-4-carbon (automated LLM audit, not human)"

DEFAULT_SHEET_PATH = Path("docs/gemini/validation.md")
DEFAULT_CONTEXT_PATH = Path("docs/gemini/validation_context.md")
DEFAULT_OUT_DIR = Path("results/gemini_roles/failure_analyst/claim-audit-carbon")

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3

VERDICT_ENUM = ["agree", "disagree", "unsure"]
CLAIM_KINDS = ("mode", "label", "counterfactual", "localisation")
OVERCLAIM_TYPE_ENUM = [
    "none",
    "evidence_backed_framing_luck",
    "false_solver_counterfactual",
    "unverified_mental_state_without_rationale",
    "magnitude_or_mechanism_exaggeration",
]

CLAIM_AUDIT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_id": {
            "type": "integer",
            "description": "Exact integer claim number (1..N) from the validation sheet.",
        },
        "verdict": {
            "type": "string",
            "enum": VERDICT_ENUM,
            "description": (
                "Independent audit verdict on whether the Atlas claim is accurate and well-supported "
                "by the trajectory and exact Bayesian solver numbers: agree, disagree, or unsure."
            ),
        },
        "overclaim_flag": {
            "type": "boolean",
            "description": (
                "True if the claim overstates an agent error, misstates what SolverPolicy would do, "
                "blames the agent for accusing the Bayesian solver's own top-posterior suspect under "
                "heavy framing/noise luck, or fabricates mental-state causes when rationale=none."
            ),
        },
        "overclaim_type": {
            "type": "string",
            "enum": OVERCLAIM_TYPE_ENUM,
            "description": "Category of over-claim if overclaim_flag is true, else 'none'.",
        },
        "rationale": {
            "type": "string",
            "description": (
                "Concise forensic rationale (25 to 420 chars) citing exact solver numbers (REGRET, tags, "
                "top=, mole:) and trajectory evidence. Use plain ASCII hyphens only; never em or en dashes."
            ),
        },
        "verbatim_context_line": {
            "type": "string",
            "description": (
                "Exact unmodified single-line excerpt (at least 20 chars, preferring the entire '>>> t...' "
                "step line, another 't... d...' tool line, an 'outcome:' line, or an exact substring of a "
                "'says:' line) copied character-for-character from inside this claim's CONTEXT_BLOCK."
            ),
        },
    },
    "required": [
        "claim_id",
        "verdict",
        "overclaim_flag",
        "overclaim_type",
        "rationale",
        "verbatim_context_line",
    ],
}

CLAIM_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": (
                "Concise quantitative synthesis (80 to 900 chars) of the independent 30-claim audit, "
                "explaining overall solver-consistency findings and specific over-claims caught. "
                "Use plain ASCII hyphens only."
            ),
        },
        "audits": {
            "type": "array",
            "items": CLAIM_AUDIT_ITEM_SCHEMA,
        },
    },
    "required": ["executive_summary", "audits"],
}

SYSTEM_PROMPT = (
    "You are an independent Forensic Claim & Solver-Consistency Auditor (automated LLM audit, not human) "
    "evaluating 30 Failure Atlas claims in the Canary insider-leak benchmark.\n\n"
    "EXACT BENCHMARK & SOLVER GROUND TRUTH (from canary/solver/policy.py and canary/solver/regret.py):\n"
    "1. Accusing the true mole yields +V (remaining company value in [0, 1]); accusing an innocent employee "
    "yields -1.0; abstaining at horizon yields 0.0. Expected value of accusing employee e with Bayesian "
    "posterior P(e) is EV(accuse e) = P(e) * V - (1 - P(e)) = P(e) * (1 + V) - 1.\n"
    "2. SolverPolicy._plan() ONLY accuses best = argmax_e P(e) when BOTH EV(accuse best) > 0 AND "
    "(P(best) >= threshold OR today >= final_day), where threshold is 0.90 (medium) or 0.85 (hard). "
    "Crucially, if P(best) <= 0.50, then EV(accuse best) <= 0.50 * V - 0.50 <= 0.0 for all V <= 1.0, so "
    "SolverPolicy NEVER accuses on the final day when top_prob <= 0.50 - it ABSTAINS instead!\n"
    "3. Step regret in canary/solver/regret.py:\n"
    "   - accuse: REGRET = max(0, V* - EV(accuse e)), tags: [premature_accusation] if P(e) < 0.60, "
    "[decoy_chase] if e == decoy, [ignored_delay] if unsurfaced leak day is still in delay pipeline and P(e) < 0.90.\n"
    "   - plant_canary: REGRET = max(0, Gini(solver_split) - Gini(agent_split)) * p_leak * leak_damage * 2, "
    "tag [uninformative_canary] if Gini(agent_split) < 0.20.\n"
    "   - restrict_access: REGRET = restrict_cost_per_day * max(1, days_left) * (1 - P(e)), "
    "tag [over_restriction] if P(e) < 0.10.\n\n"
    "AUDITING RULES:\n"
    "1. Judge each claim independently as 'agree', 'disagree', or 'unsure' by checking EVERY part of the "
    "claim against the trajectory excerpt, agent 'says:' rationale (or lack thereof when rationale=none), "
    "and exact solver state (REGRET, tags, top=<emp>:<prob>, mole:<prob>) at the '>>>' marked step t.\n"
    "2. Flag over-claims rigorously (overclaim_flag=true with appropriate overclaim_type):\n"
    "   - 'evidence_backed_framing_luck': Claim blames the agent for hallucinating, miscalculating canary "
    "intersections, or ignoring evidence to accuse an innocent employee when the exact Bayesian solver ITSELF "
    "assigned high posterior to that exact same innocent suspect (for example g4carbon.in.v14.h6 where "
    "top=e18:.63 vs mole:.01, or gpt5.5.co.v12.h0 where top=e05:.92 vs mole:.08 due to 5% canary variant noise). "
    "If the claim misdiagnoses unlucky Bayesian framing/noise or sub-threshold stopping as an agent calculation "
    "or framing-fixation error, mark 'disagree' (or 'unsure' if partially valid) and set overclaim_flag=true.\n"
    "   - 'false_solver_counterfactual': Counterfactual claim states SolverPolicy would take an action that "
    "violates SolverPolicy._plan() (for example claiming the solver on the final day would accuse top=e01 at "
    "~0.29 when EV(accuse) < 0 so SolverPolicy would abstain). Mark 'disagree' and overclaim_flag=true.\n"
    "   - 'unverified_mental_state_without_rationale': Claim asserts specific internal agent reasoning or noisy "
    "log confusion that is contradicted by or absent from the excerpt (for example rationale=none and inspected "
    "logs show after-hours: none). Mark 'disagree' or 'unsure' and overclaim_flag=true.\n"
    "   - 'magnitude_or_mechanism_exaggeration': Claim exaggerates tiny regret (~0.02) as substantial loss or "
    "calls a low-probability document strictly unpickable. Flag overclaim_flag=true (verdict may be 'agree' if "
    "core failure mode label is still right, or 'disagree'/'unsure' if materially misleading).\n"
    "3. When overclaim_flag is false, overclaim_type MUST be 'none'.\n"
    "4. For verbatim_context_line, copy ONE exact unmodified single-line string (at least 20 chars) "
    "character-for-character from inside that claim's CONTEXT_BLOCK ( NOT the '=== EPISODE' header line; "
    "prefer the '>>> t...' step line, another 't... d...' line, or an exact substring of a 'says:' line).\n"
    "5. Never use unicode em dashes or en dashes anywhere; use plain ASCII '-' only."
)

SHEET_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")
CONTEXT_SEC_RE = re.compile(
    r"(?:^|\n)" + H2 + r" (\d+)\. (\S+) t=(\d+) \((\w+)\)\n\n\*\*Claim:\*\* (.*?)\n\n```\n(.*?)\n```",
    re.S,
)
MARKED_STEP_RE = re.compile(
    r"^>>>\s+t(\d+)\s+d(\d+)\s+([A-Za-z0-9_]+)\((.*?)\)\s*->\s*(.*)$"
)
REGRET_SEGMENT_RE = re.compile(r"^REGRET\s+([0-9]+(?:\.[0-9]+)?)(?:\s*\[([^\]]*)\])?$")
BELIEF_SEGMENT_RE = re.compile(
    r"^top=([A-Za-z0-9_]+):(\.[0-9]+|[0-9]+(?:\.[0-9]+)?)\s+mole:(\.[0-9]+|[0-9]+(?:\.[0-9]+)?)$"
)
EMPLOYEE_ARG_RE = re.compile(r"(?:^|,)employee=([A-Za-z0-9_]+)")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
TODO_TBD_RE = re.compile(r"\b(?:TODO|TBD)\b", re.IGNORECASE)
SAFE_PLACEHOLDERS = frozenset({
    "",
    "null",
    "none",
    "false",
    "true",
    "unset",
    "redacted",
    "[redacted]",
    "<redacted>",
    "empty",
    "missing",
})


def _has_env_secret(text: str) -> bool:
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            return True
    return False


def scan_file_secrets(file_path: Path, root: Path) -> list[dict[str, str]]:
    try:
        rel = file_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = file_path.as_posix()
    try:
        text = file_path.read_bytes().decode("latin-1")
    except OSError:
        return [{"file": rel, "kind": "unreadable_file"}]
    findings: list[dict[str, str]] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "google_api_key"})
    if SK_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "sk_api_key"})
    if OAUTH_RE.search(text):
        findings.append({"file": rel, "kind": "oauth_token"})
    if _has_env_secret(text):
        findings.append({"file": rel, "kind": "env_api_key"})
    return findings


def validate_report_text(text: str) -> list[str]:
    errors: list[str] = []
    if "\u27e8" in text or "\u27e9" in text:
        errors.append("angle_bracket_placeholder")
    if TODO_TBD_RE.search(text):
        errors.append("todo_or_tbd_placeholder")
    if "\u2014" in text:
        errors.append("em_dash")
    if "\u2013" in text:
        errors.append("en_dash")
    if GOOGLE_KEY_RE.search(text):
        errors.append("secret_leak:google_api_key")
    if SK_KEY_RE.search(text):
        errors.append("secret_leak:sk_api_key")
    if OAUTH_RE.search(text):
        errors.append("secret_leak:oauth_token")
    if _has_env_secret(text):
        errors.append("secret_leak:env_api_key")
    return errors


def sanitize_dashes(text: Any) -> str:
    s = "" if text is None else str(text)
    return (
        s.replace("\u2014", " - ")
        .replace("\u2013", "-")
        .replace("\u2012", "-")
        .replace("\u2015", "-")
    )


def sanitize_text(text: Any) -> str:
    s = sanitize_dashes(text)
    s = s.replace("\u27e8", "[").replace("\u27e9", "]")
    if _has_env_secret(s):
        s = ENV_KEY_RE.sub("[redacted]", s)
    s = GOOGLE_KEY_RE.sub("[redacted]", s)
    s = SK_KEY_RE.sub("[redacted]", s)
    s = OAUTH_RE.sub("[redacted]", s)
    s = re.sub(r"\b(?:TODO|TBD)\b", "unspecified", s, flags=re.IGNORECASE)
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


def _strip_outer_quotes(val: str) -> str:
    s = val.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def parse_validation_sheet(sheet_path: str | Path = DEFAULT_SHEET_PATH) -> list[dict[str, Any]]:
    text = Path(sheet_path).read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not SHEET_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        rows.append(
            {
                "claim_id": int(cells[0]),
                "episode": cells[1].strip(),
                "t": int(cells[2]),
                "claim": cells[3].strip(),
                "sheet_quote": _strip_outer_quotes(cells[4]),
            }
        )
    return rows


def parse_validation_context(context_path: str | Path = DEFAULT_CONTEXT_PATH) -> dict[int, dict[str, Any]]:
    text = Path(context_path).read_text(encoding="utf-8")
    sections: dict[int, dict[str, Any]] = {}
    for match in CONTEXT_SEC_RE.finditer(text):
        cid = int(match.group(1))
        sections[cid] = {
            "claim_id": cid,
            "episode": match.group(2).strip(),
            "t": int(match.group(3)),
            "kind": match.group(4).strip(),
            "context_claim": match.group(5).strip(),
            "raw_block": match.group(6),
            "clean_block": sanitize_dashes(match.group(6)),
        }
    return sections


def _parse_kv_tokens(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in text.strip().split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_episode_header_and_outcome(raw_block: str) -> tuple[dict[str, Any], dict[str, Any]]:
    lines = raw_block.splitlines()
    ep_meta: dict[str, Any] = {}
    outcome: dict[str, Any] = {}
    for ln in lines[:4]:
        if ln.startswith("=== EPISODE "):
            parts = ln[len("=== EPISODE ") :].split("|", 1)
            ep_meta["episode_id"] = parts[0].strip()
            if len(parts) > 1:
                kv = _parse_kv_tokens(parts[1])
                ep_meta.update(kv)
                if "seed" in ep_meta and ep_meta["seed"].isdigit():
                    ep_meta["seed"] = int(ep_meta["seed"])
        elif ln.startswith("outcome:"):
            kv = _parse_kv_tokens(ln[len("outcome:") :])
            outcome["accused"] = kv.get("accused")
            outcome["correct"] = kv.get("correct") == "True" if "correct" in kv else None
            outcome["true_mole"] = kv.get("true_mole")
            outcome["score"] = float(kv["score"]) if "score" in kv else None
            outcome["solver_same_seed"] = float(kv["solver_same_seed"]) if "solver_same_seed" in kv else None
            outcome["final_day"] = int(kv["final_day"]) if "final_day" in kv and kv["final_day"].isdigit() else None
            outcome["end"] = kv.get("end")
            outcome["total_regret"] = float(kv["total_regret"]) if "total_regret" in kv else None
            outcome["rationale"] = kv.get("rationale")
    return ep_meta, outcome


def parse_marked_step(raw_block: str) -> dict[str, Any]:
    marked_lines = [ln for ln in raw_block.splitlines() if ln.startswith(">>> ")]
    if not marked_lines:
        raise ValueError("context block has no '>>> ' marked step line")
    marked_line = marked_lines[0]
    m = MARKED_STEP_RE.match(marked_line)
    if not m:
        raise ValueError(f"cannot parse marked step line: {marked_line!r}")

    step_t = int(m.group(1))
    day = int(m.group(2))
    tool = m.group(3)
    raw_args = m.group(4)
    rhs = m.group(5)

    segments = [seg.strip() for seg in rhs.split("|")]
    action_result = segments[0] if segments else ""
    regret_val = 0.0
    has_explicit_regret = False
    tags: list[str] = []
    top_emp: str | None = None
    top_prob: float | None = None
    mole_prob: float | None = None

    for seg in segments[1:]:
        rm = REGRET_SEGMENT_RE.match(seg)
        if rm:
            has_explicit_regret = True
            regret_val = float(rm.group(1))
            raw_tags = (rm.group(2) or "").strip()
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []
            continue
        bm = BELIEF_SEGMENT_RE.match(seg)
        if bm:
            top_emp = bm.group(1)
            top_prob = float(bm.group(2))
            mole_prob = float(bm.group(3))

    emp_match = EMPLOYEE_ARG_RE.search(raw_args)
    target_emp = emp_match.group(1) if emp_match else None

    return {
        "raw_line": sanitize_text(marked_line),
        "t": step_t,
        "day": day,
        "tool": tool,
        "args_str": sanitize_text(raw_args),
        "target_employee": target_emp,
        "result_str": sanitize_text(action_result),
        "has_explicit_regret": has_explicit_regret,
        "regret": round(regret_val, 6),
        "tags": tags,
        "top_employee": top_emp,
        "top_prob": round(top_prob, 4) if top_prob is not None else None,
        "mole_prob": round(mole_prob, 4) if mole_prob is not None else None,
    }


def verify_sheet_quote_in_context(sheet_quote: str, raw_block: str) -> dict[str, Any]:
    q = sheet_quote.strip()
    if not q:
        return {
            "verified": False,
            "match_mode": "empty_quote",
            "matched_substring": None,
            "matched_line": None,
        }
    for ln in raw_block.splitlines():
        if q in ln:
            return {
                "verified": True,
                "match_mode": "exact",
                "matched_substring": sanitize_text(q),
                "matched_line": sanitize_text(ln),
            }
        escaped_ln = ln.replace("|", "/")
        pos = escaped_ln.find(q)
        if pos != -1:
            orig_sub = ln[pos : pos + len(q)]
            return {
                "verified": True,
                "match_mode": "table_pipe_escaped",
                "matched_substring": sanitize_text(orig_sub),
                "matched_line": sanitize_text(ln),
            }
    norm_blk = " ".join(raw_block.split()).replace("|", "/")
    norm_q = " ".join(q.split()).replace("|", "/")
    if norm_q in norm_blk:
        return {
            "verified": True,
            "match_mode": "whitespace_and_pipe_normalized",
            "matched_substring": sanitize_text(q),
            "matched_line": None,
        }
    return {
        "verified": False,
        "match_mode": "not_found",
        "matched_substring": None,
        "matched_line": None,
    }


def load_and_verify_claims(
    sheet_path: str | Path = DEFAULT_SHEET_PATH,
    context_path: str | Path = DEFAULT_CONTEXT_PATH,
) -> list[dict[str, Any]]:
    rows = parse_validation_sheet(sheet_path)
    sections = parse_validation_context(context_path)
    if not rows:
        raise ValueError(f"no validation claim rows parsed from {sheet_path}")
    missing = [r["claim_id"] for r in rows if r["claim_id"] not in sections]
    if missing:
        raise ValueError(f"validation_context missing section ids: {missing}")

    claims: list[dict[str, Any]] = []
    for row in rows:
        cid = row["claim_id"]
        sec = sections[cid]
        if row["episode"] != sec["episode"] or row["t"] != sec["t"]:
            raise ValueError(
                f"sheet/context mismatch on claim {cid}: "
                f"({row['episode']}, {row['t']}) vs ({sec['episode']}, {sec['t']})"
            )
        ep_meta, outcome = parse_episode_header_and_outcome(sec["raw_block"])
        step_info = parse_marked_step(sec["raw_block"])
        if step_info["t"] != row["t"]:
            raise ValueError(
                f"marked step t={step_info['t']} does not match claim t={row['t']} on claim {cid}"
            )
        quote_chk = verify_sheet_quote_in_context(row["sheet_quote"], sec["raw_block"])
        has_says = any(ln.lstrip().startswith("says:") for ln in sec["raw_block"].splitlines())
        target_emp = step_info["target_employee"]
        top_emp = step_info["top_employee"]
        top_prob = step_info["top_prob"]
        true_mole = outcome.get("true_mole")

        signals = {
            "step_t_matches": step_info["t"] == row["t"],
            "has_says_rationale": has_says,
            "rationale_none": outcome.get("rationale") == "none" and not has_says,
            "accused_matches_solver_top": (
                (target_emp == top_emp) if (step_info["tool"] == "accuse" and target_emp and top_emp) else None
            ),
            "solver_top_is_innocent": bool(top_emp and true_mole and top_emp != true_mole),
            "solver_never_accuses_at_top_prob": bool(top_prob is not None and top_prob <= 0.50),
        }

        claims.append(
            {
                "claim_id": cid,
                "kind": sec["kind"],
                "episode": row["episode"],
                "t": row["t"],
                "claim": sanitize_text(sec["context_claim"] or row["claim"]),
                "sheet_claim": sanitize_text(row["claim"]),
                "sheet_quote": sanitize_text(row["sheet_quote"]),
                "sheet_quote_check": quote_chk,
                "episode_meta": ep_meta,
                "outcome": outcome,
                "solver_step": step_info,
                "consistency_signals": signals,
                "clean_block": sec["clean_block"],
                "raw_block": sec["raw_block"],
            }
        )
    return claims


def build_user_prompt(claims: list[dict[str, Any]]) -> str:
    kind_counts = Counter(c["kind"] for c in claims)
    kind_str = ", ".join(f"{k}={kind_counts.get(k, 0)}" for k in CLAIM_KINDS if kind_counts.get(k, 0))
    lines = [
        f"TOTAL_CLAIMS_TO_AUDIT: {len(claims)} ({kind_str})",
        f"REQUIRED_CLAIM_IDS: {', '.join(str(c['claim_id']) for c in claims)}",
        "",
        "For EVERY claim below, return an entry in `audits` with exact `claim_id`, independent `verdict` "
        "(`agree`, `disagree`, or `unsure`), `overclaim_flag`, `overclaim_type`, concise `rationale`, and "
        "exact `verbatim_context_line` copied character-for-character from inside that claim's CONTEXT_BLOCK.",
        "",
    ]
    for c in claims:
        st = c["solver_step"]
        oc = c["outcome"]
        sig = c["consistency_signals"]
        qc = c["sheet_quote_check"]
        lines.extend(
            [
                f"=== CLAIM {c['claim_id']} | episode={c['episode']} | t={c['t']} | kind={c['kind']} ===",
                f"CLAIM_TEXT: {c['claim']}",
                f"SHEET_QUOTE_VERIFIED: {qc['verified']} (mode={qc['match_mode']})",
                (
                    f"PARSED_SOLVER_AT_STEP_T: t={st['t']} day={st['day']} tool={st['tool']} "
                    f"target={st['target_employee']} regret={st['regret']:.3f} tags={st['tags']} "
                    f"top={st['top_employee']}:{st['top_prob']} mole_prob={st['mole_prob']} "
                    f"true_mole={oc.get('true_mole')} correct={oc.get('correct')} "
                    f"rationale_source={oc.get('rationale')} "
                    f"accused_matches_solver_top={sig['accused_matches_solver_top']} "
                    f"solver_top_is_innocent={sig['solver_top_is_innocent']} "
                    f"solver_never_accuses_at_top_prob={sig['solver_never_accuses_at_top_prob']}"
                ),
                "CONTEXT_BLOCK:",
                c["clean_block"],
                "",
            ]
        )
    return "\n".join(lines)


def verify_auditor_quote(claim_rec: dict[str, Any], raw_quote: Any) -> dict[str, Any]:
    cid = int(claim_rec["claim_id"])
    q = str(raw_quote or "").strip()
    if len(q) < 16 or "\n" in q or "\r" in q:
        return {
            "claim_id": cid,
            "quote": sanitize_text(q),
            "verified": False,
            "matched_line": None,
            "exact_line": False,
            "reason": "invalid_quote_length_or_newline",
        }
    if "\u2014" in q or "\u2013" in q:
        return {
            "claim_id": cid,
            "quote": sanitize_text(q),
            "verified": False,
            "matched_line": None,
            "exact_line": False,
            "reason": "contains_unicode_dash",
        }
    if q.startswith("=== EPISODE"):
        return {
            "claim_id": cid,
            "quote": sanitize_text(q),
            "verified": False,
            "matched_line": None,
            "exact_line": False,
            "reason": "episode_banner_not_allowed",
        }
    clean_blk = claim_rec["clean_block"]
    for ln in clean_blk.splitlines():
        if ln.startswith("=== EPISODE"):
            continue
        if q in ln:
            return {
                "claim_id": cid,
                "quote": q,
                "verified": True,
                "matched_line": ln,
                "exact_line": (q == ln or q == ln.strip()),
                "reason": "exact_verbatim_match",
            }
    return {
        "claim_id": cid,
        "quote": sanitize_text(q),
        "verified": False,
        "matched_line": None,
        "exact_line": False,
        "reason": "substring_not_in_context_block",
    }


def verify_audit_payload(payload: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c["claim_id"]: c for c in claims}
    raw_audits = payload.get("audits") if isinstance(payload.get("audits"), list) else []

    seen_ids: set[int] = set()
    duplicate_ids: list[int] = []
    invalid_verdicts: list[int] = []
    audited_by_id: dict[int, dict[str, Any]] = {}
    quote_checks: list[dict[str, Any]] = []

    for entry in raw_audits:
        if not isinstance(entry, dict):
            continue
        raw_cid = entry.get("claim_id")
        if not isinstance(raw_cid, int) or isinstance(raw_cid, bool) or raw_cid not in by_id:
            continue
        if raw_cid in seen_ids:
            duplicate_ids.append(raw_cid)
            continue
        seen_ids.add(raw_cid)

        verdict = str(entry.get("verdict") or "").strip().lower()
        if verdict not in VERDICT_ENUM:
            invalid_verdicts.append(raw_cid)
            verdict = "unsure"

        over_flag = bool(entry.get("overclaim_flag", False))
        over_type = str(entry.get("overclaim_type") or "none").strip()
        if over_type not in OVERCLAIM_TYPE_ENUM:
            over_type = "magnitude_or_mechanism_exaggeration" if over_flag else "none"
        if not over_flag:
            over_type = "none"
        elif over_type == "none":
            over_type = "magnitude_or_mechanism_exaggeration"

        q_chk = verify_auditor_quote(by_id[raw_cid], entry.get("verbatim_context_line", ""))
        quote_checks.append(q_chk)

        audited_by_id[raw_cid] = {
            "claim_id": raw_cid,
            "verdict": verdict,
            "overclaim_flag": over_flag,
            "overclaim_type": over_type,
            "rationale": sanitize_text(entry.get("rationale", "")).strip(),
            "verbatim_context_line": q_chk["quote"],
            "quote_check": q_chk,
        }

    missing_ids = [c["claim_id"] for c in claims if c["claim_id"] not in seen_ids]
    total_quotes = len(claims)
    verified_quotes = sum(
        1 for c in claims if c["claim_id"] in audited_by_id and audited_by_id[c["claim_id"]]["quote_check"]["verified"]
    )
    unverified_quotes = total_quotes - verified_quotes
    pct = round(100.0 * verified_quotes / total_quotes, 2) if total_quotes > 0 else 100.0

    merged_rows: list[dict[str, Any]] = []
    for c in claims:
        cid = c["claim_id"]
        aud = audited_by_id.get(cid)
        if aud is None:
            aud = {
                "claim_id": cid,
                "verdict": "unsure",
                "overclaim_flag": False,
                "overclaim_type": "none",
                "rationale": "Missing audit row.",
                "verbatim_context_line": "",
                "quote_check": {
                    "claim_id": cid,
                    "quote": "",
                    "verified": False,
                    "matched_line": None,
                    "exact_line": False,
                    "reason": "missing_claim_audit",
                },
            }
        merged_rows.append(
            {
                "claim_id": cid,
                "kind": c["kind"],
                "episode": c["episode"],
                "t": c["t"],
                "claim": c["claim"],
                "sheet_quote": c["sheet_quote"],
                "sheet_quote_check": c["sheet_quote_check"],
                "outcome": c["outcome"],
                "solver_step": c["solver_step"],
                "consistency_signals": c["consistency_signals"],
                "verdict": aud["verdict"],
                "overclaim_flag": aud["overclaim_flag"],
                "overclaim_type": aud["overclaim_type"],
                "rationale": aud["rationale"],
                "verbatim_context_line": aud["verbatim_context_line"],
                "quote_verified": aud["quote_check"]["verified"],
                "quote_check": aud["quote_check"],
            }
        )

    v_counts = Counter(r["verdict"] for r in merged_rows)
    agree_n = int(v_counts.get("agree", 0))
    disagree_n = int(v_counts.get("disagree", 0))
    unsure_n = int(v_counts.get("unsure", 0))
    scored_n = agree_n + disagree_n
    agreement_rate = round(agree_n / scored_n, 4) if scored_n > 0 else 0.0
    strict_agree_rate = round(agree_n / len(claims), 4) if claims else 0.0
    overclaim_n = sum(1 for r in merged_rows if r["overclaim_flag"])

    by_kind: dict[str, dict[str, Any]] = {}
    for k in CLAIM_KINDS:
        sub = [r for r in merged_rows if r["kind"] == k]
        if not sub:
            continue
        ka = sum(1 for r in sub if r["verdict"] == "agree")
        kd = sum(1 for r in sub if r["verdict"] == "disagree")
        ku = sum(1 for r in sub if r["verdict"] == "unsure")
        ko = sum(1 for r in sub if r["overclaim_flag"])
        ks = ka + kd
        by_kind[k] = {
            "n": len(sub),
            "agree": ka,
            "disagree": kd,
            "unsure": ku,
            "overclaims_flagged": ko,
            "agreement_rate": round(ka / ks, 4) if ks > 0 else 0.0,
        }

    overclaim_type_counts = Counter(r["overclaim_type"] for r in merged_rows if r["overclaim_flag"])

    return {
        "executive_summary": sanitize_text(payload.get("executive_summary", "")).strip(),
        "claims": merged_rows,
        "missing_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
        "invalid_verdicts": invalid_verdicts,
        "counts": {
            "n_claims": len(claims),
            "agree": agree_n,
            "disagree": disagree_n,
            "unsure": unsure_n,
            "scored": scored_n,
            "agreement_rate": agreement_rate,
            "strict_agree_rate": strict_agree_rate,
            "overclaims_flagged": overclaim_n,
            "by_kind": by_kind,
            "by_overclaim_type": dict(sorted(overclaim_type_counts.items())),
        },
        "quote_verification": {
            "total_quotes": total_quotes,
            "verified_quotes": verified_quotes,
            "unverified_quotes": unverified_quotes,
            "verified_quotes_pct": pct,
            "checks": quote_checks,
        },
    }


def build_repair_prompt(verified: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    by_id = {c["claim_id"]: c for c in claims}
    lines = [
        "Your previous JSON response failed strict deterministic verification in Python.",
        "Fix ALL issues listed below and return the complete corrected JSON for all claims:",
    ]
    if verified["missing_ids"]:
        lines.append("Missing claim_ids: " + ", ".join(str(i) for i in verified["missing_ids"]))
    if verified["duplicate_ids"]:
        lines.append("Duplicate claim_ids: " + ", ".join(str(i) for i in verified["duplicate_ids"]))
    if verified["invalid_verdicts"]:
        lines.append("Invalid verdicts on claim_ids: " + ", ".join(str(i) for i in verified["invalid_verdicts"]))

    for row in verified["claims"]:
        qc = row["quote_check"]
        if qc["verified"]:
            continue
        cid = row["claim_id"]
        c_rec = by_id[cid]
        cand_lines = [
            ln for ln in c_rec["clean_block"].splitlines() if not ln.startswith("=== EPISODE") and len(ln.strip()) >= 20
        ]
        marked = [ln for ln in cand_lines if ln.startswith(">>> ")]
        sample = marked + [ln for ln in cand_lines if not ln.startswith(">>> ")][:2]
        lines.append(
            f"- Claim {cid} ({c_rec['episode']} t={c_rec['t']}): reason={qc['reason']}, "
            f"submitted={qc['quote']!r}"
        )
        lines.append("  Valid verbatim lines to copy from Claim " + str(cid) + ": " + " || ".join(sample))

    lines.append(
        "Remember: copy ONE exact single-line string (for example the '>>> t...' line) character-for-character "
        "from each claim's CONTEXT_BLOCK, include every claim_id exactly once, and use plain ASCII '-' only."
    )
    return "\n".join(lines)


def build_stub_audit_payload(claims: list[dict[str, Any]]) -> dict[str, Any]:
    audits: list[dict[str, Any]] = []
    for c in claims:
        st = c["solver_step"]
        oc = c["outcome"]
        sig = c["consistency_signals"]
        claim_low = c["claim"].lower()

        verdict = "agree"
        over_flag = False
        over_type = "none"
        rationale = (
            f"Solver at t={st['t']} d{st['day']} records REGRET={st['regret']:.3f} tags={st['tags']} "
            f"with top={st['top_employee']}:{st['top_prob']} and mole={st['mole_prob']}, consistent with the claim."
        )

        if c["kind"] == "counterfactual" and sig["solver_never_accuses_at_top_prob"] and "would accuse" in claim_low:
            verdict = "disagree"
            over_flag = True
            over_type = "false_solver_counterfactual"
            rationale = (
                f"At top={st['top_employee']}:{st['top_prob']} (<= 0.50), EV(accuse) is negative so SolverPolicy "
                f"abstains rather than accusing {st['top_employee']}."
            )
        elif (
            st["tool"] == "accuse"
            and sig["accused_matches_solver_top"] is True
            and sig["solver_top_is_innocent"]
            and st["top_prob"] is not None
            and st["top_prob"] >= 0.60
        ):
            verdict = "disagree"
            over_flag = True
            over_type = "evidence_backed_framing_luck"
            rationale = (
                f"Exact Bayesian solver also ranked {st['top_employee']} first at {st['top_prob']:.2f} "
                f"(true mole {oc.get('true_mole')} at {st['mole_prob']:.2f}); wrong accusation reflects "
                f"adversarial framing/noise luck plus {st['regret']:.3f} stopping regret, not miscalculation."
            )
        elif sig["rationale_none"] and "noisy access logs" in claim_low:
            verdict = "unsure"
            over_flag = True
            over_type = "unverified_mental_state_without_rationale"
            rationale = (
                f"Solver tags {st['tags']} confirm REGRET={st['regret']:.3f} with top={st['top_employee']}:{st['top_prob']}, "
                "but rationale=none leaves noisy-log mental attribution unverified."
            )

        audits.append(
            {
                "claim_id": c["claim_id"],
                "verdict": verdict,
                "overclaim_flag": over_flag,
                "overclaim_type": over_type,
                "rationale": rationale,
                "verbatim_context_line": st["raw_line"],
            }
        )

    return {
        "executive_summary": (
            f"Stub audit evaluated {len(claims)} Failure Atlas claims against deterministic solver states "
            "and verified verbatim context lines."
        ),
        "audits": audits,
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
        "in": tin,
        "out": out_tokens,
        "thinking": thinking,
        "cached": cached,
        "cost_usd": round(usd, 6),
        "calls": 1,
        "latency_s": round(elapsed_s, 3),
    }


def _merge_usage(acc: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "in": int(acc.get("in", 0)) + int(delta.get("in", 0)),
        "out": int(acc.get("out", 0)) + int(delta.get("out", 0)),
        "thinking": int(acc.get("thinking", 0)) + int(delta.get("thinking", 0)),
        "cached": int(acc.get("cached", 0)) + int(delta.get("cached", 0)),
        "cost_usd": round(float(acc.get("cost_usd", 0.0)) + float(delta.get("cost_usd", 0.0)), 6),
        "calls": int(acc.get("calls", 0)) + int(delta.get("calls", 0)),
        "latency_s": round(float(acc.get("latency_s", 0.0)) + float(delta.get("latency_s", 0.0)), 3),
    }


def _md_cell(val: Any) -> str:
    txt = sanitize_text(val).replace("\r", " ").replace("\n", " ").strip()
    return txt.replace("|", "\\|")


def render_summary_md(meta: dict[str, Any], audit_doc: dict[str, Any]) -> str:
    u = meta["usage"]
    det = audit_doc["deterministic_verification"]
    cnt = audit_doc["auditor_summary"]
    qv = audit_doc["quote_verification"]

    lines: list[str] = [
        f"{H1} Role 4 ({meta['role']}) - Independent Failure Atlas Claim & Counterfactual Audit ({meta['model_id']})",
        "",
        f"> **Auditor Disclosure:** `{meta['auditor']}`",
        "> Human validation rows in `docs/gemini/validation.md` belong exclusively to human labeller Ivar and are NOT modified by this automated audit.",
        "",
        f"{H2} Provenance & Audit Headline",
        "",
        f"- **Role / Subrole:** `{meta['role']}` / `{meta['subrole']}`",
        f"- **Auditor:** `{meta['auditor']}`",
        f"- **Model & Thinking Level:** `{meta['model_id']}` (`thinking_level={meta['thinking_level']}`, `source={meta['source']}`, `stub={meta['stub']}`)",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Inputs (read-only):** `{meta['validation_sheet']}`, `{meta['validation_context']}`",
        f"- **Deterministic pre-audit checks:** `{det['sheet_quotes_verified']}/{det['n_claims']}` (`{det['sheet_quotes_verified_pct']:.1f}%`) sheet quotes verified in context; `{det['marked_steps_matched']}/{det['n_claims']}` `>>>` solver step markers parsed",
        f"- **Automated LLM verdicts (`n={meta['n_claims']}`):** `{meta['agree']}` agree, `{meta['disagree']}` disagree, `{meta['unsure']}` unsure (`agreement_rate={meta['agreement_rate'] * 100.0:.1f}%` on scored agree+disagree; `{meta['strict_agree_rate'] * 100.0:.1f}%` strict agree/total)",
        f"- **Over-claims / solver-inconsistencies flagged:** `{meta['overclaims_flagged']}/{meta['n_claims']}`",
        f"- **Auditor verbatim context quote verification:** `{qv['verified_quotes']}/{qv['total_quotes']}` (`{meta['verified_quotes_pct']:.1f}%` exact line/substring match in Python)",
        f"- **Gemini API telemetry:** `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd=${u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}s`",
        "",
        f"{H2} Executive Synthesis (`{meta['model_id']}`, `thinking_level={meta['thinking_level']}`)",
        "",
        cnt["executive_summary"],
        "",
        f"{H2} Breakdown by Atlas Claim Category",
        "",
        "| Claim Kind | Total | Agree | Disagree | Unsure | Scored Agreement | Over-Claims Flagged |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for k in CLAIM_KINDS:
        bk = cnt["by_kind"].get(k)
        if not bk:
            continue
        lines.append(
            f"| `{k}` | {bk['n']} | {bk['agree']} | {bk['disagree']} | {bk['unsure']} | "
            f"{bk['agreement_rate'] * 100.0:.1f}% | {bk['overclaims_flagged']} |"
        )

    flagged = [r for r in audit_doc["claims"] if r["verdict"] != "agree" or r["overclaim_flag"]]
    if flagged:
        lines.extend(
            [
                "",
                f"{H2} Flagged Over-Claims & Disagreements",
                "",
            ]
        )
        for r in flagged:
            st = r["solver_step"]
            oc = r["outcome"]
            lines.extend(
                [
                    f"{H3} Claim {r['claim_id']}: `{r['episode']}` `t={r['t']}` (`{r['kind']}`) - `{r['verdict'].upper()}` (`overclaim={r['overclaim_type']}`)",
                    f"- **Atlas claim:** {_md_cell(r['claim'])}",
                    f"- **Exact solver state at `>>> t={st['t']}`:** `d{st['day']} {st['tool']}` | `REGRET {st['regret']:.3f}` `tags={st['tags']}` | `top={st['top_employee']}:{st['top_prob']}` | `mole={st['mole_prob']}` (`true_mole={oc.get('true_mole')}`, `accused={oc.get('accused')}`, `rationale={oc.get('rationale')}`)",
                    f"- **Auditor rationale:** {_md_cell(r['rationale'])}",
                    f"- **Verified verbatim context line:** `{_md_cell(r['verbatim_context_line'])}`",
                    "",
                ]
            )

    lines.extend(
        [
            f"{H2} Full 30-Claim Independent Audit Ledger",
            "",
            "| ID | Kind | Episode | t | Solver Top / Mole | Regret & Tags | Verdict | Over-Claim | Auditor Rationale | Verified Context Quote |",
            "| ---: | --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for r in audit_doc["claims"]:
        st = r["solver_step"]
        tags_s = ",".join(st["tags"]) if st["tags"] else "none"
        belief_s = f"`{st['top_employee']}:{st['top_prob']}` / `mole:{st['mole_prob']}`"
        reg_s = f"`{st['regret']:.3f}` (`{tags_s}`)"
        oc_s = f"`{r['overclaim_type']}`" if r["overclaim_flag"] else "`none`"
        lines.append(
            f"| {r['claim_id']} | `{r['kind']}` | `{_md_cell(r['episode'])}` | {r['t']} | {belief_s} | "
            f"{reg_s} | **{r['verdict']}** | {oc_s} | {_md_cell(r['rationale'])} | "
            f"`{_md_cell(r['verbatim_context_line'])}` |"
        )

    lines.append("")
    return sanitize_text("\n".join(lines))


EXEC_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": (
                "Unified quantitative synthesis (120 to 900 chars) of the 30-claim Failure Atlas audit, "
                "summarizing overall agreement, breakdown by claim kind, and specific solver-inconsistency "
                "or framing-luck over-claims uncovered. Plain ASCII hyphens only."
            ),
        },
    },
    "required": ["executive_summary"],
}


def _log_progress(msg: str) -> None:
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except OSError:
        pass


def build_synthesis_prompt(verified_all: dict[str, Any]) -> str:
    cnt = verified_all["counts"]
    flagged = [r for r in verified_all["claims"] if r["verdict"] != "agree" or r["overclaim_flag"]]
    lines = [
        "Synthesize the completed 30-claim Failure Atlas audit into one cohesive executive_summary.",
        (
            f"COUNTS: n_claims={cnt['n_claims']} agree={cnt['agree']} disagree={cnt['disagree']} "
            f"unsure={cnt['unsure']} scored_agreement_rate={cnt['agreement_rate']:.4f} "
            f"overclaims_flagged={cnt['overclaims_flagged']}"
        ),
        f"BY_KIND: {json.dumps(cnt['by_kind'], separators=(',', ':'))}",
        f"BY_OVERCLAIM_TYPE: {json.dumps(cnt['by_overclaim_type'], separators=(',', ':'))}",
        "FLAGGED_OR_DISAGREED_CLAIMS:",
    ]
    for r in flagged:
        st = r["solver_step"]
        lines.append(
            f"- Claim {r['claim_id']} ({r['episode']} t={r['t']} {r['kind']}): verdict={r['verdict']} "
            f"overclaim={r['overclaim_type']} solver_top={st['top_employee']}:{st['top_prob']} "
            f"mole={st['mole_prob']} regret={st['regret']:.3f} rationale={r['rationale']}"
        )
    lines.append("Use plain ASCII hyphens only (never em or en dashes) and cite exact counts from COUNTS.")
    return "\n".join(lines)


def run_claim_audit(
    *,
    sheet_path: str | Path = DEFAULT_SHEET_PATH,
    context_path: str | Path = DEFAULT_CONTEXT_PATH,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    model_id: str = DEFAULT_MODEL,
    thinking_level: str = DEFAULT_THINKING_LEVEL,
    stub: bool = False,
    batch_size: int | None = None,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    max_repair_retries: int = 2,
    client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    s_path = Path(sheet_path)
    c_path = Path(context_path)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    claims = load_and_verify_claims(s_path, c_path)

    sheet_quotes_ok = sum(1 for c in claims if c["sheet_quote_check"]["verified"])
    sheet_quotes_pct = round(100.0 * sheet_quotes_ok / len(claims), 2) if claims else 100.0
    steps_matched = sum(1 for c in claims if c["consistency_signals"]["step_t_matches"])

    eff_batch = (
        max(1, int(batch_size))
        if batch_size is not None
        else (max(1, len(claims)) if (stub or client is not None) else DEFAULT_BATCH_SIZE)
    )
    batches = [claims[i : i + eff_batch] for i in range(0, len(claims), eff_batch)]

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    commit = current_git_commit()
    effective_model = "stub" if stub else model_id
    effective_thinking = "none" if stub else (thinking_level or DEFAULT_THINKING_LEVEL)
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or (
        f"{FEATURE}:{effective_model}:{ts.strftime('%Y%m%dT%H%M%SZ')}"
    )

    if client is None:
        if stub:
            script_name = f"claim_audit_stub_{int(time.time() * 1000)}_{os.getpid()}"
            stub_turns: list[dict[str, Any]] = [
                {"json": build_stub_audit_payload(b_claims)} for b_claims in batches
            ]
            if len(batches) > 1:
                stub_turns.append(
                    {
                        "json": {
                            "executive_summary": (
                                f"Stub multi-batch audit evaluated {len(claims)} Failure Atlas claims across "
                                f"{len(batches)} batches with 100% verified verbatim context quotes."
                            )
                        }
                    }
                )
            register_script(script_name, stub_turns)
            client = lab_client(f"stub:{script_name}", feature=FEATURE, run_id=run_id)
        else:
            spec = model_id if ":" in model_id else f"gemini:{model_id}"
            client = lab_client(
                spec,
                feature=FEATURE,
                run_id=run_id,
                thinking_level=effective_thinking,
                sdk_client=genai_client(timeout_s=request_timeout_s),
            )

    usage_totals: dict[str, Any] = {
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "cost_usd": 0.0,
        "calls": 0,
        "latency_s": 0.0,
    }

    combined_raw_audits: list[dict[str, Any]] = []
    batch_summaries: list[str] = []

    for b_idx, b_claims in enumerate(batches, start=1):
        user_prompt = build_user_prompt(b_claims)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        t0 = time.time()
        resp = client.chat(messages, temperature=0.0, response_schema=CLAIM_AUDIT_SCHEMA)
        delta_u = _extract_call_usage(resp, time.time() - t0)
        usage_totals = _merge_usage(usage_totals, delta_u)
        raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
        provider_items = resp.get("provider_items") if isinstance(resp, dict) else getattr(resp, "provider_items", None)
        parsed = json.loads(raw_text or "{}")
        b_verified = verify_audit_payload(parsed, b_claims)

        attempt = 0
        while attempt < max_repair_retries and (
            b_verified["quote_verification"]["unverified_quotes"] > 0
            or len(b_verified["missing_ids"]) > 0
            or len(b_verified["duplicate_ids"]) > 0
            or len(b_verified["invalid_verdicts"]) > 0
        ):
            attempt += 1
            asst_msg: dict[str, Any] = {"role": "assistant", "content": raw_text}
            if provider_items:
                asst_msg["provider_items"] = provider_items
            messages.append(asst_msg)
            messages.append({"role": "user", "content": build_repair_prompt(b_verified, b_claims)})
            t1 = time.time()
            resp = client.chat(messages, temperature=0.0, response_schema=CLAIM_AUDIT_SCHEMA)
            usage_totals = _merge_usage(usage_totals, _extract_call_usage(resp, time.time() - t1))
            raw_text = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
            provider_items = (
                resp.get("provider_items") if isinstance(resp, dict) else getattr(resp, "provider_items", None)
            )
            parsed = json.loads(raw_text or "{}")
            b_verified = verify_audit_payload(parsed, b_claims)

        if b_verified["executive_summary"]:
            batch_summaries.append(b_verified["executive_summary"])
        for row in b_verified["claims"]:
            combined_raw_audits.append(
                {
                    "claim_id": row["claim_id"],
                    "verdict": row["verdict"],
                    "overclaim_flag": row["overclaim_flag"],
                    "overclaim_type": row["overclaim_type"],
                    "rationale": row["rationale"],
                    "verbatim_context_line": row["verbatim_context_line"],
                }
            )
        _log_progress(
            f"[claim_audit batch {b_idx}/{len(batches)}] claims {b_claims[0]['claim_id']}..{b_claims[-1]['claim_id']} "
            f"quotes={b_verified['quote_verification']['verified_quotes']}/{len(b_claims)} "
            f"calls={usage_totals['calls']} latency={usage_totals['latency_s']:.1f}s"
        )

    exec_summary = " ".join(batch_summaries).strip()
    verified = verify_audit_payload(
        {"executive_summary": exec_summary, "audits": combined_raw_audits},
        claims,
    )

    if len(batches) > 1:
        synth_messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_synthesis_prompt(verified)},
        ]
        ts_syn = time.time()
        syn_resp = client.chat(synth_messages, temperature=0.0, response_schema=EXEC_SUMMARY_SCHEMA)
        usage_totals = _merge_usage(usage_totals, _extract_call_usage(syn_resp, time.time() - ts_syn))
        syn_text = syn_resp["text"] if isinstance(syn_resp, dict) else getattr(syn_resp, "text", "")
        syn_parsed = json.loads(syn_text or "{}")
        if isinstance(syn_parsed.get("executive_summary"), str) and syn_parsed["executive_summary"].strip():
            verified["executive_summary"] = sanitize_text(syn_parsed["executive_summary"]).strip()

    qv = verified["quote_verification"]
    cnt = verified["counts"]

    try:
        sheet_rel = s_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        sheet_rel = s_path.as_posix()
    try:
        ctx_rel = c_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        ctx_rel = c_path.as_posix()

    default_cmd = "PYTHONPATH=. " + " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    cmd_clean = sanitize_text(command_str or default_cmd)

    key_metric = sanitize_text(
        f"{cnt['n_claims']}/{cnt['n_claims']} atlas claims audited (automated LLM, not human): "
        f"{cnt['agree']} agree, {cnt['disagree']} disagree, {cnt['unsure']} unsure "
        f"({cnt['agreement_rate'] * 100.0:.1f}% scored agreement, "
        f"{cnt['overclaims_flagged']} over-claims flagged, "
        f"{qv['verified_quotes_pct']:.0f}% verified quotes)"
    )

    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "commit": commit,
        "git_sha": commit,
        "timestamp": ts_iso,
        "command": cmd_clean,
        "ledger_run_id": run_id,
        "stub": bool(stub),
        "fake_env": False,
        "smoke": False,
        "source": "stub" if stub else "llm",
        "auditor": "stub (automated test audit, not human)" if stub else AUDITOR_LABEL,
        "thinking_level": effective_thinking,
        "validation_sheet": sheet_rel,
        "validation_context": ctx_rel,
        "n_episodes_packed": cnt["n_claims"],
        "n_claims": cnt["n_claims"],
        "agree": cnt["agree"],
        "disagree": cnt["disagree"],
        "unsure": cnt["unsure"],
        "agreement_rate": cnt["agreement_rate"],
        "strict_agree_rate": cnt["strict_agree_rate"],
        "overclaims_flagged": cnt["overclaims_flagged"],
        "sheet_quotes_verified": sheet_quotes_ok,
        "sheet_quotes_verified_pct": sheet_quotes_pct,
        "total_quotes": qv["total_quotes"],
        "verified_quotes": qv["verified_quotes"],
        "verified_quotes_pct": qv["verified_quotes_pct"],
        "by_kind": cnt["by_kind"],
        "key_metric": key_metric,
        "usage": usage_totals,
    }
    if stub:
        meta["provider"] = "stub"

    deterministic_summary = {
        "n_claims": len(claims),
        "sheet_quotes_verified": sheet_quotes_ok,
        "sheet_quotes_verified_pct": sheet_quotes_pct,
        "marked_steps_matched": steps_matched,
        "human_sheet_modified": False,
    }

    audit_doc: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": effective_model,
        "thinking_level": effective_thinking,
        "commit": commit,
        "timestamp": ts_iso,
        "source": meta["source"],
        "stub": bool(stub),
        "auditor": meta["auditor"],
        "disclosure": (
            "Independent automated LLM claim and solver-consistency audit over docs/gemini/validation.md "
            "and docs/gemini/validation_context.md. Human validation in docs/gemini/validation.md belongs "
            "exclusively to human labeller Ivar and was left completely untouched."
        ),
        "deterministic_verification": deterministic_summary,
        "auditor_summary": {
            "n_claims": cnt["n_claims"],
            "agree": cnt["agree"],
            "disagree": cnt["disagree"],
            "unsure": cnt["unsure"],
            "agreement_rate": cnt["agreement_rate"],
            "strict_agree_rate": cnt["strict_agree_rate"],
            "overclaims_flagged": cnt["overclaims_flagged"],
            "by_kind": cnt["by_kind"],
            "by_overclaim_type": cnt["by_overclaim_type"],
            "executive_summary": verified["executive_summary"],
        },
        "quote_verification": qv,
        "usage": usage_totals,
        "claims": verified["claims"],
    }

    (out_path / "meta.json").write_text(sanitize_text(json.dumps(meta, indent=2) + "\n"), encoding="utf-8")
    (out_path / "audit.json").write_text(sanitize_text(json.dumps(audit_doc, indent=2) + "\n"), encoding="utf-8")
    (out_path / "summary.md").write_text(render_summary_md(meta, audit_doc), encoding="utf-8")

    return {"meta": meta, "audit": audit_doc, "claims": claims}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run independent gemini-4-carbon claim and counterfactual audit over Atlas validation claims."
    )
    ap.add_argument("--sheet", type=Path, default=DEFAULT_SHEET_PATH)
    ap.add_argument("--context", type=Path, default=DEFAULT_CONTEXT_PATH)
    ap.add_argument("--out", "--out-dir", dest="out_dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thinking-level", default=DEFAULT_THINKING_LEVEL)
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--request-timeout-s", "--timeout-s", dest="request_timeout_s", type=float, default=DEFAULT_REQUEST_TIMEOUT_S)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--max-repair-retries", type=int, default=2)
    args = ap.parse_args(argv)

    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd_parts = ["PYTHONPATH=.", shlex.quote(sys.executable), "scripts/run_claim_audit_carbon.py"] + [
        shlex.quote(x) for x in raw_argv
    ]
    cmd_str = " ".join(cmd_parts)

    res = run_claim_audit(
        sheet_path=args.sheet,
        context_path=args.context,
        out_dir=args.out_dir,
        model_id=args.model,
        thinking_level=args.thinking_level,
        stub=args.stub,
        batch_size=args.batch_size,
        request_timeout_s=args.request_timeout_s,
        max_repair_retries=args.max_repair_retries,
        command_str=cmd_str,
    )
    m = res["meta"]
    u = m["usage"]
    print(
        f"claim_audit_carbon: claims={m['n_claims']} agree={m['agree']} disagree={m['disagree']} "
        f"unsure={m['unsure']} rate={m['agreement_rate']:.4f} overclaims={m['overclaims_flagged']} "
        f"quotes={m['verified_quotes']}/{m['total_quotes']} ({m['verified_quotes_pct']:.1f}%) "
        f"in={u['in']} out={u['out']} thinking={u['thinking']} cost=${u['cost_usd']:.6f}"
    )
    if not args.stub and (
        m["verified_quotes_pct"] < 100.0
        or m["sheet_quotes_verified_pct"] < 100.0
        or len(res["audit"]["claims"]) != m["n_claims"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
