| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.713 ± 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.645 | 111% [99%, 127%] | 0.068 ± 0.080 | 0.652 | **101% [85%, 119%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.579 ± 0.110 | 0.80 | 0.80 | 7.7 | 0.99 | 0.645 | 90% [71%, 109%] | -0.066 ± 0.124 | 0.558 | **86% [68%, 106%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.530 ± 0.138 | 0.83 | 0.87 | 9.0 | 0.93 | 0.645 | 82% [56%, 108%] | -0.115 ± 0.170 | 0.479 | **74% [52%, 99%]** |
| medium | reference solver | 30 | 0.645 ± 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | 0.645 | – | – | 0.645 | – |
| medium | heuristic | 20 | -0.275 ± 0.361 | 0.45 | 1.00 | 11.3 | 0.62 | 0.717 | -38% [-86%, 8%] | -0.991 ± 0.369 | -0.018 | **-3% [-33%, 28%]** |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.717 | 0% [0%, 0%] | -0.717 ± 0.052 | 0.000 | **0% [0%, 0%]** |
| medium | day-1 guess (recorded under the pre-2bb6729 name stop_early; today's stop_early stops without accusing and scores 0, see results/judge_table.md) | 20 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.05 | 0.717 | -139% [-151%, -131%] | -1.717 ± 0.052 | -0.900 | **-126% [-136%, -118%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.322 ± 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 ± 0.194 | 0.360 | **72% [52%, 91%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.279 ± 0.180 | 0.70 | 0.80 | 13.2 | 0.87 | 0.499 | 56% [19%, 87%] | -0.220 ± 0.174 | 0.277 | **55% [34%, 77%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 30 | 0.473 ± 0.118 | 0.93 | 0.97 | 12.7 | 0.93 | 0.499 | 95% [62%, 140%] | -0.026 ± 0.184 | 0.421 | **84% [65%, 106%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family; the API reports modelVersion gemini-3.6-flash for this id) | 30 | 0.373 ± 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | 0.499 | 75% [36%, 123%] | -0.126 ± 0.221 | 0.110 | **22% [-23%, 63%]** |
| hard | reference solver | 30 | 0.499 ± 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | – | – | 0.499 | – |
| hard | heuristic | 20 | 0.186 ± 0.233 | 0.85 | 1.00 | 13.9 | 0.79 | 0.464 | 40% [-12%, 108%] | -0.279 ± 0.317 | 0.095 | **19% [-19%, 54%]** |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.464 | 0% [0%, 0%] | -0.464 ± 0.171 | 0.000 | **0% [0%, 0%]** |
| hard | day-1 guess (recorded under the pre-2bb6729 name stop_early; today's stop_early stops without accusing and scores 0, see results/judge_table.md) | 20 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.464 | -215% [-360%, -167%] | -1.464 ± 0.171 | -0.950 | **-192% [-231%, -166%]** |
