# v1.4 Out-of-Sample Replication Report: Seeds 0-29 Primary vs Seeds 30-59 Extension

## Pre-Registered Framing and Headline Summary

Per the pre-registered seed protocol in [gap.md](gap.md) (commit `671ed96`, locked before any fleet rerun landed), Canary reports the two v1.4 `hard` evaluation cohorts strictly separately:

1. **Pre-registered primary headline (`data/runs/committed/v1.4`, dev seeds `0-29`, `n=30`):** OpenCode + `gemini-4-carbon` over MCP (the judges' harness) scores **`+0.322 +/- 0.199`** against the paired reference solver's **`+0.499 +/- 0.119`** on the exact same 30 seeds, giving **`65% [24%, 98%]` raw** (`-0.177 +/- 0.194` paired diff) and **`72% [52%, 91%]` luck-adjusted** (`+0.360` vs `+0.499`; 10,000-resample paired bootstrap 95% CIs). Both primary 95% CIs exclude `100%` parity. Detailed trajectory accounting is in [failure_analysis_v1.4.md](failure_analysis_v1.4.md) and [paired_table_gemini.md](../../data/runs/committed/v1.4/paired_table_gemini.md).
2. **Out-of-sample replication / extension cohort (`results/replication/v1.4`, dev seeds `30-59`):** `5` out-of-sample `hard` episodes (`seeds 30, 34, 42, 45, 57`) have completed cleanly under raised OpenCode runner timeouts and passed deterministic step-by-step replay verification, paired against `solver-hard-seeds30to59` (`n=30`, full seeds `30-59` mean `+0.498 +/- 0.156`, luck-adjusted `+0.542`). On the `5` paired extension seeds, OpenCode `gemini-4-carbon` scores `+0.656 +/- 0.110` vs same-seed solver `+0.248` (`265% [115%, 304%]` raw; `110% [58%, 179%]` luck-adjusted).
3. **Secondary pooled summary (`0-29 + verified 30-59`, `n=35` paired `hard` seeds; never substituted for the `0-29` primary headline):** Across all `35` replay-verified `hard` seeds combined, OpenCode `gemini-4-carbon` scores `+0.370 +/- 0.175` vs paired solver `+0.463` (`80% [42%, 124%]` raw, paired diff `-0.093 +/- 0.193`) and **`77% [58%, 96%]` luck-adjusted** (`+0.376` vs `+0.489`).

Every figure in this report is computed deterministically without API keys by [scripts/v14_replication_report.py](../../scripts/v14_replication_report.py), which replays every episode in a fresh `canary.env.Env` and aborts on any score, accusation, step-level, manifest, orphan-transcript, duplicate-seed, or timeout hygiene violation.

## 1. Paired Statistical Tables Across Cohorts

Columns match `scripts/paired_gemini.py`: `score +/- 95% CI` uses normal-approximation half-width; `frontier / solver [95% CI]` and `luck-adj. / solver [95% CI]` use 10,000 paired bootstrap resamples (`rng_seed=0`) over shared seeds; `luck-adj. score` evaluates each accusation at `P(accused) * V - (1 - P(accused))` under `canary.analysis.accuse.audit_episode` (`0` on abstention).

### 1A. Primary Pre-Registered Cohort (`data/runs/committed/v1.4`, Seeds `0-29`)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (judges' harness, PRIMARY) | 30 | +0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | +0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | +0.360 | **72% [52%, 91%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | +0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | +0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | +0.421 | **84% [65%, 106%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family) | 30 | +0.373 +/- 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | +0.499 | 75% [36%, 123%] | -0.126 +/- 0.221 | +0.110 | **22% [-23%, 63%]** |
| hard | reference solver (seeds 0-29) | 30 | +0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | +0.499 | - | - | +0.499 | - |
| medium | OpenCode + gemini-4-carbon over MCP (judges' harness, medium context) | 30 | +0.713 +/- 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | +0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | +0.652 | **101% [85%, 119%]** |
| medium | in-process gemini-4-carbon (medium context) | 30 | +0.530 +/- 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | +0.645 | 82% [56%, 108%] | -0.115 +/- 0.170 | +0.479 | **74% [52%, 99%]** |
| medium | reference solver (medium context, seeds 0-29) | 30 | +0.645 +/- 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | +0.645 | - | - | +0.645 | - |

### 1B. Out-of-Sample Replication / Extension Cohort (`results/replication/v1.4`, Hard Seeds `30-59`)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (out-of-sample replication) | 5 | +0.656 +/- 0.110 | 1.00 | 1.00 | 11.0 | 0.89 | +0.248 | 265% [115%, 304%] | +0.408 +/- 0.557 | +0.472 | **110% [58%, 179%]** |
| hard | solver-hard-seeds30to59 (paired on the 5 completed frontier seed(s)) | 5 | +0.248 +/- 0.616 | 0.80 | 1.00 | 10.6 | 0.94 | +0.248 | - | - | +0.430 | - |
| hard | solver-hard-seeds30to59 (full 30-seed cohort) | 30 | +0.498 +/- 0.156 | 0.90 | 0.97 | 8.4 | 0.96 | +0.498 | - | - | +0.542 | - |
| hard | grok_tactics (seeds 30-59) | 30 | +0.314 +/- 0.126 | 0.83 | 0.87 | 11.1 | 0.97 | +0.498 | 63% [35%, 106%] | -0.184 +/- 0.199 | +0.321 | **59% [44%, 75%]** |
| hard | heuristic (seeds 30-59) | 30 | +0.118 +/- 0.163 | 0.87 | 1.00 | 15.6 | 0.82 | +0.498 | 24% [-11%, 60%] | -0.380 +/- 0.227 | +0.062 | **11% [-13%, 32%]** |
| hard | logs_only (seeds 30-59) | 30 | -0.942 +/- 0.114 | 0.03 | 1.00 | 10.0 | 0.01 | +0.498 | -189% [-292%, -141%] | -1.440 +/- 0.185 | -0.983 | **-181% [-206%, -164%]** |
| hard | do_nothing (seeds 30-59) | 30 | +0.000 +/- 0.000 | 0.00 | 0.00 | - | - | +0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | +0.000 | **0% [0%, 0%]** |
| hard | stop_early (seeds 30-59) | 30 | +0.000 +/- 0.000 | 0.00 | 0.00 | - | - | +0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | +0.000 | **0% [0%, 0%]** |
| hard | random (seeds 30-59) | 30 | -0.833 +/- 0.136 | 0.00 | 0.83 | 6.2 | 0.03 | +0.498 | -167% [-250%, -127%] | -1.331 +/- 0.225 | -0.791 | **-146% [-176%, -118%]** |
| hard | restrict_all (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | +0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.993 | **-183% [-208%, -166%]** |
| hard | guess_day1 (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | +0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.950 | **-175% [-199%, -159%]** |

### 1C. Secondary Pooled Hard Cohort (`0-29` Primary + Verified `30-59` Extension)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (pooled 0-29 + verified 30-59) | 35 | +0.370 +/- 0.175 | 0.86 | 0.97 | 12.9 | 0.88 | +0.463 | 80% [42%, 124%] | -0.093 +/- 0.193 | +0.376 | **77% [58%, 96%]** |
| hard | reference solver (paired on the 35 pooled frontier seeds) | 35 | +0.463 +/- 0.133 | 0.94 | 1.00 | 10.6 | 0.96 | +0.463 | - | - | +0.489 | - |
| hard | reference solver (all committed hard seeds 0-59) | 60 | +0.498 +/- 0.097 | 0.93 | 0.98 | 9.5 | 0.96 | +0.498 | - | - | +0.521 | - |

**Statistical reading of the `5`-seed extension slice and `35`-seed pool:**
- **Why luck adjustment stabilizes small-`n` raw ratios:** Across all 30 out-of-sample seeds `30-59`, `solver-hard-seeds30to59` averages `+0.498 +/- 0.156` (`90%` accuracy, only 2 wrong accusations out of 30). However, the `5` completed frontier seeds include seed `30` (solver accused `e26` vs mole `e15` at `P = 0.858`, raw `-1.000`, luck-adjusted `+0.175`). A single `-1.000` realization depresses the `5`-seed raw solver denominator to `+0.248`, inflating the raw `5`-seed ratio to `265%`, whereas the posterior-expected (luck-adjusted) solver score on those same `5` seeds is `+0.430` (`110%` luck-adjusted ratio).
- **Sub-0.85 commitment still appears out of sample:** Even among correct accusations, seed `34` (`P(accused) = 0.650` on day `8`, raw `+0.82` -> luck-adjusted `+0.183` vs solver `+0.663` at `P = 0.978`), mirroring the primary `0-29` finding that OpenCode `gemini-4-carbon` sometimes commits before canary leaks isolate a single suspect.
- **Wall-clock regime (`min = 921.8s`, `max = 2858.9s`):** Every completed `hard` episode in `30-59` ran longer than `900s` (`5/5` > `900s`), confirming that early `900s` runner caps measured wall-clock timeout rather than decision quality and justifying the raised `--timeout 3600` / `10800` replication protocol.

## 2. Replay-Verified Hard Episodes in `30-59` (Per-Seed Comparison)

| seed | shard | Gemini score | solver score | diff (F - S) | Gemini day | solver day | Gemini accused (mole) | solver accused | canaries / interviews | Gemini P(acc) | solver P(acc) | Gemini luck-adj. | solver luck-adj. | wall_s | replay |
|---:|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 30 | `opencode-gemini-4-carbon/hard-s30-33` | +0.54 | -1.00 | +1.54 | 11 | 18 | `e15` (ok, mole `e15`) | `e26` (WRONG) | 6 / 61 | 0.909 | 0.858 | +0.400 | +0.175 | 1597.9s | PASS |
| 34 | `opencode-gemini-4-carbon/hard-s34-37` | +0.82 | +0.70 | +0.12 | 8 | 6 | `e29` (ok, mole `e29`) | `e29` (ok) | 3 / 49 | 0.650 | 0.978 | +0.183 | +0.663 | 1499.2s | PASS |
| 42 | `opencode-gemini-4-carbon/hard-s42-44` | +0.57 | +0.51 | +0.06 | 12 | 10 | `e19` (ok, mole `e19`) | `e19` (ok) | 8 / 16 | 0.969 | 0.997 | +0.521 | +0.505 | 1329.9s | PASS |
| 45 | `opencode-gemini-4-carbon/hard-s45-47` | +0.59 | +0.49 | +0.10 | 16 | 11 | `e11` (ok, mole `e11`) | `e11` (ok) | 6 / 88 | 0.973 | 0.955 | +0.547 | +0.423 | 2858.9s | PASS |
| 57 | `opencode-gemini-4-carbon/hard-s57-59` | +0.76 | +0.54 | +0.22 | 8 | 8 | `e29` (ok, mole `e29`) | `e29` (ok) | 4 / 38 | 0.970 | 0.899 | +0.707 | +0.384 | 921.8s | PASS |

### Extension Shard Manifest Audit (`results/replication/v1.4`)

| shard | verified seeds | planned seeds | pending in-flight seeds | runner git_sha | llm_calls | est. cost (USD) |
|---|---|---|---|---|---:|---:|
| `opencode-gemini-4-carbon/hard-s30-33` | `30` | `30, 31, 32, 33` | `31, 32, 33` | `7232f800` | 113 | $1.77 |
| `opencode-gemini-4-carbon/hard-s34-37` | `34` | `34, 35, 36, 37` | `35, 36, 37` | `7232f800` | 84 | $1.52 |
| `opencode-gemini-4-carbon/hard-s42-44` | `42` | `42, 43, 44` | `43, 44` | `2d87d0be` | 75 | $1.31 |
| `opencode-gemini-4-carbon/hard-s45-47` | `45` | `45, 46, 47` | `46, 47` | `2d87d0be` | 157 | $2.82 |
| `opencode-gemini-4-carbon/hard-s57-59` | `57` | `57, 58, 59` | `58, 59` | `7232f800` | 77 | $1.24 |

## 3. Complete `solver-hard-seeds30to59` Out-of-Sample Reference Schedule (`n=30`)

| seed | solver score | solver day | solver accused (mole) | outcome | solver P(accused) | solver luck-adj. | frontier `opencode-gemini-4-carbon` status |
|---:|---:|---:|---|---|---:|---:|---|
| 30 | -1.00 | 18 | `e26` (mole `e15`) | wrong | 0.858 | +0.175 | verified (`opencode-gemini-4-carbon/hard-s30-33`: `+0.54`, day 11, `P=0.909`) |
| 31 | +0.52 | 9 | `e14` (mole `e14`) | correct | 1.000 | +0.520 | pending |
| 32 | -1.00 | 9 | `e11` (mole `e20`) | wrong | 0.908 | +0.535 | pending |
| 33 | +0.53 | 10 | `e32` (mole `e32`) | correct | 0.986 | +0.509 | pending |
| 34 | +0.70 | 6 | `e29` (mole `e29`) | correct | 0.978 | +0.663 | verified (`opencode-gemini-4-carbon/hard-s34-37`: `+0.82`, day 8, `P=0.650`) |
| 35 | +0.68 | 9 | `e17` (mole `e17`) | correct | 0.938 | +0.576 | pending |
| 36 | +0.77 | 5 | `e37` (mole `e37`) | correct | 0.964 | +0.706 | pending |
| 37 | +0.77 | 5 | `e25` (mole `e25`) | correct | 0.924 | +0.635 | pending |
| 38 | +0.00 | 21 | `None` (mole `e21`) | abstain | - | +0.000 | pending |
| 39 | +0.70 | 6 | `e28` (mole `e28`) | correct | 0.998 | +0.697 | pending |
| 40 | +0.55 | 8 | `e13` (mole `e13`) | correct | 0.998 | +0.547 | pending |
| 41 | +0.57 | 10 | `e36` (mole `e36`) | correct | 0.995 | +0.562 | pending |
| 42 | +0.51 | 10 | `e19` (mole `e19`) | correct | 0.997 | +0.505 | verified (`opencode-gemini-4-carbon/hard-s42-44`: `+0.57`, day 12, `P=0.969`) |
| 43 | +0.69 | 8 | `e12` (mole `e12`) | correct | 0.986 | +0.666 | pending |
| 44 | +0.75 | 8 | `e07` (mole `e07`) | correct | 0.941 | +0.647 | pending |
| 45 | +0.49 | 11 | `e11` (mole `e11`) | correct | 0.955 | +0.423 | verified (`opencode-gemini-4-carbon/hard-s45-47`: `+0.59`, day 16, `P=0.973`) |
| 46 | +0.70 | 7 | `e07` (mole `e07`) | correct | 0.966 | +0.642 | pending |
| 47 | +0.43 | 11 | `e28` (mole `e28`) | correct | 0.889 | +0.271 | pending |
| 48 | +0.46 | 9 | `e10` (mole `e10`) | correct | 0.955 | +0.394 | pending |
| 49 | +0.80 | 6 | `e31` (mole `e31`) | correct | 0.999 | +0.798 | pending |
| 50 | +0.78 | 5 | `e27` (mole `e27`) | correct | 1.000 | +0.780 | pending |
| 51 | +0.72 | 5 | `e38` (mole `e38`) | correct | 0.935 | +0.608 | pending |
| 52 | +0.66 | 6 | `e39` (mole `e39`) | correct | 0.963 | +0.599 | pending |
| 53 | +0.62 | 9 | `e04` (mole `e04`) | correct | 0.995 | +0.612 | pending |
| 54 | +0.50 | 11 | `e30` (mole `e30`) | correct | 0.986 | +0.479 | pending |
| 55 | +0.72 | 7 | `e25` (mole `e25`) | correct | 0.968 | +0.665 | pending |
| 56 | +0.53 | 14 | `e07` (mole `e07`) | correct | 0.995 | +0.522 | pending |
| 57 | +0.54 | 8 | `e29` (mole `e29`) | correct | 0.899 | +0.384 | verified (`opencode-gemini-4-carbon/hard-s57-59`: `+0.76`, day 8, `P=0.970`) |
| 58 | +0.53 | 9 | `e26` (mole `e26`) | correct | 0.942 | +0.441 | pending |
| 59 | +0.72 | 5 | `e28` (mole `e28`) | correct | 0.984 | +0.692 | pending |

## 4. Deterministic Replay Integrity and Provenance

| check | result | status |
|---|---:|---|
| Tracked `v1.4` `episodes.jsonl` shards audited | `33` | PASS |
| Episodes replay-verified in fresh `canary.env.Env` (`v1.4`) | `685 / 685` | PASS |
| Score, accusation, or step-level replay mismatches | `0` | PASS |
| Episodes with `rc == timeout`, `end_reason == error`, or `valid == False` | `0` | PASS |
| Duplicate `(agent, tier, seed)` tuples across `0-59` | `0` | PASS |
| OpenCode client-only steps skipped / truncated outputs byte-verified | `1 / 2` | PASS |

**In-repo shard locations and keyless reproduction commands:**

- Primary (`0-29`) shards: `data/runs/committed/v1.4`
- Out-of-sample replication (`30-59`) shards: `results/replication/v1.4`
- Generator script: `scripts/v14_replication_report.py`

```bash
python scripts/v14_replication_report.py
python scripts/v14_replication_report.py --check
PYTHONPATH=. python scripts/verify_replay.py results/replication/v1.4
```
