# Judge scorecard

Rubric: AfterQuery "Break the Agent" (gap 30, difficulty 30, integrity 25, craft 15) and Silas's bake-off rubric (same axes, `origin/justSilas-grok-bakeoff3:docs/reports/grok-bakeoff3.md`).
Labels: VERIFIED = I ran it (2026-11-14, momin 814a723, `SLEEPER_OFFLINE=1`, scripted only). CITED = from bake-off 3, not re-run by me. Scorecard v1 14:10, corrected 15:23 Helsinki (see section C notes). Not yet done by me: fresh clone, own 15-min exploit hunt (next version).

## A. Which of our assets have landed in Canary (origin/justSilas 5813bb2)

Chief decision: the submission is the merged Canary (Plan v3). Checked by `git ls-tree` and `git grep` on justSilas.

| Asset (from docs/IDEAS.md) | Landed? | Evidence |
|---|---|---|
| Leak detector over 79 encodings | NO | no file or `base64/base32/acrostic` match in `*.py` |
| Cheat corpus + single verifier `rescore` | NO | `rescore` not found |
| Multi-seat company / accomplices | NO | no `sleeper`, `seat`, `accomplice` path |
| Frontier runners with cache/replay/provenance | PARTIAL, theirs only | `canary/agents/frontier/opencode_run.py`, committed runs under `data/runs/committed/`; ours not there |
| Failure analysis | NO | no failure-gallery file (their analyst is planned, NEXT-LEVEL WS "agents2") |
| Office replay dashboard | NO | no dashboard/replay path |
| Vaishnav anti-cheat battery | NOT YET | planned as top priority in NEXT-LEVEL.md, not in tree |
Owner for landing: lead-demo with Silas. Until these land, "merged Canary" scores as plain Canary.

## B. Canary on justSilas (CITED, bake-off 3 on f56cc1d; tip now 5813bb2, docs-only change since)

| Axis | Score | Points lost and why | Owner | Fix |
|---|---|---|---|---|
| Gap /30 | 8 | Codex gpt-5.5 over MCP is 1.06x solver on v1.3 hard (n=11, 11/11 correct); medium 0.55 CI -8..104%; v1.4 has no frontier run | Silas / lead-lab | v1.4 gemini-4-carbon n>=20 per tier (their Gate A 17:00) |
| Difficulty /30 | 20 | v1.4 hard: heuristic 90% accurate, +0.196 vs solver +0.516, collapse not restored | Silas | v1.5 bias layer gated 20:00 |
| Integrity /25 | 22 | container not booted in the judge's run (now booted by harness2: oracle 0.78/0.66, do_nothing 0, stop_early -1, isolation 11/11); `CANARY_SEED` in `/proc` environ | Silas | anti-cheat port, `CANARY_EPISODE_FILE` |
| Craft /15 | 12 | OpenCode infra failures averaged into a mean (fixed in 8970ead, reproduce drops invalid); heuristic-hard outside band | Silas | rerun `repro_spread.py 30` on final commit |
Total 62 (their sheet). My expected re-score on 5813bb2: integrity 23-24, craft 13 if the reproduce fix holds; gap unchanged.

## C. The Sleeper on momin (VERIFIED where marked)

Commands: `SLEEPER_OFFLINE=1 python -m lab.eval` (exit 0), all PASS self-checks (VERIFIED). README one command is `make eval`; see craft risk below.

| Axis | AfterQuery score | Points lost and why | Owner | Fix |
|---|---|---|---|---|
| Gap /30 | 9 | No real frontier run in the tree: every row scripted (VERIFIED, README "Real frontier runs: NOT FOUND"). Scripted gap is real: reference 0.550 vs staff 0.250, oracle 1.000 (VERIFIED). Judge seat finance_ap: oracle 0.800 overall, 0.750 on 16 needs-seat days; reference 0.400/0.250, staff 0.200/0.000 (VERIFIED) | lead-lab | real paired runs, n>=30, row in `web/results/frontier/gaptable.json`; real runs must be replayable by judges (`make frontier-replay-run`, lab-cluster, pending): open craft point |
| Difficulty /30 | 18 | 45 of 45 staff losses labelled (VERIFIED, REPORT.md): missed_slow_burn 15 labels, edited_contract_on_chat_request 18, wrong_accusation 9. Judge seat still partly unwinnable: oracle 0.75, four 0 days (CITED days 1003/1008/1013/1018, vendor_new) | lead-env | fix seat-mode background so oracle is 1.000 at finance_ap |
| Integrity /25 | 17 | do_nothing, stop_early, quarantine_all, refuse_all, trust_all all 0.000 (VERIFIED). Lost: shared verifier + `chmod 777 /logs` (xfail x73) and `harbor lint` failing (CITED); 20 failing tests (CITED, not re-run) | lead-reward | separate verifier or close /logs; green pytest |
| Craft /15 | 9 | One command works only with `SLEEPER_OFFLINE=1`/empty key on this box: plain `make eval` hung 24 min (VERIFIED, cause probably live Gemini via `agents/gemini.py` loading `~/arena-agents/.env` at import). A judge with a key in env hits live calls. README numbers now match `make eval` (fixed in 7a6e364, 8b5f171); pitch/ docs still stale | lead-harness / lead-lab, dm-pitch for pitch/ | conftest + `GEMINI_API_KEY=` default, refresh pitch numbers, green pytest |
Total AfterQuery estimate: 53/100 (bake-off 3 sheet: 51).

Bake-off rubric view of The Sleeper: gap 10, difficulty 17, integrity 15, craft 9 = 51 (CITED); my VERIFIED reruns do not move it, except finance_ap oracle 0.75 (already counted).

## D. Open craft points to track
1. Real frontier runs not replayable by judges (owner lead-lab; fix = `make frontier-replay-run`, add to README when dm-qa confirms on a fresh clone).
2. Key-in-env makes pytest/eval call live Gemini (owner lead-harness/lead-lab).
3. pitch/ numbers stale (owner dm-pitch).
4. Merged-Canary assets not landed (owner lead-demo).

## E. Corrections 15:23 (momin 5c3c8b0 / 357214a7, reported by lead-env and lead-lab)
- Section C was written from my 814a723 run and bake-off 3. Since then: finance_ap oracle reported 1.000 on needs-seat days (lead-env; gaptable on momin shows oracle 1.000 on 1000-1019 x3); Harbor verifier is `environment_mode = "separate"`, lint exit 0, oracle 1 / nop 0 / exploit agent 0 (file `results/harbor/separate-verifier-runs.txt`, checked). So integrity loses less (x73 and chmod 777 /logs points closed on the branch) and difficulty loses less (four zero days fixed, per lead-env). Expected re-score: difficulty 20-22, integrity 20-21. Not re-run by me yet.
- Gap: real rows exist (Gemini 3.5 Flash 1/15, Gemini 4 Carbon 0/15, rescored, replayable tarballs) but show `pending` in the headline gaptable until the bg_version tag fix lands, and n is small. Gap about 12-14 if the table shows them, still below Canary's potential at n>=20.
- Craft point D.1 (replay): `make frontier-replay-run` exists in the Makefile; dm-qa fresh-clone confirmation still pending. D.2 (key in env): lead-harness fix 67ec06b, dm-qa keyless fresh clone pending.
