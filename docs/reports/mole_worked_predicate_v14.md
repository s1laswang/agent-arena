# Sleeper Winnable and Worked Predicate Port for Canary v1.4 Mole Strategies

Generated strictly offline (`api_calls=0`) via `python -m canary.mole.worked_predicate --tier hard --seeds 6240-6279 --workers 2`.

## 1. Predicate Definitions and Anti-Unfairness Invariant

This report ports Sleeper's per-seed `atk-regret-winnable` and `atk-regret-worked` predicates to Canary v1.4 `hard` so mole strategy difficulty is never credited on unwinnable or shortcut-solvable seeds:

- **Live `winnable(tier, seed, strategy)`**: `True` iff `SolverPolicy(tier)` accuses the true mole cleanly (`correct == True` and `score > 0.0`) AND all three anti-shortcut baselines fail (`DoNothing == 0.0`, `StopEarlyQuit == 0.0` both finished and mid-episode, and `LogsOnly` is incorrect).
- **Live `worked(tier, seed, strategy, investigator)`**: `True` iff `winnable == True` AND the target investigator (`GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`, `HintedHeuristic`) either fails (`correct == False`) or suffers paired regret `solver_score - inv_score >= 0.25`.
- **Counterfactual `cf_worked(strategy, source, seed)`**: Over the `60` committed v1.4 `gemini-4-carbon` Hard transcripts (`opencode, inproc` on seeds `0-29`) paired with the `30` committed `data/runs/committed/v1.4/reference/solver-hard` episodes, `cf_worked == True` iff committed `solver` solved `seed` (`correct == True`, `score > 0`) AND replacing `default_v0` with `strategy` drops counterfactual `P(true mole)` at Gemini's accusation day from `>= 1 / (1 + V_accuse)` below break-even `1 / (1 + V_accuse)` (or drops `optimal_ev` by `>= 0.20` from a break-even-justified `default_v0` baseline).
- **Hard Anti-Unfairness Invariant**: Whenever `winnable == False` (or `cf_winnable == False`), `worked` (`cf_worked`) is strictly `False`, even if the target investigator failed.

## 2. Evaluation Design and Gate Summary

- **Disjoint live seed slice**: `hard` seeds `6240-6279` (`n=40`, strict hygiene guard rejecting `0-59`, `30000-30199`, `800000+`, `900000+`, `0` live API calls).
- **Bootstrap protocol**: `5000` paired resamples (`seed=20261114`, `95%` percentile CIs).
- **Candidate set**: `11` entries (`default_v0` + `6` transcript-grounded strategies from `canary.mole.strategies` + `4` `data/forge/hall_of_fame_v1.4.jsonl` rows; `9` distinct canonical DSL strategies because `hof_v14_rank3` == `surgical_trap_shield` and `hof_v14_rank4` == `early_burst_midgame_pace`).
- **Gates**: `all_strategies_passed=True`, `anti_unfairness_invariant_all_ok=True`, `min_solver_acc=0.825` (`>= 0.800`), `max_logs_only_acc=0.000` (`<= 0.100`).
- **Unwinnable-credit suppression**: `24` naive investigator-beaten cells suppressed on live seeds `6240-6279`, and `5` counterfactual transcript credits suppressed on committed solver-failed seed(s) (`15`).

## 3. Live Winnable and Composite Worked Rates (`n=40` Disjoint Hard Seeds)

| Strategy | Cohort | Winnable Rate [95% CI] | Solver Acc (Mean Score) | LogsOnly Acc | 4-Inv Worked Rate [95% CI] | 4-Inv Worked Delta vs Default [95% CI] | Frontier 2-Proxy Worked [95% CI] | All-4 Worked | Suppressed Credits | Gates |
|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.950 [0.875, 1.000] | 0.950 (+0.576) | 0.000 | 0.375 [0.306, 0.444] | +0.000 [+0.000, +0.000] | 0.300 [0.200, 0.412] | 0.000 | 0 | PASS |
| `surgical_trap_shield` | `transcript_grounded` | 0.975 [0.925, 1.000] | 0.975 (+0.554) | 0.000 | 0.381 [0.300, 0.463] | +0.006 [-0.100, +0.113] | 0.375 [0.275, 0.475] | 0.050 | 1 | PASS |
| `gemini_midsize_shield` | `transcript_grounded` | 0.950 [0.875, 1.000] | 0.950 (+0.513) | 0.000 | 0.431 [0.344, 0.525] | +0.056 [-0.056, +0.175] | 0.412 [0.300, 0.525] | 0.075 | 2 | PASS |
| `reactive_canary_lag` | `transcript_grounded` | 0.875 [0.775, 0.975] | 0.875 (+0.378) | 0.000 | 0.325 [0.237, 0.419] | -0.050 [-0.163, +0.063] | 0.287 [0.188, 0.388] | 0.075 | 3 | PASS |
| `non_decoy_tiebreak_framer` | `transcript_grounded` | 0.825 [0.700, 0.925] | 0.825 (+0.418) | 0.000 | 0.325 [0.244, 0.412] | -0.050 [-0.156, +0.056] | 0.275 [0.188, 0.362] | 0.000 | 6 | PASS |
| `early_burst_midgame_pace` | `transcript_grounded` | 0.900 [0.800, 0.975] | 0.900 (+0.512) | 0.000 | 0.406 [0.319, 0.500] | +0.031 [-0.075, +0.138] | 0.388 [0.275, 0.500] | 0.075 | 1 | PASS |
| `frontier_synthesis_v14` | `transcript_grounded` | 0.900 [0.800, 0.975] | 0.900 (+0.403) | 0.000 | 0.325 [0.250, 0.400] | -0.050 [-0.150, +0.056] | 0.287 [0.188, 0.400] | 0.000 | 5 | PASS |
| `hof_v14_rank1` | `hof_v14` | 0.975 [0.925, 1.000] | 0.975 (+0.676) | 0.000 | 0.525 [0.444, 0.606] | +0.150 [+0.062, +0.237] | 0.325 [0.212, 0.438] | 0.100 | 2 | PASS |
| `hof_v14_rank2` | `hof_v14` | 0.975 [0.925, 1.000] | 0.975 (+0.673) | 0.000 | 0.606 [0.531, 0.681] | +0.231 [+0.156, +0.306] | 0.388 [0.275, 0.512] | 0.125 | 2 | PASS |
| `hof_v14_rank3` | `hof_v14 (=surgical_trap_shield)` | 0.975 [0.925, 1.000] | 0.975 (+0.554) | 0.000 | 0.381 [0.300, 0.463] | +0.006 [-0.100, +0.119] | 0.375 [0.275, 0.475] | 0.050 | 1 | PASS |
| `hof_v14_rank4` | `hof_v14 (=early_burst_midgame_pace)` | 0.900 [0.800, 0.975] | 0.900 (+0.512) | 0.000 | 0.406 [0.319, 0.494] | +0.031 [-0.075, +0.138] | 0.388 [0.275, 0.500] | 0.075 | 1 | PASS |

## 4. Per-Investigator Live Worked Rates and Paired Deltas vs `default_v0`

| Strategy | GeminiCarbonProxy Worked (Delta) | CodexHorizonProxy Worked (Delta) | GrokTactics Worked (Delta) | HintedHeuristic Worked (Delta) | Minimax 4-Inv Worked | Hardest Investigator |
|---|---|---|---|---|---|---|
| `default_v0` | 0.350 (+0.000) | 0.250 (+0.000) | 0.475 (+0.000) | 0.425 (+0.000) | 0.250 | `codex_horizon_proxy` |
| `surgical_trap_shield` | 0.425 (+0.075) | 0.325 (+0.075) | 0.450 (-0.025) | 0.325 (-0.100) | 0.325 | `codex_horizon_proxy` |
| `gemini_midsize_shield` | 0.525 (+0.175) | 0.300 (+0.050) | 0.575 (+0.100) | 0.325 (-0.100) | 0.300 | `codex_horizon_proxy` |
| `reactive_canary_lag` | 0.350 (+0.000) | 0.225 (-0.025) | 0.350 (-0.125) | 0.375 (-0.050) | 0.225 | `codex_horizon_proxy` |
| `non_decoy_tiebreak_framer` | 0.375 (+0.025) | 0.175 (-0.075) | 0.450 (-0.025) | 0.300 (-0.125) | 0.175 | `codex_horizon_proxy` |
| `early_burst_midgame_pace` | 0.400 (+0.050) | 0.375 (+0.125) | 0.450 (-0.025) | 0.400 (-0.025) | 0.375 | `codex_horizon_proxy` |
| `frontier_synthesis_v14` | 0.300 (-0.050) | 0.275 (+0.025) | 0.450 (-0.025) | 0.275 (-0.150) | 0.275 | `codex_horizon_proxy` |
| `hof_v14_rank1` | 0.425 (+0.075) | 0.225 (-0.025) | 0.825 (+0.350) | 0.625 (+0.200) | 0.225 | `codex_horizon_proxy` |
| `hof_v14_rank2` | 0.475 (+0.125) | 0.300 (+0.050) | 0.975 (+0.500) | 0.675 (+0.250) | 0.300 | `codex_horizon_proxy` |
| `hof_v14_rank3` | 0.425 (+0.075) | 0.325 (+0.075) | 0.450 (-0.025) | 0.325 (-0.100) | 0.325 | `codex_horizon_proxy` |
| `hof_v14_rank4` | 0.400 (+0.050) | 0.375 (+0.125) | 0.450 (-0.025) | 0.400 (-0.025) | 0.375 | `codex_horizon_proxy` |

### 4.1 Failure vs Regret-Only Decomposition and Unwinnable Credit Suppression

Each `worked == True` event decomposes into investigator wrong/abstained accusation (`correct == False`) versus accurate but high-cost catch (`correct == True` with `solver_score - inv_score >= 0.25`). Naive `raw_beaten - worked` equals suppressed unwinnable credits.

| Strategy | Investigator | Raw Beaten | Worked (`winnable & beaten`) | Suppressed (`!winnable & beaten`) | Worked via `correct==False` | Worked via `regret>=0.25` Only | Mean Paired Regret [95% CI] |
|---|---|---|---|---|---|---|---|
| `default_v0` | `GeminiCarbonProxy` | 14/40 (0.350) | 14/40 (0.350) | 0 | 1 | 13 | +0.092 [-0.034, +0.201] |
| `default_v0` | `CodexHorizonProxy` | 10/40 (0.250) | 10/40 (0.250) | 0 | 7 | 3 | +0.260 [+0.051, +0.488] |
| `default_v0` | `GrokTactics` | 19/40 (0.475) | 19/40 (0.475) | 0 | 4 | 15 | +0.240 [+0.093, +0.402] |
| `default_v0` | `HintedHeuristic` | 17/40 (0.425) | 17/40 (0.425) | 0 | 4 | 13 | +0.162 [+0.044, +0.258] |
| `surgical_trap_shield` | `GeminiCarbonProxy` | 18/40 (0.450) | 17/40 (0.425) | 1 | 7 | 10 | +0.232 [+0.061, +0.412] |
| `surgical_trap_shield` | `CodexHorizonProxy` | 13/40 (0.325) | 13/40 (0.325) | 0 | 8 | 5 | +0.282 [+0.074, +0.492] |
| `surgical_trap_shield` | `GrokTactics` | 18/40 (0.450) | 18/40 (0.450) | 0 | 8 | 10 | +0.236 [+0.052, +0.421] |
| `surgical_trap_shield` | `HintedHeuristic` | 13/40 (0.325) | 13/40 (0.325) | 0 | 5 | 8 | +0.171 [+0.024, +0.327] |
| `gemini_midsize_shield` | `GeminiCarbonProxy` | 21/40 (0.525) | 21/40 (0.525) | 0 | 10 | 11 | +0.286 [+0.120, +0.455] |
| `gemini_midsize_shield` | `CodexHorizonProxy` | 13/40 (0.325) | 12/40 (0.300) | 1 | 9 | 3 | +0.369 [+0.165, +0.578] |
| `gemini_midsize_shield` | `GrokTactics` | 23/40 (0.575) | 23/40 (0.575) | 0 | 10 | 13 | +0.292 [+0.123, +0.457] |
| `gemini_midsize_shield` | `HintedHeuristic` | 14/40 (0.350) | 13/40 (0.325) | 1 | 4 | 9 | +0.154 [+0.006, +0.297] |
| `reactive_canary_lag` | `GeminiCarbonProxy` | 15/40 (0.375) | 14/40 (0.350) | 1 | 6 | 8 | +0.069 [-0.146, +0.276] |
| `reactive_canary_lag` | `CodexHorizonProxy` | 9/40 (0.225) | 9/40 (0.225) | 0 | 7 | 2 | +0.110 [-0.153, +0.358] |
| `reactive_canary_lag` | `GrokTactics` | 16/40 (0.400) | 14/40 (0.350) | 2 | 10 | 4 | +0.116 [-0.070, +0.295] |
| `reactive_canary_lag` | `HintedHeuristic` | 15/40 (0.375) | 15/40 (0.375) | 0 | 8 | 7 | +0.045 [-0.135, +0.215] |
| `non_decoy_tiebreak_framer` | `GeminiCarbonProxy` | 17/40 (0.425) | 15/40 (0.375) | 2 | 8 | 7 | +0.128 [-0.066, +0.307] |
| `non_decoy_tiebreak_framer` | `CodexHorizonProxy` | 9/40 (0.225) | 7/40 (0.175) | 2 | 3 | 4 | +0.097 [-0.112, +0.306] |
| `non_decoy_tiebreak_framer` | `GrokTactics` | 19/40 (0.475) | 18/40 (0.450) | 1 | 7 | 11 | +0.176 [-0.052, +0.404] |
| `non_decoy_tiebreak_framer` | `HintedHeuristic` | 13/40 (0.325) | 12/40 (0.300) | 1 | 6 | 6 | +0.040 [-0.173, +0.241] |
| `early_burst_midgame_pace` | `GeminiCarbonProxy` | 16/40 (0.400) | 16/40 (0.400) | 0 | 7 | 9 | +0.203 [-0.013, +0.422] |
| `early_burst_midgame_pace` | `CodexHorizonProxy` | 15/40 (0.375) | 15/40 (0.375) | 0 | 11 | 4 | +0.359 [+0.087, +0.643] |
| `early_burst_midgame_pace` | `GrokTactics` | 19/40 (0.475) | 18/40 (0.450) | 1 | 5 | 13 | +0.108 [-0.076, +0.281] |
| `early_burst_midgame_pace` | `HintedHeuristic` | 16/40 (0.400) | 16/40 (0.400) | 0 | 7 | 9 | +0.150 [-0.043, +0.339] |
| `frontier_synthesis_v14` | `GeminiCarbonProxy` | 14/40 (0.350) | 12/40 (0.300) | 2 | 7 | 5 | +0.091 [-0.108, +0.288] |
| `frontier_synthesis_v14` | `CodexHorizonProxy` | 11/40 (0.275) | 11/40 (0.275) | 0 | 9 | 2 | +0.205 [-0.056, +0.478] |
| `frontier_synthesis_v14` | `GrokTactics` | 20/40 (0.500) | 18/40 (0.450) | 2 | 11 | 7 | +0.186 [-0.008, +0.367] |
| `frontier_synthesis_v14` | `HintedHeuristic` | 12/40 (0.300) | 11/40 (0.275) | 1 | 4 | 7 | +0.004 [-0.147, +0.134] |
| `hof_v14_rank1` | `GeminiCarbonProxy` | 17/40 (0.425) | 17/40 (0.425) | 0 | 15 | 2 | +0.308 [+0.137, +0.488] |
| `hof_v14_rank1` | `CodexHorizonProxy` | 9/40 (0.225) | 9/40 (0.225) | 0 | 8 | 1 | +0.325 [+0.118, +0.550] |
| `hof_v14_rank1` | `GrokTactics` | 34/40 (0.850) | 33/40 (0.825) | 1 | 24 | 9 | +0.573 [+0.471, +0.677] |
| `hof_v14_rank1` | `HintedHeuristic` | 26/40 (0.650) | 25/40 (0.625) | 1 | 23 | 2 | +0.479 [+0.353, +0.616] |
| `hof_v14_rank2` | `GeminiCarbonProxy` | 19/40 (0.475) | 19/40 (0.475) | 0 | 19 | 0 | +0.451 [+0.236, +0.674] |
| `hof_v14_rank2` | `CodexHorizonProxy` | 12/40 (0.300) | 12/40 (0.300) | 0 | 11 | 1 | +0.443 [+0.197, +0.695] |
| `hof_v14_rank2` | `GrokTactics` | 40/40 (1.000) | 39/40 (0.975) | 1 | 39 | 0 | +0.673 [+0.625, +0.710] |
| `hof_v14_rank2` | `HintedHeuristic` | 28/40 (0.700) | 27/40 (0.675) | 1 | 26 | 1 | +0.497 [+0.385, +0.612] |
| `hof_v14_rank3` | `GeminiCarbonProxy` | 18/40 (0.450) | 17/40 (0.425) | 1 | 7 | 10 | +0.232 [+0.057, +0.422] |
| `hof_v14_rank3` | `CodexHorizonProxy` | 13/40 (0.325) | 13/40 (0.325) | 0 | 8 | 5 | +0.282 [+0.076, +0.499] |
| `hof_v14_rank3` | `GrokTactics` | 18/40 (0.450) | 18/40 (0.450) | 0 | 8 | 10 | +0.236 [+0.050, +0.417] |
| `hof_v14_rank3` | `HintedHeuristic` | 13/40 (0.325) | 13/40 (0.325) | 0 | 5 | 8 | +0.171 [+0.019, +0.323] |
| `hof_v14_rank4` | `GeminiCarbonProxy` | 16/40 (0.400) | 16/40 (0.400) | 0 | 7 | 9 | +0.203 [-0.013, +0.415] |
| `hof_v14_rank4` | `CodexHorizonProxy` | 15/40 (0.375) | 15/40 (0.375) | 0 | 11 | 4 | +0.359 [+0.071, +0.658] |
| `hof_v14_rank4` | `GrokTactics` | 19/40 (0.475) | 18/40 (0.450) | 1 | 5 | 13 | +0.108 [-0.073, +0.276] |
| `hof_v14_rank4` | `HintedHeuristic` | 16/40 (0.400) | 16/40 (0.400) | 0 | 7 | 9 | +0.150 [-0.050, +0.335] |

## 5. Counterfactual Worked Predicate on `60` Committed v1.4 `gemini-4-carbon` Hard Transcripts

Across the `60` committed v1.4 Hard transcripts (`opencode + inproc` seeds `0-29`), committed `SolverPolicy` solved `29/30` seeds (`58/60` transcripts `cf_winnable == True`; failed seed(s) `15` in committed `solver-hard` are gated to `cf_worked = False` across harnesses).

| Strategy | CF Worked (`n/60`) [95% CI] | CF Worked Given Winnable (`n/58`) | CF Worked Given Base >= Break-Even (`n/48`) | OpenCode (`n/30`) | In-Proc (`n/30`) | Dropped `< P*(V)` | Dropped `EV >= 0.20` | Suppressed (`!cf_winnable`) | Mean `P(mole)` Drop [95% CI] | Mean `optimal_ev` Drop [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | 0/60 0.000 [0.000, 0.000] | 0/58 (0.000) | 0.000 | 0/30 (0.000) | 0/30 (0.000) | 0 | 0 | 0 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `surgical_trap_shield` | 25/60 0.417 [0.300, 0.550] | 25/58 (0.431) | 0.521 | 11/30 (0.367) | 14/30 (0.467) | 16 | 25 | 1 | +0.128 [+0.014, +0.246] | +0.160 [+0.074, +0.246] |
| `gemini_midsize_shield` | 28/60 0.467 [0.350, 0.600] | 28/58 (0.483) | 0.583 | 14/30 (0.467) | 14/30 (0.467) | 21 | 27 | 1 | +0.202 [+0.085, +0.321] | +0.203 [+0.117, +0.286] |
| `reactive_canary_lag` | 33/60 0.550 [0.433, 0.667] | 33/58 (0.569) | 0.688 | 13/30 (0.433) | 20/30 (0.667) | 28 | 31 | 1 | +0.283 [+0.170, +0.397] | +0.269 [+0.189, +0.345] |
| `non_decoy_tiebreak_framer` | 25/60 0.417 [0.300, 0.550] | 25/58 (0.431) | 0.521 | 11/30 (0.367) | 14/30 (0.467) | 19 | 24 | 0 | +0.165 [+0.037, +0.289] | +0.159 [+0.071, +0.242] |
| `early_burst_midgame_pace` | 28/60 0.467 [0.333, 0.600] | 28/58 (0.483) | 0.583 | 12/30 (0.400) | 16/30 (0.533) | 24 | 25 | 0 | +0.230 [+0.113, +0.346] | +0.183 [+0.098, +0.269] |
| `frontier_synthesis_v14` | 36/60 0.600 [0.467, 0.717] | 36/58 (0.621) | 0.750 | 16/30 (0.533) | 20/30 (0.667) | 31 | 35 | 1 | +0.327 [+0.211, +0.436] | +0.299 [+0.220, +0.378] |
| `hof_v14_rank1` | 16/60 0.267 [0.167, 0.383] | 16/58 (0.276) | 0.333 | 7/30 (0.233) | 9/30 (0.300) | 12 | 16 | 0 | +0.076 [-0.040, +0.196] | +0.041 [-0.053, +0.137] |
| `hof_v14_rank2` | 14/60 0.233 [0.133, 0.350] | 14/58 (0.241) | 0.292 | 6/30 (0.200) | 8/30 (0.267) | 11 | 14 | 0 | +0.055 [-0.062, +0.171] | +0.013 [-0.082, +0.111] |
| `hof_v14_rank3` | 25/60 0.417 [0.300, 0.550] | 25/58 (0.431) | 0.521 | 11/30 (0.367) | 14/30 (0.467) | 16 | 25 | 1 | +0.128 [+0.010, +0.245] | +0.160 [+0.074, +0.247] |
| `hof_v14_rank4` | 28/60 0.467 [0.350, 0.600] | 28/58 (0.483) | 0.583 | 12/30 (0.400) | 16/30 (0.533) | 24 | 25 | 0 | +0.230 [+0.109, +0.346] | +0.183 [+0.094, +0.271] |

## 6. Cohort Comparison: Transcript-Grounded vs Forge Hall-of-Fame v1.4

| Cohort | Strategies | Mean Live Winnable Rate | Mean 4-Inv Live Worked Rate | Mean Frontier 2-Proxy Live Worked Rate | Mean Counterfactual `cf_worked` Rate (`n=60` Gemini-4-Carbon Hard Transcripts) |
|---|---|---|---|---|---|
| `transcript_grounded_6` | `surgical_trap_shield, gemini_midsize_shield, reactive_canary_lag, non_decoy_tiebreak_framer, early_burst_midgame_pace, frontier_synthesis_v14` | 0.904 | 0.366 | 0.338 | 0.486 |
| `hof_v14_all_4` | `hof_v14_rank1, hof_v14_rank2, hof_v14_rank3, hof_v14_rank4` | 0.956 | 0.480 | 0.369 | 0.346 |
| `hof_v14_pure_forge_2` | `hof_v14_rank1, hof_v14_rank2` | 0.975 | 0.566 | 0.356 | 0.250 |

## 7. Provenance Hashes and Unwinnable Seed Audit

| Strategy | Rules | Hof Alias | Canonical SHA-256 | Behavior Hash | Live Unwinnable Seeds (`6240-6279`) |
|---|---|---|---|---|---|
| `default_v0` | 0 | none | `6ac100ee503ef397` | `4ce97ce85124050ce478649ec860136b` | `6258(solver_not_correct), 6269(solver_not_correct)` |
| `surgical_trap_shield` | 3 | none | `6c5aad23b6c3ab42` | `e55c0473d2685c858c818e49bab106a1` | `6251(solver_not_correct)` |
| `gemini_midsize_shield` | 2 | none | `1aa3fd14173717b6` | `6153914e768647835177cd6099e312c8` | `6243(solver_not_correct), 6261(solver_not_correct)` |
| `reactive_canary_lag` | 2 | none | `7a7778e4d65e5681` | `637c34ad367fd384918bcbeb2fa2b16a` | `6244(solver_not_correct), 6251(solver_not_correct), 6253(solver_not_correct), 6255(solver_not_correct), 6268(solver_not_correct)` |
| `non_decoy_tiebreak_framer` | 3 | none | `516eb15259285eae` | `eb452649e501ad9f571a7a049b65cf6a` | `6247(solver_not_correct), 6256(solver_not_correct), 6261(solver_not_correct), 6262(solver_not_correct), 6266(solver_not_correct), 6267(solver_not_correct), 6275(solver_not_correct)` |
| `early_burst_midgame_pace` | 3 | none | `caca2566113c08bd` | `3635b8fc202b2fef5a1846f25f4c0629` | `6242(solver_not_correct), 6258(solver_not_correct), 6262(solver_not_correct), 6275(solver_not_correct)` |
| `frontier_synthesis_v14` | 4 | none | `0e890e18d1c8aea7` | `eec9419bd531541cef0d1bfb6879576e` | `6244(solver_not_correct), 6251(solver_not_correct), 6253(solver_not_correct), 6256(solver_not_correct)` |
| `hof_v14_rank1` | 5 | `window_crowd_stale` | `cee95e6c0c5ff5cf` | `1fa0458fbea558cbba4b8088f9d862a8` | `6247(solver_not_correct)` |
| `hof_v14_rank2` | 5 | `two_wave_blackout` | `37a1180b0bf92ea4` | `ca7182e045d39a76fe1cfe8b905dbabf` | `6247(solver_not_correct)` |
| `hof_v14_rank3` | 3 | `surgical_trap_shield` | `f1beeca251a863b8` | `e55c0473d2685c858c818e49bab106a1` | `6251(solver_not_correct)` |
| `hof_v14_rank4` | 3 | `early_burst_midgame_pace` | `b7e4d7560adeed1c` | `3635b8fc202b2fef5a1846f25f4c0629` | `6242(solver_not_correct), 6258(solver_not_correct), 6262(solver_not_correct), 6275(solver_not_correct)` |
