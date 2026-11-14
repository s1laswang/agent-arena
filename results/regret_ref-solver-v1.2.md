> Reference definition (v1.2): all episodes (gpt-5.5, solver, heuristic) were PLAYED at commit db104c9 (tiers v1.2, true V shown); see data/runs/committed/*/meta.json. Regret replayed with rules.KNOWN_V_MODE=False using the regret code on justSilas. The v1.2 reference solver = SolverPolicy at db104c9 (hard .584, medium .690 on dev seeds 0-19). v1.3 numbers use the solver at 0933805.

# Regret report: ref-solver-v1.2 [agent]

## hard (n=20): score 0.584, accuracy 85%, mean total regret 0.053, mean P(correct) at accusation 0.95

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 2 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 5 | 60 | 9 | accuse | 0.215 |  |
| 14 | 39 | 6 | accuse | 0.197 |  |
| 19 | 74 | 11 | accuse | 0.160 |  |
| 16 | 67 | 10 | accuse | 0.093 |  |
| 8 | 81 | 12 | accuse | 0.078 |  |

## medium (n=20): score 0.690, accuracy 95%, mean total regret 0.000, mean P(correct) at accusation 1.00

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 1 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 19 | 18 | 3 | plant_canary | 0.002 |  |
| 17 | 53 | 8 | plant_canary | 0.000 |  |
| 0 | 0 | 1 | list_employees | 0.000 |  |
| 0 | 1 | 1 | status | 0.000 |  |
| 0 | 2 | 1 | list_documents | 0.000 |  |
