# Cross-Model Mole Strategy Transfer Evaluation (Gemini-4-Carbon vs Codex/GPT-5.5)

Generated strictly offline (`api_calls=0`) via `python -m canary.mole.transfer_eval --out results/mole_strategies/cross_model_transfer.json --report-out docs/reports/mole_cross_model_transfer.md`.

## 1. Executive Summary and Verification Gates

- **Catalog evaluated**: 11 strategy entries (1 `DEFAULT_STRATEGY` baseline + 6 transcript-grounded strategies from `canary/mole/strategies.py` + 4 entries from `data/forge/hall_of_fame_v1.4.jsonl`), spanning **9** distinct behavioral policies (`hof_v14_r3` is an exact behavioral alias of `surgical_trap_shield`; `hof_v14_r4` is an exact behavioral alias of `early_burst_midgame_pace`).
- **Read-only counterfactual transcript replay (`n=99`)**: `99/99` raw frontier transcripts (`60` v1.4 Gemini-4-carbon Hard across OpenCode MCP + In-Proc; `39` v1.3 Codex/GPT-5.5 across Hard `n=19` and Medium `n=20`) reconstructed cleanly into public-tool schedules and matched `100%` of committed `audit_episode` posteriors under `DEFAULT_STRATEGY`.
- **Fresh-seed v1.4 Hard transfer matrix (`seeds 6200-6229`, `n=30`, `--workers 2`)**: All `11/11` strategy entries pass catchability and fairness gates (`all_gates_passed=True`, minimum `solver_acc=0.900 >= 0.85`, maximum `logs_only_acc=0.000 <= 0.10`, seed hygiene blocking `0-59`, `30000-30199`, `800000+`).
- **Specialist vs Generalist transfer**: Unique specialists (`n=4`) achieve mean in-domain proxy regret gain `+0.232` vs out-of-domain `+0.206` (mean 5-investigator minimax regret `0.202`), whereas unique generalists (`n=4`) achieve mean 5-investigator minimax regret `0.186` and mean worst-family counterfactual EV drop `+0.022` vs specialists `+0.095`.

## 2. Strategy Catalog and Behavioral Deduplication

| Strategy Key | Source | Role | Target Family | Rules | Behavior Hash (v1.4 Hard) | HOF Survivor / Alias |
|---|---|---|---|---|---|---|
| `default` | `baseline` | `baseline` | `none` | 0 | `4ce97ce85124` | canonical |
| `surgical_trap_shield` | `transcript_strategies` | `specialist` | `codex_gpt55` | 3 | `e55c0473d268` | canonical |
| `gemini_midsize_shield` | `transcript_strategies` | `specialist` | `gemini_4_carbon` | 2 | `6153914e7686` | canonical |
| `reactive_canary_lag` | `transcript_strategies` | `specialist` | `gemini_4_carbon` | 2 | `637c34ad367f` | canonical |
| `non_decoy_tiebreak_framer` | `transcript_strategies` | `generalist` | `frontier_all` | 3 | `eb452649e501` | canonical |
| `early_burst_midgame_pace` | `transcript_strategies` | `specialist` | `gemini_4_carbon` | 3 | `3635b8fc202b` | canonical |
| `frontier_synthesis_v14` | `transcript_strategies` | `generalist` | `frontier_all` | 4 | `eec9419bd531` | canonical |
| `hof_v14_r1` | `hall_of_fame_v1.4` | `generalist` | `frontier_all` | 5 | `1fa0458fbea5` | survivor=window_crowd_stale |
| `hof_v14_r2` | `hall_of_fame_v1.4` | `generalist` | `frontier_all` | 5 | `ca7182e045d3` | survivor=two_wave_blackout |
| `hof_v14_r3` | `hall_of_fame_v1.4` | `specialist` | `codex_gpt55` | 3 | `e55c0473d268` | survivor=surgical_trap_shield, alias_of=surgical_trap_shield |
| `hof_v14_r4` | `hall_of_fame_v1.4` | `specialist` | `gemini_4_carbon` | 3 | `3635b8fc202b` | survivor=early_burst_midgame_pace, alias_of=early_burst_midgame_pace |

## 3. Part (a): Read-Only Counterfactual Replay Across Model Families

### 3.1 Reconstructed Frontier Transcript Cohorts

| Cohort ID | Ruleset | Tier | Family | Harness | Episodes | Seeds | Raw Transcript Verified | Baseline Audit Parity |
|---|---|---|---|---|---|---|---|---|
| `v14_gemini_opencode_hard` | `v1.4` | `hard` | `gemini_4_carbon` | `opencode_mcp` | 30 | `0..29` | 30/30 | 30/30 |
| `v14_gemini_inproc_hard` | `v1.4` | `hard` | `gemini_4_carbon` | `gemini_inproc` | 30 | `0..29` | 30/30 | 30/30 |
| `v13_codex_hard` | `v1.3` | `hard` | `codex_gpt55` | `codex_mcp` | 11 | `0..10` | 11/11 | 11/11 |
| `v13_gpt55_hard` | `v1.3` | `hard` | `codex_gpt55` | `openai_inproc` | 8 | `0..7` | 8/8 | 8/8 |
| `v13_codex_medium` | `v1.3` | `medium` | `codex_gpt55` | `codex_mcp` | 11 | `0..10` | 11/11 | 11/11 |
| `v13_gpt55_medium` | `v1.3` | `medium` | `codex_gpt55` | `openai_inproc` | 9 | `0..8` | 9/9 | 9/9 |

### 3.2 Cross-Family Counterfactual Optimal-EV Drop vs `DEFAULT_STRATEGY` (Paired Bootstrap 95% CI)

| Strategy | Role (Target) | v1.4 Gemini Hard EV Drop (n=60) | v1.3 Codex/GPT-5.5 Hard EV Drop (n=19) | v1.3 Codex/GPT-5.5 Med EV Drop (n=20) | v1.3 Codex/GPT-5.5 All EV Drop (n=39) | Worst-Family EV Drop |
|---|---|---|---|---|---|---|
| `default` | `baseline` (`none`) | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 |
| `surgical_trap_shield` | `specialist` (`codex_gpt55`) | +0.160 [+0.077, +0.246] | +0.034 [-0.158, +0.209] | +0.157 [-0.071, +0.410] | +0.097 [-0.043, +0.250] | +0.097 |
| `gemini_midsize_shield` | `specialist` (`gemini_4_carbon`) | +0.203 [+0.118, +0.289] | +0.030 [-0.155, +0.212] | +0.125 [-0.094, +0.384] | +0.079 [-0.062, +0.233] | +0.079 |
| `reactive_canary_lag` | `specialist` (`gemini_4_carbon`) | +0.269 [+0.192, +0.346] | -0.007 [-0.216, +0.193] | +0.187 [-0.019, +0.409] | +0.092 [-0.040, +0.245] | +0.092 |
| `non_decoy_tiebreak_framer` | `generalist` (`frontier_all`) | +0.159 [+0.071, +0.244] | -0.061 [-0.229, +0.092] | +0.088 [-0.112, +0.299] | +0.015 [-0.106, +0.150] | +0.015 |
| `early_burst_midgame_pace` | `specialist` (`gemini_4_carbon`) | +0.183 [+0.096, +0.271] | -0.029 [-0.220, +0.147] | +0.240 [+0.044, +0.456] | +0.110 [-0.026, +0.254] | +0.110 |
| `frontier_synthesis_v14` | `generalist` (`frontier_all`) | +0.299 [+0.221, +0.379] | +0.047 [-0.164, +0.256] | +0.236 [+0.063, +0.421] | +0.144 [+0.010, +0.279] | +0.144 |
| `hof_v14_r1` | `generalist` (`frontier_all`) | +0.041 [-0.053, +0.144] | -0.055 [-0.196, +0.095] | -0.019 [-0.177, +0.147] | -0.036 [-0.143, +0.073] | -0.036 |
| `hof_v14_r2` | `generalist` (`frontier_all`) | +0.013 [-0.079, +0.118] | +0.022 [-0.138, +0.192] | -0.093 [-0.271, +0.091] | -0.036 [-0.154, +0.083] | -0.036 |
| `hof_v14_r3` | `specialist` (`codex_gpt55`) | +0.160 [+0.077, +0.246] | +0.034 [-0.158, +0.209] | +0.157 [-0.071, +0.410] | +0.097 [-0.043, +0.250] | +0.097 |
| `hof_v14_r4` | `specialist` (`gemini_4_carbon`) | +0.183 [+0.096, +0.271] | -0.029 [-0.220, +0.147] | +0.240 [+0.044, +0.456] | +0.110 [-0.026, +0.254] | +0.110 |

### 3.3 Counterfactual Posterior `P(true mole)` Drop and Surfaced Canary Delta

| Strategy | Gemini Hard `P(mole)` Drop (n=60) | Gemini Surfaced Canaries (Delta) | Codex/GPT-5.5 All `P(mole)` Drop (n=39) | Codex/GPT-5.5 Surfaced Canaries (Delta) | All-Frontier EV Drop (n=99) |
|---|---|---|---|---|---|
| `default` | +0.000 [+0.000, +0.000] | 1.73 (+0.00) | +0.000 [+0.000, +0.000] | 1.51 (+0.00) | +0.000 [+0.000, +0.000] |
| `surgical_trap_shield` | +0.128 [+0.019, +0.238] | 1.70 (-0.03) | +0.111 [-0.027, +0.272] | 1.67 (+0.15) | +0.135 [+0.055, +0.219] |
| `gemini_midsize_shield` | +0.203 [+0.093, +0.322] | 1.63 (-0.10) | +0.068 [-0.073, +0.217] | 1.74 (+0.23) | +0.154 [+0.076, +0.235] |
| `reactive_canary_lag` | +0.283 [+0.174, +0.398] | 1.28 (-0.45) | +0.045 [-0.095, +0.203] | 1.54 (+0.03) | +0.200 [+0.123, +0.275] |
| `non_decoy_tiebreak_framer` | +0.165 [+0.045, +0.291] | 1.68 (-0.05) | -0.043 [-0.165, +0.082] | 2.00 (+0.49) | +0.102 [+0.026, +0.181] |
| `early_burst_midgame_pace` | +0.230 [+0.106, +0.348] | 1.32 (-0.42) | +0.100 [-0.031, +0.251] | 1.26 (-0.26) | +0.154 [+0.076, +0.235] |
| `frontier_synthesis_v14` | +0.327 [+0.211, +0.441] | 1.03 (-0.70) | +0.158 [+0.021, +0.300] | 1.21 (-0.31) | +0.238 [+0.164, +0.312] |
| `hof_v14_r1` | +0.076 [-0.038, +0.206] | 1.63 (-0.10) | -0.009 [-0.113, +0.098] | 1.62 (+0.10) | +0.011 [-0.065, +0.088] |
| `hof_v14_r2` | +0.055 [-0.053, +0.178] | 1.70 (-0.03) | -0.002 [-0.122, +0.116] | 1.56 (+0.05) | -0.007 [-0.081, +0.069] |
| `hof_v14_r3` | +0.128 [+0.019, +0.238] | 1.70 (-0.03) | +0.111 [-0.027, +0.272] | 1.67 (+0.15) | +0.135 [+0.055, +0.219] |
| `hof_v14_r4` | +0.230 [+0.106, +0.348] | 1.32 (-0.42) | +0.100 [-0.031, +0.251] | 1.26 (-0.26) | +0.154 [+0.076, +0.235] |

## 4. Part (b): Fresh-Seed Offline Transfer Matrix (v1.4 Hard Seeds 6200-6229, n=30)

### 4.1 Catchability Gates and Investigator Score / Accuracy Matrix

| Strategy | Solver Score (Acc) | GeminiProxy Score (Acc) | CodexProxy Score (Acc) | GrokTactics Score (Acc) | HintedHeur Score (Acc) | Heuristic Score (Acc) | LogsOnly Score (Acc) | Gates |
|---|---|---|---|---|---|---|---|---|
| `default` | +0.524 (93.3%) | +0.451 (80.0%) | +0.464 (93.3%) | +0.426 (80.0%) | +0.424 (90.0%) | +0.264 (96.7%) | -1.000 (0.0%) | **PASS** |
| `surgical_trap_shield` | +0.632 (100.0%) | +0.371 (80.0%) | +0.248 (76.7%) | +0.296 (80.0%) | +0.383 (80.0%) | +0.154 (86.7%) | -1.000 (0.0%) | **PASS** |
| `gemini_midsize_shield` | +0.629 (100.0%) | +0.309 (80.0%) | +0.183 (80.0%) | +0.228 (80.0%) | +0.367 (80.0%) | +0.190 (90.0%) | -1.000 (0.0%) | **PASS** |
| `reactive_canary_lag` | +0.410 (90.0%) | +0.290 (83.3%) | +0.348 (90.0%) | +0.346 (96.7%) | +0.356 (83.3%) | +0.092 (80.0%) | -1.000 (0.0%) | **PASS** |
| `non_decoy_tiebreak_framer` | +0.629 (96.7%) | +0.382 (86.7%) | +0.195 (76.7%) | +0.281 (86.7%) | +0.159 (70.0%) | +0.004 (66.7%) | -1.000 (0.0%) | **PASS** |
| `early_burst_midgame_pace` | +0.644 (100.0%) | +0.260 (73.3%) | +0.331 (86.7%) | +0.402 (86.7%) | +0.377 (83.3%) | +0.080 (76.7%) | -1.000 (0.0%) | **PASS** |
| `frontier_synthesis_v14` | +0.431 (90.0%) | +0.379 (83.3%) | +0.412 (93.3%) | +0.283 (86.7%) | +0.416 (90.0%) | +0.160 (86.7%) | -1.000 (0.0%) | **PASS** |
| `hof_v14_r1` | +0.588 (90.0%) | +0.268 (50.0%) | +0.356 (80.0%) | +0.199 (50.0%) | +0.340 (50.0%) | -0.319 (50.0%) | -1.000 (0.0%) | **PASS** |
| `hof_v14_r2` | +0.586 (90.0%) | +0.337 (46.7%) | +0.262 (73.3%) | +0.000 (0.0%) | +0.284 (40.0%) | -0.141 (56.7%) | -1.000 (0.0%) | **PASS** |
| `hof_v14_r3` | +0.632 (100.0%) | +0.371 (80.0%) | +0.248 (76.7%) | +0.296 (80.0%) | +0.383 (80.0%) | +0.154 (86.7%) | -1.000 (0.0%) | **PASS** |
| `hof_v14_r4` | +0.644 (100.0%) | +0.260 (73.3%) | +0.331 (86.7%) | +0.402 (86.7%) | +0.377 (83.3%) | +0.080 (76.7%) | -1.000 (0.0%) | **PASS** |

### 4.2 Paired Regret Gain vs `DEFAULT_STRATEGY` (Paired Bootstrap 95% CI, B=1000)

| Strategy | GeminiProxy Regret Gain | CodexProxy Regret Gain | Proxy Min-Regret Gain | Panel Min-Regret (Strongest) | Panel Min-Regret Gain |
|---|---|---|---|---|---|
| `default` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | 0.061 (`codex_horizon_proxy`) | +0.000 [+0.000, +0.000] |
| `surgical_trap_shield` | +0.188 [-0.018, +0.419] | +0.323 [-0.012, +0.644] | +0.200 [+0.031, +0.486] | 0.249 (`hinted_heuristic`) | +0.189 [+0.009, +0.406] |
| `gemini_midsize_shield` | +0.247 [+0.028, +0.498] | +0.385 [+0.049, +0.702] | +0.259 [+0.093, +0.525] | 0.262 (`hinted_heuristic`) | +0.201 [+0.023, +0.430] |
| `reactive_canary_lag` | +0.046 [-0.285, +0.407] | +0.001 [-0.389, +0.346] | +0.001 [-0.293, +0.303] | 0.053 (`hinted_heuristic`) | -0.007 [-0.295, +0.252] |
| `non_decoy_tiebreak_framer` | +0.173 [-0.080, +0.453] | +0.373 [+0.047, +0.749] | +0.186 [-0.023, +0.492] | 0.246 (`gemini_carbon_proxy`) | +0.186 [+0.000, +0.451] |
| `early_burst_midgame_pace` | +0.311 [+0.093, +0.565] | +0.252 [-0.058, +0.562] | +0.252 [+0.049, +0.506] | 0.242 (`grok_tactics`) | +0.181 [+0.011, +0.406] |
| `frontier_synthesis_v14` | -0.021 [-0.331, +0.313] | -0.042 [-0.420, +0.294] | -0.042 [-0.340, +0.264] | 0.015 (`hinted_heuristic`) | -0.046 [-0.339, +0.234] |
| `hof_v14_r1` | +0.247 [-0.077, +0.569] | +0.172 [-0.247, +0.532] | +0.172 [-0.145, +0.507] | 0.232 (`codex_horizon_proxy`) | +0.172 [-0.102, +0.436] |
| `hof_v14_r2` | +0.175 [-0.136, +0.487] | +0.263 [-0.180, +0.651] | +0.188 [-0.116, +0.538] | 0.249 (`gemini_carbon_proxy`) | +0.188 [-0.071, +0.508] |
| `hof_v14_r3` | +0.188 [-0.018, +0.419] | +0.323 [-0.012, +0.644] | +0.200 [+0.031, +0.486] | 0.249 (`hinted_heuristic`) | +0.189 [+0.009, +0.406] |
| `hof_v14_r4` | +0.311 [+0.093, +0.565] | +0.252 [-0.058, +0.562] | +0.252 [+0.049, +0.506] | 0.242 (`grok_tactics`) | +0.181 [+0.011, +0.406] |

## 5. Specialist vs Generalist Cross-Model Transfer Analysis

### 5.1 Specialist In-Domain vs Out-of-Domain Transfer

| Specialist Strategy | Target Family | In-Domain Proxy Regret Gain | Out-of-Domain Proxy Regret Gain | In-Minus-Out Gap (95% CI) | Proxy Transfer Ratio | In-Domain CF EV Drop | Out-of-Domain CF EV Drop |
|---|---|---|---|---|---|---|---|
| `surgical_trap_shield` | `codex_gpt55` | +0.323 [-0.012, +0.644] | +0.188 [-0.018, +0.419] | +0.135 [-0.203, +0.504] | 0.58 | +0.097 | +0.160 |
| `gemini_midsize_shield` | `gemini_4_carbon` | +0.247 [+0.028, +0.498] | +0.385 [+0.049, +0.702] | -0.138 [-0.485, +0.256] | 1.56 | +0.203 | +0.079 |
| `reactive_canary_lag` | `gemini_4_carbon` | +0.046 [-0.285, +0.407] | +0.001 [-0.389, +0.346] | +0.045 [-0.341, +0.387] | 0.02 | +0.269 | +0.092 |
| `early_burst_midgame_pace` | `gemini_4_carbon` | +0.311 [+0.093, +0.565] | +0.252 [-0.058, +0.562] | +0.059 [-0.269, +0.462] | 0.81 | +0.183 | +0.110 |

### 5.2 Cohort-Group Synthesis (Unique Non-Default Strategies)

| Strategy Group | Count | Mean Solver Acc | Mean GeminiProxy Regret Gain | Mean CodexProxy Regret Gain | Mean Proxy Min-Regret | Mean 5-Inv Min-Regret | Mean CF Worst-Family EV Drop |
|---|---|---|---|---|---|---|---|
| Gemini Specialists (`gemini_4_carbon`) | 3 | 0.967 | +0.201 | +0.213 | 0.231 | 0.186 | +0.094 |
| Codex Specialists (`codex_gpt55`) | 1 | 1.000 | +0.188 | +0.323 | 0.261 | 0.249 | +0.097 |
| All Unique Specialists | 4 | 0.975 | +0.198 | +0.240 | 0.239 | 0.202 | +0.095 |
| Transcript Generalists (`frontier_all`) | 2 | 0.933 | +0.076 | +0.166 | 0.133 | 0.131 | +0.080 |
| HOF v1.4 Minimax Generalists | 2 | 0.900 | +0.211 | +0.217 | 0.240 | 0.240 | -0.036 |
| All Unique Generalists | 4 | 0.917 | +0.144 | +0.192 | 0.187 | 0.186 | +0.022 |

### 5.3 Cross-Evaluation Rankings (Unique Non-Default Policies)

- **By worst-family counterfactual EV drop (Gemini Hard & Codex/GPT-5.5 All)**: `frontier_synthesis_v14` > `early_burst_midgame_pace` > `surgical_trap_shield` > `reactive_canary_lag` > `gemini_midsize_shield` > `non_decoy_tiebreak_framer` > `hof_v14_r1` > `hof_v14_r2`
- **By fresh-seed worst frontier-proxy regret (`min(GeminiProxy, CodexProxy)`)**: `gemini_midsize_shield` > `early_burst_midgame_pace` > `surgical_trap_shield` > `hof_v14_r2` > `non_decoy_tiebreak_framer` > `hof_v14_r1` > `reactive_canary_lag` > `frontier_synthesis_v14`
- **By fresh-seed 5-investigator minimax regret**: `gemini_midsize_shield` > `surgical_trap_shield` > `hof_v14_r2` > `non_decoy_tiebreak_framer` > `early_burst_midgame_pace` > `hof_v14_r1` > `reactive_canary_lag` > `frontier_synthesis_v14`
