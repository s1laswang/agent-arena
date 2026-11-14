# Forge hall-of-fame re-validation

- code sha: 373dbf5; TIERS_VERSION v1.3; HoF generation 299
- run: `/Users/silaswang/junction-aimo-team/wt/justSilas-fr8/data/fr8/j5b/hard_v13`
- tier: hard, fresh seeds 6000–6199 (n=200)
- tier params: fingerprint_accuracy=0.95, framing_rate=2.0, n_employees=30, delay_choices=(2, 3)
- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ tier min (canary.forge.fitness.tier_defaults; hard 0.75); strict_s7: same with acc ≥ 0.85; regret = vs the strongest investigator (min over investigators); judge candidate: feasible AND regret 95% CI lower bound > 0
- feasible: 20/20; distinct judge-set candidates (deduped by behaviour): hof#1, hof#8, hof#13

## Distinct behaviours (identical per-seed mole decisions on all eval episodes = one group)

| behaviour_group | members | n_canon_in_group | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | hinted_heuristic_score | hinted_heuristic_acc | regret[heuristic] | regret_ci[heuristic] | regret[hinted_heuristic] | regret_ci[hinted_heuristic] | strongest | regret | regret_ci | ratio_vs_default | feasible | strict_s7 | judge_candidate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | default | 1 | 0.548 | 0.062 | 0.855 | 0.085 | -0.163 | 0.505 | 0.221 | 0.355 | 0.711 | 0.124 | 0.326 | 0.079 | hinted_heuristic | 0.326 | 0.079 | 1.000 | True | True | False |
| hof#1 | hof#1, hof#2, hof#3, hof#4, hof#5, hof#6, hof#7 | 7 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.716 | 0.131 | 0.467 | 0.079 | hinted_heuristic | 0.467 | 0.079 | 1.166 | True | True | True |
| hof#8 | hof#8, hof#9, hof#10, hof#11, hof#12, hof#14, hof#15, hof#16, hof#17, hof#18, hof#19, hof#20 | 12 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.716 | 0.131 | 0.470 | 0.079 | hinted_heuristic | 0.470 | 0.079 | 1.167 | True | True | True |
| hof#13 | hof#13 | 1 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.716 | 0.131 | 0.470 | 0.079 | hinted_heuristic | 0.470 | 0.079 | 1.167 | True | True | True |

## All strategies

| strategy | n | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | hinted_heuristic_score | hinted_heuristic_acc | regret | regret_ci | ratio_vs_default | feasible | strict_s7 | judge_candidate | v1_fitness | canon | behaviour | behaviour_group |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 200 | 0.548 | 0.062 | 0.855 | 0.085 | -0.163 | 0.505 | 0.221 | 0.355 | 0.326 | 0.079 | 1.000 | True | True | False | None | 6ac100ee50 | eb7c74079b | default |
| hof#1 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | 058ab154ba | 4cb45e3cfb | hof#1 |
| hof#2 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | f4245924f1 | 4cb45e3cfb | hof#1 |
| hof#3 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | ffb3d0f759 | 4cb45e3cfb | hof#1 |
| hof#4 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | 2cb9cd51e8 | 4cb45e3cfb | hof#1 |
| hof#5 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | eb8252abc9 | 4cb45e3cfb | hof#1 |
| hof#6 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | fecd83dea9 | 4cb45e3cfb | hof#1 |
| hof#7 | 200 | 0.638 | 0.064 | 0.890 | 0.045 | -0.077 | 0.535 | 0.172 | 0.260 | 0.467 | 0.079 | 1.166 | True | True | True | 0.735 | 909bbcdb31 | 4cb45e3cfb | hof#1 |
| hof#8 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 62a8873160 | fa0bc90e26 | hof#8 |
| hof#9 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | a69a1f5c58 | fa0bc90e26 | hof#8 |
| hof#10 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 259c343eb1 | fa0bc90e26 | hof#8 |
| hof#11 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | f1e3039c38 | fa0bc90e26 | hof#8 |
| hof#12 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 5e881d073f | fa0bc90e26 | hof#8 |
| hof#13 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 656df8d23c | 199fde5cd4 | hof#13 |
| hof#14 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | fd4c48c881 | fa0bc90e26 | hof#8 |
| hof#15 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 48bf12b791 | fa0bc90e26 | hof#8 |
| hof#16 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 93be981c9a | fa0bc90e26 | hof#8 |
| hof#17 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 543f9c62bf | fa0bc90e26 | hof#8 |
| hof#18 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 10139a87ee | fa0bc90e26 | hof#8 |
| hof#19 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | 2ff391af04 | fa0bc90e26 | hof#8 |
| hof#20 | 200 | 0.639 | 0.065 | 0.890 | 0.045 | -0.077 | 0.535 | 0.169 | 0.255 | 0.470 | 0.079 | 1.167 | True | True | True | 0.735 | f1da06df72 | fa0bc90e26 | hof#8 |

## Notes
- J5b final HoF (300 gens, last gen index 299), tiers v1.3, code sha 373dbf5 (includes 0933805). The J5b run itself used e411cf1.
- Two-level dedupe: 20 canonical JSONs collapse into **3 behaviour groups**. All 3 are feasible under the J5b spec (acc ≥ 0.75) and also under strict §7 (acc 0.89 ≥ 0.85).
- The strongest investigator is hinted_heuristic for every mole. Regret vs the strongest investigator on fresh seeds is 0.467–0.470 ± 0.079, versus 0.735 in-run on seeds 0–39. That suggests overfitting to the dev seeds; fresh-seed regret is still +0.14 above the default mole's 0.326.
- Groups hof#8 and hof#13 have identical outcomes but different decision traces. hof#1 differs only marginally from them. On these numbers the 3 groups are effectively 1–2 practically distinct moles.
- The default mole passes strict §7 on v1.3 hard (solver acc 0.855).
