# J1 recommendation

Sources: ['/Users/silaswang/junction-aimo-team/wt/justSilas-fr8-ops/data/fr8/j1v1/parts'] (306 cell files)  
Rows: 153000

Objective: solver acc ≥ 0.90; medium heur ≤ 0.55×solver; medium/hard logs_only acc ≤ 2/N; stop_early < 0; maximise solver−heuristic gap (tiebreak smaller solver CI). Seeds column: paired n for 95% CI half-width < gap/3.

## easy (18 cells, 18 feasible)
**Recommend:** `careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | none rate (per agent) | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0 | 100 | 0.799 ± 0.018 | 1.000 | 0.681 ± 0.041 | 0.990 | 0.280 (chance 0.083) | -0.860 | 0.000/0.010 | heuristic=0.00 logs_only=0.00 random=0.32 solver=0.00 stop_early=0.00 | 0.117 ± 0.040 | 103 | ok |
| careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.3,p_single_dept_recipients=0.0 | 100 | 0.793 ± 0.022 | 1.000 | 0.681 ± 0.041 | 0.990 | 0.520 (chance 0.083) | -0.860 | 0.000/0.010 | heuristic=0.00 logs_only=0.00 random=0.32 solver=0.00 stop_early=0.00 | 0.111 ± 0.035 | 90 | ok |

## hard (144 cells, 26 feasible)
**Recommend:** `careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.3,n_employees=30,p_after_hours_mole=0.15,p_single_dept_recipients=1.0`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | none rate (per agent) | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.3,n_employees=30,p_after_hours_mole=0.15,p_single_dept_recipients=1.0 | 100 | 0.711 ± 0.035 | 0.950 | -0.036 ± 0.165 | 0.570 | 0.020 (chance 0.033) | -0.920 | 0.000/0.430 | heuristic=0.00 logs_only=0.00 random=0.30 solver=0.05 stop_early=0.00 | 0.747 ± 0.172 | 48 | ok |
| careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.0,n_employees=30,p_after_hours_mole=0.15,p_single_dept_recipients=1.0 | 100 | 0.710 ± 0.036 | 0.950 | 0.013 ± 0.163 | 0.600 | 0.000 (chance 0.033) | -0.920 | 0.000/0.400 | heuristic=0.00 logs_only=0.00 random=0.30 solver=0.05 stop_early=0.00 | 0.697 ± 0.166 | 52 | ok |

## medium (144 cells, 14 feasible)
**Recommend:** `careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=20,p_after_hours_mole=0.3,p_single_dept_recipients=0.6`

| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | stop_early mean | wrong rate solver/heur | none rate (per agent) | gap ± CI95 | seeds for CI<gap/3 | constraints |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.15,n_employees=20,p_after_hours_mole=0.3,p_single_dept_recipients=0.6 | 100 | 0.673 ± 0.034 | 0.960 | 0.103 ± 0.153 | 0.670 | 0.090 (chance 0.050) | -0.880 | 0.000/0.330 | heuristic=0.00 logs_only=0.00 random=0.31 solver=0.04 stop_early=0.00 | 0.570 ± 0.148 | 61 | ok |
| careful_mole=True,delay_choices=[1, 2, 3],framing_rate=1.5,log_rate_mole=1.3,n_employees=20,p_after_hours_mole=0.15,p_single_dept_recipients=0.6 | 100 | 0.656 ± 0.038 | 0.950 | 0.190 ± 0.147 | 0.720 | 0.030 (chance 0.050) | -0.880 | 0.000/0.280 | heuristic=0.00 logs_only=0.00 random=0.31 solver=0.05 stop_early=0.00 | 0.466 ± 0.141 | 83 | ok |

## Joint pick (solver mean easy > medium > hard)

| tier | params | solver mean ± CI95 | gap | seeds for CI<gap/3 |
|---|---|---|---|---|
| easy | `careful_mole=False,delay_choices=[1],framing_rate=1.0,log_rate_mole=1.3,n_employees=12,p_after_hours_mole=0.15,p_single_dept_recipients=0.0` | 0.799 ± 0.018 | 0.117 | 103 |
| medium | `careful_mole=True,delay_choices=[1, 2],framing_rate=0.5,log_rate_mole=1.0,n_employees=20,p_after_hours_mole=0.15,p_single_dept_recipients=1.0` | 0.769 ± 0.018 | 0.460 | 86 |
| hard | `careful_mole=True,delay_choices=[2, 3],framing_rate=1.5,log_rate_mole=1.3,n_employees=30,p_after_hours_mole=0.15,p_single_dept_recipients=1.0` | 0.711 ± 0.035 | 0.747 | 48 |
