# Verda Multi-Seed GRPO Replication and World-Paired Shared-Secret Audit

Offline belief-replay and world-identity audit of all 4 Verda 8k decision-point GRPO replicates (`v3_8k_s0`..`v3_8k_s3`), both 4k GRPO replicates (`v3_4k_s0` on Verda H100 and `v3_4k_s1` on FR8 V100, plus the preempted Verda spot replicate `714d8144`), and the same-weights 8k inference control (`v3_4k_s0_ctx8k`). Every episode is replayed step-by-step through `SolverPolicy` exact Bayesian belief tracking with zero API calls.

## 1. Executive Summary

- Episodes belief-replayed and score-verified: `712` (`0` invariant errors; `2846` GRPO curve steps audited).
- Verda 8k bimodal split across 4 seeds (3.0 h wall-clock budget per seed): H100 high-step seeds `v3_8k_s0` (`637` steps, `-0.060 +/- 0.054`) and `v3_8k_s2` (`693` steps, `-0.050 +/- 0.049`) abstain on `92.2%` and `93.3%` of episodes; A100 low-step seeds `v3_8k_s1` (`371` steps, `-0.777 +/- 0.118`) and `v3_8k_s3` (`344` steps, `-0.788 +/- 0.117`) accuse on `94.4%` and `95.6%` of episodes.
- Exact world-paired shared-secret deltas (`n=90`, held-out seeds `800000..800029`, 100% step-0 `list_employees` roster match): `v3_8k_s0 - v3_8k_s3 = +0.728 +/- 0.134` (`61/61` rosters identical), `v3_8k_s3 - v3_4k_s0_ctx8k = -0.073 +/- 0.173` (`60/60` rosters identical), and `v3_8k_s0 - v3_4k_s0_ctx8k = +0.655 +/- 0.116` (`60/60` rosters identical).
- Honest bottom line: `0/6` GRPO seeds beat the always-abstain base model (`0.000`). High-step GRPO (`~650` steps) suppresses uncalibrated 8k over-accusations, recovering `+0.655 +/- 0.116` paired over `4k@8k`, but also abstains on `21/167` episodes where the posterior already exceeded the Bayesian breakeven threshold `p* = 1 / (1 + V)`.

## 2. All 6 GRPO Seeds Plus Same-Weights 8k Control

| Run ID | Context | GPU & Instance | GRPO Steps | Secret Provenance | Held-Out Seeds | n | Score +/- 95% CI | Luck-Adj EV | Accused | Correct | Abstain | Valid Calls | Regime |
|---|---|---|---:|---|---|---:|---|---:|---:|---:|---:|---:|---|
| v3_8k_s0 | 8192 | H100 (3bb74f5a, on-demand) | 637 | shared_secret | 800000..800029 | 90 | -0.060 +/- 0.054 | -0.057 | 0.08 | 0.01 | 0.92 | 0.98 | high_step_abstain_regime |
| v3_8k_s1 | 8192 | A100 (ac58df04, spot) | 371 | ephemeral_unpaired | 800000..800029 | 90 | -0.777 +/- 0.118 | -0.829 | 0.94 | 0.09 | 0.06 | 0.92 | low_step_over_accuse_regime |
| v3_8k_s2 | 8192 | H100 (dbd083ca, spot) | 693 | ephemeral_unpaired | 800000..800029 | 90 | -0.050 +/- 0.049 | -0.044 | 0.07 | 0.01 | 0.93 | 0.96 | high_step_abstain_regime |
| v3_8k_s3 | 8192 | A100 (f4378173, on-demand) | 344 | shared_secret | 800000..800029 | 90 | -0.788 +/- 0.117 | -0.846 | 0.96 | 0.09 | 0.04 | 0.94 | low_step_over_accuse_regime |
| v3_4k_s0 | 4096 | H100 (3bb74f5a, on-demand) | 609 | ephemeral_unpaired | 800000..800059 | 180 | -0.147 +/- 0.063 | -0.155 | 0.21 | 0.03 | 0.79 | 1.00 | native_4k_moderate_abstain |
| v3_4k_s1 | 4096 | V100 (fr8-44572, slurm-cluster) | 192 | ephemeral_unpaired | 800000..800027 | 82 | -0.209 +/- 0.094 | -0.167 | 0.23 | 0.01 | 0.77 | 0.97 | native_4k_moderate_abstain |
| v3_4k_s0_ctx8k | 8192 | H100_train_A100_eval (68bbe201, on-demand) | 609 | shared_secret | 800000..800029 | 90 | -0.716 +/- 0.105 | -0.714 | 0.78 | 0.03 | 0.22 | 0.99 | inference_8k_context_shift_over_accuse |

Lost spot replicate disclosure: `v3_4k_s1_verda_spot_lost` on Verda A100 80GB spot (`714d8144`) was preempted ~30 min into training (`0.35` GPU-h, `0.38` EUR, `0` held-out episodes); the FR8 V100 job `44572` (`v3_4k_s1`, `192` steps, `n=82`) provides the second 4k replicate (`two-sample 4k_s0 - 4k_s1 = +0.061 +/- 0.113`).

### Per-Tier Breakdown Across All Audited Runs

| Run ID | Easy Score +/- CI (n) | Medium Score +/- CI (n) | Hard Score +/- CI (n) | Easy Accused | Medium Accused | Hard Accused |
|---|---|---|---|---:|---:|---:|
| v3_8k_s0 | -0.033 +/- 0.065 (30) | -0.067 +/- 0.091 (30) | -0.081 +/- 0.117 (30) | 0.03 | 0.07 | 0.13 |
| v3_8k_s1 | -0.580 +/- 0.250 (30) | -0.938 +/- 0.122 (30) | -0.813 +/- 0.205 (30) | 0.83 | 1.00 | 1.00 |
| v3_8k_s2 | -0.067 +/- 0.091 (30) | 0.000 +/- 0.000 (30) | -0.083 +/- 0.116 (30) | 0.07 | 0.00 | 0.13 |
| v3_8k_s3 | -0.643 +/- 0.249 (30) | -0.878 +/- 0.166 (30) | -0.843 +/- 0.178 (30) | 0.90 | 1.00 | 0.97 |
| v3_4k_s0 | -0.409 +/- 0.164 (60) | 0.000 +/- 0.000 (60) | -0.033 +/- 0.046 (60) | 0.60 | 0.00 | 0.03 |
| v3_4k_s1 | -0.576 +/- 0.208 (28) | 0.000 +/- 0.000 (27) | -0.037 +/- 0.073 (27) | 0.64 | 0.00 | 0.04 |
| v3_4k_s0_ctx8k | -0.447 +/- 0.233 (30) | -0.800 +/- 0.146 (30) | -0.900 +/- 0.109 (30) | 0.63 | 0.80 | 0.90 |

## 3. Exact World-Paired Shared-Secret Comparisons (n=90)

From 04:05 EET, Verda evaluations shared one `CANARY_WORLD_SECRET` (`verda_shared_secret_0405_1ca0c2a64d`). World identity is cryptographically cross-checked directly from episode transcripts by comparing step-0 `list_employees` rosters on every overlapping `(tier, seed)` where both runs queried the roster. As a negative control, pairing shared-secret `v3_8k_s0` against pre-04:05 `v3_8k_s1` yields `0/60` matching rosters, confirming why pre-04:05 comparisons must remain two-sample.

| Comparison | Formula | n | Roster Match | Overall Delta +/- 95% CI | 95% CI Bounds | Luck-Adj EV Delta +/- CI | Easy Delta +/- CI | Medium Delta +/- CI | Hard Delta +/- CI |
|---|---|---:|---|---|---|---|---|---|---|
| s0_minus_s3 | v3_8k_s0 - v3_8k_s3 | 90 | 61/61 | +0.728 +/- 0.134 | [+0.594, +0.862] | +0.789 +/- 0.091 | +0.610 +/- 0.281 | +0.812 +/- 0.183 | +0.762 +/- 0.223 |
| s3_minus_4k_at_8k | v3_8k_s3 - v3_4k_s0_ctx8k | 90 | 60/60 | -0.073 +/- 0.173 | [-0.245, +0.100] | -0.132 +/- 0.114 | -0.196 +/- 0.410 | -0.078 +/- 0.235 | +0.057 +/- 0.218 |
| s0_minus_4k_at_8k | v3_8k_s0 - v3_4k_s0_ctx8k | 90 | 60/60 | +0.655 +/- 0.116 | [+0.539, +0.771] | +0.657 +/- 0.099 | +0.414 +/- 0.231 | +0.733 +/- 0.161 | +0.819 +/- 0.180 |

Exact paired triangle identity on the 90 shared-secret worlds:
- `(v3_8k_s0 - v3_4k_s0_ctx8k) - (v3_8k_s3 - v3_4k_s0_ctx8k) = +0.6552 - (-0.0726) = +0.7278` (residual `0.000000`).
- World-level transitions `v3_8k_s3 -> v3_8k_s0` (`n=90`): `wrong_accuse -> abstain = 74`, `correct_accuse -> abstain = 5`, `wrong_accuse -> wrong_accuse = 4`, `abstain -> abstain = 4`, `wrong_accuse -> correct_accuse = 0`.
- World-level transitions `v3_4k_s0_ctx8k -> v3_8k_s0` (`n=90`): `wrong_accuse -> abstain = 61`, `abstain -> abstain = 19`, `wrong_accuse -> wrong_accuse = 5`, `correct_accuse -> abstain = 3`.
- World-level transitions `v3_4k_s0_ctx8k -> v3_8k_s3` (`n=90`): `wrong_accuse -> wrong_accuse = 55`, `abstain -> wrong_accuse = 20`, `wrong_accuse -> correct_accuse = 8`.

## 4. Belief-Replay Proof of the Step-Count Bimodal Regime Split (~350st vs ~650st)

| Run ID | Accused Eps | Mean Accuse Day | Mean p(accused) | Below Breakeven (p < p*) | Near-Zero (p <= 0.05) | Posterior Argmax | Ruled Out (Doc/Canary) | Abstained Eps | Mean Top-p (Abstain) | Missed Commits (top_p >= p*) |
|---|---:|---:|---:|---|---:|---:|---|---:|---:|---|
| v3_8k_s0 | 7 | 8.43 | 0.1637 | 6/7 | 5/7 | 2/7 | 4/1 | 83 | 0.3266 | 12/83 |
| v3_8k_s1 | 85 | 3.94 | 0.0637 | 83/85 | 64/85 | 7/85 | 36/4 | 5 | 0.2929 | 1/5 |
| v3_8k_s2 | 6 | 8.50 | 0.2042 | 5/6 | 4/6 | 1/6 | 2/2 | 84 | 0.3348 | 9/84 |
| v3_8k_s3 | 86 | 5.14 | 0.0608 | 84/86 | 64/86 | 5/86 | 49/6 | 4 | 0.0830 | 0/4 |
| v3_4k_s0 | 38 | 3.03 | 0.1380 | 35/38 | 22/38 | 8/38 | 21/5 | 142 | 0.3199 | 25/142 |
| v3_4k_s1 | 19 | 3.05 | 0.1468 | 18/19 | 10/19 | 4/19 | 7/4 | 63 | 0.3757 | 16/63 |
| v3_4k_s0_ctx8k | 70 | 6.97 | 0.0448 | 70/70 | 55/70 | 2/70 | 47/11 | 20 | 0.4307 | 4/20 |

### GRPO Training Curve Phase Transition Across Step Windows

| Run ID | GPU | Total Steps | sec/step | Steps 0..99 Free-Accuse | Steps 250..370 Free-Accuse | Steps 550+ Free-Accuse | Steps 250..370 Continue | Steps 550+ Continue | Steps 550+ Forced-Whom Acc |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v3_8k_s0 | H100 | 637 | 17.0 | 0.083 | 0.116 | 0.041 | 0.527 | 0.594 | 0.410 |
| v3_8k_s1 | A100 | 371 | 29.2 | 0.106 | 0.118 | n/a | 0.532 | n/a | n/a |
| v3_8k_s2 | H100 | 693 | 15.6 | 0.068 | 0.081 | 0.023 | 0.567 | 0.605 | 0.445 |
| v3_8k_s3 | A100 | 344 | 31.4 | 0.119 | 0.108 | n/a | 0.542 | n/a | n/a |
| v3_4k_s0 | H100 | 609 | 11.8 | 0.073 | 0.090 | 0.063 | 0.544 | 0.574 | 0.909 |
| v3_4k_s1 | V100 | 192 | 75.0 | 0.072 | n/a | n/a | n/a | n/a | n/a |

### Mechanistic Diagnosis

1. **Inference-context trigger (`4k -> 8k`)**: Evaluating `v3_4k_s0` (`609` steps, `-0.147` at 4k) at 8k context (`v3_4k_s0_ctx8k`) shifts score by `-0.568 +/- 0.123` to `-0.716 +/- 0.105`, driving `70/70` (`100.0%`) of accusations strictly below Bayesian breakeven (`55/70` at `p <= 0.05`).
2. **Low-step 8k cluster (`~350` steps on A100: `s1=371`, `s3=344`)**: In 3.0 h, A100 (`~29..31` s/step) terminates inside steps `250..370`, where `free_accuse_frac` is still `0.108..0.118`. Pooled across `s1` and `s3` (`n=180`), the policy accuses on `171/180` (`95.0%`) of episodes with `167/171` (`97.7%`) below breakeven and `85/171` accusing an employee ruled out by surfaced documents. World-paired against `4k@8k`, `s3` shows zero gain (`-0.073 +/- 0.173`).
3. **High-step 8k cluster (`~650` steps on H100: `s0=637`, `s2=693`)**: H100 (`~15.6..17.0` s/step, ~1.9x throughput) crosses step `500`, collapsing `free_accuse_frac` from `0.116 -> 0.041` (`s0`) and `0.081 -> 0.023` (`s2`). Pooled (`n=180`), abstention reaches `167/180` (`92.8%`), improving over low-step 8k by `+0.727 +/- 0.090` (two-sample) and `+0.728 +/- 0.134` (world-paired `s0 - s3`).
4. **Why high-step GRPO still trails base (`0.000`)**: On abstained episodes, `21/167` already had `max_e p(e) >= p*` (including `p = 1.000` after canary leaks), while `11/13` remaining accusations still fired below breakeven. Off-policy solver-state GRPO teaches global accusation suppression before calibrated own-trajectory stopping; closing that state-distribution gap requires on-policy DAgger / compact-state belief features.
5. **Causal caveat**: Across the four 8k seeds, H100 ran ~1.9x more GRPO steps than A100 in the same 3.0 h wall-clock budget (637 and 693 steps vs 344 and 371 steps). Training curves show all four 8k seeds sharing ~0.08..0.12 free_accuse_frac at steps 250..370 where A100 stopped, before collapsing to 0.023..0.041 at steps 550+ on H100. Because GPU family, step count, and RNG seed covary across N=4 runs, the audit reports exact mechanistic consistency without overclaiming unconfounded causality.

## 5. Reproduce

```bash
python scripts/tiebreak_verda_multiseed_audit.py
python scripts/tiebreak_verda_multiseed_audit.py --check
```
