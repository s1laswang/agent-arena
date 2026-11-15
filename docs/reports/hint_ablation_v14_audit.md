# Hint Ablation v1.4 Hard Causal Audit (Paired Posterior, Exploration & Luck-Adjusted EV)

**Scope.** Rules `v1.4`, `hard` tier, paired dev seeds `0-9` (`n=10` per arm; `30` real `gemini-4-carbon` in-process episodes from `data/runs/ablate-v2-hard-gemini` commit `d96a80f10bdd`), replay-verified in `canary.env.Env('hard', seed)` and paired seed-by-seed against `control`, the `v1.4` reference `solver`, and committed `v1.4` `inproc-gemini-4-carbon` and `opencode-gemini-4-carbon` runs on the same seeds (`30` context episodes).

**Reproduce (offline, deterministic, no API keys):**
- Re-verify committed audit JSON + report (works on shallow CI clones): `python scripts/hint_ablation_audit.py --verify-json`
- Full extraction + `Env` replay from git ref: `python scripts/hint_ablation_audit.py --from-git-ref origin/justSilas-agents2`

## 1. Executive Summary & Honest Causal Verdict

- **Replay integrity:** `30/30` ablation episodes and `30/30` context episodes replay in `Env('hard', seed)` with `0` score mismatches, `0` accusation mismatches, and `0` errors/timeouts (`max |score_diff| = 0.0e+00`).
- **Raw scoreboard vs luck-adjusted EV (`P*V - (1-P)`):** On raw score, `control` averages `+0.427` (`+/- 0.329`), `premature_accusation` `+0.487` (`+/- 0.081`), and `decoy_chase` `+0.648` (`+/- 0.077`), vs reference `solver` `+0.576` (`+/- 0.108`). Under `SolverPolicy`'s exact Bayesian posterior over each agent's own observations, luck-adjusted scores are `+0.420` (`control`), `+0.448` (`premature_accusation`), `+0.603` (`decoy_chase`), and `+0.556` (`solver`).
- **Paired treatment effects vs `control` (10,000-resample bootstrap 95% CIs):**
  - `premature_accusation - control`: raw `+0.060` [-0.176, +0.407]; luck-adjusted `+0.028` [-0.141, +0.292].
  - `decoy_chase - control`: raw `+0.221` [-0.047, +0.605]; luck-adjusted `+0.183` [-0.030, +0.471].
- **Statistical honesty (`n=10` per arm):** Every paired score 95% CI against `control` straddles `0.000`, and an independent no-hint `inproc-gemini-4-carbon` run on the exact same seeds `0-9` scored `+0.379` raw / `+0.439` luck-adjusted (`inproc - control = -0.048` [-0.409, +0.397] raw, `+0.019` [-0.195, +0.225] luck-adjusted). We therefore do **not** claim a statistically significant score gain from `n=10` alone, and we separate the exact behavioral mechanism shifts from single-seed accusation variance below.

## 2. Exact Experimental Prompts (`HINTS_V2`, Fact-Only)

All three arms run `LLMPolicy('gemini:gemini-4-carbon', context='full', temperature=0.0, hint_set='v2')` on `Env('hard', seed)`. Each hint appends a single sentence restating rules already printed in `Env.instruction()`:

- **`control`** (`1072` LLM calls): no extra sentence.
- **`premature_accusation`** (`904` LLM calls): `"Before accusing, estimate P(correct) from the evidence: accusing is only worth it if P x V - (1 - P) > 0; otherwise keep investigating, or end without accusing (score 0)."`
- **`decoy_chase`** (`777` LLM calls): `"After-hours accesses are partly faked by the mole (framing), half of them onto the angry decoy, so logs and anger are weak evidence; leaked canary variants are strong evidence."`

## 3. Per-Arm & Context Summary Table (`seeds 0-9`, `hard` v1.4)

| Run / Arm | n | Raw score +/- CI | Raw boot 95% CI | Luck-adj (`P*V-(1-P)`) | Luck-adj boot 95% CI | Acc | Abstain | Accuse day | Canaries +/- CI | Interviews | Decoy IV share (pooled / ep) | `P(accused)` mean / med | `P(top)` mean | `EV < 0` gambles |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ablation: `control` | 10 | +0.427 +/- 0.329 | [+0.073, +0.661] | +0.420 | [+0.138, +0.604] | 0.90 | 0.00 | 11.9 | 7.7 +/- 2.0 | 53.4 | 0.2% / 0.2% | 0.877 / 0.971 | 0.911 | 1 |
| ablation: `premature_accusation` | 10 | +0.487 +/- 0.081 | [+0.409, +0.565] | +0.448 | [+0.374, +0.525] | 1.00 | 0.00 | 13.6 | 8.8 +/- 2.2 | 31.9 | 0.0% / 0.0% | 0.974 / 0.972 | 0.974 | 0 |
| ablation: `decoy_chase` | 10 | +0.648 +/- 0.077 | [+0.568, +0.713] | +0.603 | [+0.529, +0.661] | 1.00 | 0.00 | 9.0 | 7.7 +/- 1.8 | 34.6 | 0.0% / 0.0% | 0.973 / 0.964 | 0.973 | 0 |
| ref: `solver` (same seeds) | 10 | +0.576 +/- 0.108 | [+0.465, +0.668] | +0.556 | [+0.440, +0.653] | 1.00 | 0.00 | 9.9 | 12.9 +/- 3.5 | 0.0 | 0.0% / 0.0% | 0.987 / 0.997 | 0.987 | 0 |
| context: `inproc-gemini-4-carbon` | 10 | +0.379 +/- 0.324 | [+0.030, +0.618] | +0.439 | [+0.262, +0.590] | 0.90 | 0.00 | 12.0 | 8.8 +/- 2.1 | 53.5 | 0.2% / 0.1% | 0.938 / 0.982 | 0.938 | 2 |
| context: `opencode-gemini-4-carbon` | 10 | +0.351 +/- 0.312 | [+0.020, +0.575] | +0.310 | [+0.110, +0.475] | 0.90 | 0.00 | 14.5 | 9.7 +/- 2.6 | 70.0 | 0.0% / 0.0% | 0.875 / 0.951 | 0.875 | 1 |

## 4. Paired Comparisons (`arm - control` and `arm / solver`, 10,000 Bootstrap Resamples)

### 4.1 Paired Treatment Effects vs `control` (`seeds 0-9`)

| Comparison (`target - control`) | Raw diff +/- CI | Raw diff boot 95% CI | Luck-adj diff +/- CI | Luck-adj boot 95% CI | Canaries diff [95% CI] | Interviews diff [95% CI] | Decoy IV share diff [95% CI] | Final day diff [95% CI] | `P(accused)` diff [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| `premature_accusation - control` | +0.060 +/- 0.323 | [-0.176, +0.407] | +0.028 +/- 0.244 | [-0.141, +0.292] | +1.1 [-1.5, +3.4] | -21.5 [-39.6, -5.5] | -0.2 pp [-0.6, +0.0] | +1.7 [-1.3, +4.5] | +0.097 [+0.008, +0.240] |
| `decoy_chase - control` | +0.221 +/- 0.359 | [-0.047, +0.605] | +0.183 +/- 0.269 | [-0.030, +0.471] | +0.0 [-2.2, +1.8] | -18.8 [-40.9, +3.7] | -0.2 pp [-0.6, +0.0] | -2.9 [-6.3, +0.8] | +0.096 [+0.005, +0.248] |
| `inproc_gemini - control` (no-hint replicate) | -0.048 +/- 0.427 | [-0.409, +0.397] | +0.019 +/- 0.217 | [-0.195, +0.225] | +1.1 [-1.5, +4.3] | +0.1 [-18.1, +18.6] | -0.1 pp [-0.6, +0.4] | +0.1 [-2.7, +3.5] | +0.061 [-0.005, +0.149] |

**Sensitivity excluding `control`'s wrong-accusation seed(s):**
- Excluding wrong seed(s) `[3]` (`n=9` paired seeds): `premature_accusation - control` is `-0.094` [-0.200, +0.039] raw and `+0.031` [-0.154, +0.325] luck-adjusted; `decoy_chase - control` is `+0.050` [-0.081, +0.187] raw and `+0.178` [-0.049, +0.494] luck-adjusted.

### 4.2 Paired Ratios & Differences vs Reference `solver` (`seeds 0-9`)

| Run / Arm | Raw / `solver` [boot 95% CI] | Raw diff (`arm - solver`) [boot 95% CI] | Luck-adj / `solver` [boot 95% CI] | Luck-adj diff (`arm - solver`) [boot 95% CI] | Canaries diff vs `solver` | Final day diff vs `solver` |
|---|---|---|---|---|---|---|
| ablation: `control` | 74.1% [14%, 116%] | -0.149 [-0.455, +0.088] | 75.6% [24%, 116%] | -0.136 [-0.453, +0.074] | -5.2 | +2.0 |
| ablation: `premature_accusation` | 84.5% [67%, 106%] | -0.089 [-0.209, +0.031] | 80.6% [63%, 103%] | -0.108 [-0.227, +0.016] | -4.1 | +3.7 |
| ablation: `decoy_chase` | 112.5% [88%, 149%] | +0.072 [-0.076, +0.231] | 108.5% [85%, 143%] | +0.047 [-0.095, +0.192] | -5.2 | -0.9 |
| context: `inproc-gemini-4-carbon` | 65.8% [5%, 117%] | -0.197 [-0.583, +0.083] | 78.9% [45%, 117%] | -0.117 [-0.327, +0.080] | -4.1 | +2.1 |
| context: `opencode-gemini-4-carbon` | 60.9% [3%, 104%] | -0.225 [-0.584, +0.020] | 55.7% [21%, 80%] | -0.246 [-0.425, -0.109] | -3.2 | +4.6 |

## 5. Exploration, Interview Waste & Posterior Calibration Breakdown

| Metric | `control` | `premature_accusation` | `decoy_chase` | `solver` | `inproc` | `opencode` |
|---|---|---|---|---|---|---|
| Canary capacity used (`2/day`) | 32.4% | 32.4% | 42.8% | 65.2% | 36.7% | 33.4% |
| Episodes with day-1 canary (`of 10`) | 4/10 | 1/10 | 7/10 | 10/10 | 4/10 | 4/10 |
| Days with >=1 canary | 44.5% | 44.1% | 48.9% | 89.9% | 45.8% | 40.0% |
| Mean first canary day | 2.4 | 3.4 | 2.2 | 1.0 | 2.5 | 2.4 |
| Leaks before accusation / `true_V` at end | 6.8 / 0.583 | 8.5 / 0.487 | 5.5 / 0.648 | 5.9 / 0.576 | 7.5 / 0.529 | 8.2 / 0.483 |
| Total interviews (10 seeds) | 534 | 319 | 346 | 0 | 535 | 700 |
| Decoy interviews (10 seeds; random = 2.5%) | 1 (0.2%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 1 (0.2%) | 0 (0.0%) |
| Accused / restricted decoy | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Access-log / message-search reads | 10.7 / 2.8 | 11.1 / 3.2 | 7.7 / 2.8 | 8.9 / 7.6 | 10.7 / 3.4 | 13.4 / 3.3 |
| Accusations at `P >= 0.95` / `0.85-0.95` / `0.60-0.85` / `< 0.60` | 6/3/0/1 | 9/1/0/0 | 9/1/0/0 | 9/1/0/0 | 7/2/1/0 | 5/1/3/1 |
| Isolated (`consistent_count == 1`) at accusation | 8/10 | 7/10 | 9/10 | 8/10 | 7/10 | 6/10 |
| Expected wrong (`sum(1 - P)`) vs realized wrong | 1.23 vs 1 | 0.26 vs 0 | 0.27 vs 0 | 0.13 vs 0 | 0.62 vs 1 | 1.25 vs 1 |
| Luck windfall (`raw - luck_adjusted`) | +0.007 | +0.039 | +0.045 | +0.020 | -0.060 | +0.041 |

## 6. Per-Seed Paired Audit Table (`seeds 0-9`)

| Seed | `control` raw / LA (`day`, `P`, `can`/`iv`) | `premature_acc` raw / LA (`day`, `P`, `can`/`iv`) | `decoy_chase` raw / LA (`day`, `P`, `can`/`iv`) | `solver` raw / LA (`day`, `P`, `can`) | `inproc` raw / LA | `opencode` raw / LA |
|---|---|---|---|---|---|---|
| 0 | +0.50 / +0.34 (d13, P=0.89, 10/36) | +0.24 / +0.24 (d21, P=1.00, 16/35) | +0.52 / +0.52 (d11, P=1.00, 13/41) | +0.64 / +0.56 (d9, P=0.95, 11) | +0.57 / +0.56 | +0.59 / +0.56 |
| 1 | +0.65 / +0.61 (d12, P=0.98, 5/11) | +0.66 / +0.66 (d10, P=1.00, 4/17) | +0.67 / +0.67 (d10, P=1.00, 3/53) | +0.69 / +0.66 (d7, P=0.99, 11) | +0.55 / +0.53 | -1.00 / +0.30 |
| 2 | +0.53 / +0.52 (d12, P=0.99, 7/51) | +0.48 / +0.43 (d12, P=0.97, 7/18) | +0.68 / +0.62 (d7, P=0.96, 7/14) | +0.58 / +0.58 (d9, P=1.00, 12) | +0.31 / +0.28 | +0.48 / +0.44 |
| 3 | -1.00 X / +0.43 (d13, P=0.92, 9/75) | +0.45 / +0.43 (d17, P=0.99, 10/79) | +0.76 / +0.66 (d7, P=0.94, 9/24) | +0.28 / +0.23 (d18, P=0.96, 22) | +0.59 / +0.57 | +0.51 / +0.16 |
| 4 | +0.72 / +0.67 (d9, P=0.97, 8/44) | +0.39 / +0.34 (d17, P=0.96, 11/26) | +0.38 / +0.33 (d19, P=0.96, 12/70) | +0.73 / +0.73 (d5, P=1.00, 7) | +0.76 / +0.70 | +0.40 / +0.39 |
| 5 | +0.71 / +0.66 (d9, P=0.97, 4/49) | +0.63 / +0.59 (d9, P=0.98, 7/12) | +0.59 / +0.58 (d9, P=0.99, 6/43) | +0.52 / +0.49 (d9, P=0.98, 13) | +0.10 / -0.01 | +0.16 / -0.41 |
| 6 | +0.15 / -0.74 (d21, P=0.23, 15/118) | +0.48 / +0.37 (d12, P=0.93, 7/34) | +0.63 / +0.57 (d7, P=0.97, 7/30) | +0.71 / +0.71 (d6, P=1.00, 9) | -1.00 / -0.06 | +0.73 / +0.73 |
| 7 | +0.61 / +0.59 (d10, P=0.98, 4/37) | +0.45 / +0.45 (d13, P=1.00, 10/41) | +0.73 / +0.72 (d7, P=0.99, 7/24) | +0.64 / +0.64 (d9, P=1.00, 11) | +0.52 / +0.44 | +0.69 / +0.32 |
| 8 | +0.67 / +0.44 (d12, P=0.86, 8/70) | +0.44 / +0.38 (d15, P=0.96, 11/22) | +0.78 / +0.69 (d7, P=0.95, 7/29) | +0.26 / +0.26 (d21, P=1.00, 24) | +0.65 / +0.62 | +0.35 / +0.12 |
| 9 | +0.73 / +0.68 (d8, P=0.97, 7/43) | +0.65 / +0.58 (d10, P=0.96, 5/35) | +0.74 / +0.67 (d6, P=0.96, 6/18) | +0.71 / +0.70 (d6, P=1.00, 9) | +0.74 / +0.74 | +0.60 / +0.49 |

`X` = wrong accusation (`-1.00`); `ABST` = abstained (`0.00`); `LA` = luck-adjusted score `P*V - (1-P)`.

## 7. Causal Interpretation & Limitations

1. **Forensic correction to raw-only reading (`control` wrong accusation != premature accusation):** Replay + `SolverPolicy` belief reconstruction reveals two opposite luck events hidden inside `control`'s `+0.427` raw mean (`+0.420` luck-adjusted). `control`'s wrong accusation (seed 3 (`score=-1.00`, `P=0.917`, `EV=+0.432`, `flips=1`, `LA=+0.431`)) was **not** a premature gamble -- it occurred at high Bayesian posterior after a 5% canary fingerprint flip, so `control` suffered bad luck there. Conversely, `control`'s actual premature / negative-EV gamble (seed 6 (`day=21`, `score=+0.15`, `P(accused)=0.226`, `P(top)=0.572`, `EV=-0.740`, `LA=-0.740`, `windfall=+0.890`)) **succeeded by luck** above posterior EV. Those two opposite luck shocks nearly cancelled in `control`'s aggregate (`raw - LA = +0.007`).
2. **Why `decoy_chase` works via canary-vs-log weighting, not decoy avoidance:** Across all unhinted runs (`control` `1/534` = `0.2%`, `inproc` `1/535` = `0.2%`, `opencode` `0/700` = `0.0%`), `gemini-4-carbon` already avoids interviewing, restricting (`0/10`), or accusing (`0/10`) the angry decoy (well below the `1/40 = 2.5%` uniform rate). Instead, the second clause of `HINTS_V2['decoy_chase']` (*"logs and anger are weak evidence; leaked canary variants are strong evidence"*) shifts exploration from Day 1: day-1 canary episodes rise from `4/10` (`control`) to `7/10` (`decoy_chase`), daily canary capacity utilization rises from `32.4%` to `42.8%`, access-log reads drop `10.7 -> 7.7`, interviews drop by `-18.8` [-40.9, +3.7] (`534 -> 346`), and accusation day advances from `11.9` to `9.0` (`8/10` paired seed wins raw, `7/10` luck-adjusted). Removing its `+0.045` luck windfall (`0` wrong vs `0.27` expected) trims `decoy_chase` from `+0.648` raw to `+0.603` luck-adjusted (108.5% of `solver` [85%, 143%]).
3. **Why `premature_accusation` improves posterior calibration but trades away time/leak V:** Reminding the agent of `P x V - (1 - P) > 0` eliminates negative-EV horizon gambling (`1 -> 0` gambles; `P(accused)` mean `0.877 -> 0.974`, paired diff `+0.097` [+0.008, +0.240]) and cuts interviews by `-21.5` [-39.6, -5.5]. However, it also delays first canary planting (`2.4 -> 3.4`) and delays accusation (`11.9 -> 13.6`, leaks `6.8 -> 8.5`, `true_V_end` `0.583 -> 0.487`), leaving a modest net luck-adjusted diff of `+0.028` [-0.141, +0.292].
4. **Honest `n=10` statistical power caveat:** With `n=10` paired seeds per arm, every paired score 95% bootstrap CI against `control` crosses zero (`premature_accusation`: raw `[-0.176, +0.407]`, LA `[-0.141, +0.292]`; `decoy_chase`: raw `[-0.047, +0.605]`, LA `[-0.030, +0.471]`), and an independent no-hint `inproc-gemini-4-carbon` run on seeds `0-9` differs from `control` by `-0.048` [-0.409, +0.397] raw (`+0.019` [-0.195, +0.225] LA). The behavioral shifts (fewer wasted interviews, higher accusation posteriors `0.974` / `0.973` vs `0.877`, and earlier canary pipelining under `decoy_chase`) are clear in mechanism, while headline score superiority requires `n >= 30` paired seeds to resolve.
