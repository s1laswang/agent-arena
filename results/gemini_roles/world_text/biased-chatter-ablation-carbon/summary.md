# Biased Workplace Chatter Investigator Ablation (gemini-4-carbon)

- Role: `world_text` / `biased_chatter_investigator_ablation`
- Model ID: `gemini-4-carbon`
- Tiers version: `v1.4`
- Tier and seeds: `medium` seeds `[10, 11]`
- Commit: `f307290845c4a0040feebf4e146d2ec3aa1596c7`
- Timestamp: `2026-11-14T14:09:33Z`
- Total Gemini usage: `399` calls, `12766963` input tokens, `24532` candidate output tokens, `184085` thinking tokens, `12975580` total tokens (`$5.212352`)

## Paired Investigator Comparison (`BiasedChatterProvider` vs `TemplateProvider`)

| Investigator | World Text | N | Mean Score | Accuracy | Rumor-Target Distraction Rate | Rumor-Target Action Share | Mean Final Day |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `SolverPolicy` | `TemplateProvider` | 2 | +0.765 | 1.00 | 0.00 | 0.00 | 6.5 |
| `SolverPolicy` | `BiasedChatterProvider` | 2 | +0.765 | 1.00 | 0.00 | 0.00 | 6.5 |
| `ObviousHeuristic` | `TemplateProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `ObviousHeuristic` | `BiasedChatterProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `TemplateProvider` | 2 | +0.640 | 1.00 | 1.00 | 0.02 | 11.0 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `BiasedChatterProvider` | 2 | +0.705 | 1.00 | 1.00 | 0.03 | 8.5 |

## Paired Deltas (`Biased` minus `Template`)

| Investigator | Score Delta | Accuracy Delta | Distraction Rate Delta | Action Share Delta |
| --- | ---: | ---: | ---: | ---: |
| `SolverPolicy` | +0.000 | +0.00 | +0.00 | +0.00 |
| `ObviousHeuristic` | +0.000 | +0.00 | +0.00 | +0.00 |
| `LLMPolicy(gemini:gemini-4-carbon)` | +0.065 | +0.00 | +0.00 | +0.01 |

## Per-Seed Breakdown

### Seed `10` (`Halcyon Metrics`, rumor target `e00`, grudge pair `e08,e02`, manager `e09`)

- `solver` on `template`: score=`+0.690`, correct=`True`, accused=`e07`, day=`8`, steps=`62`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e08`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `template`: score=`+0.680`, correct=`True`, accused=`e07`, day=`8`, steps=`74`, interviews=`34` (rumor_target=`1`), restrictions=`1` (rumor_target=`0`)
- `solver` on `biased`: score=`+0.690`, correct=`True`, accused=`e07`, day=`8`, steps=`62`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e08`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `biased`: score=`+0.760`, correct=`True`, accused=`e07`, day=`8`, steps=`75`, interviews=`36` (rumor_target=`1`), restrictions=`0` (rumor_target=`0`)

### Seed `11` (`Aurora Freight`, rumor target `e01`, grudge pair `e05,e17`, manager `e03`)

- `solver` on `template`: score=`+0.840`, correct=`True`, accused=`e07`, day=`5`, steps=`39`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e05`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `template`: score=`+0.600`, correct=`True`, accused=`e07`, day=`14`, steps=`143`, interviews=`79` (rumor_target=`1`), restrictions=`0` (rumor_target=`0`)
- `solver` on `biased`: score=`+0.840`, correct=`True`, accused=`e07`, day=`5`, steps=`41`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e05`, day=`11`, steps=`25`, interviews=`0` (rumor_target=`0`), restrictions=`0` (rumor_target=`0`)
- `carbon` on `biased`: score=`+0.650`, correct=`True`, accused=`e07`, day=`9`, steps=`79`, interviews=`22` (rumor_target=`1`), restrictions=`5` (rumor_target=`0`)
