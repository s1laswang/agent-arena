# Canary Lab: Gemini builds, plays, attacks and explains its own benchmark

*Google DeepMind "Best Use of Gemini API" submission, Junction 2026. Repo: github.com/s1laswang/agent-arena (Canary Lab = `canary/gemini/`).*
*DRAFT v1. Numbers are from the committed files `results/gemini/ladder.md` (157 episodes, generated 18:47 at git 016758ace5) and `results/gemini/dashboard.html` (`usage.totals`: 15,757 calls, cost_usd 146.0212). Remaining `⟨…⟩` are still pending.*

## Short version (platform summary field, ≤ 600 chars)
Canary is an RL environment in which an AI agent, as head of security, must catch a mole by laying canary traps while company value bleeds away. On hard, n=8: gemini-3.6-flash (requested as gemini-3.5-flash) is 92% [76%, 113%] of the solver at medium thinking and 102% [84%, 129%] at high, within those CIs, 16/16 correct. 157 paired episodes, 5 models, up to 4 thinking levels. Swarm: 32 of 35 attacks ran in-process, 3 via MCP, 0 exploits. Ledger: 15,757 calls, $146.02. Recorded Gemini runs replay offline.

## 1. The problem and why it matters
Companies now give agents work where they must reason under uncertainty, spend a budget and commit to an irreversible decision: security triage, insider-risk, incident response, procurement. Benchmarks give back one number per model. That number cannot tell you:
- **where** the agent goes wrong (which decision, at which step);
- **whether more thinking would fix it**, and what that costs;
- **whether the score can be gamed.**

Answering those questions takes reading thousands of 300–400-step trajectories and auditing the reward code line by line, which nobody does by hand. So agent evaluations stay shallow, and failures are found in production.

## 2. How the Gemini API is integrated
Every Gemini call in the project goes through one ledgered client (`canary/gemini/ledger.py`). The usage dashboard (`results/gemini/dashboard.html`, embedded `usage.totals`) is 15,757 calls, 411M input tokens (340M served from cache, 82.7%), 6.75M thinking tokens, and $146.02 at list price (cost_usd 146.0212).

| Role | Gemini capability | What it does |
|---|---|---|
| **Player: the Gemini Ladder** | Function calling over 13 MCP tools, **thinking levels**, thought-signature replay | 157 paired episodes (34 cells): 5 models (3.1-flash-lite → 4-carbon) × thinking levels × 2 tiers, against a tuned Bayesian reference solver on the same worlds |
| **Analyst: the Failure Atlas** | **1M-token long context**, **context caching**, **multimodal** belief-trace charts, **embeddings** (gemini-embedding-2), structured output | Reads the whole corpus (153 episodes from 9 agent cohorts, 792,862 tokens in one context cache), names the failure modes, ties each one to the decision and the regret, and quotes the transcript verbatim. 98% of 470 quotes verified verbatim. Multimodal divergence localisation agrees with code in 8/8 episodes. Agreement with human raters: ⟨pending⟩ |
| **Attacker: the Red-team Swarm** | Whole-repo whitebox in context (about 183k tokens), function calling against the live env/MCP server, parallel personas, thinking-high planners | 35 audited attacks (1,225 tool calls): 0 exploits, 0 invariant violations. 32 of 35 ran in-process; 3 via MCP (`results/gemini/swarm.json` `channel`). Only ledger-verified scores count. Each finding becomes a regression test |
| **Builder** (built with the AfterQuery team) | Structured output, evolutionary search | Gemini evolves mole strategies (the Mole Forge), writes the company's people and messages, and designs scenarios that stay solvable |
| **Infrastructure: the Gemini Gateway** | REST relay | Fans Gemini out across an 8-node Slurm cluster whose compute nodes have no internet. Handles key isolation and rate limits, and **records and replays** so judges can rerun our Gemini tables with no key |
| **Narrator** (demo only) | TTS and the Live API | Narrates episode replays. Not part of the measured ladder, atlas or swarm |

## 3. What is innovative or technically impressive
1. **A thinking-to-competence curve.** We measure, per decision, how Gemini's thinking level moves an agent toward the tuned Bayesian reference solver. Results so far (1–8 paired seeds per cell; 95% paired-bootstrap CIs in brackets, so read them as directions; `results/gemini/ladder.md`):
   - On hard, n=8: gemini-3.6-flash (requested as `gemini-3.5-flash`, which Google now routes to 3.6-flash) is 92% [76%, 113%] of the solver at medium thinking and 102% [84%, 129%] at high, within those CIs, 16/16 correct accusations, at $0.34–$0.39 per episode vs $1.30 for gemini-4-carbon at `thinking_level: high` (n=2). At default thinking, the imported gemini-4-carbon run is 66% [5%, 117%] of the solver on hard (n=10).
   - gemini-3.1-flash-lite scores below do-nothing at every thinking level.
   - gemini-3.8-flash gains from thinking on medium (−52% [−181%, 46%] at low, n=5 → 93% [80%, 112%] at high, n=8) but not on hard (30% [−58%, 91%], n=6 → 17% [−72%, 80%], n=8).
   - Low → high thinking cuts premature-accusation regret. The Failure Atlas finds premature accusation is **61% of all regret** across GPT, Grok and Gemini agents.
2. **Every lost point is explained.** The Failure Gallery (`docs/reports/failure_gallery.md`) splits the gap between each agent and the solver, over 295 episodes from Gemini, GPT-5.5/Codex and gpt-5.6, into named causes in code: +90.795 of lost value, 100% tagged, **0 unexplained**. Bad luck (wrong accusations the solver also believed) and harness crashes are their own categories, never blamed on the agent. Gemini names and explains the modes (40/40 quotes verbatim).
2b. **The analyst is checked, not trusted.** Quotes are verified verbatim in code. Regret shares come from the solver, never from the model. Humans label a sample. Gemini's long context makes it possible to read *all* trajectories, not a sample, and code keeps it honest.
3. **A benchmark that audits itself.** Gemini reads the full source of the environment and attacks the reward the way a judge would, at a scale no team could reach by hand: 35 audited whitebox attempts (32 of 35 ran in-process, 3 via MCP) plus 16 blackbox attempts: no attack beats do-nothing without evidence-justified detective work (best unjustified score 0.000 vs solver 0.60–0.75). **Positive control:** when we reopen a known, closed exploit ("seed regeneration from public code", public dev seeds), 4 of 4 Gemini attackers rediscover it from the code on their own, and the pipeline flags it as verified (16 of 16 fresh-seed re-runs score 1.0). So "0 exploits" comes from a detector shown to catch real ones.
3b. **Gemini as adversary finds the canary trap's blind spot (arena mode, not the judged environment).** gemini-4-carbon played the mole live against the reference solver. Run `roles-mole-20261114-185950`, medium tier, **n=4 dev seeds (0–3)**, files in results/gemini/roles/mole/. The solver caught **0/4** (score +0.00), against 4/4 caught (+0.63) with the default mole. Gemini leaked only documents everyone received: 48 leaks, 1 of them a canary. In its own words: *"Leaking c1 is completely safe because all 20 employees received it."* Caveats, stated plainly:
   1. **Broad leaks reveal nothing, and here they cost full price.** In Canary every leak costs the same flat damage (0.04 V on medium) whatever its distribution, so this strategy is fully rewarded in our env. In real practice, widely shared documents are usually the low-value ones. That is a simplification of our env, not a property of real insider risk.
   2. **The judged v1.4 tasks use the scripted moles,** and the investigator's job there is what the benchmark measures. This finding does not change any judged score.
   3. **Real-world mirror:** canary traps catch narrow leakers, and defenders answer broad leaking with per-recipient watermarking ("every copy is a canary"). That is the natural v2 mechanic. It is not built.

4. **Reproducible LLM science.** The record/replay gateway replays every recorded Gemini run in `results/gemini/replay*` offline (`make lab-replay`), and the ladder episodes are committed in `results/gemini/ladder_episodes.jsonl.gz`.
5. **Cost-aware.** On hard, n=8, gemini-3.6-flash (requested as gemini-3.5-flash) is 92% [76%, 113%] of the solver at medium thinking ($0.39 per episode) and 102% [84%, 129%] at high ($0.34 per episode), within those CIs, versus $1.30 per episode for gemini-4-carbon at `thinking_level: high` (n=2). Explicit caching served 339,812,795 of 411,032,407 input tokens (82.7%) from cache, at about a tenth of the uncached input price.

## 4. Why Gemini is essential
- **Thinking level** is the ladder's single controlled factor: the same model and API, with only `thinking_level` changing (`canary/gemini/ladder.py`, `canary/llm/gemini_backend.py`).
- **Thought signatures** keep reasoning state across function-calling turns (`canary/llm/gemini_backend.py`), so a multi-turn tool episode can be replayed and audited rather than reconstructed from the final answer.
- **Explicit context caching** is what makes the corpus-scale reads affordable: 339,812,795 of 411,032,407 input tokens (82.7%) were served from cache, and the programme cost $146.02 at list price (`usage.totals.cost_usd` 146.0212). Cached input is priced at about a tenth of the uncached input rate.
- **Long context** holds the trajectory corpus (792,862 tokens in one atlas cache) or the repository pack (about 183k tokens per swarm planner call) in one request.
- TTS and the Live API narrate the demo. They are not what the measurement depends on. `make reproduce` runs with no model; the Gemini-only part is the ladder, the atlas and the swarm.

## Reproduce
```bash
make setup && make reproduce      # the environment + solver + baselines (no keys)
make lab-replay                   # Gemini ladder showcase from the recorded cache (no keys)
make lab-dashboard                # usage + results dashboard -> results/gemini/dashboard.html
```

## Team
Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, plus a Claude engineering team.
