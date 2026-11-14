#!/usr/bin/env bash
# PEFT LoRA (J4) -> 4-bit MLX model for the local demo.
#   step 1 (FR8, CPU srun/sbatch): merge   -> fr8/j4_merge.sbatch   (needs ~6 GB RAM; not on the Mac)
#   step 2 (Mac): rsync merged fp16 model (~3.1 GB) -> mlx_lm convert -q (4-bit, ~0.9 GB)
# usage: train/peft_to_mlx.sh --run run-44397 [--out data/fr8/j4/run-44397/mlx-4bit] [--keep-merged]
set -euo pipefail
RUN="" OUT="" KEEP=0
while [ $# -gt 0 ]; do case $1 in
  --run) RUN=$2; shift 2;; --out) OUT=$2; shift 2;; --keep-merged) KEEP=1; shift;;
  -h|--help) sed -n 2,5p "$0"; exit 0;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
[ -n "$RUN" ] || { echo "--run required" >&2; exit 2; }
LOCAL=data/fr8/j4/$RUN
OUT=${OUT:-$LOCAL/mlx-4bit}
mkdir -p "$LOCAL"
ssh freighter "test -f ~/agent-arena-data/j4/$RUN/merged/config.json" \
  || { echo "merged model missing on FR8: sbatch --export=ALL,RUN=\$HOME/agent-arena-data/j4/$RUN fr8/j4_merge.sbatch" >&2; exit 3; }
rsync -az --progress "freighter:~/agent-arena-data/j4/$RUN/merged/" "$LOCAL/merged/"
uv run --python 3.12 --extra mlx python -m mlx_lm convert --hf-path "$LOCAL/merged" --mlx-path "$OUT" -q --q-bits 4
[ "$KEEP" = 1 ] || rm -rf "$LOCAL/merged"
echo "MLX model -> $OUT"
