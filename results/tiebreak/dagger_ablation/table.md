CompactLinearDAggerPolicy Covariate-Shift and 4-Stage DAgger Ablation (Canary v1.4)
===================================================================================

- Run ID: `compact-linear-dagger-v14`
- Model: `CompactLinearDAggerPolicy (4-stage SFT vs BC vs On-Policy DAgger)` (`785` linear parameters, 0 LLM calls)
- Inference module: `train/compact_dagger_ablation.py` (AST-verified zero `canary.solver` / `canary.world` imports in inference path)
- Train seed range: `109000..109509` strictly inside `TRAIN_SEEDS [100000, 200000)` (Offline SFT/BC `109000..109149`, DAgger R1 `109150..109299`, DAgger R2 `109300..109449`, Covariate-Shift Val `109450..109509`)
- Primary held-out eval seed range: `800000..800059` across `easy, medium, hard` (`n=60/tier`, `n=180` paired episodes, world secret `sha256:ebf2f09716cf76d3`)
- Headline Before -> After (`stage0_untrained` -> `stage3_onpolicy_dagger_r2`, `n=180`): mean score `+0.0000` -> `+0.6267`, paired mean delta `+0.6267` (95% CI `[+0.5775, +0.6759]`), luck-adjusted EV delta `+0.6303` (`[+0.5952, +0.6638]`), replay verified `True` (`1530` episodes, `0` invalid)

1. Held-Out 4-Stage Progression and Reference Baselines (Seeds 800000..800059, n=180)
-------------------------------------------------------------------------------------

| Stage / Policy | n | Mean Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Cap Stall | Valid Call Rate | Canaries/Ep |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| stage0_untrained | 180 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0.000 | 0.000 | 1.000 | 0.000 | 1.0000 | 0.00 |
| stage1_survivorship_sft | 180 | +0.5175 [+0.4630, +0.5670] | +0.5259 [+0.4812, +0.5680] | 0.872 | 0.022 | 0.106 | 0.000 | 1.0000 | 10.82 |
| stage2_calibrated_bc | 180 | +0.4762 [+0.4213, +0.5280] | +0.4793 [+0.4306, +0.5256] | 0.794 | 0.022 | 0.183 | 0.000 | 0.9787 | 10.24 |
| stage3a_onpolicy_dagger_r1 | 180 | +0.4988 [+0.4362, +0.5574] | +0.5193 [+0.4697, +0.5661] | 0.756 | 0.033 | 0.211 | 0.000 | 0.4012 | 7.24 |
| stage3_onpolicy_dagger_r2 | 180 | +0.6267 [+0.5753, +0.6716] | +0.6303 [+0.5952, +0.6638] | 0.944 | 0.028 | 0.028 | 0.000 | 1.0000 | 9.05 |
| heuristic | 180 | +0.2255 [+0.1283, +0.3212] | +0.2080 [+0.1320, +0.2827] | 0.789 | 0.211 | 0.000 | 0.000 | 1.0000 | 13.66 |
| solver | 180 | +0.6706 [+0.6348, +0.7023] | +0.6587 [+0.6273, +0.6880] | 0.944 | 0.006 | 0.050 | 0.000 | 1.0000 | 7.93 |

2. Paired Step-by-Step Ablation Deltas on Held-Out Seeds 800000..800059 (n=180)
-------------------------------------------------------------------------------

| Ablation Comparison (After - Before) | Mechanism Isolated | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |
|---|---|---:|---:|
| stage1_survivorship_sft - stage0_untrained | Offline SFT on winning rollouts only (survivorship bias + covariate shift) | +0.5175 [+0.4665, +0.5685] | +0.5259 [+0.4812, +0.5680] |
| stage2_calibrated_bc - stage1_survivorship_sft | Adding censored horizon abstentions + soft Bayesian posteriors (still off-policy) | -0.0413 [-0.0871, +0.0045] | -0.0466 [-0.0860, -0.0068] |
| stage3a_onpolicy_dagger_r1 - stage2_calibrated_bc | On-policy DAgger Round 1 state recovery on student rollouts | +0.0226 [-0.0484, +0.0936] | +0.0400 [-0.0166, +0.0976] |
| stage3_onpolicy_dagger_r2 - stage3a_onpolicy_dagger_r1 | On-policy DAgger Round 2 refinement on student rollouts | +0.1279 [+0.0696, +0.1861] | +0.1110 [+0.0657, +0.1558] |
| stage3_onpolicy_dagger_r2 - stage2_calibrated_bc | Total on-policy DAgger gain over calibrated offline BC (pure covariate-shift fix) | +0.1505 [+0.0869, +0.2141] | +0.1510 [+0.1007, +0.2019] |
| stage3_onpolicy_dagger_r2 - stage1_survivorship_sft | Calibrated posteriors + abstentions + on-policy DAgger over survivorship SFT | +0.1092 [+0.0478, +0.1707] | +0.1045 [+0.0596, +0.1504] |
| stage3_onpolicy_dagger_r2 - stage0_untrained | Headline Before -> After improvement from Canary experience | +0.6267 [+0.5775, +0.6759] | +0.6303 [+0.5952, +0.6638] |
| stage3_onpolicy_dagger_r2 - heuristic | Compact 785-param linear DAgger policy vs scripted heuristic baseline | +0.4012 [+0.2988, +0.5036] | +0.4223 [+0.3535, +0.4943] |
| stage3_onpolicy_dagger_r2 - solver | Compact 785-param linear DAgger policy vs exact nonlinear Bayesian solver | -0.0438 [-0.0966, +0.0090] | -0.0284 [-0.0657, +0.0091] |

3. Direct Covariate-Shift Diagnostics on Disjoint Train-Val Slice (109450..109509, n=60)
----------------------------------------------------------------------------------------

| Stage | Expert-State Agreement P_expert | Student-State Agreement P_student | Covariate-Shift Drop | Out-of-Support State Rate | Valid Call Rate | Cap Stall Rate | Train-Val Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| stage0_untrained | 0.0178 | 0.0029 | +0.0148 | 0.9912 | 1.0000 | 0.0000 | +0.0000 |
| stage1_survivorship_sft | 0.7989 | 0.7600 | +0.0389 | 0.0169 | 1.0000 | 0.0000 | +0.5443 |
| stage2_calibrated_bc | 0.7941 | 0.7435 | +0.0506 | 0.0161 | 1.0000 | 0.0000 | +0.4952 |
| stage3a_onpolicy_dagger_r1 | 0.9615 | 0.2565 | +0.7050 | 0.7478 | 0.2710 | 0.0000 | +0.4477 |
| stage3_onpolicy_dagger_r2 | 0.9751 | 0.9805 | -0.0053 | 0.0416 | 1.0000 | 0.0000 | +0.6585 |

4. Held-Out Per-Tier Breakdown (Seeds 800000..800059, n=60/tier)
----------------------------------------------------------------

| Tier | Stage / Policy | n | Mean Score [95% CI] | Luck-Adjusted EV | Accuracy | Wrong Accuse | Abstain | Cap Stall |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| easy | stage0_untrained | 60 | +0.0000 [+0.0000, +0.0000] | +0.0000 | 0.000 | 0.000 | 1.000 | 0.000 |
| easy | stage1_survivorship_sft | 60 | +0.7848 [+0.7600, +0.8068] | +0.7742 | 1.000 | 0.000 | 0.000 | 0.000 |
| easy | stage2_calibrated_bc | 60 | +0.6318 [+0.5417, +0.7150] | +0.6318 | 0.783 | 0.000 | 0.217 | 0.000 |
| easy | stage3_onpolicy_dagger_r2 | 60 | +0.7868 [+0.7610, +0.8103] | +0.7638 | 1.000 | 0.000 | 0.000 | 0.000 |
| easy | heuristic | 60 | +0.6773 [+0.6502, +0.7035] | +0.6773 | 1.000 | 0.000 | 0.000 | 0.000 |
| easy | solver | 60 | +0.7970 [+0.7712, +0.8190] | +0.7940 | 1.000 | 0.000 | 0.000 | 0.000 |
| medium | stage0_untrained | 60 | +0.0000 [+0.0000, +0.0000] | +0.0000 | 0.000 | 0.000 | 1.000 | 0.000 |
| medium | stage1_survivorship_sft | 60 | +0.4817 [+0.4077, +0.5518] | +0.4817 | 0.767 | 0.000 | 0.233 | 0.000 |
| medium | stage2_calibrated_bc | 60 | +0.4928 [+0.4188, +0.5623] | +0.4804 | 0.767 | 0.000 | 0.233 | 0.000 |
| medium | stage3_onpolicy_dagger_r2 | 60 | +0.6525 [+0.5930, +0.7055] | +0.6525 | 0.917 | 0.000 | 0.083 | 0.000 |
| medium | heuristic | 60 | -0.0140 [-0.2087, +0.1808] | -0.0827 | 0.617 | 0.383 | 0.000 | 0.000 |
| medium | solver | 60 | +0.6168 [+0.5470, +0.6807] | +0.6168 | 0.867 | 0.000 | 0.133 | 0.000 |
| hard | stage0_untrained | 60 | +0.0000 [+0.0000, +0.0000] | +0.0000 | 0.000 | 0.000 | 1.000 | 0.000 |
| hard | stage1_survivorship_sft | 60 | +0.2860 [+0.1798, +0.3760] | +0.3217 | 0.850 | 0.067 | 0.083 | 0.000 |
| hard | stage2_calibrated_bc | 60 | +0.3040 [+0.1966, +0.3960] | +0.3256 | 0.833 | 0.067 | 0.100 | 0.000 |
| hard | stage3_onpolicy_dagger_r2 | 60 | +0.4408 [+0.3132, +0.5485] | +0.4747 | 0.917 | 0.083 | 0.000 | 0.000 |
| hard | heuristic | 60 | +0.0132 [-0.1468, +0.1613] | +0.0293 | 0.750 | 0.250 | 0.000 | 0.000 |
| hard | solver | 60 | +0.5978 [+0.5255, +0.6523] | +0.5653 | 0.967 | 0.017 | 0.017 | 0.000 |

5. Keyless Reference Comparison on post-hoc locked dev hard 0..29 (Public Worlds, n=30)
---------------------------------------------------------------------------------------

- Protocol: `post-hoc locked dev hard 0..29` (`b"public"`, locked post-hoc for zero-API cross-comparison against committed frontier runs).

| Policy / Agent | n | Mean Score [95% CI] | Luck-Adjusted EV | Accuracy | Wrong Accuse | Abstain |
|---|---:|---:|---:|---:|---:|---:|
| stage0_untrained | 30 | +0.0000 [+0.0000, +0.0000] | +0.0000 | 0.000 | 0.000 | 1.000 |
| stage1_survivorship_sft | 30 | +0.3970 [+0.2726, +0.4997] | +0.3857 | 0.867 | 0.033 | 0.100 |
| stage2_calibrated_bc | 30 | +0.3727 [+0.2133, +0.5010] | +0.4170 | 0.900 | 0.067 | 0.033 |
| stage3a_onpolicy_dagger_r1 | 30 | +0.2090 [+0.0740, +0.3367] | +0.2127 | 0.433 | 0.033 | 0.533 |
| stage3_onpolicy_dagger_r2 | 30 | +0.5223 [+0.3906, +0.6053] | +0.4640 | 0.967 | 0.033 | 0.000 |
| heuristic | 30 | +0.0857 [-0.1197, +0.2710] | +0.0523 | 0.800 | 0.200 | 0.000 |
| solver | 30 | +0.4990 [+0.3676, +0.5993] | +0.4993 | 0.967 | 0.033 | 0.000 |
| opencode:google/gemini-4-carbon | 30 | +0.3223 [+0.1193, +0.5023] | +0.3223 | 0.833 | 0.133 | 0.033 |
| gemini:gemini-4-carbon | 30 | +0.4730 [+0.3373, +0.5693] | +0.4210 | 0.933 | 0.033 | 0.033 |
