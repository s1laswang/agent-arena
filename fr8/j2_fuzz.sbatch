#!/bin/bash
#SBATCH -J canary-j2
#SBATCH -p normal
#SBATCH -c 8
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH -o /home/silas/agent-arena-data/j2/slurm-%j.out
# TODO(INTEGRITY): fix module/CLI once the fuzzer lands. Override with J2_CMD.
source ~/agent-arena/fr8/env.sh || exit 1
${J2_CMD:-python -m canary.integrity.fuzz --workers 8 --out $HOME/agent-arena-data/j2}
