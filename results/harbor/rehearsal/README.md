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
