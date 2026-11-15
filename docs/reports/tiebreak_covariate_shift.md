# Off-Policy State-Visitation Divergence & DAgger Covariate-Shift Audit (`v1.4`)

Quantifies Ross-Bagnell `O(T^2 eps)` compounding off-policy state divergence versus `O(T eps)` structured on-policy DAgger recovery in Canary's `28`-feature public-ledger space on world-paired `HELDOUT_SEEDS 800000..800029` (`n=90` per policy, `30/tier`, `world_secret_tag` `sha256:ebf2f09716cf76d3`, **`540/540`** canonical `Env` replays verified, `0` invalid episodes).

- **Seed & Secret Provenance (Panel Fix A)**: Live trajectories evaluate strictly on `HELDOUT_SEEDS 800000..800029` (with committed `n=180` cross-checks on `800000..800059`) under `sha256:ebf2f09716cf76d3`; all policy weights originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`>= 900000`) touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` open-weight `Qwen2.5` runs in `experiment_ledger.json` beat untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Compact policies audited here (`is_open_weight_llm = False`) use `0` `canary.solver` / `canary.world` imports and are never conflated with open-weight LLM runs.

## 1. Own-Policy Trajectory Summary & Held-Out Score Recovery (`n=90` Live + `n=180` Committed)

| Policy (`stage_id`) | Params | `TRAIN_SEEDS` | `n=90` Score (`+/- CI95`) | `n=180` Score | Accuracy (`n=90`) | Wrong / Abstain | Mean Stop Day | Diag Arms Planted |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| `eb_reference` (`eb_experience_opt`) | `11` | `102000..103199` | `+0.6223 +/- 0.0498` | `+0.6073` | `0.911` | `0.000` / `0.089` | `7.99` | `27.44` |
| `linear_stage1_sft` (`stage1_survivorship_sft`) | `785` | `109000..109149` | `+0.5286 +/- 0.0723` | `+0.5175` | `0.889` | `0.022` / `0.089` | `10.07` | `32.43` |
| `linear_offline_bc` (`stage2_calibrated_bc`) | `785` | `109000..109149` | `+0.5169 +/- 0.0680` | `+0.4762` | `0.856` | `0.011` / `0.133` | `10.20` | `32.17` |
| `linear_stage4_dagger` (`stage3_onpolicy_dagger_r2`) | `785` | `109000..109509` | `+0.6632 +/- 0.0561` | `+0.6267` | `0.967` | `0.011` / `0.022` | `7.61` | `27.67` |
| `mlp_r0_sft` (`stage1_uncalibrated_sft`) | `12293` | `107000..107599` | `-0.2327 +/- 0.1910` | `-0.2781` | `0.411` | `0.589` / `0.000` | `4.50` | `14.63` |
| `mlp_r2_dagger` (`stage3_onpolicy_dagger_r2`) | `12293` | `107000..107599` | `+0.6292 +/- 0.0643` | `+0.6141` | `0.944` | `0.022` / `0.033` | `7.72` | `27.78` |

- **Linear DAgger Recovery (`CompactLinearDAggerPolicy`, `785`p)**: Offline calibrated BC (`stage2_calibrated_bc`) drifts to Day `10.20` (`32.17` arms, `0.133` abstain); Stage 4 DAgger (`stage3_onpolicy_dagger_r2`) recovers committed `n=180` score **`+0.4762` -> `+0.6267`** (luck-EV `+0.4793 -> +0.6303`, `+0.476 -> +0.627`, paired **`+0.1505`**; live `n=90` **`+0.1463`** `[+0.0760, +0.2185]`), while student-state teacher agreement jumps **`0.7435` -> `0.9805`**.
- **Neural MLP DAgger Recovery (`TinyMLPPolicy`, `12,293`p)**: Uncalibrated `r0` SFT (`stage1_uncalibrated_sft`) accuses prematurely at Day `4.50` (`14.63` arms, `0.589` wrong accuse); `r2` DAgger (`stage3_onpolicy_dagger_r2`) recovers committed `n=180` score **`-0.2781` -> `+0.6141`** (`-0.278 -> +0.614`, paired **`+0.8922`**; live `n=90` **`+0.8619`** `[+0.6662, +1.0449]`), converging with `EmpiricalBayesPolicy` (`7.99` days, `27.44` arms).

## 2. Compounding Off-Policy State Divergence (`O(T^2 eps)`) vs DAgger Recovery (`O(T eps)`)

| Policy vs `eb_reference` | Horizon Phase | `SMD(top1)` | `L1(top1)` | `JS(top1)` | `SMD(hits)` | `SMD(arms)` | `SMD(V_obs)` | `28D Marg L1` | `28D SMD` | Active Gap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `linear_stage1_sft` | Early (1..3) | `0.383` | `0.068` | `0.0565` | `0.158` | `0.004` | `0.038` | `0.6305` | `0.219` | `0.000` |
| `linear_stage1_sft` | Mid (4..8) | `0.305` | `0.242` | `0.0649` | `0.359` | `0.011` | `0.158` | `2.2567` | `0.341` | `0.078` |
| `linear_stage1_sft` | Late (9..21) | `0.537` | `0.161` | `0.1052` | `0.160` | `0.456` | `0.855` | `4.9512` | `0.308` | `0.233` |
| `linear_offline_bc` | Early (1..3) | `0.216` | `0.050` | `0.0416` | `0.158` | `0.021` | `0.031` | `0.5159` | `0.226` | `0.000` |
| `linear_offline_bc` | Mid (4..8) | `0.643` | `0.288` | `0.3061` | `0.400` | `0.038` | `0.153` | `2.9451` | `0.503` | `0.089` |
| `linear_offline_bc` | Late (9..21) | `1.790` | `0.314` | `0.7016` | `0.311` | `0.378` | `0.775` | `6.0684` | `0.624` | `0.228` |
| `linear_stage4_dagger` | Early (1..3) | `0.290` | `0.063` | `0.0371` | `0.184` | `0.244` | `0.039` | `0.4729` | `0.171` | `0.000` |
| `linear_stage4_dagger` | Mid (4..8) | `0.129` | `0.277` | `0.0699` | `0.132` | `0.185` | `0.344` | `1.4619` | `0.253` | `0.089` |
| `linear_stage4_dagger` | Late (9..21) | `0.423` | `0.141` | `0.0683` | `0.417` | `0.197` | `0.258` | `2.5859` | `0.248` | `0.039` |
| `mlp_r0_sft` | Early (1..3) | `0.155` | `0.063` | `0.0466` | `0.086` | `0.160` | `0.128` | `0.4647` | `0.113` | `0.056` |
| `mlp_r0_sft` | Mid (4..8) | `0.779` | `0.358` | `0.1687` | `1.015` | `0.647` | `1.412` | `4.2380` | `0.460` | `0.413` |
| `mlp_r0_sft` | Late (9..21) | `3.295` | `0.629` | `0.6820` | `2.457` | `1.193` | `1.811` | `9.7931` | `0.825` | `0.110` |
| `mlp_r2_dagger` | Early (1..3) | `0.223` | `0.054` | `0.0359` | `0.187` | `0.014` | `0.058` | `0.5396` | `0.184` | `0.000` |
| `mlp_r2_dagger` | Mid (4..8) | `0.090` | `0.242` | `0.0414` | `0.106` | `0.024` | `0.102` | `0.7732` | `0.205` | `0.044` |
| `mlp_r2_dagger` | Late (9..21) | `0.380` | `0.103` | `0.1046` | `0.412` | `0.061` | `0.079` | `1.4450` | `0.209` | `0.039` |

- **Quadratic Off-Policy Drift vs Linear DAgger Stabilization**: From Early (`Days 1..3`) to Late (`Days 9..21`), offline BC compounds `SMD(top1)` by **`8.30x`** and `JS(top1)` by **`16.87x`**, while `mlp_r0_sft` compounds `SMD(top1)` by **`21.30x`** and `28D Marginal L1` by **`21.07x`**. On-policy DAgger cuts Late `JS(top1)` by **`90.3%`** (`SMD(top1)` **`-76.3%`**, `28D Marginal L1` **`-57.4%`**) on `CompactLinearDAggerPolicy` and cuts Late `SMD(top1)` by **`88.5%`** (`JS(top1)` **`-84.7%`**, `SMD(arms)` **`-94.9%`**, `SMD(V_obs)` **`-95.6%`**) on `TinyMLPPolicy`.

## 3. Day-by-Day State-Visitation Snapshots (`Days 1, 3, 5, 7, 10, 14, 21`)

| Day (`n`) | `EB top1` / `V_obs` | Lin BC `SMD(top1)` / `JS` / `28D L1` | Lin DAgger `SMD(top1)` / `JS` / `28D L1` | MLP `r0` `SMD(top1)` / `JS` / `28D L1` | MLP `r2` `SMD(top1)` / `JS` / `28D L1` |
|---|---:|---:|---:|---:|---:|
| Day `1` (`90`) | `0.057` / `0.987` | `0.177` / `0.046` / `0.02` | `0.177` / `0.046` / `0.02` | `0.026` / `0.046` / `0.00` | `0.063` / `0.046` / `0.00` |
| Day `3` (`90`) | `0.185` / `0.921` | `0.082` / `0.064` / `0.70` | `0.268` / `0.039` / `0.76` | `0.157` / `0.043` / `0.74` | `0.318` / `0.032` / `0.94` |
| Day `5` (`90`) | `0.493` / `0.834` | `0.468` / `0.251` / `2.51` | `0.176` / `0.037` / `1.10` | `0.535` / `0.103` / `3.14` | `0.071` / `0.059` / `0.71` |
| Day `7` (`90`) | `0.701` / `0.771` | `0.902` / `0.378` / `3.80` | `0.011` / `0.092` / `1.78` | `1.102` / `0.228` / `5.49` | `0.054` / `0.025` / `0.73` |
| Day `10` (`90`) | `0.875` / `0.717` | `1.235` / `0.540` / `4.34` | `0.098` / `0.071` / `1.93` | `1.898` / `0.419` / `8.08` | `0.104` / `0.057` / `0.81` |
| Day `14` (`90`) | `0.925` / `0.694` | `1.255` / `0.613` / `4.26` | `0.041` / `0.046` / `1.92` | `2.219` / `0.505` / `8.96` | `0.257` / `0.062` / `1.13` |
| Day `21` (`30`) | `0.986` / `0.619` | `2.519` / `0.820` / `7.98` | `0.715` / `0.070` / `2.97` | `4.664` / `0.894` / `11.19` | `0.886` / `0.148` / `1.82` |

## 4. Why Structured DAgger Succeeds While Verda X2 Raw-Transcript `DAgger r1` Fails

| DAgger Cohort | Track (`is_open_weight_llm`) | Representation & Sufficiency | Student-State Match | Accuse / Abstain | Whom-Precision | Held-Out Score (`95% CI`) |
|---|---|---|---|---:|---:|---:|
| `compact-linear-dagger-v14` (`r2`) | Compact Linear (`False`) | Lossless `28`-feat public ledger (`0%` eviction) | `0.744 -> 0.980` | `0.972` / `0.028` | `170/175` (`0.971`) | **`+0.627 [+0.575, +0.672]`** (`n=180`) |
| `tiny-mlp-dagger-v14` (`r2`) | Compact Neural (`False`) | Lossless `28`-feat public ledger (`0%` eviction) | `r0 -> r2` calibrated | `0.961` / `0.039` | `168/173` (`0.971`) | **`+0.614 [+0.565, +0.663]`** (`n=180`) |
| `WS4-dagger-r1-8k-verda` (`8k`) | Open-Weight `Qwen2.5-1.5B` (`True`) | Raw `8k` chat (`56.7-84.7%` canary eviction) | `0.43 -> 0.68` | `0.92` / `0.08` | `10/46` (`0.22`) | **`-0.542 +/- 0.214`** (`n=50`) |
| `WS4-dagger-r1-4k-verda` (`4k`) | Open-Weight `Qwen2.5-1.5B` (`True`) | Raw `4k` chat (`92.2-98.0%` canary eviction) | Same `250`-step adapter | `0.15` / `0.85` | `1/6` (`0.17`) | **`-0.101 +/- 0.112`** (`n=41`) |

Ross & Bagnell's `O(T eps)` no-regret reduction requires single-step classification regret `eps` on own-policy states `s ~ d^pi` to be **realizable**. In raw-transcript `Qwen2.5-1.5B` (`0 / 19` runs `> 0.000`), `24,074` solver-relabelled rollout states lifted action-type agreement from `0.43` to `0.68`, yet sliding-window truncation evicted `92.22%..97.98%` (`4k`) and `56.73%..84.65%` (`8k`) of planted canary-variant maps before leak surfacing (plus `73.9%` `cap=96` truncation on hard `plant_canary` JSON and `3.98%` `159/4000` raw `accuse` label share without explicit `1/(1+V)` EV stopping). Preserving canary-assignment sufficiency in the `28`-feature public ledger makes `eps` small on own-policy states and turns DAgger into a verified held-out gain.

### Offline Verification Commands

```bash
python scripts/tiebreak_covariate_shift_audit.py --check
pytest -q tests/test_tiebreak_covariate_shift.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
