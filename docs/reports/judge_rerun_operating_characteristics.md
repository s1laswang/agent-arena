# Judge Rerun Operating Characteristics: `1x10` vs `3x10` Power, Luck-Adjusted Variance Reduction, `pass^3`, `gpt-5.5`, and Live Harbor Rehearsal Validation

**Scope.** Rules `v1.4`, `hard` tier, all 30 paired committed seeds (`0-29`) across five policies (`solver`, `opencode-gpt-5.5`, `inproc-carbon`, `opencode-carbon`, `opencode-3.5-flash`) from `data/runs/committed/v1.4/`, evaluated across `50,000` deterministic Monte Carlo trials (`rng_seed=20261114`) for `k=10` judge tasks and `R in {1, 2, 3, 5}` repeated frontier runs (`1x10`, `2x10`, `3x10`, `5x10`), cross-checked against `results/oracle_range_v1.4.json` (200 synthetic world secrets), `results/solver_range/solver_hard_judge40.json` (300 fresh judge secrets), and the live 3-run Harbor judge rehearsal on `afterquery-final` (`results/harbor/rehearsal/TABLE.md`, corrected in `aa1c679e` / `5f9b3297`).
Reproduce or verify in <5 s with zero API keys:

```bash
python scripts/judge_rerun_power_v14.py
python scripts/judge_rerun_power_v14.py --check
```

## Executive Summary: Operating Characteristics & Honest Rehearsal Readout

`harbor/README.md` and `scripts/oracle_range.py` quantified the Harbor oracle (`SolverPolicy`) alone on a 10-task hard build (`+0.569 +/- 0.094` SD across 200 synthetic world secrets, 90% band `[+0.393, +0.678]`), leaving open the paired operating characteristics when frontier models are judged against the oracle.
On a single `1x10` hard rerun, flipping one accusation from correct (`+V`) to wrong (`-1.0`) swings the 10-task mean by `(1 + V)/10 = 0.155 V` (`~0.16 V` for `opencode-carbon`, `0.154 V` for `opencode-gpt-5.5`, `0.155 V` for the oracle). The official AfterQuery judge procedure runs **3 independent frontier runs x 10 hard tasks (`3x10`)** paired with the oracle on the same build:

1. **`3x10` Paired Power (`opencode-carbon` MCP-only vs oracle).** Under empirical paired 10-seed build resampling (Model A), moving from `R=1` to `R=3` frontier runs cuts paired gap SD by `sqrt(3)` (`0.168` -> `0.097` raw; `0.090` -> `0.052` luck-adjusted) and raises `P(frontier_mean < oracle_mean)` from **85.1%** (`1x10`) to **97.8%** (`3x10`) on raw scores -- and from **94.4%** to **99.8%** on luck-adjusted scores. On a fixed 10-world Harbor build where only accusation outcomes re-realise across the 3 runs (Model B), `R=3` cuts conditional run-to-run gamble noise by exact factor **`sqrt(3) = 1.732x`** (`0.135 V` -> `0.078 V` SD) and lifts single-build `P(frontier_mean < oracle_mean)` from `77.7%` to `83.4%`.
2. **Luck-Adjusted Scoring Cuts Estimator Variance by >2x (Rao-Blackwellization).** Scoring each accusation by its exact solver-posterior expectation `P_accused * V_at_accuse - (1 - P_accused)` (`0` on abstention) removes conditional accusation coin-flip variance `P(1 - P)(1 + V)^2`, which makes up **53.2%** of `opencode-carbon`'s `1x10` gap variance (`76.3%` including the oracle's 5% fingerprint-flip risk). Estimator variance drops by **3.48x** empirically on the 30 paired seeds (`0.2936` -> `0.0844`) and by **4.22x** under Model B (`0.0344` -> `0.0082`; **3.58x** for `opencode-gpt-5.5`, **3.28x** for `inproc-carbon`).
3. **Second Frontier Family (`opencode-gpt-5.5`, pre-registered `cf394894` / data `ca0a0dc0`) Matches Reference on Raw Reward.** With the same 13 MCP tools (`bash`/`python3` denied), `gpt-5.5` scores `+0.504 +/- 0.064` raw (**`101% [79%, 140%]`** of solver; `28/28` accusations correct, `0` wrong, `2` text-only abstentions on seeds `0` and `17`; `3x10` raw `F / O` median `1.001`) and `+0.418 +/- 0.073` luck-adjusted (**`84% [67%, 103%]`** of solver; `+0.086 V/ep` realised luck from zero 5%-flips across 28 high-posterior accusations at mean `P = 0.940`; calibrated `pass^3 = 0.792` exact / `0.793` at 3-dp `audit_episode` rounding, Model A LA `3x10` `F / O` median `0.838`, Model B `3x10` `F - O = -0.083`).
4. **Exposing Lucky Gamblers via `pass^3` (`gemini-3.5-flash` Collapse).** In its single committed 30-seed run, `OpenCode + gemini-3.5-flash` scored `+0.373` raw (`27/30 = 90.0%` accuracy) only because **7 of its 10 sub-threshold gambles (`P_accused < 0.60`, mean `P = 0.214`) landed by luck**, adding `+0.263 V` of lottery windfall above its true luck-adjusted expectation of **`+0.110`** (`22%` of oracle). Under repeated runs on the same worlds, `3.5-flash`'s posterior-calibrated reliability collapses from empirical `0.900` to `pass^1 = 0.710`, `pass^2 = 0.637`, and **`pass^3 = 0.601`** (and **`pass^3 = 0.028`** on its 10 gamble worlds), ranking all 5 policies strictly: `solver (0.903) > inproc-carbon (0.804) > opencode-gpt-5.5 (0.792) > opencode-carbon (0.714) > opencode-3.5-flash (0.601)`.
5. **Live 3-Run Harbor Rehearsal Validation (`afterquery-final` `1bc3e281`, `aa1c679e` / `5f9b3297`).** Across 3 live Harbor 0.26.0 OpenCode + `gemini-4-carbon` runs on 10 hard judge tasks (`900000-900009`), final run means were **`+0.472` (`93%`, `n=10`), `+0.585` (`116%`, `n=10`), and `+0.626` (`131%`, `n=9` valid, `1` infra-excluded; corrected in `aa1c679e` from the `08:52` partial `n=7` `+0.656` / `153%` snapshot, full trials on `d0ead011`)** vs paired oracle **`+0.506`** (`9/10` correct; one 5% flip on `hard-900007` swung oracle by `~0.167 V`, and one flip on `hard-900002` swung `opencode-1` vs `opencode-2` by `0.158 V`). Observed 3-run spread (`SD = 0.080`, `range = 0.154`, mean of means `+0.561`) sits well inside Model B's conditional Bernoulli bound (`0.135 V`), while the `65%` MCP-only gap **did not reproduce** in the shell-enabled Harbor container (`28/29` valid accusations correct; shell used in `20/28` trials).

---

## 1. Committed 30-Seed `v1.4` Hard Baseline (Ledger- and Posterior-Verified)

Every episode across all five policies (`5 x 30 = 150` episodes) is checked against its ledger score invariant (`tol = 1e-5`, with `canary.env.Env('hard', seed)` full step-replay verification when `meta.V_final` is absent) and traced step-by-step through `SolverPolicy` to extract true company value `V_at_accuse` plus the exact Bayesian posterior `P_accused` over the agent's own observations at the accusation step.

| Policy | n | Raw Mean +/- 95% CI | Luck-Adj Mean +/- 95% CI | Realised Luck (`Raw - LA`) | Empirical Acc | Mean `P_accused` | Mean `V_at_accuse` | 1-Task Wrong Swing `(1+V)/10` | Gambles `P<0.60` (Won) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `solver` | 30 | `+0.499 +/- 0.119` | `+0.499 +/- 0.064` | `-0.000` | `0.967` | `0.965` | `0.554` | `0.155 V` | `0 (0)` |
| `opencode-gpt-5.5` | 30 | `+0.504 +/- 0.064` | `+0.418 +/- 0.073` | `+0.086` | `0.933` | `0.940` | `0.540` | `0.154 V` | `0 (0)` |
| `inproc-carbon` | 30 | `+0.473 +/- 0.118` | `+0.421 +/- 0.086` | `+0.052` | `0.933` | `0.930` | `0.541` | `0.154 V` | `1 (1)` |
| `opencode-carbon` | 30 | `+0.322 +/- 0.199` | `+0.360 +/- 0.105` | `-0.037` | `0.833` | `0.882` | `0.545` | `0.155 V` | `2 (2)` |
| `opencode-3.5-flash` | 30 | `+0.373 +/- 0.177` | `+0.110 +/- 0.219` | `+0.263` | `0.900` | `0.710` | `0.505` | `0.150 V` | `10 (7)` |

Key baseline diagnostics:
- **Single wrong accusation swing:** Across accused hard episodes, `V_at_accuse` averages `0.540` (`opencode-gpt-5.5`) and `0.545` (`opencode-carbon`) to `0.554` (`solver`), so replacing one `+V` win with a `-1.0` penalty shifts a 10-task mean by **`0.154 V` to `0.155 V` (`~0.16 V`)**.
- **Opposite signs of realised luck:** `opencode-carbon` suffered slight negative luck (`-0.037 V/ep`: 4 wrong accusations vs 3.43 expected from its posteriors, including two 5% fingerprint flips at `P >= 0.95`), `opencode-gpt-5.5` had moderate positive luck (`+0.086 V/ep`: `0` wrong across 28 accusations vs `1.69` expected at mean `P = 0.940`, offset by 2 text-only abstentions), whereas `opencode-3.5-flash` enjoyed extreme positive luck (`+0.263 V/ep`: winning 7 of 10 low-posterior gambles vs 2.14 expected).

---

## 2. Model (A): Empirical Paired 10-Seed Build Resampling (`k=10`, `R in {1, 2, 3, 5}`)

In each of `50,000` trials, each frontier run draws `k=10` world seeds with replacement from the 30 committed hard worlds paired against the oracle on those seeds, averaging across `R in {1, 2, 3, 5}` independent 10-task runs (`frontier_mean` vs `oracle_mean`, effective sample sizes `n = 10, 20, 30, 50`). Ratios `frontier_mean / oracle_mean` are summarised over trials with `oracle_mean > 0` (`>99.97%` of raw builds and `100%` of luck-adjusted builds).

| Frontier Model | Score | `R` Runs | `F - O` Mean | `F - O` SD | `F - O` `[p5, p50, p95]` | `F / O` Mean | `F / O` SD | `F / O` `[p5, p50, p95]` | `P(F < O)` | `P(F < 0.85*O)` |
|---|---|---:|---:|---:|---|---:|---:|---|---:|---:|
| `opencode-carbon` | Raw | 1 | `-0.177` | `0.168` | `[-0.484, -0.161, +0.063]` | `0.645` | `0.505` | `[0.041, 0.677, 1.145]` | **85.1%** | `70.1%` |
| `opencode-carbon` | Raw | 2 | `-0.176` | `0.119` | `[-0.389, -0.168, +0.004]` | `0.648` | `0.239` | `[0.229, 0.664, 1.009]` | **94.4%** | `79.9%` |
| `opencode-carbon` | Raw | 3 | `-0.177` | `0.097` | `[-0.347, -0.172, -0.027]` | `0.646` | `0.192` | `[0.314, 0.656, 0.942]` | **97.8%** | `85.9%` |
| `opencode-carbon` | Raw | 5 | `-0.177` | `0.076` | `[-0.308, -0.173, -0.059]` | `0.646` | `0.148` | `[0.391, 0.653, 0.877]` | **99.6%** | `92.4%` |
| `opencode-carbon` | Luck-Adj | 1 | `-0.139` | `0.090` | `[-0.292, -0.135, +0.005]` | `0.724` | `0.180` | `[0.420, 0.731, 1.011]` | **94.4%** | `75.9%` |
| `opencode-carbon` | Luck-Adj | 2 | `-0.139` | `0.064` | `[-0.247, -0.138, -0.037]` | `0.722` | `0.125` | `[0.512, 0.725, 0.922]` | **99.0%** | `84.7%` |
| `opencode-carbon` | Luck-Adj | 3 | `-0.140` | `0.052` | `[-0.228, -0.139, -0.056]` | `0.721` | `0.102` | `[0.550, 0.723, 0.885]` | **99.8%** | `90.1%` |
| `opencode-carbon` | Luck-Adj | 5 | `-0.140` | `0.040` | `[-0.207, -0.139, -0.074]` | `0.721` | `0.079` | `[0.591, 0.722, 0.848]` | **100.0%** | `95.3%` |
| `opencode-gpt-5.5` | Raw | 1 | `+0.005` | `0.123` | `[-0.176, -0.008, +0.223]` | `1.098` | `1.445` | `[0.709, 0.985, 1.711]` | **52.6%** | `22.8%` |
| `opencode-gpt-5.5` | Raw | 2 | `+0.004` | `0.087` | `[-0.127, -0.002, +0.156]` | `1.037` | `0.225` | `[0.781, 0.996, 1.420]` | **50.9%** | `14.5%` |
| `opencode-gpt-5.5` | Raw | 3 | `+0.004` | `0.071` | `[-0.106, +0.000, +0.127]` | `1.026` | `0.162` | `[0.815, 1.001, 1.318]` | **49.8%** | `9.8%` |
| `opencode-gpt-5.5` | Raw | 5 | `+0.004` | `0.055` | `[-0.082, +0.002, +0.098]` | `1.018` | `0.118` | `[0.853, 1.004, 1.233]` | **48.5%** | `4.6%` |
| `opencode-gpt-5.5` | Luck-Adj | 1 | `-0.081` | `0.085` | `[-0.225, -0.080, +0.056]` | `0.849` | `0.166` | `[0.589, 0.842, 1.131]` | **82.8%** | `52.0%` |
| `opencode-gpt-5.5` | Luck-Adj | 2 | `-0.082` | `0.060` | `[-0.182, -0.081, +0.015]` | `0.842` | `0.115` | `[0.659, 0.838, 1.034]` | **91.6%** | `54.2%` |
| `opencode-gpt-5.5` | Luck-Adj | 3 | `-0.082` | `0.049` | `[-0.165, -0.081, -0.002]` | `0.840` | `0.093` | `[0.689, 0.838, 0.996]` | **95.4%** | `55.0%` |
| `opencode-gpt-5.5` | Luck-Adj | 5 | `-0.082` | `0.038` | `[-0.145, -0.081, -0.019]` | `0.839` | `0.072` | `[0.723, 0.837, 0.959]` | **98.6%** | `57.1%` |
| `opencode-3.5-flash` | Raw | 1 | `-0.126` | `0.192` | `[-0.449, -0.121, +0.183]` | `0.834` | `2.580` | `[0.171, 0.763, 1.524]` | **74.9%** | `59.4%` |
| `opencode-3.5-flash` | Raw | 2 | `-0.125` | `0.136` | `[-0.353, -0.123, +0.095]` | `0.772` | `0.282` | `[0.349, 0.759, 1.237]` | **82.5%** | `64.3%` |
| `opencode-3.5-flash` | Raw | 3 | `-0.128` | `0.111` | `[-0.312, -0.126, +0.052]` | `0.759` | `0.220` | `[0.420, 0.751, 1.122]` | **87.6%** | `68.4%` |
| `opencode-3.5-flash` | Raw | 5 | `-0.126` | `0.086` | `[-0.270, -0.124, +0.013]` | `0.756` | `0.165` | `[0.492, 0.753, 1.030]` | **93.1%** | `72.9%` |
| `opencode-3.5-flash` | Luck-Adj | 1 | `-0.389` | `0.191` | `[-0.719, -0.380, -0.090]` | `0.217` | `0.386` | `[-0.451, 0.237, 0.816]` | **98.8%** | `96.2%` |
| `opencode-3.5-flash` | Luck-Adj | 2 | `-0.389` | `0.135` | `[-0.618, -0.385, -0.173]` | `0.220` | `0.270` | `[-0.238, 0.229, 0.649]` | **99.9%** | `99.5%` |
| `opencode-3.5-flash` | Luck-Adj | 3 | `-0.389` | `0.110` | `[-0.575, -0.387, -0.211]` | `0.220` | `0.220` | `[-0.150, 0.226, 0.572]` | **100.0%** | `99.9%` |
| `opencode-3.5-flash` | Luck-Adj | 5 | `-0.390` | `0.086` | `[-0.533, -0.388, -0.251]` | `0.219` | `0.170` | `[-0.067, 0.223, 0.493]` | **100.0%** | `100.0%` |
| `inproc-carbon` | Raw | 1 | `-0.026` | `0.159` | `[-0.290, -0.025, +0.234]` | `1.063` | `3.985` | `[0.501, 0.953, 1.737]` | **57.1%** | `34.3%` |
| `inproc-carbon` | Raw | 2 | `-0.026` | `0.113` | `[-0.212, -0.026, +0.159]` | `0.977` | `0.259` | `[0.625, 0.950, 1.421]` | **59.6%** | `31.1%` |
| `inproc-carbon` | Raw | 3 | `-0.026` | `0.093` | `[-0.178, -0.026, +0.126]` | `0.967` | `0.198` | `[0.680, 0.949, 1.311]` | **61.0%** | `27.5%` |
| `inproc-carbon` | Raw | 5 | `-0.026` | `0.071` | `[-0.143, -0.026, +0.090]` | `0.958` | `0.145` | `[0.739, 0.948, 1.209]` | **64.5%** | `22.6%` |
| `inproc-carbon` | Luck-Adj | 1 | `-0.078` | `0.093` | `[-0.236, -0.076, +0.071]` | `0.855` | `0.183` | `[0.564, 0.849, 1.162]` | **79.4%** | `50.3%` |
| `inproc-carbon` | Luck-Adj | 2 | `-0.079` | `0.066` | `[-0.190, -0.077, +0.028]` | `0.848` | `0.127` | `[0.642, 0.846, 1.061]` | **88.5%** | `51.3%` |
| `inproc-carbon` | Luck-Adj | 3 | `-0.078` | `0.054` | `[-0.168, -0.078, +0.009]` | `0.847` | `0.103` | `[0.681, 0.845, 1.019]` | **93.0%** | `51.8%` |
| `inproc-carbon` | Luck-Adj | 5 | `-0.078` | `0.042` | `[-0.147, -0.078, -0.010]` | `0.846` | `0.080` | `[0.717, 0.845, 0.978]` | **97.1%** | `52.6%` |

Takeaways from Model (A):
- **Judge harness (`opencode-carbon`) power jump:** At `R=1` (`1x10`), raw `P(F < O)` is `85.1%` (a `14.9%` false-parity risk from 10-task sampling noise). At `R=3` (`3x10`), raw `P(F < O)` reaches **97.8%** (`95th` percentile of `F - O` is `-0.027 < 0`, and `95th` percentile of `F / O` is `0.942 < 1.00`). On luck-adjusted scores, `P(F < O)` is **94.4%** even at `R=1` and **99.8%** at `R=3`.
- **Second frontier family (`opencode-gpt-5.5`) parity on raw reward:** Because `gpt-5.5` averages `+0.504` vs solver `+0.499` (`F - O = +0.005`), its `3x10` raw `P(F < O)` is `49.8%` (near a 50/50 coin toss, `90%` band `[0.815, 1.318]`); on luck-adjusted scores (`+0.418` vs `+0.499`, reflecting its 2 abstentions), `3x10` `P(F < O)` is `95.4%`.
- **Empirical `sqrt(R)` scaling:** Across all models and both score types, `SD(R=3) = SD(R=1) / sqrt(3)` (`0.577x`) and `SD(R=5) = SD(R=1) / sqrt(5)` (`0.447x`). Notice that a single `1x10` luck-adjusted evaluation of `opencode-carbon` (`SD = 0.090`) already achieves lower estimator noise than **three** raw `1x10` runs combined (`SD = 0.097`)!

---

## 3. Model (B): Posterior-Calibrated Repeated-Run Outcome Model (`R in {1, 2, 3, 5}` on the SAME 10 Judge Worlds)

On an actual Harbor judge build (`python harbor/build.py`), the 10 hard worlds are **fixed** once by the build's 32-byte `SALT`; the oracle runs once on those 10 worlds, and the frontier agent runs `R=3` independent times on those **same** 10 worlds. Model (B) simulates this exact protocol over `50,000` builds: each build draws 10 hard worlds `W`, draws 1 oracle accusation outcome per world (`+V_s` w.p. `P_s`, `-1.0` w.p. `1 - P_s`), and draws `R in {1, 2, 3, 5}` independent frontier accusation outcomes per world (`+V` w.p. `P_accused`, `-1.0` w.p. `1 - P_accused`, `0.0` on abstention).

### 3.1 Simulated Judge Build Distributions (`k=10` shared worlds, 1 Oracle Run vs `R` Frontier Runs)

| Frontier Model | `R` Runs on Same 10 Worlds | `F - O` Mean | `F - O` SD | `F - O` `[p5, p50, p95]` | `F / O` Mean | `F / O` SD | `F / O` `[p5, p50, p95]` | `P(F < O)` | `P(F < 0.85*O)` | Within-Build Run SD (RMS) | Mean `R`-Run `max - min` |
|---|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---:|
| `opencode-carbon` | 1 | `-0.140` | `0.186` | `[-0.456, -0.133, +0.157]` | `0.771` | `0.739` | `[0.125, 0.741, 1.443]` | **77.7%** | `62.4%` | n/a | n/a |
| `opencode-carbon` | 2 | `-0.140` | `0.159` | `[-0.398, -0.142, +0.127]` | `0.780` | `1.912` | `[0.254, 0.727, 1.358]` | **82.1%** | `67.0%` | `0.135` | `0.144` |
| `opencode-carbon` | 3 | `-0.140` | `0.149` | `[-0.376, -0.145, +0.114]` | `0.772` | `0.622` | `[0.302, 0.722, 1.326]` | **83.4%** | `69.0%` | `0.135` | `0.216` |
| `opencode-carbon` | 5 | `-0.139` | `0.141` | `[-0.358, -0.147, +0.107]` | `0.781` | `0.835` | `[0.340, 0.720, 1.313]` | **84.5%** | `70.6%` | `0.135` | `0.292` |
| `opencode-gpt-5.5` | 1 | `-0.081` | `0.161` | `[-0.353, -0.076, +0.179]` | `0.926` | `2.318` | `[0.368, 0.856, 1.534]` | **69.9%** | `49.1%` | n/a | n/a |
| `opencode-gpt-5.5` | 2 | `-0.081` | `0.145` | `[-0.310, -0.086, +0.167]` | `0.922` | `2.146` | `[0.457, 0.836, 1.504]` | **72.7%** | `52.3%` | `0.105` | `0.100` |
| `opencode-gpt-5.5` | 3 | `-0.083` | `0.137` | `[-0.297, -0.091, +0.155]` | `0.909` | `1.158` | `[0.486, 0.827, 1.474]` | **74.5%** | `53.8%` | `0.104` | `0.151` |
| `opencode-gpt-5.5` | 5 | `-0.082` | `0.132` | `[-0.285, -0.091, +0.148]` | `0.910` | `1.286` | `[0.514, 0.827, 1.454]` | **75.3%** | `54.2%` | `0.104` | `0.204` |
| `opencode-3.5-flash` | 1 | `-0.389` | `0.247` | `[-0.806, -0.382, +0.011]` | `0.233` | `0.766` | `[-0.608, 0.225, 1.023]` | **94.4%** | `91.3%` | n/a | n/a |
| `opencode-3.5-flash` | 2 | `-0.389` | `0.229` | `[-0.773, -0.384, -0.019]` | `0.232` | `0.562` | `[-0.540, 0.235, 0.952]` | **95.8%** | `92.5%` | `0.125` | `0.131` |
| `opencode-3.5-flash` | 3 | `-0.390` | `0.224` | `[-0.764, -0.385, -0.031]` | `0.229` | `0.697` | `[-0.512, 0.236, 0.923]` | **96.3%** | `93.1%` | `0.125` | `0.196` |
| `opencode-3.5-flash` | 5 | `-0.390` | `0.217` | `[-0.755, -0.386, -0.043]` | `0.228` | `0.489` | `[-0.495, 0.235, 0.898]` | **96.7%** | `93.8%` | `0.124` | `0.270` |
| `inproc-carbon` | 1 | `-0.081` | `0.169` | `[-0.366, -0.076, +0.190]` | `0.904` | `0.577` | `[0.337, 0.856, 1.570]` | **68.6%** | `49.2%` | n/a | n/a |
| `inproc-carbon` | 2 | `-0.079` | `0.150` | `[-0.318, -0.083, +0.173]` | `0.923` | `2.182` | `[0.432, 0.840, 1.526]` | **71.8%** | `51.4%` | `0.109` | `0.108` |
| `inproc-carbon` | 3 | `-0.079` | `0.144` | `[-0.304, -0.086, +0.170]` | `0.916` | `0.828` | `[0.465, 0.837, 1.516]` | **72.5%** | `52.2%` | `0.109` | `0.162` |
| `inproc-carbon` | 5 | `-0.078` | `0.138` | `[-0.289, -0.087, +0.164]` | `0.911` | `0.623` | `[0.498, 0.834, 1.503]` | **73.5%** | `52.7%` | `0.109` | `0.218` |

### 3.2 Exact Rao-Blackwell Variance Decomposition: Why `R=3` Cuts Gamble Noise by `sqrt(3)` and Luck-Adjusted Scoring Cuts Variance by >2x

By the Law of Total Variance on a 10-world build `W`, the variance of the raw paired gap estimator `F_bar_R - O_bar_1` decomposes into three orthogonal pieces:

```text
Var(F_bar_R - O_bar_1) = Var_W(mu_F(W) - mu_O(W))  +  (1 / R) * E_W[Var(F_bar_1 | W)]  +  E_W[Var(O_bar_1 | W)]
                         [between-build LA gap]       [frontier accusation luck / R]      [oracle 5%-flip luck]
```

where single-task conditional accusation variance is `P_accused * (1 - P_accused) * (1 + V_at_accuse)^2` (`0` on abstention). Conditioning on `(V_at_accuse, P_accused)` (luck-adjusted scoring) is exact Rao-Blackwellization: it zeroes out both conditional accusation-luck terms simultaneously.

| Frontier Model | World LA Gap Var (`k=10`) | Frontier Luck Var (`R=1`) | Frontier Luck Var (`R=3`) | Oracle Luck Var (`1x10`) | Cond 1-Run SD -> 3-Run Mean SD (`sqrt(3)` cut) | Total Gap SD `R=1` -> `R=3` -> LA | LA Variance Ratio / `n_eff` Multiplier (Model B / Empirical) |
|---|---:|---:|---:|---:|---|---|---:|
| `opencode-carbon` | `0.0082` | `0.0183` | `0.0061` | `0.0079` | `0.135` -> `0.078` (`1.732x`) | `0.185` -> `0.149` -> `0.090` | **`4.22x` (`n_eff=42.2`) / `3.48x` (`n_eff=34.8`)** |
| `opencode-gpt-5.5` | `0.0073` | `0.0110` | `0.0037` | `0.0079` | `0.105` -> `0.060` (`1.732x`) | `0.162` -> `0.138` -> `0.086` | **`3.58x` (`n_eff=35.8`) / `2.06x` (`n_eff=20.6`)** |
| `opencode-3.5-flash` | `0.0367` | `0.0155` | `0.0052` | `0.0079` | `0.125` -> `0.072` (`1.732x`) | `0.245` -> `0.223` -> `0.191` | **`1.64x` (`n_eff=16.4`) / `1.01x` (`n_eff=10.1`)** |
| `inproc-carbon` | `0.0087` | `0.0119` | `0.0040` | `0.0079` | `0.109` -> `0.063` (`1.732x`) | `0.169` -> `0.144` -> `0.093` | **`3.28x` (`n_eff=32.8`) / `2.92x` (`n_eff=29.2`)** |

Key variance findings:
- **Run-to-run spread on identical worlds:** Even with the exact same 10 worlds and stopping posteriors, 3 independent runs of `opencode-carbon` exhibit an RMS run-to-run SD of **`0.135 V`** (exact closed-form `0.135 V`), with an average `max - min` spread of **`0.216 V`** between the luckiest and unluckiest of the 3 judge runs (`0.104 V` SD and `0.151 V` spread for `opencode-gpt-5.5`). Averaging all 3 runs cuts that frontier luck SD by `sqrt(3) = 1.732x` to `0.078 V`.
- **Why `R` plateaus without luck adjustment, and why luck adjustment wins by >2x:** On a single Harbor build, increasing `R` from `1 -> 3 -> 5` shrinks `frontier_luck_var / R` (`0.0183 -> 0.0061 -> 0.0037` for `opencode-carbon`), but cannot shrink the single oracle run's 5%-flip variance (`0.0079`) or between-world variance (`0.0082`). Luck-adjusted scoring eliminates **both** frontier and oracle coin-flip noise, cutting `opencode-carbon` estimator variance by **`4.22x`** under Model B (`2.72x` even versus `3x10` raw!) and **`3.48x`** empirically across the 30 paired seeds (`3.58x` under Model B for `opencode-gpt-5.5`).
- **`gemini-3.5-flash` correction:** Once lucky gambles are replaced by calibrated posterior draws in Model B, `3.5-flash`'s mean gap widens from its lucky empirical `-0.126 V` to **`-0.390 V`**, and `P(3-run frontier mean < oracle)` reaches **`96.3%`**.

---

## 4. Posterior-Calibrated Multi-Run Reliability (`pass^1`, `pass^2`, `pass^3`)

Following `tau-bench` (`canary/analysis/gap.py:pass_hat_k`), `pass^k` is the probability that an agent identifies the true mole on **all `k` independent runs** of the same world. Under the exact solver posterior `P_win` at accusation (`P_win = 0` on abstention), posterior-calibrated reliability is `pass^k = E[P_win^k]` across the 30 hard worlds:

| Policy | Empirical 1-Run Acc | Calibrated `pass^1` `[95% CI]` | Calibrated `pass^2` `[95% CI]` | Calibrated `pass^3` `[95% CI]` | Homogeneous `(E[P_win])^3` | Expected `3/3` Tasks (of 10) | Gamble Worlds (`P<0.60`) `pass^3` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `solver` | `0.967` | `0.965 [0.952, 0.977]` | `0.933 [0.907, 0.956]` | **`0.903`** `[0.867, 0.935]` | `0.899` | `9.03 / 10` | n/a (0 worlds) |
| `opencode-gpt-5.5` | `0.933` | `0.877 [0.778, 0.953]` | `0.831 [0.730, 0.915]` | **`0.792`** `[0.686, 0.883]` | `0.675` | `7.92 / 10` | n/a (0 worlds) |
| `inproc-carbon` | `0.933` | `0.899 [0.819, 0.956]` | `0.846 [0.758, 0.919]` | **`0.804`** `[0.707, 0.888]` | `0.726` | `8.04 / 10` | `0.176` (1 world) |
| `opencode-carbon` | `0.833` | `0.852 [0.769, 0.921]` | `0.773 [0.674, 0.863]` | **`0.714`** `[0.602, 0.819]` | `0.620` | `7.14 / 10` | `0.112` (2 worlds) |
| `opencode-3.5-flash` | `0.900` | `0.710 [0.572, 0.838]` | `0.637 [0.484, 0.783]` | **`0.601`** `[0.446, 0.750]` | `0.357` | `6.01 / 10` | `0.028` (10 worlds) |

Why `pass^3` separates calibrated Bayesian investigation from lucky gambling:
- **The cubic penalty on uncalibrated guesses (`0.71^3 << 0.97^3`):** At mean posterior `0.965`, a homogeneous solver retains `0.965^3 = 0.899` (`E[P_win^3] = 0.903` across the 30 worlds: **9.03 of 10** tasks solved cleanly 3-for-3). At `3.5-flash`'s mean posterior `0.710`, homogeneous reliability is `0.710^3 = 0.357`. Even with its bimodal split (20 justified worlds + 10 low-posterior gambles), `3.5-flash`'s exact `E[P_win^3]` collapses from its single-run empirical `0.900` down to **`0.601`** (**6.01 of 10** tasks solved 3-for-3, a **30.2 percentage point deficit** behind the oracle).
- **Complete collapse on gamble worlds:** On the 10 hard seeds where `opencode-3.5-flash` committed with `P_accused < 0.60` and won `7/10` (`0.700`) in one lucky run, its probability of winning all 3 judge runs is just **`0.028` (`2.8%`)**.
- **Consistent ordering across all five policies:** On `pass^3`, all five policies rank strictly by true investigative calibration: `solver` (`0.903`) > `inproc-carbon` (`0.804`) > `opencode-gpt-5.5` (`0.792`, `0` gambles, capped only by `2/30` abstentions) > `opencode-carbon` (`0.714`) > `opencode-3.5-flash` (`0.601`).

---

## 5. Empirical Validation on the Live 3-Run Harbor Rehearsal (`afterquery-final` `1bc3e281`)

The pre-registered live judge rehearsal (`results/harbor/rehearsal/README.md` & `TABLE.md`, corrected in `aa1c679e` and `5f9b3297`; full trial directories on `s1-rehearsal-final` `d0ead011`) ran Harbor `0.26.0` (`oracle`, 3 independent `OpenCode + gemini-4-carbon` runs, `do_nothing`, and `stop_early`) on 10 fresh salted hard tasks (`900000-900009`):

| Rehearsal Cohort (`afterquery-final`) | Valid Trials | Infra Excluded | Correct / Accused | Run Mean | Same-Task Oracle | Run / Oracle `[95% Paired Boot CI]` | Paired Diff |
|---|---:|---:|---:|---:|---:|---|---:|
| `oracle` (`SolverPolicy` over MCP) | `10` | `0` | `9 / 10` | `+0.506` | `+0.506` | `100% (ref)` | `+0.000` |
| `opencode-1` (`gemini-4-carbon`) | `10` | `0` | `9 / 10` | `+0.472` | `+0.506` | `93% [20%, 371%]` | `-0.034` |
| `opencode-2` (`gemini-4-carbon`) | `10` | `0` | `10 / 10` | `+0.585` | `+0.506` | `116% [78%, 363%]` | `+0.079` |
| `opencode-3` final (`aa1c679e` / `d0ead011`) | `9` | `1` | `9 / 9` | `+0.626` | `+0.478` | `131% [86%, 590%]` | `+0.148` |
| `opencode-3` `08:52` snapshot (`TABLE.md` body) | `7` | `1` | `7 / 7` | `+0.656` | `+0.429` | `153% [89%, 411%]` | `+0.227` |
| `do_nothing` / `stop_early` | `10 / 10` | `0` | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` | `-0.506` |

How the live rehearsal tests our variance formulas -- and what it changes about the headline claim:
- **Single-flip swing formula confirmed to `0.003 V`:** On `hard-900002`, `opencode-1` accused wrong (`-1.00` at d14) while `opencode-2` solved it (`+0.58` at d13), swinging the 10-task run mean by **`0.158 V`** (vs Model B's predicted `0.155 V`). Likewise, the oracle suffered one 5%-noise flip on `hard-900007` (`-1.00` at d15 vs `+0.673` mean across the other 9 tasks), shifting the 10-task oracle mean by **`0.167 V`** to `+0.506` (inside the 200-build 90% band `[+0.393, +0.678]`).
- **Run-to-run spread matches conditional Bernoulli noise:** Across the 3 final OpenCode runs (`+0.472`, `+0.585`, `+0.626`), the mean of means is **`+0.561`** with run-to-run **`SD = 0.080`** and **`range = 0.154`** (`SD = 0.093`, `range = 0.184` on the `08:52` `n=7` snapshot), well below the MCP-only `P = 0.882` conditional Bernoulli ceiling (`0.135 V` SD, `0.216 V` mean range) because accuracy rose to `28/29` (`96.6%`).
- **Honest non-reproduction of the MCP-only gap in Harbor:** Unlike the MCP-only `opencode-carbon` cohort (`bash`/`python3` denied, `25/29` accused correct, `65%` raw / `72%` luck-adjusted), the Harbor agent container enables `bash` and `python3` (isolation `11/11` verified; shell used in `20/28` trials) on the post-15-Nov tag (`1bc3e281`). Scoring **`93%`, `116%`, and `131%`** across 3 runs shows that **the `65%` MCP-only gap did not reproduce in the full Harbor judge path**; a judge rerunning Harbor or `gpt-5.5` (`101%` raw) should expect near-reference performance.

---

## 6. Operational Guidance for Judge Reruns

1. **Expect `0.08-0.14 V` run-to-run spread across 3 frontier Harbor runs:** On a fixed 10-task hard build, runs differing by `0.11-0.22 V` (1 flipped accusation at `~0.16 V`, as observed between `opencode-1` `+0.472` and `opencode-2` `+0.585` / `opencode-3` `+0.626`) is normal conditional Bernoulli variance (`RMS SD = 0.135 V` at `P=0.882`, `0.080 V` observed at `28/29` accuracy), not infra instability.
2. **Always average all `R=3` frontier runs against the paired build's oracle:** Pooling `3x10` frontier trials cuts accusation-luck SD by `sqrt(3)` and stabilises comparisons against single-task oracle 5%-flip swings (`hard-900007`).
3. **Report luck-adjusted score alongside raw ledger reward:** Computing `P_accused * V - (1 - P_accused)` from the MCP transcript's tool observations requires zero ground-truth leakage, cuts paired gap variance by `3.5x-4.2x` on `opencode-carbon` (`3.58x` on `opencode-gpt-5.5` under Model B), and prevents lucky horizon gamblers (`gemini-3.5-flash`) from masquerading as calibrated policies.
