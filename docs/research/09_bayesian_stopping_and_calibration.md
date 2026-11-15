# 09. Bayesian Sequential Stopping, Moving Break-Even Thresholds, and Verbalized Confidence Calibration in Canary

**Squad:** `research` (`canary-research-w3`)  
**Baseline:** `origin/fr8/canary/research@d32d124e` (synced with `origin/justSilas@5f9b3297` / `afterquery-submit-2` `aa1c679e`, code-freeze tag `afterquery-final` `1bc3e281`; rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Audit Harness:** `scripts/audit_bayesian_stopping_calibration.py` and `tests/test_audit_bayesian_stopping_calibration.py` (`0` API calls, deterministic CPU, shallow-CI `--depth 1 --no-tags` safe, `0` protected paths touched)  
**Companion Monographs:** [Master Deception Synthesis](../research-deception.md) | [03. Leak Hunts, Canary Traps & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [06. Organisational Bias & Sleeper Port](06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [11. Empirical Transcript Bias Forensics](11_empirical_transcript_bias_forensics.md) | [13. Blackwell Channel Capacity & Lindley EIG](13_blackwell_channel_capacity_and_eig.md) | [17. Red-Team Swarms & Reward Integrity](17_redteam_reward_gaming_and_benchmark_integrity.md) | [18. Cross-Family gpt-5.5 vs Gemini Forensics](18_cross_family_gpt55_vs_gemini_forensics.md) | [20. Judge Peer-Review Q&A & Scorecard](20_judge_qa_and_proposal_scorecard.md)  
**Primary Benchmark Artifacts:** [Below-Break-Even Gallery](../reports/failure_gallery_breakeven.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Reference Optimality](../reports/reference_optimality.md) | [Gap Report](../reports/gap.md) | [Harbor Judge Rehearsal](../../results/harbor/rehearsal/TABLE.md) | [Cross-Family Behaviour](../../results/behaviour_compare_v1.4.md)

---

## 1. Executive Thesis: Formula Knowledge Does Not Imply Calibrated Bayesian Stopping

In Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `restrict_cost_per_day = 0.01`, `actions_per_day = 8`, `tool_call_cap = 420`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`, `framing_rate = 2.0`, frozen hash `a8f99c2537c91d72`), every investigator receives the exact terminal payoff rule inside `Env.instruction()` (`canary/env.py`): accusing the true mole earns remaining company value $+V \in [0, 1]$, accusing an innocent scores `wrong_accusation_score = -1.0`, and closing Day `21` without an accusation scores `0.0`. Solving $\mathbb{E}[\text{accuse} \mid P, V] = P \cdot V + (1 - P)(-1) > 0$ yields a **moving Bayesian break-even bar**:

$$P^*(V) = \frac{1}{1 + V}, \qquad \mathbb{E}[\text{accuse} \mid P, V] = (1 + V)\bigl(P - P^*(V)\bigr).$$

At Day `1` ($V = 1.00$), break-even sits at $50.00\%$; as leaks and canary deployments erode $V$ toward `0.46`, `0.23`, and `0.16` on Days `18-21`, $P^*(V)$ climbs monotonically to **`68.49%`**, **`81.30%`**, and **`86.21%`**. Across the `30` post-hoc locked paired dev seeds `0-29` (`data/runs/committed/v1.4/`), OpenCode `gemini-4-carbon` over MCP (`13` tools only, shell denied) scores `0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119` (`65% [24%, 98%]` raw, raw paired gap `5.30 V`; `0.360` vs `0.499` luck-adjusted, `72% [52%, 91%]`, luck-adjusted gap `4.19 V`), and `results/skill_ladder_v1.4.md` identifies EV stopping (`-0.371 +/- 0.032`) as the single steepest decision cliff on `v1.4` hard.

`scripts/audit_bayesian_stopping_calibration.py` replays all `30` paired OpenCode `gemini-4-carbon`, `SolverPolicy`, and OpenCode `gpt-5.5` trajectories alongside all `30` OpenCode commitment transcripts (`0` API calls) to establish five empirical findings grounded in nine peer-reviewed papers:

1. **Verbalized Overprecision Breaks Explicit Stopping Arithmetic (`29/30` Quantified Transcripts).** `gemini-4-carbon` explicitly knows and applies $P \cdot V - (1 - P) > 0$: on **`seed 11`** (its sole abstention), it computes $0.429 \times 0.20 - 0.571 = -0.485 < 0$ and rationally closes Day `21` at `0.00`. Yet across the `28` quantified accusations (`29/30` transcripts state an explicit probability or odds ratio; only `seed 26` omits a numerical percentage), its verbalized posterior averages **`96.60%` vs `87.94%` exact Bayesian $P_{\text{true}}(\text{accused})$** (`+8.66 pp` mean overprecision; `25/29` quantified episodes overconfident). When canaries isolate a singleton (`|C_acc| = 1`, `19` quantified accusations), overprecision is only **`+1.77 pp`**; when `|C_acc| >= 2` suspects remain consistent (`9` accusations), verbalized overprecision explodes to **`+23.20 pp`** (`+22.94 pp` across the `7` explicit-percentage un-isolated seeds `3, 7, 14, 15, 18, 20, 23`) and **`+33.43 pp`** across the `3` negative-EV gambles (`seeds 5, 18, 23`).
2. **Exact Moving-Bar Audit Exposes `3` Negative-EV Gambles Masked by Binary Luck (`Seeds 5, 18, 23`).** Under all three company-value estimators (`known_V`, `E[true V]`, and `true_V`), OpenCode `gemini-4-carbon` violates $P_{\text{true}} < P^*(V)$ on **`seeds 5, 18, 23`** (`51.02% < 86.11%`, `62.72% < 68.43%`, `45.17% < 81.22%` under `E[true V]`). Two lucky coin-flip hits (`+0.16` on `seed 5`, `+0.23` on `seed 23`) against one `-1.00` miss (`seed 18`) inject `+0.3268 V` of realized luck, hiding **`-0.9368 V` of negative luck-adjusted value** (`-0.9348 V` under `E[true V]`, `-0.8573 V` under `known_V`). Simply abstaining on those `3` seeds without changing a single investigative action recovers **`+0.9368 V` luck-adjusted** (`0.3596 -> 0.3909`, cutting **`22.36%`** of the entire luck-adjusted gap of `4.19 V`) and **`+0.61 V` raw** (`0.3223 -> 0.3427`).
3. **`SolverPolicy` Calibration Validates Canary's Luck-Adjusted Metric (`ECE = 0.0015`, `n = 30`; `95.6%-98.6%`, `n = 400`).** Across seeds `0-29`, `SolverPolicy` (`canary/solver/policy.py`, `canary/solver/belief.py`) commits **`0/30` below-break-even accusations** (tightest margin `+11.60 pp` on `E[true V]`, `+14.80 pp` on `known_V`), achieving `96.52%` mean posterior vs `96.67%` (`29/30`) empirical precision, **`Brier = 0.0275`**, and **`ECE = 0.0015`** (matching `docs/reports/reference_optimality.md` across `400` tuning seeds `8000-8399`, where stopping rules $p \ge a + b V$ add at most `+0.005` on `hard`).
4. **Cross-Family (`gpt-5.5`) and Harbor Judge-Path (`justSilas@5f9b3297`) Controls Isolate Cognitive Offloading.** Under identical MCP-only rules (`opencode-gpt-5.5`), `gpt-5.5` plants `17.17` canaries vs `4.17` interviews (`242` of `303` under-planted days in `gemini-4-carbon` vanish), achieving `0` violations against `P*(known_V)` (`1` borderline shot on `seed 5` at `66.37%` vs `68.43%` `P*(E[true V])`), `28/28` (`100.0%`) accusation precision (`Brier = 0.0108`), and `+0.504 +/- 0.064` (`101% [79%, 140%]` raw, `84% [67%, 103%]` LA, with `2` prose-only non-accusations on `seeds 0, 17`). In the Harbor judge-path rehearsal on `afterquery-final` (`1bc3e281`, updated at `aa1c679e` / `5f9b3297` in `results/harbor/rehearsal/TABLE.md`), where the isolated container permits `bash`/`python3` (`20/28` trials offloaded posterior filtering to shell scripts), `gemini-4-carbon` scored **`+0.472` (`93%`, `n = 10`), `+0.585` (`116%`, `n = 10`), and final Run 3 `+0.626` (`131%`, `9` valid trials, `5` finishing after `08:30`, `1` infra-excluded)** vs oracle `+0.506` (`28/29 = 96.6%` valid accusations correct).
5. **Zero-Protected-Path Proposals `P9.1` and `P9.2`.** Section 5 specifies and empirically validates **`P9.1`** (`gen_sunk_cost_urgency_anchor` in `canary/social/biases.py`: `300/300 = 100.0%` valid messages across `100` seeds x `3` late-horizon days, `LLR = 0.0000` nats, `SolverPolicy` loss `0.000 V`) and **`P9.2`** (`BrierCalibratedStoppingGate` in `canary/agents/policy.py`: post-hoc logit temperature + candidate-entropy calibration cutting leave-one-out soft Brier MSE **`4.42x`** from `0.0206` to `0.0047`, gating **exact seeds `[5, 18, 23]`** with `0/25` false blocks, and recovering **`+0.9368 V` LA / `+0.61 V` raw** out-of-fold).

---

## 2. Primary Literature Grounding (Live HTTP-200 Verified Links and Verbatim Quotes)

### 2.1 Loss-Derived Uncertainty Functions and Sequential Stopping: DeGroot (1962)

- **Citation:** DeGroot, M. H. (1962). Uncertainty, Information, and Sequential Experiments. *The Annals of Mathematical Statistics*, 33(2), 404-419.
- **Live Verified Links:** https://api.crossref.org/works/10.1214/aoms/1177704567 | https://doi.org/10.1214/aoms/1177704567
- **Theoretical Contribution:** Generalizes Shannon-Lindley mutual information to concave Bayes uncertainty functions induced directly by terminal statistical decision losses, proving that sequential policies must transition from broad entropy reduction during early experimentation to terminal loss minimization at the stopping boundary.
- **Verbatim Quote (Summary):**
> "The information in an experiment is then defined as the expected difference between the uncertainty of the prior distribution over $\Omega$ and the uncertainty of the posterior distribution. In any particular situation, the selection of an appropriate uncertainty function would typically be based on the use to which the experimenter's knowledge about $\theta$ is to be put. If, for example, the actions available to the experimenter and the losses associated with these actions can be specified as in a statistical decision problem, then presumably the uncertainty function would be determined from the loss function."
- **Relevance to Canary:** Directly formalizes the two-regime architecture of `SolverPolicy` (`canary/solver/policy.py`): during early days when $\max_e P(e) < P^*(V)$, balanced 3-variant `plant_canary` partitions minimize Shannon entropy $H(\text{Mole})$; near commitment, terminal asymmetric payoff $\max(0, P \cdot V - (1 - P))$ governs whether to stop immediately (`accuse_value > 0` and $P \ge 0.85$, or Day `21` with $P > 1/(1+V)$) or abstain at `0.00`.

### 2.2 Active Sequential Hypothesis Testing Under Wrong-Declaration Penalty: Naghshvar & Javidi (2013)

- **Citation:** Naghshvar, M., & Javidi, T. (2013). Active Sequential Hypothesis Testing. *The Annals of Statistics*, 41(6), 2703-2738.
- **Live Verified Links:** https://arxiv.org/abs/1203.4626 | https://api.crossref.org/works/10.1214/13-AOS1144 | https://doi.org/10.1214/13-AOS1144
- **Theoretical Contribution:** Establishes dynamic-programming lower and upper bounds on total sample-plus-error cost for an active investigator selecting sensing actions sequentially among $M$ hypotheses under an explicit wrong-declaration penalty, proving asymptotic optimality requires coupling high-rate exploration with high-reliability confirmation before stopping.
- **Verbatim Quote (Abstract):**
> "Consider a decision maker who is responsible to dynamically collect observations so as to enhance his information about an underlying phenomena of interest in a speedy manner while accounting for the penalty of wrong declaration. Due to the sequential nature of the problem, the decision maker relies on his current information state to adaptively select the most \"informative\" sensing action among the available ones."
- **Relevance to Canary:** Explains why `wrong_accusation_score = -1.0` (`TierParams` in `canary/rules.py`) coupled with daily expected leak bleed (`0.65 x 0.05 = 0.0325 V/day`) creates a genuine sequential stopping optimum: `SolverPolicy` waits until posterior concentration clears `0.85` (or Day `21` break-even $1/(1+V)$), maintaining a minimum margin of `+11.60 pp` above $P^*(\mathbb{E}[V_{\text{true}}])$ across all `30` seeds, whereas stopping early on `4` unresolved suspects (`seed 18`, Day `18`, `3` days remaining) incurs `-1.00` catastrophic declaration loss.

### 2.3 Strictly Proper Scoring Rules and Brier Reliability Decomposition: Broecker (2009)

- **Citation:** Broecker, J. (2009). Reliability, Sufficiency, and the Decomposition of Proper Scores. *Quarterly Journal of the Royal Meteorological Society*, 135(643), 1512-1519 (`arXiv:0806.0813`).
- **Live Verified Links:** https://arxiv.org/abs/0806.0813 | https://api.crossref.org/works/10.1002/qj.456 | https://doi.org/10.1002/qj.456
- **Theoretical Contribution:** Extends the classical binary Brier score decomposition into **reliability** (calibration divergence between stated forecast probabilities and true conditional event frequencies), **resolution**, and **irreducible uncertainty**, proving that strictly proper scores uniquely incentivize truthful, calibrated probability reporting and linking calibration directly to DeGroot-Fienberg sufficiency.
- **Verbatim Quote (Abstract):**
> "Scoring rules are an important tool for evaluating the performance of probabilistic forecasting schemes. In the binary case, scoring rules (which are strictly proper) allow for a decomposition into terms related to the resolution and to the reliability of the forecast. This fact is particularly well known for the Brier Score. In this paper, this result is extended to forecasts for finite--valued targets. Both resolution and reliability are shown to have a positive effect on the score."
- **Relevance to Canary:** Provides the exact mathematical decomposition computed in `expected_bayes_brier()` inside `scripts/audit_bayesian_stopping_calibration.py`: conditioned on the agent's own public observation filtrations $\mathcal{F}_t$ where $P_{\text{true}} = \Pr(Y = 1 \mid \mathcal{F}_t)$ is exact (`SolverPolicy` `ECE = 0.0015` on `n = 30`, `95.6%-98.6%` on `n = 400`), expected Brier loss decomposes additively as $\mathbb{E}[(P_{\text{stated}} - Y)^2 \mid \mathcal{F}_t] = (P_{\text{stated}} - P_{\text{true}})^2 + P_{\text{true}}(1 - P_{\text{true}})$, isolating Gemini's **`0.0206` overprecision excess** from the **`0.0836` irreducible Bayes floor** (`total = 0.1042`).

### 2.4 Overprecision vs Overestimation in Subjective Probability: Moore & Healy (2008)

- **Citation:** Moore, D. A., & Healy, P. J. (2008). The Trouble with Overconfidence. *Psychological Review*, 115(2), 502-517.
- **Live Verified Links:** https://api.crossref.org/works/10.1037/0033-295X.115.2.502 | https://doi.org/10.1037/0033-295X.115.2.502
- **Theoretical Contribution:** Disentangles three distinct phenomena conflated under "overconfidence" - *overestimation* of performance, *overplacement* relative to peers, and *overprecision* (excessive certainty in the accuracy of one's probability beliefs) - showing that overprecision is the most persistent cognitive distortion and corrupts downstream decisions even when the decision rule itself is understood.
- **Verbatim Quotes (Abstract):**
> "The authors present a reconciliation of 3 distinct ways in which the research literature has defined overconfidence: (a) overestimation of one's actual performance, (b) overplacement of one's performance relative to others, and (c) excessive precision in one's beliefs."
> "Overprecision appears to be more persistent than either of the other 2 types of overconfidence, but its presence reduces the magnitude of both overestimation and overplacement."
- **Relevance to Canary:** Solves the central forensic puzzle of Canary `v1.4` hard: why does `gemini-4-carbon` obey the abstention rule on `seed 11` ($P_{\text{stated}} = 42.9\% < 84.66\%$, though even `42.9%` overstates exact $P_{\text{true}}(\text{e37}) = 12.19\%$ by `+30.71 pp`) yet gamble recklessly on `seeds 5, 18, 23`? Because Moore-Healy **overprecision** inflates its stated belief on unresolved candidate sets (`|C_acc| >= 2`) by **`+23.20 pp`**, pushing true `45.17%-62.72%` posteriors above `82.0%-89.0%` in prose so they falsely clear $P^*(V)$.

### 2.5 Reference-Dependent Loss Framing and Horizon Risk-Seeking: Kahneman & Tversky (1979)

- **Citation:** Kahneman, D., & Tversky, A. (1979). Prospect Theory: An Analysis of Decision under Risk. *Econometrica*, 47(2), 263-291.
- **Live Verified Links:** https://api.crossref.org/works/10.2307/1914185 | https://doi.org/10.2307/1914185
- **Theoretical Contribution:** Demonstrates that outcomes evaluated below an initial reference endowment ($V_0 = 1.00$) fall onto a convex, steeper loss-domain value function, systematically driving risk-seeking gambles over sure intermediate outcomes.
- **Verbatim Quotes (Abstract):**
> "In particular, people underweight outcomes that are merely probable in comparison with outcomes that are obtained with certainty. This tendency, called the certainty effect, contributes to risk aversion in choices involving sure gains and to risk seeking in choices involving sure losses."
> "The value function is normally concave for gains, commonly convex for losses, and is generally steeper for losses than for gains."
- **Relevance to Canary:** When company value $V$ decays from `1.00` to `0.16-0.46` on Days `18-21`, rational Bayes utility raises $P^*(V) = 1/(1+V)$ toward `68.4%-86.2%` (`abstain = 0.00` becomes *more* attractive as upside $+V$ shrinks against fixed `-1.00` downside), whereas reference-dependent framing relative to $V_0 = 1.00$ perceives `0.00` abstention as a sure `-1.00` loss of the company and gambles (`seeds 5, 18, 23`).

### 2.6 Stochastic MDP Formalization of Sunk-Cost Abandonment Bias: Kleinberg, Oren, Raghavan & Sklar (2023)

- **Citation:** Kleinberg, J., Oren, S., Raghavan, M., & Sklar, N. (2023). Stochastic Model for Sunk Cost Bias (`arXiv:2106.11003`, formalizing the empirical sunk-cost effect of Arkes, H. R., & Blumer, C., 1985, *Organizational Behavior and Human Decision Processes*, 35(1), 124-140, https://api.crossref.org/works/10.1016/0749-5978(85)90049-4).
- **Live Verified Links:** https://arxiv.org/abs/2106.11003 | https://api.crossref.org/works/10.1016/0749-5978(85)90049-4
- **Theoretical Contribution:** Models sequential planning in a stochastic MDP where abandoning an endeavor after investing cumulative cost $C_{\text{sunk}}$ imposes a psychological penalty $\lambda \cdot C_{\text{sunk}}$ ($\lambda \ge 0$), proving that sunk-cost weighting distorts optimal abandonment thresholds and quantifying the resulting expected utility loss relative to an optimal bias-free agent.
- **Verbatim Quote (Abstract of `arXiv:2106.11003`):**
> "Agents exhibiting sunk-cost bias take into account the effort they have already spent on an endeavor when they evaluate whether to continue or abandon it. We model planning tasks in which an agent with this type of bias tries to reach a designated goal."
> "The agent's sunk cost bias is modeled by a cost that it incurs for abandoning the traversal: if the agent decides to stop traversing the graph, it incurs a cost of $\lambda\cdot C_{sunk}$, where ${\lambda\geq 0}$ is a parameter that captures the extent of the bias and $C_{sunk}$ is the sum of costs already invested. Since optimal (bias-free) behavior in this problem can involve abandoning the traversal before reaching the goal, the bias exhibited by these types of agents can result in sub-optimal behavior by shifting their decisions about abandonment."
- **Relevance to Canary:** Yields the exact closed-form threshold distortion tested in `sunk_cost_threshold()` (`scripts/audit_bayesian_stopping_calibration.py`) and directly grounds **Proposal `P9.1` (`gen_sunk_cost_urgency_anchor`)**: after cumulative value loss $C_{\text{sunk}} = 1 - V$, penalizing `0.00` abstention by $-\lambda(1 - V)$ shifts the perceived break-even bar from $P^*(V) = 1/(1+V)$ down to $P_{\text{sunk}}^*(V, \lambda) = \frac{1 - \lambda(1 - V)}{1 + V}$. At $\lambda = 0.35$, the Day-21 bar on `seed 5` ($V_{\text{known}} = 0.21$) drops from `82.64%` to **`59.79%`**; at $\lambda = 0.50$, $P_{\text{sunk}}^*(V, 0.50) \equiv 0.5000$ identically for all $V$, erasing the moving break-even adjustment completely!

### 2.7 Verbalized Probability Overconfidence in Black-Box LLMs: Xiong et al. (2024) & Lin, Hilton & Evans (2022)

- **Citation 1 (Black-Box Verbalized Overconfidence):** Xiong, M., Hu, Z., Lu, X., Li, Y., Fu, J., He, J., & Hooi, B. (2024). Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs. *International Conference on Learning Representations (ICLR 2024)* (`arXiv:2306.13063`). Live Verified Link: https://arxiv.org/abs/2306.13063
- **Citation 2 (Verbalized Probability Paradigm):** Lin, S., Hilton, J., & Evans, O. (2022). Teaching Models to Express Their Uncertainty in Words. *Transactions on Machine Learning Research (TMLR)* (`arXiv:2205.14334`). Live Verified Link: https://arxiv.org/abs/2205.14334
- **Verbatim Quote from Xiong et al. (2024) (Abstract):**
> "Our analysis uncovers several key insights: 1) LLMs, when verbalizing their confidence, tend to be overconfident, potentially imitating human patterns of expressing confidence. 2) As model capability scales up, both calibration and failure prediction performance improve."
- **Verbatim Quote from Lin, Hilton & Evans (2022) (Abstract):**
> "When given a question, the model generates both an answer and a level of confidence (e.g. \"90% confidence\" or \"high confidence\"). We compare the calibration of uncertainty expressed in words (\"verbalized probability\") to uncertainty extracted from model logits."
- **Relevance to Canary:** Because MCP tool-use agents lack white-box token-logit access over latent world hypotheses, they rely on in-context **verbalized probabilities** (`"~89% posterior probability"`, `">82%"`, `">13:1 combined likelihood ratio"`). Confirming Xiong et al. (2024), `gemini-4-carbon`'s verbalized probabilities cluster near `90%-99.9%` (`mean 96.60%` across `28` quantified accusations, `ECE = 0.0732`), imitating confident human investigative summaries whenever `|C_acc| >= 2` suspects remain unseparated.

### 2.8 Post-Hoc Logit Temperature Calibration: Guo, Pleiss, Sun & Weinberger (2017)

- **Citation:** Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. *Proceedings of the 34th International Conference on Machine Learning (ICML 2017)*, PMLR 70:1321-1330 (`arXiv:1706.04599`).
- **Live Verified Links:** https://arxiv.org/abs/1706.04599 | https://proceedings.mlr.press/v70/guo17a.html
- **Theoretical Contribution:** Establishes Expected Calibration Error ($\text{ECE}$) as the standard finite-bin reliability metric for modern neural predictors and demonstrates that post-hoc **temperature scaling** ($\hat{p} = \sigma(z / T)$ with $T > 1$) repairs systematic logit overconfidence without altering rank order on singleton predictions while sharply reducing proper scoring loss.
- **Verbatim Quote (Abstract):**
> "Confidence calibration -- the problem of predicting probability estimates representative of the true correctness likelihood -- is important for classification models in many applications. We discover that modern neural networks, unlike those from a decade ago, are poorly calibrated."
> "Our analysis and experiments not only offer insights into neural network learning, but also provide a simple and straightforward recipe for practical settings: on most datasets, temperature scaling -- a single-parameter variant of Platt Scaling -- is surprisingly effective at calibrating predictions."
- **Relevance to Canary:** Directly grounds **Proposal `P9.2` (`BrierCalibratedStoppingGate`)**: augmenting Guo et al.'s temperature scaling ($T = 1.4$) with a public leak-consistency entropy penalty $-\gamma \ln |C_{\text{consistent}}|$ ($\gamma = 1.0$) shrinks inflated verbalized logits precisely when multiple suspects remain unseparated (`|C_consistent| >= 2`), achieving a **`4.42x` leave-one-out soft Brier MSE reduction** (`0.0206 -> 0.0047`) and gating `3/3` negative-EV gambles (`seeds 5, 18, 23`).

---

## 3. Replay-Verified Stopping & Calibration Audit on `v1.4` Hard (`scripts/audit_bayesian_stopping_calibration.py`)

Running `/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_bayesian_stopping_calibration.py --check` deterministically replays every committed step on `v1.4` hard (`seeds 0-29`, frozen hash `a8f99c2537c91d72`) and verifies parity with `justSilas@5f9b3297`:

### 3.1 Cross-Agent Stopping, Calibration, and Break-Even Discipline (`Seeds 0-29`, Plus Harbor `5f9b3297`)

| Cohort / Harness (`v1.4` Hard) | Acc / Abs / Wrong | Raw Mean (`%` Solver) | Luck-Adj Mean (`%` Solver) | Mean $P_{\text{true}}(\text{acc})$ | Below $P^*(V_{\text{known}})$ | Below $P^*(\mathbb{E}[V])$ | Bayes Brier (Acc) | Bayes `ECE` (5-Bin) |
|---|---|---|---|---:|---|---|---:|---:|
| **`SolverPolicy` (`canary/solver/`)** | `30 / 0 / 1` | **`0.4990`** (`100.0%`) | **`0.4993`** (`100.0%`) | **`96.52%`** | **`0`** (`none`; min margin `+14.80 pp`) | **`0`** (`none`; min margin `+11.60 pp`) | **`0.0275`** | **`0.0015`** |
| **OpenCode `gemini-4-carbon` (MCP-only)** | `29 / 1 / 4` | **`0.3223`** (`64.6%`) | **`0.3596`** (`72.0%`) | `88.19%` | **`3` (`seeds 5, 18, 23`)** | **`3` (`seeds 5, 18, 23`)** | `0.1303` | `0.1148` |
| **OpenCode `gpt-5.5` (MCP-only)** | `28 / 2 / 0` | **`0.5037`** (`100.9%`) | **`0.4176`** (`83.6%`) | `93.98%` | **`0`** (`none`; `seeds 0, 17` prose-only) | **`1`** (`seed 5`: `66.37% < 68.43%`) | **`0.0108`** | - |
| **Harbor `gemini-4-carbon` (`5f9b3297`)** | `29` acc (`28/29 = 96.6%` ok) | **`+0.472 / +0.585 / +0.626`** (`93% / 116% / 131%` vs `+0.506` oracle) | - | Shell Python in `20/28` (`71.4%`) trials | Run 3 final: `9` valid (`5` post-`08:30`, `1` infra) | Externalizes set-intersection & Bayes math | - | - |

Key structural takeaways from Table 3.1:
- **`SolverPolicy` is empirically calibrated and stopping-optimal:** Across `30` paired seeds (`ECE = 0.0015`, `Brier = 0.0275`, `0` below-break-even calls) and `400` tuning seeds `8000-8399` in `docs/reports/reference_optimality.md` (`95.6%`, `96.6%`, `98.6%` accuracy in bins `[0.85, 0.90]`, `[0.90, 0.95]`, `[0.95, 1.00]`; best $p \ge a + b V$ rule adds only `+0.005`), `SolverPolicy`'s posterior is a genuine conditional probability, validating Canary's luck-adjusted metric $P_{\text{true}} V_{\text{true}} - (1 - P_{\text{true}})$.
- **Why `gpt-5.5`'s `100.9%` raw score equals `83.6%` luck-adjusted:** On `seed 5` (Day `14`, `4` consistent suspects `{e25, e26, e27, e29}`), `gpt-5.5` accused `e27` at $P_{\text{true}} = 66.37\%$, barely clearing $P^*(V_{\text{known}} = 0.51) = 66.23\%$ (`+0.15 pp`) while falling `-2.06 pp` below $P^*(\mathbb{E}[V_{\text{true}}] = 0.4612) = 68.43\%$ (`LA = -0.0641 V`, lucky hit `+0.41 V`), alongside `2` prose-only non-accusations (`seeds 0, 17` scoring `0.00` instead of calling `accuse`).
- **Why Harbor rehearsal (`93% / 116% / 131%`) eliminated MCP-only stopping errors:** When Harbor allows `bash`/`python3` (`20/28` inspected trials), `gemini-4-carbon` computes exact candidate set intersections and likelihood ratios in Python rather than estimating verbalized posteriors in prose, lifting valid accusation accuracy from `25/29` (`86.2%`) in MCP-only to **`28/29` (`96.6%`)** across the three final rehearsal runs (`+0.472`, `+0.585`, `+0.626`).

### 3.2 Verbalized Confidence vs Exact Bayesian Posterior (`29/30` OpenCode Transcripts)

Parsing the final commitment rationale of all `30` OpenCode `gemini-4-carbon` transcripts (`parse_verbalized_confidence()`) yields:

| Transcript Regime (`OpenCode gemini-4-carbon`, `v1.4` Hard) | Count | Mean $P_{\text{stated}}$ | Mean Exact $P_{\text{true}}$ | Mean Overprecision ($P_{\text{stated}} - P_{\text{true}}$) | Proper Brier Decomposition |
|---|---:|---:|---:|---:|---|
| All quantified transcripts (`28` acc + `seed 11` abstain) | `29 / 30` | `94.75%` | `85.33%` | **`+9.42 pp`** (`25/29` overconfident) | Unquantified: `seed 26` only (`5%` flip) |
| All quantified accusations (`seeds 0..29 \ {11, 26}`) | `28 / 29` | **`96.60%`** | **`87.94%`** | **`+8.66 pp`** (`ECE = 0.0732`) | $\mathbb{E}[\text{Brier}] = 0.1042 = \mathbf{0.0206}_{\text{excess}} + 0.0836_{\text{Bayes}}$ |
| Singleton-isolated accusations (`\|C_acc\| = 1`) | `19 / 28` | `99.13%` | `97.35%` | **`+1.77 pp`** (well-calibrated) | Canary watermarks pin posterior near `95%-99.9%` |
| Un-isolated accusations (`\|C_acc\| >= 2`, all `9` stated) | `9 / 28` | `91.28%` | `68.08%` | **`+23.20 pp`** (`+22.94 pp` on `7` `%`-stated) | `9/9` (`100%`) tie-break on `argmax(after_hours)` |
| Below-break-even gambles (`seeds 5, 18, 23`) | `3 / 28` | **`86.40%`** | **`52.97%`** | **`+33.43 pp`** (`+35.09` to `+37.19 pp` on `5, 23`) | Masked `-0.9368 V` LA loss behind `+0.3268 V` luck |

### 3.3 Six-Seed Forensic Spotlight: Moving Break-Even Bar vs Verbalized Overprecision

| Seed | Day (Left) | Outcome (`Acc` vs `Mole`) | Consistent Set $C_{\text{acc}}$ | $V_{\text{known}}$ / $\mathbb{E}[V]$ / $V_{\text{true}}$ | Break-Even $P^*(\mathbb{E}[V])$ | Exact $P_{\text{true}}$ | Stated $P_{\text{stated}}$ (Transcript Snippet) | Overprecision | Luck-Adj EV (Raw, Solver) |
|---:|---|---|---|---:|---:|---:|---|---:|---|
| **`5`** | `21` (`0`) | Hit (`e27` == `e27`) | `{e27, e32}` (`2`) | `0.21 / 0.161 / 0.16` | **`86.11%`** | **`51.02%`** | **`88.21%`** (`>13:1 combined likelihood ratio in favor of e27`, `92.86%` pairwise) | **`+37.19 pp`** | **`-0.4082 V`** (`+0.16`, `+0.52`) |
| **`18`** | `18` (`3`) | **MISS** (`e29` != `e27`) | `{e09, e27, e29, e37}` (`4`) | `0.51 / 0.461 / 0.46` | **`68.43%`** | **`62.72%`** | **`89.00%`** (`~89% posterior probability`) | **`+26.28 pp`** | **`-0.0842 V`** (`-1.00`, `+0.52`) |
| **`23`** | `21` (`0`) | Hit (`e29` == `e29`) | `{e15, e29, e38}` (`3`) | `0.28 / 0.231 / 0.23` | **`81.22%`** | **`45.17%`** | **`82.00%`** (`highest-posterior suspect (>82%)`) | **`+36.83 pp`** | **`-0.4444 V`** (`+0.23`, `+0.32`) |
| **`11`** | `21` (`0`) | **Abstain** (`None` vs `e09`) | `7` consistent (`top=e30`) | `0.23 / 0.181 / 0.13` | **`84.66%`** | `12.19%` (`e37`) | `42.90%` (`e37 (P ~ 42.9%)` -> EV `-0.485 < 0`) | `+30.71 pp` | **`0.0000 V`** (`0.00`, `+0.62`) |
| **`15`** | `12` (`9`) | **MISS** (`e34` != `e37`) | `{e34, e37}` (`2`) | `0.69 / 0.641 / 0.69` | `60.93%` | `80.49%` | `93.00%` (`~93% overall posterior`) | `+12.51 pp` | `+0.3602 V` (`-1.00`, `-1.00`) |
| **`26`** | `10` (`11`) | **MISS** (`e04` != `e08`) | `{e04}` (`1`, `c6-2` flip) | `0.67 / 0.621 / 0.67` | `61.68%` | `95.04%` | *Unquantified* (singleton `5%` canary flip) | - | `+0.5872 V` (`-1.00`, `+0.69`) |

Two forensic contrasts stand out:
1. **Why fixed `50%` or `60%` audit cutoffs fail (`seed 18`):** On `seed 18` (Day `18`), `gemini-4-carbon` planted `0` canaries across Days `14-18` (spending `32` interviews instead after `242` of `303` under-planted full-budget days cohort-wide) and accused `e29` at $P_{\text{true}} = 62.72\%$. Static `P >= 0.50` or `P >= 0.60` buckets misclassify `seed 18` as "justified", missing that eroded $V_{\text{true}} = 0.46$ had already raised $P^*(V)$ to **`68.49%`** (`EV = -0.0842 V < 0`) with `3` full days still left to plant a 4-person splitting canary over `{e09, e27, e29, e37}`.
2. **Negative-evidence neglect + unframed log ratios (`seeds 5, 23`):** On `seed 5`, leak-only posterior (`behaviour_temper = 0`) actually favored `e32` (`61.16%`) over `e27` (`34.33%`) because `e27` held more *unleaked* canaries; on `seed 23`, leak-only placed `e29` *third* (`29.42%` behind `e15` `31.80%` and `e38` `31.44%`). Ignoring unleaked-canary survival likelihoods and comparing `after_hours` counts against unframed `0.10/day` instead of framed `0.10 + 1.0/38 = 0.1263/day` produced `+37.19 pp` and `+36.83 pp` of verbalized overprecision.

---

## 4. Zero-Exploration Counterfactual: Exact Stopping Rule on `known_V`

What share of the `v1.4` hard gap comes purely from violating $P_{\text{true}}(\text{accused}) \ge P^*(V_{\text{known}})$ at the final step, holding `100%` of Gemini's suboptimal exploration (`68.0` interviews, `8.5` canaries) fixed?

- **Identical seed set across all three $V$ estimators:** Checking $P_{\text{true}} < P^*(V)$ under agent-visible `known_V`, Bayesian `E[true V]`, and ground-truth `true_V` flags the **exact same `3` seeds `[5, 18, 23]`** (`same_seeds_under_exp_and_true_V = True`).
- **Expected & luck-adjusted recovery:** Replacing those `3` negative-EV accusations with `0.00` abstention yields **`+0.8573 V`** on `known_V`, **`+0.9348 V`** on `E[true V]`, and **`+0.9368 V` luck-adjusted** (`+0.0312 V/episode`), lifting OpenCode `gemini-4-carbon` from **`0.3596` (`72.03%`) to `0.3909` (`78.28%` of `SolverPolicy`)** and eliminating **`22.36%`** of the entire `4.19 V` (`4.1897 V`) luck-adjusted gap (`4.1897 V -> 3.2529 V`).
- **Realized raw score gain despite forfeiting `2` lucky hits:** Even though `seeds 5` (`+0.16`) and `23` (`+0.23`) happened to hit by chance, avoiding `seed 18`'s `-1.00` miss nets **`+0.61 V` raw** (`9.67 V -> 10.28 V`, mean `0.3223 -> 0.3427`). Moreover, across all `30` seeds, `seeds 5, 18, 23` account for **`+1.6429 V` (`48.46%`)** of Gemini's total `+3.3898 V` accusation-penalty shortfall (`+2.1529 V` or `51.38%` of the total `30`-seed luck-adjusted gap).

---

## 5. Concrete Actionable Proposals (`P9.1` and `P9.2`, Zero Protected Paths)

Both proposals target **non-protected** surfaces (`canary/social/biases.py` and `canary/agents/policy.py`), preserve Canary `v1.4` frozen hash `a8f99c2537c91d72` (`canary/rules.py`, `canary/env.py`, `canary/solver/`, `canary/reproduce.py`, and `harbor/` untouched), enforce strict zero hidden mole leakage (`PublicDayFacts` conditional independence $I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$), and preserve `>= 85%` `SolverPolicy` catchability.

### 5.1 Proposal `P9.1`: Zero-Leakage Sunk-Cost & Eroding-`V` Urgency Anchor (`canary/social/biases.py`)

- **Target Surface:** Drop-in workplace social-bias generator `gen_sunk_cost_urgency_anchor(ctx, rng)` in `canary/social/biases.py` (opt-in `v1.6` social layer; `0` protected paths touched).
- **Literature Grounding:** Kahneman & Tversky (1979) loss-domain risk-seeking and Kleinberg, Oren, Raghavan & Sklar (2023) sunk-cost abandonment aversion ($P_{\text{sunk}}^*(V, \lambda) = \frac{1 - \lambda(1-V)}{1+V}$).
- **Mechanism & Strict Zero-Leakage Construction:**
  1. **Public-Only Candidate & RNG Seeding:** On late-horizon days $d \in \{12, 15, 18\}$, constructs candidate pool $C_{\text{pub}}(d) = \bigl(\bigcap_{m \in \text{pub\_sample}} \text{recipients}(m)\bigr) \setminus \{\text{decoy}\}$ solely from `PublicDayFacts` (`planned_docs` up to day $d$ and public `decoy`), seeded deterministically from `f"p9_pub:{tier}:{company}:{day}:{n_pub_docs}"` with **zero** access to `world.mole` or `world_seed`.
  2. **Authority Closure Pressure:** Selects a non-decoy senior speaker (`manager`, `lead`, `controller`, `counsel`) who cites eroded public company value $\hat{V} \approx 1 - 0.05 L_{\text{reg}}$ and remaining horizon $21 - d$, pressuring the investigator not to *"write off two weeks of work at zero"* on focal target `Name (eXX)` (placed inside `body[:110]` alongside salience terms `doc`/`leak`/`meeting`, with `0` `DECOY_VOCAB` words and `0` forbidden subject prefixes).
- **Empirical Verification (`audit_p9_1_sunk_cost_generator()`, `100` `v1.4` Hard Seeds x Days `12, 15, 18` = `300` Events):**
  - **Lint, Salience & Decoy-Disjoint Validity:** **`300 / 300 = 100.0%`** pass `lint_text()`, salience-in-`body[:110]`, non-decoy speaker/target, and `DECOY_VOCAB` disjointness.
  - **Zero Hidden Mole Information:** Conditional mutual information $I(\text{Target}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = \mathbf{0.0000\text{ nats}}$ and exact log-likelihood ratio $\text{LLR} = \mathbf{0.0000\text{ nats}}$ (`SolverPolicy` ignores uncorroborated chat: **`0.000 V` policy loss**, catchability unchanged at `96.7% >= 85%`), while uncalibrated agents applying $\lambda \in [0.35, 0.50]$ suffer a `22.9-32.6 pp` perceived break-even collapse (`82.64% -> 59.79%` or `50.00%` at $V = 0.21$).

### 5.2 Proposal `P9.2`: Leave-One-Out Brier-Calibrated Logit & Entropy Stopping Gate (`canary/agents/policy.py` & `train/`)

- **Target Surface:** Lightweight wrapper `BrierCalibratedStoppingGate` in `canary/agents/policy.py` (and small-model inference post-processor in `train/eval_agent.py`; `0` protected paths touched, `0` extra MCP calls).
- **Literature Grounding:** Guo, Pleiss, Sun & Weinberger (2017) logit temperature scaling, Broecker (2009) proper Brier reliability minimization, and Xiong et al. (2024) verbalized LLM confidence recalibration.
- **Mathematical Specification:** Given an LLM's verbalized probability $p_{\text{raw}} \in (0, 1)$, its own observed leak-consistent candidate count $|C_{\text{consistent}}| \ge 1$ (computed purely from the agent's own `check_leak_feed`, `list_documents`, and `plant_canary` tool history), and visible company value $V_{\text{known}}$ from `status`:

$$p_{\text{cal}} = \sigma\!\left(\frac{\operatorname{logit}(p_{\text{raw}})}{T} + b - \gamma \ln |C_{\text{consistent}}|\right), \qquad \text{accuse iff } p_{\text{cal}} \ge P^*(V_{\text{known}}) = \frac{1}{1 + V_{\text{known}}}.$$

- **Out-of-Fold Leave-One-Out (`LOO`) Empirical Evaluation Across All `28` Quantified OpenCode Accusations (`evaluate_p9_2_stopping_gate()`):**

| Stopping / Calibration Policy (`n = 28` Quantified Accusations, `30`-Seed Cohort) | Soft Brier MSE $\mathbb{E}[(P - P_{\text{true}})^2]$ | Expected Total Brier | Empirical Binary Brier | Gated Abstain Seeds (LOO) | False Blocks on `EV > 0` | 30-Seed Luck-Adj Gain | 30-Seed Raw Score Gain |
|---|---:|---:|---:|---|---:|---:|---:|
| **Uncalibrated Verbalized `gemini-4-carbon`** ($T=1, \gamma=0$) | `0.0206` | `0.1042` | `0.0966` | `[]` (`0` gated) | `0 / 25` | `+0.0000 V` (`0.3596`) | `+0.00 V` (`0.3223`) |
| **`P9.2` `BrierCalibratedStoppingGate` (Full Fit: $T=1.4, b=0.0, \gamma=1.0$)** | **`0.0027`** (`7.57x` cut) | `0.0863` | `0.0825` | **`[5, 18, 23]`** | **`0 / 25`** | **`+0.9368 V`** (`0.3909`) | **`+0.61 V`** (`0.3427`) |
| **`P9.2` `BrierCalibratedStoppingGate` (Strict `28`-Fold LOO)** | **`0.0047`** (**`4.42x` cut**) | **`0.0882`** | **`0.0838`** | **`[5, 18, 23]`** (`3/3` recall) | **`0 / 25`** (`100%` prec.) | **`+0.9368 V`** (`+22.36%` gap cut) | **`+0.61 V`** |
| **Exact `SolverPolicy` Bayes Posterior Reference** | `0.0000` | **`0.0836`** (floor) | `0.1027` | **`[5, 18, 23]`** | `0 / 25` | **`+0.9368 V`** (`0.3909`) | **`+0.61 V`** |

Why `P9.2` works with `100%` out-of-fold precision and recall:
- When canaries isolate a singleton (`|C_consistent| = 1`), $\ln |C_{\text{consistent}}| = 0$, so $T = 1.4$ maps `99.0%` (`logit +4.60`) to `96.38%` - safely above every feasible $P^*(V_{\text{known}})$, producing **`0 / 25` false blocks** on positive-EV accusations!
- When `|C_consistent| >= 2` suspects remain unseparated (`seeds 5, 18, 23` with $|C| \in \{2, 4, 3\}$ and inflated verbalized claims `88.21%`, `89.00%`, `82.00%`), subtracting $\gamma \ln |C|$ deflates `p_cal` below $P^*(V_{\text{known}})$ (`82.64%`, `66.23%`, `78.12%`) in every single leave-one-out fold, matching the exact Bayesian stopping oracle on `28/28` episodes without touching `SolverPolicy` or `Env`.

---

## 6. Summary Verification Ledger (`scripts/audit_bayesian_stopping_calibration.py`)

```json
{
  "monograph": "09_bayesian_stopping_and_calibration",
  "baseline_sync": "justSilas@5f9b3297",
  "tiers_version": "v1.4",
  "v14_frozen_hash": "a8f99c2537c91d72",
  "seed_pool_status": "post_hoc_locked_dev_seeds_0_to_29",
  "opencode_gemini_4_carbon": {
    "raw_mean": 0.3223,
    "luck_adjusted_mean": 0.3596,
    "below_breakeven_seeds": [5, 18, 23],
    "verbalized_overprecision_acc_28_pp": 8.66,
    "verbalized_overprecision_unisolated_9_pp": 23.2,
    "verbalized_overprecision_below_be_3_pp": 33.43
  },
  "solver_reference": {
    "raw_mean": 0.499,
    "luck_adjusted_mean": 0.4993,
    "below_breakeven_seeds": [],
    "brier_30_acc": 0.0275,
    "ece_30_acc": 0.0015
  },
  "cross_harness_controls": {
    "opencode_gpt_5_5_raw_mean": 0.5037,
    "opencode_gpt_5_5_accused_correct": "28/28",
    "harbor_rehearsal_5f9b3297_ratios_pct": [93.3, 115.6, 131.0],
    "harbor_rehearsal_5f9b3297_valid_ns": [10, 10, 9]
  },
  "proposals": {
    "P9.1_valid_events": "300/300",
    "P9.1_exact_llr_nats": 0.0,
    "P9.1_solver_policy_loss_V": 0.0,
    "P9.2_loo_soft_brier_reduction_x": 4.42,
    "P9.2_loo_gated_seeds": [5, 18, 23],
    "P9.2_loo_luck_adjusted_gain_V": 0.9368,
    "P9.2_loo_raw_gain_V": 0.61
  }
}
```
