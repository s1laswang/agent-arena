#!/bin/bash
set -u
cd "$(dirname "$0")/../.."
SEED=${SEED:-0}
SEAT=${SEAT:-controller}
HARBOR=${HARBOR:-harbor}
OUT=${OUT:-results/judge_runs}
PYTHONPATH=$PWD python -m harbor.build --seeds "$SEED" --seat "$SEAT" >/dev/null
T=$(ls -d harbor/tasks/*s"$SEED"-"$SEAT" | head -1)
rm -rf "$OUT"; mkdir -p "$OUT"
run() {
  name=$1; shift
  PYTHONPATH=$PWD/harbor/opencode/judge_agents $HARBOR run -p "$T" -o "$OUT/$name" --yes "$@" >"$OUT/$name.log" 2>&1
  r=$(cat "$OUT/$name"/*/*/verifier/reward.txt 2>/dev/null || echo none)
  echo "$name reward=$r"
}
run oracle -a oracle
run do_nothing -a nop
run stop_early --agent-import-path stop_early:StopEarlyAgent
run exploit --agent-import-path exploit_agent:ExploitAgent
echo "opencode: harbor run -p $T -a opencode -m gemini/<model> --ae GEMINI_API_KEY=\$GEMINI_API_KEY (needs a key)"
