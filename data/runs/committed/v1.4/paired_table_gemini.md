| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.713 ± 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.717 | 103% [95%, 112%] | 0.023 ± 0.061 | 0.712 | **99% [84%, 111%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.579 ± 0.110 | 0.80 | 0.80 | 7.7 | 0.99 | 0.717 | 83% [63%, 99%] | -0.125 ± 0.133 | 0.592 | **83% [63%, 99%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.530 ± 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | 0.717 | 64% [33%, 89%] | -0.261 ± 0.210 | 0.412 | **57% [32%, 82%]** |
| medium | reference solver | 20 | 0.717 ± 0.052 | 1.00 | 1.00 | 7.5 | 1.00 | 0.717 | – | – | 0.717 | – |
| medium | heuristic | 20 | -0.275 ± 0.361 | 0.45 | 1.00 | 11.3 | 0.62 | 0.717 | -38% [-86%, 8%] | -0.991 ± 0.369 | -0.018 | **-3% [-33%, 28%]** |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.717 | 0% [0%, 0%] | -0.717 ± 0.052 | 0.000 | **0% [0%, 0%]** |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.05 | 0.717 | -139% [-151%, -131%] | -1.717 ± 0.052 | -0.900 | **-126% [-136%, -118%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.322 ± 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.464 | 60% [1%, 103%] | -0.188 ± 0.236 | 0.336 | **68% [43%, 91%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.279 ± 0.180 | 0.70 | 0.80 | 13.2 | 0.87 | 0.464 | 47% [-13%, 92%] | -0.244 ± 0.236 | 0.300 | **61% [35%, 85%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.473 ± 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.464 | 100% [53%, 185%] | 0.000 ± 0.258 | 0.449 | **91% [68%, 115%]** |
| hard | reference solver | 20 | 0.464 ± 0.171 | 0.95 | 1.00 | 10.8 | 0.97 | 0.464 | – | – | 0.495 | – |
| hard | heuristic | 20 | 0.186 ± 0.233 | 0.85 | 1.00 | 13.9 | 0.79 | 0.464 | 40% [-12%, 108%] | -0.279 ± 0.317 | 0.095 | **19% [-19%, 54%]** |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.464 | 0% [0%, 0%] | -0.464 ± 0.171 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.464 | -215% [-360%, -167%] | -1.464 ± 0.171 | -0.950 | **-192% [-231%, -166%]** |
