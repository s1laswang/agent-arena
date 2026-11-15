# Statistical Robustness and Shallow-CI Audit (`v1.4` Paired Seeds `0-29`)

## Executive Summary & Honest Headline Disclosures

- **Seed lock provenance:** `post-hoc locked dev seeds 0-29 (commit 671ed96, 28 s after 8fd4dec, not pre-registered)`. All primary evaluations pair each frontier model strictly against `reference/solver` on seeds `0..29` (`n = 30` per tier; `solver-hard-seeds30to59` excluded from primary `0..29` pairing).
- **`opencode-gemini-4-carbon` on `hard` (`n = 30`, MCP tools only):** Raw ratio is **`64.6%`** (`+0.322` vs `+0.499`; percentile `[23.8%, 98.3%]`, BCa `[15.9%, 94.3%]`, Fieller `[24.7%, 105.5%]`, sign-flip perm `p = 0.0930`, Wilcoxon `p = 0.2965`). Note that while percentile and BCa raw 95% CIs stay just below `100%`, Fieller's exact paired studentized 95% CI reaches `105.5%` (`p_perm = 0.0930`). Under **luck-adjusted EV** (`SolverPolicy` posterior `paired_v13.post_expected`), the ratio is **`72.0%`** (`+0.360` vs `+0.499`) and **all 3 CIs exclude parity**: percentile `[51.7%, 91.2%]`, BCa `[49.5%, 90.0%]`, Fieller `[51.2%, 93.5%]`, with sign-flip perm `p = 0.0106` and Wilcoxon `p = 0.0221`.
- **Exact Leave-One-Seed-Out (`n = 29` jackknife) stability:** Dropping any single seed `0..29` on `opencode-gemini-4-carbon` hard keeps **all `30/30` luck-adjusted ratios `< 100%`** (min `69.0%` on seed `24`, median `71.7%`, max `77.3%` on seed `5`) and **all `30/30` raw ratios `< 100%`** (`60.8%` to `74.7%`).
- **Pre-registered second frontier family `opencode-gpt-5.5` (`cf394894`, `n = 30`, MCP tools only):** Matches the solver at **`100.9%`** raw (percentile `[78.6%, 140.3%]`, BCa `[81.2%, 150.0%]`, Fieller `[76.5%, 139.6%]`) and **`83.7%`** luck-adjusted (percentile `[66.5%, 103.1%]`, BCa `[65.6%, 102.0%]`, Fieller `[65.8%, 104.7%]`). All three 95% CIs straddle `100%` on both raw and luck-adjusted scores; raw LOO straddles parity (`9/30` subsets `< 100%`, range `91.0%` to `106.4%`), while LA LOO spans `81.0%` to `87.7%`. On abstained seeds `[0, 17]`, `accused is None` yields exact `0.0` EV while all `28` accused episodes store `V_final` in `ep['meta']['V_final']`.
- **Harbor 3x10 judge-path rehearsal (`afterquery-final` `1bc3e281`, corrected in `aa1c679e` / `5f9b3297`):** Three `gemini-4-carbon` runs scored **`93%` (`+0.472`)**, **`116%` (`+0.585`)**, and **`131%` (`+0.626`, `n = 9` valid, `5` finished after the `08:30` cutoff vs `08:52` `n = 7` partial `+0.656` / `153%`)** relative to same-task oracle (`+0.506` on all 10 tasks; `+0.478` on run 3's 9 valid tasks). **The 65% MCP-only hard gap did not reproduce in the Harbor container with shell.**
- **Headline cross-check & shallow-CI guarantee:** `0` `git` subprocess calls (safe under `--depth=1 --no-tags` or `.git`-free directories) and `96` scalar fields cross-checked against `results/eval_v14/headline_gap_table_v14.json` (max abs diff `0.00e+00`).

## Section A: 4-Way Paired Inference Matrix (`n = 30`, Seeds `0-29`)

Parameters: Percentile & BCa paired bootstrap `B = 10000`, `rng_seed = 0`; Fieller's theorem exact paired ratio CI using sample `Cov(F, S)` with `df = 29` (`t_0.975,29 = 2.0452`); paired sign-flip permutation `B = 20000`, `rng_seed = 0`; exact DP Wilcoxon signed-rank test.

### A.1 Raw Score Paired Inference

| Cohort | Tier | F Mean | S Mean | Ratio | Pct Boot 95% CI | BCa Boot 95% CI | Fieller 95% CI | Cov(F,S) | Sign-Flip p | Wilcoxon p |
|---|---|---:|---:|---:|---|---|---|---:|---:|---:|
| `opencode-gemini-4-carbon` | `hard` | `+0.322` | `+0.499` | `64.6%` | `[23.8%, 98.3%]` | `[15.9%, 94.3%]` | `[24.7%, 105.5%]` | `+0.0632` | `0.0930` | `0.2965` |
| `inproc-gemini-4-carbon` | `hard` | `+0.473` | `+0.499` | `94.8%` | `[62.2%, 140.0%]` | `[61.5%, 138.4%]` | `[63.0%, 141.7%]` | `-0.0219` | `0.7865` | `0.7188` |
| `opencode-gemini-3.5-flash` | `hard` | `+0.373` | `+0.499` | `74.7%` | `[35.9%, 122.8%]` | `[31.1%, 116.3%]` | `[36.0%, 125.1%]` | `-0.0141` | `0.2779` | `0.4676` |
| `opencode-gpt-5.5` | `hard` | `+0.504` | `+0.499` | `100.9%` | `[78.6%, 140.3%]` | `[81.2%, 150.0%]` | `[76.5%, 139.6%]` | `-0.0067` | `0.9626` | `0.6887` |
| `opencode-gemini-4-carbon` | `medium` | `+0.713` | `+0.645` | `110.5%` | `[99.3%, 127.0%]` | `[100.4%, 130.3%]` | `[97.8%, 127.0%]` | `+0.0113` | `0.1110` | `0.2245` |
| `inproc-gemini-4-carbon` | `medium` | `+0.530` | `+0.645` | `82.2%` | `[56.4%, 107.6%]` | `[52.7%, 104.4%]` | `[57.8%, 110.6%]` | `-0.0082` | `0.2098` | `0.3390` |

### A.2 Luck-Adjusted (`SolverPolicy` Posterior EV) Paired Inference

| Cohort | Tier | F LA | S LA | LA Ratio | Pct Boot 95% CI | BCa Boot 95% CI | Fieller 95% CI | Cov(F,S) | Sign-Flip p | Wilcoxon p |
|---|---|---:|---:|---:|---|---|---|---:|---:|---:|
| `opencode-gemini-4-carbon` | `hard` | `+0.360` | `+0.499` | `72.0%` | `[51.7%, 91.2%]` | `[49.5%, 90.0%]` | `[51.2%, 93.5%]` | `+0.0168` | `0.0106` | `0.0221` |
| `inproc-gemini-4-carbon` | `hard` | `+0.421` | `+0.499` | `84.3%` | `[65.0%, 105.8%]` | `[64.3%, 104.8%]` | `[64.3%, 107.4%]` | `+0.0001` | `0.1629` | `0.2894` |
| `opencode-gemini-3.5-flash` | `hard` | `+0.110` | `+0.499` | `22.0%` | `[-22.6%, 63.2%]` | `[-26.2%, 60.5%]` | `[-24.3%, 67.6%]` | `+0.0137` | `0.0013` | `0.0221` |
| `opencode-gpt-5.5` | `hard` | `+0.418` | `+0.499` | `83.7%` | `[66.5%, 103.1%]` | `[65.6%, 102.0%]` | `[65.8%, 104.7%]` | `-0.0012` | `0.1119` | `0.1840` |
| `opencode-gemini-4-carbon` | `medium` | `+0.652` | `+0.645` | `101.1%` | `[85.3%, 118.6%]` | `[84.6%, 117.7%]` | `[85.2%, 119.8%]` | `+0.0179` | `0.8980` | `0.7749` |
| `inproc-gemini-4-carbon` | `medium` | `+0.479` | `+0.645` | `74.3%` | `[51.7%, 99.1%]` | `[51.1%, 98.2%]` | `[51.5%, 101.5%]` | `-0.0202` | `0.0620` | `0.1241` |

## Section B: Exact 30-Subset Leave-One-Seed-Out (`n = 29` Jackknife) Bounds

All `30` `n = 29` subsets are indexed strictly by dropped seed index `0..29` (no mole employee IDs recorded).

| Cohort | Tier | Raw Ratio Min / Med / Max | Raw `<100%` | LA Ratio Min / Med / Max | LA `<100%` | Raw Diff Min / Med / Max | LA Diff Min / Med / Max |
|---|---|---|---:|---|---:|---|---|
| `opencode-gemini-4-carbon` | `hard` | `60.8%` (seed 14) / `63.4%` / `74.7%` (seed 1) | `30/30` | `69.0%` (seed 24) / `71.7%` / `77.3%` (seed 5) | `30/30` | `-0.199` / `-0.181` / `-0.124` | `-0.157` / `-0.141` / `-0.114` |
| `inproc-gemini-4-carbon` | `hard` | `84.8%` (seed 15) / `94.4%` / `106.5%` (seed 6) | `29/30` | `81.1%` (seed 23) / `83.7%` / `88.9%` (seed 6) | `30/30` | `-0.084` / `-0.028` / `+0.032` | `-0.096` / `-0.081` / `-0.055` |
| `opencode-gemini-3.5-flash` | `hard` | `65.7%` (seed 15) / `73.8%` / `85.6%` (seed 21) | `30/30` | `17.9%` (seed 19) / `19.8%` / `29.2%` (seed 27) | `30/30` | `-0.189` / `-0.129` / `-0.071` | `-0.412` / `-0.400` / `-0.349` |
| `opencode-gpt-5.5` | `hard` | `91.0%` (seed 15) / `101.3%` / `106.4%` (seed 17) | `9/30` | `81.0%` (seed 10) / `83.4%` / `87.7%` (seed 17) | `30/30` | `-0.049` / `+0.006` / `+0.031` | `-0.097` / `-0.083` / `-0.060` |
| `opencode-gemini-4-carbon` | `medium` | `106.4%` (seed 20) / `110.9%` / `112.7%` (seed 7) | `0/30` | `96.9%` (seed 20) / `101.1%` / `105.9%` (seed 7) | `3/30` | `+0.043` / `+0.070` / `+0.081` | `-0.021` / `+0.007` / `+0.037` |
| `inproc-gemini-4-carbon` | `medium` | `78.7%` (seed 20) / `81.5%` / `90.9%` (seed 18) | `30/30` | `70.7%` (seed 20) / `73.4%` / `79.6%` (seed 11) | `30/30` | `-0.142` / `-0.118` / `-0.058` | `-0.195` / `-0.170` / `-0.130` |

## Section C: Harbor 3x10 Judge-Path Rehearsal Sensitivity (`afterquery-final` `1bc3e281`)

- **Provenance:** Tag `afterquery-final` (`1bc3e281`), Harbor `0.26.0`, hard judge tasks `900000-900009` (`n = 10` tasks). Zero baselines `do_nothing` and `stop_early` both scored `+0.000` (`10/10`).
- **Cutoff & snapshot reconciliation (`aa1c679e` / `5f9b3297`, full trials on `d0ead011`):** The `08:52` snapshot captured `opencode-3` at `n = 7` valid trials (`+0.656` vs same-7-task oracle `+0.429` = `153% [89%, 411%]`). After all running trials completed (`09:30`), `opencode-3` finished with `n = 9` valid trials (`5` completed after the `08:30` cutoff, `1` provider rate-limit infra exclusion on `900002`), scoring `+0.626` vs same-9-task oracle `+0.478` = **`131% [86%, 590%]`**.
- **Run-to-run spread:** Final 3-run means are `+0.472`, `+0.585`, `+0.626` (mean of means `+0.561`, SD `0.080`, range `0.154`, `28/29` valid accusations correct vs 10-task oracle `+0.506`).
- **Denominator sensitivity & honest non-reproduction:** On task 900007 oracle scored -1.00 while opencode-1/2/3 scored +0.66/+0.61/+0.65; at n=10 this single task drives Fieller g=0.569 (and g=1.874 > 1 unbounded on n=7 snapshot) and inflates upper bootstrap bounds to 363%-590%, whereas n=30 v1.4 hard has Fieller g=0.062. More importantly, **the 65% MCP-only hard gap did not reproduce in the Harbor container** (`shell used in 20 of 28 valid trials; container also carries 15 Nov afterquery-final (1bc3e281) tool-error detail and W1 wording updates`).

| Run | n Valid | Infra Excl | Correct / Accused | Mean | Same-Task Oracle | Ratio | Paired Boot 95% CI | Fieller 95% CI (g) | Paired Diff |
|---|---:|---:|---|---:|---:|---:|---|---|---:|
| `opencode-1` | `10` | `0` | `9 / 10` | `+0.472` | `+0.506` | `93.3%` (`93%`) | `[19.9%, 370.6%]` | `[16.0%, 461.5%]` (g=0.569) | `-0.034` |
| `opencode-2` | `10` | `0` | `10 / 10` | `+0.585` | `+0.506` | `115.6%` (`116%`) | `[78.3%, 363.3%]` | `[63.9%, 475.7%]` (g=0.569) | `+0.079` |
| `opencode-3-final` | `9` | `1` | `9 / 9` | `+0.626` | `+0.478` | `131.0%` (`131%`) | `[86.0%, 590.0%]` | `n/a (summary-level final)` | `+0.148` |
| `opencode-3-snapshot-0852-partial` | `7` | `1` | `7 / 7` | `+0.656` | `+0.429` | `153.0%` (`153%`) | `[89.5%, 411.2%]` | `unbounded (g>=1)` (g=1.874) | `+0.227` |

## Reproduction

```bash
python scripts/eval_statistical_robustness_v14.py
python scripts/eval_statistical_robustness_v14.py --check
```
