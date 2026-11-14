# Role 6 (multimodal_evidence) - Security-SOC Access & Framing Raster Vision Run

## Provenance
- Role: `multimodal_evidence` (`soc_access_vision_hard`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`hard`, seeds `[0, 1, 2]`)
- Commit: `933f518381c9435fdef6f76c40bf64c5b78f7e42`
- Timestamp: `2026-11-14T13:47:50+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_access_vision.py --tier hard --seeds 0,1,2 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/access-heatmap-hard-carbon`
- Images read by model (`Part.from_bytes`, `image/png`): `3`
- Token usage: `in=6453`, `out=1497`, `thinking=6248`, `cached=0`, `cost_usd=0.090356`, `latency_s=120.09`

## Aggregate Results
| Metric | Gemini SOC Vision (`gemini-4-carbon`) | Naive After-Hours Log Baseline |
|---|---|---|
| Top-1 Mole Accuracy | 3/3 (100.0%) | 0/3 (0.0%) |
| Top-3 Mole Hit Rate | 3/3 (100.0%) | - |
| Top-1 Framed Decoy Identified | 3/3 (100.0%) | - |
| Framed Decoy in Suspected Decoy List | 3/3 (100.0%) | - |
| Avoided Framing Decoy Trap | 3/3 (100.0%) | 0/3 (0.0%) |

## Rendered SOC Evidence Rasters
| Seed | Raster Path | Size | Bytes | SHA-256 |
|---|---|---|---|---|
| 0 | `rasters/hard_seed_0.png` | 2180x1660 | 286793 | `1a04d5c5097df2ff97d45d69f770ad01969b2d6a71096d42cb321e66c1a4704b` |
| 1 | `rasters/hard_seed_1.png` | 2180x1660 | 288623 | `9eccb991e57302879a00a5f5cc63750a91e4a780bb5751dc8ebc413ccae9d848` |
| 2 | `rasters/hard_seed_2.png` | 2180x1660 | 292748 | `6f1916210013247a5666dc9d70560e292ccd6023f02d97e85a34c02363b5b996` |

## Per-World Breakdown
| Seed | True Mole | True Decoy | Naive Log Pick | Pred Top Suspects | Pred Decoys | Mole Top-1 | Decoy Top-1 |
|---|---|---|---|---|---|---|---|
| 0 | `e38` | `e14` | `e14` | `e38, e39, e21` | `e14, e17, e27` | YES | YES |
| 1 | `e33` | `e11` | `e11` | `e33, e22` | `e11, e36, e21` | YES | YES |
| 2 | `e25` | `e31` | `e31` | `e25, e27, e26` | `e31, e05, e12` | YES | YES |

## Visual Reasoning Excerpts
- **Seed 0** (`rasters/hard_seed_0.png`, conf `1.00`): Panel B isolates e38, e39, and e21 as the sole H6/6 holders of all six surfaced canaries, with e38 achieving an exact 6/6 green variant match (~54,872x higher canary likelihood than runner-up e39 at 3/6). Panel A and Panel C corroborate e38 (SAL) as the true mole: e38 shows a characteristic ~27% after-hours rate (3/11) and strong regular-leak correlation (L1 D6/7 across six of seven leaked docs), whereas e39 (0/10 after-hours, L0 D0/7) and e21 (1/10 after-hours, L0 D1/7) lack corroborating activity. Conversely, Panel A's largest red after-hours spike belongs to e14 (15/33 after-hours), who held zero surfaced canaries in Panel B (0/6 H0/6) and is the primary framed decoy, alongside smaller scattered framing spikes on cleared staff like e17 (6/29, H0/6) and e27 (6/25, H1/6).
- **Seed 1** (`rasters/hard_seed_1.png`, conf `0.99`): In Panel A, e11 (RES) exhibits an extreme red after-hours spike of 14/34 logs/total, yet Panel B shows 0/5 H0/5 crossed-out canary tiles and Panel C shows L0 D0/4, identifying e11 as the primary framed decoy alongside secondary framing spikes on cleared staff like e36 (8/27, H1/5), e09 (6/25, H0/5), and e37 (6/29, H1/5). By contrast, e33 (LEG) is the sole employee matching ALL 5/5 surfaced canary variants in Panel B (~38x stronger canary odds than runner-up e22 at 4/5 H5/5), corroborated in Panel C by full department exposure and direct log access to surfaced regular leaks (L1 D4/4 for e33 in LEG versus L0 D1/4 for e22 in FIN) and an unframed 2/16 after-hours profile in Panel A.
- **Seed 2** (`rasters/hard_seed_2.png`, conf `0.98`): Panel A shows an extreme red after-hours spike on e31 (21/41 logs, 51% after-hours), but Panel B clears e31 completely (0/5 H2/5 with crossed-out non-held cells on c8, c11, and c13), exposing e31 as the primary framed decoy alongside minor scattered framing on e05 (9/25), e12 (7/27), e33 (7/28), and e13 (7/30). Among the five un-cleared H5/5 holders in Panel B, e25 stands alone at 4/5 variant matches (~38x odds advantage per match over the four 3/5 H5/5 runners-up, with only a single 5% noisy flip ~A on c4-2) and is strongly corroborated by mole-consistent Panel A after-hours activity (10/21, ~1.05 logs/day) and Panel C regular-leak correlation (L3 D6/6 with direct opens on d1-3, d6-1, and d5-1 plus full FIN department exposure).
