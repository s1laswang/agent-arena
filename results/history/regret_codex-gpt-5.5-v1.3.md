> Reference definition (v1.3): episodes PLAYED at commit 0933805 (tiers v1.3, KNOWN_V_MODE=True); see data/runs/committed/v1.3/*/meta.json. gpt-5.5 covers a subset (medium seeds 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15; spend cap). Paired on gpt's seeds: solver medium .670 vs gpt .319 (diff .351); hard .553 vs -.003 (diff .556). Small n: indicative.

# Regret report: codex-gpt-5.5-v1.3 [agent]

## hard (n=2): score 0.588, accuracy 100%, mean total regret 0.136, mean P(correct) at accusation 0.99

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 4 | 0.087 | 0.043 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 1 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 75 | 10 | restrict_access | 0.032 |  |
| 0 | 53 | 8 | plant_canary | 0.030 | uninformative_canary |
| 0 | 74 | 10 | restrict_access | 0.030 |  |
| 0 | 12 | 2 | plant_canary | 0.020 | uninformative_canary |
| 0 | 7 | 1 | plant_canary | 0.020 | uninformative_canary |

## medium (n=1): score 0.530, accuracy 100%, mean total regret 0.163, mean P(correct) at accusation 0.55

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 1 | 0.116 | 0.116 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 129 | 14 | accuse | 0.115 | premature_accusation |
| 0 | 116 | 12 | restrict_access | 0.010 |  |
| 0 | 66 | 7 | plant_canary | 0.008 |  |
| 0 | 76 | 8 | plant_canary | 0.008 |  |
| 0 | 36 | 4 | plant_canary | 0.007 |  |
