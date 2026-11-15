# Mole Trap x Investigator Matrix (v1.4 Offline Simulation)

Generated offline with zero LLM API calls via `python -m canary.mole.trap_sim --seeds 6300-6319 --include-medium --out docs/reports/mole_trap_matrix_v14.md`.
Seed hygiene enforced: dev seeds 0..29 and judge/heldout seeds >=800000 are rejected by `simulate_trap_cell` and `run_trap_matrix`.
Every luck-adjusted score is evaluated at the exact accusation step via `SolverPolicy` posterior `P(accused) * V - (1 - P(accused))` (0.0 on abstention).

## 1. Headline Findings (Hard Tier, Seeds 6300-6319, n=20)

- **Solver catchability preserved across 6/6 strategies**: Every strategy evaluated on `hard` (`n_employees=40`, `canaries_per_day=2`, `fingerprint_accuracy=0.95`) keeps `SolverPolicy` >= 85% accurate and above `0.5 * baseline_solver_score` (+0.319).
- **Logs-only shortcuts remain strictly negative (6/6 bounded)**: `LogsOnly` stays <= 20% accurate and strictly below 0.0 mean score on every strategy, confirming zero unintended access-log side-channels.
- **Best feasible trap (`reactive_canary_lag`)**: Raises worst-case frontier-proxy regret to **+0.425** (+0.147 vs `default_v0` at +0.278) with luck-adjusted proxy gap **+0.326** while `SolverPolicy` reaches **100%** accuracy (+0.554).
- **Orthogonal architectural selectivity**: `wide_crowd_preference` selectively degrades `GeminiCarbonProxy` from +0.359 (80%) to +0.062 (70%) by routing around 4-8 recipient 3-variant traps, whereas `surgical_trap_shield` selectively degrades `CodexHorizonProxy` from +0.293 (85%) to +0.090 (70%) by routing around <=3-recipient bisection traps.
- **Combined multi-lever trap (`combined_frontier_trap_v14`)**: Simultaneously suppresses `GeminiCarbonProxy` to +0.118 (65%) and `CodexHorizonProxy` to -0.041 (65%), lifting worst-proxy regret to +0.407 (+0.129 gain) while `SolverPolicy` holds 95% accuracy (+0.524).

## 2. Hard-Tier Frontier Proxy and Catchability Summary

| Strategy | Solver Score +/- CI (Acc) | Gemini Proxy (Acc) | Codex Proxy (Acc) | LogsOnly (Acc) | Worst Proxy Regret (Gain) | Luck-Adj Proxy Gap | Solver Beatable | Logs Bounded |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | +0.637 +/- 0.080 (95%) | +0.359 (80%) | +0.293 (85%) | -1.000 (0%) | +0.278 (+0.000) | +0.282 | yes | yes |
| `surgical_trap_shield` | +0.390 +/- 0.226 (85%) | +0.312 (85%) | +0.090 (70%) | -0.912 (5%) | +0.078 (-0.201) | +0.189 | yes | yes |
| `wide_crowd_preference` | +0.380 +/- 0.221 (85%) | +0.062 (70%) | +0.338 (90%) | -0.912 (5%) | +0.042 (-0.236) | +0.161 | yes | yes |
| `reactive_canary_lag` | +0.554 +/- 0.061 (100%) | +0.130 (65%) | +0.007 (65%) | -1.000 (0%) | +0.425 (+0.147) | +0.326 | yes | yes |
| `non_decoy_tiebreak_framing` | +0.442 +/- 0.223 (90%) | +0.312 (85%) | +0.345 (85%) | -0.912 (5%) | +0.097 (-0.181) | +0.081 | yes | yes |
| `combined_frontier_trap_v14` | +0.524 +/- 0.084 (95%) | +0.118 (65%) | -0.041 (65%) | -1.000 (0%) | +0.407 (+0.129) | +0.291 | yes | yes |

### 2.1 Hard-Tier Scripted Baseline Matrix

| Strategy | Heuristic Score (Acc) | HintedHeuristic Score (Acc) | GrokTactics Score (Acc) | LogsOnly Score (Acc) |
|---|---|---|---|---|
| `default_v0` | -0.011 (75%) | +0.391 (90%) | +0.362 (85%) | -1.000 (0%) |
| `surgical_trap_shield` | -0.256 (60%) | +0.361 (70%) | +0.097 (30%) | -0.912 (5%) |
| `wide_crowd_preference` | +0.139 (85%) | +0.412 (90%) | +0.256 (65%) | -0.912 (5%) |
| `reactive_canary_lag` | +0.003 (75%) | +0.328 (85%) | +0.219 (70%) | -1.000 (0%) |
| `non_decoy_tiebreak_framing` | +0.046 (80%) | +0.463 (95%) | +0.399 (100%) | -0.912 (5%) |
| `combined_frontier_trap_v14` | +0.059 (80%) | +0.283 (75%) | +0.228 (65%) | -1.000 (0%) |

### 2.2 Hard-Tier Decision Quality, Luck Adjustment, and Canary Separation

| Strategy | Investigator | Raw Score | Luck-Adj Score | Acc / Wrong / Abstain | Mean Day | Surf Canaries | Sep Canaries |
|---|---|---|---|---|---|---|---|
| `default_v0` | `solver` | +0.637 | +0.580 | 95% / 0% / 5% | 8.55 | 1.70 | 1.20 |
| `default_v0` | `gemini_carbon_proxy` | +0.359 | +0.298 | 80% / 0% / 20% | 16.25 | 1.40 | 0.85 |
| `default_v0` | `codex_horizon_proxy` | +0.293 | +0.286 | 85% / 15% / 0% | 14.05 | 1.40 | 0.85 |
| `default_v0` | `grok_tactics` | +0.362 | +0.364 | 85% / 5% / 10% | 11.00 | 1.00 | 1.00 |
| `surgical_trap_shield` | `solver` | +0.390 | +0.468 | 85% / 10% / 5% | 10.50 | 1.40 | 0.65 |
| `surgical_trap_shield` | `gemini_carbon_proxy` | +0.312 | +0.280 | 85% / 10% / 5% | 15.65 | 1.30 | 0.55 |
| `surgical_trap_shield` | `codex_horizon_proxy` | +0.090 | +0.161 | 70% / 30% / 0% | 12.70 | 1.05 | 0.60 |
| `surgical_trap_shield` | `grok_tactics` | +0.097 | +0.074 | 30% / 0% / 70% | 18.15 | 0.35 | 0.30 |
| `wide_crowd_preference` | `solver` | +0.380 | +0.494 | 85% / 10% / 5% | 10.75 | 1.45 | 0.90 |
| `wide_crowd_preference` | `gemini_carbon_proxy` | +0.062 | +0.246 | 70% / 25% / 5% | 16.40 | 1.30 | 0.70 |
| `wide_crowd_preference` | `codex_horizon_proxy` | +0.338 | +0.333 | 90% / 10% / 0% | 13.25 | 1.65 | 0.90 |
| `wide_crowd_preference` | `grok_tactics` | +0.256 | +0.221 | 65% / 0% / 35% | 14.60 | 0.80 | 0.80 |
| `reactive_canary_lag` | `solver` | +0.554 | +0.507 | 100% / 0% / 0% | 10.90 | 1.60 | 1.10 |
| `reactive_canary_lag` | `gemini_carbon_proxy` | +0.130 | +0.180 | 65% / 15% / 20% | 17.25 | 1.05 | 0.50 |
| `reactive_canary_lag` | `codex_horizon_proxy` | +0.007 | +0.107 | 65% / 35% / 0% | 13.40 | 1.20 | 0.80 |
| `reactive_canary_lag` | `grok_tactics` | +0.219 | +0.251 | 70% / 5% / 25% | 13.45 | 0.75 | 0.75 |
| `non_decoy_tiebreak_framing` | `solver` | +0.442 | +0.535 | 90% / 10% / 0% | 9.35 | 1.50 | 0.85 |
| `non_decoy_tiebreak_framing` | `gemini_carbon_proxy` | +0.312 | +0.306 | 85% / 10% / 5% | 15.60 | 1.35 | 0.60 |
| `non_decoy_tiebreak_framing` | `codex_horizon_proxy` | +0.345 | +0.454 | 85% / 15% / 0% | 10.85 | 1.30 | 0.85 |
| `non_decoy_tiebreak_framing` | `grok_tactics` | +0.399 | +0.344 | 100% / 0% / 0% | 11.40 | 1.05 | 1.05 |
| `combined_frontier_trap_v14` | `solver` | +0.524 | +0.458 | 95% / 0% / 5% | 11.60 | 1.35 | 1.00 |
| `combined_frontier_trap_v14` | `gemini_carbon_proxy` | +0.118 | +0.166 | 65% / 15% / 20% | 17.60 | 1.05 | 0.55 |
| `combined_frontier_trap_v14` | `codex_horizon_proxy` | -0.041 | -0.010 | 65% / 35% / 0% | 15.15 | 0.90 | 0.60 |
| `combined_frontier_trap_v14` | `grok_tactics` | +0.228 | +0.187 | 65% / 0% / 35% | 14.65 | 0.65 | 0.65 |

## 3. Medium-Tier Cross-Check (Seeds 6320-6339, n=20)

Evaluated on `medium` (`n_employees=20`, `canaries_per_day=1`, `n_days=14`, `fingerprint_accuracy=1.0`). Because `medium` allows only 1 canary/day over 14 days, unconditional `surgical_trap_shield` over-suppresses narrow <=4-recipient bisection canaries and fails the 85% solver gate (50% if present), whereas gating the low-recipient shield on wide alternative docs (`max_recipient_count >= 18`) in `combined_frontier_trap_v14` preserves `default_v0` solver accuracy while keeping both frontier proxies suppressed.

| Strategy | Solver Score +/- CI (Acc) | Gemini Proxy (Acc) | Codex Proxy (Acc) | LogsOnly (Acc) | Worst Proxy Regret (Gain) | Luck-Adj Proxy Gap | Solver Beatable | Logs Bounded |
|---|---|---|---|---|---|---|---|---|
| `default_v0` | +0.601 +/- 0.141 (80%) | +0.560 (85%) | +0.100 (65%) | -1.000 (0%) | +0.041 (+0.000) | +0.097 | no | yes |
| `surgical_trap_shield` | +0.388 +/- 0.177 (50%) | +0.016 (55%) | -0.276 (40%) | -1.000 (0%) | +0.372 (+0.331) | +0.311 | no | yes |
| `wide_crowd_preference` | +0.537 +/- 0.130 (80%) | +0.327 (70%) | +0.031 (60%) | -1.000 (0%) | +0.210 (+0.170) | +0.368 | no | yes |
| `reactive_canary_lag` | +0.547 +/- 0.135 (80%) | +0.346 (65%) | -0.097 (55%) | -1.000 (0%) | +0.202 (+0.161) | +0.212 | no | yes |
| `non_decoy_tiebreak_framing` | +0.625 +/- 0.109 (90%) | +0.448 (80%) | +0.303 (75%) | -1.000 (0%) | +0.177 (+0.136) | +0.289 | yes | yes |
| `combined_frontier_trap_v14` | +0.547 +/- 0.135 (80%) | +0.346 (65%) | -0.097 (55%) | -1.000 (0%) | +0.202 (+0.161) | +0.212 | no | yes |

### 3.1 Medium-Tier Scripted Baseline Matrix

| Strategy | Heuristic Score (Acc) | HintedHeuristic Score (Acc) | GrokTactics Score (Acc) | LogsOnly Score (Acc) |
|---|---|---|---|---|
| `default_v0` | -0.214 (50%) | +0.475 (65%) | +0.556 (90%) | -1.000 (0%) |
| `surgical_trap_shield` | +0.025 (65%) | +0.268 (35%) | +0.129 (20%) | -1.000 (0%) |
| `wide_crowd_preference` | -0.034 (60%) | +0.451 (70%) | +0.462 (80%) | -1.000 (0%) |
| `reactive_canary_lag` | +0.021 (65%) | +0.489 (75%) | +0.314 (50%) | -1.000 (0%) |
| `non_decoy_tiebreak_framing` | +0.192 (75%) | +0.550 (80%) | +0.450 (70%) | -1.000 (0%) |
| `combined_frontier_trap_v14` | +0.133 (70%) | +0.489 (75%) | +0.308 (50%) | -1.000 (0%) |

## 4. Mechanism Mapping: Which Trap Levers Fool Which Investigator Archetype

1. **`surgical_trap_shield` -> targets narrow bisection planners (`CodexHorizonProxy`, `Heuristic`, `HintedHeuristic`)**: Whenever `recent_low_recipient_docs >= 1` (`recipient_count <= low_recipient_threshold`), the mole diverts its leak to `most_recipients`. Planners that wait to plant 2-3 recipient surgical traps lose canary surfacing and either abstain or gamble on unseparated suspect pools, while `GeminiCarbonProxy` (which plants 4-6 recipient 3-variant traps) is largely unaffected.
2. **`wide_crowd_preference` -> targets midsize 3-variant subset planters (`GeminiCarbonProxy`)**: On days 1..6 when `min_recipient_count <= 8` and a wider document (`max_recipient_count >= 12`) is available, the mole leaks `most_recipients`. This starves `GeminiCarbonProxy`'s 4-6 employee canary subsets during early/midgame, forcing delayed accusations and single-canary ties under `fingerprint_accuracy=0.95`.
3. **`reactive_canary_lag` -> targets late Day-2+ canary starters (`GeminiCarbonProxy` and `CodexHorizonProxy`)**: On days 1..8 when a newly planted `age_days == 0` document arrives alongside older held documents (`n_leakable >= 2`), the mole leaks `oldest`. Agents that spend Day 1 on interviews/searches and plant reactive canaries on Day 2+ watch the mole leak pre-canary Day-1 documents instead of their fresh traps.
4. **`non_decoy_tiebreak_framing` -> targets raw after-hours tie-breakers (`GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`)**: Frontier agents reliably filter out the angry decoy (`100%` dismissal in v1.3/v1.4 transcripts) yet break 0-separation canary ties using non-decoy after-hours logs. Routing all fake after-hours logs to `most_restricted_peer` or `random_peer` (`0%` decoy framing) manufactures false log spikes on innocent colleagues inside the live suspect pool.
5. **`combined_frontier_trap_v14` -> joint frontier pressure**: Layers early wide-crowd evasion (days 1..5), wide-alternative surgical shielding (`max_recipient_count >= 18`), reactive `age_days == 0` oldest fallback (days 1..8), and non-decoy peer framing to degrade both `GeminiCarbonProxy` and `CodexHorizonProxy` simultaneously.

## 5. Why `SolverPolicy` Remains >= 85% Accurate on Every Kept Hard Strategy

- **Day-1 dual-canary pipelining (`canaries_per_day=2`)**: Unlike frontier transcripts (mean first canary day 3.03-3.40 on v1.4 Hard) and proxies (first canary day 2), `SolverPolicy` plants 2 posterior-balanced MI canaries starting on **Day 1**. By Day 3, `SolverPolicy`'s Day-1 canaries already occupy the `oldest` slot in the 3-day leak window, turning `reactive_canary_lag` into direct canary hits (`100%` solver accuracy on Hard seeds 6300-6319).
- **Adaptive wide coverage + department intersection**: `SolverPolicy` evaluates candidate splits across coverage fractions `(0.10, 0.15, 0.25, 0.40, 0.55, 0.70, 1.00)` and exact department-intersection likelihoods on regular leaks. Even when `wide_crowd_preference` or `surgical_trap_shield` steers leaks toward wider recipient sets, wide 3-variant partitions (`>=16` recipients) plus `canary_shy()` full-staff padding keep mutual information positive every leak.
- **Tempered Poisson framing marginalization (`behaviour_temper=0.6`)**: `SolverPolicy` explicitly models `Poisson(framing_rate)` fake after-hours logs distributed across non-mole peers and tempers behavioural log likelihoods by `0.6`, preventing `non_decoy_tiebreak_framing` spikes from overriding canary variant posteriors or triggering below-breakeven `P < 1 / (1 + V)` gambles.
