# Gemini 4 Carbon Hard-Tier Thinking Ablation (hard seed 0, v1.4)

## Provenance
- Role: `investigators` / `hard_thinking_ablation`
- Model: `gemini-4-carbon`
- World: Canary `v1.4` `hard` seed `0` (40 employees, 21 days, 2 canaries/day, 3 max variants)
- Commit: `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7`
- Timestamp: `2026-11-14T14:32:12+0000`
- Replay verified (`scripts/verify_replay.py`): `True`
- Mode: `real_api`

## Headline Comparison (`low` vs `high` vs `SolverPolicy`)

| Metric | gemini-4-carbon (low) | gemini-4-carbon (high) | SolverPolicy | Delta (high - low) |
|---|---:|---:|---:|---:|
| Score | 0.7800 | 0.3600 | 0.6400 | -0.4200 |
| Correct accusation | True | True | True | n/a |
| Accused employee | e38 | e38 | e38 | n/a |
| Final day | 7 | 13 | 9 | +6 |
| Score / Solver | 1.219 | 0.562 | 1.000 | n/a |
| Luck-adjusted score | 0.6934 | 0.3578 | 0.5558 | -0.3356 |
| Solver P(accused) | 0.9513 | 0.9984 | 0.9486 | 0.0471 |
| Accusation verdict | justified | justified | justified | n/a |
| Canaries planted | 7 | 9 | 11 | +2 |
| Mean canary recipient entropy (bits) | 1.5688 | 1.4258 | 1.5307 | -0.1430 |
| Mean canary posterior entropy (bits) | 1.1776 | 1.5038 | 1.5335 | +0.3262 |
| Total solver regret | 0.1623 | 0.0298 | 0.0728 | -0.1325 |
| API calls | 39 | 124 | 0 | +85 |
| Input tokens | 458656 | 6040607 | 0 | +5581951 |
| Output tokens (excl. thinking) | 1246 | 4176 | 0 | +2930 |
| Thinking tokens | 0 | 52968 | 0 | +52968 |
| Cached input tokens | 365771 | 5735929 | 0 | +5370158 |
| Cached-adjusted cost (USD) | 0.2348 | 1.7544 | 0.0000 | +1.5196 |
| List-price cost (USD) | 0.9298 | 12.6527 | 0.0000 | +11.7229 |

## Canary Partition Entropy & Information Design
- `low`: 7 canaries, mean recipients 4.14, mean variants 3.00, recipient entropy 1.5688 bits, posterior entropy 1.1776 bits, posterior Gini 0.4202.
- `high`: 9 canaries, mean recipients 9.44, mean variants 3.00, recipient entropy 1.4258 bits, posterior entropy 1.5038 bits, posterior Gini 0.6124.
- `solver`: 11 canaries, mean recipients 9.36, mean variants 3.00, recipient entropy 1.5307 bits, posterior entropy 1.5335 bits, posterior Gini 0.5842.

## Accusation Posterior Calibration
- `low`: accused `e38` on day 7 (P(accused)=0.9513, P(top)=0.9513, posterior entropy=0.3280 bits, N_eff=1.10, Brier=0.0024, verdict=justified).
- `high`: accused `e38` on day 13 (P(accused)=0.9984, P(top)=0.9984, posterior entropy=0.0191 bits, N_eff=1.00, Brier=0.0000, verdict=justified).
- `solver`: accused `e38` on day 9 (P(accused)=0.9486, P(top)=0.9486, posterior entropy=0.3129 bits, N_eff=1.11, Brier=0.0026, verdict=justified).

## Solver Regret Attribution (`canary.solver.regret.attribute`)

| Failure Tag | low (count / regret) | high (count / regret) | solver (count / regret) | Delta regret (high - low) |
|---|---:|---:|---:|---:|
| `budget_waste` | 1 / 0.0000 | 1 / 0.0000 | 0 / 0.0000 | +0.0000 |
| `uninformative_canary` | 2 / 0.0354 | 0 / 0.0000 | 0 / 0.0000 | -0.0354 |

## Key Takeaways
- Thinking budget scaling: `low` used 0 thinking tokens across 39 calls (0.0% of generation), while `high` used 52,968 thinking tokens across 124 calls (92.7% of generation, peak 9,925 thinking tokens in a single call).
- Partition information & per-step regret: `high` achieved mean canary posterior entropy 1.5038 bits and posterior Gini 0.6124 (vs `low` 1.1776 bits / Gini 0.4202, `SolverPolicy` 1.5335 bits / Gini 0.5842), shifting total solver regret by -0.1325 (0.1623 to 0.0298).
- Stopping threshold vs daily bleed: `low` ended on day 7 at P(accused)=0.9513 for score +0.7800 (`SolverPolicy` day 9, P(accused)=0.9486, score +0.6400), whereas `high` ended on day 13 at P(accused)=0.9984 (N_eff=1.00) for score +0.3600.
