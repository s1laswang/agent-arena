# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`medium`)
- Commit: `70c1b155ddee1cac2f39c09137c00b240be4c38f`
- Timestamp: `2026-11-15T00:12:38+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier medium --design-seeds 15,16,17,18,19 --eval-seeds 5320..5359 --n-proposals 6 --out results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s15_19`
- Design seeds: `[15, 16, 17, 18, 19]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5320..5359` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 2`
- Gemini usage: `calls=1`, `in=1649`, `out=1360`, `thinking=552`, `cached=0`, `cost_usd=0.022418`, `latency_s=59.80`

## PAIRED Design Round (`medium`, seeds `[15, 16, 17, 18, 19]`)

Default v1.4 `medium` on seeds `[15, 16, 17, 18, 19]`: `SolverPolicy = +0.672`, `ObviousHeuristic = -1.000`, `regret = +1.672`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_amplifier_seeded` | `llm` | +0.404 | n/a | n/a | unsolvable (solver < X) |
| 1 | 1 | `canary_wary_scapegoater` | `llm` | +0.600 | -1.000 | +1.600 | kept |
| 1 | 2 | `pulse_leaker_peer_blur` | `llm` | +0.414 | n/a | n/a | unsolvable (solver < X) |
| 1 | 3 | `broad_opening_decoy_trap` | `llm` | +0.232 | n/a | n/a | unsolvable (solver < X) |
| 1 | 4 | `adaptive_restriction_mirror` | `llm` | +0.490 | n/a | n/a | unsolvable (solver < X) |
| 1 | 5 | `oldest_buffer_canary_mix` | `llm` | +0.508 | -1.000 | +1.508 | kept |

### Top Kept Scenario: `canary_wary_scapegoater`
- Design-seed `SolverPolicy` mean: `+0.600` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.600`
- Rationale: Pauses for a single day when low-recipient canary-like docs pile up unless already silent for two days, then resumes random_seeded leaking. Constantly frames restricted peers or decoys under weak interview signals to mislead naive heuristics.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.22, "leak_damage": 0.05, "log_rate_mole": 1.02, "p_leak": 0.88}`
- Mole DSL rules (`3` rules): `{"rules": [{"if": [["recent_low_recipient_docs", ">=", 2.0], ["days_since_last_leak", "<", 2.0]], "then": {"frame": "decoy", "leak": null}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "decoy", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5320..5359` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.597 +/- 0.085 | +0.553 +/- 0.085 | ref | ref | ref | +0.553 | 82.5% |
| `no_ev_commit` | headline | +0.290 +/- 0.251 | -0.022 +/- 0.266 | +0.307 | +0.575 | +0.267 +/- 0.336 | +0.099 | 57.5% |
| `single_canary_per_day` | extended | +0.597 +/- 0.085 | +0.553 +/- 0.085 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.553 | 82.5% |
| `binary_canary_only` | headline | +0.542 +/- 0.101 | +0.461 +/- 0.091 | +0.055 | +0.092 | +0.037 +/- 0.121 | +0.461 | 75.0% |
| `no_log_interview_updates` | extended | +0.653 +/- 0.067 | +0.491 +/- 0.091 | -0.056 | +0.061 | +0.117 +/- 0.155 | +0.491 | 77.5% |
| `heuristic_bisection` | headline | -1.000 +/- 0.000 | -1.000 +/- 0.000 | +1.597 | +1.553 | -0.044 +/- 0.120 | -0.921 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.597 | +0.553 | -0.044 +/- 0.120 | +0.000 | 0.0% |
