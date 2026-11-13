# Harbor tasks

Format checked against github.com/harbor-framework/terminal-bench-2 (task.toml, instruction.md, environment/Dockerfile, tests/test.sh, solution/solve.sh) and laude-institute/harbor `MCPServerConfig` (`[[environment.mcp_servers]]`, transport stdio).

Build tasks, one folder per (seed, seat):

    python -m harbor.build --seeds 0..19 --seat controller

Run the oracle, then an agent (needs docker and the harbor CLI):

    harbor run -p harbor/tasks --agent oracle
    harbor run -p harbor/tasks --agent opencode --model <model>

## Integrity design

Each task is a Harbor docker-compose environment (`environment/docker-compose.yaml`, same pattern as Harbor's tau3-bench adapter) with two containers:

- `main`: the agent's sandbox. Python plus the MCP client only. It holds no repo, no day spec, no state, no verifier.
- `sleeper-server`: sidecar built from `environment/runtime-server/`, runs the world, the other 7 seats and `sleeper.mcp_server` over streamable-http on :8000. State lives only in this container.

The agent reaches the world only through the seat's MCP tools. `tests/test.sh` (uploaded only at verify time) calls `GET sleeper-server:8001/reward` with a per-task random `X-Verify-Token`; the sidecar finalises the day, runs `python -m sleeper.verifier --state` on its own state and returns the Result. Reward 1 iff exit 0. The token exists only in `tests/` and in the compose file, neither of which is inside the agent's container. Any other request to :8001 gets 404.

Known limits for rw-exploit: the agent can open :8000 directly with any MCP client (same tools as its seat, fine); :8001 without the token is 404; `solution/` (oracle sources) is also hidden from the agent by Harbor.

Oracle: `solution/solve.sh` runs `harbor/oracle_client.py`, an MCP client playing the seat with `sleeper.scripted.OracleAgent` through the real tools until the day ends.

Check structure without docker: `pytest tests/test_harbor.py`. Local no-docker smoke: run `python -m harbor.sidecar` with SLEEPER_SEED, SLEEPER_SEAT, SLEEPER_OUT, VERIFY_TOKEN set, then `python harbor/oracle_client.py http://localhost:8000/mcp controller`, then curl :8001/reward with the token header (seed 0 controller gives reward 1).
