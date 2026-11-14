# Forge hall-of-fame re-validation

- code sha: 50f4074; TIERS_VERSION v1.2; HoF generation 499
- run: `/tmp/j5final/run-v1-0224`
- tier: hard, fresh seeds 2000–2199 (n=200)
- tier params: fingerprint_accuracy=0.95, framing_rate=2.0, n_employees=30, delay_choices=(2, 3)
- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ 0.85 (CONTRACT §7); judge candidate: feasible AND regret 95% CI lower bound > 0
- feasible: 20/20; distinct judge-set candidates (deduped by behaviour): hof#1, hof#2

## Distinct behaviours (identical per-seed mole decisions on all eval episodes = one group)

| behaviour_group | members | n_canon_in_group | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | regret | regret_ci | ratio_vs_default | feasible | judge_candidate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | default | 1 | 0.497 | 0.067 | 0.790 | 0.140 | -0.316 | 0.410 | 0.813 | 0.127 | 1.000 | False | False |
| hof#1 | hof#1 | 1 | 0.617 | 0.059 | 0.855 | 0.100 | -0.777 | 0.125 | 1.393 | 0.096 | 1.241 | True | True |
| hof#2 | hof#2, hof#3, hof#4, hof#5, hof#6, hof#7, hof#8, hof#9, hof#10, hof#11, hof#12, hof#13, hof#14, hof#15, hof#16, hof#17, hof#18, hof#19, hof#20 | 19 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True |

## All strategies

| strategy | n | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | regret | regret_ci | ratio_vs_default | feasible | judge_candidate | v1_fitness | canon | behaviour | behaviour_group |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 200 | 0.497 | 0.067 | 0.790 | 0.140 | -0.316 | 0.410 | 0.813 | 0.127 | 1.000 | False | False | None | 6ac100ee50 | 5193e0bd52 | default |
| hof#1 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.777 | 0.125 | 1.393 | 0.096 | 1.241 | True | True | 1.789 | 1c84c6e27b | 73fc25cd92 | hof#1 |
| hof#2 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 5f564672db | 44d65eeac0 | hof#2 |
| hof#3 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 1a24fdf395 | 44d65eeac0 | hof#2 |
| hof#4 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 0f36317467 | 44d65eeac0 | hof#2 |
| hof#5 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 7092ebc541 | 44d65eeac0 | hof#2 |
| hof#6 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 6ce53d9996 | 44d65eeac0 | hof#2 |
| hof#7 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 2089412012 | 44d65eeac0 | hof#2 |
| hof#8 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 00f8735cdf | 44d65eeac0 | hof#2 |
| hof#9 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 932f0c8eb9 | 44d65eeac0 | hof#2 |
| hof#10 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | c406f21236 | 44d65eeac0 | hof#2 |
| hof#11 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 71d05110d0 | 44d65eeac0 | hof#2 |
| hof#12 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | c3dd5e95f1 | 44d65eeac0 | hof#2 |
| hof#13 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 5bf7cc101c | 44d65eeac0 | hof#2 |
| hof#14 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 4d7ee700a6 | 44d65eeac0 | hof#2 |
| hof#15 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 6346ca816b | 44d65eeac0 | hof#2 |
| hof#16 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 5986de8c25 | 44d65eeac0 | hof#2 |
| hof#17 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 688f5e771c | 44d65eeac0 | hof#2 |
| hof#18 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | 4d78c8737a | 44d65eeac0 | hof#2 |
| hof#19 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | abe2a244b0 | 44d65eeac0 | hof#2 |
| hof#20 | 200 | 0.617 | 0.059 | 0.855 | 0.100 | -0.893 | 0.060 | 1.510 | 0.080 | 1.241 | True | True | 1.789 | b5a18adf6d | 44d65eeac0 | hof#2 |

## Notes
- This is the final J5 hall of fame (500 gens; last log gen index 499; final best 1.789), tiers v1.2 re-freeze (hard fp 0.95, framing 2.0), code sha 50f4074. It supersedes the gen-378 result.
- Two-level dedupe: 20 distinct canonical JSONs collapse into **2 behaviour groups**. Survivors are in `data/forge/hall_of_fame_v1.2.jsonl`: rank 1 = hof#2 group (regret 1.510), rank 2 = hof#1 (regret 1.393).
- Solver outcomes are identical for both groups (0.617 ± 0.059, acc 0.855, none 0.100). The 0.855 accuracy is only just above the 0.85 bar.
- **Flag:** the default mole fails the §7 accuracy bar on v1.2 hard (0.79).
