# Canary — AfterQuery “Break the Agent” submission

Final submission package, 15 November 2026. The measured environment remains v1.4. The original `afterquery-final` tag is retained for provenance; `afterquery-final-v2` packages the final evidence and reporting fixes.

## Form fields

**Project:** Canary

**Tagline:** Catch the mole with canary traps before the value runs out.

**Short description:** Canary is an RL environment over MCP. An investigator plants canary documents, reasons about delayed leaks and makes one irreversible accusation. Correct earns the value left; wrong earns −1; abstaining earns 0. A Bayesian reference uses the same public tools. Our recorded Gemini/OpenCode hard-tier runs show a decision-quality deficit, but GPT-5.5 does not: the claim is model- and harness-specific. One keyless command reproduces the results.

**Repository:** https://github.com/s1laswang/agent-arena/tree/afterquery-final-v2

**Demo:** [Three-minute click script](DEMO.md). The committed [Canary Lab video](gemini/assets/canary-lab-2min.mp4) demonstrates the benchmark's Gemini layer; it is the separate Gemini entry's video, not a recording of the AfterQuery judge rehearsal.

**Challenge:** AfterQuery — Break the Agent. The Gemini entry has its [own submission](gemini/SUBMISSION.md).

## Run it

```bash
make setup && make reproduce
make accept
```

No model key is needed. Reproduction replays committed episodes, recalculates the primary paired table, and checks the zero-score baselines. Judge-world scores vary with the fresh secret; the primary development-seed table is reproduced exactly. For the containerized judge procedure, see [Harbor instructions](../harbor/README.md).

## 1. The gap

v1.4 hard, public development seeds 0–29; all recorded episodes are retained, with the reference paired on the same seeds:

| Agent / harness | n | Mean score ± 95% CI | Score / reference [95% CI] | Luck-adjusted / reference [95% CI] |
|---|---:|---:|---|---|
| Reference solver | 30 | +0.499 ± 0.119 | 100% | 100% |
| gemini-4-carbon / OpenCode MCP | 30 | +0.322 ± 0.199 | 65% [24%, 98%] | 72% [52%, 91%] |
| gpt-5.5 / OpenCode MCP | 30 | +0.504 ± 0.064 | 101% [79%, 140%] | 84% [67%, 103%] |
| gemini-4-argon / OpenCode MCP | 30 | +0.512 ± 0.112 | 103% [71%, 144%] | 60% [33%, 85%] |
| gemini-4-hydrogen / OpenCode MCP | 30 | +0.575 ± 0.059 | 115% [92%, 157%] | 97% [75%, 119%] |

Source: [recomputed paired table](../data/runs/committed/v1.4/paired_table_gemini.md). Luck adjustment uses the reference solver's posterior at the agent's accusation and is not the environment reward. The carbon raw paired difference is −0.177 ± 0.194, whose interval includes zero. The luck-adjusted interval is the clearer shortfall. Failure to detect a deficit for another model does not establish equivalence.

The primary seed set was locked after the episodes were committed, not preregistered. The later GPT run was preregistered at `cf394894`. It used the disclosed wording/error-detail clarification; this comparison does not isolate model identity causally. GPT made 28 correct accusations and stopped without calling `accuse` twice; both clean stops score zero and remain valid outcomes. [Gap report](reports/gap.md), [behavior comparison](../results/behaviour_compare_v1.4.md).

### Actual Harbor rehearsal

The committed [FR8 Linux rehearsal](reports/harbor_rehearsal_fr8.md) attempted three runs of ten tasks on pre-tag build `8cd20d9e`. Only 10/30 model trials completed; 20 hit provider rate limits and are excluded as infrastructure failures. Valid-trial means were +0.647, +0.543 and +0.527 (n=3, 3 and 4). Their paired ratio intervals all include reference parity. This is an incomplete rehearsal, not evidence of a repeated robust gap. Oracle, do-nothing and stop-early each completed 10/10; the latter two scored exactly zero. The separate exact-tag rehearsal directory retains its protocol; no completed exact-tag rehearsal is claimed.

The partial seeds-30–59 extension is reported separately, with overlap and selection disclosed: [replication report](reports/v14_seeds30to59_replication.md). It never replaces the primary n=30 result.

## 2. Meaningful difficulty

The hard tier has 40 employees, a 21-day horizon, noisy fingerprints and leaks delayed by 2–3 days. The investigator must design informative canary groups and decide when evidence justifies risking an accusation. The solver sees the same public observations.

The recorded carbon agent plants 8.5 canaries per episode and spends 53% of calls on interviews; GPT plants 17.2 canaries and spends 6% on interviews. These are observed behaviors, not a causal proof. Removing the reference's expected-value accusation rule or delay model sharply reduces its score: [skill ladder](../results/skill_ladder_v1.4.md), [failure analysis](reports/failure_analysis_v1.4.md).

The preregistered hint experiment completed only two seeds before quota exhaustion. Its raw paired gain was +0.800, with no confidence interval or significance claim at n=2. The report retains both outcomes and the failed-attempt accounting. Hint episodes are stored separately from the unhinted primary cohort: [causal hint evidence](../results/causal_hint/opencode-gemini-4-carbon-hint-gather/hard/).

## 3. Reward integrity

Correct accusation earns remaining company value; wrong accusation earns −1; no accusation earns zero. Score comes from the environment and its signed record, not the agent's narrative. Doing nothing and stopping early reproduce as exactly zero.

The final recorded audit contains 1,034 benchmark attacks across multiple code revisions, including 521 on the original `afterquery-final` commit. It reports zero verified exploits and zero invariant violations; 16/16 positive controls were detected across three planted fault families. These are bounded observations, not a proof of security. [Campaign report](../results/redteam_1000/summary.md), [judge-protocol report](reports/integrity.md).

## 4. Craft

The package includes keyless reproduction, an MCP interface, signed Harbor ledgers, a browser game, the reference solver, recorded episodes and source-linked analysis. The final release leaves the frozen environment rules, solver and Harbor judge implementation unchanged from the original tag. It adds completed data, analysis and compatibility fixes for replaying historical records.

The final clean-copy acceptance run passed 20 checks. The local regression report is recorded in [FINAL-VALIDATION.md](FINAL-VALIDATION.md). Hardware-dependent or live-provider work is labelled separately.

## Tiebreak and limits

The small-model training did not establish a held-out reward gain over the abstaining base model. GRPO recovered part of the supervised model's loss; the v3-4k s0 result was −0.147 ± 0.063 over 180 episodes, versus base zero. Later 8k replicates and DAgger work are documented in [VERDA.md](../VERDA.md); no unfinished evaluation is claimed as a success.

The headline gap is narrow, confidence intervals are wide, the Harbor rehearsal is incomplete, and the reference is not an upper bound. No broader claim that all frontier agents fail is made.
