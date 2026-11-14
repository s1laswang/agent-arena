# Regret report: inproc-gemini-4-carbon-v1.4 [agent]

## hard (n=30): score 0.473, accuracy 93%, mean total regret 0.128, mean P(correct) at accusation 0.93

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 1 | 0.000 | 0.000 |
| premature_accusation | 1 | 0.589 | 0.020 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 30 | 0.000 | 0.000 |
| no_accusation | 1 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 22 | 174 | 17 | accuse | 0.589 | premature_accusation |
| 6 | 150 | 15 | accuse | 0.501 |  |
| 14 | 101 | 10 | accuse | 0.283 |  |
| 20 | 101 | 10 | accuse | 0.220 |  |
| 12 | 130 | 13 | accuse | 0.186 |  |

## medium (n=30): score 0.530, accuracy 83%, mean total regret 0.097, mean P(correct) at accusation 0.93

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 3 | 1.292 | 0.043 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 30 | 0.000 | 0.000 |
| no_accusation | 4 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 2 | 84 | 8 | accuse | 0.816 | premature_accusation |
| 23 | 47 | 5 | accuse | 0.590 |  |
| 11 | 140 | 14 | accuse | 0.335 | premature_accusation |
| 18 | 139 | 14 | accuse | 0.141 | premature_accusation |
| 25 | 61 | 6 | restrict_access | 0.061 |  |
