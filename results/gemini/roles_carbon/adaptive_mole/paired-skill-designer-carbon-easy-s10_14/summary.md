# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`easy`)
- Commit: `70c1b155ddee1cac2f39c09137c00b240be4c38f`
- Timestamp: `2026-11-15T00:12:37+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier easy --design-seeds 10,11,12,13,14 --eval-seeds 5280..5319 --n-proposals 6 --out results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s10_14`
- Design seeds: `[10, 11, 12, 13, 14]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5280..5319` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 6`
- Gemini usage: `calls=1`, `in=1641`, `out=1253`, `thinking=826`, `cached=0`, `cost_usd=0.024072`, `latency_s=62.58`

## PAIRED Design Round (`easy`, seeds `[10, 11, 12, 13, 14]`)

Default v1.4 `easy` on seeds `[10, 11, 12, 13, 14]`: `SolverPolicy = +0.852`, `ObviousHeuristic = -0.294`, `regret = +1.146`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_scapegoat_pivot` | `llm` | +0.740 | -1.000 | +1.740 | kept |
| 1 | 1 | `stealth_peer_deflector` | `llm` | +0.762 | -0.662 | +1.424 | kept |
| 1 | 2 | `canary_cautious_framer` | `llm` | +0.812 | -1.000 | +1.812 | kept |
| 1 | 3 | `high_tempo_decoy_blitz` | `llm` | +0.710 | -0.622 | +1.332 | kept |
| 1 | 4 | `adaptive_restriction_mimic` | `llm` | +0.814 | -1.000 | +1.814 | kept |
| 1 | 5 | `patient_frame_rotator` | `llm` | +0.875 | -1.000 | +1.875 | kept |

### Top Kept Scenario: `patient_frame_rotator`
- Design-seed `SolverPolicy` mean: `+0.875` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.875`
- Rationale: Moderate leak rate paired with weak behavioral tells and rotating frame targets creates false leads for log and interview heuristics while giving canary traps consistent random_seeded exposure across the 14-day window.
- Overridden tier knobs: `{"careful_mole": false, "decoy": true, "framing": true, "interview_lr": 1.2, "leak_damage": 0.045, "log_rate_mole": 1.0, "p_leak": 0.75}`
- Mole DSL rules (`4` rules): `{"rules": [{"if": [["days_since_last_leak", "==", 0.0], ["day", "<=", 3.0]], "then": {"frame": "decoy", "leak": null}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"frame": "decoy", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "random_peer", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5280..5319` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.762 +/- 0.052 | +0.777 +/- 0.033 | ref | ref | ref | +0.777 | 100.0% |
| `no_ev_commit` | headline | +0.041 +/- 0.296 | -0.020 +/- 0.293 | +0.721 | +0.797 | +0.076 +/- 0.442 | +0.031 | 52.5% |
| `single_canary_per_day` | extended | +0.762 +/- 0.052 | +0.777 +/- 0.033 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.777 | 100.0% |
| `binary_canary_only` | headline | +0.724 +/- 0.047 | +0.750 +/- 0.051 | +0.038 | +0.028 | -0.011 +/- 0.075 | +0.738 | 97.5% |
| `no_log_interview_updates` | extended | +0.765 +/- 0.043 | +0.715 +/- 0.071 | -0.003 | +0.063 | +0.066 +/- 0.076 | +0.705 | 92.5% |
| `heuristic_bisection` | headline | -0.335 +/- 0.285 | -0.709 +/- 0.217 | +1.097 | +1.487 | +0.390 +/- 0.363 | -0.717 | 15.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.762 | +0.777 | +0.015 +/- 0.056 | +0.000 | 0.0% |
