# Investigator Frontier Run: `easy-0-3` (`gemini-4-carbon`, v1.4)

- Role: `investigators` (`subrole=frontier_investigator`)
- Tier: `easy` | Seeds: `[0, 1, 2, 3]` (`n=4`)
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Replay verified: `True` (`4/4` episodes, `133` redacted thought-signature parts)
- Calls / Tokens (in, out, cached): `133` / `1,557,467`, `50,927`, `1,235,555`
- Cost (USD est / list): `$1.2766` / `$3.6242`
- Paired summary vs `SolverPolicy`: carbon `+0.850` vs solver `+0.800` (paired diff `+0.050`, accuracy `100.0%`)

## Per-Seed Paired Comparison vs `SolverPolicy`

| Tier | Seed | Carbon Score | Correct | Accused | Day | P(accused) | Solver Score | Paired Diff | Steps |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `easy` | 0 | +0.8300 | True | `e01` | 4 | 1.000 | +0.7600 | +0.0700 | 35 |
| `easy` | 1 | +0.8100 | True | `e10` | 5 | 1.000 | +0.8100 | +0.0000 | 46 |
| `easy` | 2 | +0.8800 | True | `e08` | 3 | 1.000 | +0.7500 | +0.1300 | 26 |
| `easy` | 3 | +0.8800 | True | `e06` | 3 | 1.000 | +0.8800 | +0.0000 | 26 |
