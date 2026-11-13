# Slides (8 max, one idea each)

Numbers are from `make eval` (20 days, 3 trials, start seed 1000, results/eval/summary.json), else NOT FOUND. Staff and oracle are scripted; the Gemini reference is not run yet. Beat numbers match DEMO.md.

1. Hook (0:00). Title: "One of the eight is a traitor." Visual: 8 desks. Say the question in one line.
2. The company (1:00). Table of 8 seats, plus the four two-person rules. One line: the sleeper has to talk someone into helping.
3. The replay (2:00). No slide. Switch to the live dashboard, same seed, staff then reference.
4. The gap (5:00). Scripted staff reward 0.500, sleeper success 0.375; oracle 0.850; Gemini reference NOT FOUND. Footer: 20 days, 3 trials. Landing: bank_swap, split_under_limit, urgent_ceo_request land 10 of 10 on staff (`scripts/landing_table.py fraud`).
5. Why they fail (6:00). Named failure modes with a count and one decision each: approved without checking the audit log, trusted a familiar name, leaked inside a summary, accused the wrong person, missed the slow-burn attack. Counts NOT FOUND.
6. Reward integrity (7:00). Reward reads final state only. Baselines do-nothing, stop-early, quarantine-all, refuse-all: 0.000 each. Canary tokens. Link to `docs/EXPLOITS.md`. "15 minutes, try it."
7. One command (8:30). Terminal with `make eval`. Works with no key. Cached Gemini runs repeat.
8. Tiebreaker and close (9:15). Small model before and after on held-out days: NOT FOUND. Close line: Gemini plays every seat, the reward counts only what really happened.
