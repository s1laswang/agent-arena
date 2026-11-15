# Final submission validation — 15 November 2026

Validation used a clean checkout in `/private/tmp/junction-final-arena`. Original worktrees and their uncommitted changes were preserved. No live model or GPU experiment was started.

| Check | Result |
|---|---|
| Full keyless regression suite after primary integration fixes | 1,187 passed, 15 skipped; no failures (276.58 s) |
| Final `make accept` | 20 PASS, 0 FAIL; one explicit live Harbor/model-key skip |
| Imported video checks | 7 passed; H.264 video duration 75.0 seconds |
| DAgger expert self-test | 2,603 steps, zero mismatches (509 easy, 903 medium, 1,191 hard) |
| Post-merge replay, replication, submission-audit, failure-analysis and video checks | 50 passed |
| Static submission audit after merging concurrent updates | 3 PASS, 1 WARN, 0 FAIL |
| Frozen environment/rules/solver/Harbor diff against `afterquery-final` | Empty |

The audit warning is the disclosed historical infrastructure-invalid episodes, retained but excluded from valid results. The full suite skips optional dependencies/services; it is not a new live-provider evaluation. The DAgger and video additions were validated separately after the full-suite run. The concurrent upstream merge brought the final exact-tag rehearsal and reporting updates; the affected report/replay tests were rerun afterward.

The exact-tag Harbor rehearsal is recorded in `results/harbor/rehearsal/TABLE.md`: 27 valid model trials (10/10/7), one excluded provider-rate-limit trial, two not launched. It did not reproduce the original MCP-only deficit. The earlier FR8 rehearsal is a different build and has only 10/30 valid model trials. Both remain separate in the submission.

The final package adds recorded paired Gemini-family runs, preserves the recovered GPT-5.5 run, keeps the two hinted episodes outside the primary cohort, includes the completed Verda/DAgger report and demo, and corrects stale submission claims. It does not change the frozen judge environment.
