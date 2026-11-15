# Role 6 (multimodal_evidence) - Multi-Tier v1.4 SOC Access & Framing Raster Vision Sweep

## Provenance
- Role: `multimodal_evidence` (`soc_access_vision_v14_sweep`)
- Model: `gemini-4-carbon`
- Thinking level: `high`
- Tiers version: `v1.4` (medium seeds [8, 9], hard seeds [8, 9, 10, 11])
- Commit: `c89f0fc1edbd01af0fef76a42231feab5b2f165f`
- Timestamp: `2026-11-14T23:14:27+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_access_vision_sweep.py --tiers medium,hard --medium-seeds 8,9 --hard-seeds 8,9,10,11 --thinking-level high --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-high-s8to11-carbon`
- Episode count: `6`
- Images read by model (`Part.from_bytes`, `image/png`): `6`
- Token usage: `calls=6`, `in=12606`, `out=3460`, `thinking=85629`, `cached=0`, `cost_usd=0.916102`, `latency_s=925.64`

## Per-Tier & Overall Aggregate Results vs Naive After-Hours Log Baseline
| Metric | `medium` (`n=2`) | `hard` (`n=4`) | Overall Vision (`n=6`) | Naive After-Hours Baseline (`n=6`) | Vision vs Naive Delta |
|---|---|---|---|---|---|
| Top-1 Mole Accuracy | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | 0/6 (0.0%) | +100.0% (6W-0T-0L) |
| Top-3 Mole Hit Rate | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Top-1 Framed Decoy Accuracy | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Framed Decoy in Suspected List | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Avoided Framing Trap Rate | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | 0/6 (0.0%) | +100.0% |
| Mean Confidence | 0.9900 | 0.9860 | 0.9873 | - | - |
| Brier Score (lower is better) | 0.0001 | 0.0003 | 0.0003 | - | - |
| Expected Calibration Error (ECE, 5-bin) | 0.0100 | 0.0140 | 0.0127 | - | - |

## Confidence Calibration & Head-to-Head Summary
- Overall Brier score: `0.000254` (ECE `0.012667`, signed confidence gap `-0.012667`)
- Mean posterior confidence: `0.9873` overall (`0.9873` when Top-1 correct, `n/a` when Top-1 wrong)
- Head-to-head vs Naive After-Hours Log Baseline: `6` wins, `0` ties, `0` losses (`+100.0%` Top-1 mole accuracy delta; Naive trapped by framed decoy on `6/6` worlds)

## Rendered SOC Evidence Rasters
| Tier | Seed | Raster Path | Size | Bytes | SHA-256 |
|---|---:|---|---|---:|---|
| `medium` | 8 | `rasters/medium_seed_8.png` | 1880x1020 | 148175 | `3402081694aa4b1194d788d24ccfffe729d8ea96ecdcea7c85b167960d6fc13e` |
| `medium` | 9 | `rasters/medium_seed_9.png` | 1880x1020 | 155045 | `f70471dfc7eb0177e30bc4457f4e8a1c57e5be8c101f007798a7ceabbddb40b8` |
| `hard` | 8 | `rasters/hard_seed_8.png` | 2180x1660 | 292464 | `349a454bbcca580c6ff31b1958a95eb22f97bb11957e5fd6cd5cf0baae2977e6` |
| `hard` | 9 | `rasters/hard_seed_9.png` | 2180x1660 | 290495 | `048de7da7566ba307110597af4ef62e8a5be7ff38c8d3d2554716c57451676b6` |
| `hard` | 10 | `rasters/hard_seed_10.png` | 2180x1660 | 289808 | `1917d25e65e9d0582ad4c38a1da59017fd1ed8d295067b813febea5fde2f1561` |
| `hard` | 11 | `rasters/hard_seed_11.png` | 2180x1660 | 287390 | `0180c1f09aaad84c50d5087473ecb3043972211eda1ac035b834e6f016c56695` |

## Per-World Breakdown
| Tier | Seed | Staff | Surfaced Canaries | True Mole | True Decoy | Naive Pick | Pred Suspects | Pred Decoys | Conf | Brier | Mole Top-1 | Decoy Top-1 |
|---|---:|---:|---:|---|---|---|---|---|---:|---:|---|---|
| `medium` | 8 | 20 | 6/12 | `e02` | `e01` | `e01` | `e02` | `e01, e19, e06` | 0.99 | 0.0001 | YES | YES |
| `medium` | 9 | 20 | 3/12 | `e15` | `e13` | `e13` | `e15` | `e13` | 0.99 | 0.0001 | YES | YES |
| `hard` | 8 | 40 | 7/38 | `e06` | `e04` | `e04` | `e06, e03, e00` | `e04, e18, e27` | 1.00 | 0.0000 | YES | YES |
| `hard` | 9 | 40 | 3/38 | `e08` | `e31` | `e31` | `e08, e11, e02` | `e31, e30, e33` | 0.97 | 0.0009 | YES | YES |
| `hard` | 10 | 40 | 6/38 | `e10` | `e00` | `e00` | `e10, e01, e04` | `e00` | 0.99 | 0.0000 | YES | YES |
| `hard` | 11 | 40 | 2/38 | `e09` | `e32` | `e32` | `e09, e12, e03` | `e32, e04, e05` | 0.98 | 0.0004 | YES | YES |

## Visual Reasoning Excerpts
- **MEDIUM Seed 8** (`rasters/medium_seed_8.png`, conf `0.99`): Panel B provides exact medium-tier canary fingerprinting that uniquely isolates e02 with ALL 6/6 surfaced variant matches (c1=C! narrowed suspects to e02, e05, and e08, and c2=A! plus confirmation traps c4, c6, c8, and c11=A! cleared e05 and e08). In contrast, Panel A reveals classic after-hours framing against innocent employees who scored 0/6 in Panel B: primary decoy e01 (FIN) exhibits a massive red spike of 9/16 (56.3%) after-hours accesses (capturing roughly half of the injected fake framing logs), with secondary red-flagged spikes on e19 (ENG, 6/18) and e06 (LEG, 5/20), whereas true mole e02 stayed low-volume at 2/5 accesses. Panel C shows e02 had department-level correlation on two of four surfaced regular leaks (L0 D2/4 on d7-1 and d10-2), though tie-breaking is unnecessary given e02's unique 6/6 exact canary match.
- **MEDIUM Seed 9** (`rasters/medium_seed_9.png`, conf `0.99`): In Panel A, e13 (LEG) exhibits a prominent red-flagged 7/17 (41.2%) after-hours spike driven by concentrated framing events (including D04 1!/1, D05 1!/1, D07 3!/3, D11 1!/1, and D12 1!/2), while e17 (SAL) shows a smaller scattered-framing elevation at 4/11 (36.4%); both are cleared in Panel B with 0/3 canary matches, confirming e13 as the primary framed decoy. In contrast, Panel B exact medium-tier fingerprinting uniquely isolates e15 (LEG) as the only employee matching ALL 3/3 surfaced canary variants (c2=C, c5=B, c6=B), whereas partial c2 matches e12 and e18 are eliminated on c5 and c6. Panel A shows e15 with moderate unframed after-hours activity at 4/16 (25.0%), and Panel C further corroborates e15 with L2 D4/5 - direct opens on d1-1 (L4) and d9-1 (L1) plus LEG department access (D) to d3-1 and d8-2 across 4 of the 5 surfaced regular leaks.
- **HARD Seed 8** (`rasters/hard_seed_8.png`, conf `1.00`): In Panel A, e04 exhibits an extreme red after-hours spike of 17/27 (63.0%) - alongside smaller cleared spikes on e18 at 7/18 (38.9%) and e27 at 6/31 (19.4%) - matching the hard-tier framing signature that concentrates ~50% of ~2.0 daily fake after-hours events onto an innocent decoy; Panel B definitively clears e04 (1/7 H3/7), e18 (1/7 H3/7), and e27 (0/7 H0/7) via unheld '-' canary tiles. By contrast, e06 is the sole employee matching ALL 7/7 surfaced canary variants in Panel B (at ~38x odds per extra match over H7/7 runners-up e03 at 3/7 and e00 at 2/7), exhibits the characteristic ~30% mole self after-hours rate in Panel A (7/23, 30.4%), and is strongly corroborated in Panel C with direct log opens on 4 of 6 surfaced regular leaks (L4 D5/6 vs L0 D0/6 for e03 and L2 D5/6 for e00).
- **HARD Seed 9** (`rasters/hard_seed_9.png`, conf `0.97`): Panel A shows an extreme after-hours framing spike on e31 (22/36, 61.1%) and smaller elevated bars on e30 (7/27) and e33 (5/16), but Panel B clears all three at 0/3 H0/3 (crossed '-' on c1, c2, and c11), identifying e31 as the primary framed decoy. In Panel B, only e08 (SAL) and e11 (ENG) match ALL 3/3 H3 surfaced canary variants (~38x odds advantage over 2/3 H3/3 rows e02 and e05). Panel C and Panel A decisively break the tie in favor of e08: e08 records strong regular-leak correlation L4 D6/8 (direct opens on d1-2 L1, d4-3 L1, d5-3 L2, and d14-2 L1) and a 6/18 (33.3%, 0.90 logs/day) after-hours profile matching the ~30% mole signature, whereas e11 shows weak L1 D4/8 regular-leak correlation (only d7-2 L1) and benign-like 4/24 (16.7%) after-hours activity.
- **HARD Seed 10** (`rasters/hard_seed_10.png`, conf `0.99`): Panel A shows an extreme red after-hours spike on e00 (ENG) at 21/34 accesses (61.8%) alongside Panel C exposure (L2 D4/4), which is the signature of concentrated decoy framing because Panel B clears e00 completely at 0/6 H2/6 (never received c3, c8, c11, or c15). Conversely, Panel B isolates H6/6 holders e10, e01, and e04, where e10 achieves a perfect ALL 6/6 H6 green variant match - multiplying mole odds by ~38^2 (1,444x) over e01 (4/6 H6/6) and ~38^4 (2.09Mx) over e04 (2/6 H6/6) while remaining unframed in Panel A (1/15 after-hours). Panel C decisively corroborates e10: ENG is the only department exposed to all four regular leaks (d7-2, d8-1, d11-2, d13-3), giving e10 L2 D4/4 (direct opens on d8-1 and d11-2), whereas e01 (FIN, L0 D0/4) and e04 (RES, L1 D1/4) lacked access to the full regular-leak set.
- **HARD Seed 11** (`rasters/hard_seed_11.png`, conf `0.98`): Panel B narrows primary suspects to e09 and e12, the only two H2/2 employees matching both surfaced canary variants c2=[B] and c4=[A] (~38x odds advantage over 1/2 H2/2 rows). Panels A and C decisively break the tie in favor of e09 (LEG): e09 shows mole-consistent elevated after-hours activity (8/19, 42.1%, ~1.0 log/day) and strong regular-leak correlation (L3 D5/6, with direct opens on d2-3, d6-3, and d8-1 in the only department exposed to 5/6 regular leaks), whereas e12 (FIN) has benign 10.5% after-hours logs (2/19) and zero regular-leak exposure (L0 D0/6). Meanwhile, e32 (SAL) exhibits a massive Panel A after-hours spike (17/33, 51.5%) despite being 100% cleared in Panel B (0/2 H0/2, crossed-out tiles), marking e32 as the primary framed decoy alongside smaller scattered-spike decoys e04 (6/20, 0/2 H2/2), e05 (6/22, 0/2 H2/2), e30 (5/16, 0/2 H0/2), and e31 (5/19, 0/2 H0/2).
