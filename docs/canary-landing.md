# Landing our assets in the merged Canary

Rule: notes only. Nothing here is pushed to justSilas*. Silas owns the merge; each port is an idea or a PR he approves. Sources: `git ls-tree`/`git show origin/momin`, `origin/justSilas` 5813bb2, `docs/agents/NEXT-LEVEL.md` (Plan v3). Line counts are `wc -l` on momin b1acd2c.
Silas's gates: A 17:00 (gemini-4-carbon v1.4 n>=20 per tier, v1.5 solver numbers, RL-mole curve), B 20:00 (ship or drop v1.5, feature freeze). Points are my estimate on the AfterQuery rubric for Canary (bake-off 3: gap 8, difficulty 20, integrity 22, craft 12).
Fit warning: the Sleeper is a many-seat company with tickets and an exfil surface. Canary has one agent and one accusation. Assets tied to tickets, seats or outgoing mail do not drop in; the idea ports, the code does not.

## Ranked, points per hour (best first)

| # | Asset | Axis, points | Hours | pts/h | Owner | Lands by |
|---|---|---|---|---|---|---|
| 1 | Failure gallery | difficulty +2 to +3 | 2 | 1.2 | lab | Gate A |
| 2 | Integrity probes + cheat corpus ideas | integrity +1 to +2 | 1.5 | 1.0 | reward | Gate A |
| 3 | Frontier runner with cache/replay/provenance | gap up to +4 (outcome-dependent), craft +1 | 3 | 0.8 | lab | Gate B |
| 4 | Office replay dashboard | craft +1, peer-review round (not AfterQuery points) | 3 | 0.3 | demo | Gate B |
| 5 | Single verifier + rescore | integrity +1 | 3 | 0.3 | reward | Gate B |
| 6 | Multi-seat company / accomplices | difficulty +2, only if it makes frontier agents fail | 8+ | 0.25 | attack | after B, v1.6 |
| 7 | Leak detector over 79 encodings | integrity ~0 on Canary alone | 4 | ~0 | reward | only with #6 |

## Per asset

### 1. Failure gallery
- What: every lost day gets a named mistake tied to a ledger action, with the information available then, plus one annotated example per label. Our run: 45 of 45 staff losses labelled, 0 unexplained, gallery per label.
- Files on momin: `lab/analyse.py` (399), `lab/report.py` (213), `sleeper/regret.py` (154), outputs `results/eval/REPORT.md`, `gallery.md`, `docs/FAILURES.md`.
- Buys: difficulty. Silas lost 10 there because failure tags came from a truncated scaffold and v1.4 hard shows a 90%-accurate heuristic (bake-off 3). A gallery over the full-history Codex and gemini-4-carbon transcripts shows decisions, not infra.
- Dependencies: Canary's own `canary/analysis/tags.py`, `accuse.py`, `import_transcript.py` and the regret files already exist; Silas's AGENTS brief plans a Gemini failure analyst writing `docs/reports/failure_gallery.md`. Our labels (tickets, seats) do not map to Canary.
- Port: do not port code. Give Silas the format (label, count, decision, info available, day/action/posterior, what the solver did) and the "every label has an example, every loss has a label" self-check. ~2 h on his side, 0.5 h ours.
- Owner: lab.

### 2. Integrity probes and cheat corpus
- What: a probe table printed by the one command (`make probes`, 1m04s: all probe rows 0.0 except `control_pad` 1.0) and a cheat corpus (1440 cheating runs = 0, 265,161-episode random search found no reward 1, per docs/IDEAS.md).
- Files: `scripts/probes.py` (213), `redteam/cheat_corpus.py` (69), `redteam/cheat_eval.py` (103), `redteam/harbor_attack.py`, `redteam/logs_race.sh`.
- Buys: integrity. Silas is already porting Poisoned Inbox's battery as his top priority (NEXT-LEVEL.md). Ours adds the `control_pad` control (do the job, then burn the budget, must still score) and a logs-race attack on the reward file; he lists both ideas. We add Canary-specific attacks: accuse after end, parallel accuse, variant-per-person.
- Dependencies: none; probes talk to the MCP tools.
- Port: send the list of attacks and the control idea as a text note to Silas/Vaishnav; they implement. ~1 h to write, ~1.5 h to land.
- Owner: reward.

### 3. Frontier runner with cache, replay, provenance
- What: runners for Gemini 4 Carbon (thought-signature handling), `claude -p`, `codex exec`; a per-run cache tarball so a judge replays a REAL row offline with the key blank; a gap table with model id, commit, provenance, invalid and capped columns.
- Files: `lab/frontier.py` (72), `lab/frontier_rows.py`, `lab/gaptable.py` (320), `lab/replay.py` (23), `scripts/gemini_cache.py`, `scripts/frontier_baselines.py`, `web/results/frontier/gaptable.json` (all rows still `pending` on momin at b1acd2c).
- Buys: gap and craft. A second, independent real run of gemini-4-carbon against Canary's MCP server on v1.4 replicates Silas's Gate A number, so a judge sees two harnesses agree. Craft: keyless replay of every REAL row. Gap points only if the run shows a frontier agent below the reference; if it ties, the honest table still beats `pending`.
- Dependencies: a Gemini key with an explicit flag (never from `.env`), Canary's MCP server and `CANARY_WORLD_SECRET` handling, Silas's `canary/agents/frontier/opencode_run.py` already exists, so overlap risk is high: coordinate with his measurement engineer to avoid double spend. `frontier-replay-run` is not confirmed yet (lab-cluster, dm-qa).
- Port: runner glue ~1.5 h, table format ~1 h, cache tarballs ~0.5 h. Output only, no change to his rules.
- Owner: lab.

### 4. Office replay dashboard
- What: browser replay of a day: who did what, the chat, the compare view (`web/replay.html` 40 lines plus `web/results.js`, fixtures).
- Files: `web/replay.html`, `web/results.html`, `web/results.js`, `lab/replay.py`; pitch capture in `pitch/capture/`.
- Buys: craft and the peer-review round; Silas already plans a Pyodide "beat the AI" game and has `justSilas-grok-viewer` (offline replay viewer for Canary episodes). Our view is Sleeper-shaped (seats, tickets).
- Dependencies: Canary episode jsonl schema, Silas's WS6 game.
- Port: new data adapter ~3 h. Low priority until Gate B.
- Owner: demo.

### 5. Single verifier and `rescore`
- What: one fail-closed function that grades the final state, re-run by `rescore` over any recorded run.
- Files: `sleeper/verifier.py` (396), `sleeper/baselines*.py`.
- Buys: integrity. Canary already grades from the server ledger and Silas is adding replay consistency (every committed episode re-played and re-graded). Our verifier is ticket and harm specific. Adopt the idea only: grader exception is a failure, tool results are detached copies.
- Port: idea only ~1 h to write, none for code.
- Owner: reward.

### 6. Multi-seat company and accomplices
- What: 8 seats in one company; the sleeper recruits accomplices and frames coworkers.
- Files: `sleeper/company.py` (489), `sleeper/days/`, `sleeper/goals/` (7 files), `sleeper/day.py`, `sleeper/daymix.py`, `sleeper/mcp_server.py`.
- Buys: difficulty, only if it makes frontier agents fail. Silas's v1.5 candidate (rumours, grudge pairs, authority-bias accusation, `seed_rumour`) targets the same; his Mole DSL could take a `recruit_accomplice` action. Freeze risk: v1.4 hash `a8f99c2537c91d72` must not change; a new tier needs his go.
- Port: 8+ h, after Gate B as v1.6 at best.
- Owner: attack.

### 7. Leak detector over 79 encodings
- What: catches secrets in outgoing text under base64/32/85, hex, acrostic, morse, every-Nth-char, splits across messages.
- File: `redteam/leak_variants.py` (143), `sleeper/goals/leak.py`.
- Buys: nothing on Canary alone: the Canary agent has no outgoing channel for secrets. Useful only if #6 lands, and as a check on the mole's leak channel.
- Owner: reward.

## Honest read
- Two of the cheapest items (#1, #2) are ideas Silas implements himself in his own code. Do not offer code: write the notes, he decides.
- The only item that can win real gap points is a real, repeated frontier run (#3). It competes with his Gate A measurement, so run it as replication on a fixed seed list, not as another headline.
- Nothing of ours is on justSilas as of 5813bb2 (scorecard section A).
