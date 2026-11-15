# Judge simulation (X3), Sun 15 Nov 03:06–03:52

Six cold Gemini judges (OpenCode, gemini-4-argon / gemini-4-hydrogen; carbon not used). Each one got only the AfterQuery rubric and the instruction "git clone -b justSilas https://github.com/s1laswang/agent-arena /tmp/judgeN; follow README.md literally". All of them judged commit `8cdc616f7f30`. This file covers judges 1–4. Judges 5 and 6 were still running when this was written, and their reports are in `/tmp/judge5-report.md` and `/tmp/judge6-report.md` on the team Mac. Judge 2 hit the hydrogen quota of 2M input tokens per minute twice, and its OpenCode session was resumed. Gemini CLI judges were not used, because the auto-mode permission classifier blocked `--yolo`.

## Scores

| judge | model | gap /30 | difficulty /30 | integrity /25 | craft /15 | total |
|---|---|---:|---:|---:|---:|---:|
| 1 (+ Harbor oracle/do_nothing, 2 tasks) | argon | 23 | 28 | 24 | 12 | 87 |
| 2 | hydrogen | 19 | 25 | 23 | 12 | 79 |
| 3 (also ran make test) | argon | 22 | 26 | 24 | 12 | 84 |
| 4 | hydrogen | 17 | 25 | 23 | 12 | 77 |

Run times on a loaded Mac: clone about 16 s, `make setup` 1–4 s, `make reproduce` 45–83 s, `make accept` 35–40 s. The first result appeared 87–111 s after the clone started. Every run exited 0, and accept reported PASS=20 FAIL=0 SKIP=1 each time. Judge 1's Harbor oracle and do_nothing jobs succeeded on the first try, with isolation at 11 checks and 0 findings.

## Ranked friction (count = judges out of 4 who flagged it)

| # | friction | count | status |
|---|---|---:|---|
| 1 | README:35 quoted the committed hard solver row as +0.625 ± 0.088, but the file says +0.553 ± 0.093 | 4 | fixed on justSilas (audit M1) |
| 2 | docs/CONTRACT.md §1–4 still state v0 rules: a wrong accusation scores 0, `status` shows true V, 30 judge seeds, stop_early means a day-1 guess. configs/README.md:13 also says 30 seeds | 4 | audit M7/M10, **open** |
| 3 | EXPLOITS and results/anticheat cite 37/37 Harbor trials and 13 jobs, but `make reproduce` prints 80/80 and 18 jobs | 4 | audit M3, **open** (regenerate the artifact) |
| 4 | "Gap not established" in harbor/README:210, PLAN.md:15 and HISTORY.md:24 contradicts the headline | 4 | fixed on justSilas (16a7e8d2) |
| 5 | README:101 says "13 scripted cheats", but the battery runs 14 attacks + 1 swarm | 4 | fixed here (audit M2) |
| 6 | No `make` target prints the headline 65% [24%, 98%]; it lives only in a committed table | 3 (implied by all 4) | fixed here: `make reproduce` recomputes it (bit-identical, 3 s) and fails on any drift |
| 7 | README:36 says `REPRO_ANTICHEAT=0` takes "about 10 s"; judges measured 22–75 s | 3 | fixed here |
| 8 | harbor/README:9 uses bare `python harbor/build.py`, which exits 127 on macOS | 3 | fixed here |
| 9 | `make accept` re-runs setup and reproduce, so the README's two lines do the same work twice | 3 | open (scripts/, out of scope) |
| 10 | The headline run is on dev seeds 0–29 outside Harbor; a Harbor run on judge seeds would be stronger | 3 | proposal to the CEO |
| 11 | The `slow act(): 0.33s > budget 0.30s` stderr line looks like an error | 3 | README now explains it |
| 12 | The Harbor sidecar compose file passes the host `GEMINI_API_KEY` even for the template provider | 3 | proposal to the CEO |
| 13 | README:25 discloses only empty-reply retries; meta.json lists 25 excluded hard attempts of 3 kinds | 2 | open |
| 14 | The accept MCP smoke check counts HTTP 400 as PASS with no note | 2 | open (scripts/) |
| 15 | The Harbor `opencode.json` allows `bash`/`python3`, but the headline OpenCode run denied them, so the two harnesses differ | 1 | **proposal to the CEO (material to the gap claim)** |
| 16 | `access_constraints` on hard is a no-op: clearance never binds | 2 | proposal to the CEO |
| 17 | EXPLOITS #25 vs #27 cross-reference (harbor/README:68, configs/README:19) | 1 | audit M6, open |

## Why craft got 12, not 15 (consensus)

The keyless one-command path works every time. Points were lost to stale or contradicting numbers in linked docs (#1–#5), the headline not being printed by any command (#6), and duplicated work in accept (#9).
