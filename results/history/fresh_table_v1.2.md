# Fresh-seed table, tiers v1.2 (frozen)

Reproduce: `uv run --python 3.12 python scripts/fresh_table.py 1000 1400` (dev seeds never used for tuning; v0.3 scoring).

seeds 1000-1399 (n=400)
| tier | agent | score ±95% | acc | accused |
|---|---|---|---|---|
| easy | solver | 0.760 ± 0.013 | 99.2% | 99.2% |
| easy | heuristic | 0.636 ± 0.029 | 97.2% | 100.0% |
| easy | obvious_heuristic | -0.433 ± 0.083 | 31.2% | 100.0% |
| easy | random | -0.598 ± 0.055 | 5.8% | 69.5% |
| easy | stop_early | -0.840 ± 0.053 | 8.0% | 100.0% |
| easy | do_nothing | 0.000 ± 0.000 | 0.0% | 0.0% |
| medium | solver | 0.658 ± 0.022 | 91.8% | 91.8% |
| medium | heuristic | -0.036 ± 0.078 | 59.8% | 100.0% |
| medium | obvious_heuristic | -0.940 ± 0.031 | 3.5% | 100.0% |
| medium | random | -0.640 ± 0.053 | 3.8% | 71.0% |
| medium | stop_early | -0.920 ± 0.038 | 4.0% | 100.0% |
| medium | do_nothing | 0.000 ± 0.000 | 0.0% | 0.0% |
| hard | solver | 0.539 ± 0.043 | 81.5% | 86.5% |
| hard | heuristic | -0.273 ± 0.081 | 43.8% | 100.0% |
| hard | obvious_heuristic | -0.973 ± 0.021 | 1.5% | 100.0% |
| hard | random | -0.643 ± 0.052 | 3.8% | 70.8% |
| hard | stop_early | -0.920 ± 0.038 | 4.0% | 100.0% |
| hard | do_nothing | 0.000 ± 0.000 | 0.0% | 0.0% |
