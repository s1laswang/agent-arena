| model | run (GPU · steps) | held-out seed idx | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs v3_4k_s0|tr4k|inf4k|cap256 (paired n) | whom-precision | GPU-h | € |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DAgger_r1|tr8k|inf4k|cap256 | – | 800000–800024 (15) | easy | 15 | -0.142 ± 0.251 | 0.27 | 0.07 | 0.73 | 1.00 | +0.000 ± 0.341 (12) | 1/4 = 0.25 |  |  |
| DAgger_r1|tr8k|inf4k|cap256 | – | 800000–800023 (14) | medium | 14 | -0.143 ± 0.190 | 0.14 | 0.00 | 0.86 | 1.00 | -0.091 ± 0.178 (11) | 0/2 = 0.00 |  |  |
| DAgger_r1|tr8k|inf4k|cap256 | – | 800000–800023 (12) | hard | 12 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (9) | 0/0 |  |  |
| DAgger_r1|tr8k|inf4k|cap256 | – | 800000–800024 (15) | all | 41 | -0.101 ± 0.112 | 0.15 | 0.02 | 0.85 | 1.00 | -0.031 ± 0.139 (32) | 1/6 = 0.17 | – | – |
| v3_4k_s0|tr4k|inf4k|cap256 | – | 800000–800023 (12) | easy | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | – | 0/3 = 0.00 |  |  |
| v3_4k_s0|tr4k|inf4k|cap256 | – | 800000–800023 (11) | medium | 11 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | – | 0/0 |  |  |
| v3_4k_s0|tr4k|inf4k|cap256 | – | 800000–800022 (9) | hard | 9 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | – | 0/0 |  |  |
| v3_4k_s0|tr4k|inf4k|cap256 | – | 800000–800023 (12) | all | 32 | -0.094 ± 0.103 | 0.09 | 0.00 | 0.91 | 1.00 | – | 0/3 = 0.00 | – | – |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.
