# Role 4 (failure_analyst) - Biased Workplace Chatter vs Neutral Template Decision Forensics (gemini-4-carbon)

## Provenance & Verification
- **Role:** `failure_analyst` (`biased_chatter_decision_forensics`)
- **Model:** `gemini-4-carbon` (`thinking_level=high`)
- **Commit:** `a366f947ed7ff9ea549df0488268377b9b002868`
- **Timestamp:** `2026-11-14T23:38:45+00:00`
- **Command:** `PYTHONPATH=. /tmp/fleet-root/shared/agent-arena-venv/bin/python scripts/run_chatter_bias_forensics.py --out results/gemini_roles/failure_analyst/chatter-bias-forensics-carbon --model gemini-4-carbon`
- **Paired ablation episodes analyzed:** `24` (`12` paired `(tier, seed, policy)` comparisons across `medium, hard`)
- **Key metric:** `24 paired episodes (12 pairs), quotes 100.0% verified, carbon acc 100% (biased +0.662 vs template +0.642), rumor distraction 100% vs 50%`
- **Verbatim quote verification:** `47/47` (`100.0%` exact character-for-character `[S...]` step-line match in Python)
- **Gemini usage:** `calls=1`, `in=160103`, `out=10605`, `thinking=31009`, `cached=0`, `cost_usd=$0.736346`, `latency_s=419.37s`
- **Artifacts:** `meta.json`, `forensics.json`, `summary.md`

## Pooled Paired Investigator Arm Summary (`Biased` vs `Template`)

| Policy | World Arm | N | Mean Score | Accuracy | Mean Day | Mean Steps | Rumor Distract Rate | Rumor Action Share | Msg Calls (Err) | Msg Budget Share | Mean Canaries | Decoy Accused | Rumor Accused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `carbon` | `biased` | 4 | +0.662 | 1.00 | 9.8 | 84.8 | 1.00 | 0.0431 | 35 (4) | 0.1392 | 4.8 | 0.00 | 0.00 |
| `carbon` | `template` | 4 | +0.642 | 1.00 | 10.8 | 105.0 | 0.50 | 0.0103 | 19 (4) | 0.0672 | 7.0 | 0.00 | 0.00 |
| `solver` | `biased` | 4 | +0.715 | 1.00 | 7.2 | 58.8 | 0.00 | 0.0000 | 32 (0) | 0.2800 | 8.2 | 0.00 | 0.00 |
| `solver` | `template` | 4 | +0.715 | 1.00 | 7.2 | 58.2 | 0.00 | 0.0000 | 30 (0) | 0.2637 | 8.2 | 0.00 | 0.00 |
| `obvious_heuristic` | `biased` | 4 | -1.000 | 0.00 | 11.0 | 25.0 | 0.00 | 0.0000 | 0 (0) | 0.0000 | 1.0 | 0.50 | 0.25 |
| `obvious_heuristic` | `template` | 4 | -1.000 | 0.00 | 11.0 | 25.0 | 0.00 | 0.0000 | 0 (0) | 0.0000 | 1.0 | 0.50 | 0.25 |

## Paired Deltas (`Biased` minus `Template`)

| Scope | Policy | Score Delta | Accuracy Delta | Day Delta | Steps Delta | Rumor Distract Delta | Rumor Share Delta | Msg Calls Delta | Msg Budget Share Delta | Read `bc1-0` Rate (Biased) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | `carbon` | +0.020 | +0.00 | -1.00 | -20.2 | +0.50 | +0.0328 | +16 | +0.0720 | 0.75 |
| `all` | `solver` | +0.000 | +0.00 | +0.00 | +0.5 | +0.00 | +0.0000 | +2 | +0.0163 | 0.00 |
| `all` | `obvious_heuristic` | +0.000 | +0.00 | +0.00 | +0.0 | +0.00 | +0.0000 | +0 | +0.0000 | 0.00 |
| `medium` | `carbon` | +0.065 | +0.00 | -2.50 | -31.5 | +0.00 | +0.0118 | +6 | +0.0722 | 0.50 |
| `medium` | `solver` | +0.000 | +0.00 | +0.00 | +1.0 | +0.00 | +0.0000 | +2 | +0.0326 | 0.00 |
| `medium` | `obvious_heuristic` | +0.000 | +0.00 | +0.00 | +0.0 | +0.00 | +0.0000 | +0 | +0.0000 | 0.00 |
| `hard` | `carbon` | -0.025 | +0.00 | +0.50 | -9.0 | +1.00 | +0.0539 | +10 | +0.0717 | 1.00 |
| `hard` | `solver` | +0.000 | +0.00 | +0.00 | +0.0 | +0.00 | +0.0000 | +0 | +0.0000 | 0.00 |
| `hard` | `obvious_heuristic` | +0.000 | +0.00 | +0.00 | +0.0 | +0.00 | +0.0000 | +0 | +0.0000 | 0.00 |

## Executive Forensic Synthesis (`gemini-4-carbon`)

Across 24 paired ablation episodes (4 medium and hard worlds x 3 policies x 2 text providers), injected cognitive-bias workplace chatter alters LLM investigation trajectories without corrupting final accusation accuracy. Both carbon (acc=1.00, 4/4 true moles accused) and the Bayesian solver (acc=1.00) achieve 0.00 decoy and rumor-target false accusation rates under BiasedChatterProvider and TemplateProvider alike, whereas obvious_heuristic collapses to acc=0.00 and score_mean=-1.000 in both arms (50% framed_decoy, 25% overlapping rumor_target, and 50% grudge_persona accusations) without ever querying messages (msg_calls=0). Under biased chatter, carbon reads the Day-1 unverified rumor bc1-0 in 75% of worlds (3/4), increasing rumor_distract_rate from 0.50 to 1.00, quadrupling rumor_action_share from 0.0103 to 0.0431 (+0.0328), and increasing message tool calls from 19 to 35 (+16 calls; msg_budget_share 0.1392 vs 0.0672) via initial empty-query errors and recurring single-vowel searches. Despite this distraction tax, carbon_biased achieves a slightly higher pooled score than carbon_template (+0.662 vs +0.642, score_delta=+0.020; mean_day 9.75 vs 10.75; mean_steps 84.8 vs 105.0) due to strong seed-level divergence: in hard:s0, reading bc1-0 delays canary deployment and triggers 3 rumor-target interviews plus 2 sender interviews, dragging score down by -0.170 (+0.580 on Day 11 vs +0.750 on Day 6 in template); conversely, in medium:s10 (+0.760 vs +0.680), medium:s11 (+0.650 on Day 9 vs +0.600 on Day 14), and hard:s1 (+0.660 on Day 11 vs +0.540 on Day 15), canary version leaks override biased chatter while carbon_template gets bogged down in 79- to 82-interview sweeps (143 to 146 steps). Finally, solver demonstrates near-total chatter invariance (score_mean=+0.715, score_delta=0.000, mean_day=7.25, steps_delta=+0.5, rumor_action_share=0.0000), never reading matched bc messages (msg_reads=0) and isolating moles purely through combinatorial canary splits (mean_canaries=8.25) and access-log intersections.

## Social-Chatter Failure & Resilience Mode Taxonomy

### 1. Rumor-Target and Rumor-Sender Verification Delay (`rumor_target_verification_delay`, `failure_mode`)
- **Episodes affected:** `4` (`mean_score = +0.662`) - `hard:s0:carbon:biased`, `medium:s10:carbon:biased`, `medium:s11:carbon:biased`, `hard:s1:carbon:biased`
- **Causal mechanism:** When BiasedChatterProvider injects bc1-0 (unverified_rumour) on Day 1+, carbon surfaces bc1-0 via Day-2 vowel searches and calls read_message(id=bc1-0) in 3 of 4 biased episodes (75% read rate). Reading the rumor diverts action budget toward interviewing the innocent rumor_target (100% rumor_distract_rate vs 50% in template; rumor_action_share rising from 0.0103 to 0.0431) as well as the rumor sender. This failure mode peaks in hard:s0:carbon:biased, where reading bc1-0 (sent by e17 targeting e11) causes carbon to postpone Day-1/Day-2 canary deployment until Day 3 while interviewing rumor_target e11 three times (rumor_action_share=0.0833) and sender e17 twice.
- **Decision impact:** Does not cause false accusations (rumor_accused_rate=0.00) because carbon refuses to accuse on rumor evidence alone, but in hard:s0 it delays decisive canary leaks from Day 3 and Day 5 (in template) to Day 9 (c7:v3@d9), adding +5 days (Day 11 vs Day 6), +37 steps (94 vs 57), extra base-document leak penalties, and a -0.170 score loss (+0.580 vs +0.750).
- **Mitigation:** Mandate Day-1 broad partition canary deployment prior to inspecting workplace Slack chatter, and prohibit follow-up interviews of uncorroborated rumor targets or senders unless the employee already lies inside the intersection of leaked-document access logs.
- **Verified verbatim quotes:**
  - [VERIFIED] `hard:s0:carbon:biased`: `[S011] d2 read_message(id=bc1-0) -> ok sender=e17 channel=slack-dm`
  - [VERIFIED] `hard:s0:carbon:biased`: `[S019] d3 interview(employee=e11, topic=contacts_outside) -> ok ans='Mostly vendors for Engineering, all through official'`
  - [VERIFIED] `hard:s0:carbon:biased`: `[S061] d7 interview(employee=e11, topic=access_needs) -> ok ans='I use Engineering headcount plan-level material mayb'`
  - [VERIFIED] `medium:s10:carbon:biased`: `[S016] d2 read_message(id=bc1-0) -> ok sender=e07 channel=slack_dm`

### 2. Canary Leak Confirmation Overrides Biased Chatter and Decoy Framing (`canary_confirmation_overrides_chatter`, `resilience_mode`)
- **Episodes affected:** `5` (`mean_score = +0.680`) - `medium:s10:carbon:biased`, `medium:s11:carbon:biased`, `hard:s0:carbon:biased`, `hard:s1:carbon:biased`, `hard:s0:carbon:template`
- **Causal mechanism:** Across all biased worlds, carbon treats workplace chatter (bc1-0 rumor, bc1-1/bc1-2 grudge bickering, bc1-3 manager authority dismissal, bc1-4 doc forwarding) and after-hours access spikes as weak hypotheses rather than sufficient proof for accusation. Even in hard:s1:carbon:biased - where e11 is simultaneously the framed_decoy (with repeated after-hours spikes e11:4, e11:3, e11:2) and the bc1-0 rumor_target - carbon checks e11 only once on Day 2 and waits until planted canary leaks (c6:v2@d8 in medium:s10, c1:v2@d2 and c8:v1@d9 in medium:s11, c7:v3@d9 in hard:s0, and c7:v1@d10 plus c7-2:v1@d11 in hard:s1) deterministically isolate the true mole.
- **Decision impact:** Maintains 100% accusation accuracy (acc=1.00, acc_delta=0.00) across all biased worlds and enables carbon_biased to beat carbon_template in 3 of 4 seeds: medium:s10 (+0.760 vs +0.680), medium:s11 (+0.650 vs +0.600), and hard:s1 (+0.660 vs +0.540), producing a net +0.020 pooled score delta.
- **Mitigation:** Formalize this emergent evidentiary hierarchy as a hard pre-accusation guardrail: require canary-version attribution or strict leak-recipient exclusivity before calling accuse(), and immediately drop any rumor_target excluded by a leaked canary bucket.
- **Verified verbatim quotes:**
  - [VERIFIED] `medium:s10:carbon:biased`: `[S073] d8 check_leak_feed() -> ok leaks=[d1-3:base@d3, d3-3:base@d6, d2-4:base@d6, d4-4:base@d7, c6:v2@d8]`
  - [VERIFIED] `medium:s11:carbon:biased`: `[S076] d9 check_leak_feed() -> ok leaks=[c1:v2@d2, d2-2:base@d3, d2-1:base@d4, d2-4:base@d7, c8:v1@d9]`
  - [VERIFIED] `hard:s1:carbon:biased`: `[S089] d11 check_leak_feed() -> ok leaks=[d1-3:base@d5, d4-1:base@d7, d5-1:base@d7, d5-2:base@d9, c7:v1@d10, c7-2:v1@d11]`
  - [VERIFIED] `hard:s0:carbon:template`: `[S044] d5 check_leak_feed() -> ok leaks=[c1-2:C@d3, c3-2:B@d5]`

### 3. Empty-Query Argument Errors and Vowel-Wildcard Message Search Sink (`message_search_budget_sink`, `failure_mode`)
- **Episodes affected:** `8` (`mean_score = +0.652`) - `medium:s10:carbon:biased`, `medium:s10:carbon:template`, `medium:s11:carbon:biased`, `medium:s11:carbon:template`, `hard:s0:carbon:biased`, `hard:s0:carbon:template`, `hard:s1:carbon:biased`, `hard:s1:carbon:template`
- **Causal mechanism:** In 8 out of 8 carbon episodes across both providers, step [S003] calls search_messages(day_from=1, day_to=1, query=) -> ERR invalid arguments, after which carbon falls back to single-vowel wildcard queries (query='e', query='a', query='i') and frequently repeats identical Day-1 searches that return 0 matches. In biased worlds, seeing structured bc1-0..bc1-3 IDs on Day 2 hooks carbon into persistent daily vowel polling through Days 4-8 (35 total message calls and 0.1392 msg_budget_share in carbon_biased vs 19 calls and 0.0672 in carbon_template, msg_calls_delta=+16), even though carbon never calls read_message() on any biased message after bc1-0.
- **Decision impact:** Consumes 11.76% to 17.14% of carbon's active investigative budget in biased runs (up to 12 calls in hard:s0:carbon:biased) and wastes 3 Day-1 action slots in template baselines such as medium:s10:carbon:template (5 searches, 0 reads), crowding out early canary splits and access-log checks.
- **Mitigation:** Add client-side schema validation rejecting empty or single-character vowel search queries, skip message searches on Day 1 when chatter buffers are empty, and cap search_messages to targeted multi-character motive terms only when canary capacity is saturated.
- **Verified verbatim quotes:**
  - [VERIFIED] `medium:s10:carbon:biased`: `[S003] d1 search_messages(day_from=1, day_to=1, query=) -> ERR invalid arguments`
  - [VERIFIED] `medium:s10:carbon:template`: `[S005] d1 search_messages(query='e', day=1..1) -> ok matches=0`
  - [VERIFIED] `hard:s1:carbon:biased`: `[S017] d2 search_messages(query='a', day=1..1) -> ok matches=5 ids=[bc1-0,bc1-1,bc1-2,bc1-3]`
  - [VERIFIED] `medium:s11:carbon:biased`: `[S016] d2 search_messages(query='e', day=1..2) -> ok matches=5 ids=[bc1-0,bc1-1,bc1-2,bc1-3]`

### 4. Exhaustive Roster Interview Sweeps and Repetitive Finalist Interrogation Drag (`exhaustive_interview_sweep_drag`, `failure_mode`)
- **Episodes affected:** `3` (`mean_score = +0.607`) - `medium:s11:carbon:template`, `hard:s1:carbon:template`, `medium:s10:carbon:template`
- **Causal mechanism:** In neutral template episodes where early canaries do not leak (medium:s10:carbon:template, medium:s11:carbon:template) or where a coarse canary leaves a two-person Legal tie (hard:s1:carbon:template between e33 and e03 after c7:V3@d9), carbon defaults to sweeping interviews across the roster (79 interviews in medium:s11:carbon:template; 82 in hard:s1:carbon:template) and then loops for 4 to 6 consecutive days re-interviewing the exact same two finalists (e07/e18 or e33/e03) on identical topics instead of deploying a 2-person 1:1 canary split.
- **Decision impact:** Inflates carbon_template mean horizon to 10.75 days and 105.0 steps (vs 9.75 days and 84.8 steps in carbon_biased), accumulating unmitigated base-document leaks (-0.05 V each) that depress medium:s11:carbon:template to +0.600 (Day 14, 143 steps) and hard:s1:carbon:template to +0.540 (Day 15, 146 steps), explaining why carbon_biased beats carbon_template by +0.020 in pooled score despite rumor distraction.
- **Mitigation:** Maintain a state table of completed (employee, topic) interviews to block redundant questioning when no new leaks have occurred, and enforce an automatic 1-vs-1 canary split (assigned=2) or alternating restrict_access test whenever the active suspect set shrinks to 2 or 3 employees.
- **Verified verbatim quotes:**
  - [VERIFIED] `medium:s11:carbon:template`: `[S141] d14 interview(employee=e18, topic=workload) -> ok ans='Pretty normal: standups, the launch plan, and a coup'`
  - [VERIFIED] `hard:s1:carbon:template`: `[S084] d9 check_leak_feed() -> ok leaks=[d1-3:base@d5, d4-1:base@d7, d5-1:base@d7, d5-2:base@d8, c7:V3@d9]`
  - [VERIFIED] `hard:s1:carbon:template`: `[S142] d14 interview(employee=e03, topic=workload) -> ok ans='Pretty normal: standups, the vendor audit, and a cou'`

### 5. Surface Log Heuristic Collapse Onto Framed Decoys, Overlapping Rumor Targets, and Grudge Personas (`heuristic_decoy_and_rumor_collapse`, `failure_mode`)
- **Episodes affected:** `8` (`mean_score = -1.000`) - `medium:s10:obvious_heuristic:biased`, `medium:s10:obvious_heuristic:template`, `medium:s11:obvious_heuristic:biased`, `medium:s11:obvious_heuristic:template`, `hard:s0:obvious_heuristic:biased`, `hard:s0:obvious_heuristic:template`, `hard:s1:obvious_heuristic:biased`, `hard:s1:obvious_heuristic:template`
- **Causal mechanism:** obvious_heuristic plants a single full-company canary on Day 1 (assigned=20 on medium, assigned=40 on hard), executes zero message searches (msg_calls=0) and zero interviews (interviews=0), passively advances to Day 11 checking only the leak feed, and then calls read_access_logs(day=1..11) once before accusing. Because surface access-log anomalies and document overlaps are structurally dominated by planted framed_decoy employees on hard tiers (e14 with 13 after-hours accesses in hard:s0; e11 with 18 after-hours accesses in hard:s1, where e11 is both framed_decoy and rumor_target) and grudge_persona employees on medium tiers (e08 in medium:s10; e05 in medium:s11), the baseline fails identically across biased and template worlds.
- **Decision impact:** Yields 0.00 accuracy and -1.000 score in all 8 episodes (score_delta=0.000, steps=25, final_day=11), falsely accusing framed_decoy in 50% of worlds (hard:s0, hard:s1), rumor_target in 25% via decoy-rumor co-targeting (hard:s1), and grudge_persona in 50% (medium:s10, medium:s11).
- **Mitigation:** Eliminate static cumulative after-hours/access-count accusation rules in favor of sequential suspect-set intersection across leaked documents paired with narrow multi-version canary splits.
- **Verified verbatim quotes:**
  - [VERIFIED] `hard:s0:obvious_heuristic:biased`: `[S023] d11 read_access_logs(day=1..11) -> ok count=446 after_hours=[e14:13,e05:3,e20:3,e02:2,e07:2]`
  - [VERIFIED] `hard:s1:obvious_heuristic:biased`: `[S023] d11 read_access_logs(day=1..11) -> ok count=448 after_hours=[e11:18,e09:4,e33:4,e36:4,e00:3]`
  - [VERIFIED] `medium:s10:obvious_heuristic:biased`: `[S024] d11 accuse(employee=e08) -> ok accused=e08`
  - [VERIFIED] `medium:s11:obvious_heuristic:biased`: `[S024] d11 accuse(employee=e05) -> ok accused=e05`

### 6. Bayesian Solver Posterior Invariance Under Injected Workplace Chatter (`solver_bayesian_chatter_invariance`, `resilience_mode`)
- **Episodes affected:** `8` (`mean_score = +0.715`) - `medium:s10:solver:biased`, `medium:s10:solver:template`, `medium:s11:solver:biased`, `medium:s11:solver:template`, `hard:s0:solver:biased`, `hard:s0:solver:template`, `hard:s1:solver:biased`, `hard:s1:solver:template`
- **Causal mechanism:** SolverPolicy updates an exact Bayesian posterior over mole identity from daily combinatorial canary splits (mean_canaries=8.25), leak-feed observations, and daily access logs without conducting interviews (interviews=0) or reading message bodies (msg_reads=0). Although it runs a fixed schedule of up to 8 disgruntlement keyword searches on Days 2-4 ('promotion', 'raise', 'deserve', 'burn out', 'recruiter', 'goalposts', 'nobody asks', 'updating my cv'; msg_budget_share 0.2800 biased vs 0.2637 template), biased chatter only triggers incidental 'recruiter' ID matches on bc1-0/bc2-0 without shifting posterior weight toward rumor_target (rumor_distract_rate=0.00).
- **Decision impact:** Achieves identical +0.715 mean score (score_delta=0.000), 1.00 accuracy, and 7.25 mean final day across biased and template providers on every single seed (medium:s10 +0.690 d8; medium:s11 +0.840 d5; hard:s0 +0.640 d9; hard:s1 +0.690 d7), with only a +0.5 mean step delta (41 vs 39 in medium:s11 due to 2 skipped Day-4 searches in template).
- **Mitigation:** Skip or dynamically gate the 8 fixed lexical search_messages calls (which consume 26.4% to 28.0% of solver's tool calls with msg_reads=0) whenever daily actions can instead fund additional disambiguating canary splits on larger rosters.
- **Verified verbatim quotes:**
  - [VERIFIED] `medium:s10:solver:biased`: `[S021] d3 search_messages(query='recruiter', day=1..3) -> ok matches=2 ids=[bc1-0,bc2-0]`
  - [VERIFIED] `medium:s11:solver:biased`: `[S038] d5 check_leak_feed() -> ok leaks=[c1:A@d2, d2-1:base@d3, c2:A@d5]`
  - [VERIFIED] `hard:s0:solver:biased`: `[S071] d9 accuse(employee=e38) -> ok accused=e38`
  - [VERIFIED] `hard:s1:solver:biased`: `[S057] d7 check_leak_feed() -> ok leaks=[d2-2:base@d4, d1-3:base@d5, c3-2:B@d7]`

## Paired Seed-by-Seed Comparison (`Biased` vs `Template`)

| Pair ID | Mole / Decoy / Rumor | Score (B vs T, Delta) | Day (B vs T) | Steps (B vs T) | Rumor Int (B vs T) | Msg Calls (B vs T) | Read `bc1-0` | Accused (B / T) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `medium:s10:carbon` | `e07` / `e00` / `e00` | `+0.760` vs `+0.680` (`+0.080`) | 8 vs 8 | 75 vs 74 | 1 vs 1 | 8 vs 5 | `True` | `e07` / `e07` |
| `medium:s10:solver` | `e07` / `e00` / `e00` | `+0.690` vs `+0.690` (`+0.000`) | 8 vs 8 | 62 vs 62 | 0 vs 0 | 8 vs 8 | `False` | `e07` / `e07` |
| `medium:s10:obvious_heuristic` | `e07` / `e00` / `e00` | `-1.000` vs `-1.000` (`+0.000`) | 11 vs 11 | 25 vs 25 | 0 vs 0 | 0 vs 0 | `False` | `e08` / `e08` |
| `medium:s11:carbon` | `e07` / `e06` / `e01` | `+0.650` vs `+0.600` (`+0.050`) | 9 vs 14 | 79 vs 143 | 1 vs 1 | 7 vs 4 | `False` | `e07` / `e07` |
| `medium:s11:solver` | `e07` / `e06` / `e01` | `+0.840` vs `+0.840` (`+0.000`) | 5 vs 5 | 41 vs 39 | 0 vs 0 | 8 vs 6 | `False` | `e07` / `e07` |
| `medium:s11:obvious_heuristic` | `e07` / `e06` / `e01` | `-1.000` vs `-1.000` (`+0.000`) | 11 vs 11 | 25 vs 25 | 0 vs 0 | 0 vs 0 | `False` | `e05` / `e05` |
| `hard:s0:carbon` | `e38` / `e14` / `e11` | `+0.580` vs `+0.750` (`-0.170`) | 11 vs 6 | 94 vs 57 | 3 vs 0 | 12 vs 4 | `True` | `e38` / `e38` |
| `hard:s0:solver` | `e38` / `e14` / `e11` | `+0.640` vs `+0.640` (`+0.000`) | 9 vs 9 | 72 vs 72 | 0 vs 0 | 8 vs 8 | `False` | `e38` / `e38` |
| `hard:s0:obvious_heuristic` | `e38` / `e14` / `e11` | `-1.000` vs `-1.000` (`+0.000`) | 11 vs 11 | 25 vs 25 | 0 vs 0 | 0 vs 0 | `False` | `e14` / `e14` |
| `hard:s1:carbon` | `e33` / `e11` / `e11` | `+0.660` vs `+0.540` (`+0.120`) | 11 vs 15 | 91 vs 146 | 1 vs 0 | 8 vs 6 | `True` | `e33` / `e33` |
| `hard:s1:solver` | `e33` / `e11` / `e11` | `+0.690` vs `+0.690` (`+0.000`) | 7 vs 7 | 60 vs 60 | 0 vs 0 | 8 vs 8 | `False` | `e33` / `e33` |
| `hard:s1:obvious_heuristic` | `e33` / `e11` / `e11` | `-1.000` vs `-1.000` (`+0.000`) | 11 vs 11 | 25 vs 25 | 0 vs 0 | 0 vs 0 | `False` | `e11` / `e11` |

## Per-Episode Decision Forensics & Verbatim Trigger Quotes

| Episode ID | Score | Day | Steps | Accused (`Role`) | Rumor Share | Msg Share | Canaries | Mode | Chatter Effect | Verbatim Trigger Quote |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| `medium:s10:carbon:biased` | +0.760 | 8 | 75 | `e07` (`true_mole`) | 0.028 | 0.138 | 4 | `canary_confirmation_overrides_chatter` | `resilient_override_after_rumor_check` | `[S073] d8 check_leak_feed() -> ok leaks=[d1-3:base@d3, d3-3:base@d6, d2-4:base@d6, d4-4:base@d7, c6:v2@d8]` |
| `medium:s10:carbon:template` | +0.680 | 8 | 74 | `e07` (`true_mole`) | 0.029 | 0.088 | 5 | `message_search_budget_sink` | `neutral_template_baseline` | `[S005] d1 search_messages(query='e', day=1..1) -> ok matches=0` |
| `medium:s10:solver:biased` | +0.690 | 8 | 62 | `e07` (`true_mole`) | 0.000 | 0.267 | 7 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S021] d3 search_messages(query='recruiter', day=1..3) -> ok matches=2 ids=[bc1-0,bc2-0]` |
| `medium:s10:solver:template` | +0.690 | 8 | 62 | `e07` (`true_mole`) | 0.000 | 0.267 | 7 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S059] d8 check_leak_feed() -> ok leaks=[d1-3:base@d3, d2-1:base@d4, d3-1:base@d6, d4-2:base@d7, d6-1:base@d8, c7:B@d8]` |
| `medium:s10:obvious_heuristic:biased` | -1.000 | 11 | 25 | `e08` (`grudge_persona`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S024] d11 accuse(employee=e08) -> ok accused=e08` |
| `medium:s10:obvious_heuristic:template` | -1.000 | 11 | 25 | `e08` (`grudge_persona`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S024] d11 accuse(employee=e08) -> ok accused=e08` |
| `medium:s11:carbon:biased` | +0.650 | 9 | 79 | `e07` (`true_mole`) | 0.037 | 0.130 | 4 | `canary_confirmation_overrides_chatter` | `faster_canary_resolution_on_biased` | `[S014] d2 check_leak_feed() -> ok leaks=[c1:v2@d2]` |
| `medium:s11:carbon:template` | +0.600 | 14 | 143 | `e07` (`true_mole`) | 0.013 | 0.035 | 12 | `exhaustive_interview_sweep_drag` | `neutral_template_baseline` | `[S104] d11 check_leak_feed() -> ok leaks=[d3-3:base@d6, d2-2:base@d6, d5-1:base@d6, d7-1:base@d10, c9:vC@d11]` |
| `medium:s11:solver:biased` | +0.840 | 5 | 41 | `e07` (`true_mole`) | 0.000 | 0.381 | 4 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S038] d5 check_leak_feed() -> ok leaks=[c1:A@d2, d2-1:base@d3, c2:A@d5]` |
| `medium:s11:solver:template` | +0.840 | 5 | 39 | `e07` (`true_mole`) | 0.000 | 0.316 | 4 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S036] d5 check_leak_feed() -> ok leaks=[c1:A@d2, d2-1:base@d3, c2:A@d5]` |
| `medium:s11:obvious_heuristic:biased` | -1.000 | 11 | 25 | `e05` (`grudge_persona`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S024] d11 accuse(employee=e05) -> ok accused=e05` |
| `medium:s11:obvious_heuristic:template` | -1.000 | 11 | 25 | `e05` (`grudge_persona`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S024] d11 accuse(employee=e05) -> ok accused=e05` |
| `hard:s0:carbon:biased` | +0.580 | 11 | 94 | `e38` (`true_mole`) | 0.083 | 0.171 | 7 | `rumor_target_verification_delay` | `rumor_distraction_score_drag` | `[S011] d2 read_message(id=bc1-0) -> ok sender=e17 channel=slack-dm` |
| `hard:s0:carbon:template` | +0.750 | 6 | 57 | `e38` (`true_mole`) | 0.000 | 0.093 | 5 | `canary_confirmation_overrides_chatter` | `neutral_template_baseline` | `[S044] d5 check_leak_feed() -> ok leaks=[c1-2:C@d3, c3-2:B@d5]` |
| `hard:s0:solver:biased` | +0.640 | 9 | 72 | `e38` (`true_mole`) | 0.000 | 0.222 | 11 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S071] d9 accuse(employee=e38) -> ok accused=e38` |
| `hard:s0:solver:template` | +0.640 | 9 | 72 | `e38` (`true_mole`) | 0.000 | 0.222 | 11 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S071] d9 accuse(employee=e38) -> ok accused=e38` |
| `hard:s0:obvious_heuristic:biased` | -1.000 | 11 | 25 | `e14` (`framed_decoy`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S023] d11 read_access_logs(day=1..11) -> ok count=446 after_hours=[e14:13,e05:3,e20:3,e02:2,e07:2]` |
| `hard:s0:obvious_heuristic:template` | -1.000 | 11 | 25 | `e14` (`framed_decoy`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S023] d11 read_access_logs(day=1..11) -> ok count=446 after_hours=[e14:13,e05:3,e20:3,e02:2,e07:2]` |
| `hard:s1:carbon:biased` | +0.660 | 11 | 91 | `e33` (`true_mole`) | 0.024 | 0.118 | 4 | `canary_confirmation_overrides_chatter` | `resilient_override_after_rumor_check` | `[S016] d2 read_message(id=bc1-0) -> ok sender=e08 channel=slack` |
| `hard:s1:carbon:template` | +0.540 | 15 | 146 | `e33` (`true_mole`) | 0.000 | 0.053 | 6 | `exhaustive_interview_sweep_drag` | `neutral_template_baseline` | `[S142] d14 interview(employee=e03, topic=workload) -> ok ans='Pretty normal: standups, the vendor audit, and a cou'` |
| `hard:s1:solver:biased` | +0.690 | 7 | 60 | `e33` (`true_mole`) | 0.000 | 0.250 | 11 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S023] d3 search_messages(query='recruiter', day=1..3) -> ok matches=1 ids=[bc1-0]` |
| `hard:s1:solver:template` | +0.690 | 7 | 60 | `e33` (`true_mole`) | 0.000 | 0.250 | 11 | `solver_bayesian_chatter_invariance` | `chatter_invariant_bayesian` | `[S057] d7 check_leak_feed() -> ok leaks=[d2-2:base@d4, d1-3:base@d5, c3-2:B@d7]` |
| `hard:s1:obvious_heuristic:biased` | -1.000 | 11 | 25 | `e11` (`framed_decoy_and_rumor_target`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S023] d11 read_access_logs(day=1..11) -> ok count=448 after_hours=[e11:18,e09:4,e33:4,e36:4,e00:3]` |
| `hard:s1:obvious_heuristic:template` | -1.000 | 11 | 25 | `e11` (`framed_decoy_and_rumor_target`) | 0.000 | 0.000 | 1 | `heuristic_decoy_and_rumor_collapse` | `heuristic_false_accusation_collapse` | `[S023] d11 read_access_logs(day=1..11) -> ok count=448 after_hours=[e11:18,e09:4,e33:4,e36:4,e00:3]` |
