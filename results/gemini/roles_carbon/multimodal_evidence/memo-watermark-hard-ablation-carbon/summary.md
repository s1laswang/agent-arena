# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`hard`, seeds `[0, 1, 2, 3, 4]`)
- Commit: `c75a9393129a5ed65cc2b9bdba44972d99e1c61a`
- Timestamp: `2026-11-14T17:05:44+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_memo_vision_ablation.py --tier hard --seeds 0,1,2,3,4 --model gemini-4-carbon --thinking-level LOW --out results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-ablation-carbon`
- Episodes per condition: `5` (3 conditions x 5 seeds = 15 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `18` (`8` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=18`, `in=34272`, `out=2391`, `thinking=0`, `cached=0`, `cost_usd=0.092454`, `latency_s=134.28`

## Paired 3-Condition Comparison (`hard` seeds `[0, 1, 2, 3, 4]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.6720 | 100.0% | 5/5 | 7.00 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.4060 | 80.0% | 4/5 | 10.75 |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.6720 | 100.0% | 5/5 | 7.00 |

- Multimodal gain over blind ablation: `+0.2660`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.6720` vs `+0.6720`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 0 | `+0.6400` (`e38`, d9, P=0.95) | `+0.0000` (`none`, d21, P=0.69) | `+0.6400` (`e38`, d9, P=0.95) | 4 | 4/4 |
| 1 | `+0.6900` (`e33`, d7, P=0.99) | `+0.5500` (`e33`, d11, P=1.00) | `+0.6900` (`e33`, d7, P=0.99) | 3 | 3/3 |
| 2 | `+0.5800` (`e25`, d9, P=1.00) | `+0.3600` (`e25`, d16, P=0.90) | `+0.5800` (`e25`, d9, P=1.00) | 5 | 5/5 |
| 3 | `+0.7200` (`e29`, d5, P=0.91) | `+0.4000` (`e29`, d11, P=0.88) | `+0.7200` (`e29`, d5, P=0.91) | 3 | 3/3 |
| 4 | `+0.7300` (`e11`, d5, P=1.00) | `+0.7200` (`e11`, d5, P=1.00) | `+0.7300` (`e11`, d5, P=1.00) | 3 | 3/3 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 0 | `c1-2` | 3 | `A` | `A` | YES | `memos/seed_0_c1-2.png` | 880x620 | 30661 | `d0ed20849fe778390faf3efe843bc82b63186ff96816ce6da890cfa6eecf8661` |
| 0 | `d2-2` | 6 | `NONE` | `NONE` | YES | `memos/seed_0_d2-2.png` | 880x620 | 31575 | `708c3c9a7e83cd80674f7919254e465ae2e164c90f69dc912c30218031a1603a` |
| 0 | `d4-1` | 6 | `NONE` | `NONE` | YES | `memos/seed_0_d4-1.png` | 880x620 | 31452 | `8d01ae58f326efecb81274fc91be72e123933dfaedafff31147685d91cb1e1d1` |
| 0 | `d4-3` | 8 | `NONE` | `NONE` | YES | `memos/seed_0_d4-3.png` | 880x620 | 31867 | `9677b91b9442b76d992c3c71d2d12bc7c240471e55da9d13a7d5c1dd5a6d1afa` |
| 1 | `d2-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_1_d2-2.png` | 880x620 | 31385 | `de14c66f2dcbdc5ff0bbc2d0b5f057a00137d2e702a071939aa5581d69720f28` |
| 1 | `d1-3` | 5 | `NONE` | `NONE` | YES | `memos/seed_1_d1-3.png` | 880x620 | 31564 | `d47d9ac80de0756cc31f84434955f52485883e5ba2308bf7b96b7f487d8ddc1a` |
| 1 | `c3-2` | 7 | `B` | `B` | YES | `memos/seed_1_c3-2.png` | 880x620 | 31637 | `0c43754910ad65fef63afc4171369c5867c5e32636670fad3298fabae96b12ce` |
| 2 | `d1-3` | 3 | `NONE` | `NONE` | YES | `memos/seed_2_d1-3.png` | 880x620 | 31563 | `5d0b706017bf15556149497b7629eb3ea6809901aad38b19f710456b46902b18` |
| 2 | `d2-1` | 5 | `NONE` | `NONE` | YES | `memos/seed_2_d2-1.png` | 880x620 | 31504 | `77d40aded4a2c9cb990dab2a0f0147bf25bb5e5651927e605fc0fe457faa5e7f` |
| 2 | `c3-2` | 5 | `B` | `B` | YES | `memos/seed_2_c3-2.png` | 880x620 | 31698 | `8004b88c11eb8e272ea95f7254c69b438febd4de4d37917b3dd6320ed4329af7` |
| 2 | `c4-2` | 9 | `C` | `C` | YES | `memos/seed_2_c4-2.png` | 880x620 | 30958 | `3d164ec451ec7935d249914b64f0eaab203993e27044769b262d54ca45a31d47` |
| 2 | `c5` | 9 | `C` | `C` | YES | `memos/seed_2_c5.png` | 880x620 | 30567 | `dde6c580c40c8f3fbbf199446cd8f75494da7c65aa1c5a0b995b11ef6ba1e0c2` |
| 3 | `d1-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_3_d1-2.png` | 880x620 | 31617 | `43ac0787eaf5f098ad2a5daabd596d9380f56cb626b323527e9f081fbe4436bf` |
| 3 | `d1-3` | 5 | `NONE` | `NONE` | YES | `memos/seed_3_d1-3.png` | 880x620 | 31564 | `d47d9ac80de0756cc31f84434955f52485883e5ba2308bf7b96b7f487d8ddc1a` |
| 3 | `c2` | 5 | `B` | `B` | YES | `memos/seed_3_c2.png` | 880x620 | 31152 | `8c3e43a2ed0f4a90112b9fcbf8ccbf33b0d04c4067f0e23323f0ffbb917c3994` |
| 4 | `c1` | 4 | `B` | `B` | YES | `memos/seed_4_c1.png` | 880x620 | 30779 | `10fef79230c02538c0633e805842d5ee461728c4637108951e36a5a2d3770e6b` |
| 4 | `d2-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_4_d2-2.png` | 880x620 | 31385 | `de14c66f2dcbdc5ff0bbc2d0b5f057a00137d2e702a071939aa5581d69720f28` |
| 4 | `c3-2` | 5 | `B` | `B` | YES | `memos/seed_4_c3-2.png` | 880x620 | 31698 | `8004b88c11eb8e272ea95f7254c69b438febd4de4d37917b3dd6320ed4329af7` |
