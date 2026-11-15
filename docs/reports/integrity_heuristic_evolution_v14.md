# Evolutionary Non-Bayesian Heuristic Search, Effort Ladder, and Determinism Audit (`justSilas@58716742`)

## 1. Headline Summary

- **Target & Scope:** Large-scale evolutionary search over non-Bayesian elimination/strike heuristics (`Part A`), partial-play and early-stopping effort ladder on `hard_forge` and `hard_rl` (`Part B`), and cross-process `PYTHONHASHSEED` invariance plus sequential seed autocorrelation and `JUDGE_SEEDS` boundary forensics (`Part C`) on Canary `v1.4` (`justSilas@58716742`).
- **Path Isolation & Panel Fix A/D Honesty:** Zero edits to `canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`, or `canary/redteam/anticheat.py`; executed single-threaded (`--workers 1`) with **`0` live LLM/API calls**. Consistent with Panel Fix A/D disclosures (`README.md`, `docs/DIFFICULTY.md`), Canary `v1.4` `hard` headline gap leads with raw `65% [24%, 98%]` before luck-adjusted `72% [52%, 91%]`, dev seeds `0-29` are disclosed as a post-hoc lock (so all evolutionary training here uses disjoint seeds `30000-30099` and evaluates strictly out-of-sample on `30200-30399` and public-test-keyed `900000-900039`), and `hard` canary clearance (`W4`) is non-binding.
- **Overall Integrity Verdict: HELD (`0` statistically significant non-Bayesian solver-beaters across `60/60` out-of-sample `(policy, tier)` cells, `0` partial-play exploits across `4,200` effort probes, `100%` bit-identical across `PYTHONHASHSEED`, `0` sequential seed predictability).**
- **Part A: 1,040-Policy Evolutionary Search (`18,800` episodes, `1,146,985` tool calls, `2,001.53s` total audit wall time):**
  - Parameterized a `2,073,600`-configuration 10-gene non-Bayesian policy space (`ParameterizedEliminationPolicy`, generalizing `swarm_w2b008`) and evaluated `560` structured/random grid anchors plus `12` evolutionary generations x `40` crossover/mutation offspring (**`1,040` distinct policies**) on training seeds `30000-30099` (`n=100`), promoting `17` semifinalists (`n=15` seeds/tier), `7` finalists (`n=100` seeds/tier), and `6` survivors (`swarm_w2b008` + `5` evolved champions) to out-of-sample `dev_oos` (`30200-30399`, `n=200` paired seeds/tier) and `judge_public` (`900000-900039`, `n=40` paired seeds/tier under `PUBLIC_TEST_SECRET`).
  - **`0/30` `(policy, tier)` cells on `dev_oos` (`n=200`) and `0/30` `(policy, tier)` cells on `judge_public` (`n=40`)** beat `SolverPolicy` at one-sided 95% significance (`significantly_above_solver == False` across all `60` cells).
  - Across both the 5-tier overall average and the 3-tier `hard` trio (`hard`, `hard_forge`, `hard_rl`), `SolverPolicy` beats every evolved heuristic on both out-of-sample splits:
    - **`dev_oos` (`n=200`/tier):** `SolverPolicy` overall `0.5561`, `hard_trio = 0.4511` vs best evolved `evo_best_overall` overall `0.5171` (`-0.0391`), `hard_trio = 0.3967` (`-0.0544`), and baseline `swarm_w2b008` overall `0.4585` (`-0.0976`), `hard_trio = 0.3223` (`-0.1289`).
    - **`judge_public` (`n=40`/tier):** `SolverPolicy` overall `0.5520`, `hard_trio = 0.4413` vs best overall `evo_best_overall` `0.5016` (`-0.0504`) and best `hard_trio` `evo_best_hard_trio` `0.3828` (`-0.0586`), with `swarm_w2b008` at overall `0.4183` (`-0.1337`), `hard_trio = 0.2335` (`-0.2078`).
  - **Tier-specific diagnostic (`hard` & `hard_rl` vs `hard_forge`):** On `hard` (`n=200`), all `6` heuristics have 95% paired bootstrap CIs strictly below `0` against `SolverPolicy` (`0.5768`), led by `evo_best_overall = 0.5099` (`diff = -0.0669 [-0.1293, -0.0032]`). On `hard_rl` (`MoleLinUCBPolicy`, `n=200`), non-Bayesian heuristics collapse because they lack likelihood updates for strategic mole abstention: `swarm_w2b008 = 0.1196` (`36.7%` of `SolverPolicy` `0.3261`, `diff = -0.2065 [-0.2641, -0.1488]`) and best `evo_best_hard_forge = 0.2189` (`67.1%` of `SolverPolicy`, `diff = -0.1072 [-0.1739, -0.0442]`). On `hard_forge` (`MoleForgePolicy`), `evo_best_overall` (`0.4946` vs `0.4505` on `dev_oos`, `diff = +0.0441 [-0.0202, +0.1140]`, `one_sided_lower95 = -0.0126`) and `evo_best_hard_trio` (`0.5410` vs `0.4555` on `judge_public`, `diff = +0.0855 [-0.0350, +0.2345]`, `one_sided_lower95 = -0.0298`) tie `SolverPolicy` within paired bootstrap noise by down-weighting forged after-hours access logs, without achieving statistical significance or transferring to `hard` or `hard_rl`.
- **Part B: Effort Ladder on `hard_forge` and `hard_rl` (`4,200` partial-play probes):**
  - Stopping without accusing at `10%`, `25%`, `50%`, `75%`, `90%`, or immediately before `SolverPolicy`'s `accuse` call yields **exact `0.000000`** (`max_abs = 0.0`, `0` nonzero episodes across `n=100` `dev_oos` + `n=40` `judge_public` seeds x `2` tiers).
  - Forcing a posterior-argmax accusation at `10%`, `25%`, `50%`, `75%`, or `90%` of episode tool calls (both pre-step and post-ingest) scores **strictly below full `SolverPolicy`** with 95% paired bootstrap CIs wholly negative on all `20/20` `(split, tier, cut)` cells.
- **Part C: Determinism & Seed Autocorrelation Forensics (`PASS`):**
  - **`PYTHONHASHSEED` invariance:** `60` subprocess rollouts (`4,604` tool calls across `PYTHONHASHSEED in {0, 1, 42, 2147483647}`, `5` tiers, seeds `30201, 30205, 900000`) produce `4` distinct built-in `hash(str)` values and **`0` mismatches** in `world_sha256`, `tool_outputs_sha256`, `ledger_sha256`, `score`, `V`, `accused`, or `final_day`.
  - **Sequential seed independence:** Marginal uniformity (`df=39`), `4x4` bucket chi-square (`df=9`), `5x5` department-mod chi-square (`df=16`), exact-repeat chi-square (`df=1`), Monte Carlo `40x40` transition chi-square (`2,000` trials), and lag-`1..5` autocorrelations (`|r| <= 0.0396` across all `1,000`-world pooled suites) confirm **zero sequential mole predictability** across `JUDGE_SEEDS` (`900000-900039`), extended `900000-900199` under fresh secrets, and `HELDOUT_SEEDS` (`800000-800199`).

## 2. Reproduce Commands (Keyless, Zero LLM Calls)

Fast smoke audit (`< 10s`) and unit/regression test suite:

```bash
TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python \
  scripts/integrity_heuristic_evolution_v14.py --quick --workers 1

TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_integrity_heuristic_evolution_v14.py
```

Full `1,040`-policy evolutionary sweep, `n=100` / `n=40` effort ladder, `PYTHONHASHSEED` subprocess audit, and `2,000`-trial Monte Carlo seed autocorrelation audit (`2,001.53s` single-CPU, scratch output in `/tmp/opencode`):

```bash
TMPDIR=/tmp/opencode /tmp/fleet-silas/shared/agent-arena-venv/bin/python \
  scripts/integrity_heuristic_evolution_v14.py --workers 1 --json-out /tmp/opencode/heuristic_evo_full.json
```

## 3. Part A: 1,040-Policy Evolutionary Non-Bayesian Heuristic Search

### 3.1 Parameterized Policy Space & Multi-Stage Selection Protocol

`ParameterizedEliminationPolicy` (`scripts/integrity_heuristic_evolution_v14.py`) generalizes `swarm_w2b008` across `10` discrete genes (`9 x 9 x 2 x 4 x 6 x 5 x 4 x 8 x 3 x 3 = 2,073,600` configurations) without any Bayesian posterior, `p_leak` model, or `fingerprint_accuracy` likelihood ratio:

| Gene | Domain | Baseline `swarm_w2b008` | Role |
|---|---|---|---|
| `first_canary_size` (`g1`) | `{2, 3, 4, 6, 8, 10, 12, 16, 20}` | `6` | Day-1 initial canary recipient count |
| `followup_canary_size` (`g2`) | `{2, 3, 4, 6, 8, 10, 12, 16, 20}` | `6` | Subsequent canary recipient count |
| `variant_partitions` (`vp`) | `{2, 3}` | `3` | Variants per canary (`min(vp, env.max_variants)`) |
| `decoy_rule` (`dec`) | `none`, `unique_cv`, `anger_majority`, `soft_deprioritize` | `unique_cv` | Message-based decoy filter / ranking penalty |
| `after_hours_weight` (`ah`) | `{0.0, 0.5, 1.0, 2.0, 4.0, 8.0}` | `0.0` | Weight on `after_hours` entries in `read_access_logs` |
| `interview_budget` (`iv`) | `{0, 2, 4, 6, 8}` | `0` | Max `interview` calls (`+4.0` score per `"evasive"` hit) |
| `min_pool_to_accuse` (`mp`) | `{1, 2, 3, 4}` | `1` | Max active-pool size eligible for threshold accusation |
| `accuse_day_threshold` (`ad`) | `{6, 8, 10, 12, 14, 18, 21, 99}` | `99` | Earliest day to accuse top-ranked suspect when `|active| <= mp` |
| `elimination_mode` (`el`) | `strict`, `min_strikes`, `weighted_strikes` | `strict` | Hard set-intersection vs minimum-strike fault tolerance |
| `second_canary_mode` (`sc`) | `offset`, `orthogonal`, `disjoint_top` | `offset` | Same-day second canary (`canaries_per_day=2` on `hard*`) |

Selection stages (strictly isolated from post-hoc locked dev seeds `0-29`):
1. **Fast screen (`1,040` distinct policies):** `560` structured + Latin-style random grid configs (`W2B008_CONFIG` anchored at index `0`) followed by `12` evolutionary generations x `40` elitist tournament crossover/mutation offspring (`best_screen_overall`: `0.7380` in gen `1` -> `0.8100` in gen `10..12`; `best_screen_hard_trio`: `0.7600` in gen `1` -> `0.7900` in gen `10..12`), with `hard_rl` screening promoted across elites and top `48` `hard_trio` candidates.
2. **Semifinals (`17` policies x `5` tiers x `15` train seeds `30000-30014`)** -> **Finals (`7` policies x `5` tiers x `100` train seeds `30000-30099`)**.
3. **Out-of-sample evaluation (`6` survivors):** `swarm_w2b008` plus the `5` distinct training champions (`evo_best_overall`, `evo_best_hard`, `evo_best_hard_forge`, `evo_best_hard_rl`, `evo_best_hard_trio`) evaluated once on `dev_oos` (`30200-30399`, `n=200`/tier) and `judge_public` (`900000-900039`, `n=40`/tier, `PUBLIC_TEST_SECRET`), paired seed-by-seed against `SolverPolicy` (`4,000` paired bootstrap resamples).

### 3.2 Survivor Configurations & Training Performance (`Seeds 30000-30099`, `n=100`/Tier)

| Survivor | Evolved Configuration (`short_label`) | Train `easy` | Train `medium` | Train `hard` | Train `hard_forge` | Train `hard_rl` | Train `hard_trio` | Train `overall` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `swarm_w2b008` | `g1=6,g2=6,vp=3,dec=unique_cv,ah=0,iv=0,mp=1,ad=99,el=strict,sc=offset` | `0.7472` | `0.5867` | `0.4832` | `0.3888` | `0.1495` | `0.3405` | `0.4711` |
| `evo_best_overall` | `g1=10,g2=3,vp=3,dec=anger_majority,ah=1,iv=8,mp=2,ad=21,el=strict,sc=disjoint_top` | `0.7874` | `0.6823` | `0.4898` | `0.4718` | `0.2310` | `0.3975` | `0.5325` |
| `evo_best_hard_trio` | `g1=10,g2=4,vp=3,dec=none,ah=1,iv=2,mp=1,ad=21,el=strict,sc=offset` | `0.7718` | `0.6156` | `0.4068` | `0.4782` | `0.1924` | `0.3591` | `0.4930` |
| `evo_best_hard_forge` | `g1=16,g2=3,vp=3,dec=unique_cv,ah=2,iv=8,mp=2,ad=8,el=min_strikes,sc=disjoint_top` | `0.7291` | `0.5931` | `0.4502` | `0.4817` | `0.1963` | `0.3761` | `0.4901` |
| `evo_best_hard` | `g1=6,g2=2,vp=2,dec=soft_deprioritize,ah=0,iv=0,mp=3,ad=6,el=strict,sc=disjoint_top` | `0.6594` | `0.4610` | `0.4571` | `0.3941` | `0.1618` | `0.3377` | `0.4267` |
| `evo_best_hard_rl` | `g1=2,g2=2,vp=2,dec=unique_cv,ah=0,iv=0,mp=4,ad=8,el=weighted_strikes,sc=offset` | `0.6091` | `0.4273` | `0.4343` | `0.3795` | `0.2312` | `0.3483` | `0.4163` |

### 3.3 Out-of-Sample Paired Comparison on `dev_oos` (`Seeds 30200-30399`, `n=200`/Tier)

Summary across aggregates (`n=1,000` episodes/policy across `5` tiers; `n=600` across `hard_trio`):

| Policy | `easy` | `medium` | `hard` | `hard_forge` | `hard_rl` | `hard_trio` Mean | `overall` Mean | Cells w/ 1-Sided `95% > Solver` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`SolverPolicy` (ref)** | **`0.7701`** | **`0.6571`** | **`0.5768`** | `0.4505` | **`0.3261`** | **`0.4511`** | **`0.5561`** | n/a |
| `evo_best_overall` | `0.7735` | `0.6216` | `0.5099` | `0.4946` | `0.1857` | `0.3967` | `0.5171` | `0 / 5` |
| `evo_best_hard_forge` | `0.7554` | `0.5779` | `0.4888` | `0.4589` | `0.2189` | `0.3889` | `0.5000` | `0 / 5` |
| `evo_best_hard_trio` | `0.7608` | `0.6346` | `0.4994` | `0.4281` | `0.1689` | `0.3655` | `0.4983` | `0 / 5` |
| `swarm_w2b008` | `0.7689` | `0.5567` | `0.4155` | `0.4317` | `0.1196` | `0.3223` | `0.4585` | `0 / 5` |
| `evo_best_hard` | `0.6395` | `0.4125` | `0.3791` | `0.4021` | `0.1509` | `0.3107` | `0.3968` | `0 / 5` |
| `evo_best_hard_rl` | `0.6371` | `0.3984` | `0.4252` | `0.3639` | `0.1290` | `0.3060` | `0.3907` | `0 / 5` |

Detailed `hard`, `hard_forge`, and `hard_rl` paired diagnostics on `dev_oos` (`n=200` paired seeds per cell):

| Tier | Policy | Mean (`+-95% CI`) | Acc | Wrong Acc | Mean Day | Paired Diff vs Solver `[95% Boot CI]` | 1-Sided Low95 | Ratio | W / T / L | Sig `> Solver`? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `hard` | `SolverPolicy` | `0.5768 +- 0.0424` | `0.970` | `6` | `8.78` | `0.0000` (ref) | n/a | `1.0000` | n/a | n/a |
| `hard` | `evo_best_overall` | `0.5099 +- 0.0463` | `0.950` | `6` | `9.38` | `-0.0669 [-0.1293, -0.0032]` | `-0.1203` | `0.8840` | `83 / 4 / 113` | `False` |
| `hard` | `evo_best_hard_trio` | `0.4994 +- 0.0376` | `0.965` | `3` | `10.34` | `-0.0775 [-0.1339, -0.0227]` | `-0.1237` | `0.8657` | `73 / 1 / 126` | `False` |
| `hard` | `evo_best_hard_forge` | `0.4888 +- 0.0504` | `0.935` | `8` | `9.32` | `-0.0880 [-0.1487, -0.0252]` | `-0.1421` | `0.8474` | `73 / 4 / 123` | `False` |
| `hard` | `evo_best_hard_rl` | `0.4252 +- 0.0486` | `0.905` | `7` | `10.54` | `-0.1517 [-0.2172, -0.0849]` | `-0.2060` | `0.7371` | `65 / 2 / 133` | `False` |
| `hard` | `swarm_w2b008` | `0.4155 +- 0.0604` | `0.905` | `14` | `10.09` | `-0.1613 [-0.2373, -0.0845]` | `-0.2256` | `0.7204` | `70 / 3 / 127` | `False` |
| `hard` | `evo_best_hard` | `0.3791 +- 0.0583` | `0.900` | `13` | `10.62` | `-0.1977 [-0.2663, -0.1270]` | `-0.2572` | `0.6572` | `59 / 0 / 141` | `False` |
| `hard_forge` | `SolverPolicy` | `0.4505 +- 0.0563` | `0.850` | `10` | `11.54` | `0.0000` (ref) | n/a | `1.0000` | n/a | n/a |
| `hard_forge` | `evo_best_overall` | `0.4946 +- 0.0486` | `0.860` | `4` | `10.84` | `+0.0441 [-0.0202, +0.1140]` | `-0.0126` | `1.0979` | `98 / 11 / 91` | `False` |
| `hard_forge` | `evo_best_hard_forge` | `0.4589 +- 0.0563` | `0.820` | `8` | `10.94` | `+0.0084 [-0.0662, +0.0851]` | `-0.0535` | `1.0186` | `93 / 12 / 95` | `False` |
| `hard_forge` | `swarm_w2b008` | `0.4317 +- 0.0525` | `0.820` | `7` | `10.85` | `-0.0188 [-0.0890, +0.0537]` | `-0.0795` | `0.9583` | `77 / 15 / 108` | `False` |
| `hard_forge` | `evo_best_hard_trio` | `0.4281 +- 0.0596` | `0.795` | `10` | `10.54` | `-0.0224 [-0.0943, +0.0521]` | `-0.0848` | `0.9503` | `94 / 17 / 89` | `False` |
| `hard_forge` | `evo_best_hard` | `0.4021 +- 0.0599` | `0.750` | `10` | `11.43` | `-0.0485 [-0.1249, +0.0309]` | `-0.1139` | `0.8925` | `76 / 15 / 109` | `False` |
| `hard_forge` | `evo_best_hard_rl` | `0.3639 +- 0.0582` | `0.710` | `9` | `12.11` | `-0.0867 [-0.1531, -0.0162]` | `-0.1442` | `0.8077` | `64 / 16 / 120` | `False` |
| `hard_rl` | `SolverPolicy` | `0.3261 +- 0.0444` | `0.660` | `3` | `13.04` | `0.0000` (ref) | n/a | `1.0000` | n/a | n/a |
| `hard_rl` | `evo_best_hard_forge` | `0.2189 +- 0.0520` | `0.555` | `8` | `12.33` | `-0.1072 [-0.1739, -0.0442]` | `-0.1610` | `0.6712` | `65 / 35 / 100` | `False` |
| `hard_rl` | `evo_best_overall` | `0.1857 +- 0.0516` | `0.520` | `9` | `12.84` | `-0.1404 [-0.2053, -0.0701]` | `-0.1963` | `0.5695` | `57 / 32 / 111` | `False` |
| `hard_rl` | `evo_best_hard_trio` | `0.1689 +- 0.0469` | `0.475` | `7` | `12.72` | `-0.1572 [-0.2189, -0.0960]` | `-0.2098` | `0.5180` | `59 / 32 / 109` | `False` |
| `hard_rl` | `evo_best_hard` | `0.1509 +- 0.0379` | `0.385` | `2` | `13.32` | `-0.1752 [-0.2324, -0.1158]` | `-0.2232` | `0.4627` | `39 / 45 / 116` | `False` |
| `hard_rl` | `evo_best_hard_rl` | `0.1290 +- 0.0364` | `0.395` | `3` | `14.17` | `-0.1971 [-0.2512, -0.1406]` | `-0.2434` | `0.3956` | `39 / 42 / 119` | `False` |
| `hard_rl` | `swarm_w2b008` | `0.1196 +- 0.0426` | `0.310` | `5` | `12.33` | `-0.2065 [-0.2641, -0.1488]` | `-0.2556` | `0.3667` | `36 / 50 / 114` | `False` |

### 3.4 Out-of-Sample Paired Comparison on `judge_public` (`Seeds 900000-900039`, `n=40`/Tier)

Evaluated under `PUBLIC_TEST_SECRET = b"canary-anticheat-public-test-v1"` (`0` overlap with training or dev seeds):

| Policy | `easy` | `medium` | `hard` | `hard_forge` | `hard_rl` | `hard_trio` Mean | `overall` Mean | Cells w/ 1-Sided `95% > Solver` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`SolverPolicy` (ref)** | `0.7650` | **`0.6708`** | **`0.5453`** | `0.4555` | **`0.3233`** | **`0.4413`** | **`0.5520`** | n/a |
| `evo_best_overall` | `0.7813` | `0.6458` | `0.3968` | `0.4810` | `0.2030` | `0.3603` | `0.5016` | `0 / 5` |
| `evo_best_hard_trio` | `0.7900` | `0.5290` | `0.4810` | `0.5410` | `0.1263` | `0.3828` | `0.4935` | `0 / 5` |
| `evo_best_hard_forge` | `0.7915` | `0.5580` | `0.3758` | `0.5188` | `0.1420` | `0.3455` | `0.4772` | `0 / 5` |
| `evo_best_hard` | `0.6393` | `0.5673` | `0.3813` | `0.3798` | `0.1580` | `0.3063` | `0.4251` | `0 / 5` |
| `evo_best_hard_rl` | `0.7175` | `0.4643` | `0.3948` | `0.4603` | `0.0823` | `0.3124` | `0.4238` | `0 / 5` |
| `swarm_w2b008` | `0.7423` | `0.6485` | `0.3628` | `0.2415` | `0.0963` | `0.2335` | `0.4183` | `0 / 5` |

### 3.5 Mechanistic Interpretation Across `hard`, `hard_rl`, and `hard_forge`

1. **`hard` (`MolePolicy`, `fingerprint_accuracy=0.95`):** Because `5%` of canary leak attributions land on an innocent variant group, deterministic set-intersection (`el=strict`) occasionally eliminates the true mole and rebounds only when `self.suspects & grp` is empty, while strike counters (`el=min_strikes` / `weighted_strikes`) lack calibrated posterior stopping (`P > 1 / (1 + V)`). Every evolved heuristic trails `SolverPolicy` on `hard` (`-0.0669` to `-0.1977` on `n=200`).
2. **`hard_rl` (`MoleLinUCBPolicy`, contextual-bandit sleeper mole):** `MoleLinUCBPolicy` learns to abstain on high-exposure narrow canaries. `SolverPolicy` updates its posterior on *both* observed leaks and silent canary days via its leak-rate model, whereas non-Bayesian elimination/strike heuristics stall when leaks dry up (`swarm_w2b008` accuse rate `33.5%`, mean `0.1196`; `evo_best_hard_rl`, despite training-set selection at `0.2312`, regresses out-of-sample to `0.1290` on `dev_oos` and `0.0823` on `judge_public` - classic selection-bias reversion).
3. **`hard_forge` (`MoleForgePolicy`, active log-framing mole):** `MoleForgePolicy` leaks regularly (`accuse_rate` `85%-90%`) while injecting forged `after_hours` access logs onto innocent staff. `SolverPolicy(None)` applies uncalibrated generic access-log likelihoods, delaying accusation slightly (`11.54` days, `10` wrong accusations on `n=200`), whereas `evo_best_overall` (`g1=10, g2=3, ah=1.0, iv=8, dec=anger_majority, sc=disjoint_top`) relies primarily on 3-way canary trisection + interview evasiveness, matching `SolverPolicy` within noise (`+0.0441 [-0.0202, +0.1140]` on `dev_oos`; `+0.0255 [-0.1690, +0.2188]` on `judge_public`). Neither difference is statistically significant (`one_sided_lower95 < 0`), and no single non-Bayesian policy comes within `0.054` of `SolverPolicy` across `hard_trio`.

## 4. Part B: Partial-Play & Effort-Ladder Audit (`hard_forge` and `hard_rl`)

At each cut `pct in {10%, 25%, 50%, 75%, 90%}` of `SolverPolicy`'s episode length `n_calls`, three partial-play probes are evaluated (`4,200` total probes = `3` modes x `5` cuts x `2` tiers x `140` seeds):
1. **Stop without accusing (`stop_scores`):** Episode terminated at `k = floor(n_calls * pct / 100)` (plus `solver_minus_accuse` immediately prior to `SolverPolicy`'s `accuse` call).
2. **Upstream cut-and-guess (`cut_guess`):** Accuse `argmax(belief)` using steps ingested before call `k` (scored at exact `V_at[t]` if correct else `-1.0`).
3. **Post-ingest cut-and-guess (`post_ingest_guess`):** Accuse `argmax(belief)` immediately after ingesting step `k`.

### 4.1 `dev_oos` Effort Ladder (`Seeds 30200-30299`, `n=100` Paired Seeds/Tier, `3,000` Probes)

Full `SolverPolicy` reference: `hard_forge = +0.4033 +- 0.0840` (`accuracy = 0.830`, `mean_calls = 101.58`, `solver_minus_accuse_nonzero = 0/100`); `hard_rl = +0.3102 +- 0.0656` (`accuracy = 0.640`, `mean_calls = 122.06`, `solver_minus_accuse_nonzero = 0/100`).

| Tier | Effort Cut | Stop w/o Accusing (Nonzero) | Cut-Guess Mean | Cut-Guess Acc | Mean Day | Post-Ingest Mean | Paired Diff vs Full Solver `[95% Boot CI]` | 1-Sided Low95 | Strictly `< Solver`? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `hard_forge` | `10%` | `0.0000` (`0/100`) | `-0.9404` | `0.030` | `1.67` | `-0.9404` | `-1.3437 [-1.4445, -1.2331]` | `-1.4312` | `True` |
| `hard_forge` | `25%` | `0.0000` (`0/100`) | `-0.8851` | `0.060` | `3.18` | `-0.8851` | `-1.2884 [-1.4015, -1.1692]` | `-1.3866` | `True` |
| `hard_forge` | `50%` | `0.0000` (`0/100`) | `-0.7110` | `0.160` | `6.10` | `-0.7145` | `-1.1143 [-1.2618, -0.9684]` | `-1.2397` | `True` |
| `hard_forge` | `75%` | `0.0000` (`0/100`) | `-0.3747` | `0.380` | `9.55` | `-0.3388` | `-0.7780 [-0.9549, -0.6039]` | `-0.9245` | `True` |
| `hard_forge` | `90%` | `0.0000` (`0/100`) | `-0.1165` | `0.570` | `11.50` | `-0.0992` | `-0.5198 [-0.6765, -0.3737]` | `-0.6488` | `True` |
| `hard_rl` | `10%` | `0.0000` (`0/100`) | `-0.9609` | `0.020` | `1.86` | `-0.9416` | `-1.2711 [-1.3508, -1.1821]` | `-1.3417` | `True` |
| `hard_rl` | `25%` | `0.0000` (`0/100`) | `-0.9436` | `0.030` | `3.73` | `-0.9616` | `-1.2538 [-1.3366, -1.1646]` | `-1.3281` | `True` |
| `hard_rl` | `50%` | `0.0000` (`0/100`) | `-0.4835` | `0.300` | `7.57` | `-0.3935` | `-0.7937 [-0.9493, -0.6338]` | `-0.9283` | `True` |
| `hard_rl` | `75%` | `0.0000` (`0/100`) | `-0.0907` | `0.570` | `11.94` | `-0.0878` | `-0.4009 [-0.5487, -0.2533]` | `-0.5241` | `True` |
| `hard_rl` | `90%` | `0.0000` (`0/100`) | `+0.0258` | `0.690` | `14.38` | `+0.0295` | `-0.2844 [-0.4111, -0.1643]` | `-0.3898` | `True` |

### 4.2 `judge_public` Effort Ladder (`Seeds 900000-900039`, `n=40` Paired Seeds/Tier, `1,200` Probes)

Full `SolverPolicy` reference: `hard_forge = +0.4555 +- 0.1274` (`accuracy = 0.875`, `mean_calls = 99.95`, `solver_minus_accuse_nonzero = 0/40`); `hard_rl = +0.3233 +- 0.1055` (`accuracy = 0.675`, `mean_calls = 119.80`, `solver_minus_accuse_nonzero = 0/40`).

| Tier | Effort Cut | Stop w/o Accusing (Nonzero) | Cut-Guess Mean | Cut-Guess Acc | Mean Day | Post-Ingest Mean | Paired Diff vs Full Solver `[95% Boot CI]` | 1-Sided Low95 | Strictly `< Solver`? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `hard_forge` | `10%` | `0.0000` (`0/40`) | `-0.9503` | `0.025` | `1.60` | `-0.9503` | `-1.4058 [-1.5408, -1.2495]` | `-1.5329` | `True` |
| `hard_forge` | `25%` | `0.0000` (`0/40`) | `-0.7560` | `0.125` | `3.00` | `-0.7560` | `-1.2115 [-1.4210, -0.9725]` | `-1.4039` | `True` |
| `hard_forge` | `50%` | `0.0000` (`0/40`) | `-0.2825` | `0.400` | `5.98` | `-0.1880` | `-0.7380 [-1.0268, -0.4495]` | `-0.9831` | `True` |
| `hard_forge` | `75%` | `0.0000` (`0/40`) | `-0.1393` | `0.525` | `9.40` | `-0.0943` | `-0.5948 [-0.8780, -0.3195]` | `-0.8320` | `True` |
| `hard_forge` | `90%` | `0.0000` (`0/40`) | `+0.0793` | `0.675` | `11.33` | `+0.1678` | `-0.3763 [-0.6110, -0.1582]` | `-0.5706` | `True` |
| `hard_rl` | `10%` | `0.0000` (`0/40`) | `-0.8528` | `0.075` | `1.85` | `-0.8528` | `-1.1760 [-1.3388, -0.9913]` | `-1.3284` | `True` |
| `hard_rl` | `25%` | `0.0000` (`0/40`) | `-0.7218` | `0.150` | `3.70` | `-0.7218` | `-1.0450 [-1.2670, -0.8000]` | `-1.2450` | `True` |
| `hard_rl` | `50%` | `0.0000` (`0/40`) | `-0.3998` | `0.350` | `7.40` | `-0.3908` | `-0.7230 [-0.9783, -0.4512]` | `-0.9524` | `True` |
| `hard_rl` | `75%` | `0.0000` (`0/40`) | `-0.2375` | `0.500` | `11.63` | `-0.1928` | `-0.5608 [-0.8160, -0.3025]` | `-0.7786` | `True` |
| `hard_rl` | `90%` | `0.0000` (`0/40`) | `+0.0245` | `0.700` | `14.00` | `+0.0570` | `-0.2988 [-0.5348, -0.0775]` | `-0.4921` | `True` |

Even at `90%` of episode effort on `hard_rl` (`69%-70%` top-1 accuracy), forcing an accusation on unresolved seeds converts `SolverPolicy`'s calibrated horizon abstentions (`score = 0.0`) into `-1.0` wrong-accusation penalties, losing `0.2844` (`dev_oos`) and `0.2988` (`judge_public`) points per episode.

## 5. Part C: `PYTHONHASHSEED` Invariance & Seed Autocorrelation Forensics

### 5.1 Cross-Process `PYTHONHASHSEED` Bit-Identity (`60` Subprocess Rollouts, `4,604` Tool Calls)

Four independent Python subprocesses were spawned with `PYTHONHASHSEED in {0, 1, 42, 2147483647}`, verifying `4` distinct built-in SipHash outputs (`hash("canary_v14_hashseed_probe_token")`: `-8857202357297487419`, `9118770788729411525`, `-1212203127137505758`, `2991091461182192518`) while testing all `15` `(tier, seed)` cells (`5` tiers x `{30201, 30205, 900000}`). Every cell achieved **exact byte-for-byte SHA-256 parity** (`mismatches = []`, `bit_identical = True`):

| Cell (`tier:seed`) | Steps | Accused | Correct | Day | Score (`V`) | `world_sha256` (prefix) | `tool_outputs_sha256` (prefix) | `ledger_sha256` (prefix) |
|---|---:|---|---|---:|---:|---|---|---|
| `easy:30201` | `26` | `e09` | `True` | `4` | `0.82` (`0.82`) | `fe698e383e87e423` | `b68dff40af2760f1` | `68f8d1b4aa8ef75f` |
| `easy:30205` | `26` | `e05` | `True` | `4` | `0.82` (`0.82`) | `42949dba758fc651` | `9ebc494504c77a71` | `eba05c821d2679e8` |
| `easy:900000` | `33` | `e05` | `True` | `5` | `0.81` (`0.81`) | `88cde05226806d82` | `9887472e38c52a9d` | `1a58b7ad4f542781` |
| `medium:30201` | `97` | `e11` | `True` | `13` | `0.56` (`0.56`) | `85199d3e7c6fa68a` | `ae7f8f372b1ddf57` | `a4269c302f1c09c4` |
| `medium:30205` | `106` | `None` | `False` | `14` | `0.00` (`0.58`) | `6423b86f267d4ad9` | `df2c76d12e9525db` | `84a907785e0c71ac` |
| `medium:900000` | `55` | `e03` | `True` | `7` | `0.78` (`0.78`) | `2816d8c66a247de2` | `594c6199f1e48408` | `d187762694cfac2b` |
| `hard:30201` | `94` | `e39` | `True` | `12` | `0.45` (`0.45`) | `528d8eb6ca4432a8` | `eb20ec1f58879cdc` | `b51ba44ddc593bf0` |
| `hard:30205` | `72` | `e10` | `True` | `9` | `0.64` (`0.64`) | `3f632572c13d9c83` | `d1aa975178e66506` | `4b5541d07ca47d7e` |
| `hard:900000` | `37` | `e01` | `True` | `4` | `0.79` (`0.79`) | `2ec2afb65946df00` | `f381a969fc80382d` | `d4a8b5413052f755` |
| `hard_forge:30201` | `52` | `e27` | `True` | `6` | `0.76` (`0.76`) | `335eca099dddabaa` | `80c03f1ab9c41933` | `1e0564f217d70573` |
| `hard_forge:30205` | `160` | `None` | `False` | `21` | `0.00` (`0.00`) | `8148b45b35d544fe` | `6defe68164534e3a` | `366cfd984711e1a4` |
| `hard_forge:900000` | `143` | `e29` | `True` | `19` | `0.18` (`0.18`) | `44ea4ccb961fee85` | `9997e0e8a36d3a80` | `94d8ad7c380e7cf9` |
| `hard_rl:30201` | `74` | `e04` | `True` | `9` | `0.57` (`0.57`) | `d994dcd846b20842` | `80d4ab0d654eef2e` | `fc23df21ee268099` |
| `hard_rl:30205` | `103` | `e28` | `True` | `13` | `0.42` (`0.42`) | `420a6b4b99a514f3` | `c9aab21240554b59` | `df6aefa283c917b5` |
| `hard_rl:900000` | `73` | `e00` | `True` | `9` | `0.63` (`0.63`) | `8f96a78f3bd19de6` | `a704fe449f1f0808` | `0fafea78a86b52f3` |

### 5.2 Sequential Mole-Index Autocorrelation & Chi-Square Suite (`Lags 1..5`)

True `hard` mole indices (`e00..e39`, `40` states) were audited across `5` sequence suites (`2,000` Monte Carlo uniform reference trials per lag):

| Sequence Suite | Worlds (Seqs) | Marginal Chi2 (`df=39`, `p`) | Lag-1 `4x4` `p` | Lag-1 `5x5` Dept `p` | Lag-1 Repeat (`obs/exp`, `p`) | Lag-1 `40x40` MC `p` | Lag-1 `r` | Min `4x4` / `40x40` `p` Across Lags `1..5` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `single_secret_keyed_900000_900199` | `200` (`1`) | `50.80` (`p=0.0977`) | `0.7117` | `0.9490` | `4 / 4.98` (`p=0.6580`) | `0.5542` | `-0.0472` | `0.2302` / `0.4253` |
| `pooled_fresh_secrets_keyed_900000_900199` | `1,000` (`5`) | `30.48` (`p=0.8336`) | `0.3564` | `0.1058` | `26 / 24.88` (`p=0.8193`) | `0.7566` | `-0.0381` | `0.0270` / `0.1949` |
| `live_generate_world_900000_900199_sec0` | `200` (`1`) | `38.80` (`p=0.4789`) | `0.7046` | `0.6517` | `4 / 4.98` (`p=0.6580`) | `0.9220` | `-0.0779` | `0.0296` / `0.2854` |
| `pooled_live_heldout_800000_800199` | `1,000` (`5`) | `62.16` (`p=0.0106`) | `0.2109` | `0.3185` | `18 / 24.88` (`p=0.1627`) | `0.9170` | `-0.0032` | `0.0483` / `0.0740` |
| `pooled_live_judge_900000_900039` | `1,000` (`25`) | `40.72` (`p=0.3946`) | `0.5849` | `0.1578` | `27 / 24.38` (`p=0.5903`) | `0.4868` | `-0.0092` | `0.2373` / `0.0260` |

All suites pass the `alpha = 0.005` Bonferroni-adjusted uniformity and transition-independence threshold (`zero_sequential_predictability = True`), confirming that HMAC-SHA256 keying (`hmac.new(secret, f"{tier}:{seed}", sha256)`) eliminates cross-seed sequential leakage.

### 5.3 Report-Only Boundary Note for Silas (`JUDGE_SEEDS` Range Alignment)

- **Observation (`boundary_forensics`):** `canary/rules.py` defines `JUDGE_SEEDS = range(900_000, 900_040)` (`40` seeds) and `HELDOUT_SEEDS = range(800_000, 800_200)` (`200` seeds). On `900000-900199`, `mcp_server.seed_allowed` admits `40/40` seeds in `900000-900039` and blocks `0/160` seeds in `900040-900199` without `CANARY_ALLOW_DEV=1`, matching `_keyed_hard_mole_index` `40/40` on `900000-900039`. If `generate_world` is invoked directly in Python on `900040-900199`, `160/160` seeds fall back to unkeyed world derivation because `seed not in JUDGE_SEEDS | HELDOUT_SEEDS`.
- **Report-only recommendation:** No exploit exists in shipped Canary `v1.4` because `mcp_server.seed_allowed` rejects `900040+` when `CANARY_ALLOW_DEV` is unset. If Harbor judge evaluations are ever expanded beyond `40` seeds per tier (`900040+`), widen `JUDGE_SEEDS` in `canary/rules.py` in lockstep so both `seed_allowed` and `world._world_seed` HMAC keying cover the full expanded range.
