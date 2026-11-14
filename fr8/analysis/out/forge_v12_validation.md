# Forge hall-of-fame re-validation

- run: `/Users/silaswang/junction-aimo-team/wt/justSilas-fr8/data/fr8/j5/run-v1-0224`
- tier: hard, fresh seeds 2000–2199 (n=200)
- tier params: fingerprint_accuracy=1.0, framing_rate=3.0, n_employees=30, delay_choices=(2, 3)
- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ 0.85 (CONTRACT §7); judge candidate: feasible AND regret 95% CI lower bound > 0
- feasible: 20/20; judge candidates: hof#1, hof#2, hof#3, hof#4, hof#5, hof#6, hof#7, hof#8, hof#9, hof#10, hof#11, hof#12, hof#13, hof#14, hof#15, hof#16, hof#17, hof#18, hof#19, hof#20

| strategy | n | solver_score | solver_ci | solver_acc | solver_none | heur_score | heur_acc | regret | regret_ci | ratio_vs_default | feasible | judge_candidate | v1_fitness |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 200 | 0.610 | 0.042 | 0.860 | 0.130 | -0.238 | 0.460 | 0.849 | 0.119 | 1.000 | True | False | None |
| hof#1 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#2 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#3 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#4 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#5 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#6 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#7 | 200 | 0.676 | 0.044 | 0.885 | 0.100 | -0.822 | 0.100 | 1.498 | 0.088 | 1.108 | True | True | 1.784 |
| hof#8 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#9 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#10 | 200 | 0.677 | 0.044 | 0.885 | 0.100 | -0.865 | 0.075 | 1.542 | 0.081 | 1.109 | True | True | 1.784 |
| hof#11 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#12 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#13 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#14 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#15 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#16 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#17 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#18 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#19 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.803 | 0.110 | 1.476 | 0.091 | 1.103 | True | True | 1.784 |
| hof#20 | 200 | 0.673 | 0.045 | 0.880 | 0.105 | -0.821 | 0.100 | 1.494 | 0.088 | 1.103 | True | True | 1.784 |

## Notes
- Command: `uv run -q --python 3.12 python -m fr8.analysis.forge_validate ~/junction-aimo-team/wt/justSilas-fr8/data/fr8/j5/run-v1-0224 --tier hard --seeds 2000:2200 --workers 2 --out fr8/analysis/out/forge_v12_validation` on origin/justSilas ef99498 (TIERS_VERSION v1.2 frozen; CONTRACT §12: fingerprint_accuracy 1.0, hard framing_rate 3.0, behaviour_weight 0.6).
- Evaluated against the hall of fame as of about generation 325 (run still in progress). run-20261114-0210 was not used.
- Investigator = canary.forge.fitness default "heuristic"; episodes are built with canary.forge.fitness.make_env.
- The 20 HoF entries form 2 behavioural clusters (#1–10 except #7, and #11–20), so they are not 20 distinct judge moles. Dedupe before building the judge set.
- All are feasible: solver ratio ≈ 1.10 vs default, acc 0.880–0.885 (≥ 0.85, but thin margin). Solver no-accusation rate is 0.10–0.105, above the J1 5% target, though that is not a §7 constraint.
- Regret on v1.2 (≈ 1.48–1.54) is lower than the v1 fitness (1.78) because the v1.2 heuristic recovers some accuracy (0.075–0.11). It is still about 0.65 above the default mole's regret of 0.849.
