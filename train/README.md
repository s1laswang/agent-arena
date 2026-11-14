# train/: small-model training (tiebreaker)

One transcript format (`train/render.py`) for export, HF training, MLX training and both eval backends.

## Primary: V100 on FR8 (J4)
```
python -m train.export_sft --split train --tier all --n 6667 --workers 3 --out data/j3/train
python -m train.export_sft --split val   --tier all --n 667  --workers 3 --out data/j3/val
rsync -az data/j3/ freighter:~/agent-arena-data/j3/
ssh freighter 'cd ~/agent-arena && sbatch fr8/j4_train.sbatch'   # FR8 head submits
```

## Fallback: Apple MLX (Saturday, only if no GPU; NOT run tonight because of Mac memory)
```
uv sync --python 3.12 --extra dev --extra mlx            # mlx-lm, darwin arm64 only
bash train/mlx_lora.sh --train 'data/j3/train/train-*.jsonl' --val 'data/j3/val/val-*.jsonl' \
     --size 0.5B --iters 600 --batch 1 --max-seq 4096 --max-mem 12 --out data/mlx-lora
# eval: base vs LoRA on held-out seeds, same tool loop as eval_hf
uv run --python 3.12 --extra mlx python -m train.eval_hf --backend mlx \
     --model mlx-community/Qwen2.5-0.5B-Instruct-4bit --tiers easy,medium,hard --seeds heldout --n 30
uv run --python 3.12 --extra mlx python -m train.eval_hf --backend mlx \
     --model mlx-community/Qwen2.5-0.5B-Instruct-4bit --adapter data/mlx-lora/adapter \
     --tiers easy,medium,hard --seeds heldout --n 30
```
- `--size 1.5B` if more than about 16 GB is free; `--max-mem` refuses to start below that free RAM (a preflight check only).
- mlx-lm downloads the 4-bit model on first use (about 0.3 GB for 0.5B, 0.9 GB for 1.5B).
- `train/to_mlx.py` converts the shards to `train.jsonl`/`valid.jsonl` ({messages, tools}), cutting long episodes at an assistant turn.
- Caveat: `--mask-prompt` in mlx-lm masks only the prompt, so tool-result tokens are also trained on. The HF path (`train.lora_sft`) masks exactly.

## Smoke tests
`make test` (no model needed); CPU tiny-model run: `SMOKE=1 bash fr8/j4_train.sbatch` (srun on FR8).
