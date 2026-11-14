> Reference definition (v1.3): episodes PLAYED at commit 0933805 (tiers v1.3, KNOWN_V_MODE=True); see data/runs/committed/v1.3/*/meta.json. gpt-5.5 covers a subset (medium seeds 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15; spend cap). Paired on gpt's seeds: solver medium .670 vs gpt .319 (diff .351); hard .553 vs -.003 (diff .556). Small n: indicative.

# Regret report: ref-heuristic-v1.3 [agent]

## hard (n=20): score -0.322, accuracy 40%, mean total regret 0.697, mean P(correct) at accusation 0.40

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 17 | 12.324 | 0.616 |
| decoy_chase | 0 | 0.000 | 0.000 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 17 | 47 | 12 | accuse | 0.863 | premature_accusation |
| 18 | 47 | 12 | accuse | 0.829 | premature_accusation |
| 12 | 47 | 12 | accuse | 0.826 | premature_accusation |
| 11 | 47 | 12 | accuse | 0.825 | premature_accusation |
| 16 | 47 | 12 | accuse | 0.811 | premature_accusation |

## medium (n=20): score -0.116, accuracy 55%, mean total regret 0.618, mean P(correct) at accusation 0.60

| tag | count | value lost (sum) | per episode |
|---|---|---|---|
| uninformative_canary | 0 | 0.000 | 0.000 |
| premature_accusation | 13 | 10.330 | 0.516 |
| decoy_chase | 1 | 0.730 | 0.036 |
| ignored_delay | 0 | 0.000 | 0.000 |
| over_restriction | 0 | 0.000 | 0.000 |
| budget_waste | 0 | 0.000 | 0.000 |
| no_accusation | 0 | 0.000 | 0.000 |

Top 5 costly decisions:

| seed | t | day | action | regret | tags |
|---|---|---|---|---|---|
| 12 | 47 | 12 | accuse | 1.044 | premature_accusation |
| 7 | 47 | 12 | accuse | 1.018 | premature_accusation |
| 14 | 47 | 12 | accuse | 0.966 | premature_accusation |
| 17 | 47 | 12 | accuse | 0.870 | premature_accusation |
| 2 | 47 | 12 | accuse | 0.768 | premature_accusation |
