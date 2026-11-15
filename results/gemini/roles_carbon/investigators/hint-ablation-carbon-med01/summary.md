# Investigator Hint Ablation: `hint-ablation-carbon-med01` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=hint_ablation`)
- Hint tags: `premature_accusation,ignored_delay` | Tier: `medium` | Seeds: `[0, 1]` (`n=2`)
- Calls / Tokens (in, out, cached): `173` / `4,829,333`, `70,201`, `4,413,503`
- Cost (USD est / list): `$1.9750` / `$10.3607`
- Paired summary vs `SolverPolicy`: hinted carbon `+0.630` vs solver `+0.565` (paired diff `+0.065`, regret/ep `0.0176`)

## Per-Seed Results

| Tier | Seed | Hinted Score | Correct | Accused | Day | P(accused) | Solver Score | Regret |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `medium` | 0 | +0.6100 | True | `e05` | 10 | 1.000 | +0.7400 | 0.0235 |
| `medium` | 1 | +0.6500 | True | `e02` | 8 | 1.000 | +0.3900 | 0.0116 |
