> **Headline findings (preliminary: 4–6 paired seeds per flash cell, 1–2 per gemini-4 cell; 95% CIs are wide, so read them as directions).**
>
> **gemini-3.5-flash with medium or high thinking matches the reference solver on hard.** It scores 91% [71%, 120%] and 102% [73%, 150%] of the solver on the same seeds, with 5/5 correct accusations in each cell, at $0.36–0.44 per episode. That is less than a third of a gemini-4-carbon episode on hard ($1.30–1.57).
>
> **gemini-3.1-flash-lite fails at every thinking level.** Its mean score is below the do-nothing score of 0 in all 8 cells, and at minimal thinking it accused the wrong employee in 8/8 episodes.
>
> **gemini-3.8-flash improves from low to high thinking on medium, but not on hard.** On medium it goes from −52% [−181%, 46%] to 92% [76%, 121%] of the solver; on hard it is 30% → 28%. Pooled over the flash models, low → high thinking mainly cuts premature-accusation regret (−0.16 per episode on medium, −0.10 on hard). Canary design does not improve: uninformative-canary regret on hard rises from 0.002 to 0.035.
