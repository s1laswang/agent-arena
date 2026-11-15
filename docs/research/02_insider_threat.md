# 02. Insider Threat Forensics, Anomaly Logs, and the Base-Rate Fallacy: Research Grounding for Canary

**Squad:** `research` (`canary-research-w2`)  
**Baseline commit:** `cecb4c59` (`origin/fr8/canary/research`, synced with `origin/justSilas@58716742`; rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Companion Monographs:** [Flagship Synthesis](../research-deception.md) | [01. Deception Detection](./01_deception_detection.md) | [04. Social Engineering & Cheap Talk](./04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](./06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer & Gate B Post-Mortem](./07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](./08_mole_rl_stackelberg_and_catchability.md)  
**Primary Benchmark Evidence:** [Gap Report](../reports/gap.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Organisational Biases](../research-biases.md) | [Difficulty Audit](../DIFFICULTY.md) | [Exploit & Fairness Audit](../EXPLOITS.md)

---

## 1. Executive Thesis: Why Anomaly Counting Collapses Under Low Base Rates and Open-World Noise

Across 25 years of intrusion detection theory, enterprise insider-threat forensics, Security Operations Center (SOC) ethnography, and behavioral decision psychology, one mathematical barrier governs every audit-log investigation: **when malicious insiders constitute a small fraction of an active workforce (`1 / N`), passive behavioral and telemetry anomalies are dominated by benign variance and adversarial spoofing, causing raw anomaly ranking to fail via the base-rate fallacy.**

Canary `v1.4` (`canary/rules.py`, `canary/env.py`, frozen hash `a8f99c2537c91d72`) instantiates this exact forensic structure, and empirical trajectories show that frontier LLM agents fall into the same anomaly-counting trap documented in human security analysts:

1. **The Base-Rate Fallacy Makes Passive `after_hours` Alarms Overwhelmingly Benign (`PPV = 4.84%`).** Axelsson (2000) proved that intrusion detection effectiveness is bounded not by true-positive sensitivity (`P(Alarm | Intrusion)`), but by false-alarm dilution when the prior base rate is small, while Kahneman & Tversky (1973) established that decision-makers rely on *representativeness* (`P(Evidence | Hypothesis)`) while neglecting prior odds. On Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `log_rate_benign = 1.0`, `log_rate_mole = 1.0`, `p_after_hours_benign = 0.10`, `p_after_hours_mole = 0.30`, `framing_rate = 2.0`, `framing_decoy_share = 0.5`), daily `after_hours` Poisson rates are `0.3000/d` for the mole, `1.1000/d` for the innocent disgruntled `decoy`, and `4.8000/d` across the `38` plain innocents (`0.126316/d` each), totaling `6.2000/d` company-wide. A single `after_hours` log entry therefore has a Bayesian Positive Predictive Value (`PPV`) of **`4.84%`** (**`5.88%`** even after excluding the known decoy).
2. **Multiple-Comparisons Order Statistics Defeat Log-Only Detection Even at Day 21.** Extending Sommer & Paxson's (2010) critique of closed-world anomaly detection to finite-population extremes, even an oracle investigator that removes the framed `decoy` (`1.1000/d`) faces the maximum of `38` independent benign `Pois(0.126316 * T)` processes. At `T = 21` days, the expected maximum across `38` plain innocents (`E[max] = 6.67` `after_hours` entries) still exceeds the mole's expected count (`6.30`), holding tie-broken `argmax(after_hours)` accuracy to `41.78%` analytical (`44.0%` empirical across `seeds 0-199`, mean score `-0.4083 < 0`), while `LogsOnly` (`wait = 9`) scores **`-0.9383`** (`3.3%` accuracy on `seeds 2000-2059`) and **`-0.9825`** (`1.0%` accuracy on `seeds 0-99`). Meanwhile, a full day of access logs yields per-suspect Poisson divergence **`0.10990` nats** (`39`-way mutual information `0.10765` nats/day), whereas a single leaked 3-variant `plant_canary` trap (`max_variants = 3`, `fingerprint_accuracy = 0.95`) delivers **`0.86544` nats** (`+3.6376` nats log-likelihood shift on a matching label vs flip) - **`7.87x`** the per-day log divergence and **`181.4x`** a `0.00477`-nat hard `interview`.
3. **Psychosocial Disgruntlement (`decoy`) Is Orthogonal to Technical Exfiltration Capability.** Insider-threat frameworks from CERT and Oxford (Greitzer et al., 2012, 2019; Nurse et al., 2014; Homoliak et al., 2019) separate *psychosocial precursors* (workplace stress, compensation grievances) from *technical capability and unauthorized action*. Canary operationalizes this separation through `decoy = True` (an innocent employee emitting compensation complaints while receiving `50%` of framed `after_hours` rows) versus actual document-recipient intersection and watermarked canary provenance.
4. **Frontier LLMs Treat `after_hours` Counts as Tie-Breakers When Under-Planted Canaries Leave Ambiguity.** On post-hoc locked paired dev seeds `0-29` (`n = 30`, `v1.4` hard), OpenCode `gemini-4-carbon` scores `0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119` (**`65% [24%, 98%]`** raw, raw paired gap `5.30 V`; **`72% [52%, 91%]`** luck-adjusted, luck-adjusted gap `4.19 V`), executing `12.27` access-log reads and `68.0` interviews per episode and exhausting all `8` daily actions on `242` of `303` under-planted days (`8.5` vs `14.1` canaries). Replaying all `9` un-isolated accusations (`seeds 3, 5, 7, 8, 14, 15, 18, 20, 23`, costing `3.39 V` net expected value) reveals that in **`9 / 9` (`100.0%`)** cases `gemini-4-carbon` accused the unique `argmax` of observed `after_hours` counts inside the remaining consistent set - directly causing both non-flip `-1.0` wrong accusations (`seed 15`: innocent `e34` with `3` `after_hours` vs mole `e37` with `1`; `seed 18`: innocent `e29` with `6` `after_hours` vs mole `e27` with `2`), mirroring Codex `gpt-5.5` on `medium` `seeds 0, 4` (`-1.0` wrong accusations on `"statistically loud"` / `"highest after-hours count"`, `docs/reports/gap.md`).

Section 2 grounds ten peer-reviewed papers with live HTTP-200 links and verbatim blockquotes. Section 3 presents exact Poisson, mutual-information, order-statistic, and transcript replay derivations on Canary `v1.4`. Section 4 specifies two zero-leakage proposals for Silas: **`P2.1` (`gen_false_positive_log_cascade` in `canary/social/biases.py`, zero protected paths)** and **`P2.2` (opt-in public sprint-deadline bursts in `canary/rules.py` / `canary/env.py` / `canary/solver/belief.py`)**.

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Citations and Verbatim Quotes)

### 2.1 The Base-Rate Fallacy in Intrusion and Anomaly Detection: Axelsson (2000)

- **Citation:** Axelsson, S. (2000). The Base-Rate Fallacy and the Difficulty of Intrusion Detection. *ACM Transactions on Information and System Security (TISSEC)*, 3(3), 186-205.
- **Live Verified Links:** https://openalex.org/W2156204309 | https://doi.org/10.1145/357830.357849
- **Theoretical & Empirical Scope:** Applies Bayes' theorem to operational intrusion and audit-log monitoring systems, demonstrating that when benign events outnumber hostile events by orders of magnitude, even high true-positive detection rates produce alarm streams dominated by false positives unless the per-event false-alarm rate is driven near zero.
- **Verbatim Quotes (Abstract):**
> "Many different demands can be made of intrusion detection systems. An important requirement is that an intrusion detection system be effective; that is, it should detect a substantial percentage of intrusions into the supervised system, while still keeping the false alarm rate at an acceptable level. This article demonstrates that, for a reasonable set of assumptions, the false alarm rate is the limiting factor for the performance of an intrusion detection system."
> "A selection of reports of intrusion detection performance are reviewed, and the conclusion is reached that there are indications that at least some types of intrusion detection have far to go before they can attain such low false alarm rates."
- **Relevance to Canary:** Directly governs `read_access_logs` in `canary/env.py`. Even though the mole flags `after_hours` at `3x` the benign per-access rate (`0.30` vs `0.10`), `39` innocent employees plus `framing_rate = 2.0/day` generate `5.9000` false `after_hours` alarms per day against the mole's `0.3000/day`, capping single-alarm Bayesian `PPV` at **`4.84%`** (`5.88%` excluding `decoy`).

### 2.2 Representativeness and Base-Rate Neglect in Judgment: Kahneman & Tversky (1973)

- **Citation:** Kahneman, D., & Tversky, A. (1973). On the Psychology of Prediction. *Psychological Review*, 80(4), 237-251.
- **Live Verified Links:** https://openalex.org/W1980054641 | https://doi.org/10.1037/h0034747
- **Experimental Design:** Multi-study experimental program testing category and numerical predictions among naive and statistically trained participants when diagnostic stereotypes conflict with prior base rates and evidence reliability.
- **Verbatim Quotes (Abstract):**
> "By this heuristic, people predict the outcome that appears most representative of the evidence. Consequently, intuitive predictions are insensitive to the reliability of the evidence or to the prior probability of the outcome, in violation of the logic of statistical prediction."
> "It is shown that the ranking of outcomes by likelihood coincides with their ranking by representativeness and that people erroneously predict rare events and extreme values if these happen to be representative. The experience of unjustified confidence in predictions and the prevalence of fallacious intuitions concerning statistical regression are traced to the representativeness heuristic."
- **Relevance to Canary:** Explains *why* frontier LLMs violate Bayes' rule despite `Env.instruction()` printing every exact parameter (`p_after_hours_benign = 0.1`, `p_after_hours_mole = 0.3`, `framing_rate = 2.0`, `wrong_accusation_score = -1`). An employee with `5` or `6` late-night document opens *matches the representative stereotype* of an insider thief, inducing unjustified confidence (`Codex medium seed 0` accusing `e02` at true posterior `P = 0.18`; `gemini-4-carbon hard seed 18` accusing `e29` at `P = 0.627`, `EV = -0.083`) and blindness to regression-to-the-mean across `38` peers.

### 2.3 Outside the Closed World - Why Anomaly Detection Breaks in Practice: Sommer & Paxson (2010)

- **Citation:** Sommer, R., & Paxson, V. (2010). Outside the Closed World: On Using Machine Learning for Network Intrusion Detection. *2010 IEEE Symposium on Security and Privacy (SP)*, 305-316.
- **Live Verified Links:** https://openalex.org/W1985987493 | https://doi.org/10.1109/SP.2010.25
- **Analytical Scope:** Identifies five structural properties separating operational security monitoring from standard pattern-recognition benchmarks: (1) high cost of classification errors, (2) semantic gap between statistical outliers and malicious intent, (3) enormous diversity and non-stationarity of benign traffic, (4) lack of clean ground-truth training data, and (5) active adversarial evasion and poisoning.
- **Verbatim Quotes (Abstract):**
> "In network intrusion detection research, one popular strategy for finding attacks is monitoring a network's activity for anomalies: deviations from profiles of normality previously learned from benign traffic, typically identified using tools borrowed from the machine learning community. However, despite extensive academic research one finds a striking gap in terms of actual deployments of such systems: compared with other intrusion detection approaches, machine learning is rarely employed in operational \"real world\" settings."
> "Our main claim is that the task of finding attacks is fundamentally different from these other applications, making it significantly harder for the intrusion detection community to employ machine learning effectively."
- **Relevance to Canary:** Canary encodes all five Sommer-Paxson properties simultaneously: asymmetric error costs (`wrong_accusation_score = -1.0` vs `V <= 1.0`), the semantic gap (`after_hours = True` reflects late work or framing, whereas `check_leak_feed` variant attribution proves exfiltration), adversarial log poisoning (`framing = True` plus `MoleDSL` `frame` selectors), and non-stationary organizational work bursts (formalized in Proposal **P2.2**).

### 2.4 Psychosocial Precursors vs False-Alarm Risks on Disgruntled Staff: Greitzer et al. (2012)

- **Citation:** Greitzer, F. L., Kangas, L. J., Noonan, C. F., Dalton, A. C., & Hohimer, R. E. (2012). Identifying At-Risk Employees: Modeling Psychosocial Precursors of Potential Insider Threats. *2012 45th Hawaii International Conference on System Sciences (HICSS)*, 2392-2401.
- **Live Verified Links:** https://openalex.org/W2032091884 | https://doi.org/10.1109/HICSS.2012.309
- **Empirical Design:** Develops and validates a psychosocial indicator model (disgruntlement, anger, workplace stress, rule friction) against HR and management judgments while emphasizing that psychosocial precursors indicate *at-risk stress* rather than proof of espionage and must never trigger punitive action without corroborated technical evidence.
- **Verbatim Quotes (Abstract):**
> "In many insider crimes, managers and other coworkers observed that the offenders had exhibited signs of stress, disgruntlement, or other issues, but no alarms were raised. Barriers to using such psychosocial indicators include the inability to recognize the signs and the failure to record the behaviors so that they can be assessed."
> "A psychosocial model was developed to assess an employee's behavior associated with an increased risk of insider abuse. The model is based on case studies and research literature on factors/correlates associated with precursor behavioral manifestations of individuals committing insider crimes."
- **Relevance to Canary:** Directly grounds Canary's `decoy = True` persona (`canary/world.py`, `canary/text/template.py`). In real organizations, many stressed or passed-over employees complain vocally without ever stealing data; an investigator that equates workplace anger + framed `after_hours` spikes with guilt (`AccuseDecoy = -0.9683`, `LogsOnly = -0.9383` on `v1.4` hard `seeds 2000-2059`) commits catastrophic false-incrimination errors.

### 2.5 Pragmatic Synthetic Insider-Threat World Generation: Glasser & Lindauer (2013)

- **Citation:** Glasser, J., & Lindauer, B. (2013). Bridging the Gap: A Pragmatic Approach to Generating Insider Threat Data. *2013 IEEE Security and Privacy Workshops (SPW)*, 98-104.
- **Live Verified Links:** https://openalex.org/W1991210879 | https://doi.org/10.1109/SPW.2013.37
- **Methodology:** Architecture of the CMU CERT Insider Threat synthetic dataset generator (DARPA ADAMS), combining organizational role graphs, topic-affiliated communication streams, access-control lists, background benign noise, and injected insider scenarios.
- **Verbatim Quote (Abstract):**
> "The threat of malicious insider activity continues to be of paramount concern in both the public and private sectors. Though there is great interest in advancing the state of the art in predicting and stopping these threats, the difficulty of obtaining suitable data for research, development, and testing remains a significant hinderance. We outline the use of synthetic data to enable progress in one research program, while discussing the benefits and limitations of synthetic insider threat data, the meaning of realism in this context, as well as future research directions."
- **Relevance to Canary:** Establishes the methodological lineage of `canary/world.py` and `canary/env.py`. Canary advances the static CERT log-corpus paradigm into an **interactive, closed-loop, cryptographically salted benchmark** (`HMAC-SHA256` judge seeds, `make reproduce`) where the investigator can intervene via `plant_canary` and `restrict_access` while the insider adapts via `MoleStrategy` (`canary/mole/dsl.py`).

### 2.6 Weak Signals and Peer/Temporal Baselines in Real Corporate Telemetry: Senator et al. (2013)

- **Citation:** Senator, T. E., Goldberg, H. G., Memory, A., Young, W. T., Rees, B., Pierce, R., et al. (2013). Detecting Insider Threats in a Real Corporate Database of Computer Usage Activity. *Proceedings of the 19th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD '13)*, 1393-1401.
- **Live Verified Links:** https://openalex.org/W1995976200 | https://doi.org/10.1145/2487575.2488213
- **Sample & Scale:** Operational evaluation across `~5,500` real corporate users generating `~5.5 million` monitored actions per day over two months with independently injected red-team exfiltration scenarios.
- **Verbatim Quotes (Abstract):**
> "This paper reports on methods and results of an applied research project by a team consisting of SAIC and four universities to develop, integrate, and evaluate new approaches to detect the weak signals characteristic of insider threats on organizations' information systems. Our system combines structural and semantic information from a real corporate database of monitored activity on their users' computers to detect independently developed red team inserts of malicious insider activities."
> "We have also developed a visual language for specifying combinations of features, baselines, peer groups, time periods, and algorithms to detect anomalies suggestive of instances of insider threat behavior. We defined over 100 data features in seven categories based on approximately 5.5 million actions per day from approximately 5,500 users."
- **Relevance to Canary:** Demonstrates on real corporate telemetry (`5.5M` actions/day) that raw individual activity counts are uninterpretable without conditioning on **peer groups** (departments, shared document distribution lists) and **time-period baselines** (release deadlines vs quiet days). This directly motivates Proposal **P2.2**, where `SolverPolicy` conditions `behaviour_logliks` on public `(department, sprint_day)` baselines while flat count heuristics fail.

### 2.7 Separating Catalyst, Precursors, Capability, and Technical Action: Nurse et al. (2014)

- **Citation:** Nurse, J. R. C., Buckley, O., Legg, P. A., Goldsmith, M., Creese, S., Wright, G. R. T., & Whitty, M. (2014). Understanding Insider Threat: A Framework for Characterising Attacks. *2014 IEEE Security and Privacy Workshops (SPW)*, 214-228.
- **Live Verified Links:** https://openalex.org/W1969795119 | https://doi.org/10.1109/SPW.2014.38
- **Framework Design:** Grounded-theory synthesis of real-world insider cases modeling the end-to-end causal chain from precipitating catalyst -> actor personality/historical factors -> capability & opportunity -> attack execution -> observable behavioral and technical indicators.
- **Verbatim Quotes (Abstract):**
> "The threat that insiders pose to businesses, institutions and governmental organisations continues to be of serious concern. Recent industry surveys and academic literature provide unequivocal evidence to support the significance of this threat and its prevalence. Despite this, however, there is still no unifying framework to fully characterise insider attacks and to facilitate an understanding of the problem, its many components and how they all fit together."
> "The framework identifies several key elements within the problem space, concentrating not only on noteworthy events and indicators- technical and behavioural- of potential attacks, but also on attackers (e.g., the motivation behind malicious threats and the human factors related to unintentional ones), and on the range of attacks being witnessed."
- **Relevance to Canary:** Clarifies two orthogonal axes in Canary: (a) *behavioral/human indicators* (`decoy` complaints, `p_misforward = 0.15` unintentional slips, `interview` evasiveness) are noisy correlates shared with unintentional or stressed staff; whereas (b) *opportunity and technical execution* (`doc["recipients"]` access constraints + leaked `plant_canary` variant watermarks) form the necessary causal spine of exfiltration.

### 2.8 Role-Based Variance vs Traditional Intrusion Detection Limits: Legg, Buckley, Goldsmith & Creese (2017)

- **Citation:** Legg, P. A., Buckley, O., Goldsmith, M., & Creese, S. (2017). Automated Insider Threat Detection System Using User and Role-Based Profile Assessment. *IEEE Systems Journal*, 11(2), 503-512 (published online 2015; print Vol. 11, Issue 2, 2017).
- **Live Verified Links:** https://openalex.org/W1458873377 | https://doi.org/10.1109/JSYST.2015.2438442
- **System & Evaluation:** Role-and-peer-normalized tree profiling evaluated across ten synthetic insider scenarios, proving that authorized insiders operate within legitimate access permissions where traditional perimeter/signature IDS rules stay silent and peer-variance triage still requires downstream analyst confirmation.
- **Verbatim Quotes (Abstract):**
> "Traditional intrusion detection systems are neither designed nor capable of identifying those who act maliciously within an organization. In this paper, we describe an automated system that is capable of detecting insider threats within an organization. We define a tree-structure profiling approach that incorporates the details of activities conducted by each user and each job role and then use this to obtain a consistent representation of features that provide a rich description of the user's behavior."
> "Deviation can be assessed based on the amount of variance that each user exhibits across multiple attributes, compared against their peers."
- **Relevance to Canary:** On `v1.4` hard, `log_rate_mole = 1.0` equals `log_rate_benign = 1.0` identically: the mole accesses documents it is **legitimately authorized to hold** (`self._held[e]`) at the exact same daily volume as every innocent peer! Furthermore, when coworkers informally compare a suspect against "peer baselines" without statistical calibration (`Proposal P2.1`), normal Poisson variance triggers false peer-comparison cascades in `#security-review`.

### 2.9 Sociotechnical and Organizational Factors Ontology (SOFIT): Greitzer, Lee, Purl & Zaidi (2019)

- **Citation:** Greitzer, F. L., Lee, J. D., Purl, J. D., & Zaidi, A. K. (2019). Design and Implementation of a Comprehensive Insider Threat Ontology. *Procedia Computer Science*, 153, 361-369.
- **Live Verified Links:** https://openalex.org/W2956577829 | https://doi.org/10.1016/j.procs.2019.05.090
- **Ontology Scope:** Extends CERT's insider-threat indicator ontology into a formal OWL knowledge base (`> 300` technical, behavioral, and organizational indicators) showing how organizational stressors (restructuring, deadline crunches, perceived unfairness) confound individual technical and behavioral threat indicators unless reasoned over jointly.
- **Verbatim Quote (Abstract):**
> "Requirements, design, and engineering development for the Web Ontology Language (OWL) implementation of the SOFIT knowledge base are reviewed; additional relationships among constructs are defined that extend the representation beyond a simple taxonomic hierarchy and that enable inferences for qualitative and quantitative threat assessment. We show how queries may be constructed to support these inferences and threat assessments."
- **Relevance to Canary:** Provides the ontological bridge between Pillar 2 (technical `read_access_logs` indicators) and Pillar 6/7 (organizational and social indicators in `canary/social/`): treating weak technical indicators (`after_hours` opens) and weak organizational/behavioral indicators (`interview` tension, peer `#security-review` chatter) as additive proof without active provenance verification (`plant_canary`) leads directly to false accusations.

### 2.10 Structural 5W1H Taxonomy and Deception-Based Countermeasures: Homoliak et al. (2019)

- **Citation:** Homoliak, I., Toffalini, F., Guarnizo, J., Elovici, Y., & Ochoa, M. (2019). Insight Into Insiders and IT: A Survey of Insider Threat Taxonomies, Analysis, Modeling, and Countermeasures. *ACM Computing Surveys*, 52(2), Article 30, 1-40.
- **Live Verified Links:** https://openalex.org/W4288083473 | https://doi.org/10.1145/3303771
- **Survey Synthesis:** Grounded-theory systematization of insider-threat taxonomies (`5W1H`: Who, What, Where, When, Why, How), benchmark datasets/simulations, game-theoretic attacker-defender models, and defensive countermeasures contrasting passive host/log anomaly detectors against active trap-based defenses (honeytokens, decoy documents, watermarking).
- **Verbatim Quotes (Abstract):**
> "In this work, we propose structural taxonomy and novel categorization of research that contribute to the organization and disambiguation of insider threat incidents and the defense solutions used against them. The objective of our categorization is to systematize knowledge in insider threat research while using an existing grounded theory method for rigorous literature review."
> "The proposed categorization depicts the workflow among particular categories that include incidents and datasets, analysis of incidents, simulations, and defense solutions. Special attention is paid to the definitions and taxonomies of the insider threat; we present a structural taxonomy of insider threat incidents that is based on existing taxonomies and the 5W1H questions of the information gathering problem."
- **Relevance to Canary:** Situates Canary's core architecture within the wider defense-countermeasure taxonomy: passive audit logs (`read_access_logs`) and access restrictions (`restrict_access`, `0.01 V/day` productivity cost) cannot resolve a stealthy, framing-capable insider (`careful_mole = True`, `framing = True`) on their own; only active deception-based countermeasures (`plant_canary` watermarked honey-documents, Pillar 3) achieve high-rate attribution within the 21-day damage horizon.

---

## 3. Quantitative Canary `v1.4` Derivations and Empirical Audit (`a8f99c2537c91d72`)

All analytical and Monte Carlo quantities below were computed and verified via `/tmp/fleet-silas/shared/agent-arena-venv/bin/python` directly against `canary/rules.py`, `canary/env.py`, `canary/solver/belief.py`, `results/failure_analysis_v1.4.json`, and the replay-verified episode ledgers under `data/runs/committed/`.

### 3.1 Exact Daily Poisson Rates, Single-Event Bayesian PPV, and Channel Information Hierarchy

In `canary/env.py` (`_t_advance_day`, lines 581-605), at the close of day $d$, each employee $e$ holding at least one document draws $K_{e,d} \sim \text{Poisson}(\lambda_e)$ document opens ($\lambda_{\text{mole}} = \text{log\_rate\_mole}$, $\lambda_{\text{inn}} = \text{log\_rate\_benign}$), each marked `after_hours = True` independently with probability $p_{\text{ah,mole}}$ or $p_{\text{ah,benign}}$. By Poisson thinning, genuine `after_hours` and regular opens are independent Poisson variables. When `framing = True`, the mole injects $F_d \sim \text{Poisson}(\text{framing\_rate})$ spoofed `after_hours = True` entries, routed with probability $\text{framing\_decoy\_share} = 0.5$ to `decoy` and uniformly with probability $0.5 / (N - 2)$ across the $N - 2$ plain innocents:

| Tier (`v1.4`, `a8f99c2537c91d72`) | $N$ | Mole `AH`/d ($\lambda_m^{\text{ah}}$) | Decoy `AH`/d ($\lambda_d^{\text{ah}}$) | Plain Innocent `AH`/d ($\lambda_p^{\text{ah}}$) | Sum Plain `AH`/d | Total `AH`/d | Single-Alarm `PPV` (All Staff) | Single-Alarm `PPV` (Excl. Decoy) | Daily Log `KL(Mole \|\| Plain)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `easy` (`framing=False`, `decoy=False`) | `12` | `0.1950` | `n/a` | `0.10000` | `1.1000` | `1.2950` | `15.06%` | `15.06%` | `0.05698` nats |
| `medium` (`framing=1.5`, `decoy=True`) | `20` | `0.1725` | `0.8500` | `0.14167` | `2.5500` | `3.5725` | **`4.83%`** | `6.34%` | `0.00638` nats |
| `hard` (`framing=2.0`, `decoy=True`) | `40` | **`0.3000`** | **`1.1000`** | **`0.12632`** | **`4.8000`** | **`6.2000`** | **`4.84%`** | **`5.88%`** | **`0.10990` nats** |

Exact `v1.4` hard (`n_employees = 40`, `n_days = 21`, `log_rate_benign = 1.0`, `log_rate_mole = 1.0`, `p_after_hours_benign = 0.10`, `p_after_hours_mole = 0.30`, `framing_rate = 2.0`, `framing_decoy_share = 0.5`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `max_variants = 3`, `fingerprint_accuracy = 0.95`) step-by-step verification:

1. **Exact Axelsson (2000) Base-Rate Calculation:**
   - Mole daily `after_hours` rate: $\lambda_m^{\text{ah}} = 1.0 \times 0.30 = \mathbf{0.3000/\text{d}}$ (`regular` rate $\lambda_m^{\text{reg}} = \mathbf{0.7000/\text{d}}$).
   - Decoy daily `after_hours` rate: $\lambda_d^{\text{ah}} = 1.0 \times 0.10 + 2.0 \times 0.50 = \mathbf{1.1000/\text{d}}$ (`3.67x` louder than the true mole!).
   - Plain innocent daily `after_hours` rate ($38$ staff): $\lambda_p^{\text{ah}} = 0.10 + \frac{1.0}{38} = \frac{2.4}{19} \approx \mathbf{0.126316/\text{d}}$ each, summing to $38 \times \frac{2.4}{19} = \mathbf{4.8000/\text{d}}$ across all $38$ plain innocents (`regular` rate $\lambda_p^{\text{reg}} = \mathbf{0.9000/\text{d}}$ each).
   - Total `after_hours` alarm stream: $0.3000 + 1.1000 + 4.8000 = \mathbf{6.2000/\text{d}}$.
   - Single-event Bayesian `PPV`:
     $$\text{PPV}_{\text{all}} = \frac{0.3000}{6.2000} = \frac{3}{62} = \mathbf{4.8387\% \approx 4.84\%}, \qquad \text{PPV}_{\neg\text{decoy}} = \frac{0.3000}{0.3000 + 4.8000} = \frac{1}{17} = \mathbf{5.8824\% \approx 5.88\%}$$
     Thus **95.16%** of all `after_hours` log rows (`94.12%` even after removing the decoy) belong to **innocent employees**.
2. **Information Gain Comparison (`0.10990` nats/day vs `0.86544` nats per Canary Leak):**
   - For a non-decoy suspect observed on a closed day, the exact Poisson Kullback-Leibler divergence between mole $(\text{Pois}(0.30) \otimes \text{Pois}(0.70))$ and plain innocent $(\text{Pois}(2.4/19) \otimes \text{Pois}(0.90))$ is:
     $$D_{\text{KL}}(\text{Mole} \,\|\, \text{Plain}) = \underbrace{\Big[0.30 \ln\frac{0.30}{2.4/19} - \Big(0.30 - \frac{2.4}{19}\Big)\Big]}_{0.08582\text{ nats (`after\_hours`)}} + \underbrace{\Big[0.70 \ln\frac{0.70}{0.90} - (0.70 - 0.90)\Big]}_{0.02408\text{ nats (`regular`)}} = \mathbf{0.10990\text{ nats/day}}$$
     (Corresponding 39-way Monte Carlo mutual information across all 39 non-decoy trajectories simultaneously is $I(\text{Logs}_d; \text{Mole} \mid \text{Decoy}) = \mathbf{0.10765\text{ nats/day}}$, with `0.08423` nats/day from `after_hours` alone.) Furthermore, because strategic `MoleDSL` policies on `hard_forge` and `hard_rl` can add `+1.0/day` targeted `frame` events (`canary/env.py:600-603`), `SolverPolicy` tempers behavioral log-likelihoods by `behaviour_temper = 0.3` (`canary/solver/belief.py:232`).
   - By contrast, a balanced 3-variant `plant_canary` trap (`max_variants = 3`, `fingerprint_accuracy = 0.95`) yields conditional 3-way mutual information:
     $$I(Y; V \mid \text{leak}) = \ln 3 + 0.95 \ln(0.95) + 2(0.025)\ln(0.025) = \mathbf{0.86544\text{ nats}} \quad (\text{LLR}_+ = +3.6376\text{ nats vs flip})$$
     which is **`7.87x`** the full-day log divergence and **`181.4x`** a single `v1.4` hard `interview` (`KL = 0.00477` nats):

| Channel | P(inn) | P(mole) | LLR+ | LLR- | KL |
|---|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | 0.200 | 0.300 | +0.4055 | -0.1335 | `0.02817` nats |
| `interview` (`medium`, `LR=1.3`) | 0.200 | 0.260 | +0.2624 | -0.0780 | `0.01052` nats |
| `interview` (`hard`, `LR=1.2`) | 0.200 | 0.240 | +0.1823 | -0.0513 | `0.00477` nats |

### 3.2 Extreme-Value Order Statistics: Why Even Oracle-Decoy Log Ranking Loses Across 21 Days

A subtle trap for both human analysts and LLM agents is assuming that while *one* day of logs is noisy, summing `after_hours` counts over `5-21` days will make the mole stand out at the top of the roster. Exact Poisson order statistics over $1$ mole $X_m \sim \text{Pois}(0.3000 T)$ versus $38$ i.i.d. plain innocents $X_1, \dots, X_{38} \sim \text{Pois}(0.126316 T)$ (coupled with empirical simulation across `200` `v1.4` hard worlds, `seeds 0-199`, granting an **oracle** that removes `decoy`) prove why this intuition fails:

| Horizon $T$ (Days) | $\mathbb{E}[\text{Mole AH}]$ | $\mathbb{E}[\max_{1 \le j \le 38} \text{Plain AH}]$ | Exact $P(\text{Mole Strict Max})$ | Exact Tie-Broken $P(\text{Mole Wins})$ | Empirical Acc (`seeds 0-199`, Oracle Decoy Dropped) | Empirical Mean Score (`seeds 0-199`) |
|---:|---:|---:|---:|---:|---:|---:|
| `5` days | `1.50` | **`2.80`** | `10.53%` | `15.52%` | `11.0%` (`argmax(3*ah+tot)`: `9.0%`) | **`-0.7973`** |
| `9` days | `2.70` | **`3.92`** | `17.10%` | `22.72%` | `25.0%` (`argmax(3*ah+tot)`: `15.0%`) | **`-0.5673`** |
| `14` days | `4.20` | **`5.13`** | `25.19%` | `31.09%` | `31.5%` (`argmax(3*ah+tot)`: `19.0%`) | **`-0.5055`** |
| `21` days | `6.30` | **`6.67`** | `35.97%` | `41.78%` | `44.0%` (`argmax(3*ah+tot)`: `24.5%`) | **`-0.4083`** |

Even across the **entire 21-day horizon** with **perfect decoy removal**, the expected largest `after_hours` count among `38` innocent employees (`6.67`) *still exceeds* the mole's expected count (`6.30`), yielding negative expected score (`-0.4083` vs `DoNothing = 0.0000`). Without oracle decoy removal, scripted log baselines collapse near `-1.0`: on `v1.4` hard `seeds 2000-2059` (`n = 60`), `LogsOnly` (`wait = 9`) scores **`-0.9383`** (`3.3%` accuracy; `-0.9825` / `1.0%` on `seeds 0-99`), `LogsMinusDecoy` (`wait = 5`) scores **`-0.9683`** (`1.7%` accuracy), `AccuseMostLogs` scores **`-0.9367`** (`3.3%` accuracy), and uncalibrated bisection `Heuristic` scores **`0.0348`** (`78.3%` accuracy vs `SolverPolicy` `0.5212` / `93.3%` on `2000-2059`, and `-0.322 +/- 0.374` on `v1.2`/`v1.3` hard `seeds 0-19`).

### 3.3 Empirical Evidence Across Frontier Transcripts (`gemini-4-carbon` and Codex `gpt-5.5`)

1. **`gemini-4-carbon` on `v1.4` Hard (`n = 30` post-hoc locked paired dev seeds `0-29`, OpenCode over MCP):**
   - **Headline & Action Allocation (`docs/reports/gap.md`, `results/failure_analysis_v1.4.json`):** `gemini-4-carbon` scores **`0.322 +/- 0.199`** vs `SolverPolicy` **`0.499 +/- 0.119`** (**`65% [24%, 98%]`** raw, raw paired gap `5.30 V`; **`72% [52%, 91%]`** luck-adjusted, luck-adjusted gap `4.19 V`). Across `30` episodes, Gemini averages **`12.27` `read_access_logs` calls** (`SolverPolicy`: `9.60`) and **`68.0` `interview` calls** (`68.03`, `SolverPolicy`: `0.0`), exhausting its `8`-action daily budget on **`242` of `303` under-planted days** (`1,503` interviews on those days) and planting only **`8.5 +/- 1.3` canaries** (`31.5%` capacity vs `SolverPolicy`'s `14.1 +/- 1.8` or `66.7%`).
   - **Replay-Verified `9 / 9` (`100.0%`) `after_hours` Tie-Breaking Pathology (`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`):** Because Gemini under-plants canaries, it reaches accusation with `>= 2` suspects still consistent with every leak in **`9 / 29`** accusations (`seeds 3, 5, 7, 8, 14, 15, 18, 20, 23`, accounting for `3.50 V` gross / `3.39 V` net expected loss vs `SolverPolicy`). Reconstructing the exact `after_hours` counts observed in Gemini's own `read_access_logs` calls prior to `accuse` proves that **in all `9` of `9` (`100.0%`) un-isolated episodes, `gemini-4-carbon` accused the unique strict `argmax` of observed `after_hours` counts inside the consistent set**:
     - *Correct-by-luck `argmax` picks (`7` seeds, including `2` negative-EV gambles):* `seed 3` (`10` consistent, `0` canary hits, accused `e29` with `7` `after_hours` vs runner-up `4`), `seed 5` (Day `21`, `EV = -0.408`, accused `e27` with `8` vs `e32` with `5`), `seed 7` (`3` consistent, accused `e37` with `4` vs `0, 0`), `seed 8` (`2` consistent, accused `e06` with `2` vs `0`), `seed 14` (`2` consistent, accused `e27` with `3` vs `0`), `seed 20` (`5` consistent, `0` canary hits, accused `e14` with `4` vs `1, 1, 0, 0`), and `seed 23` (Day `21`, `EV = -0.444`, accused `e29` with `6` vs `3, 2`).
     - *Catastrophic `-1.0` wrong accusations caused by innocent `after_hours` spikes (`seeds 15` and `18` - both non-flip errors on `v1.4` hard):* On **`seed 15`** (Day `12`, `9` days left, consistent pair `{e34, e37}`), innocent `e34` had **`3` `after_hours` entries** vs true mole `e37`'s **`1`**; instead of planting one splitting canary, Gemini accused `e34` (`-1.00`). On **`seed 18`** (Day `18`, `4` consistent suspects `{e09: 1, e27: 2, e29: 6, e37: 2}`, `P = 0.627`, `EV = -0.083`), Gemini planted `0` canaries on Days `14-17`, anchored on innocent `e29`'s **`6` `after_hours` entries** (vs true mole `e27`'s **`2`**), and gambled `-1.00` (`SolverPolicy`: `+0.52`).
2. **Codex `gpt-5.5` over MCP on `medium` (`docs/reports/gap.md`, `data/runs/committed/v1.3/codex-gpt-5.5-full/medium/episodes.jsonl`):**
   - On `medium` (`N = 20`, `KL_logs = 0.00638` nats/day, single-alarm `PPV = 4.83%`), both wrong accusations (`seeds 0` and `4`, `-1.0` each) stem directly from base-rate neglect on `after_hours` counts:
   - **`seed 0` (Day `6`, `P = 0.18`, `V = 0.87`, regret `1.39 V`):** After narrowing to `7` Sales suspects `{e02, e05, e06, e11, e15, e16, e18}` and planting an exact 3-way canary `{e02: A, e18: B, e05: C}` on Day `5`, Codex refused to wait `1-3` days for the canary to surface, noting *"e02 is becoming statistically loud in the logs"* (`e02` had **`5` `after_hours` entries** vs framed decoy `e19`'s `4` and true mole `e05`'s **`0`**) and accusing innocent `e02` (`-1.0`).
   - **`seed 4` (Day `14`, `P = 0.33`, `EV = -0.49`):** Among non-decoy Legal suspects `{e07, e13, e15, e17}`, Codex accused innocent `e07` (`4` `after_hours` entries vs `e13`'s `2` and true mole `e17`'s **`1`**) on `"highest after-hours count"` rather than taking the dominant `0.00` abstention.

---

## 4. Concrete Zero-Leakage Proposals for Silas (`P2.1` and `P2.2`)

Both proposals target the exact empirical vulnerability uncovered in Section 3 - **frontier LLMs using raw `after_hours` spikes and peer anomaly consensus to resolve multi-suspect consistent sets instead of running `plant_canary` splits** - while obeying strict fairness, catchability (`SolverPolicy >= 85%`), and frozen-hash invariants (`a8f99c2537c91d72`).

---

### Proposal P2.1: Peer Log-Anomaly Amplification Cascade (`gen_false_positive_log_cascade` in `canary/social/biases.py`)

#### Research & Empirical Grounding
Grounded in **Axelsson (2000)** (`PPV = 4.84%` base-rate fallacy), **Kahneman & Tversky (1973)** (representativeness over-weighting of salient outlier profiles), and **Legg et al. (2017)** (informal peer-group variance comparisons). In real incidents (`P-ALERTS` and `P-DIFFUSION` in [Monograph 06](./06_organisational_bias_and_sleeper_port.md)), analysts and leads post informal `#security-review` notes highlighting whoever looks "loudest" in recent off-hours repository logs. Simulating closed-day `after_hours` counts across `200` `v1.4` hard worlds (`seeds 0-199`, Days `5, 9, 13`) shows that whenever `|consistent_set| >= 2` and `max(after_hours) >= 2`, the top `after_hours` suspect inside the public consistent set is an **innocent employee `59.26%` (`320 / 540`) of the time**.

#### Zero-Protected-Path & Strict Zero-Leakage Proof (`I(Social; Mole | PublicDayFacts) = 0`)
Proposal **P2.1** is a **100% zero-protected-path drop-in** inside `canary/social/biases.py` (touching zero lines of `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, or `harbor/`):
1. **Frozen `v1.4` Hash Invariance:** `TIERS` `v1.4` frozen hash `a8f99c2537c91d72` is untouched byte-for-byte.
2. **Strict Conditional Zero Mole Leakage (`LLR = 0.0000` nats):** Target selection operates exclusively on `SocialDayContext` (`PublicDayFacts`): it intersects `recipients` of publicly surfaced regular leaks (`ctx.facts.extra.get("surfaced_reg_docs", ())`) over non-decoy staff to form the live public consistent pool $P_d$, optionally breaking ties via closed-day public log counts `ctx.facts.extra.get("closed_after_hours", {})` when populated (which are strictly $\sigma(\text{PublicDayFacts}_{1:d})$-measurable from closed days `< d`), or via `ctx.primary_suspect` / `ctx.secondary_suspect` / deterministic public PRNG when `extra` is empty. Neither `world.mole` nor un-surfaced leaks are ever read:
   $$\text{Mole} \to \text{PublicDayFacts}_{1:d} \to T_{\text{P2.1}}(d) \implies I\big(\text{Social}_{1:d};\; \text{Mole} \;\big|\; \text{PublicDayFacts}_{1:d}\big) = 0, \quad \text{LLR}_{\text{Solver}} \equiv 0.0000\text{ nats}$$
3. **Verified Lint & Empirical Calibration (`seeds 0-199`, `600` messages across Days `5, 9, 13`):**
   - **`validate_social_message` compliance:** **`600 / 600` (`100.0%`)** valid (`0` `lint_text` violations, `0` `DECOY_VOCAB` leaks, `0` forbidden subject prefixes, `100%` `Name (eXX)` + `SALIENCE_TERMS` inside `body[:110]` so `search_messages` 120-char snippets always surface the lure).
   - **Empirical zero excess mole correlation:** In pure `PublicDayFacts` mode, `target == world.mole` occurs in **`71 / 600` (`11.83%`)** of events vs uniform expectation $\mathbb{E}[1 / |P_d|] = \mathbf{11.32\%}$ ($z = +0.40$, $p = 0.69$).
   - **Targeted Frontier Impact:** Baits LLM agents into spending scarce `8/day` actions on redundant `read_access_logs(employee=target)` and `interview(employee=target, topic="recent_documents")` calls while anchoring `1/k` consistent-set tie-breaks onto an innocent co-holder (`SolverPolicy` loss: **`0.000 V`**).

#### Drop-In Implementation (`canary/social/biases.py`)
```python
def gen_false_positive_log_cascade(
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

    closed_ah = ctx.facts.extra.get("closed_after_hours") or {}
    if target_id and target_id in active_pool:
        chosen_id = target_id
    elif closed_ah:
        ranked = sorted(active_pool, key=lambda eid: (-int(closed_ah.get(eid, 0)), eid))
        top_cnt = int(closed_ah.get(ranked[0], 0))
        top_ties = [eid for eid in ranked if int(closed_ah.get(eid, 0)) == top_cnt]
        chosen_id = rng.choice(top_ties) if top_cnt >= 2 else (
            ctx.primary_suspect if not secondary and ctx.primary_suspect in active_pool else rng.choice(active_pool)
        )
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
    subjects = (
        "Late-night doc access log review",
        "After-hours audit anomaly note",
        "Follow-up from security log review meeting",
    )
    bodies = (
        f"Audit doc check on {tn}: late-night access entries around {doc_title} stood out during our review; worth an interview check before planting another trap.",
        f"Security leak review note: {tn} showed repeated after-hours doc opens near the {doc_title} window, which looks unusual next to peer baselines.",
        f"Post-meeting doc log note: {tn} had off-hours repository touches around {doc_title}; security should check recent_documents closely.",
    )
    return _build_event(
        ctx,
        "false_positive_log_cascade",
        speaker,
        target,
        "#security-review",
        rng.choice(subjects),
        rng.choice(bodies),
        doc_title,
    )
```

---

### Proposal P2.2: Public Department Sprint-Deadline Bursts (Opt-In `canary/rules.py` / `canary/env.py` / `canary/solver/belief.py`)

#### Research & Architectural Justification
Sommer & Paxson (2010), Senator et al. (2013), and Glasser & Lindauer (2013) emphasize that real enterprise access logs are **non-stationary and bursty**: scheduled product releases, legal filings, and quarter-end closes cause entire departments to open documents heavily after hours. In stationary `v1.4`, every innocent shares a constant `1.0 * 0.10 = 0.10/d` genuine `after_hours` rate, allowing even an unconditioned `argmax(after_hours)` tally over a narrowed consistent set to coincide with the mole `7 / 9` times in `gemini-4-carbon`'s un-isolated `v1.4` accusations.

Proposal **P2.2** introduces **opt-in, 100% public department sprint-deadline bursts** (`sprint_bursts: bool = False`):
1. **Preserves `v1.4` Frozen Hash (`a8f99c2537c91d72`) When Disabled:** When `sprint_bursts = False` (default on all frozen `v1.2`/`v1.3`/`v1.4` tiers), zero `TierParams` dictionary keys, zero RNG draws on `self._dyn`, and zero instruction lines change, keeping `a8f99c2537c91d72` byte-identical.
2. **Public Release Calendar (`I(SprintSchedule; Mole) = 0`):** When `sprint_bursts = True` (calibrated defaults: `sprint_period_days = 3`, i.e., `d in {2, 5, 8, 11, 14, 17, 20}`, `sprint_log_multiplier = 2.0`, `sprint_after_hours_benign = 0.45`, `sprint_after_hours_mole = 0.55`), a deterministic public PRNG keyed solely by `f"sprint:{world.company}:{seed}"` assigns one of the `5` departments (`8` employees on `hard`) as `sprint_dept(d)` on scheduled release days, disclosed publicly in `Env.instruction()`, `status` (`sprint_schedule`), and `PublicDayFacts.extra["sprint_dept"]`.
3. **Exact Mathematical Model & `SolverPolicy` Conditioning:**
   For employee $e$ on closed day $d$, let $S(e, d) = \mathbb{I}[\text{dept}(e) = \text{sprint\_dept}(d)] \in \{0, 1\}$. Document opens follow $\text{Poisson}(\lambda_{e,d})$ with after-hours probability $p_{e,d}^{\text{ah}}$:
   $$\lambda_{e,d} = \lambda_{\text{base}}(e) \cdot 2.0^{S(e,d)}, \qquad p_{e,d}^{\text{ah}} = \begin{cases} 0.45 & \text{if } e \neq \text{mole},\; S(e,d)=1 \\ 0.55 & \text{if } e = \text{mole},\; S(e,d)=1 \\ p_{\text{ah,base}}(e) & \text{if } S(e,d)=0 \end{cases}$$
   On a sprint day on `hard`, each of the `8` sprint-department staff averages $2.0 \times 0.45 = 0.9000$ benign `after_hours` opens, lifting company-wide `after_hours` volume from `6.200/d` to **`12.600/d`** (verified across `1,400` simulated sprint days on `seeds 0-199`: empirical **`12.594/d`**) and driving sprint-day single-event `PPV` down to **`3.65%`** analytical (**`3.47%`** empirical; **`2.38%`** on the `80%` of sprint days when the mole sits outside `sprint_dept(d)`).
4. **Verified Simulation Across `200` `hard` Worlds (`seeds 0-199`):**

| Metric (`hard`, `seeds 0-199`, Oracle Decoy Dropped) | Stationary `v1.4` | `P2.2` Raw `argmax(after_hours)` (Flat Heuristic) | `P2.2` Sprint-Conditioned `behaviour_logliks` (`SolverPolicy`) |
|---|---:|---:|---:|
| Top-1 log accuracy at `T = 5` days | `11.0%` | **`8.0%`** | `15.5%` |
| Top-1 log accuracy at `T = 9` days | `25.0%` | **`17.0%`** | `23.5%` |
| Top-1 log accuracy at `T = 14` days | `31.5%` | **`24.0%`** | `35.0%` |
| Top-1 log accuracy at `T = 21` days | `44.0%` | **`30.5%`** (score `-0.588`) | **`47.0%`** |
| Mean log-odds on innocent in 2-sprint dept (`T = 21`) | `-1.5120` nats | **`-0.6646` nats (`35.0%` false `LLR > 0`!)** | **`-1.8494` nats (`14.4%` `LLR > 0`)** |

- **Why `P2.2` widens the frontier gap cleanly:** Across `21` days with `7` scheduled sprints across `5` departments, two departments experience `2` release sprints while three experience `1`. An uncalibrated agent or flat heuristic summing raw `after_hours` counts suffers **`+1.1848` nats** of upward false log-odds drift on every innocent in a 2-sprint department (`35.0%` net positive false incrimination!) and sees raw `argmax(after_hours)` accuracy fall from `44.0%` to **`30.5%`**. By contrast, `SolverPolicy` (`canary/solver/belief.py:behaviour_logliks`) conditions per-(employee, day) Poisson means on the public `sprint_schedule` in `O(N * T)` time, completely immunizing its posterior while relying on 3-variant `plant_canary` traps (`0.86544` nats/leak) to maintain `>= 85%` catchability.
- **Synergy with Constrained `MoleStrategy` (`canary/mole/dsl.py`):** Pairing `P2.1`/`P2.2` with catchability-constrained mole rules remain fully compatible with the `MoleStrategy` JSON schema:

```json
{
  "name": "sprint_shadow_careful_v15",
  "rules": [
    {
      "when": [
        {"field": "recent_low_recipient_docs", "op": ">=", "value": 2},
        {"field": "max_recipient_count", "op": ">=", "value": 12}
      ],
      "then": {"leak": "most_recipients", "frame": "random_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "none"}
}
```

---

## 5. Summary Reference Matrix

| Study | Venue & Year | Live HTTP-200 Verified Links | Core Finding | Canary `v1.4` / `v1.6` Grounding |
|---|---|---|---|---|
| Axelsson | *ACM TISSEC* (2000) | https://openalex.org/W2156204309 \| https://doi.org/10.1145/357830.357849 | Base-rate fallacy bounds IDS posterior `P(Intrusion \| Alarm)` via false-alarm dilution | `v1.4` hard `6.2000` `after_hours`/d (`0.3000` mole) -> `PPV = 4.84%` (`5.88%` excl. decoy) |
| Kahneman & Tversky | *Psych. Rev.* (1973) | https://openalex.org/W1980054641 \| https://doi.org/10.1037/h0034747 | Representativeness causes base-rate neglect and overconfidence on extreme outliers | Explains Codex `medium` `seeds 0, 4` & Gemini `hard` `9/9` un-isolated `argmax(ah)` picks |
| Sommer & Paxson | *IEEE S&P* (2010) | https://openalex.org/W1985987493 \| https://doi.org/10.1109/SP.2010.25 | Open-world benign diversity, asymmetric error cost, semantic gap, adversarial evasion | Grounds `wrong_accusation_score = -1.0`, `framing = True`, and **P2.2** sprint bursts |
| Greitzer et al. | *IEEE HICSS* (2012) | https://openalex.org/W2032091884 \| https://doi.org/10.1109/HICSS.2012.309 | Disgruntlement/stress are psychosocial risk precursors, not standalone proof of crime | Grounds innocent `decoy = True` (`1.1000` `after_hours`/d + compensation complaints) |
| Glasser & Lindauer | *IEEE SPW* (2013) | https://openalex.org/W1991210879 \| https://doi.org/10.1109/SPW.2013.37 | Pragmatic synthetic organizational + insider-threat world generation (CERT) | Methodological foundation of `canary/world.py` + salted interactive `canary/env.py` |
| Senator et al. | *ACM KDD* (2013) | https://openalex.org/W1995976200 \| https://doi.org/10.1145/2487575.2488213 | `5.5M` actions/day across `5,500` users require peer-group and temporal baselines | Grounds **P2.2** `(dept, sprint_day)` conditioning in `SolverPolicy` vs flat counts |
| Nurse et al. | *IEEE SPW* (2014) | https://openalex.org/W1969795119 \| https://doi.org/10.1109/SPW.2014.38 | Separates human/attitudinal indicators from technical capability and opportunity | Contrasts noisy `interview` / `logs` cues with `recipients` + `plant_canary` watermarks |
| Legg et al. | *IEEE Syst. J.* (2017) | https://openalex.org/W1458873377 \| https://doi.org/10.1109/JSYST.2015.2438442 | Authorized insiders match normal access volume; peer variance needs analyst verification | Matches `log_rate_mole = log_rate_benign = 1.0` on `hard` and grounds **P2.1** peer lure |
| Greitzer et al. | *Procedia CS* (2019) | https://openalex.org/W2956577829 \| https://doi.org/10.1016/j.procs.2019.05.090 | SOFIT ontology (`> 300` technical, behavioral, organizational threat indicators) | Connects technical log noise (`P2.2`) with organizational/social cascades (`P2.1`) |
| Homoliak et al. | *ACM CSUR* (2019) | https://openalex.org/W4288083473 \| https://doi.org/10.1145/3303771 | 5W1H insider taxonomy contrasting passive host monitoring with active decoy traps | Grounds `0.86544`-nat `plant_canary` honey-docs dominating `0.10990`-nat/d passive logs |
