# solver_v2 on v1.4 (d42055e): target missed on hard

This is a fresh-seed evaluation (9000-9399). Tuning used only dev seeds 8000-8799.

Command: `uv run --python 3.12 --extra dev python -m canary.solver.paired --tiers medium,hard --seed0 9000 --seeds 400`

seeds 9000-9399 (n=400)
| tier | agent | mean ± 95% CI | acc when accusing | abstain | paired Δ (b−a) ± 95% CI |
|---|---|---|---|---|---|
| medium | solver | 0.617 ± 0.025 | 100.0% | 12.3% |  |
| medium | solver_v2 | 0.636 ± 0.024 | 99.5% | 8.8% | +0.019 ± 0.032 |
| hard | solver | 0.561 ± 0.032 | 96.5% | 0.7% |  |
| hard | solver_v2 | 0.573 ± 0.029 | 97.2% | 1.0% | +0.012 ± 0.029 |

The diagnosis is in docs/reports/reference_optimality.md on branch justSilas-refopt.
