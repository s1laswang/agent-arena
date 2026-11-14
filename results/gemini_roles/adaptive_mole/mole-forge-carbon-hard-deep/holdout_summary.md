# Mole Forge Holdout Generalization Report

- **Source run:** `results/gemini_roles/adaptive_mole/mole-forge-carbon-hard-deep`
- **Model:** `gemini-4-carbon`
- **Source commit:** `9b8858381c99a4b94ea3d989fcd0d232fc5411ca` (eval commit: `98cf21667a71116f6fdc3899e8cbeb8b2d2a9179`)
- **Timestamp:** `2026-11-14T17:40:32Z`
- **Tier:** `hard` (`v1.4`, solver accuracy floor `>= 75%`)
- **Unseen hard seeds:** `20..29` (`n=10`)
- **Fresh confirmation seeds:** `5020..5039` (`n=20`)
- **Top-1 unseen min regret:** `+0.1160` vs default `+0.1650` (delta `-0.0490`)
- **Top-1 confirmation min regret:** `+0.2450` vs default `+0.1755` (delta `+0.0695`)
- **Top-1 combined 30-seed min regret:** `+0.2527` vs default `+0.1947` (delta `+0.0580`)
- **All evolved strategies solvable (`SolverPolicy` feasible):** unseen=`True`, confirm=`True`

## Strategy Generalization Summary

| Strategy | Dev Fitness | Unseen Solver Acc | Unseen Min Regret | Confirm Solver Acc | Confirm Min Regret | Combined Solver Acc | Combined Min Regret | Combined Mean Regret | Feasible (U/C/All) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `DefaultMole` | +0.0560 | 100.00% | +0.1650 | 95.00% | +0.1755 | 96.67% | +0.1947 | +0.6439 | Y/Y/Y |
| `HoF#1` | +0.3745 | 90.00% | +0.1160 | 85.00% | +0.2450 | 86.67% | +0.2527 | +0.5445 | Y/Y/Y |
| `HoF#2` | +0.3685 | 90.00% | +0.1710 | 80.00% | +0.2175 | 83.33% | +0.2397 | +0.5827 | Y/Y/Y |
| `HoF#3` | +0.3645 | 90.00% | +0.1160 | 85.00% | +0.2450 | 86.67% | +0.2527 | +0.5464 | Y/Y/Y |

## Unseen Hard Seeds Breakdown (`20..29`, `n=10`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.5990 | 100.00% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.4340 | 100.00% | +0.1650 |
| `DefaultMole` | `Heuristic` | -0.1150 | 70.00% | +0.7140 |
| `DefaultMole` | `HintedHeuristic` | +0.3110 | 80.00% | +0.2880 |
| `DefaultMole` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.5990 |
| `HoF#1` | `SolverPolicy` | +0.4520 | 90.00% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.2210 | 90.00% | +0.2310 |
| `HoF#1` | `Heuristic` | +0.3360 | 90.00% | +0.1160 |
| `HoF#1` | `HintedHeuristic` | +0.1840 | 50.00% | +0.2680 |
| `HoF#1` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.4520 |
| `HoF#2` | `SolverPolicy` | +0.4610 | 90.00% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.0490 | 20.00% | +0.4120 |
| `HoF#2` | `Heuristic` | +0.2900 | 90.00% | +0.1710 |
| `HoF#2` | `HintedHeuristic` | +0.1770 | 40.00% | +0.2840 |
| `HoF#2` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.4610 |
| `HoF#3` | `SolverPolicy` | +0.4520 | 90.00% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.2210 | 90.00% | +0.2310 |
| `HoF#3` | `Heuristic` | +0.3360 | 90.00% | +0.1160 |
| `HoF#3` | `HintedHeuristic` | +0.1840 | 50.00% | +0.2680 |
| `HoF#3` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.4520 |

## Fresh Confirmation Seeds Breakdown (`5020..5039`, `n=20`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.5185 | 95.00% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.3090 | 80.00% | +0.2095 |
| `DefaultMole` | `Heuristic` | -0.0585 | 70.00% | +0.5770 |
| `DefaultMole` | `HintedHeuristic` | +0.3430 | 85.00% | +0.1755 |
| `DefaultMole` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.5185 |
| `HoF#1` | `SolverPolicy` | +0.4230 | 85.00% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.1175 | 55.00% | +0.3055 |
| `HoF#1` | `Heuristic` | +0.0685 | 75.00% | +0.3545 |
| `HoF#1` | `HintedHeuristic` | +0.1780 | 55.00% | +0.2450 |
| `HoF#1` | `ObviousHeuristic` | -0.9055 | 5.00% | +1.3285 |
| `HoF#2` | `SolverPolicy` | +0.4015 | 80.00% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.0135 | 10.00% | +0.3880 |
| `HoF#2` | `Heuristic` | -0.0185 | 70.00% | +0.4200 |
| `HoF#2` | `HintedHeuristic` | +0.1840 | 55.00% | +0.2175 |
| `HoF#2` | `ObviousHeuristic` | -0.9055 | 5.00% | +1.3070 |
| `HoF#3` | `SolverPolicy` | +0.4230 | 85.00% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.1060 | 45.00% | +0.3170 |
| `HoF#3` | `Heuristic` | +0.0685 | 75.00% | +0.3545 |
| `HoF#3` | `HintedHeuristic` | +0.1780 | 55.00% | +0.2450 |
| `HoF#3` | `ObviousHeuristic` | -0.9055 | 5.00% | +1.3285 |

## Combined Holdout Seeds Breakdown (`20,21,22,23,24,25,26,27,28,29,5020,5021,5022,5023,5024,5025,5026,5027,5028,5029,5030,5031,5032,5033,5034,5035,5036,5037,5038,5039`, `n=30`)

| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |
|---|---|---:|---:|---:|
| `DefaultMole` | `SolverPolicy` | +0.5453 | 96.67% | +0.0000 |
| `DefaultMole` | `GrokTactics` | +0.3507 | 86.67% | +0.1947 |
| `DefaultMole` | `Heuristic` | -0.0773 | 70.00% | +0.6227 |
| `DefaultMole` | `HintedHeuristic` | +0.3323 | 83.33% | +0.2130 |
| `DefaultMole` | `ObviousHeuristic` | -1.0000 | 0.00% | +1.5453 |
| `HoF#1` | `SolverPolicy` | +0.4327 | 86.67% | +0.0000 |
| `HoF#1` | `GrokTactics` | +0.1520 | 66.67% | +0.2807 |
| `HoF#1` | `Heuristic` | +0.1577 | 80.00% | +0.2750 |
| `HoF#1` | `HintedHeuristic` | +0.1800 | 53.33% | +0.2527 |
| `HoF#1` | `ObviousHeuristic` | -0.9370 | 3.33% | +1.3697 |
| `HoF#2` | `SolverPolicy` | +0.4213 | 83.33% | +0.0000 |
| `HoF#2` | `GrokTactics` | +0.0253 | 13.33% | +0.3960 |
| `HoF#2` | `Heuristic` | +0.0843 | 76.67% | +0.3370 |
| `HoF#2` | `HintedHeuristic` | +0.1817 | 50.00% | +0.2397 |
| `HoF#2` | `ObviousHeuristic` | -0.9370 | 3.33% | +1.3583 |
| `HoF#3` | `SolverPolicy` | +0.4327 | 86.67% | +0.0000 |
| `HoF#3` | `GrokTactics` | +0.1443 | 60.00% | +0.2883 |
| `HoF#3` | `Heuristic` | +0.1577 | 80.00% | +0.2750 |
| `HoF#3` | `HintedHeuristic` | +0.1800 | 53.33% | +0.2527 |
| `HoF#3` | `ObviousHeuristic` | -0.9370 | 3.33% | +1.3697 |

## Evaluated Evolved Strategies (DSL)

### `HoF#1` (`hof_rank_1`)

```json
{
  "rules": [
    {
      "if": [
        [
          "day",
          "<=",
          9
        ],
        [
          "max_recipient_count",
          "<=",
          4
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
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "n_restricted_colleagues",
          ">=",
          1
        ],
        [
          "day",
          "<",
          12
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
          "i_am_restricted",
          "==",
          1
        ],
        [
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "day",
          "<",
          12
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
          "day",
          ">=",
          8
        ],
        [
          "n_restricted_colleagues",
          ">=",
          2
        ],
        [
          "max_recipient_count",
          ">=",
          6
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
          "day",
          ">=",
          8
        ],
        [
          "n_restricted_colleagues",
          ">=",
          2
        ],
        [
          "n_leakable",
          ">=",
          2
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "most_restricted_peer"
      }
    },
    {
      "if": [
        [
          "day",
          ">=",
          11
        ],
        [
          "n_leakable",
          ">=",
          2
        ],
        [
          "newest_doc_age_days",
          "==",
          0
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "max_recipient_count",
          ">=",
          6
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "n_docs_held",
          ">=",
          4
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "most_recipients",
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
          "n_restricted_colleagues",
          ">=",
          1
        ],
        [
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "day",
          "<",
          13
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
          "i_am_restricted",
          "==",
          1
        ],
        [
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "day",
          "<",
          13
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
          "day",
          "<=",
          10
        ],
        [
          "max_recipient_count",
          "<=",
          4
        ],
        [
          "days_since_last_leak",
          "<",
          6
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
          "newest_doc_age_days",
          "<=",
          1
        ],
        [
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "max_recipient_count",
          ">=",
          6
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "day",
          ">=",
          10
        ],
        [
          "n_leakable",
          ">=",
          2
        ],
        [
          "newest_doc_age_days",
          "==",
          0
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "max_recipient_count",
          ">=",
          5
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "n_docs_held",
          ">=",
          3
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "most_recipients",
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
          "day",
          "<=",
          9
        ],
        [
          "max_recipient_count",
          "<=",
          4
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
          "recent_low_recipient_docs",
          ">=",
          1
        ],
        [
          "day",
          "<",
          12
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
          "day",
          ">=",
          11
        ],
        [
          "n_leakable",
          ">=",
          2
        ],
        [
          "newest_doc_age_days",
          "==",
          0
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "max_recipient_count",
          ">=",
          6
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "decoy"
      }
    },
    {
      "if": [
        [
          "n_docs_held",
          ">=",
          4
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "decoy"
      }
    }
  ],
  "default": {
    "leak": "most_recipients",
    "frame": "decoy"
  }
}
```
