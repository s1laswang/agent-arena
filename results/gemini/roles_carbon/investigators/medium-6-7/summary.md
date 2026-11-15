# Investigator Frontier Run: `medium-6-7` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `medium` | Seeds: `[6, 7]` (`n=2`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`2/2` episodes, `217` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `218` / `7,742,118`, `98,798`, `7,222,312`
- Cost (USD est / list): `$2.7498` / `$16.4722`
- Paired summary vs `SolverPolicy`: carbon `+0.370` vs solver `+0.805` (paired diff `-0.435`, accuracy `50.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` | 6 | +0.7400 | True | `e17` | 8 | 1.000 | +0.7900 | -0.0500 | 73 |
| `medium` | 7 | +0.0000 | False | `None` | 14 | n/a | +0.8200 | -0.8200 | 144 |
