# Canary v1.4 Trajectory, Canary Design, Horizon, and Token/Cache Audit

Every number in this report is deterministically computed from recorded `steps` and `meta` by `scripts/frontier_trajectory_audit.py` across `247` active cohort episodes (`10` cohorts, counts `[30, 30, 2, 5, 30, 30, 30, 30, 30, 30]`) after full step-and-ledger `Env` replay verification of all `442/442` committed `v1.4` episodes and `305/305` FR8 replication episodes (`0` live API calls, `0` `.git` runtime dependency).

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_trajectory_audit.py --check
```

## 1. Provenance Honesty (Panel Fixes A/C/D), Replay Verification, and Executive Findings

- **Provenance & registration honesty (Panel Fixes A/C/D):** Primary `seeds 0-29` (`data/runs/committed/v1.4/`, committed in `8fd4dec`) are a **post-hoc lock** (`671ed96`, committed `28 s` after `8fd4dec`) preventing later reruns or cherry-picking, not a pre-registration (`20+10` solver reference directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` (`f9fb7a4a`, `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard`, `n=2`, completed `seeds [34, 37]` before stopping to preserve the shared 2M TPM carbon quota for the Harbor rehearsal) and the second frontier family `gpt-5.5` (`cf394894`, OpenCode `1.19.5`, `7200 s` per-episode cap, `$200` spend cap, currently `0` committed `v1.4` episodes) were **pre-registered** before any episode ran.
- **Step-level & ledger replay verification (`1bc3e281` `norm_result` compatibility):** `442/442` committed `v1.4` episodes and `305/305` FR8 replication episodes (`747/747` total) pass deterministic `Env` replay with `0` score/accusation mismatches, `0` step mismatches, and `0` duplicate `(agent, tier, seed)` keys. Step-result comparison unwraps OpenCode's stringified MCP error JSON via `norm_result` first (`80` committed and `24` replication error steps) before normalizing pre-`1bc3e281` `data={}` against live `Env.call` `data={'detail': ...}` (`321` committed and `156` replication steps), so both pre- and post-`1bc3e281` episodes verify cleanly.
- **G1 committed extension (`seeds [34, 37]`, `n=2`) alongside FR8 hard replication (`seeds 30, 34, 42, 45, 57`, `n=5`) and `seed 34` consistency:** G1 (`opencode_gemini_4_carbon_hard_ext`) averages `0.745 +/- 0.088` (`57.50` tool calls, `29.00` interviews, `5.50` accepted canaries, `100.0%` targeted `2-3` splits) alongside FR8 hard replication (`0.656 +/- 0.110`, `100.20` calls, `50.40` interviews, `5.40` canaries, `100.0%` targeted `2-3` splits). On their shared hard `seed 34`, both independent runs correctly accuse `e29` with `0` restrictions and `100%` targeted `3`-variant splits (`G1 +0.790` on day `5` with `51` calls, `6` canaries, `26` interviews vs `FR8 +0.820` on day `8` with `83` calls, `3` canaries, `49` interviews; reference `solver +0.700` on day `6` with `10` canaries and `0` interviews).
- **Interview budget sink is a model-level trait of `gemini-4-carbon`, not an OpenCode MCP artifact:** On `hard` (`seeds 0-29`), OpenCode `gemini-4-carbon` runs `68.03` interviews/episode and `8.47` accepted canaries/episode, closely matching in-process `gemini-4-carbon` (`57.27` interviews, `8.57` canaries), whereas the Bayesian `solver` runs `0.00` interviews and plants `14.13` canaries/episode (`66.7%` slot utilization vs OpenCode `gemini-4-carbon`'s `31.5%`).
- **Distinct failure mechanics on `gemini-3.5-flash` medium (`n=30`) and `docs/reports/gap.md` hard-row gate:** On FR8 cross-model replication `medium` (`seeds 0-29`, `n=30`), OpenCode `gemini-3.5-flash` largely avoids interviews (`2.47`/episode vs OpenCode `gemini-4-carbon`'s `37.53`) and plants `7.70` accepted canaries/episode (`5.79` total calls/day), but it is the **only** active cohort that plants uninformative single-variant (`1`-label) canaries (`2` instances) and shows `0.0%` abstention (`5/30` wrong accusations). Per `gap_ships_flash_hard(root)`, `opencode:google/gemini-3.5-flash` hard (`seeds 0-29`) is replay-verified inside `data/runs/committed/v1.4` (`442/442`) and omitted from cohort tables and paired hard comparisons while `docs/reports/gap.md` has not shipped it.
- **Canary split discipline (`targeted 2-3 variant splits <=50% staff` vs `broad/single-variant`):** The reference `solver` keeps `99.1%` (medium), `99.5%` (hard `0-29`), and `99.2%` (hard `30-59`) of its canaries in targeted `2-3` variant splits covering at most half the staff (`careful_mole` weight `>= 0.5`). Frontier cohorts place `17.1%` (OpenCode carbon medium), `13.5%` (in-process carbon medium), `8.7%` (OpenCode flash medium), and `7.5%` (OpenCode carbon hard `0-29`) of accepted canaries into broad (`>50%` staff) or single-variant assignments.
- **Token caching & wall-clock justification for `--timeout 3600` (and `7200 s` `gpt-5.5` cap):** Across OpenCode cohorts, prompt caching serves `93.3%` to `95.8%` of `gemini-4-carbon` input tokens and `89.6%` of `gemini-3.5-flash` medium input tokens (`151.6s` mean wall time). OpenCode `gemini-4-carbon` averages `2630.4s` per primary hard episode (`13/30` exceed `2400s`), empirically confirming why `--timeout 2400` would truncate hard frontier runs.

## 2. Tool-Call Rate and Per-Tool Breakdown Across 10 Active Cohorts

Tool names in `canary/env.py` map to shorthand aliases as follows: `read_access_logs` (`read_logs`), `restrict_access` (`restrict`), and `advance_day` (`next_day`), alongside `check_leak_feed` and `unrestrict_access`. Canary exposes document metadata via `list_documents` and leaked items via `check_leak_feed`, so `read_document` is `0.00` across all cohorts; client-rejected non-Env tool attempts are counted under `other` (`0.00` across all active cohorts).

| cohort | n | mean calls +/- CI | calls / sim day | inv actions / day | status | list_emp | read_logs | read_msg | search_msg | list_docs | read_doc | leak_feed | plant_canary | interview | restrict | unrestrict | next_day | accuse | other |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 76.13 +/- 9.62 | 9.49 | 7.02 | 1.97 | 1.00 | 6.03 | 0.00 | 3.87 | 7.27 | 0.00 | 4.33 | 5.87 | 37.53 | 0.17 | 0.13 | 6.97 | 1.00 | 0.00 |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 128.03 +/- 12.94 | 9.61 | 7.42 | 1.50 | 1.00 | 12.27 | 0.17 | 4.23 | 12.07 | 0.00 | 6.70 | 8.50 | 68.03 | 0.10 | 0.03 | 12.47 | 0.97 | 0.00 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | 2 | 57.50 +/- 12.74 | 10.43 | 8.00 | 1.50 | 1.00 | 4.50 | 0.00 | 3.00 | 5.00 | 0.00 | 2.50 | 5.50 | 29.00 | 0.00 | 0.00 | 4.50 | 1.00 | 0.00 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | 5 | 100.20 +/- 30.43 | 9.19 | 6.97 | 1.00 | 1.00 | 10.20 | 0.40 | 5.20 | 10.20 | 0.00 | 5.40 | 5.40 | 50.40 | 0.00 | 0.00 | 10.00 | 1.00 | 0.00 |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 51.67 +/- 6.79 | 5.79 | 3.42 | 3.27 | 1.00 | 7.00 | 0.03 | 5.20 | 6.90 | 0.00 | 8.87 | 7.77 | 2.47 | 0.17 | 0.00 | 8.00 | 1.00 | 0.00 |
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
| OpenCode gemini-4-carbon hard G1 ext (34,37) | 2 | 5.50 | 5.50 | 50.0% | 12.45 (31.1%) | 0.69 | 3.00 | 0 / 0 / 11 | 0.0% (0 / 0 / 0) | 100.0% |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | 5 | 5.40 | 5.40 | 24.5% | 11.33 (28.3%) | 0.72 | 3.00 | 0 / 0 / 27 | 0.0% (0 / 0 / 0) | 100.0% |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 7.77 | 7.70 | 85.6% | 4.97 (24.8%) | 0.75 | 2.85 | 2 / 31 / 198 | 8.7% (2 / 18 / 0) | 91.3% |
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
| OpenCode gemini-4-carbon hard G1 ext (34,37) | 2 | 0.000 | 0.000 | 0/2 (0.0%) | 0/2 (0.0%) | 100.0% | 5.50 | 5.50 | 100.0% | 0/2 (0.0%) | 0.745 +/- 0.088 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | 5 | 0.000 | 0.000 | 0/5 (0.0%) | 0/5 (0.0%) | 100.0% | 11.00 | 11.00 | 100.0% | 0/5 (0.0%) | 0.656 +/- 0.110 |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 0.167 | 0.000 | 1/30 (3.3%) | 0/30 (0.0%) | 100.0% | 9.00 | 9.00 | 83.3% | 5/30 (16.7%) | 0.434 +/- 0.236 |
| in-process gemini-4-carbon medium (0-29) | 30 | 0.400 | 0.167 | 6/30 (20.0%) | 4/30 (13.3%) | 86.7% | 9.04 | 9.70 | 83.3% | 1/30 (3.3%) | 0.530 +/- 0.138 |
| in-process gemini-4-carbon hard (0-29) | 30 | 0.267 | 0.267 | 1/30 (3.3%) | 1/30 (3.3%) | 96.7% | 12.69 | 12.97 | 93.3% | 1/30 (3.3%) | 0.473 +/- 0.118 |
| reference solver medium (0-29) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 3/30 (10.0%) | 90.0% | 7.56 | 8.20 | 90.0% | 0/30 (0.0%) | 0.645 +/- 0.087 |
| reference solver hard (0-29) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 0/30 (0.0%) | 100.0% | 10.60 | 10.60 | 96.7% | 1/30 (3.3%) | 0.499 +/- 0.119 |
| reference solver hard (30-59) | 30 | 0.000 | 0.000 | 0/30 (0.0%) | 1/30 (3.3%) | 96.7% | 8.41 | 8.83 | 90.0% | 2/30 (6.7%) | 0.498 +/- 0.156 |

## 5. Token, Prompt-Cache, and Wall-Clock Efficiency (OpenCode + In-Process Reference)

All `5` active OpenCode cohorts record `meta.usage` (`in`, `cached_in`, `out`, `llm_calls`) and per-episode `meta.wall_s`. The `2` in-process `gemini-4-carbon` cohorts record `meta.usage` (`in`, `cached_in`, `out`, `calls`) without `wall_s`, allowing direct token-overhead comparison on identical seeds `0-29`:

| cohort | harness | n | mean `usage.in` | mean `usage.cached_in` | mean uncached in | mean `usage.out` | cached input % (agg / ep) | mean LLM calls | mean `wall_s` +/- CI | min / max `wall_s` | `>2400s` / `>3600s` |
|---|---|---:|---:|---:|---:|---:|---|---:|---|---|---|
| OpenCode gemini-4-carbon medium (0-29) | opencode | 30 | 3.44M | 3.23M | 213.4k | 45.7k | 93.80% / 92.95% | 77.0 | 1538.2s +/- 323.7s | 679.8s / 5427.0s | 2 / 1 |
| OpenCode gemini-4-carbon hard (0-29) | opencode | 30 | 8.79M | 8.42M | 365.4k | 70.5k | 95.84% / 95.45% | 129.0 | 2630.4s +/- 421.9s | 962.1s / 6591.7s | 13 / 5 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | opencode | 2 | 2.54M | 2.37M | 170.4k | 49.3k | 93.28% / 93.28% | 58.5 | 1506.2s +/- 224.2s | 1391.8s / 1620.6s | 0 / 0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | opencode | 5 | 5.98M | 5.71M | 265.8k | 62.7k | 95.55% / 95.16% | 101.2 | 1641.5s +/- 638.0s | 921.8s / 2858.9s | 1 / 0 |
| OpenCode gemini-3.5-flash medium (0-29) | opencode | 30 | 1.46M | 1.31M | 152.2k | 17.2k | 89.57% / 87.79% | 51.2 | 151.6s +/- 22.2s | 65.6s / 346.3s | 0 / 0 |
| in-process gemini-4-carbon medium (0-29) | inproc | 30 | 2.84M | 2.60M | 239.9k | 35.2k | 91.56% / 89.88% | 94.4 | n/a | n/a | n/a |
| in-process gemini-4-carbon hard (0-29) | inproc | 30 | 5.49M | 5.17M | 321.7k | 52.4k | 94.14% / 93.00% | 116.1 | n/a | n/a | n/a |

## 6. Paired Harness, Model-Family, and Cross-Run Deltas

- **OpenCode vs In-Process (`gemini-4-carbon`, `n=30` paired seeds per tier):** OpenCode uses `1.21x` (medium) and `1.60x` (hard) as many input tokens per episode due to MCP/CLI scaffold context, yet high prefix cache hit rates (`93.80%` and `95.84%`) keep uncached input down to `213.4k` and `365.4k` tokens/episode. Both harnesses show the same interview-heavy signature (`-9.77` interviews/ep delta on medium, `+10.77` on hard) and nearly identical hard canary counts (`8.47` vs `8.57`).
- **`gemini-4-carbon` vs `gemini-3.5-flash` on OpenCode medium (`n=30` paired seeds `0-29`):** `gemini-4-carbon` executes `+24.47` more tool calls/episode (driven by `+35.07` more interviews) and runs `10.1x` longer in wall-clock time while eliminating single-variant canary errors (`0` vs `2`) and solving `30/30` medium seeds (`100.0%` vs `83.3%`). Paired hard carbon-vs-flash rows remain gated on `gap_ships_flash_hard(root)`.
- **G1 committed extension (`seeds [34, 37]`) vs FR8 hard replication (`seeds 30, 34, 42, 45, 57`):** Both extension/replication OpenCode `gemini-4-carbon` cohorts achieve `100.0%` targeted `2-3` canary split discipline and `0.000` `restrict_access` calls/episode, with `seed 34` cross-run consistency (`G1 +0.790` vs `FR8 +0.820`, delta `-0.030`, both accusing `e29`).
