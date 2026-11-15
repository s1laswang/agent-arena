| model | run (GPU · steps) | held-out seed idx | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | Δ vs base (two-sample, n vs n) |
|---|---|---|---|---|---|---|---|---|---|---|
| base | – | 800000–800000 (1) | easy | 1 | 0.000 ± – | 0.00 | 0.00 | 1.00 | 0.15 | – |
| base | – | 800000–800000 (1) | medium | 1 | 0.000 ± – | 0.00 | 0.00 | 1.00 | 0.01 | – |
| base | – | 800000–800000 (1) | all | 2 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 0.08 | – |
| v1 | – | 800000–800003 (4) | easy | 4 | -0.750 ± 0.490 | 0.75 | 0.00 | 0.25 | 1.00 | -0.750 ± 0.490 (4 vs 1) |
| v1 | – | 800000–800003 (4) | medium | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | +0.000 ± 0.000 (4 vs 1) |
| v1 | – | 800000–800003 (4) | hard | 4 | 0.000 ± 0.000 | 0.00 | 0.00 | 1.00 | 1.00 | – |
| v1 | – | 800000–800003 (4) | all | 12 | -0.250 ± 0.256 | 0.25 | 0.00 | 0.75 | 1.00 | -0.250 ± 0.256 (12 vs 2) |

Eval: each model plays full held-out episodes alone (train.eval_hf, greedy, KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment (decision-point GRPO); evaluation never does.

Δ columns are TWO-SAMPLE (difference of means, CI = 1.96·√(se₁²+se₂²)). Held-out worlds are keyed by a secret; these evals ran without CANARY_WORLD_SECRET, so each process drew its own worlds and the same seed number is a different world in each run (checked: all 115 world-dependent step-0 list_employees results differ across runs). Seed-paired Δ would be invalid. (DEV seeds 0–9999 use the public key in canary/world.py and are identical across runs, so DEV-seed comparisons such as the v1.4 Gemini-vs-solver gap stay truly paired.)
