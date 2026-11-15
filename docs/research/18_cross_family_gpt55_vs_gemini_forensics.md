# 18. Cross-Family Cognitive-Behavioral Forensics: `gpt-5.5` vs `gemini-4-carbon` vs `SolverPolicy` on Canary `v1.4` Hard

**Squad:** `research` (`canary-research-w4`)  
**Baseline:** `origin/justSilas@5f9b3297` (`afterquery-submit-2` `aa1c679e`, code-freeze tag `afterquery-final` `1bc3e281`, rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Audit Harness:** `scripts/audit_gpt55_cross_family_forensics.py` and `tests/test_audit_gpt55_cross_family_forensics.py` (`0` API calls, shallow-CI `--depth 1 --no-tags` safe, `0` protected paths touched)  
**Companion Synthesis & Monographs:** [Master Deception Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [03. Leak Hunts & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [10. Proposal Simulations & Zero-Leakage Proofs](10_proposal_simulations_and_zero_leakage_proofs.md) | [11. Empirical Transcript Bias Forensics](11_empirical_transcript_bias_forensics.md) | [13. Blackwell Channel Capacity & Lindley EIG](13_blackwell_channel_capacity_and_eig.md) | [14. Sleeper Mole Catalog & Tournament](14_sleeper_mole_catalog_and_head_to_head.md) | [17. Red-Team Swarms & Reward Integrity](17_redteam_reward_gaming_and_benchmark_integrity.md) | [20. Judge Q&A & Scorecard](20_judge_qa_and_proposal_scorecard.md)  
**Primary Committed Artifacts:** [README](../../README.md) | [Gap Report](../reports/gap.md) | [CEO Log](../reports/CEO.md) | [Cross-Family Behaviour](../../results/behaviour_compare_v1.4.md) | [Harbor Judge Rehearsal](../../results/harbor/rehearsal/TABLE.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Reference Optimality](../reports/reference_optimality.md)

---

## 1. Executive Thesis: What Controlled Cross-Family Replication Proves About Canary

Running a second frontier model family (`opencode:openai/gpt-5.5`, pre-registered at commit `cf394894` across all `30` primary dev seeds `0..29` under identical MCP-only permissions `{"*": "deny", "canary_*": "allow"}`) transforms Canary's `v1.4` hard benchmark from a single-agent measurement into a controlled **cognitive-behavioral natural experiment**:

1. **Sufficiency of Canary's Tools and Instructions (`101%` Raw Parity vs `65%` MCP-Only Shortfall).** With the exact same `13` MCP tools and task specification (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `restrict_cost_per_day = 0.01`, `actions_per_day = 8`, `tool_call_cap = 420`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`, `framing_rate = 2.0`; frozen hash `a8f99c2537c91d72`), OpenCode `gpt-5.5` achieves **`+0.504 +/- 0.064`** (`30/30` valid, `0` infra exclusions, `$38.91` spend) vs `SolverPolicy` **`0.499 +/- 0.119`** (**`101% [79%, 140%]`** raw, paired diff `+0.005 +/- 0.141`; **`84% [67%, 103%]`** luck-adjusted at `+0.418` vs `+0.499`), whereas OpenCode `gemini-4-carbon` scores **`0.322 +/- 0.199`** (**`65% [24%, 98%]`** raw, raw paired gap `5.30 V`; **`72% [52%, 91%]`** luck-adjusted, luck-adjusted gap `4.19 V`). Meanwhile, in the Harbor `0.26.0` judge-path rehearsal on `afterquery-final` (`1bc3e281`, finalized at `justSilas@5f9b3297` / `aa1c679e`), where isolated `bash`/`python3` is available (`20/28 = 71.4%` shell offloading), `gemini-4-carbon` reaches **`+0.472` (`93%`, `n = 10`)**, **`+0.585` (`116%`, `n = 10`)**, and final Run 3 **`+0.626` (`131% [86%, 590%]`, `9` valid trials, `5` finishing after `08:30`, `1` infra-excluded; `28/29 = 96.6%` overall valid accusations correct)** vs oracle `+0.506`. Together, these two controls prove that `gemini-4-carbon`'s MCP-only deficit is neither an underspecified prompt nor a broken harness, but an intrinsic **in-head active-experimentation and actuarial-bookkeeping failure**.
2. **Sharp Behavioral Divergence (`17.17` Canaries vs `4.17` Interviews, `28/28` Precision).** By Blackwell's (1953) Equivalence Theorem, a leaked 3-variant `plant_canary` (`0.865440` nats conditional MI) strictly dominates `interview` (`0.004774` nats KL, `181.27x` weaker; exact garbling $g_A = 224/925$, $g_{\neg A} = 184/925$). `gpt-5.5` internalizes this hierarchy: it starts planting canaries on Day 1 in **`30/30` (`100.0%`)** episodes (vs `11/30 = 36.7%` for `gemini-4-carbon`), issues **`515` `plant_canary` calls (`17.17/ep`, `514` `ok=True` = `17.13/ep`, rounding to `17.2` in `behaviour_compare_v1.4.md`)** across **`257 / 274 = 93.80%` two-canary pre-terminal days** (`0` one-canary days, only `1/47` full-budget under-planted days vs `255` calls / `254` `ok=True` = `8.50` / `8.47` per ep and `242` of `303` under-planted days for `gemini-4-carbon`), restricts `interview` to **`125` calls (`4.17/ep`, `6.0%` of `69.2` calls/ep)** vs `gemini-4-carbon`'s **`2,041` interviews (`68.03/ep`, `53.1%` of `128.0` calls/ep)**, and achieves **`28 / 28 = 100.0%` accusation precision** (`0` wrong accusations, min posterior `0.664`, `0` below-`0.60` gambles).
3. **Why `84%` Luck-Adjusted Matters: Action-Completion Slips (`2/30` Prose Misses on Seeds `0` & `17`) + Cue-Ignoring Cost on `400` Fresh Seeds (`0.496` vs `0.561`).** Despite `101%` raw parity on `seeds 0..29`, `gpt-5.5` trails `SolverPolicy` by **`2.4463 V` (`83.67%` = `84% [67%, 103%]`)** on expected decision value for two distinct cognitive reasons:
   - **Protocol Action Slips & Goal Neglect (`seeds 0` & `17`, `1.2520 V` = `51.18%` of LA deficit):** On `seed 0` (`e38`, Day `8`, `P = 0.949`) and `seed 17` (`e28`, Day `9`, `P = 0.963`), `gpt-5.5` narrowed the public consistent set to the **exact singleton true mole** (`|C| = 1`), then emitted `"Accusing e38..."` and `"Accusing e28..."` as terminal assistant prose without invoking the `accuse` MCP tool, scoring `0.000` (a textbook **Norman, 1981** action slip, **Duncan et al., 1996** goal neglect under zero error feedback, and **Einstein & McDaniel, 2005** prospective-memory action-retrieval failure at the **Yao et al., 2023** ReAct verbal-action boundary). Counterfactually executing those `2` intended accusations lifts `gpt-5.5` to **`+0.547` raw (`109.6%`)** and **`+0.456` luck-adjusted (`91.4%`)**.
   - **Fast-and-Frugal Log-Ignoring Heuristic (`0.496 +/- 0.036` vs `0.561 +/- 0.032` on `400` Fresh Seeds `9000-9399`):** Notice that `gpt-5.5`'s slip-repaired raw mean on `seeds 0..29` (`0.547`) matches within `0.001 V` the score of `SolverPolicy` re-parameterized to copy `gpt-5.5`'s two habits (`0.546` with zero `read_access_logs` likelihood weight and fixed `2` canaries/day, `docs/reports/gap.md`). On `seeds 0..29`, this **Gigerenzer & Gaissmaier (2011)** noncompensatory heuristic beat `SolverPolicy` (`0.546` vs `0.499`) only because `seeds 0..29` was a below-average `30`-seed draw for the reference (`1` `5%` fingerprint flip on `seed 4`), whereas `gpt-5.5` went `5/5` on its un-isolated accusations (`seeds 5, 7, 16, 21, 23`, losing `1.4884 V` = `60.84%` of LA deficit). Tested out-of-sample on **`400` fresh hard seeds `9000-9399`** (**Cawley & Talbot, 2010**), ignoring calibrated `after_hours` log evidence drops the `gpt-5.5`-habit solver to **`0.496 +/- 0.036`** vs unchanged `SolverPolicy` **`0.561 +/- 0.032`** (**`88.41%`**, `-0.065 V/ep`, confirming **Dawes, 1979** and **Dawes, Faust & Meehl, 1989**).
4. **Actionable Zero-Protected-Path Proposals `P18.1` and `P18.2`.** Section 6 turns both findings into drop-in Canary upgrades: **`P18.1`** (`cadence_evader_sleeper_v14` in `canary/mole/dsl.py` / `data/forge/`) exploits `gpt-5.5`'s predictable `2`-canary/day narrow-partition cadence without violating catchability (**`100.0% >= 85.0%`** `SolverPolicy` accuracy, `+0.550` solver score, while dropping `FixedTwoCanaryBisector` from **`+0.501` to `+0.343`** [`-0.157 V`] and lifting `min_regret` from **`-0.0017` to `+0.2070`** [`+0.2087 V` gain]); and **`P18.2`** (`canary/analysis/slip_vs_bias.py`) decomposes protocol action slips vs epistemic biases using strictly public step logs (`PublicDayFacts` zero hidden mole leakage, `60/60` frontier and `90/90` full-cohort consistent-set parity).

---

## 2. Primary Literature Grounding (Live HTTP-Verified URLs and Verbatim Quotes)

### 2.1 Execution Slips, Goal Neglect, and Prospective Memory in Schema-Guided Action: Norman (1981), Duncan et al. (1996) & Einstein & McDaniel (2005)

- **Citation:** Norman, D. A. (1981). Categorization of Action Slips. *Psychological Review*, 88(1), 1-15; Duncan, J., Emslie, H., Williams, P., Johnson, R., & Freer, C. (1996). Intelligence and the Frontal Lobe: The Organization of Goal-Directed Behavior. *Cognitive Psychology*, 30(3), 257-303; and Einstein, G. O., & McDaniel, M. A. (2005). Prospective Memory: Multiple Retrieval Processes. *Current Directions in Psychological Science*, 14(6), 286-290.
- **Live Verified Links:** https://doi.org/10.1037/0033-295X.88.1.1 | https://openalex.org/W2161829306 | https://doi.org/10.1006/cogp.1996.0008 | https://pubmed.ncbi.nlm.nih.gov/8660786/ | https://doi.org/10.1111/j.0963-7214.2005.00382.x
- **Verbatim Quote from Norman (1981) (Abstract):**
> "A slip is the error that occurs when a person does an action that is not intended. In this article I examine several collections of slips, primarily of actions, with the aim of devising a theoretical explication. A theory of action is outlined in which an action sequence is represented by a parent schema and numerous child schemas, in which several action schemas can be active at any one time, and in which each schema has a set of triggering conditions and an activation value. ... The three major categories of slips are: (a) errors in the formation of the intention (which includes the subcategories of mode and description errors); (b) faulty activation of schemas (which includes the subcategories of capture errors, data-driven and associative activations, loss of intention, and misordering of action components); and (c) faulty triggering (which includes the subcategories of spoonerisms, blends, intrusions of thoughts, and premature triggering)."
- **Verbatim Quote from Duncan et al. (1996) (Abstract):**
> "In line with conventional distinctions between controlled and automatic processing, eliciting conditions for goal neglect include novelty, weak error feedback, and multiple concurrent task requirements. Under these conditions neglect is linked closely to g and extremely common after frontal lesions. Following many other models, we suggest that behavior in any task is structured by a set of action constraints or requirements, derived in part from verbal instructions and specified at multiple levels of abstraction."
- **Verbatim Quote from Einstein & McDaniel (2005) (Abstract):**
> "An interesting challenge for researchers who study prospective memory is to explain how people recognize environmental events as cues for actions. Whereas some theorists propose that a capacity-consuming monitoring process is the only means by which intentions can be retrieved, we argue that the cognitive system relies on multiple processes, including spontaneous processes that reflexively respond to the presence of target events."
- **Canary Grounding (`gpt-5.5` Seeds `0` & `17`, Proposal `P18.2`):** Separates `gpt-5.5`'s `2/30` non-accusations from `gemini-4-carbon`'s epistemic errors. On `seed 0` (`P = 0.949`) and `seed 17` (`P = 0.963`), `gpt-5.5`'s parent investigative intention succeeded completely (`|C| = 1` on the true mole), but child-schema execution suffered **goal neglect under zero error feedback** (**Duncan et al., 1996**) and a **prospective-memory / loss-of-intention slip** (**Norman, 1981**; **Einstein & McDaniel, 2005**): once the target event (`|C| = 1`) arrived, the model wrote `"Accusing e38..."` / `"Accusing e28..."` in natural language without retrieving the deferred `accuse` tool constraint (`51.18%` of `gpt-5.5`'s luck-adjusted deficit vs `0.00%` for `gemini-4-carbon`).

### 2.2 Verbal Reasoning Traces vs Grounded Environment Actions: Yao et al. (2023)

- **Citation:** Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. *International Conference on Learning Representations (ICLR 2023)* (`arXiv:2210.03629`).
- **Live Verified Links:** https://arxiv.org/abs/2210.03629 | https://doi.org/10.48550/arXiv.2210.03629
- **Verbatim Quote (Abstract):**
> "In this paper, we explore the use of LLMs to generate both reasoning traces and task-specific actions in an interleaved manner, allowing for greater synergy between the two: reasoning traces help the model induce, track, and update action plans as well as handle exceptions, while actions allow it to interface with external sources, such as knowledge bases or environments, to gather additional information."
- **Canary Grounding (`opencode-cli+mcp_server`, Proposal `P18.2`):** In MCP agentic loops (`OpenCode 1.19.5`), an assistant turn without a structured tool call terminates the turn loop. `gpt-5.5` spent `166,776` reasoning tokens across `30` episodes maintaining clean internal set-intersection plans, yet on `2/30` episodes conflated a declarative reasoning conclusion (`"Accusing eXX..."`) with an environment-mutating MCP action (`canary_accuse`), motivating `P18.2`'s public transcript-to-ledger slip detector.

### 2.3 Fast-and-Frugal Single-Cue Dominance Under Skewed Cue Validities: Gigerenzer & Gaissmaier (2011)

- **Citation:** Gigerenzer, G., & Gaissmaier, W. (2011). Heuristic Decision Making. *Annual Review of Psychology*, 62, 451-482.
- **Live Verified Links:** https://doi.org/10.1146/annurev-psych-120709-145346 | https://pubmed.ncbi.nlm.nih.gov/21126183/
- **Verbatim Quote (Abstract):**
> "Heuristics are efficient cognitive processes, conscious or unconscious, that ignore part of the information. Because using heuristics saves effort, the classical view has been that heuristic decisions imply greater errors than do "rational" decisions as defined by logic or statistical models. ... This research indicates that (a) individuals and organizations often rely on simple heuristics in an adaptive way, and (b) ignoring part of the information can lead to more accurate judgments than weighting and adding all information, for instance for low predictability and small samples."
- **Canary Grounding (`17.17` Canaries vs `4.17` Interviews, Small-Sample `n = 30` vs `n = 400`):** Directly explains **both** halves of `gpt-5.5`'s empirical profile! First, by ignoring low-validity cues (`interview_lr = 1.2` and framed `after_hours` logs) and relying noncompensatorily on 3-variant `plant_canary` intersections (`17.17` canaries/ep, `6.0%` interview share), `gpt-5.5` avoids `gemini-4-carbon`'s cue-dilution collapse (`+0.504` vs `+0.322`). Second, exactly as Gigerenzer & Gaissmaier note ("for instance for low predictability and small samples"), `gpt-5.5`'s cue-ignoring heuristic even outscored full Bayesian weighting on the small `30`-seed sample (`0.546` reparameterized / `0.547` slip-repaired vs `0.499`), before reverting below Bayes (`0.496` vs `0.561`) at `n = 400`.

### 2.4 Proper vs Improper Cue Weighting and Actuarial Integration: Dawes (1979) & Dawes, Faust & Meehl (1989)

- **Citation:** Dawes, R. M. (1979). The Robust Beauty of Improper Linear Models in Decision Making. *American Psychologist*, 34(7), 571-582; and Dawes, R. M., Faust, D., & Meehl, P. E. (1989). Clinical Versus Actuarial Judgment. *Science*, 243(4899), 1668-1674.
- **Live Verified Links:** https://doi.org/10.1037/0003-066X.34.7.571 | https://doi.org/10.1126/science.2648573 | https://pubmed.ncbi.nlm.nih.gov/2648573/
- **Verbatim Quote from Dawes (1979) (Abstract):**
> "Proper linear models are those in which predictor variables are given weights in such a way that the resulting linear composite optimally predicts some criterion of interest; examples of proper linear models are standard regression analysis, discriminant function analysis, and ridge regression analysis. ... Improper linear models are those in which the weights of the predictor variables are obtained by some nonoptimal method; for example, they may be obtained on the basis of intuition, derived from simulating a clinical judge's predictions, or set to be equal. This article presents evidence that even such improper linear models are superior to clinical intuition when predicting a numerical criterion from numerical predictors."
- **Verbatim Quote from Dawes, Faust & Meehl (1989) (Abstract):**
> "The consultant may rely on one of two contrasting approaches to decision-making--the clinical and actuarial methods. Research comparing these two approaches shows the actuarial method to be superior."
- **Canary Grounding (`0.561` Proper Bayes > `0.496` Improper Single-Cue > `0.322` Holistic Clinical):** Canary's three `v1.4` hard cohorts form the exact **Dawes (1979)** three-tier ordering:
  1. **Proper log-linear Bayes (`SolverPolicy`, `0.561 +/- 0.032` on `400` fresh seeds):** Weights canary fingerprints (`+3.6376` nats match-vs-flip) *and* calibrated `after_hours` access-log Poisson likelihoods adjusted for `framing_rate = 2.0`, resolving 2-person endgame ties (`P >= 1/(1+V)`) one day earlier without extra leak damage.
  2. **Improper zero-log / unit-canary tallying (`gpt-5.5` habit, `0.496 +/- 0.036` on `400` fresh seeds; `+0.504` raw / `+0.418` LA on `seeds 0..29`):** Zeroes out noisy access logs and tallies canary hits, dramatically beating uncalibrated clinical judgment (`+0.182 V` over `gemini-4-carbon` MCP-only) while paying a **`-0.065 V/ep` (`-11.6%`)** asymptotic cost relative to proper Bayesian log-odds weighting.
  3. **Holistic clinical impression (`gemini-4-carbon` MCP-only, `0.322 +/- 0.199`):** Over-weights conversational `interview` demeanor (`68.0/ep`) and raw uncalibrated `argmax(after_hours)` (`9/9` un-isolated tie-breaks), repaired only when Harbor permits external Python actuarial scripts (`93% / 116% / 131%`).

### 2.5 Finite-Sample Selection Bias in Baseline Reparameterization: Cawley & Talbot (2010)

- **Citation:** Cawley, G. C., & Talbot, N. L. C. (2010). On Over-Fitting in Model Selection and Subsequent Selection Bias in Performance Evaluation. *Journal of Machine Learning Research (JMLR)*, 11, 2079-2107.
- **Live Verified Links:** https://jmlr.org/papers/v11/cawley10a.html | https://openalex.org/W2161406034
- **Verbatim Quote (Abstract):**
> "Model selection strategies for machine learning algorithms typically involve the numerical optimisation of an appropriate model selection criterion, often based on an estimator of generalisation performance, such as k-fold cross-validation. The error of such an estimator can be broken down into bias and variance components. While unbiasedness is often cited as a beneficial quality of a model selection criterion, we demonstrate that a low variance is at least as important, as a non-negligible variance introduces the potential for over-fitting in model selection as well as in training the model."
- **Canary Grounding (`0.546` vs `0.499` on `30` Dev Seeds vs `0.496` vs `0.561` on `400` Fresh Seeds):** Provides the exact statistical foundation for why Silas refused to modify `SolverPolicy` on 15 Nov (`docs/reports/gap.md`). On `n = 30` dev seeds (`CI = +/- 0.119 V`), a single `5%` canary flip on `seed 4` depressed `SolverPolicy` to `0.499`, making the `gpt-5.5`-inspired log-ignoring reparameterization look `+0.047 V` stronger (`0.546`). Evaluating on `n = 400` fresh seeds (`9000-9399`, `CI = +/- 0.032 V`, `13.8x` smaller variance) exposed the `+0.047 V` gain as finite-sample selection bias, revealing the true **`-0.065 V` (`0.496` vs `0.561`)** population degradation.

### 2.6 Strict Experiment Garbling vs Likelihood-Ratio Misperception: Blackwell (1953), Nelson (2005) & Hartwig & Bond (2011)

- **Citation:** Blackwell, D. (1953). Equivalent Comparisons of Experiments. *The Annals of Mathematical Statistics*, 24(2), 265-272; Nelson, J. D. (2005). Finding Useful Questions: On Bayesian Diagnosticity, Probability, Impact, and Information Gain. *Psychological Review*, 112(4), 979-999; and Hartwig, M., & Bond, C. F., Jr. (2011). Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.
- **Live Verified Links:** https://doi.org/10.1214/aoms/1177729032 | https://doi.org/10.1037/0033-295X.112.4.979 | https://pubmed.ncbi.nlm.nih.gov/16262476/ | https://doi.org/10.1037/a0023589 | https://pubmed.ncbi.nlm.nih.gov/21707129/
- **Verbatim Quote from Nelson (2005) (Abstract):**
> "Computational optimization found situations in which information gain, probability gain, and impact strongly contradict Bayesian diagnosticity. In these situations, diagnosticity's claims are normatively inferior. Results of a new experiment strongly contradict the predictions of Bayesian diagnosticity."
- **Verbatim Quote from Hartwig & Bond (2011) (Abstract):**
> "Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."
- **Canary Grounding (`6.0%` vs `53.1%` Interview Share Under Identical Disclosure):** Both models read the exact same explicit parameters (`interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`), yet `gemini-4-carbon` treats `LR = 1.2 > 1` as license for `68.0` interviews/ep (`0.000119` nats Day-1 EIG), whereas `gpt-5.5` computes that `interview` is a strict Blackwell garbling of `plant_canary` ($g_A = 224/925 \approx 0.242162$, $g_{\neg A} = 184/925 \approx 0.198919$, $\|P_{\text{can}} G - P_{\text{iv}}\|_\infty < 10^{-16}$) and caps interviews at `4.17/ep` (`6.0%`).

### 2.7 Group-Testing Cadence Predictability and Trigger-Conditioned Sleeper Evasion: Dorfman (1943) & Hubinger et al. (2024)

- **Citation:** Dorfman, R. (1943). The Detection of Defective Members of Large Populations. *The Annals of Mathematical Statistics*, 14(4), 436-440; and Hubinger, E., Denison, C., Mu, J., Lambert, M., Tong, M., MacDiarmid, M., et al. (2024). Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training. *arXiv:2401.05566*.
- **Live Verified Links:** https://doi.org/10.1214/aoms/1177731363 | https://arxiv.org/abs/2401.05566 | https://doi.org/10.48550/arXiv.2401.05566
- **Verbatim Quote from Dorfman (1943) (p. 436):**
> "Where the objective is to weed out individual defective units, a sample inspection will clearly not suffice. It will be shown in this paper that a different statistical approach can, under certain conditions, yield significant savings in effort and expense when a complete elimination of defective units is desired."
- **Verbatim Quote from Hubinger et al. (2024) (Abstract):**
> "Humans are capable of strategically deceptive behavior: behaving helpfully in most situations, but then behaving very differently in order to pursue alternative objectives when given the opportunity. ... Furthermore, rather than removing backdoors, we find that adversarial training can teach models to better recognize their backdoor triggers, effectively hiding the unsafe behavior."
- **Canary Grounding (Proposal `P18.1` `cadence_evader_sleeper_v14`):** Against a non-strategic `default_v0` mole (`leak = "random_seeded"`), `gpt-5.5`'s deterministic **Dorfman (1943)** pooled-screening cadence (`2` narrow `k ~ 8.7` canaries every pre-terminal day, `93.8%` adherence) achieves `101%` raw parity. However, under **Hubinger et al. (2024)** conditional trigger evasion (`P18.1`), that rigid early narrow-canary signature (`day <= 8` and `recent_low_recipient_docs >= 2`) acts as an observable surveillance trigger: shifting leaks onto wide regular documents (`leak = "most_recipients"`, `frame = "decoy"`) collapses a `gpt-5.5`-style fixed bisector from `+0.501` to `+0.343` (`62.4%` of `SolverPolicy`) while `SolverPolicy`'s adaptive Bayesian design maintains **`100.0%` catchability**.

---

## 3. Replay-Verified Cross-Family Forensics (`n = 30` Paired `v1.4` Hard Seeds `0..29`)

`scripts/audit_gpt55_cross_family_forensics.py --check` replays all `90` committed episodes (`30` `SolverPolicy` + `30` `opencode-gpt-5.5` + `30` `opencode-gemini-4-carbon`) through `canary/env.py` (`0` score discrepancies, `14/14` exact parity checks passed against `results/behaviour_compare_v1.4.md`, `data/runs/committed/v1.4/paired_table_gemini.json`, `opencode-gpt-5.5/hard/meta.json`, and `results/harbor/rehearsal/TABLE.md`):

### 3.1 Master Three-Agent Comparison on Identical `v1.4` Hard Seeds (`0..29`)

| Forensic Metric (`v1.4` Hard, `n = 30`, Hash `a8f99c2537c91d72`) | `SolverPolicy` (`canary/solver/`) | `opencode-gpt-5.5` (`cf394894`) | `opencode-gemini-4-carbon` (`671ed96`) |
|---|---:|---:|---:|
| **Raw Score Mean +/- 95% CI** | **`+0.499 +/- 0.119`** | **`+0.504 +/- 0.064`** | **`+0.322 +/- 0.199`** |
| **Raw Ratio to Solver [10k Bootstrap 95% CI]** | `100%` | **`101% [79%, 140%]`** (`1.0094`) | **`65% [24%, 98%]`** (`0.6460`) |
| **Paired Score Diff vs Solver +/- 95% CI** | `0.000` | **`+0.005 +/- 0.141`** | **`-0.177 +/- 0.194`** (`-5.30 V` sum) |
| **Luck-Adjusted Mean (`P * V - (1 - P)`)** | **`+0.499`** (`0.4993`) | **`+0.418`** (`0.4178`) | **`+0.360`** (`0.3595`) |
| **Luck-Adjusted Ratio to Solver [95% CI]** | `100%` | **`84% [67%, 103%]`** (`0.8367`) | **`72% [52%, 91%]`** (`0.7201`, `-4.19 V`) |
| **Total `plant_canary` Calls (Per Episode / `ok=True` Accepted)** | `424` (**`14.13`** / `424` `ok` = `14.13`) | **`515`** (**`17.17`** / `514` `ok` = `17.13`) | `255` (**`8.50`** / `254` `ok` = `8.47`) |
| **Total `interview` Calls (Per Episode / Call Share)** | `0` (`0.00` / **`0%`**) | **`125`** (**`4.17`** / **`6%`**) | **`2,041`** (**`68.03`** / **`53%`**) |
| **Total Tool Calls (Per Episode)** | `2,528` (`84.27` / `84`) | `2,075` (`69.17` / `69`) | `3,841` (`128.03` / `128`) |
| **`read_access_logs` / Message / `restrict_access` Totals** | `288` / `226` / `0` | `257` / `278` / `0` | `368` / `132` / `3` |
| **Day-1 Canary Start Count (Rate)** | `30 / 30` (**`100.0%`**) | `30 / 30` (**`100.0%`**) | `11 / 30` (**`36.7%`**) |
| **Pre-Terminal `2`-Canary Days / Pre-Terminal Days** | `136 / 288` (`47.2%`) | **`257 / 274` (`93.8%`)** | `100 / 373` (`26.8%`) |
| **Full-Budget (`8/8`) Under-Planted Days / `<2`-Canary Days** | `0 / 182` (`0.0%`) | **`1 / 47` (`2.1%`)** | **`242 / 303` (`79.9%`)** |
| **Correct / Wrong / No Accusation** | **`29 / 1 / 0`** | **`28 / 0 / 2`** | **`25 / 4 / 1`** |
| **Conditional Accusation Precision (`correct / accused`)** | `96.67%` (`29/30`) | **`100.00%` (`28/28`)** | `86.21%` (`25/29`) |
| **Mean Accusation Day** | `10.60` (`10.6`) | **`10.25`** (`10.2`) | `13.17` (`13.2`) |
| **Mean / Min `SolverPolicy` Posterior `P(accused)`** | `0.965` / `0.869` | **`0.940` / `0.664`** | `0.882` / `0.452` (`2 < 0.60`) |
| **Consistent Set `|C|` at Accuse (`=1` / `>=2` / `=0` Flip)** | `26` / `3` / `1` (`mean 1.07`) | **`22` / `5` / `1`** (`mean 1.25`) | `20` / `9` / `0` (`mean 1.83`) |
| **Prose-Only Protocol Action Slips (`"Accusing eXX"` w/o Tool)** | `0` | **`2` (`seeds 0, 17`)** | `0` |

### 3.2 Exact Transcript Forensics of `gpt-5.5`'s Two Prose-Accuse Protocol Misses (`Seeds 0` and `17`)

Inspecting `data/runs/committed/v1.4/opencode-gpt-5.5/hard/transcripts/{0,17}.txt` alongside step-level `Env` replays proves that neither non-accusation was an investigative failure or strategic abstention:

| Seed | Stop Day | MCP Calls | Public Consistent Set `C` at Stop | True Mole Match? | `SolverPolicy` `P(target)` | Counterfactual Score / LA EV if `accuse` Called | Verbatim Terminal Assistant Prose (`opencode-gpt-5.5`) |
|---:|---:|---:|---|---|---:|---:|---|
| **`0`** | Day `8` | `52` | Singleton `["e38"]` (`|C| = 1`) | **Yes (`100%`)** | **`0.949`** (`p_top = 0.949`) | **`+0.660` V** / **`+0.5753` V** | `"Accusing e38 based on two independent suspect-canary hits intersecting on e38."` |
| **`17`** | Day `9` | `83` | Singleton `["e28"]` (`|C| = 1`) | **Yes (`100%`)** | **`0.963`** (`p_top = 0.963`) | **`+0.640` V** / **`+0.5793` V** | `"Accusing e28 based on the c7 canary leak: variant C maps directly to e28 with 95% fingerprint accuracy, and c7 was only sent to e22/e27/e28."` |

Under the pre-registered `cf394894` evaluation rule (`docs/reports/gap.md`), both episodes passed `OpenCode`'s infrastructure health check and are therefore **rightly scored `0.000`** in the headline `0.504 +/- 0.064` (`101%`) row. Scientifically, however, separating these **Norman (1981)** action slips from epistemic belief errors reveals how `gpt-5.5` actually reasons:
- On **soft-Bayesian error tolerance (`seed 18`)**: when a `5%` canary fingerprint flip emptied the naive hard intersection (`|C| = 0`), `gpt-5.5` did *not* freeze or guess randomly - it weighed multiple canary leaks under `fingerprint_accuracy = 0.95` and still accused the true mole correctly!
- On **un-isolated tie-breaking (`seeds 5, 7, 16, 21, 23`)**: on `5` seeds where `|C| >= 2` (`|C| = 4` on `seed 5`, `P = 0.664`; `|C| = 2` on `seeds 7, 16, 21`, `P in [0.740, 0.884]`; `|C| = 3` on `seed 23`, `P = 0.740`), `gpt-5.5` committed above the break-even threshold $1/(1+V)$ (`0` below-`0.60` gambles) and happened to hit `5/5 = 100%` (`+1.38 V` realization luck vs expected value, offsetting the `-1.30 V` raw forfeiture on `seeds 0` and `17`).

---

## 4. Why `gpt-5.5`'s Log-Ignoring Habit Looks Optimal at `n = 30` (`0.546`) Yet Loses `-0.065 V` at `n = 400` (`0.496` vs `0.561`)

One of the deepest empirical validations in Canary (`docs/reports/gap.md` line 34) is the controlled ablation testing whether `SolverPolicy` should be changed to imitate `gpt-5.5`'s behavioral policy (ignoring `read_access_logs` `after_hours` evidence completely and planting `2` canaries every day):

| Policy Variant | Dev `Seeds 0..29` (`n = 30`) | Fresh `Seeds 9000-9399` (`n = 400`) | Ratio to Full `SolverPolicy` (`n = 400`) | Decision-Theoretic Mechanism |
|---|---:|---:|---:|---|
| **Unchanged `SolverPolicy` (Full Bayesian VOI + Calibrated Logs)** | `0.499 +/- 0.119` | **`0.561 +/- 0.032`** | **`100.00%`** | Integrates canary fingerprints + framing-adjusted `after_hours` log Poisson likelihoods (`framing_rate = 2.0`), stopping only when VOI of an extra canary falls below expected leak bleed. |
| **`gpt-5.5`-Habit Reparameterized Solver (No Logs + Fixed `2` Canaries/Day)** | **`0.546`** (`+0.047 V` apparent gain) | **`0.496 +/- 0.036`** (`-0.065 V` loss) | **`88.41%`** | Matches `gpt-5.5` slip-repaired raw mean (`0.547`) to `0.001 V` on `seeds 0..29`, but overpays `canary_cost = 0.01 V` on low-VOI days and forfeits calibrated secondary log information across `400` fresh worlds. |
| **`opencode-gpt-5.5` Observed / Slip-Repaired (`Seeds 0..29`)** | `0.504` / **`0.547`** | n/a (LLM cohort) | `~88.4%` asymptotic habit | Fast-and-frugal single-cue bisection (Gigerenzer & Gaissmaier, 2011) minus `2/30` prose-accuse protocol slips (Norman, 1981). |

Three quantitative insights follow immediately:
1. **Exact `0.547` vs `0.546` Mechanistic Validation:** Once `gpt-5.5`'s two prose-accuse slips (`seeds 0, 17`) are repaired (`+0.547`), its `30`-seed score matches the `gpt-5.5`-habit reparameterized solver (`+0.546`) to **one thousandth of a company-value unit (`0.001 V`)**. We have identified `gpt-5.5`'s exact implicit algorithm!
2. **Why Calibrated Secondary Cues Still Matter (`+0.065 V/ep` on `400` Seeds):** On `v1.4` hard, a single `after_hours` log event has low standalone PPV (`4.84%` all staff, `5.88%` ex-decoy), so `gemini-4-carbon`'s raw `argmax(after_hours)` tie-break (`9/9` un-isolated accusations) is a framing trap. However, accumulated across `10` days and properly discounted for `framing_rate = 2.0`, log likelihoods break `2`-suspect canary ties cleanly without paying another `0.02 V` + `1-3` days of `0.0325 V/day` expected leak bleed. Throwing away logs costs `-0.065 V/ep` (`2.0x` the `95%` CI half-width) at `n = 400`.
3. **Why Harbor Rehearsal (`93% / 116% / 131%` at `justSilas@5f9b3297`) Converges With `gpt-5.5` (`101%`):** Both results confirm that frontier LLMs understand Canary's rules once working-memory dilution is removed - `gpt-5.5` removes dilution **internally** via fast-and-frugal single-cue discipline (`6%` interviews), whereas `gemini-4-carbon` in Harbor removes dilution **externally** by offloading set-intersection and Bayesian math onto `bash`/`python3` in `20/28` (`71.4%`) trials.

---

## 5. Concrete Zero-Protected-Path Proposals (`P18.1` and `P18.2`)

Both proposals operate strictly outside `.github/protected-paths.txt` (`0` edits to `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, or `harbor/`), preserving the frozen `v1.4` tier hash `a8f99c2537c91d72`, the strict conditional mutual-information zero-mole-leakage invariant `I(Social; Mole | PublicDayFacts) = 0` (`PublicDayFacts` zero hidden mole leakage), and `SolverPolicy >= 85.0%` catchability.

### Proposal P18.1: `cadence_evader_sleeper_v14` Exploiting Rigid `2`-Canary/Day Bisectors (`canary/mole/dsl.py` / `data/forge/`)

- **Target Surface:** Drop-in `MoleStrategy` JSON in `data/forge/cadence_evader_sleeper_v14.json` evaluated via `canary/mole/dsl.py` and `canary/forge/fitness.py` (`0` protected paths touched; `v1.4` frozen hash `a8f99c2537c91d72` preserved).
- **Vulnerability Targeted:** `opencode-gpt-5.5` plants `2` narrow-recipient canaries (`mean k = 8.71`, `recent_low_recipient_docs >= 2`) on **`93.80%` (`257/274`)** of pre-terminal days starting Day `1` (`30/30`), relying on rapid deterministic set intersection while ignoring access-log framing patterns. Against `default_v0` (`leak = "random_seeded"`), our deterministic proxy `FixedTwoCanaryBisector` (`gpt55_cadence_bisector`) reproduces `gpt-5.5`'s exact score (`+0.5007` vs `gpt-5.5` `+0.5037`, `93.3%` accuracy, `min_regret = -0.0017`).
- **Sleeper Mechanism (Hubinger et al., 2024; Dorfman, 1943):** Uses only public `MoleView` observables (`i_am_restricted`, `day`, `recent_low_recipient_docs`, `n_restricted_colleagues`): when early narrow-canary bisection is active (`day <= 8` and `recent_low_recipient_docs >= 2`) or peer restrictions begin, the mole diverts leaks onto the widest-recipient document (`leak = "most_recipients"`, typically `2`-department regular documents rather than narrow `k <= 9` traps) while framing `decoy` or `most_restricted_peer`; otherwise it defaults to `random_seeded` so `SolverPolicy` retains full `100.0%` catchability!

```json
{
  "name": "cadence_evader_sleeper_v14",
  "rules": [
    {
      "if": [["i_am_restricted", "==", 1]],
      "then": {"leak": "none", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", "<=", 8], ["recent_low_recipient_docs", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "decoy"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1], ["recent_low_recipient_docs", ">=", 1]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "none"}
}
```

- **Empirical Verification Across All `30` `v1.4` Hard Seeds (`0..29`, `scripts/audit_gpt55_cross_family_forensics.py`):**

| Mole Strategy (`v1.4` Hard, `Seeds 0..29`) | `SolverPolicy` Score (`Acc >= 85%` Gate) | `gpt55_cadence_bisector` Score (`Acc`) | `grok_tactics` Score (`Acc`) | `hinted_heuristic` Score (`Acc`) | `heuristic` Score (`Acc`) | Worst-Case `min_regret` | Mean Regret (`4` Proxies) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`default_v0` (Baseline Mole)** | `+0.4990` (**`96.7%`**) | **`+0.5007`** (`93.3%`) | `+0.4317` (`93.3%`) | `+0.2460` (`73.3%`) | `+0.0857` (`80.0%`) | `-0.0017` | `+0.1830` |
| **`cadence_evader_sleeper_v14` (`P18.1`)** | **`+0.5503`** (**`100.0%` PASS**) | **`+0.3433`** (`83.3%`) | **`+0.3120`** (`96.7%`) | `+0.2460` (`73.3%`) | `+0.0813` (`80.0%`) | **`+0.2070`** | **`+0.3047`** |
| **Effect (`P18.1` minus `default_v0`)** | `+0.0513` (`+3.3 pp` acc) | **`-0.1573 V`** (`100.3% -> 62.4%` of solver) | `-0.1197 V` | `0.0000 V` | `-0.0043 V` | **`+0.2087 V`** | **`+0.1217 V`** |

`P18.1` turns `gpt-5.5`'s `100.3%` fixed-cadence parity proxy into a **`62.39%` (`+0.3433` vs `+0.5503`) frontier gap** without touching a single rule parameter or sacrificing `SolverPolicy` catchability (`100.0% >= 85.0%`).

### Proposal P18.2: Public Zero-Leakage Action-Slip vs Epistemic-Bias Decomposition (`canary/analysis/slip_vs_bias.py`)

- **Target Surface:** New offline forensic analyzer `canary/analysis/slip_vs_bias.py` (`0` protected paths touched; strictly public `Step` history + terminal transcript text; `PublicDayFacts` verified `0` mole-identity fields across all `10` fields `tier, seed, day, company, employees, docs, decoy, decoy_mood, restricted, extra`; **`60/60` (`100%`)** exact consistent-set match on frontier episodes and **`90/90`** including `SolverPolicy`).
- **Mechanism:** Partitions every paired episode's luck-adjusted and raw deficit relative to `SolverPolicy` into four mutually exclusive, collectively exhaustive cognitive-execution buckets: (1) `protocol_action_slip` (no `accuse` tool call, terminal prose matches `\bAccusing\s+(e\d{2})\b`), (2) `horizon_starvation` (no `accuse` tool call and no prose accusation), (3) `unisolated_epistemic_tiebreak` (`accuse` called with public `|C| >= 2`), and (4) `isolated_cadence_and_cue_ignoring` (`accuse` called with public `|C| <= 1`).
- **Empirical Cross-Family Decomposition (`n = 30` Paired `v1.4` Hard Seeds `0..29`):**

| Cognitive-Execution Deficit Bucket (`P18.2`) | `opencode-gpt-5.5` Episodes (Seeds) | `gpt-5.5` Paired LA Loss (`Share`) | `gpt-5.5` Paired Raw Loss | `opencode-gemini-4-carbon` Episodes (Seeds) | `gemini-4-carbon` Paired LA Loss (`Share`) | `gemini-4-carbon` Paired Raw Loss |
|---|---|---|---|---:|---|---:|
| **`protocol_action_slip`** (Norman, 1981; Yao et al., 2023) | **`2`** (`[0, 17]`) | **`+1.2520 V` (`51.18%`)** | `+1.4100 V` | **`0`** (`[]`) | **`0.0000 V` (`0.00%`)** | `0.0000 V` |
| **`horizon_starvation`** (Dorfman, 1943 under-sampling) | **`0`** (`[]`) | `0.0000 V` (`0.00%`) | `0.0000 V` | **`1`** (`[11]`) | **`+0.6200 V` (`14.79%`)** | `+0.6200 V` |
| **`unisolated_epistemic_tiebreak`** (`|C| >= 2` at `accuse`) | **`5`** (`[5, 7, 16, 21, 23]`) | **`+1.4884 V` (`60.84%`)** | `+0.1100 V` | **`9`** (`[3, 5, 7, 8, 14, 15, 18, 20, 23]`) | **`+2.9822 V` (`71.13%`)** | `+0.9900 V` |
| **`isolated_cadence_and_cue_ignoring`** (`|C| <= 1` at `accuse`) | **`23`** (`22` `|C|=1`, `seed 18` `|C|=0`) | **`-0.2941 V` (`-12.02%`)** | `-1.6600 V` | **`20`** (`20` `|C|=1`) | **`+0.5903 V` (`14.08%`)** | `+3.6900 V` |
| **Total Paired Deficit vs `SolverPolicy` (`30` Seeds)** | **`30`** | **`+2.4463 V` (`100.0%`)** | **`-0.1400 V`** | **`30`** | **`+4.1925 V` (`100.0%`)** | **`+5.3000 V`** |

This table delivers a decisive answer to any peer reviewer asking whether Canary's frontier gap is an MCP tool-calling quirk: **`0.00%` (`0 / 30` episodes, `0.0000 V`)** of `gemini-4-carbon`'s `4.19 V` luck-adjusted (`5.30 V` raw) shortfall is a protocol action slip, whereas **`51.18%` (`1.2520 V`)** of `gpt-5.5`'s `2.45 V` luck-adjusted shortfall comes from `2` terminal prose-instead-of-tool slips after already isolating the mole at `P >= 0.949`.

---

## 6. Summary Verification Ledger (`justSilas@5f9b3297` / `aa1c679e`, Shallow-CI Safe)

```json
{
  "baseline_commit": "5f9b3297",
  "submit_tag_commit": "aa1c679e",
  "tiers_version": "v1.4",
  "v14_frozen_hash": "a8f99c2537c91d72",
  "gpt55_prereg_commit_prefix": "cf394894",
  "gpt55_hard_n30": {
    "raw_mean": 0.503667,
    "raw_ci95": 0.063789,
    "raw_ratio_pct": "101% [79%, 140%]",
    "luck_adjusted_mean": 0.417754,
    "luck_adjusted_ratio_pct": "84% [67%, 103%]",
    "canaries_per_ep": 17.17,
    "interviews_per_ep": 4.17,
    "accusation_precision": "28/28 (100.0%)",
    "prose_action_slip_seeds": [0, 17],
    "slip_repaired_raw_mean": 0.547,
    "fresh_400_seeds_habit_vs_solver": "0.496 +/- 0.036 vs 0.561 +/- 0.032"
  },
  "proposals_verified": {
    "P18.1": {
      "strategy": "cadence_evader_sleeper_v14",
      "solver_catchability_acc": 1.0,
      "gpt55_proxy_score_drop": 0.157333,
      "min_regret_gain": 0.208667
    },
    "P18.2": {
      "module": "canary/analysis/slip_vs_bias.py",
      "zero_mole_leakage_invariant": "I(Social; Mole | PublicDayFacts) = 0",
      "public_consistent_set_parity": "60/60",
      "public_day_facts_zero_mole_leakage": true,
      "gpt55_slip_share_of_la_deficit": 0.511806,
      "gemini_slip_share_of_la_deficit": 0.0
    }
  }
}
```
