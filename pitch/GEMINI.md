# Gemini: agents you can trust

The Gemini write-up is **[docs/gemini/SUBMISSION.md](../docs/gemini/SUBMISSION.md)** (one page; details in [SUBMISSION-LONG.md](../docs/gemini/SUBMISSION-LONG.md)). This page only points to it, so the two can never disagree.

- **HoldUp, the product** ([junction-meta-glasses `GEMINI.md`](https://github.com/s1laswang/junction-meta-glasses/blob/gemini-quote-0515/GEMINI.md)): a hands-free label reader for blind and low-vision users on the Gemini Live API. 0 of 754 confident strength reads were wrong across 1,740 Gemini-generated test images.
- **Canary Lab, the proof** (`canary/gemini/`): Gemini plays, attacks and explains an insider-threat benchmark scored against a Bayesian solver.
  - **Ladder:** `thinking_level` is the only factor changed; each step up adds +16.3 [+7.6, +24.4] points of the solver's score, pooled over 570 paired episodes ([thinking_effect.md](../results/gemini/thinking_effect.md), [ladder.md](../results/gemini/ladder.md)).
  - **Cross-provider control:** Gemini against committed GPT-5.5 episodes on identical worlds ([xprov.md](../results/gemini/xprov.md)).
  - **Red team:** 513 audited attacks, 0 verified exploits; the detector caught 16 of 16 planted exploits across three reopened exploit families ([swarm.md](../results/gemini/scale/swarm3/swarm.md)).
  - **Jury:** three Gemini judges, blind to our labels, match the code's label on 84.9% [81.0, 88.0] of 403 tagged decisions ([jury.md](../results/gemini/scale/jury/jury.md)).
  - **Analyst:** without our labels, Gemini recovers 3 of 5 code-defined failure modes and names 2 new ones ([atlas_blind.md](../results/gemini/atlas_blind.md)).
- **Usage:** one de-duplicated total of every logged Gemini call is in [usage_total.json](../results/gemini/usage_total.json) and the [dashboard](../results/gemini/dashboard.html).

The Canary environment itself is the team's AfterQuery entry; nothing on this page is an AfterQuery claim. The earlier Mole Forge, world-builder and scenario-designer roles have no measured results here and are not claimed.
