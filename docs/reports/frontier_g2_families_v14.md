# Canary v1.4 G2 Gemini 4 Families Replay, Timeout, and Paired Bayesian Audit

Every figure in this report is deterministically computed on pure CPU by `scripts/frontier_g2_families_audit.py` using `scripts.verify_replay`, `1bc3e281`-compatible `norm_result` step replay, `canary.analysis.accuse`, and `scripts/paired_v13.py` (`boot_ratio`, `post_expected`), with zero live API calls and zero `.git` runtime subprocess calls.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_g2_families_audit.py --check
```

## 1. Provenance Honesty, Locked Primary Headline, and Executive Summary

- **Locked primary headline (`Panel Fix A`) & PR #81 provenance:** OpenCode `gemini-4-carbon` on `v1.4` `hard` `seeds 0-29` remains **locked as the primary headline** (`0.322` raw / `65% [24%, 98%]` vs solver `0.499`, and `0.360` luck-adjusted / `72% [52%, 91%]` vs solver `0.499`). Primary `seeds 0-29` (`8fd4dec`, OpenCode `1.18.29`) are governed by a **post-hoc lock** (`671ed96`, committed `28 s` after `8fd4dec`), **not a pre-registration**. By contrast, the G2 cross-family runs (`opencode-gemini-4-argon` and `opencode-gemini-4-hydrogen`, `n=30` each on `hard` `seeds 0-29`, cited as PR #81 in `docs/reports/CEO.md` and `docs/reports/gap.md` at `9225f2ad`) were **pre-registered** in `f9fb7a4a` (`docs/agents/GEMINI-SESSIONS.md`), executed at `cf394894` on OpenCode `1.19.5` (seeing the post-`1bc3e281` specific tool error details and reworded `careful` mole rule), and landed at `origin/g2-families@8911130e`.
- **100% replay, CHIEF DATA RULE, and committed `v1.4` corpus parity (`60/60` G2 + `472/472` committed = `532/532`):** All `30/30` `gemini-4-argon` hard episodes and `30/30` `gemini-4-hydrogen` hard episodes (`60/60` G2, `120/120` paired hard `0-29` with `solver` + `gemini-4-carbon`, plus all `472/472` committed `v1.4` episodes including `opencode-gpt-5.5/hard` `n=30` with `2` clean `rc=0` non-accuse `final_day=0` exits on seeds `[0, 17]`) pass `scripts.verify_replay` and step-by-step `Env` replay (`0` mismatches, `0` duplicates; `24` argon and `28` hydrogen unwrapped MCP error steps with `0` pre-`1bc3e281` `data={}` steps). Both G2 `episodes.jsonl` files obey the CHIEF DATA RULE (`30/30` `valid=True`, `rc=0`, `0` timeouts, `0` errors), and all `60/60` transcripts pass step parity (`steps_from_events`) with `0` secret/API key leaks and `0` unredacted `thoughtSignature` blobs.
- **Wall-clock timeout finding (`30/30` argon > `900 s`, `0/60` G2 > `3600 s`):** Every single `gemini-4-argon` hard episode exceeds `900 s` (`min = 921.8 s`, `median = 1558.8 s`, `mean = 1726.2 s`, `max = 3269.3 s`: **`30/30` > `900 s`**, **`0/30` > `3600 s`**), matching `gemini-4-carbon` (`30/30` > `900 s`, `5/30` > `3600 s`, `0/30` > `7200 s`) and confirming that a `900 s` cap truncates `100%` of both `carbon` and `argon` hard episodes while `--timeout 3600` accommodates `100%` of `argon` and `hydrogen` (`201.3 s - 615.0 s`, `0/30` > `900 s`).
- **Bayesian luck-adjustment separates `argon` gambles from `hydrogen` and `gpt-5.5` canary discipline:** On raw score, `gemini-4-argon` (`0.512 +/- 0.112`, `103% [71%, 144%]`, `96.7%` accuracy) appears at solver parity alongside `gpt-5.5` (`0.504 +/- 0.064`, `101% [79%, 140%]`), but exact Bayesian luck-adjustment (`post_expected = P*V - (1-P)`) reveals **`0.299 +/- 0.132` (`60% [33%, 85%]`, CI excludes `100%` parity)** because `argon` plants only **`4.80` canaries/ep** while burning **`69.40` interviews/ep**, taking `5` sub-breakeven gambles (`seeds [3, 8, 12, 21, 27]`, `4/5` landing by luck). Conversely, `gemini-4-hydrogen` cuts interviews to `30.20/ep`, plants **`10.03` canaries/ep**, and reaches both raw (`0.575`, `115% [92%, 157%]`) and luck-adjusted parity (`0.485`, `97% [75%, 119%]`, `mean P(accused) = 0.939`), while `gpt-5.5` (`28/28` accused correct, `2` non-accuse `rc=0` exits on seeds `[0, 17]`) lands at `84% [67%, 103%]` luck-adjusted.

## 2. Paired Hard (Seeds 0-29) Score, Luck-Adjusted Gap, and Head-to-Head Comparison

| cohort (v1.4 hard, seeds 0-29) | role | n | raw score +/- 95% CI | raw / solver [95% CI] | paired raw diff | accuracy | accuse day | mean `P(acc)` | luck-adj. (`post_expected`) | luck-adj. / solver [95% CI] | paired LA diff |
|---|---|---:|---|---|---|---:|---:|---:|---|---|---|
| **OpenCode `gemini-4-carbon`** | **locked primary** | 30 | `0.322 +/- 0.199` | **`65% [24%, 98%]`** | `-0.177 +/- 0.194` | `83.3%` | `13.2` | `0.882` | `0.360 +/- 0.105` | **`72% [52%, 91%]`** | `-0.140 +/- 0.104` |
| OpenCode `gemini-4-argon` | G2 family 2 (PR #81) | 30 | `0.512 +/- 0.112` | `103% [71%, 144%]` | `+0.013 +/- 0.169` | `96.7%` | `14.0` | `0.825` | `0.299 +/- 0.132` | **`60% [33%, 85%]`** | `-0.200 +/- 0.138` |
| OpenCode `gemini-4-hydrogen` | G2 family 3 (PR #81) | 30 | `0.575 +/- 0.059` | `115% [92%, 157%]` | `+0.076 +/- 0.132` | `100.0%` | `11.9` | `0.939` | `0.485 +/- 0.097` | **`97% [75%, 119%]`** | `-0.014 +/- 0.113` |
| OpenCode `gpt-5.5` | committed cross-vendor | 30 | `0.504 +/- 0.064` | `101% [79%, 140%]` | `+0.005 +/- 0.141` | `93.3%` | n/a | `0.940` | `0.418 +/- 0.073` | `84% [67%, 103%]` | `-0.082 +/- 0.099` |
| `reference solver` | Bayesian ref | 30 | `0.499 +/- 0.119` | n/a | n/a | `96.7%` | `10.6` | `0.965` | `0.499 +/- 0.064` | n/a | n/a |

- **Head-to-head vs locked `gemini-4-carbon` (`seeds 0-29`):** `gemini-4-argon - gemini-4-carbon` is `+0.190 +/- 0.236` raw (`W/L/T = [19, 11, 0]`) but **`-0.061 +/- 0.164` luck-adjusted** (`W/L/T = [14, 16, 0]`), showing `argon` trails `carbon` in true Bayesian decision quality despite fewer unlucky coin flips. `gemini-4-hydrogen - gemini-4-carbon` is `+0.252 +/- 0.200` raw (`W/L/T = [16, 13, 1]`) and `+0.126 +/- 0.144` luck-adjusted (`W/L/T = [18, 12, 0]`).
- **Cross-family seed concordance:** All three Gemini 4 models identify the true mole on `24/30` seeds; all `5` seeds missed or abstained by `gemini-4-carbon` (`[1, 11, 15, 18, 26]`) are solved by both `argon` and `hydrogen`, while `argon` wrong/abstained seeds rescued by `hydrogen` (`[27]`) are solved cleanly (`seed 27` on G2 `argon`, `P=0.060`).

## 3. Wall-Clock Timeout Audit (`900s` / `1800s` / `3600s` / `7200s`) and Infra-Exclusion Sensitivity

| family | OpenCode (`git_sha`) | min `wall_s` | median `wall_s` | mean `wall_s` | p90 `wall_s` | max `wall_s` | `> 900s` | `> 1800s` | `> 3600s` | `> 7200s` | excluded infra attempts (seeds) | est. cost USD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| `gemini-4-carbon` | `1.18.29` (`035105e9`) | 962.1 | 2351.3 | 2630.4 | 3958.2 | 6591.7 | 30/30 | 24/30 | 5/30 | 0/30 | 25 (`[3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29]`) | $68.33 |
| `gemini-4-argon` | `1.19.5` (`cf394894`) | 921.8 | 1558.8 | 1726.2 | 2587.4 | 3269.3 | 30/30 | 13/30 | 0/30 | 0/30 | 2 (`[21, 22]`) | $51.04 |
| `gemini-4-hydrogen` | `1.19.5` (`cf394894`) | 201.3 | 320.8 | 351.9 | 474.3 | 615.0 | 0/30 | 0/30 | 0/30 | 0/30 | 0 (`[]`) | $28.15 |

### 3.1 Infra-Invalid First-Attempt Zero-Imputation Sensitivity

| family | policy | zeroed seeds (`n`) | raw score | raw / solver [95% CI] | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---|---|---|---|---|
| `gemini-4-carbon` | retry infra-invalid (standard) | `[]` (0) | `0.322` | `65% [24%, 98%]` | `0.360` | `72% [52%, 91%]` |
| `gemini-4-carbon` | `empty_model_response` = 0 (`paired_gemini.py` alt) | `[3, 19, 25, 26, 27]` (5) | `0.279` | `56% [19%, 87%]` | `0.277` | `55% [34%, 77%]` |
| `gemini-4-carbon` | any excluded infra attempt = 0 (strictest) | `[3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29]` (11) | `0.277` | `56% [28%, 84%]` | `0.237` | `47% [28%, 67%]` |
| `gemini-4-argon` | retry infra-invalid (standard) | `[]` (0) | `0.512` | `103% [71%, 144%]` | `0.299` | `60% [33%, 85%]` |
| `gemini-4-argon` | `empty_model_response` = 0 (`paired_gemini.py` alt) | `[21]` (1) | `0.494` | `99% [67%, 141%]` | `0.303` | `61% [34%, 85%]` |
| `gemini-4-argon` | any excluded infra attempt = 0 (strictest) | `[21, 22]` (2) | `0.476` | `95% [63%, 138%]` | `0.301` | `60% [33%, 85%]` |
| `gemini-4-hydrogen` | retry infra-invalid (standard) | `[]` (0) | `0.575` | `115% [92%, 157%]` | `0.485` | `97% [75%, 119%]` |
| `gemini-4-hydrogen` | `empty_model_response` = 0 (`paired_gemini.py` alt) | `[]` (0) | `0.575` | `115% [92%, 157%]` | `0.485` | `97% [75%, 119%]` |
| `gemini-4-hydrogen` | any excluded infra attempt = 0 (strictest) | `[]` (0) | `0.575` | `115% [92%, 157%]` | `0.485` | `97% [75%, 119%]` |

## 4. Behavioral, Canary-Splitting, and Calibration Profile Across Gemini 4 Families

| family | mean steps | interviews / ep (% calls) | accepted canaries / ep | mean reasoning tok | wrong accusations (seeds) | `audit_episode` verdicts (`justified` / `lucky` / `premature-wrong` / `none`) | sub-breakeven seeds (lucky / wrong) | rule citations (`careful` / `framing` / `95% noise` / `interview` / `abstain`) |
|---|---:|---|---:|---:|---|---|---|---|
| `gemini-4-carbon` | 128.03 | 68.03 (53.1%) | 8.47 | 65595 | 4 (`[1, 15, 18, 26]`) | 27 / 2 / 0 / 1 | `[5, 18, 23]` (`[5, 23]` / `[18]`) | 0 / 30 / 9 / 20 / 1 |
| `gemini-4-argon` | 124.77 | 69.40 (55.6%) | 4.80 | 40355 | 1 (`[27]`) | 26 / 3 / 1 / 0 | `[3, 8, 12, 21, 27]` (`[3, 8, 12, 21]` / `[27]`) | 0 / 24 / 3 / 25 / 0 |
| `gemini-4-hydrogen` | 90.67 | 30.20 (33.3%) | 10.03 | 35040 | 0 (`[]`) | 29 / 1 / 0 / 0 | `[19]` (`[19]` / `[]`) | 0 / 28 / 11 / 15 / 0 |
