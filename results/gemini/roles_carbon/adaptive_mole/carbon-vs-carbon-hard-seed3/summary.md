# Head-to-Head Adversarial Clash Summary

- Role: `adaptive_mole` (`carbon_vs_carbon_clash`)
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Canary Tiers Version: `v1.4`
- Scenario: tier `hard`, seed `3`
- Commit: `db9a94b0be86ec58859472a194d0db9c7c98d44f`
- Timestamp: `2026-11-14T18:55:13Z`
- Command: `/tmp/fleet-silas/canary-venv/bin/python scripts/run_gemini_clash.py --llm gemini:gemini-4-carbon --tier hard --seed 3 --out results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed3`

## Episode Outcomes

| Matchup | Investigator | Mole | Score | Correct | Accused | Final Day | End Reason | Steps | Mole Leaks | Mole Frames |
| --- | --- | --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: |
| Clash | `gemini:gemini-4-carbon` | `LLMMole(gemini-4-carbon)` | +0.490 | True | `e29` | 10 | `accused` | 96 | 9 | 2 |
| Solvability Check | `SolverPolicy` | `LLMMole(gemini-4-carbon)` | +0.740 | True | `e29` | 6 | `accused` | 53 | 3 | 3 |

- Solvable under SolverPolicy: `True`
- Investigator regret vs SolverPolicy: `+0.250`

## Ledgered Token Usage

| Feature / Slice | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) | Latency (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_investigator` | 96 | 3680442 | 3335 | 47701 | 3436300 | 1.342275 | 1379.93 |
| `clash_mole` (vs investigator) | 9 | 7285 | 559 | 1866 | 0 | 0.038820 | 121.10 |
| `clash_mole` (vs solver) | 5 | 3828 | 306 | 985 | 0 | 0.020566 | 37.82 |
| `clash_mole` (total) | 14 | 11113 | 865 | 2851 | 0 | 0.059386 | 158.92 |
| **Combined Total** | **110** | **3691555** | **4200** | **50552** | **3436300** | **1.401661** | **1538.86** |

## Adaptive Mole Decisions (Clash Episode)

| Day | Leak | Frame | Rejected | Reason |
| ---: | --- | --- | --- | --- |
| 1 | `d1-2` | `e00` | `-` | High recipient count of 17 provides strong anonymity on Day 1, while framing e00 diverts initial investigation focus. |
| 2 | `d1-3` | `None` | `-` | Document has a large recipient pool of 17, making it safe to leak early before security sets canary traps. |
| 3 | `d3-2` | `None` | `-` | Leaking d3-2 because it has the highest recipient count (17), minimizing attribution risk while no canary traps or restrictions are active. |
| 4 | `c3-2` | `None` | `-` | Recipient count of 12 is broad enough to avoid immediate identification while no traps or restrictions are active. |
| 5 | `d5-2` | `None` | `-` | Leaking d5-2 because it has the highest recipient count (20 out of 40 employees), minimizing attribution risk while no traps or restrictions are active. |
| 6 | `c6` | `None` | `-` | Leaking the freshest document with the widest distribution (21 recipients) minimizes attribution risk without risking a mismatched frame. |
| 7 | `c7` | `None` | `-` | Leaking c7 as it is fresh and has the largest recipient pool (22), minimizing individual suspicion without risking a failed frame. |
| 8 | `d6-3` | `e00` | `-` | Leaking d6-3 because it has the largest recipient pool (20) and no canary traps are active, while framing e00 to deflect early suspicion. |
| 9 | `d9-1` | `None` | `-` | Leaking d9-1 because it is fresh and has the highest recipient count (20), providing strong anonymity with zero trap indicators. |

## Adaptive Mole Decisions (Solver Check Episode)

| Day | Leak | Frame | Rejected | Reason |
| ---: | --- | --- | --- | --- |
| 1 | `d1-2` | `None` | `-` | Day 1 document has a broad distribution of 17 recipients, making it very safe to leak without risking a faulty frame. |
| 2 | `c2` | `e10` | `-` | Leaking a fresh, widely distributed document (17 recipients) before traps begin, while framing a colleague to misdirect early investigations. |
| 3 | `d3-2` | `e12` | `-` | Leaking a fresh document with a wide recipient pool of 17 minimizes canary risk while framing e12 diverts intersection tracking. |
| 4 | `None` | `e00` | `-` | I am restricted along with only one other colleague, so leaking another document would likely isolate me by recipient intersection; going quiet while framing a peer helps deflect immediate suspicion. |
| 5 | `None` | `None` | `-` | Going quiet to lay low and avoid generating further intersection data while currently under restriction with only one other restricted colleague. |
