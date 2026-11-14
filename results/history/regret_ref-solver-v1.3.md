> Reference definition (v1.3): episodes PLAYED at commit 0933805 (tiers v1.3, KNOWN_V_MODE=True); see data/runs/committed/v1.3/*/meta.json. gpt-5.5 covers a subset (medium seeds 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15; spend cap). Paired on gpt's seeds: solver medium .670 vs gpt .319 (diff .351); hard .553 vs -.003 (diff .556). Small n: indicative.

# Regret report: ref-solver-v1.3 [agent]

## hard (n=20): score 0.592, accuracy 85%, mean total regret 0.047, mean P(correct) at accusation 0.91

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 1 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 3 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 7 | 89 | 12 | accuse | 0.221 |  |
| 0 | 68 | 9 | accuse | 0.210 |  |
| 6 | 45 | 6 | accuse | 0.196 |  |
| 15 | 68 | 9 | accuse | 0.092 |  |
| 5 | 89 | 12 | accuse | 0.062 |  |

## medium (n=20): score 0.717, accuracy 100%, mean total regret 0.000, mean P(correct) at accusation 1.00

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 0 | 0.000 | 0.000 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 0 | 0 | 1 | list_employees | 0.000 |  |
| 0 | 1 | 1 | status | 0.000 |  |
| 0 | 2 | 1 | list_documents | 0.000 |  |
| 0 | 3 | 1 | check_leak_feed | 0.000 |  |
| 0 | 4 | 1 | plant_canary | 0.000 |  |
