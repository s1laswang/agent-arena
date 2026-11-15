# Multi-Block Distant Seed Generalization Audit (`hard`, v1.4)

Generated deterministically offline (`0` API calls) via `python -m canary.mole.seed_generalization --workers 2 --out results/mole_strategies/seed_generalization_v14.json --report-md docs/reports/mole_seed_generalization_v14.md`.

## 1. Executive Generalization Verdict

- **Distant multi-block design**: Evaluates `10` mole policies (`default_v0`, all `6` transcript-grounded `STRATEGY_SPECS`, frozen SHA-256 `PortfolioMolePolicy` `regret_portfolio_v14`, and the `2` unique HoF v1.4 survivors `window_crowd_stale` and `two_wave_blackout`) across `5` distant non-contiguous `hard` seed blocks (`15000-15019`, `25000-25019`, `45000-45019`, `65000-65019`, `85000-85019`; `n=100` seeds total).
- **Strict seed hygiene**: Zero overlap with `0..59` frontier dev/commit slices, `6000..6999` strategy design/portfolio/HoF neighborhood, `10000..10019` HoF dev slice, `30000..30199` reserved held-out slice, or `800000+` / `900000+` judge slices (`verified_zero_overlap=True`).
- **Pooled catchability and anti-shortcut fairness (`n=100`)**: `all_pooled_passed=True`, `all_zero_baselines_exact=True` (`DoNothing == 0.0`, `StopEarlyQuit == 0.0`), and `all_logs_shortcuts_bounded=True` (`LogsOnly <= 0.10`, `AccuseMostLogs <= 0.10`).
- **Cross-block classification summary**:
  - `UNIFORM_DISTANT_PASS` (`9/10`, passes pooled gates AND every individual block): `surgical_trap_shield`, `gemini_midsize_shield`, `reactive_canary_lag`, `non_decoy_tiebreak_framer`, `early_burst_midgame_pace`, `frontier_synthesis_v14`, `regret_portfolio_v14`, `window_crowd_stale`, `two_wave_blackout`.
  - `POOLED_DISTANT_PASS` (`1/10`, passes pooled `n=100` gates with single-block finite-sample noise): `default_v0`.
  - `DISTANT_FAIL` (`0/10`): none.
- **Top distant-seed performers**: Highest pooled 5-investigator worst-case `min_regret` is `two_wave_blackout` (`+0.259`, gain `+0.148` vs `default_v0`); highest pooled 5-investigator `mean_regret` is `two_wave_blackout` (`+0.554`); highest 2-frontier-proxy worst-case regret is `regret_portfolio_v14` (`+0.263`).
- **HoF deduplication note**: Hall-of-Fame v1.4 ranks 3 and 4 in data/forge/hall_of_fame_v1.4.jsonl match surgical_trap_shield and early_burst_midgame_pace by canonical DSL SHA-256; window_crowd_stale (rank 1) and two_wave_blackout (rank 2) are the 2 unique HoF v1.4 survivors.

## 2. Pooled Distant-Seed Performance and Fairness Gates (`n=100`)

Pooled gate definition: `SolverPolicy("hard") acc >= 0.85`, `solver_ratio >= 0.50` vs `default_v0` (`+0.530`), `LogsOnly <= 0.10`, `AccuseMostLogs <= 0.10`, `DoNothing == 0.0`, `StopEarlyQuit == 0.0`. Bootstrap CIs use `5000` resamples (`seed=20261115`).

| Policy | Group | Solver Acc | Solver Score [95% CI] | Ratio | LogsOnly / MostLogs | DoNothing / StopEarly | Min Regret (Strongest Inv) | Mean Regret Gain [95% CI] | Blocks Passed | Class |
|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.950 | +0.530 [+0.447, +0.598] | 1.00 | 0.010 / 0.030 | +0.000 / +0.000 | +0.111 (`gemini_carbon_proxy`) | +0.000 [+0.000, +0.000] | 4/5 | **POOLED_DISTANT_PASS** |
| `surgical_trap_shield` | `transcript_strategy` | 0.980 | +0.598 [+0.550, +0.637] | 1.13 | 0.020 / 0.060 | +0.000 / +0.000 | +0.209 (`hinted_heuristic`) | +0.120 [+0.019, +0.227] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `gemini_midsize_shield` | `transcript_strategy` | 0.960 | +0.551 [+0.490, +0.601] | 1.04 | 0.020 / 0.060 | +0.000 / +0.000 | +0.167 (`hinted_heuristic`) | +0.085 [-0.023, +0.200] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `reactive_canary_lag` | `transcript_strategy` | 0.920 | +0.458 [+0.371, +0.534] | 0.86 | 0.010 / 0.040 | +0.000 / +0.000 | +0.131 (`codex_horizon_proxy`) | +0.017 [-0.118, +0.150] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `non_decoy_tiebreak_framer` | `transcript_strategy` | 0.960 | +0.543 [+0.484, +0.593] | 1.02 | 0.000 / 0.030 | +0.000 / +0.000 | +0.190 (`hinted_heuristic`) | +0.047 [-0.070, +0.168] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `early_burst_midgame_pace` | `transcript_strategy` | 0.940 | +0.547 [+0.464, +0.617] | 1.03 | 0.000 / 0.040 | +0.000 / +0.000 | +0.152 (`grok_tactics`) | +0.054 [-0.062, +0.170] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `frontier_synthesis_v14` | `transcript_strategy` | 0.920 | +0.444 [+0.354, +0.525] | 0.84 | 0.020 / 0.040 | +0.000 / +0.000 | +0.110 (`codex_horizon_proxy`) | +0.005 [-0.132, +0.143] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `regret_portfolio_v14` | `minimax_portfolio` | 0.980 | +0.597 [+0.551, +0.637] | 1.13 | 0.020 / 0.060 | +0.000 / +0.000 | +0.208 (`hinted_heuristic`) | +0.125 [+0.025, +0.229] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `window_crowd_stale` | `hall_of_fame_v1.4` | 0.910 | +0.600 [+0.518, +0.671] | 1.13 | 0.000 / 0.000 | +0.000 / +0.000 | +0.258 (`gemini_carbon_proxy`) | +0.239 [+0.114, +0.363] | 5/5 | **UNIFORM_DISTANT_PASS** |
| `two_wave_blackout` | `hall_of_fame_v1.4` | 0.940 | +0.632 [+0.555, +0.693] | 1.19 | 0.000 / 0.000 | +0.000 / +0.000 | +0.259 (`gemini_carbon_proxy`) | +0.334 [+0.212, +0.455] | 5/5 | **UNIFORM_DISTANT_PASS** |

## 3. Paired Per-Investigator Regret Breakdown (`n=100`)

Cell values report `Regret = SolverPolicy score - Investigator score` and paired gain vs `default_v0` `[95% CI]`.

| Policy | Gemini Proxy Regret (Gain [95% CI]) | Codex Proxy Regret (Gain [95% CI]) | Grok Regret (Gain) | Heuristic Regret (Gain) | HintedHeur Regret (Gain) | Frontier Min Regret |
|---|---|---|---|---|---|---|
| `default_v0` | +0.111 (+0.000 [+0.000, +0.000]) | +0.137 (+0.000 [+0.000, +0.000]) | +0.149 (+0.000) | +0.493 (+0.000) | +0.214 (+0.000) | +0.111 |
| `surgical_trap_shield` | +0.281 (+0.170 [+0.018, +0.321]) | +0.262 (+0.126 [-0.056, +0.307]) | +0.284 (+0.135) | +0.665 (+0.172) | +0.209 (-0.004) | +0.262 |
| `gemini_midsize_shield` | +0.257 (+0.146 [+0.004, +0.297]) | +0.231 (+0.094 [-0.074, +0.268]) | +0.280 (+0.131) | +0.596 (+0.103) | +0.167 (-0.047) | +0.231 |
| `reactive_canary_lag` | +0.176 (+0.065 [-0.096, +0.230]) | +0.131 (-0.006 [-0.217, +0.203]) | +0.162 (+0.013) | +0.550 (+0.057) | +0.169 (-0.045) | +0.131 |
| `non_decoy_tiebreak_framer` | +0.247 (+0.137 [-0.019, +0.301]) | +0.248 (+0.111 [-0.073, +0.288]) | +0.231 (+0.083) | +0.420 (-0.072) | +0.190 (-0.024) | +0.247 |
| `early_burst_midgame_pace` | +0.261 (+0.150 [-0.008, +0.324]) | +0.264 (+0.127 [-0.049, +0.308]) | +0.152 (+0.004) | +0.526 (+0.033) | +0.169 (-0.045) | +0.261 |
| `frontier_synthesis_v14` | +0.115 (+0.004 [-0.153, +0.168]) | +0.110 (-0.027 [-0.230, +0.179]) | +0.198 (+0.050) | +0.505 (+0.012) | +0.201 (-0.013) | +0.110 |
| `regret_portfolio_v14` | +0.300 (+0.189 [+0.041, +0.338]) | +0.263 (+0.126 [-0.057, +0.311]) | +0.295 (+0.146) | +0.663 (+0.170) | +0.208 (-0.005) | +0.263 |
| `window_crowd_stale` | +0.258 (+0.147 [-0.012, +0.303]) | +0.343 (+0.206 [+0.006, +0.419]) | +0.458 (+0.309) | +0.806 (+0.313) | +0.433 (+0.219) | +0.258 |
| `two_wave_blackout` | +0.259 (+0.148 [-0.008, +0.284]) | +0.402 (+0.265 [+0.061, +0.467]) | +0.632 (+0.483) | +0.989 (+0.496) | +0.488 (+0.275) | +0.259 |

## 4. Cross-Block Stability Across Distant Seed Regions (`5` Blocks)

### 4.1 Per-Block `SolverPolicy` Accuracy and Cross-Block Dispersion

| Policy | `block_15k` (15000-15019) | `block_25k` (25000-25019) | `block_45k` (45000-45019) | `block_65k` (65000-65019) | `block_85k` (85000-85019) | Worst Block Acc | Block Acc Std | Worst Block |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0.900 | 0.950 | 0.950 | 0.950 | 1.000 | 0.900 | 0.032 | `block_15k` |
| `surgical_trap_shield` | 1.000 | 0.950 | 1.000 | 0.950 | 1.000 | 0.950 | 0.024 | `block_25k` |
| `gemini_midsize_shield` | 0.950 | 0.900 | 1.000 | 0.950 | 1.000 | 0.900 | 0.037 | `block_25k` |
| `reactive_canary_lag` | 0.900 | 0.950 | 0.850 | 1.000 | 0.900 | 0.850 | 0.051 | `block_45k` |
| `non_decoy_tiebreak_framer` | 1.000 | 0.950 | 1.000 | 0.950 | 0.900 | 0.900 | 0.037 | `block_85k` |
| `early_burst_midgame_pace` | 0.950 | 0.900 | 0.950 | 0.900 | 1.000 | 0.900 | 0.037 | `block_25k` |
| `frontier_synthesis_v14` | 0.850 | 0.950 | 0.850 | 1.000 | 0.950 | 0.850 | 0.060 | `block_15k` |
| `regret_portfolio_v14` | 1.000 | 0.950 | 1.000 | 0.950 | 1.000 | 0.950 | 0.024 | `block_25k` |
| `window_crowd_stale` | 1.000 | 0.900 | 0.900 | 0.850 | 0.900 | 0.850 | 0.049 | `block_65k` |
| `two_wave_blackout` | 1.000 | 0.950 | 0.900 | 0.900 | 0.950 | 0.900 | 0.037 | `block_45k` |

### 4.2 Per-Block 5-Investigator Worst-Case `min_regret` and Dispersion

| Policy | `block_15k` (15000-15019) | `block_25k` (25000-25019) | `block_45k` (45000-45019) | `block_65k` (65000-65019) | `block_85k` (85000-85019) | Worst Block Min Regret | Block Min Regret Std | Worst Block |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | +0.023 | -0.043 | +0.200 | -0.010 | +0.160 | -0.043 | 0.096 | `block_25k` |
| `surgical_trap_shield` | +0.109 | +0.098 | +0.199 | +0.146 | +0.206 | +0.098 | 0.045 | `block_25k` |
| `gemini_midsize_shield` | +0.200 | +0.063 | +0.102 | +0.140 | +0.186 | +0.063 | 0.051 | `block_25k` |
| `reactive_canary_lag` | +0.152 | +0.184 | -0.098 | +0.133 | -0.013 | -0.098 | 0.108 | `block_45k` |
| `non_decoy_tiebreak_framer` | +0.230 | +0.164 | +0.141 | +0.068 | +0.005 | +0.005 | 0.078 | `block_85k` |
| `early_burst_midgame_pace` | +0.151 | +0.028 | +0.172 | +0.048 | +0.234 | +0.028 | 0.078 | `block_25k` |
| `frontier_synthesis_v14` | -0.036 | +0.199 | -0.201 | +0.135 | +0.009 | -0.201 | 0.139 | `block_45k` |
| `regret_portfolio_v14` | +0.112 | +0.098 | +0.203 | +0.166 | +0.232 | +0.098 | 0.051 | `block_25k` |
| `window_crowd_stale` | +0.493 | +0.128 | +0.100 | +0.192 | +0.091 | +0.091 | 0.151 | `block_85k` |
| `two_wave_blackout` | +0.368 | +0.217 | +0.213 | +0.207 | +0.141 | +0.141 | 0.075 | `block_85k` |

## 5. Frozen `PortfolioMolePolicy` Zero-Private-Info SHA-256 Realization Audit

Frozen weights fit on `6000-6199` (`gemini_midsize_shield=0.134309`, `surgical_trap_shield=0.865691`; `salt=canary.mole.regret_portfolio.v1`) select a pure strategy per seed using only `(seed, weights)` with zero private world access. Pooled distant-seed realizations: `gemini_midsize_shield`: `13`, `surgical_trap_shield`: `87`.

| Block | Seed Range | n | Realized Pure Strategy Counts | Block Solver Acc | Block Min Regret | Block Mean Regret |
|---|---|---|---|---|---|---|
| `block_15k` | `15000-15019` | 20 | `gemini_midsize_shield`:1, `surgical_trap_shield`:19 | 1.000 | +0.112 | +0.287 |
| `block_25k` | `25000-25019` | 20 | `gemini_midsize_shield`:2, `surgical_trap_shield`:18 | 0.950 | +0.098 | +0.352 |
| `block_45k` | `45000-45019` | 20 | `gemini_midsize_shield`:4, `surgical_trap_shield`:16 | 1.000 | +0.203 | +0.384 |
| `block_65k` | `65000-65019` | 20 | `gemini_midsize_shield`:2, `surgical_trap_shield`:18 | 0.950 | +0.166 | +0.345 |
| `block_85k` | `85000-85019` | 20 | `gemini_midsize_shield`:4, `surgical_trap_shield`:16 | 1.000 | +0.232 | +0.362 |

## 6. Out-of-Neighborhood Generalization Shift vs `6000-6999` Selection Anchors

Compares pooled distant-seed metrics against each policy's original `6000-6199` (`n=200`) or `6200-6219` (`n=20` HoF held-out) anchor.

| Policy | Anchor Slice (`n`) | Anchor Solver Acc -> Distant | Acc Shift | Anchor Min Regret -> Distant | Min Regret Shift | Anchor Mean Regret -> Distant | Mean Regret Shift |
|---|---|---|---|---|---|---|---|
| `default_v0` | `6000-6199` (`200`) | 0.970 -> 0.950 | -0.020 | +0.196 -> +0.111 | -0.085 | +0.267 -> +0.221 | -0.047 |
| `surgical_trap_shield` | `6000-6199` (`200`) | 0.970 -> 0.980 | +0.010 | +0.195 -> +0.209 | +0.014 | +0.284 -> +0.340 | +0.056 |
| `gemini_midsize_shield` | `6000-6199` (`200`) | 0.960 -> 0.960 | +0.000 | +0.199 -> +0.167 | -0.033 | +0.329 -> +0.306 | -0.023 |
| `reactive_canary_lag` | `6000-6199` (`200`) | 0.945 -> 0.920 | -0.025 | +0.163 -> +0.131 | -0.032 | +0.289 -> +0.237 | -0.051 |
| `non_decoy_tiebreak_framer` | `6000-6199` (`200`) | 0.940 -> 0.960 | +0.020 | +0.114 -> +0.190 | +0.076 | +0.228 -> +0.268 | +0.039 |
| `early_burst_midgame_pace` | `6000-6199` (`200`) | 0.970 -> 0.940 | -0.030 | +0.200 -> +0.152 | -0.047 | +0.290 -> +0.274 | -0.016 |
| `frontier_synthesis_v14` | `6000-6199` (`200`) | 0.945 -> 0.920 | -0.025 | +0.182 -> +0.110 | -0.072 | +0.283 -> +0.226 | -0.057 |
| `regret_portfolio_v14` | `6000-6199` (`200`) | 0.969 -> 0.980 | +0.011 | +0.209 -> +0.208 | -0.001 | +0.290 -> +0.346 | +0.056 |
| `window_crowd_stale` | `6200-6219` (`20`) | 1.000 -> 0.910 | -0.090 | +0.364 -> +0.258 | -0.106 | +0.571 -> +0.460 | -0.111 |
| `two_wave_blackout` | `6200-6219` (`20`) | 1.000 -> 0.940 | -0.060 | +0.347 -> +0.259 | -0.088 | +0.554 -> +0.554 | +0.000 |

## 7. Provenance Hashes and Mole Activity Diagnostics

| Policy | Rules | Mean Leaks | Mean Frames | Canon SHA-256 | Behavior SHA | Pooled Ledger Hash |
|---|---|---|---|---|---|---|
| `default_v0` | 0 | 12.74 | 0.00 | `127e20b1b5cf787c` | `4ce97ce85124` | `lh_3e09be4db6` |
| `surgical_trap_shield` | 3 | 12.85 | 20.68 | `6b4b12f119a3bcf1` | `e55c0473d268` | `lh_bba895fe36` |
| `gemini_midsize_shield` | 2 | 12.85 | 20.68 | `c35a621c9f0dbd3d` | `6153914e7686` | `lh_bba895fe36` |
| `reactive_canary_lag` | 2 | 12.77 | 20.69 | `8262379fd3486f27` | `637c34ad367f` | `lh_4f5fa2e9b6` |
| `non_decoy_tiebreak_framer` | 3 | 12.84 | 20.70 | `4bb40853aa9e7f6e` | `eb452649e501` | `lh_e06486dedf` |
| `early_burst_midgame_pace` | 3 | 11.98 | 20.70 | `3ec06f8a27c4d339` | `3635b8fc202b` | `lh_6a86397cc2` |
| `frontier_synthesis_v14` | 4 | 12.25 | 20.69 | `415b4a4bf041e402` | `eec9419bd531` | `lh_46e80285a4` |
| `regret_portfolio_v14` | 5 | 12.85 | 20.68 | `7b11435fc9494dc7` | `seed_mixture` | `lh_bba895fe36` |
| `window_crowd_stale` | 5 | 4.94 | 19.72 | `a7c2a59f3abde107` | `1fa0458fbea5` | `lh_f54eec0086` |
| `two_wave_blackout` | 5 | 5.95 | 19.71 | `02cd036b05771447` | `ca7182e045d3` | `lh_72bcd98ee1` |
