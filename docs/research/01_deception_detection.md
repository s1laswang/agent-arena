# 01. Deception Detection and Investigative Interviewing: Research Grounding for Canary

**Squad:** `research` (`canary-research-w1`)  
**Baseline commit:** `07800288` (`origin/justSilas`, rules `v1.4`)  
**Scope:** Empirical psychology and investigative interviewing foundations for Canary's `interview` tool, surface text channels (`search_messages`, `read_message`), active trap design (`plant_canary`), and concrete `v1.5`/`v1.6` interview and social-layer proposals for Silas (`canary/rules.py`, `canary/env.py`, `canary/mole/dsl.py`, `canary/solver/belief.py`, and zero-protected-path `canary/social/biases.py`).

---

## 1. Executive Thesis: Why Frontier Agents Fall into the Demeanor Trap

Across 50 years of experimental psychology, lens-model meta-analyses, law-enforcement interviewing research, and computational psycholinguistics, one empirical finding dominates all others: **passive observation of demeanor, evasiveness, and surface linguistic style cannot reliably separate liars from truth-tellers, whereas active interventions that widen diagnostic signal differences and test statement-evidence consistency achieve high discrimination.**

Canary `v1.4` already encodes the first half of this reality mathematically, and frontier LLM agents fail precisely because they behave like untrained human interrogators rather than Bayesian experiment designers:

1. **Human and ungrounded interview discrimination sits near chance (~54%) because behavioral cues themselves are weak.** Meta-analytic synthesis across 206 documents and 24,483 judges shows real-time lie-truth classification averages 54% (47% sensitivity on lies, 61% specificity on truths), while lens-model meta-analysis across 153 samples and 66 cues proves lie-catchers fail *not* because they use the wrong cues, but because passive behavioral cues have near-zero diagnostic validity (`d ~ 0.10`) and overlap with innocent stress under suspicion (DePaulo et al., 2003; Bond & DePaulo, 2006; Hartwig & Bond, 2011; Luke, 2019).
2. **Real-world deception discovery comes from diagnostic external evidence and active eliciting interventions, not demeanor.** Truth-Default Theory (Levine, 2014), active cognitive-load interviewing (Vrij et al., 2006, 2008, 2009), and Strategic Use of Evidence (Hartwig et al., 2005, 2006; Tekin et al., 2015) demonstrate that accurate investigators actively widen the liar-innocent signal gap through hard attribution traps and late strategic confrontation with case-specific evidence (`85.4%` accuracy for SUE-trained interviewers vs `56.1%` for untrained interviewers).
3. **`gemini-4-carbon` reproduces the classic human investigator bias on Canary `v1.4` hard.** On `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_evasive_innocent = 0.20`, `interview_lr = 1.20`), a single interview carries Kullback-Leibler divergence `KL(Mole || Innocent) = 0.00477` nats (`d = 0.097`), whereas a leaked 3-variant canary (`max_variants = 3`, `fingerprint_accuracy = 0.95`) carries `0.86544` nats of 3-way mutual information (`181.4x` the information gain, `+3.6376` nats log-likelihood shift on a matching label vs flip). Consistent with Hartwig & Bond's (2011) finding that informing lie-catchers of valid cue weights does not fix weak channels, printing `interview_lr = 1.20` directly in `Env.instruction()` does not stop `gemini-4-carbon` over OpenCode/MCP from spending **68.0 interviews per episode** (`128.0` total tool calls vs `SolverPolicy`'s `84.3`), exhausting its 8-action daily budget on `242` of `303` under-planted days (`1,503` interview calls) and planting only **8.5 canaries** (`32%` capacity) vs `SolverPolicy`'s **0 interviews** and **14.1 canaries** (`67%` capacity). That under-exploration leaves `>= 2` suspects consistent with every leak in `9/29` accusations, costing **3.39 V** of expected value across 30 paired seeds (`docs/reports/failure_analysis_v1.4.md`).

Section 2 documents twelve verified peer-reviewed papers with live HTTP-verified links and character-for-character verbatim quotes. Section 3 maps those findings quantitatively to Canary `v1.4` (`07800288`). Section 4 delivers three concrete, zero-leakage proposals: **P1.1 (SUE Evidence-Conditioned Interview LR)** and **P1.2 (Public-Stress Othello Anxiety Decoupling)** for Silas's `v1.5`/`v1.6` core rules, plus **P1.3 (`gen_demeanor_lure` Zero-Protected-Path Social Bias Generator)** for immediate plug-in to `v1.6` `canary/social/`.

---

## 2. Primary Literature Grounding (Live HTTP-Verified Citations and Verbatim Quotes)

### 2.1 Near-Chance Demeanor Judgment and the Othello Error: Bond & DePaulo (2006)

- **Citation:** Bond, C. F., Jr., & DePaulo, B. M. (2006). Accuracy of Deception Judgments. *Personality and Social Psychology Review*, 10(3), 214-234.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/16859438/ | DOI: https://doi.org/10.1207/s15327957pspr1003_2
- **Sample & Design:** Meta-analysis of `206` documents encompassing `24,483` judges evaluating real-time truthful and deceptive statements without external physical or documentary evidence aids.
- **Verbatim Quote (Abstract):**
> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges. In relevant studies, people attempt to discriminate lies from truths in real time with no special aids or training. In these circumstances, people achieve an average of 54% correct lie-truth judgments, correctly classifying 47% of lies as deceptive and 61% of truths as nondeceptive."
- **Verbatim Quote on Motivation to Be Believed and Truth-Bias (Abstract):**
> "Our meta-analyses reveal that people are more accurate in judging audible than visible lies, that people appear deceptive when motivated to be believed, and that individuals regard their interaction partners as honest."
- **Relevance to Canary:** Ungrounded one-on-one questioning without external documentary corroboration yields near-chance classification (`54%` overall, `47%` hit rate on actual liars). Worse, high motivation to be believed makes *both* liars and suspected innocents appear deceptive (the Othello error), turning naive interview loops into false-incrimination generators.

### 2.2 Weak Effect Sizes of Behavioral Cues and Identity-Relevant Stakes: DePaulo et al. (2003)

- **Citation:** DePaulo, B. M., Lindsay, J. J., Malone, B. E., Muhlenbruck, L., Charlton, K., & Cooper, H. (2003). Cues to Deception. *Psychological Bulletin*, 129(1), 74-118.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/12555795/ | Open-Access Handle: https://dukespace.lib.duke.edu/handle/10161/14941 | DOI: https://doi.org/10.1037/0033-2909.129.1.74
- **Sample & Design:** Quantitative synthesis of `1,338` independent effect-size estimates across `158` behavioral, vocal, and verbal cues to deception (`88` cues with `k >= 3` independent estimates; median `|d| = 0.10` across the 88 multi-estimate cues).
- **Verbatim Quote on Scope and Faintness (Abstract):**
> "The combined results of 1,338 estimates of 158 cues to deception are reported. Results show that in some ways, liars are less forthcoming than truth tellers, and they tell less compelling tales. They also make a more negative impression and are more tense. Their stories include fewer ordinary imperfections and unusual contents. However, many behaviors showed no discernible links, or only weak links, to deceit."
- **Verbatim Quote on Motivation and Transgression Moderation (Abstract):**
> "Cues to deception were more pronounced when people were motivated to succeed, especially when the motivations were identity relevant rather than monetary or material. Cues to deception were also stronger when lies were about transgressions."
- **Relevance to Canary:** Canary `v1.4` hard sets `p_evasive_innocent = 0.20` and `interview_lr = 1.20` (`p_evasive_mole = 0.24`), which corresponds to a standardized binary effect size of `d = 0.097` (Hasselblad-Hedges log-odds `d_HH = 0.129`), matching DePaulo et al.'s empirical median `|d| = 0.10` to two decimal places. Moreover, because tension (`d = 0.27`), negative statements/complaints (`d = 0.21`), and identity-relevant stakes also elevate innocent workplace distress under scrutiny, a disgruntled or restricted innocent employee looks indistinguishable from (or more suspicious than) a calm mole.

### 2.3 Why Lie-Catchers Fail - Cue Weakness vs Wrong Cues: Hartwig & Bond (2011)

- **Citation:** Hartwig, M., & Bond, C. F., Jr. (2011). Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/21707129/ | Semantic Scholar: https://www.semanticscholar.org/paper/6d0351d997c9afc33afacfb1aedb313be0ef69a5 | DOI: https://doi.org/10.1037/a0023589
- **Sample & Design:** Four Brunswikian lens-model meta-analyses synthesizing `66` behavioral cues across `153` samples, comparing perceived deception cues (`r = .59` incompetence, `r = .49` ambivalence, `r = -.15` eye contact) against actual deception cues (`r = .59` in Meta-Analysis 2; `r = .72` in Meta-Analysis 3).
- **Verbatim Quote on Perceived vs Actual Cue Covariation (Abstract):**
> "Meta-Analysis 1 investigated perceived cues to deception by correlating 66 behavioral cues in 153 samples with deception judgments. People strongly associate deception with impressions of incompetence (r = .59) and ambivalence (r = .49). Contrary to self-reports, eye contact is only weakly correlated with deception judgments (r = -.15). Cues to perceived deception were then compared with cues to actual deception. The results show a substantial covariation between the 2 sets of cues (r = .59 in Meta-Analysis 2, r = .72 in Meta-Analysis 3)."
- **Verbatim Quote on Why Explicit Cue Disclosure Fails Without Active Intervention (Abstract):**
> "In conclusion, contrary to previous assumptions, people rarely rely on the wrong cues. Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."
- **Relevance to Canary:** This paper explains Canary's central benchmark phenomenon at a foundational level:
  1. **Why `Env.instruction()` cue disclosure does not save passive interviewing:** Canary explicitly tells the agent the exact likelihood ratio (`interview_lr = 1.2`, `p_evasive_innocent = 0.20`). Just as Hartwig & Bond (2011) prove, informing a lie-catcher of exact cue validity cannot make a `d = 0.097` passive behavioral cue diagnostic; accuracy is only improved by **actively intervening to widen the observable difference between mole and innocent** (`plant_canary` at `KL = 0.86544` nats, or SUE confrontation in **P1.1**).
  2. **Blueprint for `v1.6` social bias lures (`P1.3`):** Humans (and human-pretrained LLMs) strongly associate deception with impressions of *incompetence* (`r = .59`) and *ambivalence* (`r = .49`). Surfacing zero-mole-info peer messages that describe an innocent employee as flustered or ambivalent triggers an immediate false-suspicion anchor and baits `interview` calls.

### 2.4 Publication Bias and Low Informational Value of Standalone Cues: Luke (2019)

- **Citation:** Luke, T. J. (2019). Lessons From Pinocchio: Cues to Deception May Be Highly Exaggerated. *Perspectives on Psychological Science*, 14(4), 646-671.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/31173537/ | DOI: https://doi.org/10.1177/1745691619838258
- **Sample & Design:** Re-analysis of empirical deception-cue meta-analyses combined with Monte Carlo simulations of small-sample publication bias and low statistical power.
- **Verbatim Quote (Abstract):**
> "By examining data from empirical deception-cue research and using a series of Monte Carlo simulations, I demonstrate that many estimated effect sizes of deception cues may be greatly inflated by publication bias, small numbers of estimates, and low power. Indeed, simulations indicate the informational value of the present deception literature is quite low, such that it is not possible to determine whether any given effect is real or a false positive."
- **Relevance to Canary:** Even the small `d ~ 0.10` to `0.25` behavioral effects in published literature represent an upper bound inflated by selective reporting. An autonomous investigator that prioritizes ungrounded behavioral interviews over controlled attribution experiments (`plant_canary`) is chasing statistical noise, justifying `interview_lr_ungrounded = 1.05` (`KL = 0.00031` nats) in **P1.1**.

### 2.5 Truth-Default Theory (TDT) and Diagnostic Evidence Triggers: Levine (2014)

- **Citation:** Levine, T. R. (2014). Truth-Default Theory (TDT): A Theory of Human Deception and Deception Detection. *Journal of Language and Social Psychology*, 33(4), 378-392.
- **Live Verified Links:** https://api.crossref.org/works/10.1177/0261927X14535916 | Semantic Scholar: https://www.semanticscholar.org/paper/b6e5a6ff8447e675a662b723b002e5366d321ffa | DOI: https://doi.org/10.1177/0261927X14535916
- **Theory & Empirical Synthesis:** Formalizes why passive truth-default presumption is ecologically adaptive when most communications are honest (in Canary `v1.4` hard, `39/40 = 97.5%` of staff are innocent) and why accurate lie discovery outside the laboratory occurs not by reading arousal or demeanor in real time, but by comparing contextualized content against third-party corroboration and hard audit evidence.
- **Verbatim Quote (Abstract):**
> "Unlike previous theories of deception detection, TDT emphasizes contextualized communication content in deception detection over nonverbal behaviors associated with emotions, arousal, strategic self-presentation, or cognitive effort."
- **Relevance to Canary:** TDT directly explains why Canary's optimal policy (`SolverPolicy`) treats document-recipient intersection and canary variant attribution (`check_leak_feed` + `list_documents` + `plant_canary`) as primary diagnostic triggers, rather than trying to infer guilt from surface chatter (`search_messages`) or passive demeanor (`interview`).

### 2.6 Active Cognitive-Load Interviewing: Vrij et al. (2006, 2008, 2009)

- **Citation 1 (Framework):** Vrij, A., Fisher, R., Mann, S., & Leal, S. (2006). Detecting deception by manipulating cognitive load. *Trends in Cognitive Sciences*, 10(4), 141-142. Live Links: https://pubmed.ncbi.nlm.nih.gov/16516533/ | DOI: https://doi.org/10.1016/j.tics.2006.02.003
- **Citation 2 (Reverse-Order Experiment):** Vrij, A., Mann, S. A., Fisher, R. P., Leal, S., Milne, R., & Bull, R. (2008). Increasing cognitive load to facilitate lie detection: The benefit of recalling an event in reverse order. *Law and Human Behavior*, 32(3), 253-265. Live Links: https://pubmed.ncbi.nlm.nih.gov/17694424/ | DOI: https://doi.org/10.1007/s10979-007-9103-y
- **Citation 3 (Unanticipated Questions):** Vrij, A., Leal, S., Granhag, P. A., Mann, S., Fisher, R. P., Hillman, J., & Sperry, K. (2009). Outsmarting the liars: The benefit of asking unanticipated questions. *Law and Human Behavior*, 33(2), 159-166. Live Links: https://pubmed.ncbi.nlm.nih.gov/18523881/ | DOI: https://doi.org/10.1007/s10979-008-9143-y
- **Verbatim Quote from Vrij et al. (2008) (Abstract):**
> "In Experiment 1, 80 mock suspects told the truth or lied about a staged event and did or did not report their stories in reverse order. The reverse order interviews contained many more cues to deceit than the control interviews. In Experiment 2, 55 police officers watched a selection of the videotaped interviews of Experiment 1 and made veracity judgements. Requesting suspects to convey their stories in reverse order improved police observers' ability to detect deception and did not result in a response bias."
- **Verbatim Quote from Vrij et al. (2009) (Abstract):**
> "The interviewer asked typical opening questions which we expected the liars to anticipate, followed by questions about spatial and/or temporal information which we expected suspects not to anticipate, and also a request to draw the layout of the restaurant. The results supported the hypothesis, and based on correspondence in responses to the unanticipated questions, up to 80% of liars and truth tellers could be correctly classified, particularly when assessing drawings."
- **Relevance to Canary:** Generic, anticipated questions (like Canary's ungrounded `workload` or `contacts_outside` prompts) allow a prepared mole to answer smoothly with rehearsed cover stories (`LR ~ 1.05`). Diagnostic signal emerges only when the interviewer imposes targeted cognitive load around specific, unanticipated spatiotemporal/document events that the suspect actually held.

### 2.7 Strategic Use of Evidence (SUE) & Late Disclosure Confrontation: Hartwig et al. (2005, 2006) & Tekin et al. (2015)

- **Citation 1 (Late vs Early Disclosure):** Hartwig, M., Granhag, P. A., Stromwall, L. A., & Vrij, A. (2005). Detecting deception via strategic disclosure of evidence. *Law and Human Behavior*, 29(4), 469-484. Live Links: https://pubmed.ncbi.nlm.nih.gov/16133950/ | DOI: https://doi.org/10.1007/s10979-005-5521-x
- **Citation 2 (SUE Training Experiment):** Hartwig, M., Granhag, P. A., Stromwall, L. A., & Kronkvist, O. (2006). Strategic use of evidence during police interviews: When training to detect deception works. *Law and Human Behavior*, 30(5), 603-619. Live Links: https://pubmed.ncbi.nlm.nih.gov/16977348/ | DOI: https://doi.org/10.1007/s10979-006-9053-9
- **Citation 3 (SUE-Confrontation & Counter-Strategies):** Tekin, S., Granhag, P. A., Stromwall, L. A., Mac Giolla, E., Vrij, A., & Hartwig, M. (2015). Interviewing strategically to elicit admissions from guilty suspects. *Law and Human Behavior*, 39(3), 244-252. Live Links: https://pubmed.ncbi.nlm.nih.gov/25844517/ | DOI: https://doi.org/10.1037/lhb0000131
- **Verbatim Quote from Hartwig et al. (2005) (Abstract):**
> "Late disclosure observers obtained an overall accuracy of 61.7%, compared to 42.9% of Early disclosure observers. Deceptive statements were identified with high accuracy (67.6%) in Late disclosure, indicating that the technique in this form is beneficial mainly for pinpointing lies."
- **Verbatim Quote from Hartwig et al. (2006) (Abstract):**
> "Trained interviewers applied different strategies than did untrained. As a consequence of this, liars interviewed by trained interviewers were more inconsistent with the evidence compared to liars interviewed by untrained interviewers. Trained interviewers created and utilized the statement-evidence consistency cue, and obtained a considerably higher deception detection accuracy rate (85.4%) than untrained interviewers (56.1%)."
- **Verbatim Quote from Tekin et al. (2015) (Abstract):**
> "As predicted, the SUE-Confrontation interview generated more statement-evidence inconsistencies from suspects than the Early Disclosure interview. Importantly, suspects in the SUE-Confrontation condition (vs. Early and No disclosure conditions) admitted more self-incriminating information and also perceived the interviewer to have had more information about the critical phase of the crime (the phase where the interviewer lacked evidence)."
- **Relevance to Canary:** The SUE literature provides both a direct analogy to Canary's `plant_canary` design (withholding trap existence in `MoleView` until after the mole commits to leaking) and the exact empirical mechanism for Proposal **P1.1**: untrained interviewers who question suspects *without* leveraging diagnostic evidence score `56.1%` (matching Bond & DePaulo's `54%` baseline), whereas interviewers who first collect corroborated leak evidence (`check_leak_feed` + `list_documents`) and then confront actual holders about that specific leaked-document window raise accuracy to `85.4%` via statement-evidence inconsistency.

### 2.8 Linguistic Style and Cross-Topic Degradation: Newman, Pennebaker, Berry & Richards (2003)

- **Citation:** Newman, M. L., Pennebaker, J. W., Berry, D. S., & Richards, J. M. (2003). Lying Words: Predicting Deception from Linguistic Styles. *Personality and Social Psychology Bulletin*, 29(5), 665-675.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/15272998/ | DOI: https://doi.org/10.1177/0146167203029005010
- **Sample & Design:** Automated LIWC psycholinguistic classification across `5` independent samples covering typed and spoken deceptive vs truthful narratives.
- **Verbatim Quote (Abstract):**
> "In an analysis of five independent samples, a computer-based text analysis program correctly classified liars and truth-tellers at a rate of 67% when the topic was constant and a rate of 61% overall. Compared to truth-tellers, liars showed lower cognitive complexity, used fewer self-references and other-references, and used more negative emotion words."
- **Relevance to Canary:** Even automated word-count classifiers drop to `61%` accuracy across topics, and one of their primary features (`more negative emotion words`) directly collides with innocent workplace disgruntlement. In Canary (`canary/text/template.py`), the innocent `decoy` emits high-salience negative-emotion messages (`"burn out"`, `"Skipped for promotion again"`, `"Pay here is a joke"`), creating an ecologically grounded false-positive trap for LLM investigators relying on surface sentiment.

### 2.9 Computer-Mediated Communication (CMC) Cue Reversal: Hancock et al. (2008)

- **Citation:** Hancock, J. T., Curry, L. E., Goorha, S., & Woodworth, M. (2008). On Lying and Being Lied To: A Linguistic Analysis of Deception in Computer-Mediated Communication. *Discourse Processes*, 45(1), 1-23.
- **Live Verified Links:** https://api.crossref.org/works/10.1080/01638530701739181 | Semantic Scholar: https://www.semanticscholar.org/paper/1362ff6863b141df147cacd32db16d761e09cb9d | DOI: https://doi.org/10.1080/01638530701739181
- **Sample & Design:** Dyadic synchronous text-based communication across `242` transcripts comparing truthful and deceptive exchanges under high and low motivation.
- **Verbatim Quote on Cue Reversal and Motivation Dependence (Abstract):**
> "An analysis of 242 transcripts revealed that liars produced more words, more sense-based words (e.g., seeing, touching), and used fewer self-oriented but more other-oriented pronouns when lying than when telling the truth. In addition, motivated liars avoided causal terms when lying, whereas unmotivated liars tended to increase their use of negations."
- **Verbatim Quote on Receiver Detection Failure (Abstract):**
> "The linguistic patterns in both the liar and the partner's language use were not related to deception detection, suggesting that partners were unable to use this linguistic information to improve their deception detection accuracy."
- **Relevance to Canary:** In digital workplace channels (Slack/email text in `search_messages`), deceptive senders do *not* look terse or sketchy; they often produce *more* words and concrete details to blend into routine work chatter, and human/LLM readers gain zero detection lift from surface text style.

### 2.10 Meta-Analytic Limits of Automated Text Lie Detection: Hauch et al. (2015)

- **Citation:** Hauch, V., Blandon-Gitlin, I., Masip, J., & Sporer, S. L. (2015). Are Computers Effective Lie Detectors? A Meta-Analysis of Linguistic Cues to Deception. *Personality and Social Psychology Review*, 19(4), 307-342.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/25387767/ | DOI: https://doi.org/10.1177/1088868314556539
- **Sample & Design:** Meta-analysis of `44` studies evaluating `79` software-extracted linguistic cues to deception.
- **Verbatim Quote (Abstract):**
> "As expected, the meta-analyses demonstrated that, relative to truth-tellers, liars experienced greater cognitive load, expressed more negative emotions, distanced themselves more from events, expressed fewer sensory-perceptual words, and referred less often to cognitive processes. However, liars were not more uncertain than truth-tellers. These effects were moderated by event type, involvement, emotional valence, intensity of interaction, motivation, and other moderators. Although the overall effect size was small, theory-driven predictions for certain cues received support."
- **Relevance to Canary:** Confirms across 44 studies that automated surface-text cues remain small and context-fragile (and liars do *not* sound more uncertain than truth-tellers), justifying Canary's architectural rule (`canary/text/facts.py`) that `PublicDayFacts` passes zero hidden mole identity to `TextProvider` ($I(\text{Messages}; \text{Mole}) = 0$).

---

## 3. Quantitative Mapping to Canary `v1.4` (`07800288`)

### 3.1 Information-Theoretic Comparison: Passive `interview` vs Active `plant_canary`

In `canary/rules.py` and `canary/env.py` (`_t_interview`), interviewing employee `e` on `topic` on day `d` draws `signal = "evasive"` with probability `p_ev = p_evasive_innocent * (interview_lr if e == mole else 1.0)`. Both `interview` and `plant_canary` consume **1 investigative action** from the `actions_per_day = 8` budget. Their exact information-theoretic yields per action (verified via `/tmp/fleet-silas/shared/agent-arena-venv/bin/python` against `canary.rules.TIERS`) are starkly asymmetric:

| Channel / Tier (`v1.4`) | `P(evasive \| innocent)` | `P(evasive \| mole)` | `LLR(+)` (evasive) | `LLR(-)` (coop.) | `KL(Mole \|\| Innocent)` | Binary `d` (`d_HH`) |
|---|---:|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | `0.200` | `0.300` | `+0.4055` nats | `-0.1335` nats | `0.02817` nats | `0.232` (`0.297`) |
| `interview` (`medium`, `LR=1.3`) | `0.200` | `0.260` | `+0.2624` nats | `-0.0780` nats | `0.01052` nats | `0.143` (`0.188`) |
| `interview` (`hard`, `LR=1.2`) | `0.200` | `0.240` | `+0.1823` nats | `-0.0513` nats | `0.00477` nats | `0.097` (`0.129`) |
| `plant_canary` (`hard`, `k=3`, `acc=0.95`, given leak) | `0.025` (flip) | `0.950` (true) | `+3.6376` nats | `-2.9957` nats | `0.86544` nats (3-way MI) | `> 3.0` |

Key structural facts verified from `canary/rules.py`, `docs/DIFFICULTY.md`, and `results/failure_analysis_v1.4.json`:

1. **Exact alignment with DePaulo et al. (2003) & Hartwig & Bond (2011):** On `v1.4` hard, `interview_lr = 1.2` at base rate `0.20` produces standardized binary `d = 0.097`, virtually identical to DePaulo et al.'s empirical median `|d| = 0.10`. Even when the agent knows the exact LR (`Env.instruction()`), passive interviewing cannot overcome a `0.00477`-nat channel.
2. **181.4-to-1 information ratio per leaked trap:** Conditional on leaking, a balanced 3-variant canary on `v1.4` hard (`fingerprint_accuracy = 0.95`) yields `0.86544` nats of 3-way mutual information (`1.09861` nats noiseless `ln 3`; pairwise mole-vs-other-holder `KL = 3.36477` nats), which is **181.4x** the `0.00477`-nat KL divergence of a `v1.4` hard interview. Even accounting for `p_leak = 0.65`, `leak_window_days = 3`, careful-mole weighting, and regular-document competition (`~15%` to `22%` per-plant leak realization on `v1.4` hard trajectories), a single `plant_canary` action yields `~0.13` to `0.19` expected nats, or **27x to 40x** an interview.

### 3.2 How `gemini-4-carbon` Fails on `v1.4` Hard (30 Paired Dev Seeds `0-29`)

All empirical figures below are verified directly from `results/failure_analysis_v1.4.json` and `docs/reports/failure_analysis_v1.4.md`:

- **Action-budget crowding out (`68.0` vs `0.0` interviews, `128.0` vs `84.3` total calls):** `SolverPolicy` performs **0.0 interviews** per episode (`84.3` total tool calls), plants **14.1 +/- 1.8 canaries** (`66.7%` of the 2/day capacity, planting on `90.6%` of days starting on day `1.0`), isolates a consistent set of size 1 in `26/30` seeds by day `10.6`, and achieves mean score **0.499 +/- 0.119** (`0.499` luck-adjusted). By contrast, `gemini-4-carbon` over OpenCode/MCP makes **128.0 total calls** including **68.0 interviews per episode** (`57.3` in-process), plants only **8.5 +/- 1.3 canaries** (`31.5%` of capacity, planting on `38.2%` of days, first canary on day `3.0`), and scores **0.322 +/- 0.199** (`65%` of solver raw; `0.360` or `72%` luck-adjusted, raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`). On `242` of the `303` days where Gemini planted fewer than 2 canaries, it consumed all `8` daily actions, spending `1,503` of those actions on `interview`.
- **Why the loss manifests at commitment (`3.39 V` lost):** Waiting later (`day 13.4` vs `10.6`, or `13.2` across the 29 accused seeds) costs `+1.75 V` in extra leak damage across 30 seeds, which is nearly offset by `-1.69 V` in unbought canaries. The real damage of substituting `interview` for `plant_canary` is **thin evidence when committing**: Gemini made `9/29` accusations while `>= 2` employees were still consistent with every surfaced leak (solver: `3/30`, mean consistent-set size `1.83` vs `1.07`), including `3` negative-EV gambles near the horizon (`seeds 5, 18, 23` accounting for `1.64 V`), losing **+3.39 V** in expected accusation value plus **+0.62 V** on `seed 11` (`121` interviews, consistent set stuck at `7`, forced abstention).
- **Representative episode pathologies:**
  - *Seed 4:* Gemini plants `0` canaries on days `1-4` while running `6-7` interviews/day (`84` total interviews), reaching accusation on day `16` (`+0.40`), whereas `SolverPolicy` plants `2` canaries/day from day `1` and accuses the mole on day `5` (`+0.73`).
  - *Seed 18:* After narrowing to `4` consistent suspects (`e09, e27, e29, e37`) on day `12`, Gemini plants `0` canaries on days `14-17`, runs `6-7` interviews/day (`101` total), and gambles on innocent `e29` on day `18` at `P = 0.627`, `EV = -0.083` (`-1.00` vs solver `+0.52`).

---

## 4. Concrete Proposals for Silas (`v1.5` / `v1.6` Interview & Social Layer)

Proposals **P1.1** and **P1.2** specify opt-in `v1.5`/`v1.6` mechanics for Silas's core environment (`canary/rules.py`, `canary/env.py`, `canary/solver/belief.py`), preserving `v1.4` frozen hashes (`a8f99c2537c91d72`) when flags default to `False`. Proposal **P1.3** specifies a **zero-protected-path `v1.6` social bias generator** (`canary/social/biases.py`) that requires zero edits to `canary/env.py`, `canary/rules.py`, or `canary/solver/`. Every proposal maintains **strictly zero hidden mole leakage** ($I(\text{Public Cue}; \text{Mole}) = 0$).

---

### Proposal P1.1: Strategic Use of Evidence (SUE) Evidence-Conditioned Interview LR (`v1.5`/`v1.6` Core)

#### Research Justification
In Hartwig et al. (2005, 2006) and Tekin et al. (2015), ungrounded questioning without diagnostic case evidence yields `56.1%` accuracy, whereas withholding and then confronting suspects with specific incriminating evidence raises accuracy to `85.4%` via statement-evidence inconsistency (supported by Hartwig & Bond, 2011 and Vrij et al., 2008, 2009). In `v1.4`, all interviews share a flat `interview_lr = 1.2`, making `interview` strictly dominated for `SolverPolicy` (`0` calls) while treating Day 1 blind fishing identically to Day 12 evidence-backed confrontation.

Proposal **P1.1** splits interviewing into two empirically grounded regimes:
- **Ungrounded fishing (`interview_lr_ungrounded = 1.05`):** Calling `interview(employee, topic)` without naming a corroborated leaked document (or naming a document that has not surfaced, is outside `sue_window_days`, or was not held by `employee`) yields `LR = 1.05` at calm baseline (`p_inn = 0.20`, `p_mole = 0.21`, `KL = 0.00031` nats, `15.4x` weaker than `v1.4` hard). Blind Day 1-4 interview sweeps become pure deadweight loss.
- **SUE-grounded confrontation (`interview_lr_sue = 1.80`):** Calling `interview(employee, topic="recent_documents", evidence_doc=doc_id)` where `doc_id` is **publicly surfaced** (`surfaced_day <= today`), falls within the active SUE recall window (`today - doc.day <= sue_window_days`), and was **publicly held** by `employee` (`employee in doc.recipients`) yields `LR = 1.80` at calm baseline (`p_inn = 0.20`, `p_mole = 0.36`, `LLR(+) = +0.5878` nats, `LLR(-) = -0.2231` nats, `KL = 0.06879` nats).
- **Anti-farming surprise constraint:** Following Hartwig et al. (2005, 2006) and Vrij et al. (2009), surprise confrontation with a specific piece of evidence works *once*. SUE confrontation RNG is keyed by `(world_seed, "sue", employee, evidence_doc)` (independent of `day`), so re-asking `employee` about the same `evidence_doc` on later days repeats the same answer rather than granting free i.i.d. draws. Canaries (`0.86544` nats/leak) remain the primary search engine (`12.6x` higher MI than SUE), while SUE becomes a legitimate `0.06879`-nat zero-V-cost tie-breaker on a narrowed 2-4 suspect endgame set when canary capacity (`2/day`) is already saturated.

#### Exact Mathematical Specification
Let $G(e, q, d) \in \{0, 1\}$ denote the **public SUE grounding predicate** on day $d$ for employee $e$ and optional queried document $q$:

$$G(e, q, d) = \mathbb{I}\!\Big[q \neq \varnothing \;\land\; \text{topic} = \texttt{"recent\_documents"} \;\land\; \exists f \in \text{Feed}_{\le d}: f.\text{doc\_id} = q \;\land\; e \in \text{Recipients}(q) \;\land\; (d - \text{day}(q) \le W_{\text{sue}})\Big]$$

At calm baseline $p_0 = p_{\text{evasive\_innocent}} = 0.20$, define the effective probability multiplier $\lambda_{\text{eff}} \in \{1.80, 1.05\}$ and convert to a constant odds multiplier $\text{OR}_{\text{eff}}$ (so P1.1 composes cleanly with P1.2 without probability clipping blowups):

$$\text{OR}_{\text{eff}}(e, q, d) = \frac{p_0 \lambda_{\text{eff}} / (1 - p_0 \lambda_{\text{eff}})}{p_0 / (1 - p_0)} = \begin{cases} 2.2500 & \text{if } G(e, q, d) = 1 \\ 1.0633 & \text{if } G(e, q, d) = 0 \end{cases}$$

#### Code-Ready Spec (`TierParams`, `Env`, `SolverPolicy`, `MoleStrategy`)

1. **`canary/rules.py` (`TierParams` additive fields + `apply_noise`):**
   Add `sue_interview: bool = False`, `interview_lr_ungrounded: float = 1.05`, `interview_lr_sue: float = 1.80`, `sue_window_days: int = 6`. In `apply_noise(params, noise=k)`, shrink both `interview_lr_ungrounded` and `interview_lr_sue` toward `1.0` via `1 + (lr - 1) / k`.
2. **`canary/env.py` (`_SPECS["interview"]` and `_t_interview`):**
   Add optional `"evidence_doc": {"type": "string"}` to `interview` parameters. Compute `grounded` strictly from `self._feed` entries with `surfaced_day <= self.day` and public `doc["recipients"]`. Key RNG by `f"{self._world.world_seed}:sue:{emp}:{evidence_doc}"` when `grounded` else `f"{self._world.world_seed}:iv:{emp}:{topic}:{self.day}"`.
3. **`canary/solver/belief.py` & `canary/solver/policy.py`:**
   Deduplicate `(emp, evidence_doc)` SUE queries in `Observations.interviews`. In `SolverPolicy._plan()`, after planting up to `canaries_per_day` canaries and reading feed/logs, spend spare free actions (`actions_left_today > 0`) on unseen `(emp, evidence_doc)` SUE pairs when `2 <= len(alive_core) <= 4` (`+0.06879` nats/action at `0.00 V` cost, widening the solver-vs-LLM frontier gap!).
4. **`canary/mole/dsl.py` (`MoleStrategy` SUE counter-strategy):**
   Reflecting Tekin et al. (2015) on suspects' counter-interrogation strategies, a mole leaking `oldest` (`age_days = 2`, surfacing at `today - doc.day = 4..5` under `delay_choices = (2, 3)`) or `most_recipients` (`16` holders across two departments) dilutes the investigator's 8-action budget and shrinks the remaining `sue_window_days = 6` confrontation window to `1..2` days.

---

### Proposal P1.2: Decoy and Public-Stress Anxiety Decoupling (`v1.5`/`v1.6` Othello Error Layer)

#### Research Justification
Bond & DePaulo (2006) establish across 206 documents that *"people appear deceptive when motivated to be believed,"* and DePaulo et al. (2003) show that tension (`d = 0.27`), negative complaints (`d = 0.21`), and identity-relevant scrutiny elevate distress regardless of guilt. In Canary `v1.4` (`docs/DIFFICULTY.md` D11), every innocent employee has an identical flat `p_evasive_innocent = 0.20`, even when publicly restricted (`restrict_access`) or targeted by workplace grievances/rumours.

Proposal **P1.2** decouples **public workplace stress** from **hidden mole guilt** with strictly **zero hidden mole leakage**:

1. **Zero-leakage public stress baseline $p_{\text{base}}(e, d)$:** For employee $e$ interviewed on day $d$, let $r_{e,d} = \mathbb{I}[e \in \text{restricted}_d] \in \{0, 1\}$ and let $m_{e,<d} \in \mathbb{Z}_{\ge 0}$ be the count of closed-day (`day < d`) public messages carrying a grievance/rumour subject tag for $e$ (generated purely from public `PublicDayFacts` without reading `world.mole`, so $I(\text{Rumours}; \text{Mole}) = 0$):
   $$p_{\text{base}}(e, d) = \min\!\Big(p_{\text{evasive\_cap}},\; p_{\text{evasive\_innocent}} + \delta_{\text{restrict}} \cdot r_{e,d} + \delta_{\text{rumour}} \cdot \min(m_{e,<d},\, m_{\max})\Big)$$
   with calibrated defaults $p_{\text{evasive\_innocent}} = 0.20$, $\delta_{\text{restrict}} = 0.15$, $\delta_{\text{rumour}} = 0.08$, $m_{\max} = 3$, and $p_{\text{evasive\_cap}} = 0.55$.
2. **Constant odds-ratio mole scaling:** Mole status multiplies baseline odds $\text{odds}_{\text{base}} = p_{\text{base}} / (1 - p_{\text{base}})$ by $\text{OR}_{\text{eff}}$.

#### Verified Numerical Behavior and Anti-Exploit Check

| Employee Public State `(r, m)` | `P(evasive \| innocent)` | `P(evasive \| mole)` (Ungrounded `OR=1.0633`) | `KL` Ungrounded | `P(evasive \| mole)` (SUE `OR=2.2500`) | `KL` SUE | Naive SUE Expected Drift on Innocent |
|---|---:|---:|---:|---:|---:|---:|
| Calm `(r=0, m=0)` | `0.200` | `0.210` | `0.00031` nats | `0.360` | `0.06879` nats | `-0.06096` nats/iv (exonerates) |
| Restricted `(r=1, m=0)` | `0.350` | `0.364` | `0.00043` nats | `0.548` | `0.08134` nats | `+0.06068` nats/iv (false drift!) |
| Rumoured / Decoy `(r=0, m=2)` | `0.360` | `0.374` | `0.00044` nats | `0.559` | `0.08144` nats | `+0.06879` nats/iv (false drift!) |
| Restricted + Rumoured `(r=1, m=2)` | `0.510` | `0.525` | `0.00047` nats | `0.701` | `0.07510` nats | **`+0.19043` nats/iv (Othello trap!)** |

- **Othello inversion traps non-Bayesian LLMs while leaving `SolverPolicy` unbiased:** A restricted, rumoured **innocent** answers evasively **51.0%** of the time, whereas an unrestricted, calm **mole** answers evasively only **21.0%** on ungrounded interviews (`36.0%` on SUE). `SolverPolicy` conditions on public `(r, m)` in `O(1)` time (`interview_llr(p_base, or_eff, evasive)`) with zero bias, whereas an LLM attributing raw evasiveness to guilt accumulates `+0.19043` nats of bogus log-odds per interview (`+1.14` nats or `3.1x` false odds inflation over 6 interviews).
- **Anti-exploit guarantee:** Because mole status scales odds rather than linearly inflating KL, restricting an employee changes ungrounded KL by only `+0.00016` nats at a cost of `0.01 V/day`, preventing any restriction-for-SNR exploit.

---

### Proposal P1.3: Zero-Protected-Path `v1.6` Social `demeanor_lure` Bias Generator (`canary/social/biases.py`)

#### Research Justification & Immediate `v1.6` Applicability
While **P1.1** and **P1.2** target `canary/rules.py` and `canary/env.py`, Canary's `v1.6` social layer (`V16SocialProvider` in `canary/social/`) operates strictly through `PublicDayFacts` (`SocialDayContext`) with **zero edits to protected files**. Hartwig & Bond (2011) prove across 153 samples that human observers overwhelmingly judge deception from perceived *incompetence* (`r = .59`) and *ambivalence* (`r = .49`), and Bond & DePaulo (2006) show that high motivation to be believed triggers false deception judgments.

Proposal **P1.3** adds `gen_demeanor_lure(ctx: SocialDayContext, rng: random.Random, **kw)` to `canary/social/biases.py`:

1. **Zero-mole-info target selection (`I(Lure; Mole) = 0`):** Using only public `SocialDayContext` (`facts.seed`, `facts.day`, `facts.employees`, `facts.surfaced_leaks` or `facts.restricted`, excluding `facts.decoy` when rotating secondary lures), deterministically select 1-2 lure targets from the public recipient union of already-surfaced regular leaks (never accessing `world.mole`, so every consistent suspect - mole or innocent - has identical prior probability of being chosen).
2. **Perceived-deception prototype phrasing (passes `ANGER_WORDS` scrub):** Non-decoy peers post routine compliance-review Slack/email observations exhibiting Hartwig & Bond's (2011) two strongest perceived-deception cues (`incompetence/flustered recall` `r = .59` and `ambivalence/hedging` `r = .49`) plus an explicit action-budget lure:
   - *"Quick heads-up from the doc-audit sync: {target} seemed unusually hesitant and kept hedging on timeline details when asked about recent handoffs - might be worth an interview check on recent_documents or contacts_outside."*
   - *"Follow-up on {doc_id} distribution check: {target} was overly eager to explain their workflow twice without being asked; felt ambivalent compared to the rest of {dept}."*
3. **Predicted impact on the `gemini-4-carbon` vs `SolverPolicy` frontier gap:**
   - **`SolverPolicy` (`0.000 V` loss):** Ignores surface message prose (`I(Messages; Mole) = 0`), plants `2` canaries/day from Day 1, runs `0` interviews, and preserves its exact `0.499` score.
   - **`gemini-4-carbon` (widens gap via two empirically verified failure modes):** First, explicit interview-bait cues reinforce Gemini's Day 1-15 habit of burning its `8/day` action budget on `0.00477`-nat interviews instead of the second daily `plant_canary` slot (`242/303` under-planted days in `v1.4`). Second, when Gemini reaches commitment with `>= 2` consistent suspects (`9/29` accusations in `v1.4`, costing `3.39 V`), anchoring on the `demeanor_lure` peer tilts unresolved `1/k` consistent-set bets away from the mole onto an innocent holder.

---

## 5. Summary Reference Table

| Study | Venue & Year | Live HTTP-Verified Link | Key Quantitative / Theoretical Finding | Canary Mapping |
|---|---|---|---|---|
| Bond & DePaulo | *PSPR* (2006) | https://pubmed.ncbi.nlm.nih.gov/16859438/ | `206` docs, `24,483` judges: `54%` accuracy (`47%` lies, `61%` truths); motivation to be believed looks deceptive | Explains why ungrounded `interview` loops (`68.0`/ep in Gemini) fail and trigger Othello errors |
| DePaulo et al. | *Psych. Bull.* (2003) | https://pubmed.ncbi.nlm.nih.gov/12555795/ | `1,338` estimates, `158` cues: median `\|d\| = 0.10`, tension `d = 0.27`, complaints `d = 0.21`; identity-relevant stakes | Matches `v1.4` hard `interview_lr = 1.2` (`d = 0.097`) and grounds **P1.2** stress decoupling |
| Hartwig & Bond | *Psych. Bull.* (2011) | https://pubmed.ncbi.nlm.nih.gov/21707129/ | Lens model (`153` samples, `66` cues): incompetence `r = .59`, ambivalence `r = .49`; cue weakness (`r = .59-.72` match) requires widening differences | Explains why `Env.instruction()` LR disclosure fails on passive `interview` and grounds **P1.1** + **P1.3** |
| Luke | *Persp. Psych. Sci.* (2019) | https://pubmed.ncbi.nlm.nih.gov/31173537/ | Monte Carlo + empirical audit: published cue `d` values inflated by small samples & publication bias | Supports dropping ungrounded fishing LR to `1.05` (`KL = 0.00031` nats) in **P1.1** |
| Levine | *JLSP* (2014) | https://api.crossref.org/works/10.1177/0261927X14535916 | Truth-Default Theory: passive demeanor fails; contextual content & hard third-party evidence drive discovery | Validates `SolverPolicy` (`14.1` canaries, `0` ungrounded interviews) over demeanor reading |
| Vrij et al. | *TICS* (2006) | https://pubmed.ncbi.nlm.nih.gov/16516533/ | Active cognitive-load manipulation framework for deception detection | Theoretical bridge from passive questioning to targeted diagnostic probing |
| Vrij et al. | *Law Hum. Behav.* (2008) | https://pubmed.ncbi.nlm.nih.gov/17694424/ | `N = 80` suspects, `N = 55` officers: reverse-order cognitive load increases diagnostic cues without response bias | Grounds higher diagnosticity only under active event-specific recall constraints |
| Vrij et al. | *Law Hum. Behav.* (2009) | https://pubmed.ncbi.nlm.nih.gov/18523881/ | Unanticipated spatiotemporal questions reach up to `80%` classification vs rehearsed opening answers | Grounds why anticipated generic topics (`workload`) yield near-zero signal (`LR = 1.05`) |
| Hartwig et al. | *Law Hum. Behav.* (2005) | https://pubmed.ncbi.nlm.nih.gov/16133950/ | `N = 116` observers: Late evidence disclosure reaches `61.7%` (`67.6%` on lies) vs `42.9%` Early disclosure | Grounds withholding canary identity in `MoleView` and confronting only post-leak |
| Hartwig et al. | *Law Hum. Behav.* (2006) | https://pubmed.ncbi.nlm.nih.gov/16977348/ | `N = 82` trainees: Strategic Use of Evidence (SUE) raises accuracy from `56.1%` to `85.4%` | Direct mechanism for **P1.1** (`LR = 1.80` when confronting holder with surfaced leaked doc) |
| Tekin et al. | *Law Hum. Behav.* (2015) | https://pubmed.ncbi.nlm.nih.gov/25844517/ | `N = 90`: `SUE-Confrontation` increases statement-evidence inconsistencies & admissions; shifts counter-strategies | Grounds one-shot SUE confrontation and `MoleStrategy` window-dilution counter-play |
| Newman et al. | *PSPB* (2003) | https://pubmed.ncbi.nlm.nih.gov/15272998/ | `5` samples: LIWC text style drops from `67%` within-topic to `61%` cross-topic; negative-emotion overlap | Explains why angry `decoy` messages (`_ANGRY`) mimic deceptive negative-emotion lexicons |
| Hancock et al. | *Discourse Proc.* (2008) | https://api.crossref.org/works/10.1080/01638530701739181 | `242` CMC transcripts: liars write *more* words; partners gain zero detection accuracy from text style | Explains why `search_messages` surface prose carries zero reliable mole signal |
| Hauch et al. | *PSPR* (2015) | https://pubmed.ncbi.nlm.nih.gov/25387767/ | Meta-analysis (`44` studies, `79` software cues): small overall effect, liars not more uncertain, strong moderation | Confirms `PublicDayFacts` design (`I(Messages; Mole) = 0`) and **P1.3** `demeanor_lure` |
