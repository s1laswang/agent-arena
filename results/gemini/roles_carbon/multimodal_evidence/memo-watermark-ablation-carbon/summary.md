# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`medium`, seeds `[3, 4, 5]`)
- Commit: `8df685ee057904bac413d35304f389066aa2b78f`
- Timestamp: `2026-11-14T13:50:01+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_memo_vision_ablation.py --tier medium --seeds 3,4,5 --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/memo-watermark-ablation-carbon`
- Episodes per condition: `3` (3 conditions x 3 seeds = 9 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `16` (`4` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=16`, `in=30464`, `out=2085`, `thinking=1367`, `cached=0`, `cost_usd=0.095448`, `latency_s=175.62`

## Paired 3-Condition Comparison (`medium` seeds `[3, 4, 5]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.6933 | 100.0% | 3/3 | 7.67 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.0000 | 0.0% | 0/3 | n/a (horizon) |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.6933 | 100.0% | 3/3 | 7.67 |

- Multimodal gain over blind ablation: `+0.6933`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.6933` vs `+0.6933`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 3 | `+0.6000` (`e14`, d9, P=1.00) | `+0.0000` (`none`, d14, P=0.39) | `+0.6000` (`e14`, d9, P=1.00) | 8 | 8/8 |
| 4 | `+0.6900` (`e17`, d8, P=1.00) | `+0.0000` (`none`, d14, P=0.53) | `+0.6900` (`e17`, d8, P=1.00) | 5 | 5/5 |
| 5 | `+0.7900` (`e14`, d6, P=1.00) | `+0.0000` (`none`, d14, P=0.59) | `+0.7900` (`e14`, d6, P=1.00) | 3 | 3/3 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 3 | `d1-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_3_d1-1.png` | 880x620 | 31180 | `a0b100fac001becf65f29f58035663aeeda41fc843f65d0ae2df21f7d9fa0683` |
| 3 | `d2-1` | 5 | `NONE` | `NONE` | YES | `memos/seed_3_d2-1.png` | 880x620 | 31504 | `77d40aded4a2c9cb990dab2a0f0147bf25bb5e5651927e605fc0fe457faa5e7f` |
| 3 | `d3-3` | 5 | `NONE` | `NONE` | YES | `memos/seed_3_d3-3.png` | 880x620 | 31454 | `608cafe7f5be31b9edf65c59d1db85d7e6bdcc1df0c49fe4cc809dfd954da186` |
| 3 | `d4-2` | 6 | `NONE` | `NONE` | YES | `memos/seed_3_d4-2.png` | 880x620 | 31774 | `6c4e0230211506474abb08e5cc7ed37347e06d16a1ed1eb06ff2839a18cfd0bb` |
| 3 | `d5-2` | 7 | `NONE` | `NONE` | YES | `memos/seed_3_d5-2.png` | 880x620 | 31692 | `f9621796b91b6cbd2d124e88cabef231f9fba1e5559e42dca6838d61ac914630` |
| 3 | `d4-1` | 8 | `NONE` | `NONE` | YES | `memos/seed_3_d4-1.png` | 880x620 | 31496 | `d347447abbe4284b92c1752eb6fd59fea3693f4a8b8dea7de28084a4d83e86c3` |
| 3 | `d7-1` | 8 | `NONE` | `NONE` | YES | `memos/seed_3_d7-1.png` | 880x620 | 31530 | `4dedeed3162bc2c25ac48847831f9dd97b86a4c79870120ebc4339981be53bca` |
| 3 | `c6` | 9 | `A` | `A` | YES | `memos/seed_3_c6.png` | 880x620 | 30599 | `c43d3b859314d51138baff0dcee91ed7acc2e2fa2e80f311c03ecc364e538ecc` |
| 4 | `d1-3` | 3 | `NONE` | `NONE` | YES | `memos/seed_4_d1-3.png` | 880x620 | 31563 | `5d0b706017bf15556149497b7629eb3ea6809901aad38b19f710456b46902b18` |
| 4 | `d1-2` | 6 | `NONE` | `NONE` | YES | `memos/seed_4_d1-2.png` | 880x620 | 31642 | `557ee6b42cbc2783bf92caa95619fedf8029a8ba736af6c6d804f4e1941d1217` |
| 4 | `c3` | 6 | `C` | `C` | YES | `memos/seed_4_c3.png` | 880x620 | 30715 | `8270e7d946e66a4551499d71e7f0b404e85fe972fdebfa29d0b8b50391f08829` |
| 4 | `c5` | 8 | `C` | `C` | YES | `memos/seed_4_c5.png` | 880x620 | 30601 | `f45878a0fd20b1a0626d78696c9335293bb9e47ffb7c28a5e2f45f3ec2aab24d` |
| 4 | `d6-1` | 8 | `NONE` | `NONE` | YES | `memos/seed_4_d6-1.png` | 880x620 | 31764 | `54f4b455f138a7721c233649cb026fa0fb917898ff17b1f56a888018867e2d6f` |
| 5 | `d2-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_5_d2-1.png` | 880x620 | 31612 | `f1f215ef1d4514386098885026dcc5b8424e89555981130913bf51e67f9141ac` |
| 5 | `c3` | 5 | `C` | `C` | YES | `memos/seed_5_c3.png` | 880x620 | 30579 | `9ca31bdc10ab808bdd8d3d535a2a2c1bed1d3de8478e5d9036a85226ee275538` |
| 5 | `d1-1` | 6 | `NONE` | `NONE` | YES | `memos/seed_5_d1-1.png` | 880x620 | 31204 | `c0a4f499cd31afde8a42b7addb3d3f9ac4e981b2c00c0e8eb0a56b42788131c6` |
