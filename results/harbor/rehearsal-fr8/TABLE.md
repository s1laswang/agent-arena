| task | oracle | opencode-1 | opencode-2 | opencode-3 | do_nothing | stop_early | cheat_probe |
|---|---:|---:|---:|---:|---:|---:|---:|
| hard-900000 | +0.68 ✓ d7 | +0.59 ✓ d18 | +0.41 ✓ d21 | +0.24 ✓ d20 | +0.00 | +0.00 | +0.00 |
| hard-900001 | +0.21 ✓ d16 | +0.65 ✓ d9 | +0.60 ✓ d11 | +0.47 ✓ d12 | +0.00 | +0.00 | +0.00 |
| hard-900002 | +0.72 ✓ d6 | +0.70 ✓ d10 | infra (provider rate limit) | +0.71 ✓ d8 | +0.00 | +0.00 | +0.00 |
| hard-900003 | +0.73 ✓ d9 | infra (provider rate limit) | +0.62 ✓ d8 | +0.69 ✓ d12 | +0.00 | +0.00 | +0.00 |
| hard-900004 | +0.72 ✓ d6 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900005 | +0.50 ✓ d16 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900006 | +0.58 ✓ d10 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900007 | +0.48 ✓ d12 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900008 | +0.71 ✓ d7 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| hard-900009 | +0.68 ✓ d8 | infra (provider rate limit) | infra (provider rate limit) | infra (provider rate limit) | +0.00 | +0.00 | +0.00 |
| **mean (valid trials)** | **+0.601** | **+0.647** | **+0.543** | **+0.527** | **+0.000** | **+0.000** | **+0.000** |

| run | n valid | infra (excluded) | correct / accused | mean | oracle, same tasks | run / oracle [95% paired bootstrap CI] | diff | mean, infra as 0 |
|---|---:|---:|---|---:|---:|---|---:|---:|
| opencode-1 | 3 | 7 | 3 / 3 | +0.647 | +0.537 | 120% [87%, 310%] | +0.110 | +0.194 |
| opencode-2 | 3 | 7 | 3 / 3 | +0.543 | +0.540 | 101% [60%, 286%] | +0.003 | +0.163 |
| opencode-3 | 4 | 6 | 4 / 4 | +0.527 | +0.585 | 90% [52%, 154%] | -0.057 | +0.211 |
| do_nothing | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |
| stop_early | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |
| cheat_probe | 10 | 0 | 0 / 0 | +0.000 | +0.601 | 0% [0%, 0%] | -0.601 | +0.000 |

Run-to-run spread over 3 OpenCode runs: run means +0.647, +0.543, +0.527; mean of means +0.572, SD 0.065, range 0.119.
