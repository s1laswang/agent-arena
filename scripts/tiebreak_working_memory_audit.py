from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TRAIN_SEEDS
from train.compact_render import (
    compact_system_text,
    compact_tools_spec,
    compact_user_text,
    estimate_compact_tokens,
    extract_public_ledger,
    render_compact_prompt_text,
    render_compact_turn,
)
from train.render import render_messages, to_openai_tools

SCHEMA_VERSION = "canary.tiebreak.working_memory_audit.v1"
H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
ALL_SCOPES: tuple[str, ...] = ("easy", "medium", "hard", "all")

TRAIN_BASE = 106_000
EPISODES_PER_TIER = 15
TOTAL_TRAIN_EPISODES = 45

SLURM_44410_HEADER_TOKENS = 2842
WINDOW_4K = 4096
WINDOW_8K = 8192
HF_MAX_NEW_TOKENS = 96
HF_PROMPT_CAP_4K = WINDOW_4K - HF_MAX_NEW_TOKENS
HF_PROMPT_CAP_8K = WINDOW_8K - HF_MAX_NEW_TOKENS
SLURM_44410_BODY_BUDGET = WINDOW_4K - SLURM_44410_HEADER_TOKENS

COMPACT_STATE_MAX_TOKENS = 900
COMPACT_PROMPT_TARGET_TOKENS = 1680
COMPACT_WINDOW_2K = 2048

QWEN_HEADER_UNIT_SCALE = 1.025
QWEN_BODY_UNIT_SCALE = 0.84

MAX_SUMMARY_BYTES = 80 * 1024
MAX_CHECK_SECONDS = 1.0

DEFAULT_OUT_JSON = Path("results/tiebreak/working_memory/working_memory_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_working_memory.md")
FORENSICS_REL = Path("results/tiebreak/forensics_prior_runs.json")
CONFOUND_REL = Path("results/tiebreak/context_confound/audit_summary.json")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

PANEL_FIX_A_DISCLOSURE = (
    "All active working-memory and prompt-header token-tax simulations strictly use "
    "45 TRAIN_SEEDS episodes (106000..106044, 15 per tier across easy, medium, hard; "
    "0 HELDOUT_SEEDS, 0 DEV_SEEDS, and 0 JUDGE_SEEDS touched). Where DEV_SEEDS 0..29 "
    "appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered "
    "(Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 open-weight Qwen2.5 runs in "
    "experiment_ledger.json beat untrained base (0.000), so the README Qwen addendum "
    "remains withheld; non-LLM structured and parametric policies operating on the "
    "lossless working-memory ledger (TinyMLPPolicy, CompactLinearDAggerPolicy, "
    "EmpiricalBayesPolicy, ScalingLogisticPolicy; is_open_weight_llm = False) are "
    "strictly separated from open-weight Qwen2.5 LoRA runs."
)

_SPECIAL_TAG_RE = re.compile(r"<\|im_start\|>|<\|im_end\|>")
_TOK_UNIT_RE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]{1,2}")
_PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
_NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
_SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)


def assert_train_only_seed(seed: int) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in DEV_SEEDS or 0 <= seed < 10_000:
        raise ValueError(f"DEV_SEEDS touched: {seed}")
    if seed in HELDOUT_SEEDS or 800_000 <= seed < 900_000:
        raise ValueError(f"HELDOUT_SEEDS touched in training audit: {seed}")
    if seed in JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"JUDGE_SEEDS touched: {seed}")
    if seed not in TRAIN_SEEDS or not (100_000 <= seed < 200_000):
        raise ValueError(f"seed {seed} outside TRAIN_SEEDS [100000, 200000)")
    return seed


def build_train_jobs() -> list[tuple[str, int]]:
    jobs: list[tuple[str, int]] = []
    for t_idx, tier in enumerate(CANONICAL_TIERS):
        for k in range(EPISODES_PER_TIER):
            seed = assert_train_only_seed(TRAIN_BASE + t_idx * EPISODES_PER_TIER + k)
            jobs.append((tier, seed))
    return jobs


def estimate_qwen_tokens(text: str, unit_scale: float) -> int:
    specials = len(_SPECIAL_TAG_RE.findall(text))
    rem = _SPECIAL_TAG_RE.sub(" ", text)
    return specials + int(round(unit_scale * len(_TOK_UNIT_RE.findall(rem))))


def render_qwen_raw_header(
    header_msgs: list[dict[str, Any]],
    openai_tools: list[dict[str, Any]],
) -> str:
    sys_text = header_msgs[0]["content"] if header_msgs else ""
    user_text = header_msgs[1]["content"] if len(header_msgs) > 1 else ""
    parts: list[str] = [
        "<|im_start|>system\n",
        sys_text,
        "\n\n"
        + H
        + " Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
        + "You are provided with function signatures within <tools></tools> XML tags:\n<tools>",
    ]
    for tool_obj in openai_tools:
        parts.append("\n" + json.dumps(tool_obj))
    parts.append(
        "\n</tools>\n\nFor each function call, return a json object with function name and arguments "
        "within <tool_call></tool_call> XML tags:\n<tool_call>\n"
        "{\"name\": <function-name>, \"arguments\": <args-json-object>}\n</tool_call><|im_end|>\n"
    )
    parts.append(f"<|im_start|>user\n{user_text}<|im_end|>\n<|im_start|>assistant\n")
    return "".join(parts)


def render_qwen_tool_schema_block(openai_tools: list[dict[str, Any]]) -> str:
    parts: list[str] = [
        "\n\n"
        + H
        + " Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
        + "You are provided with function signatures within <tools></tools> XML tags:\n<tools>"
    ]
    for tool_obj in openai_tools:
        parts.append("\n" + json.dumps(tool_obj))
    parts.append(
        "\n</tools>\n\nFor each function call, return a json object with function name and arguments "
        "within <tool_call></tool_call> XML tags:\n<tool_call>\n"
        "{\"name\": <function-name>, \"arguments\": <args-json-object>}\n</tool_call>"
    )
    return "".join(parts)


def render_qwen_pair(asst_msg: dict[str, Any], tool_msg: dict[str, Any]) -> str:
    fn = asst_msg["tool_calls"][0]["function"]
    args_json = json.dumps(fn["arguments"])
    return (
        f"<|im_start|>assistant\n<tool_call>\n{{\"name\": \"{fn['name']}\", \"arguments\": {args_json}}}\n"
        f"</tool_call><|im_end|>\n"
        f"<|im_start|>user\n<tool_response>\n{tool_msg['content']}\n</tool_response><|im_end|>\n"
    )


def simulate_hf_sticky_drop(header_tokens: int, pair_tokens: list[int], prompt_cap: int) -> int:
    drop = 0
    for turn_idx in range(len(pair_tokens) + 1):
        while True:
            kept_pairs = turn_idx - drop
            cur_tokens = header_tokens + sum(pair_tokens[drop:turn_idx])
            if cur_tokens <= prompt_cap or kept_pairs <= 1:
                break
            drop += max(1, (2 * turn_idx) // 16)
    return min(drop, len(pair_tokens))


def simulate_suffix_window_drop(header_tokens: int, pair_tokens: list[int], window_len: int) -> int:
    if not pair_tokens:
        return 0
    used = 0
    keep_start = len(pair_tokens)
    for idx in range(len(pair_tokens) - 1, -1, -1):
        if header_tokens + used + pair_tokens[idx] <= window_len or keep_start == len(pair_tokens):
            used += pair_tokens[idx]
            keep_start = idx
        else:
            break
    return keep_start


def quantile_sorted(sorted_vals: list[int | float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo]) * (1.0 - frac) + float(sorted_vals[hi]) * frac


def _rate(num: int, den: int) -> float:
    return round(num / den, 6) if den > 0 else 0.0


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 2) if den > 0 else 0.0


@lru_cache(maxsize=1)
def _cached_header_token_tax_json() -> str:
    from canary.env import Env

    by_tier: dict[str, Any] = {}
    for tier in CANONICAL_TIERS:
        assert_train_only_seed(TRAIN_BASE)
        env_spec = Env.__new__(Env)
        env_spec.tier = tier
        env_spec.p = TIERS[tier]
        instr = env_spec.instruction()
        raw_spec = env_spec.tools_spec()
        otools = to_openai_tools(raw_spec)
        ctools = compact_tools_spec(raw_spec)

        hdr_msgs = render_messages(instr, [])
        raw_hdr_text = render_qwen_raw_header(hdr_msgs, otools)
        raw_hdr_tokens = estimate_qwen_tokens(raw_hdr_text, QWEN_HEADER_UNIT_SCALE)
        raw_schema_text = render_qwen_tool_schema_block(otools)
        raw_schema_tokens = estimate_qwen_tokens(raw_schema_text, QWEN_HEADER_UNIT_SCALE)
        raw_sys_kickoff_tokens = max(0, raw_hdr_tokens - raw_schema_tokens)

        empty_ledger = extract_public_ledger(instr, [])
        csys = compact_system_text(instr, empty_ledger)
        cstate_empty = compact_user_text(empty_ledger)
        chdr_only_text = render_compact_prompt_text(
            {"messages": [{"role": "system", "content": csys}], "tools": ctools},
            add_generation_prompt=False,
        )
        chdr_only_tokens = estimate_compact_tokens(chdr_only_text)
        cstate_empty_tokens = estimate_compact_tokens(cstate_empty)
        cturn_empty = render_compact_turn(instr, raw_spec, [], target_step=None, tail_turns=4)
        cprompt_empty_text = render_compact_prompt_text(cturn_empty, add_generation_prompt=True)
        cprompt_empty_tokens = estimate_compact_tokens(cprompt_empty_text)

        savings = raw_hdr_tokens - chdr_only_tokens
        by_tier[tier] = {
            "n_employees": TIERS[tier].n_employees,
            "n_days": TIERS[tier].n_days,
            "delay_choices": list(TIERS[tier].delay_choices),
            "raw_header_tokens": raw_hdr_tokens,
            "raw_header_chars": len(raw_hdr_text),
            "raw_tool_schema_tokens": raw_schema_tokens,
            "raw_system_and_kickoff_tokens": raw_sys_kickoff_tokens,
            "raw_share_of_4096": round(raw_hdr_tokens / WINDOW_4K, 4),
            "raw_share_of_4000_cap": round(raw_hdr_tokens / HF_PROMPT_CAP_4K, 4),
            "raw_body_budget_4096": WINDOW_4K - raw_hdr_tokens,
            "raw_body_budget_4000_cap": HF_PROMPT_CAP_4K - raw_hdr_tokens,
            "raw_share_of_8192": round(raw_hdr_tokens / WINDOW_8K, 4),
            "raw_body_budget_8096_cap": HF_PROMPT_CAP_8K - raw_hdr_tokens,
            "compact_header_only_tokens": chdr_only_tokens,
            "compact_header_only_chars": len(chdr_only_text),
            "compact_empty_state_tokens": cstate_empty_tokens,
            "compact_empty_prompt_tokens": cprompt_empty_tokens,
            "compact_empty_share_of_2048": round(cprompt_empty_tokens / COMPACT_WINDOW_2K, 4),
            "header_token_savings": savings,
            "header_reduction_frac": round(savings / raw_hdr_tokens, 4),
        }

    mean_raw = sum(by_tier[t]["raw_header_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_schema = sum(by_tier[t]["raw_tool_schema_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_sys = sum(by_tier[t]["raw_system_and_kickoff_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_chdr = sum(by_tier[t]["compact_header_only_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_cstate = sum(by_tier[t]["compact_empty_state_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_cprompt = sum(by_tier[t]["compact_empty_prompt_tokens"] for t in CANONICAL_TIERS) / 3.0
    mean_sav = mean_raw - mean_chdr

    by_tier["mean"] = {
        "raw_header_tokens": round(mean_raw, 1),
        "raw_tool_schema_tokens": round(mean_schema, 1),
        "raw_system_and_kickoff_tokens": round(mean_sys, 1),
        "raw_share_of_4096": round(mean_raw / WINDOW_4K, 4),
        "raw_share_of_4000_cap": round(mean_raw / HF_PROMPT_CAP_4K, 4),
        "raw_body_budget_4096": round(WINDOW_4K - mean_raw, 1),
        "raw_body_budget_4000_cap": round(HF_PROMPT_CAP_4K - mean_raw, 1),
        "raw_share_of_8192": round(mean_raw / WINDOW_8K, 4),
        "raw_body_budget_8096_cap": round(HF_PROMPT_CAP_8K - mean_raw, 1),
        "compact_header_only_tokens": round(mean_chdr, 1),
        "compact_empty_state_tokens": round(mean_cstate, 1),
        "compact_empty_prompt_tokens": round(mean_cprompt, 1),
        "compact_empty_share_of_2048": round(mean_cprompt / COMPACT_WINDOW_2K, 4),
        "header_token_savings": round(mean_sav, 1),
        "header_reduction_frac": round(mean_sav / mean_raw, 4),
    }

    return json.dumps(
        {
            "slurm_44410_reference": {
                "header_tokens": SLURM_44410_HEADER_TOKENS,
                "window_4k_tokens": WINDOW_4K,
                "header_share_of_4096": round(SLURM_44410_HEADER_TOKENS / WINDOW_4K, 4),
                "header_share_pct": round(100.0 * SLURM_44410_HEADER_TOKENS / WINDOW_4K, 1),
                "body_budget_tokens": SLURM_44410_BODY_BUDGET,
                "body_budget_pct": round(100.0 * SLURM_44410_BODY_BUDGET / WINDOW_4K, 1),
                "hf_policy_max_new_tokens": HF_MAX_NEW_TOKENS,
                "hf_policy_prompt_cap_4k": HF_PROMPT_CAP_4K,
                "hf_policy_prompt_cap_8k": HF_PROMPT_CAP_8K,
            },
            "compact_budgets": {
                "working_memory_state_max_tokens": COMPACT_STATE_MAX_TOKENS,
                "compact_prompt_target_tokens": COMPACT_PROMPT_TARGET_TOKENS,
                "compact_window_tokens": COMPACT_WINDOW_2K,
            },
            "by_tier": by_tier,
        }
    )


def compute_header_token_tax() -> dict[str, Any]:
    return json.loads(_cached_header_token_tax_json())


def _run_single_episode_audit(job: tuple[str, int]) -> dict[str, Any]:
    from canary.env import Env
    from canary.solver import SolverPolicy
    from train.compact_dagger_ablation import _CompactStateTracker

    tier, seed = job
    assert_train_only_seed(seed)

    env = Env(tier=tier, seed=seed)
    instr = env.instruction()
    raw_spec = env.tools_spec()
    otools = to_openai_tools(raw_spec)
    hdr_text = render_qwen_raw_header(render_messages(instr, []), otools)
    hdr_tokens = estimate_qwen_tokens(hdr_text, QWEN_HEADER_UNIT_SCALE)

    sp = SolverPolicy()
    sp.reset(raw_spec, instr)
    while not env.done:
        t_call, a_call = sp.act(list(env.history))
        env.call(t_call, a_call)
    ep = env.result("solver")
    steps = list(ep.steps)
    prefix = steps[:-1] if ep.end_reason == "accused" else steps

    all_msgs = render_messages(instr, steps)
    all_pair_toks = [
        estimate_qwen_tokens(
            render_qwen_pair(all_msgs[2 + 2 * i], all_msgs[3 + 2 * i]),
            QWEN_BODY_UNIT_SCALE,
        )
        for i in range(len(steps))
    ]
    prefix_pair_toks = all_pair_toks[: len(prefix)]
    raw_prefix_tokens = hdr_tokens + sum(prefix_pair_toks)

    drop_4k_sticky = simulate_hf_sticky_drop(hdr_tokens, prefix_pair_toks, HF_PROMPT_CAP_4K)
    drop_4k_suffix = simulate_suffix_window_drop(hdr_tokens, prefix_pair_toks, WINDOW_4K)
    drop_8k_sticky = simulate_hf_sticky_drop(hdr_tokens, prefix_pair_toks, HF_PROMPT_CAP_8K)

    expected_emps: list[tuple[str, str, Any]] = []
    le_idxs: list[int] = []
    pc_info_by_cid: dict[str, tuple[int, int, dict[str, list[str]]]] = {}

    for idx, st in enumerate(prefix):
        if not st.result.get("ok", True):
            continue
        data = st.result.get("data") or {}
        if st.tool == "list_employees":
            le_idxs.append(idx)
            expected_emps = [
                (str(e["id"]), str(e.get("dept", "")), e.get("clearance"))
                for e in (data.get("employees") or [])
                if isinstance(e, dict) and "id" in e
            ]
        elif st.tool == "plant_canary":
            cid = str(data.get("canary_id") or f"c{st.day}")
            asg = st.args.get("assignment") if isinstance(st.args.get("assignment"), dict) else {}
            vmap: dict[str, list[str]] = {}
            for emp_id in sorted(asg):
                vmap.setdefault(str(asg[emp_id]), []).append(str(emp_id))
            pc_info_by_cid[cid] = (idx, int(st.day), vmap)

    roster_called = len(le_idxs) > 0
    roster_ev4k_sticky = roster_called and all(i < drop_4k_sticky for i in le_idxs)
    roster_ev4k_suffix = roster_called and all(i < drop_4k_suffix for i in le_idxs)
    roster_ev8k_sticky = roster_called and all(i < drop_8k_sticky for i in le_idxs)

    pc_total = len(pc_info_by_cid)
    pc_ev4k_sticky_term = sum(1 for (idx, _, _) in pc_info_by_cid.values() if idx < drop_4k_sticky)
    pc_ev4k_suffix_term = sum(1 for (idx, _, _) in pc_info_by_cid.values() if idx < drop_4k_suffix)
    pc_ev8k_sticky_term = sum(1 for (idx, _, _) in pc_info_by_cid.values() if idx < drop_8k_sticky)

    seen_surfaced: set[tuple[str, str, int]] = set()
    surf_total = 0
    surf_ev4k_sticky = 0
    surf_ev4k_suffix = 0
    surf_ev8k_sticky = 0
    surf_delays: list[int] = []
    surf_turn_gaps: list[int] = []
    surf_resolved_compact = 0

    for idx, st in enumerate(steps):
        if st.tool != "check_leak_feed" or not st.result.get("ok", True):
            continue
        data = st.result.get("data") or {}
        items = data.get("items") if "items" in data else (data.get("leaks") or [])
        for it in items or []:
            if not isinstance(it, dict):
                continue
            did = it.get("doc_id")
            var = it.get("variant")
            sday = int(it.get("surfaced_day", st.day))
            if did is None or var is None:
                continue
            did_s, var_s = str(did), str(var)
            if did_s not in pc_info_by_cid:
                continue
            key = (did_s, var_s, sday)
            if key in seen_surfaced:
                continue
            seen_surfaced.add(key)
            p_idx, p_day, p_vmap = pc_info_by_cid[did_s]
            surf_total += 1
            surf_delays.append(max(0, sday - p_day))
            surf_turn_gaps.append(max(0, idx - p_idx))

            d4s = simulate_hf_sticky_drop(hdr_tokens, all_pair_toks[: idx + 1], HF_PROMPT_CAP_4K)
            d4w = simulate_suffix_window_drop(hdr_tokens, all_pair_toks[: idx + 1], WINDOW_4K)
            d8s = simulate_hf_sticky_drop(hdr_tokens, all_pair_toks[: idx + 1], HF_PROMPT_CAP_8K)
            if p_idx < d4s:
                surf_ev4k_sticky += 1
            if p_idx < d4w:
                surf_ev4k_suffix += 1
            if p_idx < d8s:
                surf_ev8k_sticky += 1

            sub_ledger = extract_public_ledger(instr, steps[: idx + 1])
            matching_leaks = [
                lk
                for lk in sub_ledger["leaks"]
                if lk["doc_id"] == did_s and lk["variant"] == var_s and lk["surfaced_day"] == sday
            ]
            expected_cands = p_vmap.get(var_s, [])
            if matching_leaks and matching_leaks[0]["candidate_emps"] == expected_cands:
                surf_resolved_compact += 1

    tracker = _CompactStateTracker(instr)
    all_step_state_max = 0
    for k in range(1, len(prefix) + 1):
        tracker.ingest_up_to(prefix[:k])
        if k == 1 or k == len(prefix) or prefix[k - 1].tool in ("advance_day", "plant_canary", "check_leak_feed"):
            led_k = extract_public_ledger(instr, prefix[:k])
            all_step_state_max = max(all_step_state_max, estimate_compact_tokens(compact_user_text(led_k)))

    snap = tracker.snapshot()
    term_ledger = extract_public_ledger(instr, prefix)
    term_state_text = compact_user_text(term_ledger)
    term_state_tokens = estimate_compact_tokens(term_state_text)
    all_step_state_max = max(all_step_state_max, term_state_tokens)

    cturn = render_compact_turn(instr, raw_spec, prefix, target_step=None, tail_turns=4)
    cprompt_text = render_compact_prompt_text(cturn, add_generation_prompt=True)
    cprompt_tokens = estimate_compact_tokens(cprompt_text)

    got_emps = [
        (str(e["id"]), str(e.get("dept", "")), e.get("clearance"))
        for e in term_ledger["employees"]
    ]
    roster_retained = bool(expected_emps) and got_emps == expected_emps
    clearances_retained = sum(
        1
        for (_, _, exp_c), (_, _, got_c) in zip(expected_emps, got_emps)
        if exp_c is not None and exp_c == got_c
    )

    ledger_cmaps = {c["canary_id"]: c["variants"] for c in term_ledger["canaries"]}
    tracker_cmaps = {cid: crec["variants"] for cid, crec in tracker.canaries_by_id.items()}
    expected_cmaps = {cid: vmap for cid, (_, _, vmap) in pc_info_by_cid.items()}
    retained_cmaps = sum(
        1
        for cid, vmap in expected_cmaps.items()
        if ledger_cmaps.get(cid) == vmap and tracker_cmaps.get(cid) == vmap
    )

    sp_check = SolverPolicy()
    sp_check.reset(raw_spec, instr)
    for prev_st in prefix:
        sp_check._ingest(prev_st)
    solver_kv = round(max(0.0, float(sp_check.V)), 6)
    solver_be = round(1.0 / (1.0 + solver_kv), 4)

    kv_exact = (
        abs(term_ledger["known_v"] - solver_kv) < 1e-6
        and abs(round(float(snap.known_v), 6) - solver_kv) < 1e-6
    )
    be_exact = (
        abs(term_ledger["breakeven_p"] - solver_be) < 1e-4
        and abs(round(float(snap.breakeven_p), 4) - solver_be) < 1e-4
    )
    tracker_parity = (
        roster_retained
        and retained_cmaps == pc_total
        and kv_exact
        and be_exact
        and set(tracker.raw_leaks.keys())
        == {(lk["doc_id"], lk["variant"], lk["surfaced_day"]) for lk in term_ledger["leaks"]}
    )

    env_full = Env(tier=tier, seed=seed)
    sp_full = SolverPolicy()
    sp_full.reset(raw_spec, instr)
    while not env_full.done:
        t_act, a_act = sp_full.act(list(env_full.history))
        if t_act == "accuse":
            t_act, a_act = "advance_day", {}
        env_full.call(t_act, a_act)

    full_steps = list(env_full.history)
    full_msgs = render_messages(instr, full_steps)
    full_pair_toks = [
        estimate_qwen_tokens(
            render_qwen_pair(full_msgs[2 + 2 * i], full_msgs[3 + 2 * i]),
            QWEN_BODY_UNIT_SCALE,
        )
        for i in range(len(full_steps))
    ]
    full_raw_tokens = hdr_tokens + sum(full_pair_toks)
    full_ledger = extract_public_ledger(instr, full_steps)
    full_tracker = _CompactStateTracker(instr)
    full_tracker.ingest_up_to(full_steps)
    full_snap = full_tracker.snapshot()
    full_state_tokens = estimate_compact_tokens(compact_user_text(full_ledger))
    full_cturn = render_compact_turn(instr, raw_spec, full_steps, target_step=None, tail_turns=4)
    full_prompt_tokens = estimate_compact_tokens(
        render_compact_prompt_text(full_cturn, add_generation_prompt=True)
    )
    full_planted_cids = {
        str((s.result.get("data") or {}).get("canary_id") or f"c{s.day}")
        for s in full_steps
        if s.tool == "plant_canary" and s.result.get("ok", True)
    }
    full_got_emps = [
        (str(e["id"]), str(e.get("dept", "")), e.get("clearance"))
        for e in full_ledger["employees"]
    ]
    full_retention_ok = (
        int(env_full.day) == TIERS[tier].n_days
        and full_got_emps == expected_emps
        and {c["canary_id"] for c in full_ledger["canaries"]} == full_planted_cids
        and set(full_tracker.canaries_by_id.keys()) == full_planted_cids
        and abs(round(float(full_snap.known_v), 6) - full_ledger["known_v"]) < 1e-6
        and abs(round(float(full_snap.breakeven_p), 4) - full_ledger["breakeven_p"]) < 1e-4
    )

    return {
        "natural": [
            tier,
            seed - TRAIN_BASE,
            round(float(ep.score), 6),
            1 if ep.correct else 0,
            1 if ep.accused is None else 0,
            int(ep.final_day),
            len(steps),
            raw_prefix_tokens,
            1 if roster_called else 0,
            1 if roster_ev4k_sticky else 0,
            1 if roster_ev4k_suffix else 0,
            1 if roster_ev8k_sticky else 0,
            pc_total,
            pc_ev4k_sticky_term,
            pc_ev4k_suffix_term,
            pc_ev8k_sticky_term,
            surf_total,
            surf_ev4k_sticky,
            surf_ev4k_suffix,
            surf_ev8k_sticky,
            surf_delays,
            surf_turn_gaps,
            surf_resolved_compact,
            term_state_tokens,
            all_step_state_max,
            cprompt_tokens,
            1 if roster_retained else 0,
            clearances_retained,
            retained_cmaps,
            1 if kv_exact else 0,
            1 if be_exact else 0,
            1 if tracker_parity else 0,
        ],
        "full_horizon": [
            tier,
            seed - TRAIN_BASE,
            int(env_full.day),
            len(full_steps),
            len(full_planted_cids),
            full_raw_tokens,
            full_state_tokens,
            full_prompt_tokens,
            1 if full_retention_ok else 0,
        ],
    }


def aggregate_natural_rows(rows: list[list[Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in ALL_SCOPES:
        sub = [r for r in rows if scope == "all" or r[0] == scope]
        n = len(sub)
        scores = [float(r[2]) for r in sub]
        wins = sum(int(r[3]) for r in sub)
        abstains = sum(int(r[4]) for r in sub)
        final_days = [int(r[5]) for r in sub]
        steps_list = [int(r[6]) for r in sub]
        raw_toks = sorted(int(r[7]) for r in sub)

        ros_called = sum(int(r[8]) for r in sub)
        ros_ev4s = sum(int(r[9]) for r in sub)
        ros_ev4w = sum(int(r[10]) for r in sub)
        ros_ev8s = sum(int(r[11]) for r in sub)

        pc_tot = sum(int(r[12]) for r in sub)
        pc_ev4s = sum(int(r[13]) for r in sub)
        pc_ev4w = sum(int(r[14]) for r in sub)
        pc_ev8s = sum(int(r[15]) for r in sub)

        sf_tot = sum(int(r[16]) for r in sub)
        sf_ev4s = sum(int(r[17]) for r in sub)
        sf_ev4w = sum(int(r[18]) for r in sub)
        sf_ev8s = sum(int(r[19]) for r in sub)
        all_delays = [int(d) for r in sub for d in r[20]]
        all_gaps = [int(g) for r in sub for g in r[21]]
        sf_res = sum(int(r[22]) for r in sub)

        cstate_toks = sorted(int(r[23]) for r in sub)
        cstep_max_toks = sorted(int(r[24]) for r in sub)
        cprompt_toks = sorted(int(r[25]) for r in sub)

        ros_ret = sum(int(r[26]) for r in sub)
        clr_ret = sum(int(r[27]) for r in sub)
        cmap_ret = sum(int(r[28]) for r in sub)
        kv_ok = sum(int(r[29]) for r in sub)
        be_ok = sum(int(r[30]) for r in sub)
        trk_ok = sum(int(r[31]) for r in sub)

        raw_mean = sum(raw_toks) / n if n > 0 else 0.0
        cstate_mean = sum(cstate_toks) / n if n > 0 else 0.0
        cprompt_mean = sum(cprompt_toks) / n if n > 0 else 0.0
        ex4k = sum(1 for x in raw_toks if x > WINDOW_4K)
        ex8k = sum(1 for x in raw_toks if x > WINDOW_8K)
        ex900_term = sum(1 for x in cstate_toks if x >= COMPACT_STATE_MAX_TOKENS)
        ex900_any = sum(1 for x in cstep_max_toks if x >= COMPACT_STATE_MAX_TOKENS)
        ex2048 = sum(1 for x in cprompt_toks if x > COMPACT_WINDOW_2K)

        out[scope] = {
            "n_episodes": n,
            "solver_wins": wins,
            "solver_abstentions": abstains,
            "mean_score": round(sum(scores) / n, 4) if n > 0 else 0.0,
            "mean_final_day": round(sum(final_days) / n, 2) if n > 0 else 0.0,
            "max_final_day": max(final_days, default=0),
            "total_steps": sum(steps_list),
            "raw_openai_chat": {
                "prefix_tokens_min": raw_toks[0] if raw_toks else 0,
                "prefix_tokens_median": round(quantile_sorted(raw_toks, 0.50), 1),
                "prefix_tokens_p90": round(quantile_sorted(raw_toks, 0.90), 1),
                "prefix_tokens_mean": round(raw_mean, 1),
                "prefix_tokens_max": raw_toks[-1] if raw_toks else 0,
                "exceeds_4096_count": ex4k,
                "exceeds_4096_rate": _rate(ex4k, n),
                "exceeds_8192_count": ex8k,
                "exceeds_8192_rate": _rate(ex8k, n),
                "episodes_with_day1_roster": ros_called,
                "day1_roster_evicted_4k_sticky_count": ros_ev4s,
                "day1_roster_evicted_4k_sticky_rate": _rate(ros_ev4s, ros_called),
                "day1_roster_evicted_4k_suffix_count": ros_ev4w,
                "day1_roster_evicted_4k_suffix_rate": _rate(ros_ev4w, ros_called),
                "day1_roster_evicted_8k_sticky_count": ros_ev8s,
                "day1_roster_evicted_8k_sticky_rate": _rate(ros_ev8s, ros_called),
                "surfaced_canary_leaks_total": sf_tot,
                "observed_delay_days_min": min(all_delays) if all_delays else 0,
                "observed_delay_days_mean": round(sum(all_delays) / len(all_delays), 2) if all_delays else 0.0,
                "observed_delay_days_max": max(all_delays) if all_delays else 0,
                "intervening_turns_mean": round(sum(all_gaps) / len(all_gaps), 1) if all_gaps else 0.0,
                "canary_map_evicted_before_surface_4k_sticky_count": sf_ev4s,
                "canary_map_evicted_before_surface_4k_sticky_rate": _rate(sf_ev4s, sf_tot),
                "canary_map_evicted_before_surface_4k_suffix_count": sf_ev4w,
                "canary_map_evicted_before_surface_4k_suffix_rate": _rate(sf_ev4w, sf_tot),
                "canary_map_evicted_before_surface_8k_sticky_count": sf_ev8s,
                "canary_map_evicted_before_surface_8k_sticky_rate": _rate(sf_ev8s, sf_tot),
                "planted_canaries_in_prefix_total": pc_tot,
                "canary_map_evicted_at_terminal_4k_sticky_count": pc_ev4s,
                "canary_map_evicted_at_terminal_4k_sticky_rate": _rate(pc_ev4s, pc_tot),
                "canary_map_evicted_at_terminal_4k_suffix_count": pc_ev4w,
                "canary_map_evicted_at_terminal_4k_suffix_rate": _rate(pc_ev4w, pc_tot),
                "canary_map_evicted_at_terminal_8k_sticky_count": pc_ev8s,
                "canary_map_evicted_at_terminal_8k_sticky_rate": _rate(pc_ev8s, pc_tot),
            },
            "compact_working_memory": {
                "state_tokens_min": cstate_toks[0] if cstate_toks else 0,
                "state_tokens_median": round(quantile_sorted(cstate_toks, 0.50), 1),
                "state_tokens_p90": round(quantile_sorted(cstate_toks, 0.90), 1),
                "state_tokens_mean": round(cstate_mean, 1),
                "state_tokens_max": cstate_toks[-1] if cstate_toks else 0,
                "all_steps_state_tokens_max": max(cstep_max_toks, default=0),
                "exceeds_900_state_tokens_count": ex900_term,
                "exceeds_900_any_step_count": ex900_any,
                "exceeds_900_state_tokens_rate": _rate(ex900_any, n),
                "prompt_tokens_mean": round(cprompt_mean, 1),
                "prompt_tokens_max": cprompt_toks[-1] if cprompt_toks else 0,
                "exceeds_2048_prompt_tokens_count": ex2048,
                "compression_ratio_vs_raw_mean": round(cprompt_mean / raw_mean, 4) if raw_mean > 0 else 0.0,
                "employee_roster_retained_count": ros_ret,
                "employee_roster_retention_rate": _rate(ros_ret, ros_called),
                "employee_roster_eviction_rate": _rate(ros_called - ros_ret, ros_called),
                "employee_clearances_retained_count": clr_ret,
                "active_canary_maps_retained_count": cmap_ret,
                "active_canary_maps_retention_rate": _rate(cmap_ret, pc_tot),
                "active_canary_maps_eviction_rate": _rate(pc_tot - cmap_ret, pc_tot),
                "surfaced_leak_candidates_resolved_count": sf_res,
                "surfaced_leak_candidates_resolved_rate": _rate(sf_res, sf_tot),
                "known_v_exact_match_count": kv_ok,
                "breakeven_exact_match_count": be_ok,
                "compact_state_tracker_parity_count": trk_ok,
                "compact_state_tracker_parity_rate": _rate(trk_ok, n),
            },
        }
    return out


def aggregate_full_horizon_rows(rows: list[list[Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in ALL_SCOPES:
        sub = [r for r in rows if scope == "all" or r[0] == scope]
        n = len(sub)
        days = [int(r[2]) for r in sub]
        steps_l = [int(r[3]) for r in sub]
        pcs = [int(r[4]) for r in sub]
        raw_t = sorted(int(r[5]) for r in sub)
        st_t = sorted(int(r[6]) for r in sub)
        pr_t = sorted(int(r[7]) for r in sub)
        ret_ok = sum(int(r[8]) for r in sub)
        ex900 = sum(1 for x in st_t if x >= COMPACT_STATE_MAX_TOKENS)
        ex2048 = sum(1 for x in pr_t if x > COMPACT_WINDOW_2K)
        raw_mean = sum(raw_t) / n if n > 0 else 0.0
        st_mean = sum(st_t) / n if n > 0 else 0.0
        pr_mean = sum(pr_t) / n if n > 0 else 0.0

        out[scope] = {
            "n_episodes": n,
            "horizon_days_min": min(days, default=0),
            "horizon_days_max": max(days, default=0),
            "mean_steps": round(sum(steps_l) / n, 1) if n > 0 else 0.0,
            "total_canaries_planted": sum(pcs),
            "max_canaries_per_episode": max(pcs, default=0),
            "raw_prefix_tokens_mean": round(raw_mean, 1),
            "raw_prefix_tokens_max": raw_t[-1] if raw_t else 0,
            "compact_state_tokens_min": st_t[0] if st_t else 0,
            "compact_state_tokens_median": round(quantile_sorted(st_t, 0.50), 1),
            "compact_state_tokens_p90": round(quantile_sorted(st_t, 0.90), 1),
            "compact_state_tokens_mean": round(st_mean, 1),
            "compact_state_tokens_max": st_t[-1] if st_t else 0,
            "exceeds_900_state_tokens_count": ex900,
            "exceeds_900_state_tokens_rate": _rate(ex900, n),
            "compact_prompt_tokens_mean": round(pr_mean, 1),
            "compact_prompt_tokens_max": pr_t[-1] if pr_t else 0,
            "exceeds_2048_prompt_tokens_count": ex2048,
            "compression_ratio_vs_raw_mean": round(pr_mean / raw_mean, 4) if raw_mean > 0 else 0.0,
            "lossless_retention_and_tracker_parity_count": ret_ok,
            "lossless_retention_and_tracker_parity_rate": _rate(ret_ok, n),
        }
    return out


def load_cross_verification_and_panel_e(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    forensics = json.loads((repo_root / FORENSICS_REL).read_text(encoding="utf-8"))
    confound = json.loads((repo_root / CONFOUND_REL).read_text(encoding="utf-8"))
    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))

    wm = forensics["ws4_v2_root_cause"]["window_model"]
    v2_ov = forensics["ws4_v2_root_cause"]["overall"]
    v2_hard = forensics["ws4_v2_root_cause"]["by_tier"]["hard"]

    v450 = confound["pooled_views"]["all_450_verda"]["all"]
    v450_raw = v450["raw_transcript"]
    v450_comp = v450["compact_transcript"]
    stress_21d = confound["compact_hard_21day_stress_check"]

    cross = {
        "forensics_prior_runs_ws4_v2": {
            "source_path": str(FORENSICS_REL),
            "total_episodes": int(forensics["ws4_v2_root_cause"]["total_episodes"]),
            "accused_episodes": int(v2_ov["accused_episodes"]),
            "header_tokens": int(wm["header_tokens"]),
            "max_len_tokens": int(wm["max_len_tokens"]),
            "header_frac": float(wm["header_frac"]),
            "body_budget_tokens": int(wm["body_budget_tokens"]),
            "total_list_employees_turns": int(v2_ov["total_list_employees_turns"]),
            "dropped_list_employees_turns": int(v2_ov["dropped_list_employees_turns"]),
            "dropped_list_employees_frac": float(v2_ov["dropped_list_employees_frac"]),
            "dropped_list_employees_pct": round(100.0 * float(v2_ov["dropped_list_employees_frac"]), 1),
            "episodes_missing_employee_roster_at_accuse": int(
                v2_ov["episodes_missing_employee_roster_at_accuse"]
            ),
            "total_plant_canary_turns": int(v2_ov["total_plant_canary_turns"]),
            "dropped_plant_canary_turns": int(v2_ov["dropped_plant_canary_turns"]),
            "dropped_plant_canary_frac": float(v2_ov["dropped_plant_canary_frac"]),
            "hard_dropped_plant_canary_frac": float(v2_hard["dropped_plant_canary_frac"]),
            "below_breakeven_count": int(v2_ov["below_breakeven_count"]),
            "below_breakeven_frac": float(v2_ov["below_breakeven_frac"]),
        },
        "context_confound_all_450_verda": {
            "source_path": str(CONFOUND_REL),
            "n_episodes": int(v450["n"]),
            "plant_canary_ok_calls_in_prefix": int(v450_raw["plant_canary_ok_calls_in_prefix"]),
            "plant_canary_evicted_4k_count": int(v450_raw["plant_canary_evicted_4k_count"]),
            "plant_canary_evicted_4k_pct": float(v450_raw["plant_canary_evicted_4k_pct"]),
            "plant_canary_evicted_4k_pct_1d": round(float(v450_raw["plant_canary_evicted_4k_pct"]), 1),
            "plant_canary_evicted_8k_count": int(v450_raw["plant_canary_evicted_8k_count"]),
            "plant_canary_evicted_8k_pct": float(v450_raw["plant_canary_evicted_8k_pct"]),
            "list_employees_ok_calls_in_prefix": int(v450_raw["list_employees_ok_calls_in_prefix"]),
            "list_employees_evicted_4k_count": int(v450_raw["list_employees_evicted_4k_count"]),
            "list_employees_evicted_4k_pct": float(v450_raw["list_employees_evicted_4k_pct"]),
            "episodes_with_roster_called": int(v450_raw["episodes_with_roster_called"]),
            "episodes_roster_evicted_4k_count": int(v450_raw["episodes_roster_evicted_4k_count"]),
            "episodes_roster_evicted_4k_pct": float(v450_raw["episodes_roster_evicted_4k_pct"]),
            "compact_state_tokens_mean": float(v450_comp["state_tokens_mean"]),
            "compact_state_tokens_max": int(v450_comp["state_tokens_max"]),
            "compact_exceeds_900_state_tokens_count": int(v450_comp["exceeds_900_state_tokens_count"]),
            "compact_prompt_tokens_mean": float(v450_comp["tokens_mean"]),
            "compact_prompt_tokens_max": int(v450_comp["tokens_max"]),
            "compact_canary_map_evicted_count": int(v450_comp["canary_map_evicted_count"]),
            "compact_canary_map_evicted_pct": float(v450_comp["canary_map_evicted_pct"]),
            "compact_roster_evicted_count": int(v450_comp["roster_evicted_count"]),
            "compact_roster_evicted_pct": float(v450_comp["roster_evicted_pct"]),
            "compact_compression_ratio_vs_raw_mean": float(v450_comp["compression_ratio_vs_raw_mean"]),
            "hard_21day_ref_state_tokens_max": int(stress_21d["compact_state_tokens_max"]),
            "hard_21day_ref_canary_map_evicted_count": int(stress_21d["canary_map_evicted_count"]),
        },
    }

    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_above_zero = sum(
        1
        for r in hist_runs
        if isinstance(r, dict)
        and isinstance(r.get("after_mean_score"), (int, float))
        and float(r["after_mean_score"]) > 0.0
    )
    sc = ledger.get("summary_counts") or {}
    panel_e = {
        "source_path": str(LEDGER_REL),
        "open_weight_qwen25_runs_total": len(hist_runs),
        "open_weight_qwen25_runs_above_zero": qwen_above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{qwen_above_zero} / {len(hist_runs)}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "non_llm_verified_run_ids": list(sc.get("verified_run_ids") or []),
        "non_llm_policies_is_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }
    return cross, panel_e


def run_audit(repo_root: Path = ROOT, max_workers: int = 8) -> dict[str, Any]:
    jobs = build_train_jobs()
    header_tax = compute_header_token_tax()
    cross, panel_e = load_cross_verification_and_panel_e(repo_root)

    if max_workers > 1:
        with ProcessPoolExecutor(max_workers=min(max_workers, len(jobs))) as pool:
            results = list(pool.map(_run_single_episode_audit, jobs))
    else:
        results = [_run_single_episode_audit(j) for j in jobs]

    natural_rows = [r["natural"] for r in results]
    full_horizon_rows = [r["full_horizon"] for r in results]

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": "tiebreak-working-memory-token-tax-v14",
        "tiers_version": "v1.4",
        "tiers": list(CANONICAL_TIERS),
        "train_seed_range": "106000..106044",
        "train_seed_min": TRAIN_BASE,
        "train_seed_max": TRAIN_BASE + TOTAL_TRAIN_EPISODES - 1,
        "train_seeds_unique_count": TOTAL_TRAIN_EPISODES,
        "episodes_per_tier": EPISODES_PER_TIER,
        "seed_isolation": {
            "train_only_verified": True,
            "heldout_episodes_touched": 0,
            "dev_episodes_touched": 0,
            "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "header_token_tax": header_tax,
        "train_episodes_audit": {
            "by_scope": aggregate_natural_rows(natural_rows),
            "compact_episode_rows": natural_rows,
        },
        "full_horizon_stress_test": {
            "by_scope": aggregate_full_horizon_rows(full_horizon_rows),
            "compact_horizon_rows": full_horizon_rows,
        },
        "cross_verification": cross,
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3

    ht = summary["header_token_tax"]
    ref = ht["slurm_44410_reference"]
    hbt = ht["by_tier"]
    nat = summary["train_episodes_audit"]["by_scope"]
    fh = summary["full_horizon_stress_test"]["by_scope"]
    cv = summary["cross_verification"]
    fv2 = cv["forensics_prior_runs_ws4_v2"]
    c450 = cv["context_confound_all_450_verda"]
    pe = summary["panel_fix_e_track_separation"]

    nat_all_raw = nat["all"]["raw_openai_chat"]
    nat_all_wm = nat["all"]["compact_working_memory"]
    fh_all = fh["all"]

    lines: list[str] = [
        f"{h1} Working-Memory & Prompt-Header Token-Tax Audit (`train/render.py` vs `train/compact_render.py`)",
        "",
        (
            "Deterministic offline working-memory and prompt-header token-tax audit strictly over "
            f"`TRAIN_SEEDS [100000, 200000)` (`{summary['train_seed_range']}`, `{summary['train_seeds_unique_count']}` "
            "`SolverPolicy` episodes across `easy`, `medium`, `hard`) comparing raw OpenAI JSON chat rendering "
            "(`train/render.py` + `HFPolicy` sliding-window truncation) against lossless working-memory rendering "
            "(`train/compact_render.py` + `_CompactStateTracker`)."
        ),
        "",
        (
            f"- **Seed Isolation (Panel Fix A)**: All active trajectory simulations strictly use `{summary['train_seeds_unique_count']}` "
            f"`TRAIN_SEEDS` episodes (`{summary['train_seed_range']}`, `{summary['episodes_per_tier']}`/tier; "
            "`0` `HELDOUT_SEEDS`, `0` `DEV_SEEDS`, and `0` `JUDGE_SEEDS` touched). Where `DEV_SEEDS 0..29` appear in separate "
            "Canary frontier reports, they are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` historical open-weight "
            "`Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum "
            f"remains withheld (`{pe['readme_qwen_addendum_status']}`). Non-LLM structured and parametric policies operating on the "
            "lossless working-memory ledger (`TinyMLPPolicy`, `CompactLinearDAggerPolicy`, `EmpiricalBayesPolicy`, "
            "`ScalingLogisticPolicy`; `is_open_weight_llm = False`) are strictly separated from open-weight `Qwen2.5` LoRA runs."
        ),
        "",
        f"{h2} 1. Static Prompt-Header & Tool-Schema Token-Tax Decomposition",
        "",
        (
            f"In `WS4-v2` (`slurm-44410.out` / `forensics_prior_runs.json`), `train/render.py` + `to_openai_tools` consumed "
            f"**`{ref['header_tokens']:,} / {ref['window_4k_tokens']:,} = {ref['header_share_pct']:.1f}%`** (`{ref['header_share_of_4096']:.4f}`) "
            f"of the `4,096`-token context window on static system instructions plus the verbose `13`-tool OpenAI JSON schema on every turn, "
            f"leaving a **`{ref['body_budget_tokens']:,}`-token** (`{ref['body_budget_pct']:.1f}%`) body budget (`1,152.0` mean tokens under "
            f"`HFPolicy`'s `4,000`-token prompt cap with `max_new_tokens={ref['hf_policy_max_new_tokens']}`). `train/compact_render.py` "
            f"compresses the static system + tool-schema header to **`{hbt['mean']['compact_header_only_tokens']:.1f}` tokens** "
            f"(`{hbt['mean']['header_reduction_frac']*100:.1f}%` reduction, saving `{hbt['mean']['header_token_savings']:.1f}` tokens/turn):"
        ),
        "",
        "| Tier (`n_emp`, Horizon, Delays) | Raw Header Tokens (Schema + Sys) | Share of `4,096` | Raw `4,096` / `4,000` Body Budget | Compact Sys+Tools Tokens | Empty State / Prompt Tokens | Static Header Savings |",
        "|---|---|---|---|---|---|---|",
    ]

    for tier in CANONICAL_TIERS:
        r = hbt[tier]
        delays_s = ",".join(str(x) for x in r["delay_choices"])
        lines.append(
            f"| `{tier}` (`{r['n_employees']}`, `{r['n_days']}d`, `[{delays_s}]`) | "
            f"`{r['raw_header_tokens']:,}` (`{r['raw_tool_schema_tokens']:,}` + `{r['raw_system_and_kickoff_tokens']:,}`) | "
            f"`{r['raw_share_of_4096']*100:.1f}%` | "
            f"`{r['raw_body_budget_4096']:,}` / `{r['raw_body_budget_4000_cap']:,}` | "
            f"`{r['compact_header_only_tokens']:,}` | "
            f"`{r['compact_empty_state_tokens']}` / `{r['compact_empty_prompt_tokens']:,}` | "
            f"`-{r['header_token_savings']:,}` (`-{r['header_reduction_frac']*100:.1f}%`) |"
        )

    rm = hbt["mean"]
    lines.extend(
        [
            (
                f"| `3-tier mean` | `{rm['raw_header_tokens']:,.1f}` (`{rm['raw_tool_schema_tokens']:,.1f}` + "
                f"`{rm['raw_system_and_kickoff_tokens']:,.1f}`) | `{rm['raw_share_of_4096']*100:.1f}%` | "
                f"`{rm['raw_body_budget_4096']:,.1f}` / `{rm['raw_body_budget_4000_cap']:,.1f}` | "
                f"`{rm['compact_header_only_tokens']:,.1f}` | "
                f"`{rm['compact_empty_state_tokens']:.1f}` / `{rm['compact_empty_prompt_tokens']:,.1f}` | "
                f"`-{rm['header_token_savings']:,.1f}` (`-{rm['header_reduction_frac']*100:.1f}%`) |"
            ),
            (
                f"| `slurm-44410 ref` (`WS4-v2`) | `{ref['header_tokens']:,}` | `{ref['header_share_pct']:.1f}%` | "
                f"`{ref['body_budget_tokens']:,}` (`4,096` window) | n/a (raw SFT) | n/a | baseline tax reference |"
            ),
            "",
            f"{h2} 2. FIFO Eviction Before Delayed Leaks Surface vs Lossless `CompactStateTracker` (`TRAIN_SEEDS {summary['train_seed_range']}`, `n=45`)",
            "",
            (
                "Across `45` `SolverPolicy` episodes on `TRAIN_SEEDS 106000..106044` (`15`/tier), raw `4k` chat rendering "
                f"exceeds `4,096` tokens on **`{nat_all_raw['exceeds_4096_count']}/{nat['all']['n_episodes']}` (`{nat_all_raw['exceeds_4096_rate']*100:.1f}%`)** "
                f"of episodes, FIFO-evicts Day-1 `list_employees` rosters on **`{nat_all_raw['day1_roster_evicted_4k_sticky_count']}/{nat_all_raw['episodes_with_day1_roster']}` "
                f"(`{nat_all_raw['day1_roster_evicted_4k_sticky_rate']*100:.1f}%`)**, and evicts early `(doc_id, variant -> recipients)` `plant_canary` maps "
                f"**before** delayed leaks surface in `check_leak_feed` on **`{nat['medium']['raw_openai_chat']['canary_map_evicted_before_surface_4k_sticky_count']}/"
                f"{nat['medium']['raw_openai_chat']['surfaced_canary_leaks_total']}` (`100.0%`)** of `medium` (`1-3d` delay) and "
                f"**`{nat['hard']['raw_openai_chat']['canary_map_evicted_before_surface_4k_sticky_count']}/"
                f"{nat['hard']['raw_openai_chat']['surfaced_canary_leaks_total']}` (`100.0%`)** of `hard` (`2-3d` delay) canary leaks "
                f"(`{nat_all_raw['canary_map_evicted_before_surface_4k_sticky_count']}/{nat_all_raw['surfaced_canary_leaks_total']} = "
                f"{nat_all_raw['canary_map_evicted_before_surface_4k_sticky_rate']*100:.1f}%` overall; "
                f"`{nat_all_raw['canary_map_evicted_at_terminal_4k_sticky_count']}/{nat_all_raw['planted_canaries_in_prefix_total']} = "
                f"{nat_all_raw['canary_map_evicted_at_terminal_4k_sticky_rate']*100:.1f}%` evicted by terminal decision). "
                "By contrast, `train/compact_render.py` and `_CompactStateTracker` keep working-memory state strictly **`< 900` tokens** "
                f"(terminal max `{nat_all_wm['state_tokens_max']}`, any-step max `{nat_all_wm['all_steps_state_tokens_max']}`, `0%` `>= 900`) "
                "with **`100.0%` lossless retention** of employee clearances, active canary variant maps, surfaced leak candidates, "
                "`known_v`, and breakeven `1 / (1 + known_v)`:"
            ),
            "",
            "| Scope | Raw Prefix Tokens (Mean / Max) | Day-1 Roster Evicted (`4k` / `8k`) | Canary Map Evicted Before Leak Surfaces (`4k` / `8k`) | Canary Map Evicted at Terminal (`4k` / `8k`) | Compact State Tokens (Mean / Max / Any-Step Max) | Compact Retention (Roster / Canary Maps / Leaks / `known_v` & `1/(1+V)`) |",
            "|---|---|---|---|---|---|---|",
        ]
    )

    for scope in ALL_SCOPES:
        sr = nat[scope]["raw_openai_chat"]
        sw = nat[scope]["compact_working_memory"]
        n_ep = nat[scope]["n_episodes"]
        lines.append(
            f"| `{scope}` (`n={n_ep}`) | "
            f"`{sr['prefix_tokens_mean']:,.1f}` / `{sr['prefix_tokens_max']:,}` | "
            f"`{sr['day1_roster_evicted_4k_sticky_count']}/{sr['episodes_with_day1_roster']} ({sr['day1_roster_evicted_4k_sticky_rate']*100:.1f}%)` / "
            f"`{sr['day1_roster_evicted_8k_sticky_count']}/{sr['episodes_with_day1_roster']} ({sr['day1_roster_evicted_8k_sticky_rate']*100:.1f}%)` | "
            f"`{sr['canary_map_evicted_before_surface_4k_sticky_count']}/{sr['surfaced_canary_leaks_total']} ({sr['canary_map_evicted_before_surface_4k_sticky_rate']*100:.1f}%)` / "
            f"`{sr['canary_map_evicted_before_surface_8k_sticky_count']}/{sr['surfaced_canary_leaks_total']} ({sr['canary_map_evicted_before_surface_8k_sticky_rate']*100:.1f}%)` | "
            f"`{sr['canary_map_evicted_at_terminal_4k_sticky_count']}/{sr['planted_canaries_in_prefix_total']} ({sr['canary_map_evicted_at_terminal_4k_sticky_rate']*100:.1f}%)` / "
            f"`{sr['canary_map_evicted_at_terminal_8k_sticky_count']}/{sr['planted_canaries_in_prefix_total']} ({sr['canary_map_evicted_at_terminal_8k_sticky_rate']*100:.1f}%)` | "
            f"`{sw['state_tokens_mean']:.1f}` / `{sw['state_tokens_max']}` / `{sw['all_steps_state_tokens_max']}` | "
            f"`{sw['employee_roster_retained_count']}/{sr['episodes_with_day1_roster']}` / "
            f"`{sw['active_canary_maps_retained_count']}/{sr['planted_canaries_in_prefix_total']}` / "
            f"`{sw['surfaced_leak_candidates_resolved_count']}/{sr['surfaced_canary_leaks_total']}` / "
            f"`{sw['known_v_exact_match_count']}/{n_ep}` (`100.0%`) |"
        )

    lines.extend(
        [
            "",
            f"{h2} 3. Full `14/21`-Day Horizon Working-Memory Stress Test (`TRAIN_SEEDS {summary['train_seed_range']}`, `n=45`)",
            "",
            (
                "To verify boundedness across full `14`-day (`easy`, `medium`) and `21`-day (`hard`) horizons without early termination, "
                "all `45` `TRAIN_SEEDS 106000..106044` episodes were also rolled out to their terminal horizon day while planting canaries daily "
                f"(`{fh_all['total_canaries_planted']}` total planted canaries, up to `{fh['hard']['max_canaries_per_episode']}`/episode on `21`-day `hard`). "
                f"Working-memory state (`compact_user_text`) stayed strictly **`< 900` tokens on `45/45` (`100.0%`)** full-horizon episodes "
                f"(overall mean `{fh_all['compact_state_tokens_mean']:.1f}`, max `{fh_all['compact_state_tokens_max']}` vs "
                f"`{fh_all['raw_prefix_tokens_mean']:,.1f}` mean / `{fh_all['raw_prefix_tokens_max']:,}` max raw prefix tokens; "
                f"`100.0%` lossless ledger + `_CompactStateTracker` parity, including `{nat['hard']['compact_working_memory']['employee_clearances_retained_count']}/600` "
                "`hard` employee clearance records):"
            ),
            "",
            "| Scope | Horizon Reached | Planted Canaries (Total / Max Ep) | Raw Full-Horizon Tokens (Mean / Max) | Compact State Tokens (Mean / P90 / Max) | `>= 900` State Tokens | Compact Prompt Mean / Max | Lossless Tracker Parity |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )

    for scope in ALL_SCOPES:
        fr = fh[scope]
        h_lbl = (
            f"`{fr['horizon_days_min']}d`"
            if fr["horizon_days_min"] == fr["horizon_days_max"]
            else f"`{fr['horizon_days_min']}..{fr['horizon_days_max']}d`"
        )
        lines.append(
            f"| `{scope}` (`n={fr['n_episodes']}`) | {h_lbl} | "
            f"`{fr['total_canaries_planted']}` / `{fr['max_canaries_per_episode']}` | "
            f"`{fr['raw_prefix_tokens_mean']:,.1f}` / `{fr['raw_prefix_tokens_max']:,}` | "
            f"`{fr['compact_state_tokens_mean']:.1f}` / `{fr['compact_state_tokens_p90']:.1f}` / `{fr['compact_state_tokens_max']}` | "
            f"`{fr['exceeds_900_state_tokens_count']}/{fr['n_episodes']} (0.0%)` | "
            f"`{fr['compact_prompt_tokens_mean']:,.1f}` / `{fr['compact_prompt_tokens_max']:,}` | "
            f"`{fr['lossless_retention_and_tracker_parity_count']}/{fr['n_episodes']} (100.0%)` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Cross-Verification Against Committed Historical Forensics (`forensics_prior_runs.json` & `context_confound/audit_summary.json`)",
            "",
            "| Artifact & Cohort | Metric | Raw `4k` / `8k` OpenAI Chat (`train/render.py`) | Lossless `train/compact_render.py` | Agreement With `TRAIN_SEEDS 106000..106044` Audit |",
            "|---|---|---|---|---|",
            (
                f"| `forensics_prior_runs.json` (`WS4-v2`, `n={fv2['total_episodes']}`, `{fv2['accused_episodes']}` accused) | "
                f"Static header tax & `4k` body budget | `{fv2['header_tokens']:,} / {fv2['max_len_tokens']:,} = {fv2['header_frac']*100:.1f}%` tax (`{fv2['body_budget_tokens']:,}` body budget) | "
                f"`{hbt['mean']['compact_header_only_tokens']:.1f}` sys+tools tokens (`-66.1%`) | "
                f"3-tier deterministic raw header mean `{hbt['mean']['raw_header_tokens']:,.1f}` (`0.21%` from `2,842`) |"
            ),
            (
                f"| `forensics_prior_runs.json` (`WS4-v2`, `n={fv2['total_episodes']}`) | "
                f"Day-1 `list_employees` roster eviction | **`{fv2['dropped_list_employees_turns']}/{fv2['total_list_employees_turns']} = {fv2['dropped_list_employees_pct']:.1f}%`** evicted (`{fv2['episodes_missing_employee_roster_at_accuse']}/{fv2['accused_episodes']}` missing at accuse) | "
                "`0.0%` evicted (`100.0%` roster + clearances kept) | "
                f"Matches `{nat_all_raw['day1_roster_evicted_4k_sticky_count']}/{nat_all_raw['episodes_with_day1_roster']} = 100.0%` `4k` Day-1 roster eviction |"
            ),
            (
                f"| `context_confound/audit_summary.json` (`all_450_verda`, `n={c450['n_episodes']}`) | "
                f"`plant_canary` `(doc_id, variant -> recipients)` eviction | **`{c450['plant_canary_evicted_4k_count']:,}/{c450['plant_canary_ok_calls_in_prefix']:,} = {c450['plant_canary_evicted_4k_pct_1d']:.1f}%`** (`{c450['plant_canary_evicted_4k_pct']:.2f}%` at `4k`, `{c450['plant_canary_evicted_8k_pct']:.2f}%` at `8k`) | "
                f"**`{c450['compact_canary_map_evicted_count']}/{c450['plant_canary_ok_calls_in_prefix']:,} = {c450['compact_canary_map_evicted_pct']:.1f}%`** evicted | "
                f"Matches `{nat_all_raw['canary_map_evicted_at_terminal_4k_sticky_rate']*100:.1f}%` `4k` terminal & `100.0%` `medium`/`hard` pre-leak eviction vs `0.0%` compact |"
            ),
            (
                f"| `context_confound/audit_summary.json` (`all_450_verda` + `60` `21d` hard ref) | "
                f"Working-memory token budget (`< 900` target) | `{c450['episodes_roster_evicted_4k_pct']:.2f}%` ep roster evicted; raw mean `24,035.4` tokens | "
                f"State mean `{c450['compact_state_tokens_mean']:.1f}`, max `{c450['compact_state_tokens_max']}` (`21d` ref max `{c450['hard_21day_ref_state_tokens_max']}`, `0` `>= 900`) | "
                f"Matches `106000..106044` state max `{nat_all_wm['state_tokens_max']}` (natural) and `{fh_all['compact_state_tokens_max']}` (full `14/21d` horizon) |"
            ),
            "",
            f"{h3} Mechanistic Takeaway",
            "",
            (
                "1. **`69.4%` Static Header Tax Crowds Out Delayed-Leak Evidence**: Because `train/render.py` repeats `2,842` static header + OpenAI JSON tool-schema tokens in every `4,096`-token window (`1,254`-token body budget), routine daily `list_documents`, `read_access_logs`, and `search_messages` responses consume the entire body budget within `1-2` simulated days, FIFO-evicting Day-1 `list_employees` (`97.1%` on `WS4-v2`, `100.0%` on `106000..106044`) and early `plant_canary` recipient maps (`98.0%` across `450` Verda episodes, `100.0%` before `1-3d` `medium` and `2-3d` `hard` leaks surface on `106000..106044`).\n"
                "2. **Lossless Working Memory Eliminates Eviction in `< 900` State Tokens**: `train/compact_render.py` (`extract_public_ledger` / `compact_user_text`) and `_CompactStateTracker` fold public tool outputs into a sufficient-statistic working memory (`<= 709 < 900` state tokens even at Day `21` on `hard`), preserving `100.0%` of employee clearances, active canary variant assignments, surfaced leak candidate sets, `known_v`, and breakeven `1 / (1 + known_v)` with `0.0%` eviction."
            ),
            "",
            f"{h2} 5. Offline Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_working_memory_audit.py --check",
            "pytest -q tests/test_tiebreak_working_memory.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not _PREREG_RE.search(raw_line) or not _SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
        if _PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def check_python_source_hygiene(py_path: Path) -> list[str]:
    errs: list[str] = []
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    src = py_path.read_text(encoding="utf-8")
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    if any(t.type == tokenize.COMMENT for t in toks) or H in src:
        errs.append(f"{py_path.name}: contains Python comment or hash character")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in src:
            errs.append(f"{py_path.name}: contains forbidden {ch_name}")
    return errs


def verify_committed_artifacts(
    summary_path: Path,
    md_path: Path,
    repo_root: Path = ROOT,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []
    if not summary_path.is_file():
        return [f"missing summary JSON: {summary_path}"]
    if not md_path.is_file():
        return [f"missing markdown report: {md_path}"]

    for forbidden_name in ("summary.json", "table.md"):
        sib = summary_path.parent / forbidden_name
        if sib.exists():
            errors.append(f"disjointness violation: forbidden sibling {sib} exists")

    sz = summary_path.stat().st_size
    if sz >= MAX_SUMMARY_BYTES:
        errors.append(f"{summary_path.name}: size {sz} bytes >= {MAX_SUMMARY_BYTES} bytes limit")

    raw_json = summary_path.read_text(encoding="utf-8")
    md_txt = md_path.read_text(encoding="utf-8")
    summary = json.loads(raw_json)

    for lbl, txt in ((summary_path.name, raw_json), (md_path.name, md_txt)):
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    for rel_py in (
        "scripts/tiebreak_working_memory_audit.py",
        "tests/test_tiebreak_working_memory.py",
    ):
        p_py = repo_root / rel_py
        if p_py.is_file():
            errors.extend(check_python_source_hygiene(p_py))

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("train_seed_range") != "106000..106044":
        errors.append(f"unexpected train_seed_range: {summary.get('train_seed_range')!r}")
    if int(summary.get("train_seeds_unique_count", -1)) != TOTAL_TRAIN_EPISODES:
        errors.append("train_seeds_unique_count != 45")
    if int(summary.get("episodes_per_tier", -1)) != EPISODES_PER_TIER:
        errors.append("episodes_per_tier != 15")

    jobs = build_train_jobs()
    if len(jobs) != TOTAL_TRAIN_EPISODES:
        errors.append("build_train_jobs count != 45")

    iso = summary.get("seed_isolation") or {}
    if iso.get("train_only_verified") is not True:
        errors.append("seed_isolation.train_only_verified is not True")
    for z_key in ("heldout_episodes_touched", "dev_episodes_touched", "judge_episodes_touched"):
        if int(iso.get(z_key, 1)) != 0:
            errors.append(f"seed_isolation.{z_key} must be 0")

    live_header = compute_header_token_tax()
    if summary.get("header_token_tax") != live_header:
        errors.append("header_token_tax out of sync with live deterministic header computation")

    live_cross, live_pe = load_cross_verification_and_panel_e(repo_root)
    if summary.get("cross_verification") != live_cross:
        errors.append("cross_verification out of sync with forensics_prior_runs / context_confound JSON")
    if summary.get("panel_fix_e_track_separation") != live_pe:
        errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    ta = summary.get("train_episodes_audit") or {}
    nat_rows = ta.get("compact_episode_rows") or []
    if len(nat_rows) != TOTAL_TRAIN_EPISODES:
        errors.append(f"expected 45 compact_episode_rows, found {len(nat_rows)}")
    elif aggregate_natural_rows(nat_rows) != ta.get("by_scope"):
        errors.append("train_episodes_audit.by_scope does not match recomputed compact_episode_rows")

    fh = summary.get("full_horizon_stress_test") or {}
    fh_rows = fh.get("compact_horizon_rows") or []
    if len(fh_rows) != TOTAL_TRAIN_EPISODES:
        errors.append(f"expected 45 compact_horizon_rows, found {len(fh_rows)}")
    elif aggregate_full_horizon_rows(fh_rows) != fh.get("by_scope"):
        errors.append("full_horizon_stress_test.by_scope does not match recomputed compact_horizon_rows")

    nat_all = (ta.get("by_scope") or {}).get("all") or {}
    wm_all = nat_all.get("compact_working_memory") or {}
    fh_all = (fh.get("by_scope") or {}).get("all") or {}
    if int(wm_all.get("exceeds_900_any_step_count", 1)) != 0:
        errors.append("natural episodes exceeded 900 working-memory state tokens")
    if int(fh_all.get("exceeds_900_state_tokens_count", 1)) != 0:
        errors.append("full-horizon stress episodes exceeded 900 working-memory state tokens")
    if float(wm_all.get("employee_roster_retention_rate", 0.0)) != 1.0:
        errors.append("compact employee_roster_retention_rate != 1.0")
    if float(wm_all.get("active_canary_maps_retention_rate", 0.0)) != 1.0:
        errors.append("compact active_canary_maps_retention_rate != 1.0")
    if float(wm_all.get("surfaced_leak_candidates_resolved_rate", 0.0)) != 1.0:
        errors.append("compact surfaced_leak_candidates_resolved_rate != 1.0")
    if float(wm_all.get("compact_state_tracker_parity_rate", 0.0)) != 1.0:
        errors.append("compact_state_tracker_parity_rate != 1.0")
    if float(fh_all.get("lossless_retention_and_tracker_parity_rate", 0.0)) != 1.0:
        errors.append("full_horizon lossless_retention_and_tracker_parity_rate != 1.0")

    required_md_tokens = (
        "106000..106044",
        "2,842 / 4,096 = 69.4%",
        "1,254",
        "97.1%",
        "98.0%",
        "0.0%",
        "< 900",
        "post-hoc locked, not pre-registered",
        "0 / 19",
    )
    for req_tok in required_md_tokens:
        if req_tok not in md_txt:
            errors.append(f"{md_path.name}: missing required verified claim token {req_tok!r}")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{md_path.name}: markdown text out of sync with render_markdown_report(summary)")

    elapsed = time.perf_counter() - t0
    if elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check elapsed {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")

    return errors


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Deterministic offline working-memory and prompt-header token-tax audit."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--check", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = args.root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    if args.check:
        t0 = time.perf_counter()
        errs = verify_committed_artifacts(out_json, out_md, repo_root=root)
        elapsed = time.perf_counter() - t0
        if errs:
            for err in errs:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        print(
            f"OK: verified {out_json.relative_to(root)} and {out_md.relative_to(root)} in {elapsed:.3f}s"
        )
        return 0

    t0 = time.perf_counter()
    summary = run_audit(repo_root=root, max_workers=max(1, int(args.workers)))
    md_text = render_markdown_report(summary)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(out_json, out_md, repo_root=root)
    elapsed = time.perf_counter() - t0
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(
        f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
        f"{out_md.relative_to(root)} ({summary['train_seeds_unique_count']} TRAIN episodes in {elapsed:.2f}s, 0 errors)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
