| tier | run | n | score ± 95% CI | accuracy | accused | mean P(accused) at accusation | solver, same seeds | frontier / solver [95% CI] | paired diff ± CI | posterior-expected score (luck-adjusted) | luck-adjusted / solver |
|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | Codex gpt-5.5 over MCP (judges' shape), full run | 11 | 0.401 ± 0.417 | 0.82 | 1.00 | 0.72 | 0.726 | 55% [-8%, 104%] | -0.325 ± 0.420 | 0.249 | 34% |
| medium | in-process gpt-5.5, fixed loop (full history, Responses + reasoning replay, effort=medium) | 9 | 0.668 ± 0.103 | 1.00 | 1.00 | 0.92 | 0.722 | 92% [80%, 106%] | -0.054 ± 0.101 | 0.542 | 75% |
| medium | Codex gpt-5.5 over MCP, earlier sample (0933805; history) | 1 | 0.530 ± 0.000 | 1.00 | 1.00 | 0.55 | 0.740 | 72% | -0.210 ± 0.000 | -0.160 | -22% |
| medium | in-process gpt-5.5, handicapped scaffold, superseded (40-turn window) | 9 | 0.319 ± 0.497 | 0.78 | 1.00 | 0.80 | 0.670 | 48% [-38%, 100%] | -0.351 ± 0.415 | 0.358 | 53% |
| medium | reference solver | 20 | 0.717 ± 0.052 | 1.00 | 1.00 | 1.00 | 0.717 | – | – | 0.717 | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 1.00 | 0.60 | 0.717 | -16% [-66%, 30%] | -0.832 ± 0.353 | -0.035 | -5% |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | – | 0.717 | 0% [0%, 0%] | -0.717 ± 0.052 | 0.000 | 0% |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.00 | 0.05 | 0.717 | -139% [-151%, -131%] | -1.717 ± 0.052 | -0.900 | -126% |
| hard | Codex gpt-5.5 over MCP (judges' shape), full run | 11 | 0.655 ± 0.041 | 1.00 | 1.00 | 0.82 | 0.616 | 106% [91%, 136%] | 0.038 ± 0.131 | 0.343 | 82% |
| hard | in-process gpt-5.5, fixed loop (full history, Responses + reasoning replay, effort=medium) | 8 | 0.264 ± 0.541 | 0.75 | 1.00 | 0.75 | 0.701 | 38% [-51%, 99%] | -0.437 ± 0.534 | 0.250 | 58% |
| hard | Codex gpt-5.5 over MCP, earlier sample (0933805; history) | 2 | 0.588 ± 0.132 | 1.00 | 1.00 | 0.99 | 0.705 | 83% [73%, 94%] | -0.117 ± 0.142 | 0.572 | 100% |
| hard | in-process gpt-5.5, handicapped scaffold, superseded (40-turn window) | 5 | -0.003 ± 0.799 | 0.60 | 1.00 | 0.61 | 0.553 | -1% [-121%, 166%] | -0.556 ± 0.944 | 0.004 | 1% |
| hard | reference solver | 20 | 0.592 ± 0.114 | 0.85 | 0.85 | 0.91 | 0.592 | – | – | 0.468 | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 1.00 | 0.40 | 0.592 | -54% [-113%, 6%] | -0.914 ± 0.403 | -0.333 | -71% |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | – | 0.592 | 0% [0%, 0%] | -0.592 ± 0.114 | 0.000 | 0% |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.00 | 0.03 | 0.592 | -152% [-203%, -110%] | -1.492 ± 0.222 | -0.934 | -200% |
