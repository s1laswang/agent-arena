| model | run (GPU · steps) | held-out seed idx | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs v3_8k_s3_A100_344st (paired n) |
|---|---|---|---|---|---|---|---|---|---|---|
| v3_8k_s3_A100_344st | – | 800000–800029 (30) | easy | 30 | -0.643 ± 0.249 | 0.90 | 0.13 | 0.10 | 0.82 | – |
| v3_8k_s3_A100_344st | – | 800000–800029 (30) | medium | 30 | -0.878 ± 0.166 | 1.00 | 0.07 | 0.00 | 1.00 | – |
| v3_8k_s3_A100_344st | – | 800000–800029 (30) | hard | 30 | -0.843 ± 0.178 | 0.97 | 0.07 | 0.03 | 0.96 | – |
| v3_8k_s3_A100_344st | – | 800000–800029 (30) | all | 90 | -0.788 ± 0.117 | 0.96 | 0.09 | 0.04 | 0.94 | – |
| v3_8k_s0_H100_637st | – | 800000–800029 (30) | easy | 30 | -0.033 ± 0.065 | 0.03 | 0.00 | 0.97 | 0.94 | +0.610 ± 0.281 (30) |
| v3_8k_s0_H100_637st | – | 800000–800029 (30) | medium | 30 | -0.067 ± 0.091 | 0.07 | 0.00 | 0.93 | 1.00 | +0.812 ± 0.183 (30) |
| v3_8k_s0_H100_637st | – | 800000–800029 (30) | hard | 30 | -0.081 ± 0.117 | 0.13 | 0.03 | 0.87 | 0.99 | +0.762 ± 0.223 (30) |
| v3_8k_s0_H100_637st | – | 800000–800029 (30) | all | 90 | -0.060 ± 0.054 | 0.08 | 0.01 | 0.92 | 0.98 | +0.728 ± 0.134 (90) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.
