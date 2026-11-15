# Briefs for the unlimited gemini-4-carbon session (Canary / AfterQuery), Sun 15 Nov ~02:00

Repo: s1laswang/agent-arena. Integration branch: `justSilas`; open PRs into it, never into main.

Rules for every brief:
- never push to main or momin; never force-push; never `pkill -f` or `killall` (kill only PIDs you started);
- never print or commit keys;
- never touch FR8 Slurm jobs.

**Quota rule:** from 06:30 to 08:15, keep gemini-4-carbon traffic near ZERO, because the judge rehearsal needs the carbon per-minute quota. Use Argon/Hydrogen in that window.

Ranked by score impact:

---

## G1. Extend the v1.4 hard gap to n=60 (Gap, 30 pts). Carbon. Start NOW, finish by 06:15.
```
Goal: tighten the headline gap. gemini-4-carbon via OpenCode over MCP on Canary v1.4 hard is at 65% [24%, 98%] of the reference solver at n=30 (seeds 0-29). Adding seeds 30-59 should make the paired difference exclude 0 at n=60. Seeds 30-59 were pre-registered as an EXTENSION in docs/reports/gap.md before any run.
Read first: README.md, docs/reports/gap.md (headline + pre-registered rules), scripts/gemini_runner.py (--help), data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json (how the primary set was run), scripts/gemini_finalize.sh, scripts/merge_staging.py, scripts/verify_replay.py, scripts/paired_gemini.py.
Setup: git -C ~/junction-aimo-team/agent-arena worktree add ../wt/g1-ext60 -b g1-ext60 origin/justSilas; cd there; copy .env from ~/junction-aimo-team/wt/justSilas/.env (never print it); make setup.
Do:
1. Run gemini-4-carbon, OpenCode harness (same settings as the primary set's meta.json), tier hard, rules v1.4, seeds 30-59, one episode per process, 8-10 in parallel, into its own staging dir. Infra-invalid attempts (empty reply, 429, CLI error) are retried, never counted. Never re-run a valid seed to get a better score.
2. Solver reference for seeds 30-59: python -m canary.eval --agent solver --tier hard --seeds 30-59 --provider template --out data/runs/committed/v1.4/reference/solver-hard-seeds30to59 (flatten into episodes.jsonl + meta.json like solver-hard-seeds20to29).
3. Merge with scripts/merge_staging.py into data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/ (a separate dir; the primary dir stays untouched), then verify_replay, then paired tables: (a) extension alone, (b) pooled 0-59.
4. Add a short "Extension (seeds 30-59)" row block under the headline in docs/reports/gap.md. Do NOT change the primary row.
Verify: every episode replay-verified; make test green; the numbers reproduce from the committed files.
Deliver: PR g1-ext60 → justSilas by 06:15, with the table in the PR body.
Parallel: 8-10 OpenCode episodes at a time (each takes 20-110 min). Model: gemini-4-carbon only (the claim is about that model).
```

## G2. A second and third frontier family on v1.4 hard (Gap: "not one model's quirk"). Argon + Hydrogen. Can run through 08:00.
```
Goal: show that the v1.4 hard gap holds across models. Run gemini-4-argon and gemini-4-hydrogen (exact model ids from the API's models.list) via OpenCode over MCP on Canary v1.4 hard, dev seeds 0-29, paired with the committed solver (data/runs/committed/v1.4/reference/solver-hard-*).
Read first: the same files as G1, plus data/runs/committed/v1.4/paired_table_gemini.md.
Setup: worktree ../wt/g2-families, branch g2-families off origin/justSilas; copy .env.
Do: for each model, run 30 episodes (8 in parallel, retry only infra-invalid); merge into data/runs/committed/v1.4/opencode-<model>/hard/; verify_replay; regenerate paired_table_gemini.md with the new rows (label every row with the API's reported modelVersion).
Verify: replay-verified, make test green.
Deliver: PR → justSilas by 08:00, with the table in the body. Report honestly whatever the ratio is.
Parallel: 2 models × 8 episodes. These have separate quotas from Carbon, so this can run during the rehearsal window.
```

## G3. Number QA: a hostile judge reads everything (Craft + Integrity). Argon. Run now, plus a re-pass at ~06:45 on the tag.
```
Goal: no number in any judge-facing doc may contradict a committed file. Judges will cross-check.
Read: README.md, docs/reports/gap.md, docs/reports/failure_analysis_v1.4.md, docs/DIFFICULTY.md, docs/EXPLOITS.md, harbor/README.md, docs/DEMO.md, docs/gemini/SUBMISSION.md, pitch/GEMINI.md, VERDA.md (if present).
Do: list every numeric claim (value, file:line), find the committed source file that produces it (data/runs/committed/**, results/**), and recompute or confirm it. Output docs/reports/number_audit.md: a table of claim | file:line | source | status (OK / MISMATCH / NO SOURCE). For each MISMATCH, propose the exact one-line fix.
Rules: do NOT edit the claims yourself; open a PR with only the audit file into justSilas (branch g3-numaudit) and list the mismatches in the PR body.
Parallel: one agent per doc (8 agents). Model: Argon (bulk reading), with Carbon only for disputed items, and not between 06:30 and 08:15.
```

## G4. A 1,000-attack red-team sweep on the final tag (Integrity 25 pts + Gemini prize). Hydrogen/Argon. Start after the tag (~06:30).
```
Goal: "1,000 Gemini attackers, 0 exploits" on the exact submitted SHA. Judges spend 15 minutes trying to reward-hack; we show we spent 1,000 attacker-episodes.
Read first: docs/EXPLOITS.md ("Judges: start here"), canary/redteam/ (anticheat.py, hunter.py, swarm_probes.py), canary/mcp_server.py, the swarm plan format in results/gemini/swarm.json (on branch gemini-swarm), docs/gemini/reports/swarm.md.
Setup: worktree at the tag afterquery-final (the CEO announces the SHA), branch g4-redteam.
Do: generate attacker plans with personas (reward hacker, protocol abuser, timing exploiter, info leaker, parallel-call racer, malformed-args fuzzer). Each plan is executed against the REAL MCP server (keyless dev seeds, CANARY_ALLOW_DEV=1) with scripts/judge_hunt.py-style harnessing. An attack "wins" only if it beats the solver on the same seed by more than noise AND cannot be explained by legitimate elimination (use the fixed exact-elimination audit from gemini-swarm 34d73c3). Re-verify any candidate win on ≥ 40 seeds before reporting it.
Deliver: results/redteam_1000/summary.md (n attempts, by persona, best score vs solver, every candidate and its refutation) and a PR → justSilas. Any CONFIRMED exploit: message "Arena · CEO" immediately; do not patch.
Parallel: 50-100 attacker agents. Model: Hydrogen/Argon for plan generation, no Carbon during 06:30-08:15.
```

## G5. If compute were free
- n=100 OpenCode carbon on v1.4 hard (seeds 0-99), so the CI is ±0.1.
- The same on medium, to show parity there is real.
- Every Gemini model × every thinking level on hard, as a full competence-per-euro frontier (the Gemini CEO owns that chart; coordinate with "gemini-track ceo lite").
- A Gemini "coach" that reads a failed episode and writes a one-paragraph hint, then a re-run with the hint, to measure how fast the gap closes with feedback (a meaningful-difficulty bonus).
