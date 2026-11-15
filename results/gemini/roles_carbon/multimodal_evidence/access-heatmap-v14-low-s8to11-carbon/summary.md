# Role 6 (multimodal_evidence) - Multi-Tier v1.4 SOC Access & Framing Raster Vision Sweep

## Provenance
- Role: `multimodal_evidence` (`soc_access_vision_v14_sweep`)
- Model: `gemini-4-carbon`
- Thinking level: `low`
- Tiers version: `v1.4` (medium seeds [8, 9], hard seeds [8, 9, 10, 11])
- Commit: `c89f0fc1edbd01af0fef76a42231feab5b2f165f`
- Timestamp: `2026-11-14T23:02:38+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_access_vision_sweep.py --tiers medium,hard --medium-seeds 8,9 --hard-seeds 8,9,10,11 --thinking-level low --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-low-s8to11-carbon`
- Episode count: `6`
- Images read by model (`Part.from_bytes`, `image/png`): `6`
- Token usage: `calls=6`, `in=12606`, `out=3108`, `thinking=1983`, `cached=0`, `cost_usd=0.076122`, `latency_s=75.48`

## Per-Tier & Overall Aggregate Results vs Naive After-Hours Log Baseline
| Metric | `medium` (`n=2`) | `hard` (`n=4`) | Overall Vision (`n=6`) | Naive After-Hours Baseline (`n=6`) | Vision vs Naive Delta |
|---|---|---|---|---|---|
| Top-1 Mole Accuracy | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | 0/6 (0.0%) | +100.0% (6W-0T-0L) |
| Top-3 Mole Hit Rate | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Top-1 Framed Decoy Accuracy | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Framed Decoy in Suspected List | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | - | - |
| Avoided Framing Trap Rate | 2/2 (100.0%) | 4/4 (100.0%) | 6/6 (100.0%) | 0/6 (0.0%) | +100.0% |
| Mean Confidence | 0.9900 | 0.9670 | 0.9747 | - | - |
| Brier Score (lower is better) | 0.0001 | 0.0031 | 0.0021 | - | - |
| Expected Calibration Error (ECE, 5-bin) | 0.0100 | 0.0330 | 0.0253 | - | - |

## Confidence Calibration & Head-to-Head Summary
- Overall Brier score: `0.002117` (ECE `0.025333`, signed confidence gap `-0.025333`)
- Mean posterior confidence: `0.9747` overall (`0.9747` when Top-1 correct, `n/a` when Top-1 wrong)
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
| `medium` | 8 | 20 | 6/12 | `e02` | `e01` | `e01` | `e02, e05, e08` | `e01, e19, e06` | 0.99 | 0.0001 | YES | YES |
| `medium` | 9 | 20 | 3/12 | `e15` | `e13` | `e13` | `e15` | `e13, e17` | 0.99 | 0.0001 | YES | YES |
| `hard` | 8 | 40 | 7/38 | `e06` | `e04` | `e04` | `e06, e03, e00` | `e04, e18, e27` | 1.00 | 0.0000 | YES | YES |
| `hard` | 9 | 40 | 3/38 | `e08` | `e31` | `e31` | `e08, e11, e02` | `e31, e30, e33` | 0.89 | 0.0121 | YES | YES |
| `hard` | 10 | 40 | 6/38 | `e10` | `e00` | `e00` | `e10, e01, e04` | `e00, e35, e22` | 1.00 | 0.0000 | YES | YES |
| `hard` | 11 | 40 | 2/38 | `e09` | `e32` | `e32` | `e09, e12, e03` | `e32, e04, e05` | 0.98 | 0.0004 | YES | YES |

## Visual Reasoning Excerpts
- **MEDIUM Seed 8** (`rasters/medium_seed_8.png`, conf `0.99`): Panel A displays a severe after-hours spike on e01 (9/16 red events, 56%) alongside secondary spikes on e19 (6/18), e06 (5/20), and e04 (4/15). However, Panel B proves these high-spike accounts are framed decoys because e01, e19, e06, and e04 all have 0/6 canary matches on exact medium-tier fingerprinting. Conversely, e02 (SAL) exhibits a modest 2/5 after-hours profile in Panel A, matches ALL 6/6 surfaced canary variants in Panel B, and shows department-level exposure (L0 D2/4, bronze D tiles on d7-1 and d10-2) in Panel C, uniquely identifying e02 as the true mole and e01 as the primary framed decoy.
- **MEDIUM Seed 9** (`rasters/medium_seed_9.png`, conf `0.99`): In Panel B, exact medium-tier canary fingerprinting isolates e15 (LEG) as the unique 3/3 match across surfaced columns c2, c5, and c6. Panel C reinforces this with e15 showing direct access or departmental exposure to 4 of 5 leaked regular documents (L4 on d1-1, L1 on d9-1, and D on d3-1 and d8-2, CORR L2 D4/5) and moderate after-hours activity (4/16, 25%) in Panel A consistent with mole behavior. By contrast, e13 exhibits the largest after-hours spike in Panel A (7/17, 41% red bar) alongside e17 (4/11, 36%), yet both score 0/3 on surfaced canary variants in Panel B - the classic signature of innocent decoys absorbing injected framing logs.
- **HARD Seed 8** (`rasters/hard_seed_8.png`, conf `1.00`): In Panel B, e06 (ENG) is the sole standout candidate, holding all 7 surfaced canaries and achieving a perfect 7/7 variant match (ALL 7/7 H7), whereas the only other H7/7 holders e03 (LEG, 3/7 matches) and e00 (ENG, 2/7 matches) require 4 and 5 simultaneous 5% variant-flip errors respectively. Panel C strongly corroborates e06, showing direct access opens on 4 of 6 surfaced regular leaks (L4 D5/6: L1 on d1-4, d2-3, d12-3 and L2 on d2-4) versus L0 D0/6 for e03 and L2 D5/6 for e00. In Panel A, e06 exhibits the expected moderate mole self after-hours profile (7/23 = 30.4%, ~1.15 logs/day), while e04 (RES) shows an extreme red after-hours spike (17/27 = 63.0%) despite being 100% cleared in Panel B (1/7 H3/7, missing c13, c15, c17), identifying e04 as the primary framed decoy alongside secondary noise spikes on cleared employees like e18 (7/18, H3/7) and e27 (6/31, H0/7).
- **HARD Seed 9** (`rasters/hard_seed_9.png`, conf `0.89`): In Panel B, e08 and e11 are tied with perfect ALL 3/3 H3 canary variant matches ([C] on c1, [B] on c2, [A] on c11), giving them ~38x higher canary likelihood than 2/3 H3/3 runners-up e02 and e05. Panel C breaks the tie decisively in favor of e08: e08 has L4 D6/8 regular-leak correlation (direct opens on d1-2, d4-3, d5-3, and d14-2 plus department exposure on d9-2 and d12-2), whereas e11 only has L1 D4/8 (single direct open on d7-2). Panel A further corroborates e08 with a mole-consistent 33% after-hours rate (6/18) versus e11 at 17% (4/24). Meanwhile, e31 exhibits a massive anomalous after-hours framing spike in Panel A (22/36 after-hours logs across 12 days) while being 100% cleared in Panel B (0/3 H0/3, crossed-out '-' on c1, c2, and c11), making e31 the primary framed decoy alongside secondary noise targets e30 (7/27, H0/3) and e33 (5/16, H0/3).
- **HARD Seed 10** (`rasters/hard_seed_10.png`, conf `1.00`): In Panel B, e10 is the sole employee holding all 6 surfaced canaries with a perfect 6/6 variant match (ALL 6/6 H6), giving overwhelming odds (~38^2 = 1444x over second-place e01 at 4/6 H6/6, and ~38^4 over e04 at 2/6 H6/6). Panel C strongly corroborates e10 (ENG), showing department access to all 4 leaked regular documents (D4/4) and direct opens on two of them (d8-1 and d11-2, L2 D4/4), whereas e01 (FIN) has zero regular-leak exposure (L0 D0/4). Meanwhile, Panel A exposes e00 as the primary framed decoy: e00 exhibits a massive red after-hours framing spike (21/34 after-hours logs across 12 days) despite being 100% cleared in Panel B (0/6 H2/6, missing c5, c8, c11, and c15). Secondary framing noise appears as smaller after-hours elevations (5 after-hours events) on cleared rows like e35, e22, e29, and e26.
- **HARD Seed 11** (`rasters/hard_seed_11.png`, conf `0.98`): In Panel A, e32 exhibits an extreme after-hours spike of 17/33 logs (51.5%) across D01-D20, yet Panel B shows e32 never received either surfaced canary (0/2 H0/2), identifying e32 as the primary framed decoy alongside minor noise spikes on cleared/non-matching staff (e04 at 6/20, e05 at 6/22, e30 at 5/16, e31 at 5/19). In Panel B, only e09 (LEG) and e12 (FIN) achieve full ALL 2/2 H2 canary variant matches ([B] on c2 and [A] on c4). Panel C and Panel A decisively break this tie: e09 has strong regular-leak correlation (L3 D5/6, directly opening three leaked docs with department exposure on five of six) and a mole-consistent 8/19 (42%) after-hours rate, whereas e12 has zero regular-leak exposure (L0 D0/6) and a benign 2/19 (10.5%) after-hours rate.
