# Harbor tasks

Format checked against github.com/harbor-framework/terminal-bench-2 (task.toml, instruction.md, environment/Dockerfile, tests/test.sh, solution/solve.sh) and laude-institute/harbor `MCPServerConfig` (`[[environment.mcp_servers]]`, transport stdio).

Build tasks, one folder per (seed, seat):

    python -m harbor.build --seeds 0..19 --seat controller

Run the oracle, then an agent (needs docker and the harbor CLI):

    harbor run -p harbor/tasks --agent oracle
    harbor run -p harbor/tasks --agent opencode --model <model>

Each task starts `sleeper.mcp_server` over stdio (env SLEEPER_SEED, SLEEPER_SEAT, SLEEPER_OUT). `tests/test.sh` runs `python -m sleeper.verifier --state $SLEEPER_OUT` and writes 0 or 1 to `/logs/verifier/reward.txt`.

Check structure without docker: `pytest tests/test_harbor.py`.
