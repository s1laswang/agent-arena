# Role 2: PAIRED Scenario Designer Run

- Role: `adaptive_mole` (`paired_designer`)
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Commit: `370de43c38b321bf9dbc5c04220abd90c4614466`
- Tier: `medium` (Canary `v1.4`)
- Seeds: `[0, 1, 2, 3, 4]`
- Solvability gate: keep iff `SolverPolicy >= 0.50` and `ObviousHeuristic <= 0.25`
- LLM output valid: `llm_ok=True`, `n_llm_valid=4/4`, `n_kept=3`
- Timestamp: `2026-11-14T13:59:29Z`
- Command: `/tmp/fleet-silas/canary-venv/bin/python scripts/run_role_designer.py --llm gemini:gemini-4-carbon --tier medium --seeds 0 1 2 3 4 --n 4 --X 0.50 --Y 0.25`

## Gemini API Usage

- Calls: `1`
- Input tokens: `1896`
- Output tokens: `1120`
- Thinking tokens: `680`
- Cached tokens: `0`
- Total tokens: `3696`
- Estimated cost (USD): `0.021792`
- Latency (s): `31.236`

## Default Scenario Baseline (Same Seeds)

- `SolverPolicy` mean score: `+0.6440` (accuracy `100.00%`)
- `ObviousHeuristic` mean score: `-1.0000` (accuracy `0.00%`)
- Default regret (`SolverPolicy - ObviousHeuristic`): `+1.6440`

## Proposed Candidate Scenarios & Regret Filter

| # | Candidate | Source | SolverPolicy Mean | Solver Acc | ObviousHeuristic Mean | Heuristic Acc | Regret | Gate Outcome |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | `decoy-magnet-narrow-dodge` | `llm` | `+0.1480` | `20%` | `skipped` | `-` | `-` | `unsolvable (solver < X)` |
| 2 | `pile-on-restricted-peers` | `llm` | `+0.6020` | `80%` | `-1.0000` | `0%` | `+1.6020` | `kept` |
| 3 | `phased-frame-shift-seeded` | `llm` | `+0.5800` | `80%` | `-1.0000` | `0%` | `+1.5800` | `kept` |
| 4 | `older-doc-trap-evasion` | `llm` | `+0.5410` | `80%` | `-1.0000` | `0%` | `+1.5410` | `kept` |

## Candidate Details (Mole DSL & Clamped Knobs)

### 1. `decoy-magnet-narrow-dodge` (`unsolvable (solver < X)`)

- Rationale: Dodges narrow 1-3 recipient traps via most_recipients while using random_seeded catch-all so 3-way Bayesian splits still surface. Low log_rate_mole and persistent decoy or restricted-peer framing mislead naive heuristics.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.22, "leak_damage": 0.042, "log_rate_mole": 1.02, "p_leak": 0.85}`
- Mole DSL rules: `[{"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["min_recipient_count", "<=", 3.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.00`, s1=`+0.74`, s2=`+0.00`, s3=`+0.00`, s4=`+0.00`

### 2. `pile-on-restricted-peers` (`kept`)

- Rationale: Piles framing onto any restricted colleague to lock in false-positive investigations by naive agents, evades repeated low-recipient probes, and defaults to random_seeded leaks with decoy framing for steady Bayesian solvability.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.2, "leak_damage": 0.04, "log_rate_mole": 1.0, "p_leak": 0.82}`
- Mole DSL rules: `[{"if": [["n_restricted_colleagues", ">=", 1.0], ["recent_low_recipient_docs", ">=", 1.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": null, "frame": "decoy"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.64`, s1=`+0.75`, s2=`+0.89`, s3=`+0.00`, s4=`+0.73`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`

### 3. `phased-frame-shift-seeded` (`kept`)

- Rationale: Early days focus framing on the decoy to build strong false priors; mid-to-late days shift framing onto restricted peers while dodging narrow traps, keeping high leak frequency via random_seeded for multi-variant canary solvers.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.25, "leak_damage": 0.044, "log_rate_mole": 1.05, "p_leak": 0.88}`
- Mole DSL rules: `[{"if": [["min_recipient_count", "<=", 2.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["day", "<=", 5.0]], "then": {"leak": "random_seeded", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "random_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.57`, s1=`+0.68`, s2=`+0.88`, s3=`+0.00`, s4=`+0.77`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`

### 4. `older-doc-trap-evasion` (`kept`)

- Rationale: Uses oldest leak selection when narrow-recipient docs appear so fresh targeted traps are skipped without halting leaks, paired with flat mole log rates and decoy-first framing to defeat log and heuristic investigators.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.24, "leak_damage": 0.041, "log_rate_mole": 1.03, "p_leak": 0.84}`
- Mole DSL rules: `[{"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["recent_low_recipient_docs", ">=", 1.0], ["day", ">=", 3.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["n_restricted_colleagues", "==", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.59`, s1=`+0.74`, s2=`+0.89`, s3=`+0.48`, s4=`+0.00`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`

## Skill-Ladder Holdout Evaluation on Fresh Seeds `5360..5399` (`n=40`)

Top kept scenario evaluated: `pile-on-restricted-peers` (`SolverPolicy` vs `ObviousHeuristic` and 5 ablation/baseline rungs).

| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |
|---|---|---|---|---|---|---|---|---|
| `full_solver` | headline | +0.620 +/- 0.076 | +0.516 +/- 0.107 | ref | ref | ref | +0.516 | 72.5% |
| `no_ev_commit` | headline | -0.003 +/- 0.271 | +0.119 +/- 0.274 | +0.623 | +0.398 | -0.225 +/- 0.381 | +0.056 | 62.5% |
| `single_canary_per_day` | extended | +0.620 +/- 0.076 | +0.516 +/- 0.107 | +0.000 | +0.000 | +0.000 +/- 0.000 | +0.516 | 72.5% |
| `binary_canary_only` | headline | +0.490 +/- 0.100 | +0.364 +/- 0.108 | +0.129 | +0.152 | +0.023 +/- 0.139 | +0.364 | 55.0% |
| `no_log_interview_updates` | extended | +0.489 +/- 0.107 | +0.539 +/- 0.105 | +0.130 | -0.023 | -0.153 +/- 0.146 | +0.539 | 75.0% |
| `heuristic_bisection` | headline | -0.957 +/- 0.084 | -1.000 +/- 0.000 | +1.577 | +1.516 | -0.060 +/- 0.146 | -0.916 | 0.0% |
| `do_nothing` | headline | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.620 | +0.516 | -0.103 +/- 0.117 | +0.000 | 0.0% |
