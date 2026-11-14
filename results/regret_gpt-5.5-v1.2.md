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


# Regret report: gpt-5.5-v1.2 [solver]

## hard (n=20): score 0.659, accuracy 90%, mean total regret 0.044, mean P(correct) at accusation 0.96

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.175 | 0.009 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 2 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 5 | 61 | 8 | accuse | 0.227 |  |
| 14 | 47 | 6 | accuse | 0.197 |  |
| 17 | 54 | 7 | accuse | 0.175 | ignored_delay |
| 18 | 89 | 12 | accuse | 0.059 |  |
| 1 | 61 | 8 | accuse | 0.054 |  |

## medium (n=20): score 0.723, accuracy 100%, mean total regret 0.000, mean P(correct) at accusation 1.00

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 0 | 1 | list_employees | 0.000 |  |
| 0 | 1 | 1 | status | 0.000 |  |
| 0 | 2 | 1 | list_documents | 0.000 |  |
| 0 | 3 | 1 | check_leak_feed | 0.000 |  |
| 0 | 4 | 1 | plant_canary | 0.000 |  |


# Regret report: gpt-5.5-v1.2 [heuristic]

## hard (n=20): score -0.015, accuracy 60%, mean total regret 0.611, mean P(correct) at accusation 0.42

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 16 | 10.950 | 0.547 |
| decoy_chase | 1 | 0.810 | 0.041 |
| ignored_delay | 2 | 1.455 | 0.073 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 17 | 47 | 12 | accuse | 0.866 | premature_accusation, ignored_delay |
| 12 | 47 | 12 | accuse | 0.828 | premature_accusation |
| 18 | 47 | 12 | accuse | 0.810 | premature_accusation, decoy_chase |
| 7 | 47 | 12 | accuse | 0.796 | premature_accusation |
| 5 | 47 | 12 | accuse | 0.789 | premature_accusation |

## medium (n=20): score -0.275, accuracy 45%, mean total regret 0.608, mean P(correct) at accusation 0.62

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 13 | 10.146 | 0.507 |
| decoy_chase | 2 | 1.703 | 0.085 |
| ignored_delay | 4 | 3.067 | 0.153 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 2 | 47 | 12 | accuse | 0.992 | premature_accusation, decoy_chase, ignored_delay |
| 14 | 47 | 12 | accuse | 0.940 | premature_accusation |
| 4 | 47 | 12 | accuse | 0.889 | premature_accusation |
| 17 | 47 | 12 | accuse | 0.870 | premature_accusation |
| 11 | 47 | 12 | accuse | 0.788 | premature_accusation |
