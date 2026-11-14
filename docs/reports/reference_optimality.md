# Is the v1.4 reference solver near-optimal?

This report shows that the v1.4 reference `solver` stops at the right time and its posterior is calibrated. Its hard-tier score is limited by how fast canary leaks bring in information, not by its decision rule. A stronger reference built on the same rules (`solver_v2`) did not clear the +0.08 bar on hard.

- **Tuning/diagnosis seeds:** dev seeds 8000-8399, n=400 per tier. All tuning used only seeds in 8000-8799.
- **Fresh evaluation seeds:** 9000-9399.
- **How the numbers were produced:** the tables come from `scripts/reference_optimality.py`. It runs the unchanged `solver` with stopping disabled; the canary plan does not depend on the threshold, so any stopping rule can be replayed offline. It reads the mole identity and the true V afterwards, only to grade the runs.
- **Commands:**
  - `uv run --python 3.12 --extra dev python scripts/reference_optimality.py --tier hard --seed0 8000 --seeds 400`
  - The same command with `--tier medium`.

## Summary
1. **Calibration.** The posterior is calibrated: the top suspect's posterior matches its empirical accuracy, and at accusation the accuracy on hard is 96-99%.
2. **Stopping.** No stopping rule we tried does better. The best rule of the form p ≥ a + b·V adds only **+0.005 on hard** and **+0.004 on medium**. Stopping with perfect knowledge of the mole would add +0.18, but no agent can do that.
3. **Where hard loses.** The loss is V drained while information accumulates: **leak damage 0.250** plus **canary cost 0.120**, out of a total loss of 0.422.
   - Within a department, only canary leaks can separate the suspects.
   - The mole holds about **3.6 regular docs** but only **1.2 of our canaries** in its leak window, so only about a fifth of its leaks are canaries.
   - That works out to about 0.13 informative canary leaks per day, and each one surfaces 2-3 days later.

## Hard
### Calibration at accusation

| posterior bin | n | empirical accuracy |
|---|---|---|
| 0.85-0.90 | 45 | 0.956 |
| 0.90-0.95 | 59 | 0.966 |
| 0.95-1.00 | 291 | 0.986 |

### Calibration over all decision days (top suspect)

| bin | n | P(top = mole) |
|---|---|---|
| 0.0-0.1 | 1258 | 0.052 |
| 0.1-0.2 | 435 | 0.193 |
| 0.2-0.3 | 348 | 0.325 |
| 0.3-0.4 | 224 | 0.455 |
| 0.4-0.5 | 258 | 0.558 |
| 0.5-0.6 | 285 | 0.618 |
| 0.6-0.7 | 251 | 0.749 |
| 0.7-0.8 | 216 | 0.861 |
| 0.8-0.9 | 182 | 0.912 |
| 0.9-1.0 | 4943 | 0.996 |

### Loss decomposition (1 - mean score = 0.422)

| bucket | loss | note |
|---|---|---|
| canary cost (correct accusations) | 0.120 | mean canaries 12.4 |
| leak damage (+ restrictions) before a correct accusation | 0.250 | |
| wrong accusations | 0.040 | 8/400 episodes, each 1 - (-1) = full loss |
| abstains (score 0) | 0.013 | 5/400 episodes |
| canary cost, all episodes (for reference) | 0.122 | |

### Stopping-rule sweep (same trajectories)

| rule | mean | Δ vs default |
|---|---|---|
| p ≥ 0.6 | 0.503 | -0.075 |
| p ≥ 0.7 | 0.571 | -0.007 |
| p ≥ 0.8 | 0.574 | -0.003 |
| p ≥ 0.85 | 0.578 | +0.000 |
| p ≥ 0.9 | 0.570 | -0.008 |
| p ≥ 0.95 | 0.562 | -0.016 |
| best p ≥ a + b·V (grid a 0.50..0.95, b -0.4..0.4) a=0.7 b=0.1 | 0.582 | +0.005 |
| oracle stop (knows the mole; upper bound, not achievable) | 0.759 | +0.181 |

### Information rate (days ≥ 3, all decision days)

- regular docs the mole can leak on a given day: mean 3.57
- our canaries the mole holds in its leak window: mean 1.23
- p_leak 0.65, canaries/day 2, variants 3, delays (2, 3), careful mole True

## Medium
### Calibration at accusation

| posterior bin | n | empirical accuracy |
|---|---|---|
| 0.65-0.70 | 1 | 0.000 |
| 0.95-1.00 | 350 | 1.000 |

### Calibration over all decision days (top suspect)

| bin | n | P(top = mole) |
|---|---|---|
| 0.0-0.1 | 997 | 0.055 |
| 0.1-0.2 | 858 | 0.197 |
| 0.2-0.3 | 499 | 0.257 |
| 0.3-0.4 | 170 | 0.382 |
| 0.4-0.5 | 71 | 0.676 |
| 0.5-0.6 | 510 | 0.622 |
| 0.6-0.7 | 90 | 0.756 |
| 0.7-0.8 | 15 | 0.933 |
| 0.8-0.9 | 7 | 1.000 |
| 0.9-1.0 | 2383 | 1.000 |

### Loss decomposition (1 - mean score = 0.379)

| bucket | loss | note |
|---|---|---|
| canary cost (correct accusations) | 0.063 | mean canaries 7.2 |
| leak damage (+ restrictions) before a correct accusation | 0.189 | |
| wrong accusations | 0.005 | 1/400 episodes, each 1 - (-1) = full loss |
| abstains (score 0) | 0.122 | 49/400 episodes |
| canary cost, all episodes (for reference) | 0.063 | |

### Stopping-rule sweep (same trajectories)

| rule | mean | Δ vs default |
|---|---|---|
| p ≥ 0.6 | 0.591 | -0.030 |
| p ≥ 0.7 | 0.623 | +0.003 |
| p ≥ 0.8 | 0.622 | +0.001 |
| p ≥ 0.85 | 0.622 | +0.001 |
| p ≥ 0.9 | 0.621 | +0.000 |
| p ≥ 0.95 | 0.621 | +0.000 |
| best p ≥ a + b·V (grid a 0.50..0.95, b -0.4..0.4) a=0.85 b=-0.2 | 0.624 | +0.004 |
| oracle stop (knows the mole; upper bound, not achievable) | 0.788 | +0.167 |

### Information rate (days ≥ 3, all decision days)

- regular docs the mole can leak on a given day: mean 4.45
- our canaries the mole holds in its leak window: mean 0.86
- p_leak 0.75, canaries/day 1, variants 3, delays (1, 2, 3), careful mole True

How to read the loss decomposition: the loss is 1 minus the score, so a wrong accusation counts as 1 − (−1) = 2. On medium the biggest loss is abstaining (12%). In those episodes the posterior stalls near 50/50 between two suspects, typically two people in the same department.

## The stronger reference: solver_v2

`solver_v2` is on branch `justSilas-solver2-algo`, at commits d42055e and b5b5e2b. It uses the same tools and information as any agent. It makes three changes:
- It counts every outstanding canary when it plans the day's canaries (the solver capped this at 4).
- On medium, it chooses its single canary by joint information gain including the pending canaries.
- When suspicion has concentrated on a few people but stalls, it restricts the top suspect. A restricted mole runs out of documents to leak, so silence convicts them and continued leaks clear them.

Results on the fresh seeds 9000-9399 (n=400 per tier, paired on the same seeds):

| tier | agent | mean ± 95% CI | acc when accusing | abstain | paired Δ ± 95% CI |
|---|---|---|---|---|---|
| medium | solver | 0.617 ± 0.025 | 100.0% | 12.3% | |
| medium | solver_v2 (d42055e) | 0.636 ± 0.024 | 99.5% | 8.8% | +0.019 ± 0.032 |
| hard | solver | 0.561 ± 0.032 | 96.5% | 0.7% | |
| hard | solver_v2 (d42055e) | 0.573 ± 0.029 | 97.2% | 1.0% | +0.012 ± 0.029 |

- **Earlier commit:** b95a7ab (pipelining only) gave medium +0.003 [−0.028, +0.034] and hard +0.010 [−0.018, +0.038].
- **Medium:** on the tuning seeds the gain was +0.04 to +0.06 (+0.059 ± 0.028 on 8300-8799). That gain is from tuning seeds only. On fresh seeds it shrank to +0.019 ± 0.032, which is not significant.
- **Hard:** the bar was +0.08 and it was **not met**. Sweeps of the solver's settings on 8000-8799 all came out within ±0.02 of the solver, which is noise: the evidence-weighting constants, `min_gain`, the number of canaries per day, the number of pending canaries counted, the accusation threshold, and the restriction-test settings.
- **Run that reproduces the table:** `uv run --python 3.12 --extra dev python -m canary.solver.paired --tiers medium,hard --seed0 9000 --seeds 400`, run on branch `justSilas-solver2-algo`.
