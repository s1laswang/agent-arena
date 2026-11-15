# Gemini ablations (generated 2026-11-15T02:44:46+0200 by `python -m canary.gemini.ablations`)

All numbers come from committed files under results/gemini/. 95% CIs: Wilson for rates, t-normal for means, paired bootstrap from ladder.json for % of solver.

## 1. Thought-signature replay: OFF vs ON
gemini-3.8-flash, thinking_level medium, hard tier, dev seeds 0-9. OFF strips `provider_items` (the model's own Content, signatures included) from every assistant turn before each call (`LedgeredClient(drop_signatures=True)`, `ladder --no-thought-signatures`). With signatures ON the agent plays all 10 episodes: 0/628 API errors (0.0%, CI [0.0, 0.6]), 0/628 invalid tool calls (0.0%, CI [0.0, 0.6]), accuracy 70.0% (CI [39.7, 89.2]), mean score 0.079 (CI -0.39 to 0.55), 14% of the solver on the same seeds (CI [-71.4, 85.2]). With signatures OFF the API rejects the first request that replays a model function call on 10/10 seeds (Wilson CI [72.2, 100.0]): `google.genai.errors.ClientError 400 INVALID_ARGUMENT`: "Function call is missing a thought_signature in functionCall parts. This is required for tools to work correctly, and missing thought_signature may lead to degraded model performance. Additional data, function call `default_api:status` , position 2. Please refer to https://aistudio.google.com/docs/thought-signatures for more details." 10/20 calls failed (every first call succeeded, every second call was rejected), so 0 episodes are playable and accuracy, score and % of solver are undefined, not zero. All 10 OFF episodes are infra-invalid and unscored. The finding: on Gemini 3.x, multi-turn function calling does not work at all without thought-signature replay; it is a hard requirement of the API, not an optimisation.

| arm | valid eps | API errors | invalid tool calls | accuracy | mean score | % of solver |
|---|---|---|---|---|---|---|
| ON | 10 | 0/628 [0.0, 0.6] | 0/628 [0.0, 0.6] | 70.0% [39.7, 89.2] | 0.079 [-0.39, 0.55] | 14% [-71.4, 85.2] |
| OFF | 0 (10 infra-invalid) | 10/20 [29.9, 70.1] | n/a | n/a | n/a | n/a |

## 2. Explicit context cache: cost delta (no new calls)
Input: the de-duplicated union of every committed ledger under results/gemini (canary.gemini.dashboard.committed_ledgers + load_ledger, the dashboard's own dedupe). Per ledger row: paid = canary.llm.pricing.cost(...)['cost_usd_est'] (cached tokens at CACHED_PRICES; models without a cached price use 10% of input); counterfactual = 'cost_usd' (all input at the full price). Models canary.llm.pricing lacks (gemini-3.5-flash, gemini-3.1-flash-lite) are priced from the dashboard's EXTRA_PRICES (the ladder_report list prices, incl. their cached-input price). Batch rows at 50%. Explicit-cache storage (per token-hour) is not in the ledger and is not included. Gallery = the atlas-feature runs whose run_id the gallery_cache records. Atlas + gallery: 54,584,568 of 64,395,859 input tokens cached (84.8%); paid $21.72 vs $58.56 uncached, saving $36.84 (62.9%). Atlas alone: $21.60 vs $58.45 (63.0% saved); gallery alone: $0.12 vs $0.12 (0.0% saved). Whole programme (all 45,692 ledgered calls, mostly implicit caching on ladder episodes): 88.0% of 1,346,251,331 input tokens cached; $407.34 paid vs $1797.18, saving $1389.84 (77.3%). These are exact accounting deltas over every ledgered call, not samples, so no CI applies. 702 calls of models with no list price in either price table count $0 on both sides (gemini-3.8-live 17, gemini-embedding-2 305, gemma-4-26b-a4b-it 73, gemma-4-31b-it 306, unknown 1). (Section 2 regenerated 2026-11-15T05:23:40+0200.)

| scope | calls | input tok | cached | paid $ | uncached $ | saved $ | saved % |
|---|---|---|---|---|---|---|---|
| atlas | 455 | 64,359,208 | 84.8% | 21.60 | 58.45 | 36.84 | 63.0 |
| gallery | 9 | 36,651 | 0.0% | 0.12 | 0.12 | 0.00 | 0.0 |
| atlas_plus_gallery | 464 | 64,395,859 | 84.8% | 21.72 | 58.56 | 36.84 | 62.9 |
| programme | 45,692 | 1,346,251,331 | 88.0% | 407.34 | 1797.18 | 1389.84 | 77.3 |

## 3. Thinking-level sweep (no new calls)
Regenerated 2026-11-15T04:47:20+0200 from the canonical results/gemini/ladder.json (git 76097d7843); sections 1 and 2 above are unchanged from 2026-11-15T02:44:46+0200. 42 model x thinking-level x tier cells. % of solver is paired on the same seeds. **Bold** = the 95% CI excludes 100%: **18 of 42 cells exclude parity, all below the solver**. gemini-3.5-flash is the requested id; the API serves gemini-3.6-flash. Thinking tokens marked * are estimates.

| tier | model | level | n | % of solver [95% CI] | thinking tok/ep | USD/ep |
|---|---|---|---|---|---|---|
| hard | gemini-3.1-flash-lite | minimal | 10 | **-174% [-215, -150]** | 0 | 0.030 |
| hard | gemini-3.1-flash-lite | low | 10 | **-79% [-164, 17]** | 5,543 | 0.056 |
| hard | gemini-3.1-flash-lite | medium | 10 | **-174% [-215, -150]** | 1,666 | 0.041 |
| hard | gemini-3.1-flash-lite | high | 10 | **-82% [-167, 11]** | 5,679 | 0.064 |
| hard | gemini-3.5-flash | minimal | 10 | **-32% [-124, 34]** | 0 | 0.248 |
| hard | gemini-3.5-flash | low | 10 | 46% [-37, 104] | 8,531 | 0.275 |
| hard | gemini-3.5-flash | medium | 40 | 87% [50, 147] | 20,275 | 0.421 |
| hard | gemini-3.5-flash | high | 40 | 88% [51, 138] | 26,775 | 0.451 |
| hard | gemini-3.8-flash | low | 10 | **3% [-82, 68]** | 0 | 0.162 |
| hard | gemini-3.8-flash | medium | 10 | **14% [-71, 85]** | 28,300 | 0.455 |
| hard | gemini-3.8-flash | high | 20 | 51% [-5, 123] | 50,732 | 0.779 |
| hard | gemini-4-argon | low | 21 | 57% [-6, 127] | 10 | 0.230 |
| hard | gemini-4-argon | medium | 21 | 64% [12, 129] | 10,924 | 0.512 |
| hard | gemini-4-argon | high | 15 | 73% [14, 117] | 41,967 | 1.468 |
| hard | gemini-4-carbon | low | 10 | 80% [62, 107] | 289 | 0.523 |
| hard | gemini-4-carbon | high | 10 | 106% [94, 126] | 63,171 | 1.931 |
| hard | gemini-4-carbon | default | 22 | 108% [62, 189] | 48,351* | 1.501 |
| hard | gemini-4-hydrogen | low | 12 | 87% [35, 125] | 3,537 | 0.150 |
| hard | gemini-4-hydrogen | medium | 12 | 87% [64, 118] | 16,120 | 0.473 |
| hard | gemini-4-hydrogen | high | 10 | **70% [15, 98]** | 33,351 | 0.720 |
| hard | gemini-4-hydrogen | xhigh | 13 | 97% [46, 140] | 65,787 | 1.191 |
| medium | gemini-3.1-flash-lite | minimal | 10 | **-110% [-153, -53]** | 0 | 0.033 |
| medium | gemini-3.1-flash-lite | low | 10 | **-33% [-110, 48]** | 4,290 | 0.044 |
| medium | gemini-3.1-flash-lite | medium | 10 | **-90% [-133, -22]** | 1,686 | 0.059 |
| medium | gemini-3.1-flash-lite | high | 10 | **-88% [-129, -16]** | 5,544 | 0.060 |
| medium | gemini-3.5-flash | minimal | 10 | 73% [22, 108] | 0 | 0.116 |
| medium | gemini-3.5-flash | low | 10 | **3% [-69, 73]** | 7,269 | 0.266 |
| medium | gemini-3.5-flash | medium | 20 | 89% [60, 109] | 15,033 | 0.289 |
| medium | gemini-3.5-flash | high | 20 | 75% [39, 104] | 21,513 | 0.386 |
| medium | gemini-3.8-flash | low | 10 | **-2% [-77, 62]** | 0 | 0.122 |
| medium | gemini-3.8-flash | medium | 10 | **65% [18, 93]** | 33,837 | 0.549 |
| medium | gemini-3.8-flash | high | 20 | **69% [33, 97]** | 45,240 | 0.618 |
| medium | gemini-4-argon | low | 22 | 96% [74, 117] | 0 | 0.155 |
| medium | gemini-4-argon | medium | 22 | 82% [55, 105] | 8,042 | 0.295 |
| medium | gemini-4-argon | high | 16 | 72% [27, 108] | 32,205 | 0.992 |
| medium | gemini-4-carbon | low | 10 | 86% [71, 107] | 530 | 0.388 |
| medium | gemini-4-carbon | high | 10 | **88% [72, 99]** | 50,290 | 1.469 |
| medium | gemini-4-carbon | default | 15 | 78% [55, 100] | 36,812* | 1.140 |
| medium | gemini-4-hydrogen | low | 13 | 78% [51, 104] | 2,932 | 0.150 |
| medium | gemini-4-hydrogen | medium | 11 | 71% [22, 105] | 10,614 | 0.356 |
| medium | gemini-4-hydrogen | high | 10 | 93% [84, 103] | 22,876 | 0.633 |
| medium | gemini-4-hydrogen | xhigh | 12 | **89% [76, 100]** | 60,073 | 1.126 |

## §4 replacement (3 sentences)

> **Thought signatures are load-bearing:** with signature replay stripped, the API rejected the first function-call replay on 10/10 hard-tier episodes of gemini-3.8-flash (400 INVALID_ARGUMENT, "Function call is missing a thought_signature"; Wilson 95% CI [72.2, 100.0]), so 0 episodes were playable, versus 10/10 played with replay on (0/628 API errors, accuracy 70.0%, CI [39.7, 89.2]).
> **Explicit context caching** cut the corpus-scale Atlas reads from $58.56 to $21.72 (62.9% saved over all 464 ledgered atlas/gallery calls; 84.8% of 64.4M input tokens cached; the 9 gallery calls used no cache), and caching overall saved 77.3% ($1389.84 of $1797.18) across all 45,692 ledgered calls in the programme (list prices; 702 calls of unpriced models such as embeddings and hosted Gemma count $0).
> **`thinking_level` turns compute into a controlled variable on one model:** on the hard tier, gemini-3.6-flash (requested as 3.5-flash) goes from -32% [-124, 34] at minimal (n=10, 0 thinking tok, $0.25/ep) to 87% [50, 147] at medium (n=40, 20,275 thinking tok, $0.42/ep) of the solver on the same seeds, while gemini-4-argon rises across low → medium → high (57% → 64% → 73%; 57% [-6, 127] at low (n=21, 10 thinking tok, $0.23/ep) vs 73% [14, 117] at high (n=15, 41,967 thinking tok, $1.47/ep), CIs overlap); across all model x level x tier cells, 18 of 42 cells exclude parity, all below the solver (95% CIs).
