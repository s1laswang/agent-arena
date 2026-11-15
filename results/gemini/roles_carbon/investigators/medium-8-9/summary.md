# Investigator Frontier Run: `medium-8-9` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `medium` | Seeds: `[8, 9]` (`n=2`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`2/2` episodes, `191` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `191` / `5,767,066`, `83,656`, `5,308,215`
- Cost (USD est / list): `$2.2851` / `$12.3707`
- Paired summary vs `SolverPolicy`: carbon `+0.760` vs solver `+0.840` (paired diff `-0.080`, accuracy `100.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` | 8 | +0.8000 | True | `e02` | 11 | 1.000 | +0.8800 | -0.0800 | 105 |
| `medium` | 9 | +0.7200 | True | `e15` | 9 | 1.000 | +0.8000 | -0.0800 | 86 |
