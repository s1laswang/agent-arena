# Judge runbook

Flags checked against harbor 0.25.0 source (`--path`, `--agent`, `--agent-import-path`, `--model`, `--n-attempts`). Verify with `harbor run --help` on the day.

Build the standard set (20 days, seat finance_ap; the same days under any seat with `--seat all`):

    python -m harbor.build --seeds 0..19 --seat finance_ap

This also writes `harbor/tasks-manifest.json` (secret salt and the lab day_id behind each task; keep it out of the repo and away from the agent).

The five judge runs, all on the same `harbor/tasks`:

1. Reference (scripted oracle through the real MCP tools, `solution/solve.sh`):

       harbor run -p harbor/tasks -a oracle

2. Three agent runs (OpenCode over MCP):

       harbor run -p harbor/tasks -a opencode -m <provider/model> --n-attempts 3

3. Do-nothing (Harbor's built-in nop agent, no tool call):

       harbor run -p harbor/tasks -a nop

4. Stop-early (calls `my_tickets` and `end_turn` once, then stops). Our `harbor/` package shadows Harbor's, so the agent lives outside it (harbor/opencode/judge_agents/stop_early.py, needs `capabilities = AgentCapabilities(mcp_servers=True)`):

       PYTHONPATH=harbor/opencode/judge_agents harbor run -p harbor/tasks --agent-import-path stop_early:StopEarlyAgent

All five in one go: `bash harbor/opencode/judge_runs.sh`.

Expected: reference 1 on winnable days, do-nothing 0, stop-early 0, agent runs below the reference. Rewards are in each trial's `/logs/verifier/reward.txt` and the job summary.

Without docker: `pytest tests/test_harbor.py`.
