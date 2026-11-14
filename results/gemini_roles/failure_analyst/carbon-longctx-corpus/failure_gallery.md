# Frontier Failure Gallery (gemini-4-carbon, source=llm)

Long-context failure analysis over all committed frontier episodes in `data/runs/committed/` (`codex:gpt-5.5`, `openai:gpt-5.5`, `grok`, `opencode:openai/gpt-5.6-sol` across `v1.2` and `v1.3`, excluding `superseded/` and `reference/`), paired with deterministic Bayesian solver regret attribution (`canary.solver.regret.attribute` under the matching tier version via `canary.rules.tiers_version`).

## Run Provenance & Verification Summary

| Field | Value |
|---|---|
| Role | `failure_analyst` |
| Model ID | `gemini-4-carbon` |
| Analysis Source | `llm` |
| Commit | `71a425530574aecd282e53a13f022be25fe4f292` |
| Episodes Packed | `101` (`8` infra-invalid skipped) |
| Packed Corpus Chars | `261,087` |
| Prompt / Output Tokens | `237,763` in / `16,390` out (cost `$0.6394`) |
| Verbatim Quote Verification | `100.0%` (`16/16` quotes verified in code) |

## Corpus & Deterministic Solver Regret Breakdown

| Tiers | Agent | Tier | Episodes | Mean Score | Accuracy | Total Solver Regret (V) |
|---|---|---|---:|---:|---:|---:|
| `v1.2` | `codex:gpt-5.5` | `hard` | 5 | -0.020 | 60% | 1.399 |
| `v1.2` | `codex:gpt-5.5` | `medium` | 5 | +0.714 | 100% | 0.533 |
| `v1.2` | `grok` | `hard` | 5 | +0.567 | 80% | 1.020 |
| `v1.2` | `grok` | `medium` | 5 | +0.672 | 100% | 0.707 |
| `v1.2` | `openai:gpt-5.5` | `hard` | 20 | +0.500 | 90% | 4.033 |
| `v1.2` | `openai:gpt-5.5` | `medium` | 20 | +0.600 | 95% | 2.429 |
| `v1.2` | `opencode:openai/gpt-5.6-sol` | `hard` | 1 | +0.635 | 100% | 0.059 |
| `v1.2` | `opencode:openai/gpt-5.6-sol` | `medium` | 1 | +0.620 | 100% | 0.700 |
| `v1.3` | `codex:gpt-5.5` | `hard` | 11 | +0.654 | 100% | 2.478 |
| `v1.3` | `codex:gpt-5.5` | `medium` | 11 | +0.401 | 82% | 3.982 |
| `v1.3` | `openai:gpt-5.5` | `hard` | 8 | +0.264 | 75% | 1.779 |
| `v1.3` | `openai:gpt-5.5` | `medium` | 9 | +0.668 | 100% | 1.272 |

### Solver Regret Tags Across Corpus

| Regret Tag | Episodes Affected | Decision Instances | Total Regret Lost (V) |
|---|---:|---:|---:|
| `premature_accusation` | 19/101 (18.8%) | 19 | 9.6369 |
| `ignored_delay` | 2/101 (2.0%) | 2 | 1.6010 |
| `uninformative_canary` | 30/101 (29.7%) | 51 | 0.5520 |
| `over_restriction` | 3/101 (3.0%) | 5 | 0.3681 |
| `budget_waste` | 45/101 (44.6%) | 106 | 0.0000 |
| `no_accusation` | 1/101 (1.0%) | 1 | 0.0000 |

## Clustered Failure Modes (gemini-4-carbon)

Across 101 mole-hunting episodes (91 correct, 9 wrong accusations, 1 horizon timeout), failures cluster into six concrete decision modes. Action budget waste is most frequent (45 episodes): repetitive sentiment searches, redundant status checks, and per-employee log queries hit daily limits and crowd out key tools. Uninformative canary design (30 episodes) wastes days on tiny 2-to-3 suspect pairs, single-variant assignments, or duplicate splits. Premature accusation drives the largest regret (19 episodes, 9.64 regret), as agents guess among unresolved candidates, compounded when they ignore leak propagation delays at day 14 (2 episodes). Minor modes include over-restricting suspects (3 episodes), which suppresses canary signals, and letting the day-14 horizon expire without accusing (1 episode).

### 1. Action Budget Waste and Daily Limit Overruns (45 episodes)

The investigator burns daily action quotas on broad keyword fishing in search_messages, repeated status or list_employees calls, and individual read_access_logs queries instead of batching. Consequently, calls to plant_canary, read_message, or check_leak_feed fail with daily limit errors, delaying suspect elimination by whole days.

Verified verbatim quotes from packed corpus blocks:

> `codex:gpt-5.5/hard/2#2`: `d2 search_messages(query=bonus,day_from=1,day_to=14) -> ERR daily action limit; call advance_day`
> `openai:gpt-5.5/medium/1#31`: `d1 plant_canary(doc_title=Q1 Strategic Review Draft A,assignment={'e00': 'e00', 'e01': 'e01', 'e02': 'e02'}) -> ERR daily action limit; call advance_day`
> `codex:gpt-5.5/medium/3#76`: `d1 read_access_logs(day_from=1,day_to=1,employee=e04) -> ERR daily action limit; call advance_day`

### 2. Uninformative or Narrow Canary Assignments (30 episodes)

Instead of partitioning the active suspect pool evenly across watermark variants, the agent plants canaries on only 2 or 3 employees at a time, assigns identical watermarks to an entire cohort, or repeats a previous split. These low-entropy canaries fail to halve the candidate set, leaving multiple suspects indistinguishable late in the investigation.

Verified verbatim quotes from packed corpus blocks:

> `codex:gpt-5.5/hard/0#0`: `regret t=36 plant_canary r=0.025 ['uninformative_canary']`
> `openai:gpt-5.5/hard/4#14`: `d1 plant_canary(doc_title=Canary D1 pair e00 e01,assignment={'e00': 'A', 'e01': 'B'}) -> ok`
> `openai:gpt-5.5/medium/11#36`: `regret t=42 plant_canary r=0.038 ['uninformative_canary']`

### 3. Premature Accusation Under Candidate Ambiguity (19 episodes)

The agent calls accuse before canary leaks or access logs uniquely isolate the mole, either rushing an early guess or running out of days after slow elimination and picking among remaining finalists on day 14. This mode accounts for the highest cumulative solver regret (9.64) and directly causes most wrong accusations.

Verified verbatim quotes from packed corpus blocks:

> `codex:gpt-5.5/medium/0#73`: `regret t=52 accuse r=1.390 ['premature_accusation']`
> `codex:gpt-5.5/hard/1#1`: `regret t=84 accuse r=0.666 ['premature_accusation']`
> `codex:gpt-5.5/medium/4#77`: `regret t=89 accuse r=0.485 ['premature_accusation']`

### 4. Over-Restriction of Suspect Access (3 episodes)

The investigator invokes restrict_access across multiple unconfirmed suspects simultaneously (often 2 to 4 employees in one day). Blocking access prematurely incurs direct penalties and prevents the true mole from reading newly planted canary documents, cutting off the diagnostic leak signal needed for confirmation.

Verified verbatim quotes from packed corpus blocks:

> `grok/hard/900001#51`: `regret t=38 restrict_access r=0.085 ['over_restriction']`
> `grok/hard/900004#54`: `regret t=40 restrict_access r=0.075 ['over_restriction']`
> `grok/medium/900000#55`: `regret t=56 restrict_access r=0.050 ['over_restriction']`

### 5. Ignored Leak Propagation Delay at Accusation (2 episodes)

After spending early days on 3-person or single-variant canaries, the agent plants late targeted canaries and treats the absence of an immediate leak as exoneration without accounting for multi-day leak delay. Forced to decide on day 14, it misinterprets pending leaks and accuses the wrong employee in both episodes.

Verified verbatim quotes from packed corpus blocks:

> `openai:gpt-5.5/hard/15#20`: `regret t=106 accuse r=0.815 ['premature_accusation', 'ignored_delay']`
> `openai:gpt-5.5/medium/17#42`: `regret t=96 accuse r=0.786 ['premature_accusation', 'ignored_delay']`

### 6. Horizon Expiration Without Accusation (1 episodes)

In episode grok/hard/900000#50, the agent tests only 2 employees per day with uninformative canaries, restricts three suspects mid-run, and calls status every day without ever invoking accuse. It reaches the day-14 horizon with accused=None, forfeiting any chance of a positive score.

Verified verbatim quotes from packed corpus blocks:

> `grok/hard/900000#50`: `### grok/hard/900000#50 score=0.000 correct=False accused=None day=14 end=horizon`
> `grok/hard/900000#50`: `d1 plant_canary(doc_title=Lab partnership terms,assignment={'e04': 'A', 'e07': 'B'}) -> ok`

## Annotated Trajectory Comparisons per Top Failure Mode

Each table below replays the Bayesian reference solver (`SolverPolicy`) step-by-step on the public observations seen by the agent up to that exact decision under the matching tier rules (`v1.2` or `v1.3`), comparing the agent's action against `P(mole)` and the solver's counterfactual best action.

### Mode 1: Action Budget Waste and Daily Limit Overruns

Episode `codex:gpt-5.5/hard/2#2` (`v1.2`, score `+0.600`, correct=`True`, accused=`e19`, true mole=`e19`, end=`accused` on day `13`, total solver regret `0.259 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=6) | `plant_canary(15 staff, {A:[e00..e07(8)], B:[e08..e14(7)]}, gini=0.62)` | P(mole=e19)=0.033, P(top=e00)=0.033 | `plant_canary({A:[e02..e14(6)], B:[e06..e26(6)]}) [gini=0.56, Q_cont=+0.725]` | `0.000` (-) |
| d2 (t=21) | `search_messages(query='bonus') -> ERR daily action limit; call advance_day` | P(mole=e19)=0.027, P(top=e01)=0.056 | `advance_day() [wait leak delay: Q_cont=+0.688 vs E[accuse e01]=-0.892]` | `0.000` (budget_waste) |
| d5 (t=46) | `plant_canary(10 staff, {A:[e03..e19(4)], B:[e04..e28(6)]}, gini=0.48)` | P(mole=e19)=0.100, P(top=e07)=0.179 | `plant_canary({A:[e07,e16,e28], B:[e03,e04,e15]}) [gini=0.66, Q_cont=+0.676]` | `0.008` (-) |
| d7 (t=67) | `plant_canary(7 staff, {A:[e08], B:[e04..e24(6)]}, gini=0.21)` | P(mole=e19)=0.155, P(top=e16)=0.165 | `plant_canary({A:[e16,e19], B:[e07,e24]}) [gini=0.66, Q_cont=+0.639]` | `0.021` (-) |
| d8 (t=83) | `interview(employee=e04, topic=workload) -> ERR daily action limit; call advance_day` | P(mole=e19)=0.168, P(top=e19)=0.168 | `advance_day() [wait leak delay: Q_cont=+0.585 vs E[accuse e19]=-0.706]` | `0.000` (budget_waste) |
| d9 (t=88) | `plant_canary(7 staff, {A:[e08,e16,e24], B:[e04..e19(4)]}, gini=0.48)` | P(mole=e19)=0.187, P(top=e19)=0.187 | `plant_canary({A:[e19,e24], B:[e07,e16]}) [gini=0.66, Q_cont=+0.552]` | `0.008` (-) |
| d9 (t=94) | `interview(employee=e19, topic=access_needs) -> ERR daily action limit; call advance_day` | P(mole=e19)=0.190, P(top=e19)=0.190 | `advance_day() [wait leak delay: Q_cont=+0.542 vs E[accuse e19]=-0.677]` | `0.000` (budget_waste) |
| d11 (t=109) | `plant_canary(6 staff, {A:[e16,e19,e24], B:[e04,e07,e14]}, gini=0.41)` | P(mole=e19)=0.444, P(top=e19)=0.444 | `plant_canary({A:[e19], B:[e07,e16]}) [gini=0.65, Q_cont=+0.116]` | `0.011` (-) |
| d13 (t=124) | `accuse(employee=e19)` | P(mole=e19)=0.873, P(top=e19)=0.873 | `plant_canary({A:[e19], B:[e07]}) [gini=0.23, Q_cont=+0.568]` | `0.171` (-) |

### Mode 2: Uninformative or Narrow Canary Assignments

Episode `codex:gpt-5.5/hard/0#0` (`v1.2`, score `-1.000`, correct=`False`, accused=`e05`, true mole=`e25`, end=`accused` on day `11`, total solver regret `0.205 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=4) | `plant_canary(6 staff, {A:[e01,e06,e10], B:[e23,e27,e29]}, gini=0.34)` | P(mole=e25)=0.033, P(top=e00)=0.033 | `plant_canary({A:[e00..e10(6)], B:[e01..e11(6)]}) [gini=0.56, Q_cont=+0.725]` | `0.010` (-) |
| d2 (t=12) | `plant_canary(5 staff, {A:[e00,e11], B:[e17,e18,e26]}, gini=0.26)` | P(mole=e25)=0.052, P(top=e12)=0.057 | `plant_canary({A:[e00..e24(5)], B:[e07..e27(7)]}) [gini=0.58, Q_cont=+0.687]` | `0.015` (-) |
| d3 (t=19) | `plant_canary(11 staff, {A:[e02..e09(5)], B:[e12..e25(6)]}, gini=0.48)` | P(mole=e25)=0.127, P(top=e12)=0.140 | `plant_canary({A:[e02..e24(4)], B:[e04,e12]}) [gini=0.64, Q_cont=+0.721]` | `0.008` (-) |
| d5 (t=36) | `plant_canary(11 staff, {A:[e12], B:[e02..e25(10)]}, gini=0.06)` | P(mole=e25)=0.175, P(top=e24)=0.175 | `plant_canary({A:[e08,e24], B:[e04,e13,e16]}) [gini=0.61, Q_cont=+0.675]` | `0.025` (uninformative_canary) |
| d6 (t=45) | `plant_canary(4 staff, {A:[e02,e22], B:[e05,e25]}, gini=0.44)` | P(mole=e25)=0.333, P(top=e05)=0.341 | `plant_canary({A:[e05], B:[e25]}) [gini=0.67, Q_cont=+0.734]` | `0.010` (-) |
| d7 (t=54) | `plant_canary(4 staff, {A:[e02,e25], B:[e05,e22]}, gini=0.49)` | P(mole=e25)=0.361, P(top=e25)=0.361 | `plant_canary({A:[e25], B:[e05]}) [gini=0.67, Q_cont=+0.725]` | `0.008` (-) |
| d8 (t=61) | `plant_canary(4 staff, {A:[e05], B:[e02,e22,e25]}, gini=0.44)` | P(mole=e25)=0.370, P(top=e25)=0.370 | `plant_canary({A:[e25], B:[e05]}) [gini=0.66, Q_cont=+0.683]` | `0.010` (-) |
| d9 (t=70) | `plant_canary(4 staff, {A:[e25], B:[e02,e05,e22]}, gini=0.41)` | P(mole=e25)=0.293, P(top=e05)=0.405 | `plant_canary({A:[e05], B:[e02]}) [gini=0.66, Q_cont=+0.684]` | `0.011` (-) |
| d11 (t=84) | `accuse(employee=e05)` | P(mole=e25)=0.078, P(top=e05)=0.921 | `plant_canary({A:[e05], B:[e25]}) [gini=0.15, Q_cont=+0.664]` | `0.108` (-) |

### Mode 3: Premature Accusation Under Candidate Ambiguity

Episode `codex:gpt-5.5/medium/0#73` (`v1.3`, score `-1.000`, correct=`False`, accused=`e02`, true mole=`e05`, end=`accused` on day `6`, total solver regret `1.409 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=6) | `plant_canary(6 staff, {A:[e00,e01], B:[e02,e03], C:[e04,e05]}, gini=0.48)` | P(mole=e05)=0.050, P(top=e00)=0.050 | `plant_canary({A:[e00,e01,e19], B:[e08,e09,e13], C:[e10,e15]}) [gini=0.58, Q_cont=+0.792]` | `0.006` (-) |
| d2 (t=15) | `plant_canary(6 staff, {A:[e06,e07], B:[e08,e09], C:[e10,e11]}, gini=0.48)` | P(mole=e05)=0.050, P(top=e07)=0.053 | `plant_canary({A:[e02,e09,e19], B:[e04,e18], C:[e01,e03,e17]}) [gini=0.59, Q_cont=+0.782]` | `0.006` (-) |
| d3 (t=23) | `plant_canary(6 staff, {A:[e14,e15], B:[e16,e18], C:[e00,e02]}, gini=0.70)` | P(mole=e05)=0.080, P(top=e14)=0.113 | `plant_canary({A:[e11,e14], B:[e08,e16], C:[e15,e18]}) [gini=0.72, Q_cont=+0.771]` | `0.001` (-) |
| d4 (t=32) | `plant_canary(6 staff, {A:[e02,e05], B:[e06,e11], C:[e15,e16]}, gini=0.74)` | P(mole=e05)=0.123, P(top=e15)=0.158 | `plant_canary({A:[e15], B:[e11,e18], C:[e02,e16]}) [gini=0.74, Q_cont=+0.751]` | `0.000` (-) |
| d5 (t=43) | `plant_canary(3 staff, {A:[e02], B:[e18], C:[e05]}, gini=0.64)` | P(mole=e05)=0.126, P(top=e02)=0.183 | `plant_canary({A:[e02], B:[e05,e16], C:[e15,e18]}) [gini=0.74, Q_cont=+0.742]` | `0.006` (-) |
| d6 (t=52) | `accuse(employee=e02)` | P(mole=e05)=0.122, P(top=e02)=0.183 | `plant_canary({A:[e02], B:[e18], C:[e15,e16]}) [gini=0.73, Q_cont=+0.732]` | `1.390` (premature_accusation) |

### Mode 4: Over-Restriction of Suspect Access

Episode `grok/hard/900001#51` (`v1.2`, score `+0.755`, correct=`True`, accused=`e09`, true mole=judge-salted (hidden), end=`accused` on day `7`, total solver regret `0.393 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=4) | `plant_canary(2 staff, {A:[e03], B:[e08]}, gini=0.13)` | P(top=e00)=0.033 | `plant_canary({A:[e01..e29(4)], B:[e13..e24(4)]}) [gini=0.43, Q_cont=+0.725]` | `0.014` (uninformative_canary) |
| d2 (t=12) | `plant_canary(2 staff, {A:[e00], B:[e02]}, gini=0.14)` | P(top=e12)=0.081 | `plant_canary({A:[e00..e25(4)], B:[e10,e12,e26]}) [gini=0.56, Q_cont=+0.716]` | `0.019` (uninformative_canary) |
| d3 (t=22) | `plant_canary(2 staff, {A:[e10], B:[e14]}, gini=0.21)` | P(top=e12)=0.089 | `plant_canary({A:[e12,e16,e25], B:[e03,e08,e14]}) [gini=0.59, Q_cont=+0.676]` | `0.017` (-) |
| d4 (t=28) | `plant_canary(2 staff, {A:[e12], B:[e09]}, gini=0.29)` | P(top=e12)=0.133 | `plant_canary({A:[e03,e18], B:[e11,e12,e22]}) [gini=0.58, Q_cont=+0.696]` | `0.013` (-) |
| d5 (t=36) | `restrict_access(employee=e03)` | P(top=e03)=0.292 | `advance_day() [wait leak delay: Q_cont=+0.698 vs E[accuse e03]=-0.461]` | `0.064` (-) |
| d5 (t=37) | `restrict_access(employee=e08)` | P(top=e03)=0.292 | `advance_day() [wait leak delay: Q_cont=+0.698 vs E[accuse e03]=-0.461]` | `0.071` (-) |
| d5 (t=38) | `restrict_access(employee=e09)` | P(top=e03)=0.292 | `advance_day() [wait leak delay: Q_cont=+0.698 vs E[accuse e03]=-0.461]` | `0.085` (over_restriction) |
| d5 (t=39) | `restrict_access(employee=e11)` | P(top=e03)=0.292 | `advance_day() [wait leak delay: Q_cont=+0.698 vs E[accuse e03]=-0.461]` | `0.085` (over_restriction) |
| d7 (t=51) | `accuse(employee=e09)` | P(top=e09)=1.000 | `accuse(employee=e09) [E[V]=+0.755]` | `0.000` (-) |

### Mode 5: Ignored Leak Propagation Delay at Accusation

Episode `openai:gpt-5.5/medium/17#42` (`v1.2`, score `-1.000`, correct=`False`, accused=`e19`, true mole=`e05`, end=`accused` on day `14`, total solver regret `0.959 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=6) | `plant_canary(3 staff, {v_e00:[e00], v_e01:[e01], v_e02:[e02]}, gini=0.27)` | P(mole=e05)=0.050, P(top=e00)=0.050 | `plant_canary({A:[e09,e16,e18], B:[e03,e12,e17], C:[e11,e15]}) [gini=0.58, Q_cont=+0.792]` | `0.019` (-) |
| d2 (t=14) | `plant_canary(3 staff, {v_e03:[e03], v_e04:[e04], v_e05:[e05]}, gini=0.33)` | P(mole=e05)=0.071, P(top=e14)=0.078 | `plant_canary({A:[e12,e14], B:[e11,e17,e19], C:[e05,e06,e13]}) [gini=0.71, Q_cont=+0.762]` | `0.023` (-) |
| d3 (t=19) | `plant_canary(3 staff, {v_e06:[e06], v_e07:[e07], v_e08:[e08]}, gini=0.35)` | P(mole=e05)=0.072, P(top=e19)=0.077 | `plant_canary({A:[e08,e19], B:[e13,e14], C:[e05,e15]}) [gini=0.62, Q_cont=+0.713]` | `0.016` (-) |
| d4 (t=24) | `plant_canary(3 staff, {v_e11:[e11], v_e12:[e12], v_e13:[e13]}, gini=0.41)` | P(mole=e05)=0.067, P(top=e19)=0.111 | `plant_canary({A:[e13,e19], B:[e06,e14], C:[e11,e12]}) [gini=0.68, Q_cont=+0.708]` | `0.016` (-) |
| d5 (t=34) | `plant_canary(3 staff, {v_e14:[e14], v_e15:[e15], v_e17:[e17]}, gini=0.36)` | P(mole=e05)=0.075, P(top=e19)=0.111 | `plant_canary({A:[e13,e15], B:[e18,e19], C:[e03,e06,e08]}) [gini=0.63, Q_cont=+0.659]` | `0.016` (-) |
| d6 (t=39) | `plant_canary(3 staff, {v_e02b:[e02], v_e18:[e18], v_e19:[e19]}, gini=0.35)` | P(mole=e05)=0.065, P(top=e19)=0.103 | `plant_canary({A:[e04,e15], B:[e03,e14], C:[e08,e11,e17]}) [gini=0.64, Q_cont=+0.607]` | `0.018` (-) |
| d7 (t=44) | `plant_canary(3 staff, {v_e02c:[e02], v_e05b:[e05], v_e06b:[e06]}, gini=0.46)` | P(mole=e05)=0.097, P(top=e19)=0.148 | `plant_canary({A:[e19], B:[e11,e14], C:[e05,e06]}) [gini=0.71, Q_cont=+0.623]` | `0.015` (-) |
| d8 (t=49) | `plant_canary(3 staff, {v_e07b:[e07], v_e11b:[e11], v_e12b:[e12]}, gini=0.42)` | P(mole=e05)=0.103, P(top=e19)=0.147 | `plant_canary({A:[e19], B:[e06,e13], C:[e05,e14]}) [gini=0.71, Q_cont=+0.574]` | `0.017` (-) |
| d14 (t=96) | `accuse(employee=e19)` | P(mole=e05)=0.177, P(top=e05)=0.177, P(accused=e19)=0.137 | `advance_day() [abstain: 0.000 > E[accuse e05]=-0.723]` | `0.786` (premature_accusation, ignored_delay) |

### Mode 6: Horizon Expiration Without Accusation

Episode `grok/hard/900000#50` (`v1.2`, score `+0.000`, correct=`False`, accused=`None`, true mole=judge-salted (hidden), end=`horizon` on day `14`, total solver regret `0.236 V`):

| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |
|---|---|---|---|---|
| d1 (t=4) | `plant_canary(2 staff, {A:[e04], B:[e07]}, gini=0.13)` | P(top=e00)=0.033 | `plant_canary({A:[e02..e18(6)], B:[e00..e29(6)]}) [gini=0.56, Q_cont=+0.725]` | `0.020` (uninformative_canary) |
| d2 (t=12) | `plant_canary(2 staff, {A:[e09], B:[e17]}, gini=0.15)` | P(top=e18)=0.060 | `plant_canary({A:[e06..e24(4)], B:[e01..e28(5)]}) [gini=0.58, Q_cont=+0.699]` | `0.020` (uninformative_canary) |
| d3 (t=18) | `plant_canary(2 staff, {A:[e19], B:[e24]}, gini=0.25)` | P(top=e18)=0.178 | `plant_canary({A:[e18], B:[e08,e28]}) [gini=0.58, Q_cont=+0.726]` | `0.015` (-) |
| d4 (t=24) | `plant_canary(2 staff, {A:[e25], B:[e18]}, gini=0.36)` | P(top=e18)=0.151 | `plant_canary({A:[e04,e18], B:[e08,e28]}) [gini=0.64, Q_cont=+0.680]` | `0.013` (-) |
| d9 (t=54) | `restrict_access(employee=e04)` | P(top=e24)=0.262 | `plant_canary({A:[e24], B:[e04,e09]}) [gini=0.65, Q_cont=+0.536]` | `0.043` (-) |
| d9 (t=55) | `restrict_access(employee=e07)` | P(top=e24)=0.262 | `plant_canary({A:[e24], B:[e07,e09]}) [gini=0.65, Q_cont=+0.536]` | `0.044` (-) |
| d9 (t=56) | `restrict_access(employee=e09)` | P(top=e24)=0.262 | `plant_canary({A:[e09,e19], B:[e24]}) [gini=0.64, Q_cont=+0.536]` | `0.042` (-) |
| d14 (t=90) | `advance_day()` | P(top=e04)=0.378 | `advance_day() [abstain: 0.000 > E[accuse e04]=-0.461]` | `0.000` (-) |
| d14 (t=91) | `(episode ended: horizon, no accusation)` | P(top=e04)=0.378 | `abstain at horizon [0.000 >= E[accuse e04]=-0.461]` | `0.000` (no_accusation) |
