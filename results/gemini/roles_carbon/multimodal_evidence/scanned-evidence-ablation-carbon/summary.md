# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`medium`, seeds `[0, 1, 2, 3, 4, 5]`)
- Commit: `48baa20e791717f9a33d032efb7f06fda68d636a`
- Timestamp: `2026-11-14T17:06:23+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_memo_vision_ablation.py --tier medium --seeds 0,1,2,3,4,5 --model gemini-4-carbon --thinking-level LOW --out results/gemini/roles_carbon/multimodal_evidence/scanned-evidence-ablation-carbon`
- Episodes per condition: `6` (3 conditions x 6 seeds = 18 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `37` (`10` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=37`, `in=70448`, `out=4812`, `thinking=0`, `cached=0`, `cost_usd=0.189016`, `latency_s=260.25`

## Paired 3-Condition Comparison (`medium` seeds `[0, 1, 2, 3, 4, 5]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.6683 | 100.0% | 6/6 | 8.17 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.0000 | 0.0% | 0/6 | n/a (horizon) |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.6683 | 100.0% | 6/6 | 8.17 |

- Multimodal gain over blind ablation: `+0.6683`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.6683` vs `+0.6683`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 0 | `+0.7400` (`e05`, d7, P=1.00) | `+0.0000` (`none`, d14, P=0.43) | `+0.7400` (`e05`, d7, P=1.00) | 5 | 5/5 |
| 1 | `+0.3900` (`e02`, d14, P=1.00) | `+0.0000` (`none`, d14, P=0.37) | `+0.3900` (`e02`, d14, P=1.00) | 12 | 12/12 |
| 2 | `+0.8000` (`e09`, d5, P=1.00) | `+0.0000` (`none`, d14, P=0.39) | `+0.8000` (`e09`, d5, P=1.00) | 4 | 4/4 |
| 3 | `+0.6000` (`e14`, d9, P=1.00) | `+0.0000` (`none`, d14, P=0.39) | `+0.6000` (`e14`, d9, P=1.00) | 8 | 8/8 |
| 4 | `+0.6900` (`e17`, d8, P=1.00) | `+0.0000` (`none`, d14, P=0.53) | `+0.6900` (`e17`, d8, P=1.00) | 5 | 5/5 |
| 5 | `+0.7900` (`e14`, d6, P=1.00) | `+0.0000` (`none`, d14, P=0.59) | `+0.7900` (`e14`, d6, P=1.00) | 3 | 3/3 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 0 | `d1-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_0_d1-1.png` | 880x620 | 31180 | `a0b100fac001becf65f29f58035663aeeda41fc843f65d0ae2df21f7d9fa0683` |
| 0 | `d1-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_0_d1-2.png` | 880x620 | 31451 | `eecb1382550b0304e851573c661b373bcdcedfc51ee974df63dd2f58f1bbca14` |
| 0 | `c3` | 6 | `C` | `C` | YES | `memos/seed_0_c3.png` | 880x620 | 30715 | `8270e7d946e66a4551499d71e7f0b404e85fe972fdebfa29d0b8b50391f08829` |
| 0 | `d3-3` | 7 | `NONE` | `NONE` | YES | `memos/seed_0_d3-3.png` | 880x620 | 31414 | `8aed0c40892ac3e613bccd592bdef8bef40b1438db9b135dbc3dc46b112b7f1b` |
| 0 | `c5` | 7 | `B` | `B` | YES | `memos/seed_0_c5.png` | 880x620 | 31029 | `55b294df9f6b6bb302dd64165f48d097913a7e91d00b35683027b32e8d6d988a` |
| 1 | `d1-2` | 2 | `NONE` | `NONE` | YES | `memos/seed_1_d1-2.png` | 880x620 | 31460 | `7993102f1f38b87fd1d95144602d64430ca10c0f21ac9347e00b72d9c002f945` |
| 1 | `d2-4` | 3 | `NONE` | `NONE` | YES | `memos/seed_1_d2-4.png` | 880x620 | 31747 | `c1a8e82489c449cb9d4e096bb0cc50e6e9661a5ce4a0df7b29187a08ffb0d23f` |
| 1 | `d2-2` | 5 | `NONE` | `NONE` | YES | `memos/seed_1_d2-2.png` | 880x620 | 31430 | `b93d682365f8f32425967cb729bd0ce3c87c541eb579cc9c163ea2300da6fc98` |
| 1 | `c2` | 5 | `A` | `A` | YES | `memos/seed_1_c2.png` | 880x620 | 30344 | `94fc4898a04551488bd23618ede40d6f1372e8e46b3aed794144ae084bec761c` |
| 1 | `d4-2` | 8 | `NONE` | `NONE` | YES | `memos/seed_1_d4-2.png` | 880x620 | 31801 | `7014eb3b200f95f4985c667c73a6fa095f4b6dba3140784d9c2b245a6220798b` |
| 1 | `d7-2` | 10 | `NONE` | `NONE` | YES | `memos/seed_1_d7-2.png` | 880x620 | 31514 | `492b39891a6f07ce6e949f38e55c955ed39eaf955a1e7d2b80c0f4961590dcc1` |
| 1 | `d7-1` | 10 | `NONE` | `NONE` | YES | `memos/seed_1_d7-1.png` | 880x620 | 31160 | `fe6a36d7d8ff3ac61d31bba5c5d3b4483befd971161ba55bec1337aeb2330b8c` |
| 1 | `d9-4` | 10 | `NONE` | `NONE` | YES | `memos/seed_1_d9-4.png` | 880x620 | 31572 | `b3fa7476ef9b6e18c3769abfadc6c44ff96213973a0d081cc9e5707c312f82ee` |
| 1 | `d8-4` | 11 | `NONE` | `NONE` | YES | `memos/seed_1_d8-4.png` | 880x620 | 31192 | `4ec529dffa9ab3683330e9bc5432c849379b0c6965f67dad236c127c2ad03fc4` |
| 1 | `d9-2` | 13 | `NONE` | `NONE` | YES | `memos/seed_1_d9-2.png` | 880x620 | 31748 | `4381931e796f3dc1e074bdfb5a3f491290ee2eb060bb9210686a0affaca1abec` |
| 1 | `c10` | 14 | `A` | `A` | YES | `memos/seed_1_c10.png` | 880x620 | 30155 | `1512b6aec65edd85400a95dc791a8dc41d2d94c7ea33315478014a244b0e21cf` |
| 1 | `d13-1` | 14 | `NONE` | `NONE` | YES | `memos/seed_1_d13-1.png` | 880x620 | 31192 | `f878623e0d01268106547f4ef3ff821924476f5cd425e3b0fc325c59030c3445` |
| 2 | `c1` | 2 | `A` | `A` | YES | `memos/seed_2_c1.png` | 880x620 | 30099 | `d39ab8604a1e525fa85270a3f2a7a2ae6a40b2e4ebdb69756282271389f47939` |
| 2 | `d2-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_2_d2-2.png` | 880x620 | 31556 | `76cbbddfbe8ce7316c0db980877531ad6862cced217fb11ee316d664eb7802bb` |
| 2 | `c3` | 5 | `A` | `A` | YES | `memos/seed_2_c3.png` | 880x620 | 30405 | `606bf654e6b1678cc40124982e8bbc2614b6c505405cf3f6fc28e78665c4e3c2` |
| 2 | `d4-1` | 5 | `NONE` | `NONE` | YES | `memos/seed_2_d4-1.png` | 880x620 | 31335 | `8158d2078ac0bb12c82b50cdfd8f0915dae8e1912b606950e5c91fde4fbac148` |
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
