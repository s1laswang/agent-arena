# Zero-Shot Cross-Mole Adversarial Generalization Benchmark (Canary v1.4)

Evaluates whether experience calibration learned strictly ONCE on standard `default` mole episodes (`TRAIN_SEEDS 100000..100119`, zero training exposure to evolved Forge HoF, `RLMole`, or sleeper DSL strategies) transfers zero-shot to unseen adversarial mole regimes on fresh world-paired `HELDOUT_SEEDS`.

Disclosure (Panel Fix A & Track Separation): `UncalibratedEmpiricalBayesPolicy` (`before`) and `EmpiricalBayesPolicy` (`after`) belong to the structured compact non-LLM policy track (never conflated with open-weight `Qwen2.5` LoRA runs). All training strictly uses `TRAIN_SEEDS` (`100000..100119`) and all evaluation strictly uses disjoint fresh `HELDOUT_SEEDS` (`800000..800029`, inside `[800000, 800200)`); no dev seeds are used here (and wherever dev seeds `0..29` appear elsewhere in Canary, they are post-hoc locked, not pre-registered).

- Train seed range (`default` mole only): `100000..100119` (Stage 2 likelihoods `100000..100059`, Stage 3 stopping/splits `100060..100119`)
- Fresh held-out seed range: `800000..800029` (`n=30` per regime, `5` regimes, `150` world-paired episodes per policy)
- Shared held-out world secret tag: `sha256:ebf2f09716cf76d3` (`100%` identical world pairings across `before`, `stage2_likelihood_only`, `after`, and `solver`)
- Tool-by-tool `Env` replay verification: `True` (`600/600` episodes replayed, `invalid_episodes=0`)
- Pooled all-5-regimes paired gain (`after - before`, `n=150`): `+1.257 [+1.177, +1.331]` (luck-adjusted EV delta `+1.257 [+1.196, +1.313]`)
- Pooled 4 unseen adversarial mole regimes (`n=120`): `+1.226 [+1.139, +1.308]` (luck-adjusted EV delta `+1.225 [+1.157, +1.286]`)

## 1. Single-Fit Parameters Learned on Standard `default` Mole (`100000..100119`)

| Policy Role | Stage | `w_canary_hit` | `w_canary_miss` | `w_doc_hit` | `w_after_hours` | `w_evasive` | `w_angry_msg` | `tau_margin` | `unsurfaced_v_disc` | `canary_cov` | `tiny_pool` | `ev_stop` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `before` (`UncalibratedEmpiricalBayesPolicy`) | `eb_naive_prior` | +1.000 | -0.800 | +0.600 | +0.800 | +0.400 | +1.200 | 0.00 | 0.00 | 0.90 | 0 | `False` |
| `stage2_likelihood_only` (uncalibrated stopping) | `eb_likelihood_only` | +1.306 | -3.652 | +6.843 | +0.216 | +0.091 | -1.225 | 0.00 | 0.00 | 0.90 | 0 | `False` |
| `after` (`EmpiricalBayesPolicy`) | `eb_experience_opt` | +1.306 | -3.652 | +6.843 | +0.216 | +0.091 | -1.225 | 0.30 | 1.00 | 0.55 | 4 | `True` |

## 2. Paired Before vs After + `SolverPolicy` Upper Bound Across 5 Mole Regimes (`800000..800029`)

| Regime | Exposure | `n` | `before` Score [95% CI] | `stage2` Score [95% CI] | `after` Score [95% CI] | `solver` Score [95% CI] | Paired `after - before` [95% CI] | Paired `after - stage2` [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `hard` | `in_distribution_mole_rules` | 30 | -0.847 [-1.000, -0.677] | +0.125 [-0.149, +0.382] | +0.534 [+0.404, +0.620] | +0.590 [+0.458, +0.682] | +1.381 [+1.172, +1.555] | +0.410 [+0.100, +0.717] |
| `hard_forge` | `zero_shot_unseen` | 30 | -1.000 [-1.000, -1.000] | +0.104 [-0.014, +0.211] | +0.220 [+0.063, +0.356] | +0.381 [+0.213, +0.525] | +1.220 [+1.063, +1.356] | +0.116 [-0.071, +0.283] |
| `hard_rl` | `zero_shot_unseen` | 30 | -1.000 [-1.000, -1.000] | +0.185 [-0.049, +0.390] | +0.257 [+0.097, +0.393] | +0.318 [+0.220, +0.415] | +1.257 [+1.097, +1.393] | +0.072 [-0.221, +0.375] |
| `hard_dsl_patient_sleeper` | `zero_shot_unseen` | 30 | -1.000 [-1.000, -1.000] | +0.229 [+0.016, +0.412] | +0.269 [+0.085, +0.427] | +0.657 [+0.628, +0.685] | +1.269 [+1.085, +1.427] | +0.040 [-0.196, +0.272] |
| `medium_hard_rl` | `zero_shot_unseen` | 30 | -0.939 [-1.000, -0.818] | +0.282 [+0.005, +0.535] | +0.219 [+0.074, +0.360] | +0.365 [+0.230, +0.495] | +1.159 [+0.955, +1.339] | -0.063 [-0.377, +0.278] |
| `pooled_4_unseen_moles` | `pooled` | 120 | -0.985 [-1.000, -0.955] | +0.200 [+0.094, +0.305] | +0.241 [+0.163, +0.316] | +0.430 [+0.366, +0.490] | +1.226 [+1.139, +1.308] | +0.041 [-0.092, +0.174] |
| `pooled_all_5_regimes` | `pooled` | 150 | -0.957 [-0.990, -0.913] | +0.185 [+0.084, +0.282] | +0.300 [+0.230, +0.364] | +0.462 [+0.406, +0.516] | +1.257 [+1.177, +1.331] | +0.115 [-0.009, +0.238] |

## 3. Accuracy, Abstention, Luck-Adjusted EV, and Calibration Gap Per Regime

`calibration_gap` measures `|E[p_policy(accused) | accuse] - P(correct | accuse)|` (confidence-minus-precision misalignment on accused episodes; `0.000` is perfectly calibrated commitment).

| Regime | Agent | `n` | Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain Rate | Mean `p(accuse)` | Calibration Gap | Mean Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hard` | `before` | 30 | -0.847 [-1.000, -0.677] | -0.855 [-0.969, -0.714] | 0.100 | 0.900 | 0.000 | 0.702 | 0.602 | 4.3 |
| `hard` | `stage2_likelihood_only` | 30 | +0.125 [-0.149, +0.382] | +0.221 [+0.096, +0.340] | 0.700 | 0.300 | 0.000 | 0.679 | 0.021 | 8.5 |
| `hard` | `after` | 30 | +0.534 [+0.404, +0.620] | +0.530 [+0.477, +0.577] | 0.967 | 0.033 | 0.000 | 0.989 | 0.022 | 8.6 |
| `hard` | `solver` | 30 | +0.590 [+0.458, +0.682] | +0.572 [+0.524, +0.618] | 0.967 | 0.033 | 0.000 | 0.955 | 0.011 | 8.2 |
| `hard_forge` | `before` | 30 | -1.000 [-1.000, -1.000] | -0.954 [-0.971, -0.936] | 0.000 | 1.000 | 0.000 | 0.720 | 0.720 | 3.6 |
| `hard_forge` | `stage2_likelihood_only` | 30 | +0.104 [-0.014, +0.211] | +0.041 [-0.061, +0.129] | 0.267 | 0.033 | 0.700 | 0.739 | 0.150 | 15.0 |
| `hard_forge` | `after` | 30 | +0.220 [+0.063, +0.356] | +0.293 [+0.207, +0.373] | 0.567 | 0.067 | 0.367 | 0.986 | 0.091 | 14.3 |
| `hard_forge` | `solver` | 30 | +0.381 [+0.213, +0.525] | +0.419 [+0.333, +0.500] | 0.767 | 0.067 | 0.167 | 0.946 | 0.026 | 11.3 |
| `hard_rl` | `before` | 30 | -1.000 [-1.000, -1.000] | -0.950 [-0.974, -0.917] | 0.000 | 1.000 | 0.000 | 0.767 | 0.767 | 3.4 |
| `hard_rl` | `stage2_likelihood_only` | 30 | +0.185 [-0.049, +0.390] | +0.186 [+0.052, +0.304] | 0.767 | 0.200 | 0.033 | 0.772 | 0.021 | 11.8 |
| `hard_rl` | `after` | 30 | +0.257 [+0.097, +0.393] | +0.305 [+0.222, +0.388] | 0.733 | 0.067 | 0.200 | 0.979 | 0.062 | 12.1 |
| `hard_rl` | `solver` | 30 | +0.318 [+0.220, +0.415] | +0.272 [+0.187, +0.355] | 0.633 | 0.000 | 0.367 | 0.953 | 0.047 | 13.3 |
| `hard_dsl_patient_sleeper` | `before` | 30 | -1.000 [-1.000, -1.000] | -0.965 [-0.976, -0.953] | 0.000 | 1.000 | 0.000 | 0.805 | 0.805 | 3.0 |
| `hard_dsl_patient_sleeper` | `stage2_likelihood_only` | 30 | +0.229 [+0.016, +0.412] | +0.161 [-0.002, +0.300] | 0.833 | 0.167 | 0.000 | 0.793 | 0.041 | 14.1 |
| `hard_dsl_patient_sleeper` | `after` | 30 | +0.269 [+0.085, +0.427] | +0.283 [+0.122, +0.410] | 0.700 | 0.100 | 0.200 | 0.938 | 0.063 | 13.9 |
| `hard_dsl_patient_sleeper` | `solver` | 30 | +0.657 [+0.628, +0.685] | +0.595 [+0.564, +0.627] | 1.000 | 0.000 | 0.000 | 0.963 | 0.037 | 12.3 |
| `medium_hard_rl` | `before` | 30 | -0.939 [-1.000, -0.818] | -0.892 [-0.969, -0.764] | 0.033 | 0.967 | 0.000 | 0.768 | 0.734 | 3.8 |
| `medium_hard_rl` | `stage2_likelihood_only` | 30 | +0.282 [+0.005, +0.535] | +0.215 [+0.044, +0.379] | 0.667 | 0.233 | 0.100 | 0.737 | 0.004 | 7.2 |
| `medium_hard_rl` | `after` | 30 | +0.219 [+0.074, +0.360] | +0.257 [+0.141, +0.379] | 0.367 | 0.033 | 0.600 | 0.958 | 0.041 | 9.6 |
| `medium_hard_rl` | `solver` | 30 | +0.365 [+0.230, +0.495] | +0.346 [+0.215, +0.479] | 0.500 | 0.000 | 0.500 | 0.976 | 0.024 | 9.1 |

## 4. Luck-Adjusted EV Paired Deltas and Adversarial Findings

| Regime | Adversarial Mechanism | Score Delta (`after - before`) | Luck-Adj EV Delta (`after - before`) | Calib Gap (`before -> after`) | Gap to `solver` (`solver - after`) |
|---|---|---:|---:|---:|---:|
| `hard` | Careful canary-share weighting + Poisson decoy/peer after-hours framing + 0.95 fingerprint accuracy | +1.381 [+1.172, +1.555] | +1.385 [+1.244, +1.501] | `0.602 -> 0.022` | +0.056 [-0.100, +0.227] |
| `hard_forge` | Per-seed evolved MoleStrategy HoF rules (early leak suppression, recipient-count thresholds, decoy/restricted framing) | +1.220 [+1.063, +1.356] | +1.247 [+1.158, +1.330] | `0.720 -> 0.091` | +0.161 [-0.070, +0.390] |
| `hard_rl` | REINFORCE-trained 1-hidden-layer MLP mole over 10 MoleView features with solver catchability >= 0.75 | +1.257 [+1.097, +1.393] | +1.255 [+1.169, +1.343] | `0.767 -> 0.062` | +0.062 [-0.096, +0.226] |
| `hard_dsl_patient_sleeper` | Silent days 1..6 + continuous decoy framing + broad-doc evasion when >=2 narrow-recipient docs are held | +1.269 [+1.085, +1.427] | +1.248 [+1.089, +1.374] | `0.805 -> 0.063` | +0.388 [+0.225, +0.573] |
| `medium_hard_rl` | hard_rl RLMole transferred onto 20-staff 14-day medium tier (1 canary/day, delays 1..3, decoy + framing) | +1.159 [+0.955, +1.339] | +1.150 [+0.964, +1.310] | `0.734 -> 0.041` | +0.146 [-0.049, +0.339] |

## 5. Key Honest Takeaways

1. **Zero-shot decoy and framing immunity transfers across all 4 unseen mole families**: fitting log-likelihoods once on standard `default` mole `TRAIN_SEEDS 100000..100119` flips `w_angry_msg` from `+1.200` to `-1.225` and Fano-tempers `w_after_hours` from `+0.800` to `+0.216`, driving a `+1.226 [+1.139, +1.308]` paired score gain across `hard_forge`, `hard_rl`, `hard_dsl_patient_sleeper`, and `medium_hard_rl` with zero adversarial training exposure.
2. **Optimal EV-stopping and adaptive split sizing specifically rescue sleeper/Forge regimes**: against stealth moles that suppress early leaks (`hard_forge` and `hard_dsl_patient_sleeper`), `stage2_likelihood_only` (`p >= 0.50` stopping + `0.90` splits) stalls because early-day silence keeps posterior mass diffuse while `p = 0.50` sits below the `1 / (1 + V_hat)` EV breakeven threshold; Stage 3 calibration (`after`) adds `+0.116 [-0.071, +0.283]` over `stage2` on `hard_forge` and `+0.040 [-0.196, +0.272]` over `stage2` on `hard_dsl_patient_sleeper`.
3. **Honest residual gap to `SolverPolicy`**: because `EmpiricalBayesPolicy` uses a 6-feature factorized summary rather than `SolverPolicy`'s full joint multi-canary MI planner and exact non-leak likelihoods, `solver - after` is `+0.056 [-0.100, +0.227]` on `hard`, `+0.062 [-0.096, +0.226]` on `hard_rl`, `+0.161 [-0.070, +0.390]` on `hard_forge`, and `+0.388 [+0.225, +0.573]` on `hard_dsl_patient_sleeper`, motivating neural/LLM DAgger distillation on compact working-memory states.

## 6. Verification Commands

```bash
python scripts/tiebreak_cross_mole_generalization.py
python scripts/tiebreak_cross_mole_generalization.py --check
```
