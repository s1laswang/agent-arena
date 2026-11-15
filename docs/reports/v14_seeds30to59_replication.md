# v1.4 Selected Fleet Replication (Non-Primary, Incomplete 30-59 Cohort)

## Post-Hoc Primary Lock, Pre-Registered Extension Rule, and Headline Summary

Per the post-hoc primary seed lock (`671ed96`, committed 28 s after `8fd4dec` to prevent reruns or cherry-picking, not a pre-registration) and the pre-registered `30-59` extension rule (`f9fb7a4a`, committed before runs and stopped early at partial `n=2` `seeds 34, 37` in `opencode-gemini-4-carbon-ext`) in [gap.md](gap.md), Canary reports the post-hoc locked `0-29` `hard` primary headline and this incomplete `30-59` fleet replication slice strictly separately:

1. **Post-hoc locked primary headline (`data/runs/committed/v1.4`, dev seeds `0-29`, `n=30`, locked in `671ed96` 28 s after `8fd4dec`):** OpenCode + `gemini-4-carbon` over MCP (the judges' harness) scores **`+0.322 +/- 0.199`** against the paired reference solver's **`+0.499 +/- 0.119`** on the exact same 30 seeds, giving **`65% [24%, 98%]` raw** (`-0.177 +/- 0.194` paired diff) and **`72% [52%, 91%]` luck-adjusted** (`+0.360` vs `+0.499`; 10,000-resample paired bootstrap 95% CIs). Both primary 95% CIs exclude `100%` parity, and this post-hoc locked primary row is never replaced. Detailed trajectory accounting is in [failure_analysis_v1.4.md](failure_analysis_v1.4.md) and [paired_table_gemini.md](../../data/runs/committed/v1.4/paired_table_gemini.md).
2. **Selected Fleet Replication (Non-Primary, Incomplete 30-59 Cohort; `results/selected_fleet_replication/v1.4`, `n=7` of `30` planned seeds):** `7` `hard` episodes (`seeds 30, 34, 42, 45, 48, 57, 58`; `23/30` seeds incomplete at fleet cutoff, distinct from the pre-registered `opencode-gemini-4-carbon-ext` G1 extension in [gap.md](gap.md), which stopped early at partial `n=2` on `seeds 34, 37` to preserve shared quota) completed cleanly across the sequential 3-to-4-seed fleet shards under raised OpenCode runner timeouts and passed deterministic step-by-step replay verification, paired against `solver-hard-seeds30to59` (`n=30`, full seeds `30-59` mean `+0.498 +/- 0.156`, luck-adjusted `+0.542`). Because sequential multi-seed workers completed their shard-head seeds first (wall-clock completion selection), this incomplete slice is reported strictly as a non-primary selected fleet replication rather than an unbiased `30-59` cohort mean. On the `7` paired fleet seeds, OpenCode `gemini-4-carbon` scores `+0.639 +/- 0.079` vs same-seed solver `+0.319` (`200% [116%, 837%]` raw; `109% [70%, 155%]` luck-adjusted).
3. **Exploratory pooled reference (`0-29` post-hoc locked primary + `7` selected fleet seeds, `n=37` paired `hard` seeds; non-primary, never substituted for the `0-29` primary headline, and distinct from the `n=32` `0-29 + 34, 37` G1 pool in [gap.md](gap.md)):** Across all `37` replay-verified `hard` seeds combined, OpenCode `gemini-4-carbon` scores `+0.382 +/- 0.166` vs paired solver `+0.465` (`82% [46%, 124%]` raw, paired diff `-0.083 +/- 0.183`) and **`78% [60%, 97%]` luck-adjusted** (`+0.380` vs `+0.486`).

Every figure in this report is computed deterministically without API keys by [scripts/v14_replication_report.py](../../scripts/v14_replication_report.py), which replays every episode in a fresh `canary.env.Env` and aborts on any score, accusation, step-level, manifest, orphan-transcript, duplicate-seed, or timeout hygiene violation.

## 1. Paired Statistical Tables Across Cohorts

Columns match `scripts/paired_gemini.py`: `score +/- 95% CI` uses normal-approximation half-width; `frontier / solver [95% CI]` and `luck-adj. / solver [95% CI]` use 10,000 paired bootstrap resamples (`rng_seed=0`) over shared seeds; `luck-adj. score` evaluates each accusation at `P(accused) * V - (1 - P(accused))` under `canary.analysis.accuse.audit_episode` (`0` on abstention).

### 1A. Post-Hoc Locked Primary Cohort (`data/runs/committed/v1.4`, Seeds `0-29`)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (judges' harness, PRIMARY) | 30 | +0.322 +/- 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | +0.499 | 65% [24%, 98%] | -0.177 +/- 0.194 | +0.360 | **72% [52%, 91%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | +0.473 +/- 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | +0.499 | 95% [62%, 140%] | -0.026 +/- 0.184 | +0.421 | **84% [65%, 106%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family) | 30 | +0.373 +/- 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | +0.499 | 75% [36%, 123%] | -0.126 +/- 0.221 | +0.110 | **22% [-23%, 63%]** |
| hard | OpenCode + gpt-5.5 over MCP (second frontier family, OpenAI) | 30 | +0.504 +/- 0.064 | 0.93 | 0.93 | 10.2 | 0.94 | +0.499 | 101% [79%, 140%] | +0.005 +/- 0.141 | +0.418 | **84% [67%, 103%]** |
| hard | reference solver (seeds 0-29) | 30 | +0.499 +/- 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | +0.499 | - | - | +0.499 | - |
| medium | OpenCode + gemini-4-carbon over MCP (judges' harness, medium context) | 30 | +0.713 +/- 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | +0.645 | 111% [99%, 127%] | +0.068 +/- 0.080 | +0.652 | **101% [85%, 119%]** |
| medium | in-process gemini-4-carbon (medium context) | 30 | +0.530 +/- 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | +0.645 | 82% [56%, 108%] | -0.115 +/- 0.170 | +0.479 | **74% [52%, 99%]** |
| medium | reference solver (medium context, seeds 0-29) | 30 | +0.645 +/- 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | +0.645 | - | - | +0.645 | - |

### 1B. Selected Fleet Replication (Non-Primary, Incomplete 30-59 Cohort; `results/selected_fleet_replication/v1.4`)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (selected fleet replication, incomplete 30-59) | 7 | +0.639 +/- 0.079 | 1.00 | 1.00 | 11.3 | 0.90 | +0.319 | 200% [116%, 837%] | +0.320 +/- 0.401 | +0.467 | **109% [70%, 155%]** |
| hard | solver-hard-seeds30to59 (paired on the 7 selected fleet seed(s)) | 7 | +0.319 +/- 0.434 | 0.86 | 1.00 | 10.1 | 0.94 | +0.319 | - | - | +0.427 | - |
| hard | solver-hard-seeds30to59 (full 30-seed cohort) | 30 | +0.498 +/- 0.156 | 0.90 | 0.97 | 8.4 | 0.96 | +0.498 | - | - | +0.542 | - |
| hard | grok_tactics (seeds 30-59) | 30 | +0.314 +/- 0.126 | 0.83 | 0.87 | 11.1 | 0.97 | +0.498 | 63% [35%, 106%] | -0.184 +/- 0.199 | +0.321 | **59% [44%, 75%]** |
| hard | heuristic (seeds 30-59) | 30 | +0.118 +/- 0.163 | 0.87 | 1.00 | 15.6 | 0.82 | +0.498 | 24% [-11%, 60%] | -0.380 +/- 0.227 | +0.062 | **11% [-13%, 32%]** |
| hard | logs_only (seeds 30-59) | 30 | -0.942 +/- 0.114 | 0.03 | 1.00 | 10.0 | 0.01 | +0.498 | -189% [-292%, -141%] | -1.440 +/- 0.185 | -0.983 | **-181% [-206%, -164%]** |
| hard | do_nothing (seeds 30-59) | 30 | +0.000 +/- 0.000 | 0.00 | 0.00 | - | - | +0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | +0.000 | **0% [0%, 0%]** |
| hard | stop_early (seeds 30-59) | 30 | +0.000 +/- 0.000 | 0.00 | 0.00 | - | - | +0.498 | 0% [0%, 0%] | -0.498 +/- 0.156 | +0.000 | **0% [0%, 0%]** |
| hard | random (seeds 30-59) | 30 | -0.833 +/- 0.136 | 0.00 | 0.83 | 6.2 | 0.03 | +0.498 | -167% [-250%, -127%] | -1.331 +/- 0.225 | -0.791 | **-146% [-176%, -118%]** |
| hard | restrict_all (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 9.0 | 0.01 | +0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.993 | **-183% [-208%, -166%]** |
| hard | guess_day1 (seeds 30-59) | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | +0.498 | -201% [-306%, -159%] | -1.498 +/- 0.156 | -0.950 | **-175% [-199%, -159%]** |

### 1C. Exploratory Pooled Hard Cohort (`0-29` Locked Primary + Selected Fleet `30-59`, Non-Primary)

| tier | cohort / run | n | score +/- 95% CI | accuracy | accused | mean day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| hard | OpenCode + gemini-4-carbon over MCP (exploratory pool: 0-29 + selected fleet 30-59) | 37 | +0.382 +/- 0.166 | 0.86 | 0.97 | 12.8 | 0.89 | +0.465 | 82% [46%, 124%] | -0.083 +/- 0.183 | +0.380 | **78% [60%, 97%]** |
| hard | reference solver (paired on the 37 pooled frontier seeds) | 37 | +0.465 +/- 0.126 | 0.95 | 1.00 | 10.5 | 0.96 | +0.465 | - | - | +0.486 | - |
| hard | reference solver (all committed hard seeds 0-59) | 60 | +0.498 +/- 0.097 | 0.93 | 0.98 | 9.5 | 0.96 | +0.498 | - | - | +0.521 | - |

**Statistical reading of the `7`-seed selected fleet slice and `37`-seed exploratory pool:**
- **Non-primary incomplete-cohort caveat (`7/30` completed, `23` pending):** Each fleet worker ran a 3-to-4-seed sequential shard (`hard-s30-33`, `hard-s34-37`, `hard-s42-44`, `hard-s45-47`, `hard-s48-51`, `hard-s57-59`), so completed episodes represent shard-head / shorter-cumulative-wall-clock realizations rather than a complete `30`-seed sample. Accordingly, Section 1B and Section 1C are diagnostic replication tables and do not supersede the complete `n=30` (`0-29`) post-hoc locked primary headline.
- **Why luck adjustment stabilizes small-`n` raw ratios:** Across all 30 out-of-sample seeds `30-59`, `solver-hard-seeds30to59` averages `+0.498 +/- 0.156` (`90%` accuracy, only 2 wrong accusations out of 30). However, the `7` completed fleet seeds include seed `30` (solver accused `e26` vs mole `e15` at `P = 0.858`, raw `-1.000`, luck-adjusted `+0.175`). A single `-1.000` realization depresses the `7`-seed raw solver denominator to `+0.319`, inflating the raw `7`-seed ratio to `200%`, whereas the posterior-expected (luck-adjusted) solver score on those same `7` seeds is `+0.427` (`109%` luck-adjusted ratio).
- **Sub-0.85 commitment still appears out of sample:** Even among correct accusations, seed `34` (`P(accused) = 0.650` on day `8`, raw `+0.82` -> luck-adjusted `+0.183` vs solver `+0.663` at `P = 0.978`), mirroring the locked primary `0-29` finding that OpenCode `gemini-4-carbon` sometimes commits before canary leaks isolate a single suspect.
- **Wall-clock regime (`min = 921.8s`, `max = 3775.2s`):** Every completed `hard` episode in `30-59` ran longer than `900s` (`7/7` > `900s`), confirming that early `900s` runner caps measured wall-clock timeout rather than decision quality and justifying the raised `--timeout 3600` / `10800` replication protocol.

## 2. Replay-Verified Hard Episodes in Selected Fleet Replication (Per-Seed Comparison)

| seed | shard | Gemini score | solver score | diff (F - S) | Gemini day | solver day | Gemini accused (mole) | solver accused | canaries / interviews | Gemini P(acc) | solver P(acc) | Gemini luck-adj. | solver luck-adj. | wall_s | replay |
|---:|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 30 | `opencode-gemini-4-carbon/hard-s30-33` | +0.54 | -1.00 | +1.54 | 11 | 18 | `e15` (ok, mole `e15`) | `e26` (WRONG) | 6 / 61 | 0.909 | 0.858 | +0.400 | +0.175 | 1597.9s | PASS |
| 34 | `opencode-gemini-4-carbon/hard-s34-37` | +0.82 | +0.70 | +0.12 | 8 | 6 | `e29` (ok, mole `e29`) | `e29` (ok) | 3 / 49 | 0.650 | 0.978 | +0.183 | +0.663 | 1499.2s | PASS |
| 42 | `opencode-gemini-4-carbon/hard-s42-44` | +0.57 | +0.51 | +0.06 | 12 | 10 | `e19` (ok, mole `e19`) | `e19` (ok) | 8 / 16 | 0.969 | 0.997 | +0.521 | +0.505 | 1329.9s | PASS |
| 45 | `opencode-gemini-4-carbon/hard-s45-47` | +0.59 | +0.49 | +0.10 | 16 | 11 | `e11` (ok, mole `e11`) | `e11` (ok) | 6 / 88 | 0.973 | 0.955 | +0.547 | +0.423 | 2858.9s | PASS |
| 48 | `opencode-gemini-4-carbon/hard-s48-51` | +0.61 | +0.46 | +0.15 | 13 | 9 | `e10` (ok, mole `e10`) | `e10` (ok) | 4 / 79 | 0.916 | 0.955 | +0.475 | +0.394 | 3775.2s | PASS |
| 57 | `opencode-gemini-4-carbon/hard-s57-59` | +0.76 | +0.54 | +0.22 | 8 | 8 | `e29` (ok, mole `e29`) | `e29` (ok) | 4 / 38 | 0.970 | 0.899 | +0.707 | +0.384 | 921.8s | PASS |
| 58 | `opencode-gemini-4-carbon/hard-s57-59` | +0.58 | +0.53 | +0.05 | 11 | 9 | `e26` (ok, mole `e26`) | `e26` (ok) | 7 / 61 | 0.908 | 0.942 | +0.435 | +0.441 | 2733.8s | PASS |

### Selected Fleet Shard Manifest Audit (`results/selected_fleet_replication/v1.4`)

| shard | verified seeds | planned seeds | pending incomplete seeds | runner git_sha | llm_calls | est. cost (USD) |
|---|---|---|---|---|---:|---:|
| `opencode-gemini-4-carbon/hard-s30-33` | `30` | `30, 31, 32, 33` | `31, 32, 33` | `7232f800` | 113 | $1.77 |
| `opencode-gemini-4-carbon/hard-s34-37` | `34` | `34, 35, 36, 37` | `35, 36, 37` | `7232f800` | 84 | $1.52 |
| `opencode-gemini-4-carbon/hard-s42-44` | `42` | `42, 43, 44` | `43, 44` | `2d87d0be` | 75 | $1.31 |
| `opencode-gemini-4-carbon/hard-s45-47` | `45` | `45, 46, 47` | `46, 47` | `2d87d0be` | 157 | $2.82 |
| `opencode-gemini-4-carbon/hard-s48-51` | `48` | `48, 49, 50, 51` | `49, 50, 51` | `ac5b5ef8` | 136 | $2.13 |
| `opencode-gemini-4-carbon/hard-s57-59` | `57, 58` | `57, 58, 59` | `59` | `7232f800` | 189 | $3.12 |

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
| 48 | +0.46 | 9 | `e10` (mole `e10`) | correct | 0.955 | +0.394 | verified (`opencode-gemini-4-carbon/hard-s48-51`: `+0.61`, day 13, `P=0.916`) |
| 49 | +0.80 | 6 | `e31` (mole `e31`) | correct | 0.999 | +0.798 | pending |
| 50 | +0.78 | 5 | `e27` (mole `e27`) | correct | 1.000 | +0.780 | pending |
| 51 | +0.72 | 5 | `e38` (mole `e38`) | correct | 0.935 | +0.608 | pending |
| 52 | +0.66 | 6 | `e39` (mole `e39`) | correct | 0.963 | +0.599 | pending |
| 53 | +0.62 | 9 | `e04` (mole `e04`) | correct | 0.995 | +0.612 | pending |
| 54 | +0.50 | 11 | `e30` (mole `e30`) | correct | 0.986 | +0.479 | pending |
| 55 | +0.72 | 7 | `e25` (mole `e25`) | correct | 0.968 | +0.665 | pending |
| 56 | +0.53 | 14 | `e07` (mole `e07`) | correct | 0.995 | +0.522 | pending |
| 57 | +0.54 | 8 | `e29` (mole `e29`) | correct | 0.899 | +0.384 | verified (`opencode-gemini-4-carbon/hard-s57-59`: `+0.76`, day 8, `P=0.970`) |
| 58 | +0.53 | 9 | `e26` (mole `e26`) | correct | 0.942 | +0.441 | verified (`opencode-gemini-4-carbon/hard-s57-59`: `+0.58`, day 11, `P=0.908`) |
| 59 | +0.72 | 5 | `e28` (mole `e28`) | correct | 0.984 | +0.692 | pending |

## 4. Deterministic Replay Integrity and Provenance

| check | result | status |
|---|---:|---|
| Tracked `v1.4` `episodes.jsonl` shards audited | `37` | PASS |
| Episodes replay-verified in fresh `canary.env.Env` (`v1.4`) | `749 / 749` | PASS |
| Score, accusation, or step-level replay mismatches | `0` | PASS |
| Episodes with `rc == timeout`, invalid `end_reason == error`, or `valid == False` | `0` | PASS |
| Duplicate `(agent, tier, seed)` tuples within cohort (`0-29` primary, `30-59` G1 ext, `30-59` fleet repl) | `0` | PASS |
| OpenCode client-only steps skipped / truncated outputs byte-verified | `1 / 2` | PASS |

**In-repo shard locations and keyless reproduction commands:**

- Post-hoc locked primary (`0-29`) shards (plus committed `opencode-gemini-4-carbon-ext` partial `n=2` G1 extension and `reference/solver-hard-seeds30to59`): `data/runs/committed/v1.4`
- Selected fleet replication (incomplete `30-59` cohort) shards: `results/selected_fleet_replication/v1.4`
- Consolidated `opencode-gemini-4-carbon-ext` shard and paired bootstrap tables (`fleet7` `n=7`, deduplicated `ext8` `n=8` keeping committed `[34, 37]`, and exploratory `pooled38` `n=38`): `results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/` ([README.md](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/README.md))
- Generator script: `scripts/v14_replication_report.py`

```bash
python scripts/v14_replication_report.py
python scripts/v14_replication_report.py --check
PYTHONPATH=. python scripts/verify_replay.py results/selected_fleet_replication/v1.4
```
