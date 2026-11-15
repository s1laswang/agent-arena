# Canary v1.4 Cross-Model Comparison and Seeds 30-59 Extension Audit

Generated deterministically offline from committed working-tree caches (`0` live LLM calls, single-process) by:
```bash
python scripts/eval_replication_and_crossmodel.py
python scripts/eval_replication_and_crossmodel.py --check
```

## Headline Anchor and Provenance Discipline

- **Authoritative headline table of record:** `docs/reports/gap.md` and `data/runs/committed/v1.4/paired_table_gemini.md`.
- **Primary `hard` headline (`opencode-gemini-4-carbon`, `n=30`, `seeds 0-29`):** raw **`65% [24%, 98%]`** (`64.6% [23.8%, 98.3%]`, `+0.322 +/- 0.199` vs solver `+0.499 +/- 0.119`, paired diff `-0.177 +/- 0.194`, bootstrap 95% CI `[-0.384, -0.008]`) first; luck-adjusted **`72% [52%, 91%]`** (`72.0% [51.7%, 91.2%]`, `+0.360` vs solver `+0.499`) second.
- **Second frontier family (`opencode-gpt-5.5`, MCP tools only, `cf394894`, `n=30`, `seeds 0-29`):** raw **`101% [79%, 140%]`** (`100.9% [78.6%, 140.3%]`, `+0.504 +/- 0.064` vs solver `+0.499 +/- 0.119`, paired diff `+0.005 +/- 0.141`, bootstrap 95% CI `[-0.124, +0.151]`), luck-adjusted **`84% [67%, 103%]`** (`83.7% [66.5%, 103.1%]`, `+0.418` vs solver `+0.499`); `28/28` accusations correct (`0` wrong, `2` text-only non-accusations on seeds `[0, 17]` scoring `0.0`, `0/30` sub-breakeven gambles); **no gap for `gpt-5.5`**.
- **Harbor 3x10 container judge-path rehearsal (`afterquery-final` `1bc3e281`, `results/harbor/rehearsal/TABLE.md`, corrected in `aa1c679e` / `5f9b3297`, full trials on `s1-rehearsal-final` `d0ead011`):** Harbor `0.26.0` + OpenCode + `gemini-4-carbon` across `3` runs on `10` hard judge tasks (`900000-900009`; container shell enabled, used in `20/28` trials; `28/29` valid accusations correct) scored **`93%`** (`+0.472`, `93% [20%, 371%]`, `n=10` valid), **`116%`** (`+0.585`, `116% [78%, 363%]`, `n=10` valid), and **`131%`** (`+0.626`, `131% [86%, 590%]` on `9` valid trials, `5` after `08:30` cut-off, `1` infra-excluded; `08:52` partial `n=7` snapshot `153% [89%, 411%]` / `+0.656`) vs same-task oracle (`+0.506` on all `10` tasks, `+0.478` on run 3's `9` valid tasks; `do_nothing = +0.000`, `stop_early = +0.000`). **The MCP-only `65%` gap did NOT reproduce in the Harbor container.**
- **Post-hoc seed lock vs true pre-registrations (Panel Fix A, commits `92708834` and `dcd8c372`):** Primary `seeds 0-29` were **post-hoc locked in `671ed96` (28 s after `8fd4dec`), not pre-registered** (a lock against later reruns and cherry-picking). By contrast, the `seeds 30-59` hard extension (`f9fb7a4a`), the `--hint gather` causal test (`fd8c1cb0`), and the second frontier family `gpt-5.5` OpenCode `1.19.5` `v1.4` hard run (`cf394894`, `seeds 0-29`, stop `08:15` Helsinki / `$200` cap, tag `afterquery-final`; committed (`n=30` on `hard`)) were pre-registered before any episode.

## Data Rule and Step-Level Replay Integrity

- Rules version verified: `v1.4` (`Env(tier, seed)` step-by-step tool replay + final score tolerance `1e-09`; backward-compatible with Panel Fix D commit `1bc3e281` `invalid arguments` `data.detail` payloads).
- Working-tree self-contained: `True` (zero reliance on unmerged or moving remote git refs).
- Total episode records inspected and replay-verified: `902/902` valid (`44960` MCP/Env steps verified, `2` client-truncated byte lengths verified, `1` client-only unavailable-tool steps skipped, `0` rejected by DATA RULE).
- Fleet shard wall-clock guard: `wall_s < 3590s` (`rc != timeout`, `end_reason != error`, `valid != False`).
- Primary `0-29` clean completions exceeding 3590s (post-hoc locked in `671ed96`, run prior to the fleet 3600s cap, motivating Harbor's `3600s -> 10800s` bump in commit `512836b9`): `6` episodes, all `rc=0` and replay-exact.
- Reference solver `0-29` split (`20 + 10` dirs, strictly filtered to `seeds 0-29` and never mixing committed `solver-hard-seeds30to59` `30-59` `n=30`): medium `solver-medium-20261114-121126` (`0-19`, `n=20`), `solver-medium-seeds20to29` (`20-29`, `n=10`); hard `solver-hard-20261114-121126` (`0-19`, `n=20`), `solver-hard-seeds20to29` (`20-29`, `n=10`); `30-59` extension/replication paired directly against `data/runs/committed/v1.4/reference/solver-hard-seeds30to59`.
- Hard clearance disclosure (`docs/DIFFICULTY.md` W4 / `92708834`): `access_constraints` on `hard` never binds because `canary_level = 1` while every employee's clearance is `1-3`.
- Paired bootstrap: `10000` resamples over shared seeds (`seed=0`).

## Part A: Primary Evaluation (`seeds 0-29`, Post-Hoc Seed Lock `671ed96`)

Seeds 0-29 per tier were post-hoc locked in commit 671ed96 (28 s after 8fd4dec), not pre-registered: a post-hoc lock against later reruns and cherry-picking. docs/reports/gap.md and data/runs/committed/v1.4/paired_table_gemini.md form the authoritative headline table of record (hard OpenCode gemini-4-carbon n=30: raw 65% [24%, 98%] first, luck-adjusted 72% [52%, 91%] second; on hard, access_constraints never binds per docs/DIFFICULTY.md W4). Separately, the hard seeds 30-59 extension was pre-registered before any episode in f9fb7a4a, and the gpt-5.5 OpenCode 1.19.5 v1.4 hard run (seeds 0-29, stop 08:15 / $200, tag afterquery-final) was pre-registered before any episode in cf394894 (101% [79%, 140%] raw, 84% [67%, 103%] luck-adjusted, n=30, no gap). In the Harbor 3x10 judge-path rehearsal on tag afterquery-final (1bc3e281, corrected in aa1c679e / 5f9b3297, full trials on s1-rehearsal-final d0ead011), gemini-4-carbon scored 93% (+0.472), 116% (+0.585), and 131% (+0.626 on 9 valid trials, 5 after the 08:30 cut-off, 1 infra-excluded; 08:52 partial n=7 snapshot 153% / +0.656; 28/29 valid accusations correct), so the 65% MCP-only gap did not reproduce in the Harbor container.

### Medium Tier (`seeds 0-29`, `n=30` paired per cohort)

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medium | `opencode-gemini-4-carbon` | 30 | +0.713 +/- 0.042 | 110.5% [99.3%, 127.0%] | +0.068 [-0.005, +0.152] | 1.00 | 1.00 | 8.0 | 0.96 | +0.652 | 101.1% [85.3%, 118.6%] | 2/30 (7%) | +0.061 |
| medium | `inproc-gemini-4-carbon` | 30 | +0.530 +/- 0.138 | 82.2% [56.4%, 107.6%] | -0.115 [-0.295, +0.044] | 0.83 | 0.87 | 9.0 | 0.93 | +0.479 | 74.3% [51.7%, 99.1%] | 3/30 (10%) | +0.051 |
| medium | `opencode-gemini-3.5-flash` | 30 | +0.434 +/- 0.236 | 67.3% [29.4%, 103.3%] | -0.211 [-0.469, +0.020] | 0.83 | 1.00 | 9.0 | 0.87 | +0.485 | 75.2% [44.9%, 105.4%] | 6/30 (20%) | -0.051 |
| medium | `solver` | 30 | +0.645 +/- 0.087 | 100% | 0.000 | 0.90 | 0.90 | 7.6 | 1.00 | +0.645 | 100% | 0/30 (0%) | +0.000 |
| medium | `grok_tactics` | 30 | +0.460 +/- 0.123 | 71.3% [50.9%, 94.5%] | -0.185 [-0.334, -0.032] | 0.70 | 0.70 | 7.7 | 1.00 | +0.460 | 71.3% [50.9%, 94.5%] | 0/30 (0%) | +0.000 |
| medium | `heuristic` | 30 | -0.407 +/- 0.284 | -63.1% [-107.0%, -19.2%] | -1.052 [-1.343, -0.749] | 0.37 | 1.00 | 11.3 | 0.59 | -0.064 | -9.9% [-35.7%, 17.6%] | 21/30 (70%) | -0.343 |
| medium | `logs_only` | 30 | -1.000 +/- 0.000 | -155.0% [-181.1%, -138.4%] | -1.645 [-1.723, -1.552] | 0.00 | 1.00 | 10.0 | 0.01 | -0.983 | -152.3% [-178.2%, -135.7%] | 30/30 (100%) | -0.017 |
| medium | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.645 [-0.723, -0.552] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| medium | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.645 [-0.723, -0.552] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| medium | `guess_day1` | 30 | -0.933 +/- 0.131 | -144.7% [-174.9%, -117.9%] | -1.578 [-1.710, -1.402] | 0.03 | 1.00 | 1.0 | 0.05 | -0.900 | -139.5% [-162.9%, -124.5%] | 30/30 (100%) | -0.033 |

**Provenance caveat on `opencode-gemini-3.5-flash` medium (`d4bc4f3d`, `+0.434 +/- 0.236`, raw `67.3% [29.4%, 103.3%]`, luck-adjusted `75.2% [44.9%, 105.4%]`):** Brought from PR 51 in commit d4bc4f3d across three shards at three git SHAs (medium-00-14 @ c01f371a, medium-15-29 @ 55d9781c, medium-s28 @ a5d12c7e). Seed 28 failed in medium-15-29 (meta.json status INCOMPLETE: seed [28] pending rerun) and was re-run alone as medium-s28; its first attempt is not in the committed data. Verified working-tree shards: `medium-00-14` @ `c01f371a` (`n=15`), `medium-15-29` @ `55d9781c` (`n=14`, status `INCOMPLETE: seed [28] pending rerun`), `medium-s28` @ `a5d12c7e` (`n=1`).

### Hard Tier (`seeds 0-29`, `n=30` paired per cohort)

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `opencode-gemini-4-carbon` | 30 | +0.322 +/- 0.199 | 64.6% [23.8%, 98.3%] | -0.177 [-0.384, -0.008] | 0.83 | 0.97 | 13.2 | 0.88 | +0.360 | 72.0% [51.7%, 91.2%] | 3/30 (10%) | -0.037 |
| hard | `inproc-gemini-4-carbon` | 30 | +0.473 +/- 0.118 | 94.8% [62.2%, 140.0%] | -0.026 [-0.213, +0.155] | 0.93 | 0.97 | 12.7 | 0.93 | +0.421 | 84.3% [65.0%, 105.8%] | 3/30 (10%) | +0.052 |
| hard | `opencode-gemini-3.5-flash` | 30 | +0.373 +/- 0.177 | 74.7% [35.9%, 122.8%] | -0.126 [-0.347, +0.091] | 0.90 | 1.00 | 12.7 | 0.71 | +0.110 | 22.0% [-22.6%, 63.2%] | 10/30 (33%) | +0.263 |
| hard | `opencode-gpt-5.5` | 30 | +0.504 +/- 0.064 | 100.9% [78.6%, 140.3%] | +0.005 [-0.124, +0.151] | 0.93 | 0.93 | 10.2 | 0.94 | +0.418 | 83.7% [66.5%, 103.1%] | 0/30 (0%) | +0.086 |
| hard | `solver` | 30 | +0.499 +/- 0.119 | 100% | 0.000 | 0.97 | 1.00 | 10.6 | 0.97 | +0.499 | 100% | 0/30 (0%) | -0.000 |
| hard | `grok_tactics` | 30 | +0.432 +/- 0.085 | 86.5% [66.8%, 119.3%] | -0.067 [-0.186, +0.075] | 0.93 | 0.93 | 10.4 | 0.96 | +0.384 | 77.0% [61.0%, 94.6%] | 0/30 (0%) | +0.047 |
| hard | `heuristic` | 30 | +0.086 +/- 0.204 | 17.2% [-25.8%, 59.7%] | -0.413 [-0.666, -0.171] | 0.80 | 1.00 | 14.4 | 0.78 | +0.052 | 10.5% [-20.2%, 37.4%] | 6/30 (20%) | +0.033 |
| hard | `logs_only` | 30 | -1.000 +/- 0.000 | -200.4% [-270.8%, -167.0%] | -1.499 [-1.599, -1.369] | 0.00 | 1.00 | 10.0 | 0.01 | -0.979 | -196.1% [-225.4%, -174.6%] | 30/30 (100%) | -0.021 |
| hard | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.499 [-0.599, -0.369] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.499 [-0.599, -0.369] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `guess_day1` | 30 | -1.000 +/- 0.000 | -200.4% [-270.8%, -167.0%] | -1.499 [-1.599, -1.369] | 0.00 | 1.00 | 1.0 | 0.03 | -0.950 | -190.3% [-218.5%, -169.3%] | 30/30 (100%) | -0.050 |

### Head-to-Head Cross-Model Comparison (`opencode-gemini-4-carbon` minus `opencode-gemini-3.5-flash`)

| tier | n | carbon raw | flash raw | paired raw diff [95% CI] | carbon luck-adj | flash luck-adj | paired luck-adj diff [95% CI] | carbon gambles (lucky) | flash gambles (lucky) | flash minus carbon luck |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medium | 30 | +0.713 | +0.434 | +0.279 [+0.072, +0.519] | +0.652 | +0.485 | +0.167 [-0.006, +0.358] | 2/30 (2) | 6/30 (1) | -0.112 |
| hard | 30 | +0.322 | +0.373 | -0.051 [-0.290, +0.182] | +0.360 | +0.110 | +0.250 [+0.038, +0.475] | 3/30 (2) | 10/30 (7) | +0.300 |

- **Second frontier family (`opencode-gpt-5.5` MCP-only on `hard`, `n=30`):** standalone `+0.504 +/- 0.064` (**`101% [79%, 140%]`** raw, **`84% [67%, 103%]`** luck-adjusted, `+0.418` LA; `0/30` sub-breakeven gambles); carbon minus `gpt-5.5` paired raw diff `-0.181` (`[-0.400, +0.009]`), paired luck-adjusted diff `-0.058` (`[-0.159, +0.044]`), accuracy concordance `both_correct=23`, `carbon_only=2`, `gpt55_only=5`, `neither=0`.

### Why `gemini-3.5-flash` Hard Raw Score (`74.7% [35.9%, 122.8%]`) Collapses Under Luck Adjustment (`22.0% [-22.6%, 63.2%]`)

1. **Unjustified sub-breakeven gambling (`0%` abstention)**: On `hard` seeds `0-29`, `opencode-gemini-3.5-flash` never abstains (`accused_rate = 1.00`) and accuses at mean solver posterior `P(accused) = 0.71` vs `opencode-gemini-4-carbon`'s `P(accused) = 0.88`. In `10/30` episodes (`33.3%`, seeds `[0, 2, 3, 10, 17, 18, 21, 23, 26, 27]`), `gemini-3.5-flash` accuses below the public EV break-even threshold `1 / (1 + shown_V)`, compared to `3/30` (`10.0%`) for `gemini-4-carbon`.
2. **Realized luck windfall**: Across those `10` negative-EV gambles, `gemini-3.5-flash` hit the true mole on `7/10` episodes (`0.90` overall accuracy), generating `realized_luck = +0.263` per episode vs `-0.037` for `gemini-4-carbon` (a `+0.300` per-episode luck swing).
3. **Decision-quality reversal**: Scoring each accusation by its exact solver-posterior expected value `P * V - (1 - P)` drops `gemini-3.5-flash` from `+0.373` (`74.7% [35.9%, 122.8%]`) to `+0.110` (`22.0% [-22.6%, 63.2%]` of solver), while `gemini-4-carbon` rises to `+0.360` (`72.0% [51.7%, 91.2%]` of solver), giving `gemini-4-carbon` a `+0.250` (`[+0.038, +0.475]`) paired luck-adjusted advantage on `hard` alongside a `+0.167` (`[-0.006, +0.358]`) paired luck-adjusted advantage on `medium` (`n=30`).
4. **Concordance on `hard` (`n=30`)**: Accuracy concordance is `both_correct=23`, `carbon_only=2`, `flash_only=4`, `neither=1`; sub-breakeven gamble concordance is `both_gamble=2`, `carbon_only=1`, `flash_only=8`, `neither=19`.

### Harbor 3x10 Container Judge-Path Rehearsal (`afterquery-final` `1bc3e281`, Corrected in `aa1c679e` / `5f9b3297`)

| run | n valid | infra excluded | correct / accused | mean | oracle same tasks | run / oracle [95% CI] |
|---|---:|---:|---:|---:|---:|---:|
| `opencode-1` | 10 | 0 | 9 / 10 | +0.472 | +0.506 | 93% [20%, 371%] |
| `opencode-2` | 10 | 0 | 10 / 10 | +0.585 | +0.506 | 116% [78%, 363%] |
| `opencode-3` (final; `5` after `08:30` cut-off; `s1-rehearsal-final` `d0ead011`) | 9 | 1 | 9 / 9 | +0.626 | +0.478 | 131% [86%, 590%] |
| `opencode-3` (`08:52` partial snapshot, superseded) | 7 | 1 | 7 / 7 | +0.656 | +0.429 | 153% [89%, 411%] |
| `do_nothing` / `stop_early` | 10 / 10 | 0 / 0 | 0 / 0 | +0.000 / +0.000 | +0.506 | 0% |

- **Run 3 final reconciliation (`aa1c679e` / `5f9b3297`, `s1-rehearsal-final` `d0ead011`):** The `08:52` snapshot in `results/harbor/rehearsal/TABLE.md` captured `opencode-3` mid-flight at `n=7` valid trials (`+0.656` vs same-7-task oracle `+0.429` = `153% [89%, 411%]`). Final `opencode-3` completed **`9` valid trials (`5` after the `08:30` cut-off, `1` infra-excluded)** with mean **`+0.626`** vs same-9-task oracle **`+0.478`** = **`131% [86%, 590%]`**, bringing total Harbor Gemini accuracy to **`28/29` valid accusations correct** across the three runs (`93%` `+0.472`, `116%` `+0.585`, `131%` `+0.626`).
- **Harness contrast vs MCP-only primary (`65% [24%, 98%]`):** In Harbor `0.26.0`, the isolated container provides `bash`/`python3` (used in `20/28` trials; world/seed/ledger isolation `11/11`) alongside the two disclosed 15 Nov tag changes on `afterquery-final` (`1bc3e281`). **The MCP-only `65%` gap did NOT reproduce in the Harbor container**, and on MCP-only `hard` (`n=30`) `gpt-5.5` also matches the solver (`101% [79%, 140%]` raw, `84% [67%, 103%]` luck-adjusted).

## Part B: Pre-Registered Hard Extension Audit (`seeds 30-59`, Strictly Separated from Headline)

Hard seeds 30-59 extension (opencode-gemini-4-carbon-ext) was pre-registered before any episode in commit f9fb7a4a (docs/reports/gap.md) to be reported (a) strictly separately on its own and (b) pooled with post-hoc locked primary seeds 0-29 (671ed96, 28 s after 8fd4dec) as a secondary sensitivity check only, never replacing the primary n=30 headline row.

### Committed G1 Extension (`opencode-gemini-4-carbon-ext` on Valid Seeds `[34, 37]`) and Secondary Pooled Sensitivity (`n=32`)

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `opencode-gemini-4-carbon-ext` | 2 | +0.745 +/- 0.088 | 101.4% [90.9%, 112.9%] | +0.010 [-0.070, +0.090] | 1.00 | 1.00 | 5.5 | 0.98 | +0.710 | 109.4% [105.1%, 113.6%] | 0/2 (0%) | +0.035 |
| hard | `opencode-gemini-4-carbon-pooled-sensitivity` | 32 | +0.349 +/- 0.190 | 67.9% [31.7%, 99.7%] | -0.165 [-0.358, -0.002] | 0.84 | 0.97 | 12.7 | 0.89 | +0.381 | 75.0% [55.8%, 93.5%] | 3/32 (9%) | -0.033 |

| seed | carbon score | carbon day | carbon P(acc) | carbon luck-adj | solver score | solver day | solver luck-adj |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 34 | +0.790 | 5 | 0.979 | +0.752 | +0.700 | 6 | +0.663 |
| 37 | +0.700 | 6 | 0.981 | +0.668 | +0.770 | 5 | +0.635 |

- **G1 extension provenance (`f9fb7a4a` / PR 60):** `2` valid episodes completed (`seeds=[34, 37]`, raw `101% [91%, 113%]` / `101.4% [90.9%, 112.9%]`, luck-adjusted `109% [105%, 114%]` / `109.4% [105.1%, 113.6%]`) before early stop at `03:22` Helsinki to preserve shared carbon quota for the judge rehearsal; `31`/`31` excluded attempts hit `infra:provider_quota` (`meta.json` git SHA `f9fb7a4a`). Per commit d4bc4f3d, PR 51's 5-seed opencode-gemini-4-carbon hard shard on origin/fr8/canary/frontier was intentionally not brought into justSilas because it overlapped this pre-registered G1 seeds 30-59 extension.
- **Secondary pooled sensitivity (`n=32`, `seeds 0-29 + [34, 37]`):** `+0.349 +/- 0.190` vs solver `+0.514` (vs `+0.498 +/- 0.156` across all 30 seeds `30-59`), raw `68% [32%, 100%]` (`67.9% [31.7%, 99.7%]`), paired diff `-0.165 +/- 0.182` (bootstrap 95% CI `[-0.358, -0.002]`), luck-adjusted `75% [56%, 93%]` (`75.0% [55.8%, 93.5%]`). Cross-check against `paired_table_{ext30to59,pooled0to59}.json`: `checked=True`, `ext_match=True`, `pooled_match=True`, `solver30to59_match=True`. Per the post-hoc seed lock (`671ed96`) and pre-registered extension rule (`f9fb7a4a`), `primary_0_29` (`n=30`) remains the sole headline.

### Reference Baselines on Hard Seeds `30-59` (`n=30` Each, Post-PR16 Verification)

- Post-PR16 zero-reward invariants on `30-59`: `stop_early == 0.0` (`all_zero=True`, `mean=+0.000`), `do_nothing == 0.0` (`all_zero=True`, `mean=+0.000`).

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `solver` | 30 | +0.498 +/- 0.156 | 100% | 0.000 | 0.90 | 0.97 | 8.4 | 0.96 | +0.542 | 100% | 0/30 (0%) | -0.044 |
| hard | `grok_tactics` | 30 | +0.314 +/- 0.126 | 63.1% [34.5%, 106.2%] | -0.184 [-0.373, +0.022] | 0.83 | 0.87 | 11.1 | 0.97 | +0.321 | 59.2% [44.4%, 75.3%] | 0/30 (0%) | -0.006 |
| hard | `heuristic` | 30 | +0.118 +/- 0.163 | 23.6% [-11.0%, 59.9%] | -0.380 [-0.602, -0.153] | 0.87 | 1.00 | 15.6 | 0.82 | +0.062 | 11.4% [-12.9%, 32.3%] | 6/30 (20%) | +0.056 |
| hard | `logs_only` | 30 | -0.942 +/- 0.114 | -189.1% [-291.5%, -140.9%] | -1.440 [-1.599, -1.243] | 0.03 | 1.00 | 10.0 | 0.01 | -0.983 | -181.4% [-206.2%, -163.9%] | 30/30 (100%) | +0.041 |
| hard | `random` | 30 | -0.833 +/- 0.136 | -167.3% [-250.3%, -126.5%] | -1.331 [-1.531, -1.089] | 0.00 | 0.83 | 6.2 | 0.03 | -0.791 | -146.0% [-175.7%, -118.1%] | 25/30 (83%) | -0.042 |
| hard | `restrict_all` | 30 | -1.000 +/- 0.000 | -200.8% [-306.1%, -158.7%] | -1.498 [-1.630, -1.327] | 0.00 | 1.00 | 9.0 | 0.01 | -0.993 | -183.3% [-208.4%, -165.8%] | 30/30 (100%) | -0.007 |
| hard | `guess_day1` | 30 | -1.000 +/- 0.000 | -200.8% [-306.1%, -158.7%] | -1.498 [-1.630, -1.327] | 0.00 | 1.00 | 1.0 | 0.03 | -0.950 | -175.3% [-199.1%, -158.6%] | 30/30 (100%) | -0.050 |
| hard | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.498 [-0.630, -0.327] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.498 [-0.630, -0.327] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
