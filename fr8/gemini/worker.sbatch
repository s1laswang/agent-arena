#!/bin/bash
# Generic Canary Lab worker: runs one command per array task with the gateway env set.
#   sbatch --array=0-3 --time=01:00:00 -c 2 fr8/gemini/worker.sbatch python -m canary.gemini.ladder ... --shard {i}/{n}
# (prefer fr8/gemini/submit.sh from the Mac). {i} -> SLURM_ARRAY_TASK_ID, {n} -> task count, {job} -> array job id.
#SBATCH -p normal
#SBATCH -c 2
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH -J canary-gemini
set -euo pipefail
GEM_CODE=$HOME/agent-arena-gemini
GEM_DATA=$HOME/agent-arena-data/gemini
cd "$GEM_CODE"
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export GEMINI_GATEWAY_URL=${GEMINI_GATEWAY_URL:-$(cat run/gateway.url 2>/dev/null || true)}
export GEMINI_GATEWAY_TOKEN_FILE=${GEMINI_GATEWAY_TOKEN_FILE:-$GEM_CODE/.gateway_token}
export GEMINI_API_KEY=""                       # workers never hold the key
export CANARY_GEMINI_LEDGER_DIR=${CANARY_GEMINI_LEDGER_DIR:-$GEM_DATA/ledger}
JOB=${SLURM_ARRAY_JOB_ID:-${SLURM_JOB_ID:-local}}
I=${SLURM_ARRAY_TASK_ID:-0}
N=${SLURM_ARRAY_TASK_COUNT:-1}
export CANARY_GEMINI_RUN_ID=${CANARY_GEMINI_RUN_ID:-slurm-$JOB}
[ -n "$GEMINI_GATEWAY_URL" ] || { echo "no GEMINI_GATEWAY_URL and no run/gateway.url: start fr8/gemini/gateway_up.sh" >&2; exit 3; }
curl -sf -m 5 "$GEMINI_GATEWAY_URL/healthz" >/dev/null || { echo "gateway $GEMINI_GATEWAY_URL not reachable" >&2; exit 3; }
args=()
for a in "$@"; do a=${a//\{i\}/$I}; a=${a//\{n\}/$N}; a=${a//\{job\}/$JOB}; args+=("$a"); done
[ "${args[0]-}" = python ] && args[0]=$GEM_CODE/.venv/bin/python
echo "[$(date -Iseconds)] $(hostname) task $I/$N run_id=$CANARY_GEMINI_RUN_ID gateway=$GEMINI_GATEWAY_URL: ${args[*]}"
exec "${args[@]}"
