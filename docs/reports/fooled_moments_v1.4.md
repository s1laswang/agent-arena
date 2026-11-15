# Fooled Moments & Showcase Replay Audit (Rules v1.4)

**Scope.** Keyless replay audit of all committed rules v1.4 episodes in `data/runs/committed/v1.4/` (410 valid episodes total; 150 real LLM episodes across 5 `(tier, agent)` lanes paired seed-for-seed with the reference `solver`, plus 260 scripted baseline episodes). Every number below is computed deterministically from the agent's own recorded tool observations by the `replay` package (`replay/loader.py`, `replay/belief_trace.py`, `replay/fooled.py`, `replay/analytics.py`) with zero API keys. Companion reports: [gap.md](gap.md) and [failure_analysis_v1.4.md](failure_analysis_v1.4.md).

**Reproduce (no keys, <10 seconds):**
```bash
uv run pytest tests/test_replay_*.py
uv run python -c "from replay.loader import load_committed_episodes, pair_with_solver; from replay.fooled import rank_showcase_pairs; print(len(rank_showcase_pairs(pair_with_solver(load_committed_episodes('data/runs/committed/v1.4')), limit=15)))"
```

## 1. Headline Findings Across 150 Paired Real v1.4 Episodes

- **Primary `gap.md` v1.4 headline (`n=30` paired seeds 0 to 29 on `hard`):** In the judges' harness (`opencode:google/gemini-4-carbon` over MCP), the frontier agent scores **65% [24%, 98%]** raw (`0.322` vs solver `0.499`) and **72% [52%, 91%]** luck-adjusted (`0.360` vs `0.499`).
- **22 fooled episodes (`fooled=True`) and 2 disclosed bad-luck flips (`bad_luck=True, fooled=False`)** across all 150 paired real v1.4 episodes (`126` episodes have `kind="none"`, comprising `120` justified accusations and `6` rational abstentions).
- **Separating being fooled from disclosed noise.** When `opencode:google/gemini-4-carbon` accuses an innocent on `hard` seeds 1 and 26 at solver posteriors `P=0.9878` (`EV=+0.3534`) and `P=0.9504` (`EV=+0.5872`), `detect_fooled_moment` classifies both as `fingerprint_bad_luck` (`fooled=False, bad_luck=True`), isolating the 5% canary fingerprint flip from genuine calibration failures.
- **Why luck-adjusted scoring changes model rankings.** On `hard` (`n=30`, seeds 0 to 29), `opencode:google/gemini-3.5-flash` achieves a higher raw score than `opencode:google/gemini-4-carbon` (`0.373` vs `0.322`, or **75% [36%, 123%]** vs **65% [24%, 98%]** of solver `0.499`). Under the Bayesian belief tracer, `gemini-3.5-flash` collapses to **22% [-23%, 63%]** luck-adjusted (`0.110`) while `gemini-4-carbon` rises to **72% [52%, 91%]** luck-adjusted (`0.360`). `gemini-3.5-flash` is fooled on **10/30** seeds (`7` negative-EV `subthreshold_gamble` hits, `2` `premature_wrong`, `1` `decoy_chase`), whereas `gemini-4-carbon` over MCP is fooled on **4/30** seeds (`2` `subthreshold_gamble`, `1` `premature_wrong`, `1` `wrong_accusation`).

## 2. Paired Gap, Calibration, and Fooled Breakdown by Lane (v1.4)

Paired ratios and 95% bootstrap CIs match `docs/reports/gap.md` and `python scripts/paired_gemini.py --version v1.4 --seeds 0-29`; fooled and bad-luck classifications come from `replay.fooled.analyze_pair_fooled`:

| Tier | Agent | Paired `n` | Raw Mean | Solver Mean | Frontier / Solver [95% CI] | Luck-Adj Mean | Luck-Adj / Solver [95% CI] | Mean `P(accused)` | Premature Rate | `fooled` | `bad_luck` | Breakdown (`kind`) |
|---|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---|
| `hard` | `solver` (scripted ref) | 30 | 0.499 | 0.499 | 100% [100%, 100%] | 0.499 | 100% [100%, 100%] | 0.9652 | 0.00% | 0 | 0 | `none`: 30 |
| `hard` | `opencode:google/gemini-4-carbon` | 30 | 0.322 | 0.499 | **65% [24%, 98%]** | 0.360 | **72% [52%, 91%]** | 0.8819 | 10.00% | 4 | 2 | `none`: 24, `fingerprint_bad_luck`: 2, `subthreshold_gamble`: 2, `wrong_accusation`: 1, `premature_wrong`: 1 |
| `hard` | `gemini:gemini-4-carbon` | 30 | 0.473 | 0.499 | 95% [62%, 140%] | 0.421 | 84% [65%, 106%] | 0.9299 | 10.00% | 3 | 0 | `none`: 27, `subthreshold_gamble`: 2, `premature_wrong`: 1 |
| `hard` | `opencode:google/gemini-3.5-flash` | 30 | 0.373 | 0.499 | 75% [36%, 123%] | 0.110 | 22% [-23%, 63%] | 0.7095 | 33.33% | 10 | 0 | `none`: 20, `subthreshold_gamble`: 7, `premature_wrong`: 2, `decoy_chase`: 1 |
| `medium` | `solver` (scripted ref) | 30 | 0.645 | 0.645 | 100% [100%, 100%] | 0.645 | 100% [100%, 100%] | 1.0000 | 0.00% | 0 | 0 | `none`: 30 |
| `medium` | `opencode:google/gemini-4-carbon` | 30 | 0.713 | 0.645 | 111% [99%, 127%] | 0.652 | 101% [85%, 119%] | 0.9615 | 6.67% | 2 | 0 | `none`: 28, `subthreshold_gamble`: 2 |
| `medium` | `gemini:gemini-4-carbon` | 30 | 0.530 | 0.645 | 82% [56%, 108%] | 0.479 | 74% [52%, 99%] | 0.9286 | 10.00% | 3 | 0 | `none`: 27, `subthreshold_gamble`: 2, `premature_wrong`: 1 |

Step-level failure tag attribution (`aggregate_failure_tags`) confirms the structural gap on `hard`:
- `opencode:google/gemini-3.5-flash`: total regret `13.4251` (`0.4475` per episode), led by `uninformative_canary` (`51` steps across `12/30` episodes, regret `1.4824`) and `premature_accusation` (`10` steps across `10/30` episodes, regret `8.5591`).
- `opencode:google/gemini-4-carbon`: total regret `5.1424` (`0.1714` per episode), with `budget_waste` in `27/30` episodes (`30` steps), `premature_accusation` in `2/30` episodes (regret `0.8044`), and `no_accusation` in `1/30` episode (seed 11 rational abstention at `P_top=0.2191 < P_breakeven=0.8130`).
- `gemini:gemini-4-carbon` (in-process): total regret `3.8276` (`0.1276` per episode), with `premature_accusation` in `1/30` episode (regret `0.5889`) and `no_accusation` in `1/30` episode (seed 26 rational abstention at `P_top=0.3793 < P_breakeven=0.6849`).

## 3. Top Ranked Showcase Pairs (`rank_showcase_pairs`)

Ranked deterministically by `replay.fooled.rank_showcase_pairs` across all 150 paired real v1.4 runs (prioritizing core fooled modes where the reference solver wins on the identical seed):

| Rank | Pair ID | Kind | Stop (`day`, `t`) | Accused | `P(acc)` | `P_be` | `EV` | Agent Score | Solver (`day`, `acc`, Score) | Score Delta |
|---:|---|---|---|---|---:|---:|---:|---:|---|---:|
| 1 | `v1.4__hard__s21__opencode_google_gemini-3_5-flash__vs__solver` | `premature_wrong` | d14, t57 | `e05` (wrong) | 0.1111 | 0.6667 | -0.8333 | -1.00 | d09, `e14`, +0.73 | -1.73 |
| 2 | `v1.4__hard__s6__gemini_gemini-4-carbon__vs__solver` | `premature_wrong` | d15, t150 | `e18` (wrong) | 0.6295 | 0.6452 | -0.0243 | -1.00 | d06, `e34`, +0.71 | -1.71 |
| 3 | `v1.4__hard__s26__opencode_google_gemini-3_5-flash__vs__solver` | `decoy_chase` | d19, t86 | `e38` (wrong) | 0.1000 | 0.7874 | -0.8730 | -1.00 | d07, `e08`, +0.69 | -1.69 |
| 4 | `v1.4__hard__s18__opencode_google_gemini-4-carbon__vs__solver` | `premature_wrong` | d18, t179 | `e29` (wrong) | 0.6272 | 0.6623 | -0.0529 | -1.00 | d13, `e27`, +0.52 | -1.52 |
| 5 | `v1.4__hard__s10__opencode_google_gemini-3_5-flash__vs__solver` | `premature_wrong` | d20, t97 | `e34` (wrong) | 0.0013 | 0.8130 | -0.9984 | -1.00 | d19, `e10`, +0.21 | -1.21 |
| 6 | `v1.4__hard__s0__opencode_google_gemini-3_5-flash__vs__solver` | `subthreshold_gamble` | d21, t97 | `e38` (hit) | 0.3325 | 0.8696 | -0.6176 | +0.05 | d09, `e38`, +0.64 | -0.59 |
| 7 | `v1.4__hard__s27__opencode_google_gemini-3_5-flash__vs__solver` | `subthreshold_gamble` | d17, t82 | `e33` (hit) | 0.1000 | 0.8000 | -0.8750 | +0.20 | d06, `e33`, +0.72 | -0.52 |
| 8 | `v1.4__hard__s5__gemini_gemini-4-carbon__vs__solver` | `subthreshold_gamble` | d21, t204 | `e27` (hit) | 0.9014 | 0.9091 | -0.0084 | +0.10 | d09, `e27`, +0.52 | -0.42 |
| 9 | `v1.4__hard__s2__opencode_google_gemini-3_5-flash__vs__solver` | `subthreshold_gamble` | d21, t76 | `e25` (hit) | 0.1429 | 0.8065 | -0.8229 | +0.19 | d09, `e25`, +0.58 | -0.39 |
| 10 | `v1.4__hard__s5__opencode_google_gemini-4-carbon__vs__solver` | `subthreshold_gamble` | d21, t194 | `e27` (hit) | 0.5102 | 0.8264 | -0.3826 | +0.16 | d09, `e27`, +0.52 | -0.36 |

## 4. Step-by-Step Belief Trace Case Studies (`compute_belief_trace`)

### Case A: Same Seed (Hard Seed 26) - Decoy Chase vs Disclosed Fingerprint Flip
Hard seed 26 (true mole `e08`, loud innocent decoy `e38`) demonstrates why `replay.fooled` separates behavioral traps from stochastic canary noise:
- **`opencode:google/gemini-3.5-flash` (`decoy_chase`, `fooled=True`):** Early leak-feed and access-log reads elevate decoy `e38` to `P_top=0.3243` on day 7 (`t=39`). Even after subsequent leaks erode `e38` down to `P=0.1000` by day 19 (`t=83`, `V=0.27`, break-even `P=0.7874`), the agent anchors on the loud innocent and calls `accuse(employee="e38")` at step 87 (`t=86`, `EV=-0.8730`, step regret `0.8822`), scoring `-1.00`.
- **`opencode:google/gemini-4-carbon` (`fingerprint_bad_luck`, `fooled=False, bad_luck=True`):** True mole `e08` leads at `P_top=0.4775` at the end of day 9 (`t=87`), when a 5% canary fingerprint flip on day 10 (`t=88`, `check_leak_feed`) jumps `e04` to `P=0.9484` and `P=0.9504` after `read_access_logs` (`t=89`). Accusing `e04` on day 10 (`t=90`, `V=0.67`, `P_breakeven=0.5988`) has positive expected value (`EV=+0.5872`); the `-1.00` outcome is classified as bad luck rather than a fooled failure.
- **Reference `solver`:** Isolates and accuses `e08` on day 7 at `P=0.97`, scoring `+0.69`.

### Case B: Horizon Negative-EV Commitment (`opencode:google/gemini-4-carbon`, Hard Seed 18)
- **Trajectory (`premature_wrong`, `fooled=True`):** Across days 1 to 18, `gemini-4-carbon` spends daily actions on interviews rather than splitting the remaining candidate set (`{e09, e27, e29, e37}`). By day 18 (`t=178`), company value has drained to `V=0.51`, raising the break-even threshold to `P_breakeven=0.6623`. With `e29` at only `P=0.6272` (`EV=-0.0529`), rational abstention (`0.00`) or planting a splitting canary dominates accusing; instead, step 180 (`t=179`) accuses `e29` (step regret `0.4879`, score `-1.00` vs solver `+0.52` on `e27` at day 13, `P=0.96`).

### Case C: Evidence Misread Despite Decisive Posterior (`opencode:google/gemini-3.5-flash`, Hard Seed 10)
- **Trajectory (`premature_wrong`, `fooled=True`):** On day 6 (`t=37`), `e34` briefly leads at `P_top=0.7078` before `read_access_logs` (`t=39`) shifts the lead to true mole `e10` (`P_top=0.6084`). By day 20 (`t=96`), the agent's own tool results concentrate `P=0.9533` on `e10` (well above `P_breakeven=0.8130` at `V=0.23`) and reduce `e34` to `P=0.0013`. At step 98 (`t=97`), the agent nevertheless accuses `e34` (`EV=-0.9984`, step regret `1.2166`, score `-1.00` vs solver `+0.21` accusing `e10` on day 19 at `P=0.94`).

## 5. Complete Catalogue of All 24 Non-Trivial Real v1.4 Episodes (`fooled` or `bad_luck`)

| Tier | Agent | Seed | `kind` | `fooled` | `bad_luck` | Stop (`day`, `t`) | Accused | Correct | `P(acc)` | `P_be` | `EV` | Score | Solver Score |
|---|---|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---:|
| `hard` | `gemini:gemini-4-carbon` | 5 | `subthreshold_gamble` | True | False | d21, t204 | `e27` | True | 0.9014 | 0.9091 | -0.0084 | +0.10 | +0.52 |
| `hard` | `gemini:gemini-4-carbon` | 6 | `premature_wrong` | True | False | d15, t150 | `e18` | False | 0.6295 | 0.6452 | -0.0243 | -1.00 | +0.71 |
| `hard` | `gemini:gemini-4-carbon` | 22 | `subthreshold_gamble` | True | False | d17, t174 | `e36` | True | 0.5605 | 0.6667 | -0.1593 | +0.50 | +0.40 |
| `hard` | `opencode:google/gemini-4-carbon` | 1 | `fingerprint_bad_luck` | False | True | d19, t177 | `e39` | False | 0.9878 | 0.7299 | +0.3534 | -1.00 | +0.69 |
| `hard` | `opencode:google/gemini-4-carbon` | 5 | `subthreshold_gamble` | True | False | d21, t194 | `e27` | True | 0.5102 | 0.8264 | -0.3826 | +0.16 | +0.52 |
| `hard` | `opencode:google/gemini-4-carbon` | 15 | `wrong_accusation` | True | False | d12, t122 | `e34` | False | 0.8049 | 0.5917 | +0.3602 | -1.00 | -1.00 |
| `hard` | `opencode:google/gemini-4-carbon` | 18 | `premature_wrong` | True | False | d18, t179 | `e29` | False | 0.6272 | 0.6623 | -0.0529 | -1.00 | +0.52 |
| `hard` | `opencode:google/gemini-4-carbon` | 23 | `subthreshold_gamble` | True | False | d21, t175 | `e29` | True | 0.4517 | 0.7812 | -0.4218 | +0.23 | +0.32 |
| `hard` | `opencode:google/gemini-4-carbon` | 26 | `fingerprint_bad_luck` | False | True | d10, t90 | `e04` | False | 0.9504 | 0.5988 | +0.5872 | -1.00 | +0.69 |
| `hard` | `opencode:google/gemini-3.5-flash` | 0 | `subthreshold_gamble` | True | False | d21, t97 | `e38` | True | 0.3325 | 0.8696 | -0.6176 | +0.05 | +0.64 |
| `hard` | `opencode:google/gemini-3.5-flash` | 2 | `subthreshold_gamble` | True | False | d21, t76 | `e25` | True | 0.1429 | 0.8065 | -0.8229 | +0.19 | +0.58 |
| `hard` | `opencode:google/gemini-3.5-flash` | 3 | `subthreshold_gamble` | True | False | d08, t46 | `e29` | True | 0.4704 | 0.6250 | -0.2473 | +0.60 | +0.28 |
| `hard` | `opencode:google/gemini-3.5-flash` | 10 | `premature_wrong` | True | False | d20, t97 | `e34` | False | 0.0013 | 0.8130 | -0.9984 | -1.00 | +0.21 |
| `hard` | `opencode:google/gemini-3.5-flash` | 17 | `subthreshold_gamble` | True | False | d19, t84 | `e28` | True | 0.4807 | 0.6623 | -0.2741 | +0.51 | +0.77 |
| `hard` | `opencode:google/gemini-3.5-flash` | 18 | `subthreshold_gamble` | True | False | d16, t63 | `e27` | True | 0.2898 | 0.6410 | -0.5480 | +0.46 | +0.52 |
| `hard` | `opencode:google/gemini-3.5-flash` | 21 | `premature_wrong` | True | False | d14, t57 | `e05` | False | 0.1111 | 0.6667 | -0.8333 | -1.00 | +0.73 |
| `hard` | `opencode:google/gemini-3.5-flash` | 23 | `subthreshold_gamble` | True | False | d17, t71 | `e29` | True | 0.1111 | 0.6289 | -0.8234 | +0.54 | +0.32 |
| `hard` | `opencode:google/gemini-3.5-flash` | 26 | `decoy_chase` | True | False | d19, t86 | `e38` | False | 0.1000 | 0.7874 | -0.8730 | -1.00 | +0.69 |
| `hard` | `opencode:google/gemini-3.5-flash` | 27 | `subthreshold_gamble` | True | False | d17, t82 | `e33` | True | 0.1000 | 0.8000 | -0.8750 | +0.20 | +0.72 |
| `medium` | `opencode:google/gemini-4-carbon` | 7 | `subthreshold_gamble` | True | False | d14, t140 | `e09` | True | 0.6272 | 0.6494 | -0.0341 | +0.50 | +0.82 |
| `medium` | `opencode:google/gemini-4-carbon` | 29 | `subthreshold_gamble` | True | False | d14, t142 | `e00` | True | 0.5585 | 0.6623 | -0.1567 | +0.47 | +0.00 |
| `medium` | `gemini:gemini-4-carbon` | 2 | `subthreshold_gamble` | True | False | d08, t84 | `e09` | True | 0.5138 | 0.5556 | -0.0752 | +0.80 | +0.80 |
| `medium` | `gemini:gemini-4-carbon` | 11 | `subthreshold_gamble` | True | False | d14, t140 | `e07` | True | 0.4264 | 0.6410 | -0.3348 | +0.52 | +0.84 |
| `medium` | `gemini:gemini-4-carbon` | 18 | `premature_wrong` | True | False | d14, t139 | `e10` | False | 0.5539 | 0.6452 | -0.1414 | -1.00 | +0.75 |
