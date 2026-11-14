# J4 proxy metrics (held-out eval)

**Descriptive only.** Episode counts are tiny; no significance is claimed. Invalid outputs are counted from meta.invalid_calls (eval_hf maps them to `status`).

## all (hard-0-4: n = 5 episodes, 440 steps; medium-10-14: n = 5 episodes, 295 steps)

| metric | hard-0-4 | medium-10-14 |
|---|---|---|
| n_episodes | 5 | 5 |
| n_steps | 440 | 295 |
| valid_rate | 0.975 | 1.000 |
| invalid_share | 0.000 | 0.000 |
| result_not_ok_share | 0.025 | 0.000 |
| repeat_share | 0.000 | 0.000 |
| mix[plant_canary] | 0.111 | 0.098 |
| mix[check_leak_feed] | 0.125 | 0.098 |
| mix[advance_day] | 0.118 | 0.098 |
| mix[read_access_logs] | 0.243 | 0.112 |
| mix[interview] | 0.020 | 0.112 |
| mix[accuse] | 0.011 | 0.017 |
| mix[status] | 0.045 | 0.064 |
| mix[other] | 0.325 | 0.400 |
| mix[status net of invalid] | 0.045 | 0.064 |
| reached_accusation | 1.000 | 1.000 |
| accuracy | 0.800 | 1.000 |
| mean_score | 0.358 | 0.764 |
| score_ci95 | 0.668 | 0.047 |
| mean_final_day | 11.400 | 6.800 |
| end_reasons | accused:5 | accused:5 |
| solver_tool_agreement | 0.089 | 0.105 |

## hard (hard-0-4: n = 5 episodes, 440 steps)

| metric | hard-0-4 |
|---|---|
| n_episodes | 5 |
| n_steps | 440 |
| valid_rate | 0.975 |
| invalid_share | 0.000 |
| result_not_ok_share | 0.025 |
| repeat_share | 0.000 |
| mix[plant_canary] | 0.111 |
| mix[check_leak_feed] | 0.125 |
| mix[advance_day] | 0.118 |
| mix[read_access_logs] | 0.243 |
| mix[interview] | 0.020 |
| mix[accuse] | 0.011 |
| mix[status] | 0.045 |
| mix[other] | 0.325 |
| mix[status net of invalid] | 0.045 |
| reached_accusation | 1.000 |
| accuracy | 0.800 |
| mean_score | 0.358 |
| score_ci95 | 0.668 |
| mean_final_day | 11.400 |
| end_reasons | accused:5 |
| solver_tool_agreement | 0.089 |

## medium (medium-10-14: n = 5 episodes, 295 steps)

| metric | medium-10-14 |
|---|---|
| n_episodes | 5 |
| n_steps | 295 |
| valid_rate | 1.000 |
| invalid_share | 0.000 |
| result_not_ok_share | 0.000 |
| repeat_share | 0.000 |
| mix[plant_canary] | 0.098 |
| mix[check_leak_feed] | 0.098 |
| mix[advance_day] | 0.098 |
| mix[read_access_logs] | 0.112 |
| mix[interview] | 0.112 |
| mix[accuse] | 0.017 |
| mix[status] | 0.064 |
| mix[other] | 0.400 |
| mix[status net of invalid] | 0.064 |
| reached_accusation | 1.000 |
| accuracy | 1.000 |
| mean_score | 0.764 |
| score_ci95 | 0.047 |
| mean_final_day | 6.800 |
| end_reasons | accused:5 |
| solver_tool_agreement | 0.105 |

## Runs

- hard-0-4: {"agent": "openai:gpt-5.5", "model": "gpt-5.5", "git_sha": "6e2455fe261e0bf5e84a6764fc02b29c23bc84c1", "tiers": null, "seeds": [0, 1, 2, 3, 4], "n": null}
- medium-10-14: {"agent": "openai:gpt-5.5", "model": "gpt-5.5", "git_sha": "db104c99491ea216e4c2fecaaa4f3fd904eb4d22", "tiers": null, "seeds": [10, 11, 12, 13, 14], "n": null}
