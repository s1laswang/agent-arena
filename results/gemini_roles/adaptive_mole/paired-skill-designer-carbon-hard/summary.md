# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`hard`)
- Commit: `0e59cc10aa43f068e5fe7c1007215df1db4d10fe`
- Timestamp: `2026-11-14T17:09:30+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier hard --design-seeds 0-9 --eval-seeds 20-39 --n-proposals 6 --max-rounds 3 --X 0.45 --Y 0.20 --out-dir results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard`
- Design seeds: `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]` (`X >= 0.45` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `20..39` (`n_episodes = 20` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 6`
- Gemini usage: `calls=1`, `in=1645`, `out=1459`, `thinking=540`, `cached=0`, `cost_usd=0.023280`, `latency_s=72.48`

## PAIRED Design Round (`hard`, seeds `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`)

Default v1.4 `hard` on seeds `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`: `SolverPolicy = +0.620`, `ObviousHeuristic = -1.000`, `regret = +1.620`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_pileon_stealth` | `llm` | +0.685 | -1.000 | +1.685 | kept |
| 1 | 1 | `canary_wary_deflector` | `llm` | +0.663 | -1.000 | +1.663 | kept |
| 1 | 2 | `pulsed_scapegoat_framer` | `llm` | +0.627 | -1.000 | +1.627 | kept |
| 1 | 3 | `rotating_blame_sprinter` | `llm` | +0.689 | -1.000 | +1.689 | kept |
| 1 | 4 | `older_cache_opportunist` | `llm` | +0.667 | -1.000 | +1.667 | kept |
| 1 | 5 | `quiet_logs_false_trail` | `llm` | +0.545 | -1.000 | +1.545 | kept |

### Top Kept Scenario: `rotating_blame_sprinter`
- Design-seed `SolverPolicy` mean: `+0.689` (solvability gate `>= 0.45` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.689`
- Rationale: Applies fast leak damage at high p_leak with random_seeded selection so Bayesian canary traps converge cleanly, while cycling blame across decoy, random peers, and restricted peers across phases of the investigation to overwhelm slow policies.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.25, "leak_damage": 0.05, "log_rate_mole": 1.0, "p_leak": 0.88}`
- Mole DSL rules (`4` rules): `{"rules": [{"if": [["day", "<", 6.0]], "then": {"frame": "decoy", "leak": "random_seeded"}}, {"if": [["n_restricted_colleagues", ">", 0.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [["day", ">=", 12.0]], "then": {"frame": "decoy", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "random_peer", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `20..39` (`n=20`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.433 +/- 0.230 | +0.628 +/- 0.051 | ref | ref | ref | +0.561 | 100.0% |
| `no_ev_commit` | headline | +0.366 +/- 0.311 | +0.259 +/- 0.331 | +0.067 | +0.369 | +0.302 +/- 0.360 | +0.134 | 75.0% |
| `single_canary_per_day` | extended | +0.479 +/- 0.172 | +0.550 +/- 0.083 | -0.046 | +0.078 | +0.124 +/- 0.328 | +0.498 | 100.0% |
| `binary_canary_only` | headline | +0.541 +/- 0.088 | +0.500 +/- 0.162 | -0.108 | +0.128 | +0.236 +/- 0.238 | +0.476 | 95.0% |
| `no_log_interview_updates` | extended | +0.540 +/- 0.057 | +0.453 +/- 0.170 | -0.107 | +0.175 | +0.283 +/- 0.246 | +0.472 | 90.0% |
| `heuristic_bisection` | headline | -1.000 +/- 0.000 | -1.000 +/- 0.000 | +1.433 | +1.628 | +0.195 +/- 0.243 | -0.960 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.433 | +0.628 | +0.195 +/- 0.243 | +0.000 | 0.0% |
