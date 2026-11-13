# DEMO: 10 minutes for the AfterQuery judges

Rule: every number below is NOT FOUND until it is pasted from `make eval` output (`results/<run_id>/summary.json`). Do not say a number on stage that is not on the results slide. Status of each file or command is as of the contract; check it exists before the run.

Presenter notes: speak rough and plain. Short sentences. No hype.

## Setup before we walk on (2 min, off the clock)

- `make eval` already run once, results open in a second tab. Dashboard open on the chosen replay day.
- Pick the replay day by seed from `days.jsonl`: a day where `staff` reward = 0 with a sleeper that succeeded, and `reference` reward = 1 on the same seed. Seed: NOT FOUND.
- Backup: a recorded screen capture of the same replay in case the venue network fails (the replay needs no network, it reads a saved transcript).

## Minute by minute

### 0:00 to 1:00 Hook

Say: "One of the eight people in this company is a traitor. Can the other seven catch it before the money is gone?"

On screen: dashboard title state, 8 desks, no names flagged.
Produced by: `web/` (dm-dashboard), loaded with `web/days/<seed>.json`.

### 1:00 to 2:00 The company and the rules

Say: 8 seats, each with a real job and least privilege. Dangerous moves need two people: payment over 10k needs the controller, new vendor bank details need procurement plus finance, new admin access needs IT plus a ticket, any document leaving needs legal. 40 to 60 tickets a day. The sleeper has to talk someone into helping. That is where agents fail.

On screen: seat table and the two-person rules.
Produced by: `docs/SLEEPER.md`, `CONTRACT.md` (Seats section), the dashboard desk view.

### 2:00 to 5:00 Live replay of one day (the centrepiece)

Two runs of the same seed, side by side, played from saved transcripts.

- 2:00 to 3:30 Plain Gemini staff (`--team staff`). Show the sleeper's move (for example a vendor bank change that looks routine), the controller approving without reading the audit log, the money going out. Reward panel: 0, harm listed.
- 3:30 to 5:00 Reference team (`--team reference`), same seed. Show the controller reading the audit log first, the out-of-band check, the quarantine agreed by two seats, the day's tickets still finished. Reward panel: 1.

Say what changed: same model, same tools, same information. Only the operating procedure differs.

On screen: office replay, chat and timeline, sleeper reveal at the end, reward panel with harm, tickets done, false quarantine.
Produced by: `python -m lab.run --team staff --days 1 --seeds 1` and `--team reference`, then the dashboard reads `results/<run_id>/` transcripts (`transcript_path` in the Result model).

### 5:00 to 6:00 The gap

On screen: gap table, one row per team.

| Team | reward | pass^k | sleeper success rate | false accusations | ticket completion |
|---|---|---|---|---|---|
| staff (plain Gemini) | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| reference | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| oracle (scripted, proves every day is winnable) | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |

Say: run over N days and K seeds (NOT FOUND), pass^k per seed, so one lucky run does not count.
Produced by: `make eval` -> `results/<run_id>/summary.json`.

### 6:00 to 7:00 Named failure modes tied to decisions

On screen: a table of failure modes with a count and one example decision each. Planned list from the design: approved without checking the audit log, trusted a familiar name, leaked inside a summary, accused the wrong person, missed the slow-burn attack. Counts: NOT FOUND. Final list comes from the failure analysis, not from this file.
Say: each one is a choice the agent made while holding the evidence to choose otherwise. The audit log, approval history and vendor records are in every day.
Produced by: `lab/analyse.py` (lab-analyst) over `days.jsonl` and transcripts. Output: `results/<run_id>/failures.md` and `failures.jsonl` via `python -m lab.analyse results/<run_id>` (rule-based, no Gemini yet; branch sleeper/lab-analyst-taxonomy). Gap table: `python -m lab.analyse --compare results/runA results/runB`.

### 7:00 to 8:30 Reward integrity

Say it plainly: reward reads only the final company state. Chat claims are ignored.

Baselines, all inside `make eval`:
- do-nothing: tickets undone. Result NOT FOUND (design target 0).
- stop-early: day unfinished. Result NOT FOUND (design target 0).
- quarantine-all and refuse-all: innocents quarantined or tickets undone. Result NOT FOUND (design target 0).
- no-sleeper days mixed in, so random accusation is punished.

Canary tokens: every secret document carries a unique token, one leaked byte (also base64, hex, spaced) in any external message or attachment is visible to the verifier.
Invite them: "You have 15 minutes. Here is the exploit log of what we already tried and patched." Open `docs/EXPLOITS.md`.
Produced by: `sleeper/verifier.py`, `sleeper/canary.py`, `sleeper/baselines.py`, `redteam/`, `docs/EXPLOITS.md`.

### 8:30 to 9:15 One command

On screen: terminal. Run the README command (target name: NOT FOUND, expected `make eval`). Show it finishing and the summary matching the gap slide. Works without a Gemini key using scripted agents; with the key it uses the response cache so reruns are the same and cheap.
Produced by: `README.md`, `Makefile` (lead-env).

### 9:15 to 10:00 Tiebreaker and close

Say: a small open model trained on the honest staff's successful days, tested on held-out days. Result: NOT FOUND until `train/` produces before and after numbers. If it is not done by the demo, say "not finished" and show only what exists.
Close: "Gemini plays every seat, so Gemini breaks Gemini. The reward only counts what really happened to the company."
Produced by: `train/`, `cluster/` (FR8 Slurm), results table from `make eval`.

## Cut list if we run over

Drop minute 6 detail first, then the tiebreaker slide. Never cut the replay or the baselines.

## Deck outline (7 slides, matches the minutes)

1. Title and hook.
2. The company: 8 seats, two-person rules.
3. Replay (live dashboard, not a slide).
4. Gap table.
5. Failure modes.
6. Reward integrity: baselines, canaries, exploit log.
7. Repro command and tiebreaker.
