# `guess_day1`: expected range of the 40-task mean, easy x judge seeds 900000-900039

`uv run python scripts/oracle_range.py 300 --tier easy --seeds 40 --agent guess_day1`: 300 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `guess_day1` on the 40 tasks of each build.

| statistic | guess_day1 40-task mean |
|---|---:|
| mean over builds | -0.839 |
| standard deviation over builds | 0.090 |
| median | -0.850 |
| **90% range (5th-95th percentile)** | **[-0.95, -0.70]** |
| 98% range (1st-99th percentile) | [-1.00, -0.60] |
| 99.8% range (0.1th-99.9th percentile) | [-1.00, -0.56] |
| min / max over builds | -1.00 / -0.55 |

Per episode (12000 episodes): mean -0.839, correct 8.1%, wrong accusations (-1) 91.9%, no accusation (0) 0.0%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
