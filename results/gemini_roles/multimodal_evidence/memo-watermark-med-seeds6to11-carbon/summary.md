# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`medium`, seeds `[6, 7, 8, 9, 10, 11]`)
- Commit: `85855affc476ed1f54e4197b4a38a8f7e08bdeff`
- Timestamp: `2026-11-14T23:07:45+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_memo_vision_ablation.py --tier medium --seeds 6,7,8,9,10,11 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/memo-watermark-med-seeds6to11-carbon`
- Episodes per condition: `6` (3 conditions x 6 seeds = 18 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `21` (`10` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=21`, `in=39984`, `out=2665`, `thinking=2119`, `cached=0`, `cost_usd=0.127808`, `latency_s=160.29`

## Paired 3-Condition Comparison (`medium` seeds `[6, 7, 8, 9, 10, 11]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.8033 | 100.0% | 6/6 | 6.00 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.0000 | 0.0% | 0/6 | n/a (horizon) |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.8033 | 100.0% | 6/6 | 6.00 |

- Multimodal gain over blind ablation: `+0.8033`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.8033` vs `+0.8033`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 6 | `+0.7900` (`e17`, d6, P=1.00) | `+0.0000` (`none`, d14, P=0.39) | `+0.7900` (`e17`, d6, P=1.00) | 4 | 4/4 |
| 7 | `+0.8200` (`e09`, d7, P=1.00) | `+0.0000` (`none`, d14, P=0.63) | `+0.8200` (`e09`, d7, P=1.00) | 3 | 3/3 |
| 8 | `+0.8800` (`e02`, d5, P=1.00) | `+0.0000` (`none`, d14, P=0.60) | `+0.8800` (`e02`, d5, P=1.00) | 2 | 2/2 |
| 9 | `+0.8000` (`e15`, d5, P=1.00) | `+0.0000` (`none`, d14, P=0.54) | `+0.8000` (`e15`, d5, P=1.00) | 3 | 3/3 |
| 10 | `+0.6900` (`e07`, d8, P=1.00) | `+0.0000` (`none`, d14, P=0.59) | `+0.6900` (`e07`, d8, P=1.00) | 6 | 6/6 |
| 11 | `+0.8400` (`e07`, d5, P=1.00) | `+0.0000` (`none`, d14, P=0.42) | `+0.8400` (`e07`, d5, P=1.00) | 3 | 3/3 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 6 | `d1-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_6_d1-2.png` | 880x620 | 31747 | `7fef9448117cf86fdedd3835617dbfb5684f9414f06b1f8f759c0d25e5e60507` |
| 6 | `d2-3` | 5 | `NONE` | `NONE` | YES | `memos/seed_6_d2-3.png` | 880x620 | 32003 | `8edcdb454fee9bbb8704c1d48eb22b53a86a6df3d980e01eb9c9b0451c95a965` |
| 6 | `d4-1` | 6 | `NONE` | `NONE` | YES | `memos/seed_6_d4-1.png` | 880x620 | 31580 | `2687dc207cf7263c7575a3dd86342c58d92c584526bcb6fffa41c3c54805515e` |
| 6 | `c5` | 6 | `A` | `A` | YES | `memos/seed_6_c5.png` | 880x620 | 30603 | `37e2391fee1db47c2ad14f3295a068594e54d1fad4464b08e049738be0b5b96b` |
| 7 | `c2` | 6 | `B` | `B` | YES | `memos/seed_7_c2.png` | 880x620 | 31464 | `5375ead980c15b06ed3f005771eec6c6739320dc81240fd24dbde2b486dc65e9` |
| 7 | `d4-2` | 6 | `NONE` | `NONE` | YES | `memos/seed_7_d4-2.png` | 880x620 | 31902 | `c574048c3cfea7157b73059479baeac3853822dcc771ad9b3be3ada5dcd3b5b2` |
| 7 | `c5` | 7 | `B` | `B` | YES | `memos/seed_7_c5.png` | 880x620 | 31218 | `f518738382ddc7e27c20d05abc3c4d72085aec554a3bad9ef432462d197f72e4` |
| 8 | `c2` | 3 | `A` | `A` | YES | `memos/seed_8_c2.png` | 880x620 | 30637 | `e9e17332ae0eb5afbd6d5d8a082ea1099ab9625213522988799f66847d37a700` |
| 8 | `c4` | 5 | `A` | `A` | YES | `memos/seed_8_c4.png` | 880x620 | 30370 | `811dcc32f3e34816970c5aeb4e33b35d5c543cd7c6f2566920e84dbbb7ac92f0` |
| 9 | `c1` | 2 | `C` | `C` | YES | `memos/seed_9_c1.png` | 880x620 | 30508 | `2b38e36c8d49f65a6cc9671151a9441a9ee2464ec2b59eee7e66a5575322f0ea` |
| 9 | `d2-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_9_d2-2.png` | 880x620 | 31513 | `ab97ae697745218bb4bd175463a809ef1f554b526584eafa613b8f5955ba0e2b` |
| 9 | `c2` | 5 | `B` | `B` | YES | `memos/seed_9_c2.png` | 880x620 | 31331 | `1f4c3bdb7d85564ced39b3d34d1243ae6e608c420bbbbb13825b145a6849a148` |
| 10 | `d1-3` | 3 | `NONE` | `NONE` | YES | `memos/seed_10_d1-3.png` | 880x620 | 31688 | `99d67aa1d30ff2cb552cd6eedc432ce17e59496361c4e086fa4755ae61948e78` |
| 10 | `d2-1` | 4 | `NONE` | `NONE` | YES | `memos/seed_10_d2-1.png` | 880x620 | 31571 | `1cfe9ba77e38bafebfb2079a28167314e1b8e3c4c10c31470f425da46c7e60f4` |
| 10 | `d3-1` | 6 | `NONE` | `NONE` | YES | `memos/seed_10_d3-1.png` | 880x620 | 31818 | `9140c6e8f285a637f0e7b11f9b564e1e4a85c95868545ce21cb8800d992d6842` |
| 10 | `d4-2` | 7 | `NONE` | `NONE` | YES | `memos/seed_10_d4-2.png` | 880x620 | 31716 | `8a7f1b6e87b71ead8a60e31a421608c8e033188db68bee44b9a5a17da03bd97c` |
| 10 | `d6-1` | 8 | `NONE` | `NONE` | YES | `memos/seed_10_d6-1.png` | 880x620 | 31890 | `b69c9e1c6f9a9170dbafea86b6791c424f8ea6c39d86c33765691bc2cbae709e` |
| 10 | `c7` | 8 | `B` | `B` | YES | `memos/seed_10_c7.png` | 880x620 | 31368 | `0bdd5775dda865472de55b520bb8a3d984af330231439c84e5d868eb44a8aa84` |
| 11 | `c1` | 2 | `A` | `A` | YES | `memos/seed_11_c1.png` | 880x620 | 30284 | `8a728d0a34c63999afc7b0264c5971b2141d249f2ee70090a2492f30ad57b950` |
| 11 | `d2-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_11_d2-1.png` | 880x620 | 31740 | `97ec3a0003684b90d2e3743983a4b5d70f172535f2bc15e5ae070f69c788d8f7` |
| 11 | `c2` | 5 | `A` | `A` | YES | `memos/seed_11_c2.png` | 880x620 | 30530 | `e7efa8cdd7bcb5e32247f24aa53f359165904cd07b3de8e00bd475ca9bc40a70` |
