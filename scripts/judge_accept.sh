#!/usr/bin/env bash
# One-command judge acceptance for AfterQuery entry "The Sleeper" (branch momin).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

rows=(); pass=0; fail=0; skip=0
record() {
  local st="$1" name="$2" detail="$3"
  rows+=("$st|$name|$detail")
  case "$st" in PASS) pass=$((pass+1));; FAIL) fail=$((fail+1));; SKIP) skip=$((skip+1));; esac
  printf '  [%s] %s — %s\n' "$st" "$name" "$detail"
}
say() { printf '%s\n' "$*"; }

say "== Sleeper judge accept (AfterQuery entry, branch momin) =="
say "cwd=$ROOT"

if command -v make >/dev/null 2>&1; then
  record PASS "make on PATH" "$(make --version | head -1)"
else
  record FAIL "make on PATH" "GNU make is required. sudo apt-get install make  (macOS: xcode-select --install)"
fi
if command -v python3.13 >/dev/null 2>&1; then
  record PASS "python3.13 on PATH" "$(python3.13 --version)"
elif command -v python3 >/dev/null 2>&1; then
  record FAIL "python3.13 on PATH" "found $(python3 --version) but this README requires python3.13"
else
  record FAIL "python3.13 on PATH" "python3.13 is required"
fi

if [ "$fail" -gt 0 ]; then
  say "Prerequisites missing; stopping before setup."
else
  say "-- make setup --"
  if make setup; then
    record PASS "make setup" ".venv ready"
  else
    record FAIL "make setup" "exit $?"
  fi

  say "-- make reproduce --"
  if make reproduce; then
    record PASS "make reproduce exits 0" "see results/eval/gap.md"
  else
    record FAIL "make reproduce exits 0" "exit $?"
  fi

  python3 - <<'PY' > /tmp/sleeper-accept-check.txt
from pathlib import Path
import re
root = Path(".").resolve()
gap = root / "results/eval/gap.md"
out = []
def emit(s, n, d):
    out.append(f"{s}\t{n}\t{d}")
if not gap.exists():
    emit("FAIL", "gap.md", "results/eval/gap.md was not written")
    print("\n".join(out))
    raise SystemExit
text = gap.read_text()
want = {
    "oracle": 1.000,
    "reference": 0.650,
    "staff": 0.250,
    "do_nothing": 0.000,
    "stop_early": 0.000,
    "quarantine_all": 0.000,
    "refuse_all": 0.000,
    "trust_all": 0.000,
}
section = text.split("## Procedure")[0] if "## Procedure" in text else text
for team, expected in want.items():
    m = re.search(rf"^\| {re.escape(team)} \|[^|]*\|[^|]*\|[^|]*\| ([0-9.]+) \|", section, re.M)
    if not m:
        emit("FAIL", f"{team} reward", "row missing from headline table")
        continue
    got = float(m.group(1))
    ok = abs(got - expected) < 1e-9
    emit("PASS" if ok else "FAIL", f"{team} reward", f"score={got:.3f} (README claims {expected:.3f})")
print("\n".join(out))
PY
  while IFS=$'\t' read -r st name detail; do
    [ -n "${st:-}" ] && record "$st" "$name" "$detail"
  done < /tmp/sleeper-accept-check.txt

  say "-- baseline rerun (do_nothing / stop_early, day-start 1000) --"
  if .venv/bin/python -m lab.run --team do_nothing --days 20 --seeds 3 --day-start 1000 > /tmp/sleeper-dn.txt 2>&1; then
    if python3 -c "import sys,re; t=open('/tmp/sleeper-dn.txt').read(); m=re.search(r'\"reward_mean\": ([0-9.]+)', t); sys.exit(0 if m and float(m.group(1))==0 else 1)"; then
      record PASS "do_nothing rerun" "reward_mean=0.0 (day-start 1000)"
    else
      record FAIL "do_nothing rerun" "reward was not 0 (see /tmp/sleeper-dn.txt)"
    fi
  else
    record FAIL "do_nothing rerun" "lab.run failed"
  fi
  if .venv/bin/python -m lab.run --team stop_early --days 20 --seeds 3 --day-start 1000 > /tmp/sleeper-se.txt 2>&1; then
    if python3 -c "import sys,re; t=open('/tmp/sleeper-se.txt').read(); m=re.search(r'\"reward_mean\": ([0-9.]+)', t); sys.exit(0 if m and float(m.group(1))==0 else 1)"; then
      record PASS "stop_early rerun" "reward_mean=0.0 (day-start 1000)"
    else
      record FAIL "stop_early rerun" "reward was not 0 (see /tmp/sleeper-se.txt)"
    fi
  else
    record FAIL "stop_early rerun" "lab.run failed"
  fi

  say "-- MCP smoke (stdio, no Docker) --"
  if PYTHONPATH=. .venv/bin/python -m harbor.opencode.smoke --seat finance_ap --day 1000 > /tmp/sleeper-mcp-smoke.txt 2>&1; then
    record PASS "MCP stdio smoke" "harbor.opencode.smoke --seat finance_ap --day 1000"
  else
    tail -20 /tmp/sleeper-mcp-smoke.txt | sed 's/^/    /'
    record FAIL "MCP stdio smoke" "see /tmp/sleeper-mcp-smoke.txt"
  fi
fi

if command -v docker >/dev/null 2>&1 && command -v harbor >/dev/null 2>&1; then
  record SKIP "Harbor + OpenCode (docker)" "tools present; full harbor run is not part of this keyless accept"
else
  record SKIP "Harbor + OpenCode (docker)" "not installed; stdio MCP smoke is the verified path. Install: uv tool install harbor; Docker Engine; curl -fsSL https://opencode.ai/v2/install | bash"
fi

say ""
say "==== ACCEPT TABLE ===="
printf '%-6s  %-32s  %s\n' "STATUS" "CHECK" "DETAIL"
for r in "${rows[@]}"; do
  IFS='|' read -r st name detail <<<"$r"
  printf '%-6s  %-32s  %s\n' "$st" "$name" "$detail"
done
say "PASS=$pass  FAIL=$fail  SKIP=$skip"
if [ "$fail" -gt 0 ]; then
  say "RESULT: FAIL"
  exit 1
fi
say "RESULT: PASS"
exit 0
