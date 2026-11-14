# Reference solver (= Harbor oracle): expected range of the 40-task mean, easy x judge seeds 900000-900039

`uv run python scripts/solver_spread.py 300 --tier easy --seeds 40 --agent solver`: 300 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `solver` on the 40 tasks of each build.

| statistic | solver 40-task mean |
|---|---:|
| mean over builds | +0.774 |
| standard deviation over builds | 0.020 |
| median | +0.775 |
| **90% range (5th-95th percentile)** | **[+0.74, +0.80]** |
| 98% range (1st-99th percentile) | [+0.71, +0.81] |
| 99.8% range (0.1th-99.9th percentile) | [+0.69, +0.82] |
| min / max over builds | +0.69 / +0.82 |

Per episode (12000 episodes): mean +0.774, correct 99.7%, wrong accusations (-1) 0.0%, no accusation (0) 0.2%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
