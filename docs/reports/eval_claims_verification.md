# Canary v1.4 Eval Claims, Replay Cache, and Hygiene Verification

Every number in this report is deterministically recomputed offline (zero API keys, zero network calls) by `scripts/verify_eval_claims.py` from the committed caches under `data/runs/committed/v1.4/` and `results/`.

## Reproduce and Verify

```bash
python scripts/verify_eval_claims.py
python scripts/verify_eval_claims.py --check --diff-base origin/justSilas
pytest -q tests/test_verify_eval_claims.py
```

- Schema: `eval_claims_manifest_v2` (`tiers_version = v1.4`, float tolerance `1e-09`)
- Overall verdict: **PASS** (5/5 deterministic gates)

## Five-Gate Summary

| gate | status | violations | warnings |
|---|---|---:|---:|
| `gate1_headline_and_gap_table_numbers` | **PASS** | 0 | 0 |
| `gate2_replay_cache_completeness_and_step_consistency` | **PASS** | 0 | 0 |
| `gate3_baselines_and_judge_spread_bands` | **PASS** | 0 | 0 |
| `gate4_version_and_preregistration_hygiene` | **PASS** | 0 | 0 |
| `gate5_protected_paths_and_secret_hygiene` | **PASS** | 0 | 0 |

## Gate 1: Headline and Gap Table Numbers (Paired Seeds 0-29)

Recomputed with 10,000 deterministic paired bootstrap resamples (`rng_seed=0`) over seeds 0-29 and cross-checked against `README.md`, `docs/reports/gap.md`, `data/runs/committed/v1.4/paired_table_gemini.json` (16 committed rows within `1e-9`), `paired_table_gemini.md`, and `results/judge_table.md`.

| cohort | n | score +/- 95% CI | solver (same seeds) | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] | mean P(accused) |
|---|---:|---:|---:|---:|---:|---:|
| opencode-gemini-4-carbon (hard) | 30 | +0.322 +/- 0.199 | +0.499 +/- 0.119 | 65% [24%, 98%] | 72% [52%, 91%] | 0.88 |
| opencode-gemini-4-carbon (medium) | 30 | +0.713 +/- 0.042 | +0.645 +/- 0.087 | 111% [99%, 127%] | 101% [85%, 119%] | 0.96 |
| inproc-gemini-4-carbon (hard) | 30 | +0.473 +/- 0.118 | +0.499 +/- 0.119 | 95% [62%, 140%] | 84% [65%, 106%] | 0.93 |
| inproc-gemini-4-carbon (medium) | 30 | +0.530 +/- 0.138 | +0.645 +/- 0.087 | 82% [56%, 108%] | 74% [52%, 99%] | 0.93 |
| opencode-gemini-3.5-flash (hard) | 30 | +0.373 +/- 0.177 | +0.499 +/- 0.119 | 75% [36%, 123%] | 22% [-23%, 63%] | 0.71 |
| opencode-gpt-5.5 (hard) | 30 | +0.504 +/- 0.064 | +0.499 +/- 0.119 | 101% [79%, 140%] | 84% [67%, 103%] | 0.94 |
| reference solver (hard) | 30 | +0.499 +/- 0.119 | +0.499 +/- 0.119 | 100% | 100% (EV +0.499) | -- |
| reference solver (medium) | 30 | +0.645 +/- 0.087 | +0.645 +/- 0.087 | 100% | 100% (EV +0.645) | -- |

## Gate 2: Replay Cache Completeness and Step Consistency

All **150** primary v1.4 frontier episodes (`0..29` per cohort), **32** pre-registered extension/second-family episodes (`v1.4/opencode-gemini-4-carbon-ext/hard` (`n=2`), `v1.4/opencode-gpt-5.5/hard` (`n=30`)), and **90** committed v1.4 solver reference episodes (`solver:medium` `0..29` `n=30`; `solver:hard` `0..59` `n=60` across `0-19`, `20-29`, `30-59`; **272** total) have complete `0..29` primary seed sets, `0` duplicate seeds per cohort, valid score invariants, `0` timeout/crash episodes marked valid (`rc=0` no-accusation stops score `0.0` per `ca0a0dc0`), and 100% tool-step and verdict replay agreement in `Env(tier, seed)` under `TIERS_VERSION == "v1.4"` (including post-`1bc3e281` `data.detail` compatibility on `invalid arguments` steps).

| cohort | tier | agent | valid | invalid | dup seeds | step mismatches | replay matched | mean score |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `v1.4/opencode-gemini-4-carbon/medium` | medium | `opencode:google/gemini-4-carbon` | 30 | 0 | 0 | 0 | 30/30 | +0.713000 |
| `v1.4/opencode-gemini-4-carbon/hard` | hard | `opencode:google/gemini-4-carbon` | 30 | 0 | 0 | 0 | 30/30 | +0.322333 |
| `v1.4/inproc-gemini-4-carbon/medium` | medium | `gemini:gemini-4-carbon` | 30 | 0 | 0 | 0 | 30/30 | +0.530333 |
| `v1.4/inproc-gemini-4-carbon/hard` | hard | `gemini:gemini-4-carbon` | 30 | 0 | 0 | 0 | 30/30 | +0.473000 |
| `v1.4/opencode-gemini-3.5-flash/hard` | hard | `opencode:google/gemini-3.5-flash` | 30 | 0 | 0 | 0 | 30/30 | +0.373000 |
| `v1.4/opencode-gemini-4-carbon-ext/hard` | hard | `opencode:google/gemini-4-carbon` | 2 | 0 | 0 | 0 | 2/2 | +0.745000 |
| `v1.4/opencode-gpt-5.5/hard` | hard | `opencode:openai/gpt-5.5` | 30 | 0 | 0 | 0 | 30/30 | +0.503667 |
| `v1.4/reference/solver:medium` | medium | `solver` | 30 | 0 | 0 | 0 | 30/30 | +0.645000 |
| `v1.4/reference/solver:hard` | hard | `solver` | 60 | 0 | 0 | 0 | 60/60 | +0.498500 |

- Gemini effort ladder (`results/gemini/ladder_episodes.jsonl.gz`): 550 native + 37 imported = 587 valid episodes, 0 invariant violations, 0 error/timeout leaks.

## Gate 3: Baselines and Judge Spread Bands

### Judge Episodes (`results/judge_episodes.jsonl`)

| baseline | easy | medium | hard |
|---|---:|---:|---:|
| `do_nothing` | +0.0000 (n=40) | +0.0000 (n=40) | +0.0000 (n=40) |
| `stop_early` | +0.0000 (n=40) | +0.0000 (n=40) | +0.0000 (n=40) |
| `guess_day1` | -0.7500 (n=40) | -0.9000 (n=40) | -0.9500 (n=40) |

### 300-Secret Judge Spread (`results/solver_range/`)

| tier | `guess_day1` mean | `guess_day1` p95 | `guess_day1` max | `solver` mean | `solver` 5th-95th pct |
|---|---:|---:|---:|---:|---:|
| easy | -0.839 | -0.70 | -0.55 | +0.774 | [+0.74, +0.80] |
| medium | -0.906 | -0.80 | -0.70 | +0.630 | [+0.56, +0.69] |
| hard | -0.953 | -0.85 | -0.80 | +0.567 | [+0.49, +0.64] |

- Harbor 10-task hard oracle band (`results/oracle_range_v1.4.json`, 200 builds): 90% range **+0.39 to +0.68**, mean **+0.569**, sd **0.094** (matches `README.md` exact figures; `do_nothing` and `stop_early` equal `0.0` at `k=2,3,10,20`).

## Gate 4: Version and Pre-Registration Hygiene

- Paired v1.4 rows verified free of `v1.2`, `v1.3`, and `superseded`: **16**
- `results/judge_table.md` v1.4 reported rows verified isolated from earlier tiers and `superseded`: **18**
- `data/runs/committed/v1.4/**/meta.json` files verified (`tiers_version == "v1.4"`): **22** (5 post-hoc locked primary frontier cohorts on dev seeds `0..29` + 2 pre-registered extension cohort(s))
- Seed lock (`671ed96` post-hoc lock on `0-29`, `PRIMARY` vs `REPLICATION`) and pre-registered extensions (`f9fb7a4a` `30-59`, `cf394894` `gpt-5.5`) in `docs/reports/gap.md`: **verified**
- Active docs scanned for unlabelled stale claims: `README.md, docs/DEMO.md, docs/DIFFICULTY.md, docs/EXPLOITS.md, docs/reports/gap.md, results/judge_table.md` (3 explicitly disclosed historical notes permitted)

## Gate 5: Protected-Path and Secret Hygiene

- Protected-path rules enforced from `.github/protected-paths.txt`: **15** rules (verified via `--diff-base origin/justSilas` and working-tree `HEAD`)
- Secret and mole-leak pattern classes scanned across `results/eval*` and `docs/reports/`: **7** pattern classes (Google API keys, sk-* keys, OAuth and provider tokens, PEM private keys, secret env assignments with `CANARY_WORLD_SECRET=canary-demo-live` public demo placeholder exempted, judge SALT bytes, and JSON mole-id world fields)
