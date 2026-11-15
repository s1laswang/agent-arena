# Integrity Audit: OpenCode GPT-5.5 Run and Harbor Rehearsal (W1B)

## Scope and Command

Deterministic, zero-API audit of the committed `opencode:openai/gpt-5.5` `v1.4` `hard` run (`ca0a0dc0`, locked against `cf394894`) and the 3-run Harbor `0.26.0` judge rehearsal (`c59ecfd0`, finalized in `aa1c679e` / tag `afterquery-submit-2` and CEO log correction `5f9b3297` from `s1-rehearsal-final` commit `d0ead011`), built from frozen `afterquery-final` (`1bc3e281`) and extending `afterquery-submit` (`9225f2ad`).

Reproduction commands (0 API calls):

```bash
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_gpt55_and_rehearsal_audit.py --check-report docs/reports/integrity_gpt55_and_rehearsal_audit.md
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -q tests/test_integrity_gpt55_and_rehearsal_audit.py
```

## 1. OpenCode `openai/gpt-5.5` (`v1.4` `hard`, `n=30`, `ca0a0dc0`)

| Check | Measured Value | Status |
|---|---|---|
| Episodes / seeds | `30` episodes, seeds `0..29`, `30` valid, `0` invalid, `0` infra-excluded | PASS |
| Step-by-step `Env("hard", seed)` replay | `2,075` tool calls replayed, `0` step payload mismatches, `0` score/verdict mismatches | PASS |
| Transcript cross-check (`transcripts/0..29.txt`) | `2,075` `tool_use` events match `episodes.jsonl` 1-to-1; `0` CLI error events; `0` secret/cheat regex hits | PASS |
| Accusation vs clean stop accounting | `28/30` accused (`28` correct, `0` wrong, days `6..14`, min solver `P(accused)` `0.664`, mean `0.939893`); `2/30` stopped without accusing (`seeds [0, 17]` at `env.day` `8` and `9`, both `score = 0.0`) | PASS |
| Post-hoc lock timestamp ordering (`cf394894`) | `cf394894` commit `1794712266` -> first transcript event `1794712287.153` (`+21.153s` after `cf394894`) -> last event `1794713326.939` (`1039.786s` span, `12142.061s` before `ca0a0dc0` `1794725469`); max concurrency `8`, initial launch order `[0, 1, 2, 3, 4, 5, 6, 7]` | PASS |
| Token and cost accounting (`meta.json`) | Exact sum match: `in = 40,822,059`, `cached_in = 38,594,816`, `out = 282,479`, `llm_calls = 2,075`, `cost_usd_est = $38.908` (`<= $200` cap), `max_wall_s = 357.1s` (`<= 7200s` cap) | PASS |
| Paired solver comparison (`paired_table_gemini.json`) | GPT-5.5 `+0.504 +/- 0.064` (`0.503667`) vs solver `+0.499 +/- 0.119` (`0.499000`); raw ratio `101% [79%, 140%]` (`diff +0.005 +/- 0.141`); luck-adjusted ratio `84% [67%, 103%]` (`0.417754` vs `0.499297`), vs OpenCode `gemini-4-carbon` `65% [24%, 98%]` raw and `72% [52%, 91%]` luck-adjusted | PASS |
| Behavioural table (`results/behaviour_compare_v1.4.md`) | Byte-identical regeneration: `17.2` canaries (`17.1667`), `4.2` interviews (`6.0%` of `69.2` calls), accuse day `10.2` (`10.25`) vs solver `14.1` canaries and Gemini `8.5` canaries / `68.0` interviews | PASS |

Note on `cf394894`: `cf394894` is a binding timestamped config lock (`configs/gpt55_hard30.json` committed `21.153s` before the first GPT-5.5 API event) for the `gpt-5.5` cross-family run, while the core rules/seeds (`v1.4`, `0..29`) were already fixed in `afterquery-final` (`1bc3e281`, a post-hoc lock relative to the earlier primary Gemini run).

## 2. Harbor `0.26.0` Judge Rehearsal (`c59ecfd0` -> `aa1c679e` / `5f9b3297`)

| Check | Measured Value | Status |
|---|---|---|
| Build & freeze provenance (`BUILD.txt`, git tags) | Built at `afterquery-final` (`1bc3e281`, `+66.0s` after tag commit), Harbor `0.26.0`; `opencode-3` started `+7498.0s` after build and before `c59ecfd0`; zero diff across frozen core (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/mcp_server.py`, `canary/world.py`, `canary/mole/`, `canary/text/`, `harbor/`) from `1bc3e281` to `HEAD` (`afterquery-submit` `9225f2ad`, `afterquery-submit-2` `aa1c679e`, `5f9b3297`) | PASS |
| Negative controls (`do_nothing`, `stop_early`) | `10/10` tasks each (`hard-900000..hard-900009`), `0` accusations, exact `+0.000` reward on every cell and summary row | PASS |
| Positive control (`oracle`) | `10/10` tasks, `9/10` correct accusations, mean `+0.506` (within expected `[0.39, 0.68]` solver band; `+0.478` on the `9` valid `opencode-3` seeds) | PASS |
| OpenCode `gemini-4-carbon` 3-run outcomes (`d0ead011`) | Run 1 (`n=10`, `0` infra): `+0.472`, `93% [20%, 371%]`; Run 2 (`n=10`, `0` infra): `+0.585`, `116% [78%, 363%]`; Run 3 finalized (`n=9` valid, `1` infra rate-limit on `hard-900002`, `0` unstarted): `+0.626` (`0.625556`), `131% [86%, 590%]` (`+0.563` infra-as-0); `28/29` (`97%`) valid Gemini accusations correct; mean of run means `+0.561`, SD `0.080`, range `0.154` | PASS |
| `scripts/rehearsal_table.py` deterministic regeneration | 100% exact match on both the `08:52` snapshot table body in `TABLE.md` (`7` valid on `opencode-3`, `+0.656`) and the finalized `s1-rehearsal-final` (`d0ead011`) 9-valid table (`+0.626`, `131% [86%, 590%]`) | PASS |
| Cross-doc alignment (`README.md`, `gap.md`, `SUBMISSION.md`, `CEO.md`) | All four docs match `+0.472` / `+0.585` / `+0.626`, `93%` / `116%` / `131%`, `10 / 10 / 9`, `28/29` correct, `afterquery-submit-2` (`aa1c679e`), and `d0ead011` | PASS |

## 3. Positive Tamper Controls (`6/6` Caught)

1. `tampered_gpt55_step_caught`: mutating one recorded `list_employees` `V` value in `episodes.jsonl` is caught by `Env` step replay (`step_mismatches = 1`).
2. `forged_gpt55_stopped_score_caught`: forging `score = 0.71` on stopped seed `0` is caught by both `Env.score()` replay and clean-stop accounting.
3. `backdated_gpt55_before_cf394894_caught`: backdating transcript `0.txt` `60s` prior to `cf394894` is caught by lock-timestamp verification (`seconds_after_cf394894 < 0`).
4. `tampered_rehearsal_negative_control_caught`: perturbing `stop_early` on `hard-900000` from `+0.00` to `+0.01` fails the negative-control zero gate.
5. `tampered_rehearsal_sha_caught`: altering `BUILD.txt` `sha` away from `1bc3e281` fails Harbor build-freeze provenance.
6. `tampered_rehearsal_final_run3_correction_caught`: altering the finalized Run 3 correction line (`+0.626 = 131% [86%, 590%]`) fails rehearsal header verification.

## 4. Report-Only Issues Identified (`0` Score/Replay Defects)

- `ISSUE-W1B-1` (low, `opencode_stopped_episode_schema_and_final_day_zero`): Clean non-accusing OpenCode exits on `gpt-5.5` seeds `[0, 17]` (`rc=0`, `step_finish` `reason="stop"` at `env.day` `8` and `9`) are stored with `end_reason="error"` and `final_day=0` alongside `meta.note="agent stopped without ending the episode (no accusation)"`. `audit_submission.py`, `anticheat.replay_committed`, and `tamper_guard.replay_committed` (`cc75aacd`) all verify `30/30` episodes cleanly, while `final_day=0` drops the stopping day unless reconstructed via `Env` replay.
- `ISSUE-W1B-2` (info, `gpt55_verbal_accusation_without_tool_call`): On both stopped `gpt-5.5` episodes (`seeds 0` and `17`), assistant prose named the true mole employee ID after canary narrowing without invoking `canary_accuse`; both episodes scored `0.0` (`accused=None`), confirming server-side ledger grading ignores assistant text.
- `ISSUE-W1B-3` (low, `rehearsal_raw_trials_on_side_branch_and_snapshot_table_body`): `results/harbor/rehearsal/` on `justSilas` (`aa1c679e` / `5f9b3297`) omits the `78 MB` raw trial folders (kept on branch `s1-rehearsal-final` at `d0ead011`) and preserves the `08:52` snapshot table body (`7` valid on `opencode-3`) beneath the `09:30` Correction blockquote (`9` valid, `+0.626 = 131% [86%, 590%]`). `scripts/rehearsal_table.py` deterministically reproduces 100% of both tables.
- `ISSUE-W1B-4` (low, `rehearsal_launcher_grep_timeout_header`): `scripts/rehearsal_run.sh` greps the first `^timeout_sec = ` in `harbor/template/task.toml`, logging `[verifier] timeout_sec = 120.0` on `BUILD.txt` line 5 before `[agent] timeout_sec = 10800.0`; disclosed and corrected on `BUILD.txt` line 8.
- `ISSUE-W1B-5` (low, `submission_doc_body_supersede_residuals`): `docs/SUBMISSION.md` places an explicit top supersede block (`Final results, Sun 15 Nov 09:00`, updated in `aa1c679e` to `93%, 116% and 131%`) above three historical body lines (`no tag exists yet`, `Only Gemini-family models were run on rules v1.4`, and `1,021 of 1,031` / `51,814` steps vs `1,051 of 1,061` / `53,889`).
