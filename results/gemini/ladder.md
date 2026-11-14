# Gemini Ladder (Canary v1.4)

> **Headline findings** (auto-generated from the table below: 1–8 paired seeds per cell; 95% CIs are wide, so read them as directions).
>
> **gemini-3.5-flash with medium or high thinking matches the reference solver on hard:** 92% [76%, 113%] and 102% [84%, 129%] of the solver on the same seeds, 16/16 correct accusations, $0.34–0.39 per episode, versus $1.30 for gemini-4-carbon at high thinking.
>
> **gemini-3.1-flash-lite fails at every thinking level:** its mean score is below the do-nothing score (0) in 8/8 (level, tier) cells; at minimal thinking it accused the wrong employee in 8/8 episodes.
>
> **gemini-3.8-flash gains from thinking on medium** (-52% [-181%, 46%] at low → 93% [80%, 112%] at high) **but not on hard** (30% [-58%, 91%] → 17% [-72%, 80%]). Pooled over the flash models, low → high thinking changes premature-accusation regret by -0.18/episode on medium, -0.10/episode on hard; uninformative-canary regret goes 0.002 → 0.000 on medium, 0.002 → 0.024 on hard (thinking buys commit timing more than experiment design).

Generated 2026-11-14T18:47:49+0200 at git `016758ace5` from `~/agent-arena-data/gemini/ladder/ladder-v14`. 157 valid Gemini episodes in 34 cells; ledger: 9039 calls, 157 run ids, list price $62.55.

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
| gemini-3.5-flash | medium | 8 | +0.546 ± 0.44 | 0.88 | 8.1 | +0.703 | **78% [13%, 127%]** | -0.156 ± 0.47 | 83% [27%, 127%] | 14,388 | 47 | 0.28 | 3.3 |
| gemini-3.5-flash | high | 8 | +0.507 ± 0.43 | 0.88 | 8.4 | +0.703 | **72% [7%, 121%]** | -0.195 ± 0.45 | 43% [-22%, 101%] | 19,260 | 54 | 0.35 | 4.3 |
| gemini-3.8-flash | low | 5 | -0.344 ± 0.79 | 0.40 | 8.8 | +0.664 | **-52% [-181%, 46%]** | -1.008 ± 0.71 | -16% [-69%, 39%] | 0 | 52 | 0.11 | 1.9 |
| gemini-3.8-flash | medium | 8 | +0.439 ± 0.41 | 0.88 | 12.0 | +0.703 | **62% [1%, 97%]** | -0.264 ± 0.40 | 1% [-59%, 57%] | 31,977 | 70 | 0.50 | 11.2 |
| gemini-3.8-flash | high | 8 | +0.651 ± 0.07 | 1.00 | 11.0 | +0.703 | **93% [80%, 112%]** | -0.051 ± 0.12 | 32% [-31%, 91%] | 42,537 | 72 | 0.58 | 12.4 |
| gemini-4-argon | low | 2 | +0.835 ± 0.03 | 1.00 | 4.5 | +0.565 | **148% [115%, 210%]** | +0.270 ± 0.31 | 148% [115%, 210%] | 0 | 16 | 0.08 | 2.8 |
| gemini-4-argon | medium | 2 | +0.610 ± 0.14 | 1.00 | 10.5 | +0.565 | **108% [73%, 174%]** | +0.045 ± 0.48 | 108% [73%, 174%] | 6,495 | 24 | 0.24 | 5.9 |
| gemini-4-argon | high | 1 | +0.810 ± 0.00 | 1.00 | 5.0 | +0.390 | **208%** | +0.420 ± 0.00 | 208% | 18,266 | 46 | 0.48 | 27.1 |
| gemini-4-carbon | low | 2 | +0.710 ± 0.24 | 1.00 | 8.0 | +0.565 | **126% [80%, 213%]** | +0.145 ± 0.58 | 126% [80%, 213%] | 359 | 53 | 0.29 | 20.7 |
| gemini-4-carbon | high | 1 | +0.780 ± 0.00 | 1.00 | 6.0 | +0.740 | **105%** | +0.040 ± 0.00 | 105% | 48,433 | 57 | 1.03 | 20.2 |
| gemini-4-carbon (imported†) | default | 6 | +0.688 ± 0.10 | 1.00 | 8.8 | +0.700 | **98% [85%, 115%]** | -0.012 ± 0.10 | 78% [38%, 110%] | 34,400* | 86 | 1.03 | – |

Reference on the union of these seeds: solver +0.703 ± 0.10 (n=8, acc 1.00); grok_tactics +0.386 ± 0.17 (n=8, acc 0.75); heuristic -0.191 ± 0.60 (n=8, acc 0.50); do_nothing +0.000 ± 0.00 (n=8, acc 0.00)

## hard

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 4 | -1.000 ± 0.00 | 0.00 | 4.0 | +0.547 | **-183% [-270%, -150%]** | -1.548 ± 0.18 | -195% [-314%, -157%] | 0 | 32 | 0.03 | 0.5 |
| gemini-3.1-flash-lite | low | 4 | -0.092 ± 1.03 | 0.50 | 7.8 | +0.547 | **-17% [-164%, 168%]** | -0.640 ± 1.11 | -138% [-165%, -94%] | 4,867 | 34 | 0.05 | 1.5 |
| gemini-3.1-flash-lite | medium | 4 | -1.000 ± 0.00 | 0.00 | 5.8 | +0.547 | **-183% [-270%, -150%]** | -1.548 ± 0.18 | -122% [-175%, -57%] | 1,805 | 39 | 0.05 | 3.4 |
| gemini-3.1-flash-lite | high | 4 | -0.580 ± 0.82 | 0.25 | 7.0 | +0.547 | **-106% [-165%, 70%]** | -1.127 ± 1.00 | -95% [-154%, 80%] | 6,556 | 46 | 0.08 | 6.1 |
| gemini-3.5-flash | minimal | 4 | -0.320 ± 0.78 | 0.50 | 12.2 | +0.547 | **-58% [-206%, 59%]** | -0.867 ± 0.73 | -47% [-187%, 63%] | 0 | 66 | 0.24 | 1.6 |
| gemini-3.5-flash | low | 4 | +0.172 ± 0.77 | 0.75 | 13.8 | +0.547 | **32% [-99%, 158%]** | -0.375 ± 0.87 | 38% [-85%, 167%] | 8,362 | 54 | 0.30 | 5.0 |
| gemini-3.5-flash | medium | 8 | +0.550 ± 0.07 | 1.00 | 11.9 | +0.599 | **92% [76%, 113%]** | -0.049 ± 0.12 | 47% [-18%, 105%] | 19,798 | 59 | 0.39 | 5.9 |
| gemini-3.5-flash | high | 8 | +0.609 ± 0.08 | 1.00 | 8.9 | +0.599 | **102% [84%, 129%]** | +0.010 ± 0.13 | 93% [73%, 125%] | 23,152 | 47 | 0.34 | 4.0 |
| gemini-3.8-flash | low | 6 | +0.170 ± 0.49 | 0.83 | 12.7 | +0.573 | **30% [-58%, 91%]** | -0.403 ± 0.51 | 47% [17%, 73%] | 0 | 69 | 0.18 | 2.6 |
| gemini-3.8-flash | medium | 8 | +0.141 ± 0.49 | 0.75 | 13.1 | +0.599 | **24% [-72%, 86%]** | -0.458 ± 0.44 | 48% [4%, 81%] | 27,277 | 60 | 0.43 | 9.9 |
| gemini-3.8-flash | high | 8 | +0.100 ± 0.48 | 0.75 | 17.2 | +0.599 | **17% [-72%, 80%]** | -0.499 ± 0.46 | -13% [-92%, 59%] | 54,393 | 91 | 0.88 | 14.7 |
| gemini-4-argon | low | 2 | +0.695 ± 0.11 | 1.00 | 8.5 | +0.665 | **105% [93%, 117%]** | +0.030 ± 0.16 | 106% [96%, 118%] | 0 | 33 | 0.21 | 4.1 |
| gemini-4-argon | medium | 2 | +0.560 ± 0.08 | 1.00 | 14.5 | +0.665 | **84% [81%, 87%]** | -0.105 ± 0.03 | 67% [49%, 81%] | 14,829 | 32 | 0.50 | 23.1 |
| gemini-4-argon | high | 2 | +0.665 ± 0.03 | 1.00 | 11.5 | +0.665 | **100% [99%, 102%]** | +0.000 ± 0.02 | 80% [73%, 89%] | 34,159 | 95 | 1.14 | 47.3 |
| gemini-4-carbon | low | 2 | +0.455 ± 0.32 | 1.00 | 13.0 | +0.665 | **68% [42%, 97%]** | -0.210 ± 0.37 | 68% [44%, 98%] | 234 | 75 | 0.52 | 24.1 |
| gemini-4-carbon | high | 2 | +0.675 ± 0.07 | 1.00 | 8.5 | +0.665 | **102% [100%, 103%]** | +0.010 ± 0.02 | 107% [101%, 115%] | 42,952 | 76 | 1.30 | 35.6 |
| gemini-4-carbon (imported†) | default | 10 | +0.379 ± 0.32 | 0.90 | 12.0 | +0.576 | **66% [5%, 117%]** | -0.197 ± 0.36 | 79% [45%, 117%] | 49,686* | 110 | 1.57 | – |

Reference on the union of these seeds: solver +0.576 ± 0.11 (n=10, acc 1.00); grok_tactics +0.529 ± 0.11 (n=10, acc 1.00); heuristic +0.221 ± 0.29 (n=10, acc 0.90); do_nothing +0.000 ± 0.00 (n=10, acc 0.00)

Provenance: tiers v1.4, v1.4 (imported dir); launch commits 107c485, 2786c00, 498bccdea8, 8fa04b3391, e9f58b4580; code fingerprints (env/harness/client files) 06ea9b6a0f68d1dc, None; API-served model versions gemini-3.6-flash, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon.

\* imported cell: output tokens incl. thinking (the measurement's usage does not split thinking out).
† imported read-only from the AfterQuery measurement (branch justSilas-gemini); not rerun by the ladder.

## Which mistakes does thinking fix?

Solver regret per episode by failure tag (`canary.solver.regret.attribute`), pooled over the models that ran low, medium and high: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash, gemini-4-argon. Δ = high − low (negative = thinking fixes it).

**medium**

| tag | low (n=15) | medium (n=22) | high (n=21) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.039 (5% eps) | +0.039 |
| other:accuse | 0.041 (7% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.041 |
| other:plant_canary | 0.027 (87% eps) | 0.023 (86% eps) | 0.023 (86% eps) | -0.004 |
| other:restrict_access | 0.000 (0% eps) | 0.005 (9% eps) | 0.007 (10% eps) | +0.007 |
| over_restriction | 0.007 (7% eps) | 0.004 (4% eps) | 0.004 (5% eps) | -0.003 |
| premature_accusation | 0.598 (53% eps) | 0.404 (46% eps) | 0.416 (48% eps) | -0.182 |
| uninformative_canary | 0.002 (7% eps) | 0.003 (9% eps) | 0.000 (0% eps) | -0.002 |

**hard**

| tag | low (n=16) | medium (n=22) | high (n=22) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.034 (4% eps) | +0.034 |
| other:accuse | 0.076 (62% eps) | 0.046 (50% eps) | 0.044 (46% eps) | -0.032 |
| other:advance_day | 0.000 (0% eps) | 0.001 (4% eps) | 0.001 (4% eps) | +0.001 |
| other:plant_canary | 0.058 (100% eps) | 0.034 (91% eps) | 0.036 (96% eps) | -0.022 |
| other:restrict_access | 0.008 (6% eps) | 0.000 (0% eps) | 0.018 (9% eps) | +0.010 |
| over_restriction | 0.009 (6% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.009 |
| premature_accusation | 0.381 (31% eps) | 0.367 (36% eps) | 0.284 (32% eps) | -0.097 |
| uninformative_canary | 0.002 (6% eps) | 0.017 (36% eps) | 0.024 (36% eps) | +0.023 |

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
