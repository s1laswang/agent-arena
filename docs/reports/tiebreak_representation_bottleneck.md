# Tiebreak Representation-Bottleneck & Minimal Sufficient-Statistic Audit (v1.4)

- **Schema / Audit ID**: `canary.tiebreak.representation_bottleneck.v1` / `tiebreak-representation-bottleneck-v14`
- **World-Paired Held-Out Evaluation**: `HELDOUT_SEEDS 800000..800029` (`n = 90` per cell, `30`/tier across `easy`, `medium`, `hard`), `world_secret_tag = sha256:ebf2f09716cf76d3`, `1080/1080` (`100%`) `Env` replay-verified.
- **Strict Seed & Solver Isolation (Panel Fix A)**: All learned parameters originate from `TRAIN_SEEDS [100000, 200000)` (`0` overlap with held-out, `0` judge seeds `>= 900000`). All 1,080 live representation-bottleneck episodes evaluate strictly on world-paired HELDOUT_SEEDS 800000..800029 (30 seeds x 3 tiers = 90 episodes per condition across easy, medium, hard) under shared deterministic world_secret_tag sha256:ebf2f09716cf76d3, all learned compact policy parameters originate strictly from disjoint TRAIN_SEEDS [100000, 200000), and 0 JUDGE_SEEDS (900k+) are touched. Any frontier reference cohorts on DEV_SEEDS 0..29 mentioned in Canary cross-track literature are post-hoc locked, not pre-registered (Panel Fix A).
- **Strict Track Separation (Panel Fix E)**: `0 / 19` open-weight Qwen2.5 runs exceed `0.000` (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`); all 4 compact policies have `is_open_weight_llm = False`.

## 1. Minimal Sufficient-Statistic Compression Across Compact Policies (`n = 90` Paired)

| Policy | Params | Active Emp Feats | Mean Score +/- 95% CI | Delta vs `0.000` | Accuse Precision | Abstain Rate | Action Agree vs `CompactLinear full_28d` |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `EmpiricalBayesPolicy` | `11` | `6 log-likelihood + 5 stopping/split sufficient stats` | `+0.6223 +/- 0.0498` | `+0.6223` (`[+0.5726, +0.6721]`) | `1.0000` (`82/82`) | `0.0889` | `0.1665` |
| `ScalingLogisticPolicy` | `82` | `14 suspect + 10 commit + 6 wait + 12 tool/canary stats` | `+0.6107 +/- 0.0687` | `+0.6107` (`[+0.5420, +0.6794]`) | `0.9765` (`83/85`) | `0.0556` | `0.4551` |
| `CompactLinearDAggerPolicy (full_28d)` | `785` | `28/28` | `+0.6632 +/- 0.0561` | `+0.6632` (`[+0.6071, +0.7194]`) | `0.9886` (`87/88`) | `0.0222` | `1.0000` |
| `CompactLinearDAggerPolicy (core_sufficient_stats)` | `785` | `19/28` | `+0.5613 +/- 0.0663` | `+0.5613` (`[+0.4951, +0.6276]`) | `1.0000` (`72/72`) | `0.2000` | `0.6452` |
| `TinyMLPPolicy (full_28d)` | `12293` | `28/28` | `+0.6292 +/- 0.0643` | `+0.6292` (`[+0.5649, +0.6935]`) | `0.9770` (`85/87`) | `0.0333` | `1.0000` |
| `TinyMLPPolicy (core_sufficient_stats)` | `12293` | `16/28` | `+0.6529 +/- 0.0696` | `+0.6529` (`[+0.5833, +0.7225]`) | `0.9667` (`87/90`) | `0.0000` | `0.7676` |

## 2. Five-Group Feature-Bottleneck Masking Matrix (`n = 90` World-Paired Per Cell)

| Policy (`Params`) | Bottleneck Group | Active Feats | Mean Score (`95% CI`) | Paired Delta vs `full_28d` | Paired Delta vs `0.000` | Precision | Abstain Rate | Step Action Agree | Terminal Agree |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CompactLinearDAggerPolicy` (`785`) | `full_28d` | `28/28` | `+0.6632` (`[+0.6071, +0.7194]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6632` | `0.9886` | `0.0222` | `1.0000` | `1.0000` |
| `CompactLinearDAggerPolicy` (`785`) | `core_sufficient_stats` | `19/28` | `+0.5613` (`[+0.4951, +0.6276]`) | `-0.1019` (`[-0.1704, -0.0334]`) | `+0.5613` | `1.0000` | `0.2000` | `0.6452` | `0.7889` |
| `CompactLinearDAggerPolicy` (`785`) | `posterior_only` | `20/28` | `+0.6019` (`[+0.5220, +0.6817]`) | `-0.0613` (`[-0.1392, +0.0165]`) | `+0.6019` | `0.9551` | `0.0111` | `0.6437` | `0.9222` |
| `CompactLinearDAggerPolicy` (`785`) | `horizon_value_only` | `0/28` | `+0.0000` (`[+0.0000, +0.0000]`) | `-0.6632` (`[-0.7194, -0.6071]`) | `+0.0000` | `0.0000` | `1.0000` | `0.7890` | `0.0222` |
| `CompactLinearDAggerPolicy` (`785`) | `no_canary_aux_only` | `8/28` | `+0.0000` (`[+0.0000, +0.0000]`) | `-0.6632` (`[-0.7194, -0.6071]`) | `+0.0000` | `0.0000` | `1.0000` | `0.8137` | `0.0222` |
| `TinyMLPPolicy` (`12293`) | `full_28d` | `28/28` | `+0.6292` (`[+0.5649, +0.6935]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6292` | `0.9770` | `0.0333` | `1.0000` | `1.0000` |
| `TinyMLPPolicy` (`12293`) | `core_sufficient_stats` | `16/28` | `+0.6529` (`[+0.5833, +0.7225]`) | `+0.0237` (`[-0.0620, +0.1093]`) | `+0.6529` | `0.9667` | `0.0000` | `0.7676` | `0.9111` |
| `TinyMLPPolicy` (`12293`) | `posterior_only` | `15/28` | `+0.4797` (`[+0.3648, +0.5946]`) | `-0.1496` (`[-0.2801, -0.0190]`) | `+0.4797` | `0.8864` | `0.0222` | `0.7730` | `0.8111` |
| `TinyMLPPolicy` (`12293`) | `horizon_value_only` | `7/28` | `+0.0000` (`[+0.0000, +0.0000]`) | `-0.6292` (`[-0.6935, -0.5649]`) | `+0.0000` | `0.0000` | `1.0000` | `0.7357` | `0.0333` |
| `TinyMLPPolicy` (`12293`) | `no_canary_aux_only` | `13/28` | `+0.0000` (`[+0.0000, +0.0000]`) | `-0.6292` (`[-0.6935, -0.5649]`) | `+0.0000` | `0.0000` | `1.0000` | `0.7457` | `0.0333` |

## 3. Cross-Track Contrast: Compact Sufficient Statistics vs Raw 4k/8k Qwen2.5 Truncation

| Representation / Cohort | `is_open_weight_llm` | Scale / Context | Canary-Map Eviction | Held-Out Score | Above `0.000` | Bottleneck Regime |
| :--- | :---: | :--- | ---: | ---: | :---: | :--- |
| `EmpiricalBayesPolicy` | `False` | `11` params (`0` ctx tok) | `0.0%` (`0/1186`) | `+0.6223` (`n=90`) | `Yes` | Explicit core sufficient statistics |
| `ScalingLogisticPolicy` | `False` | `82` params (`0` ctx tok) | `0.0%` (`0/1186`) | `+0.6107` (`n=90`) | `Yes` | Low-dim calibrated linear sufficient stats |
| `CompactLinearDAggerPolicy (core_sufficient_stats)` | `False` | `785` params (`19/28` feats) | `0.0%` (`0/1186`) | `+0.5613` vs `+0.6632` full | `Yes` | Core posterior + canary + V_obs + horizon |
| `TinyMLPPolicy (core_sufficient_stats)` | `False` | `12,293` params (`16/28` feats) | `0.0%` (`0/1186`) | `+0.6529` vs `+0.6292` full | `Yes` | Auxiliary-denoised neural sufficient stats |
| `Qwen2.5-1.5B Raw 4k/8k Pool (19 runs)` | `True` | `~1.54B` (`4k/8k` raw MCP) | `98.0%` (`1162/1186` at `4k`; `84.7%` at `8k`) | `-0.3271` (`n=450`; best `WS4-v3-8k-s2-dbd0` `-0.050`) | `0 / 19` | Truncation-induced `no_canary_aux_only` / `horizon_value_only` collapse |

## 4. Key Findings & Reproduction

1. **Minimal Sufficient-Statistic Sufficiency**: Retaining only top suspect posterior marginals, surfaced canary hits, `V_obs`, and day/horizon fraction (`core_sufficient_stats`) achieves `+0.5613` on `CompactLinearDAggerPolicy` (`1.0000` precision) and `+0.6529` on `TinyMLPPolicy` (`0.9667` precision vs `+0.6292` on `full_28d`), matching `11`-param `EmpiricalBayesPolicy` (`+0.6223`) and `82`-param `ScalingLogisticPolicy` (`+0.6107`).
2. **Dual-Factor Necessity (`posterior_only` vs `horizon_value_only`)**: Masking `V_obs` and horizon features (`posterior_only`) preserves suspect identification above `0.000` but degrades stopping calibration and precision; conversely, masking suspect/canary-hit features (`horizon_value_only`) forces uniform `1/N` posteriors and collapses both policies to `0.0000` (`100%` calibrated abstention).
3. **Why Raw 4k/8k Qwen2.5 Collapses (`0 / 19` > `0.000`)**: Raw MCP headers consume `~2848` tokens and evict `98.0%` (`1162/1186`) of planted `plant_canary` maps at `4k`, physically forcing a `1.54B` LLM into the `no_canary_aux_only` / `horizon_value_only` blind regime.

```bash
python scripts/tiebreak_representation_bottleneck_audit.py --generate --workers 8
python scripts/tiebreak_representation_bottleneck_audit.py --check
python -m pytest -q tests/test_tiebreak_representation_bottleneck.py
```
