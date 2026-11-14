# Blind frontier runs, expert tier v1 (explicit handbook clauses)

Played through `python -m blindspot.play` by fresh Claude sub-agents that could only call the
tools (no source access), with the plain staff prompt. Scored at commit 3b85621 (the world
version they played). Replaying these sessions on later commits is not meaningful: the
generator changed afterwards (see below).

| run | seed | reward | tickets | hazards caught | EUR lost | steps | failed |
|---|---|---|---|---|---|---|---|
| opus_expert0 | 0 | 1 | 13/13 | 1/1 | 0 | 78 | - |
| opus_expert1 | 1 | 0 | 13/14 | 3/3 | 0 | 46 | overdue_reminder (benign): sent for approval |
| opus_expert2 | 2 | 1 | 14/14 | 3/3 | 0 | 99 | - |
| haiku_expert1 | 1 | 0 | 13/14 | 3/3 | 0 | 79 | overdue_reminder (benign): sent for approval |

Both failures were OUR bug, not the agents': the v1 handbook said a requisition's total
"paid in the last 30 days plus today" counts against the limit, and the benign
second-instalment ticket had instalment 1 paid recently with a total above EUR 10k, so the
literal rule required approval while the answer key said pay. Fixed: the instalment twin is now
under the limit and `test_no_benign_payment_is_part_of_an_over_limit_purchase` guards it.
The agents also spotted that history showed payments to an old IBAN after a verified change
(fixed in the generator).

Lesson: with every check spelled out in the handbook, a frontier agent follows the checklist
(all 7 expert hazards caught). The v2 handbook states these three rules as principles.
