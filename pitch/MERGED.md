# MERGED: 10-minute script, Canary as the base

Draft by dm-pitch, 14 Nov, branch sleeper/dm-canary-pitch off momin b1acd2c. Not final: docs/canary-landing.md (dm-docs ranking) is not on momin yet, so every Sleeper beat below is marked "if landed".

Labels. CITED = a Canary number from Silas's branches, not rerun by us (source and commit shown). VERIFIED = we ran it (dm-qa or lead). SCRIPTED = Python teams, no model. REAL = model id, date, run id. A number with none of these is NOT FOUND. Tokens: `NOT FOUND (Silas pending)` = Canary run not published; `NOT FOUND (landing pending)` = Sleeper asset not yet in Canary. The gap is the headline.

Sources read, read-only: origin/justSilas (PLAN.md, 5813bb2 tip), origin/justSilas-grok-pitch (deck, 14 slides), docs/parallel-envs.md, docs/scorecard.md, docs/canary-watch.md.

## What the merged pitch is

Canary: the agent under test is the head of security of a company with a mole leaking documents. It reads logs, plants canary documents, accuses once. Reward is company value left if right, 0 if no accusation, -1 if wrong in the tier rules. Reference: a Bayesian canary-trap solver. Our contribution, as named beats if they land: multi-seat company replay, leak detector, single verifier rescore, cheat probes, frontier runners with replay, Gemini exploiter, failure gallery.

## Order of our "if landed" beats (docs/canary-landing.md, points per hour)

1 failure gallery (Gate A) in beat 3. 2 integrity probes and cheat corpus ideas (Gate A) in beat 5. 3 frontier runner with cache, replay and provenance (Gate B) in beats 1 and 4. 4 office replay dashboard (Gate B, provenance badge and legend on sleeper/dm-canary-viewer, in progress) in beat 4. 5 verifier and rescore in beat 5, last. 6 multi-seat company (v1.6) and 7 leak detector are OUT of the 10 minutes and sit on the backup slide at the end. A beat stays NOT FOUND (landing pending) until it is actually in Canary; lead-demo says when.

## Timing (target under 9:30)

| Beat | Time | Source |
|---|---|---|
| 1 Gap table (headline) | 0:00 to 1:30 | Canary frontier rows |
| 2 The company and the mole | 1:30 to 3:00 | Canary deck slides 3 to 6 |
| 3 Why they fail | 3:00 to 4:15 | Canary regret tags |
| 4 Replay | 4:15 to 5:30 | Canary run, or Sleeper dashboard if landed |
| 5 Reward integrity | 5:30 to 7:15 | Canary harness + our probes |
| 6 Gemini roles | 7:15 to 8:15 | pitch/GEMINI.md table |
| 7 One command, close | 8:15 to 9:15 | repro |

## Script

### Beat 1, 0:00 to 1:30. The gap

"One employee is leaking. You are the head of security. You get one accusation. We put frontier models in that chair and compared them with a solver that works only from what the chair can see."

Show the gap table. Rows, each labelled:

| Player | Label | Medium | Hard |
|---|---|---|---|
| Bayesian solver (reference) | CITED, justSilas, README 30-run mean (commit 21e5b2e) | +0.64 | +0.55 |
| Codex gpt-5.5 over MCP, v1.3 | CITED, docs/reports/gap.md (justSilas f56cc1d), n=11 each | 0.401, 55% of solver [CI -8, 104] | 0.655, 106% of solver [91, 136], 11 of 11 correct |
| gemini-4-carbon, v1.4, Harbor + OpenCode over MCP | CITED, Silas, justSilas commit 58f25318 (14 Nov 14:24), `harbor/README.md`, `results/harbor/`; judge seeds 900000 to 900002, 3 medium + 3 hard, n=6, same worlds as the oracle. Scores from the server ledger | mean over all 6: 0.503 vs oracle/solver 0.757 (difference -0.253), below the solver on 6 of 6 tasks | per-tier split: NOT FOUND (read from the table at 58f25318) |
| Claude (claude -p) | NOT FOUND (Silas pending) | NOT FOUND (Silas pending) | NOT FOUND (Silas pending) |

Say the small n out loud: the Gemini row is six episodes (3 medium, 3 hard), one model, one run, and Silas's own Gate A target is n of 20 or more per tier. In one medium episode (900002) Gemini never accused and scored 0 (per Silas's watch log, dm-docs). It is the first real frontier gap through the judges' own path.

Say the honest line: "On hard, Codex matches the solver. The gap holds on medium, with a wide interval. Silas's own report says the hard gap is not there, and v1.4 is meant to restore it. We show what is measured." If a larger gemini-4-carbon run lands, replace the n=6 row. If this row is withdrawn, use the fallback at the end.

### Beat 2, 1:30 to 3:00. The company and the mole

Company of employees, one mole, canary documents (different variants to different people), a leak feed that arrives late, one accusation. Words from Canary deck slides 3 to 6 (read-only source: justSilas-grok-pitch).

### Beat 3, 3:00 to 4:15. Why they fail

Canary regret tags: premature_accusation, decoy_chase, ignored_delay, uninformative_canary, over_restriction, budget_waste, no_accusation. Number: premature accusation is 97 to 99% of tagged value lost, no frontier episode abstained when abstaining beat the gamble (CITED, Silas's report in docs/parallel-envs.md). Fairness: a hinted agent closes the gap, a text-only probe scores about chance (design in PLAN.md; measured result NOT FOUND (Silas pending)).

Our failure gallery, ranked first: every lost day carries a named mistake tied to a ledger action and the information available then, and every label has an example. Port is the format, not code. Landed in Canary: NOT FOUND (landing pending). Our scripted run for the format: 45 of 45 staff losses labelled, 0 unexplained (SCRIPTED, scorecard citing REPORT.md at 814a723, not rerun at 1f6e1f0).

### Beat 4, 4:15 to 5:30. Replay

Canary's own run through its viewer, one investigation, accusation point on screen (justSilas-grok-viewer is Silas's offline viewer). Our provenance badge and legend (REAL or SCRIPTED, model id, commit on screen) are the dashboard beat: in progress on sleeper/dm-canary-viewer, NOT FOUND (landing pending). Keyless replay of a REAL row from its cache (frontier runner, ranked third): NOT FOUND (landing pending). Say every row's label out loud.

### Beat 5, 5:30 to 7:15. Reward integrity

- Canary harness: do_nothing 0, stop_early -1, isolation 11 of 11 (CITED, scorecard, harness2). Container boot status in the judge run: fixed per scorecard, recheck.
- Ranked second. Our cheat probes, VERIFIED by dm-qa: `make probes`, every probe 0.0 except the control control_pad at 1.0, and 730 committed runs rescored by the single verifier with 0 mismatches. Source: dm-qa, `make probes` on momin 1f6e1f0, 1m04s. Beat only if the probes or `rescore` landed in Canary: NOT FOUND (landing pending).
- Exploiter, REAL: gemini-3.5-flash, 10 seat-days (finance_ap, controller; days 1000 to 1004), 7 live, 572 calls, reward 0 on all, commit c460e0c, rescore 0 mismatches. Only if `redteam/` landed: NOT FOUND (landing pending).
- Ranked fifth, last in this beat: single verifier and `rescore`, idea only (a grader exception is a failure). The 730-run rescore above is our evidence. Landed: NOT FOUND (landing pending).
- Skill ladder: Canary plans `scripts/skill_ladder.py`, n of 400 or more per tier. NOT FOUND (Silas pending).
- Invite: "You have fifteen minutes. The exploit log is in the repo."

### Beat 6, 7:15 to 8:15. Gemini

Use the six-row role table in pitch/GEMINI.md exactly: exploiter REAL, the rest pending with owners. Canary's plan lists six Gemini jobs and a Mole Forge; say only the ones with a run. Mole Forge measured generations: NOT FOUND (Silas pending). Small model before and after: NOT FOUND (Silas pending).

### Beat 7, 8:15 to 9:15. One command and the close

Show saved output, never run live (a fresh-clone `make eval` took 10 min 3 s in the rehearsal). Canary repro: `python repro_spread.py 30` band, command name to confirm with Silas: NOT FOUND (Silas pending).

Close: "Frontier agents commit too early. We measured how much that costs, and the reward reads only what really happened."

## Fallback if no gemini-4-carbon number arrives

Two lines: "The gemini-4-carbon gap is six episodes, so treat it as an early signal, not a proven number." "Codex matches the solver on hard in Silas's v1.3 run, so the hard-tier gap is not established." "The scripted company numbers are separate, reproducible with `make eval`."

## Which of our beats survive

See HANDOFF section 0b. Keep: gap table, REAL/SCRIPTED labels, integrity beat in general, named failure beat. Only if landed: company replay, probes, rescore, exploiter, failure gallery, ladder.

## Backup slide (not in the 10 minutes)

Only if asked, all from the company setting, which is a separate setting from Canary and not landed (ranks 6 and 7, NOT FOUND (landing pending)):
- Multi-seat company with a sleeper and accomplices. SCRIPTED, make eval, momin 1f6e1f0 (dm-qa): all 8 seats oracle 1.000, reference 0.550, staff 0.250, do_nothing 0.000, stop_early 0.000. Finance_ap needs-seat: oracle 0.750, staff 0.000 (staff background, lead-env repairing): do not headline.
- Seed 1 bank_swap replay, SCRIPTED. trust_all baseline 0.000, SCRIPTED.
- Real replay: gemini-3.5-flash, finance_ap, seed 1004, REAL (ce5a8ce), ablation, no-sleeper day: pays P004 46,813.20 EUR with no matching ticket, controller approves, reward 0, reference 1, tickets 43 of 50 done correctly (48 marked closed).
- Leak detector over 79 encodings: integrity about 0 on Canary alone (docs/canary-landing.md).
