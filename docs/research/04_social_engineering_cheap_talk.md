# 04. Social Engineering, Strategic Cheap Talk, and Rumor Credulity: Research Grounding for Canary

**Squad:** `research` (`canary-research-w4`)  
**Baseline commit:** `48034b07` (`origin/fr8/canary/research`, synced with `origin/justSilas@1bfb77dc`, `justSilas-v15@de9cc50e`, `staffai@b1967615`)  
**Scope:** Game-theoretic cheap talk, Bayesian persuasion, social-engineering pretexting/distraction, and workplace rumor psychology grounding Canary's message channels (`search_messages`, `read_message`), adversarial framing (`framing=True`), vocal decoys (`decoy=True`), the `v1.5-candidate` Gate B negative result, the `v1.6` zero-leakage social layer (`V16SocialProvider`), and drop-in proposals **P4.1** and **P4.2** for Silas (`canary/social/`, `canary/text/facts.py`, `canary/mole/dsl.py`, `canary/env.py`).

---

## 1. Executive Thesis: Why Unverified Workplace Chatter Is a Babbling Equilibrium for Bayesians and a Social-Engineering Trap for Heuristics

Economic game theory, usable-security scam analysis, and social-psychological rumor research converge on a sharp structural separation between **costless, unverified communication ("cheap talk")** and **costly, cryptographically or combinatorially watermarked experiments**:

1. **When sender incentives diverge from truth-revelation or speakers lack privileged state knowledge, costless messages carry zero equilibrium information.** In Crawford & Sobel's (1982) strategic communication framework, large preference divergence collapses equilibrium signaling into a **babbling equilibrium** where rational receivers ignore unverified messages (`I(Messages; State) = 0`), whereas diagnostic belief updating requires receiver-controlled experimental signal structures (Kamenica & Gentzkow, 2011), realized in Canary by watermarked `plant_canary` splits (`0.8654` nats per leaked 3-variant canary on `v1.4` hard).
2. **Naive and heuristic investigators fall prey to distraction, authority, urgency, and illusory-truth repetition.** Social-engineering attackers and workplace rumors exploit secondary-task attention limits (Kumaraguru et al., 2010), institutional pastiche (Blythe, Petrie & Clark, 2011), distraction/authority/herd/time-pressure lures (Stajano & Wilson, 2011), anxious collective sensemaking (`R ~ i x a`, Allport & Postman, 1947; Bordia & DiFonzo, 2004), single-exposure repetition fluency (Pennycook, Cannon & Rand, 2018), egocentric email tone misreading (Kruger et al., 2005), and default gossip credulity (Dores Cruz et al., 2021). In Canary, scripts that equate angry chat (`decoy=True`), spoofed `after_hours` logs (`framing=True`), or repeated accusations with guilt collapse under `wrong_accusation_score = -1.0`: `obvious_heuristic` scores `-0.973` on `v1.4` hard (`1.5%` accuracy), and `rumour_follower` scores `-0.986` on `medium` (`0.8%` accuracy) and `-0.995` on `hard` (`0.2%` accuracy) on fresh seeds `7000-7399` (`n = 400`).
3. **`v1.5-candidate` violated babbling-equilibrium independence (`61%` to `108%` at Gate B), whereas `V16SocialProvider` restores exact zero-leakage cheap talk.** On `justSilas-v15` (`de9cc50e`), `rumour_frame_share = 0.4` coupled message generation to `world.mole` (`P(rumoured | mole) = 0.01500 < P(rumoured | innocent) = 0.02526` under peer seeding, `LLR = -0.5210` nats; `27.67x` decoy concentration under default seeding) and disclosed the mole's seeding motive in `Env.instruction()`. Consistent with Fein, Hilton & Miller (1990), explicit ulterior-motive disclosure flipped `gemini-4-carbon` from credulity to active exclusion on `hard` seeds `0-9`, raising its score from `0.351` (`61%` of solver on `v1.4`) to `0.664` (`108%` of solver `0.615` on `v1.5-candidate`, `10/10` correct, `7242fc3b`). By contrast, `V16SocialProvider` (`staffai@b1967615`) selects `primary_suspect` and `secondary_suspect` strictly from Day 1 public regular-document recipient intersections (`I(Social; Mole | PublicDayFacts) = 0`, empirical `P(primary_suspect == mole) = 13/500 = 2.60%` vs uniform `1/39 = 2.56%`), enforcing exact Crawford-Sobel babbling equilibrium for `SolverPolicy` while deploying unlabeled multi-day social-engineering pretexts (`misforward`, `recency`, `anchoring`, `authority`, `bandwagon`) against uncalibrated LLMs.

Section 2 grounds every mechanism in ten HTTP-verified primary sources with verbatim quotes. Section 3 proves the exact information-theoretic properties of `v1.4`, `v1.5` Gate B, and `v1.6`. Section 4 specifies two zero-leakage upgrades: **P4.1 (Dynamic Plausible-Recipient `misforward` & `recency` Pretexting)**, which raises Day 12 pretext survival from `22.0%` to `100.0%` across `200` hard seeds, and **P4.2 (Mole Framing-Salience Alignment)**, which concentrates spoofed `after_hours` logs (`3.75x` mole rate) onto the public social focal suspect while keeping `SolverPolicy` at `89.0%` accuracy (`>= 85%` catchability bar).

---

## 2. Primary Literature Grounding (Verified Citations and Verbatim Quotes)

### 2.1 Cheap Talk, Partition Equilibria, and Babbling Equilibrium: Crawford & Sobel (1982)

- **Citation:** Crawford, V. P., & Sobel, J. (1982). Strategic Information Transmission. *Econometrica*, 50(6), 1431-1451.
- **Link / DOI:** https://doi.org/10.2307/1913390 | OpenAlex Metadata & Abstract: https://api.openalex.org/works/W2160003140
- **Model & Core Theorem:** Formalizes costless strategic communication ("cheap talk") between an informed Sender (`S`) with bias `b` and an uninformed Receiver (`R`) whose welfare depends on `R`'s action. All Bayesian Nash equilibria are coarse interval partitions; as `b` grows, the maximum partition size shrinks to `1` (the **babbling equilibrium**), where messages are statistically independent of private state and rational receivers update by zero nats.
- **Verbatim Quote (Abstract):**
> "We characterize the set of Bayesian Nash equilibria under standard assumptions, and show that equilibrium signaling always takes a strikingly simple form, in which S partitions the support of the (scalar) variable that represents his private information and introduces noise into his signal by reporting, in effect, only which element of the partition his observation actually lies in."
- **Verbatim Quote on Preference Alignment and Informativeness (Abstract):**
> "Since R bases his choice of action on rational expectations, this establishes a sense in which equilibrium signaling is more informative when agents' preferences are more similar."
- **Relevance to Canary:** In an insider-hunt game, the mole's preference over who gets accused (`b -> infinity` against self-incrimination) is maximally opposed to the investigator's, while innocent coworkers lack private knowledge of canary variants. Any unverified workplace accusation in `search_messages` must therefore sit at the zero-information babbling equilibrium (`LLR = 0`) for a rational Bayesian (`SolverPolicy`); if rules couple message targets negatively to mole identity (`v1.5-candidate`), communication exits babbling equilibrium and leaks exclusion signal.

### 2.2 Bayesian Persuasion and Signal-Structure Design: Kamenica & Gentzkow (2011)

- **Citation:** Kamenica, E., & Gentzkow, M. (2011). Bayesian Persuasion. *American Economic Review*, 101(6), 2590-2615.
- **Link / DOI:** https://doi.org/10.1257/aer.101.6.2590 | CrossRef Metadata & Abstract: https://api.crossref.org/works/10.1257/aer.101.6.2590
- **Model & Core Theorem:** Characterizes when commitment to a probabilistic signal structure induces a Bayesian receiver to change actions (concavification of the value function over posteriors), subject to Bayes-plausibility (`E[posterior] = prior`).
- **Verbatim Quote (Abstract):**
> "When is it possible for one person to persuade another to change her action? We consider a symmetric information model where a sender chooses a signal to reveal to a receiver, who then takes a noncontractible action that affects the welfare of both players. We derive necessary and sufficient conditions for the existence of a signal that strictly benefits the sender. We characterize sender-optimal signals."
- **Relevance to Canary:** Canary pits two opposing signal-design problems against each other. First, `plant_canary` lets the investigator design a high-KL signal structure (`max_variants = 3`, `fingerprint_accuracy = 0.95`) whose realizations split the posterior toward `1.0`. Second, adversarial framing (`framing=True`) and `V16SocialProvider` pretexts construct salient, plausible-looking signal realizations around an innocent co-holder, luring boundedly rational LLM agents across the accusation threshold `P > 1 / (1 + V)` prematurely while leaving an exact-Bayes receiver unmoved by unverified text.

### 2.3 Social-Engineering Scam Principles (Distraction, Authority, Herd, Time): Stajano & Wilson (2011)

- **Citation:** Stajano, F., & Wilson, P. (2011). Understanding Scam Victims: Seven Principles for Systems Security. *Communications of the ACM*, 54(3), 70-75 (full open-access technical report: University of Cambridge Computer Laboratory `UCAM-CL-TR-754`).
- **Link / DOI:** https://doi.org/10.1145/1897852.1897872 | Open-Access Full Text PDF: https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-754.pdf
- **Empirical Design:** Behavioral synthesis of documented real-world hustles and social-engineering cons recreated on unscripted targets, extracting seven recurring human-factors vulnerabilities exploited by attackers.
- **Verbatim Quote (CACM Abstract):**
> "Effective countermeasures depend on first understanding how users naturally fall victim to fraudsters."
- **Verbatim Quotes on Core Scam Principles (UCAM-CL-TR-754, Sections 3.1, 3.2, 3.3, and 3.7):**
> "While you are distracted by what retains your interest, hustlers can do anything to you and you won't notice."
> "Society trains people not to question authority. Hustlers exploit this \"suspension of suspiciousness\" to make you do what they want."
> "Even suspicious marks will let their guard down when everyone next to them appears to share the same risks."
> "When you are under time pressure to make an important choice, you use a different decision strategy. Hustlers steer you towards a strategy involving less reasoning."
- **Relevance to Canary:** Maps directly onto four core Canary deception channels: (1) **Distraction** -> vocal `decoy` complaints (`_ANGRY`), spoofed `after_hours` logs, and `misforward` routing notes divert the `8`-action/day budget away from `plant_canary`; (2) **Social Compliance (Authority)** -> `gen_authority` posts from `manager`/`lead`/`controller`/`counsel` roles; (3) **Herd** -> `gen_bandwagon` cross-department consensus notes; and (4) **Time** -> `gen_recency` urgent alerts interacting with daily `leak_damage = 0.05` and the `n_days = 21` horizon to trigger premature accusations.

### 2.4 Secondary-Task Attention Limits and False-Alarm Tradeoffs: Kumaraguru et al. (2010)

- **Citation:** Kumaraguru, P., Sheng, S., Acquisti, A., Cranor, L. F., & Hong, J. (2010). Teaching Johnny Not to Fall for Phish. *ACM Transactions on Internet Technology*, 10(2), Article 7, 1-31.
- **Link / DOI:** https://doi.org/10.1145/1754393.1754396 | CrossRef Metadata & Abstract: https://api.crossref.org/works/10.1145/1754393.1754396
- **Sample & Design:** Controlled laboratory and field user studies evaluating phishing susceptibility, trust decisions, and false-positive misclassification of benign emails.
- **Verbatim Quote (Abstract):**
> "We identified a number of challenges for end-user security education in general and anti-phishing education in particular: users are not motivated to learn about security; for most users, security is a secondary task; it is difficult to teach people to identify security threats without also increasing their tendency to misjudge nonthreats as threats."
- **Relevance to Canary:** Highlights the exact asymmetric error trap (`wrong_accusation_score = -1.0`) facing investigators scanning benign workplace traffic: heightened threat vigilance causes observers to misclassify benign anomalies (an accidental `misforward` draft cc or an innocent colleague's late-night work) as malicious exfiltration unless anchored to watermarked provenance.

### 2.5 Institutional Pastiche and Polished Pretext Credibility: Blythe, Petrie & Clark (2011)

- **Citation:** Blythe, M., Petrie, H., & Clark, J. A. (2011). F for Fake: Four Studies on How We Fall for Phish. *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '11)*, 3469-3478.
- **Link / DOI:** https://doi.org/10.1145/1978942.1979459 | OpenAlex Metadata & Abstract: https://api.openalex.org/works/W1974464813
- **Sample & Design:** Multi-method investigation across a phishing corpus archive, an online detection experiment (`N = 224`), qualitative interviews with blind screen-reader users, and literary genre analysis.
- **Verbatim Quote (Abstract):**
> "An online survey of 224 people finds that although phish are detected approximately 80% of the time, those with logos are significantly harder to detect. A qualitative interview study was undertaken to better understand the strategies used to identify phish. Blind users were selected because it was thought they may be more vulnerable to phishing attacks, however they demonstrated robust strategies for identifying phish based on careful reading of emails. Finally an analysis was undertaken of phish as a literary form. This identifies the main literary device employed as pastiche and draws on critical theory to consider why security based pastiche may be currently very persuasive."
- **Relevance to Canary:** Explains why `v1.5-candidate`'s crude synthetic tags (`subject: "rumour: e14"`, `subject: "unverified accusation: e07"`) failed to fool `gemini-4-carbon`, whereas `V16SocialProvider` (`biases.py`) bans explicit `FORBIDDEN_SUBJECT_PREFIXES` and employs **security-based institutional pastiche** (`"Fwd check: restricted doc draft recipients"`, `"Post-meeting leak assessment"`, `#security-review`), imitating authentic audit workflows so surface cues cannot separate cheap talk from real leads.

### 2.6 Multiplicative Rumor Law and Serial Distortion: Allport & Postman (1947)

- **Citation:** Allport, G. W., & Postman, L. (1947). *The Psychology of Rumor*. New York: Henry Holt and Company (1948 printing, Ch. 2, p. 33; Ch. 6-10).
- **Link / Full Text:** https://archive.org/stream/psychology_of_rumor/psychology_of_rumor_djvu.txt | Archive Record: https://archive.org/details/psychology_of_rumor
- **Theory & Experimental Synthesis:** Establishes the basic law of rumor intensity (`R ~ i x a`, importance times ambiguity) and the three serial-transmission distortions: **leveling** (omitting caveats), **sharpening** (magnifying salient details), and **assimilation** (warping reports toward pre-existing suspicions).
- **Verbatim Quotes (Full Text, Ch. 2, p. 33, and Ch. 6):**
> "THE two essential conditions of importance and ambiguity seem to be related to rumor transmission in a roughly quantitative manner. A formula for the intensity of rumor might be written as follows: R~ixa"
> "Leveling and sharpening, of course, do not occur haphazardly but take place in essential conformity with the past experience and present attitudes of the rumor spreaders."
- **Relevance to Canary:** On `v1.4` hard, every leak destroys `leak_damage = 0.05` of company value (high importance `i`) while surfacing only after `delay_choices = (2, 3)` days across `16`-recipient two-department distributions (high ambiguity `a`). Under `R ~ i x a`, employees naturally level away benign base rates (`16` co-holders) and sharpen coincidental details (`gen_anchoring`, `gen_confirmation`, `gen_false_memory`) onto a focal colleague.

### 2.7 Workplace Dread Rumors as Collective Sensemaking: Bordia & DiFonzo (2004)

- **Citation:** Bordia, P., & DiFonzo, N. (2004). Problem Solving in Social Interactions on the Internet: Rumor As Social Cognition. *Social Psychology Quarterly*, 67(1), 33-49.
- **Link / DOI:** https://doi.org/10.1177/019027250406700105 | CrossRef Metadata & Abstract: https://api.crossref.org/works/10.1177/019027250406700105
- **Sample & Design:** Longitudinal content and cluster analysis (Rumor Interaction Analysis System) of `14` naturally occurring rumor threads tracked across their lifecycle in electronic discussion groups.
- **Verbatim Quote (Abstract):**
> "Rumor discourse has been conceptualized as an attempt to reduce anxiety and uncertainty via a process of social sensemaking. Fourteen rumors transmitted on various Internet discussion groups were observed and content analyzed over the life of each rumor. With this (previously unavailable) more ecologically robust methodology, the intertwined threads of sensemaking and the gaining of interpretive control are clearly evident in the tapestry of rumor discourse."
- **Relevance to Canary:** Demonstrates that workplace rumor threads during a crisis are endogenous expressions of group anxiety and sensemaking (`hypothesizing`, `presentation of pseudo-evidence`), not independent witness observations of covert exfiltration. Counting chat accusations mistakes correlated social anxiety for independent Bayesian likelihood ratios.

### 2.8 Illusory Truth Repetition and Minimal Plausibility Boundary: Pennycook, Cannon & Rand (2018)

- **Citation:** Pennycook, G., Cannon, T. D., & Rand, D. G. (2018). Prior Exposure Increases Perceived Accuracy of Fake News. *Journal of Experimental Psychology: General*, 147(12), 1865-1880.
- **Link / DOI:** https://doi.org/10.1037/xge0000465 | Open-Access PMC Full Text: https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ (PMID: `30234315`)
- **Sample & Design:** Multi-study experimental tests of repeated exposure to fabricated headlines, measuring perceived accuracy within-session and at a one-week delay, with and without explicit fact-checker dispute warnings, plus extreme-implausibility boundary controls.
- **Verbatim Quotes (Abstract):**
> "Using actual fake-news headlines presented as they were seen on Facebook, we show that even a single exposure increases subsequent perceptions of accuracy, both within the same session and after a week. Moreover, this \"illusory truth effect\" for fake-news headlines occurs despite a low level of overall believability and even when the stories are labeled as contested by fact checkers or are inconsistent with the reader's political ideology."
> "These observations indicate that although extreme implausibility is a boundary condition of the illusory truth effect, only a small degree of potential plausibility is sufficient for repetition to increase perceived accuracy."
- **Relevance to Canary:** Directly grounds both `V16SocialProvider`'s multi-day repetition schedules (`v5_full9_cocktail` repeating a focal suspect across Days `1..18`, even with `"unverified"` caveats in `gen_authority`) and **Proposal P4.1**: once surfaced regular-document leaks make a static Day-1 suspect *provably impossible* (extreme implausibility: `0` overlap with leaked doc recipients), the illusory-truth effect vanishes; keeping the target inside the public co-holder set preserves the small plausibility needed for repetition fluency to bite.

### 2.9 Everyday Gossip Credulity and Reputation Updating: Dores Cruz et al. (2021)

- **Citation:** Dores Cruz, T. D., Thielmann, I., Columbus, S., Molho, C., Wu, J., Righetti, F., de Vries, R. E., Koster, N., Van Lange, P. A. M., Balliet, D., & Beersma, B. (2021). Gossip and Reputation in Everyday Life. *Philosophical Transactions of the Royal Society B*, 376(1838), 20200301.
- **Link / DOI:** https://doi.org/10.1098/rstb.2020.0301 | Open-Access PMC Full Text: https://pmc.ncbi.nlm.nih.gov/articles/PMC8487731/ (PMID: `34601995`)
- **Sample & Design:** Ten-day naturalistic experience-sampling study in a Dutch community cohort (`N = 309` participants, `n_gossip = 5,284` daily gossip events) measuring sender framing, receiver belief, and behavioral intentions.
- **Verbatim Quote (Abstract):**
> "In a Dutch community sample (N = 309), we sampled daily events in which people either sent or received gossip about a target over 10 days (ngossip = 5284). Gossip senders frequently shared information about targets' cooperativeness and did so in ways that minimize potential retaliation from targets. Receivers overwhelmingly believed gossip to be true and updated their evaluation of targets based on gossip."
- **Relevance to Canary:** Quantifies why human-pretrained LLMs exhibit a strong prior toward trusting third-party peer evaluations in Slack/email (`gen_confirmation`, `gen_sycophancy`, `gen_grudge`) and why senders hedge accusations (`"Not saying it's X for sure"`, `"unverified view"`) to minimize social retaliation while still shifting receiver beliefs.

### 2.10 Egocentric Email Misreading vs Ulterior-Motive Suspicion: Kruger et al. (2005) and Fein, Hilton & Miller (1990)

- **Citation 1 (Email Egocentrism):** Kruger, J., Epley, N., Parker, J., & Ng, Z.-W. (2005). Egocentrism Over E-Mail: Can We Communicate as Well as We Think? *Journal of Personality and Social Psychology*, 89(6), 925-936. DOI: https://doi.org/10.1037/0022-3514.89.6.925 | OpenAlex Abstract: https://api.openalex.org/works/W2155644471 (PMID: `16393025`)
- **Citation 2 (Ulterior-Motive Suspicion):** Fein, S., Hilton, J. L., & Miller, D. T. (1990). Suspicion of Ulterior Motivation and the Correspondence Bias. *Journal of Personality and Social Psychology*, 58(5), 753-764. DOI: https://doi.org/10.1037/0022-3514.58.5.753 | OpenAlex Abstract: https://api.openalex.org/works/W1972891856 (PMID: `2348368`)
- **Verbatim Quote from Kruger et al. (2005) (Abstract):**
> "Without the benefit of paralinguistic cues such as gesture, emphasis, and intonation, it can be difficult to convey emotion and tone over electronic mail (e-mail). Five experiments suggest that this limitation is often underappreciated, such that people tend to believe that they can communicate over e-mail more effectively than they actually can. Studies 4 and 5 further suggest that this overconfidence is born of egocentrism, the inherent difficulty of detaching oneself from one's own perspective when evaluating the perspective of someone else."
- **Verbatim Quote from Fein, Hilton & Miller (1990) (Abstract):**
> "Three studies examined the hypothesis that when perceivers learn of the existence of multiple, plausibly rival motives for an actor's behavior, they are less likely to fall prey to the correspondence bias than when they learn of the existence of situational factors that may have constrained the actor's behavior."
- **Relevance to Canary:** Together, these two studies explain both sides of Canary's text layer. Under Kruger et al. (2005), mole-hunting readers over-interpret blunt or frustrated text (`_ANGRY` decoy messages, `gen_grudge` disputes) through their own suspicious frame. Conversely, Fein, Hilton & Miller (1990) explain the `v1.5-candidate` Gate B reversal: once `Env._social_instruction()` explicitly told `gemini-4-carbon` that `40%` of rumors were planted by the mole with an ulterior framing motive against an innocent colleague, suspicion of ulterior motivation overrode gossip credulity and turned rumor frequency into an exclusion heuristic (`61%` -> `108%`).

---

## 3. Quantitative Game-Theoretic Mapping to Canary `v1.4`, `v1.5` Gate B, and `v1.6`

### 3.1 `v1.4` Pure Cheap Talk (`PublicDayFacts`) and Adversarial Framing (`framing=True`)

In frozen `TIERS_VERSION = "v1.4"` (`canary/rules.py`, `canary/text/facts.py`, `canary/env.py`), internal messages are strictly **zero-information cheap talk** with respect to hidden mole identity:

1. **Zero mutual information by construction (`I(Messages; Mole | PublicDayFacts) = 0`):** `Env._facts(d)` constructs `PublicDayFacts(tier, seed, day, company, employees, docs, decoy, decoy_mood, restricted)` without `self._world.mole` or `self._leaked`. `TemplateProvider.day_messages` (`canary/text/template.py`) seeds its local PRNG from `f"text:{facts.tier}:{facts.seed}:{facts.day}"`, emitting doc-recipient emails (`_DOC_MAIL`), angry decoy complaints (`_ANGRY`), and office chatter (`_CHATTER`). Verified empirically by `canary/redteam/text_probe.py` (`docs/EXPLOITS.md`, `Text leak` history row): on `medium` (`k = 2` interviews/employee + `<= 3` messages/day), exact Bayesian `fair_bar("medium", 2) = 0.07372` (`7.37%` vs `5.00%` chance; `hard` `fair_bar("hard", 1) = 0.03000` vs `2.50%` chance), and the `200`-seed `stub` probe hits `14 / 200 = 7.00%` (`p = 0.62` vs `fair_bar`, `openai:gpt-4o-mini` `0 / 50 = 0.0%`), confirming zero text leakage.
2. **Adversarial `after_hours` log spoofing (`framing=True`, `decoy=True`):** On `v1.4` hard (`N = 40`, `log_rate_benign = 1.0`, `log_rate_mole = 1.0`, `p_after_hours_benign = 0.10`, `p_after_hours_mole = 0.30`, `framing_rate = 2.0`, `framing_decoy_share = 0.5`), the mole's genuine `after_hours` rate is `0.3000`/day, whereas the innocent `decoy` receives `0.10 + 2.0 * 0.5 = 1.1000` `after_hours` accesses/day (**`3.67x` higher than the mole**; `0.8500` vs `0.1725` or **`4.93x`** on `medium`), and each plain innocent receives `0.10 + 1.0 / 38 = 0.12632`/day (daily Poisson `KL(Mole || PlainInnocent) = 0.10990` nats on `hard`, `0.00638` nats on `medium`, vs `0.86539` nats for one leaked 3-variant canary).
3. **Empirical distraction cost on `v1.4` hard (`seeds 0-29`, `n = 30`):** Replaying `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl` confirms `gemini-4-carbon` spends `4.23` `search_messages`, `0.17` `read_message`, `12.27` `read_access_logs`, and `68.03` `interview` calls per episode (`84.70` noisy/cheap-talk actions vs `8.50` `plant_canary` calls, mean score `0.3223`, `65%` of solver raw / `72%` luck-adjusted), whereas `SolverPolicy` spends `0` message calls and `0` interviews (`14.1` canaries, mean score `0.499`).

### 3.2 `v1.5-candidate` Gate B Forensics: Violation of Babbling-Equilibrium Independence (`61%` -> `108%`)

On candidate branch `justSilas-v15` (`de9cc50e`, `TIERS_V15`: `rumour_rate = 2.0`, `rumour_frame_share = 0.4`, `grudge_pairs = 2`, `grudge_rate = 0.5`, `authority_day = 3`, `p_misforward = 0.15`), `Env._social_events` broke Crawford-Sobel babbling-equilibrium independence by routing `s = 0.4` of rumors and the Day 3 authority post through `seed_rumour_target(sel, MoleView(..., peers = ids \ {mole}))`, which **never names the mole**:

- **Negative mole LLR under peer/unknown-decoy seeding (`canary/solver/belief.py:social_loglik`):** Marginalizing over speaker `a != b` in an `N`-employee tier (`s = 0.4`), the per-rumor target probabilities are:
  $$P(\text{target} = b \mid \text{mole} = b) = \frac{1 - s}{N}, \qquad P(\text{target} = b \mid \text{mole} \neq b) = \frac{1 - s}{N} + \frac{s}{N - 1}$$
  On `hard` (`N = 40`), $P(\text{target} = b \mid \text{mole} = b) = 0.015000 < P(\text{target} = b \mid \text{mole} \neq b) = 0.025256$, yielding a **negative log-likelihood ratio** $\text{LLR}_{\text{rumour}}(b) = \ln(0.015000 / 0.025256) = \mathbf{-0.52103\text{ nats}}$ per rumor (`-0.53166` nats on `medium`, `N = 20`). Under `seed_rumour = "default"` (`decoy`), `P(target = decoy) = 0.4 + 0.6/40 = 0.4150` (**`27.67x`** the mole's `0.0150` rate, `17.43` expected tagged `subject: "rumour: <decoy>"` posts per 21-day episode), instantly spotlighting the guaranteed-innocent decoy on Day 1.
- **Empirical Gate B divergence (`7242fc3b` & `results/fresh_table_v1.5-candidate.md`):** On fresh seeds `7000-7399` (`n = 400`), scripted `rumour_follower` fell into Dores Cruz et al.'s (2021) gossip-credulity trap (`-0.986` on `medium`, `-0.995` on `hard`). Conversely, on `hard` dev seeds `0-9` (`7242fc3b`), `gemini-4-carbon` read the disclosed ulterior seeding rule (Fein, Hilton & Miller, 1990), cut `interview` calls from `70.00` (`v1.4` seeds `0-9`) to `51.00`/episode and `read_access_logs` from `13.40` to `8.50`/episode, accused at mean day `9.8` with `10/10` accuracy (`mean P = 0.94`), and jumped from **`0.3510` (`61%` of solver on `v1.4`) to `0.6640` (`108%` of solver `0.615` on `v1.5-candidate`, luck-adjusted `98%`)**.

### 3.3 `v1.6` (`V16SocialProvider`) Babbling-Equilibrium Restoration and Pretext Audit

`V16SocialProvider` (`origin/fr8/canary/staffai:canary/social/engine.py` & `biases.py`, commit `b1967615`) eliminates hidden-state coupling by initializing `EpisodeSocialState` solely from Day 1 `PublicDayFacts` (`rng = random.Random(f"v16:{variant}:{facts.tier}:{facts.seed}:init")`), drawing `primary_suspect` from the Day 1 non-decoy regular-document recipient intersection `inter = (r0 & r1) \ {decoy}` (combinatorial overlap probability $1 - \binom{3}{2}/\binom{5}{2} = 0.700$ on 5-department `hard`) and `secondary_suspect` from `(r0 | r1) \ {decoy, primary_suspect}`.

| Social Layer / Regime | Hidden Truth Input | `I(Social; Mole \| Public)` | Single-Event Mole LLR | `P(focal == mole)` (`hard`) | Day 12 Leak-Consistent Survival | Empirical Effect (`hard`) |
|---|---|---:|---:|---:|---:|---|
| `v1.4` `TemplateProvider` | None (`PublicDayFacts`) | `0.0000` nats | `0.0000` nats | N/A (`decoy` = `0%`) | N/A | `text_probe` `7.0% <= 7.4%` fair bar; Gemini `65%` raw (`n=30`) |
| `v1.5-candidate` (`justSilas-v15`) | `world.mole` (`MoleView.peers`) | `> 0` (peer/unid. decoy) | `-0.5210` nats | `1.50%` vs `2.53%` inn (`41.5%` decoy) | Static decoy (`0%` mole) | `rumour_follower = -0.995`; Gemini **`108%`** (`n=10`, dropped) |
| `v1.6` `V16SocialProvider` (`v5`) | None (`PublicDayFacts`) | **`0.0000` nats** | **`0.0000` nats** | **`2.60%` (`13/500`)** vs `1/39 = 2.56%` | `22.0%` (`44/200` static Day-1) | `45.0` unlabeled pastiche msgs/ep; exact solver invariance |
| **`v1.6` + Proposals P4.1 & P4.2** | `PublicDayFacts` (`P4.1`); public chat -> `MoleView` (`P4.2`) | **`0.0000` nats** (`P4.1` social) | **`0.0000` nats** (social) / `+3.84` nats naive `6d` log drift | `11.5%` vs `E[1/\|C_reg\|] = 13.0%` (Day 12) | **`100.0%` (`200/200`)** | `LogsMinusDecoy` focal trap `0% -> 42%`; Solver **`89.0%` acc** |

The deterministic Python proof below (verified with `/tmp/fleet-silas/shared/agent-arena-venv/bin/python` across `500` `v1.4`/`v1.6` hard worlds and `200` full `Env("hard", seed)` trajectories) confirms all three game-theoretic invariants:

```python
import math
import random
from canary.rules import TIERS
from canary.world import generate_world

p_hard = TIERS["hard"]
n_emp, s_v15 = p_hard.n_employees, 0.4
p_rum_mole = (1.0 - s_v15) / n_emp
p_rum_inn = (1.0 - s_v15) / n_emp + s_v15 / (n_emp - 1)
llr_v15 = math.log(p_rum_mole / p_rum_inn)
assert round(llr_v15, 5) == -0.52103

mole_hits = 0
for seed in range(500):
    w = generate_world("hard", seed, p_hard)
    rng = random.Random(f"v16:v5_full9_cocktail:hard:{w.world_seed}:init")
    non_decoy = {e.id for e in w.employees if e.id != w.decoy}
    r0 = set(w.planned_docs[1][0]["recipients"]) & non_decoy
    r1 = set(w.planned_docs[1][1]["recipients"]) & non_decoy
    pool = sorted(r0 & r1) or sorted(r0 | r1)
    primary = rng.choice(pool)
    mole_hits += int(primary == w.mole)
assert mole_hits == 13
```

Across `500` hard seeds (`0-499`), `primary_suspect == mole` in `13 / 500 = 2.60%` (two-sided binomial `p = 0.888` vs exact non-decoy prior `1 / 39 = 2.564%`), `secondary_suspect == mole` in `15 / 500 = 3.00%`, and `primary_suspect == decoy` in `0 / 500 = 0.00%`.

---

## 4. Concrete Proposals for Silas (`v1.5` / `v1.6` Bias Layer and Mole)

Both proposals preserve `v1.4` frozen hashes (`a8f99c2537c91d72`) when disabled, enforce `I(Social; Mole | PublicHistory) = 0`, add zero `#`-prefixed subject giveaways, and preserve `SolverPolicy >= 85%` catchability (`CONTRACT` Section 7).

---

### Proposal P4.1: Zero-Leakage Plausible-Recipient `misforward` and `recency` Pretexting Policy

#### Research Justification
Pennycook, Cannon & Rand (2018) establish that illusory-truth repetition breaks down under **extreme implausibility**: once a statement is provably impossible, repeated exposure no longer inflates perceived accuracy, whereas *"only a small degree of potential plausibility is sufficient for repetition to increase perceived accuracy."* In current `V16SocialProvider` (`engine.py`), `primary_suspect` is frozen on Day 1. Across `200` simulated `Env("hard", seed)` episodes (`seeds 0-199`), surfaced regular-document leaks narrow the public non-decoy co-holder intersection $C_{\text{reg}}(d)$ to a mean of `9.57` employees by Day 8 and `8.46` employees by Day 12, **eliminating the static Day-1 `primary_suspect` in `74.0%` of episodes by Day 8 (`52 / 200 = 26.0%` alive) and `78.0%` by Day 12 (`44 / 200 = 22.0%` alive)**. Consequently, `78%` of late-game `recency` (Days `8-18` in `v5_full9_cocktail`) and `misforward` lures target a colleague whom an LLM can rule out via simple set intersection.

Proposal **P4.1** upgrades `misforward` (Blythe, Petrie & Clark, 2011 pastiche) and `recency` (Stajano & Wilson, 2011 Time + Distraction principles) to condition dynamically on the **publicly surfaced regular-document recipient intersection** $C_{\text{reg}}(d)$, keeping `100.0%` (`200 / 200`) of pretexts consistent with every surfaced regular-document leak while leaking **zero bits** beyond public history.

#### Exact Mathematical Specification
Let $\text{Feed}_{\le d}^{\text{reg}} = \{f \in \text{Feed} : f.\text{surfaced\_day} \le d \;\land\; \neg f.\text{is\_canary}\}$ denote the public set of regular documents surfaced on or before day $d$, with sequential non-empty intersection:

$$C_0(d) = \{e \in \text{Employees} : e \neq \text{decoy}\}, \qquad C_k(d) = \begin{cases} C_{k-1}(d) \cap \text{Recipients}(d_k) & \text{if } C_{k-1}(d) \cap \text{Recipients}(d_k) \neq \varnothing \\ C_{k-1}(d) & \text{otherwise} \end{cases}$$

Define the active plausible pretext pool $P_d = (C_m(d) \setminus \text{restricted}_d)$ if non-empty, else $C_m(d)$. The **P4.1** pretext target $T_{\text{P4.1}}(d)$ is selected deterministically via $u_d \sim \text{RNG}(\texttt{"p41:"} \| \text{tier} \| \text{seed} \| d)$:

$$T_{\text{P4.1}}(d) = \begin{cases} \text{primary\_suspect} & \text{if } \text{primary\_suspect} \in P_d \\ \text{secondary\_suspect} & \text{if } \text{primary\_suspect} \notin P_d \;\land\; \text{secondary\_suspect} \in P_d \\ \text{UniformChoice}(P_d;\, u_d) & \text{otherwise} \end{cases}$$

Because $\text{Feed}_{\le d}^{\text{reg}}$, $\text{Recipients}(\cdot)$, $\text{decoy}$, and $\text{restricted}_d$ are measurable with respect to public history $\mathcal{F}_d^{\text{pub}}$ (and excludes private agent-planted canary assignments), conditional mutual information vanishes identically:

$$I\big(T_{\text{P4.1}}(d);\; \text{Mole} \;\big|\; \mathcal{F}_d^{\text{pub}}\big) = 0, \qquad \text{LLR}_{\text{Solver}}\big(\text{Social}_d(T_{\text{P4.1}}(d))\big) \equiv 0$$

Empirically verified across `200` hard episodes (`seeds 0-199`), $P(T_{\text{P4.1}}(d) = \text{mole})$ equals `0.130` at Day 8 (vs $\mathbb{E}[1/|C_{\text{reg}}(8)|] = 0.121$) and `0.115` at Day 12 (vs $\mathbb{E}[1/|C_{\text{reg}}(12)|] = 0.130$), confirming zero excess mole correlation while lifting pretext plausibility from `22.0%` to **`100.0%`**.

#### Code-Ready Spec (`PublicDayFacts`, `V16SocialProvider`, `SolverPolicy`)

1. **`canary/env.py` (`Env._facts`) & `canary/text/facts.py`:** Pass public surfaced regular-doc recipients inside `facts.extra["surfaced_reg_docs"]` (preserving frozen `PublicDayFacts` positional signature):
```python
surfaced_reg = tuple(
    {"doc_id": f["doc_id"], "recipients": list(self._doc_by_id[f["doc_id"]]["recipients"])}
    for f in self._feed
    if f["surfaced_day"] <= d and not self._doc_by_id[f["doc_id"]]["is_canary"]
)
```
2. **`canary/social/biases.py` (`plausible_pretext_target` for `gen_misforward` and `gen_recency`):**
```python
def plausible_pretext_target(ctx: SocialDayContext) -> EmployeeFacts:
    pool = [e.id for e in ctx.facts.employees if e.id != ctx.facts.decoy]
    for item in ctx.facts.extra.get("surfaced_reg_docs", ()):
        rec = set(item.get("recipients", ()))
        inter = [eid for eid in pool if eid in rec]
        if inter:
            pool = inter
    unrest = [eid for eid in pool if eid not in set(ctx.facts.restricted)]
    active = unrest if unrest else pool
    if ctx.primary_suspect in active:
        chosen = ctx.primary_suspect
    elif ctx.secondary_suspect in active:
        chosen = ctx.secondary_suspect
    else:
        prng = random.Random(f"p41:{ctx.facts.tier}:{ctx.facts.seed}:{ctx.facts.day}")
        chosen = prng.choice(active)
    return ctx.by_id[chosen]
```
3. **`canary/solver/belief.py`:** Zero changes required; `SolverPolicy` ignores unverified message bodies and incurs `0.0000` nats distortion.

---

### Proposal P4.2: Mole Framing-Salience Alignment (Multi-Channel Scapegoat Convergence)

#### Research Justification
Gate B proved that frontier LLMs discount isolated chat rumors when ulterior motives are salient (Fein, Hilton & Miller, 1990), yet `v1.3` and `v1.4` failure forensics (`docs/reports/gap.md`, Codex seed 0 and seed 4; `docs/reports/failure_analysis_v1.4.md`) show frontier agents repeatedly succumb when **multiple seemingly independent channels converge on a leak-consistent suspect** (Kamenica & Gentzkow, 2011; Stajano & Wilson, 2011 Distraction + Herd principles). In `v1.4`, `MoleStrategy` (`canary/mole/dsl.py`) restricts `FRAME_SELECTORS` to `("decoy", "most_restricted_peer", "random_peer", "none")`: framing `decoy` fails against LLMs that filter `_ANGRY` senders, while `random_peer` scatters fake `after_hours` accesses thinly across `38` colleagues.

Proposal **P4.2** aligns mole log-framing with public social salience **without violating the `PublicDayFacts` firewall**:
- **Strict one-way causal flow (`Public Messages -> MoleView`, never `Mole -> Social`):** Because the mole is an employee receiving company-wide `#general` and `#security-review` messages, `Env._mole_view(d)` extracts `social_focal_peers` (non-decoy peers ordered by closed-day `< d` message mentions) and exposes `"social_focal_peer"` in `FRAME_SELECTORS`. `V16SocialProvider` still never sees `world.mole` (`I(Social; Mole | PublicDayFacts) = 0`).
- **Verified quantitative impact (`100` hard seeds `0-99`):** On `hard`, executing `frame: "social_focal_peer"` on days `d >= 2` adds `+1.000` `after_hours = True` access/day onto the exact plausible co-holder named in `V16SocialProvider`, raising that innocent suspect's `after_hours` rate from `0.1263`/day to **`1.1263`/day (`3.75x` the true mole's `0.3000`/day)**. For an investigator using unadjusted `behaviour_llr`, expected false log-odds against `social_focal_peer` reach **`+3.8436` nats** by Day 6 (`E[n_ah] = 7`), **`+5.7820` nats** by Day 10 (`E[n_ah] = 11`), and **`+8.4050` nats** by Day 14 (`E[n_ah] = 16`). Across `100` simulated hard seeds (`0-99`), decoy-filtering `LogsMinusDecoy` (`wait = 5`) jumps from **`0%` to `42.0%`** accusing the innocent `social_focal_peer` (`LogsOnly` at `wait = 9`: **`1.0%` to `48.0%`**), while `SolverPolicy` (driven by 3-variant `plant_canary` splits and `behaviour_temper = 0.3`) achieves **`0.4840` mean score and `89.0%` accuracy** (strictly above the `>= 85%` catchability constraint in `CONTRACT` Section 7).

#### Code-Ready Spec (`MoleView`, `MoleStrategy` DSL, and Strategy JSON)

1. **`canary/mole/dsl.py` (`FEATURES`, `FRAME_SELECTORS`, `MoleView`, `_select_frame`):**
```python
FEATURES = (
    "day", "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
    "recent_low_recipient_docs", "n_leakable", "n_docs_held",
    "min_recipient_count", "max_recipient_count", "newest_doc_age_days",
    "n_social_focal_peers",
)
FRAME_SELECTORS = ("decoy", "most_restricted_peer", "social_focal_peer", "random_peer", "none")

def select_social_focal_frame(sel: str, v: MoleView, rng: random.Random) -> str | None:
    if sel == "social_focal_peer":
        return v.social_focal_peers[0] if v.social_focal_peers else None
    return _select_frame(sel, v, rng)
```
In `Env._mole_view(d)`, populate `social_focal_peers` by counting employee IDs `(e\d\d)` mentioned in `self._messages` with `msg["day"] < d`, excluding `w.mole` and `w.decoy`, sorted by `(-mention_count, emp_id)`.

2. **Drop-in `MoleStrategy` JSON (`salience_convergence_v16` for `hard_forge` / `v1.6`):**
```json
{
  "name": "salience_convergence_v16",
  "rules": [
    {
      "if": [["day", ">=", 2], ["n_social_focal_peers", ">=", 1], ["max_recipient_count", ">=", 12]],
      "then": {"leak": "most_recipients", "frame": "social_focal_peer"}
    },
    {
      "if": [["day", ">=", 2], ["n_social_focal_peers", ">=", 1]],
      "then": {"leak": "random_seeded", "frame": "social_focal_peer"}
    },
    {
      "if": [["n_restricted_colleagues", ">=", 1]],
      "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}
    }
  ],
  "default": {"leak": "random_seeded", "frame": "decoy"}
}
```

---

## 5. Summary Reference Table

| Study | Venue & Year | Live Link / DOI | Key Quantitative / Theoretical Finding | Canary Mapping |
|---|---|---|---|---|
| Crawford & Sobel | *Econometrica* (1982) | https://doi.org/10.2307/1913390 | Divergent sender-receiver preferences collapse cheap talk to coarse partitions / zero-info babbling equilibrium | Proves unverified chat must have `LLR = 0` (`SolverPolicy`) and why `v1.5` (`s=0.4`) broke babbling equilibrium |
| Kamenica & Gentzkow | *AER* (2011) | https://doi.org/10.1257/aer.101.6.2590 | Necessary & sufficient conditions for persuasive signal structures (`E[posterior] = prior`, concavification) | Contrasts investigator `plant_canary` (`0.865` nats) against adversarial **P4.2** multi-channel posterior skew |
| Stajano & Wilson | *Commun. ACM* (2011) | https://doi.org/10.1145/1897852.1897872 | Seven scam principles: Distraction, Social Compliance (authority), Herd, and Time pressure steer targets to low-reasoning choices | Maps 1-to-1 onto `decoy`/`misforward` (Distraction), `authority`, `bandwagon` (Herd), and `recency` + `V` bleed (Time) |
| Kumaraguru et al. | *ACM TOIT* (2010) | https://doi.org/10.1145/1754393.1754396 | Security is a secondary task; threat sensitivity inflates false positives on benign messages | Explains false accusations (`-1.0`) on benign `misforward` cc routing and benign `after_hours` work |
| Blythe, Petrie & Clark | *CHI* (2011) | https://doi.org/10.1145/1978942.1979459 | `N = 224` survey + archive + interviews: institutional pastiche/logos defeat surface heuristics; careful reading wins | Grounds `V16SocialProvider` banning `rumour:` tags in favor of realistic `#security-review` / `Fwd check:` pastiche |
| Allport & Postman | *Henry Holt* (1947) | https://archive.org/details/psychology_of_rumor | Multiplicative rumor law `R ~ i x a`; serial leveling, sharpening, and assimilation toward pre-existing attitudes | High `leak_damage` (`i`) x `delay_choices = (2, 3)` (`a`) drives leveling of `16`-holder base rates in `anchoring` |
| Bordia & DiFonzo | *Soc. Psych. Quart.* (2004) | https://doi.org/10.1177/019027250406700105 | `14` internet rumor lifecycles: dread rumors act as anxious collective sensemaking, not independent witness data | Explains why counting chat threads (`rumour_follower = -0.995` hard) conflates shared anxiety with independent evidence |
| Pennycook et al. | *JEP: General* (2018) | https://pmc.ncbi.nlm.nih.gov/articles/PMC6279465/ | Single prior exposure boosts perceived accuracy even when contested, provided minimal plausibility holds | Grounds multi-day `confirmation`/`authority` schedules and **P4.1** dynamic leak-consistent target plausibility (`22% -> 100%`) |
| Dores Cruz et al. | *Phil. Trans. R. Soc. B* (2021) | https://pmc.ncbi.nlm.nih.gov/articles/PMC8487731/ | `N = 309`, `5,284` daily gossip events: senders hedge retaliation risk; receivers overwhelmingly believe gossip | Grounds hedged accusation templates and human-pretrained LLM susceptibility to peer consensus (`sycophancy`, `bandwagon`) |
| Kruger et al. | *JPSP* (2005) | https://doi.org/10.1037/0022-3514.89.6.925 | `5` studies: egocentric anchoring over email causes systematic tone/intent misreading without paralinguistic cues | Explains why blunt `_ANGRY` decoy messages and `grudge` threads are misread as insider malice |
| Fein, Hilton & Miller | *JPSP* (1990) | https://doi.org/10.1037/0022-3514.58.5.753 | `3` studies: suspicion of ulterior motivation blocks face-value correspondence bias | Explains `v1.5-candidate` Gate B reversal (`61% -> 108%`) once `instruction()` disclosed `rumour_frame_share = 0.4` |
