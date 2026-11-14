#!/usr/bin/env bash
# Submit a worker array from the Mac; records the job id in ~/agent-arena-data/jobs/OURS.txt (team rule: only ids
# listed there may ever be cancelled, by id).
#   bash fr8/gemini/submit.sh [--array 0-3] [--time 01:00:00] [-c 2] [--mem 4G] [--name canary-gemini] -- python -m ... {i}/{n}
set -euo pipefail
source "$(dirname "$0")/common.sh"
ARRAY=0; TIME=01:00:00; CPUS=2; MEM=4G; NAME=canary-gemini
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
  case $1 in --array) ARRAY=$2; shift 2;; --time) TIME=$2; shift 2;; -c) CPUS=$2; shift 2;;
             --mem) MEM=$2; shift 2;; --name) NAME=$2; shift 2;; *) echo "unknown arg $1" >&2; exit 2;; esac
done
[ "${1-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "usage: submit.sh [opts] -- <command...>" >&2; exit 2; }
CMD=$(printf '%q ' "$@")
id=$(ssh "$FR8_HOST" "cd $GEM_CODE && mkdir -p $GEM_DATA/logs \$HOME/agent-arena-data/jobs && \
  id=\$(sbatch --parsable -p normal --array=$ARRAY --time=$TIME -c $CPUS --mem=$MEM -J $NAME \
    -o \$HOME/agent-arena-data/gemini/logs/%x-%A_%a.out fr8/gemini/worker.sbatch $CMD) && \
  echo \"\$id $NAME \$(date -Iseconds) gemini-worker array=$ARRAY time=$TIME\" >> \$HOME/agent-arena-data/jobs/OURS.txt && echo \$id")
echo "submitted $NAME: job $id (array $ARRAY, --time $TIME, -c $CPUS); logs ~/agent-arena-data/gemini/logs/$NAME-${id}_*.out"
