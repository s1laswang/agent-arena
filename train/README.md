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

## Saturday v2: dense windows (more loss per token)
J4 (44397, `--window-mode prefix`, max_len 4096): 3000 episodes -> 72k windows, 287M tokens,
4.5M loss tokens (1.6%), 1.4k tok/s on a V100 => ~57 h per epoch, so it only sees a fraction.
`--window-mode dense` cuts each episode into consecutive chunks (256-token overlap), each
starting with the system+tools header, loss on each assistant token exactly once.

**Header size matters:** the instruction (~6.4k chars) + tool specs (~3.8k chars) are roughly
2.5-3k tokens (the `[data] header=` line prints the exact number). With `--max-len 2048` there is
NO room for the conversation, so use 4096 (or shorten the instruction) for dense:
```
# j3v2 data from the frozen tiers (Mac, 3 procs), then rsync to freighter:~/agent-arena-data/j3v2/
python -m train.export_sft --split train --tier all --n 6667 --workers 3 --out data/j3v2/train
ssh freighter 'cd ~/agent-arena && sbatch --export=ALL,DATA="$HOME/agent-arena-data/j3v2/train/train-*.jsonl",\
TRAIN_ARGS="--window-mode dense --max-len 4096",MAX_EPISODES=800,TRAIN_HOURS=4 fr8/j4_train.sbatch'
```
Throughput math (estimates; check the pilot's `[data]` line): per 4096 window ~2.8k header +
~1.3k body; tokens per episode ~ (episode body tokens / ~1.0k effective stride) x 4.1k.
If an episode body is ~12k tokens -> ~12 windows ~ 50k tokens/episode (vs ~96k in prefix mode)
and the loss share rises to roughly 6-10% (the header is the floor; shortening the instruction
or a 2048 window after shortening it gets past 10%). At 1.4k tok/s: 4 h = 20M tokens ~ 400
episodes/epoch-equivalent; so set `--max-episodes` ~ 400-800 for >= 1 pass in 4-8 h.

## Demo the trained model (J4 LoRA -> MLX, local)
mlx-lm cannot load PEFT adapters directly (different adapter format), so merge then convert.
```
# 1. FR8 (CPU, ~6 GB RAM, ~5 min): merge LoRA into the fp16 base -> run-44397/merged
ssh freighter 'cd ~/agent-arena && sbatch --export=ALL,RUN=$HOME/agent-arena-data/j4/run-44397 fr8/j4_merge.sbatch'
# 2. Mac: pull merged (~3.1 GB) and quantise to 4-bit MLX (~0.9 GB); deletes the fp16 copy after
uv sync --python 3.12 --extra dev --extra mlx
bash train/peft_to_mlx.sh --run run-44397          # -> data/fr8/j4/run-44397/mlx-4bit
# 3. Mac: play held-out episodes with the fused model (no --adapter)
uv run --python 3.12 --extra mlx python -m train.eval_hf --backend mlx \
     --model data/fr8/j4/run-44397/mlx-4bit --tiers easy --seeds heldout --n 5
# base for comparison
uv run --python 3.12 --extra mlx python -m train.eval_hf --backend mlx \
     --model mlx-community/Qwen2.5-1.5B-Instruct-4bit --tiers easy --seeds heldout --n 5
```

## Smoke tests
`make test` (no model needed); CPU tiny-model run: `SMOKE=1 bash fr8/j4_train.sbatch` (srun on FR8).
