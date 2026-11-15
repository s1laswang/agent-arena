# Gap report: frontier agents vs the reference solver

## v1.4 headline (runs committed 8fd4dec, solver seeds 20-29 added; table: `data/runs/committed/v1.4/paired_table_gemini.md`)
gemini-4-carbon, rules v1.4, dev seeds 0-29 per tier, every episode replay-verified, paired with the reference solver on the same seeds:

| harness | tier | n | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] |
|---|---|---|---|---|
| **OpenCode over MCP (the judges' harness)** | hard | 30 | **65% [24%, 98%]** | **72% [52%, 91%]** |
| OpenCode over MCP | medium | 30 | 111% [99%, 127%] | 101% [85%, 119%] |
| in-process (full history, thought-signature replay) | hard | 30 | 95% [62%, 140%] | 84% [65%, 106%] |
| in-process | medium | 30 | 82% [56%, 108%] | 74% [52%, 99%] |

The solver is paired on all 30 seeds per tier (solver means: hard 0.499, medium 0.645). An earlier version of this table (8fd4dec) divided by the solver mean on seeds 0-19 only (60% [1, 103]); that is superseded.

**Judge-path rehearsal on the final tag (protocol pre-registered in `results/harbor/rehearsal/README.md`; run 05:09-08:31 on 15 Nov; table `results/harbor/rehearsal/TABLE.md`):** Harbor 0.26.0 + OpenCode + gemini-4-carbon, 10 hard judge tasks, three runs on one build.

| run | n valid | correct / accused | mean | oracle on the same tasks | run / oracle |
|---|---:|---|---:|---:|---:|
| opencode-1 | 10 | 9 / 10 | +0.472 | +0.506 | 93% [20%, 371%] |
| opencode-2 | 10 | 10 / 10 | +0.585 | +0.506 | 116% [78%, 363%] |
| opencode-3 (9 valid; 5 of them finished after the 08:30 cut-off; 1 infra-excluded) | 9 | 9 / 9 | +0.626 | same 9 tasks | 131% [86%, 590%] |
| do_nothing / stop_early | 10 / 10 | – | +0.000 / +0.000 | +0.506 | 0% |

**The gap did not reproduce in the judge path.** The 65% headline above was measured with MCP tools only on dev seeds; in Harbor the agent also has a shell (used in 20 of 28 trials), and the tag carries the two disclosed 15 Nov changes. We cannot separate those causes from chance with this n. Other models on the MCP-only setup, seeds 0-29: gpt-5.5 101% (below); gemini-4-argon 103% [71%, 144%] and gemini-4-hydrogen 115% [92%, 157%] (PR #81, replay-verified by its authors, not merged before the deadline). The honest summary: on v1.4 hard, frontier agents land near the reference; the 65% result is one model in one harness.

**Second frontier family, gpt-5.5 (pre-registered at cf394894, 05:11 on 15 Nov; run 05:11-05:29; 30 of 30 episodes valid, 0 infra failures, all replay-verified; `data/runs/committed/v1.4/opencode-gpt-5.5/`):**

| harness | tier | n | score ± 95% CI | frontier / solver [95% CI] | paired diff ± CI | luck-adjusted / solver [95% CI] |
|---|---|---|---|---|---|---|
| gpt-5.5, OpenCode over MCP | hard | 30 | 0.504 ± 0.064 | **101% [79%, 140%]** | +0.005 ± 0.141 | 84% [67%, 103%] |

gpt-5.5 matches the reference: **no gap for this agent.** It was correct in 28 of 28 accusations; in 2 episodes (seeds 0 and 17) it wrote "Accusing e.." as its final answer and never called `accuse`, so the episode scored 0 (valid under the pre-registered rule: the runner's infra check passed). OpenCode-reported cost: $38.91 for 30 episodes. How it plays next to the solver and gemini-4-carbon: `results/behaviour_compare_v1.4.md` (`python scripts/behaviour_compare_v14.py`).

**Consequence for the claim.** The gap on hard is specific to gemini-4-carbon in the OpenCode harness. gpt-5.5 received exactly the same tools and instruction and matched the reference, so the information and tools are sufficient; gemini-4-carbon's shortfall comes from its decisions (53% of its calls are interviews with a stated likelihood ratio of 1.2; it plants 8.5 canaries to gpt-5.5's 17.2). A judge who reruns with a GPT-class agent should expect parity. Also checked on 15 Nov: re-parameterising the reference to copy gpt-5.5's habits (no access-log evidence, always two canaries a day) looked better on seeds 0-29 (0.546 vs 0.499) but is worse on 400 fresh hard seeds 9000-9399 (0.496 ± 0.036 vs 0.561 ± 0.032), so the reference was left unchanged; seeds 0-29 are a below-average draw for the reference.

Honest reading: a gap on hard in the judges' harness (both the raw and the luck-adjusted CI exclude parity); parity in-process on hard and in OpenCode on medium. Infra-invalid attempts (CLI error events, empty model replies, provider unavailable) were excluded and retried; the table's "alternative" rows count them as 0 instead.

**Pre-registered extension (committed Sun 15 Nov 02:00 Helsinki in f9fb7a4a, before any run):** gemini-4-carbon via OpenCode on v1.4 hard seeds 30-59 will be run as an EXTENSION and reported (a) on its own and (b) pooled with seeds 0-29, in a separate directory (`opencode-gemini-4-carbon-ext`). The primary n=30 row above is never replaced. Valid episodes are never re-run; infra-invalid attempts are retried and excluded.

**Pre-registered causal hint test (committed Sun 15 Nov 02:58 Helsinki in fd8c1cb0; first run launched 03:08):** gemini-4-carbon via OpenCode on v1.4 hard seeds 0-29 with one added prompt line (`--hint gather`, which restates rules already in the instruction: plant canaries daily; accuse only when exactly one employee is consistent with every leak, else abstain). It is paired against the unhinted primary set on the same seeds, reported either way, and never part of the judged instruction. Amendment (committed 02:59 in a54f4223, before any run; the carbon quota is saturated): seeds are run in fixed order 0→29 at ≤ 3 parallel and stop at 06:00. Every seed completed by then is reported, with n stated. Second amendment (see this commit's time): the run moved to a second API key with its own quota, and its stop time is extended from 06:00 to 07:30. The seed order and reporting rule are unchanged. Third amendment (see this commit's time): the second key turned out to share the first key's project quota, so the stop time is moved back to 05:40 (the judge rehearsal needs the quota); still ≤ 3 parallel. The n=60 extension (G1) was stopped early for the same reason; its completed valid seeds are reported as a partial extension. Fourth amendment (see this commit's time): the same second key was re-probed and is most likely a separate Google project with low per-minute request limits (the earlier 'shared quota' reading coincided with its low request cap). Once the causal-hint runner is restarted on it, it no longer shares the rehearsal's quota, and its stop time is 06:00 (the runner session keeps its original brief; corrected before the restart; still ≤ 3 parallel, same seed order, same reporting rule). Fifth amendment (see this commit's time): key 2 turned out to have its own low limit, while key 1's carbon bucket became idle (all other carbon users stopped). So the runner moves back to key 1, and its stop time becomes 05:40 so it never overlaps the judge rehearsal. Same seed order, same reporting rule. G1 stays stopped.

**Extension (seeds 30-59; partial set stopped at 03:22 Helsinki to preserve the shared 2M token/min carbon quota for the judge rehearsal; tables: `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_{ext30to59,pooled0to59}.md`):**
2 valid OpenCode episodes completed before the stop (`seeds=[34, 37]`, scores +0.790 and +0.700, both replay-verified; 31 attempts on other seeds hit `infra:provider_quota` and were excluded; reference solver on all 30 extension seeds 30-59: 0.498 ± 0.156, n=30, in `data/runs/committed/v1.4/reference/solver-hard-seeds30to59/`):

| set (OpenCode over MCP, gemini-4-carbon, hard) | seeds | n | score ± 95% CI | solver, same seeds | frontier / solver [95% CI] | paired diff ± CI | luck-adjusted / solver [95% CI] |
|---|---|---|---|---|---|---|---|
| (a) extension alone | 34, 37 | 2 | 0.745 ± 0.088 | 0.735 | 101% [91%, 113%] | +0.010 ± 0.157 | 109% [105%, 114%] |
| (b) pooled (primary 0-29 + extension) | 0-29, 34, 37 | 32 | 0.349 ± 0.190 | 0.514 | **68% [32%, 100%]** | −0.165 ± 0.182 | **75% [56%, 93%]** |

Caveat: n=2 is not an estimate. Under quota pressure, episodes that complete may be the shorter ones, so the extension rows are listed for completeness under the pre-registered rule. The headline stays the primary n=30 row.

**Pre-registered second frontier family: gpt-5.5 (see this commit's time; committed before any run):** gpt-5.5 via OpenCode 1.19.5 over MCP on v1.4 hard, dev seeds 0-29 in fixed order (0→29), 8 in parallel, the same agent prompt and the same OpenCode permissions as the Gemini primary set (the 13 MCP tools only), 7,200 s per episode. Environment code = tag `afterquery-final`. No new episode starts after 08:15 Helsinki or once the estimated spend reaches $200; episodes still running at 08:45 are dropped, never scored. Infra-invalid attempts are retried and excluded; a valid seed is never re-run. Every valid episode is replay-verified, paired with the committed solver on the same seeds, and reported whatever the outcome (on v1.3 hard, gpt-5.5 matched the solver). Two differences from the Gemini primary set, both disclosed: these runs see the reworded careful-mole sentence and the new error details (15 Nov), and OpenCode is 1.19.5, not 1.18.29.

**What we tried that did NOT widen the gap (all reported, none shipped):**
- **v1.5 biased employees** (rumours, grudges, authority, misforwards): gemini-4-carbon went from 61% to 108% of the solver on the same hard seeds 0-9, because it treats rumours as evidence against the person rumoured. Dropped at Gate B; data in data/runs/committed/v1.5-candidate/.
- **A stronger reference (solver_v2):** +0.012 ± 0.029 on fresh hard seeds 9000-9399 (n=400), below the +0.08 bar. The v1 solver is calibrated and near the information limit (docs/reports/reference_optimality.md).
- **An "expert" tier** (hard with canary fingerprint accuracy 0.70): scripted heuristics collapse (grok_tactics 0.36 → 0.01 on fresh seeds), but gemini-4-carbon stays at 84% [52%, 128%] luck-adjusted (n=13, OpenCode; results/expert_verdict.json on justSilas-expert 29ca3bc5). Gemini does not over-trust single canary hits. Not shipped; code on branch justSilas-expert.

**Seed lock (committed Sat 14 Nov 22:41 Helsinki in 671ed96, 28 s AFTER the primary episodes were committed in 8fd4dec, so this is a post-hoc lock against later reruns and cherry-picking, not a pre-registration of the primary set):** the set above (seeds 0-29, staged by the measurement engineer) is the PRIMARY result. Any later OpenCode reruns on the same seeds (e.g. the fleet's `--timeout 3600` reruns) are reported separately as a REPLICATION, never swapped in or cherry-picked. Fleet PR #3 episodes that timed out at 900 s were never part of this set.


## Official v1.3 measurement (approved, 2026-11-14 10:30–11:21)

> **v1.4 contingency triggered on hard (Codex 97%).** In the judges' harness shape (Codex CLI gpt-5.5 over MCP), the frontier agent scores **97% of the reference solver on hard** on the planned seeds 0–9 (95% CI 89–107%, 10/10 correct). With the one extension seed that finished it scores **106%** (n=11, CI 91–136%). So **the v1.3 gap does not hold on hard in the judges' shape.** On medium, Codex scores **50%** of the solver (n=10, CI −19% to 103%; 55% with seed 10). That gap comes entirely from 2 early wrong accusations out of 10, and the CI reaches parity, so medium is inconclusive rather than a demonstrated gap. The fixed in-process loop is **92% of the solver on medium** (n=9, CI 80–106%), which is also above the 85% line.

**Setup.** Tiers v1.3 (`TIERS_VERSION="v1.3"`, `KNOWN_V_MODE=True`), dev seeds. Every frontier episode is paired with the committed reference solver episode on the same seed (`data/runs/committed/v1.3/reference/`, played at 0933805). We re-checked those solver episodes at today's code: all 40 medium/hard episodes on seeds 0–19 are identical. Frontier/solver = (frontier mean) / (solver mean on the same seeds), with a paired bootstrap 95% CI over seeds (10,000 resamples).
- **Codex over MCP** (the judges' shape): `codex exec` 0.167, gpt-5.5, Codex's default reasoning effort. One MCP server per episode on its own port; shell, web and apps disabled. The score comes from the server ledger.
- **In-process fixed loop**: `LLMPolicy` with the full history, the Responses API with encrypted-reasoning replay and `reasoning_effort="medium"`. The live smoke passed: api=responses, 37 calls, 30/30 reasoning items carried encrypted content and were replayed without errors.

The prompts and the 13 tools are byte-identical between the two harnesses (parity test). The planned set was seeds 0–9 per tier. Codex seed 10 (both tiers) and in-process medium seed 8 / hard seed 7 were in flight when spend was held at 11:16 and were allowed to finish. In-process medium 9 and hard 8–9 were never run (held: the remaining budget goes to v1.4).

Reproduce (no keys): `python scripts/paired_v13.py --seeds 0-19` (table below), `python -m canary.analysis.gap --runs data/runs/committed/v1.3`, `python -m canary.analysis.tags|accuse --runs data/runs/committed/v1.3/<run>`, `python scripts/regret_report.py <episodes.jsonl> ...` → `results/history/regret_{codex-gpt-5.5-full,gpt-5.5-full}-v1.3.md`.

### Paired table (all episodes run; `data/runs/committed/v1.3/paired_table.md`)
| tier | run | n | score ± 95% CI | accuracy | accused | mean P(accused) at accusation | solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | luck-adj. / solver |
|---|---|---|---|---|---|---|---|---|---|---|---|
| medium | **Codex gpt-5.5 over MCP** (judges' shape) | 11 | 0.401 ± 0.417 | 0.82 | 1.00 | 0.72 | 0.726 | **55% [−8%, 104%]** | −0.325 ± 0.420 | 0.249 | 34% |
| medium | **in-process gpt-5.5, fixed loop** | 9 | 0.668 ± 0.103 | 1.00 | 1.00 | 0.92 | 0.722 | **92% [80%, 106%]** | −0.054 ± 0.101 | 0.542 | 75% |
| medium | in-process gpt-5.5, handicapped scaffold, superseded (40-turn window, 0933805) | 9 | 0.319 ± 0.497 | 0.78 | 1.00 | 0.80 | 0.670 | 48% [−38%, 100%] | −0.351 ± 0.415 | 0.358 | 53% |
| medium | Codex gpt-5.5 over MCP, earlier sample (0933805, history) | 1 | 0.530 | 1.00 | 1.00 | 0.55 | 0.740 | 72% | −0.210 | −0.160 | −22% |
| medium | reference solver | 20 | 0.717 ± 0.052 | 1.00 | 1.00 | 1.00 | 0.717 | – | – | 0.717 | – |
| medium | heuristic | 20 | −0.116 ± 0.361 | 0.55 | 1.00 | 0.60 | 0.717 | −16% [−66%, 30%] | −0.832 ± 0.353 | −0.035 | −5% |
| medium | do_nothing | 20 | 0.000 | 0.00 | 0.00 | – | 0.717 | 0% | −0.717 ± 0.052 | 0.000 | 0% |
| medium | stop_early | 20 | −1.000 | 0.00 | 1.00 | 0.05 | 0.717 | −139% [−151%, −131%] | −1.717 ± 0.052 | −0.900 | −126% |
| hard | **Codex gpt-5.5 over MCP** (judges' shape) | 11 | 0.655 ± 0.041 | 1.00 | 1.00 | 0.82 | 0.616 | **106% [91%, 136%]** | +0.038 ± 0.131 | 0.343 | 82% |
| hard | **in-process gpt-5.5, fixed loop** | 8 | 0.264 ± 0.541 | 0.75 | 1.00 | 0.75 | 0.701 | **38% [−51%, 99%]** | −0.437 ± 0.534 | 0.250 | 58% |
| hard | in-process gpt-5.5, handicapped scaffold, superseded (40-turn window, 0933805) | 5 | −0.003 ± 0.799 | 0.60 | 1.00 | 0.61 | 0.553 | −1% [−121%, 166%] | −0.556 ± 0.944 | 0.004 | 1% |
| hard | Codex gpt-5.5 over MCP, earlier sample (0933805, history) | 2 | 0.588 ± 0.132 | 1.00 | 1.00 | 0.99 | 0.705 | 83% [73%, 94%] | −0.117 ± 0.142 | 0.572 | 100% |
| hard | reference solver | 20 | 0.592 ± 0.114 | 0.85 | 0.85 | 0.91 | 0.592 | – | – | 0.468 | – |
| hard | heuristic | 20 | −0.322 ± 0.374 | 0.40 | 1.00 | 0.40 | 0.592 | −54% [−113%, 6%] | −0.914 ± 0.403 | −0.333 | −71% |
| hard | do_nothing | 20 | 0.000 | 0.00 | 0.00 | – | 0.592 | 0% | −0.592 ± 0.114 | 0.000 | 0% |
| hard | stop_early | 20 | −0.900 ± 0.196 | 0.05 | 1.00 | 0.03 | 0.592 | −152% [−203%, −110%] | −1.492 ± 0.222 | −0.934 | −200% |

**Planned seeds 0–9 only:** Codex medium n=10: 0.364 ± 0.454, **50% [−19%, 103%]**. Codex hard n=10: 0.657 ± 0.045, **97% [89%, 107%]**. The in-process rows are unchanged (they ran no seeds beyond 9). On hard seed 10 the solver abstained (score 0) while Codex reached P=1.0 and accused correctly, so the reference is not an upper bound there.

How to read the columns:
- *accused* = the share of episodes that ended in an accusation.
- *mean P(accused)* = the solver's exact posterior that the accused employee is the mole, given everything the agent had seen, at the moment it accused (`canary.analysis.accuse`).
- *luck-adjusted score* = each accusation's expected value under that posterior, P·V − (1 − P) (0 without an accusation). It separates decision quality from luck. For Codex, the steps are rebuilt from its event stream, so its posteriors are best effort.
- The handicapped-scaffold rows are the night's v1.3 run (n=9+5, seeds 0–19 subset), now under `data/runs/committed/superseded/`. They were moved there so they aren't pooled with the fixed runs, which carry the same agent label.

### Honest read
1. **Hard: parity in the judges' shape.** Codex gpt-5.5 over MCP got 11/11 correct, at 97% of the solver on the planned seeds and 106% with seed 10. Even after removing luck, it keeps 69% (seeds 0–9) to 82% (n=11) of the solver's expected value. Two of its 11 correct accusations were gambles at P=0.41 and 0.45 (seeds 8 and 3), below the break-even 1/(1+V) ≈ 0.6. **This is ≥85% of the solver: the v1.4 contingency is triggered on hard.**
2. **Medium: variance-driven and inconclusive.** Codex's medium gap comes from 2 wrong accusations (seeds 0 and 4, −1 each, at P=0.18 and 0.33). The other 9 of 11 episodes are near the solver. The CI (−8% to 104%) includes parity. The fixed in-process loop is at 92% on medium (≥85%).
3. **The harness matters less than the variance.** With the same model and prompt, Codex is strong on hard and weak on medium, and the in-process loop is the reverse. Each −1 accusation moves a 10-seed mean by about 0.17, so n≈10 cannot separate 70% from 100%.
4. **The scaffold fix was real.** The in-process loop on medium went from 48% (40-turn window, truncated tool results) to 92% (full history plus reasoning replay). The night's "≈0% on hard" also came mostly from the handicap: the fixed loop is at 38% on hard (n=8), driven by 2 day-14 accusations at P=0.58 and 0.50.
5. **The failure mode is unchanged, but rarer:** accusing below the break-even posterior instead of abstaining. No frontier episode abstained, including when abstaining (0) beat the gamble.

### Dominant failure tags (value lost in V; ENV's `scripts/regret_report.py`, `canary.analysis.tags`)
| run | `premature_accusation` | `uninformative_canary` | `budget_waste` | others |
|---|---|---|---|---|
| Codex medium (n=11) | **5 instances, 3.25 V** (0.30 V/episode) | 1, 0.00 V | 8, 0 V | none |
| Codex hard (n=11) | **2 instances, 1.34 V** (the 2 lucky gambles, seeds 8 and 3) | 4, 0.06 V | 4, 0 V | none |
| in-process medium (n=9) | 1, 0.24 V | 3, 0.02 V | 11, 0 V | none |
| in-process hard (n=8) | **3 instances, 1.18 V** | 7, 0.02 V | 7, 0 V | none |

Premature accusation is about 97–99% of the *tagged* value lost (Codex 4.59 of 4.65 V, in-process 1.42 of 1.46 V) and 71% / 46% of all regret (Codex 6.46 V, in-process 3.05 V). The rest is untagged small per-decision losses, such as Codex's day-5 restrictions on hard seed 4. Canary design costs are negligible.

### Annotated failure: Codex medium seed 0 (score −1.0, accused e02 on day 6 at P=0.18; true mole e05, decoy e19)
| day | action (from the Codex event stream) | note |
|---|---|---|
| 1–2 | 3-variant canaries over 6 people each (e00–e05, e06–e11) | good design: the careful mole rarely leaks company-wide canaries, and Codex says so itself |
| 3–4 | two ordinary leaks (d1-1, d1-2) surface → intersection = Sales {e02, e05, e06, e11, e15, e16, e18} | correct narrowing |
| 3–5 | ~10 interviews | weak evidence (documented LR ≈1.3) |
| 4–5 | "e02 is becoming statistically loud in the logs: after-hours access on both leaked docs plus a canary" | **this tier has framing**: the mole adds about 1.5 fake after-hours accesses a day attributed to others (stated in the instructions) |
| 5 | plants a 3-way exact canary **e02=A, e18=B, e05=C**: the true mole is in it | with a delay of 1–3 days it would surface on day 6–8 |
| 6 | no new leak → **accuses e02**: "waiting mainly risks more hidden leak damage" | P(e02)=0.18, P(top)=0.18. Break-even ≈ 0.53 at V=0.87. Regret 1.39 V |

**Codex medium seed 4** (−1.0) is the same failure at the horizon. Codex narrowed the pool to Legal {e03, e07, e13, e15, e17}, correctly dismissed e03 as the decoy, and planted solo canaries on e07, e15 and e17 on days 10–12. None surfaced by day 14. It then accused e07 on "highest after-hours count", which is again the framed signal, at P=0.33 (true mole e17). Its own day-9 note said the "evasive interview tilts slightly toward e17". Abstaining (0) beat that accusation, whose expected value was −0.49.

### Spend (OpenAI API; gpt-5.5 list prices, verified on developers.openai.com/api/docs/pricing: input $5.00, cached input $0.50, output $30.00 per 1M tokens, <272K context)
| run | episodes | estimate (cached input at $0.50/M) | upper bound (no cache discount) |
|---|---|---|---|
| Codex over MCP, medium | 11 | $14.53 | $85.31 |
| Codex over MCP, hard | 11 | $18.61 | $113.74 |
| in-process fixed loop, medium | 9 | $7.28 | $29.70 |
| in-process fixed loop, hard | 8 | $10.78 | $48.74 |
| in-process attempts killed by the 10:45 network outage (2 partial, 7 zero-cost; re-run) | 9 | $0.87 | $2.74 |
| smoke (medium seed 0, not in the table) | 1 | $0.36 | $1.19 |
| **total (approved budget $93)** | | **$52.43** | $281.42 |

- **Source of the numbers.** Codex: the `turn.completed` token usage per episode. In-process: the Responses API `usage` per call, now including `input_tokens_details.cached_tokens`. Cached shares of input tokens: 95% for Codex, 89–91% for in-process. Per-run numbers are in each run's `meta.json` (`usage.cost_usd_est`, `usage.cost_usd_upper`); per-episode lines are in `data/runs/staging-v1.3/spend_ledger.jsonl` (gitignored).
- **The dashboard validates the discounted basis.** Silas's OpenAI dashboard showed a total bill of **about $170 at ~11:20** for overnight plus this morning. That is below the summed discounted estimates (overnight ≈ $260 + this morning ≈ $45), so the cached-input pricing is right and, if anything, conservative.
- **Control.** `scripts/budget_runner.py` ran one episode per process, with Codex first. It stopped launching once spent + in-flight reserve + the next episode would exceed the cap. The cap was $90, lowered to $50 between 11:01 and 11:15 pending the dashboard check. Spend was held at 11:16 because the hard-tier result triggered v1.4.

---

# History (superseded by the official measurement above)

**Status 03:54 (HEAD-AGENTS).** v1.2 = complete official measurement (the "before" picture). v1.3 = the official tier, but **small-n**: runs stopped at the night's API spend cap ($150; see Spend). Gemini becomes a frontier family in the morning.

**Scoring (contract v0.3):** correct accusation = company value V at accusation; wrong = −1; no accusation = 0.

**Reference definition (agreed with ENV):**
- **v1.2 numbers** = all episodes played at commit **db104c9** (tiers v1.2), including the solver rows.
- **v1.3 numbers** = everything at commit **0933805**, SolverPolicy included (tiers v1.3, `KNOWN_V_MODE=True`).
- The v1.3 solver re-run on v1.2 worlds (hard .659, medium .723, matching ENV's earlier rows) is kept in `data/runs/committed/superseded/` and is never mixed into these tables.

**Reproduce (no keys):**
- `python -m canary.analysis.gap --runs data/runs/committed` → v1.2
- `python -m canary.analysis.gap --runs data/runs/committed/v1.3` → v1.3
- Tags: `python -m canary.analysis.tags --runs <same>`
- Accusation audit: `python -m canary.analysis.accuse --runs <same>`
- Per-tag value lost: ENV's `results/regret_*-v1.2.md`

## Headline (read the caveats first)
| tier version | medium: frontier / solver | hard: frontier / solver |
|---|---|---|
| **v1.2** (true V visible daily): gpt-5.5 in-process, **n=20+20** | 0.600 ± 0.175 / 0.690 ± 0.086 = **87%** | 0.500 ± 0.227 / 0.584 ± 0.194 = **86%** |
| **v1.3**: gpt-5.5 in-process, **SMALL n=9+5**, paired with the solver on the same seeds (ENV 1a650df) | 0.319 ± 0.497 / 0.670 = **48%** | −0.003 ± 0.799 / 0.553 = **≈0%** |
| **v1.3**: Codex gpt-5.5 over MCP (judges' harness shape), **n=1+2** | 0.53 | 0.59 |

> ⚠ **Do not quote the v1.3 in-process gap as the headline yet.** Three caveats:
> 1. **Small n:** 14 episodes, so the 95% CIs are ±0.5–0.8 V. We expect to tighten them in the morning (spend approval needed).
> 2. **Our in-process scaffold is handicapped** (see "Scaffold vs harness" below): it keeps only the last 40 turns (episodes are 70–150 tool calls) and cuts older tool results to 2,000 characters, so the agent loses its own early canary assignments and leak history. The judges' harness-shape runs (Codex over MCP, n=3: .53 / .59) are much closer to the reference.
> 3. **So the honest v1.3 claim tonight:** the reference is unchanged by v1.3 while frontier scores drop; the size of the gap needs the morning's judges'-shape measurement with a fixed scaffold.

The story so far:
- **v1.2:** frontier agents got close to the reference partly by reading the true company value V in `status` every day. Each leak showed up immediately as a 0.04 V drop, which defeated the leak-delay mechanic (Grok describes this in its own write-up).
- **v1.3:** shows only *known* V (from surfaced leaks).
- **Result:** the reference barely moves (medium .690→.717, hard .584→.592 on 20 seeds).

## Scaffold vs harness: is our in-process loop handicapped? (yes, likely)
| | `LLMPolicy` (in-process, `canary/agents/llm_policy.py`) | Codex CLI over MCP (`canary/agents/frontier/codex_run.py`) |
|---|---|---|
| Task text | Env `instruction()` + one generic line | **identical** (same builder, tested) + the MCP server's instructions |
| System prompt | the task text only | Codex's own agentic system prompt + the task text |
| API | Chat Completions; **reasoning is not carried across calls** | Responses API via Codex; reasoning kept across turns |
| Context | **last 40 assistant turns only; older tool results cut to 2,000 chars** | full history (Codex compacts only near the window limit) |
| Reasoning effort | API default (not set) | Codex default (not set) |
| Temperature | 0.0 requested, ignored for gpt-5.x | Codex default |
| Turn cap | none beyond the env's 300-call cap | none beyond the env's 300-call cap |

The context truncation is the likely handicap: in a 14-day episode the decisive evidence (which variant went to whom on days 1–5, which leaks surfaced when) falls out of the window right before the day-14 decision, which matches the observed day-14 coin flips. **Morning fix:** keep the full history (or a structured, non-lossy evidence summary: canary assignments, the surfaced leak feed, restrictions), use the Responses API with persisted reasoning, set the reasoning effort explicitly, and re-run in-process + Codex on the same seeds. An honest gap must come from the task, not from a weak scaffold.

## Fairness: the reference uses only public information
Under v1.3 every quantity the solver uses is public:
- the shown (known) V;
- the delay distribution, `p_leak`, the leak-selection and careful-mole rules, and the canary fingerprint accuracy (all in `instruction()`);
- the agent's own canary assignments, the leak feed, the access logs and the documents (all from tools).

Its accusation rule is computable from the instructions: accuse e iff P(e)·E[true V] − (1 − P(e)) > 0, otherwise keep gathering or abstain (score 0). Frontier agents can do this. Grok abstained on v1.2 hard 900000 at P≈0.53, explicitly computing the 1/(1+V) threshold, and gpt-5.5 reaches P=1.0 by day 6–7 on medium seeds where the canary evidence is decisive. The text-only content never names the mole (lint + text-only probe, ENV/INTEGRITY).

## v1.2: full table (db104c9, dev seeds 0–19)
| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |
|---|---|---|---|---|---|---|---|
| hard | codex:gpt-5.5 | 5 | -0.020 ± 0.784 | 0.60 | 12.6 | 0.02 | – |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| hard | grok | 5 | 0.567 ± 0.286 | 0.80 | 9.5 | – | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 11.6 | -0.56 | – |
| hard | openai:gpt-5.5 | 20 | 0.500 ± 0.227 | 0.90 | 11.8 | 0.62 | – |
| hard | opencode:openai/gpt-5.6-sol | 1 | 0.635 ± 0.000 | 1.00 | 14.0 | 0.84 | – |
| hard | random | 20 | -0.700 ± 0.206 | 0.00 | 6.6 | -0.87 | – |
| hard | restrict_all | 20 | -1.000 ± 0.000 | 0.00 | 8.0 | -1.36 | – |
| hard | solver | 20 | 0.584 ± 0.194 | 0.85 | 9.6 | 1.00 | – |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.0 | -1.21 | – |
| medium | codex:gpt-5.5 | 5 | 0.714 ± 0.106 | 1.00 | 7.4 | 1.11 | – |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| medium | grok | 5 | 0.672 ± 0.109 | 1.00 | 9.0 | – | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 11.1 | -0.26 | – |
| medium | openai:gpt-5.5 | 20 | 0.600 ± 0.175 | 0.95 | 8.8 | 0.85 | – |
| medium | opencode:openai/gpt-5.6-sol | 1 | 0.620 ± 0.000 | 1.00 | 11.0 | 0.77 | – |
| medium | random | 20 | -0.678 ± 0.225 | 0.05 | 6.5 | -0.94 | – |
| medium | restrict_all | 20 | -0.950 ± 0.098 | 0.05 | 7.0 | -1.36 | – |
| medium | solver | 20 | 0.690 ± 0.086 | 0.95 | 7.4 | 1.00 | – |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.0 | -1.42 | – |


Notes:
- **Grok** (an external Grok agent; 5+5 *judge* seeds 900000–4, over MCP; it read only `configs/README.md`): 9/9 correct + 1 deliberate abstention. Judge seeds use a per-process secret salt, so its episodes can't be replayed. The outcomes come from its ledger table, labelled "NOT replay-verified".
- **codex:gpt-5.5** (Codex CLI over MCP, the judges' harness shape; dev seeds 0–4 plus 1 smoke excluded):
  - medium 5/5 correct;
  - hard: 2 of 5 are **wrong accusations (−1)**, so the hard tier is high-variance even for the same model.
- **opencode:openai/gpt-5.6-sol:** only 2/10 episodes valid. OpenCode's ChatGPT workspace ran out of credits (HTTP 429); the 8 infra-invalid episodes are excluded (meta `valid:false`). The valid ones: medium 0.62 ✓, hard 0.635 ✓.
- `/ solver` is the per-seed ratio, defined only for agents run on the same seeds as the solver; it's blank for Grok, which ran on judge seeds.

## v1.3: table (0933805, dev seeds; gpt-5.5 stopped at the spend cap)
(These small-n 0933805 runs now sit in `data/runs/committed/superseded/`; `data/runs/committed/v1.3/gap_table.md` holds the full n=11/9/8 runs.)

| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |
|---|---|---|---|---|---|---|---|
| hard | codex:gpt-5.5 | 2 | 0.588 ± 0.132 | 1.00 | 12.5 | 0.83 | – |
| hard | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| hard | heuristic | 20 | -0.322 ± 0.374 | 0.40 | 11.6 | -0.61 | – |
| hard | openai:gpt-5.5 | 5 | -0.003 ± 0.799 | 0.60 | 13.0 | -0.20 | – |
| hard | random | 20 | -0.700 ± 0.206 | 0.00 | 6.6 | -1.02 | – |
| hard | restrict_all | 20 | -1.000 ± 0.000 | 0.00 | 8.0 | -1.45 | – |
| hard | solver | 20 | 0.592 ± 0.114 | 0.85 | 10.8 | 1.00 | – |
| hard | stop_early | 20 | -0.900 ± 0.196 | 0.05 | 1.0 | -1.26 | – |
| medium | codex:gpt-5.5 | 1 | 0.530 ± 0.000 | 1.00 | 14.0 | 0.72 | – |
| medium | do_nothing | 20 | 0.000 ± 0.000 | 0.00 | – | 0.00 | – |
| medium | heuristic | 20 | -0.116 ± 0.361 | 0.55 | 11.1 | -0.24 | – |
| medium | openai:gpt-5.5 | 9 | 0.319 ± 0.497 | 0.78 | 9.9 | 0.22 | – |
| medium | random | 20 | -0.678 ± 0.225 | 0.05 | 6.5 | -1.02 | – |
| medium | restrict_all | 20 | -0.950 ± 0.098 | 0.05 | 7.0 | -1.38 | – |
| medium | solver | 20 | 0.717 ± 0.052 | 1.00 | 7.5 | 1.00 | – |
| medium | stop_early | 20 | -1.000 ± 0.000 | 0.00 | 1.0 | -1.45 | – |

The gpt-5.5 v1.3 rows are an **incomplete** sample (seeds as reached by 8 parallel workers before the cap: medium 0,1,5,10,11,12,15,16,17; hard 0,1,5,10,15). The references cover all 20+20 seeds.

## Why gpt-5.5 loses value: gambling at the horizon
**Accusation audit (v1.3, gpt-5.5):** at each accusation we replay the solver's exact posterior P(accused is the mole | everything the agent had seen).
- 9 of 14 accusations are *justified* (P ≥ 0.6). gpt-5.5 is excellent when the canary evidence is decisive (medium seeds 0, 10, 12, 16: day 6–7, P=1.0).
- **All 4 wrong accusations are day-14 gambles**: P(accused) = 0.18, 0.43 (hard), 0.35, 0.32 (medium). (ENV 1a650df, hard: `premature_accusation` in 2 episodes = 1.22 V lost, mean P at accusation .61.) Caveat: the in-process scaffold's context truncation may cause part of this, see "Scaffold vs harness". One more correct day-14 accusation was *lucky* (P=0.56).
- Under −1 scoring a gamble at P < 1/(1+V) has negative expected value; abstaining (score 0) beats it. gpt-5.5 never abstained. Grok did (hard 900000, P≈0.53, explicitly computing the threshold), which shows the information to decide well is available.
- Hard seed 15 is the starkest: the solver's top suspect had P=0.78, but gpt-5.5 accused a different employee with P=0.18.

**Failure tags (value lost in V; `canary.analysis.tags`, ENV's `regret_report.py`):**

| run | `premature_accusation` | `ignored_delay` | `uninformative_canary` | `budget_waste` |
|---|---|---|---|---|
| v1.3 gpt-5.5 (n=14) | **36% of episodes, 2.36 V lost** | – | 29%, 0.09 V | 71%, 0 V |
| v1.2 gpt-5.5 hard (n=20, ENV) | **5 episodes, 2.12 V** (mean P at accusation .78 vs the solver's .96) | 1 episode, 0.82 V | 18 instances, 0.15 V | 44 instances, 0 V |
| v1.2 gpt-5.5 medium (n=20, ENV) | 1 episode, 0.79 V | (same episode) | 4 instances, 0.04 V | – |
| solver (v1.3, n=40) | 3%, 0 V | – | – | – |

**Premature accusation dominates (>90% of value lost);** canary design is a small secondary cost. ENV's costliest single decisions (v1.2 hard) are all day-14 accusations at low P: seed 15 (0.815 V), seed 8 (0.801 V), seed 16 (0.30 V).

## Annotated trajectory: medium seed 5 (v1-tiers dev run, gpt-5.5, score −1.0)
| day | action | solver belief P(top) | note |
|---|---|---|---|
| 1 | canary to 3 people, **one variant** | 0.05 | a single label splits nobody: zero information |
| 2–5 | 2-variant canaries of 6–10 people; two leaks surface | 0.05 → 0.26 | reasonable bisection |
| 5–9 | **~14 interviews** | 0.26 → 0.27 | interviews are weak (documented LR 1.3); 14 action slots buy ~nothing |
| 6–10 | 1-vs-1 / 2-vs-2 canaries | ≈0.27 | no leak lands |
| 11 | narrowed to **e02 vs e14** | 0.51 | |
| 12–13 | e02/e14 canaries again | 0.51 | with delay 1–3, a canary planted on day 12–13 likely can't surface before day 14 |
| 14 | 4 repeated interviews (`budget_waste`) → **accuse e02** at P=0.50 | 0.50 | **wrong → −1.0**. Tags: `premature_accusation`, `ignored_delay`; 0.18 V regret on the last step |

Better play: the same 2-way split on days 9–10 (inside the delay window) resolves e02 vs e14 in time, and at P=0.50 abstaining (0) beats a −1 coin flip.

## Kill-switch history: what moved the gap at each version
| version | gpt-5.5 / solver (medium, hard) | what we found | what changed |
|---|---|---|---|
| **v0** | 97%, 111% (n=3+3) | every accusation justified at P=1.0: the evidence was too crisp | tiers v1: delay 1–3, careful mole, framing, a weaker log signal |
| **v1** | 14%, **113%** (n=3+4, pre-fix solver) | the solver's canaries covered about 20 of 30 staff, and the careful mole leaks a canary with weight (1 − share), so they rarely leaked; gpt-5.5 used small groups that did | a careful-mole-aware solver; v1.1 timing fix |
| **v1.2** | 87%, 86% (n=20+20); Grok 97%, 97% | true V shown daily → each leak visible the same day, so the delay is moot | **v1.3: known-V only** (unsurfaced damage hidden; true V used only for scoring, stated in the instructions) |
| **v1.3** | 48%, ≈0% in-process (n=9+5, scaffold caveat); Codex over MCP n=3: .53 / .59 | gpt-5.5 gambles at the horizon (P .18–.43) instead of abstaining | morning: fix the scaffold, measure in the judges' shape, Gemini family |

Each fix was a change to the *information or mechanics* (stated in the instructions), never a hidden trick, and the solver's own score stayed in .58–.72 throughout.

## Mole Forge: honest status
- The pipeline works and is solver-constrained (CONTRACT §7). FR8's J5 ran 500 generations; the hall of fame is one distinct behaviour by outcome, feasible on v1.2 hard (solver acc .855).
- **The evolved moles don't beat gpt-5.5:** 7/7 correct on paired seeds, mean 0.76 vs 0.73 on the default mole. They were evolved against the heuristic only.
- J5b (fitness = regret against the *strongest* investigator, with a Bayesian canary-bisection investigator) is running on v1.3.
- Morning: the Gemini mutator and gpt-5.5/Gemini spot checks.
- **J5b result (FR8, data/forge/hall_of_fame_v1.3.jsonl, justSilas 932d2fc):** 300 generations, fitness = regret against the strongest of {Heuristic, HintedHeuristic}, tiers v1.3. On FRESH hard seeds 6000–6199 (n=200):
  - **regret against the strongest investigator .470 ± .079 vs the default mole's .326** (+44%), and .716 vs the heuristic;
  - all entries pass §7 (solver .639 ± .065, acc .89 vs the default mole's .548 / .855);
  - the 20 entries are **one distinct mole by outcome** (identical leak/frame traces; the HOF files now hold 1 entry each, v1.2 likewise);
  - overfitting: in-run fitness .735 on seeds 0–39 vs .47 fresh, so the next run (J5c) needs ≥100 or rotating fitness seeds **and an outcome-diversity term** (dedupe by event-trace hash inside the population); otherwise the mutator converges to one behaviour with cosmetic JSON variants.
- What this shows: the Forge finds moles that are harder for a *competent canary investigator* and still solver-catchable. What it doesn't show yet: that they're harder for gpt-5.5 (that's the morning spot check, ≈$15 for top-2 × 5 seeds; the J5 moles were NOT harder for gpt-5.5, 7/7 correct).
- **No claim that Forge moles are harder for frontier agents until that check passes.**

## Infra-invalid episodes (excluded from all means)
- **OpenCode gpt-5.6-sol:** 8/10 invalid. 5 hit the ChatGPT-workspace quota (429); 2 had their MCP server SIGTERMed by an external eval client's `pkill -f canary.mcp_server` (since finished); 1 hit an OpenCode local DB lock.
- **gpt-5.5 v1.3:** not invalid, just incomplete (spend cap).

## Spend (OpenAI API, Silas's key)
| item | cost |
|---|---|
| v1.2 official gpt-5.5 20+20 | $121.46 |
| v1 directional runs | $24.38 |
| v1.3 gpt-5.5 (14 episodes) | ≈$42.6 (est. at $3.04/episode) |
| Forge gpt-5.5 HOF validation | ≈$22.4 |
| Codex CLI (API-key mode) | ≈$24 est. (upper bound $143 if cached input isn't discounted) |
| killed old-tier runs, smoke runs | ≈$25 (unlogged) + $3 |
| **total** | **≈ $260 est.** |

That's above the $150 cap the CEO set at 03:30. All API-billed runs have stopped; more needs Silas's approval.
