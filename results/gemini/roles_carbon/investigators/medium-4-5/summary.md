# Investigator Frontier Run: `medium-4-5` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `medium` | Seeds: `[4, 5]` (`n=2`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`2/2` episodes, `278` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `278` / `9,686,117`, `95,196`, `9,032,227`
- Cost (USD est / list): `$3.1630` / `$20.3242`
- Paired summary vs `SolverPolicy`: carbon `+0.255` vs solver `+0.740` (paired diff `-0.485`, accuracy `50.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` | 4 | +0.5100 | True | `e17` | 14 | 1.000 | +0.6900 | -0.1800 | 135 |
| `medium` | 5 | +0.0000 | False | `None` | 14 | n/a | +0.7900 | -0.7900 | 143 |
