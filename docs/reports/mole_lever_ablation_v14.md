# Mole Lever Ablation Study: `frontier_synthesis_v14` (`hard` Tier)

Generated deterministically offline (0 API calls) via `python -m canary.mole.ablation --tier hard --seeds 6600-6639 --cf-seeds 0-29 --cf-sources opencode,inproc --out results/mole_strategies/lever_ablation_v14.json --report-md docs/reports/mole_lever_ablation_v14.md`.

## 1. Executive Summary and Catchability / Anti-Cheese Gates

- **Live paired evaluation slice**: `n=40` fresh `hard` seeds (`6600-6639`), strictly disjoint from committed run seeds (`0..59`), reserved held-out evaluation seeds (`30000..30199`), and held-out/judge seeds (`800000+`, `900000+`).
- **Counterfactual frontier replay slice**: `n=60` committed v1.4 Gemini-4-carbon `hard` transcripts (`opencode,inproc`, seeds `0-29`) replayed under `canary.mole.counterfactual.ScheduleReplayPolicy` and scored with exact `SolverPolicy` posteriors.
- **Paired bootstrap uncertainty**: `5000` paired resamples (`ci=0.95`, `seed=20261114`).
- **Fairness and catchability gate summary**: **12/12** arms passed every gate (`SolverPolicy` catchability `>= 0.85`, observed minimum `0.925`; `SolverPolicy` score ratio `>= 0.50` of `default_v0` baseline `+0.556`; `LogsOnly` accuracy `<= 0.10`, observed maximum `0.000`; `DoNothing` max `|score| == 0.000`; `StopEarlyQuit` max `|score| == 0.000`).
- **Distinctness**: `unique_canonical_strategies=True`, `unique_empirical_ledgers=False`.
- **Full composite (`frontier_synthesis_v14` vs `default_v0`)**: mean frontier proxy regret gain `+0.175 [-0.052, +0.395]`, Gemini proxy score delta `-0.109 [-0.288, +0.059]`, Codex proxy score delta `-0.181 [-0.451, +0.099]`, counterfactual `P(true mole)` drop `+0.327 [+0.210, +0.435]`, counterfactual `optimal_ev` drop `+0.299 [+0.216, +0.378]`, while `SolverPolicy` score delta is `+0.030 [-0.105, +0.156]`.

## 2. Lever Specifications and Experimental Design

Every lever uses only public-free, non-omniscient `MoleView` features from `canary.mole.dsl` (no canary labels, no investigator belief state) and <=4 total DSL rules.

| Code | Lever ID | Single-Lever Arm | Leave-One-Out Arm | Mechanism |
|---|---|---|---|---|
| `(a)` | `surgical_low_recipient_shield` | `only_surgical_shield` | `no_surgical_shield` | Days 1..6 when >=2 leakable docs have <=3 recipients, leak most_recipients instead of surgical traps. |
| `(b)` | `reactive_age0_canary_oldest` | `only_reactive_oldest` | `no_reactive_oldest` | Days 1..7 when newest_doc_age_days == 0 and n_leakable >= 2, leak oldest doc to evade reactive day-d canaries. |
| `(c)` | `midgame_quiet_pacing` | `only_midgame_pacing` | `no_midgame_pacing` | Days 5..8 when days_since_last_leak < 2, throttle back-to-back leaks via leak='none'. |
| `(d)` | `non_decoy_peer_framing` | `only_peer_framing` | `no_peer_framing` | Frame most_restricted_peer when colleagues are restricted and random_peer otherwise, avoiding dismissed angry decoy. |

## 3. Paired 12-Arm Live and Counterfactual Results

| Arm | Kind | Solver Acc | Solver Score | Gemini Proxy | Codex Proxy | Grok | Frontier Regret | LogsOnly Acc (Score) | DoNothing | StopEarly | CF P(mole) Drop | CF EV Drop | Surf Canaries | Gates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `default_v0` | `baseline` | 0.975 | +0.556 +/- 0.091 | +0.292 | +0.375 | +0.332 | +0.223 | 0.000 (-1.000) | +0.000 | +0.000 | +0.000 | +0.000 | 1.73 | PASS |
| `only_surgical_shield` | `single_lever` | 0.975 | +0.547 +/- 0.090 | +0.292 | +0.375 | +0.299 | +0.214 | 0.000 (-1.000) | +0.000 | +0.000 | +0.000 | +0.000 | 1.73 | PASS |
| `only_reactive_oldest` | `single_lever` | 0.975 | +0.556 +/- 0.090 | +0.331 | +0.246 | +0.276 | +0.267 | 0.000 (-1.000) | +0.000 | +0.000 | +0.224 | +0.206 | 1.45 | PASS |
| `only_midgame_pacing` | `single_lever` | 0.975 | +0.548 +/- 0.094 | +0.392 | +0.310 | +0.274 | +0.197 | 0.000 (-1.000) | +0.000 | +0.000 | +0.091 | +0.063 | 1.37 | PASS |
| `only_peer_framing` | `single_lever` | 0.950 | +0.599 +/- 0.094 | +0.406 | +0.034 | +0.246 | +0.379 | 0.000 (-1.000) | +0.000 | +0.000 | +0.128 | +0.160 | 1.70 | PASS |
| `only_decoy_framing` | `decoy_control` | 0.950 | +0.589 +/- 0.089 | +0.360 | +0.398 | +0.149 | +0.210 | 0.000 (-1.000) | +0.000 | +0.000 | +0.130 | +0.124 | 1.50 | PASS |
| `no_surgical_shield` | `leave_one_out` | 0.975 | +0.582 +/- 0.085 | +0.183 | +0.194 | +0.263 | +0.394 | 0.000 (-1.000) | +0.000 | +0.000 | +0.327 | +0.299 | 1.03 | PASS |
| `no_reactive_oldest` | `leave_one_out` | 0.925 | +0.519 +/- 0.141 | +0.268 | -0.009 | +0.297 | +0.389 | 0.000 (-1.000) | +0.000 | +0.000 | +0.206 | +0.179 | 1.40 | PASS |
| `no_midgame_pacing` | `leave_one_out` | 0.975 | +0.571 +/- 0.090 | +0.269 | +0.177 | +0.282 | +0.347 | 0.000 (-1.000) | +0.000 | +0.000 | +0.283 | +0.269 | 1.28 | PASS |
| `no_peer_framing` | `leave_one_out` | 0.950 | +0.554 +/- 0.089 | +0.231 | +0.185 | +0.260 | +0.346 | 0.000 (-1.000) | +0.000 | +0.000 | +0.270 | +0.219 | 1.22 | PASS |
| `synthesis_decoy_framing` | `decoy_control` | 0.950 | +0.523 +/- 0.097 | +0.336 | +0.216 | +0.239 | +0.247 | 0.000 (-1.000) | +0.000 | +0.000 | +0.267 | +0.212 | 1.08 | PASS |
| `frontier_synthesis_v14` | `composite` | 0.975 | +0.586 +/- 0.084 | +0.183 | +0.194 | +0.292 | +0.397 | 0.000 (-1.000) | +0.000 | +0.000 | +0.327 | +0.299 | 1.03 | PASS |

## 4. Marginal Lever Contributions (Single-Lever Additions and Leave-One-Lever-Out)

Positive regret gain and positive counterfactual `P(true mole)` / `optimal_ev` drop indicate the lever increases investigator difficulty relative to the reference arm (`single_lever` vs `default_v0`, or full `frontier_synthesis_v14` vs `leave_one_out`).

| Lever | Contrast | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Frontier Regret Gain [95% CI] | CF P(mole) Drop Gain [95% CI] | CF EV Drop Gain [95% CI] | CF Canaries Delta [95% CI] |
|---|---|---|---|---|---|---|---|---|
| `(a) surgical_low_recipient_shield` | `only_surgical_shield` vs `default_v0` | -0.009 [-0.023, +0.000] | -0.009 [-0.023, +0.000] | -0.009 [-0.022, +0.000] | -0.009 [-0.023, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `(a) surgical_low_recipient_shield` | `frontier_synthesis_v14` vs `no_surgical_shield` | +0.004 [+0.000, +0.011] | +0.004 [+0.000, +0.011] | +0.004 [+0.000, +0.011] | +0.004 [+0.000, +0.011] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `(b) reactive_age0_canary_oldest` | `only_reactive_oldest` vs `default_v0` | +0.000 [-0.122, +0.122] | -0.039 [-0.223, +0.142] | +0.129 [-0.126, +0.398] | +0.045 [-0.140, +0.229] | +0.224 [+0.124, +0.330] | +0.206 [+0.139, +0.273] | -0.283 [-0.550, +0.000] |
| `(b) reactive_age0_canary_oldest` | `frontier_synthesis_v14` vs `no_reactive_oldest` | +0.067 [-0.093, +0.240] | +0.152 [-0.139, +0.453] | -0.136 [-0.521, +0.262] | +0.008 [-0.255, +0.295] | +0.121 [+0.042, +0.202] | +0.119 [+0.065, +0.179] | -0.367 [-0.567, -0.167] |
| `(c) midgame_quiet_pacing` | `only_midgame_pacing` vs `default_v0` | -0.007 [-0.045, +0.027] | -0.108 [-0.263, +0.039] | +0.057 [-0.099, +0.233] | -0.025 [-0.159, +0.098] | +0.091 [+0.032, +0.153] | +0.063 [+0.004, +0.122] | -0.367 [-0.550, -0.167] |
| `(c) midgame_quiet_pacing` | `frontier_synthesis_v14` vs `no_midgame_pacing` | +0.015 [+0.001, +0.035] | +0.101 [+0.036, +0.182] | -0.001 [-0.185, +0.174] | +0.050 [-0.049, +0.149] | +0.044 [-0.016, +0.102] | +0.030 [-0.011, +0.071] | -0.250 [-0.433, -0.083] |
| `(d) non_decoy_peer_framing` | `only_peer_framing` vs `default_v0` | +0.043 [-0.094, +0.170] | -0.071 [-0.283, +0.132] | +0.384 [+0.111, +0.664] | +0.157 [-0.058, +0.370] | +0.128 [+0.013, +0.242] | +0.160 [+0.076, +0.248] | -0.033 [-0.433, +0.383] |
| `(d) non_decoy_peer_framing` | `frontier_synthesis_v14` vs `no_peer_framing` | +0.032 [-0.104, +0.171] | +0.080 [-0.168, +0.332] | +0.023 [-0.275, +0.312] | +0.052 [-0.155, +0.250] | +0.057 [-0.060, +0.171] | +0.080 [+0.001, +0.161] | -0.183 [-0.450, +0.083] |

### 4.1 Counterfactual Drop Split by Frontier Harness (`opencode` vs `inproc`)

| Lever | Contrast | OpenCode CF P(mole) Drop Gain [95% CI] | OpenCode CF EV Drop Gain [95% CI] | In-Proc CF P(mole) Drop Gain [95% CI] | In-Proc CF EV Drop Gain [95% CI] |
|---|---|---|---|---|---|
| `(a) surgical_low_recipient_shield` | `single_vs_default` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `(a) surgical_low_recipient_shield` | `loo_in_synthesis` | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `(b) reactive_age0_canary_oldest` | `single_vs_default` | +0.199 [+0.028, +0.368] | +0.191 [+0.092, +0.293] | +0.248 [+0.137, +0.367] | +0.221 [+0.135, +0.306] |
| `(b) reactive_age0_canary_oldest` | `loo_in_synthesis` | +0.084 [-0.020, +0.190] | +0.105 [+0.044, +0.176] | +0.158 [+0.035, +0.283] | +0.134 [+0.046, +0.230] |
| `(c) midgame_quiet_pacing` | `single_vs_default` | +0.066 [-0.027, +0.153] | +0.049 [-0.036, +0.145] | +0.116 [+0.040, +0.204] | +0.076 [-0.001, +0.163] |
| `(c) midgame_quiet_pacing` | `loo_in_synthesis` | +0.050 [-0.022, +0.132] | +0.029 [-0.039, +0.098] | +0.037 [-0.045, +0.117] | +0.030 [-0.007, +0.074] |
| `(d) non_decoy_peer_framing` | `single_vs_default` | +0.001 [-0.150, +0.153] | +0.109 [-0.000, +0.224] | +0.256 [+0.089, +0.422] | +0.211 [+0.086, +0.336] |
| `(d) non_decoy_peer_framing` | `loo_in_synthesis` | -0.003 [-0.166, +0.158] | +0.055 [-0.061, +0.174] | +0.116 [-0.045, +0.275] | +0.105 [-0.005, +0.208] |

## 5. Non-Decoy Peer Framing vs Angry-Decoy Framing Controls

Committed frontier transcripts showed 100% dismissal of the angry decoy (`0` accusations and `0` restrictions across 159 decoy-enabled episodes), whereas non-decoy peer after-hours log framing broke 0-separation ties into wrong accusations. The two decoy control arms (`only_decoy_framing` and `synthesis_decoy_framing`) isolate framing choice while holding leak selection identical.

| Framing Contrast | Treatment vs Reference | Frontier Regret Gain [95% CI] | Gemini Score Delta [95% CI] | Codex Score Delta [95% CI] | CF P(mole) Drop Gain [95% CI] | CF EV Drop Gain [95% CI] |
|---|---|---|---|---|---|---|
| Peer vs Decoy (composite) | `frontier_synthesis_v14` vs `synthesis_decoy_framing` | +0.150 [-0.078, +0.391] | -0.153 [-0.375, +0.055] | -0.022 [-0.305, +0.266] | +0.060 [-0.060, +0.178] | +0.086 [+0.015, +0.153] |
| Peer vs Decoy (single-lever) | `only_peer_framing` vs `only_decoy_framing` | +0.169 [+0.010, +0.346] | +0.046 [-0.126, +0.217] | -0.364 [-0.623, -0.119] | -0.002 [-0.120, +0.121] | +0.036 [-0.045, +0.117] |
| Decoy vs None (composite) | `synthesis_decoy_framing` vs `no_peer_framing` | -0.099 [-0.306, +0.130] | +0.105 [-0.075, +0.283] | +0.031 [-0.206, +0.265] | -0.003 [-0.123, +0.122] | -0.006 [-0.077, +0.067] |
| Decoy vs Default (single-lever) | `only_decoy_framing` vs `default_v0` | -0.012 [-0.224, +0.192] | +0.068 [-0.141, +0.281] | +0.023 [-0.157, +0.201] | +0.130 [+0.019, +0.245] | +0.124 [+0.042, +0.205] |

## 6. Determinism and Strategy Provenance Hashes

| Arm | Rules | Framing Mode | Active Levers | Behavior Hash | Canonical SHA-256 | Empirical Ledger Hash |
|---|---|---|---|---|---|---|
| `default_v0` | 0 | `none` | `none` | `4ce97ce85124050ce478649ec860136b` | `6ac100ee503ef397` | `0d86d7f9bab5d23e` |
| `only_surgical_shield` | 1 | `none` | `surgical_low_recipient_shield` | `25006c4cd0f0fcaa59278575c1b49f78` | `b0ce0ecbb3751999` | `0d86d7f9bab5d23e` |
| `only_reactive_oldest` | 1 | `none` | `reactive_age0_canary_oldest` | `09f176625f7966c2d002ea32a8150398` | `ae25e69054f390ab` | `fe268baa2fad22af` |
| `only_midgame_pacing` | 1 | `none` | `midgame_quiet_pacing` | `1f92668c37bb0edc03c355213c6cb818` | `a3ebbcf503c7a710` | `8ddd21b1ac915079` |
| `only_peer_framing` | 1 | `peer` | `non_decoy_peer_framing` | `2e2854584c82279f5bdbaa42d455b68d` | `79710b32bfa8a62b` | `9b31a9b217af73d0` |
| `only_decoy_framing` | 0 | `decoy` | `none` | `148c75bd693d35443ef94edf2fa49a7f` | `e49411345d836752` | `120c555ea407fa78` |
| `no_surgical_shield` | 3 | `peer` | `reactive_age0_canary_oldest, midgame_quiet_pacing, non_decoy_peer_framing` | `637c34ad367fd384918bcbeb2fa2b16a` | `b4f6adb79829efc3` | `3928af42e88b12ec` |
| `no_reactive_oldest` | 3 | `peer` | `surgical_low_recipient_shield, midgame_quiet_pacing, non_decoy_peer_framing` | `2fb0ea5bedca5b5e3442f16d4bd8a3d7` | `b0c88d0fd784a8d0` | `776b835ba4935cca` |
| `no_midgame_pacing` | 3 | `peer` | `surgical_low_recipient_shield, reactive_age0_canary_oldest, non_decoy_peer_framing` | `eec9419bd531541cef0d1bfb6879576e` | `002dfc4aa23cac14` | `86552dbb822eaa3e` |
| `no_peer_framing` | 3 | `none` | `surgical_low_recipient_shield, reactive_age0_canary_oldest, midgame_quiet_pacing` | `b55d9d4a5907ef3bf59f33e5c10e46f8` | `87a7bb8844fbf248` | `ae85a3379ef24812` |
| `synthesis_decoy_framing` | 3 | `decoy` | `surgical_low_recipient_shield, reactive_age0_canary_oldest, midgame_quiet_pacing` | `1214e5b95f9149142b543c86d87d80ed` | `04c5be15bd581ce0` | `0a733e92a944e49d` |
| `frontier_synthesis_v14` | 4 | `peer` | `surgical_low_recipient_shield, reactive_age0_canary_oldest, midgame_quiet_pacing, non_decoy_peer_framing` | `eec9419bd531541cef0d1bfb6879576e` | `0e890e18d1c8aea7` | `3928af42e88b12ec` |
