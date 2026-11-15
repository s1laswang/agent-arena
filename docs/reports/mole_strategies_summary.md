# Mole Strategies & Social Deception: Executive Submission Summary

Deterministic offline verification summary (`TIERS_VERSION=v1.4`, `tier=hard`, `live_api_calls=0`) across Canary's transcript-grounded Mole DSL strategies, Forge v1.4 Hall-of-Fame survivors, 12-arm lever ablation study, cross-model strategy transfer (`99/99` transcripts, `11/11` gates), Sleeper minimax attack-regret portfolio (`canary.mole.regret_portfolio`), and V1.6 social-chatter fairness and partial checkpoint audit.

Reproduce or verify exact deterministic byte parity with zero API keys:
```bash
GOOGLE_API_KEY="" GEMINI_API_KEY="" OPENAI_API_KEY="" PYTHONPATH=. python scripts/verify_mole_strategies_gate.py --check
```

## 1. Six-Gate Submission Verification Summary

| Gate | Scope & Verification Target | Key Measured Result | Verdict |
|---|---|---|---|
| `(a)` Protected-Path Guard | `.github/protected-paths.txt` (15 protected prefixes vs `origin/justSilas`) | `0` protected-path modifications | PASS |
| `(b)` Catalogs, Seed Hygiene, 200-Seed Eval & Live Spot-Check | `6` `canary.mole.strategies` + `4` `hall_of_fame_v1.4.jsonl` rows; `6000-6199` (`n=200`) + live `6900-6903` (`n=4`) | 100% DSL round-trip, `6/6` + `4/4` unique 64-view `behavior_hash` (`8` distinct across catalogs); 200-seed min `solver_acc=0.940` (`>=0.85`), max `logs_only_acc=0.015` (`<=0.10`), `DoNothing=0.0`, `StopEarlyQuit=0.0`; live spot-check: `early_burst_midgame_pace` (`acc=0.750`, `mean=+0.395`), `hof_rank1_window_crowd_stale` (`acc=1.000`, `mean=+0.708`) | PASS |
| `(c)` Counterfactual Frontier Replay | Live `canary.mole.counterfactual` on v1.4 Gemini Hard `opencode` seeds `0-9` (`n=10`) + committed 60-transcript v1.4 Hard cohort (`30` `opencode` + `30` `inproc`) | `opencode` `0-9`: `P(true mole)` `0.777 -> 0.689` (drop `+0.088`), optimal EV `0.382 -> 0.246` (drop `+0.136`); full `60` transcripts: `P(true mole)` `0.819 -> 0.492` (drop `+0.327`), optimal EV `0.439 -> 0.140` (drop `+0.299`) | PASS |
| `(d)` 12-Arm Lever Ablation & V1.6 Replay Audit | `results/mole_strategies/lever_ablation_v14.json` (`6600-6639`, `n=40`) + `results/v16_social/partial/` (`4` files) | `12/12` ablation arms pass gates (min `solver_acc=0.925`, max `logs_only_acc=0.000`); `10/10` V1.6 checkpoints replay-verified bit-for-bit (`0` mismatches) | PASS |
| `(e)` Cross-Model Transfer & Sleeper Regret Portfolio | `results/mole_strategies/cross_model_transfer.json` + `docs/reports/mole_regret_portfolio_v14.md` (`canary.mole.regret_portfolio`) | `11/11` transfer gates passed (`6200-6229`, `n=30`, min `solver_acc=0.900`), `99/99` transcripts verified (`99/99` baseline audit parity); `PortfolioMolePolicy` (`0.8657` `surgical_trap_shield` + `0.1343` `gemini_midsize_shield`, `duality_gap=2.22e-16`) train `min_regret=0.2090` (`+0.0132` vs `default_v0`), live val `6812-6823` (`n=12`) `solver_acc=1.000`, `logs_only_acc=0.000` | PASS |
| `(f)` Offline & Hygiene Discipline | Zero API keys, zero em/en dashes, zero secret or employee-ID leaks, honest V1.6 Gate B reporting | `live_api_calls=0`, `blocked_api_attempts=0` | PASS |

## 2. Empirical Frontier Failure Modes Driving Fair Mole Levers

All mole strategies operate strictly inside `canary.mole.dsl.MoleView` (public-free features only: the mole never sees canary labels, investigator tool calls, or posterior beliefs) and remain consistently solvable by `SolverPolicy("hard")` (`>= 0.85` accuracy on 200 fresh seeds):

- **100.0% angry-decoy dismissal vs non-decoy peer framing**: Across `159` primary v1.4/v1.3 frontier episodes, frontier investigators accused the angry decoy `0` times (`100.0%` dismissal), whereas non-decoy after-hours log framing broke `0`-separation canary ties into `-1.0` wrong accusations in `5/10` total frontier wrong accusations.
- **Architectural split in canary recipient sizing**: Codex and GPT-5.5 place `30.6%` (Hard) to `75.3%` (Medium) of planted canaries into `<=3`-recipient surgical traps, while `gemini-4-carbon` places `0.0%` to `0.6%` in `<=3` recipients and concentrates `43.6%` to `73.6%` in `4-8`-recipient 3-variant partitions.
- **Delayed Day-1 canary start and single-canary fragility**: On v1.4 Hard, `gemini-4-carbon` delays its first canary to mean day `3.03` (OpenCode) and `3.40` (in-proc) vs `SolverPolicy` day `1.00`, spends `57.27` to `68.03` calls per episode (`64.4%` to `68.0%` of investigative budget) on low-LR `interview` calls, and commits `7/10` Hard wrong accusations with `<=1` separating canary under `0.95` fingerprint accuracy.

## 3. Transcript-Grounded Strategies on 200 Fresh Hard Seeds (`6000-6199`) & 60 Real Transcripts

Seed hygiene is enforced across every evaluation slice (`0-59`, `30000-30199`, `800000+`, and `900000+` strictly forbidden across `6000-6199`, `6200-6229`, `6600-6639`, `6812-6823`, and `6900-6903`).

| Strategy | Rules | BHash | Solver Acc | Solver Score +/- CI | LogsOnly Acc | Min Regret | GeminiProxy Regret (Gain) | CF P(mole) (Drop) | CF Opt EV (Drop) | Gate |
|---|---|---|---:|---|---:|---:|---|---|---|---:|
| `DEFAULT_STRATEGY (default_v0)` | 0 | `4ce97ce8` | 0.970 | +0.544 +/- 0.041 | 0.020 | 0.196 | 0.196 (+0.000) | 0.819 (+0.000) | 0.439 (+0.000) | PASS |
| `surgical_trap_shield` | 3 | `e55c0473` | 0.970 | +0.573 +/- 0.043 | 0.015 | 0.195 | 0.195 (-0.001) | 0.691 (+0.128) | 0.279 (+0.160) | PASS |
| `gemini_midsize_shield` | 2 | `6153914e` | 0.960 | +0.544 +/- 0.038 | 0.015 | 0.199 | 0.297 (+0.101) | 0.617 (+0.202) | 0.235 (+0.203) | PASS |
| `reactive_canary_lag` | 2 | `637c34ad` | 0.945 | +0.515 +/- 0.042 | 0.015 | 0.163 | 0.223 (+0.027) | 0.536 (+0.283) | 0.170 (+0.269) | PASS |
| `non_decoy_tiebreak_framer` | 3 | `eb452649` | 0.940 | +0.500 +/- 0.051 | 0.010 | 0.114 | 0.114 (-0.082) | 0.654 (+0.165) | 0.280 (+0.159) | PASS |
| `early_burst_midgame_pace` | 3 | `3635b8fc` | 0.970 | +0.572 +/- 0.041 | 0.005 | 0.199 | 0.214 (+0.018) | 0.589 (+0.230) | 0.256 (+0.183) | PASS |
| `frontier_synthesis_v14` | 4 | `eec9419b` | 0.945 | +0.516 +/- 0.042 | 0.015 | 0.182 | 0.223 (+0.027) | 0.492 (+0.327) | 0.140 (+0.299) | PASS |

## 4. Forge v1.4 Hall-of-Fame Survivors (`6200-6219`) & Live Fresh Spot-Check (`6900-6903`)

| HoF Rank | Survivor Name | Rules | BHash | Held-Out Solver Acc | Held-Out Solver Score | Held-Out Min Regret | GeminiProxy Regret | CodexProxy Regret | DSL Round-Trip |
|---:|---|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `window_crowd_stale` | 5 | `1fa0458f` | 1.000 | +0.730 | 0.364 | 0.511 | 0.364 | PASS |
| 2 | `two_wave_blackout` | 5 | `ca7182e0` | 1.000 | +0.726 | 0.347 | 0.399 | 0.347 | PASS |
| 3 | `surgical_trap_shield` | 3 | `e55c0473` | 1.000 | +0.614 | 0.271 | 0.286 | 0.390 | PASS |
| 4 | `early_burst_midgame_pace` | 3 | `3635b8fc` | 1.000 | +0.637 | 0.247 | 0.471 | 0.374 | PASS |

### 4.1 Live 4-Seed Gate Spot-Check (`hard`, Seeds `6900-6903`)

| Spot-Check Strategy | Seeds | BHash | Solver Acc (Min 0.75) | Solver Mean Score | DoNothing Max Abs | StopEarlyQuit Max Abs | Unfinished Quit | Gate |
|---|---|---|---:|---:|---:|---:|---:|---|
| `early_burst_midgame_pace` | `6900-6903` | `3635b8fc` | 0.750 | +0.395 | 0.000 | 0.000 | 0.000 | PASS |
| `hof_rank1_window_crowd_stale` | `6900-6903` | `1fa0458f` | 1.000 | +0.708 | 0.000 | 0.000 | 0.000 | PASS |

## 5. 12-Arm `frontier_synthesis_v14` Lever Ablation (`6600-6639`, `n=40` Live + `60` Transcripts)

All `12/12` single-lever, leave-one-out, decoy-control, and composite arms pass every catchability and anti-shortcut gate (`min_solver_acc=0.925`, `max_logs_only_acc=0.000`, `DoNothing=0.000`, `StopEarlyQuit=0.000`). Replacing dismissed angry-decoy framing with non-decoy peer framing increases frontier proxy regret by `+0.150` (composite) and `+0.169` (single-lever, Codex proxy score delta `-0.364`) while adding `+0.086` counterfactual EV drop in synthesis.

| Arm | Kind | Rules | Framing | Solver Acc | Solver Score | Frontier Regret | LogsOnly Acc | CF P(mole) Drop | CF EV Drop | Surf Canaries | Gate |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| `default_v0` | `baseline` | 0 | `none` | 0.975 | +0.556 | +0.223 | 0.000 | +0.000 | +0.000 | 1.73 | PASS |
| `only_surgical_shield` | `single_lever` | 1 | `none` | 0.975 | +0.547 | +0.214 | 0.000 | +0.000 | +0.000 | 1.73 | PASS |
| `only_reactive_oldest` | `single_lever` | 1 | `none` | 0.975 | +0.556 | +0.267 | 0.000 | +0.224 | +0.206 | 1.45 | PASS |
| `only_midgame_pacing` | `single_lever` | 1 | `none` | 0.975 | +0.548 | +0.197 | 0.000 | +0.091 | +0.063 | 1.37 | PASS |
| `only_peer_framing` | `single_lever` | 1 | `peer` | 0.950 | +0.599 | +0.379 | 0.000 | +0.128 | +0.160 | 1.70 | PASS |
| `only_decoy_framing` | `decoy_control` | 0 | `decoy` | 0.950 | +0.589 | +0.210 | 0.000 | +0.130 | +0.124 | 1.50 | PASS |
| `no_surgical_shield` | `leave_one_out` | 3 | `peer` | 0.975 | +0.582 | +0.394 | 0.000 | +0.327 | +0.299 | 1.03 | PASS |
| `no_reactive_oldest` | `leave_one_out` | 3 | `peer` | 0.925 | +0.519 | +0.389 | 0.000 | +0.206 | +0.179 | 1.40 | PASS |
| `no_midgame_pacing` | `leave_one_out` | 3 | `peer` | 0.975 | +0.571 | +0.347 | 0.000 | +0.283 | +0.269 | 1.28 | PASS |
| `no_peer_framing` | `leave_one_out` | 3 | `none` | 0.950 | +0.554 | +0.346 | 0.000 | +0.270 | +0.219 | 1.22 | PASS |
| `synthesis_decoy_framing` | `decoy_control` | 3 | `decoy` | 0.950 | +0.523 | +0.247 | 0.000 | +0.267 | +0.212 | 1.08 | PASS |
| `frontier_synthesis_v14` | `composite` | 4 | `peer` | 0.975 | +0.586 | +0.397 | 0.000 | +0.327 | +0.299 | 1.03 | PASS |

## 6. Cross-Model Strategy Transfer (`99/99` Transcripts, `11/11` Gates) & Sleeper Minimax Regret Portfolio

- **Cross-model transfer (`results/mole_strategies/cross_model_transfer.json`, `docs/reports/mole_cross_model_transfer.md`)**: `99/99` raw frontier transcripts (`60` v1.4 `gemini-4-carbon` Hard across OpenCode MCP + in-proc; `39` v1.3 Codex/GPT-5.5 across Hard `n=19` and Medium `n=20`) reconstruct into public-tool schedules with `99/99` `audit_episode` baseline posterior parity. On fresh v1.4 Hard seeds `6200-6229` (`n=30`), `11/11` catalog entries (`9` unique behavioral policies) pass all catchability and anti-shortcut gates (`min solver_acc=0.900 >= 0.85`, `max logs_only_acc=0.000 <= 0.10`). `frontier_synthesis_v14` leads cross-family counterfactual EV drop (`+0.299` Gemini Hard, `+0.144` Codex/GPT-5.5 All, `+0.238` across all `99` transcripts, worst-family `+0.144`), while unique specialists (`n=4`) achieve `+0.232` in-domain vs `+0.206` out-of-domain proxy regret gain (`0.202` 5-investigator minimax regret and `+0.095` worst-family CF EV drop vs generalists `0.186` and `+0.022`).
- **Sleeper minimax attack-regret portfolio (`canary.mole.regret_portfolio`, `docs/reports/mole_regret_portfolio_v14.md`)**: Linear-programming saddle-point portfolio fit on `6000-6199` (`n=200`) places `0.8657` `surgical_trap_shield` + `0.1343` `gemini_midsize_shield`, equalizing binding adversaries (`gemini_carbon_proxy`, `hinted_heuristic`) at minimax regret `0.2090` (`duality_gap=2.22e-16`), strictly dominating `default_v0` (`+0.0132`) and best single pure strategy `early_burst_midgame_pace` (`0.1995`, `+0.0095`), with expected `SolverPolicy` `acc=0.969`, `LogsOnly` `acc=0.015`, and 60-transcript Gemini counterfactual EV drop `+0.166` (counterfactual regret `+0.225`). Zero-private-info SHA-256 seed-hashed `PortfolioMolePolicy` (`select_portfolio_strategy(seed, weights)`) passes every gate on disjoint held-out live validation seeds `6812-6823` (`n=12`, realizing `surgical_trap_shield`: `11`, `gemini_midsize_shield`: `1`): `SolverPolicy("hard")` `acc=1.000` (`score=+0.562`), `LogsOnly` `acc=0.000`, `DoNothing=0.000`, and `StopEarlyQuit=0.000`.

## 7. V1.6 Social Deception Audit & Honest Gate B Negative Result

- **Engineering & fairness gates (`PASS`)**: Across `16/16` audited V1.6 and sanitized `TextProvider` specs on Hard seeds `30-35` (`0` live API calls), `SolverPolicy` achieves bit-exact calibration parity (`max_abs_score_diff = 0.000000`), non-decoy `ANGER_WORDS` leakage is `0`, `DoNothing = 0.0`, `StopEarlyQuit = 0.0`, and all `10/10` collected Gemini checkpoints under `results/v16_social/partial/` replay bit-for-bit via `canary.social_audit.verify_and_score_episodes` with `0` mismatches.
- **Live Gate B outcome (`NOT MET`, negative result)**: Live `gemini-4-carbon` evaluation on Hard seeds `30-44` was halted early after `10` valid episodes (`v0_v14_control` `n=4`, `v5_full9_cocktail` `n=3`, `v3_grudge_falsemem_misforward` `n=2`, `v1_anchoring_authority_confirmation` `n=1`) to protect shared API quota for the primary `n=60` gap run. Neither the sample-size threshold (`n >= 15` / `n >= 30`) nor the gap-widening criterion (lowering `gemini-4-carbon` score below `v0_v14_control`) was met: structured forensic tools (`plant_canary`, `read_access_logs`, `check_leak_feed`) dominated social-chatter decoys (`10/10` correct accusations), and all three tested social variants scored higher in raw mean on their paired seeds than `v0_v14_control`.

| Checkpoint Variant | Provider Spec | Valid Seeds | n | Gemini Raw Mean | Gemini Luck-Adj Mean | Paired Delta Raw vs v0 | Paired Delta Luck-Adj vs v0 | Replay Mismatches | Gate B Verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `v0_v14_control` | `template` | `30,31,32,33` | 4 | +0.497 | +0.285 | +0.000 | +0.000 | 0 | CONTROL (n=4) |
| `v1_anchoring_authority_confirmation` | `v16:v1_anchoring_authority_confirmation` | `30` | 1 | +0.650 | +0.594 | +0.110 | +0.077 | 0 | NOT MET (negative) |
| `v3_grudge_falsemem_misforward` | `v16:v3_grudge_falsemem_misforward` | `30,31` | 2 | +0.645 | +0.604 | +0.100 | +0.080 | 0 | NOT MET (negative) |
| `v5_full9_cocktail` | `v16:v5_full9_cocktail` | `30,31,32` | 3 | +0.617 | +0.452 | +0.093 | -0.041 | 0 | NOT MET (negative) |
