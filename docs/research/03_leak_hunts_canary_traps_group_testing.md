# 03. Leak Hunts, Canary Traps, Digital Fingerprinting, and Adaptive Group Testing: Research Grounding for Canary

**Squad:** `research` (`canary-research-w1`)  
**Baseline commit:** `4d93ab2e` (synced with `origin/justSilas@58716742`, rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Scope:** Information-theoretic, cryptographic traitor-tracing, adaptive noisy group-testing, and defensive honey-document foundations for Canary's `plant_canary` tool, `max_variants = 3` anti-triviality bound, `fingerprint_accuracy = 0.95` noisy attribution channel, `careful_mole = True` deterrent weighting (`docs/DIFFICULTY.md` W1), experimental `justSilas-expert` post-mortem, and concrete `v1.5`/`v1.6` proposals (**P3.1**, **P3.2**) for Silas (`canary/social/biases.py`, `canary/rules.py`, `canary/env.py`, `canary/solver/`, and `train/`).  
**Companion Synthesis & Monographs:** [Master Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [06. Organisational Bias & Sleeper Port](06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Mole RL](08_mole_rl_stackelberg_and_catchability.md)

---

## 1. Executive Thesis: Canary as Noisy Pipelined Ternary Group Testing Under Deterrence

In corporate, intelligence, and cybersecurity leak investigations, passive behavioral monitoring and uncorroborated interviews fail under the low base rate of insider betrayal (`1` mole among `N = 40` staff on Canary `v1.4` hard). Across eight decades of statistical group testing, cryptographic fingerprinting, sequential feedback coding, and defensive honey-document research, accurate leak attribution rests on one active mathematical mechanism: **distributing watermarked document variants (`plant_canary`) that partition the suspect set into balanced, orthogonal equivalence classes across consecutive rounds until posterior mass crosses a calibrated Bayes-optimal stopping boundary.**

Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `canaries_per_day = 2`, `max_variants = 3`, `fingerprint_accuracy = 0.95`, `careful_mole = True`, `p_leak = 0.65`, `delay_choices = (2, 3)`) is a faithful finite-horizon realization of **noisy, delayed, deterrence-weighted adaptive `q`-ary group testing**:

1. **Two-orders-of-magnitude channel dominance (`181.4x` passive `interview`).** Once the vocal innocent `decoy` is identified from public messages, prior uncertainty over the mole is $H(\text{Mole}) = \ln(39) = 3.66356$ nats (`5.2854` bits). Conditional on leaking, a balanced 3-variant `plant_canary` trap (`max_variants = 3`, `fingerprint_accuracy = 0.95`, flip probability `0.025` per non-matching label) achieves exact symmetric channel capacity $I(Y; V) = \ln 3 + 0.95 \ln 0.95 + 2(0.025) \ln 0.025 = \mathbf{0.86544\text{ nats}}$ (`1.2486` bits) - **181.4x** the Kullback-Leibler divergence of a `v1.4` hard `interview` (`0.00477` nats at `interview_lr = 1.2`, `p_evasive_innocent = 0.2`), delivering a `+3.6376`-nat log-likelihood shift (`\ln(0.95 / 0.025) = \ln 38`) toward holders of the surfaced variant. By the group-testing rate theorem (Aldridge, Johnson & Scarlett, 2019; Tardos, 2008), isolating `1` mole among `39` non-decoy suspects requires at least $3.66356 / 0.86544 = \mathbf{4.233}$ leaked 3-way traps in expectation when relying on canaries alone (`~2-3` leaked traps once 2-department regular leaks narrow the prior to `8-16` co-recipients).
2. **Interior deterrent optimum under `careful_mole` (`k* = N/2 = 20`) and W1 trajectory reconciliation.** Boneh & Shaw (1998) observe that fingerprinting serves both to *trace* leaks and to *deter* release when traitors suspect a trap. Canary operationalizes this deterrent tradeoff via `careful_mole = True` (`weight = 1 - k / N` for a `k`-recipient canary vs `1.0` for regular 2-department memos). On Day 1 (`39` non-decoy suspects, `N = 40`), the unconditional canary leak weight $W(k) = (k / 39)(1 - k / 40)$ is strictly concave and uniquely maximized at **$k^* = N / 2 = 20$ recipients** (`W(20) = 0.2564`), yielding **3.6x** the trap hit weight of a narrow 3-person trap (`W(3) = 0.0712`) and **10.3x** a 39-person broadcast trap (`W(39) = 0.0250`). Replaying the `30` post-hoc locked paired dev seeds `0-29` (`scripts/careful_mole_check.py`, [`docs/DIFFICULTY.md`](../DIFFICULTY.md) W1) proves that `gemini-4-carbon`'s loss (`0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119`, **65% [24%, 98%]** raw, **72% [52%, 91%]** luck-adjusted; raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`) does **not** stem from misunderstanding `careful_mole`: Gemini sized its canaries almost identically to `SolverPolicy` (mean roster share `0.26` vs `0.24`, mean careful weight `0.74` vs `0.76`, `0/30` transcripts attributing missing leaks to mole avoidance). Instead, Gemini planted only **`254` canaries (`8.5/ep`)** vs `SolverPolicy`'s **`424` (`14.1/ep`)**, burning all `8` daily actions on `242` of `303` under-planted days (`68.0` interviews/ep), planting **`0.0%` (`0/254`)** singleton/tiny (`<= 3` recipient) Burnashev confirmation traps vs `SolverPolicy`'s **`11.8%` (`50/424`)**, and committing on un-isolated suspect sets (`>= 2` consistent) in **`9/29`** accusations (`3.39 V` expected loss, including unseparated variant pairs on seeds `15` and `18` alongside `5%` fingerprint flips on seeds `1` and `26`).
3. **Why `justSilas-expert` (`fingerprint_accuracy = 0.70`) compressed solver headroom instead of widening the frontier gap.** Lowering `fingerprint_accuracy` to `0.70` on experimental `justSilas-expert` (`29ca3bc5`, `n = 13` OpenCode episodes) collapses 3-way canary capacity by **3.09x** (`0.86544 -> 0.27980` nats/leak), raising the pure canary lower bound from `4.233` to **`13.093` leaked traps** (`> 21 * 0.65` in finite-horizon expectation under regular-doc competition) and cutting Burnashev pairwise confirmation divergence from `3.36477` to `0.84724` nats. While deterministic intersection heuristics collapsed (`grok_tactics`: `0.36 -> 0.01`), `SolverPolicy` also suffered finite-horizon noise errors (`2` `-1.0` flips in `13` seeds, `0.296` raw / `0.441` luck-adjusted), leaving `gemini-4-carbon` at **`84% [52%, 128%]` luck-adjusted** (`0.373` vs `0.441`, `13/13` correct) and validating the CEO's decision to drop `expert` at the 01:40 gate ([`docs/SUBMISSION.md`](../SUBMISSION.md)).

Section 2 grounds ten foundational papers with live HTTP-200 verified links and verbatim quotes. Section 3 derives exact `v1.4` hard channel capacities, recipient-sizing optima, and trajectory diagnostics. Section 4 delivers two concrete, zero-leakage / opt-in proposals: **P3.1 (`gen_canary_fatigue_deterrent` in `canary/social/biases.py`)** and **P3.2 (Boneh-Shaw `collusion_scrub_prob` opt-in rule + `FrugalHorsteinTeacher` `O(N log N)` ternary quantile splitter for `train/` DAgger)**.

---

## 2. Primary Literature Grounding (Live HTTP-200 Citations and Verbatim Quotes)

### 2.1 Collusion-Secure Digital Fingerprinting and Deterrence: Boneh & Shaw (1998)

- **Citation:** Boneh, D., & Shaw, J. (1998). Collusion-Secure Fingerprinting for Digital Data. *IEEE Transactions on Information Theory*, 44(5), 1897-1905.
- **Live Verified Links:** https://openalex.org/W2134195444 | DOI: https://doi.org/10.1109/18.705568
- **Theoretical Contribution:** Introduces $c$-frameproof and $\epsilon$-collusion-secure fingerprinting codes ($O(c^4 \log(N/\epsilon) \log(1/\epsilon))$ length under the Marking Assumption) for uniquely watermarking digital documents so unauthorized redistributions trace back to the traitor while deterring rational insiders.
- **Verbatim Quote on Tracing and Deterrence (Abstract):**
> "This paper discusses methods for assigning code-words for the purpose of fingerprinting digital data, e.g., software, documents, music, and video. Fingerprinting consists of uniquely marking and registering each copy of the data. This marking allows a distributor to detect any unauthorized copy and trace it back to the user. This threat of detection will deter users from releasing unauthorized copies."
- **Verbatim Quote on Multi-Copy Collusion and Fingerprint Scrubbing (Abstract):**
> "A problem arises when users collude: for digital data, two different fingerprinted objects can be compared and the differences between them detected. Hence, a set of users can collude to detect the location of the fingerprint. They can then alter the fingerprint to mask their identities."
- **Relevance to Canary:** Directly grounds three core mechanics of Canary (`canary/rules.py`, `canary/env.py`):
  1. **`max_variants = 3` anti-triviality constraint:** Boneh & Shaw note that Naive 1-of-$N$ unique watermarking (`40` distinct copies on Day 1) trivially solves attribution in one leak if undetectable; capping `max_variants = 3` forces multi-round combinatorial coding (`\lceil \log_3 39 \rceil = 4` noiseless rounds).
  2. **`careful_mole = True` deterrence (`weight = 1 - k / N`):** Formalizes Boneh & Shaw's statement that *"this threat of detection will deter users from releasing unauthorized copies"* when widely circulated variants look anomalous.
  3. **`fingerprint_accuracy = 0.95` & Proposal P3.2a (`collusion_scrub_prob`):** Models imperfect watermark survival when a leaked document is paraphrased or diffed across multiple same-day watermarked copies (`c{d}` and `c{d}-2`).

### 2.2 Cryptographic Traitor Tracing Over Shared Broadcasts: Chor, Fiat, Naor & Pinkas (2000)

- **Citation:** Chor, B., Fiat, A., Naor, M., & Pinkas, B. (2000). Tracing Traitors. *IEEE Transactions on Information Theory*, 46(3), 893-910.
- **Live Verified Links:** https://openalex.org/W2295616646 | DOI: https://doi.org/10.1109/18.841169
- **Theoretical Contribution:** Establishes probabilistic $k$-resilient traitor-tracing schemes (both fully resilient and threshold decoders) when proprietary content or keys must be distributed simultaneously to large authorized user subsets.
- **Verbatim Quote (Abstract):**
> "We give cryptographic schemes that help trace the source of leaks when sensitive or proprietary data is made available to a large set of parties."
- **Verbatim Quote on Threshold vs Resilient Tracing (Abstract):**
> "We describe fully resilient schemes which can be used against any decoder which decrypts with nonnegligible probability. Since there is typically little demand for decoders which decrypt only a small fraction of the transmissions (even if it is nonnegligible), we further introduce threshold tracing schemes which can only be used against decoders which succeed in decryption with probability greater than some threshold."
- **Relevance to Canary:** In Canary `v1.4` hard, regular operational documents (`docs_per_day = (2, 3, 4)`, `p_single_dept_recipients = 0.0`) must be shared across `2` of `5` departments (`16` authorized employees per document). Chor et al.'s framework explains why passive intersection over shared `16`-holder broadcasts plateaus once multiple suspects co-inhabit the same department (`8` colleagues share identical departmental distributions unless separated by targeted sub-department `plant_canary` codewords), and why Canary enforces a **catchability threshold** (`SolverPolicy` accuracy `>= 85%`, `p_leak = 0.65`) analogous to Chor et al.'s threshold tracing regime.

### 2.3 Optimal Probabilistic Fingerprint Code Length Bounds: Tardos (2008)

- **Citation:** Tardos, G. (2008). Optimal Probabilistic Fingerprint Codes. *Journal of the ACM*, 55(2), Article 10, 1-24.
- **Live Verified Links:** https://openalex.org/W2031722321 | DOI: https://doi.org/10.1145/1346330.1346335
- **Theoretical Contribution:** Constructs randomized fingerprint codes of optimal length $O(c^2 \log(N/\epsilon))$ using an arcsine prior on bias weights and log-likelihood accusation scoring, proving matching information-theoretic converse lower bounds up to constant factors.
- **Verbatim Quote on Matching Converse Lower Bounds (Abstract):**
> "By proving matching lower bounds we establish that the length of our codes is best within a constant factor for reasonable error probabilities."
- **Verbatim Quote on Alphabet Power and Randomized Codewords (Abstract):**
> "Our results also imply that randomized fingerprint codes over a binary alphabet are as powerful as over an arbitrary alphabet and the equal strength of two distinct models for fingerprinting."
- **Relevance to Canary:** Tardos (2008) proves two foundational truths mirrored in Canary's `v1.4` hard benchmark:
  1. **Logarithmic sample-complexity floor in $N$ and $1/\epsilon$:** Accusing with false-accusation risk $\epsilon \le 1 - P^* = V / (1 + V)$ (`wrong_accusation_score = -1.0`) over $N - 1 = 39$ suspects imposes an inescapable information-theoretic lower bound on total accumulated log-likelihood evidence. When `gemini-4-carbon` plants only `8.5` canaries (`55` total canary leaks across `30` episodes = `1.83` canary leaks/episode), it operates strictly below the Tardos code-length threshold on `9/29` accusations.
  2. **Sum-of-log-likelihood decoding (`canary/solver/belief.py`):** Just as Tardos replaces brittle combinatorial elimination with additive log-likelihood accusation scores, `SolverPolicy` (`leak_loglik` lines `96-110`) weights matched vs flipped variants by $\ln(0.95) - \ln(0.025) = +3.6376$ nats instead of discarding a suspect forever on a single `5%` flip (avoiding hard elimination crashes on `medium` vs `hard` in [`docs/reports/failure_analysis_v1.4.md`](../reports/failure_analysis_v1.4.md) Section 8).

### 2.4 Information-Theoretic Rate of Adaptive Group Testing: Aldridge, Johnson & Scarlett (2019)

- **Citation:** Aldridge, M., Johnson, O., & Scarlett, J. (2019). Group Testing: An Information Theory Perspective. *Foundations and Trends in Communications and Information Theory*, 15(3-4), 196-392.
- **Live Verified Links:** https://openalex.org/W2912457157 | DOI: https://doi.org/10.1561/0100000099
- **Theoretical Contribution:** Unifies noiseless and noisy adaptive and non-adaptive group testing via mutual information per test (**group-testing rate**), proving exact capacity bounds $T \ge \frac{\log_2 \binom{N}{K}}{C_{\text{chan}}}(1 - o(1))$ under symmetric and asymmetric test noise.
- **Verbatim Quote on Pooled Defective Discovery (Abstract):**
> "The group testing problem concerns discovering a small number of defective items within a large population by performing tests on pools of items. A test is positive if the pool contains at least one defective, and negative if it contains no defectives."
- **Verbatim Quote on Exact Constant-Factor Rate per Test (Abstract):**
> "We assess the theoretical guarantees not only in terms of scaling laws, but also in terms of the constant factors, leading to the notion of the rate of group testing, indicating the amount of information learned per test."
- **Relevance to Canary:** Provides the exact constant-factor information-rate metric for `SolverPolicy.canary_mi` and `SolverPolicy.joint_mi` (`canary/solver/policy.py`, lines `463-485` and `556-590`). In Canary (`K = 1` defective mole among `39` non-decoy staff), every `plant_canary` assignment defines a pooled multi-level test whose single-plant rate is $I(\text{Mole}; \text{Outcome}_{1:\text{win}})$ in nats, accounting simultaneously for `p_leak = 0.65`, `careful_mole` pool-size damping, regular-document competition, and `fingerprint_accuracy = 0.95` channel noise.

### 2.5 Pooled Screening vs Individual Inspection: Dorfman (1943)

- **Citation:** Dorfman, R. (1943). The Detection of Defective Members of Large Populations. *The Annals of Mathematical Statistics*, 14(4), 436-440.
- **Live Verified Links:** https://openalex.org/W1975680434 | DOI: https://doi.org/10.1214/aoms/1177731363
- **Theoretical Contribution:** Founding paper of group testing; proves that pooling $g$ individuals into a composite assay and re-testing only positive pools reduces expected test count from $N$ individual inspections to $N \left(\frac{1}{g} + 1 - (1 - p)^g\right) \approx 2 N \sqrt{p}$ for prevalence $p = 1/N$.
- **Verbatim Quote (p. 436):**
> "Where the objective is to weed out individual defective units, a sample inspection will clearly not suffice. It will be shown in this paper that a different statistical approach can, under certain conditions, yield significant savings in effort and expense when a complete elimination of defective units is desired."
- **Relevance to Canary:** Captures the fundamental strategic blunder of `gemini-4-carbon` on `v1.4` hard: faced with `40` employees and an `8`-action/day budget, `gemini-4-carbon` defaults to **individual 1-by-1 inspection** (`68.0` one-on-one `interview` calls per episode at `0.00477` nats each), whereas Dorfman's pooled-testing principle (`plant_canary` testing `10-20` employees simultaneously across `3` variants in `1` action) achieves an order-of-magnitude reduction in time-to-isolation (`day 10.6` vs `13.4`).

### 2.6 Generalized Binary and `q`-ary Splitting: Hwang (1972)

- **Citation:** Hwang, F. K. (1972). A Method for Detecting All Defective Members in a Population by Group Testing. *Journal of the American Statistical Association*, 67(339), 605-608.
- **Live Verified Links:** https://openalex.org/W1968199120 | DOI: https://doi.org/10.1080/01621459.1972.10481257
- **Theoretical Contribution:** Introduces Generalized Binary Splitting (GBS), choosing initial pool size $2^\alpha$ matched to expected defective density $K/N$ and halving positive pools down to singletons within $< 1$ test of the information-theoretic entropy bound $\log_2 \binom{N}{K}$.
- **Verbatim Quote (Abstract):**
> "Suppose a population containing items classified either as defectives or as non-defectives. This article presents a new group testing method to detect all defectives in the population. The proposed method applies either when the actual number of defectives (or an upper bound) is known or when its probability distribution is known. The method is surprisingly simple yet compares favorably with other existing methods by the number of tests required to detect all defectives."
- **Relevance to Canary:** Generalizes directly to Canary's **ternary + unlabelled complement (`3 + 1 = 4`-way)** adaptive splitting (`SolverPolicy.partition_balanced`, lines `636-654`): when `none_group = True` and `|alive| > 3`, `SolverPolicy` partitions suspects into `max_variants + 1 = 4` posterior-balanced groups and leaves the largest-headcount group unlabelled (`weight = 1 - len(asg)/N` boost under `careful_mole`), then splits positive cells down to `1`-person singletons once `|alive| <= 3`.

### 2.7 Posterior-Quantile Probabilistic Bisection: Horstein (1963) & Waeber, Frazier & Henderson (2013)

- **Citation 1 (Foundational Algorithm):** Horstein, M. (1963). Sequential Transmission Using Noiseless Feedback. *IEEE Transactions on Information Theory*, 9(3), 136-143. Live Verified Links: https://openalex.org/W2040877654 | DOI: https://doi.org/10.1109/TIT.1963.1057832
- **Citation 2 (Geometric Convergence Proof):** Waeber, R., Frazier, P. I., & Henderson, S. G. (2013). Bisection Search with Noisy Responses. *SIAM Journal on Control and Optimization*, 51(3), 2261-2279. Live Verified Links: https://openalex.org/W2094365833 | DOI: https://doi.org/10.1137/120861898
- **Verbatim Quote from Horstein (1963) (Abstract):**
> "A sequential continuous-transmission system employing a binary symmetric forward channel (but which is suitable for use with any discrete memoryless forward channel) and a noiseless feedback channel is described. Its error exponent is shown to be substantially greater than the optimum block-code error exponent at all transmission rates less than channel capacity."
- **Verbatim Quote from Waeber, Frazier & Henderson (2013) (Abstract):**
> "Bisection search is the most efficient algorithm for locating a unique point"
> "While the method works extremely well in practice, very little is known about its theoretical properties. In this paper, we provide several key findings about the PBA, which lead to the main conclusion that the expected absolute residuals of successive search results, i.e., $\mathbb{E}[|X^{\ast} - X_n|]$, converge to 0 at a geometric rate."
- **Relevance to Canary:** When canary responses are corrupted by `5%` label flips (`fingerprint_accuracy = 0.95`) and non-uniform regular-leak/access-log posteriors, naive unweighted set-halving (`W2b008Elimination`, [`docs/EXPLOITS.md`](../EXPLOITS.md) #50) permanently deletes the true mole on a single flip (`3` wrong accusations on `40` hard judge seeds, `+0.363` vs solver `+0.545`). Horstein's probabilistic bisection instead partitions the **current Bayesian posterior distribution** into equal-mass quantiles (`1/3, 1/3, 1/3` across variants `A, B, C`) and updates soft posteriors via Bayes' rule after each noisy feedback observation - the exact mathematical principle behind `SolverPolicy` and our fast `O(N log N)` **P3.2b** DAgger teacher.

### 2.8 Two-Phase Exploration-and-Confirmation Stopping: Burnashev (1976), Berlin et al. (2009) & Naghshvar & Javidi (2013)

- **Citation 1 (Burnashev Reliability Function & Converse):** Berlin, P., Nakiboglu, B., Rimoldi, B., & Telatar, E. (2009). A Simple Converse of Burnashev's Reliability Function [establishing the two-phase converse of Burnashev, M. V. (1976), *Probl. Peredachi Inf.*, 12(4), 10-30]. *IEEE Transactions on Information Theory*, 55(7), 3074-3080. Live Verified Links: https://openalex.org/W2162614205 | DOI: https://doi.org/10.1109/TIT.2009.2021322
- **Citation 2 (Active Sequential Hypothesis Testing):** Naghshvar, M., & Javidi, T. (2013). Active Sequential Hypothesis Testing. *The Annals of Statistics*, 41(6), 2703-2738. Live Verified Links: https://openalex.org/W1990503235 | DOI: https://doi.org/10.1214/13-AOS1144
- **Verbatim Quote from Berlin et al. (2009) on Burnashev (1976) (Abstract):**
> "In a remarkable paper published in 1976, Burnashev determined the reliability function of variable-length block codes over discrete memoryless channels (DMCs) with feedback."
> "Besides being simpler than the original, the proposed converse suggests that a communication and a confirmation phase are implicit in any scheme for which the probability of error decreases with the largest possible exponent."
- **Verbatim Quote from Naghshvar & Javidi (2013) (Abstract):**
> "Consider a decision maker who is responsible to dynamically collect observations so as to enhance his information about an underlying phenomena of interest in a speedy manner while accounting for the penalty of wrong declaration. Due to the sequential nature of the problem, the decision maker relies on his current information state to adaptively select the most \"informative\" sensing action among the available ones."
- **Relevance to Canary:** Burnashev (1976) and Naghshvar & Javidi (2013) prove that optimal sequential identification under a severe wrong-declaration penalty (`wrong_accusation_score = -1.0` vs daily leak bleed `0.05 V`) **cannot** rely solely on uniform broad bisection up to stopping; once a leading candidate emerges ($p_{\max}(t) \ge 0.5$), the optimal active policy switches from a **communication/narrowing phase** (maximizing mutual information rate $C$) to a **confirmation phase** (maximizing pairwise Kullback-Leibler divergence $C_1 = D(P_{\text{mole}} \| P_{\text{inn}})$ via `1-2` suspect singleton traps). In `canary/solver/policy.py` (lines `424-431`), `self.tiny = True` implements this exact Burnashev confirmation phase (`50/424 = 11.8%` of `SolverPolicy` canaries have `<= 3` recipients), whereas `gemini-4-carbon` planted **`0/254` (`0.0%`)** `<= 3`-recipient confirmation traps on `v1.4` hard!

### 2.9 Baiting Insiders with Believable Decoy Documents: Bowen, Hershkop, Keromytis & Stolfo (2009)

- **Citation:** Bowen, B. M., Hershkop, S., Keromytis, A. D., & Stolfo, S. J. (2009). Baiting Inside Attackers Using Decoy Documents. In *Security and Privacy in Communication Networks (SecureComm 2009)*, LNICST, Vol. 19, pp. 51-70.
- **Live Verified Links:** https://openalex.org/W1536598138 | DOI: https://doi.org/10.1007/978-3-642-05284-2_4
- **System & Design:** Introduces the Decoy Document Distributor (`D3`) platform for insider-exfiltration detection and formalizes six canonical decoy-document properties (*believability*, *enticingness*, *conspicuousness*, *detectability*, *variability*, and *non-interference*).
- **Verbatim Quote on Trap-Based Insider Defense (Abstract):**
> "In this work we propose trap-based defense mechanisms and a deployment platform for addressing the problem of insiders attempting to exfiltrate and use sensitive information. The goal is to confuse and confound an adversary requiring more effort to identify real information from bogus information and provide a means of detecting when an attempt to exploit sensitive information has occurred."
- **Verbatim Quote on Formal Decoy Design Properties (Abstract):**
> "We introduce and formalize a number of properties of decoys as a guide to design trap-based defenses to increase the likelihood of detecting an insider attack."
- **Relevance to Canary:** Every one of Bowen et al.'s (2009) formal decoy properties maps directly onto an explicit field of Canary (`canary/env.py`, `canary/mole/dsl.py`):
  - *Believability / Indistinguishability:* `MoleDoc(doc_id, title, n_recipients, age_days)` in `MoleView` omits `is_canary`, so no `MoleStrategy` rule can distinguish a canary from a regular memo except via structural cues (`n_recipients`).
  - *Conspicuousness vs Suspicion (`careful_mole`):* Over-circulating a canary (`k -> 40`) lowers `weight = 1 - k/40 -> 0`, while narrow `<= 3`-recipient micro-traps trigger `recent_low_recipient_docs` in `hard_forge` / `hard_rl`.
  - *Detectability & Variability:* `check_leak_feed` surfaces leaked `doc_id` and `variant` (`max_variants = 3`, `fingerprint_accuracy = 0.95`).
  - *Non-interference:* `canary_cost = 0.01` models operational clutter/compliance friction when planting watermarked decoys across active workflows (directly grounding Proposal **P3.1**).

### 2.10 Game-Theoretic Taxonomy of Honey-X Signaling: Pawlick, Colbert & Zhu (2019)

- **Citation:** Pawlick, J., Colbert, E., & Zhu, Q. (2019). A Game-Theoretic Taxonomy and Survey of Defensive Deception for Cybersecurity and Privacy. *ACM Computing Surveys*, 52(4), Article 82, 1-28.
- **Live Verified Links:** https://openalex.org/W2971648973 | DOI: https://doi.org/10.1145/3337772
- **Taxonomy & Survey:** Classifies 24 game-theoretic defensive-deception models (2008-2018) along private information, action observability, and horizon into six canonical mechanisms (*perturbation*, *moving target defense*, *obfuscation*, *mixing*, *honey-x*, and *attacker engagement*).
- **Verbatim Quote on Reversing Information Asymmetry (Abstract):**
> "Advocates and engineers have recently proposed using defensive deception as a means to leverage the information asymmetry typically enjoyed by attackers as a tool for defenders."
- **Verbatim Quote on Six-Mechanism Game-Theoretic Taxonomy (Abstract):**
> "Then, we propose a taxonomy that defines six types of deception: perturbation, moving target defense, obfuscation, mixing, honey-x, and attacker engagement. These types are delineated by their information structures, agents, actions, and duration: precisely concepts captured by game theory."
- **Relevance to Canary:** Places Canary's dual-deception architecture into exact game-theoretic duality: while the mole deploys *obfuscation/perturbation* (`framing = True` injecting `2.0` fake `after_hours` logs/day) and organizational chatter generates *cheap-talk noise*, `plant_canary` is a **dynamic multi-period honey-x signaling game** in which the defender holds private type information (`is_canary` and employee-to-variant mapping `variants`) to invert the attacker's hidden-identity advantage.

---

## 3. Exact Quantitative Derivations for Canary `v1.4` Hard (`a8f99c2537c91d72`)

All numbers in this section were computed and verified directly with `/tmp/fleet-silas/shared/agent-arena-venv/bin/python` against `canary/rules.py`, `canary/env.py`, `canary/solver/policy.py`, `scripts/careful_mole_check.py`, `results/failure_analysis_v1.4.json`, and `origin/justSilas-expert:results/expert_verdict.json` (`29ca3bc5`).

### 3.1 Prior Entropy, 3-Variant Symmetric Channel Capacity, and `justSilas-expert` Comparison

On `v1.4` hard (`n_employees = 40`, `decoy = True`, frozen hash `a8f99c2537c91d72`), `Env.instruction()` discloses that exactly one employee is an innocent disgruntled `decoy` (`SolverPolicy.decoy_queries()` identifies the decoy via `ANGER_WORDS` on Day 2) and the mole is uniformly distributed over the remaining $N - 1 = 39$ employees:

$$H(\text{Mole} \mid \text{decoy known}) = \ln(39) = \mathbf{3.66356\text{ nats}} \quad (\mathbf{5.2854\text{ bits}})$$

*(Before decoy identification on Day 1, $H(\text{Mole}) = \ln(40) = 3.68888$ nats $= 5.3219$ bits.)*

Suppose a `plant_canary` document with $m = \text{max\_variants} = 3$ posterior-balanced variant labels $V \in \{A, B, C\}$ (`P(V = v) = 1/3`) is leaked by a mole who received one of those variants. By `Env._t_advance_day` (`canary/env.py`, lines `565-573`), the surfaced feed label $Y \in \{A, B, C\}$ equals the mole's true variant $V$ with probability $\alpha = \text{fingerprint\_accuracy} = 0.95$, and flips uniformly to each of the other $m - 1 = 2$ planted labels with probability $\beta = \frac{1 - \alpha}{m - 1} = \frac{0.05}{2} = 0.025$:

$$I(Y; V) = H(Y) - H(Y \mid V) = \ln m + \alpha \ln \alpha + (m - 1)\beta \ln \beta$$

$$I_{\text{hard}}(Y; V) = \ln 3 + 0.95 \ln(0.95) + 2(0.025)\ln(0.025) = 1.09861 - 0.23317 = \mathbf{0.86544\text{ nats}} \quad (\mathbf{1.2486\text{ bits}})$$

Simultaneously, for any two employees $e_1 \in V_1$ (matched label) and $e_2 \in V_2 \neq V_1$ (non-matched label) who both held the leaked canary, the single-leak log-likelihood ratio and Burnashev pairwise confirmation divergence $D_{\text{KL}}(P_{Y \mid V_1} \| P_{Y \mid V_2})$ are:

$$\text{LLR}_{\text{match vs flip}} = \ln \frac{\alpha}{\beta} = \ln \frac{0.95}{0.025} = \ln(38) = \mathbf{+3.6376\text{ nats}}, \qquad D_{\text{KL}}(P_{Y \mid V_1} \| P_{Y \mid V_2}) = (\alpha - \beta) \ln \frac{\alpha}{\beta} = 0.925 \ln(38) = \mathbf{3.36477\text{ nats}}$$

Comparing across Canary's frozen tiers, passive `interview`, and the unshipped `justSilas-expert` experiment (`29ca3bc5`) reveals why `v1.4` hard sits at the exact sweet spot of meaningful Bayesian difficulty:

| Channel / Regime | Variants $m$ | Accuracy $\alpha$ (Flip $\beta$) | Conditional MI $I(Y; V)$ | Matched vs Flip LLR | Pairwise Confirmation $D_{\text{KL}}$ | Min Leaked Traps for $\ln(39)$ | Ratio vs `v1.4` Hard `interview` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | 2 (binary) | `0.200` inn / `0.300` mole | - | `+0.4055` / `-0.1335` | `0.02817` nats | `130.0` ivs | `5.9x` |
| `interview` (`medium`, `LR=1.3`) | 2 (binary) | `0.200` inn / `0.260` mole | - | `+0.2624` / `-0.0780` | `0.01052` nats | `348.2` ivs | `2.2x` |
| `interview` (`hard`, `LR=1.2`) | 2 (binary) | `0.200` inn / `0.240` mole | - | `+0.1823` / `-0.0513` | **`0.00477` nats** | `767.4` ivs | **`1.0x`** |
| `plant_canary` (`easy`/`medium`) | `3` | `1.000` (`0.000`) | `1.09861` nats (`1.5850` b) | `+\infty` (hard elim.) | `+\infty` | `3.335` leaks | `230.1x` |
| `plant_canary` (`v1.3` hard, $N=30$) | `2` | `0.950` (`0.050`) | `0.49463` nats (`0.7136` b) | `+2.9444` nats | `2.65000` nats | `6.808` ($\ln 29$) | `103.6x` |
| **`plant_canary` (`v1.4` hard, $N=40$)** | **`3`** | **`0.950` (`0.025`)** | **`0.86544` nats (`1.2486` b)** | **`+3.6376` nats** | **`3.36477` nats** | **`4.233` leaks** | **`181.4x`** (`0.86544 / 0.00477`) |
| `plant_canary` (`justSilas-expert`, $N=40$) | `3` | `0.700` (`0.150`) | **`0.27980` nats (`0.4037` b)** | `+1.5404` nats | **`0.84724` nats** | **`13.093` leaks** | `58.6x` (`3.09x` below `v1.4`) |

*(Note on rounding: exact `kl_hard = 0.0047743` nats gives `0.86544 / 0.0047743 = 181.27x`, and `0.86544 / 0.00477 = 181.43x` using the 5-decimal rounded `0.00477` nats table entry.)*

**Information-theoretic post-mortem of `justSilas-expert` (`fingerprint_accuracy = 0.70`, commit `29ca3bc5`):**  
In `origin/justSilas-expert:results/expert_verdict.json` (`n = 13` paired episodes on dev seeds `60001..60020`), reducing `fingerprint_accuracy` from `0.95` to `0.70` (`\beta = 0.15` per wrong label, `30%` total flip rate) produced two opposing effects:
1. Non-Bayesian elimination heuristics collapsed (`grok_tactics` dropped from `0.36` to `0.01`, [`docs/reports/gap.md`](../reports/gap.md)), because `30%` flip probability destroys strict subset intersection.
2. However, because `I(Y; V)` fell **3.09x** (`0.86544 -> 0.27980` nats) and the pure canary lower bound jumped to **`13.093` leaked traps** inside a 21-day horizon (`21 * 0.65 = 13.65` expected *total* leaks across both regular and canary documents!), `SolverPolicy` itself hit the finite-horizon Tardos converse wall: on those `13` seeds, `SolverPolicy` suffered `2` wrong `-1.0` accusations (`seeds 60001, 60010`) and `1` abstention (`seed 60013`), scoring `0.296` raw (`0.441` luck-adjusted), while OpenCode `gemini-4-carbon` went `13/13` correct (`0.531` raw, `0.373` luck-adjusted, yielding **`84% [52%, 128%]` luck-adjusted** of solver). Compressing channel capacity hurt the ceiling (`SolverPolicy`) more than the under-planting challenger, proving that **meaningful difficulty comes from decision-theoretic distractors and experimental-design traps at high channel capacity (`acc = 0.95`), not from starving the optimal decoder of Shannon capacity.**

---

### 3.2 Optimal Day 1 `careful_mole` Recipient-Pool Sizing (`k* = N/2 = 20`)

In `Env._mole_view` (`canary/env.py`, lines `537-538`), when `careful_mole = True`, an eligible regular document has selection weight `1.0` while a canary assigned to $k = |\text{assignment}|$ employees has selection weight:

$$w_{\text{careful}}(k) = 1 - \frac{k}{N} = 1 - \frac{k}{40}$$

Consider Day 1 (`39` non-decoy suspects with uniform prior $1/39$, `N = 40` total staff, decoy excluded from `assignment` once known or prior to Day 2). A canary of size $k \in \{1, \dots, 39\}$ covers the true mole with probability $P(\text{mole} \in C) = \frac{k}{39}$ and, conditional on the mole holding $C$, contributes selection weight $1 - \frac{k}{40}$ to the mole's random-pick numerator. The **unconditional canary leak weight** is therefore:

$$W(k) = \frac{k}{39}\left(1 - \frac{k}{40}\right) = \frac{40 k - k^2}{1560}$$

Treating $k$ continuously gives $\frac{dW}{dk} = \frac{40 - 2k}{1560} = 0 \implies \mathbf{k^* = \frac{N}{2} = 20}$, with $\frac{d^2 W}{dk^2} = -\frac{1}{780} < 0$ (strictly concave; over integers $k \in \{1, \dots, 39\}$, $k^* = 20$ is the **unique** global maximizer!). Moreover, when the mole also holds $R \ge 1$ leakable regular documents on Day 1 (on `hard`, each regular doc goes to `2/5` of departments, so with `docs_per_day ~ Uniform{2, 3, 4}`, expected held Day 1 regular docs is $3 \times 0.4 = 1.2$), the conditional probability that a Day 1 leak hits the canary is $P(\text{canary} \mid \text{leak}, R) = \frac{k}{39} \cdot \frac{1 - k/40}{R + (1 - k/40)}$, which peaks at $k = 21$ for $R \in \{1, 2\}$ (`0.1734` at $R = 1$, `0.1033` at $R = 2$):

| Canary Pool Size $k$ (of $39$ Suspects) | Roster Share $k / 40$ | Careful Weight $1 - k / 40$ | Mole Coverage $k / 39$ | Unconditional Weight $W(k)$ | Ratio $W(20) / W(k)$ | $P(\text{canary} \mid \text{leak}, R=1)$ | Strategic Regime |
|---:|---:|---:|---:|---:|---:|---:|---|
| `k = 1` (singleton) | `0.025` | `0.975` | `0.0256` | `0.0250` | `10.3x` worse | `0.0127` | Pure endgame confirmation (`\|C\| <= 3`) |
| **`k = 3` (narrow micro-trap)** | `0.075` | `0.925` | `0.0769` | **`0.0712`** | **`3.6x` worse** (`3.604x`) | `0.0370` | Under-covers uniform prior (endgame only) |
| `k = 10` (`~0.25` share, 1/2 of pair) | `0.250` | `0.750` | `0.2564` | `0.1923` | `1.3x` worse | `0.1099` | Disjoint 2-canary/day pipeline (`2 x 10 = 20`!) |
| **`k* = 20` (`N / 2` optimum)** | **`0.500`** | **`0.500`** | **`0.5128`** | **`0.2564`** | **`1.0x` (Global Max)** | **`0.1709`** | **Single-canary Day 1 maximum hit rate** |
| `k = 30` (3/4 roster) | `0.750` | `0.250` | `0.7692` | `0.1923` | `1.3x` worse | `0.1538` | Over-broad; triggers heavy `careful_mole` damping |
| **`k = 39` (all non-decoy staff)** | `0.975` | `0.025` | `1.0000` | **`0.0250`** | **`10.3x` worse** (`10.256x`) | `0.0244` | Near-zero leak weight (`careful_mole` deterrent) |
| `k = 40` (entire roster) | `1.000` | `0.000` | `1.0000` | `0.0000` | $\infty$ (`0` leaks) | `0.0000` | Provably never leaks under `careful_mole` |

Notice the crucial synergy with `canaries_per_day = 2` on `v1.4` hard: planting **two disjoint `10`-recipient canaries** on the same day (`2 x 10 = 20` distinct suspects covered, `mean share = 0.25`, `careful weight = 0.75` each) achieves combined unconditional canary weight $2 \times \frac{10}{39} \times 0.75 = \mathbf{0.3846}$ (`1.50x` higher than a single `20`-person canary!) while partitioning `20` suspects into `6` labelled cells (`3 + 3`) plus an unlabelled `19`-suspect complement! That mathematically explains why `SolverPolicy`'s empirical mean share across all `424` planted canaries on `v1.4` hard is **`0.24` (`9.9` recipients/canary, careful weight `0.76`)**.

---

### 3.3 Reconciling [`docs/DIFFICULTY.md`](../DIFFICULTY.md) W1 and `gemini-4-carbon`'s Experimental-Design Failures (`30` Post-Hoc Locked Dev Seeds `0-29`)

In [`docs/DIFFICULTY.md`](../DIFFICULTY.md) (Known Wording Issue W1), an early version of `Env.instruction()` stated both `"The mole never knows which documents are canaries"` (true of `MoleView` in `canary/mole/dsl.py`) and the `careful_mole` weight multiplier `1 - share` (applied by `Env._mole_view` to random-pick weights). Running `scripts/careful_mole_check.py` and auditing `results/failure_analysis_v1.4.json` across the **`30` post-hoc locked paired dev seeds `0-29`** (locked post-hoc from the dev seed pool, separate from the later `30-59` extension in `f9fb7a4a`) settles both W1 and the exact group-testing root causes of the `0.322 +/- 0.199` vs `0.499 +/- 0.119` gap:

| Trajectory & Group-Testing Metric (`30` Post-Hoc Locked Dev Seeds `0-29`) | OpenCode `gemini-4-carbon` | Reference `SolverPolicy` | Causal Group-Testing Reading |
|---|---:|---:|---|
| Mean Score (`95% CI`) | **`0.322 +/- 0.199`** | **`0.499 +/- 0.119`** | **`65% [24%, 98%]` raw** (paired gap `5.30 V`) |
| Luck-Adjusted Score (`Ratio [95% CI]`) | **`0.360`** | **`0.499`** | **`72% [52%, 91%]` luck-adjusted** (gap `4.19 V`) |
| Total Canaries Planted (`Mean / Ep`, `%` of `2/day` Cap) | **`254` (`8.5 / ep`, `31.5%`)** | **`424` (`14.1 / ep`, `66.7%`)** | Gemini under-plants by `40%`, starting on Day `3.0` vs `1.0` |
| Under-Planted Days (`< 2` Canaries) with Full `8/8` Actions Spent | **`242 / 303` (`79.9%`)** | **`0 / 182` (`0.0%`)** | `1,503` `interview` actions (`68.0/ep`) crowd out 2nd canary |
| Mean Roster Share per Canary (`Max Share`) / Mean Careful Weight | **`0.26` (`0.60`) / `0.74`** | **`0.24` (`0.55`) / `0.76`** | **W1 refuted:** Gemini sized pools identically to `SolverPolicy` |
| Observed Canary Leaks / Planted (`Expected Careful vs Uniform`) | `55 / 254 = 0.22` (`65.8 vs 76.7`, `86%`) | `64 / 424 = 0.15` (`70.5 vs 79.2`, `89%`) | Careful rule cost both agents `~11%-14%` of canary leaks |
| Burnashev Singleton/Tiny Confirmation Traps (`<= 3` Recipients) | **`0 / 254` (`0.0%`)** | **`50 / 424` (`11.8%`)** | Gemini **never** switches to `1`-per-label endgame confirmation |
| Mean Same-Day `c{d}` vs `c{d}-2` Jaccard Overlap (`2`-Canary Days) | **`0.550` (`100` days)** | **`0.234` (`136` days)** | Gemini reuses overlapping recipients `2.35x` more on same day |
| Accusations Made with Un-Isolated Suspects (`\|Consistent\| >= 2`) | **`9 / 29` (`31.0%`, mean `1.83`)** | **`3 / 30` (`10.0%`, mean `1.07`)** | Costs **`+3.39 V`** (`3` negative-EV horizon gambles: seeds `5, 18, 23`) |

Per-seed forensic audit of Gemini's five non-winning seeds (`1, 11, 15, 18, 26`) confirms every theoretical prediction of Section 2:
- **Seeds `1` and `26` (Tardos / Horstein `5%` noisy-channel flips):** Gemini planted `15` (`3` leaked) and `8` (`2` leaked) canaries and reached `P = 0.99` (`e39` vs mole `e33`, Day 19) and `P = 0.95` (`e04` vs mole `e08`, Day 10); single `5%` variant flips misled both Gemini and `SolverPolicy`'s own stopping rule on that evidence.
- **Seeds `15` and `18` (Hwang / Burnashev failure to split remaining consistent suspects):** On **seed `15`**, `e34` and `e37` were assigned the **exact same variant label** across every leaked canary (`6` planted, `2` leaked), and Gemini accused innocent `e34` (`-1.00`) on Day 12 with `9` days still available to plant a `2`-person `[e34: A, e37: B]` confirmation trap. On **seed `18`**, `4` suspects (`e09, e27, e29, e37`) remained consistent on Day 12, yet Gemini planted **`0` canaries on Days `14-18`** while running `6-7` interviews/day (`101` total), gambling at negative EV (`P = 0.63`, `EV = -0.08`) on innocent `e29` (`-1.00` vs solver `+0.52`).
- **Seed `11` (Dorfman under-sampling + bad draw -> abstention `0.00` vs solver `+0.62`):** Gemini ran `121` interviews and planted `12` alternate-day canaries (`0` leaked vs `4.38` expected careful / `5.03` uniform), leaving `7` unseparated suspects at Day 21.

---

## 4. Concrete Zero-Leakage and Opt-In Proposals for Silas (`P3.1` & `P3.2`)

Both proposals enforce strict protected-path and fairness discipline: **P3.1** and **P3.2b** require **zero edits to protected files** (`canary/social/biases.py` and `train/`), while **P3.2a** is an **opt-in `v1.5`/`v1.6` field** for Silas (`canary/rules.py`, `canary/env.py`, `canary/solver/belief.py`) that preserves the `v1.4` frozen hash `a8f99c2537c91d72` and RNG stream byte-for-byte when disabled (`collusion_scrub_prob = 0.0`).

---

### Proposal P3.1: Zero-Protected-Path `gen_canary_fatigue_deterrent` Social Bias Generator (`canary/social/biases.py`)

#### Research Justification
Bowen et al. (2009) identify *non-interference* with normal workflows as a central constraint on decoy-document deployment, and Beautement, Sasse & Wonham (2008) show that security controls exceeding employees' finite *compliance budget* provoke vocal pushback (`canary_cost = 0.01 V`). Meanwhile, Section 3.2 and `results/failure_analysis_v1.4.json` prove that `gemini-4-carbon`'s primary vulnerability on `v1.4` hard is **under-planting balanced 3-variant canaries** (`8.5` vs `14.1`/ep, `242/303` under-planted days crowded by `interview`).

Proposal **P3.1** adds `gen_canary_fatigue_deterrent(ctx: SocialDayContext, rng: random.Random, ...)` directly to `canary/social/biases.py` (zero protected paths):
1. **Mechanism:** Senior operations/team-lead speakers (`AUTHORITY_ROLES`) post naturalistic workflow complaints in `#general`, `#cross-team`, or `email` pushing back against circulating multiple 3-version draft memos across `10-20` staff (claiming wide watermarked drafts tip off careful readers and stall sign-offs) and explicitly urging the investigator to run **at most one narrow 2-person check** (`W(2) = 0.0487`, `5.3x` worse hit rate than `W(20) = 0.2564`!) or **interview** `Name (eXX)` directly.
2. **Strict Zero Hidden Mole Leakage (`LLR = 0.0000` nats):** Target `Name (eXX)` and speaker are drawn deterministically from public `PublicDayFacts` (`_public_consistent_pool(ctx)` over surfaced regular leaks, excluding `facts.decoy`), never reading `world.mole`. By the Data Processing Inequality ([Monograph 07](07_v15_bias_layer_proposals.md) Proposition 1), $I(\text{Event}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$, so `SolverPolicy` (`listen = False`, `0` interviews, `14.1` optimal ternary canaries) suffers **`0.000 V` loss**, whereas LLM investigators susceptible to colleague compliance pushback either skip their second daily canary slot, shrink early pool sizes from `k ~ 10-20` down to `k = 2` (`3.6x-5.3x` lower hit weight), or substitute `0.00477`-nat `interview` calls.
3. **Verified Simulation Audit (`200` `v1.4` Hard Seeds `0-199`, `600` Events on Days `3, 6, 9`):** Verified via `/tmp/fleet-silas/shared/agent-arena-venv/bin/python`: **`600 / 600` (`100.0%`)** events pass `validate_social_message` (`0` `FORBIDDEN_SUBJECT_PREFIXES`, `0` employee IDs in `subject`, `0` `DECOY_VOCAB` collisions, `0` `lint_text` errors, `100%` `Name (eXX)` + `SALIENCE_TERMS` in `body[:110]`), and Day 6 `target == world.mole` is **`17 / 200` (`8.50%`)** vs exact public consistent-set expectation **`10.04%`** (`LLR = 0.0000` nats).

#### Drop-In Implementation (`canary/social/biases.py`)
```python
def gen_canary_fatigue_deterrent(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    subjects = (
        "Draft version clutter from extra doc checks",
        "Keep doc verification checks narrow after meeting",
        "Re: version sprawl in shared doc circulation",
    )
    bodies = (
        f"Post-meeting doc note on {tn}: flooding half the roster with extra {doc_title} drafts stalls review; run a 2-person check or interview instead.",
        f"Doc version review on {tn}: wide three-label {doc_title} circulations tip off careful readers and clutter threads; stick to one narrow 2-person check.",
        f"Leak meeting follow-up on {tn}: broad {doc_title} draft variants slow sign-offs across teams; verify {tn} via a quick 2-person doc check or interview.",
    )
    channel = rng.choice(("#cross-team", "#general", "email"))
    return _build_event(
        ctx,
        "canary_fatigue_deterrent",
        speaker,
        target,
        channel,
        rng.choice(subjects),
        rng.choice(bodies),
        doc_title,
    )
```

---

### Proposal P3.2: Boneh-Shaw Same-Day Collusion Scrubbing (`canary/rules.py` / `canary/env.py`) & `O(N log N)` Horstein-Hwang Quantile Splitter (`train/` DAgger Teacher)

Proposal **P3.2** translates Boneh & Shaw (1998), Horstein (1963), Hwang (1972), and Burnashev (1976) into two complementary upgrades - one opt-in environment rule for Silas (**P3.2a**) and one zero-protected-path `train/` DAgger helper (**P3.2b**):

#### P3.2a (Opt-In for Silas): `collusion_scrub_prob` Same-Day Multi-Variant Diffing (`canary/rules.py`, `canary/env.py`, `canary/solver/belief.py`)
- **Research & Empirical Motivation:** Boneh & Shaw (1998) prove that when a traitor holds **two distinct fingerprinted copies** from the same release batch, diffing the copies exposes watermark positions and allows scrubbing. Our trajectory audit of `v1.4` hard (`seeds 0-29`) revealed that on 2-canary days, `gemini-4-carbon` reuses overlapping recipient pools across `c{d}` and `c{d}-2` at **mean Jaccard `0.550`** (`100` days), **2.35x** higher than `SolverPolicy`'s **`0.234`** (`136` days, because `SolverPolicy._candidates` prioritizes disjoint `rest = [e for e in top if e not in used]` pools first!).
- **Exact Rule & Frozen-Hash Invariant:** Add `collusion_scrub_prob: float = 0.0` (omitted from `TierParams.to_dict()` when `0.0` so `v1.4` frozen hash `a8f99c2537c91d72` is 100% unchanged). When `collusion_scrub_prob = q_s > 0` (recommended `q_s = 0.35` on `v1.6` hard/tracks) and the mole leaks canary `doc` (`day = d_0`) while **also** holding a second same-day canary (`other["is_canary"] and other["day"] == d_0 and w.mole in other["recipients"]`), with probability `q_s` the mole diffs the two same-day templates and scrubs the watermark so the surfaced `variant` is drawn uniformly over `sorted(doc["variants"])` (`1/m` each); otherwise standard `fingerprint_accuracy` (`0.95`) applies:
  $$p_{\text{true}}(q_s) = (1 - q_s)\alpha + \frac{q_s}{m}, \qquad p_{\text{flip}}(q_s) = \frac{1 - p_{\text{true}}(q_s)}{m - 1}$$
  At `q_s = 0.35`, `m = 3`, `alpha = 0.95`: **disjoint** same-day canary pairs (`c{d} \cap c{d}-2 = \emptyset`) retain full **`p_true = 0.9500`, `MI = 0.86544` nats (`LLR = +3.6376`)**, whereas **overlapping** same-day canary pairs drop to **`p_true = 0.7342`, `p_flip = 0.1329`, `MI = 0.33528` nats (`LLR = +1.7090`)** (`2.58x` MI penalty on sloppy duplicate targeting!). Because `c{d}` and `c{d}-2` recipient lists are chosen by the investigator (`obs.docs`), `SolverPolicy` (`canary/solver/belief.py` lines `103-110`) checks `same_day_held` for suspect `s` in `O(1)` time with **zero hidden-state leakage** and **zero calibration loss**.

#### P3.2b (Zero Protected Paths): `FrugalHorsteinTeacher` Posterior-Quantile Ternary Splitter (`train/` Tiebreaker DAgger)
- **Motivation (`Qwen2.5-0.5B`/`1.5B` tiebreaker on FR8 V100s):** As documented in [Master Synthesis Section 6.1](../research-deception.md), small-model GRPO (`Qwen2.5-1.5B` `v3-8k-s2`: `-0.050 +/- 0.049`) repaired SFT over-accusation (`-0.457`) without beating `0.000` abstention because multi-day active canary partitioning requires on-policy expert action labels (DAgger), and full `SolverPolicy` (`136 + 96` `joint_mi` evaluations/day, `88.37s / 100` hard episodes) emits complex randomized coverage shuffles.
- **Horstein-Hwang + Burnashev Two-Phase Rule (`O(N log N)`, deterministic):**
  1. *Phase 1 (Horstein-Hwang narrowing when `95%`-credible core `|core| > 6`):* Cap pool size at `cap = min(|core|, max(6, N // 3))` (`~13` suspects/canary) and greedily deal sorted posterior suspects into `ABC` to equalize posterior mass `(1/3, 1/3, 1/3)`; if `canaries_per_day >= 2` and `len(pending) < 3`, deal a **disjoint** second ternary canary over `rest = core \ asg1` (immune to **P3.2a** scrubbing and achieving combined `2 x 13` coverage at `careful_mole` weight `0.675`).
  2. *Phase 2 (Burnashev confirmation when `|core| <= 6`):* Switch to `1-2` recipients per variant (`tiny` confirmation) with cyclic label rotation `(i // per + len(pending)) % 3` across pending traps so consecutive leaked traps are orthogonal.
- **Verified Benchmark Across `100` `v1.4` Hard Seeds (`0-99`):** Verified via `/tmp/fleet-silas/shared/agent-arena-venv/bin/python`: `FrugalHorsteinTeacher` achieves **`0.5067` mean score** (`91.0%` accusation accuracy, **`9.89` canaries/ep** vs `12.44` for full `SolverPolicy`, beating `gemini-4-carbon`'s `0.322` by `+0.184 V`) in **`12.25s` vs `88.37s` (`7.2x` wall-clock speedup, `0` `> 0.30s` slow steps)**, providing clean, low-entropy deterministic `ABC` quantile targets for V100 DAgger tiebreaker training in `train/`.

---

## 5. Summary Verification Table

| Study / Artifact | Venue & Year | Live HTTP-200 Link | Key Theoretical / Empirical Result | Canary `v1.4` / `v1.6` Mapping |
|---|---|---|---|---|
| Boneh & Shaw | *IEEE TIT* (1998) | https://openalex.org/W2134195444 | Collusion-secure fingerprinting traces leaks & deters traitors; multi-copy diffing scrubs markers | `plant_canary`, `max_variants = 3`, `careful_mole`, **P3.2a** `collusion_scrub_prob` |
| Chor, Fiat, Naor & Pinkas | *IEEE TIT* (2000) | https://openalex.org/W2295616646 | Probabilistic traitor tracing over shared multi-party data & threshold decoders | `16`-recipient 2-dept regular leaks + `>= 85%` solver catchability floor |
| Tardos | *JACM* (2008) | https://openalex.org/W2031722321 | Optimal $O(c^2 \log(N/\epsilon))$ randomized fingerprint codes & LLR decoding | Log-likelihood `belief.py` (`+3.6376` nats) & `justSilas-expert` converse wall |
| Aldridge, Johnson & Scarlett | *FnT CIT* (2019) | https://openalex.org/W2912457157 | Constant-factor group-testing rate $I(Y; V)$ & noisy adaptive capacity bounds | `0.86544` nats/leak (`181.4x` `interview`), `4.233`-trap lower bound for $\ln(39)$ |
| Dorfman | *Ann. Math. Stat.* (1943) | https://doi.org/10.1214/aoms/1177731363 | Pooled group screening beats 1-by-1 individual inspection for rare defectives | Diagnoses Gemini's `68.0` individual interviews vs pooled `plant_canary` |
| Hwang | *JASA* (1972) | https://doi.org/10.1080/01621459.1972.10481257 | Generalized Binary Splitting adapts pool size to prior $K/N$ near entropy floor | `SolverPolicy.partition_balanced` (`3` labels + `none_group` complement) |
| Horstein / Waeber et al. | *IEEE TIT* (1963) / *SICON* (2013) | https://doi.org/10.1109/TIT.1963.1057832 | Posterior-quantile probabilistic bisection converges geometrically under channel noise | Soft Bayesian quantile splitting under `fingerprint_accuracy = 0.95` (**P3.2b**) |
| Burnashev / Berlin et al. / Naghshvar & Javidi | *PPI* (1976) / *IEEE TIT* (2009) / *AoS* (2013) | https://openalex.org/W1990503235 | Optimal active stopping requires a narrowing phase + high-KL confirmation phase | `SolverPolicy` `11.8%` `<= 3`-person confirmation traps vs Gemini `0.0%` (`0/254`) |
| Bowen, Hershkop, Keromytis & Stolfo | *SecureComm* (2009) | https://doi.org/10.1007/978-3-642-05284-2_4 | `D3` decoy-document baiting: believability, conspicuousness, detectability, non-interference | `MoleView` omits `is_canary`; workflow clutter grounds **P3.1** (`600/600` valid) |
| Pawlick, Colbert & Zhu | *ACM CSUR* (2019) | https://openalex.org/W2971648973 | 6-type game-theoretic deception taxonomy; honey-x signaling flips asymmetry | Formal signaling-game duality between `plant_canary` and `framing = True` |
