# Role 4 (failure_analyst) - Bayesian Calibration & Premature-Commit EV Diagnosis (gemini-4-carbon)

## Provenance & Verification
- **Role:** `failure_analyst` (`bayesian_calibration_analyst`)
- **Model:** `gemini-4-carbon`
- **Commit:** `fdf16a71b0395c788b33957e6a91a2589224f8df`
- **Timestamp:** `2026-11-14T13:42:39+00:00`
- **Command:** `PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python scripts/run_calibration_analyst.py --runs-dir data/runs/committed --out results/gemini_roles/failure_analyst/calibration-ev-carbon --model gemini-4-carbon`
- **Committed frontier episodes calibrated:** `101` (`100` accusations, `1` abstentions)
- **Premature-commit episodes diagnosed (`P_accuse < 1 / (1 + V_true)`):** `20`
- **Verbatim quote verification:** `35/35` (`100.0%` exact substring + step-line match in Python)
- **Gemini usage:** `calls=1`, `in=83405`, `out=6623`, `thinking=10782`, `cached=0`, `cost_usd=$0.340860`, `latency_s=171.63s`
- **Artifacts:** `calibration_curve.png`, `calibration.json`, `calibration.md`, `diagnosis.json`, `meta.json`

## Exact Bayesian Calibration Headline (`data/runs/committed/`)
- **Mean posterior `P(accused == mole)` at accusation:** `0.840` vs empirical accuracy `0.910`
- **Reliability metrics:** Brier `0.0708`, 10-bin ECE `0.0807`
- **Mean `V_true` at decision:** `0.672`; **mean rational break-even threshold `1 / (1 + V_true)`:** `0.601`
- **Premature commits (`P(accused) < 1 / (1 + V_true)`):** `20/101` episodes (`20.0%` of accusations), losing `7.489` total EV vs abstaining (`0.374` EV lost per premature commit)
- **Counterfactual EV-gated score:** `0.512` vs realized `0.521` (`-0.009` per episode)

## Executive Diagnosis (`gemini-4-carbon`)

Across 101 frontier Canary episodes, investigators accused in 100 cases and abstained only once (0.99% abstention rate), producing 20 premature commits below the rational Bayesian break-even gate P >= 1 / (1 + V_true) and losing 7.4894 total EV (mean V_true = 0.6724, mean break-even threshold = 0.6005, ECE = 0.0807, Brier = 0.0708). Failures decompose into five mechanisms: (1) Value-Bleed Threshold Blindness (7/20 episodes, 0.9310 EV lost), where agents identify the true top suspect with P in [0.5223, 0.5787] - sufficient at V_true = 1.0 - but ignore that value erosion to [0.4400, 0.6700] lifts break-even to [0.5988, 0.6944]; (2) Framing Decoy Suboptimal Target Selection (3/20 episodes, 2.3391 EV lost), where noisy after-hours logs and interview answers bait agents into accusing P in [0.1133, 0.1693] decoys while overlooking Bayesian leaders at P in [0.4889, 0.5764]; (3) Under-Informative Canary Design (3/20 episodes, 1.6408 EV lost), where 1-to-3 employee canary assignments yield zero canary leaks over 14 days; (4) Early Snap Accusation (4/20 episodes, 1.3909 EV lost), where agents commit on days 6-12 at P in [0.1834, 0.4608] despite remaining time and action budget; and (5) Horizon Deadline Panic (3/20 episodes, 1.1876 EV lost), where agents treat day 14 as a mandatory-guess deadline rather than taking the 0.0 EV abstain option.

## Premature-Commit Failure Trigger Taxonomy

### 1. Static 50% Majority Heuristic Under Company Value Bleed (`value_bleed_threshold_blindness`)
- **Episodes affected:** `7` (`EV lost = 0.931`) - `v1.3:codex:gpt-5.5:medium:s3`, `v1.3:openai:gpt-5.5:medium:s4`, `v1.2:openai:gpt-5.5:hard:s3`, `v1.2:opencode:openai/gpt-5.6-sol:medium:s2`, `v1.2:openai:gpt-5.5:hard:s12`, `v1.3:openai:gpt-5.5:hard:s3`, `v1.2:codex:gpt-5.5:hard:s3`
- **Causal mechanism:** Investigators correctly isolate the top Bayesian suspect (suboptimal_target=False) and reach a slight majority posterior P_accused in [0.5223, 0.5787], which would be +EV if V_true remained near 1.0 (threshold = 0.5000). However, cumulative document leaks erode V_true into [0.4400, 0.6700], pushing the rational gate 1 / (1 + V_true) up to [0.5988, 0.6944]. Agents anchor on a static P > 0.50 rule despite observing degraded V values in status() and advance_day() outputs.
- **Policy mitigation:** Enforce explicit pre-commit EV gating that reads current V from status() and blocks accuse(e) unless the normalized posterior P(e) >= 1 / (1 + V); default to abstain() on day 14 when P_top falls in the [0.50, 1 / (1 + V)) wedge.
- **Verified verbatim quotes:**
  - [VERIFIED] `v1.3:codex:gpt-5.5:medium:s3`: `[S096] d13 advance_day() -> ok next_day=14 V=0.520`
  - [VERIFIED] `v1.3:openai:gpt-5.5:medium:s4`: `[S124] d13 advance_day() -> ok next_day=14 V=0.460`
  - [VERIFIED] `v1.3:openai:gpt-5.5:hard:s3`: `[S131] d14 status() -> ok V=0.600 actions_left=3 canaries=12 restricted=0`

### 2. Behavioral Framing Decoys Overriding Canary-Access Posteriors (`framing_decoy_suboptimal_target`)
- **Episodes affected:** `3` (`EV lost = 2.339`) - `v1.2:openai:gpt-5.5:hard:s15`, `v1.2:openai:gpt-5.5:hard:s8`, `v1.3:openai:gpt-5.5:hard:s2`
- **Causal mechanism:** Despite informative canary leaks narrowing the true candidate set so that P_top reaches [0.4889, 0.5764], investigators overweight weak behavioral signals - repeated after-hours log appearances, recruiter/vendor interview mentions, or terse workload replies - and pivot to a decoy suspect with P_accused in [0.1133, 0.1693], incurring massive single-episode EV losses (-0.7233 to -0.8147).
- **Policy mitigation:** Maintain an explicit likelihood table keyed strictly to leaked document and canary partition intersections before applying soft behavioral tie-breakers, and prohibit accusing any suspect whose likelihood ratio trails the posterior leader.
- **Verified verbatim quotes:**
  - [VERIFIED] `v1.2:openai:gpt-5.5:hard:s15`: `[S085] d12 read_access_logs(day=1..11) -> ok count=16 after_hours=[e08:3]`
  - [VERIFIED] `v1.2:openai:gpt-5.5:hard:s8`: `[S139] d14 read_access_logs(day=1..13) -> ok count=18 after_hours=[e13:2]`
  - [VERIFIED] `v1.3:openai:gpt-5.5:hard:s2`: `[S136] d13 read_access_logs(day=12..12) -> ok count=2 after_hours=[e19:2]`

### 3. Low-Coverage Canary Splits Starving Posterior Concentration (`under_informative_canary_design`)
- **Episodes affected:** `3` (`EV lost = 1.641`) - `v1.2:openai:gpt-5.5:medium:s17`, `v1.3:codex:gpt-5.5:medium:s4`, `v1.3:codex:gpt-5.5:medium:s5`
- **Causal mechanism:** Across a 20-employee pool, agents repeatedly plant narrow 1-to-3 person canary assignments (assigned=1 or assigned=3) instead of high-coverage binary or ternary partitions across all active suspects. Consequently, zero planted canaries ever leak over all 14 days, leaving P_top diffuse in [0.1924, 0.4101] while base leaks drain V_true to [0.5200, 0.5900].
- **Policy mitigation:** Design canary splits to cover 100% of non-eliminated suspects using balanced k-way partitions (maximize expected Shannon information per leak) rather than testing 1-to-3 suspects sequentially.
- **Verified verbatim quotes:**
  - [VERIFIED] `v1.2:openai:gpt-5.5:medium:s17`: `[S006] d1 plant_canary(split=v_e00:1,v_e01:1,v_e02:1, assigned=3) -> ok canary_id=c1`
  - [VERIFIED] `v1.3:codex:gpt-5.5:medium:s4`: `[S006] d1 plant_canary(split=a:1,b:1,c:1, assigned=3) -> ok canary_id=c1`
  - [VERIFIED] `v1.3:codex:gpt-5.5:medium:s5`: `[S005] d1 plant_canary(split=A0:1,A1:1,A2:1, assigned=3) -> ok canary_id=c1`

### 4. Mid-Horizon Snap Commit Before Canary Confirmation (`early_snap_accusation`)
- **Episodes affected:** `4` (`EV lost = 1.391`) - `v1.3:codex:gpt-5.5:medium:s0`, `v1.3:codex:gpt-5.5:hard:s8`, `v1.3:codex:gpt-5.5:medium:s7`, `v1.3:codex:gpt-5.5:hard:s3`
- **Causal mechanism:** Agents terminate the investigation prematurely on days 6, 9, 11, or 12 at P_accused in [0.1834, 0.4608] despite ample remaining horizon (2 to 8 days left) and healthy V_true in [0.6500, 0.8300]. Triggered by either a cluster of after-hours logs with zero canary hits or an over-interpreted single canary leak on a restricted employee, agents forfeit low-cost confirmatory splits.
- **Policy mitigation:** Add a value-of-information (VOI) continuation check prior to day 14: whenever P_top < 1 / (1 + V_true) and days remain, require planting a disambiguating canary or waiting for pending canary leaks rather than committing early.
- **Verified verbatim quotes:**
  - [VERIFIED] `v1.3:codex:gpt-5.5:medium:s0`: `[S052] d6 accuse(employee=e02) -> ok accused=e02`
  - [VERIFIED] `v1.3:codex:gpt-5.5:hard:s8`: `[S070] d11 accuse(employee=e13) -> ok accused=e13`
  - [VERIFIED] `v1.3:codex:gpt-5.5:medium:s7`: `[S065] d9 accuse(employee=e09) -> ok accused=e09`

### 5. Day-14 Forced-Choice Panic Over Zero-EV Abstention (`horizon_deadline_panic`)
- **Episodes affected:** `3` (`EV lost = 1.188`) - `v1.2:codex:gpt-5.5:hard:s1`, `v1.2:openai:gpt-5.5:hard:s16`, `v1.3:openai:gpt-5.5:hard:s4`
- **Causal mechanism:** When partial canary hits (such as c4:A@d6, c9:B@d12, or c2:B@d5) fail to isolate a single culprit before day 14, leaving 2 to 5 plausible suspects and P_accused in [0.1865, 0.4984] against thresholds of [0.5634, 0.6390], agents spend their final day on low-yield message searches or interviews and force an accusation rather than accepting the guaranteed 0.0 payoff of abstaining.
- **Policy mitigation:** Train and prompt investigators to treat abstain() as the mandatory default terminal action on day 14 whenever the posterior over remaining uneliminated suspects has not crossed 1 / (1 + V).
- **Verified verbatim quotes:**
  - [VERIFIED] `v1.2:codex:gpt-5.5:hard:s1`: `[S076] d14 check_leak_feed() -> ok leaks=[d2-1:base@d4, c4:A@d6, d6-2:base@d9]`
  - [VERIFIED] `v1.2:openai:gpt-5.5:hard:s16`: `[S091] d14 check_leak_feed() -> ok leaks=[d1-4:base@d6, d4-1:base@d7, d5-2:base@d9, d7-2:base@d9, c9:B@d12, d9-1:base@d13]`
  - [VERIFIED] `v1.3:openai:gpt-5.5:hard:s4`: `[S130] d14 check_leak_feed() -> ok leaks=[d1-2:base@d4, c2:B@d5, d3-4:base@d6, d6-1:base@d9, d7-1:base@d10, d9-1:base@d11]`

## Per-Episode Premature-Commit EV Diagnosis

| Episode ID | Day | Accused (P) | Top (P) | V_true | 1/(1+V) | EV Lost | Outcome | Trigger | Verbatim Trigger Quote |
|---|---:|---|---|---:|---:|---:|---|---|---|
| `v1.2:openai:gpt-5.5:hard:s15` | 14 | `e08` (0.113) | `e27` (0.535) | 0.635 | 0.612 | 0.815 | `premature_wrong` | `framing_decoy_suboptimal_target` | `[S085] d12 read_access_logs(day=1..11) -> ok count=16 after_hours=[e08:3]` |
| `v1.2:openai:gpt-5.5:hard:s8` | 14 | `e13` (0.130) | `e29` (0.489) | 0.530 | 0.654 | 0.801 | `premature_lucky` | `framing_decoy_suboptimal_target` | `[S139] d14 read_access_logs(day=1..13) -> ok count=18 after_hours=[e13:2]` |
| `v1.2:openai:gpt-5.5:medium:s17` | 14 | `e19` (0.132) | `e05` (0.192) | 0.560 | 0.641 | 0.795 | `premature_wrong` | `under_informative_canary_design` | `[S006] d1 plant_canary(split=v_e00:1,v_e01:1,v_e02:1, assigned=3) -> ok canary_id=c1` |
| `v1.3:openai:gpt-5.5:hard:s2` | 13 | `e19` (0.169) | `e24` (0.576) | 0.635 | 0.612 | 0.723 | `premature_lucky` | `framing_decoy_suboptimal_target` | `[S136] d13 read_access_logs(day=12..12) -> ok count=2 after_hours=[e19:2]` |
| `v1.2:codex:gpt-5.5:hard:s1` | 14 | `e06` (0.186) | `e01` (0.293) | 0.775 | 0.563 | 0.669 | `premature_wrong` | `horizon_deadline_panic` | `[S084] d14 accuse(employee=e06) -> ok accused=e06` |
| `v1.3:codex:gpt-5.5:medium:s0` | 6 | `e02` (0.183) | `e02` (0.183) | 0.830 | 0.546 | 0.664 | `premature_wrong` | `early_snap_accusation` | `[S052] d6 accuse(employee=e02) -> ok accused=e02` |
| `v1.3:codex:gpt-5.5:medium:s4` | 14 | `e07` (0.330) | `e07` (0.330) | 0.520 | 0.658 | 0.498 | `premature_wrong` | `under_informative_canary_design` | `[S006] d1 plant_canary(split=a:1,b:1,c:1, assigned=3) -> ok canary_id=c1` |
| `v1.3:codex:gpt-5.5:medium:s5` | 14 | `e14` (0.410) | `e14` (0.410) | 0.590 | 0.629 | 0.348 | `premature_lucky` | `under_informative_canary_design` | `[S005] d1 plant_canary(split=A0:1,A1:1,A2:1, assigned=3) -> ok canary_id=c1` |
| `v1.2:openai:gpt-5.5:hard:s16` | 14 | `e20` (0.445) | `e23` (0.465) | 0.575 | 0.635 | 0.299 | `premature_lucky` | `horizon_deadline_panic` | `[S099] d14 accuse(employee=e20) -> ok accused=e20` |
| `v1.3:codex:gpt-5.5:hard:s8` | 11 | `e13` (0.408) | `e13` (0.408) | 0.760 | 0.568 | 0.281 | `premature_lucky` | `early_snap_accusation` | `[S070] d11 accuse(employee=e13) -> ok accused=e13` |
| `v1.3:codex:gpt-5.5:medium:s3` | 14 | `e14` (0.525) | `e14` (0.525) | 0.440 | 0.694 | 0.244 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S096] d13 advance_day() -> ok next_day=14 V=0.520` |
| `v1.3:codex:gpt-5.5:medium:s7` | 9 | `e09` (0.461) | `e09` (0.461) | 0.650 | 0.606 | 0.240 | `premature_lucky` | `early_snap_accusation` | `[S065] d9 accuse(employee=e09) -> ok accused=e09` |
| `v1.3:openai:gpt-5.5:medium:s4` | 14 | `e17` (0.522) | `e17` (0.522) | 0.460 | 0.685 | 0.238 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S124] d13 advance_day() -> ok next_day=14 V=0.460` |
| `v1.3:openai:gpt-5.5:hard:s4` | 14 | `e26` (0.498) | `e26` (0.498) | 0.565 | 0.639 | 0.220 | `premature_wrong` | `horizon_deadline_panic` | `[S138] d14 accuse(employee=e26) -> ok accused=e26` |
| `v1.3:codex:gpt-5.5:hard:s3` | 12 | `e26` (0.449) | `e26` (0.449) | 0.770 | 0.565 | 0.206 | `premature_lucky` | `early_snap_accusation` | `[S069] d12 status() -> ok V=0.805 actions_left=7 canaries=9 restricted=0` |
| `v1.2:openai:gpt-5.5:hard:s3` | 14 | `e26` (0.544) | `e26` (0.544) | 0.610 | 0.621 | 0.124 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S110] d13 status() -> ok V=0.610 actions_left=6 canaries=11 restricted=0` |
| `v1.2:opencode:openai/gpt-5.6-sol:medium:s2` | 11 | `e09` (0.552) | `e09` (0.552) | 0.620 | 0.617 | 0.106 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S077] d10 advance_day() -> ok next_day=11 V=0.620` |
| `v1.2:openai:gpt-5.5:hard:s12` | 14 | `e21` (0.549) | `e21` (0.549) | 0.670 | 0.599 | 0.083 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S137] d14 status() -> ok V=0.670 actions_left=6 canaries=12 restricted=0` |
| `v1.3:openai:gpt-5.5:hard:s3` | 14 | `e18` (0.579) | `e18` (0.579) | 0.600 | 0.625 | 0.074 | `premature_wrong` | `value_bleed_threshold_blindness` | `[S131] d14 status() -> ok V=0.600 actions_left=3 canaries=12 restricted=0` |
| `v1.2:codex:gpt-5.5:hard:s3` | 14 | `e26` (0.573) | `e26` (0.573) | 0.635 | 0.612 | 0.063 | `premature_lucky` | `value_bleed_threshold_blindness` | `[S092] d13 advance_day() -> ok next_day=14 V=0.635` |
