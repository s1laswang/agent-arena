# Canary v1.4 Frontier Replication and Cross-Model Capability Report

Every figure in this report is deterministically computed from replay-verified episodes by `scripts/verify_frontier_replication.py` using `canary.analysis.gap` (`load_runs`, `mean_ci`) and `scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), with zero live API calls and zero runtime `.git` calls.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/verify_frontier_replication.py --check
```

## 1. Post-Hoc Seed Lock, Pre-Registered Extensions, and Replay Audit

- **Post-hoc seed lock and pre-registered extensions (`docs/reports/gap.md`, commits `8fd4dec`, `671ed96`, `f9fb7a4a`, `cf394894`, `eb9dee54`):** The `justSilas` committed dev set (`seeds 0-29`, `n=30` per tier in `data/runs/committed/v1.4/`) is the locked **PRIMARY** headline result (`671ed96` came 28 s after `8fd4dec`, so it is a post-hoc lock against later reruns and cherry-picking, not a pre-registration). By contrast, the G1 `opencode-gemini-4-carbon-ext` hard extension (`seeds 34, 37`, `n=2` completed before early quota stop, pre-registered in `f9fb7a4a`) and the second frontier family `gpt-5.5` (`v1.4` hard `seeds 0-29`, OpenCode `1.19.5`, pre-registered in `cf394894`, `30` committed v1.4 episodes at `58716742`) were pre-registered before any episode launched. All FR8 episodes under `results/frontier_replication/v1.4/` are evaluated separately; when G1 and FR8 `30-59` hard runs are reconciled into the deduplicated 6-seed union (`seeds 30, 34, 37, 42, 45, 57`, `n=6`), shared seed `34` deterministically uses committed `opencode-gemini-4-carbon-ext` (`eb9dee54`, never double-counting a repeated `(tier, seed)`).
- **Replay verification (`scripts/verify_replay.py`, commit `1bc3e281` compatibility) and solver `30-59` parity:** `472/472` episodes verified in `data/runs/committed/v1.4/` (`60` primary OpenCode carbon, `2` G1 carbon-ext, `60` in-process carbon, `30` OpenCode flash hard, `90` solver, `230` baselines) and `305/305` episodes verified in `results/frontier_replication/v1.4/` (`5` OpenCode carbon hard, `30` OpenCode flash medium, `270` reference solver and baselines on hard `seeds 30-59`), with `0` mismatches and `0` intra-cohort duplicates across all `777` episodes (including `521` committed and `348` replication pre-`1bc3e281` tool-error steps recorded before `data.detail` was added). Furthermore, `solver-hard-seeds30to59` matches `30/30` (`0` mismatches on `score`, `accused`, `correct`, and `final_day`) between `data/runs/committed/v1.4/reference/` and `results/frontier_replication/v1.4/reference/`.
- **Headline and reconciled extension summary:**
  - **Primary `0-29` (`n=30`, locked headline):** `opencode:google/gemini-4-carbon` on hard scores `0.322 +/- 0.199` vs solver `0.499`, giving **65% [24%, 98%]** raw and **72% [52%, 91%]** luck-adjusted; on medium (`n=30`) it reaches `111% [99%, 127%]` raw and `101% [85%, 119%]` luck-adjusted.
  - **Reconciled `30-59` hard extensions (`n=2` G1, `n=5` FR8, `n=6` deduplicated union, separate cohorts):** Committed G1 (`seeds 34, 37`, `n=2`) scores `0.745 +/- 0.088` vs solver `0.735` (`101% [91%, 113%]` raw, `109% [105%, 114%]` luck-adjusted); FR8 replication (`seeds 30, 34, 42, 45, 57`, `n=5`) scores `0.656 +/- 0.110` (5/5 correct, luck-adjusted `0.472`) vs solver `0.248` raw (`110% [58%, 179%]` luck-adjusted); and the deduplicated 6-seed union (`seeds 30, 34, 37, 42, 45, 57`, `n=6`, committed G1 on shared seed `34`) scores `0.658 +/- 0.085` vs solver `0.335` (`197% [104%, 2141%]` raw, `129% [109%, 162%]` luck-adjusted; FR8 seed-34 tie-break: `109% [66%, 160%]`).
  - **Secondary pooled hard sensitivity (`n=32`, `n=35`, `n=36`, secondary under post-hoc seed lock `671ed96`):** Pooling primary `0-29` with G1 (`n=32`, matching `README.md` / `docs/reports/gap.md`) gives `68% [32%, 100%]` raw and **75% [56%, 93%]** luck-adjusted; pooling with FR8 (`n=35`) gives `80% [42%, 124%]` raw and **77% [58%, 96%]** luck-adjusted; and pooling with the deduplicated 6-seed union (`n=36`, `0` duplicate seeds) gives `80% [44%, 122%]` raw and **81% [62%, 99%]** luck-adjusted (`post_expected_hi = 0.987 < 1.000`; FR8 seed-34 tie-break: `78% [59%, 96%]`). Across all secondary pooled sets (`n=32`, `n=35`, `n=36`), the luck-adjusted 95% CI continues to exclude parity.
  - **Cross-model replication (`gemini-3.5-flash` medium `n=30`, separate FR8 replication cohort):** On medium (`n=30` shared seeds `0-29`), `opencode:google/gemini-3.5-flash` reaches `67% [29%, 103%]` raw / `75% [45%, 105%]` luck-adjusted (`gemini-4-carbon - gemini-3.5-flash = +0.279 +/- 0.231` V raw, `+0.167 +/- 0.186` V luck-adjusted). `docs/reports/gap.md` is the sole source for primary `hard` (`0-29`) gap rows; `opencode:google/gemini-3.5-flash` hard is replay-verified in `committed_v14` (`472/472`) and omitted from tables here until `docs/reports/gap.md` ships it.

## 2. Primary Committed v1.4 Cohort (Seeds 0-29, Locked Headline)

Exact reproduction of `docs/reports/gap.md` rows in `data/runs/committed/v1.4/` (`scripts/paired_gemini.py --version v1.4 --seeds 0-29`; solver `0-29` spans `solver-*-20261114-121126` for `0-19` plus `solver-*-seeds20to29` for `20-29`):

| tier | run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.713 +/- 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | 0.652 | **101% [85%, 119%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.579 +/- 0.110 | 0.80 | 0.80 | 7.7 | 0.99 | 0.645 | 90% [71%, 109%] | -0.066 +/- 0.124 | 0.558 | **86% [68%, 106%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.530 +/- 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | 0.645 | 82% [56%, 108%] | -0.115 +/- 0.170 | 0.479 | **74% [52%, 99%]** |
| medium | reference solver | 30 | 0.645 +/- 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | 0.645 | n/a | n/a | 0.645 | n/a |
| medium | heuristic | 20 | -0.275 +/- 0.361 | 0.45 | 1.00 | 11.3 | 0.62 | 0.717 | -38% [-86%, 8%] | -0.991 +/- 0.369 | -0.018 | **-3% [-33%, 28%]** |
| medium | do_nothing | 20 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.717 | 0% [0%, 0%] | -0.717 +/- 0.052 | 0.000 | **0% [0%, 0%]** |
| medium | day-1 guess (recorded under the pre-2bb6729 name stop_early; today's stop_early stops without accusing and scores 0, see results/judge_table.md) | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.05 | 0.717 | -139% [-151%, -131%] | -1.717 +/- 0.052 | -0.900 | **-126% [-136%, -118%]** |
| medium | random | 20 | -0.678 +/- 0.225 | 0.05 | 0.75 | 6.5 | 0.08 | 0.717 | -95% [-127%, -62%] | -1.395 +/- 0.221 | -0.651 | **-91% [-118%, -63%]** |
| medium | restrict_all | 20 | -0.950 +/- 0.098 | 0.05 | 1.00 | 7.0 | 0.05 | 0.717 | -132% [-149%, -114%] | -1.667 +/- 0.104 | -0.948 | **-132% [-144%, -123%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | 0.360 | **72% [52%, 91%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.279 +/- 0.180 | 0.70 | 0.80 | 13.2 | 0.87 | 0.499 | 56% [19%, 87%] | -0.220 +/- 0.174 | 0.277 | **55% [34%, 77%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | 0.421 | **84% [65%, 106%]** |
| hard | OpenCode + gpt-5.5 over MCP (second frontier family, OpenAI; pre-registered at cf394894; episodes where the agent announced an accusation but never called accuse score 0 and are valid) | 30 | 0.504 +/- 0.064 | 0.93 | 0.93 | 10.2 | 0.94 | 0.499 | 101% [79%, 140%] | +0.005 +/- 0.141 | 0.418 | **84% [67%, 103%]** |
| hard | reference solver | 30 | 0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | n/a | n/a | 0.499 | n/a |
| hard | heuristic | 20 | 0.186 +/- 0.233 | 0.85 | 1.00 | 13.9 | 0.79 | 0.464 | 40% [-12%, 108%] | -0.279 +/- 0.317 | 0.095 | **19% [-19%, 54%]** |
| hard | do_nothing | 20 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.464 | 0% [0%, 0%] | -0.464 +/- 0.171 | 0.000 | **0% [0%, 0%]** |
| hard | day-1 guess (recorded under the pre-2bb6729 name stop_early; today's stop_early stops without accusing and scores 0, see results/judge_table.md) | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.464 | -215% [-360%, -167%] | -1.464 +/- 0.171 | -0.950 | **-192% [-231%, -166%]** |
| hard | random | 20 | -0.850 +/- 0.161 | 0.00 | 0.85 | 8.1 | 0.02 | 0.464 | -183% [-313%, -129%] | -1.315 +/- 0.232 | -0.824 | **-166% [-209%, -129%]** |
| hard | restrict_all | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | 0.464 | -215% [-360%, -167%] | -1.464 +/- 0.171 | -0.993 | **-201% [-241%, -173%]** |

Note on `stop_early` provenance: the `data/runs/committed/v1.4/reference/stop_early-*` episodes (`seeds 0-19`) were recorded under the earlier day-1 random accusation baseline (now named `guess_day1`), whereas current `stop_early` (`StopEarlyQuit` in `canary/baselines.py`, used in `seeds 30-59` below) stops on day 1 without accusing and scores `0.000`.

## 3. Cohort (a): Reconciled Seeds 30-59 Hard Extensions (G1 n=2, FR8 n=5, Deduplicated Union n=6) and Baselines

### 3.1 Committed G1 Partial Hard Extension (`seeds 34, 37`, `n=2`, Pre-Registered in `f9fb7a4a`)

`2` valid episodes completed in `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` before the run was stopped early to preserve shared carbon quota for the Harbor rehearsal (28 seeds in `30-59` stopped on `infra:provider_quota`), paired on `[34, 37]` against `data/runs/committed/v1.4/reference/solver-hard-seeds30to59`:

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59) | 2 | 0.745 +/- 0.088 | 1.00 | 1.00 | 5.5 | 0.98 | 0.735 | 101% [91%, 113%] | +0.010 +/- 0.157 | 0.710 | **109% [105%, 114%]** |
| reference solver (same 2 seeds) | 2 | 0.735 +/- 0.069 | 1.00 | 1.00 | 5.5 | 0.95 | 0.735 | n/a | n/a | 0.649 | n/a |

### 3.2 FR8 Hard Replication Cohort (`seeds 30, 34, 42, 45, 57`, `n=5`)

`5` completed `opencode:google/gemini-4-carbon` episodes in `results/frontier_replication/v1.4/opencode-gemini-4-carbon/` (25 seeds in `30-59` remain pending in FR8), paired on the exact same 5 seeds against `results/frontier_replication/v1.4/reference/solver-hard-seeds30to59` and all 8 non-solver baselines:

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP (replication seeds 30, 34, 42, 45, 57) | 5 | 0.656 +/- 0.110 | 1.00 | 1.00 | 11.0 | 0.89 | 0.248 | 265% [115%, 304%] | +0.408 +/- 0.557 | 0.472 | **110% [58%, 179%]** |
| reference solver (same 5 seeds) | 5 | 0.248 +/- 0.616 | 0.80 | 1.00 | 10.6 | 0.94 | 0.248 | n/a | n/a | 0.430 | n/a |
| grok_tactics (same 5 seeds) | 5 | 0.170 +/- 0.190 | 0.60 | 0.60 | 11.0 | 0.96 | 0.248 | 69% [10%, 136%] | -0.078 +/- 0.576 | 0.141 | **33% [4%, 82%]** |
| heuristic (same 5 seeds) | 5 | -0.034 +/- 0.479 | 0.80 | 1.00 | 17.4 | 0.68 | 0.248 | -14% [-216%, 89%] | -0.282 +/- 0.828 | -0.174 | **-41% [-165%, 38%]** |
| do_nothing (same 5 seeds) | 5 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.248 | 0% [0%, 0%] | -0.248 +/- 0.616 | 0.000 | **0% [0%, 0%]** |
| stop_early (same 5 seeds) | 5 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.248 | 0% [0%, 0%] | -0.248 +/- 0.616 | 0.000 | **0% [0%, 0%]** |
| random (same 5 seeds) | 5 | -0.800 +/- 0.392 | 0.00 | 0.80 | 6.8 | 0.01 | 0.248 | -323% [-396%, -160%] | -1.048 +/- 1.006 | -0.784 | **-182% [-231%, -124%]** |
| logs_only (same 5 seeds) | 5 | -0.650 +/- 0.686 | 0.20 | 1.00 | 10.0 | 0.01 | 0.248 | -262% [-495%, 16%] | -0.898 +/- 0.739 | -0.986 | **-229% [-351%, -171%]** |
| guess_day1 (same 5 seeds) | 5 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.248 | -403% [-495%, -160%] | -1.248 +/- 0.616 | -0.950 | **-221% [-335%, -167%]** |
| restrict_all (same 5 seeds) | 5 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | 0.248 | -403% [-495%, -160%] | -1.248 +/- 0.616 | -0.993 | **-231% [-352%, -175%]** |

Per-seed inspection on `[30, 34, 42, 45, 57]` explains why the raw 5-seed ratio (`265%`) is much higher than the luck-adjusted ratio (`110% [58%, 179%]`): on seed `30` the reference solver suffered a `-1.000` wrong accusation on day `18` (pulling the 5-seed raw solver mean down to `0.248`), while under posterior expectation the two agents are close (`0.472` vs `0.430`):

| seed | carbon score | carbon correct | carbon day | carbon P(accused) | carbon luck-adj. | solver score | solver correct | solver day | solver P(accused) | solver luck-adj. | grok_tactics score | grok_tactics luck-adj. |
|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 30 | +0.540 | True | 11 | 0.909 | +0.400 | -1.000 | False | 18 | 0.858 | +0.175 | +0.000 | +0.000 |
| 34 | +0.820 | True | 8 | 0.650 | +0.183 | +0.700 | True | 6 | 0.978 | +0.663 | +0.000 | +0.000 |
| 42 | +0.570 | True | 12 | 0.969 | +0.521 | +0.510 | True | 10 | 0.997 | +0.505 | +0.150 | +0.086 |
| 45 | +0.590 | True | 16 | 0.973 | +0.547 | +0.490 | True | 11 | 0.955 | +0.423 | +0.530 | +0.530 |
| 57 | +0.760 | True | 8 | 0.970 | +0.707 | +0.540 | True | 8 | 0.899 | +0.385 | +0.170 | +0.089 |

### 3.3 Deduplicated 6-Seed Hard Extension Union (`seeds 30, 34, 37, 42, 45, 57`, `n=6`, `eb9dee54`) and Seed-34 Comparison

Combining G1 (`seeds 34, 37`) and FR8 (`seeds 30, 34, 42, 45, 57`) covers `6` unique seeds in `30-59` (`30, 34, 37, 42, 45, 57`, with `24` seeds in `30-59` still unplayed). Seed `34` was played independently in both G1 and FR8; per `eb9dee54` (never double-count a repeated `(tier, seed)` when pooling), the canonical union deterministically selects the committed G1 episode (`1` duplicate episode dropped), with the FR8 tie-break shown alongside for sensitivity:

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP (deduplicated union seeds 30, 34, 37, 42, 45, 57; committed G1 on seed 34) | 6 | 0.658 +/- 0.085 | 1.00 | 1.00 | 9.7 | 0.96 | 0.335 | 197% [104%, 2141%] | +0.323 +/- 0.483 | 0.599 | **129% [109%, 162%]** |
| OpenCode + gemini-4-carbon over MCP (union sensitivity: FR8 tie-break on seed 34, seeds 30, 34, 37, 42, 45, 57) | 6 | 0.663 +/- 0.091 | 1.00 | 1.00 | 10.2 | 0.91 | 0.335 | 198% [104%, 2159%] | +0.328 +/- 0.481 | 0.504 | **109% [66%, 160%]** |
| reference solver (same 6 seeds) | 6 | 0.335 +/- 0.531 | 0.83 | 1.00 | 9.7 | 0.94 | 0.335 | n/a | n/a | 0.464 | n/a |
| grok_tactics (same 6 seeds) | 6 | 0.190 +/- 0.160 | 0.67 | 0.67 | 12.2 | 0.96 | 0.335 | 57% [18%, 640%] | -0.145 +/- 0.488 | 0.155 | **33% [7%, 73%]** |

Side-by-side reconciliation on shared seed `34` (true mole `e29`):

| cohort / run | source | score | correct | accused | final day | P(accused) | luck-adjusted score |
|---|---|---:|---|---|---:|---:|---:|
| Committed G1 (selected for union) | `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` | +0.790 | True | `e29` | 5 | 0.979 | +0.752 |
| FR8 replication (tie-break sensitivity) | `results/frontier_replication/v1.4/opencode-gemini-4-carbon/hard-s34` | +0.820 | True | `e29` | 8 | 0.650 | +0.183 |
| Reference solver | `data/runs/committed/v1.4/reference/solver-hard-seeds30to59` | +0.700 | True | `e29` | 6 | 0.978 | +0.663 |

Per-seed breakdown across all `6` unique seeds in the deduplicated `30-59` union:

| seed | union source | carbon score | carbon correct | carbon day | carbon P(accused) | carbon luck-adj. | solver score | solver correct | solver day | solver luck-adj. | grok_tactics score | grok_tactics luck-adj. |
|---:|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 30 | `fr8_replication` | +0.540 | True | 11 | 0.909 | +0.400 | -1.000 | False | 18 | +0.175 | +0.000 | +0.000 |
| 34 | `committed_g1` | +0.790 | True | 5 | 0.979 | +0.752 | +0.700 | True | 6 | +0.663 | +0.000 | +0.000 |
| 37 | `committed_g1` | +0.700 | True | 6 | 0.981 | +0.668 | +0.770 | True | 5 | +0.635 | +0.290 | +0.226 |
| 42 | `fr8_replication` | +0.570 | True | 12 | 0.969 | +0.521 | +0.510 | True | 10 | +0.505 | +0.150 | +0.086 |
| 45 | `fr8_replication` | +0.590 | True | 16 | 0.973 | +0.547 | +0.490 | True | 11 | +0.423 | +0.530 | +0.530 |
| 57 | `fr8_replication` | +0.760 | True | 8 | 0.970 | +0.707 | +0.540 | True | 8 | +0.385 | +0.170 | +0.089 |

### 3.4 Full Hard Extension Reference and Baselines (`seeds 30-59`, `n=30`) and Solver Parity (`30/30`)

Exact `30/30` per-seed parity (`score`, `accused`, `correct`, `final_day`) holds between `data/runs/committed/v1.4/reference/solver-hard-seeds30to59` and `results/frontier_replication/v1.4/reference/solver-hard-seeds30to59`. Across all 30 extension seeds (`30-59`), the reference solver averages `0.498 +/- 0.156` (`0.542` luck-adjusted), matching its `0-29` mean (`0.499 +/- 0.119`), while all 8 non-solver baselines remain well below solver parity on luck-adjusted value:

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| reference solver (seeds 30-59) | 30 | 0.498 +/- 0.156 | 0.90 | 0.97 | 8.4 | 0.96 | 0.498 | n/a | n/a | 0.542 | n/a |
| grok_tactics (seeds 30-59) | 30 | 0.314 +/- 0.126 | 0.83 | 0.87 | 11.1 | 0.97 | 0.498 | 63% [35%, 106%] | -0.184 +/- 0.199 | 0.321 | **59% [44%, 75%]** |
| heuristic (seeds 30-59) | 30 | 0.118 +/- 0.163 | 0.87 | 1.00 | 15.6 | 0.82 | 0.498 | 24% [-11%, 60%] | -0.380 +/- 0.227 | 0.062 | **11% [-13%, 32%]** |
| do_nothing (seeds 30-59) | 30 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | 0.000 | **0% [0%, 0%]** |
| stop_early (seeds 30-59) | 30 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | 0.000 | **0% [0%, 0%]** |
| random (seeds 30-59) | 30 | -0.833 +/- 0.136 | 0.00 | 0.83 | 6.2 | 0.03 | 0.498 | -167% [-250%, -127%] | -1.331 +/- 0.225 | -0.791 | **-146% [-176%, -118%]** |
| logs_only (seeds 30-59) | 30 | -0.942 +/- 0.114 | 0.03 | 1.00 | 10.0 | 0.01 | 0.498 | -189% [-292%, -141%] | -1.440 +/- 0.185 | -0.983 | **-181% [-206%, -164%]** |
| guess_day1 (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.950 | **-175% [-199%, -159%]** |
| restrict_all (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | 0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.993 | **-183% [-208%, -166%]** |

## 4. Cohort (b): Secondary Pooled Hard Sensitivity Reconciliation (`n=32`, `n=35`, `n=36`)

**SECONDARY SENSITIVITY ONLY (NOT THE HEADLINE):** Per the post-hoc seed lock (`docs/reports/gap.md`, commit `671ed96`), the `n=30` (`seeds 0-29`) result remains the primary headline (`65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted). Reconciling all non-overlapping pooled combinations with primary `0-29` (`n=32` with committed G1 `34, 37`, `n=35` with FR8 `30, 34, 42, 45, 57`, and `n=36` with the deduplicated 6-seed union `30, 34, 37, 42, 45, 57`, `0` duplicate seeds in every pool) shows that every luck-adjusted 95% CI continues to exclude parity (`post_expected_hi` = `0.935`, `0.959`, and `0.987`, all `< 1.000`):

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP, pooled (primary + extension) | 32 | 0.349 +/- 0.190 | 0.84 | 0.97 | 12.7 | 0.89 | 0.514 | 68% [32%, 100%] | -0.165 +/- 0.182 | 0.381 | **75% [56%, 93%]** |
| reference solver (same 32 seeds) | 32 | 0.514 +/- 0.114 | 0.97 | 1.00 | 10.3 | 0.96 | 0.514 | n/a | n/a | 0.509 | n/a |
| SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + 30, 34, 42, 45, 57 replication) | 35 | 0.370 +/- 0.175 | 0.86 | 0.97 | 12.9 | 0.88 | 0.463 | 80% [42%, 124%] | -0.093 +/- 0.193 | 0.376 | **77% [58%, 96%]** |
| reference solver (same 35 seeds) | 35 | 0.463 +/- 0.133 | 0.94 | 1.00 | 10.6 | 0.96 | 0.463 | n/a | n/a | 0.489 | n/a |
| SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + deduplicated union 30, 34, 37, 42, 45, 57; committed G1 seed 34) | 36 | 0.378 +/- 0.171 | 0.86 | 0.97 | 12.6 | 0.90 | 0.472 | 80% [44%, 122%] | -0.093 +/- 0.188 | 0.399 | **81% [62%, 99%]** |
| SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + union 30, 34, 37, 42, 45, 57; FR8 seed 34 tie-break) | 36 | 0.379 +/- 0.171 | 0.86 | 0.97 | 12.7 | 0.89 | 0.472 | 80% [44%, 122%] | -0.092 +/- 0.188 | 0.384 | **78% [59%, 96%]** |
| reference solver (same 36 seeds) | 36 | 0.472 +/- 0.130 | 0.94 | 1.00 | 10.4 | 0.96 | 0.472 | n/a | n/a | 0.493 | n/a |

## 5. Cohort (c): gemini-3.5-flash Medium Replication (`n=30`) and Capability Ordering

### 5.1 Cross-Model Capability Ordering on Medium (`seeds 0-29`, `n=30` Shared Seeds, FR8 Replication Cohort)

`results/frontier_replication/v1.4/opencode-gemini-3.5-flash` contains `30` replay-verified medium episodes (`seeds 0-29`; missing seeds in `0-29`: `[]`). Pairing all agents on those exact `30` seeds against `data/runs/committed/v1.4/reference/solver-medium*` (with deterministic `GrokTactics` included for baseline context; on full `0-29` `grok_tactics` scores `0.460 +/- 0.123`, `71% [51%, 95%]`):

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP (shared 30 seeds) | 30 | 0.713 +/- 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | 0.652 | **101% [85%, 119%]** |
| reference solver (shared 30 seeds) | 30 | 0.645 +/- 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | 0.645 | n/a | n/a | 0.645 | n/a |
| in-process gemini-4-carbon (shared 30 seeds) | 30 | 0.530 +/- 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | 0.645 | 82% [56%, 108%] | -0.115 +/- 0.170 | 0.479 | **74% [52%, 99%]** |
| grok_tactics (deterministic scripted policy, shared 30 seeds) | 30 | 0.460 +/- 0.123 | 0.70 | 0.70 | 7.7 | 1.00 | 0.645 | 71% [51%, 95%] | -0.185 +/- 0.152 | 0.460 | **71% [51%, 95%]** |
| OpenCode + gemini-3.5-flash over MCP (seeds 0-29, complete n=30) | 30 | 0.434 +/- 0.236 | 0.83 | 1.00 | 9.0 | 0.87 | 0.645 | 67% [29%, 103%] | -0.211 +/- 0.251 | 0.485 | **75% [45%, 105%]** |

### 5.2 Capability Ordering on Hard (`seeds 0-29`, `n=30` Shared Seeds)

Pairing `docs/reports/gap.md`-approved primary runs (`solver`, in-process `gemini-4-carbon`, OpenCode `gemini-4-carbon` over MCP) and deterministic `grok_tactics` on the exact same 30 hard seeds (`0-29`; `opencode:google/gemini-3.5-flash` hard is held pending `docs/reports/gap.md`):

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| reference solver (seeds 0-29) | 30 | 0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | n/a | n/a | 0.499 | n/a |
| in-process gemini-4-carbon (seeds 0-29) | 30 | 0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | 0.421 | **84% [65%, 106%]** |
| grok_tactics (deterministic scripted policy, seeds 0-29) | 30 | 0.432 +/- 0.085 | 0.93 | 0.93 | 10.4 | 0.96 | 0.499 | 87% [67%, 119%] | -0.067 +/- 0.135 | 0.384 | **77% [61%, 95%]** |
| OpenCode + gemini-4-carbon over MCP (primary seeds 0-29) | 30 | 0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | 0.360 | **72% [52%, 91%]** |

### 5.3 Direct Paired Model Comparison (`opencode:google/gemini-4-carbon` minus `opencode:google/gemini-3.5-flash`)

| tier | shared seeds (n) | gemini-4-carbon raw | gemini-3.5-flash raw | paired raw diff +/- 95% CI | gemini-4-carbon luck-adj. | gemini-3.5-flash luck-adj. | paired luck-adj. diff +/- 95% CI |
|---|---:|---:|---:|---|---:|---:|---|
| medium | 30 (`0-29`) | 0.713 | 0.434 | **+0.279 +/- 0.231** | 0.652 | 0.485 | **+0.167 +/- 0.186** |

Key takeaway on capability ordering:
- On **medium**, `gemini-4-carbon` solves `30/30` shared seeds at high posterior confidence (`mean P(accused) = 0.96`, `101%` luck-adjusted of solver), outperforming both `grok_tactics` (`71%` luck-adjusted, `30%` abstention when scripted narrowing stalls) and the FR8 `gemini-3.5-flash` medium replication cohort (`75%` luck-adjusted, accuracy `0.83`, `+0.279 +/- 0.231` raw V/episode in favor of `gemini-4-carbon`).
- On **hard**, `OpenCode + gemini-4-carbon over MCP` scores `0.322 +/- 0.199` raw (`65% [24%, 98%]`) and `0.360` luck-adjusted (`72% [52%, 91%]` of solver `0.499`), trailing both in-process `gemini-4-carbon` (`0.421`, `84% [65%, 106%]`) and deterministic `grok_tactics` (`0.384`, `77% [61%, 95%]`) while remaining significantly below the Bayesian reference `solver`.
