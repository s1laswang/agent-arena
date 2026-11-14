# Gemini Ladder (Canary v1.4)

Generated 2026-11-14T14:50:26+0200 at git `ab55927907` from `~/agent-arena-data/gemini/ladder/ladder-v14`. 64 valid Gemini episodes in 24 cells; ledger: 3224 calls, 64 run ids, list price $18.29.

Every cell is one (model, thinking level, tier) played by the in-process `LLMPolicy` (full history, thought-signature replay) through `canary.agents.play`, the frontier measurement's own runner, on v1.4 dev seeds. The solver and baselines are replayed on exactly the same worlds. **ratio** = mean score / solver's mean on the same seeds, with a paired bootstrap 95% CI over seeds; **luck-adj.** scores each accusation as P·V − (1−P) under the solver's exact posterior at that step.

## medium

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 2 | -1.000 ± 0.00 | 0.00 | 6.5 | +0.565 | **-177% [-256%, -135%]** | -1.565 ± 0.34 | -122% [-157%, -104%] | 0 | 52 | 0.04 | 0.5 |
| gemini-3.1-flash-lite | low | 2 | -0.050 ± 1.86 | 0.50 | 5.0 | +0.565 | **-9% [-135%, 231%]** | -0.615 ± 2.20 | 5% [-115%, 231%] | 4,000 | 34 | 0.05 | 1.4 |
| gemini-3.1-flash-lite | medium | 2 | +0.720 ± 0.02 | 1.00 | 8.0 | +0.565 | **127% [99%, 182%]** | +0.155 ± 0.32 | -125% [-169%, -102%] | 3,203 | 78 | 0.14 | 2.8 |
| gemini-3.1-flash-lite | high | 2 | -0.085 ± 1.79 | 0.50 | 6.0 | +0.565 | **-15% [-135%, 213%]** | -0.650 ± 2.14 | -128% [-133%, -118%] | 4,672 | 32 | 0.05 | 9.7 |
| gemini-3.5-flash | minimal | 2 | -0.110 ± 1.74 | 0.50 | 10.5 | +0.565 | **-19% [-135%, 200%]** | -0.675 ± 2.09 | 50% [-30%, 200%] | 0 | 43 | 0.14 | 0.8 |
| gemini-3.5-flash | low | 2 | -0.080 ± 1.80 | 0.50 | 9.5 | +0.565 | **-14% [-135%, 215%]** | -0.645 ± 2.15 | 75% [2%, 215%] | 5,741 | 44 | 0.24 | 6.6 |
| gemini-3.5-flash | medium | 2 | +0.865 ± 0.05 | 1.00 | 4.5 | +0.565 | **153% [120%, 215%]** | +0.300 ± 0.29 | 153% [120%, 215%] | 10,996 | 26 | 0.16 | 2.1 |
| gemini-3.5-flash | high | 2 | -0.080 ± 1.80 | 0.50 | 8.5 | +0.565 | **-14% [-135%, 215%]** | -0.645 ± 2.15 | 40% [-53%, 215%] | 24,326 | 50 | 0.37 | 4.3 |
| gemini-3.8-flash | low | 2 | -0.220 ± 1.53 | 0.50 | 9.5 | +0.565 | **-39% [-256%, 76%]** | -0.785 ± 1.19 | 52% [8%, 76%] | 0 | 58 | 0.12 | 2.0 |
| gemini-3.8-flash | medium | 3 | +0.613 ± 0.15 | 1.00 | 12.0 | +0.643 | **95% [82%, 123%]** | -0.030 ± 0.13 | 16% [-67%, 94%] | 27,653 | 66 | 0.46 | 7.9 |
| gemini-3.8-flash | high | 3 | +0.663 ± 0.12 | 1.00 | 9.7 | +0.643 | **103% [73%, 185%]** | +0.020 ± 0.31 | 68% [-20%, 185%] | 34,751 | 67 | 0.50 | 8.8 |
| gemini-4-carbon (imported†) | default | 6 | +0.688 ± 0.10 | 1.00 | 8.8 | +0.700 | **98% [85%, 115%]** | -0.012 ± 0.10 | 78% [38%, 110%] | 34,400* | 86 | 1.03 | – |

Reference on the union of these seeds: solver +0.700 ± 0.13 (n=6, acc 1.00); grok_tactics +0.338 ± 0.21 (n=6, acc 0.67); heuristic -0.470 ± 0.66 (n=6, acc 0.33); do_nothing +0.000 ± 0.00 (n=6, acc 0.00)

## hard

| model | thinking | n | score ± 95% CI | acc. | accuse day | solver, same seeds | **score / solver [95% CI]** | paired diff ± CI | luck-adj. / solver | thinking tok/ep | calls/ep | $/ep | min/ep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | minimal | 2 | -1.000 ± 0.00 | 0.00 | 4.5 | +0.665 | **-150% [-156%, -145%]** | -1.665 ± 0.05 | -164% [-180%, -150%] | 0 | 34 | 0.03 | 0.5 |
| gemini-3.1-flash-lite | low | 2 | -0.090 ± 1.78 | 0.50 | 11.0 | +0.665 | **-14% [-156%, 119%]** | -0.755 ± 1.73 | -152% [-180%, -129%] | 4,902 | 42 | 0.07 | 2.0 |
| gemini-3.1-flash-lite | medium | 2 | -1.000 ± 0.00 | 0.00 | 5.5 | +0.665 | **-150% [-156%, -145%]** | -1.665 ± 0.05 | -161% [-180%, -145%] | 1,232 | 30 | 0.03 | 5.0 |
| gemini-3.1-flash-lite | high | 2 | -1.000 ± 0.00 | 0.00 | 6.0 | +0.665 | **-150% [-156%, -145%]** | -1.665 ± 0.05 | -133% [-146%, -122%] | 4,398 | 38 | 0.06 | 9.7 |
| gemini-3.5-flash | minimal | 2 | -0.390 ± 1.20 | 0.50 | 14.0 | +0.665 | **-59% [-145%, 34%]** | -1.055 ± 1.24 | -64% [-150%, 39%] | 0 | 79 | 0.29 | 2.0 |
| gemini-3.5-flash | low | 2 | -0.295 ± 1.38 | 0.50 | 17.0 | +0.665 | **-44% [-156%, 59%]** | -0.960 ± 1.33 | -35% [-140%, 53%] | 9,753 | 66 | 0.39 | 7.8 |
| gemini-3.5-flash | medium | 2 | +0.535 ± 0.28 | 1.00 | 14.5 | +0.665 | **80% [61%, 99%]** | -0.130 ± 0.24 | -18% [-138%, 82%] | 24,572 | 75 | 0.51 | 10.1 |
| gemini-3.5-flash | high | 2 | +0.645 ± 0.01 | 1.00 | 9.5 | +0.665 | **97% [94%, 100%]** | -0.020 ± 0.04 | 98% [92%, 106%] | 22,736 | 44 | 0.31 | 3.8 |
| gemini-3.8-flash | low | 2 | -0.195 ± 1.58 | 0.50 | 9.0 | +0.665 | **-29% [-156%, 88%]** | -0.860 ± 1.53 | 50% [11%, 83%] | 0 | 49 | 0.12 | 1.7 |
| gemini-3.8-flash | medium | 4 | -0.165 ± 0.95 | 0.50 | 11.2 | +0.547 | **-30% [-217%, 106%]** | -0.713 ± 0.86 | 74% [18%, 101%] | 22,644 | 47 | 0.30 | 6.0 |
| gemini-3.8-flash | high | 2 | +0.570 ± 0.10 | 1.00 | 15.0 | +0.665 | **86% [81%, 90%]** | -0.095 ± 0.05 | 89% [85%, 93%] | 41,445 | 68 | 0.58 | 9.9 |
| gemini-4-carbon (imported†) | default | 10 | +0.379 ± 0.32 | 0.90 | 12.0 | +0.576 | **66% [5%, 117%]** | -0.197 ± 0.36 | 79% [45%, 117%] | 49,686* | 110 | 1.57 | – |

Reference on the union of these seeds: solver +0.576 ± 0.11 (n=10, acc 1.00); grok_tactics +0.529 ± 0.11 (n=10, acc 1.00); heuristic +0.221 ± 0.29 (n=10, acc 0.90); do_nothing +0.000 ± 0.00 (n=10, acc 0.00)

Provenance: tiers v1.4, v1.4 (imported dir); launch commits 2786c00, None; code fingerprints (env/harness/client files) 6ea5fa46401d3f20, None; API-served model versions –.

\* imported cell: output tokens incl. thinking (the measurement's usage does not split thinking out).
† imported read-only from the AfterQuery measurement (branch justSilas-gemini); not rerun by the ladder.

## Which mistakes does thinking fix?

Solver regret per episode by failure tag (`canary.solver.regret.attribute`), pooled over the models that ran low, medium and high: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash. Δ = high − low (negative = thinking fixes it).

**medium**

| tag | low (n=6) | medium (n=7) | high (n=7) | Δ high−low |
|---|---|---|---|---|
| ignored_delay | 0.000 (0% eps) | 0.000 (0% eps) | 0.117 (14% eps) | +0.117 |
| other:accuse | 0.103 (17% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.103 |
| other:plant_canary | 0.015 (83% eps) | 0.016 (86% eps) | 0.011 (100% eps) | -0.004 |
| other:restrict_access | 0.000 (0% eps) | 0.009 (14% eps) | 0.012 (14% eps) | +0.012 |
| premature_accusation | 0.264 (17% eps) | 0.447 (57% eps) | 0.427 (57% eps) | +0.163 |
| uninformative_canary | 0.000 (0% eps) | 0.006 (14% eps) | 0.000 (0% eps) | +0.000 |

**hard**

| tag | low (n=6) | medium (n=8) | high (n=6) | Δ high−low |
|---|---|---|---|---|
| other:accuse | 0.113 (50% eps) | 0.049 (50% eps) | 0.016 (50% eps) | -0.097 |
| other:plant_canary | 0.050 (100% eps) | 0.035 (100% eps) | 0.029 (83% eps) | -0.021 |
| other:restrict_access | 0.000 (0% eps) | 0.000 (0% eps) | 0.025 (17% eps) | +0.025 |
| over_restriction | 0.023 (17% eps) | 0.000 (0% eps) | 0.000 (0% eps) | -0.023 |
| premature_accusation | 0.625 (50% eps) | 0.625 (50% eps) | 0.483 (33% eps) | -0.142 |
| uninformative_canary | 0.000 (0% eps) | 0.018 (38% eps) | 0.018 (50% eps) | +0.018 |

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
