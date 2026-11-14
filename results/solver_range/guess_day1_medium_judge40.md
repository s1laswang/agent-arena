# `guess_day1`: expected range of the 40-task mean, medium x judge seeds 900000-900039

`uv run python scripts/oracle_range.py 300 --tier medium --seeds 40 --agent guess_day1`: 300 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `guess_day1` on the 40 tasks of each build.

| statistic | guess_day1 40-task mean |
|---|---:|
| mean over builds | -0.906 |
| standard deviation over builds | 0.064 |
| median | -0.900 |
| **90% range (5th-95th percentile)** | **[-1.00, -0.80]** |
| 98% range (1st-99th percentile) | [-1.00, -0.75] |
| 99.8% range (0.1th-99.9th percentile) | [-1.00, -0.71] |
| min / max over builds | -1.00 / -0.70 |

Per episode (12000 episodes): mean -0.906, correct 4.7%, wrong accusations (-1) 95.3%, no accusation (0) 0.0%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
