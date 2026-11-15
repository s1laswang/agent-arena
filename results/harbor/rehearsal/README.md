# Judge rehearsal (pre-registered protocol)

Written and committed **before the first run** (Sun 15 Nov ~01:15 Helsinki). The rule was approved by the Arena CEO.
The results and table are added below this protocol after the run. The protocol text itself is not edited afterwards.

## What runs
- **Code:** exactly the commit tagged `afterquery-final`. The SHA is written to `BUILD.txt` before the run.
- **Tasks:** `python harbor/build.py` with no flags, which builds the judge set: tier hard, judge seeds 900000–900009 (10 tasks). There is one build, so every job below plays the same 10 worlds. The world secret and ledger key stay in the gitignored `harbor/dataset/` and are never committed.
- **Jobs**, the judges' sequence, all on that one build:
  - `oracle`: the reference solver over MCP (`-a oracle`).
  - `opencode-1`, `opencode-2`, `opencode-3`: three independent OpenCode runs, `-m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY`.
  - `do_nothing`: `-a oracle --ae ORACLE_POLICY=do_nothing`.
  - `stop_early`: `-a oracle --ae ORACLE_POLICY=stop_early`.
- **Harbor 0.26.0 on colima (4 CPU / 8 GB).** The three OpenCode jobs run concurrently at `-n 3`, with `--agent-setup-timeout-multiplier 4`. The dry run lost all 10 trials at the default 360 s setup limit.
- **Launcher:** `scripts/rehearsal_run.sh`.
- **Scheduling amendment** (Sun 15 Nov ~01:50, before any run; this changes no scoring): the shared Gemini key's limit fell to 2M input tokens/min. A trial averages about 0.16M tokens/min, so about 6 OpenCode trials run at once:
  - `opencode-1` and `opencode-2` start at `-n 3`;
  - `opencode-3` starts at `-n 4` once runs 1 and 2 have 2 trials left.

  If time runs out before all 30 trials finish, the complete runs are reported, plus the finished trials of run 3, stated plainly. The infra rule below still applies to every trial.

## Infrastructure failures (fixed before the run)
1. **Automatic retries:** `--max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError`. These are only infrastructure exceptions. `NonZeroAgentExitCodeError` is **not** retried, because OpenCode raises it after finished games too.
2. **Infra trial:** a trial counts as infra if the server ledger is **not done** (no accusation, no horizon) and the cause is outside the agent's play. Such causes are:
   - Harbor's `ApiRateLimitError` or `AgentSetupTimeoutError`;
   - a CLI error event (`{"type":"error"}`) in `agent/opencode.txt`, for example a provider 429 or a rejected Gemini `thought_signature`.

   An agent that stops without an accusation and without such an error keeps its 0.
3. **One rerun:** each infra trial that remains after the retries gets **one** rerun, in a job named `<job>-infra-rerun`, on the same build. If the rerun is infra again, the task stays infra.
4. **No replacement of valid trials:** a valid trial (ledger done, or no infra cause) is never re-run or replaced.
5. **Reporting:**
   - The headline mean is over valid trials, as in `docs/reports/gap.md`.
   - The table also shows each run's mean with infra counted as 0, and it marks every rerun task with †.
   - Each run is compared with the oracle on the same tasks: ratio, paired bootstrap 95% CI, difference.
   - Run-to-run spread: the 3 run means, their SD and range.
   - Table: `python scripts/rehearsal_table.py results/harbor/rehearsal`.

## Not done
- No other reruns and no seed swaps.
- No exclusion of a valid trial for any reason, including a surprising score.
- The oracle and both baselines are not retried. Any exception there is reported as is.

---

# Results (added after the run; the protocol above is unchanged)

Code `afterquery-final` = `1bc3e281` (`BUILD.txt`). One build; every job played the same 10 hard judge worlds. Started 03:10 UTC (05:10 Helsinki).
Full table: [`TABLE.md`](TABLE.md) (`python scripts/rehearsal_table.py results/harbor/rehearsal`).

| run | n valid | infra | correct / accused | mean | vs the oracle on the same tasks |
|---|---:|---:|---|---:|---|
| oracle (reference solver over MCP) | 10 | 0 | 9 / 10 | **+0.506** | – |
| OpenCode gemini-4-carbon, run 1 | 10 | 0 | 9 / 10 | **+0.472** | 93% [20%, 371%] |
| OpenCode gemini-4-carbon, run 2 | 10 | 0 | 10 / 10 | **+0.585** | 116% [78%, 363%] |
| OpenCode gemini-4-carbon, run 3 | 9 | 1 | 9 / 9 | **+0.626** (+0.563 with infra as 0) | 131% [86%, 590%] |
| do_nothing | 10 | 0 | 0 / 0 | 0.000 | – |
| stop_early | 10 | 0 | 0 / 0 | 0.000 | – |

Run-to-run spread over the 3 OpenCode runs: run means +0.472, +0.585 and +0.626. The mean of means is +0.561, SD 0.080, range 0.154.

**Honest reading: this rehearsal shows no gap.**
- On these 10 judge worlds, OpenCode gemini-4-carbon matches the reference solver.
  - Runs 2 and 3 score above the oracle.
  - 28 of the 29 valid accusations were correct.
  - The oracle's mean includes one wrong accusation (900007, −1.00).
- Only run 1 is below the oracle. Its gap comes from a single wrong accusation (900002, day 14).
- Do not claim that each run is below the oracle. The committed v1.4 OpenCode result (hard, n=30 dev seeds, 65% [24, 98]) is a different, larger sample. This rehearsal does not replicate that gap at n=10.
- The baselines behave as specified: do_nothing and stop_early score exactly 0 on all 10 tasks.

Integrity and infrastructure:
- **Retries and infra.** One infra trial: run 3, 900002, Gemini 429 (`ApiRateLimitError`) after Harbor's retries. It is excluded from the headline and counted in the "infra as 0" column. Its one infra-rerun was **not** done: the run finished after the cut-off, with the submission deadline minutes away.
- **Cut-off (08:30 Helsinki = 06:30 UTC), stated plainly.**
  - Run 2 finished at 05:21 UTC and run 1 at 06:10 UTC, both complete before the cut-off.
  - Run 3 (started 05:14 UTC) finished 5 trials before the cut-off: 900000, 900001, 900003 and 900004 valid, plus 900002 infra. The other 5 trials (900005–900009) finished between 06:31 and 07:23 UTC.
  - Under the pre-registered rule, the cut-off report is runs 1 and 2 plus run 3's 4 valid trials. Its mean on those trials is +0.710, against the oracle's +0.690 on the same tasks. The full run 3 is shown above, labelled as finishing after the cut-off. No trial was dropped or re-run.
- **Scans and published key.** No SALT or Gemini key in any committed file. One `AIza` substring inside a base64 thought-signature blob is not a key. Local paths were rewritten. The retired build's ledger key is published per job.
- Harbor reports `NonZeroAgentExitCodeError` on OpenCode trials because OpenCode exits non-zero after the game has ended. When the ledger is done, the trial is valid.
