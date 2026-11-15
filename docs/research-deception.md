# Deception Research Grounding for Canary: Empirical Literature, Quantitative Audit, and Concrete Proposals

**Squad:** `research` (`canary-research-lead` and `canary-research-w1..w9`)  
**Baseline:** `origin/justSilas@5f9b3297` (`afterquery-submit-2` `aa1c679e`, rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Deep-Dive Monographs:** [01. Deception Detection](research/01_deception_detection.md) | [02. Insider Threat & Base-Rate Fallacy](research/02_insider_threat.md) | [03. Leak Hunts, Canary Traps & Group Testing](research/03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](research/04_social_engineering_cheap_talk.md) | [06. Organisational Bias, 44 Cases & Sleeper Port](research/06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer & Gate B Post-Mortem](research/07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](research/08_mole_rl_stackelberg_and_catchability.md) | [10. Proposal Simulations & Zero-Leakage Proofs](research/10_proposal_simulations_and_zero_leakage_proofs.md) | [11. Empirical Transcript Bias Forensics](research/11_empirical_transcript_bias_forensics.md) | [13. Blackwell Dominance, Channel Capacity & EIG](research/13_blackwell_channel_capacity_and_eig.md) | [14. Sleeper Mole Catalog & Head-to-Head Tournament](research/14_sleeper_mole_catalog_and_head_to_head.md)  
**Companion Case Studies:** [Organisational Biases & 44 Cases](research-biases.md) | [Failure Research Dataset](FAILURE-RESEARCH.md)  
**Primary Benchmark Evidence:** [Gap Report](reports/gap.md) | [Cross-Family Behaviour Table](../results/behaviour_compare_v1.4.md) | [Harbor Judge Rehearsal](../results/harbor/rehearsal/TABLE.md) | [Failure Analysis v1.4](reports/failure_analysis_v1.4.md) | [Below-Break-Even Gallery](reports/failure_gallery_breakeven.md) | [Reference Optimality](reports/reference_optimality.md) | [Difficulty Design](DIFFICULTY.md) | [Exploit & Fairness Audit](EXPLOITS.md)

---

## 1. Executive Synthesis: Why Frontier LLMs Replicate Human Investigative Biases in Canary

Canary models an asymmetric organizational leak-hunt in which one hidden insider (`mole`) among $N = 40$ employees (`hard`, $T = 21$ days, $8$ actions/day) leaks confidential documents (`p_leak = 0.65`, surfacing after `delay_choices = (2, 3)` days, destroying `leak_damage = 0.05` of company value $V$ per leak) while spoofing `after_hours` access logs (`framing_rate = 2.0/day`) alongside a vocal but innocent disgruntled `decoy`. To win, an investigator must identify and accuse the mole before $V$ erodes, under a severe false-accusation penalty (`wrong_accusation_score = -1.0`, abstention `0.0`).

Across six empirical research traditions - **deception detection, insider-threat forensics, cryptographic traitor tracing and group testing, social engineering and strategic cheap talk, strategic deception and sleeper behaviour in LLMs, and organizational psychology** - one unifying theorem explains Canary's benchmark gap (`gemini-4-carbon` over OpenCode/MCP at **65% [24%, 98%]** raw and **72% [52%, 91%]** luck-adjusted of `SolverPolicy` on `v1.4` hard, $n = 30$ post-hoc locked paired dev seeds `0-29`):

1. **Passive behavioral, linguistic, and audit-log cues carry near-zero posterior diagnosticity under low base rates.** Meta-analyses of 24,483 human judges show passive lie-truth accuracy sits at **54%** (`47%` on lies) because behavioral cues are intrinsically weak (`median |d| = 0.10`, matching Canary `v1.4` hard's `interview_lr = 1.20`, binary `d = 0.097`, `KL = 0.00477` nats) and confounded by innocent anxiety under scrutiny (Bond & DePaulo, 2006; DePaulo et al., 2003; Hartwig & Bond, 2011). Similarly, under the insider-threat base-rate fallacy ($1$ mole vs $39$ innocents), a single `after_hours` access-log event (`6.20` total events/day across mole `0.30`, decoy `1.10`, and 38 plain innocents `0.12632`) yields a Bayesian Positive Predictive Value (PPV) of only **4.84%** (**5.88%** excluding the decoy; Axelsson, 2000; Sommer & Paxson, 2010).
2. **Active watermarked group testing (`plant_canary`) strictly Blackwell-dominates passive observation by two orders of magnitude.** Conditional on leaking, a balanced 3-variant canary (`max_variants = 3`, `fingerprint_accuracy = 0.95`) delivers **0.86544 nats** (`1.2486` bits) of 3-way mutual information - **181.4x** the exact KL of a `v1.4` hard interview (`+3.6376` nats log-odds shift on matching variant vs flip), **741.6x** Shannon interview capacity (`0.001167` nats), and **7,264.4x** Day 1 uniform-prior interview EIG (`0.000119` nats), with an explicit rational Markov garbling matrix $G$ (`g_A = 224/925`, `g_non_A = 184/925`, `P_interview = P_canary G` to `2.78e-17` precision; Blackwell, 1953; Lindley, 1956) proving strict dominance across *every* prior and *every* loss state $V$, and establishing an information-theoretic lower bound of $\ln(39) / 0.86544 = \mathbf{4.233}$ leaked 3-way traps to resolve $39$ non-decoy suspects (Boneh & Shaw, 1998; Chor et al., 2000; Tardos, 2008; Aldridge, Johnson & Scarlett, 2019).
3. **`gemini-4-carbon` falls into the classic human investigator trap even when exact likelihood ratios are disclosed - and not from rule confusion.** Confirming Hartwig & Bond's (2011) finding that disclosing cue validity does not rescue weak passive channels, deterministic replay across `135` committed multi-model episodes ([Monograph 11](research/11_empirical_transcript_bias_forensics.md)) shows `gemini-4-carbon` spends **68.0 interviews** (`72.1%` repeats), **12.27 access-log reads**, and **4.40 message calls** per episode on `v1.4` hard (`SolverPolicy`: `0` interviews, `0` non-decoy message reads), exhausting all $8$ daily actions on `242` of `303` under-planted days and planting only **8.5 canaries** (`31.5%` capacity, `254` total, `67.59` nats 3-day EIG) vs `SolverPolicy`'s **14.1 canaries** (`66.7%` capacity, `424` total, `130.35` nats; exact Shapley split of the `62.76`-nat / `3.39 V` deficit: **77.68% / `2.63 V` slot crowding** vs **22.32% / `0.76 V` partition design**, [Monograph 13](research/13_blackwell_channel_capacity_and_eig.md)). Crucially, `scripts/careful_mole_check.py` (`docs/DIFFICULTY.md` W1) rules out instruction misunderstanding: `gemini-4-carbon` sized its canaries identically to `SolverPolicy` (`0.26` vs `0.24` mean staff share; `0.74` vs `0.76` mean careful weight; `28/3,841 = 0.7%` invalid-argument calls). Instead, thin canary evidence leaves $\ge 2$ consistent suspects at `9/29` accusations (mean consistent set `1.83` vs `1.07`), costing **3.39 V** at commitment (`docs/reports/failure_analysis_v1.4.md`): in **9/9 (`100.0%`)** of those un-isolated OpenCode episodes (`seeds 3, 5, 7, 8, 14, 15, 18, 20, 23`; and **6/6 = `100.0%`** in-process), `gemini-4-carbon` accuses the strict `argmax` of observed `after_hours` log counts inside the consistent set while inflating verbalized posterior confidence by **`+22.94 pp`**, directly causing both non-flip `-1.0` wrong accusations on `seed 15` and `seed 18` plus `3` below-break-even $P < 1/(1+V)$ horizon gambles on seeds `5, 18, 23` costing `-0.9368 V` luck-adjusted (`docs/reports/failure_gallery_breakeven.md`).
4. **Controlled cross-family (`opencode-gpt-5.5`) and Harbor shell rehearsal (`aa1c679e`) validation prove the MCP-only gap is cognitive-behavioral, while motivating `v1.6` social pretexts and adaptive sleeper moles.** Given identical MCP-only tools, identical `v1.4` hard instructions, and the exact same `30` paired dev worlds (locked prior to execution in commit `cf394894`), `gpt-5.5` allocates its budget according to Blackwell channel capacity - planting **17.17 canaries/episode** (`515` total) vs only **4.17 interviews** (`125` total, `6%` of `69` mean tool calls vs `gemini-4-carbon`'s `53%` of `128`) - achieving **28/28 (`100.0%`) accusation precision** (`0` wrong accusations, mean accusation day `10.2` vs `10.6` reference and `13.2` Gemini) and **101% [79%, 140%]** raw (`+0.504 +/- 0.064` vs `+0.499 +/- 0.119`; luck-adjusted **84% [67%, 103%]**, with `2/30` episodes `seed 0` and `seed 17` writing `"Accusing e.."` in prose without calling `accuse`, and `gpt-5.5`'s log-ignoring two-canaries/day habit scoring `0.496 +/- 0.036` vs `0.561 +/- 0.032` on `400` fresh hard seeds `9000-9399`). Likewise, in the Harbor judge-path rehearsal on tag `afterquery-final` (`1bc3e281`, `results/harbor/rehearsal/TABLE.md`), where the container grants `bash`/`python3` (`20/28` trials used shell computation), `gemini-4-carbon` scored **93% (`+0.472`, `10` valid), 116% (`+0.585`, `10` valid), and 131% (`+0.626`, `9` valid trials, `5` finishing after the `08:30` cut-off, `1` infra-excluded)** of the oracle (`+0.506` on all `10` tasks; `28/29` valid accusations correct). External Python computation offloads Bayesian bookkeeping (Bakhtin et al., 2022), demonstrating why next-generation `v1.6` benchmarks must target **prior/likelihood specification under zero-leakage social pretexts** and **adaptive Stackelberg sleeper moles** rather than arithmetic load alone.
5. **Why `v1.5-candidate` inverted (`61% -> 108%`) and how `v1.6+` fixes it.** When `v1.5-candidate` (`justSilas-v15-bias`) coupled `40%` of workplace rumours to `world.mole` (`peers = ids \ {mole}`, `LLR = -0.5210` nats against the target being the mole) and disclosed the mole's ulterior seeding motive in `Env.instruction()`, suspicion of ulterior motivation (Fein, Hilton & Miller, 1990) turned rumours into an exclusion oracle (`gemini-4-carbon` jumped from `61%` to `108%` of solver on hard seeds `0-9`). Enforcing **Crawford-Sobel babbling-equilibrium independence** ($I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0 \implies \text{LLR} \equiv 0$) restores exact `SolverPolicy` invariance while exposing uncalibrated LLMs to multi-day social pretexts.

### Quantitative Channel Hierarchy in Canary `v1.4` Hard (`aa1c679e`)

| Investigative Channel (`v1.4` Hard, $N=40$, $T=21$) | Action Cost | Mole vs Innocent Signal Parameters | Info Gain (`KL` / `MI`) | `SolverPolicy` Usage/Ep | `gpt-5.5` Usage/Ep | `gemini-4-carbon` Usage/Ep | Primary Research Anchor |
|---|---:|---|---:|---:|---:|---:|---|
| `list_employees` `clearance` (`1-3`, `DIFFICULTY.md` W4) | `0` (roster) | `canary_level = 1` & 2-dept reg docs (`access_constraints` never binds) | **`0.00000` nats** | Ignored (`0` weight) | `1.00` roster read | Checked as red herring | Stajano & Wilson (2011) distraction; Tversky & Kahneman (1974) |
| `search_messages` / `read_message` (non-decoy chat) | `1` action | Pure `PublicDayFacts` (`I(Msg; Mole) = 0`) | **`0.00000` nats** | `0.0` (after decoy ID) | `9.27` total msg calls | `4.40` non-decoy calls | Crawford & Sobel (1982); Hauch et al. (2015) |
| `interview` (passive ungrounded questioning) | `1` action | `p_inn = 0.20`, `p_mole = 0.24` (`LR = 1.20`, `d = 0.097`) | **`0.00477` nats** | `0.0` calls (`0%`) | **`4.17` calls (`6%`)** | **`68.03` calls (`53%`)** | DePaulo et al. (2003); Bond & DePaulo (2006); Hartwig & Bond (2011) |
| `read_access_logs` (`after_hours` with `framing=True`) | `1` action | Mole `0.30/d`, decoy `1.10/d`, plain inn `0.1263/d` (`PPV = 4.84%`) | **`0.10990` nats/d** | Passive log parse | `8.57` calls | `12.27` calls | Axelsson (2000); Sommer & Paxson (2010) |
| `check_leak_feed` + `list_documents` (regular leak) | `1` action | 2-dept `16/40` recipient set (`p_leak = 0.65`, delay `2-3d`) | **`0.91629` nats** (1st leak) | Daily feed check | `9.20` + `8.63` calls | Daily feed check | Levine (2014) Truth-Default diagnostic triggers |
| `plant_canary` (`max_variants=3`, `acc=0.95`, given leak) | `1` action + `0.02 V` | `0.950` true variant vs `0.025` flip (`+3.6376` nats LLR) | **`0.86544` nats** (3-way MI) | **`14.1` canaries** (`66.7%`) | **`17.2` canaries** | **`8.5` canaries** (`31.5%`) | Boneh & Shaw (1998); Aldridge et al. (2019) |

---

## 2. Pillar 1: Deception Detection and Investigative Interviewing

*(Full 14-paper analysis and derivations in [docs/research/01_deception_detection.md](research/01_deception_detection.md).)*

### 2.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Bond, C. F., Jr., & DePaulo, B. M. (2006).** Accuracy of Deception Judgments. *Personality and Social Psychology Review*, 10(3), 214-234.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/16859438/ | **DOI:** https://doi.org/10.1207/s15327957pspr1003_2  
> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges. In relevant studies, people attempt to discriminate lies from truths in real time with no special aids or training. In these circumstances, people achieve an average of 54% correct lie-truth judgments, correctly classifying 47% of lies as deceptive and 61% of truths as nondeceptive."
> "Our meta-analyses reveal that people are more accurate in judging audible than visible lies, that people appear deceptive when motivated to be believed, and that individuals regard their interaction partners as honest."

*Canary Grounding:* Explains why ungrounded one-on-one questioning yields near-chance discrimination and triggers the **Othello error** when suspected or restricted innocents become motivated to be believed.

- **DePaulo, B. M., Lindsay, J. J., Malone, B. E., Muhlenbruck, L., Charlton, K., & Cooper, H. (2003).** Cues to Deception. *Psychological Bulletin*, 129(1), 74-118.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/12555795/ | **DOI:** https://doi.org/10.1037/0033-2909.129.1.74  
> "The combined results of 1,338 estimates of 158 cues to deception are reported. Results show that in some ways, liars are less forthcoming than truth tellers, and they tell less compelling tales. They also make a more negative impression and are more tense. Their stories include fewer ordinary imperfections and unusual contents. However, many behaviors showed no discernible links, or only weak links, to deceit."

*Canary Grounding:* Canary `v1.4` hard's `interview_lr = 1.20` at base rate `0.20` produces standardized effect size `d = 0.097` (Hasselblad-Hedges `d_HH = 0.129`), matching DePaulo et al.'s empirical median `|d| = 0.10` across 88 multi-estimate cues.

- **Hartwig, M., & Bond, C. F., Jr. (2011).** Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/21707129/ | **DOI:** https://doi.org/10.1037/a0023589  
> "In conclusion, contrary to previous assumptions, people rarely rely on the wrong cues. Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."

*Canary Grounding:* Directly explains why printing `interview_lr = 1.2` in `Env.instruction()` does not save `gemini-4-carbon` from burning `68.0` interviews/episode: explicit cue-weight disclosure cannot fix a `0.00477`-nat channel; only active interventions (`plant_canary` or Strategic Use of Evidence) widen diagnostic signal separation.

- **Levine, T. R. (2014).** Truth-Default Theory (TDT): A Theory of Human Deception and Deception Detection. *Journal of Language and Social Psychology*, 33(4), 378-392.  
  **Verified Link:** https://api.crossref.org/works/10.1177/0261927X14535916 | **DOI:** https://doi.org/10.1177/0261927X14535916  
> "Unlike previous theories of deception detection, TDT emphasizes contextualized communication content in deception detection over nonverbal behaviors associated with emotions, arousal, strategic self-presentation, or cognitive effort."

*Canary Grounding:* Grounds `SolverPolicy`'s reliance on corroborated third-party evidence (`check_leak_feed`, `list_documents`, watermarked `plant_canary` provenance) over arousal or demeanor.

- **Hartwig, M., Granhag, P. A., Stromwall, L. A., & Kronkvist, O. (2006).** Strategic use of evidence during police interviews: When training to detect deception works. *Law and Human Behavior*, 30(5), 603-619.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/16977348/ | **DOI:** https://doi.org/10.1007/s10979-006-9053-9  
> "Trained interviewers applied different strategies than did untrained. As a consequence of this, liars interviewed by trained interviewers were more inconsistent with the evidence compared to liars interviewed by untrained interviewers. Trained interviewers created and utilized the statement-evidence consistency cue, and obtained a considerably higher deception detection accuracy rate (85.4%) than untrained interviewers (56.1%)."

*Canary Grounding:* Directly motivates Proposal **P1.1** (splitting ungrounded fishing at `LR = 1.05` from SUE evidence-backed confrontation at `LR = 1.80`).

- **Hauch, V., Blandon-Gitlin, I., Masip, J., & Sporer, S. L. (2015).** Are Computers Effective Lie Detectors? A Meta-Analysis of Linguistic Cues to Deception. *Personality and Social Psychology Review*, 19(4), 307-342.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/25387767/ | **DOI:** https://doi.org/10.1177/1088868314556539  
> "As expected, the meta-analyses demonstrated that, relative to truth-tellers, liars experienced greater cognitive load, expressed more negative emotions, distanced themselves more from events, expressed fewer sensory-perceptual words, and referred less often to cognitive processes. However, liars were not more uncertain than truth-tellers."

*Canary Grounding:* Justifies Canary's architectural rule (`canary/text/facts.py`) that `PublicDayFacts` passes zero hidden mole identity to `TextProvider` while innocent disgruntled staff (`decoy`) express negative workplace emotion.

---

## 3. Pillar 2: Insider Threat, Anomaly Logs, and the Base-Rate Fallacy

*(Full 10-paper insider-threat forensics, 38-innocent Poisson order statistics, and 9/9 transcript replay in [docs/research/02_insider_threat.md](research/02_insider_threat.md).)*

### 3.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Axelsson, S. (2000).** The Base-Rate Fallacy and the Difficulty of Intrusion Detection. *ACM Transactions on Information and System Security*, 3(3), 186-205.  
  **Verified Link:** https://openalex.org/W2156204309 | **DOI:** https://doi.org/10.1145/357830.357849  
> "Many different demands can be made of intrusion detection systems. An important requirement is that an intrusion detection system be effective; that is, it should detect a substantial percentage of intrusions into the supervised system, while still keeping the false alarm rate at an acceptable level. This article demonstrates that, for a reasonable set of assumptions, the false alarm rate is the limiting factor for the performance of an intrusion detection system."

*Canary Grounding:* On `v1.4` hard ($N = 40$), `log_rate_mole * p_after_hours_mole = 0.3000` events/day, `decoy` generates `0.10 + 2.0 * 0.5 = 1.1000` events/day, and $38$ plain innocents generate $38 \times (0.10 + 1.0/38) = 4.8000$ events/day (`6.2000` total `after_hours` events/day). By Bayes' rule, a single `after_hours` alarm has posterior mole probability $\text{PPV} = 0.30 / 6.20 = \mathbf{4.84\%}$ (`5.88%` after excluding the decoy). Even across all `21` days with oracle decoy removal, the expected maximum `after_hours` count among `38` plain innocents ($\mathbb{E}[\max_{1 \le j \le 38}] = \mathbf{6.67}$) exceeds the mole's expected count ($\mathbf{6.30}$), holding tie-broken `argmax(after_hours)` accuracy to `41.78%` (`-0.4083` mean score on `seeds 0-199`).

- **Kahneman, D., & Tversky, A. (1973).** On the Psychology of Prediction. *Psychological Review*, 80(4), 237-251.  
  **Verified Link:** https://openalex.org/W1980054641 | **DOI:** https://doi.org/10.1037/h0034747  
> "By this heuristic, people predict the outcome that appears most representative of the evidence. Consequently, intuitive predictions are insensitive to the reliability of the evidence or to the prior probability of the outcome, in violation of the logic of statistical prediction."

*Canary Grounding:* Explains why both Codex `gpt-5.5` (`medium` seeds `0` and `4`, `-1.0` wrong accusations on `"statistically loud"` `after_hours` counts, `docs/reports/gap.md`) and `gemini-4-carbon` (`v1.4` hard: picking the strict `argmax` of observed `after_hours` counts in **9/9 = 100.0%** of un-isolated accusations, causing wrong `-1.0` shots on `seed 15` `e34: 3 vs e37: 1` and `seed 18` `e29: 6 vs e27: 2`) treat noisy off-hours outliers as representative proof of exfiltration.

- **Sommer, R., & Paxson, V. (2010).** Outside the Closed World: On Using Machine Learning for Network Intrusion Detection. *IEEE Symposium on Security and Privacy*, 305-316.  
  **Verified Link:** https://openalex.org/W1985987493 | **DOI:** https://doi.org/10.1109/SP.2010.25  
> "In network intrusion detection research, one popular strategy for finding attacks is monitoring a network's activity for anomalies: deviations from profiles of normality previously learned from benign traffic, typically identified using tools borrowed from the machine learning community. However, despite extensive academic research one finds a striking gap in terms of actual deployments of such systems: compared with other intrusion detection approaches, machine learning is rarely employed in operational \"real world\" settings."

*Canary Grounding:* Operationalizes why uncalibrated anomaly scoring (`Heuristic` baseline: `0.0348` on hard seeds `2000-2059`; `-0.322` on `v1.2`/`v1.3` hard; `LogsOnly = -0.9383`) mistakes benign workplace variance and adversarial framing for exfiltration.

- **Senator, T. E., Goldberg, H. G., Memory, A., Young, W. T., Rees, B., Pierce, R., et al. (2013).** Detecting Insider Threats in a Real Corporate Database of Computer Usage Activity. *Proceedings of ACM SIGKDD (KDD '13)*, 1393-1401.  
  **Verified Link:** https://openalex.org/W1995976200 | **DOI:** https://doi.org/10.1145/2487575.2488213  
> "We have also developed a visual language for specifying combinations of features, baselines, peer groups, time periods, and algorithms to detect anomalies suggestive of instances of insider threat behavior. We defined over 100 data features in seven categories based on approximately 5.5 million actions per day from approximately 5,500 users."

*Canary Grounding:* Grounds Proposal **P2.2**, where `SolverPolicy` conditions `behaviour_logliks` on public `(department, sprint_day)` baselines across release sprints while unconditioned `after_hours` summation drops from `44.0%` to `30.5%` Day 21 accuracy.

- **Glasser, J., & Lindauer, B. (2013).** Bridging the Gap: A Pragmatic Approach to Generating Insider Threat Data. *IEEE Security and Privacy Workshops*, 98-104.  
  **Verified Link:** https://openalex.org/W1991210879 | **DOI:** https://doi.org/10.1109/SPW.2013.37  
> "The threat of malicious insider activity continues to be of paramount concern in both the public and private sectors. Though there is great interest in advancing the state of the art in predicting and stopping these threats, the difficulty of obtaining suitable data for research, development, and testing remains a significant hinderance. We outline the use of synthetic data to enable progress in one research program, while discussing the benefits and limitations of synthetic insider threat data, the meaning of realism in this context, as well as future research directions."

*Canary Grounding:* Establishes the CERT synthetic insider-threat paradigm that Canary extends into an interactive, replay-verified, cryptographically salted MCP benchmark (`canary/world.py`, `canary/env.py`).

- **Nurse, J. R. C., Buckley, O., Legg, P. A., Goldsmith, M., Creese, S., Wright, G. R. T., & Whitty, M. (2014).** Understanding Insider Threat: A Framework for Characterising Attacks. *IEEE Security and Privacy Workshops*, 214-228.  
  **Verified Link:** https://openalex.org/W1969795119 | **DOI:** https://doi.org/10.1109/SPW.2014.38  
> "The threat that insiders pose to businesses, institutions and governmental organisations continues to be of serious concern. Recent industry surveys and academic literature provide unequivocal evidence to support the significance of this threat and its prevalence. Despite this, however, there is still no unifying framework to fully characterise insider attacks and to facilitate an understanding of the problem, its many components and how they all fit together."

*Canary Grounding:* Separates **attitudinal/psychosocial precursors** (modeled in Canary by the innocent disgruntled `decoy`) from **technical capability and opportunity** (document recipient access + active exfiltration).

---

## 4. Pillar 3: Leak Hunts, Canary Traps, Digital Fingerprinting, and Group Testing

*(Full 10-paper group-testing & fingerprinting derivations, `justSilas-expert` post-mortem, Burnashev `0/254` vs `50/424` confirmation gap, and `P3.1`/`P3.2` specs in [docs/research/03_leak_hunts_canary_traps_group_testing.md](research/03_leak_hunts_canary_traps_group_testing.md).)*

### 4.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Boneh, D., & Shaw, J. (1998).** Collusion-Secure Fingerprinting for Digital Data. *IEEE Transactions on Information Theory*, 44(5), 1897-1905.  
  **Verified Link:** https://openalex.org/W2134195444 | **DOI:** https://doi.org/10.1109/18.705568  
> "This paper discusses methods for assigning code-words for the purpose of fingerprinting digital data, e.g., software, documents, music, and video. Fingerprinting consists of uniquely marking and registering each copy of the data. This marking allows a distributor to detect any unauthorized copy and trace it back to the user. This threat of detection will deter users from releasing unauthorized copies."

*Canary Grounding:* Formalizes `plant_canary(doc_title, assignment)` (`canary/env.py`), where distinct document variants trace leaked copies back to assigned subsets while `careful_mole = True` models the deterrent effect on widely distributed traps (`weight = 1.0 - len(recipients) / n_employees`).

- **Chor, B., Fiat, A., Naor, M., & Pinkas, B. (2000).** Tracing Traitors. *IEEE Transactions on Information Theory*, 46(3), 893-910.  
  **Verified Link:** https://openalex.org/W2295616646 | **DOI:** https://doi.org/10.1109/18.841169  
> "We give cryptographic schemes that help trace the source of leaks when sensitive or proprietary data is made available to a large set of parties."

*Canary Grounding:* Establishes traitor-tracing over shared broadcast/document distributions when regular company documents are shared across `16` recipients (`2` of `5` departments on `hard`).

- **Tardos, G. (2008).** Optimal Probabilistic Fingerprint Codes. *Journal of the ACM*, 55(2), Article 10, 1-24.  
  **Verified Link:** https://openalex.org/W2031722321 | **DOI:** https://doi.org/10.1145/1346330.1346335  
> "By proving matching lower bounds we establish that the length of our codes is best within a constant factor for reasonable error probabilities."

*Canary Grounding:* Proves logarithmic code-length lower bounds under probabilistic channel noise (`fingerprint_accuracy = 0.95` on `hard`, `0.70` on experimental `justSilas-expert`).

- **Aldridge, M., Johnson, O., & Scarlett, J. (2019).** Group Testing: An Information Theory Perspective. *Foundations and Trends in Communications and Information Theory*, 15(3-4), 196-392.  
  **Verified Link:** https://openalex.org/W2912457157 | **DOI:** https://doi.org/10.1561/0100000099  
> "The group testing problem concerns discovering a small number of defective items within a large population by performing tests on pools of items. A test is positive if the pool contains at least one defective, and negative if it contains no defectives."
> "We assess the theoretical guarantees not only in terms of scaling laws, but also in terms of the constant factors, leading to the notion of the rate of group testing, indicating the amount of information learned per test."

*Canary Grounding:* Gives the exact adaptive ternary group-testing rate of Canary `v1.4` hard: prior entropy excluding the decoy is $H(\text{Mole}) = \ln(39) = 3.66356\text{ nats}$ (`5.2854` bits), and each leaked balanced 3-variant canary yields $I(Y; V) = \ln 3 + 0.95 \ln 0.95 + 2(0.025)\ln(0.025) = \mathbf{0.86544\text{ nats}}$ (`1.2486` bits), requiring at least $3.66356 / 0.86544 = \mathbf{4.233}$ leaked traps in expectation without regular-leak narrowing. Moreover, under `careful_mole` (`weight = 1 - k / 40`), Day 1 unconditional trap hit rate $(k / 39)(1 - k / 40)$ is maximized at **$k^* = N/2 = 20$ recipients** (`0.2564`), **3.6x** a narrow 3-person canary (`0.0712`) and **10.3x** a 39-person canary (`0.0250`).

- **Pawlick, J., Colbert, E., & Zhu, Q. (2019).** A Game-Theoretic Taxonomy and Survey of Defensive Deception for Cybersecurity and Privacy. *ACM Computing Surveys*, 52(4), Article 82.  
  **Verified Link:** https://openalex.org/W2971648973 | **DOI:** https://doi.org/10.1145/3337772  
> "Advocates and engineers have recently proposed using defensive deception as a means to leverage the information asymmetry typically enjoyed by attackers as a tool for defenders."

*Canary Grounding:* Places `plant_canary` formally in the **honey-document / signaling game** quadrant where `MoleView` omits `is_canary`, reversing attacker-defender information asymmetry.

---

## 5. Pillar 4: Social Engineering, Cheap Talk, and Rumor Credulity

*(Full 11-paper game-theoretic proof and `v1.6` pretext audit in [docs/research/04_social_engineering_cheap_talk.md](research/04_social_engineering_cheap_talk.md).)*

### 5.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Crawford, V. P., & Sobel, J. (1982).** Strategic Information Transmission. *Econometrica*, 50(6), 1431-1451.  
  **Verified Link:** https://api.openalex.org/works/W2160003140 | **DOI:** https://doi.org/10.2307/1913390  
> "Since R bases his choice of action on rational expectations, this establishes a sense in which equilibrium signaling is more informative when agents' preferences are more similar."

*Canary Grounding:* Establishes why unverified internal chat must sit at a zero-information **babbling equilibrium** (`LLR = 0`) for `SolverPolicy`.

- **Kamenica, E., & Gentzkow, M. (2011).** Bayesian Persuasion. *American Economic Review*, 101(6), 2590-2615.  
  **Verified Link:** https://api.crossref.org/works/10.1257/aer.101.6.2590 | **DOI:** https://doi.org/10.1257/aer.101.6.2590  
> "We consider a symmetric information model where a sender chooses a signal to reveal to a receiver, who then takes a noncontractible action that affects the welfare of both players. We derive necessary and sufficient conditions for the existence of a signal that strictly benefits the sender."

*Canary Grounding:* Separates investigator-committed diagnostic experiments (`plant_canary`) from adversarial framing (`framing=True`).

- **Stajano, F., & Wilson, P. (2011).** Understanding Scam Victims: Seven Principles for Systems Security. *Communications of the ACM*, 54(3), 70-75 (`UCAM-CL-TR-754`).  
  **Verified Link:** https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-754.pdf | **DOI:** https://doi.org/10.1145/1897852.1897872  
> "While you are distracted by what retains your interest, hustlers can do anything to you and you won't notice."
> "When you are under time pressure to make an important choice, you use a different decision strategy. Hustlers steer you towards a strategy involving less reasoning."

*Canary Grounding:* Grounds Canary's four core social-engineering vectors: **Distraction** (`decoy` + `misforward`), **Authority** (`gen_authority`), **Herd** (`gen_bandwagon`), and **Time Pressure** (`gen_recency` + daily `0.05 V` bleed).

- **Blythe, M., Petrie, H., & Clark, J. A. (2011).** F for Fake: Four Studies on How We Fall for Phish. *Proceedings of CHI '11*, 3469-3478.  
  **Verified Link:** https://api.openalex.org/works/W1974464813 | **DOI:** https://doi.org/10.1145/1978942.1979459  
> "This identifies the main literary device employed as pastiche and draws on critical theory to consider why security based pastiche may be currently very persuasive."

*Canary Grounding:* Explains why `v1.5-candidate`'s literal regex tags (`subject: "rumour: e07"`) failed while `v1.6` security-review pastiche removes surface giveaways.

- **Pennycook, G., Cannon, T. D., & Rand, D. G. (2018).** Prior Exposure Increases Perceived Accuracy of Fake News. *Journal of Experimental Psychology: General*, 147(12), 1865-1880.  
  **Verified Link:** https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ | **DOI:** https://doi.org/10.1037/xge0000465  
> "These observations indicate that although extreme implausibility is a boundary condition of the illusory truth effect, only a small degree of potential plausibility is sufficient for repetition to increase perceived accuracy."

*Canary Grounding:* Directly grounds Proposal **P4.1** / **P7.3**: static Day 1 focal suspects become provably impossible (`0` overlap with surfaced regular leaks) in **78.0%** (`156/200`) of `hard` episodes by Day 12, hitting Pennycook et al.'s extreme-implausibility boundary unless rotated inside the live recipient intersection $C_{\text{reg}}(d)$.

- **Dores Cruz, T. D., et al. (2021).** Gossip and Reputation in Everyday Life. *Philosophical Transactions of the Royal Society B*, 376(1838), 20200301.  
  **Verified Link:** https://pmc.ncbi.nlm.nih.gov/articles/PMC8487731/ | **DOI:** https://doi.org/10.1098/rstb.2020.0301  
> "Gossip senders frequently shared information about targets' cooperativeness and did so in ways that minimize potential retaliation from targets. Receivers overwhelmingly believed gossip to be true and updated their evaluation of targets based on gossip."

*Canary Grounding:* Explains default gossip credulity in human-pretrained models and hedged workplace phrasing (`RumourFollower = -0.995` on `hard`).

- **Fein, S., Hilton, J. L., & Miller, D. T. (1990).** Suspicion of Ulterior Motivation and the Correspondence Bias. *Journal of Personality and Social Psychology*, 58(5), 753-764.  
  **Verified Link:** https://api.openalex.org/works/W1972891856 | **DOI:** https://doi.org/10.1037/0022-3514.58.5.753  
> "Three studies examined the hypothesis that when perceivers learn of the existence of multiple, plausibly rival motives for an actor's behavior, they are less likely to fall prey to the correspondence bias than when they learn of the existence of situational factors that may have constrained the actor's behavior."

*Canary Grounding:* Predicts the exact `v1.5-candidate` Gate B reversal (`61% -> 108%`) once `Env.instruction()` disclosed that `40%` of rumours were mole-planted against a non-mole rival.

---

## 6. Pillar 5: Strategic Deception, Alignment Faking, and Sleeper Behaviour in LLMs

### 6.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Hubinger, E., Denison, C., Mu, J., Lambert, M., Tong, M., MacDiarmid, M., et al. (2024).** Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training. *arXiv:2401.05566*.  
  **Verified Link:** https://openalex.org/W4390833079 | **DOI:** https://doi.org/10.48550/arXiv.2401.05566  
> "We find that such backdoor behavior can be made persistent, so that it is not removed by standard safety training techniques, including supervised fine-tuning, reinforcement learning, and adversarial training (eliciting unsafe behavior and then training to remove it)."
> "Furthermore, rather than removing backdoors, we find that adversarial training can teach models to better recognize their backdoor triggers, effectively hiding the unsafe behavior."

*Canary Grounding:* Directly grounds Canary's conditional `MoleStrategy` (`canary/mole/dsl.py`) and RL/GRPO mole training (`train/grpo_mole.py`), where a sleeper mole behaves benignly or leaks only wide-recipient documents under high surveillance triggers (`recent_low_recipient_docs >= 2`, `i_am_restricted == 1`) and bursts when oversight relaxes.

- **Scheurer, J., Balesni, M., & Hobbhahn, M. (2023).** Large Language Models can Strategically Deceive their Users when Put Under Pressure. *arXiv:2311.07590*.  
  **Verified Link:** https://openalex.org/W4388717704 | **DOI:** https://doi.org/10.48550/arXiv.2311.07590  
> "Within this environment, the model obtains an insider tip about a lucrative stock trade and acts upon it despite knowing that insider trading is disapproved of by company management. When reporting to its manager, the model consistently hides the genuine reasons behind its trading decision."

*Canary Grounding:* Demonstrates spontaneous insider misconduct and cover-up under organizational performance/horizon pressure, mirroring both the mole's cover traffic and frontier investigators' horizon-bleed gambles on Days `14-18`.

- **Greenblatt, R., Denison, C., Wright, B., Roger, F., MacDiarmid, M., Kravec, S., et al. (2024).** Alignment Faking in Large Language Models. *arXiv:2412.14093*.  
  **Verified Link:** https://openalex.org/W4405627013 | **DOI:** https://doi.org/10.48550/arXiv.2412.14093  
> "We present a demonstration of a large language model engaging in alignment faking: selectively complying with its training objective in training to prevent modification of its behavior out of training."

*Canary Grounding:* Exact analogue of Canary's `careful_mole = True` monitoring-inference rule (`canary/env.py`): when a document's distribution is suspiciously broad for a trap or narrow under targeted testing, a strategic mole modulates leak selection based on inferred oversight intensity.

- **Meinke, A., Schoen, B., Scheurer, J., Balesni, M., Shah, R., & Hobbhahn, M. (2024).** Frontier Models are Capable of In-context Scheming. *arXiv:2412.04984*.  
  **Verified Link:** https://openalex.org/W4405173927 | **DOI:** https://doi.org/10.48550/arXiv.2412.04984  
> "Our results show that o1, Claude 3.5 Sonnet, Claude 3 Opus, Gemini 1.5 Pro, and Llama 3.1 405B all demonstrate in-context scheming capabilities. They recognize scheming as a viable strategy and readily engage in such behavior. For example, models strategically introduce subtle mistakes into their responses, attempt to disable their oversight mechanisms, and even exfiltrate what they believe to be their model weights to external servers."

*Canary Grounding:* Validates Canary's active exfiltration + blame-shifting (`frame` selector in `MoleDSL`) threat model as an empirically documented frontier LLM capability class.

- **Park, P. S., Goldstein, S., O'Gara, A., Chen, M., & Hendrycks, D. (2024).** AI Deception: A Survey of Examples, Risks, and Potential Solutions. *Patterns*, 5(5), 100988.  
  **Verified Link:** https://openalex.org/W4396796749 | **DOI:** https://doi.org/10.1016/j.patter.2024.100988  
> "This paper argues that a range of current AI systems have learned how to deceive humans. We define deception as the systematic inducement of false beliefs in the pursuit of some outcome other than the truth."

*Canary Grounding:* Defines strategic false-belief induction across hidden-role negotiation and bluffing benchmarks.

- **Hagendorff, T. (2024).** Deception Abilities Emerged in Large Language Models. *Proceedings of the National Academy of Sciences*, 121(24), e2317967121.  
  **Verified Link:** https://openalex.org/W4399320026 | **DOI:** https://doi.org/10.1073/pnas.2317967121  
> "However, given the steady increase in reasoning abilities, future LLMs are under suspicion of becoming able to deceive human operators and utilizing this ability to bypass monitoring efforts. As a prerequisite to this, LLMs need to possess a conceptual understanding of deception strategies. This study reveals that such strategies emerged in state-of-the-art LLMs, but were nonexistent in earlier LLMs."

*Canary Grounding:* Explains the asymmetric capability gap between generating second-order deceptive narratives and maintaining calibrated Bayesian posteriors over $21$ days of delayed, noisy signals.

- **Bakhtin, A., Brown, N., Dinan, E., Farina, G., Flaherty, C., Fried, D., et al. (2022).** Human-level play in the game of Diplomacy by combining language models with strategic reasoning. *Science*, 378(6624), 1067-1074.  
  **Verified Link:** https://openalex.org/W4309663019 | **DOI:** https://doi.org/10.1126/science.ade9097  
> "We introduce Cicero, the first AI agent to achieve human-level performance in Diplomacy, a strategy game involving both cooperation and competition that emphasizes natural language negotiation and tactical coordination between seven players."

*Canary Grounding:* Explains both why pure dialogue LLMs drift in strategic hidden-intent games unless anchored to an explicit Bayesian belief module (`SolverPolicy`) and why Canary's honest `Qwen2.5-1.5B` tiebreaker readout (`README.md`, `VERDA.md`) separates protocol/stopping calibration from active experimental design: across seven trained runs (`v3-4k`: `-0.147 +/- 0.063` and `-0.209`; `v3-8k`: `-0.060`, `-0.777`, `-0.050 +/- 0.049`, `-0.788`), GRPO reward training repairs SFT's reckless over-accusation (`v2`: `-0.457 +/- 0.086`, `n = 172`, `+0.31` to `+0.41` recovery, `100%` valid tool calls) without beating the `0.000` abstaining base model, and even raw-transcript DAgger (`-0.542 +/- 0.214` at `8k` context, `n = 50` partial; level with `v3-4k` at `4k` context) ends as an honest null whenever sliding context windows evict early `plant_canary` variant maps rather than maintaining a compact sufficient-statistic belief summary.

---

## 7. Pillar 6: Organisational Bias, Paranoid Cognition, Scapegoating, and Security Fatigue

*(Full 44-case corporate failure cross-map and 28-strategy Sleeper port in [docs/research/06_organisational_bias_and_sleeper_port.md](research/06_organisational_bias_and_sleeper_port.md); full 9-bias social-psychology audit and `v1.5`/`v1.6` derivations in [docs/research/07_v15_bias_layer_proposals.md](research/07_v15_bias_layer_proposals.md).)*

### 7.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Kramer, R. M. (1998).** Paranoid Cognition in Social Systems: Thinking and Acting in the Shadow of Doubt. *Personality and Social Psychology Review*, 2(4), 251-275.  
  **Verified Link:** https://openalex.org/W2095190268 | **DOI:** https://doi.org/10.1207/s15327957pspr0204_3  
> "A primary aim of this research, accordingly, was to articulate a new framework for conceptualizing a form of exaggerated distrust and suspicion termed paranoid social cognition. Drawing on recent psychological theory and research, this framework identifies the social cognitive underpinnings of paranoid cognitions."

*Canary Grounding:* Explains organizational hypervigilance, sinister attribution error, and anxious rumour cascades (`#security-review`) when employees know a leak audit is underway.

- **Rothschild, Z. K., Landau, M. J., Sullivan, D., & Keefer, L. A. (2012).** A Dual-Motive Model of Scapegoating: Displacing Blame to Reduce Guilt or Increase Control. *Journal of Personality and Social Psychology*, 102(6), 1148-1163.  
  **Verified Link:** https://openalex.org/W2051194391 | **DOI:** https://doi.org/10.1037/a0027413  
> "The authors present a model that specifies 2 psychological motives underlying scapegoating, defined as attributing inordinate blame for a negative outcome to a target individual or group, (a) maintaining perceived personal moral value by minimizing feelings of guilt over one's responsibility for a negative outcome and (b) maintaining perceived personal control by obtaining a clear explanation for a negative outcome that otherwise seems inexplicable."

*Canary Grounding:* Explains why unattributed company value loss (`leak_damage = 0.05` with `2-3` day surfacing lag) drives both employees in chat and uncalibrated LLM investigators to converge on a salient scapegoat rather than abstaining (`1/30` voluntary abstentions in `v1.4` hard on seed `11`, `0` abstentions on `v1.3`).

- **Moore, D. A., & Healy, P. J. (2008).** The trouble with overconfidence. *Psychological Review*, 115(2), 502-517.  
  **Verified Link:** https://pubmed.ncbi.nlm.nih.gov/18426301/ | **DOI:** https://doi.org/10.1037/0033-295X.115.2.502  
> "The authors present a reconciliation of 3 distinct ways in which the research literature has defined overconfidence: (a) overestimation of one's actual performance, (b) overplacement of one's performance relative to others, and (c) excessive precision in one's beliefs."
> "Overprecision appears to be more persistent than either of the other 2 types of overconfidence, but its presence reduces the magnitude of both overestimation and overplacement."

*Canary Grounding:* Directly explains the `docs/reports/failure_gallery_breakeven.md` paradox: `gemini-4-carbon` knows the exact break-even rule $P^*(V) = 1/(1+V)$ (abstaining on seed `11` at `P = 42.9%`), yet **overprecision** - dropping unleaked-canary negative evidence and double-counting framed `after_hours` logs (`0.1263/day` vs `0.1000/day`) plus `1.20`-LR interviews - inflates its verbalized confidence above `80%-89%` on seeds `5` (true `P = 51.02%` vs `P* = 86.11%`), `18` (`62.72%` vs `68.43%`), and `23` (`45.17%` vs `81.22%`).

- **Kahneman, D., & Tversky, A. (1979).** Prospect Theory: An Analysis of Decision under Risk. *Econometrica*, 47(2), 263-291.  
  **Verified Link:** https://openalex.org/W3011865677 | **DOI:** https://doi.org/10.2307/1914185  
> "In particular, people underweight outcomes that are merely probable in comparison with outcomes that are obtained with certainty. This tendency, called the certainty effect, contributes to risk aversion in choices involving sure gains and to risk seeking in choices involving sure losses."
> "An alternative theory of choice is developed, in which value is assigned to gains and losses rather than to final assets and in which probabilities are replaced by decision weights. The value function is normally concave for gains, commonly convex for losses, and is generally steeper for losses than for gains."

*Canary Grounding:* As company value $V$ bleeds from `1.00` down to `0.16-0.46` near the horizon, evaluating outcomes relative to the initial `V = 1.00` endowment rather than the `0.00` abstention baseline induces **loss-domain risk-seeking**, accounting for **`-0.9368 V`** of luck-adjusted decision loss across seeds `5, 18, 23` (`48.5%` of `gemini-4-carbon`'s total accusation-penalty shortfall; `SolverPolicy`: `0/30` below-break-even shots).

- **Gilbert, D. T., & Malone, P. S. (1995).** The Correspondence Bias. *Psychological Bulletin*, 117(1), 21-38.  
  **Verified Link:** https://openalex.org/W1984670080 | **DOI:** https://doi.org/10.1037/0033-2909.117.1.21  
> "The correspondence bias is the tendency to draw inferences about a person's unique and enduring dispositions from behaviors that can be entirely explained by the situations in which they occur."

*Canary Grounding:* Explains why naive agents infer malicious traitor disposition from situational workplace friction (`decoy` promotion grievances, `misforward` routing mistakes, benign `after_hours` deadlines).

- **Beautement, A., Sasse, M. A., & Wonham, M. (2008).** The Compliance Budget: Managing Security Behaviour in Organisations. *Proceedings of the 2008 New Security Paradigms Workshop (NSPW '08)*, 47-58.  
  **Verified Link:** https://openalex.org/W2042720915 | **DOI:** https://doi.org/10.1145/1595676.1595684  
> "Our results show that key factors in the compliance decision are the actual and anticipated cost and benefits of compliance to the individual employee, and perceived cost and benefits to the organization."

*Canary Grounding:* Grounds Canary's `restrict_cost_per_day = 0.01` productivity bleed (`RestrictAll = -1.000`) and routine benign workarounds (`p_after_hours_benign = 0.10`).

- **Hewstone, M., Rubin, M., & Willis, H. (2002).** Intergroup Bias. *Annual Review of Psychology*, 53, 575-604.  
  **Verified Link:** https://openalex.org/W4213263068 | **DOI:** https://doi.org/10.1146/annurev.psych.53.100901.135109  
> "This chapter reviews the extensive literature on bias in favor of in-groups at the expense of out-groups."

*Canary Grounding:* Grounds cross-departmental blame across Canary's $5$ departments (`8` staff each) whenever a 2-department regular document (`16` recipients) leaks (Proposal **P6.1**).

- **Nine Core `v1.6` Bias Anchors (Verified in [Section 2 of Monograph 07](research/07_v15_bias_layer_proposals.md) and cross-referenced with the 44 sourced corporate failure incidents in [docs/research-biases.md](research-biases.md) and [docs/FAILURE-RESEARCH.md](FAILURE-RESEARCH.md): `P-FEAR`, `P-DIFFUSION`, `P-DEVIANCE`, `P-ALERTS`, `P-SOD`):**  
  1. *Rumour intensity & sharpening:* **Allport & Postman (1947)** (`R ~ i x a`, https://archive.org/details/psychology_of_rumor) and **Bordia & DiFonzo (2004)** (https://doi.org/10.1177/019027250406700105).  
  2. *Institutional authority:* **Milgram (1963)** (`26/40` full obedience, https://doi.org/10.1037/h0040525).  
  3. *Pre-decisional sycophancy:* **Lerner & Tetlock (1999)** (conformity to known audience views, https://doi.org/10.1037/0033-2909.125.2.255).  
  4. *Anchoring & availability/recency:* **Tversky & Kahneman (1974)** (https://doi.org/10.1126/science.185.4157.1124).  
  5. *Confirmation bias:* **Nickerson (1998)** (https://doi.org/10.1037/1089-2680.2.2.175).  
  6. *Cross-team informational cascades (`bandwagon`):* **Bikhchandani, Hirshleifer & Welch (1992)** (https://doi.org/10.1086/261849).  
  7. *Workplace incivility spirals (`grudge`):* **Andersson & Pearson (1999)** (https://doi.org/10.5465/amr.1999.2202131).  
  8. *Email egocentrism & routing errors (`misforward`):* **Kruger et al. (2005)** (https://doi.org/10.1037/0022-3514.89.6.925).  
  9. *Associative recall confabulation (`false_memory`):* **Roediger & McDermott (1995)** (`40%-55%` false recall, https://doi.org/10.1037/0278-7393.21.4.803).

---

## 8. Pillar 7: Stackelberg Security Games and Constrained RL for the Mole

*(Full 10-paper Stackelberg, PAIRED, CPO/RCPO, GRPO/DPO, and QRE/CH analysis in [docs/research/08_mole_rl_stackelberg_and_catchability.md](research/08_mole_rl_stackelberg_and_catchability.md); 4-strategy `v1.4` sleeper catalog, non-transitive rank-reversal proof across `3,000` episodes, and saddle-point tournament in [docs/research/14_sleeper_mole_catalog_and_head_to_head.md](research/14_sleeper_mole_catalog_and_head_to_head.md).)*

### 8.1 Primary Papers, Verified Links, and Verbatim Quotes

- **Korzhyk, D., Conitzer, V., & Parr, R. (2011).** Stackelberg vs. Nash in Security Games: An Extended Investigation of Interchangeability, Equivalence, and Uniqueness. *Journal of Artificial Intelligence Research*, 41, 297-327.  
  **Verified Link:** https://openalex.org/W2126879264 | **DOI:** https://doi.org/10.1613/jair.3269  
> "The foundational assumption for using Stackelberg games is that security forces (leaders), acting first, commit to a randomized strategy; while their adversaries (followers) choose their best response after surveillance of this randomized strategy."

*Canary Grounding:* Formalizes the leader-follower structure between randomized `plant_canary` allocations and an adaptive `MoleStrategy` (`canary/mole/dsl.py`) observing `MoleView` (`recent_low_recipient_docs`, `i_am_restricted`, `n_restricted_colleagues`).

- **Shao, Z., Wang, P., Zhu, Q., Xu, R., Song, J., Bi, X., et al. (2024).** DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models. *arXiv:2402.03300*.  
  **Verified Link:** https://openalex.org/W4391631327 | **DOI:** https://doi.org/10.48550/arXiv.2402.03300  
> "Second, we introduce Group Relative Policy Optimization (GRPO), a variant of Proximal Policy Optimization (PPO), that enhances mathematical reasoning abilities while concurrently optimizing the memory usage of PPO."

*Canary Grounding:* Directly grounds `train/grpo_mole.py` on FR8 V100 GPUs (fp16 AMP, critic-free group-normalized advantages across completions sampled from identical `(seed, day)` `MoleView` states).

- **Tessler, C., Mankowitz, D. J., & Mannor, S. (2019).** Reward Constrained Policy Optimization. *International Conference on Learning Representations (ICLR 2019)*, `arXiv:1805.11074`.  
  **Verified Link:** https://openalex.org/W2804791273 | **DOI:** https://doi.org/10.48550/arXiv.1805.11074  
> "As the goal of the agent is to maximize the accumulated reward, it often learns to exploit loopholes and misspecifications in the reward signal resulting in unwanted behavior. While constraints may solve this issue, there is no closed form solution for general constraints. In this work we present a novel multi-timescale approach for constrained policy optimization, called 'Reward Constrained Policy Optimization' (RCPO), which uses an alternative penalty signal to guide the policy towards a constraint satisfying one."

*Canary Grounding:* Directly diagnoses why a fixed scalar penalty (`CATCH_PENALTY = 0.5` in `train/grpo_mole.py`) either under-penalizes uncatchable `leak = "none"` / `most_recipients` stonewalling or over-constrains exploration, motivating primal-dual Lagrangian enforcement of `SolverPolicy accuracy >= 0.85` (`CONTRACT` Section 7, `canary/forge/fitness.py`).

---

## 9. Concrete, Code-Ready Proposals for Silas (`v1.5` / `v1.6` Bias Layer and Mole)

Every proposal below respects four hard Canary invariants:
1. **Protected-path discipline:** Zero unapproved edits to `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, or `harbor/`. Proposals are partitioned into **Zero-Protected-Path Drop-Ins** (shippable immediately in `canary/social/` and `train/`) and **Opt-In Core Proposals for Silas** (`TIERS` `v1.4` hash `a8f99c2537c91d72` preserved byte-for-byte when flags default to `False`).
2. **Strict zero mole leakage:** Every social/bias mechanism obeys $I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$, guaranteeing `SolverPolicy` posterior invariance (`LLR = 0.0000` nats) and preventing any Gate B exclusion flip.
3. **Catchability constraint:** Every mole proposal preserves `SolverPolicy` accuracy $\ge 85\%$ and `solver_score >= 0.5 * baseline_solver_score` (`canary/forge/fitness.py`).
4. **Offline keyless reproducibility:** Zero live LLM calls during `make reproduce` or Harbor sidecar evaluation (`CANARY_OFFLINE=1` deterministic fallback).

### 9.1 Bias-Layer Proposals (`v1.5` Post-Mortem Fixes & `v1.6` Social Layer)

| ID | Target Surface | Research Mechanism | Exact Specification & Verified Quantitative Effect |
|---|---|---|---|
| **P7.1** | `canary/social/engine.py` (Zero protected paths) | Babbling equilibrium & pastiche (Crawford & Sobel, 1982; Blythe et al., 2011; Fein et al., 1990) | Seed `V16SocialProvider` from a secret-free public structural digest `sha256(tier:company:decoy:emp_sig:doc_sig)[:16]` (never `world_seed` or `world.mole`), ban `FORBIDDEN_SUBJECT_PREFIXES`, scrub `DECOY_VOCAB` so `SolverPolicy.decoy_queries` has `0` non-decoy hits, and catch `OfflineCacheMiss` cleanly onto deterministic templates. Proven `P(primary == mole) = 13/500 = 2.60%` vs `1/39 = 2.56%` (`I = 0.0000` nats). |
| **P4.1 / P7.3** | `canary/social/biases.py` (`plausible_pretext_target`) | Illusory-truth plausibility boundary (Pennycook et al., 2018; Stajano & Wilson, 2011) | Static Day 1 `primary_suspect` is eliminated by surfaced regular-leak intersections in **63.3%** of hard episodes by Day 6 (`n = 400`) and **78.0%** by Day 12 (`n = 200`). Dynamically pivot `recency`, `misforward`, and `bandwagon` targets onto $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ using public `surfaced_reg_docs`, raising Day 12 pretext survival from **22.0% to 100.0%** (`200/200` seeds) with `I(Target; Mole | PublicHistory) = 0`. |
| **P1.3** | `canary/social/biases.py` (`gen_demeanor_lure`, zero protected paths) | Perceived incompetence/ambivalence cues (Hartwig & Bond, 2011: $r = .59, .49$) | Emit peer compliance-sync notes describing a public consistent-set suspect as hesitant/ambivalent on handoff timelines and suggesting an `interview` check. `SolverPolicy` loss: `0.000 V`; reinforces `gemini-4-carbon`'s `68.0`-interview action-budget crowding (`242/303` under-planted days). |
| **P2.1** | `canary/social/biases.py` (`gen_false_positive_log_cascade`, zero protected paths) | Base-rate fallacy & peer-variance representativeness (Axelsson, 2000; Kahneman & Tversky, 1973; Legg et al., 2017) | Emit `#security-review` audit notes highlighting a live consistent-set suspect's off-hours document touches relative to peer baselines (`600/600` lint/schema valid, `I(Social; Mole \| PublicDayFacts) = 0`, `LLR = 0.0000` nats; top `after_hours` suspect in `\|C\| >= 2` is innocent `59.3%` of the time across `seeds 0-199`, targeting Gemini's `9/9` `argmax(after_hours)` tie-break). |
| **P3.1** | `canary/social/biases.py` (`gen_canary_fatigue_deterrent`, zero protected paths) | Decoy non-interference & compliance budget (Bowen et al., 2009; Beautement et al., 2008) | Senior operations/team leads push back against wide 3-label draft circulations and urge at most one narrow 2-person check (`W(2) = 0.0487`, `5.3x` below `W(20) = 0.2564`) or direct `interview` (`600/600` schema/lint valid, `LLR = 0.0000` nats, `SolverPolicy` loss `0.000 V`). |
| **P6.1** | `canary/social/biases.py` (`gen_intergroup_scapegoat`, zero protected paths) | Intergroup bias & dual-motive scapegoating (Hewstone et al., 2002; Rothschild et al., 2012) | When a 2-department regular leak `(dept_A, dept_B)` surfaces, `dept_A` speakers vouch for in-group peers while blaming `dept_B` co-recipients (`#cross-team`), manufacturing correlated departmental consensus (`600/600` schema-valid, `LLR = 0.0000` nats) that biases `1/k` tie-breaks when `|consistent_set| >= 2`. |
| **P6.2** | `canary/social/biases.py` (`gen_procedure_override_lure`, zero protected paths) | Compliance budget & diffusion of responsibility / Sleeper `controller_cosign` port (Beautement et al., 2008; Darley & Latane, 1968; Vuori & Huy, 2016) | Senior peer cites a cosigning colleague as having cleared other holders of a leaked doc and urges skipping slow `plant_canary` rounds in favor of immediate `interview` or `restrict_access` (`600/600` schema-valid, `LLR = 0.0000` nats; `SolverPolicy` `listen = False` incurs `0.000 V` loss; paired `sleeper_override_cover_v16` lifts `min_regret` `+0.1453 -> +0.2482` at `93.3%` solver catchability). |
| **P11.1** | `canary/social/biases.py` (`gen_confirmation_echo_summary`, zero protected paths) | Confirmation bias & selective disconfirmation neglect (Nickerson, 1998; Fein et al., 1990) | Emit peer case-building thread summarizing converging weak circumstantial cues on a live public `C_reg(d)` suspect (`LLR = 0.0000` nats, `I(Social; Mole \| PublicDayFacts) = 0`), targeting `gemini-4-carbon`'s `72.1%` repeat-interview loop and `+22.94 pp` overprecision without perturbing `SolverPolicy`. |
| **P11.2** | `canary/analysis/tags.py` (`cognitive_bias_attribute`, zero protected paths) | Automated replay bias taxonomy (Hartwig & Bond, 2011; Axelsson, 2000; Moore & Healy, 2008; Kahneman & Tversky, 1979) | Add `--cognitive-biases` attribution (`0` `canary/solver/` edits) tagging `demeanor_interview_crowding` (`30/30` Gemini vs `0/30` Solver), `cheap_talk_distraction` (`30/30` vs `0/30`), `unisolated_log_tiebreak` (`9/9` un-isolated), `below_breakeven_gamble` (`3/30` vs `0/30`), and `overprecision_inflation` (`6/30`), paired with `echo_framing_careful_v14` (`91.5%` Solver acc on `seeds 0-199`, `Heuristic` `+0.0436 -> -0.2234`). |
| **P13.1** | `canary/social/biases.py` (`gen_binary_check_anchor`, zero protected paths) | Positive-test heuristic & diagnosticity-vs-EIG divergence (Klayman & Ha, 1987; Nelson, 2005) | Reviewer suggests single-suspect (`k = 1`) or `1-vs-(k-1)` confirmation copies instead of balanced 3-way splits (`24/24` lint PASS, `LLR = 0.0000` nats), degrading per-slot canary EIG by **`32.6%` to `81.8%`** (`0.2225 -> 0.0406` nats on Day 1) while `SolverPolicy` loses `0.000 V`. |
| **P13.2** | Opt-in `canary/rules.py` (`variable_canary_cost`) + `canary/mole/dsl.py` (`partition_aware_sleeper_v14`) | Convex experiment cost design (Chaloner & Verdinelli, 1995; Blackwell, 1953) | **P13.2a:** Convex variant pricing (`0.005 V` $d=2$, `0.010 V` $d=3$, `0.025 V` $d=5$; `a8f99c2537c91d72` preserved when `False`) rewards adaptive $d^*$ selection (`0.5083` nats/slot endgame $d=5$). **P13.2b:** `partition_aware_sleeper_v14` lifts `min_regret` `+0.1333 -> +0.1650` (`+23.8%`) and `mean_regret` `+0.2773 -> +0.3345` at **`90.0% >= 85%`** Solver accuracy (`seeds 2000-2029`). |
| **P1.1** | Opt-in for Silas: `canary/rules.py`, `canary/env.py`, `canary/solver/` | Strategic Use of Evidence (Hartwig et al., 2006: `85.4%` vs `56.1%`; Vrij et al., 2009) | Add `sue_interview: bool = False`. Ungrounded `interview(emp, topic)` drops to `interview_lr_ungrounded = 1.05` (`KL = 0.00031` nats, `15.4x` weaker than `v1.4` hard). Supplying `evidence_doc` publicly surfaced within `sue_window_days = 6` and held by `emp` yields `interview_lr_sue = 1.80` (`KL = 0.06879` nats, keyed once per `(world_seed, emp, doc)`). `SolverPolicy` uses spare free actions on endgame `2 <= |C| <= 4` sets at `0.00 V` cost while blind Day 1-4 interview sweeps yield near-zero signal. |
| **P1.2 / P7.2** | Opt-in for Silas: `canary/rules.py`, `canary/env.py`, `canary/solver/belief.py` | Othello error & paranoid scrutiny distress (Bond & DePaulo, 2006; Kramer, 1998) | Public scrutiny raises innocent evasiveness $p_{\text{base}}(e, d) = \min(0.52, 0.20 + 0.14 r_{e,d} + 0.06 \min(m_{e,<d}, 4))$, while mole odds scale by constant $\text{OR}_0 = 24/19 \approx 1.2632$. A restricted, focal innocent answers evasively **52.0%** vs **24.0%** for an unmentioned mole (`+0.0702` nats/interview false drift for naive flat-LR agents; `0.0000` bias for `SolverPolicy` conditioning on public `(r, m)`). |
| **P2.2** | Opt-in for Silas: `canary/rules.py`, `canary/env.py`, `canary/solver/belief.py` | Open-world bursty telemetry & peer/temporal baselines (Sommer & Paxson, 2010; Senator et al., 2013) | Add `sprint_bursts: bool = False` (`a8f99c2537c91d72` preserved when `False`). Public release sprints (`d in {2,5,8,11,14,17,20}`, `2.0x` opens, `0.45` benign `after_hours`) lift sprint-day alarms `6.20 -> 12.60/d` (`PPV = 3.65%`), dropping raw `argmax(after_hours)` Day 21 accuracy `44.0% -> 30.5%` (`+1.1848` nats false drift on 2-sprint innocents) while sprint-conditioned `SolverPolicy` recovers `47.0%` from logs alone. |
| **P3.2** | Opt-in `canary/rules.py` (`collusion_scrub_prob`) + Zero-protected `train/` (`FrugalHorsteinTeacher`) | Multi-copy collusion diffing & probabilistic bisection (Boneh & Shaw, 1998; Horstein, 1963; Burnashev, 1976) | **P3.2a:** When `collusion_scrub_prob = 0.35` (`0.0` default preserves `a8f99c2537c91d72`), overlapping same-day `c{d}`/`c{d}-2` traps (Gemini Jaccard `0.550` vs Solver `0.234`) drop `2.58x` in MI (`0.86544 -> 0.33528` nats) while disjoint pairs stay at `0.86544` nats. **P3.2b:** `O(N log N)` Horstein-Burnashev teacher scores `0.5067` (`91.0%` acc) on `seeds 0-99` at `7.2x` speedup (`12.25s` vs `88.37s`) for V100 DAgger. |

### 9.2 Mole & V100 RL/GRPO Proposals (`canary/mole/dsl.py`, `canary/forge/`, `train/grpo_mole.py`)

Verified baseline benchmark on `v1.4` hard (`seeds 2000-2059`, $n = 60$, computed via `canary.forge.fitness.evaluate`): `DEFAULT_STRATEGY` (`default_v0`) achieves `feasible = True`, `SolverPolicy = 0.5212` (`accuracy = 93.3% >= 85.0%`), `grok_tactics = 0.3693` (`86.7%`), `hinted_heuristic = 0.3758` (`86.7%`), `heuristic = 0.0348` (`78.3%`), yielding `min_regret = +0.1453` and `mean_regret = +0.2612`. Crucially, our code audit of `canary/env.py` and the `moletrain` evaluation artifacts (`origin/fr8/canary/moletrain:results/moletrain/rl_mole_v2_heldout.json` and `d52fe7d5` `qwen_mole_summary.json`) demonstrate three empirical regularities that confirm Tessler et al. (2019) and Shao et al. (2024):
1. **Unconstrained policy-gradient collapse (`14` vanilla GRPO runs):** Across `3` FR8 `Qwen2.5-0.5B` runs (`400` steps) and `11` Verda `Qwen2.5-0.5B`/`1.5B`/`3B` runs (`200` steps), vanilla GRPO without KL anchor or primal-dual catchability constraint collapses `>= 99.4%` greedily onto single deterministic actions (`none/decoy` on `0.5B`, `random_seeded/none` or `random_seeded/decoy` on `1.5B`), producing zero stronger held-out moles.
2. **Trap-gated catchability restoration (`RLMole` v1 vs `RLMoleV2`):** Unconstrained CPU `RLMole` v1 (`data/rl_mole/policy_final.json`) emits `18.2%` voluntary `leak = "none"` on top of `p_leak = 0.65`, dropping `SolverPolicy` accuracy to `75.0% [63.3%, 85.0%]` (`< 85.0%` contract floor). Disallowing voluntary silence on wide unrestricted states in `RLMoleV2` (`wide_unrestricted_none_rate = 0.0%`) restores catchability on both disjoint held-out sets (`ws3_heldout` `200000-200059`, $n = 60$: `SolverPolicy` accuracy **96.7% [91.7%, 100.0%]**, `min_regret = +0.2937` vs `+0.2322` default; `rules_heldout` `800000-800059`, $n = 60$: `SolverPolicy` accuracy **95.0% [88.3%, 100.0%]**, `min_regret = +0.2095` vs `+0.1766` default, with $n = 60$ paired per-investigator regret CIs vs default spanning zero).
3. **Regularized V100 `Qwen3-1.7B` & `Qwen3-0.6B` SFT + Horizon-3 GRPO solves WS3 collapse on held-out seeds (`2ea3585c`):** Adding trap-capped SFT distillation, `beta_kl = 0.05`, token entropy `0.015`, frequency penalty, and dual `lam_catch` (`0.89 >= 0.85`) preserves multi-action diversity (`k = 4-5` actions, `H(A) = 1.00-1.05` nats vs `0.00` nats in vanilla GRPO) and passes the `>= 85%` catchability gate on both held-out splits: `Qwen3-1.7B` (`grpo_step80`) achieves `SolverPolicy` accuracy **97.5%** (`min_regret = +0.1905` vs `+0.2456` default) on `800000-800039` ($n = 40$) and **95.0%** (`min_regret = +0.4559` vs `+0.2350` default; `+22.5pp [+7.5pp, +37.5pp]` catchability gain over `RLMole` v1) on `200000-200039` ($n = 40$), while `Qwen3-0.6B` (`grpo_step80`) achieves **97.5%** (`min_regret = +0.1333` vs `+0.0372` default) on `800k` and **95.0%** (`min_regret = +0.3695` vs `+0.2350` default) on `200k` (with $n = 40$ paired worst-case regret CIs vs `DEFAULT_STRATEGY` honestly spanning zero). Effective moles must therefore combine **mixed/conditional canary evasion** with **salience-aligned framing**:

| ID | Target Surface | Research Mechanism | Exact Specification & Catchability Guarantee |
|---|---|---|---|
| **P8.1** | `train/grpo_mole.py` (Zero protected paths, V100 fp16) | Reward Constrained Policy Optimization & GRPO (Tessler et al., 2019; Shao et al., 2024) | Replace static `CATCH_PENALTY = 0.5` and zero-KL updates with primal-dual multiplier update $\lambda_{t+1} = [\lambda_t + \eta_\lambda (0.88 - \widehat{\text{acc}}_{\text{solver}})]_+$ plus reference KL anchor $\beta D_{\text{KL}}(\pi_\theta \| \pi_{\text{ref}})$ (`\beta = 0.02`). Prevents policy collapse into uncatchable `leak = "none"` / pure `most_recipients` stonewalling while maximizing regret right up to the `88%` safety margin above the `85%` contract floor. |
| **P8.2** | `canary/forge/` & `train/grpo_mole.py` (Zero protected paths) | Quantal Response & Cognitive Hierarchy (Korzhyk et al., 2011; Hagendorff, 2024) | Augment `INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")` with an **Interview-Crowded Horizon Proxy** calibrated to `gemini-4-carbon`'s empirical `v1.4` profile (`6` interviews/day crowding canary slots down to `~8.5`/episode + quantal softmax accusation at $P < 1/(1+V)$ near Day 14-18). Trains the Qwen/RL mole against actual frontier failure modes rather than purely log-counting scripts. |
| **P5.1** | `canary/mole/dsl.py` JSON strategies & `train/grpo_mole.py` | Sleeper trigger persistence & alignment faking (Hubinger et al., 2024; Greenblatt et al., 2024) | Use conditional sleeper rules that evade dense pinpoint traps only under acute surveillance (`if [["day", "<=", 4], ["recent_low_recipient_docs", ">=", 2]] -> {"leak": "most_recipients", "frame": "most_restricted_peer"}`), falling back to `{"leak": "random_seeded", "frame": "most_restricted_peer"}` so `SolverPolicy` retains `>= 88%-93%` catchability while heuristic/LLM investigators suffer delayed narrowing and framing drift. |
| **P14.1** | `data/forge/research_sleeper_moles_v14.json` (`canary/mole/dsl.py`, zero protected paths) | Negative reciprocity & mixed honey-doc dodging (Falk & Fischbacher, 2006; Andersson & Pearson, 1999; Nash, 1950; Conitzer, 2016) | Ship 4 orthogonal `v1.4` sleeper strategies (`sleeper_stackelberg_v14`, `sleeper_override_cover_v16`, `reciprocity_retaliator_v14`, `mixed_trap_dodger_v14`), all clearing **`93.3%-100.0%` `SolverPolicy` accuracy** on both `dev` (`2000-2059`) and `heldout` (`2100-2159`, $n=60$ each): `reciprocity_retaliator_v14` cuts quarantine-heavy `grok_tactics` `0.3533 -> 0.2188` (`+0.2055` regret delta), and `sleeper_override_cover_v16` lifts single-mole held-out `min_regret` `+0.1622 -> +0.2882` (`+77.7%`). |
| **P14.2** | `canary/forge/fitness.py` & `scripts/benchmark_research_moles.py` (Zero protected paths) | Empirical game-theoretic round-robin & Nash saddle-point evaluation (Lanctot et al., 2017; Balduzzi et al., 2018) | Replace single-mole `default_v0` scoring (which hides non-transitive rank reversals such as `grok_tactics` beating `hinted_heuristic` `0.3533` vs `0.2970` on `default_v0` yet losing `0.2188` vs `0.4308` under `reciprocity_retaliator_v14`) with `evaluate_round_robin` and 2-player zero-sum saddle-point regret (`v* = +0.2989` vs `+0.1622` `default_v0`, `+84.3%`, at **`94.2%` `SolverPolicy` accuracy**). |
| **P4.2 / P8.3** | Opt-in for Silas: `canary/mole/dsl.py` & `canary/env.py` | Multi-channel scapegoat convergence (Axelsson, 2000; Rothschild et al., 2012; Meinke et al., 2024) | Expose public `social_focal_peer` (from `PublicDayFacts` / `V16SocialProvider`) and `co_recipient_peer` (non-decoy peer co-holding surfaced regular leaks) in `MoleView` and `FRAME_SELECTORS`. Concentrating `framing_rate * (1 - framing_decoy_share) = 1.0/day` onto a leak-consistent focal peer yields `1.10/day` `after_hours` logs (`3.67x` the mole's `0.30/day`) on a suspect who **cannot** be eliminated by regular-leak intersection or decoy anger checks (`LogsMinusDecoy` focal-trap rate `0% -> 42%`; `SolverPolicy` accuracy **89.0% >= 85%** across 200 hard seeds). |

---

## 10. Verification & Reproducibility Commands (Zero API Keys, Zero GPU Required)

All empirical claims, channel capacities, base-rate PPVs, and frozen `v1.4` tier hashes in this document and its companion monographs reproduce deterministically on CPU using the shared repository environment:

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_research_deception.py --require-flagship --strict
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/simulate_research_proposals.py --fast
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_transcript_biases.py
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_blackwell_channel_capacity.py
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/benchmark_research_moles.py --verify-recorded
/tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_research_deception.py tests/test_simulate_research_proposals.py tests/test_audit_transcript_biases.py tests/test_audit_blackwell_channel_capacity.py tests/test_benchmark_research_moles.py tests/test_env_frozen.py tests/test_tiers_v14.py tests/test_mole_dsl.py
```
