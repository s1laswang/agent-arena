# Role 2 (adaptive_mole): Mole Forge Evolution Report

- **Model:** `gemini-4-carbon` (`feature="mole_forge"` via `canary.gemini.lab_client`)
- **Commit:** `9b8858381c99a4b94ea3d989fcd0d232fc5411ca`
- **Timestamp:** `2026-11-14T17:33:56Z`
- **Tier:** `hard` (`v1.4`, dev seeds `0..19`, fresh seeds `20..29`)
- **Valid LLM DSL children:** `49` (invalid dropped: `0`)
- **Best dev fitness (min regret):** `0.3745` (default mole dev fitness: `0.0560`)
- **Fresh 20-seed SolverPolicy accuracy:** `90.00%` (constraint `>= 75%`)
- **Fresh 20-seed min regret vs strongest investigator:** `+0.2310` (default mole: `+0.1650`)
- **Gemini usage:** `8` calls, `12133` in tokens, `13031` out tokens (thinking `4958`), `$0.2042`

## Evolution Across Generations (Dev Seeds)

| Gen | Best Fitness | HoF Best | Feasible Mean | Feasible | Best Solver Score | Best Solver Acc | Seconds |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.3175 | 0.3175 | 0.1737 | 3/8 | +0.4740 | 80.00% | 0.00s |
| 1 | 0.3175 | 0.3175 | 0.2168 | 4/8 | +0.4740 | 80.00% | 92.96s |
| 2 | 0.3175 | 0.3175 | 0.2275 | 4/8 | +0.4740 | 80.00% | 55.88s |
| 3 | 0.3645 | 0.3645 | 0.2614 | 7/8 | +0.4765 | 90.00% | 55.36s |
| 4 | 0.3645 | 0.3645 | 0.2871 | 7/8 | +0.4765 | 90.00% | 75.86s |
| 5 | 0.3645 | 0.3645 | 0.3069 | 7/8 | +0.4765 | 90.00% | 69.75s |
| 6 | 0.3745 | 0.3745 | 0.3382 | 5/8 | +0.4765 | 90.00% | 70.98s |
| 7 | 0.3745 | 0.3745 | 0.3318 | 5/8 | +0.4765 | 90.00% | 70.33s |

## Fresh Seeds Confirmation (Seeds 5000..5019)

| Investigator | Default Mole Score | Default Mole Acc | Evolved Mole Score | Evolved Mole Acc | Evolved Regret vs Solver |
|---|---:|---:|---:|---:|---:|
| SolverPolicy | +0.5990 | 100.00% | +0.4520 | 90.00% | +0.0000 |
| GrokTactics | +0.4340 | 100.00% | +0.2210 | 90.00% | +0.2310 |
| ObviousHeuristic | -1.0000 | 0.00% | -1.0000 | 0.00% | +1.4520 |

Top Hall-of-Fame strategy (`rank=1`, `20` feasible strategies total):

```json
{
  "default": {
    "frame": "decoy",
    "leak": "most_recipients"
  },
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
        "frame": "decoy",
        "leak": "none"
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
        "frame": "most_restricted_peer",
        "leak": "none"
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
        "frame": "decoy",
        "leak": "none"
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
        "frame": "most_restricted_peer",
        "leak": "most_recipients"
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
        "frame": "most_restricted_peer",
        "leak": "oldest"
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
        "frame": "decoy",
        "leak": "oldest"
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
        "frame": "decoy",
        "leak": "most_recipients"
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
        "frame": "decoy",
        "leak": "oldest"
      }
    }
  ]
}
```
