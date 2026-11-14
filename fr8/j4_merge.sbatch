#!/bin/bash
#SBATCH -J canary-j4-merge
#SBATCH -p normal
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH -o /home/silas/agent-arena-data/j4/merge-%j.out
# Runs on FR8 (CPU): merge the J4 PEFT adapter into Qwen2.5-1.5B-Instruct -> fp16 safetensors (~3.1 GB).
# sbatch --export=ALL,RUN=$HOME/agent-arena-data/j4/run-44397 fr8/j4_merge.sbatch
set -euo pipefail
RUN=${RUN:?set RUN=~/agent-arena-data/j4/run-<jobid>}
CODE=${CODE:-$HOME/agent-arena}
module load pytorch-volta
export PYTHONPATH=$CODE HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4
cd "$CODE"
pytorch-exec python -m train.merge_peft --adapter "$RUN/lora" --out "$RUN/merged" \
  --base "$HOME/agent-arena-data/models/Qwen2.5-1.5B-Instruct"
ls -la "$RUN/merged"; du -sh "$RUN/merged"
