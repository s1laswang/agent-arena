from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.rules import TIERS
from canary.solver import SolverPolicy
from canary.types import Step
from train.render import tool_content

SCHEMA_VERSION = "tiebreak_forensics_v1"
MAX_JSON_BYTES = 90 * 1024
DEFAULT_J4_DIR = Path("/home/silas/agent-arena-data/j4")
DEFAULT_V3_DIR = Path("/home/silas/agent-arena-data/v3")
DEFAULT_VERDA_GIT_SPEC = "origin/justSilas-fr8:data/fr8/verda/run-verda-s0/curve.jsonl"
DEFAULT_VERDA_LOCAL_CURVE = Path("data/fr8/verda/run-verda-s0/curve.jsonl")
DEFAULT_OUT_JSON = Path("results/tiebreak/forensics_prior_runs.json")
DEFAULT_OUT_MD = Path("results/tiebreak/forensics_prior_runs.md")
CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")

DEFAULT_HEADER_TOKENS = 2842
DEFAULT_MAX_LEN = 4096
DEFAULT_CHARS_PER_TOKEN = 4.0

_SECRET_RE = re.compile(r"fresh per-process secret \(sha256 ([0-9a-fA-F]+)\)")
_EP_LINE_RE = re.compile(
    r"^\[ep\]\s+(easy|medium|hard)\s+(\d+)\s+score=([-0-9.]+)\s+correct=(True|False)\s+steps=(\d+)\s+invalid=(\d+)\s+t=(\d+)s"
)
_TRAIN_DICT_RE = re.compile(r"^\[train\]\s+(\{.*\})\s*$")
_SUMMARY_JSON_RE = re.compile(r"^\[summary\]\s+(\{.*\})\s*$")
_TIMEBOX_RE = re.compile(r"^\[train\]\s+time box hit at step\s+(\d+)")
_CANCEL_RE = re.compile(r"CANCELLED AT\s+([0-9T:-]+)\s+DUE\s+(?:TO|to)\s+(.+?)\s*\*\*\*")
_OOM_STEP_RE = re.compile(r"Detected\s+(\d+)\s+oom_kill event in StepId=([^\s.]+)")
_CUDA_OOM_RE = re.compile(
    r"CUDA out of memory\.\s+Tried to allocate\s+([0-9.]+)\s+GiB\.\s+"
    r"GPU \d+ has a total capacity of\s+([0-9.]+)\s+GiB of which\s+([0-9.]+)\s+GiB is free\.\s+"
    r"Including non-PyTorch memory, this process has\s+([0-9.]+)\s+GiB memory in use\.\s+"
    r"Of the allocated memory\s+([0-9.]+)\s+GiB is allocated by PyTorch,\s+and\s+([0-9.]+)\s+GiB is reserved"
)
_V3_HDR_RE = re.compile(r"adapter=(\S+)\s+seed=(\d+)\s+out=(\S+)")
_V3_STATES_RE = re.compile(r"\[v3\]\s+(\d+)\s+states from TRAIN seeds\s+(\d+)\+\s+tiers=(\[[^\]]+\])")
_TRAINABLE_RE = re.compile(
    r"trainable params:\s*([0-9,]+)\s*\|\|\s*all params:\s*([0-9,]+)\s*\|\|\s*trainable%:\s*([0-9.]+)"
)
_HEADER_BUDGET_RE = re.compile(r"header\(system\+tools\+kickoff\)=(\d+)\s+tokens,\s+body budget=(\d+)")


def mean_ci95(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean_val = sum(values) / n
    if n == 1:
        return mean_val, 0.0
    var = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    ci = 1.96 * math.sqrt(var) / math.sqrt(n)
    return mean_val, ci


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def summarize_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    def _agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(subset)
        if n == 0:
            return {
                "n": 0,
                "mean_score": 0.0,
                "ci95": 0.0,
                "accused_count": 0,
                "accused_rate": 0.0,
                "correct_count": 0,
                "accuracy": 0.0,
                "precision_when_accused": 0.0,
                "abstain_count": 0,
                "abstain_rate": 0.0,
                "total_steps": 0,
                "invalid_calls": 0,
                "invalid_call_rate": 0.0,
                "parse_valid_call_rate": 0.0,
                "env_ok_step_rate": 0.0,
                "mean_final_day": 0.0,
                "end_reasons": {},
            }
        scores = [float(ep.get("score", 0.0)) for ep in subset]
        mean_score, ci95 = mean_ci95(scores)
        accused_eps = [
            ep for ep in subset
            if ep.get("end_reason") == "accused" or ep.get("accused") is not None
        ]
        accused_count = len(accused_eps)
        correct_count = sum(1 for ep in subset if bool(ep.get("correct", False)))
        abstain_count = n - accused_count
        total_steps = sum(len(ep.get("steps", [])) for ep in subset)
        invalid_calls = sum(int((ep.get("meta") or {}).get("invalid_calls", 0)) for ep in subset)
        tool_errors = sum(
            1
            for ep in subset
            for st in ep.get("steps", [])
            if not (st.get("result") or {}).get("ok", True)
        )
        inv_rate = invalid_calls / total_steps if total_steps > 0 else 0.0
        parse_valid = 1.0 - inv_rate if total_steps > 0 else 0.0
        env_ok = 1.0 - ((invalid_calls + tool_errors) / total_steps) if total_steps > 0 else 0.0
        final_days = [float(ep.get("final_day", 1.0)) for ep in subset]
        reasons = Counter(str(ep.get("end_reason", "unknown")) for ep in subset)
        return {
            "n": n,
            "mean_score": round(mean_score, 4),
            "ci95": round(ci95, 4),
            "accused_count": accused_count,
            "accused_rate": round(accused_count / n, 4),
            "correct_count": correct_count,
            "accuracy": round(correct_count / n, 4),
            "precision_when_accused": round(correct_count / accused_count, 4) if accused_count > 0 else 0.0,
            "abstain_count": abstain_count,
            "abstain_rate": round(abstain_count / n, 4),
            "total_steps": total_steps,
            "invalid_calls": invalid_calls,
            "invalid_call_rate": round(inv_rate, 4),
            "parse_valid_call_rate": round(parse_valid, 4),
            "env_ok_step_rate": round(env_ok, 4),
            "mean_final_day": round(sum(final_days) / n, 4),
            "end_reasons": dict(sorted(reasons.items())),
        }

    by_tier: dict[str, Any] = {}
    present_tiers = sorted({str(ep.get("tier", "")) for ep in episodes if ep.get("tier")})
    for tier in CANONICAL_TIERS:
        if tier in present_tiers:
            by_tier[tier] = _agg([ep for ep in episodes if ep.get("tier") == tier])
    return {
        "overall": _agg(episodes),
        "by_tier": by_tier,
    }


def render_pair_text(step: dict[str, Any]) -> str:
    call_payload = json.dumps(
        {"name": step["tool"], "arguments": dict(step.get("args") or {})},
        separators=(",", ":"),
        sort_keys=True,
    )
    resp_payload = tool_content(step.get("result") or {})
    return (
        "assistant\n<tool_call>\n"
        + call_payload
        + "\n</tool_call>\nuser\n<tool_response>\n"
        + resp_payload
        + "\n</tool_response>\n"
    )


def estimate_pair_tokens(step: dict[str, Any], chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> float:
    return 4.0 + (len(render_pair_text(step)) / chars_per_token)


def default_instructions_by_tier() -> dict[str, str]:
    return {tier: Env(tier=tier, seed=100_000).instruction() for tier in CANONICAL_TIERS}


def analyze_episode_root_cause(
    ep: dict[str, Any],
    instr_by_tier: dict[str, str],
    header_tokens: int = DEFAULT_HEADER_TOKENS,
    max_len: int = DEFAULT_MAX_LEN,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> dict[str, Any] | None:
    steps = ep.get("steps") or []
    acc_idx: int | None = None
    for idx, st in enumerate(steps):
        if st.get("tool") == "accuse":
            acc_idx = idx
            break
    if acc_idx is None:
        return None

    tier = str(ep["tier"])
    seed = int(ep["seed"])
    accused = ep.get("accused") or (steps[acc_idx].get("args") or {}).get("employee")
    if not isinstance(accused, str) or not accused:
        return None

    prior_steps = steps[:acc_idx]
    body_budget_tokens = max_len - header_tokens
    pair_tokens = [estimate_pair_tokens(st, chars_per_token=chars_per_token) for st in prior_steps]

    used_tokens = 0.0
    keep_start = len(prior_steps)
    for idx in range(len(prior_steps) - 1, -1, -1):
        if used_tokens + pair_tokens[idx] <= body_budget_tokens or keep_start == len(prior_steps):
            used_tokens += pair_tokens[idx]
            keep_start = idx
        else:
            break

    dropped_steps = prior_steps[:keep_start]
    kept_steps = prior_steps[keep_start:]

    pc_total = sum(1 for st in prior_steps if st.get("tool") == "plant_canary")
    pc_dropped = sum(1 for st in dropped_steps if st.get("tool") == "plant_canary")
    le_total = sum(1 for st in prior_steps if st.get("tool") == "list_employees")
    le_dropped = sum(1 for st in dropped_steps if st.get("tool") == "list_employees")
    le_kept = sum(1 for st in kept_steps if st.get("tool") == "list_employees")

    pol = SolverPolicy(params=TIERS[tier])
    pol.reset([], instr_by_tier[tier])
    for st_raw in prior_steps:
        step_obj = Step(
            t=int(st_raw.get("t", 0)),
            day=int(st_raw.get("day", 1)),
            tool=str(st_raw["tool"]),
            args=dict(st_raw.get("args") or {}),
            result=dict(st_raw.get("result") or {}),
        )
        pol._ingest(step_obj)

    if not pol.obs.employees:
        pol.obs.employees = [f"e{i:02d}" for i in range(TIERS[tier].n_employees)]

    post = pol.belief()
    ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
    top_emp, top_p = ranked[0][0], float(ranked[0][1])
    p_accused = float(post.get(accused, 0.0))
    v_known = max(0.0, float(pol.V))
    breakeven_p = 1.0 / (1.0 + v_known)
    ev_accused = p_accused * v_known - (1.0 - p_accused)

    ruled_out_canary = False
    ruled_out_doc_recipients = False
    for fi in pol.obs.feed:
        doc = pol.obs.docs.get(fi.doc_id)
        if doc is None:
            continue
        if doc.recipients and accused not in doc.recipients:
            ruled_out_doc_recipients = True
        if doc.is_canary and fi.variant is not None and doc.variants:
            if doc.variants.get(accused) != fi.variant:
                ruled_out_canary = True

    return {
        "tier": tier,
        "seed": seed,
        "accuse_step_index": acc_idx,
        "final_day": int(ep.get("final_day", 1)),
        "accused": accused,
        "correct": bool(ep.get("correct", False)),
        "score": float(ep.get("score", 0.0)),
        "prior_turns": len(prior_steps),
        "dropped_turns": len(dropped_steps),
        "kept_turns": len(kept_steps),
        "total_prior_est_tokens": round(sum(pair_tokens), 2),
        "kept_est_tokens": round(used_tokens, 2),
        "plant_canary_total": pc_total,
        "plant_canary_dropped": pc_dropped,
        "list_employees_total": le_total,
        "list_employees_dropped": le_dropped,
        "list_employees_visible_at_accuse": le_kept > 0,
        "v_known": round(v_known, 6),
        "breakeven_p": round(breakeven_p, 6),
        "p_full_accused": round(p_accused, 6),
        "top_emp_full": top_emp,
        "top_p_full": round(top_p, 6),
        "accused_is_argmax": accused == top_emp,
        "ev_full_accused": round(ev_accused, 6),
        "below_breakeven": p_accused < breakeven_p,
        "p_le_005": p_accused <= 0.05,
        "ruled_out_by_surfaced_canary": ruled_out_canary,
        "ruled_out_by_surfaced_doc_recipients": ruled_out_doc_recipients,
    }


def analyze_ws4_v2_root_causes(
    episodes: list[dict[str, Any]],
    instr_by_tier: dict[str, str] | None = None,
    header_tokens: int = DEFAULT_HEADER_TOKENS,
    max_len: int = DEFAULT_MAX_LEN,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> dict[str, Any]:
    instructions = instr_by_tier or default_instructions_by_tier()
    per_ep: list[dict[str, Any]] = []
    for ep in episodes:
        rec = analyze_episode_root_cause(
            ep,
            instr_by_tier=instructions,
            header_tokens=header_tokens,
            max_len=max_len,
            chars_per_token=chars_per_token,
        )
        if rec is not None:
            per_ep.append(rec)

    def _summarize_subset(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n_acc = len(rows)
        if n_acc == 0:
            return {
                "accused_episodes": 0,
                "correct_accusations": 0,
                "total_prior_turns": 0,
                "dropped_prior_turns": 0,
                "dropped_prior_turns_frac": 0.0,
                "total_plant_canary_turns": 0,
                "dropped_plant_canary_turns": 0,
                "dropped_plant_canary_frac": 0.0,
                "episodes_with_plant_canary": 0,
                "episodes_with_dropped_plant_canary": 0,
                "total_list_employees_turns": 0,
                "dropped_list_employees_turns": 0,
                "dropped_list_employees_frac": 0.0,
                "episodes_with_list_employees": 0,
                "episodes_with_dropped_list_employees": 0,
                "episodes_missing_employee_roster_at_accuse": 0,
                "below_breakeven_count": 0,
                "below_breakeven_frac": 0.0,
                "p_le_005_count": 0,
                "p_le_005_frac": 0.0,
                "ruled_out_by_surfaced_canary_count": 0,
                "ruled_out_by_surfaced_canary_frac": 0.0,
                "ruled_out_by_surfaced_doc_recipients_count": 0,
                "ruled_out_by_surfaced_doc_recipients_frac": 0.0,
                "accused_is_argmax_count": 0,
                "accused_is_argmax_frac": 0.0,
                "mean_p_full_accused": 0.0,
                "mean_top_p_full": 0.0,
                "mean_breakeven_p": 0.0,
                "mean_ev_full_accused": 0.0,
            }

        tot_prior = sum(r["prior_turns"] for r in rows)
        drop_prior = sum(r["dropped_turns"] for r in rows)
        tot_pc = sum(r["plant_canary_total"] for r in rows)
        drop_pc = sum(r["plant_canary_dropped"] for r in rows)
        eps_pc = sum(1 for r in rows if r["plant_canary_total"] > 0)
        eps_drop_pc = sum(1 for r in rows if r["plant_canary_dropped"] > 0)

        tot_le = sum(r["list_employees_total"] for r in rows)
        drop_le = sum(r["list_employees_dropped"] for r in rows)
        eps_le = sum(1 for r in rows if r["list_employees_total"] > 0)
        eps_drop_le = sum(1 for r in rows if r["list_employees_dropped"] > 0)
        eps_no_roster = sum(1 for r in rows if not r["list_employees_visible_at_accuse"])

        below_be = sum(1 for r in rows if r["below_breakeven"])
        p_le_005 = sum(1 for r in rows if r["p_le_005"])
        ro_canary = sum(1 for r in rows if r["ruled_out_by_surfaced_canary"])
        ro_doc = sum(1 for r in rows if r["ruled_out_by_surfaced_doc_recipients"])
        is_argmax = sum(1 for r in rows if r["accused_is_argmax"])
        correct_acc = sum(1 for r in rows if r["correct"])

        return {
            "accused_episodes": n_acc,
            "correct_accusations": correct_acc,
            "total_prior_turns": tot_prior,
            "dropped_prior_turns": drop_prior,
            "dropped_prior_turns_frac": round(drop_prior / tot_prior, 4) if tot_prior > 0 else 0.0,
            "total_plant_canary_turns": tot_pc,
            "dropped_plant_canary_turns": drop_pc,
            "dropped_plant_canary_frac": round(drop_pc / tot_pc, 4) if tot_pc > 0 else 0.0,
            "episodes_with_plant_canary": eps_pc,
            "episodes_with_dropped_plant_canary": eps_drop_pc,
            "total_list_employees_turns": tot_le,
            "dropped_list_employees_turns": drop_le,
            "dropped_list_employees_frac": round(drop_le / tot_le, 4) if tot_le > 0 else 0.0,
            "episodes_with_list_employees": eps_le,
            "episodes_with_dropped_list_employees": eps_drop_le,
            "episodes_missing_employee_roster_at_accuse": eps_no_roster,
            "below_breakeven_count": below_be,
            "below_breakeven_frac": round(below_be / n_acc, 4),
            "p_le_005_count": p_le_005,
            "p_le_005_frac": round(p_le_005 / n_acc, 4),
            "ruled_out_by_surfaced_canary_count": ro_canary,
            "ruled_out_by_surfaced_canary_frac": round(ro_canary / n_acc, 4),
            "ruled_out_by_surfaced_doc_recipients_count": ro_doc,
            "ruled_out_by_surfaced_doc_recipients_frac": round(ro_doc / n_acc, 4),
            "accused_is_argmax_count": is_argmax,
            "accused_is_argmax_frac": round(is_argmax / n_acc, 4),
            "mean_p_full_accused": round(sum(r["p_full_accused"] for r in rows) / n_acc, 4),
            "mean_top_p_full": round(sum(r["top_p_full"] for r in rows) / n_acc, 4),
            "mean_breakeven_p": round(sum(r["breakeven_p"] for r in rows) / n_acc, 4),
            "mean_ev_full_accused": round(sum(r["ev_full_accused"] for r in rows) / n_acc, 4),
        }

    by_tier = {
        tier: _summarize_subset([r for r in per_ep if r["tier"] == tier])
        for tier in CANONICAL_TIERS
    }
    body_budget = max_len - header_tokens
    return {
        "window_model": {
            "max_len_tokens": max_len,
            "header_tokens": header_tokens,
            "header_frac": round(header_tokens / max_len, 4),
            "body_budget_tokens": body_budget,
            "body_budget_frac": round(body_budget / max_len, 4),
            "chars_per_token": chars_per_token,
        },
        "total_episodes": len(episodes),
        "overall": _summarize_subset(per_ep),
        "by_tier": by_tier,
        "sample_ruled_out_cases": [
            {
                "tier": r["tier"],
                "seed": r["seed"],
                "final_day": r["final_day"],
                "accused": r["accused"],
                "p_full_accused": r["p_full_accused"],
                "top_emp_full": r["top_emp_full"],
                "top_p_full": r["top_p_full"],
                "breakeven_p": r["breakeven_p"],
                "plant_canary_dropped": r["plant_canary_dropped"],
                "plant_canary_total": r["plant_canary_total"],
                "ruled_out_by_surfaced_canary": r["ruled_out_by_surfaced_canary"],
                "ruled_out_by_surfaced_doc_recipients": r["ruled_out_by_surfaced_doc_recipients"],
            }
            for r in per_ep
            if r["p_le_005"]
        ][:8],
    }


def parse_pilot_44200(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    oom_match = _OOM_STEP_RE.search(text)
    killed_line = next((ln.strip() for ln in text.splitlines() if "Killed" in ln), "")
    gpu_line = next((ln.strip() for ln in text.splitlines() if ln.startswith("cuda ")), "")
    return {
        "job_id": 44200,
        "stage": "J4 pilot",
        "log_file": path.name,
        "gpu": gpu_line,
        "status": "host_ram_oom_killed",
        "oom_kill_events": int(oom_match.group(1)) if oom_match else 0,
        "step_id": oom_match.group(2) if oom_match else "44200",
        "killed_command_excerpt": killed_line[:180],
        "root_cause": (
            "28G Slurm host cgroup RAM OOM during full-dataset prefix window materialization "
            "before completing the 5-step pilot."
        ),
    }


def _parse_kv_tokens(line: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in re.findall(r"([a-zA-Z0-9_()+/-]+)=([^\s,)]+)", line):
        out[tok[0]] = tok[1]
    return out


def parse_sft_train_log(path: Path, job_id: int, label: str) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    data_kv: dict[str, str] = {}
    header_tokens: int | None = None
    body_budget: int | None = None
    trainable_params = 0
    all_params = 0
    trainable_pct = 0.0
    train_steps: list[dict[str, Any]] = []
    train_summary: dict[str, Any] = {}
    timebox_step: int | None = None
    cancelled_reason: str | None = None
    world_secrets: list[str] = []

    for ln in lines:
        if ln.startswith("[data]"):
            data_kv.update(_parse_kv_tokens(ln))
            hb = _HEADER_BUDGET_RE.search(ln)
            if hb:
                header_tokens = int(hb.group(1))
                body_budget = int(hb.group(2))
        tr = _TRAINABLE_RE.search(ln)
        if tr:
            trainable_params = int(tr.group(1).replace(",", ""))
            all_params = int(tr.group(2).replace(",", ""))
            trainable_pct = float(tr.group(3))
        tm = _TRAIN_DICT_RE.match(ln)
        if tm:
            train_steps.append(ast.literal_eval(tm.group(1)))
        tb = _TIMEBOX_RE.match(ln)
        if tb:
            timebox_step = int(tb.group(1))
        sm = _SUMMARY_JSON_RE.match(ln)
        if sm and not train_summary:
            cand = json.loads(sm.group(1))
            if "tokens_per_s" in cand:
                train_summary = cand
        sec = _SECRET_RE.search(ln)
        if sec:
            world_secrets.append(sec.group(1))
        cn = _CANCEL_RE.search(ln)
        if cn:
            cancelled_reason = cn.group(2).strip()

    total_tokens = int(data_kv.get("tokens", "0"))
    loss_tokens = int(data_kv.get("loss_tokens", "0"))
    max_len = int(data_kv.get("max_len") or data_kv.get("max_window") or DEFAULT_MAX_LEN)
    computed_loss_frac = round(loss_tokens / total_tokens, 4) if total_tokens > 0 else 0.0
    logged_loss_frac = float(data_kv["loss_frac"]) if "loss_frac" in data_kv else computed_loss_frac

    losses = [float(s["loss"]) for s in train_steps if "loss" in s]
    out: dict[str, Any] = {
        "job_id": job_id,
        "label": label,
        "log_file": path.name,
        "window_mode": data_kv.get("mode", "prefix"),
        "episodes": int(data_kv.get("episodes", "0")),
        "windows": int(data_kv.get("windows", "0")),
        "dataset_tokens": total_tokens,
        "loss_tokens": loss_tokens,
        "loss_token_frac_exact": computed_loss_frac,
        "loss_token_frac_logged": round(logged_loss_frac, 4),
        "max_len": max_len,
        "trainable_params": trainable_params,
        "all_params": all_params,
        "trainable_pct": trainable_pct,
        "steps_completed": int(train_summary.get("steps", timebox_step or 0)),
        "full_run_steps": int(train_summary.get("full_run_steps", 0)),
        "epoch_fraction_completed": (
            round(int(train_summary.get("steps", 0)) / int(train_summary["full_run_steps"]), 4)
            if int(train_summary.get("full_run_steps", 0)) > 0
            else 0.0
        ),
        "train_tokens_processed": int(train_summary.get("tokens", 0)),
        "train_seconds": float(train_summary.get("seconds", 0.0)),
        "tokens_per_s": float(train_summary.get("tokens_per_s", 0.0)),
        "est_full_run_hours": float(train_summary.get("est_full_run_hours", 0.0)),
        "first_logged_loss": round(losses[0], 4) if losses else 0.0,
        "last_logged_loss": round(losses[-1], 4) if losses else 0.0,
        "min_logged_loss": round(min(losses), 4) if losses else 0.0,
        "time_boxed_at_step": timebox_step,
        "slurm_cancelled_reason": cancelled_reason,
        "in_job_world_secrets_sha256": world_secrets,
    }
    if header_tokens is not None and body_budget is not None:
        out["header_tokens"] = header_tokens
        out["header_frac"] = round(header_tokens / max_len, 4)
        out["body_budget_tokens"] = body_budget
        out["body_budget_frac"] = round(body_budget / max_len, 4)
    if "oversample_endings" in data_kv:
        out["oversample_endings"] = int(data_kv["oversample_endings"])
    if "accuse_loss_share" in data_kv:
        out["accuse_loss_share"] = float(data_kv["accuse_loss_share"])
    return out


def parse_eval_log(path: Path, job_id: int) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    hdr_kv = _parse_kv_tokens(lines[0]) if lines else {}
    secret_sha: str | None = None
    ep_rows: list[dict[str, Any]] = []
    cancelled_reason: str | None = None
    summary_obj: dict[str, Any] | None = None

    for ln in lines:
        sec = _SECRET_RE.search(ln)
        if sec:
            secret_sha = sec.group(1)
        epm = _EP_LINE_RE.match(ln.strip())
        if epm:
            ep_rows.append(
                {
                    "tier": epm.group(1),
                    "seed": int(epm.group(2)),
                    "score": float(epm.group(3)),
                    "correct": epm.group(4) == "True",
                    "steps": int(epm.group(5)),
                    "invalid": int(epm.group(6)),
                    "elapsed_s": int(epm.group(7)),
                }
            )
        sm = _SUMMARY_JSON_RE.match(ln.strip())
        if sm:
            summary_obj = json.loads(sm.group(1))
        cn = _CANCEL_RE.search(ln)
        if cn:
            cancelled_reason = cn.group(2).strip()

    tot_steps = sum(r["steps"] for r in ep_rows)
    tot_inv = sum(r["invalid"] for r in ep_rows)
    return {
        "job_id": job_id,
        "log_file": path.name,
        "run_id": hdr_kv.get("run", ""),
        "model": hdr_kv.get("model", ""),
        "host": hdr_kv.get("host", ""),
        "world_secret_sha256": secret_sha,
        "completed_episodes_in_log": len(ep_rows),
        "log_mean_score": round(sum(r["score"] for r in ep_rows) / len(ep_rows), 4) if ep_rows else 0.0,
        "log_parse_valid_call_rate": (
            round(1.0 - (tot_inv / tot_steps), 4) if tot_steps > 0 else 0.0
        ),
        "has_final_summary": summary_obj is not None,
        "slurm_cancelled_reason": cancelled_reason,
    }


def analyze_j4_v1_44397_evals(j4_dir: Path, train_info: dict[str, Any]) -> dict[str, Any]:
    runs_dir = j4_dir / "run-44397" / "runs"
    base_eps = read_jsonl(runs_dir / "eval-base" / "episodes.jsonl")
    lora_injob_eps = read_jsonl(runs_dir / "eval-lora" / "episodes.jsonl")
    lora_par_eps = read_jsonl(runs_dir / "eval-lora-par" / "episodes.jsonl")

    par_log = j4_dir / "run-44397" / "eval-lora-par.log"
    par_secret: str | None = None
    if par_log.exists():
        m = _SECRET_RE.search(par_log.read_text(encoding="utf-8"))
        if m:
            par_secret = m.group(1)

    first_seen_dedup: dict[tuple[str, int], dict[str, Any]] = {}
    for ep in lora_injob_eps + lora_par_eps:
        key = (str(ep["tier"]), int(ep["seed"]))
        if key not in first_seen_dedup:
            first_seen_dedup[key] = ep

    overlap_disagreements: list[dict[str, Any]] = []
    injob_map = {(str(e["tier"]), int(e["seed"])): e for e in lora_injob_eps}
    par_map = {(str(e["tier"]), int(e["seed"])): e for e in lora_par_eps}
    for key in sorted(set(injob_map) & set(par_map)):
        e1, e2 = injob_map[key], par_map[key]
        if float(e1["score"]) != float(e2["score"]) or e1.get("end_reason") != e2.get("end_reason"):
            overlap_disagreements.append(
                {
                    "tier": key[0],
                    "seed": key[1],
                    "eval_lora_score": float(e1["score"]),
                    "eval_lora_end_reason": str(e1.get("end_reason")),
                    "eval_lora_par_score": float(e2["score"]),
                    "eval_lora_par_end_reason": str(e2.get("end_reason")),
                }
            )

    injob_secrets = train_info.get("in_job_world_secrets_sha256", [])
    base_secret = injob_secrets[0] if len(injob_secrets) >= 1 else None
    lora_secret = injob_secrets[1] if len(injob_secrets) >= 2 else None

    raw_total = len(base_eps) + len(lora_injob_eps) + len(lora_par_eps)
    return {
        "env_version": "v1.3",
        "raw_total_episodes_across_subdirs": raw_total,
        "raw_lora_episodes": len(lora_injob_eps) + len(lora_par_eps),
        "eval_base": {
            "world_secret_sha256": base_secret,
            **summarize_episodes(base_eps),
        },
        "eval_lora_dedup_first_seen": {
            "dedup_policy": "first_seen_across_eval_lora_then_eval_lora_par",
            "world_secrets_mixed_sha256": [s for s in (lora_secret, par_secret) if s],
            **summarize_episodes(list(first_seen_dedup.values())),
        },
        "eval_lora_par_standalone": {
            "world_secret_sha256": par_secret,
            **summarize_episodes(lora_par_eps),
        },
        "unpaired_overlap_disagreements": overlap_disagreements,
    }


def parse_v3_oom_log(path: Path, job_id: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    hdr = _V3_HDR_RE.search(text)
    st = _V3_STATES_RE.search(text)
    oom = _CUDA_OOM_RE.search(text)
    return {
        "job_id": job_id,
        "log_file": path.name,
        "status": "cuda_oom_step_0",
        "seed": int(hdr.group(2)) if hdr else 0,
        "adapter": hdr.group(1) if hdr else "",
        "states_count": int(st.group(1)) if st else 0,
        "train_seed_start": int(st.group(2)) if st else 0,
        "tiers": ast.literal_eval(st.group(3)) if st else [],
        "tried_allocate_gib": float(oom.group(1)) if oom else 0.0,
        "gpu_total_gib": float(oom.group(2)) if oom else 0.0,
        "gpu_free_gib": float(oom.group(3)) if oom else 0.0,
        "process_in_use_gib": float(oom.group(4)) if oom else 0.0,
        "pytorch_allocated_gib": float(oom.group(5)) if oom else 0.0,
        "pytorch_reserved_unallocated_gib": float(oom.group(6)) if oom else 0.0,
        "failure_site": "model.generate(input_ids=x.expand(a.group, -1)) SDPA prefill",
    }


def summarize_grpo_curve(
    rows: list[dict[str, Any]],
    run_id: str,
    source: str,
    status: str,
) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "run_id": run_id,
            "source": source,
            "status": status,
            "available": False,
            "n_steps": 0,
        }

    def _mean(items: list[dict[str, Any]], key: str) -> float:
        vals = [float(r[key]) for r in items if key in r]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    window = min(20, max(1, n // 3))
    head = rows[:window]
    tail = rows[-window:]
    zero_var_positive = sum(1 for r in rows if int(r.get("zero_var_groups", 0)) > 0)
    all_groups_zero_var = sum(1 for r in rows if int(r.get("zero_var_groups", 0)) >= 2)

    return {
        "run_id": run_id,
        "source": source,
        "status": status,
        "available": True,
        "n_steps": n,
        "first_step": int(rows[0].get("step", 0)),
        "last_step": int(rows[-1].get("step", n - 1)),
        "elapsed_hours": round(float(rows[-1].get("elapsed_h", 0.0)), 4),
        "mean_step_seconds": _mean(rows, "sec"),
        "window_size": window,
        "mean_reward": _mean(rows, "reward"),
        "head_mean_reward": _mean(head, "reward"),
        "tail_mean_reward": _mean(tail, "reward"),
        "mean_reward_valid": _mean(rows, "reward_valid"),
        "mean_gain_vs_solver_valid": _mean(rows, "gain_vs_solver_valid"),
        "head_gain_vs_solver_valid": _mean(head, "gain_vs_solver_valid"),
        "tail_gain_vs_solver_valid": _mean(tail, "gain_vs_solver_valid"),
        "mean_valid_rate": _mean(rows, "valid"),
        "mean_accuse_frac": _mean(rows, "accuse_frac"),
        "mean_accuse_correct": _mean(rows, "accuse_correct"),
        "mean_continue_frac": _mean(rows, "continue_frac"),
        "mean_zero_var_groups": _mean(rows, "zero_var_groups"),
        "steps_with_zero_var_group": zero_var_positive,
        "steps_with_all_groups_zero_var": all_groups_zero_var,
        "max_kl": round(max(float(r.get("kl", 0.0)) for r in rows), 5),
        "last_kl": round(float(rows[-1].get("kl", 0.0)), 5),
    }


def parse_json_lines_from_slurm_log(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    rows: list[dict[str, Any]] = []
    cancelled: str | None = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("{") and s.endswith("}"):
            rows.append(json.loads(s))
        cn = _CANCEL_RE.search(ln)
        if cn:
            cancelled = cn.group(2).strip()
    return rows, cancelled


def load_git_curve_rows(git_spec: str, repo_root: Path) -> list[dict[str, Any]] | None:
    if git_spec == DEFAULT_VERDA_GIT_SPEC:
        local_curve = repo_root / DEFAULT_VERDA_LOCAL_CURVE
        if local_curve.is_file():
            return read_jsonl(local_curve)
    try:
        proc = subprocess.run(
            ["git", "show", git_spec],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    out: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        text = line.strip()
        if text:
            out.append(json.loads(text))
    return out


def _read_optional_summary_all(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_tier = payload.get("by_tier")
    if isinstance(by_tier, dict) and isinstance(by_tier.get("all"), dict):
        return dict(by_tier["all"])
    return None


def _read_optional_train_steps(path: Path, default_steps: int) -> int:
    if not path.is_file():
        return default_steps
    payload = json.loads(path.read_text(encoding="utf-8"))
    val = payload.get("steps")
    return int(val) if isinstance(val, int) else default_steps


def build_verda_v3_complete_matrix(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or ROOT
    verda_root = root / "data" / "fr8" / "verda"

    v2_off30_rel = Path("data/fr8/verda/evalbox-68bb/v2-off30/summary.json")
    s0_rel = Path("data/fr8/verda/h100-3bb7/runs/v3-verda-s0/summary.json")
    s0_off30_rel = Path("data/fr8/verda/evalbox-68bb/v3-4k-s0-off30/summary.json")
    s1_8k_rel = Path("data/fr8/verda/a100-ac58/runs/v3-verda-8k-s1/summary.json")
    s2_8k_rel = Path("data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json")
    inst_rel = Path("data/fr8/verda/instances-0308.txt")

    s0_ts_rel = Path("data/fr8/verda/h100-3bb7/run-verda-s0/lora/train_summary.json")
    s1_8k_ts_rel = Path("data/fr8/verda/a100-ac58/run-verda-8k-s1/lora/train_summary.json")
    s2_8k_ts_rel = Path("data/fr8/verda/h100spot-dbd0/run-verda-8k-s2/lora/train_summary.json")

    v2_off30_s = _read_optional_summary_all(root / v2_off30_rel)
    s0_s = _read_optional_summary_all(root / s0_rel)
    s0_off30_s = _read_optional_summary_all(root / s0_off30_rel)
    s1_8k_s = _read_optional_summary_all(root / s1_8k_rel)
    s2_8k_s = _read_optional_summary_all(root / s2_8k_rel)

    in_tree_found = sum(
        1
        for p in (v2_off30_rel, s0_rel, s0_off30_rel, s1_8k_rel, s2_8k_rel, inst_rel)
        if (root / p).is_file()
    )

    spot_714d_preempted = True
    inst_path = root / inst_rel
    if inst_path.is_file():
        inst_txt = inst_path.read_text(encoding="utf-8", errors="replace")
        spot_714d_preempted = "714d8144" not in inst_txt

    v2_off30_n = int(v2_off30_s["n"]) if v2_off30_s else 90
    v2_off30_mean_exact = round(float(v2_off30_s["mean_score"]), 4) if v2_off30_s else -0.5142
    v2_off30_ci_exact = round(float(v2_off30_s["ci95"]), 4) if v2_off30_s else 0.1152
    v2_off30_acc = int((v2_off30_s.get("end_reasons") or {}).get("accused", 52)) if v2_off30_s else 52
    v2_off30_cap = int((v2_off30_s.get("end_reasons") or {}).get("eval_cap", 38)) if v2_off30_s else 38
    v2_off30_inv = round(float(v2_off30_s["invalid_call_rate"]), 4) if v2_off30_s else 0.0825

    s0_steps = _read_optional_train_steps(root / s0_ts_rel, 609)
    s0_n = int(s0_s["n"]) if s0_s else 90
    s0_mean_exact = round(float(s0_s["mean_score"]), 4) if s0_s else -0.103
    s0_ci_exact = round(float(s0_s["ci95"]), 4) if s0_s else 0.0806
    s0_acc = int((s0_s.get("end_reasons") or {}).get("accused", 15)) if s0_s else 15
    s0_cap = int((s0_s.get("end_reasons") or {}).get("eval_cap", 75)) if s0_s else 75

    s0_off30_n = int(s0_off30_s["n"]) if s0_off30_s else 90
    s0_off30_mean_exact = round(float(s0_off30_s["mean_score"]), 4) if s0_off30_s else -0.1919
    s0_off30_ci_exact = round(float(s0_off30_s["ci95"]), 4) if s0_off30_s else 0.0959
    s0_off30_acc = int((s0_off30_s.get("end_reasons") or {}).get("accused", 23)) if s0_off30_s else 23
    s0_off30_cap = int((s0_off30_s.get("end_reasons") or {}).get("eval_cap", 67)) if s0_off30_s else 67

    s1_8k_steps = _read_optional_train_steps(root / s1_8k_ts_rel, 371)
    s1_8k_n = int(s1_8k_s["n"]) if s1_8k_s else 90
    s1_8k_mean_exact = round(float(s1_8k_s["mean_score"]), 4) if s1_8k_s else -0.7767
    s1_8k_ci_exact = round(float(s1_8k_s["ci95"]), 4) if s1_8k_s else 0.118
    s1_8k_acc = int((s1_8k_s.get("end_reasons") or {}).get("accused", 85)) if s1_8k_s else 85
    s1_8k_inv = round(float(s1_8k_s["invalid_call_rate"]), 4) if s1_8k_s else 0.0775

    s2_8k_steps = _read_optional_train_steps(root / s2_8k_ts_rel, 693)
    s2_8k_n = int(s2_8k_s["n"]) if s2_8k_s else 90
    s2_8k_mean_exact = round(float(s2_8k_s["mean_score"]), 4) if s2_8k_s else -0.0498
    s2_8k_ci_exact = round(float(s2_8k_s["ci95"]), 4) if s2_8k_s else 0.0492
    s2_8k_acc = int((s2_8k_s.get("end_reasons") or {}).get("accused", 6)) if s2_8k_s else 6
    s2_8k_inv = round(float(s2_8k_s["invalid_call_rate"]), 4) if s2_8k_s else 0.037

    pooled_s0_n = s0_n + s0_off30_n
    pooled_s0_acc = s0_acc + s0_off30_acc
    pooled_s0_cap = s0_cap + s0_off30_cap
    pooled_s0_correct = 6
    pooled_s0_mean = round((s0_n * s0_mean_exact + s0_off30_n * s0_off30_mean_exact) / max(pooled_s0_n, 1), 3)

    return {
        "fresh_clone_safe": True,
        "verda_dir_present": verda_root.is_dir(),
        "in_tree_verda_files_checked": 6,
        "in_tree_verda_files_present": in_tree_found,
        "panel_fix_a_disclosure": (
            "DEV_SEEDS 0..29 in secondary diagnostics are post-hoc locked right after episode commitment, "
            "not pre-registered; all WS4 and Verda tiebreaker evaluations use HELDOUT_SEEDS 800000..800199."
        ),
        "pooled_base": {
            "label": "base (pooled)",
            "model": "Qwen2.5-1.5B-Instruct (untrained base)",
            "context_len": 4096,
            "n": 36,
            "mean_score": 0.0,
            "ci95": 0.0,
            "valid_call_rate": 0.03,
            "accused_count": 0,
            "accused_rate": 0.0,
            "correct_count": 0,
            "abstain_rate": 1.0,
            "eval_cap_rate": 1.0,
            "audited_seed_span": "800000..800012",
            "world_secret_mode": "unpaired_per_process_urandom",
            "world_secret_sha256_list": ["f272803cdb679dbe", "404f83e6a15c3f1c"],
            "components": {
                "eval_44411": {
                    "job_id": 44411,
                    "n": 16,
                    "mean_score": 0.0,
                    "ci95": 0.0,
                    "valid_call_rate": 0.03,
                    "audited_seed_span": "800000..800005",
                    "world_secret_sha256": "f272803cdb679dbe",
                },
                "eval_44584": {
                    "job_id": 44584,
                    "n": 20,
                    "mean_score": 0.0,
                    "ci95": 0.0,
                    "valid_call_rate": 0.03,
                    "audited_seed_span": "800006..800012",
                    "world_secret_sha256": "404f83e6a15c3f1c",
                },
            },
        },
        "pooled_v2": {
            "label": "v2 (pooled)",
            "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (WS4 dense 4k SFT, oversample-endings 3)",
            "context_len": 4096,
            "n": 42 + 40 + v2_off30_n,
            "mean_score": -0.457,
            "ci95": 0.086,
            "valid_call_rate": 0.92,
            "accused_count": 42 + v2_off30_acc,
            "accused_rate": 0.55,
            "correct_count": 8,
            "precision_when_accused": 0.09,
            "accuracy": 0.05,
            "audited_seed_span": "800000..800059",
            "world_secret_mode": "unpaired_per_process_urandom",
            "components": {
                "eval_44412": {
                    "job_id": 44412,
                    "n": 82,
                    "mean_score": -0.395,
                    "ci95": 0.128,
                    "accused_count": 42,
                    "correct_count": 5,
                    "valid_call_rate": 0.92,
                    "audited_seed_span": "800000..800027",
                    "world_secret_sha256": "c86b9c8a54f8b269",
                },
                "v2_off30": {
                    "verda_instance": "68bbe201",
                    "n": v2_off30_n,
                    "mean_score": round(v2_off30_mean_exact, 3),
                    "mean_score_exact": v2_off30_mean_exact,
                    "ci95": round(v2_off30_ci_exact, 3),
                    "ci95_exact": v2_off30_ci_exact,
                    "accused_count": v2_off30_acc,
                    "eval_cap_count": v2_off30_cap,
                    "correct_count": 3,
                    "valid_call_rate": round(1.0 - v2_off30_inv, 2),
                    "audited_seed_span": "800030..800059",
                },
            },
        },
        "v3_4k_family": {
            "pooled_v3_4k_s0": {
                "label": "v3-4k-s0 (pooled)",
                "adapter_sha256_12": "3d0cd43b8037",
                "grpo_steps": s0_steps,
                "context_len": 4096,
                "n": pooled_s0_n,
                "mean_score": pooled_s0_mean,
                "ci95": 0.063,
                "valid_call_rate": 1.00,
                "accused_count": pooled_s0_acc,
                "accused_rate": round(pooled_s0_acc / max(pooled_s0_n, 1), 2),
                "accused_ratio": f"{pooled_s0_acc}/{pooled_s0_n}",
                "correct_count": pooled_s0_correct,
                "precision_when_accused": round(pooled_s0_correct / max(pooled_s0_acc, 1), 2),
                "correct_when_accused_ratio": f"{pooled_s0_correct}/{pooled_s0_acc}",
                "accuracy": 0.03,
                "eval_cap_count": pooled_s0_cap,
                "abstain_rate": round(pooled_s0_cap / max(pooled_s0_n, 1), 2),
                "forced_accuse_whom_first_w100": 0.19,
                "forced_accuse_whom_last_w100": 0.892,
                "two_sample_delta_vs_v2": {"mean_delta": 0.310, "ci95": 0.107},
                "two_sample_delta_vs_base": {"mean_delta": -0.147, "ci95": 0.063},
                "audited_seed_span": "800000..800059",
                "components": {
                    "v3_verda_s0": {
                        "verda_instance": "3bb74f5a",
                        "n": s0_n,
                        "mean_score": round(s0_mean_exact, 3),
                        "ci95": round(s0_ci_exact, 3),
                        "accused_count": s0_acc,
                        "eval_cap_count": s0_cap,
                        "correct_count": 3,
                        "valid_call_rate": 1.00,
                        "audited_seed_span": "800000..800029",
                    },
                    "v3_4k_s0_off30": {
                        "verda_instance": "68bbe201",
                        "n": s0_off30_n,
                        "mean_score": round(s0_off30_mean_exact, 3),
                        "mean_score_exact": s0_off30_mean_exact,
                        "ci95": round(s0_off30_ci_exact, 3),
                        "ci95_exact": s0_off30_ci_exact,
                        "accused_count": s0_off30_acc,
                        "eval_cap_count": s0_off30_cap,
                        "correct_count": 3,
                        "valid_call_rate": 1.00,
                        "audited_seed_span": "800030..800059",
                    },
                },
            },
            "v3_4k_s1_partial": {
                "label": "v3-4k-s1 (FR8 V100 partial)",
                "job_id": 44572,
                "eval_job_id": 44573,
                "gpu": "Tesla V100-PCIE-32GB",
                "grpo_steps": 192,
                "context_len": 4096,
                "n": 25,
                "mean_score": -0.240,
                "ci95": 0.171,
                "valid_call_rate": 0.97,
                "accused_count": 6,
                "accused_rate": 0.24,
                "correct_count": 0,
                "abstain_rate": 0.76,
                "forced_accuse_whom_first_w96": 0.224,
                "forced_accuse_whom_last_w96": 0.267,
                "audited_seed_span": "800000..800008",
                "world_secret_sha256": "09f8bc6443018b18",
            },
            "v3_4k_s1_spot_714d": {
                "label": "v3-4k-s1-spot (Verda 714d)",
                "verda_instance": "714d8144",
                "verda_instance_full": "714d8144-c036-4814-999d-a38ed192a48f",
                "gpu": "A100-80GB spot (1A100.22V)",
                "status": "spot_preempted",
                "spot_preempted": spot_714d_preempted,
                "approx_train_minutes": 29,
                "n": 0,
            },
        },
        "v3_4k_s0_at_8k_confound": {
            "label": "v3-4k-s0@8k",
            "verda_eval_instance": "68bbe201",
            "adapter_sha256_12": "3d0cd43b8037",
            "grpo_steps": s0_steps,
            "trained_context_len": 4096,
            "eval_context_len": 8192,
            "shared_world_secret": "1ca0c2a64d",
            "audited_seed_span": "800000..800029",
            "n": 90,
            "mean_score": -0.716,
            "ci95": 0.105,
            "valid_call_rate": 0.99,
            "accused_count": 70,
            "accused_rate": 0.78,
            "correct_count": 3,
            "accuracy": 0.03,
            "precision_when_accused": 0.0429,
            "abstain_rate": 0.22,
            "by_tier_mean_score": {"easy": -0.447, "medium": -0.800, "hard": -0.900},
            "by_tier_accused_rate": {"easy": 0.63, "medium": 0.80, "hard": 0.90},
            "two_sample_delta_vs_4k": {"mean_delta": -0.568, "ci95": 0.123},
            "two_sample_delta_vs_v2": {"mean_delta": -0.258, "ci95": 0.136},
        },
        "v3_8k_replicates": {
            "v3_8k_s1": {
                "label": "v3-8k-s1",
                "verda_instance": "ac58df04",
                "gpu": "A100-80GB spot",
                "grpo_steps": s1_8k_steps,
                "context_len": 8192,
                "n": s1_8k_n,
                "mean_score": round(s1_8k_mean_exact, 3),
                "mean_score_exact": s1_8k_mean_exact,
                "ci95": round(s1_8k_ci_exact, 3),
                "valid_call_rate": round(1.0 - s1_8k_inv, 2),
                "accused_count": s1_8k_acc,
                "accused_rate": round(s1_8k_acc / max(s1_8k_n, 1), 2),
                "correct_count": 8,
                "accuracy": 0.09,
                "abstain_rate": round((s1_8k_n - s1_8k_acc) / max(s1_8k_n, 1), 2),
                "forced_accuse_whom_first_w100": 0.35,
                "forced_accuse_whom_last_w100": 0.412,
                "audited_seed_span": "800000..800029",
                "world_secret_mode": "unpaired_per_process_urandom",
            },
            "v3_8k_s2": {
                "label": "v3-8k-s2",
                "verda_instance": "dbd083ca",
                "gpu": "H100-80GB spot",
                "grpo_steps": s2_8k_steps,
                "context_len": 8192,
                "n": s2_8k_n,
                "mean_score": round(s2_8k_mean_exact, 3),
                "mean_score_exact": s2_8k_mean_exact,
                "ci95": round(s2_8k_ci_exact, 3),
                "ci95_exact": s2_8k_ci_exact,
                "valid_call_rate": round(1.0 - s2_8k_inv, 2),
                "accused_count": s2_8k_acc,
                "accused_rate": round(s2_8k_acc / max(s2_8k_n, 1), 2),
                "correct_count": 1,
                "accuracy": 0.01,
                "abstain_rate": round((s2_8k_n - s2_8k_acc) / max(s2_8k_n, 1), 2),
                "forced_accuse_whom_first_w100": 0.313,
                "forced_accuse_whom_last_w100": 0.458,
                "audited_seed_span": "800000..800029",
                "world_secret_mode": "unpaired_per_process_urandom",
            },
            "v3_8k_s3": {
                "label": "v3-8k-s3",
                "verda_instance": "f4378173",
                "gpu": "A100-80GB on-demand",
                "grpo_steps": 344,
                "context_len": 8192,
                "shared_world_secret": "1ca0c2a64d",
                "n": 90,
                "mean_score": -0.788,
                "mean_score_exact": -0.7882,
                "ci95": 0.117,
                "ci95_exact": 0.1166,
                "valid_call_rate": 0.94,
                "accused_count": 86,
                "accused_rate": 0.96,
                "correct_count": 8,
                "accuracy": 0.09,
                "abstain_rate": 0.04,
                "audited_seed_span": "800000..800029",
                "truly_paired_8k_vs_4k_at_8k": {
                    "counterpart": "v3-4k-s0@8k",
                    "shared_world_secret": "1ca0c2a64d",
                    "matching_step0_rosters": "60/60",
                    "n": 90,
                    "mean_delta": -0.073,
                    "ci95": 0.173,
                },
            },
        },
    }


def build_forensics_report(
    j4_dir: Path = DEFAULT_J4_DIR,
    v3_dir: Path = DEFAULT_V3_DIR,
    repo_root: Path | None = None,
    verda_git_spec: str = DEFAULT_VERDA_GIT_SPEC,
    instr_by_tier: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = repo_root or ROOT
    verda_matrix = build_verda_v3_complete_matrix(repo_root=root)

    if (not j4_dir.is_dir() or not v3_dir.is_dir()) and j4_dir == DEFAULT_J4_DIR and v3_dir == DEFAULT_V3_DIR:
        committed_fallback = root / DEFAULT_OUT_JSON
        if committed_fallback.is_file():
            cached = json.loads(committed_fallback.read_text(encoding="utf-8"))
            cached["schema_version"] = SCHEMA_VERSION
            cached["verda_v3_complete_matrix"] = verda_matrix
            return cached

    pilot_44200 = parse_pilot_44200(j4_dir / "slurm-44200.out")
    train_44397 = parse_sft_train_log(j4_dir / "slurm-44397.out", 44397, "J4_v1_prefix_4k_sft")
    eval_44397 = analyze_j4_v1_44397_evals(j4_dir, train_44397)

    train_44410 = parse_sft_train_log(j4_dir / "slurm-44410.out", 44410, "WS4_v2_dense_4k_sft")
    eval_44411_log = parse_eval_log(j4_dir / "eval-44411.out", 44411)
    eval_44412_log = parse_eval_log(j4_dir / "eval-44412.out", 44412)
    eval_44583_log = parse_eval_log(j4_dir / "eval-44583.out", 44583)
    eval_44584_log = parse_eval_log(j4_dir / "eval-44584.out", 44584)

    ws4_base_eps = read_jsonl(j4_dir / "runs" / "ws4-base-v14" / "episodes.jsonl")
    ws4_v2_eps = read_jsonl(j4_dir / "runs" / "ws4-v2-44410" / "episodes.jsonl")
    ws4_off6_eps = read_jsonl(j4_dir / "runs" / "ws4-base-v14-off6" / "episodes.jsonl")

    ws4_base_summary = summarize_episodes(ws4_base_eps)
    ws4_v2_summary = summarize_episodes(ws4_v2_eps)
    ws4_off6_summary = summarize_episodes(ws4_off6_eps)

    header_tok = int(train_44410.get("header_tokens", DEFAULT_HEADER_TOKENS))
    max_len = int(train_44410.get("max_len", DEFAULT_MAX_LEN))
    ws4_root_cause = analyze_ws4_v2_root_causes(
        ws4_v2_eps,
        instr_by_tier=instr_by_tier,
        header_tokens=header_tok,
        max_len=max_len,
        chars_per_token=DEFAULT_CHARS_PER_TOKEN,
    )

    oom_44548 = parse_v3_oom_log(v3_dir / "slurm-44548.out", 44548)
    oom_44550 = parse_v3_oom_log(v3_dir / "slurm-44550.out", 44550)
    rows_44553, cancel_44553 = parse_json_lines_from_slurm_log(v3_dir / "slurm-44553.out")
    curve_44553 = summarize_grpo_curve(
        rows_44553,
        run_id="run-44553",
        source="v3/slurm-44553.out",
        status=f"terminated_zero_variance ({cancel_44553 or 'terminated'})",
    )

    rows_44555 = read_jsonl(v3_dir / "run-44555" / "curve.jsonl")
    _, cancel_44555 = parse_json_lines_from_slurm_log(v3_dir / "slurm-44555.out")
    curve_44555 = summarize_grpo_curve(
        rows_44555,
        run_id="run-44555",
        source="v3/run-44555/curve.jsonl",
        status=f"cancelled ({cancel_44555 or 'SIGNAL Terminated'})",
    )

    rows_44572 = read_jsonl(v3_dir / "run-44572" / "curve.jsonl")
    _, cancel_44572 = parse_json_lines_from_slurm_log(v3_dir / "slurm-44572.out")
    status_44572 = f"cancelled ({cancel_44572})" if cancel_44572 else "snapshot_in_progress_or_complete"
    curve_44572 = summarize_grpo_curve(
        rows_44572,
        run_id="run-44572",
        source="v3/run-44572/curve.jsonl",
        status=status_44572,
    )

    verda_rows = load_git_curve_rows(verda_git_spec, root)
    if verda_rows is not None:
        curve_verda = summarize_grpo_curve(
            verda_rows,
            run_id="run-verda-s0",
            source=verda_git_spec,
            status="completed_git_artifact",
        )
    else:
        curve_verda = {
            "run_id": "run-verda-s0",
            "source": verda_git_spec,
            "status": "git_ref_unavailable_fallback",
            "available": False,
            "n_steps": 0,
        }

    sha_44411 = eval_44411_log["world_secret_sha256"]
    sha_44412 = eval_44412_log["world_secret_sha256"]
    sha_44583 = eval_44583_log["world_secret_sha256"]
    sha_44584 = eval_44584_log["world_secret_sha256"]

    unpaired_secret_audit = {
        "paired": bool(sha_44411 and sha_44412 and sha_44411 == sha_44412),
        "mechanism": (
            "canary.world._key(seed) falls back to per-process os.urandom(32) on HELDOUT_SEEDS "
            "(800000+) whenever CANARY_WORLD_SECRET and data/worlds/judge/SALT are absent."
        ),
        "eval_44411_base_sha256": sha_44411,
        "eval_44412_v2_sha256": sha_44412,
        "eval_44583_base_n30_sha256": sha_44583,
        "eval_44584_base_off6_sha256": sha_44584,
        "j4_44397_eval_base_sha256": eval_44397["eval_base"]["world_secret_sha256"],
        "j4_44397_eval_lora_sha256": (
            train_44397["in_job_world_secrets_sha256"][1]
            if len(train_44397["in_job_world_secrets_sha256"]) >= 2
            else None
        ),
        "j4_44397_eval_lora_par_sha256": eval_44397["eval_lora_par_standalone"]["world_secret_sha256"],
        "distinct_secrets_observed": len(
            {
                s
                for s in (
                    sha_44411,
                    sha_44412,
                    sha_44583,
                    sha_44584,
                    eval_44397["eval_base"]["world_secret_sha256"],
                    eval_44397["eval_lora_par_standalone"]["world_secret_sha256"],
                )
                if s
            }
        ),
        "impact": (
            "Base (eval-44411) and LoRA v2 (eval-44412) evaluated the same seed integers "
            "800000..800015 on different secret-salted worlds (mole identity, roster, and "
            "document recipients differed across processes), invalidating unpaired seed-by-seed deltas."
        ),
        "fix_required": (
            "Evaluate base and fine-tuned policies in a single process or pass an explicit "
            "shared CANARY_WORLD_SECRET and verify matching world_secret_sha256 in logs."
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "j4_runs": {
            "pilot_44200": pilot_44200,
            "v1_44397": {
                "train": train_44397,
                "eval": eval_44397,
            },
            "ws4_v2_44410": {
                "train": train_44410,
                "eval_base_44411": {
                    "log": eval_44411_log,
                    "episodes": ws4_base_summary,
                },
                "eval_v2_44412": {
                    "log": eval_44412_log,
                    "episodes": ws4_v2_summary,
                },
                "eval_base_44583": {
                    "log": eval_44583_log,
                },
                "eval_base_44584_snapshot": {
                    "log": eval_44584_log,
                    "episodes": ws4_off6_summary,
                },
            },
        },
        "unpaired_secret_audit": unpaired_secret_audit,
        "ws4_v2_root_cause": ws4_root_cause,
        "v3_grpo_runs": {
            "attempt1_cuda_oom": [oom_44548, oom_44550],
            "attempt2_zero_variance_44553": curve_44553,
            "v100_curve_44555": curve_44555,
            "v100_curve_44572": curve_44572,
            "verda_curve_s0": curve_verda,
        },
        "verda_v3_complete_matrix": verda_matrix,
        "lessons_for_tiebreak_v4": [
            (
                "Eliminate the 69.4% header tax (2842/4096 tokens): use a compact state/tool "
                "renderer so employee roster and all planted canary assignments stay inside the context window."
            ),
            (
                "Train calibrated stopping and abstention: supervise explicit posterior/breakeven "
                "checks (accuse only when P(top) > 1/(1+V_known) and include censored abstention trajectories)."
            ),
            (
                "Enforce strict paired evaluation on HELDOUT_SEEDS: run base and fine-tuned models "
                "under a shared CANARY_WORLD_SECRET (or same-process world) and assert matching SHA256."
            ),
            (
                "Avoid naive on-policy GRPO without state-value variance control: 32GB V100 hits SDPA "
                "OOM on unchunked 4k group prefill, collapsed continue-only groups yield zero gradient, "
                "and forced-accuse single-step RL drifts in KL without closing the solver gap."
            ),
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3

    p44200 = report["j4_runs"]["pilot_44200"]
    v1_tr = report["j4_runs"]["v1_44397"]["train"]
    v1_ev = report["j4_runs"]["v1_44397"]["eval"]
    v1_base = v1_ev["eval_base"]["overall"]
    v1_dedup = v1_ev["eval_lora_dedup_first_seen"]["overall"]
    v1_par = v1_ev["eval_lora_par_standalone"]["overall"]

    v2_tr = report["j4_runs"]["ws4_v2_44410"]["train"]
    b14 = report["j4_runs"]["ws4_v2_44410"]["eval_base_44411"]["episodes"]["overall"]
    v2_ep = report["j4_runs"]["ws4_v2_44410"]["eval_v2_44412"]["episodes"]
    v2_all = v2_ep["overall"]
    e44583 = report["j4_runs"]["ws4_v2_44410"]["eval_base_44583"]["log"]
    e44584_ep = report["j4_runs"]["ws4_v2_44410"]["eval_base_44584_snapshot"]["episodes"]["overall"]

    sec = report["unpaired_secret_audit"]
    rc = report["ws4_v2_root_cause"]
    rc_win = rc["window_model"]
    rc_all = rc["overall"]

    v3 = report["v3_grpo_runs"]
    oom0, oom1 = v3["attempt1_cuda_oom"][0], v3["attempt1_cuda_oom"][1]
    c44553 = v3["attempt2_zero_variance_44553"]
    c44555 = v3["v100_curve_44555"]
    c44572 = v3["v100_curve_44572"]
    cverda = v3["verda_curve_s0"]

    lines: list[str] = [
        f"{h1} Tiebreaker Prior Runs Forensics (J4 / WS4 / v3)",
        "",
        "Honest post-mortem of every historical small-model investigator training and evaluation run "
        "on Canary prior to the calibrated compact tiebreaker pipeline.",
        "",
        f"{h2} 1. Ledger of Historical J4 and WS4 SFT Runs",
        "",
        "| Job / Run | Env | Model / Mode | Train Progress | Held-Out Eval N | Mean Score (+/- CI95) | Accused / Correct / Abstain | Parse-Valid / Env-OK Calls | Outcome |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| `slurm-44200` (J4 pilot) | v1.3 | Qwen2.5-1.5B prefix 4k | 0/5 pilot steps | 0 | n/a | n/a | n/a | "
            f"Host 28G cgroup OOM kill (`oom_kill={p44200['oom_kill_events']}`) |"
        ),
        (
            f"| `run-44397` base (`eval-base`) | v1.3 | Qwen2.5-1.5B-Instruct | 0 steps | "
            f"{v1_base['n']} | {v1_base['mean_score']:.3f} +/- {v1_base['ci95']:.3f} | "
            f"{v1_base['accused_rate']:.2f} / {v1_base['accuracy']:.2f} / {v1_base['abstain_rate']:.2f} | "
            f"{v1_base['parse_valid_call_rate']:.2f} / {v1_base['env_ok_step_rate']:.2f} | "
            f"91.8% unparseable tool calls (`tool_cap`) |"
        ),
        (
            f"| `slurm-44397` (`J4 / v1` dedup) | v1.3 | 1.5B LoRA prefix 4k | "
            f"{v1_tr['steps_completed']}/{v1_tr['full_run_steps']} steps ({v1_tr['epoch_fraction_completed']*100:.1f}%) | "
            f"{v1_dedup['n']} (raw {v1_ev['raw_total_episodes_across_subdirs']}) | "
            f"{v1_dedup['mean_score']:.3f} +/- {v1_dedup['ci95']:.3f} | "
            f"{v1_dedup['accused_rate']:.2f} / {v1_dedup['accuracy']:.2f} / {v1_dedup['abstain_rate']:.2f} | "
            f"{v1_dedup['parse_valid_call_rate']:.2f} / {v1_dedup['env_ok_step_rate']:.2f} | "
            f"Syntax fixed (0.08 -> 0.99 env-OK), score regressed via wrong early accusations |"
        ),
        (
            f"| `run-44397` (`eval-lora-par` only) | v1.3 | 1.5B LoRA prefix 4k | "
            f"{v1_tr['steps_completed']}/{v1_tr['full_run_steps']} steps | "
            f"{v1_par['n']} | {v1_par['mean_score']:.3f} +/- {v1_par['ci95']:.3f} | "
            f"{v1_par['accused_rate']:.2f} / {v1_par['accuracy']:.2f} / {v1_par['abstain_rate']:.2f} | "
            f"{v1_par['parse_valid_call_rate']:.2f} / {v1_par['env_ok_step_rate']:.2f} | "
            f"10/12 horizon abstentions, 1 correct hard catch, 1 wrong easy accusation |"
        ),
        (
            f"| `eval-44411` (`ws4-base-v14`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | "
            f"{b14['n']} | {b14['mean_score']:.3f} +/- {b14['ci95']:.3f} | "
            f"{b14['accused_rate']:.2f} / {b14['accuracy']:.2f} / {b14['abstain_rate']:.2f} | "
            f"{b14['parse_valid_call_rate']:.2f} / {b14['env_ok_step_rate']:.2f} | "
            f"97.0% invalid calls (`eval_cap` on day 1 across all 16 episodes) |"
        ),
        (
            f"| `slurm-44410` + `eval-44412` (`WS4 / v2`) | v1.4 | 1.5B LoRA dense 4k | "
            f"{v2_tr['steps_completed']}/{v2_tr['full_run_steps']} steps ({v2_tr['epoch_fraction_completed']*100:.1f}%) | "
            f"{v2_all['n']} | {v2_all['mean_score']:.3f} +/- {v2_all['ci95']:.3f} | "
            f"{v2_all['accused_rate']:.2f} / {v2_all['accuracy']:.2f} / {v2_all['abstain_rate']:.2f} | "
            f"{v2_all['parse_valid_call_rate']:.2f} / {v2_all['env_ok_step_rate']:.2f} | "
            f"Valid calls 0.03 -> 0.92, but uncalibrated blind accusations drove score to -0.395 |"
        ),
        (
            f"| `eval-44583` (`ws4-base-v14-n30`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | "
            f"{e44583['completed_episodes_in_log']} | n/a | n/a | n/a | "
            f"Terminated after 41s before first episode finished ({e44583['slurm_cancelled_reason']}) |"
        ),
        (
            f"| `eval-44584` (`ws4-base-v14-off6`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | "
            f"{e44584_ep['n']} (snapshot) | {e44584_ep['mean_score']:.3f} +/- {e44584_ep['ci95']:.3f} | "
            f"{e44584_ep['accused_rate']:.2f} / {e44584_ep['accuracy']:.2f} / {e44584_ep['abstain_rate']:.2f} | "
            f"{e44584_ep['parse_valid_call_rate']:.2f} / {e44584_ep['env_ok_step_rate']:.2f} | "
            f"Offset-6 base continuation; 97.0% invalid calls (`eval_cap`) |"
        ),
        "",
        f"{h3} WS4 / v2 (`eval-44412`) Tier Breakdown (`n={v2_all['n']}`)",
        "",
        "| Tier | N | Mean Score (+/- CI95) | Accused Rate | Accuracy | Abstain (`eval_cap`) | Parse-Valid Rate | Mean Final Day |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for tier in CANONICAL_TIERS:
        ts = v2_ep["by_tier"][tier]
        lines.append(
            f"| `{tier}` | {ts['n']} | {ts['mean_score']:.4f} +/- {ts['ci95']:.4f} | "
            f"{ts['accused_count']}/{ts['n']} ({ts['accused_rate']:.4f}) | "
            f"{ts['correct_count']}/{ts['n']} ({ts['accuracy']:.4f}) | "
            f"{ts['abstain_count']}/{ts['n']} ({ts['abstain_rate']:.4f}) | "
            f"{ts['parse_valid_call_rate']:.4f} | {ts['mean_final_day']:.2f} |"
        )

    lines.extend(
        [
            "",
            f"{h2} 2. Evaluation Integrity Catch: Unpaired Per-Process `os.urandom` World Secrets",
            "",
            f"- Paired status between `eval-44411` (base) and `eval-44412` (v2): **`paired = {sec['paired']}`**.",
            f"- `eval-44411.out` (`ws4-base-v14`) world secret SHA256: `{sec['eval_44411_base_sha256']}`.",
            f"- `eval-44412.out` (`ws4-v2-44410`) world secret SHA256: `{sec['eval_44412_v2_sha256']}`.",
            f"- `eval-44583.out` (`ws4-base-v14-n30`) world secret SHA256: `{sec['eval_44583_base_n30_sha256']}`.",
            f"- `eval-44584.out` (`ws4-base-v14-off6`) world secret SHA256: `{sec['eval_44584_base_off6_sha256']}`.",
            f"- `run-44397` also used three distinct per-process secrets across `eval-base` (`{sec['j4_44397_eval_base_sha256']}`), "
            f"`eval-lora` (`{sec['j4_44397_eval_lora_sha256']}`), and `eval-lora-par` (`{sec['j4_44397_eval_lora_par_sha256']}`), "
            f"producing {len(v1_ev['unpaired_overlap_disagreements'])} score/outcome disagreements on identical `(tier, seed)` pairs.",
            f"- Root mechanism: {sec['mechanism']}",
            f"- Mandatory protocol fix: {sec['fix_required']}",
            "",
            f"{h2} 3. Quantitative Root-Cause Proof on WS4 / v2 (`ws4-v2-44410`)",
            "",
            f"{h3} 3a. Header Tax and 1254-Token Context Amnesia (`~{rc_win['chars_per_token']:.1f}` chars/token)",
            "",
            f"- In `slurm-44410.out`, the OpenAI/Qwen tool-schema + system + kickoff header consumed "
            f"**`{rc_win['header_tokens']}/{rc_win['max_len_tokens']}` tokens (`{rc_win['header_frac']*100:.1f}%`)**, "
            f"leaving only **`{rc_win['body_budget_tokens']}` tokens (`{rc_win['body_budget_frac']*100:.1f}%`)** for episode history "
            f"and only **`{v2_tr['loss_token_frac_logged']*100:.1f}%` (`{v2_tr['loss_tokens']}/{v2_tr['dataset_tokens']}`)** loss-bearing assistant tokens.",
            f"- Across all **`{rc_all['accused_episodes']}`** accused episodes in `runs/ws4-v2-44410/episodes.jsonl`:",
            f"  - **`{rc_all['dropped_prior_turns']}/{rc_all['total_prior_turns']}` (`{rc_all['dropped_prior_turns_frac']*100:.1f}%`)** "
            f"prior tool turns fell outside the `{rc_win['body_budget_tokens']}`-token body window before `accuse`.",
            f"  - **`{rc_all['dropped_plant_canary_turns']}/{rc_all['total_plant_canary_turns']}` (`{rc_all['dropped_plant_canary_frac']*100:.1f}%`)** "
            f"prior `plant_canary` turns fell outside the `{rc_win['body_budget_tokens']}`-token body window "
            f"(affecting `{rc_all['episodes_with_dropped_plant_canary']}/{rc_all['episodes_with_plant_canary']}` canary-planting accused episodes), "
            f"erasing the variant-to-employee mapping needed to interpret surfaced canary leaks.",
            f"  - **`{rc_all['dropped_list_employees_turns']}/{rc_all['total_list_employees_turns']}` (`{rc_all['dropped_list_employees_frac']*100:.1f}%`)** "
            f"prior `list_employees` turns fell outside the `{rc_win['body_budget_tokens']}`-token body window "
            f"(`{rc_all['episodes_missing_employee_roster_at_accuse']}/{rc_all['accused_episodes']}` accused episodes had no visible employee roster at the `accuse` turn).",
            "",
            f"{h3} 3b. Read-Only `SolverPolicy._ingest` + `belief()` Full-History Replay Audit",
            "",
            f"- Replaying all public steps prior to each of the `{rc_all['accused_episodes']}` `v2` accusations through `SolverPolicy`:",
            f"  - **`{rc_all['below_breakeven_count']}/{rc_all['accused_episodes']}` (`{rc_all['below_breakeven_frac']*100:.2f}%`)** "
            f"accused with full-history posterior **`P_full(accused) < 1 / (1 + V_known)`** "
            f"(mean `P_full(accused) = {rc_all['mean_p_full_accused']:.4f}` vs mean breakeven `{rc_all['mean_breakeven_p']:.4f}`, "
            f"mean full-history `EV(accuse) = {rc_all['mean_ev_full_accused']:+.4f}`).",
            f"  - **`{rc_all['p_le_005_count']}/{rc_all['accused_episodes']}` (`{rc_all['p_le_005_frac']*100:.2f}%`)** "
            f"accused a suspect already ruled out or near-zero under full public evidence (**`P_full(accused) <= 0.05`**), including "
            f"`{rc_all['ruled_out_by_surfaced_canary_count']}/{rc_all['accused_episodes']}` (`{rc_all['ruled_out_by_surfaced_canary_frac']*100:.2f}%`) "
            f"explicitly contradicted by a surfaced canary variant and "
            f"`{rc_all['ruled_out_by_surfaced_doc_recipients_count']}/{rc_all['accused_episodes']}` (`{rc_all['ruled_out_by_surfaced_doc_recipients_frac']*100:.2f}%`) "
            f"not in the recipient list of a surfaced leaked document.",
            f"  - Only **`{rc_all['accused_is_argmax_count']}/{rc_all['accused_episodes']}` (`{rc_all['accused_is_argmax_frac']*100:.2f}%`)** "
            f"even named the full-history MAP suspect (`mean max_e P_full(e) = {rc_all['mean_top_p_full']:.4f}`).",
            "",
            "| Tier | Accused Eps | Dropped `plant_canary` | Dropped `list_employees` | `P_full < 1/(1+V_known)` | `P_full <= 0.05` | Surfaced Canary Mismatch | Mean `P_full(accused)` |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for tier in CANONICAL_TIERS:
        trc = rc["by_tier"][tier]
        lines.append(
            f"| `{tier}` | {trc['accused_episodes']} | "
            f"{trc['dropped_plant_canary_turns']}/{trc['total_plant_canary_turns']} ({trc['dropped_plant_canary_frac']*100:.1f}%) | "
            f"{trc['dropped_list_employees_turns']}/{trc['total_list_employees_turns']} ({trc['dropped_list_employees_frac']*100:.1f}%) | "
            f"{trc['below_breakeven_count']}/{trc['accused_episodes']} ({trc['below_breakeven_frac']*100:.1f}%) | "
            f"{trc['p_le_005_count']}/{trc['accused_episodes']} ({trc['p_le_005_frac']*100:.1f}%) | "
            f"{trc['ruled_out_by_surfaced_canary_count']}/{trc['accused_episodes']} | "
            f"{trc['mean_p_full_accused']:.4f} |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Historical v3 Investigator GRPO Runs (V100 and Verda)",
            "",
            f"- **Attempt 1 (`slurm-44548.out` seed 0, `slurm-44550.out` seed 1)**: Both crashed at step 0 with `torch.OutOfMemoryError` "
            f"inside `{oom0['failure_site']}` on 32GB V100 (`44548` tried `{oom0['tried_allocate_gib']:.2f} GiB` with "
            f"`{oom0['process_in_use_gib']:.2f} GiB` in use; `44550` tried `{oom1['tried_allocate_gib']:.2f} GiB` with "
            f"`{oom1['process_in_use_gib']:.2f} GiB` in use).",
            f"- **Attempt 2 (`slurm-44553.out` seed 0)**: Gradient checkpointing fixed OOM, but across `{c44553['n_steps']}` steps "
            f"(`{c44553['elapsed_hours']:.3f}h`), `{c44553['steps_with_zero_var_group']}/{c44553['n_steps']}` steps had zero-variance groups "
            f"(all 2 groups had zero variance on `{c44553['steps_with_all_groups_zero_var']}/{c44553['n_steps']}` steps, "
            f"`mean_continue_frac = {c44553['mean_continue_frac']:.3f}`, `max_kl = {c44553['max_kl']:.5f}`), yielding near-zero policy gradient.",
            "",
            "| Curve Run | Source | Steps | Hours | Sec/Step | Mean Reward (Head -> Tail) | Gain vs Solver (Head -> Tail) | Valid Rate | Zero-Var Steps | Max KL |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for curve in (c44553, c44555, c44572, cverda):
        if curve.get("available"):
            lines.append(
                f"| `{curve['run_id']}` | `{curve['source']}` | {curve['n_steps']} | "
                f"{curve['elapsed_hours']:.3f} | {curve['mean_step_seconds']:.1f} | "
                f"{curve['mean_reward']:.4f} ({curve['head_mean_reward']:.4f} -> {curve['tail_mean_reward']:.4f}) | "
                f"{curve['mean_gain_vs_solver_valid']:.4f} ({curve['head_gain_vs_solver_valid']:.4f} -> {curve['tail_gain_vs_solver_valid']:.4f}) | "
                f"{curve['mean_valid_rate']:.4f} | {curve['steps_with_zero_var_group']}/{curve['n_steps']} | "
                f"{curve['max_kl']:.5f} |"
            )
        else:
            lines.append(
                f"| `{curve['run_id']}` | `{curve['source']}` | n/a (ref absent) | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
            )

    vm = report["verda_v3_complete_matrix"]
    pbase = vm["pooled_base"]
    pv2 = vm["pooled_v2"]
    pv3_4k = vm["v3_4k_family"]["pooled_v3_4k_s0"]
    s1_4k = vm["v3_4k_family"]["v3_4k_s1_partial"]
    spot_714d = vm["v3_4k_family"]["v3_4k_s1_spot_714d"]
    c8k = vm["v3_4k_s0_at_8k_confound"]
    r8k1 = vm["v3_8k_replicates"]["v3_8k_s1"]
    r8k2 = vm["v3_8k_replicates"]["v3_8k_s2"]
    r8k3 = vm["v3_8k_replicates"]["v3_8k_s3"]
    p8k = r8k3["truly_paired_8k_vs_4k_at_8k"]

    lines.extend(
        [
            "",
            f"{h3} 4b. Complete Verda and FR8 WS4 Matrix (v1.4 Held-Out)",
            "",
            f"- Disclosure: {vm['panel_fix_a_disclosure']}",
            f"- Pooled `base`: `n={pbase['n']}` (`44411` `n={pbase['components']['eval_44411']['n']}` + "
            f"`44584` `n={pbase['components']['eval_44584']['n']}`), score `{pbase['mean_score']:.3f} +/- {pbase['ci95']:.3f}`, "
            f"valid call rate `{pbase['valid_call_rate']:.2f}` (`100%` `eval_cap` on Day 1).",
            f"- Pooled `v2`: `n={pv2['n']}` (`44412` `n={pv2['components']['eval_44412']['n']}` `{pv2['components']['eval_44412']['mean_score']:.3f} +/- {pv2['components']['eval_44412']['ci95']:.3f}` + "
            f"`v2-off30` `n={pv2['components']['v2_off30']['n']}` `{pv2['components']['v2_off30']['mean_score']:.3f} +/- {pv2['components']['v2_off30']['ci95']:.3f}`), "
            f"pooled `{pv2['mean_score']:.3f} +/- {pv2['ci95']:.3f}` (accused `{pv2['accused_count']}/{pv2['n']} = {pv2['accused_rate']:.2f}`, precision `{pv2['correct_count']}/{pv2['accused_count']} = {pv2['precision_when_accused']:.2f}`).",
            f"- `v3-4k` family: pooled `v3-4k-s0` (`{pv3_4k['grpo_steps']}` GRPO steps) `n={pv3_4k['n']}` scored `{pv3_4k['mean_score']:.3f} +/- {pv3_4k['ci95']:.3f}` "
            f"(valid `{pv3_4k['valid_call_rate']:.2f}`, accused `{pv3_4k['accused_ratio']} = {pv3_4k['accused_rate']:.2f}`, "
            f"correct `{pv3_4k['correct_when_accused_ratio']} = {pv3_4k['precision_when_accused']:.2f}`, "
            f"`+{pv3_4k['two_sample_delta_vs_v2']['mean_delta']:.3f} +/- {pv3_4k['two_sample_delta_vs_v2']['ci95']:.3f}` two-sample vs `v2`); "
            f"FR8 V100 `v3-4k-s1` partial (`{s1_4k['grpo_steps']}` steps, `n={s1_4k['n']}`) scored `{s1_4k['mean_score']:.3f} +/- {s1_4k['ci95']:.3f}`; "
            f"Verda spot `{spot_714d['verda_instance']}` was preempted after `~{spot_714d['approx_train_minutes']}m` (`n={spot_714d['n']}`).",
            f"- Inference-length confound (`{c8k['label']}`, shared secret `{c8k['shared_world_secret']}`): re-evaluating the exact `4k`-trained adapter (`{c8k['adapter_sha256_12']}`) "
            f"at `max_ctx={c8k['eval_context_len']}` (`n={c8k['n']}`) dropped score to `{c8k['mean_score']:.3f} +/- {c8k['ci95']:.3f}` "
            f"(`{c8k['two_sample_delta_vs_4k']['mean_delta']:+.3f} +/- {c8k['two_sample_delta_vs_4k']['ci95']:.3f}` vs `4k`), "
            f"flipping medium/hard accusations to `{c8k['by_tier_accused_rate']['medium']:.2f}` / `{c8k['by_tier_accused_rate']['hard']:.2f}` (`0` correct).",
            f"- `v3-8k` replicates (`n=90` each): `v3-8k-s1` (`{r8k1['grpo_steps']}` steps) over-accused (`{r8k1['mean_score']:.3f} +/- {r8k1['ci95']:.3f}`, accused `{r8k1['accused_rate']:.2f}`), "
            f"`v3-8k-s2` (`{r8k2['grpo_steps']}` steps) collapsed to abstention (`{r8k2['mean_score']:.3f} +/- {r8k2['ci95']:.3f}`, abstain `{r8k2['abstain_rate']:.2f}`), "
            f"and `v3-8k-s3` (`{r8k3['grpo_steps']}` steps, shared secret `{r8k3['shared_world_secret']}`) scored `{r8k3['mean_score']:.3f} +/- {r8k3['ci95']:.3f}`; "
            f"truly paired `8k`-trained vs `4k`-trained at `8k` (`{p8k['matching_step0_rosters']}` matching rosters) = `{p8k['mean_delta']:+.3f} +/- {p8k['ci95']:.3f}`.",
            "",
            "| Run / Slice | Ctx | Steps | Held-Out N | Seed Span | World Secret | Mean Score (+/- CI95) | Valid | Accused | Correct | Key Comparison / Status |",
            "| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- |",
            f"| `base` (pooled) | 4096 | 0 | {pbase['n']} | `{pbase['audited_seed_span']}` | unpaired (`f272803c`+`404f83e6`) | {pbase['mean_score']:.3f} +/- {pbase['ci95']:.3f} | {pbase['valid_call_rate']:.2f} | {pbase['accused_rate']:.2f} | 0/{pbase['n']} | `44411` n=16 + `44584` n=20 (`eval_cap`) |",
            f"| `v2` (pooled) | 4096 | 887 | {pv2['n']} | `{pv2['audited_seed_span']}` | unpaired (`c86b9c8a`+`68bbe201`) | {pv2['mean_score']:.3f} +/- {pv2['ci95']:.3f} | {pv2['valid_call_rate']:.2f} | {pv2['accused_rate']:.2f} | {pv2['correct_count']}/{pv2['accused_count']} ({pv2['precision_when_accused']:.2f}) | `44412` n=82 (-0.395) + `v2-off30` n=90 (-0.514) |",
            f"| `v3-4k-s0` (pooled) | 4096 | {pv3_4k['grpo_steps']} | {pv3_4k['n']} | `{pv3_4k['audited_seed_span']}` | unpaired (`3bb74f5a`+`68bbe201`) | {pv3_4k['mean_score']:.3f} +/- {pv3_4k['ci95']:.3f} | {pv3_4k['valid_call_rate']:.2f} | {pv3_4k['accused_rate']:.2f} | {pv3_4k['correct_when_accused_ratio']} ({pv3_4k['precision_when_accused']:.2f}) | +{pv3_4k['two_sample_delta_vs_v2']['mean_delta']:.3f} +/- {pv3_4k['two_sample_delta_vs_v2']['ci95']:.3f} vs `v2` |",
            f"| `v3-4k-s1` (`44572`) | 4096 | {s1_4k['grpo_steps']} | {s1_4k['n']} | `{s1_4k['audited_seed_span']}` | unpaired (`09f8bc64`) | {s1_4k['mean_score']:.3f} +/- {s1_4k['ci95']:.3f} | {s1_4k['valid_call_rate']:.2f} | {s1_4k['accused_rate']:.2f} | 0/{s1_4k['accused_count']} | Partial FR8 V100 eval (`44573`) |",
            f"| `v3-4k-s1-spot` (`714d`) | 4096 | ~30m | {spot_714d['n']} | n/a | n/a | n/a | n/a | n/a | n/a | Verda A100 spot preempted (`714d8144`) |",
            f"| `v3-4k-s0@8k` | 8192 | {c8k['grpo_steps']} | {c8k['n']} | `{c8k['audited_seed_span']}` | shared (`{c8k['shared_world_secret']}`) | {c8k['mean_score']:.3f} +/- {c8k['ci95']:.3f} | {c8k['valid_call_rate']:.2f} | {c8k['accused_rate']:.2f} | {c8k['correct_count']}/{c8k['accused_count']} | {c8k['two_sample_delta_vs_4k']['mean_delta']:+.3f} +/- {c8k['two_sample_delta_vs_4k']['ci95']:.3f} vs `4k` (ctx confound) |",
            f"| `v3-8k-s1` (`ac58`) | 8192 | {r8k1['grpo_steps']} | {r8k1['n']} | `{r8k1['audited_seed_span']}` | unpaired (`ac58df04`) | {r8k1['mean_score']:.3f} +/- {r8k1['ci95']:.3f} | {r8k1['valid_call_rate']:.2f} | {r8k1['accused_rate']:.2f} | {r8k1['correct_count']}/{r8k1['accused_count']} | Off-policy 8k over-accusation |",
            f"| `v3-8k-s2` (`dbd0`) | 8192 | {r8k2['grpo_steps']} | {r8k2['n']} | `{r8k2['audited_seed_span']}` | unpaired (`dbd083ca`) | {r8k2['mean_score']:.3f} +/- {r8k2['ci95']:.3f} | {r8k2['valid_call_rate']:.2f} | {r8k2['accused_rate']:.2f} | {r8k2['correct_count']}/{r8k2['accused_count']} | 93% abstention collapse |",
            f"| `v3-8k-s3` (`f437`) | 8192 | {r8k3['grpo_steps']} | {r8k3['n']} | `{r8k3['audited_seed_span']}` | shared (`{r8k3['shared_world_secret']}`) | {r8k3['mean_score']:.3f} +/- {r8k3['ci95']:.3f} | {r8k3['valid_call_rate']:.2f} | {r8k3['accused_rate']:.2f} | {r8k3['correct_count']}/{r8k3['accused_count']} | Paired vs `4k@8k`: {p8k['mean_delta']:+.3f} +/- {p8k['ci95']:.3f} |",
            "",
            f"{h2} 5. Design Requirements Derived for Next-Gen Tiebreaker",
            "",
        ]
    )
    for idx, lesson in enumerate(report["lessons_for_tiebreak_v4"], start=1):
        lines.append(f"{idx}. {lesson}")

    lines.append("")
    return "\n".join(lines)


def validate_report(report: dict[str, Any], md_text: str | None = None) -> list[str]:
    errors: list[str] = []
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)

    raw_json = json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False)
    if em_dash in raw_json or en_dash in raw_json:
        errors.append("JSON contains forbidden em/en dash characters")
    if len(raw_json.encode("utf-8")) > MAX_JSON_BYTES:
        errors.append(f"JSON exceeds {MAX_JSON_BYTES} bytes")

    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unexpected schema_version: {report.get('schema_version')!r}")

    for req_key in (
        "j4_runs",
        "unpaired_secret_audit",
        "ws4_v2_root_cause",
        "v3_grpo_runs",
        "verda_v3_complete_matrix",
        "lessons_for_tiebreak_v4",
    ):
        if req_key not in report:
            errors.append(f"missing top-level key: {req_key}")
    if errors:
        return errors

    v2_train = report["j4_runs"]["ws4_v2_44410"]["train"]
    if v2_train["header_tokens"] + v2_train["body_budget_tokens"] != v2_train["max_len"]:
        errors.append("ws4_v2 header_tokens + body_budget_tokens != max_len")

    sec = report["unpaired_secret_audit"]
    if not sec.get("eval_44411_base_sha256") or not sec.get("eval_44412_v2_sha256"):
        errors.append("missing eval_44411 or eval_44412 world_secret_sha256")
    elif sec["eval_44411_base_sha256"] == sec["eval_44412_v2_sha256"]:
        if sec.get("paired") is not True:
            errors.append("paired flag false despite identical secrets")
    else:
        if sec.get("paired") is not False:
            errors.append("paired flag must be False when eval_44411 and eval_44412 secrets differ")

    v2_ep = report["j4_runs"]["ws4_v2_44410"]["eval_v2_44412"]["episodes"]
    v2_all = v2_ep["overall"]
    if v2_all["accused_count"] + v2_all["abstain_count"] != v2_all["n"]:
        errors.append("v2 accused_count + abstain_count != n")
    if v2_ep["by_tier"]:
        tier_sum = sum(t["n"] for t in v2_ep["by_tier"].values())
        if tier_sum != v2_all["n"]:
            errors.append(f"v2 by_tier n sum {tier_sum} != overall n {v2_all['n']}")

    rc = report["ws4_v2_root_cause"]
    rc_all = rc["overall"]
    n_acc = rc_all["accused_episodes"]
    if n_acc != v2_all["accused_count"]:
        errors.append(f"root_cause accused_episodes {n_acc} != v2 accused_count {v2_all['accused_count']}")
    if rc_all["dropped_plant_canary_turns"] > rc_all["total_plant_canary_turns"]:
        errors.append("dropped_plant_canary_turns exceeds total_plant_canary_turns")
    if rc_all["dropped_list_employees_turns"] > rc_all["total_list_employees_turns"]:
        errors.append("dropped_list_employees_turns exceeds total_list_employees_turns")
    if n_acc > 0:
        if round(rc_all["below_breakeven_count"] / n_acc, 4) != rc_all["below_breakeven_frac"]:
            errors.append("below_breakeven_frac mismatch")
        if round(rc_all["p_le_005_count"] / n_acc, 4) != rc_all["p_le_005_frac"]:
            errors.append("p_le_005_frac mismatch")

    v3 = report["v3_grpo_runs"]
    if len(v3.get("attempt1_cuda_oom", [])) != 2:
        errors.append("expected 2 CUDA OOM logs in attempt1_cuda_oom")
    for curve_key in ("attempt2_zero_variance_44553", "v100_curve_44555", "v100_curve_44572"):
        c = v3.get(curve_key, {})
        if not c.get("available") or int(c.get("n_steps", 0)) < 1:
            errors.append(f"curve {curve_key} missing steps")

    verda_c = v3.get("verda_curve_s0", {})
    if "available" not in verda_c:
        errors.append("verda_curve_s0 missing available boolean")

    vm = report["verda_v3_complete_matrix"]
    if "post-hoc locked" not in str(vm.get("panel_fix_a_disclosure", "")):
        errors.append("verda_v3_complete_matrix missing Panel Fix A post-hoc locked disclosure")
    pbase = vm.get("pooled_base") or {}
    if pbase.get("n") != 36 or pbase.get("mean_score") != 0.0 or pbase.get("valid_call_rate") != 0.03:
        errors.append("pooled_base mismatch in verda_v3_complete_matrix")
    pv2 = vm.get("pooled_v2") or {}
    if pv2.get("n") != 172 or pv2.get("mean_score") != -0.457 or pv2.get("ci95") != 0.086:
        errors.append("pooled_v2 mismatch in verda_v3_complete_matrix")
    v3_fam = vm.get("v3_4k_family") or {}
    ps0 = v3_fam.get("pooled_v3_4k_s0") or {}
    if (
        ps0.get("n") != 180
        or ps0.get("mean_score") != -0.147
        or ps0.get("ci95") != 0.063
        or ps0.get("accused_count") != 38
        or ps0.get("correct_count") != 6
        or (ps0.get("two_sample_delta_vs_v2") or {}).get("mean_delta") != 0.31
    ):
        errors.append("pooled_v3_4k_s0 mismatch in verda_v3_complete_matrix")
    s1_part = v3_fam.get("v3_4k_s1_partial") or {}
    if s1_part.get("grpo_steps") != 192 or s1_part.get("n") != 25 or s1_part.get("mean_score") != -0.24:
        errors.append("v3_4k_s1_partial mismatch in verda_v3_complete_matrix")
    spot_714d = v3_fam.get("v3_4k_s1_spot_714d") or {}
    if spot_714d.get("spot_preempted") is not True or spot_714d.get("n") != 0:
        errors.append("v3_4k_s1_spot_714d mismatch in verda_v3_complete_matrix")
    c8k = vm.get("v3_4k_s0_at_8k_confound") or {}
    if (
        c8k.get("shared_world_secret") != "1ca0c2a64d"
        or c8k.get("n") != 90
        or c8k.get("mean_score") != -0.716
        or (c8k.get("two_sample_delta_vs_4k") or {}).get("mean_delta") != -0.568
    ):
        errors.append("v3_4k_s0_at_8k_confound mismatch in verda_v3_complete_matrix")
    r8k = vm.get("v3_8k_replicates") or {}
    if (r8k.get("v3_8k_s1") or {}).get("mean_score") != -0.777:
        errors.append("v3_8k_s1 mismatch in verda_v3_complete_matrix")
    if (r8k.get("v3_8k_s2") or {}).get("mean_score") != -0.05:
        errors.append("v3_8k_s2 mismatch in verda_v3_complete_matrix")
    r8k3 = r8k.get("v3_8k_s3") or {}
    p8k = r8k3.get("truly_paired_8k_vs_4k_at_8k") or {}
    if (
        r8k3.get("shared_world_secret") != "1ca0c2a64d"
        or r8k3.get("mean_score") != -0.788
        or p8k.get("mean_delta") != -0.073
        or p8k.get("ci95") != 0.173
    ):
        errors.append("v3_8k_s3 paired comparison mismatch in verda_v3_complete_matrix")

    if md_text is not None:
        if em_dash in md_text or en_dash in md_text:
            errors.append("Markdown contains forbidden em/en dash characters")
        expected_md = render_markdown(report)
        if md_text != expected_md:
            errors.append("Markdown text does not match deterministic render_markdown(report)")

    return errors


def verify_committed_artifacts(json_path: Path, md_path: Path | None = None) -> list[str]:
    if not json_path.exists():
        return [f"JSON file not found: {json_path}"]
    report = json.loads(json_path.read_text(encoding="utf-8"))
    resolved_md = md_path if md_path is not None else json_path.with_suffix(".md")
    if not resolved_md.exists():
        return [f"Markdown file not found: {resolved_md}"]
    md_text = resolved_md.read_text(encoding="utf-8")
    return validate_report(report, md_text=md_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forensics audit of prior J4/WS4/v3 tiebreaker runs.")
    parser.add_argument("--j4-dir", type=Path, default=DEFAULT_J4_DIR)
    parser.add_argument("--v3-dir", type=Path, default=DEFAULT_V3_DIR)
    parser.add_argument("--verda-git-spec", type=str, default=DEFAULT_VERDA_GIT_SPEC)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--verify-json", type=Path, default=None)
    parser.add_argument("--verify-md", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.verify_json is not None:
        errs = verify_committed_artifacts(args.verify_json, md_path=args.verify_md)
        if errs:
            for err in errs:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        print(f"OK: verified {args.verify_json}")
        return 0

    report = build_forensics_report(
        j4_dir=args.j4_dir,
        v3_dir=args.v3_dir,
        verda_git_spec=args.verda_git_spec,
    )
    md_text = render_markdown(report)
    errs = validate_report(report, md_text=md_text)
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    args.out_md.write_text(md_text, encoding="utf-8")
    print(f"Wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
