# Canary v1.4 Delayed-Leak & Fingerprint-Noise Held-Out Decomposition (`HELDOUT_SEEDS 800000..800029`)

Deterministic episode-by-episode decomposition of Canary v1.4 delayed leak visibility (`KNOWN_V_MODE = True`), 5% canary fingerprint corruption on `hard` (`fingerprint_accuracy = 0.95`), and world-paired tier-stratified regret relative to `SolverPolicy` across trained non-LLM tiebreak policies (`EmpiricalBayesPolicy`, `TinyMLPPolicy`, `CompactLinearDAggerPolicy`) and `canary.baselines.Heuristic`.

Disclosure (Panel Fix A & Panel Fix E): All tiebreaker policies audited here were trained strictly on TRAIN_SEEDS [100000, 200000) and evaluated strictly on disjoint world-paired HELDOUT_SEEDS 800000..800029 (n=90, 30 per tier) under one shared CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3); 0 DEV_SEEDS and 0 JUDGE_SEEDS (900000+) are touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A). Per Panel Fix E, non-LLM policies audited here (EmpiricalBayesPolicy, TinyMLPPolicy, CompactLinearDAggerPolicy) are strictly separated from open-weight Qwen2.5 LoRA runs.

- Held-out evaluation cohort: `HELDOUT_SEEDS 800000..800029` (`n=90` per policy, `30` per tier across `easy, medium, hard`)
- Shared world secret fingerprint: `sha256:ebf2f09716cf76d3` (`replay_verified=True`, `invalid_episodes=0`, `450/450` episodes verified via `verify_episode`)
- Trained policy provenance (loaded from committed JSON summaries): `EmpiricalBayesPolicy` (`empirical-bayes-v14`, `TRAIN_SEEDS 102000..102779`, `w_canary_hit=+1.3162`, `w_canary_miss=-3.7833`, `unsurfaced_v_discount=1.0`), `TinyMLPPolicy` (`tiny-mlp-dagger-v14`, `TRAIN_SEEDS 107000..107599`, `12293` params, `thr=0.46`), `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`, `TRAIN_SEEDS 109000..109509`, `785` params)

## 1. Overall & Tier-Stratified Held-Out Performance (`n=90` per Policy)

| Policy | Scope | `n` | Mean Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Canaries | Mean Day | Replay |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `solver` | `all` | 90 | `+0.6816 [+0.6281, +0.7350]` | `+0.6734 [+0.6324, +0.7144]` | 0.956 | 0.011 | 0.033 | 7.61 | 7.12 | `90/90` |
| `solver` | `easy` | 30 | `+0.7927 [+0.7516, +0.8337]` | `+0.7866 [+0.7385, +0.8347]` | 1.000 | 0.000 | 0.000 | 3.73 | 4.73 | `30/30` |
| `solver` | `medium` | 30 | `+0.6617 [+0.5731, +0.7502]` | `+0.6617 [+0.5731, +0.7502]` | 0.900 | 0.000 | 0.100 | 7.50 | 8.40 | `30/30` |
| `solver` | `hard` | 30 | `+0.5903 [+0.4719, +0.7088]` | `+0.5719 [+0.5243, +0.6194]` | 0.967 | 0.033 | 0.000 | 11.60 | 8.23 | `30/30` |
| `empirical_bayes` | `all` | 90 | `+0.6223 [+0.5726, +0.6721]` | `+0.6047 [+0.5538, +0.6556]` | 0.911 | 0.000 | 0.089 | 9.67 | 7.99 | `90/90` |
| `empirical_bayes` | `easy` | 30 | `+0.7287 [+0.6499, +0.8075]` | `+0.7287 [+0.6499, +0.8075]` | 0.933 | 0.000 | 0.067 | 4.83 | 5.83 | `30/30` |
| `empirical_bayes` | `medium` | 30 | `+0.5697 [+0.4608, +0.6785]` | `+0.5697 [+0.4608, +0.6785]` | 0.800 | 0.000 | 0.200 | 8.03 | 9.03 | `30/30` |
| `empirical_bayes` | `hard` | 30 | `+0.5687 [+0.5188, +0.6185]` | `+0.5158 [+0.4657, +0.5659]` | 1.000 | 0.000 | 0.000 | 16.13 | 9.10 | `30/30` |
| `tiny_mlp` | `all` | 90 | `+0.6292 [+0.5649, +0.6935]` | `+0.6295 [+0.5826, +0.6764]` | 0.944 | 0.022 | 0.033 | 9.32 | 7.72 | `90/90` |
| `tiny_mlp` | `easy` | 30 | `+0.8107 [+0.7795, +0.8418]` | `+0.8107 [+0.7795, +0.8418]` | 1.000 | 0.000 | 0.000 | 3.60 | 4.60 | `30/30` |
| `tiny_mlp` | `medium` | 30 | `+0.5840 [+0.5006, +0.6674]` | `+0.5840 [+0.5006, +0.6674]` | 0.900 | 0.000 | 0.100 | 8.77 | 9.77 | `30/30` |
| `tiny_mlp` | `hard` | 30 | `+0.4930 [+0.3411, +0.6449]` | `+0.4939 [+0.4214, +0.5664]` | 0.933 | 0.067 | 0.000 | 15.60 | 8.80 | `30/30` |
| `compact_linear_dagger` | `all` | 90 | `+0.6632 [+0.6071, +0.7194]` | `+0.6441 [+0.5937, +0.6945]` | 0.967 | 0.011 | 0.022 | 9.42 | 7.61 | `90/90` |
| `compact_linear_dagger` | `easy` | 30 | `+0.8203 [+0.7961, +0.8446]` | `+0.8203 [+0.7961, +0.8446]` | 1.000 | 0.000 | 0.000 | 3.30 | 4.30 | `30/30` |
| `compact_linear_dagger` | `medium` | 30 | `+0.6790 [+0.6024, +0.7556]` | `+0.6790 [+0.6024, +0.7556]` | 0.933 | 0.000 | 0.067 | 7.10 | 8.10 | `30/30` |
| `compact_linear_dagger` | `hard` | 30 | `+0.4903 [+0.3666, +0.6140]` | `+0.4330 [+0.3506, +0.5154]` | 0.967 | 0.033 | 0.000 | 17.87 | 10.43 | `30/30` |
| `heuristic_hard_elim` | `all` | 90 | `+0.1958 [+0.0507, +0.3409]` | `+0.2211 [+0.1150, +0.3272]` | 0.756 | 0.244 | 0.000 | 13.56 | 11.02 | `90/90` |
| `heuristic_hard_elim` | `easy` | 30 | `+0.7000 [+0.6651, +0.7349]` | `+0.7000 [+0.6651, +0.7349]` | 1.000 | 0.000 | 0.000 | 5.50 | 6.50 | `30/30` |
| `heuristic_hard_elim` | `medium` | 30 | `+0.0193 [-0.2638, +0.3025]` | `-0.0074 [-0.1959, +0.1811]` | 0.633 | 0.367 | 0.000 | 10.10 | 11.10 | `30/30` |
| `heuristic_hard_elim` | `hard` | 30 | `-0.1320 [-0.3778, +0.1138]` | `-0.0292 [-0.1752, +0.1169]` | 0.633 | 0.367 | 0.000 | 25.07 | 15.47 | `30/30` |

## 2. Pillar (a): Hidden Unsurfaced Leak Gap (`known_v - true_v`) Across Delay Regimes

Under Canary v1.4 (`KNOWN_V_MODE = True`), `status` reports `known_v` (excluding damage from leaks whose feed delay `d + delta > today`), whereas terminal scoring uses `true_v`. On `easy` (`delay_choices = (1,)`), every leak from closed days `1..today-1` has already surfaced by `today`, producing zero hidden gap at accusation steps (`0.0000` accuse-day gap across all 4 primary policies; the `0.0033` all-episode mean on `empirical_bayes` comes solely from `2/30` day-14 horizon abstentions where day-14 closure leaks surface on day 15). As feed delay widens to `1..3` days (`medium`, `leak_damage = 0.04`) and `2..3` days (`hard`, `leak_damage = 0.05`), unsurfaced in-flight leaks create a systematic upward bias in `known_v` and shift the true breakeven accusation posterior `1 / (1 + true_v)` upward relative to `1 / (1 + known_v)`.

| Policy | Tier (Delay, Noise) | `n` | Accused | Mean `known_v` | Mean `true_v` | Mean `known_v - true_v` [95% CI] | Accuse-Day Gap | Gap > 0 | Mean Unsurfaced Leaks | Uncorrected MAE | Delay-Discounted MAE | Breakeven Shift |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `solver` | `easy (1d, 0%)` | 30 | 30/30 | `0.7927` | `0.7927` | `0.0000 [0.0000, 0.0000]` | `0.0000` | `0/30` | 0.00 | `0.0000` | `0.0000` | `+0.0000` |
| `solver` | `medium (1-3d, 0%)` | 30 | 27/30 | `0.7277` | `0.7090` | `0.0187 [0.0089, 0.0284]` | `0.0133` | `12/30` | 0.47 | `0.0187` | `0.0247` | `+0.0069` |
| `solver` | `hard (2-3d, 5%)` | 30 | 30/30 | `0.6940` | `0.6473` | `0.0467 [0.0362, 0.0571]` | `0.0467` | `24/30` | 0.93 | `0.0467` | `0.0174` | `+0.0176` |
| `empirical_bayes` | `easy (1d, 0%)` | 30 | 28/30 | `0.7500` | `0.7467` | `0.0033 [-0.0012, 0.0079]` | `0.0000` | `2/30` | 0.07 | `0.0033` | `0.0033` | `+0.0020` |
| `empirical_bayes` | `medium (1-3d, 0%)` | 30 | 24/30 | `0.7010` | `0.6730` | `0.0280 [0.0187, 0.0373]` | `0.0233` | `18/30` | 0.70 | `0.0280` | `0.0220` | `+0.0105` |
| `empirical_bayes` | `hard (2-3d, 5%)` | 30 | 30/30 | `0.6187` | `0.5687` | `0.0500 [0.0395, 0.0605]` | `0.0500` | `25/30` | 1.00 | `0.0500` | `0.0175` | `+0.0201` |
| `tiny_mlp` | `easy (1d, 0%)` | 30 | 30/30 | `0.8107` | `0.8107` | `0.0000 [0.0000, 0.0000]` | `0.0000` | `0/30` | 0.00 | `0.0000` | `0.0000` | `+0.0000` |
| `tiny_mlp` | `medium (1-3d, 0%)` | 30 | 27/30 | `0.6550` | `0.6283` | `0.0267 [0.0172, 0.0361]` | `0.0222` | `17/30` | 0.67 | `0.0267` | `0.0227` | `+0.0103` |
| `tiny_mlp` | `hard (2-3d, 5%)` | 30 | 30/30 | `0.6340` | `0.5990` | `0.0350 [0.0224, 0.0476]` | `0.0350` | `17/30` | 0.70 | `0.0350` | `0.0285` | `+0.0141` |
| `compact_linear_dagger` | `easy (1d, 0%)` | 30 | 30/30 | `0.8203` | `0.8203` | `0.0000 [0.0000, 0.0000]` | `0.0000` | `0/30` | 0.00 | `0.0000` | `0.0000` | `+0.0000` |
| `compact_linear_dagger` | `medium (1-3d, 0%)` | 30 | 28/30 | `0.7370` | `0.7117` | `0.0253 [0.0158, 0.0349]` | `0.0214` | `16/30` | 0.63 | `0.0253` | `0.0233` | `+0.0090` |
| `compact_linear_dagger` | `hard (2-3d, 5%)` | 30 | 30/30 | `0.5730` | `0.5297` | `0.0433 [0.0303, 0.0564]` | `0.0433` | `20/30` | 0.87 | `0.0433` | `0.0271` | `+0.0200` |

## 3. Pillar (b): `hard` 5% Fingerprint Noise Mismatches & Smoothed Likelihood Ratios vs Naive Hard-Elimination

On `hard` (`fingerprint_accuracy = 0.95`, `max_variants = 3`), a leaked canary shows the mole's true variant with likelihood `0.95` and flips to each other planted variant with likelihood `0.0250` (`(1 - 0.95) / 2`), yielding a finite mismatch-vs-hit log-likelihood ratio of `-3.6376` nats (`EmpiricalBayesPolicy` independently learns `w_canary_miss = -3.7833` on `TRAIN_SEEDS`). Across all `120` primary `hard` episodes (`272` leaked canaries), `11` canary leaks suffered 5% fingerprint flips (`4.04%` empirical rate; `0` flips across all `easy` and `medium` episodes), with `8` mismatch events surfacing in `check_leak_feed` before decision across `6` episodes:

- **Matched-observation counterfactual**: On those `6` episodes with observed noisy canary mismatches, naive zero-tolerance hard-elimination (`fingerprint_accuracy = 1.0` without fallback) sets `P(true_mole) = 0.0` in `6/6` (`100.0%` false exculpation, including `4/6` empty-set contradiction collapses), catching `0/6` moles. Smoothed likelihood ratios keep `P_policy(true_mole) > 0` in `6/6` (`0.0%` hard false exculpation) and still catch the true mole in `3/6` (`50.0%`) episodes.
- **Live rollout comparator (`canary.baselines.Heuristic`)**: Running Silas's naive hard-elimination canary-bisection baseline (`suspects &= grp`) on the exact same `hard` worlds (`n=30`) yields mean score `-0.1320` and `7/7` (`100.0%`) false exculpations (`0/7` caught, every one scoring `-1.00`) whenever a noisy canary surfaces.

### 3.1 Per-Policy `hard` Canary Leak & Fingerprint-Noise Summary (`n=30` per Policy)

| Policy | Planted | Leaked Canaries | Observed Leaked | All Flips (Rate) | Observed Mismatch Eps | Caught on Mismatch | Policy `P(mole) > 0` | Naive Hard-Elim Exculpated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `solver` | 348 | 57 | 45 | `3 (5.3%)` | `1` | `0/1` | `1/1` | `1/1` |
| `empirical_bayes` | 484 | 86 | 67 | `2 (2.3%)` | `2` | `2/2` | `2/2` | `2/2` |
| `tiny_mlp` | 468 | 62 | 52 | `4 (6.5%)` | `2` | `1/2` | `2/2` | `2/2` |
| `compact_linear_dagger` | 536 | 67 | 54 | `2 (3.0%)` | `1` | `0/1` | `1/1` | `1/1` |
| `heuristic_hard_elim` | 752 | 102 | 87 | `9 (8.8%)` | `7` | `0/7` | `0/7` | `7/7` |

### 3.2 Episode-Level Forensics of Surfaced `hard` Noisy Canary Mismatch Events

| Policy | Seed | Canary (Plant->Surf) | Mole (`true`->`feed`) | Accused (Day) | Correct | Score | `P_smooth(mole)` | `P_policy(mole)` | `P_hard_elim(mole)` | Empty Set |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| `solver` | `800022` | `c4-2` (`d4->d6`) | `e39` (`A->C`) | `e02 (d6)` | `False` | `-1.00` | `0.0153` | `0.0153` | `0.0000` | `False` |
| `empirical_bayes` | `800007` | `c6-2` (`d6->d10`) | `e06` (`B->A`) | `e06 (d11)` | `True` | `+0.50` | `0.9951` | `0.9983` | `0.0000` | `True` |
| `empirical_bayes` | `800025` | `c4-2` (`d4->d7`) | `e25` (`B->A`) | `e25 (d8)` | `True` | `+0.56` | `1.0000` | `0.9999` | `0.0000` | `True` |
| `tiny_mlp` | `800017` | `c3` (`d3->d6`) | `e19` (`B->C`) | `e19 (d11)` | `True` | `+0.40` | `1.0000` | `1.0000` | `0.0000` | `True` |
| `tiny_mlp` | `800017` | `c5` (`d5->d7`) | `e19` (`A->C`) | `e19 (d11)` | `True` | `+0.40` | `1.0000` | `1.0000` | `0.0000` | `True` |
| `tiny_mlp` | `800029` | `c9-2` (`d9->d13`) | `e07` (`A->B`) | `e37 (d13)` | `False` | `-1.00` | `0.3074` | `0.1362` | `0.0000` | `False` |
| `compact_linear_dagger` | `800027` | `c13-2` (`d13->d18`) | `e24` (`B->C`) | `e39 (d21)` | `False` | `-1.00` | `0.0523` | `0.0307` | `0.0000` | `True` |
| `compact_linear_dagger` | `800027` | `c18-2` (`d18->d21`) | `e24` (`B->A`) | `e39 (d21)` | `False` | `-1.00` | `0.0523` | `0.0307` | `0.0000` | `True` |

## 4. Pillar (c): World-Paired Tier-Stratified Regret vs `SolverPolicy`

For each policy and world `(tier, seed)`, paired score regret `R = score(SolverPolicy) - score(policy)` is decomposed exactly into three mutually exclusive episode buckets: (1) `Both-Correct V Gap` (pure `true_v` stopping-time and canary-cost difference when both policies catch the mole), (2) `Wrong-Accuse Asymmetry` (episodes where at least one policy incurs the `-1.0` wrong-accusation penalty), and (3) `Abstention Asymmetry` (one policy catches while the other abstains at `0.0`).

| Policy | Scope | `n` | Score Regret vs `Solver` [95% CI] | Luck-Adjusted Regret [95% CI] | Both-Correct V Gap | Wrong-Accuse Regret | Abstention Regret |
|---|---|---:|---:|---:|---:|---:|---:|
| `empirical_bayes` | `all` | 90 | `+0.0592 [-0.0056, +0.1241]` | `+0.0687 [+0.0139, +0.1235]` | `+0.0364` (79) | `-0.0171` (1) | `+0.0399` (10) |
| `empirical_bayes` | `easy` | 30 | `+0.0640 [-0.0257, +0.1537]` | `+0.0580 [-0.0361, +0.1520]` | `+0.0120` (28) | `+0.0000` (0) | `+0.0520` (2) |
| `empirical_bayes` | `medium` | 30 | `+0.0920 [-0.0311, +0.2151]` | `+0.0920 [-0.0311, +0.2151]` | `+0.0243` (22) | `+0.0000` (0) | `+0.0677` (8) |
| `empirical_bayes` | `hard` | 30 | `+0.0217 [-0.1015, +0.1449]` | `+0.0561 [-0.0037, +0.1158]` | `+0.0730` (29) | `-0.0513` (1) | `+0.0000` (0) |
| `tiny_mlp` | `all` | 90 | `+0.0523 [-0.0258, +0.1305]` | `+0.0439 [-0.0098, +0.0976]` | `+0.0314` (81) | `+0.0187` (3) | `+0.0022` (6) |
| `tiny_mlp` | `easy` | 30 | `-0.0180 [-0.0665, +0.0305]` | `-0.0240 [-0.0792, +0.0311]` | `-0.0180` (30) | `+0.0000` (0) | `+0.0000` (0) |
| `tiny_mlp` | `medium` | 30 | `+0.0777 [-0.0457, +0.2010]` | `+0.0777 [-0.0457, +0.2010]` | `+0.0710` (24) | `+0.0000` (0) | `+0.0067` (6) |
| `tiny_mlp` | `hard` | 30 | `+0.0973 [-0.0968, +0.2914]` | `+0.0780 [-0.0079, +0.1639]` | `+0.0413` (27) | `+0.0560` (3) | `+0.0000` (0) |
| `compact_linear_dagger` | `all` | 90 | `+0.0183 [-0.0431, +0.0798]` | `+0.0293 [-0.0229, +0.0815]` | `+0.0253` (83) | `+0.0014` (2) | `-0.0084` (5) |
| `compact_linear_dagger` | `easy` | 30 | `-0.0277 [-0.0700, +0.0146]` | `-0.0337 [-0.0832, +0.0158]` | `-0.0277` (30) | `+0.0000` (0) | `+0.0000` (0) |
| `compact_linear_dagger` | `medium` | 30 | `-0.0173 [-0.1233, +0.0887]` | `-0.0173 [-0.1233, +0.0887]` | `+0.0080` (25) | `+0.0000` (0) | `-0.0253` (5) |
| `compact_linear_dagger` | `hard` | 30 | `+0.1000 [-0.0429, +0.2429]` | `+0.1389 [+0.0441, +0.2336]` | `+0.0957` (28) | `+0.0043` (2) | `+0.0000` (0) |
| `heuristic_hard_elim` | `all` | 90 | `+0.4858 [+0.3333, +0.6382]` | `+0.4523 [+0.3497, +0.5548]` | `+0.1040` (64) | `+0.4014` (23) | `-0.0197` (3) |
| `heuristic_hard_elim` | `easy` | 30 | `+0.0927 [+0.0370, +0.1484]` | `+0.0866 [+0.0246, +0.1487]` | `+0.0927` (30) | `+0.0000` (0) | `+0.0000` (0) |
| `heuristic_hard_elim` | `medium` | 30 | `+0.6423 [+0.3272, +0.9574]` | `+0.6691 [+0.4619, +0.8763]` | `+0.0640` (16) | `+0.6373` (11) | `-0.0590` (3) |
| `heuristic_hard_elim` | `hard` | 30 | `+0.7223 [+0.4387, +1.0060]` | `+0.6010 [+0.4489, +0.7532]` | `+0.1553` (18) | `+0.5670` (12) | `+0.0000` (0) |
