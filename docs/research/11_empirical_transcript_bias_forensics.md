# 11. Empirical Frontier Transcript Bias Forensics: Multi-Model Replay Signatures, Literature Grounding, and Automated Bias Diagnostics

**Squad:** `research` (`canary-research-w7`)  
**Baseline commit:** `713f3ddd` (`origin/fr8/canary/research`, synced with `origin/justSilas@58716742`; rules `v1.4`, frozen hash `a8f99c2537c91d72`; historical `v1.3` frozen hash `8df71cf570bb48bc`)  
**Reproducible Forensic Script:** `python scripts/audit_transcript_biases.py` (`0` API calls, `~2.0 s` full replay + `107`-point cross-verification against `results/failure_analysis_v1.4.json`)  
**Companion Monographs:** [Flagship Synthesis](../research-deception.md) | [01. Deception Detection](./01_deception_detection.md) | [02. Insider Threat](./02_insider_threat.md) | [03. Leak Hunts & Group Testing](./03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](./04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](./06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer & Gate B Post-Mortem](./07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](./08_mole_rl_stackelberg_and_catchability.md)  
**Primary Benchmark Evidence:** [Gap Report](../reports/gap.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Below-Break-Even Spotlight](../reports/failure_gallery_breakeven.md) | [Difficulty Audit](../DIFFICULTY.md)

---

## 1. Executive Thesis: Deterministic Cognitive-Bias Forensics Across `135` Replayed Episodes

Do frontier LLM investigators lose to Canary's exact Bayesian `SolverPolicy` because they misunderstand tool schemas or hidden mechanics, or because they reproduce classic human cognitive biases under partial observability, low prior base rates (`1 / 40`), and eroding company value `V`?

To answer this question without post-hoc narrative guesswork, `scripts/audit_transcript_biases.py` deterministically replays and cross-verifies **`135` committed episodes** (`0` live LLM calls, `107 / 107` exact scalar and set-identity checks passing against `results/failure_analysis_v1.4.json`):
- **Primary `v1.4` Hard Cohorts (`a8f99c2537c91d72`, `n = 30` post-hoc locked paired dev seeds `0-29`, locked in `671ed96` `28 s` after `8fd4dec`):** OpenCode `gemini-4-carbon` over MCP (`30` episodes + `30` reasoning transcripts), In-Process `gemini-4-carbon` (`30` episodes + `30` thought-block transcripts), and `SolverPolicy` (`30` paired episodes), plus `v1.4` Hard extension seeds `[34, 37]` (`n = 2`, pooled `n = 32`) and `v1.4` Medium context (`n = 30` per cohort).
- **Cross-Model `v1.4` Grok Contrast (`docs/reports/grok-agent/`):** `5` `hard` and `5` `medium` MCP tool-call ledgers and post-episode rationales (`seeds 900000-900004`).
- **Historical `v1.3` OpenAI `gpt-5.5` Contrast (`8df71cf570bb48bc`, `data/runs/committed/v1.3/`):** Codex `gpt-5.5` over MCP (`11` `medium` + `11` `hard` episodes) and In-Process `gpt-5.5` (`9` `medium` + `8` `hard` episodes).

Four empirical findings establish the behavioral spine of Canary's frontier gap:

1. **Demeanor Interview Fixation Crowds Out Active Canary Design (`68.03` vs `0.00` Interviews/Ep).** Confirming Hartwig & Bond (2011) and Bond & DePaulo (2006), explicit disclosure of `interview_lr = 1.2` and `p_evasive_innocent = 0.2` in `Env.instruction()` does not deter `gemini-4-carbon` from spending **`68.03` interviews/episode** in OpenCode (`57.27` in-process vs `0.00` in `SolverPolicy`), of which **`72.1%` (`1,471 / 2,039`)** are repeat interviews of already-questioned employees. Each `v1.4` hard `interview` yields **`0.00477` nats** (`d = 0.097`), whereas one leaked 3-variant `plant_canary` (`max_variants = 3`, `fingerprint_accuracy = 0.95`) yields **`0.86544` nats** (`181.4x` more mutual information). On **`242` of the `303` under-planted days** (`79.9%`), OpenCode `gemini-4-carbon` exhausted all `8 / 8` daily investigative actions (`1,503` of them on interviews), delaying its first canary to **Day `3.0`** (vs Day `1.0` for `SolverPolicy`) and planting only **`8.5 +/- 1.3` canaries** (`31.5%` capacity vs `SolverPolicy` `14.1 +/- 1.8` or `66.7%`). Crucially, `invalid_calls` average `0.93`/episode (`28 / 3,841 = 0.73%`), and canary sizing matches `SolverPolicy` (`10.1` recipients and `3.0` variants vs `9.9` and `3.0`), ruling out syntax or `careful_mole` confusion (`docs/DIFFICULTY.md` W1).
2. **Base-Rate Neglect Turns Un-Isolated Consistent Sets into `9 / 9` (`100.0%`) `argmax(after_hours)` Guesses.** Consistent with Axelsson (2000) and Kahneman & Tversky (1973), passive `after_hours` access logs on `v1.4` hard (`mole = 0.30/d`, `decoy = 1.10/d`, `38` plain innocents `= 0.126316/d` each, company total `= 6.20/d`) carry a theoretical single-event Bayesian `PPV` of **`4.84%`** (`5.88%` excluding `decoy`), matched by OpenCode `gemini-4-carbon`'s empirical observed `PPV` of **`4.37%`** (`95 / 2,175` `after_hours` rows; `5.32%` ex-decoy). Because canary under-planting leaves `|consistent_set| >= 2` in **`9 / 29` (`31.0%`)** OpenCode accusations (`seeds 3, 5, 7, 8, 14, 15, 18, 20, 23`, costing `+3.50 V` gross / `+3.39 V` net expected value), `audit_transcript_biases.py` proves that in **`9 / 9` (`100.0%`)** of those un-isolated OpenCode accusations (and **`6 / 6` = `100.0%`** in In-Process `gemini-4-carbon`), Gemini accused the **unique strict `argmax` of observed `after_hours` log counts** inside the consistent set - directly causing both non-flip `-1.00` wrong accusations (`seed 15`: innocent `e34` with `3` `after_hours` vs mole `e37` with `1`; `seed 18`: innocent `e29` with `6` `after_hours` vs mole `e27` with `2`).
3. **Verbalized Overprecision (`+22.94 pp`) Drives Loss-Domain Below-Break-Even Horizon Gambles (`-0.9368 V`).** Reconciling Moore & Healy's (2008) *overprecision* with Kahneman & Tversky's (1979) *loss-domain risk seeking*, `gemini-4-carbon` knows the exact break-even formula `P*(V) = 1 / (1 + V)` (using it to abstain on `seed 11` at `P = 42.9%` and citing break-even EV in `25 / 30` in-process transcripts). Yet across the unresolved OpenCode commitments (`|C_acc| >= 2`), dropping unleaked-canary negative evidence and double-counting unframed `after_hours` ratios inflates verbalized final-rationale confidence by **`+22.94` percentage points** above exact Bayesian `SolverPolicy` posteriors (`seed 18`: `89.0%` claimed vs `62.72%` exact; `seed 23`: `82.0%` claimed vs `45.17%` exact), inducing **`3` negative-EV horizon shots** (`seeds 5, 18, 23`, `+1.64 V` accusation-penalty gap vs `0 / 30` in `SolverPolicy`).
4. **Distinct Model Families Fail via Distinct Human Bias Profiles.** Cross-model transcript auditing demonstrates that Canary is not a single-model quirk:
   - **`gemini-4-carbon` (`v1.4` Hard `n = 30`):** High demeanor-interview crowding (`68.03`/ep OpenCode, `57.27`/ep in-process) -> thin commitment sets (`1.83` mean size) -> `9 / 9` `after_hours` tie-breaking + `+22.94 pp` overprecision (`0.322 +/- 0.199` vs `0.499 +/- 0.119`, `65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted).
   - **Grok (`v1.4` Hard `n = 5`, Medium `n = 5`):** Near-zero interview fixation (`0.60`/ep `hard`, `3.60`/ep `medium`) and explicit break-even abstention (`hard-900000`: abstains at `P ~ 53% < 0.70`), but relies on costly productivity-bleeding `restrict_access` experiments (`1.80`/ep `hard`, `1.40`/ep `medium` vs `0.00` in `SolverPolicy`).
   - **Codex & In-Process `gpt-5.5` (`v1.3` Historical `8df71cf570bb48bc`):** Moderate interviewing (`8.73-11.64`/ep Codex MCP; `6.38-7.78`/ep in-process), heavy log/message scanning (`33.75` log reads/ep and `17.50` message calls/ep in-process `hard`), **`0` abstentions across `39 / 39` episodes**, and representativeness-driven premature accusations on `"statistically loud"` `after_hours` outliers (`Codex medium seeds 0, 4` at `P = 0.183, 0.330` -> `-1.00` each, `34%` luck-adjusted of `SolverPolicy`).

Section 2 grounds ten peer-reviewed studies with live HTTP-200 links and verbatim blockquotes. Section 3 presents the complete replay-verified forensic tables produced by `scripts/audit_transcript_biases.py`. Section 4 specifies two concrete, zero-protected-path proposals: **`P11.1` (`gen_confirmation_echo_summary` in `canary/social/biases.py`, `LLR = 0.0000` nats)** and **`P11.2` (automated cognitive-bias tagger integration in `canary/analysis/tags.py` + catchability-verified `MoleStrategy` JSON)**.

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Citations and Verbatim Quotes)

### 2.1 Cue Weakness vs Cue Ignorance in Deception Judgment: Hartwig & Bond (2011)

- **Citation:** Hartwig, M., & Bond, C. F., Jr. (2011). Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.
- **Live Verified Links:** https://doi.org/10.1037/a0023589 | https://api.crossref.org/works/10.1037/a0023589
- **Sample & Design:** Four Brunswikian lens-model meta-analyses synthesizing `66` behavioral cues across `153` samples, testing whether human lie-catchers fail because they rely on invalid cue beliefs or because passive behavioral cues possess intrinsically weak diagnostic effect sizes.
- **Verbatim Quotes (Abstract):**
> "Meta-Analysis 1 investigated perceived cues to deception by correlating 66 behavioral cues in 153 samples with deception judgments. People strongly associate deception with impressions of incompetence (r = .59) and ambivalence (r = .49). Contrary to self-reports, eye contact is only weakly correlated with deception judgments (r = -.15). Cues to perceived deception were then compared with cues to actual deception. The results show a substantial covariation between the 2 sets of cues (r = .59 in Meta-Analysis 2, r = .72 in Meta-Analysis 3)."
> "In conclusion, contrary to previous assumptions, people rarely rely on the wrong cues. Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."
- **Relevance to Canary Transcripts:** Explains the central paradox of `gemini-4-carbon`'s `v1.4` trajectories. `Env.instruction()` explicitly discloses the exact `interview` cue weight (`interview_lr = 1.2`, `p_evasive_innocent = 0.20`), yet OpenCode `gemini-4-carbon` still executes `68.03` interviews/episode (`2,041` total). As Hartwig & Bond prove, knowing exact cue weights cannot extract signal from a `0.00477`-nat passive channel; only active experimental interventions (`plant_canary` at `0.86544` nats/leak) widen behavioral separation between mole and innocent.

### 2.2 Near-Chance Demeanor Accuracy and the Othello Error: Bond & DePaulo (2006)

- **Citation:** Bond, C. F., Jr., & DePaulo, B. M. (2006). Accuracy of Deception Judgments. *Personality and Social Psychology Review*, 10(3), 214-234.
- **Live Verified Links:** https://doi.org/10.1207/s15327957pspr1003_2 | https://api.crossref.org/works/10.1207/s15327957pspr1003_2
- **Sample & Design:** Meta-analysis across `206` documents and `24,483` judges classifying truthful and deceptive statements in real time without external documentary evidence.
- **Verbatim Quotes (Abstract):**
> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges. In relevant studies, people attempt to discriminate lies from truths in real time with no special aids or training. In these circumstances, people achieve an average of 54% correct lie-truth judgments, correctly classifying 47% of lies as deceptive and 61% of truths as nondeceptive."
> "Our meta-analyses reveal that people are more accurate in judging audible than visible lies, that people appear deceptive when motivated to be believed, and that individuals regard their interaction partners as honest."
- **Relevance to Canary Transcripts:** Across OpenCode `gemini-4-carbon`'s `2,039` valid `v1.4` hard interviews, innocent employees produced **`309` evasive answers** (`20.12%` of `1,536` innocent interviews) compared with **`112` evasive answers** from the mole (`22.27%` of `503` mole interviews) - a `2.76 : 1` flood of innocent evasiveness that mirrors Bond & DePaulo's `54%` near-chance ceiling and induces false suspicion whenever an un-isolated suspect happens to draw a benign evasive streak.

### 2.3 Empirical Faintness of Passive Behavioral Cues: DePaulo et al. (2003)

- **Citation:** DePaulo, B. M., Lindsay, J. J., Malone, B. E., Muhlenbruck, L., Charlton, K., & Cooper, H. (2003). Cues to Deception. *Psychological Bulletin*, 129(1), 74-118.
- **Live Verified Links:** https://doi.org/10.1037/0033-2909.129.1.74 | https://api.crossref.org/works/10.1037/0033-2909.129.1.74
- **Sample & Design:** Meta-analytic synthesis of `1,338` independent estimates across `158` behavioral, paralinguistic, and verbal cues (`median |d| = 0.10` across `88` multi-estimate cues).
- **Verbatim Quote (Abstract):**
> "The combined results of 1,338 estimates of 158 cues to deception are reported. Results show that in some ways, liars are less forthcoming than truth tellers, and they tell less compelling tales. They also make a more negative impression and are more tense. Their stories include fewer ordinary imperfections and unusual contents. However, many behaviors showed no discernible links, or only weak links, to deceit."
- **Relevance to Canary Transcripts:** Validates Canary `v1.4` hard's parameterization (`p_evasive_innocent = 0.20`, `p_evasive_mole = 0.24` -> Cohen's `d = 0.097`, Hasselblad-Hedges `d_HH = 0.129`), matching DePaulo et al.'s empirical median `|d| = 0.10` while grounding why disgruntled (`decoy`) or scrutinized innocents look tense without being guilty.

### 2.4 The Base-Rate Fallacy in Audit and Intrusion Logs: Axelsson (2000)

- **Citation:** Axelsson, S. (2000). The Base-Rate Fallacy and the Difficulty of Intrusion Detection. *ACM Transactions on Information and System Security (TISSEC)*, 3(3), 186-205.
- **Live Verified Links:** https://openalex.org/W2156204309 | https://doi.org/10.1145/357830.357849
- **Theoretical Scope:** Bayesian analysis of audit-log and intrusion-detection alarms showing that under low prior incidence (`1 / N`), posterior alarm precision (`PPV`) is dominated by the benign false-alarm rate across `N - 1` legitimate users.
- **Verbatim Quote (Abstract):**
> "Many different demands can be made of intrusion detection systems. An important requirement is that an intrusion detection system be effective; that is, it should detect a substantial percentage of intrusions into the supervised system, while still keeping the false alarm rate at an acceptable level. This article demonstrates that, for a reasonable set of assumptions, the false alarm rate is the limiting factor for the performance of an intrusion detection system."
- **Relevance to Canary Transcripts:** Directly predicts the `2,175` `after_hours` log rows observed by OpenCode `gemini-4-carbon` across `30` `v1.4` hard episodes: `390` (`17.9%`) belong to the framed `decoy`, `1,690` (`77.7%`) belong to the `38` plain innocents, and only **`95` (`4.37%`)** belong to the true mole (`5.32%` after excluding `decoy`, matching theoretical `PPV = 4.84%` / `5.88%`).

### 2.5 Representativeness and Base-Rate Neglect: Kahneman & Tversky (1973)

- **Citation:** Kahneman, D., & Tversky, A. (1973). On the Psychology of Prediction. *Psychological Review*, 80(4), 237-251.
- **Live Verified Links:** https://openalex.org/W1980054641 | https://doi.org/10.1037/h0034747
- **Experimental Scope:** Demonstrates that decision-makers rank hypotheses by *representativeness* (`P(Evidence | Hypothesis)`) while neglecting prior base rates (`1 / N`), reliability attenuation, and order-statistic regression across multi-candidate pools.
- **Verbatim Quotes (Abstract):**
> "By this heuristic, people predict the outcome that appears most representative of the evidence. Consequently, intuitive predictions are insensitive to the reliability of the evidence or to the prior probability of the outcome, in violation of the logic of statistical prediction."
> "It is shown that the ranking of outcomes by likelihood coincides with their ranking by representativeness and that people erroneously predict rare events and extreme values if these happen to be representative. The experience of unjustified confidence in predictions and the prevalence of fallacious intuitions concerning statistical regression are traced to the representativeness heuristic."
- **Relevance to Canary Transcripts:** Directly explains both OpenCode `gemini-4-carbon`'s `9 / 9` (`100.0%`) `argmax(after_hours)` tie-breaks on un-isolated `v1.4` hard sets (including `seed 18` citing `"6 after-hours accesses out of 18 total accesses (33.3%), matching the mole's 30% after-hours rate"` while ignoring `framing_rate = 2.0` and `3` co-holders) and Codex `gpt-5.5`'s two `v1.3` medium `-1.00` wrong accusations (`seed 0` at `P = 0.183` on `"statistically loud"` `e02`; `seed 4` at `P = 0.330` on `e07`'s `"highest after-hours count"`).

### 2.6 Anchoring, Availability, and Insufficient Adjustment: Tversky & Kahneman (1974)

- **Citation:** Tversky, A., & Kahneman, D. (1974). Judgment under Uncertainty: Heuristics and Biases. *Science*, 185(4157), 1124-1131.
- **Live Verified Links:** https://doi.org/10.1126/science.185.4157.1124 | https://api.crossref.org/works/10.1126/science.185.4157.1124
- **Theoretical Synthesis:** Establishes representativeness, availability of salient instances, and insufficient adjustment from early anchors as systematic sources of probabilistic miscalibration.
- **Verbatim Quote (Abstract):**
> "This article described three heuristics that are employed in making judgments under uncertainty: (i) representativeness, which is usually employed when people are asked to judge the probability that an object or event A belongs to class or process B; (ii) availability of instances or scenarios, which is often employed when people are asked to assess the frequency of a class or the plausibility of a particular development; and (iii) adjustment from an anchor, which is usually employed in numerical prediction when a relevant value is available. These heuristics are highly economical and usually effective, but they lead to systematic and predictable errors."
- **Relevance to Canary Transcripts:** Explains why early focal suspects surfaced on Days `1-3` via initial recipient lists or noisy logs attract `72.1%` repeat-interview loops (`1,471` repeat `interview` calls in OpenCode `gemini-4-carbon`) and premature `restrict_access` actions (`3` OpenCode calls; `8` In-Process calls, `7` targeting innocents; `9` Grok hard calls) before canary evidence has narrowed the field.

### 2.7 Selective Hypothesis-Consistent Evidence Seeking: Nickerson (1998)

- **Citation:** Nickerson, R. S. (1998). Confirmation Bias: A Ubiquitous Phenomenon in Many Guises. *Review of General Psychology*, 2(2), 175-220.
- **Live Verified Links:** https://doi.org/10.1037/1089-2680.2.2.175 | https://api.crossref.org/works/10.1037/1089-2680.2.2.175
- **Analytical Scope:** Comprehensive synthesis distinguishing diagnostic multi-hypothesis testing (Platt's strong inference / balanced partitioning) from case-building confirmation loops that repeatedly query a single favored suspect while neglecting disconfirming non-events.
- **Verbatim Quote (Abstract):**
> "Confirmation bias, as the term is typically used in the psychological literature, connotes the seeking or interpreting of evidence in ways that are partial to existing beliefs, expectations, or a hypothesis in hand. The author reviews evidence of such a bias in a variety of guises and gives examples of its operation in several practical contexts. Possible explanations are considered, and the question of its utility or disutility is discussed."
- **Relevance to Canary Transcripts:** Directly captures two coupled transcript failures: (a) **positive-test case-building** (`26` interviews on `e27` in `seed 5`, `33` interviews on `e29` in `seed 23`, and `32` interviews with `0` canaries across Days `14-18` in `seed 18`), and (b) **neglect of negative canary evidence** (ignoring that a focal suspect held multiple *unleaked* canaries, which lowered `e27`'s leak-only posterior to `34.33%` vs `e32`'s `61.16%` on `seed 5`). Directly grounds Proposal **`P11.1`** (`gen_confirmation_echo_summary`).

### 2.8 Overprecision vs Overestimation in Belief Calibration: Moore & Healy (2008)

- **Citation:** Moore, D. A., & Healy, P. J. (2008). The trouble with overconfidence. *Psychological Review*, 115(2), 502-517.
- **Live Verified Links:** https://doi.org/10.1037/0033-295X.115.2.502 | https://api.crossref.org/works/10.1037/0033-295X.115.2.502
- **Theoretical & Experimental Scope:** Separates overconfidence into *overestimation*, *overplacement*, and *overprecision* (excessive certainty in the accuracy of one's beliefs), demonstrating that overprecision is the most persistent and resistant to feedback.
- **Verbatim Quotes (Abstract):**
> "The authors present a reconciliation of 3 distinct ways in which the research literature has defined overconfidence: (a) overestimation of one's actual performance, (b) overplacement of one's performance relative to others, and (c) excessive precision in one's beliefs."
> "Overprecision appears to be more persistent than either of the other 2 types of overconfidence, but its presence reduces the magnitude of both overestimation and overplacement."
- **Relevance to Canary Transcripts:** Resolves why `gemini-4-carbon` commits negative-EV gambles *despite* knowing `P*(V) = 1 / (1 + V)`. Parsing all `30` OpenCode final rationales in `audit_transcript_biases.py` shows that across unresolved (`|C_acc| >= 2`) accusations with explicit probability claims, Gemini's verbalized posterior exceeds exact `SolverPolicy` `P(accused)` by **`+22.94` percentage points** (`seed 23`: `82.0%` claimed vs `45.17%` exact, `+36.83 pp`; `seed 18`: `89.0%` vs `62.72%`, `+26.28 pp`; `seed 20`: `96.0%` vs `71.24%`, `+24.76 pp`; `seed 3`: `99.6%` vs `76.58%`, `+23.02 pp`). Overprecision masks sub-break-even posteriors behind inflated subjective certainty.

### 2.9 Loss-Domain Risk Seeking at Eroding Horizons: Kahneman & Tversky (1979)

- **Citation:** Kahneman, D., & Tversky, A. (1979). Prospect Theory: An Analysis of Decision under Risk. *Econometrica*, 47(2), 263-291.
- **Live Verified Links:** https://openalex.org/W3011865677 | https://doi.org/10.2307/1914185
- **Theoretical Scope:** Establishes reference-dependent evaluation and a convex value function over losses, predicting risk-seeking gambles when decision-makers frame an eroded state relative to an initial endowment rather than a `0.00` status-quo baseline.
- **Verbatim Quotes (Abstract):**
> "In particular, people underweight outcomes that are merely probable in comparison with outcomes that are obtained with certainty. This tendency, called the certainty effect, contributes to risk aversion in choices involving sure gains and to risk seeking in choices involving sure losses."
> "An alternative theory of choice is developed, in which value is assigned to gains and losses rather than to final assets and in which probabilities are replaced by decision weights. The value function is normally concave for gains, commonly convex for losses, and is generally steeper for losses than for gains."
- **Relevance to Canary Transcripts:** As leaks erode company value `V` from `1.00` down to `0.16-0.46` on Days `18-21`, the rational Bayesian break-even bar `P*(V) = 1 / (1 + V)` rises from `50.0%` to **`68.4%-86.2%`**. Agents anchored on initial `V = 1.00` treat `0.00` abstention as locking in a sure loss of the company, firing negative-EV shots (`seeds 5, 18, 23` in OpenCode `gemini-4-carbon`; `seeds 5, 6, 22` in In-Process `gemini-4-carbon`; `0` abstentions across `22 / 22` Codex `gpt-5.5` `v1.3` episodes).

### 2.10 Suspicion of Ulterior Motive and Cheap-Talk Discounting: Fein, Hilton & Miller (1990)

- **Citation:** Fein, S., Hilton, J. L., & Miller, D. T. (1990). Suspicion of Ulterior Motivation and the Correspondence Bias. *Journal of Personality and Social Psychology*, 58(5), 753-764.
- **Live Verified Links:** https://doi.org/10.1037/0022-3514.58.5.753 | https://api.crossref.org/works/10.1037/0022-3514.58.5.753
- **Experimental Design:** Three studies demonstrating that while naive observers commit correspondence bias on dispositional remarks, explicit cues to ulterior strategic motives invert attribution into active discounting.
- **Verbatim Quote (Abstract):**
> "Three studies examined the hypothesis that when perceivers learn of the existence of multiple, plausibly rival motives for an actor's behavior, they are less likely to fall prey to the correspondence bias than when they learn of the existence of situational factors that may have constrained the actor's behavior."
- **Relevance to Canary Transcripts:** Explains both halves of Canary's message-search forensics: (1) on `v1.4` hard (`301` non-decoy cheap-talk snippets vs `88` decoy snippets returned to OpenCode `gemini-4-carbon`, `129` non-decoy cheap-talk calls across `30 / 30` episodes), organic workplace chatter triggers situational/topical distraction (`24` message calls *after* `decoy` was already found); whereas (2) on `v1.5-candidate` Gate B (`Monograph 07`), explicitly disclosing `"The seeded target is never the mole"` triggered Fein-Hilton ulterior-motive discounting (`61% -> 108%` inversion), proving why `P11.1` must preserve strict conditional zero mole leakage (`LLR = 0.0000` nats).

---

## 3. Multi-Model Empirical Forensic Synthesis (`scripts/audit_transcript_biases.py`)

Every figure below is produced deterministically by `/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_transcript_biases.py` (`cross_verification.passed = True`, `107` checks, `0` mismatches).

### 3.1 Signature 1 (`v1.4` Hard `n = 30`): Demeanor Interview Crowding vs Active Canary Capacity

On `v1.4` hard (`n_employees = 40`, `n_days = 21`, `actions_per_day = 8`, `canaries_per_day = 2`, `max_variants = 3`, `fingerprint_accuracy = 0.95`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, frozen hash `a8f99c2537c91d72`), post-hoc locked paired dev seeds `0-29` show identical exploration starvation across both OpenCode MCP and In-Process harnesses:

| Metric (`v1.4` Hard, `n = 30`, Seeds `0-29`) | OpenCode `gemini-4-carbon` | In-Process `gemini-4-carbon` | `SolverPolicy` (Paired) | Extension `[34, 37]` (`n = 2`) |
|---|---:|---:|---:|---:|
| Mean raw score `+/- 95% CI` | **`0.322 +/- 0.199`** | `0.473 +/- 0.118` | **`0.499 +/- 0.119`** | `+0.745 +/- 0.010` (`Solver`: `+0.700`) |
| Raw frontier / solver `[95% CI]` | **`65% [24%, 98%]`** | `95% [73%, 118%]` | `100%` | pooled `n = 32`: `+0.349 +/- 0.190` |
| Luck-adjusted score (`%` of solver `[95% CI]`) | **`0.360` (`72% [52%, 91%]`)** | `0.421` (`84% [67%, 100%]`) | **`0.499` (`100%`)** | pooled `n = 32`: **`75% [56%, 93%]`** |
| Total tool calls / episode (`invalid_calls`) | `128.03` (`0.93`) | `116.77` (`0.03`) | `84.30` (`0.00`) | `55.50` (`0.00`) |
| `interview` calls / episode (`v1.4` `medium` `n = 30`) | **`68.03`** (`37.53`) | **`57.27`** (`47.30`) | **`0.00`** (`0.00`) | `12.50` |
| Days `1-2` interviews / Repeat interviews (`%` of `ok`) | `300` / **`1,471` (`72.1%`)** | `248` / `1,158` (`67.4%`) | `0` / `0` (`0.0%`) | `9` / `2` (`8.0%`) |
| Observed evasive answers (`mole` vs `innocent`) | `112` vs **`309`** (`2.76x` inn) | `117` vs `254` (`2.17x` inn) | `0` vs `0` | `1` vs `5` |
| Total played days / Under-planted days (`< 2` canaries) | `403` / `303` (`75.2%`) | `390` / `292` (`74.9%`) | `319` / `182` (`57.1%`) | `13` / `5` |
| Under-planted days exhausting `8 / 8` actions | **`242` of `303` (`79.9%`)** | `205` of `292` (`70.2%`) | **`0` of `182` (`0.0%`)** | `1` of `5` |
| `interview` calls executed on `8 / 8` under-planted days | **`1,503`** | `1,253` | **`0`** | `4` |
| First `plant_canary` day (mean) | **`3.0`** | **`3.4`** | **`1.0`** | `1.5` |
| Canaries before accusation (`%` of `2/day` capacity) | **`8.5 +/- 1.3` (`31.5%`)** | `8.6 +/- 1.2` (`33.0%`) | **`14.1 +/- 1.8` (`66.7%`)** | `7.5` (`Solver`: `10.5`) |
| Days with `>= 1` canary (`%` of played days) | **`38.0%`** | `40.8%` | **`90.9%`** | `69.2%` |
| Mean recipients / unique variant labels per canary | `10.1` / `3.0` | `10.3` / `3.0` | `9.9` / `3.0` | `11.1` / `3.0` |

**Key Forensic Proof:** Across OpenCode `gemini-4-carbon`'s `2,039` valid interviews, topic selection splits across `recent_documents` (`1,105`), `access_needs` (`444`), `contacts_outside` (`306`), and `workload` (`184`), targeting the true mole `503` times, plain innocents `1,536` times, and the identified `decoy` **`0` times** (`gemini-4-carbon` correctly filtered out `decoy` from interviewing!). Thus `gemini-4-carbon` understood both `decoy` filtering and `careful_mole` canary sizing (`10.1` recipients, `3.0` variants), yet traded away `5.6` watermarked canaries per episode (`4.85` nats of cumulative diagnostic capacity) in exchange for `68.03` passive `0.00477`-nat demeanor checks (`0.32` nats expected KL).

---

### 3.2 Signature 2: Base-Rate Log Distraction, Cheap-Talk Searches, and the `9 / 9` (`100.0%`) `argmax(after_hours)` Tie-Breaker

1. **Theoretical vs Observed `after_hours` Base-Rate Dilution (`Axelsson, 2000`):**
   - Theoretical `v1.4` hard daily `after_hours` rates: `mole = 0.3000/d`, `decoy = 1.1000/d`, each of `38` plain innocents `= 0.126316/d` (`4.8000/d` sum), company total `= 6.2000/d` -> single-alarm Bayesian **`PPV = 4.84%`** (`5.88%` excluding `decoy`).
   - Across `368` `read_access_logs` calls (`12.27`/ep), OpenCode `gemini-4-carbon` inspected **`2,175` `after_hours` entries**: **`95` mole (`4.37%`)**, **`390` decoy (`17.93%`)**, and **`1,690` plain innocents (`77.70%`)** (`5.32%` empirical `PPV` excluding `decoy`).
2. **Cheap-Talk Message Distraction & Uncalibrated Restrictions:**
   - `SolverPolicy` issues `7.53` `search_messages` calls/ep strictly on `decoy_keyword` vocabulary (`106` decoy snippets vs `5` non-decoy snippets, **`0` topical cheap-talk queries**, **`0` `restrict_access` calls**).
   - OpenCode `gemini-4-carbon` issues `4.23` `search_messages` + `0.17` `read_message` (`4.40`/ep), including **`129` non-decoy cheap-talk calls across `30 / 30` (`100.0%`) episodes** (`60` `broad_wildcard`, `50` `topical_cheap_talk`, `16` `employee_id`, `8` `decoy_keyword`, `3` `non-decoy read_message` -> **`301` non-decoy snippets vs `88` decoy snippets**), plus **`24` message calls after `decoy` was already seen**. OpenCode makes `3` `restrict_access` calls (`seed 5`: mole `e27`; `seed 11`: innocent `e18` on Day 13; `seed 21`: mole `e17`, costing `+0.12 V` gap), while In-Process makes **`8` `restrict_access` calls, `7` (`87.5%`) against innocent employees**.
3. **Replay-Verified `9 / 9` (`100.0%`) Strict `argmax(after_hours)` Tie-Breaking on Un-Isolated Accusations:**
   Deduplicating every `read_access_logs` entry observed prior to `accuse` across all **`9` un-isolated OpenCode `v1.4` hard accusations** (`|C_acc| >= 2`, all `9` at `P(accused) < 0.85`) proves `100.0%` reliance on raw `after_hours` outlier ranking:

| Seed | Accuse Day | `\|C_acc\|` | Observed `after_hours` Counts Across `C_acc` (`accused` in bold) | Accused (Outcome) | Exact `P(acc)` | Break-Even `P*` | Exact `EV` | Claimed `%` (`Overprecision`) |
|---:|---:|---:|---|---|---:|---:|---:|---:|
| `3` | `19` | `10` | **`e29: 7`**, `e01: 4`, `e26: 4`, `e05: 3`, `e18: 2`, `e32: 2`, `e36: 2`, `e06: 1`, `e21: 1`, `e08: 0` | `e29` (hit, `+0.51`) | `0.7658` | `0.6623` | `+0.1190` | `99.6%` (**`+23.02 pp`**) |
| `5` | `21` | `2` | **`e27: 8`**, `e32: 5` | `e27` (hit, `+0.16`) | **`0.5102`** | **`0.8621`** | **`-0.4075`** | `n/a` (ratio `>13:1`) |
| `7` | `10` | `3` | **`e37: 4`**, `e11: 0`, `e39: 0` | `e37` (hit, `+0.69`) | `0.7833` | `0.5917` | `+0.3607` | `98.7%` (**`+20.37 pp`**) |
| `8` | `14` | `2` | **`e06: 2`**, `e08: 0` | `e06` (hit, `+0.35`) | `0.8275` | `0.7407` | `+0.1185` | `n/a` |
| `14` | `12` | `2` | **`e27: 3`**, `e39: 0` | `e27` (hit, `+0.55`) | `0.7722` | `0.6452` | `+0.1979` | `94.0%` (**`+16.78 pp`**) |
| **`15`** | `12` | `2` | **`e34: 3`**, `e37: 1` *(mole `e37`)* | **`e34` (WRONG `-1.00`)** | `0.8049` | `0.6098` | `+0.3208` | `93.0%` (**`+12.51 pp`**) |
| **`18`** | `18` | `4` | **`e29: 6`**, `e27: 2`, `e37: 2`, `e09: 1` *(mole `e27`)* | **`e29` (WRONG `-1.00`)** | **`0.6272`** | **`0.6849`** | **`-0.0834`** | `89.0%` (**`+26.28 pp`**) |
| `20` | `12` | `5` | **`e14: 4`**, `e04: 1`, `e18: 1`, `e10: 0`, `e37: 0` | `e14` (hit, `+0.66`) | `0.7124` | `0.6024` | `+0.1835` | `96.0%` (**`+24.76 pp`**) |
| `23` | `21` | `3` | **`e29: 6`**, `e15: 2`, `e38: 2` | `e29` (hit, `+0.23`) | **`0.4517`** | **`0.8130`** | **`-0.4438`** | `82.0%` (**`+36.83 pp`**) |

*(Note: `Break-Even P* = 1 / (1 + V_true)` at accusation; `Exact EV` uses `SolverPolicy`'s `accuse_value(P, E[true V])` from `results/failure_analysis_v1.4.json`.)*

---

### 3.3 Signature 3: Exact Additive Gap Accounting, Overprecision (`+22.94 pp`), and Cross-Model Contrast

1. **Exact `30`-Seed Additive Skill-vs-Luck Decomposition (`v1.4` Hard, `SolverPolicy - OpenCode gemini-4-carbon`):**
   - **Thin-evidence commitment penalty (`9` un-isolated `+3.50 V`, `20` isolated `-0.11 V`):** **`+3.39 V`** (`+1.64 V` of which comes from the `3` negative-EV gambles on `seeds 5, 18, 23`).
   - **Horizon abstention after slow exploration (`seed 11`, `121` interviews, `7` consistent):** **`+0.62 V`**.
   - **Extra leak damage (`+1.75 V`) vs saved canary cost (`-1.69 V`) + restriction cost (`+0.12 V`):** **`+0.18 V` net** (`+1.75 - 1.69 + 0.12`).
   - **Total luck-adjusted gap:** **`+4.19 V`** (`+0.140` per episode), plus **`+1.11 V`** realized luck delta (`4` wrong vs `3.4` expected: `seeds 1, 26` disclosed `5%` flips at `P = 0.99, 0.95`; `seed 15` unresolved pair at `P = 0.80`; `seed 18` negative-EV gamble at `P = 0.63`), yielding a **raw paired gap of `5.30 V`** (`+0.177` per episode).
   - **Transcript Telemetry (`30 / 30` OpenCode & `30 / 30` In-Process transcripts):** OpenCode `gemini-4-carbon` consumed **`23,191` reasoning tokens/episode** (`695,738` total, `$1.676` mean / `$50.29` total run cost) and emitted final rationales in `30 / 30` episodes; In-Process `gemini-4-carbon` averaged `18.37` thought blocks/episode and explicitly reasoned about `1 / (1 + V)` or expected-value break-even in **`25 / 30` (`83.3%`)** episodes, yet still took `3` negative-EV horizon shots (`seeds 5, 6, 22`).
2. **Cross-Model Behavioral Matrix (`v1.4` Gemini vs `v1.4` Grok vs Historical `v1.3` OpenAI `gpt-5.5`):**

| Model & Harness Cohort | Rules (`Hash`) | Tier (`n`) | Raw Score (`% Solver`) | Luck-Adj (`% Solver`) | `interview` / Ep | `plant_canary` / Ep | `read_access_logs` / Ep | Msg Calls / Ep | `restrict` / Ep | Abstentions | Dominant Cognitive-Bias Failure Signature |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| OpenCode `gemini-4-carbon` | `v1.4` (`a8f99c2537c91d72`) | `hard` (`30`) | `0.322` (`65%`) | `0.360` (`72%`) | **`68.03`** | `8.50` | `12.27` | `4.40` | `0.10` | `1 / 30` | Demeanor crowding (`242/303` days) -> `9/9` log `argmax` + `+22.94 pp` overprecision |
| In-Process `gemini-4-carbon` | `v1.4` (`a8f99c2537c91d72`) | `hard` (`30`) | `0.473` (`95%`) | `0.421` (`84%`) | **`57.27`** | `8.60` | `11.80` | `4.47` | **`0.27`** | `1 / 30` | Demeanor crowding (`205/292` days) + `7/8` innocent restrictions + `6/6` log `argmax` |
| `SolverPolicy` (Reference) | `v1.4` (`a8f99c2537c91d72`) | `hard` (`30`) | **`0.499` (`100%`)** | **`0.499` (`100%`)** | **`0.00`** | **`14.13`** | `9.60` | `7.53` | **`0.00`** | `0 / 30` | Exact Bayesian benchmark (`0` `EV < 0`, `26/30` singleton `\|C_acc\| = 1`) |
| Grok Agent (`grok-agent`) | `v1.4` (`a8f99c2537c91d72`) | `hard` (`5`) | `4` hit, `1` abst | calibrated | **`0.60`** | `9.20` | `9.60` | `4.00` | **`1.80`** | **`1 / 5`** | Suppresses interviews & abstains at `P ~ 0.53 < 0.70` (`hard-900000`), but over-restricts |
| Grok Agent (`grok-agent`) | `v1.4` (`a8f99c2537c91d72`) | `medium` (`5`) | `5` accused | n/a | `3.60` | `6.60` | `7.00` | `3.20` | **`1.40`** | `0 / 5` | Costly multi-suspect `restrict_access` elimination experiments (`0.01 V/d` bleed) |
| Codex `gpt-5.5` (MCP) | `v1.3` (`8df71cf570bb48bc`) | `medium` (`11`) | `0.401` (`55%`) | **`0.249` (`34%`)** | `11.64` | `7.73` | `7.64` | `12.18` | `0.27` | **`0 / 11`** | Representativeness log-chasing (`seeds 0, 4` wrong `-1.0` at `P = 0.183, 0.330`) |
| Codex `gpt-5.5` (MCP) | `v1.3` (`8df71cf570bb48bc`) | `hard` (`11`) | `0.655` (`106%`) | `0.343` (`82%`) | `8.73` | `10.09` | `10.18` | `11.64` | `0.82` | **`0 / 11`** | Thin-posterior lucky bets (`seeds 3, 8` at `P = 0.449, 0.408`) under 14-day `v1.3` |
| In-Process `gpt-5.5` | `v1.3` (`8df71cf570bb48bc`) | `hard` (`8`) | `0.264` (`38%`) | `0.250` (`58%`) | `6.38` | `10.62` | **`33.75`** | **`17.50`** | `0.12` | **`0 / 8`** | Compulsive log/message re-scanning (`51.25` passive reads/ep) + `2` wrong shots (`seeds 3, 4`) |

---

## 4. Concrete Zero-Protected-Path Proposals (`P11.1` and `P11.2`)

Both proposals translate our empirical transcript forensics into immediate, zero-protected-path Canary upgrades while preserving frozen `v1.4` hashes (`a8f99c2537c91d72`), strict conditional zero mole leakage ($I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$, `LLR = 0.0000` nats), and the `>= 85%` `SolverPolicy` catchability floor.

---

### Proposal P11.1: Leak-Consistent Confirmation Echo Summary (`gen_confirmation_echo_summary` in `canary/social/biases.py`)

#### Empirical & Theoretical Justification
Section 3 revealed two converging vulnerabilities: (1) in [Monograph 07](./07_v15_bias_layer_proposals.md), static Day-1 `primary_suspect` selection in `V16SocialProvider` is eliminated by surfaced regular-leak recipient intersections in **`63.3%`** of `hard` worlds by Day 6 (`76.8%` by Day 10); and (2) when `|consistent_set| >= 2` on Days `6-18`, frontier LLMs suffer **`+22.94 pp` verbalized overprecision** (Moore & Healy, 2008) and positive-test confirmation loops (Nickerson, 1998; Tversky & Kahneman, 1974), spending scarce `8/day` actions on follow-up `interview` and `read_access_logs` calls rather than planting a 3-variant splitting canary.

Proposal **`P11.1`** adds `gen_confirmation_echo_summary` to `canary/social/biases.py` (`0` protected paths touched):
1. **Live Public-Intersection Survival:** Filters non-decoy unrestricted staff against `ctx.facts.extra.get("surfaced_reg_docs", ())` so the echoed focal suspect $T_d$ **always** survives public regular-leak set intersection (`|P_d| >= 1`), prioritizing any `ctx.prior_events` target still inside $P_d$ to sustain multi-day narrative continuity.
2. **Strict Conditional Zero Mole Leakage (`LLR = 0.0000` nats):** Neither `world.mole`, `Env._leaked` un-surfaced items, nor private `Env._dyn` state is ever read. Because $\text{Mole} \to \text{PublicDayFacts}_{1:d} \to \text{EchoSummary}_d$ forms a Markov chain, $I(\text{EchoSummary}_d; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$ and `SolverPolicy` incurs **`0.0000` nats** calibration drift (`0.000 V` loss) while avoiding any Fein-Hilton (1990) Gate B exclusion flip.
3. **Simulation-Verified Lint & Statistical Calibration (`200` `v1.4` Hard Worlds, `seeds 0-199`):**
   - **`validate_social_message` pass rate (`Days 6, 10, 14` = `600` messages):** **`600 / 600` (`100.0%`)** valid (`0` `lint_text` violations, `0` `DECOY_VOCAB` substring hits, `0` forbidden subject prefixes, `100%` `Name (eXX)` + `SALIENCE_TERMS` inside `body[:110]` so `search_messages` 120-char snippets always surface the summary).
   - **Empirical zero excess mole correlation:** Independent per-world checks across `seeds 0-199` confirm exact uniformity over $P_d$: Day 6 hits `19 / 200` (`9.50%`) vs $\mathbb{E}[1/|P_6|] = 20.08$ (`10.04%`, $z = -0.26$, $p = 0.79$); Day 10 hits `30 / 200` (`15.00%`) vs $\mathbb{E}[1/|P_{10}|] = 25.43$ (`12.72%`, $z = +0.98$, $p = 0.33$). Across all `600` multi-candidate events (`|P_d| >= 2`), **`506 / 600` (`84.33%`)** reinforce an **innocent** leak-consistent co-holder and explicitly bait another `interview` / `recent_documents` log check.

#### Drop-In Implementation (`canary/social/biases.py`)
```python
def gen_confirmation_echo_summary(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    pool = [e.id for e in ctx.facts.employees if e.id != ctx.facts.decoy]
    for item in ctx.facts.extra.get("surfaced_reg_docs", ()):
        rec = set(item.get("recipients", ()))
        inter = [eid for eid in pool if eid in rec]
        if inter:
            pool = inter
    unrest = [eid for eid in pool if eid not in set(ctx.facts.restricted)]
    active_pool = unrest if unrest else pool

    prior_targets = [
        str(ev.get("target"))
        for ev in ctx.prior_events
        if int(ev.get("day", 0)) < ctx.facts.day and ev.get("target") in active_pool
    ]
    if target_id and target_id in active_pool:
        chosen_id = target_id
    elif prior_targets:
        chosen_id = prior_targets[-1]
    elif not secondary and ctx.primary_suspect in active_pool:
        chosen_id = ctx.primary_suspect
    elif ctx.secondary_suspect in active_pool:
        chosen_id = ctx.secondary_suspect
    else:
        chosen_id = rng.choice(active_pool)

    target = ctx.by_id[chosen_id]
    speaker = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers or ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, pspeaker, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Summary of leak doc review thread",
        "Working summary from security review meeting",
        "Consolidated doc audit status note",
    )
    if pday is not None:
        bodies = (
            f"Summary of leak doc review on {tn}: Day {pday} notes from {pspeaker} around {early_doc} align with today's {doc_title} check; run one follow-up interview before deciding.",
            f"Meeting leak summary on {tn}: combining Day {pday} doc circulation on {early_doc} with {doc_title} keeps them as the main working lead to interview next.",
            f"Consolidated doc audit note on {tn}: earlier Day {pday} review and {doc_title} distribution point the same way; check recent_documents logs once more.",
        )
    else:
        bodies = (
            f"Summary of leak doc review on {tn}: cross-team notes around {doc_title} all converge on the same working lead; worth a quick interview follow-up.",
            f"Meeting leak summary on {tn}: multiple reviewers flagged {doc_title} circulation alignment; check recent_documents logs before closing.",
        )
    channel = rng.choice(("#security-review", "email"))
    return _build_event(
        ctx,
        "confirmation_echo_summary",
        speaker,
        target,
        channel,
        rng.choice(subjects),
        rng.choice(bodies),
        doc_title,
    )
```

---

### Proposal P11.2: Automated Cognitive-Bias Tagger (`canary/analysis/tags.py`) + Paired Catchability-Verified `MoleStrategy`

#### Architectural & Diagnostic Gap Closed in `canary/analysis/tags.py`
Currently, `canary/analysis/tags.py` wraps `canary.solver.regret.attribute` (`protected` under `canary/solver/`) with seven operational tags whose `premature_accusation` rule uses a **fixed `pe < 0.60` cutoff** (`canary/solver/regret.py:80`). As proved on `v1.4` hard `seed 18` (`P = 0.6272 >= 0.60`, `E[true V] = 0.4612`, break-even `P* = 0.6843`, `EV = -0.0834 < 0`, `-1.00` wrong accusation), fixed cutoffs **miss moving-bar negative-EV gambles** and provide zero visibility into *which psychological mechanism* caused the regret (`demeanor_interview_crowding`, `cheap_talk_distraction`, `unisolated_log_tiebreak`, `overprecision_inflation`).

Because `canary/analysis/tags.py` (`outside` `.github/protected-paths.txt`!) already accepts `attribute: Callable[[EpisodeResult], list[dict]] | None = None` in `tag_report(eps, attribute=...)`, Proposal **`P11.2`** adds `cognitive_bias_attribute(ep)` directly inside `canary/analysis/tags.py` (`--cognitive-biases` CLI flag, **`0` edits to `canary/solver/`**), augmenting `WHY` with five research-grounded tags whose empirical rates on `v1.4` hard (`n = 30`, `scripts/audit_transcript_biases.py`) cleanly separate frontier models from `SolverPolicy`:

| `P11.2` Cognitive-Bias Tag (`canary/analysis/tags.py`) | Exact Deterministic Trigger | OpenCode `gemini-4-carbon` (`n = 30`) | In-Process `gemini-4-carbon` (`n = 30`) | `SolverPolicy` (`n = 30`) | Literature Anchor |
|---|---|---:|---:|---:|---|
| `demeanor_interview_crowding` | Closed day with `< P.canaries_per_day` canaries, `>= P.actions_per_day` actions, and `>= 1` `interview` | **`30 / 30` (`100.0%`, `242` d)** | **`28 / 30` (`93.3%`, `205` d)** | **`0 / 30` (`0.0%`, `0` d)** | Hartwig & Bond (2011); Bond & DePaulo (2006) |
| `cheap_talk_distraction` | `search_messages` on non-decoy query or `read_message` on non-decoy sender | **`30 / 30` (`100.0%`, `129` c)** | **`30 / 30` (`100.0%`, `133` c)** | **`0 / 30` (`0.0%`, `0` c)** | Fein, Hilton & Miller (1990); Tversky & Kahneman (1974) |
| `unisolated_log_tiebreak` | `accuse(e)` with `\|C_acc\| >= 2` and `e in argmax_{c in C_acc} obs_after_hours(c)` | **`9 / 30` (`30.0%`, `9/9` uniso)** | **`6 / 30` (`20.0%`, `6/6` uniso)** | `2 / 30` (`6.7%`, both `P >= 0.85`) | Axelsson (2000); Kahneman & Tversky (1973) |
| `below_breakeven_gamble` | `accuse(e)` with `accuse_value(P(e), E[true V], P) < 0.0` (`P(e) < 1 / (1 + E[V])`) | **`3 / 30` (`10.0%`, `5, 18, 23`)** | **`3 / 30` (`10.0%`, `5, 6, 22`)** | **`0 / 30` (`0.0%`, `0` shots)** | Kahneman & Tversky (1979); Moore & Healy (2008) |
| `overprecision_inflation` | `meta["claimed_posterior_pct"] - 100 * P(e) >= 15.0` percentage points | **`6 / 30` (`20.0%`, `+22.94 pp`)** | `n/a` (no `%` table) | **`0 / 30` (`0.0%`)** | Moore & Healy (2008); Nickerson (1998) |

#### Drop-In Wrapper Specification (`canary/analysis/tags.py`)
```python
COGNITIVE_BIAS_WHY = {
    "demeanor_interview_crowding": "exhausted daily action budget with interviews while under-planting canaries",
    "cheap_talk_distraction": "searched or read non-decoy workplace chatter carrying 0.0000 nats mole signal",
    "unisolated_log_tiebreak": "accused max-after_hours suspect inside an unresolved consistent set (|C| >= 2)",
    "below_breakeven_gamble": "accused below moving break-even bar P < 1 / (1 + E[true V]) (expected value < 0)",
    "overprecision_inflation": "verbalized confidence exceeded exact Bayesian posterior by >= 15 percentage points",
}
```

#### Paired Catchability-Verified `MoleStrategy` (`echo_framing_careful_v14`)
To exploit `demeanor_interview_crowding` and `unisolated_log_tiebreak` simultaneously during adversary evaluation (`canary/mole/dsl.py`), `echo_framing_careful_v14` switches to `most_recipients` (`>= 12` holders) + `frame: "random_peer"` whenever `recent_low_recipient_docs >= 2` and `max_recipient_count >= 12`, starving late-canary investigators of narrow splits while injecting benign peer `after_hours` noise, and stonewalls (`leak: "none"`, `frame: "most_restricted_peer"`) when restricted:

```json
{
  "name": "echo_framing_careful_v14",
  "rules": [
    {
      "if": [
        ["recent_low_recipient_docs", ">=", 2],
        ["max_recipient_count", ">=", 12]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "random_peer"
      }
    },
    {
      "if": [
        ["i_am_restricted", "==", 1]
      ],
      "then": {
        "leak": "none",
        "frame": "most_restricted_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

**Paired `200`-World Verification (`v1.4` Hard `seeds 0-199`, `MoleStrategy.from_json` + `run_episode`):**
- **`SolverPolicy` catchability gate (`>= 85%` required):** **`183 / 200` (`91.5% >= 85%` PASS)**, mean score **`+0.5213`** (vs `188 / 200` = `94.0%`, `+0.5282` on `default_v0`; only `-0.0069 V` solver drift because Day-1 `SolverPolicy` saturates `2/day` 3-variant canaries before the mole can coast on wide docs).
- **Uncalibrated `Heuristic` degradation:** Accuracy drops from `153 / 200` (`76.5%`) to **`119 / 200` (`59.5%`)**, and mean score collapses from `+0.0436` into negative territory (**`-0.2234`**), widening the paired `SolverPolicy - Heuristic` gap by **`+53.7%`** (`+0.4846 V -> +0.7447 V`), while `LogsMinusDecoy` remains crushed at **`-0.9258`** (`4.0%` accuracy).

---

## 5. Summary Reference Matrix

| Study | Venue & Year | Live HTTP-200 Verified Links | Core Finding | Canary Transcript Forensic Signature & Proposal |
|---|---|---|---|---|
| Hartwig & Bond | *Psych. Bull.* (2011) | https://api.crossref.org/works/10.1037/a0023589 \| https://doi.org/10.1037/a0023589 | Lens model (`153` samples, `66` cues): cue weakness (`d ~ 0.10`), not cue ignorance, limits passive detection | `Env.instruction()` LR disclosure fails to stop `68.03` interviews/ep (`242/303` crowded days); **`P11.2`** |
| Bond & DePaulo | *PSPR* (2006) | https://api.crossref.org/works/10.1207/s15327957pspr1003_2 \| https://doi.org/10.1207/s15327957pspr1003_2 | `206` docs, `24,483` judges: `54%` accuracy (`47%` lies); motivation to be believed triggers Othello errors | `309` innocent evasive answers vs `112` mole evasive answers in `v1.4` hard OpenCode interviews |
| DePaulo et al. | *Psych. Bull.* (2003) | https://api.crossref.org/works/10.1037/0033-2909.129.1.74 \| https://doi.org/10.1037/0033-2909.129.1.74 | `1,338` estimates, `158` cues: median `\|d\| = 0.10`; tension and complaints confound stress with deceit | Matches `v1.4` hard `interview_lr = 1.2` (`d = 0.097`, `KL = 0.00477` nats vs `0.86544`-nat canary) |
| Axelsson | *ACM TISSEC* (2000) | https://openalex.org/W2156204309 \| https://doi.org/10.1145/357830.357849 | Base-rate fallacy bounds audit-alarm `PPV` when benign events outnumber hostile events | `2,175` observed `after_hours` rows: `4.37%` empirical `PPV` (`5.32%` ex-decoy; `4.84%` / `5.88%` exact) |
| Kahneman & Tversky | *Psych. Rev.* (1973) | https://openalex.org/W1980054641 \| https://doi.org/10.1037/h0034747 | Representativeness induces base-rate neglect and unjustified confidence on statistical outliers | Explains **`9 / 9` (`100.0%`)** `argmax(after_hours)` tie-breaks (`seeds 15, 18` `-1.0`) & Codex `medium` `seeds 0, 4` |
| Tversky & Kahneman | *Science* (1974) | https://doi.org/10.1126/science.185.4157.1124 \| https://api.crossref.org/works/10.1126/science.185.4157.1124 | Representativeness, availability of salient instances, and insufficient adjustment from early anchors | `72.1%` repeat interviews (`1,471` calls) & `7 / 8` innocent In-Process `restrict_access` actions |
| Nickerson | *Rev. Gen. Psych.* (1998) | https://doi.org/10.1037/1089-2680.2.2.175 | Positive-test case-building and selective neglect of disconfirming non-events | `26-33` single-suspect interviews + dropping unleaked-canary negative evidence; grounds **`P11.1`** |
| Moore & Healy | *Psych. Rev.* (2008) | https://api.crossref.org/works/10.1037/0033-295X.115.2.502 \| https://doi.org/10.1037/0033-295X.115.2.502 | Reconciles overestimation, overplacement, and persistent *overprecision* in subjective probabilities | **`+22.94 pp`** verbalized posterior inflation across unresolved OpenCode commitments (`seed 23`: `+36.83 pp`) |
| Kahneman & Tversky | *Econometrica* (1979) | https://openalex.org/W3011865677 \| https://doi.org/10.2307/1914185 | Convex loss-domain value function induces risk-seeking gambles against sure losses | `3` below-break-even `P < 1/(1+V)` horizon gambles (`seeds 5, 18, 23`, `-0.9368 V` luck-adj); **`P11.2`** |
| Fein, Hilton & Miller | *JPSP* (1990) | https://api.crossref.org/works/10.1037/0022-3514.58.5.753 \| https://doi.org/10.1037/0022-3514.58.5.753 | Disclosing ulterior motives flips correspondence bias into active discounting | Grounds `129` organic cheap-talk calls vs Gate B flip and strict `LLR = 0.0000` nats in **`P11.1`** |
