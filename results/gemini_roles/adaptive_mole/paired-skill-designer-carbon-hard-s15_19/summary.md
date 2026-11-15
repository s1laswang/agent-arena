# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`hard`)
- Commit: `cec07dc8ea61d2c129dd81e249e93dec05b76983`
- Timestamp: `2026-11-14T23:08:24+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier hard --design-seeds 15,16,17,18,19 --eval-seeds 5240..5279 --n-proposals 6 --out results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard-s15_19`
- Design seeds: `[15, 16, 17, 18, 19]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5240..5279` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 6`
- Gemini usage: `calls=1`, `in=1645`, `out=1334`, `thinking=143`, `cached=0`, `cost_usd=0.018060`, `latency_s=21.33`

## PAIRED Design Round (`hard`, seeds `[15, 16, 17, 18, 19]`)

Default v1.4 `hard` on seeds `[15, 16, 17, 18, 19]`: `SolverPolicy = +0.330`, `ObviousHeuristic = -1.000`, `regret = +1.330`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_pileon_steady` | `llm` | +0.632 | -1.000 | +1.632 | kept |
| 1 | 1 | `canary_aware_deflector` | `llm` | +0.590 | -1.000 | +1.590 | kept |
| 1 | 2 | `scattered_blame_blitz` | `llm` | +0.670 | -1.000 | +1.670 | kept |
| 1 | 3 | `restricted_turtle_trap` | `llm` | +0.628 | -1.000 | +1.628 | kept |
| 1 | 4 | `oldest_buffer_decoy` | `llm` | +0.615 | -0.640 | +1.256 | kept |
| 1 | 5 | `adaptive_scapegoat_shift` | `llm` | +0.614 | -1.000 | +1.614 | kept |

### Top Kept Scenario: `scattered_blame_blitz`
- Design-seed `SolverPolicy` mean: `+0.670` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.670`
- Rationale: High leak probability and maximum leak damage force rapid attribution, while alternating framing between decoys and random peers dilutes anomaly detection and confuses naive investigators who chase log spikes.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.2, "leak_damage": 0.05, "log_rate_mole": 1.0, "p_leak": 0.88}`
- Mole DSL rules (`3` rules): `{"rules": [{"if": [["day", "<=", 6.0]], "then": {"frame": "decoy", "leak": "random_seeded"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"frame": "random_peer", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "decoy", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5240..5279` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.498 +/- 0.141 | +0.571 +/- 0.055 | ref | ref | ref | +0.519 | 97.5% |
| `no_ev_commit` | headline | +0.142 +/- 0.251 | +0.317 +/- 0.224 | +0.356 | +0.254 | -0.102 +/- 0.333 | +0.145 | 77.5% |
| `single_canary_per_day` | extended | +0.479 +/- 0.120 | +0.493 +/- 0.118 | +0.019 | +0.078 | +0.059 +/- 0.222 | +0.510 | 95.0% |
| `binary_canary_only` | headline | +0.547 +/- 0.063 | +0.556 +/- 0.049 | -0.050 | +0.015 | +0.064 +/- 0.134 | +0.505 | 97.5% |
| `no_log_interview_updates` | extended | +0.454 +/- 0.141 | +0.552 +/- 0.089 | +0.044 | +0.018 | -0.025 +/- 0.171 | +0.524 | 97.5% |
| `heuristic_bisection` | headline | -0.960 +/- 0.078 | -1.000 +/- 0.000 | +1.458 | +1.571 | +0.113 +/- 0.148 | -0.961 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.498 | +0.571 | +0.073 +/- 0.132 | +0.000 | 0.0% |
