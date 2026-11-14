# Medium vs Hard and the 2x2 Harness Crossover (Rules v1.4, Paired Seeds 0-29)

**Scope.** Exact replay-verified analysis of all **180 committed v1.4 episodes** on paired dev seeds `0-29`: the full `2x2` `gemini-4-carbon` factorial (`{OpenCode over MCP, In-Process} x {Medium, Hard}`, 120 episodes) paired seed-by-seed against `SolverPolicy` (60 episodes). Every episode is replayed in a fresh `Env` and verified against the recorded score and accusation; all confidence intervals use 10,000-resample paired bootstraps (`rng_seed = 0`). Reproduce with one command (no API keys, ~3 s): `python scripts/harness_and_tier_analysis_v14.py` (`--check` verifies exact reproduction).

## Executive Summary: Two Headline Patterns, One Mechanistic Explanation

Judges reading `docs/reports/gap.md` observe two immediate patterns across the 120 `gemini-4-carbon` episodes:
1. **Tier separation in the judges' harness (OpenCode over MCP):** Medium is at solver parity (**111%** `[99%, 127%]` raw; **101%** `[85%, 119%]` luck-adjusted), while Hard opens a clear gap (**65%** `[24%, 98%]` raw; **72%** `[52%, 91%]` luck-adjusted).
2. **2x2 Harness x Tier crossover:** OpenCode beats In-Process on Medium (`+0.713` vs `+0.530`, paired diff `+0.183` `[+0.059, +0.341]`; luck-adjusted `0.652` vs `0.479`, diff `+0.173` `[+0.034, +0.322]`), whereas In-Process beats OpenCode on Hard (`+0.473` vs `+0.322`, `OC - IP = -0.151` `[-0.382, +0.070]`; luck-adjusted `0.421` vs `0.360`, `OC - IP = -0.061` `[-0.202, +0.077]`). The **Difference-in-Differences** `(OC_hard - IP_hard) - (OC_med - IP_med)` is **`-0.333`** `[-0.659, -0.046]` on raw score (`p = 0.0224`) and **`-0.234`** `[-0.461, -0.017]` on luck-adjusted score (`p = 0.0350`), excluding zero on both metrics.

**Why the crossover happens (mechanistic proof):**
- **On Medium (`N = 20`, `100%` fingerprint accuracy, 1 canary/day, no clearance constraints), noiseless set elimination suffices.** Every leaked regular document and canary variant is a deterministic 0/1 filter (`mole in C` in `30/30` episodes for every agent). OpenCode starts planting canaries slightly earlier (day `1.07` vs `1.47`), wastes fewer full-budget days on zero-canary interview sprees (`35` vs `60` days), isolates `|C| = 1` on `27/30` seeds, and commits decisively on all `30/30` episodes (`30/30` correct; `3` unresolved `|C| = 2` bets all landed, adding `+0.061` V/ep of positive luck that explains `111%` raw vs `101%` luck-adjusted). In-Process reaches day 14 with `|C| >= 2` on 5 episodes and abstains on `4/30` (seeds `3, 7, 8, 12`, `26/30` accused) plus 1 horizon miss (seed 18).
- **On Hard (`N = 40`, `95%` fingerprint accuracy = 5% variant flip, 2 canaries/day, 2-3 day delay, clearance constraints), BOTH harnesses severely under-explore AND OpenCode's strict-elimination commitment breaks under noise.** Both OpenCode and In-Process plant only `8.5` and `8.6` canaries vs Solver's `14.1` (`32%` and `33%` of the 2/day capacity vs Solver's `67%`) while spending `68.0` and `57.3` calls on near-zero-information interviews (`<= 0.0048` nats each vs `1.099` nats per 3-way canary; Solver runs `0` interviews). Crucially, `95%` fingerprint accuracy turns a canary variant mismatch from hard exclusion into a `1:38` likelihood ratio. OpenCode's aggressive commitment suffers `2/2` wrong accusations on false `|C| = 1` flip traps (seeds `1, 26`) plus `9/29` under-isolated (`|C| >= 2`) accusations (`P(accused) = 0.88`, `10/29` below `0.85`). In-Process's `generateContent` loop with persisted `thought_signature_replay` tracks noisy likelihoods more conservatively (`P(accused) = 0.93`, only `4/29` below `0.85`), **recovering to accuse the true mole on `2` flip episodes (seeds `3, 5`) even after subsequent leaks drove the strict noiseless consistent set to `|C| = 0` (empty)** and rationally abstaining on flip seed `26` (`1` wrong total vs OpenCode's `4`).

## 1. Full 2x2 Factorial Scoreboard and Paired Bootstrap Contrasts

### 1.1 Six-Cell Headline Table (Paired Seeds 0-29)

| Tier | Harness | n | Raw Score +/- CI | Raw / Solver [95% Boot CI] | Luck-Adj Score +/- CI | Luck-Adj / Solver [95% Boot CI] | Accused | Accuracy | Mean P(accused) |
|---|---|---:|---|---|---|---|---|---|---|
| medium | OpenCode over MCP | 30 | +0.713 +/- 0.042 | 111% [99%, 127%] | +0.652 +/- 0.089 | 101% [85%, 119%] | 30/30 (100%) | 30/30 (100%) | 0.962 |
| medium | In-Process (thought-sig) | 30 | +0.530 +/- 0.138 | 82% [56%, 108%] | +0.479 +/- 0.123 | 74% [52%, 99%] | 26/30 (87%) | 25/30 (83%) | 0.929 |
| medium | SolverPolicy (reference) | 30 | +0.645 +/- 0.087 | -- | +0.645 +/- 0.087 | -- | 27/30 (90%) | 27/30 (90%) | 1.000 |
| hard | OpenCode over MCP | 30 | +0.322 +/- 0.199 | 65% [24%, 98%] | +0.360 +/- 0.105 | 72% [52%, 91%] | 29/30 (97%) | 25/30 (83%) | 0.882 |
| hard | In-Process (thought-sig) | 30 | +0.473 +/- 0.118 | 95% [62%, 140%] | +0.421 +/- 0.086 | 84% [65%, 106%] | 29/30 (97%) | 28/30 (93%) | 0.930 |
| hard | SolverPolicy (reference) | 30 | +0.499 +/- 0.119 | -- | +0.499 +/- 0.064 | -- | 30/30 (100%) | 29/30 (97%) | 0.965 |

Note: `luck_adjusted_round3_mean` (rounding `P(accused)` to 3 decimals as in `scripts/paired_v13.py`) gives Medium `0.652 / 0.479 / 0.645` and Hard `0.360 / 0.421 / 0.499`, matching `docs/reports/gap.md` to every printed digit.

### 1.2 Exact Paired 2x2 Contrasts (10,000-Resample Paired Bootstrap 95% CIs)

| Contrast (n = 30 paired seeds) | Metric | Mean Diff (per ep) | Sum (30 seeds) | 95% Paired Boot CI | Indep-Tier Boot CI | Boot 2-Sided p | Seed Wins (+ / - / tie) |
|---|---|---:|---:|---|---|---:|---|
| OpenCode - In-Process (Medium) | Raw score | **+0.183** | +5.48 V | [+0.059, +0.341] | -- | 0.0002 | 18 / 10 / 2 |
| OpenCode - In-Process (Hard) | Raw score | **-0.151** | -4.52 V | [-0.382, +0.070] | -- | 0.1824 | 16 / 14 / 0 |
| DiD: (OC_hard - IP_hard) - (OC_med - IP_med) | Raw score | **-0.333** | -10.00 V | [-0.659, -0.046] | [-0.611, -0.077] | 0.0224 | 10 / 20 / 0 |
| OpenCode - In-Process (Medium) | Luck-adjusted | **+0.173** | +5.18 V | [+0.034, +0.322] | -- | 0.0108 | 18 / 11 / 1 |
| OpenCode - In-Process (Hard) | Luck-adjusted | **-0.061** | -1.84 V | [-0.202, +0.077] | -- | 0.3870 | 12 / 18 / 0 |
| DiD: (OC_hard - IP_hard) - (OC_med - IP_med) | Luck-adjusted | **-0.234** | -7.02 V | [-0.461, -0.017] | [-0.438, -0.036] | 0.0350 | 10 / 20 / 0 |
| Tier drop: OpenCode (Hard - Medium) | Raw score | **-0.391** | -11.72 V | [-0.600, -0.207] | -- | 0.0000 | 7 / 23 / 0 |
| Tier drop: In-Process (Hard - Medium) | Raw score | **-0.057** | -1.72 V | [-0.253, +0.139] | -- | 0.5630 | 11 / 19 / 0 |
| Tier drop: Solver (Hard - Medium) | Raw score | **-0.146** | -4.38 V | [-0.305, +0.004] | -- | 0.0566 | 7 / 23 / 0 |
| Solver-adj tier drop: (OC_h - S_h) - (OC_m - S_m) | Luck-adjusted | **-0.147** | -4.40 V | [-0.284, -0.011] | -- | 0.0342 | 13 / 17 / 0 |
| Solver-adj tier drop: (IP_h - S_h) - (IP_m - S_m) | Luck-adjusted | **+0.088** | +2.63 V | [-0.124, +0.301] | -- | 0.4134 | 16 / 14 / 0 |

## 2. Six-Cell Mechanistic Behavioral and Posterior Metrics

| Metric | Med OC | Med IP | Med Solver | Hard OC | Hard IP | Hard Solver |
|---|---:|---:|---:|---:|---:|---:|
| Canaries planted before accusation | 5.83 | 6.93 | 7.30 | 8.47 | 8.57 | 14.13 |
| Days with >=1 canary (mean / share of days) | 5.83 (73%) | 6.93 (71%) | 7.30 (89%) | 5.13 (38%) | 5.33 (41%) | 9.60 (91%) |
| Days with 2 canaries (mean / share of days) | 0.00 (0%) | 0.00 (0%) | 0.00 (0%) | 3.33 (25%) | 3.23 (25%) | 4.53 (43%) |
| Canary capacity used (1/day Med, 2/day Hard) | 73% | 71% | 89% | 32% | 33% | 67% |
| First canary planted (day) | 1.07 | 1.47 | 1.00 | 3.03 | 3.40 | 1.00 |
| Mean canary group size (staff share) | 7.72 (39%) | 6.97 (35%) | 4.87 (24%) | 10.14 (25%) | 10.33 (26%) | 9.86 (25%) |
| Mean canary variant count (max 3) | 3.00 | 2.99 | 2.76 | 3.00 | 3.00 | 3.00 |
| Canary Shannon split entropy (bits, max 1.585) | 1.530 | 1.493 | 1.430 | 1.517 | 1.534 | 1.546 |
| Canary Shannon split entropy (nats, max 1.099) | 1.060 | 1.035 | 0.991 | 1.051 | 1.063 | 1.072 |
| Unique staff ever covered by a canary | 17.8 (89%) | 16.9 (85%) | 14.7 (74%) | 27.8 (70%) | 27.6 (69%) | 38.6 (96%) |
| Interviews called per episode | 37.5 | 47.3 | 0.0 | 68.0 | 57.3 | 0.0 |
| Full-budget days (<max canaries, 8/8 actions) | 35 / 239 | 60 / 291 | 0 / 246 | 242 / 403 | 205 / 389 | 0 / 318 |
| Interviews on under-canaried full-budget days | 229 | 385 | 0 | 1503 | 1253 | 0 |
| `check_leak_feed` calls per episode | 4.3 | 5.5 | 8.2 | 6.7 | 6.3 | 10.6 |
| `read_access_logs` calls per episode | 6.0 | 8.0 | 7.2 | 12.3 | 11.8 | 9.6 |
| Total tool calls per episode | 76.1 | 94.2 | 63.3 | 128.0 | 116.2 | 84.3 |
| Accusation day (accused episodes) | 7.97 | 9.04 | 7.56 | 13.17 | 12.69 | 10.60 |
| Decision day (abstentions at horizon 14/21) | 7.97 | 9.70 | 8.20 | 13.43 | 12.97 | 10.60 |
| Abstention rate (count / 30) | 0% (0/30) | 13% (4/30) | 10% (3/30) | 3% (1/30) | 3% (1/30) | 0% (0/30) |
| Wrong accusations (expected from posteriors) | 0 (1.2) | 1 (1.9) | 0 (0.0) | 4 (3.4) | 1 (2.0) | 1 (1.0) |
| Strict consistent-set size `|C|` at accusation (mean) | 1.10 | 1.15 | 1.04 | 1.83 | 1.21 | 1.07 |
| Accusations at `|C| = 0` / `|C| = 1` / `|C| > 1` | 0 / 27 / 3 | 0 / 22 / 4 | 0 / 26 / 1 | 0 / 20 / 9 | 2 / 21 / 6 | 1 / 26 / 3 |
| Mole excluded from strict `C` at accusation | 0/30 | 0/26 | 0/27 | 2/29 | 3/29 | 2/30 |
| Episodes with >=1 surfaced 5% variant flip | 0/30 | 0/30 | 0/30 | 2/30 | 4/30 | 2/30 |
| Wait days after first `|C| = 1` (hesitation) | 0.00 (0 eps) | 0.00 (0 eps) | 0.00 (0 eps) | 0.55 (5 eps) | 0.36 (3 eps) | 0.00 (0 eps) |
| Solver posterior `P(accused)` mean / median | 0.962 / 1.000 | 0.929 / 1.000 | 1.000 / 1.000 | 0.882 / 0.964 | 0.930 / 0.979 | 0.965 / 0.974 |
| Accusations at P >=0.95 / 0.85-0.95 / 0.60-0.85 / <0.60 | 27 / 0 / 2 / 1 | 22 / 0 / 1 / 3 | 27 / 0 / 0 / 0 | 16 / 3 / 8 / 2 | 18 / 7 / 3 / 1 | 24 / 6 / 0 / 0 |
| Negative-EV accusations (`EV < 0` under Solver) | 2 | 3 | 0 | 3 | 3 | 0 |

(In `canary/env.py`, the access-log tool is named `read_access_logs`; zero `get_access_logs` aliases exist.)

## 3. Exact Additive V Decompositions Across 30 Paired Seeds

For every episode where an agent accuses, `true_V = 1 - leak_damage * L - canary_cost * C - R` and `luck_adjusted = true_V - (1 - P) * (1 + true_V)`. Across 30 paired seeds, the difference `A - B` decomposes with zero residual into commitment posterior quality `-(pen_A - pen_B)` on jointly accused seeds, asymmetric accusation/abstention terms (`A`-only accused vs `A`-abstained), leak timing, canary cost, restriction cost, and luck (`realized - luck_adjusted`).

| Paired Comparison (30 seeds, V units) | Luck-Adj Diff | Commitment Quality | A-Only Accused | A-Abstained | Leak Timing | Canary Cost | Restrict | Luck Diff | Raw Diff |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Medium: OpenCode - In-Process | **+5.18** | +1.81 | +2.20 | +0.00 | +0.84 | +0.22 | +0.11 | +0.30 | **+5.48** |
| Hard: OpenCode - In-Process | **-1.84** | -1.89 | +0.59 | -0.39 | -0.10 | -0.01 | -0.04 | -2.68 | **-4.52** |
| Medium: OpenCode - Solver | **+0.21** | -1.18 | +1.17 | +0.00 | -0.00 | +0.28 | -0.06 | +1.83 | **+2.04** |
| Medium: In-Process - Solver | **-4.97** | -3.08 | +1.80 | -2.97 | -0.64 | +0.03 | -0.11 | +1.53 | **-3.44** |
| Hard: OpenCode - Solver | **-4.19** | -3.39 | +0.00 | -0.62 | -1.75 | +1.69 | -0.12 | -1.11 | **-5.30** |
| Hard: In-Process - Solver | **-2.35** | -1.48 | +0.00 | -0.64 | -1.85 | +1.70 | -0.08 | +1.57 | **-0.78** |

## 4. Proof Part I: Why OpenCode Hits Parity and Beats In-Process on Medium

1. **Noiseless set elimination is exact on Medium.** With `N = 20`, `fingerprint_accuracy = 1.00`, and no clearance constraints, every leaked canary variant and regular document is a 0/1 set intersection with zero false exclusions (`mole in C` in `30/30` OpenCode and `26/26` In-Process accusations). Whenever `|C| = 1` surfaces in `check_leak_feed`, **both harnesses accuse on that exact day** (`0.00` wait days after first `|C| = 1` across `27/27` OpenCode and `22/22` In-Process isolated episodes).
2. **Why OpenCode beats In-Process (`+5.48 V` raw = `+0.183/ep`, `+5.18 V` luck-adjusted = `+0.173/ep`):** In-Process starts its first canary later (`day 1.47` vs `1.07`) and burns `60` active days exhausting all 8 actions on interviews with 0 canaries (vs `35` for OpenCode; `47.3` vs `37.5` interviews/episode). Consequently, In-Process reaches the day-14 horizon with `|C| >= 2` on **5 seeds (`3, 7, 8, 12, 18`)**: it abstains on 4 (`seeds 3, 7, 8, 12`, losing `+2.20 V` of luck-adjusted value that OpenCode captured on those exact 4 seeds) and guesses wrong on seed 18 (`-1.00`, `|C| = 2`, `P = 0.554`).
3. **Why Medium OpenCode is `111%` raw yet `101%` luck-adjusted vs Solver:** On `27/30` seeds OpenCode isolated `|C| = 1` (`P = 1.00`). On the remaining 3 seeds (`7, 23, 29`), `|C| = 2` remained (`P = 0.627, 0.660, 0.558`), and OpenCode committed anyway -- winning all 3 coin-tilted bets for `+1.83 V` (`+0.061/ep`) of positive luck, while `SolverPolicy` rationally abstained on 3 unresolved horizon seeds (`20, 21, 29`). Removing luck puts OpenCode (`0.652`) and Solver (`0.645`) at exact parity (`101.1%`).

| Seed | IP Outcome | IP Score | IP 1st Canary | IP Canaries / Interviews | IP End `|C|` (`P_top`) | OC Score (Day) | OC Canaries | OC `|C|` (`P_acc`) | Solver Score (Day) |
|---:|---|---:|---:|---|---:|---|---:|---|---:|
| 3 | abstained | +0.00 | day 1 | 13 / 76 | 5 (0.25) | +0.60 (d9) | 8 | 1 (1.00) | +0.60 (d9) |
| 7 | abstained | +0.00 | day 1 | 8 / 80 | 7 (0.18) | +0.50 (d14) | 10 | 2 (0.63) | +0.82 (d7) |
| 8 | abstained | +0.00 | day 6 | 6 / 83 | 3 (0.36) | +0.85 (d4) | 3 | 1 (1.00) | +0.88 (d5) |
| 12 | abstained | +0.00 | day 1 | 8 / 78 | 2 (0.51) | +0.81 (d6) | 3 | 1 (1.00) | +0.67 (d10) |
| 18 | wrong | -1.00 | day 1 | 9 / 74 | 2 (0.55) | +0.80 (d6) | 4 | 1 (1.00) | +0.75 (d6) |

## 5. Proof Part II: Why Hard Opens a Real Gap and Reverses the Harness Ranking

1. **Shared model-level bottleneck -- severe canary under-exploration:** On Hard (`N = 40`, 21 days, 2 canaries/day, 2-3 day delay, clearance constraints), individual canaries planted by both harnesses are well-structured (mean group size `10.1` and `10.3` = ~25% of staff, 3.00 variants, split entropy `1.517` and `1.534` bits vs Solver's `1.546` bits out of `1.585` max). The failure is **rate and budget allocation**: OpenCode and In-Process plant only `8.47` and `8.57` canaries before accusing (vs Solver's `14.13`), using `32%` and `33%` of the 2-canary/day pipeline (vs Solver's `67%`) while spending `68.0` and `57.3` calls on interviews (`<= 0.005` nats each).
2. **Why In-Process beats OpenCode on Hard (`+0.151/ep` raw, `+0.061/ep` luck-adjusted):** Under `fingerprint_accuracy = 0.95`, a leaked canary showing variant `X` gives a `38:1` likelihood ratio (`0.95` vs `0.025`) among recipients of that canary, **not** a noiseless exclusion. Strict set elimination fails whenever the 5% variant flip occurs:
   - **OpenCode (`opencode-cli+mcp_server`)** encountered 2 episodes with a surfaced 5% flip (`seeds 1, 26`); on **both**, strict elimination collapsed to a false singleton `|C| = 1` excluding the true mole, and OpenCode accused the innocent singleton (`-1.00` each). In addition, OpenCode's aggressive commitment habit produced `9/29` accusations with `|C| >= 2` (`10/29` at `P < 0.85`, mean `P(accused) = 0.882`, expected wrong `3.4`, actual wrong `4`).
   - **In-Process (`generateContent` with `thought_signature_replay = true`)** encountered **4 episodes** with a surfaced 5% variant flip (`seeds 3, 5, 6, 26`). On **seeds 3 and 5**, subsequent leaks contradicted the flipped canary and drove the strict consistent set to **empty (`|C| = 0`)** -- a total breakdown for noiseless set elimination -- yet In-Process weighed the 5% noise model across turns and **accused the true mole on both** (`P = 0.985` on seed 3, `+0.59`; `P = 0.901` on seed 5, `+0.10`). On **seed 26**, a flip left `|C| = 3` (`P_top = 0.379`) and In-Process **rationally abstained (`0.00` vs OpenCode's `-1.00`)**. Overall, In-Process achieved `P(accused) = 0.930` (`25/29` at `P >= 0.85`, expected wrong `2.0`, actual wrong `1`).

### 5.1 All Surfaced 5% Fingerprint-Flip Episodes Across Harnesses on Hard

| Harness | Seed | Flipped Canary (Day: Shown vs Mole's) | Strict `|C|` at Decision | Mole in `C`? | Agent Decision | Solver `P` | Score |
|---|---:|---|---:|---|---|---:|---:|
| OpenCode | 1 | c16 (d19: v1!=v2) | 1 | NO | accuse e39 d19 (WRONG) | 0.988 | -1.00 |
| OpenCode | 26 | c6-2 (d10: S1!=S3) | 1 | NO | accuse e04 d10 (WRONG) | 0.950 | -1.00 |
| In-Process | 3 | c3 (d6: v3!=v2) | 0 | NO | accuse e29 d10 (OK) | 0.985 | +0.59 |
| In-Process | 5 | c3 (d6: v2!=v3) | 0 | NO | accuse e27 d21 (OK) | 0.901 | +0.10 |
| In-Process | 6 | c4-2 (d7: Z!=Y) | 3 | NO | accuse e18 d15 (WRONG) | 0.629 | -1.00 |
| In-Process | 26 | c4 (d6: v2!=v1) | 3 | NO | abstain (d21) | 0.379 | +0.00 |
| SolverPolicy | 4 | c3-2 (d5: B!=C) | 0 | NO | accuse e11 d5 (OK) | 1.000 | +0.73 |
| SolverPolicy | 15 | c5 (d9: C!=A) | 1 | NO | accuse e17 d9 (WRONG) | 0.874 | -1.00 |

### 5.2 Paired Outcome Divergences on Hard (Seeds Where OpenCode and In-Process Differ in Outcome)

| Seed | OC Outcome (Day, `|C|`, Flip?, `P`) | OC Score | IP Outcome (Day, `|C|`, Flip?, `P`) | IP Score | Solver Score |
|---:|---|---:|---|---:|---:|
| 1 | e39 WRONG (d19, |C|=1, flip=Y, P=0.99) | -1.00 | e33 OK (d12, |C|=1, flip=N, P=0.99) | +0.55 | +0.69 |
| 6 | e34 OK (d6, |C|=1, flip=N, P=1.00) | +0.73 | e18 WRONG (d15, |C|=3, flip=Y, P=0.63) | -1.00 | +0.71 |
| 11 | abstain (d21) | +0.00 | e09 OK (d18, |C|=1, flip=N, P=0.99) | +0.40 | +0.62 |
| 15 | e34 WRONG (d12, |C|=2, flip=N, P=0.80) | -1.00 | e37 OK (d12, |C|=1, flip=N, P=0.96) | +0.65 | -1.00 |
| 18 | e29 WRONG (d18, |C|=4, flip=N, P=0.63) | -1.00 | e27 OK (d14, |C|=1, flip=N, P=0.99) | +0.55 | +0.52 |
| 26 | e04 WRONG (d10, |C|=1, flip=Y, P=0.95) | -1.00 | abstain (d21) | +0.00 | +0.69 |

