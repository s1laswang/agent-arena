"""LoRA SFT of a small open model on the exported data (TRL + PEFT). UNTESTED on a GPU.

Written for 1 x V100 (fp16 only: no bf16, no FlashAttention-2, so attention is 'sdpa').
Loss is on the assistant turns only (the tool calls and the final summary), never on the
instruction or the tool results. By default the output layer is only run on those tokens
("sparse logits"), which keeps memory low for ~10k-token conversations.

    python training/train_lora.py --dry-run                     # prints the config, needs nothing installed
    python training/train_lora.py --data training/data/sft.jsonl --out training/out/qwen3-4b-lora
    python training/train_lora.py --model Qwen/Qwen2.5-1.5B-Instruct --max-len 8192   # smaller / faster

Needs: torch, transformers, peft, accelerate, datasets, and trl (optional: without trl it
falls back to the plain transformers Trainer). See training/requirements.txt.
Slurm: see training/slurm/train_lora.sbatch. --resume continues from the last checkpoint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.common import (ROOT, assistant_char_spans, model_short_name, render_text,  # noqa: E402
                             validate_row)

DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_TARGETS = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="LoRA SFT on training/data/sft.jsonl (1 GPU, fp16).")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF model id or local folder")
    ap.add_argument("--data", default=str(ROOT / "training" / "data" / "sft.jsonl"))
    ap.add_argument("--out", default="", help="output folder (default training/out/<model>-lora[-<SLURM_JOB_ID>])")
    ap.add_argument("--protocol", choices=["auto", "native", "plain"], default="auto",
                    help="native = the model's chat template with tools; plain = tools as text (must match eval)")
    ap.add_argument("--max-len", type=int, default=16384, help="max tokens per conversation")
    ap.add_argument("--truncate", action="store_true", help="cut long conversations instead of dropping them")
    ap.add_argument("--max-examples", type=int, default=0, help="use at most this many rows (0 = all)")
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--warmup-ratio", type=float, default=0.03)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", default=DEFAULT_TARGETS)
    ap.add_argument("--precision", choices=["fp16", "fp32"], default="fp16",
                    help="fp16 = fp16 base weights + fp32 LoRA weights + fp16 autocast (V100)")
    ap.add_argument("--attn", default="sdpa", help="attn_implementation (V100: sdpa or eager)")
    ap.add_argument("--no-grad-ckpt", action="store_true", help="turn off gradient checkpointing")
    ap.add_argument("--no-sparse-logits", action="store_true",
                    help="run the output layer on every token (more memory)")
    ap.add_argument("--trainer", choices=["trl", "hf"], default="trl")
    ap.add_argument("--logging-steps", type=int, default=5)
    ap.add_argument("--save-total-limit", type=int, default=2)
    ap.add_argument("--resume", action="store_true", help="resume from the newest checkpoint in --out")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trust-remote-code", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the config and data stats, train nothing")
    args = ap.parse_args(argv)
    if not args.out:
        tail = os.environ.get("SLURM_JOB_ID")
        name = model_short_name(args.model) + "-lora" + (f"-{tail}" if tail else "")
        args.out = str(ROOT / "training" / "out" / name)
    return args


def config_dict(args) -> dict:
    cfg = dict(vars(args))
    cfg["effective_batch"] = args.batch_size * args.grad_accum
    cfg["fp16"] = args.precision == "fp16"
    cfg["bf16"] = False
    cfg["gradient_checkpointing"] = not args.no_grad_ckpt
    cfg["sparse_logits"] = not args.no_sparse_logits
    cfg["loss"] = "assistant turns only"
    cfg["slurm_job_id"] = os.environ.get("SLURM_JOB_ID")
    return cfg


def load_rows(path, limit: int = 0) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def data_stats(rows: list, max_len: int) -> dict:
    """Rough sizes without a tokenizer (about 3 characters per token for this JSON-heavy text)."""
    bad = sum(1 for r in rows if validate_row(r))
    lens = sorted(len(render_text(None, r["messages"], r["tools"])) // 3 for r in rows)
    fams: dict = {}
    for r in rows:
        fams[r.get("family", "?")] = fams.get(r.get("family", "?"), 0) + 1
    if not lens:
        return {"rows": 0}
    return {"rows": len(rows), "invalid_rows": bad, "by_family": fams,
            "approx_tokens": {"min": lens[0], "median": lens[len(lens) // 2], "max": lens[-1]},
            "approx_over_max_len": sum(1 for n in lens if n > max_len)}


# ---------------------------------------------------------------- tokenization

def tokenize_example(tok, row: dict, protocol: str, max_len: int, truncate: bool):
    """-> {"input_ids", "labels"} with labels = -100 outside assistant turns, or None (too long / bad)."""
    full, spans = assistant_char_spans(tok, row["messages"], row["tools"], protocol)
    if spans is None:
        return None
    if getattr(tok, "is_fast", False):
        enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
        ids, offs = enc["input_ids"], enc["offset_mapping"]
        labels = [-100] * len(ids)
        k = 0
        for t, (a, b) in enumerate(offs):
            while k < len(spans) and spans[k][1] <= a:
                k += 1
            if k < len(spans) and a >= spans[k][0] and b <= spans[k][1] and b > a:
                labels[t] = ids[t]
    else:   # slow tokenizer: tokenize the pieces one by one
        ids, labels, pos = [], [], 0
        for a, b in spans + [(len(full), len(full))]:
            for piece, train_it in ((full[pos:a], False), (full[a:b], True)):
                if piece:
                    p_ids = tok(piece, add_special_tokens=False)["input_ids"]
                    ids += p_ids
                    labels += list(p_ids) if train_it else [-100] * len(p_ids)
            pos = b
    if len(ids) > max_len:
        if not truncate:
            return None
        ids, labels = ids[:max_len], labels[:max_len]
    if all(x == -100 for x in labels):
        return None
    return {"input_ids": ids, "labels": labels}


class PadCollator:
    def __init__(self, pad_id: int, multiple: int = 8):
        self.pad_id = pad_id
        self.multiple = multiple

    def __call__(self, batch):
        import torch
        n = max(len(b["input_ids"]) for b in batch)
        if len(batch) > 1:   # one example: no padding, so attention can skip the mask
            n = ((n + self.multiple - 1) // self.multiple) * self.multiple
        ids = torch.full((len(batch), n), self.pad_id, dtype=torch.long)
        lab = torch.full((len(batch), n), -100, dtype=torch.long)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            m = len(b["input_ids"])
            ids[i, :m] = torch.tensor(b["input_ids"], dtype=torch.long)
            lab[i, :m] = torch.tensor(b["labels"], dtype=torch.long)
            att[i, :m] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}


def make_trainer_class(base, sparse: bool):
    """Trainer subclass whose loss runs the output layer only on labelled (assistant) tokens."""
    import torch
    import torch.nn.functional as F

    class AssistantLossTrainer(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            # we return a per-batch mean, so the Trainer must divide by the grad accumulation steps
            self.model_accepts_loss_kwargs = False
            self.loss_is_scaled_for_ga = False

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            inputs = dict(inputs)
            labels = inputs.pop("labels")
            dec = model.get_decoder() if (sparse and hasattr(model, "get_decoder")) else None
            head = model.get_output_embeddings() if dec is not None else None
            if dec is not None and head is not None:
                amp = bool(getattr(self.args, "fp16", False)) and torch.cuda.is_available()
                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=amp):
                    hidden = dec(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"],
                                 use_cache=False).last_hidden_state
                    h, y = hidden[:, :-1, :], labels[:, 1:]
                    mask = y != -100
                    logits = head(h[mask])
                logits = logits.float()
                loss = F.cross_entropy(logits, y[mask]) if mask.any() else logits.sum() * 0.0
            else:
                out = model(**inputs, use_cache=False)
                logits = out.logits[:, :-1, :].float()
                y = labels[:, 1:]
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1), ignore_index=-100)
            return (loss, {"loss": loss}) if return_outputs else loss

    return AssistantLossTrainer


def trainer_kwargs(args, has_val: bool = True) -> dict:
    """Trainer settings with the current names (transformers 5 / TRL 1). See compat_kwargs()."""
    kw = dict(output_dir=args.out, num_train_epochs=args.epochs, per_device_train_batch_size=args.batch_size,
              per_device_eval_batch_size=1, gradient_accumulation_steps=args.grad_accum,
              learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=args.warmup_ratio,
              weight_decay=0.0, max_grad_norm=1.0, logging_steps=args.logging_steps,
              save_strategy="epoch", save_total_limit=args.save_total_limit,
              fp16=args.precision == "fp16", bf16=False,
              gradient_checkpointing=not args.no_grad_ckpt, gradient_checkpointing_kwargs={"use_reentrant": False},
              report_to="none", seed=args.seed, remove_unused_columns=False, prediction_loss_only=True,
              dataloader_num_workers=0, optim="adamw_torch")
    if has_val:
        kw["eval_strategy"] = "epoch"
    return kw


def compat_kwargs(kw: dict, fields: set, trl: bool = False, max_len: int | None = None) -> dict:
    """Rename / drop settings so they fit the installed config class (its dataclass field names).

    transformers 5 has a float warmup_steps (ratio) and eval_strategy; older ones have
    warmup_ratio and evaluation_strategy. TRL: max_length (new) or max_seq_length (old).
    """
    kw = dict(kw)
    if "warmup_steps" in kw and isinstance(kw["warmup_steps"], float) and "warmup_ratio" in fields:
        kw["warmup_ratio"] = kw.pop("warmup_steps")
    if "eval_strategy" in kw and "eval_strategy" not in fields and "evaluation_strategy" in fields:
        kw["evaluation_strategy"] = kw.pop("eval_strategy")
    if trl:
        kw["dataset_kwargs"] = {"skip_prepare_dataset": True}
        kw["packing"] = False
        if max_len:
            kw["max_seq_length" if ("max_seq_length" in fields and "max_length" not in fields) else "max_length"] = max_len
    dropped = sorted(k for k in kw if k not in fields)
    if dropped:
        print(f"[train] note: this version does not take {dropped}; skipped")
    return {k: v for k, v in kw.items() if k in fields}


def _fields(cls) -> set:
    return set(getattr(cls, "__dataclass_fields__", {}))


def train(args) -> int:
    import inspect
    import random

    if "CUDA_VISIBLE_DEVICES" not in os.environ:   # 1 GPU by design (Slurm sets this for us)
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    print(f"[train] torch {torch.__version__}, cuda {torch.cuda.is_available()}, "
          f"gpus {torch.cuda.device_count()}", flush=True)

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=args.trust_remote_code)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    from training.common import choose_protocol
    protocol = choose_protocol(tok, args.protocol)
    print(f"[train] protocol: {protocol}", flush=True)

    rows = load_rows(args.data, args.max_examples)
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    examples, dropped = [], 0
    for r in rows:
        ex = tokenize_example(tok, r, protocol, args.max_len, args.truncate)
        if ex is None:
            dropped += 1
        else:
            examples.append(ex)
    if not examples:
        print("[train] no usable examples (all too long?). Try a bigger --max-len or --truncate.")
        return 2
    n_val = int(len(examples) * args.val_frac) if len(examples) >= 20 else 0
    val, trn = examples[:n_val], examples[n_val:]
    ntok = sum(len(e["input_ids"]) for e in trn)
    nlab = sum(sum(1 for x in e["labels"] if x != -100) for e in trn)
    print(f"[train] {len(trn)} train / {len(val)} val examples, {dropped} dropped; "
          f"{ntok} tokens, {nlab} trained tokens", flush=True)

    if args.precision == "fp16" and not torch.cuda.is_available():
        print("[train] no GPU: using fp32 (fp16 training needs a GPU)", flush=True)
        args.precision = "fp32"
    fp16 = args.precision == "fp16"
    from training.common import dtype_kwarg
    model = AutoModelForCausalLM.from_pretrained(
        args.model, attn_implementation=args.attn, trust_remote_code=args.trust_remote_code,
        **dtype_kwarg(torch.float16 if fp16 else torch.float32))
    model.config.use_cache = False
    if torch.cuda.is_available():
        model.to("cuda")
    lora = LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
                      target_modules=[m.strip() for m in args.target_modules.split(",") if m.strip()],
                      bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    for p in model.parameters():          # trainable LoRA weights in fp32 (fp16 AMP needs that)
        if p.requires_grad:
            p.data = p.data.float()
    model.print_trainable_parameters()

    from datasets import Dataset
    train_ds = Dataset.from_list(trn)
    val_ds = Dataset.from_list(val) if val else None

    common = trainer_kwargs(args, has_val=val_ds is not None)
    base, cfg = None, None
    if args.trainer == "trl":
        try:
            from trl import SFTConfig, SFTTrainer
            cfg = SFTConfig(**compat_kwargs(common, _fields(SFTConfig), trl=True, max_len=args.max_len))
            base = SFTTrainer
        except ImportError:
            print("[train] trl not installed; using the transformers Trainer")
    if base is None:
        cfg = TrainingArguments(**compat_kwargs(common, _fields(TrainingArguments)))
        base = Trainer

    cls = make_trainer_class(base, sparse=not args.no_sparse_logits)
    tkw = dict(model=model, args=cfg, train_dataset=train_ds, eval_dataset=val_ds,
               data_collator=PadCollator(tok.pad_token_id))
    params = inspect.signature(base.__init__).parameters
    tkw["processing_class" if "processing_class" in params else "tokenizer"] = tok
    trainer = cls(**tkw)

    resume = None
    if args.resume and Path(args.out).exists() and any(Path(args.out).glob("checkpoint-*")):
        resume = True
    trainer.train(resume_from_checkpoint=resume)
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    with open(Path(args.out) / "pinbox_train_config.json", "w", encoding="utf-8") as f:
        json.dump({**config_dict(args), "protocol_used": protocol, "train_examples": len(trn),
                   "val_examples": len(val), "dropped": dropped}, f, indent=1)
    print(f"[train] saved LoRA adapter to {args.out}")
    print(f"[train] next: python training/eval_small_model.py --model {args.model} --adapter {args.out}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        out = {"config": config_dict(args), "trainer_kwargs": trainer_kwargs(args)}
        if Path(args.data).exists():
            rows = load_rows(args.data, args.max_examples)
            out["data"] = data_stats(rows, args.max_len)
        else:
            out["data"] = f"missing: {args.data} (run training/export_sft.py first)"
        print(json.dumps(out, indent=1))
        print("[train] dry run: nothing trained, no ML libraries imported")
        return 0
    return train(args)


if __name__ == "__main__":
    sys.exit(main())
