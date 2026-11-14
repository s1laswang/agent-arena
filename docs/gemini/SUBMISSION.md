# Canary Lab: Gemini builds, plays, attacks and explains its own benchmark

*Google DeepMind "Best Use of Gemini API" submission, Junction 2026. Repo: github.com/s1laswang/agent-arena (Canary Lab = `canary/gemini/`).*
*DRAFT v1 (Sat 18:40). Numbers are from committed files: results/gemini/{ladder,atlas,swarm}.md and the dashboard ledger as of Sat 18:30. They are refreshed before submission. Remaining `⟨…⟩` are still pending.*

## Short version (platform summary field, ≤ 600 chars)
Canary is an RL environment in which an AI agent, as head of security, must catch a mole by laying canary traps while the company's value bleeds away. A Bayesian solver sets the bar. Canary Lab puts Gemini at the centre of the science. 134 paired Gemini episodes across 6 models and thinking levels measure how much thinking buys how much competence. Gemini reads every trajectory in a 1M-token context to explain why agents fail, with verified quotes. A swarm of Gemini attackers reads our entire codebase to break the reward. Every number replays offline.

## 1. The problem and why it matters
Companies now give agents work where they must reason under uncertainty, spend a budget and commit to an irreversible decision: security triage, insider-risk, incident response, procurement. Benchmarks give back one number per model. That number cannot tell you:
- **where** the agent goes wrong (which decision, at which step);
- **whether more thinking would fix it**, and what that costs;
- **whether the score can be gamed.**

Answering those questions takes reading thousands of 300–400-step trajectories and auditing the reward code line by line, which nobody does by hand. So agent evaluations stay shallow, and failures are found in production.

## 2. How the Gemini API is integrated
Every Gemini call in the project goes through one ledgered client (`canary/gemini/ledger.py`). The usage dashboard and every number below come from that ledger: 11,187 calls, 251M input tokens (204M served from cache) and 4.4M thinking tokens, for $88.75 at list price, as of Sat 18:23.

| Role | Gemini capability | What it does |
|---|---|---|
| **Player: the Gemini Ladder** | Function calling over 13 MCP tools, **thinking levels**, thought-signature replay | 134 paired episodes (31 cells): 6 models (3.1-flash-lite → 4-carbon) × thinking levels × 2 tiers, against a Bayes-optimal reference on the same worlds |
| **Analyst: the Failure Atlas** | **1M-token long context**, **context caching**, **multimodal** belief-trace charts, **embeddings** (gemini-embedding-2), **Batch API**, structured output | Reads the whole corpus (153 episodes from 9 agent cohorts, 792,862 tokens in one context cache), names the failure modes, ties each one to the decision and the regret, and quotes the transcript verbatim. 98% of 470 quotes verified verbatim. Multimodal divergence localisation agrees with code in 8/8 episodes. Agreement with human raters: ⟨pending⟩ |
| **Attacker: the Red-team Swarm** | Whole-repo whitebox in context (about 183k tokens), function calling against the live env/MCP server, parallel personas, thinking-high planners | 35 audited attacks (1,225 tool calls): 0 exploits, 0 invariant violations. Only ledger-verified scores count. Each finding becomes a regression test |
| **Builder** (built with the AfterQuery team) | Structured output, evolutionary search | Gemini evolves mole strategies (the Mole Forge), writes the company's people and messages, and designs scenarios that stay solvable |
| **Infrastructure: the Gemini Gateway** | REST relay | Fans Gemini out across an 8-node Slurm cluster whose compute nodes have no internet. Handles key isolation and rate limits, and **records and replays** so judges can rerun our Gemini tables with no key |
| **Narrator** | **TTS** (and the **Live API**, stretch) | Narrates episode replays for the demo |

## 3. What is innovative or technically impressive
1. **A thinking-to-competence curve.** We measure, per decision, how Gemini's thinking level moves an agent toward a Bayes-optimal policy. Results so far (1–7 seeds per cell, wide CIs):
   - gemini-3.5-flash at medium/high thinking matches the solver on hard: 97% and 106% of the solver, 12/12 correct accusations, at $0.35–0.41 per episode vs $1.30 for gemini-4-carbon-high.
   - gemini-3.1-flash-lite scores below do-nothing at every thinking level.
   - gemini-3.8-flash gains from thinking on medium (−52% → 94%) but not on hard.
   - Low → high thinking cuts premature-accusation regret. The Failure Atlas finds premature accusation is **61% of all regret** across GPT, Grok and Gemini agents.
2. **The analyst is checked, not trusted.** Quotes are verified verbatim in code. Regret shares come from the solver, never from the model. Humans label a sample. Gemini's long context makes it possible to read *all* trajectories, not a sample, and code keeps it honest.
3. **A benchmark that audits itself.** Gemini reads the full source of the environment and attacks the reward the way a judge would, at a scale no team could reach by hand: 35 audited whitebox attempts plus 16 blackbox attempts: no attack beats do-nothing without evidence-justified detective work (best unjustified score 0.000 vs solver 0.60–0.75). **Positive control:** when we reopen a known, closed exploit (EXPLOITS #23, public dev seeds), 4 of 4 Gemini attackers rediscover it from the code on their own, and the pipeline flags it as verified (16 of 16 fresh-seed re-runs score 1.0). So "0 exploits" comes from a detector shown to catch real ones.
4. **Reproducible LLM science.** The record/replay gateway makes every Gemini number rerunnable offline (`make lab-replay`).
5. **Cost-aware.** The cost frontier shows gemini-3.5-flash (medium thinking) reaching solver level on hard at about 30% of the cost of gemini-4-carbon-high. Caching and the Batch API cut analysis cost by ⟨z⟩%.

## 4. Why Gemini is essential
- **1M-token context** is what lets one model read the entire trajectory corpus and the entire codebase at once. RAG over fragments loses the cross-episode patterns that make up the failure atlas.
- **Thinking levels on one model family** make the ladder a controlled experiment: the same model and API, with only the thinking level changing.
- **Caching, Batch and flash-lite pricing** make analysis and red-teaming at this scale cost ⟨$⟩ instead of ⟨$$⟩.
- **Native multimodal input, embeddings and TTS/Live** on the same API and key: charts in, clusters out, a narrated demo.
- Without Gemini there is no ladder, no atlas, no swarm and no evolved hard tier. Canary would be a single number.

## Reproduce
```bash
make setup && make reproduce      # the environment + solver + baselines (no keys)
make lab-replay                   # Gemini ladder showcase from the recorded cache (no keys)
make lab-dashboard                # usage + results dashboard -> results/gemini/dashboard.html
```

## Team
Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, plus a Claude engineering team.
