# Failure Gallery Spotlight: Below-Break-Even Accusations (`P < 1 / (1 + V)`)

*Reproduce offline with zero API keys: `python -m canary.gemini.gallery_breakeven --check`. Every figure below is computed deterministically from `results/failure_analysis_v1.4.json` and `data/runs/committed/v1.4/` via exact `Env` replay and `SolverPolicy` Bayesian belief updates.*

Companion to [`docs/reports/failure_gallery.md`](failure_gallery.md), where the `gemini-4-carbon/opencode/v1.4` row covers an 18-episode OpenCode v1.4 subset (`10` hard seeds `0..9` plus `8` medium seeds) under a fixed `P >= 0.60` cutoff. This spotlight audits all `30` judged hard seeds `0..29` against the moving break-even bar `1 / (1 + E[true V])`, exposing `seed 5` at `51.02%` vs `86.11%` break-even, `seed 23` at `45.17%` vs `81.22%`, and `seed 18` at `62.72%` vs `68.43%`.

## 1. The Moving Break-Even Bar `P*(V) = 1 / (1 + V)`

In Canary v1.4 hard (`40` employees, `21` days, wrong accusation score `-1.0`, abstention score `0.0`), the task instructions state the exact stopping condition explicitly:

> If day 21 ends and you have not accused anyone, your score is 0. So accusing is only worth it when `P(correct) x V + (1 - P(correct)) x (-1)` is greater than 0.

Solving `P * V - (1 - P) > 0` gives the exact break-even posterior threshold:

```text
EV(accuse | P, V) = P * V - (1 - P) = (1 + V) * (P - P*(V)),    where P*(V) = 1 / (1 + V)
```

Two structural consequences govern late-horizon decisions:

1. **Break-even rises monotonically as company value `V` decays.** At `V = 1.00` (day 1, zero damage), break-even is `1 / 2.00 = 50.00%`. At `V = 0.67`, break-even reaches `60.00%`. By `V = 0.46` (seed 18), break-even is `68.49%`; at `V = 0.23` (seed 23), `81.30%`; at `V = 0.16` (seed 5), `86.21%`; and at `V = 0.10` (in-process seed 5), `90.91%`. Fixed audit cutoffs (`P >= 0.50` for evidence-backed luck or `P >= 0.60` in `canary.analysis.accuse`) treat a `62.7%` accusation at `V = 0.46` as justified even though abstaining (`0.00`) strictly dominates it.
2. **Lucky coin-flips hide negative-EV blunders on the raw scoreboard.** Across the 30 judged-harness episodes (`opencode:google/gemini-4-carbon`, v1.4 hard seeds `0..29`), Gemini made `29` accusations and `1` abstention (seed 11). Exactly **3 accusations** (`seeds 5, 18, 23`) violated `P < 1 / (1 + V)` under all three company-value measures (`E[true V]`, ground-truth `V_true`, and even unadjusted shown `V_known`). Two of those three gambles happened to land on the mole (`+0.16` on seed 5, `+0.23` on seed 23) and one hit an innocent (`-1.00` on seed 18), masking **`-0.9348 V` of negative expected decision value** (`-0.9368 V` luck-adjusted) behind `+0.3268 V` of net realized luck.

## 2. Spotlight Table: OpenCode `gemini-4-carbon` Below-Break-Even Seeds

| seed | day | accused (mole) | consistent set | solver `P(accused)` | `E[true V]` (`V_true` / `V_known`) | break-even `1/(1+E[V])` (`1/(1+V_true)`) | margin `P - P*` | decision `EV` vs `0.0` | luck-adj `EV` (`V_true`) | `EV` on `V_known` | raw score (solver) | audit label (`P>=0.60` / `P>=0.50`) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | 21 | `e27` (`e27`, correct) | `{e27, e32}` (2) | **51.02%** (`0.5102`) | `0.1612` (`0.16` / `0.21`) | **86.11%** (86.21%) | `-35.09 pp` | **`-0.4075`** | **`-0.4082`** | `-0.3826` | `+0.16` (`+0.52`) | `lucky` / `correct_accusation` |
| 18 | 18 | `e29` (`e27`, WRONG) | `{e09, e27, e29, e37}` (4) | **62.72%** (`0.6272`) | `0.4612` (`0.46` / `0.51`) | **68.43%** (68.49%) | `-5.71 pp` | **`-0.0834`** | **`-0.0842`** | `-0.0529` | `-1.00` (`+0.52`) | `justified` / `wrong_accusation_evidence_backed` |
| 23 | 21 | `e29` (`e29`, correct) | `{e15, e29, e38}` (3) | **45.17%** (`0.4517`) | `0.2313` (`0.23` / `0.28`) | **81.22%** (81.30%) | `-36.05 pp` | **`-0.4438`** | **`-0.4444`** | `-0.4218` | `+0.23` (`+0.32`) | `lucky` / `correct_accusation` |
| **sum (3 seeds)** | | 2 correct, 1 wrong | mean `3.00` | mean `52.97%` | | mean `78.59%` | mean `-25.62 pp` | **`-0.9348`** | **`-0.9368`** | **`-0.8573`** | `-0.61` (`+1.36`) | 1 mislabeled `justified` |

Reference check on the same 30 seeds: `SolverPolicy` accused on `30/30` seeds with **0** below-break-even accusations; its tightest break-even margin across all 30 seeds was **`+11.60 pp`** (seed 10, `EV = +0.1405`).

## 3. Case-by-Case Forensic Anatomy (With Verbatim Transcript Proof)

Crucially, `gemini-4-carbon` did **not** forget the break-even formula. On **seed 11** (its lone abstention), it explicitly plugged its estimated posterior into `P * V - (1 - P)` and closed day 21 at `0.00`:

> `seed 11 transcript`: "accusing `e37` had negative expected value ($0.429 \times 0.20 - 0.571 = -0.485 < 0$), so abstaining by closing Day 21 for a guaranteed score of `0` maximized expected score."

Instead, on seeds 5, 18, and 23, `gemini-4-carbon` **miscalibrated its own posterior** above `80%` by (a) dropping negative evidence from unleaked canaries and (b) mispricing noisy after-hours access logs under hard-tier framing (`framing_rate = 2.0`, `50%` decoy / `50%` uniform across the 38 other innocents, which raises an innocent's after-hours rate from `0.1000/day` to `0.10 + 1.0/38 = 0.1263/day`).

### Seed 5: 51.02% Posterior vs 86.11% Break-Even (Horizon Coin-Flip Masked by Luck)

- **Trajectory & evidence:** Gemini planted `19` canaries and ran `103` interviews over `21` days (`0` canaries and `25` interviews across days `18..21`). Only one canary leak (`c17-2: v1`, group size `5`) surfaced on day 20, leaving two Finance employees consistent with every leak: `e27` and `e32`.
- **Exact Bayesian posterior vs break-even:** On Gemini's own observations, leak-only evidence (`behaviour_temper = 0`) actually favored `e32` (`e32` 61.16%, `e27` 34.33%) because `e27` held more unleaked canaries. Adding 20 days of access logs brought the full solver posterior to `e27` 51.02%, `e32` 47.64%, `e12` 0.64%. At `E[true V] = 0.1612` (`V_true = 0.16` after `13` leaks and `19` canaries), break-even was **`86.11%`** (`86.21%` on `V_true`). Accusing `e27` at `51.02%` was **`35.09 pp` below break-even**, with exact decision **`EV = -0.4075`** (`luck_adjusted = -0.4082`) against `0.00` for abstaining.
- **Why Gemini gambled:** Gemini ignored unleaked-canary negative evidence and over-counted raw interview/after-hours ratios:
  > `seed 5 transcript` (`t=194`, day `21`): "answered **evasively in 6/26 interviews** (23.1%, matching the 0.24 mole rate), compared to `e32`'s 5 after-hours accesses and 0/15 evasive interviews (>13:1 combined likelihood ratio in favor of `e27`)."
- **Scoreboard distortion:** Because `e27` happened to be the mole, Gemini recorded `+0.16` raw (realized luck **`+0.5682 V`**), hiding a `-0.4082 V` expected blunder. On the same seed, the solver isolated `e27` to a singleton on day `9` (`P = 98.19%`, score `+0.52`, luck-adjusted `+0.4926`).

### Seed 23: 45.17% Posterior vs 81.22% Break-Even (Sub-50% Shot on 3 Unresolved Suspects)

- **Trajectory & evidence:** Across `21` days, Gemini planted only `12` canaries (using both daily canary slots only once in 21 days; `0` canaries and `22` interviews across days `18..21`) and ran `86` interviews. At day 21, three Legal suspects remained consistent with all leaks: `e15`, `e29`, and `e38`.
- **Exact Bayesian posterior vs break-even:** Leak-only posterior placed `e29` third among the three consistent suspects (`e15` 31.80%, `e38` 31.44%, `e29` 29.42%). With access logs included, the solver posterior was `e29` 45.17%, `e15` 30.82%, `e38` 15.70%: less than a coin flip on `e29` (`45.17%`). With `E[true V] = 0.2313` (`V_true = 0.23`), break-even stood at **`81.22%`** (`81.30%` on `V_true`), leaving `e29` **`36.05 pp` below break-even** with exact decision **`EV = -0.4438`** (`luck_adjusted = -0.4444`) vs `0.00` for abstaining.
- **Why Gemini gambled:** Gemini treated `6` after-hours accesses over 20 days as a `~10x` likelihood spike without framing or unleaked-canary normalization:
  > `seed 23 transcript` (`t=175`, day `21`): "higher access-log likelihood ratio) and gave **7 evasive answers across 33 interviews**, making `e29` the highest-posterior suspect (`>82%`)."
- **Scoreboard distortion:** Hitting the `45.17%` shot yielded `+0.23` raw vs the solver's `+0.32` (day `18`, `P = 96.27%`), making the raw gap look like `+0.09 V` when the true luck-adjusted gap was **`+0.7151 V`** (masked by **`+0.6744 V`** of Gemini luck).

### Seed 18: 62.72% Posterior vs 68.43% Break-Even (Why Fixed 50%/60% Cutoffs Fail)

- **Trajectory & evidence:** By day 12, leaks narrowed Legal suspects to 4 employees (`e09`, `e27`, `e29`, `e37`), each carrying an identical leak-only posterior (`e09` 23.04%, `e27` 23.04%, `e29` 23.04%, `e37` 23.04%). Gemini then planted **`0` canaries across days `14..18`**, spending `32` interviews across those 5 days instead, and accused `e29` on day `18` with **`3` days still left** in the 21-day horizon.
- **Exact Bayesian posterior vs break-even:** Access logs lifted `e29` to `62.72%` (`e29` 62.72%, `e27` 14.47%, `e37` 11.17%, `e09` 6.25%), above both `0.50` and `0.60`. However, `8` leaks (`-0.40 V`) and `14` canaries (`-0.14 V`) had already lowered `V_true` to `0.46` (`E[true V] = 0.4612`, `V_known = 0.51`), pushing break-even `1 / (1 + V)` up to **`68.43%`** (`68.49%` on `V_true`, `66.23%` even on `V_known`). Thus `P = 62.72%` fell **`5.71 pp` below break-even**, with exact decision **`EV = -0.0834`** (`luck_adjusted = -0.0842`, `EV_known = -0.0529`).
- **Why Gemini gambled (and why fixed cutoffs misclassify it):** Gemini compared `e29`'s `33.3%` after-hours share against the unframed `10%` baseline (`0.1000/day` instead of framed `0.1263/day`):
  > `seed 18 transcript` (`t=179`, day `18`): "Across 17 closed days of logs, **`e29`** logged **6 after-hours accesses out of 18 total accesses (33.3%)**, matching the mole's 30% after-hours rate (vs. 10% innocent baseline) and yielding ~89% posterior probability (~11x higher than the next candidate, `e27`)."
  The true mole was `e27`, so Gemini scored `-1.00` (solver: `+0.52` on day `13`, `P = 95.58%`, singleton consistent set). Fixed-threshold audits (`canary.analysis.accuse` at `P >= 0.60` and fixed `P >= 0.50` gallery buckets) misclassify seed 18 as `justified` / `evidence-backed luck`, missing both the negative EV (`-0.0834`) and the unplayed splitting canary over `{e09, e27, e29, e37}` on days 14..16.
- **Extreme moving-bar check (in-process seed 5):** In the companion in-process `gemini-4-carbon` run on seed 5, Gemini accused `e27` on day 21 at **`P = 90.14%`**, yet `V_true` had decayed to `0.10` (`E[true V] = 0.0512`), where break-even `1 / (1 + V)` is **`90.91%`** (`95.12%` on `E[true V]`), making even a `90.14%` accusation negative-EV (`EV_exp = -0.0524`, `luck_adjusted = -0.0084`).

## 4. Exact Gap Accounting (Per-Seed and 30-Seed Additive Identity)

For every accused episode, `V_true = 1 - 0.05 * leaks - 0.01 * canaries - restrict_cost` and `luck_adjusted = V_true - (1 - P) * (1 + V_true)`. Consequently, `solver - Gemini` decomposes with zero residual:

| scope | leak term `0.05*(L_G-L_S)` | canary term `0.01*(C_G-C_S)` | restrict term | accusation penalty `(1-P)(1+V)` diff | abstention term | **luck-adj gap** | luck `(luck_S - luck_G)` | **raw gap** |
|---|---|---|---|---|---|---|---|---|
| seed 5 | `+0.3000` | `+0.0600` | `+0.0000` | **`+0.5407`** | `+0.0000` | **`+0.9007`** | `-0.5407` | **`+0.3600`** |
| seed 18 | `+0.1000` | `-0.0400` | `+0.0000` | **`+0.4770`** | `+0.0000` | **`+0.5370`** | `+0.9830` | **`+1.5200`** |
| seed 23 | `+0.2000` | `-0.1100` | `+0.0000` | **`+0.6251`** | `+0.0000` | **`+0.7151`** | `-0.6251` | **`+0.0900`** |
| **seeds 5, 18, 23 subtotal** | `+0.6000` | `-0.0900` | `+0.0000` | **`+1.6429`** | `+0.0000` | **`+2.1529`** | `-0.1829` | **`+1.9700`** |
| other 27 seeds (`0..29 \ {5,18,23}`) | `+1.1500` | `-1.6000` | `+0.1200` | `+1.7470` | `+0.6199` | `+2.0368` | `+1.2932` | `+3.3300` |
| **all 30 hard seeds (`0..29`)** | **`+1.7500`** | **`-1.6900`** | **`+0.1200`** | **`+3.3898`** | **`+0.6199`** | **`+4.1897`** | **`+1.1103`** | **`+5.3000`** |

Share of the gap carried by the 3 below-break-even seeds (`5, 18, 23`):

- **Accusation-penalty gap:** `+1.6429 V` out of `+3.3898 V` (**`48.46%`** of Gemini's total accusation-penalty shortfall; the remaining 6 positive-EV unisolated accusations contribute `+1.8573 V` and the 20 isolated accusations net `-0.1104 V`).
- **Total 30-seed luck-adjusted gap:** `+1.6429 V` penalty alone is **`39.21%`** of the entire `+4.1897 V` luck-adjusted gap (and total luck-adjusted gap on seeds `5, 18, 23` is **`+2.1529 V`**, or **`51.38%`** of the 30-seed gap).

### Zero-Exploration Abstention Counterfactual on Seeds `5, 18, 23`

If OpenCode `gemini-4-carbon` changed **zero** exploration actions and simply abstained (`score = 0.00`) whenever `P(accused) < 1 / (1 + E[true V])` (as it did on seed 11):

- **Expected decision value gain (`0 - sum(EV_exp)`):** **`+0.9348 V`** across 30 seeds (`+0.0312 V/episode`).
- **Luck-adjusted score gain (`0 - sum(LA)`):** **`+0.9368 V`** across 30 seeds (`+0.0312 V/episode`), lifting mean luck-adjusted score from **`0.3596`** (`72.03%` of solver) to **`0.3909`** (**`78.28%`** of solver) and cutting the 30-seed luck-adjusted gap by **`22.36%`** (`+4.1897 V` -> `+3.2529 V`).
- **Realized raw score gain (`0 - sum(raw)`):** **`+0.61 V`** (`0.3223` -> `0.3427` mean raw score), even after forfeiting the two lucky hits (`+0.16` and `+0.23`) to avoid the single `-1.00` wrong accusation.

## 5. Cross-Cohort Break-Even Discipline on Committed v1.4 Hard (`seeds 0..29`, Never Pooled)

| committed v1.4 hard cohort (`seeds 0..29`) | accused / abstained | below `1/(1+E[V])` | seeds below break-even | below-BE `sum(EV_exp)` | below-BE `sum(LA)` | below-BE `sum(raw)` | realized luck on below-BE | cohort raw mean | cohort luck-adj mean (% of solver) |
|---|---|---|---|---|---|---|---|---|---|
| `opencode:google/gemini-3.5-flash` | `30 / 0` | **`10`** (`7` hit, `3` wrong) | `0, 2, 3, 10, 17, 18, 21, 23, 26, 27` | `-7.0172` | `-6.9978` | `-0.45` | `+6.5478` | `0.3730` | `0.1098` (`22.0%`) |
| **`opencode:google/gemini-4-carbon`** (judged) | `29 / 1` | **`3`** (`2` hit, `1` wrong) | `5, 18, 23` | `-0.9348` | `-0.9368` | `-0.61` | `+0.3268` | `0.3223` | `0.3596` (`72.0%`) |
| `inproc:gemini-4-carbon` | `29 / 1` | **`3`** (`2` hit, `1` wrong) | `5, 6, 22` | `-0.2940` | `-0.2235` | `-0.40` | `-0.1765` | `0.4730` | `0.4211` (`84.3%`) |
| `solver` (reference) | `30 / 0` | **`0`** (`0` hit, `0` wrong) | `none` | `+0.0000` | `+0.0000` | `+0.00` | `+0.0000` | `0.4990` | `0.4993` (`100.0%`) |

Across models and harnesses on the exact same 30 hard seeds, below-break-even gambling tracks capability cleanly: `opencode-gemini-3.5-flash` never abstains (`30/30`) and takes `10` negative-EV shots (`-7.0172 V` decision EV, bailed out by `+6.5478 V` of lucky hits so its `0.3730` raw mean masks a `0.1098` luck-adjusted mean, `22.0%` of solver); `opencode-gemini-4-carbon` cuts that to `3` negative-EV shots (`-0.9348 V` decision EV, `72.0%` of solver luck-adjusted); `inproc-gemini-4-carbon` trims the EV loss on its `3` borderline shots to `-0.2940 V` (`84.3%` of solver); and `SolverPolicy` takes `0` negative-EV shots (`100.0%`).
