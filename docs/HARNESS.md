# Harness: Harbor + OpenCode over MCP

The judges run one seat (`SLEEPER_SEAT`, default `controller`) with OpenCode under Harbor. The other 7 seats run inside the env. Same verifier.

## Findings (checked 2026-11-14)

Harbor task folder ([tasks overview](https://docs.harborframework.com/tasks/overview)): `task.toml`, `instruction.md`, `environment/Dockerfile`, `solution/solve.sh`, `tests/test.sh`. `tests/test.sh` must write the reward to `/logs/verifier/reward.txt` (or `reward.json`).

`task.toml` ([configuration](https://docs.harborframework.com/tasks/configuration.md)), schema_version 1.4: `[task] name = "org/name"`, `[agent] timeout_sec`, `[verifier] timeout_sec, environment_mode ("shared"|"separate"), environment`, `[environment] docker_image, build_timeout_sec, env, workdir, healthcheck`, and MCP servers as `[[environment.mcp_servers]]` with `name`, `transport` ("stdio"|"sse"|"streamable-http"), `command`, `args` (stdio) or `url` (http).

Running OpenCode ([pre-integrated agents](https://docs.harborframework.com/agents/pre-integrated-agents.md)): agent name `opencode` (also `opencode-v2`), model `provider/model`, env with `--ae KEY=value`, `--ak skip_install=true` if the image has opencode:
`harbor run -p harbor/tasks/controller-1 -a opencode -m google/gemini-2.5-pro --ae GOOGLE_GENERATIVE_AI_API_KEY=$GEMINI_API_KEY`
(`-p` vs `-t`, and the Google key variable, are NOT verified: Harbor docs show only `-t` with an OpenAI key. Run `harbor run --help`. Harbor is not installed on this laptop.)

OpenCode config ([schema](https://opencode.ai/config.json), installed opencode v2.0.32): servers live under `mcp.servers.<name>` with `type: "local"`, `command: [..]`, `environment`, `cwd`, `disabled`; `{env:NAME}` substitution; model is top-level `"google/gemini-2.5-pro"`. Older opencode v1 used `mcp.<name>` with `enabled`; v2 rejects that layout. `opencode debug config` showed our file parses.

Gemini key: the Google provider normally reads `GOOGLE_GENERATIVE_AI_API_KEY` (unverified for v2).

## What we ship

- `harbor/opencode/opencode.json`: local stdio MCP `python -m sleeper.mcp_server --seat $SLEEPER_SEAT --day $SLEEPER_DAY`.
- `harbor/opencode/instruction.md.tmpl` + `seats.json`: plain seat job, no hint of who the sleeper is.
- `harbor/opencode/render.py`: `python -m harbor.opencode.render --seat controller --seeds 1 2 3` writes `harbor/tasks/<seat>-<seed>/` (task.toml with the mcp server, instruction.md) and copies `environment/ tests/ solution/` from `harbor/base/` if present (env-harbor owns those).
- `harbor/opencode/smoke.py`: no-Docker stdio MCP client. `python -m harbor.opencode.smoke --seat controller --day 1` against the real server, or `python -m harbor.opencode.smoke <cmd...>` for any server.
- `tests/test_opencode_seat.py`: render, config, smoke against a stub server.

## Status

Proven: render, config parse, MCP client round trip against a stub server. NOT yet proven: real `sleeper.mcp_server` (not on momin yet), `opencode run` against it (no Gemini key), `harbor run` (no Harbor install; Docker is present).
