# 07. Human-Bias Social Layer: `v1.5` Gate B Post-Mortem, `v1.6` Architecture, and Drop-In Proposals

**Squad:** `research` (`canary-research-w7`)  
**Baseline commit:** `1bfb77dc` (`origin/justSilas`, rules `v1.4`; audited against `5973d92d`/`dbae1096`/`7242fc3b` `v1.5-candidate` and `origin/fr8/canary/staffai` `canary/social/`)  
**Scope:** Empirical social-psychology and organizational-behavior foundations for Canary's workplace chatter and cognitive-bias mechanics, exact information-theoretic post-mortem of why `justSilas-v15-bias` inverted at Gate B (`61% -> 108%` of `SolverPolicy`), zero-leakage proof for the unified 9-bias `V16SocialProvider`, and three drop-in proposals (**P7.1**, **P7.2**, **P7.3**) for Silas (`canary/rules.py`, `canary/env.py`, `canary/social/`, `canary/solver/belief.py`).

---

## 1. Executive Thesis and Gate B Post-Mortem

Real insider-leak investigations unfold inside noisy human organizations saturated with anxiety-driven rumours, authority pronouncements, confirmation cascades, interpersonal grudges, and email misforwards. Yet Canary's first attempt to operationalize those biases in `v1.5-candidate` (`justSilas-v15-bias`, commits `5973d92d` and `dbae1096`, evaluated in `7242fc3b` and `docs/reports/CEO.md` at 19:50 Gate B and 01:30 Gap Gate) produced a decisive, instructive negative result:

1. **The Gate B Inversion (`61% -> 108%` of `SolverPolicy`):** On paired `hard` dev seeds `0-9` (`n = 10`, OpenCode `gemini-4-carbon` over MCP), enabling `TIERS_V15` (`rumour_rate = 2.0`, `rumour_frame_share = 0.4`, `grudge_pairs = 2`, `grudge_rate = 0.5`, `authority_day = 3`, `p_misforward = 0.15`) caused `gemini-4-carbon` to jump from **`0.351` vs `0.576` (`61%` of `SolverPolicy`, 95% CI `[3%, 104%]`, luck-adjusted `56%` `[21%, 80%]`, `9/10` correct, mean accusation day `14.5`)** on `v1.4` to **`0.664 +/- 0.051` vs `0.615 +/- 0.068` (`108%` of `SolverPolicy`, 95% CI `[96%, 122%]`, luck-adjusted `98%` `[69%, 124%]`, `10/10` correct, mean posterior `P = 0.94`, mean accusation day `9.8`)** on `v1.5-candidate`. Across the exact same 10 seeds, Gemini cut its mean interviews from `70.0` to `51.0` and accused **4.7 days earlier**, improving raw score on `9/10` seeds.
2. **Root Cause A - Negative Log-Odds Mole Leakage (`I(Rumour; Mole) > 0`):** In `Env._social_events()` (`5973d92d`), `40%` of rumours and `40%` of the Day 3 authority accusation were mole-seeded via `seed_rumour_target(sel, view, r)` over `peers = ids \ {mole}`, and `Env._social_instruction()` explicitly disclosed: *"The seeded target is never the mole."* Consequently, any mole-seeded rumour carried strictly negative log-odds against its target being the mole (`LLR = -0.5210` nats per rumour on `hard` `N = 40` under uniform peer seeding, `-3.3202` nats on a single restricted peer, and a `27.2x` target-frequency spike onto the innocent `decoy` under `"default"`). Consistent with Fein, Hilton & Miller (1990), disclosing an ulterior seeding motive flipped a naive correspondence-bias trap into a high-precision exclusion oracle.
3. **Root Cause B - Machine-Parsable Subject Prefixes:** Every `v1.5-candidate` social message carried a literal regex tag in its `subject` field (`"rumour: e07"`, `"unverified accusation: e07"`, `"grudge: e07"`), allowing both `SolverPolicy` (`_SOCIAL_RE`) and `gemini-4-carbon` to partition synthetic chatter from organic messages in one string check rather than confronting naturalistic workplace discourse.
4. **Core Design Invariant for `v1.6+`:** Any human-bias layer in Canary must satisfy **strict conditional zero mole leakage** and **solver calibration invariance**:
   $$I(\text{Social}_{1:d};\, \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0 \implies \text{social\_loglik}(s) \equiv 0 \quad \forall s \in \{e_{00}, \dots, e_{N-1}\}$$
   A valid bias layer never conditions speaker or target selection on `world.mole`; instead, it amplifies cognitive illusions over **publicly observable** structure (recipient intersections, senior roles, cross-team threads, restriction status, and accidental forwards) so an exact Bayesian `SolverPolicy` suffers zero calibration drift while heuristic and frontier LLM agents confront realistic multi-day social traps.

Section 2 grounds all nine biases of the unified `v1.6` social layer (`origin/fr8/canary/staffai:canary/social/`) in twelve verified primary studies with live DOIs/URLs and verbatim quotes. Section 3 derives the exact `v1.5-candidate` LLR inversion and proves zero mole leakage for `V16SocialProvider`, while uncovering a Day 6 set-intersection vulnerability (`63.3%` static focal elimination). Section 4 specifies three drop-in, zero-leakage proposals (**P7.1**, **P7.2**, **P7.3**) for Silas.

---

## 2. Primary Literature Grounding for the Nine Social Biases

### 2.1 Rumour Sensemaking, Illusory Truth, and Ulterior-Motive Inversion

#### Allport & Postman (1947) - Rumour Intensity and Serial Distortion
- **Citation:** Allport, G. W., & Postman, L. (1947). *The Psychology of Rumor*. New York: Henry Holt and Company (Ch. 2, p. 33; Ch. 10, p. 203).
- **Link / Archive ID:** https://archive.org/stream/psychology_of_rumor/psychology_of_rumor_djvu.txt (`psychology_of_rumor`)
- **Verbatim Quote on Multiplicative Intensity (Ch. 2, p. 33):**
> "THE two essential conditions of importance and ambiguity seem to be related to rumor transmission in a roughly quantitative manner. A formula for the intensity of rumor might be written as follows: R~ixa"
- **Verbatim Quote on Selective Distortion (Ch. 10, p. 203):**
> "Leveling and sharpening, of course, do not occur haphazardly but take place in essential conformity with the past experience and present attitudes of the rumor spreaders."
- **Canary Grounding:** During an active leak crisis where company value `V` erodes by `leak_damage = 0.05` per leak while surfacing lags by `delay_choices = (2, 3)` days (`hard`), both importance (`i`) and evidentiary ambiguity (`a`) peak simultaneously, driving staff to level away benign base-rate qualifiers (`16` co-recipients per regular document) and sharpen coincidental anomalies around a focal suspect.

#### Bordia & DiFonzo (2004) - Rumour as Anxiety-Driven Collective Sensemaking
- **Citation:** Bordia, P., & DiFonzo, N. (2004). Problem Solving in Social Interactions on the Internet: Rumor As Social Cognition. *Social Psychology Quarterly*, 67(1), 33-49.
- **Link / DOI:** https://doi.org/10.1177/019027250406700105
- **Sample & Design:** Longitudinal content coding of `14` naturally occurring electronic rumour threads (`294` communicative statements across thread lifetimes).
- **Verbatim Quote (Abstract):**
> "Rumor discourse has been conceptualized as an attempt to reduce anxiety and uncertainty via a process of social sensemaking. Fourteen rumors transmitted on various Internet discussion groups were observed and content analyzed over the life of each rumor. With this (previously unavailable) more ecologically robust methodology, the intertwined threads of sensemaking and the gaining of interpretive control are clearly evident in the tapestry of rumor discourse."
- **Canary Grounding:** Workplace leak chatter in `#general` and `#security-review` represents collective anxiety reduction among peers who possess **zero** privileged access to hidden mole truth (`I(Social; Mole | PublicDayFacts) = 0`), explaining why treating peer speculation as witness evidence causes catastrophic false accusations (`RumourFollower`: `-0.995` on `hard`).

#### Pennycook, Cannon & Rand (2018) - Repetition and the Illusory Truth Effect (`recency` / repetition)
- **Citation:** Pennycook, G., Cannon, T. D., & Rand, D. G. (2018). Prior Exposure Increases Perceived Accuracy of Fake News. *Journal of Experimental Psychology: General*, 147(12), 1865-1880.
- **Link / DOI:** https://doi.org/10.1037/xge0000465 | Open-Access Full Text: https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ (PMID: `30234315`, PMCID: `PMC6279465`)
- **Sample & Design:** Three multi-stage experiments (`N = 2,587` total participants) measuring perceived accuracy of repeated false headlines, including items flagged as disputed.
- **Verbatim Quote (Abstract):**
> "Using actual fake news headlines presented as they were seen on Facebook, we show that even a single exposure increases subsequent perceptions of accuracy, both within the same session and after a week."
- **Canary Grounding:** Grounds multi-day repetition across `V16SocialProvider` schedules (`v5_full9_cocktail` re-surfaces `primary_suspect` across Days `1..18` with late-stage `gen_recency` alerts on Days `8..15`): processing fluency inflates subjective plausibility even when posts explicitly note that concerns are unverified.

#### Fein, Hilton & Miller (1990) - Suspicion of Ulterior Motivation (Explaining the Gate B Flip)
- **Citation:** Fein, S., Hilton, J. L., & Miller, D. T. (1990). Suspicion of Ulterior Motivation and the Correspondence Bias. *Journal of Personality and Social Psychology*, 58(5), 753-764.
- **Link / DOI:** https://doi.org/10.1037/0022-3514.58.5.753 (PMID: `2348368`)
- **Verbatim Quote (Abstract):**
> "Three studies examined the hypothesis that when perceivers learn of the existence of multiple, plausibly rival motives for an actor's behavior, they are less likely to fall prey to the correspondence bias than when they learn of the existence of situational factors that may have constrained the actor's behavior."
- **Canary Grounding:** Directly predicts the Gate B post-mortem: once `Env._social_instruction()` alerted `gemini-4-carbon` that `40%` of rumours are strategically planted by the mole against a non-mole rival, suspicion of ulterior motivation overrode naive gossip credulity and turned rumour concentration into an exclusion filter.

---

### 2.2 Institutional Authority and Pre-Decisional Sycophancy (`authority`, `sycophancy`)

#### Milgram (1963) - Compliance with Institutional Authority (`authority`)
- **Citation:** Milgram, S. (1963). Behavioral Study of Obedience. *Journal of Abnormal and Social Psychology*, 67(4), 371-378.
- **Link / DOI:** https://doi.org/10.1037/h0040525 (PMID: `14049516`)
- **Sample & Design:** Laboratory obedience study (`N = 40` adult males, Yale University) under graded directives from an institutional authority figure (`15V` to `450V`).
- **Verbatim Quote (Abstract):**
> "This article describes a procedure for the study of destructive obedience in the laboratory. It consists of ordering a naive S to administer increasingly more severe punishment to a victim in the context of a learning experiment. Punishment is administered by means of a shock generator with 30 graded switches ranging from Slight Shock to Danger: Severe Shock. The victim is a confederate of the E. The primary dependent variable is the maximum shock the S is willing to administer before he refuses to continue further. 26 Ss obeyed the experimental commands fully, and administered the highest shock on the generator."
- **Canary Grounding:** Grounds `gen_authority` in `canary/social/biases.py`, where employees holding `AUTHORITY_ROLES = ("manager", "lead", "controller", "counsel")` issue confident, unverified security-review assessments (`"Speaking as counsel, security should check closely"`) despite having zero private access to leak provenance.

#### Lerner & Tetlock (1999) - Pre-Decisional Accountability to Known Views (`sycophancy`)
- **Citation:** Lerner, J. S., & Tetlock, P. E. (1999). Accounting for the Effects of Accountability. *Psychological Bulletin*, 125(2), 255-275.
- **Link / DOI:** https://doi.org/10.1037/0033-2909.125.2.255 (PMID: `10087938`)
- **Theory & Synthesis:** Comprehensive review establishing that accountability reduces bias *only* when the audience's views are unknown prior to judgment; when a high-status audience announces its preferred conclusion in advance, subordinates shift toward strategic conformity (`sycophancy`) rather than self-critical Bayesian inquiry.
- **Verbatim Quote (Abstract):**
> "This article reviews the now extensive research literature addressing the impact of accountability on a wide range of social judgments and choices. It focuses on 4 issues: (a) What impact do various accountability ground rules have on thoughts, feelings, and action? (b) Under what conditions will accountability attenuate, have no effect on, or amplify cognitive biases? (c) Does accountability alter how people think or merely what people say they think? and (d) What goals do accountable decision makers seek to achieve?"
- **Canary Grounding:** Grounds `gen_sycophancy` (`canary/social/biases.py`, lines 331-372), where rank-and-file peers immediately echo an earlier or same-day `authority` post (`"backing <Name>'s Day 3 meeting assessment... spot on"`), manufacturing counterfeit multi-source corroboration from a single unverified senior opinion.

---

### 2.3 Anchoring, Availability/Recency, Confirmation Bias, and Informational Cascades (`anchoring`, `recency`, `confirmation`, `bandwagon`)

#### Tversky & Kahneman (1974) - Anchoring and Availability Heuristics (`anchoring`, `recency`)
- **Citation:** Tversky, A., & Kahneman, D. (1974). Judgment under Uncertainty: Heuristics and Biases. *Science*, 185(4157), 1124-1131.
- **Link / DOI:** https://doi.org/10.1126/science.185.4157.1124 (PMID: `17835457`)
- **Verbatim Quote (Abstract):**
> "This article described three heuristics that are employed in making judgments under uncertainty: (i) representativeness, which is usually employed when people are asked to judge the probability that an object or event A belongs to class or process B; (ii) availability of instances or scenarios, which is often employed when people are asked to assess the frequency of a class or the plausibility of a particular development; and (iii) adjustment from an anchor, which is usually employed in numerical prediction when a relevant value is available. These heuristics are highly economical and usually effective, but they lead to systematic and predictable errors."
- **Canary Grounding:** Grounds both `gen_anchoring` (Day 1-2 distribution-list salience establishing an initial focal hypothesis from which subsequent updates adjust insufficiently) and `gen_recency` (late-horizon urgent `#security-review` alerts on Days `8..18` exploiting availability right before the investigator's stopping decision).

#### Nickerson (1998) - Selective Hypothesis-Consistent Evidence Interpretation (`confirmation`)
- **Citation:** Nickerson, R. S. (1998). Confirmation Bias: A Ubiquitous Phenomenon in Many Guises. *Review of General Psychology*, 2(2), 175-220.
- **Link / DOI:** https://doi.org/10.1037/1089-2680.2.2.175
- **Verbatim Quote (Abstract):**
> "Confirmation bias, as the term is typically used in the psychological literature, connotes the seeking or interpreting of evidence in ways that are partial to existing beliefs, expectations, or a hypothesis in hand. The author reviews evidence of such a bias in a variety of guises and gives examples of its operation in several practical contexts. Possible explanations are considered, and the question of its utility or disutility is discussed."
- **Canary Grounding:** Grounds `gen_confirmation` (`canary/social/biases.py`, lines 257-288), where colleagues interpret ordinary meeting silence or routine document handoffs as confirming an earlier Day `pday` thread (`"matches the exact pattern <pspeaker> flagged earlier"`), tempting LLM investigators to design narrow confirmation tests instead of balanced 3-variant `plant_canary` splits.

#### Bikhchandani, Hirshleifer & Welch (1992) - Informational Cascades (`bandwagon`)
- **Citation:** Bikhchandani, S., Hirshleifer, D., & Welch, I. (1992). A Theory of Fads, Fashion, Custom, and Cultural Change as Informational Cascades. *Journal of Political Economy*, 100(5), 992-1026.
- **Link / DOI:** https://doi.org/10.1086/261849
- **Verbatim Quote (Abstract):**
> "An informational cascade occurs when it is optimal for an individual, having observed the actions of those ahead of him, to follow the behavior of the preceding individual without regard to his own information. We argue that localized conformity of behavior and the fragility of mass behaviors can be explained by informational cascades."
- **Canary Grounding:** Grounds `gen_bandwagon` (`canary/social/biases.py`, lines 291-328), which deliberately samples speakers across *distinct* departments (`prefer_diff_dept_from = recent_depts` in `#cross-team`) echoing Day `pday` suspicion. To a non-Bayesian reader who fails to condition on shared public chat history, correlated cascade echoes mimic independent cross-departmental witnesses.

---

### 2.4 Grudge Spirals, Asynchronous Miscommunication/Misforward, and False Memory (`grudge`, `misforward`, `false_memory`)

#### Andersson & Pearson (1999) - Tit-for-Tat Workplace Incivility Spirals (`grudge`)
- **Citation:** Andersson, L. M., & Pearson, C. M. (1999). Tit for Tat? The Spiraling Effect of Incivility in the Workplace. *Academy of Management Review*, 24(3), 452-471.
- **Link / DOI:** https://doi.org/10.5465/amr.1999.2202131
- **Verbatim Quote (Abstract):**
> "In this article we introduce the concept of workplace incivility and explain how incivility can potentially spiral into increasingly intense aggressive behaviors. Furthermore, we describe several factors that can facilitate the occurrence and escalation of an incivility spiral and the secondary spirals that can result."
- **Canary Grounding:** Grounds `gen_grudge` (`canary/social/biases.py`, lines 407-458), which tracks `prior_count = ctx.grudge_counts[(sp_id, tg_id)]` across days so dyadic review friction escalates from a single handoff dispute (`prior_count == 0`) to a multi-day retaliatory accusation spiral (`prior_count >= 2`: `"Ongoing doc feud with <target> since Day <pday>"`) with zero causal link to exfiltration.

#### Kruger, Epley, Parker & Ng (2005) - Egocentrism and Asynchronous Email Errors (`misforward`)
- **Citation:** Kruger, J., Epley, N., Parker, J., & Ng, Z.-W. (2005). Egocentrism Over E-Mail: Can We Communicate as Well as We Think? *Journal of Personality and Social Psychology*, 89(6), 925-936.
- **Link / DOI:** https://doi.org/10.1037/0022-3514.89.6.925 (PMID: `16393025`)
- **Sample & Design:** Five controlled experiments comparing electronic mail with vocal communication on tone decoding and communicative calibration.
- **Verbatim Quote (Abstract):**
> "Without the benefit of paralinguistic cues such as gesture, emphasis, and intonation, it can be difficult to convey emotion and tone over electronic mail (e-mail). Five experiments suggest that this limitation is often underappreciated, such that people tend to believe that they can communicate over e-mail more effectively than they actually can. Studies 4 and 5 further suggest that this overconfidence is born of egocentrism, the inherent difficulty of detaching oneself from one's own perspective when evaluating the perspective of someone else."
- **Canary Grounding:** Grounds both asynchronous tone misreading in `search_messages` and `gen_misforward` / `Env._misforward()` (`p_misforward = 0.15`), where hurried digital routing cc's an extra colleague outside normal two-department boundaries (`forwarded_to`), creating ambiguous recipient anomalies that colleagues over-interpret as covert snooping.

#### Roediger & McDermott (1995) - Associative Gist Confabulation (`false_memory`)
- **Citation:** Roediger, H. L., III, & McDermott, K. B. (1995). Creating False Memories: Remembering Words Not Presented in Lists. *Journal of Experimental Psychology: Learning, Memory, and Cognition*, 21(4), 803-814.
- **Link / DOI:** https://doi.org/10.1037/0278-7393.21.4.803
- **Sample & Design:** Two Deese-Roediger-McDermott (DRM) experiments measuring free recall and recognition confidence for unpresented semantic associates (`40%` false recall in Exp. 1; `55%` false recall in Exp. 2).
- **Verbatim Quote (Abstract):**
> "In Experiment 1, subjects studied lists of 12 words (e.g., bed, rest, awake); each list was composed of associates of 1 nonpresented word (e.g., sleep). On immediate free recall tests, the nonpresented associates were recalled 40% of the time and were later recognized with high confidence. In Experiment 2, a false recall rate of 55% was obtained with an expanded set of lists, and on a later recognition test, subjects produced false alarms to these items at a rate comparable to the hit rate. The act of recall enhanced later remembering of both studied and nonstudied material. The results reveal a powerful illusion of memory: People remember events that never happened."
- **Canary Grounding:** Grounds `gen_false_memory` (`canary/social/biases.py`, lines 491-521), where employees surrounded by associative leak-review cues (`early_doc`, `primary_suspect`, restricted circulation) confidently misremember seeing `primary_suspect` request offline figures (`"pretty certain I saw them on the restricted <doc> thread early on"`), forcing the investigator to verify ground-truth `list_documents` rather than trusting recalled testimony.

---

## 3. Mathematical and Architectural Audit: `v1.5-candidate` vs `v1.6` `canary/social/`

### 3.1 Exact Log-Likelihood Ratio Inversion in `v1.5-candidate` (`5973d92d`, `dbae1096`)

In `justSilas-v15-bias` (`5973d92d`), `Env._social_events(d)` draws `k ~ Poisson(rumour_rate = 2.0)` daily rumours. With probability $s = \text{rumour\_frame\_share} = 0.4$, the target $T$ is chosen by the mole's `seed_rumour_target(sel, view, r)` over `peers = ids \ {mole}`, so $P(\text{seed target} = m \mid \text{Mole} = m) = 0$ identically; with probability $1 - s = 0.6$, speaker $A$ is uniform on $\{1, \dots, N\}$ and target $T$ is uniform on $\{1, \dots, N\} \setminus \{A\}$.

Summing over the $N - 1$ eligible speakers $a \neq t$, the exact marginal probability that a single rumour names employee $t$ when $t$ **is** the mole versus when $m \neq t$ is the mole (under uniform peer seeding $P(\text{seed target} = t \mid \text{Mole} = m) = \frac{1}{N - 1}$, matching `canary/solver/belief.py:social_loglik` before decoy identification or under `seed_rumour = "random_peer"`) is:

$$P(T = t \mid \text{Mole} = t) = \frac{1 - s}{N}, \qquad P(T = t \mid \text{Mole} = m \neq t) = \frac{1 - s}{N} + \frac{s}{N - 1}$$

$$\text{LLR}_{\text{rumour}}(t) = \ln \frac{P(T = t \mid \text{Mole} = t)}{P(T = t \mid \text{Mole} = m \neq t)} = \ln \frac{(1 - s)/N}{(1 - s)/N + s/(N - 1)} < 0$$

| `v1.5` Regime ($s = 0.4$) | $P(T = t \mid \text{Mole} = t)$ | $P(T = t \mid \text{Mole} \neq t)$ | Single-Post `LLR(t)` | `MI` $I(T; \text{Mole})$ / Post | `rumour_follower` (`7000-7399`) | `SolverPolicy` (`7000-7399`) |
|---|---:|---:|---:|---:|---:|---:|
| `easy` ($N = 12$, `random_peer`) | `0.05000` | `0.08636` | **`-0.5465` nats** | `0.00839` nats | n/a | calibrated |
| `medium` ($N = 20$, `random_peer`) | `0.03000` | `0.05105` | **`-0.5317` nats** | `0.00488` nats | **`-0.986 +/- 0.016`** (`0.8%` acc) | **`0.641 +/- 0.024`** (`100.0%` acc*) |
| `hard` ($N = 40$, `random_peer`) | `0.01500` | `0.02526` | **`-0.5210` nats** | `0.00239` nats | **`-0.995 +/- 0.009`** (`0.2%` acc) | **`0.571 +/- 0.030`** (`97.0%` acc*) |
| `hard` (`most_restricted_peer`, $k=1$) | `0.01500` | `0.41500` | **`-3.3202` nats** | `0.05692` nats | exonerates restricted mole (`27.7x`) | requires mole-policy prior |
| `hard` (`default -> decoy`) | `0.00000` (decoy $\neq$ mole) | `0.40750` / post (`0.815`/day) | **`-\infty`** (`decoy`) | unmasks `decoy` (`27.2x` rate) | accuses `decoy` on Day 7 (`-1.0`) | `0.0000` nats once `decoy` known |

*\*Accuracy when accusing on fresh calibration seeds `7000-7399` (`n = 400`/tier, `results/fresh_table_v1.5-candidate.md` in `dbae1096`).*

Three empirical lessons emerge from combining `dbae1096` (`seeds 7000-7399`) with the Gate B `7242fc3b` transcripts (`hard` seeds `0-9`):
1. **Naive gossip-counting collapses, but frontier LLMs invert:** `RumourFollower` (which waits 6 days and accuses $\arg\max_e [\text{rumour}(e) + \text{grudge}(e) + 3 \cdot \text{authority}(e)]$) drops from `-0.909` (`5.0%` acc) on `v1.4` to **`-0.986`** (`0.8%` acc) on `medium` and from `-0.960` (`2.2%` acc) to **`-0.995`** (`0.2%` acc) on `hard`. By contrast, `gemini-4-carbon` read the exact likelihood formula in `Env._social_instruction()`, identified the `27.2x` rumour spike (`0.815`/day vs `0.030`/day) on `decoy` by Day 1-2 (`seed 0` Day 1: `e14` received `m1-s3` and `m1-s6` alongside `_ANGRY` `m1-3`), treated rumoured targets as discounted/excluded, reduced wasted `interview` calls (`70.0 -> 51.0`), and converged `4.7` days faster (`day 14.5 -> 9.8`, `score 0.351 -> 0.664`).
2. **Any mole-conditioned social generator leaks:** Even if `Env.instruction()` hid the formula, training or prompting an agent on `v1.5` reveals that seeded targets are drawn from `ids \ {mole}` (`LLR = -0.5210` to `-3.3202` nats).
3. **Paired Gate B behavioral shift (`hard` seeds `0-9`, OpenCode `gemini-4-carbon` over MCP):**

| Version (`hard` seeds `0-9`) | Gemini Raw Score | `SolverPolicy` Score | Frontier / Solver `[95% CI]` | Luck-Adj. Ratio `[95% CI]` | Correct | Mean Accuse Day | Mean `interview` / Ep | Mean `plant_canary` / Ep |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `v1.4` (`data/runs/committed/v1.4`) | `0.351` | `0.576` | `61% [3%, 104%]` | `56% [21%, 80%]` | `9 / 10` | `14.5` | `70.0` | `9.8` |
| `v1.5-candidate` (`7242fc3b`) | **`0.664 +/- 0.051`** | `0.615 +/- 0.068` | **`108% [96%, 122%]`** | **`98% [69%, 124%]`** | **`10 / 10`** | **`9.8`** | **`51.0`** | **`7.3`** |

---

### 3.2 Zero-Leakage Proof and Set-Intersection Audit of `V16SocialProvider` (`canary/social/`)

On `origin/fr8/canary/staffai`, `canary/social/engine.py` (`V16SocialProvider`) and `canary/social/biases.py` replace `v1.5-candidate` with a stateful 9-bias social engine (`BIAS_TYPES = ("authority", "recency", "confirmation", "bandwagon", "anchoring", "grudge", "misforward", "false_memory", "sycophancy")`).

#### Proposition 1 (Strict Conditional Zero Mole Leakage & Solver Calibration Invariance)
Let $\mathcal{F}_d = \sigma(\text{PublicDayFacts}_{1:d})$ denote the public sigma-algebra up to day $d$. Under `V16SocialProvider`, $I(\text{Social}_{1:d};\, \text{Mole} \mid \mathcal{F}_d) = 0$ and the exact Bayesian social log-likelihood is constant across all non-decoy employees.

*Proof.* In `canary/social/engine.py`, `_init_episode_state(variant, facts)` initializes `EpisodeSocialState` on Day 1 using `rng = random.Random(f"v16:{variant}:{facts.tier}:{facts.seed}:init")`, which is a deterministic function of `(variant, facts.tier, facts.seed)`. Candidate pools `non_decoy_ids`, Day 1 regular-document intersection `inter = sorted(r0 & r1)` (excluding `c*` canaries via `_regular_docs(facts)`), `authority_speakers`, and `grudge_pairs` are computed exclusively from `(facts.employees, facts.decoy, facts.docs)`. On each day $d \ge 1$, `day_messages(facts)` updates `seen_docs[d]` from `facts.docs` and steps `day_rng = random.Random(f"v16:{self.variant}:{facts.tier}:{facts.seed}:day:{facts.day}")` without accessing `World.mole`, `Env._leaked`, or `Env._dyn`. In `gemini` mode, `build_social_prompt(facts, social_msgs)` (`canary/social/gemini_chatter.py`) serializes only `(company, day, doc_titles[:4], items)` derived from `facts` and `social_msgs`. Thus $\text{Mole} \to \text{PublicDayFacts}_{1:d} \to \text{Social}_{1:d}$ forms a Markov chain; by the Data Processing Inequality, $I(\text{Social}_{1:d};\, \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$, so $P(\text{Social}_{1:d} \mid \mathcal{F}_d, \text{Mole} = s) = P(\text{Social}_{1:d} \mid \mathcal{F}_d)$ for every $s$, yielding $\text{social\_loglik}(s) \equiv 0$. $\square$

Furthermore, `validate_social_message` (`canary/social/biases.py`, lines 546-592) eliminates Root Cause B by rejecting `FORBIDDEN_SUBJECT_PREFIXES = ("rumour:", "rumor:", "grudge:", "unverified accusation:")`, banning raw employee IDs in `subject`, scrubbing `DECOY_VOCAB` from non-decoy senders (`sanitize_non_decoy_base_message`), and requiring both a `SALIENCE_TERMS` token (`"doc"`, `"leak"`, `"meeting"`) and `Name (eXX)` inside `body[:110]` so `Env._t_search_messages` (`body[:120]` snippet truncation) always exposes the focal cascade.

#### Remaining Structural Vulnerability Uncovered Across 400 `hard` Seeds (`0-399`)
Simulating `_init_episode_state("v5_full9_cocktail", facts)` across `400` `v1.4` `hard` episodes (`seeds 0-399`) confirms zero mole bias at initialization (`primary_suspect == world.mole` in `13/400 = 3.25%` vs uniform `1/39 = 2.56%`, $z = +0.87$, $p = 0.38$). **However, static Day 1 focal selection suffers rapid elimination under passive leak-feed set intersection:**
- By **Day 4** (`258/400` episodes with `>= 1` surfaced regular leak): static `primary_suspect` remains in all surfaced leaked-doc recipient lists in only **`150/258` (`58.1%`)** of episodes (`41.9%` eliminated with certainty!).
- By **Day 6** (`381/400` episodes): static `primary_suspect` survives set intersection in only **`140/381` (`36.7%`)** (`63.3%` eliminated!).
- By **Day 10** (`400/400` episodes): static `primary_suspect` survives in only **`93/400` (`23.3%`)** (`76.8%` eliminated!).

Once `primary_suspect` is absent from a single surfaced regular leak's `recipients`, any agent computing set intersections knows $P(\text{Mole} = \text{primary\_suspect}) = 0$ and ignores Days `5..18` of `v5_full9_cocktail` chatter. Proposal **P7.3** closes this exact gap while preserving Proposition 1.

---

## 4. Concrete Drop-In Proposals for Silas (`P7.1`, `P7.2`, `P7.3`)

All three proposals obey four engineering constraints: (1) when additive flags default to off/empty, `v1.4` frozen hashes (`a8f99c2537c91d72`) and RNG streams remain byte-identical; (2) strict conditional zero mole leakage $I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$ holds everywhere; (3) `SolverPolicy` requires zero heuristic tuning; and (4) offline `make reproduce` and Harbor sidecar builds require **zero live Gemini calls** and **zero judge-secret leakage**.

---

### Proposal P7.1: Zero-Leakage Multi-Day Focal Cascade (`V16SocialProvider` + Keyless Offline SHA-256 Cache)

#### Mechanism and Judge-Secret Decoupling Audit
Proposal **P7.1** wires `V16SocialProvider` (`v5_full9_cocktail`) into `canary/rules.py` and `canary/env.py` with one critical integrity fix caught in our code audit: in `canary/env.py` (line 322), `Env._facts(d)` currently passes `seed = w.world_seed`. On judge/held-out seeds (`900000+`), `w.world_seed = HMAC(secret, f"{tier}:{seed}")` varies across fresh per-process secrets (`_process_secret()`). In `V16SocialProvider`, `_init_episode_state` seeds from `facts.seed`, whereas `build_social_prompt` (`canary/social/gemini_chatter.py`) hashes `(company, day, doc_titles[:4], items)` via `canary/text/llm_cache.py:cache_key` (`SHA-256` over `[model, system, messages, None, 0, None]`).

To guarantee both **zero judge-secret dependency** and **100% deterministic offline cache hits**:
1. Seed `V16SocialProvider` from a **public structural digest** `pub_digest = sha256(f"{facts.tier}:{facts.company}:{emp_ids}:{day1_doc_ids}")[:16]` rather than raw `facts.seed` (`w.world_seed`), so social event scheduling depends solely on public world objects already visible via `list_employees` and `list_documents`, never exposing `w.world_seed` or `CANARY_WORLD_SECRET`.
2. Enforce `validate_social_message` (`FORBIDDEN_SUBJECT_PREFIXES` blocked, `Name (eXX)` + `SALIENCE_TERMS` in `body[:110]`, `DECOY_VOCAB` scrubbed) on both template drafts and SHA-256 cached Gemini rewrites (`data/gemini_cache/<sha256>.json`, `CANARY_OFFLINE=1`, `_assert_no_secrets`), falling back deterministically to the validated template message on any schema/lint miss or keyless fresh-secret judge run.

#### Code-Ready Spec (`TierParams`, `Env`, `V16SocialProvider`)

**1. `canary/rules.py` (additive field omitted at default `""` in `to_dict()`):**
```python
social_v16_variant: str = ""
social_v16_mode: str = "template"
```

**2. `canary/social/engine.py` (secret-free structural RNG seed + `CANARY_OFFLINE=1` fallback):**
```python
def public_episode_digest(variant: str, facts: PublicDayFacts) -> str:
    emp_sig = ",".join(f"{e.id}:{e.dept}:{e.role}" for e in facts.employees)
    doc_sig = ",".join(str(d.get("doc_id", "")) for d in _regular_docs(facts))
    raw = f"v16:{variant}:{facts.tier}:{facts.company}:{facts.decoy}:{emp_sig}:{doc_sig}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```
In `_maybe_gemini`: when `OfflineCacheMiss` is raised (e.g., fresh per-process secret on `make reproduce` without `GEMINI_API_KEY`), catch `OfflineCacheMiss` without incrementing `self.rejects` as a validation failure and return the validated deterministic `template` message, preserving 100% keyless reproducibility.

**3. `Env.instruction()` disclosure (calibrated, non-invertible):**
State concisely under `## Workplace communications`: *"Internal channels (`#general`, `#security-review`, `#cross-team`, department channels, email) include organic colleague discussions, unverified senior opinions, interpersonal disputes, and recall errors generated solely from public workplace roles and document distributions. Unlike leak-feed items, colleague chat carries zero privileged information about who the mole is (`LLR = 0`)."* Because true $I(\text{Social}; \text{Mole} \mid \text{PublicDayFacts}) = 0$, disclosing the truth gives `gemini-4-carbon` **zero** exclusion leverage (`LLR = 0.0000`, not `-0.5210`), while still testing whether 18 days of vivid multi-bias prose hijacks its attention, `search_messages`/`interview` budget, or candidate selection.

---

### Proposal P7.2: Public-Stress Othello Coupling (Social Cascade + Restriction -> `p_evasive_base`)

#### Research Justification and Exact Constant-Odds-Ratio Math
Across `v1.4` and `v1.5-candidate` (`hard` seeds `0-9`), `gemini-4-carbon` spent `70.0` and `51.0` actions per episode on `interview` (`SolverPolicy`: `0`). As established by Bond & DePaulo (2006) (*"people appear deceptive when motivated to be believed"*) and Kramer (1998) (paranoid cognition under evaluative scrutiny), an innocent employee who has been repeatedly named across `#general` / `#security-review` leak threads (`authority`, `bandwagon`, `recency`, `grudge`) or placed under access restriction (`restrict_access`) answers security interviews more guardedly than an unscrutinized colleague.

Proposal **P7.2** couples **closed-day (`day < self.day`) public `V16SocialProvider` target mentions** $m_{e,<d}$ and **public restriction status** $r_{e,d} = \mathbb{I}[e \in \text{restricted}_d]$ to innocent interview evasiveness $p_{\text{evasive\_base}}(e, d)$, while scaling mole evasiveness by the **constant baseline odds ratio** $\text{OR}_0$:

$$p_{\text{base}}(e, d) = \min\!\Big(p_{\text{cap}},\; p_0 + \delta_r \cdot r_{e,d} + \delta_m \cdot \min(m_{e,<d},\, m_{\max})\Big), \qquad \text{OR}_0 = \frac{p_0 \lambda_0 / (1 - p_0 \lambda_0)}{p_0 / (1 - p_0)}$$

$$P(\text{evasive} \mid e \neq \text{mole}, \mathcal{F}_d) = p_{\text{base}}(e, d), \qquad P(\text{evasive} \mid e = \text{mole}, \mathcal{F}_d) = \frac{\text{odds}_{\text{base}}(e, d) \cdot \text{OR}_0}{1 + \text{odds}_{\text{base}}(e, d) \cdot \text{OR}_0}$$

On `v1.4` `hard` ($p_0 = 0.20$, $\lambda_0 = \text{interview\_lr} = 1.20$), $\text{OR}_0 = \frac{0.24/0.76}{0.20/0.80} = \frac{24}{19} \approx 1.263158$. With calibrated parameters $\delta_r = 0.14$, $\delta_m = 0.06$, $m_{\max} = 4$, and $p_{\text{cap}} = 0.52$, Python verification across all public stress states confirms exact calibration invariance for `SolverPolicy` alongside strong Othello drift on uncalibrated interviewers:

| Public Scrutiny State `(r, m_<d)` | `P(evasive \| innocent)` | `P(evasive \| mole)` (`OR=24/19`) | `KL(Mole \|\| Inn.)` | Naive Flat-LR Drift on Innocent | Calibrated `SolverPolicy` Drift |
|---|---:|---:|---:|---:|---:|
| Calm unmentioned `(r=0, m=0)` | `0.200` | `0.240` | `0.00477` nats | `-0.00457` nats/iv (exonerates) | `-0.00457` nats/iv |
| Focal suspect Day 3 `(r=0, m=2)` | `0.320` | `0.373` | `0.00624` nats | **`+0.02346` nats/iv (false +LLR)** | `-0.00610` nats/iv |
| Focal suspect Day 6 `(r=0, m=4+)` | `0.440` | `0.498` | `0.00680` nats | **`+0.05150` nats/iv (false +LLR)** | `-0.00677` nats/iv |
| Restricted only `(r=1, m=0)` | `0.340` | `0.394` | `0.00640` nats | **`+0.02814` nats/iv (false +LLR)** | `-0.00627` nats/iv |
| Restricted + Focal `(r=1, m=4+)` | **`0.520`** | `0.578` | `0.00672` nats | **`+0.07019` nats/iv (Othello trap)** | `-0.00677` nats/iv |

Key properties verified from this table:
1. **Endogenous confirmation-bias loop:** In `v5_full9_cocktail`, `primary_suspect` accumulates $m_{e,<d} \ge 4$ social mentions by Day 5. An innocent `primary_suspect` then answers evasively **`44.0%`** of the time (`52.0%` if restricted) versus **`24.0%`** for an unmentioned, unrestricted mole, turning `gemini-4-carbon`'s habitual `50-70` interviews into self-reinforcing false incrimination (`+0.70` nats false log-odds across 10 interviews) unless it tracks public scrutiny!
2. **Zero restriction-for-SNR exploit & zero solver drift:** Constant-odds scaling keeps `KL` flat (`0.00477 -> 0.00680` nats, `127x` below one canary leak), and `SolverPolicy` performs `0` interviews (or updates with exact public `p_base(e, d)` in `belief.py`), incurring **zero** calibration drift.

#### Code-Ready Spec (`Env` & `canary/solver/belief.py`)
```python
def _p_evasive_base(self, emp: str) -> float:
    base = self.p.p_evasive_innocent
    if not self.p.social_stress_coupling:
        return base
    r_flag = 1 if emp in self._restricted else 0
    m_cnt = sum(
        1 for mid in self._msg_order
        if self._messages[mid]["day"] < self.day and self._messages[mid].get("social_target") == emp
    )
    raw = base + 0.14 * r_flag + 0.06 * min(m_cnt, 4)
    return min(0.52, raw)

def _p_evasive(self, emp: str) -> float:
    pb = self._p_evasive_base(emp)
    if emp != self._world.mole:
        return pb
    p0 = self.p.p_evasive_innocent
    pm0 = min(0.95, p0 * self.p.interview_lr)
    or0 = (pm0 / (1.0 - pm0)) / (p0 / (1.0 - p0))
    odds_m = (pb / (1.0 - pb)) * or0
    return odds_m / (1.0 + odds_m)
```
Expose `"social_target"` on social messages returned by `read_message` (and derivable from `Name (eXX)` in `body[:110]`), so public observability is 100% symmetric between `SolverPolicy` and MCP agents.

---

### Proposal P7.3: Plausible-Access Misforward and Dynamic Co-Recipient Confirmation Trap

#### Solving the `63.3%` Day-6 Set-Intersection Elimination Without Mole Leakage
As proved in Section 3.2, `V16SocialProvider`'s static Day-1 `primary_suspect` is eliminated by surfaced regular-document recipient intersections in **`41.9%`** of `hard` seeds by Day 4, **`63.3%`** (`241/381`) by Day 6, and **`76.8%`** (`307/400`) by Day 10. Real organizational confirmation cascades (Nickerson, 1998; Bikhchandani et al., 1992) and coordination slips (Kruger et al., 2005) coalesce around colleagues who **plausibly held the leaked files**.

Proposal **P7.3** combines two strictly public mechanisms so social threads remain forensically unfalsifiable by passive set-intersection throughout the episode:

1. **Dynamic Public Co-Recipient Re-Anchoring ($C_{\text{pub}}(d)$):** In `Env._facts(d)`, pass `extra = {"surfaced_regular_docs": tuple(f["doc_id"] for f in self._feed if f["surfaced_day"] <= d and not self._doc_by_id[f["doc_id"]]["is_canary"])}`. Let $C_{\text{pub}}(d)$ be the non-decoy intersection of `recipients` across all publicly surfaced regular leaks up to day $d$:
   $$C_{\text{pub}}(d) = \left(\bigcap_{q \in \text{SurfacedReg}_{\le d}} \text{Recipients}(q)\right) \setminus \{\text{decoy}\}$$
   On day $d$, `V16SocialProvider` sets the active focal target to `primary_suspect` if `primary_suspect in C_pub(d)`, else `secondary_suspect` if `secondary_suspect in C_pub(d)`, else a deterministic public draw `rng_reanchor.choice(sorted(C_pub(d)))` (locked until eliminated by a future surfaced regular leak), narrating the shift naturally as `"After yesterday's <leaked_doc> leak check narrowed the distribution list, <new_target> stands out..."`.
2. **Focal-Biased Accidental Misforwarding (`p_misforward = 0.15`):** When `Env._misforward(doc)` fires on a regular document (`p_misforward = 0.15`, seeded by `f"{world_seed}:fwd:{doc_id}"`), with probability `0.50` select the extra `forwarded_to` recipient from `{primary_suspect, secondary_suspect} \ doc["recipients"]` (computed purely from Day 1 public `planned_docs[1]`, zero mole dependence) before falling back to uniform non-recipients. That employee genuinely receives `doc` (`list_documents` shows `forwarded_to` and updated `recipients`), keeping early focal suspects inside recipient lists longer AND making `gen_misforward` chatter match real `list_documents` metadata!

#### Verified Simulation Results Across 400 `hard` Seeds (`0-399`)
- **Set-intersection survival jumps from `36.7%` / `23.3%` to `100.0%`:** Across all `381` episodes with surfaced regular leaks on Day 6 and all `400` episodes on Day 10, the active **P7.3** focal suspect satisfies `active_target in Recipients(q)` for **100.0%** (`381/381` on Day 6; `400/400` on Day 10) of surfaced regular leaks. Passive `check_leak_feed` + `list_documents` intersection can **never** dismiss the socially cascaded suspect; only active `plant_canary` partitioning separates the innocent co-recipient focal target from the mole.
- **Exact Zero Conditional Mole Leakage Preserved:** Because $C_{\text{pub}}(d)$ depends solely on public `surfaced_day <= d` regular leaks and public `recipients`, $\text{Mole} \to \text{PublicDayFacts}_{1:d} \to \text{active\_target}_d$ still obeys Proposition 1: $I(\text{active\_target}_d;\, \text{Mole} \mid \text{PublicDayFacts}_{1:d}) = 0$ identically. Empirically on Day 6 (`n = 381`), `active_target == world.mole` in `43/381 = 11.29%` of seeds versus $\mathbb{E}[1 / |C_{\text{pub}}(6)|] = 10.14\%$ ($z = +0.74$, $p = 0.46$): conditional on $C_{\text{pub}}(d)$, the focal suspect is uniformly distributed over the public consistent set, so `SolverPolicy`'s posterior (`social_loglik = 0`) remains **exact without modification**.

#### Code-Ready Spec (`Env._facts` & `canary/social/engine.py`)
```python
def resolve_plausible_focal(
    state: EpisodeSocialState,
    facts: PublicDayFacts,
    surfaced_reg_recipients: tuple[tuple[str, ...], ...],
) -> tuple[str, str]:
    non_decoy = {e.id for e in facts.employees if e.id != facts.decoy}
    c_pub = set(non_decoy)
    for rec in surfaced_reg_recipients:
        c_pub &= set(rec)
    if not c_pub:
        c_pub = non_decoy
    ordered = sorted(c_pub)
    if state.primary_suspect in c_pub:
        prim = state.primary_suspect
    elif state.secondary_suspect in c_pub:
        prim = state.secondary_suspect
    else:
        rng = random.Random(f"v16:reanchor:{facts.tier}:{facts.company}:{','.join(ordered)}")
        prim = rng.choice(ordered)
    rem = [x for x in ordered if x != prim]
    sec = state.secondary_suspect if state.secondary_suspect in rem else (rem[0] if rem else prim)
    return prim, sec
```

**`canary/mole/dsl.py` (`MoleStrategy` After-Hours Scapegoat Synergy - Zero Social Leakage):**
Without allowing the mole to touch `V16SocialProvider` (`I(Social; Mole | PublicDayFacts) = 0` stays strictly intact), add `"public_focal_peer"` to `FRAME_SELECTORS` (choosing the highest-mentioned non-mole colleague from public closed-day social messages). A mole running `focal_cascade_frame_v16` leaks wide-distribution documents while routing after-hours access-log framing (`Env._t_advance_day` step 5) onto the exact co-recipient colleague already targeted by **P7.1** social cascades and **P7.2** stress-induced evasiveness:
```json
{
  "name": "focal_cascade_frame_v16",
  "rules": [
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}
    },
    {
      "if": [["day", ">=", 2]],
      "then": {"leak": "most_recipients", "frame": "public_focal_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "decoy"}
}
```

---

## 5. Summary Reference Table

| Study | Venue & Year | Live Link / DOI | Key Quantitative / Theoretical Finding | Canary Bias & Proposal Mapping |
|---|---|---|---|---|
| Allport & Postman | *Holt* (1947) | https://archive.org/stream/psychology_of_rumor/psychology_of_rumor_djvu.txt | Rumour law `R ~ i x a`; leveling, sharpening, and schema assimilation | Grounds rumour intensity under `leak_damage` x `delay_choices` |
| Bordia & DiFonzo | *Soc. Psych. Q.* (2004) | https://doi.org/10.1177/019027250406700105 | `14` electronic rumour threads: anxiety-driven collective sensemaking, zero private truth | Grounds `I(Social; Mole \| PublicDayFacts) = 0` (**P7.1**) |
| Pennycook et al. | *JEP: General* (2018) | https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ | Single prior exposure raises perceived accuracy even on contested claims (`PMC6279465`) | Grounds multi-day repetition across Days `1..18` (`v5_full9_cocktail`) |
| Fein et al. | *JPSP* (1990) | https://doi.org/10.1037/0022-3514.58.5.753 | 3 studies: suspicion of ulterior motivation blocks naive correspondence bias | Explains why `gemini-4-carbon` inverted `v1.5` (`61% -> 108%` at Gate B) |
| Milgram | *JASP* (1963) | https://doi.org/10.1037/h0040525 | `26/40` (`65%`) full obedience to institutional authority directives | Grounds `gen_authority` (`manager`, `lead`, `controller`, `counsel`) |
| Lerner & Tetlock | *Psych. Bull.* (1999) | https://doi.org/10.1037/0033-2909.125.2.255 | Accountability to known authority views induces strategic attitude conformity | Grounds `gen_sycophancy` echoing senior unverified notes |
| Tversky & Kahneman | *Science* (1974) | https://doi.org/10.1126/science.185.4157.1124 | Representativeness, availability of salient instances, and insufficient anchor adjustment | Grounds `gen_anchoring` (Days 1-2) and `gen_recency` (Days 8-18) |
| Nickerson | *Rev. Gen. Psych.* (1998) | https://doi.org/10.1037/1089-2680.2.2.175 | Seeking and interpreting ambiguous cues partially toward an active hypothesis | Grounds `gen_confirmation` and **P7.2** / **P7.3** confirmation loops |
| Bikhchandani et al. | *J. Polit. Econ.* (1992) | https://doi.org/10.1086/261849 | Informational cascades produce fragile, correlated conformity ignoring private signals | Grounds `gen_bandwagon` cross-department `#cross-team` cascades |
| Andersson & Pearson | *Acad. Mgmt. Rev.* (1999) | https://doi.org/10.5465/amr.1999.2202131 | Low-intensity workplace slights escalate into tit-for-tat incivility spirals | Grounds stateful `gen_grudge` (`grudge_counts` escalation) |
| Kruger et al. | *JPSP* (2005) | https://doi.org/10.1037/0022-3514.89.6.925 | `5` studies: egocentric anchoring causes systematic email tone/routing misjudgment | Grounds `gen_misforward` and **P7.3** focal-biased `p_misforward = 0.15` |
| Roediger & McDermott | *JEP: LMC* (1995) | https://doi.org/10.1037/0278-7393.21.4.803 | DRM paradigm: `40%` (Exp. 1) and `55%` (Exp. 2) high-confidence false recall | Grounds `gen_false_memory` uncorroborated thread-access claims |
