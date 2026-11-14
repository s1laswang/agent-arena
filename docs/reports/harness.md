# HARNESS report

## 03:05 head summary (HEAD-HARNESS, reviewer/QA role)
- Tiers v1.2 FROZEN (db104c9). The fresh-clone check (~05:00), the reproduce/README numbers and Harbor instruction.md must all use v1.2 and the regenerated instruction.md (relayed to the repro and harbor branches).
- The repro branch already has the parse_seeds fix (a73b283): bare N > 1000 is one seed, plus a 10k cap. Review pending.
## 02:30 status
- Head was blocked on a permission prompt from 01:55 to 02:25. CEO reassigned the build work: eval.py and mcp_server.py are merged (f2931d4); repro/README/CI is on justSilas-harness-repro; Harbor and isolation are on justSilas-harness-harbor (engineers in the CEO session).
- Head role from now on: review and QA of eval/MCP (issues go to the CEO), a fresh-clone reproduce at about 06:30, and this summary.
- Blockers: none.
- Next 45 min: review canary/eval.py and canary/mcp_server.py, run make test, report issues.

## 02:45 status
- Done (verified: ran): `make test` 338 passed. Live MCP server medium/900003 + `--play solver` over MCP → accused correctly, ledger score 0.64; /ledger 403 without/with wrong token; second session gets "episode over".
- Finding P0 (sent to CEO): no committed SALT / CANARY_WORLD_SECRET → judge worlds re-randomise per process (solver medium/900003: 0.65, 0.43, 0.79, 0.0 in separate runs). `make reproduce` can't give exact numbers until SALT is committed and reproduce fails closed.
- Finding P1: one in-process solver episode ran >4 min / 1.9 GB before I killed it (others 0.02 s) → solver needs a guard.
- Finding P2: `--reproduce` still a stub (repro engineer); LLM agents only via MCP; ledger_payload uses Env private attrs.
- Next: review the harbor/repro branches as they land; fresh-clone reproduce at about 06:30.

## 02:55 decisions (CEO)
- SALT will NOT be committed (public repo + internet in agent containers = answer key). `make reproduce` uses one random secret per invocation shared by all its runs (paired comparison; statistical repro, exact with CANARY_WORLD_SECRET) → repro engineer, plus a fixed-secret two-subprocess determinism test. Harbor bakes a build-time secret into the server image only (harbor/build.py, never committed) → harbor engineer.
- Solver guard + 1.9 GB root-cause → ENV. Public env.verdict() → ENV.
- QA follow-up for me: the README must state expected numbers as mean ± CI (not exact), and the fresh-clone check must verify the gap holds across two different secrets.

## 02:55 P1 resolved (not a solver bug)
- Root cause (verified): `parse_seeds('900003')` returns `range(900003)`, because a bare integer means "N seeds". `--seeds 900003` therefore queues 900,003 episodes. Reproduced 6/6 (60 s timeout, about 1 GB RSS). run_episode itself is fine. Fix + test routed to the repro engineer via the CEO; ENV told to stand down.
- The fresh-clone check moves to about 05:00 (clock correction).

---
# Engineer sections

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
  - **These numbers must be refreshed after the v1.2 freeze.**
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

### Untested / open
- CI on GitHub (first run on the push to justSilas). A Linux-only failure in another department's tests is possible.
- No committed frontier runs yet. AGENTS should write `data/runs/committed/<run_id>/episodes.jsonl` (EpisodeResult lines; steps may be empty), ideally on judge seeds. The table marks non-judge seeds.
- The README numbers must be refreshed whenever ENV changes the solver or the tiers: run `python /tmp/canary_spread.py 30`, or just `make reproduce` and use its CI.
- `test_integrity_hunter.py::test_stub_hunt_fake_server_plumbing` still fails intermittently under load (INTEGRITY's code).
