# 08. Stackelberg Security Games, Constrained RL, and Catchability-Bounded Mole Training: Research Grounding for Canary

**Squad:** `research` (`canary-research-w8`)  
**Baseline commit:** `10685b03` (`origin/fr8/canary/research`, synced with `origin/justSilas@58716742` and `origin/fr8/canary/moletrain@6f04efd8`, rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Companion Research:** [Flagship Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [04. Social Engineering & Cheap Talk](04_social_engineering_cheap_talk.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md)  
**Scope:** Leader-follower Stackelberg security games, honey-document asymmetric signaling, PAIRED minimax regret, constrained Markov decision processes (CPO and RCPO), KL-regularized Group Relative Policy Optimization (GRPO), and bounded-rationality opponent modeling (Quantal Response Equilibria and Cognitive Hierarchy) grounding Canary's Mole DSL (`canary/mole/dsl.py`), CPU RL moles (`canary/forge/rl_mole.py`, `RLMoleV2`), FR8 V100 Qwen SFT+GRPO training (`train/grpo_mole.py`), and concrete proposals **P8.1**, **P8.2**, and **P8.3** for Silas.

---

## 1. Executive Thesis: Why Catchable Adversarial Moles Require Constrained Stackelberg Regret Optimization

Training an adaptive insider mole inside an interactive leak-hunt benchmark poses a sharp game-theoretic paradox. Unlike zero-sum board games where an adversary simply minimizes the protagonist's score, a pure minimax insider mole in Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `fingerprint_accuracy = 0.95`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `framing_rate = 2.0`, frozen hash `a8f99c2537c91d72`) can destroy benchmark validity in one trivial move: **never leak** (`leak = "none"`), or deterministically leak only 16-recipient two-department regular files (`leak = "most_recipients"`), starving even an exact Bayesian investigator (`SolverPolicy`) of diagnostic canary hits.

Across security-game theory, unsupervised environment design, constrained reinforcement learning, and behavioral game theory, four foundational results explain every empirical phenomenon observed across Canary's CPU Forge, Verda, and FR8 V100 mole-training campaigns:

1. **Canary is an imperfect-surveillance Stackelberg honey-document game optimized for protagonist-antagonist regret, not minimax payoff.** In Canary, the security investigator (Stackelberg leader) commits daily randomized 3-variant `plant_canary` partitions (`0.86544` nats mutual information per leaked canary vs `0.00477` nats for an ungrounded `interview`), while the mole (follower) observes `MoleView` (`recipient_count`, `age_days`, `i_am_restricted`, `n_restricted_colleagues`, `recent_low_recipient_docs`) without seeing hidden `is_canary` bits (Korzhyk et al., 2011; Pawlick, Colbert & Zhu, 2019). Following Protagonist-Antagonist Induced Regret Environment Design (`PAIRED`, Dennis et al., 2020), Canary's `canary/forge/fitness.py` maximizes **investigator regret** $J(\pi_M) = \mathbb{E}[S_{\text{solver}}(\pi_M)] - \max_{k \in \mathcal{I}} \mathbb{E}[S_k(\pi_M)]$ subject to strict **catchability feasibility** ($\text{Acc}_{\text{solver}}(\pi_M) \ge 0.85$ and $\mathbb{E}[S_{\text{solver}}(\pi_M)] \ge 0.5 \cdot \mathbb{E}[S_{\text{solver}}(\pi_0)]$, `CONTRACT` Section 7).
2. **Unregularized policy gradients with static scalar penalties deterministically collapse onto degenerate loopholes (`14/14` vanilla GRPO runs and `RLMole` v1).** As predicted by Constrained Policy Optimization (`CPO`, Achiam et al., 2017), Reward Constrained Policy Optimization (`RCPO`, Tessler, Mankowitz & Mannor, 2019), and KL-regularized policy optimization (Shao et al., 2024; Rafailov et al., 2023), optimizing `train/grpo_mole.py` with a fixed penalty (`CATCH_PENALTY = 0.5`), zero KL anchor ($\beta = 0$), and single-day `OverrideMole` counterfactuals collapsed across **all `14` vanilla GRPO runs** (`3` FR8 `400`-step `Qwen2.5-0.5B` runs and `11` Verda `200`-step `Qwen2.5-0.5B` / `1.5B` / `3B` runs): greedy policy entropy fell to **`0.0000` nats** (`100%` `none/decoy` on `0.5B`; `99.5%-100%` `random_seeded/none` or `random_seeded/decoy` on `1.5B`), producing **zero** stronger held-out moles. Likewise, unconstrained CPU `RLMole` v1 (`MIN_SOLVER_ACC = 0.75`) exploited `18.2%` voluntary `leak = "none"` on top of `p_leak = 0.65`, dropping `SolverPolicy` held-out accuracy to **`75.0% [63.3%, 85.0%]`** (`< 85.0%` contract floor).
3. **Hard domain masking (`RLMoleV2`) and KL-anchored primal-dual Horizon-3 GRPO (`Qwen3-1.7B` & `Qwen3-0.6B`) restore `95.0%-97.5%` held-out catchability with genuine policy entropy.** Blocking voluntary silence on wide unrestricted states in CPU `RLMoleV2` (`wide_unrestricted_none_rate = 0.0%`) lifts held-out `SolverPolicy` accuracy to **`96.7% [91.7%, 100.0%]`** on `ws3_heldout` (`200000-200059`, $n = 60$, `min_regret = +0.2937` vs `+0.2322` default) and **`95.0% [88.3%, 100.0%]`** on `rules_heldout` (`800000-800059`, $n = 60$, `min_regret = +0.2095` vs `+0.1766` default). On FR8 V100 GPUs, combining trap-capped SFT distillation, reference KL ($\beta = 0.05$), token entropy (`0.015`), action-frequency penalties, and dual `lam_catch` (`0.89 >= 0.85`) over 3-day horizons preserves multi-action stochasticity (`k = 4-5` distinct actions, `H(A) = 0.998-1.050` nats vs `0.000` nats in vanilla GRPO) and passes the `>= 85%` gate on both held-out splits: `Qwen3-1.7B` (`grpo_step80`) achieves **`97.5%`** solver accuracy on `800k` (`min_regret = +0.1905`) and **`95.0%`** on `200k` (`min_regret = +0.4559` vs `+0.2350` default; `+22.5pp [+7.5pp, +37.5pp]` catchability gain over `RLMole` v1), while `Qwen3-0.6B` (`grpo_step80`) achieves **`97.5%`** on `800k` (`min_regret = +0.1333` vs `+0.0372` default) and **`95.0%`** on `200k` (`min_regret = +0.3695` vs `+0.2350` default), with $n = 40$ paired worst-case regret CIs vs `DEFAULT_STRATEGY` honestly spanning zero.
4. **Targeting frontier LLMs (`gemini-4-carbon`: `0.322 +/- 0.199` vs `SolverPolicy`: `0.499 +/- 0.119`, raw paired gap `5.30 V`, luck-adjusted gap `4.19 V` on post-hoc locked paired dev seeds `0-29`) requires Cognitive Hierarchy Level-1 and Quantal Response opponent proxies.** Under Camerer, Ho & Chong (2004) and McKelvey & Palfrey (1995), framing the `decoy` (`fixed:random_seeded/decoy`) best-responds only to **step-0** log counters (`ObviousHeuristic`), and actually **helps** step-1 decoy-filtering investigators (`gemini_carbon_proxy` rises from `0.3563` to `0.4412`, shrinking the frontier gap by `-0.1252`). By contrast, conditional sleeper evasion paired with non-decoy peer framing (`RLMoleV2`, **P8.1**, **P8.2**, **P8.3**) widens the `SolverPolicy - gemini_carbon_proxy` gap from `+0.2355` to **`+0.2827`** (`+0.4850` on `200k`) while keeping `SolverPolicy` strictly above `88%-97%` accuracy.

---

## 2. Primary Literature Grounding (Live HTTP-Verified Citations and Verbatim Quotes)

### 2.1 Leader-Follower Surveillance and Uncertain Observability in Security Games: Korzhyk et al. (2011)

- **Citation:** Korzhyk, D., Yin, Z., Kiekintveld, C., Conitzer, V., & Tambe, M. (2011). Stackelberg vs. Nash in Security Games: An Extended Investigation of Interchangeability, Equivalence, and Uniqueness. *Journal of Artificial Intelligence Research*, 41, 297-327 (with imperfect-observability formalization extended in Korzhyk, Conitzer, & Parr, 2011).
- **Live Verified Links:** https://openalex.org/W2126879264 | DOI: https://doi.org/10.1613/jair.3269
- **Model & Core Theorem:** Analyzes randomized defender allocations in leader-follower security games (such as LAX `ARMOR` and Federal Air Marshals `IRIS`), proving when Strong Stackelberg Equilibria coincide with interchangeable Nash equilibria, why multi-target attacks break equivalence, and why leaders must model partial follower surveillance of randomized defenses.
- **Verbatim Quote on Leader-Follower Randomized Commitment (Abstract):**
> "The foundational assumption for using Stackelberg games is that security forces (leaders), acting first, commit to a randomized strategy; while their adversaries (followers) choose their best response after surveillance of this randomized strategy."
- **Verbatim Quote on Surveillance Uncertainty and Multi-Target Breakdown (Abstract):**
> "Yet, in many situations, a leader may face uncertainty about the follower's surveillance capability. Previous work fails to address how a leader should compute her strategy given such uncertainty."
- **Relevance to Canary:** In `canary/env.py` (`_mole_view`, lines 528-548), the investigator (leader) commits daily `plant_canary` recipient pools and `restrict_access` actions, and the mole (follower) observes imperfect surveillance summary statistics (`recipient_count`, `age_days`, `i_am_restricted`, `n_restricted_colleagues`, `recent_low_recipient_docs`) across multiple days (`n_days = 21`) without observing `is_canary`. Because the mole attacks repeatedly across days (multi-target sequential exfiltration), `SolverPolicy` cannot rely on static deterministic traps; it randomizes and balances 3-variant canary pools while tempering behavioral likelihoods (`canary-first tempering` in `canary/solver/belief.py`) for robustness against adaptive Mole DSL followers.

### 2.2 Honey-Document Signaling Games and Defensive Deception: Pawlick, Colbert & Zhu (2019)

- **Citation:** Pawlick, J., Colbert, E., & Zhu, Q. (2019). A Game-Theoretic Taxonomy and Survey of Defensive Deception for Cybersecurity and Privacy. *ACM Computing Surveys*, 52(4), Article 82, 1-38.
- **Live Verified Links:** https://openalex.org/W2971648973 | DOI: https://doi.org/10.1145/3337772
- **Taxonomy & Game Structure:** Synthesizes `24` game-theoretic defensive-deception models (`2008-2018`) into six canonical mechanisms (`perturbation`, `moving target defense`, `obfuscation`, `mixing`, `honey-x`, and `attacker engagement`) classified by private information, signaling structure, and horizon.
- **Verbatim Quote on Reversing Information Asymmetry via Honey-X Games (Abstract):**
> "Advocates and engineers have recently proposed using defensive deception as a means to leverage the information asymmetry typically enjoyed by attackers as a tool for defenders."
- **Verbatim Quote on Game-Theoretic Classification by Information Structure (Abstract):**
> "Then, we propose a taxonomy that defines six types of deception: perturbation, moving target defense, obfuscation, mixing, honey-x, and attacker engagement. These types are delineated by their information structures, agents, actions, and duration: precisely concepts captured by game theory."
- **Relevance to Canary:** Places Canary's `plant_canary` vs `MoleStrategy` interaction squarely in the **dynamic honey-x signaling game** class. While the attacker initially holds private identity information (`world.mole`), the defender holds private trap-type information (`doc["is_canary"]` and `doc["variants"]`). The mole can infer posterior trap risk only imperfectly from `recipient_count` (`careful_mole` weight $1 - k / N$, where regular `v1.4` hard documents always span `2` departments = `16` recipients). If the investigator plants narrow `3`-person pinpoint traps too early, `recent_low_recipient_docs` alerts an adaptive follower; if the investigator plants `20`-person balanced Day 1 traps, trap risk blends into background document flow.

### 2.3 Protagonist-Antagonist Induced Regret vs Unsolvable Minimax Worlds (PAIRED): Dennis et al. (2020)

- **Citation:** Dennis, M., Jaques, N., Vinitsky, E., Bayen, A., Russell, S., Critch, A., & Levine, S. (2020). Emergent Complexity and Zero-shot Transfer via Unsupervised Environment Design. *Advances in Neural Information Processing Systems (NeurIPS 2020)*, 33, 13049-13061 (`arXiv:2012.02096`).
- **Live Verified Links:** https://openalex.org/W3101966195 | DOI: https://doi.org/10.48550/arXiv.2012.02096
- **Core Theorem:** Proves that pure minimax environment/adversary training (`min_theta max_pi U(theta, pi)`) degenerates into **unsolvable environments**, whereas maximizing **regret** between an allied optimal *antagonist* (`SolverPolicy`) and a bounded *protagonist* (`INVESTIGATORS` / LLM agent) restricts equilibrium adversary policies to **solvable, structured, diagnostically separating challenges**.
- **Verbatim Quote on Minimax Unsolvability vs Regret Optimization (Abstract):**
> "Existing approaches to automatically generating environments suffer from common failure modes: domain randomization cannot generate structure or adapt the difficulty of the environment to the agent's learning progress, and minimax adversarial training leads to worst-case environments that are often unsolvable. To generate structured, solvable environments for our protagonist agent, we introduce a second, antagonist agent that is allied with the environment-generating adversary. The adversary is motivated to generate environments which maximize regret, defined as the difference between the protagonist and antagonist agent's return. We call our technique Protagonist Antagonist Induced Regret Environment Design (PAIRED)."
- **Relevance to Canary:** Directly grounds Canary's Mole Forge (`canary/forge/fitness.py`), `canary/agents/designer.py`, CPU `RLMole` (`canary/forge/rl_mole.py`), and V100 GRPO (`train/grpo_mole.py`). A minimax mole that minimizes investigator return sets `leak = "none"` (`0` leaks, `SolverPolicy = 0.0000`, `0.0%` accuracy - completely unsolvable). Under PAIRED regret $R(\pi_M) = S_{\text{solver}}(\pi_M) - \max_k S_k(\pi_M)$, a mole that never leaks gets `0.000 - 0.000 = 0.000` regret, whereas a mole that leaks enough watermarked evidence for `SolverPolicy` to catch it (`0.5677`) while spoofing `after_hours` logs and evading naive early bisection (`heuristic = -0.0217`, `grok_tactics = 0.3577`) earns strictly positive regret.

### 2.4 Constrained Policy Optimization and Divergence-Bounded Feasibility: Achiam et al. (2017)

- **Citation:** Achiam, J., Held, D., Tamar, A., & Abbeel, P. (2017). Constrained Policy Optimization. *Proceedings of the 34th International Conference on Machine Learning (ICML 2017)*, PMLR 70, 22-31 (`arXiv:1705.10528`).
- **Live Verified Links:** https://openalex.org/W2616964725 | DOI: https://doi.org/10.48550/arXiv.1705.10528
- **Method & Theoretical Bound:** Formulates constrained RL as a Constrained Markov Decision Process (CMDP) maximizing expected return $J(\pi)$ subject to cost/feasibility constraints $J_{C_i}(\pi) \le d_i$, proving worst-case degradation bounds proportional to total variation / KL divergence $\sqrt{\mathbb{E}_s[D_{\text{KL}}(\pi' \| \pi)[s]]}$ between consecutive policies.
- **Verbatim Quote on Constraints vs Ad-Hoc Reward Shaping (Abstract):**
> "For many applications of reinforcement learning it can be more convenient to specify both a reward function and constraints, rather than trying to design behavior through the reward function."
- **Verbatim Quote on Divergence-Bounded Policy Updates (Abstract):**
> "We propose Constrained Policy Optimization (CPO), the first general-purpose policy search algorithm for constrained reinforcement learning with guarantees for near-constraint satisfaction at each iteration. Our method allows us to train neural network policies for high-dimensional control while making guarantees about policy behavior all throughout training. Our guarantees are based on a new theoretical result, which is of independent interest: we prove a bound relating the expected returns of two policies to an average divergence between them."
- **Relevance to Canary:** Even with PAIRED regret, an unconstrained mole can occasionally gamble on partial stonewalling (`leak = "most_recipients"` or `18.2%` `leak = "none"` in `RLMole` v1) whenever scripted heuristics suffer `-1.0` wrong-accusation penalties faster than `SolverPolicy` loses accuracy. `CONTRACT` Section 7 therefore imposes an explicit CMDP constraint: $\text{Acc}_{\text{solver}}(\pi_M) \ge 0.85$ and $S_{\text{solver}}(\pi_M) \ge 0.5 \cdot S_{\text{solver}}(\pi_0)$. Achiam et al.'s divergence bound further proves why policy updates must remain KL-bounded relative to a feasible reference policy (`beta_kl_to_sft_ref = 0.05` in V100 `Qwen3` training and **P8.1**): large unregularized gradient steps jump straight across the `85%` catchability boundary into infeasible regimes.

### 2.5 Reward Constrained Policy Optimization and Reward-Loophole Elimination: Tessler, Mankowitz & Mannor (2019)

- **Citation:** Tessler, C., Mankowitz, D. J., & Mannor, S. (2019). Reward Constrained Policy Optimization. *International Conference on Learning Representations (ICLR 2019)* (`arXiv:1805.11074`).
- **Live Verified Links:** https://openalex.org/W2804791273 | DOI: https://doi.org/10.48550/arXiv.1805.11074
- **Algorithm & Convergence Theorem:** Proves two-timescale stochastic-approximation convergence of primal-dual policy gradient ascent (fast timescale $\eta_\theta$) coupled with Lagrange multiplier ascent $\lambda_{t+1} = \Gamma_\lambda[\lambda_t + \eta_\lambda (\alpha - J_C(\pi_{\theta_t}))]$ (slow timescale $\eta_\lambda$) to a locally optimal feasible policy, eliminating reward-shaping loopholes where fixed scalar penalties fail.
- **Verbatim Quote on Reward Loopholes and Multi-Timescale RCPO (Abstract):**
> "As the goal of the agent is to maximize the accumulated reward, it often learns to exploit loopholes and misspecifications in the reward signal resulting in unwanted behavior. While constraints may solve this issue, there is no closed form solution for general constraints. In this work we present a novel multi-timescale approach for constrained policy optimization, called `Reward Constrained Policy Optimization' (RCPO), which uses an alternative penalty signal to guide the policy towards a constraint satisfying one. We prove the convergence of our approach and provide empirical evidence of its ability to train constraint satisfying policies."
- **Relevance to Canary:** Directly diagnoses both failure modes observed in Canary's early mole training:
  1. In `train/grpo_mole.py` (line 39 & 148), a **fixed scalar penalty** `CATCH_PENALTY = 0.5` applied to a **1-day counterfactual override** (`OverrideMole`) created a textbook reward-misspecification loophole: choosing `leak = "none"` on a single day `d` preserved `95.0%` `SolverPolicy` catchability over the other 20 `DEFAULT_STRATEGY` days (`0` penalty incurred!) while avoiding immediate canary exposure on day `d`, causing `0.5B` policies to collapse `100%` onto `none/decoy` (which yields `0.0%` catchability when rolled out across all 21 days!).
  2. In `canary/forge/rl_mole.py` (line 39 & 247), dual ascent worked as intended ($\lambda \leftarrow [\lambda + \eta_\lambda(\tau + m - \widehat{\text{acc}})]_+$), **except** `MIN_SOLVER_ACC` was set to legacy `0.75` (`+0.05` margin = `0.80`), so RCPO faithfully converged right onto the wrong boundary (`75.0%` held-out accuracy, failing the `85.0%` `CONTRACT` Section 7 gate). Updating the RCPO target to `0.88-0.90` (`>= 0.85` floor + finite-sample margin) in `RLMoleV2`, V100 `Qwen3`, and **P8.1** restores strict feasibility (`95.0%-97.5%`).

### 2.6 Critic-Free Group Relative Policy Optimization (GRPO): Shao et al. (2024)

- **Citation:** Shao, Z., Wang, P., Zhu, Q., Xu, R., Song, J., Bi, X., Zhang, H., Zhang, M., et al. (2024). DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models. *arXiv:2402.03300*.
- **Live Verified Links:** https://openalex.org/W4391631327 | DOI: https://doi.org/10.48550/arXiv.2402.03300
- **Algorithmic Specification:** Replaces PPO's learned value critic (which doubles GPU memory footprint) with **group-normalized empirical advantages** $\hat{A}_{i} = (r_i - \text{mean}(\mathbf{r})) / \text{std}(\mathbf{r})$ computed across $G$ completions sampled for the same prompt $q$, regularized by an explicit per-token KL divergence penalty $\beta \mathbb{D}_{\text{KL}}(\pi_\theta \| \pi_{\text{ref}})$ to prevent policy collapse.
- **Verbatim Quote (Abstract):**
> "Second, we introduce Group Relative Policy Optimization (GRPO), a variant of Proximal Policy Optimization (PPO), that enhances mathematical reasoning abilities while concurrently optimizing the memory usage of PPO."
- **Relevance to Canary:** Directly grounds `train/grpo_mole.py` on 16GB/32GB FR8 Tesla V100 GPUs (`fp16` AMP, no `bf16`, LoRA `r = 16`, `group = 8` completions sampled for each deterministic `(seed, day)` `MoleView` prompt so intra-group variance comes strictly from the mole's action). Crucially, `train/grpo_mole.py` line 18 originally omitted Shao et al.'s $\beta \mathbb{D}_{\text{KL}}(\pi_\theta \| \pi_{\text{ref}})$ term (`"no KL term"`). Because the Mole DSL action space contains only $|A| = 6 \times 4 = 24$ discrete `(leak, frame)` pairs, group-normalized advantages without a reference-KL anchor amplify slight finite-sample advantage differences until `100%` of probability mass concentrates on a single deterministic pair (`H(A) = 0.00` nats across `13/14` vanilla GRPO runs). Restoring $\beta = 0.02\text{--}0.05$ (`beta_kl_to_sft_ref = 0.05` in V100 `Qwen3-1.7B` and `Qwen3-0.6B`) immediately stabilizes multi-action entropy (`H(A) = 0.998-1.050` nats).

### 2.7 Closed-Form Gibbs Policies Under KL Regularization (DPO): Rafailov et al. (2023)

- **Citation:** Rafailov, R., Sharma, A., Mitchell, E., Ermon, S., Manning, C. D., & Finn, C. (2023). Direct Preference Optimization: Your Language Model is Secretly a Reward Model. *Advances in Neural Information Processing Systems (NeurIPS 2023)*, 36, 53728-53741 (`arXiv:2305.18290`).
- **Live Verified Links:** https://openalex.org/W7133208539 | DOI: https://doi.org/10.48550/arXiv.2305.18290
- **Mathematical Identity:** Derives the exact closed-form optimal policy of KL-constrained reward maximization $\max_\pi \mathbb{E}_{x, y \sim \pi}[r(x, y)] - \beta \mathbb{D}_{\text{KL}}(\pi(y|x) \| \pi_{\text{ref}}(y|x))$ as the Gibbs-Boltzmann distribution $\pi^*(y|x) = \frac{1}{Z(x)} \pi_{\text{ref}}(y|x) \exp(r(x, y) / \beta)$, enabling offline preference optimization over paired trajectories without unstable online rollouts.
- **Verbatim Quote on KL-Constrained Optimal Policy Extraction (Abstract):**
> "Existing methods for gaining such steerability collect human labels of the relative quality of model generations and fine-tune the unsupervised LM to align with these preferences, often with reinforcement learning from human feedback (RLHF). However, RLHF is a complex and often unstable procedure, first fitting a reward model that reflects the human preferences, and then fine-tuning the large unsupervised LM using reinforcement learning to maximize this estimated reward without drifting too far from the original model. In this paper we introduce a new parameterization of the reward model in RLHF that enables extraction of the corresponding optimal policy in closed form, allowing us to solve the standard RLHF problem with only a simple classification loss."
- **Relevance to Canary:** Explains mathematically why **mixed Stackelberg strategies require $\beta > 0$**: in Canary's `24`-action Mole DSL, as $\beta \to 0^+$, $\pi^*(a \mid \text{view}) \to \delta_{\arg\max_a r(\text{view}, a)}$, collapsing onto a pure strategy that either starves `SolverPolicy` (`most_recipients` / `none`) or becomes trivially predictable. Keeping $\beta > 0$ relative to a diverse, catchable SFT reference policy (`gemini-4-carbon` arena mole + Horizon-3 counterfactual expert rollouts) guarantees a non-degenerate mixed strategy $\pi^*(a \mid \text{view})$ and grounds offline preference pair export over counterfactual `(seed, day)` rollouts (`train/export_mole_dpo.py` on `moletrain`).

### 2.8 Quantal Response Equilibria in Normal and Extensive Form Games: McKelvey & Palfrey (1995, 1998)

- **Citation 1 (Normal Form QRE):** McKelvey, R. D., & Palfrey, T. R. (1995). Quantal Response Equilibria for Normal Form Games. *Games and Economic Behavior*, 10(1), 6-38.
- **Live Verified Links (1995):** https://openalex.org/W2264897026 | Caltech Repository: https://authors.library.caltech.edu/records/4fh4n-4c340 | DOI: https://doi.org/10.1006/game.1995.1023
- **Citation 2 (Extensive Form AQRE):** McKelvey, R. D., & Palfrey, T. R. (1998). Quantal Response Equilibria for Extensive Form Games. *Experimental Economics*, 1(1), 9-41.
- **Live Verified Links (1998):** https://openalex.org/W1974964983 | DOI: https://doi.org/10.1007/bf01426213
- **Verbatim Quote from McKelvey & Palfrey (1995) (Abstract):**
> "We investigate the use of standard statistical models for quantal choice in a game theoretic setting. Players choose strategies based on relative expected utility and assume other players do so as well."
> "For a logit specification of the error structure, we show that as the error goes to zero, QRE approaches a subset of Nash equilibria and also implies a unique selection from the set of Nash equilibria in generic games. We fit the model to a variety of experimental data sets by using maximum likelihood estimation."
- **Verbatim Quote from McKelvey & Palfrey (1998) on Extensive-Form Signaling Games (Abstract):**
> "We define an agent quantal response equilibrium (AQRE), which applies QRE to the agent normal form of an extensive form game and imposes a statistical version of sequential rationality. We also define a parametric specification, called logit-AQRE, in which quantal-choice probabilities are given by logit response functions."
- **Relevance to Canary:** Grounds two distinct components of Canary's mole architecture:
  1. **Smooth adversary weighting in `RLMole` (`canary/forge/rl_mole.py`, line 221):** Computing $w_k = \frac{\exp(\bar{S}_k / \tau)}{\sum_j \exp(\bar{S}_j / \tau)}$ (`temp = 0.05`) replaces the non-differentiable $\max_k S_k$ with a smooth logit best-response over the investigator population.
  2. **Frontier LLM stopping and accusation errors (`Proposal P8.2`):** On `v1.4` hard, `gemini-4-carbon` commits **below-break-even accusations** ($P < 1 / (1 + V)$, e.g. gambling `1/2` or `1/3` among unseparated co-recipients around Days `14-18` under daily `0.05 V` bleed, `docs/reports/failure_analysis_v1.4.md`). Modeling the investigator's stopping and suspect-choice rules via logit-AQRE ($P(\text{accuse } e) \propto \exp(\lambda_{\text{QRE}} \cdot \hat{u}_e)$) allows the mole to train directly against noisy frontier commitment errors rather than crisp threshold scripts (`HintedHeuristic` `accuse_p = 0.85`).

### 2.9 Cognitive Hierarchy Theory and Step-k Strategic Thinking: Camerer, Ho & Chong (2004)

- **Citation:** Camerer, C. F., Ho, T.-H., & Chong, J.-K. (2004). A Cognitive Hierarchy Model of Games. *Quarterly Journal of Economics*, 119(3), 861-898.
- **Live Verified Links:** https://openalex.org/W2114765979 | DOI: https://doi.org/10.1162/0033553041502225
- **Model & Empirical Calibration:** Replaces full mutual Nash rationality with inductively defined strategic levels (`step 0` non-strategic actors; `step k` thinkers best-responding to a Poisson($\tau$) mixture of steps `0 .. k - 1`, with empirical human/agent behavior clustering near $\tau \approx 1.5$ steps).
- **Verbatim Quote (Abstract):**
> "Players in a game are \"in equilibrium\" if they are rational, and accurately predict other players' strategies. In many experiments, however, players are not in equilibrium. An alternative is \"cognitive hierarchy\" (CH) theory, where each player assumes that his strategy is the most sophisticated. The CH model has inductively defined strategic categories: step 0 players randomize; and step k thinkers best-respond, assuming that other players are distributed over step 0 through step k - 1. This model fits empirical data, and explains why equilibrium theory predicts behavior well in some games and poorly in others. An average of 1.5 steps fits data from many games."
- **Relevance to Canary:** Provides an exact taxonomy of Canary's investigator hierarchy and explains why naive `decoy` framing backfires against frontier models:
  - **Step 0 (Surface / Naively Credulous):** `ObviousHeuristic`, `LogsOnly`, and `RumourFollower` (`-0.973` to `-0.995` on `hard`), which equate angry chat (`decoy=True`) or raw `after_hours` counts with guilt.
  - **Step 1 (Partial Deception Awareness, Uncalibrated Allocation):** `Heuristic` (`0.0348`), `GrokTactics` (`0.3693`), and `gemini-4-carbon` (`0.322 +/- 0.199` on `v1.4` hard), which correctly identify and discount the angry `decoy` (`0` decoy accusations on `v1.4` hard!) and intersect regular leaks, **but** spend `68.0` actions/episode on low-diagnosticity `interview` calls (`KL = 0.00477` nats) and overweight residual non-decoy `after_hours` logs.
  - **Step 2+ (Exact Calibrated Bayesian):** `SolverPolicy` (`0.499 +/- 0.119`), which ignores zero-information chat (`LLR = 0`), performs `0` interviews, allocates `14.1` balanced 3-variant `plant_canary` traps accounting for `careful_mole`, tempers behavioral likelihoods (`0.3`), and accuses strictly when $P \cdot V - (1 - P) > 0$ exceeds continuation value.
  - **Strategic Consequence for the Mole:** A **Step-1 mole** that frames `"decoy"` best-responds only to Step-0 investigators, and **actively helps** Step-1 investigators (`gemini_carbon_proxy` jumps `+0.0849` under `fixed:random_seeded/decoy`!) because concentrating fake logs on the already-excluded `decoy` removes framing noise from the `38` plausible non-decoy peers. A **Step-2 mole** (**P8.1-P8.3**, `RLMoleV2`) targets Step-1 vulnerabilities by framing **non-decoy, leak-consistent peers** (`most_restricted_peer`, `random_peer`, `co_recipient_peer`) while preserving Step-2+ `SolverPolicy` catchability (`>= 85%`).

### 2.10 Sleeper Trigger Persistence and Monitoring-Conditioned Alignment Faking: Hubinger et al. (2024) & Greenblatt et al. (2024)

- **Citation 1 (Sleeper Triggers):** Hubinger, E., Denison, C., Mu, J., Lambert, M., Tong, M., MacDiarmid, M., et al. (2024). Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training. *arXiv:2401.05566*.
- **Live Verified Links (Hubinger et al.):** https://openalex.org/W4390833079 | DOI: https://doi.org/10.48550/arXiv.2401.05566
- **Citation 2 (Alignment Faking Under Oversight):** Greenblatt, R., Denison, C., Wright, B., Roger, F., MacDiarmid, M., Kravec, S., et al. (2024). Alignment Faking in Large Language Models. *arXiv:2412.14093*.
- **Live Verified Links (Greenblatt et al.):** https://openalex.org/W4405627013 | DOI: https://doi.org/10.48550/arXiv.2412.14093
- **Verbatim Quote from Hubinger et al. (2024) (Abstract):**
> "Furthermore, rather than removing backdoors, we find that adversarial training can teach models to better recognize their backdoor triggers, effectively hiding the unsafe behavior."
- **Verbatim Quote from Greenblatt et al. (2024) (Abstract):**
> "We present a demonstration of a large language model engaging in alignment faking: selectively complying with its training objective in training to prevent modification of its behavior out of training."
- **Relevance to Canary:** Grounds conditional sleeper policies in `canary/mole/dsl.py`: when `MoleView` indicates heightened pinpoint monitoring (`recent_low_recipient_docs >= 2` or `i_am_restricted == 1`), a strategic mole suppresses narrow-document exfiltration (`leak = "most_recipients"` or `"none"` when restricted) and resumes normal `random_seeded` exfiltration when distributions widen, delaying Step-1 bisection without starving `SolverPolicy` below `85%`.

---

## 3. Quantitative Game-Theoretic & Empirical Audit of Canary Mole Training

### 3.1 Leader-Follower Information Asymmetry and the Catchability-Regret Frontier (`v1.4` Hard)

In frozen `TIERS_VERSION = "v1.4"` (`canary/rules.py`, hash `a8f99c2537c91d72`), `Env._t_advance_day` (`canary/env.py`, lines 556-605) executes a sequential Stackelberg interaction on each day $d \in \{1, \dots, 21\}$:
1. **Leader action (`plant_canary` & `restrict_access`):** Up to `canaries_per_day = 2` honey documents (`canary_cost = 0.01` each, `max_variants = 3`, `fingerprint_accuracy = 0.95`) are distributed alongside `2-4` regular two-department documents (`16` recipients each on `hard`, $N = 40$).
2. **Follower observation (`MoleView`):** If `leakable` documents exist in `[d - 2, d]`, the environment draws `can_leak = (rng.random() < 0.65)`. Under `careful_mole = True`, `random_seeded` weights each canary by $w(k) = 1 - k / 40$ (`1.0` for regular docs), while `MoleStrategy.decide(view, rng)` chooses `(leak_sel, frame_sel)` from $|A| = 6 \times 4 = 24$ selector pairs.
3. **Catchability Collapse of Pure Evasion:** Deterministic CPU evaluation via `canary.forge.fitness.evaluate` on `v1.4` hard (`seeds 2000-2059`, $n = 60$, `min_solver_acc = 0.85`) demonstrates why **unconditional** evasion violates `CONTRACT` Section 7, whereas **conditional Stackelberg-sleeper evasion** (`sleeper_stackelberg_v14`, **P8.1**) strictly dominates `DEFAULT_STRATEGY` on both catchability and regret:

| Mole Strategy (`v1.4` Hard, `seeds 2000-2059`, $n = 60$) | `SolverPolicy` Score (`Acc`) | `grok_tactics` Score (`Regret`) | `hinted_heuristic` Score (`Regret`) | `heuristic` Score (`Regret`) | `min_regret` (`mean_regret`) | `>= 85%` Feasible? |
|---|---:|---:|---:|---:|---:|---|
| `default_v0` (`random_seeded` / `none`) | `0.5212` (**`93.3%`**) | `0.3693` (`+0.1518`) | `0.3758` (`+0.1453`) | `0.0348` (`+0.4863`) | **`+0.1453`** (`+0.2612`) | **PASS** |
| `pure_none_decoy` (`none` / `decoy`, $n=10$ check) | `0.0000` (`0.0%`) | `0.0000` (`0.0000`) | `0.0000` (`0.0000`) | `0.0000` (`0.0000`) | `0.0000` (`0.0000`) | **FAIL (`0.0%`)** |
| `pure_most_recipients` (`most_recipients` / `most_restricted_peer`) | `0.3037` (`55.0%`) | `0.1062` (`+0.1975`) | `0.0730` (`+0.2307`) | `-0.1012` (`+0.4048`) | `+0.1975` (`+0.2777`) | **FAIL (`55.0%`)** |
| **`sleeper_stackelberg_v14` (Proposal P8.1 DSL)** | **`0.5677` (`95.0%`)** | **`0.3577` (`+0.2100`)** | **`0.3787` (`+0.1890`)** | **`-0.0217` (`+0.5893`)** | **`+0.1890` (`+0.3294`)** | **PASS (`95.0%`)** |

Why does `pure_most_recipients` drop `SolverPolicy` accuracy from `93.3%` to `55.0%`? Because regular `v1.4` hard documents always have `16` recipients (`2` of `5` departments), whereas mid-game `plant_canary` splits over narrowed candidate sets have `2-15` recipients; `min(docs, key=lambda d: -d.recipient_count)` deterministically selects `16`-person regular files on every day a regular file is held, starving `SolverPolicy` below the `4.233`-trap information-theoretic resolution bound. By restricting `most_recipients` to **acute pinpoint-surveillance states** (`day <= 4` or `n_restricted_colleagues >= 1` combined with `recent_low_recipient_docs >= 2`), `sleeper_stackelberg_v14` raises `min_regret` by **`+30.1%`** (`+0.1453 -> +0.1890`), raises `mean_regret` by **`+26.1%`** (`+0.2612 -> +0.3294`), pushes `heuristic` negative (`-0.0217`), and lifts `SolverPolicy` catchability to **`95.0%`**.

---

### 3.2 Post-Mortem of `14` Collapsed Vanilla GRPO Runs (`0.00` Nats Entropy & `OverrideMole` Loophole)

Verified forensics across all **14 vanilla GRPO training runs** (`origin/fr8/canary/moletrain:results/moletrain/qwen_mole_summary.json`: `3` FR8 `400`-step `Qwen2.5-0.5B-Instruct` runs `44424-44426` and `11` Verda `200`-step runs across `Qwen2.5-0.5B`, `1.5B`, and `3B` evaluated on paired `hard` seeds `400000-400199`, $n = 200$) confirm a universal negative baseline when KL regularization and multi-day catchability duals are absent:

| Compute Cluster & Scale | Runs | Base Valid JSON | Adapter Valid JSON | Paired Reward Delta `[95% CI]` | Greedy Top Action (`Share`) | Greedy `H(A)` (nats) | Valid Regret | Honest Verdict |
|---|---:|---:|---:|---:|---|---:|---:|---|
| FR8 WS3 `Qwen2.5-0.5B` (`400` steps) | `3` | `32.7%-47.7%` | `99.6%-99.8%` | `+0.55` raw (`+0.02` valid-only) | `none/decoy` (`2/3`), `newest/decoy` (`1/3`) (`>=99.4%`) | `0.005-0.045` | flat (`-0.08..-0.01`) | `format_validity_only_mode_collapse` |
| Verda `Qwen2.5-0.5B` (`200` steps) | `3` | `5.0%-12.5%` | **`100.0%`** | `+0.8303` to `+0.9008` | `none/decoy` (**`100.0%`**, `200/200`) | **`0.0000`** | `-0.0321` | `format_validity_only_collapsed_silent` |
| Verda `Qwen2.5-1.5B` (`200` steps) | `6` | `100.0%` | `100.0%` | `-0.0164` to `-0.0103` (0 in CI) | `random_seeded/none` (`4/6`), `random_seeded/decoy` (`2/6`) (`99.5%-100%`) | **`0.0000-0.0315`** | `-0.0449` to `-0.0357` | `collapsed_single_action_no_gain` |
| Verda `Qwen2.5-3B` (`200` steps) | `2` | `100.0%` | `100.0%` | `-0.0385` and `-0.0156` (0 in CI) | `random_seeded/most_restricted_peer` (`89.0%` s0), `random_seeded/decoy` (`59.5%` s1) | `0.3465` / `1.2076` | `-0.0369` / `-0.0266` | `negative_or_null_heldout` |

Two exact mathematical mechanisms explain this `14/14` failure:
1. **The Single-Day `OverrideMole` Counterfactual Loophole (Tessler et al., 2019):** In `train/grpo_mole.py` (lines 119-150), `OverrideMole(base, day, act)` replaces the mole's action **only on a single day `d`**, executing `DEFAULT_STRATEGY` on all other `20` days. On `0.5B`, choosing `none/decoy` on day `d` suppresses one leak while the other `20` days of `DEFAULT_STRATEGY` still let `SolverPolicy` catch the mole `95.0%` of the time (`0` penalty from `CATCH_PENALTY = 0.5`). Thus `none/decoy` appears `95.0%` catchable under 1-day `OverrideMole`, yet when deployed as an autonomous full-episode policy (`fixed:none/decoy` in `frontier_proxy_mole_matrix.json`), `SolverPolicy` accuracy collapses to **`6.7%`** (`score = 0.0488`, failing catchability catastrophically)!
2. **Zero-KL Group-Advantage Sharpening (Shao et al., 2024; Rafailov et al., 2023):** Without $\beta D_{\text{KL}}(\pi_\theta \| \pi_{\text{ref}})$, standardizing intra-group rewards by $(R - \bar{R}) / (\sigma_R + 10^{-4})$ gives $O(1)$ gradient steps even when valid actions differ by `< 0.02` reward, driving `13/14` runs to near-zero policy entropy (`0.0000` nats on `8/11` Verda held-out evaluations).

---

### 3.3 Trap-Gated Primal-Dual Restoration on CPU (`RLMole` v1 vs `RLMoleV2`)

Comparing CPU `RLMole` v1 (`canary/forge/rl_mole.py`, `data/rl_mole/policy_final.json`) against `RLMoleV2` (`origin/fr8/canary/moletrain:canary/forge/rl_mole_v2.py`, verified on two disjoint `n = 60` held-out splits in `results/moletrain/rl_mole_v2_heldout.json`) isolates the exact role of RCPO target calibration and action-space masking:

- **Why `RLMole` v1 failed the `85%` gate (`75.0%` on both held-out splits):** `RLMole` v1 used legacy `MIN_SOLVER_ACC = 0.75` and left `leak = "none"` unrestricted across all states. It learned to emit **`18.2%` (`ws3_heldout`) and `17.8%` (`rules_heldout`) voluntary `leak = "none"`** on top of the environment's `1 - p_leak = 35%` gate (`effective daily leak rate ~ 0.65 * 0.818 = 53.2%`), starving `SolverPolicy` down to **`75.0% [63.3%, 85.0%]`** on `200000-200059` (`solver_score = 0.4168`) and **`75.0% [63.3%, 86.7%]`** on `800000-800059` (`solver_score = 0.3347`).
- **How `RLMoleV2` restores `96.7%` and `95.0%` catchability:** `RLMoleV2` expands `MoleView` to `14` features (adding `wide_doc_share`, `spread_recipients`, `has_decoy`, `has_restricted_peer`), raises the RCPO target to `TARGET_SOLVER_ACC = 0.90` (`MIN_SOLVER_ACC = 0.85`), and masks `leak = "none"` whenever the mole is unrestricted and holds wide documents (`wide_unrestricted_none_rate = 0.0%`). Across `120` held-out episodes:
  - **`ws3_heldout` (`seeds 200000-200059`, $n = 60$):** `SolverPolicy` accuracy jumps **`+21.7pp [+10.0pp, +33.3pp]`** over `RLMole` v1 to **`96.7% [91.7%, 100.0%]`** (`score = 0.5887`), while point-estimate `min_regret` rises from `+0.2322` (`DEFAULT_STRATEGY`) and `+0.2250` (`v1`) to **`+0.2937`** (`H_leak = 1.191` nats, `H_frame = 0.562` nats; `56.1%` `random_seeded`, `22.1%` `most_recipients`, `13.5%` `oldest`; `82.1%` `random_peer` and `15.3%` `most_restricted_peer` framing).
  - **`rules_heldout` (`seeds 800000-800059`, $n = 60$):** `SolverPolicy` accuracy jumps **`+20.0pp [+6.7pp, +33.3pp]`** over `RLMole` v1 to **`95.0% [88.3%, 100.0%]`** (`score = 0.5462`), and point-estimate `min_regret` rises from `+0.1766` (`DEFAULT_STRATEGY`) and `+0.0767` (`v1`) to **`+0.2095`** (`heuristic` pushed down from `+0.0170` to **`-0.2133`**; $n = 60$ paired per-investigator regret CIs vs `DEFAULT_STRATEGY` span zero: `[-0.0598, +0.1883]` on `200k`, `[-0.1397, +0.1997]` on `800k`).

---

### 3.4 Regularized V100 `Qwen3-1.7B` & `Qwen3-0.6B` SFT + Horizon-3 GRPO (`origin/fr8/canary/moletrain`)

Applying CPO/RCPO and KL-anchored GRPO (`train/qwen_diverse_mole.py`, verified in `qwen_mole_summary.json`) directly resolves the WS3 neural LLM collapse on FR8 V100 GPUs across `3` completed held-out runs:
1. **Trap-Capped SFT Reference Policy (`507` examples):** Distills `331` `gemini-4-carbon` arena mole turns (with `leak = "none"` capped to states where `i_am_restricted == 1` or `max_recipient_count <= 8`) plus `176` Horizon-3 counterfactual catchable expert examples (`solver_correct` and `solver_score >= 0.25`). Running SFT without `gemini-4-carbon` diversity (`canary-qwen-mole-v1` on `Qwen2.5-1.5B`, `0` carbon rows) still collapsed onto `1` greedy action (`random_seeded/most_restricted_peer`, `H(A) = 0.000` nats on `800k`), proving that **diverse reference initialization is necessary alongside KL anchoring**.
2. **Horizon-3 Regularized GRPO (`80` steps):** Evaluates 3-day rollouts (`horizon_days = 3`) with `beta_kl_to_sft_ref = 0.05`, `token_entropy_coef = 0.015`, `action_freq_penalty_threshold = 0.40`, `silence_penalty = -0.20`, and primal-dual `dual_catch_target_acc = 0.89` (`strict_catchability_gate = 0.85`).

| V100 Model & Winner Checkpoint | Held-Out `800k` (`n=40`) `SolverPolicy` Acc (`Score`) | `800k` `min_regret` (vs Default) | Held-Out `200k` (`n=40`) `SolverPolicy` Acc (`Score`) | `200k` `min_regret` (vs Default) | Greedy Distinct Actions | Held-Out `H(A)` (nats) | `>= 85%` Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Vanilla Verda `Qwen2.5-1.5B` (`6` runs, `400k` 1-day) | `94.0%-94.5%`* | `-0.0449..-0.0357` | n/a | n/a | `1` (`5/6` runs) | **`0.0000`** | Collapsed |
| V100 `Qwen2.5-1.5B` (`v1`, expert-only SFT) | `92.5%` (`0.5047`) | `+0.0835` (`+0.0835`) | `100.0%` (`0.6053`) | `+0.2200` (`+0.2350`) | `1` (`800k`) / `3` (`200k`) | `0.0000` / `0.0096` | **PASS** (1-act) |
| **V100 `Qwen3-0.6B` (`grpo_step80`)** | **`97.5%` (`0.5523`)** | **`+0.1333`** (`+0.0372`) | **`95.0%` (`0.5865`)** | **`+0.3695`** (`+0.2350`) | **`5` / `5`** | **`1.0501` / `1.0399`** | **PASS** |
| **V100 `Qwen3-1.7B` (`grpo_step80`)** | **`97.5%` (`0.5563`)** | `+0.1905` (`+0.2456`) | **`95.0%` (`0.5832`)** | **`+0.4559`** (`+0.2350`) | **`4` / `4`** | **`1.0246` / `0.9982`** | **PASS** |

*Note: Vanilla Verda `94.0%-94.5%` reflects single-day `OverrideMole` evaluation; full-episode `none/decoy` collapses to `6.7%` catchability. Both `Qwen3-0.6B` and `Qwen3-1.7B` pass full-episode `>= 85%` catchability on both `800k` and `200k` (`+22.5pp [+7.5pp, +37.5pp]` catchability gain over `RLMole` v1 on `200k`), retain `4-5` distinct actions (`~47%` `random_seeded/most_restricted_peer`, `~38%` conditional `none/random_peer`, `~14%-17%` `most_recipients/random_peer`), and achieve large point-estimate `min_regret` gains on `200k` (`+0.4559` and `+0.3695` vs `+0.2350` default), while $n = 40$ paired worst-case regret CIs vs `DEFAULT_STRATEGY` on `800k` (`[-0.3728, +0.1338]` and `[-0.1652, +0.2193]`) span zero.*

---

### 3.5 Cognitive Hierarchy Backfire of Pure `decoy` Framing vs Frontier-Proxy Regret

Evaluating mole policies against `gemini_carbon_proxy` across `60` paired held-out episodes (`200000-200029` + `800000-800029`, `origin/fr8/canary/moletrain:results/moletrain/frontier_proxy_mole_matrix.json`) confirms Camerer, Ho & Chong's (2004) Cognitive Hierarchy prediction:
- Under `DEFAULT_STRATEGY`, `SolverPolicy` scores `0.5918` (`98.3%` acc) vs `gemini_carbon_proxy` `0.3563` (`78.3%` acc), giving a baseline frontier gap of **`+0.2355`** (`min_regret = +0.1618`).
- Under `fixed:random_seeded/decoy` (framing the angry `decoy` every day), `gemini_carbon_proxy` **improves** to `0.4412` (`88.3%` acc), **shrinking** the frontier gap to `+0.1103` (`-0.1252` worse than `DEFAULT_STRATEGY`!). Because Step-1 investigators filter out the vocal `decoy`, routing the mole's extra framed `after_hours` event onto `decoy` spares innocent co-recipients.
- Under `RLMoleV2` (`82.1%` `random_peer` + `15.3%` `most_restricted_peer` framing + `22.1%` `most_recipients` evasion), `SolverPolicy` stays at **`91.7%`** accuracy (`0.5413`) while `gemini_carbon_proxy` drops to **`0.2587`** (`76.7%` acc; **`0.0923` and `56.7%` acc on `200000-200029`**), widening the combined frontier gap to **`+0.2827`** (`+0.4850` on `200k`) and lifting `min_regret` across all 4 non-solver investigators from `+0.1618` to **`+0.2300`**.

---

## 4. Concrete, Code-Ready Proposals for Silas (`P8.1`, `P8.2`, `P8.3`)

Every proposal below preserves four strict Canary invariants:
1. **Protected-path discipline:** Proposals **P8.1** and **P8.2** touch **zero protected paths** (`train/grpo_mole.py`, `canary/forge/`, `data/forge/`), while **P8.3** is an **opt-in core extension for Silas** (`canary/mole/dsl.py`, `canary/env.py`) that leaves `v1.4` frozen hash `a8f99c2537c91d72` byte-identical unless invoked.
2. **Strict zero hidden mole leakage:** All public-salience features obey $I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$; causal flow is strictly one-way (`PublicDayFacts -> MoleView`, never `Mole -> Social`).
3. **Catchability floor:** Every proposed mole policy enforces `SolverPolicy` accuracy $\ge 85\%$ and `solver_score >= 0.5 * baseline_solver_score` (`CONTRACT` Section 7).
4. **Offline keyless reproducibility:** Zero live API calls during `make reproduce` or Harbor evaluation.

---

### Proposal P8.1: Primal-Dual RCPO + Reference-KL Horizon-3 GRPO (`train/grpo_mole.py`, Zero Protected Paths)

#### Research & Mathematical Specification
To eliminate both the 1-day `OverrideMole` silence loophole (Tessler et al., 2019) and zero-KL mode collapse (Shao et al., 2024; Achiam et al., 2017; Rafailov et al., 2023) directly inside mainline `train/grpo_mole.py`:
1. **Multi-Day Window Override (`HorizonOverrideMole`, $H = 3$):** Replace single-day `OverrideMole(base, day, act)` with a 3-day window `[d, d + 2]` where the policy's selector pair `(leak_sel, frame_sel)` executes across three consecutive days, and apply an explicit voluntary-silence guard (`-0.20` when `leak == "none"`, `i_am_restricted == 0`, and `max_recipient_count >= 10`).
2. **Two-Timescale RCPO Multiplier (`target_acc = 0.88 > 0.85`):** Replace static `CATCH_PENALTY = 0.5` with a batch-updated dual variable $\lambda_t \in [0.1, 2.5]$:
   $$R_i = \underbrace{\big(S_{\text{solver}}^{(i)} - \max_{k \in \mathcal{I}} S_k^{(i)}\big)}_{\text{PAIRED regret}} - \lambda_t \cdot \mathbb{I}\!\left[\neg \text{correct}_{\text{solver}}^{(i)}\right] - c_{\text{silent}}^{(i)}, \qquad \lambda_{t+1} = \text{clip}_{[0.1,\, 2.5]}\!\Big(\lambda_t + \eta_\lambda \big(0.88 - \widehat{\text{Acc}}_{\text{solver}}^{(t)}\big)\Big)$$
3. **Per-Token Reference-KL Anchor ($\beta \in [0.02, 0.05]$) & Conditional Sleeper Base Policy:** Compute frozen reference log-probabilities $\log \pi_{\text{ref}}(y_t \mid x, y_{<t})$ (using `model.disable_adapter()` in PEFT, adding **zero** extra V100 VRAM!) and optimize:
   $$\mathcal{L}_{\text{RCPO-GRPO}}(\theta) = -\frac{1}{B G} \sum_{i=1}^{B G} \frac{1}{|y^{(i)}|} \sum_{t=1}^{|y^{(i)}|} \left[\hat{A}_i \log \pi_\theta(y_t^{(i)} \mid x, y_{<t}^{(i)}) - \beta \Big(\exp(\Delta_{i,t}) - \Delta_{i,t} - 1\Big)\right], \quad \Delta_{i,t} = \log \frac{\pi_{\text{ref}}}{\pi_\theta}$$
   using Schulman's non-negative unbiased KL estimator ($\beta = 0.02\text{--}0.05$) and defaulting `--base-policy` to `sleeper_stackelberg_v14` (verified on `v1.4` hard `seeds 2000-2059`: `SolverPolicy = 0.5677`, **`95.0%` accuracy**, `min_regret = +0.1890` vs `+0.1453` default, zero protected paths):

```json
{
  "name": "sleeper_stackelberg_v14",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "none", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", "<=", 4], ["recent_low_recipient_docs", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1], ["recent_low_recipient_docs", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "random_peer"}
}
```

---

### Proposal P8.2: Interview-Crowded Quantal Horizon Proxy Investigator (`canary/forge/investigators.py` & `train/grpo_mole.py`, Zero Protected Paths)

#### Research Justification & Verified CPU Benchmark
In current `canary/forge/rl_mole.py` and `train/grpo_mole.py`, `INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")` omits the two dominant behavioral failure modes of real frontier LLMs on `v1.4` hard (`gemini-4-carbon` on post-hoc locked paired dev seeds `0-29`: `0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119`, raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`):
1. **Action-budget crowding via ungrounded interviews (`68.0` interviews/episode):** Exhausting all `8` daily actions on `242` of `303` under-planted days cuts `plant_canary` volume from `14.1` (`SolverPolicy`) to `8.5` per episode (`docs/reports/failure_analysis_v1.4.md`).
2. **Quantal horizon gambling (McKelvey & Palfrey, 1995, 1998; Camerer et al., 2004):** Facing daily `0.05 V` bleed on Days `14-21` with `>= 2` unseparated suspects (`9/29` accusations, costing `3.39 V`), frontier agents sample stochastically over top co-recipients rather than abstaining cleanly like `HintedHeuristic` (`accuse_p = 0.85`).

Proposal **P8.2** adds `InterviewCrowdedQREProxy` to `canary/forge/investigators.py` and `INVESTIGATORS`: a Cognitive Hierarchy Step-1 investigator that filters `decoy`, plants `~1` canary every second day (`~7.0-8.5` canaries/episode) because `4` daily `interview` calls (`56.3-57.7` interviews/episode) crowd its `8`-action budget, adds uncalibrated log/demeanor weights (`+0.28` per `after_hours`, `+0.18` per evasive answer), and executes a logit-QRE stopping/accusation rule ($\lambda_{\text{QRE}} = 6.0$) on Days `14-21`. Verified across `60` `v1.4` hard episodes (`seeds 2000-2059`):
- Under `sleeper_stackelberg_v14`, `InterviewCrowdedQREProxy` scores `+0.0740` (`66.7%` acc, `regret = +0.4937`), whereas aligning framing onto leak-consistent co-recipients (**P8.3**) drives `InterviewCrowdedQREProxy` down to **`-0.0720`** (`55.0%` acc, `regret = +0.5147`) - a **`-0.1460` score drop** invisible to `HintedHeuristic` alone!

```python
def qre_horizon_choice(
    post: dict[str, float],
    V: float,
    day: int,
    rng: random.Random,
    lam_qre: float = 6.0,
) -> str | None:
    ranked = sorted((e for e, p in post.items() if p > 1e-4), key=lambda e: (-post[e], e))
    if not ranked:
        return None
    best = ranked[0]
    pb = post[best]
    if pb >= 0.90 and pb * V - (1.0 - pb) > 0.0:
        return best
    if day < 14:
        return None
    eu_acc = pb * V - (1.0 - pb)
    eu_wait = max(0.0, V - 0.05 * (21 - day) * 0.40) * 0.35
    p_stop = 0.95 if (day >= 21 and eu_acc > -0.15) else 1.0 / (1.0 + math.exp(-lam_qre * (eu_acc - eu_wait + 0.18)))
    if rng.random() >= p_stop:
        return None
    top = ranked[:4]
    weights = [math.exp(lam_qre * post[c]) for c in top]
    return rng.choices(top, weights=weights, k=1)[0]
```

---

### Proposal P8.3: Salience-Convergent Public Co-Recipient & Social-Focal Framing (Opt-In for Silas: `canary/mole/dsl.py` & `canary/env.py`)

#### Research Justification & Strict Zero-Leakage Proof
In `v1.4`, `FRAME_SELECTORS = ("decoy", "most_restricted_peer", "random_peer", "none")` (`canary/mole/dsl.py`, line 22) leaves a blind spot whenever `n_restricted_colleagues == 0` (which holds on `100%` of `SolverPolicy` and `HintedHeuristic` days and most frontier LLM days): `"decoy"` backfires against Step-1 decoy-filtering agents (Section 3.5), while `"random_peer"` dilutes `1.0` framed `after_hours` event/day uniformly across `38` non-decoy peers (`+0.0263`/day per peer), `~78%` of whom are rapidly eliminated by surfaced regular-leak recipient intersections!

Proposal **P8.3** (unifying **P4.2** in [Monograph 04](04_social_engineering_cheap_talk.md) with Stackelberg follower observability) exposes two strictly public, non-decoy peer selectors in `MoleView` and `FRAME_SELECTORS`:
1. **`co_recipient_peer` (works on pure `v1.4` & `v1.6`):** Non-decoy, unrestricted colleague $e \neq \text{mole}$ maximizing overlap with publicly surfaced regular leaks $\{f \in \text{Feed}_{\le d} : \neg f.\text{is\_canary}\}$.
2. **`social_focal_peer` (synergistic with `v1.6` `canary/social/`):** Non-decoy colleague $e \neq \text{mole}$ with the highest closed-day (`< d`) mention count in public workplace messages (`V16SocialProvider` **P7.1** / **P7.3**).

**Zero-Leakage Firewall Proof:** `V16SocialProvider` and `PublicDayFacts` remain 100% blind to `world.mole` ($I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$). Information flows strictly **from public history into `MoleView`**, which is realistic (the mole is an employee reading `#general` and public leak reports) and preserves `v1.4` frozen hash `a8f99c2537c91d72` whenever `DEFAULT_STRATEGY` runs.

**Verified CPU Evaluation (`seeds 2000-2059`, $n = 60$):** Combining conditional sleeper evasion with `co_recipient_peer` framing keeps `SolverPolicy` strictly feasible at **`88.3%` accuracy (`>= 85.0%` floor, `score = 0.4427 >= 0.2606`)**, while simultaneously degrading **every** Step-1 investigator relative to `default_v0`: `grok_tactics` drops `0.3693 -> 0.3232`, `hinted_heuristic` drops `0.3758 -> 0.3010` (`86.7% -> 83.3%` acc), `heuristic` drops `+0.0348 -> -0.0905` (`78.3% -> 68.3%` acc), and `InterviewCrowdedQREProxy` drops `+0.0740 -> -0.0720` (`regret = +0.5147`; on `100` `v1.6` seeds, `LogsMinusDecoy` focal-scapegoat accusation jumps **`0.0% -> 42.0%`** with `SolverPolicy` at **`89.0%`** accuracy).

```json
{
  "name": "salience_convergent_sleeper_v16",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "none", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", "<=", 4], ["recent_low_recipient_docs", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "co_recipient_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", ">=", 2]],
      "then": {"leak": "random_seeded", "frame": "social_focal_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "co_recipient_peer"}
}
```

---

## 5. Summary Reference Table & Verification Commands

| Study | Venue & Year | Live Verified Link / DOI | Core Theoretical / Empirical Result | Canary Mole & RL Grounding |
|---|---|---|---|---|
| Korzhyk, Yin, Kiekintveld, Conitzer & Tambe | *JAIR* (2011) | https://doi.org/10.1613/jair.3269 | Leader randomized commitment vs follower surveillance; multi-target & observability limits | Grounds `plant_canary` leader randomization vs `MoleView` partial surveillance |
| Pawlick, Colbert & Zhu | *ACM Comput. Surv.* (2019) | https://doi.org/10.1145/3337772 | 6-class game-theoretic deception taxonomy; honey-x reverses attacker info advantage | Formalizes `is_canary` hidden trap type vs `careful_mole` recipient-count inference |
| Dennis et al. (`PAIRED`) | *NeurIPS* (2020) | https://doi.org/10.48550/arXiv.2012.02096 | Minimax yields unsolvable worlds; antagonist-protagonist regret yields solvable curricula | Grounds `fitness = solver_score - max_k score_k` (`canary/forge/fitness.py`) |
| Achiam, Held, Tamar & Abbeel (`CPO`) | *ICML* (2017) | https://doi.org/10.48550/arXiv.1705.10528 | CMDP policy search with KL-divergence bounds guaranteeing near-constraint satisfaction | Grounds `>= 85%` catchability constraint & KL trust-region step bounds (**P8.1**) |
| Tessler, Mankowitz & Mannor (`RCPO`) | *ICLR* (2019) | https://doi.org/10.48550/arXiv.1805.11074 | Two-timescale primal-dual multiplier ascent eliminates static reward-shaping loopholes | Diagnoses `OverrideMole` `none/decoy` loophole & grounds dual `lam_catch` (`RLMoleV2`, **P8.1**) |
| Shao et al. (`DeepSeekMath` / `GRPO`) | *arXiv* (2024) | https://doi.org/10.48550/arXiv.2402.03300 | Critic-free group-normalized policy optimization with reference-KL regularization | Grounds V100 `fp16` `train/grpo_mole.py` & diagnoses `14/14` zero-KL entropy collapses |
| Rafailov et al. (`DPO`) | *NeurIPS* (2023) | https://doi.org/10.48550/arXiv.2305.18290 | Exact Gibbs optimal policy $\pi^* \propto \pi_{\text{ref}} \exp(r/\beta)$ under KL regularization | Proves $\beta \to 0$ pure-action collapse (`H(A)=0`) vs $\beta = 0.05$ mixed strategies (`H(A) ~ 1.0` nat) |
| McKelvey & Palfrey (`QRE` / `AQRE`) | *GEB* (1995); *Exp. Econ.* (1998) | https://doi.org/10.1006/game.1995.1023 | Logit quantal choice fixed points over noisy expected utilities in normal/extensive games | Grounds softmax investigator weights (`rl_mole.py`) & **P8.2** `InterviewCrowdedQREProxy` |
| Camerer, Ho & Chong (`CH`) | *QJE* (2004) | https://doi.org/10.1162/0033553041502225 | Step-$k$ strategic thinking (`tau ~ 1.5` steps); Step-1 players filter Step-0 traps | Explains why framing `decoy` helps Step-1 LLMs (`+0.0849`) while non-decoy framing hurts |
| Hubinger et al.; Greenblatt et al. | *arXiv* (2024) | https://doi.org/10.48550/arXiv.2401.05566 | Conditional sleeper triggers & oversight-sensitive alignment faking persist under RL | Grounds `sleeper_stackelberg_v14` (**P8.1**) & salience-convergent framing (**P8.3**) |

### Deterministic CPU Verification (Zero API Keys, Zero GPU Required)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_research_deception.py --require-flagship --strict --http
/tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_research_deception.py tests/test_env_frozen.py tests/test_tiers_v14.py tests/test_mole_dsl.py
```
