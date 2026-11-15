# Canary Lab Role 6: Multimodal Evidence (`gemini-4-carbon` Suite)

Consolidated provenance, SHA-256 PNG image-manifest verification, `canary.llm.pricing.cost` reconciliation, and per-subfamily visual forensics metrics across all committed `gemini-4-carbon` runs under `results/gemini/roles_carbon/multimodal_evidence/`.
Regenerate or verify deterministically without API keys via:
`PYTHONPATH=. python -m canary.gemini.multimodal_carbon --sync` and `PYTHONPATH=. python -m canary.gemini.multimodal_carbon --check`.

## Scope & Non-Judged Benchmark Disclosure

- **Research & arena multimodal probes (`non_judged_multimodal_research_and_arena_probes_dev_seeds_only`):** All 17 multimodal_evidence runs are non-judged research and arena probes on public dev seeds (seeds 0..14; 0 judge seeds >= 900000). Frozen judged Canary v1.4 (a8f99c2537c91d72) is a text-tool benchmark and is never altered by these visual scans, composite dossiers, or trajectory chart forensics runs.
- **Native pixel ingestion (`Part.from_bytes`):** Every image across all 17 runs was rendered to PNG and passed natively as raw `image/png` bytes via `google.genai.types.Part.from_bytes`. Compact SHA-256, dimension, and byte-length manifests are committed in each `meta.json` (`0` committed raw `.png` dumps, `0` `.world.json` answer-key files, `0` secret leaks).
- **Human validation sheet untouched:** `docs/gemini/validation.md` remains reserved exclusively for human labeller Ivar.

## Suite Totals (`gemini-4-carbon`, `stub=False`, Pricing & Hygiene Verified)

| Metric | Value |
| --- | --- |
| Verified `gemini-4-carbon` Runs | `17` across `4` multimodal sub-families (rejected: `0`) |
| Native `image/png` Inputs Read (`Part.from_bytes`) | `260` PNGs (`27,268,097` bytes SHA-256 verified) |
| Gemini API Calls | `226` |
| Input / Output / Thinking Tokens | `486,594` in / `47,941` out / `206,845` thinking (`0` cached) |
| Recorded & Pricing-Reconciled Cost | `$3.521048` USD (`$3.52`) |
| Seed & Secret Hygiene | dev seeds `0..14`, `0` judge seeds (`>= 900000`), `0` `.world.json` files, `0` secret leaks |
| Latest Committed Run Timestamp | `2026-11-14T23:58:33+00:00` |

## 4 Multimodal Sub-Families Summary

| Sub-Family | Runs | PNGs Read | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Multimodal Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **Watermarked Leak-Memo & Scanned-Document Vision Ablations** (`watermark_memo_ablation`) | `6` | `156` | `156` | 297,024 / 20,133 / 9,420 | `$0.889578` | OCR/watermark `140/140` (`100.0%`) across `27` unique paired episodes (`medium` 0..11 + `hard` 0..14); vision mean `+0.6263` (`100.0%` acc) vs blind `+0.1822` (`37.0%` acc), delta `+0.4441`, `100.0%` text-oracle recovery |
| **SOC Access-Heatmap Vision & Thinking-Level Calibration** (`soc_access_heatmap_vision`) | `5` | `28` | `28` | 58,425 / 13,301 / 115,434 | `$1.404200` | Top-1 mole `27/28` (`96.4%`; `21/22` = `95.5%` unique) vs naive after-hours `0/28` (`0.0%`); Top-1 decoy `28/28` (`100.0%`); paired `high` vs `low` cuts Brier `0.0021` -> `0.0003` |
| **3-Image Composite Incident Dossier Fusion** (`multi_image_incident_dossier`) | `3` | `51` | `17` | 76,652 / 6,876 / 66,726 | `$0.889324` | Joint 3-PNG fusion (`badge_raster` + `leaked_memo_scans` + `org_canary_map`) achieves `14/17` (`82.4%`) Top-1 mole (Top-3 `16/17` = `94.1%`) vs `0/17` (`0.0%`) single-image baselines; decoy Top-1 `16/17` (`94.1%`), scan OCR `43/43` (`100.0%`) |
| **4-Panel Trajectory & Belief-Chart Visual Forensics** (`visual_chart_forensics`) | `3` | `25` | `25` | 54,493 / 7,631 / 15,265 | `$0.337946` | `25/25` (`100.0%`) EV-threshold, exact stop-day, and hidden-bleed readout (`19/19` = `100.0%` v1.4 entropy-lag & pattern match across `20` unique source episodes); clusters: `fooled_wrong_suspect`=2, `horizon_below_ev_stall`=4, `horizon_forced_guess`=2, `none_justified_accusation`=16, `premature_early_accusation`=1 |
| **Total** | **`17`** | **`260`** | **`226`** | **`486,594 / 47,941 / 206,845`** | **`$3.521048`** | All 17 runs verified (`stub=False`) |

## Sub-Family Metric Breakdowns

### 1. Watermarked Leak-Memo & Scanned-Document Vision Ablations (`n=27` Unique Paired Episodes)

| Tier Slice | Unique Episodes (Seeds) | Memo Scans Exact | Canary Scans Exact | Vision Mean (95% CI) | Blind Mean (95% CI) | Paired Score Delta (95% CI) | Vision Acc vs Blind Acc | Oracle Recovery |
| --- | --- | ---: | ---: | --- | --- | --- | --- | ---: |
| `medium` | `12` (`0..11`) | `58/58` (`100.0%`) | `20/20` (`100.0%`) | `+0.7358` [+0.6567, +0.8008] | `+0.0000` [+0.0000, +0.0000] | `+0.7358` [+0.6567, +0.8008] | `100.0%` vs `0.0%` | `100.0%` |
| `hard` | `15` (`0..14`) | `82/82` (`100.0%`) | `25/25` (`100.0%`) | `+0.5387` [+0.4433, +0.6240] | `+0.3280` [+0.1860, +0.4553] | `+0.2107` [+0.1067, +0.3247] | `100.0%` vs `66.7%` | `100.0%` |
| `overall` | `27` (`12 med + 15 hard`) | `140/140` (`100.0%`) | `45/45` (`100.0%`) | `+0.6263` [+0.5493, +0.6952] | `+0.1822` [+0.0889, +0.2874] | `+0.4441` [+0.3181, +0.5648] | `100.0%` vs `37.0%` | `100.0%` |

### 2. SOC Access-Heatmap Vision & Paired `low` vs `high` Thinking Calibration

- **Pooled evaluations (`n=28` across 5 runs; `22` unique worlds `medium 0..9` + `hard 0..11`):** Top-1 mole `27/28` (`96.4%`, Top-3 `28/28` = `100.0%`), Top-1 framed decoy `28/28` (`100.0%`), avoided framing trap `100.0%`, versus naive after-hours log baseline `0/28` (`0.0%` mole, `100.0%` trapped by framed decoy).

| Paired Slice | Worlds (n) | `low` Mole / Decoy Acc | `high` Mole / Decoy Acc | `low` Mean Brier | `high` Mean Brier | `low` Think Tok (Cost) | `high` Think Tok (Cost) |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `all_paired_worlds` | `6` | `100% / 100%` | `100% / 100%` | `0.002117` | `0.000254` | `1,983` (`$0.0761`) | `85,629` (`$0.9161`) |
| `hard_seeds_8to11` | `4` | `100% / 100%` | `100% / 100%` | `0.003125` | `0.000331` | `1,688` (`$0.0572`) | `60,977` (`$0.6518`) |
| `medium_seeds_8to9` | `2` | `100% / 100%` | `100% / 100%` | `0.000100` | `0.000100` | `295` (`$0.0189`) | `24,652` (`$0.2643`) |

### 3. 3-Image Composite Incident Dossier Fusion (`n=17` Unique Worlds, `51` PNGs)

| Tier Slice | Worlds (n) | 3-Image Mole Top-1 (95% CI) | Mole Top-3 | Decoy Top-1 | Avoided Trap | Exhibit 2 Scan OCR | Dept Attribution | Single-Image Baselines (Ex1 / Ex2 / Ex3) |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `medium` | `9` | `7/9` (`77.8%` [45.3%, 93.7%]) | `8/9` (`88.9%`) | `8/9` (`88.9%`) | `9/9` (`100.0%`) | `14/14` (`100.0%`) | `8/9` (`88.9%`) | `0.0% / 0.0% / 0.0%` |
| `hard` | `8` | `7/8` (`87.5%` [52.9%, 97.8%]) | `8/8` (`100.0%`) | `8/8` (`100.0%`) | `8/8` (`100.0%`) | `29/29` (`100.0%`) | `7/8` (`87.5%`) | `0.0% / 0.0% / 0.0%` |
| `overall` | `17` | `14/17` (`82.4%` [59.0%, 93.8%]) | `16/17` (`94.1%`) | `16/17` (`94.1%`) | `17/17` (`100.0%`) | `43/43` (`100.0%`) | `15/17` (`88.2%`) | `0.0% / 0.0% / 0.0%` |

### 4. 4-Panel Trajectory & Belief-Chart Visual Forensics (`25` Charts, `20` Unique Episodes)

- **Pooled chart evaluations (`n=25`):** EV break-even threshold `25/25` (`100.0%`), exact stop-day `25/25` (`100.0%`), hidden bleed gap `25/25` (`100.0%`), v1.4 Shannon entropy-lag vs `SolverPolicy` `19/19` (`100.0%`), v1.4 outcome pattern `19/19` (`100.0%`).
- **Diagnosed clusters (all `25` charts):** `fooled_wrong_suspect=2`, `horizon_below_ev_stall=4`, `horizon_forced_guess=2`, `none_justified_accusation=16`, `premature_early_accusation=1`.
- **De-duplicated unique source episodes (`n=20`):** `fooled_wrong_suspect=1`, `horizon_below_ev_stall=2`, `horizon_forced_guess=2`, `none_justified_accusation=14`, `premature_early_accusation=1`.

## 17-Run Provenance Ledger (`results/gemini/roles_carbon/multimodal_evidence/`)

| Run ID | Sub-Family | Subrole | Thinking | Commit | PNGs | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Finding |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `access-heatmap-carbon` | `soc_access_heatmap_vision` | `soc_access_vision` | `default` | `62ea18bae54f` | 3 | 3 | 6,000 / 1,055 / 3,291 | `$0.055460` | mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0013 |
| `access-heatmap-hard-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_hard` | `default` | `933f518381c9` | 3 | 3 | 6,453 / 1,497 / 6,248 | `$0.090356` | mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0002 |
| `access-heatmap-v14-high-s8to11-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `high` | `c89f0fc1edbd` | 6 | 6 | 12,606 / 3,460 / 85,629 | `$0.916102` | mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0003 |
| `access-heatmap-v14-low-s8to11-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `low` | `c89f0fc1edbd` | 6 | 6 | 12,606 / 3,108 / 1,983 | `$0.076122` | mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0021 |
| `access-heatmap-v14-sweep-carbon` | `soc_access_heatmap_vision` | `soc_access_vision_v14_sweep` | `default` | `b40e5c8ddd30` | 10 | 10 | 20,760 / 4,181 / 18,283 | `$0.266160` | mole top-1 90.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0390 |
| `belief-chart-forensics-carbon` | `visual_chart_forensics` | `belief_chart_forensics` | `default` | `42341129d027` | 6 | 6 | 10,812 / 1,295 / 2,065 | `$0.055224` | EV-threshold 100%, exact stop-day 100%, bleed-gap 100% (horizon_forced_guess=2, none_justified_accusation=3, premature_early_accusation=1) |
| `carbon-trajectory-forensics` | `visual_chart_forensics` | `carbon_v14_trajectory_forensics` | `default` | `44b700f1b8d0` | 7 | 7 | 16,093 / 2,340 / 5,041 | `$0.105996` | EV-threshold 100%, exact stop-day 100%, bleed-gap 100%, entropy-lag 100% (fooled_wrong_suspect=1, horizon_below_ev_stall=2, none_justified_accusation=4) |
| `carbon-trajectory-forensics-v14-expanded` | `visual_chart_forensics` | `carbon_v14_trajectory_forensics` | `default` | `c89f0fc1edbd` | 12 | 12 | 27,588 / 3,996 / 8,159 | `$0.176726` | EV-threshold 100%, exact stop-day 100%, bleed-gap 100%, entropy-lag 100% (fooled_wrong_suspect=1, horizon_below_ev_stall=2, none_justified_accusation=9) |
| `memo-watermark-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `default` | `8df685ee0579` | 16 | 16 | 30,464 / 2,085 / 1,367 | `$0.095448` | OCR/watermark 100.0% (16/16), vision +0.6933 (100% acc) vs blind +0.0000 (0% acc), delta +0.6933 |
| `memo-watermark-hard-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `low` | `c75a9393129a` | 18 | 18 | 34,272 / 2,391 / 0 | `$0.092454` | OCR/watermark 100.0% (18/18), vision +0.6720 (100% acc) vs blind +0.4060 (80% acc), delta +0.2660 |
| `memo-watermark-hard-seeds10to14-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `default` | `898dbbb4ae98` | 39 | 39 | 74,256 / 4,966 / 3,691 | `$0.235082` | OCR/watermark 100.0% (39/39), vision +0.3760 (100% acc) vs blind +0.2340 (60% acc), delta +0.1420 |
| `memo-watermark-hard-seeds5to9-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `default` | `726f9de02be0` | 25 | 25 | 47,600 / 3,214 / 2,243 | `$0.149770` | OCR/watermark 100.0% (25/25), vision +0.5680 (100% acc) vs blind +0.3440 (60% acc), delta +0.2240 |
| `memo-watermark-med-seeds6to11-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `default` | `85855affc476` | 21 | 21 | 39,984 / 2,665 / 2,119 | `$0.127808` | OCR/watermark 100.0% (21/21), vision +0.8033 (100% acc) vs blind +0.0000 (0% acc), delta +0.8033 |
| `multi-image-dossier-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `default` | `5ee074194638` | 15 | 5 | 22,538 / 2,020 / 10,910 | `$0.174376` | 3-image mole top-1 5/5 (100.0%) vs single-image 0/5, decoy top-1 5/5, memo OCR 15/15 (100%) |
| `multi-image-dossier-med6to8-hard5to7-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `default` | `a6b5a80e7a47` | 18 | 6 | 27,055 / 2,345 / 25,336 | `$0.330920` | 3-image mole top-1 4/6 (66.7%) vs single-image 0/6, decoy top-1 5/6, memo OCR 12/12 (100%) |
| `multi-image-dossier-v14-expanded-carbon` | `multi_image_incident_dossier` | `multi_image_incident_dossier` | `default` | `1c51dca7ea61` | 18 | 6 | 27,059 / 2,511 / 30,480 | `$0.384028` | 3-image mole top-1 5/6 (83.3%) vs single-image 0/6, decoy top-1 6/6, memo OCR 16/16 (100%) |
| `scanned-evidence-ablation-carbon` | `watermark_memo_ablation` | `visual_memo_blind_ablation` | `low` | `48baa20e7917` | 37 | 37 | 70,448 / 4,812 / 0 | `$0.189016` | OCR/watermark 100.0% (37/37), vision +0.6683 (100% acc) vs blind +0.0000 (0% acc), delta +0.6683 |

## Per-Run Provenance & Multimodal Verification Details

### 1. `access-heatmap-carbon` (`soc_access_vision`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/access-heatmap-carbon` (`subfamily=soc_access_heatmap_vision`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `62ea18bae54f2e525e942df7c08bff9247e3bb1d` (`2026-11-14T13:23:46+00:00`)
- **Scope & dev seeds:** medium seeds [0, 1, 2] (3 rasters) (seeds: `[0, 1, 2]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `3` `image/png` files, `458,027` bytes, dimensions `1880x1020`
- **Gemini API usage:** `calls=3`, `in=6,000`, `out=1,055`, `thinking=3,291`, `cached=0`, `cost_usd=$0.055460` (pricing expected `$0.055460`)
- **Key metric:** mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0013
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 2. `access-heatmap-hard-carbon` (`soc_access_vision_hard`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/access-heatmap-hard-carbon` (`subfamily=soc_access_heatmap_vision`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `933f518381c9435fdef6f76c40bf64c5b78f7e42` (`2026-11-14T13:47:50+00:00`)
- **Scope & dev seeds:** hard seeds [0, 1, 2] (3 rasters) (seeds: `[0, 1, 2]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `3` `image/png` files, `868,164` bytes, dimensions `2180x1660`
- **Gemini API usage:** `calls=3`, `in=6,453`, `out=1,497`, `thinking=6,248`, `cached=0`, `cost_usd=$0.090356` (pricing expected `$0.090356`)
- **Key metric:** mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0002
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 3. `access-heatmap-v14-high-s8to11-carbon` (`soc_access_vision_v14_sweep`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-high-s8to11-carbon` (`subfamily=soc_access_heatmap_vision`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=high`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `c89f0fc1edbd01af0fef76a42231feab5b2f165f` (`2026-11-14T23:14:27+00:00`)
- **Scope & dev seeds:** 6 rasters (medium:[8, 9], hard:[8, 9, 10, 11]) (seeds: `[8, 9, 10, 11]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `6` `image/png` files, `1,463,377` bytes, dimensions `1880x1020`, `2180x1660`
- **Gemini API usage:** `calls=6`, `in=12,606`, `out=3,460`, `thinking=85,629`, `cached=0`, `cost_usd=$0.916102` (pricing expected `$0.916102`)
- **Key metric:** mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0003
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 4. `access-heatmap-v14-low-s8to11-carbon` (`soc_access_vision_v14_sweep`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-low-s8to11-carbon` (`subfamily=soc_access_heatmap_vision`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=low`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `c89f0fc1edbd01af0fef76a42231feab5b2f165f` (`2026-11-14T23:02:38+00:00`)
- **Scope & dev seeds:** 6 rasters (medium:[8, 9], hard:[8, 9, 10, 11]) (seeds: `[8, 9, 10, 11]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `6` `image/png` files, `1,463,377` bytes, dimensions `1880x1020`, `2180x1660`
- **Gemini API usage:** `calls=6`, `in=12,606`, `out=3,108`, `thinking=1,983`, `cached=0`, `cost_usd=$0.076122` (pricing expected `$0.076122`)
- **Key metric:** mole top-1 100.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0021
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 5. `access-heatmap-v14-sweep-carbon` (`soc_access_vision_v14_sweep`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-sweep-carbon` (`subfamily=soc_access_heatmap_vision`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `b40e5c8ddd303039e7fb605ec50b4005a174a064` (`2026-11-14T17:10:38+00:00`)
- **Scope & dev seeds:** 10 rasters (medium:[3, 4, 5, 6, 7], hard:[3, 4, 5, 6, 7]) (seeds: `[3, 4, 5, 6, 7]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `10` `image/png` files, `2,227,743` bytes, dimensions `1880x1020`, `2180x1660`
- **Gemini API usage:** `calls=10`, `in=20,760`, `out=4,181`, `thinking=18,283`, `cached=0`, `cost_usd=$0.266160` (pricing expected `$0.266160`)
- **Key metric:** mole top-1 90.0% vs naive 0.0%, decoy top-1 100.0%, Brier 0.0390
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 6. `belief-chart-forensics-carbon` (`belief_chart_forensics`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/belief-chart-forensics-carbon` (`subfamily=visual_chart_forensics`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.3`, `stub=False`)
- **Commit & timestamp:** `42341129d027e54e5bf58e44f3e64690295b75c5` (`2026-11-14T13:22:00+00:00`)
- **Scope & dev seeds:** 6 v1.3 belief/trajectory charts (seeds: `[0, 1, 2, 4, 5]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `6` `image/png` files, `1,448,245` bytes, dimensions `1984x1792`
- **Gemini API usage:** `calls=6`, `in=10,812`, `out=1,295`, `thinking=2,065`, `cached=0`, `cost_usd=$0.055224` (pricing expected `$0.055224`)
- **Key metric:** EV-threshold 100%, exact stop-day 100%, bleed-gap 100% (horizon_forced_guess=2, none_justified_accusation=3, premature_early_accusation=1)
- **Committed files:** `diagnoses.json`, `meta.json`, `summary.md`

### 7. `carbon-trajectory-forensics` (`carbon_v14_trajectory_forensics`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/carbon-trajectory-forensics` (`subfamily=visual_chart_forensics`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `44b700f1b8d03f46eb90bc99142f4ffc221563cf` (`2026-11-14T17:49:49+00:00`)
- **Scope & dev seeds:** 7 v1.4 belief/trajectory charts (seeds: `[1, 5, 6, 7, 8]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `7` `image/png` files, `2,833,495` bytes, dimensions `2208x2624`
- **Gemini API usage:** `calls=7`, `in=16,093`, `out=2,340`, `thinking=5,041`, `cached=0`, `cost_usd=$0.105996` (pricing expected `$0.105996`)
- **Key metric:** EV-threshold 100%, exact stop-day 100%, bleed-gap 100%, entropy-lag 100% (fooled_wrong_suspect=1, horizon_below_ev_stall=2, none_justified_accusation=4)
- **Committed files:** `diagnoses.json`, `meta.json`, `summary.md`

### 8. `carbon-trajectory-forensics-v14-expanded` (`carbon_v14_trajectory_forensics`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/carbon-trajectory-forensics-v14-expanded` (`subfamily=visual_chart_forensics`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `c89f0fc1edbd01af0fef76a42231feab5b2f165f` (`2026-11-14T23:06:40+00:00`)
- **Scope & dev seeds:** 12 v1.4 belief/trajectory charts (seeds: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 11]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `12` `image/png` files, `4,714,769` bytes, dimensions `2208x2624`
- **Gemini API usage:** `calls=12`, `in=27,588`, `out=3,996`, `thinking=8,159`, `cached=0`, `cost_usd=$0.176726` (pricing expected `$0.176726`)
- **Key metric:** EV-threshold 100%, exact stop-day 100%, bleed-gap 100%, entropy-lag 100% (fooled_wrong_suspect=1, horizon_below_ev_stall=2, none_justified_accusation=9)
- **Committed files:** `diagnoses.json`, `meta.json`, `summary.md`

### 9. `memo-watermark-ablation-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/memo-watermark-ablation-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `8df685ee057904bac413d35304f389066aa2b78f` (`2026-11-14T13:50:01+00:00`)
- **Scope & dev seeds:** medium seeds [3, 4, 5] (3 paired episodes, 16 scans) (seeds: `[3, 4, 5]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `16` `image/png` files, `500,909` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=16`, `in=30,464`, `out=2,085`, `thinking=1,367`, `cached=0`, `cost_usd=$0.095448` (pricing expected `$0.095448`)
- **Key metric:** OCR/watermark 100.0% (16/16), vision +0.6933 (100% acc) vs blind +0.0000 (0% acc), delta +0.6933
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`

### 10. `memo-watermark-hard-ablation-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-ablation-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=low`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `c75a9393129a5ed65cc2b9bdba44972d99e1c61a` (`2026-11-14T17:05:44+00:00`)
- **Scope & dev seeds:** hard seeds [0, 1, 2, 3, 4] (5 paired episodes, 18 scans) (seeds: `[0, 1, 2, 3, 4]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `18` `image/png` files, `564,626` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=18`, `in=34,272`, `out=2,391`, `thinking=0`, `cached=0`, `cost_usd=$0.092454` (pricing expected `$0.092454`)
- **Key metric:** OCR/watermark 100.0% (18/18), vision +0.6720 (100% acc) vs blind +0.4060 (80% acc), delta +0.2660
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`

### 11. `memo-watermark-hard-seeds10to14-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-seeds10to14-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `898dbbb4ae98f0dbf742f8e91a2557cb614a5877` (`2026-11-14T23:45:43+00:00`)
- **Scope & dev seeds:** hard seeds [10, 11, 12, 13, 14] (5 paired episodes, 39 scans) (seeds: `[10, 11, 12, 13, 14]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `39` `image/png` files, `1,225,250` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=39`, `in=74,256`, `out=4,966`, `thinking=3,691`, `cached=0`, `cost_usd=$0.235082` (pricing expected `$0.235082`)
- **Key metric:** OCR/watermark 100.0% (39/39), vision +0.3760 (100% acc) vs blind +0.2340 (60% acc), delta +0.1420
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`

### 12. `memo-watermark-hard-seeds5to9-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-seeds5to9-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `726f9de02be0fe1ce8493640796d3f0cb9941e5d` (`2026-11-14T22:55:26+00:00`)
- **Scope & dev seeds:** hard seeds [5, 6, 7, 8, 9] (5 paired episodes, 25 scans) (seeds: `[5, 6, 7, 8, 9]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `25` `image/png` files, `784,209` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=25`, `in=47,600`, `out=3,214`, `thinking=2,243`, `cached=0`, `cost_usd=$0.149770` (pricing expected `$0.149770`)
- **Key metric:** OCR/watermark 100.0% (25/25), vision +0.5680 (100% acc) vs blind +0.3440 (60% acc), delta +0.2240
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`

### 13. `memo-watermark-med-seeds6to11-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/memo-watermark-med-seeds6to11-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `85855affc476ed1f54e4197b4a38a8f7e08bdeff` (`2026-11-14T23:07:45+00:00`)
- **Scope & dev seeds:** medium seeds [6, 7, 8, 9, 10, 11] (6 paired episodes, 21 scans) (seeds: `[6, 7, 8, 9, 10, 11]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `21` `image/png` files, `657,481` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=21`, `in=39,984`, `out=2,665`, `thinking=2,119`, `cached=0`, `cost_usd=$0.127808` (pricing expected `$0.127808`)
- **Key metric:** OCR/watermark 100.0% (21/21), vision +0.8033 (100% acc) vs blind +0.0000 (0% acc), delta +0.8033
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`

### 14. `multi-image-dossier-carbon` (`multi_image_incident_dossier`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/multi-image-dossier-carbon` (`subfamily=multi_image_incident_dossier`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `5ee0741946388cfaea3c8d287aaf0c7586a7509c` (`2026-11-14T17:22:19+00:00`)
- **Scope & dev seeds:** 5 3-image dossiers (15 PNGs: medium_0, medium_1, medium_2, hard_0, hard_1) (seeds: `[0, 1, 2]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `15` `image/png` files, `1,995,561` bytes, dimensions `1274x996`, `1320x1232`, `1510x644`, `1510x1126`, `1530x1636`, `2144x1934`, `2144x1962`, `2252x1126`
- **Gemini API usage:** `calls=5`, `in=22,538`, `out=2,020`, `thinking=10,910`, `cached=0`, `cost_usd=$0.174376` (pricing expected `$0.174376`)
- **Key metric:** 3-image mole top-1 5/5 (100.0%) vs single-image 0/5, decoy top-1 5/5, memo OCR 15/15 (100%)
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 15. `multi-image-dossier-med6to8-hard5to7-carbon` (`multi_image_incident_dossier`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/multi-image-dossier-med6to8-hard5to7-carbon` (`subfamily=multi_image_incident_dossier`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `a6b5a80e7a47d2bdf91514c57ca08834921762eb` (`2026-11-14T23:58:33+00:00`)
- **Scope & dev seeds:** 6 3-image dossiers (18 PNGs: medium_6, medium_7, medium_8, hard_5, hard_6, hard_7) (seeds: `[5, 6, 7, 8]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `18` `image/png` files, `2,411,361` bytes, dimensions `1274x996`, `1320x1204`, `1320x1232`, `1510x644`, `1510x1126`, `1530x1636`, `2144x1962`, `2144x1990`
- **Gemini API usage:** `calls=6`, `in=27,055`, `out=2,345`, `thinking=25,336`, `cached=0`, `cost_usd=$0.330920` (pricing expected `$0.330920`)
- **Key metric:** 3-image mole top-1 4/6 (66.7%) vs single-image 0/6, decoy top-1 5/6, memo OCR 12/12 (100%)
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 16. `multi-image-dossier-v14-expanded-carbon` (`multi_image_incident_dossier`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/multi-image-dossier-v14-expanded-carbon` (`subfamily=multi_image_incident_dossier`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `1c51dca7ea613e96cc60623613a3b1e25057fee7` (`2026-11-14T23:05:23+00:00`)
- **Scope & dev seeds:** 6 3-image dossiers (18 PNGs: medium_3, medium_4, medium_5, hard_2, hard_3, hard_4) (seeds: `[2, 3, 4, 5]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `18` `image/png` files, `2,496,095` bytes, dimensions `1274x996`, `1320x1204`, `1320x1232`, `1510x644`, `1510x1126`, `1530x1636`, `2144x1934`, `2144x1962`, `2252x1126`
- **Gemini API usage:** `calls=6`, `in=27,059`, `out=2,511`, `thinking=30,480`, `cached=0`, `cost_usd=$0.384028` (pricing expected `$0.384028`)
- **Key metric:** 3-image mole top-1 5/6 (83.3%) vs single-image 0/6, decoy top-1 6/6, memo OCR 16/16 (100%)
- **Committed files:** `meta.json`, `results.json`, `summary.md`

### 17. `scanned-evidence-ablation-carbon` (`visual_memo_blind_ablation`)
- **Artifact directory:** `results/gemini/roles_carbon/multimodal_evidence/scanned-evidence-ablation-carbon` (`subfamily=watermark_memo_ablation`)
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=low`, `tiers_version=v1.4`, `stub=False`)
- **Commit & timestamp:** `48baa20e791717f9a33d032efb7f06fda68d636a` (`2026-11-14T17:06:23+00:00`)
- **Scope & dev seeds:** medium seeds [0, 1, 2, 3, 4, 5] (6 paired episodes, 37 scans) (seeds: `[0, 1, 2, 3, 4, 5]`)
- **Verified PNG manifest (`Part.from_bytes=True`):** `37` `image/png` files, `1,155,408` bytes, dimensions `880x620`
- **Gemini API usage:** `calls=37`, `in=70,448`, `out=4,812`, `thinking=0`, `cached=0`, `cost_usd=$0.189016` (pricing expected `$0.189016`)
- **Key metric:** OCR/watermark 100.0% (37/37), vision +0.6683 (100% acc) vs blind +0.0000 (0% acc), delta +0.6683
- **Committed files:** `comparison.json`, `meta.json`, `summary.md`, `vision_calls.jsonl`
