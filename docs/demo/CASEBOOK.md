# Out-Think Gemini: Casebook and Scoreboard Provenance

Deterministic, zero-API-call provenance and scoreboard reference for **Out-Think Gemini** (`results/gemini/out_think_gemini.json` and `demo/out-think-gemini/cases.js`, `tiers_version = v1.4`). All **12 playable decision snapshots** come from **550 recorded ladder episodes** (`618` unique ledger runs, **$262.7061** verified API spend in `results/gemini/ladder_episodes.jsonl.gz` and `results/gemini/ladder_ledger.jsonl.gz`), paired against the exact Bayesian `SolverPolicy` reference (`data/runs/committed/v1.4/reference`). Across the 12 cases, the bundle ships **39 paired `thinking_level` trajectories** across `minimal`, `low`, `medium`, `high`, and `xhigh` (**581,904** thinking tokens, **2,194** ledger calls, **$15.280309** direct trajectory spend) plus **12 `cross_model_carbon` case comparisons** (23 `gemini-4-carbon` runs).

## 1. Corpus and Bundle Provenance Summary

| Provenance Field | Verified Value |
| --- | --- |
| Canonical JSON Artifact | `results/gemini/out_think_gemini.json` |
| Browser UMD Bundle | `demo/out-think-gemini/cases.js` (`json_js_identical = True`, `isBootstrapFallback = False`) |
| Source Ladder Episodes | `results/gemini/ladder_episodes.jsonl.gz` (**550** valid recorded episodes) |
| Source Cost Ledger | `results/gemini/ladder_ledger.jsonl.gz` (**618** unique ledger runs, **$262.7061** total spend) |
| Reference Solver Corpus | `data/runs/committed/v1.4/reference` (`tiers_version = v1.4`) |
| Playable Decision Cases | **12** (`8` `hold_fire`, `4` `accuse`; 6 `hard`, 6 `medium`) |
| Public World Seeds (11 unique) | `hard:1`, `hard:18`, `hard:3`, `hard:4`, `hard:7`, `medium:1`, `medium:2`, `medium:4`, `medium:6`, `medium:8`, `medium:9` (0 overlap with `HELDOUT_SEEDS` or `JUDGE_SEEDS`) |
| Anchor Gemini Models (6) | `gemini-4-carbon`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-3.5-flash`, `gemini-4-argon` |
| Paired `thinking_level` Runs | **39** across `minimal` (4), `low` (12), `medium` (10), `high` (11), `xhigh` (2) |
| Paired Trajectory Token & Cost Totals | **581,904** thinking tokens, **2,194** ledger calls, **$15.280309** |
| `cross_model_carbon` Comparisons | **12/12** cases covered (**23** `gemini-4-carbon` runs) |
| Embedded `ladder_matrix` Cells | **222** cross-model / cross-level cells on the same `(tier, seed)` worlds |

## 2. Aggregate Scoreboard Benchmarks and Thinking Ladder

### 2.1 Judge and Reference Policy Scoreboard (12 Cases)

| Benchmark Policy | Total Score | Mean Score | Right Calls | Accuracy | Optimal Calls | Optimal Rate | Compute Spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Optimal Judge** | `+7.80` | `+0.6500` | `12/12` | `100.0%` | `12/12` | `100.0%` | `$0.00` |
| **Bayesian Solver** | `+7.90` | `+0.6583` | `12/12` | `100.0%` | `12/12` | `100.0%` | `$0.00` |
| **Always-Hold-Fire** | `+7.42` | `+0.6183` | `8/12` | `66.7%` | `8/12` | `66.7%` | `$0.00` |
| **Oracle Mole-Now (Hindsight)** | `+7.98` | `+0.6650` | `12/12` | `100.0%` | `4/12` | `33.3%` | `$0.00` |
| **Opposite-of-Solver** | `-2.49` | `-0.2075` | `2/12` | `16.7%` | `0/12` | `0.0%` | `$0.00` |
| **Wrong-Accusation** | `-12.00` | `-1.0000` | `0/12` | `0.0%` | `0/12` | `0.0%` | `$0.00` |

- **Optimal Judge (`+7.80`, `12/12` optimal, `$0`) vs Bayesian Solver (`+7.90`, `12/12`):** Optimal Judge acts from each anchor model's frozen pre-accusation state at `(decision_day, decision_step)` (earning `V_d` on the 4 `accuse` cases `+0.71 + 0.73 + 0.50 + 0.82 = +2.76` and `ev_hold_fire` on the 8 `hold_fire` cases `+5.04`, summing to `+7.80`). Full-episode `SolverPolicy` designs its own canary splits from `t = 0` (`+7.90` across the 12 case worlds, isolating `hard:1` by day 7 for `+0.69` rather than day 14 `V_d = 0.50` on `flash35-hard-1`).
- **Always-Hold-Fire (`+7.42`) vs Optimal Judge (`+7.80`):** Holding fire when `top_prob >= 0.98` incurs the `-0.12` `OVER-CAUTIOUS DELAY` penalty on `carbon-medium-4`, `flash35-hard-1`, and `argon-medium-6` (`-0.36` combined) plus `-0.02` continuation decay on `carbon-hard-1` (`+0.69` vs `+0.71`).
- **Opposite-of-Solver (`-2.49`) and Wrong-Accusation (`-12.00`):** Inverting `SolverPolicy` delays all 4 pinned accusations and gambles below break-even on all 8 `hold_fire` cases (`2/12` lucky hits on `flash38-hard-7` and `argon-hard-18` where `top_suspect == true_mole`, `6/12` `-1.00` false accusations, `0/12` optimal). Accusing a non-mole suspect on every case scores `-1.00 * 12 = -12.00`.

### 2.2 Monotonic Gemini `thinking_level` Ladder (39 Paired Trajectories)

Monotonic Gemini `thinking_level` mean score progression: **`minimal -0.525 -> low -0.2367 -> medium +0.307 -> high +0.6127 -> xhigh +0.705`**.

| `thinking_level` | Runs (`n`) | Total Score | Mean Score | Right Calls | Accuracy | Thinking Tokens | Total Cost (USD) | Optimal Judge Outscored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `minimal` | 4 | `-2.10` | `-0.525` (`-0.5250`) | `1/4` | `25.00%` | 0 | `$0.324639` | `3/4` |
| `low` | 12 | `-2.84` | `-0.2367` (`-0.2367`) | `6/12` | `50.00%` | 37,548 | `$3.863664` | `11/12` |
| `medium` | 10 | `+3.07` | `+0.307` (`+0.3070`) | `8/10` | `80.00%` | 157,746 | `$3.454475` | `6/10` |
| `high` | 11 | `+6.74` | `+0.6127` (`+0.6127`) | `10/11` | `90.91%` | 276,139 | `$5.826949` | `3/11` |
| `xhigh` | 2 | `+1.41` | `+0.705` (`+0.7050`) | `2/2` | `100.00%` | 110,471 | `$1.810582` | `1/2` |
| **Combined (`all 5 levels`)** | **39** | **`+6.28`** | **`+0.1610`** | **`27/39`** | **`69.23%`** | **581,904** | **`$15.280309`** | **`24/39`** |

## 3. Playable 12-Case Decision Threshold and EV Master Table

| `case_id` | `model` | `tier` | `seed` | `decision_day` | `decision_step` | `value_at_decision` (`V_d`) | `break_even_prob` (`1/(1+V_d)`) | `SolverPolicy` `top_prob` (`top_suspect`) | `recommended_call` | `EV(accuse_top)` | Optimal Judge EV | Solver EV | Per-Level Scores / Thinking Tokens / Costs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |
| `carbon-hard-1` | `gemini-4-carbon` | `hard` | 1 | 9 | 90 | `0.71` | `0.5848` | `0.9769` (`e33`) | `accuse` | `+0.6704` | `+0.71` | `+0.69` | `low`: +0.29 (467t, $1.0508); `high`: +0.71 (40,681t, $1.5962) |
| `flash-lite-hard-4` | `gemini-3.1-flash-lite` | `hard` | 4 | 6 | 49 | `0.83` | `0.5464` | `0.1520` (`e29`) | `hold_fire` | `-0.7218` | `+0.73` | `+0.73` | `minimal`: -1.00 (0t, $0.0438); `low`: -1.00 (5,885t, $0.0689); `medium`: -1.00 (0t, $0.0397); `high`: +0.82 (3,484t, $0.0620) |
| `flash38-hard-7` | `gemini-3.8-flash` | `hard` | 7 | 6 | 33 | `0.79` | `0.5587` | `0.3646` (`e37`) | `hold_fire` | `-0.3474` | `+0.64` | `+0.64` | `low`: -1.00 (0t, $0.0742); `medium`: +0.54 (23,042t, $0.3154); `high`: +0.63 (56,815t, $0.7145) |
| `carbon-medium-4` | `gemini-4-carbon` | `medium` | 4 | 8 | 75 | `0.73` | `0.5780` | `1.0000` (`e17`) | `accuse` | `+0.7300` | `+0.73` | `+0.69` | `low`: +0.37 (1,024t, $0.8079); `high`: +0.73 (44,035t, $1.1549) |
| `flash-lite-medium-1` | `gemini-3.1-flash-lite` | `medium` | 1 | 4 | 26 | `0.88` | `0.5319` | `0.2107` (`e14`) | `hold_fire` | `-0.6038` | `+0.39` | `+0.39` | `minimal`: -1.00 (0t, $0.0214); `low`: +0.90 (2,756t, $0.0332); `medium`: +0.71 (3,264t, $0.1430); `high`: +0.83 (3,046t, $0.0447) |
| `hydrogen-hard-3` | `gemini-4-hydrogen` | `hard` | 3 | 18 | 43 | `0.50` | `0.6667` | `0.0998` (`e01`) | `hold_fire` | `-0.8503` | `+0.28` | `+0.28` | `low`: -1.00 (4,430t, $0.1967); `medium`: +0.44 (15,753t, $0.4922); `high`: -1.00 (35,452t, $0.6535); `xhigh`: +0.71 (61,861t, $0.9419) |
| `flash38-medium-9` | `gemini-3.8-flash` | `medium` | 9 | 8 | 60 | `0.70` | `0.5882` | `0.2530` (`e06`) | `hold_fire` | `-0.5698` | `+0.80` | `+0.80` | `low`: -1.00 (0t, $0.1288); `medium`: +0.53 (51,015t, $0.8332); `high`: +0.75 (28,178t, $0.3126) |
| `flash35-hard-1` | `gemini-3.5-flash` | `hard` | 1 | 14 | 68 | `0.50` | `0.6667` | `0.9990` (`e33`) | `accuse` | `+0.4984` | `+0.50` | `+0.69` | `minimal`: -1.00 (0t, $0.2163); `low`: +0.41 (9,089t, $0.4014); `medium`: +0.68 (26,168t, $0.5245); `high`: +0.65 (27,008t, $0.3596) |
| `argon-hard-18` | `gemini-4-argon` | `hard` | 18 | 19 | 115 | `0.34` | `0.7463` | `0.4616` (`e27`) | `hold_fire` | `-0.3814` | `+0.52` | `+0.52` | `low`: -1.00 (0t, $0.3094); `medium`: +0.50 (0t, $0.1550) |
| `argon-medium-6` | `gemini-4-argon` | `medium` | 6 | 7 | 64 | `0.82` | `0.5495` | `1.0000` (`e17`) | `accuse` | `+0.8200` | `+0.82` | `+0.79` | `low`: +0.53 (0t, $0.1558); `medium`: +0.77 (11,230t, $0.2717); `high`: +0.82 (16,481t, $0.5904) |
| `hydrogen-medium-2` | `gemini-4-hydrogen` | `medium` | 2 | 14 | 90 | `0.56` | `0.6410` | `0.5248` (`e06`) | `hold_fire` | `-0.1814` | `+0.80` | `+0.80` | `low`: +0.66 (2,572t, $0.1479); `medium`: -1.00 (16,039t, $0.5583); `high`: +0.90 (8,344t, $0.1761); `xhigh`: +0.70 (48,610t, $0.8687) |
| `flash35-medium-8` | `gemini-3.5-flash` | `medium` | 8 | 14 | 83 | `0.62` | `0.6173` | `0.3485` (`e17`) | `hold_fire` | `-0.4355` | `+0.88` | `+0.88` | `minimal`: +0.90 (0t, $0.0432); `low`: -1.00 (11,325t, $0.4885); `medium`: +0.90 (11,235t, $0.1216); `high`: +0.90 (12,615t, $0.1625) |

## 4. Per-Level Trajectory Provenance Table (All 39 Paired Runs)

| `case_id` | `model` | `thinking_level` | `call_at_t` | Accused (Day) | Correct | Score | Regret | Thinking Tokens | In / Out / Cached Tokens | Ledger Calls | Cost (USD) | Failure Tag | `run_id` |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| `carbon-hard-1` | `gemini-4-carbon` | `low` | `hold_fire` | `e33` (d17) | `yes` | `+0.29` | `0.40` | 467 | 2,252,359 / 4,227 / 2,011,033 | 153 | `$1.050836` | `ignored_delay` | `ladder:ladder-v14:gemini-4-carbon/low/hard/1` |
| `carbon-hard-1` | `gemini-4-carbon` | `high` | `accuse` | `e33` (d9) | `yes` | `+0.71` | `0.00` | 40,681 | 3,194,664 / 2,867 / 2,859,540 | 99 | `$1.596177` | `none` | `ladder:ladder-v14:gemini-4-carbon/high/hard/1` |
| `flash-lite-hard-4` | `gemini-3.1-flash-lite` | `minimal` | `accuse` | `e39` (d6) | `no` | `-1.00` | `1.73` | 0 | 322,419 / 871 / 169,282 | 50 | `$0.043823` | `premature_accusation` | `ladder:ladder-v14:gemini-3.1-flash-lite/minimal/hard/4` |
| `flash-lite-hard-4` | `gemini-3.1-flash-lite` | `low` | `accuse` | `e38` (d6) | `no` | `-1.00` | `1.73` | 5,885 | 704,388 / 2,064 / 529,510 | 42 | `$0.068881` | `premature_accusation` | `ladder:ladder-v14:gemini-3.1-flash-lite/low/hard/4` |
| `flash-lite-hard-4` | `gemini-3.1-flash-lite` | `medium` | `accuse` | `e20` (d5) | `no` | `-1.00` | `1.73` | 0 | 275,771 / 1,148 / 137,609 | 47 | `$0.039703` | `premature_accusation` | `ladder:ladder-v14:gemini-3.1-flash-lite/medium/hard/4` |
| `flash-lite-hard-4` | `gemini-3.1-flash-lite` | `high` | `accuse` | `e11` (d6) | `yes` | `+0.82` | `0.00` | 3,484 | 517,100 / 1,152 / 330,056 | 42 | `$0.061966` | `none` | `ladder:ladder-v14:gemini-3.1-flash-lite/high/hard/4` |
| `flash38-hard-7` | `gemini-3.8-flash` | `low` | `accuse` | `e11` (d6) | `no` | `-1.00` | `1.64` | 0 | 251,917 / 973 / 175,351 | 34 | `$0.074227` | `premature_accusation` | `ladder:ladder-v14:gemini-3.8-flash/low/hard/7` |
| `flash38-hard-7` | `gemini-3.8-flash` | `medium` | `hold_fire` | `e37` (d12) | `yes` | `+0.54` | `0.10` | 23,042 | 1,503,044 / 1,102 / 1,336,943 | 49 | `$0.315385` | `none` | `ladder:ladder-v14:gemini-3.8-flash/medium/hard/7` |
| `flash38-hard-7` | `gemini-3.8-flash` | `high` | `hold_fire` | `e37` (d14) | `yes` | `+0.63` | `0.01` | 56,815 | 4,319,526 / 2,272 / 4,069,188 | 75 | `$0.714516` | `none` | `ladder:ladder-v14:gemini-3.8-flash/high/hard/7` |
| `carbon-medium-4` | `gemini-4-carbon` | `low` | `hold_fire` | `e17` (d14) | `yes` | `+0.37` | `0.32` | 1,024 | 1,845,935 / 3,907 / 1,543,830 | 118 | `$0.807903` | `ignored_delay` | `ladder:ladder-v14:gemini-4-carbon/low/medium/4` |
| `carbon-medium-4` | `gemini-4-carbon` | `high` | `accuse` | `e17` (d8) | `yes` | `+0.73` | `0.00` | 44,035 | 2,847,472 / 2,567 / 2,634,794 | 76 | `$1.154853` | `none` | `ladder:ladder-v14:gemini-4-carbon/high/medium/4` |
| `flash-lite-medium-1` | `gemini-3.1-flash-lite` | `minimal` | `accuse` | `e06` (d4) | `no` | `-1.00` | `1.39` | 0 | 109,482 / 630 / 30,919 | 27 | `$0.021359` | `premature_accusation` | `ladder:ladder-v14:gemini-3.1-flash-lite/minimal/medium/1` |
| `flash-lite-medium-1` | `gemini-3.1-flash-lite` | `low` | `accuse` | `e02` (d4) | `yes` | `+0.90` | `0.00` | 2,756 | 198,908 / 775 / 97,025 | 24 | `$0.033193` | `none` | `ladder:ladder-v14:gemini-3.1-flash-lite/low/medium/1` |
| `flash-lite-medium-1` | `gemini-3.1-flash-lite` | `medium` | `hold_fire` | `e02` (d8) | `yes` | `+0.71` | `0.00` | 3,264 | 1,392,498 / 1,985 / 946,577 | 82 | `$0.143018` | `none` | `ladder:ladder-v14:gemini-3.1-flash-lite/medium/medium/1` |
| `flash-lite-medium-1` | `gemini-3.1-flash-lite` | `high` | `hold_fire` | `e02` (d5) | `yes` | `+0.83` | `0.00` | 3,046 | 316,271 / 720 / 177,819 | 32 | `$0.044707` | `none` | `ladder:ladder-v14:gemini-3.1-flash-lite/high/medium/1` |
| `hydrogen-hard-3` | `gemini-4-hydrogen` | `low` | `accuse` | `e21` (d18) | `no` | `-1.00` | `1.28` | 4,430 | 362,444 / 1,320 / 273,733 | 38 | `$0.196724` | `premature_accusation` | `ladder:ladder30:gemini-4-hydrogen/low/hard/3` |
| `hydrogen-hard-3` | `gemini-4-hydrogen` | `medium` | `accuse` | `e29` (d12) | `yes` | `+0.44` | `0.00` | 15,753 | 1,524,652 / 2,511 / 1,355,648 | 68 | `$0.492160` | `none` | `ladder:ladder30:gemini-4-hydrogen/medium/hard/3` |
| `hydrogen-hard-3` | `gemini-4-hydrogen` | `high` | `accuse` | `e26` (d12) | `no` | `-1.00` | `1.28` | 35,452 | 1,794,494 / 2,041 / 1,627,671 | 63 | `$0.653505` | `premature_accusation` | `ladder:ladder30:gemini-4-hydrogen/high/hard/3` |
| `hydrogen-hard-3` | `gemini-4-hydrogen` | `xhigh` | `accuse` | `e29` (d6) | `yes` | `+0.71` | `0.00` | 61,861 | 2,722,473 / 2,415 / 2,543,057 | 64 | `$0.941924` | `none` | `ladder:ladder30:gemini-4-hydrogen/xhigh/hard/3` |
| `flash38-medium-9` | `gemini-3.8-flash` | `low` | `accuse` | `e06` (d8) | `no` | `-1.00` | `1.80` | 0 | 475,236 / 1,468 / 345,343 | 61 | `$0.128824` | `premature_accusation` | `ladder:ladder-v14:gemini-3.8-flash/low/medium/9` |
| `flash38-medium-9` | `gemini-3.8-flash` | `medium` | `hold_fire` | `e15` (d14) | `yes` | `+0.53` | `0.27` | 51,015 | 5,201,408 / 2,247 / 4,840,870 | 101 | `$0.833202` | `none` | `ladder:ladder-v14:gemini-3.8-flash/medium/medium/9` |
| `flash38-medium-9` | `gemini-3.8-flash` | `high` | `hold_fire` | `e15` (d9) | `yes` | `+0.75` | `0.05` | 28,178 | 1,387,890 / 774 / 1,239,897 | 43 | `$0.312559` | `none` | `ladder:ladder-v14:gemini-3.8-flash/high/medium/9` |
| `flash35-hard-1` | `gemini-3.5-flash` | `minimal` | `accuse` | `e27` (d14) | `no` | `-1.00` | `1.69` | 0 | 703,436 / 4,663 / 487,060 | 69 | `$0.216298` | `variant_inversion` | `ladder:ladder-v14:gemini-3.5-flash/minimal/hard/1` |
| `flash35-hard-1` | `gemini-3.5-flash` | `low` | `accuse` | `e33` (d13) | `yes` | `+0.41` | `0.28` | 9,089 | 1,862,883 / 3,624 / 1,545,781 | 67 | `$0.401434` | `none` | `ladder:ladder-v14:gemini-3.5-flash/low/hard/1` |
| `flash35-hard-1` | `gemini-3.5-flash` | `medium` | `accuse` | `e33` (d11) | `yes` | `+0.68` | `0.01` | 26,168 | 2,973,282 / 2,008 / 2,683,143 | 75 | `$0.524500` | `none` | `ladder:ladder-v14:gemini-3.5-flash/medium/hard/1` |
| `flash35-hard-1` | `gemini-3.5-flash` | `high` | `accuse` | `e33` (d10) | `yes` | `+0.65` | `0.04` | 27,008 | 1,691,493 / 1,241 / 1,503,564 | 49 | `$0.359648` | `none` | `ladder:ladder-v14:gemini-3.5-flash/high/hard/1` |
| `argon-hard-18` | `gemini-4-argon` | `low` | `accuse` | `e37` (d19) | `no` | `-1.00` | `1.52` | 0 | 909,096 / 3,216 / 811,031 | 36 | `$0.309393` | `premature_accusation` | `ladder:ladder30:gemini-4-argon/low/hard/18` |
| `argon-hard-18` | `gemini-4-argon` | `medium` | `accuse` | `e27` (d13) | `yes` | `+0.50` | `0.02` | 0 | 213,120 / 1,985 / 153,221 | 25 | `$0.154971` | `none` | `ladder:ladder30:gemini-4-argon/medium/hard/18` |
| `argon-medium-6` | `gemini-4-argon` | `low` | `hold_fire` | `e17` (d11) | `yes` | `+0.53` | `0.26` | 0 | 260,038 / 2,454 / 204,621 | 23 | `$0.155838` | `ignored_delay` | `ladder:ladder-v14:gemini-4-argon/low/medium/6` |
| `argon-medium-6` | `gemini-4-argon` | `medium` | `accuse` | `e17` (d7) | `yes` | `+0.77` | `0.02` | 11,230 | 334,012 / 1,488 / 275,543 | 23 | `$0.271672` | `none` | `ladder:ladder-v14:gemini-4-argon/medium/medium/6` |
| `argon-medium-6` | `gemini-4-argon` | `high` | `accuse` | `e17` (d7) | `yes` | `+0.82` | `0.00` | 16,481 | 1,159,626 / 1,869 / 1,006,514 | 65 | `$0.590374` | `none` | `ladder:ladder-v14:gemini-4-argon/high/medium/6` |
| `hydrogen-medium-2` | `gemini-4-hydrogen` | `low` | `accuse` | `e09` (d9) | `yes` | `+0.66` | `0.14` | 2,572 | 209,050 / 1,042 / 135,258 | 32 | `$0.147938` | `none` | `ladder:ladder30:gemini-4-hydrogen/low/medium/2` |
| `hydrogen-medium-2` | `gemini-4-hydrogen` | `medium` | `accuse` | `e06` (d14) | `no` | `-1.00` | `1.80` | 16,039 | 1,533,691 / 3,267 / 1,324,261 | 91 | `$0.558253` | `premature_accusation` | `ladder:ladder30:gemini-4-hydrogen/medium/medium/2` |
| `hydrogen-medium-2` | `gemini-4-hydrogen` | `high` | `accuse` | `e09` (d3) | `yes` | `+0.90` | `0.00` | 8,344 | 243,914 / 804 / 181,295 | 27 | `$0.176134` | `none` | `ladder:ladder30:gemini-4-hydrogen/high/medium/2` |
| `hydrogen-medium-2` | `gemini-4-hydrogen` | `xhigh` | `accuse` | `e09` (d8) | `yes` | `+0.70` | `0.10` | 48,610 | 2,780,129 / 2,536 / 2,586,054 | 77 | `$0.868658` | `none` | `ladder:ladder30:gemini-4-hydrogen/xhigh/medium/2` |
| `flash35-medium-8` | `gemini-3.5-flash` | `minimal` | `accuse` | `e02` (d3) | `yes` | `+0.90` | `0.00` | 0 | 59,728 / 465 / 5,008 | 16 | `$0.043159` | `none` | `ladder:ladder-v14:gemini-3.5-flash/minimal/medium/8` |
| `flash35-medium-8` | `gemini-3.5-flash` | `low` | `accuse` | `e09` (d14) | `no` | `-1.00` | `1.88` | 11,325 | 2,162,993 / 2,051 / 1,753,973 | 84 | `$0.488473` | `premature_accusation` | `ladder:ladder-v14:gemini-3.5-flash/low/medium/8` |
| `flash35-medium-8` | `gemini-3.5-flash` | `medium` | `accuse` | `e02` (d3) | `yes` | `+0.90` | `0.00` | 11,235 | 236,571 / 530 / 148,053 | 21 | `$0.121611` | `none` | `ladder:ladder-v14:gemini-3.5-flash/medium/medium/8` |
| `flash35-medium-8` | `gemini-3.5-flash` | `high` | `accuse` | `e02` (d3) | `yes` | `+0.90` | `0.00` | 12,615 | 409,216 / 582 / 287,246 | 26 | `$0.162510` | `none` | `ladder:ladder-v14:gemini-3.5-flash/high/medium/8` |

## 5. Cross-Model `gemini-4-carbon` Reference Strips (12 Cases, 23 Runs)

| `case_id` | World | Anchor Model | Carbon Level | Accused (Day) | Correct | Score | Thinking Tokens | Cost (USD) | `run_id` |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `carbon-hard-1` | `hard:1` | `gemini-4-carbon` | `low` | `e33` (d17) | `yes` | `+0.29` | 467 | `$1.050836` | `ladder:ladder-v14:gemini-4-carbon/low/hard/1` |
| `carbon-hard-1` | `hard:1` | `gemini-4-carbon` | `high` | `e33` (d9) | `yes` | `+0.71` | 40,681 | `$1.596177` | `ladder:ladder-v14:gemini-4-carbon/high/hard/1` |
| `flash-lite-hard-4` | `hard:4` | `gemini-3.1-flash-lite` | `low` | `e11` (d11) | `yes` | `+0.54` | 18 | `$0.488795` | `ladder:ladder-v14:gemini-4-carbon/low/hard/4` |
| `flash-lite-hard-4` | `hard:4` | `gemini-3.1-flash-lite` | `high` | `e11` (d8) | `yes` | `+0.66` | 51,059 | `$1.330160` | `ladder:ladder-v14:gemini-4-carbon/high/hard/4` |
| `flash38-hard-7` | `hard:7` | `gemini-3.8-flash` | `low` | `e37` (d15) | `yes` | `+0.39` | 581 | `$0.827693` | `ladder:ladder-v14:gemini-4-carbon/low/hard/7` |
| `flash38-hard-7` | `hard:7` | `gemini-3.8-flash` | `high` | `e37` (d11) | `yes` | `+0.60` | 60,951 | `$1.860788` | `ladder:ladder-v14:gemini-4-carbon/high/hard/7` |
| `carbon-medium-4` | `medium:4` | `gemini-4-carbon` | `low` | `e17` (d14) | `yes` | `+0.37` | 1,024 | `$0.807903` | `ladder:ladder-v14:gemini-4-carbon/low/medium/4` |
| `carbon-medium-4` | `medium:4` | `gemini-4-carbon` | `high` | `e17` (d8) | `yes` | `+0.73` | 44,035 | `$1.154853` | `ladder:ladder-v14:gemini-4-carbon/high/medium/4` |
| `flash-lite-medium-1` | `medium:1` | `gemini-3.1-flash-lite` | `low` | `e02` (d6) | `yes` | `+0.83` | 570 | `$0.282205` | `ladder:ladder-v14:gemini-4-carbon/low/medium/1` |
| `flash-lite-medium-1` | `medium:1` | `gemini-3.1-flash-lite` | `high` | `none` (horizon) | `no` | `+0.00` | 83,162 | `$5.083245` | `ladder:ladder-v14:gemini-4-carbon/high/medium/1` |
| `hydrogen-hard-3` | `hard:3` | `gemini-4-hydrogen` | `low` | `e29` (d7) | `yes` | `+0.65` | 123 | `$0.340349` | `ladder:ladder-v14:gemini-4-carbon/low/hard/3` |
| `hydrogen-hard-3` | `hard:3` | `gemini-4-hydrogen` | `high` | `e29` (d8) | `yes` | `+0.68` | 60,941 | `$1.435737` | `ladder:ladder-v14:gemini-4-carbon/high/hard/3` |
| `flash38-medium-9` | `medium:9` | `gemini-3.8-flash` | `low` | `e15` (d9) | `yes` | `+0.61` | 621 | `$0.444088` | `ladder:ladder-v14:gemini-4-carbon/low/medium/9` |
| `flash38-medium-9` | `medium:9` | `gemini-3.8-flash` | `high` | `e15` (d8) | `yes` | `+0.69` | 44,121 | `$1.166486` | `ladder:ladder-v14:gemini-4-carbon/high/medium/9` |
| `flash35-hard-1` | `hard:1` | `gemini-3.5-flash` | `low` | `e33` (d17) | `yes` | `+0.29` | 467 | `$1.050836` | `ladder:ladder-v14:gemini-4-carbon/low/hard/1` |
| `flash35-hard-1` | `hard:1` | `gemini-3.5-flash` | `high` | `e33` (d9) | `yes` | `+0.71` | 40,681 | `$1.596177` | `ladder:ladder-v14:gemini-4-carbon/high/hard/1` |
| `argon-hard-18` | `hard:18` | `gemini-4-argon` | `high` | `e27` (d14) | `yes` | `+0.55` | 50,921 | `$6.743832` | `inproc:v1.4:gemini-4-carbon/hard/18` |
| `argon-medium-6` | `medium:6` | `gemini-4-argon` | `low` | `e17` (d9) | `yes` | `+0.63` | 1,041 | `$0.468401` | `ladder:ladder-v14:gemini-4-carbon/low/medium/6` |
| `argon-medium-6` | `medium:6` | `gemini-4-argon` | `high` | `e17` (d9) | `yes` | `+0.78` | 45,479 | `$1.292662` | `ladder:ladder-v14:gemini-4-carbon/high/medium/6` |
| `hydrogen-medium-2` | `medium:2` | `gemini-4-hydrogen` | `low` | `e09` (d5) | `yes` | `+0.80` | 48 | `$0.171707` | `ladder:ladder-v14:gemini-4-carbon/low/medium/2` |
| `hydrogen-medium-2` | `medium:2` | `gemini-4-hydrogen` | `high` | `e09` (d5) | `yes` | `+0.86` | 32,893 | `$0.741771` | `ladder:ladder-v14:gemini-4-carbon/high/medium/2` |
| `flash35-medium-8` | `medium:8` | `gemini-3.5-flash` | `low` | `e02` (d4) | `yes` | `+0.85` | 0 | `$0.138997` | `ladder:ladder-v14:gemini-4-carbon/low/medium/8` |
| `flash35-medium-8` | `medium:8` | `gemini-3.5-flash` | `high` | `e02` (d4) | `yes` | `+0.85` | 23,083 | `$0.502651` | `ladder:ladder-v14:gemini-4-carbon/high/medium/8` |

## 6. Deterministic Stopping Equations and Keyless Verification

- **Break-even accusation threshold:** Accusing suspect `s` at value `V_d` yields `+V_d` if `s == true_mole` and `-1.00` otherwise, so `EV(accuse s) = p(s) * V_d - (1 - p(s)) >= 0` if and only if `p(s) >= 1 / (1 + V_d)`.
- **Six deterministic UI / VM verdict labels (`demo/out-think-gemini/engine.js`):** `OPTIMAL ACCUSATION`, `OPTIMAL HOLD FIRE`, `CAUTIOUS HOLD FIRE`, `OVER-CAUTIOUS DELAY`, `LUCKY GUESS (BELOW BREAK-EVEN)`, and `FALSE ACCUSATION (-1.00)`.
- **Keyless regeneration and drift check (0 API calls):**
  - `GEMINI_API_KEY="" GOOGLE_API_KEY="" PYTHONPATH=. python -m canary.gemini.outthink --check`
  - `GEMINI_API_KEY="" GOOGLE_API_KEY="" PYTHONPATH=. python -m canary.gemini.outthink_casebook --write-doc`
  - `GEMINI_API_KEY="" GOOGLE_API_KEY="" PYTHONPATH=. python -m canary.gemini.outthink_casebook --check`
  - `GEMINI_API_KEY="" GOOGLE_API_KEY="" PYTHONPATH=. python -m canary.gemini.outthink_casebook --json`
