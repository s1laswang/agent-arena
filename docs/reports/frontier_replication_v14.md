# Canary v1.4 Frontier Replication and Cross-Model Capability Report

Every figure in this report is deterministically computed from replay-verified episodes by `scripts/verify_frontier_replication.py` using `canary.analysis.gap` (`load_runs`, `mean_ci`) and `scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), with zero live API calls.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/verify_frontier_replication.py --check
```

## 1. Pre-Registered Seed Rule and Replay Audit

- **Pre-registered seed rule (`docs/reports/gap.md`, commit `671ed96`):** The `justSilas` committed dev set (`seeds 0-29`, `n=30` per tier in `data/runs/committed/v1.4/`) is the locked **PRIMARY** headline result. All subsequent episodes under `results/frontier_replication/v1.4/` are evaluated and reported strictly separately as replication or cross-model cohorts, never swapped into `data/runs/committed/v1.4/`.
- **Replay verification (`scripts/verify_replay.py`):** `410/410` episodes verified in `data/runs/committed/v1.4/` and `304/304` episodes verified in `results/frontier_replication/v1.4/` (`5` `opencode:google/gemini-4-carbon` hard, `29` `opencode:google/gemini-3.5-flash` medium, and `270` reference solver and baseline episodes on hard `seeds 30-59`), with `0` mismatches and `0` duplicate `(agent, tier, seed)` entries.
- **Headline summary:**
  - **Primary `0-29` (`n=30`, locked headline):** `opencode:google/gemini-4-carbon` on hard scores `0.322 +/- 0.199` vs solver `0.499`, giving **65% [24%, 98%]** raw and **72% [52%, 91%]** luck-adjusted; on medium (`n=30`) it reaches `111% [99%, 127%]` raw and `101% [85%, 119%]` luck-adjusted.
  - **Replication hard (`seeds 30, 34, 42, 45, 57`, `n=5`, separate cohort):** `opencode:google/gemini-4-carbon` scores `0.656 +/- 0.110` (5/5 correct, mean `P(accused) = 0.89`, luck-adjusted `0.472`) vs solver `0.248` raw (luck-adjusted `0.430`, ratio `110% [58%, 179%]`).
  - **Secondary pooled sensitivity (`n=35`, secondary per pre-registered rule):** Pooling primary `0-29` with replication `30, 34, 42, 45, 57` yields `80% [42%, 124%]` raw and **77% [58%, 96%]** luck-adjusted, where the luck-adjusted 95% CI `[58%, 96%]` continues to exclude parity.
  - **Cross-model ordering (`gemini-4-carbon` vs `gemini-3.5-flash` vs `grok_tactics` vs `solver`):** On medium (`n=29` shared seeds `0-27, 29`), `opencode:google/gemini-3.5-flash` drops to `66% [26%, 104%]` raw / `74% [42%, 106%]` luck-adjusted (`gemini-4-carbon - gemini-3.5-flash = +0.289 +/- 0.238` V raw, `+0.174 +/- 0.192` V luck-adjusted). On hard (`n=30`, `0-29`), `gemini-3.5-flash`'s raw `75% [36%, 123%]` reflects 7 lucky sub-break-even guesses (mean `P(accused) = 0.71`); its luck-adjusted ratio falls to **22% [-23%, 63%]** (`gemini-4-carbon - gemini-3.5-flash = +0.250 +/- 0.221` V/episode).

## 2. Primary Committed v1.4 Cohort (Seeds 0-29, Locked Headline)

Exact reproduction of `data/runs/committed/v1.4/` (`scripts/paired_gemini.py --version v1.4 --seeds 0-29` and `docs/reports/gap.md`):

| tier | run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.713 +/- 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | 0.652 | **101% [85%, 119%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.579 +/- 0.110 | 0.80 | 0.80 | 7.7 | 0.99 | 0.645 | 90% [71%, 109%] | -0.066 +/- 0.124 | 0.558 | **86% [68%, 106%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.530 +/- 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | 0.645 | 82% [56%, 108%] | -0.115 +/- 0.170 | 0.479 | **74% [52%, 99%]** |
| medium | reference solver | 30 | 0.645 +/- 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | 0.645 | n/a | n/a | 0.645 | n/a |
| medium | heuristic | 20 | -0.275 +/- 0.361 | 0.45 | 1.00 | 11.3 | 0.62 | 0.717 | -38% [-86%, 8%] | -0.991 +/- 0.369 | -0.018 | **-3% [-33%, 28%]** |
| medium | do_nothing | 20 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.717 | 0% [0%, 0%] | -0.717 +/- 0.052 | 0.000 | **0% [0%, 0%]** |
| medium | stop_early | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.05 | 0.717 | -139% [-151%, -131%] | -1.717 +/- 0.052 | -0.900 | **-126% [-136%, -118%]** |
| medium | random | 20 | -0.678 +/- 0.225 | 0.05 | 0.75 | 6.5 | 0.08 | 0.717 | -95% [-127%, -62%] | -1.395 +/- 0.221 | -0.651 | **-91% [-118%, -63%]** |
| medium | restrict_all | 20 | -0.950 +/- 0.098 | 0.05 | 1.00 | 7.0 | 0.05 | 0.717 | -132% [-149%, -114%] | -1.667 +/- 0.104 | -0.948 | **-132% [-144%, -123%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | 0.360 | **72% [52%, 91%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.279 +/- 0.180 | 0.70 | 0.80 | 13.2 | 0.87 | 0.499 | 56% [19%, 87%] | -0.220 +/- 0.174 | 0.277 | **55% [34%, 77%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | 0.421 | **84% [65%, 106%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family; modelVersion gemini-3.6-flash) | 30 | 0.373 +/- 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | 0.499 | 75% [36%, 123%] | -0.126 +/- 0.221 | 0.110 | **22% [-23%, 63%]** |
| hard | reference solver | 30 | 0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | n/a | n/a | 0.499 | n/a |
| hard | heuristic | 20 | 0.186 +/- 0.233 | 0.85 | 1.00 | 13.9 | 0.79 | 0.464 | 40% [-12%, 108%] | -0.279 +/- 0.317 | 0.095 | **19% [-19%, 54%]** |
| hard | do_nothing | 20 | 0.000 +/- 0.000 | 0.00 | 0.00 | 0.0 | n/a | 0.464 | 0% [0%, 0%] | -0.464 +/- 0.171 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.464 | -215% [-360%, -167%] | -1.464 +/- 0.171 | -0.950 | **-192% [-231%, -166%]** |
| hard | random | 20 | -0.850 +/- 0.161 | 0.00 | 0.85 | 8.1 | 0.02 | 0.464 | -183% [-313%, -129%] | -1.315 +/- 0.232 | -0.824 | **-166% [-209%, -129%]** |
| hard | restrict_all | 20 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | 0.464 | -215% [-360%, -167%] | -1.464 +/- 0.171 | -0.993 | **-201% [-241%, -173%]** |

Note on `stop_early` provenance: the `data/runs/committed/v1.4/reference/stop_early-*` episodes (`seeds 0-19`) were recorded under the earlier day-1 random accusation baseline (now named `guess_day1`), whereas current `stop_early` (`StopEarlyQuit` in `canary/baselines.py`, used in `seeds 30-59` below) stops on day 1 without accusing and scores `0.000`.

## 3. Cohort (a): gemini-4-carbon Hard Replication (Seeds 30, 34, 42, 45, 57) and Seeds 30-59 Baselines

### 3.1 Paired 5-Seed Hard Replication Cohort (`seeds 30, 34, 42, 45, 57`, `n=5`)

Five completed `opencode:google/gemini-4-carbon` episodes in `results/frontier_replication/v1.4/opencode-gemini-4-carbon/` (25 seeds in `30-59` remain pending), paired on the exact same 5 seeds against `results/frontier_replication/v1.4/reference/solver-hard-seeds30to59` and all 8 non-solver baselines:

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
| 57 | +0.760 | True | 8 | 0.970 | +0.707 | +0.540 | True | 8 | 0.899 | +0.384 | +0.170 | +0.089 |

### 3.2 Full Hard Extension Reference and Baselines (`seeds 30-59`, `n=30`)

Across the full 30-seed extension block (`results/frontier_replication/v1.4/reference/*-hard-seeds30to59`), the reference solver averages `0.498 +/- 0.156` (`0.542` luck-adjusted), matching its `0-29` mean (`0.499 +/- 0.119`), while all 8 non-solver baselines remain well below solver parity on luck-adjusted value:

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

## 4. Cohort (b): Secondary Pooled Hard Sensitivity Row (`n=35`)

**SECONDARY SENSITIVITY ONLY (NOT THE HEADLINE):** Per the pre-registered seed rule (`docs/reports/gap.md`), the `n=30` (`seeds 0-29`) result remains the primary headline (`65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted). Pooling the 30 primary episodes with the 5 non-overlapping replication episodes (`seeds 30, 34, 42, 45, 57`, total `n=35`) provides a secondary sensitivity check:

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + 30,34,42,45,57 replication) | 35 | 0.370 +/- 0.175 | 0.86 | 0.97 | 12.9 | 0.88 | 0.463 | 80% [42%, 124%] | -0.093 +/- 0.193 | 0.376 | **77% [58%, 96%]** |
| reference solver (same 35 seeds) | 35 | 0.463 +/- 0.133 | 0.94 | 1.00 | 10.6 | 0.96 | 0.463 | n/a | n/a | 0.489 | n/a |

## 5. Cohort (c): gemini-3.5-flash Medium (`n=29`) + Hard (`n=30`) and Cross-Model Capability Ordering

### 5.1 Cross-Model Capability Ordering on Medium (`seeds 0-27, 29`, `n=29` Shared Seeds)

`results/frontier_replication/v1.4/opencode-gemini-3.5-flash` contains `29` replay-verified medium episodes (`seeds 0-27, 29`; missing seeds in `0-29`: `[28]`). Pairing all agents on those exact `29` seeds against `data/runs/committed/v1.4/reference/solver-medium*` (with deterministic `GrokTactics` included for baseline context; on full `0-29` `grok_tactics` scores `0.460 +/- 0.123`, `71% [51%, 95%]`):

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| OpenCode + gemini-4-carbon over MCP (shared 29 seeds) | 29 | 0.713 +/- 0.043 | 1.00 | 1.00 | 7.9 | 0.96 | 0.640 | 111% [99%, 129%] | +0.073 +/- 0.083 | 0.650 | **101% [85%, 120%]** |
| reference solver (shared 29 seeds) | 29 | 0.640 +/- 0.090 | 0.90 | 0.90 | 7.6 | 1.00 | 0.640 | n/a | n/a | 0.640 | n/a |
| in-process gemini-4-carbon (shared 29 seeds) | 29 | 0.523 +/- 0.142 | 0.83 | 0.86 | 9.1 | 0.93 | 0.640 | 82% [55%, 108%] | -0.118 +/- 0.176 | 0.470 | **73% [50%, 100%]** |
| grok_tactics (deterministic scripted policy, shared 29 seeds) | 29 | 0.458 +/- 0.128 | 0.69 | 0.69 | 7.6 | 1.00 | 0.640 | 72% [51%, 96%] | -0.182 +/- 0.158 | 0.458 | **72% [51%, 96%]** |
| OpenCode + gemini-3.5-flash over MCP (seeds 0-27, 29; seed 28 pending) | 29 | 0.424 +/- 0.243 | 0.83 | 1.00 | 9.1 | 0.86 | 0.640 | 66% [26%, 104%] | -0.217 +/- 0.259 | 0.476 | **74% [42%, 106%]** |

### 5.2 Cross-Model Capability Ordering on Hard (`seeds 0-29`, `n=30` Shared Seeds)

Pairing `solver`, `gemini-4-carbon` (in-process and OpenCode over MCP), `grok_tactics` (deterministic policy), and `gemini-3.5-flash` (OpenCode over MCP) on the exact same 30 hard seeds (`0-29`):

| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver [95% CI] |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| reference solver (seeds 0-29) | 30 | 0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | n/a | n/a | 0.499 | n/a |
| in-process gemini-4-carbon (seeds 0-29) | 30 | 0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | 0.421 | **84% [65%, 106%]** |
| grok_tactics (deterministic scripted policy, seeds 0-29) | 30 | 0.432 +/- 0.085 | 0.93 | 0.93 | 10.4 | 0.96 | 0.499 | 87% [67%, 119%] | -0.067 +/- 0.135 | 0.384 | **77% [61%, 95%]** |
| OpenCode + gemini-4-carbon over MCP (primary seeds 0-29) | 30 | 0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | 0.360 | **72% [52%, 91%]** |
| OpenCode + gemini-3.5-flash over MCP (seeds 0-29) | 30 | 0.373 +/- 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | 0.499 | 75% [36%, 123%] | -0.126 +/- 0.221 | 0.110 | **22% [-23%, 63%]** |

### 5.3 Direct Paired Model Comparison (`opencode:google/gemini-4-carbon` minus `opencode:google/gemini-3.5-flash`)

| tier | shared seeds (n) | gemini-4-carbon raw | gemini-3.5-flash raw | paired raw diff +/- 95% CI | gemini-4-carbon luck-adj. | gemini-3.5-flash luck-adj. | paired luck-adj. diff +/- 95% CI |
|---|---:|---:|---:|---|---:|---:|---|
| medium | 29 (`0-27, 29`) | 0.713 | 0.424 | **+0.289 +/- 0.238** | 0.650 | 0.476 | **+0.174 +/- 0.192** |
| hard | 30 (`0-29`) | 0.322 | 0.373 | -0.051 +/- 0.239 | 0.360 | 0.110 | **+0.250 +/- 0.221** |

Key takeaway on capability ordering (`solver` > `gemini-4-carbon` / `grok_tactics` > `gemini-3.5-flash` > `heuristic` > `do_nothing` / `stop_early`):
- On **medium**, `gemini-4-carbon` solves `29/29` shared seeds at high posterior confidence (`mean P(accused) = 0.96`, `101%` luck-adjusted of solver), outperforming both `grok_tactics` (`72%` luck-adjusted, `31%` abstention when scripted narrowing stalls) and `gemini-3.5-flash` (`74%` luck-adjusted, accuracy `0.83`, `+0.289 +/- 0.238` raw V/episode in favor of `gemini-4-carbon`).
- On **hard**, `gemini-3.5-flash` commits on weak evidence (`mean P(accused) = 0.71` vs `gemini-4-carbon`'s `0.88` and `solver`'s `0.97`). Lucky low-posterior guesses lift its raw score (`0.373`), but posterior-expected scoring exposes a decision-quality drop to `0.110` (`22% [-23%, 63%]` of solver), trailing `gemini-4-carbon` (`0.360`, `72% [52%, 91%]`) by `+0.250 +/- 0.221` luck-adjusted V per episode while `gemini-4-carbon` itself remains significantly below the Bayesian reference `solver` (`0.499`).
