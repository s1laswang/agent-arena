# Tiebreak Stopping Counterfactual & Regret Decomposition Audit (`v1.4`)

Deterministic CPU-only stopping counterfactual sweep and exact additive regret decomposition across `1,080` world-paired held-out episodes (`2` compact non-LLM policies x `6` stopping rules x `n=90` on `HELDOUT_SEEDS 800000..800029`, `30`/tier across `easy`, `medium`, `hard` under `sha256:ebf2f09716cf76d3`, `1080/1080` fresh `Env` replays verified). `EmpiricalBayesPolicy` (`11` params) peaks at **`+0.6223`** under `calibrated_ev_breakeven` (vs `+0.2772` on `reckless_p35`, regret `+0.3451`, and `+0.5590` on `hyper_conservative_p99`, regret `+0.0633`), while `CompactLinearDAggerPolicy` (`785` params) peaks at **`+0.6632`** under `calibrated_ev_breakeven` (vs `+0.3628` on `reckless_p35`, regret `+0.3004`, and `+0.5534` on `hyper_conservative_p99`, regret `+0.1098`).

- **Seed & Secret Provenance (Panel Fix A)**: All `1,080` live counterfactual episodes run strictly on world-paired `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`, all learned compact policy weights originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` (`102000..102779` and `109000..109509`), and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Separate frontier reference rows on `DEV_SEEDS 0..29` (`hard`, `n=30`) are ingested from committed replay-verified artifacts and are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Audited compact policies (`is_open_weight_llm = False`) are never conflated with Track 1 open-weight `Qwen2.5` LoRA runs.

## 1. World-Paired Stopping Sweep & Exact Regret Decomposition (`HELDOUT_SEEDS 800000..800029`, `n=90` / Rule)

For each world `i` (`tier`, `seed`), total paired regret `R_i = S_{i,cal} - S_{i,cf}` decomposes with `0.0` residual into three mutually exclusive channels: (1) **Premature Wrong-Accusation Penalty** (`-1` cliff episodes), (2) **Late-Stopping Value-Leakage Loss** (`V_cal - V_cf` when both catch the mole), and (3) **Over-Abstention Missed-Catch Loss** (`V_cal` forfeited when abstaining instead of catching).

| Policy | Stopping Rule (`formula`) | Score (`95% CI`) | Correct / Wrong / Abstain | Mean Accuse Day | Total Regret vs Cal | Wrong-Cliff Regret | Late-Leak Regret | Abstain-Miss Regret |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` (`11`p) | `reckless_p35` (`top_p >= 0.35`) | `+0.2772 [+0.1165, +0.4379]` | `62/23/5` | `5.69` | `+0.3451` | `+0.3976` | `-0.0474` | `-0.0050` |
| `EmpiricalBayesPolicy` (`11`p) | `uncalibrated_p55` (`top_p >= 0.55`) | `+0.5311 [+0.4282, +0.6341]` | `76/7/7` | `6.76` | `+0.0912` | `+0.1122` | `-0.0160` | `-0.0050` |
| `EmpiricalBayesPolicy` (`11`p) | `calibrated_ev_breakeven` (`p * V_est - (1 - p) > tau_cal`) | `+0.6223 [+0.5726, +0.6721]` | `82/0/8` | `7.40` | `+0.0000` | `+0.0000` | `+0.0000` | `+0.0000` |
| `EmpiricalBayesPolicy` (`11`p) | `conservative_p92` (`top_p >= 0.92`) | `+0.6223 [+0.5726, +0.6721]` | `82/0/8` | `7.40` | `+0.0000` | `+0.0000` | `+0.0000` | `+0.0000` |
| `EmpiricalBayesPolicy` (`11`p) | `hyper_conservative_p99` (`top_p >= 0.99`) | `+0.5590 [+0.5058, +0.6122]` | `78/0/12` | `7.91` | `+0.0633` | `+0.0000` | `+0.0416` | `+0.0218` |
| `EmpiricalBayesPolicy` (`11`p) | `always_abstain` (`never accuse (0.000 baseline)`) | `+0.0000 [+0.0000, +0.0000]` | `0/0/90` | `n/a` | `+0.6223` | `+0.0000` | `+0.0000` | `+0.6223` |
| `CompactLinearDAggerPolicy` (`785`p) | `reckless_p35` (`top_p >= 0.35`) | `+0.3628 [+0.2117, +0.5138]` | `69/19/2` | `5.89` | `+0.3004` | `+0.3564` | `-0.0560` | `+0.0000` |
| `CompactLinearDAggerPolicy` (`785`p) | `uncalibrated_p55` (`top_p >= 0.55`) | `+0.5801 [+0.4835, +0.6767]` | `82/6/2` | `7.06` | `+0.0831` | `+0.1002` | `-0.0171` | `+0.0000` |
| `CompactLinearDAggerPolicy` (`785`p) | `calibrated_ev_breakeven` (`p * V_est - (1 - p) > tau_cal`) | `+0.6632 [+0.6071, +0.7194]` | `87/1/2` | `7.47` | `+0.0000` | `+0.0000` | `+0.0000` | `+0.0000` |
| `CompactLinearDAggerPolicy` (`785`p) | `conservative_p92` (`top_p >= 0.92`) | `+0.6502 [+0.5912, +0.7093]` | `86/1/3` | `7.59` | `+0.0130` | `+0.0000` | `+0.0061` | `+0.0069` |
| `CompactLinearDAggerPolicy` (`785`p) | `hyper_conservative_p99` (`top_p >= 0.99`) | `+0.5534 [+0.4841, +0.6228]` | `72/0/18` | `7.38` | `+0.1098` | `-0.0111` | `+0.0391` | `+0.0818` |
| `CompactLinearDAggerPolicy` (`785`p) | `always_abstain` (`never accuse (0.000 baseline)`) | `+0.0000 [+0.0000, +0.0000]` | `0/0/90` | `n/a` | `+0.6632` | `-0.0111` | `+0.0000` | `+0.6743` |

## 2. Per-Tier Stopping Score & Regret Breakdown (`easy` / `medium` / `hard`, `n=30` / Cell)

| Policy | Stopping Rule | `easy` Score (Wrong / Abst) | `medium` Score (Wrong / Abst) | `hard` Score (Wrong / Abst) | Mean `top_p` at Stop | Below-Breakeven Accuses |
|---|---|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `reckless_p35` | `+0.5233` (`5/0`) | `+0.0653` (`10/5`) | `+0.2430` (`8/0`) | `0.636` | `50/85` |
| `EmpiricalBayesPolicy` | `uncalibrated_p55` | `+0.6490` (`2/1`) | `+0.4763` (`2/6`) | `+0.4680` (`3/0`) | `0.863` | `9/83` |
| `EmpiricalBayesPolicy` | `calibrated_ev_breakeven` | `+0.7287` (`0/2`) | `+0.5697` (`0/6`) | `+0.5687` (`0/0`) | `0.933` | `0/82` |
| `EmpiricalBayesPolicy` | `conservative_p92` | `+0.7287` (`0/2`) | `+0.5697` (`0/6`) | `+0.5687` (`0/0`) | `0.933` | `0/82` |
| `EmpiricalBayesPolicy` | `hyper_conservative_p99` | `+0.6723` (`0/2`) | `+0.4857` (`0/9`) | `+0.5190` (`0/1`) | `0.939` | `0/78` |
| `EmpiricalBayesPolicy` | `always_abstain` | `+0.0000` (`0/30`) | `+0.0000` (`0/30`) | `+0.0000` (`0/30`) | `0.942` | `0/0` |
| `CompactLinearDAggerPolicy` | `reckless_p35` | `+0.3070` (`9/0`) | `+0.3503` (`6/2`) | `+0.4310` (`4/0`) | `0.668` | `43/88` |
| `CompactLinearDAggerPolicy` | `uncalibrated_p55` | `+0.7660` (`1/0`) | `+0.5120` (`3/2`) | `+0.4623` (`2/0`) | `0.879` | `8/88` |
| `CompactLinearDAggerPolicy` | `calibrated_ev_breakeven` | `+0.8203` (`0/0`) | `+0.6790` (`0/2`) | `+0.4903` (`1/0`) | `0.952` | `4/88` |
| `CompactLinearDAggerPolicy` | `conservative_p92` | `+0.8203` (`0/0`) | `+0.6790` (`0/2`) | `+0.4513` (`1/1`) | `0.971` | `0/87` |
| `CompactLinearDAggerPolicy` | `hyper_conservative_p99` | `+0.8203` (`0/0`) | `+0.6790` (`0/2`) | `+0.1610` (`0/16`) | `0.975` | `0/72` |
| `CompactLinearDAggerPolicy` | `always_abstain` | `+0.0000` (`0/30`) | `+0.0000` (`0/30`) | `+0.0000` (`0/30`) | `0.975` | `0/0` |

## 3. Cross-Link to Verda `8k`/`4k` Qwen2.5 Regimes & Post-Hoc Frontier Reference

### 3.1 Verda `8k`/`4k` Open-Weight Qwen2.5 Stopping Regimes (`HELDOUT_SEEDS`, Track 1 `is_open_weight_llm = True`)

| Empirical Verda Cohort (`multiseed_summary.json`) | `n` | Mean Score (`+/- 95% CI`) | Accuse / Abstain Rate | Mean `p_accused` | Below-Breakeven Accuse | Counterfactual Stopping Analog |
|---|---:|---:|---:|---:|---:|---|
| `verda_8k_low_step_s1_s3` (`Qwen2.5-1.5B GRPO 8k low-step (s1+s3 pooled)`) | `180` | `-0.7824 +/- 0.0827` | `95.0% / 5.0%` | `0.0623` | `97.7%` | `reckless_p35 / premature uncalibrated stopping` |
| `verda_8k_high_step_s0_s2` (`Qwen2.5-1.5B GRPO 8k high-step (s0+s2 pooled)`) | `180` | `-0.0551 +/- 0.0363` | `7.2% / 92.8%` | `0.1824` | `84.6%` | `always_abstain / hyper_conservative_p99 abstain collapse` |
| `v3_4k_s0` (`Qwen2.5-1.5B GRPO 4k-s0 (4k truncation)`) | `180` | `-0.1474 +/- 0.0628` | `21.1% / 78.9%` | `0.1380` | `92.1%` | `context-truncated uncalibrated stopping + abstention` |
| `v3_4k_s1` (`Qwen2.5-1.5B GRPO 4k-s1 (4k truncation)`) | `82` | `-0.2088 +/- 0.0938` | `23.2% / 76.8%` | `0.1468` | `94.7%` | `context-truncated uncalibrated stopping + abstention` |

### 3.2 Separate Post-Hoc Locked `DEV_SEEDS 0..29` (`hard`, `n=30`) Frontier Stopping Reference

*Protocol note (Panel Fix A)*: `DEV_SEEDS 0..29` rows below are **post-hoc locked, not pre-registered**, evaluated on `hard` (`n=30`), and strictly separated from `HELDOUT_SEEDS 800000..800029`.

| Cohort (`DEV_SEEDS 0..29`, `hard`, `n=30`) | Mean Score (`+/- 95% CI`) | Luck-Adjusted EV | Correct / Wrong / Abstain | Mean Accuse Day | Mean `top_p` at Accuse | Below-Breakeven Accuse |
|---|---:|---:|---:|---:|---:|---:|
| `gemini-4-carbon (OpenCode over MCP, judges' harness)` | `+0.3223 +/- 0.1989` | `+0.3596` | `25/4/1` | `13.17` | `0.8819` | `10.3%` |
| `gpt-5.5 (OpenCode over MCP)` | `+0.5037 +/- 0.0638` | `+0.4176` | `28/0/2` | `10.25` | `0.9398` | `0.0%` |
| `gemini-3.5-flash (OpenCode over MCP)` | `+0.3730 +/- 0.1766` | `+0.1098` | `27/3/0` | `12.70` | `0.7412` | `30.0%` |
| `SolverPolicy (Bayesian canary-trap reference)` | `+0.4990 +/- 0.1193` | `+0.4993` | `29/1/0` | `10.60` | `0.9652` | `0.0%` |

## 4. Key Scientific Findings

1. **Asymmetric `-1` Cliff Dominates Premature Stopping**: Lowering the stopping bar to `reckless_p35` costs `+0.3451` total regret on `EmpiricalBayesPolicy` (`+0.3976` from the `-1` wrong-accusation cliff) and `+0.3004` on `CompactLinearDAggerPolicy` (`+0.3564` from wrong accusations), reproducing the mechanism behind Verda `v3_8k_s1`/`s3` (`-0.7824`, `97.7%` below-breakeven accusations).
2. **Uncalibrated `p >= 0.55` Still Loses to EV-Dynamic Stopping**: Even `uncalibrated_p55` suffers positive regret (`+0.0912` on `EmpiricalBayesPolicy`, `+0.0831` on `CompactLinearDAggerPolicy`) because decayed `V_est < 1.0` pushes true breakeven `1/(1+V_est)` above `0.55` and omits the option value of waiting one day for pending canary leaks.
3. **Over-Conservative Thresholds Trade Wrong-Cliff Risk for Delayed-Leak Decay & Abstention Loss**: Requiring `top_p >= 0.99` eliminates wrong accusations (`0/90` on both policies) but incurs `+0.0416` / `+0.0391` late-stopping `V` decay plus `+0.0218` / `+0.0818` missed-catch abstention regret, bridging continuously into `always_abstain` (`0.0000`) and Verda `v3_8k_s0`/`s2` abstain collapse (`-0.0551`, `92.8%` abstain).

## 5. Offline Reproducibility Commands

```bash
python scripts/tiebreak_stopping_counterfactual_audit.py --check
python scripts/tiebreak_stopping_counterfactual_audit.py --generate --workers 8
python -m pytest -q tests/test_tiebreak_stopping_counterfactual.py
python scripts/reproduce_tiebreak_all.py --check
```
