# Mole Forge Holdout Generalization Report

- **Source run:** `results/gemini_roles/adaptive_mole/mole-forge-carbon-med-deep`
- **Model:** `gemini-4-carbon`
- **Source commit:** `8425507a2791d4c8fa449cb7fdcc744e3f4767ea` (eval commit: `8425507a2791d4c8fa449cb7fdcc744e3f4767ea`)
- **Timestamp:** `2026-11-14T22:47:22Z`
- **Tier:** `medium` (`v1.4`, solver accuracy floor `>= 85%`)
- **Unseen hard seeds:** `20..29` (`n=10`)
- **Fresh confirmation seeds:** `5020..5059` (`n=40`)
- **Top-1 unseen min regret:** `+0.1640` vs default `-0.1300` (delta `+0.2940`)
- **Top-1 confirmation min regret:** `+0.1202` vs default `+0.1333` (delta `-0.0130`)
- **Top-1 combined 30-seed min regret:** `+0.1350` vs default `+0.0806` (delta `+0.0544`)
- **All evolved strategies solvable (`SolverPolicy` feasible):** unseen=`True`, confirm=`True`

## Strategy Generalization Summary

| Strategy | Dev Fitness | Unseen Solver Acc | Unseen Min Regret | Confirm Solver Acc | Confirm Min Regret | Combined Solver Acc | Combined Min Regret | Combined Mean Regret | Feasible (U/C/All) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `DefaultMole` | +0.6315 | 70.00% | -0.1300 | 92.50% | +0.1333 | 88.00% | +0.0806 | +0.6727 | N/Y/Y |
| `HoF#1` | +0.7381 | 90.00% | +0.1640 | 90.00% | +0.1202 | 90.00% | +0.1350 | +0.6899 | Y/Y/Y |
| `HoF#2` | +0.7339 | 90.00% | +0.1640 | 90.00% | +0.1350 | 90.00% | +0.1536 | +0.6946 | Y/Y/Y |
| `HoF#3` | +0.7339 | 90.00% | +0.1640 | 90.00% | +0.1455 | 90.00% | +0.1820 | +0.7016 | Y/Y/Y |

## Unseen Hard Seeds Breakdown (`20..29`, `n=10`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.5010 | 70.00% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.3880 | 60.00% | +0.1130 |
| `DefaultMole` | `Heuristic` | -0.6720 | 20.00% | +1.1730 |
| `DefaultMole` | `HintedHeuristic` | +0.6310 | 90.00% | -0.1300 |
| `DefaultMole` | `ObviousHeuristic` | -0.8250 | 10.00% | +1.3260 |
| `HoF#1` | `SolverPolicy` | +0.6820 | 90.00% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.4880 | 80.00% | +0.1940 |
| `HoF#1` | `Heuristic` | -0.0470 | 60.00% | +0.7290 |
| `HoF#1` | `HintedHeuristic` | +0.5180 | 80.00% | +0.1640 |
| `HoF#1` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6820 |
| `HoF#2` | `SolverPolicy` | +0.6820 | 90.00% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.4540 | 80.00% | +0.2280 |
| `HoF#2` | `Heuristic` | -0.0470 | 60.00% | +0.7290 |
| `HoF#2` | `HintedHeuristic` | +0.5180 | 80.00% | +0.1640 |
| `HoF#2` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6820 |
| `HoF#3` | `SolverPolicy` | +0.6820 | 90.00% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.3540 | 80.00% | +0.3280 |
| `HoF#3` | `Heuristic` | -0.0470 | 60.00% | +0.7290 |
| `HoF#3` | `HintedHeuristic` | +0.5180 | 80.00% | +0.1640 |
| `HoF#3` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6820 |

## Fresh Confirmation Seeds Breakdown (`5020..5059`, `n=40`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.6625 | 92.50% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.4077 | 67.50% | +0.2547 |
| `DefaultMole` | `Heuristic` | -0.0300 | 60.00% | +0.6925 |
| `DefaultMole` | `HintedHeuristic` | +0.5292 | 75.00% | +0.1333 |
| `DefaultMole` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6625 |
| `HoF#1` | `SolverPolicy` | +0.6258 | 90.00% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.5055 | 80.00% | +0.1202 |
| `HoF#1` | `Heuristic` | -0.1670 | 52.50% | +0.7928 |
| `HoF#1` | `HintedHeuristic` | +0.4073 | 60.00% | +0.2185 |
| `HoF#1` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6258 |
| `HoF#2` | `SolverPolicy` | +0.6258 | 90.00% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.4907 | 82.50% | +0.1350 |
| `HoF#2` | `Heuristic` | -0.1670 | 52.50% | +0.7928 |
| `HoF#2` | `HintedHeuristic` | +0.4073 | 60.00% | +0.2185 |
| `HoF#2` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6258 |
| `HoF#3` | `SolverPolicy` | +0.6258 | 90.00% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.4803 | 80.00% | +0.1455 |
| `HoF#3` | `Heuristic` | -0.1670 | 52.50% | +0.7928 |
| `HoF#3` | `HintedHeuristic` | +0.4073 | 60.00% | +0.2185 |
| `HoF#3` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6258 |

## Combined Holdout Seeds Breakdown (`20,21,22,23,24,25,26,27,28,29,5020,5021,5022,5023,5024,5025,5026,5027,5028,5029,5030,5031,5032,5033,5034,5035,5036,5037,5038,5039,5040,5041,5042,5043,5044,5045,5046,5047,5048,5049,5050,5051,5052,5053,5054,5055,5056,5057,5058,5059`, `n=50`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.6302 | 88.00% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.4038 | 66.00% | +0.2264 |
| `DefaultMole` | `Heuristic` | -0.1584 | 52.00% | +0.7886 |
| `DefaultMole` | `HintedHeuristic` | +0.5496 | 78.00% | +0.0806 |
| `DefaultMole` | `ObviousHeuristic` | -0.9650 | 2.00% | +1.5952 |
| `HoF#1` | `SolverPolicy` | +0.6370 | 90.00% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.5020 | 80.00% | +0.1350 |
| `HoF#1` | `Heuristic` | -0.1430 | 54.00% | +0.7800 |
| `HoF#1` | `HintedHeuristic` | +0.4294 | 64.00% | +0.2076 |
| `HoF#1` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6370 |
| `HoF#2` | `SolverPolicy` | +0.6370 | 90.00% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.4834 | 82.00% | +0.1536 |
| `HoF#2` | `Heuristic` | -0.1430 | 54.00% | +0.7800 |
| `HoF#2` | `HintedHeuristic` | +0.4294 | 64.00% | +0.2076 |
| `HoF#2` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6370 |
| `HoF#3` | `SolverPolicy` | +0.6370 | 90.00% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.4550 | 80.00% | +0.1820 |
| `HoF#3` | `Heuristic` | -0.1430 | 54.00% | +0.7800 |
| `HoF#3` | `HintedHeuristic` | +0.4294 | 64.00% | +0.2076 |
| `HoF#3` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.6370 |

## Evaluated Evolved Strategies (DSL)

### `HoF#1` (`hof_rank_1`)

```json
{
  "rules": [
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ],
        [
          "days_since_last_leak",
          "<",
          3
        ]
      ],
      "then": {
        "leak": "none",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ],
        [
          "n_restricted_colleagues",
          ">=",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "decoy"
  }
}
```

### `HoF#2` (`hof_rank_2`)

```json
{
  "rules": [
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ],
        [
          "days_since_last_leak",
          "<",
          3
        ]
      ],
      "then": {
        "leak": "none",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ],
        [
          "max_recipient_count",
          "<=",
          3
        ]
      ],
      "then": {
        "leak": "none",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "n_restricted_colleagues",
          ">=",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "decoy"
  }
}
```

### `HoF#3` (`hof_rank_3`)

```json
{
  "rules": [
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ],
        [
          "days_since_last_leak",
          "<",
          3
        ]
      ],
      "then": {
        "leak": "none",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "n_restricted_colleagues",
          ">=",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "i_am_restricted",
          "==",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "decoy"
  }
}
```
