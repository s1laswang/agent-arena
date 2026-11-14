# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`medium`)
- Commit: `16f24a08e1fb57397ddf90a5b413b4359a5f16bc`
- Timestamp: `2026-11-14T13:48:53+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier medium --design-seeds 5,6,7,8,9 --eval-seeds 5100..5119 --n-proposals 4 --X 0.50 --Y 0.20`
- Design seeds: `[5, 6, 7, 8, 9]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5100..5119` (`n_episodes = 20` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 4`, `n_kept = 3`
- Gemini usage: `calls=1`, `in=1649`, `out=957`, `thinking=476`, `cached=0`, `cost_usd=0.017628`, `latency_s=21.97`

## PAIRED Design Round (`medium`, seeds `[5, 6, 7, 8, 9]`)

Default v1.4 `medium` on seeds `[5, 6, 7, 8, 9]`: `SolverPolicy = +0.816`, `ObviousHeuristic = -1.000`, `regret = +1.816`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_amplifier_stealth` | `llm` | +0.668 | -1.000 | +1.668 | kept |
| 1 | 1 | `restricted_scapegoat_pivot` | `llm` | +0.690 | -1.000 | +1.690 | kept |
| 1 | 2 | `canary_wary_peer_framer` | `llm` | +0.474 | n/a | n/a | unsolvable (solver < X) |
| 1 | 3 | `high_tempo_frame_rotator` | `llm` | +0.710 | -1.000 | +1.710 | kept |

### Top Kept Scenario: `high_tempo_frame_rotator`
- Design-seed `SolverPolicy` mean: `+0.710` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.710`
- Rationale: Applies high leak frequency and damage to force early mistakes from naive heuristics, rotating framing from decoy to restricted peers as the investigation progresses. Maintains consistent random_seeded selection for clean canary trap resolution.
- Overridden tier knobs: `{"careful_mole": false, "decoy": true, "framing": true, "interview_lr": 1.24, "leak_damage": 0.05, "log_rate_mole": 1.04, "p_leak": 0.88}`
- Mole DSL rules (`3` rules): `{"rules": [{"if": [["n_restricted_colleagues", ">=", 1.0], ["day", ">=", 6.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [["recent_low_recipient_docs", ">=", 2.0], ["day", "<=", 3.0]], "then": {"frame": "decoy", "leak": "oldest"}}, {"if": [], "then": {"frame": "decoy", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5100..5119` (`n=20`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.706 +/- 0.084 | +0.722 +/- 0.054 | ref | ref | ref | +0.722 | 100.0% |
| `no_ev_commit` | headline | +0.616 +/- 0.247 | +0.508 +/- 0.289 | +0.090 | +0.214 | +0.123 +/- 0.386 | +0.409 | 85.0% |
| `single_canary_per_day` | extended | +0.706 +/- 0.084 | +0.722 +/- 0.054 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.722 | 100.0% |
| `binary_canary_only` | headline | +0.626 +/- 0.127 | +0.533 +/- 0.106 | +0.080 | +0.189 | +0.110 +/- 0.151 | +0.513 | 90.0% |
| `no_log_interview_updates` | extended | +0.695 +/- 0.087 | +0.600 +/- 0.103 | +0.011 | +0.122 | +0.111 +/- 0.118 | +0.600 | 90.0% |
| `heuristic_bisection` | headline | -0.918 +/- 0.160 | -0.811 +/- 0.255 | +1.625 | +1.533 | -0.091 +/- 0.359 | -0.867 | 10.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.706 | +0.722 | +0.016 +/- 0.099 | +0.000 | 0.0% |
