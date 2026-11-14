# ENV report

## 02:05 status
- Done: worktree, v0 rule fields + PublicDayFacts interface (pushed justSilas-env), baselines.py v0 (untested until Env lands)
- In progress: sim-engine (Env v0, ETA 02:40), world-text (TemplateProvider ETA 02:30), bayes-solver (v1 04:00)
- Blockers: none

## 02:25 status
- **Env v0 MERGED to justSilas** (verified: make test 44 green; 1000 random episodes ~1.4s). Includes v0.2 integrity (HMAC seeds, fixed errors, accuse parity), template text, baselines (do_nothing/stop_early/random/restrict_all), rules.apply_noise.
- Baselines, 100 dev seeds, mean score easy/med/hard: do_nothing 0/0/0; stop_early .11/.04/.02; random .08/.03/.02; restrict_all .09/.03/.005
- In progress: bayes-solver (v1 04:00); next: heuristic baseline, Mole DSL
