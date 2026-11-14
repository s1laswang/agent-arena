# Canary × Gemini

The Gemini write-up is **[docs/gemini/SUBMISSION.md](../docs/gemini/SUBMISSION.md)**. This page is a short pointer to it, so the two can never disagree.

- **Ladder:** Gemini's `thinking_level` is the only factor that changes, across 157 episodes paired with the Bayesian solver on the same worlds ([results/gemini/ladder.md](../results/gemini/ladder.md)).
- **Red team:** Gemini read the whole repo and made 51 audited attacks, with 0 exploits found. In the positive control, attackers rediscovered a known, reopened exploit 4 times out of 4 ([results/gemini/swarm.md](../results/gemini/swarm.md)).
- **Analyst:** Gemini organises and explains the failures the code attributes, quoting the transcripts. The [Failure Gallery](../docs/reports/failure_gallery.md) is an exact decomposition done in code; Gemini only names and explains its categories. Atlas v1 was not blind; see the honesty notes in the write-up.
- **Arena mole:** playing the mole in arena mode, gemini-4-carbon found the canary trap's blind spot (n=4, not the judged environment).
- **Usage:** 15,757 Gemini calls are logged ([results/gemini/dashboard.html](../results/gemini/dashboard.html)).

The earlier Mole Forge, world-builder and scenario-designer roles have no measured results in this submission and are not claimed.
