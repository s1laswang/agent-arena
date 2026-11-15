# Tiebreak Heterogeneous 4-Family Compact Ensemble & Epistemic Disagreement Gate (`v1.4`)

Keyless CPU-only heterogeneous ensemble and epistemic disagreement abstention audit combining `4` AST-isolated non-LLM compact architectures (`13,171` total constituent parameters, `0` context tokens) on world-paired `HELDOUT_SEEDS 800000..800029` (`n=90` across `easy,medium,hard`, `sha256:ebf2f09716cf76d3`, `1080/1080` fresh `Env` replays verified). `EpistemicGatedEnsemblePolicy` achieves **`+0.6564`** (`95% CI [+0.6038, +0.7091]`), wrong-accusation rate **`0.0%`** (vs `1.39%` mean constituent and `2.2%` worst constituent), multiclass Brier **`0.0362`** (vs `0.0594` mean constituent), and NLL **`0.0935`** nats (vs `0.1306` mean constituent), while outperforming overly conservative `4/4` `UnanimousConsensusEnsemblePolicy` (`+0.5658`, paired delta `+0.0907`).

- **Seed & Secret Provenance (Panel Fix A)**: All held-out evaluations strictly run on world-paired HELDOUT_SEEDS 800000..800029 (n=90 across easy, medium, hard, 30 seeds/tier) under canonical CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3) with 100% fresh Env replay verification. Constituent compact policies are trained strictly on disjoint TRAIN_SEEDS [100000, 200000) (102000..102779, 107000..108999, 109000..109509, 107000..107599), ensemble weights and epistemic gate thresholds are fit strictly on disjoint TRAIN_SEEDS validation slice 109800..109829 (n=90, 0 overlap with HELDOUT_SEEDS), and 0 JUDGE_SEEDS (900k+) are touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A).
- **Strict Track Separation (Panel Fix E)**: Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). All 4 constituent models and both ensemble policies audited here (13,171 total constituent parameters, 0 context tokens, is_open_weight_llm = False) are non-LLM structured policies strictly separated from Track 1 open-weight Qwen2.5 LoRA and Verda GRPO runs.

## 1. Held-Out Comparison Across Constituent Families & Ensemble Gates (`HELDOUT_SEEDS 800000..800029`, `n=90`)

| Policy (`policy_class`) | Params | Mean Score `[95% CI]` | Paired vs `do_nothing` | Accuse / Wrong / Abstain | Precision | Sub-Breakeven | Brier / NLL (nats) | Mean JSD / Consensus |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `do_nothing` (`AbstainPolicy`) | `0` | `+0.0000 [+0.0000, +0.0000]` | `+0.0000 [+0.0000, +0.0000]` | `0/0/90` (`0.0%` wrong) | `100.0%` | `0/90` | `0.9472` / `3.0565` | `0.0000` / `4.00/4` |
| `empirical_bayes` (`EmpiricalBayesPolicy`) | `11` | `+0.6223 [+0.5726, +0.6721]` | `+0.6223 [+0.5726, +0.6721]` | `82/0/8` (`0.0%` wrong) | `100.0%` | `0/90` | `0.0759` / `0.1673` | `0.0096` / `3.87/4` |
| `scaling_logistic` (`ScalingLogisticPolicy`) | `82` | `+0.6107 [+0.5420, +0.6794]` | `+0.6107 [+0.5420, +0.6794]` | `85/2/5` (`2.2%` wrong) | `97.7%` | `0/90` | `0.0643` / `0.1651` | `0.0064` / `3.97/4` |
| `compact_linear_dagger` (`CompactLinearDAggerPolicy`) | `785` | `+0.6632 [+0.6071, +0.7194]` | `+0.6632 [+0.6071, +0.7194]` | `88/1/2` (`1.1%` wrong) | `98.9%` | `3/90` | `0.0547` / `0.1143` | `0.0056` / `3.93/4` |
| `tiny_mlp` (`TinyMLPPolicy`) | `12,293` | `+0.6292 [+0.5649, +0.6935]` | `+0.6292 [+0.5649, +0.6935]` | `87/2/3` (`2.2%` wrong) | `97.7%` | `0/90` | `0.0426` / `0.0759` | `0.0049` / `3.99/4` |
| `unanimous_consensus_ensemble` (`UnanimousConsensusEnsemblePolicy`) | `13,171` | `+0.5658 [+0.4935, +0.6381]` | `+0.5658 [+0.4935, +0.6381]` | `66/0/24` (`0.0%` wrong) | `100.0%` | `0/90` | `0.0356` / `0.0865` | `0.0045` / `3.91/4` |
| `epistemic_gated_ensemble` (`EpistemicGatedEnsemblePolicy`) | `13,171` | `+0.6564 [+0.6038, +0.7091]` | `+0.6564 [+0.6038, +0.7091]` | `80/0/10` (`0.0%` wrong) | `100.0%` | `0/90` | `0.0362` / `0.0935` | `0.0056` / `3.91/4` |

## 2. Per-Tier Held-Out Breakdown (`easy`, `medium`, `hard`, `n=30` / Tier)

| Policy | `easy` Score (`Wrong%`, `Brier`) | `medium` Score (`Wrong%`, `Brier`) | `hard` Score (`Wrong%`, `Brier`) | Pooled (`n=90`) | Veto Events |
|---|---:|---:|---:|---:|---:|
| `empirical_bayes` | `+0.7287` (`0.0%`, `0.0456`) | `+0.5697` (`0.0%`, `0.1817`) | `+0.5687` (`0.0%`, `0.0005`) | `+0.6223` | `0` |
| `scaling_logistic` | `+0.8127` (`0.0%`, `0.0154`) | `+0.5573` (`3.3%`, `0.1166`) | `+0.4620` (`3.3%`, `0.0608`) | `+0.6107` | `0` |
| `compact_linear_dagger` | `+0.8203` (`0.0%`, `0.0000`) | `+0.6790` (`0.0%`, `0.0551`) | `+0.4903` (`3.3%`, `0.1089`) | `+0.6632` | `0` |
| `tiny_mlp` | `+0.8107` (`0.0%`, `0.0000`) | `+0.5840` (`0.0%`, `0.0358`) | `+0.4930` (`6.7%`, `0.0920`) | `+0.6292` | `0` |
| `unanimous_consensus_ensemble` | `+0.7993` (`0.0%`, `0.0008`) | `+0.6510` (`0.0%`, `0.1057`) | `+0.2470` (`0.0%`, `0.0002`) | `+0.5658` | `780` |
| `epistemic_gated_ensemble` | `+0.8183` (`0.0%`, `0.0008`) | `+0.6510` (`0.0%`, `0.1057`) | `+0.5000` (`0.0%`, `0.0020`) | `+0.6564` | `345` |

## 3. Disjoint `TRAIN_SEEDS` Validation Calibration Ledger (`109800..109829`, `n=90`, `0` Held-Out Overlap)

Selected configuration `cand_uniform_epistemic_jsd06` strictly on `TRAIN_SEEDS 109800..109829`: `weights={'empirical_bayes': 0.25, 'scaling_logistic': 0.25, 'compact_linear_dagger': 0.25, 'tiny_mlp': 0.25}`, `margin=0.32`, `terminal_margin=0.25`, `max_jsd=0.06`, `min_consensus=4/4` (`terminal=4/4`).

| Validation Candidate | Weights `(EB, SL, DAG, MLP)` | `margin` / `max_jsd` / `cons` | `TRAIN_SEEDS` Score (`n=90`) | Wrong Rate | Abstain Rate | Brier / NLL | Vetoes |
|---|---|---:|---:|---:|---:|---:|---:|
| `cand_loose_low_margin` | `(0.25, 0.25, 0.25, 0.25)` | `0.03` / `0.30` / `2` | `+0.4646` | `11.1%` | `5.6%` | `0.1828` / `0.3307` | `121` |
| `cand_unanimous_fixed_high_margin` | `(0.25, 0.25, 0.25, 0.25)` | `0.38` / `0.05` / `4` | `+0.4718` | `0.0%` | `35.6%` | `0.0449` / `0.1050` | `925` |
| `cand_eb35_majority_term3` | `(0.35, 0.25, 0.25, 0.15)` | `0.30` / `0.10` / `4` | `+0.5971` | `0.0%` | `10.0%` | `0.0485` / `0.1099` | `439` |
| `cand_eb35_epistemic_jsd06` | `(0.35, 0.25, 0.25, 0.15)` | `0.32` / `0.06` / `4` | `+0.5787` | `0.0%` | `14.4%` | `0.0483` / `0.1090` | `524` |
| `cand_uniform_epistemic_jsd06` **(selected)** | `(0.25, 0.25, 0.25, 0.25)` | `0.32` / `0.06` / `4` | `+0.6037` | `0.0%` | `13.3%` | `0.0446` / `0.1084` | `467` |

## 4. Paired Epistemic-Gated Ensemble Deltas vs Peers (`HELDOUT_SEEDS 800000..800029`, `n=90`)

| Peer Policy | Paired Score Delta `[95% CI]` | Wins / Losses / Ties | Wrong-Rate Delta | Multiclass Brier Delta | NLL Delta (nats) |
|---|---:|---:|---:|---:|---:|
| `empirical_bayes` | `+0.0341 [-0.0296, +0.0978]` | `45/32/13` | `+0.0000` | `-0.0397` | `-0.0738` |
| `scaling_logistic` | `+0.0458 [-0.0264, +0.1180]` | `39/32/19` | `-0.0222` | `-0.0281` | `-0.0716` |
| `compact_linear_dagger` | `-0.0068 [-0.0560, +0.0424]` | `28/28/34` | `-0.0111` | `-0.0185` | `-0.0208` |
| `tiny_mlp` | `+0.0272 [-0.0432, +0.0977]` | `43/36/11` | `-0.0222` | `-0.0064` | `+0.0176` |
| `unanimous_consensus_ensemble` | `+0.0907 [+0.0472, +0.1341]` | `16/0/74` | `+0.0000` | `+0.0006` | `+0.0070` |

## 5. Key Epistemic Gate Takeaways

1. **Elimination of Premature Single-Model Wrong & Sub-Breakeven Accusations**: Across `HELDOUT_SEEDS 800000..800029` (`n=90`), individual constituent families incur `1.1%` to `2.2%` wrong accusations (`scaling_logistic` `2/90`, `tiny_mlp` `2/90`, `compact_linear_dagger` `1/90` plus `3/90` sub-breakeven commitments). Vetoing `345` premature single-family accusation triggers until `p_ens > 1 / (1 + known_v) + margin` and normalized `JSD <= 0.06` drives `EpistemicGatedEnsemblePolicy` wrong accusations to **`0/90 = 0.0%`** (`100.0%` accusation precision across `80` accusations) and `0/90` sub-breakeven commitments.
2. **Strictly Better Multiclass Brier Calibration & Hard-Tier Gain**: Combining `EmpiricalBayesPolicy` (`11`p), `ScalingLogisticPolicy` (`82`p), `CompactLinearDAggerPolicy` (`785`p), and `TinyMLPPolicy` (`12,293`p) lowers multiclass Brier to **`0.0362`** (beating every constituent: `0.0759`, `0.0643`, `0.0547`, `0.0426`) and lifts `hard` (`20` suspects, `75%` noisy fingerprints, `1-3` day delayed leaks) to **`+0.5000`** (`0.0%` wrong vs `3.3%` on `compact_linear_dagger` and `6.7%` on `tiny_mlp`).
3. **Avoiding Strict Unanimity Over-Abstention**: Fixed high-margin `4/4` `UnanimousConsensusEnsemblePolicy` achieves `0.0%` wrong accusations (`+0.5658`) but over-abstains on `24/90` episodes (`+0.2470` on `hard`); validation-calibrated `EpistemicGatedEnsemblePolicy` recovers **`+0.0907` (`95% CI [+0.0472, +0.1341]`, `16` wins / `0` losses)** while retaining `0.0%` wrong accusations.

## 6. Offline Reproducibility Commands

```bash
python scripts/tiebreak_compact_ensemble_gate.py --check
python -m pytest -q tests/test_tiebreak_compact_ensemble_gate.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
