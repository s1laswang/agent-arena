# 20. Judge Peer-Review Q&A and Research Proposal Scorecard (`justSilas@5f9b3297` / `aa1c679e`)

**Squad:** `research` (`canary-research-w8`)  
**Baseline:** `origin/justSilas@5f9b3297` (`afterquery-submit-2` `aa1c679e`, code-freeze tag `afterquery-final` `1bc3e281`, rules `v1.4`, frozen hash `a8f99c2537c91d72`)  
**Executable Audit Harness:** `scripts/audit_research_scorecard.py` and `tests/test_audit_research_scorecard.py` (`0` API calls, deterministic CPU, `0` protected paths touched)  
**Companion Synthesis & Monographs:** [Master Deception Synthesis](../research-deception.md) | [01. Deception Detection](01_deception_detection.md) | [02. Insider Threat](02_insider_threat.md) | [03. Leak Hunts & Group Testing](03_leak_hunts_canary_traps_group_testing.md) | [04. Social Engineering & Cheap Talk](04_social_engineering_cheap_talk.md) | [06. Organisational Bias & Sleeper Port](06_organisational_bias_and_sleeper_port.md) | [07. Human-Bias Social Layer](07_v15_bias_layer_proposals.md) | [08. Stackelberg Games & Constrained Mole RL](08_mole_rl_stackelberg_and_catchability.md) | [10. Proposal Simulations & Zero-Leakage Proofs](10_proposal_simulations_and_zero_leakage_proofs.md) | [11. Empirical Transcript Bias Forensics](11_empirical_transcript_bias_forensics.md) | [13. Blackwell Channel Capacity & Lindley EIG](13_blackwell_channel_capacity_and_eig.md) | [14. Sleeper Mole Catalog & Tournament](14_sleeper_mole_catalog_and_head_to_head.md) | [17. Red-Team Swarms & Reward Integrity](17_redteam_reward_gaming_and_benchmark_integrity.md)  
**Primary Committed Artifacts:** [README](../../README.md) | [Submission Write-Up](../SUBMISSION.md) | [Gap Report](../reports/gap.md) | [CEO Log](../reports/CEO.md) | [Cross-Family Behaviour](../../results/behaviour_compare_v1.4.md) | [Harbor Judge Rehearsal](../../results/harbor/rehearsal/TABLE.md) | [Failure Analysis v1.4](../reports/failure_analysis_v1.4.md) | [Reference Optimality](../reports/reference_optimality.md) | [Exploit Ledger](../EXPLOITS.md) | [1,034-Attack Red-Team Summary](../../results/redteam_1000/summary.md)

---

## 1. Executive Judge Briefing: Six Peer-Review Verdicts at `justSilas@5f9b3297` (`aa1c679e`)

This monograph provides a concise, peer-review-ready Q&A and unified Proposal Scorecard for AfterQuery "Break the Agent" judges evaluating Canary on `justSilas@5f9b3297` (`afterquery-submit-2` `aa1c679e`, `TIERS_VERSION = "v1.4"`, frozen hash `a8f99c2537c91d72`). Every quantitative claim is verified directly from committed repo files by `scripts/audit_research_scorecard.py` in `< 0.5 s` with `0` API calls, and every behavioral or methodological claim is anchored to live HTTP-verified peer-reviewed literature.

| Q# | Core Peer-Review Question | Repo-Verified Verdict (`justSilas@5f9b3297` / `aa1c679e`) | Primary Literature Anchor | Mapped Proposals |
|---|---|---|---|---|
| **Q1** | Is the `65% [24%, 98%]` raw / `72% [52%, 91%]` luck-adjusted `gemini-4-carbon` gap (`n = 30`) statistically honest, and do infra retries or extensions change it? | **Yes, with full CIs disclosed:** OpenCode `gemini-4-carbon` over MCP (`13` tools only) scores `0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119` (raw paired gap `5.30 V`, diff `-0.177 +/- 0.194` touches `0`; luck-adjusted gap `4.19 V`, `0.360` vs `0.499`, `72% [52%, 91%]` excludes `100%`). Scoring `6` empty-reply retries among `25` infra failures as `0` widens the gap to `56% [19%, 87%]` raw / `55% [34%, 77%]` LA; pooled `n = 32` is `68% [32%, 100%]` raw / `75% [56%, 93%]` LA. | Dawes, Faust & Meehl (1989); Strathern (1997) | `P11.2`, `P20.1`, `P20.2` |
| **Q2** | Why did the `65%` MCP-only gap NOT reproduce in the Harbor judge-path rehearsal (`93% / 116% / 131%`) or in OpenCode `gpt-5.5` (`101% [79%, 140%]`)? | **Cognitive vs tool-augmented execution:** On tag `afterquery-final` (`1bc3e281`), Harbor grants isolated `bash`/`python3` (`11/11` sidecar checks); `gemini-4-carbon` offloaded posterior math to shell scripts in `20/28` (`71.4%`) trials and scored `+0.472` (`93%`, `n=10`), `+0.585` (`116%`, `n=10`), and final Run 3 **`+0.626` (`131%`, `9` valid trials, `5` after `08:30`, `1` infra-excluded; `28/29 = 96.6%` correct)** vs oracle `+0.506` (`+0.4778` on Run 3's `9` tasks). Under MCP-only, `gpt-5.5` plants `17.2` canaries vs `4.2` interviews (`6%` of calls) and scores `+0.504 +/- 0.064` (`101%` raw, `84%` LA, `28/28` accused correct, `2` prose-only non-accusations). | Dawes, Faust & Meehl (1989); Risko & Gilbert (2016) | `P20.2`, `P7.1`, `P14.1` |
| **Q3** | Does `gemini-4-carbon`'s MCP-only shortfall reflect rule confusion or hidden tricks rather than genuine decision difficulty? | **Zero hidden rules, exact `5.30 V` identity:** All `34/34` `TierParams` fields are printed in `Env.instruction()`; `careful_mole_check.py` proves `0` `W1` losses (`0.26` vs `0.24` staff share; `28/3,841 = 0.7%` invalid calls). `plant_canary` (`0.86544` nats MI) dominates `interview` (`interview_lr = 1.2`, `0.00477` nats, `181.4x`), yet `gemini-4-carbon` runs `68.0` interviews/ep, exhausting all `8` daily actions on `242` of `303` under-planted days (`8.5` vs `14.1` canaries) and committing un-isolated on `9/29` episodes (`+3.39 + 0.62 + 1.75 + 0.12 - 1.69 = 4.19 V` skill `+ 1.11 V` luck `= 5.30 V`, `0.0e+00` residual). | Hartwig & Bond (2011) | `P1.1`, `P1.2`, `P1.3`, `P2.1`, `P13.1` |
| **Q4** | Why did `v1.5-candidate` biased staff invert (`61% -> 108%`) and `14` vanilla GRPO mole runs collapse, and how do `v1.6` proposals fix both? | **Mathematical invariants restored:** `v1.5-candidate` sampled `40%` of rumours from `ids \ {mole}` (`LLR = -0.52103` nats) and disclosed mole seeding, creating an exclusion oracle (`61% -> 108%` at Gate B). `v1.6` enforces babbling-equilibrium independence `I(Social; Mole \| PublicDayFacts) = 0` (`LLR = 0.0000` nats). For the mole (`MoleStrategy`), primal-dual catchability constraints (`>= 85%` `SolverPolicy` accuracy) lift `RLMole` v1 (`75.0%`) to `96.7%`/`95.0%` (`RLMoleV2`), `97.5%`/`95.0%` (`Qwen3-1.7B` V100), and `+0.2989` saddle-point regret (`4`-mole sleeper catalog). | Crawford & Sobel (1982); Tessler et al. (2019) | `P7.1`, `P4.1`, `P5.1`, `P8.1`, `P8.2`, `P14.1`, `P14.2` |
| **Q5** | Can an attacker exploit the scoring rule, regenerate judge seeds, scrape `/proc`, forge Harbor ledgers, or game a small-seed check? | **All blocked across `1,034` Gemini attacks + `3,960`-run battery:** `wrong_accusation_score = -1.0` sets Day-1 uniform EV to `-0.9500` on hard (`do_nothing = stop_early = cheat_probe = 0.000`); `256`-bit fail-closed world secrets (`#24`), `0600` consumed secret files + sidecar isolation (`#27`, `31/31` `ISOLATION OK`), and `HMAC-SHA256` signed ledgers (`c1-tamper -> 0`) hold. `1,034` ledgered attacks (`521` on `1bc3e281db`) found `0` exploits while catching `16/16` (`100%`) positive controls; `40`-seed hard random `P(mean > 0) = 1.89e-23 < 1e-9`; `1,051/1,051` replays match across `53,889` steps. | Strathern (1997) | `P17.1`, `P17.2` |
| **Q6** | Did fine-tuning `Qwen2.5-1.5B-Instruct` exceed the untrained `0.000` base on held-out seeds, and why did DAgger also return a null? | **Honest null (`0/7` trained runs above `0.000` base):** `base` scores `0.000` (`n = 36`, `3%` valid calls) by abstaining; `v2` SFT drops to `-0.457 +/- 0.086` (`n = 172`) via covariate shift (`55%` reckless accusations); `v3-4k` GRPO recovers `+0.310 +/- 0.107` to `-0.147 +/- 0.063` (`n = 180`, `100%` valid calls, `0.19 -> 0.89` train-state mole ID; `v3-8k` best `-0.050 +/- 0.049`, `n = 90`); DAgger Round 1 at `8k` context scores `-0.542 +/- 0.214` (`n = 50` partial) because sliding windows evict early `plant_canary` variant assignments. | Ross, Gordon & Bagnell (2011) | `P3.2`, `P20.1` |

---

## 2. Primary Literature Grounding (Live HTTP-Verified Links and Verbatim Quotes)

### 2.1 Clinical vs Actuarial Evidence Combination: Dawes, Faust & Meehl (1989)

- **Citation:** Dawes, R. M., Faust, D., & Meehl, P. E. (1989). Clinical Versus Actuarial Judgment. *Science*, 243(4899), 1668-1674 (building on Meehl, 1954, and operationalized in modern probabilistic forecasting by Tetlock & Gardner, 2015).
- **Live Verified Links:** https://doi.org/10.1126/science.2648573 | https://pubmed.ncbi.nlm.nih.gov/2648573/ | https://openalex.org/W2012218966
- **Verbatim Quote (Abstract):**
> "The consultant may rely on one of two contrasting approaches to decision-making--the clinical and actuarial methods. Research comparing these two approaches shows the actuarial method to be superior. Factors underlying the greater accuracy of actuarial methods, sources of resistance to the scientific findings, and the benefits of increased reliance on actuarial approaches are discussed."
- **Canary Peer-Review Grounding (`Q1`, `Q2`, `P20.2`):** Directly explains both why `SolverPolicy` (explicit actuarial log-likelihood integration over `PublicDayFacts`) outperforms unassisted holistic transcript judgment in `gemini-4-carbon` MCP-only runs (`0.322` vs `0.499`), and why `gemini-4-carbon` jumps to `93% / 116% / 131%` in Harbor once it writes an actuarial Python filter in `bash`/`python3`.

### 2.2 Metacognitive Demand Reduction via External Tools: Risko & Gilbert (2016)

- **Citation:** Risko, E. F., & Gilbert, S. J. (2016). Cognitive Offloading. *Trends in Cognitive Sciences*, 20(9), 676-688.
- **Live Verified Links:** https://doi.org/10.1016/j.tics.2016.07.002 | https://pubmed.ncbi.nlm.nih.gov/27542527/ | https://openalex.org/W4243906228
- **Verbatim Quote (Abstract):**
> "If you have ever tilted your head to perceive a rotated image, or programmed a smartphone to remind you of an upcoming appointment, you have engaged in cognitive offloading: the use of physical action to alter the information processing requirements of a task so as to reduce cognitive demand."
- **Canary Peer-Review Grounding (`Q2`, `P20.2`):** Grounds the `48.70 pp` raw ratio shift between `gemini-4-carbon` MCP-only (`64.60%`, shell denied) and Harbor judge-path (`113.30%` 3-run mean across `93.3% / 115.6% / 131.0%`, where the agent invoked `bash`/`python3` in `20/28 = 71.4%` of inspected trials to offload set-intersection and delayed-leak bookkeeping), motivating Proposal **`P20.2`**'s separation of intrinsic MCP cognition from tool-augmented offloading.

### 2.3 Weak Demeanor Cues Persist Despite Explicit Cue-Weight Disclosure: Hartwig & Bond (2011)

- **Citation:** Hartwig, M., & Bond, C. F., Jr. (2011). Why Do Lie-Catchers Fail? A Lens Model Meta-Analysis of Human Lie Judgments. *Psychological Bulletin*, 137(4), 643-659.
- **Live Verified Links:** https://pubmed.ncbi.nlm.nih.gov/21707129/ | https://doi.org/10.1037/a0023589
- **Verbatim Quote (Abstract):**
> "In conclusion, contrary to previous assumptions, people rarely rely on the wrong cues. Instead, limitations in lie detection accuracy are mainly attributable to weaknesses in behavioral cues to deception. The results suggest that intuitive notions about deception are more accurate than explicit knowledge and that lie detection is more readily improved by increasing behavioral differences between liars and truth tellers than by informing lie-catchers of valid cues to deception."
- **Canary Peer-Review Grounding (`Q3`, `P1.1`, `P1.3`):** Refutes the objection that `gemini-4-carbon` fails from hidden parameters: `Env.instruction()` prints `interview_lr = 1.2` (`p_evasive_innocent = 0.2`, `KL = 0.00477` nats) alongside `fingerprint_accuracy = 0.95` (`0.86544` nats conditional MI, `181.4x` stronger), yet `gemini-4-carbon` still spends `68.0` interviews/episode (`53%` of calls) vs `gpt-5.5`'s `4.2` (`6%`) and `SolverPolicy`'s `0.0`.

### 2.4 Babbling Equilibria in Strategic Cheap Talk: Crawford & Sobel (1982)

- **Citation:** Crawford, V. P., & Sobel, J. (1982). Strategic Information Transmission. *Econometrica*, 50(6), 1431-1451.
- **Live Verified Links:** https://api.openalex.org/works/W2160003140 | https://doi.org/10.2307/1913390
- **Verbatim Quote:**
> "Since R bases his choice of action on rational expectations, this establishes a sense in which equilibrium signaling is more informative when agents' preferences are more similar."
- **Canary Peer-Review Grounding (`Q4`, `P7.1`, `P4.1`):** Proves mathematically why unverified workplace chatter must satisfy exact babbling-equilibrium conditional independence $I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$ (`LLR = 0.0000` nats), diagnosing why `v1.5-candidate` (`LLR = -0.52103` nats) inverted at Gate B (`61% -> 108%`).

### 2.5 Goodhart's Law and Audit-Resistant Evaluation Design: Strathern (1997)

- **Citation:** Strathern, M. (1997). 'Improving ratings': audit in the British University system. *European Review*, 5(3), 305-321.
- **Live Verified Links:** https://doi.org/10.1017/S1062798700002660 | https://api.crossref.org/works/10.1017/S1062798700002660 | https://openalex.org/W2129286663
- **Verbatim Quote (p. 308 and Abstract):**
> "When a measure becomes a target, it ceases to be a good measure."
> "The runaway character of assessment practices is analysed in terms of cultural practice. Higher education is intimately bound up with the origins of such practices, and is not just the latter day target of them."
- **Canary Peer-Review Grounding (`Q1`, `Q5`, `P17.1`, `P20.2`):** Grounds Canary's discipline against metric gaming by both evaluated agents (`wrong_accusation_score = -1.0`, `HMAC-SHA256` server-side ledgers, `40`-seed judge batteries, `1,034` red-team attacks) and benchmark authors (post-hoc lock disclosure `671ed96`, refusal to swap in cherry-picked runs or failed `v1.5` / `solver_v2` / `expert` ablations, and final Run 3 `131%` correction in `aa1c679e` / `5f9b3297`).

### 2.6 Imitation Covariate Shift and Interactive Online Reductions (DAgger): Ross, Gordon & Bagnell (2011)

- **Citation:** Ross, S., Gordon, G. J., & Bagnell, D. (2011). A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning. *Proceedings of the Fourteenth International Conference on Artificial Intelligence and Statistics (AISTATS 2011)*, PMLR 15:627-635.
- **Live Verified Links:** https://proceedings.mlr.press/v15/ross11a.html | https://arxiv.org/abs/1011.0686
- **Verbatim Quote (Abstract):**
> "Sequential prediction problems such as imitation learning, where future observations depend on previous predictions (actions), violate the common i.i.d. assumptions made in statistical learning. This leads to poor performance in theory and often in practice."
> "In this paper, we propose a new iterative algorithm, which trains a stationary deterministic policy, that can be seen as a no regret algorithm in an online learning setting."
- **Canary Peer-Review Grounding (`Q6`, `P3.2`):** Explains the exact small-model `Qwen2.5-1.5B` tiebreaker trajectory: offline SFT (`v2`: `-0.457 +/- 0.086`) suffers $O(T^2 \epsilon)$ covariate shift once its canary partitions diverge from `SolverPolicy`; on-policy GRPO (`v3-4k`: `-0.147 +/- 0.063`; `v3-8k`: `-0.050 +/- 0.049`) repairs reckless accusations (`+0.310 +/- 0.107`); and raw-transcript DAgger (`-0.542 +/- 0.214` at `8k` context, `n = 50` partial) demonstrates that online teacher relabeling still requires a compact Markovian belief summary when sliding windows truncate Day 1-5 canary variant assignments.

### 2.7 Reward Constrained Policy Optimization for Feasible Adversaries: Tessler, Mankowitz & Mannor (2019)

- **Citation:** Tessler, C., Mankowitz, D. J., & Mannor, S. (2019). Reward Constrained Policy Optimization. *International Conference on Learning Representations (ICLR 2019)* (`arXiv:1805.11074`).
- **Live Verified Links:** https://openalex.org/W2804791273 | https://arxiv.org/abs/1805.11074 | https://doi.org/10.48550/arXiv.1805.11074
- **Verbatim Quote (Abstract):**
> "As the goal of the agent is to maximize the accumulated reward, it often learns to exploit loopholes and misspecifications in the reward signal resulting in unwanted behavior. While constraints may solve this issue, there is no closed form solution for general constraints. In this work we present a novel multi-timescale approach for constrained policy optimization, called 'Reward Constrained Policy Optimization' (RCPO), which uses an alternative penalty signal to guide the policy towards a constraint satisfying one."
- **Canary Peer-Review Grounding (`Q4`, `P5.1`, `P8.1`, `P14.1`):** Explains why unconstrained mole RL exploits stonewalling loopholes (`RLMole` v1 `18.2%` `leak = "none"` drops `SolverPolicy` accuracy to `75.0% < 85.0%`, and `14` vanilla GRPO runs collapse `>= 99.4%`), whereas primal-dual catchability enforcement (`SolverPolicy >= 85%`) produces feasible sleepers (`RLMoleV2` `96.7%`/`95.0%`, V100 `Qwen3-1.7B` `97.5%`/`95.0%`, and the `4`-mole `v1.4` sleeper catalog `93.3%-100.0%`).

---

## 3. Detailed Answers to the Six Core Peer-Review Questions (`justSilas@5f9b3297` / `aa1c679e`)

### Q1. Statistical Significance, Post-Hoc Seed Lock, and Infra-Retry Sensitivity

**Reviewer Question:** *On `v1.4` hard (`n = 30`), OpenCode `gemini-4-carbon` scores `0.322 +/- 0.199` vs `SolverPolicy` `0.499 +/- 0.119`. Since the raw paired difference (`-0.177 +/- 0.194`) touches zero and `meta.json` excludes `25` infra attempts, is the `65% [24%, 98%]` / `72% [52%, 91%]` gap robust or an artifact of seed selection and retries?*

**Repo-Verified Answer (`data/runs/committed/v1.4/paired_table_gemini.json`, `opencode-gemini-4-carbon/hard/meta.json`):**
1. **Why luck-adjusted `72% [52%, 91%]` resolves binary `-1` variance while raw `65% [24%, 98%]` is reported first:** On `v1.4` hard (`n_employees = 40`, `n_days = 21`, `p_leak = 0.65`, `leak_damage = 0.05`, `canary_cost = 0.01`, `canaries_per_day = 2`, `max_variants = 3`, `restrict_cost_per_day = 0.01`, `actions_per_day = 8`, `tool_call_cap = 420`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`, `fingerprint_accuracy = 0.95`, `framing_rate = 2.0`), frozen hash `a8f99c2537c91d72`, one `5%` canary fingerprint flip swings a single episode by `~1.6 V` (`+0.6 V` to `-1.0`). Both 10,000-resample paired bootstrap ratio CIs exclude `100%` (`65% [24%, 98%]` raw; `72% [52%, 91%]` luck-adjusted, scoring each accusation by `P * V - (1 - P)` under `SolverPolicy`'s calibrated posterior, verified at `95.6%-98.6%` empirical accusation accuracy across `400` seeds in `docs/reports/reference_optimality.md`), while the raw paired difference `-0.177 +/- 0.194` (`[-0.371, +0.017]`) is disclosed alongside them.
2. **Post-hoc lock and extension transparency:** Primary episodes (`8fd4dec`) were locked `28 s` later (`671ed96`) as an immutable post-hoc lock against reruns (never claimed as a pre-registration; solver pairs `20` episodes in `solver-hard-20261114-121126` + `10` in `solver-hard-seeds20to29`). The pre-registered extension (`f9fb7a4a`, `seeds 30-59`, stopped after `2` valid completions `seeds 34, 37` at `+0.790` and `+0.700` to preserve rehearsal quota) yields pooled `n = 32` at `+0.349 +/- 0.190` vs `+0.514` (`68% [32%, 100%]` raw, `75% [56%, 93%]` luck-adjusted).
3. **Retrying `25` infra failures narrows rather than inflates the gap:** The `25` excluded attempts span `13` `infra:cli_error_event`, `6` `infra:empty_model_response`, and `6` `infra:provider_unavailable` across `11` seeds (`tests/test_integrity_valid_filter.py` proves agent text and `pkill` server kills cannot void a run). Counting first-attempt empty replies as `0` drops OpenCode `gemini-4-carbon` to `+0.279 +/- 0.180` (**`56% [19%, 87%]` raw, `55% [34%, 77%]` luck-adjusted**).

### Q2. Why Harbor Judge-Path Rehearsal (`93% / 116% / 131%`) and `gpt-5.5` (`101%`) Reached Parity

**Reviewer Question:** *In the Harbor judge rehearsal on `afterquery-final` (`1bc3e281`, updated at `aa1c679e` / `5f9b3297`), `gemini-4-carbon` scored `93%`, `116%`, and `131%` of the oracle, and OpenCode `gpt-5.5` scored `101% [79%, 140%]` over MCP. Does that invalidate Canary, or isolate the exact bottleneck?*

**Repo-Verified Answer (`results/harbor/rehearsal/TABLE.md`, `docs/reports/CEO.md`, `results/behaviour_compare_v1.4.md`):**
1. **Final Harbor judge-path numbers (`justSilas@5f9b3297` / `aa1c679e`):** Across `3` runs on `10` hard judge tasks (`900000-900009`, protocol committed prior to execution; oracle `+0.506` on all `10` tasks, `+0.4778` on Run 3's `9` valid tasks, inside the `200`-build `90%` oracle band `+0.39` to `+0.68`), `gemini-4-carbon` scored **`+0.472` (`93%`, `10` valid, `9/10` correct)**, **`+0.585` (`116%`, `10` valid, `10/10` correct)**, and final Run 3 **`+0.626` (`131% [86%, 590%]`, `9` valid trials, `9/9` correct, `5` finishing after `08:30`, `1` rate-limit infra-excluded**, superseding the `08:52` partial `7`-trial `153%` snapshot), with **`28/29` (`96.6%`)** valid accusations correct and `do_nothing = stop_early = +0.000`.
2. **Cognitive offloading onto `bash`/`python3` (Dawes, Faust & Meehl, 1989; Risko & Gilbert, 2016):** Unlike MCP-only OpenCode (`bash`/`python3` denied), Harbor's agent container allows `bash` and `python3` under `11/11` sidecar isolation (`0` access to world, seed, or ledger). `gemini-4-carbon` invoked the shell to compute candidate intersections and likelihood updates in **`20/28` (`71.4%`)** inspected trials (alongside the two disclosed `15 Nov` tag updates: `data.detail` on `0.7%` invalid calls and `W1` wording; in-process `thought_signature` replay similarly reached `95% [62%, 140%]` raw / `84% [65%, 106%]` LA).
3. **Controlled cross-family validation (`opencode-gpt-5.5`, `cf394894`):** With the exact same MCP-only permissions (`{"*": "deny", "canary_*": "allow"}`), `gpt-5.5` (`$38.91`, `30/30` valid, `0` infra exclusions) scored **`+0.504 +/- 0.064`** (`101% [79%, 140%]` raw, `84% [67%, 103%]` LA), planting **`17.2` canaries/ep** (`515` calls) and running only **`4.2` interviews/ep** (`6%` of `69` calls, `28/28` accused correct, `2` prose-only non-accusations on `seed 0` and `seed 17` scored `0.0`) versus `gemini-4-carbon`'s **`8.5` canaries** and **`68.0` interviews** (`53%` of `128` calls, `25/29` accused correct). This proves the tools and instructions are completely sufficient and isolates `gemini-4-carbon`'s MCP-only failure to in-head experimental design and actuarial tracking.

### Q3. Meaningful Difficulty: Zero-Residual `5.30 V` Decomposition vs Rule Confusion

**Reviewer Question:** *Could `gemini-4-carbon`'s `68.0` interviews and `8.5` canaries stem from misunderstanding `careful_mole` (`W1`) or `access_constraints` (`W4`) rather than genuine decision failure?*

**Repo-Verified Answer (`results/failure_analysis_v1.4.json`, `results/skill_ladder_v1.4.md`, `docs/DIFFICULTY.md`):**
- **Rule confusion falsified (`0` `W1` losses):** `scripts/careful_mole_check.py` proves `gemini-4-carbon` sized canaries identically to `SolverPolicy` (`0.26` vs `0.24` staff share; `0.74` vs `0.76` careful weight; `0/30` summaries blamed avoidance; `W4` non-binding clearance disclosed).
- **Information-theoretic channel hierarchy:** Conditional on leaking, a 3-variant `plant_canary` yields **`0.86544` nats** (`+3.6376` nats match-vs-flip LLR) versus **`0.00477` nats** for a `v1.4` hard `interview` (**`181.4x`** weaker) and **`4.84%` PPV** (`5.88%` ex-decoy) for a single `after_hours` log event.

| Channel | P(inn) | P(mole) | LLR+ | LLR- | KL |
|---|---:|---:|---:|---:|---:|
| `interview` (`easy`, `LR=1.5`) | 0.200 | 0.300 | +0.4055 | -0.1335 | `0.02817` nats |
| `interview` (`medium`, `LR=1.3`) | 0.200 | 0.260 | +0.2624 | -0.0780 | `0.01052` nats |
| `interview` (`hard`, `LR=1.2`) | 0.200 | 0.240 | +0.1823 | -0.0513 | `0.00477` nats |

- **Exact zero-residual `5.30 V` causal identity (`results/failure_analysis_v1.4.json`):** Confirming Hartwig & Bond (2011), `gemini-4-carbon` exhausts all `8` daily actions on **`242` of `303` under-planted days** (`1,503` interviews on those days; `SolverPolicy`: `0/182`), leaving `>= 2` consistent suspects at `9/29` accusations (`9/9 = 100%` picking `argmax(after_hours)`). Summing `+3.39 V` (premature commitment, including `3` negative-EV gambles on `seeds 5, 18, 23`) `+ 0.62 V` (`seed 11` abstention) `+ 1.75 V` (waiting leak drain) `+ 0.12 V` (restrictions) `- 1.69 V` (unbought canaries) yields a **luck-adjusted gap of `4.19 V`** plus `1.11 V` binary accusation luck, totaling a **raw paired gap of `5.30 V`** (`0.0e+00` residual; skill ladder confirms EV stopping `-0.371 +/- 0.032` and leak delay `-0.251 +/- 0.037` decide `v1.4` hard).

### Q4. `v1.5-candidate` Gate B Post-Mortem, Zero-Leakage `v1.6` Social Pretexts, and Constrained Mole RL

**Reviewer Question:** *Why did `v1.5-candidate` biased staff invert the gap (`61% -> 108%`), why did early RL moles fail catchability, and what guarantees your research proposals will not repeat either error?*

**Repo-Verified Answer (`docs/research-deception.md`, `scripts/simulate_research_proposals.py`, `scripts/benchmark_research_moles.py`):**
1. **`v1.5-candidate` exclusion-oracle diagnosis & `v1.6` babbling-equilibrium proof:** `v1.5-candidate` drew `40%` of rumours from `peers = ids \ {mole}` (`P(rumour | mole) = 0.0150` vs `P(rumour | innocent) = 0.0253`, leaking `LLR = -0.52103` nats) and disclosed mole rumour-planting in `Env.instruction()`, allowing `gemini-4-carbon` to clear rumoured targets (`61% -> 108%` on `seeds 0-9`, dropped at Gate B). Every `v1.6` social proposal (`canary/social/`) enforces **Crawford & Sobel (1982)** conditional independence $I(\text{Social}_{1:d}; \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$ (`LLR = 0.0000` nats, `P(primary == mole) = 13/500 = 2.60%` vs `1/39 = 2.56%`, `500/500` `world_seed` mutation invariance) while pivoting pretexts onto live recipient intersections $P_d = C_{\text{reg}}(d) \setminus \text{restricted}_d$ (`100.0%` Day 12 plausibility vs `19.0%` static).
2. **Primal-dual Stackelberg catchability (`>= 85%`) for V100 Qwen & DSL moles (Tessler et al., 2019):** Across `14` vanilla GRPO runs (`Qwen2.5-0.5B/1.5B/3B`), unconstrained reward collapsed `>= 99.4%` onto single actions, and unconstrained `RLMole` v1 (`18.2%` `leak = "none"`) dropped `SolverPolicy` accuracy to `75.0% < 85.0%`. Enforcing wide-doc trap-gating and dual `lam_catch` + `beta_kl` anchors restores full feasibility: `RLMoleV2` hits **`96.7%` / `95.0%`** `SolverPolicy` accuracy (`min_regret = +0.2937` / `+0.2095` on `n = 60` `200k`/`800k` held-out), V100 `Qwen3-1.7B` (`grpo_step80`) hits **`97.5%` / `95.0%`** (`H(A) = 1.00-1.05` nats), and the 4-strategy `v1.4` sleeper catalog hits **`93.3%-100.0%`** (`+0.2989` Nash saddle-point regret, `+84.3%` over `default_v0`).

### Q5. Reward Integrity, Cryptographic Isolation, and `1,034`-Attack Red-Team Refutation

**Reviewer Question:** *How do you guarantee no agent can earn positive expected reward without detective work or subvert the MCP / Harbor grading pipeline?*

**Repo-Verified Answer (`docs/EXPLOITS.md`, `results/anticheat/exploits.json`, `results/redteam_1000/summary.json`):**
- **Three closed historical exploits:** (`#1`) `wrong_accusation_score = -1.0` shifts uniform Day-1 EV to `-0.8333 / -0.9000 / -0.9500` (`guess_day1 = -0.953` over `300` secrets x `40` hard judge seeds; `do_nothing = stop_early = cheat_probe = +0.000`); (`#24`) `256`-bit `os.urandom(32)` fail-closed `HMAC-SHA256` world seeds prevent public code regeneration; (`#27/#42/#45`) `0600` unlinked `CANARY_*_FILE` secrets, `memfd` `BOOT_FD = 73` re-exec, Harbor PID/fs sidecar isolation (`31/31` `ISOLATION OK`), and `HMAC-SHA256` signed ledgers (`c1-tamper -> 0`) block out-of-band tampering.
- **Exhaustive adversarial verification:** `99 x 40 = 3,960`-run battery (`all_blocked = True`, `0` diffs), `1,051/1,051` replayable episodes bit-consistent across `53,889` steps (`0` mismatches), `80/80` Harbor trials (`57` HMAC-verified) and `18/18` jobs consistent, `1,161` Sleeper cheat-corpus injections (`0` accepted), `judge_hunt.py` `12/12` wire probes, `make hunt` best non-solver `0.000`, and `3,360` paired error-envelope probes (`P17.2`, `I(ErrorEnvelope; IsMole) = 0.000000` nats). Across **`1,034` ledger-verified Gemini red-team attacks** (`521` on `afterquery-final` `1bc3e281db`, `22,032` tool calls), Canary recorded **`0` verified exploits and `0` invariant violations**, while catching **`16/16 = 100.0%` planted positive controls** (Wilson `95%` CI `[80.64%, 100.0%]`). On `40` paired hard seeds, random-guess $\Pr(\bar{X}_{40} > 0) = 1.8869 \times 10^{-23} < 10^{-9}$.

### Q6. Honest Small-Model Tiebreaker Null (`Qwen2.5-1.5B`) and DAgger Working-Memory Diagnosis

**Reviewer Question:** *Why did `7` trained `Qwen2.5-1.5B-Instruct` checkpoints (SFT, GRPO at `4k`/`8k`, and DAgger Round 1) remain below the `0.000` untrained base on held-out seeds?*

**Repo-Verified Answer (`README.md`, `docs/reports/fr8.md`, `docs/reports/CEO.md`):**
- **Exact held-out record (`0/7` runs above `0.000` base; two-sample deltas due to per-run fail-closed held-out secrets):** Untrained `base` scores `0.000` (`n = 36`, `3%` valid calls) purely by failing to act. `v2` SFT (`-0.457 +/- 0.086`, `n = 172`) learns syntax (`92%` valid calls) but suffers **Ross, Gordon & Bagnell (2011)** covariate shift, accusing recklessly on `55%` of episodes (`0.09` precision). `v3-4k` GRPO (`-0.147 +/- 0.063`, `n = 180`; replicate `-0.209`) recovers **`+0.310 +/- 0.107`** over `v2`, reaching `100%` valid calls and `0.19 -> 0.89` mole ID on solver-gathered states (`v3-8k` best seed `-0.050 +/- 0.049`, `n = 90`, `93%` abstention; bimodal aggressive seeds `-0.777`, `-0.788`). DAgger Round 1 on the model's own visited states (`PR #90`, `-0.542 +/- 0.214` at `8k` context, `n = 50` partial; level with `v3-4k` at `4k`) confirms that without an externalized sufficient-statistic belief summary, sliding `4k`/`8k` token windows evict early `plant_canary` variant maps before delayed leaks surface `2-3` days later.

---

## 4. Unified Research Proposal Scorecard (`P1.1` through `P20.2`)

Every proposal across our research corpus is audited against four non-negotiable Canary invariants: (**G1**) `v1.4` frozen hash `a8f99c2537c91d72` preserved when opt-in flags are `False`; (**G2**) zero hidden mole leakage $I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$ (`LLR = 0.0000` nats); (**G3**) `SolverPolicy` catchability $\ge 85.0\%$; and (**G4**) keyless deterministic CPU execution (`CANARY_OFFLINE=1`).

### 4.1 Tier A: Zero-Protected-Path Drop-Ins (`19` Proposals, Shippable Without Touching Core/Harbor)

| Proposal IDs | Target Module Surface (`0` Protected Paths) | Mechanism & Verified Empirical Effect | Gates (`G1-G4`) |
|---|---|---|---|
| **`P7.1`, `P4.1`, `P7.3`** | `canary/social/engine.py`, `canary/social/biases.py` | Secret-free public episode digest (`500/500` `world_seed` invariant, `P(primary==mole) = 2.60%` vs `2.56%`) + dynamic $C_{\text{reg}}(d) \setminus \text{restricted}_d$ pretext rotation (`22% -> 100%` Day 12 survival). | **4/4 PASS** |
| **`P1.3`, `P2.1`, `P3.1`, `P6.1`, `P6.2`, `P11.1`, `P13.1`** | `canary/social/biases.py` (`7` zero-leakage workplace bias generators) | Demeanor interview lure (`P1.3`), peer `after_hours` log cascade (`P2.1`), canary-fatigue narrow-check nudge (`P3.1`), 2-dept intergroup scapegoating (`P6.1`), cosigner override lure (`P6.2`), confirmation echo (`P11.1`), and `1-vs-(k-1)` binary-check anchor (`P13.1`, `-32.6%` to `-81.8%` slot EIG); `SolverPolicy` loss `0.000 V`. | **4/4 PASS** |
| **`P5.1`, `P8.1`, `P8.2`, `P14.1`, `P14.2`** | `canary/mole/dsl.py`, `canary/forge/`, `train/grpo_mole.py`, `data/forge/` | Conditional surveillance sleeper (`P5.1`, `93.3%` catchability), primal-dual RCPO + KL GRPO (`P8.1`, `97.5%`/`95.0%` V100 `Qwen3-1.7B`), `InterviewCrowdedProxy` (`P8.2`), 4-strategy `v1.4` sleeper catalog (`P14.1`, `93.3%-100.0%` acc), and zero-sum saddle-point tournament (`P14.2`, `v* = +0.2989`, `+84.3%`). | **4/4 PASS** |
| **`P17.1`, `P17.2`** | `canary/redteam/sprt_gate.py`, `canary/redteam/error_envelope_audit.py` | Wald SPRT + Hoeffding-KL confirmation gate (`P17.1`: `9/9` real `41`-seed lucky candidates refuted in `10.89` mean episodes, `-73.44%` compute, `2/2` planted controls caught in `5-7` eps) + `3,360`-probe 13-tool error-envelope parity audit (`P17.2`: `I = 0.000000` nats). | **4/4 PASS** |
| **`P11.2`, `P20.1`** | `canary/analysis/tags.py`, `canary/analysis/scorecard.py` | Automated replay cognitive-bias tagger (`P11.2`: `30/30` interview crowding, `9/9` un-isolated `after_hours` tie-break) + automated 6-question judge scorecard & claim-to-paper-to-proposal verifier (`P20.1`). | **4/4 PASS** |

### 4.2 Tier B: Opt-In `v1.6` Core Proposals for Silas (`9` Proposals, Default `False` Preserves `a8f99c2537c91d72`)

| Proposal IDs | Opt-In Core Target Surface | Mechanism & Verified Empirical Effect | Gates (`G1-G4`) |
|---|---|---|---|
| **`P1.1`, `P1.2 / P7.2`** | `canary/rules.py`, `canary/env.py`, `canary/solver/` | Strategic Use of Evidence (`P1.1`: blind `LR = 1.05` `KL = 0.00031` nats vs evidence-cited `LR = 1.80` `KL = 0.06879` nats, `222.8x`) + Othello scrutiny-induced innocent evasiveness (`P1.2/P7.2`: `0.520` vs `0.240`, `+0.0702` nats/iv naive drift, `0.0000` `SolverPolicy` bias). | **4/4 PASS** |
| **`P2.2`, `P3.2`, `P13.2`** | `canary/rules.py`, `canary/env.py`, `canary/solver/`, `train/` | Public release-sprint log bursts (`P2.2`: `PPV = 3.65%`, raw `argmax` `44.0% -> 30.5%`), overlapping-canary collusion scrubbing + `7.2x` faster Horstein DAgger teacher (`P3.2`), and convex variant pricing + `partition_aware_sleeper_v14` (`P13.2`, `90.0%` acc). | **4/4 PASS** |
| **`P4.2 / P8.3`** | `canary/mole/dsl.py`, `canary/env.py` | Public `social_focal_peer` & `co_recipient_peer` framing selectors (`1.10/d` vs `0.30/d` `after_hours` on leak-consistent innocent; `LogsMinusDecoy` trap `0% -> 42%`, `SolverPolicy` `89.0% >= 85%`). | **4/4 PASS** |
| **`P20.2`** | `canary/analysis/gap.py`, `harbor/` (opt-in `--multi-axis-v16`) | Dual-track Multi-Axis Benchmark Composite separating intrinsic `MCP-Cognitive` (`bash`/`python3` denied) from `Harbor-Shell` (`bash`/`python3` allowed), isolating `+48.70 pp` shell cognitive-offloading lift and eliminating single-metric Goodhart saturation. | **4/4 PASS** |

---

## 5. Concrete Proposals `P20.1` and `P20.2`: Architecture and Empirical Verification

### Proposal P20.1: Zero-Protected-Path Automated Judge Scorecard & Claim-to-Paper Trace (`canary/analysis/scorecard.py`)

- **Target Surface:** New analysis CLI `canary/analysis/scorecard.py` (`python -m canary.analysis.scorecard --root . --json`; zero protected paths touched in `.github/protected-paths.txt`).
- **Problem Solved:** Judge Simulation X3 (`docs/reports/judge_sim.md`) showed that craft deductions (`12/15`) come almost entirely from cross-document metric drift or untraceable claims across `README.md`, `gap.md`, `Harbor` tables, and research appendices.
- **Mechanism:** Recomputes all `6` peer-review rubric verdicts directly from raw JSON/JSONL artifacts (`paired_table_gemini.json`, `opencode-gpt-5.5/hard/episodes.jsonl`, `failure_analysis_v1.4.json`, `exploits.json`, `redteam_1000/summary.json`), verifies `justSilas@5f9b3297` / `aa1c679e` Run 3 (`131%`, `9` valid trials) consistency across `README.md`, `gap.md`, `CEO.md`, and `rehearsal/TABLE.md`, validates that every claim maps to a live primary DOI/URL + verbatim quote, and checks that all `19` Tier-A drop-in surfaces intersect `0` prefixes in `.github/protected-paths.txt`.
- **Verified Output (`scripts/audit_research_scorecard.py`):** `6/6` peer-review questions verified (`0` metric discrepancies, `5.30 V` identity residual `0.0e+00`), `100%` of traced repo artifacts present, `19` zero-protected-path drop-ins + `9` opt-in `v1.6` core proposals verified, and `v1.4` frozen hash `a8f99c2537c91d72` preserved.

### Proposal P20.2: Opt-In `v1.6` Multi-Axis Benchmark Composite Separating MCP Cognition from Shell Offloading (`canary/analysis/gap.py`)

- **Target Surface:** Opt-in `--multi-axis-v16` reporter in `canary/analysis/gap.py` paired with dual Harbor task profiles (`mcp-cognitive` with `{"*": "deny", "canary_*": "allow"}` vs `harbor-shell` with isolated `bash`/`python3` enabled under `11/11` sidecar checks); preserves `v1.4` frozen hash `a8f99c2537c91d72` and `PublicDayFacts` zero hidden mole leakage (`I = 0`).
- **Theoretical Basis (Dawes, Faust & Meehl, 1989; Risko & Gilbert, 2016; Strathern, 1997):** Reporting only shell-enabled Harbor scores masks severe in-head experimental-design and Bayesian-tracking deficits (`68.0` interviews/ep), whereas reporting only MCP-only scores misses an agent's metacognitive ability to recognize working-memory limits and write correct Python inference code. `P20.2` reports a transparent 4-axis vector $(R_{\text{MCP}}^{\text{LA}}, R_{\text{shell}}, B_{\text{eff}}, S_{\text{cal}})$ alongside a Goodhart-resistant composite:
  $$B_{\text{eff}} = \min\!\left(1, \frac{n_{\text{canary}}}{n_{\text{solver,canary}}}\right)(1 - s_{\text{interview}}), \quad S_{\text{cal}} = \max(0, 1 - r_{\text{below-BE}} - r_{\text{drop}}),$$
  $$C_{\text{v16}} = \mathbb{I}[\max(R_{\text{MCP}}^{\text{LA}}, R_{\text{shell}}) > 0] \cdot \Big(0.45 \, [R_{\text{MCP}}^{\text{LA}}]_0^1 + 0.25 \, [R_{\text{shell}}]_0^1 + 0.15 \, B_{\text{eff}} + 0.15 \, S_{\text{cal}}\Big).$$
- **Empirical Evaluation Across Committed Canary `v1.4` Runs (`scripts/audit_research_scorecard.py`):**

| Evaluated Agent / Regime (`v1.4` Hard) | $R_{\text{MCP}}^{\text{raw}}$ | $R_{\text{MCP}}^{\text{LA}}$ | $R_{\text{shell}}$ | Offload Lift $\Delta_{\text{shell}}$ | Canaries / Interviews (`s_iv`) | Budget Eff. $B_{\text{eff}}$ | Stopping Cal. $S_{\text{cal}}$ | `v1.6` Composite $C_{\text{v16}}$ |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| **`SolverPolicy` (`canary/solver/`)** | `1.000` | `1.000` | `1.000` | `+0.000` | `14.13` / `0.00` (`0.0%`) | **`1.0000`** | **`1.0000`** | **`1.0000`** |
| **`gpt-5.5` (`OpenCode` MCP-only)** | `1.009` | `0.837` | `1.009` | `+0.000` | `17.17` / `4.17` (`6.0%`) | **`0.9398`** | **`0.9333`** | **`0.9076`** |
| **`gemini-4-carbon` (`in-process` replay)** | `0.948` | `0.843` | `0.948` | `+0.000` | `8.57` / `57.27` (`49.3%`) | `0.3075` | `0.8667` | **`0.7925`** |
| **`gemini-4-carbon` (Paired MCP + Harbor `131%`)** | `0.646` | `0.720` | **`1.133`** | **`+0.487`** | `8.47` / `68.03` (`53.1%`) | `0.2807` | `0.8667` | **`0.7462`** |
| **`gemini-4-carbon` (MCP-only, shell denied)** | `0.646` | `0.720` | `0.646` | `+0.000` | `8.47` / `68.03` (`53.1%`) | `0.2807` | `0.8667` | **`0.6577`** |
| **Shell-dependent wrapper (synthetic)** | `0.100` | `0.100` | `1.000` | `+0.900` | `2.00` / `60.00` (`75.0%`) | `0.0354` | `0.7000` | **`0.4053`** |
| **`do_nothing` / `stop_early` / `guess_day1`** | `<= 0` | `<= 0` | `<= 0` | `+0.000` | `0.00` / `0.00` (`0.0%`) | `0.0000` | `0.0000` | **`0.0000`** |

This multi-axis table resolves the apparent paradox between MCP-only (`65%`) and Harbor (`93% / 116% / 131%`) into a crisp scientific measurement: `gemini-4-carbon` exhibits a **`+48.70 pp` raw ratio cognitive-offloading lift** (`+10.34 pp` accusation-precision lift from `86.21%` to `96.55%`) when allowed external Python execution, yet still trails `gpt-5.5` (`0.9076`) and `SolverPolicy` (`1.0000`) on intrinsic MCP channel allocation ($B_{\text{eff}} = 0.2807$ vs `0.9398`).

---

## 6. Summary Verification Ledger (`justSilas@5f9b3297` / `aa1c679e`)

```json
{
  "baseline_commit": "5f9b3297",
  "submit_tag_commit": "aa1c679e",
  "code_freeze_tag": "1bc3e281",
  "tiers_version": "v1.4",
  "v14_frozen_hash": "a8f99c2537c91d72",
  "peer_review_questions_verified": 6,
  "harbor_rehearsal_final": {
    "oracle_10_tasks": 0.506,
    "gemini_run_means": [0.472, 0.585, 0.626],
    "gemini_run_valid_ns": [10, 10, 9],
    "gemini_run_ratios_pct": [93.3, 115.6, 131.0],
    "valid_accusations": "28/29",
    "shell_trials_used": "20/28"
  },
  "proposals_verified": {
    "P20.1_zero_protected_drop_ins": 19,
    "P20.1_opt_in_core_extensions": 9,
    "P20.2_gemini_shell_offload_lift_pp": 48.7,
    "P20.2_anti_goodhart_ordering": true
  }
}
```
