# V1.6 Social Fairness and Offline Replay Audit

Generated offline via `python scripts/run_v16_social_audit.py --workers 1` using `canary.social_audit` (`audit_text_provider` and `verify_and_score_episodes`) with zero live LLM API calls.

## 1. Executive Summary

- **Tier and seed window**: `hard` (`v1.4`), seeds `30,31,32,33,34,35` (`n=6` per provider).
- **Execution discipline**: `workers=1`, `live_api_calls=0`, `blocked_api_attempts=0`, `offline_enforced=True`.
- **V1.6 TextProvider fairness gate**: **16/16** providers passed all 6 fairness checks and all 6 `canary.social_audit` gates (`all_v16_providers_passed=True`).
- **Bit-exact SolverPolicy calibration parity**: Across all 16 audited V1.6 and sanitized providers on seeds `30,31,32,33,34,35`, `SolverPolicy` achieved **100% bit-exact parity** vs `TemplateProvider` (`max_abs_score_diff=0.0`, exact score, accusation, final day, and tool-call sequence on all `6/6` seeds; `0` false decoy IDs).
- **Shared checkpoint replay verification**: Read-only audit of `/tmp/fleet-momin/shared/v16_runs` discovered `4` `episodes.jsonl` files (`10` records read, `0` invalid/incomplete records skipped cleanly, `5` logged retry entries across `5` `invalid_attempts.jsonl` files) and replay-verified **10/10** valid episodes with **0** mismatches (`all_episode_replays_passed=True`).
- **Raw v1.4 `TemplateProvider` control diagnostic**: Passed 5/6 `canary.social_audit` gates (`public_facts_only`, `lint_clean`, `solver_calibration_parity`, `zero_baselines`, `replay_and_paired_gap`) and failed `anger_words_hygiene` as expected (`8` non-decoy hits on `['recruiter']` across seeds `30,31,32,33,34,35`), confirming the hygiene check catches non-decoy `ANGER_WORDS` leakage that `V16SocialProvider` and `SanitizedTemplateProvider` eliminate.

## 2. Six-Check V1.6 TextProvider Fairness Matrix (Seeds 30,31,32,33,34,35)

| Provider Spec | Mode | Det | No Snoop | Decoy Anger (n1>=3) | Non-Decoy Clean (n2=0) | Bit-Exact Solver Parity | Replay Gate | Lint (msg/iv) | Zero Baselines | Cache Hits / Fallbacks / Stub | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `v16:v1_anchoring_authority_confirmation` | `deterministic_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (994/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |
| `v16:v2_recency_bandwagon_sycophancy` | `deterministic_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1078/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |
| `v16:v3_grudge_falsemem_misforward` | `deterministic_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1072/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |
| `v16:v4_triad_authority_recency_grudge` | `deterministic_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1060/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |
| `v16:v5_full9_cocktail` | `deterministic_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1168/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |
| `v16-gemini-stub:v1_anchoring_authority_confirmation` | `gemini_stub_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (994/6584) | PASS (0.0/0.0) | 0 / 0 / 349 | **PASS** |
| `v16-gemini-stub:v2_recency_bandwagon_sycophancy` | `gemini_stub_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1078/6584) | PASS (0.0/0.0) | 0 / 0 / 421 | **PASS** |
| `v16-gemini-stub:v3_grudge_falsemem_misforward` | `gemini_stub_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1072/6584) | PASS (0.0/0.0) | 0 / 0 / 442 | **PASS** |
| `v16-gemini-stub:v4_triad_authority_recency_grudge` | `gemini_stub_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1060/6584) | PASS (0.0/0.0) | 0 / 0 / 421 | **PASS** |
| `v16-gemini-stub:v5_full9_cocktail` | `gemini_stub_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1168/6584) | PASS (0.0/0.0) | 0 / 0 / 481 | **PASS** |
| `v16-gemini:v1_anchoring_authority_confirmation` | `gemini_cached_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (994/6584) | PASS (0.0/0.0) | 5 / 344 / 0 | **PASS** |
| `v16-gemini:v2_recency_bandwagon_sycophancy` | `gemini_cached_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1078/6584) | PASS (0.0/0.0) | 0 / 421 / 0 | **PASS** |
| `v16-gemini:v3_grudge_falsemem_misforward` | `gemini_cached_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1072/6584) | PASS (0.0/0.0) | 0 / 442 / 0 | **PASS** |
| `v16-gemini:v4_triad_authority_recency_grudge` | `gemini_cached_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1060/6584) | PASS (0.0/0.0) | 0 / 421 / 0 | **PASS** |
| `v16-gemini:v5_full9_cocktail` | `gemini_cached_fallback` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (1168/6584) | PASS (0.0/0.0) | 170 / 311 / 0 | **PASS** |
| `sanitized_template` | `reference_sanitized_template` | PASS (0 err) | PASS (126d/6584iv) | PASS (6/6, min_n1=28) | PASS (hits=0, max_n2=0) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (898/6584) | PASS (0.0/0.0) | 0 / 0 / 0 | **PASS** |

### 2.1 Raw v1.4 Control Diagnostic (`template`)

| Provider Spec | Mode | Det | No Snoop | Decoy Anger | Non-Decoy Clean | Bit-Exact Solver Parity | Replay Gate | Lint (msg/iv) | Zero Baselines | Expected Diagnostic |
|---|---|---|---|---|---|---|---|---|---|---|
| `template` | `v14_template_baseline` | PASS | PASS (126d/6584iv) | FAIL (n2>0: isolated 1/6, min_n1=28) | FAIL (hits=8, max_n2=1, words=['recruiter']) | PASS (6/6, diff=0.000000) | PASS (n=6, err=0) | PASS (898/6584) | PASS (0.0/0.0) | Non-decoy `recruiter` token only |

## 3. SolverPolicy Calibration and Baseline Summary on Seeds 30,31,32,33,34,35

- **SolverPolicy mean score (`hard`, seeds `30,31,32,33,34,35`)**: `0.072` vs `TemplateProvider` `0.072` (`max_abs_score_diff = 0.000000`, accuracy `0.667` vs `0.667`).
- **Heuristic baseline mean score across providers**: `0.243` (paired raw gap vs `SolverPolicy`: `-0.172`, luck-adjusted gap: `+0.393`).
- **Zero-information baselines**: `DoNothing = 0.000`, `StopEarlyQuit = 0.000`, unfinished episode `= 0.000`, Day-1 blind guess `StopEarly = -1.000 <= 0.000` across all audited providers.

## 4. Read-Only Replay Verification of Shared V1.6 Checkpoints

- **Shared root**: `/tmp/fleet-momin/shared/v16_runs` (`read_only=True`, `exists=True`)
- **Checkpoint files audited**: `4` `episodes.jsonl` files; `10` valid episodes replay-verified, `0` invalid/incomplete lines skipped in `episodes.jsonl`, `5` failed retry records logged separately in `5` `invalid_attempts.jsonl` files.

| Checkpoint File | Variant | Provider Spec | Valid Seeds | n Valid | Skipped | Mismatches | Agent Raw | Solver Raw | Agent Luck-Adj | Solver Luck-Adj | Acc | Mean Day | Mean P(acc) | Replay Status |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `inproc/v0_v14_control/hard/episodes.jsonl` | `v0_v14_control` | `template` | `30,31,32,33` | 4 | 0 | 0 | 0.497 | -0.237 | 0.285 | 0.435 | 1.000 | 13.50 | 0.852 | **PASS** |
| `w1_real/inproc/v1_anchoring_authority_confirmation/hard/episodes.jsonl` | `v1_anchoring_authority_confirmation` | `v16:v1_anchoring_authority_confirmation` | `30` | 1 | 0 | 0 | 0.650 | -1.000 | 0.594 | 0.175 | 1.000 | 9.00 | 0.966 | **PASS** |
| `w6_real/inproc/v3_grudge_falsemem_misforward/hard/episodes.jsonl` | `v3_grudge_falsemem_misforward` | `v16:v3_grudge_falsemem_misforward` | `30,31` | 2 | 0 | 0 | 0.645 | -0.240 | 0.604 | 0.348 | 1.000 | 8.00 | 0.975 | **PASS** |
| `w7_real/inproc/v5_full9_cocktail/hard/episodes.jsonl` | `v5_full9_cocktail` | `v16:v5_full9_cocktail` | `30,31,32` | 3 | 0 | 0 | 0.617 | -0.493 | 0.452 | 0.410 | 1.000 | 9.67 | 0.901 | **PASS** |

### 4.1 Per-Episode Replay Audit Table

| Variant | Seed | Agent Score | Solver Score | Accused? | Correct | Day (Solver Day) | True V | P(acc) | Verdict | Agent Luck-Adj | Solver Luck-Adj | Canaries | Interviews | Tool Calls |
|---|---:|---:|---:|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| `v0_v14_control` | 30 | 0.540 | -1.000 | `True` | `True` | 11 (18) | 0.540 | 0.985 | `justified` | 0.517 | 0.175 | 6 | 38 | 88 |
| `v0_v14_control` | 31 | 0.550 | 0.520 | `True` | `True` | 10 (9) | 0.550 | 0.988 | `justified` | 0.531 | 0.520 | 5 | 51 | 93 |
| `v0_v14_control` | 32 | 0.480 | -1.000 | `True` | `True` | 13 (9) | 0.480 | 0.966 | `justified` | 0.430 | 0.535 | 12 | 48 | 116 |
| `v0_v14_control` | 33 | 0.420 | 0.530 | `True` | `True` | 20 (10) | 0.420 | 0.467 | `lucky` | -0.337 | 0.509 | 13 | 17 | 102 |
| `v1_anchoring_authority_confirmation` | 30 | 0.650 | -1.000 | `True` | `True` | 9 (18) | 0.650 | 0.966 | `justified` | 0.594 | 0.175 | 5 | 47 | 94 |
| `v3_grudge_falsemem_misforward` | 30 | 0.650 | -1.000 | `True` | `True` | 8 (18) | 0.650 | 1.000 | `justified` | 0.650 | 0.175 | 10 | 31 | 80 |
| `v3_grudge_falsemem_misforward` | 31 | 0.640 | 0.520 | `True` | `True` | 8 (9) | 0.640 | 0.950 | `justified` | 0.558 | 0.520 | 6 | 33 | 81 |
| `v5_full9_cocktail` | 30 | 0.500 | -1.000 | `True` | `True` | 11 (18) | 0.500 | 0.945 | `justified` | 0.417 | 0.175 | 10 | 25 | 82 |
| `v5_full9_cocktail` | 31 | 0.640 | 0.520 | `True` | `True` | 8 (9) | 0.640 | 0.961 | `justified` | 0.576 | 0.520 | 6 | 19 | 62 |
| `v5_full9_cocktail` | 32 | 0.710 | -1.000 | `True` | `True` | 10 (9) | 0.710 | 0.796 | `justified` | 0.361 | 0.535 | 4 | 55 | 103 |

### 4.2 Paired Checkpoint Intersection vs `v0_v14_control`

| Variant | n Paired | Paired Seeds | Control Raw | Variant Raw | Delta Raw (Var - Ctl) | Control Luck-Adj | Variant Luck-Adj | Delta Luck-Adj (Var - Ctl) |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| `v1_anchoring_authority_confirmation` | 1 | `30` | 0.540 | 0.650 | +0.110 | 0.517 | 0.594 | +0.077 |
| `v3_grudge_falsemem_misforward` | 2 | `30,31` | 0.545 | 0.645 | +0.100 | 0.524 | 0.604 | +0.080 |
| `v5_full9_cocktail` | 3 | `30,31,32` | 0.523 | 0.617 | +0.093 | 0.493 | 0.452 | -0.041 |

## 5. Reproducibility Command

```bash
CANARY_OFFLINE=1 python scripts/run_v16_social_audit.py --workers 1 \
  --tier hard --seeds 30-35 \
  --out-json results/v16_social/social_audit_report.json \
  --out-md docs/reports/v16_social_fairness_audit.md
```

When `/tmp/fleet-momin/shared/v16_runs` is absent (for example on fresh CI clones), `scripts/run_v16_social_audit.py` automatically falls back to committed `results/v16_social/partial`.
