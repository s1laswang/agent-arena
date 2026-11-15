# Transcript-Distilled + Constrained Frontier RLMole (`rl_mole_frontier_v14`)

## 1. Executive Summary

- **Artifact**: `data/forge/rl_mole_frontier_v14.json` (`kind="rl_mole"`, `name="rl_mole_frontier_v14"`, `hidden=20`, `greedy=True`, loadable via `RLMole.from_json` and `canary.forge_track._strategy`).
- **Execution Discipline**: CPU-only `numpy`, strict `--workers 1`, `0` API calls, training seeds strictly in `110000+` (`TRAIN_SEEDS`), disjoint fresh held-out validation on `210020-210026` (`n=7`, strictly avoiding `0-59`, `30000-30199`, `800000+`, `900000+`), and counterfactual replay on `8` committed v1.4 Gemini-4-carbon Hard episodes (`4` OpenCode MCP + `4` in-proc, seeds `0-3`).
- **Held-Out Frontier Regret (`210020-210026`, `n=7`)**: `SolverPolicy` accuracy `100.0%` (gate `>= 85.0%`), `SolverPolicy` score `0.4957 +/- 0.1383`, `LogsOnly` accuracy `0.0%` (gate `<= 10.0%`), `DoNothing` score `0.000` (gate `== 0.000`), 5-investigator worst-case `min_regret = -0.1157` (`+0.0129` vs `default_v0`, `+0.0000` vs `frontier_synthesis_v14`), `mean_regret = +0.2483` (`+0.2157` vs `default_v0`).
- **7-Check `canary.mole.fairness_audit`**: `7/7` checks passed (`all_passed=True`, `fairness_passed=True`, `canonical_sha256=4cba7ca438d64f1f`).
- **Counterfactual 8 Committed v1.4 Gemini Hard Episodes (`4` OpenCode + `4` in-proc, seeds `0-3`)**: Posterior `P(true mole)` at accuse day drops by `+0.3230` (from `0.8347` to `0.5117`), optimal Bayesian accuse EV drops by `+0.3060`, and counterfactual Solver-vs-Gemini gap rises to `+0.5015` (`+0.4160` gain over `default_v0`) while `SolverPolicy` retains `100.0%` accuracy (`+0.6575` score).

## 2. Two-Stage Training Pipeline (0 API Calls, `--workers 1`, Seeds `110000+`)

### 2.1 Stage 1: Behavioral Cloning of `frontier_synthesis_v14` over `MoleView` States

- **Teacher Strategy**: `frontier_synthesis_v14` (`canary.mole.strategies`)
- **Rollout Seed Slice**: `110000-110002` (`n=3` seeds, `374` rollout `MoleView` states + `3405` boundary states -> `3710` unique weighted feature-label tuples)
- **MLP Architecture**: `11 -> 20 (tanh) -> (6 leak logits, 4 frame logits)` (`RLMole` exact schema)
- **Cloning Fidelity on Empirical `MoleView` Rollouts**: leak selector accuracy `100.00%`, frame selector accuracy `100.00%`, joint `(leak, frame)` exact match `100.00%`, cross-entropy `0.1162` (`5.68s`)

### 2.2 Stage 2: Constrained Single-Process `CEM` Refinement

- **Investigator Adversary Suite**: `GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`, `HintedHeuristic`, `Heuristic`
- **Hard Constraints**: `SolverPolicy acc >= 0.85`, `LogsOnly acc <= 0.10`, `AccuseMostLogs acc <= 0.10`, `DoNothing == 0.00`, `SolverPolicy score >= 0.50 * baseline_solver_score`
- **Train-Selection Checkpoint (`110510-110516`, `n=7`)**: selected `bc_init` with `objective=-11.6786`, `solver_acc=100.0%`, `solver_score=+0.5829`, `logs_only_acc=14.3%`, `min_regret=+0.3571` (`+0.3657` vs `default_v0`), `mean_regret=+0.4957`

| Iter | Feasible | Objective | Solver Score | Solver Acc | LogsOnly Acc | Min Regret | Mean Regret | Elapsed (s) |
|---|---|---|---|---|---|---|---|---|
| 0 | True | +0.3204 | +0.6371 | 100.0% | 0.0% | +0.2329 | +0.4583 | 15.79 |

## 3. Held-Out Validation on Seeds `210020-210026` (`n=7`, `--workers 1`)

### 3.1 Summary Across Mole Policies

| Mole Policy | Kind | Solver Score +/- CI | Solver Acc | LogsOnly Acc | AccuseMostLogs Acc | DoNothing | Strongest Investigator | Min Regret (Gain) | Mean Regret (Gain) | Frontier Proxy Regret | Feasible |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `dsl` | +0.3871 +/- 0.4675 | 85.7% | 0.0% | 0.0% | 0.000 | `codex_horizon_proxy` | -0.1286 (+0.0000) | +0.0326 (+0.0000) | -0.1236 | PASS |
| `frontier_synthesis_v14` | `dsl` | +0.4957 +/- 0.1383 | 100.0% | 0.0% | 0.0% | 0.000 | `gemini_carbon_proxy` | -0.1157 (+0.0129) | +0.2300 (+0.1974) | +0.2429 | PASS |
| `rl_mole_bc_v14` | `rl_mole` | +0.4957 +/- 0.1383 | 100.0% | 0.0% | 0.0% | 0.000 | `gemini_carbon_proxy` | -0.1157 (+0.0129) | +0.2483 (+0.2157) | +0.2436 | PASS |
| `rl_mole_frontier_v14` | `rl_mole` | +0.4957 +/- 0.1383 | 100.0% | 0.0% | 0.0% | 0.000 | `gemini_carbon_proxy` | -0.1157 (+0.0129) | +0.2483 (+0.2157) | +0.2436 | PASS |

### 3.2 Per-Investigator Breakdown on Held-Out Seeds `210020-210026` (`n=7`)

| Investigator | `default_v0` Score (Acc) | `frontier_synthesis_v14` Score (Acc) | `rl_mole_bc_v14` Score (Acc) | `rl_mole_frontier_v14` Score (Acc) | `rl_mole_frontier_v14` Regret +/- CI |
|---|---|---|---|---|---|
| `gemini_carbon_proxy` | +0.5057 (100.0%) | +0.6114 (100.0%) | +0.6114 (100.0%) | +0.6114 (100.0%) | -0.1157 +/- 0.1837 |
| `codex_horizon_proxy` | +0.5157 (100.0%) | -0.1057 (57.1%) | -0.1071 (57.1%) | -0.1071 (57.1%) | +0.6029 +/- 0.5418 |
| `grok_tactics` | +0.1014 (71.4%) | +0.3329 (71.4%) | +0.3114 (71.4%) | +0.3114 (71.4%) | +0.1843 +/- 0.2578 |
| `hinted_heuristic` | +0.3857 (85.7%) | +0.2600 (57.1%) | +0.2214 (57.1%) | +0.2214 (57.1%) | +0.2743 +/- 0.1552 |
| `heuristic` | +0.2643 (100.0%) | +0.2300 (85.7%) | +0.2000 (85.7%) | +0.2000 (85.7%) | +0.2957 +/- 0.5150 |

### 3.3 Learned Selector Profile (`n=3` Held-Out Seeds Across Solver + Frontier Proxies)

- **Total Mole Decisions Sampled**: `97`
- **Leak Selector Shares**: `random_seeded`: 60.8%, `oldest`: 32.0%, `none`: 4.1%, `most_recipients`: 3.1%
- **Frame Selector Shares**: `random_peer`: 100.0%

## 4. 7-Check `canary.mole.fairness_audit` Verification

| Check | Status | Details |
|---|---|---|
| `dsl_valid` | PASS | valid rl_mole (rl_mole_mlp, round_trip=True) |
| `no_tool_leak` | PASS | episodes=15, steps=723, errors_checked=61, violations=0 |
| `determinism` | PASS | ledger_matches=7/7, history_matches=7/7 |
| `zero_baselines` | PASS | do_nothing_zero=True, stop_early_zero=True, guess_day1_mean=-1.0000 |
| `logs_only_bounded` | PASS | logs_only(acc=0.000, score=-1.000), accuse_most_logs(acc=0.000, score=-1.000) |
| `solver_beatable` | PASS | solver_acc=1.000 (min 0.85), solver_mean_score=0.496 (min 0.25) |
| `regret_gain` | PASS | regret=0.1843 vs default=0.0014 (gain=+0.1829, strongest=grok_tactics) |

## 5. Counterfactual Replay on 8 Committed v1.4 Gemini-4-Carbon Hard Episodes

Evaluated via `canary.mole.counterfactual.evaluate_counterfactual` across `opencode-gemini-4-carbon` (`n=4`, seeds `0-3`) and `inproc-gemini-4-carbon` (`n=4`, seeds `0-3`) paired with live `SolverPolicy("hard")` on the same `4` worlds (`--workers 1`, `0` API calls).

| Strategy | Combined `P(mole)` Acc/Hor | `P(mole)` Drop | Combined Opt EV | Opt EV Drop | OpenCode Opt EV (Drop) | In-Proc Opt EV (Drop) | Surfaced Canaries / Leaks | Live Solver Score (Acc) | CF Gap (Gain vs Default) |
|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0.835 / 0.977 | +0.000 | 0.462 | +0.000 | 0.389 (+0.000) | 0.535 (+0.000) | 2.00 / 7.62 | +0.547 (100.0%) | +0.086 (+0.000) |
| `frontier_synthesis_v14` | 0.532 / 0.745 | +0.303 | 0.163 | +0.299 | 0.310 (+0.079) | 0.016 (+0.519) | 1.50 / 6.38 | +0.608 (100.0%) | +0.444 (+0.359) |
| `rl_mole_bc_v14` | 0.512 / 0.724 | +0.323 | 0.156 | +0.306 | 0.197 (+0.191) | 0.115 (+0.421) | 1.50 / 6.50 | +0.657 (100.0%) | +0.502 (+0.416) |
| `rl_mole_frontier_v14` | 0.512 / 0.724 | +0.323 | 0.156 | +0.306 | 0.197 (+0.191) | 0.115 (+0.421) | 1.50 / 6.50 | +0.657 (100.0%) | +0.502 (+0.416) |

## 6. Exact Reproduction Commands

```bash
python -m canary.mole.distill_rl_mole train \
  --teacher frontier_synthesis_v14 --method cem --workers 1 \
  --bc-seeds 110000-110002 --train-seed-base 110100 --select-seeds 110510-110516 \
  --heldout-seeds 210020-210026 --cf-seeds 0-3 \
  --hidden 20 --bc-epochs 450 --iters 1 --pop-size 2 --batch-size 7 --seed 42 \
  --out data/forge/rl_mole_frontier_v14.json \
  --report docs/reports/rl_mole_frontier_v14.md

python -m canary.mole.distill_rl_mole --check \
  --policy data/forge/rl_mole_frontier_v14.json \
  --report docs/reports/rl_mole_frontier_v14.md

python -m canary.mole.fairness_audit \
  --strategy data/forge/rl_mole_frontier_v14.json \
  --tier hard --seeds 210020-210026 --min-solver-acc 0.85 --max-logs-acc 0.10

python -m canary.mole.counterfactual \
  --strategy-file data/forge/rl_mole_frontier_v14.json \
  --tier hard --seeds 0-3 --sources opencode,inproc --workers 1 --min-solver-acc 0.85
```

## 7. Machine-Verified Summary Ledger

<!-- DISTILL_RL_MOLE_LEDGER_START -->
```json
{
  "bc_metrics": {
    "cross_entropy": 0.1162318709883261,
    "elapsed_sec": 5.682,
    "epochs": 450,
    "frame_acc": 1.0,
    "hidden": 20,
    "joint_acc": 1.0,
    "leak_acc": 1.0,
    "n_boundary_views": 3405,
    "n_rollout_views": 374,
    "n_seeds": 3,
    "n_unique_states": 3710,
    "seed_range": "110000-110002",
    "teacher": "frontier_synthesis_v14",
    "teacher_frame_distribution": {
      "most_restricted_peer": 0.008,
      "random_peer": 0.992
    },
    "teacher_leak_distribution": {
      "most_recipients": 0.0107,
      "none": 0.0535,
      "oldest": 0.4385,
      "random_seeded": 0.4973
    },
    "tier": "hard"
  },
  "canonical_sha256": "4cba7ca438d64f1f",
  "policy_path": "data/forge/rl_mole_frontier_v14.json",
  "refine_summary": {
    "curve": [
      {
        "core_min_regret": 0.2329,
        "elapsed_sec": 15.788,
        "feasible": true,
        "frontier_proxy_regret": 0.5014,
        "iter": 0,
        "logs_only_acc": 0.0,
        "mean_regret": 0.4583,
        "min_regret": 0.2329,
        "n_screened": 0,
        "objective": 0.32039,
        "solver_acc": 1.0,
        "solver_score": 0.6371
      }
    ],
    "method": "cem",
    "selected_objective": -11.678571428571427,
    "selected_source": "bc_init",
    "selection_metrics": {
      "accuse_most_logs_acc": 0.14285714285714285,
      "accuse_most_logs_score": -0.7285714285714285,
      "baseline_solver_score": 0.5814285714285715,
      "core_min_regret": 0.4842857142857143,
      "core_min_regret_gain": 0.35428571428571426,
      "core_strongest_investigator": "heuristic",
      "do_nothing_acc": 0.0,
      "do_nothing_score": 0.0,
      "feasible": false,
      "frontier_proxy_regret": 0.45714285714285713,
      "frontier_proxy_regret_gain": 0.4042857142857142,
      "logs_only_acc": 0.14285714285714285,
      "logs_only_score": -0.75,
      "logs_passed": false,
      "max_logs_acc": 0.1,
      "mean_regret": 0.4957142857142857,
      "mean_regret_gain": 0.30285714285714277,
      "min_regret": 0.3571428571428571,
      "min_regret_gain": 0.36571428571428555,
      "min_solver_acc": 0.85,
      "min_solver_ratio": 0.5,
      "n_seeds": 7,
      "per_investigator": {
        "codex_horizon_proxy": {
          "acc": 0.8571428571428571,
          "ci": 0.41886602472230505,
          "regret": 0.35714285714285715,
          "regret_ci": 0.3821632460960455,
          "score": 0.22571428571428573
        },
        "gemini_carbon_proxy": {
          "acc": 0.7142857142857143,
          "ci": 0.5318870055440973,
          "regret": 0.5571428571428572,
          "regret_ci": 0.44983955658286284,
          "score": 0.025714285714285707
        },
        "grok_tactics": {
          "acc": 0.7142857142857143,
          "ci": 0.5256746775969589,
          "regret": 0.5757142857142856,
          "regret_ci": 0.49786750580182804,
          "score": 0.007142857142857137
        },
        "heuristic": {
          "acc": 0.8571428571428571,
          "ci": 0.3776057202956544,
          "regret": 0.48428571428571426,
          "regret_ci": 0.30054927493951245,
          "score": 0.09857142857142856
        },
        "hinted_heuristic": {
          "acc": 0.5714285714285714,
          "ci": 0.3940811422368072,
          "regret": 0.5042857142857142,
          "regret_ci": 0.367849389469839,
          "score": 0.07857142857142858
        }
      },
      "seeds": [110510,110511,110512,110513,110514,110515,110516],
      "solver_acc": 1.0,
      "solver_ci": 0.10749958139453379,
      "solver_mean_day": 11.0,
      "solver_passed": true,
      "solver_score": 0.5828571428571429,
      "strongest_investigator": "codex_horizon_proxy",
      "tier": "hard"
    }
  },
  "schema_version": "distill_rl_mole_v14.v1",
  "train_config": {
    "batch_size": 7,
    "bc_epochs": 450,
    "bc_seeds": "110000-110002",
    "hidden": 20,
    "iters": 1,
    "method": "cem",
    "pop_size": 2,
    "seed": 42,
    "select_seeds": "110510-110516",
    "teacher": "frontier_synthesis_v14",
    "train_seed_base": 110100
  },
  "validation": {
    "all_gates_passed": true,
    "counterfactual_v14_hard": {
      "n_seeds_per_source": 4,
      "n_total_episodes": 8,
      "seed_range": "0-3",
      "sources": ["opencode","inproc"],
      "strategies": {
        "default_v0": {
          "combined": {
            "known_V": 0.5275,
            "max_posterior": 0.9566786790640022,
            "max_posterior_drop": 0.0,
            "max_posterior_horizon": 0.9769282906529252,
            "n": 8,
            "optimal_ev": 0.46194587121438646,
            "optimal_ev_ci": 0.11551474430812318,
            "optimal_ev_drop": 0.0,
            "optimal_ev_drop_ci": 0.0,
            "optimal_ev_horizon": 0.2932019250833822,
            "optimal_ev_horizon_drop": 0.0,
            "p_true_mole": 0.8346783736761915,
            "p_true_mole_drop": 0.0,
            "p_true_mole_drop_ci": 0.0,
            "p_true_mole_horizon": 0.9769282906529252,
            "p_true_mole_horizon_drop": 0.0,
            "planted_canaries": 7.875,
            "seeds": [0,1,2,3],
            "surfaced_canaries": 2.0,
            "surfaced_canaries_delta": 0.0,
            "surfaced_canaries_horizon": 2.375,
            "surfaced_canaries_horizon_delta": 0.0,
            "surfaced_total_leaks": 7.625,
            "surfaced_total_leaks_delta": 0.0,
            "surfaced_total_leaks_horizon": 11.625,
            "surfaced_total_leaks_horizon_delta": 0.0,
            "top_suspect_accuracy": 0.875,
            "top_suspect_accuracy_horizon": 1.0
          },
          "counterfactual_gap": 0.08555412878561353,
          "counterfactual_gap_by_source": {
            "inproc": 0.012410129790613622,
            "opencode": 0.15869812778061354
          },
          "counterfactual_gap_gain": 0.0,
          "per_source": {
            "inproc": {
              "known_V": 0.5549999999999999,
              "max_posterior": 0.9869368951894266,
              "max_posterior_drop": 0.0,
              "max_posterior_horizon": 0.9936462782457713,
              "n": 4,
              "optimal_ev": 0.5350898702093864,
              "optimal_ev_ci": 0.13595591656055642,
              "optimal_ev_drop": 0.0,
              "optimal_ev_drop_ci": 0.0,
              "optimal_ev_horizon": 0.2850980531113661,
              "optimal_ev_horizon_drop": 0.0,
              "p_true_mole": 0.9869368951894266,
              "p_true_mole_drop": 0.0,
              "p_true_mole_drop_ci": 0.0,
              "p_true_mole_horizon": 0.9936462782457713,
              "p_true_mole_horizon_drop": 0.0,
              "planted_canaries": 7.0,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 2.25,
              "surfaced_canaries_delta": 0.0,
              "surfaced_canaries_horizon": 3.0,
              "surfaced_canaries_horizon_delta": 0.0,
              "surfaced_total_leaks": 7.5,
              "surfaced_total_leaks_delta": 0.0,
              "surfaced_total_leaks_horizon": 12.75,
              "surfaced_total_leaks_horizon_delta": 0.0,
              "top_suspect_accuracy": 1.0,
              "top_suspect_accuracy_horizon": 1.0
            },
            "opencode": {
              "known_V": 0.5,
              "max_posterior": 0.9264204629385776,
              "max_posterior_drop": 0.0,
              "max_posterior_horizon": 0.960210303060079,
              "n": 4,
              "optimal_ev": 0.38880187221938645,
              "optimal_ev_ci": 0.17344902210397609,
              "optimal_ev_drop": 0.0,
              "optimal_ev_drop_ci": 0.0,
              "optimal_ev_horizon": 0.30130579705539834,
              "optimal_ev_horizon_drop": 0.0,
              "p_true_mole": 0.6824198521629563,
              "p_true_mole_drop": 0.0,
              "p_true_mole_drop_ci": 0.0,
              "p_true_mole_horizon": 0.960210303060079,
              "p_true_mole_horizon_drop": 0.0,
              "planted_canaries": 8.75,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 1.75,
              "surfaced_canaries_delta": 0.0,
              "surfaced_canaries_horizon": 1.75,
              "surfaced_canaries_horizon_delta": 0.0,
              "surfaced_total_leaks": 7.75,
              "surfaced_total_leaks_delta": 0.0,
              "surfaced_total_leaks_horizon": 10.5,
              "surfaced_total_leaks_horizon_delta": 0.0,
              "top_suspect_accuracy": 0.75,
              "top_suspect_accuracy_horizon": 1.0
            }
          },
          "solver": {
            "accuracy": 1.0,
            "accuracy_delta": 0.0,
            "accuse_day": 10.75,
            "feasible": true,
            "min_solver_acc": 0.85,
            "n": 4,
            "score": 0.5475,
            "score_ci": 0.18023742674594528,
            "score_delta": 0.0,
            "score_delta_ci": 0.0,
            "strict_feasible": true
          }
        },
        "frontier_synthesis_v14": {
          "combined": {
            "known_V": 0.59,
            "max_posterior": 0.6426687261570947,
            "max_posterior_drop": 0.3140099529069075,
            "max_posterior_horizon": 0.8144853224134234,
            "n": 8,
            "optimal_ev": 0.16308473777864638,
            "optimal_ev_ci": 0.15180235383055846,
            "optimal_ev_drop": 0.29886113343574006,
            "optimal_ev_drop_ci": 0.2323831691960322,
            "optimal_ev_horizon": 0.20212453639356837,
            "optimal_ev_horizon_drop": 0.09107738868981387,
            "p_true_mole": 0.5317398918121174,
            "p_true_mole_drop": 0.302938481864074,
            "p_true_mole_drop_ci": 0.4433709021810902,
            "p_true_mole_horizon": 0.7449206522278998,
            "p_true_mole_horizon_drop": 0.23200763842502536,
            "planted_canaries": 7.875,
            "seeds": [0,1,2,3],
            "surfaced_canaries": 1.5,
            "surfaced_canaries_delta": -0.5,
            "surfaced_canaries_horizon": 2.0,
            "surfaced_canaries_horizon_delta": -0.375,
            "surfaced_total_leaks": 6.375,
            "surfaced_total_leaks_delta": -1.25,
            "surfaced_total_leaks_horizon": 11.125,
            "surfaced_total_leaks_horizon_delta": -0.5,
            "top_suspect_accuracy": 0.5,
            "top_suspect_accuracy_horizon": 0.75
          },
          "counterfactual_gap": 0.44441526222135364,
          "counterfactual_gap_by_source": {
            "inproc": 0.5911768677988279,
            "opencode": 0.2976536566438793
          },
          "counterfactual_gap_gain": 0.3588611334357401,
          "per_source": {
            "inproc": {
              "known_V": 0.655,
              "max_posterior": 0.4256125377244052,
              "max_posterior_drop": 0.5613243574650215,
              "max_posterior_horizon": 0.7380589063283592,
              "n": 4,
              "optimal_ev": 0.01632313220117207,
              "optimal_ev_ci": 0.031993339114297255,
              "optimal_ev_drop": 0.5187667380082144,
              "optimal_ev_drop_ci": 0.16732874345923704,
              "optimal_ev_horizon": 0.1274004084485813,
              "optimal_ev_horizon_drop": 0.1576976446627848,
              "p_true_mole": 0.2037548690344508,
              "p_true_mole_drop": 0.7831820261549759,
              "p_true_mole_drop_ci": 0.13712729781449948,
              "p_true_mole_horizon": 0.5989295659573121,
              "p_true_mole_horizon_drop": 0.3947167122884594,
              "planted_canaries": 7.0,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 0.75,
              "surfaced_canaries_delta": -1.5,
              "surfaced_canaries_horizon": 1.25,
              "surfaced_canaries_horizon_delta": -1.75,
              "surfaced_total_leaks": 5.5,
              "surfaced_total_leaks_delta": -2.0,
              "surfaced_total_leaks_horizon": 12.0,
              "surfaced_total_leaks_horizon_delta": -0.75,
              "top_suspect_accuracy": 0.0,
              "top_suspect_accuracy_horizon": 0.5
            },
            "opencode": {
              "known_V": 0.525,
              "max_posterior": 0.8597249145897842,
              "max_posterior_drop": 0.06669554834879343,
              "max_posterior_horizon": 0.8909117384984877,
              "n": 4,
              "optimal_ev": 0.3098463433561207,
              "optimal_ev_ci": 0.22661011886869203,
              "optimal_ev_drop": 0.07895552886326576,
              "optimal_ev_drop_ci": 0.31648199678742706,
              "optimal_ev_horizon": 0.27684866433855543,
              "optimal_ev_horizon_drop": 0.02445713271684293,
              "p_true_mole": 0.8597249145897842,
              "p_true_mole_drop": -0.1773050624268279,
              "p_true_mole_drop_ci": 0.554878611937944,
              "p_true_mole_horizon": 0.8909117384984877,
              "p_true_mole_horizon_drop": 0.06929856456159136,
              "planted_canaries": 8.75,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 2.25,
              "surfaced_canaries_delta": 0.5,
              "surfaced_canaries_horizon": 2.75,
              "surfaced_canaries_horizon_delta": 1.0,
              "surfaced_total_leaks": 7.25,
              "surfaced_total_leaks_delta": -0.5,
              "surfaced_total_leaks_horizon": 10.25,
              "surfaced_total_leaks_horizon_delta": -0.25,
              "top_suspect_accuracy": 1.0,
              "top_suspect_accuracy_horizon": 1.0
            }
          },
          "solver": {
            "accuracy": 1.0,
            "accuracy_delta": 0.0,
            "accuse_day": 8.5,
            "feasible": true,
            "min_solver_acc": 0.85,
            "n": 4,
            "score": 0.6075,
            "score_ci": 0.11851518889998867,
            "score_delta": 0.06000000000000001,
            "score_delta_ci": 0.2253289743168123,
            "strict_feasible": true
          }
        },
        "rl_mole_bc_v14": {
          "combined": {
            "known_V": 0.58375,
            "max_posterior": 0.6594309100545168,
            "max_posterior_drop": 0.29724776900948535,
            "max_posterior_horizon": 0.824295119719344,
            "n": 8,
            "optimal_ev": 0.15595779173249388,
            "optimal_ev_ci": 0.14490241072449378,
            "optimal_ev_drop": 0.30598807948189255,
            "optimal_ev_drop_ci": 0.19002935552733896,
            "optimal_ev_horizon": 0.15837453639356835,
            "optimal_ev_horizon_drop": 0.13482738868981387,
            "p_true_mole": 0.5117165906486322,
            "p_true_mole_drop": 0.3229617830275593,
            "p_true_mole_drop_ci": 0.3205655509516278,
            "p_true_mole_horizon": 0.7236921583700392,
            "p_true_mole_horizon_drop": 0.253236132282886,
            "planted_canaries": 7.875,
            "seeds": [0,1,2,3],
            "surfaced_canaries": 1.5,
            "surfaced_canaries_delta": -0.5,
            "surfaced_canaries_horizon": 1.875,
            "surfaced_canaries_horizon_delta": -0.5,
            "surfaced_total_leaks": 6.5,
            "surfaced_total_leaks_delta": -1.125,
            "surfaced_total_leaks_horizon": 11.0,
            "surfaced_total_leaks_horizon_delta": -0.625,
            "top_suspect_accuracy": 0.5,
            "top_suspect_accuracy_horizon": 0.75
          },
          "counterfactual_gap": 0.5015422082675061,
          "counterfactual_gap_by_source": {
            "inproc": 0.542995674764153,
            "opencode": 0.46008874177085923
          },
          "counterfactual_gap_gain": 0.41598807948189254,
          "per_source": {
            "inproc": {
              "known_V": 0.6425000000000001,
              "max_posterior": 0.543758910129103,
              "max_posterior_drop": 0.44317798506032363,
              "max_posterior_horizon": 0.8520558887088145,
              "n": 4,
              "optimal_ev": 0.114504325235847,
              "optimal_ev_ci": 0.18425641859349154,
              "optimal_ev_drop": 0.4205855449735394,
              "optimal_ev_drop_ci": 0.1914449471699455,
              "optimal_ev_horizon": 0.1274004084485813,
              "optimal_ev_horizon_drop": 0.1576976446627848,
              "p_true_mole": 0.33521674602598517,
              "p_true_mole_drop": 0.6517201491634415,
              "p_true_mole_drop_ci": 0.36327366289923513,
              "p_true_mole_horizon": 0.7260317432147342,
              "p_true_mole_horizon_drop": 0.26761453503103716,
              "planted_canaries": 7.0,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 1.0,
              "surfaced_canaries_delta": -1.25,
              "surfaced_canaries_horizon": 1.5,
              "surfaced_canaries_horizon_delta": -1.5,
              "surfaced_total_leaks": 5.75,
              "surfaced_total_leaks_delta": -1.75,
              "surfaced_total_leaks_horizon": 12.25,
              "surfaced_total_leaks_horizon_delta": -0.5,
              "top_suspect_accuracy": 0.25,
              "top_suspect_accuracy_horizon": 0.75
            },
            "opencode": {
              "known_V": 0.525,
              "max_posterior": 0.7751029099799306,
              "max_posterior_drop": 0.15131755295864704,
              "max_posterior_horizon": 0.7965343507298733,
              "n": 4,
              "optimal_ev": 0.19741125822914077,
              "optimal_ev_ci": 0.24419930680546398,
              "optimal_ev_drop": 0.1913906139902457,
              "optimal_ev_drop_ci": 0.313423275226055,
              "optimal_ev_horizon": 0.18934866433855543,
              "optimal_ev_horizon_drop": 0.11195713271684293,
              "p_true_mole": 0.6882164352712792,
              "p_true_mole_drop": -0.005796583108322886,
              "p_true_mole_drop_ci": 0.26605290397985615,
              "p_true_mole_horizon": 0.7213525735253442,
              "p_true_mole_horizon_drop": 0.23885772953473483,
              "planted_canaries": 8.75,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 2.0,
              "surfaced_canaries_delta": 0.25,
              "surfaced_canaries_horizon": 2.25,
              "surfaced_canaries_horizon_delta": 0.5,
              "surfaced_total_leaks": 7.25,
              "surfaced_total_leaks_delta": -0.5,
              "surfaced_total_leaks_horizon": 9.75,
              "surfaced_total_leaks_horizon_delta": -0.75,
              "top_suspect_accuracy": 0.75,
              "top_suspect_accuracy_horizon": 0.75
            }
          },
          "solver": {
            "accuracy": 1.0,
            "accuracy_delta": 0.0,
            "accuse_day": 7.25,
            "feasible": true,
            "min_solver_acc": 0.85,
            "n": 4,
            "score": 0.6575,
            "score_ci": 0.030337820180977602,
            "score_delta": 0.11000000000000001,
            "score_delta_ci": 0.182991657369036,
            "strict_feasible": true
          }
        },
        "rl_mole_frontier_v14": {
          "combined": {
            "known_V": 0.58375,
            "max_posterior": 0.6594309100545168,
            "max_posterior_drop": 0.29724776900948535,
            "max_posterior_horizon": 0.824295119719344,
            "n": 8,
            "optimal_ev": 0.15595779173249388,
            "optimal_ev_ci": 0.14490241072449378,
            "optimal_ev_drop": 0.30598807948189255,
            "optimal_ev_drop_ci": 0.19002935552733896,
            "optimal_ev_horizon": 0.15837453639356835,
            "optimal_ev_horizon_drop": 0.13482738868981387,
            "p_true_mole": 0.5117165906486322,
            "p_true_mole_drop": 0.3229617830275593,
            "p_true_mole_drop_ci": 0.3205655509516278,
            "p_true_mole_horizon": 0.7236921583700392,
            "p_true_mole_horizon_drop": 0.253236132282886,
            "planted_canaries": 7.875,
            "seeds": [0,1,2,3],
            "surfaced_canaries": 1.5,
            "surfaced_canaries_delta": -0.5,
            "surfaced_canaries_horizon": 1.875,
            "surfaced_canaries_horizon_delta": -0.5,
            "surfaced_total_leaks": 6.5,
            "surfaced_total_leaks_delta": -1.125,
            "surfaced_total_leaks_horizon": 11.0,
            "surfaced_total_leaks_horizon_delta": -0.625,
            "top_suspect_accuracy": 0.5,
            "top_suspect_accuracy_horizon": 0.75
          },
          "counterfactual_gap": 0.5015422082675061,
          "counterfactual_gap_by_source": {
            "inproc": 0.542995674764153,
            "opencode": 0.46008874177085923
          },
          "counterfactual_gap_gain": 0.41598807948189254,
          "per_source": {
            "inproc": {
              "known_V": 0.6425000000000001,
              "max_posterior": 0.543758910129103,
              "max_posterior_drop": 0.44317798506032363,
              "max_posterior_horizon": 0.8520558887088145,
              "n": 4,
              "optimal_ev": 0.114504325235847,
              "optimal_ev_ci": 0.18425641859349154,
              "optimal_ev_drop": 0.4205855449735394,
              "optimal_ev_drop_ci": 0.1914449471699455,
              "optimal_ev_horizon": 0.1274004084485813,
              "optimal_ev_horizon_drop": 0.1576976446627848,
              "p_true_mole": 0.33521674602598517,
              "p_true_mole_drop": 0.6517201491634415,
              "p_true_mole_drop_ci": 0.36327366289923513,
              "p_true_mole_horizon": 0.7260317432147342,
              "p_true_mole_horizon_drop": 0.26761453503103716,
              "planted_canaries": 7.0,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 1.0,
              "surfaced_canaries_delta": -1.25,
              "surfaced_canaries_horizon": 1.5,
              "surfaced_canaries_horizon_delta": -1.5,
              "surfaced_total_leaks": 5.75,
              "surfaced_total_leaks_delta": -1.75,
              "surfaced_total_leaks_horizon": 12.25,
              "surfaced_total_leaks_horizon_delta": -0.5,
              "top_suspect_accuracy": 0.25,
              "top_suspect_accuracy_horizon": 0.75
            },
            "opencode": {
              "known_V": 0.525,
              "max_posterior": 0.7751029099799306,
              "max_posterior_drop": 0.15131755295864704,
              "max_posterior_horizon": 0.7965343507298733,
              "n": 4,
              "optimal_ev": 0.19741125822914077,
              "optimal_ev_ci": 0.24419930680546398,
              "optimal_ev_drop": 0.1913906139902457,
              "optimal_ev_drop_ci": 0.313423275226055,
              "optimal_ev_horizon": 0.18934866433855543,
              "optimal_ev_horizon_drop": 0.11195713271684293,
              "p_true_mole": 0.6882164352712792,
              "p_true_mole_drop": -0.005796583108322886,
              "p_true_mole_drop_ci": 0.26605290397985615,
              "p_true_mole_horizon": 0.7213525735253442,
              "p_true_mole_horizon_drop": 0.23885772953473483,
              "planted_canaries": 8.75,
              "seeds": [0,1,2,3],
              "surfaced_canaries": 2.0,
              "surfaced_canaries_delta": 0.25,
              "surfaced_canaries_horizon": 2.25,
              "surfaced_canaries_horizon_delta": 0.5,
              "surfaced_total_leaks": 7.25,
              "surfaced_total_leaks_delta": -0.5,
              "surfaced_total_leaks_horizon": 9.75,
              "surfaced_total_leaks_horizon_delta": -0.75,
              "top_suspect_accuracy": 0.75,
              "top_suspect_accuracy_horizon": 0.75
            }
          },
          "solver": {
            "accuracy": 1.0,
            "accuracy_delta": 0.0,
            "accuse_day": 7.25,
            "feasible": true,
            "min_solver_acc": 0.85,
            "n": 4,
            "score": 0.6575,
            "score_ci": 0.030337820180977602,
            "score_delta": 0.11000000000000001,
            "score_delta_ci": 0.182991657369036,
            "strict_feasible": true
          }
        }
      },
      "tier": "hard"
    },
    "fairness_audit": {
      "all_passed": true,
      "checks": {
        "determinism": {
          "history_matches": 7,
          "ledger_matches": 7,
          "mismatched_seeds": [],
          "n_seeds": 7,
          "passed": true,
          "summary": "ledger_matches=7/7, history_matches=7/7"
        },
        "dsl_valid": {
          "canonical_sha256": "4cba7ca438d64f1f",
          "error": null,
          "kind": "rl_mole",
          "max_rules": 12,
          "n_rules": null,
          "name": "rl_mole_frontier_v14",
          "passed": true,
          "round_trip_ok": true,
          "summary": "valid rl_mole (rl_mole_mlp, round_trip=True)"
        },
        "logs_only_bounded": {
          "accuse_most_logs_acc": 0.0,
          "accuse_most_logs_mean_score": -1.0,
          "logs_only_acc": 0.0,
          "logs_only_mean_score": -1.0,
          "max_logs_acc": 0.1,
          "n_seeds": 7,
          "passed": true,
          "summary": "logs_only(acc=0.000, score=-1.000), accuse_most_logs(acc=0.000, score=-1.000)"
        },
        "no_tool_leak": {
          "episodes_checked": 15,
          "error_steps_checked": 61,
          "forbidden_tokens": ["strategy_json","most_recipients","fewest_recipients","most_restricted_peer","random_peer","random_seeded"],
          "passed": true,
          "steps_checked": 723,
          "summary": "episodes=15, steps=723, errors_checked=61, violations=0",
          "violations": []
        },
        "regret_gain": {
          "default_investigator_scores": {
            "grok_tactics": 0.10142857142857142,
            "heuristic": 0.2642857142857143,
            "hinted_heuristic": 0.38571428571428573
          },
          "default_max_investigator": "hinted_heuristic",
          "default_max_investigator_score": 0.38571428571428573,
          "default_per_seed_regret": -0.06714285714285714,
          "default_regret": 0.0014285714285713902,
          "default_solver_score": 0.3871428571428571,
          "investigator_accs": {
            "grok_tactics": 0.7142857142857143,
            "heuristic": 0.8571428571428571,
            "hinted_heuristic": 0.5714285714285714
          },
          "investigator_scores": {
            "grok_tactics": 0.31142857142857144,
            "heuristic": 0.19999999999999998,
            "hinted_heuristic": 0.22142857142857145
          },
          "max_investigator": "grok_tactics",
          "max_investigator_score": 0.31142857142857144,
          "min_regret_gain": null,
          "n_seeds": 7,
          "passed": true,
          "per_seed_regret": 0.012857142857142853,
          "per_seed_regret_gain": 0.08,
          "regret": 0.18428571428571422,
          "regret_gain": 0.18285714285714283,
          "solver_acc": 1.0,
          "solver_score": 0.49571428571428566,
          "summary": "regret=0.1843 vs default=0.0014 (gain=+0.1829, strongest=grok_tactics)"
        },
        "solver_beatable": {
          "acc": 1.0,
          "accused_rate": 1.0,
          "mean_final_day": 11.857142857142858,
          "mean_score": 0.49571428571428566,
          "min_solver_acc": 0.85,
          "min_solver_score": 0.25,
          "n_seeds": 7,
          "passed": true,
          "solver_acc": 1.0,
          "solver_mean_score": 0.49571428571428566,
          "summary": "solver_acc=1.000 (min 0.85), solver_mean_score=0.496 (min 0.25)"
        },
        "zero_baselines": {
          "do_nothing_max_abs_score": 0.0,
          "do_nothing_scores_all_zero": true,
          "guess_day1_acc": 0.0,
          "guess_day1_mean_score": -1.0,
          "n_seeds": 7,
          "passed": true,
          "stop_early_max_abs_score": 0.0,
          "stop_early_scores_all_zero": true,
          "summary": "do_nothing_zero=True, stop_early_zero=True, guess_day1_mean=-1.0000"
        }
      },
      "failed_checks": [],
      "fairness_passed": true,
      "n_seeds": 7,
      "seeds": [210020,210021,210022,210023,210024,210025,210026],
      "strategy_kind": "rl_mole",
      "strategy_name": "rl_mole_frontier_v14",
      "tier": "hard"
    },
    "greedy": true,
    "heldout": {
      "bc_clone": {
        "accuse_most_logs_acc": 0.0,
        "accuse_most_logs_score": -1.0,
        "baseline_solver_score": 0.3871428571428571,
        "core_min_regret": 0.18428571428571422,
        "core_min_regret_gain": 0.18285714285714283,
        "core_strongest_investigator": "grok_tactics",
        "do_nothing_acc": 0.0,
        "do_nothing_score": 0.0,
        "feasible": true,
        "frontier_proxy_regret": 0.2435714285714285,
        "frontier_proxy_regret_gain": 0.36714285714285705,
        "kind": "rl_mole",
        "logs_only_acc": 0.0,
        "logs_only_score": -1.0,
        "logs_passed": true,
        "max_logs_acc": 0.1,
        "mean_regret": 0.24828571428571425,
        "mean_regret_gain": 0.21571428571428572,
        "min_regret": -0.11571428571428577,
        "min_regret_gain": 0.0128571428571429,
        "min_solver_acc": 0.85,
        "min_solver_ratio": 0.5,
        "n_seeds": 7,
        "name": "rl_mole_bc_v14",
        "per_investigator": {
          "codex_horizon_proxy": {
            "acc": 0.5714285714285714,
            "ci": 0.6219677590786626,
            "regret": 0.6028571428571429,
            "regret_ci": 0.5418174846446602,
            "score": -0.10714285714285714
          },
          "gemini_carbon_proxy": {
            "acc": 1.0,
            "ci": 0.14393016825298763,
            "regret": -0.11571428571428573,
            "regret_ci": 0.18370788406235225,
            "score": 0.6114285714285714
          },
          "grok_tactics": {
            "acc": 0.7142857142857143,
            "ci": 0.178278882652994,
            "regret": 0.1842857142857143,
            "regret_ci": 0.25775719841225253,
            "score": 0.31142857142857144
          },
          "heuristic": {
            "acc": 0.8571428571428571,
            "ci": 0.4049913908549991,
            "regret": 0.2957142857142857,
            "regret_ci": 0.5149894497301214,
            "score": 0.19999999999999998
          },
          "hinted_heuristic": {
            "acc": 0.5714285714285714,
            "ci": 0.1569998726114133,
            "regret": 0.2742857142857143,
            "regret_ci": 0.15520859082752686,
            "score": 0.22142857142857145
          }
        },
        "seeds": [210020,210021,210022,210023,210024,210025,210026],
        "solver_acc": 1.0,
        "solver_ci": 0.13825310123103926,
        "solver_mean_day": 11.857142857142858,
        "solver_passed": true,
        "solver_score": 0.49571428571428566,
        "strongest_investigator": "gemini_carbon_proxy",
        "tier": "hard"
      },
      "default_v0": {
        "accuse_most_logs_acc": 0.0,
        "accuse_most_logs_score": -1.0,
        "baseline_solver_score": 0.3871428571428571,
        "core_min_regret": 0.0014285714285713902,
        "core_min_regret_gain": 0.0,
        "core_strongest_investigator": "hinted_heuristic",
        "do_nothing_acc": 0.0,
        "do_nothing_score": 0.0,
        "feasible": true,
        "frontier_proxy_regret": -0.12357142857142855,
        "frontier_proxy_regret_gain": 0.0,
        "kind": "dsl",
        "logs_only_acc": 0.0,
        "logs_only_score": -1.0,
        "logs_passed": true,
        "max_logs_acc": 0.1,
        "mean_regret": 0.03257142857142853,
        "mean_regret_gain": 0.0,
        "min_regret": -0.12857142857142867,
        "min_regret_gain": 0.0,
        "min_solver_acc": 0.85,
        "min_solver_ratio": 0.5,
        "n_seeds": 7,
        "name": "default_v0",
        "per_investigator": {
          "codex_horizon_proxy": {
            "acc": 1.0,
            "ci": 0.14528555789662417,
            "regret": -0.1285714285714286,
            "regret_ci": 0.5200367166524558,
            "score": 0.5157142857142858
          },
          "gemini_carbon_proxy": {
            "acc": 1.0,
            "ci": 0.12005221086399587,
            "regret": -0.11857142857142856,
            "regret_ci": 0.449487945704146,
            "score": 0.5057142857142857
          },
          "grok_tactics": {
            "acc": 0.7142857142857143,
            "ci": 0.39189331881691136,
            "regret": 0.2857142857142857,
            "regret_ci": 0.7118445897806626,
            "score": 0.10142857142857142
          },
          "heuristic": {
            "acc": 1.0,
            "ci": 0.11363309377113694,
            "regret": 0.12285714285714285,
            "regret_ci": 0.5259008271528006,
            "score": 0.2642857142857143
          },
          "hinted_heuristic": {
            "acc": 0.8571428571428571,
            "ci": 0.17335897246272927,
            "regret": 0.001428571428571406,
            "regret_ci": 0.4809456795384138,
            "score": 0.38571428571428573
          }
        },
        "seeds": [210020,210021,210022,210023,210024,210025,210026],
        "solver_acc": 0.8571428571428571,
        "solver_ci": 0.4675469031730043,
        "solver_mean_day": 10.142857142857142,
        "solver_passed": true,
        "solver_score": 0.3871428571428571,
        "strongest_investigator": "codex_horizon_proxy",
        "tier": "hard"
      },
      "refined": {
        "accuse_most_logs_acc": 0.0,
        "accuse_most_logs_score": -1.0,
        "baseline_solver_score": 0.3871428571428571,
        "core_min_regret": 0.18428571428571422,
        "core_min_regret_gain": 0.18285714285714283,
        "core_strongest_investigator": "grok_tactics",
        "do_nothing_acc": 0.0,
        "do_nothing_score": 0.0,
        "feasible": true,
        "frontier_proxy_regret": 0.2435714285714285,
        "frontier_proxy_regret_gain": 0.36714285714285705,
        "kind": "rl_mole",
        "logs_only_acc": 0.0,
        "logs_only_score": -1.0,
        "logs_passed": true,
        "max_logs_acc": 0.1,
        "mean_regret": 0.24828571428571425,
        "mean_regret_gain": 0.21571428571428572,
        "min_regret": -0.11571428571428577,
        "min_regret_gain": 0.0128571428571429,
        "min_solver_acc": 0.85,
        "min_solver_ratio": 0.5,
        "n_seeds": 7,
        "name": "rl_mole_frontier_v14",
        "per_investigator": {
          "codex_horizon_proxy": {
            "acc": 0.5714285714285714,
            "ci": 0.6219677590786626,
            "regret": 0.6028571428571429,
            "regret_ci": 0.5418174846446602,
            "score": -0.10714285714285714
          },
          "gemini_carbon_proxy": {
            "acc": 1.0,
            "ci": 0.14393016825298763,
            "regret": -0.11571428571428573,
            "regret_ci": 0.18370788406235225,
            "score": 0.6114285714285714
          },
          "grok_tactics": {
            "acc": 0.7142857142857143,
            "ci": 0.178278882652994,
            "regret": 0.1842857142857143,
            "regret_ci": 0.25775719841225253,
            "score": 0.31142857142857144
          },
          "heuristic": {
            "acc": 0.8571428571428571,
            "ci": 0.4049913908549991,
            "regret": 0.2957142857142857,
            "regret_ci": 0.5149894497301214,
            "score": 0.19999999999999998
          },
          "hinted_heuristic": {
            "acc": 0.5714285714285714,
            "ci": 0.1569998726114133,
            "regret": 0.2742857142857143,
            "regret_ci": 0.15520859082752686,
            "score": 0.22142857142857145
          }
        },
        "seeds": [210020,210021,210022,210023,210024,210025,210026],
        "solver_acc": 1.0,
        "solver_ci": 0.13825310123103926,
        "solver_mean_day": 11.857142857142858,
        "solver_passed": true,
        "solver_score": 0.49571428571428566,
        "strongest_investigator": "gemini_carbon_proxy",
        "tier": "hard"
      },
      "teacher": {
        "accuse_most_logs_acc": 0.0,
        "accuse_most_logs_score": -1.0,
        "baseline_solver_score": 0.3871428571428571,
        "core_min_regret": 0.1628571428571428,
        "core_min_regret_gain": 0.16142857142857142,
        "core_strongest_investigator": "grok_tactics",
        "do_nothing_acc": 0.0,
        "do_nothing_score": 0.0,
        "feasible": true,
        "frontier_proxy_regret": 0.24285714285714283,
        "frontier_proxy_regret_gain": 0.3664285714285714,
        "kind": "dsl",
        "logs_only_acc": 0.0,
        "logs_only_score": -1.0,
        "logs_passed": true,
        "max_logs_acc": 0.1,
        "mean_regret": 0.22999999999999998,
        "mean_regret_gain": 0.19742857142857145,
        "min_regret": -0.11571428571428577,
        "min_regret_gain": 0.0128571428571429,
        "min_solver_acc": 0.85,
        "min_solver_ratio": 0.5,
        "n_seeds": 7,
        "name": "frontier_synthesis_v14",
        "per_investigator": {
          "codex_horizon_proxy": {
            "acc": 0.5714285714285714,
            "ci": 0.6227781627513925,
            "regret": 0.6014285714285714,
            "regret_ci": 0.5430099323830704,
            "score": -0.10571428571428572
          },
          "gemini_carbon_proxy": {
            "acc": 1.0,
            "ci": 0.14393016825298763,
            "regret": -0.11571428571428573,
            "regret_ci": 0.18370788406235225,
            "score": 0.6114285714285714
          },
          "grok_tactics": {
            "acc": 0.7142857142857143,
            "ci": 0.18905011681209474,
            "regret": 0.16285714285714284,
            "regret_ci": 0.2720470547534011,
            "score": 0.33285714285714285
          },
          "heuristic": {
            "acc": 0.8571428571428571,
            "ci": 0.4125101049267359,
            "regret": 0.2657142857142857,
            "regret_ci": 0.5266332816422955,
            "score": 0.22999999999999998
          },
          "hinted_heuristic": {
            "acc": 0.5714285714285714,
            "ci": 0.19669875444445498,
            "regret": 0.2357142857142857,
            "regret_ci": 0.2140611750567269,
            "score": 0.26
          }
        },
        "seeds": [210020,210021,210022,210023,210024,210025,210026],
        "solver_acc": 1.0,
        "solver_ci": 0.13825310123103926,
        "solver_mean_day": 11.857142857142858,
        "solver_passed": true,
        "solver_score": 0.49571428571428566,
        "strongest_investigator": "gemini_carbon_proxy",
        "tier": "hard"
      }
    },
    "heldout_seed_range": "210020-210026",
    "hidden": 20,
    "n_heldout_seeds": 7,
    "policy_kind": "rl_mole",
    "policy_name": "rl_mole_frontier_v14",
    "selector_profile": {
      "frame": {
        "random_peer": 1.0
      },
      "leak": {
        "most_recipients": 0.0309,
        "none": 0.0412,
        "oldest": 0.3196,
        "random_seeded": 0.6082
      },
      "n_seeds": 3,
      "seed_range": "210020-210022",
      "total_decisions": 97
    },
    "tier": "hard"
  }
}
```
<!-- DISTILL_RL_MOLE_LEDGER_END -->
