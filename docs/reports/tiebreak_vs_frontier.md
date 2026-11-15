# Tiebreak vs Frontier Failure Convergence Report (Rules v1.4)

> **Thesis (`README.md`)**: *"The model never learned to gather evidence in its own games: the same decision gemini-4-carbon gets wrong (fewer canaries, earlier commitment)"*

**Seed Hygiene and Protocol Disclosure (Panel Fix A)**:
- `DEV_SEEDS 0..29` (`dev_eval_seed_range = "0..29"`) used in the frontier vs solver panels below are **post-hoc locked, not pre-registered** (locked immediately after committing `data/runs/committed/v1.4/` to prevent reruns or cherry-picking).
- All compact policy training strictly uses `TRAIN_SEEDS 102000..102779` (`[100000, 200000)`), and all held-out tiebreak evaluations strictly use disjoint `HELDOUT_SEEDS 800000..800029` / `800000..800059` (`[800000, 800200)`), with `0` `JUDGE_SEEDS` (`900000+`) touched.
- Replay provenance: `510/510` live/committed episodes verified step-by-step in fresh `Env` (`0` mismatches), `90/90` held-out `SolverPolicy` reference episodes verified under shared `sha256:ebf2f09716cf76d3`, and `450/450` Verda `Qwen2.5-1.5B` held-out transcripts verified via `SolverPolicy` Bayesian belief replay.

## 1. Executive Convergence Summary: Same Two Decisions Broken, Two Scales

Evaluating every trajectory under the reference `SolverPolicy`'s exact Bayesian posterior over the **agent's own tool observations** demonstrates that frontier `gemini-4-carbon` and raw-context `Qwen2.5-1.5B` fail on the exact same two sequential decision bottlenecks, while calibrating those two bottlenecks on `TRAIN_SEEDS` closes the gap:

1. **Under-Exploration of Diagnostic Canary Variants**: On post-hoc locked `DEV_SEEDS 0..29` (`hard`, `n=30`), `SolverPolicy` plants `14.13` canaries (`42.40` diagnostic variant arms, `66.7%` daily slot utilization, `0.0` interviews) before committing, isolating a single consistent suspect in `26/30` (`86.7%`) episodes. `gemini-4-carbon` (OpenCode/MCP) plants only `8.47` canaries (`25.40` variant arms, `31.5%` slot utilization) while spending `68.0` calls/episode on low-KL interviews. Raw-context `Qwen2.5-1.5B` magnifies the same deficit on `HELDOUT_SEEDS`: `v2-off30` plants `2.11` canaries before accusing (`6.24` variant arms) and pooled `v3-4k` (`n=180`) plants only `3.53` before accusing (`97-100%` later evicted by the `2,842`-token prompt header tax). Trained `EmpiricalBayesPolicy` (`eb_experience_opt`) learns to plant `17.13` canaries (`49.87` variant arms) on `hard` `0..29` and `9.67` across all 3 held-out tiers.
2. **Premature Commitment Below Breakeven (`top_p < 1 / (1 + known_v)`)**: Because a wrong accusation scores `-1.0` while abstaining scores `0.0`, accusing has negative expected value against visible `known_v` whenever `P(accused) < breakeven = 1 / (1 + known_v)` (and stricter negative EV under delayed leaks where `E[true V] < known_v`). On `hard` `0..29`, `SolverPolicy` commits below breakeven in `0/30` (`0.0%`) episodes and below `0.85` in `0/30` (`0.0%`). `gemini-4-carbon` (OpenCode/MCP) commits with `top_p < breakeven` in `3/29` (`10.3%`) accusations and below `0.85` in `10/29` (`34.5%`). Raw-context `Qwen2.5-1.5B` commits with `P(accused) < breakeven` in `90/94` (`95.7%`) pooled `v2` accusations, `35/38` (`92.1%`) pooled `v3-4k` accusations (`25/38 = 65.8%` even for argmax `top_p`), and `83/85` (`97.7%`) `v3-8k-s1` accusations. Training `EmpiricalBayesPolicy` on `TRAIN_SEEDS` drives `top_p < breakeven` commitments from `90.0%` (`27/30`) down to `0.0%` (`0/30`) on `hard` `0..29`, and from `64.4%` (`58/90`) down to `0.0%` (`0/82`) on `HELDOUT_SEEDS`.
3. **Abstention Calibration Under Delayed Leaks**: Under `1-3` day (`medium`) and `2-3` day (`hard`) leak delays, raw-context `Qwen2.5-1.5B` oscillates between reckless commitment (`v2`, `v3-8k-s1`, `v3-8k-s3`) and uncalibrated `eval_cap` / abstention collapse (`v3-4k` `142/180` abstained with `28/142` missed positive-EV states already present in its own transcript; `v3-8k-s2` `93.3%` abstained with `9/84` missed positive-EV states). Trained `EmpiricalBayesPolicy` abstains `8/90` times on `HELDOUT_SEEDS` with `8/8` (`100.0%`) calibrated abstentions and `0` missed positive-EV commitments.

## 2. Panel A: Post-Hoc Locked `DEV_SEEDS 0..29` (Not Pre-Registered) - Frontier vs Compact Policy vs Solver

### 2.1 Hard Tier (`n=30` Paired Worlds, 40 Employees, 21 Days, 2-3 Day Leak Delay, 5% Fingerprint Noise)

| Cohort | n | Score +/- 95% CI | Luck-Adj EV | Canaries Pre-Accuse | Diag Variant Arms | Slot Util | Interviews | Accuse Day | Mean `P(acc)` / `breakeven` | `top_p < breakeven` | `P(acc) < 0.85` | Abstain (Cal / Miss) | Env Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| gemini-4-carbon (OpenCode over MCP, judges' harness) | 30 | `+0.322 +/- 0.199` | `+0.360` | 8.47 | 25.40 | 31.5% | 68.0 | 13.2 | `0.88 / 0.64` | 3/29 (10.3%) | 10/29 (34.5%) | 1 (1/0) | `30/30` |
| gemini-4-carbon (in-process full history) | 30 | `+0.473 +/- 0.118` | `+0.421` | 8.57 | 25.70 | 33.0% | 57.3 | 12.7 | `0.93 / 0.64` | 3/29 (10.3%) | 4/29 (13.8%) | 1 (1/0) | `30/30` |
| gemini-3.5-flash (OpenCode over MCP) | 30 | `+0.373 +/- 0.177` | `+0.110` | 12.43 | 36.57 | 48.9% | 0.7 | 12.7 | `0.71 / 0.65` | 9/30 (30.0%) | 12/30 (40.0%) | 0 (0/0) | `30/30` |
| EmpiricalBayesPolicy (uncalibrated naive prior) | 30 | `-0.846 +/- 0.169` | `-0.835` | 5.93 | 17.80 | 74.8% | 1.6 | 4.0 | `0.10 / 0.53` | 27/30 (90.0%) | 28/30 (93.3%) | 0 (0/0) | `30/30` |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | 30 | `+0.550 +/- 0.048` | `+0.480` | 17.13 | 49.87 | 89.5% | 6.6 | 9.6 | `0.96 / 0.63` | 0/30 (0.0%) | 1/30 (3.3%) | 0 (0/0) | `30/30` |
| SolverPolicy (Bayesian canary-trap reference) | 30 | `+0.499 +/- 0.119` | `+0.499` | 14.13 | 42.40 | 66.7% | 0.0 | 10.6 | `0.97 / 0.63` | 0/30 (0.0%) | 0/30 (0.0%) | 0 (0/0) | `30/30` |

- **World-paired `hard` `0..29` deltas** (post-hoc locked, not pre-registered): `gemini-4-carbon` OpenCode minus `SolverPolicy` = `-0.177 +/- 0.194`; trained `eb_experience_opt` minus uncalibrated `eb_naive_prior` = `+1.396 +/- 0.167`; trained `eb_experience_opt` minus `gemini-4-carbon` OpenCode = `+0.228 +/- 0.209`.

### 2.2 Medium Tier (`n=30` Paired Worlds, 20 Employees, 14 Days, 1-3 Day Leak Delay, 0% Noise)

| Cohort | n | Score +/- 95% CI | Luck-Adj EV | Canaries Pre-Accuse | Diag Variant Arms | Slot Util | Interviews | Accuse Day | `top_p < breakeven` | Abstain (Cal / Miss) | Env Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemini-4-carbon (OpenCode over MCP, judges' harness) | 30 | `+0.713 +/- 0.042` | `+0.652` | 5.83 | 17.50 | 73.2% | 37.5 | 8.0 | 2/30 (6.7%) | 0 (0/0) | `30/30` |
| gemini-4-carbon (in-process full history) | 30 | `+0.530 +/- 0.138` | `+0.479` | 6.93 | 20.70 | 71.5% | 47.2 | 9.0 | 3/26 (11.5%) | 4 (4/0) | `30/30` |
| EmpiricalBayesPolicy (uncalibrated naive prior) | 30 | `-0.945 +/- 0.108` | `-0.947` | 2.93 | 8.80 | 74.6% | 1.6 | 3.9 | 29/30 (96.7%) | 0 (0/0) | `30/30` |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | 30 | `+0.516 +/- 0.176` | `+0.555` | 8.07 | 22.93 | 89.0% | 6.2 | 8.3 | 1/26 (3.9%) | 4 (4/0) | `30/30` |
| SolverPolicy (Bayesian canary-trap reference) | 30 | `+0.645 +/- 0.087` | `+0.645` | 7.30 | 19.77 | 89.0% | 0.0 | 7.6 | 0/27 (0.0%) | 3 (3/0) | `30/30` |

## 3. Panel B: Disjoint `HELDOUT_SEEDS` (`800000..800059`) - Raw-Context `Qwen2.5-1.5B` WS4/Verda vs `EmpiricalBayesPolicy` vs `SolverPolicy`

| Cohort | Seed Span | n | Score +/- 95% CI | Canaries Pre-Accuse (Total) | Diag Variant Arms | Accused | `top_p < breakeven` | `P(acc) < breakeven` | Argmax Match | Abstain (Cal / Miss) | Audit Mode |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Qwen2.5-1.5B base (untrained, pooled 44411 + 44584) | `800000..800012` | 36 | `+0.000 +/- 0.000` | 0.00 (0.00) | 0.00 | 0/36 (0.0%) | n/a | n/a | n/a | 36 (cap stall) | `forensic_log` |
| Qwen2.5-1.5B LoRA v2 (dense 4k SFT, Verda off30) | `800030..800059` | 90 | `-0.514 +/- 0.115` | 2.11 (2.11) | 6.24 | 52/90 (57.8%) | 47/52 (90.4%) | 50/52 (96.2%) | 8/52 (15.4%) | 38 (34/4) | `belief_replay (90/90)` |
| Qwen2.5-1.5B LoRA v3-4k (609-step GRPO, Verda pooled) | `800000..800059` | 180 | `-0.147 +/- 0.063` | 3.53 (3.53) | 9.31 | 38/180 (21.1%) | 25/38 (65.8%) | 35/38 (92.1%) | 8/38 (21.1%) | 142 (114/28) | `belief_replay (180/180)` |
| Qwen2.5-1.5B LoRA v3-8k seed 1 (371-step GRPO, Verda A100) | `800000..800029` | 90 | `-0.777 +/- 0.118` | 2.31 (2.31) | 6.91 | 85/90 (94.4%) | 77/85 (90.6%) | 83/85 (97.7%) | 10/85 (11.8%) | 5 (4/1) | `belief_replay (90/90)` |
| Qwen2.5-1.5B LoRA v3-8k seed 2 (693-step GRPO, Verda H100) | `800000..800029` | 90 | `-0.050 +/- 0.049` | 1.69 (1.69) | 4.96 | 6/90 (6.7%) | 2/6 (33.3%) | 5/6 (83.3%) | 1/6 (16.7%) | 84 (75/9) | `belief_replay (90/90)` |
| EmpiricalBayesPolicy (uncalibrated naive prior) | `800000..800029` | 90 | `-0.386 +/- 0.172` | 4.80 (4.80) | 14.40 | 90/90 (100.0%) | 58/90 (64.4%) | 60/90 (66.7%) | 35/90 (38.9%) | 0 (0/0) | `fresh_Env (90/90)` |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | `800000..800029` | 90 | `+0.622 +/- 0.050` | 9.67 (9.67) | 27.44 | 82/90 (91.1%) | 0/82 (0.0%) | 0/82 (0.0%) | 82/82 (100.0%) | 8 (8/0) | `fresh_Env (90/90)` |
| SolverPolicy (Bayesian canary-trap reference, held-out n=90) | `800000..800029` | 90 | `+0.682 +/- 0.053` | 7.61 (7.61) | 22.83 | 87/90 (96.7%) | 0/87 (0.0%) | 0/87 (0.0%) | 87/87 (100.0%) | 3 (3/0) | `fresh_Env (90/90)` |

- **Pooled WS4 + Verda `v2` (`n=172`, `800000..800059`)**: `-0.457 +/- 0.086`, `8/94` accusation precision (`8.5%`), with `90/94` (`95.7%`) premature accusations committed strictly below `breakeven = 1 / (1 + known_v)` under `2842/4096` header crowding (`1254` body tokens).
- **8k Inference-Length Confound and Truly Paired 8k-vs-4k@8k Null (`800000..800029`, shared secret `1ca0c2a64d`)**: evaluating the 4k-trained `v3-4k-s0` adapter at `max_ctx=8192` (`v3-4k-s0@8k`, `n=90`) dropped score to `-0.716 +/- 0.105` (`-0.568 +/- 0.123` vs 4k), while 8k-trained `v3-8k-s3` (`n=90`) scored `-0.788 +/- 0.117`, giving a truly paired delta of `-0.073 +/- 0.173` across `60/60` identical step-0 rosters.
- **World-Paired `EmpiricalBayesPolicy` Gain (`HELDOUT_SEEDS`, shared `sha256:ebf2f09716cf76d3`, Non-LLM Compact Control)**: `+1.008 +/- 0.163` (`[+0.845, +1.171]`) on `n=90` (`800000..800029`), and `+1.028` (`[+0.915, +1.138]`) on full `n=180` (`800000..800059`). Per `docs/agents/PANEL-0500.md` Fix E, this non-LLM compact parametric control is strictly separated from open-weight `Qwen2.5` LoRA runs.

## 4. Per-Tier Breakdown on `HELDOUT_SEEDS` (Delayed Leaks: Easy 1d vs Medium 1-3d vs Hard 2-3d + 5% Noise)

| Cohort | Tier | n | Score +/- 95% CI | Canaries Pre-Accuse | Diag Variant Arms | Accused | `top_p < breakeven` | `P(acc) < breakeven` | Abstain (Cal / Miss) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-1.5B LoRA v2 (dense 4k SFT, Verda off30) | `easy` | 30 | `-0.839 +/- 0.182` | 1.13 | 3.37 | 29/30 | 26/29 (89.7%) | 27/29 (93.1%) | 1 (1/0) |
| Qwen2.5-1.5B LoRA v2 (dense 4k SFT, Verda off30) | `medium` | 30 | `-0.070 +/- 0.127` | 2.80 | 8.17 | 4/30 | 3/4 (75.0%) | 4/4 (100.0%) | 26 (24/2) |
| Qwen2.5-1.5B LoRA v2 (dense 4k SFT, Verda off30) | `hard` | 30 | `-0.633 +/- 0.175` | 2.40 | 7.20 | 19/30 | 18/19 (94.7%) | 19/19 (100.0%) | 11 (9/2) |
| Qwen2.5-1.5B LoRA v3-4k (609-step GRPO, Verda pooled) | `easy` | 60 | `-0.409 +/- 0.165` | 1.23 | 2.90 | 36/60 | 25/36 (69.4%) | 33/36 (91.7%) | 24 (17/7) |
| Qwen2.5-1.5B LoRA v3-4k (609-step GRPO, Verda pooled) | `medium` | 60 | `+0.000 +/- 0.000` | 3.20 | 7.22 | 0/60 | 0/0 (0.0%) | 0/0 (0.0%) | 60 (53/7) |
| Qwen2.5-1.5B LoRA v3-4k (609-step GRPO, Verda pooled) | `hard` | 60 | `-0.033 +/- 0.046` | 6.17 | 17.82 | 2/60 | 0/2 (0.0%) | 2/2 (100.0%) | 58 (44/14) |
| Qwen2.5-1.5B LoRA v3-8k seed 1 (371-step GRPO, Verda A100) | `easy` | 30 | `-0.580 +/- 0.250` | 0.87 | 2.53 | 25/30 | 21/25 (84.0%) | 23/25 (92.0%) | 5 (4/1) |
| Qwen2.5-1.5B LoRA v3-8k seed 1 (371-step GRPO, Verda A100) | `medium` | 30 | `-0.938 +/- 0.122` | 2.77 | 8.30 | 30/30 | 27/30 (90.0%) | 30/30 (100.0%) | 0 (0/0) |
| Qwen2.5-1.5B LoRA v3-8k seed 1 (371-step GRPO, Verda A100) | `hard` | 30 | `-0.813 +/- 0.204` | 3.30 | 9.90 | 30/30 | 29/30 (96.7%) | 30/30 (100.0%) | 0 (0/0) |
| Qwen2.5-1.5B LoRA v3-8k seed 2 (693-step GRPO, Verda H100) | `easy` | 30 | `-0.067 +/- 0.091` | 1.13 | 3.30 | 2/30 | 0/2 (0.0%) | 2/2 (100.0%) | 28 (24/4) |
| Qwen2.5-1.5B LoRA v3-8k seed 2 (693-step GRPO, Verda H100) | `medium` | 30 | `+0.000 +/- 0.000` | 1.57 | 4.60 | 0/30 | 0/0 (0.0%) | 0/0 (0.0%) | 30 (27/3) |
| Qwen2.5-1.5B LoRA v3-8k seed 2 (693-step GRPO, Verda H100) | `hard` | 30 | `-0.083 +/- 0.116` | 2.37 | 6.97 | 4/30 | 2/4 (50.0%) | 3/4 (75.0%) | 26 (24/2) |
| EmpiricalBayesPolicy (uncalibrated naive prior) | `easy` | 30 | `+0.635 +/- 0.162` | 4.50 | 13.50 | 30/30 | 2/30 (6.7%) | 2/30 (6.7%) | 0 (0/0) |
| EmpiricalBayesPolicy (uncalibrated naive prior) | `medium` | 30 | `-0.945 +/- 0.108` | 3.30 | 9.90 | 30/30 | 30/30 (100.0%) | 30/30 (100.0%) | 0 (0/0) |
| EmpiricalBayesPolicy (uncalibrated naive prior) | `hard` | 30 | `-0.847 +/- 0.168` | 6.60 | 19.80 | 30/30 | 26/30 (86.7%) | 28/30 (93.3%) | 0 (0/0) |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | `easy` | 30 | `+0.729 +/- 0.079` | 4.83 | 13.63 | 28/30 | 0/28 (0.0%) | 0/28 (0.0%) | 2 (2/0) |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | `medium` | 30 | `+0.570 +/- 0.109` | 8.03 | 22.97 | 24/30 | 0/24 (0.0%) | 0/24 (0.0%) | 6 (6/0) |
| EmpiricalBayesPolicy (trained on TRAIN_SEEDS 102000..102779) | `hard` | 30 | `+0.569 +/- 0.050` | 16.13 | 45.73 | 30/30 | 0/30 (0.0%) | 0/30 (0.0%) | 0 (0/0) |

## 5. Offline Reproducibility and Deterministic Verifier Commands

```bash
python scripts/tiebreak_vs_frontier_comparison.py
python scripts/tiebreak_vs_frontier_comparison.py --check
```
