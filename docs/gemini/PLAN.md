# Canary Lab: Gemini plan (Google DeepMind "Best Use of Gemini API")

Owner: Gemini CEO (Claude), branch `gemini-track`. Deadline **Sun 15 Nov 10:00 Helsinki**; submission-ready on this branch from **Sun 06:00**.
These files live in `docs/gemini/` (not `docs/PLAN.md`) so they never conflict with the AfterQuery plan when `gemini-track` is merged into `justSilas`.

## Questions for Silas

1. **Gemini gateway on the FR8 login node.** FR8 compute nodes have no internet (checked again 14:00, curl rc=6); the login node does. To fan Gemini episodes out over the cluster, I want to run one light process on the login node: an asyncio relay (about 1% CPU, one port, bound to the cluster-internal interface) that forwards to `generativelanguage.googleapis.com`, holds the key, rate-limits and logs usage. Compute nodes never see the key. **Default if you don't answer by 16:00:** I run it on the login node with `nice -n 19` and a hard `--time`-style self-exit after 8 h. The fallback is the same relay on the Mac, exposed to the cluster with `ssh -R`, which only works while the Mac is awake.
2. **Merge path (agreed with the Arena CEO, 15:00):** PR 1 (code plus first results) by **Sat 19:30**, PR 2 (results and docs only) by Sun 01:30. ~~Original proposal: at 05:00 Sunday I open a PR from `gemini-track` into `justSilas`. It is additive: a new package `canary/gemini/`, new `docs/gemini/`, new tests and new Makefile targets, with no edits to env, reward or reproduce. The AfterQuery CEO merges it into `main`.~~
3. **Which project is the Gemini entry?** I chose **Canary** (agent-arena), see below. Override only if you strongly prefer another.

4. **Momin's fleet (FLEET-CONTEXT.md, 14:45).** The fleet's `gemini` team (in `~/momin/fleet`, paused at 14:33) has our goal on our repo. **Proposed split, needs your OK to give the fleet instructions:**
   - **Fleet gemini team:** one **labelled real run per existing role** with gemini-4-carbon, covering Mole Forge, world builder, scenario designer, arena mole, hunter and analyst v0 (`pitch/GEMINI.md` roles). Each run records the model id and commit.
   - **Canary Lab (us):** ladder, Failure Atlas, red-team swarm, gateway and dashboard (already built and tested on `gemini-track`). We also own the submission write-up, the evidence pack and the video assets. We do not rebuild the six roles.
   - **Shared:** the fleet logs Gemini usage in our ledger schema (`canary/gemini/ledger.py`: `{ts, feature, model, kind, in, out, thinking, cached, latency_s, cost_usd, ok, ...}`), so the dashboard and the submission count all Gemini work.
   - I will not touch `~/momin/fleet`, `fr8/*`, `momin` or `sleeper/*`. I read them only.
5. **How do the fleet's compute-node jobs reach Gemini?** Our compute-node test returned no internet. If the fleet already has a proxy, our ladder and swarm use the same route, and our gateway stays local and only does record/replay.

6. **ElevenLabs:** not requested for the Gemini entry. The judges reward Gemini being essential, so the demo voice is Gemini TTS (gemini-3.8-flash-tts) and the live commentator is the Gemini Live API (gemini-3.8-live), both already working. Using another vendor's voice here would weaken the "why Gemini" story. ElevenLabs fits the Meta glasses entry much better.

## Decision: the Gemini entry is Canary, extended into "Canary Lab"

Candidates compared:
- **Canary / agent-arena (chosen).** It already has a real benchmark: a Bayesian reference solver, frozen tiers, reward integrity work and reproducible numbers. Gemini is already the frontier agent under test (gemini-4-carbon is at about the solver on medium and 56–79% of the solver on hard). This is the only candidate where Gemini can be the agent, the adversary, the auditor and the analyst at once, with numbers to show for it.
- **Meta glasses.** Strong for Gemini Live/multimodal, but that is the Meta CEO's product and it would split our focus. I advise them through the playbook.
- **Valio Aimo.** Function calling plus catalog matching. It is solid, but judges see that pattern often.

**Pitch in one line:** *Gemini builds, plays, attacks and explains its own benchmark.* An RL environment tells you that an agent fails. Canary Lab uses Gemini at scale to tell you **why, how much thinking would fix it, and whether the score can be gamed**, and every claim is reproducible offline.

## The problem and why it matters

Agents are now given security, ops and procurement work where they must reason under uncertainty, spend a budget and commit to an irreversible decision. Benchmarks report one number per model, which says nothing about where an agent fails, whether more thinking would help, or whether the score can be gamed. Evaluating that by hand means reading thousands of 400-step trajectories, which nobody does.

## Architecture: Gemini in six deep roles

```
                 ┌─────────────────────────── FR8 cluster (Slurm) ───────────────────────────┐
  Mac / judges   │ compute01/02/06: N sbatch-array workers (env + solver + regret, CPU)       │
  make lab-*  ──►│     │ HTTP (cluster-internal, no key)                                     │
                 │     ▼                                                                      │
                 │ login node: Gemini Gateway (relay · rate limit · record/replay cache · ledger)│
                 └─────┼──────────────────────────────────────────────────────────────────────┘
                       ▼
                Gemini API: 3.1-flash-lite · 3.5-flash · 3.8-flash · 4-hydrogen · 4-argon · 4-carbon
                (thinking levels, function calling, structured output, context caching, batch,
                 embeddings, multimodal, TTS)
```

| # | Module (`canary/gemini/`) | Gemini capability used (depth, not decoration) | Output |
|---|---|---|---|
| 1 | **ladder**: the Gemini Ladder | Function calling (13 MCP tools), **thinking levels** (minimal→high), thought-signature replay, massive parallel runs on FR8 through the gateway | Score, regret and cost vs thinking tokens for 6 models × 3–4 levels × 2 tiers × ≥10 paired seeds. *"How much thinking buys how much of the gap?"* |
| 2 | **atlas**: Failure Atlas | **1M-token long context** (the whole corpus in one prompt), **context caching** (one cached corpus, many questions), **multimodal** (per-episode belief-vs-solver chart PNGs), **embeddings** (cluster reasoning snippets), **structured output** with verified verbatim quotes, **Batch API** for per-decision labels | `results/gemini/atlas.md/json`: failure modes tied to decisions and regret, with a human-agreement score |
| 3 | **swarm**: auto red team | **Whole-repo whitebox** in context (about 400k tokens of source, CONTRACT and EXPLOITS), function calling against a live env/MCP, many attacker personas in parallel, ledger-verified | Exploit candidates, verified by the ledger rather than by Gemini's word; regression tests auto-written for any real finding |
| 4 | **gateway**: cluster relay | Key isolation, adaptive rate limiting, **record/replay** cache (every Gemini number reproduces offline with no key) | `data/gemini/replay/` and the usage ledger |
| 5 | **dashboard** | Reads the ledger and every result file | One static HTML page: usage, cost, tokens by feature/model, ladder curves, atlas, swarm. Also published as a claude.ai artifact |
| 6 | **narrate** (stretch) | **TTS** (gemini-3.8-flash-tts) narrates replays for the demo video; **Live API** (gemini-3.8-live) commentator as a stretch | Demo video voice track, live demo |

Already on `justSilas` (the AfterQuery team owns these, and we credit them in the submission): the Mole Forge (Gemini mutates mole strategies), world builder, PAIRED scenario designer, analyst v0, arena mole and the gemini-4-carbon frontier measurement.

**Innovation claims we must back with data:**
1. **Thinking-to-competence curve.** A first-of-its-kind measurement of how Gemini's thinking level moves an agent toward a Bayes-optimal reference, attributed per decision through regret. It tells you where thinking helps (canary design) and where it does not (commit timing).
2. **Self-auditing benchmark.** Gemini holds the entire repo in context and attacks the reward. Only ledger-verified exploits count, and each finding becomes a test.
3. **The analyst is checked, not trusted.** Every quote is verified verbatim against the transcript, every failure mode is tied to solver regret, and humans label a sample to give an agreement score.
4. **Reproducible LLM science.** Record/replay through the gateway: judges rerun our Gemini tables with `make lab-replay` and no key.

## Demo script (3 min video, 10 min live)

1. **0:00 Hook.** "Gemini 4 Carbon catches the mole as well as a Bayesian solver on medium. On hard it falls to about 60%. Why?" Show the browser game with one Gemini episode replayed and Gemini TTS commentary.
2. **0:30 Ladder.** The heatmap and curve: score vs thinking level for 6 Gemini models. Then the cost frontier: "3.8-flash-high gets X% of carbon's score for Y% of the cost."
3. **1:15 Atlas.** "Gemini read all N trajectories, about 3M tokens across the cached corpus, in one sitting." It shows the top 3 failure modes with verified quotes and regret, a belief-chart thumbnail, and the human agreement score.
4. **2:00 Swarm.** "Fifty Gemini attackers read our whole codebase and tried to break the reward." Show the scoreboard: attempts, best non-solver score, regression tests written.
5. **2:30 Dashboard.** Calls, tokens, thinking tokens, cache hits and cost by feature. Then `make lab-replay` reproduces everything offline.
6. **2:50 Close.** Why Gemini is essential: 1M context, thinking control, caching and batch economics, multimodal, all on one API.

## Timeline (Helsinki). Revised 15:00 to fit the AfterQuery freeze (Sat 20:00 feature freeze, judged runs 20:00–02:00, docs only after 02:00)

| When | Milestone | Gate / check |
|---|---|---|
| Sat 15:00 | Docs pushed, team spawned, ledger base (done) | — |
| Sat 17:00 | **M1:** gateway local and tested; ladder smoke; atlas v0 on committed runs; swarm with 3 attackers; dashboard v0 | If the gateway is not needed yet, it is not started on FR8 |
| Sat 19:00 | **M2 (code freeze for PR 1):** all modules merged into gemini-track, tests green, first ladder table, atlas v1 gallery, swarm wave 1, dashboard v1 | `make test` green |
| **Sat 19:30** | **PR 1 `gemini-track` → `justSilas`**: code plus first results, everything the pitch and judges should see | Arena CEO merges before the 20:00 freeze |
| Sat 19:30–Sun 01:30 | Ladder runs to completion; atlas v2 with ladder data; swarm wave 2; replay cache | Results only, no env-path code |
| **Sun 01:30** | **PR 2 (results and docs only)**: results/gemini/*, docs/gemini/*, replay cache | After 02:00 only docs go into justSilas |
| Sun 06:00 | **Submission-ready**: text, video v1, screenshots, dashboard | — |
| Sun 08:00 | Silas reviews; final video; humans submit | — |
| Sun 09:30 | Submitted (10:00 hard deadline) | — |

**Lanes agreed with the Arena CEO (15:00):**
- The gemini-4-carbon **default-thinking** headline (n≥30 per tier) belongs to their measurement engineer (`justSilas-gemini`). Our ladder covers the other models and explicit thinking levels, reuses their runners, and runs paired with the solver on the same v1.4 dev seeds.
- The atlas and the swarm are ours. Exploits go to the Arena CEO immediately, with a ledger-verified repro.
- The gateway runs only when FR8 actually needs Gemini. It is token-gated, keeps the key out of world-readable files and command lines, and has a hard stop.

## Scoring checklist (official DeepMind criteria, JUDGING.md, read Sat 19:10)
There is no weighted rubric. Judges want a "meaningful, innovative, technically impressive use of Gemini, beyond simply adding an LLM", and the write-up must answer 4 questions. Overall winner: peer review picks 5, then a grand jury. A clear 3-minute story matters as much as depth.

| # | Criterion | Our evidence (committed file) | Status |
|---|---|---|---|
| Q1 | Problem and why it matters | SUBMISSION.md §1: agents doing irreversible, budgeted decisions; benchmarks give one number with no "why" | ✅ draft v1 |
| Q2 | How Gemini is integrated | SUBMISSION.md §2 table: 6 roles × named API capabilities; one ledger row per call (dashboard: 11k+ calls) | ✅ draft v1; refresh numbers at 05:00 |
| Q3 | Innovative or technically impressive | Thinking-to-competence ladder (results/gemini/ladder.md); 793k-token one-cache atlas with 98% verified quotes (atlas.md); self-auditing red team with positive control (swarm_control.md); keyless replay of Gemini runs (`make lab-replay`) | ✅ v1; ladder needs more seeds per cell |
| Q4 | Why Gemini is essential | 1M context (whole corpus, whole repo), thinking levels on one family (a controlled experiment), caching and Batch economics, multimodal charts, embeddings, TTS and Live, all on one API | ✅ v1; add measured cache saving (204M of 251M input tokens cached) |
| D1 | "Beyond adding an LLM": Gemini does work no single prompt could | Atlas tags 404 decisions and explains 61% of regret; swarm runs 51 audited attacks; ladder runs 134+ paired episodes | ✅ |
| D2 | Breadth of Gemini API surface, used for real | function calling, thinking levels, thought signatures, structured output, explicit and implicit caching, Batch, embeddings, multimodal input, TTS, Live API, count_tokens | ✅ all used in committed runs |
| D3 | Rigor and honesty (credibility with technical judges) | Code-verified quotes, solver-computed regret, paired CIs, human validation sheet, positive control, infra-invalid episodes excluded | ⏳ human agreement pending (Ivar) |
| D4 | Demo lands in 3 minutes | VIDEO.md storyboard plus Gemini TTS narration plus Live commentator clip; dashboard screenshots | ⏳ final cut Sun 08:00 |
| D5 | Reproducible | `make reproduce` (env), `make lab-replay` (Gemini runs keyless), `make lab-dashboard` | ✅ |

**Optimisations from the rubric:**
1. Lead the video and the write-up with ONE striking finding: "premature accusation is 61% of all lost value across GPT, Grok and Gemini, and thinking cuts it", then the cost result (3.5-flash at solver level on hard for about 30% of carbon-high's cost).
2. Every Gemini capability claim links to a committed run, labelled with model id and commit (ROLES.md, PLAN-95 F).
3. Keep honesty visible (small-n CIs, the positive control): technical judges reward it.
4. Before 06:00, the ladder needs at least 6 seeds in the headline cells (3.5-flash medium/high and 3.8-flash low/high on both tiers).

## Fleet coordination (added 14:55 after FLEET-CONTEXT.md)
- **`sleeper/*` and `momin`** are "The Sleeper", a different environment with its own analyst (`agents/analyst.py`), exploiter (`redteam/gemini_exploiter.py`) and dashboard. Under docs/IDEAS.md its best parts are folded into Canary. Our Canary Lab modules target Canary and don't duplicate it. The submission credits both. If Sleeper parts merge into Canary with Gemini runs, our ladder, atlas and dashboard can read those runs.
- **The fleet `gemini` team** has the same goal and the same repo. Proposed split: see Questions for Silas #4. Until Silas answers, I build no new Canary Lab modules. Remaining effort goes to evidence (labelled real runs with model id and commit), the write-up and the showcase, per FLEET-CONTEXT §3.
- **FR8 CPU** is shared with up to 160 fleet agents. Our Canary Lab jobs stay small: ladder and swarm are API-bound and can run from the Mac at ≤16 concurrent.

## Risks

- **Rate limits** under massive parallelism. The gateway applies an adaptive concurrency cap per model, and the ladder is resumable.
- **The gemini-4 models are slow** (carbon-high takes about 23 s per call, so a 300-step episode is about 2 h). The ladder runs many episodes in parallel, and we use fewer seeds for carbon and more for the flash models.
- **Collision with the AfterQuery measurement engineer on the same key.** We share the rate limit. The gateway ledger shows our share, and carbon runs are coordinated through the CEO log.
- **Over-claiming.** Every number in the submission comes from a committed file, and every quote is verified.
