> Reference definition (v1.2): all episodes (gpt-5.5, solver, heuristic) were PLAYED at commit db104c9 (tiers v1.2, true V shown); see data/runs/committed/*/meta.json. Regret replayed with rules.KNOWN_V_MODE=False using the regret code on justSilas. The v1.2 reference solver = SolverPolicy at db104c9 (hard .584, medium .690 on dev seeds 0-19). v1.3 numbers use the solver at 0933805.

# Regret report: ref-heuristic-v1.2 [agent]

## hard (n=20): score -0.322, accuracy 40%, mean total regret 0.693, mean P(correct) at accusation 0.40

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 17 | 12.250 | 0.613 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 2 | 1.455 | 0.073 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 17 | 47 | 12 | accuse | 0.866 | premature_accusation, ignored_delay |
| 12 | 47 | 12 | accuse | 0.828 | premature_accusation |
| 11 | 47 | 12 | accuse | 0.825 | premature_accusation |
| 7 | 47 | 12 | accuse | 0.796 | premature_accusation |
| 1 | 47 | 12 | accuse | 0.793 | premature_accusation |

## medium (n=20): score -0.116, accuracy 55%, mean total regret 0.607, mean P(correct) at accusation 0.60

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 13 | 10.128 | 0.506 |
| decoy_chase | 1 | 0.711 | 0.035 |
| ignored_delay | 5 | 3.503 | 0.175 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 12 | 47 | 12 | accuse | 1.044 | premature_accusation |
| 7 | 47 | 12 | accuse | 0.966 | premature_accusation |
| 14 | 47 | 12 | accuse | 0.940 | premature_accusation |
| 17 | 47 | 12 | accuse | 0.870 | premature_accusation |
| 2 | 47 | 12 | accuse | 0.749 | premature_accusation, ignored_delay |
