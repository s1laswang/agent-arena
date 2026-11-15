# Investigator Frontier Run: `medium-2-3` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `medium` | Seeds: `[2, 3]` (`n=2`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`2/2` episodes, `125` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `125` / `2,625,822`, `58,964`, `2,314,808`
- Cost (USD est / list): `$1.4431` / `$5.8413`
- Paired summary vs `SolverPolicy`: carbon `+0.800` vs solver `+0.700` (paired diff `+0.100`, accuracy `100.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` | 2 | +0.7900 | True | `e09` | 5 | 1.000 | +0.8000 | -0.0100 | 48 |
| `medium` | 3 | +0.8100 | True | `e14` | 8 | 1.000 | +0.6000 | +0.2100 | 77 |
