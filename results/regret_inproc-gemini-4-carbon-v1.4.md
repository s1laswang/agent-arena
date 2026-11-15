# Regret report: inproc-gemini-4-carbon-v1.4 [agent]

## hard (n=22): score 0.493, accuracy 95%, mean total regret 0.109, mean P(correct) at accusation 0.94

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 23 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 6 | 150 | 15 | accuse | 0.501 |  |
| 14 | 101 | 10 | accuse | 0.283 |  |
| 20 | 101 | 10 | accuse | 0.220 |  |
| 12 | 130 | 13 | accuse | 0.186 |  |
| 10 | 70 | 11 | accuse | 0.092 |  |

## medium (n=15): score 0.558, accuracy 80%, mean total regret 0.070, mean P(correct) at accusation 0.96

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 1 | 0.816 | 0.054 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 15 | 0.000 | 0.000 |
| no_accusation | 3 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 2 | 84 | 8 | accuse | 0.816 | premature_accusation |
| 10 | 72 | 7 | restrict_access | 0.045 |  |
| 2 | 6 | 1 | plant_canary | 0.017 |  |
| 3 | 36 | 4 | plant_canary | 0.009 |  |
| 0 | 67 | 7 | plant_canary | 0.008 |  |
