#!/usr/bin/env bash
# fr8/submit.sh <j1|j2|j3|j5> [extra sbatch args...]  -> sync, sbatch, record id in OURS.txt
# Only ids in freighter:~/agent-arena-data/jobs/OURS.txt may ever be cancelled (by id, never -u / name).
set -euo pipefail
job=${1:?usage: fr8/submit.sh <j1|j2|j3|j5> [sbatch args]}; shift
script=$(ls "$(dirname "$0")"/${job}_*.sbatch); script=fr8/$(basename "$script")
bash "$(dirname "$0")/sync.sh" >/dev/null
q=$(printf '%q ' "$@")
id=$(ssh freighter "mkdir -p ~/agent-arena-data/$job ~/agent-arena-data/jobs && cd ~/agent-arena && \
  id=\$(sbatch --parsable $q $script) && echo \"\$id canary-$job \$(date -Iseconds) $q\" >> ~/agent-arena-data/jobs/OURS.txt && echo \$id" 2>/dev/null)
echo "$job submitted: $id"
