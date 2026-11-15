# Head-to-Head Mole Representation Pareto & Catchability Benchmark (`v1.4` Hard)

Offline head-to-head comparison (`0` API calls) of all three fair Canary mole policy representations against `default_v0` on a single unified fresh disjoint evaluation slice (`7400-7459`, `n=60` v1.4 `hard` seeds; strictly disjoint from `0..59`, `6000..6999`, `30000..30199`, `110000..110999`, `800000+`, `900000+`) plus exact `ScheduleReplayPolicy` counterfactual replay on all `60` committed v1.4 Gemini-4-carbon `hard` transcripts (`opencode` + `inproc`, seeds `0-29`).

Reproduce or run the deterministic `<2s` artifact equivalence gate:
```bash
PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.representation_pareto --out results/mole_strategies/representation_pareto_v14.json --report-md docs/reports/mole_representation_pareto_v14.md --workers 4
PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.representation_pareto --check
```

## 1. Executive Takeaways for Judges

- **Unified fairness & catchability compliance**: `9/9` evaluated policies pass all four fairness gates on fresh seeds `7400-7459` (`SolverPolicy("hard") acc >= 0.85`, `LogsOnly acc <= 0.10`, `DoNothing == 0.0`, `StopEarlyQuit == 0.0`).
- **2D Pareto Frontier 1 (`SolverPolicy score` vs `min_frontier_proxy_regret`)**: `hof_v14_r1`, `surgical_trap_shield`, `regret_portfolio_v14`, `default_v0`, `rl_mole_frontier_v14_softmax` (representing families: `baseline`, `continuous_rl_mole`, `minimax_portfolio`, `symbolic_dsl`). Highest worst-case frontier-proxy regret among feasible policies is `rl_mole_frontier_v14_softmax` (`+0.195`, Solver score `+0.508`).
- **2D Pareto Frontier 2 (`SolverPolicy accuracy` vs `counterfactual_ev_drop`)**: `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14` (representing families: `continuous_rl_mole`, `symbolic_dsl`). Largest exact counterfactual Gemini-4-carbon optimal-EV drop among feasible policies is `frontier_synthesis_v14` (`+0.299`, Solver accuracy `0.950`).
- **5-Investigator Minimax Regret Frontier (`SolverPolicy score` vs `min_panel_regret`)**: `hof_v14_r1`, `default_v0`. Highest 5-investigator worst-case regret on fresh seeds is `default_v0` (`+0.142`).
- **Greedy/calibrated vs uncalibrated softmax `RLMole` (`450` continuous float weights)**: `rl_mole_frontier_v14` (`greedy=True`) achieves Solver accuracy `0.950`, min frontier-proxy regret `+0.114`, and counterfactual EV drop `+0.284` (`gate=PASS`), whereas `rl_mole_frontier_v14_softmax` (`greedy=False`) yields Solver accuracy `0.967`, min frontier-proxy regret `+0.195`, and counterfactual EV drop `+0.251` (`gate=PASS`).

## 2. Policy Representation Complexity & Structural Summary

| Policy | Family | Decision Mode | Complexity / Parameter Count | Leaks / Ep | Frames / Ep | Provenance SHA-256 |
|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | `deterministic_seeded_dsl` | 0 rules (fixed default) (`eff_params=0`) | 12.85 | 0.00 | `127e20b1b5cf787c` |
| `surgical_trap_shield` | `symbolic_dsl` | `deterministic_seeded_dsl` | 3 DSL rules (6 predicates) (`eff_params=26`) | 13.00 | 20.63 | `0907d6d754536d07` |
| `gemini_midsize_shield` | `symbolic_dsl` | `deterministic_seeded_dsl` | 2 DSL rules (4 predicates) (`eff_params=18`) | 13.00 | 20.63 | `63bc6e8692bbc5da` |
| `early_burst_midgame_pace` | `symbolic_dsl` | `deterministic_seeded_dsl` | 3 DSL rules (6 predicates) (`eff_params=26`) | 11.80 | 20.75 | `242e9589796dceab` |
| `frontier_synthesis_v14` | `symbolic_dsl` | `deterministic_seeded_dsl` | 4 DSL rules (9 predicates) (`eff_params=37`) | 12.52 | 20.70 | `d61b3efdda1601d2` |
| `hof_v14_r1` (`window_crowd_stale`) | `symbolic_dsl` | `deterministic_seeded_dsl` | 5 DSL rules (6 predicates, HoF r1) (`eff_params=30`) | 4.83 | 19.73 | `a7c2a59f3abde107` |
| `rl_mole_frontier_v14` | `continuous_rl_mole` | `deterministic_greedy_mlp` | 450 float weights (11x20 MLP, greedy) (`eff_params=450`) | 12.70 | 20.70 | `4730184ded6f707d` |
| `rl_mole_frontier_v14_softmax` | `continuous_rl_mole` | `stochastic_softmax_mlp` | 450 float weights (11x20 MLP, softmax) (`eff_params=450`) | 12.52 | 20.37 | `75b177954ed4192e` |
| `regret_portfolio_v14` (`fit:6000-6199`) | `minimax_portfolio` | `seed_hashed_simplex_mixture` | 2-policy SHA-256 mixture (5 support rules) (`eff_params=2`) | 13.00 | 20.63 | `fb1c64a60e18355c` |

## 3. Unified Fresh-Seed Catchability, Fairness Gates & Counterfactual Replay (`7400-7459`, `n=60` + `60` CF Transcripts)

Paired bootstrap 95% confidence intervals use `B=2000` resamples (`seed=20261115`). `Min Proxy Regret` is `min(Solver - GeminiCarbonProxy, Solver - CodexHorizonProxy)` on paired live seeds; `Min Panel Regret` takes the minimum across all 5 non-solver investigators.

| Policy | Family | Solver Acc | Solver Score [95% CI] | LogsOnly Acc | DoNothing / StopEarly | Min Proxy Regret [95% CI] | Min Panel Regret | CF EV Drop [95% CI] | Gate |
|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.933 | +0.525 [+0.405, +0.625] | 0.000 | +0.000 / 0.000 | +0.183 [+0.043, +0.318] | +0.142 (`grok_tactics`) | +0.000 [+0.000, +0.000] | **PASS** |
| `surgical_trap_shield` | `symbolic_dsl` | 0.933 | +0.543 [+0.471, +0.601] | 0.000 | +0.000 / 0.000 | +0.144 [+0.022, +0.218] | +0.106 (`hinted_heuristic`) | +0.160 [+0.076, +0.249] | **PASS** |
| `gemini_midsize_shield` | `symbolic_dsl` | 0.933 | +0.493 [+0.399, +0.568] | 0.000 | +0.000 / 0.000 | +0.160 [+0.026, +0.259] | +0.088 (`hinted_heuristic`) | +0.203 [+0.116, +0.288] | **PASS** |
| `early_burst_midgame_pace` | `symbolic_dsl` | 0.933 | +0.526 [+0.443, +0.596] | 0.000 | +0.000 / 0.000 | +0.139 [+0.023, +0.245] | +0.138 (`hinted_heuristic`) | +0.183 [+0.097, +0.274] | **PASS** |
| `frontier_synthesis_v14` | `symbolic_dsl` | 0.950 | +0.480 [+0.378, +0.564] | 0.000 | +0.000 / 0.000 | +0.110 [-0.044, +0.245] | +0.059 (`grok_tactics`) | +0.299 [+0.218, +0.377] | **PASS** |
| `hof_v14_r1` | `symbolic_dsl` | 0.917 | +0.584 [+0.456, +0.679] | 0.000 | +0.000 / 0.000 | +0.141 [-0.030, +0.291] | +0.141 (`gemini_carbon_proxy`) | +0.041 [-0.057, +0.136] | **PASS** |
| `rl_mole_frontier_v14` | `continuous_rl_mole` | 0.950 | +0.480 [+0.376, +0.563] | 0.000 | +0.000 / 0.000 | +0.114 [-0.053, +0.274] | +0.114 (`codex_horizon_proxy`) | +0.284 [+0.202, +0.364] | **PASS** |
| `rl_mole_frontier_v14_softmax` | `continuous_rl_mole` | 0.967 | +0.508 [+0.424, +0.579] | 0.017 | +0.000 / 0.000 | +0.195 [+0.047, +0.282] | +0.135 (`grok_tactics`) | +0.251 [+0.168, +0.331] | **PASS** |
| `regret_portfolio_v14` | `minimax_portfolio` | 0.933 | +0.539 [+0.464, +0.600] | 0.000 | +0.000 / 0.000 | +0.145 [+0.022, +0.211] | +0.101 (`hinted_heuristic`) | +0.156 [+0.070, +0.242] | **PASS** |

## 4. Paired Investigator Regret Breakdown on Fresh Disjoint Seeds (`7400-7459`, `n=60`)

Cell values report `Regret = SolverPolicy("hard") score - Investigator score` (and paired gain vs `default_v0` `[95% CI]`).

| Policy | GeminiCarbonProxy Regret (Gain) | CodexHorizonProxy Regret (Gain) | GrokTactics Regret (Gain) | HintedHeuristic Regret (Gain) | Heuristic Regret (Gain) | Mean 5-Inv Regret Gain [95% CI] |
|---|---|---|---|---|---|---|
| `default_v0` | +0.183 (+0.000) | +0.395 (+0.000) | +0.142 (+0.000) | +0.228 (+0.000) | +0.367 (+0.000) | +0.000 [+0.000, +0.000] |
| `surgical_trap_shield` | +0.144 (-0.039) | +0.149 (-0.246) | +0.141 (-0.002) | +0.106 (-0.122) | +0.506 (+0.139) | -0.054 [-0.180, +0.085] |
| `gemini_midsize_shield` | +0.213 (+0.030) | +0.160 (-0.235) | +0.196 (+0.054) | +0.088 (-0.140) | +0.447 (+0.079) | -0.042 [-0.178, +0.108] |
| `early_burst_midgame_pace` | +0.139 (-0.044) | +0.294 (-0.101) | +0.158 (+0.016) | +0.138 (-0.090) | +0.372 (+0.004) | -0.043 [-0.192, +0.117] |
| `frontier_synthesis_v14` | +0.147 (-0.036) | +0.110 (-0.285) | +0.059 (-0.083) | +0.147 (-0.081) | +0.454 (+0.086) | -0.080 [-0.237, +0.089] |
| `hof_v14_r1` | +0.141 (-0.041) | +0.343 (-0.052) | +0.438 (+0.296) | +0.380 (+0.152) | +0.958 (+0.590) | +0.189 [+0.034, +0.361] |
| `rl_mole_frontier_v14` | +0.197 (+0.015) | +0.114 (-0.281) | +0.137 (-0.005) | +0.153 (-0.075) | +0.393 (+0.025) | -0.064 [-0.223, +0.101] |
| `rl_mole_frontier_v14_softmax` | +0.195 (+0.013) | +0.211 (-0.183) | +0.135 (-0.007) | +0.184 (-0.044) | +0.474 (+0.106) | -0.023 [-0.140, +0.102] |
| `regret_portfolio_v14` | +0.155 (-0.027) | +0.145 (-0.250) | +0.155 (+0.013) | +0.101 (-0.127) | +0.499 (+0.132) | -0.052 [-0.177, +0.089] |

## 5. Exact Counterfactual Replay on `60` Committed v1.4 Gemini-4-carbon Hard Transcripts (`opencode` + `inproc`, Seeds `0-29`)

Every policy (including stateful/continuous `RLMole` and SHA-256 seed-hashed `PortfolioMolePolicy`) is replayed via `Env("hard", seed, mole_strategy=...)` + `ScheduleReplayPolicy` holding Gemini-4-carbon tool calls fixed.

| Policy | CF Optimal EV | CF EV Drop vs Default [95% CI] | CF P(mole) | CF P(mole) Drop [95% CI] | Top-Suspect Acc (Drop) | Surfaced Canaries / Leaks | OpenCode / InProc EV Drop |
|---|---|---|---|---|---|---|---|
| `default_v0` | 0.439 | +0.000 [+0.000, +0.000] | 0.819 | +0.000 [+0.000, +0.000] | 0.883 (+0.000) | 1.73 / 6.82 | +0.000 / +0.000 |
| `surgical_trap_shield` | 0.279 | +0.160 [+0.076, +0.249] | 0.691 | +0.128 [+0.016, +0.249] | 0.767 (+0.117) | 1.70 / 6.45 | +0.109 / +0.210 |
| `gemini_midsize_shield` | 0.235 | +0.203 [+0.116, +0.288] | 0.617 | +0.203 [+0.086, +0.316] | 0.667 (+0.217) | 1.63 / 6.48 | +0.188 / +0.218 |
| `early_burst_midgame_pace` | 0.256 | +0.183 [+0.097, +0.274] | 0.589 | +0.230 [+0.110, +0.347] | 0.633 (+0.250) | 1.32 / 5.45 | +0.149 / +0.217 |
| `frontier_synthesis_v14` | 0.140 | +0.299 [+0.218, +0.377] | 0.492 | +0.327 [+0.205, +0.438] | 0.600 (+0.283) | 1.03 / 5.92 | +0.252 / +0.346 |
| `hof_v14_r1` | 0.398 | +0.041 [-0.057, +0.136] | 0.743 | +0.076 [-0.043, +0.198] | 0.817 (+0.067) | 1.63 / 4.43 | +0.039 / +0.044 |
| `rl_mole_frontier_v14` | 0.155 | +0.284 [+0.202, +0.364] | 0.508 | +0.311 [+0.199, +0.422] | 0.583 (+0.300) | 1.08 / 6.03 | +0.257 / +0.311 |
| `rl_mole_frontier_v14_softmax` | 0.188 | +0.251 [+0.168, +0.331] | 0.600 | +0.219 [+0.105, +0.335] | 0.700 (+0.183) | 1.23 / 6.13 | +0.183 / +0.319 |
| `regret_portfolio_v14` | 0.283 | +0.156 [+0.070, +0.242] | 0.691 | +0.128 [+0.015, +0.243] | 0.767 (+0.117) | 1.73 / 6.47 | +0.101 / +0.210 |

## 6. Two-Dimensional Pareto Frontier Analysis

### 6.1 Frontier A: `(SolverPolicy Score, Min Frontier-Proxy Regret)`

| Policy | Family | Solver Score (`x`) | Min Frontier-Proxy Regret (`y`) | Pareto Rank | Pareto Optimal | Dominated By |
|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | +0.5248 | +0.1827 | 1 | **YES** | none |
| `surgical_trap_shield` | `symbolic_dsl` | +0.5430 | +0.1437 | 1 | **YES** | none |
| `gemini_midsize_shield` | `symbolic_dsl` | +0.4932 | +0.1600 | 2 | no | `default_v0`, `rl_mole_frontier_v14_softmax` |
| `early_burst_midgame_pace` | `symbolic_dsl` | +0.5265 | +0.1387 | 2 | no | `hof_v14_r1`, `surgical_trap_shield`, `regret_portfolio_v14` |
| `frontier_synthesis_v14` | `symbolic_dsl` | +0.4802 | +0.1097 | 3 | no | `hof_v14_r1`, `surgical_trap_shield`, `regret_portfolio_v14`, `early_burst_midgame_pace`, `default_v0`, `rl_mole_frontier_v14_softmax`, `gemini_midsize_shield` |
| `hof_v14_r1` | `symbolic_dsl` | +0.5835 | +0.1415 | 1 | **YES** | none |
| `rl_mole_frontier_v14` | `continuous_rl_mole` | +0.4797 | +0.1142 | 3 | no | `hof_v14_r1`, `surgical_trap_shield`, `regret_portfolio_v14`, `early_burst_midgame_pace`, `default_v0`, `rl_mole_frontier_v14_softmax`, `gemini_midsize_shield` |
| `rl_mole_frontier_v14_softmax` | `continuous_rl_mole` | +0.5082 | +0.1953 | 1 | **YES** | none |
| `regret_portfolio_v14` | `minimax_portfolio` | +0.5392 | +0.1453 | 1 | **YES** | none |

### 6.2 Frontier B: `(SolverPolicy Accuracy, Counterfactual EV Drop)`

| Policy | Family | Solver Accuracy (`x`) | Counterfactual EV Drop (`y`) | Pareto Rank | Pareto Optimal | Dominated By |
|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.9333 | +0.0000 | 7 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14`, `gemini_midsize_shield`, `early_burst_midgame_pace`, `surgical_trap_shield`, `regret_portfolio_v14` |
| `surgical_trap_shield` | `symbolic_dsl` | 0.9333 | +0.1599 | 5 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14`, `gemini_midsize_shield`, `early_burst_midgame_pace` |
| `gemini_midsize_shield` | `symbolic_dsl` | 0.9333 | +0.2032 | 3 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14` |
| `early_burst_midgame_pace` | `symbolic_dsl` | 0.9333 | +0.1830 | 4 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14`, `gemini_midsize_shield` |
| `frontier_synthesis_v14` | `symbolic_dsl` | 0.9500 | +0.2987 | 1 | **YES** | none |
| `hof_v14_r1` | `symbolic_dsl` | 0.9167 | +0.0412 | 7 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14`, `gemini_midsize_shield`, `early_burst_midgame_pace`, `surgical_trap_shield`, `regret_portfolio_v14` |
| `rl_mole_frontier_v14` | `continuous_rl_mole` | 0.9500 | +0.2837 | 2 | no | `frontier_synthesis_v14` |
| `rl_mole_frontier_v14_softmax` | `continuous_rl_mole` | 0.9667 | +0.2509 | 1 | **YES** | none |
| `regret_portfolio_v14` | `minimax_portfolio` | 0.9333 | +0.1559 | 6 | no | `rl_mole_frontier_v14_softmax`, `frontier_synthesis_v14`, `rl_mole_frontier_v14`, `gemini_midsize_shield`, `early_burst_midgame_pace`, `surgical_trap_shield` |

## 7. Representation Family Synthesis & Tradeoffs for Judges

| Family | Evaluated Policies | Fairness Pass | Best Live Proxy Regret | Best Counterfactual EV Drop | Best 5-Inv Minimax Regret | Pareto Frontier Memberships (LiveProxy / CF / Panel) |
|---|---|---|---|---|---|---|
| `baseline` (Baseline Default) | 1 | 1/1 | `default_v0` (+0.183) | `default_v0` (+0.000) | `default_v0` (+0.142) | `default_v0` / none / `default_v0` |
| `symbolic_dsl` (Symbolic Mole DSL) | 5 | 5/5 | `gemini_midsize_shield` (+0.160) | `frontier_synthesis_v14` (+0.299) | `hof_v14_r1` (+0.141) | `surgical_trap_shield`, `hof_v14_r1` / `frontier_synthesis_v14` / `hof_v14_r1` |
| `continuous_rl_mole` (Continuous Distilled RLMole) | 2 | 2/2 | `rl_mole_frontier_v14_softmax` (+0.195) | `rl_mole_frontier_v14` (+0.284) | `rl_mole_frontier_v14_softmax` (+0.135) | `rl_mole_frontier_v14_softmax` / `rl_mole_frontier_v14_softmax` / none |
| `minimax_portfolio` (Game-Theoretic Minimax Portfolio) | 1 | 1/1 | `regret_portfolio_v14` (+0.145) | `regret_portfolio_v14` (+0.156) | `regret_portfolio_v14` (+0.101) | `regret_portfolio_v14` / none / none |

- **Symbolic Mole DSL (`<=5` discrete rules, `0` continuous weights)**: Human-auditable rule lists map each empirical frontier failure mode directly to an inspectable `(condition -> selector)` branch, achieving minimal parameter complexity (`2-5` rules) and direct per-rule ablation interpretability.
- **Continuous Distilled `RLMole` (`450` float weights, `11->20` MLP)**: Smooth feature combination blends multiple symbolic mechanisms into a single continuous network; greedy argmax (`rl_mole_frontier_v14`) tracks its symbolic teacher (`CF EV drop +0.284`, `LogsOnly=0.000`), while `Env`-seeded softmax sampling (`rl_mole_frontier_v14_softmax`) injects action-level entropy (`CodexHorizonProxy` regret `+0.211` vs `+0.114`, live min proxy regret `+0.195`, `SolverPolicy` acc `0.967`).
- **Game-Theoretic SHA-256 `PortfolioMolePolicy` (`2` active simplex weights)**: Zero-private-information seed randomization hedges across complementary pure DSL specialists (`surgical_trap_shield` and `gemini_midsize_shield`), equalizing binding investigator regrets without expanding the action vocabulary.
