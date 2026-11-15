| model | run (GPU · steps) | held-out seed idx | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs base (two-sample, n vs n) |
|---|---|---|---|---|---|---|---|---|---|---|
| base | – | 800000–800005 (6) | easy | 6 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.06 | – |
| base | – | 800000–800004 (5) | medium | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.00 | – |
| base | – | 800000–800004 (5) | hard | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – |
| base | – | 800000–800005 (6) | all | 16 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – |
| v1 | – | 800000–800003 (4) | easy | 4 | -0.750 ± 0.490 | 0.75 | 0.00 | 0.25 | 1.00 | -0.750 ± 0.490 (4 vs 6) |
| v1 | – | 800000–800003 (4) | medium | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4 vs 5) |
| v1 | – | 800000–800003 (4) | hard | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4 vs 5) |
| v1 | – | 800000–800003 (4) | all | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | -0.250 ± 0.256 (12 vs 16) |
| v2 | – | 800000–800027 (28) | easy | 28 | -0.616 ± 0.266 | 0.89 | 0.14 | 0.11 | 0.61 | -0.616 ± 0.266 (28 vs 6) |
| v2 | – | 800000–800026 (27) | medium | 27 | -0.006 ± 0.097 | 0.07 | 0.04 | 0.93 | 1.00 | -0.006 ± 0.097 (27 vs 5) |
| v2 | – | 800000–800026 (27) | hard | 27 | -0.556 ± 0.191 | 0.56 | 0.00 | 0.44 | 0.97 | -0.556 ± 0.191 (27 vs 5) |
| v2 | – | 800000–800027 (28) | all | 82 | -0.395 ± 0.128 | 0.51 | 0.06 | 0.49 | 0.92 | -0.395 ± 0.128 (82 vs 16) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.

Δ columns are TWO-SAMPLE (difference of means, CI = 1.96·√(se₁²+se₂²)). Held-out worlds are keyed by a secret; these evals ran without CANARY_WORLD_SECRET, so each process drew its own worlds and the same seed number is a different world in each run (checked: all 115 world-dependent step-0 list_employees results differ across runs). Seed-paired Δ would be invalid.
