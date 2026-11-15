# Role 6 (multimodal_evidence) - Multi-Image Composite Incident Dossier Run

## Provenance
- Role: `multimodal_evidence` (`multi_image_incident_dossier`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`6` composite dossiers across `medium` seeds `6,7,8` and `hard` seeds `5,6,7`)
- Commit: `a6b5a80e7a47d2bdf91514c57ca08834921762eb`
- Timestamp: `2026-11-14T23:58:33+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_incident_dossier.py --worlds medium:6,medium:7,medium:8,hard:5,hard:6,hard:7 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/multi-image-dossier-med6to8-hard5to7-carbon`
- Composite dossiers evaluated (`episode_count`): `6`
- Images read by model (`Part.from_bytes`, `image/png`, `3` distinct PNGs per single call): `18`
- Token usage: `calls=6`, `in=27055`, `out=2345`, `thinking=25336`, `cached=0`, `cost_usd=0.330920`, `latency_s=316.60`

## Multi-Image Fusion vs Single-Image Baselines
| Approach | Inputs Available | Top-1 Mole Accuracy | Top-1 Framed Decoy Accuracy | Avoided Framing Trap |
|---|---|---|---|---|
| **Gemini 3-Image Joint Dossier (`gemini-4-carbon`)** | **Exhibit 1 + Exhibit 2 + Exhibit 3 (`3` PNGs in 1 call)** | **4/6 (66.7%)** | **5/6 (83.3%)** | **6/6 (100.0%)** |
| Exhibit 1 Only (Naive After-Hours Swipe Pick) | `badge_raster` PNG only (no canary roster, no leak feed) | 0/6 (0.0%) | - | 1/6 (16.7%) |
| Exhibit 2 Only (Leaked Memo Scans Only) | `leaked_memo_scans` PNG only (no employee IDs) | 0/6 (0.0%) | 0/6 (0.0%) | - |
| Exhibit 3 Only (Static Floorplan + Canary Matrix) | `org_canary_map` PNG only (no leak outcomes, uniform `1/N` prior = 3.8%) | 0/6 (0.0%) | 0/6 (0.0%) | - |

- Exhibit 2 visual watermark scan readout exact match (`DOC-ID` + `COPY-CODE`): `12/12` (`100.0%`)
- Exhibit 3 floorplan department attribution accuracy: `4/6` (`66.7%`)

## Per-World Cross-Image Breakdown
| World | True Mole (Dept) | True Decoy | Img-1 Naive Pick | Leaked Canaries (Img 2) | Pred Mole Top-3 | Pred Decoy | Mole Top-1 | Decoy Top-1 |
|---|---|---|---|---|---|---|---|---|
| `medium_6` | `e17` (Engineering) | `e19` | `e19` | `c4=C, c6=C, c9=C` | `e17` | `e19` | YES | YES |
| `medium_7` | `e09` (Finance) | `e03` | `e03` | `` | `e10, e06, e18` | `e03` | NO | YES |
| `medium_8` | `e02` (Sales) | `e01` | `e05` | `c1=C` | `e02` | `e05, e01` | YES | NO |
| `hard_5` | `e27` (Finance) | `e04` | `e04` | `c12-2=C, c14-2=A` | `e27, e12, e17` | `e04` | YES | YES |
| `hard_6` | `e34` (Research) | `e20` | `e20` | `c3=A, c9-2=A` | `e34, e39` | `e20, e11` | YES | YES |
| `hard_7` | `e37` (Sales) | `e12` | `e12` | `c3=B, c12-2=B, c14-2=B, c18=B` | `e32, e37` | `e12` | NO | YES |

## Rendered Composite Dossier PNGs (18 Files)
| World | Exhibit | Path | Dimensions | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `medium_6` | `badge_raster` | `dossiers/badge_raster_seed_medium_6.png` | 1274x996 | 109867 | `c55b8ee19531299a45c172f99bd769bf7bd58859a368e0b438df632697c060d3` |
| `medium_6` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_6.png` | 1510x1126 | 84534 | `428c2ea7a816d06c9425b99c6fa5fff3006f29c8c4d0adfee2e262c61a4f5376` |
| `medium_6` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_6.png` | 1320x1204 | 125746 | `6b555b05f2884f9dfe1f14a7021e2a88804a324128e303bbb6e38f769cd95986` |
| `medium_7` | `badge_raster` | `dossiers/badge_raster_seed_medium_7.png` | 1274x996 | 111514 | `53f05fe146cb3eca010e0576230259e694112057c5e4a0572b84eac3f896ecaf` |
| `medium_7` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_7.png` | 1510x644 | 40654 | `b54052b830d7bec9555f204862be43e08c99b3f84df08fbb9efd45b4649022fd` |
| `medium_7` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_7.png` | 1320x1232 | 126224 | `a1a0ffdbf5f0d61b0a19dd17210864970d494e789c96b91a96b16f4432c61275` |
| `medium_8` | `badge_raster` | `dossiers/badge_raster_seed_medium_8.png` | 1274x996 | 109735 | `58b01eaf6a8ccbe452999144967256ea1e889cf030490d55f99b50502d2d90d6` |
| `medium_8` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_medium_8.png` | 1510x644 | 51511 | `a5213ceac6fcdbc2e5afa41b723aa570dffb9db566fb8900e1b1c09533c9bdfd` |
| `medium_8` | `org_canary_map` | `dossiers/org_canary_map_seed_medium_8.png` | 1320x1204 | 125317 | `ad7374aaad5e8e2f8e5951cde29d0817cfec5858727e0e4c40b9e5b52aea5416` |
| `hard_5` | `badge_raster` | `dossiers/badge_raster_seed_hard_5.png` | 1530x1636 | 199538 | `f063b24ea5ba64211a9f5bb11024a0c007efc85b1c26f1d6988893e1a6d76875` |
| `hard_5` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_5.png` | 1510x644 | 66526 | `e7479ca2bfc611a8301d413eb50e283bb1bac1763d98efb02f0a00b6134e79e0` |
| `hard_5` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_5.png` | 2144x1990 | 240568 | `50921b9347d745e26b12c17b7be6d4de3126c323344de1cf79133f57352c82f4` |
| `hard_6` | `badge_raster` | `dossiers/badge_raster_seed_hard_6.png` | 1530x1636 | 200728 | `0f20cd5c63eab64f5d742870dc8b7c899000f0b39483861470d9c0e87aa0a18f` |
| `hard_6` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_6.png` | 1510x644 | 54672 | `adb912adc770866fb6dbe885a6f1c12c5b24b613a3b34f5ee34b042f099e8e73` |
| `hard_6` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_6.png` | 2144x1962 | 239725 | `5ee0c6a98fe70b84b573cec95a9a41a5488213c97d5f7a6d78c0fe4c24d24720` |
| `hard_7` | `badge_raster` | `dossiers/badge_raster_seed_hard_7.png` | 1530x1636 | 194319 | `ce7c8e115d5df457fa1d4a93d536fd5e868c97f1f904b97a7c27434b834b5014` |
| `hard_7` | `leaked_memo_scans` | `dossiers/leaked_memo_scans_seed_hard_7.png` | 1510x1126 | 90109 | `e6c39dc41216cee1f8dc2c47ac79269dbecc2d4102449f33b30d02a3059cb8c6` |
| `hard_7` | `org_canary_map` | `dossiers/org_canary_map_seed_hard_7.png` | 2144x1962 | 240074 | `0c1bc955616946bd0037319e5beea120cf9ddacf0e53188ea19fb01bfc7cfad2` |

## Cross-Image Forensic Reasoning Excerpts
- **`medium_6`** (conf `0.99`, dept `Engineering`): Exhibit 2 shows three intercepted leaked canary memos: (c4, C) surfaced Day 07, (c6, C) surfaced Day 07, and (c9, C) surfaced Day 11, each confirmed by COPY-CODE C stamps, 3 header segments, and 3/8 active footer ticks. Cross-referencing Exhibit 3's Canary Distribution Matrix and Issued Variants Roster reveals that e17 (desk ENG-05 in the Engineering zone) is the sole employee issued c4:C, c6:C, and c9:C, providing an exact 3-of-3 watermark match. Exhibit 1 corroborates e17's moderate mole swipe profile (2/11 or 18% after-hours, with vault access preceding both the Day 07 and Day 11 leaks), while exposing e19 (15/21 or 71% after-hours, flagged TOP AH SPIKE) as the framed decoy since Exhibit 3 shows e19 holds c4:B, c8:B, and c10:A and matches none of the leaked variants.
- **`medium_7`** (conf `0.62`, dept `Engineering`): Exhibit 2 reports zero surfaced watermarked canary scans through Day 13 (DOC-ID: NONE, 0/8 active footer ticks), leaving Exhibit 3's 3-canary-per-employee roster (such as e10's c3:C, c7:C, c10:C) untriggered on the external leak feed. Cross-referencing Exhibit 1's vault telemetry separates the framed decoy from active high-volume vault users: e03 (Legal, LEG-01) exhibits the dominant TOP AH SPIKE at 10/25 swipes (40% after-hours) atop a normal 15 regular daytime swipes, matching the ~50% concentrated fake after-hours framing signature injected onto an innocent decoy. Among remaining staff, e10 (Engineering, ENG-02) has the highest total vault volume at 23 swipes across 12 of 13 days with 3/23 (13%) after-hours swipes closely matching the expected ~15% mole self-after-hours profile, outranking secondary high-volume candidate e06 (Finance, FIN-03, 22 swipes but only 1/22 or 5% after-hours) and e18 (Sales, SAL-06, 17 swipes with 3/17 or 18% after-hours).
- **`medium_8`** (conf `0.98`, dept `Sales`): Exhibit 2 shows one intercepted leaked canary scan for doc_id c1 (surfaced Day 02) carrying 3 header segments, COPY-CODE C, and 3/8 active footer ticks (variant C). Intersecting (c1, C) against Exhibit 3's Static Canary Distribution Matrix uniquely identifies e02 (issued c1:C, c7:B, c10:C), who is assigned to desk SAL-01 in the Sales department zone; all other c1 holders received variants A (e00, e03) or B (e01, e04). Cross-referencing Exhibit 1 confirms e02 maintains a moderate vault swipe profile (1/10 after-hours, 10% AH, including vault access prior to the Day 02 leak is not required for static pre-issued canaries or masked by low framing), while e05 (5/12, 42% AH) and secondary spike e01 (4/11, 36% AH) exhibit heavy red after-hours framing anomalies despite holding neither c1 (for e05) nor variant C (for e01), marking e05 as the primary framed decoy.
- **`hard_5`** (conf `0.95`, dept `Finance`): Exhibit 2 reveals two leaked canary memos: doc c12-2 with COPY-CODE C (surfaced Day 17) and doc c14-2 with COPY-CODE A (surfaced Day 18). Intersecting these document IDs in Exhibit 3 clears 32 employees and leaves 8 staff who received both c12-2 and c14-2 (e02, e07, e12, e17, e22, e27, e32, e37). Among them, only e27 (Finance, clearance CLR-2) holds exact matching variants for both leaks (c12-2:C and c14-2:A), whereas runner-up candidates e12, e17, and e22 match only one variant each. Exhibit 1 corroborates e27 with an elevated 7/24 (29% after-hours) vault swipe profile consistent with the 30% mole baseline, while isolating e04 (19/40, 48% after-hours, flagged TOP AH SPIKE) as the primary framed decoy since Exhibit 3 confirms e04 received neither c12-2 nor c14-2.
- **`hard_6`** (conf `0.98`, dept `Research`): Exhibit 2 shows two intercepted leaked canary memos: DOC-ID c3 with COPY-CODE A (surfaced Day 07) and DOC-ID c9-2 with COPY-CODE A (surfaced Day 11). Intersecting c3 and c9-2 in Exhibit 3's Canary Distribution Matrix clears 38 of 40 employees, leaving only e34 (Research, CLR-2) and e39 (Engineering, CLR-3) as recipients of both documents. Between them, e34 was issued exact matching variants c3:A and c9-2:A (~38x variant likelihood advantage over e39, who held c3:C and c9-2:A). Cross-referencing Exhibit 1 confirms e34 exhibits a strong self after-hours profile (13/22 swipes, 59% AH, including after-hours vault access immediately preceding both Day 07 and Day 11 leaks) versus e39's 5/26 (19% AH). Meanwhile, e20 (16/37 swipes, 43% AH, TOP AH SPIKE) and e11 (9/27 swipes, 33% AH, ELEVATED AH) held neither c3 nor c9-2 in Exhibit 3, isolating e20 as the primary framed decoy and e11 as secondary framing scatter.
- **`hard_7`** (conf `0.68`, dept `Research`): Exhibit 2 shows four leaked canary scans all bearing 2-segment header bars, 2/8 active footer ticks, and COPY-CODE B: (c3, B) on Day 06, (c12-2, B) on Day 15, (c14-2, B) on Day 18, and (c18, B) on Day 20. Intersecting {c3, c12-2, c14-2, c18} against Exhibit 3's Canary Distribution Matrix eliminates 38 of 40 staff, leaving only e32 (Research, CLR-2: c3:B, c12-2:A, c14-2:B, c18:B) and e37 (Sales, CLR-1: c3:A, c12-2:B, c14-2:B, c18:B), each matching 3 of 4 leaked variants with 1 noisy flip. Cross-referencing Exhibit 1 resolves the tie in favor of e32, who shows higher vault activity and after-hours swipe rate (3/21, 14% AH across D07, D14, D20) than e37 (2/19, 11% AH on D01, D03), while isolating e12 (19/39, 49% AH, TOP AH SPIKE) as the primary framed decoy cleared by Exhibit 3 because e12 was never issued c3 and held variant C on c12-2, c14-2, and c18.
