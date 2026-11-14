# Canary on Harbor (OpenCode over MCP), with the answer out of the agent's reach

Judges rerun us with **Harbor running the OpenCode agent, connected to our environment over MCP**.
This folder builds that package as a Harbor dataset (one task per tier and judge seed) and proves the
agent container holds nothing that reveals the mole.

```bash
uv tool install harbor                       # Harbor CLI (tested: 0.26.0); needs Docker with the compose plugin
python harbor/build.py                       # THE JUDGE SET -> harbor/dataset/canary-hard-9000{00..09}/ (10 hard tasks)
harbor run -p harbor/dataset -a oracle -n 4                               # reference solver over MCP
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4  # do-nothing baseline (expect 0)
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4  # stop-early baseline (expect about -1)
harbor run -p harbor/dataset -a opencode -m openai/<model> -n 4           # the agent (needs OPENAI_API_KEY)
python harbor/build.py --tiers medium --seeds 900000                 # just one task
python harbor/build.py --tiers easy,medium,hard --seeds judge        # everything: 3 tiers x all 40 judge seeds
```

**The default build is the judge set: tier hard, judge seeds 900000–900009 (10 tasks).**
- **Why hard.** Hard is the tier where the reference solver keeps its expected-value edge. On medium a frontier agent
  can land near the solver with one lucky early accusation, so a short rerun can show parity by chance; on hard the
  21-day horizon, delayed leak feed and 2 canaries a day reward the calibrated "keep investigating vs commit" call
  that agents get wrong.
- **Why these seeds.** 900000–900009 are the first 10 frozen judge seeds, fixed in `docs/PLAN-95.md` (commit
  08f87b6, Saturday 14 Nov 18:48) before any frontier run on this set, so it is pre-registered, not picked after
  seeing results. The seed numbers alone don't pick the worlds either: each build draws a fresh world secret, so the
  worlds a judge's build serves are new to everyone, us included. (The 6-task Gemini demo below used seeds
  900000–900002 on an earlier build, i.e. different worlds.)
- Medium and easy, and any other judge (900000–900039) or held-out (800000–800199) seed, still build with
  `--tiers` / `--seeds`.

`harbor/dataset/` is gitignored: it holds the vendored package copies and the build-time world secret.

## Layout

```
harbor/
  build.py                 generator: one self-contained Harbor task per (tier, seed)
  check_isolation.sh       run inside the agent container; exits non-zero on any finding
  template/                the task skeleton build.py renders
    task.toml              separate verifier, sidecar artifact + collect hook, [[environment.mcp_servers]]
    environment/Dockerfile           agent (`main`) image: python:3.12-slim + curl/procps. No canary code.
    environment/.dockerignore        keeps canary-server/ out of the agent image's build context
    environment/opencode.json        project OpenCode config -> http://canary-server:8765/mcp
    environment/docker-compose.yaml  the canary-server sidecar
    environment/canary-server/       sidecar image: Dockerfile, entrypoint.sh, collect.py (+ vendored canary/, SALT)
    solution/solve.sh                oracle: check_isolation --oracle-run, then `--play solver` over MCP
    tests/Dockerfile, tests/test.sh  verifier: checks the ledger's HMAC signature, then reward = ledger["score"]
  canary-task/instruction.md         ENV's rules text (tests/test_env_docs.py pins it); build.py uses the same renderer
```

## How the isolation works

```
 agent container "main"                         sidecar "canary-server" (uid 10001)
 ------------------------                       ------------------------------------------
 OpenCode (installed by Harbor)  --HTTP/MCP-->  python -m canary.mcp_server  (one episode, one container per trial)
 /app/opencode.json                             canary/ package, Env, world
 nothing else                                   data/worlds/judge/SALT  (build-time secret, 0600, owner canary)
                                                episode.json {tier, seed} (build time, 0600)
                                                /run/canary/ledger_token (0600, made at start)
                                                ledger_key (build-time HMAC key, 0600; also in the verifier image)
                                                environ: only *_FILE paths, host, port, provider
```

- Separate containers: separate filesystem, **separate PID namespace** (no `pid: host`, no shared volumes,
  no docker socket). The server's `/proc/<pid>/environ` does not exist from the agent's point of view. This closes
  the judge-sim finding (EXPLOITS #25) where a same-uid process read the server's environ and scored 1.0.
- Defence in depth: the server reads its episode, world secret and ledger token from 0600 files through
  `mcp_server.py`'s `CANARY_EPISODE_FILE` / `CANARY_WORLD_SECRET_FILE` / `CANARY_LEDGER_TOKEN_FILE`, so even
  inside the sidecar its environ holds no seed, tier, secret or token (checked: 0 such variables in `/proc/1/environ`).
- The **world secret** is generated by `build.py` at build time (one random 32-byte secret per build, or
  `--secret-file`) and baked into the sidecar image as a 0600 file (`data/worlds/judge/SALT`, also named by
  `CANARY_WORLD_SECRET_FILE`). No env var holds it. Because it is fixed
  at build time, the oracle and every agent trial of a task play **the same world** (a paired comparison).
  It is never committed and never enters the agent image. `--secret-file data/worlds/judge/SALT` reproduces the team's
  exact numbers, if that file exists locally.
- Grading: after the agent finishes, Harbor **stops `main`**, runs `[[verifier.collect]]` (`collect.py`) inside the
  sidecar (it reads the token file and GETs `/ledger` on localhost), copies `/evidence/ledger.json` out as an
  artifact, and a **separate verifier container** (`tests/Dockerfile`) writes `float(ledger["score"])` to
  `/logs/verifier/reward.txt`. Negative scores pass through (wrong accusation = -1). The agent never holds the
  token, can't run processes during collection, and never touches the verifier sandbox.
- **Signed ledger (defence in depth).** `build.py` draws one random 32-byte **ledger signing key** per build and
  writes it, 0600, into exactly two build contexts: the sidecar's (`canary-server/ledger_key`, read through
  `CANARY_LEDGER_KEY_FILE`) and the separate verifier's (`tests/ledger_key`). Neither is in the agent image's build
  context (`environment/.dockerignore` excludes `canary-server/`; `tests/` is never uploaded to `main`) or in
  `solution/`. The server HMAC-SHA256-signs every `/ledger` payload (`"sig": {"alg": "HMAC-SHA256", "mac": ...}` over
  the canonical JSON of every other field; `canary.mcp_server.sign_ledger`). `test.sh` **fails closed**, reward 0
  plus a `FAIL:` line, if the key is missing, the signature is missing or wrong (forged score, any edited field,
  another build's key), or the score is outside {−1, 0} ∪ (0, 1]. So even a ledger.json written into the verifier's
  path by something other than this task's server is worthless. `tests/test_harbor_ledger_sig.py` covers forged,
  tampered, unsigned, wrong-key and out-of-range ledgers, and a real server whose signed ledger reproduces the
  in-process score through `test.sh`. `check_isolation.sh` also fails on any `*ledger_key*` file in `main`.
- From the agent's side the network shows only `/mcp`, `/healthz`, `/ledger` (403 without the token) and
  `/admin/reset` (disabled: no admin token is set).

### check_isolation.sh

Runs inside `main` and fails on any of:
- files named `*truth*`, `*SALT*`, `*.world.json`, `*.mole.json`; canary package source; `import canary` working;
- any `CANARY_*` variable in its own env; **any readable `/proc/*/environ` containing `CANARY_`**;
- a server process in `ps` or in `/proc/*/cmdline` (no server pid visible); host daemons (dockerd/containerd/
  systemd/launchd) visible, which would mean a host PID namespace;
- a docker socket; a bind mount of the repo or worlds;
- `GET /ledger` answering without the token (positive control: `/healthz` reachable = network only).

`--oracle-run` skips `/solution` and `/logs`: the oracle's vendored solver is uploaded only for `-a oracle`.
Any `CANARY_*` name in the agent container is a finding, even a harmless one: an early oracle selector named
`CANARY_ORACLE_AGENT` was flagged in our own runs (env and three `/proc/<pid>/environ`), so it was renamed to
`ORACLE_POLICY`. Keep every variable passed into `main` (`--ae`, `[environment].env`) free of the `CANARY_` prefix.

Negative control: the same script run inside the `canary-server` sidecar reports 6 findings (SALT file, canary
source, `import canary`, CANARY_* env, server cmdline in /proc, CANARY_ in `/proc/1/environ`) and exits 1.

### Fallbacks and trade-offs

| Situation | What to do | Trade-off |
|---|---|---|
| Harbor older than the sidecar collect hooks (`[[verifier.collect]]`, artifact `service`, added 2026; present in 0.26.0) | `python harbor/build.py --verifier shared`: test.sh runs in `main` and GETs `/ledger` with a per-build token from `[verifier].env` (also put in the sidecar's compose env); the ledger signing key also comes from `[verifier].env` (it wins over any `/tests/ledger_key`, which would sit in the agent's container) | The verifier shares the agent's container: a hostile agent could leave a process that rewrites `/logs/verifier/reward.txt` or replace `python3`. It still can't read the truth or forge a signed ledger, but grading is weaker. Prefer the default |
| Provider without compose (e2b, runloop, apple-container, ...) | Server outside the sandbox: run `python -m canary.mcp_server` on a host the sandbox can reach, put its URL in `[[environment.mcp_servers]]`, keep the ledger token on the host; test.sh can't reach it, so score from the host (or via a token in `[verifier].env` with a shared verifier) | Each trial needs its own server (single-episode), started by the operator; the agent can reach the host's `/ledger` endpoint (token-protected) |
| Must run server and agent in ONE container | Run the server as a different uid; episode, secret and tokens from 0600 files owned by that uid via the `*_FILE` vars (now in `mcp_server.py`), never env; `hidepid=2` on /proc if possible | Same kernel PID namespace: relies on uid separation; root in the agent container defeats it, so run the agent as non-root (`[agent] user`) |
| `network_mode = "allowlist"` | Harbor's egress sidecar puts services without explicit `networks:` into one network namespace. Still separate PID/filesystem, but re-run check_isolation.sh | none for the truth; keep `public` (the agent needs its model API anyway) |

The `*_FILE` interface (`CANARY_EPISODE_FILE`, `CANARY_WORLD_SECRET_FILE`, `CANARY_LEDGER_TOKEN_FILE`,
`CANARY_ADMIN_TOKEN_FILE`) landed in `mcp_server.py` while this package was built; the sidecar uses it.

## Research: Harbor (sources at the end)

**(a) Task folder layout.** A task is a directory: `instruction.md`, `task.toml`, `environment/` (a `Dockerfile`,
or `docker-compose.yaml` for multi-container), optional `solution/solve.sh`, and `tests/test.sh` [1].
`test.sh` must write a number to `/logs/verifier/reward.txt` (or labeled metrics to `/logs/verifier/reward.json`,
which wins if both exist) [3]. Main `task.toml` fields [2]: `schema_version` (1.4), top-level `artifacts`, `[task]`
(name `org/name`, description, authors, keywords), `[metadata]` (free-form), `[verifier]` (`timeout_sec`, `env`,
`user`, `environment_mode = "shared"|"separate"`, `[verifier.environment]`, `network_mode`), `[[verifier.collect]]`
(service, command, timeout) [6], `[agent]` (`timeout_sec`, `user`, `network_mode`), `[solution].env`, `[environment]`
(`docker_image`, `cpus`, `memory_mb`, `storage_mb`, `build_timeout_sec`, `network_mode`, `allowed_hosts`, `env`,
`workdir`, `[[environment.mcp_servers]]`). Harbor copies `solution/` to `/solution` only for the oracle [8];
for a shared verifier it uploads `tests/` to `/tests/` after the agent runs; a separate verifier built from
`tests/Dockerfile` must bake the tests in [3][4]. A dataset is a directory of tasks (or a `dataset.toml`) run with
`-p` [9]. Real examples: terminal-bench-2 (e.g. `chess-best-move/`: `task.toml` with `[verifier] timeout_sec`,
`[agent] timeout_sec`, `[environment] docker_image/cpus/memory_mb`, `tests/test.sh` writing `reward.txt`) [11].

**(b) Sidecars the agent can reach but not see.** Yes. `environment/docker-compose.yaml` is merged over Harbor's base
compose; `main` is reserved for the agent container and every other service is a sidecar on the same Docker network,
reached by service name (`http://mcp-server:8000`) [5]. Separate containers mean separate filesystems and PID
namespaces. Harbor also collects artifacts from sidecars (`service = "..."`) and runs `[[verifier.collect]]` hooks
inside them; in separate-verifier mode it stops `main` first "so leftover agent processes cannot interfere" [6][10].
Its own example `examples/tasks/sidecar-artifacts` scores from sidecar evidence exactly like we do [12]. Compose works
natively on docker, podman, ec2, islo, vercel, and via DinD on daytona, modal, gke and others; not on e2b, runloop,
apple-container, singularity, and a few more [5].

**(c) OpenCode and MCP.** `-a opencode` is a pre-integrated installed agent: setup installs Node (nvm) and
`npm i -g opencode-ai@<version|latest>` in `main`; the run is `opencode --model=<provider/model> run --format=json
--thinking --dangerously-skip-permissions -- <instruction>` [7]. MCP servers declared in task.toml under
`[[environment.mcp_servers]]` (`name`, `transport = "streamable-http"`, `url`) are written by Harbor into
`~/.config/opencode/opencode.json` as `{"mcp": {"<name>": {"type": "remote", "url": ..., "oauth": false}}}` before the
run [2][7]. OpenCode is listed under the "MCP servers" capability; HTTP MCP headers are not forwarded for `opencode`
(only claude-code, codex, opencode-v2) [13], so we use no auth header (the MCP endpoint is the game itself; the grader
endpoint is token-protected). Credentials come from host env vars per provider (e.g. `OPENAI_API_KEY` for
`openai/<model>`) [14]. A ChatGPT login on a laptop is not passed into the container.

**(d) CLI.** `uv tool install harbor` [15]; then `harbor run -p <task-or-dataset-dir> -a oracle` (runs
`solution/solve.sh`) [8], or `harbor run -p <dir> -a opencode -m openai/<model>` [7][9]. Useful flags: `-n` concurrency,
`-k` attempts, `-o` jobs dir, `-y` auto-confirm, `--ae KEY=VAL` agent env, `--ak key=val` agent kwargs. `harbor lint
<task>` checks the task statically; `harbor view ./jobs` opens the viewer. Results land in
`jobs/<timestamp>/<task>__<id>/` (`verifier/reward.txt`, `artifacts/`, `agent/`).

Sources (read 2026-11-14 from a clone of the repo; docs are the `docs-mintlify/` tree):
[1] harbor `docs-mintlify/tasks/overview.mdx`; [2] `tasks/configuration.mdx`; [3] `tasks/verifier.mdx`;
[4] `tasks/separate-verifier.mdx`; [5] `tasks/multi-container.mdx`, `tasks/environment.mdx` (MCPs);
[6] `jobs/artifact-collection.mdx` (sidecar artifacts, collect hooks); [7] `src/harbor/agents/installed/opencode.py`
(`install`, `_build_register_config_command`, `run`); [8] `tasks/solution.mdx`; [9] `datasets/datasets.mdx`;
[10] `CHANGELOG.md` "Sidecar Artifacts and Collect Hooks", `src/harbor/trial/single_step.py`;
[11] https://github.com/laude-institute/terminal-bench-2 (`chess-best-move/`); [12] `examples/tasks/sidecar-artifacts/`;
[13] `agents/pre-integrated-agents.mdx` (capability table); [14] `agents/agent-auth-resolution.mdx`;
[15] `getting-started/installation.mdx`. Repo: https://github.com/laude-institute/harbor (redirects to harbor-framework/harbor).

## Verified on this machine (tiers v1.4)

Harbor 0.26.0 on colima (2 CPU / 3 GB), Saturday 14 Nov. Every log and output is committed under
[`results/harbor/`](../results/harbor/). The logs were scanned for the build secret (0 hits), and local absolute paths were rewritten.

**Baselines on one build (medium + hard, judge seed 900000).** All policies play the same worlds because the secret is fixed per build.

| policy | medium 900000 | hard 900000 | expected |
|---|---:|---:|---|
| oracle (reference solver over MCP) | **0.78** | **0.66** | equal to the in-process solver on the same build: 0.78 / 0.66 |
| `ORACLE_POLICY=do_nothing` | 0.0 | 0.0 | 0 |
| `ORACLE_POLICY=stop_early` | −1.0 | −1.0 | about −1 |

Jobs: `results/harbor/{oracle,do_nothing,stop_early}/`. There were 0 exceptions, about 1.5 min per 2-trial job.

**Isolation, checked inside the agent container (`main`).** `solve.sh` runs `check_isolation.sh` before it plays (`agent/isolation.txt` in every oracle trial). Result on both tiers: `ISOLATION OK: 11 checks passed, 0 findings`.
- No secret, truth or world files; no canary source, and `import canary` fails; no `CANARY_*` variables.
- No server process in `ps`/`/proc`; its own PID namespace; no docker socket; no bind mounts.
- The game is reachable only over HTTP, and `/ledger` without the right token returns 403.

**A frontier model through the exact judge path: gemini-4-carbon via OpenCode over MCP.** One 6-task build: judge seeds 900000–900002, medium and hard. The oracle ran on the same build, so each pair below is the same world.

| task (v1.4) | oracle (solver) | gemini-4-carbon | difference | Gemini's game |
|---|---:|---:|---:|---|
| medium 900000 | 0.84 | 0.83 | −0.01 | correct, day 6, 59 tool calls |
| medium 900001 | 0.88 | 0.61 | −0.27 | correct, day 11, 106 calls |
| medium 900002 | 0.84 | **0.00** | −0.84 | never accused: ran to day 14 (144 calls) |
| hard 900000 | 0.60 | 0.50 | −0.10 | correct, day 14, 158 calls |
| hard 900001 | 0.67 | 0.62 | −0.05 | correct, day 8, 85 calls |
| hard 900002 | 0.71 | 0.46 | −0.25 | correct, day 13, 154 calls |
| **mean** | **0.757** | **0.503** | **−0.253** | below the solver on all 6 tasks |

Jobs: `results/harbor/g-oracle/` and `results/harbor/g-gemini-try2/` (medium 900000) plus `results/harbor/g-gemini-rest/` (the other 5). Every score is the server-side ledger's (`verifier/ledger.json`), and each trial keeps the agent's full OpenCode transcript (`agent/opencode.txt`). Harbor reports `NonZeroAgentExitCodeError` on most Gemini trials because OpenCode exits non-zero after the game has already ended. The ledgers show completed episodes, so the scores are real. This is a small sample (6 tasks, one run each): read it as a judge-path demonstration, not as the benchmark's gap estimate.

```bash
# the working command; the key must reach OpenCode as GOOGLE_GENERATIVE_AI_API_KEY
GOOGLE_GENERATIVE_AI_API_KEY=<your key> harbor run -p harbor/dataset -a opencode \
    -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 2
```

**Pitfall: the API key name.** OpenCode's Google provider reads only `GOOGLE_GENERATIVE_AI_API_KEY`. If you export only `GEMINI_API_KEY`, or export `GOOGLE_GENERATIVE_AI_API_KEY` without `--api-key-name`, Harbor does not forward the key. OpenCode then fails with `AI_LoadAPIKeyError` before its first model call, and every trial ends at reward 0 with `NonZeroAgentExitCodeError`. Those zeros are infrastructure failures, not model results, and we did not commit them as results.

**Running the anti-cheat solutions (INTEGRITY):**
```bash
uv run --python 3.12 python harbor/build.py --tiers medium,hard --seeds 900000 --out harbor/dataset-cheat
harbor run -p harbor/dataset-cheat -a oracle --ae ORACLE_POLICY=cheat_probe -n 2 -o results/harbor --job-name cheat-probe   # must be exactly 0
harbor run -p harbor/dataset-cheat -a oracle --ae ORACLE_POLICY=cheat -n 1 -o results/harbor --job-name cheat               # -1, or V on a lucky guess
```
`harbor/dataset*/` is gitignored, because each build holds its world secret (`SALT`).

There are two cheat solutions:

- `cheat` (`harbor/template/solution/cheat.py`) tries the main out-of-band tricks and then accuses everyone, in parallel and in sequence. Exactly one accusation is accepted, so it ends at −1, or at V on a lucky 1-in-N guess.
- `cheat_probe` (`canary/redteam/harbor_cheat.py`, ported from Poisoned Inbox's `run_cheat`) **never accuses**, so any reward other than exactly 0 means a hole. It sits where an agent sits and tries:
  - **Grader routes:** `/ledger` and `/admin/reset` with no token, 16 guessed tokens, header/cookie tokens, and path/case/method tricks; likely debug paths.
  - **Secrets:** the token, SALT and episode files; `CANARY_*` variables; every `/proc/*/environ`.
  - **Reward files:** pre-written `/logs/verifier/reward.{txt,json}`; a fake ledger in `/evidence`, `/logs/verifier` and `/logs/artifacts`; a background process that rewrites the reward files for 15 minutes.
  - **MCP wire:** made-up tools (`score`, `verdict`, `set_reward`, `_t_accuse`, ...), hidden arguments on real tools, `resources/*` and `prompts/*`, and `accuse` with a list / `*` / object / comma string.

If an attack does get in, `cheat_probe` uses it: it reads the server ledger, narrows the mole down with canaries and accuses. So a real hole shows up as a reward above 0, not only as a log line. `tests/test_harbor_cheat.py` checks both directions against the real MCP server:

- the probe finds no hole, and the ledger score stays 0;
- with the ledger token planted on disk, the probe accuses the right person, and the score is above 0.

**`cheat_probe` verified through Harbor** (Harbor 0.25.0 on Docker Desktop / Windows 11, Saturday 14 Nov; medium + hard 900000, separate verifier). Job: [`results/harbor/cheat-probe/`](../results/harbor/cheat-probe/). The logs were scanned for the build secret (0 hits), and local paths were rewritten.

| | medium 900000 | hard 900000 |
|---|---|---|
| reward | **0.0** | **0.0** |
| `agent/cheat.json` | 130 attempts, `"holes": []` | 130 attempts, `"holes": []` |
| grader routes | 35 × 403, 21 × 404, 3 × 405, 1 × 307 | same |
| secrets | no file, no `CANARY_*` variable, nothing in `/proc` | same |
| reward files | 6 fakes planted and the 15-minute rewrite loop started; the separate verifier ignored them all | same |
| MCP | made-up tools → `unknown tool`, 8 unknown methods → method not found, hidden arguments → `invalid arguments`, 9 of 9 malformed accusations rejected | same |
| server ledger | `accused: null`, `score: 0.0` | same |
| isolation | `ISOLATION OK: 11 checks passed, 0 findings` | same |

The job had 0 exceptions and took 2 min 14 s. Harbor also copied two of the planted fakes (`score: 1.0`) out of `/logs/artifacts` in `main`, so they appear under `artifacts/logs/artifacts/` in the job. They are evidence of the attack, not results. The reward comes only from `artifacts/ledger.json`, which the sidecar collect hook writes.

Windows note: a Windows checkout with `core.autocrlf=true` gives the `.sh` files CRLF endings, and bash in the Linux containers rejects those. Convert the built `harbor/dataset*/` to LF before `harbor run` (this run did), or check out with `core.autocrlf=input`.
