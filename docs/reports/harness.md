# HARNESS report

## 02:37 status (mcp-server engineer, filling in for HEAD-HARNESS)

### Done (verified)
- **EXPLOITS #25 closed on the server side.** canary/mcp_server.py reads `CANARY_EPISODE_FILE` (JSON {tier,seed}), `CANARY_WORLD_SECRET_FILE`, `CANARY_LEDGER_TOKEN_FILE` and `CANARY_ADMIN_TOKEN_FILE`. These are 0600 files read at startup; a file wins over its plain env var, and the plain vars still work for local dev.
  - The world secret goes to canary.world in-process through ENV's new `world.set_world_secret` (checked before CANARY_WORLD_SECRET and SALT; must be >= 16 bytes) and is never exported.
  - A missing, empty or malformed file makes the server exit 2 without echoing the contents.
  - Verified: `pytest -rA tests/test_integrity_secrets.py` shows `test_25_server_environ_holds_no_secrets` PASSED. The strict xfail flipped automatically. `tests/test_mcp.py` (14 passed) adds two tests:
    - the files configure the episode and the world: the server with the secret file matches an in-process Env with the same secret, step for step, and the file token beats the plain token;
    - a bad episode file is refused without echo.
- `/ledger` now reads ENV's public `Env.verdict()` instead of private attributes.
- `set -o pipefail; make test`: 355 passed, 3 skipped.

### Untested / open
- Unchanged from 02:20: no real-model OpenCode or Codex episode yet, no Harbor task, `--reproduce` still TODO.

## 02:20 status (mcp-server engineer, filling in for HEAD-HARNESS)

### Done (verified)
- **`canary/eval.py` merged to justSilas (9fd44cc).**
  - `run_episode(env, policy, max_iters=1000) -> EpisodeResult`. Stops at 1000 iterations with `end_reason="error"`; a policy exception ends the episode with "error" and `meta["error"]`.
  - CLI: `python -m canary.eval --agent <baseline|heuristic|solver> --tier easy|medium|hard|all --seeds N|dev20|judge|a-b|a,b --provider template [--out data/runs]` writes `data/runs/<run_id>/episodes.jsonl` + `meta.json` (agent, model, provider, tier, seeds, git sha, timestamp, summary). It prints signed mean ± 95% CI (negative means work), accuracy, number accused and mean accusation day.
  - `openai:`/`gemini:` agents and an unknown agent exit with code 2 and a clear message. `--reproduce` prints TODO.
  - Verified with `pytest tests/test_eval.py` (12 passed), `make eval AGENT=do_nothing TIER=easy SEEDS=3` (score +0.000), `make reproduce` (prints TODO) and `python -m canary.eval --agent solver --tier all --seeds 5`. Solver scores: easy +0.838±0.031, medium +0.760±0.057, hard +0.762±0.070, accuracy 1.00. `--agent stop_early --tier easy --seeds dev20` scores -0.900±0.196.
- **`canary/mcp_server.py`** (streamable HTTP, mcp 2.3.0 low-level `Server`).
  - Tools come from `Env.tools_spec()` 1:1 (names, descriptions, JSON schemas). Raw args are forwarded to `Env.call`, so the server has no second validator.
  - Each tool returns `{ok,data,error}` as JSON text plus structured content. The rules are sent as MCP `instructions`.
  - `Env.call` runs under a lock.
  - `GET /ledger?token=` (403 if the token is missing or wrong, always 403 if `CANARY_LEDGER_TOKEN` is unset). Optional `POST /admin/reset?token=` (needs `CANARY_ADMIN_TOKEN`). `GET /healthz`.
  - **Seed gate (INTEGRITY #23/#24):** only judge/held-out seeds are served unless `CANARY_ALLOW_DEV=1`. The server refuses to start (exit 2) otherwise, and reset returns 400. The seed is never logged or returned.
  - Verified by `pytest tests/test_mcp.py` (12 passed):
    - tools/list equals tools_spec and instructions equal `Env.instruction()`;
    - do_nothing, stop_early (x2) and solver (hard) over MCP give step-by-step identical results and the same score as in-process;
    - env error strings pass through unchanged;
    - no seed in output, and accuse reveals no correctness;
    - ledger/admin return 403 without a token;
    - 8 parallel accuse threads record exactly 1 accusation and the other 7 get "episode over";
    - a fresh process configured from env vars matches in-process;
    - a dev seed is refused without ALLOW_DEV, and a judge seed is served.
  - Also run by hand: `CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=... make mcp`, then `python -m canary.mcp_server --play solver` (75 calls, correct, ledger score 0.66).
- **`configs/opencode/opencode.json`** (remote MCP pointing at `http://127.0.0.1:8765/mcp`, oauth off). Verified with `opencode mcp list` (OpenCode 1.18.29), which showed "canary connected". `configs/README.md` explains how to run an agent and read the ledger.
- `tests/conftest.py` sets `CANARY_ALLOW_DEV=1` for the test session, because INTEGRITY's real-server tests use dev seed 7. `make test`: 332 passed, 3 skipped, 7 xfailed, 2 xpassed.

### Untested
- A full OpenCode or Codex agent episode with a real model (not run, to save keys; AGENTS will run it). The Codex `-c mcp_servers.canary.url=...` line in configs/README.md is untested.
- `CANARY_PROVIDER=gemini:*` through the server.
- Harbor task and isolation (not started).

### Notes / blockers
- `tests/test_integrity_hunter.py::test_stub_hunt_fake_server_plumbing` (INTEGRITY's fake server) failed once in 4 full-suite runs and passed on rerun. It looks flaky; it is not in HARNESS code.
- Judge seeds give the same world across server restarts only with `CANARY_WORLD_SECRET`/SALT (ENV's fail-closed change), so in-process comparisons on judge seeds need the same secret.

### Next
- `--reproduce` (judge table), Harbor task + isolation check, README.

## 02:45 harbor-isolation engineer

Branch `justSilas-harness-harbor`. Files: `harbor/README.md` (Harbor research (a)-(d) with sources, design, fallbacks),
`harbor/build.py`, `harbor/template/`, `harbor/check_isolation.sh`. `harbor/dataset/` (generated) is gitignored.

### Design
- One Harbor task per (tier, judge seed), built by `python harbor/build.py` (default 3 tiers x 40 judge seeds).
- Agent container `main`: python:3.12-slim + curl/procps + `/app/opencode.json`. No canary code, no data, no secret.
  The MCP server is declared in task.toml `[[environment.mcp_servers]]` (streamable-http,
  `http://canary-server:8765/mcp`); Harbor writes it into OpenCode's config.
- Sidecar `canary-server` (compose, own filesystem + PID namespace, uid 10001): vendored `canary/`, the **build-time
  world secret** as a 0600 file `data/worlds/judge/SALT` and `episode.json` {tier, seed}, a ledger token made at start
  into a 0600 file; the server reads all three via `CANARY_*_FILE` (EXPLOITS #25), so its environ holds none of
  them (checked: 0 of SEED/TIER/LEDGER_TOKEN/WORLD_SECRET in the sidecar's `/proc/1/environ`). One server container per trial.
- Grading: separate verifier. Harbor stops `main`, runs `[[verifier.collect]]` inside the sidecar (`collect.py` GETs
  `/ledger` with the token on localhost), ships `/evidence/ledger.json` as an artifact, and `tests/test.sh` writes
  `ledger["score"]` to `/logs/verifier/reward.txt` (negative allowed).
- Oracle `solve.sh` runs `check_isolation.sh --oracle-run`, then `python -m canary.mcp_server --play $ORACLE_POLICY`
  (default solver; `--ae ORACLE_POLICY=do_nothing|stop_early` gives the judges' baselines through the same path).

### Verified (Harbor 0.26.0, colima 2 CPU / 3 GB, Docker 29.5.2)
- `harbor lint <task>`: exit 0, no findings. task.toml validates with Harbor's `TaskConfig`.
- Oracle end to end through Harbor (`harbor run -p <task> -a oracle -o jobs -n 1 -y`), medium 900000, one fixed
  build-time secret:

  | run | reward.txt | ledger | isolation (inside `main`) |
  |---|---|---|---|
  | solver | 0.79 | accused day 6, correct | ISOLATION OK, 11 checks |
  | solver again (same build) | 0.79 | identical (paired world) | ISOLATION OK |
  | do_nothing | 0.0 | horizon, day 14 | ISOLATION OK |
  | stop_early | -1.0 | wrong accusation day 1 | ISOLATION OK |

  Two earlier builds (different random secrets) gave 0.56 and 0.52: the world follows the build-time secret.
  After switching the sidecar to the `*_FILE` interface (same secret file): solver 0.79 again, stop_early -1.0,
  both ISOLATION OK. Strict check in `main` of that build: ISOLATION OK, 11 checks.
- **One OpenCode run (not through Harbor):** host OpenCode 1.18.29 (`opencode run -m openai/gpt-5.6-sol`, ChatGPT
  login) against the same containerized sidecar (port published to 127.0.0.1:18765 for this test only), prompt =
  the task's instruction.md. 46 MCP tool calls; it planted single-recipient canary variants and accused e11 on
  day 5: **ledger score 0.84, correct** (collected with the sidecar's own collect hook). The solver scored 0.79 on
  the same world. One seed only, but on this world the agent beat the reference (flag for ENV/CEO: the gap).
- `check_isolation.sh` in strict mode (no `--oracle-run`) inside `main` of a Harbor-equivalent compose stack (Harbor's
  `docker-compose-build.yaml` + our compose): **ISOLATION OK, 11 checks, 0 findings**. Manual probe: 0 files in
  `/proc/*/environ` contain `CANARY_`, `ps` shows only `sleep infinity` and the probe.
- Negative control: the same script inside the sidecar reports 6 findings (SALT, source, `import canary`, CANARY_* env,
  server cmdline, CANARY_ in `/proc/1/environ`) and fails. The check also caught our own first oracle selector
  `CANARY_ORACLE_AGENT` (env + 3 environs), now renamed `ORACLE_POLICY`.
- From `main`: `/healthz` 200, `/ledger` without or with a wrong token 403; `/admin/reset` disabled (no admin token).
- `make test` after merging origin/justSilas: 353 passed, 3 skipped, 1 xfailed (exit 0). A first run under Docker load
  had 1 flaky failure in `tests/test_integrity_hunter.py::test_stub_hunt_fake_server_plumbing`; it passed alone and on rerun.

### Untested / caveats
- `harbor run -a opencode` inside Harbor: needs `OPENAI_API_KEY` on the host (Harbor forwards it into `main`). The
  laptop's OpenCode ChatGPT login does not carry into the container, and no key was added tonight.
- Only medium/900000 was run through Harbor; all 120 tasks are generated by the same code path.
- Providers without compose (e2b, runloop, ...) can't run this task; see the fallback table in harbor/README.md.

### Notes for other owners
- The `*_FILE` interface landed in `mcp_server.py` during this work and the sidecar uses it; nothing else needed.
- colima was stopped after the runs (`colima stop`); restart with `colima start --cpu 2 --memory 3` to rerun.
