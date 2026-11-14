# J4 proxy metrics (held-out eval)

**Descriptive only.** Episode counts are tiny; no significance is claimed. Invalid outputs are counted from meta.invalid_calls (eval_hf maps them to `status`).

## all (eval-base: n = 2 episodes, 600 steps; eval-lora-par: n = 12 episodes, 1304 steps; eval-lora: n = 5 episodes, 433 steps)

| metric | eval-base | eval-lora-par | eval-lora |
|---|---|---|---|
| n_episodes | 2 | 12 | 5 |
| n_steps | 600 | 1304 | 433 |
| valid_rate | 0.082 | 0.996 | 0.991 |
| invalid_share | 0.918 | 0.000 | 0.000 |
| result_not_ok_share | 0.000 | 0.004 | 0.009 |
| repeat_share | 0.997 | 0.000 | 0.000 |
| mix[plant_canary] | 0.000 | 0.127 | 0.122 |
| mix[check_leak_feed] | 0.000 | 0.128 | 0.127 |
| mix[advance_day] | 0.000 | 0.127 | 0.122 |
| mix[read_access_logs] | 0.000 | 0.140 | 0.136 |
| mix[interview] | 0.000 | 0.000 | 0.000 |
| mix[accuse] | 0.000 | 0.002 | 0.005 |
| mix[status] | 1.000 | 0.245 | 0.238 |
| mix[other] | 0.000 | 0.232 | 0.249 |
| mix[status net of invalid] | 0.082 | 0.245 | 0.238 |
| reached_accusation | 0.000 | 0.167 | 0.400 |
| accuracy | 0.000 | 0.083 | 0.000 |
| mean_score | 0.000 | -0.043 | -0.400 |
| score_ci95 | 0.000 | 0.188 | 0.480 |
| mean_final_day | 1.000 | 13.917 | 11.000 |
| end_reasons | tool_cap:2 | accused:2, horizon:10 | accused:2, horizon:3 |
| solver_tool_agreement | 0.000 | 0.861 | 0.808 |

## easy (eval-base: n = 1 episodes, 300 steps; eval-lora-par: n = 4 episodes, 391 steps; eval-lora: n = 2 episodes, 94 steps)

| metric | eval-base | eval-lora-par | eval-lora |
|---|---|---|---|
| n_episodes | 1 | 4 | 2 |
| n_steps | 300 | 391 | 94 |
| valid_rate | 0.153 | 0.987 | 0.968 |
| invalid_share | 0.847 | 0.000 | 0.000 |
| result_not_ok_share | 0.000 | 0.013 | 0.032 |
| repeat_share | 0.997 | 0.000 | 0.000 |
| mix[plant_canary] | 0.000 | 0.138 | 0.117 |
| mix[check_leak_feed] | 0.000 | 0.141 | 0.138 |
| mix[advance_day] | 0.000 | 0.138 | 0.117 |
| mix[read_access_logs] | 0.000 | 0.138 | 0.128 |
| mix[interview] | 0.000 | 0.000 | 0.000 |
| mix[accuse] | 0.000 | 0.003 | 0.021 |
| mix[status] | 1.000 | 0.269 | 0.234 |
| mix[other] | 0.000 | 0.174 | 0.245 |
| mix[status net of invalid] | 0.153 | 0.269 | 0.234 |
| reached_accusation | 0.000 | 0.250 | 1.000 |
| accuracy | 0.000 | 0.000 | 0.000 |
| mean_score | 0.000 | -0.250 | -1.000 |
| score_ci95 | nan | 0.490 | 0.000 |
| mean_final_day | 1.000 | 13.750 | 6.500 |
| end_reasons | tool_cap:1 | accused:1, horizon:3 | accused:2 |
| solver_tool_agreement | 0.000 | 0.943 | 0.854 |

## hard (eval-lora-par: n = 4 episodes, 468 steps; eval-lora: n = 1 episodes, 119 steps)

| metric | eval-lora-par | eval-lora |
|---|---|---|
| n_episodes | 4 | 1 |
| n_steps | 468 | 119 |
| valid_rate | 1.000 | 1.000 |
| invalid_share | 0.000 | 0.000 |
| result_not_ok_share | 0.000 | 0.000 |
| repeat_share | 0.000 | 0.000 |
| mix[plant_canary] | 0.118 | 0.118 |
| mix[check_leak_feed] | 0.120 | 0.118 |
| mix[advance_day] | 0.118 | 0.118 |
| mix[read_access_logs] | 0.137 | 0.134 |
| mix[interview] | 0.000 | 0.000 |
| mix[accuse] | 0.002 | 0.000 |
| mix[status] | 0.229 | 0.227 |
| mix[other] | 0.278 | 0.286 |
| mix[status net of invalid] | 0.229 | 0.227 |
| reached_accusation | 0.250 | 0.000 |
| accuracy | 0.250 | 0.000 |
| mean_score | 0.121 | 0.000 |
| score_ci95 | 0.238 | nan |
| mean_final_day | 14.000 | 14.000 |
| end_reasons | accused:1, horizon:3 | horizon:1 |
| solver_tool_agreement | 0.824 | 0.833 |

## medium (eval-base: n = 1 episodes, 300 steps; eval-lora-par: n = 4 episodes, 445 steps; eval-lora: n = 2 episodes, 220 steps)

| metric | eval-base | eval-lora-par | eval-lora |
|---|---|---|---|
| n_episodes | 1 | 4 | 2 |
| n_steps | 300 | 445 | 220 |
| valid_rate | 0.010 | 1.000 | 0.995 |
| invalid_share | 0.990 | 0.000 | 0.000 |
| result_not_ok_share | 0.000 | 0.000 | 0.005 |
| repeat_share | 0.997 | 0.000 | 0.000 |
| mix[plant_canary] | 0.000 | 0.126 | 0.127 |
| mix[check_leak_feed] | 0.000 | 0.126 | 0.127 |
| mix[advance_day] | 0.000 | 0.126 | 0.127 |
| mix[read_access_logs] | 0.000 | 0.146 | 0.141 |
| mix[interview] | 0.000 | 0.000 | 0.000 |
| mix[accuse] | 0.000 | 0.000 | 0.000 |
| mix[status] | 1.000 | 0.243 | 0.245 |
| mix[other] | 0.000 | 0.234 | 0.232 |
| mix[status net of invalid] | 0.010 | 0.243 | 0.245 |
| reached_accusation | 0.000 | 0.000 | 0.000 |
| accuracy | 0.000 | 0.000 | 0.000 |
| mean_score | 0.000 | 0.000 | 0.000 |
| score_ci95 | nan | 0.000 | 0.000 |
| mean_final_day | 1.000 | 14.000 | 14.000 |
| end_reasons | tool_cap:1 | horizon:4 | horizon:2 |
| solver_tool_agreement | 0.000 | 0.817 | 0.775 |

## Runs

- eval-base: {"agent": "hf:Qwen2.5-1.5B-Instruct", "model": "base", "git_sha": "", "tiers": ["easy", "medium", "hard"], "seeds": "heldout", "n": 30}
- eval-lora-par: {"agent": "hf-lora:lora", "model": "/home/silas/agent-arena-data/j4/run-44397/lora", "git_sha": "", "tiers": ["easy", "medium", "hard"], "seeds": "heldout", "n": 30}
- eval-lora: {"agent": "hf-lora:lora", "model": "/home/silas/agent-arena-data/j4/run-44397/lora", "git_sha": "", "tiers": ["easy", "medium", "hard"], "seeds": "heldout", "n": 30}
