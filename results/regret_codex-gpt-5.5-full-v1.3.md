# Regret report: codex-gpt-5.5-full-v1.3 [agent]

## hard (n=11): score 0.655, accuracy 100%, mean total regret 0.225, mean P(correct) at accusation 0.82

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 4 | 0.062 | 0.006 |
| premature_accusation | 2 | 1.335 | 0.121 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 4 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 8 | 70 | 11 | accuse | 0.979 | premature_accusation |
| 3 | 71 | 12 | accuse | 0.356 | premature_accusation |
| 2 | 113 | 13 | accuse | 0.079 |  |
| 4 | 38 | 5 | restrict_access | 0.069 |  |
| 4 | 40 | 5 | restrict_access | 0.060 |  |

## medium (n=11): score 0.401, accuracy 82%, mean total regret 0.362, mean P(correct) at accusation 0.72

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 1 | 0.000 | 0.000 |
| premature_accusation | 5 | 3.252 | 0.296 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 8 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 52 | 6 | accuse | 1.390 | premature_accusation |
| 7 | 65 | 9 | accuse | 0.844 | premature_accusation |
| 4 | 89 | 14 | accuse | 0.485 | premature_accusation |
| 5 | 96 | 14 | accuse | 0.332 | premature_accusation |
| 3 | 105 | 14 | accuse | 0.202 | premature_accusation |
