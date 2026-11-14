#!/usr/bin/env bash
# FALLBACK when the gateway may not run on the login node: run it on the Mac and expose it to FR8 with ssh -R.
#   bash fr8/gemini/tunnel_up.sh            # start: Mac gateway + reverse tunnel + login-node TCP relay
#   bash fr8/gemini/tunnel_up.sh --down     # stop all three
# Works only while the Mac is awake and online. The key stays on the Mac; the token is copied FR8 -> Mac (0600).
# sshd binds -R forwards to the login node's loopback (GatewayPorts no), so a stdlib byte relay
# (canary.gemini.tcprelay, no key, no auth of its own) exposes it on the cluster-internal address for compute nodes.
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$REPO_ROOT"
LPORT=${LPORT:-18787}; RPORT=${RPORT:-18787}
RUN=data/gemini/tunnel; mkdir -p "$RUN"
if [ "${1-}" = "--down" ]; then
  [ -f "$RUN/ssh.pid" ] && kill "$(cat $RUN/ssh.pid)" 2>/dev/null && echo "tunnel stopped" || true
  [ -f "$RUN/gateway.pid" ] && kill "$(cat $RUN/gateway.pid)" 2>/dev/null && echo "mac gateway stopped" || true
  rm -f "$RUN/ssh.pid"
  ssh "$FR8_HOST" "cd $GEM_CODE && [ -f run/tcprelay.pid ] && kill \$(cat run/tcprelay.pid) 2>/dev/null; rm -f run/tcprelay.pid run/gateway.url; echo 'fr8 relay stopped'"
  exit 0
fi
# 1) token: the one the FR8 workers read, copied to a 0600 local file
(umask 077; ssh "$FR8_HOST" "cat $GEM_CODE/.gateway_token" > "$RUN/token")
# 2) Mac gateway (live, key from .env, niced, self-exit)
if ! { [ -f "$RUN/gateway.pid" ] && kill -0 "$(cat $RUN/gateway.pid)" 2>/dev/null; }; then
  nohup nice -n 10 uv run --python 3.12 --extra llm python -m canary.gemini.gateway --host 127.0.0.1 --port "$LPORT" \
    --token-file "$RUN/token" --max-hours 8 --max-concurrency 64 --model-limit gemini-4-carbon=8 \
    --pidfile "$RUN/gateway.pid" > "$RUN/gateway.log" 2>&1 &
  for i in $(seq 1 50); do curl -s -m 1 "http://127.0.0.1:$LPORT/healthz" >/dev/null && break; sleep 0.2; done
fi
curl -sf "http://127.0.0.1:$LPORT/healthz" >/dev/null || { echo "mac gateway failed; see $RUN/gateway.log" >&2; exit 1; }
# 3) reverse tunnel: login-node 127.0.0.1:RPORT -> Mac 127.0.0.1:LPORT
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -R "127.0.0.1:$RPORT:127.0.0.1:$LPORT" "$FR8_HOST"
pgrep -f "ssh -f -N .*-R 127.0.0.1:$RPORT:127.0.0.1:$LPORT" | head -1 > "$RUN/ssh.pid"
# 4) login-node relay on the cluster-internal address -> loopback tunnel end
ssh "$FR8_HOST" "bash -s" <<REMOTE
set -euo pipefail
cd $GEM_CODE; mkdir -p run
c1=\$(getent hosts compute01 | awk '{print \$1; exit}')
IP=\$(ip -4 route get "\$c1" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -f run/tcprelay.pid ] && kill \$(cat run/tcprelay.pid) 2>/dev/null || true
setsid nohup nice -n 19 .venv/bin/python -m canary.gemini.tcprelay --listen "\$IP:$GW_PORT" --to "127.0.0.1:$RPORT" \
  --max-hours 8 > $GEM_DATA/gateway/tcprelay.log 2>&1 < /dev/null &
echo \$! > run/tcprelay.pid
echo "http://\$IP:$GW_PORT" > run/gateway.url
sleep 1; curl -s -m 3 "http://\$IP:$GW_PORT/healthz"; echo
echo "tunnel up: workers use \$(cat run/gateway.url) (Mac gateway via ssh -R)"
REMOTE
