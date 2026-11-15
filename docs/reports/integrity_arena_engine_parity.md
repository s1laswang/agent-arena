# Canary Arena Engine Parity & Cross-Squad Integrity Audit (`v1.4`)

- **Base commit:** `58716742` (`origin/justSilas`, `TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`)
- **Audit harness:** `scripts/audit_arena_engine_parity.py` (`0` live API calls, deterministic offline execution)
- **Overall verdict:** **PASS** (`all_passed = True`, `0` core `Env` / `Game` / pre-end hidden-truth failures, `8/8` planted-bug controls caught, `5/5` live cross-squad Arena surfaces audited via `git show`, `6` report-only cross-squad issues logged as `ISSUE-ARENA-ENGINE-*`)
- **Measured runtime:** `3.33s` full sweep (`1,745` states), `1.85s` `--quick` sweep (`1,151` states), `0.54s` `--quick --simulate-missing-refs` (`0/5` remote refs gracefully skipped for single-branch CI)

## 1. Core `canary.env.Env` & `game/canary_game.py` Fuzz Parity (`Part 1`)

We fuzzed multi-day trajectories across all `5` v1.4 targets (`easy`, `medium`, `hard`, `hard_forge`, `hard_rl`) and replayed `SolverPolicy` trajectories step-by-step through `game/canary_game.py:Game`:

| Metric | Full Sweep (`quick=False`) | Quick Sweep (`--quick`) | Invariant Verified |
|---|---:|---:|---|
| Fuzzed `Env` episodes | `31` | `21` | Covers all `5` targets + `tool_call_cap` exhaustion (`easy:4999`, `300` calls) |
| Interactive `Game` full `SolverPolicy` replays | `4` (`3000..3003`) | `2` (`3000, 3003`) | Step-for-step `call_json` == `Env.call`, `0` init history drain, seed-invariant `spec_json()` |
| Total step states verified | `1,745` | `1,151` | `visible_V() == peek_status()["V"] == round(max(0, 1 - leak_damage * surfaced - costs), 10)` |
| States with active unsurfaced leaks | `368` | `226` | `KNOWN_V_MODE = True`: `visible_V > true_V` (or `0.0`); unsurfaced leak damage never leaked |
| Terminal scoring checks (`correct` / `wrong` / `abstain` / `cap`) | `10 / 10 / 10 / 1` | `10 / 5 / 5 / 1` | Correct accuse `round(true_V, 10)`, wrong accuse `-1.0`, horizon abstain `0.0`, `tool_cap` `0.0` |
| Post-end no-op calls (`5` tools per ended episode) | `155` | `105` | `ok=False`, `error="episode over"`, `0` mutations to `score()`, `V`, `visible_V()`, or `ledger()` |
| Panel Fix D (`1bc3e281`) `data.detail` role-parity checks | `136` | `136` | Byte-identical `<id>`-normalized `data.detail` across `mole` / `decoy` / `innocent` (`0` mismatches) |
| `Game` `JUDGE_SEEDS` (`900000-900039`) refused | `40/40` | `40/40` | Fail-closed `ValueError` |
| `Game` `HELDOUT_SEEDS` (`800000-800199`) refused | `200/200` | `200/200` | Fail-closed `ValueError` |
| `Game` `<3000` dev seeds (`0..29` post-hoc locked + `30,100,999,2999`) refused | `34/34` | `34/34` | Fail-closed `ValueError` protecting post-hoc lock benchmark seeds |
| `Game` malformed / `>=10000` seeds refused | `12/12` | `12/12` | Rejects `10000, 100000, -1, -900000, 3000.5, "3000.0", "3e3", "NaN", "abc", "", True, None` |

Per-target state coverage (full sweep): `easy` `506` states (`7` episodes, `16` detail checks across `mole`/`innocent`), `medium` `214` states (`6` episodes, `83` unsurfaced-leak states, `24` detail checks across `mole`/`decoy`/`innocent`), `hard` `254` states (`6` episodes, `113` unsurfaced-leak states, `24` detail checks), `hard_forge` `270` states (`6` episodes, `85` unsurfaced-leak states, `24` detail checks), `hard_rl` `230` states (`6` episodes, `85` unsurfaced-leak states, `24` detail checks), plus `271` states across `Game(3000..3003)` and `24` `Game(3000)` detail checks (`1,745` total states, `0` violations).

## 2. Planted-Bug Negative Controls (`Part 2`)

All `8` synthetic negative controls (and `1` clean unsurfaced-leak control on `medium:3000` with `0` false positives) execute unconditionally in both full and `--quick` modes without requiring remote refs:

| Control ID | Planted Defect | Caught | Triggered Detector Signal |
|---|---|---|---|
| `planted_visible_v_uses_true_v` | `visible_V()` returns `true_V` (`0.92`) instead of `known_v` (`0.96`) on unsurfaced leak | `True` | `visible_V_formula_mismatch:got=0.92:exp=0.96` |
| `planted_wrong_accuse_zero_penalty` | Wrong accusation returns `0.0` instead of `-1.0` | `True` | `terminal_score_mismatch:got=0.0:exp=-1.0` |
| `planted_abstain_nonzero_score` | Horizon abstention returns `0.55` instead of `0.0` | `True` | `terminal_score_mismatch:got=0.55:exp=0.0` |
| `planted_post_end_accuse_overwrite` | Post-end `accuse(mole)` mutates `score()` after episode end | `True` | `post_end_mutation_on_accuse` |
| `planted_detail_role_asymmetry` | `1bc3e281` `data.detail` text differs when `employee == mole` vs `decoy`/`innocent` | `True` | `role_detail_asymmetry:mole_vs_decoy` |
| `planted_game_seed_gate_bypass` | Interactive `Game` accepts `900000`, `800000`, and `<3000` seed `6` | `True` | `accepted_judge_seed:900000`, `accepted_heldout_seed:800000`, `accepted_low_dev_seed:6` |
| `planted_pre_end_mole_and_accuse_leak` | Duel payload exposes `mole="e34"` and unsealed `accuse.args.employee="e34"` while `human_done=False` | `True` | `$.mole` + `$.steps[0].args.employee` pre-end leak |
| `planted_mole_mode_is_canary_leak` | Mole-mode `leakable_docs` exposes `is_canary=True` before episode end | `True` | `$.leakable_docs[0].is_canary` pre-end leak |

## 3. Live Cross-Squad Arena Engine & Pack Audit (`Part 3`)

When remote refs exist locally, `audit_arena_engine_parity.py` inspects all `5` cross-squad Arena artifacts via `git show` (and executes ESM bundles under Node `v24.22.3`); when refs are absent, each surface reports `SKIPPED_ABSENT_REF` cleanly.

| Surface | Git Ref & Path | Pre-End Leak Gate | Core Parity Metrics Verified (Full / Quick) | Report-Only Issues |
|---|---|---|---|---|
| Eval Scoring Parity | `origin/fr8/canary/eval-arena:docs/arena/scoring_parity.py` | **PASS** (`0` leaks) | `5/5` trajectories (`easy:3000`, `medium:3000`, `hard:6`, wrong accuse `-1.0`, abstain `0.0`) match `Env` | `1` (`EVAL-SESSION-UNBOUNDED-SEED`) |
| Port Replay Engine | `origin/fr8/canary/canary-port-w3-arena:docs/arena/replay_engine.js` | **PASS** (`0` leaks) | Node ESM replay on `4` / `2` committed `hard` seeds (`6,26,4,11`), `515` / `148` step `known_v == Env.visible_V()` checks, `8` / `4` causal day-clamp & `[SEALED]` checks | `2` (`REPLAY-COMPACT-RESTRICT-AND-ZEROV`, `DUEL-TIEBREAK-ORDER-DIVERGENCE`) |
| Strategies Mole Mode | `origin/fr8/canary/canary-strategies-w2-arena:docs/arena/mole_mode.py` | **PASS** (`0` `is_canary`/posterior leaks) | `40/40` judge + `200/200` held-out + `34/34` `<3000` seeds refused; `10/10` / `3/3` `solver_score == Env.score()` | `2` (`MOLE-PLEAK-GATE-BYPASS`, `MOLE-RECIPIENT-LIST-EXPOSURE`) |
| Research Seed Catalog | `origin/fr8/canary/research-arena:docs/arena/SEEDS.md` | **PASS** (`0` live mole leaks) | `canary_arena_seeds_v1`, `10` Mode 1 seeds in `3000..9999`, `13` / `5` `SolverPolicy` rollouts + `3` headline `hard` (`6,26,4`) Gemini transcripts exact match | `1` (`SEEDS-DOC-REJECTED-INTERVIEW-COUNT`) |
| StaffAI Living Office | `origin/fr8/canary/canary-staffai-w5-arena:docs/arena/data/living_office_pack.js` | **PASS** (`0` pre-end truth keys) | `default_enabled=False`, `gateBPassed=False`, `54/54` cached prompts (`0` API calls), `63` day records (`hard:0,1,6`), `3/3` / `1/1` `sealed_reveal` `SolverPolicy` & world truth exact match | `0` |

## 4. Cross-Squad Discrepancies (`ISSUE-ARENA-ENGINE-*`, Report-Only)

1. **`ISSUE-ARENA-ENGINE-MOLE-PLEAK-GATE-BYPASS`** (`medium` severity, `origin/fr8/canary/canary-strategies-w2-arena`, `docs/arena/mole_mode.py:51-69` vs `canary/mole/dsl.py:135-138`):
   - `_HumanMoleStrategy.decide(view, rng)` records `can_leak_gate = bool(view.can_leak)` in `self.last_applied` without setting `leak = None` when `view.can_leak` is `False` (whereas `Env._t_advance_day` delegates `p_leak` enforcement to `MoleStrategy.decide` via `view.can_leak`).
   - Empirical check: across `10` `medium` seeds (`3000..3009`, `57` leak-action days; `5/20` in `--quick`), `18` days where `Env._mole_view` drew `can_leak = False` still leaked the chosen document (`effective p_leak = 1.00` instead of `0.75` on `medium` and `0.65` on `hard`), miscalibrating `SolverPolicy` Bayesian updates.
   - Proposed fix for `strategies-arena`: gate `if not view.can_leak or leak not in held_ids: leak = None` inside `_HumanMoleStrategy.decide`.
2. **`ISSUE-ARENA-ENGINE-MOLE-RECIPIENT-LIST-EXPOSURE`** (`low` severity, `origin/fr8/canary/canary-strategies-w2-arena`, `docs/arena/mole_mode.py:232,236` vs `canary/mole/dsl.py:30-35`):
   - `MoleModeSession.get_mole_day_view()` includes full `"recipients": list(doc["recipients"])` on all `237` `leakable_docs` entries (`95` in `--quick`) alongside `peer_roster` department labels, whereas canonical `MoleDoc` / `MoleView` exposes only `recipient_count` and `age_days`.
   - Proposed fix for `strategies-arena`: omit `recipients` from pre-end `leakable_docs` / `docs` dictionaries so human moles have exact `MoleView` information parity.
3. **`ISSUE-ARENA-ENGINE-EVAL-SESSION-UNBOUNDED-SEED`** (`low` severity, `origin/fr8/canary/eval-arena`, `docs/arena/scoring_parity.py:334-340,407`):
   - `ArenaSession` (aliased as `ArenaGame = ArenaSession`) validates seeds only with `_parse_int_seed(seed)` rather than `canary_game.check_seed(seed)` (`3000..9999`), accepting benchmark probes `[6, 800000, 900000]` directly if mounted by browser UI code without `game/canary_game.py:Game`.
   - Proposed fix for `eval-arena`: require `3000 <= seed <= 9999` by default in `ArenaSession.__init__` unless an explicit offline replay flag is passed.
4. **`ISSUE-ARENA-ENGINE-REPLAY-COMPACT-RESTRICT-AND-ZEROV`** (`low` severity, `origin/fr8/canary/canary-port-w3-arena`, `docs/arena/replay_engine.js:356-360,708-714`):
   - Full `episodes.jsonl` records match `Env.visible_V()` on `515/515` steps (`0` drift), but compact step objects omitting `result` and explicit `known_v` skip `restrict_cost_per_day * restricted.size` on `advance_day` (`known_v = 1.0` instead of `0.99` after `restrict_access("e00")` + `advance_day`), and `extractPostEndMetaFromRaw` fallback `score > 0` infers `correct = false` when a mole is correctly accused at `true_V = 0.0` (`score = 0.0`, vs `-1.0` for wrong accusations) without explicit `correct`/`mole` fields.
   - Proposed fix for `port-arena`: apply the `restrict_cost_per_day * restricted.size` fallback whenever `resData?.V` and explicit `st.known_v` are absent, and use `score >= 0` (`score > -0.5`) when `accused` is non-null.
5. **`ISSUE-ARENA-ENGINE-DUEL-TIEBREAK-ORDER-DIVERGENCE`** (`advisory` severity, `origin/fr8/canary/canary-port-w3-arena:docs/arena/replay_engine.js:758-814` vs `origin/fr8/canary/eval-arena:docs/arena/scoring_parity.py:954-1001`):
   - On same-day catches (probed on `hard:6` Day `6` with Gemini at `50` calls / `+0.73` vs Solver at `52` calls / `+0.71`), `replay_engine.js` `computeFirstCatchFromContenders` returns `'Solver'` (`You > Solver > Gemini` tie priority ignoring `tool_calls` and `score`), whereas `scoring_parity.duel_end_screen_summary` returns `'gemini'` via `(correct, -final_day, -tool_calls, score)`.
   - Proposed fix: align `computeFirstCatchFromContenders` tie-breaking with `_combatant_rank_tuple` (`final_day` asc, `tool_calls` asc, `score` desc).
6. **`ISSUE-ARENA-ENGINE-SEEDS-DOC-REJECTED-INTERVIEW-COUNT`** (`advisory` severity, `origin/fr8/canary/research-arena`, `docs/arena/SEEDS.md:45`):
   - In Featured Hard `hard:15`, `SEEDS.md` lists `68` interviews (counting all `68` `interview` tool calls, `67` `ok=True` + `1` `ok=False`), whereas `replay_engine.js` `summarizePublicStepCounts` displays `67` (`ok=True` interviews only).
