#!/bin/bash
# Oracle: play the reference Bayesian solver against the sidecar over MCP (the same wire the agent uses).
# Harbor copies solution/ to /solution only for `-a oracle` runs; the agent never sees it.
# The judges' baselines use the same path:  harbor run ... -a oracle --ae ORACLE_POLICY=do_nothing
#                                            harbor run ... -a oracle --ae ORACLE_POLICY=stop_early
# build.py vendors the canary package into solution/canary so the solver can run as an MCP client.
set -euo pipefail
URL="${MCP_URL:-http://canary-server:8765/mcp}"
AGENT="${ORACLE_POLICY:-solver}"   # solver | do_nothing | stop_early | any canary.baselines name
mkdir -p /logs/agent

# 1) Prove the container is clean before playing (the vendored /solution is expected in oracle runs only).
bash /solution/check_isolation.sh --oracle-run 2>&1 | tee /logs/agent/isolation.txt

# 2) Solver deps (pinned to uv.lock); the agent image ships none of them.
pip install --no-cache-dir -q "numpy==2.4.6" "pydantic==2.14.3" "python-dotenv==1.2.4" "mcp==2.3.0" 2>&1 | tail -n 2

# 3) Play.
cd /solution
echo "oracle agent: $AGENT"
if [ "$AGENT" = "cheat" ]; then   # INTEGRITY: out-of-band cheat attempts; must not earn reward (cheat.py)
  python /solution/cheat.py 2>&1 | tee /logs/agent/cheat.txt
  exit 0
fi
python -m canary.mcp_server --play "$AGENT" --url "$URL" 2>&1 | tee /logs/agent/solver.txt
