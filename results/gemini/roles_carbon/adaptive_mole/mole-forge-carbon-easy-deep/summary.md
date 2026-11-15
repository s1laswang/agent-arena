# Role 2 (adaptive_mole): Mole Forge Evolution Report

- **Model:** `gemini-4-carbon` (`feature="mole_forge"` via `canary.gemini.lab_client`)
- **Commit:** `785d21a1cb79edd061e1e34031bb04284e38c110`
- **Timestamp:** `2026-11-14T23:54:18Z`
- **Tier:** `easy` (`v1.4`, dev seeds `0..9`, fresh seeds `20..39`)
- **Valid LLM DSL children:** `25` (invalid dropped: `0`)
- **Best dev fitness (min regret):** `0.5613` (default mole dev fitness: `0.3412`)
- **Fresh 20-seed SolverPolicy accuracy:** `75.00%` (constraint `>= 85%`)
- **Fresh 20-seed min regret vs strongest investigator:** `+0.1595` (default mole: `+0.0600`)
- **Gemini usage:** `34` calls, `5498` in tokens, `4832` out tokens (thinking `3203`), `$0.0913`

## Evolution Across Generations (Dev Seeds)

| Gen | Best Fitness | HoF Best | Feasible Mean | Feasible | Best Solver Score | Best Solver Acc | Seconds |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.5605 | 0.5605 | 0.3963 | 7/8 | +0.6490 | 90.00% | 0.00s |
| 1 | 0.5605 | 0.5605 | 0.4834 | 7/8 | +0.6490 | 90.00% | 49.82s |
| 2 | 0.5613 | 0.5613 | 0.5453 | 4/8 | +0.6490 | 90.00% | 60.92s |
| 3 | 0.5613 | 0.5613 | 0.4607 | 4/8 | +0.6490 | 90.00% | 57.54s |
| 4 | 0.5613 | 0.5613 | 0.5309 | 8/8 | +0.6490 | 90.00% | 476.15s |
| 5 | 0.5613 | 0.5613 | 0.5437 | 6/8 | +0.6490 | 90.00% | 1060.43s |

## Fresh Seeds Confirmation (Seeds 5000..5019)

| Investigator | Default Mole Score | Default Mole Acc | Evolved Mole Score | Evolved Mole Acc | Evolved Regret vs Solver |
|---|---:|---:|---:|---:|---:|
| SolverPolicy | +0.7670 | 100.00% | +0.4105 | 75.00% | +0.0000 |
| GrokTactics | +0.7070 | 100.00% | +0.2510 | 35.00% | +0.1595 |
| ObviousHeuristic | -0.5625 | 25.00% | -0.6120 | 20.00% | +1.0225 |

Top Hall-of-Fame strategy (`rank=1`, `20` feasible strategies total):

```json
{
  "default": {
    "frame": "random_peer",
    "leak": "random_seeded"
  },
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
          "days_since_last_leak",
          "<",
          2
        ],
        [
          "day",
          ">",
          2
        ],
        [
          "day",
          "<",
          12
        ]
      ],
      "then": {
        "frame": "random_peer",
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
          "n_restricted_colleagues",
          ">=",
          1
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
          "i_am_restricted",
          "==",
          1
        ]
      ],
      "then": {
        "frame": "random_peer",
        "leak": "oldest"
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
        "frame": "random_peer",
        "leak": "most_recipients"
      }
    }
  ]
}
```
