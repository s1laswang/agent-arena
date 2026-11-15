# Role 6 (multimodal_evidence) - Security-SOC Access & Framing Raster Vision Run

## Provenance
- Role: `multimodal_evidence` (`soc_access_vision`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`medium`, seeds `[0, 1, 2]`)
- Commit: `62ea18bae54f2e525e942df7c08bff9247e3bb1d`
- Timestamp: `2026-11-14T13:23:46+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_access_vision.py --tier medium --seeds 0,1,2 --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/access-heatmap-carbon`
- Images read by model (`Part.from_bytes`, `image/png`): `3`
- Token usage: `in=6000`, `out=1055`, `thinking=3291`, `cached=0`, `cost_usd=0.055460`, `latency_s=72.27`

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
| 0 | `rasters/medium_seed_0.png` | 1880x1020 | 153744 | `353e9b66a13d46deab1c2305c33956140e71fce6a1db774aa658ecad27d2e5d7` |
| 1 | `rasters/medium_seed_1.png` | 1880x1020 | 155973 | `1a09eb4de72f8893e5b434c2eb727c20cbca449ba68b8445220c559b976f0b6f` |
| 2 | `rasters/medium_seed_2.png` | 1880x1020 | 148310 | `ae99a74f781a64adcaa03c439c1c140cfecf2cd0c2136c212027c05f126f9b91` |

## Per-World Breakdown
| Seed | True Mole | True Decoy | Naive Log Pick | Pred Top Suspects | Pred Decoys | Mole Top-1 | Decoy Top-1 |
|---|---|---|---|---|---|---|---|
| 0 | `e05` | `e19` | `e19` | `e05` | `e19, e07` | YES | YES |
| 1 | `e02` | `e00` | `e00` | `e02, e09` | `e00, e06, e11` | YES | YES |
| 2 | `e09` | `e05` | `e05` | `e09` | `e05, e13` | YES | YES |

## Visual Reasoning Excerpts
- **Seed 0** (`rasters/medium_seed_0.png`, conf `0.99`): In Panel B, exact medium-tier canary fingerprinting isolates e05 (SAL) as the only employee holding all three leaked canary variants (ALL 3/3), while clearing every other row via struck-out variant mismatches. Panel C corroborates e05's access to all three regular leaked documents through the SAL department (L1 D3/3, with direct opens L3 on d1-1 and department access D on d4-2 and d5-3). In Panel A, e05 shows a moderate 3/21 (14.3%) after-hours rate consistent with true mole behavior, whereas e19 (13/27 after-hours) and e07 (5/19 after-hours) exhibit heavy red after-hours framing spikes despite 0/3 canary matches, identifying e19 as the primary framed decoy and e07 as secondary framing spillover.
- **Seed 1** (`rasters/medium_seed_1.png`, conf `0.94`): In Panel A, e00 exhibits an extreme after-hours spike of 9/13 (69%) alongside secondary spikes in e06 (5/17) and e11 (4/7), but Panel B clears all of them via exact canary variant mismatches (e00 holds 1/2, e06 and e11 hold 0/2), confirming e00 as the primary framed decoy. In Panel B, only e02 and e09 hold both surfaced canary variants (c7=A and c12=B for ALL 2/2). Panel C breaks the tie decisively in favor of e02, who directly opened four of the six regular leaked documents and belongs to a department correlated with five of six leaks (L4 D5/6), whereas e09 only opened one regular leaked document with two department matches (L1 D2/6) - making e02 the true mole.
- **Seed 2** (`rasters/medium_seed_2.png`, conf `0.99`): In Panel B, exact medium-tier canary fingerprinting uniquely isolates e09 with an ALL 5/5 green match across c1, c3, c6, c8, and c9, eliminating every other employee. In Panel A, e05 displays an extreme red after-hours spike (10/19 accesses) and e13 shows a secondary elevated red rate (5/13 accesses), yet both score 0/5 in Panel B - identifying e05 as the primary framed decoy absorbing injected fake after-hours logs and e13 as a secondary noise target. Meanwhile, e09 exhibits a moderate 3/14 (21%) after-hours profile consistent with genuine mole activity and aligns with ENG department access (L1 D4/5) in Panel C.
