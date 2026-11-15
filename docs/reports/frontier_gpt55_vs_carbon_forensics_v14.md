# Paired Cross-Vendor Forensics on Canary v1.4 Hard (Seeds 0-29): OpenCode gpt-5.5 vs gemini-4-carbon vs Solver

Every figure in this report is deterministically computed on pure CPU from replay-verified `episodes.jsonl` records and OpenCode `transcripts/*.txt` event streams by `scripts/frontier_gpt55_vs_carbon_forensics.py` using `scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), `canary.analysis.accuse` (`audit_episode`), and `_ReplayTemplateProvider` caching (`0` API calls, `0` subprocesses, `0` runtime `.git` calls).

## 1. Provenance Sync (justSilas@5f9b3297) and Headline Summary

- **Upstream sync (`justSilas@5f9b3297`):** Code freeze `afterquery-final` (`1bc3e281`), submit tags `9225f2ad` / `aa1c679e`, CEO log correction `5f9b3297`, and Harbor judge rehearsal final ratios `93%, 116%, 131%` (`n=[10, 10, 9]` valid trials) on `s1-rehearsal-final@d0ead011`.
- **Primary `gemini-4-carbon` hard `0-29` (`post_hoc_lock`):** Episodes committed at `8fd4dec`, locked `28s` later at `671ed96` (`OpenCode 1.18.29`, `25` infra-excluded retries): raw `0.322` (`65% [24%, 98%]` of solver `0.499`), luck-adjusted `0.360` (`72% [52%, 91%]`).
- **Pre-registered `openai/gpt-5.5` hard `0-29` (`pre_registered`):** Pre-registered at `cf394894`, results committed at `ca0a0dc0` (`OpenCode 1.19.5`, `0` infra exclusions, `$38.91` total): raw `0.504` (`101% [79%, 140%]`), luck-adjusted `0.418` (`84% [67%, 103%]`).

| Cohort | n | Raw +/- 95% CI | Raw / Solver [95% CI] | Mean P(acc) | Luck-Adj (LA) | LA / Solver [95% CI] | End V (all/acc) | Acc Day | Canaries | Interviews | Total Calls | C / W / None |
|---|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|
| OpenCode gpt-5.5 hard (0-29) | 30 | +0.504 +/- 0.064 | 101% [79%, 140%] | 0.940 | +0.418 | 84% [67%, 103%] | 0.547 / 0.540 | 10.25 | 17.2 | 4.2 | 69.2 | 28 / 0 / 2 |
| OpenCode gemini-4-carbon hard (0-29) | 30 | +0.322 +/- 0.199 | 65% [24%, 98%] | 0.882 | +0.360 | 72% [52%, 91%] | 0.531 / 0.545 | 13.17 | 8.5 | 68.0 | 128.0 | 25 / 4 / 1 |
| reference solver hard (0-29) | 30 | +0.499 +/- 0.119 | 100% | 0.965 | +0.499 | 100% | 0.554 / 0.554 | 10.60 | 14.1 | 0.0 | 84.3 | 29 / 1 / 0 |

## 2. Paired Head-to-Head (`gpt-5.5` minus `gemini-4-carbon`, n=30 Hard Seeds)

- **Raw paired delta:** `+0.181` (`+/- 0.210` normal 95% CI; seeded 10,000-resample bootstrap 95% CI `[-0.009, +0.400]`), seed concordance `W/L/T = 14/15/1` (`gpt-5.5` wins fewer individual raw ties/margins because it plants `17.2` vs `8.5` canaries on shared solves, but avoids all four `-1.0` wrong accusations).
- **Luck-adjusted paired delta:** `+0.058` (`+/- 0.104` normal 95% CI; bootstrap 95% CI `[-0.044, +0.159]`), seed concordance `W/L/T = 18/12/0`.
- **Outcome concordance:** Across all `23` non-divergence seeds, both OpenCode models accuse the exact same true mole (`23/23` correct); the entire accuracy and penalty separation concentrates in `7` divergence seeds `[0, 1, 11, 15, 17, 18, 26]`.

## 3. Deep Forensics of the 7 Divergence Seeds

### 3A. Carbon's 4 Wrong Accusations [1, 15, 18, 26] + 1 Horizon Abstention [11] (5/5 Solved by gpt-5.5)

| Seed | Mole / Decoy | Carbon Outcome | Carbon P(acc) / P(mole) | Carbon Canaries / IVs | Mechanism | gpt-5.5 Outcome (P, Canaries) | Solver Outcome |
|---:|---|---|---|---:|---|---|---|
| 1 | `e33` / `e11` | accused `e39` (d19, `-1.000`, LA `+0.304`) | `0.988` / `0.012` | 15 / 90 | `single_noisy_canary_false_attribution` | accused `e33` (d12, `+0.430`, P=`0.966`, c=22) | accused `e33` (`+0.690`) |
| 15 | `e37` / `e39` | accused `e34` (d12, `-1.000`, LA `+0.360`) | `0.805` / `0.177` | 6 / 68 | `single_noisy_canary_false_attribution` | accused `e37` (d10, `+0.570`, P=`0.956`, c=18) | accused `e17` (`-1.000`) |
| 18 | `e27` / `e33` | accused `e29` (d18, `-1.000`, LA `-0.085`) | `0.627` / `0.145` | 14 / 101 | `below_breakeven_gamble_after_interview_erosion` | accused `e27` (d14, `+0.480`, P=`1.000`, c=22) | accused `e27` (`+0.520`) |
| 26 | `e08` / `e38` | accused `e04` (d10, `-1.000`, LA `+0.587`) | `0.950` / `0.027` | 8 / 43 | `single_noisy_canary_false_attribution` | accused `e08` (d10, `+0.620`, P=`0.982`, c=18) | accused `e08` (`+0.690`) |
| 11 | `e09` / `e32` | `None` (`horizon` d21, `+0.000`) | top `e30`=`0.219` / `0.204` | 12 / 121 | `interview_saturation_diffuse_posterior` | accused `e09` (d14, `+0.460`, P=`0.981`, c=24) | accused `e09` (`+0.620`) |

### 3B. GPT-5.5's 2 Clean rc=0 Non-Accuse Prose Exits [0, 17]

| Seed | Mole | Steps / Exit Day | Last MCP Tool | V_at_end | Top Posterior | Prose Suspect Named | Counterfactual Score / LA | Final Stop Prose |
|---:|---|---|---|---:|---|---|---|
| 0 | `e38` | 52 / day 8 (`rc=0`, `stop`) | `check_leak_feed` | 0.660 | `e38` (`0.949`) | `e38` (mole=True) | `+0.660` / `+0.575` | Accusing e38 based on two independent suspect-canary hits intersecting on e38. |
| 17 | `e28` | 83 / day 9 (`rc=0`, `stop`) | `check_leak_feed` | 0.640 | `e28` (`0.963`) | `e28` (mole=True) | `+0.640` / `+0.579` | Accusing e28 based on the c7 canary leak: variant C maps directly to e28 with 95% fingerprint accuracy, and c7 was only sent to e22/e27/e28. |

## 4. Why GPT-5.5 Raw Ratio Is 101% While Luck-Adjusted Ratio Is 84% [67%, 103%]

1. **Zero `-1.0` realization luck (`+0.086` per seed on `gpt-5.5` vs `-0.000` on `solver` and `-0.037` on `carbon`):** Across `gpt-5.5`'s `28` accusations, mean Bayesian posterior was `0.940`, implying `1.68` expected noisy-canary false positives (`5` accusations made at `P < 0.90` on seeds `[5, 7, 16, 21, 23]`). Realizing `0` wrong accusations (`28/28` correct) added `+0.086` realization luck per seed above posterior expectation (`0.504` raw vs `0.418` LA), whereas the solver realized `1` noisy-canary `-1.0` error (seed `15`, vs `1.04` expected).
2. **Exact decomposition of the `-0.082` (`0.0815`) LA shortfall vs solver (`0.418` vs `0.499`):**
   - **Two non-accuse zeros on seeds `[0, 17]` (`+0.0417`/seed, `51.2%` of LA gap):** Scoring `0.000` instead of solver's `+0.556` and `+0.696` accounts for over half the LA gap. Had `gpt-5.5` invoked `accuse` for the exact mole it named in prose on `[0, 17]`, counterfactual `gpt-5.5` reaches `0.547` raw (`110%` of solver, `30/30` correct) and `0.456` LA (`91%` of solver).
   - **Slightly lower `V_at_end` and terminal posterior on the 28 accused seeds (`+0.0398`/seed, `48.8%` of LA gap):** On seeds where `gpt-5.5` accused, heavier canary planting (`17.2` vs `14.1`) and `4.2` interviews yielded `V_at_end = 0.540` vs solver `0.543` and mean `P(accused) = 0.940` vs solver `0.966`.

## 5. Seed-by-Seed 3-Way Matrix (v1.4 Hard Seeds 0-29)

| Seed | Mole | gpt-5.5 (acc, raw, P, LA, d, V, c/iv) | carbon (acc, raw, P, LA, d, V, c/iv) | solver (acc, raw, P, LA, d, V, c) | dRaw (G-C) | dLA (G-C) |
|---:|---|---|---|---|---:|---:|
| 0 | `e38` | `None` +0.00 P=- LA=+0.00 d0 V=0.66 (14/0) | `e38` +0.59 P=0.981 LA=+0.56 d11 V=0.59 (7/57) | `e38` +0.64 P=0.949 LA=+0.56 d9 V=0.64 (11) | -0.59 (L) | -0.560 (L) |
| 1 | `e33` | `e33` +0.43 P=0.966 LA=+0.38 d12 V=0.43 (22/0) | `e39` -1.00 P=0.988 LA=+0.30 d19 V=0.32 (15/90) | `e33` +0.69 P=0.985 LA=+0.66 d7 V=0.69 (11) | +1.43 (W) | +0.077 (W) |
| 2 | `e25` | `e25` +0.47 P=0.944 LA=+0.39 d11 V=0.47 (18/11) | `e25` +0.48 P=0.971 LA=+0.44 d14 V=0.48 (7/80) | `e25` +0.58 P=0.999 LA=+0.58 d9 V=0.58 (12) | -0.01 (L) | -0.049 (L) |
| 3 | `e29` | `e29` +0.42 P=0.986 LA=+0.40 d10 V=0.42 (18/0) | `e29` +0.51 P=0.766 LA=+0.16 d19 V=0.51 (7/40) | `e29` +0.28 P=0.958 LA=+0.23 d18 V=0.28 (22) | -0.09 (L) | +0.243 (W) |
| 4 | `e11` | `e11` +0.72 P=0.984 LA=+0.69 d6 V=0.72 (8/0) | `e11` +0.40 P=0.992 LA=+0.39 d16 V=0.40 (10/84) | `e11` +0.73 P=1.000 LA=+0.73 d5 V=0.73 (7) | +0.32 (W) | +0.304 (W) |
| 5 | `e27` | `e27` +0.41 P=0.664 LA=-0.06 d14 V=0.41 (24/8) | `e27` +0.16 P=0.510 LA=-0.41 d21 V=0.16 (19/103) | `e27` +0.52 P=0.982 LA=+0.49 d9 V=0.52 (13) | +0.25 (W) | +0.345 (W) |
| 6 | `e34` | `e34` +0.75 P=0.957 LA=+0.67 d6 V=0.75 (10/0) | `e34` +0.73 P=0.998 LA=+0.73 d6 V=0.73 (7/25) | `e34` +0.71 P=0.999 LA=+0.71 d6 V=0.71 (9) | +0.02 (W) | -0.052 (L) |
| 7 | `e37` | `e37` +0.55 P=0.740 LA=+0.15 d11 V=0.55 (20/4) | `e37` +0.69 P=0.783 LA=+0.32 d10 V=0.69 (6/57) | `e37` +0.64 P=1.000 LA=+0.64 d9 V=0.64 (11) | -0.14 (L) | -0.176 (L) |
| 8 | `e06` | `e06` +0.58 P=0.999 LA=+0.58 d7 V=0.58 (12/4) | `e06` +0.35 P=0.827 LA=+0.12 d14 V=0.35 (10/79) | `e06` +0.26 P=1.000 LA=+0.26 d21 V=0.26 (24) | +0.23 (W) | +0.462 (W) |
| 9 | `e08` | `e08` +0.70 P=0.968 LA=+0.65 d6 V=0.70 (11/2) | `e08` +0.60 P=0.932 LA=+0.49 d15 V=0.60 (10/85) | `e08` +0.71 P=0.995 LA=+0.70 d6 V=0.71 (9) | +0.10 (W) | +0.154 (W) |
| 10 | `e10` | `e10` +0.64 P=0.923 LA=+0.51 d9 V=0.64 (16/12) | `e10` +0.40 P=0.934 LA=+0.31 d16 V=0.40 (8/85) | `e10` +0.21 P=0.942 LA=+0.14 d19 V=0.21 (24) | +0.24 (W) | +0.206 (W) |
| 11 | `e09` | `e09` +0.46 P=0.981 LA=+0.43 d14 V=0.46 (24/0) | `None` +0.00 P=- LA=+0.00 d21 V=0.13 (12/121) | `e09` +0.62 P=1.000 LA=+0.62 d9 V=0.62 (13) | +0.46 (W) | +0.432 (W) |
| 12 | `e24` | `e24` +0.66 P=0.981 LA=+0.63 d8 V=0.66 (14/0) | `e24` +0.65 P=0.976 LA=+0.61 d9 V=0.65 (10/40) | `e24` +0.48 P=0.869 LA=+0.29 d12 V=0.48 (17) | +0.01 (W) | +0.018 (W) |
| 13 | `e20` | `e20` +0.52 P=0.992 LA=+0.51 d10 V=0.52 (18/1) | `e20` +0.40 P=0.975 LA=+0.36 d13 V=0.40 (10/70) | `e20` +0.34 P=0.964 LA=+0.29 d17 V=0.34 (21) | +0.12 (W) | +0.143 (W) |
| 14 | `e27` | `e27` +0.47 P=0.965 LA=+0.42 d10 V=0.47 (18/3) | `e27` +0.71 P=0.772 LA=+0.32 d8 V=0.71 (4/44) | `e27` +0.23 P=0.996 LA=+0.23 d15 V=0.23 (17) | -0.24 (L) | +0.098 (W) |
| 15 | `e37` | `e37` +0.57 P=0.956 LA=+0.50 d10 V=0.57 (18/0) | `e34` -1.00 P=0.805 LA=+0.36 d12 V=0.69 (6/68) | `e17` -1.00 P=0.874 LA=+0.43 d9 V=0.64 (11) | +1.57 (W) | +0.140 (W) |
| 16 | `e20` | `e20` +0.57 P=0.877 LA=+0.38 d12 V=0.57 (18/5) | `e20` +0.70 P=0.966 LA=+0.64 d10 V=0.70 (5/51) | `e20` +0.69 P=0.952 LA=+0.61 d8 V=0.69 (11) | -0.13 (L) | -0.265 (L) |
| 17 | `e28` | `None` +0.00 P=- LA=+0.00 d0 V=0.64 (16/15) | `e28` +0.54 P=0.995 LA=+0.53 d10 V=0.54 (6/49) | `e28` +0.77 P=0.958 LA=+0.70 d5 V=0.77 (8) | -0.54 (L) | -0.532 (L) |
| 18 | `e27` | `e27` +0.48 P=1.000 LA=+0.48 d14 V=0.48 (22/7) | `e29` -1.00 P=0.627 LA=-0.08 d18 V=0.46 (14/101) | `e27` +0.52 P=0.956 LA=+0.45 d13 V=0.52 (18) | +1.48 (W) | +0.565 (W) |
| 19 | `e09` | `e09` +0.28 P=0.932 LA=+0.19 d14 V=0.28 (22/0) | `e09` +0.62 P=0.964 LA=+0.56 d11 V=0.62 (8/60) | `e09` +0.67 P=0.951 LA=+0.59 d9 V=0.67 (13) | -0.34 (L) | -0.369 (L) |
| 20 | `e14` | `e14` +0.62 P=0.969 LA=+0.57 d10 V=0.62 (18/8) | `e14` +0.66 P=0.712 LA=+0.18 d11 V=0.66 (4/66) | `e14` +0.53 P=0.982 LA=+0.50 d12 V=0.53 (17) | -0.04 (L) | +0.388 (W) |
| 21 | `e14` | `e14` +0.69 P=0.884 LA=+0.49 d11 V=0.69 (16/0) | `e14` +0.69 P=0.820 LA=+0.39 d10 V=0.69 (6/58) | `e14` +0.73 P=0.920 LA=+0.59 d9 V=0.73 (12) | +0.00 (T) | +0.108 (W) |
| 22 | `e36` | `e36` +0.33 P=0.981 LA=+0.30 d12 V=0.33 (22/4) | `e36` +0.64 P=0.943 LA=+0.55 d14 V=0.64 (6/82) | `e36` +0.40 P=0.969 LA=+0.36 d15 V=0.40 (20) | -0.31 (L) | -0.242 (L) |
| 23 | `e29` | `e29` +0.57 P=0.740 LA=+0.16 d11 V=0.57 (18/9) | `e29` +0.23 P=0.452 LA=-0.44 d21 V=0.23 (12/86) | `e29` +0.32 P=0.963 LA=+0.27 d18 V=0.32 (23) | +0.34 (W) | +0.606 (W) |
| 24 | `e17` | `e17` +0.58 P=0.980 LA=+0.55 d8 V=0.58 (12/0) | `e17` +0.67 P=0.995 LA=+0.66 d13 V=0.67 (8/69) | `e17` +0.31 P=0.992 LA=+0.30 d14 V=0.31 (19) | -0.09 (L) | -0.113 (L) |
| 25 | `e16` | `e16` +0.64 P=0.986 LA=+0.62 d9 V=0.64 (16/0) | `e16` +0.72 P=0.997 LA=+0.71 d11 V=0.72 (3/60) | `e16` +0.58 P=0.979 LA=+0.55 d8 V=0.58 (12) | -0.08 (L) | -0.098 (L) |
| 26 | `e08` | `e08` +0.62 P=0.982 LA=+0.59 d10 V=0.62 (18/18) | `e04` -1.00 P=0.950 LA=+0.59 d10 V=0.67 (8/43) | `e08` +0.69 P=0.968 LA=+0.64 d7 V=0.69 (11) | +1.62 (W) | +0.004 (W) |
| 27 | `e33` | `e33` +0.44 P=1.000 LA=+0.44 d10 V=0.44 (16/12) | `e33` +0.46 P=1.000 LA=+0.46 d15 V=0.46 (14/78) | `e33` +0.72 P=0.985 LA=+0.69 d6 V=0.72 (8) | -0.02 (L) | -0.020 (L) |
| 28 | `e35` | `e35` +0.52 P=0.992 LA=+0.51 d10 V=0.52 (18/0) | `e35` +0.64 P=0.978 LA=+0.60 d12 V=0.64 (6/64) | `e35` +0.75 P=0.984 LA=+0.72 d6 V=0.75 (10) | -0.12 (L) | -0.096 (L) |
| 29 | `e19` | `e19` +0.42 P=0.988 LA=+0.40 d12 V=0.42 (18/2) | `e19` +0.43 P=0.964 LA=+0.38 d13 V=0.43 (7/46) | `e19` +0.65 P=0.884 LA=+0.46 d8 V=0.65 (10) | -0.01 (L) | +0.024 (W) |
