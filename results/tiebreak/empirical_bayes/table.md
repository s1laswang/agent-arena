EmpiricalBayesPolicy Tiebreaker and Component Ablation Report (Canary v1.4)
===========================================================================

- Train seed range: `102000..102779` (Stage 2 likelihoods `102000..102179`, Stage 3 stopping/splits `102600..102779`)
- Primary held-out eval seed range: `800000..800059` across `easy, medium, hard` (`n=60/tier`, `180` episodes/variant, matching `v3-4k-s0` `n=180` scale)
- Retained held-out subset seed range: `800000..800029` across `easy, medium, hard` (`n=30/tier`, `90` episodes/variant for exact `n=90` cross-comparisons)
- Held-out world secret tag: `canary-tiebreak-heldout-v14-eval-01` (sha256 prefix `ebf2f09716cf`, shared across all paired held-out variants)
- Keyless reference benchmark: `post-hoc locked dev hard 0..29` (`b"public"`, `n=30`, paired vs `solver` and committed `gemini-4-carbon`)
- Tool-by-tool Env replay verified: `True` (`1530` episodes replayed with zero mismatches)

1. Learned Parameter and Component Ablation Configurations (TRAIN_SEEDS 102000..102779)
---------------------------------------------------------------------------------------

| Variant | w_canary_hit | w_canary_miss | w_doc_hit | w_after_hours | w_evasive | w_angry_msg | tau_margin | unsurfaced_v_disc | canary_cov | tiny_pool | ev_stop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| eb_naive_prior | +1.000 | -0.800 | +0.600 | +0.800 | +0.400 | +1.200 | 0.00 | 0.00 | 0.90 | 0 | False |
| eb_likelihood_only | +1.316 | -3.783 | +7.921 | +0.122 | +0.344 | -2.362 | 0.00 | 0.00 | 0.90 | 0 | False |
| eb_ev_stop_only | +1.000 | -0.800 | +0.600 | +0.800 | +0.400 | +1.200 | 0.00 | 0.00 | 0.90 | 0 | True |
| eb_no_canary_planting | +1.316 | -3.783 | +7.921 | +0.122 | +0.344 | -2.362 | 0.50 | 1.00 | 0.00 | 0 | True |
| eb_experience_opt | +1.316 | -3.783 | +7.921 | +0.122 | +0.344 | -2.362 | 0.50 | 1.00 | 0.65 | 3 | True |

2. Component Ablation Matrix and Held-Out Overall Progression (Seeds 800000..800059, n=180, Plus Exact Seeds 800000..800029, n=90)
----------------------------------------------------------------------------------------------------------------------------------

Primary held-out evaluation on `800000..800059` (`n=60/tier = 180` episodes, shared secret `canary-tiebreak-heldout-v14-eval-01`, 100% Env replay-verified):

| Agent / Variant | Mechanism Isolated | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| eb_naive_prior | Untrained prior + uncalibrated p>=0.50 stopping + default 0.90 splits | 180 | 4.89 | -0.421 [-0.538, -0.301] | -0.395 [-0.506, -0.281] | 0.328 | 0.661 | 0.011 | 4.7 |
| eb_likelihood_only | Learned log-likelihoods on TRAIN_SEEDS, no EV-stopping, default 0.90 splits | 180 | 9.32 | +0.358 [+0.259, +0.455] | +0.328 [+0.264, +0.389] | 0.783 | 0.189 | 0.028 | 7.3 |
| eb_ev_stop_only | Naive prior + 1/(1+V) EV-stopping without learned likelihoods (negative ablation) | 180 | 5.23 | -0.421 [-0.536, -0.303] | -0.395 [-0.504, -0.282] | 0.333 | 0.656 | 0.011 | 4.9 |
| eb_no_canary_planting | Learned likelihoods + EV-stopping, canary_cov=0.0 passive logs/messages/docs only (negative ablation) | 180 | 0.00 | +0.029 [-0.006, +0.062] | -0.008 [-0.033, +0.017] | 0.089 | 0.022 | 0.889 | 13.4 |
| eb_experience_opt | Full learned likelihoods + learned canary-split sizing + learned tau_margin EV-stopping | 180 | 9.71 | +0.607 [+0.559, +0.648] | +0.605 [+0.567, +0.639] | 0.922 | 0.017 | 0.061 | 7.6 |
| heuristic | Scripted heuristic baseline | 180 | 13.66 | +0.226 [+0.129, +0.321] | +0.208 [+0.132, +0.282] | 0.789 | 0.211 | 0.000 | 11.1 |
| solver | Exact Bayesian reference solver | 180 | 7.93 | +0.671 [+0.635, +0.702] | +0.659 [+0.628, +0.688] | 0.944 | 0.006 | 0.050 | 7.1 |

Retained exact `n=90` subset on `800000..800029` (`n=30/tier`, shared secret `canary-tiebreak-heldout-v14-eval-01`):

| Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| eb_naive_prior | 90 | 4.80 | -0.386 [-0.558, -0.209] | -0.365 [-0.528, -0.200] | 0.356 | 0.644 | 0.000 | 4.7 |
| eb_likelihood_only | 90 | 8.92 | +0.341 [+0.193, +0.480] | +0.368 [+0.272, +0.460] | 0.767 | 0.200 | 0.033 | 7.1 |
| eb_ev_stop_only | 90 | 5.14 | -0.395 [-0.564, -0.220] | -0.374 [-0.536, -0.211] | 0.356 | 0.644 | 0.000 | 5.0 |
| eb_no_canary_planting | 90 | 0.00 | +0.023 [-0.034, +0.079] | +0.020 [-0.016, +0.062] | 0.089 | 0.033 | 0.878 | 13.0 |
| eb_experience_opt | 90 | 9.67 | +0.622 [+0.571, +0.671] | +0.605 [+0.552, +0.654] | 0.911 | 0.000 | 0.089 | 7.4 |
| heuristic | 90 | 13.56 | +0.196 [+0.049, +0.335] | +0.221 [+0.114, +0.326] | 0.756 | 0.244 | 0.000 | 11.0 |
| solver | 90 | 7.61 | +0.682 [+0.624, +0.730] | +0.673 [+0.631, +0.713] | 0.956 | 0.011 | 0.033 | 6.9 |

3. Held-Out Per-Tier Results (Seeds 800000..800059, n=60/tier, and Seeds 800000..800029, n=30/tier)
---------------------------------------------------------------------------------------------------

Full held-out per-tier breakdown (`800000..800059`, `n=60/tier`):

| Tier | Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| easy | eb_naive_prior | 60 | 4.52 | +0.600 [+0.462, +0.712] | +0.617 [+0.543, +0.683] | 0.917 | 0.083 | 0.000 | 5.5 |
| easy | eb_likelihood_only | 60 | 3.63 | +0.675 [+0.549, +0.776] | +0.608 [+0.523, +0.687] | 0.933 | 0.067 | 0.000 | 4.6 |
| easy | eb_ev_stop_only | 60 | 4.83 | +0.583 [+0.447, +0.696] | +0.613 [+0.543, +0.677] | 0.917 | 0.083 | 0.000 | 5.8 |
| easy | eb_no_canary_planting | 60 | 0.00 | +0.108 [+0.052, +0.173] | +0.014 [-0.043, +0.081] | 0.183 | 0.000 | 0.817 | 11.1 |
| easy | eb_experience_opt | 60 | 4.52 | +0.746 [+0.698, +0.785] | +0.746 [+0.698, +0.785] | 0.967 | 0.000 | 0.033 | 5.2 |
| easy | heuristic | 60 | 5.85 | +0.677 [+0.650, +0.704] | +0.677 [+0.650, +0.704] | 1.000 | 0.000 | 0.000 | 6.8 |
| easy | solver | 60 | 3.72 | +0.797 [+0.771, +0.819] | +0.794 [+0.764, +0.819] | 1.000 | 0.000 | 0.000 | 4.7 |
| medium | eb_naive_prior | 60 | 3.40 | -0.939 [-1.000, -0.862] | -0.900 [-0.955, -0.834] | 0.017 | 0.950 | 0.033 | 4.0 |
| medium | eb_likelihood_only | 60 | 7.35 | +0.261 [+0.067, +0.436] | +0.237 [+0.131, +0.343] | 0.683 | 0.233 | 0.083 | 7.7 |
| medium | eb_ev_stop_only | 60 | 3.48 | -0.940 [-1.000, -0.863] | -0.904 [-0.960, -0.840] | 0.017 | 0.950 | 0.033 | 4.2 |
| medium | eb_no_canary_planting | 60 | 0.00 | -0.021 [-0.091, +0.041] | -0.047 [-0.092, -0.011] | 0.050 | 0.050 | 0.900 | 14.0 |
| medium | eb_experience_opt | 60 | 8.07 | +0.545 [+0.439, +0.635] | +0.564 [+0.477, +0.642] | 0.817 | 0.033 | 0.150 | 8.2 |
| medium | heuristic | 60 | 10.22 | -0.014 [-0.215, +0.183] | -0.083 [-0.216, +0.052] | 0.617 | 0.383 | 0.000 | 11.2 |
| medium | solver | 60 | 8.12 | +0.617 [+0.546, +0.680] | +0.617 [+0.546, +0.680] | 0.867 | 0.000 | 0.133 | 8.2 |
| hard | eb_naive_prior | 60 | 6.77 | -0.923 [-1.000, -0.823] | -0.904 [-0.964, -0.828] | 0.050 | 0.950 | 0.000 | 4.4 |
| hard | eb_likelihood_only | 60 | 16.97 | +0.139 [-0.046, +0.311] | +0.138 [+0.033, +0.240] | 0.733 | 0.267 | 0.000 | 9.5 |
| hard | eb_ev_stop_only | 60 | 7.37 | -0.905 [-0.978, -0.808] | -0.893 [-0.961, -0.810] | 0.067 | 0.933 | 0.000 | 4.7 |
| hard | eb_no_canary_planting | 60 | 0.00 | -0.002 [-0.044, +0.033] | +0.008 [+0.000, +0.021] | 0.033 | 0.017 | 0.950 | 21.0 |
| hard | eb_experience_opt | 60 | 16.53 | +0.531 [+0.462, +0.582] | +0.505 [+0.470, +0.538] | 0.983 | 0.017 | 0.000 | 9.3 |
| hard | heuristic | 60 | 24.92 | +0.013 [-0.145, +0.163] | +0.029 [-0.069, +0.124] | 0.750 | 0.250 | 0.000 | 15.3 |
| hard | solver | 60 | 11.97 | +0.598 [+0.525, +0.653] | +0.565 [+0.527, +0.602] | 0.967 | 0.017 | 0.017 | 8.5 |

Retained `n=30/tier` per-tier breakdown (`800000..800029`):

| Tier | Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| easy | eb_naive_prior | 30 | 4.50 | +0.635 [+0.455, +0.764] | +0.665 [+0.564, +0.749] | 0.933 | 0.067 | 0.000 | 5.5 |
| easy | eb_likelihood_only | 30 | 3.77 | +0.667 [+0.483, +0.801] | +0.650 [+0.532, +0.753] | 0.933 | 0.067 | 0.000 | 4.8 |
| easy | eb_ev_stop_only | 30 | 4.83 | +0.616 [+0.438, +0.746] | +0.646 [+0.547, +0.731] | 0.933 | 0.067 | 0.000 | 5.8 |
| easy | eb_no_canary_planting | 30 | 0.00 | +0.120 [+0.030, +0.227] | +0.083 [-0.005, +0.200] | 0.167 | 0.000 | 0.833 | 7.6 |
| easy | eb_experience_opt | 30 | 4.83 | +0.729 [+0.644, +0.796] | +0.729 [+0.644, +0.796] | 0.933 | 0.000 | 0.067 | 5.2 |
| easy | heuristic | 30 | 5.50 | +0.700 [+0.665, +0.735] | +0.700 [+0.665, +0.735] | 1.000 | 0.000 | 0.000 | 6.5 |
| easy | solver | 30 | 3.73 | +0.793 [+0.748, +0.828] | +0.787 [+0.734, +0.828] | 1.000 | 0.000 | 0.000 | 4.7 |
| medium | eb_naive_prior | 30 | 3.30 | -0.945 [-1.000, -0.835] | -0.905 [-0.975, -0.816] | 0.033 | 0.967 | 0.000 | 4.3 |
| medium | eb_likelihood_only | 30 | 7.80 | +0.347 [+0.103, +0.562] | +0.332 [+0.189, +0.469] | 0.733 | 0.167 | 0.100 | 8.1 |
| medium | eb_ev_stop_only | 30 | 3.47 | -0.947 [-1.000, -0.840] | -0.915 [-0.984, -0.826] | 0.033 | 0.967 | 0.000 | 4.5 |
| medium | eb_no_canary_planting | 30 | 0.00 | -0.048 [-0.167, +0.037] | -0.038 [-0.093, +0.000] | 0.033 | 0.067 | 0.900 | 14.0 |
| medium | eb_experience_opt | 30 | 8.03 | +0.570 [+0.459, +0.669] | +0.570 [+0.459, +0.669] | 0.800 | 0.000 | 0.200 | 7.8 |
| medium | heuristic | 30 | 10.10 | +0.019 [-0.266, +0.289] | -0.007 [-0.188, +0.178] | 0.633 | 0.367 | 0.000 | 11.1 |
| medium | solver | 30 | 7.50 | +0.662 [+0.566, +0.741] | +0.662 [+0.566, +0.741] | 0.900 | 0.000 | 0.100 | 7.8 |
| hard | eb_naive_prior | 30 | 6.60 | -0.847 [-1.000, -0.677] | -0.855 [-0.969, -0.714] | 0.100 | 0.900 | 0.000 | 4.3 |
| hard | eb_likelihood_only | 30 | 15.20 | +0.007 [-0.280, +0.279] | +0.122 [-0.045, +0.280] | 0.633 | 0.367 | 0.000 | 8.6 |
| hard | eb_ev_stop_only | 30 | 7.13 | -0.854 [-1.000, -0.684] | -0.854 [-0.971, -0.713] | 0.100 | 0.900 | 0.000 | 4.6 |
| hard | eb_no_canary_planting | 30 | 0.00 | -0.003 [-0.088, +0.067] | +0.016 [+0.000, +0.041] | 0.067 | 0.033 | 0.900 | 21.0 |
| hard | eb_experience_opt | 30 | 16.13 | +0.569 [+0.517, +0.616] | +0.516 [+0.464, +0.564] | 1.000 | 0.000 | 0.000 | 9.1 |
| hard | heuristic | 30 | 25.07 | -0.132 [-0.381, +0.107] | -0.029 [-0.179, +0.108] | 0.633 | 0.367 | 0.000 | 15.5 |
| hard | solver | 30 | 11.60 | +0.590 [+0.458, +0.682] | +0.572 [+0.524, +0.618] | 0.967 | 0.033 | 0.000 | 8.2 |

4. Paired Held-Out Ablation and Before/After Deltas (95% Paired Bootstrap CI)
-----------------------------------------------------------------------------

| Scope | Comparison (After - Before) | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |
|---|---|---:|---:|
| overall 800000..800059 (n=180) | eb_likelihood_only - eb_naive_prior | +0.779 [+0.648, +0.908] | +0.723 [+0.620, +0.823] |
| overall 800000..800059 (n=180) | eb_ev_stop_only - eb_naive_prior | +0.000 [-0.011, +0.018] | +0.001 [-0.010, +0.014] |
| overall 800000..800059 (n=180) | eb_no_canary_planting - eb_naive_prior | +0.450 [+0.333, +0.563] | +0.387 [+0.273, +0.496] |
| overall 800000..800059 (n=180) | eb_experience_opt - eb_no_canary_planting | +0.579 [+0.521, +0.632] | +0.613 [+0.571, +0.654] |
| overall 800000..800059 (n=180) | eb_experience_opt - eb_ev_stop_only | +1.028 [+0.916, +1.136] | +1.000 [+0.896, +1.100] |
| overall 800000..800059 (n=180) | eb_experience_opt - eb_likelihood_only | +0.249 [+0.140, +0.357] | +0.277 [+0.210, +0.347] |
| overall 800000..800059 (n=180) | eb_experience_opt - eb_naive_prior | +1.028 [+0.915, +1.138] | +1.000 [+0.896, +1.101] |
| overall 800000..800059 (n=180) | eb_experience_opt - heuristic | +0.382 [+0.286, +0.478] | +0.397 [+0.328, +0.465] |
| overall 800000..800059 (n=180) | eb_experience_opt - solver | -0.063 [-0.116, -0.013] | -0.054 [-0.097, -0.013] |
| subset 800000..800029 (n=90) | eb_likelihood_only - eb_naive_prior | +0.726 [+0.537, +0.911] | +0.733 [+0.586, +0.879] |
| subset 800000..800029 (n=90) | eb_ev_stop_only - eb_naive_prior | -0.009 [-0.016, -0.003] | -0.009 [-0.019, +0.001] |
| subset 800000..800029 (n=90) | eb_no_canary_planting - eb_naive_prior | +0.409 [+0.237, +0.576] | +0.385 [+0.226, +0.541] |
| subset 800000..800029 (n=90) | eb_experience_opt - eb_no_canary_planting | +0.599 [+0.531, +0.671] | +0.584 [+0.522, +0.643] |
| subset 800000..800029 (n=90) | eb_experience_opt - eb_ev_stop_only | +1.017 [+0.855, +1.177] | +0.979 [+0.827, +1.129] |
| subset 800000..800029 (n=90) | eb_experience_opt - eb_likelihood_only | +0.282 [+0.133, +0.436] | +0.237 [+0.142, +0.337] |
| subset 800000..800029 (n=90) | eb_experience_opt - eb_naive_prior | +1.008 [+0.844, +1.170] | +0.970 [+0.818, +1.120] |
| subset 800000..800029 (n=90) | eb_experience_opt - heuristic | +0.427 [+0.288, +0.575] | +0.384 [+0.287, +0.485] |
| subset 800000..800029 (n=90) | eb_experience_opt - solver | -0.059 [-0.122, +0.008] | -0.069 [-0.124, -0.015] |
| easy 800000..800059 (n=60) | eb_likelihood_only - eb_naive_prior | +0.075 [-0.095, +0.246] | -0.009 [-0.119, +0.099] |
| easy 800000..800059 (n=60) | eb_ev_stop_only - eb_naive_prior | -0.017 [-0.029, -0.006] | -0.004 [-0.025, +0.027] |
| easy 800000..800059 (n=60) | eb_experience_opt - eb_no_canary_planting | +0.637 [+0.565, +0.705] | +0.732 [+0.661, +0.798] |
| easy 800000..800059 (n=60) | eb_experience_opt - eb_likelihood_only | +0.071 [-0.040, +0.202] | +0.138 [+0.049, +0.231] |
| easy 800000..800059 (n=60) | eb_experience_opt - eb_naive_prior | +0.146 [+0.033, +0.277] | +0.129 [+0.056, +0.207] |
| easy 800000..800059 (n=60) | eb_experience_opt - heuristic | +0.069 [+0.017, +0.114] | +0.069 [+0.017, +0.114] |
| medium 800000..800059 (n=60) | eb_likelihood_only - eb_naive_prior | +1.200 [+0.996, +1.388] | +1.136 [+1.012, +1.259] |
| medium 800000..800059 (n=60) | eb_ev_stop_only - eb_naive_prior | -0.001 [-0.003, +0.000] | -0.005 [-0.014, +0.000] |
| medium 800000..800059 (n=60) | eb_experience_opt - eb_no_canary_planting | +0.566 [+0.431, +0.692] | +0.611 [+0.522, +0.694] |
| medium 800000..800059 (n=60) | eb_experience_opt - eb_likelihood_only | +0.284 [+0.065, +0.518] | +0.328 [+0.183, +0.468] |
| medium 800000..800059 (n=60) | eb_experience_opt - eb_naive_prior | +1.484 [+1.363, +1.591] | +1.464 [+1.365, +1.555] |
| medium 800000..800059 (n=60) | eb_experience_opt - heuristic | +0.559 [+0.347, +0.767] | +0.647 [+0.512, +0.782] |
| hard 800000..800059 (n=60) | eb_likelihood_only - eb_naive_prior | +1.062 [+0.869, +1.245] | +1.042 [+0.922, +1.158] |
| hard 800000..800059 (n=60) | eb_ev_stop_only - eb_naive_prior | +0.018 [-0.008, +0.066] | +0.010 [-0.006, +0.035] |
| hard 800000..800059 (n=60) | eb_experience_opt - eb_no_canary_planting | +0.532 [+0.459, +0.599] | +0.497 [+0.463, +0.529] |
| hard 800000..800059 (n=60) | eb_experience_opt - eb_likelihood_only | +0.392 [+0.203, +0.593] | +0.367 [+0.260, +0.477] |
| hard 800000..800059 (n=60) | eb_experience_opt - eb_naive_prior | +1.454 [+1.336, +1.550] | +1.408 [+1.325, +1.479] |
| hard 800000..800059 (n=60) | eb_experience_opt - heuristic | +0.518 [+0.359, +0.685] | +0.475 [+0.378, +0.577] |

5. Keyless Reference Comparison on Post-Hoc Locked Dev Hard 0..29 vs Solver and Committed gemini-4-carbon (n=30)
----------------------------------------------------------------------------------------------------------------

- Seed protocol: `post-hoc locked dev hard 0..29` keyless public worlds (`b"public"`, locked after primary commitment to prevent cherry-picking; evaluated with zero LLM API calls against committed `gemini-4-carbon` episodes and in-process `solver`).

| Agent / Variant | n | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---:|---:|---:|---:|---:|---:|---:|
| eb_naive_prior | 30 | -0.846 [-1.000, -0.661] | -0.835 [-0.970, -0.666] | 0.100 | 0.900 | 0.000 | 4.0 |
| eb_likelihood_only | 30 | +0.414 [+0.224, +0.566] | +0.297 [+0.177, +0.403] | 0.900 | 0.100 | 0.000 | 9.3 |
| eb_ev_stop_only | 30 | -0.859 [-1.000, -0.685] | -0.848 [-0.970, -0.695] | 0.067 | 0.900 | 0.033 | 3.8 |
| eb_no_canary_planting | 30 | +0.010 [+0.000, +0.030] | -0.019 [-0.057, +0.000] | 0.033 | 0.000 | 0.967 | 21.0 |
| eb_experience_opt | 30 | +0.550 [+0.502, +0.597] | +0.481 [+0.432, +0.525] | 1.000 | 0.000 | 0.000 | 9.6 |
| heuristic | 30 | +0.086 [-0.123, +0.271] | +0.052 [-0.099, +0.187] | 0.800 | 0.200 | 0.000 | 14.4 |
| opencode:google/gemini-4-carbon | 30 | +0.322 [+0.116, +0.502] | +0.322 [+0.116, +0.502] | 0.833 | 0.133 | 0.033 | 13.2 |
| gemini:gemini-4-carbon | 30 | +0.473 [+0.341, +0.570] | +0.421 [+0.335, +0.503] | 0.933 | 0.033 | 0.033 | 12.7 |
| solver | 30 | +0.499 [+0.366, +0.598] | +0.499 [+0.435, +0.562] | 0.967 | 0.033 | 0.000 | 10.6 |

| Post-Hoc Locked Dev Hard 0..29 Paired Comparison | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |
|---|---:|---:|
| eb_experience_opt - eb_naive_prior | +1.396 [+1.216, +1.542] | +1.316 [+1.158, +1.447] |
| eb_experience_opt - eb_ev_stop_only | +1.410 [+1.238, +1.546] | +1.328 [+1.182, +1.449] |
| eb_experience_opt - eb_no_canary_planting | +0.540 [+0.484, +0.593] | +0.500 [+0.449, +0.547] |
| eb_experience_opt - eb_likelihood_only | +0.137 [-0.012, +0.317] | +0.184 [+0.083, +0.296] |
| eb_experience_opt - heuristic | +0.465 [+0.271, +0.677] | +0.428 [+0.301, +0.571] |
| eb_experience_opt - opencode:google/gemini-4-carbon | +0.228 [+0.039, +0.445] | +0.158 [-0.029, +0.376] |
| eb_experience_opt - gemini:gemini-4-carbon | +0.077 [-0.037, +0.224] | +0.060 [-0.033, +0.160] |
| eb_experience_opt - solver | +0.051 [-0.055, +0.197] | -0.019 [-0.076, +0.040] |

6. Stage 3 Training Search Ledger (TRAIN_SEEDS 102600..102779, Including Suboptimal Configs)
--------------------------------------------------------------------------------------------

| Phase | canary_cov | tiny_pool | tau_margin | unsurfaced_v_disc | ev_stop | Train Mean Score | Accuracy | Wrong | Abstain |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| stage2_uncalibrated_baseline_all | 0.90 | 0 | 0.00 | 0.00 | False | +0.370 | 0.806 | 0.178 | 0.017 |
| canary_split_search | 0.90 | 0 | 0.65 | 1.00 | True | +0.529 | 0.911 | 0.033 | 0.056 |
| canary_split_search | 0.65 | 3 | 0.65 | 1.00 | True | +0.604 | 0.933 | 0.033 | 0.033 |
| canary_split_search | 0.55 | 4 | 0.65 | 1.00 | True | +0.587 | 0.900 | 0.022 | 0.078 |
| canary_split_search | 0.45 | 6 | 0.65 | 1.00 | True | +0.554 | 0.878 | 0.056 | 0.067 |
| canary_split_search | 0.35 | 6 | 0.65 | 1.00 | True | +0.601 | 0.900 | 0.000 | 0.100 |
| tau_margin_search | 0.65 | 3 | 0.00 | 1.00 | True | +0.602 | 0.933 | 0.033 | 0.033 |
| tau_margin_search | 0.65 | 3 | 0.30 | 1.00 | True | +0.591 | 0.933 | 0.033 | 0.033 |
| tau_margin_search | 0.65 | 3 | 0.50 | 1.00 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| tau_margin_search | 0.65 | 3 | 0.65 | 1.00 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| tau_margin_search | 0.65 | 3 | 0.75 | 1.00 | True | +0.609 | 0.933 | 0.022 | 0.044 |
| tau_margin_search | 0.65 | 3 | 0.85 | 1.00 | True | +0.609 | 0.933 | 0.022 | 0.044 |
| unsurfaced_v_discount_search | 0.65 | 3 | 0.50 | 0.00 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| unsurfaced_v_discount_search | 0.65 | 3 | 0.50 | 0.50 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| unsurfaced_v_discount_search | 0.65 | 3 | 0.50 | 1.00 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| unsurfaced_v_discount_search | 0.65 | 3 | 0.50 | 1.25 | True | +0.610 | 0.944 | 0.022 | 0.033 |
| stage3_selected_all | 0.65 | 3 | 0.50 | 1.00 | True | +0.607 | 0.939 | 0.028 | 0.033 |
