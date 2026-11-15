| model | run (GPU · steps) | held-out seed idx | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs base (two-sample, n vs n) | Δ vs v2 (two-sample, n vs n) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | – | 800000–800005 (6) | easy | 6 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.06 | – | +0.731 ± 0.160 (6 vs 58) |
| base | – | 800000–800004 (5) | medium | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.00 | – | +0.039 ± 0.081 (5 vs 57) |
| base | – | 800000–800004 (5) | hard | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – | +0.596 ± 0.128 (5 vs 57) |
| base | – | 800000–800005 (6) | all | 16 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – | +0.457 ± 0.086 (16 vs 172) |
| v1 | – | 800000–800003 (4) | easy | 4 | -0.750 ± 0.490 | 0.75 | 0.00 | 0.25 | 1.00 | -0.750 ± 0.490 (4 vs 6) | -0.019 ± 0.516 (4 vs 58) |
| v1 | – | 800000–800003 (4) | medium | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4 vs 5) | +0.039 ± 0.081 (4 vs 57) |
| v1 | – | 800000–800003 (4) | hard | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4 vs 5) | +0.596 ± 0.128 (4 vs 57) |
| v1 | – | 800000–800003 (4) | all | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | -0.250 ± 0.256 (12 vs 16) | +0.207 ± 0.270 (12 vs 172) |
| v2 | – | 800000–800059 (58) | easy | 58 | -0.731 ± 0.160 | 0.93 | 0.10 | 0.07 | 0.57 | -0.731 ± 0.160 (58 vs 6) | – |
| v2 | – | 800000–800059 (57) | medium | 57 | -0.039 ± 0.081 | 0.11 | 0.04 | 0.89 | 1.00 | -0.039 ± 0.081 (57 vs 5) | – |
| v2 | – | 800000–800059 (57) | hard | 57 | -0.596 ± 0.128 | 0.60 | 0.00 | 0.40 | 0.96 | -0.596 ± 0.128 (57 vs 5) | – |
| v2 | – | 800000–800059 (58) | all | 172 | -0.457 ± 0.086 | 0.55 | 0.05 | 0.45 | 0.92 | -0.457 ± 0.086 (172 vs 16) | – |
| v3_4k_s0 | – | 800000–800029 (30) | easy | 30 | -0.276 ± 0.222 | 0.47 | 0.10 | 0.53 | 0.99 | -0.276 ± 0.222 (30 vs 6) | +0.456 ± 0.274 (30 vs 58) |
| v3_4k_s0 | – | 800000–800029 (30) | medium | 30 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (30 vs 5) | +0.039 ± 0.081 (30 vs 57) |
| v3_4k_s0 | – | 800000–800029 (30) | hard | 30 | -0.033 ± 0.065 | 0.03 | 0.00 | 0.97 | 1.00 | -0.033 ± 0.065 (30 vs 5) | +0.563 ± 0.144 (30 vs 57) |
| v3_4k_s0 | – | 800000–800029 (30) | all | 90 | -0.103 ± 0.081 | 0.17 | 0.03 | 0.83 | 1.00 | -0.103 ± 0.081 (90 vs 16) | +0.354 ± 0.118 (90 vs 172) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.

Δ columns are TWO-SAMPLE (difference of means, CI = 1.96·√(se₁²+se₂²)). Held-out worlds are keyed by a secret; these evals ran without CANARY_WORLD_SECRET, so each process drew its own worlds and the same seed number is a different world in each run (checked: all 115 world-dependent step-0 list_employees results differ across runs). Seed-paired Δ would be invalid.
