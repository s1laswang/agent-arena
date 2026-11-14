| run | seed | difficulty | reward | tickets | hazards caught | EUR lost | steps | failed |
|---|---|---|---|---|---|---|---|---|
| haiku_x2_s4 | 4 | expert | 0 | 12/13 | 3/4 | 7,452 | 72 | linked_split (hazard) |
| opus_x2_s3 | 3 | expert | 1 | 13/13 | 2/2 | 0 | 74 | - |
| opus_x2_s4 | 4 | expert | 1 | 13/13 | 4/4 | 0 | 80 | - |
| opus_x2_s5 | 5 | expert | 1 | 14/14 | 3/3 | 0 | 84 | - |

Expert tier v2 (handbook v4.5: the three expert rules stated as principles). Blind Claude
sub-agents, plain staff prompt, tools only. Opus caught 9/9 expert-day hazards; Haiku missed the
requisition split on seed 4 (paid phase 2, EUR 7,452 lost) while Opus solved the same day.
Two Opus runs broke the "one call at a time" instruction for a few unrelated write calls; the
session replay is still consistent (each call is recorded only after it completes).
