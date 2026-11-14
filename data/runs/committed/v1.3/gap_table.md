| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |
|---|---|---|---|---|---|---|---|
| hard | codex:gpt-5.5 | 11 | 0.655 ± 0.041 | 1.00 | 11.6 | 0.98 | – |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 11.6 | -0.61 | – |
| hard | openai:gpt-5.5 | 8 | 0.264 ± 0.541 | 0.75 | 12.2 | 0.36 | – |
| hard | random | 20 | -0.700 ± 0.206 | 0.00 | 6.6 | -1.02 | – |
| hard | restrict_all | 20 | -1.000 ± 0.000 | 0.00 | 8.0 | -1.45 | – |
| hard | solver | 20 | 0.592 ± 0.114 | 0.85 | 10.8 | 1.00 | – |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.0 | -1.26 | – |
| medium | codex:gpt-5.5 | 11 | 0.401 ± 0.417 | 0.82 | 8.8 | 0.60 | – |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 11.1 | -0.24 | – |
| medium | openai:gpt-5.5 | 9 | 0.668 ± 0.103 | 1.00 | 9.9 | 0.95 | – |
| medium | random | 20 | -0.678 ± 0.225 | 0.05 | 6.5 | -1.02 | – |
| medium | restrict_all | 20 | -0.950 ± 0.098 | 0.05 | 7.0 | -1.38 | – |
| medium | solver | 20 | 0.717 ± 0.052 | 1.00 | 7.5 | 1.00 | – |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.0 | -1.45 | – |

**GAP ALERT (>=85% of solver on medium):** openai:gpt-5.5: 0.668 vs solver 0.717 (93%)
