# Session brief: SWARM (worktree ~/junction-aimo-team/wt/gemini-swarm, branch gemini-swarm)
Read COMMON.md (same folder) first. Previous engineer's report: docs/gemini/reports/swarm.md (latest entry Sat 18:42).

State (Sat 20:40):
- Done: v1 (35 whitebox), blackbox (16), positive control ("seed regeneration from public code", 4/4 re-found, verified). Wave 2 (24) and wave 2b (16) were running (escalation, hydrogen executor).
- Untracked: results/gemini/swarm_review_w2b008.json. The last engineer was about to "commit results, tests and report".

Tasks:
1. Check whether the wave 2/2b processes finished (ps; their output dirs). If one died, resume or close it out; count lost attempts as infra-invalid.
2. Audit wave 2/2b like v1: score from the ledger, audit against the reference posterior, fresh-seed confirmation for any candidate. **A verified exploit must go immediately to the top of the report, with a repro command.** The CEO escalates it; you do not patch env code.
3. **By 00:45:** one merged judge-facing results/gemini/swarm.md + swarm.json covering every wave (by-wave table, attack list by persona and name, positive control, hold-out tests), with tests green. Push.
