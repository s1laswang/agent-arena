# Canary watch log

Rule: read only. Never merge or copy Silas's code into our branches. Sources: `git log`/`git show origin/<branch>` on origin justSilas*, vaishnav/*.

## Tick 1, 2026-11-14 ~12:40 Helsinki (baseline)

Last-seen SHAs (tip, commit time +0200):
- justSilas 8970ead 12:33 (was f56cc1d at bake-off 2)
- justSilas-harness / harness2 11f1b4e 12:32
- justSilas-fr8 9600a62 12:28; fr8-trainer 285735f 12:27
- justSilas-v14 8f87ed1 12:08 (rules frozen v1.4)
- justSilas-measure 11fe514 11:25; integrity 013cf9f 08:19; fr8-analyst 54f5544 07:15
- justSilas-grok-bakeoff2 3f91fe4; vaishnav/poisoned-inbox 9068b16 08:11
- All other justSilas-* branches unchanged since 04:30 or earlier.

What changed since f56cc1d (11 commits, `git log f56cc1d..origin/justSilas`):
- `canary/reproduce.py`: invalid (infra) episodes dropped from reported means, per-seed dedupe, newest run wins. Fixes bake-off risk 2. Results refreshed (`results/judge_table.md`).
- Codex smoke run moved to `superseded/` (it double-counted hard seed 0).
- fr8 trainer: `eval_hf` KV/prefix reuse, `--max-calls`, `fr8/j4_eval.sbatch` (fast small-model eval).
- New brief `docs/agents/NEXT-LEVEL.md` (CEO, Sat ~12:30), the plan for the rest of the hackathon.

Numbers (all theirs, from `docs/reports/gap.md` and NEXT-LEVEL.md):
- Codex gpt-5.5 over MCP, v1.3: medium n=11 55% of solver [-8,104], hard n=11 106% [91,136]. No gap on hard.
- Nothing newer yet. Gemini measurement (`gemini-4-carbon`, branch `justSilas-gemini`, OpenCode over MCP and in-process, v1.3 and v1.4) is running but not on origin yet.
- Nothing beats our numbers: we have no frontier run either.

Their plan (what to expect next):
- OpenAI key removed, Gemini unlimited with `gemini-4-carbon`. Rules frozen v1.4 (8f87ed1).
- Thesis: frontier agents never abstain; accuse at P 0.18-0.45 when abstaining (0) beats a likely -1. They want "calibrated commitment" as the measured skill across three families (gpt-5.5, Grok, gemini-4-carbon).
- Skill ladder (`scripts/skill_ladder.py`, n>=400 per tier), copied from Poisoned Inbox.
- v1.5 "dormant mole" knob, branch only.
- Gemini failure analyst, Mole Forge with Gemini mutator, hint ablation (causal), Gemini exploit hunter (black and white box).
- Boot Harbor for real (colima), do-nothing 0 / stop_early about -1 logs in `results/harbor/`; gemini-4-carbon through OpenCode on 3 hard + 3 medium.
- `CANARY_EPISODE_FILE` instead of seed in env; rerun `repro_spread.py 30`.
- Small-model v2 when a V100 frees up (~18:30), goal reward gain.

Ideas to copy (idea only, no code):
- Skill ladder table: one rule removed per rung (lead-reward / lead-demo). We have one-rule ablations in spirit; make it a table.
- Hint ablation: one sentence per failure mode, show tag drops on a real model (lead-lab).
- Report invalid infra episodes as a separate column, never in the mean.
- Run Harbor for real and commit logs (lead-env / lead-harness).

Weaknesses we can beat:
- Their frontier gap is inconclusive (hard 106%) and OpenAI is now removed, so their strongest evidence (Codex) is frozen at n=11. A real, repeated gemini-4-carbon gap on our judge seat would beat it.
- They have not booted Harbor yet (planned). If we boot ours first and commit logs, integrity/craft favour us.
- Their small-model LoRA did not raise reward (n=17, mean -0.148); ours is also unproven. Only a reward gain counts.

Our own gaps this watch exposes (from bake-off 2, still true until fixed): no real frontier run, finance_ap oracle 0.75, shared verifier + chmod 777 /logs, 20 failing tests.

Routing sent: chief, lead-lab (numbers, hint ablation), lead-reward (ladder, integrity), lead-env (Harbor boot, rules freeze), lead-attack (nothing new), lead-demo.

## Tick 2, 2026-11-14 13:16 Helsinki

Last-seen SHAs (changed ones marked *): justSilas* cca3cb8 (was 8970ead), justSilas-harness2* 4c60e11 (was 11f1b4e), justSilas-grok-bakeoff3* 72b32cf (new branch, 10:43 UTC).
Unchanged: harness 11f1b4e, fr8 9600a62, fr8-trainer 285735f, fr8-analyst 54f5544, fr8-ops f7b0124, v14 8f87ed1, measure 11fe514, integrity 013cf9f, agents 51d540b, grok-bakeoff2 3f91fe4, vaishnav/poisoned-inbox 9068b16. Not on origin yet: justSilas-gemini (the gemini-4-carbon runs), env2, agents2, integrity2.

New facts:
- Bake-off 3 (`docs/reports/grok-bakeoff3.md`, run on Canary f56cc1d, Sleeper 07e17ee): Poisoned Inbox 64, Canary 62 (gap 8, difficulty 20, integrity 22, craft 12), Blind Spot 61, The Sleeper 51 (gap 10, difficulty 17, integrity 15, craft 9). Canary fell from 70 to 62 because the official v1.3 Codex run is 1.06x solver on hard and v1.4 hard shows the heuristic at 90% accuracy, +0.196 vs solver +0.516 (they say v1.4 did not restore the collapse). v1.4 has no frontier runs. Its recommendation is still "ship Canary as an unfinished measurement". The judge there did not boot Docker.
- Harbor booted for real (harness2 17ba746, 4c60e11, `results/harbor/`): oracle medium 0.78 / hard 0.66 = in-process solver, do_nothing 0/0, stop_early -1/-1, check_isolation 11/11 OK, 6-task v1.4 build all equal the solver. This closes their bake-off risk 3.
- NEXT-LEVEL.md (cca3cb8): top priority is an anti-cheat port from Poisoned Inbox into Canary: a probe battery inside `make reproduce` (do_nothing, stop_early, random, restrict_all, probe_all, accuse_decoy, malformed args, parallel accuse, calls past cap) plus a control that must keep the solver score, a stop-early ladder (solver cut at 25/50/75% = 0), replay consistency of every committed episode, and a Harbor `ORACLE_POLICY=cheat` run that tries to rewrite reward.txt and hit /ledger and /admin. Vaishnav is the human owner.

Beats us: their Harbor boot with committed logs; their anti-cheat battery will be in the one command. Our equivalents: `make exploits` and docs/EXPLOITS.md, but no Harbor boot logs and shared verifier + chmod 777 /logs.
Beats them: they have no v1.4 frontier run and no Gemini run yet; their frontier gap on v1.3 hard is above the reference. Whoever lands a real, repeated frontier-below-reference number first on the judge seat wins the gap axis.
Ideas to copy (idea only): anti-cheat probe table printed by the one command; stop-early ladder on the reference itself; replay consistency flag; Harbor cheat solution; booting Harbor via colima and committing logs.
Routing: chief, lead-lab, lead-reward, lead-env, lead-harness, lead-demo.
