#!/bin/bash
set -u
cd "$(dirname "$0")/.."
SEAT=${1:?seat}; DAY=${2:?day}; CLIENT=${3:?claude|codex}
O=${OUT:-out/cli}/$CLIENT-$DAY
PY=${PY:-$PWD/.venv/bin/python}
TO=${TIMEOUT:-1500}
rm -rf "$O"; mkdir -p "$O"; O=$(cd "$O" && pwd)
S=$O/state.json
PROMPT=$(PYTHONPATH=$PWD $PY -c "from harbor.opencode.instruction import seat_instruction as f; print(f('$SEAT'))")
PROMPT="$PROMPT

Use the sleeper MCP tools to do your seat's work for the day. Keep calling tools until a tool says the day is over."
ARGS="[\"-m\",\"sleeper.mcp_server\",\"--seat\",\"$SEAT\",\"--day\",\"$DAY\",\"--out\",\"$S\"]"
run() { perl -e 'alarm shift; exec @ARGV' "$TO" "$@"; }
case $CLIENT in
  claude)
    cat >"$O/mcp.json" <<J
{"mcpServers":{"sleeper":{"command":"$PY","args":$ARGS,"env":{"PYTHONPATH":"$PWD","SLEEPER_SEAT":"$SEAT"}}}}
J
    run claude -p "$PROMPT" --mcp-config "$O/mcp.json" --strict-mcp-config --allowedTools "mcp__sleeper__*" \
      --output-format stream-json --verbose >"$O/transcript" 2>"$O/stderr";;
  codex)
    run codex exec --json --skip-git-repo-check -s read-only \
      -c "mcp_servers.sleeper.command=\"$PY\"" -c "mcp_servers.sleeper.args=$ARGS" \
      -c "mcp_servers.sleeper.env={PYTHONPATH=\"$PWD\",SLEEPER_SEAT=\"$SEAT\"}" \
      -c 'mcp_servers.sleeper.default_tools_approval_mode="approve"' \
      "$PROMPT" >"$O/transcript" 2>"$O/stderr";;
  *) echo "client must be claude or codex"; exit 2;;
esac
sleep 2
SLEEPER_SEAT=$SEAT PYTHONPATH=$PWD $PY -m sleeper.verifier --require-seat --state "$S" >"$O/reward.json"
cat "$O/reward.json"
