# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`medium`)
- Commit: `cec07dc8ea61d2c129dd81e249e93dec05b76983`
- Timestamp: `2026-11-14T22:54:25+00:00`
- Command: `CANARY_LLM_MAX_RETRIES=12 PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier medium --design-seeds 10,11,12,13,14 --eval-seeds 5200..5239 --n-proposals 6 --X 0.50 --Y 0.20 --out-dir results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s10_14`
- Design seeds: `[10, 11, 12, 13, 14]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5200..5239` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 6`
- Gemini usage: `calls=1`, `in=1649`, `out=1429`, `thinking=595`, `cached=0`, `cost_usd=0.023538`, `latency_s=25.31`

## PAIRED Design Round (`medium`, seeds `[10, 11, 12, 13, 14]`)

Default v1.4 `medium` on seeds `[10, 11, 12, 13, 14]`: `SolverPolicy = +0.736`, `ObviousHeuristic = -1.000`, `regret = +1.736`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_pileon_stealth` | `llm` | +0.510 | -1.000 | +1.510 | kept |
| 1 | 1 | `canary_aware_deflector` | `llm` | +0.642 | -1.000 | +1.642 | kept |
| 1 | 2 | `peer_scatter_pressure` | `llm` | +0.570 | -1.000 | +1.570 | kept |
| 1 | 3 | `restricted_scapegoat_trap` | `llm` | +0.618 | -1.000 | +1.618 | kept |
| 1 | 4 | `paced_cadence_framer` | `llm` | +0.689 | -1.000 | +1.689 | kept |
| 1 | 5 | `late_pivot_shadow` | `llm` | +0.534 | -1.000 | +1.534 | kept |

### Top Kept Scenario: `paced_cadence_framer`
- Design-seed `SolverPolicy` mean: `+0.689` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.689`
- Rationale: Maintains steady leak cadence by forcing leaks after two quiet days while occasionally picking most_recipients only on very early days before canary narrowing matures. Zero excess log rate and weak interviews punish non-canary strategies.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.21, "leak_damage": 0.046, "log_rate_mole": 1.01, "p_leak": 0.78}`
- Mole DSL rules (`4` rules): `{"rules": [{"if": [["day", "<=", 2.0], ["min_recipient_count", "<=", 4.0]], "then": {"frame": "decoy", "leak": "most_recipients"}}, {"if": [["days_since_last_leak", ">=", 2.0]], "then": {"frame": "decoy", "leak": "random_seeded"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "random_peer", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5200..5239` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.602 +/- 0.092 | +0.592 +/- 0.079 | ref | ref | ref | +0.592 | 87.5% |
| `no_ev_commit` | headline | +0.253 +/- 0.244 | +0.409 +/- 0.207 | +0.349 | +0.183 | -0.166 +/- 0.305 | +0.269 | 82.5% |
| `single_canary_per_day` | extended | +0.602 +/- 0.092 | +0.592 +/- 0.079 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.592 | 87.5% |
| `binary_canary_only` | headline | +0.449 +/- 0.103 | +0.516 +/- 0.096 | +0.153 | +0.076 | -0.077 +/- 0.148 | +0.516 | 77.5% |
| `no_log_interview_updates` | extended | +0.561 +/- 0.087 | +0.547 +/- 0.081 | +0.041 | +0.045 | +0.004 +/- 0.154 | +0.547 | 85.0% |
| `heuristic_bisection` | headline | -0.916 +/- 0.114 | -1.000 +/- 0.000 | +1.518 | +1.592 | +0.074 +/- 0.152 | -0.917 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.602 | +0.592 | -0.010 +/- 0.103 | +0.000 | 0.0% |
