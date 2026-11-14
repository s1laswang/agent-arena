# Slides (8 max, one idea each)

Numbers are from `make eval` (20 days, 3 trials, start seed 1000, results/eval/summary.json), else NOT FOUND. Staff and oracle are scripted; the Gemini reference is not run yet. Beat numbers match DEMO.md.

1. Hook (0:00). Title: "One of the eight is a traitor." Visual: 8 desks. Say the question in one line.
2. The company (1:00). Table of 8 seats, plus the four two-person rules. One line: the sleeper has to talk someone into helping.
3. The replay (2:00). No slide. Switch to the live dashboard, same seed, staff then reference.
4. The gap (5:00). Scripted staff reward 0.250, sleeper success 0.938; scripted reference 0.550; scripted oracle 1.000 (make eval on momin 5634505, rerun on 814a723 NOT FOUND (killed under load)); Gemini reference NOT FOUND. Footer: 20 days, 3 trials. Landing table per strategy: `scripts/landing_table.py` (see DEMO). trust_all baseline scores 0.000 (make eval on momin 5634505, rerun on 814a723 NOT FOUND (killed under load)), below staff.
5. Why they fail (6:00). 39 of 39 staff losses carry a named mistake, 0 unexplained. Most common: created_account_without_ticket, edited_contract_on_chat_request, wrong_accusation (9 of 39 each). 33 of 39 losses (84%) flip to a win when one seat follows the oracle procedure. One line: the tool that would have prevented each was available.
6. Reward integrity (7:00). Reward reads final state only. Baselines do-nothing, stop-early, quarantine-all, refuse-all: 0.00 each. Canary tokens. Link to `docs/EXPLOITS.md`. "15 minutes, try it."
7. One command (8:30). Terminal with `make eval`. Works with no key. Cached Gemini runs repeat.
8. Tiebreaker and close (9:15). Small model before and after on held-out days: NOT FOUND. Close line: Gemini plays every seat, the reward counts only what really happened.
9. Multi-model gap table (5:45, after slide 4). Table and replay beat in `pitch/MULTIMODEL.md`. Rows are labelled REAL (model id, date, run id) or SCRIPTED. REAL cells: NOT FOUND (lead-lab pending). The seed 1 bank_swap and trust_all stories are SCRIPTED.
10. Opening slide, move to first (0:00 to 1:30): the multi-model gap table from slide 9 opens the talk. Scripted slides 4 to 6 become "how we validated the reward".
11. Skill ladder (reward integrity, 7:00): "reward rises with skill, and only the full procedure reaches the reference". Figures NOT FOUND (ladder.md not on momin yet).
