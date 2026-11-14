# Regret report: gpt-5.5-full-v1.3 [agent]

## hard (n=8): score 0.264, accuracy 75%, mean total regret 0.222, mean P(correct) at accusation 0.75

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 7 | 0.023 | 0.003 |
| premature_accusation | 3 | 1.178 | 0.147 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 7 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 2 | 142 | 13 | accuse | 0.901 | premature_accusation |
| 5 | 74 | 11 | accuse | 0.223 |  |
| 4 | 138 | 14 | accuse | 0.203 | premature_accusation |
| 3 | 132 | 14 | accuse | 0.074 | premature_accusation |
| 7 | 125 | 13 | accuse | 0.024 |  |

## medium (n=9): score 0.668, accuracy 100%, mean total regret 0.141, mean P(correct) at accusation 0.92

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 3 | 0.024 | 0.003 |
| premature_accusation | 1 | 0.237 | 0.026 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 11 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 6 | 141 | 13 | accuse | 0.383 |  |
| 4 | 126 | 14 | accuse | 0.238 | premature_accusation |
| 6 | 64 | 6 | restrict_access | 0.059 |  |
| 4 | 79 | 9 | restrict_access | 0.038 |  |
| 2 | 6 | 1 | plant_canary | 0.025 |  |
