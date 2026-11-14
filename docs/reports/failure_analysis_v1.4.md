# Failure analysis, rules v1.4 hard: Gemini over MCP vs the reference solver

**Scope.** The judges' harness (OpenCode + `gemini-4-carbon` over MCP), rules v1.4, hard tier, dev seeds 0–29, each episode paired with the reference solver on the same seed. This is the run behind the headline **65% of the solver** (72% luck-adjusted) in `docs/reports/gap.md`. Every number below is computed by `scripts/failure_analysis_v14.py` from the committed episodes (`data/runs/committed/v1.4/`). The script replays every episode in a fresh Env and aborts unless the replay reproduces the recorded score. Raw per-episode output: `results/failure_analysis_v1.4.json`. Reproduce (no keys, a few seconds): `uv run python scripts/failure_analysis_v14.py`.

**Bottom line.**
- **The expected story is half right.** Gemini under-explores. It plants 8.5 canaries against 14.1, spends the daily action budget on 68 near-worthless interviews per episode, and identifies the mole later (day 13.4 vs 10.6). But the V drained by waiting (+1.75 V over 30 seeds) is almost exactly repaid by the canaries it never bought (-1.69 V).
- **What under-exploration actually costs is thin evidence at the moment of commitment.** 9 of 29 accusations were made while two or more people were still consistent with every leak (solver: 3 of 30). That is the largest mistake, 3.39 V of expected value. It includes 3 negative-EV accusations near the horizon.
- **The four wrong accusations:** two are disclosed fingerprint noise at P ≥ 0.95 (luck). One is a P 0.80 bet on an unresolved pair, which the solver also lost on the same seed. One is a negative-EV gamble. Gemini's posteriors predicted 3.4 wrong accusations, and it made 4.

**Companion.** The Gemini Failure Atlas (`results/gemini/atlas.md`, Gemini CEO) reads every trajectory of every cohort and names failure modes by share of solver regret. This report is narrower and deeper. It covers one judged tier and one run, and it accounts for every point of the gap to the solver exactly. It also tests the "was the information there?" question with counterfactual replays. The two use different units: the atlas measures per-step regret across 153 episodes, and this report measures paired V on 30 seeds. Where they overlap, they agree on the first mode, accusing on sub-threshold evidence.

**Definitions.**
- *Solver posterior* is the reference `SolverPolicy`'s exact Bayesian posterior computed from **the agent's own tool results only** (as in `canary/analysis/accuse.py`). Whatever it says, the agent had the evidence for it.
- *Solver rule* is the solver's own accusation rule applied to that posterior: accuse the top suspect when P ≥ 0.85 and EV = P·E[true V] − (1−P) > 0, or on the last day when EV > 0.
- *Consistent set* is the set of employees who held every leaked regular document (recipients are public through the free `list_documents`) and got the shown label of every leaked canary, in the agent's last leak-feed read. A size of 1 means the leaks alone isolate one person, up to the stated 5% fingerprint noise.
- *Luck-adjusted score* is P·V − (1−P) at the accusation, and 0 without one. This is the definition used in `scripts/paired_v13.py`.

## 1. Headline numbers (30 paired seeds)

| | **Gemini, OpenCode/MCP** | **reference solver** | Gemini in-process (context) |
|---|---|---|---|
| mean score | 0.322 ± 0.199 | 0.499 ± 0.119 | 0.473 ± 0.118 |
| luck-adjusted score | 0.360 | 0.499 | 0.421 |
| canaries planted before the accusation | **8.5** ± 1.3 | **14.1** ± 1.8 | **8.6** ± 1.2 |
| canary capacity used (2/day) | 32% | 67% | 33% |
| days with ≥1 canary | 38% | 91% | 41% |
| first canary (day) | 3.0 | 1.0 | 3.4 |
| staff who ever received a canary (of 40) | 27.8 | 38.6 | 27.6 |
| recipients / labels per canary | 10.1 / 3.0 | 9.9 / 3.0 | 10.3 / 3.0 |
| interviews per episode | 68 | 0 | 57 |
| leak-feed reads / access-log reads | 6.7 / 12.3 | 10.6 / 9.6 | 6.3 / 11.8 |
| accusation day (accused episodes) | **13.2** | **10.6** | **12.7** |
| accusation day (abstentions counted as day 21) | 13.4 | 10.6 | 13.0 |
| leaks before the accusation | 7.3 | 6.1 | 7.4 |
| solver posterior P(accused) at the accusation, mean / median | 0.88 / 0.96 | 0.97 / 0.98 | 0.93 / 0.98 |
| accusations at P ≥ 0.95 / 0.85–0.95 / 0.60–0.85 / < 0.60 | 16 / 3 / 8 / 2 | 24 / 6 / 0 / 0 | 18 / 7 / 3 / 1 |
| accusations with EV < 0 (by the solver posterior) | 3 | 0 | 3 |
| accusations made while the leaks had isolated one person | 20 / 29 | 26 / 30 | 21 / 29 |
| wrong accusations (expected from the posteriors) | **4** (3.4) | **1** (1.0) | **1** (2.0) |
| abstentions (no accusation by day 21) | 1 / 30 | 0 / 30 | 1 / 30 |

The reviewer's figures check out. Gemini plants 8.5 canaries against the solver's 14.1. It accuses on day 13.4 against day 10.6, counting the one abstention as day 21 (13.2 over the 29 accusations). Its 4 wrong accusations were made at solver posteriors 0.99, 0.80, 0.63, 0.95 (seeds 1, 15, 18, 26).

## 2. Where the gap comes from (exact accounting)

Summed over the 30 seeds, the solver scores **5.30 V** more than Gemini (0.177 per episode, the paired difference in gap.md).

**By episode outcome (the raw scoreboard):**

| Gemini outcome | seeds | solver − Gemini (V) |
|---|---|---|
| wrong accusation | 4 | 4.90 |
| abstained | 1 | 0.62 |
| correct accusation | 25 | -0.22 |
| **total** | 30 | **5.30** |

On the 25 seeds where both agents accused correctly, Gemini scores 0.547 against the solver's 0.538. That is no loss, even though it accuses later (day 12.9 vs 10.9, later on 16 of 25 seeds) and takes 7.4 leaks against 6.4. The extra leak damage is paid for by the canaries it never bought (8.0 vs 14.4 at 0.01 V each). So the raw gap is the wrong accusations plus one abstention. The question is how much of that is skill and how much is luck.

**Luck-adjusted, by mistake (an additive identity; the script asserts that it sums).** For an accused episode, V = 1 − 0.05·leaks − 0.01·canaries − restriction costs, and the luck-adjusted score is V − (1−P)(1+V). So the solver-minus-Gemini luck-adjusted gap splits exactly into the terms below. Luck is the realised score minus the luck-adjusted score.

| # | mistake (ranked by expected V lost) | V lost, 30 seeds | per episode |
|---|---|---|---|
| 1 | Accusing on evidence that had not isolated the mole (expected loss (1−P)(1+V) at the accusation, vs the solver's) | +3.39 | +0.113 |
| 2 | Never reaching an accusable posterior → abstained (seed 11) | +0.62 | +0.021 |
| 3 | Extra leak damage from accusing later | +1.75 | +0.058 |
| 4 | Restriction costs | +0.12 | +0.004 |
| 5 | Canary costs *saved* by planting fewer canaries | -1.69 | -0.056 |
| | **luck-adjusted gap** | **+4.19** | +0.140 |
| | bad luck (realised − expected; Gemini -1.12, solver -0.01) | +1.11 | +0.037 |
| | **raw gap** | **+5.30** | +0.177 |

- Row 1 comes entirely from the 9 accusations Gemini made while two or more employees were still consistent with every leak (seeds 3, 5, 7, 8, 14, 15, 18, 20, 23). Those account for 3.50 V, and the 20 isolated accusations net -0.11. 1.64 V of it is the three accusations with **negative EV** under the solver posterior (seeds 5, 18, 23, all on day ≥ 18), where abstaining (score 0) was better by the formula the instructions print. The solver accused at a consistent set of 1 in 26/30 episodes and never at EV < 0.
- Rows 3 and 5 nearly cancel (+1.75 and -1.69). Accusing later drains V, but Gemini financed the wait by not paying for canaries, so waiting by itself is close to free here. What under-exploration really costs is row 1: the evidence is *thinner* at the moment Gemini commits.
- *Hesitation*, meaning the agent had decisive evidence and still waited, is small. On only 5 seeds (4, 17, 21, 24, 25) did the solver rule fire on Gemini's own evidence before Gemini accused. There it waited 2.2 more days on average, and the top suspect was always the mole. Accusing at that moment (exact counterfactual replay) would have added 0.37 V in total.
- Luck: Gemini's posteriors predicted 3.4 wrong accusations and it made 4 (P(≥ 4 | its posteriors) = 0.46), so the count is not anomalous. The solver's posteriors predicted 1.0 and it made 1. Gemini was not unlucky overall. It took bets that the evidence priced at about three lost accusations in 29, against about one for the solver.

## 3. The four wrong accusations

| seed | day | accused | mole | solver P(accused) | EV | consistent set at accusation | fingerprint flip? | solver on this seed | reading |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 19 | e39 | e33 | 0.99 | +0.31 | e39 | yes | correct (+0.69) | **luck**: the one label that singled out e39 was a 5% fingerprint flip (rules: "evidence, not proof") |
| 15 | 12 | e34 | e37 | 0.80 | +0.32 | e34, e37 | no | wrong (-1.00) | **resolvable**: e34 and e37 sat in the same variant of every canary; one split canary would have separated them with 9 days left. The solver also lost this seed (to a flip) |
| 18 | 18 | e29 | e27 | 0.63 | -0.08 | e09, e27, e29, e37 | no | correct (+0.52) | **a gamble**: 4 people still consistent, EV < 0, and Gemini planted no canary on days 14–18 |
| 26 | 10 | e04 | e08 | 0.95 | +0.54 | e04 | yes | correct (+0.69) | **luck**: the label that pointed at e04 was a fingerprint flip |

The honest verdict: **two of the four are bad luck that the rules disclose** (seeds 1 and 26, P ≥ 0.95, wrecked by the stated 5% fingerprint noise). On that same evidence the solver's own rule (P ≥ 0.85, EV > 0) accuses the same innocent. **One is a real gamble** (seed 18, EV −0.08 at P 0.63, day 18). **One is a defensible bet on an unresolved pair** (seed 15, P 0.80, EV +0.32), and the solver itself lost this seed. So "luck, not gambling" holds for three of the four, not for all four. Across all 29 accusations Gemini did take three negative-EV shots at the horizon (seeds 5, 18, 23). Two of them happened to land (+0.16, +0.23) and one did not (−1.00).

## 4. How Gemini commits: single canary hits

Canary hits on the accused in Gemini's last feed read before accusing: 2 accusation(s) with 0 hit(s), 9 accusation(s) with 1 hit(s), 14 accusation(s) with 2 hit(s), 4 accusation(s) with 3 hit(s). The solver: 15 with 1, 12 with 2, 3 with 3.

Gemini accused on a **single canary hit 9 times out of 29** (the hit variant had 5.3 holders on average). It accused with **no canary hit at all** 2 times, on regular-document leaks and logs only. Both of those were correct. The solver accuses on a single hit even more often (15/30, holders 3.3). A single hit is not the problem. The solver's single hit lands on a group that the regular leaks have *already* narrowed, so the consistent set is 1 (mean consistent-set size at accusation: solver 1.1, Gemini 1.8). Gemini's single hits often leave several people standing.

## 5. Root cause: under-exploration, and why the information was there

Each mistake traces back to one decision about a tool the agent had.

1. **Interviews instead of canaries (the daily action budget).** Gemini runs 68 interviews per episode. On 242 of the 303 days on which it planted fewer than 2 canaries, it had used all 8 daily actions, 1503 of them on interviews. The instructions state the interview likelihood ratio: the mole is evasive with probability 0.2 × 1.2, against 0.2 for an innocent. An interview is therefore worth at most 0.005 nats (the KL divergence between the mole's and an innocent's answer), while a well-split canary is worth up to ln 3 ≈ 1.1 nats when it leaks. The solver never interviews and plants on 91% of its days, against Gemini's 38%. **Decision that would have avoided it:** use the second `plant_canary` slot each day instead of interviews.
2. **Late and intermittent canaries.** Gemini's first canary comes on day 3.0 on average, against day 1 for the solver, and it often plants two canaries every *other* day (seed 11 and seed 4 below). With a stated delay of 2–3 days, every skipped day pushes the next answer back by a day. Result: capacity used 32% against 67%, and 8.5 against 14.1 canaries.
3. **Committing before the leaks isolate one person.** This is the most expensive mistake (row 1). When the consistent set is 2–4 people, one canary that gives each of them a different label settles it in 2–3 days. Seed 15 had 9 days left and seed 18 had 3. **Decision:** plant the splitting canary, or abstain if EV < 0. Both options are named in the instructions.
4. **The abstention (seed 11).** Here Gemini's own evidence never passed P = 0.40. The consistent set stuck at 7 from day 8, while Gemini planted 12 canaries on alternate days and ran 121 interviews. Abstaining was the right call on that evidence. The loss (0.62 V) is the evidence it never collected: the solver, on the same seed, accused correctly on day 9.

**The information and tools were available. Evidence:**
- *Same observations.* The solver posterior above is computed **only from tool results Gemini itself received**. When it shows P ≥ 0.85 while Gemini waits (5 seeds), or a consistent set of 4 when Gemini accuses (seed 18), that is a fact about Gemini's own transcript, not about something hidden.
- *Same tools, same budgets.* On the same 30 seeds, the solver uses only the 13 public tools under the same 8-actions/day and 2-canaries/day limits, makes 84 calls against Gemini's 128, and reaches a consistent set of 1 in 26/30 episodes by day 10.6.
- *Nothing missed in the feed.* Gemini read the leak feed on the days that known V dropped. Its average lag between a leak surfacing and Gemini seeing it is 0.00 days, so it did not lose information by reading the feed less often (6.7 reads against 10.6).
- *Not a harness artifact.* The in-process run (full history, thought-signature replay) shows the same exploration profile: 8.6 canaries, 57 interviews, and 33% capacity. It had fewer wrong accusations (1, expected 2.0) and fewer sub-0.85 accusations (4 vs 10). Under-exploration is a trait of the model, and the OpenCode run additionally commits on thinner evidence.
- *The rules are stated.* Interview LR, delay 2–3, fingerprint accuracy 0.95 ("evidence, not proof"), 2 canaries/day × 3 labels, and the EV-to-accuse formula all appear in the instructions (see `docs/DIFFICULTY.md` for the audit).

## 6. Two annotated episodes

### Seed 4: slow identification (correct, +0.40 vs solver +0.73)

Gemini plants nothing on days 1–4 and runs 6–7 interviews a day. From day 5 it plants two canaries every other day. The solver plants 2 a day from day 1, and its day-1–3 canaries surface by day 4. It accuses on day 5.

| day | Gemini: canaries / interviews | Gemini: P(top) on its own evidence (top = mole?) | Gemini: # consistent | solver: canaries | solver: P(top) (top = mole?) | solver: # consistent |
|---|---|---|---|---|---|---|
| 1 | 0 / 6 | 0.03 (e00) | 40 | 2 | 0.03 (e00) | 40 |
| 2 | 0 / 6 | 0.04 (e01) | 40 | 2 | 0.04 (e31) | 40 |
| 3 | 0 / 7 | 0.04 (e08) | 40 | 2 | 0.06 (e31) | 40 |
| 4 | 0 / 6 | 0.06 (e29) | 40 | 1 | 0.75 (e11, mole) | 2 |
| 5 | 2 / 4 | 0.15 (e29) | 19 | 0 | **accuse** 1.00 (e11, mole) | 0 |
| 6 | 0 / 7 | 0.15 (e29) | 19 |  |  |  |
| 7 | 2 / 4 | 0.24 (e29) | 9 |  |  |  |
| 8 | 0 / 6 | 0.25 (e29) | 9 |  |  |  |
| 9 | 2 / 4 | 0.28 (e29) | 9 |  |  |  |
| 10 | 0 / 6 | 0.34 (e29) | 9 |  |  |  |
| 11 | 2 / 4 | 0.29 (e29) | 9 |  |  |  |
| 12 | 0 / 7 | 0.30 (e29) | 9 |  |  |  |
| 13 | 2 / 4 | 0.27 (e29) | 9 |  |  |  |
| 14 | 0 / 6 | 0.95 (e11, mole) | 1 |  |  |  |
| 15 | 0 / 7 | 0.96 (e11, mole) | 1 |  |  |  |
| 16 | 0 / 0 | **accuse** 0.99 (e11, mole) | 1 |  |  |  |

The solver rule fires on Gemini's own evidence at the end of day 14 (P 0.95 on the mole, consistent set 1). Gemini spends two more days interviewing and accuses on day 16. Accusing on day 14 would have scored 0.50 (exact replay) instead of 0.40. The other 9 days of the gap with the solver come from exploring late and at half capacity, not from hesitation.

### Seed 18: committing on an unresolved group (wrong, −1.00 vs solver +0.52)

Both agents narrow the field to 12 by day 6. On day 12 Gemini's leaks leave 4 people consistent (e09, e27, e29, e37). Gemini plants two canaries on days 12 and 13 and then none on days 14–17, filling those days with interviews.

| day | Gemini: canaries / interviews | Gemini: P(top) on its own evidence (top = mole?) | Gemini: # consistent | solver: canaries | solver: P(top) (top = mole?) | solver: # consistent |
|---|---|---|---|---|---|---|
| 1 | 2 / 4 | 0.03 (e03) | 40 | 2 | 0.03 (e00) | 40 |
| 2 | 1 / 5 | 0.04 (e17) | 40 | 2 | 0.04 (e03) | 40 |
| 3 | 0 / 5 | 0.05 (e33) | 40 | 2 | 0.04 (e03) | 40 |
| 4 | 2 / 4 | 0.10 (e17) | 16 | 2 | 0.11 (e20) | 16 |
| 5 | 0 / 7 | 0.10 (e19) | 16 | 2 | 0.14 (e03) | 12 |
| 6 | 1 / 5 | 0.18 (e29) | 12 | 1 | 0.16 (e38) | 12 |
| 7 | 1 / 6 | 0.17 (e17) | 12 | 1 | 0.25 (e27, mole) | 12 |
| 8 | 0 / 7 | 0.16 (e17) | 12 | 1 | 0.23 (e27, mole) | 12 |
| 9 | 2 / 4 | 0.17 (e17) | 12 | 2 | 0.21 (e27, mole) | 12 |
| 10 | 1 / 6 | 0.17 (e17) | 12 | 1 | 0.28 (e27, mole) | 12 |
| 11 | 0 / 7 | 0.17 (e17) | 12 | 1 | 0.25 (e27, mole) | 12 |
| 12 | 2 / 4 | 0.47 (e29) | 4 | 1 | 0.25 (e24) | 12 |
| 13 | 2 / 5 | 0.42 (e29) | 4 | 0 | **accuse** 0.96 (e27, mole) | 1 |
| 14 | 0 / 6 | 0.36 (e29) | 4 |  |  |  |
| 15 | 0 / 7 | 0.52 (e29) | 4 |  |  |  |
| 16 | 0 / 6 | 0.67 (e29) | 4 |  |  |  |
| 17 | 0 / 7 | 0.61 (e29) | 4 |  |  |  |
| 18 | 0 / 6 | **accuse** 0.63 (e29) | 4 |  |  |  |

On day 18 it accuses e29 at P 0.63. EV is -0.08 by the formula in the instructions, so abstaining scored more, and 4 people were still consistent. The mole was e27. A canary on day 14–16 giving each of the four a different label (3 labels + 1 non-recipient) shows in the feed 2–3 days after the mole leaks it. A leak on the planting day would have surfaced on day 16–19, inside the 21-day horizon. The solver's canaries isolate e27 by day 13.

## 7. Per-seed table

| seed | Gemini score | solver score | Gemini day | solver day | Gemini canaries | solver canaries | Gemini interviews | P(accused) | EV | # consistent | canary hits on accused | solver-rule decisive earlier? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | +0.59 | +0.64 | 11 | 9 | 6 | 11 | 57 | 0.98 | +0.51 | 1 | 2 |  |
| 1 | -1.00 ✗ | +0.69 | 19 | 7 | 15 | 11 | 90 | 0.99 | +0.31 | 1 | 3 |  |
| 2 | +0.48 | +0.58 | 14 | 9 | 7 | 12 | 80 | 0.97 | +0.44 | 1 | 2 |  |
| 3 | +0.51 | +0.28 | 19 | 18 | 7 | 22 | 40 | 0.77 | +0.12 | 10 | 0 |  |
| 4 | +0.40 | +0.73 | 16 | 5 | 10 | 7 | 84 | 0.99 | +0.39 | 1 | 2 | day 14 (cf +0.50) |
| 5 | +0.16 | +0.52 | 21 | 9 | 19 | 13 | 103 | 0.51 | -0.41 | 2 | 1 |  |
| 6 | +0.73 | +0.71 | 6 | 6 | 7 | 9 | 25 | 1.00 | +0.68 | 1 | 2 |  |
| 7 | +0.69 | +0.64 | 10 | 9 | 6 | 11 | 57 | 0.78 | +0.36 | 3 | 1 |  |
| 8 | +0.35 | +0.26 | 14 | 21 | 10 | 24 | 79 | 0.83 | +0.12 | 2 | 1 |  |
| 9 | +0.60 | +0.71 | 15 | 6 | 10 | 9 | 85 | 0.93 | +0.49 | 1 | 1 |  |
| 10 | +0.40 | +0.21 | 16 | 19 | 8 | 24 | 85 | 0.93 | +0.26 | 1 | 1 |  |
| 11 | +0.00 | +0.62 | — | 9 | 12 | 13 | 121 | — | — | — | — |  |
| 12 | +0.65 | +0.48 | 9 | 12 | 10 | 17 | 40 | 0.98 | +0.61 | 1 | 2 |  |
| 13 | +0.40 | +0.34 | 13 | 17 | 10 | 21 | 70 | 0.98 | +0.37 | 1 | 2 |  |
| 14 | +0.71 | +0.23 | 8 | 15 | 4 | 17 | 44 | 0.77 | +0.28 | 2 | 1 |  |
| 15 | -1.00 ✗ | -1.00 | 12 | 9 | 6 | 11 | 68 | 0.80 | +0.32 | 2 | 2 |  |
| 16 | +0.70 | +0.69 | 10 | 8 | 5 | 11 | 51 | 0.97 | +0.64 | 1 | 2 |  |
| 17 | +0.54 | +0.77 | 10 | 5 | 6 | 8 | 49 | 1.00 | +0.53 | 1 | 3 | day 8 (cf +0.64) |
| 18 | -1.00 ✗ | +0.52 | 18 | 13 | 14 | 18 | 101 | 0.63 | -0.08 | 4 | 1 |  |
| 19 | +0.62 | +0.67 | 11 | 9 | 8 | 13 | 60 | 0.96 | +0.56 | 1 | 2 |  |
| 20 | +0.66 | +0.53 | 11 | 12 | 4 | 17 | 66 | 0.71 | +0.18 | 5 | 0 |  |
| 21 | +0.69 | +0.73 | 10 | 9 | 6 | 12 | 58 | 0.82 | +0.39 | 1 | 1 | day 8 (cf +0.74) |
| 22 | +0.64 | +0.40 | 14 | 15 | 6 | 20 | 82 | 0.94 | +0.50 | 1 | 2 |  |
| 23 | +0.23 | +0.32 | 21 | 18 | 12 | 23 | 86 | 0.45 | -0.44 | 3 | 1 |  |
| 24 | +0.67 | +0.31 | 13 | 14 | 8 | 19 | 69 | 1.00 | +0.66 | 1 | 2 | day 9 (cf +0.79) |
| 25 | +0.72 | +0.58 | 11 | 8 | 3 | 12 | 60 | 1.00 | +0.67 | 1 | 3 | day 10 (cf +0.72) |
| 26 | -1.00 ✗ | +0.69 | 10 | 7 | 8 | 11 | 43 | 0.95 | +0.54 | 1 | 2 |  |
| 27 | +0.46 | +0.72 | 15 | 6 | 14 | 8 | 78 | 1.00 | +0.46 | 1 | 2 |  |
| 28 | +0.64 | +0.75 | 12 | 6 | 6 | 10 | 64 | 0.98 | +0.56 | 1 | 3 |  |
| 29 | +0.43 | +0.65 | 13 | 8 | 7 | 10 | 46 | 0.96 | +0.38 | 1 | 2 |  |

✗ = wrong accusation. *cf* = exact score had Gemini accused the top suspect at that end of day.

## 8. Context from other analyses (cited, not recomputed by this script)

- **The reference is a fair bar.** HEAD-ENV's `docs/reports/reference_optimality.md` (on justSilas via PR #20; hard dev seeds 8000–8399) finds the v1.4 solver's posterior *calibrated*: accuracy at accusation is 96–99% on hard, and P(top = mole) tracks the posterior across all decision days. This is the property the luck adjustment and the "expected wrong accusations" above rely on. It also finds the solver's stopping *near-optimal*: the best p ≥ a + b·V rule adds +0.005 on hard. Its hard loss is information-rate bound, made of leak damage 0.250 plus canary cost 0.120 out of 0.422, and a stronger `solver_v2` gained only +0.012 ± 0.029 on fresh seeds. So Gemini's shortfall measured against it is Gemini's own, not a soft reference.
- **Why hard and not medium.** S3's scripted version of the Gemini swarm's w2b-008 plan is a no-Bayes elimination heuristic that intersects suspects with the recipients of leaked documents and canaries and accuses only when one suspect is left (`canary/redteam/swarm_probes.py` on `s3-integrity` d3e7629, work in progress, numbers as reported by S3). On 40 judge seeds per tier it ties the solver on easy (+0.742 vs +0.765) and medium (+0.648 vs +0.671), but falls clearly behind on hard (+0.363 vs +0.545, 3 wrong). That matches the pattern here. On medium, set elimination is enough, so frontier parity there (OpenCode 111%) is expected. On hard, fingerprint noise and the 2–3-day delays break strict elimination (seeds 1 and 26 above: the strict consistent set excluded the true mole after a flip), and weighing evidence and choosing what to test next is what pays.

## 9. What this means for the rubric

- **Main mistakes, tied to decisions:** (1) committing before the leaks isolate one person, including three negative-EV shots at the horizon; (2) spending the daily action budget on interviews instead of the second canary; (3) late, every-other-day canaries. Each one maps to a tool call the agent could have made differently.
- **Information and tools available:** the solver posterior is computed from Gemini's own observations, and the solver reaches decisive evidence with the same tools and budgets on the same seeds.
- **Not withheld info or trick wording:** two of the four wrong accusations come from the disclosed 5% fingerprint noise, which hits any investigator. The instruction audit (`docs/DIFFICULTY.md`) finds no hidden rule.
- **Caveat:** n = 30 and the raw ratio's CI is wide (gap.md). The decomposition is exact for these 30 episodes, but the shares carry sampling noise. This is one model (gemini-4-carbon). A second family is a PLAN-95 item.
