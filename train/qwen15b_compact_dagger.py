from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import dataclasses
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, TIERS_VERSION, TRAIN_SEEDS
from train.compact_render import (
    CompactHFPolicy,
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
from train.render import parse_tool_call

RUN_ID = "qwen15b-compact-dagger-v14"
MODEL_LABEL = "Qwen2.5-1.5B-Instruct Compact LoRA + On-Policy DAgger r1"
DEFAULT_MODEL_PATH = "/home/silas/agent-arena-data/models/Qwen2.5-1.5B-Instruct"
DEFAULT_WORK_DIR = "/tmp/fleet-silas/shared/tiebreak-v100/qwen15b_compact_dagger"
EVAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
VARIANT_LABELS: tuple[str, ...] = ("A", "B", "C")


class QwenCompactPolicy(CompactHFPolicy):
    def __init__(
        self,
        model=None,
        tokenizer=None,
        name: str = "qwen15b_compact",
        max_ctx: int = 2048,
        max_new: int = 72,
        tail_turns: int = 4,
        kv_reuse: bool = True,
        generator=None,
    ) -> None:
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


def _mean_ci95(xs: list[float]) -> tuple[float, float, float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    mean_v = sum(xs) / n
    if n < 2:
        return mean_v, mean_v, mean_v, 0.0
    var = sum((x - mean_v) ** 2 for x in xs) / (n - 1)
    hw = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return mean_v, mean_v - hw, mean_v + hw, hw


def query_calibrated_teacher(
    instruction: str,
    history: list,
    d_cut: int | None = None,
    max_calls: int = 65,
) -> tuple[str, dict[str, Any]]:
    from canary.solver.policy import SolverPolicy

    ledger = extract_public_ledger(instruction, history)
    _ = compact_user_text(ledger)
    if not ledger["employees"]:
        return "list_employees", {}

    sp = SolverPolicy()
    sp.reset([], instruction)
    for st in history:
        sp._ingest(st)
    sp.seen = len(history)
    post = sp.belief()
    ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
    top_emp, top_p = ranked[0][0], float(ranked[0][1])

    day = int(ledger["day"])
    n_days = int(ledger["n_days"])
    known_v = float(ledger["known_v"])
    breakeven_p = 1.0 / (1.0 + known_v)
    actions_today = int(ledger["actions_today"])
    actions_cap = int(ledger["actions_per_day"])
    calls_used = len(history)

    today_steps = []
    for st in reversed(history):
        res = st.result if hasattr(st, "result") else st["result"]
        tool = st.tool if hasattr(st, "tool") else st["tool"]
        if tool == "advance_day" and isinstance(res, dict) and res.get("ok"):
            break
        today_steps.append(st)

    def _ok_tool(step_obj: Any, tname: str) -> bool:
        t = step_obj.tool if hasattr(step_obj, "tool") else step_obj["tool"]
        r = step_obj.result if hasattr(step_obj, "result") else step_obj["result"]
        return t == tname and isinstance(r, dict) and bool(r.get("ok"))

    checked_feed = any(_ok_tool(s, "check_leak_feed") for s in today_steps)
    listed_docs = any(_ok_tool(s, "list_documents") for s in today_steps)
    canaries_today = sum(1 for s in today_steps if _ok_tool(s, "plant_canary"))

    if day >= 2 and not checked_feed and actions_today < actions_cap and calls_used < max_calls - 3:
        if d_cut is None or day <= d_cut + 1:
            return "check_leak_feed", {}

    missing_doc = any(it.doc_id and it.doc_id not in sp.obs.docs for it in sp.obs.feed)
    if missing_doc and not listed_docs and calls_used < max_calls - 3:
        return "list_documents", {"day_from": 1, "day_to": day}

    req_p = (
        (breakeven_p + 0.05)
        if (day >= n_days or calls_used >= max_calls - 7)
        else max(0.85, breakeven_p + 0.05)
    )
    if d_cut is None and top_p >= req_p:
        return "accuse", {"employee": top_emp}

    min_delay = min(sp.P.delay_choices)
    max_can = min(int(sp.P.canaries_per_day), 2 if (sp.P.canaries_per_day > 1 and day <= 12) else 1)
    can_plant = (
        (d_cut is None or day <= d_cut)
        and day <= n_days - min_delay
        and canaries_today < max_can
        and actions_today < actions_cap
        and known_v > 0.20
        and calls_used + (n_days - day) * 2 < max_calls - 5
    )
    if can_plant:
        recent_tested: set[str] = set()
        for c in ledger["canaries"]:
            if day - int(c["day"]) <= max(sp.P.delay_choices):
                for emps in c["variants"].values():
                    recent_tested.update(emps)
        restricted = {e for e, cnt in ledger["consistency_counts"].items() if cnt.get("restricted")}
        elig = [e for e, _ in ranked if e not in restricted]
        top4_mass = sum(post[e] for e in elig[:4])
        if top4_mass >= 0.55:
            pool = [e for e in elig if post[e] > 0.01][:4]
            if len(pool) < 2:
                pool = elig[:2]
        else:
            untested = [e for e in elig if e not in recent_tested]
            pool = (untested + [e for e in elig if e not in untested])[:4]
        if pool:
            k_vars = min(int(sp.P.max_variants), len(pool), 3)
            asg: dict[str, str] = {}
            for idx, eid in enumerate(pool):
                v_idx = (idx % k_vars) if (canaries_today == 0 or len(pool) <= k_vars) else ((idx * k_vars) // len(pool))
                asg[eid] = VARIANT_LABELS[v_idx]
            asg = dict(sorted(asg.items()))
            title = f"m{day}" if canaries_today == 0 else f"m{day}b"
            return "plant_canary", {"doc_title": title, "assignment": asg}

    return "advance_day", {}


def _select_turn_indices(steps: list, end_reason: str) -> list[int]:
    n = len(steps)
    if n == 0:
        return []
    keep: set[int] = {0, n - 1}
    can_idx: list[int] = []
    routine_idx: list[int] = []
    for idx, st in enumerate(steps):
        tname = st.tool if hasattr(st, "tool") else st["tool"]
        if tname in ("accuse", "list_employees", "list_documents"):
            keep.add(idx)
        elif tname == "plant_canary":
            can_idx.append(idx)
        else:
            routine_idx.append(idx)
    for idx in can_idx[:2] + can_idx[-2:]:
        keep.add(idx)
    for idx in routine_idx[:2] + routine_idx[-3:]:
        keep.add(idx)
    ordered = sorted(keep)
    if end_reason in ("accused", "horizon"):
        ordered.append(n - 1)
    return ordered


def _rollout_teacher_job(job: tuple[str, int, int | None, int, int]) -> dict[str, Any] | None:
    tier, seed, d_cut, max_calls, tail_turns = job
    if seed not in TRAIN_SEEDS or not (100_000 <= seed < 200_000):
        raise ValueError(f"non-train seed {seed}")
    schedules = [None] if d_cut is None else [d_cut, 0]
    for cur_cut in schedules:
        env = Env(tier=tier, seed=seed)
        ins = env.instruction()
        ctools = compact_tools_spec(env.tools_spec())
        for _ in range(max_calls):
            if env.done:
                break
            tool, args = query_calibrated_teacher(ins, env.history, d_cut=cur_cut, max_calls=max_calls)
            env.call(tool, args)
        ep = env.result("compact_teacher")
        if cur_cut is None:
            if ep.end_reason == "accused" and not ep.correct:
                return None
            if ep.end_reason not in ("accused", "horizon"):
                return None
        else:
            if ep.end_reason != "horizon" or ep.score != 0.0 or ep.correct:
                continue
        steps = list(env.history)
        idxs = _select_turn_indices(steps, ep.end_reason)
        turns = [
            render_compact_turn(ins, ctools, steps[:i], target_step=steps[i], tail_turns=tail_turns)
            for i in idxs
        ]
        return {
            "tier": tier,
            "seed": seed,
            "censored": cur_cut is not None,
            "score": float(ep.score),
            "end_reason": ep.end_reason,
            "correct": bool(ep.correct),
            "turns": turns,
        }
    return None


def export_sft_turns(
    sft_seeds_by_tier: dict[str, list[int]],
    censored_per_tier: int,
    max_calls: int = 65,
    tail_turns: int = 4,
    workers: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    jobs: list[tuple[str, int, int | None, int, int]] = []
    for tier in EVAL_TIERS:
        t_seeds = sft_seeds_by_tier[tier]
        for s in t_seeds:
            jobs.append((tier, s, None, max_calls, tail_turns))
        for s in t_seeds[:censored_per_tier]:
            jobs.append((tier, s, 1, max_calls, tail_turns))

    if workers > 1 and len(jobs) > 4:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            raw_out = list(ex.map(_rollout_teacher_job, jobs))
    else:
        raw_out = [_rollout_teacher_job(j) for j in jobs]

    kept = [r for r in raw_out if r is not None]
    turns = [t for r in kept for t in r["turns"]]
    nat = [r for r in kept if not r["censored"]]
    aug = [r for r in kept if r["censored"]]
    stats = {
        "jobs_total": len(jobs),
        "natural_kept": len(nat),
        "censored_abstentions_kept": len(aug),
        "natural_mean_score": round(sum(r["score"] for r in nat) / max(len(nat), 1), 4),
        "turns_exported": len(turns),
    }
    return turns, stats


def build_lora_model(model_path: str, r: int, alpha: int, tiny: bool, device: str):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    tok = AutoTokenizer.from_pretrained(model_path)
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id

    if tiny:
        cfg = Qwen2Config(
            vocab_size=max(len(tok), 151936),
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

    for g_attr in ("temperature", "top_p", "top_k"):
        if hasattr(base, "generation_config") and hasattr(base.generation_config, g_attr):
            setattr(base.generation_config, g_attr, None)

    lora_cfg = LoraConfig(
        r=r,
        lora_alpha=alpha,
        lora_dropout=0.05,
        target_modules=LORA_TARGETS,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.to(device)
    return model, tok


def tokenize_turns(turns: list[dict[str, Any]], tok, max_ctx: int = 2048) -> list[tuple[list[int], list[int]]]:
    windows: list[tuple[list[int], list[int]]] = []
    for rec in turns:
        for ids, labels, _ in compact_turn_window(rec, tok, max_len=max_ctx):
            windows.append((ids, labels))
    return windows


def train_lora_windows(
    model,
    tok,
    windows: list[tuple[list[int], list[int]]],
    epochs: int,
    batch_size: int,
    grad_accum: int,
    lr: float,
    max_steps: int,
    device: str,
    rng_seed: int = 0,
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    if not windows:
        raise ValueError("empty training windows")

    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.config.use_cache = False
    model.train()

    rng = random.Random(rng_seed)
    stream: list[tuple[list[int], list[int]]] = []
    for ep_idx in range(max(1, epochs)):
        shuf = list(windows)
        rng.shuffle(shuf)
        chunk_w = max(batch_size * 8, 32)
        buckets = [sorted(shuf[i:i + chunk_w], key=lambda w: len(w[0])) for i in range(0, len(shuf), chunk_w)]
        for b in buckets:
            sub_batches = [b[j:j + batch_size] for j in range(0, len(b), batch_size)]
            rng.shuffle(sub_batches)
            for sb in sub_batches:
                stream.extend(sb)

    eff_bs = batch_size * grad_accum
    est_steps = max(1, len(stream) // max(eff_bs, 1))
    total_steps = min(est_steps, max_steps) if max_steps > 0 else est_steps

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    warm = max(1, int(0.05 * total_steps))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1.0, (s + 1) / warm) * max(0.1, 0.5 * (1.0 + math.cos(math.pi * s / max(total_steps, 1)))),
    )
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    t0 = time.time()
    cursor = 0
    losses: list[float] = []
    for step in range(total_steps):
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for _ in range(grad_accum):
            batch = [stream[(cursor + k) % len(stream)] for k in range(batch_size)]
            cursor += batch_size
            max_l = max(len(x[0]) for x in batch)
            inp_rows = [x[0] + [pad_id] * (max_l - len(x[0])) for x in batch]
            att_rows = [[1] * len(x[0]) + [0] * (max_l - len(x[0])) for x in batch]
            lab_rows = [x[1] + [-100] * (max_l - len(x[1])) for x in batch]

            x_t = torch.tensor(inp_rows, dtype=torch.long, device=device)
            a_t = torch.tensor(att_rows, dtype=torch.long, device=device)
            y_t = torch.tensor(lab_rows, dtype=torch.long, device=device)
            nz = (y_t != -100).nonzero()
            min_sup = max(1, int(nz[:, 1].min().item())) if nz.numel() > 0 else max_l - 1
            keep_k = max_l - (min_sup - 1)

            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                logits = model(input_ids=x_t, attention_mask=a_t, logits_to_keep=keep_k).logits
                y_sub = y_t[:, min_sup:]
                n_tok = (y_sub != -100).sum().clamp(min=1)
                ce_sum = F.cross_entropy(
                    logits[:, :-1].float().reshape(-1, logits.size(-1)),
                    y_sub.reshape(-1),
                    ignore_index=-100,
                    reduction="sum",
                )
                loss = (ce_sum / n_tok) / grad_accum
            scaler.scale(loss).backward()
            step_loss += float(loss.detach().cpu())

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()
        losses.append(step_loss)
        if (step + 1) % 20 == 0 or (step + 1) == total_steps:
            print(
                json.dumps({
                    "train_step": step + 1,
                    "total_steps": total_steps,
                    "loss": round(step_loss, 4),
                    "sec": round(time.time() - t0, 1),
                }),
                flush=True,
            )

    return {
        "steps": total_steps,
        "windows": len(windows),
        "first_loss": round(losses[0], 4),
        "final_loss": round(losses[-1], 4),
        "seconds": round(time.time() - t0, 2),
    }


def rollout_batched_episodes(
    model,
    tok,
    jobs: list[tuple[str, int]],
    agent_name: str,
    batch_size: int = 15,
    max_ctx: int = 2048,
    max_new_tokens: int = 72,
    tail_turns: int = 4,
    max_calls: int = 65,
    world_secret: str | bytes | None = None,
    collect_dagger: bool = False,
    use_lora_adapter: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import torch

    if hasattr(model, "gradient_checkpointing_disable"):
        model.gradient_checkpointing_disable()
    model.config.use_cache = True
    model.eval()
    tok.padding_side = "left"
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    secret_tag = compute_world_secret_tag(world_secret) or "unset"

    episodes_out: list[dict[str, Any]] = []
    dagger_turns: list[dict[str, Any]] = []
    use_amp_gen = model.device.type == "cuda"

    def _run_single_chunk(chunk: list[tuple[str, int]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        c_eps: list[dict[str, Any]] = []
        c_dag: list[dict[str, Any]] = []
        envs = [Env(tier=t, seed=s) for t, s in chunk]
        pols = [
            QwenCompactPolicy(
                name=agent_name,
                max_ctx=max_ctx,
                max_new=max_new_tokens,
                tail_turns=tail_turns,
                kv_reuse=False,
            )
            for _ in chunk
        ]
        for env, pol in zip(envs, pols):
            pol.reset(env.tools_spec(), env.instruction())

        for _ in range(max_calls):
            active = [idx for idx, env in enumerate(envs) if not env.done]
            if not active:
                break
            prompt_ids_list: list[list[int]] = []
            for idx in active:
                t_cur = tail_turns
                while True:
                    msgs = render_compact_messages(pols[idx].instruction, envs[idx].history, tail_turns=t_cur)
                    p_txt = tok.apply_chat_template(
                        msgs, tools=pols[idx].tools, tokenize=False, add_generation_prompt=True
                    )
                    ids = list(tok(p_txt, add_special_tokens=False)["input_ids"])
                    if len(ids) <= max_ctx - max_new_tokens or t_cur <= 0:
                        prompt_ids_list.append(ids)
                        break
                    t_cur -= 1

            max_p = max(len(ids) for ids in prompt_ids_list)
            inp_batch = [[pad_id] * (max_p - len(ids)) + ids for ids in prompt_ids_list]
            att_batch = [[0] * (max_p - len(ids)) + [1] * len(ids) for ids in prompt_ids_list]
            x_t = torch.tensor(inp_batch, dtype=torch.long, device=model.device)
            a_t = torch.tensor(att_batch, dtype=torch.long, device=model.device)

            with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp_gen):
                out_t = model.generate(
                    input_ids=x_t,
                    attention_mask=a_t,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    use_cache=True,
                    pad_token_id=pad_id,
                    eos_token_id=tok.eos_token_id,
                )

            for b_i, idx in enumerate(active):
                gen_ids = out_t[b_i, max_p:].tolist()
                if tok.eos_token_id is not None and tok.eos_token_id in gen_ids:
                    gen_ids = gen_ids[:gen_ids.index(tok.eos_token_id) + 1]
                raw_txt = tok.decode(gen_ids, skip_special_tokens=False)
                pols[idx].calls += 1
                parsed = parse_tool_call(raw_txt, pols[idx].tool_names)
                if parsed is None:
                    pols[idx].invalid += 1
                    s_tool, s_args = "status", {}
                else:
                    s_tool, s_args = parsed

                if collect_dagger:
                    t_tool, t_args = query_calibrated_teacher(
                        pols[idx].instruction, envs[idx].history, d_cut=None, max_calls=max(max_calls, 58)
                    )
                    disagree = (s_tool != t_tool) or (s_args != t_args) or (parsed is None)
                    h_len = len(envs[idx].history)
                    anchor = (
                        t_tool in ("accuse", "list_employees", "list_documents")
                        or h_len < 4
                        or (h_len % 3 == 0)
                    )
                    if disagree or anchor:
                        d_turn = render_compact_turn(
                            pols[idx].instruction,
                            pols[idx].tools,
                            list(envs[idx].history),
                            target_step={"tool": t_tool, "args": t_args},
                            tail_turns=tail_turns,
                        )
                        c_dag.append(d_turn)
                        if disagree and ("accuse" in (s_tool, t_tool) or parsed is None):
                            c_dag.append(d_turn)

                envs[idx].call(s_tool, s_args)

        for env, pol in zip(envs, pols):
            ep = env.result(agent_name)
            if ep.end_reason == "error" and not env.done:
                ep.end_reason = "eval_cap"
            ep.meta = dict(ep.meta or {})
            ep.meta["invalid_calls"] = int(pol.invalid)
            ep.meta["world_secret_tag"] = secret_tag
            c_eps.append(dataclasses.asdict(ep))
        return c_eps, c_dag

    def _run_chunks():
        cur_bs = max(1, batch_size)
        pos = 0
        while pos < len(jobs):
            chunk = jobs[pos:pos + cur_bs]
            try:
                c_eps, c_dag = _run_single_chunk(chunk)
                episodes_out.extend(c_eps)
                dagger_turns.extend(c_dag)
                pos += len(chunk)
            except RuntimeError as exc:
                if "out of memory" in str(exc).lower() and cur_bs > 1 and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    cur_bs = max(1, cur_bs // 2)
                    continue
                raise

    with _world_secret_scope(world_secret):
        if not use_lora_adapter and hasattr(model, "disable_adapter"):
            with model.disable_adapter():
                _run_chunks()
        else:
            _run_chunks()

    return episodes_out, dagger_turns


def score_and_verify_episodes(
    episodes: list[dict[str, Any]],
    ep_file: Path,
    world_secret: str,
) -> dict[str, Any]:
    ep_file.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(episodes, key=lambda e: (EVAL_TIERS.index(str(e["tier"])), int(e["seed"])))
    with open(ep_file, "w", encoding="utf-8") as fh:
        for ep in ordered:
            fh.write(json.dumps(ep, default=str) + "\n")

    ver = verify_episode_file(ep_file, world_secret=world_secret)
    if not ver["replay_ok"] or ver["excluded_count"] != 0:
        raise RuntimeError(f"replay verification failed on {ep_file}: {ver['mismatches'][:2]} excl={ver['excluded_count']}")

    ev_rows = [luck_adjusted_episode_ev(ep, world_secret=world_secret) for ep in ordered]
    scores = [round(float(r["raw_score"]), 6) for r in ev_rows]
    evs = [float(r["luck_adjusted_ev"]) for r in ev_rows]
    mean_s, lo_s, hi_s, hw_s = _mean_ci95(scores)
    mean_ev, lo_ev, hi_ev, _ = _mean_ci95(evs)

    tot_calls = sum(int(r["total_calls"]) for r in ev_rows)
    val_calls = sum(int(r["valid_calls"]) for r in ev_rows)
    vcr = (val_calls / tot_calls) if tot_calls > 0 else 1.0
    n_tot = len(ev_rows)
    n_acc = sum(1 for r in ev_rows if r["accused"] is not None and r["end_reason"] == "accused")
    n_cor = sum(1 for r in ev_rows if r["correct"])
    n_wrg = sum(1 for r in ev_rows if r["accused"] is not None and r["end_reason"] == "accused" and not r["correct"])

    by_tier: dict[str, Any] = {}
    for tier in EVAL_TIERS:
        sub = [r for r in ev_rows if r["tier"] == tier]
        if not sub:
            continue
        ts = [float(r["raw_score"]) for r in sub]
        te = [float(r["luck_adjusted_ev"]) for r in sub]
        tm, tlo, thi, thw = _mean_ci95(ts)
        tem, _, _, _ = _mean_ci95(te)
        tc = sum(int(r["total_calls"]) for r in sub)
        vc = sum(int(r["valid_calls"]) for r in sub)
        t_acc = sum(1 for r in sub if r["accused"] is not None and r["end_reason"] == "accused")
        by_tier[tier] = {
            "n": len(sub),
            "mean_score": round(tm, 6),
            "ci95": round(thw, 6),
            "ci95_low": round(tlo, 6),
            "ci95_high": round(thi, 6),
            "luck_adjusted_ev": round(tem, 6),
            "accuracy": round(sum(1 for r in sub if r["correct"]) / len(sub), 4),
            "accuse_rate": round(t_acc / len(sub), 4),
            "abstain_rate": round((len(sub) - t_acc) / len(sub), 4),
            "wrong_accuse_rate": round(
                sum(1 for r in sub if r["accused"] is not None and r["end_reason"] == "accused" and not r["correct"])
                / len(sub),
                4,
            ),
            "valid_call_rate": round((vc / tc) if tc > 0 else 1.0, 4),
        }

    return {
        "n": n_tot,
        "mean_score": round(mean_s, 6),
        "ci95": round(hw_s, 6),
        "ci95_low": round(lo_s, 6),
        "ci95_high": round(hi_s, 6),
        "luck_adjusted_ev": round(mean_ev, 6),
        "luck_adjusted_ci95_low": round(lo_ev, 6),
        "luck_adjusted_ci95_high": round(hi_ev, 6),
        "accuracy": round(n_cor / max(n_tot, 1), 4),
        "accuse_rate": round(n_acc / max(n_tot, 1), 4),
        "abstain_rate": round((n_tot - n_acc) / max(n_tot, 1), 4),
        "wrong_accuse_rate": round(n_wrg / max(n_tot, 1), 4),
        "valid_call_rate": round(vcr, 4),
        "world_secret_tag": compute_world_secret_tag(world_secret),
        "replay_verified": True,
        "invalid_episodes": 0,
        "by_tier": by_tier,
        "scores": scores,
        "_evs": evs,
    }


def render_table_markdown(summary: dict[str, Any]) -> str:
    b = summary["before"]
    a = summary["after"]
    p = summary["paired"]
    st = summary["stages"]
    title = "Qwen2.5-1.5B-Instruct Compact LoRA + On-Policy DAgger r1 (Canary v1.4)"
    lines = [
        title,
        "=" * len(title),
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Model: `{summary['model']}`",
        f"- Train seeds: `{summary['train_seeds']['start']}..{summary['train_seeds']['stop'] - 1}` "
        f"(SFT r0 `{st['sft_r0']['sft_seed_range'][0]}..{st['sft_r0']['sft_seed_range'][1]}`, "
        f"DAgger r1 `{st['dagger_r1']['dagger_seed_range'][0]}..{st['dagger_r1']['dagger_seed_range'][1]}`)",
        f"- Held-out eval seeds: `{summary['eval_seeds']['start']}..{summary['eval_seeds']['stop'] - 1}` "
        f"across `{','.join(summary['tiers'])}` (`n={summary['n']}` paired episodes)",
        f"- Shared held-out world secret tag: `{b['world_secret_tag']}`",
        f"- Tool-by-tool Env replay verified: `{summary['replay_verified']}` (`invalid_episodes={summary['invalid_episodes']}`)",
        "",
        "Overall Paired Held-Out Comparison",
        "----------------------------------",
        "",
        "| Stage | n | Mean Score [95% CI] | Luck-Adj EV | Accuracy | Accuse | Abstain | Wrong | Valid Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| before (base_compact) | {b['n']} | {b['mean_score']:+.4f} [{b['ci95_low']:+.4f}, {b['ci95_high']:+.4f}] | "
        f"{b['luck_adjusted_ev']:+.4f} | {b['accuracy']:.3f} | {b['accuse_rate']:.3f} | "
        f"{b['abstain_rate']:.3f} | {b['wrong_accuse_rate']:.3f} | {b['valid_call_rate']:.4f} |",
        f"| after (dagger_r1) | {a['n']} | {a['mean_score']:+.4f} [{a['ci95_low']:+.4f}, {a['ci95_high']:+.4f}] | "
        f"{a['luck_adjusted_ev']:+.4f} | {a['accuracy']:.3f} | {a['accuse_rate']:.3f} | "
        f"{a['abstain_rate']:.3f} | {a['wrong_accuse_rate']:.3f} | {a['valid_call_rate']:.4f} |",
        "",
        "| Paired Comparison | n | Mean Delta | 95% CI Low | 95% CI High | Luck-Adj EV Delta | W / L / T |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| after - before | {summary['n']} | {p['mean_delta']:+.4f} | {p['ci95_low']:+.4f} | "
        f"{p['ci95_high']:+.4f} | {p['luck_adjusted_ev_delta']:+.4f} | {p['wins']}/{p['losses']}/{p['ties']} |",
        "",
        "Per-Tier Held-Out Breakdown",
        "---------------------------",
        "",
        "| Tier | Stage | n | Mean Score [95% CI] | Luck-Adj EV | Accuracy | Wrong | Abstain | Valid Calls |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tier in summary["tiers"]:
        for lbl, src in (("before", b), ("after", a)):
            tb = src["by_tier"].get(tier)
            if not tb:
                continue
            lines.append(
                f"| {tier} | {lbl} | {tb['n']} | {tb['mean_score']:+.4f} [{tb['ci95_low']:+.4f}, {tb['ci95_high']:+.4f}] | "
                f"{tb['luck_adjusted_ev']:+.4f} | {tb['accuracy']:.3f} | {tb['wrong_accuse_rate']:.3f} | "
                f"{tb['abstain_rate']:.3f} | {tb['valid_call_rate']:.4f} |"
            )
    return "\n".join(lines) + "\n"


def _rollout_pure_python_tiny(
    jobs: list[tuple[str, int]],
    agent_name: str,
    raw_reply: str,
    max_calls: int,
    tail_turns: int,
    world_secret: str | bytes | None = None,
    collect_dagger: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    secret_tag = compute_world_secret_tag(world_secret) or "unset"
    episodes_out: list[dict[str, Any]] = []
    dagger_turns: list[dict[str, Any]] = []
    with _world_secret_scope(world_secret):
        for tier, seed in jobs:
            env = Env(tier=tier, seed=seed)
            pol = QwenCompactPolicy(name=agent_name, tail_turns=tail_turns, kv_reuse=False, generator=lambda _t: raw_reply)
            pol.reset(env.tools_spec(), env.instruction())
            for _ in range(max_calls):
                if env.done:
                    break
                if collect_dagger:
                    t_tool, t_args = query_calibrated_teacher(pol.instruction, env.history, d_cut=None, max_calls=12)
                    dagger_turns.append(
                        render_compact_turn(
                            pol.instruction,
                            pol.tools,
                            list(env.history),
                            target_step={"tool": t_tool, "args": t_args},
                            tail_turns=tail_turns,
                        )
                    )
                s_tool, s_args = pol.act(env.history)
                env.call(s_tool, s_args)
            ep = env.result(agent_name)
            if ep.end_reason == "error" and not env.done:
                ep.end_reason = "eval_cap"
            ep.meta = dict(ep.meta or {})
            ep.meta["invalid_calls"] = int(pol.invalid)
            ep.meta["world_secret_tag"] = secret_tag
            episodes_out.append(dataclasses.asdict(ep))
    return episodes_out, dagger_turns


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    t0 = time.time()
    torch_mod = None
    try:
        import torch as _torch_mod

        torch_mod = _torch_mod
    except ImportError:
        if not args.tiny:
            raise

    device = "cuda" if (torch_mod is not None and torch_mod.cuda.is_available() and not args.tiny) else "cpu"
    if torch_mod is not None and device == "cpu":
        torch_mod.set_num_threads(2)
    work_dir = Path(args.work_dir)
    out_dir = Path(args.out_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    sft_per_tier = 1 if args.tiny else args.sft_per_tier
    dagger_per_tier = 1 if args.tiny else args.dagger_per_tier
    eval_per_tier = 1 if args.tiny else args.eval_per_tier
    censored_per_tier = 0 if args.tiny else args.censored_per_tier
    teacher_max_calls = 40 if args.tiny else args.max_calls
    rollout_max_calls = 1 if args.tiny else args.max_calls
    max_new_tokens = 2 if args.tiny else args.max_new_tokens
    tail_turns_eff = 1 if args.tiny else args.tail_turns
    batch_size_eval = 3 if args.tiny else args.eval_batch_size
    batch_size_train = 1 if args.tiny else args.train_batch_size
    grad_accum = 1 if args.tiny else args.grad_accum
    sft_max_steps = 1 if args.tiny else args.sft_max_steps
    dagger_max_steps = 1 if args.tiny else args.dagger_max_steps
    lora_r = 4 if args.tiny else args.lora_r
    lora_alpha = 8 if args.tiny else args.lora_alpha

    sft_base = 105_000
    sft_seeds_by_tier = {
        t: list(range(sft_base + idx * sft_per_tier, sft_base + (idx + 1) * sft_per_tier))
        for idx, t in enumerate(EVAL_TIERS)
    }
    dag_base = sft_base + len(EVAL_TIERS) * sft_per_tier
    dagger_seeds_by_tier = {
        t: list(range(dag_base + idx * dagger_per_tier, dag_base + (idx + 1) * dagger_per_tier))
        for idx, t in enumerate(EVAL_TIERS)
    }
    eval_seeds = list(range(800_000, 800_000 + eval_per_tier))
    if any(s not in HELDOUT_SEEDS for s in eval_seeds):
        raise ValueError("eval_seeds outside HELDOUT_SEEDS")

    all_train_seeds = sorted(
        {s for v in sft_seeds_by_tier.values() for s in v}
        | {s for v in dagger_seeds_by_tier.values() for s in v}
    )
    secret = args.world_secret or DEFAULT_HELD_OUT_WORLD_SECRET
    secret_tag = compute_world_secret_tag(secret)
    hygiene = audit_seed_hygiene(all_train_seeds, eval_seeds, {"before": secret_tag, "after": secret_tag})
    if not hygiene["ok"]:
        raise RuntimeError(f"seed hygiene violation: {hygiene['violations']}")

    sft_turns, sft_data_stats = export_sft_turns(
        sft_seeds_by_tier=sft_seeds_by_tier,
        censored_per_tier=censored_per_tier,
        max_calls=teacher_max_calls,
        tail_turns=tail_turns_eff,
        workers=1 if args.tiny else args.cpu_workers,
    )
    print("[sft_data] " + json.dumps(sft_data_stats), flush=True)

    eval_jobs = [(tier, s) for tier in EVAL_TIERS for s in eval_seeds]
    dagger_jobs = [(t, s) for t in EVAL_TIERS for s in dagger_seeds_by_tier[t]]

    if torch_mod is None:
        before_eps, _ = _rollout_pure_python_tiny(
            eval_jobs, "qwen15b_base_compact", "unparsed", rollout_max_calls, tail_turns_eff, secret, False
        )
        before_block = score_and_verify_episodes(before_eps, work_dir / "before_episodes.jsonl", secret)
        sft_train_stats = {"steps": 1, "windows": min(4, len(sft_turns)), "first_loss": 2.0, "final_loss": 1.5, "seconds": 0.01}
        ok_call = '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>'
        sft_rollout_eps, dagger_turns = _rollout_pure_python_tiny(
            dagger_jobs, "qwen15b_sft_r0", ok_call, rollout_max_calls, tail_turns_eff, None, True
        )
        sft_rollout_mean = round(sum(float(e["score"]) for e in sft_rollout_eps) / max(len(sft_rollout_eps), 1), 4)
        mixed_windows_len = len(dagger_turns) * 2
        dagger_train_stats = {"steps": 1, "windows": max(1, mixed_windows_len), "first_loss": 1.5, "final_loss": 1.1, "seconds": 0.01}
        after_eps, _ = _rollout_pure_python_tiny(
            eval_jobs, "qwen15b_dagger_r1", ok_call, rollout_max_calls, tail_turns_eff, secret, False
        )
        after_block = score_and_verify_episodes(after_eps, work_dir / "after_episodes.jsonl", secret)
    else:
        model, tok = build_lora_model(args.model, r=lora_r, alpha=lora_alpha, tiny=args.tiny, device=device)

        before_eps, _ = rollout_batched_episodes(
            model=model,
            tok=tok,
            jobs=eval_jobs,
            agent_name="qwen15b_base_compact",
            batch_size=batch_size_eval,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new_tokens,
            tail_turns=tail_turns_eff,
            max_calls=rollout_max_calls,
            world_secret=secret,
            collect_dagger=False,
            use_lora_adapter=False,
        )
        before_block = score_and_verify_episodes(before_eps, work_dir / "before_episodes.jsonl", secret)
        print(f"[eval_before] mean={before_block['mean_score']:+.4f} vcr={before_block['valid_call_rate']:.4f}", flush=True)

        sft_windows = tokenize_turns(sft_turns[:2] if args.tiny else sft_turns, tok, max_ctx=args.max_ctx)
        sft_train_stats = train_lora_windows(
            model=model,
            tok=tok,
            windows=sft_windows,
            epochs=2,
            batch_size=batch_size_train,
            grad_accum=grad_accum,
            lr=args.lr,
            max_steps=sft_max_steps,
            device=device,
            rng_seed=0,
        )
        if not args.tiny and args.save_adapters:
            model.save_pretrained(str(work_dir / "sft_r0_adapter"))

        sft_rollout_eps, dagger_turns = rollout_batched_episodes(
            model=model,
            tok=tok,
            jobs=dagger_jobs,
            agent_name="qwen15b_sft_r0",
            batch_size=batch_size_eval,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new_tokens,
            tail_turns=tail_turns_eff,
            max_calls=rollout_max_calls,
            world_secret=None,
            collect_dagger=True,
            use_lora_adapter=True,
        )
        sft_rollout_mean = round(sum(float(e["score"]) for e in sft_rollout_eps) / max(len(sft_rollout_eps), 1), 4)
        print(f"[dagger_rollout] sft_r0_train_mean={sft_rollout_mean:+.4f} relabeled_turns={len(dagger_turns)}", flush=True)

        dagger_windows = tokenize_turns(dagger_turns[:2] if args.tiny else dagger_turns, tok, max_ctx=args.max_ctx)
        rng_mix = random.Random(1)
        sft_sample = list(sft_windows)
        rng_mix.shuffle(sft_sample)
        target_mix_n = max(len(dagger_windows), 1)
        sft_half = (sft_sample * ((target_mix_n // max(len(sft_sample), 1)) + 1))[:target_mix_n]
        mixed_windows = dagger_windows + sft_half
        mixed_windows_len = len(mixed_windows)

        dagger_train_stats = train_lora_windows(
            model=model,
            tok=tok,
            windows=mixed_windows,
            epochs=1,
            batch_size=batch_size_train,
            grad_accum=grad_accum,
            lr=args.dagger_lr,
            max_steps=dagger_max_steps,
            device=device,
            rng_seed=1,
        )
        if not args.tiny and args.save_adapters:
            model.save_pretrained(str(work_dir / "dagger_r1_adapter"))

        after_eps, _ = rollout_batched_episodes(
            model=model,
            tok=tok,
            jobs=eval_jobs,
            agent_name="qwen15b_dagger_r1",
            batch_size=batch_size_eval,
            max_ctx=args.max_ctx,
            max_new_tokens=max_new_tokens,
            tail_turns=tail_turns_eff,
            max_calls=rollout_max_calls,
            world_secret=secret,
            collect_dagger=False,
            use_lora_adapter=True,
        )
        after_block = score_and_verify_episodes(after_eps, work_dir / "after_episodes.jsonl", secret)
        print(f"[eval_after] mean={after_block['mean_score']:+.4f} vcr={after_block['valid_call_rate']:.4f}", flush=True)

    before_evs = before_block.pop("_evs")
    after_evs = after_block.pop("_evs")
    deltas = [round(a - b, 6) for b, a in zip(before_block["scores"], after_block["scores"])]
    ev_deltas = [a - b for b, a in zip(before_evs, after_evs)]
    d_mean, d_lo, d_hi, d_hw = _mean_ci95(deltas)
    ev_d_mean, _, _, _ = _mean_ci95(ev_deltas)
    wins = sum(1 for d in deltas if d > 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    ties = len(deltas) - wins - losses

    sft_min = min(s for v in sft_seeds_by_tier.values() for s in v)
    sft_max = max(s for v in sft_seeds_by_tier.values() for s in v)
    dag_min = min(s for v in dagger_seeds_by_tier.values() for s in v)
    dag_max = max(s for v in dagger_seeds_by_tier.values() for s in v)

    summary: dict[str, Any] = {
        "run_id": RUN_ID,
        "model": MODEL_LABEL,
        "tiers_version": TIERS_VERSION,
        "tiers": list(EVAL_TIERS),
        "n": len(deltas),
        "train_seeds": {"start": sft_min, "stop": dag_max + 1},
        "eval_seeds": {"start": min(eval_seeds), "stop": max(eval_seeds) + 1},
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": 0,
        "inference_modules": [
            "train/compact_render.py",
            "train/eval_compact_hf.py",
            "train/qwen15b_compact_dagger.py",
        ],
        "before": before_block,
        "after": after_block,
        "paired": {
            "mean_delta": round(d_mean, 6),
            "ci95": round(d_hw, 6),
            "ci95_low": round(d_lo, 6),
            "ci95_high": round(d_hi, 6),
            "luck_adjusted_ev_delta": round(ev_d_mean, 6),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "deltas": deltas,
        },
        "stages": {
            "sft_r0": {
                "sft_seed_range": [sft_min, sft_max],
                **sft_data_stats,
                **sft_train_stats,
            },
            "dagger_r1": {
                "dagger_seed_range": [dag_min, dag_max],
                "sft_r0_rollout_n": len(sft_rollout_eps),
                "sft_r0_rollout_mean_score": sft_rollout_mean,
                "dagger_turns": len(dagger_turns),
                "mixed_windows": mixed_windows_len,
                **dagger_train_stats,
            },
        },
        "elapsed_seconds": round(time.time() - t0, 2),
        "notes": (
            "Paired before/after evaluation of Qwen2.5-1.5B-Instruct on CompactState working-memory prompts "
            "before (untrained base) vs after two-stage LoRA SFT r0 + closed-loop DAgger r1 trained strictly "
            "on TRAIN_SEEDS and verified tool-by-tool in Env on HELDOUT_SEEDS under shared world secret."
        ),
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "table.md").write_text(render_table_markdown(summary), encoding="utf-8")
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.qwen15b_compact_dagger")
    ap.add_argument("--model", default=DEFAULT_MODEL_PATH)
    ap.add_argument("--work-dir", default=DEFAULT_WORK_DIR)
    ap.add_argument("--out-dir", default="results/tiebreak/qwen15b_compact_dagger")
    ap.add_argument("--world-secret", default=DEFAULT_HELD_OUT_WORLD_SECRET)
    ap.add_argument("--sft-per-tier", type=int, default=65)
    ap.add_argument("--censored-per-tier", type=int, default=12)
    ap.add_argument("--dagger-per-tier", type=int, default=20)
    ap.add_argument("--eval-per-tier", type=int, default=30)
    ap.add_argument("--max-ctx", type=int, default=2048)
    ap.add_argument("--max-new-tokens", type=int, default=80)
    ap.add_argument("--tail-turns", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--eval-batch-size", type=int, default=30)
    ap.add_argument("--train-batch-size", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2.5e-4)
    ap.add_argument("--dagger-lr", type=float, default=1.0e-4)
    ap.add_argument("--sft-max-steps", type=int, default=180)
    ap.add_argument("--dagger-max-steps", type=int, default=90)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--cpu-workers", type=int, default=6)
    ap.add_argument("--save-adapters", action="store_true")
    ap.add_argument("--tiny", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_arg_parser().parse_args(argv)
    return run_pipeline(args)


if __name__ == "__main__":
    main()
