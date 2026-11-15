# Tiebreak Access-Restriction Containment vs Pure Canary Identification Audit (`v1.4`)

Keyless CPU-only counterfactual value decomposition separating active access-restriction leak containment (`restrict_access` / `unrestrict_access`) from pure canary identification (`plant_canary` + calibrated `accuse`) across `720` world-paired held-out episodes (`2` compact non-LLM policies x `4` containment conditions x `n=90` on `HELDOUT_SEEDS 800000..800029`, `30`/tier across `easy`, `medium`, `hard` under `sha256:ebf2f09716cf76d3`, `720/720` fresh `Env` replays verified) plus `1080` disjoint `TRAIN_SEEDS 109700..109729` threshold-selection episodes.

## 1. Held-Out Containment vs Identification Decomposition (`n=90` per condition)

| Policy (`params`) | Condition | `tau_restrict` | Mean Score `[95% CI]` | Delta vs Unmodified `[95% CI]` | Delta vs `do_nothing` `[95% CI]` | Restrict / Ep | Canaries / Ep | Accuse Day | True `V` @ Accuse | Wrong | Abstain |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` (`11`p) | `no_restrict` | suppressed | `+0.6223` (`[+0.5726, +0.6721]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6223` (`[+0.5726, +0.6721]`) | `0.00` | `9.67` | `7.40` | `0.6831` | `0.000` | `0.089` |
| `EmpiricalBayesPolicy` (`11`p) | `default_unmodified` | native | `+0.6223` (`[+0.5726, +0.6721]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6223` (`[+0.5726, +0.6721]`) | `0.00` | `9.67` | `7.40` | `0.6831` | `0.000` | `0.089` |
| `EmpiricalBayesPolicy` (`11`p) | `train_tuned_containment` | `0.46` | `+0.6201` (`[+0.5712, +0.6690]`) | `-0.0022` (`[-0.0100, +0.0055]`) | `+0.6201` (`[+0.5712, +0.6690]`) | `0.62` | `9.43` | `7.30` | `0.6806` | `0.000` | `0.089` |
| `EmpiricalBayesPolicy` (`11`p) | `aggressive_over_restrict` | `0.08` | `+0.4259` (`[+0.3616, +0.4902]`) | `-0.1964` (`[-0.2675, -0.1254]`) | `+0.4259` (`[+0.3616, +0.4902]`) | `4.99` | `10.93` | `6.97` | `0.6182` | `0.000` | `0.311` |
| `CompactLinearDAggerPolicy` (`785`p) | `no_restrict` | suppressed | `+0.6632` (`[+0.6071, +0.7194]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6632` (`[+0.6071, +0.7194]`) | `0.00` | `9.42` | `7.47` | `0.6917` | `0.011` | `0.022` |
| `CompactLinearDAggerPolicy` (`785`p) | `default_unmodified` | native | `+0.6632` (`[+0.6071, +0.7194]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `+0.6632` (`[+0.6071, +0.7194]`) | `0.00` | `9.42` | `7.47` | `0.6917` | `0.011` | `0.022` |
| `CompactLinearDAggerPolicy` (`785`p) | `train_tuned_containment` | `0.28` | `+0.6630` (`[+0.6180, +0.7080]`) | `-0.0002` (`[-0.0241, +0.0236]`) | `+0.6630` (`[+0.6180, +0.7080]`) | `1.31` | `9.18` | `7.18` | `0.6859` | `0.000` | `0.033` |
| `CompactLinearDAggerPolicy` (`785`p) | `aggressive_over_restrict` | `0.08` | `+0.4452` (`[+0.3703, +0.5202]`) | `-0.2180` (`[-0.2944, -0.1416]`) | `+0.4452` (`[+0.3703, +0.5202]`) | `4.99` | `11.36` | `6.50` | `0.6464` | `0.011` | `0.289` |

## 2. Per-Tier Held-Out Breakdown (`n=30` per tier)

| Policy | Condition | Easy (`n=30`) | Medium (`n=30`) | Hard (`n=30`) | Hard Restrict / Ep | Hard Canaries / Ep | Hard True `V` @ Accuse |
|---|---|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `no_restrict` | `+0.7287` | `+0.5697` | `+0.5687` | `0.00` | `16.13` | `0.5687` |
| `EmpiricalBayesPolicy` | `default_unmodified` | `+0.7287` | `+0.5697` | `+0.5687` | `0.00` | `16.13` | `0.5687` |
| `EmpiricalBayesPolicy` | `train_tuned_containment` | `+0.7270` | `+0.5640` | `+0.5693` | `0.63` | `15.67` | `0.5693` |
| `EmpiricalBayesPolicy` | `aggressive_over_restrict` | `+0.4373` | `+0.4500` | `+0.3903` | `3.87` | `20.27` | `0.5323` |
| `CompactLinearDAggerPolicy` | `no_restrict` | `+0.8203` | `+0.6790` | `+0.4903` | `0.00` | `17.87` | `0.5297` |
| `CompactLinearDAggerPolicy` | `default_unmodified` | `+0.8203` | `+0.6790` | `+0.4903` | `0.00` | `17.87` | `0.5297` |
| `CompactLinearDAggerPolicy` | `train_tuned_containment` | `+0.8043` | `+0.6713` | `+0.5133` | `1.57` | `17.20` | `0.5310` |
| `CompactLinearDAggerPolicy` | `aggressive_over_restrict` | `+0.4473` | `+0.5357` | `+0.3527` | `4.20` | `19.93` | `0.5400` |

## 3. Disjoint `TRAIN_SEEDS` Containment Threshold Selection (`109700..109729`, `n=90`)

| Policy | Selected `tau_restrict` | Candidate Grid Scores (`tau: mean_score / restrict_per_ep`) |
|---|---:|---|
| `empirical_bayes` | `0.46` | `0.16`: `+0.5673` (`2.33`/ep), `0.22`: `+0.5699` (`2.16`/ep), `0.28`: `+0.5536` (`1.91`/ep), `0.34`: `+0.5618` (`1.36`/ep), `0.40`: `+0.5633` (`1.03`/ep), `0.46`: `+0.5802` (`0.79`/ep) |
| `compact_linear_dagger` | `0.28` | `0.16`: `+0.6446` (`2.19`/ep), `0.22`: `+0.6458` (`1.99`/ep), `0.28`: `+0.6472` (`1.38`/ep), `0.34`: `+0.6276` (`1.09`/ep), `0.40`: `+0.6304` (`0.86`/ep), `0.46`: `+0.6347` (`0.67`/ep) |

## 4. Mechanism Findings & Provenance Disclosures (Panel Fix A + Panel Fix E)

### Mechanism Summary
1. **Pure Canary Identification Dominates Value Capture**: Both `EmpiricalBayesPolicy` (`11` params) and `CompactLinearDAggerPolicy` (`785` params) emit `0.00` native `restrict_access` calls per episode, so `NoRestrictPolicyWrapper` (`no_restrict`) matches `DefaultPolicy` (`default_unmodified`) bit-for-bit on held-out seeds while actively blocking restriction calls when wrapped around containment policies.
2. **Single-Day Quarantine Trade-Off (`TrainTunedContainmentWrapper`)**: Quarantining top suspects when `p_top * leak_cost > restrict_cost_per_day` while `p_top < 1 / (1 + known_v)` (waiting for in-flight canary confirmation) incurs explicit daily `0.01` restriction friction and blocks new canary assignments while active, showing why rapid canary split identification rather than prolonged quarantine captures nearly all achievable Canary `v1.4` score.
3. **Over-Containment Friction Degradation (`AggressiveOverRestrictWrapper`, `tau_restrict = 0.08`)**: Low-threshold multi-suspect quarantine (`p >= 0.08`) burns daily `V` friction on innocent suspects and prevents `plant_canary` from assigning variants to restricted staff, measurably degrading held-out score.

### Panel Fix A (Seed & Secret Provenance)
- All containment threshold fitting runs strictly on disjoint TRAIN_SEEDS 109700..109729 (30 seeds x 3 tiers = 90 episodes per candidate inside [100000, 200000)), all held-out value decomposition evaluations run strictly on world-paired HELDOUT_SEEDS 800000..800029 (30 seeds x 3 tiers = 90 episodes per condition inside [800000, 800200)) under deterministic world_secret_tag sha256:ebf2f09716cf76d3, and 0 JUDGE_SEEDS (900k+) are touched. Separate historical DEV_SEEDS 0..29 slices in the repository are post-hoc locked, not pre-registered, and 0 DEV_SEEDS episodes are rolled out here (Panel Fix A).

### Panel Fix E (Strict Track Separation)
- Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Non-LLM compact policies (EmpiricalBayesPolicy 11 params and CompactLinearDAggerPolicy 785 params; is_open_weight_llm = False) are strictly separated from Track 1 open-weight LLMs.
- Open-weight Qwen2.5 runs exceeding `0.000`: **`0 / 19`** (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`).
