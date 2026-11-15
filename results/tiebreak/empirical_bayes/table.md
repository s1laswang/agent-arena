EmpiricalBayesPolicy Tiebreaker Report (Canary v1.4)
====================================================

- Train seed range: `102000..102779` (Stage 2 likelihoods `102000..102179`, Stage 3 stopping/splits `102600..102779`)
- Held-out eval seed range: `800000..800029` across `easy, medium, hard` (`n=30/tier`, `90` episodes/stage)
- Held-out world secret tag: `canary-tiebreak-heldout-v14-eval-01` (sha256 prefix `ebf2f09716cf`)
- Dev keyless benchmark: `hard` seeds `0..29` (`b"public"`, `n=30`, paired vs `solver` and committed `gemini-4-carbon`)
- Tool-by-tool Env replay verified: `True` (`660` episodes replayed with zero mismatches)

1. Learned Parameter Progression (theta + Stopping + Canary Split Sizing)
-------------------------------------------------------------------------

| Stage | w_canary_hit | w_canary_miss | w_doc_hit | w_after_hours | w_evasive | w_angry_msg | tau_margin | unsurfaced_v_disc | canary_cov | tiny_pool | ev_stop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| eb_naive_prior | +1.000 | -0.800 | +0.600 | +0.800 | +0.400 | +1.200 | 0.00 | 0.00 | 0.90 | 0 | False |
| eb_likelihood_learned | +1.316 | -3.783 | +7.921 | +0.122 | +0.344 | -2.362 | 0.00 | 0.00 | 0.90 | 0 | False |
| eb_experience_opt | +1.316 | -3.783 | +7.921 | +0.122 | +0.344 | -2.362 | 0.50 | 1.00 | 0.65 | 3 | True |

2. Held-Out Overall Progression (Seeds 800000..800029, n=90 Pooled Across Easy/Medium/Hard)
-------------------------------------------------------------------------------------------

| Agent / Stage | n | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---:|---:|---:|---:|---:|---:|---:|
| eb_naive_prior | 90 | -0.386 [-0.558, -0.209] | -0.365 [-0.528, -0.200] | 0.356 | 0.644 | 0.000 | 4.7 |
| eb_likelihood_learned | 90 | +0.341 [+0.193, +0.480] | +0.368 [+0.272, +0.460] | 0.767 | 0.200 | 0.033 | 7.1 |
| eb_experience_opt | 90 | +0.622 [+0.571, +0.671] | +0.605 [+0.552, +0.654] | 0.911 | 0.000 | 0.089 | 7.4 |
| heuristic | 90 | +0.196 [+0.049, +0.335] | +0.221 [+0.114, +0.326] | 0.756 | 0.244 | 0.000 | 11.0 |
| solver | 90 | +0.682 [+0.624, +0.730] | +0.673 [+0.631, +0.713] | 0.956 | 0.011 | 0.033 | 6.9 |

3. Held-Out Per-Tier Results (Seeds 800000..800029, n=30/tier)
--------------------------------------------------------------

| Tier | Agent / Stage | n | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| easy | eb_naive_prior | 30 | +0.635 [+0.455, +0.764] | +0.665 [+0.564, +0.749] | 0.933 | 0.067 | 0.000 | 5.5 |
| easy | eb_likelihood_learned | 30 | +0.667 [+0.483, +0.801] | +0.650 [+0.532, +0.753] | 0.933 | 0.067 | 0.000 | 4.8 |
| easy | eb_experience_opt | 30 | +0.729 [+0.644, +0.796] | +0.729 [+0.644, +0.796] | 0.933 | 0.000 | 0.067 | 5.2 |
| easy | heuristic | 30 | +0.700 [+0.665, +0.735] | +0.700 [+0.665, +0.735] | 1.000 | 0.000 | 0.000 | 6.5 |
| easy | solver | 30 | +0.793 [+0.748, +0.828] | +0.787 [+0.734, +0.828] | 1.000 | 0.000 | 0.000 | 4.7 |
| medium | eb_naive_prior | 30 | -0.945 [-1.000, -0.835] | -0.905 [-0.975, -0.816] | 0.033 | 0.967 | 0.000 | 4.3 |
| medium | eb_likelihood_learned | 30 | +0.347 [+0.103, +0.562] | +0.332 [+0.189, +0.469] | 0.733 | 0.167 | 0.100 | 8.1 |
| medium | eb_experience_opt | 30 | +0.570 [+0.459, +0.669] | +0.570 [+0.459, +0.669] | 0.800 | 0.000 | 0.200 | 7.8 |
| medium | heuristic | 30 | +0.019 [-0.266, +0.289] | -0.007 [-0.188, +0.178] | 0.633 | 0.367 | 0.000 | 11.1 |
| medium | solver | 30 | +0.662 [+0.566, +0.741] | +0.662 [+0.566, +0.741] | 0.900 | 0.000 | 0.100 | 7.8 |
| hard | eb_naive_prior | 30 | -0.847 [-1.000, -0.677] | -0.855 [-0.969, -0.714] | 0.100 | 0.900 | 0.000 | 4.3 |
| hard | eb_likelihood_learned | 30 | +0.007 [-0.280, +0.279] | +0.122 [-0.045, +0.280] | 0.633 | 0.367 | 0.000 | 8.6 |
| hard | eb_experience_opt | 30 | +0.569 [+0.517, +0.616] | +0.516 [+0.464, +0.564] | 1.000 | 0.000 | 0.000 | 9.1 |
| hard | heuristic | 30 | -0.132 [-0.381, +0.107] | -0.029 [-0.179, +0.108] | 0.633 | 0.367 | 0.000 | 15.5 |
| hard | solver | 30 | +0.590 [+0.458, +0.682] | +0.572 [+0.524, +0.618] | 0.967 | 0.033 | 0.000 | 8.2 |

4. Paired Held-Out Before/After Deltas (95% Paired Bootstrap CI)
----------------------------------------------------------------

| Scope | Comparison (After - Before) | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |
|---|---|---:|---:|
| overall (n=90) | eb_likelihood_learned - eb_naive_prior | +0.726 [+0.537, +0.911] | +0.733 [+0.586, +0.879] |
| overall (n=90) | eb_experience_opt - eb_likelihood_learned | +0.282 [+0.133, +0.436] | +0.237 [+0.142, +0.337] |
| overall (n=90) | eb_experience_opt - eb_naive_prior | +1.008 [+0.844, +1.170] | +0.970 [+0.818, +1.120] |
| overall (n=90) | eb_experience_opt - heuristic | +0.427 [+0.288, +0.575] | +0.384 [+0.287, +0.485] |
| overall (n=90) | eb_experience_opt - solver | -0.059 [-0.122, +0.008] | -0.069 [-0.124, -0.015] |
| easy (n=30) | eb_likelihood_learned - eb_naive_prior | +0.033 [-0.202, +0.267] | -0.015 [-0.160, +0.130] |
| easy (n=30) | eb_experience_opt - eb_likelihood_learned | +0.061 [-0.094, +0.252] | +0.079 [-0.032, +0.202] |
| easy (n=30) | eb_experience_opt - eb_naive_prior | +0.094 [-0.034, +0.257] | +0.064 [-0.025, +0.168] |
| easy (n=30) | eb_experience_opt - heuristic | +0.029 [-0.060, +0.099] | +0.029 [-0.060, +0.099] |
| medium (n=30) | eb_likelihood_learned - eb_naive_prior | +1.292 [+1.013, +1.539] | +1.237 [+1.078, +1.392] |
| medium (n=30) | eb_experience_opt - eb_likelihood_learned | +0.223 [-0.036, +0.514] | +0.238 [+0.057, +0.417] |
| medium (n=30) | eb_experience_opt - eb_naive_prior | +1.515 [+1.363, +1.644] | +1.475 [+1.346, +1.593] |
| medium (n=30) | eb_experience_opt - heuristic | +0.550 [+0.254, +0.862] | +0.577 [+0.388, +0.767] |
| hard (n=30) | eb_likelihood_learned - eb_naive_prior | +0.854 [+0.561, +1.150] | +0.977 [+0.789, +1.155] |
| hard (n=30) | eb_experience_opt - eb_likelihood_learned | +0.561 [+0.274, +0.861] | +0.394 [+0.226, +0.571] |
| hard (n=30) | eb_experience_opt - eb_naive_prior | +1.415 [+1.214, +1.577] | +1.371 [+1.213, +1.499] |
| hard (n=30) | eb_experience_opt - heuristic | +0.701 [+0.459, +0.953] | +0.545 [+0.400, +0.697] |

5. Keyless Dev Hard 0..29 Paired Comparison vs Solver and Committed gemini-4-carbon (n=30)
------------------------------------------------------------------------------------------

| Agent / Stage | n | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |
|---|---:|---:|---:|---:|---:|---:|---:|
| eb_naive_prior | 30 | -0.846 [-1.000, -0.661] | -0.835 [-0.970, -0.666] | 0.100 | 0.900 | 0.000 | 4.0 |
| eb_likelihood_learned | 30 | +0.414 [+0.224, +0.566] | +0.297 [+0.177, +0.403] | 0.900 | 0.100 | 0.000 | 9.3 |
| eb_experience_opt | 30 | +0.550 [+0.502, +0.597] | +0.481 [+0.432, +0.525] | 1.000 | 0.000 | 0.000 | 9.6 |
| heuristic | 30 | +0.086 [-0.123, +0.271] | +0.052 [-0.099, +0.187] | 0.800 | 0.200 | 0.000 | 14.4 |
| opencode:google/gemini-4-carbon | 30 | +0.322 [+0.116, +0.502] | +0.322 [+0.116, +0.502] | 0.833 | 0.133 | 0.033 | 13.2 |
| gemini:gemini-4-carbon | 30 | +0.473 [+0.341, +0.570] | +0.421 [+0.335, +0.503] | 0.933 | 0.033 | 0.033 | 12.7 |
| solver | 30 | +0.499 [+0.366, +0.598] | +0.499 [+0.435, +0.562] | 0.967 | 0.033 | 0.000 | 10.6 |

| Dev Hard Paired Comparison | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |
|---|---:|---:|
| eb_experience_opt - eb_naive_prior | +1.396 [+1.216, +1.542] | +1.316 [+1.158, +1.447] |
| eb_experience_opt - eb_likelihood_learned | +0.137 [-0.012, +0.317] | +0.184 [+0.083, +0.296] |
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
