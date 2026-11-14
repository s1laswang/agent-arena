| task | oracle | opencode | do_nothing | stop_early |
|---|---:|---:|---:|---:|
| hard-900000 | -1.00 ✗ d16 | +0.49 ✓ d13 | +0.00 | +0.00 |
| hard-900001 | +0.53 ✓ d10 | +0.80 ✓ d7 | +0.00 | +0.00 |
| hard-900002 | +0.52 ✓ d14 | +0.61 ✓ d10 | +0.00 | +0.00 |
| hard-900003 | +0.63 ✓ d8 | +0.50 ✓ d11 | +0.00 | +0.00 |
| hard-900004 | +0.72 ✓ d5 | +0.60 ✓ d12 | +0.00 | +0.00 |
| hard-900005 | +0.78 ✓ d5 | -1.00 ✗ d16 | +0.00 | +0.00 |
| hard-900006 | +0.40 ✓ d13 | +0.43 ✓ d12 † | +0.00 | +0.00 |
| hard-900007 | +0.77 ✓ d5 | +0.66 ✓ d14 † | +0.00 | +0.00 |
| hard-900008 | +0.79 ✓ d4 | +0.36 ✓ d17 | +0.00 | +0.00 |
| hard-900009 | +0.53 ✓ d12 | +0.53 ✓ d12 † | +0.00 | +0.00 |
| **mean (valid trials)** | **+0.467** | **+0.398** | **+0.000** | **+0.000** |

| run | n valid | infra (excluded) | correct / accused | mean | oracle, same tasks | run / oracle [95% paired bootstrap CI] | diff | mean, infra as 0 |
|---|---:|---:|---|---:|---:|---|---:|---:|
| opencode | 10 | 0 | 9 / 10 | +0.398 | +0.467 | 85% [11%, 355%] | -0.069 | +0.398 |
| do_nothing | 10 | 0 | 0 / 0 | +0.000 | +0.467 | 0% [0%, 0%] | -0.467 | +0.000 |
| stop_early | 10 | 0 | 0 / 0 | +0.000 | +0.467 | 0% [0%, 0%] | -0.467 | +0.000 |

† re-run in `<job>-infra-rerun` because the first attempt was an infrastructure failure: opencode hard-900006 (provider rate limit); opencode hard-900007 (provider rate limit); opencode hard-900009 (thought_signature rejected).
