"""LoRA SFT of Qwen2.5-1.5B-Instruct on exported Canary transcripts (V100: fp16 AMP, sdpa).

    python -m train.lora_sft --data DIR_OR_GLOB --out OUT [--model PATH] [--epochs 1]
        [--max-steps N] [--pilot] [--max-len 4096] [--grad-accum 8] [--lr 2e-4]
        [--max-episodes N] [--tiny]

--pilot  : run ~--pilot-steps optimizer steps, print tokens/s and the estimated full-run time.
--tiny   : replace the model with a tiny randomly initialised Qwen2 (CPU smoke test); the
           tokenizer still comes from --model (needs only the tokenizer files).
Loss on assistant tokens only; long episodes are split into windows (train.windows).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import time

DEFAULT_MODEL = os.path.expanduser("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct")
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_records(data: str, max_episodes: int | None = None, split: str = "train"):
    if os.path.isdir(data):
        files = sorted(glob.glob(os.path.join(data, f"{split}-*.jsonl")))
    else:
        files = sorted(glob.glob(data))
    recs = []
    for fn in files:
        with open(fn) as f:
            for line in f:
                if line.strip():
                    recs.append(json.loads(line))
    random.Random(0).shuffle(recs)
    return recs[:max_episodes] if max_episodes else recs


_TOK = None


def _init_tok(model_path):
    global _TOK
    from transformers import AutoTokenizer
    _TOK = AutoTokenizer.from_pretrained(model_path)


def _np_windows(ws):
    import numpy as np
    return [(np.asarray(i, dtype=np.int32), np.asarray(l, dtype=np.int32)) for i, l in ws]


def _rec_windows(args):
    rec, max_len = args
    from train.windows import record_windows
    return _np_windows(record_windows(rec, _TOK, max_len))


def build_windows(recs, model_path, tok, max_len, workers):
    """Tokenize episodes into windows; parallel across `workers` processes (order preserved)."""
    from train.windows import record_windows
    if workers <= 1 or len(recs) < 64:
        return [w for r in recs for w in _np_windows(record_windows(r, tok, max_len))]
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(workers, initializer=_init_tok, initargs=(model_path,)) as pool:
        parts = pool.map(_rec_windows, [(r, max_len) for r in recs], chunksize=32)
    return [w for part in parts for w in part]


def tok_cache_path(cache_dir, data, max_len, max_episodes, model_path):
    import hashlib
    files = sorted(glob.glob(os.path.join(data, "train-*.jsonl")) if os.path.isdir(data) else glob.glob(data))
    sig = json.dumps([[f, os.path.getsize(f), int(os.path.getmtime(f))] for f in files]
                     + [max_len, max_episodes, os.path.basename(model_path.rstrip("/"))])
    return os.path.join(cache_dir, hashlib.sha1(sig.encode()).hexdigest()[:16] + ".pkl")


def slurm_budget_hours(reserve_min: float) -> float | None:
    """Hours left in this Slurm job minus `reserve_min`; None outside Slurm or if unknown."""
    jid = os.environ.get("SLURM_JOB_ID")
    if not jid:
        return None
    import subprocess
    from datetime import datetime
    try:
        end = subprocess.run(["squeue", "-j", jid, "-h", "-o", "%e"], capture_output=True,
                             text=True, timeout=20).stdout.strip()
        left = (datetime.strptime(end, "%Y-%m-%dT%H:%M:%S") - datetime.now()).total_seconds()
    except Exception:
        left = None
    if left is None:  # squeue unavailable (e.g. inside the container): use a deadline file
        fn = os.path.expanduser(f"~/agent-arena-data/j4/deadline-{jid}.txt")
        try:
            left = float(open(fn).read().split()[0]) - time.time()
        except Exception:
            return None
    return max(0.05, (left - 60 * reserve_min) / 3600)


def build_model(args, torch, device):
    from transformers import AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model
    if args.tiny:
        from transformers import Qwen2Config, Qwen2ForCausalLM
        cfg = Qwen2Config(vocab_size=151936, hidden_size=64, intermediate_size=128,
                          num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
                          max_position_embeddings=32768, tie_word_embeddings=True)
        cfg._attn_implementation = "sdpa"
        torch.manual_seed(0)
        model = Qwen2ForCausalLM(cfg)
    else:
        dtype = torch.float16 if device == "cuda" else torch.float32
        model = AutoModelForCausalLM.from_pretrained(args.model, dtype=dtype,
                                                     attn_implementation="sdpa")
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=args.r, lora_alpha=2 * args.r, lora_dropout=0.05,
                                             target_modules=TARGETS, task_type="CAUSAL_LM"))
    for p in model.parameters():  # fp32 master weights for the trainable LoRA params
        if p.requires_grad:
            p.data = p.data.float()
    model.to(device)
    return model


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=0, help="optimizer steps; 0 = from epochs")
    ap.add_argument("--max-len", type=int, default=None, help="default 4096 prefix / 2048 dense")
    ap.add_argument("--window-mode", choices=["prefix", "dense"], default="prefix")
    ap.add_argument("--overlap", type=int, default=256, help="dense: token overlap between chunks")
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--max-episodes", type=int, default=0)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--pilot-steps", type=int, default=5)
    ap.add_argument("--tiny", action="store_true")
    ap.add_argument("--max-hours", type=float, default=0, help="stop + save after this long")
    ap.add_argument("--save-every", type=int, default=200)
    ap.add_argument("--tok-workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    ap.add_argument("--tok-cache", default=os.path.expanduser("~/agent-arena-data/j4/tok"),
                    help="dir for cached tokenized windows ('' disables)")
    ap.add_argument("--reserve-min", type=float, default=90,
                    help="in Slurm: clamp --max-hours to job end minus this (eval reserve)")
    a = ap.parse_args(argv)

    if a.max_len is None:
        a.max_len = 2048 if a.window_mode == "dense" else 4096
    import torch
    from transformers import AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    from train.windows import record_windows

    recs = load_records(a.data, a.max_episodes or None)
    t0 = time.time()
    cache = tok_cache_path(a.tok_cache, a.data, a.max_len, a.max_episodes, a.model) if a.tok_cache else None
    if cache and os.path.exists(cache):
        import pickle
        with open(cache, "rb") as f:
            windows = pickle.load(f)
        print(f"[data] loaded tokenized cache {cache}", flush=True)
    else:
        windows = build_windows(recs, a.model, tok, a.max_len, a.tok_workers)
        if cache:
            import pickle
            os.makedirs(a.tok_cache, exist_ok=True)
            with open(cache + ".tmp", "wb") as f:
                pickle.dump(windows, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(cache + ".tmp", cache)
    random.Random(1).shuffle(windows)
    n_tok = sum(len(w[0]) for w in windows)
    n_lab = sum(int((w[1] != -100).sum()) for w in windows)
    print(f"[data] episodes={len(recs)} windows={len(windows)} tokens={n_tok} "
          f"loss_tokens={n_lab} loss_frac={n_lab / max(n_tok, 1):.3f} mode={a.window_mode} "
          f"max_len={a.max_len} max_window={max((len(w[0]) for w in windows), default=0)} "
          f"tokenize_s={time.time() - t0:.1f}", flush=True)
    if recs:
        hdr = tok.apply_chat_template(recs[0]["messages"][:2], tools=recs[0].get("tools"),
                                      tokenize=False)
        h = len(tok(hdr, add_special_tokens=False)["input_ids"])
        print(f"[data] header(system+tools+kickoff)={h} tokens, body budget={a.max_len - h}",
              flush=True)
        if h > a.max_len - 512:
            print("[warn] header leaves <512 tokens per window; raise --max-len", flush=True)
    if not windows:
        raise SystemExit("no training windows (header longer than --max-len?)")

    if not a.pilot:
        budget = slurm_budget_hours(a.reserve_min)
        if budget is not None and (not a.max_hours or budget < a.max_hours):
            print(f"[train] clamping max_hours {a.max_hours} -> {budget:.2f} (job end - {a.reserve_min} min)",
                  flush=True)
            a.max_hours = budget
    steps_per_epoch = math.ceil(len(windows) / a.grad_accum)
    total_steps = a.max_steps or max(1, int(steps_per_epoch * a.epochs))
    if a.pilot:
        total_steps = min(total_steps, a.pilot_steps)
    full_steps = a.max_steps or max(1, int(steps_per_epoch * a.epochs))

    model = build_model(a, torch, device)
    model.print_trainable_parameters()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    warm = max(1, int(0.03 * total_steps))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, 1 - s / max(total_steps, 1)) ** 0.5)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    model.train()
    os.makedirs(a.out, exist_ok=True)

    wi, step, tok_seen, t_start = 0, 0, 0, time.time()
    log = open(os.path.join(a.out, "train_log.jsonl"), "a")
    while step < total_steps:
        loss_acc = 0.0
        for _ in range(a.grad_accum):
            inp, lab = windows[wi % len(windows)]
            wi += 1
            x = torch.as_tensor(inp, dtype=torch.long, device=device).unsqueeze(0)
            y = torch.as_tensor(lab, dtype=torch.long, device=device).unsqueeze(0)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                loss = model(input_ids=x, labels=y).loss / a.grad_accum
            scaler.scale(loss).backward()
            loss_acc += float(loss)
            tok_seen += len(inp)
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        scaler.step(opt)
        scaler.update()
        opt.zero_grad(set_to_none=True)
        sched.step()
        step += 1
        el = time.time() - t_start
        rec = {"step": step, "loss": round(loss_acc, 4), "lr": sched.get_last_lr()[0],
               "tok_per_s": round(tok_seen / el, 1), "elapsed_s": round(el, 1)}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        if step % 10 == 0 or step == total_steps or a.pilot:
            print(f"[train] {rec}", flush=True)
        if a.max_hours and el > 3600 * a.max_hours:
            print(f"[train] time box hit at step {step}", flush=True)
            break
        if not a.pilot and step % a.save_every == 0:
            model.save_pretrained(os.path.join(a.out, f"ckpt-{step}"))

    el = time.time() - t_start
    tps = tok_seen / max(el, 1e-9)
    est_full_s = n_tok * (full_steps / steps_per_epoch) / max(tps, 1e-9)
    summary = {"device": device, "steps": step, "tokens": tok_seen, "seconds": round(el, 1),
               "tokens_per_s": round(tps, 1), "windows": len(windows),
               "steps_per_epoch": steps_per_epoch, "full_run_steps": full_steps,
               "est_full_run_hours": round(est_full_s / 3600, 2), "pilot": a.pilot}
    print("[summary] " + json.dumps(summary), flush=True)
    with open(os.path.join(a.out, "pilot.json" if a.pilot else "train_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    if not a.pilot:
        model.save_pretrained(a.out)
        tok.save_pretrained(a.out)
        print(f"[saved] LoRA adapter -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
