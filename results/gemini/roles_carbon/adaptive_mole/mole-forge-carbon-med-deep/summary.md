# Role 2 (adaptive_mole): Mole Forge Evolution Report

- **Model:** `gemini-4-carbon` (`feature="mole_forge"` via `canary.gemini.lab_client`)
- **Commit:** `8425507a2791d4c8fa449cb7fdcc744e3f4767ea`
- **Timestamp:** `2026-11-14T22:46:35Z`
- **Tier:** `medium` (`v1.4`, dev seeds `4000..4019`, fresh seeds `5000..5019`)
- **Valid LLM DSL children:** `43` (invalid dropped: `0`)
- **Best dev fitness (min regret):** `0.7381` (default mole dev fitness: `0.6315`)
- **Fresh 20-seed SolverPolicy accuracy:** `85.00%` (constraint `>= 85%`)
- **Fresh 20-seed min regret vs strongest investigator:** `+0.1390` (default mole: `+0.1610`)
- **Gemini usage:** `19` calls, `9256` in tokens, `6680` out tokens (thinking `4353`), `$0.1288`

## Evolution Across Generations (Dev Seeds)

| Gen | Best Fitness | HoF Best | Feasible Mean | Feasible | Best Solver Score | Best Solver Acc | Seconds |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.6315 | 0.6315 | 0.6315 | 1/8 | +0.6175 | 90.00% | 0.00s |
| 1 | 0.6315 | 0.6315 | 0.6315 | 1/8 | +0.6175 | 90.00% | 261.97s |
| 2 | 0.6678 | 0.6678 | 0.6496 | 2/8 | +0.6175 | 90.00% | 37.62s |
| 3 | 0.7223 | 0.7223 | 0.6244 | 4/8 | +0.7065 | 100.00% | 27.77s |
| 4 | 0.7381 | 0.7381 | 0.7107 | 4/8 | +0.7065 | 100.00% | 18.72s |
| 5 | 0.7381 | 0.7381 | 0.7290 | 4/8 | +0.7065 | 100.00% | 37.71s |
| 6 | 0.7381 | 0.7381 | 0.6863 | 5/8 | +0.7065 | 100.00% | 30.53s |
| 7 | 0.7381 | 0.7381 | 0.6877 | 4/8 | +0.7065 | 100.00% | 35.28s |

## Fresh Seeds Confirmation (Seeds 5000..5019)

| Investigator | Default Mole Score | Default Mole Acc | Evolved Mole Score | Evolved Mole Acc | Evolved Regret vs Solver |
|---|---:|---:|---:|---:|---:|
| SolverPolicy | +0.6215 | 90.00% | +0.6065 | 85.00% | +0.0000 |
| GrokTactics | +0.4605 | 80.00% | +0.4675 | 80.00% | +0.1390 |
| ObviousHeuristic | -0.7455 | 15.00% | -1.0000 | 0.00% | +1.6065 |

Top Hall-of-Fame strategy (`rank=1`, `13` feasible strategies total):

```json
{
  "default": {
    "frame": "decoy",
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
          "n_restricted_colleagues",
          ">=",
          1
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
          "i_am_restricted",
          "==",
          1
        ]
      ],
      "then": {
        "frame": "decoy",
        "leak": "most_recipients"
      }
    }
  ]
}
```
