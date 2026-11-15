# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`hard`, seeds `[10, 11, 12, 13, 14]`)
- Commit: `898dbbb4ae98f0dbf742f8e91a2557cb614a5877`
- Timestamp: `2026-11-14T23:45:43+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=30 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_memo_vision_ablation.py --tier hard --seeds 10,11,12,13,14 --model gemini-4-carbon --out results/gemini_roles/multimodal_evidence/memo-watermark-hard-seeds10to14-carbon`
- Episodes per condition: `5` (3 conditions x 5 seeds = 15 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `39` (`6` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=39`, `in=74256`, `out=4966`, `thinking=3691`, `cached=0`, `cost_usd=0.235082`, `latency_s=323.89`

## Paired 3-Condition Comparison (`hard` seeds `[10, 11, 12, 13, 14]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.3760 | 100.0% | 5/5 | 14.40 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.2340 | 60.0% | 3/5 | 14.00 |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.3760 | 100.0% | 5/5 | 14.40 |

- Multimodal gain over blind ablation: `+0.1420`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.3760` vs `+0.3760`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 10 | `+0.2100` (`e10`, d19, P=0.94) | `+0.0000` (`none`, d21, P=0.48) | `+0.2100` (`e10`, d19, P=0.94) | 10 | 10/10 |
| 11 | `+0.6200` (`e09`, d9, P=1.00) | `+0.6200` (`e09`, d9, P=0.91) | `+0.6200` (`e09`, d9, P=1.00) | 4 | 4/4 |
| 12 | `+0.4800` (`e24`, d12, P=0.87) | `+0.3200` (`e24`, d18, P=0.87) | `+0.4800` (`e24`, d12, P=0.87) | 5 | 5/5 |
| 13 | `+0.3400` (`e20`, d17, P=0.96) | `+0.0000` (`none`, d21, P=0.43) | `+0.3400` (`e20`, d17, P=0.96) | 8 | 8/8 |
| 14 | `+0.2300` (`e27`, d15, P=1.00) | `+0.2300` (`e27`, d15, P=0.88) | `+0.2300` (`e27`, d15, P=1.00) | 12 | 12/12 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 10 | `d2-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_10_d2-2.png` | 880x620 | 31513 | `ab97ae697745218bb4bd175463a809ef1f554b526584eafa613b8f5955ba0e2b` |
| 10 | `d5-3` | 7 | `NONE` | `NONE` | YES | `memos/seed_10_d5-3.png` | 880x620 | 31882 | `51a9c3580391eab59ccebc1dcf52e1f60566c7dedde4d01ef8046f577871543c` |
| 10 | `d5-2` | 9 | `NONE` | `NONE` | YES | `memos/seed_10_d5-2.png` | 880x620 | 31992 | `c402b1dede9d61a3fd8d4844fbf6c343efa5b2b7fc429c3462a813861f7dcc01` |
| 10 | `d7-1` | 9 | `NONE` | `NONE` | YES | `memos/seed_10_d7-1.png` | 880x620 | 31606 | `d48a82c17a17b5c7c0f51eda79968689ea3f1524795f6bdf522d623fa5f0ea32` |
| 10 | `d8-1` | 11 | `NONE` | `NONE` | YES | `memos/seed_10_d8-1.png` | 880x620 | 31135 | `3f5809dd0cf260755bd539c76edff2147d806db50571a24c8554ce4fabc023ef` |
| 10 | `d9-1` | 12 | `NONE` | `NONE` | YES | `memos/seed_10_d9-1.png` | 880x620 | 31473 | `f94beb9f72da40c1ecb7aecc6a2a72408fa880d5c789ef0b7aa09a010240477d` |
| 10 | `d12-1` | 15 | `NONE` | `NONE` | YES | `memos/seed_10_d12-1.png` | 880x620 | 31309 | `80070390623a18d3272fdf0f7020506adcd07db142319d44f3cd72a3a65a6b59` |
| 10 | `d13-3` | 16 | `NONE` | `NONE` | YES | `memos/seed_10_d13-3.png` | 880x620 | 31510 | `96641ae7e3df60e891705b02df976aeb6821c1a84ca1f5f32e4b8d60aa704f7f` |
| 10 | `d14-1` | 17 | `NONE` | `NONE` | YES | `memos/seed_10_d14-1.png` | 880x620 | 31105 | `051fd6cbf5e534a91ec786520ee0d499a8f3390f9c601043f0af8065a70bcff5` |
| 10 | `c15` | 19 | `B` | `B` | YES | `memos/seed_10_c15.png` | 880x620 | 31209 | `fb7fa955802a1db9c195f285107ae15d165a830e9dd5559f2b544e521f9e21cb` |
| 11 | `d2-3` | 4 | `NONE` | `NONE` | YES | `memos/seed_11_d2-3.png` | 880x620 | 31929 | `39260c62a5e727311c7fc01d46474cc44db6b8c471c340218a12562463082fe6` |
| 11 | `c2-2` | 6 | `C` | `C` | YES | `memos/seed_11_c2-2.png` | 880x620 | 30973 | `5b337d19f7564704d7c899676f5c1044f9f0a85f33b2fa5bd0a072af47e92d8a` |
| 11 | `d3-2` | 7 | `NONE` | `NONE` | YES | `memos/seed_11_d3-2.png` | 880x620 | 31944 | `817f4b3f35e25117dbae2b89a124f07b3d45fe09c4197cfc18c9bdd91d0473f4` |
| 11 | `c5` | 9 | `B` | `B` | YES | `memos/seed_11_c5.png` | 880x620 | 31390 | `e9dfcecb2ac01af1f3befda71c27da6a46f2251deaac00f74ed711db4f750811` |
| 12 | `d2-1` | 5 | `NONE` | `NONE` | YES | `memos/seed_12_d2-1.png` | 880x620 | 31629 | `9215fee1fbf7a1f751ceadab584d454494ead0f617d78e651064146c2b793753` |
| 12 | `d5-1` | 7 | `NONE` | `NONE` | YES | `memos/seed_12_d5-1.png` | 880x620 | 31504 | `0fc3be299328e01c63afbd373290de539c88b2630fac0814f99486145671a3b8` |
| 12 | `d6-1` | 9 | `NONE` | `NONE` | YES | `memos/seed_12_d6-1.png` | 880x620 | 31838 | `6a0c65627717bc1c85f02d5b335a518145b61075fcd10917272071f1a50e0ff7` |
| 12 | `d7-2` | 10 | `NONE` | `NONE` | YES | `memos/seed_12_d7-2.png` | 880x620 | 31644 | `dd460e0115c98e7d340fb97ae69b1b821c7b7eaa91247e5d3429703886517266` |
| 12 | `c8` | 11 | `A` | `A` | YES | `memos/seed_12_c8.png` | 880x620 | 30057 | `066111d353ba6a7e9c8f78eb809874956075fa21d6e4e4ce612ac66a6e7f7ea3` |
| 13 | `d1-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_13_d1-1.png` | 880x620 | 31312 | `33be5967c7d3732f8d7d872576dfcc9c0b1291bf79ff4f3e5e4e8e9f95427089` |
| 13 | `d2-2` | 4 | `NONE` | `NONE` | YES | `memos/seed_13_d2-2.png` | 880x620 | 31513 | `ab97ae697745218bb4bd175463a809ef1f554b526584eafa613b8f5955ba0e2b` |
| 13 | `d2-1` | 5 | `NONE` | `NONE` | YES | `memos/seed_13_d2-1.png` | 880x620 | 31629 | `9215fee1fbf7a1f751ceadab584d454494ead0f617d78e651064146c2b793753` |
| 13 | `d7-1` | 9 | `NONE` | `NONE` | YES | `memos/seed_13_d7-1.png` | 880x620 | 31606 | `d48a82c17a17b5c7c0f51eda79968689ea3f1524795f6bdf522d623fa5f0ea32` |
| 13 | `d8-1` | 12 | `NONE` | `NONE` | YES | `memos/seed_13_d8-1.png` | 880x620 | 31491 | `192be700a0d2b82e46454b82bd05b492af762a3c1c8f9f85804bf30664fe3cdb` |
| 13 | `d11-2` | 15 | `NONE` | `NONE` | YES | `memos/seed_13_d11-2.png` | 880x620 | 31312 | `1ab410ac9fed62f3bbac003611722f05adb31d6cb5deefa81117467767f64a44` |
| 13 | `d12-1` | 16 | `NONE` | `NONE` | YES | `memos/seed_13_d12-1.png` | 880x620 | 31450 | `ab7dc32c1648b1542ab60e768f4142ac450b04679c466eedc9d1d48ec3563dae` |
| 13 | `c14` | 17 | `A` | `A` | YES | `memos/seed_13_c14.png` | 880x620 | 30129 | `5128849cc061a6ce48d8305d7140042400c3489763041e66b3010c20991a19b8` |
| 14 | `d1-1` | 3 | `NONE` | `NONE` | YES | `memos/seed_14_d1-1.png` | 880x620 | 31312 | `33be5967c7d3732f8d7d872576dfcc9c0b1291bf79ff4f3e5e4e8e9f95427089` |
| 14 | `d1-2` | 6 | `NONE` | `NONE` | YES | `memos/seed_14_d1-2.png` | 880x620 | 31769 | `22829d17beb71d740e9637912400af1d48fe6672206110cc8cd5ebcf0f837f9d` |
| 14 | `d4-4` | 7 | `NONE` | `NONE` | YES | `memos/seed_14_d4-4.png` | 880x620 | 31322 | `ae1e218830fdcc4eddb93e2ce2eda392ad62ee20595b439575353aaa2310cf95` |
| 14 | `d3-3` | 8 | `NONE` | `NONE` | YES | `memos/seed_14_d3-3.png` | 880x620 | 31761 | `ca43e24e6421888260149185d45ba94520dcbf6336e9b42487a004de88179e0a` |
| 14 | `d5-1` | 9 | `NONE` | `NONE` | YES | `memos/seed_14_d5-1.png` | 880x620 | 31678 | `0c73977b1a14de113127ec81016c8e26e0debfa7628dc4eb4ec0696b588a6309` |
| 14 | `d6-3` | 10 | `NONE` | `NONE` | YES | `memos/seed_14_d6-3.png` | 880x620 | 31937 | `4204d49fd775ff0069541ec624e83a77069d0b5bd7b0bb14f6f14f7858d195a7` |
| 14 | `d6-1` | 11 | `NONE` | `NONE` | YES | `memos/seed_14_d6-1.png` | 880x620 | 31104 | `527589395c038c5b35f11ec733c6baf7cab039224338dbf321ab5b9c0910d085` |
| 14 | `d9-1` | 12 | `NONE` | `NONE` | YES | `memos/seed_14_d9-1.png` | 880x620 | 31473 | `f94beb9f72da40c1ecb7aecc6a2a72408fa880d5c789ef0b7aa09a010240477d` |
| 14 | `d8-3` | 13 | `NONE` | `NONE` | YES | `memos/seed_14_d8-3.png` | 880x620 | 31847 | `c17d3acafc930a3e056d2f6feb649d46cb4ebd9c33c45e7ca220f7d8eac7699f` |
| 14 | `d9-3` | 13 | `NONE` | `NONE` | YES | `memos/seed_14_d9-3.png` | 880x620 | 31782 | `d0f812f6ff8e5593860d1af79c1a7c08fcf791ee0f0f00a2dc499eba58aad09f` |
| 14 | `d11-1` | 14 | `NONE` | `NONE` | YES | `memos/seed_14_d11-1.png` | 880x620 | 30847 | `071d12825a3d9f16a84ce82aaff8b1e17864a91562709c5b129d0265adbf0375` |
| 14 | `c12` | 15 | `A` | `A` | YES | `memos/seed_14_c12.png` | 880x620 | 30334 | `c150bce69717c8f4b5f77d3dc37e1426ca28bf8e6816585929290efae04816f0` |
