> Reference definition (v1.3): episodes PLAYED at commit 0933805 (tiers v1.3, KNOWN_V_MODE=True); see data/runs/committed/v1.3/*/meta.json. gpt-5.5 covers a subset (medium seeds 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15; spend cap). Paired on gpt's seeds: solver medium .670 vs gpt .319 (diff .351); hard .553 vs -.003 (diff .556). Small n: indicative.

# Regret report: gpt-5.5-v1.3 [agent]

## hard (n=5): score -0.003, accuracy 60%, mean total regret 0.313, mean P(correct) at accusation 0.61

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 5 | 0.050 | 0.010 |
| premature_accusation | 2 | 1.221 | 0.244 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 19 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 15 | 115 | 14 | accuse | 0.962 | premature_accusation |
| 1 | 142 | 14 | accuse | 0.259 | premature_accusation |
| 10 | 84 | 9 | plant_canary | 0.024 | uninformative_canary |
| 10 | 113 | 11 | plant_canary | 0.017 | uninformative_canary |
| 5 | 101 | 10 | plant_canary | 0.016 |  |

## medium (n=9): score 0.319, accuracy 78%, mean total regret 0.220, mean P(correct) at accusation 0.80

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 2 | 0.045 | 0.005 |
| premature_accusation | 3 | 1.143 | 0.127 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 17 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 17 | 119 | 14 | accuse | 0.534 | premature_accusation |
| 1 | 126 | 14 | accuse | 0.454 | premature_accusation |
| 5 | 143 | 14 | accuse | 0.155 | premature_accusation |
| 17 | 51 | 7 | plant_canary | 0.045 | uninformative_canary |
| 11 | 56 | 7 | restrict_access | 0.032 |  |
