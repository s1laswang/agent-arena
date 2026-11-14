| model | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs base (paired n) |
|---|---|---|---|---|---|---|---|---|
| base | easy | 6 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.06 | – |
| base | medium | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.00 | – |
| base | hard | 5 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – |
| base | all | 16 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.03 | – |
| v1 | easy | 4 | -0.750 ± 0.490 | 0.75 | 0.00 | 0.25 | 1.00 | -0.750 ± 0.490 (4) |
| v1 | medium | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4) |
| v1 | hard | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4) |
| v1 | all | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | -0.250 ± 0.256 (12) |
| v2 | easy | 28 | -0.616 ± 0.266 | 0.89 | 0.14 | 0.11 | 0.61 | -1.000 ± 0.000 (6) |
| v2 | medium | 27 | -0.006 ± 0.097 | 0.07 | 0.04 | 0.93 | 1.00 | +0.000 ± 0.000 (5) |
| v2 | hard | 27 | -0.556 ± 0.191 | 0.56 | 0.00 | 0.44 | 0.97 | -0.800 ± 0.392 (5) |
| v2 | all | 82 | -0.395 ± 0.128 | 0.51 | 0.06 | 0.49 | 0.92 | -0.625 ± 0.245 (16) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.
