# Head-to-Head Adversarial Clash Summary

- Role: `adaptive_mole` (`carbon_vs_carbon_clash`)
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Canary Tiers Version: `v1.4`
- Scenario: tier `medium`, seed `6`
- Commit: `8425507a2791d4c8fa449cb7fdcc744e3f4767ea`
- Timestamp: `2026-11-14T23:52:27Z`
- Command: `/tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_gemini_clash.py --llm gemini:gemini-4-carbon --tier medium --seed 6 --out results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed6`

## Episode Outcomes

| Matchup | Investigator | Mole | Score | Correct | Accused | Final Day | End Reason | Steps | Mole Leaks | Mole Frames |
| --- | --- | --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: |
| Clash | `gemini:gemini-4-carbon` | `LLMMole(gemini-4-carbon)` | +0.750 | True | `e17` | 6 | `accused` | 55 | 5 | 1 |
| Solvability Check | `SolverPolicy` | `LLMMole(gemini-4-carbon)` | +0.340 | True | `e17` | 12 | `accused` | 93 | 11 | 6 |

- Solvable under SolverPolicy: `True`
- Investigator regret vs SolverPolicy: `-0.410`

## Ledgered Token Usage

| Feature / Slice | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) | Latency (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_investigator` | 55 | 999864 | 1918 | 20705 | 816815 | 0.674012 | 1278.83 |
| `clash_mole` (vs investigator) | 5 | 3518 | 316 | 1479 | 0 | 0.024986 | 117.47 |
| `clash_mole` (vs solver) | 11 | 8085 | 759 | 2512 | 0 | 0.048880 | 250.62 |
| `clash_mole` (total) | 16 | 11603 | 1075 | 3991 | 0 | 0.073866 | 368.09 |
| **Combined Total** | **71** | **1011467** | **2993** | **24696** | **816815** | **0.747878** | **1646.92** |

## Adaptive Mole Decisions (Clash Episode)

| Day | Leak | Frame | Rejected | Reason |
| ---: | --- | --- | --- | --- |
| 1 | `d1-2` | `None` | `-` | Leaking d1-2 safely on Day 1 since 11 of 20 employees received it, minimizing individual exposure without risking a blind frame. |
| 2 | `d2-3` | `None` | `-` | Leak d2-3 as it is fresh and widely distributed among 11 recipients, minimizing personal exposure while avoiding blind framing. |
| 3 | `d3-1` | `e04` | `-` | Leak fresh d3-1 with wide distribution (11 recipients) while avoiding low-recipient c3, and frame e04 to divert attention. |
| 4 | `c4` | `None` | `-` | Leaking c4 maximizes anonymity with 12 recipients while avoiding potential canary traps like c3. |
| 5 | `c5` | `None` | `-` | Leaking c5 because it has the highest recipient count (12), minimizing exposure while no restrictions or canary traps are active. |

## Adaptive Mole Decisions (Solver Check Episode)

| Day | Leak | Frame | Rejected | Reason |
| ---: | --- | --- | --- | --- |
| 1 | `d1-2` | `None` | `-` | Leaking d1-2 on Day 1 as it has a large recipient pool of 11 out of 20 employees, minimizing personal exposure while avoiding risky blind framing. |
| 2 | `d2-3` | `e04` | `-` | Leaking fresh wide-distribution d2-3 (11 recipients) while avoiding narrower c2, and framing e04 to divert early suspicion. |
| 3 | `d3-1` | `None` | `-` | Leak d3-1 because it is fresh and has a large recipient pool of 11, avoiding the c3 canary trap while refraining from risky blind framing. |
| 4 | `d4-1` | `None` | `-` | Leaking d4-1 because its high recipient count of 10 minimizes attribution risk while avoiding the clear 3-recipient canary traps, and skipping framing avoids targeting a non-recipient. |
| 5 | `d5-4` | `None` | `-` | Leaking d5-4 is relatively safe with 11 recipients, whereas the other held documents with only 3 recipients are almost certainly canary traps. |
| 6 | `d6-1` | `e04` | `-` | Leak d6-1 because it is fresh and has the widest distribution (11 recipients), avoiding obvious 3-recipient canary traps while framing e04 to deflect intersection analysis. |
| 7 | `d7-4` | `None` | `-` | Leaking d7-4 because it is fresh and has the highest recipient count (11), avoiding the obvious canary trap c5 while keeping risk minimal without framing. |
| 8 | `d6-2` | `e05` | `-` | Leaking older widely-distributed document with 10 recipients to avoid canary traps while framing e05 to misdirect security. |
| 9 | `d8-2` | `e05` | `-` | Avoid the obvious canary trap c9 (3 recipients) and leak widely-shared d8-2 (10 recipients) while framing a colleague to misdirect security. |
| 10 | `c10` | `e00` | `-` | Leaking c10 because its very high recipient count of 17 provides maximum anonymity, while framing e00 to misdirect security. |
| 11 | `d11-1` | `e04` | `-` | Leaking a fresh, widely distributed document (8 recipients) to minimize exposure while misdirecting security onto colleague e04. |
