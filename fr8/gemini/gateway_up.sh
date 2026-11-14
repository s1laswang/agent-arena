#!/usr/bin/env bash
# Start the gateway on the FR8 login node: niced, nohup/setsid, pidfile, hard self-exit (--max-hours), bound to the
# login node's cluster-internal address (the source IP it uses to reach compute01) so compute nodes can reach it.
# Writes the worker URL to ~/agent-arena-gemini/run/gateway.url. Every request needs the token; the key is read in
# the process from the 0600 ~/agent-arena-gemini/.gateway.env (never argv) and `ps` is checked for it.
#   bash fr8/gemini/gateway_up.sh [--max-hours 8] [--max-concurrency 64] [--model-limit gemini-4-carbon=8 ...]
# Policy (Arena CEO, Sat): only start it when a real FR8 job needs Gemini; stop it with gateway_down.sh after.
set -euo pipefail
source "$(dirname "$0")/common.sh"
EXTRA=("$@")
[[ " ${EXTRA[*]-} " == *" --max-hours "* ]] || EXTRA+=(--max-hours 8)
[[ " ${EXTRA[*]-} " == *" --max-concurrency "* ]] || EXTRA+=(--max-concurrency 64)
[[ " ${EXTRA[*]-} " == *" --model-limit "* ]] || EXTRA+=(--model-limit gemini-4-carbon=8)
Q=$(printf '%q ' "${EXTRA[@]}")
ssh "$FR8_HOST" "bash -s" <<REMOTE
set -euo pipefail
cd $GEM_CODE
mkdir -p run $GEM_DATA/gateway
if [ -f run/gateway.pid ] && kill -0 \$(cat run/gateway.pid) 2>/dev/null; then
  echo "gateway already running: pid \$(cat run/gateway.pid) url \$(cat run/gateway.url)"; exit 0
fi
c1=\$(getent hosts compute01 | awk '{print \$1; exit}')
IP=\$(ip -4 route get "\$c1" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "\$IP" ] || IP=\$(hostname -I | awk '{print \$1}')
if ss -ltn 2>/dev/null | awk '{print \$4}' | grep -q ":$GW_PORT\$"; then echo "port $GW_PORT busy" >&2; exit 1; fi
LOG=$GEM_DATA/gateway/gateway-\$(date +%Y%m%d-%H%M%S).log
setsid nohup nice -n 19 .venv/bin/python -m canary.gemini.gateway --host "\$IP" --port $GW_PORT \
  --key-file $GEM_CODE/.gateway.env --token-file $GEM_CODE/.gateway_token \
  --stats-dir $GEM_DATA/gateway --pidfile $GEM_CODE/run/gateway.pid $Q > "\$LOG" 2>&1 < /dev/null &
echo "http://\$IP:$GW_PORT" > run/gateway.url
for i in \$(seq 1 50); do curl -s -m 1 "http://\$IP:$GW_PORT/healthz" >/dev/null && break; sleep 0.2; done
curl -s -m 2 "http://\$IP:$GW_PORT/healthz"; echo
curl -s -o /dev/null -w 'no-token request -> HTTP %{http_code}\n' -X POST "http://\$IP:$GW_PORT/v1beta/models/x:generateContent"
# the key must not be visible in the process table (checked inside python: the key never goes on a command line)
if ! .venv/bin/python -c "import subprocess; from canary.gemini.gateway import load_key; from pathlib import Path; k=load_key(Path('.gateway.env')); raise SystemExit(k in subprocess.run(['ps','auxww'],capture_output=True,text=True).stdout)"; then
  echo "KEY VISIBLE IN ps: stopping" >&2; kill \$(cat run/gateway.pid); exit 1
fi
echo "ps check: key not on any command line"
echo "gateway up: pid \$(cat run/gateway.pid) url \$(cat run/gateway.url) log \$LOG"
REMOTE
