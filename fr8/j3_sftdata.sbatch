#!/bin/bash
#SBATCH -J canary-j3
#SBATCH -p normal
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH --time=02:00:00
#SBATCH --array=0-7%8
#SBATCH -o /home/silas/agent-arena-data/j3/slurm-%A_%a.out
# 8 tasks (<=8 cores): tasks 0-5 = train (3 tiers x 2 halves, ~3334 eps each = 20k), 6-7 = val (2k across tiers).
# Seeds are assigned by train.export_sft from --split (train: 100000-199999); shards pass --shard/--nshards.
# TODO(trainer): confirm export_sft accepts --shard/--nshards (else drop and use one task per tier).
source ~/agent-arena/fr8/env.sh || exit 1
tiers=(easy medium hard)
i=$SLURM_ARRAY_TASK_ID
if [ "$i" -lt 6 ]; then split=train; tier=${tiers[$((i/2))]}; n=3334; shard=$((i%2)); ns=2
else split=val; tier=all; n=1000; shard=$((i-6)); ns=2; fi
out=$HOME/agent-arena-data/j3/$split/$tier
mkdir -p "$out"
python -m train.export_sft --split $split --tier $tier --n $n --out "$out" --shard $shard --nshards $ns ${J3_ARGS:-}
