#!/usr/bin/env bash
# MLX LoRA fallback (Apple silicon). Same JSONL as train.export_sft, converted by train.to_mlx.
# usage: train/mlx_lora.sh --train GLOB --val GLOB [--size 0.5B|1.5B] [--iters 600] [--batch 1]
#                          [--max-seq 4096] [--max-mem 12] [--out DIR] [--max-episodes N]
set -euo pipefail
SIZE=0.5B ITERS=600 BATCH=1 MAXSEQ=4096 MAXMEM=12 OUT=data/mlx-lora MAXEP=0 TRAIN="" VAL=""
while [ $# -gt 0 ]; do case $1 in
  --train) TRAIN=$2; shift 2;; --val) VAL=$2; shift 2;; --size) SIZE=$2; shift 2;;
  --iters) ITERS=$2; shift 2;; --batch) BATCH=$2; shift 2;; --max-seq) MAXSEQ=$2; shift 2;;
  --max-mem) MAXMEM=$2; shift 2;; --out) OUT=$2; shift 2;; --max-episodes) MAXEP=$2; shift 2;;
  -h|--help) sed -n 2,4p "$0"; echo "--max-mem GB: refuse to start unless this much RAM is free; preflight check only (mlx_lm lora has no hard cap)"; exit 0;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done
[ -n "$TRAIN" ] && [ -n "$VAL" ] || { echo "--train and --val required" >&2; exit 2; }
case $SIZE in 0.5B|1.5B) ;; *) echo "--size 0.5B|1.5B" >&2; exit 2;; esac
MODEL=mlx-community/Qwen2.5-${SIZE}-Instruct-4bit
# memory guard: free + inactive pages (macOS), in GB
FREE_GB=$(vm_stat | awk '/page size/{ps=$8} /Pages free/{f=$3} /Pages inactive/{i=$3} END{printf "%d", (f+i)*ps/1e9}')
if [ "$FREE_GB" -lt "$MAXMEM" ]; then echo "only ${FREE_GB} GB free < --max-mem ${MAXMEM}; refusing" >&2; exit 3; fi
PY="uv run --python 3.12 --extra mlx python"
$PY -m train.to_mlx --train "$TRAIN" --val "$VAL" --out "$OUT/data" --max-episodes "$MAXEP"
$PY -m mlx_lm lora --model "$MODEL" --train --data "$OUT/data" --adapter-path "$OUT/adapter" \
  --iters "$ITERS" --batch-size "$BATCH" --max-seq-length "$MAXSEQ" --num-layers 16 \
  --mask-prompt --grad-checkpoint --steps-per-eval 100 --save-every 100
echo "adapter -> $OUT/adapter  (eval: python -m train.eval_hf --backend mlx --model $MODEL --adapter $OUT/adapter)"
