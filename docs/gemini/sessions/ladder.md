# Session brief: LADDER (worktree ~/junction-aimo-team/wt/gemini-ladder, branch gemini-ladder)
Read COMMON.md (same folder) first. Previous engineer's report: docs/gemini/reports/ladder.md (latest entry Sat 19:01).

State (Sat 20:40):
- The grid runs as background processes on the Mac, writing to ~/agent-arena-data/gemini/ladder/ladder-v14. `bin/phase4.sh` may have fired.
- Untracked: results/gemini/replay-ladder-showcase/ (a showcase recording, 6 cells; check that its manifest exists).
- Report v1.1 with an auto headline (`ladder_report.headline`, CI-gated wording). Keyless exports: results/gemini/ladder_episodes.jsonl.gz + ladder_ledger.jsonl.gz. `bin/refresh.sh` re-exports and commits.

Tasks:
1. `ps` for live ladder processes and count finished episodes per cell. Re-queue anything lost to infra failures (resumable).
2. Commit the showcase replay once `python -m canary.gemini.lab_replay` reproduces it keyless (≤20 MB).
3. **By 00:45:** run `bin/refresh.sh`. Final results/gemini/ladder.{md,json} + figures, with ≥6 paired seeds per headline cell on both tiers (3.5-flash medium/high, 3.8-flash low/high) and carbon low/high n≥4 on hard if possible. Push.
4. Leave the grid running. At **05:00** run `bin/refresh.sh` again, push, then stop the ladder processes (by PID, your own processes only).
