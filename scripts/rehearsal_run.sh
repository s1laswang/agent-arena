#!/usr/bin/env bash
# Judge rehearsal launcher (protocol: results/harbor/rehearsal/README.md).
#   scripts/rehearsal_run.sh <out-dir>      e.g. results/harbor/rehearsal
# Run from a checkout of exactly the tagged commit. Needs GEMINI_API_KEY in .env (never printed) and Harbor + Docker.
# Builds the default judge set once, then runs oracle, do_nothing, stop_early and 3 OpenCode gemini-4-carbon runs on it.
set -euo pipefail
OUT=${1:?out dir}
mkdir -p "$OUT"
rm -rf harbor/dataset
uv run --python 3.12 python harbor/build.py
{ echo "sha: $(git rev-parse HEAD)"; echo "describe: $(git describe --tags --always)"; echo "built_utc: $(date -u +%FT%TZ)";
  echo "harbor: $(harbor --version 2>&1 | tail -1)"; grep -m1 '^timeout_sec = ' harbor/dataset/canary-hard-900000/task.toml | sed 's/^/agent_/'; } > "$OUT/BUILD.txt"
GOOGLE_GENERATIVE_AI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2- | tr -d '"')"
export GOOGLE_GENERATIVE_AI_API_KEY
LOGS=${REHEARSAL_LOGS:-$OUT/.logs}; mkdir -p "$LOGS"
OC=(-a opencode -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY --agent-setup-timeout-multiplier 4
    --max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError -n 3 -y -o "$OUT")
pids=()
for k in 1 2 3; do
  harbor run -p harbor/dataset "${OC[@]}" --job-name "opencode-$k" > "$LOGS/opencode-$k.log" 2>&1 & pids+=($!)
  sleep 20   # stagger the three jobs' container starts
done
( harbor run -p harbor/dataset -a oracle -n 2 -y -o "$OUT" --job-name oracle > "$LOGS/oracle.log" 2>&1
  for p in do_nothing stop_early; do
    harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=$p -n 2 -y -o "$OUT" --job-name $p > "$LOGS/$p.log" 2>&1
  done ) & pids+=($!)
echo "started: ${pids[*]} (PIDs of this script's own jobs; stop only these)"
wait "${pids[@]}"
echo "all jobs done $(date -u +%T)"
