"""Compact Calibrated SFT + On-Policy EV-Margin DPO + 2-Round DAgger trainer and paired evaluator for Qwen2.5-1.5B-Instruct."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import dataclasses
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Iterable

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS as RULE_TIERS, TRAIN_SEEDS
from train.compact_render import (
    CompactHFPolicy,
    compact_system_text,
    compact_tools_spec,
    compact_turn_window,
    compact_user_text,
    extract_public_ledger,
    render_compact_messages,
    render_compact_turn,
)
from train.eval_compact_hf import (
    DEFAULT_HELD_OUT_WORLD_SECRET,
    _world_secret_scope,
    audit_seed_hygiene,
    compute_world_secret_tag,
    luck_adjusted_episode_ev,
    verify_episode_file,
)
from train.render import assistant_msg, parse_tool_call

DEFAULT_MODEL_PATH = "/home/silas/agent-arena-data/models/Qwen2.5-1.5B-Instruct"
DEFAULT_SCRATCH_DIR = "/tmp/fleet-silas/shared/tiebreak-v100/qwen15b_dpo_dagger"
DEFAULT_SUMMARY_OUT = "results/tiebreak/qwen15b_dpo_dagger/summary.json"
DEFAULT_TABLE_OUT = "results/tiebreak/qwen15b_dpo_dagger/table.md"
EVAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
LORA_TARGETS: list[str] = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

SFT_SEED_START = 106_000
SFT_SEED_STOP = 106_240
DAGGER_R1_START = 106_240
DAGGER_R1_STOP = 106_330
DAGGER_R2_START = 106_330
DAGGER_R2_STOP = 106_420
EVAL_SEED_START = 800_000
EVAL_SEED_STOP = 800_030


class QwenCompactDpoPolicy(CompactHFPolicy):
    def __init__(
        self,
        model=None,
        tokenizer=None,
        name: str = "qwen15b_dpo_dagger",
        max_ctx: int = 2048,
        max_new: int = 128,
        tail_turns: int = 4,
        kv_reuse: bool = True,
        generator=None,
    ):
        super().__init__(
            model=model,
            tokenizer=tokenizer,
            name=name,
            max_ctx=max_ctx,
            max_new=max_new,
            tail_turns=tail_turns,
            kv_reuse=kv_reuse,
            generator=generator,
        )

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list) -> tuple[str, dict[str, Any]]:
        return super().act(history)


def validate_seed_plan(
    sft_seeds: Iterable[int],
    r1_seeds: Iterable[int],
    r2_seeds: Iterable[int],
    eval_seeds: Iterable[int],
) -> dict[str, list[int]]:
    sft = [int(s) for s in sft_seeds]
    r1 = [int(s) for s in r1_seeds]
    r2 = [int(s) for s in r2_seeds]
    ev = [int(s) for s in eval_seeds]
    all_train = sft + r1 + r2
    if len(set(sft)) + len(set(r1)) + len(set(r2)) != len(set(all_train)):
        raise ValueError("training stage seed ranges must be pairwise disjoint")
    for s in all_train:
        if s not in TRAIN_SEEDS or not (100_000 <= s < 200_000):
            raise ValueError(f"train seed {s} outside TRAIN_SEEDS [100000, 200000)")
        if s in DEV_SEEDS or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"train seed {s} leaks into non-training split")
    for s in ev:
        if s not in HELDOUT_SEEDS or not (800_000 <= s < 800_200):
            raise ValueError(f"eval seed {s} outside HELDOUT_SEEDS [800000, 800200)")
    return {"sft": sft, "r1": r1, "r2": r2, "eval": ev, "train_all": sorted(set(all_train))}


def _deterministic_canary_split(
    ledger: dict[str, Any],
    post: dict[str, float],
    emps: list[str],
) -> dict[str, str]:
    params = ledger["params"]
    k = int(params["max_variants"])
    counts = ledger["consistency_counts"]
    decoy_ids = {eid for eid, c in counts.items() if int(c.get("angry_msgs", 0)) >= 2}
    pool = [
        eid
        for eid in ledger["consistent_suspects"]
        if eid not in decoy_ids and not counts.get(eid, {}).get("restricted", False)
    ]
    if len(pool) <= 1:
        ranked = sorted(emps, key=lambda e: (-float(post.get(e, 0.0)), e))
        pool = [
            eid
            for eid in ranked
            if eid not in decoy_ids and not counts.get(eid, {}).get("restricted", False)
        ][: min(6, max(k, len(emps)))]
    if len(pool) <= 1:
        return {}
    c_idx = len(ledger["canaries"])
    win = 9
    if len(pool) > win:
        stride = 6 if len(pool) <= 12 else win
        off = (c_idx * stride) % len(pool)
        sub = (pool[off:] + pool[:off])[:win]
    else:
        sub = list(pool)
    sub = sorted(sub)
    labels = "ABCDEFGH"[:k]
    asg: dict[str, str] = {}
    for idx_e, eid in enumerate(sub):
        if len(sub) <= k:
            b_idx = idx_e % k
        elif c_idx % 2 == 0:
            b_idx = min(k - 1, (idx_e * k) // len(sub))
        else:
            b_idx = idx_e % k
        asg[eid] = labels[b_idx]
    return asg


def calibrated_teacher_step(
    instruction: str,
    tools_spec: list[dict],
    history: list,
    stop_margin: float = 0.06,
    censor_canary_after_day: int | None = None,
) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy

    sp = SolverPolicy(read_logs=False, find_decoy=True)
    sp.reset(tools_spec, instruction)
    for st in history:
        sp._ingest(st)
    sp.seen = len(history)

    ledger = extract_public_ledger(instruction, history)
    params = ledger["params"]
    day = int(ledger["day"])
    n_days = int(params["n_days"])
    emps = [e["id"] for e in ledger["employees"]]

    if sp.obs.employees:
        post = sp.belief()
    else:
        n_emp = max(1, int(params.get("n_employees", 12)))
        post = {f"e{i:02d}": 1.0 / n_emp for i in range(n_emp)}

    best = max(post, key=lambda e: (post[e], -int(e[1:]) if e[1:].isdigit() else 0))
    top_p = float(post[best])
    known_v = float(ledger["known_v"])
    breakeven_p = 1.0 / (1.0 + max(0.0, known_v))
    ev_top = top_p * known_v - (1.0 - top_p)
    thr = (breakeven_p + stop_margin) if day >= n_days else max(breakeven_p + stop_margin, 0.85)

    today_ok_tools: list[str] = []
    for st in reversed(history):
        t_name = st["tool"] if isinstance(st, dict) else getattr(st, "tool", "")
        res = st["result"] if isinstance(st, dict) else getattr(st, "result", None)
        ok = bool((res or {}).get("ok", True)) if isinstance(res, dict) else True
        if t_name == "advance_day" and ok:
            break
        if ok:
            today_ok_tools.append(str(t_name))

    n_can_today = today_ok_tools.count("plant_canary")
    max_can = int(params["canaries_per_day"])
    actions_today = int(ledger["actions_today"])
    actions_cap = int(params["actions_per_day"])
    can_plant = censor_canary_after_day is None or day <= censor_canary_after_day

    if not emps:
        tool, args = "list_employees", {}
    elif day >= 2 and "list_documents" not in today_ok_tools:
        tool, args = "list_documents", {"day_from": max(1, day - 2), "day_to": day}
    elif day >= 2 and "check_leak_feed" not in today_ok_tools:
        tool, args = "check_leak_feed", {}
    elif params.get("decoy") and day == 2 and "search_messages" not in today_ok_tools and actions_today < actions_cap:
        tool, args = "search_messages", {"query": "promotion"}
    elif top_p >= thr and censor_canary_after_day is None:
        tool, args = "accuse", {"employee": best}
    elif can_plant and n_can_today < max_can and actions_today < actions_cap and day < n_days:
        asg = _deterministic_canary_split(ledger, post, emps)
        if asg:
            tool, args = "plant_canary", {"doc_title": f"Memo d{day}_{n_can_today + 1}", "assignment": asg}
        else:
            tool, args = "advance_day", {}
    else:
        tool, args = "advance_day", {}

    return {
        "tool": tool,
        "args": args,
        "post": post,
        "best_emp": best,
        "top_p": top_p,
        "known_v": known_v,
        "breakeven_p": breakeven_p,
        "threshold_p": thr,
        "ev_top": ev_top,
        "day": day,
        "n_days": n_days,
    }


def collect_sft_windows(
    sft_seeds: list[int],
    tiers: tuple[str, ...],
    tok,
    max_len: int = 2048,
    stop_margin: float = 0.06,
    censored_count: int = 36,
) -> tuple[list[tuple[list[int], list[int], bool]], dict[str, Any]]:
    windows: list[tuple[list[int], list[int], bool]] = []
    natural_scores: list[float] = []
    accused_eps = 0
    correct_eps = 0
    abstain_eps = 0
    censored_kept = 0

    for idx, seed in enumerate(sft_seeds):
        tier = tiers[idx % len(tiers)]
        env = Env(tier=tier, seed=seed)
        ins, ts = env.instruction(), env.tools_spec()
        max_iters = int(env.p.tool_call_cap)
        ep_turns: list[tuple[list, dict[str, Any], bool]] = []
        for _ in range(max_iters):
            if env.done:
                break
            info = calibrated_teacher_step(ins, ts, env.history, stop_margin=stop_margin)
            hist_snap = list(env.history)
            target = {"tool": info["tool"], "args": info["args"]}
            is_terminal_decision = info["tool"] == "accuse" or (
                info["tool"] == "advance_day" and info["day"] >= info["n_days"]
            )
            ep_turns.append((hist_snap, target, is_terminal_decision))
            env.call(info["tool"], info["args"])
        ep = env.result("calibrated_teacher")
        natural_scores.append(float(ep.score))
        if ep.end_reason == "accused":
            accused_eps += 1
            if ep.correct:
                correct_eps += 1
        else:
            abstain_eps += 1
        if ep.end_reason == "accused" and not ep.correct:
            continue
        for hist_snap, target, is_term in ep_turns:
            rec = render_compact_turn(ins, ts, hist_snap, target_step=target, tail_turns=4)
            ws = compact_turn_window(rec, tok, max_len=max_len)
            for ids, labs, _ in ws:
                windows.append((ids, labs, is_term))
                if is_term:
                    windows.append((ids, labs, True))

    for idx in range(min(censored_count, len(sft_seeds))):
        seed = sft_seeds[idx]
        tier = tiers[idx % len(tiers)]
        env = Env(tier=tier, seed=seed)
        ins, ts = env.instruction(), env.tools_spec()
        ep_turns = []
        aborted = False
        for _ in range(int(env.p.tool_call_cap)):
            if env.done:
                break
            info = calibrated_teacher_step(
                ins, ts, env.history, stop_margin=stop_margin, censor_canary_after_day=1
            )
            if info["top_p"] >= info["breakeven_p"]:
                aborted = True
                break
            is_final = info["tool"] == "advance_day" and info["day"] >= info["n_days"]
            if info["day"] >= max(2, info["n_days"] - 2):
                ep_turns.append((list(env.history), {"tool": info["tool"], "args": info["args"]}, is_final))
            env.call(info["tool"], info["args"])
        ep = env.result("censored_abstain")
        if aborted or ep.end_reason != "horizon" or ep.score != 0.0:
            continue
        censored_kept += 1
        for hist_snap, target, is_term in ep_turns:
            rec = render_compact_turn(ins, ts, hist_snap, target_step=target, tail_turns=4)
            ws = compact_turn_window(rec, tok, max_len=max_len)
            for ids, labs, _ in ws:
                windows.append((ids, labs, is_term))
                if is_term:
                    windows.append((ids, labs, True))

    stats = {
        "sft_episodes": len(sft_seeds),
        "teacher_mean_score": round(sum(natural_scores) / max(1, len(natural_scores)), 6),
        "teacher_accused": accused_eps,
        "teacher_correct": correct_eps,
        "teacher_natural_abstentions": abstain_eps,
        "censored_abstentions_kept": censored_kept,
        "sft_windows": len(windows),
    }
    return windows, stats


def _encode_prompt_ids(tok, instruction: str, ctools: list[dict], history: list, max_ctx: int, max_new: int) -> tuple[list[int], list[dict]]:
    t_turns = 4
    while True:
        ledger = extract_public_ledger(instruction, history)
        msgs = [
            {"role": "system", "content": compact_system_text(instruction, ledger)},
            {"role": "user", "content": compact_user_text(ledger)},
        ]
        if t_turns > 0:
            full_msgs = render_compact_messages(instruction, history, tail_turns=t_turns)
            msgs = msgs + full_msgs[2:]
        ids = tok.apply_chat_template(msgs, tools=ctools, tokenize=True, add_generation_prompt=True)
        if hasattr(ids, "keys"):
            ids = ids["input_ids"]
        id_list = list(ids)
        if len(id_list) <= max_ctx - max_new or t_turns <= 0:
            return id_list[: max_ctx - max_new], msgs
        t_turns -= 1


def _tokenize_reply_on_prompt(
    tok,
    prompt_msgs: list[dict],
    ctools: list[dict],
    parsed_call: tuple[str, dict[str, Any]] | None,
    raw_text: str,
    max_len: int = 2048,
) -> tuple[list[int], list[int]] | None:
    if parsed_call is not None:
        rec = {"messages": prompt_msgs + [assistant_msg(parsed_call[0], parsed_call[1])], "tools": ctools}
        ws = compact_turn_window(rec, tok, max_len=max_len)
        if not ws:
            return None
        return ws[0][0], ws[0][1]
    prefix_txt = tok.apply_chat_template(prompt_msgs, tools=ctools, tokenize=False, add_generation_prompt=True)
    prefix_ids = list(tok(prefix_txt, add_special_tokens=False)["input_ids"])
    raw_ids = list(tok((raw_text or "invalid")[:220], add_special_tokens=False)["input_ids"])[:64]
    if not raw_ids:
        raw_ids = [int(tok.eos_token_id or 0)]
    ids = prefix_ids + raw_ids
    if len(ids) > max_len:
        return None
    labels = [-100] * len(prefix_ids) + raw_ids
    return ids, labels


def rollout_batched(
    model,
    tok,
    jobs: list[tuple[str, int]],
    agent_name: str,
    batch_size: int = 24,
    max_ctx: int = 2048,
    max_new_tokens: int = 128,
    max_calls: int = 110,
    disable_adapter: bool = False,
    collect_dagger: bool = False,
    stop_margin: float = 0.06,
    world_secret_tag: str = "unset",
) -> dict[str, Any]:
    import torch

    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id
    pad_id = int(tok.pad_token_id)
    eos_id = int(tok.eos_token_id)
    eot_id = tok.convert_tokens_to_ids("<|endoftext|>")
    stop_ids = [eos_id]
    if isinstance(eot_id, int) and eot_id >= 0 and eot_id != eos_id:
        stop_ids.append(eot_id)
    stop_set = set(stop_ids)

    if hasattr(model, "gradient_checkpointing_disable"):
        model.gradient_checkpointing_disable()
    model.config.use_cache = True
    model.eval()
    device = next(model.parameters()).device

    episodes_by_idx: list[dict[str, Any] | None] = [None for _ in jobs]
    dagger_sft: list[tuple[list[int], list[int], bool]] = []
    dpo_pairs: list[dict[str, Any]] = []
    premature_accuse_mistakes = 0
    missed_accuse_mistakes = 0
    other_mistakes = 0

    def finalize_slot(st: dict[str, Any]) -> None:
        env = st["env"]
        ep = env.result(agent_name)
        if not env.done:
            ep.end_reason = "eval_cap"
        ep.meta = dict(ep.meta or {})
        ep.meta["invalid_calls"] = st["invalid_count"]
        ep.meta["world_secret_tag"] = world_secret_tag
        episodes_by_idx[st["job_idx"]] = dataclasses.asdict(ep)

    ctx_mgr = model.disable_adapter() if disable_adapter else nullcontext()
    with ctx_mgr, torch.no_grad():
        slots: list[dict[str, Any]] = []
        next_job_idx = 0
        while True:
            while len(slots) < batch_size and next_job_idx < len(jobs):
                t_name, seed_val = jobs[next_job_idx]
                j_idx = next_job_idx
                next_job_idx += 1
                env = Env(tier=t_name, seed=seed_val)
                raw_ts = env.tools_spec()
                ctools = compact_tools_spec(raw_ts)
                st_obj: dict[str, Any] = {
                    "job_idx": j_idx,
                    "env": env,
                    "instruction": env.instruction(),
                    "raw_spec": raw_ts,
                    "ctools": ctools,
                    "tool_set": {t["function"]["name"] for t in ctools},
                    "invalid_count": 0,
                    "calls_used": 0,
                    "day_tool_counts": {},
                    "cf_added": 0,
                }
                if env.done or max_calls <= 0:
                    finalize_slot(st_obj)
                else:
                    slots.append(st_obj)

            if not slots:
                break

            batch_ids: list[list[int]] = []
            batch_msgs: list[list[dict]] = []
            for st in slots:
                p_ids, p_msgs = _encode_prompt_ids(
                    tok, st["instruction"], st["ctools"], st["env"].history, max_ctx, max_new_tokens
                )
                batch_ids.append(p_ids)
                batch_msgs.append(p_msgs)

            max_p = max(len(x) for x in batch_ids)
            inp = torch.full((len(slots), max_p), pad_id, dtype=torch.long, device=device)
            att = torch.zeros((len(slots), max_p), dtype=torch.long, device=device)
            for b_idx, seq in enumerate(batch_ids):
                inp[b_idx, max_p - len(seq) :] = torch.tensor(seq, dtype=torch.long, device=device)
                att[b_idx, max_p - len(seq) :] = 1

            out = model.generate(
                input_ids=inp,
                attention_mask=att,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                use_cache=True,
                logits_to_keep=1,
                pad_token_id=pad_id,
                eos_token_id=stop_ids,
            )

            still_active: list[dict[str, Any]] = []
            for b_idx, st in enumerate(slots):
                gen_ids = out[b_idx, max_p:].tolist()
                cut = next((k for k, tid in enumerate(gen_ids) if tid in stop_set), None)
                if cut is not None:
                    gen_ids = gen_ids[: cut + 1]
                raw_txt = tok.decode(gen_ids, skip_special_tokens=False)
                parsed = parse_tool_call(raw_txt, st["tool_set"])
                if parsed is None:
                    st["invalid_count"] += 1
                    s_tool, s_args = "status", {}
                else:
                    s_tool, s_args = parsed

                env = st["env"]
                hist_before = list(env.history)
                day_before = int(env.day)
                res = env.call(s_tool, s_args)
                st["calls_used"] += 1

                if collect_dagger:
                    dt_key = (day_before, s_tool)
                    dtc = st["day_tool_counts"]
                    dtc[dt_key] = dtc.get(dt_key, 0) + 1
                    if dtc[dt_key] <= 2 or s_tool == "accuse":
                        t_info = calibrated_teacher_step(
                            st["instruction"], st["raw_spec"], hist_before, stop_margin=stop_margin
                        )
                        t_tool, t_args = t_info["tool"], t_info["args"]
                        is_term = t_tool == "accuse" or (
                            t_tool == "advance_day" and t_info["day"] >= t_info["n_days"]
                        )

                        c_tok = _tokenize_reply_on_prompt(
                            tok, batch_msgs[b_idx], st["ctools"], (t_tool, t_args), "", max_len=max_ctx
                        )
                        if c_tok is not None:
                            dagger_sft.append((c_tok[0], c_tok[1], is_term))
                            if is_term:
                                dagger_sft.append((c_tok[0], c_tok[1], True))

                        mistake_margin = 0.0
                        if parsed is not None and s_tool == "accuse":
                            s_emp = str(s_args.get("employee", ""))
                            if t_tool != "accuse" or s_emp != t_info["best_emp"]:
                                p_s = float(t_info["post"].get(s_emp, 0.0))
                                ev_s = p_s * t_info["known_v"] - (1.0 - p_s)
                                ev_t = max(0.0, t_info["ev_top"]) if t_tool == "accuse" else 0.0
                                mistake_margin = min(1.6, max(0.45, ev_t - ev_s))
                                premature_accuse_mistakes += 1
                        elif t_tool == "accuse" and (parsed is None or s_tool != "accuse"):
                            mistake_margin = min(1.2, max(0.35, t_info["ev_top"]))
                            missed_accuse_mistakes += 1
                        elif parsed is None or not res.ok or (s_tool != "plant_canary" and s_tool != t_tool):
                            mistake_margin = 0.25
                            other_mistakes += 1

                        if mistake_margin > 0.0 and c_tok is not None:
                            r_tok = _tokenize_reply_on_prompt(
                                tok, batch_msgs[b_idx], st["ctools"], parsed, raw_txt, max_len=max_ctx
                            )
                            if r_tok is not None and r_tok[0] != c_tok[0]:
                                dpo_pairs.append({
                                    "chosen_ids": c_tok[0],
                                    "chosen_labels": c_tok[1],
                                    "rejected_ids": r_tok[0],
                                    "rejected_labels": r_tok[1],
                                    "ev_margin": mistake_margin,
                                })

                        if (
                            c_tok is not None
                            and st["cf_added"] < 2
                            and t_tool != "accuse"
                            and (parsed is None or s_tool != "accuse")
                            and t_info["top_p"] < t_info["breakeven_p"] - 0.04
                            and t_info["day"] >= max(2, t_info["n_days"] - 3)
                        ):
                            cf_tok = _tokenize_reply_on_prompt(
                                tok,
                                batch_msgs[b_idx],
                                st["ctools"],
                                ("accuse", {"employee": t_info["best_emp"]}),
                                "",
                                max_len=max_ctx,
                            )
                            if cf_tok is not None and cf_tok[0] != c_tok[0]:
                                st["cf_added"] += 1
                                dpo_pairs.append({
                                    "chosen_ids": c_tok[0],
                                    "chosen_labels": c_tok[1],
                                    "rejected_ids": cf_tok[0],
                                    "rejected_labels": cf_tok[1],
                                    "ev_margin": min(1.5, max(0.40, -t_info["ev_top"])),
                                })

                if env.done or st["calls_used"] >= max_calls:
                    finalize_slot(st)
                else:
                    still_active.append(st)

            slots = still_active

    episodes = [ep for ep in episodes_by_idx if ep is not None]
    mean_sc = sum(float(e["score"]) for e in episodes) / max(1, len(episodes))
    return {
        "episodes": episodes,
        "mean_score": round(mean_sc, 6),
        "dagger_sft": dagger_sft,
        "dpo_pairs": dpo_pairs,
        "premature_accuse_mistakes": premature_accuse_mistakes,
        "missed_accuse_mistakes": missed_accuse_mistakes,
        "other_mistakes": other_mistakes,
    }


def build_lora_model(model_path: str, r: int = 16, tiny: bool = False):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(1)
    tok = AutoTokenizer.from_pretrained(model_path)
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id

    if tiny:
        from transformers import Qwen2Config, Qwen2ForCausalLM

        cfg = Qwen2Config(
            vocab_size=max(151936, len(tok)),
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=1,
            max_position_embeddings=4096,
            tie_word_embeddings=True,
        )
        cfg._attn_implementation = "sdpa"
        torch.manual_seed(0)
        base = Qwen2ForCausalLM(cfg)
    else:
        dtype = torch.float16 if device == "cuda" else torch.float32
        base = AutoModelForCausalLM.from_pretrained(model_path, dtype=dtype, attn_implementation="sdpa")

    lora_cfg = LoraConfig(
        r=r,
        lora_alpha=2 * r,
        lora_dropout=0.05,
        target_modules=LORA_TARGETS,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.to(device)
    return model, tok, device


def capture_lora_state(model) -> dict[str, Any]:
    return {k: v.detach().cpu().clone() for k, v in model.named_parameters() if v.requires_grad}


def load_lora_state(model, state: dict[str, Any]) -> None:
    named = dict(model.named_parameters())
    for k, val in state.items():
        named[k].data.copy_(val.to(device=named[k].device, dtype=named[k].dtype))


def _enable_train_mode(model) -> None:
    model.config.use_cache = False
    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.train()


def _collate_sft_batch(batch: list[tuple[list[int], list[int], bool]], pad_id: int, device):
    import torch

    max_l = max(len(x[0]) for x in batch)
    inp = torch.full((len(batch), max_l), pad_id, dtype=torch.long, device=device)
    att = torch.zeros((len(batch), max_l), dtype=torch.long, device=device)
    lab = torch.full((len(batch), max_l), -100, dtype=torch.long, device=device)
    wt = torch.ones((len(batch), max_l), dtype=torch.float32, device=device)
    max_ans = 1
    for idx, (ids, labels, is_term) in enumerate(batch):
        off = max_l - len(ids)
        inp[idx, off:] = torch.tensor(ids, dtype=torch.long, device=device)
        att[idx, off:] = 1
        lab[idx, off:] = torch.tensor(labels, dtype=torch.long, device=device)
        if is_term:
            wt[idx, off:] = 2.0
        for p_i, lv in enumerate(labels):
            if lv != -100:
                max_ans = max(max_ans, len(labels) - p_i)
                break
    keep = min(max_l, max_ans + 1)
    return inp, att, lab, wt, keep


def _weighted_sft_loss(logits, labels, weights):
    import torch.nn.functional as F

    keep = logits.size(1)
    if keep < 2:
        return logits.sum() * 0.0
    span = keep - 1
    shift_lg = logits[:, :-1, :].float()
    shift_lb = labels[:, -span:]
    shift_wt = weights[:, -span:]
    ce = F.cross_entropy(
        shift_lg.reshape(-1, shift_lg.size(-1)),
        shift_lb.reshape(-1),
        ignore_index=-100,
        reduction="none",
    )
    active = (shift_lb.reshape(-1) != -100).float()
    denom = (active * shift_wt.reshape(-1)).sum().clamp(min=1.0)
    return (ce * shift_wt.reshape(-1)).sum() / denom


def sequence_logprob(logits, labels):
    import torch

    keep = logits.size(1)
    if keep < 2:
        return logits.new_zeros((logits.size(0),), dtype=torch.float32)
    span = keep - 1
    shift_lg = logits[:, :-1, :].float()
    shift_lb = labels[:, -span:]
    mask = shift_lb != -100
    safe_lb = shift_lb.clamp(min=0)
    tok_lp = torch.log_softmax(shift_lg, dim=-1).gather(-1, safe_lb.unsqueeze(-1)).squeeze(-1)
    return (tok_lp * mask).sum(dim=-1)


def train_sft_stage(
    model,
    tok,
    windows: list[tuple[list[int], list[int], bool]],
    steps: int = 200,
    micro_batch: int = 4,
    grad_accum: int = 4,
    lr: float = 2.5e-4,
    rng_seed: int = 0,
) -> dict[str, Any]:
    import torch

    device = next(model.parameters()).device
    use_amp = device.type == "cuda"
    pad_id = int(tok.pad_token_id or tok.eos_token_id)
    shuffled = list(windows)
    random.Random(rng_seed).shuffle(shuffled)

    _enable_train_mode(model)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    warm = max(1, int(0.06 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1.0, (s + 1) / warm) * (0.5 * (1.0 + math.cos(math.pi * min(1.0, s / max(1, steps))))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    t0 = time.time()
    cursor = 0
    losses: list[float] = []
    for step in range(1, steps + 1):
        step_loss = 0.0
        for _ in range(grad_accum):
            mb = [shuffled[(cursor + k) % len(shuffled)] for k in range(micro_batch)]
            cursor += micro_batch
            if cursor >= len(shuffled):
                random.Random(rng_seed + step).shuffle(shuffled)
                cursor = 0
            inp, att, lab, wt, keep = _collate_sft_batch(mb, pad_id, device)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(input_ids=inp, attention_mask=att, logits_to_keep=keep).logits
                loss = _weighted_sft_loss(logits, lab, wt) / grad_accum
            scaler.scale(loss).backward()
            step_loss += float(loss.detach().item())
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        scaler.step(opt)
        scaler.update()
        opt.zero_grad(set_to_none=True)
        sched.step()
        losses.append(step_loss)
        if step % 25 == 0 or step == steps:
            print(
                f"[sft] step={step}/{steps} loss={step_loss:.4f} elapsed_s={time.time() - t0:.1f}",
                flush=True,
            )

    return {
        "steps": steps,
        "initial_loss": round(losses[0], 4) if losses else 0.0,
        "final_loss": round(losses[-1], 4) if losses else 0.0,
        "seconds": round(time.time() - t0, 2),
    }


def precompute_ref_logps(
    model,
    ref_lora_state: dict[str, Any],
    pairs: list[dict[str, Any]],
    pad_id: int,
    batch_size: int = 8,
) -> None:
    import torch

    if not pairs:
        return
    saved = capture_lora_state(model)
    load_lora_state(model, ref_lora_state)
    if hasattr(model, "gradient_checkpointing_disable"):
        model.gradient_checkpointing_disable()
    model.eval()
    device = next(model.parameters()).device
    use_amp = device.type == "cuda"

    flat_seqs: list[tuple[list[int], list[int], bool]] = []
    for p in pairs:
        flat_seqs.append((p["chosen_ids"], p["chosen_labels"], False))
        flat_seqs.append((p["rejected_ids"], p["rejected_labels"], False))

    all_lps: list[float] = []
    with torch.no_grad():
        for i in range(0, len(flat_seqs), batch_size):
            chunk = flat_seqs[i : i + batch_size]
            inp, att, lab, _, keep = _collate_sft_batch(chunk, pad_id, device)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                lg = model(input_ids=inp, attention_mask=att, logits_to_keep=keep).logits
            lps = sequence_logprob(lg, lab).cpu().tolist()
            all_lps.extend(float(v) for v in lps)

    for idx, p in enumerate(pairs):
        p["ref_chosen_lp"] = all_lps[2 * idx]
        p["ref_rejected_lp"] = all_lps[2 * idx + 1]

    load_lora_state(model, saved)


def train_joint_dpo_dagger_round(
    model,
    tok,
    dagger_sft: list[tuple[list[int], list[int], bool]],
    replay_sft: list[tuple[list[int], list[int], bool]],
    dpo_pairs: list[dict[str, Any]],
    ref_lora_state: dict[str, Any],
    steps: int = 60,
    grad_accum: int = 4,
    lr: float = 7e-5,
    beta: float = 0.15,
    dpo_weight: float = 0.6,
    rng_seed: int = 0,
    round_tag: str = "r1",
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    device = next(model.parameters()).device
    use_amp = device.type == "cuda"
    pad_id = int(tok.pad_token_id or tok.eos_token_id)

    precompute_ref_logps(model, ref_lora_state, dpo_pairs, pad_id=pad_id)
    _enable_train_mode(model)

    rng = random.Random(rng_seed)
    dag_pool = list(dagger_sft) if dagger_sft else list(replay_sft)
    rep_pool = list(replay_sft) if replay_sft else list(dag_pool)
    pair_pool = list(dpo_pairs)
    rng.shuffle(dag_pool)
    rng.shuffle(rep_pool)
    if pair_pool:
        rng.shuffle(pair_pool)

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    warm = max(1, int(0.08 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1.0, (s + 1) / warm) * (0.5 * (1.0 + math.cos(math.pi * min(1.0, s / max(1, steps))))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    t0 = time.time()
    sft_losses: list[float] = []
    dpo_losses: list[float] = []
    dpo_margins: list[float] = []
    c_dag, c_rep, c_pair = 0, 0, 0

    for step in range(1, steps + 1):
        sft_acc = 0.0
        dpo_acc = 0.0
        margin_acc = 0.0
        for _ in range(grad_accum):
            mb_sft = [dag_pool[c_dag % len(dag_pool)], rep_pool[c_rep % len(rep_pool)]]
            c_dag += 1
            c_rep += 1
            inp_s, att_s, lab_s, wt_s, keep_s = _collate_sft_batch(mb_sft, pad_id, device)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                lg_s = model(input_ids=inp_s, attention_mask=att_s, logits_to_keep=keep_s).logits
                loss_s = _weighted_sft_loss(lg_s, lab_s, wt_s) / grad_accum
            scaler.scale(loss_s).backward()
            sft_acc += float(loss_s.detach().item())

            if pair_pool:
                pair = pair_pool[c_pair % len(pair_pool)]
                c_pair += 1
                p_seqs = [
                    (pair["chosen_ids"], pair["chosen_labels"], False),
                    (pair["rejected_ids"], pair["rejected_labels"], False),
                ]
                inp_p, att_p, lab_p, _, keep_p = _collate_sft_batch(p_seqs, pad_id, device)
                with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                    lg_p = model(input_ids=inp_p, attention_mask=att_p, logits_to_keep=keep_p).logits
                lps = sequence_logprob(lg_p, lab_p)
                delta_c = lps[0] - float(pair["ref_chosen_lp"])
                delta_r = lps[1] - float(pair["ref_rejected_lp"])
                u = beta * (delta_c - delta_r)
                target_m = 0.15 * float(pair["ev_margin"])
                loss_d = -F.logsigmoid(u - target_m)
                scaled_d = (dpo_weight * loss_d) / grad_accum
                scaler.scale(scaled_d).backward()
                dpo_acc += float(loss_d.detach().item()) / grad_accum
                margin_acc += float(u.detach().item()) / grad_accum

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        scaler.step(opt)
        scaler.update()
        opt.zero_grad(set_to_none=True)
        sched.step()
        sft_losses.append(sft_acc)
        dpo_losses.append(dpo_acc)
        dpo_margins.append(margin_acc)
        if step % 20 == 0 or step == steps:
            print(
                f"[dpo-{round_tag}] step={step}/{steps} sft={sft_acc:.4f} dpo={dpo_acc:.4f} "
                f"reward_margin={margin_acc:+.4f} elapsed_s={time.time() - t0:.1f}",
                flush=True,
            )

    return {
        "steps": steps,
        "dpo_pairs": len(pair_pool),
        "dagger_sft_windows": len(dagger_sft),
        "final_sft_loss": round(sft_losses[-1], 4) if sft_losses else 0.0,
        "final_dpo_loss": round(dpo_losses[-1], 4) if dpo_losses else 0.0,
        "final_reward_margin": round(dpo_margins[-1], 4) if dpo_margins else 0.0,
        "seconds": round(time.time() - t0, 2),
    }


def _bootstrap_ci(vals: list[float], n_boot: int = 5000, rng_seed: int = 0) -> tuple[float, float, float]:
    if not vals:
        return 0.0, 0.0, 0.0
    n = len(vals)
    mean_v = sum(vals) / n
    if n < 2 or n_boot <= 0:
        return mean_v, mean_v, mean_v
    rng = random.Random(rng_seed)
    means = sorted(sum(rng.choices(vals, k=n)) / n for _ in range(n_boot))
    return mean_v, means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))]


def _score_and_verify_stage(
    stage_name: str,
    episodes: list[dict[str, Any]],
    run_dir: Path,
    world_secret: str,
    secret_tag: str,
    tiers: tuple[str, ...],
    bootstrap_n: int = 5000,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "meta.json"
    ep_path = run_dir / "episodes.jsonl"
    meta_path.write_text(
        json.dumps({"run_id": stage_name, "agent": stage_name, "world_secret_tag": secret_tag}, indent=2),
        encoding="utf-8",
    )
    with open(ep_path, "w", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep, default=str) + "\n")

    ver = verify_episode_file(ep_path, world_secret=world_secret)
    if not ver["replay_ok"] or ver["mismatch_count"] != 0 or ver["excluded_count"] != 0:
        raise RuntimeError(f"replay verification failed for {stage_name}: {ver['mismatches'][:3]}")

    ordered_eps = sorted(episodes, key=lambda r: (tiers.index(str(r["tier"])), int(r["seed"])))
    scored = [luck_adjusted_episode_ev(ep, world_secret=world_secret) for ep in ordered_eps]
    if not all(r["replay_match"] for r in scored):
        raise RuntimeError(f"luck_adjusted_episode_ev replay mismatch in {stage_name}")

    def summarize_rows(rows: list[dict[str, Any]], seed_offset: int) -> dict[str, Any]:
        n_r = len(rows)
        raw_s = [round(float(r["raw_score"]), 6) for r in rows]
        evs = [round(float(r["luck_adjusted_ev"]), 6) for r in rows]
        m_sc, sc_lo, sc_hi = _bootstrap_ci(raw_s, n_boot=bootstrap_n, rng_seed=seed_offset)
        m_ev, ev_lo, ev_hi = _bootstrap_ci(evs, n_boot=bootstrap_n, rng_seed=seed_offset + 17)
        tot_calls = sum(int(r["total_calls"]) for r in rows)
        val_calls = sum(int(r["valid_calls"]) for r in rows)
        n_acc = sum(1 for r in rows if r["accused"] is not None and r["end_reason"] == "accused")
        n_cor = sum(1 for r in rows if r["correct"])
        n_wrg = sum(
            1 for r in rows if r["accused"] is not None and r["end_reason"] == "accused" and not r["correct"]
        )
        return {
            "n": n_r,
            "mean_score": round(m_sc, 6),
            "ci95": round((sc_hi - sc_lo) / 2.0, 6),
            "ci95_low": round(sc_lo, 6),
            "ci95_high": round(sc_hi, 6),
            "luck_adjusted_ev": round(m_ev, 6),
            "luck_ci95_low": round(ev_lo, 6),
            "luck_ci95_high": round(ev_hi, 6),
            "accuracy": round(n_cor / max(1, n_r), 6),
            "accuse_rate": round(n_acc / max(1, n_r), 6),
            "abstain_rate": round((n_r - n_acc) / max(1, n_r), 6),
            "wrong_accuse_rate": round(n_wrg / max(1, n_r), 6),
            "valid_call_rate": round(val_calls / max(1, tot_calls), 6) if tot_calls > 0 else 1.0,
            "scores": raw_s,
            "luck_evs": evs,
        }

    overall = summarize_rows(scored, seed_offset=100)
    by_tier = {}
    for t_i, tier in enumerate(tiers):
        t_rows = [r for r in scored if r["tier"] == tier]
        t_sum = summarize_rows(t_rows, seed_offset=200 + t_i)
        t_sum.pop("scores", None)
        t_sum.pop("luck_evs", None)
        by_tier[tier] = t_sum

    luck_evs = overall.pop("luck_evs")
    overall["world_secret_tag"] = secret_tag
    overall["replay_verified"] = True
    overall["invalid_episodes"] = int(ver["excluded_count"])
    overall["by_tier"] = by_tier
    return {"summary": overall, "scored": scored, "luck_evs": luck_evs}


def _paired_summary(
    before_scores: list[float],
    after_scores: list[float],
    before_evs: list[float],
    after_evs: list[float],
    bootstrap_n: int = 5000,
    rng_seed: int = 0,
) -> dict[str, Any]:
    deltas = [round(float(a) - float(b), 6) for b, a in zip(before_scores, after_scores)]
    ev_deltas = [round(float(a) - float(b), 6) for b, a in zip(before_evs, after_evs)]
    m_d, lo_d, hi_d = _bootstrap_ci(deltas, n_boot=bootstrap_n, rng_seed=rng_seed)
    m_e, lo_e, hi_e = _bootstrap_ci(ev_deltas, n_boot=bootstrap_n, rng_seed=rng_seed + 31)
    n = len(deltas)
    if n >= 2:
        var = sum((x - m_d) ** 2 for x in deltas) / (n - 1)
        norm_half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    else:
        norm_half = 0.0
    wins = sum(1 for d in deltas if d > 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    return {
        "mean_delta": round(m_d, 6),
        "ci95_low": round(lo_d, 6),
        "ci95_high": round(hi_d, 6),
        "normal_ci95_low": round(m_d - norm_half, 6),
        "normal_ci95_high": round(m_d + norm_half, 6),
        "luck_adjusted_mean_delta": round(m_e, 6),
        "luck_adjusted_ci95_low": round(lo_e, 6),
        "luck_adjusted_ci95_high": round(hi_e, 6),
        "wins": wins,
        "losses": losses,
        "ties": n - wins - losses,
        "deltas": deltas,
    }


def format_summary_markdown(summary: dict[str, Any]) -> str:
    b = summary["before"]
    s = summary["sft_only"]
    a = summary["after"]
    p_main = summary["paired"]
    p_sft = summary["paired_sft_vs_base"]
    p_dpo = summary["paired_dpo_vs_sft"]
    lines = [
        f"**Qwen2.5-1.5B-Instruct Compact SFT + EV-Margin DPO + 2-Round DAgger (`{summary['run_id']}`)**",
        "",
        f"- Tiers: `{','.join(summary['tiers'])}` (`{summary['tiers_version']}`), paired held-out `n = {summary['n']}` (`{summary['eval_seeds']['start']}..{summary['eval_seeds']['stop'] - 1}`), train seeds `{summary['train_seeds']['start']}..{summary['train_seeds']['stop'] - 1}`",
        f"- Shared `world_secret_tag`: `{b['world_secret_tag']}`, `replay_verified = {summary['replay_verified']}`, `invalid_episodes = {summary['invalid_episodes']}`",
        f"- Evaluation protocol: strictly disjoint `HELDOUT_SEEDS` (`{summary['eval_seeds']['start']}..{summary['eval_seeds']['stop'] - 1}`), zero overlap with `TRAIN_SEEDS`, `DEV_SEEDS`, or `JUDGE_SEEDS`.",
        "",
        "| Stage | Scope | n | Mean Score [95% CI] | Luck-Adj EV [95% CI] | Acc | Accuse | Abstain | Wrong | Valid Calls |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lbl, st_obj in (("base_compact (before)", b), ("sft_only", s), ("dpo_dagger_r2 (after)", a)):
        lines.append(
            f"| {lbl} | all | {st_obj['n']} | {st_obj['mean_score']:+.4f} [{st_obj['ci95_low']:+.4f}, {st_obj['ci95_high']:+.4f}] | "
            f"{st_obj['luck_adjusted_ev']:+.4f} [{st_obj['luck_ci95_low']:+.4f}, {st_obj['luck_ci95_high']:+.4f}] | "
            f"{st_obj['accuracy']:.1%} | {st_obj['accuse_rate']:.1%} | {st_obj['abstain_rate']:.1%} | "
            f"{st_obj['wrong_accuse_rate']:.1%} | {st_obj['valid_call_rate']:.1%} |"
        )
        for tier in summary["tiers"]:
            tr = st_obj["by_tier"][tier]
            lines.append(
                f"| {lbl} | {tier} | {tr['n']} | {tr['mean_score']:+.4f} [{tr['ci95_low']:+.4f}, {tr['ci95_high']:+.4f}] | "
                f"{tr['luck_adjusted_ev']:+.4f} [{tr['luck_ci95_low']:+.4f}, {tr['luck_ci95_high']:+.4f}] | "
                f"{tr['accuracy']:.1%} | {tr['accuse_rate']:.1%} | {tr['abstain_rate']:.1%} | "
                f"{tr['wrong_accuse_rate']:.1%} | {tr['valid_call_rate']:.1%} |"
            )

    lines.extend([
        "",
        "| Paired Comparison | n | Mean Score Delta [95% CI] | Luck-Adj EV Delta [95% CI] | W/L/T |",
        "|---|---:|---:|---:|---:|",
        (
            f"| sft_only - base_compact | {summary['n']} | "
            f"{p_sft['mean_delta']:+.4f} [{p_sft['ci95_low']:+.4f}, {p_sft['ci95_high']:+.4f}] | "
            f"{p_sft['luck_adjusted_mean_delta']:+.4f} [{p_sft['luck_adjusted_ci95_low']:+.4f}, {p_sft['luck_adjusted_ci95_high']:+.4f}] | "
            f"{p_sft['wins']}/{p_sft['losses']}/{p_sft['ties']} |"
        ),
        (
            f"| dpo_dagger_r2 - sft_only | {summary['n']} | "
            f"{p_dpo['mean_delta']:+.4f} [{p_dpo['ci95_low']:+.4f}, {p_dpo['ci95_high']:+.4f}] | "
            f"{p_dpo['luck_adjusted_mean_delta']:+.4f} [{p_dpo['luck_adjusted_ci95_low']:+.4f}, {p_dpo['luck_adjusted_ci95_high']:+.4f}] | "
            f"{p_dpo['wins']}/{p_dpo['losses']}/{p_dpo['ties']} |"
        ),
        (
            f"| dpo_dagger_r2 - base_compact (headline) | {summary['n']} | "
            f"{p_main['mean_delta']:+.4f} [{p_main['ci95_low']:+.4f}, {p_main['ci95_high']:+.4f}] | "
            f"{p_main['luck_adjusted_mean_delta']:+.4f} [{p_main['luck_adjusted_ci95_low']:+.4f}, {p_main['luck_adjusted_ci95_high']:+.4f}] | "
            f"{p_main['wins']}/{p_main['losses']}/{p_main['ties']} |"
        ),
    ])
    return "\n".join(lines) + "\n"


def _torch_stack_ready(model_path: str) -> bool:
    if not Path(model_path).is_dir():
        return False
    try:
        import peft
        import torch
        import transformers

        _ = (peft, torch, transformers)
        return True
    except ImportError:
        return False


def _rollout_policy_pure_python(
    jobs: list[tuple[str, int]],
    agent_name: str,
    generator_fn,
    max_calls: int,
    world_secret_tag: str,
) -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    for t_name, seed_val in jobs:
        env = Env(tier=t_name, seed=seed_val)
        pol = QwenCompactDpoPolicy(name=agent_name, generator=generator_fn)
        pol.reset(env.tools_spec(), env.instruction())
        calls = 0
        while not env.done and calls < max_calls:
            tool, call_args = pol.act(env.history)
            env.call(tool, call_args)
            calls += 1
        ep = env.result(agent_name)
        if not env.done:
            ep.end_reason = "eval_cap"
        ep.meta = dict(ep.meta or {})
        ep.meta["invalid_calls"] = pol.invalid
        ep.meta["world_secret_tag"] = world_secret_tag
        episodes.append(dataclasses.asdict(ep))
    mean_sc = sum(float(e["score"]) for e in episodes) / max(1, len(episodes))
    return {
        "episodes": episodes,
        "mean_score": round(mean_sc, 6),
        "dagger_sft": [],
        "dpo_pairs": [],
        "premature_accuse_mistakes": 0,
        "missed_accuse_mistakes": 0,
        "other_mistakes": 0,
    }


def _finalize_and_write_outputs(
    args: argparse.Namespace,
    tiers: tuple[str, ...],
    seed_plan: dict[str, list[int]],
    eval_jobs: list[tuple[str, int]],
    world_secret: str,
    secret_tag: str,
    scratch: Path,
    boot_n: int,
    base_eval: dict[str, Any],
    sft_eval: dict[str, Any],
    r2_eval: dict[str, Any],
    sft_data_stats: dict[str, Any],
    sft_train_stats: dict[str, Any],
    r1_roll: dict[str, Any],
    r1_train_stats: dict[str, Any],
    r2_roll: dict[str, Any],
    r2_train_stats: dict[str, Any],
    t_start: float,
) -> dict[str, Any]:
    eval_root = scratch / "eval"
    base_ver = _score_and_verify_stage("base_compact", base_eval["episodes"], eval_root / "base_compact", world_secret, secret_tag, tiers, boot_n)
    sft_ver = _score_and_verify_stage("sft_only", sft_eval["episodes"], eval_root / "sft_only", world_secret, secret_tag, tiers, boot_n)
    r2_ver = _score_and_verify_stage("dpo_dagger_r2", r2_eval["episodes"], eval_root / "dpo_dagger_r2", world_secret, secret_tag, tiers, boot_n)

    hygiene = audit_seed_hygiene(
        train_seeds=seed_plan["train_all"],
        eval_seeds=seed_plan["eval"],
        world_secret_tags={
            "before": base_ver["summary"]["world_secret_tag"],
            "sft_only": sft_ver["summary"]["world_secret_tag"],
            "after": r2_ver["summary"]["world_secret_tag"],
        },
    )
    if not hygiene["ok"]:
        raise RuntimeError(f"seed/secret hygiene audit failed: {hygiene['violations']}")

    paired_main = _paired_summary(
        base_ver["summary"]["scores"],
        r2_ver["summary"]["scores"],
        base_ver["luck_evs"],
        r2_ver["luck_evs"],
        bootstrap_n=boot_n,
        rng_seed=args.rng_seed,
    )
    paired_sft = _paired_summary(
        base_ver["summary"]["scores"],
        sft_ver["summary"]["scores"],
        base_ver["luck_evs"],
        sft_ver["luck_evs"],
        bootstrap_n=boot_n,
        rng_seed=args.rng_seed + 1,
    )
    paired_dpo_vs_sft = _paired_summary(
        sft_ver["summary"]["scores"],
        r2_ver["summary"]["scores"],
        sft_ver["luck_evs"],
        r2_ver["luck_evs"],
        bootstrap_n=boot_n,
        rng_seed=args.rng_seed + 2,
    )

    summary_payload: dict[str, Any] = {
        "run_id": args.run_id,
        "model": "Qwen2.5-1.5B-Instruct Compact SFT + EV-DPO + DAgger r2",
        "tiers_version": "v1.4",
        "tiers": list(tiers),
        "n": len(eval_jobs),
        "train_seeds": {"start": min(seed_plan["train_all"]), "stop": max(seed_plan["train_all"]) + 1},
        "sft_seed_range": f"{min(seed_plan['sft'])}..{max(seed_plan['sft'])}",
        "dagger_seed_range": f"{min(seed_plan['r1'])}..{max(seed_plan['r2'])}",
        "eval_seeds": {"start": min(seed_plan["eval"]), "stop": max(seed_plan["eval"]) + 1},
        "eval_seeds_per_tier": len(seed_plan["eval"]),
        "rng_seed": args.rng_seed,
        "replay_verified": True,
        "invalid_episodes": 0,
        "world_secret_tag": secret_tag,
        "inference_modules": [
            "train/compact_render.py",
            "train/eval_compact_hf.py",
            "train/qwen15b_dpo_dagger.py",
        ],
        "before": base_ver["summary"],
        "sft_only": sft_ver["summary"],
        "after": r2_ver["summary"],
        "paired": paired_main,
        "paired_sft_vs_base": paired_sft,
        "paired_dpo_vs_sft": paired_dpo_vs_sft,
        "training_telemetry": {
            "stop_margin": args.stop_margin,
            "dpo_beta": args.dpo_beta,
            "dpo_weight": args.dpo_weight,
            "lora_r": args.lora_r,
            "sft_data": sft_data_stats,
            "sft_train": sft_train_stats,
            "dagger_r1_rollout": {
                "mean_score": r1_roll["mean_score"],
                "premature_accuse_mistakes": r1_roll["premature_accuse_mistakes"],
                "missed_accuse_mistakes": r1_roll["missed_accuse_mistakes"],
                "other_mistakes": r1_roll["other_mistakes"],
            },
            "dagger_r1_train": r1_train_stats,
            "dagger_r2_rollout": {
                "mean_score": r2_roll["mean_score"],
                "premature_accuse_mistakes": r2_roll["premature_accuse_mistakes"],
                "missed_accuse_mistakes": r2_roll["missed_accuse_mistakes"],
                "other_mistakes": r2_roll["other_mistakes"],
            },
            "dagger_r2_train": r2_train_stats,
        },
        "elapsed_seconds": round(time.time() - t_start, 2),
        "notes": (
            "Paired before/after evaluation of Qwen2.5-1.5B-Instruct on CompactState working-memory prompts "
            "before (untrained base) vs after calibrated LoRA SFT + on-policy EV-margin DPO + 2-round DAgger "
            "trained strictly on TRAIN_SEEDS and replay-verified on HELDOUT_SEEDS under shared world secret."
        ),
    }

    out_summary = Path(args.out_summary)
    out_table = Path(args.out_table)
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_table.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    out_table.write_text(format_summary_markdown(summary_payload), encoding="utf-8")

    scratch_summary = scratch / "summary.json"
    scratch_table = scratch / "table.md"
    scratch_summary.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    scratch_table.write_text(format_summary_markdown(summary_payload), encoding="utf-8")

    print(
        f"[done] before={base_ver['summary']['mean_score']:+.4f} sft={sft_ver['summary']['mean_score']:+.4f} "
        f"after={r2_ver['summary']['mean_score']:+.4f} delta={paired_main['mean_delta']:+.4f} "
        f"[{paired_main['ci95_low']:+.4f}, {paired_main['ci95_high']:+.4f}] elapsed_s={summary_payload['elapsed_seconds']}",
        flush=True,
    )
    return summary_payload


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    t_start = time.time()
    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    for t in tiers:
        if t not in RULE_TIERS:
            raise ValueError(f"unknown tier {t!r}")

    if args.tiny:
        sft_seeds = [SFT_SEED_START]
        r1_seeds = [SFT_SEED_START + 1]
        r2_seeds = [SFT_SEED_START + 2]
        eval_seeds = [EVAL_SEED_START]
        sft_steps = 1
        dpo_steps = 1
        censored_n = 0
        batch_sz = 3
        max_calls_train = 1
        max_calls_eval = 1
        max_new = 4
        boot_n = 50
    else:
        sft_seeds = list(range(SFT_SEED_START, SFT_SEED_START + args.sft_episodes))
        r1_start = sft_seeds[-1] + 1 if sft_seeds else DAGGER_R1_START
        r1_seeds = list(range(r1_start, r1_start + args.dagger_episodes_per_round))
        r2_start = r1_seeds[-1] + 1 if r1_seeds else DAGGER_R2_START
        r2_seeds = list(range(r2_start, r2_start + args.dagger_episodes_per_round))
        eval_seeds = list(range(EVAL_SEED_START, EVAL_SEED_START + args.eval_seeds_per_tier))
        sft_steps = args.sft_steps
        dpo_steps = args.dpo_steps
        censored_n = args.censored_abstentions
        batch_sz = args.batch_size
        max_calls_train = args.max_calls_train
        max_calls_eval = args.max_calls_eval
        max_new = args.max_new_tokens
        boot_n = args.bootstrap_n

    seed_plan = validate_seed_plan(sft_seeds, r1_seeds, r2_seeds, eval_seeds)
    world_secret = args.world_secret or os.environ.get("CANARY_WORLD_SECRET") or DEFAULT_HELD_OUT_WORLD_SECRET
    secret_tag = compute_world_secret_tag(world_secret)
    if secret_tag is None:
        raise ValueError("world_secret must produce a valid sha256 tag")

    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    eval_jobs = [(tier, s) for tier in tiers for s in seed_plan["eval"]]

    if args.tiny and not _torch_stack_ready(args.model):
        with _world_secret_scope(world_secret):
            t_scores: list[float] = []
            for idx, seed_val in enumerate(seed_plan["sft"]):
                env = Env(tier=tiers[idx % len(tiers)], seed=seed_val)
                ins, ts = env.instruction(), env.tools_spec()
                for _ in range(int(env.p.tool_call_cap)):
                    if env.done:
                        break
                    info = calibrated_teacher_step(ins, ts, env.history, stop_margin=args.stop_margin)
                    env.call(info["tool"], info["args"])
                t_scores.append(float(env.result("calibrated_teacher").score))
            sft_data_stats = {
                "sft_episodes": len(seed_plan["sft"]),
                "teacher_mean_score": round(sum(t_scores) / max(1, len(t_scores)), 6),
                "sft_windows": len(seed_plan["sft"]),
            }
            abstain_gen = lambda _turn: '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>'
            r1_jobs = [(tiers[i % len(tiers)], s) for i, s in enumerate(seed_plan["r1"])]
            r2_jobs = [(tiers[i % len(tiers)], s) for i, s in enumerate(seed_plan["r2"])]
            r1_roll = _rollout_policy_pure_python(r1_jobs, "dagger_r1_student", abstain_gen, max_calls_train, secret_tag)
            r2_roll = _rollout_policy_pure_python(r2_jobs, "dagger_r2_student", abstain_gen, max_calls_train, secret_tag)
            base_eval = _rollout_policy_pure_python(eval_jobs, "base_compact", abstain_gen, max_calls_eval, secret_tag)
            sft_eval = _rollout_policy_pure_python(eval_jobs, "sft_only", abstain_gen, max_calls_eval, secret_tag)
            r2_eval = _rollout_policy_pure_python(eval_jobs, "dpo_dagger_r2", abstain_gen, max_calls_eval, secret_tag)
        stub_train = {"steps": sft_steps, "seconds": 0.01}
        return _finalize_and_write_outputs(
            args=args,
            tiers=tiers,
            seed_plan=seed_plan,
            eval_jobs=eval_jobs,
            world_secret=world_secret,
            secret_tag=secret_tag,
            scratch=scratch,
            boot_n=boot_n,
            base_eval=base_eval,
            sft_eval=sft_eval,
            r2_eval=r2_eval,
            sft_data_stats=sft_data_stats,
            sft_train_stats=stub_train,
            r1_roll=r1_roll,
            r1_train_stats=stub_train,
            r2_roll=r2_roll,
            r2_train_stats=stub_train,
            t_start=t_start,
        )

    print(f"[init] loading model={args.model} tiny={args.tiny}", flush=True)
    model, tok, device = build_lora_model(args.model, r=args.lora_r, tiny=args.tiny)
    print(f"[init] device={device} secret_tag={secret_tag}", flush=True)

    with _world_secret_scope(world_secret):
        sft_windows, sft_data_stats = collect_sft_windows(
            sft_seeds=seed_plan["sft"],
            tiers=tiers,
            tok=tok,
            max_len=args.max_ctx,
            stop_margin=args.stop_margin,
            censored_count=censored_n,
        )
        print(f"[sft-data] {json.dumps(sft_data_stats)}", flush=True)

        sft_train_stats = train_sft_stage(
            model=model,
            tok=tok,
            windows=sft_windows,
            steps=sft_steps,
            micro_batch=2 if args.tiny else args.sft_micro_batch,
            grad_accum=1 if args.tiny else args.grad_accum,
            lr=args.sft_lr,
            rng_seed=args.rng_seed,
        )
        sft_lora_state = capture_lora_state(model)
        sft_dir = scratch / "adapters" / "sft_only"
        sft_dir.mkdir(parents=True, exist_ok=True)
        if not args.tiny:
            model.save_pretrained(str(sft_dir))

        r1_jobs = [(tiers[i % len(tiers)], s) for i, s in enumerate(seed_plan["r1"])]
        t_r1 = time.time()
        r1_roll = rollout_batched(
            model=model,
            tok=tok,
            jobs=r1_jobs,
            agent_name="dagger_r1_student",
            batch_size=batch_sz,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new,
            max_calls=max_calls_train,
            collect_dagger=True,
            stop_margin=args.stop_margin,
            world_secret_tag=secret_tag,
        )
        print(
            f"[dagger-r1-rollout] mean_score={r1_roll['mean_score']:+.4f} sft_win={len(r1_roll['dagger_sft'])} "
            f"dpo_pairs={len(r1_roll['dpo_pairs'])} premature_acc={r1_roll['premature_accuse_mistakes']} "
            f"seconds={time.time() - t_r1:.1f}",
            flush=True,
        )
        r1_train_stats = train_joint_dpo_dagger_round(
            model=model,
            tok=tok,
            dagger_sft=r1_roll["dagger_sft"],
            replay_sft=sft_windows,
            dpo_pairs=r1_roll["dpo_pairs"],
            ref_lora_state=sft_lora_state,
            steps=dpo_steps,
            grad_accum=1 if args.tiny else args.grad_accum,
            lr=args.dpo_lr_r1,
            beta=args.dpo_beta,
            dpo_weight=args.dpo_weight,
            rng_seed=args.rng_seed + 101,
            round_tag="r1",
        )

        r2_jobs = [(tiers[i % len(tiers)], s) for i, s in enumerate(seed_plan["r2"])]
        t_r2 = time.time()
        r2_roll = rollout_batched(
            model=model,
            tok=tok,
            jobs=r2_jobs,
            agent_name="dagger_r2_student",
            batch_size=batch_sz,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new,
            max_calls=max_calls_train,
            collect_dagger=True,
            stop_margin=args.stop_margin,
            world_secret_tag=secret_tag,
        )
        print(
            f"[dagger-r2-rollout] mean_score={r2_roll['mean_score']:+.4f} sft_win={len(r2_roll['dagger_sft'])} "
            f"dpo_pairs={len(r2_roll['dpo_pairs'])} premature_acc={r2_roll['premature_accuse_mistakes']} "
            f"seconds={time.time() - t_r2:.1f}",
            flush=True,
        )
        r1_keep = r1_roll["dpo_pairs"][::2]
        merged_pairs = list(r2_roll["dpo_pairs"]) + r1_keep
        merged_dag_sft = list(r2_roll["dagger_sft"]) + r1_roll["dagger_sft"][::2]
        r2_train_stats = train_joint_dpo_dagger_round(
            model=model,
            tok=tok,
            dagger_sft=merged_dag_sft,
            replay_sft=sft_windows,
            dpo_pairs=merged_pairs,
            ref_lora_state=sft_lora_state,
            steps=dpo_steps,
            grad_accum=1 if args.tiny else args.grad_accum,
            lr=args.dpo_lr_r2,
            beta=args.dpo_beta,
            dpo_weight=args.dpo_weight,
            rng_seed=args.rng_seed + 202,
            round_tag="r2",
        )
        r2_lora_state = capture_lora_state(model)
        r2_dir = scratch / "adapters" / "dpo_dagger_r2"
        r2_dir.mkdir(parents=True, exist_ok=True)
        if not args.tiny:
            model.save_pretrained(str(r2_dir))

        print(f"[eval] running paired held-out evaluation on n={len(eval_jobs)} episodes", flush=True)

        base_eval = rollout_batched(
            model=model,
            tok=tok,
            jobs=eval_jobs,
            agent_name="base_compact",
            batch_size=batch_sz,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new,
            max_calls=max_calls_eval,
            disable_adapter=True,
            world_secret_tag=secret_tag,
        )
        load_lora_state(model, sft_lora_state)
        sft_eval = rollout_batched(
            model=model,
            tok=tok,
            jobs=eval_jobs,
            agent_name="sft_only",
            batch_size=batch_sz,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new,
            max_calls=max_calls_eval,
            disable_adapter=False,
            world_secret_tag=secret_tag,
        )
        load_lora_state(model, r2_lora_state)
        r2_eval = rollout_batched(
            model=model,
            tok=tok,
            jobs=eval_jobs,
            agent_name="dpo_dagger_r2",
            batch_size=batch_sz,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new,
            max_calls=max_calls_eval,
            disable_adapter=False,
            world_secret_tag=secret_tag,
        )

    return _finalize_and_write_outputs(
        args=args,
        tiers=tiers,
        seed_plan=seed_plan,
        eval_jobs=eval_jobs,
        world_secret=world_secret,
        secret_tag=secret_tag,
        scratch=scratch,
        boot_n=boot_n,
        base_eval=base_eval,
        sft_eval=sft_eval,
        r2_eval=r2_eval,
        sft_data_stats=sft_data_stats,
        sft_train_stats=sft_train_stats,
        r1_roll=r1_roll,
        r1_train_stats=r1_train_stats,
        r2_roll=r2_roll,
        r2_train_stats=r2_train_stats,
        t_start=t_start,
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.qwen15b_dpo_dagger")
    ap.add_argument("--model", default=DEFAULT_MODEL_PATH)
    ap.add_argument("--scratch-dir", default=DEFAULT_SCRATCH_DIR)
    ap.add_argument("--out-summary", default=DEFAULT_SUMMARY_OUT)
    ap.add_argument("--out-table", default=DEFAULT_TABLE_OUT)
    ap.add_argument("--run-id", default="qwen15b-dpo-dagger-v14")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--world-secret", default=DEFAULT_HELD_OUT_WORLD_SECRET)
    ap.add_argument("--sft-episodes", type=int, default=240)
    ap.add_argument("--censored-abstentions", type=int, default=36)
    ap.add_argument("--dagger-episodes-per-round", type=int, default=60)
    ap.add_argument("--eval-seeds-per-tier", type=int, default=30)
    ap.add_argument("--stop-margin", type=float, default=0.06)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--sft-steps", type=int, default=180)
    ap.add_argument("--sft-micro-batch", type=int, default=4)
    ap.add_argument("--sft-lr", type=float, default=2.5e-4)
    ap.add_argument("--dpo-steps", type=int, default=55)
    ap.add_argument("--dpo-lr-r1", type=float, default=7e-5)
    ap.add_argument("--dpo-lr-r2", type=float, default=5e-5)
    ap.add_argument("--dpo-beta", type=float, default=0.15)
    ap.add_argument("--dpo-weight", type=float, default=0.6)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--max-ctx", type=int, default=2048)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--max-calls-train", type=int, default=110)
    ap.add_argument("--max-calls-eval", type=int, default=115)
    ap.add_argument("--bootstrap-n", type=int, default=5000)
    ap.add_argument("--rng-seed", type=int, default=0)
    ap.add_argument("--tiny", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_pipeline(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
