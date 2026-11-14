# Role 2: PAIRED Scenario Designer Run

- Role: `adaptive_mole` (`paired_designer`)
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Commit: `9222669912afd57e53fbd3b07f0cdba985df705d`
- Tier: `hard` (Canary `v1.4`)
- Seeds: `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`
- Solvability gate: keep iff `SolverPolicy >= 0.45` and `ObviousHeuristic <= 0.20`
- LLM output valid: `llm_ok=True`, `n_llm_valid=6/6`, `n_kept=6`
- Timestamp: `2026-11-14T17:06:51Z`
- Command: `/tmp/fleet-silas/canary-venv/bin/python scripts/run_role_designer.py --llm gemini:gemini-4-carbon --tier hard --seeds 0-9 --n 6 --rounds 3 --X 0.45 --Y 0.20 --out results/gemini_roles/adaptive_mole/paired-designer-carbon-hard`

## Gemini API Usage

- Calls: `1`
- Input tokens: `1889`
- Output tokens: `1659`
- Thinking tokens: `669`
- Cached tokens: `0`
- Total tokens: `4217`
- Estimated cost (USD): `0.027058`
- Latency (s): `30.887`

## Default Scenario Baseline (Same Seeds)

- `SolverPolicy` mean score: `+0.6200` (accuracy `100.00%`)
- `ObviousHeuristic` mean score: `-1.0000` (accuracy `0.00%`)
- Default regret (`SolverPolicy - ObviousHeuristic`): `+1.6200`

## Proposed Candidate Scenarios & Regret Filter

| # | Candidate | Source | SolverPolicy Mean | Solver Acc | ObviousHeuristic Mean | Heuristic Acc | Regret | Gate Outcome |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | `scapegoat-cascade-seeded` | `llm` | `+0.7170` | `100%` | `-1.0000` | `0%` | `+1.7170` | `kept` |
| 2 | `decoy-funnel-broad-dodge` | `llm` | `+0.6980` | `100%` | `-1.0000` | `0%` | `+1.6980` | `kept` |
| 3 | `phased-frame-shift-seeded` | `llm` | `+0.7180` | `100%` | `-1.0000` | `0%` | `+1.7180` | `kept` |
| 4 | `restricted-mirror-evasion` | `llm` | `+0.6867` | `100%` | `-1.0000` | `0%` | `+1.6867` | `kept` |
| 5 | `stale-cache-decoy-lock` | `llm` | `+0.6920` | `100%` | `-1.0000` | `0%` | `+1.6920` | `kept` |
| 6 | `crowd-cover-peer-scatter` | `llm` | `+0.5846` | `90%` | `-1.0000` | `0%` | `+1.5846` | `kept` |

## Candidate Details (Mole DSL & Clamped Knobs)

### 1. `scapegoat-cascade-seeded` (`kept`)

- Rationale: Evades narrow pinpoint traps by leaking broad or older docs when low-recipient docs accumulate, piles framing onto restricted colleagues once restrictions start, and defaults to random_seeded leaks with decoy framing so partitioned Bayesian traps work while naive heuristics chase scapegoats.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.45, "leak_damage": 0.04, "log_rate_mole": 1.0, "p_leak": 0.85}`
- Mole DSL rules: `[{"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.71`, s1=`+0.77`, s2=`+0.74`, s3=`+0.50`, s4=`+0.81`, s5=`+0.71`, s6=`+0.76`, s7=`+0.71`, s8=`+0.75`, s9=`+0.71`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`

### 2. `decoy-funnel-broad-dodge` (`kept`)

- Rationale: Dodges tiny-recipient sniper canaries via min_recipient_count checks, shifts blame from decoy early to restricted peers mid-game, and maintains high p_leak with random_seeded fallback so multi-variant Bayesian narrowing converges cleanly within 21 days.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.4, "leak_damage": 0.042, "log_rate_mole": 1.02, "p_leak": 0.88}`
- Mole DSL rules: `[{"if": [["min_recipient_count", "<=", 2.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["n_restricted_colleagues", "==", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.70`, s1=`+0.76`, s2=`+0.64`, s3=`+0.51`, s4=`+0.80`, s5=`+0.70`, s6=`+0.75`, s7=`+0.70`, s8=`+0.65`, s9=`+0.76`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`

### 3. `phased-frame-shift-seeded` (`kept`)

- Rationale: Uses early decoy framing to build false suspicion on the decoy, pivots mid-episode to framing restricted peers or random peers when heat rises, and avoids low-recipient traps by leaking oldest docs while keeping random_seeded active for broad canary partitions.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.5, "leak_damage": 0.04, "log_rate_mole": 1.0, "p_leak": 0.84}`
- Mole DSL rules: `[{"if": [["recent_low_recipient_docs", ">=", 2.0], ["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "oldest", "frame": "most_restricted_peer"}}, {"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["day", "<=", 7.0]], "then": {"leak": "random_seeded", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "random_peer"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.71`, s1=`+0.77`, s2=`+0.74`, s3=`+0.45`, s4=`+0.81`, s5=`+0.71`, s6=`+0.76`, s7=`+0.71`, s8=`+0.75`, s9=`+0.77`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`

### 4. `restricted-mirror-evasion` (`kept`)

- Rationale: Specifically counters restriction-and-watch heuristics: when under restriction or seeing restricted colleagues, the mole leaks high-recipient docs and frames restricted peers or decoys, diluting naive attribution while steady random_seeded baseline feeds Bayesian updates.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.42, "leak_damage": 0.043, "log_rate_mole": 1.05, "p_leak": 0.86}`
- Mole DSL rules: `[{"if": [["i_am_restricted", "==", 1.0], ["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["min_recipient_count", "<=", 3.0], ["recent_low_recipient_docs", ">=", 1.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 1.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.75`, s1=`+0.80`, s2=`+0.58`, s3=`+0.68`, s4=`+0.80`, s5=`+0.69`, s6=`+0.64`, s7=`+0.53`, s8=`+0.64`, s9=`+0.76`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`

### 5. `stale-cache-decoy-lock` (`kept`)

- Rationale: Exploits leak window memory by preferring oldest held documents whenever narrow canaries appear, breaking naive recency and small-set heuristics, while keeping log_rate_mole at baseline and framing decoy relentlessly before switching to restricted colleagues.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.48, "leak_damage": 0.04, "log_rate_mole": 1.0, "p_leak": 0.82}`
- Mole DSL rules: `[{"if": [["recent_low_recipient_docs", ">=", 1.0], ["min_recipient_count", "<=", 2.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [["recent_low_recipient_docs", ">=", 3.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [["n_restricted_colleagues", ">=", 2.0]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}}, {"if": [["day", ">=", 15.0]], "then": {"leak": "most_recipients", "frame": "decoy"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.71`, s1=`+0.77`, s2=`+0.46`, s3=`+0.50`, s4=`+0.82`, s5=`+0.71`, s6=`+0.71`, s7=`+0.72`, s8=`+0.75`, s9=`+0.77`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`

### 6. `crowd-cover-peer-scatter` (`kept`)

- Rationale: Blends crowd-cover leaking on high-recipient pools during sniper-canary bursts with scattered peer framing late in the game, preventing naive top-suspect lock-on while giving Bayesian multi-variant traps frequent leaks and strong interview confirmation.
- Clamped knobs: `{"careful_mole": true, "decoy": true, "framing": true, "interview_lr": 1.46, "leak_damage": 0.044, "log_rate_mole": 1.03, "p_leak": 0.89}`
- Mole DSL rules: `[{"if": [["recent_low_recipient_docs", ">=", 2.0]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}, {"if": [["min_recipient_count", "<=", 2.0]], "then": {"leak": "oldest", "frame": "decoy"}}, {"if": [["i_am_restricted", "==", 1.0]], "then": {"leak": "oldest", "frame": "most_restricted_peer"}}, {"if": [["day", ">=", 12.0], ["n_restricted_colleagues", "==", 0.0]], "then": {"leak": "random_seeded", "frame": "random_peer"}}, {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}}]`
- Per-seed `SolverPolicy` scores: s0=`+0.69`, s1=`+0.80`, s2=`+0.37`, s3=`+0.49`, s4=`+0.80`, s5=`+0.00`, s6=`+0.63`, s7=`+0.69`, s8=`+0.64`, s9=`+0.75`
- Per-seed `ObviousHeuristic` scores: s0=`-1.00`, s1=`-1.00`, s2=`-1.00`, s3=`-1.00`, s4=`-1.00`, s5=`-1.00`, s6=`-1.00`, s7=`-1.00`, s8=`-1.00`, s9=`-1.00`
