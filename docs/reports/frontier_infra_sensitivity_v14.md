# Canary v1.4 Frontier Infrastructure Exclusion, Timeout, and Quota Sensitivity Audit

Every figure in this report is deterministically computed from committed `meta.json` and replay-verified `episodes.jsonl` files by `scripts/frontier_infra_sensitivity.py` using `canary.analysis.gap` (`load_runs`, `mean_ci`) and `scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), with zero live API calls and zero `.git` runtime dependency.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_infra_sensitivity.py --check
```

## 1. Post-Hoc Seed Lock, Replay Audit, and Headline Summary

- **Post-hoc seed lock and pre-registered `gpt-5.5` family (`docs/reports/gap.md`, synced to `justSilas@9225f2ad`):** The primary `seeds 0-29` set (`n=30` per tier in `data/runs/committed/v1.4/`) was locked in commit `671ed96` (`28 s` after `8fd4dec`), making it a **post-hoc lock against later reruns and cherry-picking, not a pre-registration**. On `hard` (`n=30`), `OpenCode + gemini-4-carbon over MCP` scores **65% [24%, 98%]** of the paired reference solver (`0.322 +/- 0.199` vs `0.499`), with luck-adjusted ratio **72% [52%, 91%]** (`0.360` vs `0.499`); on `medium` (`n=30`), it reaches `111% [99%, 127%]` raw and `101% [85%, 119%]` luck-adjusted. Pre-registered second frontier family `OpenCode + gpt-5.5` (`cf394894`, shipped in `ca0a0dc0`, `data/runs/committed/v1.4/opencode-gpt-5.5/hard`) matches the solver at **101% [79%, 140%]** raw (`0.504 +/- 0.064` vs `0.499`) and **84% [67%, 103%]** luck-adjusted (`0.418` vs `0.499`) with `0` infra exclusions (`30/30` first-attempt valid, `28/28` accusations correct, `2` clean `rc=0` non-accusation stops on `seeds [0, 17]` scoring `0.0` with `final_day=0`; Harbor judge-path rehearsal in `c59ecfd0` / `results/harbor/rehearsal/TABLE.md` also landed at or above oracle).
- **Deterministic replay verification (`scripts/verify_replay.py`):** `472/472` committed `v1.4` episodes (including `30/30` `opencode-gpt-5.5/hard`) and `305/305` FR8 replication `v1.4` episodes (`777/777` combined corpus) pass full `Env` replay with `0` mismatches and `0` duplicate `(agent, tier, seed)` entries. `docs/reports/gap.md` does not yet ship `gemini-3.5-flash` hard (`0-29`); those 30 committed episodes are replay-verified in `data/runs/committed/v1.4/` (`472/472`) and held out of tables below via `gap_ships_flash_hard(root)`.
- **Retrying infra failures is strictly conservative (favors the frontier agent):** Across `71` excluded infra-invalid attempts in committed `v1.4` (`31` `provider_quota`, `19` `cli_error_event`, `12` `empty_model_response`, `7` `provider_unavailable`, `2` `mcp_server_error`, and `0` on `opencode-gpt-5.5/hard`), scoring `empty_model_response` first-attempt failures as `0` lowers OpenCode `gemini-4-carbon` hard from `65% [24%, 98%]` raw (`72% [52%, 91%]` luck-adjusted) to `56% [19%, 87%]` raw (`55% [34%, 77%]` luck-adjusted), and scoring **all** `11` infra-retried seeds as `0` lowers it further to `56% [28%, 84%]` raw (`47% [28%, 67%]` luck-adjusted; medium `111% [99%, 127%]` -> `90% [71%, 109%]` -> `83% [63%, 103%]` raw; `opencode-gpt-5.5` hard is invariant across Regimes 1/2/3 at `101% [79%, 140%]` raw).
- **Timeout truncation (`900s` -> `7200s`) and `ext` quota survivor bias:** Legacy `900s` PR 3 timeouts would truncate `30/30` (`100.0%`) of valid primary `gemini-4-carbon` hard episodes and `26/30` (`86.7%`) of medium episodes while truncating `0/30` (`0.0%`, max `wall_s = 357.1s`) of `gpt-5.5` hard episodes; the `cf394894` `7200s` cap truncates `0` episodes across all OpenCode cohorts (max observed `wall_s = 6591.7s`). In `opencode-gemini-4-carbon-ext/hard`, `31` `infra:provider_quota` exclusions blocked `9` of the `11` launched seeds (`30..40`) before the `03:22` Helsinki stop; the `2` survivors (`seeds 34, 37`) took `1506.2s` and `5.50` days vs `2630.4s` and `13.43` days on primary `0-29`.

## 2. Cohort-Level meta.json Exclusion and Retry Inventory

Committed `v1.4` run directories (`data/runs/committed/v1.4/`):

| directory | agent | tier | planned | valid eps | invalid in jsonl | excluded attempts | affected seeds | category breakdown |
|---|---|---|---:|---:|---:|---:|---:|---|
| `data/runs/committed/v1.4/opencode-gemini-4-carbon/medium` | `opencode:google/gemini-4-carbon` | medium | 30 | 30 | 0 | 15 | 8 | `cli_error_event`=6, `empty_model_response`=6, `mcp_server_error`=2, `provider_unavailable`=1 |
| `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard` | `opencode:google/gemini-4-carbon` | hard | 30 | 30 | 0 | 25 | 11 | `cli_error_event`=13, `empty_model_response`=6, `provider_unavailable`=6 |
| `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` | `opencode:google/gemini-4-carbon` | hard | 30 | 2 | 0 | 31 | 9 | `provider_quota`=31 |
| `data/runs/committed/v1.4/opencode-gpt-5.5/hard` | `opencode:openai/gpt-5.5` | hard | 30 | 30 | 0 | 0 | 0 | none |
| `data/runs/committed/v1.4/inproc-gemini-4-carbon/medium` | `gemini:gemini-4-carbon` | medium | 30 | 30 | 0 | 0 | 0 | none |
| `data/runs/committed/v1.4/inproc-gemini-4-carbon/hard` | `gemini:gemini-4-carbon` | hard | 30 | 30 | 0 | 0 | 0 | none |

FR8 sharded replication directories (`results/frontier_replication/v1.4/`):

| directory | agent | tier | shards | completed / target | excluded attempts | shard status provenance |
|---|---|---|---:|---|---:|---|
| `results/frontier_replication/v1.4/opencode-gemini-4-carbon` | `opencode:google/gemini-4-carbon` | hard | 5 | 5/30 | 0 | `5` seeds `[30, 34, 42, 45, 57]` landed across `5` shards (`25` of `30-59` pending) |
| `results/frontier_replication/v1.4/opencode-gemini-3.5-flash` | `opencode:google/gemini-3.5-flash` | medium | 3 | 30/30 | 0 | `medium-15-29` logged `INCOMPLETE: seed [28] pending rerun`; resolved by standalone `medium-s28` (`30/30` complete) |

## 3. Paired Imputation Sensitivity Across Three Retry Regimes (Primary Seeds 0-29)

Because `scripts/gemini_runner.py` stops re-queuing a seed once a valid episode finishes, every seed listed in `infra_invalid_attempts_excluded` failed on its first attempt. Comparing (1) the primary retry policy, (2) `empty_model_response` seeds imputed as `0` (`docs/reports/gap.md` alternative row), and (3) **all** first-attempt infra-invalid seeds imputed as `0` (`empty_model_response`, `cli_error_event`, `provider_unavailable`, `mcp_server_error`, `provider_quota`, `provider_rate_limit`) across `gemini-4-carbon` and `gpt-5.5`:

| tier | regime | zeroed seeds (count) | n | score +/- 95% CI | accuracy | accused | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---|---|---:|---|---:|---:|---:|---|---|---|---|
| hard | Regime 1 (PRIMARY locked headline): infra-invalid attempts excluded and retried | none (0) | 30 | 0.322 +/- 0.199 | 0.83 | 0.97 | 0.499 | **65% [24%, 98%]** | -0.177 +/- 0.194 | 0.360 | **72% [52%, 91%]** |
| hard | Regime 2 (gap.md alternative): seeds with empty_model_response scored as 0 | `[3, 19, 25, 26, 27]` (5) | 30 | 0.279 +/- 0.180 | 0.70 | 0.80 | 0.499 | 56% [19%, 87%] | -0.220 +/- 0.174 | 0.277 | 55% [34%, 77%] |
| hard | Regime 3 (strictest lower bound): all first-attempt infra-invalid seeds scored as 0 | `[3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29]` (11) | 30 | 0.277 +/- 0.136 | 0.57 | 0.60 | 0.499 | 56% [28%, 84%] | -0.222 +/- 0.163 | 0.237 | 47% [28%, 67%] |
| medium | Regime 1 (PRIMARY locked headline): infra-invalid attempts excluded and retried | none (0) | 30 | 0.713 +/- 0.042 | 1.00 | 1.00 | 0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | 0.652 | 101% [85%, 119%] |
| medium | Regime 2 (gap.md alternative): seeds with empty_model_response scored as 0 | `[7, 12, 13, 17, 22, 29]` (6) | 30 | 0.579 +/- 0.110 | 0.80 | 0.80 | 0.645 | 90% [71%, 109%] | -0.066 +/- 0.124 | 0.558 | 86% [68%, 106%] |
| medium | Regime 3 (strictest lower bound): all first-attempt infra-invalid seeds scored as 0 | `[7, 12, 13, 17, 19, 22, 27, 29]` (8) | 30 | 0.534 +/- 0.121 | 0.73 | 0.73 | 0.645 | 83% [63%, 103%] | -0.111 +/- 0.134 | 0.513 | 80% [60%, 101%] |
| hard | OpenCode gpt-5.5 Regimes 1/2/3 (invariant: 0 infra exclusions, 30/30 first-attempt valid; 2 rc=0 non-accusation stops on [0, 17] score 0.0) | none (0) | 30 | 0.504 +/- 0.064 | 0.93 | 0.93 | 0.499 | **101% [79%, 140%]** | +0.005 +/- 0.141 | 0.418 | **84% [67%, 103%]** |

- **Why `hard` raw mean moves slightly (`0.279` -> `0.277`) while luck-adjusted drops (`0.277` -> `0.237`, `55%` -> `47%`):** On the `6` non-empty-reply retried hard seeds `[14, 15, 18, 23, 24, 29]`, `4` valid retries succeeded while `2` (`seeds [15, 18]`) made `-1.000` wrong accusations, nearly canceling in raw score (`+0.040` net across 6 seeds) whereas posterior-expected value was positive (`+1.192` net). Under both raw and luck-adjusted metrics, retrying never inflates the frontier gap.
- **`OpenCode + gpt-5.5` hard (`0-29`, `ca0a0dc0`) retry invariance and clean `rc=0` stops:** `data/runs/committed/v1.4/opencode-gpt-5.5/hard` logged `0` `infra_invalid_attempts_excluded` (`30/30` first-attempt valid with `meta.attempts=1`), so Regimes 1, 2, and 3 are identical (`0.504 +/- 0.064`, `101% [79%, 140%]` raw, `84% [67%, 103%]` luck-adjusted). On `28/28` accusations `gpt-5.5` was correct; on `seeds [0, 17]` it wrote an accusation in prose without calling `accuse` and exited cleanly (`rc=0`, `score=0.0`, `final_day=0`).
- **FR8 `gemini-3.5-flash` medium `seed 28` rerun sensitivity (`results/frontier_replication/v1.4/opencode-gemini-3.5-flash/`):** As played (`30/30` with `medium-s28`), `gemini-3.5-flash` medium scores `0.434 +/- 0.236` (`67% [29%, 103%]` raw, `75% [45%, 105%]` luck-adjusted); imputing standalone rerun `seed 28` as `0` shifts it to `0.410 +/- 0.236` (`64% [25%, 100%]` raw, `71% [41%, 102%]` luck-adjusted).

## 4. Wall-Clock Timeout Truncation Sweep (900s, 1800s, 2400s, 3600s, 7200s)

Episodes whose recorded `meta.wall_s` exceeds each timeout cap across all OpenCode cohorts:

| cohort | n | mean `wall_s` +/- CI | median / min / max `wall_s` | `>900s` (PR 3) | `>1800s` | `>2400s` | `>3600s` | `>7200s` (`cf394894`) |
|---|---:|---|---|---|---|---|---|---|
| OpenCode gemini-4-carbon hard (primary 0-29) | 30 | 2630.4s +/- 421.9s | 2351.3s / 962.1s / 6591.7s | 30/30 (100%) | 24/30 (80%) | 13/30 (43%) | 5/30 (17%) | 0/30 (0%) |
| OpenCode gemini-4-carbon medium (primary 0-29) | 30 | 1538.2s +/- 323.7s | 1327.6s / 679.8s / 5427.0s | 26/30 (87%) | 7/30 (23%) | 2/30 (7%) | 1/30 (3%) | 0/30 (0%) |
| OpenCode gpt-5.5 hard (0-29) | 30 | 230.6s +/- 20.4s | 240.0s / 118.5s / 357.1s | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) |
| OpenCode gemini-4-carbon-ext hard (survivors 34, 37) | 2 | 1506.2s +/- 224.2s | 1506.2s / 1391.8s / 1620.6s | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) |
| FR8 OpenCode gemini-4-carbon hard replication | 5 | 1641.5s +/- 638.0s | 1499.2s / 921.8s / 2858.9s | 5/5 (100%) | 1/5 (20%) | 1/5 (20%) | 0/5 (0%) | 0/5 (0%) |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | 30 | 151.6s +/- 22.2s | 132.2s / 65.6s / 346.3s | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) | 0/30 (0%) |

Counterfactual `0-29` scores for `OpenCode + gemini-4-carbon` and `OpenCode + gpt-5.5` if episodes exceeding threshold `T` are truncated to `0`:

| agent | tier | timeout `T` | truncated seeds | counterfactual score +/- CI | counterfactual / solver [95% CI] | counterfactual luck-adj. / solver [95% CI] |
|---|---|---:|---:|---|---|---|
| `gemini-4-carbon` | hard | 900s | 30/30 | 0.000 +/- 0.000 | 0% [0%, 0%] | 0% [0%, 0%] |
| `gemini-4-carbon` | hard | 1800s | 24/30 | 0.075 +/- 0.115 | 15% [-8%, 38%] | 20% [7%, 36%] |
| `gemini-4-carbon` | hard | 2400s | 13/30 | 0.242 +/- 0.164 | 48% [16%, 76%] | 51% [33%, 68%] |
| `gemini-4-carbon` | hard | 3600s | 5/30 | 0.260 +/- 0.199 | 52% [10%, 86%] | 64% [45%, 82%] |
| `gemini-4-carbon` | hard | 7200s | 0/30 | 0.322 +/- 0.199 | 65% [24%, 98%] | 72% [52%, 91%] |
| `gemini-4-carbon` | medium | 900s | 26/30 | 0.113 +/- 0.105 | 17% [4%, 35%] | 14% [1%, 30%] |
| `gemini-4-carbon` | medium | 1800s | 7/30 | 0.576 +/- 0.119 | 89% [70%, 108%] | 86% [67%, 107%] |
| `gemini-4-carbon` | medium | 2400s | 2/30 | 0.681 +/- 0.075 | 106% [92%, 122%] | 102% [87%, 120%] |
| `gemini-4-carbon` | medium | 3600s | 1/30 | 0.697 +/- 0.061 | 108% [98%, 123%] | 102% [86%, 120%] |
| `gemini-4-carbon` | medium | 7200s | 0/30 | 0.713 +/- 0.042 | 111% [99%, 127%] | 101% [85%, 119%] |
| `gpt-5.5` | hard | 900s | 0/30 | 0.504 +/- 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |
| `gpt-5.5` | hard | 1800s | 0/30 | 0.504 +/- 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |
| `gpt-5.5` | hard | 2400s | 0/30 | 0.504 +/- 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |
| `gpt-5.5` | hard | 3600s | 0/30 | 0.504 +/- 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |
| `gpt-5.5` | hard | 7200s | 0/30 | 0.504 +/- 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |

## 5. Quota Survivor-Duration Audit on opencode-gemini-4-carbon-ext (Seeds 30-59)

Before the `03:22` Helsinki stop to preserve the shared `2M token/min` carbon quota for the judge rehearsal, `opencode-gemini-4-carbon-ext/hard` launched `11` contiguous seeds (`30..40`, leaving `19` seeds `41..59` unstarted). Only `2` seeds (`[34, 37]`) completed, while `9` seeds (`[30, 31, 32, 33, 35, 36, 38, 39, 40]`) accumulated `31` `infra:provider_quota` exclusions:

| cohort / seed subset | n | mean score +/- CI | mean `final_day` | mean `steps` | mean `wall_s` +/- CI | `>1800s` share |
|---|---:|---|---:|---:|---|---:|
| Primary `opencode-gemini-4-carbon` hard (`0-29`) | 30 | 0.322 +/- 0.199 | 13.43 | 128.03 | 2630.4s +/- 421.9s | 80% |
| Extension `opencode-gemini-4-carbon-ext` survivors (`34, 37`) | 2 | 0.745 +/- 0.088 | 5.50 | 57.50 | 1506.2s +/- 224.2s | 0% |
| FR8 replication `opencode-gemini-4-carbon` hard (`[30, 34, 42, 45, 57]`) | 5 | 0.656 +/- 0.110 | 11.00 | 100.20 | 1641.5s +/- 638.0s | 20% |
| Reference `solver` on `ext` completed seeds (`34, 37`) | 2 | 0.735 +/- 0.069 | 5.50 | 49.00 | n/a (CPU) | n/a |
| Reference `solver` on `ext` quota-blocked seeds (`9` seeds in `30..40`) | 9 | 0.194 +/- 0.465 | 10.56 | 84.00 | n/a (CPU) | n/a |
| Reference `solver` on full extension (`30-59`) | 30 | 0.498 +/- 0.156 | 8.83 | 71.67 | n/a (CPU) | n/a |

Survivor-bias confirmation: `ext` survivors (`34, 37`) ran `0.57x` the wall time, `0.41x` the simulation days, and `0.45x` the tool calls of primary `0-29`. Even on the deterministic CPU `solver` (zero quota exposure), `seeds [34, 37]` resolved in `5.50` days (score `0.735`), whereas the `9` quota-blocked seeds in `30..40` required `10.56` days (score `0.194`). Under heavy TPM contention, short early-leak worlds selectively survive while multi-week episodes hit `provider_quota`, confirming why primary `0-29` (`n=30`) remains the sole headline.
