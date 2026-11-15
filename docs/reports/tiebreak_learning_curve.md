# Tiebreak Sample-Complexity Learning Curve Audit (v1.4)

## 1. Executive Summary and Crossover Findings

- **Schema / Audit ID**: `canary.tiebreak.learning_curve.v1` / `tiebreak-sample-complexity-learning-curve-v14`
- **Training slice (strictly disjoint `TRAIN_SEEDS [100000, 200000)`)**: `110000..111499` partitioned into `K=3` pairwise-disjoint folds (`110000..110287, 110500..110787, 111000..111287`)
- **Held-out world-paired evaluation**: `HELDOUT_SEEDS 800000..800029` (`n=90`: `30` seeds per tier across `easy, medium, hard`) under shared `world_secret_tag` `sha256:ebf2f09716cf76d3` (`TemplateProvider()`, `1710/1710` fresh `Env` replays verified, `0` invalid episodes)
- **11-parameter `EmpiricalBayesPolicy` crossover**: crosses `ci95_low(after - before_naive) > 0.0` across all `K=3` folds at **`N_train = 9`** episodes and beats the `0.000` untrained-abstain bar (`after_ci95_low > 0.0` on all `3/3` folds) at **`N_train = 9`** episodes (`N_train <= 18`)
- **82-parameter `ScalingLogisticPolicy` comparison (`scaling_summary.json`)**: on the same `90` held-out worlds (`800000..800029`), `N_train = 15` reaches pooled `mean_score = +0.32878` (`ci95_low = +0.26707 > 0.0`) but scores **`0.00000`** (`100%` abstention) on `hard` tier; all-tier (`easy, medium, hard`) `ci95_low > 0.0` requires **`N_train = 60`** (`>= 60` on the `(0, 15, 60, 240, 900)` grid) and asymptotic `> +0.600` score requires **`N_train = 900`** (`>= 90`)
- **Higher-capacity compact vs raw-transcript LLM scaling**: `785`-param `CompactLinearDAggerPolicy` (`N_train = 510`, `after = +0.62672`) and `12293`-param `TinyMLPPolicy` (`N_train = 600`, `after = +0.61406`) pass all strict paired-CI gates once explicit compact state externalization compresses transcripts into low-dimensional sufficient statistics, whereas **`0 / 19`** open-weight `Qwen2.5` raw-transcript LoRA runs beat `0.000` even at **`24074`** solver-relabelled DAgger states

## 2. EmpiricalBayesPolicy (11 Params) K=3 Cross-Fold Learning Curve

Untrained `eb_naive_prior` baseline (`N_train = 0`) on `HELDOUT_SEEDS 800000..800029` (`n=90`): `mean_score = -0.38567` (`95% CI [-0.55797, -0.21336]`), `accuracy = 0.35556`, `wrong_accuse_rate = 0.64444`, `abstain_rate = 0.00000`.

| N_train | K Folds | Params | Cross-Fold Score (Mean +/- SE) | Paired Delta vs Naive (Mean +/- SE) | Min Fold Paired CI95 Low | Min Fold After CI95 Low | Hard-Tier Score (Mean +/- SE) | Cross-Fold Acc | Wrong Rate | Abstain Rate | Folds Passing (Paired / >0) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 (naive) | 1 | 0 | -0.38567 +/- 0.00000 | +0.00000 +/- 0.00000 | +0.00000 | -0.55797 | -0.84667 +/- 0.00000 | 0.35556 | 0.64444 | 0.00000 | 0/3 / 0/3 |
| 9 | 3 | 11 | +0.47974 +/- 0.09411 | +0.86541 +/- 0.09411 | +0.51993 | +0.16403 | +0.28555 +/- 0.12631 | 0.87407 | 0.06667 | 0.05926 | 3/3 / 3/3 |
| 18 | 3 | 11 | +0.55863 +/- 0.03038 | +0.94430 +/- 0.03038 | +0.69785 | +0.39600 | +0.56156 +/- 0.01710 | 0.90741 | 0.04074 | 0.05185 | 3/3 / 3/3 |
| 36 | 3 | 11 | +0.61452 +/- 0.00861 | +1.00019 +/- 0.00861 | +0.80866 | +0.50893 | +0.55355 +/- 0.01886 | 0.93704 | 0.02222 | 0.04074 | 3/3 / 3/3 |
| 72 | 3 | 11 | +0.57759 +/- 0.01202 | +0.96326 +/- 0.01202 | +0.76903 | +0.45665 | +0.53433 +/- 0.01564 | 0.91481 | 0.04444 | 0.04074 | 3/3 / 3/3 |
| 144 | 3 | 11 | +0.63659 +/- 0.00970 | +1.02226 +/- 0.00971 | +0.84208 | +0.56379 | +0.57400 +/- 0.02683 | 0.95185 | 0.00741 | 0.04074 | 3/3 / 3/3 |
| 288 | 3 | 11 | +0.61996 +/- 0.00838 | +1.00563 +/- 0.00838 | +0.82659 | +0.53117 | +0.49589 +/- 0.05135 | 0.94074 | 0.01852 | 0.04074 | 3/3 / 3/3 |

## 3. Per-Fold Breakdown on Disjoint TRAIN_SEEDS (110000..111499)

| N_train | Fold | Train Seed Slice | Held-Out Score [95% CI] | Paired Delta vs Naive [95% CI] | Easy | Medium | Hard | Acc | Wrong | Abstain |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 9 | 0 | `110000..110194` | +0.56333 [+0.49250, +0.63416] | +0.94900 [+0.78968, +1.10832] | +0.79633 | +0.58933 | +0.30433 | 0.90000 | 0.02222 | 0.07778 |
| 9 | 1 | `110500..110694` | +0.58400 [+0.52687, +0.64113] | +0.96967 [+0.81050, +1.12883] | +0.74167 | +0.51600 | +0.49433 | 0.94444 | 0.01111 | 0.04444 |
| 9 | 2 | `111000..111194` | +0.29189 [+0.16403, +0.41975] | +0.67756 [+0.51993, +0.83519] | +0.73533 | +0.08233 | +0.05800 | 0.77778 | 0.16667 | 0.05556 |
| 18 | 0 | `110000..110197` | +0.60111 [+0.55289, +0.64933] | +0.98678 [+0.81760, +1.15596] | +0.68433 | +0.57233 | +0.54667 | 0.92222 | 0.00000 | 0.07778 |
| 18 | 1 | `110500..110697` | +0.57500 [+0.50323, +0.64677] | +0.96067 [+0.77619, +1.14515] | +0.59833 | +0.53100 | +0.59567 | 0.92222 | 0.03333 | 0.04444 |
| 18 | 2 | `111000..111197` | +0.49978 [+0.39600, +0.60355] | +0.88544 [+0.69785, +1.07303] | +0.60467 | +0.35233 | +0.54233 | 0.87778 | 0.08889 | 0.03333 |
| 36 | 0 | `110000..110203` | +0.59733 [+0.50893, +0.68574] | +0.98300 [+0.80866, +1.15734] | +0.78633 | +0.43033 | +0.57533 | 0.91111 | 0.05556 | 0.03333 |
| 36 | 1 | `110500..110703` | +0.62211 [+0.56726, +0.67697] | +1.00778 [+0.84574, +1.16982] | +0.75367 | +0.59667 | +0.51600 | 0.94444 | 0.01111 | 0.04444 |
| 36 | 2 | `111000..111203` | +0.62411 [+0.58214, +0.66608] | +1.00978 [+0.83971, +1.17985] | +0.69167 | +0.61133 | +0.56933 | 0.95556 | 0.00000 | 0.04444 |
| 72 | 0 | `110000..110215` | +0.55800 [+0.45665, +0.65935] | +0.94367 [+0.76903, +1.11830] | +0.78833 | +0.32067 | +0.56500 | 0.88889 | 0.07778 | 0.03333 |
| 72 | 1 | `110500..110715` | +0.57533 [+0.49436, +0.65631] | +0.96100 [+0.79531, +1.12669] | +0.75367 | +0.44800 | +0.52433 | 0.92222 | 0.04444 | 0.03333 |
| 72 | 2 | `111000..111215` | +0.59944 [+0.54296, +0.65593] | +0.98511 [+0.81513, +1.15509] | +0.69767 | +0.58700 | +0.51367 | 0.93333 | 0.01111 | 0.05556 |
| 144 | 0 | `110000..110239` | +0.65200 [+0.59915, +0.70485] | +1.03767 [+0.87611, +1.19922] | +0.77233 | +0.58233 | +0.60133 | 0.95556 | 0.01111 | 0.03333 |
| 144 | 1 | `110500..110739` | +0.63911 [+0.59845, +0.67977] | +1.02478 [+0.85488, +1.19467] | +0.70767 | +0.60933 | +0.60033 | 0.95556 | 0.00000 | 0.04444 |
| 144 | 2 | `111000..111239` | +0.61867 [+0.56379, +0.67355] | +1.00433 [+0.84208, +1.16659] | +0.75400 | +0.58167 | +0.52033 | 0.94444 | 0.01111 | 0.04444 |
| 288 | 0 | `110000..110287` | +0.62222 [+0.55696, +0.68748] | +1.00789 [+0.84337, +1.17240] | +0.77033 | +0.62433 | +0.47200 | 0.93333 | 0.02222 | 0.04444 |
| 288 | 1 | `110500..110787` | +0.63322 [+0.59213, +0.67431] | +1.01889 [+0.85124, +1.18653] | +0.70767 | +0.59767 | +0.59433 | 0.95556 | 0.00000 | 0.04444 |
| 288 | 2 | `111000..111287` | +0.60444 [+0.53117, +0.67772] | +0.99011 [+0.82659, +1.15363] | +0.76833 | +0.62367 | +0.42133 | 0.93333 | 0.03333 | 0.03333 |

## 4. ScalingLogisticPolicy (82 Params) Curve on Identical 90 Held-Out Worlds

Loaded from `results/tiebreak/scaling/scaling_summary.json` (`TRAIN_SEEDS 107000..108999`, `HELDOUT_SEEDS 800000..800029`):

| N_train | Params | Held-Out n | Mean Score [95% CI] | Luck-Adjusted EV | Hard-Tier Score (CI95 Low) | Accuracy | Abstain Rate | Wrong Rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 82 | 90 | +0.00000 [+0.00000, +0.00000] | +0.00000 | +0.00000 (+0.00000) | 0.00000 | 1.00000 | 0.00000 |
| 15 | 82 | 90 | +0.32878 [+0.26707, +0.39049] | +0.32878 | +0.00000 (+0.00000) | 0.57778 | 0.42222 | 0.00000 |
| 60 | 82 | 90 | +0.59767 [+0.54245, +0.65289] | +0.57429 | +0.43033 (+0.36140) | 0.95556 | 0.03333 | 0.01111 |
| 240 | 82 | 90 | +0.59467 [+0.53665, +0.65269] | +0.58501 | +0.41167 (+0.30033) | 0.93333 | 0.05556 | 0.01111 |
| 900 | 82 | 90 | +0.61067 [+0.54196, +0.67938] | +0.61553 | +0.46200 (+0.34333) | 0.92222 | 0.05556 | 0.02222 |

## 5. Cross-Architecture Parameter Efficiency and Raw-Transcript Bottleneck

| Architecture / Family | Track | Open-Weight LLM | Learned Params | Training Budget | Held-Out Eval Slice | Before Score | After Score | Paired CI95 Low | Panel Fix E Bar |
|---|---|---|---:|---|---|---:|---:|---:|---|
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `track_2` | `False` | 11 | `N_train=360` (`102000..102779`) | `800000..800059` (`n=180`) | -0.42089 | +0.60728 | +0.91517 | `PASS (Non-LLM Control)` |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `track_2` | `False` | 82 | `N_train=900` (`107000..108999`) | `800000..800029` (`n=90`) | +0.00000 | +0.61067 | +0.54196 | `PASS (Non-LLM Control)` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `track_2` | `False` | 785 | `N_train=510` (`109000..109509`) | `800000..800059` (`n=180`) | +0.00000 | +0.62672 | +0.57753 | `PASS (Non-LLM Control)` |
| `TinyMLP` (`tiny-mlp-dagger-v14`) | `track_1` | `False` | 12293 | `N_train=600` (`107000..107599`) | `800000..800059` (`n=180`) | -0.85556 | +0.61406 | +1.38505 | `PASS (Non-LLM Control)` |
| `Qwen2.5-1.5B LoRA (19 historical runs)` | `track_1_open_weight_llm` | `True` | LoRA `r=16` (`1.5B` base) | `24074` DAgger states (`19` runs) | varied (`best WS4-v3-8k-s2-dbd0`) | +0.00000 | -0.05000 | n/a (`0 / 19 > 0.000`) | `FAIL (HOLD)` |

## 6. Governance Disclosures (Panel Fix A and Panel Fix E)

- **Panel Fix A (Seed Hygiene and Post-Hoc Dev Disclosure)**: All EmpiricalBayesPolicy learning-curve fits use strictly disjoint TRAIN_SEEDS inside [100000, 200000) (specifically 110000..111500 partitioned into K=3 disjoint folds: 110000..110287, 110500..110787, 111000..111287) and evaluate on world-paired HELDOUT_SEEDS 800000..800029 (n=90: 30 per tier across easy, medium, hard) under shared deterministic world_secret_tag sha256:ebf2f09716cf76d3 (0 JUDGE_SEEDS touched). Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A).
- **Panel Fix E (Strict Track Separation and Honest Null Ledger)**: Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in experiment_ledger.json beat untrained base (0.000), including DAgger r1 on 24074 solver-relabelled raw-transcript states, so the README.md Qwen addendum remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). All compact models compared here (EmpiricalBayesPolicy 11 params, ScalingLogisticPolicy 82 params, CompactLinearDAggerPolicy 785 params, TinyMLPPolicy 12293 params; is_open_weight_llm = False) are non-LLM compact parametric or neural policies strictly separated from open-weight Qwen2.5 LoRA runs.

## 7. Reproduction Commands

```bash
python scripts/tiebreak_learning_curve.py --check
python -m pytest -q tests/test_tiebreak_learning_curve.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
