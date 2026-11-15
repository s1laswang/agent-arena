# Saltless Harbor Trajectory Posteriors and Luck-Adjusted Scoring on Real `rehearsal-dry` Judge Runs

**Scope.** Rules `v1.4`, `hard` tier, all `10` real Harbor judge tasks (`hard-900000..hard-900009`) from `results/harbor/rehearsal-dry/` (`SALT` unpublished, zero ground-truth mole access, HMAC-verified server ledgers + `ATIF-v1.7` OpenCode MCP trajectories).
Reproduce or verify in <2 s with zero API keys:

```bash
python scripts/harbor_luck_adjusted_v14.py
python scripts/harbor_luck_adjusted_v14.py --check
```

## Executive Summary: Saltless Rao-Blackwellization on Unpublished-`SALT` Judge Worlds

On live Harbor judge builds (`python harbor/build.py`), the 32-byte world secret (`SALT`) is unpublished, so `Env('hard', seed)` replay cannot be run offline. However, every Harbor OpenCode container writes `agent/trajectory.json` (`ATIF-v1.7` with every `canary_<tool>` call and exact server JSON observation) alongside HMAC-signed `artifacts/ledger.json` (which records exact `true_V` at episode end even when `score == -1.0`). Feeding those public tool observations into `SolverPolicy` recovers exact Bayesian posteriors `P(accused)` and Rao-Blackwell luck-adjusted scores `P(accused) * true_V - (1 - P(accused))` **100% saltlessly**:

1. **Why raw `n=10` had a `[11%, 355%]` CI -- and how saltless posteriors resolve it:** On `rehearsal-dry`, raw means are `+0.398` (`opencode` `gemini-4-carbon`, `7` primary + `3` `opencode-infra-rerun` = `10` valid trials) vs `+0.467` (`oracle`), giving raw ratio **`85% [11%, 355%]`** (paired diff `-0.069`, variance `0.6279`). Both policies went `9/10` (`90%`) and suffered **one `-1.00` wrong accusation on Day 16 via a 5% canary fingerprint flip (`fingerprint_accuracy = 0.95`) on `c12`** -- on **different tasks** (`oracle` on `hard-900000`, `opencode` on `hard-900005` where `P(accused) = 0.914`, `LA = +0.271`), while `opencode` also won a negative-EV coin-flip gamble on `hard-900004` (`P(accused) = 0.520 < 0.60`, `LA = -0.169`, `+0.769 V` windfall).
2. **3.28x single-agent and 4.37x paired variance reduction (confirming `judge_rerun_power_v14` out of sample):** Saltless Rao-Blackwellization shifts `opencode` from `+0.398 +/- 0.314` raw (`SD = 0.507`) to **`+0.388 +/- 0.173`** (bootstrap 95% CI `[+0.215, +0.541]`, `SD = 0.280`), cutting single-agent score variance by **`3.28x`**. Paired against same-build `true_V`-calibrated `oracle` (`+0.542`), paired diff variance drops **`4.37x`** (`0.6279` -> `0.1436`, matching `judge_rerun_power_v14` Model B's analytical `4.22x` prediction) and recovers a **`71.6%`** (`72% [36%, 111%]`) frontier/oracle ratio -- **matching the 30-seed committed `v1.4` dev headline (`72% [52%, 91%]`) to within 0.5 percentage points!**
3. **Bit-exact dev equivalence (`0.0` error across `29` accused episodes):** Converting all `30` committed `v1.4/opencode-gemini-4-carbon/hard` dev episodes into synthetic ATIF trajectories (with non-MCP `bash` and orphan tool-call noise injected) and scoring them saltlessly agrees with `Env`-replayed `SolverPolicy` posteriors to **`0.0e+00`** (`<= 1e-12`) and with `paired_v13.p_acc` to **`0.0e+00`**.

---

## 1. Per-Task Saltless OpenCode Posteriors vs Paired `oracle` (`hard-900000..900009`)

Following `scripts/rehearsal_table.py`, tasks `hard-900006` (`provider rate limit`), `hard-900007` (`provider rate limit`), and `hard-900009` (`thought_signature rejected`) were unresolved (`done=false`) in primary `opencode` and are filled from `opencode-infra-rerun` (marked `[rerun]`). Every trial passes HMAC-SHA256 verification against `<job>/ledger_key` and `shown_V - true_V == 0.05 * unsurfaced_leaks`.

| Task | Source | Accused | Cor | Day | Raw | `true_V` | `shown_V` | `P(acc)` | `P(top)` | Luck-Adj | Luck (`Raw-LA`) | Can / IV / MCP | `oracle` Raw (`V`, Day, Can) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hard-900000` | `primary` | `e15` | Y | 13 | `+0.49` | `0.49` | `0.54` | `0.9673` | `0.9673` | **`+0.4413`** | `+0.0487` | `16/63/135` | `-1.00` (N, `V=0.31`, d16, c=19) |
| `hard-900001` | `primary` | `e08` | Y | 7 | `+0.80` | `0.80` | `0.85` | `0.9615` | `0.9615` | **`+0.7306`** | `+0.0694` | `5/40/74` | `+0.53` (Y, `V=0.53`, d10, c=17) |
| `hard-900002` | `primary` | `e00` | Y | 10 | `+0.61` | `0.61` | `0.71` | `0.9930` | `0.9930` | **`+0.5987`** | `+0.0113` | `9/55/104` | `+0.52` (Y, `V=0.52`, d14, c=18) |
| `hard-900003` | `primary` | `e13` | Y | 11 | `+0.50` | `0.50` | `0.60` | `0.9621` | `0.9621` | **`+0.4431`** | `+0.0569` | `15/56/114` | `+0.63` (Y, `V=0.63`, d8, c=12) |
| `hard-900004` | `primary` | `e35` | Y | 12 | `+0.60` | `0.60` | `0.65` | `0.5196` | `0.5196` | **`-0.1686`** | `+0.7686` | `5/72/122` | `+0.72` (Y, `V=0.72`, d5, c=8) |
| `hard-900005` | `primary` | `e30` | N | 16 | `-1.00` | `0.39` | `0.39` | `0.9144` | `0.9144` | **`+0.2710`** | `-1.2710` | `11/92/164` | `+0.78` (Y, `V=0.78`, d5, c=7) |
| `hard-900006` | `rerun` | `e33` | Y | 12 | `+0.43` | `0.43` | `0.48` | `0.9862` | `0.9862` | **`+0.4103`** | `+0.0197` | `12/63/123` | `+0.40` (Y, `V=0.40`, d13, c=15) |
| `hard-900007` | `rerun` | `e31` | Y | 14 | `+0.66` | `0.66` | `0.66` | `0.9865` | `0.9865` | **`+0.6376`** | `+0.0224` | `9/68/137` | `+0.77` (Y, `V=0.77`, d5, c=8) |
| `hard-900008` | `primary` | `e29` | Y | 17 | `+0.36` | `0.36` | `0.46` | `0.7481` | `0.7481` | **`+0.0174`** | `+0.3426` | `14/97/174` | `+0.79` (Y, `V=0.79`, d4, c=6) |
| `hard-900009` | `rerun` | `e07` | Y | 12 | `+0.53` | `0.53` | `0.63` | `0.9804` | `0.9804` | **`+0.5000`** | `+0.0300` | `12/58/117` | `+0.53` (Y, `V=0.53`, d12, c=17) |
| **Mean / Total** | `7+3` | `10/10` | `9/10` | `12.4` | **`+0.398`** | `0.537` | `0.597` | `0.9019` | `0.9019` | **`+0.388`** | `+0.010` | `10.8/66.4/126.4` | **`+0.467`** (`9/10`, `V=0.598`, d9.2, c=12.7) |

Per-task diagnostic highlights:
- **`hard-900004` (OpenCode lucky negative-EV gamble):** OpenCode planted only `5` canaries while spending `72` interviews, then accused `e35` on Day 12 at `P(accused) = 0.5196 < 0.60` (`true_V = 0.60`). Because `0.5196 * 0.60 - 0.4804 = -0.1686 < 0`, this accusation had **negative expected value (`-0.169 V`)** relative to abstaining (`0.0`), yet won `+0.60` by coin flip (`+0.769 V` windfall).
- **`hard-900005` (OpenCode justified accusation hit by 5% fingerprint flip):** OpenCode planted `11` canaries and observed two canary leaks (`c7-2` variant `B: [e05, e14, e30, e36]` on Day 12, then `c12` variant `B: [e30]` on Day 16), reaching `P(accused) = 0.9144` (`LA = +0.2710`, `true_V = 0.39`) before accusing `e30` on Day 16. On this task, `oracle` had already solved the world on Day 5 (`accused = e05`, `correct = True`, `V = 0.78`), confirming that `c12` (`A: [e05], B: [e30], C: [e01, e14]`) suffered a `2.5%` (`(1 - 0.95) / 2`) fingerprint flip from `A` to `B`.
- **`hard-900008` (late-horizon value erosion):** OpenCode ran `97` interviews across `17` days (`true_V = 0.36`, `shown_V = 0.46` with `2` unsurfaced leaks) and accused `e29` at `P(accused) = 0.7481`, yielding barely positive luck-adjusted EV (`+0.0174 V`) versus `oracle`'s Day 4 solve (`+0.79 V`, `6` canaries, `0` interviews).

---

## 2. Token, Compute, and USD Cost Accounting (`ATIF-v1.7` Metrics)

| Task | Source | LLM Calls | MCP Calls | Non-MCP Calls | Prompt Tokens | Cached Tokens | Completion Tokens | Reasoning Tokens | ATIF `sum(cost_usd)` | List-Price USD (`$2/$0.10/$10`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hard-900000` | `primary` | 66 | 135 | 21 | 6,102,524 | 5,736,018 | 25,498 | 71,642 | `$2.2780` | `$2.2780` |
| `hard-900001` | `primary` | 31 | 74 | 4 | 1,640,997 | 1,532,052 | 6,812 | 48,741 | `$0.9266` | `$0.9266` |
| `hard-900002` | `primary` | 46 | 104 | 10 | 3,214,936 | 3,065,034 | 16,317 | 51,677 | `$1.2862` | `$1.2862` |
| `hard-900003` | `primary` | 49 | 114 | 11 | 4,032,830 | 3,854,998 | 18,580 | 67,345 | `$1.6004` | `$1.6004` |
| `hard-900004` | `primary` | 49 | 122 | 15 | 3,525,625 | 3,354,944 | 23,821 | 48,842 | `$1.4035` | `$1.4035` |
| `hard-900005` | `primary` | 62 | 164 | 10 | 4,664,044 | 4,436,834 | 22,192 | 51,501 | `$0.0000 (unpriced)` | `$1.6350` |
| `hard-900006` | `rerun` | 43 | 123 | 3 | 2,597,802 | 2,453,698 | 7,824 | 51,254 | `$0.0000 (unpriced)` | `$1.1244` |
| `hard-900007` | `rerun` | 48 | 137 | 0 | 3,438,567 | 3,278,542 | 4,777 | 75,097 | `$1.4466` | `$1.4466` |
| `hard-900008` | `primary` | 63 | 174 | 10 | 5,898,493 | 5,675,634 | 17,264 | 75,251 | `$0.0000 (unpriced)` | `$1.9384` |
| `hard-900009` | `rerun` | 60 | 117 | 18 | 4,782,907 | 4,593,879 | 20,671 | 54,469 | `$1.5888` | `$1.5888` |
| **Total (10 valid)** | `7+3` | **517** | **1264** | **102** | **39,898,725** | **37,981,633** | **163,756** | **595,819** | **`$10.5303`** (`7/10`) | **`$15.2281`** |

Note on cost accounting: On `7/10` valid trials (`5` primary + `2` rerun), OpenCode's `step-finish` events populated `metrics.cost_usd`, matching `canary.llm.pricing` (`$2.00/M` uncached input, `$0.10/M` cached input, `$10.00/M` completion + reasoning output) to `< 1e-15` per trial (`$10.5303` reported on the 10 valid trials; `$12.89` across all 13 attempted trials = `$9.86` primary + `$3.04` rerun in `rehearsal-dry/README.md`). On 3 isolated containers (`hard-900005`, `hard-900006` rerun, `hard-900008`), OpenCode recorded `cost = 0` (`cost_usd` omitted in ATIF) while logging full token counts; applying the exact same list prices yields **`$15.23`** (`$1.52/trial`) across all 10 valid trials.

---

## 3. Paired `oracle` Ledger Forensics: Why `hard-900000` Lost `-1.00` on Day 16

Across the 10 tasks, `oracle` (`SolverPolicy` over MCP) averaged **`0.598`** `true_V` at episode end (`0.537` for `opencode`), finishing in **`9.2` days** (vs `12.4` days for `opencode`) by planting **`12.7` canaries** (`69.0%` of the 2-canary/day capacity, `0` interviews) versus `opencode`'s `10.8` canaries (`43.5%` capacity) and `66.4` interviews/task.

Why did `oracle` score `-1.00` on `hard-900000` (`final_day = 16`, `true_V = 0.31`, `canaries_planted = 19`, `122` MCP calls) despite optimal canary design? `artifacts/ledger.json` reconstructs the exact causal chain without needing `SALT`:
1. **Early canary hit + careful-mole regular-doc streak (Days 1-12):** `oracle` planted `c1` on Day 1 (`C: [e15, e29, e30, e31, e38]`), which leaked on Day 1 and surfaced on Day 4. Over Days 4-12, `8` regular documents leaked and surfaced (`d3-3, d6-2, d7-2, d8-1, d7-1, d9-2, d11-4, d12-1`) while `c2..c11` did not leak, concentrating the posterior onto `['e01', 'e15', 'e31', 'e38']`.
2. **Endgame singleton split on Day 12 (`c12`):** On Day 12 (`t=93`), `oracle` planted `c12` with variants `A: [e31]`, `B: [e01, e15]`, `C: [e38]`. That canary leaked on Day 13 (`t=102`, `surfaces_on = 16`).
3. **5% fingerprint flip on Day 16 (`38:1` likelihood ratio):** Under hard-tier rules (`fingerprint_accuracy = 0.95`), a leaked 3-variant canary flips to each specific non-holder variant with probability `(1 - 0.95) / 2 = 0.025` (`2.5%`). When `c12` surfaced on Day `16` (`t=116`) with flipped label `A` (`[e31]`), `e31` gained a `38:1` (`0.95 / 0.025`) likelihood boost on top of already matching `c1` and all `8` regular leaks, pushing `SolverPolicy`'s posterior above `threshold = 0.85` and triggering immediate accusation at `t=121` (`-1.00`, a `-1.31 V` single-task swing from `+0.31` to `-1.00`, or `-0.131 V` on the 10-task mean).

---

## 4. Paired Frontier Gap: Raw vs Calibrated `oracle` Expectations (`judge_rerun_power_v14`)

Because Harbor's `oracle` container runs `SolverPolicy` in-process over MCP without writing an ATIF `trajectory.json`, we pair OpenCode's exact saltless luck-adjusted score (`+0.388`) against **both** `oracle` raw (`+0.467` on `rehearsal-dry`) **and** `oracle` posterior-calibrated expectations from `judge_rerun_power_v14` (same-build `true_V` calibrated at `SolverPolicy` `pass^1 = 0.9652`, plus the 30-seed `v1.4` dev, 200-build `oracle_range_v1.4`, and 300-build `solver_hard_judge40` references):

| Comparison Mode | OpenCode Mean | Reference Mean | Frontier / Oracle `[95% Boot CI]` | Mean Diff `[95% Boot CI]` | Paired Diff Var (Reduction) |
|---|---:|---:|---|---|---:|
| **1. Raw vs Paired `oracle` Raw** (`TABLE.md`) | `+0.398` | `+0.467` | `85.2% [10.8%, 355.0%]` | `-0.069 [-0.562, +0.405]` | `0.6279` (`1.00x`) |
| **2. Saltless LA vs Paired `oracle` Raw** | `+0.388` | `+0.467` | `83.1% [36.0%, 321.4%]` | `-0.079 [-0.422, +0.338]` | `0.4179` (`1.50x`) |
| **3. Saltless LA vs Same-Build Calibrated `oracle`** (`pass^1 * V_true - (1 - pass^1)`) | **`+0.388`** | **`+0.542`** | **`71.6% [36.4%, 111.4%]`** | **`-0.154 [-0.385, +0.052]`** | **`0.1436` (`4.37x`)** |
| **4. Saltless LA vs `judge_rerun_power_v14` Dev-30 `solver` LA** | `+0.388` | `+0.499` | `77.7% [43.0%, 108.3%]` | `-0.111 [-0.285, +0.042]` | n/a (fixed ref) |
| **5. Saltless LA vs `oracle_range_v1.4` (200 synthetic secrets)** | `+0.388` | `+0.569` | `68.2% [37.7%, 95.0%]` | `-0.181 [-0.355, -0.028]` | n/a (fixed ref) |
| **6. Saltless LA vs `solver_hard_judge40` (300 judge secrets)** | `+0.388` | `+0.567` | `68.4% [37.9%, 95.3%]` | `-0.179 [-0.353, -0.026]` | n/a (fixed ref) |
| *Reference: Committed `v1.4` Dev Seeds `0-29` (`n=30`, `paired_table_gemini.json`)* | `+0.360` | `+0.499` | `72.0% [52.0%, 91.0%]` | `-0.139` | `3.48x` emp / `4.22x` Mod B |

---

## 5. Cross-Build Stability Across Legacy Harbor Smoke Runs (`g-gemini-*` vs `g-oracle`)

Applying the exact same saltless ATIF scorer to the earlier retired Harbor smoke build (`results/harbor/g-gemini-rest` + `g-gemini-try2` paired with `results/harbor/g-oracle`, independent unpublished `SALT`) confirms stability across three disjoint world-secret sets:

- **Earlier Harbor `hard` smoke (`n=3`, `hard-900000..hard-900002`):** OpenCode raw `+0.527` -> saltless luck-adjusted **`+0.397`** vs `g-oracle` `+0.660` (**`60.2%`** luck-adjusted ratio, vs `79.8%` raw).
- **Earlier Harbor `medium` smoke (`n=3`, `medium-900000..medium-900002`):** OpenCode saltless luck-adjusted **`+0.480`** (`P(accused) = 1.000` on both accused tasks; `medium-900002` abstained at horizon with `P(top) = 0.5886`, EV `-0.058 < 0`, `LA = 0.000`) vs `g-oracle` `+0.853`.
- **Three-cohort `hard` convergence:** OpenCode `gemini-4-carbon` saltless luck-adjusted hard score is **`+0.360`** on committed dev seeds `0-29` (`n=30`), **`+0.397`** on `g-gemini-rest` (`n=3`), and **`+0.388`** on `rehearsal-dry` (`n=10`), with multi-run reliability `pass^1 = 0.902` and `pass^3 = 0.785` (vs dev-30 `pass^1 = 0.852`, `pass^3 = 0.714`).

