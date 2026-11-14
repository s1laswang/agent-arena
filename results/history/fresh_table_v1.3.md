# Paired table: seeds 1000-1399, V mode = known, tiers v1.3

Diff = agent - solver on the same seed (paired 95% CI). Acc = correct accusations; no-acc = episodes without an accusation.

| tier | agent | mean score | ±95% | diff vs solver (paired) | acc | no-acc | mean accusation day |
|---|---|---|---|---|---|---|---|
| easy | solver | 0.760 | 0.013 | — | 99.2% | 0.8% | 5.2 |
| easy | grok_tactics | 0.691 | 0.018 | -0.070 ± 0.021 | 98.5% | 1.5% | 6.1 |
| easy | heuristic | 0.636 | 0.029 | -0.125 ± 0.029 | 97.2% | 0.0% | 6.9 |
| easy | random | -0.598 | 0.055 | -1.358 ± 0.055 | 5.8% | 30.5% | 6.2 |
| easy | stop_early | -0.840 | 0.053 | -1.600 ± 0.055 | 8.0% | 0.0% | 1.0 |
| easy | do_nothing | 0.000 | 0.000 | -0.760 ± 0.013 | 0.0% | 100.0% | — |
| medium | solver | 0.639 | 0.024 | — | 89.2% | 10.8% | 8.0 |
| medium | grok_tactics | 0.459 | 0.033 | -0.180 ± 0.040 | 76.0% | 22.8% | 8.4 |
| medium | heuristic | -0.036 | 0.078 | -0.674 ± 0.079 | 59.8% | 0.0% | 11.2 |
| medium | random | -0.640 | 0.053 | -1.279 ± 0.059 | 3.8% | 29.0% | 6.1 |
| medium | stop_early | -0.920 | 0.038 | -1.559 ± 0.045 | 4.0% | 0.0% | 1.0 |
| medium | do_nothing | 0.000 | 0.000 | -0.639 ± 0.024 | 0.0% | 100.0% | — |
| hard | solver | 0.559 | 0.040 | — | 83.5% | 12.2% | 9.6 |
| hard | grok_tactics | 0.306 | 0.042 | -0.252 ± 0.058 | 54.5% | 41.2% | 9.8 |
| hard | heuristic | -0.273 | 0.081 | -0.831 ± 0.089 | 43.8% | 0.0% | 11.7 |
| hard | random | -0.643 | 0.052 | -1.201 ± 0.065 | 3.8% | 29.2% | 6.3 |
| hard | stop_early | -0.920 | 0.038 | -1.479 ± 0.055 | 4.0% | 0.0% | 1.0 |
| hard | do_nothing | 0.000 | 0.000 | -0.559 ± 0.040 | 0.0% | 100.0% | — |
