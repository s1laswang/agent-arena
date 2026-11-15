# Regret report: opencode-gemini-4-carbon-v1.3 [agent]

## hard (n=10): score 0.543, accuracy 90%, mean total regret 0.149, mean P(correct) at accusation 0.80

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 2 | 0.757 | 0.076 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 1 | 0.036 | 0.004 |
| budget_waste | 11 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 5 | 142 | 14 | accuse | 0.538 | premature_accusation |
| 9 | 132 | 13 | accuse | 0.219 | premature_accusation |
| 0 | 126 | 13 | accuse | 0.171 |  |
| 7 | 81 | 8 | accuse | 0.124 |  |
| 8 | 133 | 13 | accuse | 0.086 |  |

## medium (n=10): score 0.610, accuracy 80%, mean total regret 0.013, mean P(correct) at accusation 1.00

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 11 | 0.000 | 0.000 |
| no_accusation | 2 | 0.041 | 0.004 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 98 | 10 | (no accusation) | 0.041 | no_accusation |
| 6 | 67 | 7 | plant_canary | 0.010 |  |
| 4 | 48 | 5 | plant_canary | 0.009 |  |
| 0 | 86 | 9 | plant_canary | 0.008 |  |
| 5 | 48 | 5 | plant_canary | 0.007 |  |
