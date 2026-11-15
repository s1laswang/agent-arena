# Instruction audit by gemini-4-carbon (one pass)

Generated 2026-11-14T17:03:48+00:00 by `scripts/instruction_audit.py`. Input: Harbor preface + Env.instruction() for easy/medium/hard + tools_spec (23696 chars). Usage: 7132 in / 6062 out tokens, cost_usd 0.074884, thinking low, finish {'FinishReason.STOP': 1}. The model's claims are checked against the code in docs/DIFFICULTY.md.

---

Here is the audit of the task statement across all three tiers and the MCP tool definitions.

---

### Finding 1: Clearance levels (`access_constraints`) on regular documents are completely undocumented
- **ID:** F1
- **Category:** 2. Hidden information / 4. Broken or inconsistent tools
- **Tier(s):** Hard (and Exact parameters of Easy/Medium)
- **Exact quote:** 
  - Hard tier, Canaries: `"Each employee has a clearance level (1 to 3). Canaries are level 1, so every employee may receive one."`
  - Hard tier, Documents: `"0% of documents go to everyone in one department. The other 100% go to everyone in two departments."`
  - Hard tier, Exact parameters: `"access_constraints: on"`, `"canary_level: 1"`
- **Why it matters for a strong agent:** `access_constraints: on` is enabled in the hard tier, and `list_employees` returns `clearance` in the hard tier. Yet the "Documents" section still claims that 100% of documents go to *everyone* in two departments! If regular documents have clearance levels (1 to 3) that filter out lower-clearance employees in those departments—or if clearance constrains something else—the prose directly contradicts or omits it. Furthermore, if `list_documents` does not explicitly list every recipient ID (which is itself undocumented, see F6) and the agent infers recipients from department + clearance, the contradiction makes inference impossible. Even if `list_documents` shows recipients, the mole's DSL depends on document recipient counts, and knowing how clearance affects recipient distribution matters for planning.
- **Severity:** High
- **Suggested rewording:** In the Hard tier's **Documents** section, explicitly state how clearance levels work, e.g.: `"Each new regular document is assigned a clearance level (1, 2, or 3, with probabilities ...). It goes to every unrestricted employee in two randomly chosen departments whose clearance level is at least the document's level."`

---

### Finding 2: Mole DSL leaks vs. "Careful Mole" vs. `p_leak` — severe contradiction and ambiguity
- **ID:** F2
- **Category:** 1. Trick wording / 2. Hidden information
- **Tier(s):** All (especially Medium and Hard)
- **Exact quote:**
  - `"Every rule and number of the game is written on this page. Nothing is hidden except who the mole is."`
  - `"If the mole has such a document, it leaks one with probability 0.75. By default it picks one at random, with every eligible document equally likely. This mole is careful: for a canary, the chance of being picked is multiplied by (1 - the share of all employees who received any variant of that canary)."`
  - `"The mole follows a fixed list of if-then rules. The first rule that matches is used; otherwise a default rule applies. ... A rule chooses which document to leak: newest, oldest, most recipients, fewest recipients, random, or none. ... The mole never knows which documents are canaries. The 0.75 leak probability above still applies to every leak."`
- **Why it matters for a strong agent:** There are four interlocking problems here for a Bayesian agent computing exact posteriors from leaked (or unleaked) documents and canaries:
  1. **Contradiction on "Nothing is hidden":** Does the mole actually have a secret, randomly generated Mole DSL program in each episode, or does it *only* use the default rule? Claiming `"Nothing is hidden except who the mole is"` conflicts with `"The mole follows a fixed list of if-then rules"` if that list of rules is hidden from the agent! If a secret DSL rule list is sampled per episode, what is the prior distribution over rules?
  2. **Contradiction on canary awareness:** `"The mole never knows which documents are canaries"` directly contradicts `"for a canary, the chance of being picked is multiplied by (1 - the share of all employees who received any variant of that canary)"`. How does `careful_mole` multiply *only* a canary's weight without knowing it's a canary, or does `careful_mole` apply to *all* documents based on recipient share, or is `careful_mole` a server-side downweighting applied specifically to canaries?
  3. **Interaction between DSL deterministic choices and `careful_mole`:** If a DSL rule selects `fewest recipients` (which will almost always be a 1–3 recipient canary!), how is the canary's chance "multiplied by $(1 - \text{share})$"? Does `careful_mole` only modify relative weights during `random` selection, or does it turn a chosen canary leak into a non-leak with probability $\text{share}$, or are relative weights normalized across eligible documents (meaning `p_leak` stays 0.75 even if the *only* eligible document is a canary)?
  4. **Tie-breaking in DSL:** Almost every day publishes 2–4 documents simultaneously (same age) and canaries/dept docs can tie on recipient counts. How are ties broken for `newest`, `oldest`, `most recipients`, and `fewest recipients`? Uniformly at random (with or without `careful_mole` weights)?
- **Severity:** High
- **Suggested rewording:** 
  - Change `"Nothing is hidden except who the mole is"` to `"Nothing is hidden except who the mole is (and, in tiers with a decoy, who the decoy is, plus the mole's specific if-then rule list)."`, and state how the rule list is generated (e.g., `"Each episode samples 0 to 3 random if-then rules..."` or whatever the true generator is).
  - Explicitly give the exact mathematical formula for `careful_mole` and tie-breaking: e.g., `"When choosing among eligible documents (either via 'random' or to break ties in newest/oldest/most/fewest), regular documents have weight 1 and canaries have weight (1 - |canary_recipients| / n_employees). One document is sampled proportional to these weights, and then leaked with probability p_leak (unless the rule chose 'none', in which case nothing is leaked)."`

---

### Finding 3: Hard tier fingerprint error with only 1 planted variant label (division by zero / impossible fallback)
- **ID:** F3
- **Category:** 1. Trick wording / 2. Hidden information
- **Tier(s):** Hard
- **Exact quote:** `"Use at most 3 different labels and at least 1 recipient. ... If the canary leaks, the leak feed shows the variant label the mole received with probability 0.95. Otherwise (fingerprint recovery from a rewritten leak is imperfect) it shows one of the OTHER variant labels planted for that canary, chosen uniformly."`
- **Why it matters for a strong agent:** A natural strategy is to plant a canary on a suspect subset using **1 variant label** (which is explicitly legal: `"at most 3 different labels and at least 1 recipient"`). If only 1 distinct variant label was planted for that canary, there *are* no "OTHER variant labels planted for that canary"! What happens in the remaining 5% probability? Does it always show that single label (making a 1-label canary 100% accurate and bypassing the `fingerprint_accuracy` mechanic), does it show `"unknown"`/`null`, or does it fabricate a random string? A strong agent will immediately spot that 1-label canaries might exploit or break this rule and needs to know the exact behavior.
- **Severity:** High
- **Suggested rewording:** State the exact behavior when only 1 distinct variant label is used, e.g.: `"If only 1 variant label was planted in assignment, that label is shown with probability 1.0 (there is no other variant to confuse it with — though planting only 1 label tests only membership in the recipient set rather than splitting it into 3 groups)."` (Or if the server emits an `"corrupted"` / random label, state that instead.)

---

### Finding 4: Access log generation model — per-document vs. per-employee Poisson rate, and fake accesses
- **ID:** F4
- **Category:** 1. Trick wording / 2. Hidden information
- **Tier(s):** All
- **Exact quote:** 
  - `"Access logs exist for days that have ended. Every employee opens documents it holds a random number of times per day (Poisson). The average is 1.0 for an innocent employee and 1.3 for the mole."`
  - `"Framing adds one fake after-hours access for that colleague."`
- **Why it matters for a strong agent:** 
  1. **"opens documents it holds a random number of times per day (Poisson)"** is critically ambiguous between two completely different statistical models:
     - *Model A (per-employee total):* Total accesses per day for employee $i$ is $\text{Poisson}(\lambda_i)$ (if they hold $\ge 1$ doc), with each access picking a held document uniformly.
     - *Model B (per-document):* For *each* held document, employee $i$ opens it $\text{Poisson}(\lambda_i)$ times per day (so holding 20 documents yields $\sim 20\lambda_i$ accesses/day).
     An agent doing log-likelihood updates on access counts will get wildly wrong posteriors (often saturating to 0 or 1 within days!) if it assumes Model B when the game uses Model A, or vice versa.
  2. **Framing details:** Does a fake after-hours access specify a document ID (and if so, only from documents that colleague holds, or *any* document, which would be a smoking gun of framing)? And in Medium/Hard tiers, **when** do framing rules in the Mole DSL trigger relative to background framing (`framing_rate`)? The Easy tier lists `"A rule may also frame one colleague..."` even though `"Framing is off in this tier"` and `framing_rate: 1` appears in Easy's exact parameters! Can a Mole DSL rule still frame in Easy tier when `framing: off`, or is DSL framing also disabled when `framing: off`? And in Medium/Hard, is DSL rule framing *additive* on top of the $\text{Poisson}(\text{framing\_rate})$ background framing (`"does no extra framing"`)? Which employee is `"the first restricted colleague"` (lowest ID `eXX`, or earliest restricted)? Can a DSL `"random colleague"` pick the mole itself or the decoy?
- **Severity:** High
- **Suggested rewording:** 
  - Clarify the Poisson rate: e.g., `"Each day, each employee who holds at least one document makes Poisson(rate) total document accesses (NOT per document), choosing uniformly at random among documents they hold at that day's end."`
  - Clarify framing: specify whether fake accesses attach to a random document held by the target, clarify that when `framing: off` (Easy), *neither* background framing nor DSL framing occurs, specify that in Medium/Hard DSL framing adds 1 extra fake access on top of the daily `Poisson(framing_rate)` fake accesses, and define `"first restricted colleague"` (e.g., lowest employee ID currently restricted, excluding the mole) and `"random colleague"` (uniformly among all employees other than the mole).

---

### Finding 5: Timing of daily events (when `restrict_access`, document publication, leaks, surfacing, and costs happen)
- **ID:** F5
- **Category:** 2. Hidden information / 1. Trick wording
- **Tier(s):** All
- **Exact quote:**
  - `"Each day, between 2 and 4 new sensitive documents are published... Restricted employees do not receive new documents."`
  - `"At the end of each day, the mole may leak one document that it received in the last 3 days (today included)... It appears in the leak feed after a delay of 1 day(s)"`
  - `"`restrict_access(employee)` costs 0.01 of V for every day that ends while the employee is restricted."`
- **Why it matters for a strong agent:** Within a single day $d$, what is the exact sequence of events?
  1. Are day $d$'s 2–4 regular documents already published *at the start* of day $d$ (before the agent can act on day $d$)? If so, calling `restrict_access(e05)` on day $d$ only prevents `e05` from receiving regular documents starting on day $d+1$, whereas `restrict_access(e05)` immediately blocks `plant_canary` on day $d$ (`"Restricted employees cannot receive a canary"`). An agent trying to restrict a suspect on day 1 before day 1's docs go out needs to know they already received day 1's docs.
  2. `"after a delay of 1 day(s)"`: If the mole leaks a document at the end of day 1 with delay = 1, is it visible in `check_leak_feed` on **day 2** (immediately after calling `advance_day` from day 1 to day 2), or on **day 3** (1 full day intervening)? "End of day 1 + 1 day delay" could mean end of day 2 (visible day 3) or start of day 2 (visible day 2). In Hard tier (`delay_choices: 2, 3`), a 1-day shift changes which day's canaries could have surfaced!
  3. `"in the last 3 days (today included)"`: On day 4, does `leak_window_days: 3` mean documents received on days `{2, 3, 4}` (3 days, today included) or `{1, 2, 3, 4}` ($4 - 1 \le 3$)? `"last 3 days (today included)"` means `{d-2, d-1, d}`, so age $\in \{0, 1, 2\}$. Meanwhile, Mole DSL refers to `"the age of the newest one"` — is a document received today age 0 or age 1?
- **Severity:** High
- **Suggested rewording:** Add a 4-line **"Order of events on day $d$**" bullet under **Days**:
  1. *Start of day $d$:* Leaks scheduled to surface on day $d$ appear in the leak feed (and lower visible $V$); 2–4 new regular documents are published to non-restricted employees. (A leak from the end of day $t$ with delay $\Delta$ surfaces at the start of day $t + \Delta$, so $\Delta = 1$ means visible at the start of day $t+1$.)
  2. *During day $d$:* You take actions (including `plant_canary`, `restrict_access`, `accuse`).
  3. *End of day $d$ (`advance_day`):* Each currently restricted employee costs `0.01` of $V$; access logs and messages for day $d$ are finalized; the mole potentially leaks a document received on day $d, d-1,$ or $d-2$ (ages 0, 1, 2) and applies any framing.

---

### Finding 6: Totally undocumented message system and tool output schemas
- **ID:** F6
- **Category:** 2. Hidden information / 4. Broken or inconsistent tools
- **Tier(s):** All
- **Exact quote:**
  - Tools: `search_messages` (`"Case-insensitive substring search over message subject+body (max 20 results)."`), `read_message` (`"Read one full message by id."`)
  - Evidence (Medium/Hard): `"There is a decoy: one innocent, unhappy employee who writes angry messages."`
  - Exact parameters: `"noise: 1"`
- **Why it matters for a strong agent:** Both `search_messages` and `read_message` cost **1 of the 8 daily actions**, yet **nothing in the rules explains what messages exist in the game or whether the mole ever leaves clues in messages!**
  - In Easy tier, there is no decoy, yet `search_messages` and `read_message` are still listed as tools. Are messages purely flavor/noise in Easy, or does the mole write suspicious messages (e.g., mentioning external contacts, money, or Mole DSL hints)?
  - Even in Medium/Hard, do messages *only* serve to identify who the decoy is (so you don't get fooled by fake after-hours accesses), or does the mole also send/receive incriminating messages?
  - Can `search_messages(query="")` (empty string) be used to list up to 20 messages without guessing keywords? (In JSON schema, `query` has `"type": "string"` with no `minLength`, unlike `doc_title` which has `"minLength": 1`.) Are messages available for the *current* day or only closed days?
  - Similarly, what fields does `list_documents` return? Specifically, does `list_documents` tell you **which employees or departments received each document**? (Crucial for cross-referencing leaked regular documents with recipients!)
- **Severity:** Medium
- **Suggested rewording:** 
  - Add a bullet in **Evidence** explaining the message generative process across tiers (what benign employees, the decoy, and the mole write, and whether messages exist for the current day or only ended days). Explain what `query=""` does.
  - Mention in **Documents** (or `list_documents` description) what metadata is visible for each document (e.g., `"list_documents shows each document's id, day, title, whether it is a canary, and its recipient list / departments"`).

---

### Finding 7: Unexplained parameters in `Exact parameters` and clumsy template artifacts in prose
- **ID:** F7
- **Category:** 4. Broken or inconsistent tools / 1. Trick wording
- **Tier(s):** All
- **Exact quote:**
  - Documents (all tiers): `"0% of documents go to everyone in one department. The other 100% go to everyone in two departments."`
  - Easy tier leaks: `"after a delay of 1 day(s), each equally likely."`
  - Exact parameters: `"p_single_dept_recipients: 0"`, `"doc_recipient_share: 0"`, `"noise: 1"`, `"framing_rate: 1"` (in Easy, where framing is off), `"framing_decoy_share: 0.5"` (in Easy, where decoy & framing are off).
- **Why it matters for a strong agent:** 
  - `doc_recipient_share: 0` and `noise: 1` are never explained anywhere in the prose, violating `"The same numbers as above"`. What is `noise: 1`? What does `doc_recipient_share: 0` mean (presumably when 0 it means 100% of the chosen departments get the doc rather than a random subset)? A careful agent reading `"Every rule and number of the game is written on this page"` will waste reasoning tokens wondering how `noise: 1` affects observations or whether `doc_recipient_share: 0` is a special sentinel value.
  - Saying `"0% of documents go to everyone in one department. The other 100% go to everyone in two departments"` is clearly an unpolished string-interpolation artifact, and doesn't state how the two departments are chosen (uniformly at random without replacement? How many departments exist?).
- **Severity:** Low
- **Suggested rewording:** 
  - Replace `"0% of documents..."` with `"Every regular document goes to two randomly chosen departments (uniformly without replacement)."`, and mention how many departments exist (or note that `list_employees` shows them).
  - Either omit inactive/internal parameters (`doc_recipient_share`, `p_single_dept_recipients`, `noise`, and inactive `framing_*` in Easy) from `Exact parameters`, or add a 3-word parenthetical note explaining `noise: 1` and `doc_recipient_share: 0`.

---

### Finding 8: Ambiguity on `interview` repeatability across days and topics
- **ID:** F8
- **Category:** 1. Trick wording / 2. Hidden information
- **Tier(s):** All
- **Exact quote:** `"Interviews: an innocent answers evasively with probability 0.2. The mole answers evasively with probability 0.2 x 1.5. Asking the same employee about the same topic on the same day gives the same answer."`
- **Why it matters for a strong agent:** By stating `"Asking the same employee about the same topic on the same day gives the same answer"`, the text strongly implies—without quite stating—that:
  1. Asking the same employee about **different topics on the same day** (there are 4 enum topics in `interview`) produces **4 independent** Bernoulli draws!
  2. Asking the same employee about the **same topic on different days** produces **independent** Bernoulli draws!
  3. All 4 topics (`recent_documents`, `contacts_outside`, `workload`, `access_needs`) have the exact same evasive probabilities ($0.2$ vs. $0.2 \times \text{LR}$), and the tool returns a clear boolean/label for `evasive` (rather than natural-language prose the agent has to classify subjectively).
  If those draws are *indeed* independent across topics and days, a strong agent should know for certain so it can spend unused end-of-day actions farming independent likelihood-ratio signals on top suspects. Conversely, if topics are correlated or natural-language-only, assuming independence would cause overconfident false accusations.
- **Severity:** Medium
- **Suggested rewording:** `"Interviews: each (employee, topic, day) triple independently produces an evasive answer with probability 0.2 (innocent) or 0.2 x 1.5 (mole), regardless of topic. Repeating the exact same (employee, topic) on the same day returns the cached answer from earlier that day."` (Adjust `1.5` per tier, and clarify whether the JSON output explicitly includes an `evasive: true/false` field or text.)

---

### Finding 9: Edge cases on company value `V` clamping and endgame scoring
- **ID:** F9
- **Category:** 1. Trick wording
- **Tier(s):** All
- **Exact quote:**
  - `"V shown is the value you can see: damage from leaks that haven't surfaced yet is not visible until they surface. Your score uses the true V, which includes undetected damage."`
  - `"If day 14 ends and you have not accused anyone, your score is 0. So accusing is only worth it when P(correct) x V + (1 - P(correct)) x (-1) is greater than 0."`
  - Harbor preface: `"The episode ends when you call accuse (exactly once), when the last day ends, or at the tool-call limit."`
- **Why it matters for a strong agent:**
  1. In the formula `P(correct) x V + (1 - P(correct)) x (-1)`, `V` refers to **true V** (which is $\le$ shown $V$ because of unsurfaced leaks from the last 1–3 days), not shown $V$. While a careful reader will deduce this from the second bullet, writing `V` right after defining `"V shown"` could mislead an agent on a close EV decision near $P(\text{correct}) \approx 0.55$.
  2. Does calling `advance_day` *on* day 14 (or 21 in Hard) immediately end the episode with score 0 (`"when the last day ends"`), or is there an end-of-day step? Make sure the agent knows not to call `advance_day` on day 14/21 if it intends to accuse!
  3. Can you call `plant_canary` or `restrict_access` when $V = 0$, or do paid actions still work when $V$ is clamped at 0? (Unlikely to hit $V=0$ unless heavily restricting, e.g., restricting 10 people for 10 days = $1.00$, which *is* plausible if an agent tries a mass-restriction quarantine strategy!) Wait: **mass-restriction quarantine**! What if an agent restricts *all* 12 employees on Days 1–2 ($12 \times 0.01 = 0.12$/day), starving everyone of new docs after Day 3 so no more leaks happen, and plants targeted canaries by unrestricting 3 people at a time? Wait—`status` shows `V`! If the agent restricts *everyone* except suspect $X$ after old docs expire (3 days), any drop in visible $V$ (once leaks surface) proves $X$ leaked, without even planting canaries! And if $V$ clamps at 0, restricting everyone is free once $V=0$ (though score would be 0 anyway). That's fine strategically, just good to be sure action costs don't block actions at $V=0$.
- **Severity:** Low
- **Suggested rewording:** Change `V` in the expected value formula to `true_V`: `"So accusing is only worth it when P(correct) x true_V + (1 - P(correct)) x (-1) > 0 (remember true_V may be lower than shown V due to unsurfaced leaks). Do not call advance_day on the final day if you want to accuse, as ending the final day immediately ends the episode with score 0."`

---

### Verdict

**Not quite ready to publish as-is — several high-severity omissions and contradictions would punish strong Bayesian reasoning rather than test it.** While the core game design, action budgets (8 actions/day, 14–21 days, 300–420 tool calls), and tier progressions are well-balanced and leave plenty of time for canary binary/ternary search (even with 2–3 day leak delays in the 40-employee Hard tier, where 2 three-variant canaries per day can partition 40 suspects in a few days), a strong mathematical agent will immediately stumble over unspecified generative models. In particular: (1) Hard tier turns `access_constraints: on` and introduces employee clearance levels without stating how clearance restricts regular documents; (2) the interaction between the hidden Mole DSL, `careful_mole`, and the claim `"Nothing is hidden except who the mole is"` is internally contradictory; (3) the Hard tier's 5% canary-label error rule is undefined when planting a 1-label canary; (4) the Poisson access-log model is ambiguous between per-employee and per-document rates; (5) exact intra-day ordering and off-by-one leak delay timing are unclear; and (6) the message system (`search_messages`/`read_message`) and unexplained parameters (`noise`, `doc_recipient_share`) have no rules describing them. Resolving Findings F1–F6 (and tidying F7–F9) requires only ~20 lines of crisp specification and will make the benchmark completely fair, unambiguous, and a true test of reasoning under uncertainty.
