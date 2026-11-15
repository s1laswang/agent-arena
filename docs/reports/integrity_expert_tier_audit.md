# Integrity, Calibration, Fuzz & Final `n=13` Verdict Audit: `justSilas-expert` (`29ca3bc5`)

## 1. Headline Summary

- **Target Audited:** `origin/justSilas-expert` @ `29ca3bc5` (`29ca3bc51c82c47e50261b206f89dd117e6543b0`), introduced at `036b90c7` (`EXPERT_TIERS["expert"]`, `EXPERT_RULES_VERSION = "v1.6"` outside frozen `TIERS` `TIERS_VERSION = "v1.4"`, identical to `v1.4` `hard` except `name="expert"` and `fingerprint_accuracy=0.70` vs `hard` `0.95`) and recorded as non-shipping in `docs/reports/gap.md` (`244434fc`, carried forward into `justSilas` @ `f9fb7a4a` and `e1d5948f`).
- **Base Branch & Constraints:** Packaged on `fr8/canary/integrity` (`62d258cd`, synced with `origin/justSilas` @ `e1d5948f`) with **zero edits to protected files** (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`), `--workers 1`, and **`0` live LLM/API calls**.
- **Harness:** `scripts/integrity_expert_tier_audit.py` with both `--expert-root` full worktree audit mode and `<15s` standalone keyless `--self-test` mode on `justSilas`.
- **Reward, State & Anti-Cheat Integrity Verdict: HELD (`0` exploits, `0` invariant violations).**
  - **20,000-episode multi-mode fuzzer sweep** (`--tier expert --seeds 71000-71199 --budget 20000 --mode all --workers 1`, `92.25s`): **`best_non_solver_score = 0.0`**, **`0` invariant violations** across `random` (`6,666`), `malformed` (`6,666`), `evolve` (`6,666`), and `parallel_accuse` (`200` 8-thread barrier races).
  - **200-seed `V` & `known_V` redaction audit** (`seeds 71000-71199`, `8,200` steps checked, `5,570` hidden-leak states, `1.93s`): **`0` `true_V` rises**, **`0` `known_V` rises**, **`0` `known_V` formula mismatches**, **`0` hidden-leak exposures**, and verified `score()` uses `true_V` rather than `known_V` when unsurfaced leaks exist.
  - **200-seed 11-policy baseline & exploit ladder** (`seeds 71000-71199`, `131.47s`): `do_nothing = 0.0000`, `stop_early = 0.0000`, `restrict_all = -1.0000`, `accuse_decoy = -0.9808`, `guess_day1 = -0.9800`, `logs_only = -0.9650`, `accuse_most_logs = -0.9250`, `heuristic = -0.5297 +- 0.0899`, `swarm_w2b008 = 0.0479 +- 0.0930`, `grok_tactics = 0.0808 +- 0.0893`, and `solver = 0.4071 +- 0.0448` (`84.0%` overall accuracy, `97.11%` accuracy when accusing). Scripted single-hit canary heuristics collapse (`grok_tactics` drops from `0.361` on `hard` to `0.011` on `expert` over `n=400` fresh seeds `70000-70399`, and `swarm_w2b008` drops to `0.0479` on `71000-71199`) while `SolverPolicy(None)` stays strongly positive.
- **Final `n=13` Verdict & Ship-Gate Audit (`results/expert_verdict.json` @ `29ca3bc5`): RIGHTLY DROPPED.**
  - **Exact numerical & paired-solver verification:** All `13` paired `SolverPolicy(None)` replays on `justSilas-expert@29ca3bc5` match `results/expert_verdict.json` to `0.0` score discrepancy (`gemini_mean = 0.5308` vs `solver_mean = 0.2962`, raw ratio `179.2% [91.7%, 1254.4%]`; `luck_adj_gemini = 0.3727` vs `luck_adj_solver = 0.4413`, luck-adjusted ratio **`84% [52%, 128%]`** (`0.8445 [0.5239, 1.2778]`), matching `docs/reports/gap.md` verbatim).
  - **Four independent ship-bar blockers confirmed:** (1) `n=13 < 30` minimum paired sample size (`PLAN-95` Track 2); (2) luck-adjusted 95% CI `[52%, 128%]` spans parity (`1.00`) while raw ratio is `179%`; (3) `gemini-4-carbon` went `13/13` correct (`84%` luck-adjusted vs `72% [52%, 91%]` on `v1.4` `hard` `n=30`), confirming it did **not** over-trust single canary hits (`2/13` single-hit accusations vs solver's `4/12`) and did not widen the frontier gap; and (4) **`0` raw OpenCode `expert` episode transcripts (`episodes.jsonl`)** were committed under `data/`, leaving `results/expert_verdict.json` summary-only without git-replayable frontier trajectories.
- **Five Report-Only Compatibility & Tooling Issues Identified (`EXP-BUG-01` .. `EXP-BUG-05`):**
  1. **`EXP-BUG-01` (High):** `canary/world.py:121` (`TRACKS.get(tier, tier) in ("hard", "expert")`) silently changed `hard_rl` from `4` departments on `justSilas` to `5` departments on `justSilas-expert` (`036b90c7`), altering `mole`, `decoy`, employee roster, and document recipients across every `hard_rl` seed (`0, 1, 7, 4000`) while `tests/test_expert_tier.py:16` omitted `hard_rl` from `PINNED`.
  2. **`EXP-BUG-02` (Medium):** `SolverPolicy("expert")` raises `KeyError: 'expert'`, `solver.params._from_exact_block` and `tier_from_instruction` return `None`, `_params_from_prose` returns `None` without the full bullet block, empty-instruction fallback mis-infers `fingerprint_accuracy=0.95`, and `default_threshold()` falls back to `0.90` instead of `0.85`.
  3. **`EXP-BUG-03` (Medium):** `harbor/build.py --tiers expert` exits `rc=2` (`unknown tier 'expert'`), `scripts/gemini_runner.py --tiers-version v1.6` exits `rc=2` against `TIERS_VERSION='v1.4'`, and `anticheat.replay_committed` marks `tiers_version == 'v1.6'` episodes `not_replayable`.
  4. **`EXP-BUG-04` (Low):** `canary.redteam.encodings.audit_env_no_encoded_leak("expert", ...)` raises `ValueError: unknown tier expert` and `canary.eval --tier all` omits `EXPERT_TIERS`.
  5. **`EXP-BUG-05` (High):** `scripts/expert_verdict.py:40,117` checks `meta["V"]` instead of `meta["V_final"]` (under-reporting `gemini.below_break_even` as `0` instead of `3/13` on seeds `60003`, `60012`, `60019`), filters `end_reason != "error"` on OpenCode runs (silently dropping any unaccused timeout or abstention), and has `0` committed raw OpenCode `expert` transcripts in git.

## 2. Reproduce Commands (Keyless, Zero API Calls)

Run the fast standalone self-test, report validator, and unit test suite on `justSilas` (`<15s`, zero external worktree or API keys required):

```bash
python scripts/integrity_expert_tier_audit.py --self-test --check-report docs/reports/integrity_expert_tier_audit.md
python -m pytest -p no:cacheprovider -q tests/test_integrity_expert_tier_audit.py
```

Reproduce the full 20,000-episode fuzz sweep, 200-seed 11-policy ladder, 200-seed `known_V` audit, paired solver replay, and cross-branch `world_seed` digest comparison against a checkout of `origin/justSilas-expert` (`29ca3bc5`, `--workers 1`):

```bash
python scripts/integrity_expert_tier_audit.py --expert-root /path/to/justSilas-expert --seeds 71000-71199 --budget 20000 --workers 1
```

## 3. Final `n=13` Verdict, Paired Replay & DATA-RULE Audit (`results/expert_verdict.json` @ `29ca3bc5`)

### 3.1 Aggregate Verdict Verification & Missing-Seed Sensitivity

Every aggregate metric in `results/expert_verdict.json` (`29ca3bc5`) was independently recomputed from `per_seed` and paired against deterministic `SolverPolicy(None)` replays on `Env("expert", seed)` across seeds `60000..60020`:

| Metric | Recorded (`29ca3bc5`) | Recomputed / Paired Replay | Abs Diff | Audit Status |
|---|---|---|---|---|
| Valid paired seeds (`n`) | `13` | `13` (`60001..60020` subset) | `0` | Verified (`n < 30` ship bar) |
| `gemini_mean` (`opencode:google/gemini-4-carbon`) | `0.530769` | `0.530769` (`13/13` correct) | `0.000000` | Exact match |
| `solver_mean_same_seeds` (`SolverPolicy(None)`, `thr=0.90`) | `0.296154` | `0.296154` (`10` right, `2` `-1.0`, `1` abstain) | `0.000000` | Exact `13/13` replay match |
| Raw `ratio` `[95% bootstrap CI]` (`10,000` resamples) | `1.792208 [0.917404, 12.543860]` | `1.792208 [0.917404, 12.543860]` | `0.000000` | Exact match (`179% [92%, 1254%]`) |
| `luck_adj_gemini` (`mean(P*V - (1-P))`) | `0.372692` | `0.372692` | `0.000000` | Exact match |
| `luck_adj_solver` (`mean(P*V - (1-P))`) | `0.441334` | `0.441334` | `0.000000` | Exact `13/13` replay match |
| **`luck_adj_ratio` `[95% bootstrap CI]`** | **`0.844468 [0.523919, 1.277849]`** | **`0.844468 [0.523919, 1.277849]`** | **`0.000000`** | **Exact match (`84% [52%, 128%]` in `gap.md`)** |
| `gemini.mean_P_at_accusation` | `0.899692` | `0.899692` | `0.000000` | Exact match |
| `solver.mean_P_at_accusation` (`12` accused) | `0.948500` | `0.948500` | `0.000000` | Exact match |
| `single_canary_hit_accusations` (Gemini / Solver) | `2` / `4` | `2` (`60002, 60013`) / `4` (`60002, 60011, 60015, 60020`) | `0` / `0` | Exact match |
| **`gemini.below_break_even` ($P < 1/(1+V)$)** | **`0`** | **`3` (`60003, 60012, 60019`)** | **`3` (`EXP-BUG-05`)** | **`meta["V"]` vs `meta["V_final"]` bug** |
| `SolverPolicy(None, threshold=0.85)` same-seeds mean | n/a | `0.315385` (`60005`: `0.39 -> 0.45`, `60013`: `0.00 -> 0.19`) | `+0.019231` | Minor effect (`EXP-BUG-02`) |
| Sensitivity if missing `60001-60020` (`7` seeds) = `0.0` (`n=20`) | n/a | Raw `0.9091 [0.4888, 2.5376]`, Luck `0.5407 [0.2837, 0.8496]` | n/a | Uncommitted staging bound |
| Sensitivity if missing `60000-60020` (`8` seeds) = `0.0` (`n=21`) | n/a | Raw `0.8880 [0.4721, 2.4662]`, Luck `0.5367 [0.2793, 0.8437]` | n/a | Uncommitted staging bound |
| Committed tree replay (`anticheat.replay_committed`) | `819/829` (`anticheat_expert`) | `959/969` consistent, `0` step mismatches (`47,586` steps) | `0` mismatches | `0` raw `expert` OpenCode JSONLs in `data/` |

### 3.2 Seed-by-Seed Audit (`n=13` Paired Episodes in `results/expert_verdict.json`)

For all `13` valid Gemini episodes, `gemini_correct == True` implies `score == V_at_accusation` on the exact cent grid (`0` score-range or cent-grid violations). Three Gemini accusations (`60003`, `60012`, `60019`) had posterior $P < 1/(1+V)$ and negative luck-adjusted expected value despite landing on the true mole:

| Seed | Gemini Score (`V`) | Gemini Correct | Gemini `P` | Break-Even `1/(1+V)` | Gemini Luck-Adj EV | Below Break-Even? | Gemini 1-Hit? | Solver Score | Solver `P` | Solver `V` | Solver Luck-Adj EV | Solver 1-Hit? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `60001` | `0.46` | `True` | `0.995` | `0.684932` | `+0.452700` | `False` | `False` | `-1.00` (wrong) | `0.971` | `0.51` | `+0.466210` | `False` |
| `60002` | `0.42` | `True` | `0.970` | `0.704225` | `+0.377400` | `False` | `True` | `+0.66` | `1.000` | `0.66` | `+0.660000` | `True` |
| **`60003`** | **`0.47`** | **`True`** | **`0.645`** | **`0.680272`** | **`-0.051850`** | **`True`** | `False` | `+0.58` | `0.943` | `0.58` | `+0.489940` | `False` |
| `60004` | `0.69` | `True` | `0.965` | `0.591716` | `+0.630850` | `False` | `False` | `+0.60` | `1.000` | `0.60` | `+0.600000` | `False` |
| `60005` | `0.44` | `True` | `0.982` | `0.694444` | `+0.414080` | `False` | `False` | `+0.39` | `0.917` | `0.39` | `+0.274630` | `False` |
| `60010` | `0.41` | `True` | `1.000` | `0.709220` | `+0.410000` | `False` | `False` | `-1.00` (wrong) | `0.906` | `0.33` | `+0.204980` | `False` |
| `60011` | `0.59` | `True` | `0.970` | `0.628931` | `+0.542300` | `False` | `False` | `+0.69` | `1.000` | `0.69` | `+0.690000` | `True` |
| **`60012`** | **`0.59`** | **`True`** | **`0.586`** | **`0.628931`** | **`-0.068260`** | **`True`** | `False` | `+0.44` | `0.947` | `0.44` | `+0.363680` | `False` |
| `60013` | `0.66` | `True` | `1.000` | `0.602410` | `+0.660000` | `False` | `True` | `0.00` (abstain) | `None` | `0.00` | `0.000000` | `None` |
| `60015` | `0.41` | `True` | `1.000` | `0.709220` | `+0.410000` | `False` | `False` | `+0.78` | `0.909` | `0.78` | `+0.618020` | `True` |
| `60016` | `0.58` | `True` | `1.000` | `0.632911` | `+0.580000` | `False` | `False` | `+0.61` | `0.924` | `0.61` | `+0.487640` | `False` |
| **`60019`** | **`0.66`** | **`True`** | **`0.583`** | **`0.602410`** | **`-0.032220`** | **`True`** | `False` | `+0.32` | `0.951` | `0.32` | `+0.255320` | `False` |
| `60020` | `0.52` | `True` | `1.000` | `0.657895` | `+0.520000` | `False` | `False` | `+0.78` | `0.914` | `0.78` | `+0.626920` | `True` |

Why raw ratio (`179.2%`) diverges from luck-adjusted ratio (`84.4%`): with `fingerprint_accuracy = 0.70`, even a well-calibrated posterior (`P = 0.971` on `60001`, `P = 0.906` on `60010`) occasionally suffers a multi-canary misattribution flip, costing the solver two `-1.00` realizations on this 13-seed slice while Gemini's three sub-break-even gambles (`P = 0.645, 0.586, 0.583`) happened to hit `3/3`. Scoring each accusation by exact Bayesian EV $P \cdot V - (1 - P)$ removes realization variance and places Gemini at `84% [52%, 128%]` of the solver.

## 4. Reward, State & Baseline Calibration Sweep (`origin/justSilas-expert @ 29ca3bc5`, Seeds `71000-71199`)

### 4.1 Multi-Mode Fuzz, `known_V` Redaction, and Env/MCP Gate Summary

| Check Suite | Seeds / Scope | Budget / Volume | Headline Result | Pass |
|---|---|---|---|---|
| `canary.redteam.fuzz` (`--mode all --workers 1`) | `71000-71199` (`200` seeds) | `20,000` (`6,666` `random` + `6,666` `malformed` + `6,666` `evolve` + `200` x 8-thr `parallel_accuse`), `92.25s` | `best_non_solver_score = 0.0`, `0` invariant violations (`best_score_per_call = 1.0` valid Day-1 `accuse`) | `True` |
| `known_V` & `true_V` redaction audit | `71000-71199` (`200` seeds) | `8,200` steps checked, `5,570` unsurfaced-leak states, `1.93s` | `0` `true_V` rises, `0` `known_V` rises, `0` formula mismatches, `0` hidden-leak exposures, `score() == true_V < known_V` verified | `True` |
| `Env("expert", ...)` parameter & cap enforcement | `71000-71003` | `40` staff, `5` depts, clearances `[1,2,3]` | `420`-call cap (`score=0.0`, post-cap `accuse` blocked), `2` canaries/day, `3` max variants, `8` actions/day | `True` |
| `mcp_server.Episode("expert", ...)` security | `0` (dev), `900000` (judge) | 8-thread barrier race + HMAC tamper probe | Dev seed `0` blocked without `CANARY_ALLOW_DEV`, mid-episode ledger redacted, `1/8` parallel `accuse` winner, HMAC verified | `True` |
| Committed `results/anticheat_expert/exploits.json` | `20` seeds x `32` rows | `819/829` replayed (`33,593` steps, `0` mismatches) | `all_blocked = True` (`swarm_w2b008` absent there; audited below on `200` seeds) | `True` |

### 4.2 200-Seed 11-Policy Baseline & Exploit Ladder (`Seeds 71000-71199`, `131.47s`)

All `10` non-solver baselines and exploit probes score strictly below `SolverPolicy(None)` on `expert` (`all_checks_pass = True`), matching the `n=400` committed reference slice (`results/expert_fresh_70000.json`, seeds `70000-70399`, where `hard -> expert` moves `solver` `0.543 -> 0.422`, `grok_tactics` `0.361 -> 0.011`, and `heuristic` `0.013 -> -0.573`):

| Policy | `n` | Mean Score (`+-95% CI`) | Min | Max | Episodes `> 0` | Accused Rate | Overall Acc | Acc Among Accused | Invariant Role |
|---|---|---|---|---|---|---|---|---|---|
| `restrict_all` | `200` | `-1.0000 +- 0.0000` | `-1.00` | `-1.00` | `0` | `1.000` | `0.000` | `0.0000` | Strictly negative (`< 0`) |
| `accuse_decoy` | `200` | `-0.9808 +- 0.0266` | `-1.00` | `0.95` | `2` | `1.000` | `0.010` | `0.0100` | Decoy trap negative |
| `guess_day1` | `200` | `-0.9800 +- 0.0276` | `-1.00` | `1.00` | `2` | `1.000` | `0.010` | `0.0100` | Blind guess negative (`~ -38/40 + 1/40`) |
| `logs_only` | `200` | `-0.9650 +- 0.0341` | `-1.00` | `0.85` | `4` | `1.000` | `0.020` | `0.0200` | Access-log framing trap |
| `accuse_most_logs` | `200` | `-0.9250 +- 0.0511` | `-1.00` | `0.95` | `8` | `1.000` | `0.040` | `0.0400` | Naive log count negative |
| `heuristic` | `200` | `-0.5297 +- 0.0899` | `-1.00` | `0.70` | `69` | `1.000` | `0.350` | `0.3500` | Noisy canary intersection collapses |
| `do_nothing` | `200` | `0.0000 +- 0.0000` | `0.00` | `0.00` | `0` | `0.000` | `0.000` | `None` | Exact `0.0000` |
| `stop_early` | `200` | `0.0000 +- 0.0000` | `0.00` | `0.00` | `0` | `0.000` | `0.000` | `None` | Exact `0.0000` |
| `swarm_w2b008` | `200` | `0.0479 +- 0.0930` | `-1.00` | `0.84` | `111` | `0.825` | `0.565` | `0.6848` | Deterministic intersection probe (`<< solver`) |
| `grok_tactics` | `200` | `0.0808 +- 0.0893` | `-1.00` | `0.91` | `132` | `0.895` | `0.660` | `0.7374` | Scripted canary tactic (`heuristic < grok < solver`) |
| **`solver` (`SolverPolicy(None)`)** | **`200`** | **`0.4071 +- 0.0448`** | **`-1.00`** | **`0.81`** | **`168`** | **`0.865`** | **`0.840`** | **`0.9711`** | **Calibrated Bayesian reference** |

## 5. Report-Only Compatibility & Tooling Issues (`origin/justSilas-expert @ 29ca3bc5`)

Per squad rules, zero protected files were modified. Because `expert` was dropped at `29ca3bc5` (`docs/reports/gap.md`), none of `EXP-BUG-01..05` affect shipped `justSilas` (`v1.4`), where `hard_rl` remains 4-department and `TIERS` is frozen; they are documented below as regression guards in case an `expert` or `v1.6` tier is ever revived:

1. **`EXP-BUG-01` (High, Frozen-Tier World Regression): `canary/world.py:121` Mutated `hard_rl` from `4` to `5` Departments.**
   - **Location:** `canary/world.py:121` and `tests/test_expert_tier.py:16` (`origin/justSilas-expert @ 036b90c7`).
   - **Finding:** `justSilas` sets `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]` (`4` departments on `hard_rl`). Commit `036b90c7` rewrote this to `DEPTS[: 5 if TRACKS.get(tier, tier) in ("hard", "expert") else 4]`. Because `TRACKS["hard_rl"] == "hard"`, `hard_rl` silently gained a 5th department (`Research`), altering world SHA-256 digests across all `4` pinned check seeds (`hard_rl:0` `746f0f2bd6fe61fe` mole `e20` decoy `e36` -> `be380767a89ac944` mole `e28` decoy `e23`; `hard_rl:1` `138092858ebbc0f8` -> `befb4a6812702ae5`; `hard_rl:7` `5c32525fda71f82b` -> `aedba98e8ab93fdf`; `hard_rl:4000` `b2b1a0d5648340ed` -> `d437cb8b30c6b4c8`). `tests/test_expert_tier.py` missed the regression because `PINNED` only checked `easy`, `medium`, `hard`, and `hard_forge`.
   - **Recommendation:** Include `hard_rl` in all world-pinning tests (`WORLD_PIN_TIERS = ("easy", "medium", "hard", "hard_forge", "hard_rl")`, enforced in `scripts/integrity_expert_tier_audit.py`) and key department counts off explicit `tier in ("hard", "hard_forge", "expert")`.

2. **`EXP-BUG-02` (Medium, Solver Parameter & Threshold Wiring): `SolverPolicy("expert")` Raises `KeyError` & `default_threshold()` Uses `0.90` Instead of `0.85`.**
   - **Location:** `canary/solver/params.py:63,97` and `canary/solver/policy.py:39,90,147,276`.
   - **Finding:** Because `expert` lives in `EXPERT_TIERS` outside `TIERS`, `SolverPolicy("expert")` raises `KeyError: 'expert'`, `_from_exact_block(ins)` and `tier_from_instruction(ins)` return `None`, `_params_from_prose` returns `None` if the full bullet block is absent, empty-instruction fallback (`policy.py:276`) picks `TIERS["hard"]` (`fingerprint_accuracy=0.95`), and `default_threshold()` returns `0.90` instead of the `hard`-track `0.85` because `tier_from_instruction` is `None`. `SolverPolicy(None)` recovers `fingerprint_accuracy=0.70` only via `_from_param_block(ins)`.
   - **Recommendation:** Resolve named tiers via `rules.tier_params(p)` inside `SolverPolicy.__init__` and include `"expert"` in `_TIER_LINE` / `_EXACT_LINE` if `EXPERT_TIERS` is ever re-enabled.

3. **`EXP-BUG-03` (Medium, Harbor / Runner / Replay Version Guards): `harbor/build.py`, `gemini_runner.py`, and `anticheat.replay_committed` Reject `expert` / `v1.6`.**
   - **Location:** `harbor/build.py:177`, `scripts/gemini_runner.py:155`, `canary/redteam/anticheat.py:501`.
   - **Finding:** `harbor/build.py --tiers expert --seeds 900000` exits `rc=2` (`unknown tier 'expert'; known: easy, medium, hard`), `scripts/gemini_runner.py --tiers-version v1.6 --tiers expert --dry-run` exits `rc=2` (`TIERS_VERSION='v1.4' != --tiers-version 'v1.6'`), and `anticheat.replay_committed` marks `tiers_version == "v1.6"` episodes (`10` rows in `results/anticheat_expert`) `not_replayable`.
   - **Recommendation:** Map `EXPERT_RULES_VERSION` (`"v1.6"`) in `anticheat._env_at_version` and route `harbor/build.py` tier validation through `rules.tier_params` if an external tier is promoted.

4. **`EXP-BUG-04` (Low, Redteam CLI Coverage): Redteam Encoding Probe and `canary.eval --tier all` Omit `EXPERT_TIERS`.**
   - **Location:** `canary/redteam/encodings.py:1292`, `canary/eval.py:23`.
   - **Finding:** `audit_env_no_encoded_leak("expert", [900000])` raises `ValueError: unknown tier expert` because it checks `TIERS` directly rather than `tier_params("expert")`.
   - **Recommendation:** Use `rules.tier_params(tier)` in redteam probes so candidate tiers outside `TIERS` can be scanned without bespoke wrappers.

5. **`EXP-BUG-05` (High, Verdict Accounting & Transcript Provenance): `scripts/expert_verdict.py` `meta["V_final"]` Mismatch, `end_reason != "error"` Filter, and `0` Committed Transcripts.**
   - **Location:** `scripts/expert_verdict.py:40,117-118`.
   - **Finding:** (a) OpenCode MCP episodes record company value at `meta["V_final"]` rather than `meta["V"]`, causing `expert_verdict.py` to report `gemini.below_break_even = 0` when `3/13` episodes (`60003`, `60012`, `60019`) were actually below $1/(1+V)$; (b) filtering `e.get("end_reason") != "error"` drops unaccused OpenCode stops/timeouts instead of checking `meta.valid is not False` and `not str(meta.error).startswith("infra:")`; and (c) `0` raw OpenCode `expert` `episodes.jsonl` files were committed in git.
   - **Recommendation:** Always read `meta.get("V", meta.get("V_final"))`, use the canonical `paired_gemini.py` validity filter (`meta.valid` / `infra:*`), and commit raw `episodes.jsonl` + MCP ledgers alongside any reported frontier verdict.
