# Regret report: opencode-gemini-3.5-flash-v1.4 [agent]

## hard (n=30): score 0.373, accuracy 90%, mean total regret 0.448, mean P(correct) at accusation 0.71

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 51 | 1.482 | 0.049 |
| premature_accusation | 10 | 8.559 | 0.285 |
| decoy_chase | 1 | 0.882 | 0.029 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 21 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 10 | 97 | 20 | accuse | 1.217 | premature_accusation |
| 21 | 57 | 14 | accuse | 1.154 | premature_accusation |
| 18 | 63 | 16 | accuse | 0.991 | premature_accusation |
| 26 | 86 | 19 | accuse | 0.882 | premature_accusation, decoy_chase |
| 27 | 82 | 17 | accuse | 0.879 | premature_accusation |
