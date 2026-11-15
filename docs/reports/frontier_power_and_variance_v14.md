# Canary v1.4 Statistical Power, Luck-Adjustment Variance Reduction, and Harbor n=10 Subsample Reconciliation

Synced to `justSilas@5f9b3297` across the replay-verified `777`-episode v1.4 corpus (`472` committed + `305` FR8 replication; `0` mismatches, `0` timeout/error episodes in valid JSONL) plus `60` replay-verified G2 hard `0-29` episodes (`gemini-4-argon` `103%/60%`, `gemini-4-hydrogen` `115%/97%` from `results/frontier_replication/v1.4/g2_families_audit.json`, pre-registered `f9fb7a4a`, landed `8911130e`). Primary `gemini-4-carbon` `0-29` carries post-hoc lock `671ed96` (`28s` after `8fd4dec`); pre-registered OpenCode `gpt-5.5` (`cf394894` -> `ca0a0dc0`, `101%/84%`) has clean `rc=0` non-accuse seeds `[0, 17]`. Pure CPU, zero live API calls, zero subprocesses, zero `.git` runtime calls.

## Headline Findings

1. **Luck-adjustment (`post_expected`) yields a `3.48x` paired variance reduction (`N_eff = 104.4` raw episodes at `n=30`) on primary OpenCode `gemini-4-carbon` hard (`0-29`):** Four `-1.0` cliff realizations (`seeds [1, 15, 18, 26]`) contribute `78.1%` of Carbon hard's raw score sum-of-squares, inflating paired diff SD from `0.290` to `0.542` and widening the paired bootstrap 95% ratio CI from `[52%, 91%]` (`39 pp` rounded / `39.5 pp` exact) to `[24%, 98%]` (`74 pp` rounded / `74.5 pp` exact; `1.89x` CI compression). Across all `5` hard `0-29` cohorts, `Var(raw_diff) / Var(la_diff)` exceeds `1.0` (`1.35x` to `3.48x`), including zero-wrong `gpt-5.5` (`2.06x`, `N_eff = 61.7`) because solver seed `15` carries its own `-1.0` noisy-canary cliff. Only `gemini-4-carbon` medium (`30/30` empirical accuracy with lucky gambles on seeds `[7, 29]`) has `VRF = 0.59x < 1` because zero Bernoulli cliff flips materialized.
2. **MDE at 80% power (`alpha=0.05` two-sided) explains why `n=10` is uninformative on raw scores and why `n=30..36` luck-adjusted crosses the primary gap:** On `gemini-4-carbon` hard, at `n=10` raw paired-`t` MDE is `0.540` (`108.1%` of solver; normal-approx `0.480` = `96.2%`). At `n=30`, luck-adjusted paired-`t` MDE falls from `0.287` (`57.5%` of solver, power `40.8%`) to `0.154` (`30.8%` of solver, power `72.1%`), reaching 80% paired-`t` power for the observed `-0.140` (`28.0%` of solver) luck-adjusted gap at `n = 36` (`n = 34` normal-approx) vs `n = 76` (`n = 74` normal-approx) under raw scoring.
3. **Exact `n=10` sampling from locked `gemini-4-carbon` hard `0-29` (`64.6%` of solver) reconciles single-run Harbor variance while isolating shared-world + harness effects across `[93%, 116%, 131%]` (`d0ead011`):** Drawing `n=10` without replacement from `hard 0-29` (`4/30` wrong) yields exact hypergeometric `P(0 wrong) = 17.68%` (`23.91%` binomial WR) and `P(<=1 wrong) = 59.28%` (`60.69%` WR). Because Carbon averages `97.2%` of solver (`+0.526` vs `+0.541`) on its `26` non-wrong seeds, exact `P(sample_ratio_vs_solver >= 0.93 | n=10, WOR) = 17.84%` (`22.17%` WR) and `P(>= 1.00 | n=10, WOR) = 11.52%` (`15.14%` WR). Thus a single `93%` (`9/10`) run (`opencode-1`) occurs ~1 in 5 times by chance alone, whereas `[116%, 131%]` (`28/29` pooled accuracy across `[10, 10, 9]`) reflects (i) all 3 Harbor runs sharing the same 10 fixed judge tasks where oracle hit a `-1.00` cliff on `hard-900007`, plus (ii) Harbor bash shell access (`20/28` trials) and `1bc3e281` error/prompt updates.

## 1. Luck-Adjustment Variance Reduction and Effective Sample Size (`0-29` Paired Cohorts)

| Cohort | Wrong (F/S) | SD(raw diff) | SD(la diff) | VRF = Var(raw)/Var(la) | N_eff (at n=30) | Raw / Solver [95% CI] (span) | LA / Solver [95% CI] (span) |
|---|---|---:|---:|---:|---:|---|---|
| OpenCode gemini-4-carbon hard (0-29) | 4/1 | 0.542 | 0.290 | 3.48x | 104.4 | 65% [24%, 98%] (74 pp) | 72% [52%, 91%] (39 pp) |
| OpenCode gemini-4-carbon medium (0-29) | 0/0 | 0.225 | 0.293 | 0.59x | 17.7 | 111% [99%, 127%] (28 pp) | 101% [85%, 119%] (34 pp) |
| in-process gemini-4-carbon hard (0-29) | 1/1 | 0.513 | 0.300 | 2.92x | 87.5 | 95% [62%, 140%] (78 pp) | 84% [65%, 106%] (41 pp) |
| in-process gemini-4-carbon medium (0-29) | 1/0 | 0.474 | 0.468 | 1.03x | 30.9 | 82% [56%, 108%] (52 pp) | 74% [52%, 99%] (47 pp) |
| OpenCode gpt-5.5 hard (0-29) | 0/1 | 0.395 | 0.276 | 2.06x | 61.7 | 101% [79%, 140%] (61 pp) | 84% [67%, 103%] (36 pp) |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | 5/0 | 0.700 | 0.573 | 1.49x | 44.8 | 67% [29%, 103%] (74 pp) | 75% [45%, 105%] (60 pp) |
| G2 OpenCode gemini-4-argon hard (0-29) | 1/1 | 0.471 | 0.386 | 1.49x | 44.7 | 103% [71%, 144%] (73 pp) | 60% [33%, 85%] (52 pp) |
| G2 OpenCode gemini-4-hydrogen hard (0-29) | 0/1 | 0.368 | 0.317 | 1.35x | 40.5 | 115% [92%, 157%] (65 pp) | 97% [75%, 119%] (44 pp) |

## 2. Minimum Detectable Effect (`MDE` at 80% Power, Two-Sided `alpha=0.05`) Across `n in {6, 9, 10, 20, 30, 32, 35, 36, 60}`

### 2a. Primary OpenCode `gemini-4-carbon` Hard (`0-29` Empirical Variance: Raw SD `0.542`, LA SD `0.290`)

| n | Canary v1.4 Cohort Meaning | Raw MDE_t (% sol) | Raw MDE_z (% sol) | Raw Power_t (@ -0.177) | LA MDE_t (% sol) | LA MDE_z (% sol) | LA Power_t (@ -0.140) |
|---:|---|---|---|---|---|---|---|
| 6 | `carbon_hard_30_59_dedup_union` | 0.777 (155.8%) | 0.620 (124.2%) | 10.1% | 0.417 (83.5%) | 0.332 (66.5%) | 16.2% |
| 9 | `harbor_rehearsal_opencode_3_valid` | 0.578 (115.9%) | 0.506 (101.4%) | 13.9% | 0.310 (62.1%) | 0.271 (54.3%) | 24.7% |
| 10 | `harbor_rehearsal_opencode_1_2_and_v13_planned` | 0.540 (108.1%) | 0.480 (96.2%) | 15.2% | 0.289 (58.0%) | 0.257 (51.5%) | 27.5% |
| 20 | `v12_and_initial_solver_0_19` | 0.358 (71.7%) | 0.339 (68.0%) | 28.3% | 0.192 (38.4%) | 0.182 (36.4%) | 53.3% |
| 30 | `v14_locked_primary_0_29` | 0.287 (57.5%) | 0.277 (55.5%) | 40.8% | 0.154 (30.8%) | 0.149 (29.8%) | 72.1% |
| 32 | `v14_pooled_0_29_plus_g1_ext` | 0.277 (55.5%) | 0.268 (53.8%) | 43.2% | 0.149 (29.7%) | 0.144 (28.8%) | 75.1% |
| 35 | `v14_0_29_plus_fr8_rep` | 0.264 (52.9%) | 0.257 (51.4%) | 46.6% | 0.142 (28.4%) | 0.138 (27.6%) | 79.0% |
| 36 | `v14_0_29_plus_dedup_union` | 0.260 (52.1%) | 0.253 (50.7%) | 47.7% | 0.140 (27.9%) | 0.136 (27.2%) | 80.1% |
| 60 | `v14_full_0_59_target` | 0.199 (39.9%) | 0.196 (39.3%) | 70.0% | 0.107 (21.4%) | 0.105 (21.0%) | 95.6% |

### 2b. Paired-`t` MDE (`% of solver`, 80% Power) Across All Paired `0-29` Cohorts (`Raw -> Luck-Adjusted`)

| Cohort | n=6 | n=10 | n=20 | n=30 | n=36 | n=60 | n* (15% sol, Raw -> LA) |
|---|---|---|---|---|---|---|---:|
| OpenCode gemini-4-carbon hard (0-29) | 156%->83% | 108%->58% | 72%->38% | 57%->31% | 52%->28% | 40%->21% | 414 -> 121 |
| OpenCode gemini-4-carbon medium (0-29) | 50%->65% | 35%->45% | 23%->30% | 18%->24% | 17%->22% | 13%->17% | 45 -> 74 |
| in-process gemini-4-carbon hard (0-29) | 147%->86% | 102%->60% | 68%->40% | 54%->32% | 49%->29% | 38%->22% | 371 -> 129 |
| in-process gemini-4-carbon medium (0-29) | 106%->104% | 73%->72% | 49%->48% | 39%->38% | 35%->35% | 27%->27% | 191 -> 186 |
| OpenCode gpt-5.5 hard (0-29) | 114%->79% | 79%->55% | 52%->36% | 42%->29% | 38%->27% | 29%->20% | 221 -> 109 |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | 156%->127% | 108%->88% | 72%->59% | 57%->47% | 52%->43% | 40%->33% | 414 -> 278 |
| G2 OpenCode gemini-4-argon hard (0-29) | 136%->111% | 94%->77% | 62%->51% | 50%->41% | 45%->37% | 35%->28% | 314 -> 211 |
| G2 OpenCode gemini-4-hydrogen hard (0-29) | 106%->91% | 74%->63% | 49%->42% | 39%->34% | 35%->30% | 27%->23% | 193 -> 143 |

## 3. Exact `n=10` and `n=9` Sampling Distribution from `gemini-4-carbon` Hard `0-29` vs Harbor Rehearsal (`d0ead011`)

| Sampling Regime | n | P(0 wrong) | P(<=1 wrong) | P(ratio >= 0.93) | P(ratio >= 1.00) | P(ratio >= 1.16) | P(ratio >= 1.31) | Ratio Median [2.5%, 97.5%] |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Exact Combinatorial / Hypergeom (WOR) | 10 | 17.68% | 59.28% | 17.84% | 11.52% | 2.20% | 0.28% | n/a (exact tail enumeration) |
| Seeded 10,000 Draws (WOR, seed=20261115) | 10 | 17.76% | 59.78% | 17.95% | 11.62% | 2.22% | 0.26% | 65.6% [7.0%, 115.0%] |
| Seeded 10,000 Draws / Binomial (WR, seed=20261115) | 10 | 23.91% | 60.69% | 22.17% | 15.14% | 4.54% | 1.05% | 67.9% [-14.4%, 122.4%] |
| Exact Combinatorial / Hypergeom (WOR, `opencode-3` size) | 9 | 21.84% | 65.52% | 20.45% | 13.70% | 3.16% | 0.55% | n/a (exact tail enumeration) |

Conditional on wrong-accusation count `W` in `n=10` WOR draws (`seed=20261115`): `E[ratio | W=0] = 97.8%`, `E[ratio | W=1] = 75.3%`, `E[ratio | W=2] = 47.4%`, `E[ratio | W>=3] = 12.3%`. In `hard 0-29`, `seed 15` is a joint `-1.0` cliff for both solver and Carbon (`67.1%` -> `59.9%` when drawn); by contrast, when an agent achieves `W=0` (`10/10`) on a 10-task set containing one unilateral oracle `-1.0` cliff (matching Harbor `hard-900007`), expected ratio jumps to `135.8%` (aligning with Harbor `opencode-2` `116%` and `opencode-3` `131%`).

## Reproduce

```bash
PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --write
PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --check
pytest -q tests/test_frontier_power_and_variance_v14.py
```
