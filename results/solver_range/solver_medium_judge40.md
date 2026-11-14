# Reference solver (= Harbor oracle): expected range of the 40-task mean, medium x judge seeds 900000-900039

`uv run python scripts/oracle_range.py 300 --tier medium --seeds 40 --agent solver`: 300 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `solver` on the 40 tasks of each build.

| statistic | solver 40-task mean |
|---|---:|
| mean over builds | +0.630 |
| standard deviation over builds | 0.040 |
| median | +0.635 |
| **90% range (5th-95th percentile)** | **[+0.56, +0.69]** |
| 98% range (1st-99th percentile) | [+0.53, +0.71] |
| 99.8% range (0.1th-99.9th percentile) | [+0.50, +0.72] |
| min / max over builds | +0.50 / +0.72 |

Per episode (12000 episodes): mean +0.630, correct 88.1%, wrong accusations (-1) 0.1%, no accusation (0) 11.8%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
