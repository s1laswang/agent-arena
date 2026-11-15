# Pooled thinking-effect estimate (Canary v1.4 ladder, no new calls)

> **Each step up in thinking_level adds +16.3 [+7.6, +24.4] pp of the solver's score (n=570 episodes, 6 Gemini models, 63 (tier, seed) worlds; OLS with model and tier fixed effects, (tier, seed)-clustered bootstrap 95% CI).**

Generated 2026-11-15T04:51:03+0200 by `python -m canary.gemini.thinking_effect` from `results/gemini/ladder_episodes.jsonl.gz` (ladder.json git 76097d7843). Models with >= 2 thinking levels: gemini-3.1-flash-lite, gemini-3.6-flash (requested as 3.5-flash), gemini-3.8-flash, gemini-4-argon, gemini-4-carbon, gemini-4-hydrogen. Excluded by construction: the imported carbon-default cell, hosted Gemma, level `default`. Step coding: minimal 0, low 1, medium 2, high 3, xhigh 4. Outcome: agent score minus the solver's score on the same (tier, seed), in % of the solver's mean score on that tier. 95% CIs: percentile bootstrap over (tier, seed) worlds, B=10,000, RNG seed 20261115.

## Pooled slopes (OLS, model + tier fixed effects)

| outcome | per thinking step [95% CI] | per 10k thinking tokens/episode [95% CI] | CI excludes 0 (step / dose) |
|---|---|---|---|
| pp of the solver's score | +16.3 [+7.6, +24.4] | +0.2 [-4.6, +5.1] | yes / no |
| pp accuracy | +3.8 [+1.2, +6.4] | -0.7 [-2.6, +1.4] | yes / no |
| premature-accusation regret per episode | -0.079 [-0.111, -0.047] | -0.008 [-0.026, +0.009] | yes / no |

n = 570 episodes in 63 (tier, seed) worlds.

## Per-model slopes (score, pp of the solver's score per thinking step; tier fixed effect)

| model | levels | n | slope [95% CI] |
|---|---|---|---|
| gemini-3.1-flash-lite | minimal, low, medium, high | 80 | +12.4 [-11.3, +37.6] |
| gemini-3.6-flash (requested as 3.5-flash) | minimal, low, medium, high | 160 | +30.6 [+11.6, +49.6] |
| gemini-3.8-flash | low, medium, high | 80 | +38.1 [+1.8, +76.8] |
| gemini-4-argon | low, medium, high | 117 | -3.7 [-29.5, +21.6] |
| gemini-4-carbon | low, high | 40 | +8.6 [-2.1, +17.6] |
| gemini-4-hydrogen | low, medium, high, xhigh | 93 | +3.9 [-8.7, +15.7] |

Forest plot: thinking_effect.png. Data: thinking_effect.json.
