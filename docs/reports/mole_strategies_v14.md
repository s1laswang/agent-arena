# Transcript-Grounded Mole DSL Strategies: v1.4 Hard Fresh-Seed & Counterfactual Report

Offline CPU evaluation on **200 fresh disjoint v1.4 `hard` seeds (`6000-6199`)** (seed hygiene enforced: `0-59`, `30000-30199`, `800000+`, and `900000+` strictly forbidden) plus counterfactual schedule replay over **60 committed v1.4 Gemini-4-carbon Hard transcripts** (30 OpenCode MCP + 30 in-proc on seeds `0-29`). Paired bootstrap 95% CIs use `10000` paired seed resamples (`seed=20261114`). Zero Gemini API calls.

Reproduce or verify exact JSON-to-Markdown equivalence:
```bash
PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python scripts/eval_mole_strategies_v14.py --check
```

## 1. Headline Findings

- **100% fairness and catchability pass rate (6/6 transcript strategies + `DEFAULT_STRATEGY`)**: Every strategy keeps `SolverPolicy("hard")` accuracy >= `0.85`, `LogsOnly` and `AccuseMostLogs` accuracy <= `0.10`, and `DoNothing` / `StopEarlyQuit` identically `0.0` (`all_passed=True`, `unique_behavior_hashes=True`).
- **Strongest worst-case investigator gap (`min_regret`)**: `early_burst_midgame_pace` achieves `min_regret = 0.199` [0.125, 0.235] vs `DEFAULT_STRATEGY` `0.196` (gain `+0.004`, 95% CI [-0.065, +0.089]).
- **Strongest `GeminiCarbonProxy` paired regret gain**: `gemini_midsize_shield` reaches `GeminiCarbonProxy` regret `0.297` vs `DEFAULT_STRATEGY` `0.196` (paired gain `+0.101`, 95% CI [-0.002, +0.201]).
- **Counterfactual replay on 60 real v1.4 Gemini Hard transcripts**: `frontier_synthesis_v14` reduces Gemini optimal Bayesian EV at accusation by `+0.299` (surfaced canaries delta `-0.70`, `P(true mole)` drop `+0.327`, counterfactual regret `0.401`, gain vs `DEFAULT_STRATEGY` `+0.341`).

## 2. SolverPolicy("hard") Catchability & Anti-Shortcut Baselines (Seeds 6000-6199, n=200)

| Strategy | Rules | BHash | Solver Acc | Solver Score +/- 95% CI | Accuse Day | / Default | LogsOnly Acc (Score) | AccuseMostLogs Acc (Score) | DoNothing | StopEarlyQuit | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `DEFAULT_STRATEGY (default_v0)` | 0 | `4ce97ce8` | 0.970 | 0.544 +/- 0.041 | 9.51 | 1.000 | 0.020 (-0.964) | 0.025 (-0.954) | 0.000 | 0.000 | PASS |
| `surgical_trap_shield` | 3 | `e55c0473` | 0.970 | 0.573 +/- 0.043 | 9.20 | 1.053 | 0.015 (-0.974) | 0.020 (-0.963) | 0.000 | 0.000 | PASS |
| `gemini_midsize_shield` | 2 | `6153914e` | 0.960 | 0.544 +/- 0.038 | 9.75 | 0.999 | 0.015 (-0.974) | 0.020 (-0.963) | 0.000 | 0.000 | PASS |
| `reactive_canary_lag` | 2 | `637c34ad` | 0.945 | 0.515 +/- 0.042 | 10.07 | 0.947 | 0.015 (-0.973) | 0.015 (-0.973) | 0.000 | 0.000 | PASS |
| `non_decoy_tiebreak_framer` | 3 | `eb452649` | 0.940 | 0.500 +/- 0.051 | 10.09 | 0.919 | 0.010 (-0.983) | 0.030 (-0.944) | 0.000 | 0.000 | PASS |
| `early_burst_midgame_pace` | 3 | `3635b8fc` | 0.970 | 0.572 +/- 0.041 | 10.04 | 1.051 | 0.005 (-0.991) | 0.030 (-0.944) | 0.000 | 0.000 | PASS |
| `frontier_synthesis_v14` | 4 | `eec9419b` | 0.945 | 0.516 +/- 0.042 | 10.47 | 0.948 | 0.015 (-0.973) | 0.015 (-0.973) | 0.000 | 0.000 | PASS |

## 3. Paired Investigator Regret (`solver - inv`) & Bootstrap 95% CIs (Seeds 6000-6199, n=200)

| Strategy | Strongest Inv | Min Regret [95% Boot CI] | Min Regret Gain vs Default [95% Boot CI] | GeminiProxy Regret [95% Boot CI] | GeminiProxy Regret Gain [95% Boot CI] | Mean Suite Regret (Gain) |
|---|---|---|---|---|---|---|
| `DEFAULT_STRATEGY (default_v0)` | GeminiCarbonProxy | 0.196 [0.111, 0.226] | +0.000 [+0.000, +0.000] | 0.196 [0.123, 0.269] | +0.000 [+0.000, +0.000] | 0.267 (+0.000) |
| `surgical_trap_shield` | GeminiCarbonProxy | 0.195 [0.125, 0.232] | -0.001 [-0.060, +0.085] | 0.195 [0.131, 0.261] | -0.001 [-0.093, +0.092] | 0.284 (+0.017) |
| `gemini_midsize_shield` | HintedHeuristic(hard) | 0.199 [0.134, 0.263] | +0.004 [-0.056, +0.116] | 0.297 [0.224, 0.371] | +0.101 [-0.002, +0.201] | 0.329 (+0.061) |
| `reactive_canary_lag` | HintedHeuristic(hard) | 0.163 [0.100, 0.222] | -0.033 [-0.090, +0.075] | 0.223 [0.146, 0.302] | +0.027 [-0.077, +0.130] | 0.289 (+0.021) |
| `non_decoy_tiebreak_framer` | GeminiCarbonProxy | 0.114 [0.044, 0.179] | -0.082 [-0.145, +0.031] | 0.114 [0.046, 0.183] | -0.082 [-0.179, +0.016] | 0.228 (-0.039) |
| `early_burst_midgame_pace` | GrokTactics(hard) | 0.199 [0.125, 0.235] | +0.004 [-0.065, +0.089] | 0.214 [0.137, 0.293] | +0.018 [-0.082, +0.123] | 0.291 (+0.023) |
| `frontier_synthesis_v14` | HintedHeuristic(hard) | 0.182 [0.119, 0.231] | -0.014 [-0.076, +0.089] | 0.223 [0.148, 0.298] | +0.027 [-0.077, +0.132] | 0.283 (+0.016) |

### 3.1 Per-Investigator Score, Accuracy, and Paired Regret Breakdown

| Strategy | GeminiCarbonProxy Score / Acc / Regret | CodexHorizonProxy Score / Acc / Regret | GrokTactics Score / Acc / Regret | Heuristic Score / Acc / Regret | HintedHeuristic Score / Acc / Regret |
|---|---|---|---|---|---|
| `DEFAULT_STRATEGY (default_v0)` | +0.349 / 0.83 / +0.196 | +0.335 / 0.86 / +0.209 | +0.334 / 0.82 / +0.210 | +0.025 / 0.78 / +0.519 | +0.342 / 0.78 / +0.203 |
| `surgical_trap_shield` | +0.378 / 0.83 / +0.195 | +0.268 / 0.82 / +0.306 | +0.368 / 0.84 / +0.205 | +0.070 / 0.81 / +0.503 | +0.363 / 0.81 / +0.211 |
| `gemini_midsize_shield` | +0.247 / 0.77 / +0.297 | +0.164 / 0.80 / +0.379 | +0.260 / 0.78 / +0.284 | +0.061 / 0.80 / +0.482 | +0.344 / 0.80 / +0.199 |
| `reactive_canary_lag` | +0.292 / 0.82 / +0.223 | +0.246 / 0.82 / +0.270 | +0.273 / 0.82 / +0.243 | -0.029 / 0.73 / +0.545 | +0.353 / 0.84 / +0.163 |
| `non_decoy_tiebreak_framer` | +0.386 / 0.87 / +0.114 | +0.234 / 0.81 / +0.267 | +0.267 / 0.80 / +0.234 | +0.135 / 0.79 / +0.366 | +0.339 / 0.80 / +0.161 |
| `early_burst_midgame_pace` | +0.358 / 0.81 / +0.214 | +0.244 / 0.80 / +0.328 | +0.372 / 0.83 / +0.199 | +0.067 / 0.76 / +0.505 | +0.366 / 0.78 / +0.206 |
| `frontier_synthesis_v14` | +0.293 / 0.81 / +0.223 | +0.268 / 0.83 / +0.248 | +0.285 / 0.84 / +0.231 | -0.016 / 0.74 / +0.532 | +0.334 / 0.79 / +0.182 |

## 4. Counterfactual Replay on 60 Committed v1.4 Gemini Hard Transcripts (30 OpenCode + 30 In-Proc)

| Strategy | Surfaced Canaries (Delta) | Horizon Canaries (Delta) | P(true mole) (Drop) | Gemini Opt EV (Drop) | OpenCode EV (Drop) | In-Proc EV (Drop) | CF Regret (Gain vs Default) |
|---|---|---|---|---|---|---|---|
| `DEFAULT_STRATEGY (default_v0)` | 1.73 (+0.00) | 2.03 (+0.00) | 0.819 (+0.000) | 0.439 (+0.000) | 0.417 (+0.000) | 0.460 (+0.000) | +0.060 (+0.000) |
| `surgical_trap_shield` | 1.70 (-0.03) | 2.07 (+0.03) | 0.691 (+0.128) | 0.279 (+0.160) | 0.308 (+0.109) | 0.250 (+0.211) | +0.218 (+0.158) |
| `gemini_midsize_shield` | 1.63 (-0.10) | 1.95 (-0.08) | 0.617 (+0.202) | 0.235 (+0.203) | 0.229 (+0.188) | 0.242 (+0.218) | +0.272 (+0.212) |
| `reactive_canary_lag` | 1.28 (-0.45) | 1.62 (-0.42) | 0.536 (+0.283) | 0.170 (+0.269) | 0.194 (+0.223) | 0.145 (+0.315) | +0.407 (+0.347) |
| `non_decoy_tiebreak_framer` | 1.68 (-0.05) | 1.93 (-0.10) | 0.654 (+0.165) | 0.280 (+0.159) | 0.289 (+0.128) | 0.272 (+0.189) | +0.193 (+0.132) |
| `early_burst_midgame_pace` | 1.32 (-0.42) | 1.63 (-0.40) | 0.589 (+0.230) | 0.256 (+0.183) | 0.268 (+0.149) | 0.243 (+0.217) | +0.277 (+0.217) |
| `frontier_synthesis_v14` | 1.03 (-0.70) | 1.42 (-0.62) | 0.492 (+0.327) | 0.140 (+0.299) | 0.165 (+0.252) | 0.115 (+0.346) | +0.401 (+0.341) |

## 5. Empirical Grounding & Solver Catchability Rationale by Strategy

### `surgical_trap_shield` (`lever=low_recipient_surgical_shield`, `cohort=codex_gpt55`)
- **Empirical transcript finding**: Codex and GPT-5.5 place 30.6% to 75.3% of planted canaries into <=3-recipient surgical traps while dismissing the angry decoy in 100.0% of 159 frontier episodes.
- **Why `SolverPolicy` stays unbeaten**: Early surgical-trap deflection ends after day 7 and defaults to random_seeded, allowing SolverPolicy wide balanced partitions and mid-to-late game canaries to isolate the mole.

### `gemini_midsize_shield` (`lever=midsize_canary_evasion`, `cohort=gemini_4_carbon`)
- **Empirical transcript finding**: Gemini-4-carbon places 0.0% to 0.6% of canaries in <=3 recipients and concentrates 43.6% to 73.6% of canaries in 4-8 recipient 3-variant cells, failing on 0-hit seeds.
- **Why `SolverPolicy` stays unbeaten**: Crowd preference is restricted to days 1-6 when wide documents coexist with 1-8 recipient traps; SolverPolicy still narrows via regular leaks and wide >=9-recipient partitions.

### `reactive_canary_lag` (`lever=reactive_canary_lag_oldest`, `cohort=gemini_4_carbon`)
- **Empirical transcript finding**: On v1.4 Hard, Gemini delays its first canary to mean day 3.03 (OpenCode) and 3.40 (in-proc) versus Solver day 1.00, planting reactive age-0 canaries and making 7/10 Hard wrong accusations with <=1 separating canary under 0.95 fingerprint accuracy.
- **Why `SolverPolicy` stays unbeaten**: SolverPolicy plants 2 canaries per day starting day 1.00 (14.13 per episode on Hard), so its earlier canaries already occupy the oldest leak-window slot when oldest is selected.

### `non_decoy_tiebreak_framer` (`lever=non_decoy_peer_framing`, `cohort=frontier_all`)
- **Empirical transcript finding**: Frontier investigators dismissed the angry decoy in 100.0% of 159 decoy-enabled episodes (0 accusations, 0 restrictions), whereas non-decoy framed after-hours logs broke 0-separation canary ties into -1.0 wrong accusations in 5/10 total frontier wrong accusations.
- **Why `SolverPolicy` stays unbeaten**: SolverPolicy marginalises Poisson framing across peers with behaviour_temper=0.6 and never allows after-hours log spikes to override primary document and canary likelihoods.

### `early_burst_midgame_pace` (`lever=early_burst_midgame_quiet_pacing`, `cohort=gemini_4_carbon`)
- **Empirical transcript finding**: Gemini spends 57.27 to 68.03 calls per Hard episode on low-LR interviews (64.4% to 68.0% of investigative budget), lags Solver by +1.97 to +2.52 days, and makes 22 below-breakeven gambles.
- **Why `SolverPolicy` stays unbeaten**: Early leaks on days 1-2 hit Solver day-1 canaries, and midgame pacing only throttles consecutive days inside days 5-8, preserving ample leak volume over 21 days for >=0.85 Solver accuracy.

### `frontier_synthesis_v14` (`lever=composite_frontier_synthesis`, `cohort=frontier_all`)
- **Empirical transcript finding**: Combines early surgical-trap deflection, reactive age-0 canary evasion on days 1-7, bounded midgame pacing on days 5-8, and non-decoy peer framing across restricted and peer pools.
- **Why `SolverPolicy` stays unbeaten**: All four conditional rules relax to random_seeded after day 8 while framing only non-decoy peers, keeping SolverPolicy above 0.90 accuracy while reducing Gemini and Codex proxy scores.

## 6. Machine-Verified Summary Ledger

<!-- MOLE_STRATEGIES_V14_LEDGER_START -->
```json
{
  "baseline_strategy": "default_v0",
  "bootstrap_resamples": 10000,
  "bootstrap_seed": 20261114,
  "counterfactual_meta": {
    "n_seeds": 30,
    "n_transcripts_by_source": {
      "inproc": 30,
      "opencode": 30
    },
    "n_transcripts_total": 60,
    "sources": [
      "opencode",
      "inproc"
    ],
    "tier": "hard",
    "transcript_seeds": [
      0,
      1,
      2,
      3,
      4,
      5,
      6,
      7,
      8,
      9,
      10,
      11,
      12,
      13,
      14,
      15,
      16,
      17,
      18,
      19,
      20,
      21,
      22,
      23,
      24,
      25,
      26,
      27,
      28,
      29
    ]
  },
  "gates": {
    "all_logs_only_le_010": true,
    "all_passed": true,
    "all_solver_acc_ge_085": true,
    "all_zero_baselines_exact": true,
    "max_logs_acc": 0.1,
    "min_solver_acc": 0.85,
    "min_solver_ratio": 0.5,
    "seed_hygiene_passed": true,
    "unique_behavior_hashes": true
  },
  "highlights": {
    "best_counterfactual_ev_drop_strategy": "frontier_synthesis_v14",
    "best_gemini_regret_gain_strategy": "gemini_midsize_shield",
    "best_min_regret_strategy": "early_burst_midgame_pace"
  },
  "investigator_order": [
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "heuristic",
    "hinted_heuristic"
  ],
  "n_seeds": 200,
  "schema_version": "mole_strategies_v14_eval.v1",
  "seed_range": "6000-6199",
  "strategies": {
    "default_v0": {
      "baselines": {
        "accuse_most_logs_acc": 0.025,
        "accuse_most_logs_score": -0.95375,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.02,
        "logs_only_score": -0.9640000000000001,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "4ce97ce85124050ce478649ec860136b",
      "counterfactual": {
        "counterfactual_regret": 0.060320082274490705,
        "counterfactual_regret_gain_vs_default": 0.0,
        "inproc_optimal_ev": 0.4604184931883333,
        "inproc_optimal_ev_drop": 0.0,
        "inproc_surfaced_canaries": 1.8333333333333333,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.41694134226268526,
        "opencode_optimal_ev_drop": 0.0,
        "opencode_surfaced_canaries": 1.6333333333333333,
        "optimal_ev": 0.4386799177255093,
        "optimal_ev_drop": 0.0,
        "p_true_mole": 0.8189873583461771,
        "p_true_mole_drop": 0.0,
        "surfaced_canaries": 1.7333333333333334,
        "surfaced_canaries_delta": 0.0,
        "surfaced_canaries_horizon": 2.033333333333333,
        "surfaced_canaries_horizon_delta": 0.0,
        "surfaced_total_leaks": 6.816666666666666
      },
      "display_name": "DEFAULT_STRATEGY (default_v0)",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.86,
          "regret": 0.20905,
          "regret_boot_ci_95": [
            0.12480000000000001,
            0.2944
          ],
          "regret_gain_boot_ci_95": [
            0.0,
            0.0
          ],
          "regret_gain_vs_default": 0.0,
          "score": 0.3354
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.835,
          "regret": 0.19585,
          "regret_boot_ci_95": [
            0.12335000000000002,
            0.26905
          ],
          "regret_gain_boot_ci_95": [
            0.0,
            0.0
          ],
          "regret_gain_vs_default": 0.0,
          "score": 0.3486
        },
        "grok_tactics": {
          "accuracy": 0.82,
          "regret": 0.2101,
          "regret_boot_ci_95": [
            0.1361,
            0.2836
          ],
          "regret_gain_boot_ci_95": [
            0.0,
            0.0
          ],
          "regret_gain_vs_default": 0.0,
          "score": 0.33435000000000004
        },
        "heuristic": {
          "accuracy": 0.78,
          "regret": 0.5191,
          "regret_boot_ci_95": [
            0.43810000000000004,
            0.60045
          ],
          "regret_gain_boot_ci_95": [
            0.0,
            0.0
          ],
          "regret_gain_vs_default": 0.0,
          "score": 0.02535
        },
        "hinted_heuristic": {
          "accuracy": 0.78,
          "regret": 0.2027,
          "regret_boot_ci_95": [
            0.1404,
            0.2655
          ],
          "regret_gain_boot_ci_95": [
            0.0,
            0.0
          ],
          "regret_gain_vs_default": 0.0,
          "score": 0.34175
        }
      },
      "is_default": true,
      "lever_id": "baseline_uniform_random",
      "n_rules": 0,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.19585,
        "gemini_regret_boot_ci_95": [
          0.12335000000000002,
          0.26905
        ],
        "gemini_regret_gain_boot_ci_95": [
          0.0,
          0.0
        ],
        "gemini_regret_gain_vs_default": 0.0,
        "mean_regret": 0.26736,
        "mean_regret_gain_vs_default": 0.0,
        "min_regret": 0.19585,
        "min_regret_boot_ci_95": [
          0.11120000000000001,
          0.2255
        ],
        "min_regret_gain_boot_ci_95": [
          0.0,
          0.0
        ],
        "min_regret_gain_vs_default": 0.0,
        "strongest_investigator": "gemini_carbon_proxy",
        "strongest_investigator_label": "GeminiCarbonProxy"
      },
      "solver": {
        "accuracy": 0.97,
        "mean_accuse_day": 9.512562814070352,
        "passed": true,
        "ratio_vs_default": 1.0,
        "score": 0.54445,
        "score_boot_ci_95": [
          0.5004500000000001,
          0.58165
        ],
        "score_ci_95": 0.04076713285461622
      },
      "target_cohort": "baseline"
    },
    "early_burst_midgame_pace": {
      "baselines": {
        "accuse_most_logs_acc": 0.03,
        "accuse_most_logs_score": -0.9440000000000001,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.005,
        "logs_only_score": -0.991,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "3635b8fc202b2fef5a1846f25f4c0629",
      "counterfactual": {
        "counterfactual_regret": 0.2773242001803299,
        "counterfactual_regret_gain_vs_default": 0.21700411790583918,
        "inproc_optimal_ev": 0.24345978246729363,
        "inproc_optimal_ev_drop": 0.21695871072103964,
        "inproc_surfaced_canaries": 1.2666666666666666,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.26789181717204663,
        "opencode_optimal_ev_drop": 0.14904952509063862,
        "opencode_surfaced_canaries": 1.3666666666666667,
        "optimal_ev": 0.25567579981967015,
        "optimal_ev_drop": 0.18300411790583915,
        "p_true_mole": 0.5887801143434904,
        "p_true_mole_drop": 0.23020724400268672,
        "surfaced_canaries": 1.3166666666666667,
        "surfaced_canaries_delta": -0.4166666666666667,
        "surfaced_canaries_horizon": 1.6333333333333333,
        "surfaced_canaries_horizon_delta": -0.4,
        "surfaced_total_leaks": 5.45
      },
      "display_name": "early_burst_midgame_pace",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.795,
          "regret": 0.32775,
          "regret_boot_ci_95": [
            0.2397,
            0.4211
          ],
          "regret_gain_boot_ci_95": [
            -0.0005499999999999984,
            0.24009999999999998
          ],
          "regret_gain_vs_default": 0.11870000000000001,
          "score": 0.24420000000000003
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.81,
          "regret": 0.2141,
          "regret_boot_ci_95": [
            0.13685,
            0.29345
          ],
          "regret_gain_boot_ci_95": [
            -0.08175,
            0.1229
          ],
          "regret_gain_vs_default": 0.01824999999999999,
          "score": 0.35784999999999995
        },
        "grok_tactics": {
          "accuracy": 0.83,
          "regret": 0.19949999999999998,
          "regret_boot_ci_95": [
            0.13629999999999998,
            0.26239999999999997
          ],
          "regret_gain_boot_ci_95": [
            -0.10644999999999999,
            0.07925
          ],
          "regret_gain_vs_default": -0.0106,
          "score": 0.37244999999999995
        },
        "heuristic": {
          "accuracy": 0.755,
          "regret": 0.50495,
          "regret_boot_ci_95": [
            0.4119,
            0.5985
          ],
          "regret_gain_boot_ci_95": [
            -0.13955,
            0.11225
          ],
          "regret_gain_vs_default": -0.014149999999999998,
          "score": 0.067
        },
        "hinted_heuristic": {
          "accuracy": 0.78,
          "regret": 0.20620000000000002,
          "regret_boot_ci_95": [
            0.15065,
            0.26155
          ],
          "regret_gain_boot_ci_95": [
            -0.07780000000000001,
            0.08465
          ],
          "regret_gain_vs_default": 0.0034999999999999988,
          "score": 0.36575
        }
      },
      "is_default": false,
      "lever_id": "early_burst_midgame_quiet_pacing",
      "n_rules": 3,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.2141,
        "gemini_regret_boot_ci_95": [
          0.13685,
          0.29345
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.08175,
          0.1229
        ],
        "gemini_regret_gain_vs_default": 0.01824999999999999,
        "mean_regret": 0.29050000000000004,
        "mean_regret_gain_vs_default": 0.02314000000000005,
        "min_regret": 0.19949999999999998,
        "min_regret_boot_ci_95": [
          0.12475,
          0.23504999999999998
        ],
        "min_regret_gain_boot_ci_95": [
          -0.06525000000000003,
          0.08885000000000003
        ],
        "min_regret_gain_vs_default": 0.0036499999999999866,
        "strongest_investigator": "grok_tactics",
        "strongest_investigator_label": "GrokTactics(hard)"
      },
      "solver": {
        "accuracy": 0.97,
        "mean_accuse_day": 10.040201005025125,
        "passed": true,
        "ratio_vs_default": 1.050509688676646,
        "score": 0.57195,
        "score_boot_ci_95": [
          0.5286500000000001,
          0.6106
        ],
        "score_ci_95": 0.04132796157104885
      },
      "target_cohort": "gemini_4_carbon"
    },
    "frontier_synthesis_v14": {
      "baselines": {
        "accuse_most_logs_acc": 0.015,
        "accuse_most_logs_score": -0.9725,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.015,
        "logs_only_score": -0.9734999999999999,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "eec9419bd531541cef0d1bfb6879576e",
      "counterfactual": {
        "counterfactual_regret": 0.4009706305212989,
        "counterfactual_regret_gain_vs_default": 0.3406505482468082,
        "inproc_optimal_ev": 0.11481559036923798,
        "inproc_optimal_ev_drop": 0.34560290281909534,
        "inproc_surfaced_canaries": 0.9,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.16524314858816436,
        "opencode_optimal_ev_drop": 0.2516981936745209,
        "opencode_surfaced_canaries": 1.1666666666666667,
        "optimal_ev": 0.14002936947870118,
        "optimal_ev_drop": 0.2986505482468081,
        "p_true_mole": 0.49230926006633907,
        "p_true_mole_drop": 0.32667809827983796,
        "surfaced_canaries": 1.0333333333333334,
        "surfaced_canaries_delta": -0.7,
        "surfaced_canaries_horizon": 1.4166666666666667,
        "surfaced_canaries_horizon_delta": -0.6166666666666667,
        "surfaced_total_leaks": 5.916666666666667
      },
      "display_name": "frontier_synthesis_v14",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.835,
          "regret": 0.24844999999999998,
          "regret_boot_ci_95": [
            0.16245,
            0.3385
          ],
          "regret_gain_boot_ci_95": [
            -0.0843,
            0.1635
          ],
          "regret_gain_vs_default": 0.039400000000000004,
          "score": 0.26755
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.815,
          "regret": 0.22265000000000001,
          "regret_boot_ci_95": [
            0.14805000000000001,
            0.29774999999999996
          ],
          "regret_gain_boot_ci_95": [
            -0.0768,
            0.1317
          ],
          "regret_gain_vs_default": 0.0268,
          "score": 0.29335
        },
        "grok_tactics": {
          "accuracy": 0.84,
          "regret": 0.23115000000000002,
          "regret_boot_ci_95": [
            0.1672,
            0.29510000000000003
          ],
          "regret_gain_boot_ci_95": [
            -0.07695,
            0.1166
          ],
          "regret_gain_vs_default": 0.021050000000000003,
          "score": 0.28485
        },
        "heuristic": {
          "accuracy": 0.74,
          "regret": 0.5318,
          "regret_boot_ci_95": [
            0.44695,
            0.621
          ],
          "regret_gain_boot_ci_95": [
            -0.10875000000000001,
            0.13099999999999998
          ],
          "regret_gain_vs_default": 0.012699999999999994,
          "score": -0.015799999999999998
        },
        "hinted_heuristic": {
          "accuracy": 0.79,
          "regret": 0.18225000000000002,
          "regret_boot_ci_95": [
            0.12285,
            0.24285
          ],
          "regret_gain_boot_ci_95": [
            -0.10145,
            0.06465
          ],
          "regret_gain_vs_default": -0.02045,
          "score": 0.33375
        }
      },
      "is_default": false,
      "lever_id": "composite_frontier_synthesis",
      "n_rules": 4,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.22265000000000001,
        "gemini_regret_boot_ci_95": [
          0.14805000000000001,
          0.29774999999999996
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.0768,
          0.1317
        ],
        "gemini_regret_gain_vs_default": 0.0268,
        "mean_regret": 0.28326,
        "mean_regret_gain_vs_default": 0.015900000000000025,
        "min_regret": 0.18225000000000002,
        "min_regret_boot_ci_95": [
          0.11885,
          0.2309
        ],
        "min_regret_gain_boot_ci_95": [
          -0.07649999999999998,
          0.08920000000000003
        ],
        "min_regret_gain_vs_default": -0.013599999999999973,
        "strongest_investigator": "hinted_heuristic",
        "strongest_investigator_label": "HintedHeuristic(hard)"
      },
      "solver": {
        "accuracy": 0.945,
        "mean_accuse_day": 10.474226804123711,
        "passed": true,
        "ratio_vs_default": 0.9477454311690697,
        "score": 0.516,
        "score_boot_ci_95": [
          0.47240000000000004,
          0.55515
        ],
        "score_ci_95": 0.041582753576150704
      },
      "target_cohort": "frontier_all"
    },
    "gemini_midsize_shield": {
      "baselines": {
        "accuse_most_logs_acc": 0.02,
        "accuse_most_logs_score": -0.96325,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.015,
        "logs_only_score": -0.97425,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "6153914e768647835177cd6099e312c8",
      "counterfactual": {
        "counterfactual_regret": 0.2718397239046334,
        "counterfactual_regret_gain_vs_default": 0.2115196416301427,
        "inproc_optimal_ev": 0.24229156637947435,
        "inproc_optimal_ev_drop": 0.21812692680885892,
        "inproc_surfaced_canaries": 1.5,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.22869565247792545,
        "opencode_optimal_ev_drop": 0.1882456897847598,
        "opencode_surfaced_canaries": 1.7666666666666666,
        "optimal_ev": 0.2354936094286999,
        "optimal_ev_drop": 0.20318630829680936,
        "p_true_mole": 0.6165110717736867,
        "p_true_mole_drop": 0.20247628657249042,
        "surfaced_canaries": 1.6333333333333333,
        "surfaced_canaries_delta": -0.1,
        "surfaced_canaries_horizon": 1.95,
        "surfaced_canaries_horizon_delta": -0.08333333333333333,
        "surfaced_total_leaks": 6.483333333333333
      },
      "display_name": "gemini_midsize_shield",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.8,
          "regret": 0.37935,
          "regret_boot_ci_95": [
            0.2895,
            0.47085
          ],
          "regret_gain_boot_ci_95": [
            0.04100000000000001,
            0.2998
          ],
          "regret_gain_vs_default": 0.1703,
          "score": 0.16435
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.765,
          "regret": 0.29710000000000003,
          "regret_boot_ci_95": [
            0.22425,
            0.37075
          ],
          "regret_gain_boot_ci_95": [
            -0.002350000000000006,
            0.20134999999999997
          ],
          "regret_gain_vs_default": 0.10125,
          "score": 0.2466
        },
        "grok_tactics": {
          "accuracy": 0.78,
          "regret": 0.2842,
          "regret_boot_ci_95": [
            0.22755,
            0.34119999999999995
          ],
          "regret_gain_boot_ci_95": [
            -0.019100000000000002,
            0.16745000000000002
          ],
          "regret_gain_vs_default": 0.0741,
          "score": 0.2595
        },
        "heuristic": {
          "accuracy": 0.795,
          "regret": 0.4824,
          "regret_boot_ci_95": [
            0.39714999999999995,
            0.5690500000000001
          ],
          "regret_gain_boot_ci_95": [
            -0.1492,
            0.07709999999999999
          ],
          "regret_gain_vs_default": -0.03670000000000001,
          "score": 0.0613
        },
        "hinted_heuristic": {
          "accuracy": 0.8,
          "regret": 0.19945000000000002,
          "regret_boot_ci_95": [
            0.1359,
            0.26485
          ],
          "regret_gain_boot_ci_95": [
            -0.08535,
            0.0834
          ],
          "regret_gain_vs_default": -0.0032500000000000016,
          "score": 0.34424999999999994
        }
      },
      "is_default": false,
      "lever_id": "midsize_canary_evasion",
      "n_rules": 2,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.29710000000000003,
        "gemini_regret_boot_ci_95": [
          0.22425,
          0.37075
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.002350000000000006,
          0.20134999999999997
        ],
        "gemini_regret_gain_vs_default": 0.10125,
        "mean_regret": 0.3285,
        "mean_regret_gain_vs_default": 0.06114000000000003,
        "min_regret": 0.19945000000000002,
        "min_regret_boot_ci_95": [
          0.1339,
          0.26275
        ],
        "min_regret_gain_boot_ci_95": [
          -0.05630000000000002,
          0.11615
        ],
        "min_regret_gain_vs_default": 0.00360000000000002,
        "strongest_investigator": "hinted_heuristic",
        "strongest_investigator_label": "HintedHeuristic(hard)"
      },
      "solver": {
        "accuracy": 0.96,
        "mean_accuse_day": 9.75,
        "passed": true,
        "ratio_vs_default": 0.9986224630360914,
        "score": 0.5437,
        "score_boot_ci_95": [
          0.5027,
          0.5799
        ],
        "score_ci_95": 0.03840832837972285
      },
      "target_cohort": "gemini_4_carbon"
    },
    "non_decoy_tiebreak_framer": {
      "baselines": {
        "accuse_most_logs_acc": 0.03,
        "accuse_most_logs_score": -0.94375,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.01,
        "logs_only_score": -0.98275,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "eb452649e501ad9f571a7a049b65cf6a",
      "counterfactual": {
        "counterfactual_regret": 0.19251434512847876,
        "counterfactual_regret_gain_vs_default": 0.13219426285398805,
        "inproc_optimal_ev": 0.27178716149043924,
        "inproc_optimal_ev_drop": 0.18863133169789406,
        "inproc_surfaced_canaries": 1.5666666666666667,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.28851748158593654,
        "opencode_optimal_ev_drop": 0.12842386067674869,
        "opencode_surfaced_canaries": 1.8,
        "optimal_ev": 0.2801523215381879,
        "optimal_ev_drop": 0.15852759618732135,
        "p_true_mole": 0.6542909684547357,
        "p_true_mole_drop": 0.16469638989144145,
        "surfaced_canaries": 1.6833333333333333,
        "surfaced_canaries_delta": -0.05,
        "surfaced_canaries_horizon": 1.9333333333333333,
        "surfaced_canaries_horizon_delta": -0.1,
        "surfaced_total_leaks": 6.35
      },
      "display_name": "non_decoy_tiebreak_framer",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.815,
          "regret": 0.26655,
          "regret_boot_ci_95": [
            0.17245000000000002,
            0.3614
          ],
          "regret_gain_boot_ci_95": [
            -0.07550000000000001,
            0.18505
          ],
          "regret_gain_vs_default": 0.0575,
          "score": 0.23385
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.87,
          "regret": 0.11424999999999999,
          "regret_boot_ci_95": [
            0.045599999999999995,
            0.18309999999999998
          ],
          "regret_gain_boot_ci_95": [
            -0.17880000000000001,
            0.015699999999999995
          ],
          "regret_gain_vs_default": -0.0816,
          "score": 0.38615
        },
        "grok_tactics": {
          "accuracy": 0.795,
          "regret": 0.23384999999999997,
          "regret_boot_ci_95": [
            0.1609,
            0.30815000000000003
          ],
          "regret_gain_boot_ci_95": [
            -0.07925,
            0.12364999999999998
          ],
          "regret_gain_vs_default": 0.02374999999999999,
          "score": 0.26655
        },
        "heuristic": {
          "accuracy": 0.785,
          "regret": 0.36585,
          "regret_boot_ci_95": [
            0.2655,
            0.46795000000000003
          ],
          "regret_gain_boot_ci_95": [
            -0.28545000000000004,
            -0.02515000000000002
          ],
          "regret_gain_vs_default": -0.15325,
          "score": 0.13455
        },
        "hinted_heuristic": {
          "accuracy": 0.8,
          "regret": 0.16149999999999998,
          "regret_boot_ci_95": [
            0.0925,
            0.22669999999999998
          ],
          "regret_gain_boot_ci_95": [
            -0.13085000000000002,
            0.046049999999999994
          ],
          "regret_gain_vs_default": -0.04120000000000001,
          "score": 0.3389
        }
      },
      "is_default": false,
      "lever_id": "non_decoy_peer_framing",
      "n_rules": 3,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.11424999999999999,
        "gemini_regret_boot_ci_95": [
          0.045599999999999995,
          0.18309999999999998
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.17880000000000001,
          0.015699999999999995
        ],
        "gemini_regret_gain_vs_default": -0.0816,
        "mean_regret": 0.2284,
        "mean_regret_gain_vs_default": -0.038959999999999995,
        "min_regret": 0.11424999999999999,
        "min_regret_boot_ci_95": [
          0.044349999999999994,
          0.1793
        ],
        "min_regret_gain_boot_ci_95": [
          -0.14465,
          0.03084999999999999
        ],
        "min_regret_gain_vs_default": -0.0816,
        "strongest_investigator": "gemini_carbon_proxy",
        "strongest_investigator_label": "GeminiCarbonProxy"
      },
      "solver": {
        "accuracy": 0.94,
        "mean_accuse_day": 10.091370558375635,
        "passed": true,
        "ratio_vs_default": 0.9190926623197722,
        "score": 0.5004,
        "score_boot_ci_95": [
          0.44789999999999996,
          0.5463
        ],
        "score_ci_95": 0.05050334302801177
      },
      "target_cohort": "frontier_all"
    },
    "reactive_canary_lag": {
      "baselines": {
        "accuse_most_logs_acc": 0.015,
        "accuse_most_logs_score": -0.9725,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.015,
        "logs_only_score": -0.9734999999999999,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "637c34ad367fd384918bcbeb2fa2b16a",
      "counterfactual": {
        "counterfactual_regret": 0.4070385928324931,
        "counterfactual_regret_gain_vs_default": 0.3467185105580024,
        "inproc_optimal_ev": 0.1450741378438483,
        "inproc_optimal_ev_drop": 0.315344355344485,
        "inproc_surfaced_canaries": 1.1333333333333333,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.1941820098244988,
        "opencode_optimal_ev_drop": 0.22275933243818644,
        "opencode_surfaced_canaries": 1.4333333333333333,
        "optimal_ev": 0.16962807383417353,
        "optimal_ev_drop": 0.26905184389133574,
        "p_true_mole": 0.5359592911894882,
        "p_true_mole_drop": 0.28302806715668893,
        "surfaced_canaries": 1.2833333333333334,
        "surfaced_canaries_delta": -0.45,
        "surfaced_canaries_horizon": 1.6166666666666667,
        "surfaced_canaries_horizon_delta": -0.4166666666666667,
        "surfaced_total_leaks": 6.466666666666667
      },
      "display_name": "reactive_canary_lag",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.825,
          "regret": 0.26954999999999996,
          "regret_boot_ci_95": [
            0.17704999999999999,
            0.36485
          ],
          "regret_gain_boot_ci_95": [
            -0.0679,
            0.18719999999999998
          ],
          "regret_gain_vs_default": 0.060500000000000005,
          "score": 0.24585
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.825,
          "regret": 0.22315000000000002,
          "regret_boot_ci_95": [
            0.1461,
            0.3018
          ],
          "regret_gain_boot_ci_95": [
            -0.0768,
            0.13049999999999998
          ],
          "regret_gain_vs_default": 0.027299999999999994,
          "score": 0.29225
        },
        "grok_tactics": {
          "accuracy": 0.82,
          "regret": 0.24285,
          "regret_boot_ci_95": [
            0.17495000000000002,
            0.31115000000000004
          ],
          "regret_gain_boot_ci_95": [
            -0.0682,
            0.13215
          ],
          "regret_gain_vs_default": 0.03275000000000001,
          "score": 0.27255
        },
        "heuristic": {
          "accuracy": 0.73,
          "regret": 0.5448,
          "regret_boot_ci_95": [
            0.45675,
            0.6352
          ],
          "regret_gain_boot_ci_95": [
            -0.0935,
            0.13925
          ],
          "regret_gain_vs_default": 0.025699999999999997,
          "score": -0.0294
        },
        "hinted_heuristic": {
          "accuracy": 0.84,
          "regret": 0.16260000000000002,
          "regret_boot_ci_95": [
            0.0975,
            0.2273
          ],
          "regret_gain_boot_ci_95": [
            -0.12285,
            0.045599999999999995
          ],
          "regret_gain_vs_default": -0.040100000000000004,
          "score": 0.3528
        }
      },
      "is_default": false,
      "lever_id": "reactive_canary_lag_oldest",
      "n_rules": 2,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.22315000000000002,
        "gemini_regret_boot_ci_95": [
          0.1461,
          0.3018
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.0768,
          0.13049999999999998
        ],
        "gemini_regret_gain_vs_default": 0.027299999999999994,
        "mean_regret": 0.28859,
        "mean_regret_gain_vs_default": 0.021230000000000027,
        "min_regret": 0.16260000000000002,
        "min_regret_boot_ci_95": [
          0.09960000000000001,
          0.22155000000000002
        ],
        "min_regret_gain_boot_ci_95": [
          -0.09045,
          0.07519999999999996
        ],
        "min_regret_gain_vs_default": -0.033249999999999974,
        "strongest_investigator": "hinted_heuristic",
        "strongest_investigator_label": "HintedHeuristic(hard)"
      },
      "solver": {
        "accuracy": 0.945,
        "mean_accuse_day": 10.072164948453608,
        "passed": true,
        "ratio_vs_default": 0.9466434015979428,
        "score": 0.5154,
        "score_boot_ci_95": [
          0.47064999999999996,
          0.5547
        ],
        "score_ci_95": 0.041854109849289375
      },
      "target_cohort": "gemini_4_carbon"
    },
    "surgical_trap_shield": {
      "baselines": {
        "accuse_most_logs_acc": 0.02,
        "accuse_most_logs_score": -0.96325,
        "all_passed": true,
        "do_nothing_max_abs": 0.0,
        "do_nothing_score": 0.0,
        "logs_only_acc": 0.015,
        "logs_only_score": -0.97425,
        "stop_early_quit_max_abs": 0.0,
        "stop_early_quit_score": 0.0,
        "stop_early_quit_unfinished_score": 0.0
      },
      "behavior_hash": "e55c0473d2685c858c818e49bab106a1",
      "counterfactual": {
        "counterfactual_regret": 0.21792821942859125,
        "counterfactual_regret_gain_vs_default": 0.15760813715410055,
        "inproc_optimal_ev": 0.2499093726313595,
        "inproc_optimal_ev_drop": 0.2105091205569738,
        "inproc_surfaced_canaries": 1.5,
        "n_transcripts": 60,
        "opencode_optimal_ev": 0.30756752184479136,
        "opencode_optimal_ev_drop": 0.10937382041789387,
        "opencode_surfaced_canaries": 1.9,
        "optimal_ev": 0.27873844723807545,
        "optimal_ev_drop": 0.15994147048743382,
        "p_true_mole": 0.6906799746049128,
        "p_true_mole_drop": 0.12830738374126435,
        "surfaced_canaries": 1.7,
        "surfaced_canaries_delta": -0.03333333333333333,
        "surfaced_canaries_horizon": 2.066666666666667,
        "surfaced_canaries_horizon_delta": 0.03333333333333333,
        "surfaced_total_leaks": 6.45
      },
      "display_name": "surgical_trap_shield",
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.825,
          "regret": 0.3056,
          "regret_boot_ci_95": [
            0.20895,
            0.4034
          ],
          "regret_gain_boot_ci_95": [
            -0.030149999999999996,
            0.2208
          ],
          "regret_gain_vs_default": 0.09655000000000001,
          "score": 0.26755
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.835,
          "regret": 0.19535,
          "regret_boot_ci_95": [
            0.1313,
            0.2612
          ],
          "regret_gain_boot_ci_95": [
            -0.09325000000000001,
            0.0919
          ],
          "regret_gain_vs_default": -0.0005000000000000046,
          "score": 0.3778
        },
        "grok_tactics": {
          "accuracy": 0.84,
          "regret": 0.20475000000000002,
          "regret_boot_ci_95": [
            0.1422,
            0.2644
          ],
          "regret_gain_boot_ci_95": [
            -0.09945,
            0.08410000000000001
          ],
          "regret_gain_vs_default": -0.005350000000000004,
          "score": 0.36840000000000006
        },
        "heuristic": {
          "accuracy": 0.81,
          "regret": 0.5031,
          "regret_boot_ci_95": [
            0.41755000000000003,
            0.5908
          ],
          "regret_gain_boot_ci_95": [
            -0.13094999999999998,
            0.09705
          ],
          "regret_gain_vs_default": -0.016000000000000007,
          "score": 0.07005
        },
        "hinted_heuristic": {
          "accuracy": 0.815,
          "regret": 0.21050000000000002,
          "regret_boot_ci_95": [
            0.14639999999999997,
            0.27505
          ],
          "regret_gain_boot_ci_95": [
            -0.0671,
            0.08175
          ],
          "regret_gain_vs_default": 0.007799999999999998,
          "score": 0.36265000000000003
        }
      },
      "is_default": false,
      "lever_id": "low_recipient_surgical_shield",
      "n_rules": 3,
      "passed": true,
      "regret_summary": {
        "gemini_regret": 0.19535,
        "gemini_regret_boot_ci_95": [
          0.1313,
          0.2612
        ],
        "gemini_regret_gain_boot_ci_95": [
          -0.09325000000000001,
          0.0919
        ],
        "gemini_regret_gain_vs_default": -0.0005000000000000046,
        "mean_regret": 0.28386,
        "mean_regret_gain_vs_default": 0.016500000000000015,
        "min_regret": 0.19535,
        "min_regret_boot_ci_95": [
          0.12480000000000001,
          0.23215
        ],
        "min_regret_gain_boot_ci_95": [
          -0.060100000000000015,
          0.0854
        ],
        "min_regret_gain_vs_default": -0.0005000000000000004,
        "strongest_investigator": "gemini_carbon_proxy",
        "strongest_investigator_label": "GeminiCarbonProxy"
      },
      "solver": {
        "accuracy": 0.97,
        "mean_accuse_day": 9.2,
        "passed": true,
        "ratio_vs_default": 1.0527137478188997,
        "score": 0.5731499999999999,
        "score_boot_ci_95": [
          0.527,
          0.6135499999999999
        ],
        "score_ci_95": 0.04266941046660756
      },
      "target_cohort": "codex_gpt55"
    }
  },
  "strategy_order": [
    "default_v0",
    "surgical_trap_shield",
    "gemini_midsize_shield",
    "reactive_canary_lag",
    "non_decoy_tiebreak_framer",
    "early_burst_midgame_pace",
    "frontier_synthesis_v14"
  ],
  "tier": "hard",
  "tiers_version": "v1.4",
  "transcript_strategy_order": [
    "surgical_trap_shield",
    "gemini_midsize_shield",
    "reactive_canary_lag",
    "non_decoy_tiebreak_framer",
    "early_burst_midgame_pace",
    "frontier_synthesis_v14"
  ]
}
```
<!-- MOLE_STRATEGIES_V14_LEDGER_END -->
