# 01. Deception Detection and Investigative Interviewing: Research Grounding for Canary

**Squad:** `research` (`canary-research-w1`)  
**Baseline commit:** `622ae4f1` (`origin/justSilas`, rules `v1.4`)  
**Scope:** Empirical psychology and investigative interviewing foundations for Canary's `interview` tool, surface text channels (`search_messages`, `read_message`), active trap design (`plant_canary`), and concrete `v1.5`/`v1.6` bias-layer proposals for Silas (`canary/rules.py`, `canary/env.py`, `canary/mole/dsl.py`, `canary/solver/belief.py`).

---

## 1. Executive Thesis: Why Frontier Agents Fall into the Demeanor Trap

Across 50 years of experimental psychology, law-enforcement interviewing research, and computational psycholinguistics, one empirical finding dominates all others: **passive observation of demeanor, evasiveness, and surface linguistic style cannot reliably separate liars from truth-tellers, whereas diagnostic hard evidence and active evidence-grounded traps achieve high discrimination.**

Canary `v1.4` already encodes the first half of this reality mathematically, and frontier LLM agents fail precisely because they behave like untrained human interrogators rather than Bayesian experiment designers:

1. **Human and ungrounded interview discrimination sits near chance (~54%).** Meta-analytic synthesis across 206 documents and 24,483 judges shows real-time lie-truth classification averages 54% (47% sensitivity on lies, 61% specificity on truths), because behavioral cues to deceit are faint (median `|d| = 0.10` across multi-estimate cues) and heavily confounded with innocent stress under suspicion (DePaulo et al., 2003; Bond & DePaulo, 2006; Luke, 2019).
2. **Real-world deception discovery comes from diagnostic external evidence, not demeanor.** Truth-Default Theory (Levine, 2014) and Strategic Use of Evidence (Hartwig et al., 2006) demonstrate that accurate investigators rely on hard physical/documentary attribution and strategic confrontation with case-specific evidence (`85.4%` accuracy for SUE-trained interviewers vs `56.1%` for untrained interviewers).
3. **`gemini-4-carbon` reproduces the classic human investigator bias on Canary `v1.4` hard.** On `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_evasive_innocent = 0.20`, `interview_lr = 1.20`), a single interview carries Kullback-Leibler divergence `KL(Mole || Innocent) = 0.00477` nats (`d = 0.097`), whereas a leaked 3-variant canary (`max_variants = 3`, `fingerprint_accuracy = 0.95`) carries `0.8654` nats (`181x` the information gain, `+3.6376` nats log-likelihood shift on a matching label). Despite every parameter being printed in `Env.instruction()`, `gemini-4-carbon` over OpenCode/MCP spends **68 interviews per episode** (exhausting its 8-action daily budget on 242 of 303 under-planted days) and plants only **8.5 canaries** (`32%` capacity) vs `SolverPolicy`'s **0 interviews** and **14.1 canaries** (`67%` capacity). That under-exploration leaves `>= 2` suspects consistent with every leak in `9/29` accusations, costing **3.39 V** of expected value across 30 paired seeds (`docs/reports/failure_analysis_v1.4.md`).

Section 2 documents nine verified primary papers with live DOI/OA links and verbatim quotes. Section 3 maps those findings quantitatively to Canary `v1.4`. Section 4 delivers two drop-in, zero-leakage proposals (**P1.1: SUE Evidence-Conditioned Interview LR** and **P1.2: Decoy and Public-Stress Anxiety Decoupling**) for Silas's `v1.5`/`v1.6` human-bias and deception layer.

---

## 2. Primary Literature Grounding (Verified Citations and Verbatim Quotes)

### 2.1 Near-Chance Demeanor Judgment and Truth-Bias: Bond & DePaulo (2006)

- **Citation:** Bond, C. F., Jr., & DePaulo, B. M. (2006). Accuracy of Deception Judgments. *Personality and Social Psychology Review*, 10(3), 214-234.
- **Link / DOI:** https://doi.org/10.1207/s15327957pspr1003_2 (PMID: `16859438`)
- **Sample & Design:** Meta-analysis of `206` documents encompassing `24,483` judges evaluating real-time truthful and deceptive statements without external physical/documentary evidence aids.
- **Verbatim Quote (Abstract):**
> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges. In relevant studies, people attempt to discriminate lies from truths in real time with no special aids or training. In these circumstances, people achieve an average of 54% correct lie-truth judgments, correctly classifying 47% of lies as deceptive and 61% of truths as nondeceptive."
- **Verbatim Quote on Motivation and Innocent Suspicion (Abstract):**
> "Our meta-analyses reveal that people are more accurate in judging audible than visible lies, that people appear deceptive when motivated to be believed, and that individuals regard their interaction partners as honest."
- **Relevance to Canary:** Ungrounded one-on-one questioning without external documentary corroboration yields near-chance classification (`54%` overall, `47%` hit rate on actual liars). Worse, high motivation to be believed makes *both* liars and suspected innocents appear deceptive (the Othello error), turning naive interview loops into false-incrimination generators.

### 2.2 Weak Effect Sizes of Behavioral Cues and Innocent High-Stakes Anxiety: DePaulo et al. (2003)

- **Citation:** DePaulo, B. M., Lindsay, J. J., Malone, B. E., Muhlenbruck, L., Charlton, K., & Cooper, H. (2003). Cues to Deception. *Psychological Bulletin*, 129(1), 74-118.
- **Link / DOI:** https://doi.org/10.1037/0033-2909.129.1.74 | Open-Access PDF: https://dukespace.lib.duke.edu/handle/10161/14941 (PMID: `12555795`)
- **Sample & Design:** Quantitative synthesis of `1,338` independent effect-size estimates across `158` behavioral, vocal, and verbal cues to deception (`88` cues with `k >= 3` independent estimates).
- **Verbatim Quote on Scope and Faintness (Abstract):**
> "The combined results of 1,338 estimates of 158 cues to deception are reported. Results show that in some ways, liars are less forthcoming than truth tellers, and they tell less compelling tales. They also make a more negative impression and are more tense. Their stories include fewer ordinary imperfections and unusual contents. However, many behaviors showed no discernible links, or only weak links, to deceit."
- **Verbatim Quote on Median Cue Strength (Full Text, p. 97):**
> "The median effect size of the 88 cues was just |0.10|. Only 3 of these cues had effect sizes greater than |0.40|."
- **Verbatim Quote on High-Stakes Innocent Nervousness (Full Text, p. 105):**
> "But truth tellers may also seem more nervous in the high stakes setting. Nervousness would only be a cue to deception in the murder trial if liars feel even more nervous than truth tellers."
- **Key Verified Cue Effect Sizes (Table 5 & Table 6, Full Text):**
  - Nervous, tense overall (`Cue 061`, `k = 16`): `d = 0.27` (95% CI `[0.16, 0.38]`)
  - Vocal tension (`Cue 062`, `k = 10`): `d = 0.26` (95% CI `[0.13, 0.39]`)
  - Vocal pitch / frequency (`Cue 063`, `k = 12`): `d = 0.21` (95% CI `[0.08, 0.34]`)
  - Negative statements and complaints (`Cue 052`, `k = 9`): `d = 0.21` (95% CI `[0.09, 0.32]`)
  - Blinking (`Cue 066`, `k = 17`): `d = 0.07` (nonsignificant); relaxed posture (`Cue 064`, `k = 13`): `d = -0.02` (nonsignificant).
- **Relevance to Canary:** Canary `v1.4` hard sets `p_evasive_innocent = 0.20` and `interview_lr = 1.20` (`p_evasive_mole = 0.24`), which corresponds to a standardized binary effect size of `d = 0.097` (Hasselblad-Hedges log-odds `d_HH = 0.129`), matching DePaulo et al.'s empirical median `|d| = 0.10` almost to two decimal places. Furthermore, Cue 052 (`negative statements and complaints`, `d = 0.21`) and high-stakes innocent nervousness explain why a disgruntled or restricted innocent employee looks indistinguishable from (or more suspicious than) a calm mole.

### 2.3 Publication Bias and Low Informational Value of Standalone Cues: Luke (2019)

- **Citation:** Luke, T. J. (2019). Lessons From Pinocchio: Cues to Deception May Be Highly Exaggerated. *Perspectives on Psychological Science*, 14(4), 646-671.
- **Link / DOI:** https://doi.org/10.1177/1745691619838258 (PMID: `31173537`)
- **Sample & Design:** Re-analysis of empirical deception-cue meta-analyses combined with Monte Carlo simulations of small-sample publication bias and low statistical power.
- **Verbatim Quote (Abstract):**
> "By examining data from empirical deception-cue research and using a series of Monte Carlo simulations, I demonstrate that many estimated effect sizes of deception cues may be greatly inflated by publication bias, small numbers of estimates, and low power. Indeed, simulations indicate the informational value of the present deception literature is quite low, such that it is not possible to determine whether any given effect is real or a false positive."
- **Relevance to Canary:** Even the small `d ~ 0.10` to `0.25` behavioral effects in published literature represent an upper bound inflated by selective reporting. An autonomous investigator that prioritizes ungrounded behavioral interviews over controlled attribution experiments (`plant_canary`) is chasing statistical noise.

### 2.4 Truth-Default Theory (TDT) and Diagnostic Evidence Triggers: Levine (2014)

- **Citation:** Levine, T. R. (2014). Truth-Default Theory (TDT): A Theory of Human Deception and Deception Detection. *Journal of Language and Social Psychology*, 33(4), 378-392.
- **Link / DOI:** https://doi.org/10.1177/0261927X14535916
- **Theory & Empirical Synthesis:** Formalizes why passive truth-bias is ecologically rational when most workplace communications are honest (in Canary `v1.4` hard, `39/40 = 97.5%` of staff are innocent) and why accurate lie detection outside the laboratory occurs not by reading arousal or demeanor in real time, but by comparing contextualized content against third-party corroboration and hard physical/audit evidence.
- **Verbatim Quote (Abstract):**
> "Unlike previous theories of deception detection, TDT emphasizes contextualized communication content in deception detection over nonverbal behaviors associated with emotions, arousal, strategic self-presentation, or cognitive effort."
- **Relevance to Canary:** TDT directly explains why Canary's optimal policy (`SolverPolicy`) treats document-recipient intersection and canary variant attribution (`check_leak_feed` + `list_documents` + `plant_canary`) as primary diagnostic triggers, rather than trying to infer guilt from surface chatter (`search_messages`) or passive demeanor (`interview`).

### 2.5 Active Cognitive-Load Interviewing: Vrij et al. (2006, 2008, 2009)

- **Citation 1 (Framework):** Vrij, A., Fisher, R., Mann, S., & Leal, S. (2006). Detecting deception by manipulating cognitive load. *Trends in Cognitive Sciences*, 10(4), 141-142. DOI: https://doi.org/10.1016/j.tics.2006.02.003 (PMID: `16516537`)
- **Citation 2 (Reverse-Order Experiment):** Vrij, A., Mann, S. A., Fisher, R. P., Leal, S., Milne, R., & Bull, R. (2008; online 2007). Increasing cognitive load to facilitate lie detection: The benefit of recalling an event in reverse order. *Law and Human Behavior*, 32(3), 253-265. DOI: https://doi.org/10.1007/s10979-007-9103-y (PMID: `17694424`)
- **Citation 3 (Unanticipated Questions):** Vrij, A., Leal, S., Granhag, P. A., Mann, S., Fisher, R. P., Hillman, J., & Sperry, K. (2009). Outsmarting the liars: The benefit of asking unanticipated questions. *Law and Human Behavior*, 33(2), 159-166. DOI: https://doi.org/10.1007/s10979-008-9143-y (PMID: `18546065`)
- **Verbatim Quote from Vrij et al. (2008) (Abstract):**
> "In Experiment 1, 80 mock suspects told the truth or lied about a staged event and did or did not report their stories in reverse order. The reverse order interviews contained many more cues to deceit than the control interviews. In Experiment 2, 55 police officers watched a selection of the videotaped interviews of Experiment 1 and made veracity judgements. Requesting suspects to convey their stories in reverse order improved police observers' ability to detect deception and did not result in a response bias."
- **Verbatim Quote from Vrij et al. (2009) (Abstract):**
> "The interviewer asked typical opening questions which we expected the liars to anticipate, followed by questions about spatial and/or temporal information which we expected suspects not to anticipate, and also a request to draw the layout of the restaurant. The results supported the hypothesis, and based on correspondence in responses to the unanticipated questions, up to 80% of liars and truth tellers could be correctly classified, particularly when assessing drawings."
- **Relevance to Canary:** Generic, anticipated questions (like Canary's ungrounded `workload` or `contacts_outside` prompts) allow a prepared mole to answer smoothly with rehearsed cover stories (`LR ~ 1.05`). Diagnostic signal emerges only when the interviewer imposes targeted cognitive load around specific, unanticipated spatiotemporal/document events that the suspect actually held.

### 2.6 Strategic Use of Evidence (SUE): Hartwig, Granhag, Stromwall & Kronkvist (2006)

- **Citation:** Hartwig, M., Granhag, P. A., Stromwall, L. A., & Kronkvist, O. (2006). Strategic use of evidence during police interviews: When training to detect deception works. *Law and Human Behavior*, 30(5), 603-619.
- **Link / DOI:** https://doi.org/10.1007/s10979-006-9053-9 (PMID: `16977348`)
- **Sample & Design:** Controlled experiment with `N = 82` police trainees interviewing `N = 82` guilty or innocent mock suspects. Trainees trained in the Strategic Use of Evidence (SUE) withheld incriminating evidence initially, elicited free recall and specific commitments around the evidence window, and strategically confronted suspects to test statement-evidence consistency.
- **Verbatim Quote (Abstract):**
> "Trained interviewers applied different strategies than did untrained. As a consequence of this, liars interviewed by trained interviewers were more inconsistent with the evidence compared to liars interviewed by untrained interviewers. Trained interviewers created and utilized the statement-evidence consistency cue, and obtained a considerably higher deception detection accuracy rate (85.4%) than untrained interviewers (56.1%)."
- **Relevance to Canary:** Hartwig et al. (2006) provide the exact empirical blueprint for Proposal **P1.1**. Untrained interviewers who question suspects *without* leveraging diagnostic evidence score `56.1%` (indistinguishable from Bond & DePaulo's `54%` baseline). Interviewers who first gather case evidence (in Canary: surfaced leaked documents in `check_leak_feed` cross-referenced with recipient lists in `list_documents`) and then question holders about that specific leaked-document window raise accuracy to `85.4%` via statement-evidence inconsistency.

### 2.7 Linguistic Style and Cross-Topic Degradation: Newman, Pennebaker, Berry & Richards (2003)

- **Citation:** Newman, M. L., Pennebaker, J. W., Berry, D. S., & Richards, J. M. (2003). Lying Words: Predicting Deception from Linguistic Styles. *Personality and Social Psychology Bulletin*, 29(5), 665-675.
- **Link / DOI:** https://doi.org/10.1177/0146167203029005010 (PMID: `15272998`)
- **Sample & Design:** Automated LIWC psycholinguistic classification across `5` independent studies covering typed and spoken deceptive vs truthful narratives.
- **Verbatim Quote (Abstract):**
> "In an analysis of five independent samples, a computer-based text analysis program correctly classified liars and truth-tellers at a rate of 67% when the topic was constant and a rate of 61% overall. Compared to truth-tellers, liars showed lower cognitive complexity, used fewer self-references and other-references, and used more negative emotion words."
- **Relevance to Canary:** Even automated word-count classifiers drop to `61%` accuracy across topics, and one of their primary features (`more negative emotion words`) directly collides with innocent workplace disgruntlement. In Canary (`canary/text/template.py`), the innocent `decoy` emits high-salience negative-emotion messages (`"burn out"`, `"Skipped for promotion again"`, `"Pay here is a joke"`), creating an ecologically grounded false-positive trap for LLM investigators relying on surface sentiment.

### 2.8 Computer-Mediated Communication (CMC) Cue Reversal: Hancock et al. (2008)

- **Citation:** Hancock, J. T., Curry, L. E., Goorha, S., & Woodworth, M. (2008; online 2007). On Lying and Being Lied To: A Linguistic Analysis of Deception in Computer-Mediated Communication. *Discourse Processes*, 45(1), 1-23.
- **Link / DOI:** https://doi.org/10.1080/01638530701739181
- **Sample & Design:** Dyadic synchronous text-based communication across `242` transcripts comparing truthful and deceptive exchanges under high and low motivation.
- **Verbatim Quote on Cue Reversal and Motivation Dependence (Abstract):**
> "An analysis of 242 transcripts revealed that liars produced more words, more sense-based words (e.g., seeing, touching), and used fewer self-oriented but more other-oriented pronouns when lying than when telling the truth. In addition, motivated liars avoided causal terms when lying, whereas unmotivated liars tended to increase their use of negations."
- **Verbatim Quote on Receiver Detection Failure (Abstract):**
> "The linguistic patterns in both the liar and the partner's language use were not related to deception detection, suggesting that partners were unable to use this linguistic information to improve their deception detection accuracy."
- **Relevance to Canary:** In digital workplace channels (Slack/email text in `search_messages`), deceptive senders do *not* look terse or sketchy; they often produce *more* words and concrete details to blend into routine work chatter, and human/LLM readers gain zero detection lift from surface text style.

### 2.9 Meta-Analytic Limits of Automated Text Lie Detection: Hauch et al. (2015)

- **Citation:** Hauch, V., Blandon-Gitlin, I., Masip, J., & Sporer, S. L. (2015). Are Computers Effective Lie Detectors? A Meta-Analysis of Linguistic Cues to Deception. *Personality and Social Psychology Review*, 19(4), 307-342.
- **Link / DOI:** https://doi.org/10.1177/1088868314556539 (PMID: `25387767`)
- **Sample & Design:** Meta-analysis of `44` studies evaluating `79` software-extracted linguistic cues to deception.
- **Verbatim Quote (Abstract):**
> "These effects were moderated by event type, involvement, emotional valence, intensity of interaction, motivation, and other moderators. Although the overall effect size was small, theory-driven predictions for certain cues received support."
- **Relevance to Canary:** Confirms across 44 studies that automated surface-text cues remain small and context-fragile, justifying Canary's architectural rule (`canary/text/facts.py`) that `PublicDayFacts` passes zero hidden mole identity to `TextProvider`.

---

## 3. Quantitative Mapping to Canary `v1.4` (`622ae4f1`)

### 3.1 Information-Theoretic Comparison: `interview` vs `plant_canary`

In `canary/rules.py` and `canary/env.py` (`_t_interview`, lines 419-427), interviewing employee `e` on `topic` on day `d` draws `signal = "evasive"` with probability `p_ev = p_evasive_innocent * (interview_lr if e == mole else 1.0)`. Both `interview` and `plant_canary` consume **1 investigative action** from the `actions_per_day = 8` budget. Their exact information-theoretic yields per action are starkly asymmetric:

| Channel / Tier (`v1.4`) | `P(evasive \| innocent)` | `P(evasive \| mole)` | `LLR(+)` (evasive) | `LLR(-)` (coop.) | `KL(Mole \|\| Innocent)` | Binary `d` (`d_HH`) |
|---|---:|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | `0.200` | `0.300` | `+0.4055` nats | `-0.1335` nats | `0.02817` nats | `0.232` (`0.297`) |
| `interview` (`medium`, `LR=1.3`) | `0.200` | `0.260` | `+0.2624` nats | `-0.0780` nats | `0.01052` nats | `0.143` (`0.188`) |
| `interview` (`hard`, `LR=1.2`) | `0.200` | `0.240` | `+0.1823` nats | `-0.0513` nats | `0.00477` nats | `0.097` (`0.129`) |
| `plant_canary` (`hard`, `k=3`, `acc=0.95`, given leak) | `0.025` (flip) | `0.950` (true) | `+3.6376` nats | `-2.9957` nats | `0.86539` nats | `> 3.0` |

Key structural facts verified from `canary/rules.py`, `docs/DIFFICULTY.md`, and `docs/reports/failure_analysis_v1.4.md`:

1. **Exact alignment with DePaulo et al. (2003):** On `v1.4` hard, `interview_lr = 1.2` at base rate `0.20` produces standardized binary `d = 0.097`, virtually identical to DePaulo et al.'s empirical median `|d| = 0.10`.
2. **181-to-1 information ratio per leaked trap:** Conditional on leaking, a balanced 3-variant canary on `v1.4` hard (`fingerprint_accuracy = 0.95`) yields `0.8654` nats of mutual information (`1.0986` nats noiseless `ln 3`), which is **181x** the `0.00477`-nat KL divergence of a `v1.4` hard interview. Even accounting for `p_leak = 0.65`, `leak_window_days = 3`, careful-mole weighting (`mean weight = 0.76`), and regular-document competition (`15%` to `22%` per-plant leak realization on `v1.4` hard trajectories), a single `plant_canary` action yields `~0.13` to `0.19` expected nats, or **27x to 40x** an interview.

### 3.2 How `gemini-4-carbon` Fails on `v1.4` Hard (30 Paired Dev Seeds `0-29`)

All empirical figures below come directly from `docs/reports/failure_analysis_v1.4.md` and `results/failure_analysis_v1.4.json` (`scripts/failure_analysis_v14.py` on `622ae4f1`):

- **Action-budget crowding out (`68` vs `0` interviews):** `SolverPolicy` performs **0 interviews** per episode, plants **14.1 +/- 1.8 canaries** (`67%` of the 2/day capacity, planting on `91%` of days starting on day `1.0`), isolates a consistent set of size 1 in `26/30` seeds by day `10.6`, and achieves mean score **0.499 +/- 0.119** (`0.499` luck-adjusted). By contrast, `gemini-4-carbon` over OpenCode/MCP performs **68 interviews per episode** (`57` in-process), plants only **8.5 +/- 1.3 canaries** (`32%` of capacity, planting on `38%` of days, first canary on day `3.0`), and scores **0.322 +/- 0.199** (`65%` of solver raw; `0.360` or `72%` luck-adjusted). On `242` of the `303` days where Gemini planted fewer than 2 canaries, it consumed all `8` daily actions, spending `1,503` of those actions on `interview`.
- **Why the loss manifests at commitment (`3.39 V` lost):** Waiting later (`day 13.4` vs `10.6`) costs `+1.75 V` in extra leak damage across 30 seeds, which is nearly offset by `-1.69 V` in unbought canaries. The real damage of substituting `interview` for `plant_canary` is **thin evidence when committing**: Gemini made `9/29` accusations while `>= 2` employees were still consistent with every surfaced leak (solver: `3/30`), including `3` negative-EV gambles near the horizon (`seeds 5, 18, 23`), losing **+3.39 V** in expected accusation value plus **+0.62 V** on `seed 11` (`121` interviews, consistent set stuck at `7`, forced abstention).
- **Representative episode pathologies:**
  - *Seed 4:* Gemini plants `0` canaries on days `1-4` while running `6-7` interviews/day (`84` total interviews), reaching accusation on day `16` (`+0.40`), whereas `SolverPolicy` plants `2` canaries/day from day `1` and accuses the mole on day `5` (`+0.73`).
  - *Seed 18:* After narrowing to `4` consistent suspects (`e09, e27, e29, e37`) on day `12`, Gemini plants `0` canaries on days `14-17`, runs `6-7` interviews/day (`101` total), and gambles on innocent `e29` on day `18` at `P = 0.63`, `EV = -0.08` (`-1.00` vs solver `+0.52`).

---

## 4. Concrete Proposals for Silas (`v1.5` / `v1.6` Deception & Bias Layer)

Both proposals below are designed to:
1. Preserve `v1.4` frozen hashes (`a8f99c2537c91d72`) when feature flags default to `False`.
2. Maintain **strictly zero hidden mole leakage**: every conditioning variable is computed exclusively from public state (`surfaced_day <= self.day`, public `recipients`, public `restricted`, and closed-day public messages), never from `self._world.mole` or unsurfaced `self._leaked`.
3. Remain **exact-Bayes tractable** in `O(1)` per interview inside `canary/solver/belief.py` and fully disclosed in `Env.instruction()`.

---

### Proposal P1.1: Strategic Use of Evidence (SUE) Evidence-Conditioned Interview LR

#### Research Justification
In Hartwig et al. (2006), ungrounded questioning without diagnostic case evidence yields `56.1%` accuracy, whereas withholding and then confronting suspects with specific incriminating evidence raises accuracy to `85.4%` via statement-evidence inconsistency (supported by Levine, 2014 and Vrij et al., 2008, 2009). In `v1.4`, all interviews share a flat `interview_lr = 1.2`, making `interview` strictly dominated for `SolverPolicy` (`0` calls) while punishing frontier models uniformly whether they fish blindly on Day 1 or ask targeted questions on Day 12.

Proposal **P1.1** splits interviewing into two empirically grounded regimes:
- **Ungrounded fishing (`interview_lr_ungrounded = 1.05`):** Calling `interview(employee, topic)` without naming a corroborated leaked document (or naming a document that has not surfaced, is outside `sue_window_days`, or was not held by `employee`) yields `LR = 1.05` at calm baseline (`p_inn = 0.20`, `p_mole = 0.21`, `KL = 0.00031` nats, `15x` weaker than `v1.4` hard). Blind Day 1-4 interview sweeps become pure deadweight loss.
- **SUE-grounded confrontation (`interview_lr_sue = 1.80`):** Calling `interview(employee, topic="recent_documents", evidence_doc=doc_id)` where `doc_id` is **publicly surfaced** (`surfaced_day <= today`), falls within the active SUE recall window (`today - doc.day <= sue_window_days`), and was **publicly held** by `employee` (`employee in doc.recipients`) yields `LR = 1.80` at calm baseline (`p_inn = 0.20`, `p_mole = 0.36`, `LLR(+) = +0.5878` nats, `LLR(-) = -0.2231` nats, `KL = 0.06879` nats).
- **Anti-farming surprise constraint:** Following Hartwig et al. (2006) and Vrij et al. (2009), surprise confrontation with a specific piece of evidence works *once*. SUE confrontation RNG is keyed by `(world_seed, "sue", employee, evidence_doc)` (independent of `day`), so re-asking `employee` about the same `evidence_doc` on later days repeats the same answer rather than granting free i.i.d. draws. Canaries (`0.8654` nats/leak) remain the primary search engine (`12.6x` higher KL than SUE), while SUE becomes a legitimate `0.069`-nat tie-breaker on a narrowed 2-3 suspect endgame set when canary capacity (`2/day`) is already saturated.

#### Exact Mathematical Specification
Let $G(e, q, d) \in \{0, 1\}$ denote the **public SUE grounding predicate** on day $d$ for employee $e$ and optional queried document $q$:

$$G(e, q, d) = \mathbb{I}\!\Big[q \neq \varnothing \;\land\; \text{topic} = \texttt{"recent\_documents"} \;\land\; \exists f \in \text{Feed}_{\le d}: f.\text{doc\_id} = q \;\land\; e \in \text{Recipients}(q) \;\land\; (d - \text{day}(q) \le W_{\text{sue}})\Big]$$

At calm baseline $p_0 = p_{\text{evasive\_innocent}} = 0.20$, define the effective probability multiplier at $p_0$:

$$\lambda_{\text{eff}}(e, q, d) = \begin{cases} \lambda_{\text{sue}} = 1.80 & \text{if } G(e, q, d) = 1 \\ \lambda_{\text{ungrounded}} = 1.05 & \text{if } G(e, q, d) = 0 \end{cases}$$

and convert to a constant odds multiplier $\text{OR}_{\text{eff}}$ (so P1.1 composes cleanly with P1.2 without probability clipping blowups):

$$\text{OR}_{\text{eff}}(e, q, d) = \frac{p_0 \lambda_{\text{eff}} / (1 - p_0 \lambda_{\text{eff}})}{p_0 / (1 - p_0)} = \begin{cases} 2.2500 & \text{if } G(e, q, d) = 1 \\ 1.0633 & \text{if } G(e, q, d) = 0 \end{cases}$$

When $p_{\text{base}}(e, d) = p_0 = 0.20$, this recovers $P(\text{evasive} \mid \text{mole}) = 0.360$ (`LR = 1.80`) when grounded and $0.210$ (`LR = 1.05`) when ungrounded.

#### Code-Ready Spec (`TierParams`, `Env`, `SolverPolicy`, `MoleStrategy`)

**1. `canary/rules.py` (`TierParams` additive fields + `apply_noise`):**
```python
sue_interview: bool = False
interview_lr_ungrounded: float = 1.05
interview_lr_sue: float = 1.80
sue_window_days: int = 6
```
In `apply_noise(params, noise=k)`: shrink both `interview_lr_ungrounded -> 1 + (interview_lr_ungrounded - 1) / k` and `interview_lr_sue -> 1 + (interview_lr_sue - 1) / k`.

**2. `canary/env.py` (`_SPECS["interview"]` and `_t_interview`):**
```python
"interview": (
    "Interview one employee on a topic, optionally confronting them with one surfaced leaked doc_id.",
    {"employee": _EMP, "topic": {"type": "string", "enum": list(TOPICS)}, "evidence_doc": {"type": "string"}},
    ["employee", "topic"],
)

def _is_sue_grounded(self, emp: str, topic: str, evidence_doc: str | None) -> bool:
    if not self.p.sue_interview or not evidence_doc or topic != "recent_documents":
        return False
    surfaced_ids = {f["doc_id"] for f in self._feed if f["surfaced_day"] <= self.day}
    doc = self._doc_by_id.get(evidence_doc)
    if doc is None or evidence_doc not in surfaced_ids:
        return False
    return emp in doc["recipients"] and (self.day - doc["day"]) <= self.p.sue_window_days

def _interview_or(self, grounded: bool) -> float:
    p0 = self.p.p_evasive_innocent
    lr = (self.p.interview_lr_sue if grounded else self.p.interview_lr_ungrounded) if self.p.sue_interview else self.p.interview_lr
    pm0 = min(0.95, p0 * lr)
    return (pm0 / (1.0 - pm0)) / (p0 / (1.0 - p0))
```
For RNG seeding inside `_t_interview`:
- If `grounded` is `True`: `seed_key = f"{self._world.world_seed}:sue:{emp}:{evidence_doc}"`
- If `grounded` is `False`: `seed_key = f"{self._world.world_seed}:iv:{emp}:{topic}:{self.day}"`

**3. `canary/solver/belief.py` & `canary/solver/policy.py`:**
- Record `(emp, evasive_bool, grounded_bool, dedup_key)` in `Observations.interviews`, deduplicating repeated `(emp, evidence_doc)` SUE queries so re-asking adds zero spurious LLR.
- In `SolverPolicy._plan()`: after planting up to `canaries_per_day` canaries and reading `check_leak_feed` / `read_access_logs`, if `actions_left_today > 0` and `2 <= len(alive_core) <= 4`, greedily spend remaining free daily actions on unseen `(emp, evidence_doc)` SUE pairs among `alive_core` (`+0.069` nats/action at zero V cost!).

**4. `canary/mole/dsl.py` (`MoleStrategy` counter-strategy spec):**
Hartwig et al. (2006) emphasize that strategic liars adopt counter-strategies to minimize statement-evidence exposure. Under P1.1, a mole that leaks wide-distribution documents (`most_recipients`, 16 holders across 2 departments on `hard`) or older window-edge documents (`oldest`, `age_days = 2`, which coupled with `delay_choices = (2, 3)` surfaces at `today - doc.day = 4..5`, leaving only `1..2` days before `sue_window_days = 6` expires!) dilutes the investigator's daily action budget across 16 holders and shortens the SUE confrontation window:
```json
{
  "name": "sue_evasion_v15",
  "rules": [
    {
      "if": [["max_recipient_count", ">=", 14], ["newest_doc_age_days", ">=", 1]],
      "then": {"leak": "oldest", "frame": "most_restricted_peer"}
    },
    {
      "if": [["max_recipient_count", ">=", 12]],
      "then": {"leak": "most_recipients", "frame": "decoy"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "none"}
}
```

---

### Proposal P1.2: Decoy and Public-Stress Anxiety Decoupling (Othello Error Bias Layer)

#### Research Justification
DePaulo et al. (2003, p. 105) warn that *"truth tellers may also seem more nervous in the high stakes setting"*, and Bond & DePaulo (2006) find across 206 studies that *"people appear deceptive when motivated to be believed."* In real organizations, employees placed under access restriction (`restrict_access`) or targeted by workplace gossip/rumours experience acute scrutiny and defensiveness (the Othello error), while disgruntled employees (`decoy`) express negative emotion (`Newman et al., 2003`, Cue 052 `d = 0.21`).

In Canary `v1.4` (`docs/DIFFICULTY.md` D11), every innocent employee has an identical flat `p_evasive_innocent = 0.20`, even when restricted or publicly rumoured. Proposal **P1.2** decouples **public workplace stress** from **hidden mole guilt** with strictly **zero hidden mole leakage**:

1. **Zero-leakage public rumour generation:** In `PublicDayFacts` / `TemplateProvider.day_messages`, closed-day workplace chatter includes `0..2` deterministic rumour/complaint mentions per day seeded solely from `f"rumour:{tier}:{world_seed}:{day}"` over public employee IDs (weighting `decoy` and `restricted` employees higher, **never** reading `world.mole`). Mutual information between rumour counts and mole identity is identically zero: $I(\text{Rumours}; \text{Mole}) = 0$.
2. **Public-stress baseline $p_{\text{base}}(e, d)$:** An employee's innocent evasive probability rises deterministically with current public restriction status $r_{e,d} = \mathbb{I}[e \in R_d]$ and closed-day public rumour/grievance count $m_{e,<d}$ (messages on days $1 \dots d-1$ where $e$ is the disgruntled sender or named rumour subject).
3. **Constant odds-ratio deception coupling:** Mole status multiplies the **odds** of evasiveness by $\text{OR}_{\text{eff}}$ rather than raw probability. As verified numerically below, constant odds-ratio scaling prevents an exploit where an investigator restricts staff merely to inflate KL divergence, while inflicting severe false-incrimination drift on LLM agents that mistake stress-induced evasiveness for guilt!

#### Exact Mathematical Specification
For employee $e$ interviewed on day $d$, let $r_{e,d} = \mathbb{I}[e \in \text{restricted}_d] \in \{0, 1\}$ and let $m_{e,<d} \in \mathbb{Z}_{\ge 0}$ be the count of closed-day (`day < d`) public messages carrying a grievance/rumour tag involving $e$. Define the **innocent stress-adjusted evasive probability**:

$$p_{\text{base}}(e, d) = \min\!\Big(p_{\text{evasive\_cap}},\; p_{\text{evasive\_innocent}} + \delta_{\text{restrict}} \cdot r_{e,d} + \delta_{\text{rumour}} \cdot \min(m_{e,<d},\, m_{\max})\Big)$$

With calibrated defaults $p_{\text{evasive\_innocent}} = 0.20$, $\delta_{\text{restrict}} = 0.15$, $\delta_{\text{rumour}} = 0.08$, $m_{\max} = 3$, and $p_{\text{evasive\_cap}} = 0.55$:

$$P(\text{evasive} \mid e \neq \text{mole}, r_{e,d}, m_{e,<d}) = p_{\text{base}}(e, d)$$

$$P(\text{evasive} \mid e = \text{mole}, r_{e,d}, m_{e,<d}) = \frac{\text{odds}_{\text{base}}(e, d) \cdot \text{OR}_{\text{eff}}}{1 + \text{odds}_{\text{base}}(e, d) \cdot \text{OR}_{\text{eff}}}, \qquad \text{odds}_{\text{base}}(e, d) = \frac{p_{\text{base}}(e, d)}{1 - p_{\text{base}}(e, d)}$$

#### Verified Numerical Behavior and Anti-Exploit Check

| Employee Public State `(r, m)` | `P(evasive \| innocent)` | `P(evasive \| mole)` (Ungrounded `OR=1.063`) | `KL` Ungrounded | `P(evasive \| mole)` (SUE `OR=2.250`) | `KL` SUE | Naive SUE Expected Drift on Innocent |
|---|---:|---:|---:|---:|---:|---:|
| Calm `(r=0, m=0)` | `0.200` | `0.210` | `0.00031` nats | `0.360` | `0.06879` nats | `-0.06096` nats/iv (exonerates) |
| Restricted `(r=1, m=0)` | `0.350` | `0.364` | `0.00043` nats | `0.548` | `0.08134` nats | `+0.06068` nats/iv (false drift!) |
| Rumoured / Decoy `(r=0, m=2)` | `0.360` | `0.374` | `0.00044` nats | `0.559` | `0.08144` nats | `+0.06879` nats/iv (false drift!) |
| Restricted + Rumoured `(r=1, m=2)` | `0.510` | `0.525` | `0.00047` nats | `0.701` | `0.07510` nats | **`+0.19043` nats/iv (Othello trap!)** |

Two critical properties jump out of this table:
1. **Inversion of raw evasive rates traps non-Bayesian LLMs:** A restricted, rumoured **innocent** answers evasively **51.0%** of the time, whereas an unrestricted, unrumoured **mole** answers evasively only **21.0%** of the time on ungrounded interviews (`36.0%` on SUE interviews). An LLM investigator that ignores public stress accumulates `+0.19043` nats of bogus log-odds per interview against the stressed innocent (`+1.14` nats, or `3.1x` false odds inflation, after 6 interviews).
2. **Bounded KL blocks restriction-for-interview-gain exploits:** Because deception scales odds (`OR_eff`), restricting an employee changes ungrounded KL only from `0.00031` to `0.00047` nats (at a direct cost of `restrict_cost_per_day = 0.01 V/day`), so an agent can never profit by restricting suspects merely to amplify interview SNR.

#### Code-Ready Spec (`TierParams`, `PublicDayFacts`, `Env`, `SolverPolicy`, `MoleStrategy`)

**1. `canary/rules.py` (`TierParams` additive fields):**
```python
stress_anxiety: bool = False
stress_restrict_delta: float = 0.15
stress_rumour_delta: float = 0.08
stress_rumour_cap: int = 3
p_evasive_cap: float = 0.55
rumour_rate: float = 1.0
```

**2. `canary/text/facts.py` & `canary/env.py` (Zero-Leakage Public Stress Calculation):**
- In `TemplateProvider.day_messages(facts: PublicDayFacts)`, when `rumour_rate > 0`, sample `k ~ Poisson(rumour_rate)` using `random.Random(f"rumour:{facts.tier}:{facts.seed}:{facts.day}")` (purely public seed, zero access to `world.mole`). Pick subject `subj` with weight `3.0` if `subj == facts.decoy` or `subj in facts.restricted` else `1.0` across `facts.employees`, and emit a message dictionary including `"about": subj` and `"kind": "rumour"` (alongside `"about": facts.decoy, "kind": "grievance"` on `_ANGRY` messages, or detectable via fixed public phrase templates).
- In `Env._p_evasive_base(self, emp: str) -> float`:
```python
def _p_evasive_base(self, emp: str) -> float:
    base = self.p.p_evasive_innocent
    if not self.p.stress_anxiety:
        return base
    r_flag = 1 if emp in self._restricted else 0
    m_cnt = sum(
        1 for mid in self._msg_order
        if self._messages[mid]["day"] < self.day and self._messages[mid].get("stress_subject") == emp
    )
    raw = base + self.p.stress_restrict_delta * r_flag + self.p.stress_rumour_delta * min(m_cnt, self.p.stress_rumour_cap)
    return min(self.p.p_evasive_cap, raw)

def _p_evasive(self, emp: str, grounded: bool) -> float:
    pb = self._p_evasive_base(emp)
    if emp != self._world.mole:
        return pb
    odds_m = (pb / (1.0 - pb)) * self._interview_or(grounded)
    return odds_m / (1.0 + odds_m)
```
Expose `"stress_subject"` (or `rumour_counts` up to `today - 1`) in `read_message` / `search_messages` results so `SolverPolicy` and LLM agents have identical 100% public observability.

**3. `canary/solver/belief.py` (Exact Bayesian Stress Decoupling):**
```python
def interview_llr(p_base: float, or_eff: float, evasive: bool) -> float:
    odds_m = (p_base / (1.0 - p_base)) * or_eff
    p_mole = odds_m / (1.0 + odds_m)
    return math.log(p_mole / p_base) if evasive else math.log((1.0 - p_mole) / (1.0 - p_base))
```
Because `p_base` and `or_eff` depend solely on public `(restricted_at_call, public_stress_count_before_day, is_sue_grounded)`, `SolverPolicy` computes `interview_llr` exactly in `O(1)` time and suffers zero Othello-error bias.

**4. `canary/mole/dsl.py` (`MoleStrategy` Scapegoat Synergy):**
Without touching message generation (keeping $I(\text{Rumours}; \text{Mole}) = 0$), add `"most_rumoured_peer"` to `FRAME_SELECTORS` (selected from public `MoleView.rumoured_peers: tuple[str, ...]`). A mole running `othello_scapegoat_v15` concentrates its after-hours framing onto whichever colleague is already restricted or publicly rumoured, aligning three independent noisy channels (angry/rumoured Slack messages + framed after-hours access logs + 51% stress-induced interview evasiveness) onto a single innocent scapegoat:
```json
{
  "name": "othello_scapegoat_v15",
  "rules": [
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", ">=", 2]],
      "then": {"leak": "random_seeded", "frame": "decoy"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "none"}
}
```

---

## 5. Summary Reference Table

| Study | Venue & Year | Live Link / DOI | Key Quantitative / Theoretical Finding | Canary Mapping |
|---|---|---|---|---|
| Bond & DePaulo | *PSPR* (2006) | https://doi.org/10.1207/s15327957pspr1003_2 | `206` docs, `24,483` judges: `54%` overall accuracy (`47%` lies, `61%` truths); motivation to be believed looks deceptive | Explains why ungrounded `interview` loops (`68`/ep in Gemini) fail and trigger Othello errors |
| DePaulo et al. | *Psych. Bull.* (2003) | https://doi.org/10.1037/0033-2909.129.1.74 | `1,338` estimates, `158` cues: median `\|d\| = 0.10`, tension `d = 0.27`, complaints `d = 0.21`; innocent high-stakes anxiety | Matches `v1.4` hard `interview_lr = 1.2` (`d = 0.097`) and grounds **P1.2** stress decoupling |
| Luke | *Persp. Psych. Sci.* (2019) | https://doi.org/10.1177/1745691619838258 | Monte Carlo + empirical audit: published cue `d` values inflated by small samples & publication bias | Supports dropping ungrounded fishing LR to `1.05` (`KL = 0.00031` nats) in **P1.1** |
| Levine | *JLSP* (2014) | https://doi.org/10.1177/0261927X14535916 | Truth-Default Theory: passive demeanor fails; hard contextual/third-party evidence drives discovery | Validates `SolverPolicy` (`14.1` canaries, `0` ungrounded interviews) over demeanor reading |
| Vrij et al. | *TICS* (2006) | https://doi.org/10.1016/j.tics.2006.02.003 | Active cognitive-load manipulation framework for deception detection | Theoretical bridge from passive questioning to targeted diagnostic probing |
| Vrij et al. | *Law Hum. Behav.* (2008) | https://doi.org/10.1007/s10979-007-9103-y | `N = 80` suspects, `N = 55` officers: reverse-order cognitive load increases diagnostic cues without response bias | Grounds higher diagnosticity only under active event-specific recall constraints |
| Vrij et al. | *Law Hum. Behav.* (2009) | https://doi.org/10.1007/s10979-008-9143-y | Unanticipated spatiotemporal questions reach up to `80%` classification vs rehearsed opening answers | Grounds why anticipated generic topics (`workload`) yield near-zero signal (`LR = 1.05`) |
| Hartwig et al. | *Law Hum. Behav.* (2006) | https://doi.org/10.1007/s10979-006-9053-9 | `N = 82` trainees: Strategic Use of Evidence (SUE) raises accuracy from `56.1%` to `85.4%` | Direct mechanism for **P1.1** (`LR = 1.80` only when confronting with a surfaced held leaked doc) |
| Newman et al. | *PSPB* (2003) | https://doi.org/10.1177/0146167203029005010 | `5` samples: LIWC text style drops from `67%` within-topic to `61%` cross-topic; negative-emotion overlap | Explains why angry `decoy` messages (`_ANGRY`) mimic deceptive negative-emotion lexicons |
| Hancock et al. | *Discourse Proc.* (2008) | https://doi.org/10.1080/01638530701739181 | `242` CMC transcripts: liars write *more* words; partners gain zero detection accuracy from text style | Explains why `search_messages` surface prose carries zero reliable mole signal |
| Hauch et al. | *PSPR* (2015) | https://doi.org/10.1177/1088868314556539 | Meta-analysis (`44` studies, `79` software cues): small overall effect, strong context moderation | Confirms `PublicDayFacts` design (`I(Messages; Mole) = 0`) and **P1.2** rumour non-leakage |
