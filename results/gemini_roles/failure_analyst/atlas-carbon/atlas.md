# Canary Lab Failure Atlas (gemini-4-carbon, source=llm)

Across 101 Canary Lab episodes (total solver regret 20.3903), agent failures cluster around stopping-time miscalibration and suboptimal experiment design. Stopping errors account for 61.1% of total regret: agents frequently commit premature accusations below P=0.60 using noisy framing logs (39.4% regret share), settle for moderate-posterior accusations when another canary split carries higher continuation value (13.8%), or misinterpret unsurfaced 1-to-3 day pipeline leaks as exoneration (7.9%). On the information-gathering side, narrow 2-to-3 recipient or lopsided canaries lag optimal Gini partitions across 71 episodes (27.8% regret share), leaving finalists unresolved near day 14, while aggressive access restrictions (10.7%) burn company value and block suspects from receiving diagnostic traps. Late commits after certainty (0.4%) represent a minor residual leak cost.

## Provenance and Verification Summary

| Metric | Value |
|---|---|
| Generated At | `2026-11-14T13:59:28+00:00` |
| Git SHA | `26ab62d` |
| Model | `gemini-4-carbon` |
| Source | `llm` (synthetic=`False`) |
| Ledger Run IDs | `atlas-carbon-v1` |
| Corpus Episodes | `101` (`8` invalid skipped) |
| Corpus Input / Cached Tokens | `596,862` input / `0` cached (`298,506` per corpus pack) |
| Output / Thinking Tokens | `3,191` output / `13,356` thinking (`2` calls, `$1.3592`) |
| Total Solver Regret | `20.3903 V` |
| Verbatim Quote Verification | `17 / 17` (`100.0%`) |
| Solver-vs-LLM Stratified Agreement | `28 / 30` (`93.3%`) |

## Accusation Posteriors and Corpus Breakdown

Across `100` accusations (`1` horizon abstentions), mean Bayesian posterior `P(accused)` is `0.8456` overall (`0.8899` on correct accusations vs `0.3979` on wrong accusations), with `19` accusations below the rational EV threshold `-wrong / (V - wrong)` and `19` below `0.60`.

| Tiers | Agent | Tier | Episodes | Mean Score | Accuracy | Mean P(accused) | Total Regret (V) |
|---|---|---|---:|---:|---:|---:|---:|
| `v1.2` | `codex:gpt-5.5` | `hard` | 5 | -0.020 | 60% | 0.7050 | 1.3989 |
| `v1.2` | `codex:gpt-5.5` | `medium` | 5 | +0.714 | 100% | 1.0000 | 0.5331 |
| `v1.2` | `grok` | `hard` | 5 | +0.567 | 80% | 0.9945 | 1.0198 |
| `v1.2` | `grok` | `medium` | 5 | +0.672 | 100% | 0.9734 | 0.7071 |
| `v1.2` | `openai:gpt-5.5` | `hard` | 20 | +0.500 | 90% | 0.7837 | 4.0330 |
| `v1.2` | `openai:gpt-5.5` | `medium` | 20 | +0.600 | 95% | 0.9482 | 2.4294 |
| `v1.2` | `opencode:openai/gpt-5.6-sol` | `hard` | 1 | +0.635 | 100% | 0.6919 | 0.0585 |
| `v1.2` | `opencode:openai/gpt-5.6-sol` | `medium` | 1 | +0.620 | 100% | 0.7219 | 0.6996 |
| `v1.3` | `codex:gpt-5.5` | `hard` | 11 | +0.654 | 100% | 0.8181 | 2.4775 |
| `v1.3` | `codex:gpt-5.5` | `medium` | 11 | +0.401 | 82% | 0.7191 | 3.9818 |
| `v1.3` | `openai:gpt-5.5` | `hard` | 8 | +0.264 | 75% | 0.7473 | 1.7794 |
| `v1.3` | `openai:gpt-5.5` | `medium` | 9 | +0.668 | 100% | 0.9173 | 1.2721 |

## Failure Modes Ranked by Deterministic Solver Regret Share

| Rank | Mode ID | Name | Decision | Regret Share | Total Regret (V) | Episodes | Verified Quotes |
|---:|---|---|---|---:|---:|---:|---:|
| 1 | `premature-accusation` | Premature Accusation on Noisy Framing Evidence | `accuse` | 39.41% | 8.0359 | 17 | 3/3 |
| 2 | `uninformative-canary` | Narrow or Lopsided Canary Partitions | `plant_canary` | 27.79% | 5.6662 | 71 | 3/3 |
| 3 | `subthreshold-commit` | Subthreshold Accusation Before Optimal Split | `accuse` | 13.82% | 2.8175 | 24 | 3/3 |
| 4 | `over-restriction` | Over-Restriction Starving Diagnostic Traps | `restrict_access` | 10.73% | 2.1883 | 19 | 3/3 |
| 5 | `ignored-delay` | Ignoring Leak-Feed Delay Pipeline | `accuse` | 7.85% | 1.6010 | 2 | 2/2 |
| 6 | `late-commit` | Delayed Accusation and Horizon Expiration | `advance_day` | 0.40% | 0.0814 | 5 | 3/3 |

### 1. Premature Accusation on Noisy Framing Evidence (`premature-accusation`)

- Decision: `accuse` | Regret Share: `39.41%` (`8.0359 V`) | Affected Episodes: `17`

Agents call accuse with Bayesian posterior P(accused) < 0.60 (17 episodes, 8.0359 regret, 39.4% share; wrong accusations average P=0.3979). When canary variants fail to surface or leave a multi-person pool at the horizon, agents over-weight framed after-hours access logs and evasive interviews instead of waiting for diagnostic splits, risking a -1.0 penalty.

Verbatim verified quotes:

> `codex:gpt-5.5/medium/0#73` (step `52`, verified=`True`): `transcript t=52: Waiting mainly risks more hidden leak damage while giving low odds of a cleaner canary hit.`
> `codex:gpt-5.5/hard/1#1` (step `84`, verified=`True`): `transcript t=84: The single sharpest clue is that the leaked canary `c4` was label A, and inside that A group `e06` is the one with an after-hours access to `c4` on the very day it leaked.`
> `codex:gpt-5.5/hard/8#70` (step `59`, verified=`True`): `transcript t=59: At this point, the ordinary feed has gone quiet, so the best live signal is the accumulated log imbalance.`

### 2. Narrow or Lopsided Canary Partitions (`uninformative-canary`)

- Decision: `plant_canary` | Regret Share: `27.79%` (`5.6662 V`) | Affected Episodes: `71`

Agents plant 2-to-3 employee micro-sweeps, lopsided 1-vs-many splits, or redundant post-lock traps whose Gini information gain lags the Bayesian reference partition (71 episodes, 5.6662 regret, 27.8% share). Tiny early batches often miss the true mole entirely, leaving multiple suspects indistinguishable late in the 14-day horizon.

Verbatim verified quotes:

> `codex:gpt-5.5/medium/5#78` (step `14`, verified=`True`): `transcript t=14: I've started exact-label canaries across small batches; if one surfaces, it will directly name one of those batch members rather than just a department pair.`
> `codex:gpt-5.5/hard/0#0` (step `36`, verified=`True`): `regret t=36 d5 plant_canary r=0.0251 p_best=0.1746 tags=['uninformative_canary']`
> `openai:gpt-5.5/hard/4#14` (step `9`, verified=`True`): `t=9 d1 plant_canary(title='Canary D1 pair e00 e01',assignment={A:[e00], B:[e01]}) -> ok [p_best=0.033]`

### 3. Subthreshold Accusation Before Optimal Split (`subthreshold-commit`)

- Decision: `accuse` | Regret Share: `13.82%` (`2.8175 V`) | Affected Episodes: `24`

Agents accuse at moderate confidence (0.60 <= P(accused) < p*) when planting or awaiting one more canary split yields higher continuation expected value than immediate termination (24 episodes, 2.8175 regret, 13.8% share). Under 5% fingerprint noise or indirect timing inference, stopping above the static myopic threshold still forfeits positive option value.

Verbatim verified quotes:

> `opencode:openai/gpt-5.6-sol/medium/2#61` (step `78`, verified=`True`): `transcript t=78: Isolation produced three consecutive no-leak days after `e09`'s eligible documents expired, while unrestricted `e16` continuously received fresh documents.`
> `codex:gpt-5.5/hard/2#2` (step `124`, verified=`True`): `transcript t=124: That pushes e19 over the accusation threshold at the current company value.`
> `codex:gpt-5.5/hard/0#0` (step `84`, verified=`True`): `transcript t=84: Their intersection is `e05`; allowing for the 5% fingerprint error, `e05` is now far above the accusation threshold.`

### 4. Over-Restriction Starving Diagnostic Traps (`over-restriction`)

- Decision: `restrict_access` | Regret Share: `10.73%` (`2.1883 V`) | Affected Episodes: `19`

Agents invoke restrict_access across multiple low-posterior suspects or top finalists simultaneously (19 episodes, 2.1883 regret, 10.7% share). Beyond paying direct daily restriction costs, blanket lockouts starve restricted suspects of new ordinary and canary documents, destroying future separating signal.

Verbatim verified quotes:

> `codex:gpt-5.5/hard/4#66` (step `38`, verified=`True`): `transcript t=38: I'm also going to restrict those three after the canary is delivered; that preserves today's trap while limiting fresh documents to the strongest suspects.`
> `grok/hard/900001#51` (step `38`, verified=`True`): `regret t=38 d5 restrict_access r=0.0849 p_best=0.2921 tags=['over_restriction']`
> `grok/hard/900004#54` (step `40`, verified=`True`): `regret t=40 d6 restrict_access r=0.0752 p_best=0.6646 tags=['over_restriction']`

### 5. Ignoring Leak-Feed Delay Pipeline (`ignored-delay`)

- Decision: `accuse` | Regret Share: `7.85%` (`1.6010 V`) | Affected Episodes: `2`

Agents accuse with low posterior while recently planted decisive canaries remain in the 1-to-3 day leak-surfacing pipeline (2 episodes, 1.6010 regret, 7.9% share). Treating the absence of an immediate feed item as exoneration of canary recipients causes severe misattribution to the wrong finalist.

Verbatim verified quotes:

> `openai:gpt-5.5/hard/15#20` (step `106`, verified=`True`): `regret t=106 d14 accuse r=0.8147 p_accused=0.1133 p_best=0.5352 tags=['premature_accusation', 'ignored_delay']`
> `openai:gpt-5.5/medium/17#42` (step `96`, verified=`True`): `regret t=96 d14 accuse r=0.7863 p_accused=0.1370 p_best=0.1773 tags=['premature_accusation', 'ignored_delay']`

### 6. Delayed Accusation and Horizon Expiration (`late-commit`)

- Decision: `advance_day` | Regret Share: `0.40%` (`0.0814 V`) | Affected Episodes: `5`

Agents call advance_day after the Bayesian posterior has already reached certainty or exceeded optimal immediate accusation EV, or let day 14 expire without accusing (5 episodes, 0.0814 regret, 0.4% share). Waiting for redundant direct canary hits when restriction or elimination already locked P=1.0000 needlessly bleeds company value V.

Verbatim verified quotes:

> `codex:gpt-5.5/medium/7#80` (step `54`, verified=`True`): `regret t=54 d7 advance_day r=0.0152 p_best=1.0000 tags=[]`
> `openai:gpt-5.5/medium/1#93` (step `88`, verified=`True`): `regret t=88 d9 advance_day r=0.0142 p_best=1.0000 tags=[]`
> `grok/hard/900000#50` (step `91`, verified=`True`): `regret t=91 d14 (no accusation) r=0.0000 p_best=0.3784 tags=['no_accusation']`

## Stratified Solver-vs-LLM Agreement Audit (n=30)

Episodes are sampled deterministically in round-robin order across `(tier, outcome_stratum)` buckets and evaluated by comparing the deterministic primary regret mode from `canary.solver.regret.attribute` against independent `gemini-4-carbon` episode classifications: `28 / 30` (`93.3%`) exact mode agreement.

| Episode | Tier | Outcome | Regret (V) | Solver Mode | Gemini Mode | Agree |
|---|---|---|---:|---|---|---|
| `codex:gpt-5.5/hard/8#70` | `hard` | `correct_high_regret` | 1.0405 | `premature-accusation` | `premature-accusation` | `yes` |
| `openai:gpt-5.5/hard/12#17` | `hard` | `correct_low_regret` | 0.1786 | `uninformative-canary` | `premature-accusation` | `no` |
| `grok/hard/900000#50` | `hard` | `horizon_no_accusation` | 0.2363 | `late-commit` | `late-commit` | `yes` |
| `openai:gpt-5.5/hard/15#20` | `hard` | `wrong_accusation` | 0.8798 | `ignored-delay` | `ignored-delay` | `yes` |
| `codex:gpt-5.5/medium/7#80` | `medium` | `correct_high_regret` | 0.9031 | `premature-accusation` | `premature-accusation` | `yes` |
| `grok/medium/900001#56` | `medium` | `correct_low_regret` | 0.1720 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `codex:gpt-5.5/medium/0#73` | `medium` | `wrong_accusation` | 1.4089 | `premature-accusation` | `premature-accusation` | `yes` |
| `openai:gpt-5.5/hard/2#86` | `hard` | `correct_high_regret` | 0.9715 | `premature-accusation` | `premature-accusation` | `yes` |
| `codex:gpt-5.5/hard/3#3` | `hard` | `correct_low_regret` | 0.1577 | `uninformative-canary` | `premature-accusation` | `no` |
| `codex:gpt-5.5/hard/1#1` | `hard` | `wrong_accusation` | 0.7197 | `premature-accusation` | `premature-accusation` | `yes` |
| `opencode:openai/gpt-5.6-sol/medium/2#61` | `medium` | `correct_high_regret` | 0.6996 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `grok/medium/900004#59` | `medium` | `correct_low_regret` | 0.1717 | `uninformative-canary` | `uninformative-canary` | `yes` |
| `openai:gpt-5.5/medium/17#42` | `medium` | `wrong_accusation` | 0.9592 | `ignored-delay` | `ignored-delay` | `yes` |
| `openai:gpt-5.5/hard/8#28` | `hard` | `correct_high_regret` | 0.8738 | `premature-accusation` | `premature-accusation` | `yes` |
| `openai:gpt-5.5/hard/13#18` | `hard` | `correct_low_regret` | 0.1574 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `openai:gpt-5.5/hard/4#88` | `hard` | `wrong_accusation` | 0.2828 | `premature-accusation` | `premature-accusation` | `yes` |
| `openai:gpt-5.5/medium/6#98` | `medium` | `correct_high_regret` | 0.5923 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `grok/medium/900000#55` | `medium` | `correct_low_regret` | 0.1657 | `over-restriction` | `over-restriction` | `yes` |
| `codex:gpt-5.5/medium/4#77` | `medium` | `wrong_accusation` | 0.6305 | `premature-accusation` | `premature-accusation` | `yes` |
| `codex:gpt-5.5/hard/4#66` | `hard` | `correct_high_regret` | 0.4653 | `over-restriction` | `over-restriction` | `yes` |
| `openai:gpt-5.5/hard/1#11` | `hard` | `correct_low_regret` | 0.1520 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `codex:gpt-5.5/hard/0#0` | `hard` | `wrong_accusation` | 0.2048 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `codex:gpt-5.5/medium/5#78` | `medium` | `correct_high_regret` | 0.4603 | `premature-accusation` | `premature-accusation` | `yes` |
| `grok/medium/900003#58` | `medium` | `correct_low_regret` | 0.1603 | `over-restriction` | `over-restriction` | `yes` |
| `codex:gpt-5.5/hard/3#65` | `hard` | `correct_high_regret` | 0.4206 | `premature-accusation` | `premature-accusation` | `yes` |
| `openai:gpt-5.5/hard/19#24` | `hard` | `correct_low_regret` | 0.1324 | `subthreshold-commit` | `subthreshold-commit` | `yes` |
| `openai:gpt-5.5/hard/4#14` | `hard` | `wrong_accusation` | 0.1447 | `uninformative-canary` | `uninformative-canary` | `yes` |
| `openai:gpt-5.5/medium/4#96` | `medium` | `correct_high_regret` | 0.3664 | `premature-accusation` | `premature-accusation` | `yes` |
| `codex:gpt-5.5/medium/2#75` | `medium` | `correct_low_regret` | 0.1271 | `uninformative-canary` | `uninformative-canary` | `yes` |
| `grok/hard/900001#51` | `hard` | `correct_high_regret` | 0.3927 | `over-restriction` | `over-restriction` | `yes` |
