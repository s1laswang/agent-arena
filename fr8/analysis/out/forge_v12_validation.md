# Forge hall-of-fame re-validation

- code sha: 32e2d95; TIERS_VERSION v1.2; HoF generation 378
- run: `/tmp/j5snap/run-v1-0224`
- tier: hard, fresh seeds 2000–2199 (n=200)
- tier params: fingerprint_accuracy=0.95, framing_rate=2.0, n_employees=30, delay_choices=(2, 3)
- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ 0.85 (CONTRACT §7); judge candidate: feasible AND regret 95% CI lower bound > 0
- feasible: 20/20; distinct judge-set candidates (deduped by behaviour): hof#1, hof#5, hof#7, hof#8, hof#16

## Distinct behaviours (identical per-seed mole decisions on all eval episodes = one group)

| behaviour_group | members | n_canon_in_group | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | regret | regret_ci | ratio_vs_default | feasible | judge_candidate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | default | 1 | 0.497 | 0.067 | 0.790 | 0.140 | -0.316 | 0.410 | 0.813 | 0.127 | 1.000 | False | False |
| hof#1 | hof#1, hof#2, hof#3, hof#4 | 4 | 0.623 | 0.061 | 0.880 | 0.065 | -0.777 | 0.125 | 1.400 | 0.099 | 1.255 | True | True |
| hof#5 | hof#5, hof#6 | 2 | 0.623 | 0.061 | 0.880 | 0.065 | -0.830 | 0.095 | 1.453 | 0.092 | 1.255 | True | True |
| hof#7 | hof#7, hof#11, hof#12, hof#13, hof#14, hof#15, hof#17, hof#19, hof#20 | 9 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True |
| hof#8 | hof#8, hof#9, hof#10, hof#18 | 4 | 0.623 | 0.061 | 0.880 | 0.065 | -0.891 | 0.060 | 1.514 | 0.082 | 1.255 | True | True |
| hof#16 | hof#16 | 1 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True |

## All strategies

| strategy | n | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | regret | regret_ci | ratio_vs_default | feasible | judge_candidate | v1_fitness | canon | behaviour | behaviour_group |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 200 | 0.497 | 0.067 | 0.790 | 0.140 | -0.316 | 0.410 | 0.813 | 0.127 | 1.000 | False | False | None | 6ac100ee50 | 5193e0bd52 | default |
| hof#1 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.777 | 0.125 | 1.400 | 0.099 | 1.255 | True | True | 1.788 | eab3175961 | 87df69afad | hof#1 |
| hof#2 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.777 | 0.125 | 1.400 | 0.099 | 1.255 | True | True | 1.788 | 14fc449cc5 | 87df69afad | hof#1 |
| hof#3 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.777 | 0.125 | 1.400 | 0.099 | 1.255 | True | True | 1.788 | 0afacdfdfa | 87df69afad | hof#1 |
| hof#4 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.777 | 0.125 | 1.400 | 0.099 | 1.255 | True | True | 1.788 | fa5c010bfb | 87df69afad | hof#1 |
| hof#5 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.830 | 0.095 | 1.453 | 0.092 | 1.255 | True | True | 1.788 | a1e4c66d9f | 834a6a51da | hof#5 |
| hof#6 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.830 | 0.095 | 1.453 | 0.092 | 1.255 | True | True | 1.788 | 42a6e622c8 | 834a6a51da | hof#5 |
| hof#7 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 356d907207 | 9ea7edecfd | hof#7 |
| hof#8 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.891 | 0.060 | 1.514 | 0.082 | 1.255 | True | True | 1.788 | 0add62c88f | 0b4ad9e622 | hof#8 |
| hof#9 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.891 | 0.060 | 1.514 | 0.082 | 1.255 | True | True | 1.788 | f1d4af9893 | 0b4ad9e622 | hof#8 |
| hof#10 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.891 | 0.060 | 1.514 | 0.082 | 1.255 | True | True | 1.788 | 396a4dd2b4 | 0b4ad9e622 | hof#8 |
| hof#11 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 311558455b | 9ea7edecfd | hof#7 |
| hof#12 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 05744c2caa | 9ea7edecfd | hof#7 |
| hof#13 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 84f48fe5c2 | 9ea7edecfd | hof#7 |
| hof#14 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | e1c60c6ad4 | 9ea7edecfd | hof#7 |
| hof#15 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 91f0b90b79 | 9ea7edecfd | hof#7 |
| hof#16 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 44f7790905 | 018b3e1943 | hof#16 |
| hof#17 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 30f37d5729 | 9ea7edecfd | hof#7 |
| hof#18 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.891 | 0.060 | 1.514 | 0.082 | 1.255 | True | True | 1.788 | 6677ee9986 | 0b4ad9e622 | hof#8 |
| hof#19 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 0d8c938b03 | 9ea7edecfd | hof#7 |
| hof#20 | 200 | 0.623 | 0.061 | 0.880 | 0.065 | -0.794 | 0.115 | 1.418 | 0.100 | 1.255 | True | True | 1.788 | 6742ef1aad | 9ea7edecfd | hof#7 |

## Notes
- Against the re-freeze at db104c9 (origin/justSilas bca5406 merged; code sha 32e2d95): hard fingerprint_accuracy 0.95, framing_rate 2.0. The J5 run was at generation 378 of 500 (still running). The HoF snapshot is saved as `forge_v12_hof_source_gen378.jsonl`.
- Dedupe: `canon` = sha of canonical strategy JSON (canary.forge.mutate.canonical); `behaviour` = sha of the full sequence of mole decide() outputs over all 400 eval episodes (200 seeds × solver/heuristic). All 20 entries have distinct canon hashes and fall into 5 behaviour groups.
- Solver outcomes are identical across all 5 groups (0.623 ± 0.061, acc 0.880, none rate 0.065). The groups differ only in how badly they fool the heuristic.
- **Flag:** the default mole alone fails the §7 accuracy bar on v1.2 hard (solver acc 0.79 < 0.85). The evolved moles pass at 0.88, a thin margin.
- Survivors (5, deduped, ranked by v1.2 regret) are written to `data/forge/hall_of_fame_v1.2.jsonl` (+ `.meta.json`).
