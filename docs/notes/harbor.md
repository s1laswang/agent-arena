# Harbor notes (for packaging Poisoned Inbox as Harbor tasks)

Researched Sat 14 Nov 2026, ~02:00. Everything below comes from Harbor's own README, docs and
source code unless it says **UNVERIFIED** or **OUR PROPOSAL**.

- Repo: `github.com/laude-institute/harbor` now redirects to **github.com/harbor-framework/harbor**.
- Versions checked: PyPI stable **0.25.0** (25 Oct 2026, tag `v0.25.0`) and `main` at commit
  `f9c47b1` (13 Nov 2026). The parts we need (task.toml schema, MCP config, verifier, OpenCode
  MCP wiring, paths) are the same in both. Harbor needs **Python >= 3.12** and **Docker**.
- Docs site: https://harborframework.com/docs (source lives in the repo under `docs-mintlify/`).

## 1. Task folder format

```
my-task/
  task.toml            # config (required)
  instruction.md       # the prompt the agent gets (required)
  environment/         # Dockerfile, plus optional docker-compose.yaml for sidecars
  solution/solve.sh    # used only by the "oracle" agent (optional)
  tests/test.sh        # verifier entry point; must write the reward (required)
  tests/Dockerfile     # optional: own image for a "separate" verifier
```

Source: `src/harbor/models/task/paths.py`, docs `tasks/overview.mdx`.

### task.toml (all fields we may need)

```toml
schema_version = "1.4"          # older "version = ..." is still accepted
artifacts = [                    # MUST sit above the first [section]
  { source = "/srv/episode/state.json", service = "pinbox-env" },
]

[task]                           # optional; if present, name is required
name = "northwind/ap-run-s7-d2"  # must be "org/name"
description = "..."
authors = [{ name = "Team", email = "x@y.z" }]
keywords = ["mcp"]

[metadata]                       # free-form; Harbor does not read it
family = "ap_run"

[agent]
timeout_sec = 1800.0             # default: none (no timeout)
# user = "agent"                 # optional OS user for the agent
# network_mode = "public"        # optional override during agent.run() only

[verifier]
timeout_sec = 300.0              # default 600
environment_mode = "separate"    # "shared" (default if nothing set) or "separate"
env = { }                        # env vars for test.sh; ${VAR} reads the host

[[verifier.collect]]             # runs AFTER the agent, inside a compose service
service = "pinbox-env"
command = "python -m pinbox ... > /srv/episode/grade.json"
timeout_sec = 60.0

[environment]
build_timeout_sec = 600.0        # default 600
cpus = 1
memory_mb = 2048
storage_mb = 10240
# docker_image = "org/img:tag"   # prebuilt image instead of environment/Dockerfile
# network_mode = "public"        # "public" (default) | "no-network" | "allowlist"
# workdir = "/app"
env = { }                        # ${VAR} and ${VAR:-default} from the host

[environment.healthcheck]        # optional; runs in main before agent setup
command = "curl -sf http://pinbox-env:8000/health"
interval_sec = 2.0
retries = 15

[[environment.mcp_servers]]      # see section 2
name = "pinbox"
transport = "streamable-http"
url = "http://pinbox-env:8000/mcp"

[solution]
env = { }                        # env vars for solve.sh (wins over --ae)
```

Source: `src/harbor/models/task/config.py` (classes `TaskConfig`, `EnvironmentConfig`,
`VerifierConfig`, `VerifierCollectConfig`, `MCPServerConfig`), docs `tasks/configuration.mdx`.

### environment/ and multi-container (sidecars)

- `environment/Dockerfile` builds the agent container. Build context = the `environment/` folder.
- `environment/docker-compose.yaml` **is supported**. Harbor merges it on top of its own base file.
  The agent container is the compose service **`main`** (reserved name, constant
  `MAIN_SERVICE_NAME = "main"`). All other services are sidecars on the same Docker network,
  reachable by service name (e.g. `http://pinbox-env:8000`).
- Harbor's base compose (`src/harbor/environments/docker/docker-compose-build.yaml`):
  ```yaml
  services:
    main:
      build: { context: ${CONTEXT_DIR} }
      pull_policy: build
      command: [ "sh", "-c", "sleep infinity" ]
  ```
  So you only add sidecars and `main` overrides. Official example (`examples/tasks/hello-mcp`):
  ```yaml
  services:
    main:
      depends_on:
        mcp-server:
          condition: service_healthy
    mcp-server:
      build:
        context: ./mcp-server
      expose:
        - "8000"
      healthcheck:
        test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('localhost',8000),timeout=2); s.close()"]
        interval: 2s
        timeout: 5s
        retries: 15
        start_period: 5s
  ```
- Compose works on the `docker` provider (the default) and a few others. Not on e2b, runloop, etc.
- Each trial gets its own compose project (named from the trial session id), so each trial gets a
  fresh sidecar and a fresh episode. Source: `docker.py` line ~761.

### tests/test.sh and the reward

- Harbor runs `/tests/test.sh`. It must write the reward to:
  - `/logs/verifier/reward.txt`: one number, e.g. `1` or `0`; or
  - `/logs/verifier/reward.json`: a flat JSON object of numbers, e.g. `{"reward": 1, "progress": 0.83}`.
  - If both exist, **reward.json wins**. Non-numbers, NaN or Inf make the trial error out.
  - With reward.json, the main score key should be `"reward"` (reward.txt is read as `{"reward": x}`).
- Before running test.sh, Harbor **deletes any old reward.txt/reward.json**, so an agent cannot
  pre-write a reward. Source: `Verifier._remove_reward_files` in `src/harbor/verifier/verifier.py`.
- Other files in `/logs/verifier/` are copied back to the trial folder (handy for a grade report).

### solution/solve.sh

- Optional. Only the `oracle` agent uses it: it uploads `solution/` to `/solution` in `main` and
  runs `solve.sh` there. `[solution].env` vars are set. Output goes to `/logs/agent/oracle.txt`.
- Multiple solutions: pass `--ae NAME=value` and branch inside solve.sh (docs `tasks/solution.mdx`,
  example `examples/tasks/hello-world-multiple-solutions`). Do not also set that var in `[solution].env`.

## 2. MCP servers

Declare them in task.toml. Harbor passes them to agents that support MCP (OpenCode, Claude Code,
Codex, Gemini CLI, Goose, OpenHands, Terminus-2, and more):

```toml
[[environment.mcp_servers]]
name = "mcp-server"
transport = "streamable-http"      # "stdio" | "sse" (default!) | "streamable-http"; "http" -> streamable-http
url = "http://mcp-server:8000/mcp" # required for sse / streamable-http
# command = "..."; args = [...]    # required/used for stdio only
# headers = { Authorization = "Bearer ${MCP_TOKEN}" }   # HTTP only; see note
```

Note: the default transport is `sse`, so always set `transport` explicitly.

What OpenCode does with it (`src/harbor/agents/installed/opencode.py`,
`_build_register_config_command`): before the run it writes `~/.config/opencode/opencode.json`:

```json
{ "mcp": { "pinbox": { "type": "remote", "url": "http://pinbox-env:8000/mcp", "oauth": false } } }
```

(stdio servers become `{"type": "local", "command": [command, ...args]}`). Then it runs
`opencode --model=<model> run --format=json --thinking --dangerously-skip-permissions -- <instruction>`.

- **`headers` are NOT forwarded by `opencode`** (v1). Only `claude-code`, `codex` and `opencode-v2`
  forward headers (docs `agents/pre-integrated-agents.mdx`, "HTTP MCP headers"). So do not rely on
  an auth header for the MCP endpoint.
- Header values that look like credentials must be `${VAR}` references, never literals (validator
  in `MCPServerConfig.validate_headers`).
- Job-level MCP is also possible: `harbor run ... --mcp-config path/.mcp.json` (Claude-style
  `{"mcpServers": {"name": {"type": "http", "url": "..."}}}`) or `mcp_servers:` under an agent in a
  job config YAML (example `examples/jobs/mcp-proof/`). Agent-level servers override task servers
  with the same name. We should use the task.toml way so judges need no extra flags.
- "MCP server support means the integration passes the supplied configuration to the agent; it
  does not guarantee connectivity" (docs). The sidecar must be up: use `depends_on` +
  `condition: service_healthy`.

## 3. When are tests/ and solution/ copied? Can the agent see them?

Order of a single-step trial (`src/harbor/trial/single_step.py`):
1. Start environment (build images, start compose, healthcheck).
2. Agent setup (OpenCode installs itself with npm), then agent run.
3. Collect artifacts: hooks + files from `main`; then (separate mode only) **stop `main`**; then
   sidecar collect hooks + sidecar files.
4. Verifier.

- `tests/` is uploaded to `/tests/` **after** the agent finishes (shared mode). In separate mode
  with `tests/Dockerfile`, tests are baked into the verifier image and never touch the agent's
  container. Either way the agent cannot see tests during its run.
- `solution/` is uploaded to `/solution/` **only by the oracle agent**. A real agent never sees it.
- `environment/` is only a Docker build context. The agent sees only what the main `Dockerfile`
  COPYs. Warning: `COPY . /app` in the main Dockerfile would copy every sidecar folder too.
- `/logs/agent`, `/logs/verifier`, `/logs/artifacts` are mounted into `main` during the run.

Shared vs separate verifier (docs `tasks/separate-verifier.mdx`):
- `shared` (default when you set nothing): test.sh runs inside the agent's `main` container after
  the agent. It can reach sidecars over the network.
- `separate`: a fresh container runs test.sh. Image choice: `[verifier.environment].docker_image`,
  else `tests/Dockerfile` (must `COPY . /tests/`), else a fresh copy of the agent image with
  `tests/` uploaded. The agent's files are not inherited; only declared `artifacts` are copied in,
  at their original paths. Sidecars are stopped by then, so get their data with
  `[[verifier.collect]]` + `artifacts = [{ source = "...", service = "<sidecar>" }]`.
  Official example: `examples/tasks/sidecar-artifacts` (scores only from sidecar evidence).
  Separate mode also enables `harbor job regrade`.

## 4. CLI

Install (needs Python >= 3.12 and Docker running):

```bash
uv tool install harbor        # or: pip install harbor   (pin: pip install "harbor==0.25.0")
```

Checked on this Windows laptop: `pip install "harbor==0.25.0"` works in a Python 3.14 venv, and
`harbor --version` prints `0.25.0`. `harbor run --help` lists `-p`, `-a`, `-m`, `-k`, `--ae`.
(Here `harbor.exe` inside the Temp folder gave "Permission denied", probably a machine policy;
`python -c "import harbor.cli.main as m; m.app()" ...` works the same.) Docker Desktop 29.5 with
Linux containers and Compose v5 is installed here.

Run one local task folder (or a folder of task folders) with `-p`:

```bash
# reference run (runs solution/solve.sh)
harbor run -p harbor/tasks/ap-run-s7-d2 -a oracle -y
# do-nothing baseline
harbor run -p harbor/tasks -a nop -y
# stop-early baseline (OUR PROPOSAL: solve.sh reads PINBOX_SOLUTION)
harbor run -p harbor/tasks -a oracle --ae PINBOX_SOLUTION=stop_early_50 -y
# frontier agent, 3 attempts per task
export ANTHROPIC_API_KEY=...      # or GEMINI_API_KEY / GOOGLE_API_KEY, OPENAI_API_KEY, ...
harbor run -p harbor/tasks -a opencode -m anthropic/claude-sonnet-5-5 -k 3 -n 4 -y
harbor run -p harbor/tasks -a opencode -m gemini/<model-id> -k 3 -y
```

Useful flags (from `src/harbor/cli/jobs.py`, same in 0.25.0): `-p/--path` local task or dataset
dir; `-a/--agent` (`oracle`, `nop`, `opencode`, `opencode-v2`, `claude-code`, ... or
`module.path:ClassName`); `-m/--model` (LiteLLM-style `provider/model`); `-k/--n-attempts`;
`-n/--n-concurrent`; `--ae KEY=VALUE` agent env; `--ak key=value` agent kwargs (e.g.
`--ak version=1.2.3` to pin the OpenCode npm version: installed agents take a `version` kwarg,
see `agents/installed/base.py`); `-o/--jobs-dir` (default `jobs`);
`--job-name`; `-y/--yes` auto-confirm prompts (Harbor asks before passing host env vars);
`--env-file .env`; `-e/--env` sandbox provider (default `docker`). `harbor trial start -p <task>`
runs a single trial. `harbor view ./jobs` opens a local results viewer.

API keys: Harbor collects the provider key from the host (`anthropic` -> `ANTHROPIC_API_KEY`;
`gemini`/`google` -> `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_GENERATIVE_AI_API_KEY`;
`openai` -> `OPENAI_API_KEY`) and routes it to the agent (docs `agents/agent-auth-resolution.mdx`).

How results are reported:
- At the end, `harbor run` prints a table per (agent, model, dataset): Trials, Exceptions, the
  metric (default mean reward), Pass@k, then a "Reward / Count" table and an exception table.
- Files: `jobs/<YYYY-MM-DD__HH-MM-SS>/result.json` (whole job, `stats.evals[...]`),
  `jobs/<job>/<task-name>__<7 chars>/result.json` (one trial; `verifier_result.rewards`),
  `.../verifier/reward.txt|json` and test.sh stdout, `.../agent/` (e.g. `opencode.txt`,
  `oracle.txt`, ATIF trajectory), `.../artifacts/` (+ `manifest.json`), `trial.log`.

OpenCode inside the task container:
- It installs at agent setup (`npm i -g opencode-ai@latest` via nvm; needs curl/bash, and network).
  Pre-installed images can use `--ak skip_install=true`.
- `[agent] network_mode` applies only to `agent.run()`, not setup. Keep `public` (default): the
  agent calls the model API from inside `main`.

## 5. AfterQuery Junction 2026 starter kit / scoring skeleton

- **Not found publicly.** Web and GitHub search found no AfterQuery starter kit or scoring
  skeleton repo. The AfterQuery GitHub org has one public repo, `AfterQuery/storebench` (their own
  benchmark: task.toml + prompt + a stdlib re-grader). Not a Harbor task folder and not the kit.
- A copy of the Junction brief in another team's public repo says AfterQuery hands teams "a scoring
  skeleton, a starter kit (harness docs and the rubric)" and that the harness is "Harbor running
  the OpenCode agent", connecting "over MCP". Judges rerun: reference run, 3 agent runs, do-nothing
  and stop-early baselines. **Get the real kit from the AfterQuery mentors / Junction platform**
  and check it against these notes.

## 6. OUR PROPOSAL: how Poisoned Inbox maps onto this

One task folder per eval episode, generated by `harbor/build_tasks.py`:

```
harbor/tasks/ap-run-s7-d2/
  task.toml            # mcp_servers -> http://pinbox-env:8000/mcp; verifier separate; collect hook
  instruction.md       # task + full policy (from Task.instruction) + "use the pinbox MCP tools"
  environment/
    Dockerfile         # main: ubuntu/python slim + curl. NO pinbox code. Do not COPY . 
    docker-compose.yaml# main depends_on pinbox-env (healthy); pinbox-env built from ./pinbox-env
    pinbox-env/        # Dockerfile (python:3.12-slim, pip install mcp) + copy of pinbox/
                       # CMD python -m pinbox serve ap_run:7:2 --transport http --port 8000
  solution/
    solve.sh           # runs the reference agent over MCP (needs an MCP client: pip/uv install
                       # mcp, or pre-install it in main). PINBOX_SOLUTION picks reference / stop_early_N
  tests/
    Dockerfile         # verifier image: python:3.12-slim + copy of pinbox/ + COPY . /tests/
    test.sh            # regrade from collected state; write reward.json {"reward": 0|1, "progress": x}
```

- Grading path (separate mode): after the agent, `main` is stopped; the collect hook in
  `pinbox-env` dumps the final state (or the GradeReport) to a file; the file is an artifact; the
  verifier recomputes truth from (family, seed, difficulty) baked into `tests/`, never from the
  collected file. This needs **no admin route and no token**, and the agent can never touch the
  verifier. This differs from SPEC section 11 ("verifier fetches the grade with a token"). The
  token route only works in `shared` mode, where test.sh runs inside the agent's own container.
  If we keep it, make the admin route token-protected, because the agent can reach `pinbox-env:8000`
  directly with curl.
- The MCP tool result should carry the dispatch dict as JSON text so solve.sh's client can map it
  back to `{"ok", "result", "error"}` for `Task.reference(client)`.
- Shell scripts must have LF line endings (repo is on Windows): add `.gitattributes` with
  `*.sh text eol=lf`.

## 7. Could NOT verify

- No end-to-end Harbor run was done. A smoke test of the official `hello-mcp` example with the
  oracle agent was planned but not run (the action was blocked in this session). Next step for
  the Harbor builder: run `harbor run -p <hello-mcp copy> -a oracle` and `-a nop` on this
  laptop to confirm Harbor + Docker Desktop on Windows works before building our tasks.
- Did not run a full OpenCode + model trial (no API key used here). Tool names as the model sees
  them: OpenCode's docs (opencode.ai/docs/mcp-servers, which describe the new 2.x CLI) say
  `<server>_<tool>`, e.g. `pinbox_list_invoices`. Harbor's `opencode` agent installs the 1.x
  package (`opencode-ai`, 1.19.5 on npm today) and writes the 1.x config shape
  (`mcp.<name>`), while `opencode-v2` installs `@opencode/cli` (2.3.0) and writes
  `mcp.servers.<name>`. Naming in 1.x: UNVERIFIED (probably the same). Keep tool names short and
  plain so the prefix does not matter.
- Whether a lingering agent process could rewrite `/logs/verifier/reward.*` in `shared` mode after
  test.sh ends: UNVERIFIED. `separate` mode avoids the question (main is stopped first).
- Whether Docker layer caching avoids rebuilding the identical `pinbox-env` image for every task
  folder: UNVERIFIED (likely yes with BuildKit, since contents are identical).
- `allowlist` network mode with compose on Docker Desktop for Windows: UNVERIFIED (docs say it
  needs Linux nftables support). We do not need it.
- AfterQuery's private starter kit and scoring skeleton: not seen.
- Which Harbor version and which model the judges will use: unknown.

## Sources

- https://github.com/harbor-framework/harbor (README, `pyproject.toml`; commit f9c47b1, tag v0.25.0)
- `src/harbor/models/task/config.py`, `src/harbor/models/task/paths.py`, `src/harbor/models/trial/paths.py`
- `src/harbor/verifier/verifier.py`, `src/harbor/trial/single_step.py`, `src/harbor/trial/trial.py`
- `src/harbor/agents/oracle.py`, `src/harbor/agents/nop.py`, `src/harbor/agents/installed/opencode.py`, `opencode_v2.py`
- `src/harbor/environments/docker/docker.py`, `docker-compose-build.yaml`, `src/harbor/constants.py`
- `src/harbor/cli/jobs.py`, `src/harbor/cli/trials.py`, `src/harbor/models/job/result.py`
- Examples: `examples/tasks/hello-mcp`, `examples/tasks/sidecar-artifacts`, `examples/jobs/mcp-proof`,
  `examples/configs/agents/opencode-job.yaml`
- Docs (https://harborframework.com/docs, source `docs-mintlify/`): tasks/overview, configuration,
  environment, multi-container, verifier, separate-verifier, solution, network-policies;
  jobs/run-a-job, jobs/artifact-collection; agents/pre-integrated-agents, agents/agent-auth-resolution;
  getting-started/installation, quick-start
- PyPI: https://pypi.org/project/harbor/ (0.25.0 latest stable)
- https://github.com/AfterQuery/storebench (AfterQuery's only public repo)

## Packaging decisions (Harbor builder, Sat 14 Nov 2026, 02:45-04:00)

What exists now: `harbor/build_tasks.py` writes `harbor/tasks/<episode_id>/` for every eval episode
of every family (`pinbox.eval.eval_set()`). How to run it: `harbor/README.md`.

1. **Env server = compose sidecar `pinbox-env`.** It runs
   `python -m pinbox serve FAMILY:SEED:DIFF --transport http --host 0.0.0.0 --port 8000`
   (admin token from `$PINBOX_ADMIN_TOKEN`, state in `/srv/pinbox/state`, user `pinbox`).
   `task.toml` points the agent's MCP config at `http://pinbox-env:8000/mcp` (streamable-http).
   The agent image (`main`) is `python:3.12.16-slim-trixie` + curl, with no `COPY` at all; its
   `.dockerignore` also drops `pinbox-env/` from the build context. Harbor only uploads
   `environment/` into `main` for prebuilt-image tasks without a Dockerfile, so it is never copied in
   (checked: `should_upload_environment_dir` in `environments/definition.py`).
2. **Separate verifier is the default.** Checked in Harbor 0.25.0 `trial/single_step.py`: in
   separate mode Harbor (a) stops `main`, (b) runs `[[verifier.collect]]` hooks in sidecars,
   (c) downloads artifacts, (d) stops the whole compose project, (e) starts the verifier from
   `tests/Dockerfile`, after emptying `/logs/verifier`. So nothing the agent leaves behind can
   touch grading.
3. **Deviation from SPEC section 11 ("test.sh fetches the grade via the admin route with a token
   only in tests/").** In separate mode the server is already stopped when `test.sh` runs (step d
   above), so `test.sh` cannot call it. Instead the collect hook (`collect.py`, runs inside
   `pinbox-env` after `main` is stopped) calls `/admin/grade` and `/admin/trajectory` with a token
   the server makes at start (`secrets.token_hex(32)`, file mode 0600, never leaves the container,
   in no repo file) and saves `grade.json`, `trajectory.jsonl`, `final_state.json` to
   `/srv/pinbox/out`. That folder is the only artifact; `tests/verify.py` checks it (right episode,
   well-formed, reward matches checks) and writes `reward.txt`. If the admin route fails, the hook
   grades the server's saved state folder instead (truth still rebuilt from the seed).
   The SPEC's literal design is kept as `build_tasks.py --verifier shared` for Harbor versions
   without a separate verifier: token in `tests/admin_token` and in the compose env (fresh random
   token per build), `test.sh` runs in `main` after the agent and calls the admin route. It is
   weaker (see 8).
4. **pinbox snapshot.** Each task folder carries `pinbox.zip` (deterministic: sorted names, fixed
   timestamps, no `__pycache__`; ~150 KB), in `environment/pinbox-env/` and `solution/`. Folders
   stay self-contained; git and Docker store identical bytes once. `task.toml [metadata]` records its
   sha256. Rebuild the tasks after any pinbox change.
5. **Pins.** Base image `python:3.12.16-slim-trixie` (index digest
   `sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` on 14 Nov).
   `mcp==2.3.0` plus its whole `pip freeze` closure (`template/requirements.txt`). Image sizes here:
   main ~196 MB, pinbox-env ~237 MB, verifier ~177 MB.
6. **Oracle.** `solution/solve.sh` makes a venv in `/tmp`, pip-installs the pinned requirements
   (needs network during the oracle run), unzips pinbox and runs `run_solution.py`, which plays the
   episode with `pinbox.mcp_client.McpEpisodeClient` and `agents.baselines.make_agent`.
   `--ae PINBOX_SOLUTION=` picks `reference` (default), `do_nothing`, `stop_early_25|50|75`,
   `stop_before_last_write`, a family's naive policy, or `cheat` (reward-hack probe). Stop-early over
   MCP sizes its cut from a local scratch copy of the episode, like `baselines.stop_early`.
7. **Reward file.** Only `reward.txt` (0 or 1), so Harbor's mean is the binary reward. Progress and
   failure tags go to `verifier/verdict.json`.
8. **Shared mode is exploitable; separate is not (verified).** The `cheat` probe starts a background
   loop that keeps rewriting `/logs/verifier/reward.txt` and `reward.json`. Shared mode, first
   version: Harbor reported reward **1** although `verify.py` wrote 0. Separate mode: **0**.
   `test.sh` now kills leftover processes in shared mode and runs `python3 -I -S`; a root agent can
   still replace programs in its own container, so shared mode stays a fallback only.
9. **Windows.** The builder rewrites files in place (never deletes a whole task folder): once a
   `shutil.rmtree` failed with "Access denied" on the OneDrive folder and left a half-deleted task,
   which then failed in Harbor with "open Dockerfile: no such file". All generated text is LF
   (`harbor/.gitattributes` too). `harbor.exe` is blocked here; `python -m harbor.cli.main` works.
   In Git Bash set `MSYS_NO_PATHCONV=1` or `/solution/...` paths get rewritten.
10. **Offline re-check.** `harbor/export_runs.py` copies each trial's trajectory into
   `runs/recorded/...`; `python -m pinbox eval --include-recorded ...` / `python -m pinbox replay`
   re-grades them. Checked: replays of the Harbor runs give the same rewards.

### Verified on this laptop (Harbor 0.25.0, Docker Desktop 29.5.2 / Compose v5.1.4, Windows 11)

| Run | Tasks | Result |
|---|---|---|
| `-a oracle` (reference), all tasks (build of 03:02) | 42 (ap_run 30, refunds 8, board_pack 4) | 41 x reward 1; 1 error = the half-deleted `ap_run-s1-d1` folder (builder bug, fixed in 9; that task then scored 1 in every later run) |
| `-a oracle` / `-a nop` / `--ae PINBOX_SOLUTION=stop_early_50` / `cheat`, `ap_run-s1-d1` | 1 each | 1 / 0 / 0 / 0 |
| `harbor/run_all.sh` with `QUICK=1` (final build: one task per family; reference, do-nothing, stop-early, cheat) | 3 x 4 | reference 1.0 on all 3 families; do-nothing, stop-early, cheat 0.0 on all 3 |
| shared-mode build, `ap_run-s1-d1`: oracle / nop / cheat (first test.sh) | 1 each | 1 / 0 / **1** (exploit, see 8) |
| shared-mode build with the process-killing test.sh: cheat / oracle | 1 each | 0 / 1 |
| raw MCP from the agent container with curl, protocol `2025-03-26` (what OpenCode 1.x speaks) | - | initialize, 16 tools listed, `tools/call` works through host name `pinbox-env` |
| `python -m pinbox replay` of exported Harbor trajectories | 4 checked | same rewards as Harbor |

One trial takes about 1.5-2.5 minutes here (4 at a time). Harbor removed every container and image
it built after each trial.

### Still not verified

- **OpenCode itself.** No model API key on this machine, and installing Node with `curl | bash`
  inside a test container was not allowed in this session. What is checked: Harbor writes the
  legacy `mcp.pinbox = {type: remote, url, oauth: false}` config (source), and a raw 2025-03-26 MCP
  client works against our server from inside `main`.
- Linux or macOS hosts, other Harbor versions than 0.25.0, cloud providers (compose sidecars need
  the `docker` provider).
- Shared mode against a root agent that replaces programs (cannot be fixed in shared mode).
