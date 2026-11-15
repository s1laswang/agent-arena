# Mole Strategies v1.4 Head-to-Head Benchmark

Deterministic keyless head-to-head evaluation generated with zero LLM API calls via `scripts/benchmark_mole_strategies.py`.
Evaluated on fresh dev seeds `6000-6029` (`n=30` paired seeds per cell). Seed hygiene is strictly enforced: seeds `0..29` (the post-hoc locked frontier seed set, where commit `671ed96` came 28 s after `8fd4dec`, not pre-registered), `30000..30199`, `800000..899999`, and `>=900000` raise `ValueError`.
All tables report raw scores first (`mean +/- 95% CI` and accuracy) and luck-adjusted scores second (`SolverPolicy` posterior `P(accused) * V - (1 - P(accused))` at the accusation step, `0.0` on abstention).

## 1. Gate Thresholds and Strategy Families

- **Catchability gate**: `solver_acc >= 0.85`.
- **Side-channel gate**: `logs_only <= +0.000` raw mean score.
- **Strategy families evaluated**: (a) `default_v0` (`DEFAULT_STRATEGY`), (b) 6 transcript-grounded DSL strategies from `canary.mole.strategies`, (c) 4 stateful adaptive strategies from `canary.mole.adaptive` (`adaptive_crowd_shield`, `adaptive_reactive_lag`, `adaptive_horizon_squeeze`, `adaptive_counter_frontier` / alias `adaptive_combined`), and (d) RL mole policies (`rl_mole_v1` from `data/rl_mole/policy_final.json`; optional `rl_mole_v2` auto-detection at `results/moletrain/rl_mole_v2_policy.json`: `detected=False`).

## 2. Tier `hard` Head-to-Head Matrix (Seeds `6000-6029`, `n=30`)

Tier parameters: `n_employees=40`, `n_days=21`, `canaries_per_day=2`, `max_variants=3`, `fingerprint_accuracy=0.95`, `leak_damage=0.05`.

- **Gate summary**: **11/12** strategies pass both gates (`catchability_gate`: `11/12`, `side_channel_gate`: `12/12`).
- **Baseline (`default_v0`)**: `SolverPolicy` raw `+0.464 +/- 0.184` (`90.0%` acc; luck-adjusted `+0.583 +/- 0.047`), min frontier-proxy regret `+0.199`, min non-solver regret `+0.093`.
- **Top catchable frontier-proxy trap (`frontier_synthesis_v14`)**: raises min frontier-proxy paired regret to `+0.401` (`+0.202` vs `default_v0`) while `SolverPolicy` reaches `96.7%` accuracy (raw `+0.538 +/- 0.112`; luck-adjusted `+0.525 +/- 0.045`).
- **Top catchable all-investigator trap (`gemini_midsize_shield`)**: raises worst-case paired regret across all 4 non-solver investigators to `+0.216` (`+0.123` vs `default_v0`) at `96.7%` solver accuracy.
- **Catchability gate rejections**: `rl_mole_v1` (`solver_acc=80.0%`) fell below `solver_acc >= 0.85`.

### 2.1 Raw Mean Score +/- 95% CI, Accuracy, and Gates (Raw First)

| Strategy | Family | Solver Raw +/- CI (Acc) | Gemini Proxy Raw +/- CI (Acc) | Codex Proxy Raw +/- CI (Acc) | GrokTactics Raw +/- CI (Acc) | HintedHeuristic Raw +/- CI (Acc) | LogsOnly Raw +/- CI (Acc) | Catchable | Logs <= 0 | Overall |
|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | +0.464 +/- 0.184 (90.0%) | +0.265 +/- 0.172 (80.0%) | +0.178 +/- 0.244 (76.7%) | +0.371 +/- 0.132 (83.3%) | +0.305 +/- 0.157 (70.0%) | -0.938 +/- 0.121 (3.3%) | yes | yes | PASS |
| `surgical_trap_shield` | `transcript_dsl` | +0.429 +/- 0.181 (90.0%) | +0.362 +/- 0.157 (86.7%) | +0.240 +/- 0.231 (80.0%) | +0.317 +/- 0.134 (83.3%) | +0.325 +/- 0.149 (86.7%) | -0.942 +/- 0.114 (3.3%) | yes | yes | PASS |
| `gemini_midsize_shield` | `transcript_dsl` | +0.550 +/- 0.069 (96.7%) | +0.252 +/- 0.174 (76.7%) | +0.156 +/- 0.215 (80.0%) | +0.269 +/- 0.124 (76.7%) | +0.334 +/- 0.150 (86.7%) | -0.942 +/- 0.114 (3.3%) | yes | yes | PASS |
| `reactive_canary_lag` | `transcript_dsl` | +0.525 +/- 0.112 (96.7%) | +0.121 +/- 0.219 (70.0%) | +0.194 +/- 0.223 (80.0%) | +0.339 +/- 0.096 (83.3%) | +0.336 +/- 0.146 (90.0%) | -0.943 +/- 0.111 (3.3%) | yes | yes | PASS |
| `non_decoy_tiebreak_framer` | `transcript_dsl` | +0.549 +/- 0.113 (96.7%) | +0.386 +/- 0.155 (86.7%) | +0.277 +/- 0.216 (83.3%) | +0.318 +/- 0.135 (83.3%) | +0.299 +/- 0.154 (80.0%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `early_burst_midgame_pace` | `transcript_dsl` | +0.562 +/- 0.119 (96.7%) | +0.319 +/- 0.177 (80.0%) | +0.216 +/- 0.249 (76.7%) | +0.389 +/- 0.100 (83.3%) | +0.363 +/- 0.126 (83.3%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `frontier_synthesis_v14` | `transcript_dsl` | +0.538 +/- 0.112 (96.7%) | +0.090 +/- 0.213 (63.3%) | +0.137 +/- 0.234 (76.7%) | +0.329 +/- 0.093 (80.0%) | +0.386 +/- 0.113 (93.3%) | -0.943 +/- 0.111 (3.3%) | yes | yes | PASS |
| `adaptive_crowd_shield` | `adaptive` | +0.507 +/- 0.156 (93.3%) | +0.303 +/- 0.149 (80.0%) | +0.173 +/- 0.241 (76.7%) | +0.356 +/- 0.084 (90.0%) | +0.335 +/- 0.121 (80.0%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `adaptive_reactive_lag` | `adaptive` | +0.573 +/- 0.117 (96.7%) | +0.318 +/- 0.177 (86.7%) | +0.345 +/- 0.199 (86.7%) | +0.232 +/- 0.149 (70.0%) | +0.388 +/- 0.127 (80.0%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `adaptive_horizon_squeeze` | `adaptive` | +0.459 +/- 0.184 (90.0%) | +0.250 +/- 0.149 (66.7%) | +0.204 +/- 0.226 (80.0%) | +0.332 +/- 0.090 (90.0%) | +0.253 +/- 0.175 (70.0%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `adaptive_counter_frontier` (`adaptive_combined`) | `adaptive` | +0.358 +/- 0.204 (86.7%) | +0.260 +/- 0.146 (80.0%) | +0.095 +/- 0.248 (73.3%) | +0.288 +/- 0.120 (80.0%) | +0.403 +/- 0.078 (90.0%) | -1.000 +/- 0.000 (0.0%) | yes | yes | PASS |
| `rl_mole_v1` | `rl_mole` | +0.315 +/- 0.117 (80.0%) | +0.177 +/- 0.190 (66.7%) | +0.174 +/- 0.221 (80.0%) | +0.227 +/- 0.104 (56.7%) | +0.194 +/- 0.155 (46.7%) | -1.000 +/- 0.000 (0.0%) | no | yes | FAIL |

### 2.2 Raw Paired Regret vs SolverPolicy (`Solver - Investigator`, +/- 95% CI)

| Strategy | Gemini Regret +/- CI | Codex Regret +/- CI | GrokTactics Regret +/- CI | HintedHeuristic Regret +/- CI | LogsOnly Regret +/- CI | Min Frontier Regret (Gain) | Min Non-Solver Regret (Gain) |
|---|---|---|---|---|---|---|---|
| `default_v0` | +0.199 +/- 0.264 | +0.286 +/- 0.279 | +0.093 +/- 0.226 | +0.159 +/- 0.242 | +1.402 +/- 0.211 | +0.199 (+0.000) | +0.093 (+0.000) |
| `surgical_trap_shield` | +0.067 +/- 0.194 | +0.189 +/- 0.313 | +0.112 +/- 0.236 | +0.104 +/- 0.246 | +1.371 +/- 0.219 | +0.067 (-0.132) | +0.067 (-0.026) |
| `gemini_midsize_shield` | +0.298 +/- 0.188 | +0.394 +/- 0.218 | +0.281 +/- 0.121 | +0.216 +/- 0.180 | +1.491 +/- 0.156 | +0.298 (+0.098) | +0.216 (+0.123) |
| `reactive_canary_lag` | +0.405 +/- 0.245 | +0.331 +/- 0.249 | +0.187 +/- 0.165 | +0.189 +/- 0.186 | +1.469 +/- 0.163 | +0.331 (+0.132) | +0.187 (+0.094) |
| `non_decoy_tiebreak_framer` | +0.163 +/- 0.201 | +0.272 +/- 0.259 | +0.232 +/- 0.183 | +0.251 +/- 0.214 | +1.549 +/- 0.113 | +0.163 (-0.036) | +0.163 (+0.070) |
| `early_burst_midgame_pace` | +0.243 +/- 0.231 | +0.346 +/- 0.241 | +0.173 +/- 0.145 | +0.199 +/- 0.190 | +1.562 +/- 0.119 | +0.243 (+0.044) | +0.173 (+0.080) |
| `frontier_synthesis_v14` | +0.448 +/- 0.240 | +0.401 +/- 0.261 | +0.209 +/- 0.164 | +0.152 +/- 0.164 | +1.482 +/- 0.158 | +0.401 (+0.202) | +0.152 (+0.059) |
| `adaptive_crowd_shield` | +0.204 +/- 0.206 | +0.334 +/- 0.265 | +0.151 +/- 0.155 | +0.172 +/- 0.205 | +1.507 +/- 0.156 | +0.204 (+0.005) | +0.151 (+0.058) |
| `adaptive_reactive_lag` | +0.255 +/- 0.160 | +0.228 +/- 0.249 | +0.341 +/- 0.178 | +0.185 +/- 0.177 | +1.573 +/- 0.117 | +0.228 (+0.029) | +0.185 (+0.092) |
| `adaptive_horizon_squeeze` | +0.209 +/- 0.250 | +0.255 +/- 0.317 | +0.127 +/- 0.203 | +0.206 +/- 0.257 | +1.459 +/- 0.184 | +0.209 (+0.010) | +0.127 (+0.034) |
| `adaptive_counter_frontier` | +0.098 +/- 0.248 | +0.263 +/- 0.340 | +0.070 +/- 0.237 | -0.045 +/- 0.203 | +1.358 +/- 0.204 | +0.098 (-0.102) | -0.045 (-0.138) |
| `rl_mole_v1` | +0.138 +/- 0.213 | +0.141 +/- 0.248 | +0.088 +/- 0.171 | +0.121 +/- 0.195 | +1.315 +/- 0.117 | +0.138 (-0.061) | +0.088 (-0.005) |

### 2.3 Luck-Adjusted Scores and Luck-Adjusted Regret (Luck-Adjusted Second)

| Strategy | Solver Luck-Adj +/- CI | Gemini Luck-Adj +/- CI (Regret +/- CI) | Codex Luck-Adj +/- CI (Regret +/- CI) | GrokTactics Luck-Adj +/- CI (Regret) | HintedHeuristic Luck-Adj +/- CI (Regret) | LogsOnly Luck-Adj +/- CI |
|---|---|---|---|---|---|---|
| `default_v0` | +0.583 +/- 0.047 | +0.243 +/- 0.133 (+0.339 +/- 0.136) | +0.227 +/- 0.198 (+0.356 +/- 0.189) | +0.370 +/- 0.092 (+0.213) | +0.320 +/- 0.081 (+0.263) | -0.984 +/- 0.008 |
| `surgical_trap_shield` | +0.500 +/- 0.060 | +0.339 +/- 0.111 (+0.161 +/- 0.102) | +0.231 +/- 0.202 (+0.269 +/- 0.210) | +0.323 +/- 0.099 (+0.176) | +0.359 +/- 0.072 (+0.140) | -0.987 +/- 0.009 |
| `gemini_midsize_shield` | +0.484 +/- 0.069 | +0.279 +/- 0.107 (+0.206 +/- 0.130) | +0.170 +/- 0.192 (+0.315 +/- 0.194) | +0.277 +/- 0.086 (+0.208) | +0.370 +/- 0.075 (+0.114) | -0.987 +/- 0.009 |
| `reactive_canary_lag` | +0.508 +/- 0.047 | +0.238 +/- 0.122 (+0.271 +/- 0.125) | +0.187 +/- 0.205 (+0.321 +/- 0.206) | +0.289 +/- 0.090 (+0.220) | +0.353 +/- 0.061 (+0.156) | -0.968 +/- 0.019 |
| `non_decoy_tiebreak_framer` | +0.531 +/- 0.049 | +0.406 +/- 0.100 (+0.126 +/- 0.118) | +0.248 +/- 0.199 (+0.283 +/- 0.207) | +0.327 +/- 0.097 (+0.205) | +0.320 +/- 0.081 (+0.212) | -0.984 +/- 0.009 |
| `early_burst_midgame_pace` | +0.556 +/- 0.054 | +0.366 +/- 0.101 (+0.190 +/- 0.105) | +0.213 +/- 0.230 (+0.343 +/- 0.233) | +0.354 +/- 0.093 (+0.203) | +0.350 +/- 0.079 (+0.206) | -0.980 +/- 0.010 |
| `frontier_synthesis_v14` | +0.525 +/- 0.045 | +0.204 +/- 0.116 (+0.321 +/- 0.116) | +0.135 +/- 0.216 (+0.390 +/- 0.211) | +0.284 +/- 0.086 (+0.241) | +0.354 +/- 0.060 (+0.171) | -0.971 +/- 0.019 |
| `adaptive_crowd_shield` | +0.563 +/- 0.058 | +0.230 +/- 0.129 (+0.333 +/- 0.144) | +0.136 +/- 0.223 (+0.427 +/- 0.240) | +0.311 +/- 0.083 (+0.252) | +0.343 +/- 0.076 (+0.220) | -0.870 +/- 0.046 |
| `adaptive_reactive_lag` | +0.554 +/- 0.051 | +0.384 +/- 0.083 (+0.170 +/- 0.094) | +0.405 +/- 0.138 (+0.149 +/- 0.150) | +0.288 +/- 0.084 (+0.266) | +0.387 +/- 0.086 (+0.167) | -0.883 +/- 0.043 |
| `adaptive_horizon_squeeze` | +0.535 +/- 0.052 | +0.152 +/- 0.141 (+0.383 +/- 0.153) | +0.155 +/- 0.203 (+0.381 +/- 0.213) | +0.263 +/- 0.085 (+0.272) | +0.336 +/- 0.079 (+0.199) | -0.875 +/- 0.047 |
| `adaptive_counter_frontier` | +0.525 +/- 0.065 | +0.227 +/- 0.128 (+0.298 +/- 0.141) | +0.126 +/- 0.206 (+0.399 +/- 0.202) | +0.270 +/- 0.075 (+0.255) | +0.359 +/- 0.073 (+0.166) | -0.865 +/- 0.041 |
| `rl_mole_v1` | +0.309 +/- 0.073 | +0.209 +/- 0.119 (+0.101 +/- 0.121) | +0.082 +/- 0.210 (+0.227 +/- 0.205) | +0.189 +/- 0.094 (+0.120) | +0.256 +/- 0.093 (+0.054) | -0.982 +/- 0.015 |
