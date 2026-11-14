# Reference solver (= Harbor oracle): expected range of the 10-task mean, hard x judge seeds 900000-900009

`uv run python scripts/oracle_range.py 500 --tier hard --seeds 10 --agent solver`: 500 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `solver` on the 10 tasks of each build.

| statistic | solver 10-task mean |
|---|---:|
| mean over builds | +0.570 |
| standard deviation over builds | 0.093 |
| median | +0.597 |
| **90% range (5th-95th percentile)** | **[+0.40, +0.68]** |
| 98% range (1st-99th percentile) | [+0.29, +0.71] |
| 99.8% range (0.1th-99.9th percentile) | [+0.18, +0.72] |
| min / max over builds | +0.17 / +0.73 |

Per episode (5000 episodes): mean +0.570, correct 96.1%, wrong accusations (-1) 3.0%, no accusation (0) 0.9%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
