# Regret report: opencode-gemini-4-argon-v1.4 [agent]

## hard (n=30): score 0.512, accuracy 97%, mean total regret 0.220, mean P(correct) at accusation 0.83

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 2 | 0.000 | 0.000 |
| premature_accusation | 4 | 2.828 | 0.094 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 1 | 0.948 | 0.032 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 24 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 27 | 180 | 18 | accuse | 0.948 | premature_accusation, ignored_delay |
| 8 | 91 | 14 | accuse | 0.667 | premature_accusation |
| 21 | 121 | 12 | accuse | 0.620 | premature_accusation |
| 12 | 180 | 18 | accuse | 0.593 | premature_accusation |
| 7 | 136 | 14 | accuse | 0.471 |  |
