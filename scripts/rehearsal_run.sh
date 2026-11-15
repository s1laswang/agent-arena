#!/usr/bin/env bash
# Judge rehearsal launcher (protocol: results/harbor/rehearsal/README.md).
#   scripts/rehearsal_run.sh <out-dir>      e.g. results/harbor/rehearsal
# Run from a checkout of exactly the tagged commit. Needs GEMINI_API_KEY in .env (never printed) and Harbor + Docker.
# Builds the default judge set once, then runs oracle, do_nothing, stop_early and 3 OpenCode gemini-4-carbon runs on it.
#
# Gemini quota (2M input tokens/min on the key; a trial averages ~0.16M/min, ~0.24M late): about 6 OpenCode trials in
# flight. Runs 1 and 2 start at N12 each; run 3 starts at N3 once runs 1+2 have FREE_AT trials left to finish, so if
# time runs out, runs 1 and 2 are complete. Scheduling only: it changes no scoring and no task.
set -euo pipefail
OUT=${1:?out dir}
N12=${N12:-3}; N3=${N3:-4}; FREE_AT=${FREE_AT:-2}
mkdir -p "$OUT"
rm -rf harbor/dataset
uv run --python 3.12 python harbor/build.py
{ echo "sha: $(git rev-parse HEAD)"; echo "describe: $(git describe --tags --always)"; echo "built_utc: $(date -u +%FT%TZ)";
  echo "harbor: $(harbor --version 2>&1 | tail -1)"; grep -m1 '^timeout_sec = ' harbor/dataset/canary-hard-900000/task.toml | sed 's/^/agent_/';
  echo "schedule: opencode-1/2 at -n $N12 from the start; opencode-3 at -n $N3 once runs 1+2 have <= $FREE_AT trials left";
  echo "retries: --max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError"; } > "$OUT/BUILD.txt"
GOOGLE_GENERATIVE_AI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2- | tr -d '"')"
export GOOGLE_GENERATIVE_AI_API_KEY
LOGS=${REHEARSAL_LOGS:-$OUT/.logs}; mkdir -p "$LOGS"
OC=(-a opencode -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY --agent-setup-timeout-multiplier 4
    --max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError -y -o "$OUT")
oc() { harbor run -p harbor/dataset "${OC[@]}" -n "$2" --job-name "opencode-$1" > "$LOGS/opencode-$1.log" 2>&1; }
done_trials() { ls "$OUT"/opencode-1/canary-*/result.json "$OUT"/opencode-2/canary-*/result.json 2>/dev/null | wc -l | tr -d ' '; }
pids=()
oc 1 "$N12" & pids+=($!); sleep 20
oc 2 "$N12" & pids+=($!)
( harbor run -p harbor/dataset -a oracle -n 2 -y -o "$OUT" --job-name oracle > "$LOGS/oracle.log" 2>&1
  for p in do_nothing stop_early; do
    harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=$p -n 2 -y -o "$OUT" --job-name $p > "$LOGS/$p.log" 2>&1
  done ) & pids+=($!)
( until [ "$(done_trials)" -ge $((20 - FREE_AT)) ]; do sleep 30; done
  echo "opencode-3 start: $(date -u +%FT%TZ)" >> "$OUT/BUILD.txt"; oc 3 "$N3" ) & pids+=($!)
echo "started: ${pids[*]} (PIDs of this script's own jobs; stop only these)"
wait "${pids[@]}"
echo "all jobs done $(date -u +%T)"
