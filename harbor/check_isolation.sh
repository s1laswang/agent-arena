#!/bin/bash
# check_isolation.sh: run INSIDE the agent container (Harbor's `main` service). Exits non-zero on any finding.
#
# Asserts that nothing the agent can reach locally reveals the answer:
#   1. no files named *truth*, *SALT*, *ledger_key*, *.world.json, no canary package source (canary/*.py, a canary dist-info)
#   2. no CANARY_* variable at all in this env (CANARY_WORLD_SECRET / CANARY_LEDGER_TOKEN / CANARY_SEED /
#      CANARY_TIER / ...), and no readable /proc/*/environ containing CANARY_ (the Grok judge-sim exploit:
#      a same-uid process read the server's /proc/<pid>/environ and scored 1.0)
#   3. no game-server process visible in `ps` (no server pid at all), no host PID namespace
#   4. /proc shows nothing from the server (cmdline, environ), no docker socket, no bind mount of the repo
# Positive control (informational, plus one hard check): the server answers on the network, and
# GET /ledger without the token is refused (403).
#
# Usage: bash check_isolation.sh [--oracle-run] [--url http://canary-server:8765]
#   --oracle-run  skip /solution (the oracle's vendored solver, present only in `-a oracle` runs) and /logs.
set -u
ORACLE=0
BASE_URL="${ISOLATION_BASE_URL:-http://canary-server:8765}"
while [ $# -gt 0 ]; do
  case "$1" in
    --oracle-run) ORACLE=1 ;;
    --url) shift; BASE_URL="$1" ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

FINDINGS=0
CHECKS=0
finding() { FINDINGS=$((FINDINGS + 1)); echo "FINDING: $*"; }
ok() { CHECKS=$((CHECKS + 1)); echo "ok: $*"; }

PRUNE=(-path /proc -o -path /sys -o -path /dev)
if [ "$ORACLE" = 1 ]; then PRUNE+=(-o -path /solution -o -path /logs); fi

# ---------------------------------------------------------------- 1. files
hits="$(find / \( "${PRUNE[@]}" \) -prune -o \( -iname '*truth*' -o -name '*SALT*' -o -name '*ledger_key*' -o -name '*.world.json' \
        -o -name '*.mole.json' \) -print 2>/dev/null | head -n 50)"
if [ -n "$hits" ]; then finding "truth/secret-like files:"; echo "$hits" | sed 's/^/    /'; else ok "no *truth* / *SALT* / *ledger_key* / *.world.json / *.mole.json files"; fi

src="$(find / \( "${PRUNE[@]}" \) -prune -o \( -path '*/canary/mcp_server.py' -o -path '*/canary/world.py' \
       -o -path '*/canary/env.py' -o -path '*/canary/rules.py' -o -path '*/mole/dsl.py' -o -name 'canary-*.dist-info' \
       -o -name 'canary.egg-link' -o -name '__editable__*canary*' \) -print 2>/dev/null | head -n 50)"
if [ -n "$src" ]; then finding "canary source present:"; echo "$src" | sed 's/^/    /'; else ok "no canary package source / install"; fi

if command -v python3 >/dev/null 2>&1 && python3 -c 'import canary' >/dev/null 2>&1; then
  finding "python can import canary"
else
  ok "python cannot import canary"
fi

# ---------------------------------------------------------------- 2. environment
SECRET_RE='^CANARY_[A-Z0-9_]*='
if env | grep -Eq "$SECRET_RE"; then
  finding "CANARY_* env var(s) in this shell: $(env | grep -Eo '^CANARY_[A-Z0-9_]+' | sort -u | tr '\n' ' ')"
else
  ok "no CANARY_* variable (WORLD_SECRET / LEDGER_TOKEN / ADMIN_TOKEN / SEED / TIER) in env"
fi

# ---------------------------------------------------------------- 3. processes
if command -v ps >/dev/null 2>&1; then
  procs="$(ps -eo pid=,args= 2>/dev/null | grep -Ei 'canary[.]mcp_server|/opt/canary-server|uvicorn' | grep -v -e grep -e check_isolation)"
  if [ -n "$procs" ]; then finding "server-like process visible:"; echo "$procs" | sed 's/^/    /'; else ok "ps: no canary.mcp_server / uvicorn process ($(ps -e --no-headers | wc -l | tr -d ' ') processes visible)"; fi
else
  echo "note: ps not installed; relying on /proc scan"
fi

# ---------------------------------------------------------------- 4. /proc
self=$$
bad_cmd=""; bad_env=""; hostpid=""; nproc=0; nenv=0
for d in /proc/[0-9]*; do
  pid="${d#/proc/}"
  [ "$pid" = "$self" ] && continue
  cmd="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"
  case "$cmd" in *check_isolation*) continue ;; esac
  if printf '%s' "$cmd" | grep -Eqi 'canary[.]mcp_server|/opt/canary-server|uvicorn'; then bad_cmd="$bad_cmd $pid"; fi
  nproc=$((nproc + 1))
  if [ -r "$d/environ" ] && tr '\0' '\n' < "$d/environ" >/dev/null 2>&1; then nenv=$((nenv + 1)); fi
  if tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -Eq "$SECRET_RE"; then bad_env="$bad_env $pid"; fi
  if printf '%s' "$cmd" | grep -Eq '(^|/)(dockerd|containerd|containerd-shim[^ ]*|kubelet|launchd|systemd)( |$)'; then hostpid="$hostpid $pid"; fi
done
if [ -n "$bad_cmd" ]; then finding "/proc cmdline of server process(es):$bad_cmd"; else ok "/proc: no server cmdline"; fi
if [ -n "$bad_env" ]; then finding "readable /proc/<pid>/environ containing CANARY_ in pid(s):$bad_env"; else ok "/proc: no readable /proc/*/environ contains CANARY_ ($nproc pids scanned, $nenv environ readable)"; fi
if [ -n "$hostpid" ]; then finding "host PID namespace? host daemons visible in pid(s):$hostpid"; else ok "own PID namespace (no dockerd/containerd/kubelet/launchd/systemd visible)"; fi

if [ -S /var/run/docker.sock ] || [ -S /run/docker.sock ]; then finding "docker socket mounted (could exec into the sidecar)"; else ok "no docker socket"; fi

mounts="$(grep -Ei 'agent-arena|junction|/canary|worlds' /proc/self/mountinfo 2>/dev/null)"
if [ -n "$mounts" ]; then finding "suspicious bind mounts:"; echo "$mounts" | sed 's/^/    /'; else ok "no bind mount of the repo / worlds"; fi

# ---------------------------------------------------------------- positive control: network only
fetch() { # prints HTTP status code
  if command -v curl >/dev/null 2>&1; then curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1"
  else python3 -c "import sys,urllib.request,urllib.error
try: print(urllib.request.urlopen(sys.argv[1], timeout=5).status)
except urllib.error.HTTPError as e: print(e.code)
except Exception: print('000')" "$1"; fi
}
hz="$(fetch "$BASE_URL/healthz")"
echo "info: $BASE_URL/healthz -> HTTP $hz (the game is reachable over the network only)"
if [ "$hz" = "200" ]; then
  led="$(fetch "$BASE_URL/ledger")"; led2="$(fetch "$BASE_URL/ledger?token=guess")"
  if [ "$led" = "403" ] && [ "$led2" = "403" ]; then ok "GET /ledger without/with a wrong token -> 403"
  else finding "GET /ledger not refused (no token: $led, wrong token: $led2)"; fi
fi

echo "----"
if [ "$FINDINGS" -gt 0 ]; then echo "ISOLATION FAILED: $FINDINGS finding(s), $CHECKS check(s) passed"; exit 1; fi
echo "ISOLATION OK: $CHECKS checks passed, 0 findings"
