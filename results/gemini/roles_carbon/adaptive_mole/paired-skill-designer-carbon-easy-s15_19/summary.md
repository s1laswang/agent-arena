# Role 2 (adaptive_mole) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder

## Provenance
- Role: `adaptive_mole` (`paired_skill_designer`)
- Model: `gemini-4-carbon` via `canary.gemini.lab_client(..., feature="paired_designer")`
- Tiers version: `v1.4` (`easy`)
- Commit: `67132908d1c300d75834e1d1a0b70632e757b65d`
- Timestamp: `2026-11-15T00:18:28+00:00`
- Command: `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_paired_skill_designer.py --llm gemini:gemini-4-carbon --tier easy --design-seeds 15,16,17,18,19 --eval-seeds 5360..5399 --n-proposals 6 --out results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s15_19`
- Design seeds: `[15, 16, 17, 18, 19]` (`X >= 0.50` for `SolverPolicy`, `Y <= 0.20` for `ObviousHeuristic`)
- Fresh skill-ladder seeds: `5360..5399` (`n_episodes = 40` per rung)
- LLM proposal validity: `llm_ok = True`, `n_llm_valid = 6`, `n_kept = 6`
- Gemini usage: `calls=1`, `in=1641`, `out=1257`, `thinking=338`, `cached=0`, `cost_usd=0.019232`, `latency_s=25.67`

## PAIRED Design Round (`easy`, seeds `[15, 16, 17, 18, 19]`)

Default v1.4 `easy` on seeds `[15, 16, 17, 18, 19]`: `SolverPolicy = +0.816`, `ObviousHeuristic = +0.094`, `regret = +0.722`.

| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |
|---:|---:|---|---|---:|---:|---:|---|
| 1 | 0 | `decoy_magnet_seeded` | `llm` | +0.800 | -0.632 | +1.432 | kept |
| 1 | 1 | `scapegoat_pileon` | `llm` | +0.780 | -0.224 | +1.004 | kept |
| 1 | 2 | `canary_cautious_framer` | `llm` | +0.812 | -1.000 | +1.812 | kept |
| 1 | 3 | `pulsed_peer_framer` | `llm` | +0.792 | -0.244 | +1.036 | kept |
| 1 | 4 | `quiet_logs_broad_start` | `llm` | +0.774 | -0.612 | +1.386 | kept |
| 1 | 5 | `adaptive_blame_shifter` | `llm` | +0.816 | -0.632 | +1.448 | kept |

### Top Kept Scenario: `canary_cautious_framer`
- Design-seed `SolverPolicy` mean: `+0.812` (solvability gate `>= 0.50` passed)
- Design-seed `ObviousHeuristic` mean: `-1.000` (exploitability gate `<= 0.20` passed)
- Design-seed PAIRED regret: `+1.812`
- Rationale: Briefly shifts to oldest docs on early canary bursts if not starved, otherwise uses random_seeded and frames the decoy. Low log and interview signals punish non-canary strategies.
- Overridden tier knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.2, "leak_damage": 0.05, "log_rate_mole": 1.0, "p_leak": 0.8}`
- Mole DSL rules (`3` rules): `{"rules": [{"if": [["recent_low_recipient_docs", ">=", 2.0], ["days_since_last_leak", "==", 0.0], ["day", "<=", 4.0]], "then": {"frame": "decoy", "leak": "most_recipients"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"frame": "most_restricted_peer", "leak": "random_seeded"}}, {"if": [], "then": {"frame": "decoy", "leak": "random_seeded"}}]}`

## Skill-Ladder Evaluation on Fresh Seeds `5360..5399` (`n=40`)

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.782 +/- 0.029 | +0.750 +/- 0.045 | ref | ref | ref | +0.750 | 100.0% |
| `no_ev_commit` | headline | -0.110 +/- 0.294 | +0.449 +/- 0.231 | +0.892 | +0.301 | -0.591 +/- 0.425 | +0.340 | 80.0% |
| `single_canary_per_day` | extended | +0.782 +/- 0.029 | +0.750 +/- 0.045 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.750 | 100.0% |
| `binary_canary_only` | headline | +0.681 +/- 0.093 | +0.741 +/- 0.051 | +0.102 | +0.010 | -0.092 +/- 0.119 | +0.733 | 97.5% |
| `no_log_interview_updates` | extended | +0.796 +/- 0.024 | +0.714 +/- 0.052 | -0.014 | +0.036 | +0.050 +/- 0.047 | +0.714 | 100.0% |
| `heuristic_bisection` | headline | -0.474 +/- 0.254 | -1.000 +/- 0.000 | +1.256 | +1.750 | +0.494 +/- 0.261 | -0.866 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.782 | +0.750 | -0.032 +/- 0.053 | +0.000 | 0.0% |
