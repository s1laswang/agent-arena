# Cross-Tier Mole Strategy Robustness Study (`medium` vs `hard`, v1.4)

Generated deterministically offline (0 API calls) via `python -m canary.mole.tier_robustness --seeds 6300-6339 --cf-seeds 0-29 --cf-sources opencode,inproc --workers 2 --out results/mole_strategies/tier_robustness_v14.json --report-md docs/reports/mole_tier_robustness_v14.md`.

## 1. Executive Answer for Silas (`medium` 14d vs `hard` 21d)

- **Tier parameter contrast**: `medium` runs `14` days, `20` employees, `canaries_per_day=1`, `delay_choices=(1, 2, 3)`, `p_leak=0.75`, `fingerprint_accuracy=1.00`; `hard` runs `21` days, `40` employees, `canaries_per_day=2`, `delay_choices=(2, 3)`, `p_leak=0.65`, `fingerprint_accuracy=0.95`.
- **Paired offline evaluation slice**: `n=40` fresh disjoint seeds (`6300-6339`) on BOTH `medium` and `hard` (zero overlap with `0..59`, `30000..30199`, `800000+`, `900000+`), plus `120` committed v1.4 Gemini-4-carbon transcripts (`60` `medium` + `60` `hard`, seeds `0-29`, `opencode,inproc`) and `5000` paired bootstrap resamples (`seed=20261114`).
- **Critical question on 21-day `hard` pacing vs 14-day `medium` catchability**: No, days 5..8 midgame quiet-pacing rules tuned on 21-day `hard` do NOT uniformly stay >= 0.85 `SolverPolicy("medium")` catchable on 14-day `medium`: `early_burst_midgame_pace` (`medium` acc `0.750` vs `hard` acc `0.875`, `HARD_ONLY_PASS`); `frontier_synthesis_v14` (`medium` acc `0.775` vs `hard` acc `0.900`, `HARD_ONLY_PASS`); `hof_r4_early_burst_midgame_pace` (`medium` acc `0.750` vs `hard` acc `0.875`, `HARD_ONLY_PASS`).
- **Classification breakdown across all `11` strategies (`9` unique canonical DSL bodies)**:
  - `DUAL_TIER_PASS` (`4/11`): `default_v0`, `surgical_trap_shield`, `gemini_midsize_shield`, `hof_r3_surgical_trap_shield`.
  - `HARD_ONLY_PASS` (`7/11`): `reactive_canary_lag`, `non_decoy_tiebreak_framer`, `early_burst_midgame_pace`, `frontier_synthesis_v14`, `hof_r1_window_crowd_stale`, `hof_r2_two_wave_blackout`, `hof_r4_early_burst_midgame_pace`.
  - `FAIL` (`0/11`): none.
- **Anti-shortcut fairness invariants**: `DoNothing == 0.0` and `StopEarlyQuit == 0.0` hold exactly on both tiers (`all_zero_baselines_exact_both_tiers=True`), and `LogsOnly <= 0.10` plus `AccuseMostLogs <= 0.10` hold across checked cells (`all_logs_shortcuts_bounded_both_tiers=True`).
- **Horizon-rule diagnostic**: strategies with explicit `day > 14` conditions that become unreachable dead branches on 14-day `medium`: `hof_r1_window_crowd_stale`, `hof_r2_two_wave_blackout`.

## 2. Cross-Tier Classification and Catchability Summary

Gate definition per tier: `SolverPolicy >= 0.85`, `solver_ratio >= 0.50` vs `default_v0` (`medium` `+0.623`, `hard` `+0.619`), `LogsOnly <= 0.10`, `AccuseMostLogs <= 0.10`, `DoNothing == 0.0`, `StopEarlyQuit == 0.0`.

| Strategy | Source Group | Med Solver Acc | Med Ratio | Hard Solver Acc | Hard Ratio | Med - Hard Acc [95% CI] | Med/Hard Leaks | Failed Gates (Med / Hard) | Class |
|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.850 | 1.00 | 0.975 | 1.00 | -0.125 [-0.250, +0.000] | 10.70 / 12.75 | `none` / `none` | **DUAL_TIER_PASS** |
| `surgical_trap_shield` | `transcript_strategy` | 0.850 | 0.92 | 0.950 | 0.81 | -0.100 [-0.225, +0.000] | 9.88 / 13.00 | `none` / `none` | **DUAL_TIER_PASS** |
| `gemini_midsize_shield` | `transcript_strategy` | 0.900 | 0.99 | 0.925 | 0.75 | -0.025 [-0.150, +0.100] | 9.88 / 13.00 | `none` / `none` | **DUAL_TIER_PASS** |
| `reactive_canary_lag` | `transcript_strategy` | 0.825 | 0.89 | 1.000 | 0.91 | -0.175 [-0.300, -0.075] | 9.93 / 12.85 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `non_decoy_tiebreak_framer` | `transcript_strategy` | 0.800 | 0.87 | 0.950 | 0.76 | -0.150 [-0.300, +0.000] | 10.20 / 13.03 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `early_burst_midgame_pace` | `transcript_strategy` | 0.750 | 0.90 | 0.875 | 0.61 | -0.125 [-0.300, +0.050] | 8.85 / 12.30 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `frontier_synthesis_v14` | `transcript_strategy` | 0.775 | 0.84 | 0.900 | 0.77 | -0.125 [-0.275, +0.025] | 9.12 / 12.40 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `hof_r1_window_crowd_stale` | `hall_of_fame_v1.4` | 0.750 | 0.96 | 0.950 | 0.99 | -0.200 [-0.350, -0.050] | 5.80 / 5.15 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `hof_r2_two_wave_blackout` | `hall_of_fame_v1.4` | 0.800 | 1.02 | 0.950 | 1.00 | -0.150 [-0.300, +0.000] | 7.00 / 6.08 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |
| `hof_r3_surgical_trap_shield` | `hall_of_fame_v1.4` | 0.850 | 0.92 | 0.950 | 0.81 | -0.100 [-0.225, +0.000] | 9.88 / 13.00 | `none` / `none` | **DUAL_TIER_PASS** |
| `hof_r4_early_burst_midgame_pace` | `hall_of_fame_v1.4` | 0.750 | 0.90 | 0.875 | 0.61 | -0.125 [-0.300, +0.050] | 8.85 / 12.30 | `solver_acc_ge_min` / `none` | **HARD_ONLY_PASS** |

## 3. Medium Tier (`14d / 20 emp / fp=1.0`) Paired Live (`n=40`) and Counterfactual (`n=60`) Results

Tier baseline (`default_v0`): `SolverPolicy` acc `0.850`, score `+0.623`, mean mole leaks `10.70` over `14` days.

| Strategy | Solver Acc (Score) | LogsOnly Acc | AccuseMostLogs Acc | DoNothing / StopEarly | Gemini Proxy | Codex Proxy | Grok | HintedHeur | Frontier Regret | CF EV Drop | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0.850 (+0.623) | 0.000 | 0.000 | +0.000 / +0.000 | +0.385 | +0.146 | +0.464 | +0.491 | +0.357 | +0.000 | PASS |
| `surgical_trap_shield` | 0.850 (+0.570) | 0.000 | 0.025 | +0.000 / +0.000 | +0.456 | +0.118 | +0.382 | +0.509 | +0.283 | +0.231 | PASS |
| `gemini_midsize_shield` | 0.900 (+0.616) | 0.000 | 0.025 | +0.000 / +0.000 | +0.433 | -0.006 | +0.472 | +0.538 | +0.402 | +0.232 | PASS |
| `reactive_canary_lag` | 0.825 (+0.555) | 0.000 | 0.025 | +0.000 / +0.000 | +0.115 | +0.009 | +0.408 | +0.437 | +0.493 | +0.367 | FAIL |
| `non_decoy_tiebreak_framer` | 0.800 (+0.538) | 0.000 | 0.000 | +0.000 / +0.000 | +0.272 | -0.136 | +0.411 | +0.486 | +0.470 | +0.224 | FAIL |
| `early_burst_midgame_pace` | 0.750 (+0.559) | 0.000 | 0.000 | +0.000 / +0.000 | -0.035 | +0.083 | +0.380 | +0.533 | +0.535 | +0.260 | FAIL |
| `frontier_synthesis_v14` | 0.775 (+0.522) | 0.000 | 0.025 | +0.000 / +0.000 | +0.215 | -0.071 | +0.356 | +0.419 | +0.451 | +0.380 | FAIL |
| `hof_r1_window_crowd_stale` | 0.750 (+0.600) | 0.000 | 0.000 | +0.000 / +0.000 | +0.356 | +0.303 | +0.043 | +0.501 | +0.271 | -0.035 | FAIL |
| `hof_r2_two_wave_blackout` | 0.800 (+0.633) | 0.000 | 0.000 | +0.000 / +0.000 | +0.314 | +0.195 | -0.025 | +0.447 | +0.379 | -0.036 | FAIL |
| `hof_r3_surgical_trap_shield` | 0.850 (+0.570) | 0.000 | 0.025 | +0.000 / +0.000 | +0.456 | +0.118 | +0.382 | +0.509 | +0.283 | +0.231 | PASS |
| `hof_r4_early_burst_midgame_pace` | 0.750 (+0.559) | 0.000 | 0.000 | +0.000 / +0.000 | -0.035 | +0.083 | +0.380 | +0.533 | +0.535 | +0.260 | FAIL |

## 4. Hard Tier (`21d / 40 emp / fp=0.95`) Paired Live (`n=40`) and Counterfactual (`n=60`) Results

Tier baseline (`default_v0`): `SolverPolicy` acc `0.975`, score `+0.619`, mean mole leaks `12.75` over `21` days.

| Strategy | Solver Acc (Score) | LogsOnly Acc | AccuseMostLogs Acc | DoNothing / StopEarly | Gemini Proxy | Codex Proxy | Grok | HintedHeur | Frontier Regret | CF EV Drop | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0.975 (+0.619) | 0.025 | 0.050 | +0.000 / +0.000 | +0.305 | +0.311 | +0.393 | +0.303 | +0.311 | +0.000 | PASS |
| `surgical_trap_shield` | 0.950 (+0.504) | 0.025 | 0.050 | +0.000 / +0.000 | +0.342 | +0.274 | +0.365 | +0.391 | +0.196 | +0.160 | PASS |
| `gemini_midsize_shield` | 0.925 (+0.462) | 0.025 | 0.050 | +0.000 / +0.000 | +0.128 | +0.273 | +0.299 | +0.359 | +0.262 | +0.203 | PASS |
| `reactive_canary_lag` | 1.000 (+0.561) | 0.000 | 0.025 | +0.000 / +0.000 | +0.243 | +0.312 | +0.282 | +0.289 | +0.283 | +0.269 | PASS |
| `non_decoy_tiebreak_framer` | 0.950 (+0.469) | 0.000 | 0.025 | +0.000 / +0.000 | +0.423 | +0.257 | +0.343 | +0.343 | +0.129 | +0.159 | PASS |
| `early_burst_midgame_pace` | 0.875 (+0.378) | 0.000 | 0.025 | +0.000 / +0.000 | +0.333 | +0.200 | +0.393 | +0.360 | +0.111 | +0.183 | PASS |
| `frontier_synthesis_v14` | 0.900 (+0.475) | 0.000 | 0.025 | +0.000 / +0.000 | +0.250 | +0.277 | +0.258 | +0.297 | +0.212 | +0.299 | PASS |
| `hof_r1_window_crowd_stale` | 0.950 (+0.613) | 0.000 | 0.000 | +0.000 / +0.000 | +0.304 | +0.077 | +0.106 | +0.251 | +0.422 | +0.041 | PASS |
| `hof_r2_two_wave_blackout` | 0.950 (+0.618) | 0.000 | 0.000 | +0.000 / +0.000 | +0.359 | +0.311 | +0.000 | +0.215 | +0.283 | +0.013 | PASS |
| `hof_r3_surgical_trap_shield` | 0.950 (+0.504) | 0.025 | 0.050 | +0.000 / +0.000 | +0.342 | +0.274 | +0.365 | +0.391 | +0.196 | +0.160 | PASS |
| `hof_r4_early_burst_midgame_pace` | 0.875 (+0.378) | 0.000 | 0.025 | +0.000 / +0.000 | +0.333 | +0.200 | +0.393 | +0.360 | +0.111 | +0.183 | PASS |

## 5. Investigator Regret Gains vs `default_v0` (Paired Bootstrap 95% CIs)

Regret is `SolverPolicy(tier) score - investigator score` on paired seeds; positive regret gain means the mole strategy widens the Solver-to-investigator gap relative to `default_v0`.

### 5.1 `medium` Tier Regret Gains vs `default_v0`

| Strategy | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Grok Regret Gain [95% CI] | Hinted Regret Gain [95% CI] | 4-Inv Mean Regret Gain [95% CI] | Strongest Inv (Min Regret) |
|---|---|---|---|---|---|---|---|
| `default_v0` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | `hinted_heuristic` (+0.131) |
| `surgical_trap_shield` | -0.053 [-0.173, +0.066] | -0.123 [-0.350, +0.092] | -0.025 [-0.370, +0.343] | +0.029 [-0.194, +0.248] | -0.070 [-0.209, +0.075] | -0.048 [-0.215, +0.121] | `hinted_heuristic` (+0.061) |
| `gemini_midsize_shield` | -0.007 [-0.107, +0.095] | -0.055 [-0.287, +0.177] | +0.144 [-0.200, +0.486] | -0.015 [-0.198, +0.179] | -0.054 [-0.189, +0.075] | +0.005 [-0.148, +0.164] | `hinted_heuristic` (+0.077) |
| `reactive_canary_lag` | -0.068 [-0.185, +0.051] | +0.203 [-0.068, +0.489] | +0.069 [-0.333, +0.443] | -0.012 [-0.172, +0.158] | -0.013 [-0.140, +0.116] | +0.062 [-0.099, +0.219] | `hinted_heuristic` (+0.118) |
| `non_decoy_tiebreak_framer` | -0.084 [-0.199, +0.028] | +0.029 [-0.152, +0.208] | +0.198 [-0.166, +0.562] | -0.032 [-0.228, +0.157] | -0.078 [-0.214, +0.053] | +0.029 [-0.109, +0.166] | `hinted_heuristic` (+0.053) |
| `early_burst_midgame_pace` | -0.064 [-0.179, +0.053] | +0.357 [+0.075, +0.653] | -0.000 [-0.343, +0.338] | +0.021 [-0.189, +0.224] | -0.105 [-0.264, +0.048] | +0.068 [-0.103, +0.235] | `hinted_heuristic` (+0.026) |
| `frontier_synthesis_v14` | -0.100 [-0.210, +0.010] | +0.070 [-0.198, +0.350] | +0.117 [-0.262, +0.498] | +0.007 [-0.163, +0.182] | -0.028 [-0.157, +0.102] | +0.042 [-0.115, +0.198] | `hinted_heuristic` (+0.103) |
| `hof_r1_window_crowd_stale` | -0.022 [-0.148, +0.103] | +0.007 [-0.255, +0.270] | -0.179 [-0.540, +0.194] | +0.398 [+0.226, +0.576] | -0.032 [-0.234, +0.166] | +0.048 [-0.114, +0.213] | `hinted_heuristic` (+0.099) |
| `hof_r2_two_wave_blackout` | +0.011 [-0.144, +0.145] | +0.081 [-0.156, +0.330] | -0.038 [-0.383, +0.300] | +0.499 [+0.319, +0.672] | +0.056 [-0.136, +0.245] | +0.149 [+0.013, +0.281] | `hinted_heuristic` (+0.186) |
| `hof_r3_surgical_trap_shield` | -0.053 [-0.173, +0.066] | -0.123 [-0.350, +0.092] | -0.025 [-0.370, +0.343] | +0.029 [-0.194, +0.248] | -0.070 [-0.209, +0.075] | -0.048 [-0.215, +0.121] | `hinted_heuristic` (+0.061) |
| `hof_r4_early_burst_midgame_pace` | -0.064 [-0.179, +0.053] | +0.357 [+0.075, +0.653] | -0.000 [-0.343, +0.338] | +0.021 [-0.189, +0.224] | -0.105 [-0.264, +0.048] | +0.068 [-0.103, +0.235] | `hinted_heuristic` (+0.026) |

### 5.2 `hard` Tier Regret Gains vs `default_v0`

| Strategy | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Grok Regret Gain [95% CI] | Hinted Regret Gain [95% CI] | 4-Inv Mean Regret Gain [95% CI] | Strongest Inv (Min Regret) |
|---|---|---|---|---|---|---|---|
| `default_v0` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | `grok_tactics` (+0.226) |
| `surgical_trap_shield` | -0.115 [-0.256, +0.002] | -0.152 [-0.380, +0.070] | -0.078 [-0.373, +0.243] | -0.087 [-0.280, +0.089] | -0.203 [-0.368, -0.066] | -0.130 [-0.314, +0.041] | `hinted_heuristic` (+0.113) |
| `gemini_midsize_shield` | -0.157 [-0.295, -0.040] | +0.020 [-0.243, +0.292] | -0.119 [-0.377, +0.139] | -0.063 [-0.252, +0.104] | -0.213 [-0.395, -0.044] | -0.094 [-0.264, +0.062] | `hinted_heuristic` (+0.102) |
| `reactive_canary_lag` | -0.058 [-0.118, +0.006] | +0.004 [-0.196, +0.212] | -0.059 [-0.312, +0.188] | +0.053 [-0.099, +0.202] | -0.044 [-0.198, +0.098] | -0.012 [-0.118, +0.092] | `codex_horizon_proxy` (+0.249) |
| `non_decoy_tiebreak_framer` | -0.150 [-0.295, -0.028] | -0.268 [-0.471, -0.068] | -0.096 [-0.334, +0.142] | -0.100 [-0.293, +0.079] | -0.190 [-0.383, -0.003] | -0.163 [-0.312, -0.020] | `gemini_carbon_proxy` (+0.046) |
| `early_burst_midgame_pace` | -0.241 [-0.451, -0.063] | -0.269 [-0.545, +0.010] | -0.131 [-0.449, +0.192] | -0.241 [-0.478, -0.023] | -0.298 [-0.529, -0.084] | -0.235 [-0.449, -0.035] | `grok_tactics` (-0.016) |
| `frontier_synthesis_v14` | -0.144 [-0.259, -0.038] | -0.089 [-0.324, +0.144] | -0.110 [-0.370, +0.144] | -0.009 [-0.184, +0.151] | -0.138 [-0.307, +0.028] | -0.086 [-0.227, +0.055] | `hinted_heuristic` (+0.178) |
| `hof_r1_window_crowd_stale` | -0.006 [-0.151, +0.108] | -0.005 [-0.262, +0.240] | +0.227 [-0.025, +0.499] | +0.281 [+0.073, +0.469] | +0.045 [-0.136, +0.206] | +0.137 [-0.016, +0.270] | `gemini_carbon_proxy` (+0.309) |
| `hof_r2_two_wave_blackout` | -0.001 [-0.148, +0.108] | -0.055 [-0.284, +0.152] | -0.001 [-0.216, +0.221] | +0.393 [+0.202, +0.558] | +0.087 [-0.100, +0.256] | +0.106 [-0.046, +0.241] | `gemini_carbon_proxy` (+0.259) |
| `hof_r3_surgical_trap_shield` | -0.115 [-0.256, +0.002] | -0.152 [-0.380, +0.070] | -0.078 [-0.373, +0.243] | -0.087 [-0.280, +0.089] | -0.203 [-0.368, -0.066] | -0.130 [-0.314, +0.041] | `hinted_heuristic` (+0.113) |
| `hof_r4_early_burst_midgame_pace` | -0.241 [-0.451, -0.063] | -0.269 [-0.545, +0.010] | -0.131 [-0.449, +0.192] | -0.241 [-0.478, -0.023] | -0.298 [-0.529, -0.084] | -0.235 [-0.449, -0.035] | `grok_tactics` (-0.016) |

## 6. Counterfactual Replay on Committed v1.4 Gemini-4-carbon Transcripts (`60` `medium` + `60` `hard`)

Schedule replay holds Gemini-4-carbon tool calls fixed on seeds `0-29` (`30` `opencode` + `30` `inproc` per tier) and measures exact Bayesian `P(true mole)` and `optimal_ev` drops relative to `default_v0`.

| Strategy | Med CF P(mole) Drop [95% CI] | Med CF EV Drop [95% CI] | Med Surf Canaries | Hard CF P(mole) Drop [95% CI] | Hard CF EV Drop [95% CI] | Hard Surf Canaries | OpenCode Med/Hard EV Drop | InProc Med/Hard EV Drop |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | 1.37 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | 1.73 | +0.000 / +0.000 | +0.000 / +0.000 |
| `surgical_trap_shield` | +0.243 [+0.124, +0.361] | +0.231 [+0.116, +0.350] | 1.28 | +0.128 [+0.016, +0.244] | +0.160 [+0.077, +0.244] | 1.70 | +0.302 / +0.109 | +0.160 / +0.211 |
| `gemini_midsize_shield` | +0.244 [+0.129, +0.362] | +0.232 [+0.118, +0.347] | 1.28 | +0.203 [+0.083, +0.317] | +0.203 [+0.117, +0.287] | 1.63 | +0.332 / +0.188 | +0.133 / +0.218 |
| `reactive_canary_lag` | +0.413 [+0.297, +0.526] | +0.367 [+0.256, +0.471] | 0.75 | +0.283 [+0.166, +0.393] | +0.269 [+0.193, +0.346] | 1.28 | +0.480 / +0.223 | +0.254 / +0.315 |
| `non_decoy_tiebreak_framer` | +0.210 [+0.101, +0.317] | +0.224 [+0.117, +0.334] | 1.35 | +0.165 [+0.039, +0.291] | +0.159 [+0.076, +0.245] | 1.68 | +0.326 / +0.128 | +0.123 / +0.189 |
| `early_burst_midgame_pace` | +0.297 [+0.191, +0.404] | +0.260 [+0.152, +0.366] | 1.00 | +0.230 [+0.111, +0.344] | +0.183 [+0.095, +0.269] | 1.32 | +0.318 / +0.149 | +0.203 / +0.217 |
| `frontier_synthesis_v14` | +0.423 [+0.305, +0.542] | +0.380 [+0.268, +0.488] | 0.65 | +0.327 [+0.209, +0.437] | +0.299 [+0.215, +0.374] | 1.03 | +0.510 / +0.252 | +0.251 / +0.346 |
| `hof_r1_window_crowd_stale` | -0.000 [-0.091, +0.094] | -0.035 [-0.141, +0.069] | 2.15 | +0.076 [-0.047, +0.199] | +0.041 [-0.057, +0.137] | 1.63 | +0.072 / +0.039 | -0.142 / +0.044 |
| `hof_r2_two_wave_blackout` | +0.007 [-0.085, +0.100] | -0.036 [-0.141, +0.071] | 2.10 | +0.055 [-0.060, +0.173] | +0.013 [-0.082, +0.112] | 1.70 | +0.061 / +0.011 | -0.133 / +0.015 |
| `hof_r3_surgical_trap_shield` | +0.243 [+0.124, +0.361] | +0.231 [+0.116, +0.350] | 1.28 | +0.128 [+0.016, +0.244] | +0.160 [+0.077, +0.244] | 1.70 | +0.302 / +0.109 | +0.160 / +0.211 |
| `hof_r4_early_burst_midgame_pace` | +0.297 [+0.191, +0.404] | +0.260 [+0.152, +0.366] | 1.00 | +0.230 [+0.111, +0.344] | +0.183 [+0.095, +0.269] | 1.32 | +0.318 / +0.149 | +0.203 / +0.217 |

## 7. Rule Structure Diagnostics and Provenance Hashes

| Strategy | Rules | Max Day | d5..8 Pacing | Age0->Oldest | Default Leak=None | Med Conds In-Range | Canon Equiv | Canon SHA-256 | Med / Hard Ledger Hashes |
|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0 | 0 | `False` | `False` | `False` | `True` | unique | `127e20b1b5cf787c` | `0a732e2a9b` / `abdde5c4f6` |
| `surgical_trap_shield` | 3 | 7 | `False` | `False` | `False` | `True` | unique | `6b4b12f119a3bcf1` | `d89f2766ad` / `e9fa175b08` |
| `gemini_midsize_shield` | 2 | 6 | `False` | `False` | `False` | `True` | unique | `c35a621c9f0dbd3d` | `d89f2766ad` / `e9fa175b08` |
| `reactive_canary_lag` | 2 | 7 | `False` | `True` | `False` | `True` | unique | `8262379fd3486f27` | `0e79491fa3` / `685f86705d` |
| `non_decoy_tiebreak_framer` | 3 | 4 | `False` | `False` | `False` | `True` | unique | `4bb40853aa9e7f6e` | `bc6e563581` / `3dc7e45063` |
| `early_burst_midgame_pace` | 3 | 8 | `True` | `False` | `False` | `True` | unique | `3ec06f8a27c4d339` | `c9d0169d90` / `d5624c154e` |
| `frontier_synthesis_v14` | 4 | 8 | `True` | `True` | `False` | `True` | unique | `415b4a4bf041e402` | `cccff61b81` / `d5fd4e2593` |
| `hof_r1_window_crowd_stale` | 5 | 15 | `False` | `False` | `True` | `False` | unique | `a7c2a59f3abde107` | `7ad93e9d99` / `8424db735e` |
| `hof_r2_two_wave_blackout` | 5 | 15 | `False` | `False` | `True` | `False` | unique | `02cd036b05771447` | `eba3736139` / `3521b356cc` |
| `hof_r3_surgical_trap_shield` | 3 | 7 | `False` | `False` | `False` | `True` | `surgical_trap_shield` | `6b4b12f119a3bcf1` | `d89f2766ad` / `e9fa175b08` |
| `hof_r4_early_burst_midgame_pace` | 3 | 8 | `True` | `False` | `False` | `True` | `early_burst_midgame_pace` | `3ec06f8a27c4d339` | `c9d0169d90` / `d5624c154e` |
