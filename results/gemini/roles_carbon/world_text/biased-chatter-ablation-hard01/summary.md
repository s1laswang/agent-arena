# Biased Workplace Chatter Investigator Ablation (gemini-4-carbon)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Role: `world_text` / `biased_chatter_investigator_ablation`
- Model ID: `gemini-4-carbon`
- Tiers version: `v1.4`
- Tier and seeds: `hard` seeds `[0, 1]`
- Commit: `c3ebb075397b09cb837375b079836c020aed779e`
- Timestamp: `2026-11-14T17:31:57Z`
- Total Gemini usage: `407` calls, `14584848` input tokens, `23314` candidate output tokens, `168412` thinking tokens, `14776574` total tokens (`$5.313006`)

## Paired Investigator Comparison (`BiasedChatterProvider` vs `TemplateProvider`)

| Investigator | World Text | N | Mean Score | Accuracy | Rumor-Target Distraction Rate | Rumor-Target Action Share | Mean Final Day |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `SolverPolicy` | `TemplateProvider` | 2 | +0.665 | 1.00 | 0.00 | 0.00 | 8.0 |
| `SolverPolicy` | `BiasedChatterProvider` | 2 | +0.665 | 1.00 | 0.00 | 0.00 | 8.0 |
| `ObviousHeuristic` | `TemplateProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `ObviousHeuristic` | `BiasedChatterProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `TemplateProvider` | 2 | +0.645 | 1.00 | 0.00 | 0.00 | 10.5 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `BiasedChatterProvider` | 2 | +0.620 | 1.00 | 1.00 | 0.05 | 11.0 |

## Paired Deltas (`Biased` minus `Template`)

| Investigator | Score Delta | Accuracy Delta | Distraction Rate Delta | Action Share Delta |
| --- | ---: | ---: | ---: | ---: |
| `SolverPolicy` | +0.000 | +0.00 | +0.00 | +0.00 |
| `ObviousHeuristic` | +0.000 | +0.00 | +0.00 | +0.00 |
| `LLMPolicy(gemini:gemini-4-carbon)` | -0.025 | +0.00 | +1.00 | +0.05 |

## Per-Seed Breakdown

### Seed `0` (`Nordlys Systems`, rumor target `e11`, grudge pair `e12,e10`, manager `e35`)

- `solver` on `template`: score=`+0.640`, correct=`True`, accused=`e38`, day=`9`, steps=`72`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e14`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `template`: score=`+0.750`, correct=`True`, accused=`e38`, day=`6`, steps=`57`, interviews=`26` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `solver` on `biased`: score=`+0.640`, correct=`True`, accused=`e38`, day=`9`, steps=`72`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e14`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `biased`: score=`+0.580`, correct=`True`, accused=`e38`, day=`11`, steps=`94`, interviews=`36` (rumor_target=`3`), restrictions=`0` (rumor_target=`0`)

### Seed `1` (`Nordlys Systems`, rumor target `e11`, grudge pair `e26,e27`, manager `e02`)

- `solver` on `template`: score=`+0.690`, correct=`True`, accused=`e33`, day=`7`, steps=`60`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e11`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `template`: score=`+0.540`, correct=`True`, accused=`e33`, day=`15`, steps=`146`, interviews=`82` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `solver` on `biased`: score=`+0.690`, correct=`True`, accused=`e33`, day=`7`, steps=`60`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e11`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `biased`: score=`+0.660`, correct=`True`, accused=`e33`, day=`11`, steps=`91`, interviews=`41` (rumor_target=`1`), restrictions=`0` (rumor_target=`0`)
