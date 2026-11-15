# Ladder Scale Analysis: Mole Susceptibility Across Gemma, Flash, and Gemini-4 Thinking Budgets

Generated offline with 0 API calls via `python -m canary.mole.ladder_miner --out docs/reports/mole_ladder_scale_analysis.md`. All vulnerability metrics are streamed directly from committed v1.4 ladder transcripts and replayed through `canary.solver.policy.SolverPolicy` and `canary.mole.counterfactual`.

## 1. Corpus Provenance and Headline Scaling Findings

- **Deduplicated ladder corpus**: **555** valid exported ladder episodes across **41** `(model, thinking_level, tier)` cells (297 Hard across 21 cells; 258 Medium across 20 cells) streamed from `results/gemini/scale/ladder30/ladder_episodes.jsonl.gz` (481 valid, +481 distinct), `results/gemini/ladder_episodes.jsonl.gz` (550 valid, +69 distinct), `results/gemini/ladder_gemma_episodes.jsonl.gz` (5 valid, +5 distinct). (Note: `results/gemini/ladder.md` reports 587 Gemini episodes by combining the 550 exported Gemini ladder episodes with 37 read-only imported `inproc-gemini-4-carbon` `default` episodes audited in `docs/reports/mole_transcript_mining.md`, plus the 5 hosted-Gemma episodes.)
- **Angry-decoy boundary (`flash-lite` vs all stronger models)**: `gemini-3.1-flash-lite` accuses the angry decoy in **15/80** episodes (81.2% dismissal rate), whereas across all stronger models (`gemma-4-31b-it`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon`) angry-decoy dismissal is **474/475 (99.8%)** (1 total decoy accusation). Naive `frame=decoy` only fools `flash-lite`; non-decoy peer framing is essential from Flash-3.6 and Gemma-31B upward.
- **Thinking shifts canary geometry from surgical `<=3` traps to `4-8` / `>=9` partitions**: On Hard, raising thinking from `low` to `high` drives `<=3`-recipient canary share to **0.0%** across `gemini-4` (`gemini-4-carbon`: 30.5% -> 0.0%; `gemini-4-argon`: 49.4% -> 0.0%), while `gemini-3.5-flash` (served `3.6-flash`) retains **37.8%** `<=3` surgical traps even at `high` thinking.
- **Thinking inflates low-LR interview share in Gemini-4 and delays canary start in 3.8-Flash/Argon**: On Hard, `interview` share of investigative calls jumps with thinking in `gemini-4-carbon` (20.9% at `low` -> 67.2% at `high`) and `gemini-4-argon` (11.8% -> 70.2%), while first-canary lag vs Day-1 Solver reaches **+3.43d** (`gemini-4-argon` `high`) and **+5.00d** (`gemini-3.8-flash` `high`).
- **Below-breakeven gambling scales down with capability and thinking**: `gemma-4-31b-it` (`default` Hard) makes **5/5 (100.0%)** accusations below `1/(1+E[true V])`, and `gemini-3.1-flash-lite` gambles below breakeven on **37/40 (92.5%)** Hard accusations, whereas `gemini-4-carbon` drops to **0/10 (0.0%)** at `low` and **2/10 (20.0%)** at `high`.
- **Counterfactual `frontier_synthesis_v14` vs `default_v0` (`hard`, 198 episodes across 21 cells)**: Across all **16/16** non-degenerate Gemini cells (`3.5-flash`, `3.8-flash`, `4-hydrogen`, `4-argon`, `4-carbon`), `frontier_synthesis_v14` reduces mean `P(true mole)` at accusation from **0.783** to **0.503** (drop **+0.280 +/- 0.066**) and reduces `optimal_EV` from **0.407** to **0.188** (drop **+0.219 +/- 0.051**).

## 2. Family-Level Vulnerability Scaling (Gemma -> Flash-Lite -> Flash -> Gemini-4)

| Family | Tier | n | Score +/- CI | Acc | Can/Ep | Rec <=3 | Rec 4-8 | Rec >=9 | 1st Can Day (Lag) | Interview% | Decoy Dismiss | Below-BE Acc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 31B (open-weight) | hard | 5 | -0.024 +/- 0.781 | 60.0% | 8.20 | 17.1% | 34.1% | 48.8% | 1.80 (+0.80d) | 11.0% | 100.0% | 5/5 (100.0%) |
| Gemini 3.1 Flash-Lite | hard | 40 | -0.731 +/- 0.201 | 15.0% | 2.90 | 53.4% | 24.1% | 22.4% | 2.24 (+1.24d) | 15.7% | 87.5% | 37/40 (92.5%) |
| Gemini 3.5/3.6 & 3.8 Flash | hard | 140 | +0.268 +/- 0.094 | 83.6% | 11.51 | 33.3% | 20.4% | 46.3% | 2.53 (+1.53d) | 2.8% | 99.3% | 42/139 (30.2%) |
| Gemini 4 (Hydrogen/Argon/Carbon) | hard | 112 | +0.397 +/- 0.093 | 89.3% | 8.54 | 22.0% | 40.2% | 37.7% | 2.89 (+1.89d) | 42.8% | 100.0% | 25/112 (22.3%) |
| Gemini 3.1 Flash-Lite | medium | 40 | -0.586 +/- 0.241 | 22.5% | 1.18 | 63.8% | 17.0% | 19.1% | 2.81 (+1.81d) | 17.8% | 75.0% | 38/40 (95.0%) |
| Gemini 3.5/3.6 & 3.8 Flash | medium | 100 | +0.435 +/- 0.120 | 85.0% | 6.24 | 49.2% | 27.1% | 23.7% | 2.27 (+1.27d) | 12.5% | 100.0% | 34/100 (34.0%) |
| Gemini 4 (Hydrogen/Argon/Carbon) | medium | 118 | +0.611 +/- 0.060 | 91.5% | 6.29 | 26.0% | 48.9% | 25.1% | 1.48 (+0.48d) | 51.9% | 100.0% | 21/111 (18.9%) |

## 3. Per-(Model, Thinking, Tier) Mole-Evasion Vulnerabilities (Hard Tier)

| Model | Thinking | n | Score +/- CI | Acc | Think Tok | Can/Ep | Rec <=3 | Rec 4-8 | Rec >=9 | 1st Can (Lag) | Interview% | Decoy Dismiss | Below-BE Acc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma-4-31b-it (hosted) | default | 5 | -0.024 +/- 0.781 | 60.0% | 16936 | 8.20 | 17.1% | 34.1% | 48.8% | 1.80 (+0.80d) | 11.0% | 100.0% | 5/5 (100.0%) |
| gemini-3.1-flash-lite | minimal | 10 | -1.000 +/- 0.000 | 0.0% | 0 | 1.80 | 88.9% | 0.0% | 11.1% | 3.33 (+2.33d) | 7.1% | 80.0% | 10/10 (100.0%) |
| gemini-3.1-flash-lite | low | 10 | -0.454 +/- 0.545 | 30.0% | 5543 | 3.70 | 27.0% | 27.0% | 45.9% | 1.50 (+0.50d) | 18.7% | 100.0% | 10/10 (100.0%) |
| gemini-3.1-flash-lite | medium | 10 | -1.000 +/- 0.000 | 0.0% | 1666 | 1.50 | 80.0% | 0.0% | 20.0% | 2.78 (+1.78d) | 17.4% | 80.0% | 10/10 (100.0%) |
| gemini-3.1-flash-lite | high | 10 | -0.471 +/- 0.528 | 30.0% | 5679 | 4.60 | 52.2% | 39.1% | 8.7% | 1.50 (+0.50d) | 17.6% | 90.0% | 7/10 (70.0%) |
| gemini-3.5-flash (served 3.6-flash) | minimal | 10 | -0.186 +/- 0.441 | 60.0% | 0 | 24.40 | 18.9% | 29.1% | 52.0% | 1.00 (+0.00d) | 0.4% | 100.0% | 4/10 (40.0%) |
| gemini-3.5-flash (served 3.6-flash) | low | 10 | +0.266 +/- 0.418 | 80.0% | 8531 | 11.40 | 43.9% | 11.4% | 44.7% | 1.20 (+0.20d) | 1.3% | 100.0% | 4/10 (40.0%) |
| gemini-3.5-flash (served 3.6-flash) | medium | 40 | +0.385 +/- 0.130 | 92.5% | 20276 | 12.40 | 34.5% | 12.5% | 53.0% | 1.43 (+0.43d) | 0.9% | 97.5% | 15/40 (37.5%) |
| gemini-3.5-flash (served 3.6-flash) | high | 40 | +0.390 +/- 0.152 | 90.0% | 26775 | 11.65 | 37.8% | 16.3% | 45.9% | 1.62 (+0.62d) | 3.3% | 100.0% | 10/40 (25.0%) |
| gemini-3.8-flash | low | 10 | +0.019 +/- 0.451 | 70.0% | 0 | 13.60 | 52.2% | 16.2% | 31.6% | 3.00 (+2.00d) | 0.0% | 100.0% | 2/10 (20.0%) |
| gemini-3.8-flash | medium | 10 | +0.079 +/- 0.466 | 70.0% | 28300 | 4.50 | 35.6% | 44.4% | 20.0% | 6.00 (+5.00d) | 6.3% | 100.0% | 2/10 (20.0%) |
| gemini-3.8-flash | high | 20 | +0.237 +/- 0.244 | 80.0% | 50732 | 5.50 | 5.5% | 59.1% | 35.5% | 6.00 (+5.00d) | 7.2% | 100.0% | 5/19 (26.3%) |
| gemini-4-hydrogen | low | 12 | +0.477 +/- 0.271 | 91.7% | 3537 | 5.92 | 14.1% | 36.6% | 49.3% | 1.83 (+0.83d) | 4.7% | 100.0% | 7/12 (58.3%) |
| gemini-4-hydrogen | medium | 10 | +0.525 +/- 0.091 | 100.0% | 16061 | 9.50 | 2.1% | 43.2% | 54.7% | 1.00 (+0.00d) | 22.6% | 100.0% | 3/10 (30.0%) |
| gemini-4-hydrogen | high | 9 | +0.394 +/- 0.351 | 88.9% | 34275 | 9.89 | 0.0% | 43.8% | 56.2% | 1.22 (+0.22d) | 37.9% | 100.0% | 0/9 (0.0%) |
| gemini-4-hydrogen | xhigh | 10 | +0.475 +/- 0.325 | 90.0% | 66948 | 8.30 | 0.0% | 30.1% | 69.9% | 1.60 (+0.60d) | 49.0% | 100.0% | 0/10 (0.0%) |
| gemini-4-argon | low | 18 | +0.205 +/- 0.311 | 77.8% | 11 | 9.44 | 49.4% | 33.5% | 17.1% | 3.83 (+2.83d) | 11.8% | 100.0% | 4/18 (22.2%) |
| gemini-4-argon | medium | 19 | +0.290 +/- 0.266 | 84.2% | 12074 | 7.26 | 46.4% | 32.6% | 21.0% | 5.00 (+4.00d) | 41.6% | 100.0% | 6/19 (31.6%) |
| gemini-4-argon | high | 14 | +0.373 +/- 0.311 | 85.7% | 42162 | 4.57 | 0.0% | 65.6% | 34.4% | 4.43 (+3.43d) | 70.2% | 100.0% | 3/14 (21.4%) |
| gemini-4-carbon | low | 10 | +0.463 +/- 0.092 | 100.0% | 289 | 16.70 | 30.5% | 43.7% | 25.7% | 1.90 (+0.90d) | 20.9% | 100.0% | 0/10 (0.0%) |
| gemini-4-carbon | high | 10 | +0.608 +/- 0.102 | 100.0% | 63171 | 8.00 | 0.0% | 46.3% | 53.7% | 2.00 (+1.00d) | 67.2% | 100.0% | 2/10 (20.0%) |

## 4. Per-(Model, Thinking, Tier) Mole-Evasion Vulnerabilities (Medium Tier)

| Model | Thinking | n | Score +/- CI | Acc | Think Tok | Can/Ep | Rec <=3 | Rec 4-8 | Rec >=9 | 1st Can (Lag) | Interview% | Decoy Dismiss | Below-BE Acc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 10 | -0.805 +/- 0.382 | 10.0% | 0 | 0.80 | 75.0% | 12.5% | 12.5% | 4.12 (+3.12d) | 11.5% | 70.0% | 10/10 (100.0%) |
| gemini-3.1-flash-lite | low | 10 | -0.243 +/- 0.606 | 40.0% | 4290 | 1.50 | 53.3% | 6.7% | 40.0% | 1.40 (+0.40d) | 22.2% | 80.0% | 8/10 (80.0%) |
| gemini-3.1-flash-lite | medium | 10 | -0.656 +/- 0.450 | 20.0% | 1686 | 1.00 | 60.0% | 30.0% | 10.0% | 3.44 (+2.44d) | 13.1% | 60.0% | 10/10 (100.0%) |
| gemini-3.1-flash-lite | high | 10 | -0.640 +/- 0.470 | 20.0% | 5544 | 1.40 | 71.4% | 21.4% | 7.1% | 2.60 (+1.60d) | 24.0% | 90.0% | 10/10 (100.0%) |
| gemini-3.5-flash (served 3.6-flash) | minimal | 10 | +0.532 +/- 0.340 | 90.0% | 0 | 7.60 | 47.4% | 18.4% | 34.2% | 1.00 (+0.00d) | 0.0% | 100.0% | 3/10 (30.0%) |
| gemini-3.5-flash (served 3.6-flash) | low | 10 | +0.021 +/- 0.547 | 60.0% | 7269 | 7.10 | 49.3% | 16.9% | 33.8% | 1.00 (+0.00d) | 13.2% | 100.0% | 5/10 (50.0%) |
| gemini-3.5-flash (served 3.6-flash) | medium | 20 | +0.635 +/- 0.177 | 95.0% | 15033 | 6.30 | 61.9% | 19.8% | 18.3% | 1.05 (+0.05d) | 14.6% | 100.0% | 4/20 (20.0%) |
| gemini-3.5-flash (served 3.6-flash) | high | 20 | +0.538 +/- 0.236 | 90.0% | 21513 | 7.05 | 60.3% | 15.6% | 24.1% | 1.05 (+0.05d) | 17.8% | 100.0% | 5/20 (25.0%) |
| gemini-3.8-flash | low | 10 | -0.012 +/- 0.529 | 60.0% | 0 | 7.60 | 44.7% | 18.4% | 36.8% | 1.50 (+0.50d) | 11.5% | 100.0% | 5/10 (50.0%) |
| gemini-3.8-flash | medium | 10 | +0.473 +/- 0.326 | 90.0% | 33837 | 5.00 | 40.0% | 58.0% | 2.0% | 5.60 (+4.60d) | 11.2% | 100.0% | 6/10 (60.0%) |
| gemini-3.8-flash | high | 20 | +0.496 +/- 0.229 | 90.0% | 45240 | 4.20 | 22.6% | 63.1% | 14.3% | 4.70 (+3.70d) | 10.5% | 100.0% | 6/20 (30.0%) |
| gemini-4-hydrogen | low | 13 | +0.575 +/- 0.184 | 76.9% | 2932 | 5.31 | 36.2% | 37.7% | 26.1% | 1.46 (+0.46d) | 12.0% | 100.0% | 5/10 (50.0%) |
| gemini-4-hydrogen | medium | 9 | +0.439 +/- 0.391 | 77.8% | 11352 | 6.11 | 20.0% | 43.6% | 36.4% | 1.44 (+0.44d) | 46.7% | 100.0% | 3/8 (37.5%) |
| gemini-4-hydrogen | high | 10 | +0.682 +/- 0.081 | 100.0% | 22876 | 7.00 | 0.0% | 65.7% | 34.3% | 1.10 (+0.10d) | 58.9% | 100.0% | 1/10 (10.0%) |
| gemini-4-hydrogen | xhigh | 10 | +0.642 +/- 0.151 | 90.0% | 61838 | 6.60 | 0.0% | 63.6% | 36.4% | 1.70 (+0.70d) | 54.1% | 100.0% | 1/9 (11.1%) |
| gemini-4-argon | low | 21 | +0.701 +/- 0.053 | 100.0% | 0 | 6.43 | 51.9% | 31.9% | 16.3% | 1.14 (+0.14d) | 34.6% | 100.0% | 4/21 (19.1%) |
| gemini-4-argon | medium | 21 | +0.633 +/- 0.080 | 95.2% | 8424 | 6.52 | 37.2% | 51.8% | 10.9% | 1.71 (+0.71d) | 51.4% | 100.0% | 2/20 (10.0%) |
| gemini-4-argon | high | 14 | +0.479 +/- 0.333 | 85.7% | 33560 | 4.93 | 2.9% | 75.4% | 21.7% | 2.43 (+1.43d) | 69.1% | 100.0% | 3/14 (21.4%) |
| gemini-4-carbon | low | 10 | +0.629 +/- 0.100 | 100.0% | 530 | 7.70 | 42.9% | 32.5% | 24.7% | 1.10 (+0.10d) | 40.7% | 100.0% | 0/10 (0.0%) |
| gemini-4-carbon | high | 10 | +0.639 +/- 0.164 | 90.0% | 50290 | 6.40 | 1.6% | 53.1% | 45.3% | 1.00 (+0.00d) | 67.7% | 100.0% | 2/9 (22.2%) |

## 5. Thinking-Budget Scaling Shifts (`high` minus `low` within Model)

| Model | Tier | n (low/high) | dScore | dAcc | Rec <=3 (low -> high) | Rec 4-8 (low -> high) | 1st Can Lag (low -> high) | Interview% (low -> high) | Below-BE% (low -> high) |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | hard | 10/10 | -0.017 | +0.0% | 27.0% -> 52.2% (+25.2%) | 27.0% -> 39.1% (+12.1%) | +0.50d -> +0.50d (+0.00d) | 18.7% -> 17.6% (-1.1%) | 100.0% -> 70.0% (-30.0%) |
| gemini-3.5-flash (served 3.6-flash) | hard | 10/40 | +0.123 | +10.0% | 43.9% -> 37.8% (-6.1%) | 11.4% -> 16.3% (+4.9%) | +0.20d -> +0.62d (+0.42d) | 1.3% -> 3.3% (+2.0%) | 40.0% -> 25.0% (-15.0%) |
| gemini-3.8-flash | hard | 10/20 | +0.218 | +10.0% | 52.2% -> 5.5% (-46.7%) | 16.2% -> 59.1% (+42.9%) | +2.00d -> +5.00d (+3.00d) | 0.0% -> 7.2% (+7.2%) | 20.0% -> 26.3% (+6.3%) |
| gemini-4-hydrogen | hard | 12/9 | -0.083 | -2.8% | 14.1% -> 0.0% (-14.1%) | 36.6% -> 43.8% (+7.2%) | +0.83d -> +0.22d (-0.61d) | 4.7% -> 37.9% (+33.2%) | 58.3% -> 0.0% (-58.3%) |
| gemini-4-argon | hard | 18/14 | +0.168 | +7.9% | 49.4% -> 0.0% (-49.4%) | 33.5% -> 65.6% (+32.1%) | +2.83d -> +3.43d (+0.60d) | 11.8% -> 70.2% (+58.4%) | 22.2% -> 21.4% (-0.8%) |
| gemini-4-carbon | hard | 10/10 | +0.145 | +0.0% | 30.5% -> 0.0% (-30.5%) | 43.7% -> 46.3% (+2.6%) | +0.90d -> +1.00d (+0.10d) | 20.9% -> 67.2% (+46.3%) | 0.0% -> 20.0% (+20.0%) |
| gemini-3.1-flash-lite | medium | 10/10 | -0.397 | -20.0% | 53.3% -> 71.4% (+18.1%) | 6.7% -> 21.4% (+14.7%) | +0.40d -> +1.60d (+1.20d) | 22.2% -> 24.0% (+1.8%) | 80.0% -> 100.0% (+20.0%) |
| gemini-3.5-flash (served 3.6-flash) | medium | 10/20 | +0.517 | +30.0% | 49.3% -> 60.3% (+11.0%) | 16.9% -> 15.6% (-1.3%) | +0.00d -> +0.05d (+0.05d) | 13.2% -> 17.8% (+4.6%) | 50.0% -> 25.0% (-25.0%) |
| gemini-3.8-flash | medium | 10/20 | +0.508 | +30.0% | 44.7% -> 22.6% (-22.1%) | 18.4% -> 63.1% (+44.7%) | +0.50d -> +3.70d (+3.20d) | 11.5% -> 10.5% (-1.0%) | 50.0% -> 30.0% (-20.0%) |
| gemini-4-hydrogen | medium | 13/10 | +0.107 | +23.1% | 36.2% -> 0.0% (-36.2%) | 37.7% -> 65.7% (+28.0%) | +0.46d -> +0.10d (-0.36d) | 12.0% -> 58.9% (+46.9%) | 50.0% -> 10.0% (-40.0%) |
| gemini-4-argon | medium | 21/14 | -0.223 | -14.3% | 51.9% -> 2.9% (-49.0%) | 31.9% -> 75.4% (+43.5%) | +0.14d -> +1.43d (+1.29d) | 34.6% -> 69.1% (+34.5%) | 19.1% -> 21.4% (+2.4%) |
| gemini-4-carbon | medium | 10/10 | +0.010 | -10.0% | 42.9% -> 1.6% (-41.3%) | 32.5% -> 53.1% (+20.6%) | +0.10d -> +0.00d (-0.10d) | 40.7% -> 67.7% (+27.0%) | 0.0% -> 22.2% (+22.2%) |

## 6. Counterfactual Schedule Replay: `frontier_synthesis_v14` vs `default_v0` (`hard`, Seeds `0-9`)

Each cell's recorded tool schedule up to its accusation day (`ScheduleReplayPolicy(target_day='accuse')`) is replayed deterministically in `Env('hard', seed)` against `default_v0` (`DEFAULT_STRATEGY`) and `frontier_synthesis_v14` via `inspect_observation_history`. Positive `P(mole) Drop` and `opt_EV Drop` indicate stronger mole evasion under `frontier_synthesis_v14`.

| Model | Thinking | n | P(mole) Default -> Synth | P(mole) Drop +/- CI | opt_EV Default -> Synth | opt_EV Drop +/- CI | Surfaced Canaries (d) | Top=Mole Acc |
|---|---|---|---|---|---|---|---|---|
| gemma-4-31b-it (hosted) | default | 5 | 0.089 -> 0.058 | +0.031 +/- 0.054 | 0.000 -> 0.041 | -0.041 +/- 0.080 | 0.60 -> 1.00 (+0.40) | 0.0% -> 0.0% |
| gemini-3.1-flash-lite | minimal | 10 | 0.098 -> 0.084 | +0.014 +/- 0.021 | 0.000 -> 0.000 | +0.000 +/- 0.000 | 0.00 -> 0.00 (+0.00) | 20.0% -> 0.0% |
| gemini-3.1-flash-lite | low | 10 | 0.205 -> 0.176 | +0.028 +/- 0.107 | 0.005 -> 0.118 | -0.113 +/- 0.149 | 0.20 -> 0.50 (+0.30) | 30.0% -> 10.0% |
| gemini-3.1-flash-lite | medium | 10 | 0.118 -> 0.097 | +0.021 +/- 0.031 | 0.000 -> 0.000 | +0.000 +/- 0.000 | 0.00 -> 0.00 (+0.00) | 10.0% -> 0.0% |
| gemini-3.1-flash-lite | high | 10 | 0.393 -> 0.215 | +0.178 +/- 0.233 | 0.229 -> 0.090 | +0.139 +/- 0.194 | 0.30 -> 0.30 (+0.00) | 40.0% -> 30.0% |
| gemini-3.5-flash (served 3.6-flash) | minimal | 10 | 0.831 -> 0.515 | +0.316 +/- 0.214 | 0.307 -> 0.127 | +0.180 +/- 0.122 | 3.10 -> 2.60 (-0.50) | 90.0% -> 60.0% |
| gemini-3.5-flash (served 3.6-flash) | low | 10 | 0.712 -> 0.496 | +0.215 +/- 0.361 | 0.370 -> 0.229 | +0.141 +/- 0.295 | 1.80 -> 1.10 (-0.70) | 70.0% -> 40.0% |
| gemini-3.5-flash (served 3.6-flash) | medium | 10 | 0.845 -> 0.693 | +0.152 +/- 0.175 | 0.473 -> 0.292 | +0.180 +/- 0.166 | 2.30 -> 1.60 (-0.70) | 80.0% -> 70.0% |
| gemini-3.5-flash (served 3.6-flash) | high | 10 | 0.933 -> 0.367 | +0.566 +/- 0.245 | 0.553 -> 0.251 | +0.302 +/- 0.233 | 2.40 -> 1.00 (-1.40) | 100.0% -> 40.0% |
| gemini-3.8-flash | low | 10 | 0.701 -> 0.548 | +0.153 +/- 0.242 | 0.311 -> 0.264 | +0.048 +/- 0.203 | 2.00 -> 1.40 (-0.60) | 80.0% -> 50.0% |
| gemini-3.8-flash | medium | 10 | 0.657 -> 0.429 | +0.227 +/- 0.307 | 0.372 -> 0.148 | +0.224 +/- 0.173 | 1.30 -> 0.80 (-0.50) | 70.0% -> 50.0% |
| gemini-3.8-flash | high | 10 | 0.597 -> 0.456 | +0.141 +/- 0.241 | 0.323 -> 0.168 | +0.154 +/- 0.137 | 1.30 -> 0.90 (-0.40) | 70.0% -> 40.0% |
| gemini-4-hydrogen | low | 10 | 0.514 -> 0.275 | +0.239 +/- 0.215 | 0.251 -> 0.056 | +0.195 +/- 0.194 | 1.60 -> 1.20 (-0.40) | 40.0% -> 10.0% |
| gemini-4-hydrogen | medium | 8 | 0.758 -> 0.616 | +0.142 +/- 0.295 | 0.335 -> 0.264 | +0.070 +/- 0.237 | 2.12 -> 2.12 (+0.00) | 75.0% -> 62.5% |
| gemini-4-hydrogen | high | 8 | 0.852 -> 0.718 | +0.134 +/- 0.294 | 0.557 -> 0.261 | +0.297 +/- 0.175 | 2.12 -> 1.50 (-0.62) | 87.5% -> 87.5% |
| gemini-4-hydrogen | xhigh | 7 | 0.980 -> 0.647 | +0.333 +/- 0.238 | 0.625 -> 0.279 | +0.346 +/- 0.242 | 2.43 -> 1.43 (-1.00) | 100.0% -> 85.7% |
| gemini-4-argon | low | 10 | 0.871 -> 0.350 | +0.521 +/- 0.272 | 0.478 -> 0.138 | +0.340 +/- 0.251 | 1.50 -> 0.80 (-0.70) | 90.0% -> 30.0% |
| gemini-4-argon | medium | 10 | 0.721 -> 0.462 | +0.259 +/- 0.326 | 0.331 -> 0.158 | +0.173 +/- 0.186 | 1.20 -> 0.70 (-0.50) | 80.0% -> 50.0% |
| gemini-4-argon | high | 10 | 0.771 -> 0.385 | +0.387 +/- 0.301 | 0.344 -> 0.079 | +0.265 +/- 0.216 | 1.20 -> 0.50 (-0.70) | 90.0% -> 50.0% |
| gemini-4-carbon | low | 10 | 0.969 -> 0.639 | +0.330 +/- 0.177 | 0.460 -> 0.130 | +0.330 +/- 0.172 | 2.00 -> 1.70 (-0.30) | 100.0% -> 70.0% |
| gemini-4-carbon | high | 10 | 0.889 -> 0.566 | +0.323 +/- 0.260 | 0.505 -> 0.227 | +0.278 +/- 0.240 | 1.70 -> 1.60 (-0.10) | 100.0% -> 60.0% |
| **Capable Gemini Pooled** | **all** | **153** | **0.783 -> 0.503** | **+0.280 +/- 0.066** | **0.407 -> 0.188** | **+0.219 +/- 0.051** | **1.86 -> 1.29 (-0.57)** | **82.3% -> 52.3%** |
| **All Hard Cells Pooled** | **all** | **198** | **0.649 -> 0.419** | **+0.229 +/- 0.054** | **0.326 -> 0.157** | **+0.169 +/- 0.043** | **1.48 -> 1.07 (-0.41)** | **68.7% -> 42.4%** |

## 7. Implications for Fair Mole Design Across Model Scales

1. **Small/open-weight and low-budget regimes (`gemma-4-31b-it`, `gemini-3.1-flash-lite`)** fail primarily through uncalibrated below-breakeven accusations (92.5%-100.0% on Hard); `flash-lite` also falls for the angry decoy (18.8% decoy accusation rate across Medium + Hard), whereas `gemma-4-31b-it` already dismisses the decoy (100.0%) but accuses before isolating a suspect.
2. **Mid-scale high-throughput Flash (`gemini-3.5-flash` served as `3.6-flash`)** plants early Day-1/Day-2 surgical `<=3`-recipient traps (34.5%-43.9% on Hard at low-high thinking) with minimal interview waste (0.9%-3.3% investigative share), making Rule 1 (`recent_low_recipient_docs >= 2 -> leak=most_recipients`) the decisive evasion lever (`P(mole)` drops by 0.566 at `high` thinking).
3. **Frontier reasoning cells (`gemini-3.8-flash @ high`, `gemini-4-hydrogen/argon/carbon @ high/xhigh`)** abandon `<=3` surgical traps (0.0%-5.5% on Hard), spend 37.9%-70.2% of investigative calls on low-LR interviews, and plant reactive `4-8` / `>=9` canaries later in the horizon, making Rule 2 (`newest_doc_age_days == 0 -> leak=oldest`), Rule 3 (days 5-8 pacing), and Rule 4 (non-decoy peer framing) the binding levers while preserving Day-1 pipelined `SolverPolicy` catchability.
