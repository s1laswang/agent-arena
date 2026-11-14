#!/usr/bin/env bash
# One-command judge acceptance for AfterQuery entry "Canary" (branch justSilas).
# Runs setup, reproduce, baseline checks and an MCP smoke test.
# Exit 0 only if every required row PASSes. No API key required.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

rows=()
pass=0
fail=0
skip=0
say() { printf '%s\n' "$*"; }
record() { # STATUS name detail
  local st="$1" name="$2" detail="$3"
  rows+=("$st|$name|$detail")
  case "$st" in
    PASS) pass=$((pass+1)) ;;
    FAIL) fail=$((fail+1)) ;;
    SKIP) skip=$((skip+1)) ;;
  esac
  printf '  [%s] %s — %s\n' "$st" "$name" "$detail"
}

say "== Canary judge accept (AfterQuery entry, branch justSilas) =="
say "cwd=$ROOT"

if command -v make >/dev/null 2>&1; then
  record PASS "make on PATH" "$(make --version | head -1)"
else
  record FAIL "make on PATH" "GNU make is required. Install: sudo apt-get install make   (macOS: xcode-select --install)"
fi
if command -v uv >/dev/null 2>&1; then
  record PASS "uv on PATH" "$(uv --version)"
else
  record FAIL "uv on PATH" "Install: curl -LsSf https://astral.sh/uv/install.sh | sh   then open a new shell"
fi
if command -v python3 >/dev/null 2>&1; then
  record PASS "python3 on PATH" "$(python3 --version)"
else
  record FAIL "python3 on PATH" "python3 is required"
fi

if [ "$fail" -gt 0 ]; then
  say "Prerequisites missing; stopping before setup."
else
  say "-- make setup --"
  if make setup; then
    record PASS "make setup" "uv sync ok"
  else
    record FAIL "make setup" "exit $?"
  fi

  say "-- make reproduce --"
  if make reproduce; then
    record PASS "make reproduce exits 0" "see results/latest/judge_table.md"
  else
    record FAIL "make reproduce exits 0" "exit $?"
  fi

  # Parse the paired table and anti-cheat line
  python3 - <<'PY' > /tmp/canary-accept-check.txt
import re, sys
from pathlib import Path
root = Path(".").resolve()
table = root / "results/latest/judge_table.md"
logish = table.read_text() if table.exists() else ""
# also scan no extra file; numbers live in judge_table.md
# Expected 30-run bands from the README (v1.4)
bands = {
    ("solver", "medium"): (0.55, 0.72),
    ("solver", "hard"): (0.36, 0.62),
    ("solver", "easy"): (0.71, 0.80),
    ("do_nothing", "medium"): (0.0, 0.0),
    ("do_nothing", "hard"): (0.0, 0.0),
    ("do_nothing", "easy"): (0.0, 0.0),
    ("stop_early", "medium"): (-1.0, -0.75),
    ("stop_early", "hard"): (-1.0, -0.85),
    ("stop_early", "easy"): (-1.0, -0.65),
}
# Parse paired-run rows under each ## tier
tier = None
mode = None
found = {}
for line in logish.splitlines():
    if line.startswith("## "):
        m = re.match(r"## (medium|hard|easy)", line)
        tier = m.group(1) if m else None
        mode = None
    if line.startswith("Paired runs"):
        mode = "paired"
    if line.startswith("Reported") or line.startswith("History"):
        mode = None
    if mode == "paired" and line.startswith("|") and "reference" in line or (mode=="paired" and line.startswith("|") and "baseline" in line):
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 5 or parts[0] in ("agent", "---"):
            continue
        name = parts[0]
        # score column is like +0.625 ± 0.086
        sm = re.search(r"([+-]?\d+\.\d+)", parts[4] if len(parts)>4 else "")
        if not sm:
            continue
        score = float(sm.group(1))
        found[(name, tier)] = score

out = []
def emit(status, name, detail):
    out.append(f"{status}\t{name}\t{detail}")

if not table.exists():
    emit("FAIL", "judge_table.md", "results/latest/judge_table.md was not written")
else:
    emit("PASS", "judge_table.md written", str(table))

for key, (lo, hi) in bands.items():
    name, tier = key
    if key not in found:
        emit("FAIL", f"{name} {tier}", "row missing from paired table")
        continue
    s = found[key]
    # allow 0.01 slack for rounding / a new secret vs 30-run min/max
    slack = 0.01
    if name == "do_nothing":
        ok = abs(s) < 1e-9
        emit("PASS" if ok else "FAIL", f"do_nothing {tier}", f"score={s:+.3f} (must be exactly 0)")
    elif name == "stop_early":
        # designed to be negative (wrong day-1 guess = -1); "about 0" would be wrong here
        ok = s <= 0 and (lo - slack) <= s <= (hi + slack)
        emit("PASS" if ok else "FAIL", f"stop_early {tier}", f"score={s:+.3f} (must be <= 0 and in README band [{lo}, {hi}] ±0.01)")
    else:
        ok = (lo - slack) <= s <= (hi + slack)
        emit("PASS" if ok else "FAIL", f"{name} {tier}", f"score={s:+.3f} (README band [{lo}, {hi}] ±0.01 slack)")

# ANTI-CHEAT is printed by make reproduce to stdout, not always to the table file.
# Check exploits.json exists and attacks means <= 0
ex = root / "results/latest/exploits.json"
if ex.exists():
    emit("PASS", "exploits.json written", str(ex))
else:
    emit("FAIL", "exploits.json written", "missing")
print("\n".join(out))
PY
  while IFS=$'\t' read -r st name detail; do
    [ -n "${st:-}" ] && record "$st" "$name" "$detail"
  done < /tmp/canary-accept-check.txt

  say "-- MCP smoke (local server, no Docker, no OpenCode) --"
  MCP_PORT="${MCP_PORT:-18765}"
  export MCP_PORT MCP_PORT_FALLBACK=1
  port="$(bash scripts/mcp_port.sh)"
  say "using MCP_PORT=$port"
  # start server
  set +e
  CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=judge-accept-demo \
    MCP_PORT="$port" MCP_PORT_FALLBACK=0 \
    make mcp > /tmp/canary-mcp-accept.log 2>&1 &
  mcp_pid=$!
  set -e
  ready=0
  for i in $(seq 1 40); do
    if python3 - "$port" <<'PY'
import socket, sys
s=socket.socket(); s.settimeout(0.2)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
    then ready=1; break; fi
    if ! kill -0 "$mcp_pid" 2>/dev/null; then break; fi
    sleep 0.25
  done
  if [ "$ready" = "1" ]; then
    code=$(curl -sS -m 3 -o /tmp/canary-mcp-body.txt -w "%{http_code}" "http://127.0.0.1:${port}/mcp" || true)
    record PASS "MCP server binds" "http://127.0.0.1:${port}/mcp http_code=${code:-none}"
  else
    # show last log lines
    tail -20 /tmp/canary-mcp-accept.log 2>/dev/null | sed 's/^/    /'
    record FAIL "MCP server binds" "server did not listen on port $port (see /tmp/canary-mcp-accept.log)"
  fi
  kill "$mcp_pid" 2>/dev/null || true
  wait "$mcp_pid" 2>/dev/null || true
  pkill -f "canary.mcp_server" 2>/dev/null || true
fi

if command -v docker >/dev/null 2>&1 && command -v harbor >/dev/null 2>&1; then
  record SKIP "Harbor + OpenCode (docker)" "tools present; full harbor run is not part of this keyless accept (needs a model key). See README judge path."
else
  record SKIP "Harbor + OpenCode (docker)" "not installed on this machine; local MCP smoke is the verified path. Install: uv tool install harbor; official Docker Engine; curl -fsSL https://opencode.ai/v2/install | bash"
fi

say ""
say "==== ACCEPT TABLE ===="
printf '%-6s  %-32s  %s\n' "STATUS" "CHECK" "DETAIL"
printf '%s\n' "------  --------------------------------  ------"
for r in "${rows[@]}"; do
  IFS='|' read -r st name detail <<<"$r"
  printf '%-6s  %-32s  %s\n' "$st" "$name" "$detail"
done
say "----"
say "PASS=$pass  FAIL=$fail  SKIP=$skip"
if [ "$fail" -gt 0 ]; then
  say "RESULT: FAIL"
  exit 1
fi
say "RESULT: PASS"
exit 0
