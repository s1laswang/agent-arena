# Role 1 Consolidated Suite: World Text & Persona Synthesis (`gemini-4-carbon`)

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment
- Role: `world_text`
- Target Model ID: `gemini-4-carbon`
- Verified `world_text` run folders consolidated: `16`
- Total Gemini API calls: `1637`
- Total tokens (in / out / thinking / cached): `54,755,491` / `791,997` / `791,365` / `50,867,472`
- Total estimated cost (USD): `$22.728348`
- Non-leak & safety audit: `truth_leaks=0`, `prompt_leaks=0`, `lint_violations=0`, `stego_violations=0`, `fallbacks=0`, `secret_leaks=0` (`all_clean=True`)
- Provenance note: `worldtext-carbon-suite/` intentionally omits `meta.json` so `canary.gemini.worldtext_carbon` and role scanners do not double-count tokens or costs.

## 1. Company Personas & Workplace Chatter (`company_personas_suite`)

| Slice | Worlds | Personas | Solver Acc (95% CI) | Solver Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) |
| --- | ---: | ---: | --- | --- | --- | --- |
| `easy` | 4 | 48 | 100.0% [51.0%, 100.0%] | +0.8000 [+0.7550, +0.8500] | +0.8000 [+0.7550, +0.8500] | +0.0000 [+0.0000, +0.0000] |
| `medium` | 10 | 200 | 90.0% [59.6%, 98.2%] | +0.6660 [+0.4800, +0.7940] | +0.7300 [+0.6350, +0.8000] | -0.0640 [-0.1880, +0.0020] |
| `hard` | 10 | 400 | 100.0% [72.2%, 100.0%] | +0.6340 [+0.5350, +0.7030] | +0.6200 [+0.5210, +0.6910] | +0.0140 [+0.0000, +0.0420] |
| `overall` | 24 | 648 | 95.8% [79.8%, 99.3%] | +0.6750 [+0.5842, +0.7446] | +0.6958 [+0.6367, +0.7467] | -0.0208 [-0.0792, +0.0133] |

## 1b. 37-Encoding Non-Leak & Text-Only Probe Audit (`v14_multi_tier_parity_and_probe_audit`)

- Encodings scanned: `37` (`0` violations across `24` worlds, `648` personas, `2,791` messages, `5,184` interviews)

| Tier | Worlds (n) | Personas | Truth / Lint / Stego Hits | Text-Only Probe | Fair Bar | Probe p-val vs Bar | Leak Flag |
| --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `easy` | 4 | 48 | `0 / 0 / 0` | `0/4` (0.0%) | 17.0% | `1.0000` | `False` |
| `medium` | 10 | 200 | `0 / 0 / 0` | `1/10` (10.0%) | 7.4% | `0.5351` | `False` |
| `hard` | 10 | 400 | `0 / 0 / 0` | `0/10` (0.0%) | 3.5% | `1.0000` | `False` |

## 2. Bias-Flavoured Workplace Chatter & Investigator Ablation (`biased_chatter_suite`)

- Biased chatter corpus: `70` messages (`70` live LLM, `0` fallbacks) across `2` folders
- Paired ablation episodes: `36` across `3` folders

| Slice | Policy | Paired Seeds | Biased Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) | Biased Acc | Rumor Distraction |
| --- | --- | ---: | --- | --- | --- | ---: | ---: |
| `medium` | `carbon` | 2 | +0.7050 [+0.6500, +0.7600] | +0.6400 [+0.6000, +0.6800] | +0.0650 [+0.0500, +0.0800] | 100.0% | 100.0% |
| `medium` | `solver` | 2 | +0.7650 [+0.6900, +0.8400] | +0.7650 [+0.6900, +0.8400] | +0.0000 [+0.0000, +0.0000] | 100.0% | 0.0% |
| `medium` | `obvious_heuristic` | 2 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |
| `hard` | `carbon` | 4 | +0.5675 [+0.5150, +0.6275] | +0.4825 [+0.2700, +0.6775] | +0.0850 [-0.0975, +0.2575] | 100.0% | 50.0% |
| `hard` | `solver` | 4 | +0.5825 [+0.3825, +0.7050] | +0.5475 [+0.3700, +0.6650] | +0.0350 [+0.0000, +0.1050] | 100.0% | 0.0% |
| `hard` | `obvious_heuristic` | 4 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |
| `overall` | `carbon` | 6 | +0.6133 [+0.5450, +0.6900] | +0.5350 [+0.3700, +0.6650] | +0.0783 [-0.0433, +0.2000] | 100.0% | 66.7% |
| `overall` | `solver` | 6 | +0.6433 [+0.4817, +0.7567] | +0.6200 [+0.4667, +0.7400] | +0.0233 [+0.0000, +0.0700] | 100.0% | 0.0% |
| `overall` | `obvious_heuristic` | 6 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |

## 3. Persona-Conditioned Live Suspect Interviews (`persona_interviews_suite`)

- Worlds / Live interviews: `15` / `120` across `3` folders
- Signal calibration accuracy: `100.0%` [96.9%, 100.0%]
- Counterfactual prompt invariance: `100.0%` [98.9%, 100.0%] (`360` swap checks)
- Pooled SolverPolicy parity: `+0.6540` [+0.5513, +0.7400] vs template `+0.6440` [+0.5440, +0.7327] (delta `+0.0100` [+0.0000, +0.0287])

| Slice | Worlds | Persona Solver (95% CI) | Template Solver (95% CI) | Paired Delta (95% CI) | Solver Acc |
| --- | ---: | --- | --- | --- | ---: |
| `easy` | 4 | +0.8000 [+0.7550, +0.8500] | +0.8000 [+0.7550, +0.8500] | +0.0000 [+0.0000, +0.0000] | 100.0% |
| `medium` | 3 | +0.6467 [+0.3900, +0.8000] | +0.6433 [+0.3900, +0.8000] | +0.0033 [+0.0000, +0.0100] | 100.0% |
| `hard` | 8 | +0.5837 [+0.4363, +0.6987] | +0.5663 [+0.4300, +0.6787] | +0.0175 [+0.0000, +0.0525] | 100.0% |
| `overall` | 15 | +0.6540 [+0.5513, +0.7400] | +0.6440 [+0.5440, +0.7327] | +0.0100 [+0.0000, +0.0287] | 100.0% |

## 4. Dynamic Mid-Episode Corporate Incident Events (`dynamic_events_suite`)

| Slice | Worlds | Live-Events Solver (95% CI) | Baseline Solver (95% CI) | Paired Delta (95% CI) | Solver Acc | ObviousHeuristic |
| --- | ---: | --- | --- | --- | ---: | ---: |
| `medium` | 3 | +0.6933 [+0.6000, +0.7900] | +0.6933 [+0.6000, +0.7900] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |
| `hard` | 8 | +0.5988 [+0.4950, +0.6750] | +0.5988 [+0.4950, +0.6750] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |
| `overall` | 11 | +0.6245 [+0.5418, +0.6955] | +0.6245 [+0.5418, +0.6955] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |

## 5. Thinking-Level World Synthesis Calibration (`thinking_calibration_suite`)

| Thinking Level | Worlds | Thinking Tokens | Think Tok / World | Output Tokens | Distinct Bigrams | Solver Mean | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `low` | 2 | 0 | 0.0 | 4,668 | 1,178.0 | +0.7800 | $0.0627 |
| `medium` | 2 | 3,703 | 1,851.5 | 4,307 | 1,124.0 | +0.7800 | $0.0962 |
| `high` | 2 | 38,674 | 19,337.0 | 5,257 | 1,750.0 | +0.7800 | $0.4554 |

## 6. De-Duplicated Role 1 (`world_text`) Totals (`totals`)

| Subrole Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `biased_chatter` | 1 | 2 | 3,429 | 2,734 | 1,756 | 0 | $0.034198 |
| `biased_chatter_hard` | 1 | 12 | 32,161 | 13,478 | 7,609 | 0 | $0.199102 |
| `biased_chatter_investigator_ablation` | 3 | 1317 | 54,239,859 | 666,365 | 588,166 | 50,863,655 | $18.502424 |
| `company_personas_chatter` | 4 | 129 | 170,729 | 74,513 | 99,845 | 0 | $2.085038 |
| `dynamic_mid_episode_events` | 3 | 33 | 166,943 | 11,924 | 19,720 | 3,817 | $0.650326 |
| `persona_interviews` | 3 | 120 | 118,268 | 8,751 | 31,892 | 0 | $0.642966 |
| `thinking_level_calibration` | 1 | 24 | 24,102 | 14,232 | 42,377 | 0 | $0.614294 |
| **total** | **16** | **1637** | **54,755,491** | **791,997** | **791,365** | **50,867,472** | **$22.728348** |
