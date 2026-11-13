# Pitch notes: Blind Spot

## The one-liner

"What does it cost a company when its AI employee pays a fake invoice?" Companies are handing
back-office work to AI agents. The failures that ruin companies are rarely movie villains: they are
an extra zero (Mizuho, Citi, Deutsche Bank), a unit nobody wrote down (Mars Climate Orbiter), a
spreadsheet range that stopped five rows early (Reinhart-Rogoff, London Whale), a check everyone
stopped doing because it never mattered (Challenger), six eyes that each assumed the others looked
(Citi/Revlon), and a familiar-looking email from a supplier (Facebook and Google, >USD 100m).
Blind Spot measures whether an AI agent catches these, or causes them.

## Story for the 10-minute demo

1. **The research (1 min).** 38 real cases with sources, from Barings to Wirecard. Pattern table:
   mechanism -> warning signal that existed -> control that would have caught it.
2. **The day (2 min).** Kestrel Components Oy, an AP queue of 7-9 tickets. Show one hazard and its
   benign twin side by side: the same wording, different records. "No trick wording: the answer is
   one tool call away."
3. **The honest clerk on autopilot (1 min).** Does exactly what tickets say: 100% of valid work done,
   0% of hazards caught, EUR 570k lost over 30 days. Reward 0.30 (only clean days).
4. **Frontier agent vs reference (3 min).** Gemini as plain staff vs the same Gemini inside the
   reference procedure (plan the whole queue, run the controls before anything irreversible), plus
   the scripted oracle at 1.00 that proves every day is solvable with the tools alone. Per-family
   catch rates show WHERE the agent fails (split payments across tickets, spreadsheet totals and
   stale lists are the hardest because the signal is spread over two records).
5. **Try to cheat it (2 min).** Do nothing, stop early, refuse all, escalate all, claim in chat,
   pay-by-the-records, hedge with flags, change-then-revert bank details: all 0.
6. **Gemini (1 min).** Plays the employee, writes the hazard variants, reads the transcripts to name
   failure modes.

## Why it matters (business story)

- BEC alone: the FBI's IC3 counts it among the costliest cybercrime categories every year (cite the
  current IC3 report figure on the slide; not yet sourced in our dataset).
- The controls in the handbook (three-way match, callback on file, approval limits, four-eyes) are
  standard internal-control practice. The environment tests whether an AI applies them when the
  queue looks routine, which is exactly when humans stop applying them.

## Lines for Q&A

- "Isn't the handbook giving it away?" Real companies have handbooks; humans who have read them still
  pay fake invoices. The difficulty is noticing which of nine routine tickets is the one.
- "Why binary reward?" One wrong payment is the whole story; partial metrics are reported next to it.
- "Is any of it real?" Every hazard family maps to real cases in `data/failures/`; the company and
  numbers are synthetic and labelled as such.
