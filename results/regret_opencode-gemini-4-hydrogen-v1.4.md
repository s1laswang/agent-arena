# Regret report: opencode-gemini-4-hydrogen-v1.4 [agent]

## hard (n=30): score 0.575, accuracy 100%, mean total regret 0.111, mean P(correct) at accusation 0.94

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 4 | 0.068 | 0.002 |
| premature_accusation | 1 | 0.540 | 0.018 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 28 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 19 | 147 | 21 | accuse | 0.540 | premature_accusation |
| 3 | 171 | 17 | accuse | 0.302 |  |
| 8 | 74 | 8 | accuse | 0.171 |  |
| 6 | 64 | 7 | accuse | 0.141 |  |
| 5 | 89 | 13 | accuse | 0.125 |  |
