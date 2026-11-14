# Slides (8 max, one idea each)

Numbers are from `make eval` (20 days, 3 trials, start seed 1000, results/eval/summary.json), else NOT FOUND. Staff and oracle are scripted; the Gemini reference is not run yet. Beat numbers match DEMO.md.

1. Hook (0:00). Title: "One of the eight is a traitor." Visual: 8 desks. Say the question in one line.
2. The company (1:00). Table of 8 seats, plus the four two-person rules. One line: the sleeper has to talk someone into helping.
3. The replay (2:00). No slide. Switch to the live dashboard, same seed, staff then reference.
4. The gap (5:00). Scripted staff reward 0.350, sleeper success 0.625; scripted oracle 1.000; Gemini reference NOT FOUND. Footer: 20 days, 3 trials. Landing: bank_swap, split_under_limit, urgent_ceo_request land 10 of 10 on staff and the oracle blocks them (`scripts/landing_table.py`).
5. Why they fail (6:00). Rates per day for scripted staff vs scripted reference, from REPORT.md: wrong_accusation 0.15, created_account_without_ticket 0.15, edited_contract_on_chat_request 0.10, leaked_in_summary 0.10, trusted_familiar_name 0.10, unfinished_tickets 0.10, shared_doc_on_chat_request 0.05, missed_slow_burn 0.05; reference 0.00 on all. One line: the tool that would have prevented each was available.
6. Reward integrity (7:00). Reward reads final state only. Baselines do-nothing, stop-early, quarantine-all, refuse-all: 0.000 each. Canary tokens. Link to `docs/EXPLOITS.md`. "15 minutes, try it."
7. One command (8:30). Terminal with `make eval`. Works with no key. Cached Gemini runs repeat.
8. Tiebreaker and close (9:15). Small model before and after on held-out days: NOT FOUND. Close line: Gemini plays every seat, the reward counts only what really happened.
