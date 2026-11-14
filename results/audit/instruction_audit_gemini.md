# Instruction audit by gemini-4-carbon (one pass)

Generated 2026-11-14T21:19:39+00:00 at git `eb4c245` by `scripts/instruction_audit.py --gemini`. Input: Harbor preface + Env.instruction() for easy/medium/hard + tools_spec (23696 chars, sha256 0752bd7962b42ef6). Usage: 7132 in / 4998 out tokens, cost_usd 0.064244, thinking low, finish {'FinishReason.STOP': 1}. The model's claims are checked against the code in docs/DIFFICULTY.md.

---

### Findings

**1. Unexplained clearance constraints (`access_constraints: on`) on regular documents**
- **Category:** Hidden information / Broken or inconsistent tools
- **Tier(s):** Hard (and inconsistent with Easy/Medium)
- **Exact quote:**
  - Hard tier, *Documents*: `"0% of documents go to everyone in one department. The other 100% go to everyone in two departments."`
  - Hard tier, *Canaries*: `"Each employee has a clearance level (1 to 3). Canaries are level 1, so every employee may receive one."`
  - Hard tier, *Exact parameters*: `"- access_constraints: on"`
- **Why it matters for a strong agent:** Saying *"Canaries are level 1, so every employee may receive one"* and setting `access_constraints: on` strongly implies that non-canary documents have clearance levels (1 to 3) and that employees only receive a document if their clearance meets or exceeds the document's level. Yet the *Documents* section still claims `"100% go to everyone in two departments"` with no mention of clearance filtering! Also, it does not say whether `list_documents` returns the exact recipient list or only departments/clearance, leaving the agent unable to know who actually holds a leaked document or if the prose contradicts the code.
- **Severity:** High
- **Suggested rewording:** Explicitly state how clearance levels work in Hard tier's *Documents* section: *"Each document has a clearance level (1, 2, or 3, [state distribution]). It goes to every unrestricted employee in two randomly chosen departments whose clearance level is at least the document's level."* Also clarify what fields `list_documents` returns (e.g., exact recipient IDs, departments, clearance level).

---

**2. Broken math/edge case when planting a 1-variant canary with imperfect fingerprint accuracy**
- **Category:** Trick wording / Hidden information
- **Tier(s):** Hard
- **Exact quote:**
  - Hard tier, *Canaries*: `"Use at most 3 different labels and at least 1 recipient."` ... `"If the canary leaks, the leak feed shows the variant label the mole received with probability 0.95. Otherwise (fingerprint recovery from a rewritten leak is imperfect) it shows one of the OTHER variant labels planted for that canary, chosen uniformly."`
- **Why it matters for a strong agent:** A classic strategy is a binary test: give variant `"A"` to half the suspects and no canary at all to the rest (1 variant label total). If the agent plants only 1 variant label, the set of *"OTHER variant labels planted for that canary"* is **empty**. What happens in the remaining 5% case? Does it still show that single label (giving 100% label certainty and bypassing the 0.95 noise!), show a random string, or fail? A Bayesian agent cannot compute exact likelihoods—or might exploit a 1-label loophole—without knowing this.
- **Severity:** High
- **Suggested rewording:** Either require at least 2 distinct variant labels when `fingerprint_accuracy < 1`, or state the exact fallback: *"If only 1 variant label was planted, the leak feed always shows that label [or: shows 'corrupted' / an unplanted label with probability 0.05]."*

---

**3. Contradiction between "Careful mole", "Mole never knows which documents are canaries", and Mole DSL**
- **Category:** Trick wording / Hidden information
- **Tier(s):** All tiers (especially Medium and Hard)
- **Exact quote:**
  - Medium/Hard, *How leaks work*: `"By default it picks one at random, with every eligible document equally likely. This mole is careful: for a canary, the chance of being picked is multiplied by (1 - the share of all employees who received any variant of that canary)."`
  - All tiers, *How the mole decides (Mole DSL)*: `"The mole follows a fixed list of if-then rules. The first rule that matches is used; otherwise a default rule applies."` ... `"A rule chooses which document to leak: newest, oldest, most recipients, fewest recipients, random, or none."` ... `"The mole never knows which documents are canaries."`
- **Why it matters for a strong agent:** Three major ambiguities collide here:
  1. **Direct contradiction:** How can the mole *"never know which documents are canaries"* while multiplying **only a canary's** selection weight by `(1 - recipient_share)`? And how is "chance of being picked is multiplied by..." normalized across non-canaries and canaries? (Presumably selection weights are `1.0` for regular docs and `1 - k/N` for a canary with `k` recipients, then normalized—or does the 1 - k/N reduction turn into a non-leak?)
  2. **Interaction with DSL deterministic choices:** What if a non-default Mole DSL rule triggers and chooses `fewest recipients` or `newest`? Canaries usually have the fewest recipients! Does `careful_mole` weight-scaling only apply when the rule chooses `random`, or does it affect `fewest recipients` / tie-breaking / `p_leak`?
  3. **Prior over Mole DSL:** *"Every rule and number of the game is written on this page. Nothing is hidden except who the mole is."* Yet the mole's fixed list of if-then DSL rules is completely hidden! Does every episode sample a random DSL program, or is the mole *always* using the default rule unless specified? If sampled, what is the prior? Furthermore, if a rule chooses `none`, does the mole not leak even though *"The [p_leak] leak probability above still applies to every leak"*?
- **Severity:** High
- **Suggested rewording:** 
  - Clarify whether the mole's DSL rule list is also hidden and randomly generated per episode (updating *"Nothing is hidden except who the mole is and what rule list it follows"*), or if the mole only uses the default rule.
  - Specify exact math for `careful_mole`: *"When choosing among eligible documents (or ties), non-canary documents have weight 1 and canaries have weight (1 - |recipients| / n_employees); one is drawn proportional to weight. Does this apply only to `random` or all DSL choices?"* (Remove *"never knows which documents are canaries"* in Medium/Hard, or explain that canaries look slightly suspicious when widely distributed).
  - Clarify `none`: *"If the matching rule chooses `none`, the mole does not leak today; otherwise it leaks with probability `p_leak`."*

---

**4. Access log Poisson rate: per-employee total vs. per-held-document, and fake access details**
- **Category:** Trick wording / Hidden information
- **Tier(s):** All tiers
- **Exact quote:**
  - All tiers, *Evidence*: `"Every employee opens documents it holds a random number of times per day (Poisson). The average is 1.0 for an innocent employee and 1.3 for the mole."`
  - Medium/Hard, *Evidence*: `"Each day the mole adds fake after-hours accesses for other employees (Poisson, average 1.5)."`
  - All tiers, *Mole DSL*: `"Framing adds one fake after-hours access for that colleague."`
- **Why it matters for a strong agent:**
  1. **"opens documents it holds a random number of times per day (Poisson, average 1.0)"**: Does an employee holding $D$ documents generate $\text{Poisson}(1.0)$ total log entries per day (picking uniformly among its $D$ held documents), OR $\text{Poisson}(1.0)$ entries *per held document* per day (averaging $1.0 \times D$ accesses/day)? Over 14–21 days an employee accumulates ~30–50 documents; the difference between 1 access/day and 40 accesses/day completely changes statistical inference and payload sizes of `read_access_logs`.
  2. **Which document is attached to a framed/fake access?** Can a fake access log entry reference a document that the framed colleague *does not even hold* (e.g., restricted, wrong department, or unplanted canary)? If yes, fake accesses are trivially detectable; if no, the agent needs to know they are drawn from the victim's held documents (or all published documents).
  3. **DSL framing vs. `framing: off` / `framing_rate`:** In Easy tier, `framing: off`, yet `framing_rate: 1` is in *Exact parameters*, and the *Mole DSL* section still says *"A rule may also frame one colleague"*. Can a DSL rule still frame someone in Easy tier when `framing: off`? In Medium/Hard, is DSL rule framing *in addition to* the daily `Poisson(framing_rate)` framing? (The last line hints *"no extra framing"*, implying they stack, which should be explicit).
- **Severity:** High
- **Suggested rewording:** State clearly: *"Each day, for each employee, total genuine log entries ~ Poisson(rate), each assigned uniformly to a document that employee currently holds [OR: for each document an employee holds, accesses ~ Poisson(rate)]."* Specify which document a fake access logs (e.g., *"a random document held by that colleague, if any"*), and state in Easy tier that *"Framing is off in this tier (neither background framing nor Mole DSL framing occurs)."*

---

**5. Messages system (`search_messages`, `read_message`) is almost completely undocumented**
- **Category:** Hidden information
- **Tier(s):** All tiers
- **Exact quote:**
  - Easy tier, *Evidence*: `"`search_messages` returns at most 20 results."`
  - Medium/Hard tier, *Evidence*: `"There is a decoy: one innocent, unhappy employee who writes angry messages. The mole is equally likely to be any other employee."`
- **Why it matters for a strong agent:** Two of the 8 action-consuming tools (`search_messages` and `read_message`) deal with employee messages, yet **Easy tier never even mentions what messages exist or why an agent would ever read them!** Even in Medium/Hard, only decoy "angry messages" are mentioned. Do messages contain mole signals (e.g., discussing outside contacts, financial trouble, hints about the Mole DSL rules, or leaked topics)? Or are messages purely useful to identify the *decoy* in Medium/Hard (and completely useless traps in Easy)? Also, if `search_messages(query="")` is called, does an empty string match all messages so the agent can browse without guessing keywords?
- **Severity:** High
- **Suggested rewording:** Add a bullet under *Evidence* explaining the generative role of messages in every tier: what kinds of messages innocent employees, the decoy, and the mole send, whether messages contain clues about the mole (or the mole's DSL rules!), and whether `query=""` is allowed or has a minimum length.

---

**6. Exact intraday order of events (Day 1 documents, `restrict_access`, `plant_canary`, leak timing, and leak surfacing)**
- **Category:** Hidden information
- **Tier(s):** All tiers
- **Exact quote:**
  - *Documents*: `"Each day, between 2 and 4 new sensitive documents are published... Restricted employees do not receive new documents."`
  - *How leaks work*: `"At the end of each day, the mole may leak one document that it received in the last 3 days (today included)..."` ... `"Each leak lowers the true V by 0.05 right away. It appears in the leak feed after a delay of 1 day(s)"`
  - *Restricting access*: `"`restrict_access(employee)` costs 0.01 of V for every day that ends while the employee is restricted."`
- **Why it matters for a strong agent:**
  1. When a day starts (before the agent takes actions), are today's 2–4 regular documents *already* published and distributed? If so, calling `restrict_access(e07)` on Day $t$ only blocks documents starting on Day $t+1$, while *still* charging 0.01 at the end of Day $t$! Conversely, if documents are published at the *end* of the day, `list_documents` at the start of Day 1 (as instructed in the Harbor preface: *"Call `status` first, then `list_employees` and `list_documents`"*) would be empty!
  2. What does *"after a delay of 1 day(s)"* mean? If a document is leaked at the end of Day 1 with delay 1, is it visible in `check_leak_feed` on Day 2 (at the start of Day 2, right after `advance_day` closes Day 1), or not until Day 3? This 1-day shift is crucial for Bayesian updating (knowing which day's eligible window a surfaced leak came from) and for knowing whether planting a canary on Day 13 (Easy) or Day 19 (Hard, delay 2–3) can ever surface before the game ends on Day 14 / Day 21!
- **Severity:** High
- **Suggested rewording:** Give an explicit 4-step timeline for Day $d$:
  1. *Start of Day $d$*: Leaks from Day $d - \text{delay}$ surface (lowering visible $V$ and appearing in `check_leak_feed`); 2–4 new documents are published to currently unrestricted employees.
  2. *Agent's turn*: Agent takes up to 8 actions (e.g., `plant_canary` distributes today; `restrict_access` takes effect immediately for future publications).
  3. *`advance_day` (End of Day $d$)*: Restriction fee (`0.01` per currently restricted employee) is deducted from visible & true $V$; access logs for Day $d$ are generated; the mole decides whether to leak (lowering true $V$ immediately).
  4. Move to Day $d+1$ (or end episode with score 0 if $d = n\_days$).

---

**7. Interview mechanics across topics and days**
- **Category:** Hidden information
- **Tier(s):** All tiers
- **Exact quote:**
  - *Evidence*: `"Interviews: an innocent answers evasively with probability 0.2. The mole answers evasively with probability 0.2 x 1.5. Asking the same employee about the same topic on the same day gives the same answer."`
  - *MCP tool `interview`*: `"enum": ["recent_documents", "contacts_outside", "workload", "access_needs"]`
- **Why it matters for a strong agent:** 
  1. Does asking the same employee **4 different topics on the same day** give 4 **independent** Bernoulli draws? And does asking the same employee the **same topic on a different day** give a fresh **independent** draw? The wording implies yes to both, which makes spamming interviews a mathematically well-defined likelihood-ratio test—unless evasiveness is partially determined by topic or fixed traits (e.g., does the decoy in Medium/Hard also answer evasively more often on `"workload"`?).
  2. Does `interview` return an explicit boolean (`"evasive": true/false`), or natural-language prose where the agent has to guess whether the tone counts as "evasive"? (Also connects to the undocumented `noise: 1` parameter).
- **Severity:** Medium
- **Suggested rewording:** State explicitly: *"The tool returns a structured flag (or text) indicating whether the answer was evasive. Across different topics or different days, draws are conditionally independent given the employee's role. The decoy has the same 0.2 evasive probability as any innocent employee [or state otherwise]."*

---

**8. Undocumented parameters and dead prose in "Exact parameters" & "Documents"**
- **Category:** Broken or inconsistent tools / Trick wording
- **Tier(s):** All tiers
- **Exact quote:**
  - *Documents*: `"0% of documents go to everyone in one department. The other 100% go to everyone in two departments."`
  - *Exact parameters*:
    - `"- doc_recipient_share: 0"`
    - `"- noise: 1"`
    - `"- framing_rate: 1"` and `"- framing_decoy_share: 0.5"` (in Easy tier where `framing: off` and `decoy: off`)
    - `"- canary_level: 1"` (in Easy/Medium where clearance levels are never mentioned)
- **Why it matters for a strong agent:**
  - `"0% of documents go to everyone in one department..."` reads like an uncleaned template string (`{p_single_dept_recipients}%`), which looks suspicious to a careful reader checking for edge cases.
  - `noise: 1` and `doc_recipient_share: 0` are **never explained anywhere in the prose**, despite the header claiming *"The same numbers as above, one per line"* and *"Every rule and number of the game is written on this page."* A strong agent will wonder what `noise: 1` controls (message noise? log noise? interview text noise?).
- **Severity:** Medium
- **Suggested rewording:** Rewrite `"0% of documents..."` cleanly as *"Every regular document goes to all unrestricted employees in two randomly chosen departments."* Explain `noise: 1` and `doc_recipient_share: 0` in the prose (or remove unused internal config parameters from the agent-facing prompt).

---

**9. Tool-argument rule vs. `plant_canary` schema, and unspecified `day_from`/`day_to` defaults**
- **Category:** Broken or inconsistent tools
- **Tier(s):** All tiers
- **Exact quote:**
  - *Rules for tool arguments*: `"Give exactly one employee id per call, such as e07. Lists, wildcards and names are rejected."`
  - *MCP tool `list_documents` & `search_messages`*: `"day_from"` and `"day_to"` are optional (`"required": []` / `["query"]`), whereas in `read_access_logs` `"required": ["day_from", "day_to"]`.
- **Why it matters for a strong agent:**
  1. Literally read, *"Give exactly one employee id per call"* contradicts `plant_canary(doc_title, assignment)` where `assignment` maps multiple employee IDs to variant labels, and contradicts calling `read_access_logs(day_from, day_to)` with `employee` omitted (to fetch all employees' logs at once in 1 action instead of spending 12–40 actions!). If omitting `employee` in `read_access_logs` is allowed and returns *all* employees' logs for that day range in a single action, the agent must be confident that rule doesn't forbid it (and whether output is truncated!).
  2. When `day_from` / `day_to` are omitted in `list_documents` or `search_messages`, do they default to all days up to today? And in `read_access_logs`, if `day_to` includes the *current* (unclosed) day, does the call return an error (wasting a call toward the cap and/or an action) or silently clamp to `current_day - 1`? (Especially on Day 1 when no days are closed yet!).
- **Severity:** Medium
- **Suggested rewording:** Change the argument rule to: *"For tools with an `employee` string parameter, pass a single employee id such as `"e07"` (not a list, wildcard, or full name). Omitting `employee` in `read_access_logs` returns logs for all employees."* Specify defaults for optional `day_from`/`day_to` and warn that `read_access_logs` requires `day_to < current_day` (and whether failed tool calls consume one of the 8 daily actions in addition to one of the 300/420 tool calls).

---

**10. Mole DSL imprecise definitions ("age of the newest one", "first restricted colleague")**
- **Category:** Trick wording / Hidden information
- **Tier(s):** All tiers
- **Exact quote:**
  - *Mole DSL*: `"...the age of the newest one..."` and `"A rule may also frame one colleague (the decoy, the first restricted colleague, or a random colleague)."`
- **Why it matters for a strong agent:**
  - Is the "age" of a document received today `0` or `1`?
  - Does "the first restricted colleague" mean lowest lexicographical ID (`e00`, `e01`, ...) currently restricted, or the colleague who was restricted earliest chronologically?
  - When a DSL rule chooses `newest`, `oldest`, `most recipients`, or `fewest recipients` and multiple eligible documents tie (which happens almost every day, since 2–4 docs are published per day to two departments!), how are ties broken? Uniformly at random (weighted by `careful_mole`)?
- **Severity:** Low
- **Suggested rewording:** Define age (`current_day - received_day`, so today is 0), define "first restricted colleague" (lowest employee ID currently restricted), and state that ties in DSL document selection are broken uniformly at random (subject to `careful_mole` weights when on).

---

### Verdict

**Not yet ready for publication without revisions.** While the core game design, action/call budgets, and scoring incentives are well-structured and mathematically rich, the prompt currently fails its own promise that *"Every rule and number of the game is written on this page."* A strong Bayesian agent will be tripped up not by reasoning under uncertainty, but by critical specification gaps: an unstated clearance-filtering rule in Hard tier (`access_constraints: on`), an undefined 0-element set when planting a 1-variant canary under 0.95 fingerprint accuracy, ambiguity over whether access logs are `Poisson(1)` per employee or per held document, zero explanation of what messages exist in Easy tier (or whether messages contain mole clues), an unstated prior/status for the hidden Mole DSL rules alongside a contradiction on how a mole that "never knows which documents are canaries" downweights canaries, and unclear intraday ordering of publications, restrictions, and leak delays. Resolving Findings 1–6 (a ~15-line tightening of the prompt) will make the benchmark completely fair, ensuring that failures genuinely reflect agent reasoning rather than guesswork about undocumented simulator mechanics.
