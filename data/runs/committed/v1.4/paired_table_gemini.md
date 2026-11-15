| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.713 ± 0.042 | 1.00 | 1.00 | 8.0 | 0.96 | 0.645 | 111% [99%, 127%] | 0.068 ± 0.080 | 0.652 | **101% [85%, 119%]** |
| medium | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.579 ± 0.110 | 0.80 | 0.80 | 7.7 | 0.99 | 0.645 | 90% [71%, 109%] | -0.066 ± 0.124 | 0.558 | **86% [68%, 106%]** |
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 15 | 0.558 ± 0.155 | 0.80 | 0.80 | 8.7 | 0.96 | 0.712 | 78% [55%, 100%] | -0.154 ± 0.176 | 0.500 | **70% [45%, 96%]** |
| medium | reference solver | 30 | 0.645 ± 0.087 | 0.90 | 0.90 | 7.6 | 1.00 | 0.645 | – | – | 0.645 | – |
| medium | heuristic | 30 | -0.407 ± 0.284 | 0.37 | 1.00 | 11.3 | 0.59 | 0.645 | -63% [-107%, -19%] | -1.052 ± 0.301 | -0.064 | **-10% [-36%, 18%]** |
| medium | do_nothing | 30 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.645 | 0% [0%, 0%] | -0.645 ± 0.087 | 0.000 | **0% [0%, 0%]** |
| medium | stop_early | 30 | -0.933 ± 0.131 | 0.03 | 1.00 | 1.0 | 0.05 | 0.645 | -145% [-175%, -118%] | -1.578 ± 0.160 | -0.900 | **-140% [-163%, -125%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.322 ± 0.199 | 0.83 | 0.97 | 13.2 | 0.88 | 0.499 | 65% [24%, 98%] | -0.177 ± 0.194 | 0.360 | **72% [52%, 91%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 30 | 0.279 ± 0.180 | 0.70 | 0.80 | 13.2 | 0.87 | 0.499 | 56% [19%, 87%] | -0.220 ± 0.174 | 0.277 | **55% [34%, 77%]** |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 22 | 0.493 ± 0.153 | 0.95 | 1.00 | 12.0 | 0.94 | 0.457 | 108% [62%, 189%] | 0.036 ± 0.236 | 0.473 | **98% [75%, 123%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family; the API reports modelVersion gemini-3.6-flash for this id) | 30 | 0.373 ± 0.177 | 0.90 | 1.00 | 12.7 | 0.71 | 0.499 | 75% [36%, 123%] | -0.126 ± 0.221 | 0.110 | **22% [-23%, 63%]** |
| hard | reference solver | 30 | 0.499 ± 0.119 | 0.97 | 1.00 | 10.6 | 0.97 | 0.499 | – | – | 0.499 | – |
| hard | heuristic | 30 | 0.086 ± 0.204 | 0.80 | 1.00 | 14.4 | 0.78 | 0.499 | 17% [-26%, 60%] | -0.413 ± 0.250 | 0.052 | **10% [-20%, 37%]** |
| hard | do_nothing | 30 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.499 | 0% [0%, 0%] | -0.499 ± 0.119 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 30 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.499 | -200% [-271%, -167%] | -1.499 ± 0.119 | -0.950 | **-190% [-218%, -169%]** |
