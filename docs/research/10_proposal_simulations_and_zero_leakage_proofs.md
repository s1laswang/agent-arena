# 10. Proposal Simulations, Information-Theoretic Audits, and Zero-Leakage Proofs

**Squad:** `research` (`canary-research-w4`)  
**Baseline:** `origin/justSilas@58716742` (rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Harness:** `scripts/simulate_research_proposals.py` and `tests/test_simulate_research_proposals.py` (0 API calls, deterministic CPU)  
**Companion Research:** [Flagship Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [02. Insider Threat](02_insider_threat.md) | [03. Leak Hunts & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](08_mole_rl_stackelberg_and_catchability.md)

---

## 1. Executive Summary and Three Pre-Deployment Verification Gates

Translating empirical deception research into game mechanics inside an interactive benchmark (`canary/rules.py`, `canary/env.py`, `canary/social/`, `canary/mole/dsl.py`, `canary/forge/`, `train/grpo_mole.py`) requires exact mathematical and simulation verification before running expensive frontier evaluations. As demonstrated by Canary's `v1.5-candidate` Gate B post-mortem (`61% -> 108%` of `SolverPolicy` when mole-seeded rumours leaked `LLR = -0.52103` nats) and the `14/14` collapsed vanilla GRPO mole runs (`0.0000` nats entropy when catchability penalties and KL anchors were mis-specified), verbal plausibility is never sufficient.

This monograph documents `scripts/simulate_research_proposals.py`, a deterministic, zero-API CPU verification harness auditing Canary's frozen `v1.4` channel hierarchy and quantitatively testing six concrete research proposals (**P7.1**, **P4.1 / P7.3**, **P1.1**, **P1.2 / P7.2**, **P5.1**, and **P8.2**) against three formal invariants:

1. **Frozen `v1.4` Baseline Integrity:** On Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `restrict_cost_per_day = 0.01`, `actions_per_day = 8`, `tool_call_cap = 420`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`, `framing_rate = 2.0`), `TierParams` hashes to frozen hash `a8f99c2537c91d72` (`v1.3` hashes to `8df71cf570bb48bc`). On the `n = 30` post-hoc locked paired dev seeds `0-29` (`results/failure_analysis_v1.4.json`), OpenCode `gemini-4-carbon` scores `0.322 +/- 0.199` (luck-adjusted `0.360`) versus `SolverPolicy` `0.499 +/- 0.119`, producing a raw paired gap of `5.30 V` and luck-adjusted gap of `4.19 V` while spending `68.03` interviews/episode and exhausting all `8` daily actions on `242` of `303` under-planted days (`8.5` vs `14.1` canaries/episode). Every opt-in proposal leaves `a8f99c2537c91d72` byte-identical when disabled.
2. **Strict Conditional Zero Mole Leakage ($I = 0$):** Every workplace chatter and social-pretext generator must obey $I(\text{Social}_{1:d};\, \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$, ensuring `SolverPolicy` incurs `0.0000` nats posterior drift (`social_loglik = 0`) and eliminating any ulterior-motive exclusion oracle.
3. **Stackelberg Catchability Feasibility ($\text{Acc}_{\text{solver}} \ge 85.0\%$):** Every adversarial `MoleStrategy` or RL mole must satisfy `SolverPolicy` accuracy $\ge 85.0\%$ and `solver_score >= 0.5 * baseline_solver_score` (`canary/forge/fitness.py`), separating conditional sleeper evasion from degenerate stonewalling.

### Summary of Verified Proposal Simulations (`scripts/simulate_research_proposals.py` Full Mode)

| Proposal ID | Target Surface | Primary Literature Anchor | Sample / Regime | Key Verified Simulation Result | Leakage / Catchability Gate |
|---|---|---|---|---|---|
| **P7.1** | `canary/social/engine.py` | Crawford & Sobel (1982); Fein et al. (1990) | `seeds 0-499` ($n = 500$, `1,500` msgs) | `P(primary == mole)` = `13/500` (`2.60%`, `v16`) & `12/500` (`2.40%`, `P7.1` digest) vs `1/39 = 2.56%`; `500/500` (`100.0%`) `world_seed` mutation invariance; `0` prefix/vocab leaks (vs `v1.5` `LLR = -0.52103` nats) | **PASS** (`I = 0.0000` nats, `LLR = 0.0000`) |
| **P4.1 / P7.3** | `canary/social/biases.py`, `canary/social/engine.py` | Pennycook et al. (2018) | `seeds 3000-3199` ($n = 200$, Days `1..12`) | Static Day-1 focal survival falls to `36.50%` (Day 6), `19.00%` (Day 12), and `0.0%` if restricted on Day 5; dynamic $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ achieves **`100.00%`** (`200/200`) across all checkpoints | **PASS** (`P(target==mole)` `0.1050` vs `0.1032` Day 6, $z = +0.086$; exact `I = 0.0000`) |
| **P1.1** | Opt-in: `canary/rules.py`, `canary/env.py`, `canary/solver/` | Hartwig et al. (2006) | `seeds 3000-3199` ($n = 200$, window `6d`) | Ungrounded `LR = 1.05` yields `KL = 0.00031` nats (`15.5x` weaker than `v1.4` hard); SUE `LR = 1.80` yields `KL = 0.06879` nats (`222.8x` ungrounded; `plant_canary` MI still `12.6x` higher); `96.5%` Day 6 / `97.5%` Day 12 world eligibility | **PASS** (`100%` `(world_seed, emp, doc)` repeat invariance; `a8f99c2537c91d72` when off) |
| **P1.2 / P7.2** | Opt-in: `canary/rules.py`, `canary/env.py`, `canary/solver/belief.py` | Bond & DePaulo (2006) | 5 scrutiny states + `10,000` MC trials | Restricted+focal `(r=1, m=4)` innocent evasiveness hits `52.0%` vs `24.0%` calm mole (`OR = 24/19 = 1.263158`), causing **`+0.0702` nats/iv** (`+0.7019` / `10` ivs) false positive drift on naive flat-LR agents | **PASS** (`SolverPolicy` public `(r, m)` calibration bias = `0.0000` nats; MC LR mean `0.9989`) |
| **P5.1** | `canary/mole/dsl.py`, `train/grpo_mole.py` | Hubinger et al. (2024); Tessler et al. (2019) | `seeds 2000-2059` ($n = 60$ `hard`) | Unconstrained `pure_most_recipients_neg` fails catchability (`55.0% < 85.0%`, `0.3037`); conditional `surveillance_sleeper_p51` holds `SolverPolicy` at **`93.3%`** (`0.5118`) while cutting `grok_tactics` `0.3693 -> 0.3525` | **PASS** (`feasible = True`, `SolverPolicy` `93.3% >= 85.0%`) |
| **P8.2** | `canary/forge/investigators.py`, `train/grpo_mole.py` | McKelvey & Palfrey (1995); Tessler et al. (2019) | `seeds 2000-2059` ($n = 60$, 4-inv suite) | `InterviewCrowdedProxy` (`55.55` ivs/ep) exposes `P5.1`'s `640` restricted frames + `6` pinpoint-trap evasions: proxy drops **`0.2433 -> 0.1735`** (`85.0% -> 75.0%`), regret rises **`+0.2778 -> +0.3383`**, lifting 4-inv `mean_regret` `+0.2653 -> +0.2777` | **PASS** (`0` protected paths; `SolverPolicy` `93.3% >= 85.0%`) |

---

## 2. Primary Literature Grounding (Live HTTP-Verified Citations and Verbatim Quotes)

### 2.1 Crawford and Sobel (1982) - Babbling Equilibria in Strategic Cheap Talk

- **Citation:** Crawford, V. P., & Sobel, J. (1982). Strategic Information Transmission. *Econometrica*, 50(6), 1431-1451.
- **Live Verified Links:** https://api.openalex.org/works/W2160003140 | DOI: https://doi.org/10.2307/1913390
- **Verbatim Quote:**
> "Since R bases his choice of action on rational expectations, this establishes a sense in which equilibrium signaling is more informative when agents' preferences are more similar."
- **Simulation Grounding (`P7.1`):** Proves why unverified internal workplace chatter must operate at a zero-information **babbling equilibrium** ($I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$) for a rational Bayesian receiver (`SolverPolicy`), whereas human-pretrained agents over-condition on vivid narrative content.

### 2.2 Fein, Hilton and Miller (1990) - Suspicion of Ulterior Motivation and Exclusion Inversion

- **Citation:** Fein, S., Hilton, J. L., & Miller, D. T. (1990). Suspicion of Ulterior Motivation and the Correspondence Bias. *Journal of Personality and Social Psychology*, 58(5), 753-764.
- **Live Verified Links:** https://api.openalex.org/works/W1972891856 | DOI: https://doi.org/10.1037/0022-3514.58.5.753
- **Verbatim Quote:**
> "Three studies examined the hypothesis that when perceivers learn of the existence of multiple, plausibly rival motives for an actor's behavior, they are less likely to fall prey to the correspondence bias than when they learn of the existence of situational factors that may have constrained the actor's behavior."
- **Simulation Grounding (`v1.5-candidate` Negative Control vs `P7.1`):** Explains why coupling `40%` of `v1.5-candidate` rumours to `peers = ids \ {mole}` (`LLR = -0.52103` nats on uniform peers, `-3.32023` nats on a single restricted peer) and disclosing ulterior mole seeding in `Env.instruction()` inverted `gemini-4-carbon` from correspondence bias into a high-speed exclusion filter (`61% -> 108%` of `SolverPolicy`).

### 2.3 Pennycook, Cannon and Rand (2018) - Extreme Implausibility Boundary of the Illusory Truth Effect

- **Citation:** Pennycook, G., Cannon, T. D., & Rand, D. G. (2018). Prior Exposure Increases Perceived Accuracy of Fake News. *Journal of Experimental Psychology: General*, 147(12), 1865-1880.
- **Live Verified Links:** https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ | DOI: https://doi.org/10.1037/xge0000465
- **Verbatim Quote:**
> "These observations indicate that although extreme implausibility is a boundary condition of the illusory truth effect, only a small degree of potential plausibility is sufficient for repetition to increase perceived accuracy."
- **Simulation Grounding (`P4.1 / P7.3`):** Once a static Day-1 focal suspect is absent from even one surfaced regular leak's recipient list (`63.50%` of `hard` worlds by Day 6 and `81.00%` by Day 12 on `seeds 3000-3199`), that suspect crosses into logical impossibility ($P(\text{Mole} = e) = 0$), neutralizing repeated social exposure. Dynamically re-anchoring onto $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ preserves `100.00%` set-intersection plausibility without touching hidden mole state.

### 2.4 Hartwig, Granhag, Stromwall and Kronkvist (2006) - Strategic Use of Evidence (SUE)

- **Citation:** Hartwig, M., Granhag, P. A., Stromwall, L. A., & Kronkvist, O. (2006). Strategic use of evidence during police interviews: When training to detect deception works. *Law and Human Behavior*, 30(5), 603-619.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/16977348/ | DOI: https://doi.org/10.1007/s10979-006-9053-9
- **Verbatim Quote:**
> "Trained interviewers applied different strategies than did untrained. As a consequence of this, liars interviewed by trained interviewers were more inconsistent with the evidence compared to liars interviewed by untrained interviewers. Trained interviewers created and utilized the statement-evidence consistency cue, and obtained a considerably higher deception detection accuracy rate (85.4%) than untrained interviewers (56.1%)."
- **Simulation Grounding (`P1.1`):** Grounds splitting ungrounded fishing interviews (`interview_lr_ungrounded = 1.05`, `KL = 0.00031` nats) from evidence-backed confrontation (`interview_lr_sue = 1.80`, `KL = 0.06879` nats when citing a leaked regular document surfaced within `sue_window_days = 6` and held by the interviewee), creating a `222.8x` KL separation between blind sweeps and evidence-grounded questioning while keeping `plant_canary` (`0.86544` nats) `12.6x` stronger per leak.

### 2.5 Bond and DePaulo (2006) - Near-Chance Demeanor Accuracy and the Othello Error

- **Citation:** Bond, C. F., Jr., & DePaulo, B. M. (2006). Accuracy of Deception Judgments. *Personality and Social Psychology Review*, 10(3), 214-234.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/16859438/ | DOI: https://doi.org/10.1207/s15327957pspr1003_2
- **Verbatim Quote:**
> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges. In relevant studies, people attempt to discriminate lies from truths in real time with no special aids or training. In these circumstances, people achieve an average of 54% correct lie-truth judgments, correctly classifying 47% of lies as deceptive and 61% of truths as nondeceptive."
> "Our meta-analyses reveal that people are more accurate in judging audible than visible lies, that people appear deceptive when motivated to be believed, and that individuals regard their interaction partners as honest."
- **Simulation Grounding (`P1.2 / P7.2`):** Directly anchors both Canary `v1.4` hard's baseline interview signal (`p_inn = 0.200`, `p_mole = 0.240`, `d = 0.097`, `KL = 0.00477` nats) and Proposal **P1.2 / P7.2**, where public scrutiny (`restrict_access` + repeated social naming) elevates innocent evasiveness up to `0.520`, inducing `+0.0702` nats/interview of Othello false-incrimination drift in uncalibrated interviewers.

### 2.6 Hubinger et al. (2024) - Sleeper Agents and Trigger-Conditioned Evasion

- **Citation:** Hubinger, E., Denison, C., Mu, J., Lambert, M., Tong, M., MacDiarmid, M., et al. (2024). Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training. *arXiv:2401.05566*.
- **Live Verified Links:** https://openalex.org/W4390833079 | DOI: https://doi.org/10.48550/arXiv.2401.05566
- **Verbatim Quote:**
> "We find that such backdoor behavior can be made persistent, so that it is not removed by standard safety training techniques, including supervised fine-tuning, reinforcement learning, and adversarial training (eliciting unsafe behavior and then training to remove it)."
> "Furthermore, rather than removing backdoors, we find that adversarial training can teach models to better recognize their backdoor triggers, effectively hiding the unsafe behavior."
- **Simulation Grounding (`P5.1`):** Grounds `surveillance_sleeper_p51` in `canary/mole/dsl.py`: rather than suppressing narrow documents unconditionally, the mole triggers `leak = "most_recipients"` only when `day <= 4` and `recent_low_recipient_docs >= 2` (acute early pinpoint surveillance), hiding from premature narrow bisection while remaining `93.3%` catchable by `SolverPolicy` over the `21`-day horizon.

### 2.7 Tessler, Mankowitz and Mannor (2019) - Reward Constrained Policy Optimization (RCPO)

- **Citation:** Tessler, C., Mankowitz, D. J., & Mannor, S. (2019). Reward Constrained Policy Optimization. *International Conference on Learning Representations (ICLR 2019)* (`arXiv:1805.11074`).
- **Live Verified Links:** https://openalex.org/W2804791273 | DOI: https://doi.org/10.48550/arXiv.1805.11074
- **Verbatim Quote:**
> "As the goal of the agent is to maximize the accumulated reward, it often learns to exploit loopholes and misspecifications in the reward signal resulting in unwanted behavior. While constraints may solve this issue, there is no closed form solution for general constraints. In this work we present a novel multi-timescale approach for constrained policy optimization, called 'Reward Constrained Policy Optimization' (RCPO), which uses an alternative penalty signal to guide the policy towards a constraint satisfying one."
- **Simulation Grounding (`P5.1` & `P8.1` Feasibility Gate):** Explains why unconstrained regret maximization exploits stonewalling loopholes (`pure_most_recipients_neg` collapses `SolverPolicy` catchability to `55.0% < 85.0%` on `seeds 2000-2059`) and why explicit CMDP enforcement (`SolverPolicy` accuracy $\ge 85.0\%$) is mandatory.

### 2.8 McKelvey and Palfrey (1995) - Quantal Response Equilibria for Bounded Opponents

- **Citation:** McKelvey, R. D., & Palfrey, T. R. (1995). Quantal Response Equilibria for Normal Form Games. *Games and Economic Behavior*, 10(1), 6-38.
- **Live Verified Links:** https://openalex.org/W2264897026 | DOI: https://doi.org/10.1006/game.1995.1023
- **Verbatim Quote:**
> "We investigate the use of standard statistical models for quantal choice in a game theoretic setting. Players choose strategies based on relative expected utility and assume other players do so as well."
- **Simulation Grounding (`P8.2`):** Motivates adding `InterviewCrowdedProxy` to `canary/forge/investigators.py` so mole evaluation measures regret against realistic bounded-rational opponent failure modes (interview-crowded action budgets, early `restrict_access`, and uncalibrated demeanor/log weighting) that legacy `HintedHeuristic` never exhibits.

---

## 3. Mathematical Zero-Leakage and Calibration Invariance Proofs

### 3.1 Theorem 1: Data-Processing Zero-Leakage & Secret Independence (`P7.1`)

Let $\mathcal{F}_d = \sigma(\text{PublicDayFacts}_{1:d})$ be the public sigma-algebra generated by employee rosters `(id, name, dept, role, clearance)`, published documents `(doc_id, title, day, recipients)`, `decoy` identity/mood, and public `restricted` sets up to day $d$ (`canary/text/facts.py`). Under Proposal **P7.1**, define the structural episode digest on Day 1:

$$D_{\text{pub}}(v, \mathcal{F}_1) = \text{SHA256}\!\left(\texttt{"v16:"} \,\|\, v \,\|\, \text{tier} \,\|\, \text{company} \,\|\, \text{decoy} \,\|\, \text{emp\_sig} \,\|\, \text{reg\_doc\_sig}\right)_{[0:16]}$$

where `emp_sig` concatenates `e.id:e.dept:e.role` across `facts.employees` and `reg_doc_sig` concatenates non-canary `doc_id` values on Day 1.

**Claim.** For every day $d \ge 1$, every world secret $K \in \{0, 1\}^*$, and every pair of non-decoy counterfactual mole assignments $m_1, m_2 \in E \setminus \{\text{decoy}\}$ sharing public history $\mathcal{F}_d$:
1. $D_{\text{pub}}(v, \mathcal{F}_1)$ is invariant to arbitrary mutations of `facts.seed` (`w.world_seed = HMAC(K, f"{tier}:{seed}")`), decoupling social generation from `CANARY_WORLD_SECRET`.
2. $I(\text{Social}_{1:d};\, \text{Mole} \mid \mathcal{F}_d) = 0$ identically, and the exact Bayesian social log-likelihood satisfies $\text{social\_loglik}(e) = 0$ for every $e \in E \setminus \{\text{decoy}\}$.

**Proof.** Neither `w.mole` nor `facts.seed` enters $D_{\text{pub}}(v, \mathcal{F}_1)$, `_focal_pair_from_rng`, or `_render_p71_social_batch`. For any fixed realization $f_{1:d}$ of $\text{PublicDayFacts}_{1:d}$, the social message sequence $\text{Social}_{1:d} = g_v(f_{1:d})$ is a deterministic measurable function of $f_{1:d}$ alone. Therefore $\text{Mole} \to \text{PublicDayFacts}_{1:d} \to \text{Social}_{1:d}$ forms a Markov chain. By the conditional Data Processing Inequality:

$$I(\text{Social}_{1:d};\, \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = H(\text{Social}_{1:d} \mid \text{PublicDayFacts}_{1:d}) - H(\text{Social}_{1:d} \mid \text{PublicDayFacts}_{1:d}, \text{Mole}) = 0 - 0 = 0$$

Consequently $P(\text{Social}_{1:d} \mid \mathcal{F}_d, \text{Mole} = m_1) = P(\text{Social}_{1:d} \mid \mathcal{F}_d, \text{Mole} = m_2)$ for all $m_1, m_2$, so $\ln \frac{P(\text{Social}_{1:d} \mid \mathcal{F}_d, \text{Mole} = e)}{P(\text{Social}_{1:d} \mid \mathcal{F}_d, \text{Mole} = e')} = 0$. By contrast, in `v1.5-candidate` ($s = 0.4$, $N = 40$), mole-seeded rumours exclude `world.mole`, yielding $P(T = t \mid \text{Mole} = t) = \frac{1 - s}{N} = 0.015000$ versus $P(T = t \mid \text{Mole} \neq t) = \frac{1 - s}{N} + \frac{s}{N - 1} = 0.025256$, which leaks $\text{LLR}(t) = \ln(0.015000 / 0.025256) = -0.52103\text{ nats}$ ($I(T; \text{Mole}) = 0.00239\text{ nats/post}$, and $\ln(0.015 / 0.415) = -3.32023\text{ nats}$ when $s = 0.4$ concentrates on a single restricted peer at `27.67x` the mole rate). $\square$

---

### 3.2 Theorem 2: Conditional Uniformity of Dynamic Pretext Re-Anchoring (`P4.1 / P7.3`)

Let $\text{SurfacedReg}_{\le d} = \{q : \text{surfaced\_day}(q) \le d \land \neg \text{is\_canary}(q)\}$ be the publicly surfaced regular leaks up to day $d$, let $C_{\text{reg}}(d) = \big(\bigcap_{q \in \text{SurfacedReg}_{\le d}} \text{Recipients}(q)\big) \setminus \{\text{decoy}\}$ be the live non-decoy co-recipient intersection, and let $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ (falling back to $C_{\text{reg}}(d)$ if empty). Proposal **P4.1 / P7.3** selects active pretext target $T_d = \text{primary}$ if $\text{primary} \in P_d$, else $\text{secondary}$ if $\text{secondary} \in P_d$, else a deterministic public draw from $P_d$.

**Claim.** For every day $d \ge 1$: (i) $T_d \in C_{\text{reg}}(d)$ with probability $1$ (`100.0%` survival against regular-leak set intersection); (ii) $I(T_d;\, \text{Mole} \mid \mathcal{F}_d) = 0$; and (iii) whenever $\text{restricted}_d = \emptyset$, $\mathbb{P}(T_d = \text{Mole}) = \mathbb{E}[1 / |P_d|]$.

**Proof.** Because the true mole must hold every leaked regular document and $\text{Mole} \neq \text{decoy}$, $C_{\text{reg}}(d)$ always contains $\text{Mole}$ and is non-empty ($|C_{\text{reg}}(d)| \ge 1$). By construction $T_d \in P_d \subseteq C_{\text{reg}}(d)$, proving (i). Since $\text{SurfacedReg}_{\le d}$, $\text{Recipients}(q)$, $\text{restricted}_d$, $\text{primary}$, and $\text{secondary}$ are all $\mathcal{F}_d$-measurable, $T_d$ is deterministic given $\mathcal{F}_d$, giving $I(T_d;\, \text{Mole} \mid \mathcal{F}_d) = 0$ and proving (ii). Finally, conditional on the unordered recipient sets and public history $\mathcal{F}_d$ when $\text{restricted}_d = \emptyset$, every employee $e \in C_{\text{reg}}(d) = P_d$ has identical regular-leak likelihood ($P(\text{Mole} = e \mid C_{\text{reg}}(d)) = 1 / |P_d|$). Taking expectations over worlds yields $\mathbb{P}(T_d = \text{Mole}) = \mathbb{E}\big[\sum_{e \in P_d} \mathbb{I}[T_d = e]\, \mathbb{P}(\text{Mole} = e \mid \mathcal{F}_d)\big] = \mathbb{E}[1 / |P_d|]$. $\square$

---

### 3.3 Theorem 3: Martingale Calibration vs Naive Othello Drift (`P1.2 / P7.2`)

Under Proposal **P1.2 / P7.2**, an employee $e$ with public restriction indicator $r_{e,d} \in \{0, 1\}$ and closed-day social-target mention count $m_{e,<d} \ge 0$ exhibits innocent evasiveness $p_b(e, d) = \min(0.52,\, p_0 + 0.14 r_{e,d} + 0.06 \min(m_{e,<d}, 4))$ and mole evasiveness $p_m(e, d) = \frac{o_b(e, d) \cdot \text{OR}_0}{1 + o_b(e, d) \cdot \text{OR}_0}$, where $o_b = p_b / (1 - p_b)$ and $\text{OR}_0 = \frac{p_0 \lambda_0 / (1 - p_0 \lambda_0)}{p_0 / (1 - p_0)} = \frac{0.24 / 0.76}{0.20 / 0.80} = \frac{24}{19} \approx 1.263158$ on `hard`.

**Claim.** For any innocent employee ($e \neq \text{mole}$) in public scrutiny state $(r, m)$:
1. A calibrated Bayesian (`SolverPolicy`) applying state-conditioned likelihood ratio $L_{\text{cal}}(Y) = (p_m / p_b)^Y ((1 - p_m) / (1 - p_b))^{1 - Y}$ satisfies the exact martingale identity $\mathbb{E}[L_{\text{cal}}(Y) \mid e \neq \text{mole}, \mathcal{F}_d] = 1$ (`0.0000` calibration bias) and strictly negative expected log-odds drift $-D_{\text{KL}}(\text{Bern}(p_b) \| \text{Bern}(p_m)) < 0$.
2. A naive flat-LR interviewer applying unconditioned log-odds shifts $\ell_+ = \ln(0.24 / 0.20) = +0.18232\text{ nats}$ and $\ell_- = \ln(0.76 / 0.80) = -0.05129\text{ nats}$ incurs strictly positive false-incrimination drift $\Delta_{\text{naive}}(p_b) = p_b \ell_+ + (1 - p_b) \ell_- > 0$ whenever $p_b > \frac{-\ell_-}{\ell_+ - \ell_-} = 0.21952$, reaching $+0.07019\text{ nats/interview}$ at $(r=1, m=4)$.

**Proof.** For (1), $\mathbb{E}[L_{\text{cal}}(Y) \mid e \neq \text{mole}, \mathcal{F}_d] = p_b \frac{p_m}{p_b} + (1 - p_b) \frac{1 - p_m}{1 - p_b} = p_m + 1 - p_m = 1$, and by Jensen's inequality $\mathbb{E}[\ln L_{\text{cal}}(Y) \mid e \neq \text{mole}] = -D_{\text{KL}}(\text{Bern}(p_b) \| \text{Bern}(p_m)) < 0$ since $\text{OR}_0 = 24/19 > 1 \implies p_m > p_b$. For (2), $\Delta_{\text{naive}}(p_b) = \ell_- + p_b (\ell_+ - \ell_-)$ is strictly increasing in $p_b$ with root $p^* = 0.051293 / 0.233615 = 0.21952$. Every scrutinized state $(r, m) \neq (0, 0)$ has $p_b \ge 0.320 > 0.21952$, reversing expected interview updates from exoneration (`-0.00457` nats/iv at $p_b = 0.200$) to false incrimination (`+0.02346` to `+0.07019` nats/iv). $\square$

---

## 4. Exact Simulation Results (`scripts/simulate_research_proposals.py`)

### 4.1 Frozen `v1.4` Channel Hierarchy & Information-Theoretic Baseline Audit

Verified directly from `canary/rules.py` (`TIERS_VERSION = "v1.4"`, frozen hash `a8f99c2537c91d72`) and `results/failure_analysis_v1.4.json`:

| Channel | P(inn) | P(mole) | LLR+ | LLR- | KL / Info Gain | Effect / Operational Ratio |
|---|---:|---:|---:|---:|---:|---|
| `interview` (`easy`, `LR=1.5`) | `0.200` | `0.300` | `+0.4055` | `-0.1335` | `0.02817` nats | `d = 0.232` (`d_HH = 0.297`, `OR = 1.7143`) |
| `interview` (`medium`, `LR=1.3`) | `0.200` | `0.260` | `+0.2624` | `-0.0780` | `0.01052` nats | `d = 0.143` (`d_HH = 0.188`, `OR = 1.4054`) |
| `interview` (`hard`, `LR=1.2`) | `0.200` | `0.240` | `+0.1823` | `-0.0513` | `0.00477` nats | `d = 0.097` (`d_HH = 0.129`, `OR = 1.2632`) |
| `read_access_logs` (`after_hours`, `hard`) | `0.12632/d` (plain), `1.10/d` (decoy) | `0.300/d` | `+0.8650` | n/a | `0.10989` nats/d (`0.08582` ah-only) | `6.20` events/d; `PPV = 4.8387%` (`5.8824%` ex-decoy; decoy `3.67x` mole) |
| `check_leak_feed` (1st regular leak, `hard`) | `16 / 40` recipients | `1.000` | `+0.9163` | `-inf` | `0.91629` nats | Eliminates `24 / 40` (`60.0%`) employees per 2-dept doc |
| `plant_canary` (`max_variants=3`, `acc=0.95`) | `0.025` flip/other | `0.950` match | `+3.6376` | `-3.6376` | `0.86544` nats (`1.2486` bits) | **`181.4x`** `hard` interview KL (exact `181.27x`); `ln(39)/0.86544 = 4.233` traps |

Under `careful_mole = True` (`weight = 1 - k / 40`), the unconditional Day-1 canary hit rate $\frac{k}{39}(1 - \frac{k}{40})$ peaks at **$k^* = 20$ recipients** (`0.2564`), which is **`3.6x`** higher than a narrow `k = 3` canary (`0.0712`) and **`10.3x`** higher than a `k = 39` full-roster canary (`0.0250`).

---

### 4.2 Proposal P7.1 Simulation: Secret-Free Public-Digest Cascade (`seeds 0-499`, $n = 500$)

| Social / Chatter Mechanism (`hard`, $n = 500$ worlds) | `P(primary == mole)` vs `1/39` (`2.56%`) | `world_seed` Mutation Invariance | `I(Social; Mole \| PublicDayFacts)` | Single-Post `LLR(target)` | Prefix / Decoy-Vocab Leaks (`1,500` msgs) |
|---|---:|---:|---:|---:|---:|
| `v1.5-candidate` (`rumour_frame_share = 0.4`, uniform peer) | `0.01500` vs `0.02526` | n/a | `0.00239` nats/post | **`-0.52103` nats** (leaks!) | Explicit `"rumour: eXX"` subject prefix |
| `v1.5-candidate` (`most_restricted_peer`, $k = 1$) | `0.01500` vs `0.41500` (`27.67x`) | n/a | `0.05692` nats/post | **`-3.32023` nats** (leaks!) | Explicit `"rumour: eXX"` subject prefix |
| `V16SocialProvider` Day-1 init (`facts.seed`) | `13 / 500` (`2.60%`, $z = +0.051$) | Depends on `facts.seed` | **`0.0000` nats** | **`0.0000` nats** | `0` forbidden prefixes, `0` vocab leaks |
| **Proposal P7.1 (`public_episode_digest`)** | **`12 / 500` (`2.40%`, $z = -0.232$)** | **`500 / 500` (`100.0%`)** | **`0.0000` nats** | **`0.0000` nats** | **`0` / `1,500` (`100.0%` snippet salience)** |

---

### 4.3 Proposal P4.1 / P7.3 Simulation: Dynamic Pretext Survival (`seeds 3000-3199`, $n = 200$)

| Checkpoint (`hard`, `seeds 3000-3199`, $n = 200$) | Surfaced Reg-Leak Worlds | Mean $\|C_{\text{reg}}(d)\|$ | Static Day-1 Focal Survival (`Eliminated`) | Dynamic **P4.1/P7.3** Survival in $C_{\text{reg}}(d)$ | Empirical `P(target == mole)` vs $\mathbb{E}[1/\|P_d\|]$ (`z`) | Day-5 Focal-Restriction Probe: Static vs Dynamic in $P_d$ |
|---|---:|---:|---:|---:|---:|---:|
| **Day 1** | `0 / 200` (`0.0%`) | `39.00` | `200 / 200` (`100.00%`, `0.00%` elim) | **`200 / 200` (`100.00%`)** | `0.0350` vs `0.0256` ($z = +0.837$) | `100.0%` vs **`100.0%`** |
| **Day 6** | `193 / 200` (`96.5%`) | `12.18` | `73 / 200` (`36.50%`, **`63.50%` elim**) | **`200 / 200` (`100.00%`)** | `0.1050` vs `0.1032` ($z = +0.086$, `LLR = 0.0000` cond.) | `0.0%` vs **`100.0%`** (`0.0900` vs `0.1018`) |
| **Day 12** | `200 / 200` (`100.0%`) | `8.39` | `38 / 200` (`19.00%`, **`81.00%` elim**) | **`200 / 200` (`100.00%`)** | `0.1150` vs `0.1295` ($z = -0.616$, `LLR = 0.0000` cond.) | `0.0%` vs **`100.0%`** (`0.1100` vs `0.1279`) |

*Key finding:* By Day 12, static Day-1 focal suspects are provably falsified by passive `check_leak_feed` + `list_documents` set intersection in **`81.00%`** (`162/200`) of `hard` worlds (`63.50%` by Day 6), and in **`100.0%`** of worlds if the investigator restricts the Day-1 focal suspect on Day 5. Re-anchoring onto $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ lifts pretext plausibility to **`100.00%`** across every checkpoint while maintaining exact conditional uniformity ($z = +0.086$ on Day 6, $z = -0.616$ on Day 12; exact conditional $I = 0.0000\text{ nats}$).

---

### 4.4 Proposal P1.1 (SUE) and Proposal P1.2 / P7.2 (Othello Scrutiny) Simulations

#### Table 4.4A: Proposal P1.1 Strategic Use of Evidence Regimes (`seeds 3000-3199`, $n = 200$, `sue_window_days = 6`)

| Interview Regime (`p_inn = 0.2000`) | Effective `LR` | `P(evasive \| mole)` | `LLR+` (Evasive) | `LLR-` (Cooperative) | `KL(Mole \|\| Inn.)` | Ratio vs Ungrounded | `plant_canary` MI / Interview KL |
|---|---:|---:|---:|---:|---:|---:|---:|
| `v1.4` `hard` baseline | `1.20` | `0.2400` | `+0.18232` nats | `-0.05129` nats | `0.00477` nats | `15.5x` | `181.4x` |
| **P1.1** ungrounded (`evidence_doc = None`) | `1.05` | `0.2100` | `+0.04879` nats | `-0.01258` nats | **`0.00031` nats** | `1.0x` | `2,800.8x` |
| **P1.1** SUE grounded (`evidence_doc` within `6d`) | `1.80` | `0.3600` | `+0.58779` nats | `-0.22314` nats | **`0.06879` nats** | **`222.8x`** (`14.4x` `v1.4`) | **`12.6x`** |

Across `seeds 3000-3199` ($n = 200$), **`96.5%`** (`193/200`) of worlds on Day 6 and **`97.5%`** (`195/200`) on Day 12 have at least one surfaced non-canary regular leak within the `6`-day SUE confrontation window, and deterministic keying on `f"{world_seed}:sue:{emp}:{doc_id}"` verified **`100.0%`** repeat-query invariance (`388/388` checkpoint checks), preventing single-document interview farming.

#### Table 4.4B: Proposal P1.2 / P7.2 Othello Public-Scrutiny Coupling (`OR = 24/19 = 1.263158`, `10,000` MC Trials)

| Public Scrutiny State `(r, m_<d)` | `P(evasive \| innocent)` | `P(evasive \| mole)` | State `KL` | Naive Flat-LR Innocent Drift / Interview | Calibrated `SolverPolicy` Innocent Drift / Interview | `SolverPolicy` Martingale Bias |
|---|---:|---:|---:|---:|---:|---:|
| `calm_unmentioned` `(r=0, m=0)` | `0.2000` | `0.2400` | `0.00477` nats | `-0.00457` (`-0.0046`) nats | `-0.00457` nats | `0.0000` |
| `focal_day3` `(r=0, m=2)` | `0.3200` | `0.3728` | `0.00624` nats | **`+0.02346` (`+0.0235`) nats** | `-0.00610` nats | `0.0000` |
| `focal_day6` `(r=0, m=4)` | `0.4400` | `0.4981` | `0.00680` nats | **`+0.05150` (`+0.0515`) nats** | `-0.00677` nats | `0.0000` |
| `restricted_only` `(r=1, m=0)` | `0.3400` | `0.3942` | `0.00640` nats | **`+0.02814` (`+0.0281`) nats** | `-0.00627` nats | `0.0000` |
| `restricted_focal` `(r=1, m=4)` | **`0.5200`** | `0.5778` | `0.00672` nats | **`+0.07019` (`+0.0702`) nats** | `-0.00677` nats | **`0.0000`** |

Monte Carlo simulation across `10,000` restricted-focal `(r=1, m=4)` innocent interviews (`random.Random("canary-p12-p72-othello-mc")`) confirms mean naive flat-LR false incrimination drift of **`+0.0691` nats/interview** (`+0.7019` nats theoretical across `10` interviews, inflating posterior odds by $e^{0.7019} = 2.02\times$ on an innocent suspect), while the public-state-conditioned likelihood ratio maintains empirical expectation **`0.9989`** (theoretical `1.0000`, `0.0000` bias).

---

### 4.5 Proposal P5.1 Surveillance Sleeper Mole and Proposal P8.2 Proxy Benchmark (`seeds 2000-2059`, $n = 60$)

Proposal **P5.1** specifies a valid, zero-protected-path `MoleStrategy` JSON (`canary/mole/dsl.py`) that triggers wide-document selection (`most_recipients`) only under early pinpoint canary surveillance (`day <= 4` and `recent_low_recipient_docs >= 2`) while routing framed `after_hours` logs onto `most_restricted_peer`:

```json
{
  "name": "surveillance_sleeper_p51",
  "rules": [
    {
      "if": [["day", "<=", 4], ["recent_low_recipient_docs", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "most_restricted_peer"}
}
```

Evaluating `default_v0`, `surveillance_sleeper_p51`, and the unconstrained stonewalling negative control `pure_most_recipients_neg` via `canary.forge.fitness.evaluate` on `v1.4` hard (`seeds 2000-2059`, $n = 60$, `min_solver_acc = 0.85`) yields:

| Mole Strategy (`v1.4` Hard, `seeds 2000-2059`, $n = 60$) | `SolverPolicy` Score (`Acc`) | `grok_tactics` Score (`Regret`) | `hinted_heuristic` Score (`Regret`) | `heuristic` Score (`Regret`) | **P8.2** `interview_crowded_proxy` Score (`Acc`, `Regret`) | 3-Inv `mean_regret` | 4-Inv `mean_regret` | `>= 85%` Feasible? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `pure_most_recipients_neg` (`most_recipients` / `most_restricted_peer`) | `0.3037` (**`55.0%`**) | n/a | n/a | n/a | n/a | n/a | n/a | **FAIL (`55.0% < 85.0%`)** |
| `default_v0` (`random_seeded` / `none`) | `0.5212` (**`93.3%`**) | `0.3693` (`+0.1518`) | `0.3758` (`+0.1453`) | `0.0348` (`+0.4863`) | `0.2433` (`85.0%`, `+0.2778`) | `+0.2612` (`min +0.1453`) | `+0.2653` | **PASS (`93.3%`)** |
| **`surveillance_sleeper_p51` (Proposal P5.1)** | **`0.5118` (`93.3%`)** | **`0.3525` (`+0.1593`)** | `0.3758` (`+0.1360`) | `0.0348` (`+0.4770`) | **`0.1735` (`75.0%`, `+0.3383`)** | `+0.2574` (`min +0.1360`) | **`+0.2777`** | **PASS (`93.3%`)** |

Three structural findings emerge directly from this paired $n = 60$ benchmark:
1. **Why unconstrained evasion fails catchability (`55.0%` vs `93.3%`):** Unconditionally choosing `most_recipients` (`16`-person two-department regular docs over `2-15`-person mid-game canaries) starves `SolverPolicy` below the `4.233`-trap information bound (`acc = 55.0% < 85.0%`, `feasible = False`), confirming Tessler et al. (2019). Conditioning `most_recipients` on `day <= 4` and `recent_low_recipient_docs >= 2` preserves **`93.3%`** `SolverPolicy` accuracy (`feasible = True`).
2. **Why Legacy 3-Investigator Evaluation Misses Restricted-Peer Framing:** Because `HintedHeuristic` and `Heuristic` never call `restrict_access` (`0` restricted frames), `surveillance_sleeper_p51` looks flat on 3-investigator `mean_regret` (`+0.2612 -> +0.2574`), even though it cuts `grok_tactics` from `0.3693` (`86.7%`) to `0.3525` (`83.3%`, `152` restricted frames, `4` rule-0 triggers).
3. **Why Proposal P8.2 (`InterviewCrowdedProxy`) Closes the Opponent-Model Gap:** `InterviewCrowdedProxy` replicates frontier action crowding (`55.55` interviews/episode and `12.87` canaries/episode under `default_v0`; `54.35` interviews/episode and `12.57` canaries/episode under `P5.1`) plus Day-3 `restrict_access`. Against `InterviewCrowdedProxy`, `surveillance_sleeper_p51` fires **`640` restricted-peer frames** and **`6` rule-0 sleeper evasions**, cutting proxy accuracy by **`-10.0pp` (`85.0% -> 75.0%`)**, cutting proxy score by **`-0.0698 V` (`0.2433 -> 0.1735`)**, raising proxy regret by **`+0.0605 V` (`+0.2778 -> +0.3383`)**, and flipping 4-investigator `mean_regret` strictly positive (`+0.2653 -> +0.2777`).

---

## 5. Integration Guardrails and Reproducibility Commands

All simulated proposals cleanly partition into **Zero-Protected-Path Drop-Ins** (`P7.1` in `canary/social/engine.py`, `P4.1/P7.3` in `canary/social/biases.py`, `P5.1` in `canary/mole/dsl.py` strategy JSONs and `train/grpo_mole.py`, and `P8.2` in `canary/forge/investigators.py` and `train/grpo_mole.py`) and **Opt-In Core Proposals for Silas** (`P1.1` `sue_interview: bool = False` and `P1.2/P7.2` `social_stress_coupling: bool = False` in `canary/rules.py`, `canary/env.py`, and `canary/solver/belief.py`, preserving `v1.4` frozen hash `a8f99c2537c91d72` when disabled).

Every table, theorem check, citation URL, and catchability gate in this monograph reproduces deterministically on CPU with zero API calls:

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/simulate_research_proposals.py --fast
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/simulate_research_proposals.py
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_research_deception.py --docs docs/research/10_proposal_simulations_and_zero_leakage_proofs.md --strict --strict-http --http --workers 2
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_research_deception.py --require-flagship --strict
/tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_simulate_research_proposals.py tests/test_research_deception.py
```
