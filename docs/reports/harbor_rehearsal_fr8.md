# Pre-Tag FR8 Harbor 0.26.0 Rehearsal (`canary-1`)

## Overview

End-to-end multi-container judge rehearsal executed on FR8 Linux host `canary-1` (Linux `6.8.0-149-generic`, Docker `29.1.3`, Harbor `0.26.0`) against one shared default judge build (`uv run python harbor/build.py`, frozen tiers `v1.4`, tier `hard`, judge seeds `900000-900009`, 10 tasks).

- **Build provenance (`results/harbor/rehearsal-fr8/BUILD.txt`):** commit `8cd20d9e0f92d88588b8a99f4d1aaa2260693f7e` (`describe: 8cd20d9e`), `built_utc: 2026-11-14T23:18:51Z`, `harbor: 0.26.0`, `agent_timeout_sec = 10800.0`.
- **Pre-tag code equivalence and Panel Fix D disclosure:** `8cd20d9e` predates Panel Fix D (`1bc3e281`, tagged `afterquery-final`) and `origin/justSilas` (`58716742`), with zero diff through `origin/justSilas` (`58716742`) across `canary/rules.py`, `canary/world.py`, `canary/solver/`, `harbor/build.py`, `harbor/template/`, and `harbor/check_isolation.sh`. Because `8cd20d9e` predates Panel Fix D (`1bc3e281`), these rehearsal trials ran before `1bc3e281` added `data.detail` on `"invalid arguments"` in `canary/env.py` (keeping the `"invalid arguments"` error string unchanged) and reworded the W1 careful-mole sentence in `canary/env.py` and `harbor/canary-task/instruction.md` (matching the post-run disclosure in [`README.md`](../../README.md) and [`docs/DIFFICULTY.md`](../DIFFICULTY.md)).
- **Shared world secret & separate HMAC-signed verifier:** all 7 jobs (70 trials) ran against the same build-time sidecar secret and separate verifier key, so every task `hard-900000` through `hard-900009` is strictly paired across jobs. The build directory `harbor/dataset/` (holding `SALT` and `ledger_key`) stays gitignored and uncommitted; packaged artifacts sit under `results/harbor/rehearsal-fr8/` (`results/harbor/rehearsal-fr8/TABLE.md`, `results/harbor/rehearsal-fr8/BUILD.txt`, and `results/harbor/rehearsal-fr8/<job>/`).

## Step A: Oracle, Baselines, and Anti-Cheat Probe (40/40 Valid)

All four deterministic/probe jobs ran 10/10 tasks with 0 retries, 0 infrastructure errors, 10/10 `ISOLATION OK: 11 checks passed, 0 findings` inside the `main` agent container, and 10/10 separate-verifier `signature=ok` checks:

| Job | Policy / Flag | Valid / Total | Accused (Correct) | Mean Reward | Verifier & Isolation |
|---|---|---:|---:|---:|---|
| `oracle` | reference solver over MCP (`-a oracle`) | 10 / 10 | 10 / 10 (10 correct) | `+0.601` | 10/10 `signature=ok`, 10/10 `ISOLATION OK` |
| `do_nothing` | `ORACLE_POLICY=do_nothing` | 10 / 10 | 0 / 10 | `+0.000` | 10/10 `signature=ok`, 10/10 `ISOLATION OK` |
| `stop_early` | `ORACLE_POLICY=stop_early` | 10 / 10 | 0 / 10 | `+0.000` | 10/10 `signature=ok`, 10/10 `ISOLATION OK` |
| `cheat_probe` | `ORACLE_POLICY=cheat_probe` | 10 / 10 | 0 / 10 | `+0.000` | 10/10 `signature=ok`, 149 attempts/trial, 0 failed controls, 0 holes |

## Step B: OpenCode `google/gemini-4-carbon` (`-n 2` x 3 Jobs)

Three independent Harbor jobs (`opencode-1`, `opencode-2`, `opencode-3`) ran `-a opencode -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY --agent-setup-timeout-multiplier 4 --max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError` at concurrency `-n 2` per job (staggered so live trials stayed within the Gemini token-per-minute budget).

- Across 30 scheduled trials (3 x 10), **10 trials completed valid episodes** (`ledger.done = true`) and **20 trials terminated as `infra (provider rate limit)`** (`ApiRateLimitError` after 16, 14, and 12 Harbor retries respectively, with `ledger.done = false` and no accusation). No `<job>-infra-rerun` pass was launched after Gemini API quota exhaustion.
- **10/10 valid OpenCode trials caught the mole** (`correct = true`), accusing the exact culprit verified by `oracle` (`e15` on `hard-900000`, `e39` on `hard-900001`, `e24` on `hard-900002`, `e32` on `hard-900003`). Nine of the ten valid OpenCode trials recorded Harbor's post-game `NonZeroAgentExitCodeError` after `ledger.done = true`; per the pre-registered rehearsal protocol, completed server ledgers are valid results.
- **Run-to-run spread (3 OpenCode runs, valid-trial means):** `+0.647`, `+0.543`, `+0.527` -> **mean of means `+0.572`, SD `0.065`, range `0.119`**.

## Per-Task Matrix (`scripts/rehearsal_table.py`)

| task | oracle | opencode-1 | opencode-2 | opencode-3 | do_nothing | stop_early | cheat_probe |
|---|---:|---:|---:|---:|---:|---:|---:|
| hard-900000 | +0.68 ok d7 | +0.59 ok d18 | +0.41 ok d21 | +0.24 ok d20 | +0.00 | +0.00 | +0.00 |
| hard-900001 | +0.21 ok d16 | +0.65 ok d9 | +0.60 ok d11 | +0.47 ok d12 | +0.00 | +0.00 | +0.00 |
| hard-900002 | +0.72 ok d6 | +0.70 ok d10 | infra (provider rate limit) | +0.71 ok d8 | +0.00 | +0.00 | +0.00 |
| hard-900003 | +0.73 ok d9 | infra (provider rate limit) | +0.62 ok d8 | +0.69 ok d12 | +0.00 | +0.00 | +0.00 |
| hard-900004 | +0.72 ok d6 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900005 | +0.50 ok d16 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900006 | +0.58 ok d10 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900007 | +0.48 ok d12 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900008 | +0.71 ok d7 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900009 | +0.68 ok d8 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| **mean (valid trials)** | **+0.601** | **+0.647** | **+0.543** | **+0.527** | **+0.000** | **+0.000** | **+0.000** |

Note: on `hard-900001`, `oracle` accused `e39` on day 16 (`+0.21`) while `opencode-1..3` accused `e39` earlier on days 9-12 (`+0.65`, `+0.60`, `+0.47`), lifting the 3-task matched subset ratios on `opencode-1` and `opencode-2`; on `hard-900000`, `hard-900002`, and `hard-900003`, `oracle` matched or beat every OpenCode run.

## Paired Ratios vs `oracle` and Infra-Counted-as-0 Means (`scripts/rehearsal_table.py`)

| run | n valid | infra (excluded) | correct / accused | mean | oracle, same tasks | run / oracle [95% paired bootstrap CI] | diff | mean, infra as 0 |
|---|---:|---:|---|---:|---:|---|---:|---:|
| opencode-1 | 3 | 7 | 3 / 3 | +0.647 | +0.537 | 120% [87%, 310%] | +0.110 | +0.194 |
| opencode-2 | 3 | 7 | 3 / 3 | +0.543 | +0.540 | 101% [60%, 286%] | +0.003 | +0.163 |
| opencode-3 | 4 | 6 | 4 / 4 | +0.527 | +0.585 | 90% [52%, 154%] | -0.057 | +0.211 |
| do_nothing | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |
| stop_early | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |
| cheat_probe | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |

Run-to-run spread over 3 OpenCode runs: run means `+0.647`, `+0.543`, `+0.527`; mean of means `+0.572`, SD `0.065`, range `0.119`.

## Artifact & Consistency Verification

- `canary.redteam.anticheat.harbor_consistency`: **70/70 trials and 7/7 job summaries consistent** (`reward.json` == `reward.txt` == sidecar `artifacts/ledger.json` == verifier ledger copy; 70/70 graded with `signature=ok`; 29 OpenCode trials have `agent/opencode.txt` trajectories and every accused trial names the same culprit in the trajectory and server ledger; 10/10 `cheat_probe` trials report 0 holes and score `+0.000`).
- Reproduction table command once `results/harbor/rehearsal-fr8/` is present:
  ```bash
  python scripts/rehearsal_table.py results/harbor/rehearsal-fr8
  ```
