# Multimodal Belief and Value-Bleed Chart Forensics (gemini-4-carbon)

- **Role:** `multimodal_evidence` (`belief_chart_forensics`)
- **Model:** `gemini-4-carbon` via `google.genai.types.Part.from_bytes(mime_type="image/png")`
- **Commit:** `42341129d027e54e5bf58e44f3e64690295b75c5`
- **Timestamp:** `2026-11-14T13:22:00+00:00`
- **Ledger run_id:** `multimodal-forensics-20261114T132200Z`
- **Replay rules:** `canary.rules.tiers_version("v1.3")`
- **Charts analyzed:** `6` (3 wrong/premature accusations + 3 high-scoring episodes from `data/runs/committed/v1.3/`)
- **Visual EV-threshold accuracy:** `6/6` (`1.000`)
- **Accusation-day accuracy (|est - actual| <= 1):** `6/6` (`1.000`; exact match `6/6`)
- **Hidden-bleed gap accuracy:** `6/6` (`1.000`)
- **Total Gemini usage:** `6` calls, `10812` input tokens, `1295` output tokens, `2065` thinking tokens, `$0.055224` USD, `114.71` s

## Visual Reading vs Solver Ground Truth

| Chart | Cohort | Agent / Tier / Seed | Score | GT P(accused) vs 1/(1+V) | GT Below EV | Gemini Below EV | Actual Day | Gemini Day | GT Bleed Gap | Gemini Bleed | Primary Pattern |
|---|---|---|---:|---|---|---|---|---:|---|---|---|
| `charts/ep_0.png` | wrong_or_premature | `codex:gpt-5.5` / `medium` / `0` | -1.000 | 0.183 vs 0.546 | `True` | `True` | 6 | 6 | `True` (0.040) | `True` | `premature_early_accusation` |
| `charts/ep_1.png` | wrong_or_premature | `codex:gpt-5.5` / `medium` / `4` | -1.000 | 0.330 vs 0.658 | `True` | `True` | 14 | 14 | `True` (0.040) | `True` | `horizon_forced_guess` |
| `charts/ep_2.png` | wrong_or_premature | `openai:gpt-5.5` / `hard` / `4` | -1.000 | 0.498 vs 0.639 | `True` | `True` | 14 | 14 | `True` (0.070) | `True` | `horizon_forced_guess` |
| `charts/ep_3.png` | high_scoring | `codex:gpt-5.5` / `medium` / `1` | +0.840 | 1.000 vs 0.543 | `False` | `False` | 5 | 5 | `False` (0.000) | `False` | `none_justified_accusation` |
| `charts/ep_4.png` | high_scoring | `openai:gpt-5.5` / `medium` / `2` | +0.830 | 1.000 vs 0.546 | `False` | `False` | 6 | 6 | `False` (0.000) | `False` | `none_justified_accusation` |
| `charts/ep_5.png` | high_scoring | `openai:gpt-5.5` / `hard` / `5` | +0.735 | 0.852 vs 0.576 | `False` | `False` | 11 | 11 | `True` (0.070) | `True` | `none_justified_accusation` |

## Per-Chart Multimodal Forensic Diagnoses

### Episode 0 (`charts/ep_0.png`): `codex:gpt-5.5` on `medium` seed `0` (wrong_or_premature)
- **Ground truth:** accused `e02` on day `6` (correct=`False`, score=`-1.000`), `P(accused)=0.183` vs `1/(1+V)=0.546` (`below_ev=True`), `max_bleed_gap=0.040` (`bleed=True`), canaries planted=`5`.
- **Gemini visual output:** `accused_below_ev_threshold=True` (match=`True`), `estimated_accuse_day=6` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=True` (match=`True`), pattern=`premature_early_accusation`.
- **Visual diagnosis:** In Panel 1, the Bayesian posterior remains weakly distributed across roughly seven suspects (e02, e05, e06, e11, e15, e16, and e18) through Day 6 rather than concentrating on a single mole. Panel 2 shows consistent daily canary deployments from Day 1 to Day 5 alongside moderate value decay and intermittent shaded hidden bleed gaps on Days 2-3 and Days 5-6 where known_V exceeds true_V. In Panel 3, the agent triggers an early accusation on Day 6 at a posterior probability near 0.18, lying far below the rational EV break-even threshold of roughly 0.55 despite ample remaining horizon.

### Episode 1 (`charts/ep_1.png`): `codex:gpt-5.5` on `medium` seed `4` (wrong_or_premature)
- **Ground truth:** accused `e07` on day `14` (correct=`False`, score=`-1.000`), `P(accused)=0.330` vs `1/(1+V)=0.658` (`below_ev=True`), `max_bleed_gap=0.040` (`bleed=True`), canaries planted=`12`.
- **Gemini visual output:** `accused_below_ev_threshold=True` (match=`True`), `estimated_accuse_day=14` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=True` (match=`True`), pattern=`horizon_forced_guess`.
- **Visual diagnosis:** In Panel 1, posterior probability remains split across four remaining candidates (e07, e13, e15, and e17) from Day 7 onward, peaking near 0.33 without isolating a single mole. Panel 2 shows steady canary deployments from Day 1 through Day 12 alongside gradual value decay from 0.99 to 0.52 and small intermittent hidden bleed gaps where known_V exceeds true_V. In Panel 3, the agent reaches the final Day 14 horizon and makes an accusation at P(accused) near 0.33, well below the rational EV threshold 1/(1+V) near 0.66.

### Episode 2 (`charts/ep_2.png`): `openai:gpt-5.5` on `hard` seed `4` (wrong_or_premature)
- **Ground truth:** accused `e26` on day `14` (correct=`False`, score=`-1.000`), `P(accused)=0.498` vs `1/(1+V)=0.639` (`below_ev=True`), `max_bleed_gap=0.070` (`bleed=True`), canaries planted=`12`.
- **Gemini visual output:** `accused_below_ev_threshold=True` (match=`True`), `estimated_accuse_day=14` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=True` (match=`True`), pattern=`horizon_forced_guess`.
- **Visual diagnosis:** Panel 1 shows the Bayesian posterior splitting mainly between suspects e26 and e28 from Day 5 onward without fully resolving a single culprit by Day 14. In Panel 2, frequent canary deployments across Days 1 through 12 keep known_V relatively close to true_V, though small shaded hidden bleed gaps still appear as company value steadily erodes below 0.60. Panel 3 shows the top-suspect posterior plateauing near 0.50 and failing to cross the rising 1/(1+V) rational EV threshold, resulting in a sub-threshold accusation forced at the Day 14 horizon.

### Episode 3 (`charts/ep_3.png`): `codex:gpt-5.5` on `medium` seed `1` (high_scoring)
- **Ground truth:** accused `e02` on day `5` (correct=`True`, score=`+0.840`), `P(accused)=1.000` vs `1/(1+V)=0.543` (`below_ev=False`), `max_bleed_gap=0.000` (`bleed=False`), canaries planted=`4`.
- **Gemini visual output:** `accused_below_ev_threshold=False` (match=`True`), `estimated_accuse_day=5` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=False` (match=`True`), pattern=`none_justified_accusation`.
- **Visual diagnosis:** In Panel 1, Bayesian posterior probability progressively narrows across subsets of suspects before concentrating entirely on suspect e02 at 1.0 by Day 5. Panel 2 shows consistent canary deployments across Days 1 through 4, with known_V and true_V coinciding completely at every step from 0.99 down to 0.84 without any hidden bleed gap. In Panel 3, the accusation occurs on Day 5 just as the accused posterior hits certainty at 1.0, sitting well above the rational EV threshold curve near 0.54.

### Episode 4 (`charts/ep_4.png`): `openai:gpt-5.5` on `medium` seed `2` (high_scoring)
- **Ground truth:** accused `e09` on day `6` (correct=`True`, score=`+0.830`), `P(accused)=1.000` vs `1/(1+V)=0.546` (`below_ev=False`), `max_bleed_gap=0.000` (`bleed=False`), canaries planted=`5`.
- **Gemini visual output:** `accused_below_ev_threshold=False` (match=`True`), `estimated_accuse_day=6` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=False` (match=`True`), pattern=`none_justified_accusation`.
- **Visual diagnosis:** Panel 1 shows Bayesian posterior probability progressively narrowing across days 3 to 5 before concentrating completely on suspect e09 at day 6. In Panel 2, canaries are deployed consistently from day 1 through day 5, keeping known_V and true_V completely aligned with zero hidden bleed gap as company value declines from 0.99 to 0.83. Panel 3 confirms a justified accusation on day 6, where the accused suspect posterior reaches 1.0 and sits well above the rational EV threshold of roughly 0.55.

### Episode 5 (`charts/ep_5.png`): `openai:gpt-5.5` on `hard` seed `5` (high_scoring)
- **Ground truth:** accused `e19` on day `11` (correct=`True`, score=`+0.735`), `P(accused)=0.852` vs `1/(1+V)=0.576` (`below_ev=False`), `max_bleed_gap=0.070` (`bleed=True`), canaries planted=`9`.
- **Gemini visual output:** `accused_below_ev_threshold=False` (match=`True`), `estimated_accuse_day=11` (abs_err=`0`, within_1=`True`), `hidden_bleed_gap_present=True` (match=`True`), pattern=`none_justified_accusation`.
- **Visual diagnosis:** In Panel 1, Bayesian posterior probability narrows onto suspects e15 and e19 by Day 5 before concentrating strongly above 0.80 on suspect e19 from Day 8 through Day 11. Panel 2 shows consistent canary deployments from Day 1 to Day 9 alongside intermittent shaded hidden bleed gaps on Days 3 to 5, Days 7 to 8, and Day 11 as company value declines to roughly 0.74. In Panel 3, the top-suspect posterior crosses the rational EV threshold 1/(1+V) on Day 6, resulting in a well-supported accusation on Day 11 with P(accused) near 0.85 and clearly above the ~0.58 break-even threshold.
