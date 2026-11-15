"""X2: DAgger round 1 for the small investigator (v3-4k s0 -> DAgger SFT).

Diagnosis (v3-4k s0): GRPO states were the last steps of SOLVER trajectories, where the solver had already gathered
the evidence; the model learned WHOM from evidence (forced-accuse .19 -> .89 on training states) but held-out
precision stayed ~.19 because in its OWN episodes the evidence is never gathered. DAgger fixes the state
distribution: roll out the student, label every state it reaches with the reference solver's action computed from
the SAME agent-visible history, and SFT on (student state -> solver action).

  expert_action(instruction, tools_spec, history)  the solver's next call from any history (stateless; below)
  rollout   student episodes on TRAIN seeds with vLLM (same render/truncation/parse as eval_hf)       [GPU]
  relabel   replay each episode into a fresh Env (determinism check) + expert label at every step     [CPU]
  sft       LoRA SFT from the student adapter; loss only on the expert's assistant turn                [GPU]
  selftest  expert_action == the solver's own next call along solver trajectories                     [CPU]

Seeds: TRAIN only (rules.TRAIN_SEEDS, base 150000 + offset); held-out and judge seeds asserted untouched.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import time
from collections import Counter
from pathlib import Path

SEED_BASE = 150_000
DAILY = ("list_documents", "check_leak_feed")


def _check_seed(seed: int) -> None:
    from canary import rules
    assert seed in rules.TRAIN_SEEDS, f"seed {seed} not in TRAIN_SEEDS"
    assert seed not in rules.HELDOUT_SEEDS and seed not in rules.JUDGE_SEEDS


def _as_step(s):
    from canary.types import Step
    return s if isinstance(s, Step) else Step(**{k: s[k] for k in ("t", "day", "tool", "args", "result")})


# ---------------------------------------------------------------- expert: solver action from any history
def expert_action(instruction: str, tools_spec: list, history: list, roster=None) -> tuple[str, dict]:
    """The reference solver's next call given only the agent-visible history (which may come from another policy).

    SolverPolicy is a phase machine whose queue is built from its OWN past calls, so querying it on a foreign
    history would replay a stale queue. Instead we rebuild its daily loop from the history:
      day start (after advance_day)      -> status
      day queue (computed from the belief at the day's first status, exactly as the solver does):
        list_documents, check_leak_feed, [decoy search_messages], [read_access_logs(yesterday)]
        -> the first item not yet done today
      decide (belief from everything seen, minus today's own canaries) -> accuse best if the solver would
      else today's canary plan minus canaries already planted today -> status -> advance_day
    selftest checks this equals the solver's own call at every step of solver episodes.
    roster: a list_employees Step (static public roster). If the student never listed employees, the expert asks
    for it at the first state only and otherwise acts as if it had the roster (else every later label would be
    list_employees).
    """
    from canary.solver import SolverPolicy
    from canary.solver.policy import accuse_value
    hist = [_as_step(s) for s in history]
    if not any(s.tool == "list_employees" and (s.result or {}).get("ok", True) for s in hist):
        if roster is None or not hist:
            return "list_employees", {}
        hist = [roster] + hist
    if hist[-1].tool == "advance_day":
        return "status", {}
    ia = max((i for i, s in enumerate(hist) if s.tool == "advance_day"), default=-1)
    seg = hist[ia + 1:]
    if not any(s.tool == "status" for s in seg):
        return "status", {}
    i_status = ia + 1 + next(i for i, s in enumerate(seg) if s.tool == "status")
    sol = SolverPolicy()
    sol.reset(tools_spec, instruction)
    sol.phase = "day"
    for s in hist[:i_status + 1]:
        sol._ingest(s)
    o = sol.obs
    today = o.today
    # the day queue as the solver builds it right after the day's first status
    q = [("list_documents", {"day_from": max(1, today - 3), "day_to": today}), ("check_leak_feed", {})]
    q += sol.decoy_queries()
    if sol.read_logs and sol.behaviour_temper > 0 and today > 1:
        q.append(("read_access_logs", {"day_from": today - 1, "day_to": today - 1}))
    done = seg[i_status - ia:]

    def did(tool, args):
        if tool in DAILY:
            return any(s.tool == tool for s in done)
        return any(s.tool == tool and s.args == args for s in done)
    for tool, args in q:
        if not did(tool, args):
            return tool, args
    planted = [s for s in done if s.tool == "plant_canary"]
    for s in hist[i_status + 1:]:
        if s.tool != "plant_canary":
            sol._ingest(s)
    post = sol.belief()
    best = max(post, key=post.get)
    thr = sol.threshold if sol.threshold is not None else sol.default_threshold()
    last = o.today >= sol.P.n_days
    if accuse_value(post[best], sol.expected_true_V(), sol.P) > 0 and (post[best] >= thr or last):
        return "accuse", {"employee": best}
    if not planted or len(planted) < len(sol.plan_canaries(post)):
        plan = sol.plan_canaries(post)
        if len(planted) < len(plan):
            i = len(planted)
            return "plant_canary", {"doc_title": f"Board memo draft {today}" + (f" ({i + 1})" if i else ""),
                                    "assignment": plan[i]}
    if hist[-1].tool == "status" and hist[-1] is not hist[i_status]:
        return "advance_day", {}
    return "status", {}


def same_call(a, b) -> bool:
    return a[0] == b[0] and json.dumps(a[1], sort_keys=True) == json.dumps(b[1], sort_keys=True)


def selftest(a):
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver import SolverPolicy
    tot, bad = Counter(), Counter()
    for tier in a.tiers.split(","):
        for k in range(a.n):
            seed = SEED_BASE + 40_000 + k
            _check_seed(seed)
            env = Env(tier=tier, seed=seed)
            ep = run_episode(env, SolverPolicy())
            ins, spec = env.instruction(), env.tools_spec()
            for t, st in enumerate(ep.steps):
                e = expert_action(ins, spec, ep.steps[:t])
                tot[tier] += 1
                if not same_call(e, (st.tool, st.args)):
                    bad[tier] += 1
                    if bad[tier] <= 3:
                        print(f"[mismatch] {tier} {seed} t={t} solver={st.tool} {json.dumps(st.args)[:120]} "
                              f"expert={e[0]} {json.dumps(e[1])[:120]}", flush=True)
    print(json.dumps({"steps": dict(tot), "mismatch": dict(bad)}), flush=True)


# ---------------------------------------------------------------- rollout (vLLM, GPU)
class Prompter:
    """eval_hf.HFPolicy's render + sticky truncation (same token ids), without the HF model."""

    def __init__(self, tok, tools_spec, instruction, max_ctx, max_new):
        from train.eval_hf import HFPolicy
        self.p = HFPolicy(None, tok, "dagger", max_ctx=max_ctx, max_new=max_new, kv_reuse=False)
        self.p.reset(tools_spec, instruction)

    def ids(self, history):
        return self.p._prompt_ids(history)


_PTOK = None


def _ptok_init(path):
    global _PTOK
    from transformers import AutoTokenizer
    _PTOK = AutoTokenizer.from_pretrained(path)


def _prompt_job(job):
    """(spec, instruction, history, drop, max_ctx, max_new) -> (ids, drop); runs in a CPU worker."""
    spec, ins, hist, drop, max_ctx, max_new = job
    pr = Prompter(_PTOK, spec, ins, max_ctx, max_new)
    pr.p.drop = drop
    ids = pr.ids(hist)
    return ids, pr.p.drop


def rollout(a):
    from vllm import LLM, SamplingParams
    from transformers import AutoTokenizer
    from canary.env import Env
    from train.render import parse_tool_call
    tok = AutoTokenizer.from_pretrained(a.tokenizer)   # prompt ids: same template as eval_hf (checked by tokcheck)
    llm = LLM(model=a.model, max_model_len=a.max_ctx, dtype="float16", tokenizer=a.tokenizer,
              enable_prefix_caching=True, gpu_memory_utilization=a.gpu_mem, seed=0, max_num_seqs=a.batch)
    rng = random.Random(a.seed)
    tiers = a.tiers.split(",")
    jobs = []
    for i in range(a.episodes):
        seed = a.seed_base + i // len(tiers)
        _check_seed(seed)
        jobs.append((tiers[i % len(tiers)], seed, rng.random() < a.sample_frac))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = open(out / "rollouts.jsonl", "w")
    import multiprocessing as mp
    pool = mp.get_context("spawn").Pool(a.workers, initializer=_ptok_init, initargs=(a.tokenizer,))
    active, t0, nxt, n_done = [], time.time(), 0, 0
    while active or nxt < len(jobs):
        while len(active) < a.batch and nxt < len(jobs):
            tier, seed, samp = jobs[nxt]; nxt += 1
            env = Env(tier=tier, seed=seed)
            pr = Prompter(tok, env.tools_spec(), env.instruction(), a.max_ctx, a.max_new)
            active.append({"env": env, "pr": pr, "tier": tier, "seed": seed, "sample": samp, "invalid": 0, "n": 0,
                           "spec": env.tools_spec(), "ins": env.instruction(), "drop": 0})
        res = pool.map(_prompt_job, [(e["spec"], e["ins"], list(e["env"].history), e["drop"], a.max_ctx, a.max_new)
                                     for e in active], chunksize=2)
        for e, (_, d) in zip(active, res):
            e["drop"] = d
        prompts = [{"prompt_token_ids": ids} for ids, _ in res]
        sps = [SamplingParams(temperature=a.temperature if e["sample"] else 0.0, max_tokens=a.max_new,
                              seed=hash((e["seed"], e["n"])) & 0xFFFF) for e in active]
        outs = llm.generate(prompts, sps, use_tqdm=False)
        keep = []
        for e, o in zip(active, outs):
            call = parse_tool_call(o.outputs[0].text, e["pr"].p.tool_names)
            if call is None:
                e["invalid"] += 1
                call = ("status", {})
            e["env"].call(*call)
            e["n"] += 1
            if e["env"].done or e["n"] >= a.max_calls:
                res = e["env"].result("v3-4k-s0")
                end = res.end_reason if e["env"].done else "eval_cap"
                f.write(json.dumps({"tier": e["tier"], "seed": e["seed"], "sampled": e["sample"], "score": res.score,
                                    "correct": res.correct, "end_reason": end, "invalid": e["invalid"],
                                    "steps": [s.__dict__ if hasattr(s, "__dict__") else s for s in res.steps]},
                                   default=str) + "\n")
                f.flush()
                n_done += 1
                if n_done % 10 == 0:
                    print(f"[rollout] {n_done}/{len(jobs)} t={time.time() - t0:.0f}s", flush=True)
            else:
                keep.append(e)
        active = keep
    print(f"[rollout] done {n_done} in {time.time() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------- relabel (CPU)
def _relabel_episode(rec):
    from canary.env import Env
    try:
        _check_seed(rec["seed"])
        env = Env(tier=rec["tier"], seed=rec["seed"])
        ins, spec = env.instruction(), env.tools_spec()
        steps = [_as_step(s) for s in rec["steps"]]
        mism = 0
        for s in steps:                      # replay the student's actions into a fresh Env
            r = env.call(s.tool, s.args)
            got = env.history[-1].result
            if json.dumps(got, sort_keys=True, default=str) != json.dumps(s.result, sort_keys=True, default=str):
                mism += 1
        hist = list(env.history)
        renv = Env(tier=rec["tier"], seed=rec["seed"])
        renv.call("list_employees", {})
        roster = renv.history[-1]
        labels = []
        for t in range(len(hist)):
            try:
                e = expert_action(ins, spec, hist[:t], roster)
            except Exception as ex:  # off-distribution state the solver can't handle: no label
                labels.append({"t": t, "error": f"{type(ex).__name__}: {ex}"[:160]})
                continue
            labels.append({"t": t, "tool": e[0], "args": e[1],
                           "agree": same_call(e, (hist[t].tool, hist[t].args))})
        # the state after the last step (episode ended by horizon/cap/accuse): no label needed
        return {"tier": rec["tier"], "seed": rec["seed"], "replay_mismatch": mism, "labels": labels}
    except Exception as ex:
        return {"tier": rec["tier"], "seed": rec["seed"], "error": f"{type(ex).__name__}: {ex}"[:300], "labels": []}


def relabel(a):
    from concurrent.futures import ProcessPoolExecutor
    recs = [json.loads(l) for l in open(a.rollouts) if l.strip()]
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(_relabel_episode, recs, chunksize=1))
    with open(a.out, "w") as f:
        for r in res:
            f.write(json.dumps(r) + "\n")
    lab = [x for r in res for x in r["labels"]]
    ok = [x for x in lab if "tool" in x]
    print(json.dumps({"episodes": len(res), "states": len(lab), "labelled": len(ok),
                      "agree": round(sum(x["agree"] for x in ok) / max(1, len(ok)), 3),
                      "expert_tools": dict(Counter(x["tool"] for x in ok)),
                      "replay_mismatch_eps": sum(1 for r in res if r.get("replay_mismatch")),
                      "errors": sum(1 for r in res if "error" in r), "sec": round(time.time() - t0)}), flush=True)


# ---------------------------------------------------------------- SFT (GPU)
KEY_TOOLS = {"plant_canary", "accuse"}
_HDR: dict = {}


def _build_example(job):
    """(tier, seed, steps[:t], expert call, weight, max_ctx, max_new) -> (prompt ids, target ids, weight, tool).
    Prompt = eval_hf's exact render + truncation; target = the expert's assistant turn up to <|im_end|>."""
    from canary.env import Env
    from train.render import assistant_msg, render_messages
    tier, seed, steps, call, w, max_ctx, max_new = job
    tok = _PTOK
    if (tier, seed) not in _HDR:
        env = Env(tier=tier, seed=seed)
        _HDR[(tier, seed)] = (env.tools_spec(), env.instruction())
    spec, ins = _HDR[(tier, seed)]
    pr = Prompter(tok, spec, ins, max_ctx, max_new)
    hist = [_as_step(s) for s in steps]
    p_ids = pr.ids(hist)
    msgs = render_messages(ins, hist)
    cut = msgs[:2] + msgs[2 + 2 * pr.p.drop:]
    full = tok.apply_chat_template(cut + [assistant_msg(*call)], tools=pr.p.tools, tokenize=True)
    if hasattr(full, "keys"):
        full = full["input_ids"]
    full = list(full)
    assert full[:len(p_ids)] == p_ids, "chat template not prefix-stable"
    tgt = full[len(p_ids):]
    im_end = tok.convert_tokens_to_ids("<|im_end|>")
    if im_end in tgt:
        tgt = tgt[:tgt.index(im_end) + 1]
    return p_ids, tgt, w, call[0]


def select_states(recs, labs, a):
    """(rec, t, label, weight) examples. Up-weight plant_canary / accuse labels and the abstain decision (states
    where the student accused but the solver would not, or the student kept going where the solver accuses)."""
    rng = random.Random(a.seed)
    by = {(r["tier"], r["seed"]): r for r in recs}
    ex = []
    for L in labs:
        rec = by.get((L["tier"], L["seed"]))
        if rec is None:
            continue
        seen = Counter()
        for x in L["labels"]:
            if "tool" not in x:
                continue
            t = x["t"]
            stu = rec["steps"][t]["tool"]
            key = x["tool"] in KEY_TOOLS or stu == "accuse"
            if x["agree"] and not key and rng.random() > a.keep_agree:
                continue
            # the same non-key correction repeated all day (student keeps ignoring it): keep the first --max-repeat
            k = (rec["steps"][t]["day"], x["tool"], json.dumps(x["args"], sort_keys=True))
            seen[k] += 1
            if not key and seen[k] > a.max_repeat:
                continue
            w = a.key_weight if key else 1.0
            ex.append((rec, t, (x["tool"], x["args"]), w))
    rng.shuffle(ex)
    return ex[:a.max_examples] if a.max_examples else ex


def sft(a):
    from transformers import AutoTokenizer
    recs = [json.loads(l) for l in open(a.rollouts) if l.strip()]
    labs = [json.loads(l) for l in open(a.labels) if l.strip()]
    exs = select_states(recs, labs, a)
    tok = AutoTokenizer.from_pretrained(a.tokenizer or a.model)
    t0 = time.time()
    jobs = [(rec["tier"], rec["seed"], rec["steps"][:t], call, w, a.max_ctx, a.max_new) for rec, t, call, w in exs]
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(a.workers, initializer=_ptok_init, initargs=(a.tokenizer or a.model,)) as pool:
        data = pool.map(_build_example, jobs, chunksize=8)
    n_tok = sum(len(p) + len(c) for p, c, _, _ in data)
    print(f"[sft] examples={len(data)} tokens={n_tok} mean_len={n_tok / max(1, len(data)):.0f} "
          f"label_tools={dict(Counter(d[3] for d in data))} weighted_key={sum(1 for d in data if d[2] > 1)} "
          f"build_s={time.time() - t0:.0f}", flush=True)
    if a.build_only:
        return
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM
    dev = "cuda"
    base = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16, attn_implementation="sdpa").to(dev)
    base.config.use_cache = False
    base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base.enable_input_require_grads()
    model = PeftModel.from_pretrained(base, a.adapter, is_trainable=True)
    params = [p for p in model.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    steps = max(1, math.ceil(len(data) * a.epochs / a.grad_accum))
    warm = max(1, int(0.05 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.05, 1 - s / steps))
    wmean = sum(d[2] for d in data) / len(data)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    log = open(out / "train_log.jsonl", "a")
    deadline = time.time() + a.hours * 3600
    model.train()
    i, t_start = 0, time.time()
    order = list(range(len(data)))
    for step in range(steps):
        opt.zero_grad(set_to_none=True)
        tot = 0.0
        for _ in range(a.grad_accum):
            if i % len(order) == 0:
                random.Random(a.seed + i).shuffle(order)
            p_ids, tgt, w, _ = data[order[i % len(order)]]
            i += 1
            x = torch.tensor([p_ids + tgt], device=dev)
            K = len(tgt) + 1
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(input_ids=x, logits_to_keep=K).logits[:, :-1].float()
            y = torch.tensor([tgt], device=dev)
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
            loss = loss * (w / wmean) / a.grad_accum
            loss.backward()
            tot += float(loss)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step(); sched.step()
        el = time.time() - t_start
        rec = {"step": step + 1, "of": steps, "loss": round(tot, 4), "lr": sched.get_last_lr()[0],
               "examples": i, "elapsed_s": round(el, 1)}
        log.write(json.dumps(rec) + "\n"); log.flush()
        if (step + 1) % 10 == 0 or step == 0:
            print(f"[sft] {rec} eta_min={(steps - step - 1) * el / (step + 1) / 60:.1f}", flush=True)
        if time.time() > deadline:
            print(f"[sft] time box hit at step {step + 1}", flush=True)
            break
    model.save_pretrained(out / "lora")
    tok.save_pretrained(out / "lora")
    cfg = out / "lora" / "adapter_config.json"
    c = json.load(open(cfg)); c["base_model_name_or_path"] = a.model; json.dump(c, open(cfg, "w"), indent=1)
    (out / "lora" / "dagger_summary.json").write_text(json.dumps(
        {"examples": len(data), "tokens": n_tok, "steps": step + 1, "seconds": round(time.time() - t_start),
         "args": vars(a)}, default=str, indent=1))
    print(f"[sft] saved {out / 'lora'}", flush=True)


def tokcheck(a):
    """Print a hash of prompt ids for a few solver states (compare across venvs / tokenizer dirs)."""
    import hashlib
    from transformers import AutoTokenizer
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver import SolverPolicy
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    h = hashlib.sha1()
    for tier in ("easy", "hard"):
        env = Env(tier=tier, seed=SEED_BASE + 41_000)
        ep = run_episode(env, SolverPolicy())
        pr = Prompter(tok, env.tools_spec(), env.instruction(), 8192, 96)
        for t in (0, 5, len(ep.steps) // 2, len(ep.steps) - 1):
            h.update(json.dumps(pr.ids(ep.steps[:t])).encode())
    print("tokcheck", h.hexdigest(), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest"); s.add_argument("--tiers", default="easy,medium,hard"); s.add_argument("--n", type=int, default=3)
    r = sub.add_parser("rollout")
    r.add_argument("--model", required=True, help="student merged into the base (vLLM)")
    r.add_argument("--tokenizer", required=True); r.add_argument("--out", required=True)
    r.add_argument("--episodes", type=int, default=300); r.add_argument("--tiers", default="easy,medium,hard")
    r.add_argument("--seed-base", type=int, default=SEED_BASE + 20_000)
    r.add_argument("--max-ctx", type=int, default=8192); r.add_argument("--max-new", type=int, default=96)
    r.add_argument("--max-calls", type=int, default=120); r.add_argument("--batch", type=int, default=96)
    r.add_argument("--sample-frac", type=float, default=0.25); r.add_argument("--temperature", type=float, default=0.7)
    r.add_argument("--gpu-mem", type=float, default=0.85); r.add_argument("--seed", type=int, default=0)
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 3))
    k = sub.add_parser("tokcheck"); k.add_argument("--tokenizer", required=True)
    l = sub.add_parser("relabel")
    l.add_argument("--rollouts", required=True); l.add_argument("--out", required=True)
    l.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    t = sub.add_parser("sft")
    t.add_argument("--model", required=True); t.add_argument("--adapter", required=True)
    t.add_argument("--rollouts", required=True); t.add_argument("--labels", required=True); t.add_argument("--out", required=True)
    t.add_argument("--max-ctx", type=int, default=8192); t.add_argument("--max-new", type=int, default=96)
    t.add_argument("--keep-agree", type=float, default=0.25); t.add_argument("--key-weight", type=float, default=3.0)
    t.add_argument("--max-examples", type=int, default=0); t.add_argument("--epochs", type=float, default=1.0)
    t.add_argument("--grad-accum", type=int, default=16); t.add_argument("--lr", type=float, default=5e-5)
    t.add_argument("--hours", type=float, default=1.0); t.add_argument("--seed", type=int, default=0)
    t.add_argument("--tokenizer", default=None); t.add_argument("--build-only", action="store_true")
    t.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    t.add_argument("--max-repeat", type=int, default=2, help="per (day, non-key label) per episode")
    a = ap.parse_args(argv)
    {"selftest": selftest, "tokcheck": tokcheck, "rollout": rollout, "relabel": relabel, "sft": sft}[a.cmd](a)


if __name__ == "__main__":
    main()
