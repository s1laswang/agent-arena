#!/usr/bin/env bash
# Stop the FR8 login-node gateway (our pidfile only) and show its final stats summary.
set -euo pipefail
source "$(dirname "$0")/common.sh"
ssh "$FR8_HOST" "bash -s" <<REMOTE
cd $GEM_CODE
if [ -f run/gateway.pid ] && kill -0 \$(cat run/gateway.pid) 2>/dev/null; then
  pid=\$(cat run/gateway.pid); kill -TERM \$pid
  for i in \$(seq 1 50); do kill -0 \$pid 2>/dev/null || break; sleep 0.2; done
  kill -0 \$pid 2>/dev/null && { echo "still alive, SIGKILL"; kill -KILL \$pid; }
  echo "gateway \$pid stopped"
else
  echo "gateway not running"
fi
rm -f run/gateway.pid run/gateway.url
# no leftovers of ours
pgrep -u \$USER -af canary.gemini.gateway || echo "no gateway processes left"
f=\$(ls -t $GEM_DATA/gateway/stats-*.jsonl 2>/dev/null | head -1)
[ -n "\$f" ] && python3 -c "import json,sys,collections;r=[json.loads(l) for l in open(sys.argv[1])];c=collections.Counter(x['status'] for x in r);print('last stats file',sys.argv[1],'requests',len(r),'status',dict(c))" "\$f" || true
REMOTE
