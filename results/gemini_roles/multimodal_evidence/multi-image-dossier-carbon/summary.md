# Role 6 (multimodal_evidence) - Multi-Image Composite Incident Dossier Run

## Provenance
- Role: `multimodal_evidence` (`multi_image_incident_dossier`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`5` composite dossiers across `medium` seeds `0,1,2` and `hard` seeds `0,1`)
- Commit: `5ee0741946388cfaea3c8d287aaf0c7586a7509c`
- Timestamp: `2026-11-14T17:22:19+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_incident_dossier.py --worlds medium:0,medium:1,medium:2,hard:0,hard:1 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/multi-image-dossier-carbon`
- Composite dossiers evaluated (`episode_count`): `5`
- Images read by model (`Part.from_bytes`, `image/png`, `3` distinct PNGs per single call): `15`
- Token usage: `calls=5`, `in=22538`, `out=2020`, `thinking=10910`, `cached=0`, `cost_usd=0.174376`, `latency_s=181.79`

## Multi-Image Fusion vs Single-Image Baselines
| Approach | Inputs Available | Top-1 Mole Accuracy | Top-1 Framed Decoy Accuracy | Avoided Framing Trap |
|---|---|---|---|---|
| **Gemini 3-Image Joint Dossier (`gemini-4-carbon`)** | **Exhibit 1 + Exhibit 2 + Exhibit 3 (`3` PNGs in 1 call)** | **5/5 (100.0%)** | **5/5 (100.0%)** | **5/5 (100.0%)** |
| Exhibit 1 Only (Naive After-Hours Swipe Pick) | `badge_raster` PNG only (no canary roster, no leak feed) | 0/5 (0.0%) | - | 0/5 (0.0%) |
| Exhibit 2 Only (Leaked Memo Scans Only) | `leaked_memo_scans` PNG only (no employee IDs) | 0/5 (0.0%) | 0/5 (0.0%) | - |
| Exhibit 3 Only (Static Floorplan + Canary Matrix) | `org_canary_map` PNG only (no leak outcomes, uniform `1/N` prior = 4.0%) | 0/5 (0.0%) | 0/5 (0.0%) | - |

- Exhibit 2 visual watermark scan readout exact match (`DOC-ID` + `COPY-CODE`): `15/15` (`100.0%`)
- Exhibit 3 floorplan department attribution accuracy: `5/5` (`100.0%`)

## Per-World Cross-Image Breakdown
| World | True Mole (Dept) | True Decoy | Img-1 Naive Pick | Leaked Canaries (Img 2) | Pred Mole Top-3 | Pred Decoy | Mole Top-1 | Decoy Top-1 |
|---|---|---|---|---|---|---|---|---|
| `medium_0` | `e05` (Sales) | `e19` | `e19` | `c6=A, c11=A` | `e05` | `e19` | YES | YES |
| `medium_1` | `e02` (Sales) | `e00` | `e00` | `c7=B, c10=C` | `e02` | `e00, e17` | YES | YES |
| `medium_2` | `e09` (Engineering) | `e05` | `e05` | `c6=B, c9=C` | `e09` | `e05` | YES | YES |
| `hard_0` | `e38` (Sales) | `e14` | `e14` | `c3=B, c6-2=B, c10-2=C, c12=A` | `e38, e33` | `e14, e31` | YES | YES |
| `hard_1` | `e33` (Legal) | `e11` | `e11` | `c5=C, c6-2=B, c10-2=C, c12=C, c16-2=B` | `e33, e38, e03` | `e11` | YES | YES |

## Rendered Composite Dossier PNGs (15 Files)
| World | Exhibit | Path | Dimensions | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `medium_0` | `badge_raster` | `dossiers/badge_raster_seed_medium_0.png` | 1274x996 | 109929 | `5db8875ab1b1e2b4ce6bacf86b5ab740db0992c86e2153ca2017b2aeb6ace58a` |
| `medium_0` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_0.png` | 1510x644 | 53943 | `896e9ee63e040a075d890978f14a9244f76af3a0ed307aaf7117164bd63f19b6` |
| `medium_0` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_0.png` | 1320x1232 | 125479 | `2ce378a08ab2e1c4e89b635ccc3bc525fea38a31ccc26a01adcbb1564b12626e` |
| `medium_1` | `badge_raster` | `dossiers/badge_raster_seed_medium_1.png` | 1274x996 | 112359 | `b6ce7ba8544a556a205a7974f97e35631695cda3a66a94e901d972bac2f1079b` |
| `medium_1` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_1.png` | 1510x644 | 66000 | `58f9bfa13f0197a0dcce7cd53b406331cad916c2d67ee9765ffdf248d11f0224` |
| `medium_1` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_1.png` | 1320x1232 | 125551 | `046d7a88994859d7ac4f7afb454e87e43f12544db43413c00be0320f343eccee` |
| `medium_2` | `badge_raster` | `dossiers/badge_raster_seed_medium_2.png` | 1274x996 | 110767 | `e10c7581f4333d8f3066da8826afdee9ec7079b89ad816c504bee81be456bbc2` |
| `medium_2` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_2.png` | 1510x644 | 66972 | `3238077acc5e98910db95908d91ba9cf6a953c643fe2c9404ed14cf5b3eee5bf` |
| `medium_2` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_2.png` | 1320x1232 | 124977 | `1e455abcbd3504144a0de8f827266b81752c88d4478cbef75deb5d241d2e9ac9` |
| `hard_0` | `badge_raster` | `dossiers/badge_raster_seed_hard_0.png` | 1530x1636 | 200692 | `5340a659567d00bf835064f64708780404ae922b644b03cb326868af009aefc6` |
| `hard_0` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_0.png` | 1510x1126 | 101200 | `a2d5f4f744bb89598f5e46ae65a2374f69b645cd3ab46f180a6aea8f00958e31` |
| `hard_0` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_0.png` | 2144x1934 | 237373 | `938f8a463bb697a40e7f9bc29afacaf4a663ff924e1dad68698e703d913c48ba` |
| `hard_1` | `badge_raster` | `dossiers/badge_raster_seed_hard_1.png` | 1530x1636 | 201215 | `696359194c4b794af9f3d133470b3057054f7e94d998a64ec5fbb4a587b19855` |
| `hard_1` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_1.png` | 2252x1126 | 121545 | `0bcfd69115f241a9467698819658d0410d3bb7052d616eea912529650949bc27` |
| `hard_1` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_1.png` | 2144x1962 | 237559 | `8138c26581b5d20b543d1dbed87a470f8496b1b23d103610a3ca49777c38351f` |

## Cross-Image Forensic Reasoning Excerpts
- **`medium_0`** (conf `0.99`, dept `Sales`): Exhibit 2 shows two intercepted leaked canary memos: DOC-ID c6 with COPY-CODE A (surfaced Day 09, 1 header segment, footer tick A:1) and DOC-ID c11 with COPY-CODE A (surfaced Day 13, 1 header segment, footer tick A:1). Cross-referencing Exhibit 3's Canary Distribution Matrix shows c6:A was issued only to e01 and e05, while c11:A was issued only to e04, e05, and e12; their exact intersection uniquely identifies e05, assigned to desk SAL-02 in the Sales zone. Exhibit 1 confirms e05 accessed the vault regularly across D01-D13 (0/15 after-hours, consistent with never framing oneself), whereas e19 exhibits the extreme TOP AH SPIKE of 14/24 (58% after-hours) despite holding only c4:B, c8:B, and c10:A in Exhibit 3, confirming e19 is the framed decoy.
- **`medium_1`** (conf `0.99`, dept `Sales`): Exhibit 2 shows two intercepted leaked canary memos surfacing on Day 11: DOC-ID c7 with COPY-CODE B (2 header segments, 2/8 footer ticks) and DOC-ID c10 with COPY-CODE C (3 header segments, 3/8 footer ticks). Cross-referencing Exhibit 3's Canary Distribution Matrix reveals that e02 (assigned to desk SAL-01 in the Sales clearance zone, holding c1:C, c7:B, c10:C) is the sole employee issued both exact leaked variants (c7:B and c10:C). Exhibit 1 shows e02 with 6/12 (50%) after-hours vault swipes, whereas e00 exhibits the dominant TOP AH SPIKE of 9/21 (43% AH) and e17 shows an ELEVATED AH spike of 6/17 (35% AH); because Exhibit 3 clears both e00 (c1:A, c5:C, c9:B) and e17 (c4:C, c6:C, c9:C) of holding either leaked document, e00 is the primary framed decoy and e17 absorbed secondary framing noise.
- **`medium_2`** (conf `0.98`, dept `Engineering`): Exhibit 2 shows two intercepted leaked canary memos: DOC-ID c6 with COPY-CODE B (2 header segments, 2/8 footer ticks, surfaced Day 08) and DOC-ID c9 with COPY-CODE C (3 header segments, 3/8 footer ticks, surfaced Day 11). Cross-referencing these exact (doc_id, variant) pairs against Exhibit 3's Canary Distribution Matrix shows c6:B was issued only to e09 and e13, while c9:C was issued only to e09, e16, and e17, uniquely identifying e09 (assigned to Engineering desk ENG-04) as the sole employee holding both leaked canary variants (c2:C, c6:B, c9:C). Exhibit 1 corroborates e09's moderate mole swipe profile (4/18 or 22% after-hours swipes, including anomalies on D08 and D10 aligned with the Day 08 and Day 11 leaks), whereas e05 exhibits the dominant TOP AH SPIKE (9/24 or 38% after-hours swipes) but holds c2:B, c6:A, and c11:A in Exhibit 3, proving e05 is an innocent framed decoy.
- **`hard_0`** (conf `1.00`, dept `Sales`): Exhibit 2 shows four leaked canary memos: c3 (variant B, Day 05), c6-2 (variant B, Day 09), c10-2 (variant C, Day 13), and c12 (variant A, Day 15). Intersecting these four DOC-IDs in Exhibit 3 clears 38 of 40 employees, leaving only e38 (Sales, CLR-1) and e33 (Legal, CLR-2) as recipients of all four documents. Across the four leaked memos, e38 matches 4/4 watermark variants (c3:B, c6-2:B, c10-2:C, c12:A) whereas e33 matches only 2/4 (mismatching c3:C and c12:C), giving >1400:1 variant odds in favor of e38. Exhibit 1 corroborates e38 with elevated after-hours activity (4/24 swipes, 17% AH) and vault access prior to every leak date, versus 1/19 (5% AH) for e33. Meanwhile, Exhibit 1's top after-hours spike e14 (12/31, 39% AH, TOP AH SPIKE) and secondary spike e31 (9/31, 29% AH, ELEVATED AH) held zero leaked canaries in Exhibit 3, confirming e14 as the primary framed decoy and e31 as an innocent secondary spike.
- **`hard_1`** (conf `0.97`, dept `Legal`): Exhibit 2 shows five leaked canary memos: (c5, C) and (c6-2, B) surfaced Day 10, (c10-2, C) Day 13, (c12, C) Day 15, and (c16-2, B) Day 19. Intersecting those five DOC-IDs in Exhibit 3 eliminates 32 staff and leaves eight holders (e03, e08, e13, e18, e23, e28, e33, e38). Among them, e33 (Legal, CLR-1) is the sole 5/5 exact variant match (c5:C, c6-2:B, c10-2:C, c12:C, c16-2:B), giving ~38x higher odds than runner-up e38 (4/5 match, c12:A) and >1400x over e03 (3/5 match). Exhibit 1 corroborates e33 with 8/26 (31% AH) vault swipes matching the ~30% mole profile and pre-leak vault access prior to every leak day, while isolating e11 (18/32, 56% AH, TOP AH SPIKE) as the primary framed decoy since Exhibit 3 confirms e11 held zero of the leaked canaries.
