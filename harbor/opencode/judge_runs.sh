#!/bin/bash
set -u
cd "$(dirname "$0")/../.."
SEATS=${SEATS:-${SEAT:-controller}}
SEEDS=${SEEDS:-${SEED:-0}}
RUNS=${RUNS:-"oracle do_nothing stop_early exploit"}
HARBOR=${HARBOR:-harbor}
OUT=${OUT:-results/judge_runs}
AGENTS=$PWD/harbor/opencode/judge_agents
PYTHONPATH=$PWD python -m harbor.build --seeds "$SEEDS" --seat "$SEATS" >/dev/null
rm -rf "$OUT"; mkdir -p "$OUT"
for T in harbor/tasks/*; do
  n=$(basename "$T")
  s=${n#*-s}; seed=${s%%-*}; seat=${s#*-}
  case ",${SEATS}," in *,"$seat",*|*,all,*) ;; *) continue;; esac
  python - "$SEEDS" "$seed" <<'PY' || continue
import sys
spec, seed = sys.argv[1], int(sys.argv[2])
ok = False
for p in spec.split(","):
    a, _, b = p.partition("..")
    ok |= int(a) <= seed <= int(b or a)
sys.exit(0 if ok else 1)
PY
  for name in $RUNS; do
    case $name in
      oracle) a="-a oracle";;
      do_nothing) a="-a nop";;
      stop_early) a="--agent-import-path stop_early:StopEarlyAgent";;
      exploit) a="--agent-import-path exploit_agent:ExploitAgent";;
    esac
    start=$SECONDS
    PYTHONPATH=$AGENTS $HARBOR run -p "$T" -o "$OUT/$n/$name" --yes $a >"$OUT/$n-$name.log" 2>&1
    r=$(cat "$OUT/$n/$name"/*/*/verifier/reward.txt 2>/dev/null || echo none)
    echo "$n $name reward=$r ($((SECONDS-start))s)"
  done
done
echo "opencode: harbor run -p harbor/tasks/<task> -a opencode -m gemini/<model> --ae GEMINI_API_KEY=\$GEMINI_API_KEY (needs a key)"
