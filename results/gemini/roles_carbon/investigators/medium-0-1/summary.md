# Investigator Frontier Run: `medium-0-1` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `medium` | Seeds: `[0, 1]` (`n=2`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`2/2` episodes, `163` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `163` / `4,658,670`, `71,772`, `4,257,294`
- Cost (USD est / list): `$1.9462` / `$10.0351`
- Paired summary vs `SolverPolicy`: carbon `+0.700` vs solver `+0.565` (paired diff `+0.135`, accuracy `100.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` | 0 | +0.6700 | True | `e05` | 10 | 1.000 | +0.7400 | -0.0700 | 96 |
| `medium` | 1 | +0.7300 | True | `e02` | 7 | 1.000 | +0.3900 | +0.3400 | 67 |
