> Reference definition (v1.2): all episodes (gpt-5.5, solver, heuristic) were PLAYED at commit db104c9 (tiers v1.2, true V shown); see data/runs/committed/*/meta.json. Regret replayed with rules.KNOWN_V_MODE=False using the regret code on justSilas. The v1.2 reference solver = SolverPolicy at db104c9 (hard .584, medium .690 on dev seeds 0-19). v1.3 numbers use the solver at 0933805.

# Regret report: gpt-5.5-v1.2 [agent]

## hard (n=20): score 0.500, accuracy 90%, mean total regret 0.202, mean P(correct) at accusation 0.78

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 18 | 0.146 | 0.007 |
| premature_accusation | 5 | 2.120 | 0.106 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.815 | 0.041 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 44 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 15 | 106 | 14 | accuse | 0.815 | premature_accusation, ignored_delay |
| 8 | 146 | 14 | accuse | 0.801 | premature_accusation |
| 16 | 99 | 14 | accuse | 0.299 | premature_accusation |
| 2 | 65 | 9 | accuse | 0.237 |  |
| 6 | 83 | 10 | accuse | 0.210 |  |

## medium (n=20): score 0.600, accuracy 95%, mean total regret 0.121, mean P(correct) at accusation 0.95

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 4 | 0.038 | 0.002 |
| premature_accusation | 1 | 0.786 | 0.039 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.786 | 0.039 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 17 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 17 | 96 | 14 | accuse | 0.786 | premature_accusation, ignored_delay |
| 10 | 75 | 9 | accuse | 0.254 |  |
| 10 | 43 | 4 | restrict_access | 0.069 |  |
| 11 | 42 | 5 | plant_canary | 0.038 | uninformative_canary |
| 5 | 71 | 8 | plant_canary | 0.029 |  |
