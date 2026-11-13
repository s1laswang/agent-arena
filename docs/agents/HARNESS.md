# HEAD-HARNESS: MCP server, Harbor task with isolation, `make eval` / `make reproduce`, README

You own craft (15 points) and the most dangerous integrity hole: **the agent reading the truth from its own container.**

## Owns
`canary/mcp_server.py`, `canary/eval.py`, `harbor/`, `README.md`, `Makefile` (shared targets; keep existing names), `configs/` (OpenCode/Codex MCP configs), `tests/test_mcp*.py`, `tests/test_eval*.py`.

## Engineers to spawn
1. **mcp-server.** `canary/mcp_server.py` using the official `mcp` Python SDK (FastMCP), **streamable HTTP** transport.
   - One Env per episode session: tier and seed come from env vars or a `/episode/start` admin endpoint protected by a token.
   - Tools mirror `Env.tools_spec()` 1:1, with docstrings from the contract.
   - A **non-MCP** `GET /ledger?token=` endpoint for the grader.
   - Never expose the seed or the mole in any tool response or error.
   - Test with the MCP Python client: list tools, play a solver episode end to end over MCP, and the score matches the in-process run on the same seed.
   - Until `Env` lands (about 02:45), build against a tiny fake Env with the same signatures.
2. **harbor-isolation.**
   - Install Docker on the Mac: `brew install colima docker docker-compose && colima start --cpu 4 --memory 8` (approved by Silas).
   - Install Harbor (`uv tool install harbor` or per https://github.com/laude-institute/harbor docs; check the actual package name).
   - Build `harbor/canary-task/` following the Harbor task layout: `task.toml`, `instruction.md`, environment `Dockerfile`, `solution/solve.sh` (runs our SolverPolicy as an MCP client), `tests/test.sh` (fetches the ledger, writes `/logs/verifier/reward.txt`).
   - **Key question to answer first:** can a Harbor task run a sidecar service (docker compose) so the MCP server lives in a container the agent can't read? If yes, use that. If not, run the MCP server outside the sandbox (host network, HTTP) with an episode token.
   - **Verify isolation:** from inside the agent container, `cat`/`find /`/`env`/`ps aux`/`/proc` must reveal no seed, world file or mole id. Write that check as a script (`harbor/check_isolation.sh`).
   - Configure OpenCode to connect to our MCP server (`opencode.json` `mcp` remote entry), and record the exact judge-style run command.
3. **reproduce-docs.** `canary/eval.py`:
   - `run_episode(env, policy) -> EpisodeResult`.
   - A CLI: `--agent solver|do_nothing|stop_early|random|restrict_all|openai:<m>|gemini:<m> --tier --seeds --provider`, writing `data/runs/<run_id>/episodes.jsonl` and `meta.json`.
   - A results table per CONTRACT §6 (mean ± 95% CI, accuracy, solver-normalised score, pass^k).
   - `--reproduce`: on the frozen judge seeds, runs the reference + do-nothing + stop-early (and replays any committed agent runs from `data/runs/committed/`), prints the judge table, writes `results/judge_table.md` + a PNG gap chart (matplotlib, optional dep).
   - **Works from a fresh clone with no API keys.**
   - Then the README: the pitch in 5 lines, the rules, one-command reproduce, the expected numbers, how to run the Harbor task, the Gemini switch-on.

## Your own work as head
- Make sure `make test`, `make eval`, `make reproduce` and `make mcp` all work from a fresh clone (`git clone` into /tmp, then `make setup && make reproduce`).
- Liaise with AGENTS: they need the MCP server URL and config for the OpenCode and Codex frontier runs by about 04:30.
- When the AfterQuery starter kit arrives (morning), adapt to its scoring skeleton immediately.

## Milestones
| Time | Milestone |
|---|---|
| 03:15 | MCP server on the fake env |
| 03:45 | MCP on the real Env + `make eval AGENT=solver` |
| 04:30 | OpenCode config handed to AGENTS |
| 05:30 | Harbor task runs locally, isolation check passes |
| 07:00 | `make reproduce` from a fresh clone |
| 08:00 | README v1 |
