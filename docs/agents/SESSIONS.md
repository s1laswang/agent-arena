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

---

## S6. VERDA: Compute Track submission (owner: Arena CEO; this session executes)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s6-verda -b s6-verda origin/justSilas`

```
You are the VERDA engineer for Canary (s1laswang/agent-arena). We are entering the Verda Compute Track (25% each: Ambition, Fit = right Verda product and why, Working prototype + documented process, Path to scale). Read ~/junction-aimo-team/VERDA-TRACK.md first. HONESTY RULE: never claim FR8 freighter work ran on Verda; label every number with where it ran. Work in ~/junction-aimo-team/wt/s6-verda. Do everything yourself; no sub-agents. Verda GPU instances are owned by the "fr8 relaunch gpu audit" session: never launch a GPU instance yourself; ask it.

Facts already true:
- REAL Verda workload: v3 small-model GRPO (seed 0) on a Verda H100 80GB instance (1H100.80S.32V, FIN-02, €4.742/h), started 23:32 after two setup failures (the first instance 3bb74f5a started 22:46). About 12 s/step vs ~78 s on the FR8 V100 (6.5×). The training plus held-out eval ends ~02:45, with a hard-stop reaper at 03:23. Spend so far ~€3.6, cap $30. Get instance ids, logs, step counts, cost and the eval table from the fr8 session (docs/reports/fr8.md on branch justSilas-fr8).
- Freighter scale this weekend (for Ambition, labelled FR8): Momin's Gemini agent fleet on Slurm CPU, 813+ v1.4 frontier episodes, ~1,000 replay-verified committed episodes, the GRPO mole jobs, the J4/v2 SFT runs. Count GPU-hours and episodes from the repo and docs/reports/fr8.md.

Tasks:
1. A second Verda product, with no GPU setup: the Verda Inference API, or the NVIDIA Nemotron endpoint, as an open-weight Canary investigator.
   - Point OpenCode (or the in-process runner canary.agents.play, which has an OpenAI-compatible client path) at the Verda endpoint.
   - Run v1.4 hard dev seeds 0–9 (more if fast), replay-verify, and pair with the solver using scripts/paired_gemini.py or scripts/gap_vs_reference.py.
   - That gives a third model family on the judged tier (the reviewer asked for a non-Gemini model) and real Verda Fit. If it needs a key we don't have, write the exact ask under "Questions for Silas" in docs/PLAN.md and stop that task.
2. Write VERDA.md at the repo root:
   - the idea → prototype timeline;
   - the products used and why (GPU instance for GRPO: 6.5× V100 throughput, on-demand; Inference API/Nemotron for open-weight agents);
   - small-model before/after (base / v1 / v2 / v3, from the fr8 table; placeholder until ~03:00);
   - freighter vs Verda numbers, clearly labelled;
   - cost and duration;
   - the scale path: Instant Clusters for multi-node GRPO over thousands of rollouts, batch jobs for nightly eval sweeps, auto-scaling containers to serve the Canary MCP env to labs as an eval-as-a-service.
3. PR into justSilas; report to "Arena · CEO" via SendMessage. Never print keys (the Verda creds are in agent-arena/.env as VERDA_CLIENT_ID / VERDA_CLIENT_SECRET). Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
```

---

## S7. OPEN-7B: train an open model on Canary experience (the big compute bet)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/s7-open7b -b s7-open7b origin/justSilas`

```
You are the OPEN-MODEL engineer for Canary (s1laswang/agent-arena). Read docs/PLAN-COMPUTE.md first. That is your plan. Goal by 08:30: a replay-verified chart on v1.4 hard held-out seeds (n=30 each) for Qwen2.5-7B-Instruct base → SFT → expert iteration, next to gemini-4-carbon (0.322) and the solver (0.499). Work in ~/junction-aimo-team/wt/s7-open7b. Do everything yourself; no sub-agents. GPUs: 4 Verda A100-40G plus an H100, provisioned ONLY by the "fr8 relaunch gpu audit" session. Send it exact job specs (command, GPU, hours) and never create instances yourself. Never touch Momin's FR8 jobs; never pkill by pattern.

Reuse what exists:
- train/ (SFT/LoRA pipeline, eval_hf, j4/v2 scripts);
- train/grpo_investigator.py (the v3 GRPO, decision-point states);
- canary.agents.play / LLMPolicy (OpenAI-compatible tool-calling loop, so point it at a vLLM server);
- canary.eval (solver episodes on CPU);
- scripts/paired_gemini.py or scripts/gap_vs_reference.py (pairing).
Diagnosis to fix: the 1.5B/4k model accuses at the right time but at the wrong person (v2: accused 51%, correct 6%), because the evidence falls outside its window. Use FULL history (16k-32k context).

Steps:
1. (00:30-01:30) vLLM OpenAI server with Qwen2.5-7B-Instruct on one A100 (tool calling on), then 1 episode end-to-end with LLMPolicy on v1.4 hard dev seed. Then the base eval: n=30 held-out (HELDOUT seeds, v1.4 hard), run in parallel.
2. Generate ~3,000 v1.4 solver episodes on CPU (train seeds only, never judge/held-out), render them as full-history chat transcripts in the exact LLMPolicy format, and run SFT with LoRA on 7B at 16k context (A100 #3). Eval n=30.
3. Expert iteration: sample K=4 episodes per train seed from the SFT model via vLLM (A100 #1-2), keep the episodes that beat 0 / match the solver's accusation, SFT again (EI-1), eval n=30. EI-2 only if EI-1 improved.
4. Write results/leaderboard_v14_hard.json (rows: agent, n, mean ± CI, accuracy, abstain rate, GPU-hours, €) and docs/reports/open7b.md (honest, a null result included). Commit episodes under data/runs/committed/v1.4/open7b-*/ and replay-verify them.
Kill criteria are in PLAN-COMPUTE.md. Report every milestone to "Arena · CEO". Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
```

---

# Round X (Sun 15 Nov ~03:15): last-7-hours sessions (plan: Arena CEO; no sub-agents)

## X1. CAUSAL HINT (Meaningful difficulty)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/x1-hint -b x1-hint origin/justSilas`
```
You are the CAUSAL-HINT engineer for Canary (s1laswang/agent-arena, AfterQuery "Break the Agent"; judged rules v1.4, frozen). Work in ~/junction-aimo-team/wt/x1-hint. Do everything yourself; no sub-agents. Gemini only, never OpenAI. Never print keys (copy .env from ~/junction-aimo-team/wt/justSilas/.env). Never pkill by pattern. Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
Why: docs/reports/failure_analysis_v1.4.md shows gemini-4-carbon (OpenCode, v1.4 hard) loses mostly by committing before the evidence singles out one employee, and plants 8.5 canaries vs the solver's 14.1. The rubric wants proof that "the info and tools to do better are available". A one-sentence hint stating rules already in the instruction, which moves Gemini toward the solver, is that proof. If it doesn't move, report that too.
Steps:
1. Read: docs/reports/failure_analysis_v1.4.md, docs/reports/gap.md (the pre-registered "causal hint" rule is already there), canary/agents (HINTS dict; `--hint ev_delay` was added at f53ae53), scripts/gemini_runner.py, canary/agents/frontier/opencode_run.py.
2. Add hint "gather" to HINTS, default OFF, with this exact text: "Evidence first: you may plant up to the stated number of canaries every day; plant them every day, and accuse only when exactly one employee is consistent with every leak you have seen (otherwise abstain, which scores 0)." Tests: Env.instruction() unchanged on every tier; the prompt without the flag is byte-identical; with the flag = base + "\n" + text.
3. Run gemini-4-carbon via OpenCode, v1.4 hard, dev seeds 0-29, --hint gather, into its own staging dir. Run it on the Verda CPU instance that the "fr8 relaunch gpu audit" session provides (ask it for host + access; it owns Verda). Fall back to the Mac at ≤ 4 parallel if the box isn't ready by 04:00. Use ≤ 8 parallel; infra-invalid attempts are retried, never counted; never re-run a valid seed.
4. Merge into data/runs/committed/v1.4/opencode-gemini-4-carbon-hint-gather/hard/, replay-verify (scripts/verify_replay.py), and pair against the solver AND against the unhinted primary set on the same seeds (scripts/paired_gemini.py or scripts/gap_vs_reference.py). Report: % of solver, luck-adjusted, paired diff vs unhinted, canaries planted, premature-commit rate (reuse scripts/failure_analysis_v14.py functions).
5. Add a short "Causal hint test" section to docs/reports/failure_analysis_v1.4.md (results only, either outcome). make test green. PR into justSilas by 06:00. STOP all Gemini calls at 06:00 (the judge rehearsal needs the quota from 06:30).
Report milestones to "Arena · CEO" via SendMessage.
```

## X2. DAGGER TIEBREAKER (small model trained on its own states)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/x2-dagger -b x2-dagger origin/justSilas-fr8`
```
You are the DAGGER engineer for Canary's tiebreaker ("a smaller model improves after training on the environment's experience"). Work in ~/junction-aimo-team/wt/x2-dagger. Do everything yourself; no sub-agents. GPUs come ONLY from the "fr8 relaunch gpu audit" session (it owns Verda; send it exact job specs: command, GPU, hours). Never create instances yourself, never touch FR8 Slurm jobs, never pkill by pattern. Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
Diagnosis to fix: v3-4k s0 (GRPO, Qwen2.5-1.5B LoRA, Verda H100, 609 steps) learned to name the mole from evidence on TRAINING states (forced-accusation whom-accuracy 0.19 → 0.89), but held-out precision is only 0.19 (3/16). Its score is −0.10 vs base 0.00, though +0.31 vs v2. The cause: its training states were the last 6 steps of SOLVER trajectories, where the solver had already gathered the evidence. The model never learned to gather evidence in its OWN states.
Fix (DAgger), round 1:
1. Roll out the v3-4k s0 adapter (ask fr8 for the path) on TRAIN seeds (150000+, never judge or held-out) for ~300 episodes. Use vLLM on an A100/H100 if available, else HF generation with KV reuse (train/eval_hf).
2. At every state the model reaches, query the reference solver for the action it would take from the SAME observation history (canary/solver policy works from the agent-visible history; replay the model's actions into a fresh Env and ask the solver at each step).
3. Build SFT examples (state → solver action), up-weighting plant_canary and accuse/abstain decisions.
4. LoRA SFT from v3-4k s0 at 8k context.
5. Held-out eval n=30/tier (eval_hf, the same seeds as the other rows).
Optional round 2 only if round 1 beats v3. Read first: train/README.md, train/grpo_investigator.py, train/eval_hf.py, fr8/analysis/ws4_table.py, fr8/verda/README.md, docs/reports/fr8.md.
Deliver docs/reports/dagger.md and rows in the ws4 table (base / v1 / v2 / v3-4k / v3-8k / DAgger: n, mean ± CI, accused, correct, abstain, whom-precision, GPU-hours, €). Honest null if no gain. Done by 07:30; no training after 09:00. PR into justSilas; report to "Arena · CEO".
```

## X3. JUDGE SIMULATION (Craft)
Worktree: `git -C ~/junction-aimo-team/agent-arena worktree add ../wt/x3-judgesim -b x3-judgesim origin/justSilas`
```
You are the JUDGE-SIMULATION lead for Canary (s1laswang/agent-arena, public; AfterQuery rubric: gap 30, meaningful difficulty 30, reward integrity 25, craft 15 = "rules make sense; ONE command from the README reproduces reported results"). Work in ~/junction-aimo-team/wt/x3-judgesim. You may launch Gemini (gemini-4-argon or hydrogen; NOT carbon) OpenCode or Gemini CLI agents as cold judges, but no Claude sub-agents. Never pkill by pattern. Never print keys. Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
1. Launch 6 Gemini judge agents. Each gets ONLY the rubric text above plus "git clone -b justSilas https://github.com/s1laswang/agent-arena /tmp/judgeN". Each follows README.md literally: make setup, make reproduce, make accept. Judge 1 also does harbor/README.md (oracle + do_nothing on 2 tasks) if Docker/colima is free; DON'T restart colima, because the s1-rehearsal session uses it from 06:30. At most 3 heavy runs at once (the Mac is loaded).
2. Each judge logs: time to first result; every confusing sentence (file:line); every number it can't trace to a committed file; every error; a rubric score per line, with reasons.
3. You aggregate into docs/reports/judge_sim.md: a ranked friction list.
4. Fix cheap items yourself, in docs, README, harbor/README.md or the Makefile only: no canary/ rules/env/solver changes and no committed-data changes. Run make test + make accept green, then open a PR into justSilas by 06:00. Anything bigger goes to "Arena · CEO" as a one-line proposal.
```

## X4. VERDA (Compute Track) = S6 above, plus:
- the Verda CPU instance hosting X1's runners (fr8 provisions it);
- docs/reports/verda-evidence.md (Meta YOLO + PaliGemma; the v3 GPU runs);
- Gemini J1 (Qwen3-14B self-hosted) as an open-weight point.

Output: VERDA.md, PR by 08:30.
