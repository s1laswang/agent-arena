# Panel Fix E Tiebreak Addendum Pack

Deterministic readiness audit for `README.md` (`Tiebreak: a small model trained on Canary experience`) and `docs/agents/PANEL-0500.md` (`Fix E. Tiebreak`: added as an addendum only if held-out mean > 0 with a 95% CI excluding 0 under one shared `CANARY_WORLD_SECRET` on `HELDOUT_SEEDS`). Note on `README.md` frontier seeds: dev seeds `0..29` are `post-hoc locked` (not pre-registered); all tiebreak evaluations below strictly use disjoint `TRAIN_SEEDS [100000, 200000)` and `HELDOUT_SEEDS [800000, 800200)`.

- Track 1 Open-Weight LLM DAgger Status: `AWAITING_V100_COMPLETION`
- README Addendum Action: `DO_NOT_APPEND_YET`
- Track 1 Passing Runs (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` / `TinyMLP`): `0 / 0`
- Track 2 Non-LLM Parametric Controls Passing 5/5 Criteria: `2 / 2`

## 1. Ready-to-Paste `README.md` Tiebreak Addendum (Track 1: Open-Weight LLM / Neural Policies)

| Model / Run | Architecture | Held-Out Score +/- 95% CI | Paired Delta [95% CI] | n | World Secret | Panel Fix E Status |
|---|---|---|---|---:|---|---|
| base (untrained) | Open-weight LLM (Qwen2.5-1.5B) | 0.000 (cannot play: 3% valid tool calls; per-process world secret) | two-sample / n/a | 36 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v2 (SFT on solver play) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.457 +/- 0.086 | two-sample / n/a | 172 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-4k (GRPO on environment reward, Verda H100) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.147 +/- 0.063 | two-sample / n/a | 180 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| v3-8k seed 2 (GRPO, 8k context, Verda H100 spot) | Open-weight LLM (Qwen2.5-1.5B LoRA) | -0.050 +/- 0.049 | two-sample / n/a | 90 | per-process (unpaired) | `PUBLISHED_BASELINE` |
| DAgger round 1 (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` LoRA, V100) | Open-weight LLM (LoRA) | pending V100 completion | pending paired eval | >=30 | shared `CANARY_WORLD_SECRET` | `AWAITING_V100_COMPLETION` |

## 2. Four-Bullet Addendum Summary

- **Track 1 LLM DAgger Status (`AWAITING_V100_COMPLETION`)**: `0` Track 1 `results/tiebreak/*/summary.json` runs have passed all 5 gates yet while V100 DAgger jobs run; per `PANEL-0500.md` Fix E, `README.md` keeps its honest negative Qwen2.5 table unchanged until a paired V100 run clears `0.0` with 95% CI > `0.0`.
- **Published Raw-Context Qwen2.5-1.5B Progression**: reward training fixed `v2`'s blind accusations (`v3-4k` `-0.147 +/- 0.063`, `n=180` vs `v2` `-0.457 +/- 0.086`, `n=172`; `+0.310 +/- 0.107` two-sample, `100%` valid tool calls) and `v3-8k seed 2` reached `-0.050 +/- 0.049` (`n=90`), but `2,842`-token prompt headers and off-policy states prevented positive held-out score without on-policy DAgger / compact working memory.
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
| `empirical-bayes-v14` | `track_2` | `EmpiricalBayesPolicy` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | 5/5 | `PASS_NON_LLM_CONTROL` |
| `scaling-logistic-v14` | `track_2` | `ScalingLogisticPolicy` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | 5/5 | `PASS_NON_LLM_CONTROL` |

## 5. Offline Verification Commands

```bash
python scripts/tiebreak_addendum_pack.py
python scripts/tiebreak_addendum_pack.py --check
```
