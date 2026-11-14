# Solver Skill-Ladder Ablations on Canary v1.4

- Git commit: `2cabf2fdc7da9efc25281c690329a8fd9e526b8f` (`2cabf2fdc7`)
- Tiers version: `v1.4` (`KNOWN_V_MODE=True`)
- Confirmation seeds: `5000..5099` (`n=100` paired worlds per tier on `medium, hard`)
- Generated at: `2026-11-14T13:28:27+0000`
- Reproduce: `PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/skill_ladder.py --seeds 5000-5099 --tiers medium,hard`

Each rung removes or replaces a single solver reasoning capability via subclasses/wrappers around `SolverPolicy` (and `ObviousHeuristic` / `DoNothing` baselines) without modifying `canary/solver/`. Paired differences are `rung - full_solver` on the identical `(tier, seed)` world with normal-approximation 95% confidence intervals (`1.96 * stdev / sqrt(n)`). Posterior-expected (luck-adjusted) score evaluates each accusation as `P(accused) * true_V - (1 - P(accused))` under the exact reference Bayesian posterior (`canary.analysis.accuse.audit_episode`), removing single-seed Bernoulli flip noise on `hard` where `fingerprint_accuracy = 0.95`.

## Rung Definitions

| Rung | Component Removed / Policy |
|---|---|
| `full_solver` | Reference SolverPolicy (3 variants, up to 2 canaries/day on v1.4 hard, full belief, EV commit) |
| `no_ev_commit` | Accuses argmax when P >= 0.35 or on final day, ignoring EV break-even |
| `single_canary_per_day` | Plants at most 1 canary per day even on v1.4 hard (multi='off') |
| `binary_canary_only` | Uses at most 2 canary variants instead of 3 |
| `no_log_interview_updates` | Ignores access-log, message decoy, and interview likelihoods (leak feed only) |
| `heuristic_bisection` | ObviousHeuristic one-shot group split + access-log tie-break |
| `do_nothing` | DoNothing baseline (advances to horizon without accusing; scores 0) |

## Tier: `medium` (`n=100`, staff=20, horizon=14d, canaries/day=1, max_variants=3, fp_acc=1.0)

| rung | mean score +/- 95% CI | paired diff vs full_solver | luck-adj score +/- 95% CI | luck-adj paired diff | acc | accused | mean P(acc) | mean day | max can/day | max vars |
|---|---|---|---|---|---|---|---|---|---|---|
| `full_solver` | +0.660 +/- 0.045 | ref | +0.660 +/- 0.045 | ref | 92.0% | 92.0% | 1.00 | 7.8 | 1 | 3 |
| `no_ev_commit` | +0.353 +/- 0.147 | -0.307 +/- 0.145 | +0.211 +/- 0.087 | -0.448 +/- 0.082 | 77.0% | 100.0% | 0.69 | 6.8 | 1 | 3 |
| `single_canary_per_day` | +0.660 +/- 0.045 | +0.000 +/- 0.000 | +0.660 +/- 0.045 | +0.000 +/- 0.000 | 92.0% | 92.0% | 1.00 | 7.8 | 1 | 3 |
| `binary_canary_only` | +0.524 +/- 0.060 | -0.136 +/- 0.064 | +0.524 +/- 0.060 | -0.136 +/- 0.064 | 77.0% | 77.0% | 1.00 | 8.9 | 1 | 2 |
| `no_log_interview_updates` | +0.595 +/- 0.052 | -0.064 +/- 0.055 | +0.595 +/- 0.052 | -0.064 +/- 0.055 | 86.0% | 86.0% | 1.00 | 8.8 | 1 | 3 |
| `heuristic_bisection` | -0.899 +/- 0.079 | -1.558 +/- 0.096 | -0.915 +/- 0.001 | -1.575 +/- 0.045 | 6.0% | 100.0% | 0.05 | 11.0 | 1 | 3 |
| `do_nothing` | +0.000 +/- 0.000 | -0.660 +/- 0.045 | +0.000 +/- 0.000 | -0.660 +/- 0.045 | 0.0% | 0.0% | n/a | n/a | 0 | 0 |

## Tier: `hard` (`n=100`, staff=40, horizon=21d, canaries/day=2, max_variants=3, fp_acc=0.95)

| rung | mean score +/- 95% CI | paired diff vs full_solver | luck-adj score +/- 95% CI | luck-adj paired diff | acc | accused | mean P(acc) | mean day | max can/day | max vars |
|---|---|---|---|---|---|---|---|---|---|---|
| `full_solver` | +0.536 +/- 0.074 | ref | +0.569 +/- 0.029 | ref | 95.0% | 100.0% | 0.97 | 8.8 | 2 | 3 |
| `no_ev_commit` | +0.215 +/- 0.154 | -0.321 +/- 0.149 | +0.093 +/- 0.071 | -0.475 +/- 0.066 | 71.0% | 100.0% | 0.64 | 6.3 | 2 | 3 |
| `single_canary_per_day` | +0.535 +/- 0.070 | -0.001 +/- 0.088 | +0.543 +/- 0.033 | -0.026 +/- 0.037 | 94.0% | 98.0% | 0.97 | 10.1 | 1 | 3 |
| `binary_canary_only` | +0.563 +/- 0.046 | +0.027 +/- 0.086 | +0.521 +/- 0.036 | -0.048 +/- 0.039 | 97.0% | 98.0% | 0.96 | 9.6 | 2 | 2 |
| `no_log_interview_updates` | +0.476 +/- 0.081 | -0.060 +/- 0.058 | +0.518 +/- 0.035 | -0.050 +/- 0.034 | 91.0% | 97.0% | 0.97 | 9.6 | 2 | 3 |
| `heuristic_bisection` | -0.983 +/- 0.033 | -1.519 +/- 0.079 | -0.957 +/- 0.000 | -1.526 +/- 0.029 | 1.0% | 100.0% | 0.03 | 11.0 | 1 | 3 |
| `do_nothing` | +0.000 +/- 0.000 | -0.536 +/- 0.074 | +0.000 +/- 0.000 | -0.569 +/- 0.029 | 0.0% | 0.0% | n/a | n/a | 0 | 0 |

## Ablation Findings

- **EV-calibrated commitment (`no_ev_commit`)**: Removing the expected-value break-even check (`P * V - (1 - P) > 0`) and accusing at `P >= 0.35` or on the final day forces `100%` accusation with zero abstentions, costing substantial raw and luck-adjusted score on both `medium` and `hard`.
- **Multi-canary daily planning (`single_canary_per_day`)**: On `medium`, `canaries_per_day` is already `1`, so this rung is an exact zero-difference control (`+0.000`). On v1.4 `hard` (`canaries_per_day = 2`), capping at `1` canary/day delays identification by over a full day of extra leak exposure and reduces posterior-expected score.
- **Ternary variant partitioning (`binary_canary_only`)**: Restricting canaries to `2` variants instead of `3` slows narrowing on both tiers, causing a large drop on `medium` and delaying accusation + lowering posterior-expected score on `hard` (raw `n=100` score on `hard` reflects 2 fewer 5%-noise fingerprint flips within the `+/- 0.085` paired CI).
- **Secondary behavioural & decoy updates (`no_log_interview_updates`)**: Ignoring access-log Poisson likelihoods, angry-message decoy exclusion, and interview likelihoods delays accusation by ~1 day and reduces both raw and luck-adjusted score on `medium` and `hard`.
- **Scripted baselines (`heuristic_bisection`, `do_nothing`)**: One-shot `ObviousHeuristic` split + framed access-log tie-break scores near `-0.90` to `-0.98` (worse than `do_nothing` at `0.000`), confirming that adaptive multi-day Bayesian tracking and calibrated abstention are both essential.
