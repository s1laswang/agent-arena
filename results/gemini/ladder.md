# Gemini Ladder (Canary v1.4)

> **Headline findings** (auto-generated from the table below: 10–10 paired seeds per cell; 95% CIs are wide, so read them as directions).
>
> **gemini-3.5-flash (requested ID; the API serves gemini-3.6-flash) with medium or high thinking matches the reference solver on hard:** 98% [82%, 119%] and 109% [90%, 139%] of the solver on the same seeds, 20/20 correct accusations, $0.33–0.37 per episode, versus $1.93 for gemini-4-carbon at high thinking.
>
> **gemini-3.1-flash-lite fails at every thinking level:** its mean score is below the do-nothing score (0) in 8/8 (level, tier) cells; at minimal thinking it accused the wrong employee in 19/20 episodes.
>
> **gemini-3.8-flash gains from thinking on medium** (-2% [-77%, 62%] at low → 92% [82%, 106%] at high); on hard 3% [-82%, 68%] → 31% [-44%, 88%]. Pooled over the flash models, low → high thinking changes premature-accusation regret by -0.10/episode on medium, -0.14/episode on hard; uninformative-canary regret goes 0.004 → 0.002 on medium, 0.017 → 0.029 on hard (thinking buys commit timing more than experiment design).

Generated 2026-11-14T23:58:22+0200 at git `e41768f1e9` from `~/agent-arena-data/gemini/ladder/ladder-v14`. 357 valid Gemini episodes in 34 cells; ledger: 19016 calls, 320 run ids, list price $147.98.

Every cell is one (model, thinking level, tier) played by the in-process `LLMPolicy` (full history, thought-signature replay) through `canary.agents.play`, the frontier measurement's own runner, on v1.4 dev seeds. The solver and baselines are replayed on exactly the same worlds. **ratio** = mean score / solver's mean on the same seeds, with a paired bootstrap 95% CI over seeds; **luck-adj.** scores each accusation as P·V − (1−P) under the solver's exact posterior at that step.

## medium

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 10 | -0.805 ± 0.38 | 0.10 | 5.0 | +0.730 | **-110% [-153%, -53%]** | -1.535 ± 0.37 | -116% [-130%, -105%] | 0 | 39 | 0.03 | 0.6 |
| gemini-3.1-flash-lite | low | 10 | -0.243 ± 0.61 | 0.40 | 5.0 | +0.730 | **-33% [-110%, 48%]** | -0.973 ± 0.62 | -63% [-111%, 5%] | 4,290 | 30 | 0.04 | 1.3 |
| gemini-3.1-flash-lite | medium | 10 | -0.656 ± 0.45 | 0.20 | 5.5 | +0.730 | **-90% [-133%, -22%]** | -1.386 ± 0.51 | -122% [-136%, -110%] | 1,686 | 40 | 0.06 | 1.4 |
| gemini-3.1-flash-lite | high | 10 | -0.640 ± 0.47 | 0.20 | 7.4 | +0.730 | **-88% [-129%, -16%]** | -1.370 ± 0.55 | -91% [-108%, -71%] | 5,544 | 37 | 0.06 | 3.3 |
| gemini-3.5-flash | minimal | 10 | +0.532 ± 0.34 | 0.90 | 8.9 | +0.730 | **73% [22%, 108%]** | -0.198 ± 0.35 | 51% [3%, 95%] | 0 | 37 | 0.12 | 0.8 |
| gemini-3.5-flash | low | 10 | +0.021 ± 0.55 | 0.60 | 10.9 | +0.730 | **3% [-69%, 73%]** | -0.709 ± 0.56 | 8% [-43%, 61%] | 7,269 | 50 | 0.27 | 4.7 |
| gemini-3.5-flash | medium | 10 | +0.594 ± 0.35 | 0.90 | 7.8 | +0.730 | **81% [30%, 119%]** | -0.136 ± 0.37 | 85% [41%, 119%] | 14,697 | 49 | 0.29 | 3.6 |
| gemini-3.5-flash | high | 10 | +0.548 ± 0.35 | 0.90 | 8.4 | +0.730 | **75% [23%, 112%]** | -0.182 ± 0.36 | 41% [-13%, 92%] | 19,266 | 54 | 0.35 | 4.3 |
| gemini-3.8-flash | low | 10 | -0.012 ± 0.53 | 0.60 | 9.3 | +0.730 | **-2% [-77%, 62%]** | -0.742 ± 0.49 | 1% [-39%, 41%] | 0 | 58 | 0.12 | 2.0 |
| gemini-3.8-flash | medium | 10 | +0.473 ± 0.33 | 0.90 | 12.4 | +0.730 | **65% [18%, 93%]** | -0.257 ± 0.32 | -1% [-57%, 50%] | 33,837 | 75 | 0.55 | 11.1 |
| gemini-3.8-flash | high | 10 | +0.669 ± 0.06 | 1.00 | 11.1 | +0.730 | **92% [82%, 106%]** | -0.061 ± 0.10 | 45% [-7%, 91%] | 42,350 | 70 | 0.58 | 11.7 |
| gemini-4-argon | low | 10 | +0.744 ± 0.08 | 1.00 | 7.1 | +0.730 | **102% [88%, 120%]** | +0.014 ± 0.12 | 75% [26%, 116%] | 0 | 26 | 0.15 | 5.5 |
| gemini-4-argon | medium | 10 | +0.599 ± 0.15 | 0.90 | 9.3 | +0.730 | **82% [62%, 100%]** | -0.131 ± 0.14 | 58% [14%, 94%] | 9,711 | 39 | 0.37 | 10.6 |
| gemini-4-argon | high | 10 | +0.380 ± 0.46 | 0.80 | 9.6 | +0.730 | **52% [-17%, 105%]** | -0.350 ± 0.46 | 47% [-13%, 100%] | 34,846 | 93 | 1.13 | 30.0 |
| gemini-4-carbon | low | 10 | +0.629 ± 0.10 | 1.00 | 9.1 | +0.730 | **86% [71%, 107%]** | -0.101 ± 0.15 | 81% [59%, 106%] | 530 | 65 | 0.39 | 39.2 |
| gemini-4-carbon | high | 10 | +0.639 ± 0.16 | 0.90 | 8.4 | +0.730 | **88% [72%, 99%]** | -0.091 ± 0.10 | 66% [24%, 97%] | 50,290 | 88 | 1.47 | 65.5 |
| gemini-4-carbon (imported†) | default | 15 | +0.558 ± 0.15 | 0.80 | 8.7 | +0.712 | **78% [55%, 100%]** | -0.154 ± 0.18 | 70% [45%, 96%] | 36,812* | 95 | 1.14 | – |

Reference on the union of these seeds: solver +0.712 ± 0.07 (n=15, acc 1.00); grok_tactics +0.423 ± 0.17 (n=15, acc 0.67); heuristic -0.353 ± 0.42 (n=15, acc 0.40); do_nothing +0.000 ± 0.00 (n=15, acc 0.00)

## hard

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 10 | -1.000 ± 0.00 | 0.00 | 4.4 | +0.576 | **-174% [-215%, -150%]** | -1.576 ± 0.11 | -166% [-214%, -134%] | 0 | 34 | 0.03 | 0.5 |
| gemini-3.1-flash-lite | low | 10 | -0.454 ± 0.54 | 0.30 | 6.9 | +0.576 | **-79% [-164%, 17%]** | -1.030 ± 0.56 | -142% [-174%, -119%] | 5,543 | 34 | 0.06 | 1.6 |
| gemini-3.1-flash-lite | medium | 10 | -1.000 ± 0.00 | 0.00 | 5.1 | +0.576 | **-174% [-215%, -150%]** | -1.576 ± 0.11 | -145% [-179%, -113%] | 1,666 | 34 | 0.04 | 1.9 |
| gemini-3.1-flash-lite | high | 10 | -0.471 ± 0.53 | 0.30 | 6.7 | +0.576 | **-82% [-167%, 11%]** | -1.047 ± 0.54 | -67% [-150%, 20%] | 5,679 | 39 | 0.06 | 3.4 |
| gemini-3.5-flash | minimal | 10 | -0.186 ± 0.44 | 0.60 | 13.7 | +0.576 | **-32% [-124%, 34%]** | -0.762 ± 0.38 | -23% [-100%, 35%] | 0 | 73 | 0.25 | 1.9 |
| gemini-3.5-flash | low | 10 | +0.266 ± 0.42 | 0.80 | 11.6 | +0.576 | **46% [-37%, 104%]** | -0.310 ± 0.39 | 22% [-48%, 83%] | 8,531 | 49 | 0.28 | 4.3 |
| gemini-3.5-flash | medium | 10 | +0.562 ± 0.07 | 1.00 | 11.1 | +0.576 | **98% [82%, 119%]** | -0.014 ± 0.11 | 61% [3%, 111%] | 19,377 | 56 | 0.37 | 5.5 |
| gemini-3.5-flash | high | 10 | +0.629 ± 0.07 | 1.00 | 8.6 | +0.576 | **109% [90%, 139%]** | +0.053 ± 0.13 | 93% [74%, 119%] | 23,123 | 45 | 0.33 | 4.1 |
| gemini-3.8-flash | low | 10 | +0.019 ± 0.45 | 0.70 | 11.5 | +0.576 | **3% [-82%, 68%]** | -0.557 ± 0.43 | 44% [9%, 78%] | 0 | 65 | 0.16 | 2.3 |
| gemini-3.8-flash | medium | 10 | +0.079 ± 0.47 | 0.70 | 13.5 | +0.576 | **14% [-71%, 85%]** | -0.497 ± 0.47 | 53% [16%, 91%] | 28,300 | 63 | 0.45 | 9.6 |
| gemini-3.8-flash | high | 10 | +0.181 ± 0.39 | 0.80 | 16.5 | +0.576 | **31% [-44%, 88%]** | -0.395 ± 0.39 | 6% [-61%, 67%] | 53,118 | 88 | 0.84 | 13.9 |
| gemini-4-argon | low | 10 | +0.585 ± 0.08 | 1.00 | 10.1 | +0.576 | **102% [83%, 130%]** | +0.009 ± 0.13 | 72% [28%, 110%] | 0 | 26 | 0.17 | 4.4 |
| gemini-4-argon | medium | 10 | +0.236 ± 0.42 | 0.80 | 14.6 | +0.576 | **41% [-35%, 108%]** | -0.340 ± 0.45 | 32% [-21%, 89%] | 17,346 | 47 | 0.64 | 17.6 |
| gemini-4-argon | high | 10 | +0.262 ± 0.42 | 0.80 | 13.6 | +0.576 | **45% [-34%, 99%]** | -0.314 ± 0.39 | 35% [-18%, 75%] | 44,695 | 122 | 1.61 | 39.3 |
| gemini-4-carbon | low | 10 | +0.463 ± 0.09 | 1.00 | 11.7 | +0.576 | **80% [62%, 107%]** | -0.113 ± 0.14 | 75% [56%, 104%] | 289 | 76 | 0.52 | 55.1 |
| gemini-4-carbon | high | 10 | +0.608 ± 0.10 | 1.00 | 10.8 | +0.576 | **106% [94%, 126%]** | +0.032 ± 0.09 | 80% [45%, 111%] | 63,171 | 107 | 1.93 | 72.1 |
| gemini-4-carbon (imported†) | default | 22 | +0.493 ± 0.15 | 0.95 | 12.0 | +0.457 | **108% [62%, 189%]** | +0.036 ± 0.24 | 98% [75%, 123%] | 48,351* | 103 | 1.50 | – |

Reference on the union of these seeds: solver +0.457 ± 0.15 (n=22, acc 0.95); grok_tactics +0.437 ± 0.10 (n=22, acc 0.91); heuristic +0.068 ± 0.25 (n=22, acc 0.77); do_nothing +0.000 ± 0.00 (n=22, acc 0.00)

Provenance: tiers v1.4, v1.4 (imported dir); launch commits 035105e9e1, 107c485, 2786c00, 498bccdea8, 7cb16dc305, 8fa04b3391, e9f58b4580; code fingerprints (env/harness/client files) 06ea9b6a0f68d1dc, None; API-served model versions gemini-3.1-flash-lite, gemini-3.6-flash, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon.

\* imported cell: output tokens incl. thinking (the measurement's usage does not split thinking out).
† imported read-only from the AfterQuery measurement (branch justSilas-gemini); not rerun by the ladder.

## Which mistakes does thinking fix?

Solver regret per episode by failure tag (`canary.solver.regret.attribute`), pooled over the models that ran low, medium and high: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash, gemini-4-argon. Δ = high − low (negative = thinking fixes it).

**medium**

| tag | low (n=40) | medium (n=40) | high (n=40) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.031 (5% eps) | +0.031 |
| other:accuse | 0.026 (5% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.026 |
| other:plant_canary | 0.032 (85% eps) | 0.024 (85% eps) | 0.020 (82% eps) | -0.011 |
| other:restrict_access | 0.002 (2% eps) | 0.003 (5% eps) | 0.004 (5% eps) | +0.002 |
| over_restriction | 0.005 (5% eps) | 0.002 (2% eps) | 0.008 (8% eps) | +0.003 |
| premature_accusation | 0.556 (50% eps) | 0.520 (48% eps) | 0.457 (50% eps) | -0.099 |
| uninformative_canary | 0.004 (12% eps) | 0.002 (8% eps) | 0.002 (5% eps) | -0.003 |

**hard**

| tag | low (n=40) | medium (n=40) | high (n=40) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.018 (2% eps) | +0.018 |
| other:accuse | 0.047 (45% eps) | 0.051 (45% eps) | 0.055 (45% eps) | +0.009 |
| other:advance_day | 0.000 (0% eps) | 0.001 (2% eps) | 0.000 (2% eps) | +0.000 |
| other:plant_canary | 0.062 (98% eps) | 0.036 (85% eps) | 0.036 (98% eps) | -0.026 |
| other:restrict_access | 0.011 (8% eps) | 0.000 (0% eps) | 0.010 (5% eps) | -0.001 |
| over_restriction | 0.015 (8% eps) | 0.000 (0% eps) | 0.007 (5% eps) | -0.008 |
| premature_accusation | 0.494 (42% eps) | 0.474 (40% eps) | 0.349 (35% eps) | -0.144 |
| uninformative_canary | 0.017 (32% eps) | 0.015 (30% eps) | 0.029 (35% eps) | +0.011 |

## Thinking levels each model accepts (probe)

| model | accepted thinking_level |
|---|---|
| gemini-3.1-flash-lite | minimal, low, medium, high |
| gemini-3.5-flash | minimal, low, medium, high |
| gemini-3.8-flash | low, medium, high |
| gemini-4-hydrogen | low, medium, high, xhigh |
| gemini-4-argon | low, medium, high |
| gemini-4-carbon | low, medium, high |

Figures: ladder_heatmap.png, ladder_curve.png, ladder_cost.png, ladder_tags.png. Data: ladder.json (rows, tags, ledger run ids).
