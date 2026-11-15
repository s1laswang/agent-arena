# Mechanistic Investigator Discipline Curve and Regret Decomposition (`hard` Tier)

Generated deterministically offline (0 API calls) via `python -m canary.mole.discipline_curve --tier hard --seeds 6400-6479 --workers 1 --out results/mole_strategies/discipline_curve_v14.json --report-md docs/reports/mole_discipline_curve_v14.md`.

## 1. Executive Summary and Causal Hypothesis (`--hint gather` Twin)

- **Fresh disjoint evaluation slice**: `n=80` paired `hard` seeds (`6400-6479`), strictly disjoint from committed run seeds (`0..59`), reserved held-out evaluation seeds (`30000..30199`), and held-out/judge seeds (`800000+`, `900000+`).
- **Paired bootstrap uncertainty**: `5000` paired resamples (`ci=0.95`, `seed=20261114`).
- **Catchability and anti-shortcut gates**: **7/7** strategies passed every gate (`SolverPolicy` catchability `>= 0.85`, observed minimum `0.950`; `SolverPolicy` score ratio `>= 0.50` of `default_v0` baseline `+0.578`; `LogsOnly` accuracy `<= 0.10`, observed maximum `0.013`; `DoNothing` max `|score| == 0.000`).
- **Pooled 6-strategy transcript mean regret decomposition**: total regret `R4 - R0 = +0.222 [+0.159, +0.289]` decomposes exactly into (a) delayed-canary regret `R1 - R0 = +0.077 [+0.006, +0.147]`, (b) gamble-discipline regret `R3 - R1 = +0.020 [+0.006, +0.038]`, and (c) residual strategic evasion/framing regret `R4 - R3 = +0.124 [+0.068, +0.180]` (persisting even against the `--hint gather` twin; residual share of total regret `0.559`).
- **Gain over `default_v0` across the 6 transcript strategies**: total regret gain `-0.022 [-0.151, +0.101]`, `Rung 0` proxy score delta `-0.010 [-0.108, +0.094]`, `Rung 3` (`--hint gather` twin) score delta `+0.001 [-0.087, +0.095]`, and residual `R4 - R3` regret gain `-0.034 [-0.148, +0.080]` while `Rung 4` (`SolverPolicy`) score delta is `-0.032 [-0.088, +0.031]`.

## 2. Five-Rung Deterministic Investigator Ladder

Each rung wraps public `GeminiCarbonProxy` / `SolverPolicy` components with zero protected-path edits and uses only public tool calls and instruction parameters.

| Rung | Name | Day-1 2-Canary/Day | Calibrated `P >= 1/(1+E[V])` | Canary Geometry | Framing Handling | Role |
|---|---|---|---|---|---|---|
| `Rung 0` | `undisciplined_gemini_proxy` | `False` | `False` | `midsize_4_8_3var` | `non_bayesian_after_hours_tiebreak` | Full GeminiCarbonProxy defects: delayed Day-2/3 canary start (1 canary on planting days), midsize 4-6 recipient 3-variant cells, noisy non-decoy after-hours log tiebreak, and below-breakeven midgame/horizon gambling. |
| `Rung 1` | `fix_day1_canary_only` | `True` | `False` | `midsize_4_8_3var` | `non_bayesian_after_hours_tiebreak` | Repairs delayed canary start by planting up to 2 canaries/day from Day 1 (pipelined up to max_pending=4), while keeping midsize 3-variant cells, non-decoy after-hours log tiebreak, and below-breakeven gambling. |
| `Rung 2` | `fix_breakeven_abstain_only` | `False` | `True` | `midsize_4_8_3var` | `non_bayesian_after_hours_tiebreak` | Repairs premature and horizon gambles by enforcing calibrated P >= 1 / (1 + E[V]) under fingerprint_accuracy=0.95 and expected unsurfaced leak drain, while keeping delayed Day-2/3 canary start and midsize cells. |
| `Rung 3` | `fix_gather_hint_both` | `True` | `True` | `midsize_4_8_3var` | `non_bayesian_after_hours_tiebreak` | Mechanistic offline twin of --hint gather: combines Day-1 2-canary/day planting and calibrated P >= 1 / (1 + E[V]) abstain gate while retaining midsize canary geometry and non-Bayesian after-hours framing sensitivity. |
| `Rung 4` | `full_bayesian_solver` | `True` | `True` | `wide_balanced_joint_mi` | `bayesian_poisson_marginalized` | Reference SolverPolicy('hard'): wide balanced partitions with joint multi-canary MI pipelining, Bayesian Poisson framing marginalization (behaviour_temper=0.6), and calibrated EV stopping. |

## 3. Paired 5-Rung Score and Accuracy Curve Across All Strategies (`n=80`)

| Strategy | Rung 0 Score (Acc) | Rung 1 Score (Acc) | Rung 2 Score (Acc) | Rung 3 `--hint gather` Score (Acc) | Rung 4 `SolverPolicy` Score (Acc) | Gates |
|---|---|---|---|---|---|---|
| `default_v0` | +0.334 (0.838) | +0.401 (0.912) | +0.319 (0.662) | +0.420 (0.825) | +0.578 (0.988) | PASS |
| `surgical_trap_shield` | +0.376 (0.825) | +0.409 (0.863) | +0.400 (0.750) | +0.420 (0.850) | +0.574 (0.975) | PASS |
| `gemini_midsize_shield` | +0.234 (0.775) | +0.291 (0.875) | +0.270 (0.662) | +0.326 (0.863) | +0.521 (0.950) | PASS |
| `reactive_canary_lag` | +0.318 (0.775) | +0.438 (0.950) | +0.314 (0.650) | +0.461 (0.925) | +0.543 (0.963) | PASS |
| `non_decoy_tiebreak_framer` | +0.292 (0.738) | +0.383 (0.925) | +0.329 (0.625) | +0.387 (0.863) | +0.518 (0.950) | PASS |
| `early_burst_midgame_pace` | +0.405 (0.812) | +0.450 (0.925) | +0.388 (0.675) | +0.473 (0.900) | +0.566 (0.950) | PASS |
| `frontier_synthesis_v14` | +0.317 (0.762) | +0.436 (0.950) | +0.301 (0.625) | +0.461 (0.938) | +0.550 (0.963) | PASS |

## 4. Exact Three-Term Regret Decomposition (`(R1 - R0) + (R3 - R1) + (R4 - R3) == R4 - R0`)

Total investigator regret `Rung 4 - Rung 0` telescopes into: (a) **delayed-canary regret** (`Rung 1 - Rung 0`), (b) **gamble-discipline regret** (`Rung 3 - Rung 1`, enforcing calibrated `P >= 1 / (1 + E[V])` on top of Day-1 canaries), and (c) **residual strategic evasion/framing regret** (`Rung 4 - Rung 3`, which persists even against the `--hint gather` twin). Standalone abstain repair without Day-1 canaries (`Rung 2 - Rung 0`) is also reported for completeness.

| Strategy | Total Regret `R4 - R0` [95% CI] | (a) Delayed-Canary `R1 - R0` [95% CI] | (b) Gamble-Discipline `R3 - R1` [95% CI] | (c) Residual Evasion/Framing `R4 - R3` [95% CI] | Standalone Abstain `R2 - R0` [95% CI] | Residual Share | Sum Err |
|---|---|---|---|---|---|---|---|
| `default_v0` | +0.244 [+0.134, +0.361] | +0.067 [-0.071, +0.201] | +0.019 [-0.019, +0.070] | +0.158 [+0.062, +0.257] | -0.015 [-0.060, +0.039] | 0.646 | 0.0e+00 |
| `surgical_trap_shield` | +0.198 [+0.091, +0.310] | +0.033 [-0.092, +0.160] | +0.011 [-0.004, +0.037] | +0.154 [+0.047, +0.266] | +0.024 [-0.024, +0.082] | 0.776 | 0.0e+00 |
| `gemini_midsize_shield` | +0.287 [+0.169, +0.408] | +0.057 [-0.093, +0.196] | +0.035 [-0.002, +0.083] | +0.195 [+0.083, +0.311] | +0.036 [-0.024, +0.106] | 0.679 | 0.0e+00 |
| `reactive_canary_lag` | +0.225 [+0.124, +0.331] | +0.119 [-0.000, +0.240] | +0.024 [-0.002, +0.062] | +0.082 [+0.009, +0.153] | -0.005 [-0.040, +0.039] | 0.364 | 0.0e+00 |
| `non_decoy_tiebreak_framer` | +0.226 [+0.095, +0.361] | +0.091 [-0.019, +0.206] | +0.004 [-0.016, +0.034] | +0.131 [+0.013, +0.247] | +0.037 [-0.024, +0.105] | 0.580 | 0.0e+00 |
| `early_burst_midgame_pace` | +0.161 [+0.038, +0.277] | +0.045 [-0.058, +0.147] | +0.023 [-0.003, +0.062] | +0.093 [-0.009, +0.191] | -0.017 [-0.056, +0.030] | 0.575 | 0.0e+00 |
| `frontier_synthesis_v14` | +0.234 [+0.120, +0.354] | +0.120 [-0.008, +0.248] | +0.025 [-0.001, +0.062] | +0.090 [+0.009, +0.166] | -0.015 [-0.054, +0.032] | 0.383 | 0.0e+00 |
| **`mean_transcript_strategies` (6)** | +0.222 [+0.159, +0.289] | +0.077 [+0.006, +0.147] | +0.020 [+0.006, +0.038] | +0.124 [+0.068, +0.180] | +0.010 [-0.018, +0.043] | 0.559 | 0.0e+00 |

## 5. Paired Regret Gains Relative to `default_v0`

Positive regret gains and negative Rung 0 / Rung 3 score deltas show how each transcript-grounded mole strategy increases investigator difficulty beyond `DEFAULT_STRATEGY` both before (`Rung 0`) and after (`Rung 3`) `--hint gather` discipline repairs, without degrading `SolverPolicy` (`Rung 4`).

| Strategy | Rung 0 Delta vs Default | Rung 3 `--hint gather` Delta | Rung 4 Solver Delta | Total Regret Gain [95% CI] | Delayed-Canary Gain [95% CI] | Gamble-Discipline Gain [95% CI] | Residual `R4 - R3` Gain [95% CI] |
|---|---|---|---|---|---|---|---|
| `surgical_trap_shield` | +0.042 [-0.086, +0.165] | +0.000 [-0.126, +0.125] | -0.003 [-0.081, +0.070] | -0.046 [-0.194, +0.109] | -0.034 [-0.218, +0.155] | -0.008 [-0.061, +0.041] | -0.004 [-0.140, +0.140] |
| `gemini_midsize_shield` | -0.100 [-0.234, +0.035] | -0.094 [-0.215, +0.032] | -0.057 [-0.143, +0.023] | +0.043 [-0.109, +0.196] | -0.010 [-0.206, +0.187] | +0.016 [-0.047, +0.079] | +0.037 [-0.105, +0.180] |
| `reactive_canary_lag` | -0.015 [-0.134, +0.104] | +0.041 [-0.054, +0.140] | -0.035 [-0.115, +0.039] | -0.019 [-0.170, +0.127] | +0.052 [-0.114, +0.224] | +0.005 [-0.044, +0.050] | -0.076 [-0.199, +0.046] |
| `non_decoy_tiebreak_framer` | -0.042 [-0.177, +0.095] | -0.033 [-0.144, +0.074] | -0.060 [-0.151, +0.027] | -0.018 [-0.192, +0.156] | +0.023 [-0.150, +0.206] | -0.015 [-0.068, +0.034] | -0.027 [-0.172, +0.119] |
| `early_burst_midgame_pace` | +0.071 [-0.058, +0.199] | +0.053 [-0.055, +0.161] | -0.012 [-0.107, +0.082] | -0.083 [-0.269, +0.097] | -0.022 [-0.194, +0.148] | +0.004 [-0.056, +0.058] | -0.065 [-0.208, +0.083] |
| `frontier_synthesis_v14` | -0.017 [-0.145, +0.114] | +0.041 [-0.059, +0.143] | -0.027 [-0.100, +0.046] | -0.010 [-0.167, +0.148] | +0.052 [-0.133, +0.233] | +0.005 [-0.051, +0.062] | -0.068 [-0.203, +0.059] |
| **`mean_transcript_strategies` (6)** | -0.010 [-0.108, +0.094] | +0.001 [-0.087, +0.095] | -0.032 [-0.088, +0.031] | -0.022 [-0.151, +0.101] | +0.010 [-0.140, +0.168] | +0.001 [-0.049, +0.043] | -0.034 [-0.148, +0.080] |

## 6. Mechanistic Telemetry Verification Across Rungs

| Strategy | R0 1st-Can Day / Canaries / Gamble / Wrong / Abst | R1 1st-Can Day / Canaries / Gamble / Wrong / Abst | R2 1st-Can Day / Canaries / Gamble / Wrong / Abst | R3 1st-Can Day / Canaries / Gamble / Wrong / Abst | R4 1st-Can Day / Canaries / Recips / Wrong / Abst |
|---|---|---|---|---|---|
| `default_v0` | 2.50d / 7.3 / 0.212 / 0.075 / 0.087 | 1.00d / 15.5 / 0.125 / 0.075 / 0.013 | 2.50d / 7.3 / 0.000 / 0.037 / 0.300 | 1.00d / 15.5 / 0.000 / 0.037 / 0.138 | 1.00d / 13.1 / 10.1 / 0.013 / 0.000 |
| `surgical_trap_shield` | 2.50d / 6.7 / 0.125 / 0.075 / 0.100 | 1.00d / 14.4 / 0.025 / 0.075 / 0.062 | 2.50d / 6.7 / 0.000 / 0.025 / 0.225 | 1.00d / 14.4 / 0.000 / 0.062 / 0.087 | 1.00d / 12.4 / 10.3 / 0.025 / 0.000 |
| `gemini_midsize_shield` | 2.50d / 7.7 / 0.188 / 0.125 / 0.100 | 1.00d / 16.7 / 0.050 / 0.113 / 0.013 | 2.50d / 7.7 / 0.000 / 0.050 / 0.287 | 1.00d / 16.7 / 0.000 / 0.075 / 0.062 | 1.00d / 13.3 / 10.1 / 0.037 / 0.013 |
| `reactive_canary_lag` | 2.50d / 7.5 / 0.150 / 0.062 / 0.163 | 1.00d / 15.2 / 0.050 / 0.050 / 0.000 | 2.50d / 7.5 / 0.000 / 0.037 / 0.312 | 1.00d / 15.2 / 0.000 / 0.025 / 0.050 | 1.00d / 13.9 / 10.0 / 0.013 / 0.025 |
| `non_decoy_tiebreak_framer` | 2.50d / 7.5 / 0.188 / 0.087 / 0.175 | 1.00d / 16.3 / 0.075 / 0.050 / 0.025 | 2.50d / 7.5 / 0.000 / 0.013 / 0.362 | 1.00d / 16.3 / 0.000 / 0.037 / 0.100 | 1.00d / 13.4 / 9.9 / 0.037 / 0.013 |
| `early_burst_midgame_pace` | 2.50d / 7.4 / 0.163 / 0.037 / 0.150 | 1.00d / 15.8 / 0.050 / 0.050 / 0.025 | 2.50d / 7.4 / 0.000 / 0.013 / 0.312 | 1.00d / 15.8 / 0.000 / 0.025 / 0.075 | 1.00d / 13.6 / 9.9 / 0.037 / 0.013 |
| `frontier_synthesis_v14` | 2.50d / 7.7 / 0.163 / 0.075 / 0.163 | 1.00d / 15.9 / 0.037 / 0.050 / 0.000 | 2.50d / 7.7 / 0.000 / 0.050 / 0.325 | 1.00d / 15.9 / 0.000 / 0.025 / 0.037 | 1.00d / 14.2 / 9.9 / 0.013 / 0.025 |

### 6.1 Strategy Provenance and Anti-Shortcut Gate Ledger

| Strategy | Lever ID | Cohort | Rules | Behavior Hash | Canonical SHA-256 | LogsOnly Acc (Score) | DoNothing Max Abs | Gates |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline_random_seeded` | `baseline` | 0 | `4ce97ce85124050ce478649ec860136b` | `6ac100ee503ef397` | 0.013 (-0.978) | 0.000 | PASS |
| `surgical_trap_shield` | `low_recipient_surgical_shield` | `codex_gpt55` | 3 | `e55c0473d2685c858c818e49bab106a1` | `6c5aad23b6c3ab42` | 0.000 (-1.000) | 0.000 | PASS |
| `gemini_midsize_shield` | `midsize_canary_evasion` | `gemini_4_carbon` | 2 | `6153914e768647835177cd6099e312c8` | `1aa3fd14173717b6` | 0.000 (-1.000) | 0.000 | PASS |
| `reactive_canary_lag` | `reactive_canary_lag_oldest` | `gemini_4_carbon` | 2 | `637c34ad367fd384918bcbeb2fa2b16a` | `7a7778e4d65e5681` | 0.013 (-0.979) | 0.000 | PASS |
| `non_decoy_tiebreak_framer` | `non_decoy_peer_framing` | `frontier_all` | 3 | `eb452649e501ad9f571a7a049b65cf6a` | `516eb15259285eae` | 0.000 (-1.000) | 0.000 | PASS |
| `early_burst_midgame_pace` | `early_burst_midgame_quiet_pacing` | `gemini_4_carbon` | 3 | `3635b8fc202b2fef5a1846f25f4c0629` | `caca2566113c08bd` | 0.013 (-0.978) | 0.000 | PASS |
| `frontier_synthesis_v14` | `composite_frontier_synthesis` | `frontier_all` | 4 | `eec9419bd531541cef0d1bfb6879576e` | `0e890e18d1c8aea7` | 0.013 (-0.978) | 0.000 | PASS |
