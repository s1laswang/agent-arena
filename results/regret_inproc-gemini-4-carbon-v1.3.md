# Regret report: inproc-gemini-4-carbon-v1.3 [agent]

## hard (n=10): score 0.566, accuracy 90%, mean total regret 0.283, mean P(correct) at accusation 0.72

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 2 | 0.268 | 0.027 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 7 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 6 | 92 | 9 | accuse | 0.625 |  |
| 4 | 111 | 11 | accuse | 0.526 |  |
| 1 | 113 | 11 | accuse | 0.488 |  |
| 5 | 128 | 13 | accuse | 0.315 |  |
| 0 | 97 | 11 | accuse | 0.223 |  |

## medium (n=10): score 0.553, accuracy 90%, mean total regret 0.073, mean P(correct) at accusation 0.90

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 2 | 0.375 | 0.037 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 9 | 0.000 | 0.000 |
| no_accusation | 1 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 9 | 140 | 14 | accuse | 0.242 | premature_accusation |
| 3 | 141 | 14 | accuse | 0.133 | premature_accusation |
| 4 | 78 | 8 | restrict_access | 0.048 |  |
| 4 | 79 | 8 | restrict_access | 0.044 |  |
| 9 | 86 | 9 | restrict_access | 0.027 |  |
