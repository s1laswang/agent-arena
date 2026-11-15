# Cost-Ledger Accounting and Stateful Trajectory Boundary Exploit Sweep (`v1.4` and `justSilas-v15`)

## 1. Executive Summary and Honesty Alignment

- **Targets Audited (`0` Protected Paths Touched, `0` Live API Calls):**
  - **`v1.4` (`origin/justSilas` @ `5f9b3297`, `integrity` @ `0b665485`):** All `5` targets (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`), `TIERS_VERSION = "v1.4"`, frozen tier hash `a8f99c2537c91d72`, `KNOWN_V_MODE = True`.
  - **`justSilas-v15` (`origin/justSilas-v15` @ `de9cc50e`):** All `4` `v1.5` targets (`easy`, `medium`, `hard`, `hard_forge`), loaded in-memory into `_canary_v15_isolated` via `load_v15_runtime()` from `scripts.integrity_v14_v15_differential_sweep` (`git show` in full clones and embedded `zlib`+`base64` fallback in `fetch-depth=1` shallow CI checkouts or `.git`-less archives), plus explicit divergence probes on `hard_rl` and `tiers_version("v1.2")`.
- **Panel Honesty Alignment:** Consistent with the squad ledger, Canary's `v1.4` `hard` MCP-only headline gap (`opencode:google/gemini-4-carbon`, `n=30`) is cited with raw **`65% [24%, 98%]`** (`+0.322` vs solver `+0.499`) before luck-adjusted **`72% [52%, 91%]`**, dev seeds `0-29` are a post-hoc lock (`671ed96`, locked after the primary run), and `hard` employee `clearance` `1..3` vs `canary_level = 1` never binds.
- **Scale and Wall Time:**
  - **Full Sweep (`--full`):** **`2,880` adversarial boundary trajectories** (`320` per cell x `9` `(version, tier)` cells: `1,600` on `v1.4` + `1,280` on `justSilas-v15`), **`223,411` step-audited `Env.call` evaluations** (`125,458` on `v1.4` + `97,953` on `v1.5`), `27,100` rejected/invalid calls, `26,314` post-end calls, `62,635` masked hidden-leak steps, and `13,314` pre-termination `V == 0.0` saturated steps in **`26.53s`** (`0` LLM/API calls).
  - **Quick CI Mode (`--quick`):** **`18` boundary trajectories** (`1,302` steps across all `9` cells and all `8` families + `6` positive controls + `5` diagnostic probes) in **`~1.4s - 1.8s`**, well below the `< 3s` budget.
- **Accounting and Boundary Integrity Verdict: HELD (`0` Exploits, `0` Invariant Violations Across `2,880/2,880` Trajectories; `6/6` Positive Controls Caught).**
  - **Exact `V` / Loss Saturation (`L_true >= 1.0` -> `V == 0.0`):** Across `432/432` (`100.0%`) saturation trajectories (`48` per cell), `V` clamped cleanly at `0.0` without going negative (`0` auto-terminations on `V == 0.0`; `13,314` pre-done `V == 0.0` steps audited), including `27` split-horizon trajectories where `round(V, 10) == 0.0` while `visible_V() > 0.0` due to unsurfaced leaks, verifying that `accuse(mole)` scores true `V = 0.0` rather than `visible_V() > 0.0`.
  - **Post-End Immutability:** Across `26,314` post-termination tool calls (`accuse` after wrong `accuse`, `accuse` after correct `accuse`, `accuse` and `next_day`/`advance_day` after `finish`/horizon and after `tool_cap`), `100.0%` returned `ok=False, error="episode over", data={}` with `0` overwrites of `score()`, `verdict()`, `day`, or `ledger()`.
  - **`restrict_access` / `unrestrict_access` Toggles and Invalid Calls:** Across `270` toggle trajectories (`5,400` steps) and `27,100` rejected calls, immediate `V` and `visible_V()` deltas were `0.0` on `100.0%` of toggles and invalid calls; same-day `restrict -> unrestrict` pairs incurred `0.0` day-close cost and never refunded `V`.
  - **Floating-Point vs Exact `Decimal` Closed-Form Cost Sums:** Across all `223,411` steps, `10`-decimal rounded quantities (`round(env.V, 10)`, `score()`, `verdict()["V"]`, and `visible_V()`) matched exact `decimal.Decimal` closed-form formulas with **`0.0` maximum drift** (`0` mismatches), while raw unrounded `self.V` exhibited benign IEEE-754 ULP drift up to `6.661e-16` across `55,951` steps (`ISS-COST-02`).
  - **Positive Controls:** All **`6/6` (`100.0%`)** planted accounting bugs were caught immediately by `StepAccountingAuditor`.
- **Report-Only Maintainer Findings (`5` Issues Documented in Section 6; `0` Protected Edits):** `ISS-COST-01` (`peek_status()` `tool_calls_left` off-by-one and missing `episode_over` on exact `tool_cap` step), `ISS-COST-02` (unrounded `self.V` ULP drift in `meta["V"]` / `ledger` vs `10`-dp `score()`/`verdict()`), `ISS-COST-03` (`V == 0.0` non-auto-termination and `SolverPolicy` `ev > 0` abstention at `posterior = 1.0`), `ISS-COST-04` (`regret.py` `sp.V` vs `expected_true_V()`, `obs.leak_days` shift under `KNOWN_V_MODE=True`, and final-day `advance_day` `"V"` omission), and `ISS-COST-05` (`justSilas-v15` `de9cc50e` missing `v1.2` `KNOWN_V_MODE_HISTORY`, `hard_rl`, and `1bc3e281` `_bad(detail)`).

## 2. Reproduce Commands (Keyless, Shallow-CI Safe, Zero API Calls)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_cost_and_trajectory_boundary_sweep.py --quick
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_cost_and_trajectory_boundary_sweep.py --quick --shallow-fallback
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_cost_and_trajectory_boundary_sweep.py --full
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_cost_and_trajectory_boundary_sweep.py
```

## 3. Full `2,880`-Trajectory Sweep Breakdown by `(Version, Tier)` Cell

Note on notation: in Canary (`canary/env.py:85, 298-315`), `self.V` denotes remaining company value starting at `1.0` and clamping at `0.0`, corresponding to `1.0 - L` where cumulative loss `L = leak_damage * n_leaks + canary_cost * n_canaries + restrict_cost_per_day * n_restrict_person_days` saturates across `L >= 1.0` (`self.V == 0.0`). Every step verifies `score() <= round(1.0 - min(1.0, L_true), 10) == round(self.V, 10)`.

| Cell (`version:tier`) | Trajectories | Audited Steps | Rejected Calls | Post-End Calls | Masked Unsurfaced-Leak Steps (`masked / total`) | Pre-Done `V == 0.0` Steps | Saturation Reached (`V == 0.0`) | Split (`V == 0`, `vis_V > 0`) | Max Raw `self.V` Float Drift | Max `10`-dp Drift (`V` / `vis_V`) | Blind Fuzz Mean Score (`+-95% CI`) | Violations |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `v1.4:easy` | `320` | `21,347` | `2,781` | `2,922` | `78 / 123` | `837` | `48 / 48` | `0` | `5.031e-16` | `0.0 / 0.0` | `-0.8045 +- 0.0973` | `0` |
| `v1.4:medium` | `320` | `21,616` | `2,754` | `2,980` | `7,565 / 8,059` | `728` | `48 / 48` | `3` | `4.718e-16` | `0.0 / 0.0` | `-0.8137 +- 0.0981` | `0` |
| `v1.4:hard` | `320` | `27,509` | `3,206` | `2,902` | `12,418 / 14,089` | `2,237` | `48 / 48` | `4` | `4.996e-16` | `0.0 / 0.0` | `-0.8466 +- 0.0808` | `0` |
| `v1.4:hard_forge` | `320` | `27,491` | `3,206` | `2,902` | `7,428 / 8,753` | `1,809` | `48 / 48` | `5` | `5.551e-16` | `0.0 / 0.0` | `-0.7695 +- 0.1121` | `0` |
| `v1.4:hard_rl` | `320` | `27,495` | `3,206` | `2,902` | `8,803 / 10,002` | `2,111` | `48 / 48` | `4` | `4.996e-16` | `0.0 / 0.0` | `-0.8625 +- 0.0759` | `0` |
| `v1.5:easy` | `320` | `21,351` | `2,781` | `2,922` | `78 / 120` | `853` | `48 / 48` | `0` | `5.031e-16` | `0.0 / 0.0` | `-0.8045 +- 0.0973` | `0` |
| `v1.5:medium` | `320` | `21,617` | `2,754` | `2,980` | `7,282 / 7,742` | `715` | `48 / 48` | `4` | `4.441e-16` | `0.0 / 0.0` | `-0.8137 +- 0.0981` | `0` |
| `v1.5:hard` | `320` | `27,491` | `3,206` | `2,902` | `12,455 / 14,260` | `2,240` | `48 / 48` | `5` | `5.135e-16` | `0.0 / 0.0` | `-0.8466 +- 0.0808` | `0` |
| `v1.5:hard_forge` | `320` | `27,494` | `3,206` | `2,902` | `6,528 / 7,676` | `1,784` | `48 / 48` | `2` | `6.661e-16` | `0.0 / 0.0` | `-0.7695 +- 0.1121` | `0` |
| **Total (`9` cells)** | **`2,880`** | **`223,411`** | **`27,100`** | **`26,314`** | **`62,635 / 70,824`** | **`13,314`** | **`432 / 432`** | **`27`** | **`6.661e-16`** | **`0.0 / 0.0`** | **all `<= -0.7695`** | **`0`** |

## 4. Breakdown by Adversarial Boundary Family (`8` Families)

| Trajectory Family | Trajectories | Audited Steps | Rejected Calls | Post-End Calls | Max Raw `self.V` Drift | Max `10`-dp Rounded Drift | Violations | Boundary Mechanics Verified |
|---|---|---|---|---|---|---|---|---|
| `saturation_loss_ge_one` | `432` | `24,872` | `0` | `1,080` | `3.331e-16` | `0.0` | `0` | Exact `L >= 1.0` (`V == 0.0` and `visible_V() == 0.0`) floor clamping, non-auto-termination, split `(V == 0.0, visible_V() > 0.0)` `accuse(mole) -> 0.0`, `accuse(innocent) -> -1.0`, horizon `-> 0.0` |
| `post_end_tool_calls` | `432` | `45,420` | `324` | `2,700` | `4.441e-16` | `0.0` | `0` | `accuse` after wrong `accuse`, `accuse` after correct `accuse`, `finish`/`submit_report`/`next_day` probes, `accuse` and `advance_day`/`next_day` past horizon and past `tool_call_cap` |
| `tool_cap_exact_boundary` | `180` | `66,360` | `13,110` | `360` | `0.000e+00` | `0.0` | `0` | Exact `t = tool_call_cap - 1` (`tool_calls_left == 1`): valid `accuse(mole)` succeeds before cap check (`end_reason="accused"`), whereas invalid `accuse` triggers `end_reason="tool_cap"` (`score=0.0`) |
| `restrict_unrestrict_toggle` | `270` | `5,400` | `1,485` | `0` | `2.220e-16` | `0.0` | `0` | Full-budget same-day `restrict`/`unrestrict` toggles (`0.0` immediate and day-close cost), duplicate `restrict` and unrestrict-unrestricted refund probes (`0` budget burn, `0.0` refund), restricted canary rejection |
| `invalid_arg_zero_delta` | `360` | `12,060` | `9,540` | `0` | `1.110e-16` | `0.0` | `0` | Schema-invalid (`bool` for `int`, out-of-range days, `day_from > day_to`, bad IDs, extra/missing keys), handler-invalid, canary-cap, daily-action-cap, and unknown tools (`finish`, `next_day`, `refund`, `_cost`, `verdict`): exact `0.0` delta on `V`, `visible_V()`, `_costs`, and `_actions_today` |
| `float_vs_closed_form` | `216` | `21,212` | `0` | `0` | `6.661e-16` | `0.0` | `0` | Full-horizon non-dyadic binary fraction accumulation (`0.01`, `0.01*k`, `0.04`, `0.05`) vs exact `decimal.Decimal` closed-form sums across `self.V`, `self._costs`, `visible_V()`, `score()`, `verdict()`, and `EpisodeResult.meta["V"]` |
| `known_v_mode_dual` | `270` | `10,260` | `0` | `0` | `4.441e-16` | `0.0` | `0` | Paired `KNOWN_V_MODE = True` vs `False` rollouts: identical true `V`/`score()`/streams; `visible_V()` hides unsurfaced leaks under `True` and equals `round(V, 10)` under `False`; `v1.4` tier hash `a8f99c2537c91d72` preserved |
| `stateful_adversarial_fuzz` | `720` | `37,827` | `2,641` | `22,174` | `4.718e-16` | `0.0` | `0` | Blind PRNG boundary walks mixing toggles, canaries, interviews, logs, malformed/unknown tools, horizon, and random accusations (`mean <= -0.7695` across all `9` cells) |

## 5. Planted Accounting-Bug Positive Controls (`6/6` Caught, `100%` Recall)

All positive controls are executed in-memory on transient `Env` subclasses without touching `canary/env.py`:

| Control ID | Planted Accounting / State-Machine Defect | Caught | Violations | Triggered Invariant Kinds |
|---|---|---|---|---|
| `PC1_negative_tool_cost` | `unrestrict_access` subtracts `restrict_cost_per_day` from `_costs` and adds `+0.01` to `self.V` (cost refund / `V` inflation) | `True` | `5` | `closed_form_true_v_mismatch`, `immediate_unrestrict_cost_or_refund`, `v_monotone_or_range_violation`, `visible_v_closed_form_mismatch`, `visible_v_monotone_or_range_violation` |
| `PC2_post_done_accuse_overwrite` | Post-done `accuse(mole)` bypasses `_done` lock after a wrong `accuse(innocent)`, overwriting `-1.0` to `+V` | `True` | `3` | `multiple_or_missing_ledger_accusations`, `post_end_response_invalid`, `post_end_state_mutation` |
| `PC3_free_interview_on_error` | Invalid-topic `interview` omits `_history.append` (free call toward `tool_call_cap`), decrements `_actions_today`, and leaks `answer` in error `data` | `True` | `3` | `error_payload_leak_or_extra_keys`, `history_not_incremented`, `rejected_call_budget_mutation` |
| `PC4_visible_v_hidden_leak_sidechannel` | `visible_V()` returns `round(self.V, 10)` under `KNOWN_V_MODE = True`, leaking unsurfaced leak drops on the day they occur | `True` | `4` | `visible_v_closed_form_mismatch`, `visible_v_hidden_leak_sidechannel` |
| `PC5_score_gt_one_minus_loss_inflation` | `score()` grades a correct accusation from `visible_V() + 0.05` instead of true `V = 1 - L_true`, inflating `score > 1 - L_true` | `True` | `2` | `score_contract_mismatch`, `score_exceeds_one_minus_loss` |
| `PC6_action_budget_and_horizon_bypass` | Valid `interview` omits `_actions_today += 1` (free daily action) and `advance_day` advances `self.day` past `n_days` (`15 > 14`) | `True` | `3` | `action_budget_accounting`, `day_out_of_bounds`, `horizon_transition_invalid` |

## 6. Issues-Only Maintainer Findings for Silas (`0` Protected Edits)

None of `ISS-COST-01`..`ISS-COST-05` permit a positive-reward exploit on shipped `justSilas` (`v1.4`) or `justSilas-v15` (`de9cc50e`), as `score()`, `verdict()`, `visible_V()`, action caps, and post-end locks all hold `100%` across `223,411` audited steps.

1. **`ISS-COST-01` (Low, `v1.4` and `v1.5` UI Helper & Exact-Cap Signal): `Env.peek_status()` `tool_calls_left` Off-By-One (`cap - len(_history) - 1`) and Missing `"episode_over": True` on Exact `tool_call_cap` Step.**
   - **Location:** `canary/env.py:241-244, 283-286, 409-413` and `canary/mcp_server.py:396`.
   - **Evidence:** `peek_status()` ("Same data as the `status` tool, without counting a call") delegates directly to `_t_status({})`, which subtracts `1` for an in-flight `status` step that `peek_status()` never appends. Measured at `t = 0`: `peek_status()["tool_calls_left"]` is `299` on `easy`/`medium` (`cap = 300`) and `419` on `hard` (`cap = 420`), becoming `-1` at `t = cap` and `-2` at `t = cap + 1`. In addition, when non-terminal call `t = cap - 1` hits `tool_call_cap`, `_call()` serializes `res` (`ok=True`, `tool_calls_left=0`, without `"episode_over": True`) before calling `self._end("tool_cap")`, causing `mcp_server.play_policy` (`canary/mcp_server.py:396`) to issue one extra `#(cap + 1)` call before seeing `"episode over"`.
   - **Proposed Maintainer Fix:** In `peek_status()`, compute `"tool_calls_left": max(0, self.p.tool_call_cap - len(self._history))` (without `- 1`), and optionally set `res.data["episode_over"] = True` when `len(self._history) >= self.p.tool_call_cap` ends the episode on a `res.ok` step.

2. **`ISS-COST-02` (Low, `v1.4` and `v1.5` Float Representation Split): Unrounded IEEE-754 `self.V` / `self._costs` in `EpisodeResult.meta["V"]` and `LedgerEntry.detail["V"]` vs `10`-Decimal Rounded `score()`, `verdict()["V"]`, and `visible_V()`.**
   - **Location:** `canary/env.py:252, 256, 270, 296, 298-305, 313, 315, 496, 523, 577` and `canary/redteam/anticheat.py:759`.
   - **Evidence:** Across `223,411` audited steps, `55,951` steps (`25.04%`) exhibited non-zero IEEE-754 ULP drift in raw `self.V` (up to `6.661e-16`, and up to `2.665e-15` in `self._costs`) from sequential non-dyadic float updates (`0.01`, `0.04`, `0.05`) vs exact `Decimal` closed-form sums, whereas `round(..., 10)` in `score()`, `verdict()["V"]`, and `visible_V()` achieved **`0.0` drift across `223,411/223,411` steps**. Raw `self.V` is written to `EpisodeResult.meta["V"]` and `LedgerEntry.detail["V"]` (which required `round(float(d.get("V", 0.0)), 10)` in `anticheat.py:759` and broke naive `meta["V"] == score` equality checks).
   - **Proposed Maintainer Fix:** Apply `round(..., 10)` directly inside `_charge()` (`self.V = round(max(0.0, self.V - x), 10)`) and `_cost()` (`self._costs = round(self._costs + x, 10)`) so raw `self.V`, `meta["V"]`, `ledger`, `verdict()`, and `score()` are bit-identical everywhere.

3. **`ISS-COST-03` (Low, `v1.4` and `v1.5` Saturation Boundary Semantics): Non-Auto-Termination at `V == 0.0` (`L >= 1.0`) Makes Accusation Weakly Dominated and Causes `SolverPolicy` (`ev > 0`) to Abstain Even at `posterior = 1.0`.**
   - **Location:** `canary/env.py:254-257, 298-299` and `canary/solver/policy.py:303-305`.
   - **Evidence:** Across `432/432` saturation trajectories (`13,314` pre-done `V == 0.0` steps), `Env` never auto-terminates when `V` hits `0.0`. At `V == 0.0`, `accuse(mole)` scores `0.0` (identical to abstaining), while `accuse(innocent)` scores `-1.0`. Because `SolverPolicy._plan()` requires strict `ev = accuse_value(post[best], expected_true_V(), P) > 0.0`, and `accuse_value(1.0, 0.0, P) == 0.0` (`-0.05` at `p = 0.95`), `SolverPolicy` refuses to accuse even when `post[best] == 1.0`, walking to `"horizon"` (`correct=False, score=0.0`).
   - **Proposed Maintainer Fix:** Document explicitly in `CONTRACT.md` that `V == 0.0` episodes remain open until `accuse`/`horizon`/`tool_cap` with optimal zero-risk action = abstain (`score = 0.0`), or allow `ev >= 0.0 and post[best] >= 1.0 - 1e-9` if diagnostic solver `accuracy` should credit exact identification at `V == 0.0`.

4. **`ISS-COST-04` (Low-Medium, Offline Regret Attribution Accounting in `v1.4` and `v1.5`): `canary/solver/regret.py` Uses `sp.V` (`visible_V`) Instead of `sp.expected_true_V()`, Mis-Indexes `obs.leak_days` Under `KNOWN_V_MODE = True`, and Omits Final-Day Restriction Cost on Horizon `advance_day`.**
   - **Location:** `canary/solver/regret.py:61, 84-90, 113`, `canary/solver/policy.py:200-204, 213-220`, and `canary/env.py:613-615`.
   - **Evidence:** Across `10/10` probed `hard` episodes (`seeds 0..9`), `SolverPolicy._close(closed_day, V_after)` recorded `surfaced_day - 1` into `sp.obs.leak_days` (`10/10` mismatch vs true leak days under `KNOWN_V_MODE = True`), `sp.V` exceeded true `V` at Day 5 by a mean of `+0.045` (max `+0.100`) because `regret.attribute()` passes `sp.V` (`visible_V`) instead of `sp.expected_true_V()` into `accuse_value`, and `Env._t_advance_day` on `d == p.n_days` (`10/10` episodes) returned `{"closed_day": d, "episode_over": True}` without `"V"`, leaving `sp.V` un-decremented for Day `n_days` restriction costs on the terminal `(no accusation)` regret row.
   - **Proposed Maintainer Fix:** In `canary/solver/regret.py`, use `V = sp.expected_true_V()` for `accuse_value` / `q_continue`, gate `ignored_delay` tagging on `sp.v_drops_reveal_leaks()`, and subtract `P.restrict_cost_per_day * len(sp.restricted)` when ingesting a horizon `advance_day` step that omits `"V"`.

5. **`ISS-COST-05` (Medium, Pre-Merge Regression Guard on `origin/justSilas-v15` @ `de9cc50e`): `justSilas-v15` Drops `v1.2` `KNOWN_V_MODE_HISTORY`, `TRACKS["hard_rl"]`, and `1bc3e281` Structured `_bad(detail)` Relative to `justSilas` @ `5f9b3297`.**
   - **Location:** `canary/rules.py:126-184` and `canary/env.py:20-28, 458-580` on `origin/justSilas-v15 @ de9cc50e`.
   - **Evidence:** Differential probes confirm that on `v1.4` (`justSilas`), `with rules.tiers_version("v1.2"):` sets `KNOWN_V_MODE = False` and restores `True` on exit, `TRACKS` includes `["hard_forge", "hard_rl"]`, and invalid-argument `ToolResult.data` carries `{"detail": ...}`. On `justSilas-v15` (`de9cc50e`), `tiers_version("v1.2")` raises `KeyError`, `Env("hard_rl", 0)` raises `ValueError`, and invalid-argument calls return `data={}`.
   - **Proposed Maintainer Fix:** Rebase `justSilas-v15` onto `justSilas` (`5f9b3297`) preserving `TIERS_V12`, `KNOWN_V_MODE_HISTORY`, `TRACKS["hard_rl"]`, and `_bad(detail)` before promoting any `v1.5`/`v1.6` social-layer ruleset.
