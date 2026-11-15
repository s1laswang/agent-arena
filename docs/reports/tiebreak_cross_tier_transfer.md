# Zero-Shot Cross-Tier Transfer and OOD Pool/Horizon Generalization Audit (Canary `v1.4`)

- Schema: `canary.tiebreak.cross_tier_transfer.v1` (`tiebreak-cross-tier-transfer-and-ood-horizon-v14`)
- Evaluation Slice: `HELDOUT_SEEDS 800000..800029` (`n=30` per tier, `90` episodes per trained policy; shared `world_secret_tag` `sha256:ebf2f09716cf76d3`; `1140/1140` `100%` `Env` replay-verified; `0` API calls; `0` `canary.solver`/`canary.world` imports)
- Training Provenance: strictly disjoint `TRAIN_SEEDS` in `[100000, 200000)` (`112000..113079` for `EmpiricalBayesPolicy`, `107000..108469` for `ScalingLogisticPolicy`, `270` episodes per train regime; `0` `DEV_SEEDS` rolled out; `0` `JUDGE_SEEDS (900k+)` touched)
- Panel Fix A Disclosure: All cross-tier transfer models audited here are fit strictly on disjoint single-tier or pooled TRAIN_SEEDS in [100000, 200000) (107000..108469 and 112000..113079) and evaluated strictly on world-paired HELDOUT_SEEDS 800000..800029 (n=30 per tier, 90 episodes per trained policy) under deterministic world_secret_tag sha256:ebf2f09716cf76d3; 0 DEV_SEEDS are rolled out and 0 JUDGE_SEEDS (900k+) are touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A).
- Panel Fix E Disclosure: `0 / 19` open-weight Qwen2.5-1.5B runs beat untrained `0.000` (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`); both compact policy families audited here (`EmpiricalBayesPolicy`, `11` params; `ScalingLogisticPolicy`, `82` params) have `is_open_weight_llm = False` and are strictly separated from open-weight LLM runs.

## 1. Canary `v1.4` Tier Shift Geometry (`easy` vs `medium` vs `hard`)

| Tier | Staff Pool `N` | Horizon `H` | Leak Delay `d` | Canaries / Day (`K` Variants) | Fingerprint Noise (`1 - fp_acc`) | Decoy / Framing / Careful Mole | Access Constraints |
| :--- | ---: | ---: | :--- | :--- | ---: | :--- | :--- |
| `easy` | `12` | `14d` | `1d` | `1` (`K=3`) | `0.0% (fp=1.00)` | `False / False / False` | `False` |
| `medium` | `20` | `14d` | `1,2,3d` | `1` (`K=3`) | `0.0% (fp=1.00)` | `True / True / True` | `False` |
| `hard` | `40` | `21d` | `2,3d` | `2` (`K=3`) | `5.0% (fp=0.95)` | `True / True / True` | `True` |

## 2. Full `4 x 3` Cross-Tier Transfer Matrix on World-Paired `HELDOUT_SEEDS 800000..800029`

### 2A. `EmpiricalBayesPolicy` (`11` Parameters, `is_open_weight_llm = False`)

| Train Regime (`TRAIN_SEEDS`) | Eval `easy` (`N=12, H=14d, 0% noise`) | Eval `medium` (`N=20, H=14d, 0% noise`) | Eval `hard` (`N=40, H=21d, 5% noise`) | Pooled `3`-Tier Mean (`n=90`) | Paired Delta vs `before` (`n=90`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `before_untrained` (`untrained prior`) | `+0.6347` (`28/2/0`) | `-0.9450` (`1/29/0`) | `-0.8467` (`3/27/0`) | `-0.3857 [-0.5617, -0.2272]` | `baseline` |
| `easy_only` (`112000..112269`) | `+0.7930` (`30/0/0`) | `-0.7237` (`5/25/0`) | `-0.5580` (`8/22/0`) | `-0.1629 [-0.3273, +0.0092]` | `+0.2228 [+0.1010, +0.3514]` |
| `medium_only` (`112270..112539`) | `+0.7697` (`30/0/0`) | `+0.5807` (`25/0/5`) | `+0.5880` (`30/0/0`) | `+0.6461 [+0.6061, +0.6870]` | `+1.0318 [+0.8621, +1.1859]` |
| `hard_only` (`112540..112809`) | `+0.7843` (`30/0/0`) | `+0.5750` (`26/2/2`) | `+0.4817` (`27/2/1`) | `+0.6137 [+0.5329, +0.6724]` | `+0.9993 [+0.8471, +1.1464]` |
| `pooled_all` (`112810..113079`) | `+0.7943` (`30/0/0`) | `+0.5963` (`27/2/1`) | `+0.3750` (`25/4/1`) | `+0.5886 [+0.4869, +0.6711]` | `+0.9742 [+0.8024, +1.1620]` |

### 2B. `ScalingLogisticPolicy` (`82` Parameters, `is_open_weight_llm = False`)

| Train Regime (`TRAIN_SEEDS`) | Eval `easy` (`N=12, H=14d, 0% noise`) | Eval `medium` (`N=20, H=14d, 0% noise`) | Eval `hard` (`N=40, H=21d, 5% noise`) | Pooled `3`-Tier Mean (`n=90`) | Paired Delta vs `before` (`n=90`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `before_untrained` (`untrained prior`) | `+0.0000` (`0/0/30`) | `+0.0000` (`0/0/30`) | `+0.0000` (`0/0/30`) | `+0.0000 [+0.0000, +0.0000]` | `baseline` |
| `easy_only` (`107000..107269`) | `+0.7967` (`30/0/0`) | `+0.5403` (`26/1/3`) | `+0.2747` (`24/1/5`) | `+0.5372 [+0.4586, +0.6074]` | `+0.5372 [+0.4804, +0.6062]` |
| `medium_only` (`107600..107869`) | `+0.7907` (`30/0/0`) | `+0.6567` (`29/0/1`) | `+0.3997` (`30/0/0`) | `+0.6157 [+0.5710, +0.6623]` | `+0.6157 [+0.5701, +0.6541]` |
| `hard_only` (`108200..108469`) | `+0.7220` (`29/1/0`) | `+0.4093` (`24/5/1`) | `+0.4680` (`28/1/1`) | `+0.5331 [+0.4266, +0.6432]` | `+0.5331 [+0.4104, +0.6313]` |
| `pooled_all` (`107000..107089,107600..107689,108200..108289`) | `+0.7787` (`30/0/0`) | `+0.6320` (`28/0/2`) | `+0.4717` (`29/0/1`) | `+0.6274 [+0.5889, +0.6681]` | `+0.6274 [+0.5818, +0.6739]` |

## 3. Zero-Shot OOD Pool/Horizon Retention vs Unseen `5%` Canary Fingerprint Noise (`hard`, `n=30`)

| OOD Transfer / Surgical Arm (`hard`, `N=40, H=21d, 5% noise`) | Score `[95% Bootstrap CI]` | Calibrated Public EV `[95% CI]` | C / W / A (`Precision`) | Retention vs `hard_only` | Paired Delta vs Reference `[95% CI]` |
| :--- | :--- | :--- | :--- | ---: | :--- |
| `EmpiricalBayesPolicy` (`medium_only -> hard`) | `+0.5880 [+0.5503, +0.6233]` | `+0.5246 [+0.4960, +0.5566]` | `30/0/0` (`30/30`) | `122.1%` | `+0.1063 [-0.0213, +0.2827]` (vs `eb_hard_only`) |
| `EmpiricalBayesPolicy` (`easy_only -> hard` raw) | `-0.5580 [-0.7943, -0.2827]` | `-0.5239 [-0.7670, -0.2565]` | `8/22/0` (`8/30`) | `-115.8%` | `-1.0397 [-1.3453, -0.7140]` (vs `eb_hard_only`) |
| `eb_easy_deception_neutral_hard_elim` (`0%` fp hard-elim) | `+0.3807 [+0.2077, +0.5380]` | `+0.4418 [+0.3197, +0.5228]` | `26/3/1` (`26/29`) | `79.0%` | `+0.9387 [+0.5993, +1.2503]` (vs `eb_easy_only`) |
| `eb_easy_deception_neutral_fp95_cal` (`5%` fp calibrated) | `+0.4407 [+0.2407, +0.5570]` | `+0.4967 [+0.4574, +0.5309]` | `28/2/0` (`28/30`) | `91.5%` | `+0.0600 [-0.0213, +0.1933]` (vs `0%` fp hard-elim) |
| `eb_medium_plus_fp95_and_h21_stop` | `+0.5393 [+0.4633, +0.6130]` | `+0.5033 [+0.4338, +0.5576]` | `28/0/2` (`28/28`) | `112.0%` | `-0.0487 [-0.1257, +0.0187]` (vs `eb_medium_only`) |
| `ScalingLogisticPolicy` (`easy_only -> hard`) | `+0.2747 [+0.1487, +0.3860]` | `+0.2848 [+0.2201, +0.3520]` | `24/1/5` (`24/25`) | `58.7%` | `-0.1933 [-0.3573, -0.0210]` (vs `sl_hard_only`) |
| `ScalingLogisticPolicy` (`medium_only -> hard`) | `+0.3997 [+0.3397, +0.4590]` | `+0.3695 [+0.3254, +0.4300]` | `30/0/0` (`30/30`) | `85.4%` | `-0.0683 [-0.1523, +0.0507]` (vs `sl_hard_only`) |
| `sl_easy_noise_blind_hard_elim` (`w_suspect[5]=-30`) | `+0.3050 [+0.1850, +0.3960]` | `+0.3003 [+0.2410, +0.3633]` | `24/1/5` (`24/25`) | `65.2%` | `+0.0303 [+0.0097, +0.0593]` (vs `sl_easy_only`) |

## 4. Exact Environment-Side `5%` Canary Fingerprint Noise Counterfactual (`fp_acc: 1.00 -> 0.95` on `hard`, `n=30`)

| Policy (`N=40, H=21d, 2-3d delay, decoy+framing`) | Noise-Free `hard` (`fp=1.00`) | Standard `v1.4` `hard` (`fp=0.95`, `5%` noise) | Exact `5%` Noise Cost (`fp=0.95 - fp=1.00`) `[95% CI]` | Calibrated EV Delta `[95% CI]` |
| :--- | :--- | :--- | :--- | :--- |
| `eb_easy_deception_neutral_hard_elim` | `+0.5917` (`30/0/0`) | `+0.3807` (`26/3/1`) | `-0.2110 [-0.3800, -0.0517]` | `-0.0983 [-0.2155, -0.0159]` |
| `eb_hard_only` | `+0.6107` (`29/0/1`) | `+0.4817` (`27/2/1`) | `-0.1290 [-0.3247, -0.0087]` | `-0.0147 [-0.0544, +0.0260]` |
| `sl_easy_only` | `+0.3490` (`26/0/4`) | `+0.2747` (`24/1/5`) | `-0.0743 [-0.2077, +0.0547]` | `-0.0046 [-0.0849, +0.0738]` |
| `sl_hard_only` | `+0.4940` (`29/1/0`) | `+0.4680` (`28/1/1`) | `-0.0260 [-0.0603, +0.0213]` | `+0.0743 [-0.0139, +0.1976]` |

## 5. Mechanistic Findings

1. **Employee-Equivariant Pool Scaling (`N=12/20 -> 40`) + Horizon-Aware `1/(1+V(d))` Stopping (`H=14d -> 21d`) Generalize Zero-Shot (`85.4%` to `122.1%` Retention)**: When deceptive social/framing channels are calibrated on `medium_only` (`N=20, H=14d, 0% fingerprint noise, 1 canary/day`), zero-shot transfer to `hard` (`N=40, H=21d, 5% fingerprint noise, 2 canaries/day`) retains `122.1%` of `hard_only` score for `EmpiricalBayesPolicy` (`+0.5880` vs `+0.4817`, `30/30` correct, `0` wrong accusations) and `85.4%` for `ScalingLogisticPolicy` (`+0.3997` vs `+0.4680`, `30/30` correct, `0` wrong accusations). Even from `easy_only` (`N=12, H=14d, decoy=False, framing=False`), `ScalingLogisticPolicy` achieves `+0.2747` zero-shot on `hard` (`58.7%` of `hard_only`, `24/30` correct, `1` wrong) because its features normalize recipient/variant group information as `log(N / |group|)` and gate decoy/after-hours signals via the public instruction flags.
2. **Why Raw `EmpiricalBayesPolicy` (`easy_only`) Fails on `medium`/`hard` vs Surgical Fix**: On `easy_only` (`decoy=False`), `0` angry messages occur across all `180` Stage-2 episodes, so unguarded class-imbalanced Laplace smoothing (`1` mole vs `11` innocents) assigns `w_angry_msg = +2.387` plus unframed `w_after_hours = +0.692`, producing `22/30` decoy/framing wrong accusations (`-0.5580`) on `hard`. Shrinking zero-count unseen channels to `0.0` immediately restores `+0.3807` (`26/30` correct) on `v1.4` `hard` and `+0.5917` (`30/30` correct) on noise-free `hard` (`fp=1.00`).
3. **Exact OOD Cost of Unseen `5%` Canary Fingerprint Noise (`fp_acc: 1.00 -> 0.95`)**: Turning on `hard`'s `5%` canary variant flip rate drops noise-free `easy`-trained deterministic elimination (`eb_easy_deception_neutral_hard_elim`) from `+0.5917` (`30/30` correct) to `+0.3807` (`26/30` correct, `3` wrong, `1` abstain): a paired OOD noise cost of `-0.2110` (`95%` CI `[-0.3800, -0.0517]`). Replacing only `w_canary_miss` with `5%`-noise-calibrated LLR on frozen `v1.4` `hard` recovers `+0.0600` (`26 -> 28` correct), while `eb_hard_only` suffers only `-0.1290` (`29/30 -> 27/30` correct).

## 6. Reproduction and Fast Verification

```bash
python scripts/tiebreak_cross_tier_transfer_audit.py
python scripts/tiebreak_cross_tier_transfer_audit.py --check
pytest -q tests/test_tiebreak_cross_tier_transfer.py
```
