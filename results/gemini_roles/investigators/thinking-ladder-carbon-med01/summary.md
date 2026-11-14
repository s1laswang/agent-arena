# Gemini Thinking-Level Experiment: gemini-4-carbon (low vs high)

- Role: `investigators` (`thinking_level_ablation`)
- Model: `gemini-4-carbon` (live Gemini API)
- Canary tiers version: `v1.4`, tier: `medium`, paired dev seeds: `0, 1`
- Commit: `2cb207f51c44d3069e2101c4849a21965b606f92`
- Timestamp: `2026-11-14T14:16:06+0000`
- Command: `python scripts/run_carbon_thinking_ladder.py --model gemini-4-carbon --levels low,high --tier medium --seeds 0,1 --resume --out results/gemini_roles/investigators/thinking-ladder-carbon-med01`

## Aggregate Performance vs Paired SolverPolicy

| policy / level | n | mean score | accuracy | accused | mean day | score / solver | diff vs solver | mean P(accused) | luck-adj score | thinking tok/ep | out tok/ep | calls/ep | API latency s/ep | s/call | est $/ep | regret/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SolverPolicy (reference) | 2 | +0.565 | 1.00 | 1.00 | 10.5 | 100.0% | +0.000 | 1.00 | +0.565 | 0 | 0 | 0.0 | 0.0 | 0.00 | $0.0000 | 0.000 |
| gemini-4-carbon (thinking=low) | 2 | +0.655 | 1.00 | 1.00 | 10.0 | 115.9% | +0.090 | 1.00 | +0.655 | 134 | 2,337 | 65.0 | 811.4 | 12.48 | $0.3704 | 0.046 |
| gemini-4-carbon (thinking=high) | 2 | +0.655 | 1.00 | 1.00 | 9.5 | 115.9% | +0.090 | 1.00 | +0.655 | 52,281 | 2,999 | 94.0 | 1821.3 | 19.38 | $1.3993 | 0.028 |

## Paired Seed-by-Seed Breakdown

| seed | policy / level | score | solver score | score - solver | correct | accused | day | P(accused) | thinking tok | calls | latency s | est $ | regret | tags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | SolverPolicy | +0.740 | +0.740 | +0.000 | True | e05 | 7 | 1.00 | 0 | 0 | 0.0 | $0.0000 | 0.000 | none |
| 0 | thinking=low | +0.640 | +0.740 | -0.100 | True | e05 | 10 | 1.00 | 169 | 55 | 692.1 | $0.3150 | 0.053 | none |
| 0 | thinking=high | +0.570 | +0.740 | -0.170 | True | e05 | 11 | 1.00 | 56,119 | 107 | 2105.2 | $1.5918 | 0.044 | budget_waste:1 |
| 1 | SolverPolicy | +0.390 | +0.390 | +0.000 | True | e02 | 14 | 1.00 | 0 | 0 | 0.0 | $0.0000 | 0.000 | none |
| 1 | thinking=low | +0.670 | +0.390 | +0.280 | True | e02 | 10 | 1.00 | 98 | 75 | 930.6 | $0.4258 | 0.040 | budget_waste:2 |
| 1 | thinking=high | +0.740 | +0.390 | +0.350 | True | e02 | 8 | 1.00 | 48,443 | 81 | 1537.4 | $1.2069 | 0.012 | budget_waste:1 |

## Solver Regret Attribution by Tag (`canary.solver.regret.attribute`)

| tag | solver count | low count (regret sum) | high count (regret sum) | high - low count (regret delta) |
|---|---|---|---|---|
| `budget_waste` | 0 | 2 (0.000) | 2 (0.000) | +0 (+0.000) |

## High vs Low Thinking Summary

- Mean score delta (`high - low`): `+0.000` (accuracy delta `+0.00`, solver-ratio delta `+0.000`)
- Thinking tokens per episode: `134` (`low`) vs `52,281` (`high`), multiplier `391.62x` (`+52,148` tokens/ep)
- API latency per episode: `811.4s` (`low`) vs `1821.3s` (`high`), delta `+1009.9s`
- Solver regret per episode (`canary.solver.regret.attribute`): `0.046` (`low`) vs `0.028` (`high`), delta `-0.018`
- Total experiment usage: `318` calls, `104,829` thinking tokens, `9,240,098` input tokens, `8,471,482` cached tokens, estimated list cost `$3.5394`
