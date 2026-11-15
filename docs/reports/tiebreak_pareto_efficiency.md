# Tiebreak Cross-Architecture Parameter, Token & Investigative Tool-Budget Pareto Audit (`v1.4`)

Keyless CPU-only cross-architecture efficiency synthesis and live investigative tool-budget Pareto audit across `1,440` world-paired held-out episodes (`2` compact non-LLM policies x `8` investigative call caps `B in [4, 8, 16, 24, 36, 48, 96, 420]` x `n=90` on `HELDOUT_SEEDS 800000..800029`, `30`/tier across `easy`, `medium`, `hard` under `sha256:ebf2f09716cf76d3`, `1440/1440` fresh `Env` replays verified). `EmpiricalBayesPolicy` (`11` params, `0` context tokens) reaches **`+0.3114`** at `B=24` (`21.00` investigative calls/ep), **`+0.4743`** at `B=36`, and **`+0.6223`** unmodified (`B=420`, `33.78` calls/ep), while `CompactLinearDAggerPolicy` (`785` params, `0` context tokens) reaches **`+0.3921`** at `B=24`, **`+0.5643`** at `B=36`, and **`+0.6632`** unmodified (`B=420`, `28.34` calls/ep), with **`15/16`** configurations forming the exact `(params, investigative_calls, -mean_score)` Pareto frontier.

- **Seed & Secret Provenance (Panel Fix A)**: All `1,440` live budget-curve episodes run strictly on world-paired `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`, all learned compact policy parameters originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` (`102000..102779`, `107000..108999`, `109000..109509`, `107000..107599`), and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Separate frontier behavioral efficiency rows on `DEV_SEEDS 0..29` (`hard`, `n=30`) are ingested from committed replay-verified runs and are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Non-LLM compact policies (`is_open_weight_llm = False`) are strictly separated from Track 1 open-weight `Qwen2.5` LoRA runs and are never conflated.

## 1. Cross-Architecture Parameter, Token & Score Tables (Strict Track Separation)

### 1.1 Track 2 & Non-LLM Compact Policies on World-Paired `HELDOUT_SEEDS` (`sha256:ebf2f09716cf76d3`)

| Policy (`run_id`) | Params | Context Tokens | `HELDOUT` Primary Score (`95% CI`, `n`) | Matched `n=90` (`800000..800029`) | Canaries / Ep | Replay Verified | `(params, -score)` Pareto |
|---|---:|---:|---:|---:|---:|---:|---:|
| `do_nothing (abstain baseline)` | `0` | `0` | `+0.000` (`[+0.000, +0.000]`, `n=180`) | `+0.0000` | `0.00` | `100%` | **YES** |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `11` | `0` | `+0.607` (`[+0.559, +0.648]`, `n=180`) | `+0.6223` | `9.71` | `100%` | **YES** |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `82` | `0` | `+0.611` (`[+0.542, +0.679]`, `n=90`) | `+0.6107` | n/a | `100%` | **YES** |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `785` | `0` | `+0.627` (`[+0.575, +0.672]`, `n=180`) | `+0.6632` | `9.05` | `100%` | **YES** |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `12,293` | `0` | `+0.614` (`[+0.565, +0.663]`, `n=180`) | n/a | `9.31` | `100%` | no (dominated) |

### 1.2 Track 1 Open-Weight `Qwen2.5-1.5B` LLM Runs (`0 / 19` Above `0.000`, `README` Addendum Held)

| Run ID | Architecture / Scale | Context Tokens | `HELDOUT` `n` | Mean Score (`+/- 95% CI`) | Valid Call Rate | Ledger Status | Dominated by `do_nothing` (`0`p, `+0.000`) |
|---|---|---:|---:|---:|---:|---|---:|
| `WS4-base-pooled` | `~1.54B total (0 trainable)` | `4,096` | `36` | `+0.000` | `3%` | `BASELINE_CAVEATED` | `YES` |
| `WS4-v2` | `~1.54B total (~18.5M LoRA r=16)` | `4,096` | `172` | `-0.457 +/- 0.086` | `92%` | `NEGATIVE_BLIND_ACCUSE` | `YES` |
| `WS4-v3-verda-s0-eval` | `~1.54B total (~18.5M LoRA r=16)` | `4,096` | `180` | `-0.147 +/- 0.063` | `100%` | `NEGATIVE_4K_TRUNCATION_PERSISTS` | `YES` |
| `WS4-v3-8k-s2-dbd0` | `~1.54B total (~18.5M LoRA r=16)` | `8,192` | `90` | `-0.050 +/- 0.049` | `96%` | `NEGATIVE_ABSTAIN_COLLAPSE` | `YES` |
| `WS4-dagger-r1-8k-verda` | `~1.54B total (~18.5M LoRA r=16)` | `8,192` | `50` | `-0.542 +/- 0.214` | `100%` | `NEGATIVE_DAGGER_HONEST_NULL` | `YES` |
| `WS4-dagger-r1-4k-verda` | `~1.54B total (~18.5M LoRA r=16)` | `4,096` | `41` | `-0.101 +/- 0.112` | `100%` | `NEGATIVE_DAGGER_HONEST_NULL` | `YES` |

### 1.3 Separate Post-Hoc Locked `DEV_SEEDS 0..29` (`hard`, `n=30`) Frontier Behavioral Efficiency Panel

*Protocol note (Panel Fix A)*: `DEV_SEEDS 0..29` rows below are **post-hoc locked, not pre-registered**, evaluated on `hard` (`n=30`), and strictly separated from `HELDOUT_SEEDS 800000..800029` above.

| Cohort / Agent (`DEV_SEEDS 0..29`, `hard`, `n=30`) | Mean Score (`+/- 95% CI`) | Luck-Adjusted EV | Interviews / Ep | Canaries / Ep | Slot Utilization | Correct / Wrong / Abstain |
|---|---:|---:|---:|---:|---:|---:|
| `gemini-4-carbon (OpenCode over MCP, judges' harness)` | `+0.322 +/- 0.199` | `+0.360` | `68.0` | `8.47` | `31.5%` | `25/4/1` |
| `gpt-5.5 (OpenCode over MCP)` | `+0.504 +/- 0.064` | `+0.418` | `4.1` | `17.13` | `84.5%` | `28/0/2` |
| `gemini-3.5-flash (OpenCode over MCP)` | `+0.373 +/- 0.177` | `+0.110` | `0.7` | `12.43` | `48.9%` | `27/3/0` |
| `SolverPolicy (Bayesian canary-trap reference)` | `+0.499 +/- 0.119` | `+0.499` | `0.0` | `14.13` | `66.7%` | `29/1/0` |

## 2. Live Investigative Tool-Budget Pareto Curve (`HELDOUT_SEEDS 800000..800029`, `n=90` / Cap)

Each row wraps `EmpiricalBayesPolicy` (`11` params) or `CompactLinearDAggerPolicy` (`785` params) in `BudgetCappedPolicy` (`0` `canary.solver`/`canary.world` imports). Once investigative MCP calls reach `B`, only calibrated `accuse` or `advance_day` to horizon is allowed. Pareto optimality (`is_pareto_optimal`) is evaluated exactly over `(param_count, mean_investigative_calls, -mean_score)`.

| Policy | Params | Cap `B` | Score (`95% CI`) | Inv Calls / Ep | Canaries / Ep | Accuse Rate | Wrong Rate | Score / Inv Call | Pareto Optimal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `11` | `4` | `+0.0000 [+0.0000, +0.0000]` | `4.00` | `1.33` | `0.0%` | `0.0%` | `+0.0000` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `8` | `+0.0690 [+0.0196, +0.1184]` | `8.00` | `1.67` | `7.8%` | `0.0%` | `+0.0086` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `16` | `+0.1849 [+0.1129, +0.2569]` | `15.18` | `3.62` | `22.2%` | `0.0%` | `+0.0122` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `24` | `+0.3114 [+0.2244, +0.3985]` | `21.00` | `5.68` | `41.1%` | `1.1%` | `+0.0148` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `36` | `+0.4743 [+0.3920, +0.5567]` | `27.30` | `7.67` | `65.6%` | `1.1%` | `+0.0174` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `48` | `+0.5764 [+0.5134, +0.6395]` | `31.07` | `8.89` | `80.0%` | `0.0%` | `+0.0186` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `96` | `+0.6210 [+0.5706, +0.6714]` | `33.70` | `9.66` | `90.0%` | `0.0%` | `+0.0184` | **YES** |
| `EmpiricalBayesPolicy` | `11` | `420` | `+0.6223 [+0.5726, +0.6721]` | `33.78` | `9.67` | `91.1%` | `0.0%` | `+0.0184` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `4` | `+0.0000 [+0.0000, +0.0000]` | `4.00` | `1.33` | `0.0%` | `0.0%` | `+0.0000` | no |
| `CompactLinearDAggerPolicy` | `785` | `8` | `+0.0782 [+0.0262, +0.1303]` | `7.82` | `1.91` | `8.9%` | `0.0%` | `+0.0100` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `16` | `+0.2783 [+0.1964, +0.3603]` | `13.84` | `3.02` | `33.3%` | `0.0%` | `+0.0201` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `24` | `+0.3921 [+0.3065, +0.4777]` | `18.77` | `5.10` | `47.8%` | `0.0%` | `+0.0209` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `36` | `+0.5643 [+0.4902, +0.6384]` | `23.66` | `7.22` | `72.2%` | `0.0%` | `+0.0239` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `48` | `+0.6400 [+0.5813, +0.6987]` | `26.32` | `8.43` | `85.6%` | `0.0%` | `+0.0243` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `96` | `+0.6632 [+0.6071, +0.7194]` | `28.34` | `9.42` | `97.8%` | `1.1%` | `+0.0234` | **YES** |
| `CompactLinearDAggerPolicy` | `785` | `420` | `+0.6632 [+0.6071, +0.7194]` | `28.34` | `9.42` | `97.8%` | `1.1%` | `+0.0234` | **YES** |

## 3. Per-Tier Score & Efficiency Breakdown Across Budget Caps (`easy` / `medium` / `hard`, `n=30` / Cell)

| Policy | Cap `B` | `easy` (`n=30`) | `medium` (`n=30`) | `hard` (`n=30`) | Pooled (`n=90`) | Retained vs `B=420` |
|---|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `4` | `+0.0000` (`4.0`c) | `+0.0000` (`4.0`c) | `+0.0000` (`4.0`c) | `+0.0000` (`4.00`c) | `0.0%` |
| `EmpiricalBayesPolicy` | `8` | `+0.2070` (`8.0`c) | `+0.0000` (`8.0`c) | `+0.0000` (`8.0`c) | `+0.0690` (`8.00`c) | `11.1%` |
| `EmpiricalBayesPolicy` | `16` | `+0.5263` (`13.5`c) | `+0.0283` (`16.0`c) | `+0.0000` (`16.0`c) | `+0.1849` (`15.18`c) | `29.7%` |
| `EmpiricalBayesPolicy` | `24` | `+0.6403` (`15.8`c) | `+0.2180` (`23.4`c) | `+0.0760` (`23.9`c) | `+0.3114` (`21.00`c) | `50.0%` |
| `EmpiricalBayesPolicy` | `36` | `+0.7287` (`17.5`c) | `+0.3967` (`30.9`c) | `+0.2977` (`33.5`c) | `+0.4743` (`27.30`c) | `76.2%` |
| `EmpiricalBayesPolicy` | `48` | `+0.7287` (`18.3`c) | `+0.5527` (`35.0`c) | `+0.4480` (`39.9`c) | `+0.5764` (`31.07`c) | `92.6%` |
| `EmpiricalBayesPolicy` | `96` | `+0.7287` (`18.6`c) | `+0.5697` (`37.3`c) | `+0.5647` (`45.2`c) | `+0.6210` (`33.70`c) | `99.8%` |
| `EmpiricalBayesPolicy` | `420` | `+0.7287` (`18.6`c) | `+0.5697` (`37.3`c) | `+0.5687` (`45.4`c) | `+0.6223` (`33.78`c) | `100.0%` |
| `CompactLinearDAggerPolicy` | `4` | `+0.0000` (`4.0`c) | `+0.0000` (`4.0`c) | `+0.0000` (`4.0`c) | `+0.0000` (`4.00`c) | `0.0%` |
| `CompactLinearDAggerPolicy` | `8` | `+0.2347` (`7.5`c) | `+0.0000` (`8.0`c) | `+0.0000` (`8.0`c) | `+0.0782` (`7.82`c) | `11.8%` |
| `CompactLinearDAggerPolicy` | `16` | `+0.7783` (`9.6`c) | `+0.0567` (`16.0`c) | `+0.0000` (`16.0`c) | `+0.2783` (`13.84`c) | `42.0%` |
| `CompactLinearDAggerPolicy` | `24` | `+0.8203` (`9.9`c) | `+0.2243` (`22.4`c) | `+0.1317` (`24.0`c) | `+0.3921` (`18.77`c) | `59.1%` |
| `CompactLinearDAggerPolicy` | `36` | `+0.8203` (`9.9`c) | `+0.5673` (`27.9`c) | `+0.3053` (`33.1`c) | `+0.5643` (`23.66`c) | `85.1%` |
| `CompactLinearDAggerPolicy` | `48` | `+0.8203` (`9.9`c) | `+0.6790` (`29.9`c) | `+0.4207` (`39.2`c) | `+0.6400` (`26.32`c) | `96.5%` |
| `CompactLinearDAggerPolicy` | `96` | `+0.8203` (`9.9`c) | `+0.6790` (`29.9`c) | `+0.4903` (`45.2`c) | `+0.6632` (`28.34`c) | `100.0%` |
| `CompactLinearDAggerPolicy` | `420` | `+0.8203` (`9.9`c) | `+0.6790` (`29.9`c) | `+0.4903` (`45.2`c) | `+0.6632` (`28.34`c) | `100.0%` |

## 4. Key Efficiency Takeaways

1. **Calibrated Low-Budget Abstention (`B=4` to `B=16`)**: At `B=4`, before delayed canary leaks can surface and isolate a suspect above the `1/(1+V)` breakeven bar, `BudgetCappedPolicy` abstains cleanly (`0.0%` wrong accusations on both policies) rather than gambling blindly like `WS4-v2` (`-0.457`) or `WS4-dagger-r1-8k` (`-0.542`).
2. **Steep Canary-Driven Marginal Return (`B=16` to `B=48`)**: Expanding investigative calls from `B=8` to `B=36` lifts `EmpiricalBayesPolicy` to `+0.4743` (`27.30` mean investigative calls/ep, `76.2%` of unmodified score) and `CompactLinearDAggerPolicy` to `+0.5643` (`23.66` mean investigative calls/ep, `85.1%` of unmodified score).
3. **Frontier Tool-Allocation Contrast (`DEV_SEEDS 0..29`, post-hoc locked, not pre-registered)**: `gpt-5.5` achieves `+0.504` on `hard` with `17.13` canaries/ep and only `4.1` interviews/ep, whereas `gemini-4-carbon` spends `68.0` interviews/ep with `8.47` canaries/ep for `+0.322` (`gemini-3.5-flash` `+0.373`, `SolverPolicy` `+0.499`). The tool-budget Pareto curve shows that once investigative calls are directed into high-KL 3-arm canary splits plus calibrated stopping, `<= 785` parameters saturate episode value in `< 30` mean investigative calls.

## 5. Offline Reproducibility Commands

```bash
python scripts/tiebreak_pareto_efficiency.py --check
python -m pytest -q tests/test_tiebreak_pareto_efficiency.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
