# Role 2 (adaptive_mole): Mole Forge Evolution Report

- **Model:** `gemini-4-carbon` (`feature="mole_forge"` via `canary.gemini.lab_client`)
- **Commit:** `99767a5d144e89cbd9522ddd9720af55bb2217eb`
- **Timestamp:** `2026-11-14T14:30:05Z`
- **Tier:** `hard` (`v1.4`, dev seeds `4000..4009`, fresh seeds `5000..5019`)
- **Valid LLM DSL children:** `6` (invalid dropped: `0`)
- **Best dev fitness (min regret):** `0.3700` (default mole dev fitness: `0.2450`)
- **Fresh 20-seed SolverPolicy accuracy:** `95.00%` (constraint `>= 75%`)
- **Fresh 20-seed min regret vs strongest investigator:** `+0.2395` (default mole: `+0.2420`)
- **Gemini usage:** `12` calls, `2546` in tokens, `1060` out tokens (thinking `1180`), `$0.0275`

## Evolution Across Generations (Dev Seeds)

| Gen | Best Fitness | HoF Best | Feasible Mean | Feasible | Best Solver Score | Best Solver Acc | Seconds |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.3130 | 0.3130 | 0.2410 | 3/4 | +0.5760 | 100.00% | 0.00s |
| 1 | 0.3130 | 0.3130 | 0.3130 | 1/4 | +0.5760 | 100.00% | 23.80s |
| 2 | 0.3700 | 0.3700 | 0.3415 | 2/4 | +0.5130 | 100.00% | 33.59s |

## Fresh Seeds Confirmation (Seeds 5000..5019)

| Investigator | Default Mole Score | Default Mole Acc | Evolved Mole Score | Evolved Mole Acc | Evolved Regret vs Solver |
|---|---:|---:|---:|---:|---:|
| SolverPolicy | +0.5780 | 95.00% | +0.5210 | 95.00% | +0.0000 |
| GrokTactics | +0.3360 | 80.00% | +0.2815 | 85.00% | +0.2395 |
| ObviousHeuristic | -1.0000 | 0.00% | -1.0000 | 0.00% | +1.5210 |

Top Hall-of-Fame strategy (`rank=1`, `4` feasible strategies total):

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
          "n_restricted_colleagues",
          ">",
          0
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
          "<=",
          5
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
          "recent_low_recipient_docs",
          ">=",
          2
        ]
      ],
      "then": {
        "frame": "random_peer",
        "leak": "oldest"
      }
    }
  ]
}
```
