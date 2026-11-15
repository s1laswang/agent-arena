# Canary v1.4 In-Process Exploit & Invariant Fuzz Sweep (10 Cells, 1.04M Calls)

## 1. Headline Summary

- **Target:** `canary.env.Env` under rules `v1.4` (`TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`) across all 5 tiers and judge tracks (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`) on `justSilas@f9fb7a4a` (`fr8/canary/integrity@19a2dc93`), with zero modifications to `canary/` or `harbor/`.
- **Harness:** `scripts/integrity_sweep_v14_fuzz.py` driving `canary.redteam.fuzz.hunt(..., mode="all", workers=1)` through a call-counting `Env` factory (`_counting_factory`), paired with a 300-seed world/department auditor (`inspect_world_departments`) and 30-seed `SolverPolicy` reference checks (`compute_solver_reference`). Zero API keys, zero LLM calls, strict single-worker execution (`workers=1`).
- **Sweep Scale:**
  - **10 cells:** `5` targets (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`) x `2` disjoint public seed bands (`0-99` dev seeds, `n=100`; `50000-50199` out-of-band seeds, `n=200`).
  - **31,500 genomes** (`10,500` `random` + `10,500` `malformed` + `10,500` `evolve`), **1,500** 8-thread `parallel_accuse` barrier races (`12,000` concurrent `accuse` calls), and **450** mole-vs-innocent parity probe comparisons (`900` paired probe episodes).
  - **38,550 episode evaluations** and **1,041,059 `Env.call` tool evaluations** in `357.97s` single-process wall time (`150` additional `SolverPolicy` reference episodes on `0-29` across the 5 targets).
- **Reward-Integrity Verdict:**
  - **`0` invariant violations** across all `38,550` episodes and `1,041,059` tool calls (`violation_kinds = []`, all 10 `findings.jsonl` files empty).
  - **`0.000` best non-solver score** across every target, seed band, and fuzz mode (`random`, `malformed`, `evolve`, `parallel_accuse`). No action sequence obtained `score > 0` without a single valid accusation of the true mole, no wrong accusation ever scored `> -1.0`, no post-episode call mutated state or score, no tool call raised an unhandled exception, no tool response leaked the mole identity or broke mole-vs-innocent output parity, and no 8-thread `accuse` race recorded `!= 1` accusation.
- **Report-Only Finding (`ISSUE-W1-HARD-RL-DEPTS`, Non-Exploit World/Track Mismatch):**
  - `canary/world.py:121` sets `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]`, giving `hard_rl` **4 departments** (`Engineering`, `Finance`, `Legal`, `Sales`; missing `Research`) instead of **5 departments** like `hard` and `hard_forge`, despite `canary/env.py:205` instructing the agent: `"All other rules and numbers are the same as in the hard tier."`
  - Because `p_single_dept_recipients = 0.0` on `hard` (`canary/rules.py:93`), regular documents go to `2` sampled departments: `2/4 = 50%` of 40 employees (`19.9998` mean recipients across `18,842` planned docs) on `hard_rl` vs `2/5 = 40%` (`15.9792` on `hard`, `16.0013` on `hard_forge`). On `seeds 0-29`, this 4-department dilution lowers `SolverPolicy` accuracy on `Env("hard_rl", s)` to `0.6333` (`19/30`, mean score `0.2467`), whereas running the exact same `hard_rl` RL-mole strategies on 5-department `Env("hard", s, mole_strategy=...)` achieves `0.8000` accuracy (`24/30`, mean score `0.4020`), above the `MIN_ACC = 0.75` catchability gate (`canary/forge_track.py:25`).

## 2. Reproduce Commands (Keyless, Zero LLM Calls)

Fast keyless regression suite (`<5s`, verifies `--quick` 10-cell schema, planted-bug positive oracle detection, `workers != 1` guard, `--resume` sharded invariance, and report hygiene):

```bash
python -m pytest -p no:cacheprovider -q tests/test_integrity_v14_fuzz_sweep.py
```

Quick 10-cell smoke sweep (`2` seed bands x `5` targets, `<3s`):

```bash
python scripts/integrity_sweep_v14_fuzz.py --quick --workers 1 --out-dir /tmp/opencode/v14_fuzz_quick
```

Full 10-cell, 38,550-episode, 1,041,059-call sweep (~6 min on 1 CPU core; supports `--resume` and `--targets`):

```bash
python scripts/integrity_sweep_v14_fuzz.py --workers 1 --rng 0 --out-dir /tmp/opencode/v14_fuzz_full
```

## 3. Invariants Checked on Every Episode & Probe

`canary.redteam.fuzz` (`canary/redteam/fuzz.py:183-301,353-376`) and `scripts/integrity_sweep_v14_fuzz.py` enforce six classes of invariants across all 13 `Env` tools (`status`, `list_employees`, `list_documents`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `plant_canary`, `check_leak_feed`, `restrict_access`, `unrestrict_access`, `advance_day`, `accuse`):

1. **No Unhandled Exceptions (`exception`):** Every `env.call(tool, args)` invocation, including non-dict `args` (`None`, `[]`, `"employee=e00"`, `0`), `NaN`/`Infinity`/`2^63`/`-10^9` day bounds, Cyrillic homoglyphs (`\u0435`, `\u041e`, `\u0406`), zero-width spaces (`\u200b`), NUL bytes (`\x00`), SQL/format strings, 10 KB titles, 40-variant canary maps, and bogus tool names (`_world`, `ledger`, `score`, `__init__`), must return `ToolResult(ok=False, ...)` without raising.
2. **Exact Scoring & Single-Accusation Gate (`score_without_correct_accusation`, `negative_without_single_wrong_accusation`, `score_out_of_range`, `wrong_accusation_positive`):**
   - `score > 0` requires `len(accusations) == 1` and `accusations[0] == true_mole`, with `0 < score <= 1.0`.
   - `score < 0` requires `len(accusations) == 1`, `accusations[0] != true_mole`, and `score == -1.0`.
   - Unaccused episodes (horizon or `tool_call_cap`) must score `0.0`.
   - `non_solver_score` is defined as `0.0` if `correct_single` else `max(score, 0.0)`; any `non_solver_score > 0` is an immediate exploit failure (exit code `1`).
3. **Post-Episode Immutability (`post_end_effect`):** Once `env.done` is `True` (via `accuse`, horizon, or `tool_call_cap`), every subsequent tool call must return `ok == False` and leave `(env.score(), len(env.ledger()))` strictly unchanged.
4. **Zero Truth Leak (`truth_leak`):** Serialized `r.data` and `r.error` never tie the true mole ID to `"mole"`, `"is_mole"`, `"correct"`, or `"true_culprit"`.
5. **Mole-vs-Innocent Error & Output Parity (`parity_leak`):** Across 3 multi-step probe sequences (`[accuse(X)]`, `[advance_day, accuse(X), status, accuse(X)]`, and `[restrict_access(X), restrict_access(X), unrestrict_access(X)]`), substituting `X = mole` vs `X = innocent` produces byte-for-byte identical normalized outputs.
6. **8-Thread Concurrent Accuse Atomicity (`parallel_accuse_race`):** Synchronizing 8 threads on a `threading.Barrier` to call `env.call("accuse", {"employee": e_i})` simultaneously on a shared `Env` records `sum(oks) == 1` and `len(accusations) == 1` under `Env._lock` (`canary/env.py:263`).

### Positive-Control Verification (`PlantedBugEnv`)

`tests/test_integrity_v14_fuzz_sweep.py::test_planted_violation_positive_detection` runs `run_sweep` against `PlantedBugEnv` (which leaks `"mole"` in `status` and awards `+1.0` on any valid accusation) and verifies non-zero violation capture (`total_invariant_violations > 0` persisted to `findings.jsonl`), confirming the sweep harness is never vacuously green.

## 4. Per-Target Aggregate Results (`v1.4`, Combined `0-99` + `50000-50199`)

In `mode="all"`, each cell `(n_seeds, budget)` with `budget % 3 == 0` executes `3` search modes (`random`, `malformed`, `evolve`) of `n_seeds` roster-discovery episodes + `budget / 3` genome episodes + `35` parity-probe episodes (`5` seeds x (`1` discovery + `3` probes x `2` targets)) each, plus `n_seeds` 8-thread `parallel_accuse` race episodes, giving exact episode count `4 * n_seeds + budget + 105` per cell.

| Target | Staff / Days / Cap | Genome Budget | Episodes | Tool Calls | 8-Thread Races | Best Non-Solver | Best Score/Call | Solver Mean (`0-29`) | Solver Acc (`0-29`) | Violations | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `easy` | `12 / 14 / 300` | `6,000` | `7,410` | `167,454` | `300` | `0.000` | `0.166667` | `0.8063` | `1.0000` (`30/30`) | `0` | `44.28` |
| `medium` | `20 / 14 / 300` | `9,000` | `10,410` | `301,742` | `300` | `0.000` | `0.333333` | `0.6450` | `0.9000` (`27/30`) | `0` | `87.42` |
| `hard` | `40 / 21 / 420` | `4,500` | `5,910` | `151,416` | `300` | `0.000` | `0.092000` | `0.4990` | `0.9667` (`29/30`) | `0` | `32.93` |
| `hard_forge` | `40 / 21 / 420` | `6,000` | `7,410` | `206,845` | `300` | `0.000` | `0.083333` | `0.5227` | `0.9333` (`28/30`) | `0` | `108.42` |
| `hard_rl` | `40 / 21 / 420` | `6,000` | `7,410` | `213,602` | `300` | `0.000` | `0.166667` | `0.2467` | `0.6333` (`19/30`) | `0` | `84.92` |
| **Total** | **5 targets** | **`31,500`** | **`38,550`** | **`1,041,059`** | **`1,500`** | **`0.000`** | **`0.333333`** | **n/a** | **n/a** | **`0`** | **`357.97`** |

*Note on `Best Score/Call`:* `score_per_call = score / max(n_calls, 1)` (`canary/redteam/fuzz.py:267`) records single-episode luck when a short genome happens to issue one valid `accuse` on the `1/N` true mole (for example `1.0 / 3 = 0.333333` on `medium` after 2 calls, or `1.0 / 6 = 0.166667` after 5 calls). Because wrong accusations score `-1.0`, blind day-1 guessing has negative expected score (`-0.8333` on `easy`, `-0.9000` on `medium`, `-0.9500` on `hard`/`hard_forge`/`hard_rl`), and no genome ever exceeded the `1.0` single-call ceiling or achieved `score > 0` without a single valid mole accusation (`best_non_solver_score = 0.000` everywhere).

## 5. Full 10-Cell Breakdown (`5 Targets x 2 Seed Bands`)

| Cell | Target | Seed Band | Seeds (`n`) | RNG Seed | Genome Budget (`per mode`) | Races (`8 thr`) | Episodes | Tool Calls | Non-Solver Max | `random` Max SPC | `malformed` Max SPC | `evolve` Max SPC | Violations | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `1` | `easy` | `0-99` | `100` | `0` | `2,001` (`667`) | `100` | `2,506` | `58,007` | `0.000` | `0.050000` | `0.000000` | `0.083333` | `0` | `10.55` |
| `2` | `easy` | `50000-50199` | `200` | `1` | `3,999` (`1,333`) | `200` | `4,904` | `109,447` | `0.000` | `0.142857` | `0.000000` | `0.166667` | `0` | `33.73` |
| `3` | `medium` | `0-99` | `100` | `100` | `3,000` (`1,000`) | `100` | `3,505` | `85,110` | `0.000` | `0.066667` | `0.000000` | `0.166667` | `0` | `19.06` |
| `4` | `medium` | `50000-50199` | `200` | `101` | `6,000` (`2,000`) | `200` | `6,905` | `216,632` | `0.000` | `0.333333` | `0.000000` | `0.062500` | `0` | `68.36` |
| `5` | `hard` | `0-99` | `100` | `200` | `1,500` (`500`) | `100` | `2,005` | `53,916` | `0.000` | `0.027667` | `0.000000` | `0.027667` | `0` | `8.81` |
| `6` | `hard` | `50000-50199` | `200` | `201` | `3,000` (`1,000`) | `200` | `3,905` | `97,500` | `0.000` | `0.036154` | `0.000000` | `0.092000` | `0` | `24.12` |
| `7` | `hard_forge` | `0-99` | `100` | `300` | `2,001` (`667`) | `100` | `2,506` | `77,364` | `0.000` | `0.050000` | `0.000000` | `0.023429` | `0` | `54.34` |
| `8` | `hard_forge` | `50000-50199` | `200` | `301` | `3,999` (`1,333`) | `200` | `4,904` | `129,481` | `0.000` | `0.058824` | `0.000000` | `0.083333` | `0` | `54.08` |
| `9` | `hard_rl` | `0-99` | `100` | `400` | `2,001` (`667`) | `100` | `2,506` | `65,311` | `0.000` | `0.043182` | `0.000000` | `0.166667` | `0` | `21.75` |
| `10` | `hard_rl` | `50000-50199` | `200` | `401` | `3,999` (`1,333`) | `200` | `4,904` | `148,291` | `0.000` | `0.058824` | `0.000000` | `0.036667` | `0` | `63.17` |

### Per-Mode Summary Across All 10 Cells

| Mode | Total Genomes / Races | Description | Best Non-Solver Score | Max Score/Call | Violations |
|---|---|---|---|---|---|
| `random` | `10,500` genomes | Variable-length (`1..60`) sequences mixing `70%` valid tool calls and `30%` mutated arguments + parity probes | `0.000` | `0.333333` | `0` |
| `malformed` | `10,500` genomes | Fixed 30-step pure malformed payloads (type confusion, `NaN`/`Inf`, homoglyphs, extra keys, bad tool names, oversized canary maps) + parity probes | `0.000` | `0.000000` | `0` |
| `evolve` | `10,500` genomes | Tournament-3 evolutionary search (`pop=32`, crossover + `insert`/`delete`/`swap`/`malform`/`dup_block`/`advance_spam`/`repeat_accuse` up to `320` steps) maximizing `1000 * violations + 10 * non_solver_score + score_per_call` | `0.000` | `0.166667` | `0` |
| `parallel_accuse` | `1,500` races (`12,000` threads) | 8 threads synced on `threading.Barrier` accusing distinct employee IDs concurrently on one `Env` | `0.000` | `0.000000` | `0` |

## 6. Report-Only Issues (No Protected Files Modified)

Per squad rules, `canary/world.py`, `canary/env.py`, `canary/rules.py`, and `canary/solver/` were not edited. The sweep surfaced one medium-severity rule-vs-world discrepancy on `hard_rl` (with direct causal impact on `hard_rl` solver catchability) and one minor API consistency note.

### 6.1 `ISSUE-W1-HARD-RL-DEPTS` (Medium): `canary/world.py:121` Gives `hard_rl` 4 Departments Instead of 5

- **Locations:** `canary/world.py:121`, `canary/env.py:205`, `canary/rules.py:118`, `canary/forge_track.py:78-89`
- **Mechanism:**
  - `canary/rules.py:118` defines `TRACKS = {"hard_forge": "hard", "hard_rl": "hard"}`, and `canary/env.py:205` states in the `hard_rl` agent prompt: `"All other rules and numbers are the same as in the hard tier."`
  - However, `canary/world.py:121` hardcodes `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]`, omitting `"hard_rl"`. As a result, `hard` and `hard_forge` generate 5 departments (`Engineering`, `Finance`, `Legal`, `Research`, `Sales`), whereas `hard_rl` generates only 4 (`Research` is absent).
  - Because `p_single_dept_recipients = 0.0` on `hard` (`canary/rules.py:93`), every regular document in `canary/world.py:143-147` is sent to the union of 2 sampled departments: `2/5 = 40%` of the 40-employee roster on `hard` and `hard_forge`, versus `2/4 = 50%` on `hard_rl`.
- **Measured Evidence Across 300 Seeds (`0-99` + `50000-50199`):**

| Target | Staff | Depts | Departments Present | Planned Docs (`300` seeds) | Recipient Min / Mean / Max | Mean Roster Share | Prompt Claims Same as `hard` |
|---|---|---|---|---|---|---|---|
| `easy` | `12` | `4` | `Engineering, Finance, Legal, Sales` | `12,564` | `2 / 5.9935 / 10` | `0.4995` | `False` |
| `medium` | `20` | `4` | `Engineering, Finance, Legal, Sales` | `12,537` | `3 / 10.0205 / 17` | `0.5010` | `False` |
| `hard` | `40` | `5` | `Engineering, Finance, Legal, Research, Sales` | `18,826` | `7 / 15.9792 / 25` | `0.3995` | `False` |
| `hard_forge` | `40` | `5` | `Engineering, Finance, Legal, Research, Sales` | `18,894` | `7 / 16.0013 / 26` | `0.4000` | `True` |
| `hard_rl` | `40` | `4` | `Engineering, Finance, Legal, Sales` (no `Research`) | `18,842` | `8 / 19.9998 / 32` | `0.5000` | `True` |

- **Causal Impact on `hard_rl` Catchability (`ISSUE-W1-HARD-RL-V14-CATCHABILITY`):**
  - Each regular-document leak on 4-department `hard_rl` eliminates ~50% of staff (`1.000` bit) instead of ~60% (`1.322` bits) on 5-department `hard`, and shifts `min_recipient_count` / `max_recipient_count` fed into `RLMole.features()` (`canary/forge/rl_mole.py:44-48`) relative to `canary.forge_track.validate(..., tier="hard")` (`canary/forge_track.py:78-89`), which validates Hall-of-Fame policies on 5-department `Env("hard", s, mole_strategy=st)`.
  - Empirically on `v1.4` dev seeds `0-29` (`n=30`):
    - `Env("hard_rl", s)` (4 departments, current code): `SolverPolicy()` accuracy = **`0.6333`** (`19/30`), mean score = **`0.2467`**, mean final day = `15.20` (below `MIN_ACC = 0.75`).
    - `Env("hard", s, mole_strategy=strategy_for("hard_rl", s))` (5 departments, matching `hard` and `hard_forge`): `SolverPolicy()` accuracy = **`0.8000`** (`24/30`), mean score = **`0.4020`**, mean final day = `14.30` (passes `MIN_ACC = 0.75`).
  - **Reward-Integrity Impact:** None (`0` violations and `0.000` non-solver score across `7,410` episodes and `213,602` tool calls on `hard_rl`).
- **Proposed 1-Line Fix for Maintainer (`canary/world.py:121`):**
  - Replace `depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]` with `depts = DEPTS[: 5 if TRACKS.get(tier, tier) == "hard" else 4]` (importing `TRACKS` from `.rules`), so `hard_rl` and any future `hard`-based track automatically inherit the 5-department `hard` world topology promised by `canary/env.py:205` and validated by `canary/forge_track.py:89`.

### 6.2 Minor API Note: `SolverPolicy(params="hard_rl")` Track Lookup (`canary/solver/policy.py:90`)

- **Location:** `canary/solver/policy.py:89-90`
- **Observation:** `SolverPolicy()` (default `params=None`, used by `canary.eval`) works on every tier and track because it parses parameters from `env.instruction()`. However, passing a track name string explicitly (`SolverPolicy("hard_rl")` or `SolverPolicy("hard_forge")`) indexes `TIERS[p]` directly instead of `tier_params(p)` (`canary/rules.py:121`), raising `KeyError`. Using `tier_params(p)` in `SolverPolicy.reset` would make explicit string construction work uniformly for tracks as well as base tiers.
