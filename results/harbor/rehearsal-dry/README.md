# Dry judge rehearsal (Sat 14 → Sun 15 Nov, before the `afterquery-final` tag)

This was a dry run of the judges' Harbor sequence, done to find harness breakage before the real rehearsal (`../rehearsal/`). It ran **one** OpenCode run, not three, so it says nothing about a gap. Treat it as a harness check.

- **Code:** `be435fd5`. That is justSilas `512836b9`, which sets the agent timeout to 10800 s, plus PR #26 (replay fix and docs; no change under `harbor/template`).
- **Build:** `python harbor/build.py` with no flags: hard, judge seeds 900000–900009, a fresh world secret, and HMAC ledger signing. This build is retired. Its signing key is published as `<job>/ledger_key` so that the trials' signatures can be re-checked. The world secret (SALT) is not published.
- **Platform:** Harbor 0.26.0 on colima, 4 CPU / 8 GB, on a heavily loaded laptop.
- **Scans:** every log was scanned for the build's SALT and the Gemini key (0 hits). Local absolute paths were rewritten to repo-relative paths or `~`.

## Result
See [`TABLE.md`](TABLE.md), produced by `python scripts/rehearsal_table.py results/harbor/rehearsal-dry`.

| job | n | mean | notes |
|---|---:|---:|---|
| oracle (reference solver over MCP) | 10 | **+0.467** | 9/10 correct; one wrong accusation (900000, day 16) |
| OpenCode gemini-4-carbon | 10 (7 + 3 infra reruns †) | **+0.398** | 9/10 correct; one wrong accusation (900005, day 16); 85% of the oracle [11%, 355%], n=10 |
| do_nothing | 10 | 0.000 | exactly 0 on every task |
| stop_early | 10 | 0.000 | exactly 0 on every task |

Integrity:
- All 43 trials pass `canary.redteam.anticheat.harbor_consistency`. Each trial's ledger, reward and HMAC (checked with the published key) agree.
- For all 13 OpenCode trials, the agent's trajectory names the same accused employee as the ledger.
- The jobs' summaries match their trials.

## Harness findings, and what changed
1. **`AgentSetupTimeoutError` on every OpenCode trial: fixed with a flag.**
   - Cause: Harbor's `opencode` agent installs nodejs/npm (apt), nvm/Node and `opencode-ai` in every agent container within a fixed 360 s. At `-n 5` on this host, every install took longer.
   - Fix: `--agent-setup-timeout-multiplier 4`. `task.toml` cannot raise this limit. The flag is documented for judges in `harbor/README.md` and the README.
   - That first attempt is not committed. It produced 10 trials with no reward.
2. **Agent timeout.** The first OpenCode attempt on the earlier build (3600 s agent timeout) was stopped and rebuilt on `512836b9` (10800 s). The baselines were rerun on the new build so that every job plays the same worlds.
3. **3 of 10 OpenCode trials were infrastructure failures.** In each, the ledger was not done and there was no accusation.
   - 900006 and 900007: Gemini 429 on per-minute input tokens. The key was shared with other Gemini runs that night.
   - 900009: Gemini 400, "Function call is missing a thought_signature". OpenCode did not replay the signature.
   - All three were rerun once in `opencode-infra-rerun`, on the same build. Harbor retries were set to `--retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError`, and all 3 reruns are valid. This is the rule the real rehearsal fixed in advance (`../rehearsal/README.md`).
4. **The anti-cheat Harbor check did not see nested jobs.** It also did not know that Harbor leaves `ApiRateLimitError` / `AgentSetupTimeoutError` trials out of its job stats. Both are fixed, with tests, including a forged-exclusion negative.

## Wall time and cost
| job | start → end (Helsinki) | Gemini cost (Harbor's estimate) |
|---|---|---|
| OpenCode, 10 tasks, `-n 5` | 23:50 → 00:50 (60 min) | $9.86 |
| OpenCode infra rerun, 3 tasks, `-n 3` | 00:51 → 01:33 (42 min) | $3.04 |
| oracle / do_nothing / stop_early, `-n 2`, alongside | 23:50 → 00:06 | – |

Harbor reports `NonZeroAgentExitCodeError` on the OpenCode trials because OpenCode exits non-zero (EPIPE) after the game has ended. When the ledger is done, the score is real; see `harbor/README.md`.
