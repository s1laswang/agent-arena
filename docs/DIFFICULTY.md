# DIFFICULTY: is the judged task fair, and why do agents lose?

Rubric line (30 pts): *explain the agent's main mistakes, tied to decisions in the task; the info and tools to do better are available; no withheld info, trick wording, impossible timing or broken tools.*

This page has two parts:

1. **Why agents lose.** The full analysis is [`docs/reports/failure_analysis_v1.4.md`](reports/failure_analysis_v1.4.md), every number computed by `scripts/failure_analysis_v14.py`. A summary is below.
2. **The instruction audit (PLAN-95 B4).** One pass by hand plus mechanical checks, and one gemini-4-carbon pass, over the exact text the agent receives. Every claim is checked against the code.

Nothing on this page changes a rule or the instruction text. Text changes are **proposed to the CEO** (P0–P12 below).

---

## Part 1. The agent's main mistakes (v1.4 hard, the judges' harness)

OpenCode + gemini-4-carbon over MCP, 30 dev seeds, paired with the reference solver: **65% of the solver (72% luck-adjusted)**.

| # | mistake | decision it maps to | expected V lost, 30 seeds |
|---|---|---|---|
| 1 | Committing before the leaks isolate one person. 9 of 29 accusations were made with ≥ 2 people still consistent with every leak (solver: 3 of 30), and 3 had negative EV near the horizon | plant one canary that gives each remaining suspect a different label, or abstain when P·V − (1−P) < 0 (the formula is printed in the instructions) | 3.39 |
| 2 | Never building evidence, then abstaining (seed 11) | the same under-exploration as #3 | 0.62 |
| 3 | Under-exploration: 8.5 canaries vs the solver's 14.1, 32% of canary capacity, first canary on day 3, and 68 interviews per episode filling the 8-action budget | use the second `plant_canary` slot every day instead of interviews (the instructions give interview LR 1.2) | waiting costs +1.75 in leaks, but −1.69 in canary costs never paid, so ≈ 0 net. It costs through #1 and #2 |

The other 1.11 V of the raw gap is bad luck. Two of the four wrong accusations were made at solver posteriors 0.99 and 0.95 and were wrecked by the **disclosed** 5% fingerprint noise. On the same evidence, the solver's own rule accuses the same innocent.

**Why "the information was available" holds:**
- The solver posterior in that report is computed only from the tool results Gemini itself received.
- The solver reaches a consistent set of 1 in 26 of 30 episodes by day 10.6, using the same 13 tools under the same budgets on the same seeds.
- Gemini lost no information to the leak feed (0.00-day average lag).
- The in-process harness shows the same exploration profile, so this is not an MCP artifact.

**Companion:** the Gemini Failure Atlas ([`results/gemini/atlas.md`](../results/gemini/atlas.md)) covers every cohort, tagged by share of solver regret. Its top mode, premature accusation on a sub-threshold posterior, is the same as mistake #1 here.

---

## Part 2. Instruction audit

### What was audited
- **The judged text:** `canary.text.instruction.render(tier)` (= `Env(tier, 0).instruction()`) for easy, medium and hard, at rules v1.4 on this branch. Also the Harbor preface that `harbor/build.py` prepends, and the MCP tool list (`Env.tools_spec()`). The exact bundle is in [`results/audit/instruction_bundle.txt`](../results/audit/instruction_bundle.txt). Render hashes are in [`results/audit/instruction_checks.md`](../results/audit/instruction_checks.md). `harbor/canary-task/instruction.md` is the medium render (checked).
- **Pass 1, by hand plus code checks.** Every sentence was checked against `canary/env.py`, `canary/world.py`, `canary/mole/dsl.py`, `canary/rules.py` and `harbor/template/task.toml`. This pass started from an earlier draft (integrity engineer, same questions), and each of its findings was re-verified on the current code. `scripts/instruction_audit.py --checks` (no keys) mechanically verifies four things:
  - every TierParams field is printed: 34/34 on every tier;
  - every tool the text names exists;
  - **all 13 tools return `ok` with documented fields on all three tiers: 39/39 calls, 0 failures**;
  - the timing budget.
- **Pass 2, gemini-4-carbon.** One call via `scripts/instruction_audit.py --gemini` (thinking=low, 7,132 in / 4,998 out tokens, **$0.064**). The model saw only what the agent sees, never the source. Raw output: [`results/audit/instruction_audit_gemini.md`](../results/audit/instruction_audit_gemini.md). It reported 10 findings (G1–G10) with the verdict "not yet ready for publication without revisions". An earlier gemini-4-carbon pass on the draft (≈ $0.25) raised the same issues. **Every Gemini claim was checked in code.** Where the code shows the text is accurate, the severity is lowered and the reason is given.

### Verdict against the rubric

| rubric clause | verdict | evidence |
|---|---|---|
| **No withheld info** | No hidden rule changes who the mole is or what an action does. Several mechanics are **under-specified**, though the code settles them: order of events within a day (D8), the access-log model (D6), the careful-mole normalisation (D3), and message content (D9). An agent can still play them correctly by reading the numbers. The solver plays from the same text-level facts | D1–D11, D20–D22; solver 0.564 on hard (n = 400, `results/skill_ladder_v1.4.md`) |
| **No trick wording** | Two sentences invite a wrong reading: "the mole never knows which documents are canaries" next to the careful-mole weight (D3), and the fixed list of if-then rules on base tiers that only use the default rule (D2). Neither hides a number. Both have proposed rewordings | D2, D3, D20 |
| **No impossible timing** | **In-game: feasible.** Hard gives 168 investigative actions under a 420-call cap, and a canary planted by day 19 can still surface. **Wall clock: one real risk.** Harbor's agent timeout is 3,600 s and is not stated anywhere the agent reads. 5 of the 30 committed OpenCode hard episodes took longer (3,632–6,592 s), mostly because of provider latency | D17, **D19** |
| **No broken tools** | 39/39 smoke calls ok. Invalid calls are rejected without costing a daily action (they count toward the call cap, as stated) | D18, `results/audit/instruction_checks.md` |

### Findings

"Status" is one of three values. **By design** comes with the reason. **Proposed to CEO** means a text change we have not made. **Fixed** applies to none of the findings. The `G#` ids refer to the Gemini pass.

| # | Finding (source) | What the code actually does | Severity | Status |
|---|---|---|---|---|
| D1 | **Clearance is shown but has no effect** (G1, pass 1). Hard shows `clearance` 1–3 in `list_employees` and `access_constraints: on`. Gemini read this as an undocumented rule that filters regular documents | `world.py` draws a `min_clearance` for each regular document. Recipients are never filtered by it, no tool returns it (`list_documents` keys: day, doc_id, is_canary, recipients, title), and canaries are level 1. So "100% go to everyone in two departments" is literally true, and clearance changes nothing | low (a red herring; nothing stated is false) | **proposed to CEO (P1):** add "Clearance has no other effect." |
| D2 | **"Nothing is hidden" vs "the mole follows a fixed list of if-then rules"** (G3.3). Is a secret rule list sampled per episode? | On easy, medium and hard the mole is `DEFAULT_STRATEGY`: no rules, a `random_seeded` leak, no extra framing. Only the `hard_forge` and `hard_rl` tracks use other policies, and their text says so | medium (an agent may hedge against a policy that does not exist) | **proposed to CEO (P2):** on base tiers, say "In this tier the mole uses only the default rule." |
| D3 | **"The mole never knows which documents are canaries" contradicts the careful-mole weight,** which applies only to canaries (G3.1) | `env._mole_view`: the p_leak gate comes first. Then each eligible document has weight 1, and a canary has weight 1 − recipients/N. `dsl._select_leak` draws with `rng.choices` in proportion to the weights. If every weight is 0, nothing leaks | medium (a contradiction in wording on a mechanic the solver relies on) | **proposed to CEO (P3)** |
| D4 | DSL tie-breaking, careful weights under deterministic selectors, "age", "first restricted colleague" (G3.2, G10) | Irrelevant on the judged tiers, where the default mole only uses the weighted random selector. On tracks, `dsl.py` breaks ties by received order and ignores the careful weights | low | **by design:** the judged tiers never use deterministic selectors |
| D5 | **Fingerprint noise on a one-label canary** (G2): "one of the OTHER variant labels" has no other label to show | `env._t_advance_day`: if there is no other label, the true label is always shown, with no RNG draw. This is not exploitable: a leak of a one-label canary already proves the mole is a recipient, and the noise only blurs *which subgroup* | low (Gemini rated it high; the "loophole" carries no extra information) | **proposed to CEO (P4):** "If only one label was planted, that label is always shown." |
| D6 | **Access-log Poisson: per employee or per document?** (G4.1) | Per employee per day: a Poisson total, each access to a uniformly random document the employee holds. On hard, the mole's rate equals the benign rate (1.0), so counts carry no signal there. Only the after-hours share differs (0.3 vs 0.1) | medium on medium; none on hard | **proposed to CEO (P5)** |
| D7 | Framing details: which document a fake access names, DSL framing on easy, and stacking (G4.2–4.3) | A fake access names a random document the target holds, and is skipped if it holds none. Framing is off on easy, and the default mole never DSL-frames | low | **by design:** "(some only matter when their feature is on)" covers easy's inactive `framing_*` values |
| D8 | **Order of events within a day; what "a delay of 1 day" means** (G6) | Day d's documents are published at the **start** of day d (day 1 at reset). At `advance_day` from day d, in order: (1) the mole may leak a document from days d−2..d; (2) restriction costs are charged; (3) day d's access logs and messages are created; then day d+1 starts. A leak at the end of day d shows from day d+delay | medium (derivable but scattered; an off-by-one changes canary attribution on hard) | **proposed to CEO (P6)** |
| D9 | **Messages are undocumented** (G5): what they contain, whether the mole leaves clues, whether `query=""` lists everything | Text providers get only `PublicDayFacts`, never the mole, so messages carry no signal about the mole beyond the decoy's anger. The text-only probe sits at the fair bar (`docs/EXPLOITS.md` #9). Day d's messages appear when day d ends. `search_messages("")` is rejected (no daily action used; it counts toward the cap) | medium | **by design** for content: deciding which evidence is worth an action is part of the task. **Proposed to CEO (P7)** for the mechanics. Whether to also say "messages never mention the mole" is a difficulty call: it is true, and it would make the task easier |
| D10 | Unexplained parameters (`noise`, `doc_recipient_share`) and the "0% ... The other 100%" artifact (G8) | `noise` is the difficulty-curve knob, and 1 means the tier as written. `doc_recipient_share: 0` means the feature is off | low (cosmetic) | **proposed to CEO (P8)** |
| D11 | **Interviews: independent across topics and days? Do they return a label or prose? What is the decoy's rate?** (G7) | The signal is seeded by (world, employee, topic, day), so different topics or days are independent draws, with the same probability for every topic. Only the mole gets the ×LR, so the decoy answers like any innocent (0.2). The answer is a sentence from an evasive or cooperative phrase bank | low–medium | **by design** for prose: reading a human answer is the realistic skill. **Proposed to CEO (P9)** to state independence and the decoy's rate |
| D12 | The EV formula says `V` right after "V shown"; the last day ends at 0; paid actions at V = 0 | The score uses the true V, as the line before the formula says. `advance_day` on the last day ends the episode at 0, which is stated. The battery's `restrict_all` scores ≤ 0 (EXPLOITS.md row 4) | low | **by design.** Optional (P10): write "true V" in the formula |
| D13 | `check_leak_feed` costs a daily action | It is listed among the 8-action tools. The feed is cumulative, so one read per day is enough. Gemini read it on the days known V dropped, with 0.00-day average lag (failure analysis §5) | low | **by design:** a budget decision, which is part of the skill |
| D14 | The leak feed lists items in leak order, not surfacing order | `_feed` is appended in leak order. Two items surfacing on the same day reveal which leaked first, which is information about the leak day only, not about who leaked | low | **by design:** harmless. Noted for the CEO only |
| D15 | `search_messages` "returns at most 20 results" without saying which 20 | The first 20 matches in day order. `day_from` and `day_to` (default 1..horizon) narrow the window | low | **proposed to CEO (P7)** |
| D16 | Is the call that reaches the cap executed? | Yes. The call runs, and if it was not an accusation the episode then ends at 0, so an `accuse` as the last call counts | low | **proposed to CEO (P10)** |
| D17 | Impossible in-game timing? | Hard: 21 days, delay 2–3, a 3-day leak window. A canary planted on day d can leak at the end of days d..d+2. Plants up to day 19 can still surface by the horizon. Budget: 8 × 21 = 168 investigative actions under a 420-call cap | none (feasible) | **by design:** the solver wins on the same clock (0.564 on hard) |
| D18 | Broken tools? | All 13 tools return `ok` with documented fields on all three tiers (`results/audit/instruction_checks.md`) | none | **by design:** nothing to fix |
| **D19** | **Unstated wall-clock limit (new, pass 1).** Harbor's `[agent] timeout_sec = 3600` (`harbor/template/task.toml`) appears nowhere the agent reads | In the committed v1.4 OpenCode runs (local runner, no 3,600 s cap), 5 of 30 hard episodes (seeds 5, 11, 19, 24, 29) and 1 of 30 medium episodes ran longer than 3,600 s. Seed 29 took 6,592 s with only 104 LLM calls, which points to provider latency rather than agent behaviour. Under the judges' Harbor run, such an episode may be cut off before it accuses (score 0). The committed Harbor gemini trials took 608–1,985 s | **medium** (this is the one "impossible timing" risk; it is not a rule of the game, but it can score a slow-but-correct agent 0) | **proposed to CEO (P0):** raise `[agent] timeout_sec` to 10800 in `harbor/template/task.toml` (no rules change), or state the limit in the preface |
| **D20** | **"Give exactly one employee id per call" vs `plant_canary`'s multi-employee `assignment`, and the optional `employee` of `read_access_logs`** (new, G9.1) | The rule is enforced only on tools whose `employee` argument is a single string. `assignment` maps many ids, as its own sentence says. `read_access_logs` without `employee` returns every employee's logs for the range in one action | low (a literal reading would make an agent waste actions on per-employee log reads) | **proposed to CEO (P11)** |
| **D21** | **Defaults of the optional day arguments; `read_access_logs` on an unclosed day** (new, G9.2) | `list_documents`: days 1..today. `search_messages`: 1..horizon. `read_access_logs` needs both days. A range ending today silently returns no entries for today ("logs exist for days that have ended"). `day_to` beyond the horizon, or `day_from` > `day_to`, is rejected without costing a daily action | low | **proposed to CEO (P12)** |
| **D22** | Interview answers are prose, not a flag, and the solver reads none of them | The template provider's phrase banks are disjoint (16 evasive and 16 cooperative phrases, no overlap). The reference solver does not interview at all, so nothing about the solver's score depends on parsing them | none | **by design** |

### Proposed changes, for the CEO (not applied)
All of these are wording changes to `Env.instruction()` or the tool descriptions, plus one Harbor config value (P0). None changes a rule, a number, the solver or any score. After a text change, regenerate `harbor/canary-task/instruction.md` (`tests/test_env_docs.py::test_instruction_md_matches_generator`). Changing the text also changes what the committed v1.4 runs were played on, so the CEO should weigh applying it before any further judged run against leaving the measured text frozen.

- **P0 (D19, Harbor only, highest priority):** `harbor/template/task.toml` `[agent] timeout_sec = 3600.0` → `10800.0`. Alternatively, add to the Harbor preface: "Your agent has 60 minutes of wall-clock time in total; an episode that has not accused by then scores 0."
- **P1 (D1, hard):** after "Canaries are level 1, so every employee may receive one.", add "Clearance has no other effect."
- **P2 (D2, base tiers):** replace "The default mole leaks a random document and does no extra framing, exactly as described above." with "In this tier the mole uses only the default rule: it leaks a random eligible document (weighted as above) and does no extra framing."
- **P3 (D3, careful tiers):** replace the careful sentence with "This mole is careful: each eligible document has weight 1, except a canary, whose weight is 1 − (the share of all employees who received any variant of it); it picks one document in proportion to these weights. A canary sent to everyone is never picked." Replace "The mole never knows which documents are canaries." with "Apart from that weight, canaries are treated like any other document."
- **P4 (D5, hard):** append "If only one label was planted, that label is always shown."
- **P5 (D6):** "Every employee who holds documents makes a random number of accesses per day in total, not per document (Poisson, average X for an innocent employee and Y for the mole); each access is to a random document it holds."
- **P6 (D8):** add under Days: "Order of events: day d's new documents go out at the start of day d. When you call `advance_day` on day d: (1) the mole may leak a document it received on days d−2..d; (2) restriction costs are charged; (3) day d's access logs and messages are created; then day d+1 starts. A leak at the end of day d with delay k appears in the feed from day d+k on."
- **P7 (D9, D15):** change the `list_documents` description to "List published documents with their recipients (and variants for canaries) in an inclusive day range." Change `search_messages` to "... (the first 20 matches in day order)". Add `minLength: 1` to `query`. Add "Messages for a day appear when that day ends."
- **P8 (D10):** when `p_single_dept_recipients` is 0, print "Every regular document goes to everyone in two randomly chosen departments." Annotate `noise: 1 (no change)` and `doc_recipient_share: 0 (off)`.
- **P9 (D11):** "Different topics, or the same topic on different days, are independent draws with the same probabilities. The decoy answers like any innocent employee."
- **P10 (D12, D16):** write "true V" in the EV formula, and use "Your Nth call is your last; unless it is `accuse`, the episode then ends with score 0."
- **P11 (D20):** "Tools that take an `employee` argument take exactly one id, such as e07. `plant_canary`'s `assignment` maps several ids to labels. `read_access_logs` without `employee` returns every employee's logs for the range."
- **P12 (D21):** state the defaults (`list_documents`: day 1 to today; `search_messages`: day 1 to the last day). Also add "`read_access_logs` returns nothing for a day that has not ended."

### How the audit relates to the measured failures
None of the findings explains the measured v1.4 losses (Part 1).
- Gemini's three costly decisions all rest on facts that are stated plainly with their numbers:
  - accusing below the EV line (the formula is printed);
  - interviewing instead of planting (interview LR 1.2; 2 canaries a day);
  - planting late (delay 2–3).
- Its two wrong accusations at P ≥ 0.95 come from the fingerprint noise, which the text calls "evidence, not proof".
- The text gaps most likely to cause errors in principle, D8 (order of events) and D3 (careful weight), do not appear in its transcripts as a cause: its canaries were valid, and its feed reads were on time.
- D19 is a risk for the judges' run, not an explanation of these results: the committed runs had no 3,600 s cap.
- The PLAN-95 B1 hint ablation (an opt-in sentence restating the EV rule and the delays) is the causal test that remains. If spelling those out moves Gemini toward the solver, the information was always enough and the failure is the decision.
