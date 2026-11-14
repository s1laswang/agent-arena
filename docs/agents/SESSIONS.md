# Paste prompts for separate Claude sessions (v2, Sat 14 Nov ~23:00 Helsinki)

One terminal per session, each in its own worktree. No sub-agents: each session does its work itself, so usage stays low. Every session reports to "Arena · CEO" via SendMessage.

Shared rules (already in every prompt):
- Gemini only, never OpenAI or Codex. Never print keys. Never touch other users' FR8 jobs.
- Rules v1.4 are frozen; v1.6 "expert" is a candidate (head-agents) and solver_v2 is a candidate (head-env); the gate is at 01:40.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Already running (don't duplicate):
- head-env (solver_v2, oracle range)
- head-agents (expert tier + Gemini check)
- fr8 (v3 small model, Verda)
- Gemini CEO (Gemini submission)

---

## S1. REHEARSAL: judge rehearsal + Gemini data hygiene
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s1-rehearsal -b s1-rehearsal origin/justSilas`

```
You are the REHEARSAL engineer for Canary (s1laswang/agent-arena, AfterQuery "Break the Agent"; judges rerun with Harbor + OpenCode over MCP: reference run, 3 agent runs, do-nothing, stop-early). Work in ~/junction-aimo-team/wt/s1-rehearsal (branch s1-rehearsal off origin/justSilas). Do everything yourself; do NOT spawn sub-agents. Read docs/PLAN.md (scoring checklist), docs/PLAN-95.md (end section), docs/reports/gap.md, harbor/README.md.

State: v1.4 gemini-4-carbon runs are committed and replay-verified (data/runs/committed/v1.4/, paired table paired_table_gemini.md). Headline: OpenCode hard 65% [24, 98], luck-adjusted 72% [52, 91]. `python harbor/build.py` (no flags) builds the judge set (hard × 900000–900009) with a signed ledger. Colima runs on this Mac. GEMINI_API_KEY is in ~/junction-aimo-team/wt/justSilas/.env: copy .env into your worktree, never print it.

Tasks:
1. NOW, a dry run of the judges' sequence on the CURRENT justSilas: build the default set; run the oracle, do_nothing and stop_early (harbor -a oracle with ORACLE_POLICY), then 1 OpenCode run with gemini-4-carbon (--api-key-name GOOGLE_GENERATIVE_AI_API_KEY) on all 10 tasks. Fix any harness breakage you hit (report harbor/ or core changes to the CEO first). Save to results/harbor/rehearsal-dry/.
2. Fix the gemini-3.5-flash v1.4 runs: they are in ~/junction-aimo-team/wt/justSilas-gemini/data/runs/staging-gemini-3.5-flash-v1.4 (also merged copy held at /tmp/hold/opencode-gemini-3.5-flash). Score replay passes but tests/test_anticheat.py::test_frontier_runs_are_replayed (step-level) fails for them. Find why (likely MCP error wrapping in the recorded steps), fix it in the replay unwrapping or document it as an exclusion, then commit them under data/runs/committed/v1.4/opencode-gemini-3.5-flash/ with make test green.
3. AFTER the CEO sends the tag `afterquery-final` (~07:00): the full rehearsal on exactly that SHA: oracle, 3 independent OpenCode gemini-4-carbon runs × 10 tasks, do_nothing, stop_early → results/harbor/rehearsal/ with per-task rewards, each run's mean vs the oracle, and the run-to-run spread. Commit and send the table to the CEO.
Report each step to "Arena · CEO".
```

---

## S2. DIFFICULTY: the v1.4 failure analysis (Meaningful difficulty, 30 pts)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s2-difficulty -b s2-difficulty origin/justSilas`

```
You are the DIFFICULTY analyst for Canary (s1laswang/agent-arena). Rubric line: "explain the agent's main mistakes, tied to decisions in the task; the info and tools to do better are available; no withheld info, trick wording, impossible timing, broken tools" (30 pts). Work in ~/junction-aimo-team/wt/s2-difficulty. Do everything yourself; no sub-agents. Read docs/reports/gap.md, results/skill_ladder_v1.4.md, canary/analysis/ (tags.py, accuse.py), docs/EXPLOITS.md.

Data: data/runs/committed/v1.4/opencode-gemini-4-carbon/{hard,medium} and inproc-gemini-4-carbon/, paired with reference/solver-* on the same seeds 0–29.

Tasks:
1. Write docs/reports/failure_analysis_v1.4.md from the 30 OpenCode hard episodes vs the solver on the same seeds, all computed in code (scripts/failure_analysis_v14.py, committed):
   - canaries planted (reviewer: Gemini ~8.5 vs solver ~14.1);
   - accusation day (~13.4 vs ~10.6), and the V lost to waiting;
   - the solver posterior at Gemini's accusation;
   - wrong accusations, and the solver posterior at each one (reviewer: all 4 at 0.63–0.99, so luck, not gambling; say so honestly);
   - abstain rate; how often Gemini accuses on a single canary hit.
   Then rank the mistakes by V lost. The likely story: under-exploration (fewer canaries) → slower identification → V drains, not reckless gambling. Tie each mistake to the tool or decision that would have avoided it, and show that the information was available (the solver used the same observations). Two annotated example episodes.
2. Instruction audit → docs/DIFFICULTY.md. Render canary.text.instruction for each tier and check it for trick wording, hidden info, impossible timing and broken tools. Do one pass yourself and one gemini-4-carbon pass (key in ~/junction-aimo-team/wt/justSilas/.env; copy it, never print it). A previous draft is at ~/junction-aimo-team/agent-arena/.claude/worktrees/agent-a96efd00d9a86f599/docs/DIFFICULTY.md; start from it. Don't change rules or instruction text; propose changes to the CEO.
3. make test green; push; open a PR into justSilas; report to "Arena · CEO". Coordinate with "Gemini CEO" (its atlas failure gallery): yours is the v1.4 judged-tier analysis, so cross-link, don't duplicate.
```

---

## S3. INTEGRITY: one exploit ledger + the final hunt (Reward integrity, 25 pts)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s3-integrity -b s3-integrity origin/justSilas`

```
You are the INTEGRITY engineer for Canary (s1laswang/agent-arena). Judges spend 15 minutes trying to reward-hack it; do-nothing and stop-early must score ~0 (stop_early now stops without accusing and scores exactly 0; guess_day1 is the day-1 random accusation). Work in ~/junction-aimo-team/wt/s3-integrity. Do everything yourself; no sub-agents. Teammate Vaishnav designed the anti-cheat battery; credit him.

Read: docs/EXPLOITS.md, tests/test_anticheat.py, canary/redteam/anticheat.py, results/anticheat/exploits.md, harbor/README.md (signed ledger, PR #7), docs/reports/CEO.md (fleet findings 18:40).

Tasks:
1. ONE exploit ledger. docs/EXPLOITS.md is canonical. A previous draft EXPLOITS.md sits at ~/junction-aimo-team/agent-arena/.claude/worktrees/agent-a96efd00d9a86f599/EXPLOITS.md; merge anything new from it into docs/EXPLOITS.md. Add a short top section, "Judges: start here", listing the attack classes with result, mitigation and enforcing test. Cover:
   - the HMAC ledger, with the tamper negative control in results/harbor_negative/;
   - the cheat_probe 0/0 and the cheat run −1;
   - isolation;
   - the 51-attacker Gemini swarm;
   - Momin's 129-row corpus.
   Add Residual risks:
   - the sidecar holds the Gemini key;
   - check_leak_feed spends daily budget;
   - published retired keys can't catch re-signed forgeries.
   Numbers come from repo files only.
2. If the expert tier (branch justSilas-expert) is merged at the 01:40 gate: rerun make hunt plus the anti-cheat battery on it and add its rows.
3. At the tag `afterquery-final` (the CEO sends the SHA, ~07:00): run a 15-minute judge-protocol hunt yourself, plus make hunt and `REPRO_FAST=0 make reproduce`, on that SHA. Report in docs/reports/integrity.md.
Push, PR into justSilas, report to "Arena · CEO".
```

---

## S4. CRAFT: README first screen + fresh clone + tag (Craft, 15 pts)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s4-craft -b s4-craft origin/justSilas`

```
You are the CRAFT engineer for Canary (s1laswang/agent-arena). Rubric: "rules make sense for the setting; ONE command from the README reproduces our reported results". Repo is public; main's landing page sends judges to branch justSilas. Work in ~/junction-aimo-team/wt/s4-craft. Do everything yourself; no sub-agents.

Tasks:
1. README first screen (the reviewer counted 22 KB of version history as a minus):
   - one claim;
   - one v1.4 table (solver / gemini-4-carbon OpenCode / do_nothing / stop_early on hard, with numbers from docs/reports/gap.md);
   - one command (`make setup && make reproduce`, then `make accept`);
   - the Harbor judge block with the oracle's expected range from harbor/README.md;
   - links to docs/EXPLOITS.md, docs/reports/gap.md and docs/gemini/SUBMISSION.md.
   Move everything else (version history, v1.2/v1.3 stories) into docs/HISTORY.md. Keep every number traceable to a committed file.
2. Fresh-clone check on macOS: clone the public repo into /tmp, `git clone -b justSilas`, then `make setup && make reproduce && make accept`. Time it and fix anything that breaks: zip-download test skips (test_salt_never_tracked needs .git), Linux-only bits. Commit the log to results/fresh_clone/.
3. Repo hygiene: list what in results/ (11 MB, 691 files) is stale and propose deletions to the CEO; don't delete committed run data.
4. When the CEO says go (~07:00): re-run make test + make accept on the final merge, create an annotated tag `afterquery-final`, push it, and send the SHA to "Arena · CEO".
Push, PR into justSilas, report to "Arena · CEO".
```

---

## S5. DEMO: 10-minute demo + video storyboard (peer review / best overall)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s5-demo -b s5-demo origin/justSilas`

```
You are the DEMO producer for Canary (s1laswang/agent-arena). Judging: a 10-minute demo; overall winner = peer-review top 5, then a jury. Work in ~/junction-aimo-team/wt/s5-demo. Do everything yourself; no sub-agents. Read docs/PLAN.md (the "Demo (10 min)" section maps minutes to rubric points), docs/reports/gap.md, origin/ivar/aq-game-ux (docs/VIDEO-SCRIPT.md, docs/research-biases.md, game/), game/ (browser game, make game-serve), the viewer branches (justSilas-grok-viewer), pitch/.

Tasks:
1. docs/DEMO.md: a minute-by-minute script for the live 10-minute demo, with exact commands and expected outputs:
   - `make reproduce`;
   - a solver vs gemini-4-carbon replay on one hard seed where Gemini under-explores, picked from the committed v1.4 runs, with the "Fooled"/slow moment timestamped;
   - the gap table;
   - EXPLOITS;
   - the small-model result (leave a placeholder until fr8 reports ~07:00);
   - the Gemini roles;
   - the game link.
   Dry-run every command and note its runtime.
2. Merge-readiness review of Ivar's branch origin/ivar/aq-game-ux (game fixes, research, video script): check that `make game-serve` works and that the score matches Python on one seed, then list issues for Ivar. Don't merge yourself; send the verdict to the CEO.
3. A video storyboard (≤ 10 min) from Ivar's VIDEO-SCRIPT.md with only committed numbers; mark every number with its source file. No ElevenLabs unless Silas provides a key.
Push, PR into justSilas, report to "Arena · CEO".
```
