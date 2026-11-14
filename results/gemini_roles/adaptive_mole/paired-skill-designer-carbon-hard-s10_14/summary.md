# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`hard`)
- Commit: `94974340ae44c96fe5eb03d797c041b95d19d922`
- Timestamp: `2026-11-14T22:40:43+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier hard --design-seeds 10,11,12,13,14 --eval-seeds 5200..5239 --n-proposals 6 --X 0.50 --Y 0.20 --out-dir results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard-s10_14`
- Design seeds: `[10, 11, 12, 13, 14]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5200..5239` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 5`
- Gemini usage: `calls=1`, `in=1645`, `out=1348`, `thinking=639`, `cached=0`, `cost_usd=0.023160`, `latency_s=60.52`

## PAIRED Design Round (`hard`, seeds `[10, 11, 12, 13, 14]`)

Default v1.4 `hard` on seeds `[10, 11, 12, 13, 14]`: `SolverPolicy = +0.376`, `ObviousHeuristic = -1.000`, `regret = +1.376`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_to_restricted_pivot` | `llm` | +0.512 | -1.000 | +1.512 | kept |
| 1 | 1 | `canary_wary_scapegoater` | `llm` | +0.488 | n/a | n/a | unsolvable (solver < X) |
| 1 | 2 | `high_tempo_decoy_flood` | `llm` | +0.566 | -1.000 | +1.566 | kept |
| 1 | 3 | `adaptive_heat_deflector` | `llm` | +0.628 | -1.000 | +1.628 | kept |
| 1 | 4 | `phased_framing_carousel` | `llm` | +0.572 | -1.000 | +1.572 | kept |
| 1 | 5 | `stealth_log_pileon` | `llm` | +0.624 | -1.000 | +1.624 | kept |

### Top Kept Scenario: `adaptive_heat_deflector`
- Design-seed `SolverPolicy` mean: `+0.628` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.628`
- Rationale: When personally restricted, takes a single-day pause after leaking and frames random peers to diffuse suspicion; otherwise leaks via random_seeded and piles framing onto the decoy to trap investigators who over-weight access logs.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.3, "leak_damage": 0.045, "log_rate_mole": 1.0, "p_leak": 0.8}`
- Mole DSL rules (`3` rules): `{"rules": [{"if": [["i_am_restricted", "==", 1.0], ["days_since_last_leak", "==", 0.0]], "then": {"frame": "random_peer", "leak": null}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "decoy", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5200..5239` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.588 +/- 0.094 | +0.497 +/- 0.142 | ref | ref | ref | +0.566 | 92.5% |
| `no_ev_commit` | headline | +0.426 +/- 0.207 | +0.339 +/- 0.229 | +0.161 | +0.158 | -0.003 +/- 0.281 | +0.191 | 77.5% |
| `single_canary_per_day` | extended | +0.573 +/- 0.094 | +0.638 +/- 0.045 | +0.015 | -0.141 | -0.156 +/- 0.198 | +0.574 | 100.0% |
| `binary_canary_only` | headline | +0.531 +/- 0.117 | +0.597 +/- 0.050 | +0.056 | -0.100 | -0.156 +/- 0.214 | +0.523 | 100.0% |
| `no_log_interview_updates` | extended | +0.540 +/- 0.083 | +0.542 +/- 0.125 | +0.048 | -0.045 | -0.093 +/- 0.191 | +0.572 | 90.0% |
| `heuristic_bisection` | headline | -0.960 +/- 0.078 | -1.000 +/- 0.000 | +1.548 | +1.497 | -0.051 +/- 0.186 | -0.958 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.588 | +0.497 | -0.090 +/- 0.169 | +0.000 | 0.0% |
