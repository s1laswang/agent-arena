# Canary Lab Role: Failure Analyst (`gemini-4-carbon` Suite)

Consolidated provenance, verbatim quote verification, and decision-forensics findings across all committed `gemini-4-carbon` runs under `results/gemini/roles_carbon/failure_analyst/`.
Regenerate automatically as new analyst runs land via:
`PYTHONPATH=. python -m canary.gemini.analyst_carbon`

## Human Validation Reservation & Automated Audit Disclosure

- **Human validation sheet (`docs/gemini/validation.md`) is untouched:** `docs/gemini/validation.md` is strictly reserved for human labeller **Ivar** and scored only via `python -m canary.gemini.atlas_agreement`. No automated script in this suite fills or edits `docs/gemini/validation.md`.
- **Automated LLM / solver audit disclosure:** Any claim audit or agreement rate reported inside `results/gemini/roles_carbon/failure_analyst/` (including automated claim audits such as `claim-audit-carbon` and deterministic solver-vs-LLM agreement checks in `atlas-carbon`) is **explicitly an automated LLM or solver audit (`gemini-4-carbon`), never human inter-annotator agreement**.

## Suite Totals (`gemini-4-carbon`, `stub=False`, Secret Hygiene Clean)

| Metric | Value |
| --- | --- |
| Verified `gemini-4-carbon` Runs | `5` (rejected: `0`, secret leaks: `0`) |
| Corpus Scope Analyzed | `327` episode-level evaluations (`246` directly diagnosed) + `30` audited atlas claims (automated LLM audit) |
| Verbatim Quote Verification | `145/145` (`100.0%` exact Python verification) |
| Gemini API Calls | `10` |
| Input / Output / Thinking Tokens | `1,114,554` in / `44,068` out / `95,665` thinking (`0` cached) |
| Recorded Gemini API Cost | `$3.477568` USD |

## Committed `failure_analyst` Carbon Runs

| Run ID | Subrole | Thinking | Commit | Scope | Verbatim Quotes | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Finding |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `atlas-carbon` | `failure_atlas_carbon` | `default` | `26ab62d` | 101 episodes | `17/17` (`100%`) | 2 | 596,862 / 3,191 / 13,356 | `$1.3592` | 101 episodes (total solver regret 20.39 V), 6 modes (top: premature-accusation 39.4%), 17/17 (100.0%) quotes verified, automated solver-vs-LLM agreement 93.3% |
| `calibration-ev-carbon` | `bayesian_calibration_analyst` | `default` | `fdf16a71b039` | 101 episodes calibrated (20 premature diagnosed) | `35/35` (`100%`) | 1 | 83,405 / 6,623 / 10,782 | `$0.3409` | 101 episodes calibrated (ECE 0.0807, Brier 0.0708), 20 premature commits below 1/(1+V) losing 7.49 EV, 35/35 (100.0%) quotes verified |
| `carbon-longctx-corpus` | `carbon_longctx_corpus` | `default` | `71a425530574` | 101 episodes | `16/16` (`100%`) | 2 | 237,763 / 16,390 / 14,887 | `$0.6394` | 101 episodes (261,087 chars in one prompt), 6 decision failure clusters, 16/16 (100.0%) quotes verified |
| `chatter-bias-forensics-carbon` | `biased_chatter_decision_forensics` | `high` | `a366f947ed7f` | 24 paired episodes (12 pairs) | `47/47` (`100%`) | 1 | 160,103 / 10,605 / 31,009 | `$0.7363` | 24 paired episodes (12 pairs), quotes 100.0% verified, carbon acc 100% (biased +0.662 vs template +0.642), rumor distraction 100% vs 50% |
| `claim-audit-carbon` | `atlas_claim_audit_carbon` | `medium` | `a366f947ed7f` | 30 claims audited (automated LLM audit) | `30/30` (`100%`) | 4 | 36,421 / 7,259 / 25,631 | `$0.4017` | 30/30 atlas claims audited (automated LLM, not human): 22 agree, 6 disagree, 2 unsure (78.6% scored agreement, 9 over-claims flagged, 100% verified quotes) |

## Per-Run Provenance & Decision Forensics Details

### 1. `atlas-carbon` (`failure_atlas_carbon`)
- **Artifact directory:** `results/gemini/roles_carbon/failure_analyst/atlas-carbon`
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `stub=False`)
- **Commit & timestamp:** `26ab62d` (`2026-11-14T13:59:28+00:00`)
- **Scope:** 101 episodes
- **Verbatim quotes:** `17/17` (`100.0%`)
- **Gemini API usage:** `calls=2`, `in=596,862`, `out=3,191`, `thinking=13,356`, `cached=0`, `cost_usd=$1.359194`
- **Key metric:** 101 episodes (total solver regret 20.39 V), 6 modes (top: premature-accusation 39.4%), 17/17 (100.0%) quotes verified, automated solver-vs-LLM agreement 93.3%
- **Audit disclosure:** `automated solver-vs-LLM agreement check (not human labelling)` (`docs/gemini/validation.md` remains untouched for human labeller Ivar)
- **Labelled modes / clusters:** `Premature Accusation on Noisy Framing Evidence (39.4% regret)`; `Narrow or Lopsided Canary Partitions (27.8% regret)`; `Subthreshold Accusation Before Optimal Split (13.8% regret)`; `Over-Restriction Starving Diagnostic Traps (10.7% regret)`; `Ignoring Leak-Feed Delay Pipeline (7.8% regret)`; `Delayed Accusation and Horizon Expiration (0.4% regret)`
- **Committed files:** `atlas.json`, `atlas.md`, `charts/ignored-delay.svg`, `charts/late-commit.svg`, `charts/over-restriction.svg`, `charts/premature-accusation.svg`, `charts/subthreshold-commit.svg`, `charts/uninformative-canary.svg`, `meta.json`
- **Synthesis:** Across 101 Canary Lab episodes (total solver regret 20.3903), agent failures cluster around stopping-time miscalibration and suboptimal experiment design. Stopping errors account for 61.1% of total regret: agents frequently commit premature accusations below P=0.60 using noisy framing logs (39.4% regret share), settle for moderate-posterior accusations when another canary split carries higher continuation value (13.8%), or misinterpret unsurfaced 1-to-3 day pipeline leaks as exoneration (7.9%). On the information-gathering side, narrow 2-to-3 recipient or lopsided canaries lag optimal Gini partitions across 71 episodes (27.8% regret share), leaving finalists unresolved near day 14, while aggressive access restrictions (10.7%) burn company value and block suspects from receiving diagnostic traps. Late commits after certainty (0.4%) represent a minor residual leak cost.

### 2. `calibration-ev-carbon` (`bayesian_calibration_analyst`)
- **Artifact directory:** `results/gemini/roles_carbon/failure_analyst/calibration-ev-carbon`
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `stub=False`)
- **Commit & timestamp:** `fdf16a71b039` (`2026-11-14T13:42:39+00:00`)
- **Scope:** 101 episodes calibrated (20 premature diagnosed)
- **Verbatim quotes:** `35/35` (`100.0%`)
- **Gemini API usage:** `calls=1`, `in=83,405`, `out=6,623`, `thinking=10,782`, `cached=0`, `cost_usd=$0.340860`
- **Key metric:** 101 episodes calibrated (ECE 0.0807, Brier 0.0708), 20 premature commits below 1/(1+V) losing 7.49 EV, 35/35 (100.0%) quotes verified
- **Labelled modes / clusters:** `Static 50% Majority Heuristic Under Company Value Bleed`; `Behavioral Framing Decoys Overriding Canary-Access Posteriors`; `Low-Coverage Canary Splits Starving Posterior Concentration`; `Mid-Horizon Snap Commit Before Canary Confirmation`; `Day-14 Forced-Choice Panic Over Zero-EV Abstention`
- **Committed files:** `calibration.json`, `calibration.md`, `diagnosis.json`, `meta.json`, `summary.md`
- **Synthesis:** Across 101 frontier Canary episodes, investigators accused in 100 cases and abstained only once (0.99% abstention rate), producing 20 premature commits below the rational Bayesian break-even gate P >= 1 / (1 + V_true) and losing 7.4894 total EV (mean V_true = 0.6724, mean break-even threshold = 0.6005, ECE = 0.0807, Brier = 0.0708). Failures decompose into five mechanisms: (1) Value-Bleed Threshold Blindness (7/20 episodes, 0.9310 EV lost), where agents identify the true top suspect with P in [0.5223, 0.5787] - sufficient at V_true = 1.0 - but ignore that value erosion to [0.4400, 0.6700] lifts break-even to [0.5988, 0.6944]; (2) Framing Decoy Suboptimal Target Selection (3/20 episodes, 2.3391 EV lost), where noisy after-hours logs and interview answers bait agents into accusing P in [0.1133, 0.1693] decoys while overlooking Bayesian leaders at P in [0.4889, 0.5764]; (3) Under-Informative Canary Design (3/20 episodes, 1.6408 EV lost), where 1-to-3 employee canary assignments yield zero canary leaks over 14 days; (4) Early Snap Accusation (4/20 episodes, 1.3909 EV lost), where agents commit on days 6-12 at P in [0.1834, 0.4608] despite remaining time and action budget; and (5) Horizon Deadline Panic (3/20 episodes, 1.1876 EV lost), where agents treat day 14 as a mandatory-guess deadline rather than taking the 0.0 EV abstain option.

### 3. `carbon-longctx-corpus` (`carbon_longctx_corpus`)
- **Artifact directory:** `results/gemini/roles_carbon/failure_analyst/carbon-longctx-corpus`
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=default`, `stub=False`)
- **Commit & timestamp:** `71a425530574` (`2026-11-14T13:31:42Z`)
- **Scope:** 101 episodes
- **Verbatim quotes:** `16/16` (`100.0%`)
- **Gemini API usage:** `calls=2`, `in=237,763`, `out=16,390`, `thinking=14,887`, `cached=0`, `cost_usd=$0.639426`
- **Key metric:** 101 episodes (261,087 chars in one prompt), 6 decision failure clusters, 16/16 (100.0%) quotes verified
- **Labelled modes / clusters:** `Action Budget Waste and Daily Limit Overruns`; `Uninformative or Narrow Canary Assignments`; `Premature Accusation Under Candidate Ambiguity`; `Over-Restriction of Suspect Access`; `Ignored Leak Propagation Delay at Accusation`; `Horizon Expiration Without Accusation`
- **Committed files:** `failure_gallery.md`, `meta.json`, `pack_stats.json`, `raw_response.json`, `report.json`
- **Synthesis:** Across 101 mole-hunting episodes (91 correct, 9 wrong accusations, 1 horizon timeout), failures cluster into six concrete decision modes. Action budget waste is most frequent (45 episodes): repetitive sentiment searches, redundant status checks, and per-employee log queries hit daily limits and crowd out key tools. Uninformative canary design (30 episodes) wastes days on tiny 2-to-3 suspect pairs, single-variant assignments, or duplicate splits. Premature accusation drives the largest regret (19 episodes, 9.64 regret), as agents guess among unresolved candidates, compounded when they ignore leak propagation delays at day 14 (2 episodes). Minor modes include over-restricting suspects (3 episodes), which suppresses canary signals, and letting the day-14 horizon expire without accusing (1 episode).

### 4. `chatter-bias-forensics-carbon` (`biased_chatter_decision_forensics`)
- **Artifact directory:** `results/gemini/roles_carbon/failure_analyst/chatter-bias-forensics-carbon`
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=high`, `stub=False`)
- **Commit & timestamp:** `a366f947ed7f` (`2026-11-14T23:38:45+00:00`)
- **Scope:** 24 paired episodes (12 pairs)
- **Verbatim quotes:** `47/47` (`100.0%`)
- **Gemini API usage:** `calls=1`, `in=160,103`, `out=10,605`, `thinking=31,009`, `cached=0`, `cost_usd=$0.736346`
- **Key metric:** 24 paired episodes (12 pairs), quotes 100.0% verified, carbon acc 100% (biased +0.662 vs template +0.642), rumor distraction 100% vs 50%
- **Labelled modes / clusters:** `Rumor-Target and Rumor-Sender Verification Delay`; `Canary Leak Confirmation Overrides Biased Chatter and Decoy Framing`; `Empty-Query Argument Errors and Vowel-Wildcard Message Search Sink`; `Exhaustive Roster Interview Sweeps and Repetitive Finalist Interrogation Drag`; `Surface Log Heuristic Collapse Onto Framed Decoys, Overlapping Rumor Targets, and Grudge Personas`; `Bayesian Solver Posterior Invariance Under Injected Workplace Chatter`
- **Committed files:** `forensics.json`, `meta.json`, `summary.md`
- **Synthesis:** Across 24 paired ablation episodes (4 medium and hard worlds x 3 policies x 2 text providers), injected cognitive-bias workplace chatter alters LLM investigation trajectories without corrupting final accusation accuracy. Both carbon (acc=1.00, 4/4 true moles accused) and the Bayesian solver (acc=1.00) achieve 0.00 decoy and rumor-target false accusation rates under BiasedChatterProvider and TemplateProvider alike, whereas obvious_heuristic collapses to acc=0.00 and score_mean=-1.000 in both arms (50% framed_decoy, 25% overlapping rumor_target, and 50% grudge_persona accusations) without ever querying messages (msg_calls=0). Under biased chatter, carbon reads the Day-1 unverified rumor bc1-0 in 75% of worlds (3/4), increasing rumor_distract_rate from 0.50 to 1.00, quadrupling rumor_action_share from 0.0103 to 0.0431 (+0.0328), and increasing message tool calls from 19 to 35 (+16 calls; msg_budget_share 0.1392 vs 0.0672) via initial empty-query errors and recurring single-vowel searches. Despite this distraction tax, carbon_biased achieves a slightly higher pooled score than carbon_template (+0.662 vs +0.642, score_delta=+0.020; mean_day 9.75 vs 10.75; mean_steps 84.8 vs 105.0) due to strong seed-level divergence: in hard:s0, reading bc1-0 delays canary deployment and triggers 3 rumor-target interviews plus 2 sender interviews, dragging score down by -0.170 (+0.580 on Day 11 vs +0.750 on Day 6 in template); conversely, in medium:s10 (+0.760 vs +0.680), medium:s11 (+0.650 on Day 9 vs +0.600 on Day 14), and hard:s1 (+0.660 on Day 11 vs +0.540 on Day 15), canary version leaks override biased chatter while carbon_template gets bogged down in 79- to 82-interview sweeps (143 to 146 steps). Finally, solver demonstrates near-total chatter invariance (score_mean=+0.715, score_delta=0.000, mean_day=7.25, steps_delta=+0.5, rumor_action_share=0.0000), never reading matched bc messages (msg_reads=0) and isolating moles purely through combinatorial canary splits (mean_canaries=8.25) and access-log intersections.

### 5. `claim-audit-carbon` (`atlas_claim_audit_carbon`)
- **Artifact directory:** `results/gemini/roles_carbon/failure_analyst/claim-audit-carbon`
- **Model & thinking:** `gemini-4-carbon` (`thinking_level=medium`, `stub=False`)
- **Commit & timestamp:** `a366f947ed7f` (`2026-11-14T23:12:35+00:00`)
- **Scope:** 30 claims audited (automated LLM audit)
- **Verbatim quotes:** `30/30` (`100.0%`)
- **Gemini API usage:** `calls=4`, `in=36,421`, `out=7,259`, `thinking=25,631`, `cached=0`, `cost_usd=$0.401742`
- **Key metric:** 30/30 atlas claims audited (automated LLM, not human): 22 agree, 6 disagree, 2 unsure (78.6% scored agreement, 9 over-claims flagged, 100% verified quotes)
- **Audit disclosure:** `gemini-4-carbon (automated LLM audit, not human)` (`docs/gemini/validation.md` remains untouched for human labeller Ivar)
- **Committed files:** `audit.json`, `meta.json`, `summary.md`
