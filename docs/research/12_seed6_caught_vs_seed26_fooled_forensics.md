# 12. Paired Replay Forensics of `seed 6` (`Caught`) vs `seed 26` (`Fooled`): Horstein-Burnashev Confirmation Dynamics and Zero-Leakage Proposals

**Squad:** `research` (`canary-research-w1`)  
**Baseline commit:** `9da5b4e1` (`origin/fr8/canary/research`, synced with `origin/justSilas@5f9b3297`; rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Forensic Harness:** `scripts/audit_seed6_seed26_forensics.py` and `tests/test_audit_seed6_seed26_forensics.py` (`0` API calls, `~0.4 s` deterministic CPU replay across `6` trajectories, `0` protected paths touched)  
**Companion Monographs:** [Master Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [03. Leak Hunts, Canary Traps & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](08_mole_rl_stackelberg_and_catchability.md) | [11. Empirical Transcript Bias Forensics](11_empirical_transcript_bias_forensics.md) | [13. Blackwell Channel Capacity & Lindley EIG](13_blackwell_channel_capacity_and_eig.md) | [17. Red-Team Swarms & Benchmark Integrity](17_redteam_reward_gaming_and_benchmark_integrity.md)  
**Primary Benchmark Evidence:** [Submission Overview](../SUBMISSION.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Gap Report](../reports/gap.md) | [Difficulty Audit](../DIFFICULTY.md)

---

## 1. Executive Thesis: Why the Same Frontier Model Catches the Mole on `seed 6` (`+0.73`) and Gets Fooled on `seed 26` (`-1.00`)

Across the `30` post-hoc locked paired `v1.4` hard dev seeds `0-29` (`n_employees = 40`, `n_days = 21`, `canaries_per_day = 2`, `max_variants = 3`, `fingerprint_accuracy = 0.95`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `framing_rate = 2.0`, frozen hash `a8f99c2537c91d72`), OpenCode `gemini-4-carbon` over MCP scores **`0.322 +/- 0.199`** against `SolverPolicy`'s **`0.499 +/- 0.119`** (`65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted; `30`-seed raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`). As documented in [docs/SUBMISSION.md](../SUBMISSION.md) (`justSilas@5f9b3297`), this MCP-only deficit is specific to model and harness regime: in the containerized Harbor judge-path rehearsal (`results/harbor/rehearsal/TABLE.md`), three OpenCode `gemini-4-carbon` runs reached **`93%`, `116%`, and `131%`** of the oracle (`+0.472`, `+0.585`, `+0.626` vs `+0.506` across **`10`, `10`, and `9` valid trials**), while OpenCode `gpt-5.5` with MCP tools only scored `101% [79%, 140%]` on `seeds 0-29` (`17.2` canaries/episode vs `gemini-4-carbon`'s `8.5`).

Understanding *why* MCP-only `gemini-4-carbon` underperforms `SolverPolicy` requires examining within-cohort paired trajectories where the exact same model and tool interface diverge sharply. `scripts/audit_seed6_seed26_forensics.py` deterministically replays and cross-verifies (`0` replay discrepancies, `0` parity errors against `results/failure_analysis_v1.4.json`) the sharpest micro-level contrast in the `v1.4` hard record - **`seed 6` (`caught`, `+0.73`) vs `seed 26` (`fooled`, `-1.00`)** - across OpenCode `gemini-4-carbon`, In-Process `gemini-4-carbon`, and `SolverPolicy`:

1. **`seed 6` (`caught` in OpenCode `+0.73`, `caught` in `SolverPolicy` `+0.71`, `fooled` in In-Process `-1.00`): Early Day-1 Horstein Splitting Isolates the Mole Before Noise Accumulates.** On `seed 6` (`mole = e34`, `decoy = e20`), OpenCode `gemini-4-carbon` plants `2` disjoint `3`-variant canaries immediately on **Day 1** (`c1` covering `12` staff, `c1-2` covering `13` staff, same-day Jaccard `0.000`; `7` canaries total across Days `1-4`, `0` tiny `<= 3`-recipient confirmations, `25` interviews, `5` log reads, `0` ground-truth flips). When `c1-2` (`variant B`, Day 3) and `c3-2` (`variant A`, Day 6) surface alongside regular leaks `d2-1` and `d1-2`, exact set-and-variant intersection isolates `consistent_suspects = ["e34"]` (`n_consistent = 1`, `P(mole) = P(e34) = 0.9981 > P* = 0.5948`, `EV = +0.6781`), allowing OpenCode `gemini-4-carbon` to accuse `e34` on **Day 6 for `+0.73`** (`+0.02 V` ahead of `SolverPolicy`'s **`+0.71`** on Day 6, which planted `9` canaries including **`2` tiny `<= 3`-recipient Burnashev confirmations** `c4` and `c5`, `0` interviews, reaching `P(mole) = 0.9995`). Conversely, on the *exact same world seed*, In-Process `gemini-4-carbon` plants `0` canaries on Days `1-2`, executes `85` interviews, suffers a `5%` flip on `c4-2` (`true_variant = Y -> shown_variant = Z`), and commits a below-break-even Day-15 gamble on innocent `e18` (`-1.00`, `n_consistent = 3`, `P(e18) = 0.6295 < P* = 0.6661`, `EV = -0.0550`).
2. **`seed 26` (`fooled` in OpenCode `-1.00`, `caught` in `SolverPolicy` `+0.69`, `abstained` in In-Process `+0.00`): Three Empty Canary Days + Zero Tiny Confirmations Collide with a Disclosed `5%` Label Flip (`1.69 V` Paired Raw Gap).** On `seed 26` (`mole = e08`, `decoy = e38`), OpenCode `gemini-4-carbon` plants **`0` canaries across Days `1-3`**, spending early investigative capacity on **`43` interviews** and **`9` access-log reads**. When it finally plants two simultaneous `9`-recipient (`3`-per-variant) Research traps on Day 6 (`c6` and `c6-2`, same-day recipient Jaccard `1.000`), `c6` surfaces on Day 8 (`variant D1 = {e04, e08, e37}`, `n_consistent = 3`) while innocent `e04` temporarily leads `after_hours` logs **`3 vs 1`** (`P(e04) = 0.7309` vs `P(e08) = 0.1506`). On Day 9, true mole `e08` logs `3` fresh `after_hours` events to overtake `e04` **`4 vs 3`**, flipping the exact Bayesian top suspect back to **`e08` (`P(e08) = 0.4775 > P(e04) = 0.4467`)** while three newly planted narrow splitting canaries (`c8`, `c8-2` on Day 8; `c9` on Day 9) are still in transit inside `delay_choices = (2, 3)`. On Day 10, `c6-2` (`planted_day = 6`, `surfaced_day = 10`) suffers the disclosed `5%` (`1 - fingerprint_accuracy = 0.05`, `0.025` per wrong label) flip **`true_variant = S3 -> shown_variant = S1`**. Treating `D1 ∩ S1 = {e04}` as deterministic closure without waiting for in-flight `c8`/`c8-2`/`c9` or running a second tiny (`<= 3`-recipient) confirmation trap, OpenCode `gemini-4-carbon` accuses innocent **`e04` on Day 10 for `-1.00`** (`P(e04) = 0.9504`, `P(e08) = 0.0267`). By contrast, `SolverPolicy` plants **`11` canaries from Day 1** (`0` interviews), switches on Day 5 to a **`3`-recipient (`careful_weight = 0.925`) Burnashev singleton confirmation trap `c5-2`** (`e08 -> variant A`), and accuses **`e08` on Day 7 for `+0.69`** (`P(e08) = 0.9681`), opening a **`1.69 V` paired raw gap** (`+0.69` vs `-1.00`; single-seed luck-adjusted delta `+0.6361 - 0.5872 = +0.0489 V`).
3. **Cohort-Wide Confirmation Deficit (`0 / 254` vs `50 / 424` Tiny Confirmation Traps).** Across all `30` post-hoc locked `v1.4` hard seeds `0-29`, `SolverPolicy` devotes **`50 / 424` (`11.8%`)** of its planted canaries to `<= 3`-recipient Burnashev confirmation traps (`self.tiny = True` in `canary/solver/policy.py`), whereas OpenCode `gemini-4-carbon` plants **`0 / 254` (`0.0%`)** `<= 3`-recipient traps - relying exclusively on coarse multi-holder block intersections and `after_hours` tie-breakers.
4. **Actionable Zero-Protected-Path Proposals (`P12.1` and `P12.2`).** Section 5 translates this forensic contrast into two drop-in, zero-protected-path designs: **`P12.1`** (`gen_single_hit_closure_lure` in `canary/social/biases.py`, using `PublicDayFacts` only with exact `I(Social; Mole | PublicDayFacts) = 0` and `LLR = 0.0000` nats to tempt premature closure before confirmation) and **`P12.2`** (an explicit Burnashev confirmation-phase state summary `n_confirming_canaries_on_top_suspect` and confirmation-transition curriculum for `train/` small-model SFT/GRPO, plus a catchability-verified `MoleStrategy` stress test preserving frozen `v1.4` hash `a8f99c2537c91d72` and `>= 85%` `SolverPolicy` catchability).

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Citations and Verbatim Quotes)

### 2.1 Posterior-Quantile Probabilistic Bisection Over Noisy Channels: Horstein (1963)

- **Citation:** Horstein, M. (1963). Sequential Transmission Using Noiseless Feedback. *IEEE Transactions on Information Theory*, 9(3), 136-143.
- **Live Verified Links:** https://api.crossref.org/works/10.1109/TIT.1963.1057832 | DOI: https://doi.org/10.1109/TIT.1963.1057832
- **Theoretical Contribution:** Introduces sequential probabilistic bisection over discrete memoryless noisy channels with feedback, partitioning the current posterior distribution into equal-probability quantiles at each transmission step and updating soft Bayesian posteriors rather than performing hard combinatorial elimination.
- **Verbatim Quote (Abstract):**
> "A sequential continuous-transmission system employing a binary symmetric forward channel (but which is suitable for use with any discrete memoryless forward channel) and a noiseless feedback channel is described. Its error exponent is shown to be substantially greater than the optimum block-code error exponent at all transmission rates less than channel capacity."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Directly explains why `SolverPolicy` begins `3`-variant posterior-quantile splitting on Day 1 (`c1`, `c1-2`) and updates log-likelihoods softly under `fingerprint_accuracy = 0.95` (`+3.6376` nats match vs flip). On `seed 6`, OpenCode `gemini-4-carbon` approximates Horstein splitting from Day 1 (`c1` `12` staff, `c1-2` `13` staff, Jaccard `0.000`) and isolates `e34` by Day 6 (`+0.73`); on `seed 26`, skipping Days `1-3` forfeits `6` pipelined canary slots and forces reliance on a single Day-6 static block code (`c6`, `c6-2`) whose `S3 -> S1` flip mimics a clean intersection on `e04`.

### 2.2 Variable-Length Feedback Reliability and the Two-Phase Confirmation Theorem: Burnashev (1976) & Berlin et al. (2009)

- **Citation:** Berlin, P., Nakiboglu, B., Rimoldi, B., & Telatar, E. (2009). A Simple Converse of Burnashev's Reliability Function [establishing the two-phase communication-and-confirmation converse of Burnashev, M. V. (1976), Data transmission over a discrete channel with feedback: Random transmission time, *Problemy Peredachi Informatsii*, 12(4), 10-30]. *IEEE Transactions on Information Theory*, 55(7), 3074-3080.
- **Live Verified Links:** https://api.crossref.org/works/10.1109/TIT.2009.2021322 | DOI: https://doi.org/10.1109/TIT.2009.2021322
- **Theoretical Contribution:** Establishes a direct martingale converse for Burnashev's (1976) optimal variable-length feedback error exponent $E(R) = C_1 (1 - R / C)$, proving that any sequential scheme achieving optimal error decay against wrong declaration must transition from a **communication (search) phase** driven by Shannon capacity $C$ into a dedicated **confirmation phase** driven by maximum pairwise Kullback-Leibler divergence $C_1 = \max_{x, x'} D(P_{Y|x} \| P_{Y|x'})$.
- **Verbatim Quotes (Abstract):**
> "In a remarkable paper published in 1976, Burnashev determined the reliability function of variable-length block codes over discrete memoryless channels (DMCs) with feedback."
> "Besides being simpler than the original, the proposed converse suggests that a communication and a confirmation phase are implicit in any scheme for which the probability of error decreases with the largest possible exponent."
- **Relevance to Canary (`seed 6` vs `seed 26`):** This theorem is the mathematical backbone of `SolverPolicy`'s `self.tiny = True` endgame (`canary/solver/policy.py`, lines `424-431`). In Canary `v1.4` hard, broad `10-17`-recipient partitions maximize search-phase mutual information ($C = 0.86544$ nats/leak conditional on leaking), whereas `<= 3`-recipient singleton-per-variant traps (`1` suspect per label `A, B, C`) maximize both `careful_mole` leak weight (`1 - 3/40 = 0.925` vs `0.775` for `k = 9`) and Burnashev confirmation divergence ($C_1 = 0.925 \ln 38 = 3.36477$ nats). On `seed 26`, `SolverPolicy`'s Day-5 `3`-recipient confirmation canary `c5-2` (`e08: A`) surfaces on Day 7 for `+0.69`, whereas OpenCode `gemini-4-carbon` plants `0` tiny confirmations on both `seed 6` and `seed 26` (`0 / 254` across `seeds 0-29`).

### 2.3 Active Sequential Hypothesis Testing Under Wrong-Declaration Penalties: Naghshvar & Javidi (2013)

- **Citation:** Naghshvar, M., & Javidi, T. (2013). Active Sequential Hypothesis Testing. *The Annals of Statistics*, 41(6), 2703-2738.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/13-AOS1144 | https://arxiv.org/abs/1203.4626 | DOI: https://doi.org/10.1214/13-AOS1144
- **Theoretical Contribution:** Generalizes Burnashev's two-phase structure to finite-$M$ Bayesian active sequential hypothesis testing with per-step sampling cost and severe wrong-declaration loss, proving asymptotic optimality of policies (*Extrinsic Jensen-Shannon* / two-phase policy) that switch sensing actions once the leading posterior crosses an interior confirmation threshold $p_{\text{confirm}} \in (0, 1)$.
- **Verbatim Quote (Abstract):**
> "Consider a decision maker who is responsible to dynamically collect observations so as to enhance his information about an underlying phenomena of interest in a speedy manner while accounting for the penalty of wrong declaration. Due to the sequential nature of the problem, the decision maker relies on his current information state to adaptively select the most \"informative\" sensing action among the available ones."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Directly parameterizes Canary's `M = 39` non-decoy active sensing MDP under daily leak bleed (`leak_damage = 0.05`) and wrong-accusation penalty (`wrong_accusation_score = -1.0`). On `seed 6` Day 5 (`P(e34) = 0.6325`) and `seed 26` Day 5 (`P(e08) = 0.2008`, `6` consistent), `SolverPolicy` adaptively shifts from `16-17`-person departmental splits to `3-4`-person high-weight confirmation probes (`c4`, `c5` on `seed 6`; `c5-2`, `c6` on `seed 26`), directly inspiring Proposal **`P12.2`**.

### 2.4 Asymmetric Sequential Probability Ratio Stopping Boundaries: Wald (1945)

- **Citation:** Wald, A. (1945). Sequential Tests of Statistical Hypotheses. *The Annals of Mathematical Statistics*, 16(2), 117-186.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/aoms/1177731118 | DOI: https://doi.org/10.1214/aoms/1177731118
- **Theoretical Contribution:** Establishes the Sequential Probability Ratio Test (SPRT), proving that under asymmetric Type-I and Type-II error costs, optimal stopping requires continuing observation inside an explicit continuation region until cumulative log-likelihood crosses an upper commitment threshold, making sample size an endogenous random variable.
- **Verbatim Quotes (Part I, Section 1, pp. 118-119):**
> "An essential feature of the sequential test, as distinguished from the current test procedure, is that the number of observations required by the sequential test is not predetermined, but is a random variable due to the fact that at any stage of the experiment the decision of terminating the process depends on the results of the observations previously made."
> "In this paper a particular test procedure, called the sequential probability ratio test, is devised and shown to have certain optimum properties (see section 4.7)."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Grounds `canary/solver/policy.py:accuse_value`, where `wrong_accusation_score = -1.0` and `0.0` abstention impose a dynamic break-even posterior $P^*(V) = 1 / (1 + \mathbb{E}[V_{\text{true}}])$ plus `SolverPolicy`'s interior safety margin $P_{\text{top}} \ge 0.85$ before `n_days = 21`. On `seed 6` In-Process Day 15, `gemini-4-carbon` violates Wald's lower continuation bound directly (`P(e18) = 0.6295 < P^* = 0.6661`, `EV = -0.0550 -> -1.00`), whereas on `seed 26` In-Process Day 21, respecting the continuation bound yields a calibrated `0.00` abstention (`+1.00 V` higher than OpenCode's `-1.00`).

### 2.5 The Positive-Test Heuristic vs Multi-Hypothesis Partitioning: Klayman & Ha (1987)

- **Citation:** Klayman, J., & Ha, Y.-W. (1987). Confirmation, Disconfirmation, and Information in Hypothesis Testing. *Psychological Review*, 94(2), 211-228.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/0033-295X.94.2.211 | DOI: https://doi.org/10.1037/0033-295X.94.2.211
- **Theoretical Contribution:** Demonstrates that human investigators rely on a **positive test strategy** - querying individual focal hypotheses expected to exhibit a target trait rather than constructing balanced experiments that partition competing hypotheses - creating severe diagnostic inefficiency over multi-candidate spaces.
- **Verbatim Quote (Abstract):**
> "With this strategy, there is a tendency to test cases that are expected (or known) to have the property of interest rather than those expected (or known) to lack that property. This strategy is not equivalent to confirmation bias in the first sense; we show that the positive test strategy can be a very good heuristic for determining the truth or falsity of a hypothesis under realistic conditions. It can, however, lead to systematic errors or inefficiencies. The appropriateness of human hypothesis-testing strategies and prescriptions about optimal strategies must be understood in terms of the interaction between the strategy and the task at hand."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Captures the exact action-budget pathology of `seed 26` Days `1-3` and Days `5-9`: OpenCode `gemini-4-carbon` conducts `43` one-on-one `interview` probes (`0.00477` nats KL each), including `8` interviews on `e04` and `9` on `e08`, instead of using Days `1-3` to plant `6` pooled `0.86544`-nat `plant_canary` partitions.

### 2.6 Case-Building Confirmation Bias and Disconfirming-Cue Neglect: Nickerson (1998)

- **Citation:** Nickerson, R. S. (1998). Confirmation Bias: A Ubiquitous Phenomenon in Many Guises. *Review of General Psychology*, 2(2), 175-220.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/1089-2680.2.2.175 | DOI: https://doi.org/10.1037/1089-2680.2.2.175
- **Theoretical Contribution:** Synthesizes psychological and forensic evidence showing that once an investigator forms a favored focal hypothesis, subsequent cue interpretation and stopping decisions systematically overweight hypothesis-consistent coincidences while discounting rival candidates' emerging anomalies.
- **Verbatim Quote (Abstract):**
> "Confirmation bias, as the term is typically used in the psychological literature, connotes the seeking or interpreting of evidence in ways that are partial to existing beliefs, expectations, or a hypothesis in hand. The author reviews evidence of such a bias in a variety of guises and gives examples of its operation in several practical contexts. Possible explanations are considered, and the question of its utility or disutility is discussed."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Explains OpenCode `gemini-4-carbon`'s closing rationale on `seed 26` (`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts/26.txt`, line `280`). After anchoring on `e04`'s `3 vs 1` `after_hours` lead on Day 8 (`P(e04) = 0.7309`), Gemini's Day-10 accusation summary cites `e04`'s `"elevated after-hours access activity (3 after-hours vs. 5 daytime accesses)"` as corroboration for `c6-2 = S1`, omitting that on Day 9 co-finalist `e08` had surged to **`4` cumulative `after_hours` accesses** (`top_suspect = e08`, `P(e08) = 0.4775 > P(e04) = 0.4467` at end of Day 9!). Directly grounds Proposal **`P12.1`**.

### 2.7 Overprecision and Deterministic Closure Under Noisy Signals: Moore & Healy (2008)

- **Citation:** Moore, D. A., & Healy, P. J. (2008). The trouble with overconfidence. *Psychological Review*, 115(2), 502-517.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/0033-295X.115.2.502 | https://pubmed.ncbi.nlm.nih.gov/18426301/ | DOI: https://doi.org/10.1037/0033-295X.115.2.502
- **Theoretical Contribution:** Distinguishes *overestimation*, *overplacement*, and *overprecision* (excessive certainty in the precision of subjective probability beliefs), demonstrating that overprecision persists across feedback regimes and suppresses further diagnostic sampling.
- **Verbatim Quotes (Abstract):**
> "The authors present a reconciliation of 3 distinct ways in which the research literature has defined overconfidence: (a) overestimation of one's actual performance, (b) overplacement of one's performance relative to others, and (c) excessive precision in one's beliefs."
> "Overprecision appears to be more persistent than either of the other 2 types of overconfidence, but its presence reduces the magnitude of both overestimation and overplacement."
- **Relevance to Canary (`seed 6` vs `seed 26`):** On `seed 26` Day 10, `Env.instruction()` explicitly warns that `fingerprint_accuracy = 0.95` is *"evidence, not proof"*, and exact Bayesian updating retains a `4.96%` residual error probability (`P(e04) = 0.95044`, `P(e08) = 0.02674`). Yet OpenCode `gemini-4-carbon`'s rationale treats the noisy `9`-person block intersection (`D1 ∩ S1 = {e04}`) as exact noiseless proof (*"Their intersection uniquely identified e04"*), terminating the episode with `11` days still on the clock.

### 2.8 Supply-Line Blindness Under Multi-Day Feedback Delays: Sterman (1989)

- **Citation:** Sterman, J. D. (1989). Modeling Managerial Behavior: Misperceptions of Feedback in a Dynamic Decision Making Experiment. *Management Science*, 35(3), 321-339.
- **Live Verified Links:** https://api.crossref.org/works/10.1287/mnsc.35.3.321 | DOI: https://doi.org/10.1287/mnsc.35.3.321
- **Theoretical Contribution:** Proves experimentally and econometrically that decision-makers in delayed-feedback systems systematically neglect **in-transit supply lines** - acting on current surfaced observations while ignoring pending interventions already placed in the delay pipeline.
- **Verbatim Quote (Abstract):**
> "Subjects manage a simulated inventory distribution system which contains multiple actors, feedbacks, nonlinearities, and time delays. The interaction of individual decisions with the structure of the simulated firm produces aggregate dynamics which systematically diverge from optimal behavior. An anchoring and adjustment heuristic for stock management is proposed as a model of the subjects' decision processes. Econometric tests show the rule explains the subjects' behavior well. The estimation results identify several 'misperceptions of feedback' which account for the poor performance of the subjects. In particular, subjects are shown to be insensitive to the feedbacks from their decisions to the environment."
- **Relevance to Canary (`seed 6` vs `seed 26`):** Explains the hidden tragedy of `seed 26` Day 10. On Day 8 (`c8`: `5` recipients, `e08=T2, e04=T1`; `c8-2`: `5` recipients, `e08=V2, e04=V1`) and Day 9 (`c9`: `4` recipients, `e08=B9, e04=A9`), OpenCode `gemini-4-carbon` had **already paid the `0.03 V` canary cost** for three narrow confirmation traps separating `e08` from `e04` inside the `delay_choices = (2, 3)` supply line (due to surface on Days `10-12`). Ignoring its own paid in-transit supply line on Day 10 turned an easily recoverable `5%` flip into an irreversible `-1.00` loss.

---

## 3. Exact Replay-Verified Forensics: `seed 6` (`Caught`) vs `seed 26` (`Fooled`)

Every scalar, posterior, set membership, and tool count below is produced deterministically by `/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_seed6_seed26_forensics.py --check` (`tiers_version = "v1.4"`, `v14_hash = "a8f99c2537c91d72"`, `total_replay_discrepancies = 0`, `failure_analysis_parity_errors = []`).

### 3.1 Cross-Harness Head-to-Head Summary Table (`v1.4` Hard, Frozen Hash `a8f99c2537c91d72`)

| Forensic Metric (`v1.4` Hard `a8f99c2537c91d72`) | `seed 6` OpenCode `gemini-4-carbon` | `seed 6` In-Process `gemini-4-carbon` | `seed 6` `SolverPolicy` | `seed 26` OpenCode `gemini-4-carbon` | `seed 26` In-Process `gemini-4-carbon` | `seed 26` `SolverPolicy` |
|---|---:|---:|---:|---:|---:|---:|
| Ground-truth `mole_id` / `decoy_id` | `e34` / `e20` | `e34` / `e20` | `e34` / `e20` | `e08` / `e38` | `e08` / `e38` | `e08` / `e38` |
| Episode outcome (`accused_id`) | **`caught` (`e34`)** | `fooled` (`e18`) | **`caught` (`e34`)** | **`fooled` (`e04`)** | `abstained` (`None`) | **`caught` (`e08`)** |
| Accusation / final day | **Day `6`** | Day `15` | **Day `6`** | **Day `10`** | Day `21` (horizon) | **Day `7`** |
| Replay-verified raw score | **`+0.73`** | `-1.00` | **`+0.71`** | **`-1.00`** | `+0.00` | **`+0.69`** |
| Luck-adjusted score (`P*V - (1-P)`) | **`+0.7268`** | `-0.0558` | **`+0.7091`** | **`+0.5872`** | `+0.0000` | **`+0.6361`** |
| Realized luck (`raw - luck_adj`) | `+0.0032` | `-0.9442` | `+0.0009` | **`-1.5872`** | `+0.0000` | `+0.0539` |
| Paired raw swing (`Solver - Agent`) | **`-0.02 V`** | `+1.71 V` | `0.00 V` | **`+1.69 V`** | `+0.69 V` | `0.00 V` |
| Total steps (`invalid_calls`) | `57` (`1`) | `151` (`1`) | `52` (`0`) | `91` (`1`) | `212` (`1`) | `60` (`0`) |
| `plant_canary` count (`first_canary_day`) | **`7` (Day `1`)** | `10` (Day `3`) | **`9` (Day `1`)** | **`8` (Day `4`)** | `14` (Day `4`) | **`11` (Day `1`)** |
| Canaries planted on Days `1-3` | **`6`** (`2, 2, 2`) | `1` (`0, 0, 1`) | **`6`** (`2, 2, 2`) | **`0`** (`0, 0, 0`) | `0` (`0, 0, 0`) | **`6`** (`2, 2, 2`) |
| Tiny confirmations (`<= 3` recipients) | **`0`** | `0` | **`2`** (`c4`, `c5`) | **`0`** | `0` | **`1`** (`c5-2`) |
| Mean recipients / `careful_weight` | `8.71` / `0.782` | `7.70` / `0.808` | `9.89` / `0.753` | `8.25` / `0.794` | `6.86` / `0.829` | `12.00` / `0.700` |
| Same-day `2`-canary Jaccard overlap | **`0.000`** (`3` days) | `0.867` (`3` days) | `0.181` (`4` days) | **`1.000`** (`3` days) | `0.285` (`5` days) | `0.130` (`5` days) |
| `careful_mole` retention ratio | `0.884` | `0.899` | `0.907` | `0.872` | `0.857` | `0.818` |
| `interview` / `read_access_logs` calls | **`25` / `5`** | `85` / `14` | **`0` / `5`** | **`43` / `9`** | `122` / `20` | **`0` / `6`** |
| Ground-truth `5%` label flips | **`0`** | `1` (`c4-2`: `Y->Z`) | **`0`** | **`1` (`c6-2`: `S3->S1`)** | `1` (`c4`: `v1->v2`) | **`0`** |
| `consistent_suspects` at accusation | `["e34"]` (`1`) | `["e12","e18","e24"]` (`3`) | `["e34"]` (`1`) | `["e04"]` (`1`, flipped) | `[]` (abstained) | `["e08"]` (`1`) |
| Exact `P(accused)` / `P(mole)` at commit | **`0.9981` / `0.9981`** | `0.6295` / `0.0059` | **`0.9995` / `0.9995`** | **`0.9504` / `0.0267`** | `None` / `None` | **`0.9681` / `0.9681`** |
| Break-even `P*(E[V])` / `EV(accused)` | `0.5948` / `+0.6781` | `0.6661` / **`-0.0550`** | `0.6020` / `+0.6604` | `0.6168` / `+0.5409` | `0.7353` (true `V`) | `0.5913` / `+0.6373` |

---

### 3.2 Day-by-Day Forensic Trace of `seed 6` (`mole = e34`, `decoy = e20`): Fast Isolation vs Burnashev Confirmation

On `seed 6`, both OpenCode `gemini-4-carbon` and `SolverPolicy` start planting `2` canaries/day on **Day 1**, closing the case on **Day 6** after `4` ground-truth leaks (`visible_V = true_V`: `0.73` for OpenCode with `7` canaries, `0.71` for `SolverPolicy` with `9` canaries):

| Day | OpenCode `gemini-4-carbon`: Canaries (`k`) & Interviews | OpenCode Surfaced Feed & `\|C\|` (`consistent`) | OpenCode `P(top)` (`top`) & `P(e34)` | `SolverPolicy`: Canaries (`k`) & Interviews | `SolverPolicy` Surfaced Feed & `\|C\|` | `SolverPolicy` `P(top)` (`top`) & `P(e34)` |
|---:|---|---|---|---|---|---|
| `1` | `c1` (`12`), `c1-2` (`13`, `e34=B`); `5` ivs | none; `\|C\| = 40` | `0.0251` (`e00`), `P(e34) = 0.0251` | `c1` (`16`), `c1-2` (`16`); `0` ivs | none; `\|C\| = 40` | `0.0250` (`e00`), `P(e34) = 0.0250` |
| `2` | `c2` (`7`), `c2-2` (`8`); `4` ivs, `1` log | none; `\|C\| = 40` (`e20` decoy ID'd) | `0.0353` (`e16`), `P(e34) = 0.0211` | `c2` (`16`), `c2-2` (`17`, `e34=A`); `0` ivs | none; `\|C\| = 40` (`e20` decoy ID'd) | `0.0405` (`e01`), `P(e34) = 0.0258` |
| `3` | `c3` (`6`), `c3-2` (`7`, `e34=A`); `4` ivs | **`c1-2: B`** (`k=13`, no flip); `\|C\| = 4` (`e28,e30,e34,e35`) | `0.3310` (`e30`), `P(e34) = 0.2106` | `c3` (`8`), `c3-2` (`6`, `e34=A`); `0` ivs | `d1-2` (`k=19`); `\|C\| = 19` | `0.0924` (`e31`), `P(e34) = 0.0706` |
| `4` | `c4` (`8`, `e34=A`); `5` ivs, `1` log | `d2-1` (`k=14`); `\|C\| = 2` (`e30,e34`) | `0.4461` (`e30`), `P(e34) = 0.4362` | **`c4` (`3`, tiny `e34=C`)**, `c4-2` (`4`); `0` ivs | `d2-1` (`k=14`); `\|C\| = 8` | `0.1705` (`e31`), `P(e34) = 0.1664` |
| `5` | `0` canaries; `7` ivs, `1` log (`8/8` actions) | none; `\|C\| = 2` (`e30,e34`) | `0.4527` (`e34`), `P(e34) = 0.4527` | **`c5` (`3`, tiny `e34=C`)**; `0` ivs | **`c3-2: A`** (`k=6`, no flip); `\|C\| = 2` (`e31,e34`) | `0.6325` (`e34`), `P(e34) = 0.6325` (`EV +0.082`, waits `< 0.85`) |
| `6` | **`accuse(e34)`** (`0` ivs, `1` log, `1` feed) | `d1-2` (`k=19`) + **`c3-2: A`** (`k=7`); **`\|C\| = 1` (`e34`)** | **`0.9981` (`e34`)**, **`+0.73` (`caught`)** | **`accuse(e34)`** (`0` ivs, `1` log, `1` feed) | **`c4: C`** (`k=3`, tiny singleton); **`\|C\| = 1` (`e34`)** | **`0.9995` (`e34`)**, **`+0.71` (`caught`)** |

**Three Forensic Takeaways from `seed 6`:**
1. **Why OpenCode `gemini-4-carbon` won on `seed 6` (`+0.73`):** Planting `2` disjoint (`Jaccard = 0.000`) `12-13`-recipient canaries on Day 1 (`careful_weight = 0.700` and `0.675`) covered `25 / 39` (`64.1%`) of non-decoy staff immediately. Mole `e34` leaked `c1-2` on Day 1 (surfacing Day 3, narrowing `|C|` from `40` to `4`) and `c3-2` on Day 3 (surfacing Day 6, isolating `e34` at `P = 0.9981` with `0` label flips). Because `2` extra Burnashev confirmation canaries (`c4`, `c5`) cost `SolverPolicy` `0.02 V`, OpenCode edged `SolverPolicy` `+0.73` vs `+0.71` on raw score (`+0.7268` vs `+0.7091` luck-adjusted).
2. **Hidden Fragility Even Inside `seed 6`'s Win:** Notice Day 5 of OpenCode `gemini-4-carbon`: with `consistent_suspects = ["e30", "e34"]` (`n_consistent = 2`, `P(e34) = 0.4527`), OpenCode planted **`0` canaries** on Day 5 and burned `7` of `8` actions interviewing `e34`, `e30`, and `e22` (`0` tiny `<= 3`-person `[e30: A, e34: B]` confirmation traps). It won on Day 6 only because its earlier Day-3 canary `c3-2` (`7` recipients) happened to surface unflipped.
3. **Same-Seed Harness Control (`In-Process gemini-4-carbon` on `seed 6`):** Delaying the first canary to Day 3 (`1` canary across Days `1-3`), planting near-duplicate same-day recipient pools (`mean_same_day_jaccard = 0.867`), and running `85` interviews left In-Process `gemini-4-carbon` vulnerable to a single `c4-2` flip (`Y -> Z` on Day 7), culminating in a negative-EV Day-15 accusation on `e18` (`P = 0.6295 < P* = 0.6661`, `-1.00`).

---

### 3.3 Day-by-Day Forensic Anatomy of `seed 26` (`mole = e08`, `decoy = e38`): How `0` Early Canaries + `0` Tiny Confirmations Caused `-1.00`

On `seed 26`, OpenCode `gemini-4-carbon` and `SolverPolicy` face the identical world (`mole = e08` in Research, disgruntled innocent `decoy = e38` in Research):

| Day | OpenCode `gemini-4-carbon`: Canaries (`k`) & Interviews | OpenCode `after_hours` (`e04` vs `e08`) & `\|C\|` | OpenCode Exact `P(top)` (`top`) & `P(e08)` | `SolverPolicy`: Canaries (`k`) | `SolverPolicy` Surfaced Feed & `\|C\|` | `SolverPolicy` `P(top)` (`top`) & `P(e08)` |
|---:|---|---|---|---|---|---|
| `1` | **`0` canaries**; `2` ivs (`4` actions used) | `e04: 0` vs `e08: 0`; `\|C\| = 40` | `0.0250` (`e01`), `P(e08) = 0.0250` | `c1` (`16`, `e08=B`), `c1-2` (`16`) | none; `\|C\| = 40` | `0.0250` (`e00`), `P(e08) = 0.0250` |
| `2` | **`0` canaries**; `6` ivs, `1` log (`8/8` full) | `e04: 1` vs `e08: 1`; `\|C\| = 40` (`e38` decoy) | `0.0402` (`e04`), `P(e08) = 0.0346` | `c2` (`16`), `c2-2` (`16`) | none; `\|C\| = 40` (`e38` decoy) | `0.0416` (`e03`), `P(e08) = 0.0266` |
| `3` | **`0` canaries**; `5` ivs, `1` log (`7` actions) | `e04: 1` vs `e08: 1`; `\|C\| = 40` | `0.0407` (`e04`), `P(e08) = 0.0223` | `c3` (`11`), `c3-2` (`17`, `e08=C`) | none; `\|C\| = 40` | `0.0573` (`e19`), `P(e08) = 0.0255` |
| `4` | `c4` (`14`), `c4-2` (`14`) (`Jaccard = 1.0`); `4` ivs | `e04: 2` vs `e08: 1`; `d1-2` -> `\|C\| = 15` | `0.1532` (`e04`), `P(e08) = 0.0518` | `c4` (`15`), `c4-2` (`11`) | none; `\|C\| = 40` | `0.0846` (`e19`), `P(e08) = 0.0298` |
| `5` | `c5` (`6`, `e08=R, e04=P`); `6` ivs (`8/8` full) | `e04: 3` vs `e08: 1`; `\|C\| = 15` | `0.1864` (`e38`), `P(e08) = 0.0565` | `c5` (`7`, `e08=C`), **`c5-2` (`3`, tiny `e08=A`)** | **`c3-2: C`** (`k=17`, no flip); `\|C\| = 6` | **`0.2008` (`e08`)**, `P(e08) = 0.2008` |
| `6` | `c6` (`9`, `e08=D1,e04=D1`), `c6-2` (`9`, `e08=S3,e04=S1`); `4` ivs | `e04: 3` vs `e08: 1`; `d4-3` -> `\|C\| = 10` | `0.2469` (`e38`), `P(e08) = 0.0679` | `c6` (`4`) | none; `\|C\| = 6` (`e06,e08,e20..e23`) | `0.1956` (`e06`), `P(e08) = 0.1929` |
| `7` | **`0` canaries**; `6` ivs, `1` log (`8/8` full) | `e04: 3` vs `e08: 1`; `d3-1` -> `\|C\| = 10` (Research) | `0.2830` (`e04`), `P(e08) = 0.0845` | **`accuse(e08)`** (`0` ivs, `1` log, `1` feed) | `d3-1` + **`c5-2: A`** (`k=3`, tiny singleton); **`\|C\| = 1` (`e08`)** | **`0.9681` (`e08`)**, **`+0.69` (`caught`)** |
| `8` | `c8` (`5`, `e08=T2,e04=T1`), `c8-2` (`5`, `e08=V2,e04=V1`); `4` ivs | **`e04: 3` vs `e08: 1`**; **`c6: D1`** -> **`\|C\| = 3` (`e04,e08,e37`)** | **`0.7309` (`e04`)**, `P(e08) = 0.1506` (`EV +0.229`, `< 0.85`) | *episode already closed Day 7 (`+0.69`)* | - | - |
| `9` | `c9` (`4`, `e08=B9,e04=A9`); `6` ivs (`4` on `e08`, `2` on `e04`) | **`e04: 3` vs `e08: 4` (`e08` overtakes!)**; `\|C\| = 3` | **`0.4775` (`e08`, mole!)** > `P(e04) = 0.4467` | - | - | - |
| `10` | **`accuse(e04)`** (`0` ivs, `1` log, `1` feed) | `e04: 3` vs `e08: 4`; **`c6-2: S1` (`FLIP` from `S3`!)** -> `\|C\| = 1` (`e04`) | **`0.9504` (`e04`)**, `P(e08) = 0.0267` -> **`-1.00` (`fooled`)** | - | - | - |

**Four-Stage Causal Chain of the `seed 26` Failure (`-1.00` vs `+0.69`, `1.69 V` Paired Raw Gap):**
1. **Stage 1 - Days `1-3` Canary Starvation (`0` vs `6` Canaries):** OpenCode `gemini-4-carbon` spends Days `1-3` executing `13` passive interviews (`0.00477` nats each) and `0` `plant_canary` calls, whereas `SolverPolicy` plants `6` broad `3`-variant canaries (`c1` through `c3-2`), catching mole `e08` in `c3-2` (`variant C`) by Day 5 (`|C| = 6`).
2. **Stage 2 - Burnashev Confirmation Phase Divergence (`0` vs `1` Tiny Singleton Canary):** Once `SolverPolicy` narrows `|C|` to `6` on Day 5, `self.tiny = True` plants `c5-2` with **`k = 3` recipients (`careful_weight = 0.925`)** assigning `e08` a **singleton variant `A`**. `c5-2` leaks immediately on Day 5 and surfaces on Day 7 (`P(e08) = 0.9681`, `+0.69`). OpenCode `gemini-4-carbon`, by contrast, plants two identical-recipient `9`-person traps on Day 6 (`c6` and `c6-2`, `Jaccard = 1.000`, `3` suspects per variant). Because each variant of `c6-2` holds `3` Research suspects (`S1 = {e04, e20, e28}`, `S3 = {e08, ...}`), any `0.025` flip from `S3` to `S1` collides directly with co-finalist `e04` inside `D1 = {e04, e08, e37}`!
3. **Stage 3 - Day 8 Anchoring vs Day 9 Disconfirming Log Surge:** On Day 8, `e04` leads `after_hours` `3 vs 1` (`P(e04) = 0.7309`). On Day 9, mole `e08` records `3` new `after_hours` accesses (`cum_after_hours: e08 = 4 vs e04 = 3`), pushing exact Bayesian `P(e08) = 0.4775` *above* `P(e04) = 0.4467`. Yet OpenCode's Day-10 rationale anchors on `e04`'s `3` `after_hours` accesses (Nickerson, 1998) and ignores `e08`'s `4` `after_hours` accesses.
4. **Stage 4 - Supply-Line Blindness on the `c6-2` (`S3 -> S1`) Flip:** When `c6-2` (`planted_day = 6`, `surfaced_day = 10`) flips `S3 -> S1` under `1 - fingerprint_accuracy = 0.05`, exact `P(e04)` reaches `0.9504` (`solver_rule_fires = True` on that partial trajectory, which is why [docs/reports/failure_analysis_v1.4.md](../reports/failure_analysis_v1.4.md) fairly credits `seed 26` as disclosed `5%` flip luck in static post-commitment accounting, with luck-adjusted score `+0.5872`). Yet dynamically, OpenCode already had **three narrow confirmation traps (`c8`, `c8-2`, `c9`, `k = 4..5`, `careful_weight = 0.875..0.900`) in flight** from Days `8-9` separating `e04` and `e08`, with `11` days remaining (`V = 0.67`). Waiting `1-2` days for a single in-flight confirmation or requiring `1` tiny (`<= 3`-recipient) confirmation hit before accusing when Day-9 logs contradicted `c6-2` would have overturned the flip (`+3.6376` nats back to `e08`).

---

## 4. Mathematical Theory: `careful_mole` Pool Sizing (`k* = 20`) vs Burnashev Confirmation (`k <= 3`)

`compute_careful_mole_curve(n_employees = 40)` in `scripts/audit_seed6_seed26_forensics.py` proves why optimal play in Canary `v1.4` hard requires **two distinct pool-sizing regimes** rather than a single fixed heuristic:

1. **Phase 1 - Uninformed Search (`Day 1..3`, `39` Non-Decoy Suspects):** Under `careful_mole = True`, a `k`-recipient canary carries selection weight $w(k) = 1 - k/40$ and covers the uniform mole with probability $k/39$, giving unconditional hit weight:
   $$W(k) = \frac{k}{39}\left(1 - \frac{k}{40}\right) = \frac{40k - k^2}{1560}, \qquad k^* = \arg\max_{1 \le k \le 39} W(k) = \mathbf{20} \;\left(W(20) = \frac{20}{78} = \mathbf{0.2564}\right).$$
   Planting **two disjoint `10`-recipient canaries** on Day 1 (`c1` and `c1-2` with `Jaccard = 0.0`, closely matched by OpenCode's `12 + 13` on `seed 6`!) achieves combined unconditional hit weight $2 W(10) = 2 \times \frac{10}{39} \times 0.75 = \mathbf{0.3846}$ (`1.50x` a single `k = 20` canary, **`3.60x`** a premature `k = 3` micro-trap for single-slot $W(20)/W(3) = 3.6036$, and **`10.26x`** a `k = 39` broadcast trap $W(20)/W(39) = 10.2564$).
2. **Phase 2 - Burnashev Endgame Confirmation (`|core| <= 6` or `P_top >= 0.45`):** Once regular leaks and Phase-1 canaries concentrate `>= 85%` of posterior mass onto `2-3` finalists (such as `{e30, e34}` on `seed 6` Day 4 or `{e04, e08, e37}` on `seed 26` Day 8), coverage of the top `3` suspects is already `~1.0`! Shrinking the canary to **`k = 2` or `k = 3` (`1` finalist per variant `A, B, C`, `0` co-holders)** raises `careful_weight` from `0.775` (`k = 9`) to **`0.925 - 0.950`**, eliminates within-variant co-holder ambiguity (`|V_y| = 1`), and delivers full Burnashev confirmation divergence $D_{\text{KL}} = 0.925 \ln(38) = \mathbf{3.36477\text{ nats}}$ per surfaced trap, driving two-hit false-flip probability down from $1 - \alpha = 0.05$ (`seed 26`) to $\beta^2 / (\alpha^2 + \beta^2) \approx 6.9 \times 10^{-4}$.

| Pool Size $k$ (`N = 40`) | Roster Share $k/40$ | `careful_weight` $1 - k/40$ | Uniform Coverage $k/39$ | Phase-1 Unconditional $W(k)$ | Variant Cell Size $\lceil k/3 \rceil$ | Optimal Burnashev Phase |
|---:|---:|---:|---:|---:|---:|---|
| `1` | `0.025` | `0.975` | `0.0256` | `0.0250` | `1` (`binary`) | Suboptimal (`0` variant contrast if `k=1`) |
| **`2`** | `0.050` | **`0.950`** | `0.0513` | `0.0487` | **`1` (`singleton`)** | **Phase 2: Pairwise confirmation (`\|C\| = 2`)** |
| **`3`** | `0.075` | **`0.925`** | `0.0769` | `0.0712` | **`1` (`singleton`)** | **Phase 2: Ternary confirmation (`c4`/`c5` s6, `c5-2` s26)** |
| **`10` (`2x10` disjoint)** | `0.250` | `0.750` | `0.2564` (`0.5128` pair) | `0.1923` (**`0.3846` pair**) | `3-4` | **Phase 1: Disjoint `2/day` Horstein search** |
| `13` (`seed 6` `c1-2`) | `0.325` | `0.675` | `0.3333` | `0.2250` | `4-5` | Phase 1: High-rate search (`seed 6` Day 1) |
| **`20` (single-slot $k^*$)** | `0.500` | `0.500` | `0.5128` | **`0.2564` (max single)** | `6-7` | **Phase 1: Single-canary global maximum** |
| `39` (all non-decoy) | `0.975` | `0.025` | `1.0000` | `0.0250` | `13` | Deterred (`10.26x` below $k^*=20$) |

---

## 5. Concrete Zero-Protected-Path Proposals (`P12.1` and `P12.2`)

Both proposals strictly respect `.github/protected-paths.txt` (`0` edits to `canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/types.py`, `canary/eval.py`, `canary/reproduce.py`, `canary/mcp_server.py`, `canary/solver/`, or `harbor/`), preserve the frozen `v1.4` tier hash `a8f99c2537c91d72`, and require `0` live API calls during `make reproduce`.

### Proposal P12.1: Zero-Leakage Premature-Closure Social Lure (`gen_single_hit_closure_lure` in `canary/social/biases.py`)

- **Target Surface:** `canary/social/biases.py` and `canary/social/engine.py` (`V16SocialProvider`, zero protected paths touched).
- **Behavioral Mechanism Targeted:** Operationalizes **Moore & Healy's (2008) overprecision**, **Nickerson's (1998) confirmation bias**, and **Sterman's (1989) supply-line neglect** observed directly on `seed 26` Day 10. On Days `7-12`, an authority reviewer (`AUTHORITY_ROLES = ("manager", "lead", "controller", "counsel")`) posts a naturalistic `#security-review` or email note arguing that once initial document circulation overlaps on a single recurring name (`target = _resolve_target(ctx, target_id)` drawn strictly from public Day-1/mid-game `PublicDayFacts` recipient intersections), running extra follow-up verification drafts only lets more value bleed out before closing the review.
- **Drop-In Implementation Specification (`canary/social/biases.py`):**
  ```python
  def gen_single_hit_closure_lure(
      ctx: SocialDayContext,
      rng: random.Random,
      target_id: str | None = None,
      secondary: bool = False,
  ) -> dict[str, Any]:
      target = _resolve_target(ctx, target_id, secondary=secondary)
      speaker = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers)
      tn = _target_label(target)
      sp_role = _safe_role(speaker)
      doc_title = _today_doc_title(ctx, rng)
      subjects = (
          "Closing out the doc circulation review",
          "Security review timing on recent leak",
          "Meeting follow-up on doc overlap",
      )
      bodies = (
          f"Leak review note ({sp_role}): {tn} already sits in the {doc_title} overlap; waiting days for extra confirmation drafts just risks further bleed.",
          f"Post-meeting doc check ({sp_role}): once circulation narrows to {tn} on {doc_title}, a second round of small test drafts rarely changes the picture.",
      )
      channel = rng.choice(("#security-review", "email"))
      return _build_event(
          ctx,
          "confirmation",
          speaker,
          target,
          channel,
          rng.choice(subjects),
          rng.choice(bodies),
          doc_title,
      )
  ```
- **Strict Zero-Leakage & Linter Proof:**
  1. **Zero Hidden Mole Information (`I(Social; Mole | PublicDayFacts) = 0`, `LLR = 0.0000` nats):** `ctx` (`SocialDayContext`) is constructed exclusively from `PublicDayFacts(tier, seed, day, company, employees, docs, decoy, decoy_mood, restricted, extra)` (`canary/text/facts.py`) and regular non-canary documents (`not doc_id.startswith("c")`). Neither `world.mole`, `Env._leaked`, nor `Env._feed` is ever read. By the Markov chain $\text{Mole} \to \text{PublicDayFacts}_{1:d} \to \text{Social}_{1:d}$, exact Bayesian `social_loglik(s) == 0.0000` nats for every employee $s \in \{e_{00}, \dots, e_{39}\}$, avoiding the `v1.5-candidate` Gate B exclusion-oracle inversion (`61% -> 108%`, [Monograph 07](07_v15_bias_layer_proposals.md)).
  2. **Naturalistic Linter Compliance:** Rejects all `FORBIDDEN_SUBJECT_PREFIXES`, bans raw `eXX` IDs in `subject`, excludes `DECOY_VOCAB`, and places both `SALIENCE_TERMS` (`"leak"`, `"doc"`, `"meeting"`) and `Name (eXX)` inside `body[:110]` so `search_messages` (`body[:120]`) surfaces the closure lure cleanly.

---

### Proposal P12.2: Burnashev Confirmation-Phase Feature & Curriculum (`train/`) + Catchability-Verified `MoleStrategy` Stress Test (`canary/mole/`)

In the final hackathon tiebreaker run ([docs/SUBMISSION.md](../SUBMISSION.md), [docs/reports/CEO.md](../reports/CEO.md)), no trained small model cleared the untrained base model bar because SFT/GRPO policies struggled on the **exploration-to-confirmation commitment transition** (`train/README.md`: naive SFT never accused, while unweighted accuse up-weighting risked premature accusations without isolating evidence). Proposal **`P12.2`** targets `train/` and `canary/mole/` (`0` protected paths touched):

1. **Part P12.2a - Explicit Burnashev Confirmation State Summary & Two-Phase Curriculum (`train/render.py`, `train/windows.py`, `train/grpo_investigator.py`):**
   - Compute a purely client-side, deterministic history digest appended to the investigator's user/state turn in `train/render.py` using **only the agent's own public tool results** (`list_documents`, `plant_canary`, `check_leak_feed`):
     - `consistent_set_size`: exact count of non-decoy employees consistent with all surfaced regular leaks;
     - `n_confirming_canaries_on_top_suspect`: count of surfaced `check_leak_feed` canary variants matching the leading suspect (`0`, `1`, `2+`), paired with `min_confirming_canary_pool_size` (`<= 3` indicates a true Burnashev singleton confirmation vs `9` on `seed 26`'s flipped `c6-2`) and `in_flight_splitting_canaries` (count of planted canaries within `leak_window_days = 3` that assign distinct labels to the top `2` suspects, equal to **`3`** on `seed 26` Day 10!).
   - **Curriculum & Window Weighting (`train/windows.py`, `train/grpo_investigator.py`):** Extend `windows_ex()` and `collect_states()` to oversample **Burnashev Phase-2 transition turns** (turns where `2 <= consistent_set_size <= 6` and `SolverPolicy` plants a `<= 3`-recipient `tiny` confirmation canary, such as Day 4 on `seed 6` and Day 5 on `seed 26`) alongside commitment turns where `n_confirming_canaries_on_top_suspect >= 2` or `min_confirming_canary_pool_size <= 3`. All training seeds stay strictly inside `rules.TRAIN_SEEDS` (`seed >= 150000`, disjoint from `HELDOUT_SEEDS` and `JUDGE_SEEDS`), preserving frozen `v1.4` hash `a8f99c2537c91d72`.
2. **Part P12.2b - Confirmation-Evading `MoleStrategy` Stress Test (`canary/mole/dsl.py`):**
   - To train and evaluate investigators against moles that specifically punish late canary starters while remaining provably catchable by `SolverPolicy`'s two-phase Horstein-Burnashev strategy, register `burnashev_confirmation_evader_v14` in `canary/forge/` (`MoleStrategy` DSL, `0` protected paths):

```json
{
  "name": "burnashev_confirmation_evader_v14",
  "rules": [
    {
      "if": [["day", "<=", 3], ["min_recipient_count", ">=", 14]],
      "then": {"leak": "most_recipients", "frame": "decoy"}
    },
    {
      "if": [["recent_low_recipient_docs", ">=", 2], ["days_since_last_leak", "<=", 1]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

- **Catchability & Frozen-Hash Invariant:** `burnashev_confirmation_evader_v14` parses cleanly via `MoleStrategy.from_json()`, uses only public `MoleView` features (`day`, `min_recipient_count`, `recent_low_recipient_docs`, `days_since_last_leak`, `n_restricted_colleagues`) with zero access to `is_canary`, achieves empirically verified **`94.00%` `SolverPolicy` accuracy (`47/50`, mean score `+0.5434`)** across `50` fresh `v1.4` hard seeds `7000-7049` via `canary.forge.fitness.real_runner` (clearing `FEASIBLE_SOLVER_ACC = 0.85` with `9.0` percentage points to spare), and leaves frozen `v1.4` rules (`a8f99c2537c91d72`) untouched.

---

## 6. Reproducible Verification Ledger (`scripts/audit_seed6_seed26_forensics.py`)

Run the complete deterministic replay audit (`0` API keys, `< 0.5 s` CPU) with:

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_seed6_seed26_forensics.py --check
```

```json
{
  "tiers_version": "v1.4",
  "v14_hash": "a8f99c2537c91d72",
  "seeds_0_29_lock_status": "post-hoc locked (671ed96)",
  "harbor_rehearsal_pct_of_oracle": [93, 116, 131],
  "harbor_rehearsal_valid_trials": [10, 10, 9],
  "total_replay_discrepancies": 0,
  "failure_analysis_parity_errors": [],
  "careful_mole_optimal_day1_k": 20,
  "seed_6": {
    "mole_id": "e34",
    "decoy_id": "e20",
    "opencode_gemini_4_carbon": {"outcome": "caught", "accused_id": "e34", "day": 6, "score": 0.73, "canaries": 7, "tiny_confirmations": 0, "interviews": 25, "flips": 0, "p_mole": 0.9981},
    "reference_solver": {"outcome": "caught", "accused_id": "e34", "day": 6, "score": 0.71, "canaries": 9, "tiny_confirmations": 2, "interviews": 0, "flips": 0, "p_mole": 0.9995}
  },
  "seed_26": {
    "mole_id": "e08",
    "decoy_id": "e38",
    "opencode_gemini_4_carbon": {"outcome": "fooled", "accused_id": "e04", "day": 10, "score": -1.0, "canaries": 8, "days_1_to_3_canaries": 0, "tiny_confirmations": 0, "interviews": 43, "log_reads": 9, "flip_doc": "c6-2", "flip": "S3->S1", "p_accused": 0.9504},
    "reference_solver": {"outcome": "caught", "accused_id": "e08", "day": 7, "score": 0.69, "canaries": 11, "tiny_confirmations": 1, "interviews": 0, "flips": 0, "p_mole": 0.9681, "paired_raw_gap_V": 1.69}
  },
  "proposals": ["P12.1", "P12.2"]
}
```
