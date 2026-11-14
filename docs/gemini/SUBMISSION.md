# Canary Lab: thinking as a controlled variable, and a Gemini red team you can trust

*Google DeepMind "Best Use of Gemini API", Junction 2026. Code: github.com/s1laswang/agent-arena (`canary/gemini/`). Every number below links to a committed file. Model ids are as listed by the Gemini API (`models.list`) on our key on 14 Nov 2026. When we request `gemini-3.5-flash`, the API serves **`gemini-3.6-flash`** (recorded per call in the ladder provenance), so this text says "3.6-flash".*

## Short version (≤ 600 chars)
Canary is an RL environment where an AI head of security must catch a mole with canary traps while company value bleeds away, scored against a Bayesian reference solver. We used Gemini's thinking level as a controlled variable across 157 paired episodes, and on hard, 3.6-flash reaches the solver at a quarter of carbon-high's cost (n=8, wide CIs). A Gemini red team read our whole repo and found 0 exploits, and in a positive control it re-found a known exploit 4/4. 15,757 Gemini calls, all logged.

## 1. The problem
Agents now make irreversible decisions under uncertainty with a budget: security triage, insider risk, procurement. A benchmark gives one number per model. It can't tell you whether more thinking would help, what that costs, or whether the score can be gamed. Answering that needs controlled experiments and an adversarial audit, at a scale nobody does by hand.

## 2. How Gemini is integrated
Every Gemini call goes through one client that writes one log row per call (`canary/gemini/ledger.py`). The totals are 15,757 calls, 411M input tokens of which 340M (82.7%) came from cache, 6.75M thinking tokens, and $146.02 at list price (`results/gemini/dashboard.html`, `usage.totals`).

| Role | Gemini-specific capability | Result (committed) |
|---|---|---|
| **Player: the Ladder** (`ladder.py`) | `thinking_level` as the only changed factor; thought-signature replay across function-calling turns (13 MCP tools) | 157 paired episodes, 34 cells (5 models × levels × 2 tiers), same worlds as the solver (`results/gemini/ladder.md`) |
| **Attacker: the Red-team Swarm** (`swarm.py`) | The whole repo in one long-context prompt (about 183k tokens), function calling against the env | 51 audited attacks (35 whitebox, of which 32 in-process and 3 via the real MCP server; 16 blackbox): **0 exploits**. **Positive control: 4/4** (`results/gemini/swarm*.md`) |
| **Analyst: Atlas and Gallery** (`atlas.py`, `gallery.py`) | 793k-token corpus in one explicit context cache on 3.8-flash; multimodal belief charts; embeddings | Organises and explains code-attributed failures with quotes (`results/gemini/atlas.md`, `docs/reports/failure_gallery.md`). See the honesty notes |
| **Adversary: the arena mole** (`roles.py`) | gemini-4-carbon plays the mole live | Finds the canary trap's blind spot (§3.3) |
| **Infrastructure** (`gateway.py`) | Token-gated relay for clusters without internet; record/replay | The showcase and 4 ladder episodes replay keyless (`make lab-replay`) |
| **Demo only** | TTS (3.8-flash-tts), Live API (3.8-live) | Narration and a live commentator clip. Not part of any measurement |

## 3. What is innovative
1. **Thinking as a controlled variable on a solver-referenced benchmark** (`results/gemini/ladder.md`). Each cell has 1–8 paired seeds, so the 95% paired-bootstrap CIs are wide; read these as directions.
   - On hard (n=8), 3.6-flash is 92% [76, 113] of the solver at medium thinking ($0.39 per episode) and 102% [84, 129] at high ($0.34). It made 16/16 correct accusations. gemini-4-carbon at high costs $1.30 per episode (n=2).
   - 3.1-flash-lite scores below do-nothing at every thinking level.
   - 3.8-flash improves with thinking on medium (−52% at low → 93% [80, 112] at high) but not on hard.
   - These are real Gemini-only controls (`thinking_level`, thought signatures), not a swappable LLM slot. The OpenAI backend in the repo is used only for the AfterQuery comparison runs.
2. **A red team proven by a positive control** (`results/gemini/swarm.md`, `swarm_control.md`).
   - Gemini attackers read the full source and attack the reward. Scores come only from the server's ledger, and every correct accusation is audited against the solver's posterior, so detective work is not mistaken for an exploit.
   - In 51 attacks, the best score not justified by evidence was 0.000, against a solver score of 0.60–0.75.
   - To show the detector works, we reopened a known exploit ("seed regeneration from public code"). **4/4 attackers rediscovered it from the code, and 16/16 fresh-seed re-runs scored 1.0, flagged as verified.** "0 exploits" therefore comes from a detector shown to catch a real one.
3. **Gemini as adversary finds the canary trap's blind spot** (arena mode, not the judged env; medium, n=4 dev seeds 0–3, run `roles-mole-20261114-185950`).
   - The gemini-4-carbon mole was caught 0/4 times (solver score +0.00), against 4/4 caught (+0.63) with the default mole.
   - It leaked only documents everyone had: 48 leaks, 1 of them a canary. In its words: *"Leaking c1 is completely safe because all 20 employees received it."*
   - Caveats:
     - Our env charges flat damage per leak whatever the distribution. That is a simplification; broadly shared documents are usually the low-value ones.
     - The judged tasks use scripted moles.
     - The real-world fix, per-recipient watermarking, is a natural v2 mechanic and is not built.
4. **Cost-aware evaluation.** Caching served 82.7% of all input tokens. The cost frontier is in `results/gemini/ladder_cost.png`.

**Honesty notes**
- **Atlas v1 is not blind.** Its corpus showed Gemini our code-computed regret tags and solver beliefs. So Gemini *organised and explained* failures the code had already attributed; it did not discover them from scratch. A blind re-run strips those fields, lets Gemini find the modes, and scores recovery against our tags in code: `results/gemini/atlas_blind.md` (if present).
- **The Failure Gallery is an exact code decomposition.** "0 unexplained" holds by construction. Gemini only names and explains the categories.
- **The multimodal chart check is a consistency check, not independent discovery.** The charts plot code-computed solver beliefs. Gemini placed the divergence within 3 steps of the code's estimate in 8/8 episodes (`results/gemini/v2/atlas.json` `localisation`).
- **No human-agreement number is claimed.**
- **The AfterQuery gap is harness-dependent.** The AfterQuery team reports a gap on hard in the OpenCode/MCP harness and parity in-process; see their `docs/reports/gap.md`. We make no frontier-gap claim here.

## 4. Why Gemini is essential
- **`thinking_level`** on one model family is what makes the ladder a controlled experiment.
- **Thought signatures** keep reasoning state across tool turns, so episodes replay and audit exactly.
- **Explicit context caching** makes corpus-scale and repo-scale reads affordable: 82.7% of 411M input tokens were cached.
- **1M-token context** fits the whole trajectory corpus or the whole repo in one request.
- **Live, TTS, multimodal and embeddings** sit on the same API and key.

## Gemini across the team (breadth)
Gemini is used in all three of our Junction challenges, most heavily here.
- **Valio Aimo** (github.com/s1laswang/junction-aimo-agents, `docs/GEMINI.md`):
  - The buyer agent uses function calling on gemini-3.8-flash and escalates 19% of steps to gemini-4-hydrogen at high thinking.
  - gemini-embedding-2 drives catalog substitution.
  - Compacting the tool results the agent re-sends with each call cut cost per order by 59%.
  - All 6 of 6 scenarios in the live demo montage pass.
- **Meta glasses: HoldUp** (github.com/s1laswang/junction-meta-glasses), a hands-free label checker for blind and low-vision users:
  - The Live API with function calling mid-stream;
  - schema-constrained label verification with per-field confidence;
  - box_2d spatial grounding;
  - speculative verification that cut question-to-first-audio from 5.8 s to 0.8–1.8 s;
  - a 1,740-image eval with Wilson CIs.

## Reproduce
```bash
make setup && make reproduce   # environment, solver and baselines (no keys)
make lab-replay                # recorded Gemini runs, keyless
make lab-dashboard             # usage and results dashboard
```

## Team
Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), Chintufp, with a Claude engineering team.
