# Role 6 (multimodal_evidence) - Multi-Image Composite Incident Dossier Run

## Provenance
- Role: `multimodal_evidence` (`multi_image_incident_dossier`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`6` composite dossiers across `medium` seeds `3,4,5` and `hard` seeds `2,3,4`)
- Commit: `1c51dca7ea613e96cc60623613a3b1e25057fee7`
- Timestamp: `2026-11-14T23:05:23+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_incident_dossier.py --worlds medium:3,medium:4,medium:5,hard:2,hard:3,hard:4 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/multi-image-dossier-v14-expanded-carbon`
- Composite dossiers evaluated (`episode_count`): `6`
- Images read by model (`Part.from_bytes`, `image/png`, `3` distinct PNGs per single call): `18`
- Token usage: `calls=6`, `in=27059`, `out=2511`, `thinking=30480`, `cached=0`, `cost_usd=0.384028`, `latency_s=354.69`

## Multi-Image Fusion vs Single-Image Baselines
| Approach | Inputs Available | Top-1 Mole Accuracy | Top-1 Framed Decoy Accuracy | Avoided Framing Trap |
|---|---|---|---|---|
| **Gemini 3-Image Joint Dossier (`gemini-4-carbon`)** | **Exhibit 1 + Exhibit 2 + Exhibit 3 (`3` PNGs in 1 call)** | **5/6 (83.3%)** | **6/6 (100.0%)** | **6/6 (100.0%)** |
| Exhibit 1 Only (Naive After-Hours Swipe Pick) | `badge_raster` PNG only (no canary roster, no leak feed) | 0/6 (0.0%) | - | 0/6 (0.0%) |
| Exhibit 2 Only (Leaked Memo Scans Only) | `leaked_memo_scans` PNG only (no employee IDs) | 0/6 (0.0%) | 0/6 (0.0%) | - |
| Exhibit 3 Only (Static Floorplan + Canary Matrix) | `org_canary_map` PNG only (no leak outcomes, uniform `1/N` prior = 3.8%) | 0/6 (0.0%) | 0/6 (0.0%) | - |

- Exhibit 2 visual watermark scan readout exact match (`DOC-ID` + `COPY-CODE`): `16/16` (`100.0%`)
- Exhibit 3 floorplan department attribution accuracy: `6/6` (`100.0%`)

## Per-World Cross-Image Breakdown
| World | True Mole (Dept) | True Decoy | Img-1 Naive Pick | Leaked Canaries (Img 2) | Pred Mole Top-3 | Pred Decoy | Mole Top-1 | Decoy Top-1 |
|---|---|---|---|---|---|---|---|---|
| `medium_3` | `e14` (Sales) | `e13` | `e13` | `c7=C` | `e10, e14` | `e13` | NO | YES |
| `medium_4` | `e17` (Legal) | `e03` | `e03` | `c4=C` | `e17` | `e03` | YES | YES |
| `medium_5` | `e14` (Sales) | `e09` | `e09` | `c3=A, c12=B` | `e14` | `e09` | YES | YES |
| `hard_2` | `e25` (Finance) | `e31` | `e31` | `c2-2=B, c3-2=B, c6=C, c11=C` | `e25, e30` | `e31, e21` | YES | YES |
| `hard_3` | `e29` (Finance) | `e12` | `e12` | `c2-2=C, c7-2=C, c9-2=A, c11-2=A, c17-2=C` | `e29, e24` | `e12, e28` | YES | YES |
| `hard_4` | `e11` (Engineering) | `e31` | `e31` | `c1-2=B, c10=A, c14=B` | `e11` | `e31` | YES | YES |

## Rendered Composite Dossier PNGs (18 Files)
| World | Exhibit | Path | Dimensions | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `medium_3` | `badge_raster` | `dossiers/badge_raster_seed_medium_3.png` | 1274x996 | 109347 | `46084e32980d0a742bf63bbd65996df8306124b11e99dff42455957b20950586` |
| `medium_3` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_3.png` | 1510x644 | 51231 | `b5fcab902b05f163aacf6ec3206d8a92d21bc21b35610830a330fac402f861ba` |
| `medium_3` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_3.png` | 1320x1204 | 125584 | `67efa6de764b0d323f129699641cb933fe18a75e071799cab73a55b9e1de014a` |
| `medium_4` | `badge_raster` | `dossiers/badge_raster_seed_medium_4.png` | 1274x996 | 110480 | `9ef46a2fb71295fb1ebb48c33bea044f8676bc2cd49257f9e8b51f37eee3ffb0` |
| `medium_4` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_4.png` | 1510x644 | 51333 | `d429f153e12f7d066600114e65b80b9908c3a3a121127994400d0fc4eeb2a54c` |
| `medium_4` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_4.png` | 1320x1204 | 125261 | `a0c2b19608c5eec2e1d005a2b16b97f634949c210c6153b85a124a7f7837b650` |
| `medium_5` | `badge_raster` | `dossiers/badge_raster_seed_medium_5.png` | 1274x996 | 109980 | `e2abe26a77583309e3111c33d7aa15ab84e585ae7d9fd813bd51f4132173203e` |
| `medium_5` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_5.png` | 1510x644 | 67149 | `78d297c4a1b7d5854eaceb534ea0e886b780a50add42ce8fa4aeb3027c249407` |
| `medium_5` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_5.png` | 1320x1232 | 126393 | `a4b63d800eb513227296d38f31c8fc0bf860e0d3eb628852b902e96738e81045` |
| `hard_2` | `badge_raster` | `dossiers/badge_raster_seed_hard_2.png` | 1530x1636 | 202881 | `bceea437d28663ae5aa2ce835b480f015a2c69e1932e18ae30af1b5639a86012` |
| `hard_2` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_2.png` | 1510x1126 | 87492 | `41c61b1bf55736cd2b257fa47b229a43e07c9c20ecc14e8f1b4ac4a1d5d9415b` |
| `hard_2` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_2.png` | 2144x1962 | 239888 | `ad9108d536bad8960e7bde29e5b50d311598b42e6cc33c75753a179373e930ad` |
| `hard_3` | `badge_raster` | `dossiers/badge_raster_seed_hard_3.png` | 1530x1636 | 198945 | `641f5547b7d5772e0c76558cf58365c95ff16377fb8ed9d47b60376c3b31b685` |
| `hard_3` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_3.png` | 2252x1126 | 119286 | `e08b7844a5ac258bdb1ecade7b6c6a569717d6a1d6aaf71c1325bd458cdbcb0b` |
| `hard_3` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_3.png` | 2144x1934 | 238148 | `4087c1352750426de0c5489acde39f44a8f37bc0730d4a14dd4b71f7608c90f4` |
| `hard_4` | `badge_raster` | `dossiers/badge_raster_seed_hard_4.png` | 1530x1636 | 196401 | `d270c0a1cd1e25c38fb026a258e117d80dc27afe11aa85d87d794f9892c9421b` |
| `hard_4` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_4.png` | 1510x1126 | 97367 | `c5fd3ccad8d9dd8959f959cd6962d9dfaeb9df0879e0af4cb86345646483dfe4` |
| `hard_4` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_4.png` | 2144x1934 | 238929 | `73faae00b67f624ceb1f50a16d5702ff85ea59bdd2f920ac51a4ee0ddbe31d81` |

## Cross-Image Forensic Reasoning Excerpts
- **`medium_3`** (conf `0.62`, dept `Sales`): Exhibit 2 shows one intercepted canary memo scan through Day 13: DOC-ID c7 with COPY-CODE C (confirmed by 3 header bar segments and 3/8 active footer ticks, surfaced Day 10). Intersecting (c7, C) against Exhibit 3's Canary Distribution Matrix narrows the 20 staff to exactly two candidates who were issued c7:C - e10 (c3:C, c7:C, c10:C) and e14 (c3:A, c7:C, c12:B) - both assigned to the Sales clearance zone (SAL-03 and SAL-04). Cross-referencing Exhibit 1 ranks e10 slightly ahead of e14 because e10 logged a physical vault swipe on D10 (matching the Day 10 surfacing date, whereas e14 had zero swipes on D09-D10) and exhibits a moderate 2/7 (29% AH) swipe profile consistent with the 15% mole after-hours baseline over a small sample, while e14 remains the secondary suspect at 2/10 (20% AH). Meanwhile, e13 exhibits the dominant TOP AH SPIKE of 14/27 (52% AH) in Exhibit 1 but was only issued c3:C, c6:B, and c11:B in Exhibit 3 (no access to c7), confirming e13 is the innocent framed decoy.
- **`medium_4`** (conf `0.98`, dept `Legal`): Exhibit 2 shows one intercepted leaked canary scan: doc_id c4 with COPY-CODE C (confirmed by 3 header segments and 3/8 footer ticks), surfaced on Day 07. Intersecting (c4, C) against Exhibit 3's Canary Distribution Matrix uniquely identifies employee e17 (assigned c4:C, c6:C, c9:C), who sits in the Legal clearance zone (desk LEG-05); only e15-e19 received c4, and none of the others hold variant C. Exhibit 1 corroborates e17's vault access prior to the Day 07 leak (including swipes on D01, D02, D03, and D05 with 3/11 or 27% after-hours), while exposing e03 (8/25 swipes, 32% after-hours, flagged TOP AH SPIKE) as the primary framed decoy because e03 was only issued c1:A, c8:C, and c10:C and never held c4.
- **`medium_5`** (conf `0.99`, dept `Sales`): Exhibit 2 reveals two intercepted leaked canary memos: doc c3 with COPY-CODE A (1 header segment, footer tick A:1, surfaced Day 04) and doc c12 with COPY-CODE B (2 header segments, footer ticks A:1 and B:2, surfaced Day 13). Cross-referencing Exhibit 3's Canary Distribution Matrix shows c3:A was issued only to e11 and e14, while c12:B was issued only to e06, e07, and e14; their unique intersection identifies e14 (assigned to ZONE-SAL / Sales desk SAL-03) as the sole employee holding both leaked variants. Exhibit 1 corroborates this finding: e14 exhibits a moderate vault profile of 1/8 after-hours swipes (12% AH, including an after-hours swipe on D04 when c3 surfaced), whereas e09 triggers the TOP AH SPIKE status at 12/24 after-hours swipes (50% AH) despite holding only c2:C, c6:B, and c9:C, confirming e09 as the framed innocent decoy.
- **`hard_2`** (conf `1.00`, dept `Finance`): Exhibit 2 reveals four leaked canary memos: c2-2 (variant B, Day 05), c3-2 (variant B, Day 05), c6 (variant C, Day 11), and c11 (variant C, Day 15). Intersecting these four DOC-IDs against Exhibit 3's Canary Distribution Matrix eliminates 38 of 40 staff, leaving only e25 and e30 as holders of all four documents. Employee e25 (Finance, clearance L3) matches all 4 of 4 leaked variants (c2-2:B, c3-2:B, c6:C, c11:C), whereas e30 (Legal) matches 0 of 4 (c2-2:A, c3-2:C, c6:A, c11:A), giving e25 overwhelming canary odds (>2,000,000:1 at 38x per matching variant). Exhibit 1 corroborates e25 with an elevated 8/23 (35% AH) swipe profile consistent with the ~30% mole after-hours rate and vault access preceding each leak date, while exposing e31 (28/47, 60% AH TOP AH SPIKE) and e21 (8/21, 38% AH ELEVATED AH) as framed decoys who lacked at least three of the four leaked canaries in Exhibit 3.
- **`hard_3`** (conf `0.99`, dept `Finance`): Exhibit 2 reveals five leaked canary memos: (c2-2, C), (c7-2, C), (c9-2, A), (c11-2, A), and (c17-2, C). Cross-referencing Exhibit 3's Canary Distribution Matrix shows only two employees were issued all five leaked DOC-IDs: e29 and e24. Employee e29 (Finance, CLR-2) matches 5/5 leaked variant codes (c2-2:C, c7-2:C, c9-2:A, c11-2:A, c17-2:C), whereas e24 only matches 3/5 (mismatching on c2-2:A and c11-2:C). Exhibit 1 corroborates e29 as the mole with 6/15 (40% AH) vault swipes matching the ~30% mole after-hours profile, including after-hours activity on leak days D06 and D11, while e24 shows a benign 2/19 (11% AH) profile. Meanwhile, e12 exhibits the dominant TOP AH SPIKE of 26/47 (55% AH) and e28 shows ELEVATED AH of 8/24 (33% AH), but both are 100% cleared by Exhibit 3 because e12 held zero of the leaked DOC-IDs and e28 lacked four of the five, confirming e12 as the primary framed decoy and e28 as a secondary decoy spike.
- **`hard_4`** (conf `0.99`, dept `Engineering`): Exhibit 2 reveals three leaked canary memos: doc c1-2 (variant B, surfaced Day 04), doc c10 (variant A, surfaced Day 13), and doc c14 (variant B, surfaced Day 17). Cross-referencing Exhibit 3's Canary Distribution Matrix shows that only e08-e15 received c1-2, and among all 40 staff, e11 (Engineering, CLR-2) is the sole employee issued all three leaked documents (c1-2, c10, c14). Furthermore, e11's assigned variants (c1-2:B, c10:A, c14:B) match all three intercepted watermarks 100%. Exhibit 1 corroborates e11's mole profile with elevated self after-hours vault access (6/26 swipes, 23% AH) preceding each leak window (including AH swipes on D03, D08, D14, D16, and D17). Conversely, e31 (Sales) displays the dominant TOP AH SPIKE in Exhibit 1 (17/34 swipes, 50% AH) but is completely cleared by Exhibit 3 because e31 was never issued c1-2 (and held non-matching variants c10:B and c14:A), identifying e31 as the primary framed decoy.
