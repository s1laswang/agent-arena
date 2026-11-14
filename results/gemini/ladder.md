# Gemini Ladder (Canary v1.4)

> **Headline findings (preliminary: 4–6 paired seeds per flash cell, 1–2 per gemini-4 cell; 95% CIs are wide, so read them as directions).**
>
> **gemini-3.5-flash with medium or high thinking matches the reference solver on hard.** It scores 91% [71%, 120%] and 102% [73%, 150%] of the solver on the same seeds, with 5/5 correct accusations in each cell, at $0.36–0.44 per episode. That is less than a third of a gemini-4-carbon episode on hard ($1.30–1.57).
>
> **gemini-3.1-flash-lite fails at every thinking level.** Its mean score is below the do-nothing score of 0 in all 8 cells, and at minimal thinking it accused the wrong employee in 8/8 episodes.
>
> **gemini-3.8-flash improves from low to high thinking on medium, but not on hard.** On medium it goes from −52% [−181%, 46%] to 92% [76%, 121%] of the solver; on hard it is 30% → 28%. Pooled over the flash models, low → high thinking mainly cuts premature-accusation regret (−0.16 per episode on medium, −0.10 on hard). Canary design does not improve: uninformative-canary regret on hard rises from 0.002 to 0.035.

Generated 2026-11-14T18:29:32+0200 at git `270a43fa4d` from `~/agent-arena-data/gemini/ladder/ladder-v14`. 133 valid Gemini episodes in 30 cells; ledger: 7552 calls, 133 run ids, list price $49.12.

Every cell is one (model, thinking level, tier) played by the in-process `LLMPolicy` (full history, thought-signature replay) through `canary.agents.play`, the frontier measurement's own runner, on v1.4 dev seeds. The solver and baselines are replayed on exactly the same worlds. **ratio** = mean score / solver's mean on the same seeds, with a paired bootstrap 95% CI over seeds; **luck-adj.** scores each accusation as P·V − (1−P) under the solver's exact posterior at that step.

## medium

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 4 | -1.000 ± 0.00 | 0.00 | 5.5 | +0.633 | **-158% [-209%, -130%]** | -1.633 ± 0.18 | -127% [-163%, -105%] | 0 | 42 | 0.03 | 0.5 |
| gemini-3.1-flash-lite | low | 4 | -0.525 ± 0.93 | 0.25 | 5.2 | +0.633 | **-83% [-154%, 89%]** | -1.157 ± 1.09 | -57% [-124%, 103%] | 4,440 | 32 | 0.05 | 1.4 |
| gemini-3.1-flash-lite | medium | 4 | -0.140 ± 0.97 | 0.50 | 7.0 | +0.633 | **-22% [-143%, 127%]** | -0.773 ± 1.06 | -135% [-168%, -112%] | 2,407 | 62 | 0.10 | 2.2 |
| gemini-3.1-flash-lite | high | 4 | -0.100 ± 1.02 | 0.50 | 7.0 | +0.633 | **-16% [-130%, 162%]** | -0.733 ± 1.18 | -104% [-128%, -77%] | 5,158 | 38 | 0.06 | 5.7 |
| gemini-3.5-flash | minimal | 4 | +0.315 ± 0.86 | 0.75 | 8.8 | +0.633 | **50% [-82%, 159%]** | -0.318 ± 0.94 | 36% [-51%, 133%] | 0 | 36 | 0.12 | 0.7 |
| gemini-3.5-flash | low | 4 | -0.152 ± 0.97 | 0.50 | 11.5 | +0.633 | **-24% [-149%, 117%]** | -0.785 ± 1.04 | -9% [-93%, 114%] | 5,330 | 47 | 0.24 | 4.5 |
| gemini-3.5-flash | medium | 6 | +0.768 ± 0.07 | 1.00 | 7.0 | +0.668 | **115% [97%, 147%]** | +0.100 ± 0.16 | 115% [97%, 147%] | 12,468 | 38 | 0.21 | 2.7 |
| gemini-3.5-flash | high | 6 | +0.452 ± 0.58 | 0.83 | 8.0 | +0.668 | **68% [-21%, 138%]** | -0.217 ± 0.62 | 26% [-50%, 110%] | 19,586 | 53 | 0.35 | 4.4 |
| gemini-3.8-flash | low | 5 | -0.344 ± 0.79 | 0.40 | 8.8 | +0.664 | **-52% [-181%, 46%]** | -1.008 ± 0.71 | -16% [-69%, 39%] | 0 | 52 | 0.11 | 1.9 |
| gemini-3.8-flash | medium | 6 | +0.365 ± 0.54 | 0.83 | 12.0 | +0.668 | **55% [-30%, 103%]** | -0.303 ± 0.55 | 2% [-71%, 61%] | 30,792 | 71 | 0.51 | 12.1 |
| gemini-3.8-flash | high | 7 | +0.646 ± 0.08 | 1.00 | 10.6 | +0.686 | **94% [79%, 117%]** | -0.040 ± 0.14 | 53% [-8%, 107%] | 36,002 | 67 | 0.51 | 11.9 |
| gemini-4-argon | medium | 2 | +0.610 ± 0.14 | 1.00 | 10.5 | +0.565 | **108% [73%, 174%]** | +0.045 ± 0.48 | 108% [73%, 174%] | 6,495 | 24 | 0.24 | 5.9 |
| gemini-4-argon | high | 1 | +0.810 ± 0.00 | 1.00 | 5.0 | +0.390 | **208%** | +0.420 ± 0.00 | 208% | 18,266 | 46 | 0.48 | 27.1 |
| gemini-4-carbon (imported†) | default | 6 | +0.688 ± 0.10 | 1.00 | 8.8 | +0.700 | **98% [85%, 115%]** | -0.012 ± 0.10 | 78% [38%, 110%] | 34,400* | 86 | 1.03 | – |

Reference on the union of these seeds: solver +0.686 ± 0.11 (n=7, acc 1.00); grok_tactics +0.379 ± 0.20 (n=7, acc 0.71); heuristic -0.321 ± 0.63 (n=7, acc 0.43); do_nothing +0.000 ± 0.00 (n=7, acc 0.00)

## hard

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 4 | -1.000 ± 0.00 | 0.00 | 4.0 | +0.547 | **-183% [-270%, -150%]** | -1.548 ± 0.18 | -195% [-314%, -157%] | 0 | 32 | 0.03 | 0.5 |
| gemini-3.1-flash-lite | low | 4 | -0.092 ± 1.03 | 0.50 | 7.8 | +0.547 | **-17% [-164%, 168%]** | -0.640 ± 1.11 | -138% [-165%, -94%] | 4,867 | 34 | 0.05 | 1.5 |
| gemini-3.1-flash-lite | medium | 4 | -1.000 ± 0.00 | 0.00 | 5.8 | +0.547 | **-183% [-270%, -150%]** | -1.548 ± 0.18 | -122% [-175%, -57%] | 1,805 | 39 | 0.05 | 3.4 |
| gemini-3.1-flash-lite | high | 4 | -0.580 ± 0.82 | 0.25 | 7.0 | +0.547 | **-106% [-165%, 70%]** | -1.127 ± 1.00 | -95% [-154%, 80%] | 6,556 | 46 | 0.08 | 6.1 |
| gemini-3.5-flash | minimal | 4 | -0.320 ± 0.78 | 0.50 | 12.2 | +0.547 | **-58% [-206%, 59%]** | -0.867 ± 0.73 | -47% [-187%, 63%] | 0 | 66 | 0.24 | 1.6 |
| gemini-3.5-flash | low | 4 | +0.172 ± 0.77 | 0.75 | 13.8 | +0.547 | **32% [-99%, 158%]** | -0.375 ± 0.87 | 38% [-85%, 167%] | 8,362 | 54 | 0.30 | 5.0 |
| gemini-3.5-flash | medium | 6 | +0.557 ± 0.10 | 1.00 | 12.2 | +0.573 | **97% [76%, 126%]** | -0.017 ± 0.15 | 35% [-47%, 121%] | 20,349 | 61 | 0.41 | 6.6 |
| gemini-3.5-flash | high | 6 | +0.608 ± 0.11 | 1.00 | 9.3 | +0.573 | **106% [82%, 145%]** | +0.035 ± 0.18 | 95% [67%, 142%] | 23,011 | 50 | 0.35 | 4.1 |
| gemini-3.8-flash | low | 6 | +0.170 ± 0.49 | 0.83 | 12.7 | +0.573 | **30% [-58%, 91%]** | -0.403 ± 0.51 | 47% [17%, 73%] | 0 | 69 | 0.18 | 2.6 |
| gemini-3.8-flash | medium | 6 | +0.025 ± 0.64 | 0.67 | 13.0 | +0.573 | **4% [-111%, 92%]** | -0.548 ± 0.58 | 46% [-13%, 91%] | 27,899 | 60 | 0.44 | 10.9 |
| gemini-3.8-flash | high | 5 | +0.166 ± 0.58 | 0.80 | 16.8 | +0.584 | **28% [-79%, 87%]** | -0.418 ± 0.58 | 12% [-87%, 84%] | 50,463 | 86 | 0.80 | 15.2 |
| gemini-4-argon | medium | 2 | +0.560 ± 0.08 | 1.00 | 14.5 | +0.665 | **84% [81%, 87%]** | -0.105 ± 0.03 | 67% [49%, 81%] | 14,829 | 32 | 0.50 | 23.1 |
| gemini-4-argon | high | 2 | +0.665 ± 0.03 | 1.00 | 11.5 | +0.665 | **100% [99%, 102%]** | +0.000 ± 0.02 | 80% [73%, 89%] | 34,159 | 95 | 1.14 | 47.3 |
| gemini-4-carbon | low | 1 | +0.620 ± 0.00 | 1.00 | 9.0 | +0.640 | **97%** | -0.020 ± 0.00 | 98% | 0 | 47 | 0.31 | 23.4 |
| gemini-4-carbon | high | 2 | +0.675 ± 0.07 | 1.00 | 8.5 | +0.665 | **102% [100%, 103%]** | +0.010 ± 0.02 | 107% [101%, 115%] | 42,952 | 76 | 1.30 | 35.6 |
| gemini-4-carbon (imported†) | default | 10 | +0.379 ± 0.32 | 0.90 | 12.0 | +0.576 | **66% [5%, 117%]** | -0.197 ± 0.36 | 79% [45%, 117%] | 49,686* | 110 | 1.57 | – |

Reference on the union of these seeds: solver +0.576 ± 0.11 (n=10, acc 1.00); grok_tactics +0.529 ± 0.11 (n=10, acc 1.00); heuristic +0.221 ± 0.29 (n=10, acc 0.90); do_nothing +0.000 ± 0.00 (n=10, acc 0.00)

Provenance: tiers v1.4, v1.4 (imported dir); launch commits 107c485, 2786c00, 498bccdea8, 8fa04b3391, e9f58b4580; code fingerprints (env/harness/client files) 06ea9b6a0f68d1dc, None; API-served model versions gemini-3.6-flash, gemini-3.8-flash, gemini-4-argon.

\* imported cell: output tokens incl. thinking (the measurement's usage does not split thinking out).
† imported read-only from the AfterQuery measurement (branch justSilas-gemini); not rerun by the ladder.

## Which mistakes does thinking fix?

Solver regret per episode by failure tag (`canary.solver.regret.attribute`), pooled over the models that ran low, medium and high: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash. Δ = high − low (negative = thinking fixes it).

**medium**

| tag | low (n=13) | medium (n=16) | high (n=17) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.048 (6% eps) | +0.048 |
| other:accuse | 0.048 (8% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.048 |
| other:plant_canary | 0.027 (85% eps) | 0.017 (81% eps) | 0.020 (82% eps) | -0.006 |
| other:restrict_access | 0.000 (0% eps) | 0.007 (12% eps) | 0.009 (12% eps) | +0.009 |
| over_restriction | 0.008 (8% eps) | 0.005 (6% eps) | 0.005 (6% eps) | -0.003 |
| premature_accusation | 0.690 (62% eps) | 0.468 (50% eps) | 0.470 (53% eps) | -0.220 |
| uninformative_canary | 0.003 (8% eps) | 0.005 (12% eps) | 0.000 (0% eps) | -0.003 |

**hard**

| tag | low (n=14) | medium (n=16) | high (n=15) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.049 (7% eps) | +0.049 |
| other:accuse | 0.082 (64% eps) | 0.032 (38% eps) | 0.045 (47% eps) | -0.037 |
| other:advance_day | 0.000 (0% eps) | 0.002 (6% eps) | 0.000 (0% eps) | +0.000 |
| other:plant_canary | 0.051 (100% eps) | 0.031 (88% eps) | 0.034 (93% eps) | -0.017 |
| other:restrict_access | 0.009 (7% eps) | 0.000 (0% eps) | 0.027 (13% eps) | +0.017 |
| over_restriction | 0.010 (7% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.010 |
| premature_accusation | 0.436 (36% eps) | 0.504 (50% eps) | 0.313 (33% eps) | -0.123 |
| uninformative_canary | 0.002 (7% eps) | 0.017 (38% eps) | 0.033 (47% eps) | +0.030 |

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
