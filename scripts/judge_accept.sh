#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) export PATH="${PATH}:${HOME}/.local/bin" ;;
esac
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/canary-accept.XXXXXX")"
mcp_pid=""
_descendants() { local c; for c in $(pgrep -P "$1" 2>/dev/null || true); do _descendants "$c"; echo "$c"; done; }
_cleanup_mcp() {
  if [ -n "${mcp_pid:-}" ]; then
    local _kids
    _kids=$(_descendants "$mcp_pid")
    kill $_kids "$mcp_pid" 2>/dev/null || true
    wait "$mcp_pid" 2>/dev/null || true
    mcp_pid=""
  fi
}
trap '_cleanup_mcp; rm -rf "$TMPD"' EXIT

rows=()
pass=0
fail=0
skip=0
say() { printf '%s\n' "$*"; }
record() {
  local st="$1" name="$2" detail="$3"
  rows+=("$st|$name|$detail")
  case "$st" in
    PASS) pass=$((pass+1)) ;;
    FAIL) fail=$((fail+1)) ;;
    SKIP) skip=$((skip+1)) ;;
  esac
  printf '  [%s] %s - %s\n' "$st" "$name" "$detail"
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
  need_cmp=0
  need_diff=0
  command -v cmp >/dev/null 2>&1 || need_cmp=1
  command -v diff >/dev/null 2>&1 || need_diff=1
  if [ "$need_cmp" = "1" ] || [ "$need_diff" = "1" ]; then
    mkdir -p "$TMPD/shim-bin"
    python3 - "$TMPD/shim-bin" "$need_cmp" "$need_diff" <<'PY'
import sys, textwrap
from pathlib import Path

shim_dir = Path(sys.argv[1])
need_cmp = sys.argv[2] == "1"
need_diff = sys.argv[3] == "1"
shebang = chr(35) + "!/usr/bin/env python3\n"

if need_cmp:
    cmp_path = shim_dir / "cmp"
    cmp_path.write_text(
        shebang + textwrap.dedent("""\
        import sys
        from pathlib import Path

        quiet = False
        files = []
        end_opts = False
        for arg in sys.argv[1:]:
            if not end_opts and arg == "--":
                end_opts = True
            elif not end_opts and arg in ("-s", "--quiet", "--silent"):
                quiet = True
            elif not end_opts and arg.startswith("-") and arg != "-":
                if not quiet:
                    sys.stderr.write(f"cmp: unsupported option: {arg}\\n")
                sys.exit(2)
            else:
                files.append(arg)
        if len(files) != 2:
            if not quiet:
                sys.stderr.write("cmp: expected two file operands\\n")
            sys.exit(2)
        def _read(p):
            return sys.stdin.buffer.read() if p == "-" else Path(p).read_bytes()
        try:
            b1 = _read(files[0])
            b2 = _read(files[1])
        except OSError as exc:
            if not quiet:
                sys.stderr.write(f"cmp: {exc}\\n")
            sys.exit(2)
        if b1 == b2:
            sys.exit(0)
        if not quiet:
            lim = min(len(b1), len(b2))
            idx = next((i for i in range(lim) if b1[i] != b2[i]), lim)
            line_no = b1[:idx].count(b"\\n") + 1
            sys.stdout.write(f"{files[0]} {files[1]} differ: byte {idx + 1}, line {line_no}\\n")
        sys.exit(1)
        """),
        encoding="utf-8",
    )
    cmp_path.chmod(0o755)

if need_diff:
    diff_path = shim_dir / "diff"
    diff_path.write_text(
        shebang + textwrap.dedent("""\
        import difflib, sys
        from pathlib import Path

        brief = False
        files = []
        end_opts = False
        for arg in sys.argv[1:]:
            if not end_opts and arg == "--":
                end_opts = True
            elif not end_opts and arg in ("-q", "--brief"):
                brief = True
            elif not end_opts and (arg in ("-u", "--unified", "-a", "--text") or arg.startswith("-U")):
                continue
            elif not end_opts and arg.startswith("-") and arg != "-":
                sys.stderr.write(f"diff: unsupported option: {arg}\\n")
                sys.exit(2)
            else:
                files.append(arg)
        if len(files) != 2:
            sys.stderr.write("diff: expected two file operands\\n")
            sys.exit(2)
        def _read(p):
            return sys.stdin.buffer.read() if p == "-" else Path(p).read_bytes()
        try:
            b1 = _read(files[0])
            b2 = _read(files[1])
        except OSError as exc:
            sys.stderr.write(f"diff: {exc}\\n")
            sys.exit(2)
        if b1 == b2:
            sys.exit(0)
        try:
            if brief:
                sys.stdout.write(f"Files {files[0]} and {files[1]} differ\\n")
            else:
                l1 = b1.decode("utf-8", errors="replace").splitlines(keepends=True)
                l2 = b2.decode("utf-8", errors="replace").splitlines(keepends=True)
                out = list(difflib.unified_diff(l1, l2, fromfile=files[0], tofile=files[1]))
                if out:
                    for line in out:
                        sys.stdout.write(line if line.endswith("\\n") else line + "\\n")
                else:
                    sys.stdout.write(f"Binary files {files[0]} and {files[1]} differ\\n")
            sys.stdout.flush()
        except BrokenPipeError:
            pass
        sys.exit(1)
        """),
        encoding="utf-8",
    )
    diff_path.chmod(0o755)
PY
    export PATH="$TMPD/shim-bin:$PATH"
  fi

  say "-- make setup --"
  if make setup; then
    record PASS "make setup" "uv sync ok"
  else
    record FAIL "make setup" "exit $?"
  fi

  say "-- make reproduce --"
  reuse_age=""
  if [ "${ACCEPT_FORCE_REPRODUCE:-0}" != "1" ] \
    && [ -s "results/latest/judge_table.md" ] \
    && [ -s "results/latest/exploits.json" ] \
    && [ -s "results/latest/paired_table_gemini.md" ] \
    && [ -s "data/runs/committed/v1.4/paired_table_gemini.md" ] \
    && { ! command -v cmp >/dev/null 2>&1 || cmp -s "results/latest/paired_table_gemini.md" "data/runs/committed/v1.4/paired_table_gemini.md"; }; then
    reuse_age="$(ACCEPT_REUSE_MAX_AGE_S="${ACCEPT_REUSE_MAX_AGE_S:-900}" python3 - <<'PY' || true
import json, os, re, sys, time
from pathlib import Path

root = Path(".").resolve()
jt = root / "results/latest/judge_table.md"
ex = root / "results/latest/exploits.json"
pt = root / "results/latest/paired_table_gemini.md"
rules_py = root / "canary/rules.py"
committed_ex = root / "results/anticheat/exploits.json"
committed_pt = root / "data/runs/committed/v1.4/paired_table_gemini.md"

for req in (jt, ex, pt, rules_py, committed_ex, committed_pt):
    if not req.is_file() or req.stat().st_size <= 0:
        sys.exit(1)

try:
    max_age = float(os.environ.get("ACCEPT_REUSE_MAX_AGE_S", "900"))
except ValueError:
    sys.exit(1)

jt_mtime = jt.stat().st_mtime
age = time.time() - jt_mtime
if max_age <= 0 or age > max_age or age < -5.0:
    sys.exit(1)
if jt_mtime < rules_py.stat().st_mtime or jt_mtime < committed_ex.stat().st_mtime:
    sys.exit(1)
if pt.read_bytes() != committed_pt.read_bytes():
    sys.exit(1)

try:
    ex_data = json.loads(ex.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)
if not isinstance(ex_data, dict):
    sys.exit(1)
if not (
    ex_data.get("all_blocked") is True
    and ex_data.get("replay_all_consistent") is True
    and ex_data.get("harbor_all_consistent") is True
):
    sys.exit(1)

jt_text = jt.read_text(encoding="utf-8")
h2 = chr(35) * 2
for tier_name in ("easy", "medium", "hard"):
    if re.search(rf"^{h2} {tier_name}\b", jt_text, re.M) is None:
        sys.exit(1)

print(int(max(0.0, age)))
PY
)"
  fi
  if [ -n "$reuse_age" ]; then
    say "reusing fresh results/latest/judge_table.md (${reuse_age}s old; set ACCEPT_FORCE_REPRODUCE=1 to rerun)"
    record PASS "make reproduce exits 0" "reused fresh results/latest/judge_table.md (${reuse_age}s old; set ACCEPT_FORCE_REPRODUCE=1 to rerun)"
  else
    if make reproduce; then
      record PASS "make reproduce exits 0" "see results/latest/judge_table.md"
    else
      record FAIL "make reproduce exits 0" "exit $?"
    fi
  fi

  python3 - <<'PY' > "$TMPD/check.txt"
import json, re
from pathlib import Path

root = Path(".").resolve()
table = root / "results/latest/judge_table.md"
logish = table.read_text(encoding="utf-8") if table.exists() else ""
K_SD = 4.0
bands = {}
band_src = {}
for name in ("solver", "guess_day1"):
    for t in ("medium", "hard", "easy"):
        f = root / "results" / "solver_range" / f"{name}_{t}_judge40.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            bands[(name, t)] = (d["mean"] - K_SD * d["sd"], d["mean"] + K_SD * d["sd"])
            band_src[(name, t)] = f"{f.relative_to(root)}: mean {d['mean']:+.3f}, sd {d['sd']:.3f}, {d['builds']} secrets"
        elif name == "solver":
            bands[(name, t)] = (0.25, 0.90)
            band_src[(name, t)] = f"fallback band; {f.relative_to(root)} not committed yet"
        else:
            bands[(name, t)] = None
            band_src[(name, t)] = f"missing {f.relative_to(root)}"
for name in ("do_nothing", "stop_early"):
    for t in ("medium", "hard", "easy"):
        bands[(name, t)] = (0.0, 0.0)

h2 = chr(35) * 2
tier = None
mode = None
found = {}
for line in logish.splitlines():
    if line.startswith(f"{h2} "):
        m = re.match(rf"{h2} (medium|hard|easy)\b", line)
        tier = m.group(1) if m else None
        mode = None
    if line.startswith("Paired runs"):
        mode = "paired"
    if line.startswith("Reported") or line.startswith("History"):
        mode = None
    if mode == "paired" and line.startswith("|") and ("reference" in line or "baseline" in line):
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 5 or parts[0] in ("agent", "---"):
            continue
        name = parts[0]
        sm = re.search(r"([+-]?\d+\.\d+)", parts[4] if len(parts) > 4 else "")
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

for key, band in bands.items():
    name, tier = key
    if key not in found:
        emit("FAIL", f"{name} {tier}", "row missing from paired table")
        continue
    s = found[key]
    if name in ("do_nothing", "stop_early"):
        ok = abs(s) < 1e-9
        why = "never accuses" if name == "do_nothing" else "day-1 stop, no accusation"
        emit("PASS" if ok else "FAIL", f"{name} {tier}", f"score={s:+.3f} (must be exactly 0: {why})")
        continue
    if band is None:
        emit("FAIL", f"{name} {tier}", f"score={s:+.3f}; no expected band ({band_src[key]})")
        continue
    lo, hi = band
    ok = lo <= s <= hi and (name != "guess_day1" or s <= 0)
    extra = " and <= 0" if name == "guess_day1" else ""
    emit("PASS" if ok else "FAIL", f"{name} {tier}",
         f"score={s:+.3f} (expected [{lo:+.2f}, {hi:+.2f}]{extra}; {band_src[key]})")

ex = root / "results/latest/exploits.json"
if ex.exists():
    try:
        ex_obj = json.loads(ex.read_text(encoding="utf-8"))
    except Exception:
        ex_obj = None
    if isinstance(ex_obj, dict) and ex_obj.get("all_blocked") is True:
        emit("PASS", "exploits.json written", str(ex))
    else:
        emit("FAIL", "exploits.json written", f"{ex}: all_blocked is not True")
else:
    emit("FAIL", "exploits.json written", "missing")
print("\n".join(out))
PY
  while IFS=$'\t' read -r st name detail; do
    [ -n "${st:-}" ] && record "$st" "$name" "$detail"
  done < "$TMPD/check.txt"

  say "-- MCP smoke (local server, no Docker, no OpenCode) --"
  MCP_PORT="${MCP_PORT:-18765}"
  export MCP_PORT MCP_PORT_FALLBACK=1
  port="$(bash scripts/mcp_port.sh)"
  say "using MCP_PORT=$port"
  set +e
  CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=judge-accept-demo \
    MCP_PORT="$port" MCP_PORT_FALLBACK=0 \
    make mcp > "$TMPD/mcp.log" 2>&1 &
  mcp_pid=$!
  set -e
  ready=0
  for i in $(seq 1 100); do
    if python3 - "$port" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.2)
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
    sleep 0.1
  done
  if [ "$ready" = "1" ]; then
    init_req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"judge-accept","version":"1.0"}}}'
    init_code=$(curl -sS -m 5 -X POST \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -d "$init_req" \
      -o "$TMPD/mcp-body.txt" -w "%{http_code}" \
      "http://127.0.0.1:${port}/mcp" || true)
    ledger_ok_code=$(curl -sS -m 5 \
      -o "$TMPD/ledger-ok.txt" -w "%{http_code}" \
      "http://127.0.0.1:${port}/ledger?token=judge-accept-demo" || true)
    ledger_unauth_code=$(curl -sS -m 5 \
      -o "$TMPD/ledger-unauth.txt" -w "%{http_code}" \
      "http://127.0.0.1:${port}/ledger" || true)
    if mcp_err="$(python3 - "$TMPD" "${init_code:-}" "${ledger_ok_code:-}" "${ledger_unauth_code:-}" <<'PY'
import json, sys
from pathlib import Path

tmpd = Path(sys.argv[1])
init_code, ledger_ok_code, ledger_unauth_code = sys.argv[2], sys.argv[3], sys.argv[4]
problems = []

if init_code != "200":
    problems.append(f"initialize={init_code or 'none'} (expected 200)")
else:
    raw = (tmpd / "mcp-body.txt").read_text(encoding="utf-8", errors="replace") if (tmpd / "mcp-body.txt").is_file() else ""
    msg = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            cand = line[5:].strip()
            if cand:
                try:
                    obj = json.loads(cand)
                    if isinstance(obj, dict) and obj.get("id") == 1:
                        msg = obj
                        break
                except Exception:
                    pass
    if msg is None and raw.strip():
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                msg = obj
        except Exception:
            pass
    res = msg.get("result") if isinstance(msg, dict) else None
    if not isinstance(res, dict) or "serverInfo" not in res or "protocolVersion" not in res:
        problems.append("initialize missing serverInfo/protocolVersion")

if ledger_ok_code != "200":
    problems.append(f"/ledger token={ledger_ok_code or 'none'} (expected 200)")
else:
    lraw = (tmpd / "ledger-ok.txt").read_text(encoding="utf-8", errors="replace") if (tmpd / "ledger-ok.txt").is_file() else ""
    try:
        lobj = json.loads(lraw)
        if not isinstance(lobj, dict):
            problems.append("/ledger token body is not a JSON object")
    except Exception:
        problems.append("/ledger token body is invalid JSON")

if ledger_unauth_code != "403":
    problems.append(f"/ledger unauth={ledger_unauth_code or 'none'} (expected 403)")

if problems:
    print("; ".join(problems))
    sys.exit(1)
PY
    )"; then
      record PASS "MCP server binds" "http://127.0.0.1:${port}/mcp JSON-RPC initialize=200, /ledger token=200 unauth=403"
    else
      tail -20 "$TMPD/mcp.log" 2>/dev/null | sed 's/^/    /' || true
      record FAIL "MCP server binds" "http://127.0.0.1:${port}/mcp ${mcp_err:-MCP smoke check failed}"
    fi
  else
    tail -20 "$TMPD/mcp.log" 2>/dev/null | sed 's/^/    /' || true
    record FAIL "MCP server binds" "server did not listen on port $port (log tail above)"
  fi
  _cleanup_mcp
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
