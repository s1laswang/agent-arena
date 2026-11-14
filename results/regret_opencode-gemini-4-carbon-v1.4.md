# Regret report: opencode-gemini-4-carbon-v1.4 [agent]

## hard (n=30): score 0.322, accuracy 83%, mean total regret 0.171, mean P(correct) at accusation 0.88

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 2 | 0.804 | 0.027 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 30 | 0.000 | 0.000 |
| no_accusation | 1 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 18 | 179 | 18 | accuse | 0.488 |  |
| 20 | 111 | 11 | accuse | 0.429 |  |
| 23 | 175 | 21 | accuse | 0.422 | premature_accusation |
| 5 | 194 | 21 | accuse | 0.383 | premature_accusation |
| 14 | 82 | 8 | accuse | 0.340 |  |

## medium (n=30): score 0.713, accuracy 100%, mean total regret 0.044, mean P(correct) at accusation 0.96

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 1 | 0.157 | 0.005 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 34 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 23 | 47 | 5 | accuse | 0.572 |  |
| 29 | 142 | 14 | accuse | 0.157 | premature_accusation |
| 1 | 61 | 6 | restrict_access | 0.064 |  |
| 1 | 62 | 6 | restrict_access | 0.064 |  |
| 22 | 63 | 6 | restrict_access | 0.038 |  |
