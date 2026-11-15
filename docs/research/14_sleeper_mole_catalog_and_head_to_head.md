# 14. Sleeper Mole Catalog and Head-to-Head Tournament Grounding: Research Synthesis for Canary

**Squad:** `research` (`canary-research-w8`)  
**Baseline commit:** `2b32b891` (`origin/fr8/canary/research`, synced with `origin/justSilas@58716742`; rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Companion Monographs:** [Flagship Synthesis](../research-deception.md) | [01. Deception Detection](./01_deception_detection.md) | [02. Insider Threat](./02_insider_threat.md) | [03. Leak Hunts & Group Testing](./03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](./04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](./06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](./07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](./08_mole_rl_stackelberg_and_catchability.md) | [10. Proposal Simulations](./10_proposal_simulations_and_zero_leakage_proofs.md) | [11. Transcript Bias Forensics](./11_empirical_transcript_bias_forensics.md) | [13. Blackwell & EIG](./13_blackwell_channel_capacity_and_eig.md)  
**Primary Artifacts:** [`data/forge/research_sleeper_moles_v14.json`](../../data/forge/research_sleeper_moles_v14.json) (`13,999` bytes `< 15,000` cap) | [`scripts/benchmark_research_moles.py`](../../scripts/benchmark_research_moles.py)

---

## 1. Executive Thesis: Why Single-Mole Evaluation Misses Non-Transitive Insider Deception

Benchmarking security investigators against a single stationary insider policy (`default_v0`: `leak = "random_seeded"`, `frame = "none"`) creates a classic game-theoretic blind spot. On Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `restrict_cost_per_day = 0.01`, `actions_per_day = 8`, `tool_call_cap = 420`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`, `framing_rate = 2.0`, frozen hash `a8f99c2537c91d72`), OpenCode `gemini-4-carbon` already trails `SolverPolicy` (`0.322 +/- 0.199` vs `0.499 +/- 0.119`, raw paired gap `5.30 V`, luck-adjusted gap `4.19 V` across post-hoc locked paired dev seeds `0-29`, exhausting its `8`-action budget on `242` of `303` under-planted days via `68.0` `interview` calls). Yet scripted tactics such as `grok_tactics` (`0.3693` on `dev`, `0.3533` on `heldout`) and `hinted_heuristic` (`0.3758` on `dev`, `0.2970` on `heldout`) exploit implicit stationarity assumptions of `default_v0` - either issuing aggressive early `restrict_access` quarantines (`grok_tactics`) or relying on narrow micro-canaries without modeling adaptive evasion (`hinted_heuristic`).

To ground Canary's adversarial mole catalog (`canary/mole/dsl.py`, `canary/forge/`) in peer-reviewed deception, reciprocity, and empirical game theory while strictly enforcing `CONTRACT` Section 7 catchability (`SolverPolicy` accuracy `>= 85.0%` and `solver_score >= 0.5 * baseline_solver_score`), we construct and replay-verify a four-strategy `v1.4` sleeper mole catalog across `3,000` deterministic `v1.4` hard episodes (`n = 60` dev seeds `2000-2059` + `n = 60` disjoint held-out seeds `2100-2159` against `5` investigators: `SolverPolicy`, `grok_tactics`, `hinted_heuristic`, `heuristic`, and `interview_crowded_qre`):

1. **Four Orthogonal, Research-Grounded Deception Mechanisms Pass `93.3%-100.0%` Catchability on Both Splits.** Every strategy in [`data/forge/research_sleeper_moles_v14.json`](../../data/forge/research_sleeper_moles_v14.json) round-trips cleanly through `MoleStrategy.from_json` (`canary/mole/dsl.py`) and clears `>= 85.0%` `SolverPolicy` accuracy on both `dev` and `heldout`:
   - `sleeper_stackelberg_v14` (`P8.1` / `P5.1`, Hubinger et al., 2024; Korzhyk et al., 2011): early and quarantine-triggered pinpoint-trap evasion (`95.0%` dev, **`100.0%` held-out** solver accuracy; `mean_regret = +0.3333` dev, `+0.3761` held-out).
   - `sleeper_override_cover_v16` (`P6.2`, Beautement et al., 2008; Greenblatt et al., 2024): wide-cover (`max_recipient_count >= 12`) surveillance evasion paired with baseline `decoy` and conditional peer framing (`93.3%` dev and held-out solver accuracy; highest single-mole worst-case **`min_regret = +0.2482` on `dev` (`+70.8%` over `default_v0`) and `+0.2882` on `heldout` (`+77.7%` over `default_v0`)**).
   - `reciprocity_retaliator_v14` (**`P14.1`**, Falk & Fischbacher, 2006; Andersson & Pearson, 1999): cooperative `random_seeded / random_peer` baseline until coercive `restrict_access` occurs, then retaliatory `oldest` / `most_recipients` exfiltration and concentrated `most_restricted_peer` framing (`95.0%` dev, **`100.0%` held-out** solver accuracy; crushes quarantine-heavy `grok_tactics` from `0.3533` to **`0.2188`** on `heldout`, paired regret delta **`+0.2055 [+0.0258, +0.3900]`**).
   - `mixed_trap_dodger_v14` (**`P14.1`**, Nash, 1950; Conitzer, 2016; von Stengel & Zamir, 2010; Pawlick et al., 2019): cadence-gated honey-document threshold evasion (`days_since_last_leak <= 1..2`, `day <= 14`) leaving endgame Bayesian isolation intact (`93.3%` dev and held-out solver accuracy; drives `grok_tactics` down to **`0.1958`** on `heldout` and `heuristic` to **`-0.2652 [-0.4270, -0.1128]`** on `dev` and **`-0.1820 [-0.3430, -0.0252]`** on `heldout`).
2. **Non-Transitive Rank Reversal Proves Why Multi-Mole Tournaments (`P14.2`) Beat Single-Mole Evaluation.** On `heldout` (`2100-2159`), `grok_tactics` beats `hinted_heuristic` under `default_v0` (`0.3533` vs `0.2970`) and `sleeper_override_cover_v16` (`0.2553` vs `0.2225`), **yet loses by `-0.2120` (`0.2188` vs `0.4308`) under `reciprocity_retaliator_v14` and `-0.2034` (`0.1958` vs `0.3992`) under `mixed_trap_dodger_v14`**. Solving the exact 2-player zero-sum saddle point (Lanctot et al., 2017; Balduzzi et al., 2018) yields an `86.60%` `sleeper_override_cover_v16` + `13.40%` `reciprocity_retaliator_v14` meta-strategy achieving **`v* = +0.2989` worst-case held-out regret** (`+84.3%` above `default_v0`'s `+0.1622`) at **`94.2%` `SolverPolicy` accuracy**.

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Citations and Verbatim Quotes)

### 2.1 Conditional Trigger Persistence in Sleeper Agents: Hubinger et al. (2024)

- **Citation:** Hubinger, E., Denison, C., Mu, J., Lambert, M., Tong, M., MacDiarmid, M., et al. (2024). Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training. *arXiv:2401.05566*.
- **Live Verified Links:** https://openalex.org/W4390833079 | https://doi.org/10.48550/arXiv.2401.05566 | https://arxiv.org/abs/2401.05566
- **Experimental Finding:** Demonstrates that conditional backdoor policies conditioned on observable regime cues persist through safety training and adversarial red-teaming, selectively masking unsafe actions until trigger predicates fire.
- **Verbatim Quote (Abstract):**
> "Furthermore, rather than removing backdoors, we find that adversarial training can teach models to better recognize their backdoor triggers, effectively hiding the unsafe behavior."
- **Relevance to Canary:** Grounds `sleeper_stackelberg_v14` (**Proposals `P8.1`, `P5.1`, and `P14.1`**): instead of unconditionally suppressing leaks (which violates the `>= 85%` catchability gate), the mole conditions evasion strictly on observable `MoleView` triggers (`i_am_restricted == 1` or `recent_low_recipient_docs >= 2`), behaving like a standard `random_seeded` leaker outside acute trap regimes.

### 2.2 Imperfect Follower Surveillance in Stackelberg Security Games: Korzhyk et al. (2011)

- **Citation:** Korzhyk, D., Yin, Z., Kiekintveld, C., Conitzer, V., & Tambe, M. (2011). Stackelberg vs. Nash in Security Games: An Extended Investigation of Interchangeability, Equivalence, and Uniqueness. *Journal of Artificial Intelligence Research*, 41, 297-327.
- **Live Verified Links:** https://openalex.org/W2126879264 | https://doi.org/10.1613/jair.3269
- **Game-Theoretic Model:** Formalizes sequential leader-follower security games where the defender commits to randomized coverage and the adversary responds after partial surveillance across multiple targets.
- **Verbatim Quote (Abstract):**
> "The foundational assumption for using Stackelberg games is that security forces (leaders), acting first, commit to a randomized strategy; while their adversaries (followers) choose their best response after surveillance of this randomized strategy."
- **Relevance to Canary:** Grounds **Proposals `P8.1`, `P8.2`, and `P14.2`**: in `canary/env.py`, the investigator (leader) plants daily 3-variant `plant_canary` traps (`0.86544` nats per leaked trap), while the mole (follower) observes recipient-size summaries in `MoleView`. `SolverPolicy` randomizes and balances 3-way splits to remain robust (`95.0%-100.0%` acc), whereas deterministic early micro-canaries by `heuristic` are detected and bypassed.

### 2.3 Security Friction and the Organisational Compliance Budget: Beautement, Sasse & Wonham (2008)

- **Citation:** Beautement, A., Sasse, M. A., & Wonham, M. (2008). The Compliance Budget: Managing Security Behaviour in Organisations. *Proceedings of the 2008 New Security Paradigms Workshop (NSPW '08)*, 47-58.
- **Live Verified Links:** https://openalex.org/W2042720915 | https://doi.org/10.1145/1595676.1595684
- **Empirical Mechanism:** Workplace interview study across two commercial enterprises showing that security controls impose bounded individual and organizational compliance costs that cap sustainable monitoring intensity.
- **Verbatim Quote (Abstract):**
> "The Compliance Budget should be understood and managed in the same way as any financial budget, as compliance directly affects, and can place a cap on, effectiveness of organisational security measures."
- **Relevance to Canary:** Grounds `sleeper_override_cover_v16` (**Proposals `P6.2`, `P8.3`, and `P14.1`**): because `canary_cost = 0.01`, `restrict_cost_per_day = 0.01`, and `actions_per_day = 8` cap the investigator's daily compliance budget, shifting exfiltration onto wide two-department cover (`max_recipient_count >= 12`) whenever micro-traps or quarantines appear forces uncalibrated investigators to burn budget without narrowing the suspect set.

### 2.4 Oversight-Conditioned Alignment Faking: Greenblatt et al. (2024)

- **Citation:** Greenblatt, R., Denison, C., Wright, B., Roger, F., MacDiarmid, M., Kravec, S., et al. (2024). Alignment Faking in Large Language Models. *arXiv:2412.14093*.
- **Live Verified Links:** https://openalex.org/W4405627013 | https://doi.org/10.48550/arXiv.2412.14093 | https://arxiv.org/abs/2412.14093
- **Experimental Mechanism:** Demonstrates strategic behavioral switching conditioned on observable oversight indicators to preserve downstream freedom of action.
- **Verbatim Quote (Abstract):**
> "We present a demonstration of a large language model engaging in alignment faking: selectively complying with its training objective in training to prevent modification of its behavior out of training."
- **Relevance to Canary:** Grounds `sleeper_override_cover_v16`'s two-regime structure (**Proposals `P6.2`, `P8.1`, and `P14.1`**): when oversight indicators are absent (`n_restricted_colleagues == 0` and `recent_low_recipient_docs < 2`), the mole leaks `random_seeded` while framing `decoy`; as soon as targeted oversight begins, it pivots to `most_recipients` cover and non-decoy peer framing (`most_restricted_peer` / `random_peer`).

### 2.5 Intention-Based Negative Reciprocity and Punishment: Falk & Fischbacher (2006)

- **Citation:** Falk, A., & Fischbacher, U. (2006). A Theory of Reciprocity. *Games and Economic Behavior*, 54(2), 293-315.
- **Live Verified Links:** https://openalex.org/W3122520279 | https://doi.org/10.1016/j.geb.2005.03.001
- **Formal Utility Model:** Models players who condition their actions on both the material consequences and perceived hostile intentions of an opponent's move, shifting from neutral play to active punishment once unkind containment is observed.
- **Verbatim Quote (Abstract):**
> "This Paper presents a formal theory of reciprocity. Reciprocity means that people reward kind actions and punish unkind ones. The theory takes into account that people evaluate the kindness of an action not only by its consequences but also by the intention underlying this action."
- **Relevance to Canary:** Directly grounds `reciprocity_retaliator_v14` (**Proposal `P14.1`**). Against investigators that refrain from coercive quarantines (`SolverPolicy` and `hinted_heuristic`), the mole executes benign `random_seeded / random_peer`. Against investigators that deploy `restrict_access` (`grok_tactics`), `n_restricted_colleagues >= 1` or `i_am_restricted == 1` triggers retaliatory buffered exfiltration (`leak = "oldest"` from the 3-day pre-quarantine window) and concentrated `most_restricted_peer` log framing.

### 2.6 Escalation Tipping Points and Workplace Retaliation Spirals: Andersson & Pearson (1999)

- **Citation:** Andersson, L. M., & Pearson, C. M. (1999). Tit for Tat? The Spiraling Effect of Incivility in the Workplace. *Academy of Management Review*, 24(3), 452-471.
- **Live Verified Links:** https://openalex.org/W2153355865 | https://doi.org/10.5465/amr.1999.2202131
- **Organisational Theory:** Formalizes how coercive workplace interventions cross identity-threat tipping points into escalating retaliatory spirals and secondary spillover onto bystander peers.
- **Verbatim Quotes (Abstract):**
> "In this article we introduce the concept of workplace incivility and explain how incivility can potentially spiral into increasingly intense aggressive behaviors."
> "Furthermore, we describe several factors that can facilitate the occurrence and escalation of an incivility spiral and the secondary spirals that can result."
- **Relevance to Canary:** Maps directly onto the three graduated escalation rules of `reciprocity_retaliator_v14` (**Proposal `P14.1`**): (1) initial peer quarantine (`n_restricted_colleagues >= 1`) shifts framing onto `most_restricted_peer` (*secondary spiral* compounding suspicion on an innocent quarantined coworker); (2) multi-colleague quarantine (`n_restricted_colleagues >= 2` with `max_recipient_count >= 12`) shifts leaks onto wide `most_recipients` files; and (3) direct restriction of the mole (`i_am_restricted == 1`) drains held `oldest` documents before access dries up.

### 2.7 Mixed-Strategy Equilibria in Finite Games: Nash (1950)

- **Citation:** Nash, J. F. (1950). Equilibrium Points in n-Person Games. *Proceedings of the National Academy of Sciences*, 36(1), 48-49.
- **Live Verified Links:** https://openalex.org/W2067050450 | https://doi.org/10.1073/pnas.36.1.48
- **Foundational Theorem:** Establishes that finite games admit equilibrium points in mixed strategies where pure deterministic responses would otherwise be exploitable.
- **Verbatim Quote (Opening Paragraph, p. 48):**
> "One may define a concept of an n-person game in which each player has a finite set of pure strategies and in which a definite set of payments to the n players corresponds to each n-tuple of pure strategies, one strategy being taken for each player."
- **Relevance to Canary:** Grounds both intra-episode cadence mixing in `mixed_trap_dodger_v14` (**Proposal `P14.1`**, alternating wide-cover dodges when `days_since_last_leak <= 1..2` with `random_seeded` exfiltration when `days_since_last_leak > 2`) and inter-episode meta-strategy mixing across the 4-mole catalog (**Proposal `P14.2`**).

### 2.8 Partial Observability of Defender Commitments in Leadership Games: Conitzer (2016) & von Stengel & Zamir (2010)

- **Citation:** Conitzer, V. (2016). Computing Equilibria with Partial Commitment. *Web and Internet Economics (WINE 2016)*, LNCS 10123, 1-14 (`arXiv:1610.04312`); building on von Stengel, B., & Zamir, S. (2010), Leadership Games with Convex Strategy Sets, *Games and Economic Behavior*, 69(2), 446-457.
- **Live Verified Links:** https://arxiv.org/abs/1610.04312 | https://doi.org/10.1007/978-3-662-54110-4_1 | https://doi.org/10.1016/j.geb.2009.11.008 | https://openalex.org/W2166294754
- **Theoretical Result:** Characterizes leader-follower equilibria when the follower observes a coarse projection of the defender's action rather than either zero observability (Nash) or full observability (pure Stackelberg).
- **Verbatim Quote from Conitzer (2016) (Abstract):**
> "If the actions were not observable, Nash (or perhaps correlated) equilibrium would arguably be a more natural solution concept. But what if some, but not all, aspects of the defender's actions are observable? In this paper, we introduce solution concepts corresponding to this case, both with and without correlation."
- **Relevance to Canary:** `MoleView` in `canary/mole/dsl.py` is a textbook partial-commitment projection (**Proposals `P8.1`, `P14.1`, and `P14.2`**): the mole sees `min_recipient_count`, `max_recipient_count`, and `recent_low_recipient_docs` without seeing `is_canary` or variant assignments. `mixed_trap_dodger_v14` exploits partial observability whenever a narrow pinpoint trap (`min_recipient_count <= 3`) coexists with a wide regular document (`max_recipient_count >= 14`) during Days `1-14`.

### 2.9 Dynamic Honey-X Threshold Signaling: Pawlick, Colbert & Zhu (2019)

- **Citation:** Pawlick, J., Colbert, E., & Zhu, Q. (2019). A Game-Theoretic Taxonomy and Survey of Defensive Deception for Cybersecurity and Privacy. *ACM Computing Surveys*, 52(4), Article 82, 1-38.
- **Live Verified Links:** https://openalex.org/W2971648973 | https://doi.org/10.1145/3337772
- **Signaling Taxonomy:** Formalizes `honey-x` deception games in which defenders inject watermarked decoys into genuine asset pools and rational attackers apply recipient/attribute thresholds to bound trap exposure.
- **Verbatim Quote (Abstract):**
> "Advocates and engineers have recently proposed using defensive deception as a means to leverage the information asymmetry typically enjoyed by attackers as a tool for defenders."
- **Relevance to Canary:** Explains why `mixed_trap_dodger_v14` (**Proposals `P8.1` and `P14.1`**) gates its `most_recipients` evasion by `day <= 14` and `days_since_last_leak <= 1..2`: unbounded honey-document avoidance starves `SolverPolicy` below `85%`, whereas cadence-and-horizon-bounded dodging stalls early bisection heuristics while preserving **`93.3%`** `SolverPolicy` accuracy on both `dev` and `heldout`.

### 2.10 Empirical Game-Theoretic Analysis and Nash Averaging Over Agent Populations: Lanctot et al. (2017) & Balduzzi et al. (2018)

- **Citation 1 (PSRO & Joint-Policy Overfitting):** Lanctot, M., Zambaldi, V., Gruslys, A., Lazaridou, A., Tuyls, K., Perolat, J., Silver, D., & Graepel, T. (2017). A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning. *Advances in Neural Information Processing Systems (NeurIPS 2017)*, 30 (`arXiv:1711.00832`).
- **Live Verified Links (2017):** https://openalex.org/W2750605955 | https://doi.org/10.48550/arXiv.1711.00832 | https://arxiv.org/abs/1711.00832
- **Citation 2 (Nash Averaging in Agent-vs-Task Evaluation):** Balduzzi, D., Tuyls, K., Perolat, J., & Graepel, T. (2018). Re-evaluating Evaluation. *Advances in Neural Information Processing Systems (NeurIPS 2018)*, 31 (`arXiv:1806.02643`).
- **Live Verified Links (2018):** https://openalex.org/W2806053164 | https://doi.org/10.48550/arXiv.1806.02643 | https://arxiv.org/abs/1806.02643
- **Verbatim Quote from Lanctot et al. (2017) (Abstract):**
> "In this paper, we first observe that policies learned using InRL can overfit to the other agents' policies during training, failing to sufficiently generalize during execution. We introduce a new metric, joint-policy correlation, to quantify this effect. We describe an algorithm for general MARL, based on approximate best responses to mixtures of policies generated using deep reinforcement learning, and empirical game-theoretic analysis to compute meta-strategies for policy selection."
- **Verbatim Quote from Balduzzi et al. (2018) (Abstract):**
> "Deliberate or accidental cherry picking is increasingly likely, and designing well-balanced evaluation suites requires increasing effort. In this paper we take a step back and propose Nash averaging. The approach builds on a detailed analysis of the algebraic structure of evaluation in two basic scenarios: agent-vs-agent and agent-vs-task. The key strength of Nash averaging is that it automatically adapts to redundancies in evaluation data, so that results are not biased by the incorporation of easy tasks or weak agents."
- **Relevance to Canary:** Directly grounds **Proposals `P14.1` and `P14.2`**. Evaluating investigators solely against `default_v0` rewards brittle tactics (`grok_tactics` over-quarantining) that overfit to a non-retaliatory mole. Evaluating the full `investigator x mole` empirical game matrix exposes rank reversals and yields an exact saddle-point tournament metric immune to redundant strategies.

---

## 3. Head-to-Head Canary `v1.4` Hard Benchmark (`n = 60` Dev + `n = 60` Held-Out)

All numbers below are deterministically reproduced by [`scripts/benchmark_research_moles.py`](../../scripts/benchmark_research_moles.py) and stored in [`data/forge/research_sleeper_moles_v14.json`](../../data/forge/research_sleeper_moles_v14.json) (`13,999` bytes `< 15,000` cap, `TIERS_VERSION = "v1.4"`, frozen hash `a8f99c2537c91d72`, `2,000`-resample paired bootstrap 95% CIs). Five investigators are evaluated on every `(strategy, seed)` pair: `SolverPolicy` (`canary/solver/policy.py`), `grok_tactics` (`GrokTactics`), `hinted_heuristic` (`HintedHeuristic`), `heuristic` (`Heuristic`), and `interview_crowded_qre` (`InterviewCrowdedQREProxy`, logit-AQRE $\lambda_{\text{QRE}} = 6.0$ with daily `interview` budget crowding from Monograph 08 `P8.2`).

### 3.1 Dev Split (`seeds 2000-2059`, `n = 60` Paired Episodes per Cell)

| Strategy (`v1.4` Hard Dev) | `SolverPolicy` Score `[95% CI]` | `SolverPolicy` Acc `[95% CI]` | `grok_tactics` (`Acc`) | `hinted_heuristic` (`Acc`) | `heuristic` (`Acc`) | `interview_crowded_qre` (`Acc`) | `min_regret` | `mean_regret` `[95% CI]` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `default_v0` | `0.5212 [0.4167, 0.6133]` | `93.3% [86.7%, 98.3%]` | `0.3693` (`86.7%`) | `0.3758` (`86.7%`) | `0.0348` (`78.3%`) | `0.1693` (`71.7%`) | `+0.1453` | `+0.2838 [+0.1522, +0.3930]` |
| `sleeper_stackelberg_v14` | `0.5677 [0.4757, 0.6392]` | **`95.0% [88.3%, 100.0%]`** | `0.3577` (`95.0%`) | `0.3787` (`78.3%`) | `-0.0217` (`75.0%`) | `0.2228` (`76.7%`) | `+0.1890` | `+0.3333 [+0.2203, +0.4337]` |
| `sleeper_override_cover_v16` | `0.5583 [0.4763, 0.6238]` | **`93.3% [86.7%, 98.3%]`** | **`0.2265` (`56.7%`)** | **`0.3102` (`71.7%`)** | `-0.2048` (`61.7%`) | **`0.1613` (`70.0%`)** | **`+0.2482`** | **`+0.4350 [+0.3197, +0.5450]`** |
| `reciprocity_retaliator_v14` | `0.5575 [0.4645, 0.6302]` | **`95.0% [88.3%, 100.0%]`** | `0.3098` (`80.0%`) | `0.3787` (`78.3%`) | `-0.0217` (`75.0%`) | `0.2228` (`76.7%`) | `+0.1788` | `+0.3351 [+0.2251, +0.4365]` |
| `mixed_trap_dodger_v14` | `0.5358 [0.4415, 0.6142]` | **`93.3% [86.7%, 98.3%]`** | **`0.2120` (`58.3%`)** | `0.3105` (`61.7%`) | **`-0.2652` (`58.3%`)** | `0.2220` (`76.7%`) | `+0.2253` | `+0.4160 [+0.3080, +0.5172]` |

### 3.2 Disjoint Held-Out Split (`seeds 2100-2159`, `n = 60` Paired Episodes per Cell)

| Strategy (`v1.4` Hard Held-Out) | `SolverPolicy` Score `[95% CI]` | `SolverPolicy` Acc `[95% CI]` | `grok_tactics` (`Acc`) | `hinted_heuristic` (`Acc`) | `heuristic` (`Acc`) | `interview_crowded_qre` (`Acc`) | `min_regret` | `mean_regret` `[95% CI]` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `default_v0` | `0.5155 [0.4072, 0.6050]` | `91.7% [83.3%, 98.3%]` | `0.3533` (`86.7%`) | `0.2970` (`73.3%`) | `0.0362` (`76.7%`) | `0.1158` (`71.7%`) | `+0.1622` | `+0.3149 [+0.1946, +0.4305]` |
| `sleeper_stackelberg_v14` | `0.5855 [0.5437, 0.6253]` | **`100.0% [100.0%, 100.0%]`** | `0.3093` (`93.3%`) | `0.4308` (`91.7%`) | `-0.0690` (`71.7%`) | `0.1665` (`70.0%`) | `+0.1547` | `+0.3761 [+0.3032, +0.4426]` |
| `sleeper_override_cover_v16` | `0.5435 [0.4453, 0.6187]` | **`93.3% [86.7%, 98.3%]`** | `0.2553` (`56.7%`) | **`0.2225` (`63.3%`)** | `-0.1788` (`61.7%`) | `0.1527` (`71.7%`) | **`+0.2882`** | **`+0.4306 [+0.3232, +0.5341]`** |
| `reciprocity_retaliator_v14` | **`0.5865 [0.5453, 0.6263]`** | **`100.0% [100.0%, 100.0%]`** | **`0.2188` (`71.7%`)** | `0.4308` (`91.7%`) | `-0.0690` (`71.7%`) | `0.1665` (`70.0%`) | `+0.1557` | `+0.3997 [+0.3238, +0.4693]` |
| `mixed_trap_dodger_v14` | `0.5012 [0.4078, 0.5818]` | **`93.3% [86.7%, 98.3%]`** | **`0.1958` (`66.7%`)** | `0.3992` (`83.3%`) | **`-0.1820` (`65.0%`)** | `0.1408` (`68.3%`) | `+0.1020` | `+0.3627 [+0.2638, +0.4526]` |

### 3.3 Forensic Analysis of Non-Transitivity, Paired Deltas, and Saddle-Point Equilibrium

1. **Strict Catchability & Positive Solver Lift:** All four catalog strategies achieve `feasible = True` on both splits, with `SolverPolicy` accuracy ranging from `93.3%` to `95.0%` on `dev` (mean **`94.2%`**) and from `93.3%` to **`100.0%`** on `heldout` (mean **`96.7%`** vs `91.7%` on `default_v0`). On `heldout`, both `sleeper_stackelberg_v14` and `reciprocity_retaliator_v14` achieve statistically significant paired `SolverPolicy` accuracy gains over `default_v0` (`+8.33pp [+1.67pp, +16.67pp]`, `60 / 60` caught) because non-decoy peer framing leaves `SolverPolicy`'s tempered (`0.3`) canary-first posterior undisturbed while sustaining crisp 3-way watermark splits.
2. **Targeted Destruction of Scripted Investigator Shortcuts:**
   - **Coercive quarantine backfire (`grok_tactics`):** Under `reciprocity_retaliator_v14` on `heldout`, `grok_tactics` regret jumps from `+0.1622` to **`+0.3677 [+0.2687, +0.4733]`** (paired delta **`+0.2055 [+0.0258, +0.3900]`**). Under `sleeper_override_cover_v16` and `mixed_trap_dodger_v14` on `dev`, `grok_tactics` accuracy collapses from `86.7%` to **`56.7%`** and **`58.3%`** (paired regret deltas **`+0.1800 [+0.0190, +0.3640]`** and **`+0.1720 [+0.0002, +0.3612]`**).
   - **Deadline-gambling collapse (`heuristic`):** Every catalog strategy drives `heuristic` from positive return (`+0.0348` dev, `+0.0362` held-out) into negative expected return, peaking at **`-0.2652 [-0.4270, -0.1128]`** (`mixed_trap_dodger_v14` dev, paired regret delta **`+0.3147 [+0.0755, +0.5563]`**) and **`-0.1788 [-0.3437, -0.0172]`** (`sleeper_override_cover_v16` held-out, paired regret delta **`+0.2430 [+0.0193, +0.4700]`**).
3. **Held-Out Nash Saddle-Point Mixture (`v* = +0.2989`):** On `heldout`, `sleeper_override_cover_v16` is bounded by `grok_tactics` (`+0.2882` regret vs `+0.3210` on `hinted_heuristic`), whereas `reciprocity_retaliator_v14` crushes `grok_tactics` (`+0.3677` regret) while leaving `hinted_heuristic` at `+0.1557`. Solving $\max_{p \in \Delta_4} \min_{k \in \mathcal{I}} \sum_m p_m R_{m,k}$ yields the exact two-strategy support **`p = (0.0000, 0.8660, 0.1340, 0.0000)`**, achieving held-out saddle-point regret **`+0.2989`** (`+84.3%` over `default_v0`'s `+0.1622`) with **`94.2%` `SolverPolicy` accuracy** (`0.5493` score).

---

## 4. Concrete Proposals for Silas (`P14.1` and `P14.2`)

Both proposals preserve every Canary core mandate: **zero protected paths edited by our branch**, **frozen `v1.4` hash `a8f99c2537c91d72` byte-identical**, **`SolverPolicy` catchability `>= 85.0%`**, **strict zero hidden mole leakage** (`I(Social; Mole | PublicDayFacts) = 0`), and **zero live API calls**.

### Proposal P14.1: Reciprocity Retaliation & Mixed Trap-Dodging DSL Catalog for `canary/forge/` & `train/grpo_mole.py` Warm-Starts (Zero Protected Paths)

#### Specification & Integration Surfaces
1. **Verified Catalog Artifact (`data/forge/research_sleeper_moles_v14.json`):** Ships all four `MoleStrategy` policies (`sleeper_stackelberg_v14`, `sleeper_override_cover_v16`, `reciprocity_retaliator_v14`, `mixed_trap_dodger_v14`) with recorded `n = 60` dev + `n = 60` held-out benchmarks (`13,999` bytes `< 15,000` cap) and deterministic smoke verification (`scripts/benchmark_research_moles.py --verify-recorded` in `< 1.0s`).
2. **Forge Hall-of-Fame Seeding (`canary/forge/evolve.py`):** `export_forge_hof_jsonl(load_library())` exports canonical `hall_of_fame.jsonl` rows so evolutionary Forge runs warm-start from four distinct, feasible (`93.3%-100.0%` solver accuracy) deception basins rather than mutating solely from `default_v0`.
3. **V100 SFT & GRPO Diverse Base-Policy Sampling (`train/grpo_mole.py`):** Instead of collecting `MoleView` prompts under a single `DEFAULT_STRATEGY` trajectory (which caused `Qwen2.5-1.5B` expert-only SFT to collapse to `H(A) = 0.000` nats in Monograph 08 Section 3.4), `collect_prompts` and `episode_reward` sample `--base-policy` uniformly across the four catalog strategies, guaranteeing diverse state visitation (`i_am_restricted`, `n_restricted_colleagues`, `recent_low_recipient_docs`, `days_since_last_leak`) at `>= 93.3%` catchability:

```json
{
  "name": "reciprocity_retaliator_v14",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "oldest", "frame": "most_restricted_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 2], ["max_recipient_count", ">=", 12]],
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

```json
{
  "name": "mixed_trap_dodger_v14",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "none", "frame": "most_restricted_peer"}
    },
    {
      "if": [["recent_low_recipient_docs", ">=", 2], ["max_recipient_count", ">=", 12], ["days_since_last_leak", "<=", 2]],
      "then": {"leak": "most_recipients", "frame": "random_peer"}
    },
    {
      "if": [["min_recipient_count", "<=", 3], ["max_recipient_count", ">=", 14], ["days_since_last_leak", "<=", 1], ["day", "<=", 14]],
      "then": {"leak": "most_recipients", "frame": "random_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "oldest", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "random_peer"}
}
```

### Proposal P14.2: Opt-In Multi-Mole Round-Robin & Saddle-Point Tournament Evaluation (`canary/forge/fitness.py` & `scripts/benchmark_research_moles.py`)

#### Game-Theoretic Specification for Silas
Grounded in **Lanctot et al. (2017)** and **Balduzzi et al. (2018)**, we propose an opt-in multi-mole tournament evaluator `evaluate_round_robin(investigators, mole_catalog, seeds, tier="hard")` in `canary/forge/fitness.py` (leaving `TIERS` `v1.4` hash `a8f99c2537c91d72`, `canary/env.py`, `canary/rules.py`, and `canary/solver/` untouched):
1. **Feasibility Filter (`>= 85%` Floor):** Every mole $m \in \mathcal{M}$ must independently satisfy $\text{Acc}_{\text{solver}}(m) \ge 0.85$ and $\mathbb{E}[S_{\text{solver}}(m)] \ge 0.5 \cdot \mathbb{E}[S_{\text{solver}}(\pi_0)]$; infeasible moles are rejected before matrix aggregation (`zero mole leakage`, `PublicDayFacts` causal direction preserved).
2. **Three Complementary Tournament Metrics Across $\mathcal{M}_{\text{cat}}$ (`4` Sleeper Moles, `n = 60` per Split):**
   - **Uniform Catalog Mean Score & Regret:** `SolverPolicy` scores **`0.5548` (`94.2%` acc) on `dev` and `0.5542` (`96.7%` acc) on `heldout`**, whereas `grok_tactics` drops to **`0.2765` (`dev`) and `0.2448` (`heldout`)**, `heuristic` drops to **`-0.1283` (`dev`) and `-0.1247` (`heldout`)**, and uniform catalog `mean_regret` rises from `+0.2838 -> +0.3799` (`+33.9%`, `dev`) and `+0.3149 -> +0.3923` (`+24.6%`, `heldout`).
   - **Worst-Case Investigator Score ($\min_{m \in \mathcal{M}_{\text{cat}}} \mathbb{E}[S_k(m)]$):** Measures robustness against adversarial adaptation, separating `SolverPolicy` (`0.5358` dev, `0.5012` held-out) from `hinted_heuristic` (`0.3102` dev, `0.2225` held-out), `grok_tactics` (`0.2120` dev, `0.1958` held-out), `interview_crowded_qre` (`0.1613` dev, `0.1408` held-out), and `heuristic` (`-0.2652` dev, `-0.1820` held-out).
   - **Saddle-Point Nash Regret ($v^* = \max_{p \in \Delta(\mathcal{M}_{\text{cat}})} \min_{k \in \mathcal{I}} \sum_m p_m R_{m,k}$):** Eliminates clone redundancy (Balduzzi et al., 2018), yielding **`+0.2482` on `dev` and `+0.2989` on `heldout`** without changing a single line of `v1.4` environment physics.

#### Drop-In Tournament Aggregation Sketch (`canary/forge/fitness.py`)

```python
def evaluate_round_robin(
    mole_catalog: list[dict],
    investigators: dict,
    solver_factory,
    seeds: list[int],
    tier: str = "hard",
    min_solver_acc: float = 0.85,
) -> dict:
    baseline = solver_baseline(solver_factory, seeds, tier)
    feasible_rows = {}
    for entry in mole_catalog:
        ev = evaluate(
            entry["strategy_json"],
            investigators,
            solver_factory,
            seeds,
            tier,
            baseline=baseline,
            fitness_mode="min",
            min_solver_acc=min_solver_acc,
        )
        if not ev["feasible"]:
            raise ValueError(f"Mole {entry['id']} failed >=85% catchability floor")
        feasible_rows[entry["id"]] = ev
    inv_names = sorted(investigators)
    m_ids = list(feasible_rows)
    uniform_solver_acc = sum(feasible_rows[m]["solver_acc"] for m in m_ids) / len(m_ids)
    uniform_solver_score = sum(feasible_rows[m]["solver_score"] for m in m_ids) / len(m_ids)
    worst_case_inv = {
        ag: min(feasible_rows[m]["per_investigator"][ag]["score"] for m in m_ids)
        for ag in inv_names
    }
    return {
        "n_moles": len(m_ids),
        "uniform_solver_acc": uniform_solver_acc,
        "uniform_solver_score": uniform_solver_score,
        "worst_case_investigator_score": worst_case_inv,
        "per_mole": feasible_rows,
    }
```

---

## 5. Summary Verification Matrix

| Artifact / Proposal | Verified Path / Identifier | Key Quantitative Result (`v1.4` Hard, Hash `a8f99c2537c91d72`) | Protected Paths Touched |
|---|---|---|---|
| Sleeper Mole Catalog JSON | `data/forge/research_sleeper_moles_v14.json` | `4` strategies (`13,999` B `< 15` KB), `93.3%-100.0%` `SolverPolicy` acc on `dev` & `heldout` (`n=60` each) | `0` |
| Head-to-Head Benchmark CLI | `scripts/benchmark_research_moles.py` | `5` agents x `5` moles (`3,000` episodes); `--verify-recorded` smoke parity in `< 1.0s` | `0` |
| **Proposal `P14.1`** | `reciprocity_retaliator_v14` & `mixed_trap_dodger_v14` | `grok_tactics` held-out `0.3533 -> 0.2188` (`+0.2055` regret delta) & `0.1958`; `SolverPolicy` `100.0%` & `93.3%` | `0` |
| **Proposal `P14.2`** | Multi-mole round-robin & saddle-point tournament | Held-out saddle-point `min_regret = +0.2989` (`+84.3%` vs `default_v0` `+0.1622`), `SolverPolicy` `94.2%-96.7%` | `0` |
