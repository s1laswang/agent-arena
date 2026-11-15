# Canary × Gemini

The Gemini write-up is **[docs/gemini/SUBMISSION.md](../docs/gemini/SUBMISSION.md)**. This page is a short pointer to it, so the two can never disagree.

- **Ladder:** Gemini's `thinking_level` is the only factor that changes, across 587 episodes paired with the Bayesian solver on the same worlds ([results/gemini/ladder.md](../results/gemini/ladder.md)).
- **Red team:** 100 ledger-verified Gemini attacks: 91 attackers over 4 waves (75 whitebox with the whole repo in context, 16 blackbox) plus 9 re-runs through the real MCP server, with 0 verified exploits. In a positive control, the same pipeline caught a deliberately reopened exploit 4 times out of 4. That validates the detector; the attackers had a tool that runs the public generator ([results/gemini/swarm.md](../results/gemini/swarm.md)).
- **Analyst:** blind, Gemini recovers 3 of 5 code-defined failure modes and names 2 new ones ([atlas_blind.md](../results/gemini/atlas_blind.md)). It also organises and explains the failures the code attributes. The [Failure Gallery](../docs/reports/failure_gallery.md) is an exact decomposition done in code; Gemini only names and explains its categories. Atlas v1 was not blind; see the honesty notes in the write-up.
- **Arena mole:** playing the mole in arena mode, gemini-4-carbon found the canary trap's blind spot (arena mode: adaptive Gemini mole, not the judged environment; n=4).
- **Usage:** 24,855 Gemini calls are logged ([results/gemini/dashboard.html](../results/gemini/dashboard.html)).

The earlier Mole Forge, world-builder and scenario-designer roles have no measured results in this submission and are not claimed.
