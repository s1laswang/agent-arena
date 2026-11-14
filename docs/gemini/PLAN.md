# Canary Lab: Gemini plan (Google DeepMind "Best Use of Gemini API")

Owner: Gemini CEO (Claude), branch `gemini-track`. Deadline **Sun 15 Nov 10:00 Helsinki**; submission-ready on this branch from **Sun 06:00**.
These files live in `docs/gemini/` (not `docs/PLAN.md`) so they never conflict with the AfterQuery plan when `gemini-track` is merged into `justSilas`.

## Questions for Silas

1. **Gemini gateway on the FR8 login node.** FR8 compute nodes have no internet (checked again 14:00, curl rc=6); the login node does. To fan Gemini episodes out over the cluster, I want to run one light process on the login node: an asyncio relay (about 1% CPU, one port, bound to the cluster-internal interface) that forwards to `generativelanguage.googleapis.com`, holds the key, rate-limits and logs usage. Compute nodes never see the key. **Default if you don't answer by 16:00:** I run it on the login node with `nice -n 19` and a hard `--time`-style self-exit after 8 h. The fallback is the same relay on the Mac, exposed to the cluster with `ssh -R`, which only works while the Mac is awake.
2. **Merge path.** Which branch gets merged for the final submission? **Proposal:** at 05:00 Sunday I open a PR from `gemini-track` into `justSilas`. It is additive: a new package `canary/gemini/`, new `docs/gemini/`, new tests and new Makefile targets, with no edits to env, reward or reproduce. The AfterQuery CEO merges it into `main`.
3. **Which project is the Gemini entry?** I chose **Canary** (agent-arena), see below. Override only if you strongly prefer another.

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

## Timeline (Helsinki)

| When | Milestone | Gate / check |
|---|---|---|
| Sat 15:00 | Docs pushed, team spawned, `canary/gemini/ledger.py` base (done) | — |
| Sat 17:00 | **M1:** gateway smoke on FR8 (1 compute job → gateway → Gemini); ladder smoke (2 models × 2 levels × 2 seeds); atlas v0 on the committed gemini-4-carbon runs; swarm v0 (3 attackers); dashboard v0 from the ledger | If the gateway is blocked, the ladder runs on the Mac at ≤16 concurrent |
| Sat 19:00 | **Full ladder launched** on FR8 (≥500 episodes) | Rate-limit errors < 5% |
| Sat 22:00 | **M2:** demo v1 end to end; submission text draft v1; dashboard v1 published | Go/no-go for stretch (TTS narrate, Live, clash matrix) |
| Sun 02:00 | Ladder complete; atlas on the full corpus; swarm 50 attackers done | — |
| Sun 05:00 | PR `gemini-track` → `justSilas`; README "Canary Lab" section; replay cache committed | `make test` green, `make lab-replay` works keyless |
| **Sun 06:00** | **Submission-ready**: text, video v1, screenshots, dashboard | Freeze features |
| Sun 08:00 | Silas reviews; final video cut; humans submit | — |
| Sun 09:30 | Submitted (10:00 hard deadline) | — |

## Risks

- **Rate limits** under massive parallelism. The gateway applies an adaptive concurrency cap per model, and the ladder is resumable.
- **The gemini-4 models are slow** (carbon-high takes about 23 s per call, so a 300-step episode is about 2 h). The ladder runs many episodes in parallel, and we use fewer seeds for carbon and more for the flash models.
- **Collision with the AfterQuery measurement engineer on the same key.** We share the rate limit. The gateway ledger shows our share, and carbon runs are coordinated through the CEO log.
- **Over-claiming.** Every number in the submission comes from a committed file, and every quote is verified.
