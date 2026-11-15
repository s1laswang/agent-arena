# Adaptive Gemini Mole (`gemini-4-carbon`): Keyless Strategy Replay & Behavioral Equivalence Audit

Every metric, behavioral signature, and table cell in this report is computed deterministically offline (`0` Gemini API calls) from committed `results/gemini/roles_carbon/adaptive_mole` artifacts by `python -m canary.gemini.mole_replay_audit --require-populated`.

## Scope & Verification Gates

1. **Scope (`arena mode, not the judged v1.4 environment`):** All `14` audited DSL strategy runs (`4` `mole_forge` Hall-of-Fame runs and `10` `paired_designer` scenario runs) operate in **arena mode, not the judged v1.4 environment**, replayed strictly on public dev seeds `[0, 1, 2, 3, 4]` (`JUDGE_SEEDS` explicitly blocked by `validate_dev_seeds`). The judged Canary `v1.4` benchmark (`a8f99c2537c91d72`) uses frozen scripted moles only and is untouched.
2. **Double-replay determinism gate (`deterministic_ok`):** Every top `MoleStrategy` is executed twice from scratch in `Env(tier, seed, mole_strategy=...)` against `SolverPolicy` and twice against `ObviousHeuristic(seed=seed)` (`70` `(run, seed)` pairs per policy, `280` total `Env` episodes), requiring exact equality of episode scores, accusation verdicts, server-ledger leak counts, and full step-by-step tool histories.
3. **Non-silent leak & catchability gates (`leaks_ok`, `catchable_ok`):** Each strategy must trigger `total_leak_count >= 1` on the server ledger against `SolverPolicy` (`min_seed_leak_count >= 2` across all `14` runs, ruling out silent-mole degeneracies) and strictly separate `SolverPolicy` above `ObviousHeuristic` (`solver_mean_score` exceeds `obvious_mean_score` on `14/14` runs).
4. **Privileged-state isolation gate (`mole_view_clean_ok`):** `_MoleViewRecorder` intercepts every live `MoleView` passed to `MoleStrategy.decide()` (`1,034` live `MoleView` snapshots across `14` runs) and `check_mole_view_privileges` enforces the `11`-field `MoleView` allowlist and `4`-field `MoleDoc` allowlist against `20` forbidden privileged identifiers (`is_canary`, `variant`, `posterior`, `belief`, `true_mole`, `world_seed`, `salt`, `ledger`, `secret`, and related keys) plus structured JSON payload scans, confirming `0` violations.

## Headline Replay & Equivalence Summary

- **Populated DSL strategy runs audited:** `14` (`4` `mole_forge`, `10` `paired_designer`), **`14/14` (`100.00%`) `PASS`**.
- **Deterministic replay coverage (`seeds = [0, 1, 2, 3, 4]`):** `70` unique `(run, seed)` pairs per investigator policy (`280` total `Env` episodes across double-replay determinism checks), `0` Gemini API calls.
- **Solvability & catchability separation (`n=14` top strategies):** `SolverPolicy` achieves **`+0.6114`** mean score and **`97.14%`** (`68/70`) catch accuracy vs `ObviousHeuristic` **`-0.8337`** mean score and **`8.57%`** (`6/70`) catch accuracy, yielding **`+1.4451`** mean catchability margin (`382` solver-episode leaks, `360` heuristic-episode leaks).
- **Privileged-state isolation (`check_mole_view_privileges`):** **`1,034`** live replay `MoleView` snapshots (`260` `mole_forge` + `774` `paired_designer`) and **`2,163`** synthetic probe `MoleView` states verified with **`0`** privileged-field violations.
- **All-strategy behavioral equivalence (`n=106` loaded strategies):** `57` `mole_forge` Hall-of-Fame strategies + `49` `paired_designer` kept strategies = **`106`** total `MoleStrategy` entries, **`105`** syntactically unique canonical JSON definitions, and **`93`** distinct behavioral equivalence classes (`87` singletons + `6` multi-member classes) across `2,163` synthetic `MoleView` probe states under two fixed RNG streams (`104729`, `130363`).
- **Top-strategy behavioral equivalence (`n=14` run winners):** `14` syntactically unique top strategies map to **`13`** distinct behavioral equivalence classes (`12` singletons + `1` cross-tier behavioral convergence pair `fd22f2b13cb0920e`).

## 1. Aggregate Replay Slices (`source_kind` and `tier`)

### By Source Kind

| Source Kind | Runs | Loaded Entries | Episodes / Policy | Solver Mean | Solver Acc | Obvious Mean | Obvious Acc | Mean Margin | Solver Leaks | Obvious Leaks | Live Views | Violations | Pass Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `mole_forge` | 4 | 57 | 20 | +0.5900 | 100.00% | -0.7090 | 15.00% | +1.2990 | 126 | 59 | 260 | 0 | 4/4 |
| `paired_designer` | 10 | 49 | 50 | +0.6200 | 96.00% | -0.8836 | 6.00% | +1.5036 | 256 | 301 | 774 | 0 | 10/10 |
| `overall` | 14 | 106 | 70 | +0.6114 | 97.14% | -0.8337 | 8.57% | +1.4451 | 382 | 360 | 1034 | 0 | 14/14 |

### By Difficulty Tier

| Tier | Runs | Loaded Entries | Episodes / Policy | Solver Mean | Solver Acc | Obvious Mean | Obvious Acc | Mean Margin | Solver Leaks | Obvious Leaks | Live Views | Violations | Pass Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `easy` | 3 | 32 | 15 | +0.6800 | 100.00% | -0.2240 | 40.00% | +0.9040 | 76 | 36 | 136 | 0 | 3/3 |
| `medium` | 5 | 27 | 25 | +0.7496 | 100.00% | -1.0000 | 0.00% | +1.7496 | 120 | 186 | 396 | 0 | 5/5 |
| `hard` | 6 | 47 | 30 | +0.4620 | 93.33% | -1.0000 | 0.00% | +1.4620 | 186 | 138 | 502 | 0 | 6/6 |
| `overall` | 14 | 106 | 70 | +0.6114 | 97.14% | -0.8337 | 8.57% | +1.4451 | 382 | 360 | 1034 | 0 | 14/14 |

## 2. Per-Run Deterministic Replay & Privilege Audit (`seeds = 0..4`)

| Run Folder | Source Kind | Tier | Top Strategy Label | Entries | Solver Mean | Solver Acc | Obvious Mean | Obvious Acc | Margin | Solver Leaks | Min Seed Leaks | Obvious Leaks | Live Views | Behavioral Sig | Status |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-easy-deep` | `mole_forge` | `easy` | `rank_1` | 20 | +0.6160 | 100.00% | +0.1640 | 60.00% | +0.4520 | 29 | 3 | 5 | 52 | `70cd234e43d5d085` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-hard-deep` | `mole_forge` | `hard` | `rank_1` | 20 | +0.4900 | 100.00% | -1.0000 | 0.00% | +1.4900 | 37 | 4 | 8 | 65 | `3bee53e24ac8d7a4` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-med-deep` | `mole_forge` | `medium` | `rank_1` | 13 | +0.7400 | 100.00% | -1.0000 | 0.00% | +1.7400 | 25 | 2 | 38 | 80 | `6e0da8b669452ea5` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-v14` | `mole_forge` | `hard` | `rank_1` | 4 | +0.5140 | 100.00% | -1.0000 | 0.00% | +1.5140 | 35 | 4 | 8 | 63 | `d6494acd5dd676bc` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-designer-carbon` | `paired_designer` | `medium` | `pile-on-restricted-peers` | 3 | +0.7100 | 100.00% | -1.0000 | 0.00% | +1.7100 | 28 | 2 | 38 | 83 | `6f01b1be17f381f2` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-designer-carbon-hard` | `paired_designer` | `hard` | `phased-frame-shift-seeded` | 6 | +0.5800 | 100.00% | -1.0000 | 0.00% | +1.5800 | 29 | 2 | 30 | 96 | `66437aa965c5994f` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s10_14` | `paired_designer` | `easy` | `patient_frame_rotator` | 6 | +0.6220 | 100.00% | -0.6120 | 20.00% | +1.2340 | 31 | 2 | 15 | 49 | `8382c5ac77980325` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s15_19` | `paired_designer` | `easy` | `canary_cautious_framer` | 6 | +0.8020 | 100.00% | -0.2240 | 40.00% | +1.0260 | 16 | 2 | 16 | 35 | `fd22f2b13cb0920e` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard` | `paired_designer` | `hard` | `rotating_blame_sprinter` | 6 | +0.5400 | 100.00% | -1.0000 | 0.00% | +1.5400 | 33 | 2 | 30 | 96 | `653e85a391c260c8` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard-s10_14` | `paired_designer` | `hard` | `adaptive_heat_deflector` | 5 | +0.3240 | 80.00% | -1.0000 | 0.00% | +1.3240 | 26 | 2 | 31 | 91 | `fd22f2b13cb0920e` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard-s15_19` | `paired_designer` | `hard` | `scattered_blame_blitz` | 6 | +0.3240 | 80.00% | -1.0000 | 0.00% | +1.3240 | 26 | 2 | 31 | 91 | `3a0524534e0cca80` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s10_14` | `paired_designer` | `medium` | `paced_cadence_framer` | 6 | +0.8020 | 100.00% | -1.0000 | 0.00% | +1.8020 | 19 | 3 | 34 | 73 | `29d0663ec0344e4d` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s15_19` | `paired_designer` | `medium` | `canary_wary_scapegoater` | 2 | +0.7560 | 100.00% | -1.0000 | 0.00% | +1.7560 | 23 | 2 | 38 | 80 | `5203d949d2ba1943` | `PASS` |
| `results/gemini/roles_carbon/adaptive_mole/paired-solvable-scenarios-carbon` | `paired_designer` | `medium` | `high_tempo_frame_rotator` | 3 | +0.7400 | 100.00% | -1.0000 | 0.00% | +1.7400 | 25 | 2 | 38 | 80 | `dbf90d68efe62971` | `PASS` |

## 3. Behavioral Equivalence Deduplication (`2,163` Synthetic `MoleView` States)

Syntactic JSON uniqueness overstates policy diversity whenever two DSL rule lists differ only by unreachable predicates (such as `days_since_last_leak == 0` when day-start `days_since_last_leak` is at least `1`), shadowed fallthrough clauses, or commuting disjoint rules. `behavioral_signature` evaluates each `MoleStrategy` across `2,163` deterministic synthetic `MoleView` states spanning days `1..21`, recipient counts `1..9`, restriction counts, decoy availability, and open/closed leak gates under two fixed RNG seeds (`104729` and `130363`), hashing the `(leak, frame)` decision stream with SHA-256.

| Strategy Pool | Total Entries | Syntactic Unique JSON | Behavioral Equivalence Classes | Singleton Classes | Multi-Member Classes | Synthetic Probe Views |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_strategies` | 106 | 105 | 93 | 87 | 6 | 2163 |
| `top_strategies` | 14 | 14 | 13 | 12 | 1 | 2163 |

### Multi-Member Behavioral Equivalence Classes (`all_strategies`)

| Behavioral Sig | Members | Source Kinds | Representative Run | Representative Label | Algebraic Cause |
| --- | ---: | --- | --- | --- | --- |
| `f736a50831cf9c1d` | 8 | `paired_designer` | `paired-skill-designer-carbon-easy-s10_14` | `decoy_scapegoat_pivot` | Unreachable `days_since_last_leak == 0` guards and redundant decoy fallthroughs collapse to `n_restricted_colleagues >= 1` framing `most_restricted_peer` else `decoy` |
| `a104f7a7d3c777b5` | 3 | `paired_designer` | `paired-skill-designer-carbon-easy-s10_14` | `canary_cautious_framer` | Unreachable day-start `days_since_last_leak == 0` or sub-unit guards collapse to `n_restricted_colleagues >= 2` framing `most_restricted_peer` else `decoy` |
| `70cd234e43d5d085` | 2 | `mole_forge` | `mole-forge-carbon-easy-deep` | `rank_1` | Rules 2 and 3 (`rank_1` vs `rank_3`) commute on disjoint state support after Rule 1 handles `i_am_restricted == 1` with `days_since_last_leak` under `3` before day `12` |
| `a3c51c44288cb5cc` | 2 | `mole_forge` | `mole-forge-carbon-med-deep` | `rank_10` | Exact canonical baseline rule recurrence (`mole-forge-carbon-med-deep` `rank_10` and `mole-forge-carbon-v14` `rank_3`: empty rule list with `random_seeded` and `none` default) |
| `fd22f2b13cb0920e` | 2 | `paired_designer` | `paired-skill-designer-carbon-easy-s15_19` | `canary_cautious_framer` | Sole top-strategy convergence (`easy-s15_19` `canary_cautious_framer` and `hard-s10_14` `adaptive_heat_deflector`): `i_am_restricted == 1` frames `most_restricted_peer` else `decoy` |
| `8116c33c8422fd0d` | 2 | `paired_designer` | `paired-skill-designer-carbon-hard-s10_14` | `high_tempo_decoy_flood` | Complement day-threshold inversion (`day <= 7` early decoy flood vs `day >= 8` late pivot to `most_restricted_peer` or `random_peer`) yields identical decisions on integer days |

## 4. Verbatim CLI Summary & Keyless Reproduction

```bash
GEMINI_API_KEY="" GOOGLE_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.mole_replay_audit --require-populated
GEMINI_API_KEY="" GOOGLE_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_mole_replay_audit.py tests/test_gemini_lab_mole_replay_doc.py
```

```text
run_id                                   kind             tier     solver  obvious  leaks  views sig              status
------------------------------------------------------------------------------------------------------------------------
mole-forge-carbon-easy-deep              mole_forge       easy     +0.616   +0.164     29     52 70cd234e43d5d085 PASS
mole-forge-carbon-hard-deep              mole_forge       hard     +0.490   -1.000     37     65 3bee53e24ac8d7a4 PASS
mole-forge-carbon-med-deep               mole_forge       medium   +0.740   -1.000     25     80 6e0da8b669452ea5 PASS
mole-forge-carbon-v14                    mole_forge       hard     +0.514   -1.000     35     63 d6494acd5dd676bc PASS
paired-designer-carbon                   paired_designer  medium   +0.710   -1.000     28     83 6f01b1be17f381f2 PASS
paired-designer-carbon-hard              paired_designer  hard     +0.580   -1.000     29     96 66437aa965c5994f PASS
paired-skill-designer-carbon-easy-s10_14 paired_designer  easy     +0.622   -0.612     31     49 8382c5ac77980325 PASS
paired-skill-designer-carbon-easy-s15_19 paired_designer  easy     +0.802   -0.224     16     35 fd22f2b13cb0920e PASS
paired-skill-designer-carbon-hard        paired_designer  hard     +0.540   -1.000     33     96 653e85a391c260c8 PASS
paired-skill-designer-carbon-hard-s10_14 paired_designer  hard     +0.324   -1.000     26     91 fd22f2b13cb0920e PASS
paired-skill-designer-carbon-hard-s15_19 paired_designer  hard     +0.324   -1.000     26     91 3a0524534e0cca80 PASS
paired-skill-designer-carbon-med-s10_14  paired_designer  medium   +0.802   -1.000     19     73 29d0663ec0344e4d PASS
paired-skill-designer-carbon-med-s15_19  paired_designer  medium   +0.756   -1.000     23     80 5203d949d2ba1943 PASS
paired-solvable-scenarios-carbon         paired_designer  medium   +0.740   -1.000     25     80 dbf90d68efe62971 PASS
runs=14 (mole_forge=4, paired_designer=10) all_strategies_classes=93/106 top_strategies_classes=13/14 all_passed=True
```
