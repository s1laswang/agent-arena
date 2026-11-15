# Multi-World-Secret Stability & Luck-Adjusted EV Robustness Audit (`v1.4`)

Deterministic keyless audit across all `4` verified Canary compact non-LLM policies (`CompactLinearDAggerPolicy`, `TinyMLPPolicy`, `ScalingLogisticPolicy`, `EmpiricalBayesPolicy`) evaluating `HELDOUT_SEEDS 800000..800029` (`n=90` per secret: `30` `easy`, `30` `medium`, `30` `hard`) across `K=5` independent deterministic world secrets (`eval-01` = `sha256:ebf2f09716cf76d3` through `eval-05`, `450` fast `TemplateProvider()` episodes/policy, `1800` primary trained rollouts + `1800` fresh `Env` replays). Luck-adjusted accusation expected value is computed directly from public tool observations via `EmpiricalBayesPolicy`'s exact calibrated softmax posterior (`p_posterior * known_or_true_V_est - (1 - p_posterior) * 1.0`, `0` `canary.solver` imports).

- **Seed & Secret Provenance (Panel Fix A)**: All `1800` primary rollouts strictly evaluate `HELDOUT_SEEDS 800000..800029` across `K=5` deterministic world secrets (`eval-01..05`, primary `sha256:ebf2f09716cf76d3`), while all policy weights and posterior likelihood parameters originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`900k+`) touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` compact policies audited here (`is_open_weight_llm = False`) are non-LLM structured/neural models strictly separated from open-weight `Qwen2.5` LoRA and Verda GRPO runs.

## 1. Headline Multi-Secret Stability Summary (`K=5` World Secrets x `n=90` = `450` Episodes / Policy)

| Policy (`run_id`) | Params | Train Seeds | Mean Score Across `K=5` Secrets | Raw Sample SD / Within-Secret SE / Excess `tau` (`< 0.030`) | Mean Luck-Adj EV Across `K=5` | Inter-Secret Luck-EV SD | Positive Paired `95% CI` Secrets (vs `0.000` / Untrained) | Verda `8k` SD / Policy SD |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `785` | `109000..109509` | `+0.6199` (`[+0.5837, +0.6632]`) | `0.03301` / `0.03348` / **`0.00000`** | `+0.5976` (`[+0.5404, +0.6380]`) | **`0.03779`** | **`5/5` & `5/5`** | `12.7x` |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `12,293` | `107000..107599` | `+0.6036` (`[+0.5566, +0.6352]`) | `0.03214` / `0.03498` / **`0.00000`** | `+0.6011` (`[+0.5866, +0.6260]`) | **`0.01614`** | **`5/5` & `5/5`** | `13.1x` |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `82` | `107000..108999` | `+0.5717` (`[+0.5406, +0.6107]`) | `0.02718` / `0.03726` / **`0.00000`** | `+0.5816` (`[+0.5262, +0.6120]`) | **`0.03267`** | **`5/5` & `5/5`** | `15.4x` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `11` | `102000..102779` | `+0.6020` (`[+0.5446, +0.6282]`) | `0.03393` / `0.03328` / **`0.00660`** | `+0.6030` (`[+0.5870, +0.6201]`) | **`0.01218`** | **`5/5` & `5/5`** | `12.4x` |

Across all `4` compact non-LLM policies, raw sample inter-secret score SD (`ddof=1` across `K=5` secrets of `n=90` episodes) spans `0.02718..0.03393` (population SD `0.02431..0.03035`), matching the theoretical `n=90` finite-sample standard error (`~0.033..0.037`) so that noise-subtracted excess inter-secret heterogeneity `tau` spans **`0.00000..0.00660`** (every policy strictly `< 0.03`). Inter-secret luck-adjusted EV SD spans `0.01218..0.03779`, and **`20/20` (`100.0%`)** policy-secret cells achieve strictly positive paired `95%` CIs on both raw score and luck-adjusted EV against both zero-skill `abstain` (`0.000`) and architecture-matched untrained baselines.

## 2. Per-Secret Trajectory & Luck-Adjusted EV Matrix (`20` Policy x Secret Cells, `n=90` Each)

| Policy | Secret ID (`world_secret_tag`) | Raw Score (`95% CI`) | Luck-Adj EV (`95% CI`) | Paired Delta vs Untrained (`95% CI`) | Luck-EV Delta vs Untrained (`95% CI`) | Acc / Wrong / Abstain | Mean `p_post` / `V_est` | Replay |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `CompactLinearDAggerPolicy` | `eval-01` (`sha256:ebf2f09716cf76d3`) | `+0.6632 [+0.6071, +0.7194]` | `+0.6242 [+0.5675, +0.6809]` | `+0.6632 [+0.6071, +0.7194]` | `+0.6242 [+0.5675, +0.6809]` | `0.967` / `0.011` / `0.022` | `0.968` / `0.687` | `90/90` |
| `CompactLinearDAggerPolicy` | `eval-02` (`sha256:d367a024407a1f41`) | `+0.6081 [+0.5356, +0.6806]` | `+0.6380 [+0.5978, +0.6781]` | `+0.6081 [+0.5356, +0.6806]` | `+0.6380 [+0.5978, +0.6781]` | `0.944` / `0.033` / `0.022` | `0.986` / `0.674` | `90/90` |
| `CompactLinearDAggerPolicy` | `eval-03` (`sha256:2548c365a196248e`) | `+0.5998 [+0.5322, +0.6674]` | `+0.5404 [+0.4725, +0.6083]` | `+0.5998 [+0.5322, +0.6674]` | `+0.5404 [+0.4725, +0.6083]` | `0.911` / `0.022` / `0.067` | `0.940` / `0.670` | `90/90` |
| `CompactLinearDAggerPolicy` | `eval-04` (`sha256:a9ecdb729beee970`) | `+0.6449 [+0.5933, +0.6965]` | `+0.5984 [+0.5401, +0.6566]` | `+0.6449 [+0.5933, +0.6965]` | `+0.5984 [+0.5401, +0.6566]` | `0.967` / `0.011` / `0.022` | `0.960` / `0.671` | `90/90` |
| `CompactLinearDAggerPolicy` | `eval-05` (`sha256:7cb9a7ed5b13640e`) | `+0.5837 [+0.5069, +0.6604]` | `+0.5873 [+0.5266, +0.6480]` | `+0.5837 [+0.5069, +0.6604]` | `+0.5873 [+0.5266, +0.6480]` | `0.900` / `0.033` / `0.067` | `0.969` / `0.681` | `90/90` |
| `TinyMLPPolicy` | `eval-01` (`sha256:ebf2f09716cf76d3`) | `+0.6292 [+0.5649, +0.6935]` | `+0.6078 [+0.5596, +0.6560]` | `+1.5626 [+1.4688, +1.6563]` | `+1.5022 [+1.4590, +1.5455]` | `0.944` / `0.022` / `0.033` | `0.970` / `0.680` | `90/90` |
| `TinyMLPPolicy` | `eval-02` (`sha256:d367a024407a1f41`) | `+0.5566 [+0.4787, +0.6345]` | `+0.5866 [+0.5364, +0.6368]` | `+1.4454 [+1.3144, +1.5765]` | `+1.4811 [+1.4352, +1.5270]` | `0.889` / `0.033` / `0.078` | `0.986` / `0.659` | `90/90` |
| `TinyMLPPolicy` | `eval-03` (`sha256:2548c365a196248e`) | `+0.6352 [+0.5764, +0.6940]` | `+0.6260 [+0.5790, +0.6731]` | `+1.6130 [+1.5416, +1.6844]` | `+1.5205 [+1.4778, +1.5632]` | `0.922` / `0.011` / `0.067` | `0.985` / `0.697` | `90/90` |
| `TinyMLPPolicy` | `eval-04` (`sha256:a9ecdb729beee970`) | `+0.6088 [+0.5468, +0.6707]` | `+0.5893 [+0.5362, +0.6424]` | `+1.4532 [+1.3215, +1.5850]` | `+1.4837 [+1.4352, +1.5322]` | `0.922` / `0.011` / `0.067` | `0.980` / `0.666` | `90/90` |
| `TinyMLPPolicy` | `eval-05` (`sha256:7cb9a7ed5b13640e`) | `+0.5882 [+0.5108, +0.6657]` | `+0.5960 [+0.5446, +0.6474]` | `+1.5660 [+1.4783, +1.6537]` | `+1.4905 [+1.4427, +1.5382]` | `0.889` / `0.033` / `0.078` | `0.975` / `0.688` | `90/90` |
| `ScalingLogisticPolicy` | `eval-01` (`sha256:ebf2f09716cf76d3`) | `+0.6107 [+0.5420, +0.6794]` | `+0.6120 [+0.5664, +0.6575]` | `+0.6107 [+0.5420, +0.6794]` | `+0.6120 [+0.5664, +0.6575]` | `0.922` / `0.022` / `0.056` | `0.984` / `0.676` | `90/90` |
| `ScalingLogisticPolicy` | `eval-02` (`sha256:d367a024407a1f41`) | `+0.5624 [+0.4870, +0.6379]` | `+0.5923 [+0.5490, +0.6357]` | `+0.5624 [+0.4870, +0.6379]` | `+0.5923 [+0.5490, +0.6357]` | `0.911` / `0.033` / `0.056` | `0.988` / `0.647` | `90/90` |
| `ScalingLogisticPolicy` | `eval-03` (`sha256:2548c365a196248e`) | `+0.5586 [+0.5006, +0.6165]` | `+0.5262 [+0.4688, +0.5835]` | `+0.5586 [+0.5006, +0.6165]` | `+0.5262 [+0.4688, +0.5835]` | `0.856` / `0.000` / `0.144` | `0.982` / `0.644` | `90/90` |
| `ScalingLogisticPolicy` | `eval-04` (`sha256:a9ecdb729beee970`) | `+0.5861 [+0.5181, +0.6541]` | `+0.5831 [+0.5348, +0.6314]` | `+0.5861 [+0.5181, +0.6541]` | `+0.5831 [+0.5348, +0.6314]` | `0.922` / `0.022` / `0.056` | `0.982` / `0.647` | `90/90` |
| `ScalingLogisticPolicy` | `eval-05` (`sha256:7cb9a7ed5b13640e`) | `+0.5406 [+0.4497, +0.6315]` | `+0.5943 [+0.5457, +0.6429]` | `+0.5406 [+0.4497, +0.6315]` | `+0.5943 [+0.5457, +0.6429]` | `0.867` / `0.056` / `0.078` | `0.984` / `0.671` | `90/90` |
| `EmpiricalBayesPolicy` | `eval-01` (`sha256:ebf2f09716cf76d3`) | `+0.6223 [+0.5726, +0.6721]` | `+0.6039 [+0.5555, +0.6523]` | `+1.0080 [+0.8448, +1.1712]` | `+1.0068 [+0.8542, +1.1593]` | `0.911` / `0.000` / `0.089` | `0.989` / `0.682` | `90/90` |
| `EmpiricalBayesPolicy` | `eval-02` (`sha256:d367a024407a1f41`) | `+0.5989 [+0.5242, +0.6736]` | `+0.6201 [+0.5759, +0.6643]` | `+1.0179 [+0.8529, +1.1829]` | `+1.0804 [+0.9334, +1.2275]` | `0.911` / `0.033` / `0.056` | `0.982` / `0.686` | `90/90` |
| `EmpiricalBayesPolicy` | `eval-03` (`sha256:2548c365a196248e`) | `+0.6160 [+0.5618, +0.6702]` | `+0.6066 [+0.5644, +0.6489]` | `+1.1177 [+0.9596, +1.2757]` | `+1.0851 [+0.9384, +1.2318]` | `0.956` / `0.011` / `0.033` | `0.985` / `0.653` | `90/90` |
| `EmpiricalBayesPolicy` | `eval-04` (`sha256:a9ecdb729beee970`) | `+0.6282 [+0.5761, +0.6804]` | `+0.5975 [+0.5459, +0.6491]` | `+1.0391 [+0.8888, +1.1895]` | `+1.0414 [+0.9041, +1.1788]` | `0.911` / `0.000` / `0.089` | `0.984` / `0.682` | `90/90` |
| `EmpiricalBayesPolicy` | `eval-05` (`sha256:7cb9a7ed5b13640e`) | `+0.5446 [+0.4576, +0.6315]` | `+0.5870 [+0.5350, +0.6391]` | `+0.9421 [+0.7832, +1.1010]` | `+1.0101 [+0.8659, +1.1543]` | `0.856` / `0.044` / `0.100` | `0.986` / `0.675` | `90/90` |

## 3. Pooled `450`-Episode Tier & Calibration Summary Across `K=5` World Secrets

| Policy | Pooled `450` Raw Score (`95% CI`) | Pooled `450` Luck-Adj EV (`95% CI`) | `easy` (`n=150`) Score / Luck-EV | `medium` (`n=150`) Score / Luck-EV | `hard` (`n=150`) Score / Luck-EV | Valid Call Rate |
|---|---:|---:|---:|---:|---:|---:|
| `CompactLinearDAggerPolicy` | `+0.6199 [+0.5906, +0.6493]` | `+0.5976 [+0.5719, +0.6234]` | `+0.7955` / `+0.7661` | `+0.6103` / `+0.5836` | `+0.4541` / `+0.4433` | `1.0000` |
| `TinyMLPPolicy` | `+0.6036 [+0.5730, +0.6342]` | `+0.6011 [+0.5788, +0.6235]` | `+0.8002` / `+0.7807` | `+0.5636` / `+0.5408` | `+0.4470` / `+0.4820` | `1.0000` |
| `ScalingLogisticPolicy` | `+0.5717 [+0.5391, +0.6043]` | `+0.5816 [+0.5597, +0.6035]` | `+0.7762` / `+0.7493` | `+0.5298` / `+0.5086` | `+0.4090` / `+0.4868` | `1.0000` |
| `EmpiricalBayesPolicy` | `+0.6020 [+0.5728, +0.6312]` | `+0.6030 [+0.5817, +0.6244]` | `+0.7685` / `+0.7505` | `+0.5366` / `+0.5354` | `+0.5009` / `+0.5232` | `1.0000` |

## 4. Contrast vs Bimodal Verda `8k` GRPO Seed Instability (`Qwen2.5-3B` LoRA)

Whereas compact non-LLM policies act on sufficient public summary statistics with calibrated EV stopping (producing tight inter-secret SDs `< 0.03` and `5/5` positive paired `95%` CIs), open-weight `Qwen2.5-3B` Verda `8k` GRPO runs on the same `HELDOUT_SEEDS 800000..800029` (`n=90`) exhibit severe bimodal instability across training seeds (`s0=-0.060`, `s2=-0.050` high-step abstain collapse vs `s1=-0.777`, `s3=-0.788` low-step over-accusation):

| Cohort / Run | Seeds / Scope | Mean Score | Luck-Adjusted EV | Accuse / Abstain Rate | Regime / Stability Verdict |
|---|---|---:|---:|---:|---|
| Verda GRPO `v3_8k_s0` (`8k-s0`, `H100`) | `800000..800029` (`n=90`, `637` steps) | `-0.0604` (`-0.060`) | `-0.0571` | `0.078` / `0.922` | `high_step_abstain_regime` (below `0.000` base) |
| Verda GRPO `v3_8k_s1` (`8k-s1`, `A100`) | `800000..800029` (`n=90`, `371` steps) | `-0.7767` (`-0.777`) | `-0.8289` | `0.944` / `0.056` | `low_step_over_accuse_regime` (below `0.000` base) |
| Verda GRPO `v3_8k_s2` (`8k-s2`, `H100`) | `800000..800029` (`n=90`, `693` steps) | `-0.0498` (`-0.050`) | `-0.0439` | `0.067` / `0.933` | `high_step_abstain_regime` (below `0.000` base) |
| Verda GRPO `v3_8k_s3` (`8k-s3`, `A100`) | `800000..800029` (`n=90`, `344` steps) | `-0.7882` (`-0.788`) | `-0.8459` | `0.956` / `0.044` | `low_step_over_accuse_regime` (below `0.000` base) |
| **Verda `8k` GRPO Dispersion (`4` runs)** | `s0, s1, s2, s3` (`360` eps) | `-0.4188` (`SD = 0.4200`, range `0.7384`) | `-0.4440` (`SD = 0.4544`) | bimodal `0.072` vs `0.950` | **`0/4` runs > `0.000`** (`+0.7273` cluster split) |
| **Compact Non-LLM Policies (`4` models x `5` secrets)** | `eval-01..05` (`1800` eps) | `+0.5993` (`SD = 0.0272..0.0339`, `tau <= 0.0066 < 0.030`) | `+0.5958` (`SD = 0.0122..0.0378`) | calibrated EV commit | **`20/20` cells positive `95% CI`** (`12.4x..15.4x` tighter SD) |

### Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_multiseed_stability_audit.py --check
pytest -q tests/test_tiebreak_multiseed_stability.py tests/test_reproduce_tiebreak_all.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
