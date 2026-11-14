# Reference solver (= Harbor oracle): expected range of the 40-task mean, hard x judge seeds 900000-900039

`uv run python scripts/solver_spread.py 300 --tier hard --seeds 40 --agent solver`: 300 simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless `make reproduce` draw), `solver` on the 40 tasks of each build.

| statistic | solver 40-task mean |
|---|---:|
| mean over builds | +0.567 |
| standard deviation over builds | 0.050 |
| median | +0.572 |
| **90% range (5th-95th percentile)** | **[+0.49, +0.64]** |
| 98% range (1st-99th percentile) | [+0.44, +0.66] |
| 99.8% range (0.1th-99.9th percentile) | [+0.41, +0.67] |
| min / max over builds | +0.41 / +0.67 |

Per episode (12000 episodes): mean +0.567, correct 96.0%, wrong accusations (-1) 3.0%, no accusation (0) 1.1%.

do_nothing and stop_early never accuse, so they score exactly 0 on every build.
