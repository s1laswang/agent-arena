# Canary v1.4 Mole-Archetype and Seed-Difficulty Stratified Gap Audit

Every figure in this report is deterministically computed on pure CPU by `scripts/frontier_mole_stratified_gap.py` from `Env(tier, seed)` world/mole attributes across `90` worlds (`medium 0-29`, `hard 0-29`, `hard 30-59`) and `14` stratified cohorts after full step-and-ledger replay verification of `472/472` committed `v1.4` episodes and `305/305` FR8 replication episodes (synced through `justSilas@5f9b3297`, `0` live API calls, `0` `.git` or subprocess runtime dependency).

**Complementary scope:** `docs/reports/failure_analysis_v1.4.md` decomposes within-episode agent decision mistakes on primary hard `seeds 0-29`, and `docs/reports/reference_optimality.md` establishes aggregate solver calibration and stopping optimality on dev `seeds 8000-9399`. This report addresses the orthogonal **across-seed structural and mole-archetype question**: (1) whether every mole archetype and department-anonymity stratum is reliably solvable by the Bayesian reference solver, and (2) which specific mole archetypes and world difficulty strata drive the luck-adjusted frontier gap across `gemini-4-carbon`, `gpt-5.5`, `gemini-3.5-flash`, and non-Bayesian baselines.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_mole_stratified_gap.py --check
```

## 1. Provenance Honesty (Panel Fixes A/C/D), Replay Integrity, and Headline Findings

- **Provenance & registration honesty (Panel Fixes A/C/D, synced to `justSilas@5f9b3297`):** Primary `seeds 0-29` (`data/runs/committed/v1.4/`, committed in `8fd4dec`) are governed by a **post-hoc lock** (`671ed96`, committed `28 s` after `8fd4dec`) against later reruns and cherry-picking, not a pre-registration (`20+10` solver reference split directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` (`f9fb7a4a`, `opencode-gemini-4-carbon-ext/hard`, `n=2`, completed `seeds [34, 37]` before stopping to preserve shared carbon quota for the Harbor rehearsal) and the second frontier family `gpt-5.5` (`cf394894`, shipped in `ca0a0dc0` at `data/runs/committed/v1.4/opencode-gpt-5.5/hard`, OpenCode `1.19.5`, `7200 s` per-episode cap, `$200` spend cap, `30` committed `v1.4` episodes with `0` infra exclusions and `2` clean `rc=0` non-accuse `final_day=0` exits on `seeds [0, 17]`) were **pre-registered** before any episode ran. Upstream submission tags: `afterquery-final` (`1bc3e281` code freeze), `afterquery-submit` (`9225f2ad` 08:52 `153%` snapshot on `7` trials), and `afterquery-submit-2` (`aa1c679e`) plus append-only CEO correction `5f9b3297` recording final Harbor rehearsal ratios `93%, 116%, 131%` across `10, 10, 9` valid trials (`s1-rehearsal-final` `d0ead011`, run 3 final `131%` on `9` valid trials superseding the 08:52 `153%` snapshot).
- **100% replay integrity (`1bc3e281` `norm_result` order):** `472/472` committed `v1.4` episodes and `305/305` FR8 replication episodes (`777/777` total) pass step-by-step and ledger replay with `0` mismatches and `0` duplicates, unwrapping OpenCode MCP error JSON first (`84` committed, `24` replication steps) before matching pre-`1bc3e281` `data={}` against live `data={'detail': ...}` (`321` committed, `156` replication steps) and verifying `2` clean `rc=0` non-accuse `final_day=0` exits (`seeds [0, 17]`).
- **Every mole archetype and department stratum is reliably solved by the reference solver:** Across all `60` hard worlds (`0-59`), the Bayesian reference solver achieves `93.3%` accuracy (`94.9%` precision when accusing, raw `+0.498`, luck-adjusted `+0.521`), with strongly positive luck-adjusted scores across every mole archetype (`+0.374` on `decoy_entangled`, `+0.525` and `100.0%` `13/13` accuracy on `deep_crowd_camouflage`, `+0.554` on `low_tempo_stealth`, `+0.567` on `high_tempo_exposed`) and every department-size stratum (`+0.559` compact, `+0.461` standard, `+0.554` and `100.0%` `11/11` accuracy on `crowded_dept`). On `medium 0-29`, the solver achieves `100.0%` precision when accusing (`0` wrong accusations, `3` calibrated abstentions).
- **Primary hard frontier gap is concentrated in crowded departments and low-tempo stealth moles, NOT decoy traps:** On primary hard `0-29`, OpenCode `gemini-4-carbon` trails the solver by `+0.140` V/episode luck-adjusted (`+0.177` raw). Stratification shows the gap is driven by **`deep_crowd_camouflage`** (`n=8`, luck-adjusted gap `+0.209`, raw gap `+0.389`, accuracy `75.0%` vs solver `100.0%`) and **`low_tempo_stealth`** (`n=10`, luck-adjusted gap `+0.208`), and structurally by **`crowded_dept`** (`mole_dept_size >= 11`, `n=7`, luck-adjusted gap `+0.253`, raw gap `+0.521`) and **`mid_horizon_isolation`** (`solver_day 9-12`, `n=10`, luck-adjusted gap `+0.228`). On `decoy_entangled` (`n=6`), `gemini-4-carbon` is not fooled by the angry-message decoy (luck-adjusted `+0.474` vs solver `+0.392`). By contrast, OpenCode `gpt-5.5` (`n=30`, raw `+0.504`, luck-adjusted `+0.418`, `83.7%` of solver luck-adjusted, `93.3%` accuracy) plants about 2 canaries/day and reaches `100.0%` accuracy on `deep_crowd_camouflage` (`n=8`, raw `+0.451`, luck-adjusted `+0.375`) and `100.0%` on `crowded_dept` (`n=7`, raw `+0.451`, luck-adjusted `+0.341`), while both of its clean `rc=0` non-accuse `final_day=0` prose stops (`seeds [0, 17]`) occur in `low_tempo_stealth` (`n=10`, abstain `20.0%`).
- **Extension hard `30-59` confirms both baseline scaling fragility and partial-cohort selection structure:** Across full `seeds 30-59` (`n=30`), `grok_tactics` suffers its largest luck-adjusted deficit on `deep_crowd_camouflage` (`+0.399` V/ep) while `heuristic` collapses on `low_tempo_stealth` (`+0.560` V/ep) and `deep_crowd_camouflage` (`+0.496` V/ep). Meanwhile, the deduplicated `6`-seed OpenCode `gemini-4-carbon` extension union (`seeds [30, 34, 37, 42, 45, 57]`, committed G1 precedence on shared `seed 34`: G1 raw `+0.790` / luck-adj `+0.752` vs FR8 raw `+0.820` / luck-adj `+0.183`) contains **`0/6` `deep_crowd_camouflage` seeds** and **`0/6` `crowded_dept` (`>=11`) seeds** (mean `mole_dept_size = 7.17` vs `9.07` on `hard 0-29` and `8.10` on `hard 30-59`), structurally explaining why early quota-constrained completions outperform the full-distribution primary benchmark.
- **`docs/reports/gap.md` hard-row gate (`gap_ships_flash_hard(root)`):** `opencode:google/gemini-3.5-flash` hard (`seeds 0-29`) is replay-verified inside `data/runs/committed/v1.4` (`472/472`) and gated out of primary hard tables here until `docs/reports/gap.md` ships it; FR8 `gemini-3.5-flash` medium (`seeds 0-29`, `n=30`) is reported in full below.

## 2. Deterministic World & Mole Policy Genome Extraction (90 Seeds)

In `canary/env.py`, standard `medium` and `hard` episodes (`tier not in TRACKS`) run `DEFAULT_STRATEGY` (`default_v0`: `0` conditional Mole DSL rules, `random_seeded` leak selector weighted by `careful_mole` `1 - share`, and Poisson framing), whereas evolved HoF DSL and RL policies apply on the `hard_forge` and `hard_rl` tracks. Because `p_single_dept_recipients = 0.0` on both `medium` (`4` depts, `20` staff) and `hard` (`5` depts, `40` staff), **100% of regular documents are sent to two whole departments**: regular document leaks narrow suspects down to `mole_dept`, after which **only canary variants** (and weak after-hours/interview LRs) can separate the `mole_dept_size` colleagues.

| seed block | n | mole policy | mean mole dept size | same-dept decoy seeds | mean decoy doc overlap | mean mole doc share | realized mole log density / day | mean passive leaks (expected) | archetype counts (`decoy` / `crowd` / `stealth` / `exposed`) | dept counts (`compact` / `standard` / `crowded`) |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|
| medium (0-29) | 30 | `default_v0` | 5.40 | 12/30 | 14.0 | 53.2% | 1.09 | 10.30 (10.50) | 12 / 6 / 7 / 5 | 7 / 15 / 8 |
| hard (0-29) | 30 | `default_v0` | 9.07 | 6/30 | 9.9 | 40.0% | 1.00 | 13.13 (13.65) | 6 / 8 / 10 / 6 | 13 / 10 / 7 |
| hard (30-59) | 30 | `default_v0` | 8.10 | 4/30 | 9.3 | 39.0% | 1.03 | 12.63 (13.65) | 4 / 5 / 13 / 8 | 13 / 13 / 4 |

Seed-intrinsic stratification rules (zero dependence on frontier trajectories):
- **`decoy_entangled`:** `same_dept_decoy == True` (`100%` regular-document overlap between mole and angry-message decoy, plus `50%` framed after-hours log share on the decoy).
- **`deep_crowd_camouflage`:** non-entangled mole in a department of size `>= floor(n_employees / n_depts) + 2` (`>= 7` on `medium`, `>= 10` on `hard`), requiring multi-round 3-variant canary splitting inside `mole_dept`.
- **`low_tempo_stealth`:** non-entangled mole in a compact/standard department with realized passive leaks `< n_days * p_leak` (`<= 10` on `medium`, `<= 13` on `hard`).
- **`high_tempo_exposed`:** non-entangled mole in a compact/standard department with realized passive leaks `>= n_days * p_leak` (`>= 11` on `medium`, `>= 14` on `hard`).

## 3. Primary Hard Seeds 0-29 Stratified Gap (Locked Headline Block)

### 3.1 By Realized Mole Behavioral Archetype

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver hard (0-29)** | **ALL** | 30 | +0.499 | +0.499 | +0.499 | n/a | n/a | 96.7% | 0.0% | 10.6 |
| reference solver hard (0-29) | `decoy_entangled` | 6 | +0.492 | +0.392 | +0.392 | n/a | n/a | 100.0% | 0.0% | 11.5 |
| reference solver hard (0-29) | `deep_crowd_camouflage` | 8 | +0.524 | +0.489 | +0.489 | n/a | n/a | 100.0% | 0.0% | 11.0 |
| reference solver hard (0-29) | `low_tempo_stealth` | 10 | +0.434 | +0.552 | +0.552 | n/a | n/a | 90.0% | 0.0% | 9.6 |
| reference solver hard (0-29) | `high_tempo_exposed` | 6 | +0.582 | +0.532 | +0.532 | n/a | n/a | 100.0% | 0.0% | 10.8 |
| **OpenCode gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.322 | +0.360 | +0.499 | +0.140 | 72.0% | 83.3% | 3.3% | 13.2 |
| OpenCode gemini-4-carbon hard (0-29) | `decoy_entangled` | 6 | +0.315 | +0.474 | +0.392 | -0.082 | 120.9% | 83.3% | 0.0% | 11.0 |
| OpenCode gemini-4-carbon hard (0-29) | `deep_crowd_camouflage` | 8 | +0.135 | +0.280 | +0.489 | +0.209 | 57.3% | 75.0% | 0.0% | 16.4 |
| OpenCode gemini-4-carbon hard (0-29) | `low_tempo_stealth` | 10 | +0.316 | +0.345 | +0.552 | +0.208 | 62.4% | 80.0% | 10.0% | 12.9 |
| OpenCode gemini-4-carbon hard (0-29) | `high_tempo_exposed` | 6 | +0.590 | +0.376 | +0.532 | +0.156 | 70.6% | 100.0% | 0.0% | 11.5 |
| **in-process gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.473 | +0.421 | +0.499 | +0.078 | 84.3% | 93.3% | 3.3% | 12.7 |
| in-process gemini-4-carbon hard (0-29) | `decoy_entangled` | 6 | +0.503 | +0.393 | +0.392 | -0.001 | 100.2% | 83.3% | 16.7% | 10.6 |
| in-process gemini-4-carbon hard (0-29) | `deep_crowd_camouflage` | 8 | +0.463 | +0.335 | +0.489 | +0.153 | 68.6% | 100.0% | 0.0% | 15.1 |
| in-process gemini-4-carbon hard (0-29) | `low_tempo_stealth` | 10 | +0.485 | +0.561 | +0.552 | -0.008 | 101.5% | 90.0% | 0.0% | 11.0 |
| in-process gemini-4-carbon hard (0-29) | `high_tempo_exposed` | 6 | +0.437 | +0.331 | +0.532 | +0.201 | 62.1% | 100.0% | 0.0% | 14.0 |
| **OpenCode gpt-5.5 hard (0-29)** | **ALL** | 30 | +0.504 | +0.418 | +0.499 | +0.082 | 83.7% | 93.3% | 6.7% | 10.2 |
| OpenCode gpt-5.5 hard (0-29) | `decoy_entangled` | 6 | +0.563 | +0.489 | +0.392 | -0.096 | 124.5% | 100.0% | 0.0% | 10.2 |
| OpenCode gpt-5.5 hard (0-29) | `deep_crowd_camouflage` | 8 | +0.451 | +0.375 | +0.489 | +0.114 | 76.7% | 100.0% | 0.0% | 11.2 |
| OpenCode gpt-5.5 hard (0-29) | `low_tempo_stealth` | 10 | +0.499 | +0.430 | +0.552 | +0.122 | 77.9% | 80.0% | 20.0% | 8.6 |
| OpenCode gpt-5.5 hard (0-29) | `high_tempo_exposed` | 6 | +0.522 | +0.383 | +0.532 | +0.149 | 72.0% | 100.0% | 0.0% | 11.2 |

### 3.2 By Mole Department Size & Solver Isolation Horizon

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver hard (0-29)** | **ALL** | 30 | +0.499 | +0.499 | +0.499 | n/a | n/a | 96.7% | 0.0% | 10.6 |
| reference solver hard (0-29) | `compact_dept` | 13 | +0.465 | +0.548 | +0.548 | n/a | n/a | 92.3% | 0.0% | 9.9 |
| reference solver hard (0-29) | `standard_dept` | 10 | +0.470 | +0.410 | +0.410 | n/a | n/a | 100.0% | 0.0% | 12.3 |
| reference solver hard (0-29) | `crowded_dept` | 7 | +0.603 | +0.537 | +0.537 | n/a | n/a | 100.0% | 0.0% | 9.4 |
| **OpenCode gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.322 | +0.360 | +0.499 | +0.140 | 72.0% | 83.3% | 3.3% | 13.2 |
| OpenCode gemini-4-carbon hard (0-29) | `compact_dept` | 13 | +0.414 | +0.413 | +0.548 | +0.135 | 75.4% | 84.6% | 7.7% | 11.5 |
| OpenCode gemini-4-carbon hard (0-29) | `standard_dept` | 10 | +0.372 | +0.343 | +0.410 | +0.067 | 83.8% | 90.0% | 0.0% | 13.7 |
| OpenCode gemini-4-carbon hard (0-29) | `crowded_dept` | 7 | +0.081 | +0.283 | +0.537 | +0.253 | 52.8% | 71.4% | 0.0% | 15.3 |
| **in-process gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.473 | +0.421 | +0.499 | +0.078 | 84.3% | 93.3% | 3.3% | 12.7 |
| in-process gemini-4-carbon hard (0-29) | `compact_dept` | 13 | +0.437 | +0.462 | +0.548 | +0.086 | 84.4% | 92.3% | 0.0% | 12.0 |
| in-process gemini-4-carbon hard (0-29) | `standard_dept` | 10 | +0.498 | +0.394 | +0.410 | +0.016 | 96.1% | 90.0% | 10.0% | 12.7 |
| in-process gemini-4-carbon hard (0-29) | `crowded_dept` | 7 | +0.504 | +0.383 | +0.537 | +0.153 | 71.4% | 100.0% | 0.0% | 14.0 |
| **OpenCode gpt-5.5 hard (0-29)** | **ALL** | 30 | +0.504 | +0.418 | +0.499 | +0.082 | 83.7% | 93.3% | 6.7% | 10.2 |
| OpenCode gpt-5.5 hard (0-29) | `compact_dept` | 13 | +0.472 | +0.404 | +0.548 | +0.144 | 73.8% | 84.6% | 15.4% | 9.8 |
| OpenCode gpt-5.5 hard (0-29) | `standard_dept` | 10 | +0.581 | +0.489 | +0.410 | -0.079 | 119.2% | 100.0% | 0.0% | 9.3 |
| OpenCode gpt-5.5 hard (0-29) | `crowded_dept` | 7 | +0.451 | +0.341 | +0.537 | +0.195 | 63.6% | 100.0% | 0.0% | 12.3 |

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver hard (0-29)** | **ALL** | 30 | +0.499 | +0.499 | +0.499 | n/a | n/a | 96.7% | 0.0% | 10.6 |
| reference solver hard (0-29) | `fast_isolation` | 11 | +0.699 | +0.651 | +0.651 | n/a | n/a | 100.0% | 0.0% | 6.5 |
| reference solver hard (0-29) | `mid_horizon_isolation` | 10 | +0.441 | +0.529 | +0.529 | n/a | n/a | 90.0% | 0.0% | 9.6 |
| reference solver hard (0-29) | `late_or_stalled_isolation` | 9 | +0.319 | +0.280 | +0.280 | n/a | n/a | 100.0% | 0.0% | 16.7 |
| **OpenCode gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.322 | +0.360 | +0.499 | +0.140 | 72.0% | 83.3% | 3.3% | 13.2 |
| OpenCode gemini-4-carbon hard (0-29) | `fast_isolation` | 11 | +0.293 | +0.530 | +0.651 | +0.122 | 81.3% | 81.8% | 0.0% | 12.5 |
| OpenCode gemini-4-carbon hard (0-29) | `mid_horizon_isolation` | 10 | +0.354 | +0.301 | +0.529 | +0.228 | 56.9% | 80.0% | 10.0% | 12.1 |
| OpenCode gemini-4-carbon hard (0-29) | `late_or_stalled_isolation` | 9 | +0.323 | +0.216 | +0.280 | +0.064 | 77.1% | 88.9% | 0.0% | 15.1 |
| **in-process gemini-4-carbon hard (0-29)** | **ALL** | 30 | +0.473 | +0.421 | +0.499 | +0.078 | 84.3% | 93.3% | 3.3% | 12.7 |
| in-process gemini-4-carbon hard (0-29) | `fast_isolation` | 11 | +0.418 | +0.490 | +0.651 | +0.161 | 75.3% | 81.8% | 9.1% | 11.0 |
| in-process gemini-4-carbon hard (0-29) | `mid_horizon_isolation` | 10 | +0.445 | +0.341 | +0.529 | +0.188 | 64.5% | 100.0% | 0.0% | 14.6 |
| in-process gemini-4-carbon hard (0-29) | `late_or_stalled_isolation` | 9 | +0.571 | +0.425 | +0.280 | -0.145 | 151.6% | 100.0% | 0.0% | 12.4 |
| **OpenCode gpt-5.5 hard (0-29)** | **ALL** | 30 | +0.504 | +0.418 | +0.499 | +0.082 | 83.7% | 93.3% | 6.7% | 10.2 |
| OpenCode gpt-5.5 hard (0-29) | `fast_isolation` | 11 | +0.528 | +0.485 | +0.651 | +0.167 | 74.4% | 90.9% | 9.1% | 9.3 |
| OpenCode gpt-5.5 hard (0-29) | `mid_horizon_isolation` | 10 | +0.471 | +0.329 | +0.529 | +0.200 | 62.2% | 90.0% | 10.0% | 11.4 |
| OpenCode gpt-5.5 hard (0-29) | `late_or_stalled_isolation` | 9 | +0.510 | +0.435 | +0.280 | -0.154 | 155.1% | 100.0% | 0.0% | 10.1 |

## 4. Primary + FR8 Medium Seeds 0-29 Stratified Gap

On `medium` (`seeds 0-29`, `n=30`), OpenCode `gemini-4-carbon` achieves `100.0%` accuracy across all four mole archetypes (`+0.652` luck-adjusted vs solver `+0.645`), whereas FR8 OpenCode `gemini-3.5-flash` (`+0.485` luck-adjusted, gap `+0.160`) collapses specifically on `low_tempo_stealth` (`n=7`, accuracy `57.1%`, luck-adjusted `-0.011`, gap `+0.650`), and in-process `gemini-4-carbon` (`+0.479` luck-adjusted) drops most in `crowded_dept` (`>= 7` colleagues, luck-adjusted gap `+0.244`):

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver medium (0-29)** | **ALL** | 30 | +0.645 | +0.645 | +0.645 | n/a | n/a | 90.0% | 10.0% | 7.6 |
| reference solver medium (0-29) | `decoy_entangled` | 12 | +0.698 | +0.698 | +0.698 | n/a | n/a | 91.7% | 8.3% | 6.4 |
| reference solver medium (0-29) | `deep_crowd_camouflage` | 6 | +0.572 | +0.572 | +0.572 | n/a | n/a | 83.3% | 16.7% | 8.4 |
| reference solver medium (0-29) | `low_tempo_stealth` | 7 | +0.639 | +0.639 | +0.639 | n/a | n/a | 85.7% | 14.3% | 7.2 |
| reference solver medium (0-29) | `high_tempo_exposed` | 5 | +0.616 | +0.616 | +0.616 | n/a | n/a | 100.0% | 0.0% | 9.8 |
| **OpenCode gemini-4-carbon medium (0-29)** | **ALL** | 30 | +0.713 | +0.652 | +0.645 | -0.007 | 101.1% | 100.0% | 0.0% | 8.0 |
| OpenCode gemini-4-carbon medium (0-29) | `decoy_entangled` | 12 | +0.773 | +0.721 | +0.698 | -0.024 | 103.4% | 100.0% | 0.0% | 7.0 |
| OpenCode gemini-4-carbon medium (0-29) | `deep_crowd_camouflage` | 6 | +0.647 | +0.553 | +0.572 | +0.018 | 96.8% | 100.0% | 0.0% | 9.5 |
| OpenCode gemini-4-carbon medium (0-29) | `low_tempo_stealth` | 7 | +0.687 | +0.594 | +0.639 | +0.044 | 93.1% | 100.0% | 0.0% | 8.3 |
| OpenCode gemini-4-carbon medium (0-29) | `high_tempo_exposed` | 5 | +0.684 | +0.684 | +0.616 | -0.068 | 111.0% | 100.0% | 0.0% | 8.0 |
| **in-process gemini-4-carbon medium (0-29)** | **ALL** | 30 | +0.530 | +0.479 | +0.645 | +0.166 | 74.3% | 83.3% | 13.3% | 9.0 |
| in-process gemini-4-carbon medium (0-29) | `decoy_entangled` | 12 | +0.517 | +0.462 | +0.698 | +0.236 | 66.2% | 83.3% | 8.3% | 8.5 |
| in-process gemini-4-carbon medium (0-29) | `deep_crowd_camouflage` | 6 | +0.507 | +0.507 | +0.572 | +0.065 | 88.6% | 83.3% | 16.7% | 10.6 |
| in-process gemini-4-carbon medium (0-29) | `low_tempo_stealth` | 7 | +0.534 | +0.410 | +0.639 | +0.229 | 64.1% | 85.7% | 14.3% | 9.8 |
| in-process gemini-4-carbon medium (0-29) | `high_tempo_exposed` | 5 | +0.586 | +0.586 | +0.616 | +0.030 | 95.1% | 80.0% | 20.0% | 7.5 |
| **OpenCode gemini-3.5-flash medium (0-29)** | **ALL** | 30 | +0.434 | +0.485 | +0.645 | +0.160 | 75.2% | 83.3% | 0.0% | 9.0 |
| OpenCode gemini-3.5-flash medium (0-29) | `decoy_entangled` | 12 | +0.473 | +0.592 | +0.698 | +0.106 | 84.8% | 83.3% | 0.0% | 7.8 |
| OpenCode gemini-3.5-flash medium (0-29) | `deep_crowd_camouflage` | 6 | +0.723 | +0.723 | +0.572 | -0.152 | 126.5% | 100.0% | 0.0% | 8.0 |
| OpenCode gemini-3.5-flash medium (0-29) | `low_tempo_stealth` | 7 | -0.026 | -0.011 | +0.639 | +0.650 | -1.8% | 57.1% | 0.0% | 11.3 |
| OpenCode gemini-3.5-flash medium (0-29) | `high_tempo_exposed` | 5 | +0.638 | +0.638 | +0.616 | -0.022 | 103.6% | 100.0% | 0.0% | 10.0 |

## 5. Extension Hard Seeds 30-59: Reference, Baselines, G1, FR8, and 6-Seed Union

Extension cohorts on `hard` (`seeds 30-59`) pair `solver` (`n=30`), `grok_tactics` (`n=30`), and `heuristic` (`n=30`) on all 30 seeds, alongside pre-registered G1 `opencode-gemini-4-carbon-ext` (`seeds [34, 37]`, `n=2`), FR8 `opencode:google/gemini-4-carbon` replication (`seeds [30, 34, 42, 45, 57]`, `n=5`), and their deduplicated `6`-seed union (`seeds [30, 34, 37, 42, 45, 57]`, `n=6`, committed G1 precedence on `seed 34`), each paired against the exact same seeds in `solver_hard_30_59`:

### 5.1 Extension Hard 30-59 by Mole Archetype

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver hard (30-59)** | **ALL** | 30 | +0.498 | +0.542 | +0.542 | n/a | n/a | 90.0% | 3.3% | 8.4 |
| reference solver hard (30-59) | `decoy_entangled` | 4 | +0.095 | +0.346 | +0.346 | n/a | n/a | 50.0% | 25.0% | 9.7 |
| reference solver hard (30-59) | `deep_crowd_camouflage` | 5 | +0.626 | +0.583 | +0.583 | n/a | n/a | 100.0% | 0.0% | 8.6 |
| reference solver hard (30-59) | `low_tempo_stealth` | 13 | +0.477 | +0.555 | +0.555 | n/a | n/a | 92.3% | 0.0% | 8.8 |
| reference solver hard (30-59) | `high_tempo_exposed` | 8 | +0.654 | +0.593 | +0.593 | n/a | n/a | 100.0% | 0.0% | 7.2 |
| **grok_tactics hard (30-59)** | **ALL** | 30 | +0.314 | +0.321 | +0.542 | +0.221 | 59.2% | 83.3% | 13.3% | 11.1 |
| grok_tactics hard (30-59) | `decoy_entangled` | 4 | +0.228 | +0.207 | +0.346 | +0.139 | 59.8% | 75.0% | 25.0% | 12.3 |
| grok_tactics hard (30-59) | `deep_crowd_camouflage` | 5 | +0.238 | +0.183 | +0.583 | +0.399 | 31.5% | 80.0% | 20.0% | 14.2 |
| grok_tactics hard (30-59) | `low_tempo_stealth` | 13 | +0.345 | +0.405 | +0.555 | +0.150 | 72.9% | 84.6% | 7.7% | 9.1 |
| grok_tactics hard (30-59) | `high_tempo_exposed` | 8 | +0.356 | +0.327 | +0.593 | +0.265 | 55.2% | 87.5% | 12.5% | 12.1 |
| **heuristic hard (30-59)** | **ALL** | 30 | +0.118 | +0.062 | +0.542 | +0.480 | 11.4% | 86.7% | 0.0% | 15.6 |
| heuristic hard (30-59) | `decoy_entangled` | 4 | +0.280 | +0.054 | +0.346 | +0.292 | 15.5% | 100.0% | 0.0% | 14.5 |
| heuristic hard (30-59) | `deep_crowd_camouflage` | 5 | +0.026 | +0.087 | +0.583 | +0.496 | 14.9% | 80.0% | 0.0% | 15.4 |
| heuristic hard (30-59) | `low_tempo_stealth` | 13 | -0.006 | -0.005 | +0.555 | +0.560 | -0.9% | 76.9% | 0.0% | 15.7 |
| heuristic hard (30-59) | `high_tempo_exposed` | 8 | +0.295 | +0.159 | +0.593 | +0.434 | 26.8% | 100.0% | 0.0% | 16.1 |
| **OpenCode gemini-4-carbon hard G1 ext (34,37)** | **ALL** | 2 | +0.745 | +0.710 | +0.649 | -0.061 | 109.4% | 100.0% | 0.0% | 5.5 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `decoy_entangled` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `deep_crowd_camouflage` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `low_tempo_stealth` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `high_tempo_exposed` | 2 | +0.745 | +0.710 | +0.649 | -0.061 | 109.4% | 100.0% | 0.0% | 5.5 |
| **OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)** | **ALL** | 5 | +0.656 | +0.472 | +0.430 | -0.042 | 109.6% | 100.0% | 0.0% | 11.0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `decoy_entangled` | 1 | +0.540 | +0.400 | +0.175 | -0.224 | 227.9% | 100.0% | 0.0% | 11.0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `deep_crowd_camouflage` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `low_tempo_stealth` | 3 | +0.640 | +0.592 | +0.438 | -0.154 | 135.2% | 100.0% | 0.0% | 12.0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `high_tempo_exposed` | 1 | +0.820 | +0.183 | +0.663 | +0.480 | 27.6% | 100.0% | 0.0% | 8.0 |
| **OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34)** | **ALL** | 6 | +0.658 | +0.599 | +0.464 | -0.135 | 129.0% | 100.0% | 0.0% | 9.7 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `decoy_entangled` | 1 | +0.540 | +0.400 | +0.175 | -0.224 | 227.9% | 100.0% | 0.0% | 11.0 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `deep_crowd_camouflage` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `low_tempo_stealth` | 3 | +0.640 | +0.592 | +0.438 | -0.154 | 135.2% | 100.0% | 0.0% | 12.0 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `high_tempo_exposed` | 2 | +0.745 | +0.710 | +0.649 | -0.061 | 109.4% | 100.0% | 0.0% | 5.5 |

### 5.2 Extension Hard 30-59 by Mole Department Size Stratum

| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **reference solver hard (30-59)** | **ALL** | 30 | +0.498 | +0.542 | +0.542 | n/a | n/a | 90.0% | 3.3% | 8.4 |
| reference solver hard (30-59) | `compact_dept` | 13 | +0.402 | +0.571 | +0.571 | n/a | n/a | 84.6% | 0.0% | 8.2 |
| reference solver hard (30-59) | `standard_dept` | 13 | +0.559 | +0.500 | +0.500 | n/a | n/a | 92.3% | 7.7% | 8.6 |
| reference solver hard (30-59) | `crowded_dept` | 4 | +0.613 | +0.584 | +0.584 | n/a | n/a | 100.0% | 0.0% | 8.5 |
| **grok_tactics hard (30-59)** | **ALL** | 30 | +0.314 | +0.321 | +0.542 | +0.221 | 59.2% | 83.3% | 13.3% | 11.1 |
| grok_tactics hard (30-59) | `compact_dept` | 13 | +0.452 | +0.419 | +0.571 | +0.151 | 73.5% | 76.9% | 23.1% | 8.4 |
| grok_tactics hard (30-59) | `standard_dept` | 13 | +0.196 | +0.262 | +0.500 | +0.237 | 52.5% | 92.3% | 0.0% | 12.4 |
| grok_tactics hard (30-59) | `crowded_dept` | 4 | +0.250 | +0.190 | +0.584 | +0.395 | 32.5% | 75.0% | 25.0% | 14.3 |
| **heuristic hard (30-59)** | **ALL** | 30 | +0.118 | +0.062 | +0.542 | +0.480 | 11.4% | 86.7% | 0.0% | 15.6 |
| heuristic hard (30-59) | `compact_dept` | 13 | +0.326 | +0.197 | +0.571 | +0.374 | 34.5% | 100.0% | 0.0% | 14.7 |
| heuristic hard (30-59) | `standard_dept` | 13 | -0.048 | -0.071 | +0.500 | +0.571 | -14.2% | 76.9% | 0.0% | 16.5 |
| heuristic hard (30-59) | `crowded_dept` | 4 | -0.022 | +0.055 | +0.584 | +0.530 | 9.3% | 75.0% | 0.0% | 15.5 |
| **OpenCode gemini-4-carbon hard G1 ext (34,37)** | **ALL** | 2 | +0.745 | +0.710 | +0.649 | -0.061 | 109.4% | 100.0% | 0.0% | 5.5 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `compact_dept` | 2 | +0.745 | +0.710 | +0.649 | -0.061 | 109.4% | 100.0% | 0.0% | 5.5 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `standard_dept` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | `crowded_dept` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| **OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)** | **ALL** | 5 | +0.656 | +0.472 | +0.430 | -0.042 | 109.6% | 100.0% | 0.0% | 11.0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `compact_dept` | 2 | +0.680 | +0.291 | +0.419 | +0.128 | 69.5% | 100.0% | 0.0% | 9.5 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `standard_dept` | 3 | +0.640 | +0.592 | +0.438 | -0.154 | 135.2% | 100.0% | 0.0% | 12.0 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | `crowded_dept` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| **OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34)** | **ALL** | 6 | +0.658 | +0.599 | +0.464 | -0.135 | 129.0% | 100.0% | 0.0% | 9.7 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `compact_dept` | 3 | +0.677 | +0.607 | +0.491 | -0.115 | 123.5% | 100.0% | 0.0% | 7.3 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `standard_dept` | 3 | +0.640 | +0.592 | +0.438 | -0.154 | 135.2% | 100.0% | 0.0% | 12.0 |
| OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34) | `crowded_dept` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## 6. Pooled Hard 0-59 Reference Solver Solvability Proof (n=60)

| pooled hard 0-59 stratum | n | solver raw score | solver luck-adj. score | solver accuracy | precision when accusing | abstention rate | mean accuse day |
|---|---:|---:|---:|---:|---:|---:|---:|
| mole archetype: `decoy_entangled` | 10 | +0.333 | +0.374 | 80.0% | 88.9% | 10.0% | 10.9 |
| mole archetype: `deep_crowd_camouflage` | 13 | +0.563 | +0.525 | 100.0% | 100.0% | 0.0% | 10.1 |
| mole archetype: `low_tempo_stealth` | 23 | +0.458 | +0.554 | 91.3% | 91.3% | 0.0% | 9.1 |
| mole archetype: `high_tempo_exposed` | 14 | +0.623 | +0.567 | 100.0% | 100.0% | 0.0% | 8.8 |
| dept size: `compact_dept` | 26 | +0.433 | +0.559 | 88.5% | 88.5% | 0.0% | 9.1 |
| dept size: `standard_dept` | 23 | +0.520 | +0.461 | 95.7% | 100.0% | 4.3% | 10.3 |
| dept size: `crowded_dept` | 11 | +0.606 | +0.554 | 100.0% | 100.0% | 0.0% | 9.1 |

Conclusion: across all `60` evaluated hard worlds (`0-59`) and `30` medium worlds (`0-29`), no mole archetype or department stratum is broken or unsolvable. The Bayesian reference solver maintains `+0.374` to `+0.567` luck-adjusted value across every hard mole archetype (`100.0%` accuracy on all `13/13` `deep_crowd_camouflage` worlds and `100.0%` on all `11/11` `crowded_dept` worlds), whereas frontier models that under-invest daily actions in `plant_canary` lose posterior resolution precisely where intra-departmental anonymity pools (`>= 10-14` staff) or below-average leak tempo (`low_tempo_stealth`) demand sustained multi-canary bisection.
