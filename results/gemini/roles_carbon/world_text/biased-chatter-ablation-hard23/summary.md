# Biased Workplace Chatter Investigator Ablation (gemini-4-carbon)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Role: `world_text` / `biased_chatter_investigator_ablation`
- Model ID: `gemini-4-carbon`
- Tiers version: `v1.4`
- Tier and seeds: `hard` seeds `[2, 3]`
- Commit: `361fbab16b9c1016f72480d4550bb200dc7f5d60`
- Timestamp: `2026-11-14T23:24:52Z`
- Total Gemini usage: `511` calls, `26888048` input tokens, `30353` candidate output tokens, `235669` thinking tokens, `27154070` total tokens (`$7.977066`)

## Paired Investigator Comparison (`BiasedChatterProvider` vs `TemplateProvider`)

| Investigator | World Text | N | Mean Score | Accuracy | Rumor-Target Distraction Rate | Rumor-Target Action Share | Mean Final Day |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `SolverPolicy` | `TemplateProvider` | 2 | +0.430 | 1.00 | 0.00 | 0.00 | 13.5 |
| `SolverPolicy` | `BiasedChatterProvider` | 2 | +0.500 | 1.00 | 0.00 | 0.00 | 11.5 |
| `ObviousHeuristic` | `TemplateProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `ObviousHeuristic` | `BiasedChatterProvider` | 2 | -1.000 | 0.00 | 0.00 | 0.00 | 11.0 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `TemplateProvider` | 2 | +0.320 | 1.00 | 0.00 | 0.00 | 17.0 |
| `LLMPolicy(gemini:gemini-4-carbon)` | `BiasedChatterProvider` | 2 | +0.515 | 1.00 | 0.00 | 0.00 | 11.0 |

## Paired Deltas (`Biased` minus `Template`)

| Investigator | Score Delta | Accuracy Delta | Distraction Rate Delta | Action Share Delta |
| --- | ---: | ---: | ---: | ---: |
| `SolverPolicy` | +0.070 | +0.00 | +0.00 | +0.00 |
| `ObviousHeuristic` | +0.000 | +0.00 | +0.00 | +0.00 |
| `LLMPolicy(gemini:gemini-4-carbon)` | +0.195 | +0.00 | +0.00 | +0.00 |

## Per-Seed Breakdown

### Seed `2` (`Kestrel Labs`, rumor target `e10`, grudge pair `e06,e26`, manager `e09`)

- `solver` on `template`: score=`+0.580`, correct=`True`, accused=`e25`, day=`9`, steps=`71`, rumor_target_distraction=`0`
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e31`, day=`11`, steps=`25`, rumor_target_distraction=`0`
- `carbon` on `template`: score=`+0.460`, correct=`True`, accused=`e25`, day=`14`, llm_calls=`106`, rumor_target_distraction=`0`
- `solver` on `biased`: score=`+0.720`, correct=`True`, accused=`e25`, day=`5`, steps=`45`, rumor_target_distraction=`0`
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e31`, day=`11`, steps=`25`, rumor_target_distraction=`0`
- `carbon` on `biased`: score=`+0.530`, correct=`True`, accused=`e25`, day=`12`, llm_calls=`78`, rumor_target_distraction=`0`

### Seed `3` (`Nordlys Systems`, rumor target `e25`, grudge pair `e35,e22`, manager `e33`)

- `solver` on `template`: score=`+0.280`, correct=`True`, accused=`e29`, day=`18`, steps=`137`, rumor_target_distraction=`0`
- `obvious_heuristic` on `template`: score=`-1.000`, correct=`False`, accused=`e12`, day=`11`, steps=`25`, rumor_target_distraction=`0`
- `carbon` on `template`: score=`+0.180`, correct=`True`, accused=`e29`, day=`20`, llm_calls=`202`, rumor_target_distraction=`0`
- `solver` on `biased`: score=`+0.280`, correct=`True`, accused=`e29`, day=`18`, steps=`137`, rumor_target_distraction=`0`
- `obvious_heuristic` on `biased`: score=`-1.000`, correct=`False`, accused=`e12`, day=`11`, steps=`25`, rumor_target_distraction=`0`
- `carbon` on `biased`: score=`+0.500`, correct=`True`, accused=`e29`, day=`10`, llm_calls=`100`, rumor_target_distraction=`0`
