| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 10 | 0.610 ± 0.203 | 0.80 | 0.80 | 6.9 | 1.00 | 0.730 | 84% [52%, 112%] | -0.120 ± 0.233 | 0.610 | **84% [52%, 112%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 10 | 0.610 ± 0.203 | 0.80 | 0.80 | 6.9 | 1.00 | 0.730 | 84% [52%, 112%] | -0.120 ± 0.233 | 0.610 | **84% [52%, 112%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 10 | 0.553 ± 0.151 | 0.90 | 0.90 | 10.3 | 0.90 | 0.730 | 76% [54%, 98%] | -0.177 ± 0.183 | 0.423 | **58% [23%, 91%]** |
| medium | Codex gpt-5.5 over MCP (earlier official run) | 10 | 0.364 ± 0.454 | 0.80 | 1.00 | 9.0 | 0.69 | 0.730 | 50% [-19%, 103%] | -0.366 ± 0.456 | 0.197 | **27% [-26%, 80%]** |
| medium | in-process gpt-5.5, fixed loop (earlier official run) | 9 | 0.668 ± 0.103 | 1.00 | 1.00 | 9.9 | 0.92 | 0.722 | 92% [80%, 106%] | -0.054 ± 0.101 | 0.542 | **75% [42%, 103%]** |
| medium | reference solver | 10 | 0.730 ± 0.088 | 1.00 | 1.00 | 7.2 | 1.00 | 0.730 | – | – | 0.730 | – |
| medium | heuristic | 10 | -0.038 ± 0.515 | 0.60 | 1.00 | 11.2 | 0.68 | 0.730 | -5% [-76%, 59%] | -0.768 ± 0.492 | 0.077 | **11% [-26%, 49%]** |
| medium | do_nothing | 10 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.730 | 0% [0%, 0%] | -0.730 ± 0.088 | 0.000 | **0% [0%, 0%]** |
| medium | stop_early | 10 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.05 | 0.730 | -137% [-156%, -125%] | -1.730 ± 0.088 | -0.900 | **-123% [-141%, -112%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 10 | 0.544 ± 0.341 | 0.90 | 1.00 | 11.2 | 0.80 | 0.678 | 80% [26%, 111%] | -0.134 ± 0.334 | 0.381 | **83% [18%, 162%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 10 | 0.477 ± 0.356 | 0.80 | 0.90 | 10.9 | 0.81 | 0.678 | 70% [13%, 109%] | -0.201 ± 0.347 | 0.362 | **79% [14%, 154%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 10 | 0.566 ± 0.342 | 0.90 | 1.00 | 11.9 | 0.72 | 0.678 | 83% [31%, 113%] | -0.112 ± 0.329 | 0.235 | **51% [23%, 86%]** |
| hard | Codex gpt-5.5 over MCP (earlier official run) | 10 | 0.657 ± 0.045 | 1.00 | 1.00 | 11.5 | 0.80 | 0.678 | 97% [89%, 107%] | -0.021 ± 0.064 | 0.314 | **69% [18%, 135%]** |
| hard | in-process gpt-5.5, fixed loop (earlier official run) | 8 | 0.264 ± 0.541 | 0.75 | 1.00 | 12.2 | 0.75 | 0.701 | 38% [-51%, 99%] | -0.437 ± 0.534 | 0.250 | **58% [-41%, 112%]** |
| hard | reference solver | 10 | 0.678 ± 0.039 | 1.00 | 1.00 | 11.5 | 0.87 | 0.678 | – | – | 0.457 | – |
| hard | heuristic | 10 | -0.318 ± 0.546 | 0.40 | 1.00 | 11.7 | 0.43 | 0.678 | -47% [-125%, 29%] | -0.996 ± 0.530 | -0.282 | **-62% [-138%, -2%]** |
| hard | do_nothing | 10 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.678 | 0% [0%, 0%] | -0.678 ± 0.039 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 10 | -0.800 ± 0.392 | 0.10 | 1.00 | 1.0 | 0.03 | 0.678 | -118% [-153%, -58%] | -1.478 ± 0.401 | -0.934 | **-204% [-302%, -162%]** |
