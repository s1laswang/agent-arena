# Canary v1.4 Out-of-Band Megahunt, 5x5 Corpus/Transcript Injection, and Ladder Replay Audit (2.24M Calls, 0 API Calls)

## 1. Scope, Post-Hoc Lock Protocol, and Headline Verdict

- **Target:** `canary.env.Env` (`TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`), `data/redteam/corpus.jsonl`, `v1.4` frontier/reference episode transcripts, and `results/gemini/**/ladder*_episodes.jsonl.gz` + `ladder.json` artifacts on `fr8/canary/integrity` (`e19e2bd2`, synced with `justSilas@58716742` including `justSilas@1bc3e281` Panel Fix D `data.detail` error contracts). Zero protected files (`canary/`, `harbor/`) were modified.
- **Zero-LLM / Single-Worker Discipline:** `scripts/integrity_megahunt_and_corpus_v14.py` executes strictly in-process on CPU (`workers = 1`, `rng_seed = 0`) with **0 live LLM or external API calls**. When `data/worlds/judge/SALT` and `CANARY_WORLD_SECRET` are absent in keyless sandboxes, `run_all` installs `DETERMINISTIC_SWEEP_SECRET` (`b"canary-w4-megahunt-deterministic-key-v14"`) and restores prior world-secret state on exit so judge-band (`900000-900039`) and held-out-band (`800000-800099`) worlds are 100% reproducible without external keys.
- **Methodology Lock (`post-hoc lock`):** Seed bands (`900000-900039` and `800000-800099`), fuzz budgets (`900` and `1,500` per target), stateful exploit families (`5` families), `5x5` trajectory injection phases, and `ladder.json` reconciliation tolerances (`1e-9` score/mean parity) operate as a deterministic **post-hoc lock** over the frozen `v1.4` ruleset and committed artifacts.
- **Grand Total Execution (`megahunt_corpus_ladder_summary.json`):**
  - **`2,244,618` total `Env.call` evaluations** in `607.91s` (`1` worker, `all_passed = True`):
    1. **Out-of-Band Megahunt:** `22,150` episodes and `1,845,969` `Env.call`s (`402,474` fuzz + `1,443,495` stateful) across `5` targets x `2` seed bands -> **`0` invariant violations**, **`0.000` best non-solver score**, and `PlantedBugEnv` positive control **`detected = True`** (`244` planted violations caught across `8` violation classes).
    2. **5x5 Corpus + Transcript-Mined Injection & Panel Fix D (`1bc3e281`) Parity:** `219` adversarial shapes (`129` `corpus.jsonl` + `90` mined from `472` `v1.4` episodes / `536` failed steps) injected across `5` targets x `5` trajectory phases (`5,475` phase injections, `4,313` full `SolverPolicy` trajectory completions verified, `410` precondition-blocked checks, `580` `1bc3e281` `data.detail` checks, `70` mole-vs-innocent `data.detail` parity checks; `331,521` `Env.call`s) -> **`0` illegal acceptances**, **`0` state/trajectory corruptions**, **`0` `data.detail` parity mismatches**.
    3. **Ladder `.jsonl.gz` Full Replay & `ladder.json` Cell Reconciliation:** `4` `.jsonl.gz` archives (`1,041 / 1,041` episodes, `67,128` recorded steps = `67,128` replayed `Env.call`s) and `3` `ladder.json` summaries -> **`1,041 / 1,041` (`100%`) replay-consistent**, **`0` step mismatches** (`297` pre-`1bc3e281` `detail`-less error steps cleanly reconciled), **`0` score/V-bound/tool-cap/timeout flags**, and **`100%` native + imported subset reconciliation**.
  - **Report-Only Issues Logged (`3` non-exploit findings, `0` protected-path edits):** `ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER` (`low`), `ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL` (`low`), and `ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL` (`advisory`).

## 2. Reproduce Commands (Keyless, 0 API Calls, `workers=1`)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_megahunt_and_corpus_v14.py

/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_megahunt_and_corpus_v14.py --quick --workers 1 --out-dir /tmp/opencode/integrity_w4_quick --check-report docs/reports/integrity_megahunt_and_corpus_v14.md

/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_megahunt_and_corpus_v14.py --workers 1 --rng 0 --out-dir /tmp/opencode/w4 --check-report docs/reports/integrity_megahunt_and_corpus_v14.md
```

## 3. Part A: Out-of-Band Megahunt (`900000-900039` + `800000-800099`, 1.85M Calls)

### 3.1 Fuzz + Stateful Attack Families and Invariants

Across all `5` targets (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`) and both secret-salted seed bands (`900000-900039`, `n=40`, `fuzz_budget=900`; `800000-800099`, `n=100`, `fuzz_budget=1,500`), `run_megahunt` combines `canary.redteam.fuzz.hunt(..., mode="all", workers=1)` (`random`, `malformed`, `evolve`, `parallel_accuse`) with `5` dedicated white-box stateful exploit families wrapped in `AuditedEnvRunner`:

1. **`restrict_toggle_leak_delay`:** Interleaves `plant_canary`, `restrict_access`, duplicate `restrict_access`, canary-to-restricted-recipient attempts, `check_leak_feed`, and alternating-day `unrestrict_access` / duplicate `unrestrict_access` across the full horizon while verifying `KNOWN_V_MODE` formula parity (`visible_V() == round(max(0.0, 1.0 - leak_damage * surfaced - _costs), 10)`), monotonicity of `V` and `visible_V()`, and zero unsurfaced leak exposure.
2. **`dual_canary_partitions`:** Probes singleton (`1`-recipient) and overlapping `3`-variant canary partitions, verifies `2nd` daily canary acceptance on `hard`/`hard_forge`/`hard_rl` (`canaries_per_day = 2`) vs rejection on `easy`/`medium` (`canaries_per_day = 1`), rejects `3rd` daily canary and `4`-variant (`> max_variants`) maps, cross-checks leaked canary variants against `_doc_by_id`, and rejects post-end `plant_canary`.
3. **`tool_call_cap_cliff` (`4` full-cap episodes per seed):**
   - `cliff_accuse`: burns `tool_call_cap - 1` calls (`299` or `419`), executes `accuse` on the exact `cap`-th call, and verifies `end_reason == "accused"` (never overwritten by `"tool_cap"`) and post-cliff lockout.
   - `cliff_exhaust`: burns all `cap` calls without accusing, verifying `done == True`, `score == 0.0`, `end_reason == "tool_cap"`, and rejection of a `cap + 1` mole accusation.
   - `invalid_burn`: burns `cap` consecutive malformed/unknown/wildcard calls, verifying failed calls still advance the `tool_call_cap` counter to `done == True, score == 0.0` without mutating `V`, `_costs`, `_actions_today`, `_canaries_today`, or `_restricted`.
   - `countdown_zero`: verifies `status.data["tool_calls_left"]` transitions `1 -> 0` on calls `cap - 1` and `cap`, locking the episode on call `cap`.
4. **`out_of_order_day_windows`:** Probes inverted `[day_from > day_to]` windows across `list_documents`, `read_access_logs`, and `search_messages`; out-of-bounds days (`0`, `-1`, `n_days + 1`, `True`); future document queries (`day_from = d + 1`); and same-day unclosed log/message queries (`day_from = d, day_to = n_days`), asserting zero future-day or unclosed-day leakage.
5. **`barrier_race_16t_accuse_advance`:** Launches `2` 16-thread `threading.Barrier` races per seed (`mid_horizon` and `final_horizon`), pitting `8` concurrent `accuse` threads against `8` concurrent `advance_day` threads on one shared `Env`, verifying `sum(acc_oks) == len(ledger_accusations) <= 1` and exact `verdict()["end_reason"]` consistency.

### 3.2 Per-Target Megahunt Summary (`22,150` Episodes, `1,845,969` `Env.call`s)

| Target | Staff / Days / Canaries / Cap | `900000-900039` Eps / Calls | `800000-800099` Eps / Calls | Fuzz Calls | Stateful Calls | Total Eps | Total `Env.call`s | Best Non-Solver | Best Score/Call | Violations | Time (s) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `easy` | `12 / 14 / 1 / 300` | `1,525 / 90,584` | `2,905 / 209,048` | `70,351` | `229,281` | `4,430` | `299,632` | `0.000` | `0.500000` | `0` | `103.39` |
| `medium` | `20 / 14 / 1 / 300` | `1,525 / 91,786` | `2,905 / 222,836` | `84,843` | `229,779` | `4,430` | `314,622` | `0.000` | `0.076923` | `0` | `139.15` |
| `hard` | `40 / 21 / 2 / 420` | `1,525 / 120,538` | `2,905 / 285,692` | `78,094` | `328,136` | `4,430` | `406,230` | `0.000` | `0.250000` | `0` | `166.01` |
| `hard_forge` | `40 / 21 / 2 / 420` | `1,525 / 122,134` | `2,905 / 284,842` | `78,834` | `328,142` | `4,430` | `406,976` | `0.000` | `0.058235` | `0` | `71.54` |
| `hard_rl` | `40 / 21 / 2 / 420` | `1,525 / 123,589` | `2,905 / 294,920` | `90,352` | `328,157` | `4,430` | `418,509` | `0.000` | `0.500000` | `0` | `80.17` |
| **Total** | **5 targets** | **`7,625 / 548,631`** | **`14,525 / 1,297,338`** | **`402,474`** | **`1,443,495`** | **`22,150`** | **`1,845,969`** | **`0.000`** | **`0.500000`** | **`0`** | **`560.32`** |

*Note on `Best Score/Call`:* `0.500000` (`1.0 / 2` calls on `easy` evolve and `hard_rl` random) reflects single-episode `1/N` blind-guess luck when a 2-step genome (`list_employees` + `accuse` or `status` + `accuse`) happens to name the true mole on day 1; wrong accusations score `-1.0`, so blind guessing has strictly negative expected value (`-0.8333` on `easy`, `-0.9500` on `hard_rl`), and `best_non_solver_score == 0.0` everywhere.

### 3.3 Stateful Family Call Totals & `PlantedBugEnv` Positive Control

| Stateful Family | Episodes per Target | Total Episodes (`5` Targets) | `easy` Calls | `medium` Calls | `hard` Calls | `hard_forge` Calls | `hard_rl` Calls | Total `Env.call`s | Violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `restrict_toggle_leak_delay` | `140` | `700` | `16,901` | `17,399` | `26,016` | `26,022` | `26,037` | `112,375` | `0` |
| `dual_canary_partitions` | `140` | `700` | `12,040` | `12,040` | `20,860` | `20,860` | `20,860` | `86,660` | `0` |
| `tool_call_cap_cliff` | `560` | `2,800` | `168,560` | `168,560` | `235,760` | `235,760` | `235,760` | `1,044,400` | `0` |
| `out_of_order_day_windows` | `140` | `700` | `24,920` | `24,920` | `37,660` | `37,660` | `37,660` | `162,820` | `0` |
| `barrier_race_16t_accuse_advance` | `280` | `1,400` | `6,860` | `6,860` | `7,840` | `7,840` | `7,840` | `37,240` | `0` |
| **Total Stateful** | **`1,260`** | **`6,300`** | **`229,281`** | **`229,779`** | **`328,136`** | **`328,142`** | **`328,157`** | **`1,443,495`** | **`0`** |

- **`PlantedBugEnv` Positive-Control Verification (`detected = True`):** Running the same fuzz, stateful, and 16-thread barrier harnesses against `PlantedBugEnv` (which increments `V` to `1.05` and leaks `"mole"` in `status`, omits lock serialization on `accuse`, and awards `+1.0` on wrong accusations) captured **`79` fuzz violations**, **`161` stateful violations**, and **`4` 16-thread barrier race violations** across `8` distinct kinds: `barrier_16t_accuse_race`, `parallel_accuse_race`, `parity_leak`, `post_end_effect`, `score_without_correct_accusation`, `true_v_monotonicity`, `truth_leak`, and `wrong_accusation_positive`.

## 4. Part B: 5x5 Corpus + Transcript-Mined Injection & `1bc3e281` `data.detail` Parity (`331,521` Calls)

### 4.1 Corpus & `v1.4` Transcript Mining Summary

- **Sources Scanned:**
  - `data/redteam/corpus.jsonl`: **`129` rows** (`129` unconditionally invalid foreign-tool calls from Sleeper `momin:*`, `0` Canary-native rows).
  - `data/runs/committed/v1.4/**/episodes.jsonl` (`21` files) + `results/frontier_replication/v1.4/**/episodes.jsonl` (`3` files): **`472` episodes** and **`536` failed tool steps** (`ok == False`) scanned, yielding **`90` unique `[tool, shape(args)]` patterns** (`23` from frontier LLMs, `67` from reference baselines; `8` unconditionally invalid + `82` state/roster-gated).
- **5x5 Trajectory Injection Protocol (`219` rows x `5` targets x `5` phases = `5,475` phase injections on seed `900000`):**
  - At each phase (`day1_start`, `pre_canary`, `midpoint`, `pre_accuse`, `post_end`) of the baseline `SolverPolicy` trajectory, a fresh `Env` replays prefix steps `0..idx`, checks the exact public state oracle `is_legally_valid_in_state`, and injects the payload (`3,425` unconditionally invalid injections + `2,050` state-gated injections).
  - For every rejected injection (`4,313` across the `25` cells), the harness verifies `inj_res.error in ERRORS`, validates `justSilas@1bc3e281` `data.detail` (`580` `"invalid arguments"` payloads checked for non-empty `{"detail": str}` with zero unprompted mole ID or `world_seed` leak), confirms zero immediate mutation of `(V, visible_V(), _costs, score(), _actions_today, _canaries_today, _restricted, len(docs))`, and **replays the remainder of the `SolverPolicy` trajectory to completion**, asserting `0.0` drift in `(score, accused, correct, V, end_reason)`.
  - **Precondition-Blocked Verification (`410` checks = `82` state-gated shapes x `5` targets):** Every state-gated transcript failure is also tested in a state where its precondition is explicitly blocked (unrestricted target for `unrestrict_access`, already-restricted target for `restrict_access`, exhausted `canaries_per_day` or `actions_per_day`, or post-`accuse`), confirming `410 / 410` clean rejections with zero state corruption.
  - **Panel Fix D (`1bc3e281`) Mole-vs-Innocent `data.detail` Parity (`70` checks, `80` `Env.call`s):** Across all `5` targets, `7` `invalid arguments` probes (`unrestrict_access` on unrestricted ID, invalid `interview` topic, inverted `read_access_logs` window, blank and `25`-char `plant_canary` variant labels, duplicate `restrict_access`, and `plant_canary` to restricted ID) produced **byte-identical `<id>`-normalized `data.detail` signatures** between `true_mole` and innocent staff (`mismatches_count = 0`).

### 4.2 Per-Target x Phase Injection Matrix (`5,475` Injections, `0` Illegal Acceptances, `0` Corruptions)

| Target | `day1_start` (Rej / Legal) | `pre_canary` (Rej / Legal) | `midpoint` (Rej / Legal) | `pre_accuse` (Rej / Legal) | `post_end` (Rej / Legal) | Illegal Acceptances | Corruptions |
|---|---|---|---|---|---|---:|---:|
| `easy` (`12` staff) | `207 / 12` | `207 / 12` | `210 / 9` | `207 / 12` | `219 / 0` | `0` | `0` |
| `medium` (`20` staff) | `174 / 45` | `174 / 45` | `209 / 10` | `174 / 45` | `219 / 0` | `0` | `0` |
| `hard` (`40` staff) | `138 / 81` | `138 / 81` | `138 / 81` | `138 / 81` | `219 / 0` | `0` | `0` |
| `hard_forge` (`40` staff) | `138 / 81` | `138 / 81` | `138 / 81` | `138 / 81` | `219 / 0` | `0` | `0` |
| `hard_rl` (`40` staff) | `138 / 81` | `138 / 81` | `138 / 81` | `138 / 81` | `219 / 0` | `0` | `0` |

*(State-gated rows include valid-schema `accuse` / `interview` / `restrict_access` calls on higher employee IDs `e12..e39` or exhausted-action-budget calls from `40`-employee transcripts, which are rejected on `12`-/`20`-employee rosters or mid-turn action caps and legally permitted only when roster membership and daily budgets hold; all `219 / 219` rows are rejected at `post_end` on every target.)*

## 5. Part C: Ladder `.jsonl.gz` Full Replay & `ladder.json` Alignment (`1,041` Episodes, `67,128` Calls)

### 5.1 Step-by-Step `Env` Replay Across All 4 `.jsonl.gz` Exports

`audit_ladder_exports` decompresses every committed ladder `.jsonl.gz` archive, replays every recorded tool step against a fresh `Env(tier=tier, seed=seed)` (`67,128` `Env.call`s), enforces step-level `V` / `visible_V()` monotonicity and daily action/canary caps, reconciles pre-`justSilas@1bc3e281` error payloads via `reconcile_replayed_step` (when a pre-Fix-D transcript recorded `data: {}` on a failed call that now carries `data: {"detail": ...}`), and verifies exact final `(score, accused, correct, end_reason, final_day, V)` parity.

| Export Archive | Replayable / Replayed | Consistent | Steps (`Env.call`s) | Step Mismatches | Pre-`1bc3e281` `detail` Steps | Score / V / Cap / Error Flags | End Reasons | `wall_s >= 3600s` (`>= 10800s`) | Max `wall_s` Cell |
|---|---:|---:|---:|---:|---:|---:|---|---:|---|
| `results/gemini/ladder_episodes.jsonl.gz` | `550 / 550` | `550` (`100%`) | `35,464` | `0` | `164` | `0 / 0 / 0 / 0` | `542` accused, `8` horizon | `18` (`1`) | `11,347.1s` (`gemini-4-carbon@high\|medium\|seed=3`) |
| `results/gemini/ladder_gemma_episodes.jsonl.gz` | `5 / 5` | `5` (`100%`) | `463` | `0` | `0` | `0 / 0 / 0 / 0` | `5` accused | `0` (`0`) | `1,696.8s` (`gemma-4-31b-it@default\|hard\|seed=3`) |
| `results/gemini/scale/ladder30/ladder_episodes.jsonl.gz` | `481 / 481` | `481` (`100%`) | `30,738` | `0` | `133` | `0 / 0 / 0 / 0` | `476` accused, `5` horizon | `18` (`1`) | `11,347.1s` (`gemini-4-carbon@high\|medium\|seed=3`) |
| `results/gemini/scale/ladder30/ladder_gemma_episodes.jsonl.gz` | `5 / 5` | `5` (`100%`) | `463` | `0` | `0` | `0 / 0 / 0 / 0` | `5` accused | `0` (`0`) | `1,696.8s` (`gemma-4-31b-it@default\|hard\|seed=3`) |
| **Total Across 4 Archives** | **`1,041 / 1,041`** | **`1,041` (`100%`)** | **`67,128`** | **`0`** | **`297`** | **`0 / 0 / 0 / 0`** | **`1,028` accused, `13` horizon** | **`36` (`2`)** | **`11,347.1s` max** |

### 5.2 `ladder.json` Cell-by-Cell Reconciliation (`3` Summary Files)

| `ladder.json` File | JSON `episodes` | Native `.jsonl.gz` Matched (`Cells`) | Imported Episodes (`Cells`) | Gemma JSON / `.gz` | Native & Gemma Cell Mismatches | Imported Subset Match vs Committed `v1.4` | Reconciled |
|---|---:|---:|---:|---:|---:|---|---|
| `results/gemini/ladder.json` | `587` | `550` (`40` cells) | `37` (`2` cells) | `5 / 5` | `0` | `True` (`medium n=15`, `hard n=22`) | `True` |
| `results/gemini/scale/ladder30/ladder.json` | `518` | `481` (`40` cells) | `37` (`2` cells) | `5 / 5` | `0` | `True` (`medium n=15`, `hard n=22`) | `True` |
| `results/gemini/scale/ladder30/only/ladder.json` | `101` | `101` (`16` cells, `ladder_run="ladder30"`) | `0` (`0` cells) | `0 / 0` | `0` | `n/a` | `True` |

## 6. Report-Only Issues (0 Protected Files Modified)

### 6.1 `ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER` (Severity: Low)
- **Locations:** `canary/redteam/corpus.py:41-59`, `data/redteam/corpus.jsonl`
- **Finding:** `corpus._always_invalid` checks only `Env._check_args` (JSON schema keys, types, and `1..21` integer bounds) and therefore captures only `2 / 8` unconditionally invalid `v1.4` frontier failure patterns while missing **`6` unconditionally invalid frontier patterns** enforced inside tool handlers:
  1. `["search_messages", {"day_from": "<N>", "day_to": "<N>", "query": " "}]`
  2. `["search_messages", {"query": " "}]`
  3. `["search_messages", {"day_from": "<N>", "day_to": "<N>", "query": ""}]`
  4. `["plant_canary", {"assignment": {"e00": "gA", ..., "e20": "gC"}, "doc_title": "<TEXT>"}]` (`6` distinct variants `gA..gF` `> max_variants = 3`)
  5. `["plant_canary", {"assignment": {"e02": "v2", "e05": "v1", "e22": "v1", "e25": "", "e31": "v3", "e38": "v2"}, "doc_title": "<TEXT>"}]` (empty variant label `""`)
  6. `["read_message", {"id": "1"}]` (non-`"m"` message ID prefix)
  In addition, committed `data/redteam/corpus.jsonl` currently holds only the `129` Sleeper foreign-tool rows (`momin:*`) and `0` Canary-native rows. None of these shapes bypass `Env` handler validation (`0` illegal acceptances across `5,475` injections).

### 6.2 `ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL` (Severity: Low)
- **Locations:** `canary/gemini/ladder_report.py:777-785`, `results/gemini/ladder.json`, `results/gemini/scale/ladder30/ladder.json`
- **Finding:** `ladder_report.py` writes `ladder_episodes.jsonl.gz` (`550` native episodes in `results/gemini/`, `481` in `scale/ladder30/`) before `load_import` appends `37` imported `gemini-4-carbon@default` episodes into `ladder.json` (`episodes = 587` and `518`). Furthermore, those `2` imported cells reflect an earlier snapshot of `data/runs/committed/v1.4/inproc-gemini-4-carbon`: `medium` imported `n = 15` (`mean = 0.558`) vs committed `n = 30` (`mean = 0.530333`), and `hard` imported `n = 22` (`mean = 0.493182`) vs committed `n = 30` (`mean = 0.473`). Every imported seed matches its committed `inproc-gemini-4-carbon` episode to `0.0` score difference (`committed_subset_exact_match = True`).

### 6.3 `ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL` (Severity: Advisory)
- **Locations:** `canary/gemini/ladder.py:292,389-393`, `results/gemini/ladder_episodes.jsonl.gz`
- **Finding:** In-process `ladder.py` enforces a per-HTTP-request timeout (`600s` with retry backoff) rather than a per-episode wall-clock cap. In `results/gemini/ladder_episodes.jsonl.gz`, `18` valid multi-turn episodes have `wall_s >= 3600s` and `1` has `wall_s >= 10800s` (max `11,347.1s` on `gemini-4-carbon@high|medium|seed=3`). All `18` episodes completed cleanly (`timeout_or_error_flags = 0`) and replay with `0` step or score mismatches.
