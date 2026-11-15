# Role 6 (multimodal_evidence) - Multi-Tier v1.4 SOC Access & Framing Raster Vision Sweep

## Provenance
- Role: `multimodal_evidence` (`soc_access_vision_v14_sweep`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (medium seeds [3, 4, 5, 6, 7], hard seeds [3, 4, 5, 6, 7])
- Commit: `b40e5c8ddd303039e7fb605ec50b4005a174a064`
- Timestamp: `2026-11-14T17:10:38+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_access_vision_sweep.py --tiers medium,hard --seeds 3,4,5,6,7 --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/access-heatmap-v14-sweep-carbon`
- Episode count: `10`
- Images read by model (`Part.from_bytes`, `image/png`): `10`
- Token usage: `calls=10`, `in=20760`, `out=4181`, `thinking=18283`, `cached=0`, `cost_usd=0.266160`, `latency_s=340.38`

## Per-Tier & Overall Aggregate Results vs Naive After-Hours Log Baseline
| Metric | `medium` (`n=5`) | `hard` (`n=5`) | Overall Vision (`n=10`) | Naive After-Hours Baseline (`n=10`) | Vision vs Naive Delta |
|---|---|---|---|---|---|
| Top-1 Mole Accuracy | 4/5 (80.0%) | 5/5 (100.0%) | 9/10 (90.0%) | 0/10 (0.0%) | +90.0% (9W-1T-0L) |
| Top-3 Mole Hit Rate | 5/5 (100.0%) | 5/5 (100.0%) | 10/10 (100.0%) | - | - |
| Top-1 Framed Decoy Accuracy | 5/5 (100.0%) | 5/5 (100.0%) | 10/10 (100.0%) | - | - |
| Framed Decoy in Suspected List | 5/5 (100.0%) | 5/5 (100.0%) | 10/10 (100.0%) | - | - |
| Avoided Framing Trap Rate | 5/5 (100.0%) | 5/5 (100.0%) | 10/10 (100.0%) | 0/10 (0.0%) | +100.0% |
| Mean Confidence | 0.9140 | 0.9834 | 0.9487 | - | - |
| Brier Score (lower is better) | 0.0770 | 0.0010 | 0.0390 | - | - |
| Expected Calibration Error (ECE, 5-bin) | 0.1340 | 0.0166 | 0.0753 | - | - |

## Confidence Calibration & Head-to-Head Summary
- Overall Brier score: `0.039010` (ECE `0.075300`, signed confidence gap `+0.048700`)
- Mean posterior confidence: `0.9487` overall (`0.9852` when Top-1 correct, `0.6200` when Top-1 wrong)
- Head-to-head vs Naive After-Hours Log Baseline: `9` wins, `1` ties, `0` losses (`+90.0%` Top-1 mole accuracy delta; Naive trapped by framed decoy on `10/10` worlds)

## Rendered SOC Evidence Rasters
| Tier | Seed | Raster Path | Size | Bytes | SHA-256 |
|---|---:|---|---|---:|---|
| `medium` | 3 | `rasters/medium_seed_3.png` | 1880x1020 | 153199 | `141eba07a396d53d3601c7a6fbe26ae5e30dadb24a52dc5dd90ff84aa9bed537` |
| `medium` | 4 | `rasters/medium_seed_4.png` | 1880x1020 | 155074 | `2679b12ed395724e061ab287fc2672067eae6a4fec393d7b5f5308576ae5b883` |
| `medium` | 5 | `rasters/medium_seed_5.png` | 1880x1020 | 157451 | `f14e824211d689692723153fe9a889d9bf21c1dea3caed3cd63e0a321c26dad9` |
| `medium` | 6 | `rasters/medium_seed_6.png` | 1880x1020 | 155758 | `035efd837d50025e0536f73d5cbed5fc6d42919ca028d0ed078a72a1724cbffa` |
| `medium` | 7 | `rasters/medium_seed_7.png` | 1880x1020 | 142876 | `07ee3475bfc705a6db0b1ba97061bd9a4779b06bc912cb792d72b13be4110e8b` |
| `hard` | 3 | `rasters/hard_seed_3.png` | 2180x1660 | 290569 | `fa67da3305f70da371847b40fd2e9877a7ff369d75342ce61925df28955e97ae` |
| `hard` | 4 | `rasters/hard_seed_4.png` | 2180x1660 | 295081 | `4a83f4ef724ef2fada88dbad6cae82470468e593ef3af32b528103a6637874f8` |
| `hard` | 5 | `rasters/hard_seed_5.png` | 2180x1660 | 295576 | `39bbc035b967f46fa697e077ea0d0dd33b82f1d3e05285ead76be6e52892805d` |
| `hard` | 6 | `rasters/hard_seed_6.png` | 2180x1660 | 290382 | `b0df34c9a420914a35b20e8136790352fe7a609bb054b4e76a305288deb5eb30` |
| `hard` | 7 | `rasters/hard_seed_7.png` | 2180x1660 | 291777 | `549bb199ca88cfa74b781de9aab609770adeae225de712a812cabfeadefe7317` |

## Per-World Breakdown
| Tier | Seed | Staff | Surfaced Canaries | True Mole | True Decoy | Naive Pick | Pred Suspects | Pred Decoys | Conf | Brier | Mole Top-1 | Decoy Top-1 |
|---|---:|---:|---:|---|---|---|---|---|---:|---:|---|---|
| `medium` | 3 | 20 | 1/12 | `e14` | `e13` | `e13` | `e14, e15` | `e13` | 0.98 | 0.0004 | YES | YES |
| `medium` | 4 | 20 | 4/12 | `e17` | `e03` | `e03` | `e17` | `e03, e05, e08` | 0.99 | 0.0001 | YES | YES |
| `medium` | 5 | 20 | 3/12 | `e14` | `e09` | `e09` | `e14` | `e09, e13` | 0.99 | 0.0001 | YES | YES |
| `medium` | 6 | 20 | 3/12 | `e17` | `e19` | `e19` | `e17` | `e19, e03, e09` | 0.99 | 0.0001 | YES | YES |
| `medium` | 7 | 20 | 0/12 | `e09` | `e03` | `e03` | `e06, e09, e05` | `e03, e17, e04` | 0.62 | 0.3844 | NO | YES |
| `hard` | 3 | 40 | 6/38 | `e29` | `e12` | `e12` | `e29, e26, e20` | `e12` | 1.00 | 0.0000 | YES | YES |
| `hard` | 4 | 40 | 7/38 | `e11` | `e31` | `e31` | `e11, e08, e02` | `e31, e29, e27` | 1.00 | 0.0000 | YES | YES |
| `hard` | 5 | 40 | 6/38 | `e27` | `e04` | `e04` | `e27, e34, e30` | `e04, e24, e21` | 0.93 | 0.0049 | YES | YES |
| `hard` | 6 | 40 | 5/38 | `e34` | `e20` | `e20` | `e34, e35, e37` | `e20, e06, e25` | 0.99 | 0.0001 | YES | YES |
| `hard` | 7 | 40 | 6/38 | `e37` | `e12` | `e12` | `e37, e34, e36` | `e12, e27, e03` | 1.00 | 0.0000 | YES | YES |

## Visual Reasoning Excerpts
- **MEDIUM Seed 3** (`rasters/medium_seed_3.png`, conf `0.98`): In Panel B, exact canary fingerprinting narrows the mole candidates to e13, e14, and e15 (all matching c8=B with 1/1). Panel A immediately flags e13 (LEG) as the primary framed decoy due to an extreme red after-hours spike of 18/32 (40% of all 45 after-hours events across the company), which matches the concentrated decoy framing signature despite e13 coincidentally sharing partition B on c8. Panel C decisively breaks the tie in favor of e14 (SAL): all 8 surfaced regular leaks belong to the SAL department (D8/8) and e14 directly opened 5 of them (L5 D8/8) with a plausible mole after-hours rate of 3/14 in Panel A, whereas e13 (L3 D3/8) and e15 (L1 D2/8) lacked departmental access to the majority of leaked regular documents.
- **MEDIUM Seed 4** (`rasters/medium_seed_4.png`, conf `0.99`): In Panel A, e03 exhibits the most prominent red after-hours spike (6/22 across five days), alongside secondary spikes on e05 (4/15), e08 (4/21), and e15 (4/18), yet Panel B clears all four with 0/4 canary matches - a classic framing decoy pattern where 50% of injected fake after-hours logs target one innocent employee (e03). Conversely, e17 maintains a clean daytime-only profile in Panel A (0/19 after-hours, consistent with the mole never framing itself) while uniquely matching ALL 4/4 exact canary variants in Panel B and correlating with 6 of 7 regular leaked documents in Panel C (L3 D6/7 via LEG department access and direct opens on d1-3, d1-1, and d3-1).
- **MEDIUM Seed 5** (`rasters/medium_seed_5.png`, conf `0.99`): In Panel B, exact medium-tier canary fingerprinting isolates e14 (SAL) as the unique ALL 3/3 match across c4, c7, and c9, corroborated in Panel C where e14 shows strong regular-leak exposure (L3 D6/8, including direct opens L4 on d2-1, L1 on d2-3, and L1 on d7-1) and a moderate 4/14 after-hours rate in Panel A. Conversely, Panel A highlights e09 (13/25 after-hours) as the primary framed decoy with a massive red spike bar despite 0/3 canary matches and minimal regular-leak correlation (L1 D1/8), alongside e13 (6/18 after-hours) showing a secondary red-highlighted spike while cleared on c7 and c9 (1/3).
- **MEDIUM Seed 6** (`rasters/medium_seed_6.png`, conf `0.99`): In Panel B, exact medium-tier canary fingerprinting isolates e17 as the only 3/3 match across c2=B, c7=C, and c8=A, whereas every other employee is cleared by mismatched or unheld variants. In Panel A, e17 maintains a low, inconspicuous after-hours profile (1/11), while fellow ENG employee e19 exhibits an extreme red after-hours spike (10/22 across nine separate days) alongside 0/3 canary matches - the classic signature of the primary framed decoy absorbing roughly half of the injected fake after-hours logs (with minor after-hours elevations on e03, e09, and e14). Panel C corroborates e17's access to all seven regular leaked documents via ENG department distribution (L3 D7/7, with direct opens on d1-2, d2-3, and d3-1).
- **MEDIUM Seed 7** (`rasters/medium_seed_7.png`, conf `0.62`): Because Panel B has 0 surfaced canaries (all rows 0/0), Panel C provides the primary discriminating signal: all 7 surfaced regular leaks map to the FIN department (D7/7 exclusively on FIN rows e01, e05, e06, e09, e12, e15, e19). Within FIN, e06 has the strongest direct access correlation at L5 D7/7 (direct opens on 5 of 7 leaked docs including L3 on d2-3) alongside elevated overall volume and a mole-consistent 4/20 (20%) after-hours ratio in Panel A, ahead of L4 D7/7 peers e09, e05, and e15. Conversely, Panel A flags e03 (LEG) with an extreme red 7/19 after-hours spike despite minimal leak exposure in Panel C (L1 D1/7), marking e03 as the primary framed decoy alongside secondary spike rows e17 (4/15, L1 D1/7), e04 (4/14, L1 D4/7), and e11 (4/22, L2 D4/7).
- **HARD Seed 3** (`rasters/hard_seed_3.png`, conf `1.00`): In Panel A, e12 shows an extreme red after-hours spike (26/41 logs, 63%) but is completely cleared in Panel B (0/6 H0/6) and Panel C (L0 D0/5), identifying e12 as the framed decoy absorbing fake after-hours injections. Conversely, Panel B isolates the mole among the three H6/6 holders, where e29 achieves an exact 6/6 variant match (~1444x canary odds advantage over 4/6 holder e26). Panel A and Panel C strongly corroborate e29, who exhibits a mole-consistent moderate after-hours rate (9/22, 41% vs e26 at 1/15, 7%) alongside direct access to two regular leaked docs (L4 on d1-2 and L1 on d15-3) and full FIN department exposure (L2 D5/5).
- **HARD Seed 4** (`rasters/hard_seed_4.png`, conf `1.00`): In Panel A, e31 exhibits an extreme red after-hours framing spike (22/40 logs, 55% after-hours), while e29 (7/21) and e27 (6/23) show smaller secondary spikes; however, Panel B proves all three held 0/7 surfaced canaries (crossed-out tiles, H0/7), confirming e31 as the primary framed decoy. Conversely, e11 is the sole employee matching all 7/7 surfaced canary variants in Panel B (overwhelmingly beating runner-up e08 at 4/7 by three variant matches), displays the expected ~30% mole after-hours rate in Panel A (5/17 logs), and is corroborated in Panel C by direct access to leaked regular doc d3-4 (L1) plus department exposure across five of six regular leaks (L1 D5/6).
- **HARD Seed 5** (`rasters/hard_seed_5.png`, conf `0.93`): Panel A shows an extreme after-hours spike on e04 (19/30 red logs) alongside smaller spikes on e24 (6/21), e21 (5/15), and e19 (5/17), but Panel B clears all of them (e04 and e19 are H0/6; e24 and e21 are H3/6), identifying e04 as the primary framed decoy absorbing ~50% of injected fake events. Among the three un-cleared H6/6 canary holders in Panel B, zero rows have 6/6 due to 5% variant noise, so e27 at 5/6 H6/6 holds a ~38x canary variant odds lead over runner-up e34 at 4/6 H6/6 (and a massive lead over e30 at 2/6 H6/6). Panel C corroborates e27 in FIN with direct opens and full department exposure across surfaced regular leaks (L3 D6/6) alongside unframed Panel A activity (2/13 after-hours).
- **HARD Seed 6** (`rasters/hard_seed_6.png`, conf `0.99`): Employee e34 (RES) is the clear mole: in Panel B, e34 is the sole ALL 5/5 H5 match across c1-2, c5, c6, c7, and c16 (~1444x higher variant-match odds than the 3/5 H5/5 runners-up); in Panel C, e34 has full department exposure to all six regular leaks plus direct opens (L2 D6/6, whereas H5/5 peers in LEG and SAL only have D1/6); and in Panel A, e34 shows the expected mole baseline of 6/20 (30%) after-hours logs. Conversely, Panel A's largest red after-hours spike hits e20 (12/30), identifying e20 as the primary framed decoy alongside secondary framing scatter on cleared employees e06 (7/29, H0/5), e25 (7/21, H1/5), and e33 (7/21, H1/5).
- **HARD Seed 7** (`rasters/hard_seed_7.png`, conf `1.00`): In Panel A, e12 exhibits an extreme after-hours spike (25/43 red events) typical of concentrated decoy framing, and is 100% cleared in Panel B with H0/6 canary holdings (alongside minor cleared spikes on e27 at 7/24 and e03 at 6/24). Conversely, e37 shows a moderate mole-consistent after-hours rate in Panel A (6/17, ~35%), achieves an exact 6/6 variant match across all held canaries in Panel B (overwhelmingly beating H6/6 peers e34 and e36 at 3/6 each), and is corroborated in Panel C by direct leaked-document opens (L4 on d2-2 and department exposure D4/5).
