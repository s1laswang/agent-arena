# Regret report: gpt-5.5-v1 [agent]

## hard (n=7): score 0.666, accuracy 100%, mean total regret 0.335, mean P(correct) at accusation 0.78

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 11 | 0.015 | 0.002 |
| premature_accusation | 1 | 1.605 | 0.229 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 1.605 | 0.229 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 9 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 129 | 14 | accuse | 1.605 | premature_accusation, ignored_delay |
| 7 | 51 | 6 | accuse | 0.438 |  |
| 5 | 52 | 6 | accuse | 0.024 |  |
| 0 | 87 | 10 | plant_canary | 0.015 | uninformative_canary |
| 5 | 45 | 5 | plant_canary | 0.013 |  |

## medium (n=8): score 0.015, accuracy 62%, mean total regret 0.201, mean P(correct) at accusation 0.81

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 5 | 0.114 | 0.014 |
| premature_accusation | 2 | 0.588 | 0.073 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.038 | 0.005 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 20 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 7 | 133 | 14 | accuse | 0.550 | premature_accusation |
| 4 | 41 | 5 | restrict_access | 0.070 |  |
| 4 | 40 | 5 | restrict_access | 0.067 |  |
| 6 | 61 | 8 | restrict_access | 0.047 |  |
| 5 | 112 | 14 | accuse | 0.038 | premature_accusation, ignored_delay |


# Regret report: gpt-5.5-v1 [solver]

## hard (n=7): score 0.400, accuracy 71%, mean total regret 0.058, mean P(correct) at accusation 0.92

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 1 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 5 | 60 | 9 | accuse | 0.215 |  |
| 8 | 81 | 12 | accuse | 0.078 |  |
| 1 | 53 | 8 | accuse | 0.054 |  |
| 7 | 53 | 8 | accuse | 0.039 |  |
| 0 | 74 | 11 | accuse | 0.018 |  |

## medium (n=8): score 0.629, accuracy 88%, mean total regret 0.000, mean P(correct) at accusation 1.00

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
| 0 | 0 | 1 | list_employees | 0.000 |  |
| 0 | 1 | 1 | status | 0.000 |  |
| 0 | 2 | 1 | list_documents | 0.000 |  |
| 0 | 3 | 1 | check_leak_feed | 0.000 |  |
| 0 | 4 | 1 | plant_canary | 0.000 |  |


# Regret report: gpt-5.5-v1 [heuristic]

## hard (n=7): score -0.069, accuracy 57%, mean total regret 0.583, mean P(correct) at accusation 0.51

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 5 | 3.595 | 0.514 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.589 | 0.084 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 7 | 47 | 12 | accuse | 0.796 | premature_accusation |
| 5 | 47 | 12 | accuse | 0.789 | premature_accusation |
| 1 | 47 | 12 | accuse | 0.760 | premature_accusation |
| 0 | 47 | 12 | accuse | 0.661 | premature_accusation |
| 8 | 47 | 12 | accuse | 0.589 | premature_accusation, ignored_delay |

## medium (n=8): score -0.191, accuracy 50%, mean total regret 0.601, mean P(correct) at accusation 0.65

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 5 | 3.956 | 0.494 |
| decoy_chase | 1 | 0.992 | 0.124 |
| ignored_delay | 4 | 3.067 | 0.383 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 2 | 47 | 12 | accuse | 0.992 | premature_accusation, decoy_chase, ignored_delay |
| 4 | 47 | 12 | accuse | 0.889 | premature_accusation |
| 1 | 47 | 12 | accuse | 0.711 | premature_accusation, ignored_delay |
| 5 | 47 | 12 | accuse | 0.692 | premature_accusation, ignored_delay |
| 0 | 47 | 12 | accuse | 0.672 | premature_accusation, ignored_delay |
