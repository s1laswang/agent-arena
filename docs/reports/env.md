# ENV report

## 02:05 status
- Done: worktree, v0 rule fields + PublicDayFacts interface (pushed justSilas-env), baselines.py v0 (untested until Env lands)
- In progress: sim-engine (Env v0, ETA 02:40), world-text (TemplateProvider ETA 02:30), bayes-solver (v1 04:00)
- Blockers: none

## 02:25 status
- **Env v0 MERGED to justSilas** (verified: make test 44 green; 1000 random episodes ~1.4s). Includes v0.2 integrity (HMAC seeds, fixed errors, accuse parity), template text, baselines (do_nothing/stop_early/random/restrict_all), rules.apply_noise.
- Baselines, 100 dev seeds, mean score easy/med/hard: do_nothing 0/0/0; stop_early .11/.04/.02; random .08/.03/.02; restrict_all .09/.03/.005
- In progress: bayes-solver (v1 04:00); next: heuristic baseline, Mole DSL

## 02:40 status
- Done (verified: 200 dev seeds): `heuristic` baseline (leak-recipient intersection + halving canary). Score/acc easy .74/99%, medium .67/96%, hard .41/59%.
- **Finding: easy/medium too easy, since an obvious heuristic nearly solves them.** Calibration must cut leak informativeness (e.g. more recipients per doc, max_variants=2 everywhere, longer delays, careful mole on medium). Will tune with solver numbers at 04:00.
- In progress: Mole DSL (sim-engine), solver v1 (bayes-solver).

## 03:20 status
- Done (verified: make test 260 passed on justSilas 744f503): solver v1 (acc 99.5/99/97.5%, score .83/.75/.72 under old scoring), regret v1, Mole DSL (default = v0 ledger on 200 seeds), contract v0.2+v0.3 (wrong accusation = -1), Forge compat (features, !=, decide(view)).
- In progress: bayes-solver: v0.3 accuse rule, DSL robustness (20 random strategies), recalibration (heuristic <=55% solver on medium, logs-only <=2x chance), ETA 05:00.
- Next: instruction.md, judge worlds (07:30), GeminiWorldText wiring.
