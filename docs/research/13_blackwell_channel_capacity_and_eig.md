# 13. Blackwell Experiment Dominance, Channel Capacity, and Lindley EIG Decomposition in Canary

**Squad:** `research` (`canary-research-w6`)  
**Baseline commit:** `713f3ddd` (`origin/fr8/canary/research`, synced with `origin/justSilas@58716742`; rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Audit Harness:** `scripts/audit_blackwell_channel_capacity.py` and `tests/test_audit_blackwell_channel_capacity.py` (`0` API calls, deterministic CPU, `0` protected paths touched)  
**Companion Monographs:** [Master Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [02. Insider Threat](02_insider_threat.md) | [03. Leak Hunts, Canary Traps & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](08_mole_rl_stackelberg_and_catchability.md)  
**Primary Benchmark Evidence:** [Gap Report](../reports/gap.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Below-Break-Even Spotlight](../reports/failure_gallery_breakeven.md) | [Reference Optimality](../reports/reference_optimality.md) | [Difficulty Design](../DIFFICULTY.md)

---

## 1. Executive Thesis: Why Canary's Frontier Gap Is a Theorem of Statistical Experiment Comparison

Why does Canary's Bayesian reference investigator (`SolverPolicy`, `canary/solver/policy.py`) score `0.499 +/- 0.119` on `v1.4` hard (`n = 30` post-hoc locked paired dev seeds `0-29`, frozen hash `a8f99c2537c91d72`) with **`0` `interview` calls**, while `gemini-4-carbon` over OpenCode/MCP scores `0.322 +/- 0.199` (**65% [24%, 98%]** raw, **72% [52%, 91%]** luck-adjusted; raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`) after burning **`68.03` interviews per episode** (`2,041` total calls, `2,039` valid)?

Existing deception meta-analyses show qualitatively that passive questioning cues are weak (`interview_lr = 1.2`, `p_evasive_innocent = 0.2`), yet a qualitative statement leaves three foundational questions open:
1. Could *some* prior belief vector or *some* company-value loss state $V \in (0, 1]$ make a free passive `interview` decision-theoretically preferable to a leaked `plant_canary` experiment?
2. When `careful_mole = True`, probabilistic non-leaking (`p_leak = 0.65`), and regular-document competition (`docs_per_day = (2, 3, 4)`) dilute `plant_canary` below its conditional `0.86544`-nat ceiling, how large is unconditional single-action Expected Information Gain (EIG) relative to `interview`?
3. Across the `30` paired `v1.4` hard trajectories (`results/failure_analysis_v1.4.json`), how much of `gemini-4-carbon`'s information deficit and **`3.39 V` un-isolated commitment penalty** comes from **action-slot crowding** (planting too few canaries because `interview` calls exhaust the `8`-action daily budget on `242` of the `303` under-planted days) versus **sub-optimal per-canary partition design**?

`scripts/audit_blackwell_channel_capacity.py` resolves all three questions with exact rational linear algebra, Lindley-Shannon mutual information, and step-by-step posterior replay across all `30` paired `v1.4` hard episodes:

1. **Exact Rational Strict Blackwell Dominance (`G` with `max_err = 2.78e-17`).** By Blackwell's (1953) Equivalence Theorem, statistical experiment $\mathcal{E}_1$ dominates $\mathcal{E}_2$ across **every** prior distribution and **every** bounded utility/loss function (including Canary's asymmetric accusation payoff $+V$ vs $-1.0$ and abstention $0.0$) if and only if $\mathcal{E}_2 = \mathcal{E}_1 G$ for a row-stochastic Markov garbling matrix $G$. On `v1.4` hard (`max_variants = 3`, `fingerprint_accuracy = 0.95`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`), `audit_blackwell_channel_capacity.py` constructs the exact rational `3 x 2` garbling matrix $G$ with $g_A = \mathbf{224/925} \approx 0.242162$ and $g_{\neg A} = \mathbf{184/925} \approx 0.198919$ (`3/10` and `1/5` on `easy`; `13/50` and `1/5` on `medium`), reconstructing `P_interview = P_canary G` to machine precision (`2.78e-17`) while reverse garbling is strictly impossible (`TV_interview = 0.040 < TV_canary = 0.925`).
2. **Conditional, Capacity, Prior-Weighted, and Unconditional Windowed EIG Hierarchy (`40.3x` to `7,264.4x`).** A single leaked 3-variant canary on `v1.4` hard yields `0.86544` nats of mutual information, equivalent to **`181.27` exact-KL interviews** (`181.4` at 5-decimal table rounding), **`741.6` worst-case Shannon-capacity interviews** (`C_iv = 0.001167` nats achieved at prior $q^* = 0.49455$), and **`7,264.4` Day-1 uniform-prior interviews** (`EIG_iv(1/39) = 0.000119` nats, illustrating Nelson's 2005 critique of prior-free diagnosticity). Even unconditionally before knowing whether a trap will leak over its `leak_window_days = 3` window against regular 2-department documents, an optimal Day-1 canary (`k* = 17`, `n_reg = 1.2`) yields **`0.41762` nats** (`87.5x` `KL_iv`, **`3,505.5x`** Day-1 `EIG_iv`), and a steady-state canary (`k* = 15`, `n_reg = 3.6`) yields **`0.19247` nats** (`40.3x` `KL_iv`, **`1,615.6x`** Day-1 `EIG_iv`) while costing `0.01 V` (`0.02 V/day` across `canaries_per_day = 2`, strictly below expected daily leak bleed `0.65 * 0.05 = 0.0325 V/day`).
3. **Exact Replay Shapley Decomposition of the `62.76`-Nat EIG Deficit and `3.39 V` Commitment Loss (`77.7%` Slot Crowding vs `22.3%` Partition Design).** Replaying every investigative step of `opencode-gemini-4-carbon` and `SolverPolicy` on `v1.4` hard seeds `0-29` (`0` score/accusation discrepancies) shows `SolverPolicy` accumulates **`130.3512` nats** of 3-day canary EIG (`424` canaries, `0.30743` nats/canary, `0.10378` nats/action) versus `gemini-4-carbon`'s **`67.5912` nats** (`254` canaries, `0.26611` nats/canary, `0.02275` nats/action) - a **`4.56x` per-action EIG advantage** for `SolverPolicy`, while all **`2,039` valid interviews** executed by `gemini-4-carbon` across 30 episodes yielded **`1.1077` nats total** (`0.000543` nats/interview, `0.0369` nats/episode - equivalent to just **`4.16` canaries total**, or `0.14` canaries/episode). Exact two-factor Shapley decomposition of the **`62.7601`-nat** canary EIG deficit attributes **`77.68%` (`48.7508` nats, `2.63 V` of the `3.39 V` un-isolated commitment loss)** to **canary-slot crowding** (`170` unplanted canaries) and **`22.32%` (`14.0092` nats, `0.76 V`)** to **per-canary partition design** (`86.6%` per-canary EIG efficiency; Oaxaca solver-reference split: `83.28%` / `2.82 V` crowding vs `16.72%` / `0.57 V` partition).

Section 2 grounds ten primary statistical, information-theoretic, and cognitive-psychology papers with live HTTP-200 verified links and verbatim quotes. Section 3 presents the exact mathematical derivations and `v1.4` tier tables. Section 4 reports the step-by-step 30-seed replay decomposition. Section 5 specifies two concrete, zero-leakage / catchability-verified proposals: **P13.1 (`gen_binary_check_anchor` positive-test lure in `canary/social/biases.py`, `24/24` lint PASS, `LLR = 0.0000` nats)** and **P13.2 (opt-in variable-cost canary alphabet tiers + `partition_aware_sleeper_v14` `MoleStrategy` achieving `min_regret = +0.1650` vs `+0.1333` default at `90.0% >= 85.0%` `SolverPolicy` catchability)**.

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Citations and Verbatim Quotes)

### 2.1 Equivalent Comparisons of Statistical Experiments and Garbling: Blackwell (1953)

- **Citation:** Blackwell, D. (1953). Equivalent Comparisons of Experiments. *The Annals of Mathematical Statistics*, 24(2), 265-272.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/aoms/1177729032 | DOI: https://doi.org/10.1214/aoms/1177729032
- **Theoretical Contribution:** Proves the equivalence between **decision-theoretic dominance** (experiment $\mathcal{E}_1$ achieves weakly lower Bayes risk than $\mathcal{E}_2$ for every prior and every bounded loss function) and **statistical garbling** ($\mathcal{E}_2 = \mathcal{E}_1 G$ for a Markov transition kernel $G$ that adds pure post-processing noise without accessing the hidden state $\theta$).
- **Verbatim Quote (Summary):**
> "Sherman [8] and Stein [9] have shown that a method given by the author [1] for comparing two experiments is equivalent, for experiments with a finite number of outcomes, to the original method introduced by Bohnenblust, Shapley, and Sherman [4]. A new proof of this result is given, and the restriction to experiments with a finite number of outcomes is removed. A class of weaker comparisons--comparison in $k$-decision problems--is introduced, in three equivalent forms. For dichotomies, all methods are equivalent, and can be described in terms of errors of the first and second kinds."
- **Relevance to Canary:** Proves that `SolverPolicy`'s preference for leaked `plant_canary` partitions over `interview` is **utility-invariant**: because `P_interview = P_canary G` holds via an explicit strictly interior stochastic matrix $G$ (`g_A = 224/925`, `g_non_A = 184/925` on `v1.4` hard), **no** company-value state $V$ and **no** prior belief over suspects can ever give an `interview` higher Bayes decision value than a leaked 3-variant canary covering the suspect.

### 2.2 Expected Shannon Information Provided by an Experiment: Lindley (1956)

- **Citation:** Lindley, D. V. (1956). On a Measure of the Information Provided by an Experiment. *The Annals of Mathematical Statistics*, 27(4), 986-1005.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/aoms/1177728069 | DOI: https://doi.org/10.1214/aoms/1177728069
- **Theoretical Contribution:** Defines the expected information of a statistical experiment $\mathcal{E}$ under prior $p(\theta)$ as mutual information $\text{EIG}(\mathcal{E}; p) = H(\Theta) - \mathbb{E}_Y[H(\Theta \mid Y)] = I(\Theta; Y)$, proving invariance to one-to-one reparameterizations, additivity over sequential stages, and consistency with Blackwell's garbling partial order ($\mathcal{E}_1 \succeq_B \mathcal{E}_2 \implies \text{EIG}(\mathcal{E}_1; p) \ge \text{EIG}(\mathcal{E}_2; p)$ for all priors $p$).
- **Verbatim Quote (Summary):**
> "A measure is introduced of the information provided by an experiment. The measure is derived from the work of Shannon [10] and involves the knowledge prior to performing the experiment, expressed through a prior probability distribution over the parameter space. The measure is used to compare some pairs of experiments without reference to prior distributions; this method of comparison is contrasted with the methods discussed by Blackwell. Finally, the measure is applied to provide a solution to some problems of experimental design, where the object of experimentation is not to reach decisions but rather to gain knowledge about the world."
- **Relevance to Canary:** Directly grounds `canary/solver/policy.py` (`canary_eig`) and `exact_canary_eig_nats` in `scripts/audit_blackwell_channel_capacity.py`: during Days `1..18` when immediate accusation is sub-optimal ($p_{\max} < P^*(V)$), selecting the `plant_canary` assignment that maximizes expected posterior entropy reduction $H(\text{Mole}) - \mathbb{E}_Y[H(\text{Mole} \mid Y)]$ is the exact Lindley-optimal exploratory design rule.

### 2.3 Uncertainty Functions and Sequential Experimental Stopping: DeGroot (1962)

- **Citation:** DeGroot, M. H. (1962). Uncertainty, Information, and Sequential Experiments. *The Annals of Mathematical Statistics*, 33(2), 404-419.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/aoms/1177704567 | DOI: https://doi.org/10.1214/aoms/1177704567
- **Theoretical Contribution:** Generalizes Lindley's Shannon-entropy EIG to arbitrary concave uncertainty functions derived from terminal statistical decision losses, analyzing sequential policies that choose experiments at each stage to minimize expected terminal loss or expected sample size to reach a target certainty threshold.
- **Verbatim Quote (Summary):**
> "The information in an experiment is then defined as the expected difference between the uncertainty of the prior distribution over $\Omega$ and the uncertainty of the posterior distribution. In any particular situation, the selection of an appropriate uncertainty function would typically be based on the use to which the experimenter's knowledge about $\theta$ is to be put. If, for example, the actions available to the experimenter and the losses associated with these actions can be specified as in a statistical decision problem, then presumably the uncertainty function would be determined from the loss function."
- **Relevance to Canary:** Bridges early-game **Shannon entropy reduction** (splitting `39` suspects into balanced thirds) and endgame **loss-derived Bayes stopping** (`canary/solver/policy.py` switching from balanced 3-way splits when $H(\text{Mole})$ is broad to targeted `k <= 3` confirmation traps as $p_{\max}$ approaches Canary's asymmetric accusation threshold $1/(1+V)$).

### 2.4 Noisy Discrete Channel Capacity and Converse Coding Bounds: Shannon (1948)

- **Citation:** Shannon, C. E. (1948). A Mathematical Theory of Communication. *The Bell System Technical Journal*, 27(3), 379-423.
- **Live Verified Links:** https://api.crossref.org/works/10.1002/j.1538-7305.1948.tb01338.x | DOI: https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- **Theoretical Contribution:** Establishes discrete channel capacity $C = \max_{p(x)} I(X; Y)$ and proves that resolving $H(\Theta)$ nats of source uncertainty across noisy channel uses requires at least $H(\Theta) / C$ expected channel transmissions.
- **Verbatim Quote (Introduction):**
> "In the present paper we will extend the theory to include a number of new factors, in particular the effect of noise in the channel, and the savings possible due to the statistical structure of the original message and due to the nature of the final destination of the information."
- **Relevance to Canary:** Yields both exact worst-case capacities in Canary `v1.4` hard: the symmetric 3-ary `plant_canary` channel (`fingerprint_accuracy = 0.95`, flip `0.025`) achieves capacity $C_{\text{canary}} = \mathbf{0.86544\text{ nats}}$ at uniform `(1/3, 1/3, 1/3)` variant mass, whereas the asymmetric binary `interview` channel (`0.20` vs `0.24`) has global Shannon capacity $C_{\text{iv}} = \mathbf{0.001167\text{ nats}}$ (achieved at prior $q^* = 0.49455$), a **`741.6x` capacity ratio**.

### 2.5 Decision-Theoretic Unification of Bayesian Experimental Design: Chaloner & Verdinelli (1995)

- **Citation:** Chaloner, K., & Verdinelli, I. (1995). Bayesian Experimental Design: A Review. *Statistical Science*, 10(3), 273-304.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/ss/1177009939 | DOI: https://doi.org/10.1214/ss/1177009939
- **Theoretical Contribution:** Synthesizes Lindley's Shannon-information criterion ($D$-/entropy-optimality) and terminal decision utility within a single two-stage Savage expected-utility framework $\max_{e \in E} \int_{\mathcal{Y}} \max_{d \in D} \int_\Theta u(d, \theta, e, y)\, p(\theta \mid y, e)\, p(y \mid e)\, d\theta\, dy$, showing how explicit experimental costs $c(e)$ trade off against posterior variance/entropy reduction.
- **Verbatim Quote (Abstract):**
> "This paper reviews the literature on Bayesian experimental design. A unified view of this topic is presented, based on a decision-theoretic approach. This framework casts criteria from the Bayesian literature of design as part of a single coherent approach. The decision-theoretic structure incorporates both linear and nonlinear design problems and it suggests possible new directions to the experimental design problem, motivated by the use of new utility functions."
- **Relevance to Canary:** Formalizes Canary's explicit experimental cost trade-off (`canary_cost = 0.01 V` vs expected leak bleed `0.0325 V/day` on `v1.4` hard) and grounds Proposal **P13.2a** (`binary_probe` at `0.005 V`, `standard_ternary` at `0.010 V`, and `wide_pentanary` at `0.025 V`), where optimal design shifts from cost-efficient broad partitioning to high-capacity endgame isolation as $H(\text{Mole})$ shrinks.

### 2.6 Normative Failure of Prior-Free Diagnosticity vs Information Gain: Nelson (2005)

- **Citation:** Nelson, J. D. (2005). Finding Useful Questions: On Bayesian Diagnosticity, Probability, Impact, and Information Gain. *Psychological Review*, 112(4), 979-999.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/0033-295X.112.4.979 | DOI: https://doi.org/10.1037/0033-295X.112.4.979
- **Theoretical Contribution:** Compares competing normative metrics of question usefulness - **Bayesian diagnosticity** (likelihood ratio $\text{LR} = P(E \mid H_1)/P(E \mid H_0)$), **information gain** (Lindley mutual information), **Kullback-Leibler divergence**, **probability gain** (Bayes classification error reduction), and **impact** - proving that likelihood-ratio diagnosticity is scale-blind to rare event rates and prior skew, contradicting both information gain and expected decision utility.
- **Verbatim Quote (Abstract):**
> "Several norms for how people should assess a question's usefulness have been proposed, notably Bayesian diagnosticity, information gain (mutual information), Kullback-Liebler distance, probability gain (error minimization), and impact (absolute change). Several probabilistic models of previous experiments on categorization, covariation assessment, medical diagnosis, and the selection task are shown to not discriminate among these norms as descriptive models of human intuitions and behavior. Computational optimization found situations in which information gain, probability gain, and impact strongly contradict Bayesian diagnosticity. In these situations, diagnosticity's claims are normatively inferior."
- **Relevance to Canary:** Directly explains the **`7,264.4x` Day-1 EIG gap** in Canary `v1.4` hard! An uncalibrated LLM reading `interview_lr = 1.2` sees a positive likelihood ratio (`+0.1823` nats on an evasive answer), but at Day-1 prior $q = 1/39 = 0.02564$ an interview yields $\text{EIG}_{\text{iv}}(1/39) = \mathbf{0.000119\text{ nats}}$ and **zero** probability gain (`eu_interview = 0.0` for every $q \le 0.48$), whereas a Day-1 windowed canary (`k* = 17`) delivers `0.41762` nats (`3,505.5x` unconditionally; `7,264.4x` conditional on leak).

### 2.7 Positive-Test Heuristic and Asymmetric Single-Target Probing: Klayman & Ha (1987)

- **Citation:** Klayman, J., & Ha, Y.-W. (1987). Confirmation, Disconfirmation, and Information in Hypothesis Testing. *Psychological Review*, 94(2), 211-228.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/0033-295X.94.2.211 | DOI: https://doi.org/10.1037/0033-295X.94.2.211
- **Theoretical Contribution:** Demonstrates that human hypothesis-testers default to a **positive test strategy** - probing individual focal candidates expected to hold the target property (`1-on-1` or `1-vs-rest` confirmation tests) rather than designing balanced multi-hypothesis partitions - which causes severe information loss whenever the candidate pool exceeds two hypotheses.
- **Verbatim Quote (Abstract):**
> "With this strategy, there is a tendency to test cases that are expected (or known) to have the property of interest rather than those expected (or known) to lack that property. This strategy is not equivalent to confirmation bias in the first sense; we show that the positive test strategy can be a very good heuristic for determining the truth or falsity of a hypothesis under realistic conditions. It can, however, lead to systematic errors or inefficiencies. The appropriateness of human hypothesis-testing strategies and prescriptions about optimal strategies must be understood in terms of the interaction between the strategy and the task at hand."
- **Relevance to Canary:** Directly grounds both why `gemini-4-carbon` loses `13.4%` per-canary EIG relative to `SolverPolicy` (`0.26611` vs `0.30743` nats/canary; partition entropy `1.0022` vs `1.0476` nats) and Proposal **P13.1 (`gen_binary_check_anchor`)**: nudging an investigator toward "clean single-person (`k = 1`) or asymmetric `1-vs-(k-1)` binary confirmation drafts" destroys **`32.6%` to `45.5%`** of 3-way canary EIG (and **`59.7%` to `81.8%`** for `k = 1` traps under `careful_mole` + regular-doc competition) without leaking a single bit of hidden mole identity.

### 2.8 Receiver-Optimal Signal Design vs Garbled Persuasion: Kamenica & Gentzkow (2011)

- **Citation:** Kamenica, E., & Gentzkow, M. (2011). Bayesian Persuasion. *American Economic Review*, 101(6), 2590-2615.
- **Live Verified Links:** https://api.crossref.org/works/10.1257/aer.101.6.2590 | DOI: https://doi.org/10.1257/aer.101.6.2590
- **Theoretical Contribution:** Characterizes optimal signal structures over a finite state space via concavification of the receiver's indirect utility over posteriors, showing that informative experiments induce mean-preserving spreads of the prior with high posterior dispersion while garbled signals collapse posteriors inside the inaction region.
- **Verbatim Quote (Abstract):**
> "We consider a symmetric information model where a sender chooses a signal to reveal to a receiver, who then takes a noncontractible action that affects the welfare of both players. We derive necessary and sufficient conditions for the existence of a signal that strictly benefits the sender."
- **Relevance to Canary:** Explains the exact Bayes-utility dominance table in `audit_blackwell_channel_capacity.py` (`bayes_utility_checks`): across priors $q_A \in \{0.10, 0.3333, 0.50\}$ and company values $V \in \{0.85, 0.70, 0.55\}$, a single `interview` keeps both posterior realizations (`evasive` and `cooperative`) below or barely at the break-even accusation threshold $1/(1+V)$ (`eu_interview = 0.0000` in `8/9` cells and `0.0020` at $V=0.85, q_A=0.50$), whereas a leaked 3-variant canary pushes the matching posterior above $0.90$ and yields `0.4725 V` to `0.7575 V` of positive expected decision utility.

### 2.9 Group-Testing Rate Constants and Per-Test Information: Aldridge, Johnson & Scarlett (2019)

- **Citation:** Aldridge, M., Johnson, O., & Scarlett, J. (2019). Group Testing: An Information Theory Perspective. *Foundations and Trends in Communications and Information Theory*, 15(3-4), 196-392.
- **Live Verified Links:** https://api.crossref.org/works/10.1561/0100000099 | DOI: https://doi.org/10.1561/0100000099
- **Theoretical Contribution:** Formalizes the finite-blocklength and adaptive **rate of group testing** (bits/nats learned per pooled test under channel noise and dilution), proving that test pool sizes and partition balance govern the constant factor of required tests.
- **Verbatim Quote (Abstract):**
> "We assess the theoretical guarantees not only in terms of scaling laws, but also in terms of the constant factors, leading to the notion of the rate of group testing, indicating the amount of information learned per test."
- **Relevance to Canary:** Establishes Canary `v1.4` hard's exact finite-horizon constant factors: conditional 3-way group-testing rate `0.86544` nats/leak (`4.233` leaked traps lower bound for `39` non-decoy suspects) and unconditional windowed group-testing rate `0.41762` nats on Day 1 (`k* = 17`) and `0.19247` nats in steady state (`k* = 15`), explaining why planting `8.47` vs `14.13` canaries/episode leaves `gemini-4-carbon` `2.092` nats/episode short of `SolverPolicy`.

### 2.10 Why Cue-Weight Disclosure Cannot Rescue Low-Capacity Channels: Hartwig & Bond (2011)

- **Citation:** Hartwig, M., & Bond, C. F., Jr. (2011). Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/a0023589 | DOI: https://doi.org/10.1037/a0023589
- **Theoretical Contribution:** Synthesizes `153` Brunswikian lens-model samples to show that human lie-detection failure stems from the near-zero channel capacity of passive demeanor cues rather than miscalibrated cue weights, so explicit validity instructions cannot substitute for active behavioral separation.
- **Verbatim Quote (Abstract):**
> "In conclusion, contrary to previous assumptions, people rarely rely on the wrong cues. Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."
- **Relevance to Canary:** Directly confirmed by Part B of our replay audit: `Env.instruction()` prints the exact `v1.4` hard cue validity (`interview_lr = 1.2`, `p_evasive_innocent = 0.2`), yet `gemini-4-carbon`'s `2,039` valid interviews across `30` episodes accumulated only **`1.1077` nats total** (`0.0369` nats/episode = `1.01%` of the `3.6636`-nat non-decoy prior entropy $\ln 39$), proving empirically that passive questioning cannot isolate a mole even under full parameter transparency.

---

## 3. Exact Blackwell Dominance Proof and Multi-Tier Channel Capacity Audit (Part A)

### 3.1 Constructive Rational Proof of Strict Blackwell Dominance (`plant_canary` $\succ_B$ `interview`)

Consider three disjoint non-decoy suspect groups $(S_A, S_B, S_C)$ assigned distinct variants $(A, B, C)$ in a `plant_canary` experiment (`max_variants = 3`), and compare observing the leaked canary variant $Y \in \{A, B, C\}$ (with symmetric accuracy $\alpha = \text{fingerprint\_accuracy}$ and off-diagonal flip rate $\epsilon = (1 - \alpha)/2$) against interviewing suspect $e \in S_A$ and observing binary demeanor $Z \in \{\text{evasive}, \text{cooperative}\}$ (with innocent evasiveness $p_0 = \text{p\_evasive\_innocent}$ and mole evasiveness $p_1 = p_0 \cdot \text{interview\_lr}$).

Over the 3-cell state partition $\Theta_{\text{part}} = \{\text{Mole} \in S_A,\, \text{Mole} \in S_B,\, \text{Mole} \in S_C\}$, the two Markov experiment matrices are:

$$P_{\text{canary}} = \begin{pmatrix} \alpha & \epsilon & \epsilon \\ \epsilon & \alpha & \epsilon \\ \epsilon & \epsilon & \alpha \end{pmatrix}, \qquad P_{\text{interview}} = \begin{pmatrix} p_1 & 1 - p_1 \\ p_0 & 1 - p_0 \\ p_0 & 1 - p_0 \end{pmatrix}.$$

Solving $P_{\text{canary}} G = P_{\text{interview}}$ for a `3 x 2` post-processing kernel $G$ with row entries $(g_A, 1 - g_A)$ on variant $A$ and $(g_{\neg A}, 1 - g_{\neg A})$ on variants $B, C$ yields the unique closed-form rational solution (`exact_blackwell_garbling` in `scripts/audit_blackwell_channel_capacity.py`):

$$\Delta = \frac{p_1 - p_0}{\alpha - \epsilon}, \qquad g_{\neg A} = p_0 - \epsilon \Delta, \qquad g_A = g_{\neg A} + \Delta.$$

Evaluating `exact_blackwell_garbling` across all three frozen `v1.4` tiers (`a8f99c2537c91d72`) establishes **strict Blackwell dominance** on every tier:

| `v1.4` Tier | Canary $(\alpha, \epsilon)$ | Interview $(p_0, p_1)$ | Exact Rational $g_A$ | Exact Rational $g_{\neg A}$ | $\|P_{\text{can}} G - P_{\text{iv}}\|_\infty$ | $\text{TV}_{\text{canary}}$ vs $\text{TV}_{\text{iv}}$ | Strict Blackwell Dominance |
|---|---|---|---|---|---:|---|---:|
| **`easy`** ($N=12$) | `(1.000, 0.000)` | `(0.200, 0.300)` | **`3/10`** (`0.300000`) | **`1/5`** (`0.200000`) | `0.00e+00` | `1.000` vs `0.100` | **`True`** |
| **`medium`** ($N=20$) | `(1.000, 0.000)` | `(0.200, 0.260)` | **`13/50`** (`0.260000`) | **`1/5`** (`0.200000`) | `0.00e+00` | `1.000` vs `0.060` | **`True`** |
| **`hard`** ($N=40$) | `(0.950, 0.025)` | `(0.200, 0.240)` | **`224/925`** (`0.242162`) | **`184/925`** (`0.198919`) | `2.78e-17` | `0.925` vs `0.040` | **`True`** |

Three exact properties follow immediately from `audit_blackwell_channel_capacity.py`:
1. **Strict interiority:** On `v1.4` hard, $g_A = 224/925 \in (0, 1)$ and $g_{\neg A} = 184/925 \in (0, 1)$ (`is_row_stochastic_strict_interior = True`), so an investigator holding a leaked canary outcome can *literally simulate* an `interview` of any group via a local coin flip without calling the environment.
2. **Non-invertibility (strictness):** By data-processing contraction of total variation distance, any reverse garbling $H$ satisfying $P_{\text{interview}} H = P_{\text{canary}}$ would require $\text{TV}_{\text{canary}} \le \text{TV}_{\text{interview}}$, which fails by **`23.1x`** on `hard` (`0.925 > 0.040`, `reverse_garbling_impossible = True`).
3. **Positive Bayes expected-utility dominance across Canary's accusation payoff (`+V` vs `-1.0`, abstain `0.0`):** Across all `15` `(V, prior_A)` grid points tested (`V in {0.85, 0.70, 0.55}`, `prior_A in {0.10, 0.3333, 0.50, 0.65, 0.80}`), `eu_canary > eu_interview` strictly (`dominance_gap` from **`+0.2325 V` to `+0.7575 V`** on `hard`). At every moderate prior (`prior_A <= 0.3333`), a single interview leaves both posteriors below $1/(1+V)$ and produces **`0.0000 V`** decision value, whereas a leaked 3-way canary yields **`+0.7575 V`** ($V=0.85$), **`+0.6150 V`** ($V=0.70$), and **`+0.4725 V`** ($V=0.55$).

### 3.2 Complete `v1.4` Channel Capacity and Windowed Lindley EIG Hierarchy

First, our audit cross-checks the passive binary `interview` Kullback-Leibler divergences across all three frozen `v1.4` tiers (`verify_research_deception.py` reference format):

| Investigative Channel (`v1.4` Tier) | $P(\text{evasive} \mid \text{inn})$ | $P(\text{evasive} \mid \text{mole})$ | $\text{LLR}_+$ (Evasive) | $\text{LLR}_-$ (Coop) | Forward $D_{\text{KL}}(P_{\text{mole}} \| P_{\text{inn}})$ |
|---|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | `0.200` | `0.300` | `+0.4055` | `-0.1335` | `0.02817` nats |
| `interview` (`medium`, `LR=1.3`) | `0.200` | `0.260` | `+0.2624` | `-0.0780` | `0.01052` nats |
| `interview` (`hard`, `LR=1.2`) | `0.200` | `0.240` | `+0.1823` | `-0.0513` | `0.00477` nats |

Second, because `KL` measures divergence only at the degenerate `1`-vs-`1` point and ignores both binary channel capacity maximization and `plant_canary`'s unconditional leak probability under `careful_mole` (`w(k) = 1 - k / N`) and regular-document competition ($q(e) = 1 - (1 - p_{\text{leak}} w / (w + \max(1, n_{\text{reg}}(e))))^W$), `audit_tier_channels()` computes all four exact ratios across `easy`, `medium`, and `hard`:

| Metric (`scripts/audit_blackwell_channel_capacity.py`) | `v1.4` Easy ($N=12, m=12$) | `v1.4` Medium ($N=20, m=19$) | `v1.4` Hard ($N=40, m=39$) |
|---|---:|---:|---:|
| Non-decoy prior entropy $\ln(m)$ | `2.48491` nats | `2.94444` nats | **`3.66356` nats** |
| `interview` forward $D_{\text{KL}}(P_1 \| P_0)$ | `0.02817` nats | `0.01052` nats | **`0.00477` nats** |
| `interview` Shannon capacity $C_{\text{iv}} = \max_q I(\text{Mole}_e; Z)$ | `0.00671` nats ($q^*=0.4888$) | `0.00255` nats ($q^*=0.4923$) | **`0.00117` nats** ($q^*=0.4945$) |
| `interview` Day-1 uniform-prior $\text{EIG}_{\text{iv}}(1/m)$ | `0.00213` nats | `0.00052` nats | **`0.00012` nats** (`0.000119`) |
| `plant_canary` conditional 3-way MI $I(Y; V \mid \text{leak})$ | `1.09861` nats (`ln 3`) | `1.09861` nats (`ln 3`) | **`0.86544` nats** |
| Pure canary lower bound $\ln(m) / I(Y; V \mid \text{leak})$ | `2.262` leaked traps | `2.680` leaked traps | **`4.233` leaked traps** |
| **Conditional ratio:** $I_{\text{can}} / D_{\text{KL,iv}}$ (exact / 5dp table) | `39.00x` (`39.0x`) | `104.40x` (`104.4x`) | **`181.27x` (`181.4x`)** |
| **Capacity ratio:** $I_{\text{can}} / C_{\text{iv}}$ (Shannon capacity) | `163.8x` | `431.3x` | **`741.6x`** |
| **Day-1 prior ratio:** $I_{\text{can}} / \text{EIG}_{\text{iv}}(1/m)$ | `515.2x` | `2,101.4x` | **`7,264.4x`** |
| **Unconditional Day-1 window EIG** ($W=3$, $\mathbb{E}[n_{\text{reg}}]=1.2$) | `0.94705` nats ($k^*=9$, `33.6x` KL) | `0.53781` nats ($k^*=9$, `51.1x` KL) | **`0.41762` nats** ($k^*=17$, **`87.5x`** KL / **`3,505.5x`** Day-1 EIG) |
| **Unconditional Steady window EIG** ($W=3$, $\mathbb{E}[n_{\text{reg}}]=3.6$) | `0.53115` nats ($k^*=10$, `18.9x` KL) | `0.24808` nats ($k^*=8$, `23.6x` KL) | **`0.19247` nats** ($k^*=15$, **`40.3x`** KL / **`1,615.6x`** Day-1 EIG) |
| Daily canary cost vs expected daily leak bleed | `0.010 V` vs `0.0450 V` | `0.010 V` vs `0.0300 V` | **`0.020 V` vs `0.0325 V`** |

Even in the most conservative steady-state regime (`n_reg = 3.6` regular memos competing in the 3-day window plus `careful_mole = True` deterrent weight `0.625` at $k^* = 15$), **one unplanted canary slot costs as much expected information as `40.3` KL-idealized interviews or `1,615.6` Day-1 prior-weighted interviews** - more than `5` entire `8`-action days of nonstop questioning!

---

## 4. Replay-Verified Lindley EIG Audit & Shapley Decomposition on `v1.4` Hard (`n = 30`, Part B)

To test how theoretical channel dominance translates into empirical agent behavior, `audit_v14_hard_replay()` replays all `30` post-hoc locked paired dev seeds `0-29` of OpenCode `gemini-4-carbon` (`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`) and `SolverPolicy` (`solver-hard-20261114-121126` + `solver-hard-seeds20to29`), computing exact Bayesian posteriors `sp.posterior()` immediately prior to every `plant_canary` and `interview` action (`0` score or accusation mismatches across all `60` replayed trajectories):

| Replay Trajectory Metric (`v1.4` Hard, Seeds `0-29`, $n = 30$) | OpenCode `gemini-4-carbon` | `SolverPolicy` Reference | Ratio / Paired Gap |
|---|---:|---:|---:|
| Mean episode score (`95%` bootstrap CI) | `0.322 +/- 0.199` | `0.499 +/- 0.119` | Raw gap **`5.30 V`**, LA gap **`4.19 V`** |
| Active episode days / canary slot capacity (`2/day`) | `403` days / `806` slots | `318` days / `636` slots | Gemini runs `+85` extra days (`+2.83 d/ep`) |
| Valid `plant_canary` actions (`canaries_per_episode`) | **`254`** (`8.47/ep`, `1` failed) | **`424`** (`14.13/ep`, `0` failed) | **`-170` missing canaries** (`31.5%` vs `66.7%` cap) |
| Total investigative actions (`ok = True`) | `2,971` (`99.03/ep`) | `1,256` (`41.87/ep`) | Gemini spends `2.37x` more actions |
| `interview` calls (`ok` / total) | **`2,039` / `2,041`** (`68.03/ep`) | **`0` / `0`** (`0.00/ep`) | `1,503` interviews on `242` of the `303` under-planted days |
| Mean recipients $k$ / `careful_mole` weight per canary | `10.27` / `0.7432` | `9.49` / `0.7627` | Near-identical sizing (`DIFFICULTY.md` W1) |
| Mean posterior mass covered $\sum_{e \in \text{asg}} p(e)$ | `0.7702` | `0.5635` | Solver splits top mass symmetrically |
| Mean conditional partition entropy $H_{\text{part}}$ (`%` of $\ln 3$) | `1.00218` nats (`91.22%`) | `1.04760` nats (`95.36%`) | `+4.13 pp` partition balance in Solver |
| Mean conditional canary MI given leak (`%` of `0.86544`) | `0.78531` nats (`90.74%`) | `0.82267` nats (`95.06%`) | `+4.32 pp` conditional MI efficiency |
| **3-day windowed EIG per canary** ($\bar{I}_{\text{can}}$) | **`0.26611` nats** | **`0.30743` nats** | Gemini achieves **`86.56%`** per-canary EIG |
| **Total 3-day canary EIG across 30 episodes** | **`67.5912` nats** (`2.2530/ep`) | **`130.3512` nats** (`4.3450/ep`) | **`-62.7601` nats deficit** (`-2.0920/ep`) |
| **Total EIG from all `2,039` valid interviews** | **`1.1077` nats** (`0.0369/ep`) | `0.0000` nats | `0.000543` nats/iv (= `4.16` canaries total!) |
| **Canary EIG per investigative action** | **`0.02275` nats/act** | **`0.10378` nats/act** | **`SolverPolicy` is `4.56x` more efficient/action** |
| **Canary EIG per active day** | **`0.16772` nats/day** | **`0.40991` nats/day** | **`SolverPolicy` is `2.44x` faster/day** |

### Exact Two-Factor Shapley and Oaxaca Decomposition of the `62.76`-Nat & `3.39 V` Deficit

Let $N_S = 424$, $N_G = 254$ denote total canaries planted across the `30` paired episodes, and let $\bar{I}_S = 0.307432$, $\bar{I}_G = 0.266107$ denote mean 3-day Lindley EIG per canary. Total active canary EIG satisfies $E_S - E_G = N_S \bar{I}_S - N_G \bar{I}_G = \mathbf{62.76005\text{ nats}}$, which decomposes exactly without residual into **quantity (slot crowding)** and **quality (per-canary partition design)** under both the symmetric two-player **Shapley midpoint** and **Oaxaca solver-reference** decompositions:

$$\Delta E_{\text{total}} = \underbrace{(N_S - N_G)\,\frac{\bar{I}_S + \bar{I}_G}{2}}_{\text{Shapley Slot Crowding: } 48.7508\text{ nats }(77.68\%)} + \underbrace{\frac{N_S + N_G}{2}\,(\bar{I}_S - \bar{I}_G)}_{\text{Shapley Partition Design: } 14.0092\text{ nats }(22.32\%)}.$$

Mapping these exact information shares onto the **`3.3898 V` (`3.39 V`) commitment-isolation loss** from `results/failure_analysis_v1.4.json` (`9/29` un-isolated accusations on `seeds [3, 5, 7, 8, 14, 15, 18, 20, 23]`, where `gemini-4-carbon` averaged only `9.11` canaries and `2.3094` nats vs `SolverPolicy`'s `17.33` canaries and `5.2072` nats while burning `71.56` interviews/episode):

| Decomposition Method | Slot Crowding EIG (`N_S - N_G = 170`) | Partition Design EIG (`I_S - I_G = 0.0413`) | Crowding Share / Attributed `3.39 V` | Partition Share / Attributed `3.39 V` |
|---|---:|---:|---:|---:|
| **Shapley Symmetric Midpoint** | **`48.7508` nats** | **`14.0092` nats** | **`77.68%` (`2.63 V`)** | **`22.32%` (`0.76 V`)** |
| **Oaxaca (`SolverPolicy` Rate Reference)** | **`52.2635` nats** | **`10.4966` nats** | **`83.28%` (`2.82 V`)** | **`16.72%` (`0.57 V`)** |

This decomposition reconciles `docs/DIFFICULTY.md` (W1) and `docs/reports/failure_analysis_v1.4.md` quantitatively:
- **Primary bottleneck (`77.7%` Shapley / `83.3%` Oaxaca = `2.63-2.82 V`):** `gemini-4-carbon` understands `plant_canary` (`254/254` valid traps use all `3` variant labels with `91.2%` partition entropy efficiency), but wastes `2,041` actions on a Blackwell-dominated `0.000543`-nat/call `interview` channel that crowds out `170` canary slots (`1.1077` nats gained from `2,039` interviews vs **`48.75` nats lost** from `170` crowded-out canaries - a **`44.0 : 1` negative information trade**!).
- **Secondary bottleneck (`22.3%` Shapley / `16.7%` Oaxaca = `0.57-0.76 V`):** Even when `gemini-4-carbon` plants canaries, Klayman-Ha positive-test skew and over-covering already-low-probability suspects reduce per-canary EIG by `13.44%` (`0.26611` vs `0.30743` nats), motivating Proposal **P13.1** to amplify positive-test anchoring in the social bias layer.

---

## 5. Concrete Proposals for Silas (`v1.6` Social Bias Layer, Opt-In Canary Tiers, and Partition-Aware Mole)

Both proposals obey Canary's four hard engineering invariants: **zero unapproved edits to protected paths**, **strict conditional zero hidden mole leakage** ($I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$, preserving `SolverPolicy` posterior invariance), **frozen `v1.4` hash `a8f99c2537c91d72` byte-identity** when opt-in flags default to `False`, and **`SolverPolicy` catchability $\ge 85.0\%$** (`canary/forge/fitness.py`).

### Proposal P13.1: Positive-Test Binary Check Anchor (`gen_binary_check_anchor` in `canary/social/biases.py`)

- **Target Surface:** `canary/social/biases.py` (Zero protected paths touched; drop-in bias generator for `V16SocialProvider`).
- **Research Grounding:** Operationalizes **Klayman & Ha's (1987) positive-test heuristic** and **Nelson's (2005) diagnosticity-vs-EIG divergence**. While `P1.3` and `P6.2` tempt agents to substitute `interview` or `restrict_access` for `plant_canary`, **P13.1** targets the `22.3%` (`0.76 V`) *partition-design* margin directly: an institutional reviewer (`manager`, `lead`, `controller`, or `counsel`) posts a `#security-review` or email note suggesting that `plant_canary` drafts should use a "clean single-person (`k = 1`) or direct two-way (`1-vs-(k-1)`) confirmation copy" on the public focal suspect rather than "noisy three-way group splits."
- **Strict Zero-Leakage & Hygiene Guarantees (`audit_proposals_p13`):**
  - Consumes **only** `PublicDayFacts` (`ctx.facts`, `ctx.primary_suspect`, `ctx.secondary_suspect`, `ctx.seen_docs`), so $I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$ identically (`LLR = 0.0000` nats; `SolverPolicy` ignores social messages after decoy ID and loses `0.000 V`).
  - Verified **`24 / 24` (`100%`) lint & schema PASS** across `8` seeds (`0` `lint_text` errors, `0` `FORBIDDEN_SUBJECT_PREFIXES`, `0` employee IDs in subjects, `0` `DECOY_VOCAB` collisions, `0` decoy senders/mentions, `100%` `body[:110]` salience compliance).
- **Exact Quantitative EIG Degradation Induced by Binary / Confirmatory Anchoring (`n_reg = 3.0`):**

| Suspect Pool Size $m$ | Optimal 3-Way Recipients $k^*$ | Balanced 3-Way $\text{EIG}_3$ | Asymmetric `1-vs-(k*-1)` Binary EIG (% Loss) | Pinpoint `2`-Person Binary EIG (% Loss) | Confirmatory `1`-Person (`k=1`) EIG (% Loss) |
|---:|---:|---:|---:|---:|---:|
| **`m = 39`** (Day 1) | `15` | **`0.22249` nats** | `0.13972` nats (**`-37.20%`**) | `0.07556` nats (**`-66.04%`**) | `0.04057` nats (**`-81.76%`**) |
| **`m = 18`** (1st reg leak) | `10` | **`0.29175` nats** | `0.16831` nats (**`-42.31%`**) | `0.12885` nats (**`-55.84%`**) | `0.07032` nats (**`-75.90%`**) |
| **`m = 12`** (Mid-game) | `8` | **`0.31688` nats** | `0.17264` nats (**`-45.52%`**) | `0.16551` nats (**`-47.77%`**) | `0.09157` nats (**`-71.10%`**) |
| **`m = 6`** (Late-game) | `4` | **`0.33522` nats** | `0.22582` nats (**`-32.63%`**) | `0.23396` nats (**`-30.21%`**) | `0.13504` nats (**`-59.72%`**) |

### Proposal P13.2: Opt-In Variable-Cost Canary Alphabet Schedule (`v1.6` Core) and `partition_aware_sleeper_v14` Mole

- **Part P13.2a (Opt-In Core Proposal for Silas: `canary/rules.py`, `canary/env.py`, `canary/solver/policy.py`):** Add `variable_canary_cost: bool = False` (preserving frozen hash `a8f99c2537c91d72` when `False`). Under Chaloner & Verdinelli's (1995) cost-utility design principle, charge `canary_cost(d_variants)` convexly by distinct variant count $|L(\text{assignment})|$ (`0.005 V` for `binary_probe` $d=2$, `0.010 V` for `standard_ternary` $d=3$, `0.025 V` for `wide_pentanary` $d=5$):
  - **Cost-efficiency vs slot-capacity trade-off (`audit_proposals_p13`):** On `v1.6` hard (`n_reg = 3.0`), `binary_probe` ($d=2$, `0.49463` nats given leak) maximizes **EIG per `0.01 V` spent** (`0.3625` early / `0.4843` mid / `0.4997` endgame nats per `0.01 V` vs `0.2225` / `0.3169` / `0.3480` for $d=3$), whereas `wide_pentanary` ($d=5$, `1.34161` nats given leak) maximizes **EIG per scarce canary slot** (`0.2777` early / `0.4440` mid / **`0.5083` endgame nats/slot** at $m=5$, resolving a 5-suspect consistent set in a single leaked trap before late-game `0.0325 V/day` bleed forces a below-break-even gamble). `SolverPolicy` selects $(d^*, \text{asg}^*)$ maximizing $\text{EIG}(\text{asg}) - \lambda_V c(d)$, whereas uncalibrated LLMs either overspend `0.025 V` early or under-split in the endgame.
- **Part P13.2b (Zero-Protected-Path `MoleStrategy` JSON for `canary/mole/dsl.py` & `canary/forge/`):** Pair the channel-capacity analysis with `partition_aware_sleeper_v14`, a catchability-verified `MoleStrategy` that exploits Klayman-Ha pinpoint traps (`min_recipient_count <= 2` on Days `1..8` or `recent_low_recipient_docs >= 2` shortly after a leak) by diverting exfiltration onto wide `most_recipients` documents while framing restricted peers once restrictions begin:

```json
{
  "name": "partition_aware_sleeper_v14",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "none", "frame": "most_restricted_peer"}
    },
    {
      "if": [["recent_low_recipient_docs", ">=", 2], ["days_since_last_leak", "<=", 2]],
      "then": {"leak": "most_recipients", "frame": "random_peer"}
    },
    {
      "if": [["min_recipient_count", "<=", 2], ["day", "<=", 8]],
      "then": {"leak": "most_recipients", "frame": "random_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "random_peer"}
}
```

- **Live `canary.forge.fitness.evaluate` Verification (`v1.4` Hard, `seeds 2000-2029`, $n = 30$):**
  - `DEFAULT_STRATEGY` (`default_v0`): `SolverPolicy = 0.5663` (`solver_acc = 96.67% >= 85%`), `hinted_heuristic = 0.4330`, `heuristic = 0.1450`, `min_regret = +0.1333`, `mean_regret = +0.2773`, `feasible = True`.
  - `partition_aware_sleeper_v14`: `SolverPolicy = 0.5063` (**`solver_acc = 90.00% >= 85.0%`**, `feasible = True`), `hinted_heuristic = 0.3413`, `heuristic = 0.0023` (collapsing naive log/pinpoint heuristics by `-0.1427 V`), lifting **`min_regret` from `+0.1333` to `+0.1650` (`+23.8%`)** and **`mean_regret` from `+0.2773` to `+0.3345` (`+20.6%`)** with zero protected-path edits.

---

## 6. Reproducibility Commands (Zero API Calls, Deterministic CPU)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_blackwell_channel_capacity.py
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_research_deception.py --docs docs/research/13_blackwell_channel_capacity_and_eig.md --http --strict
/tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_audit_blackwell_channel_capacity.py tests/test_research_deception.py
```
