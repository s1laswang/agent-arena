# Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation

## Provenance
- Role: `multimodal_evidence` (`visual_memo_blind_ablation`)
- Model: `gemini-4-carbon`
- Tiers version: `v1.4` (`hard`, seeds `[5, 6, 7, 8, 9]`)
- Commit: `726f9de02be0fe1ce8493640796d3f0cb9941e5d`
- Timestamp: `2026-11-14T22:55:26+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_memo_vision_ablation.py --tier hard --seeds 5,6,7,8,9 --model gemini-4-carbon --out results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-seeds5to9-carbon`
- Episodes per condition: `5` (3 conditions x 5 seeds = 15 paired episodes)
- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `25` (`11` watermarked canary scans)
- Vision watermark readout accuracy: `100.0%` overall (`100.0%` on planted canary memos)
- Token usage: `calls=25`, `in=47600`, `out=3214`, `thinking=2243`, `cached=0`, `cost_usd=0.149770`, `latency_s=168.17`

## Paired 3-Condition Comparison (`hard` seeds `[5, 6, 7, 8, 9]`)
| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |
|---|---|---:|---:|---:|---:|
| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | +0.5680 | 100.0% | 5/5 | 10.20 |
| `blind_no_vision` | Text `variant` redacted, vision disabled | +0.3440 | 60.0% | 3/5 | 8.67 |
| `text_oracle` | Unredacted text `check_leak_feed` upper bound | +0.5680 | 100.0% | 5/5 | 10.20 |

- Multimodal gain over blind ablation: `+0.2240`
- Oracle Bayesian solver performance recovered by vision: `100.0%` (`+0.5680` vs `+0.5680`)

## Per-Seed Paired Episodes
| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |
|---:|---|---|---|---:|---:|
| 5 | `+0.5200` (`e27`, d9, P=0.98) | `+0.5200` (`e27`, d9, P=1.00) | `+0.5200` (`e27`, d9, P=0.98) | 6 | 6/6 |
| 6 | `+0.7100` (`e34`, d6, P=1.00) | `+0.0000` (`none`, d21, P=0.60) | `+0.7100` (`e34`, d6, P=1.00) | 4 | 4/4 |
| 7 | `+0.6400` (`e37`, d9, P=1.00) | `+0.5500` (`e37`, d10, P=1.00) | `+0.6400` (`e37`, d9, P=1.00) | 3 | 3/3 |
| 8 | `+0.2600` (`e06`, d21, P=1.00) | `+0.0000` (`none`, d21, P=0.33) | `+0.2600` (`e06`, d21, P=1.00) | 9 | 9/9 |
| 9 | `+0.7100` (`e08`, d6, P=1.00) | `+0.6500` (`e08`, d7, P=0.88) | `+0.7100` (`e08`, d6, P=1.00) | 3 | 3/3 |

## Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts
| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |
|---:|---|---:|---|---|---|---|---|---:|---|
| 5 | `d1-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_5_d1-2.png` | 880x620 | 31747 | `7fef9448117cf86fdedd3835617dbfb5684f9414f06b1f8f759c0d25e5e60507` |
| 5 | `d2-3` | 5 | `NONE` | `NONE` | YES | `memos/seed_5_d2-3.png` | 880x620 | 32003 | `8edcdb454fee9bbb8704c1d48eb22b53a86a6df3d980e01eb9c9b0451c95a965` |
| 5 | `c3` | 7 | `A` | `A` | YES | `memos/seed_5_c3.png` | 880x620 | 30528 | `1625d8131b05f001adbb6c09bc6ff27e1454978febd2d8a67a75db586f452e5f` |
| 5 | `d4-3` | 8 | `NONE` | `NONE` | YES | `memos/seed_5_d4-3.png` | 880x620 | 31995 | `09e24a57eced490bf85a67aa7959e9d318dcb1e3adba7a275596b701f4179cde` |
| 5 | `c4` | 9 | `C` | `C` | YES | `memos/seed_5_c4.png` | 880x620 | 30680 | `3bbca073050cc1482ceb905c774edaa6a38ec65e8c48179dd2bf8e788b3019b0` |
| 5 | `c6-2` | 9 | `A` | `A` | YES | `memos/seed_5_c6-2.png` | 880x620 | 31259 | `bff70986ea6ab467bd48f0e2e0ce86cc3a2d03d100910e303f501eb5233f2ce2` |
| 6 | `d1-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_6_d1-2.png` | 880x620 | 31747 | `7fef9448117cf86fdedd3835617dbfb5684f9414f06b1f8f759c0d25e5e60507` |
| 6 | `d2-1` | 4 | `NONE` | `NONE` | YES | `memos/seed_6_d2-1.png` | 880x620 | 31571 | `1cfe9ba77e38bafebfb2079a28167314e1b8e3c4c10c31470f425da46c7e60f4` |
| 6 | `c3-2` | 5 | `A` | `A` | YES | `memos/seed_6_c3-2.png` | 880x620 | 31091 | `457c4052c9f58bbabe4679fcca49bef4c2158a3fafcf7185fac2ff70d40f8657` |
| 6 | `c4` | 6 | `C` | `C` | YES | `memos/seed_6_c4.png` | 880x620 | 30686 | `b8447a424060a168409e83bd4b603530e266e497b25c69fc4b726bcdfd9f2d6d` |
| 7 | `c1-2` | 3 | `A` | `A` | YES | `memos/seed_7_c1-2.png` | 880x620 | 30846 | `8654d58a3a0bb283826602054533249fd2ba6903b2f88d8ecd1b5ae3a5d094dd` |
| 7 | `d5-2` | 8 | `NONE` | `NONE` | YES | `memos/seed_7_d5-2.png` | 880x620 | 32046 | `cfee93f05d51843197927f3d895dfc9154fb8968ba8ebe1855148793f140ef2f` |
| 7 | `d6-3` | 9 | `NONE` | `NONE` | YES | `memos/seed_7_d6-3.png` | 880x620 | 32228 | `749bed0e475e4e262221517a5dbbcc4a70125b4f972ce4020d9db2a7637de452` |
| 8 | `d1-4` | 3 | `NONE` | `NONE` | YES | `memos/seed_8_d1-4.png` | 880x620 | 31568 | `101a9b9e2137960b75d1e046c7c1f25d5abd13de4f864049715d6f824a584405` |
| 8 | `d2-4` | 6 | `NONE` | `NONE` | YES | `memos/seed_8_d2-4.png` | 880x620 | 31900 | `0cd7fe002d4858edd09dc9d19835c4bdc6bc4a46cb7195b4ec03b390d0bfe2bc` |
| 8 | `d5-2` | 9 | `NONE` | `NONE` | YES | `memos/seed_8_d5-2.png` | 880x620 | 31992 | `c402b1dede9d61a3fd8d4844fbf6c343efa5b2b7fc429c3462a813861f7dcc01` |
| 8 | `d7-2` | 11 | `NONE` | `NONE` | YES | `memos/seed_8_d7-2.png` | 880x620 | 31222 | `8c584a693054f44004a6314d29ac2e2a5799309b076ae179926c8c25a11562b0` |
| 8 | `c8` | 13 | `A` | `A` | YES | `memos/seed_8_c8.png` | 880x620 | 30470 | `bae6f74fd4f4b16365c536725faef28e09bdee7d663d7e20d99055783f623679` |
| 8 | `d12-1` | 14 | `NONE` | `NONE` | YES | `memos/seed_8_d12-1.png` | 880x620 | 31269 | `79764fb7e3002849d593c476a7c3145a3bd420fe0bbfe529420278c58900ddd4` |
| 8 | `d13-2` | 16 | `NONE` | `NONE` | YES | `memos/seed_8_d13-2.png` | 880x620 | 31931 | `00764cde1429cfc28a6754cc4ca977a1010942f085935c55ebb168c7876d006b` |
| 8 | `c17` | 21 | `A` | `A` | YES | `memos/seed_8_c17.png` | 880x620 | 30274 | `b3cd47f1be17d54ae49f073f92617ed047efc1a7aac5c397fe6d93b7e9ba8877` |
| 8 | `c19` | 21 | `A` | `A` | YES | `memos/seed_8_c19.png` | 880x620 | 30538 | `4d09555b3e93cd71f12d59829e0918154891b114f4dce85c1a8f4f042daca47e` |
| 9 | `d1-2` | 3 | `NONE` | `NONE` | YES | `memos/seed_9_d1-2.png` | 880x620 | 31747 | `7fef9448117cf86fdedd3835617dbfb5684f9414f06b1f8f759c0d25e5e60507` |
| 9 | `c3-2` | 6 | `B` | `B` | YES | `memos/seed_9_c3-2.png` | 880x620 | 32005 | `c362042d57c1db53f94dcbf270792457dafb279210c702a47aca925116a76c98` |
| 9 | `c2` | 6 | `C` | `C` | YES | `memos/seed_9_c2.png` | 880x620 | 30866 | `18c2049e79796fd816bd369cb8102f6b6ada1d70a9ccf6c3ee303b16db3883db` |
