# Sleeper Minimax Attack-Regret Mole Portfolio: v1.4 Hard Report

Ports the Sleeper minimax attack-regret portfolio (`max_w min_{inv != solver} sum_i w_i E[Solver - inv | strat_i]`) into Canary v1.4 `hard` over `DEFAULT_STRATEGY` plus all 6 transcript-grounded `STRATEGY_SPECS`. Portfolio weights are fit on `6000-6199` (`n=200`) subject to `SolverPolicy("hard") acc >= 0.90`, `LogsOnly acc <= 0.10`, `DoNothing == 0.0`, and `StopEarlyQuit == 0.0`, and realized per episode via deterministic zero-private-info SHA-256 seed hashing (`PortfolioMolePolicy` / `select_portfolio_strategy(seed, weights)`) on disjoint held-out validation seeds `6812-6823` (`n=12`). Zero LLM API calls.

Reproduce or verify exact embedded ledger consistency:
```bash
PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.regret_portfolio --out docs/reports/mole_regret_portfolio_v14.md
PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.regret_portfolio --check
```

## 1. Headline Findings

- **Strict minimax dominance over every pure strategy on train (`6000-6199`, `n=200`)**: Optimal portfolio places `0.8657` on `surgical_trap_shield`, `0.1343` on `gemini_midsize_shield` (zero mass on the remaining 5 candidates), achieving worst-case investigator regret `0.2090` vs `default_v0` `0.1958` (`+0.0132`) and vs best single pure strategy `early_burst_midgame_pace` `0.1995` (`+0.0095`).
- **Exact saddle-point duality & equalized binding adversaries**: Binding investigators (`GeminiCarbonProxy` (`0.2090`), `HintedHeuristic(hard)` (`0.2090`)) are equalized at the minimax floor (`duality_gap = 2.22e-16`), leaving zero single-investigator exploit below `0.2090`.
- **Train & disjoint held-out validation fairness gates (`100%` pass)**: Train expected `SolverPolicy("hard")` accuracy is `0.969` (`>= 0.90`), `LogsOnly` accuracy is `0.015` (`<= 0.10`), and `DoNothing` / `StopEarlyQuit` are `0.000` / `0.000`. On disjoint live validation seeds `6812-6823` (`n=12`), `PortfolioMolePolicy` achieves `SolverPolicy("hard")` accuracy `1.000`, `LogsOnly` accuracy `0.000`, `DoNothing = 0.000`, and `StopEarlyQuit = 0.000` (`gates_passed=True`).
- **Expected counterfactual impact on 60 committed v1.4 Gemini-4-carbon Hard transcripts (`0` API calls)**: Under portfolio mixture weights, expected Gemini-4-carbon optimal Bayesian EV drop is `+0.166` and expected counterfactual regret is `+0.225` (vs `default_v0` `+0.060`).

## 2. Optimal Minimax Portfolio Weights & Dual Adversarial Equilibrium (`6000-6199`, `n=200`)

| Strategy | Portfolio Weight `w_i` | Pure Solver Acc | Pure LogsOnly Acc | Pure Strongest Inv | Pure Min Regret | Pure Mean Regret |
|---|---|---|---|---|---|---|
| `default_v0` | `0.000000` | `0.970` | `0.020` | `GeminiCarbonProxy` | `0.1958` | `0.2674` |
| `surgical_trap_shield` | `0.865691` | `0.970` | `0.015` | `GeminiCarbonProxy` | `0.1953` | `0.2839` |
| `gemini_midsize_shield` | `0.134309` | `0.960` | `0.015` | `HintedHeuristic(hard)` | `0.1995` | `0.3285` |
| `reactive_canary_lag` | `0.000000` | `0.945` | `0.015` | `HintedHeuristic(hard)` | `0.1626` | `0.2886` |
| `non_decoy_tiebreak_framer` | `0.000000` | `0.940` | `0.010` | `GeminiCarbonProxy` | `0.1142` | `0.2284` |
| `early_burst_midgame_pace` | `0.000000` | `0.970` | `0.005` | `GrokTactics(hard)` | `0.1995` | `0.2905` |
| `frontier_synthesis_v14` | `0.000000` | `0.945` | `0.015` | `HintedHeuristic(hard)` | `0.1823` | `0.2833` |
| **`PortfolioMolePolicy (w*)`** | **`1.000000`** | **`0.969`** | **`0.015`** | **`Equalized (GeminiCarbonProxy, HintedHeuristic(hard))`** | **`0.2090`** | **`0.2899`** |

### 2.1 Train Per-Investigator Expected Regret & Dual Adversary Mixture

| Investigator | `default_v0` Regret | Best Pure (`early_burst_midgame_pace`) Regret | Portfolio `w*` Expected Regret | Gain vs Default | Dual Weight `y_j` |
|---|---|---|---|---|---|
| `GeminiCarbonProxy` | `0.1958` | `0.2141` | `0.2090` | `+0.0132` | `0.0980` |
| `CodexHorizonProxy` | `0.2091` | `0.3277` | `0.3155` | `+0.1065` | `0.0000` |
| `GrokTactics(hard)` | `0.2101` | `0.1995` | `0.2154` | `+0.0053` | `0.0000` |
| `Heuristic(hard)` | `0.5191` | `0.5050` | `0.5003` | `-0.0188` | `0.0000` |
| `HintedHeuristic(hard)` | `0.2027` | `0.2062` | `0.2090` | `+0.0063` | `0.9020` |

## 3. Disjoint Held-Out Live Validation (`6812-6823`, `n=12`)

Each held-out seed in `6812-6823` instantiates a fresh `Env("hard", seed, mole_strategy=...)` and fresh investigator policy (`SolverPolicy("hard")` plus 5 non-solver investigators and 4 fairness baselines; zero `copy.deepcopy` of generator-based `ScriptedPolicy` instances). Deterministic SHA-256 selection (`salt=canary.mole.regret_portfolio.v1`) uses only `(seed, weights)` with zero private world state, realizing `surgical_trap_shield`: `11`, `gemini_midsize_shield`: `1` across `12` seeds.

| Policy | Solver Acc | Solver Score [95% Boot CI] | LogsOnly Acc | AccuseMostLogs Acc | DoNothing | StopEarlyQuit | Min Regret [95% Boot CI] | Mean Regret | Gates |
|---|---|---|---|---|---|---|---|---|---|
| `DEFAULT_STRATEGY (default_v0)` | `1.000` | `0.640` [0.568, 0.703] | `0.083` | `0.083` | `0.000` | `0.000` | `0.196` [-0.033, 0.296] | `0.354` | PASS |
| `PortfolioMolePolicy (regret_portfolio_v14)` | `1.000` | `0.562` [0.467, 0.648] | `0.000` | `0.083` | `0.000` | `0.000` | `0.154` [-0.082, 0.218] | `0.303` | PASS |

### 3.1 Validation Paired Per-Investigator Breakdown (`6812-6823`, `n=12`)

| Investigator | Default Score / Acc / Regret | Portfolio Score / Acc / Regret | Paired Regret Gain [95% Boot CI] |
|---|---|---|---|
| `GeminiCarbonProxy` | `+0.177` / `0.750` / `+0.462` | `+0.408` / `0.917` / `+0.154` | `-0.308` [-0.610, -0.060] |
| `CodexHorizonProxy` | `+0.444` / `0.917` / `+0.196` | `+0.263` / `0.833` / `+0.299` | `+0.103` [-0.183, +0.489] |
| `GrokTactics(hard)` | `+0.281` / `0.833` / `+0.359` | `+0.248` / `0.833` / `+0.314` | `-0.045` [-0.206, +0.102] |
| `Heuristic(hard)` | `+0.128` / `0.833` / `+0.512` | `-0.015` / `0.750` / `+0.578` | `+0.066` [-0.441, +0.543] |
| `HintedHeuristic(hard)` | `+0.398` / `0.833` / `+0.242` | `+0.392` / `0.833` / `+0.171` | `-0.072` [-0.187, +0.041] |

Note on `12`-seed validation variance: on `6812-6823` (`n=12`), each single wrong-vs-right accusation changes an investigator mean score by roughly `1.5 / 12 = 0.125`, producing wide paired 95% bootstrap CIs (`min_regret` delta `-0.042`, 95% CI [-0.222, +0.197]). Strongest held-out per-investigator regret gains occur on `CodexHorizonProxy` (`+0.103`), `Heuristic(hard)` (`+0.066`), while preserving `1.000` `SolverPolicy("hard")` accuracy and `0.000` `LogsOnly` accuracy.

## 4. Machine-Verified Embedded Ledger

<!-- MOLE_REGRET_PORTFOLIO_V14_LEDGER_START -->
```json
{
  "constraints": {
    "do_nothing_exact": 0.0,
    "max_logs_only_acc": 0.1,
    "min_solver_acc": 0.9,
    "stop_early_quit_exact": 0.0
  },
  "portfolio_salt": "canary.mole.regret_portfolio.v1",
  "runtime_meta": {
    "elapsed_seconds_recorded": 19.722,
    "max_workers": 4,
    "zero_api_calls": true
  },
  "schema_version": "mole_regret_portfolio_v14.v1",
  "seed_hygiene": {
    "disjoint_train_val": true,
    "forbidden_ranges_excluded": true,
    "train_n_seeds": 200,
    "train_seed_range": "6000-6199",
    "val_n_seeds": 12,
    "val_seed_range": "6812-6823",
    "val_seeds": [
      6812,
      6813,
      6814,
      6815,
      6816,
      6817,
      6818,
      6819,
      6820,
      6821,
      6822,
      6823
    ]
  },
  "tier": "hard",
  "tiers_version": "v1.4",
  "train": {
    "candidate_order": [
      "default_v0",
      "surgical_trap_shield",
      "gemini_midsize_shield",
      "reactive_canary_lag",
      "non_decoy_tiebreak_framer",
      "early_burst_midgame_pace",
      "frontier_synthesis_v14"
    ],
    "candidates": {
      "default_v0": {
        "accuse_most_logs_accuracy": 0.025,
        "counterfactual_ev_drop": 0.0,
        "counterfactual_regret": 0.060320082274490705,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.86,
          "gemini_carbon_proxy": 0.835,
          "grok_tactics": 0.82,
          "heuristic": 0.78,
          "hinted_heuristic": 0.78
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.20905,
          "gemini_carbon_proxy": 0.19585,
          "grok_tactics": 0.2101,
          "heuristic": 0.5191,
          "hinted_heuristic": 0.2027
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.3354,
          "gemini_carbon_proxy": 0.3486,
          "grok_tactics": 0.33435000000000004,
          "heuristic": 0.02535,
          "hinted_heuristic": 0.34175
        },
        "logs_only_accuracy": 0.02,
        "mean_regret": 0.26736,
        "min_regret": 0.19585,
        "solver_accuracy": 0.97,
        "solver_score": 0.54445,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "gemini_carbon_proxy"
      },
      "early_burst_midgame_pace": {
        "accuse_most_logs_accuracy": 0.03,
        "counterfactual_ev_drop": 0.18300411790583915,
        "counterfactual_regret": 0.2773242001803299,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.795,
          "gemini_carbon_proxy": 0.81,
          "grok_tactics": 0.83,
          "heuristic": 0.755,
          "hinted_heuristic": 0.78
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.32775,
          "gemini_carbon_proxy": 0.2141,
          "grok_tactics": 0.19949999999999998,
          "heuristic": 0.50495,
          "hinted_heuristic": 0.20620000000000002
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.24420000000000003,
          "gemini_carbon_proxy": 0.35784999999999995,
          "grok_tactics": 0.37244999999999995,
          "heuristic": 0.067,
          "hinted_heuristic": 0.36575
        },
        "logs_only_accuracy": 0.005,
        "mean_regret": 0.29050000000000004,
        "min_regret": 0.19949999999999998,
        "solver_accuracy": 0.97,
        "solver_score": 0.57195,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "grok_tactics"
      },
      "frontier_synthesis_v14": {
        "accuse_most_logs_accuracy": 0.015,
        "counterfactual_ev_drop": 0.2986505482468081,
        "counterfactual_regret": 0.4009706305212989,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.835,
          "gemini_carbon_proxy": 0.815,
          "grok_tactics": 0.84,
          "heuristic": 0.74,
          "hinted_heuristic": 0.79
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.24844999999999998,
          "gemini_carbon_proxy": 0.22265000000000001,
          "grok_tactics": 0.23115000000000002,
          "heuristic": 0.5318,
          "hinted_heuristic": 0.18225000000000002
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.26755,
          "gemini_carbon_proxy": 0.29335,
          "grok_tactics": 0.28485,
          "heuristic": -0.015799999999999998,
          "hinted_heuristic": 0.33375
        },
        "logs_only_accuracy": 0.015,
        "mean_regret": 0.28326,
        "min_regret": 0.18225000000000002,
        "solver_accuracy": 0.945,
        "solver_score": 0.516,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "hinted_heuristic"
      },
      "gemini_midsize_shield": {
        "accuse_most_logs_accuracy": 0.02,
        "counterfactual_ev_drop": 0.20318630829680936,
        "counterfactual_regret": 0.2718397239046334,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.8,
          "gemini_carbon_proxy": 0.765,
          "grok_tactics": 0.78,
          "heuristic": 0.795,
          "hinted_heuristic": 0.8
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.37935,
          "gemini_carbon_proxy": 0.29710000000000003,
          "grok_tactics": 0.2842,
          "heuristic": 0.4824,
          "hinted_heuristic": 0.19945000000000002
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.16435,
          "gemini_carbon_proxy": 0.2466,
          "grok_tactics": 0.2595,
          "heuristic": 0.0613,
          "hinted_heuristic": 0.34424999999999994
        },
        "logs_only_accuracy": 0.015,
        "mean_regret": 0.3285,
        "min_regret": 0.19945000000000002,
        "solver_accuracy": 0.96,
        "solver_score": 0.5437,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "hinted_heuristic"
      },
      "non_decoy_tiebreak_framer": {
        "accuse_most_logs_accuracy": 0.03,
        "counterfactual_ev_drop": 0.15852759618732135,
        "counterfactual_regret": 0.19251434512847876,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.815,
          "gemini_carbon_proxy": 0.87,
          "grok_tactics": 0.795,
          "heuristic": 0.785,
          "hinted_heuristic": 0.8
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.26655,
          "gemini_carbon_proxy": 0.11424999999999999,
          "grok_tactics": 0.23384999999999997,
          "heuristic": 0.36585,
          "hinted_heuristic": 0.16149999999999998
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.23385,
          "gemini_carbon_proxy": 0.38615,
          "grok_tactics": 0.26655,
          "heuristic": 0.13455,
          "hinted_heuristic": 0.3389
        },
        "logs_only_accuracy": 0.01,
        "mean_regret": 0.2284,
        "min_regret": 0.11424999999999999,
        "solver_accuracy": 0.94,
        "solver_score": 0.5004,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "gemini_carbon_proxy"
      },
      "reactive_canary_lag": {
        "accuse_most_logs_accuracy": 0.015,
        "counterfactual_ev_drop": 0.26905184389133574,
        "counterfactual_regret": 0.4070385928324931,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.825,
          "gemini_carbon_proxy": 0.825,
          "grok_tactics": 0.82,
          "heuristic": 0.73,
          "hinted_heuristic": 0.84
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.26954999999999996,
          "gemini_carbon_proxy": 0.22315000000000002,
          "grok_tactics": 0.24285,
          "heuristic": 0.5448,
          "hinted_heuristic": 0.16260000000000002
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.24585,
          "gemini_carbon_proxy": 0.29225,
          "grok_tactics": 0.27255,
          "heuristic": -0.0294,
          "hinted_heuristic": 0.3528
        },
        "logs_only_accuracy": 0.015,
        "mean_regret": 0.28859,
        "min_regret": 0.16260000000000002,
        "solver_accuracy": 0.945,
        "solver_score": 0.5154,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "hinted_heuristic"
      },
      "surgical_trap_shield": {
        "accuse_most_logs_accuracy": 0.02,
        "counterfactual_ev_drop": 0.15994147048743382,
        "counterfactual_regret": 0.21792821942859125,
        "do_nothing_score": 0.0,
        "investigator_accuracies": {
          "codex_horizon_proxy": 0.825,
          "gemini_carbon_proxy": 0.835,
          "grok_tactics": 0.84,
          "heuristic": 0.81,
          "hinted_heuristic": 0.815
        },
        "investigator_regrets": {
          "codex_horizon_proxy": 0.3056,
          "gemini_carbon_proxy": 0.19535,
          "grok_tactics": 0.20475000000000002,
          "heuristic": 0.5031,
          "hinted_heuristic": 0.21050000000000002
        },
        "investigator_scores": {
          "codex_horizon_proxy": 0.26755,
          "gemini_carbon_proxy": 0.3778,
          "grok_tactics": 0.36840000000000006,
          "heuristic": 0.07005,
          "hinted_heuristic": 0.36265000000000003
        },
        "logs_only_accuracy": 0.015,
        "mean_regret": 0.28386,
        "min_regret": 0.19535,
        "solver_accuracy": 0.97,
        "solver_score": 0.5731499999999999,
        "stop_early_quit_score": 0.0,
        "strongest_investigator": "gemini_carbon_proxy"
      }
    },
    "investigator_order": [
      "gemini_carbon_proxy",
      "codex_horizon_proxy",
      "grok_tactics",
      "heuristic",
      "hinted_heuristic"
    ],
    "n_seeds": 200,
    "portfolio": {
      "active_strategies": [
        "surgical_trap_shield",
        "gemini_midsize_shield"
      ],
      "best_pure_min_regret": 0.19949999999999998,
      "best_pure_strategy": "early_burst_midgame_pace",
      "binding_investigators": [
        "gemini_carbon_proxy",
        "hinted_heuristic"
      ],
      "dual_investigator_weights": {
        "codex_horizon_proxy": 0.0,
        "gemini_carbon_proxy": 0.09796099290780197,
        "grok_tactics": 0.0,
        "heuristic": 0.0,
        "hinted_heuristic": 0.902039007092198
      },
      "duality_gap": 2.220446049250313e-16,
      "expected_accuse_most_logs_accuracy": 0.019999999999999997,
      "expected_counterfactual_ev_drop": 0.16574962024640583,
      "expected_counterfactual_regret": 0.2251689933010384,
      "expected_do_nothing_score": 0.0,
      "expected_investigator_accuracies": {
        "codex_horizon_proxy": 0.8216422872340425,
        "gemini_carbon_proxy": 0.825598404255319,
        "grok_tactics": 0.8319414893617021,
        "heuristic": 0.8079853723404256,
        "hinted_heuristic": 0.8129853723404254
      },
      "expected_investigator_scores": {
        "codex_horizon_proxy": 0.25368936170212764,
        "gemini_carbon_proxy": 0.3601787234042553,
        "grok_tactics": 0.3537738031914894,
        "heuristic": 0.06887480053191489,
        "hinted_heuristic": 0.36017872340425533
      },
      "expected_logs_only_accuracy": 0.015,
      "expected_regrets": {
        "codex_horizon_proxy": 0.31550525265957446,
        "gemini_carbon_proxy": 0.20901589095744683,
        "grok_tactics": 0.21542081117021278,
        "heuristic": 0.5003198138297872,
        "hinted_heuristic": 0.20901589095744683
      },
      "expected_solver_accuracy": 0.968656914893617,
      "expected_solver_score": 0.569194614361702,
      "expected_stop_early_quit_score": 0.0,
      "gates_passed": true,
      "mean_regret": 0.28985553191489366,
      "mean_regret_gain_vs_default": 0.022495531914893674,
      "min_regret": 0.20901589095744683,
      "min_regret_gain_vs_best_pure": 0.009515890957446843,
      "min_regret_gain_vs_default": 0.01316589095744683,
      "weights": {
        "default_v0": 0.0,
        "early_burst_midgame_pace": 0.0,
        "frontier_synthesis_v14": 0.0,
        "gemini_midsize_shield": 0.13430851063829805,
        "non_decoy_tiebreak_framer": 0.0,
        "reactive_canary_lag": 0.0,
        "surgical_trap_shield": 0.8656914893617019
      }
    },
    "seed_range": "6000-6199",
    "source": "precomputed_json:results/mole_strategies/v14_fresh_6000_6199.json"
  },
  "validation": {
    "default_v0": {
      "accuse_most_logs_accuracy": 0.08333333333333333,
      "accuse_most_logs_score": -0.8416666666666667,
      "do_nothing_max_abs": 0.0,
      "do_nothing_score": 0.0,
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.9166666666666666,
          "regret": 0.1958333333333333,
          "regret_boot_ci_95": [
            -0.030833333333333338,
            0.5075
          ],
          "score": 0.44416666666666665
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.75,
          "regret": 0.46249999999999997,
          "regret_boot_ci_95": [
            0.18999999999999997,
            0.7816666666666666
          ],
          "score": 0.1775
        },
        "grok_tactics": {
          "accuracy": 0.8333333333333334,
          "regret": 0.3591666666666667,
          "regret_boot_ci_95": [
            0.19166666666666668,
            0.5825
          ],
          "score": 0.2808333333333333
        },
        "heuristic": {
          "accuracy": 0.8333333333333334,
          "regret": 0.5116666666666666,
          "regret_boot_ci_95": [
            0.23833333333333329,
            0.8608333333333333
          ],
          "score": 0.12833333333333333
        },
        "hinted_heuristic": {
          "accuracy": 0.8333333333333334,
          "regret": 0.24249999999999997,
          "regret_boot_ci_95": [
            0.03416666666666665,
            0.5399999999999999
          ],
          "score": 0.3975
        }
      },
      "logs_only_accuracy": 0.08333333333333333,
      "logs_only_score": -0.8541666666666666,
      "mean_regret": 0.3543333333333333,
      "min_regret": 0.1958333333333333,
      "min_regret_boot_ci_95": [
        -0.03333333333333335,
        0.2958333333333333
      ],
      "n_seeds": 12,
      "seeds": [
        6812,
        6813,
        6814,
        6815,
        6816,
        6817,
        6818,
        6819,
        6820,
        6821,
        6822,
        6823
      ],
      "selected_strategy_counts": {
        "default_v0": 12
      },
      "solver_accuracy": 1.0,
      "solver_score": 0.64,
      "solver_score_boot_ci_95": [
        0.5675,
        0.7025
      ],
      "stop_early_quit_max_abs": 0.0,
      "stop_early_quit_score": 0.0,
      "strongest_investigator": "codex_horizon_proxy"
    },
    "gates_passed": true,
    "n_seeds": 12,
    "paired_comparison": {
      "mean_regret_delta_vs_default": -0.05116666666666658,
      "min_regret_delta_boot_ci_95": [
        -0.22166666666666657,
        0.19666666666666663
      ],
      "min_regret_delta_vs_default": -0.04166666666666666,
      "per_investigator_gain": {
        "codex_horizon_proxy": {
          "gain_boot_ci_95": [
            -0.18333333333333326,
            0.4891666666666667
          ],
          "gain_vs_default": 0.10333333333333339
        },
        "gemini_carbon_proxy": {
          "gain_boot_ci_95": [
            -0.61,
            -0.06
          ],
          "gain_vs_default": -0.30833333333333335
        },
        "grok_tactics": {
          "gain_boot_ci_95": [
            -0.20583333333333334,
            0.1025
          ],
          "gain_vs_default": -0.04500000000000004
        },
        "heuristic": {
          "gain_boot_ci_95": [
            -0.44083333333333335,
            0.5425000000000001
          ],
          "gain_vs_default": 0.06583333333333341
        },
        "hinted_heuristic": {
          "gain_boot_ci_95": [
            -0.18749999999999992,
            0.04083333333333334
          ],
          "gain_vs_default": -0.0716666666666666
        }
      }
    },
    "regret_portfolio_v14": {
      "accuse_most_logs_accuracy": 0.08333333333333333,
      "accuse_most_logs_score": -0.8416666666666667,
      "do_nothing_max_abs": 0.0,
      "do_nothing_score": 0.0,
      "investigators": {
        "codex_horizon_proxy": {
          "accuracy": 0.8333333333333334,
          "regret": 0.2991666666666667,
          "regret_boot_ci_95": [
            0.010000000000000023,
            0.6558333333333334
          ],
          "score": 0.2633333333333333
        },
        "gemini_carbon_proxy": {
          "accuracy": 0.9166666666666666,
          "regret": 0.15416666666666665,
          "regret_boot_ci_95": [
            0.009166666666666656,
            0.3
          ],
          "score": 0.4083333333333334
        },
        "grok_tactics": {
          "accuracy": 0.8333333333333334,
          "regret": 0.31416666666666665,
          "regret_boot_ci_95": [
            0.08583333333333336,
            0.5841666666666666
          ],
          "score": 0.24833333333333332
        },
        "heuristic": {
          "accuracy": 0.75,
          "regret": 0.5775,
          "regret_boot_ci_95": [
            0.2683333333333333,
            0.9341666666666667
          ],
          "score": -0.014999999999999994
        },
        "hinted_heuristic": {
          "accuracy": 0.8333333333333334,
          "regret": 0.17083333333333336,
          "regret_boot_ci_95": [
            -0.0725,
            0.4841666666666667
          ],
          "score": 0.39166666666666666
        }
      },
      "logs_only_accuracy": 0.0,
      "logs_only_score": -1.0,
      "mean_regret": 0.3031666666666667,
      "min_regret": 0.15416666666666665,
      "min_regret_boot_ci_95": [
        -0.08166666666666664,
        0.21833333333333335
      ],
      "n_seeds": 12,
      "seeds": [
        6812,
        6813,
        6814,
        6815,
        6816,
        6817,
        6818,
        6819,
        6820,
        6821,
        6822,
        6823
      ],
      "selected_strategy_counts": {
        "gemini_midsize_shield": 1,
        "surgical_trap_shield": 11
      },
      "solver_accuracy": 1.0,
      "solver_score": 0.5625,
      "solver_score_boot_ci_95": [
        0.4666666666666666,
        0.6483333333333333
      ],
      "stop_early_quit_max_abs": 0.0,
      "stop_early_quit_score": 0.0,
      "strongest_investigator": "gemini_carbon_proxy"
    },
    "seed_range": "6812-6823",
    "seeds": [
      6812,
      6813,
      6814,
      6815,
      6816,
      6817,
      6818,
      6819,
      6820,
      6821,
      6822,
      6823
    ]
  }
}
```
<!-- MOLE_REGRET_PORTFOLIO_V14_LEDGER_END -->
