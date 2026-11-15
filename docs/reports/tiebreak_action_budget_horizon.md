# Action-Budget & Early-Horizon Truncation Anytime Calibration Audit (`v1.4`)

Deterministic keyless anytime decision-quality audit evaluating AST-isolated budget-capped policy wrappers (`BudgetCappedEmpiricalBayesPolicy` `11`p, `BudgetCappedScalingLogisticPolicy` `82`p, `BudgetCappedCompactLinearPolicy` `785`p, `BudgetCappedTinyMLPPolicy` `12,293`p) against `BudgetCappedGreedyHeuristicPolicy` across forced decision-day caps `max_days` in `{3, 5, 7, 10, 21}` (`effective_cap_day = min(max_days, tier_horizon)`) on world-paired `HELDOUT_SEEDS 800000..800029` (`n=90` per cell: `30` `easy`, `30` `medium`, `30` `hard`; `world_secret_tag` `sha256:ebf2f09716cf76d3`, `2250` episodes, **`2250/2250` (`100.0%`) fresh canonical `Env` replays verified**, `0` post-cap investigative actions). When `day >= min(max_days, tier_horizon)`, after reading surfaced morning public state, each policy must immediately make its final calibrated `accuse` vs `abstain` decision without planting further canaries.

- **Seed & Secret Provenance (Panel Fix A)**: All `2250` episodes strictly evaluate `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`, while all learned compact weights and `EmpiricalBayesPolicy` likelihoods originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`900k+`) touched**. Where `DEV_SEEDS 0..29` appear in cross-referenced Canary frontier comparisons (`gemini-4-carbon` vs reference solver), they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` compact policies audited here (`is_open_weight_llm = False`) are non-LLM structured/neural policies strictly separated from open-weight `Qwen2.5` LoRA and Verda GRPO runs.

## 1. Anytime Calibration Headline (`max_days = 3 -> 5 -> 7 -> 10 -> 21`)

| Budget-Capped Policy (`run_id`) | Params | `max_days=3` Score (`hard` Score / Wrong) | `max_days=5` Score | `max_days=7` Score | `max_days=10` Score | `max_days=21` Full Score | Monotonic (`All` / `hard`) | Positive `95% CI` Cells (vs `Heuristic` / vs `0.000`) |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| `BudgetCappedEmpiricalBayesPolicy` (`empirical-bayes-v14`) | `11` | `+0.0690` (`h=+0.0000`, `0/30` wrong) | `+0.2476` | `+0.4268` | `+0.5557` | `+0.6223` | **`Yes` / `Yes`** | **`5/5` & `5/5`** |
| `BudgetCappedScalingLogisticPolicy` (`scaling-logistic-v14`) | `82` | `+0.0671` (`h=+0.0000`, `0/30` wrong) | `+0.2881` | `+0.4133` | `+0.5549` | `+0.6107` | **`Yes` / `Yes`** | **`5/5` & `5/5`** |
| `BudgetCappedCompactLinearPolicy` (`compact-linear-dagger-v14`) | `785` | `+0.0782` (`h=+0.0000`, `0/30` wrong) | `+0.3522` | `+0.4924` | `+0.6002` | `+0.6632` | **`Yes` / `Yes`** | **`5/5` & `5/5`** |
| `BudgetCappedTinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `12,293` | `+0.1173` (`h=+0.0000`, `0/30` wrong) | `+0.2766` | `+0.3901` | `+0.5347` | `+0.6292` | **`Yes` / `Yes`** | **`5/5` & `5/5`** |
| `BudgetCappedGreedyHeuristicPolicy` (`baseline-budget-greedy-heuristic-v14`) | `0` | `-0.6643` (`h=-0.8760`, `28/30` wrong) | `-0.4416` | `-0.2270` | `+0.0834` | `+0.1958` | **`Yes` / `Yes`** | `0/5` (baseline) |

At severe horizon truncation (`max_days = 3`, before `hard`'s `2-3d` canary leak delay resolves multi-arm splits across `40` employees under `95%` fingerprint accuracy), all `4` calibrated compact policies achieve **`0/30` wrong accusations and `mean_score = +0.0000` (`100.0%` safe abstention) on `hard`**, cap overall wrong accusations at `0.011` (`0-1` / `90`), and climb **strictly monotonically** across `max_days = 3 -> 5 -> 7 -> 10 -> 21` to **`+0.6107..+0.6632`** (`20/20` positive world-paired `95%` CIs vs `BudgetCappedGreedyHeuristicPolicy` and `20/20` positive `95%` CIs vs `0.000` abstain). Conversely, `BudgetCappedGreedyHeuristicPolicy` commits catastrophic `-1.000` blind guesses at `max_days = 3` (`-0.6643` overall, `-0.8760` on `hard` with `28/30` wrong) and `max_days = 5` (`-0.4416` overall, `-0.8213` on `hard` with `27/30` wrong).

## 2. Full `25`-Cell Action-Budget & Horizon Curve (`n=90` Paired Held-Out Worlds per Cell)

| Policy | `max_days` | Raw Score (`95% CI`) | Public EV (`95% CI`) | Paired Delta vs `Heuristic` (`95% CI`) | Delta vs Full `21` | Canaries (`All` / `hard`) | Decision Day | Acc / Wrong / Abstain | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `BudgetCappedEmpiricalBayesPolicy` | `3` | `+0.0690 [+0.0196, +0.1184]` | `+0.0493 [+0.0085, +0.0902]` | `+0.7333 [+0.5844, +0.8822]` | `-0.5533` | `2.67` / `4.00` | `3.00` | `0.078` / `0.000` / `0.922` | `90/90` |
| `BudgetCappedEmpiricalBayesPolicy` | `5` | `+0.2476 [+0.1688, +0.3263]` | `+0.2388 [+0.1627, +0.3148]` | `+0.6891 [+0.5305, +0.8478]` | `-0.3748` | `5.13` / `7.93` | `4.81` | `0.300` / `0.000` / `0.700` | `90/90` |
| `BudgetCappedEmpiricalBayesPolicy` | `7` | `+0.4268 [+0.3410, +0.5126]` | `+0.3985 [+0.3204, +0.4767]` | `+0.6538 [+0.4769, +0.8306]` | `-0.1956` | `6.92` / `11.13` | `6.07` | `0.567` / `0.011` / `0.422` | `90/90` |
| `BudgetCappedEmpiricalBayesPolicy` | `10` | `+0.5557 [+0.4791, +0.6322]` | `+0.5550 [+0.4942, +0.6158]` | `+0.4722 [+0.3023, +0.6421]` | `-0.0667` | `8.62` / `14.27` | `7.24` | `0.811` / `0.022` / `0.167` | `90/90` |
| `BudgetCappedEmpiricalBayesPolicy` | `21` | `+0.6223 [+0.5726, +0.6721]` | `+0.6039 [+0.5555, +0.6523]` | `+0.4266 [+0.2804, +0.5727]` | `+0.0000` | `9.67` / `16.13` | `7.99` | `0.911` / `0.000` / `0.089` | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `3` | `+0.0671 [+0.0100, +0.1242]` | `+0.0435 [+0.0046, +0.0824]` | `+0.7314 [+0.5800, +0.8829]` | `-0.5436` | `2.67` / `4.00` | `3.00` | `0.089` / `0.011` / `0.900` | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `5` | `+0.2881 [+0.1914, +0.3848]` | `+0.2768 [+0.1947, +0.3589]` | `+0.7297 [+0.5678, +0.8916]` | `-0.3226` | `5.03` / `8.00` | `4.70` | `0.389` / `0.033` / `0.578` | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `7` | `+0.4133 [+0.3043, +0.5224]` | `+0.4092 [+0.3267, +0.4916]` | `+0.6403 [+0.4744, +0.8062]` | `-0.1973` | `6.87` / `11.80` | `5.90` | `0.611` / `0.067` / `0.322` | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `10` | `+0.5549 [+0.4610, +0.6488]` | `+0.5240 [+0.4521, +0.5958]` | `+0.4714 [+0.3045, +0.6383]` | `-0.0558` | `8.68` / `15.80` | `7.03` | `0.833` / `0.056` / `0.111` | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `21` | `+0.6107 [+0.5420, +0.6794]` | `+0.6120 [+0.5664, +0.6575]` | `+0.4149 [+0.2724, +0.5574]` | `+0.0000` | `10.21` / `19.33` | `7.98` | `0.922` / `0.022` / `0.056` | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `3` | `+0.0782 [+0.0262, +0.1303]` | `+0.0754 [+0.0253, +0.1256]` | `+0.7426 [+0.5919, +0.8932]` | `-0.5850` | `2.33` / `3.00` | `3.00` | `0.089` / `0.000` / `0.911` | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `5` | `+0.3522 [+0.2665, +0.4380]` | `+0.3404 [+0.2575, +0.4233]` | `+0.7938 [+0.6342, +0.9533]` | `-0.3110` | `4.62` / `7.00` | `4.62` | `0.422` / `0.000` / `0.578` | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `7` | `+0.4924 [+0.4103, +0.5746]` | `+0.4703 [+0.3902, +0.5504]` | `+0.7194 [+0.5523, +0.8866]` | `-0.1708` | `6.24` / `10.27` | `5.70` | `0.611` / `0.000` / `0.389` | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `10` | `+0.6002 [+0.5317, +0.6687]` | `+0.5786 [+0.5122, +0.6450]` | `+0.5168 [+0.3597, +0.6738]` | `-0.0630` | `7.88` / `13.87` | `6.73` | `0.778` / `0.000` / `0.222` | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `21` | `+0.6632 [+0.6071, +0.7194]` | `+0.6242 [+0.5675, +0.6809]` | `+0.4674 [+0.3247, +0.6102]` | `+0.0000` | `9.42` / `17.87` | `7.61` | `0.967` / `0.011` / `0.022` | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `3` | `+0.1173 [+0.0552, +0.1795]` | `+0.1138 [+0.0535, +0.1741]` | `+0.7817 [+0.6339, +0.9294]` | `-0.5119` | `2.67` / `4.00` | `3.00` | `0.133` / `0.000` / `0.867` | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `5` | `+0.2766 [+0.1895, +0.3636]` | `+0.2615 [+0.1815, +0.3415]` | `+0.7181 [+0.5486, +0.8876]` | `-0.3527` | `5.00` / `8.00` | `4.67` | `0.344` / `0.011` / `0.644` | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `7` | `+0.3901 [+0.3012, +0.4790]` | `+0.3642 [+0.2821, +0.4462]` | `+0.6171 [+0.4395, +0.7947]` | `-0.2391` | `6.76` / `11.20` | `5.89` | `0.500` / `0.011` / `0.489` | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `10` | `+0.5347 [+0.4568, +0.6125]` | `+0.5032 [+0.4314, +0.5750]` | `+0.4512 [+0.2862, +0.6162]` | `-0.0946` | `8.54` / `14.47` | `7.13` | `0.733` / `0.011` / `0.256` | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `21` | `+0.6292 [+0.5649, +0.6935]` | `+0.6078 [+0.5596, +0.6560]` | `+0.4334 [+0.2885, +0.5784]` | `+0.0000` | `9.32` / `15.60` | `7.72` | `0.944` / `0.022` / `0.033` | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `3` | `-0.6643 [-0.8143, -0.5143]` | `-0.7603 [-0.8042, -0.7163]` | `+0.0000 [+0.0000, +0.0000]` | `-0.8601` | `2.67` / `4.00` | `3.00` | `0.178` / `0.822` / `0.000` | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `5` | `-0.4416 [-0.6142, -0.2689]` | `-0.4669 [-0.5784, -0.3553]` | `+0.0000 [+0.0000, +0.0000]` | `-0.6373` | `5.29` / `8.00` | `4.96` | `0.311` / `0.689` / `0.000` | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `7` | `-0.2270 [-0.4067, -0.0473]` | `-0.2689 [-0.4038, -0.1341]` | `+0.0000 [+0.0000, +0.0000]` | `-0.4228` | `7.63` / `11.93` | `6.66` | `0.444` / `0.556` / `0.000` | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `10` | `+0.0834 [-0.0806, +0.2475]` | `+0.0171 [-0.1122, +0.1465]` | `+0.0000 [+0.0000, +0.0000]` | `-0.1123` | `10.53` / `17.43` | `8.70` | `0.656` / `0.344` / `0.000` | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `21` | `+0.1958 [+0.0507, +0.3409]` | `+0.2500 [+0.1468, +0.3533]` | `+0.0000 [+0.0000, +0.0000]` | `+0.0000` | `13.56` / `25.07` | `11.02` | `0.756` / `0.244` / `0.000` | `90/90` |

## 3. Hard-Tier (`n=30`, `40` Staff, `2-3d` Delay, `95%` FP) Canary-Budget Progression

| Policy | `max_days=3` (`canaries`, `w`, `a`) | `max_days=5` (`canaries`, `w`, `a`) | `max_days=7` (`canaries`, `w`, `a`) | `max_days=10` (`canaries`, `w`, `a`) | `max_days=21` (`canaries`, `w`, `a`) | Full Parity |
|---|---|---|---|---|---|---:|
| `BudgetCappedEmpiricalBayesPolicy` | `+0.0000` (`c=4.0`, `w=0`, `a=30`) | `+0.0760` (`c=7.9`, `w=0`, `a=27`) | `+0.2983` (`c=11.1`, `w=0`, `a=17`) | `+0.4617` (`c=14.3`, `w=1`, `a=5`) | `+0.5687` (`c=16.1`, `w=0`, `a=0`) | `90/90` |
| `BudgetCappedScalingLogisticPolicy` | `+0.0000` (`c=4.0`, `w=0`, `a=30`) | `+0.0470` (`c=8.0`, `w=1`, `a=26`) | `+0.1093` (`c=11.8`, `w=3`, `a=18`) | `+0.3527` (`c=15.8`, `w=3`, `a=5`) | `+0.4620` (`c=19.3`, `w=1`, `a=1`) | `90/90` |
| `BudgetCappedCompactLinearPolicy` | `+0.0000` (`c=3.0`, `w=0`, `a=30`) | `+0.1040` (`c=7.0`, `w=0`, `a=26`) | `+0.2457` (`c=10.3`, `w=0`, `a=20`) | `+0.3723` (`c=13.9`, `w=0`, `a=14`) | `+0.4903` (`c=17.9`, `w=1`, `a=0`) | `90/90` |
| `BudgetCappedTinyMLPPolicy` | `+0.0000` (`c=4.0`, `w=0`, `a=30`) | `+0.0677` (`c=8.0`, `w=1`, `a=25`) | `+0.2117` (`c=11.2`, `w=1`, `a=19`) | `+0.3847` (`c=14.5`, `w=1`, `a=10`) | `+0.4930` (`c=15.6`, `w=2`, `a=0`) | `90/90` |
| `BudgetCappedGreedyHeuristicPolicy` | `-0.8760` (`c=4.0`, `w=28`, `a=0`) | `-0.8213` (`c=8.0`, `w=27`, `a=0`) | `-0.7720` (`c=11.9`, `w=26`, `a=0`) | `-0.3793` (`c=17.4`, `w=18`, `a=0`) | `-0.1320` (`c=25.1`, `w=11`, `a=0`) | `90/90` |

## 4. Track-Separated Context: Explaining `WS4-base-pooled` Day-1 Loop & `gemini-4-carbon` Canary Deficit

| Track / Cohort (Strictly Separated) | Seed Split | `n` | Effective Horizon / Cap | Mean Canaries | Mean Score | Failure / Calibration Mechanism |
|---|---|---:|---|---:|---:|---|
| Track 1 Open-Weight LLM: `WS4-base-pooled` (`Qwen2.5-1.5B` base) | `HELDOUT 800000..800012` | `36` | Day `1.0` (`eval_cap=120`, `100%`) | `0.00` | `+0.0000` | `2.87%` valid tool syntax -> trapped on Day 1 with `0` canaries -> passive `0.000` cap stall |
| Track 1 Open-Weight LLM: `Qwen2.5-1.5B` LoRA `v2-off30` / `v3-8k-s1` | `HELDOUT` | `90 / 90` | Early commit (`~2.1-2.3` canaries) | `2.11` / `2.31` | `-0.5142` / `-0.7767` | Operates in `max_days=3..5` low-canary regime (`90-98%` below breakeven) without `1/(1+V)` EV gate |
| Track 1 Open-Weight LLM: `Qwen2.5-1.5B` LoRA `v3-4k` pooled | `HELDOUT 800000..800059` | `180` | `4k` header eviction (`2842/4096`) | `3.53` | `-0.1474` | Plants `3.53` canaries (`max_days ~ 4`), `97-100%` evicted on `medium`/`hard` -> `142/180` abstains + `92.1%` sub-BE commits |
| Frontier LLM (MCP): `gemini-4-carbon` (`hard`, post-hoc locked) | `DEV 0..29` | `30` | Accuse Day `13.17` (`31.5%` slot util) | `8.47` (`~8.5`) | `+0.3223` (`EV +0.3596`) | Spends `68.0` calls on low-KL interviews, planting `8.47` (`8.57` in-proc) canaries -> matches `max_days=5..7` (`7.0-11.8` hard canaries) |
| Frontier LLM (MCP) / Reference: `gpt-5.5` / reference solver (`hard`, post-hoc locked) | `DEV 0..29` | `30 / 30` | Accuse Day `10.25` / `10.60` | `17.13` / `14.13` (`~14.1`) | `+0.5037` / `+0.4990` | `66.7-84.5%` canary slot utilization + `0%` sub-breakeven commits -> matches `max_days=21` (`15.6-19.3` hard canaries) |

1. **Why `WS4-base-pooled` scores `0.000` under `eval_cap = 120` on Day `1`**: With `2.87%` valid tool calls (`97.13%` malformed tool syntax), untrained `Qwen2.5-1.5B` never advances past Day `1` (`0.00` canaries planted, `36/36` `eval_cap` terminations). In Canary's asymmetric payoff (`0.000` passive default vs `-1.000` wrong accusation), a Day-`1` syntax stall accidentally matches optimal `max_days=1` abstention on `hard`, explaining why uncalibrated fine-tunes (`v2` `2.11` canaries, `v3-8k-s1` `2.31` canaries) drop into `-0.514..-0.777` just like `BudgetCappedGreedyHeuristicPolicy` at `max_days=3` (`-0.6643`).
2. **Why `gemini-4-carbon`'s `8.47` (`~8.5`) vs `14.13` (`~14.1`) reference canaries costs `~0.18` on `hard`**: On `hard` (`40` staff, `2` canaries/day x `3` variants, `2-3d` leak delay), `8.5` planted canaries corresponds to stopping active canary design around `max_days = 5..7` (`7.0 - 11.8` `hard` canaries in Section 3), where `hard` compact-policy score at `max_days = 7..10` sits at `+0.1093..+0.4617` because delayed `3`-way splits have not yet isolated `1` of `40` employees with margin against `5%` fingerprint noise. Extending canary planting to `15.6 - 19.3` `hard` canaries (`max_days = 21`) raises `hard` score to `+0.4620..+0.5687`.

### Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_action_budget_horizon_audit.py --check
python -m pytest -q tests/test_tiebreak_action_budget_horizon.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
