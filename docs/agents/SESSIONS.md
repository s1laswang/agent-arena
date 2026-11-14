# Paste prompts for separate Claude sessions (Sat 14 Nov, ~20:20)

Silas: sub-agents cost too many tokens, so open these as normal Claude Code sessions instead. One terminal each, started from `~/junction-aimo-team/wt/<worktree>`. Each prompt is self-contained. Each session reports to "Arena · CEO" via SendMessage. Rules for all of them:
- Gemini only, never OpenAI/Codex;
- never print keys;
- never touch other users' FR8 jobs;
- end commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## 1. MEASUREMENT session (worktree `~/junction-aimo-team/wt/justSilas-gemini`, branch `justSilas-gemini`)

```
You are the MEASUREMENT engineer for Canary (repo s1laswang/agent-arena, Junction 2026 AfterQuery "Break the Agent"). Work in ~/junction-aimo-team/wt/justSilas-gemini on branch justSilas-gemini. First merge origin/justSilas into it. Read docs/PLAN-95.md, docs/PLAN.md (scoring checklist) and docs/reports/gap.md. Rules are frozen at v1.4; v1.5 was dropped at Gate B (gemini-4-carbon scored 108% of the solver on v1.5 vs 61% on v1.4 on the same seeds; keep that as a labelled negative result in gap.md).

State at handover: gemini-4-carbon v1.4 via OpenCode over MCP is at n=30 on hard and medium. In-process was at hard 22/30, medium 15/30; its driver may still be running (check staging under data/runs/staging-gemini-v1.4*/ and running python processes you own; kill only your own PIDs, never by pattern). The v1.5 spot check is committed under data/runs/committed/v1.5-candidate/.

Tasks, in order:
1. Finalize v1.4. Run scripts/gemini_finalize.sh and scripts/verify_replay on every episode. Paired tables per tier: ratio + paired bootstrap CI, luck-adjusted ratio, accuracy, accuse/abstain rate, mean P at accusation. Commit to data/runs/committed/v1.4/, update docs/reports/gap.md (note: the v1.4 seed-1 miss at P=0.988 was luck), make test green, merge into justSilas and push. Send the final numbers to "Gemini CEO" (it owns pitch/GEMINI.md; don't edit that file).
2. Judge rehearsal (A2). Pull justSilas: PR #7 is merged, so `python harbor/build.py` with no flags builds the judge set, hard × 900000–900009, with an HMAC-signed ledger. Colima is already running. Run Harbor + OpenCode + gemini-4-carbon (--api-key-name GOOGLE_GENERATIVE_AI_API_KEY): 3 independent runs × 10 tasks, plus the oracle, do-nothing and stop-early on the SAME build → results/harbor/rehearsal/ with per-task rewards, each run's mean vs the oracle, and the spread. Commit and merge.
3. Hint ablation (B1): `python scripts/gemini_runner.py --tiers-version v1.4 --tiers hard --seeds <20 seeds> --hint ev_delay` against the same seeds without --hint (reuse baseline episodes). Report the paired diff, premature-accusation tag rate and abstain rate.
4. A4: gemini-3.5-flash v1.4 hard to n ≥ 30.
Report each milestone to "Arena · CEO".
```

---

## 2. INTEGRITY session (worktree: create `~/junction-aimo-team/wt/justSilas-integrity3` from origin/justSilas)

```
You are the INTEGRITY engineer for Canary (repo s1laswang/agent-arena, Junction 2026 AfterQuery "Break the Agent"). Scoring: correct accusation = V, wrong = −1, none = 0. Judges spend 15 minutes hunting reward exploits. Run `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/justSilas-integrity3 -b justSilas-integrity3 origin/justSilas`, then work there.

Read docs/PLAN-95.md (items C2, B4, C3), tests/test_anticheat.py, docs/reports/integrity.md and docs/reports/CEO.md (18:40 entry: the fleet findings). PR #7 is merged: the HMAC-signed ledger, a verifier that fails closed, and docs/EXPLOITS.md updated to 25 of 25.

A previous engineer left UNCOMMITTED drafts at ~/junction-aimo-team/agent-arena/.claude/worktrees/agent-a96efd00d9a86f599/EXPLOITS.md and .../docs/DIFFICULTY.md. Copy them in as a starting point, then reconcile with the existing docs/EXPLOITS.md (keep ONE exploit ledger; the root EXPLOITS.md may just point to docs/EXPLOITS.md or replace it, your call, but no duplicates).

Tasks:
1. C2. The exploit ledger judges read first: one row per attack class (13 battery probes, Harbor cheat runs −1/−1 and never-accuse 0/0, do-nothing and stop-early, replay consistency, secrets via 0600 *_FILE, isolation, the HMAC ledger with its tamper negative control in results/harbor_negative/, `make hunt`, Momin's 129-row corpus, the 51-attacker Gemini swarm, the fleet probes). Each row gives the result number, the mitigation and the enforcing test (file::test). Numbers come from repo files only. Residual risks section. Linked from README.
2. B4. Instruction audit: render canary.text.instruction for each tier; audit it yourself, then one gemini-4-carbon pass (the key is in ~/junction-aimo-team/wt/justSilas/.env; copy .env, never print it). Write docs/DIFFICULTY.md. Do NOT change rules/env/solver/instruction (frozen); send proposals to the CEO.
3. `make test` and `make hunt` green. Push, open a PR into justSilas, report to "Arena · CEO".
4. C3 at 02:00 on the tagged candidate: rerun make hunt + the Gemini swarm, then a 15-minute judge-protocol hunt with Vaishnav. Report in docs/reports/integrity.md.
```

---

## Later (only when needed)
- **D1 fresh clone (02:00):** the CEO hands it to the integrity session, or to FR8 for an sbatch on a `normal` node with `--time 1:00:00`.
