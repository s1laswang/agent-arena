| model | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs base (paired n) |
|---|---|---|---|---|---|---|---|---|
| base | easy | 1 | 0.000 ± – | 0.00 | 0.00 | 1.00 | 0.15 | – |
| base | medium | 1 | 0.000 ± – | 0.00 | 0.00 | 1.00 | 0.01 | – |
| base | all | 2 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.08 | – |
| v1 | easy | 4 | -0.750 ± 0.490 | 0.75 | 0.00 | 0.25 | 1.00 | -1.000 ± – (1) |
| v1 | medium | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± – (1) |
| v1 | hard | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | – |
| v1 | all | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | -0.500 ± 0.980 (2) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.
