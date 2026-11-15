# Selective Prediction Risk-Coverage Curve, AURC & Split-Conformal Abstention Audit (`v1.4`)

Under Canary's asymmetric payoff (`+V` if right, `-1.0` if wrong, `0.0` if abstain), stopping and abstention form a selective prediction and split-conformal risk-control problem (El-Yaniv & Wiener 2010; Angelopoulos et al. 2022). We calibrate finite-sample split-conformal posterior margin thresholds `tau_alpha` over `m(h) = p_top(h) - 1/(1 + V_hat(h))` strictly on disjoint `TRAIN_SEEDS 109600..109629` (`n=90` across `easy,medium,hard`), and evaluate all `4` AST-isolated compact policies (`EmpiricalBayesPolicy` `11`p, `ScalingLogisticPolicy` `82`p, `CompactLinearDAggerPolicy` `785`p, `TinyMLPPolicy` `12,293`p) on world-paired `HELDOUT_SEEDS 800000..800029` (`n=90`, `world_secret_tag` `sha256:ebf2f09716cf76d3`, **`845/845` (`100.0%`) canonical `Env` replays verified**).

- **Seed & Secret Provenance (Panel Fix A)**: Calibration strictly uses `TRAIN_SEEDS 109600..109629` inside `[100000, 200000)` (`0` overlap with policy training seeds `102000..109509` and `0` overlap with held-out), evaluation strictly uses `HELDOUT_SEEDS 800000..800029` inside `[800000, 800200)` under `sha256:ebf2f09716cf76d3`, and **`0` `JUDGE_SEEDS` (`>= 900000`) are touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Track 1 open-weight LLM baselines (`is_open_weight_llm = True`) and non-LLM compact policies (`is_open_weight_llm = False`) are strictly separated below.

## 1. Selective Risk-Coverage Integrals (`AURC` & `AUSC`) vs Track 1 Open-Weight Extremes

| Policy / Run | Track | Params | Native Cov / Abstain | Native FA / Cond Risk | Native Score (`95% CI`) | `AURC` / `E-AURC` | `AUSC` | Peak Selective Score @ Cov |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | Non-LLM Compact | `11` | `0.911` / `0.089` | `0.000` / `0.000` | `+0.6223 [+0.5726, +0.6721]` | `0.00316` / `0.00052` | `+0.3691` | `+0.6264` @ `0.922` |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | Non-LLM Compact | `82` | `0.944` / `0.056` | `0.022` / `0.024` | `+0.6107 [+0.5420, +0.6794]` | `0.00313` / `0.00188` | `+0.3533` | `+0.6218` @ `0.933` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | Non-LLM Compact | `785` | `0.978` / `0.022` | `0.011` / `0.011` | `+0.6632 [+0.6071, +0.7194]` | `0.00115` / `0.00078` | `+0.3890` | `+0.6702` @ `0.989` |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | Non-LLM Compact | `12,293` | `0.967` / `0.033` | `0.022` / `0.023` | `+0.6292 [+0.5649, +0.6935]` | `0.00100` / `0.00025` | `+0.3759` | `+0.6562` @ `0.956` |
| `Heuristic` (`baseline-uncalibrated-heuristic-v14`) | Non-LLM Baseline | `0` | `1.000` / `0.000` | `0.244` / `0.244` | `+0.1958 [+0.0507, +0.3409]` | `0.24444` / `n/a` | `+0.0979` | `+0.1958` @ `1.000` |
| `Qwen2.5-1.5B` (`WS4-v2` pooled `n=172`) | Track 1 Open-Weight LLM | `1.5B` | `0.550` / `0.450` | `0.500` / `0.910` | `-0.457 +/- 0.086` | `n/a` (point) | `n/a` | Blind over-coverage (`91%` err) |
| `Qwen2.5-1.5B` (`WS4-v3-8k-s2-dbd0` `n=90`) | Track 1 Open-Weight LLM | `1.5B` | `0.070` / `0.930` | `0.056` / `0.830` | `-0.050 +/- 0.049` | `n/a` (point) | `n/a` | Under-coverage (`7%` accused) |

Across all `4` compact policies, posterior margin ranking yields `AURC` between `0.00100` and `0.00316` (`77x-244x` below uncalibrated `Heuristic`'s `0.24444`) and `AUSC` between `+0.3533` and `+0.3890`. Track 1 open-weight `Qwen2.5` runs fail at opposite selective extremes: `WS4-v2` (`4k` SFT) accuses on `55%` of episodes with `91%` conditional error (`-0.457`), whereas `WS4-v3-8k-s2` (`8k` GRPO) collapses to `7%` coverage (`93%` abstain/cap) yet still errs on `83%` of its accusations (`-0.050`).

## 2. Split-Conformal Risk Control (`TRAIN 109600..109629` -> `HELDOUT 800000..800029`)

| Policy | Target `alpha` | Calibrated `tau_alpha` | Cal FA / CRC Bound `(k+1)/91` | Held-Out Cov / Abstain | Held-Out FA Rate (`count/90`) | Held-Out Cond Risk | Held-Out Score (`95% CI`) | Bound Check |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `EmpiricalBayesPolicy` | `0.02` | `+0.3405` | `0/90` (`0.0110`) | `0.744` / `0.256` | `0.0000` (`0/90`) | `0.0000` | `+0.5459 [+0.4771, +0.6146]` | `exact <= alpha` |
| `EmpiricalBayesPolicy` | `0.05` | `-0.3151` | `3/90` (`0.0440`) | `0.944` / `0.056` | `0.0222` (`2/90`) | `0.0235` | `+0.6042 [+0.5374, +0.6710]` | `exact <= alpha` |
| `EmpiricalBayesPolicy` | `0.10` | `-1.0000` | `6/90` (`0.0769`) | `1.000` / `0.000` | `0.0667` (`6/90`) | `0.0667` | `+0.5663 [+0.4744, +0.6583]` | `exact <= alpha` |
| `EmpiricalBayesPolicy` | `0.20` | `-1.0000` | `6/90` (`0.0769`) | `1.000` / `0.000` | `0.0667` (`6/90`) | `0.0667` | `+0.5663 [+0.4744, +0.6583]` | `exact <= alpha` |
| `ScalingLogisticPolicy` | `0.02` | `+0.3406` | `0/90` (`0.0110`) | `0.567` / `0.433` | `0.0000` (`0/90`) | `0.0000` | `+0.4083 [+0.3323, +0.4843]` | `exact <= alpha` |
| `ScalingLogisticPolicy` | `0.05` | `-0.2884` | `3/90` (`0.0440`) | `0.989` / `0.011` | `0.0333` (`3/90`) | `0.0337` | `+0.6118 [+0.5381, +0.6855]` | `exact <= alpha` |
| `ScalingLogisticPolicy` | `0.10` | `-1.0000` | `4/90` (`0.0549`) | `1.000` / `0.000` | `0.0444` (`4/90`) | `0.0444` | `+0.6007 [+0.5201, +0.6813]` | `exact <= alpha` |
| `ScalingLogisticPolicy` | `0.20` | `-1.0000` | `4/90` (`0.0549`) | `1.000` / `0.000` | `0.0444` (`4/90`) | `0.0444` | `+0.6007 [+0.5201, +0.6813]` | `exact <= alpha` |
| `CompactLinearDAggerPolicy` | `0.02` | `+0.3112` | `0/90` (`0.0110`) | `0.822` / `0.178` | `0.0000` (`0/90`) | `0.0000` | `+0.6201 [+0.5568, +0.6834]` | `exact <= alpha` |
| `CompactLinearDAggerPolicy` | `0.05` | `-0.4142` | `3/90` (`0.0440`) | `0.978` / `0.022` | `0.0111` (`1/90`) | `0.0114` | `+0.6632 [+0.6071, +0.7194]` | `exact <= alpha` |
| `CompactLinearDAggerPolicy` | `0.10` | `-1.0000` | `5/90` (`0.0659`) | `1.000` / `0.000` | `0.0222` (`2/90`) | `0.0222` | `+0.6591 [+0.5954, +0.7228]` | `exact <= alpha` |
| `CompactLinearDAggerPolicy` | `0.20` | `-1.0000` | `5/90` (`0.0659`) | `1.000` / `0.000` | `0.0222` (`2/90`) | `0.0222` | `+0.6591 [+0.5954, +0.7228]` | `exact <= alpha` |
| `TinyMLPPolicy` | `0.02` | `-0.3151` | `0/90` (`0.0110`) | `0.989` / `0.011` | `0.0222` (`2/90`) | `0.0225` | `+0.6401 [+0.5787, +0.7015]` | `within 1-SE binomial` |
| `TinyMLPPolicy` | `0.05` | `-1.0000` | `2/90` (`0.0330`) | `1.000` / `0.000` | `0.0333` (`3/90`) | `0.0333` | `+0.6290 [+0.5593, +0.6987]` | `exact <= alpha` |
| `TinyMLPPolicy` | `0.10` | `-1.0000` | `2/90` (`0.0330`) | `1.000` / `0.000` | `0.0333` (`3/90`) | `0.0333` | `+0.6290 [+0.5593, +0.6987]` | `exact <= alpha` |
| `TinyMLPPolicy` | `0.20` | `-1.0000` | `2/90` (`0.0330`) | `1.000` / `0.000` | `0.0333` (`3/90`) | `0.0333` | `+0.6290 [+0.5593, +0.6987]` | `exact <= alpha` |

## 3. Held-Out Risk-Coverage & Score-Coverage Operating Grid (`n=90`)

| Policy | Cov `0.20` (Risk / Score) | Cov `0.50` (Risk / Score) | Cov `0.80` (Risk / Score) | Cov `0.90` (Risk / Score) | Cov `0.95` (Risk / Score) | Cov `1.00` Forced (Risk / Score) |
|---|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `0.000` / `+0.1686` | `0.000` / `+0.3934` | `0.000` / `+0.5763` | `0.000` / `+0.6210` | `0.035` / `+0.5931` | `0.067` / `+0.5663` |
| `ScalingLogisticPolicy` | `0.000` / `+0.1506` | `0.000` / `+0.3629` | `0.000` / `+0.5620` | `0.012` / `+0.6112` | `0.023` / `+0.6107` | `0.044` / `+0.6007` |
| `CompactLinearDAggerPolicy` | `0.000` / `+0.1739` | `0.000` / `+0.4102` | `0.000` / `+0.6080` | `0.000` / `+0.6538` | `0.012` / `+0.6548` | `0.022` / `+0.6591` |
| `TinyMLPPolicy` | `0.000` / `+0.1730` | `0.000` / `+0.3980` | `0.000` / `+0.5781` | `0.000` / `+0.6219` | `0.000` / `+0.6562` | `0.033` / `+0.6290` |

### Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_selective_risk_coverage_audit.py --check
python -m pytest -q tests/test_tiebreak_selective_risk_coverage.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
