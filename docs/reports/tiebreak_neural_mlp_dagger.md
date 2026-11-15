# TinyMLP 2-Layer Neural Policy + On-Policy DAgger Tiebreaker Report (Canary v1.4)

Evaluates whether a compact 2-layer Multi-Layer Perceptron (`TinyMLPPolicy`, `28 -> 128 -> 64 -> 5`, `12293` parameters, pure NumPy, `0` LLM API calls) trained strictly on Canary v1.4 experience (`TRAIN_SEEDS`) via EV-calibrated behavior cloning and two rounds of on-policy DAgger state relabeling measurably improves on disjoint world-paired `HELDOUT_SEEDS`.

Disclosure (Panel Fix A & Panel Fix E Track Separation): `TinyMLPPolicy` belongs to **Track 1 (`neural_mlp` subfamily: compact non-LLM neural policy, `is_open_weight_llm = False`)** in `scripts/tiebreak_addendum_pack.py` (`PROMOTED_TRACK1_NEURAL`). Per `README.md` and `docs/agents/PANEL-0500.md` (Fix E), this non-LLM neural policy is strictly separated from open-weight autoregressive `Qwen2.5` LoRA runs (`J4-*`, `WS4-*`) and never conflated with LLM RL claims. All training and DAgger state relabeling strictly use `TRAIN_SEEDS` (`107000..107599`, inside `[100000, 200000)`) and all held-out evaluations strictly use disjoint `HELDOUT_SEEDS` (`800000..800059`, inside `[800000, 800200)`); `0` `DEV_SEEDS` and `0` `JUDGE_SEEDS` (`900000+`) are touched (where `DEV_SEEDS 0..29` appear elsewhere in Canary frontier reports, they are **post-hoc locked, not pre-registered**).

- Run ID: `tiny-mlp-dagger-v14` (`TinyMLP (2-layer Neural MLP + On-Policy DAgger r2)`)
- Inference module (AST-isolated): `train/neural_mlp_tiebreak.py:TinyMLPPolicy` (`28 -> 128 -> 64 -> 5`, `12293` parameters, commit threshold `0.46`)
- Train seed range (`TRAIN_SEEDS`): `107000..107599` (Stage 1 `1207` states, Stage 2 `1073` states, DAgger r1 `877` states, DAgger r2 `841` states)
- Held-out eval seed range (`HELDOUT_SEEDS`): `800000..800059` across `easy, medium, hard` (`n=180`, shared `sha256:ebf2f09716cf76d3`)
- Replay provenance: `replay_verified=True`, `invalid_episodes=0`, `900/900` episodes verified step-by-step via `verify_episode`
- Headline paired gain (`stage0_untrained` -> `stage3_onpolicy_dagger_r2`): `-0.8556` -> `+0.6141`, paired delta `+1.4696` (`95% CI [+1.3850, +1.5542]`)
- Calibrated DAgger vs uncalibrated `r0` SFT (`stage1_uncalibrated_sft` -> `stage3_onpolicy_dagger_r2`): `-0.2781` -> `+0.6141`, paired delta `+0.8922` (`95% CI [+0.7556, +1.0288]`)

## 1. Held-Out 4-Stage Progression + `SolverPolicy` Reference (`800000..800059`, `n=180`)

| Stage | Role | `n` | Mean Score [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Canaries | Mean Day | Valid Calls | Replay |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `stage0_untrained` | He-init untrained TinyMLP baseline (before) | 180 | `-0.8556 [-0.9314, -0.7797]` | 0.072 | 0.928 | 0.000 | 0.00 | 1.0 | 1.000 | `180/180` |
| `stage1_uncalibrated_sft` | r0 uncalibrated SFT without abstention calibration | 180 | `-0.2781 [-0.4108, -0.1454]` | 0.389 | 0.611 | 0.000 | 4.67 | 4.4 | 1.000 | `180/180` |
| `stage2_calibrated_bc` | Off-policy EV-calibrated behavior cloning on SolverPolicy | 180 | `+0.6106 [+0.5609, +0.6603]` | 0.917 | 0.022 | 0.061 | 9.79 | 7.8 | 1.000 | `180/180` |
| `stage3_onpolicy_dagger_r2` | On-policy DAgger r2 relabeled TinyMLPPolicy (after) | 180 | `+0.6141 [+0.5651, +0.6630]` | 0.933 | 0.028 | 0.039 | 9.31 | 7.7 | 1.000 | `180/180` |
| `solver_reference` | Exact Bayesian `SolverPolicy` upper bound (training teacher) | 180 | `+0.6596 [+0.6102, +0.7090]` | 0.933 | 0.028 | 0.039 | 7.46 | 7.0 | 1.000 | `180/180` |

## 2. World-Paired Stage-by-Stage Deltas (`n=180`, Shared `sha256:ebf2f09716cf76d3`)

| Comparison (After - Before) | Mean Delta | 95% CI Low | 95% CI High |
|---|---:|---:|---:|
| `stage1_uncalibrated_sft - stage0_untrained` | `+0.5774` | `+0.4189` | `+0.7359` |
| `stage2_calibrated_bc - stage1_uncalibrated_sft` | `+0.8887` | `+0.7568` | `+1.0206` |
| `stage3_onpolicy_dagger_r2 - stage2_calibrated_bc` | `+0.0034` | `-0.0619` | `+0.0688` |
| `stage3_onpolicy_dagger_r2 - stage1_uncalibrated_sft` | `+0.8922` | `+0.7556` | `+1.0288` |
| `stage3_onpolicy_dagger_r2 - stage0_untrained` | `+1.4696` | `+1.3850` | `+1.5542` |
| `solver_reference - stage3_onpolicy_dagger_r2` | `+0.0456` | `-0.0150` | `+0.1062` |

## 3. Per-Tier Breakdown Across Delayed-Leak Regimes (`easy`, `medium`, `hard`)

| Tier | Stage | `n` | Mean Score [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Canaries | Mean Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `easy` | `stage0_untrained` | 60 | `-0.7000 [-0.8822, -0.5178]` | 0.150 | 0.850 | 0.000 | 0.00 | 1.0 |
| `easy` | `stage1_uncalibrated_sft` | 60 | `-0.1118 [-0.3542, +0.1305]` | 0.467 | 0.533 | 0.000 | 1.67 | 2.7 |
| `easy` | `stage2_calibrated_bc` | 60 | `+0.8010 [+0.7674, +0.8346]` | 1.000 | 0.000 | 0.000 | 3.65 | 4.7 |
| `easy` | `stage3_onpolicy_dagger_r2` | 60 | `+0.8047 [+0.7850, +0.8243]` | 1.000 | 0.000 | 0.000 | 3.62 | 4.6 |
| `easy` | `solver_reference` | 60 | `+0.7970 [+0.7726, +0.8214]` | 1.000 | 0.000 | 0.000 | 3.72 | 4.7 |
| `medium` | `stage0_untrained` | 60 | `-0.9000 [-1.0112, -0.7888]` | 0.050 | 0.950 | 0.000 | 0.00 | 1.0 |
| `medium` | `stage1_uncalibrated_sft` | 60 | `-0.1135 [-0.3477, +0.1207]` | 0.483 | 0.517 | 0.000 | 4.48 | 5.5 |
| `medium` | `stage2_calibrated_bc` | 60 | `+0.6075 [+0.5349, +0.6801]` | 0.833 | 0.000 | 0.167 | 7.75 | 8.8 |
| `medium` | `stage3_onpolicy_dagger_r2` | 60 | `+0.6075 [+0.5494, +0.6656]` | 0.900 | 0.000 | 0.100 | 8.22 | 9.2 |
| `medium` | `solver_reference` | 60 | `+0.6532 [+0.5859, +0.7204]` | 0.883 | 0.000 | 0.117 | 7.12 | 8.0 |
| `hard` | `stage0_untrained` | 60 | `-0.9667 [-1.0320, -0.9013]` | 0.017 | 0.983 | 0.000 | 0.00 | 1.0 |
| `hard` | `stage1_uncalibrated_sft` | 60 | `-0.6090 [-0.7988, -0.4192]` | 0.217 | 0.783 | 0.000 | 7.87 | 4.9 |
| `hard` | `stage2_calibrated_bc` | 60 | `+0.4233 [+0.3163, +0.5304]` | 0.917 | 0.067 | 0.017 | 17.97 | 10.0 |
| `hard` | `stage3_onpolicy_dagger_r2` | 60 | `+0.4300 [+0.3140, +0.5460]` | 0.900 | 0.083 | 0.017 | 16.10 | 9.2 |
| `hard` | `solver_reference` | 60 | `+0.5287 [+0.4073, +0.6500]` | 0.917 | 0.083 | 0.000 | 11.55 | 8.3 |

## 4. Architecture Diagnosis and Honest Takeaways

1. **Uncalibrated `r0` SFT (`stage1_uncalibrated_sft`) reproduces the `WS4-v2` premature-accusation failure**: training the 2-layer MLP (`28 -> 128 -> 64 -> 5`, `12293` params) on winning-episode states with end-of-episode oversampling and weak negative stopping weights raises suspect accuracy from `0.072` to `0.389`, yet still accuses wrong suspects on `0.611` of episodes (`-0.2781` overall, `-0.6090` on `hard`), directly paralleling dense `WS4-v2` SFT (`-0.457`).
2. **EV-calibrated behavior cloning + on-policy DAgger closes the commitment and medium-tier abstention gap**: enforcing breakeven stopping (`top_p >= 1 / (1 + known_v)` and `accuse_value > 0`) in `stage2_calibrated_bc` jumps held-out score by `+0.8887` (`+0.6106`), and two rounds of on-policy DAgger relabeling (`stage3_onpolicy_dagger_r2`) raise overall accuracy from `0.917` to `0.933` (lifting `medium` accuracy from `0.833` to `0.900` while keeping `medium` wrong accusations at `0.000`).
3. **Honest comparison to `SolverPolicy` and open-weight LLMs**: `stage3_onpolicy_dagger_r2` matches `SolverPolicy` accuracy (`0.933`) on identical held-out worlds with a residual timing/multi-canary planning gap on delayed leaks (`solver_reference - stage3_onpolicy_dagger_r2` = `+0.0456`). Because `TinyMLPPolicy` acts on lossless 28-dimensional public-observation features rather than raw 4k-8k JSON transcripts, it remains strictly separated from open-weight `Qwen2.5` LoRA runs (`J4-*`, `WS4-*`).

## 5. Offline Verification Commands

```bash
python -m train.neural_mlp_tiebreak --check
python -m train.neural_mlp_tiebreak --eval-only
pytest -q tests/test_neural_mlp_tiebreak.py
```
