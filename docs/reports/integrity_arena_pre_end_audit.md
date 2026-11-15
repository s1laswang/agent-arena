# Canary Arena Pre-End Hidden-Truth Leak Audit

## 1. Executive Summary

- **Base commit audited:** `e19e2bd2` (`origin/fr8/canary/integrity`, synced with `justSilas@58716742`, zero protected or unowned files touched).
- **Verifier entrypoint:** `scripts/verify_arena_integrity.py` (`--root`, `--json-out`, `--check`).
- **Execution & runtime:** `0` live LLM or external API calls; deterministic `--check` runtime `0.28s` (`< 5s` gate); all temporary synthesis confined strictly to `/tmp/opencode/integrity_w5_scratch` and removed on exit.
- **Overall verdict:** **PASS (`3/3` checks: A1, A2, A3)** across WS6 `game/` (`6` source files + `19` built static site files), post-hoc locked `v1.4` `hard` seeds `6` and `26`, and `6/6` (`100%`) planted pre-end leak positive controls (`exit 1`), with automatic recursive bundle scanning ready for `docs/arena/**` and `docs/demo/**` as Arena UI and replay branches merge.

## 2. Reproduce Commands (0 API Calls)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_arena_integrity.py --check
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_verify_arena_integrity.py tests/test_submission_audit.py -k "verify_arena or test_real_repo_passes_audit"
```

## 3. Check A1: Secret, Key & Benchmark-Seed Firewall

| Metric | Verified Value | Gate |
|---|---:|---|
| WS6 `game/` files scanned (`app.js`, `build.py`, `canary_game.py`, `index.html`, `style.css`, `tests/parity.mjs`) | `6` | PASS |
| Scratch `game.build.build(tmp_site)` total files / Python modules | `19` / `15` | PASS (`py/manifest.json` 1:1 match) |
| `docs/arena/**` and `docs/demo/**` auto-discovery (`*.{html,js,mjs,json,jsonl,py,css}`) | `0` present on `e19e2bd2` (auto-scanned when present) | PASS |
| Raw API keys / OAuth tokens / gateway header keys across `7` credential families | `0` | PASS |
| `SALT` / `CANARY_WORLD_SECRET` / `CANARY_LEDGER_TOKEN` literals or repo secret byte matches | `0` | PASS |
| Shipped `canary/redteam` or `canary/mcp_server.py` modules in `py/manifest.json` | `0` | PASS |
| `JUDGE_SEEDS` (`900000..900039`) fail-closed `ValueError` rejection | `40/40` (`100%`) | PASS |
| Benchmark `HELDOUT_SEEDS` (`800000..800029`) fail-closed `ValueError` rejection | `30/30` (`100%`) | PASS |
| Boundary & malformed seed probes (`0`, `2999`, `10000`, `100000`, `800199`, `-1`, `"3000.0"`, `"3e3"`, `"abc"`, `None`, `True`) | `11/11` (`100%`) | PASS |

## 4. Check A2: Pre-End Replay & Bundle Truth-Leak Scanner

### 4.1 Post-Hoc Locked `v1.4` `hard` Seeds `6` and `26` (`opencode-gemini-4-carbon` + Live `Env`)

`verify_arena_integrity.py` replays `Env("hard", 6)` and `Env("hard", 26)` step-for-step alongside `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`, verifying that every pre-terminal step (`!done`) is free of unsealed `mole`, `true_mole`, `decoy`, `correct`, `leaking_sprite_employee`, mole-mode `is_canary`, and unsurfaced `true_v` exposure:

| Seed (`v1.4` `hard`) | True Mole / Decoy | Accused / Outcome / Score | Total Steps | Pre-Terminal (`!done`) Steps | Pre-Terminal Steps with `true_v != known_v` | Unsurfaced Leak Days | `V`-Bearing Responses Verified (`V == known_v`) | Pre-End Truth Leaks |
|---:|---|---|---:|---:|---:|---|---:|---:|
| `6` | `e34` / `e20` | `e34` (`correct=True`, day `6`, `+0.73`) | `57` | `56` | `40` | `[2, 3, 4, 5]` | `7/7` | `0` |
| `26` | `e08` / `e38` | `e04` (`correct=False`, day `10`, `-1.0`, `true_v=0.67`) | `91` | `90` | `49` | `[3, 5, 6, 7, 9]` | `10/10` | `0` |

Exact day-opening `known_v` vs `true_v` gaps verified on `advance_day`:
- **Seed `6`:** day `2` (`0.98` vs `0.93`), day `3` (`0.91` vs `0.86`), day `4` (`0.84` vs `0.79`), day `5` (`0.83` vs `0.73`), day `6` (`0.73` vs `0.73`, all leaks surfaced).
- **Seed `26`:** day `3` (`1.00` vs `0.95`), day `5` (`0.93` vs `0.88`), day `6` (`0.87` vs `0.82`), day `7` (`0.80` vs `0.75`), day `9` (`0.73` vs `0.68`), day `10` (`0.67` vs `0.67`, all leaks surfaced).

### 4.2 WS6 `Game` Init Budget & Pre-End Reveal Invariants

- **Zero auto-`status` budget drain:** `Game(3000)` initializes with `len(g.env.history) == 0` and `g.actions == []`, and stays at `len(g.env.history) == 0` across `spec_json()`, `actions_json()`, and `reveal_json()`; `game/app.js` contains `0` automatic `status` invocations on boot or case open.
- **Pre-end reveal seal & unsurfaced `known_v` parity:** `Game(3000).reveal_json()` returns `{"error": "the episode is not over yet"}` (`0` `mole`, `you`, or `solver` keys) both at initialization and on day `5` when an unsurfaced leak is active (`status` returns `known_v = 0.96` while `true_v = 0.92`).

## 5. Check A3: 6 Planted Pre-End Leak Positive Controls (`6/6` Recall)

Inside `/tmp/opencode/integrity_w5_scratch`, Check A3 verifies `exit 0` on `1/1` clean Arena baseline bundle and `exit 1` on `6/6` (`100%`) single-mutation planted pre-end leaks:

| # | Control ID | Synthetic Surface | Planted Pre-End Leak | Exit Code | Caught |
|---:|---|---|---|---:|---|
| 1 | `planted_step_mole_id` | `docs/arena/replays.json` | Active step (`done: false`) containing `"mole": "e12"` | `1` | PASS |
| 2 | `planted_unsurfaced_true_v` | `docs/arena/hud_state.json` | Active day `2` HUD (`hard:6`, `done: false`) exposing `V: 0.95` (`true_v`) instead of `1.0` (`known_v`) | `1` | PASS |
| 3 | `planted_unsealed_ai_accuse` | `docs/arena/duel_split.json` | Split-screen opponent step exposing `"tool": "accuse", "args": {"employee": "e29"}` while `human_done: false` | `1` | PASS |
| 4 | `planted_pixel_sprite_leak` | `docs/arena/office_frames.js` | `window.ARENA_OFFICE_FRAMES` sprite frame setting `"leaking_sprite_employee": "e29"` while `done: false` | `1` | PASS |
| 5 | `planted_mole_mode_is_canary` | `docs/arena/mole_mode_payload.json` | Mode 3 `be_the_mole` pre-end document payload containing `"is_canary": true` | `1` | PASS |
| 6 | `planted_judge_seed_bundle` | `docs/arena/bundle.js` | `window.ARENA_BUNDLE` shipping `JUDGE_SEEDS` seed `900000` | `1` | PASS |

## 6. Report-Only Maintainer Note for `canary-lead`

- **Python-scope `self.env` attribute in `game/canary_game.py:39` (WS6 `medium` `3000..9999`):** `game/canary_game.py:39` assigns `self.env = Env(TIER, self.seed)` on `Game` instances in Pyodide Python scope (`ws6_self_env_in_python_scope = True`). While normal DOM/JSON methods (`spec_json`, `call_json`, `reveal_json`) never leak hidden truth before `done == True` and `check_seed` blocks all `JUDGE_SEEDS` (`900000..900039`) and `HELDOUT_SEEDS` (`800000..800199`), a player opening browser DevTools on WS6 `medium` public dev seeds `3000..9999` can read `S.game.env._world.mole` directly from the Pyodide interpreter scope. For Canary Arena, `docs/arena/arena_integrity.py` closes this in-scope attribute path by encapsulating the `Env` instance inside a lexical closure rather than exposing `self.env` on the wrapper object. Per file-ownership boundaries, `game/canary_game.py` was not edited.
