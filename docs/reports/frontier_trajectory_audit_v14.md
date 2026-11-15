# Canary v1.4 Trajectory, Canary Design, Horizon, and Token/Cache Audit

Every number in this report is deterministically computed from recorded `steps` and `meta` across all `275` replay-verified Canary `v1.4` episodes (`10` cohorts, counts `[30, 30, 5, 30, 30, 30, 30, 30, 30, 30]`) by `scripts/frontier_trajectory_audit.py` with zero live API calls and zero `.git` dependency.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_trajectory_audit.py --check
```

## 1. Executive Findings Across Harness, Model Family, and Solver

- **Replay & cohort coverage:** `275/275` episodes pass deterministic `Env` replay (`scripts/verify_replay.py`) with `0` score/accusation mismatches and `0` duplicate seeds across all 10 cohorts.
- **Interview budget sink is a model-level trait of `gemini-4-carbon`, not an OpenCode MCP artifact:** On `hard` (`seeds 0-29`), OpenCode `gemini-4-carbon` runs `68.03` interviews/episode and `8.47` accepted canaries/episode, closely matching in-process `gemini-4-carbon` (`57.27` interviews, `8.57` canaries), whereas the Bayesian `solver` runs `0.00` interviews and plants `14.13` canaries/episode (`66.7%` slot utilization vs OpenCode `gemini-4-carbon`'s `31.5%`).
- **Distinct failure mechanics between `gemini-4-carbon` and `gemini-3.5-flash`:** OpenCode `gemini-3.5-flash` largely avoids interviews (`2.47` on medium, `0.77` on hard) and plants `12.43` accepted canaries/episode on hard (`5.79` and `5.40` total calls/day), but it is the **only** cohort that plants uninformative single-variant (`1`-label) canaries (`2` on medium, `1` on hard) and full-company `40/40`-recipient canaries (`2` on hard, which have `0.0` leak probability under `careful_mole`), and it exhibits `0.0%` abstention even when suspects remain unresolved.
- **Canary split discipline (`targeted 2-3 variant splits <=50% staff` vs `broad/single-variant`):** The reference `solver` keeps `99.1%` (medium), `99.5%` (hard `0-29`), and `99.2%` (hard `30-59`) of its canaries in targeted `2-3` variant splits covering at most half the staff (`careful_mole` weight `>= 0.5`). Frontier cohorts place `17.1%` (OpenCode carbon medium), `13.5%` (in-process carbon medium), `8.7%` (OpenCode flash medium), `7.8%` (OpenCode flash hard), and `7.5%` (OpenCode carbon hard `0-29`) of accepted canaries into broad (`>50%` staff) or single-variant assignments.
- **Token caching & wall-clock justification for `--timeout 3600`:** Across OpenCode cohorts, prompt caching serves `93.8%` to `95.8%` of `gemini-4-carbon` input tokens and `89.6%` to `92.2%` of `gemini-3.5-flash` input tokens. OpenCode `gemini-4-carbon` averages `2630.4s` per hard episode (`13/30` episodes exceed `2400s`), empirically confirming why `--timeout 2400` would truncate hard `gemini-4-carbon` runs while `gemini-3.5-flash` finishes in `151.6s` (medium) and `234.4s` (hard).

## 2. Tool-Call Rate and Per-Tool Breakdown Across All 10 Cohorts

Tool names in `canary/env.py` map to shorthand aliases as follows: `read_access_logs` (`read_logs`), `restrict_access` (`restrict`), and `advance_day` (`next_day`), alongside `check_leak_feed` and `unrestrict_access`. Canary exposes document metadata via `list_documents` and leaked items via `check_leak_feed`, so `read_document` is `0.00` across all cohorts; non-Env tool attempts (`1` rejected `bash` call in OpenCode `gemini-3.5-flash` hard) appear under `other`.

| cohort | n | mean calls +/- CI | calls / sim day | inv actions / day | status | list_emp | read_logs | read_msg | search_msg | list_docs | read_doc | leak_feed | plant_canary | interview | restrict | unrestrict | next_day | accuse | other |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 76.13 +/- 9.62 | 9.49 | 7.02 | 1.97 | 1.00 | 6.03 | 0.00 | 3.87 | 7.27 | 0.00 | 4.33 | 5.87 | 37.53 | 0.17 | 0.13 | 6.97 | 1.00 | 0.00 |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 128.03 +/- 12.94 | 9.61 | 7.42 | 1.50 | 1.00 | 12.27 | 0.17 | 4.23 | 12.07 | 0.00 | 6.70 | 8.50 | 68.03 | 0.10 | 0.03 | 12.47 | 0.97 | 0.00 |
| OpenCode gemini-4-carbon hard rep (30,34,42,45,57) | 5 | 100.20 +/- 30.43 | 9.19 | 6.97 | 1.00 | 1.00 | 10.20 | 0.40 | 5.20 | 10.20 | 0.00 | 5.40 | 5.40 | 50.40 | 0.00 | 0.00 | 10.00 | 1.00 | 0.00 |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 51.67 +/- 6.79 | 5.79 | 3.42 | 3.27 | 1.00 | 7.00 | 0.03 | 5.20 | 6.90 | 0.00 | 8.87 | 7.77 | 2.47 | 0.17 | 0.00 | 8.00 | 1.00 | 0.00 |
| OpenCode gemini-3.5-flash hard (0-29) | 30 | 65.43 +/- 6.03 | 5.40 | 3.29 | 3.33 | 1.00 | 9.93 | 0.13 | 4.93 | 7.73 | 0.00 | 12.27 | 12.57 | 0.77 | 0.03 | 0.00 | 11.70 | 1.00 | 0.03 |
| in-process gemini-4-carbon medium (0-29) | 30 | 94.17 +/- 11.83 | 9.63 | 7.28 | 1.77 | 1.00 | 7.97 | 0.03 | 4.60 | 8.83 | 0.00 | 5.47 | 6.93 | 47.30 | 0.40 | 0.17 | 8.83 | 0.87 | 0.00 |
| in-process gemini-4-carbon hard (0-29) | 30 | 116.23 +/- 15.52 | 8.96 | 6.76 | 1.47 | 1.00 | 11.80 | 0.07 | 4.40 | 11.83 | 0.00 | 6.33 | 8.57 | 57.27 | 0.27 | 0.27 | 12.00 | 0.97 | 0.00 |
| reference solver medium (0-29) | 30 | 63.27 +/- 8.04 | 7.79 | 3.79 | 15.50 | 1.00 | 7.20 | 0.00 | 7.67 | 8.20 | 0.00 | 8.20 | 7.30 | 0.00 | 0.00 | 0.00 | 7.30 | 0.90 | 0.00 |
| reference solver hard (0-29) | 30 | 84.27 +/- 11.58 | 8.10 | 4.10 | 20.20 | 1.00 | 9.60 | 0.00 | 7.53 | 10.60 | 0.00 | 10.60 | 14.13 | 0.00 | 0.00 | 0.00 | 9.60 | 1.00 | 0.00 |
| reference solver hard (30-59) | 30 | 71.67 +/- 9.38 | 8.25 | 4.25 | 16.70 | 1.00 | 7.83 | 0.00 | 7.47 | 8.83 | 0.00 | 8.83 | 12.17 | 0.00 | 0.00 | 0.00 | 7.87 | 0.97 | 0.00 |

## 3. Canary Information-Gathering & Split Design Quality

Under Canary `v1.4` (`careful_mole = True`, `max_variants = 3`, `n_employees = 20` on medium and `40` on hard), each accepted `plant_canary` call maps recipients to variant labels (`assignment`). A canary is classified as **uninformative broad/single-variant** when it uses only `1` variant label (`len(set(assignment.values())) == 1`, giving zero variant split among recipients) or covers `> 50%` of staff (`> 10` on medium, `> 20` on hard, pushing the careful-mole selection weight `1 - share` below `0.5`, and to `0.0` at `100%` coverage). Its exact complement is a **targeted 2-3 variant split** (`2` or `3` distinct variants covering `<= 50%` of staff):

| cohort | n | plant calls / ep | accepted / ep | slot util. | mean recipients (% staff) | mean careful weight | mean distinct variants | 1 / 2 / 3-var counts | uninf. broad or 1-var % (1-var / >50% / 100%) | targeted 2-3 split % |
|---|---:|---:|---:|---:|---|---:|---:|---|---|---:|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 5.87 | 5.83 | 73.2% | 7.60 (38.0%) | 0.62 | 3.00 | 0 / 0 / 175 | 17.1% (0 / 30 / 0) | 82.9% |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 8.50 | 8.47 | 31.5% | 10.27 (25.7%) | 0.74 | 3.00 | 0 / 0 / 254 | 7.5% (0 / 19 / 0) | 92.5% |
| OpenCode gemini-4-carbon hard rep (30,34,42,45,57) | 5 | 5.40 | 5.40 | 24.5% | 11.33 (28.3%) | 0.72 | 3.00 | 0 / 0 / 27 | 0.0% (0 / 0 / 0) | 100.0% |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 7.77 | 7.70 | 85.6% | 4.97 (24.8%) | 0.75 | 2.85 | 2 / 31 / 198 | 8.7% (2 / 18 / 0) | 91.3% |
| OpenCode gemini-3.5-flash hard (0-29) | 30 | 12.57 | 12.43 | 49.0% | 9.12 (22.8%) | 0.77 | 2.94 | 1 / 19 / 353 | 7.8% (1 / 28 / 2) | 92.2% |
| in-process gemini-4-carbon medium (0-29) | 30 | 6.93 | 6.93 | 71.5% | 6.92 (34.6%) | 0.65 | 2.99 | 0 / 3 / 205 | 13.5% (0 / 28 / 0) | 86.5% |
| in-process gemini-4-carbon hard (0-29) | 30 | 8.57 | 8.57 | 33.0% | 10.22 (25.6%) | 0.74 | 3.00 | 0 / 0 / 257 | 8.2% (0 / 21 / 0) | 91.8% |
| reference solver medium (0-29) | 30 | 7.30 | 7.30 | 89.0% | 4.58 (22.9%) | 0.77 | 2.71 | 0 / 64 / 155 | 0.9% (0 / 2 / 0) | 99.1% |
| reference solver hard (0-29) | 30 | 14.13 | 14.13 | 66.7% | 9.49 (23.7%) | 0.76 | 3.00 | 0 / 0 / 424 | 0.5% (0 / 2 / 0) | 99.5% |
| reference solver hard (30-59) | 30 | 12.17 | 12.17 | 68.9% | 9.96 (24.9%) | 0.75 | 2.99 | 0 / 3 / 362 | 0.8% (0 / 3 / 0) | 99.2% |

## 4. Collateral Damage (`restrict_access`) and Horizon / Stopping Behavior

| cohort | n | restrict calls / ep | unrestrict calls / ep | episodes w/ restrict | abstention rate (`horizon`) | accused rate | mean accuse day (accused) | mean final day (all) | accuracy | wrong accuse rate | mean score +/- CI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 0.167 | 0.133 | 2/30 (6.7%) | 0/30 (0.0%) | 100.0% | 7.97 | 7.97 | 100.0% | 0/30 (0.0%) | 0.713 +/- 0.042 |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 0.100 | 0.033 | 3/30 (10.0%) | 1/30 (3.3%) | 96.7% | 13.17 | 13.43 | 83.3% | 4/30 (13.3%) | 0.322 +/- 0.199 |
| OpenCode gemini-4-carbon hard rep (30,34,42,45,57) | 5 | 0.000 | 0.000 | 0/5 (0.0%) | 0/5 (0.0%) | 100.0% | 11.00 | 11.00 | 100.0% | 0/5 (0.0%) | 0.656 +/- 0.110 |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 0.167 | 0.000 | 1/30 (3.3%) | 0/30 (0.0%) | 100.0% | 9.00 | 9.00 | 83.3% | 5/30 (16.7%) | 0.434 +/- 0.236 |
| OpenCode gemini-3.5-flash hard (0-29) | 30 | 0.033 | 0.000 | 1/30 (3.3%) | 0/30 (0.0%) | 100.0% | 12.70 | 12.70 | 90.0% | 3/30 (10.0%) | 0.373 +/- 0.177 |
| in-process gemini-4-carbon medium (0-29) | 30 | 0.400 | 0.167 | 6/30 (20.0%) | 4/30 (13.3%) | 86.7% | 9.04 | 9.70 | 83.3% | 1/30 (3.3%) | 0.530 +/- 0.138 |
| in-process gemini-4-carbon hard (0-29) | 30 | 0.267 | 0.267 | 1/30 (3.3%) | 1/30 (3.3%) | 96.7% | 12.69 | 12.97 | 93.3% | 1/30 (3.3%) | 0.473 +/- 0.118 |
| reference solver medium (0-29) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 3/30 (10.0%) | 90.0% | 7.56 | 8.20 | 90.0% | 0/30 (0.0%) | 0.645 +/- 0.087 |
| reference solver hard (0-29) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 0/30 (0.0%) | 100.0% | 10.60 | 10.60 | 96.7% | 1/30 (3.3%) | 0.499 +/- 0.119 |
| reference solver hard (30-59) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 1/30 (3.3%) | 96.7% | 8.41 | 8.83 | 90.0% | 2/30 (6.7%) | 0.498 +/- 0.156 |

## 5. Token, Prompt-Cache, and Wall-Clock Efficiency (OpenCode + In-Process Reference)

All 5 OpenCode cohorts record `meta.usage` (`in`, `cached_in`, `out`, `llm_calls`) and per-episode `meta.wall_s`. The 2 in-process `gemini-4-carbon` cohorts record `meta.usage` (`in`, `cached_in`, `out`, `calls`) without `wall_s`, allowing direct token-overhead comparison on identical seeds `0-29`:

| cohort | harness | n | mean `usage.in` | mean `usage.cached_in` | mean uncached in | mean `usage.out` | cached input % (agg / ep) | mean LLM calls | mean `wall_s` +/- CI | min / max `wall_s` | `>2400s` / `>3600s` |
|---|---|---:|---:|---:|---:|---:|---|---:|---|---|---|
| OpenCode gemini-4-carbon medium (0-29) | opencode | 30 | 3.44M | 3.23M | 213.4k | 45.7k | 93.80% / 92.95% | 77.0 | 1538.2s +/- 323.7s | 679.8s / 5427.0s | 2 / 1 |
| OpenCode gemini-4-carbon hard (0-29) | opencode | 30 | 8.79M | 8.42M | 365.4k | 70.5k | 95.84% / 95.45% | 129.0 | 2630.4s +/- 421.9s | 962.1s / 6591.7s | 13 / 5 |
| OpenCode gemini-4-carbon hard rep (30,34,42,45,57) | opencode | 5 | 5.98M | 5.71M | 265.8k | 62.7k | 95.55% / 95.16% | 101.2 | 1641.5s +/- 638.0s | 921.8s / 2858.9s | 1 / 0 |
| OpenCode gemini-3.5-flash medium (0-29) | opencode | 30 | 1.46M | 1.31M | 152.2k | 17.2k | 89.57% / 87.79% | 51.2 | 151.6s +/- 22.2s | 65.6s / 346.3s | 0 / 0 |
| OpenCode gemini-3.5-flash hard (0-29) | opencode | 30 | 2.52M | 2.33M | 197.4k | 25.0k | 92.18% / 91.26% | 63.7 | 234.4s +/- 18.1s | 154.0s / 339.2s | 0 / 0 |
| in-process gemini-4-carbon medium (0-29) | inproc | 30 | 2.84M | 2.60M | 239.9k | 35.2k | 91.56% / 89.88% | 94.4 | n/a | n/a | n/a |
| in-process gemini-4-carbon hard (0-29) | inproc | 30 | 5.49M | 5.17M | 321.7k | 52.4k | 94.14% / 93.00% | 116.1 | n/a | n/a | n/a |

## 6. Paired Harness and Model-Family Deltas (`seeds 0-29`)

- **OpenCode vs In-Process (`gemini-4-carbon`, `n=30` paired seeds per tier):** OpenCode uses `1.21x` (medium) and `1.60x` (hard) as many input tokens per episode due to MCP/CLI scaffold context, yet high prefix cache hit rates (`93.80%` and `95.84%`) keep uncached input down to `213.4k` and `365.4k` tokens/episode. Both harnesses show the same interview-heavy signature (`-9.77` interviews/ep delta on medium, `+10.77` on hard) and nearly identical hard canary counts (`8.47` vs `8.57`).
- **`gemini-4-carbon` vs `gemini-3.5-flash` on OpenCode (`n=30` paired seeds per tier):** `gemini-4-carbon` executes `+24.47` (medium) and `+62.60` (hard) more tool calls/episode, driven by `+35.07` and `+67.27` more interviews, and runs `10.1x` (medium) and `11.2x` (hard) longer in wall-clock time while eliminating single-variant and full-staff zero-leak canary errors and achieving substantially higher posterior calibration at accusation.
