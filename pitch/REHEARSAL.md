# Rehearsal, timed dry run

Fresh clone of momin 359278a into a scratch folder, `GEMINI_API_KEY=` empty, shared `.venv`. Machine load average was 115 at start and 500 at the end, so command times are worst case. Speaking time is words divided by 140 per minute (counted from SCRIPT.md, bracketed stage directions excluded). Browser clicks were NOT run: no browser here, so click time is an estimate, labelled so.

## Commands and pages, measured

| Step | Command or page | Result | Time |
|---|---|---|---|
| server | `python -m http.server 8799 -d web` | index.html, replay.html?day=1-staff&vs=1-oracle, results.html, days/1-staff.json, days/1-oracle.json all HTTP 200 | each under 0.04 s |
| results page data | `web/results/eval/gap.md` | 404 in a fresh clone: the folder is written only by `make eval`, so results.html has no table until it has been run | n/a |
| backup | `python -m sleeper.transcript --seed 1 --team oracle` | prints the day and Result, reward 1, scripted | 2.7 s |
| `make eval` | plain, empty key | finished, REPLAY OK, tables printed | 10 min 3 s (load 115 to 500; README says about 2 min when idle) |
| `results/baselines/table.md` | | not in a fresh clone (needs `python -m sleeper.baselines`, part of `make eval-full`) | NOT FOUND |

## Beats: planned, actual, what broke

Planned = SCRIPT.md heading time. Actual speaking = words at 140 per minute after the cuts below. Click time is not measured.

| Beat | Words | Actual speaking | What broke or looked wrong |
|---|---|---|---|
| 0:00 real gap | 110 | 0:47 | REAL cells are NOT FOUND (lead-lab pending), so today this beat has nothing to read; use the fallback and go to the hook |
| Hook | 45 | 0:19 | none |
| 1:00 company | 136 | 0:58 | none |
| 2:00 replay | 216 | 1:33 | click time for Step and Reveal not measured. Page loads fine |
| 5:00 validated reward | 92 | 0:39 | needs `web/results/eval` from a run, else Results page is empty |
| 5:45 multi-model | 117 | 0:50 | placeholders only |
| 6:00 why they fail | 103 | 0:44 | counts are NOT FOUND until sourced |
| 7:00 reward integrity | 215 | 1:32 | baselines table not in a fresh clone, use the README table |
| 8:30 one command | 13 | 0:06 | do not run live: 10 min 3 s in this rehearsal |
| 9:15 close | 133 | 0:57 | training result NOT FOUND, say "not finished" |

Speaking total 8:25 after the cuts (10:03 before). Plus about 1:00 of clicking, estimated, so about 9:25, under the 9:30 limit but with no slack.

## Cuts and fixes made in SCRIPT.md

- Removed: the tickets-queue paragraph, "Our question is simple", the deterministic pass-hat-k note, the baseline-ignores-chat note, the key-and-cache paragraph, the analyse-output line, and the long ladder description. Shortened the "nothing is hidden" paragraph.
- `make eval` is shown from saved output, not run live.

## Before going on stage

1. Run `make eval` (and `python -m sleeper.baselines`) on an idle machine at least 15 minutes ahead so `web/results/eval` and `results/baselines/table.md` exist. Check the commit printed matches the slide.
2. Click the replay path once in a real browser and time it: NOT MEASURED here.
3. Fill the REAL cells or use the fallback.
