"""Merge a PEFT LoRA adapter into its HF base and save fp16 safetensors (CPU; ~6 GB RAM for 1.5B).

    python -m train.merge_peft --adapter DIR --out DIR [--base PATH]
mlx-lm cannot load PEFT adapters (its adapters use its own key names/config), so the demo path
is: merge here (FR8, fr8/j4_merge.sbatch) -> mlx_lm convert -q on the Mac (train/peft_to_mlx.sh).
"""
from __future__ import annotations

import argparse
import json
import os


def base_of(adapter: str, base: str | None) -> str:
    if base:
        return base
    return json.load(open(os.path.join(adapter, "adapter_config.json")))["base_model_name_or_path"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=None, help="default: base_model_name_or_path from adapter")
    a = ap.parse_args(argv)
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base = base_of(a.adapter, a.base)
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float32)  # merge in fp32
    model = PeftModel.from_pretrained(model, a.adapter).merge_and_unload()
    model = model.to(torch.float16)
    model.save_pretrained(a.out, safe_serialization=True)
    AutoTokenizer.from_pretrained(base).save_pretrained(a.out)
    print(json.dumps({"base": base, "adapter": a.adapter, "merged": a.out}))


if __name__ == "__main__":
    main()
