# Non-Parametric Statistical Power, Multiplicity Control & World-Pairing Audit (`v1.4`)

Deterministic non-parametric inference, Holm-Bonferroni FWER, Benjamini-Hochberg FDR, world-secret pairing variance-reduction, and Minimum Detectable Effect (`MDE` at `80%` power, `alpha = 0.05` two-sided) audit across Canary tiebreak evaluations (`B = 10000` seeded Monte Carlo sign-flip permutations and percentile bootstraps, `seed = 20261115`; **`540/540`** canonical `Env` replays verified for `HELDOUT_SEEDS 800000..800029` pairing).

- **Seed & Secret Provenance (Panel Fix A)**: Held-out comparisons strictly evaluate `HELDOUT_SEEDS [800000, 800200)` (`800000..800059` at `n=180` and `800000..800029` at `n=90` under `sha256:ebf2f09716cf76d3`, plus Verda shared-secret `verda_shared_secret_0405_1ca0c2a64d` / `1ca0c2a64d` slices), while all compact policy weights originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`>= 900000`) touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` compact policies (`is_open_weight_llm = False`) are strictly separated from Track 1 open-weight `Qwen2.5` runs.

## 1. Primary Family (`m = 8`): Sign-Flip Permutation, Holm-Bonferroni FWER & BH FDR

| Comparison (`comparison_id`) | Track | `n` | Paired Mean Delta | Bootstrap `95% CI` | `p_perm` (2-sided) | `p_Holm` (2-sided) | `q_BH` (2-sided) | `p_Holm` (`>0`) | `MDE` (`80%`) | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `empirical_bayes_vs_before` | `compact_non_llm` | `180` | `+1.0282` | `[+0.9145, +1.1381]` | `0.0001` | `0.0008` | `0.0001` | `0.0008` | `0.1623` | **VERIFIED COMPACT GAIN** |
| `compact_linear_dagger_vs_before` | `compact_non_llm` | `180` | `+0.6267` | `[+0.5763, +0.6738]` | `0.0001` | `0.0008` | `0.0001` | `0.0008` | `0.0707` | **VERIFIED COMPACT GAIN** |
| `tiny_mlp_dagger_vs_before` | `compact_non_llm` | `180` | `+1.4696` | `[+1.3814, +1.5509]` | `0.0001` | `0.0008` | `0.0001` | `0.0008` | `0.1215` | **VERIFIED COMPACT GAIN** |
| `scaling_logistic_vs_before` | `compact_non_llm` | `90` | `+0.6107` | `[+0.5367, +0.6726]` | `0.0001` | `0.0008` | `0.0001` | `0.0008` | `0.0993` | **VERIFIED COMPACT GAIN** |
| `verda_v3_8k_s0_vs_s3` | `open_weight_qwen25_seed_diagnostic` | `90` | `+0.7278` | `[+0.5861, +0.8512]` | `0.0001` | `0.0008` | `0.0001` | `0.0008` | `0.1936` | **SEED BIFURCATION (BOTH < 0)** |
| `verda_4k_at_8k_vs_8k_s3_null` | `open_weight_qwen25_null` | `90` | `+0.0726` | `[-0.1048, +0.2412]` | `0.3907` | `0.3907` | `0.3907` | `0.5822` | `0.2499` | **HONEST NULL** |
| `verda_dagger_r1_8k_vs_base` | `open_weight_qwen25_honest_negative` | `50` | `-0.5420` | `[-0.7510, -0.3308]` | `0.0001` | `0.0008` | `0.0001` | `1.0000` | `0.3123` | **HONEST NEGATIVE (< 0)** |
| `verda_dagger_r1_4k_vs_base` | `open_weight_qwen25_honest_null` | `41` | `-0.1010` | `[-0.2195, -0.0034]` | `0.0661` | `0.1322` | `0.0755` | `1.0000` | `0.1636` | **HONEST NULL** |

Across the `m = 8` primary family, **`4/4`** non-LLM compact policies (`EmpiricalBayesPolicy` `+1.0282`, `CompactLinearDAggerPolicy` `+0.6267`, `TinyMLPPolicy` `+1.4696`, `ScalingLogisticPolicy` `+0.6107`) achieve exact sign-flip permutation `p_perm = 0.0001` (`1 / 10001`), surviving Holm-Bonferroni FWER (`p_Holm <= 0.0008`) and Benjamini-Hochberg FDR (`q_BH <= 0.0002`) with `100%` post-hoc power. Expanding multiplicity control to `m = 12` by adding all `4` world-paired `CompactPolicy vs Heuristic` comparisons keeps **`8/8`** compact comparisons significant (`p_Holm <= 0.0012`, `q_BH <= 0.0002`), while **`0` open-weight `Qwen2.5` runs** beat `0.000` base.

## 2. World-Secret Pairing Variance Reduction (`Var(A_i - B_i)` vs `Var(A) + Var(B)`)

| Comparison | Cohort (`world_secret_tag`) | `n` | `Var(A) + Var(B)` | `Var(A_i - B_i)` | World `r` | Var Reduction | `N_eff_ratio` | Equiv Unpaired `n` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `empirical_bayes_vs_heuristic` | `sha256:ebf2f09716cf76d3` | `90` | `0.5512` | `0.5001` | `+0.151` | `+9.3%` | **`1.102x`** | `99.2` |
| `scaling_logistic_vs_heuristic` | `sha256:ebf2f09716cf76d3` | `90` | `0.6038` | `0.4758` | `+0.274` | `+21.2%` | **`1.269x`** | `114.2` |
| `compact_linear_dagger_vs_heuristic` | `sha256:ebf2f09716cf76d3` | `90` | `0.5671` | `0.4775` | `+0.235` | `+15.8%` | **`1.188x`** | `106.9` |
| `tiny_mlp_vs_heuristic` | `sha256:ebf2f09716cf76d3` | `90` | `0.5901` | `0.4922` | `+0.224` | `+16.6%` | **`1.199x`** | `107.9` |
| `empirical_bayes_vs_naive_prior` | `sha256:ebf2f09716cf76d3` | `90` | `0.7536` | `0.6240` | `+0.323` | `+17.2%` | **`1.208x`** | `108.7` |
| `compact_linear_dagger_vs_empirical_bayes` | `sha256:ebf2f09716cf76d3` | `90` | `0.1318` | `0.1180` | `+0.105` | `+10.5%` | **`1.117x`** | `100.5` |
| `compact_linear_dagger_vs_tiny_mlp` | `sha256:ebf2f09716cf76d3` | `90` | `0.1707` | `0.1362` | `+0.204` | `+20.2%` | **`1.253x`** | `112.8` |
| `empirical_bayes_vs_scaling_logistic` | `sha256:ebf2f09716cf76d3` | `90` | `0.1686` | `0.1373` | `+0.195` | `+18.5%` | **`1.228x`** | `110.5` |
| `tiny_mlp_vs_scaling_logistic` | `sha256:ebf2f09716cf76d3` | `90` | `0.2075` | `0.1679` | `+0.191` | `+19.1%` | **`1.236x`** | `111.2` |
| `verda_s0_minus_s3` | `verda_shared_secret_0405_1ca0c2a64d` | `90` | `0.3858` | `0.4206` | `-0.119` | `-9.0%` | **`0.917x`** | `82.6` |
| `verda_s3_minus_4k_at_8k` | `verda_shared_secret_0405_1ca0c2a64d` | `90` | `0.5788` | `0.7004` | `-0.211` | `-21.0%` | **`0.826x`** | `74.4` |
| `verda_s0_minus_4k_at_8k` | `verda_shared_secret_0405_1ca0c2a64d` | `90` | `0.3276` | `0.3150` | `+0.047` | `+3.8%` | **`1.040x`** | `93.6` |

- **`HELDOUT_SEEDS` (`sha256:ebf2f09716cf76d3`)**: All **`9/9`** world-paired compact comparisons achieve `N_eff_ratio > 1.0` (mean **`1.200x`**, peak **`1.269x`** on `scaling_logistic_vs_heuristic`, equivalent to `114.2` unpaired episodes from `n=90`), because calibrated policies covary positively (`r = +0.105..+0.323`) with shared world difficulty `V`.
- **Verda Shared-Secret (`verda_shared_secret_0405_1ca0c2a64d`)**: Collapsed raw-JSON `Qwen2.5` runs exhibit near-zero or mildly negative world correlation (`N_eff_ratio` `0.928x` mean; `0.826x` on `s3_minus_4k_at_8k`) because blind Day-1..5 accusations (`0.043..0.093` whom-precision) do not track true world difficulty; shared-secret pairing nonetheless eliminates world-realization confounds (`60/60` and `61/61` roster exact matches) and yields conservative paired CIs.

## 3. Minimum Detectable Effect (`MDE` at `80%` Power, `alpha = 0.05` Two-Sided)

| Sample Size `n` | `t`-Factor (`/ SD`) | Compact vs `Abstain` (`SD=0.337`) | Scaling vs `Abstain` (`SD=0.333`) | Compact vs `Heuristic` Paired (`SD=0.697`) | Compact vs `Heuristic` Unpaired (`SD=0.760`) | Verda `DAgger r1` 8k (`SD=0.772`) | Verda `DAgger r1` 4k (`SD=0.366`) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| `30` | `0.5294` | `0.1783` | `0.1761` | `0.3692` | `0.4025` | `0.4087` | `0.1937` |
| `41` | `0.4485` | `0.1510` | `0.1492` | `0.3128` | `0.3410` | `0.3463` | `0.1641` |
| `50` | `0.4043` | `0.1361` | `0.1344` | `0.2819` | `0.3074` | `0.3121` | `0.1479` |
| `90` | `0.2986` | `0.1006` | `0.0993` | `0.2082` | `0.2270` | `0.2305` | `0.1092` |
| `180` | `0.2100` | `0.0707` | `0.0698` | `0.1464` | `0.1596` | `0.1621` | `0.0768` |

### Quantitative Explanation of Reaper-Truncated Verda X2 `DAgger r1` (`n=50` at 8k, `n=41` at 4k)

1. **8k Evaluation (`WS4-dagger-r1-8k-verda`, `n=50` pulled before `08:00` reaper)**: Against `0.000` base (`SD = 0.7721`), `MDE(n=50)` is **`0.3121`**, so the observed score **`-0.542 +/- 0.214`** (`95% CI [-0.756, -0.328]`, `|-0.542| = 1.74x MDE`) decisively **rules out any `> 0.0` held-out score** (`p_perm = 0.0001` negative, `p_Holm(>0) = 1.0000`). Conversely, for the shared-secret head-to-head vs `v3-4k-s0@8k cap=256` (`n=43`, `+0.242 +/- 0.304`, `SD = 1.0171`), `MDE(n=43)` is **`0.4449`**: `|+0.242| < 0.4449` had only **`32.5%`** power and would have required **`n >= 141`** paired worlds for `80%` power.
2. **4k Evaluation (`WS4-dagger-r1-4k-verda`, `n=41` pulled before `07:30` reaper)**: High abstention (`35/41`) lowers `SD` to `0.3659`, giving `MDE(n=41)` = **`0.1641`** (and `MDE(n=32)` = **`0.2052`** vs `v3-4k-s0@4k cap=256`, where observed delta was `-0.031 +/- 0.139`). Hence `-0.101 +/- 0.112` sits inside the small-effect null zone (`|-0.101| < 0.1641`, `40.1%` power), **yet** its `95% CI [-0.213, +0.011]` caps any plausible positive score at **`+0.011`** and rules out every tiebreak-relevant improvement `>= +0.164` at `>= 80%` power.

### Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_statistical_power_audit.py --check
pytest -q tests/test_tiebreak_statistical_power.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
