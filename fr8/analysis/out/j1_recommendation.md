# J1 recommendation

Sources: ['/Users/silaswang/junction-aimo-team/wt/justSilas-fr8-ops/data/fr8/j1/parts'] (306 cell files)  
Rows: 153000

Objective: solver acc ≥ 0.90; medium heur ≤ 0.55×solver; medium/hard logs_only acc ≤ 2/N; stop_early < 0; maximise solver−heuristic gap (tiebreak smaller solver CI). Seeds column: paired n for 95% CI half-width < gap/3.

## easy (18 cells, 18 feasible)
**Recommend:** `careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0 | 100 | 0.796 ± 0.019 | 1.000 | 0.681 ± 0.041 | 0.990 | 0.280 (chance 0.083) | -0.860 | 0.000/0.010 | 0.115 ± 0.039 | 106 | ok |
| careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.0,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0 | 100 | 0.801 ± 0.017 | 1.000 | 0.694 ± 0.039 | 0.990 | 0.150 (chance 0.083) | -0.860 | 0.000/0.010 | 0.108 ± 0.038 | 113 | ok |
| careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.15,n_employees=12,p_after_hours_mole=0.3,p_single_dept_recipients=0.6 | 100 | 0.840 ± 0.012 | 1.000 | 0.735 ± 0.022 | 1.000 | 0.430 (chance 0.083) | -0.860 | 0.000/0.000 | 0.105 ± 0.023 | 42 | ok |

## hard (144 cells, 65 feasible)
**Recommend:** `careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=30,p_after_hours_mole=0.3,p_single_dept_recipients=0.0`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=30,p_after_hours_mole=0.3,p_single_dept_recipients=0.0 | 100 | 0.523 ± 0.096 | 0.910 | -0.387 ± 0.158 | 0.370 | 0.060 (chance 0.033) | -0.920 | 0.090/0.630 | 0.910 ± 0.168 | 31 | ok |
| careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.0,n_employees=30,p_after_hours_mole=0.3,p_single_dept_recipients=0.0 | 100 | 0.595 ± 0.074 | 0.950 | -0.259 ± 0.162 | 0.450 | 0.030 (chance 0.033) | -0.920 | 0.050/0.550 | 0.854 ± 0.169 | 36 | ok |
| careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.3,n_employees=30,p_after_hours_mole=0.15,p_single_dept_recipients=1.0 | 100 | 0.716 ± 0.051 | 0.980 | -0.036 ± 0.165 | 0.570 | 0.020 (chance 0.033) | -0.920 | 0.020/0.430 | 0.752 ± 0.171 | 47 | ok |

## medium (144 cells, 35 feasible)
**Recommend:** `careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=20,p_after_hours_mole=0.15,p_single_dept_recipients=0.0`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=20,p_after_hours_mole=0.15,p_single_dept_recipients=0.0 | 100 | 0.541 ± 0.087 | 0.930 | -0.184 ± 0.161 | 0.500 | 0.010 (chance 0.050) | -0.880 | 0.070/0.500 | 0.726 ± 0.179 | 55 | ok |
| careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=20,p_after_hours_mole=0.3,p_single_dept_recipients=0.0 | 100 | 0.511 ± 0.091 | 0.920 | -0.184 ± 0.161 | 0.500 | 0.030 (chance 0.050) | -0.880 | 0.080/0.500 | 0.696 ± 0.159 | 48 | ok |
| careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.0,n_employees=20,p_after_hours_mole=0.3,p_single_dept_recipients=0.0 | 100 | 0.528 ± 0.086 | 0.930 | -0.142 ± 0.160 | 0.530 | 0.000 (chance 0.050) | -0.880 | 0.070/0.470 | 0.669 ± 0.172 | 60 | ok |

## Proposed canary/rules.py values (TierParams fields; everything else unchanged)

```python
# easy
n_employees=12, delay_choices=(1,), careful_mole=False, framing_rate=1.0, log_rate_mole=1.3,
p_after_hours_mole=0.15, p_single_dept_recipients=0.0
# medium
n_employees=20, delay_choices=(1, 2, 3), careful_mole=True, framing_rate=1.5, log_rate_mole=1.15,
p_after_hours_mole=0.15, p_single_dept_recipients=0.0
# hard  (objective pick; see note — robust alternative: log_rate_mole=1.0)
n_employees=30, delay_choices=(2, 3), careful_mole=True, framing_rate=1.5, log_rate_mole=1.15,
p_after_hours_mole=0.3, p_single_dept_recipients=0.0
```

## Notes
- Data: J1 regrid run locally by ops (306 cells, 100 seeds × 5 agents each, 153,000 episodes, scoring v0.3 with a wrong accusation = −1, solver v1). Command:
  `python -m fr8.analysis.j1_recommend ~/junction-aimo-team/wt/justSilas-fr8-ops/data/fr8/j1/parts --closest 3 --out fr8/analysis/out/j1_recommendation.md`
- Hard pick has solver acc 0.91 at n=100 (binomial 95% CI ≈ 0.85–0.96), so ≥ 0.90 is not robustly met. The runner-up (log_rate_mole=1.0) has acc 0.95, gap 0.854 ± 0.169 (overlapping), and is the safer choice.
- Easy: every cell is feasible, but the gap is small (≈0.11), so it needs ~106 paired seeds for CI < gap/3. Easy logs_only accuracy is 0.28 vs chance 0.083, which is unconstrained by design.
- Seeds per tier for a 95% CI half-width < gap/3 (paired, recommended cell): easy 106, medium 55, hard 31 (36 for the alternative).
- fingerprint_accuracy (v0.4) is not in this grid: the curve section needs a regrid once ENV v0.4 lands. j1_recommend already renders it whenever a `fingerprint_accuracy` column is present.
