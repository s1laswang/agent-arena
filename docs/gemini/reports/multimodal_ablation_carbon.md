# Multimodal Evidence Statistical & Methodology Report (`gemini-4-carbon`)

Statistical, causal-ablation, and provenance audit for Role 6 (`roles_carbon/multimodal_evidence`), derived deterministically from `results/gemini/roles_carbon/multimodal_evidence/index.json` and its 17 verified `gemini-4-carbon` run directories (`stub=False`).

## 1. Scope, Hygiene, and Statistical Methodology

- **Non-judged dev-seed boundary (`non_judged_multimodal_research_and_arena_probes_dev_seeds_only`):** All `17` runs execute on public dev seeds (`0..14`; max observed seed `14`, `0` judge seeds `>= 900000`). Frozen judged Canary `v1.4` (`a8f99c2537c91d72`) and `v1.3` (`8df71cf570bb48bc`) text-tool benchmarks are never altered, and `docs/gemini/validation.md` remains untouched for human labeller Ivar.
- **Native pixel ingestion (`Part.from_bytes`):** Every visual artifact across all `17` runs (`260` `image/png` files, `27,268,097` bytes) was passed as raw PNG bytes via `google.genai.types.Part.from_bytes(mime_type="image/png")`. Compact SHA-256, pixel-dimension, and byte-size manifests are committed in each run's `meta.json` (`0` committed `.png` dumps, `0` `.world.json` answer-key files, `0` secret leaks).
- **Confidence interval estimators:** Continuous paired-episode scores report both normal-approximation 95% CIs (`mean +/- 1.96 * s / sqrt(n)` via `canary.analysis.gap.mean_ci`) and 2,000-draw percentile bootstrap 95% CIs (`seed=20261115`). Binomial proportions report Wilson score 95% CIs (`z=1.95996`). Both batch-pooled evaluations (`100` samples) and deduplicated unique world/episode slices (`86` unique samples: `27 + 17 + 22 + 20`) are reported explicitly.

## 2. Suite Totals (`results/gemini/roles_carbon/multimodal_evidence/index.json`)

| Suite Metric | Verified Value |
| --- | --- |
| Target Model | `gemini-4-carbon` (`verified=True`, `stub=False`) |
| Verified Run Folders | `17` (`17` scanned, `0` rejected) across `4` subfamilies |
| Evaluated Samples | `100` (`30` watermark-ablation episodes + `17` 3-PNG dossiers + `28` SOC heatmaps + `25` 4-panel charts; `86` deduplicated unique) |
| Native PNGs Read (`Part.from_bytes`) | `260` `image/png` inputs (`27,268,097` SHA-256 verified bytes) |
| Gemini API Calls | `226` |
| Tokens (Input / Output / Thinking / Cached) | `486,594` in / `47,941` out / `206,845` thinking / `0` cached |
| Pricing-Reconciled API Cost | `$3.521048` USD (`4,035.235` s total latency; `100%` reconciled via `canary.llm.pricing.cost`) |
| Hygiene & Seed Audit | dev seeds `0..14`, `0` judge seeds, `0` `.world.json` files, `0` secret leaks, latest run `2026-11-14T23:58:33+00:00` |

### Subfamily Allocation Summary

| Subfamily ID | Canonical Subrole(s) | Runs | Evaluated Samples (Unique) | PNGs Read | API Calls | Tokens (In / Out / Thinking) | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `watermark_memo_ablation` | `visual_memo_blind_ablation` | `6` | `30` (`27`) | `156` | `156` | `297,024 / 20,133 / 9,420` | `$0.889578` |
| `multi_image_incident_dossier` | `multi_image_incident_dossier` | `3` | `17` (`17`) | `51` | `17` | `76,652 / 6,876 / 66,726` | `$0.889324` |
| `soc_access_heatmap_vision` | `soc_access_vision`, `soc_access_vision_hard`, `soc_access_vision_v14_sweep` | `5` | `28` (`22`) | `28` | `28` | `58,425 / 13,301 / 115,434` | `$1.404200` |
| `visual_chart_forensics` | `belief_chart_forensics`, `carbon_v14_trajectory_forensics` | `3` | `25` (`20`) | `25` | `25` | `54,493 / 7,631 / 15,265` | `$0.337946` |
| **Total** | **All 4 Subfamilies** | **`17`** | **`100` (`86`)** | **`260`** | **`226`** | **`486,594 / 47,941 / 206,845`** | **`$3.521048`** |

## 3. Subfamily 1 (`visual_memo_blind_ablation` / `watermark_memo_ablation`): Causal Pixel-Only Watermark Ablation

**Methodology:** On each `v1.4` world seed, text `variant` copy-codes in `check_leak_feed` are redacted and rendered exclusively into `880x620` leaked-memo PNG scans (header stamp, micro-footer, and faint diagonal copy-code). An identical Bayesian investigator (`SolverPolicy`) runs three paired arms per seed: (1) `multimodal_carbon` reading each surfaced PNG via `Part.from_bytes`, (2) `blind_no_vision` with vision disabled, and (3) `text_oracle` receiving unredacted text copy-codes. Across `6` runs (`30` batch episodes, `156/156` = `100.0%` batch scan readout, `49/49` = `100.0%` planted canary readout; `medium` seeds `3, 4, 5` replicated identically across `scanned-evidence-ablation-carbon` and `memo-watermark-ablation-carbon`), deduplication yields `n=27` unique `(tier, seed)` paired episodes (`140` unique PNG scans, `45` planted canary scans).

- **Pooled unique (`n=27`, `140` PNG scans):** `gemini-4-carbon` scores `+0.6263 +/- 0.0724` vs `+0.1822 +/- 0.0978` blind, achieving a paired visual lift of `+0.4441 +/- 0.1219` (95% CI; bootstrap `[+0.3181, +0.5648]`), `140/140` (`100.0%`) watermark readout accuracy, and `100.0%` Bayesian `text_oracle` score recovery (`+0.6263` vs `+0.6263`).
- **Tier regime mechanics:** On `medium` (`n=12`, seeds `0..11`), leaked document metadata alone never pushes any suspect posterior above the `1/(1+V)` EV stopping threshold, leaving `blind_no_vision` at `+0.0000 +/- 0.0000` (`0/12` = `0.0%` accuracy) while pixel readout recovers `+0.7358 +/- 0.0754` (`12/12` = `100.0%`). On `hard` (`n=15`, seeds `0..14`), correlation with non-visual telemetry lets `blind_no_vision` reach `+0.3280 +/- 0.1374` (`10/15` = `66.67%`), while pixel watermark readout lifts mean score by `+0.2107 +/- 0.1118` to `+0.5387 +/- 0.0960` (`15/15` = `100.0%`).

| Tier Slice | Unique Episodes (`n`) | Seeds | Memo Scans Exact (Wilson 95% CI) | Canary Scans Exact | `multimodal_carbon` Mean +/- 95% CI (Bootstrap 95% CI) | `blind_no_vision` Mean +/- 95% CI (Bootstrap 95% CI) | Paired Lift +/- 95% CI (Bootstrap 95% CI) | Mole Acc: Vision vs Blind (Delta) | `text_oracle` Recovery |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| `medium` | `12` | `0..11` | `58/58` (`100.0%`, `[0.9379, 1.0000]`) | `20/20` (`100.0%`) | `+0.7358 +/- 0.0754` (`[+0.6567, +0.8008]`) | `+0.0000 +/- 0.0000` (`[+0.0000, +0.0000]`) | `+0.7358 +/- 0.0754` (`[+0.6567, +0.8008]`) | `100.0%` (`[0.7575, 1.0000]`) vs `0.0%` (`[0.0000, 0.2425]`) (`+100.0%`) | `100.0%` (`+0.7358`) |
| `hard` | `15` | `0..14` | `82/82` (`100.0%`, `[0.9552, 1.0000]`) | `25/25` (`100.0%`) | `+0.5387 +/- 0.0960` (`[+0.4433, +0.6240]`) | `+0.3280 +/- 0.1374` (`[+0.1860, +0.4553]`) | `+0.2107 +/- 0.1118` (`[+0.1067, +0.3247]`) | `100.0%` (`[0.7961, 1.0000]`) vs `66.67%` (`[0.4171, 0.8482]`) (`+33.33%`) | `100.0%` (`+0.5387`) |
| `overall` | `27` | `12 med + 15 hard` | `140/140` (`100.0%`, `[0.9733, 1.0000]`) | `45/45` (`100.0%`) | `+0.6263 +/- 0.0724` (`[+0.5493, +0.6952]`) | `+0.1822 +/- 0.0978` (`[+0.0889, +0.2874]`) | `+0.4441 +/- 0.1219` (`[+0.3181, +0.5648]`) | `100.0%` (`[0.8754, 1.0000]`) vs `37.04%` (`[0.2153, 0.5577]`) (`+62.96%`) | `100.0%` (`+0.6263`) |

| Batch Run ID | Tier | Seeds | Episodes | Scans Exact | Vision Mean | Blind Mean | Oracle Mean | Vision Acc | Blind Acc |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `scanned-evidence-ablation-carbon` | `medium` | `[0, 1, 2, 3, 4, 5]` | `6` | `37/37` | `+0.6683` | `+0.0000` | `+0.6683` | `100.0%` | `0.0%` |
| `memo-watermark-ablation-carbon` | `medium` | `[3, 4, 5]` | `3` | `16/16` | `+0.6933` | `+0.0000` | `+0.6933` | `100.0%` | `0.0%` |
| `memo-watermark-med-seeds6to11-carbon` | `medium` | `[6, 7, 8, 9, 10, 11]` | `6` | `21/21` | `+0.8033` | `+0.0000` | `+0.8033` | `100.0%` | `0.0%` |
| `memo-watermark-hard-ablation-carbon` | `hard` | `[0, 1, 2, 3, 4]` | `5` | `18/18` | `+0.6720` | `+0.4060` | `+0.6720` | `100.0%` | `80.0%` |
| `memo-watermark-hard-seeds5to9-carbon` | `hard` | `[5, 6, 7, 8, 9]` | `5` | `25/25` | `+0.5680` | `+0.3440` | `+0.5680` | `100.0%` | `60.0%` |
| `memo-watermark-hard-seeds10to14-carbon` | `hard` | `[10, 11, 12, 13, 14]` | `5` | `39/39` | `+0.3760` | `+0.2340` | `+0.3760` | `100.0%` | `60.0%` |

## 4. Subfamily 2 (`multi_image_incident_dossier`): 3-PNG Cross-Check & Framing-Trap Resistance

**Methodology:** Each `generate_content` call receives `3` distinct PNGs (`51` PNGs across `17` unique `v1.4` worlds: `medium` seeds `0..8` and `hard` seeds `0..7`; `17` API calls, `$0.889324` USD): Exhibit 1 (`badge_raster` with adversarial after-hours swipe spikes on a framed innocent decoy), Exhibit 2 (`leaked_memo_scans` with `DOC-ID` + `COPY-CODE` watermarks, no employee IDs), and Exhibit 3 (`org_canary_map` static floorplan + recipient copy-code matrix, no leak outcomes). No single exhibit identifies the mole (`0.0%` across Exhibit-1-only, Exhibit-2-only, and Exhibit-3-only baselines), and an Exhibit-1-only naive after-hours swipe pick accuses the framed decoy on `16/17` (`94.12%`) worlds.

| Tier Slice | Worlds (`n`) | PNGs (`3n`) | 3-PNG Mole Top-1 (Wilson 95% CI) | Mole Top-3 | Decoy Top-1 (Wilson 95% CI) | Decoy in List | Avoided Framing Trap | Exhibit 2 Scan OCR | Dept Attribution | Img-1-Only Mole Acc | Img-1-Only Decoy Trap Rate | Mole Lift vs Single-Image |
| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | --- | ---: |
| `medium` | `9` | `27` | `7/9` (`77.78%`, `[0.4526, 0.9368]`) | `8/9` (`88.89%`) | `8/9` (`88.89%`, `[0.5650, 0.9801]`) | `9/9` (`100.0%`) | `9/9` (`100.0%`) | `14/14` (`100.0%`) | `8/9` (`88.89%`) | `0.0%` | `8/9` (`88.89%`) | `+77.78%` (`+0.7778`) |
| `hard` | `8` | `24` | `7/8` (`87.50%`, `[0.5291, 0.9776]`) | `8/8` (`100.0%`) | `8/8` (`100.0%`, `[0.6756, 1.0000]`) | `8/8` (`100.0%`) | `8/8` (`100.0%`) | `29/29` (`100.0%`) | `7/8` (`87.50%`) | `0.0%` | `8/8` (`100.0%`) | `+87.50%` (`+0.8750`) |
| `overall` | `17` | `51` | `14/17` (`82.35%`, `[0.5897, 0.9381]`) | `16/17` (`94.12%`) | `16/17` (`94.12%`, `[0.7302, 0.9895]`) | `17/17` (`100.0%`) | `17/17` (`100.0%`) | `43/43` (`100.0%`) | `15/17` (`88.24%`) | `0.0%` | `16/17` (`94.12%`) | `+82.35%` (`+0.8235`) |

## 5. Subfamily 3 (`soc_access_vision` / `soc_access_heatmap_vision`): 28 SOC Heatmaps & Paired `low` vs `high` `thinking_level` Calibration

**Methodology:** Evaluates `28` decoy-framed SOC access & canary-correlation rasters (`1880x1020` on `medium`, `2180x1660` on `hard`) across `5` runs (`28` API calls, `115,434` thinking tokens, `$1.404200` USD), covering `22` unique `v1.4` worlds (`medium` seeds `0..9`, `hard` seeds `0..11`) plus a controlled within-world `thinking_level` sweep (`low` vs `high`) on `n=6` identical PNG rasters (`s8..11`: `medium:8, medium:9, hard:8, hard:9, hard:10, hard:11`).

| Evaluation Slice | Worlds (`n`) | Mole Top-1 (Wilson 95% CI) | Mole Top-3 | Decoy Top-1 (Wilson 95% CI) | Avoided Trap | Naive Log Mole Acc (Trapped Rate) | Mole Lift vs Naive | Mean Conf | Mean Brier |
| --- | ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `pooled_all_evaluations` | `28` | `27/28` (`96.43%`, `[0.8229, 0.9937]`) | `28/28` (`100.0%`) | `28/28` (`100.0%`, `[0.8794, 1.0000]`) | `28/28` (`100.0%`) | `0/28` (`0.0%`; `28/28` = `100.0%` trapped) | `+96.43%` (`+0.9643`) | `0.9696` | `0.014594` |
| `deduplicated_unique_worlds` | `22` | `21/22` (`95.45%`, `[0.7820, 0.9919]`) | `22/22` (`100.0%`) | `22/22` (`100.0%`, `[0.8513, 1.0000]`) | `22/22` (`100.0%`) | `0/22` (`0.0%`; `22/22` = `100.0%` trapped) | `+95.45%` (`+0.9545`) | `0.9682` | `0.017997` |
| `medium` (unique) | `10` | `9/10` (`90.00%`, `[0.5958, 0.9821]`) | `10/10` (`100.0%`) | `10/10` (`100.0%`, `[0.7225, 1.0000]`) | `10/10` (`100.0%`) | `0/10` (`0.0%`; `10/10` = `100.0%` trapped) | `+90.00%` (`+0.9000`) | `0.9470` | `0.038910` |
| `hard` (unique) | `12` | `12/12` (`100.0%`, `[0.7575, 1.0000]`) | `12/12` (`100.0%`) | `12/12` (`100.0%`, `[0.7575, 1.0000]`) | `12/12` (`100.0%`) | `0/12` (`0.0%`; `12/12` = `100.0%` trapped) | `+100.0%` (`+1.0000`) | `0.9858` | `0.000569` |

### Paired `low` vs `high` `thinking_level` Calibration (`s8..11`, Identical SHA-256 PNGs)

| Paired Slice | Worlds (`n`) | World List | `low` Mole / Decoy Acc | `high` Mole / Decoy Acc | `low` Think Tokens (Cost) | `high` Think Tokens (Cost) | `low` Mean Conf / Brier | `high` Mean Conf / Brier | Brier Delta (`high - low`) | Brier Ratio (`low / high`) |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |
| `all_paired_worlds` | `6` | `medium:8, medium:9, hard:8, hard:9, hard:10, hard:11` | `100.0% / 100.0%` | `100.0% / 100.0%` | `1,983` (`$0.076122`) | `85,629` (`$0.916102`) | `0.9747` / `0.002117` | `0.9873` / `0.000254` | `-0.001863` | `8.32x` |
| `hard_seeds_8to11` | `4` | `hard:8, hard:9, hard:10, hard:11` | `100.0% / 100.0%` | `100.0% / 100.0%` | `1,688` (`$0.057198`) | `60,977` (`$0.651798`) | `0.9670` / `0.003125` | `0.9860` / `0.000331` | `-0.002794` | `9.43x` |
| `medium_seeds_8to9` | `2` | `medium:8, medium:9` | `100.0% / 100.0%` | `100.0% / 100.0%` | `295` (`$0.018924`) | `24,652` (`$0.264304`) | `0.9900` / `0.000100` | `0.9900` / `0.000100` | `0.000000` | `1.00x` |

## 6. Subfamily 4 (`trajectory_forensics` / `visual_chart_forensics`): 25 4-Panel Posterior & Value-Bleed Charts (`v1.3` + `v1.4`)

**Methodology:** Renders committed investigator episodes into 4-panel PNG charts (`6` `v1.3` belief/bleed charts at `1984x1792` in `belief-chart-forensics-carbon` + `19` `v1.4` 4-panel posterior/bleed/entropy charts at `2208x2624` across `carbon-trajectory-forensics` (`7`) and `carbon-trajectory-forensics-v14-expanded` (`12`); `25` total charts, `20` deduplicated unique source episodes, `25` API calls, `$0.337946` USD) and scores `gemini-4-carbon` visual readouts directly against exact `SolverPolicy` replay ground truth.

| Chart Slice | Charts (`n`) | EV-Threshold Accuracy (Wilson 95% CI) | Exact Accuse/Stop-Day | Stop-Day Within +/-1 | Hidden-Bleed Gap | `v1.4` Entropy-Lag vs `SolverPolicy` | `v1.4` Outcome Pattern Match |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| `pooled_all_charts` (`6` `v1.3` + `19` `v1.4`) | `25` | `25/25` (`100.0%`, `[0.8668, 1.0000]`) | `25/25` (`100.0%`) | `25/25` (`100.0%`) | `25/25` (`100.0%`) | `19/19` (`100.0%`) | `19/19` (`100.0%`) |
| `deduplicated_unique_episodes` (`6` `v1.3` + `14` `v1.4`) | `20` | `20/20` (`100.0%`, `[0.8389, 1.0000]`) | `20/20` (`100.0%`) | `20/20` (`100.0%`) | `20/20` (`100.0%`) | `14/14` (`100.0%`) | `14/14` (`100.0%`) |

- **Failure cluster distribution (`pooled_all_charts`, `n=25`):** `none_justified_accusation=16`, `horizon_below_ev_stall=4`, `fooled_wrong_suspect=2`, `horizon_forced_guess=2`, `premature_early_accusation=1`.
- **Failure cluster distribution (`deduplicated_unique_episodes`, `n=20`):** `none_justified_accusation=14`, `horizon_below_ev_stall=2`, `horizon_forced_guess=2`, `fooled_wrong_suspect=1`, `premature_early_accusation=1`.

## 7. 17-Run Provenance & Pricing Ledger

| Run ID | Subfamily | Subrole | Rules | Thinking | Commit | PNGs | Calls | Tokens (In / Out / Thinking) | Cost (USD) |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `access-heatmap-carbon` | `soc_access_heatmap_vision` | `soc_access_vision` | `v1.4` | `default` | `62ea18bae54f` | `3` | `3` | `6,000 / 1,055 / 3,291` | `$0.055460` |
| `access-heatmap-hard-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_hard` | `v1.4` | `default` | `933f518381c9` | `3` | `3` | `6,453 / 1,497 / 6,248` | `$0.090356` |
| `access-heatmap-v14-high-s8to11-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `v1.4` | `high` | `c89f0fc1edbd` | `6` | `6` | `12,606 / 3,460 / 85,629` | `$0.916102` |
| `access-heatmap-v14-low-s8to11-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `v1.4` | `low` | `c89f0fc1edbd` | `6` | `6` | `12,606 / 3,108 / 1,983` | `$0.076122` |
| `access-heatmap-v14-sweep-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `v1.4` | `default` | `b40e5c8ddd30` | `10` | `10` | `20,760 / 4,181 / 18,283` | `$0.266160` |
| `belief-chart-forensics-carbon` | `visual_chart_forensics` | `belief_chart_forensics` | `v1.3` | `default` | `42341129d027` | `6` | `6` | `10,812 / 1,295 / 2,065` | `$0.055224` |
| `carbon-trajectory-forensics` | `visual_chart_forensics` | `carbon_v14_trajectory_forensics` | `v1.4` | `default` | `44b700f1b8d0` | `7` | `7` | `16,093 / 2,340 / 5,041` | `$0.105996` |
| `carbon-trajectory-forensics-v14-expanded` | `visual_chart_forensics` | `carbon_v14_trajectory_forensics` | `v1.4` | `default` | `c89f0fc1edbd` | `12` | `12` | `27,588 / 3,996 / 8,159` | `$0.176726` |
| `memo-watermark-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `default` | `8df685ee0579` | `16` | `16` | `30,464 / 2,085 / 1,367` | `$0.095448` |
| `memo-watermark-hard-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `low` | `c75a9393129a` | `18` | `18` | `34,272 / 2,391 / 0` | `$0.092454` |
| `memo-watermark-hard-seeds10to14-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `default` | `898dbbb4ae98` | `39` | `39` | `74,256 / 4,966 / 3,691` | `$0.235082` |
| `memo-watermark-hard-seeds5to9-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `default` | `726f9de02be0` | `25` | `25` | `47,600 / 3,214 / 2,243` | `$0.149770` |
| `memo-watermark-med-seeds6to11-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `default` | `85855affc476` | `21` | `21` | `39,984 / 2,665 / 2,119` | `$0.127808` |
| `multi-image-dossier-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `v1.4` | `default` | `5ee074194638` | `15` | `5` | `22,538 / 2,020 / 10,910` | `$0.174376` |
| `multi-image-dossier-med6to8-hard5to7-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `v1.4` | `default` | `a6b5a80e7a47` | `18` | `6` | `27,055 / 2,345 / 25,336` | `$0.330920` |
| `multi-image-dossier-v14-expanded-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `v1.4` | `default` | `1c51dca7ea61` | `18` | `6` | `27,059 / 2,511 / 30,480` | `$0.384028` |
| `scanned-evidence-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `v1.4` | `low` | `48baa20e7917` | `37` | `37` | `70,448 / 4,812 / 0` | `$0.189016` |
| **Total** | **4 Subfamilies** | **17 Verified Runs** | **`v1.3` + `v1.4`** | **`default` / `low` / `high`** | **-** | **`260`** | **`226`** | **`486,594 / 47,941 / 206,845`** | **`$3.521048`** |

## 8. Keyless Offline Verification

```bash
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.multimodal_carbon --check
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_multimodal_ablation_report.py
```
