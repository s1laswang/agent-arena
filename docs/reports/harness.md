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

- **Tiers v1.2 (db104c9) merged** (justSilas at bca5406 includes this branch). `build.py` renders each task's
  instruction.md as preface + `Env(tier, 0).instruction()` at build time: verified equal to `Env(tier, 900017).instruction()`
  for easy/medium/hard, medium equal to the committed `harbor/canary-task/instruction.md`, hard shows
  `fingerprint_accuracy: 0.95`, `framing_rate: 2`. Full dataset: `python harbor/build.py` wrote 120 tasks in 4 s (139 MB, gitignored).
  Rerun on the final merged code (v1.2 tiers + exact-fingerprint solver), same secret file, `harbor run -p <2 tasks> -a oracle -n 2`:
  medium/900000 reward 0.79, hard/900000 reward 0.81, both accused correctly on day 6, both ISOLATION OK (11 checks). colima stopped afterwards.

### Notes for other owners
- The `*_FILE` interface landed in `mcp_server.py` during this work and the sidecar uses it; nothing else needed.
- colima was stopped after the runs (`colima stop`); restart with `colima start --cpu 2 --memory 3` to rerun.

## 02:37 reproduce-docs engineer (branch justSilas-harness-repro)

### Done (verified)
- **`make reproduce` = `python -m canary.eval --reproduce`** (new `canary/reproduce.py`; `canary/eval.py` adds `--repro-seeds`, `--results-dir`).
  - It runs solver, heuristic, logs_only, random, stop_early and do_nothing on all 40 JUDGE_SEEDS × medium/hard/easy, in-process. That is 720 episodes in about 2 s, so no multiprocessing is needed.
  - It writes `results/judge_table.md` (per tier: n, mean ± 95% CI, accuracy, accused, mean accuse day, / solver, pass^k), `results/judge_episodes.jsonl` (per-episode rows) and `results/gap_chart.png`. matplotlib is the new optional `plot` extra; without it the chart is skipped and a note is printed.
  - **Secret:** with no `CANARY_WORLD_SECRET`/SALT, the run draws ONE random secret (`secrets.token_hex(32)`) per invocation and shares it across all agents, so the runs are paired. It prints only the sha256 fingerprint plus "statistical reproduction; set CANARY_WORLD_SECRET for exact numbers", and removes the secret from `os.environ` afterwards.
  - **Committed agent runs:** episodes in `data/runs/committed/**/episodes.jsonl` appear in a separate "Reported agent runs (replayed, unpaired, own CI)" block with pass^k. Until AGENTS commit runs, the block shows "pending". `.gitignore` now tracks `data/runs/committed/`.
  - **Per-episode timeout guard:** SIGALRM, 60 s by default (`REPRO_EPISODE_TIMEOUT`). A timed-out episode scores 0, is listed in the table header, and is tagged `end_reason=timeout`. None fired in any run.
  - **Seed control:** `REPRO_FAST=1` gives 5 seeds/tier and is labelled FAST MODE; `REPRO_SEEDS=N` and `--repro-seeds N` also work.
- **`make setup`** prints a uv install hint (exit 127) when uv is missing, and installs `--extra plot`. `make reproduce` no longer prints TODO.
- **tests/test_reproduce.py: 12 tests**, all passing.
  - Outputs, every agent on every tier, and the do_nothing/stop_early invariants.
  - Pending frontier rows; a replay with repeated runs gives pass^3; the reported block is separate.
  - Exact mode is bit-for-bit in-process, and **two subprocesses with a fixed secret give identical judge_episodes.jsonl** (CEO request).
  - A keyless run never writes a 64-hex secret and removes the env var.
  - The timeout guard; the seed-count env vars; the chart is skipped without matplotlib; the CLI.
- **Variance across secrets:** 30 keyless runs (`/tmp/canary_spread.py 30`).
  - At 33f4454: solver medium +0.51 [+0.40, +0.59], hard +0.56.
  - At 9c36218 (solver fix + tiers v1.1): solver medium +0.63, hard +0.60.
  - At 849e652 (plus the bounded-DP solver and Env.verdict), which are the README "expected" numbers:
    - solver mean-of-means: medium **+0.63** [+0.56, +0.71], hard **+0.62** [+0.54, +0.69], easy +0.78 [+0.75, +0.82];
    - heuristic: medium −0.03 [−0.22, +0.22], hard −0.21 [−0.42, −0.06];
    - logs_only: medium −0.98, hard −1.00;
    - do_nothing is exactly 0 in every run.
  - After merging 92459d3 (solver: exact fingerprint likelihood), the results are byte-identical to 849e652 with a fixed secret (`cmp`), so the README numbers still hold.
  - **After the tiers v1.2 freeze (f85f21c), which are the README numbers now:**
    - solver: medium **+0.64** [+0.52, +0.71], hard **+0.62** [+0.51, +0.72], easy +0.77;
    - heuristic: medium +0.00 [−0.32, +0.27], hard −0.22 [−0.50, +0.04];
    - logs_only: medium −0.97, hard −1.00 (all 30 runs);
    - do_nothing is exactly 0.
  - **FINAL, frozen v1.2 (db104c9: hard fingerprint .95, framing 2.0), merged as edffdac. The README now shows:**
    - **The committed run** (fingerprint d7e45dc56304), mean ± CI:
      - medium: solver **+0.648 ± 0.074** (acc .90), heuristic +0.046 ± 0.242, logs_only −0.958, random −0.588, stop_early −0.950, do_nothing 0;
      - hard: solver **+0.624 ± 0.079** (acc .88), heuristic −0.262 ± 0.256, logs_only −0.865, random −0.800, stop_early −0.850, do_nothing 0;
      - easy: solver +0.774 ± 0.045.
    - **Spread over 30 fresh secrets:**
      - solver means: medium +0.62 [+0.52, +0.68], hard +0.55 [+0.39, +0.65], easy +0.78;
      - heuristic: medium −0.01 [−0.32, +0.37], hard −0.27 [−0.55, 0.00].
    - **Note for the CEO:** across secrets, the heuristic's best medium run (+0.37) comes within the solver's worst run (+0.52) by a margin smaller than either CI. The medium gap rests on the mean, not on every draw.
- **Full-size determinism:** with `CANARY_WORLD_SECRET=det-full-check`, two separate `--reproduce` processes (40 seeds × 3 tiers) gave a byte-identical `judge_episodes.jsonl` (`cmp`).
  - **Caveat for ENV:** `SolverPolicy(act_budget=0.3)` caps the canary-split search by wall clock (`perf_counter`). On a much slower machine (CI, a judge laptop) the budget could bind and change the solver's choices, so bit-for-bit equality across machines is not guaranteed. Suggestion: make the cap count-based (nodes or iterations), or keep it far above the observed search time.
- **Secret handling (after ENV's `world.set_world_secret`):** a keyless reproduce now installs its `os.urandom(32)` secret in-process via `set_world_secret`, so it is never in `os.environ` (cf. #25). Any earlier in-process secret is cleared while an explicit `CANARY_WORLD_SECRET` is in use, then restored (test added).
- **README rewrite:**
  - the 5-line pitch, the one command `make setup && make reproduce` (uv prerequisite stated) and expected numbers with ranges;
  - why the numbers are statistical, plus exact-match instructions;
  - the rules and the reward (V / −1 / 0: do-nothing = 0, guessing < 0);
  - MCP how-to (from configs/README.md), with Harbor linked to harbor/README.md (owned by another engineer, not yet on justSilas);
  - an integrity summary linking EXPLOITS.md, real-world grounding, a Gemini placeholder linking pitch/GEMINI.md, and a CI badge.
  - **Citations verified by web search:**
    - canary trap = Clancy, *Patriot Games* (1987); *Spycatcher* "barium meal test" (Wikipedia: Canary trap).
    - Tesla: the confirmed story is **2008**, not 2018. In 2022 Musk said Tesla sent apparently identical emails, each coded with one or two spaces between sentences (The Intercept, 2022-12-15). Wikipedia says the scheme was undone when a copy was forwarded. The README states both; no 2018 claim is made.
- **CI:** `.github/workflows/ci.yml` runs on ubuntu-latest with astral-sh/setup-uv@v6: `make setup`, `make test`, `REPRO_FAST=1 make reproduce`, then uploads the fast table. It triggers on push to justSilas, on PRs and by workflow_dispatch, with a 15-min timeout. The repo is private, so the README badge renders only for signed-in members. Actions are enabled (`gh api .../actions/permissions`). **Not yet observed running on GitHub**: the first run happens on the push to justSilas.
- **Fresh-clone check** (`/tmp/canary_fresh_clone.sh`): `git clone --branch justSilas-harness-repro` (111484b) into /tmp/canary-fresh, no `.env`, CANARY_WORLD_SECRET/OPENAI/GEMINI keys unset.
  - clone 1.5 s; `make setup` exit 0 in 0.5 s (warm uv cache); `make reproduce` exit 0 in 8.5 s.
  - With an empty uv cache (`UV_CACHE_DIR=/tmp/canary-uvcache`): `make setup` 2.9 s, `make reproduce` 8.6 s. Python 3.12 was already present on this Mac.
  - Fresh-clone solver: medium +0.526 ± 0.089, hard +0.532 ± 0.116, easy +0.771 ± 0.039, all inside the README ranges at that commit. All three results files were written.
  - **Re-run on the final branch head 5ff950b:**
    - clone 1.2 s; `make setup` exit 0 in 0.6 s (warm cache); `make reproduce` exit 0 in 5.5 s;
    - cold uv cache: `make setup` 2.8 s, `make reproduce` 5.6 s;
    - solver medium +0.593 ± 0.090, hard +0.573 ± 0.099, easy +0.804 ± 0.034, all inside the README ranges.

### Commands run
`make setup`; `make test`; `make reproduce` (×4); `uv run ... pytest -q tests/test_reproduce.py`; `python /tmp/canary_spread.py 10` and `... 30`; `CANARY_WORLD_SECRET=cmp-secret` CLI vs in-process comparison (identical); `bash /tmp/canary_fresh_clone.sh`; `bash /tmp/canary_cold_setup.sh`.

- **parse_seeds fix (CEO request):**
  - A bare N ≤ 1000 is a count; a larger N is a single seed (`900003` → `[900003]`). `n:N` is an explicit count, and `a-b` / `a,b` work as before.
  - Expansions over 10,000 seeds, or seeds × tiers over 10,000 in the CLI, are rejected with exit 2 and a clear message.
  - 3 new tests in tests/test_eval.py (12 cases).
- **Merged to justSilas** at b17d269 (fast-forward). `make test`: 385 passed, 3 skipped (exit 0).

### Untested / open
- **CI has never run on GitHub.** After the push to justSilas (b17d269), `gh api repos/s1laswang/agent-arena/actions/workflows` and `.../actions/runs` both report total_count 0, although Actions show as enabled.
  - Possible causes: a private repo with no Actions minutes or billing, or a workflow that must also be on the default branch (`main`, which we must not touch).
  - Silas should check Settings → Actions / Billing.
  - The workflow file itself is untested on GitHub.
- No committed frontier runs yet. AGENTS should write `data/runs/committed/<run_id>/episodes.jsonl` (EpisodeResult lines; steps may be empty), ideally on judge seeds. The table marks non-judge seeds.
- The README numbers must be refreshed whenever ENV changes the solver or the tiers: run `python /tmp/canary_spread.py 30`, or just `make reproduce` and use its CI.
- `test_integrity_hunter.py::test_stub_hunt_fake_server_plumbing` still fails intermittently under load (INTEGRITY's code).
