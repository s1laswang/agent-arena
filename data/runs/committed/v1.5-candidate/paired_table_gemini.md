| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 10 | 0.664 ± 0.051 | 1.00 | 1.00 | 9.8 | 0.94 | 0.615 | 108% [96%, 122%] | 0.049 ± 0.079 | 0.571 | **98% [69%, 124%]** |
| hard | OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply counted as 0 instead of retried | 10 | 0.600 ± 0.140 | 0.90 | 0.90 | 10.1 | 0.94 | 0.615 | 98% [79%, 113%] | -0.015 ± 0.110 | 0.510 | **88% [57%, 115%]** |
| hard | reference solver | 10 | 0.615 ± 0.068 | 1.00 | 1.00 | 8.7 | 0.98 | 0.615 | – | – | 0.580 | – |
| hard | heuristic | 10 | 0.137 ± 0.381 | 0.80 | 1.00 | 12.9 | 0.84 | 0.615 | 22% [-48%, 72%] | -0.478 ± 0.358 | 0.180 | **31% [7%, 47%]** |
| hard | do_nothing | 10 | 0.000 ± 0.000 | 0.00 | 0.00 | 0.0 | – | 0.615 | 0% [0%, 0%] | -0.615 ± 0.068 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 10 | -1.000 ± 0.000 | 0.00 | 1.00 | 1.0 | 0.03 | 0.615 | -163% [-182%, -148%] | -1.615 ± 0.068 | -0.950 | **-164% [-183%, -149%]** |
