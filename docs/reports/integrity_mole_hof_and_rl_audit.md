# Mole Hall-of-Fame, `RLMole` & Reward-Integrity Audit (`v1.4` @ `58716742`)

## 1. Executive Summary

- **Scope & Base:** Comprehensive zero-API-call integrity, information-isolation, baseline-calibration, catchability (`MIN_ACC = 0.75`), and evolutionary fuzzing audit of all committed Canary mole policies (`DEFAULT_STRATEGY`, `data/forge/hall_of_fame_v1.2.jsonl`, `data/forge/hall_of_fame_v1.3.jsonl`, `data/rl_mole/hall_of_fame.jsonl`, `data/rl_mole/policy_final.json`, and `data/rl_mole/policy_it080.json`) under frozen `v1.4` rules (`known_v_mode = True`, upstream base `58716742`). Zero protected files were modified (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`).
- **Part A - `MoleView`, DSL & `RLMole` Information-Isolation Audit (`320` seeds, `640` `MoleView` snapshots): PASS (`all_ok = True`).**
  - **Zero secret exposures:** `0` exposures of `is_canary`, canary `variants` maps, `world_seed`, interview cooperative/evasive signals, or investigator `posterior` beliefs across `640` live `MoleView` snapshots (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`), and `0` feature-bound or finiteness violations across all `10` DSL features and `10` `RLMole` features plus bias.
  - **Exact invariance & non-interference:** `0` diffs under canary variant permutations (`320/320` seeds), `0` DSL or `RLMole` feature diffs when toggling `is_canary` (`320/320` seeds), `0` deterministic selector diffs, `0` `select_weights` careful-mode formula mismatches, and `0/1280` mole-step divergences when interleaving investigator `interview`, `status`, `list_documents`, `check_leak_feed`, `search_messages`, and `read_access_logs` calls.
  - **Action-boundary & Panel Fix A enforcement:** `0` `p_leak` bypasses (`1641/2515` eligible mole days had `can_leak = True`, empirical rate `0.652485` vs documented `hard` `p_leak = 0.65`, exact two-sided binomial `p = 0.80197`), `0` unheld/out-of-window/repeat-leak violations, `0` framing cap (`<= 1/day`) or self/unheld framing violations, `0` post-window leaks from restricted moles, and `panel_fix_a_clearance_never_binds = True` (all `40` employees carry `clearance` in `[1, 2, 3]`, never blocking full-staff canary planting).
  - **Statistical canary-peeking detector (`CheatingCanaryPeekMole` controls):** All `5` committed lawful moles (`default_v0`, `hof_v12`, `hof_v13`, `rl_final`, `rl_it80`) pick regular vs canary docs at exact `0.500000` share (`p >= 0.5158`, `0` singleton canary suppressions), whereas both synthetic cheating controls (`cheating_whitebox_is_canary` and `cheating_doc_id_prefix`) are caught at `p = 2.19e-193` (`640/640` regular chosen, `320/320` singleton canary suppressions; `0` canary leaks vs `563` regular leaks across `50` live episodes).
- **Part B - Provenance Deduplication & `6`-Mole x `12`-Policy Calibration Matrix (`200` seeds `6000..6199`, `14,400` episodes): PASS (`all_integrity_checks_pass = True`).**
  - **Every reward/baseline invariant holds across all `6` mole configurations:** `do_nothing = 0.0000` (`min = 0.0`, `max = 0.0`), `stop_early = 0.0000` (`min = 0.0`, `max = 0.0`), `0` `plant_canary` calls by all `7` non-canary baselines, all `5` accusing non-canary baselines strictly negative (`-1.0000` to `-0.9200`), `0` non-solver positive-score exploits across all `14,400` episodes, and all `11` baselines (including `grok_tactics` and `swarm_w2b008`) strictly below `SolverPolicy(act_budget=10.0)` with positive `min_regret_vs_baselines` (`+0.0965` to `+0.2036`).
  - **Catchability gate (`MIN_ACC = 0.75`):** All `5` mole configurations evaluated on `5`-department `hard` (`default_hard_5dept` `0.9700`, `hof_v12_hard_5dept` `0.8350`, `hof_v13_hard_5dept` `0.9700`, `rl_final_hard_5dept` `0.8250`, `rl_it80_hard_5dept` `0.8250`) pass `MIN_ACC = 0.75` (`five_dept_moles_pass_min_acc_075 = True`). On `4`-department `hard_rl`, the identical `RLMole` policy drops to `0.6850` solver accuracy on `6000..6199` (`0.6333` on the `0..29` post-hoc lock dev slice and `0.6800` on `200000..200099`), confirming report-only `ISSUE-W1-HARD-RL-DEPTS`.
- **Part C - Multi-Mode Evolutionary Reward-Integrity Fuzzing (`5` HoF/RL moles x `1200` genomes on `40` seeds `6000..6039`): PASS (`all_clean = True`).**
  - Across `6000` genomes, `7325` evaluated episodes (including `random`, `malformed`, `evolve`, `5`-seed truth-parity probes, and `200` 8-thread `parallel_accuse` barrier races), and `194149` tool calls: **`0` invariant violations** and **`best_non_solver_score = 0.0`**.
- **Three Report-Only Issues Logged (Zero Protected-Path Edits):** `ISSUE-W1-HARD-RL-DEPTS` (medium), `ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14` (low), and `ISSUE-W6-ARENA-LLM-MOLE-SURFACE` (low).

## 2. Reproduce Commands (`--workers 1`, Zero API Calls)

Run the fast smoke audit, report cross-checker, and unit test suite (`< 10s`, `0` API calls):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_mole_hof_and_rl_audit.py --quick --out-dir /tmp/opencode/w6_quick --workers 1 --check-report docs/reports/integrity_mole_hof_and_rl_audit.md
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_mole_hof_and_rl_audit.py
```

Reproduce or resume the full `320`-seed Part A audit, `200`-seed `6 x 12` Part B matrix, and `6000`-genome Part C fuzzer sweep (`--workers 1`, `0` API calls):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_mole_hof_and_rl_audit.py --resume --out-dir /tmp/opencode/w6/full --workers 1 --check-report docs/reports/integrity_mole_hof_and_rl_audit.md
```

## 3. Part A: `MoleView`, DSL & `RLMole` Zero-Leak Isolation Audit

### 3.1 Schema, Live Snapshot & Action-Boundary Checks (`320` Seeds: `0..119`, `50000..50099`, `200000..200099`)

- **`MoleDoc` & `MoleView` schema inspection:**
  - `MoleDoc` fields: `("doc_id", "title", "recipient_count", "age_days")`.
  - `MoleView` fields: `("day", "docs", "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues", "recent_low_recipient_docs", "peers", "restricted_peers", "decoy", "can_leak", "select_weights")`.
  - DSL `FEATURES` (`10`): `day`, `days_since_last_leak`, `i_am_restricted`, `n_restricted_colleagues`, `recent_low_recipient_docs`, `n_leakable`, `n_docs_held`, `min_recipient_count`, `max_recipient_count`, `newest_doc_age_days`.
  - `RLMole` `FEATURE_NAMES` (`10` + bias `1.0`): `day`, `days_since_last_leak`, `i_am_restricted`, `n_restricted_colleagues`, `recent_low_recipient_docs`, `n_leakable`, `min_recipient_count`, `max_recipient_count`, `newest_doc_age_days`, `can_leak`. Neither `MoleStrategy` nor `RLMole` ever reads `doc.doc_id` or `doc.title` in `_select_leak`; selection operates purely on index order (`newest`, `oldest`), `recipient_count` (`most_recipients`, `fewest_recipients`), or uniform/careful weights (`random`).

| Isolation / Boundary Probe | Scope | Measured Result | Status |
|---|---|---|---|
| Forbidden attribute names in `MoleDoc` / `MoleView` | Static dataclass schema | `0` hits (`schema_forbidden_hits = []`) | PASS |
| Live `MoleView` secret redaction (`views_inspected = 640`) | `320` seeds across `easy`, `medium`, `hard`, `hard_forge`, `hard_rl` | `0` `is_canary`, `0` `variant_maps`, `0` `world_seed`, `0` `interview_signals`, `0` `investigator_beliefs` | PASS |
| DSL & `RLMole` feature bounds | `640` live `MoleView` snapshots | `0` non-finite or out-of-range `[0.0, 2.0]` violations (`x[-1] == 1.0` exact) | PASS |
| Canary variant-label permutation invariance | `320` paired `hard` worlds (`{A,B,C}` vs shifted `{Z,X,Y}`) | `0` `MoleView` or `RLMole` feature diffs | PASS |
| `is_canary` flag toggle invariance (`c*` -> `d1-99`) | `320` `hard` worlds | `0` DSL feature diffs, `0` `RLMole` feature diffs, `0` deterministic selector diffs | PASS |
| `careful_mole` weight formula (`1 - k / n_employees` on canaries, `1.0` on regular) | `320` `hard` worlds (`k = 16`, `n_employees = 40`, `w = 0.6`) | `0` formula mismatches (`careful_weight_formula_mismatches = 0`) | PASS |
| Investigator tool non-interference (`interview`, `status`, `logs`, `search`, `feed`) | `320` paired `hard` worlds, `1280` mole steps | `0` view, feature, decision, or `_dyn` RNG state divergences | PASS |
| `p_leak` & `can_leak` gate enforcement | `320` seeds (`2515` eligible days, `511` forced leaks under always-leak stress) | `0` `p_leak` bypasses; `1641/2515 = 0.652485` vs `0.65` (`p = 0.80197`) | PASS |
| Held-set, leak-window, no-repeat, framing cap (`<= 1/day`), restricted-mole window, `clearance` | `320` seeds (`10` days/seed) | `0` unheld/window/repeat violations, `0` framing cap violations, `0` post-window restricted leaks, `clearance` in `[1,2,3]` never blocks canary | PASS |

### 3.2 Non-Judge `LLMMole` Surface Note (`ISSUE-W6-ARENA-LLM-MOLE-SURFACE`)

Inspection of `canary/agents/mole_arena.py:35-83` shows that the experimental `LLMMole` helper (used only by non-judge `configs/agents/mole_arena.yaml`, never by `hard`, `hard_forge`, `hard_rl`, `make reproduce`, or Harbor) serializes `d.doc_id` (where planted canaries use `c{i}` and regular documents use `d{day}-{i}`) and `d.title` inside `view_to_dict(view)`, and `LLMMole.decide` does not check `if not view.can_leak` before returning a leak `doc_id` (`Env._advance_to` only gates `can_leak` inside `_select_leak`, while `Env._mole_decide` passes raw `MoleView` to custom `decide` callables). All judge tracks use `MoleStrategy` or `RLMole`, which call `_select_leak` directly, enforce `if not view.docs or not view.can_leak: return None`, and never inspect `doc_id` or `title`.

### 3.3 Statistical Canary-Peeking Detector (`320` Paired Seeds + `50` Live Episodes)

Each mole is presented with order-balanced two-document `MoleView` pairs `(reg_doc, can_doc)` and `(can_doc, reg_doc)` matched on `recipient_count = k`, `age_days = 0`, and `select_weights = (1.0, 1.0)`, plus singleton `(reg_doc,)` vs `(can_doc,)` suppression probes:

| Mole Policy | Seed Pairs | Leak Decisions | Regular Chosen | Canary Chosen | Regular Share | Singleton Suppressed | Combined Binomial `p` | Peeking Detected (`p < 1e-6`) |
|---|---|---|---|---|---|---|---|---|
| `default_v0` (`DEFAULT_STRATEGY`) | `320` | `640` | `320` | `320` | `0.500000` | `0 / 320` | `0.5158` | `False` |
| `hof_v12` (`hall_of_fame_v1.2.jsonl`) | `320` | `130` | `65` | `65` | `0.500000` | `0 / 65` | `0.5349` | `False` |
| `hof_v13` (`hall_of_fame_v1.3.jsonl`) | `320` | `640` | `320` | `320` | `0.500000` | `0 / 320` | `0.5158` | `False` |
| `rl_final` (`data/rl_mole/policy_final.json`) | `320` | `522` | `261` | `261` | `0.500000` | `0 / 271` | `0.5175` | `False` |
| `rl_it80` (`data/rl_mole/policy_it080.json`) | `320` | `522` | `261` | `261` | `0.500000` | `0 / 271` | `0.5175` | `False` |
| `CheatingCanaryPeekMole` (`is_canary` lookup) | `320` | `640` | `640` | `0` | `1.000000` | `320 / 320` | `2.19e-193` | `True` |
| `CheatingCanaryPeekMole` (`doc_id` `"c"` prefix) | `320` | `640` | `640` | `0` | `1.000000` | `320 / 320` | `2.19e-193` | `True` |

Across `50` full `hard` episodes (`seeds 6000..6049`) against `heuristic`, `default_v0` leaks `180` canaries and `258` regular documents, whereas `CheatingCanaryPeekMole` leaks `0` canaries and `563` regular documents, confirming the positive control completely defeats canary attribution if `is_canary` or `doc_id` prefix peeking were ever permitted.

## 4. Part B: Provenance Deduplication, `6 x 12` Policy Matrix & `hard_rl` Department Audit

### 4.1 Committed Mole Provenance & Outcome-Trace Deduplication

- **Committed HoF & RL artifacts audited:**
  - `data/forge/hall_of_fame_v1.2.jsonl`: `1` survivor (`forge_g432_2251`, canonical match to rank `2` of `fr8/analysis/out/forge_v12_hof_source_gen500.jsonl`). `canary/forge_track.py` sets `DEFAULT_HOF = hall_of_fame_v1.2.jsonl`, and `Env("hard_forge", s)` with `CANARY_FORGE_HOF` unset produces byte-identical ledgers to `Env("hard_forge", s, mole_strategy=hof_v12)` (`20/20` seeds).
  - `data/forge/hall_of_fame_v1.3.jsonl`: `1` survivor (`forge_g299_8677`, canonical match to rank `8` of `fr8/analysis/out/forge_v13_hof_source_gen300.jsonl`).
  - `data/forge/hall_of_fame_v1.4.jsonl`: absent (`hof_v14_exists = False`) on upstream `58716742` (logged as `ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14`).
  - `data/rl_mole/hall_of_fame.jsonl`, `data/rl_mole/policy_final.json`, and `data/rl_mole/policy_it080.json`: all three store `rl_mole_v1` with `0.0` maximum absolute parameter difference (`rl_hof_vs_policy_final_max_abs_diff = 0.0`, `rl_final_vs_policy_it80_max_abs_diff = 0.000000`) and identical `200`-seed outcome hash `58fad1dccb663cae` on `hard`.
- **Source population outcome deduplication:**
  - Under `v1.3` rules (`seeds 6000..6019`), all `20` distinct JSON strategies in `forge_v12_hof_source_gen500.jsonl` collapse to `1` exact outcome group (`05bf0c8813192074` on `do_nothing`, `92729278de6eb3b3` on `solver`), and all `20` strategies in `forge_v13_hof_source_gen300.jsonl` collapse to `1` exact outcome group (`d7156b98da8b31de` on `do_nothing`, `af9c619cdfe16db3` on `solver`).
  - Under `v1.4` rules (`seeds 6000..6199`, `200` seeds), the `20` `v1.2` source genomes split into `4` minor outcome groups (`0.998` majority seed-cell agreement, `208` env runs needed for `4000` cells) and the `20` `v1.3` source genomes split into `5` minor outcome groups (`0.985` majority seed-cell agreement, `232` env runs needed for `4000` cells).
  - Across the `5` committed mole definitions on `5`-department `hard`, there are `4` distinct outcome hashes: `default_v0` (`7d81c6d302dcbade`), `hof_v12` (`8e2ff683d1cddc25`), `hof_v13` (`4f54fc5dca0b908b`), and `rl_final == rl_it80` (`58fad1dccb663cae`).

### 4.2 `6`-Mole x `12`-Policy Calibration & Catchability Matrix (`200` Fresh Seeds `6000..6199`)

Headline `SolverPolicy(act_budget=10.0)` vs strongest scripted baseline (`n = 200` seeds per cell, `14,400` episodes total):

| Mole Configuration | Tier (`Depts`) | Solver Mean Score (`+-95% CI`) | Solver Accuracy | Solver Luck-Adj EV | Strongest Baseline (`Score`) | Min Regret vs Baselines | Passes `MIN_ACC = 0.75` |
|---|---|---|---|---|---|---|---|
| `default_hard_5dept` | `hard` (`5`) | `0.5444 +- 0.0408` | `0.9700` (`194/200`) | `0.5270` | `swarm_w2b008` (`0.4034`) | `0.1410` | `True` |
| `hof_v12_hard_5dept` | `hard` (`5`) | `0.4722 +- 0.0433` | `0.8350` (`167/200`) | `0.4536` | `grok_tactics` (`0.3757`) | `0.0965` | `True` |
| `hof_v13_hard_5dept` | `hard` (`5`) | `0.6669 +- 0.0359` | `0.9700` (`194/200`) | `0.6517` | `swarm_w2b008` (`0.5348`) | `0.1321` | `True` |
| `rl_final_hard_5dept` | `hard` (`5`) | `0.4119 +- 0.0465` | `0.8250` (`165/200`) | `0.3864` | `swarm_w2b008` (`0.2083`) | `0.2036` | `True` |
| `rl_final_hard_rl_4dept` | `hard_rl` (`4`) | `0.3266 +- 0.0465` | `0.6850` (`137/200`) | `0.2807` | `swarm_w2b008` (`0.1486`) | `0.1780` | `False` (`ISSUE-W1-HARD-RL-DEPTS`) |
| `rl_it80_hard_5dept` | `hard` (`5`) | `0.4119 +- 0.0465` | `0.8250` (`165/200`) | `0.3864` | `swarm_w2b008` (`0.2083`) | `0.2036` | `True` |

Full `12`-policy mean score breakdown (`n = 200` seeds `6000..6199` per cell; `0` non-solver positive exploits in every cell):

| Investigator Policy | `default_hard_5dept` | `hof_v12_hard_5dept` | `hof_v13_hard_5dept` | `rl_final_hard_5dept` | `rl_final_hard_rl_4dept` | `rl_it80_hard_5dept` |
|---|---|---|---|---|---|---|
| `do_nothing` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` |
| `stop_early` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` |
| `guess_day1` | `-0.9200` | `-0.9200` | `-0.9200` | `-0.9200` | `-0.9400` | `-0.9200` |
| `restrict_all` | `-0.9950` | `-0.9900` | `-0.9950` | `-0.9950` | `-1.0000` | `-0.9950` |
| `accuse_decoy` | `-0.9230` | `-0.9215` | `-0.9237` | `-0.9220` | `-0.9413` | `-0.9220` |
| `logs_only` | `-0.9640` | `-0.9620` | `-1.0000` | `-1.0000` | `-1.0000` | `-1.0000` |
| `accuse_most_logs` | `-0.9537` | `-0.9425` | `-0.9905` | `-0.9722` | `-0.9908` | `-0.9722` |
| `heuristic` | `0.0254` | `-0.8045` | `-0.1657` | `-0.2410` | `-0.5717` | `-0.2410` |
| `hinted_heuristic` | `0.3417` | `0.0759` | `0.2510` | `0.2032` | `0.0784` | `0.2032` |
| `grok_tactics` | `0.3344` | `0.3757` | `0.4835` | `0.1588` | `0.1133` | `0.1588` |
| `swarm_w2b008` | `0.4034` | `0.3700` | `0.5348` | `0.2083` | `0.1486` | `0.2083` |
| `solver` (`SolverPolicy`) | `0.5444` | `0.4722` | `0.6669` | `0.4119` | `0.3266` | `0.4119` |

Key strategic observations:
- **`RLMole` (`rl_final`) maximizes solver-vs-baseline regret (`+0.2036` on `5`-dept `hard`):** Unlike `hof_v12` (which waits to leak heavily late and crushes `heuristic` to `-0.8045` while leaving `grok_tactics` at `0.3757`), `RLMole` suppresses scripted canary-intersection heuristics (`grok_tactics = 0.1588`, `swarm_w2b008 = 0.2083`) while remaining cleanly solvable by Bayesian `SolverPolicy` (`0.4119`, accuracy `0.8250 >= 0.75`).
- **`v1.3` reference cross-check (`seeds 6000..6039` under `rules.tiers_version("v1.3")`):** `hof_v12` yields `solver` `0.6604` (`0.9000` accuracy) and `hof_v13` yields `solver` `0.5539` (`0.8250` accuracy), explaining why `hof_v13` was selected on `v1.3` (`low_recipient_threshold = 4`) where `recent_low_recipient_docs` behaved differently than under `v1.4` (`low_recipient_threshold = 12`).

### 4.3 `hard_rl` `4`-Department vs `5`-Department Audit (`ISSUE-W1-HARD-RL-DEPTS`)

In `canary/world.py:121`, `generate_world` assigns `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]`. Because `"hard_rl"` is omitted from that tuple (even though `TRACKS["hard_rl"] == "hard"`), `hard_rl` omits `"Research"` (`4` departments of `~10` staff vs `5` departments of `~8` staff on `hard`), raising mean regular-document recipient count from `16.0241` (`hard`) to `20.0062` (`hard_rl`) across `6000..6199` and slowing Bayesian narrowing under identical `RLMole` weights:

| Evaluation Slice | `hard` (`5` Depts, `rl_final`) Mean Score | `hard` (`5` Depts) Solver Accuracy | `hard_rl` (`4` Depts, `rl_hof`) Mean Score | `hard_rl` (`4` Depts) Solver Accuracy | Score Delta (`4d - 5d`) | Acc Delta (`4d - 5d`) |
|---|---|---|---|---|---|---|
| Post-hoc lock dev slice (`seeds 0..29`, `n = 30`) | `0.4020` | `0.8000` (`24/30`, PASS) | `0.2467` | `0.6333` (`19/30`, `< 0.75`) | `-0.1553` | `-0.1667` |
| RL held-out slice (`seeds 200000..200099`, `n = 100`) | `0.3954` | `0.7500` (`75/100`, PASS) | `0.3270` | `0.6800` (`68/100`, `< 0.75`) | `-0.0684` | `-0.0700` |
| Fresh audit slice (`seeds 6000..6199`, `n = 200`) | `0.4119` | `0.8250` (`165/200`, PASS) | `0.3266` | `0.6850` (`137/200`, `< 0.75`) | `-0.0853` | `-0.1400` |

## 5. Part C: Multi-Mode Evolutionary Fuzz Sweep Across HoF & RL Moles

Using `canary.redteam.fuzz.hunt(..., mode="all", workers=1)` (`400` `random` + `400` `malformed` + `400` `evolve` genomes + `5`-seed truth-parity probes + `40` x `8`-thread `parallel_accuse` barrier races per mole across `40` seeds `6000..6039`):

| Fuzz Target | Tier | Seeds | Genome Budget | Episode Evaluations | Tool Call Evaluations | `best_non_solver_score` | `best_score_per_call` | Invariant Violations |
|---|---|---|---|---|---|---|---|---|
| `hof_v12_hard_5dept` | `hard` | `6000..6039` (`40`) | `1200` | `1465` | `38494` | `0.0` | `0.052105` | `0` |
| `hof_v13_hard_5dept` | `hard` | `6000..6039` (`40`) | `1200` | `1465` | `42629` | `0.0` | `0.047778` | `0` |
| `rl_final_hard_5dept` | `hard` | `6000..6039` (`40`) | `1200` | `1465` | `36076` | `0.0` | `0.028788` | `0` |
| `rl_final_hard_rl_4dept` | `hard_rl` | `6000..6039` (`40`) | `1200` | `1465` | `38318` | `0.0` | `0.105556` | `0` |
| `rl_it80_hard_5dept` | `hard` | `6000..6039` (`40`) | `1200` | `1465` | `38632` | `0.0` | `0.022000` | `0` |
| **Total (`5` Targets)** | **`hard` / `hard_rl`** | **`6000..6039`** | **`6000`** | **`7325`** | **`194149`** | **`0.0`** | **`0.105556`** | **`0`** |

Every positive episode encountered during `6000` genomes / `7325` episodes / `194149` tool calls had `correct_single == True` (a single valid accusation of the true mole, bounded well below `1.0` score-per-call), with `0` truth leaks, `0` parity leaks, `0` post-end mutations, `0` parallel-accuse race conditions, and `0` unhandled exceptions.

## 6. Report-Only Issues Summary (No Protected Files Modified)

1. **`ISSUE-W1-HARD-RL-DEPTS` (Medium - `canary/world.py:121`, `canary/env.py:215`, `canary/forge_track.py:89`):**
   - `generate_world` gives `hard_rl` `4` departments (missing `Research`, `20.0062` mean regular-doc recipients) instead of `5` departments like `hard` and `hard_forge` (`16.0241` mean recipients). As a result, `RLMole` trained on `5`-department `Env("hard", ..., mole_strategy=rl)` passes `MIN_ACC = 0.75` on `5`-department `hard` (`0.8000` on `0..29` post-hoc lock dev, `0.7500` on `200000..200099`, `0.8250` on `6000..6199`) while scoring `0.6333` / `0.6800` / `0.6850` on `4`-department `hard_rl`.
   - *Proposal for Silas:* Use `TRACKS.get(tier, tier) == "hard"` (or `tier in ("hard", "hard_forge", "hard_rl")`) in `canary/world.py:121` when regenerating `hard_rl` worlds in a future version bump.
2. **`ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14` (Low - `canary/forge_track.py:23`, `data/forge/`):**
   - `DEFAULT_HOF` in `canary/forge_track.py` still defaults to `hall_of_fame_v1.2.jsonl` when `CANARY_FORGE_HOF` is unset, and upstream `58716742` does not ship `data/forge/hall_of_fame_v1.4.jsonl`. Both `hall_of_fame_v1.2.jsonl` (`0.8350` solver accuracy) and `hall_of_fame_v1.3.jsonl` (`0.9700` solver accuracy) remain clean and above `MIN_ACC = 0.75` on `v1.4`.
3. **`ISSUE-W6-ARENA-LLM-MOLE-SURFACE` (Low - `canary/agents/mole_arena.py:35-83`, `canary/env.py:559-562`):**
   - Non-judge `LLMMole` exposes `doc_id` (`c`-prefix vs `d`-prefix) and `title` in `view_to_dict` and omits `if not view.can_leak` in `LLMMole.decide`. Judge tracks (`hard`, `hard_forge`, `hard_rl`) exclusively use `MoleStrategy` and `RLMole`, which are verified zero-leak in Part A.
   - *Proposal for Silas:* Redact `doc_id` to positional indices in `LLMMole` prompts and enforce `if not view.can_leak: leak = None` inside `Env._advance_to` after calling custom `mole_strategy.decide`.
