# Panel Fix E Tiebreak Addendum Pack

Deterministic readiness audit for `README.md` (`Tiebreak: a small model trained on Canary experience`) and `docs/agents/PANEL-0500.md` (`Fix E. Tiebreak`: added as an addendum only if held-out mean > 0 with a 95% CI excluding 0 under one shared `CANARY_WORLD_SECRET` on `HELDOUT_SEEDS`). Note on `README.md` frontier seeds: dev seeds `0..29` are `post-hoc locked` (not pre-registered); all tiebreak evaluations below strictly use disjoint `TRAIN_SEEDS [100000, 200000)` and `HELDOUT_SEEDS [800000, 800200)`.

- Track 1 Open-Weight LLM DAgger Status: `AWAITING_V100_COMPLETION`
- README Addendum Action: `HOLD_README_QWEN_ADDENDUM_UNTIL_V100`
- Track 1 Passing Runs (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` / `TinyMLP`): `1 / 1`
- Track 2 Non-LLM Parametric Controls Passing 5/5 Criteria: `2 / 2`

## 1. Ready-to-Paste `README.md` Tiebreak Addendum (Track 1: Open-Weight LLM / Neural Policies)

| Model / Run | Architecture | Held-Out Score +/- 95% CI | Paired Delta [95% CI] | n | World Secret | Panel Fix E Status |
|---|---|---|---|---:|---|---|
| base (untrained) | Open-weight LLM (Qwen2.5-1.5B) | 0.000 (cannot play: 3% valid tool calls; per-process world secret) | two-sample / n/a | 36 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v1 (J4 SFT on solver episodes, FR8 V100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.250 +/- 0.256 | two-sample (+0.207 +/- 0.270 vs v2) | 12 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v2 (SFT on solver play, FR8 V100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.457 +/- 0.086 | two-sample (-0.457 +/- 0.086 vs base) | 172 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-4k s0 (GRPO, 609 steps, Verda H100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.147 +/- 0.063 | two-sample (+0.310 +/- 0.107 vs v2) | 180 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-4k s1 (GRPO, FR8 V100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.209 +/- 0.094 | two-sample (+0.249 +/- 0.127 vs v2) | 82 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-8k s0 (GRPO, 8k ctx, 637 steps, Verda H100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.060 +/- 0.054 | +0.728 +/- 0.134 (paired vs v3-8k s3) | 90 | shared (1ca0c2a64d) | `PUBLISHED_BASELINE` |
| v3-8k s1 (GRPO, 8k ctx, 371 steps, Verda A100 spot) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.777 +/- 0.118 | two-sample (-0.319 +/- 0.146 vs v2) | 90 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-8k s2 (GRPO, 8k ctx, 693 steps, Verda H100 spot) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.050 +/- 0.049 | two-sample (+0.408 +/- 0.099 vs v2) | 90 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-8k s3 (GRPO, 8k ctx, 344 steps, Verda A100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.788 +/- 0.117 | -0.073 +/- 0.173 (paired vs v3-4k s0 @8k) | 90 | shared (1ca0c2a64d) | `PUBLISHED_BASELINE` |
| DAgger r1 @8k (Verda X2, cap 256, partial n=50, honest null) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.542 +/- 0.214 | +0.242 +/- 0.304 (paired n=43 vs v3-4k s0 @8k) | 50 | shared (1ca0c2a64d) | `PUBLISHED_HONEST_NULL` |
| DAgger r1 @4k (Verda X2, cap 256, partial n=41, honest null) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.101 +/- 0.112 | -0.031 +/- 0.139 (paired n=32 vs v3-4k s0 @4k) | 41 | shared (1ca0c2a64d) | `PUBLISHED_HONEST_NULL` |
| `tiny-mlp-dagger-v14` (TinyMLP (2-layer Neural MLP + On-Policy DAgger r2)) | Compact neural MLP (TinyMLPPolicy, non-LLM) | `+0.614 +/- 0.049 [+0.565, +0.663]` | `+1.470 [+1.385, +1.554]` | 180 | `paired (sha256:ebf2f097)` | `PROMOTED_TRACK1_NEURAL` (5/5) |
| DAgger round 1 (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` LoRA, V100) | Open-weight LLM (LoRA) | pending V100 completion | pending paired eval | >=30 | shared `CANARY_WORLD_SECRET` | `AWAITING_V100_COMPLETION` |

## 2. Four-Bullet Addendum Summary

- **Open-Weight LLM DAgger Status (`AWAITING_V100_COMPLETION`)**: no `Qwen2.5` V100 LoRA run has completed all 5 gates yet (so the `README.md` Qwen addendum stays withheld per `PANEL-0500.md`), while Track 1 compact neural policy `tiny-mlp-dagger-v14` (Compact neural MLP (TinyMLPPolicy, non-LLM)) passes 5/5 gates at `+0.614 +/- 0.049 [+0.565, +0.663]` (paired delta `+1.470 [+1.385, +1.554]`, `n=180`).
- **Published Raw-Context Qwen2.5-1.5B Progression (`README.md`, `justSilas-fr8`, Verda X2)**: reward training beat `v2` (`-0.457 +/- 0.086`, `n=172`) across `v3-4k s0` (`-0.147 +/- 0.063`, `n=180`), `v3-4k s1` (`-0.209 +/- 0.094`, `n=82`), and 600+ step 8k GRPO (`v3-8k s0` `-0.060 +/- 0.054` with paired `+0.728 +/- 0.134` vs `s3` `-0.788 +/- 0.117` under shared secret `1ca0c2a64d`; `v3-8k s2` `-0.050 +/- 0.049`, `v3-8k s1` `-0.777 +/- 0.118`), while Verda X2 `DAgger r1` ended as an honest null (`-0.542 +/- 0.214` at 8k `n=50` partial, paired `+0.242 +/- 0.304` `n=43` vs `v3-4k s0 @8k`; `-0.101 +/- 0.112` at 4k `n=41` partial, paired `-0.031 +/- 0.139` `n=32`), with none above `base` (`0.000`, `n=36`).
- **5-Criterion Panel Fix E Gate**: every candidate run is machine-checked for (1) `heldout_mean_gt_zero` (`after.mean_score > 0` and `after_ci95_low > 0`), (2) `paired_delta_ci95_gt_zero` under one shared `world_secret_tag` on `HELDOUT_SEEDS [800000, 800200)`, (3) `train_eval_disjoint` strictly inside `TRAIN_SEEDS [100000, 200000)`, (4) `replay_and_zero_errors` (`n >= 30`, `replay_verified = True`, `invalid_episodes = 0`), and (5) AST-verified `autonomous_inference` (`0` `canary.solver` / `canary.world` imports).
- **Track 2 Non-LLM Parametric Controls (Strictly Separated from Qwen LoRA)**: `empirical-bayes-v14` (`EmpiricalBayesPolicy`, held-out `+0.607 +/- 0.044 [+0.559, +0.648]`, paired delta `+1.028 [+0.915, +1.141]`, `n=180`); `scaling-logistic-v14` (`ScalingLogisticPolicy`, held-out `+0.611 +/- 0.069 [+0.542, +0.679]`, paired delta `+0.611 [+0.542, +0.679]`, `n=90`) pass all 5 mathematical and AST-isolation criteria on CPU, establishing a clean non-LLM empirical-Bayes / parametric upper-bound control that is never conflated with open-weight Qwen2.5 LoRA.

## 3. Track 2 Non-LLM Parametric and Empirical-Bayes Controls (Not Conflated With Qwen2.5 LoRA)

| Run ID | Policy Family (Non-LLM) | Held-Out Score +/- 95% CI | Paired Delta [95% CI] | n | Shared Secret | AST Audited Module(s) | Verdict |
|---|---|---|---|---:|---|---|---|
| `empirical-bayes-v14` | `EmpiricalBayesPolicy` (non-LLM control) | `+0.607 +/- 0.044 [+0.559, +0.648]` | `+1.028 [+0.915, +1.141]` | 180 | `paired (sha256:ebf2f097)` | `train/empirical_bayes_policy.py` | `PASS_NON_LLM_CONTROL` |
| `scaling-logistic-v14` | `ScalingLogisticPolicy` (non-LLM control) | `+0.611 +/- 0.069 [+0.542, +0.679]` | `+0.611 [+0.542, +0.679]` | 90 | `paired (sha256:ebf2f097)` | `scripts/tiebreak_scaling_calibration.py` | `PASS_NON_LLM_CONTROL` |

## 4. Complete 5-Criterion Panel Fix E Audit Matrix

| Run ID | Track | Family | C1 `heldout>0` | C2 `paired_ci>0` | C3 `disjoint_seeds` | C4 `replay_n>=30` | C5 `ast_isolated` | Passed | Verdict |
|---|---|---|---|---|---|---|---|---:|---|
| `tiny-mlp-dagger-v14` | `track_1` | `TinyMLP` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | 5/5 | `PROMOTED_TRACK1_NEURAL` |
| `empirical-bayes-v14` | `track_2` | `EmpiricalBayesPolicy` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | 5/5 | `PASS_NON_LLM_CONTROL` |
| `scaling-logistic-v14` | `track_2` | `ScalingLogisticPolicy` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | 5/5 | `PASS_NON_LLM_CONTROL` |

## 5. Offline Verification Commands

```bash
python scripts/tiebreak_addendum_pack.py
python scripts/tiebreak_addendum_pack.py --check
```
